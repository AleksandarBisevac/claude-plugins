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

import ast
import hashlib
import io
import json
import os
import posixpath
import re
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
import _loader                                     # noqa: E402  (the entry points that read the full gate)
import _output                                     # noqa: E402  (REPO_ROOT: where the release guard sits)
import _panel_composition                          # noqa: E402  (the panel's reading of the full gate)
import _doctor_trail                               # noqa: E402  (the doctor's full-run check)
import _doctor_report                              # noqa: E402  (the collector that check reports into)
import _json_schema                                # noqa: E402  (the schema reader validate-manifest uses)
import _tree_stamp                                 # noqa: E402  (the digest a binding checks a tested state against)


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

        places = M.record_places(moved, cfg)
        check("ev3p `record_places` is the journal directory and the returns' "
              "folder, each asked of the resolver that owns it rather than "
              "joined here, and `returns_in` is the one definition of the "
              "folder's name under an evidence directory - in either spelling: "
              "%r" % (places,),
              places == [(M.JOURNAL_PLACE, _journal_io.journal_dir(moved, cfg)),
                         (M.RETURNS_PLACE, M.returns_dir(moved, cfg))]
              and M.returns_dir(moved, cfg)
              == M.returns_in(M.evidence_dir(moved, cfg))
              and M.returns_in("a/b", posixpath.join) == "a/b/" + os.path.basename(
                  M.returns_in("x")))

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

        # --- RED-FIRST: a named writer names its own ledger file -------------
        # A SEPARATE PROJECT, not `plain` - every case below this point counts
        # evidence FILES and ROWS in `plain`, and a write here would shift
        # both counts out from under them.
        writer_proj = _project(os.path.join(tmp, "writer"), {})
        with_session = dict(row)
        with_session["runId"] = "R-writer-session"
        p_named = M.append_row(writer_proj, with_session, session_id="sess-9",
                               writer="ci-42")
        check("ev18b RED-FIRST: a writer handed to `append_row` WINS over a "
              "session id - one writer's rows should not be split across "
              "files by which session happened to append them: %r"
              % (os.path.basename(p_named),),
              "ci-42" in os.path.basename(p_named)
              and "sess-9" not in os.path.basename(p_named))

        back = M.read_rows(plain, manifest_path=M.plan_file_of(plain))
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
        torn = M.read_rows(plain, manifest_path=M.plan_file_of(plain))
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
        mid = M.read_rows(mid_proj, manifest_path=M.plan_file_of(mid_proj))
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

        nothing = os.path.join(tmp, "nothing-here")
        empty = M.read_rows(nothing, manifest_path=M.plan_file_of(nothing))
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
        bad_read = M.read_rows(bad_proj, manifest_path=M.plan_file_of(bad_proj))
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
              "FILE's bytes - a reader repairing the file goes to that "
              "position, so it must be the file's own, not a line's: %r "
              "(byte at %d)" % (bad_said, bad_offset),
              "0xff" in bad_said
              and ("in position %d:" % bad_offset) in bad_said)
        uni_proj = _project(os.path.join(tmp, "utf8-non-ascii"), {})
        uni_dir = M.evidence_dir(uni_proj)
        os.makedirs(uni_dir, exist_ok=True)
        with open(os.path.join(uni_dir, "2026-01.uni.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"runId": "U-ćevap — été"}\n')
        uni_read = M.read_rows(uni_proj, manifest_path=M.plan_file_of(uni_proj))
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
        # left byte-for-byte as it was, and `append_row` raises the refusal.
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
                                     writer="w-ap"),):
            try:
                ap_call()
                ap_errors.append(None)
            except Exception as exc:
                ap_errors.append(str(exc))
        with open(ap_path, "rb") as fh:
            ap_after = fh.read()
        check("ap1 RED-FIRST: appending onto a ledger file that is not UTF-8 "
              "is REFUSED - `append_row` raises, naming the file, and not one "
              "byte is written: %r" % (ap_errors,),
              len(ap_errors) == 1 and all(ap_errors)
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
        check("ec7b the unchained-head warning promises no repair that cannot "
              "come: no scope appends a row to a ledger file any more, so it "
              "says the rows stay unchained and does not say a full run "
              "recorded into the file closes the gap: %r"
              % (old_only["warnings"],),
              "closes the gap" not in old_only["warnings"][0]
              and "links onto them" not in old_only["warnings"][0]
              and "stay unchained" in old_only["warnings"][0]
              and "no run appends" in old_only["warnings"][0].lower())

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
            _harness.git(None, "init", "-q", rmp, prefix=("git",))
            for _k, _v in (("user.email", "p@example.com"), ("user.name", "P")):
                _harness.git(None, "-C", rmp, "config", _k, _v, prefix=("git",))
            rpath = M.append_row(rmp, _run("run-1", "passed",
                                           "2026-06-01T10:00:00Z"))
            _harness.git(None, "-C", rmp, "add", "-A", prefix=("git",))
            _harness.git(None, "-C", rmp, "-c", "commit.gpgsign=false",
                         "commit", "-q", "-m", "e", prefix=("git",))
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
            _harness.git(None, "-C", rmp, "checkout", "--", ".",
                         prefix=("git",))
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

        # --- a run id in the trail -----------------------------------------
        # No run is anchored in the trail any more, but a pointer moved and a
        # boundary stamped each name their run there.
        kept_details = _journal_io.normalise_details({"runId": "R1"})
        check("ev23 `runId` SURVIVES `normalise_details`. It has to be on the "
              "allow-list or it is dropped in silence - the failure that "
              "already bit `reason`, where the field was written, discarded, "
              "and believed by everything reading the document instead of the "
              "row: %r" % (kept_details,),
              "runId" in _journal_io.DETAILS_KEYS
              and (kept_details or {}).get("runId") == "R1")
        check("ev22 NOTHING RECORDS A RUN THROUGH A LEDGER ROW ANY MORE: the "
              "module offers no `record` - the full run's record is in the "
              "plan (`write_full_record`), like every other run's: %r"
              % ((hasattr(M, "record"), hasattr(M, "write_full_record")),),
              not hasattr(M, "record") and hasattr(M, "write_full_record"))

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
                _harness.git(None, "init", "-q", root, prefix=("git",))
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
        # The plan-file lock (`SHARD_LOCK`) asked with the pointer's own
        # sentence, as `write_pointer` asks it through `write_plan_file`.
        def pointer_lock_state(project, session_id):
            ask = getattr(M, "shard_lock_state", None)
            if ask is None:
                return "absent", "no shard_lock_state in this build"
            return ask(project, session_id=session_id,
                       outcome=M.RECONCILE_OUTCOME, repair=M.RECONCILE_REPAIR)
        state, _detail = pointer_lock_state(proj, session_id="me")
        check("ed5 with no lock scheme at all the write proceeds under the "
              "weaker guarantee and SAYS which - the panel's documented "
              "fallback, and the same reason: refusing every non-git project "
              "would refuse a case that has an answer: %r" % (state,),
              state == "unlockable")

        gitproj = os.path.join(tmp, "gitptr")
        os.makedirs(gitproj)
        _harness.git(None, "init", "-q", gitproj, prefix=("git",))
        free, _d = pointer_lock_state(gitproj, session_id="me")
        check("ed6 an unheld lock reads FREE - the state a normal standalone run "
              "meets, and the one that must not be confused with the two below",
              free == "free")

        _locks.acquire(gitproj, "index", session="me", out=lambda *_a: None)
        mine, _d = pointer_lock_state(gitproj, session_id="me")
        check("ed7 THE RE-ENTRANCY CASE: a lock held by OUR OWN session reads "
              "`ours`, not `held`. `_locks.acquire` is not re-entrant, so a run "
              "inside its own phase would otherwise be refused by the lock it "
              "already holds - which is every in-phase recording there is: %r"
              % (mine,),
              mine == "ours")

        theirs, detail = pointer_lock_state(gitproj, session_id="someone-else")
        check("ed8 ...and the SAME lock read by a different session is `held`, "
              "with a sentence naming the repair. The pair is the point: either "
              "half alone passes with the identity check deleted: %r"
              % ((theirs, detail),),
              theirs == "held" and "reconcile" in (detail or ""))

        blocked = M.write_pointer(gitproj, mpath, "task",
                                  {"taskId": "P1.1", "phaseId": "P1"}, prow,
                                  session_id="someone-else", wait=0.2)
        check("ed9 THE DESIGNED PARTIAL STATE: a pointer refused by another live "
              "session leaves the LEDGER ROW standing and says so. That is the "
              "only reachable partial write, and it is the harmless one - a run "
              "that happened with nothing yet pointing at it, which `--reconcile` "
              "repairs. The reverse would be a claim with no basis: %r"
              % (blocked.get("reason"),),
              blocked["written"] is False
              and "reconcile" in (blocked.get("reason") or ""))
        _locks.release(gitproj, "index", session="me", out=lambda *_a: None)

        # ONE RULE FOR "IS THIS LOCK OURS", the lock's own. A claim another live
        # process of this session took for its own write is that process's; a
        # pointer written under it with no lock of its own is the lost write the
        # lock serialises every other caller against.
        import platform as _pf
        _pl_path = os.path.join(_locks.lock_dir(gitproj), "index.lock")
        _pl_claim = {"sessionId": "me", "pid": os.getppid(), "hostname": _pf.node(),
                     "note": "another process's write", "token": "tok-elsewhere",
                     "handedOff": False,
                     "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _locks._write_lock(_pl_path, _pl_claim)
        _pl_other, _pl_why = pointer_lock_state(gitproj, session_id="me")
        _locks._write_lock(_pl_path, dict(_pl_claim, handedOff=True))
        _pl_hand, _d = pointer_lock_state(gitproj, session_id="me")
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
        _locks.acquire(held_proj, "index", session="other", out=lambda *_a: None)
        refused = M.write_pointer(held_proj, held_path,
                                  "task", {"taskId": "P1.1", "phaseId": "P1"},
                                  {"runId": "R9", "status": "failed",
                                   "ts": "2026-08-26T12:00:00Z"},
                                  session_id="me", wait=0.2)
        jr2 = [r for r in _journal_io.read_all(held_proj)
               if r.get("action") == "task.testEvidence"]
        check("ed11 THE C4 RULE: a pointer that was REFUSED writes NO "
              "plan-movement row. The chain must never assert a transition "
              "before it exists - and a refused cache write is a designed state "
              "here, so this is the ordinary path and not an error one: "
              "written=%r rows=%r" % (refused["written"], len(jr2)),
              refused["written"] is False and jr2 == [])
        _locks.release(held_proj, "index", session="other", out=lambda *_a: None)

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
            _locks.release(dr_proj, "index", session="me",
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
        best = M.latest_by_subject(M.read_rows(
            orphan, manifest_path=M.plan_file_of(orphan))["rows"])
        check("ed14 a row that names no subject is SKIPPED, never guessed at - "
              "it cannot be pointed at anything, and inventing one would put a "
              "pointer on a task that never ran: %r" % (list(best),),
              best == {})

        held2, held2_path = _manifest_project("recon-held", git=True)
        M.append_row(held2, {"v": 1, "runId": "RH", "ts": "2026-08-26T09:00:00Z",
                             "scope": "task", "taskId": "P1.1", "phaseId": "P1",
                             "status": "failed", "steps": []})
        _locks.acquire(held2, "index", session="other", out=lambda *_a: None)
        blocked_rep = M.reconcile(held2, held2_path, session_id="me", wait=0.2)
        _locks.release(held2, "index", session="other", out=lambda *_a: None)
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
                                          session_id="me", wait=0.2)
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

        # THE PHASE LOCK GUARDS NO WRITE, so it refuses nothing: in the
        # one-file layout the index and the phase body are the same bytes, and
        # every writer of them - the pointer, the record, this stamp, every
        # verb - now takes `index`, which eb15 holds.
        ph_proj, ph_path = _manifest_project("since-phase-held", git=True)
        M.append_row(ph_proj, {"v": 1, "runId": "RL", "ts": "2026-06-02T15:38:00Z",
                               "scope": "task", "taskId": "P1.1",
                               "phaseId": "P1", "status": "passed", "steps": []})
        _locks.acquire(ph_proj, "phase-P1", session="other", out=lambda *_a: None)
        ph_held = M.write_evidence_since(ph_proj, ph_path, "P1", session_id="me",
                                         wait=0.2)
        _locks.release(ph_proj, "phase-P1", session="other", out=lambda *_a: None)
        check("eb16 SECOND DIRECTION: a PHASE lock another session holds does "
              "not refuse the stamp - it is a claim on the phase's run, and the "
              "writer of this file that it once excluded (the pointer) takes "
              "`index` now, as this stamp does: %r"
              % ((ph_held["written"], ph_held.get("reason")),),
              ph_held["written"] is True
              and ph_held["at"] == "2026-06-02T15:38:00Z")

        # THE SECOND DIRECTION, and it is the case that fails when the lock
        # check is tightened until it refuses everything: a lock held by OUR OWN
        # session is the ordinary state of a run a verb launched, and refusing
        # it would refuse every recording made under a verb's hold.
        _locks.acquire(lockproj, "index", session="me", out=lambda *_a: None)
        ours = M.write_evidence_since(lockproj, lockpath, "P1", session_id="me",
                                      wait=0.2)
        _locks.release(lockproj, "index", session="me", out=lambda *_a: None)
        check("eb17 a lock held by THIS session does not refuse the stamp - "
              "`_locks.acquire` is not re-entrant and a run under its own hold "
              "already has the lock, so the holder is compared rather than the "
              "lock re-taken: %r" % ((ours["written"], ours["at"]),),
              ours["written"] is True
              and ours["at"] == "2026-06-02T15:38:00Z")

        _locks.acquire(lockproj, "index", session="other", out=lambda *_a: None)
        _istate, _idetail = M.lock_state(lockproj, "index", "index",
                                         session_id="me",
                                         outcome="OUTCOME-SENTINEL",
                                         repair="REPAIR-SENTINEL")
        _pstate, _pdetail = M.shard_lock_state(
            lockproj, session_id="me", outcome=M.RECONCILE_OUTCOME,
            repair=M.RECONCILE_REPAIR)
        _locks.release(lockproj, "index", session="other", out=lambda *_a: None)
        check("eb18 `lock_state` names the lock it was ASKED about and carries "
              "the CALLER's outcome and repair, in that order, while "
              "`shard_lock_state` produces the pointer's own sentence through "
              "it. Two writers with two repairs: a shared hint would send half "
              "of them to a command that cannot help them: %r / %r"
              % (_idetail, _pdetail),
              _istate == "held" and _pstate == "held"
              and "the index lock is held" in _idetail
              and _idetail.endswith("OUTCOME-SENTINEL; REPAIR-SENTINEL")
              and "the index lock is held" in _pdetail
              and _pdetail.endswith(M.RECONCILE_HINT))

        # `write_pointer`'s rule, one writer over, and with the half that writer
        # cannot show: this block can leave by a refusal made under the lock,
        # so the sentence has to survive a path that returns without the
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
        # The refusal made under the lock is a save that failed: the write is
        # made to raise rather than a filesystem made read-only, which a
        # platform may not honour.
        _dh_real = _locks.release
        _dh_save = M._mio.save_plan_json
        _locks.release = lambda *_a, **_k: _locks.E_LIVE

        def _dh_refuse(*_a, **_k):
            raise OSError("this write is refused by the case")
        M._mio.save_plan_json = _dh_refuse
        try:
            db_no = M.write_evidence_since(dh_proj, dh_path, "P1",
                                           session_id="me")
        finally:
            _locks.release = _dh_real
            M._mio.save_plan_json = _dh_save
            _locks.release(dh_proj, "index", session="me", out=lambda *_a: None)
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
        {"ts": "2026-02-01T00:00:00Z", "runId": "c1", "status": "passed",
         "steps": [{"name": "lint", "exit": 0, "durationMs": 1000}]},
        {"ts": "2026-02-02T00:00:00Z", "runId": "c2", "status": "failed",
         "steps": [{"name": "lint", "exit": 1, "durationMs": 2000}]},
        {"ts": "2026-02-03T00:00:00Z", "runId": "c3", "status": "failed",
         "steps": [{"name": "lint", "exit": 1, "durationMs": 1500}]},
        # A run that came LATER and passed - it must not win `gate_last_caught`,
        # which asks when the gate last CAUGHT something, not when it last ran.
        {"ts": "2026-02-04T00:00:00Z", "runId": "c4", "status": "passed",
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
    _step_mean_cases(check, cost_rows)

    _worktree_ledger_cases(check)
    _merge_ledger_cases(check)
    _chain_order_cases(check)
    _narrowed_shadow_cases(check)
    _selection_miss_row_cases(check)
    _resolve_named_cases(check)
    _pin_suite_cases(check)


def _step_mean_cases(check, cost_rows):
    """(smm) the mean a step's recorded runs took, beside the count it divides
    by - the reading a brief judges a step's duration from, so the count has to
    travel with it: a mean over one run is a different claim from one over many.
    `cost_rows` is the `ev43`-`ev48` fixture: three measured lint runs and a
    fourth that carries no durationMs."""
    def mean(rows, name):
        # Looked up at call time, so a module without it fails each case.
        return _harness.attempt(lambda: M.step_mean_ms(rows, name))
    got = mean(cost_rows, "lint")
    # 1125 is the mean a divisor of EVERY run would give (4500 / 4); the
    # fixture is chosen so that mistake and the right answer disagree.
    check("smm1 step_mean_ms is the mean over the MEASURED runs and their count "
          "- (1500, 3), not 4500 spread over the four runs: %r" % (got,),
          got[0] and got[1] == (1500, 3))
    unmeasured = mean([{"steps": [{"name": "lint", "exit": 0}]}], "lint")
    absent = mean(cost_rows, "selftests")
    check("smm2 ...and None, never a zero mean, for a step whose runs carry no "
          "durationMs and for a step no row names: %r / %r"
          % (unmeasured, absent),
          unmeasured == (True, None) and absent == (True, None))
    single = mean(cost_rows[:1], "lint")
    check("smm3 one measured run is a mean with a count of 1, so the caller "
          "can say it was one: %r" % (single,),
          single[0] and single[1] == (1000, 1))
    # Every step below carries a duration, so only the row's status can tell a
    # run that measured from one that stopped early: the fast could-not-run and
    # cancelled rows and the slow timed-out one would move a mean over all five
    # far from the two verdict rows' 2000.
    stopped = [dict({"steps": [{"name": "lint", "exit": code, "durationMs": ms}]},
                    status=status)
               for status, code, ms in (("passed", 0, 1000), ("failed", 1, 3000),
                                        ("could-not-run", 2, 50),
                                        ("cancelled", 143, 10),
                                        ("timed-out", 124, 90000))]
    verdicts = mean(stopped, "lint")
    none_left = mean(stopped[2:], "lint")
    check("smm4 step_mean_ms counts only the rows whose status is a measured "
          "verdict, passed or failed: (2000, 2) over the two of them, and None "
          "when only could-not-run, cancelled and timed-out rows remain: %r / %r"
          % (verdicts, none_left),
          verdicts == (True, (2000, 2)) and none_left == (True, None))


def _part_repeat_cases(check):
    """(prt) a row whose steps are part repeated: a repeated step is no time
    this run spent and no run of that step, the writer keeps which run it came
    from, and such a row is a source for the steps it measured and for no
    other. The word is spelled as the ledger holds it, as a row on disk is the
    contract."""
    key = "1:sha256:part"
    ids = {"phaseId": "P1"}
    measured = {"runId": "R-measured", "ts": "2026-01-01T00:00:00Z",
                "scope": "phase", "phaseId": "P1", "status": "passed",
                M.REUSE_KEY: key,
                "steps": [{"name": "tree", "exit": 0, "durationMs": 1000},
                          {"name": "plan", "exit": 0, "durationMs": 100}]}
    # The repeated step still carries a duration, as a row a hand or an older
    # writer produced might: the reader must not count it either way.
    part = {"runId": "R-part", "ts": "2026-01-02T00:00:00Z",
            "scope": "phase", "phaseId": "P1", "status": "passed",
            M.REUSE_KEY: key, M.VERDICT_SOURCE: "part-reused",
            "reusedFrom": {"runId": "R-measured"},
            "steps": [{"name": "tree", "exit": 0, "durationMs": 1000,
                       "reusedFrom": {"runId": "R-measured",
                                      "ts": "2026-01-01T00:00:00Z"}},
                      {"name": "plan", "exit": 0, "durationMs": 120}]}
    rows = [measured, part]
    tree_mean = _harness.attempt(lambda: M.gate_mean_ms(rows, ["tree"]))
    plan_mean = _harness.attempt(lambda: M.step_mean_ms(rows, "plan"))
    tally = _harness.attempt(lambda: M.gate_tally(rows, "tree"))
    check("prt1 a repeated step's duration is not time the run that repeated "
          "it spent: the tree step's mean is its one measurement - not the same "
          "figure counted twice - while the plan step, measured by both rows, "
          "is the mean of both; and a repeat is no run of the step in its "
          "tally: %r / %r / %r" % (tree_mean, plan_mean, tally),
          tree_mean == (True, (1000, 1)) and plan_mean == (True, (110, 2))
          and tally == (True, (1, 0)))

    written = _harness.attempt(lambda: M.row_for(
        "/nonexistent-project", {
            "status": "passed", "durationMs": 120,
            M.VERDICT_SOURCE: "part-reused",
            "steps": [{"name": "tree", "exit": 0, "durationMs": 1000,
                       "reusedFrom": {"runId": "R-measured",
                                      "ts": "2026-01-01T00:00:00Z",
                                      "extra": "dropped"}},
                      {"name": "plan", "exit": 0, "durationMs": 120}]},
        "phase", ids, {"runId": "R-new"}))
    steps = (written[1] or {}).get("steps") if written[0] else None
    check("prt2 the writer keeps, step by step, which run a repeated step came "
          "from - and no duration for it, since this run spent none - while a "
          "measured step keeps its own: %r" % (steps,),
          isinstance(steps, list) and len(steps) == 2
          and steps[0].get("reusedFrom") == {"runId": "R-measured",
                                              "ts": "2026-01-01T00:00:00Z"}
          and "durationMs" not in steps[0]
          and steps[1].get("durationMs") == 120
          and "reusedFrom" not in steps[1]
          and (written[1] or {}).get(M.VERDICT_SOURCE) == "part-reused")

    def source(rows_in, steps_in):
        got = _harness.attempt(lambda: M.reusable_run(
            rows_in, "phase", ids, key, frozenset(("passed", "failed")),
            steps=steps_in))
        return got if not got[0] else (True, (got[1] or {}).get("runId"))
    for_tree = source(rows, ["tree"])
    for_plan = source(rows, ["plan"])
    whole = source(rows, None)
    unknown = source(rows, ["lint"])
    check("prt3 a part-repeated row is a source for the steps it MEASURED and "
          "for no other: the tree step it repeated reaches past it to the run "
          "that measured it, the plan step it measured is taken from it, a "
          "whole-run repeat never takes it, and a step no candidate measured "
          "is no repeat at all: tree=%r plan=%r whole=%r unknown=%r"
          % (for_tree, for_plan, whole, unknown),
          for_tree == (True, "R-measured") and for_plan == (True, "R-part")
          and whole == (True, "R-measured") and unknown == (True, None))


def _left_to_phase_gate_cases(check):
    """(ltp) the entries a task's run left to the phase gate cross onto its
    row - name, the arm that proposed it, the setting as its basis and the
    name that matched - and no other field; a run that left nothing
    out writes no key at all, so a row of the old shape is the same bytes.
    The key is spelled as the ledger holds it."""
    left = [{"name": "browser", "arm": "declared",
             "basis": "executor.phaseGateOnly", "matched": "browser.py",
             "extra": "dropped"},
            {"name": "affected/phase-gate: e2e", "arm": "phase-gate",
             "basis": "executor.phaseGateOnly", "matched": "playwright test"}]
    base = {"status": "passed", "durationMs": 5,
            "steps": [{"name": "sweep", "exit": 0, "durationMs": 5}]}
    written = _harness.attempt(lambda: M.row_for(
        "/nonexistent-project", dict(base, leftToPhaseGate=left), "task",
        {"taskId": "P1.1", "phaseId": "P1"}, {"runId": "R-left"}))
    plain = _harness.attempt(lambda: M.row_for(
        "/nonexistent-project", dict(base), "task",
        {"taskId": "P1.1", "phaseId": "P1"}, {"runId": "R-plain"}))
    row = written[1] if written[0] else {}
    check("ltp1 the row lists each entry left to the phase gate with its arm, "
          "the setting as its basis and the matching name, and nothing else; "
          "a run that left nothing out has no such key: %r / %r"
          % (row.get("leftToPhaseGate"),
             sorted(plain[1]) if plain[0] else plain),
          row.get("leftToPhaseGate") == [dict((k, v) for k, v in e.items()
                                              if k != "extra") for e in left]
          and plain[0] and "leftToPhaseGate" not in plain[1])
    reader = getattr(M, "left_to_phase_gate_names", None)
    names = (_harness.attempt(lambda: reader(row)) if reader else None,
             _harness.attempt(lambda: reader({})) if reader else None)
    check("ltp2 the reader the binding asks gives the DECLARED entries a row "
          "left out, never a step another arm proposed, and none for a row "
          "with no key: %r" % (names,),
          names == ((True, ["browser"]), (True, [])))


def _pin_suite_cases(check):
    """(ps) one tracked path for a runner's spelling, and the one own-miss
    reading every third-place reader shares."""
    tmp = _harness.fixture_root("audit-evidence-pin-")
    try:
        tracked = ["pkg1/tests/x.test.js", "pkg2/tests/x.test.js",
                   "backend/tests/test_x.py"]
        listing = {"project": tmp, "tracked": tracked, "listingFailed": None}
        got = [M.pin_suite(s, listing) for s in
               ("tests/x.test.js", "test_x.py", "./backend/tests/test_x.py",
                "../elsewhere.py", "tests/none.py")]
        check("ps1 RED-FIRST: a spelling two tracked siblings end in pins to "
              "NEITHER, naming both; one only one tracked path ends in pins "
              "to it; a normalized root spelling pins to itself; a path "
              "outside the project and a name nothing tracks pin to nothing, "
              "each with its reason: %r" % (got,),
              got[0][0] is None and "pkg1/tests/x.test.js" in got[0][1]
              and "pkg2/tests/x.test.js" in got[0][1]
              and got[1] == ("backend/tests/test_x.py", None)
              and got[2] == ("backend/tests/test_x.py", None)
              and got[3][0] is None and "outside the project" in got[3][1]
              and got[4][0] is None and "no candidate path" in got[4][1])
        unlisted = {"project": tmp, "tracked": None,
                    "listingFailed": "the tracked files could not be listed"}
        os.makedirs(os.path.join(tmp, "tests"))
        with open(os.path.join(tmp, "tests", "on_disk.py"), "w") as fh:
            fh.write("")
        check("ps2 where git cannot list, a spelling on disk from the root "
              "is kept as written and any other is refused NAMING the listing "
              "failure - an unlisted tree is not an empty one",
              M.pin_suite("tests/on_disk.py", unlisted)
              == ("tests/on_disk.py", None)
              and "could not be listed"
              in (M.pin_suite("tests/gone.py", unlisted)[1] or ""))
        check("ps3 same_suite: equal, or pinned to one tracked path - never a "
              "suffix alone, so the relative spelling of pkg1's suite is not "
              "pkg2's",
              M.same_suite("test_x.py", "backend/tests/test_x.py", listing)
              and M.same_suite("tests/x.test.js", "tests/x.test.js", listing)
              and not M.same_suite("tests/x.test.js", "pkg2/tests/x.test.js",
                                   listing))
        row = {"selectionMiss": [{"test": "test_x.py"}, "junk", {}]}
        check("ps4 RED-FIRST: own_miss finds the miss a row recorded under "
              "the runner's spelling for the plan's key, and none for a "
              "suite the row does not list: %r"
              % ((M.own_miss(row, ["backend/tests/test_x.py"], listing),
                  M.own_miss(row, ["pkg1/tests/x.test.js"], listing)),),
              M.own_miss(row, ["backend/tests/test_x.py"], listing)
              == {"test": "test_x.py"}
              and M.own_miss(row, ["pkg1/tests/x.test.js"], listing) is None
              and M.own_miss({}, ["test_x.py"], listing) is None)
        ledger = {"unreadableFiles": [os.path.join(tmp, "docs", "e.jsonl"),
                                      "rel.jsonl"]}
        check("ps5 unreadable_names spells each lost file from the project",
              M.unreadable_names(ledger, tmp) == ["docs/e.jsonl", "rel.jsonl"]
              and M.unreadable_names({}, tmp) == [])
        ok, bad = (M.pin_suites(["test_x.py"], tmp, run=lambda *_a, **_k: (
                       0, "backend/tests/test_x.py\0", "")),
                   M.pin_suites(["test_x.py", "tests/x.test.js"], tmp,
                                run=lambda *_a, **_k: (
                                    0, "\0".join(tracked) + "\0", "")))
        check("ps6 pin_suites pins every suite or none, naming each it could "
              "not: %r" % ((ok, bad),),
              ok == (["backend/tests/test_x.py"], None)
              and bad[0] is None and "tests/x.test.js names each of" in bad[1])
    finally:
        _harness.remove_tree(tmp)


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
    read = M.read_rows(main, manifest_path=M.plan_file_of(main))
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
    check("em12 a run's targets are the readers' keys - `subject_key`, the "
          "gate a reader of its history files it under, and the "
          "`_same_subject` pair, a moved id mapped in both, which also joins "
          "the key `latest_by_subject` files a pointer under (`holder_key`: "
          "the task, for a task's run on its phase's gate) - and nothing when "
          "the plan is unread: %r" % (M.merge_targets(row, {}),),
          M.merge_targets(row, {}) == ("key phase P1",
                                       "pair task=P1.2 phase=P1")
          and M.merge_targets(_em_run("r", stamp, "P1.9"), moved)
          == ("key task P1.2", "pair task=P1.2 phase=P1")
          and M.merge_targets(row, None) == ()
          and M.subject_key(row) == ("phase", "P1")
          and M.holder_key(row) == ("task", "P1.2")
          and M.latest_by_subject([dict(row, ts=stamp)])
          == {("task", "P1.2"): dict(row, ts=stamp)})

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
        _harness.git(root, *args, prefix=git, timeout=30)

    def rev():
        return _harness.git(root, "rev-parse", "HEAD", prefix=git,
                            timeout=30).strip()

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
              "is PROVISIONAL, naming that run AS whole-bearing - the rule "
              "the walk chose it by, not 'measured': %r" % (res_un,),
              res_un["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and res_un["basis"].startswith(
                  "the newest whole-bearing full run (run-unrelated, "))

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

        # --- RED-FIRST: recorded runs are the only source -----------------------
        phase_with_stale_cache = {"id": "P1", "mergedHead": repo["first"],
                                  "fullEvidence": {"status": "whole",
                                                    "runId": "some-old-run"}}
        res_cache = M.full_status([unrelated_row], phase_with_stale_cache,
                                  repo["root"], ["echo x"],
                                  run=_fake_git(
                                      {"merge-base --is-ancestor": (1, "", "")}))
        check("fs11 RED-FIRST: a stale phase.fullEvidence claiming whole is "
              "never consulted - the answer comes from recorded runs alone: %r"
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
              and "never been recorded" not in res_only["basis"]
              and res_only["basis"].startswith(
                  "no whole-bearing full run carries a readable ts"))

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

        # --- append_row: the save boundary scrubs every string ---------------
        sc_proj = _project(os.path.join(tmp, "scrub-proj"))
        sc_home = "/".join(("", "Users", "someone", ".config", "tool"))
        sc_path = M.append_row(sc_proj, {
            "runId": "SC-1", "ts": "2026-01-01T00:00:00Z",
            "basis": "sandbox read %s under %s" % (
                sc_home, os.path.join(sc_proj, "src", "a.py")),
            "nested": {"lines": ["see %s" % sc_home, "plain words, docs/a.md"]}})
        sc_text = open(sc_path, encoding="utf-8").read()
        check("sc1 an evidence row whose composed text names a home path and "
              "the checkout root is stored with neither, in a nested list "
              "too, and the sentence around them survives: %r"
              % (sc_text[:240],),
              "someone" not in sc_text and sc_proj not in sc_text
              and "src/a.py" in sc_text and "plain words, docs/a.md" in sc_text
              and sc_text.count(_journal_io.OUTSIDE_TOKEN) == 2)
        sc_ok = M.append_row(sc_proj, {"runId": "SC-2",
                                       "ts": "2026-01-01T00:00:01Z",
                                       "basis": "ran 5 suites in docs/a.md"})
        # ALLOW twin: a row naming no machine is byte-identical in its text.
        check("sc2 a row without a machine path keeps its words: %r"
              % (open(sc_ok, encoding="utf-8").read()[-160:],),
              "ran 5 suites in docs/a.md" in open(sc_ok,
                                                  encoding="utf-8").read())
        # Only a STEP's command is the plan's gate entry copied; a `command`
        # anywhere else is composed text and is scrubbed like the rest.
        sc_gate = "python3 %s --selftest" % (sc_home,)
        sc_keep = M.append_row(sc_proj, {
            "runId": "SC-3", "ts": "2026-01-01T00:00:02Z",
            "steps": [{"name": "suite", "command": sc_gate}],
            "command": "rerun of %s" % (sc_home,),
            "detail": {"command": "nested %s" % (sc_home,)}})
        sc_rows = [json.loads(line) for line in
                   open(sc_keep, encoding="utf-8").read().splitlines() if line]
        sc_row = [r for r in sc_rows if r.get("runId") == "SC-3"][-1]
        check("sc3 the ledger keeps `steps[i].command` verbatim, so a recorded "
              "run still matches the gate it ran, and scrubs a `command` key "
              "anywhere else - top level or nested - because a name match is "
              "not a copy of the plan: %r" % (sc_row,),
              sc_row["steps"][0]["command"] == sc_gate
              and "someone" not in sc_row["command"]
              and "someone" not in sc_row["detail"]["command"])
    finally:
        _harness.remove_tree(tmp)


def _project_config_cases(check):
    """`project_config_for` with no project named answers the checkout the
    plan is in - never the session's project and never the manifest's own
    directory."""
    base = _harness.fixture_root("evidence-project-config-")
    env_was = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        root = os.path.join(base, "repo")
        os.makedirs(os.path.join(root, ".git"))
        os.makedirs(os.path.join(root, "docs", "audit", ".claude"))
        mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{}")
        os.environ["CLAUDE_PROJECT_DIR"] = os.path.join(base, "elsewhere")
        project, config = M.project_config_for(mpath)
        check("pc1 RED-FIRST: with no project named, the project is the plan's "
              "git toplevel - not CLAUDE_PROJECT_DIR naming another checkout, "
              "not the manifest's own docs/audit, and not a stray .claude/ "
              "there - so the record is <root>/docs/audit/evidence: %r"
              % ((project, M.evidence_dir(project, config)),),
              project == root
              and M.evidence_dir(project, config)
              == os.path.join(root, "docs", "audit", "evidence"))
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        named = os.path.join(base, "named")
        check("pc2 ALLOW: a project named by the caller still wins: %r"
              % (M.project_config_for(mpath, named)[0],),
              M.project_config_for(mpath, named)[0] == named)
    finally:
        if env_was is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = env_was
        _harness.remove_tree(base)


def _moment_reader_cases(check):
    """The window reader and the order reader read one moment, and a run with
    no window is never read as a run that did not happen."""
    # The same instant in three spellings: an offset, a fraction of a second,
    # and the Z form every writer here produces.
    _z = {"runId": "Z", "ts": "2026-09-01T10:10:00Z",
          M.STARTED_KEY: "2026-09-01T10:00:00Z"}
    _off = {"runId": "OFF", "ts": "2026-09-01T12:10:00+02:00",
            M.STARTED_KEY: "2026-09-01T12:00:00+02:00"}
    _frac = {"runId": "FRAC", "ts": "2026-09-01T10:10:00.400Z",
             M.STARTED_KEY: "2026-09-01T10:00:00.400Z"}
    check("mw1 a window stamped with an offset is the SAME window as its Z "
          "spelling, and its ends agree with stamp_moment - the window reader "
          "and the order reader read one moment: %r / %r / %r"
          % (M.window_of(_z)[:2], M.window_of(_off)[:2],
             M.stamp_moment(_off["ts"])),
          M.window_of(_off)[:2] == M.window_of(_z)[:2]
          and M.window_of(_off)[1] == M.stamp_moment(_off["ts"]))
    check("mw2 ...and a fractional stamp names the whole second it fell in, "
          "the unit `overlap_state` reasons in, rather than no window at all: "
          "%r" % (M.window_of(_frac),),
          M.window_of(_frac)[:2] == M.window_of(_z)[:2])
    check("mw3 SECOND DIRECTION: a stamp naming no moment still places a row "
          "in no window - a reader that widened to accept anything would put "
          "it somewhere: %r" % (M.window_of({"runId": "B", "ts": "soon",
                                             "durationMs": 5})[0],),
          M.window_of({"runId": "B", "ts": "soon", "durationMs": 5})[0] is None
          and M.window_of({"runId": "D", "ts": "2026-09-01",
                           "durationMs": 5})[0] is None)

    _mine = {"runId": "MINE", "ts": "2026-09-01T10:10:00Z",
             M.STARTED_KEY: "2026-09-01T10:00:00Z"}
    _blind = {"runId": "BLIND", "ts": "not a moment",
              M.RUNNER_KEY: M.RUNNER_OUTSIDE}
    contesting, basis = M.contested_by([_blind], _mine)
    check("mw4 an outside run with NO window makes contested_by answer "
          "undecided (None), never an empty list - an empty list says this "
          "run was alone, and nothing placed that run anywhere: %r / %r"
          % (contesting, basis),
          contesting is None and "BLIND" in basis)
    verdict = M.attribution_of(_mine, [_blind])
    check("mw5 ...so the verdict is not claimed as this run's own: %r"
          % (verdict,),
          verdict["attributed"] is None and "BLIND" in verdict["basis"])
    check("mw6 ...and the gate-side question reports it as undecided too, "
          "not as solitude: %r"
          % (_ids(M.undecided_neighbours(
              [dict(_blind, **{M.RUNNER_KEY: M.RUNNER_GATE})], _mine,
              M.RUNNER_GATE)),),
          _ids(M.undecided_neighbours(
              [dict(_blind, **{M.RUNNER_KEY: M.RUNNER_GATE})], _mine,
              M.RUNNER_GATE)) == ["BLIND"])
    _far = {"runId": "FAR", "ts": "2026-08-01T10:10:00Z",
            M.STARTED_KEY: "2026-08-01T10:00:00Z",
            M.RUNNER_KEY: M.RUNNER_OUTSIDE}
    contesting, _basis = M.contested_by([_far], _mine)
    check("mw7 SECOND DIRECTION: an outside run with a window a month away "
          "still leaves this run alone - an empty list, not undecided: %r"
          % (contesting,),
          contesting == []
          and M.attribution_of(_mine, [_far])["attributed"] is True)


def _banner_cases(check):
    """The banners a measured run printed, as the row keeps them.

    ABSENT AND EMPTY ARE TWO ANSWERS. A row measured by a build that wrote this
    key and printed nothing holds `[]`; a row from before the key existed holds
    nothing, and a reader that read the second as the first would repeat a
    verdict while saying it had been clean.
    """
    plain = _harness.fixture_root("audit-evidence-banners-")
    base = {"status": "passed", "failed": [], "steps": []}
    ident = {"runId": "R1"}
    named = (M.BANNER_NO_OVERLAP, M.BANNER_TREE_CHANGED)
    with_both = M.row_for(plain, dict(base, banners=list(named)), "phase",
                          {"phaseId": "P1"}, ident)
    with_none = M.row_for(plain, dict(base, banners=[]), "phase",
                          {"phaseId": "P1"}, ident)
    old = M.row_for(plain, dict(base), "phase", {"phaseId": "P1"}, ident)
    invented = M.row_for(plain, dict(base, banners=[M.BANNER_NO_OVERLAP,
                                                    "SENTINEL-INVENTED"]),
                         "phase", {"phaseId": "P1"}, ident)
    check("bn1 row_for carries the banner list a measured run printed: %r"
          % (with_both.get("banners"),),
          M.banners_of(with_both) == list(named))
    check("bn2 ...an EMPTY list is stored as an empty list, the answer 'the "
          "run printed none': %r" % (with_none.get("banners"),),
          with_none.get("banners") == [] and M.banners_of(with_none) == [])
    check("bn3 ...and a row without the key reads as None - 'banners not "
          "recorded' - which is not the empty list: %r"
          % (("banners" in old, M.banners_of(old)),),
          "banners" not in old and M.banners_of(old) is None)
    check("bn4 ...a banner outside the allow-list is dropped, so a caller "
          "cannot widen the row: %r" % (invented.get("banners"),),
          invented.get("banners") == [M.BANNER_NO_OVERLAP])


# --- the runnable full gate, asked of every reader --------------------------------
_RFG_REVIEW = ("review-only: the sign-off reviewer refuses diff prose that "
               "claims more than the code")


def _rfg_plan(fullgate, head, preamble=None, build=None):
    """A plan whose `meta.fullGate` is `fullGate` and whose one phase merged
    at `head` - the fixture every reader below is asked about."""
    meta = {"version": 3,
            "buildCommands": build or {"ok": "true",
                                       "claimsMatchCode": _RFG_REVIEW},
            "fullGate": list(fullgate)}
    if preamble is not None:
        meta["nodePreamble"] = preamble
    return {"meta": meta,
            "phases": [{"id": "P1", "title": "one", "status": "done",
                        "mergedAt": "2026-09-01T00:00:00Z",
                        "mergedHead": head, "tasks": []}]}


def _rfg_project(name, fullgate):
    """`(root, manifest_path, manifest, head)` - a git repository with one
    commit, the phase merged at it, and the plan at the default path the
    release guard reads."""
    root = _harness.fixture_root("evidence-io-rfg-%s-" % (name,))
    _project(root, {"manifestPath": "docs/audit/audit-plan.json"})
    os.makedirs(os.path.join(root, "docs", "audit"))
    git = ("git", "-C", root)
    _harness.git(None, "init", "-q", root, prefix=("git",))
    _harness.git(None, "-c", "user.email=fixture@example.com",
                 "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                 "commit", "-q", "--allow-empty", "-m", "fixture", prefix=git)
    head = _harness.git(None, "rev-parse", "HEAD", prefix=git).strip()
    manifest = _rfg_plan(fullgate, head)
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    return root, mpath, manifest, head


def _rfg_green_row(root, head, commands):
    """One measured, clean, green scope-`full` row carrying `commands` as its
    steps - the shape `run-test-gate.py --full` records for the commands it
    actually ran."""
    row = {"v": M.ROW_VERSION, "runId": "R-rfg", "ts": "2026-09-02T00:00:00Z",
           "scope": M.FULL_SCOPE, "status": M.RUN_PASSED,
           "steps": [{"name": "ok", "command": c, "exit": 0, "durationMs": 5}
                     for c in commands],
           "testedState": {"head": head},
           "observations": {"ranTotal": 1, "countsBasis": "1 check",
                            "dirtyOutside": []}}
    M.append_row(root, row)
    return row


def _rfg_gate(manifest):
    """`full_gate(manifest)`, or - on a tree that has no such function - the
    reading every reader made before it existed: the unfiltered resolution
    of `meta.fullGate`, with nothing named as removed. Asserting against
    that fallback is what makes the cases below fail by assertion there."""
    fg = getattr(M, "full_gate", None)
    if fg is not None:
        return fg(manifest)
    meta = manifest.get("meta") or {}
    return {"commands": M.resolved_commands(manifest, meta.get("fullGate")),
            "reviewOnly": []}


def _runnable_full_gate_cases(check):
    """A review-only entry in `meta.fullGate` is never a command, so no reader
    may count it: a green run of the runnable entries is a whole run, and a
    fullGate holding only review-only entries reads as no runnable full gate -
    the answer a plan naming no fullGate gets - on every surface."""
    whole = _manifest_vocab.FULL_STATUS_WHOLE
    status_mod = _loader.load_script("audit-status.py", "rfg_audit_status")
    report_mod = _loader.load_script("render-report.py", "rfg_render_report")
    gate_mod = _loader.load_script("full-gate.py", "rfg_full_gate")
    guard = _loader.load(os.path.join(_output.REPO_ROOT, ".claude", "hooks",
                                      "guard-release.py"), "rfg_guard_release")

    # --- the one function --------------------------------------------------
    mixed_plan = _rfg_plan(["ok", "claimsMatchCode"], "a" * 40)
    check("rfg1 RED-FIRST: full_gate over [ok, claimsMatchCode] keeps the "
          "runnable entry and names the removed one: %r"
          % (_rfg_gate(mixed_plan),),
          _rfg_gate(mixed_plan) == {"commands": [("ok", "true")],
                                    "reviewOnly": ["claimsMatchCode"]})
    pre_plan = _rfg_plan(["ok", "claimsMatchCode"], "a" * 40, preamble="cd .")
    check("rfg2 RED-FIRST: the review-only rule is judged on the raw "
          "buildCommands value BEFORE the preamble, which still leads the "
          "runnable entry: %r" % (_rfg_gate(pre_plan),),
          _rfg_gate(pre_plan) == {"commands": [("ok", "cd . && true")],
                                  "reviewOnly": ["claimsMatchCode"]})
    key_plan = _rfg_plan(["ok", "claimsMatchCode", "review-only: read it"],
                         "a" * 40, build={"ok": "true",
                                          "claimsMatchCode": "echo prose"})
    check("rfg3 RED-FIRST: a catalog review-only key is review-only whatever "
          "its value says, and a literal `review-only:` entry is too: %r"
          % (_rfg_gate(key_plan),),
          _rfg_gate(key_plan) == {
              "commands": [("ok", "true")],
              "reviewOnly": ["claimsMatchCode", "review-only: read it"]})
    only_plan = _rfg_plan(["claimsMatchCode"], "a" * 40)
    none_plan = {"meta": {"buildCommands": {"ok": "true"}}, "phases": []}
    check("rfg4 RED-FIRST: a fullGate of only review-only entries has no "
          "runnable command, and no fullGate has none either: %r"
          % ((_rfg_gate(only_plan), _rfg_gate(none_plan)),),
          _rfg_gate(only_plan) == {"commands": [],
                                   "reviewOnly": ["claimsMatchCode"]}
          and _rfg_gate(none_plan) == {"commands": [], "reviewOnly": []})

    # --- a green run of the runnable entries is a whole run ------------------
    root, mpath, mixed, head = _rfg_project("mixed", ["ok", "claimsMatchCode"])
    root_o, mpath_o, only, _head_o = _rfg_project("only", ["claimsMatchCode"])
    try:
        # ALLOW first: with NO run recorded the mixed plan really is held,
        # so the cases after it cannot pass on a guard that holds nothing.
        held_none, problem_none = guard.read_held_phases(root)
        check("rfg5 ALLOW: the mixed plan with no full run recorded is held "
              "provisional by the release guard and by audit-status: %r"
              % ((held_none, problem_none),),
              problem_none is None and [h[0] for h in held_none] == ["P1"]
              and status_mod.full_run_block(mixed, mpath, root)["P1"]["answer"]
              == _manifest_vocab.FULL_STATUS_PROVISIONAL)
        row = _rfg_green_row(root, head, ["true"])
        declared = [c for _n, c in _rfg_gate(mixed)["commands"]]
        rows = M.read_rows(root, manifest_path=mpath)["rows"]
        check("rfg6 RED-FIRST: the green [true] run is a whole run for "
              "_full_disqualification and full_status against the runnable "
              "gate: %r" % ((M._full_disqualification(row, declared),
                             M.full_status(rows, mixed["phases"][0], root,
                                           declared)),),
              M._full_disqualification(row, declared) is None
              and M.full_status(rows, mixed["phases"][0], root,
                                declared)["answer"] == whole)
        block = status_mod.full_run_block(mixed, mpath, root)
        check("rfg7 RED-FIRST: audit-status reads the merged phase WHOLE: %r"
              % (block,), (block.get("P1") or {}).get("answer") == whole)
        rblock = report_mod._full_run_block(mixed, mpath, root)
        check("rfg8 RED-FIRST: the report reads the merged phase WHOLE: %r"
              % (rblock,), (rblock.get("P1") or {}).get("answer") == whole)
        rep = _doctor_report.Report()
        _doctor_trail.check_full_run(rep, root, "docs/audit/audit-plan.json",
                                     mixed, root)
        said = [(r["level"], r["detail"]) for r in rep.rows
                if r["check"] == "full run"]
        check("rfg9 RED-FIRST: the doctor's full-run check is one OK row "
              "reading the phase whole: %r" % (said,),
              [lv for lv, _d in said] == ["OK"]
              and "read whole" in said[0][1])
        held, problem = guard.read_held_phases(root)
        check("rfg10 RED-FIRST: the release guard holds nothing over a "
              "whole run of the runnable entries: %r" % ((held, problem),),
              held == [] and problem is None)
        check("rfg11 RED-FIRST: the panel's third-place reading is the "
              "runnable command alone: %r"
              % (_panel_composition.full_gate_commands(mixed),),
              _panel_composition.full_gate_commands(mixed) == ["true"])

        # --- only review-only entries: no runnable full gate, never a red ----
        check("rfg12 RED-FIRST: a fullGate of only review-only entries is no "
              "runnable gate to audit-status, the report and the panel - the "
              "answer no fullGate gets: %r"
              % ((status_mod.full_run_block(only, mpath_o, root_o),
                  report_mod._full_run_block(only, mpath_o, root_o),
                  _panel_composition.full_gate_commands(only)),),
              status_mod.full_run_block(only, mpath_o, root_o) == {}
              and report_mod._full_run_block(only, mpath_o, root_o) == {}
              and _panel_composition.full_gate_commands(only) == [])
        rep_o = _doctor_report.Report()
        _doctor_trail.check_full_run(rep_o, root_o,
                                     "docs/audit/audit-plan.json", only, root_o)
        said_o = [(r["level"], r["detail"]) for r in rep_o.rows
                  if r["check"] == "full run"]
        check("rfg13 RED-FIRST: the doctor says no third place is declared "
              "for it: %r" % (said_o,),
              [lv for lv, _d in said_o] == ["OK"]
              and "no third place declared" in said_o[0][1])
        held_o, problem_o = guard.read_held_phases(root_o)
        check("rfg14 RED-FIRST: the release guard holds nothing over it: %r"
              % ((held_o, problem_o),), held_o == [] and problem_o is None)
        called = []
        real = gate_mod._stream_subprocess
        gate_mod._stream_subprocess = lambda cmd, out: called.append(cmd) or 0
        try:
            lines = []
            code = gate_mod.main([mpath_o], out=lines.append)
        finally:
            gate_mod._stream_subprocess = real
        check("rfg15 RED-FIRST: full-gate.py declares no runnable full gate "
              "for it and exits 0 without invoking the runner, naming the "
              "review-only entry it left out: %r" % ((code, called, lines),),
              code == gate_mod.E_OK and called == []
              and not gate_mod.declares_full_gate(only)
              and gate_mod.declares_full_gate(mixed)
              and any("claimsMatchCode" in ln for ln in lines))
    finally:
        _harness.remove_tree(root)
        _harness.remove_tree(root_o)


def _tree_key_cases(check):
    """The name a measured tree is recorded under has one definition: the gate
    runner writes `testedState.tree.key` with it and the stored-verdict
    comparison reads it back with it. Two spellings held equal by a case agree
    only on what the case happens to try - a realpath policy changed in one
    makes every stored verdict from another tree read as moved."""
    rtg = _loader.load_script("run-test-gate.py", "ev_tree_key_rtg", cache=False)
    check("tk1 run-test-gate names a measured tree through _evidence_io.tree_key "
          "itself, not a copy of it: %r"
          % ((getattr(rtg, "tree_key", None), M.tree_key),),
          getattr(rtg, "tree_key", None) is M.tree_key)

    # The alias above holds one name for one function; this holds the WRITE. A
    # run-test-gate that hashed locally at the write site while keeping the
    # alias would pass tk1 and disagree with every reader, so the key is read
    # back off the record a real `--record --tree` run wrote and compared with the
    # reader's own function over the same directory. A second tree is measured
    # too, each in a project of its own so the second run is measured and not
    # a repeat of the first's verdict.
    #
    # The second tree is reached through a symlink to its real directory, so
    # realpath and abspath of what `--tree` receives differ on every platform:
    # on a plain temp tree they agree wherever the temp root is not itself a
    # link, and a writer hashing abspath would pass there. Where a symlink
    # cannot be made the tree stays plain and tk2l is recorded as a named skip,
    # which is never a proof that the symlink case held.
    keys = []
    shown = []
    linked = None
    link_skip = None
    for name in ("one", "two"):
        project = _harness.fixture_root("ev-tk-project-%s-" % (name,))
        tree = _harness.fixture_root("ev-tk-tree-%s-" % (name,))
        _harness.git(None, "init", "-q", project)
        _harness.git(None, "init", "-q", tree)
        mpath = os.path.join(project, "audit-plan.json")
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2,
                                "buildCommands": {"chk": "true"}},
                       "phases": [{"id": "P1", "title": "p",
                                   "status": "in_progress",
                                   "testGate": ["chk"], "tasks": []}]}, fh)
        real = tree
        if name == "two":
            link = os.path.join(_harness.fixture_root("ev-tk-link-"), "via-link")
            try:
                os.symlink(tree, link, target_is_directory=True)
                tree = link
                linked = (os.path.abspath(link), os.path.realpath(link))
            except (OSError, NotImplementedError, AttributeError) as err:
                link_skip = "%s: %s" % (type(err).__name__, err)
        lines = []
        code = rtg.main([mpath, "P1", "--project-dir", project, "--record",
                         "--tree", tree], out=lines.append)
        # The run's RECORD, read off the plan as written: no row is written
        # beside it, and a fixture repository with no commit gives a record
        # whose `testedState.head` is null, which `read_rows` passes over.
        with open(mpath, encoding="utf-8") as fh:
            record = json.load(fh)["phases"][0].get(M.RECORD_KEY)
        rows = [record] if isinstance(record, dict) else []
        # A record keeps the key flat, under `RECORD_TREE_KEY`, where a row
        # kept it as `tree.key` - the same value either way.
        written = (rows[-1].get("testedState") or {}).get(
            M.RECORD_TREE_KEY) if rows else None
        keys.append(written)
        shown.append((name, code, len(rows), written, M.tree_key(tree)))
        if name == "two" and linked:
            # The symlink-reached tree is named by where it really is, which
            # is what a reader of the same directory through any spelling gets.
            check("tk2l RED-FIRST: a tree passed as a symlink is recorded "
                  "under the hash of its REAL path - not the hash of the "
                  "spelling it was passed as, and the two spellings differ "
                  "here: %r" % ((linked, written),),
                  linked[0] != linked[1]
                  and linked[1] == os.path.realpath(real)
                  and bool(written)
                  and written == M.tree_key(real)
                  and written == hashlib.sha1(linked[1].encode("utf-8")
                                              ).hexdigest()[:12]
                  and written != hashlib.sha1(linked[0].encode("utf-8")
                                              ).hexdigest()[:12])
        check("tk2%s RED-FIRST: the key `run-test-gate --record --tree` wrote "
              "into testedState.tree.key is _evidence_io.tree_key of that "
              "same tree: %r" % (name[0], shown[-1]),
              code == rtg.E_OK and len(rows) == 1
              and bool(written) and written == M.tree_key(tree))
    if link_skip is not None:
        _harness.skip(check, "tk2l",
                      "os.symlink is refused here (%s), so the tree stayed "
                      "plain and no symlink-reached tree was recorded"
                      % (link_skip,), True)
    check("tk3 ALLOW: two different trees were recorded under two different "
          "keys, so the key names the tree and not the run: %r" % (keys,),
          len(keys) == 2 and keys[0] and keys[1] and keys[0] != keys[1])


def _claimed_followers_cases(check):
    """`claimed_followers` is the one reading of which undeclared paths a
    follower owner claims, shared by the integration and the drive."""
    tmp = _harness.fixture_root("audit-evidence-claims-")
    try:
        owner = [o for o in M.FOLLOWER_OWNERS if o.endswith(".py")][0]
        os.makedirs(os.path.join(tmp, *owner.split("/")[:-1]))
        # The owner answers for a path it was not asked about too, and twice
        # for one it was: only the asked paths count, each record once.
        with open(os.path.join(tmp, *owner.split("/")), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write("import json\n"
                     "for rel in ('gen/a.txt', 'gen/a.txt', 'gen/z.txt'):\n"
                     "    print('FOLLOWER-OWED ' + json.dumps({'path': rel,\n"
                     "          'recipe': 'make gen', 'owner': 'gen'}))\n")
        got = M.claimed_followers(tmp, ["gen/a.txt", "notes.txt"])
        check("fc1 an owner's claims are read for the asked paths alone, each "
              "record once, the path it was not asked about left out: %r" % (got,),
              [r.get("path") for r in got] == ["gen/a.txt"]
              and got[0].get("recipe") == "make gen")
        empty = os.path.join(tmp, "no-owner")
        os.makedirs(empty)
        none = M.claimed_followers(empty, ["gen/a.txt"])
        check("fc2 a tree holding no owner claims nothing: %r" % (none,), none == [])
    finally:
        _harness.remove_tree(tmp)


def _gate_reach_row_cases(check):
    """`grr`: the gate's reach, an observation of a task's run, as its row
    keeps it - capped, every path and reason redacted, and written only when
    the run read it, so a row from a run that never asked holds no key that a
    reader could take for "every file reached".

    EVERY FIELD IS BOUNDED, because the row is hash-chained: a gap's suites are
    a path list cut at `MAX_PATHS` with the cut counted, its reason goes
    through the bounded text redactor, and the run's step names are not copied
    a second time - `steps[].name` already holds them."""
    plain = _harness.fixture_root("audit-evidence-reach-")
    base = {"status": "passed", "failed": [], "steps": []}
    ident = {"runId": "R1"}
    ids = {"taskId": "P1.1", "phaseId": "P1"}
    home = os.path.join(plain, "secret-home")
    many = [{"path": "docs/f%d.md" % (i,), "why": "no suite reads it"}
            for i in range(M.MAX_PATHS + 5)]
    reach = {"gate": ["python3 tests/test_m.py"],
             "gaps": [{"path": "CHANGELOG.md",
                       "why": "the listing in %s/x exited 1" % (home,)}] + many}
    try:
        row = M.row_for(plain, dict(base, **{M.GATE_REACH_KEY: reach}), "task",
                        ids, ident)
        kept = row.get(M.GATE_REACH_KEY) or {}
        gaps = kept.get("gaps") or []
        check("grr1 row_for keeps the reach a run read: each gap with its "
              "reason, the first gap first: %r" % (gaps[:1],),
              M.GATE_REACH_KEY == "gateReach"
              and gaps[:1] and gaps[0].get("path") == "CHANGELOG.md"
              and "exited 1" in gaps[0].get("why", ""))
        check("grr2 ...capped at MAX_PATHS gaps, and a reason naming a path "
              "under the project keeps no absolute path: %r"
              % ((len(gaps), gaps[0].get("why")),),
              len(gaps) == M.MAX_PATHS
              and plain not in json.dumps(kept))
        quiet = M.row_for(plain, dict(base, **{M.GATE_REACH_KEY:
                                              {"gate": ["g"], "gaps": []}}),
                          "task", ids, ident)
        check("grr3 an empty gap list is stored as one, the answer 'every "
              "declared file reached': %r" % (quiet.get(M.GATE_REACH_KEY),),
              quiet.get(M.GATE_REACH_KEY) == {"gaps": []})
        old = M.row_for(plain, dict(base), "task", ids, ident)
        check("grr4 SECOND-DIRECTION CASE: a run that read no reach writes "
              "neither key - a row that always carried one could not be told "
              "from a run that asked: %r" % (sorted(old),),
              M.GATE_REACH_KEY not in old
              and M.GATE_REACH_NOT_ASKED_KEY not in old)
        failed = M.row_for(plain, dict(base, **{
            M.GATE_REACH_NOT_ASKED_KEY: "RuntimeError: broke in %s/y" % (home,)}),
            "task", ids, ident)
        said = failed.get(M.GATE_REACH_NOT_ASKED_KEY)
        check("grr5 a reading that failed is kept as the sentence saying why, "
              "redacted, beside no reach key: %r" % ((said, sorted(failed)),),
              M.GATE_REACH_NOT_ASKED_KEY == "gateReachNotAsked"
              and isinstance(said, str) and "broke in" in said
              and plain not in said and M.GATE_REACH_KEY not in failed)

        # A reading the size a wide phase produces: one gap whose derivation
        # selects far more suites than any path list keeps, a reason far past a
        # value's bound, more gaps than a row keeps, and a step-name list that
        # repeats what `steps` already says. Before the bound, the reason joined
        # every suite and the row grew with the phase.
        limit = M._journal_io.MAX_VALUE_CHARS
        wide = ["tests/test_s%03d.py" % (i,) for i in range(M.MAX_PATHS + 25)]
        inside = os.path.join(plain, "tests", "test_inside.py")
        long_reach = {
            "gate": ["step %d" % (i,) for i in range(M.MAX_STEPS)],
            "gaps": [{"path": "CHANGELOG.md", "why": "selects " * 600,
                      "suites": [inside] + wide}]
            + [{"path": "docs/g%d.md" % (i,), "why": "no suite",
                "suites": []} for i in range(M.MAX_PATHS + 3)]}
        big = M.row_for(plain, dict(base, **{M.GATE_REACH_KEY: long_reach}),
                        "task", ids, ident)
        bkept = big.get(M.GATE_REACH_KEY) or {}
        bgaps = bkept.get("gaps") or []
        first = bgaps[0] if bgaps else {}
        check("grr6 a gap's suites are kept as a path list cut at MAX_PATHS "
              "with the cut counted beside it, each one repo-relative, and its "
              "reason is held to a value's bound however long it came in: %r"
              % ((len(first.get("suites") or []), first.get("suitesDropped"),
                  (first.get("suites") or [None])[0],
                  len(first.get("why") or "")),),
              len(first.get("suites") or []) == M.MAX_PATHS
              and first.get("suitesDropped") == 26
              and (first.get("suites") or [None])[0] == "tests/test_inside.py"
              and 0 < len(first.get("why") or "") <= limit
              and all(len(g.get("why") or "") <= limit for g in bgaps))
        check("grr7 ...the gaps past MAX_PATHS are counted rather than "
              "silently cut, and the run's step names are not copied onto the "
              "reach - `steps` already holds them: %r"
              % ((len(bgaps), bkept.get("gapsDropped"), sorted(bkept)),),
              len(bgaps) == M.MAX_PATHS and bkept.get("gapsDropped") == 4
              and sorted(bkept) == ["gaps", "gapsDropped"]
              # Bounded twice is bounded once: the runner bounds the reading
              # for `--json` and `row_for` bounds it again, so a second pass
              # that re-counted a cut or lost one would show here.
              and M.gate_reach_record(plain, bkept) == bkept)
        long_why = M.row_for(plain, dict(base, **{
            M.GATE_REACH_NOT_ASKED_KEY: "RuntimeError: " + "x" * 4000}),
            "task", ids, ident).get(M.GATE_REACH_NOT_ASKED_KEY)
        check("grr8 ...and the sentence saying the reading failed is held to "
              "the same bound: %r" % (len(long_why or ""),),
              isinstance(long_why, str) and 0 < len(long_why) <= limit
              and long_why.startswith("RuntimeError: "))
    finally:
        _harness.remove_tree(plain)


def _joined_step_cases(check):
    """A declared entry and the affected steps run as ONE call are recorded as
    one step whose name is the entry followed by each affected step's name.
    `step_parts` is the one reader of what such a step covers;
    `declared_steps`, `derived_step_suites` and `step_runs_suite` answer for it
    through that reader, and for every older name exactly as before. The names
    are spelled here as a row on disk holds them - the row is the contract."""
    prefix = M.DERIVED_STEP_PREFIX
    parts = getattr(M, "step_parts", None)
    writer = getattr(M, "joined_step_name", None)
    own = "python3 tools/sweep.py tests/test_own.py"
    rel = prefix + "related: tests/test_other.py"
    py = prefix + "python: tests/test_core.py, tests/test_more.py"
    joined = own + " + " + rel + " + " + py
    tail_first = rel + " + " + own
    read = None if parts is None else [
        parts(joined), parts(own), parts(rel), parts(tail_first),
        parts("lint + affected/"), parts(own + " + affected/phase-gate: lint")]
    check("jst1 a joined step's name reads as its declared entry and the "
          "affected steps joined to it, in order; a declared name, a derived "
          "name, a derived name with a command after it, a tail that is no "
          "affected step and a phase-gate tail read as they always did: %r"
          % (read,),
          read == [(own, [rel, py]), (own, []), (None, [rel]),
                   (None, [tail_first]), ("lint + affected/", []),
                   (own + " + affected/phase-gate: lint", [])])
    spelled = writer(own, [rel, py]) if writer else None
    check("jst2 the writer spells the name the reader reads back: %r"
          % (spelled,),
          spelled == joined and parts is not None
          and parts(spelled) == (own, [rel, py]))
    declared = [M.declared_steps([joined]), M.declared_steps([joined, "lint"]),
                M.declared_steps([joined, prefix + "phase-gate: lint"]),
                M.declared_steps([own, rel, py]),
                M.declared_steps([own, rel, "lint"]),
                M.declared_steps([tail_first])]
    check("jst3 declared_steps reads a joined step as its declared entry, and "
          "an older row - declared steps then derived ones, a declared-looking "
          "step after a derived one, a derived step with a command after it - "
          "exactly as before: %r" % (declared,),
          declared == [([own], 0), ([own, "lint"], 0), ([own], 0), ([own], 0),
                       ([own, rel, "lint"], 0), ([], 0)])
    suites = [M.derived_step_suites(joined), M.derived_step_suites(rel),
              M.derived_step_suites(own),
              M.derived_step_suites(prefix + "phase-gate: selftests")]
    check("jst4 derived_step_suites lists every affected suite a joined step "
          "ran, in its name's order, and an older name's as before: %r"
          % (suites,),
          suites == [["tests/test_other.py", "tests/test_core.py",
                      "tests/test_more.py"], ["tests/test_other.py"], [], []])
    runs = [M.step_runs_suite({"name": joined}, s)
            for s in ("tests/test_core.py", "tests/test_other.py",
                      "tests/test_own.py")]
    check("jst5 step_runs_suite knows a joined step ran each affected suite "
          "its name lists, and says nothing of the declared entry's own "
          "suites, as of any declared step: %r" % (runs,),
          runs == [True, True, False])
    pre = getattr(M, "PRE_GATE_STEP", None)
    led = None if pre is None else [
        M.declared_steps([pre, own, rel]), M.declared_steps([pre]),
        M.declared_steps([pre, joined, "lint"])]
    check("pgs1 declared_steps reads a LEADING pre-gate step as no gate "
          "entry, so the declared gate after it is what a row binds: %r"
          % (led,),
          led == [([own], 0), ([], 0), ([own, "lint"], 0)])
    kept = None if pre is None else [
        M.declared_steps([own, pre]), M.declared_steps(["preGate", own]),
        M.declared_steps([pre + " x", own])]
    # The over-fire direction: a reader that dropped the pre-gate's name
    # wherever it stood, or the plan's bare key, passes pgs1 alone.
    check("pgs2 ALLOW: only the reserved name, and only at the head, is "
          "skipped - one after a declared step, the plan's bare key as an "
          "entry, and a name merely opening with the reserved one stay "
          "declared: %r" % (kept,),
          pre is not None
          and kept == [([own, pre], 0), (["preGate", own], 0),
                       ([pre + " x", own], 0)])
    # A GREEN re-gate whose joined step ran without the suite the red-first
    # stage ran beside it keeps that stage step at the head of its steps.
    stage = M.RED_FIRST_STEP_PREFIX + "affected/related: tests/test_other.py"
    leaned = [M.declared_steps([stage, joined]),
              M.declared_steps([pre, stage, joined, "lint"]),
              M.declared_steps([stage, stage + "2", joined])]
    check("pgs3 a green row that keeps the red-first step its joined step "
          "leaned on binds the declared gate after it, with or without a "
          "pre-gate ahead of it: %r" % (leaned,),
          leaned == [([own], 0), ([own, "lint"], 0), ([own], 0)])
    head = "c0ffee12"
    clean = {"head": head, "dirtyDigest": M.CLEAN_DIRTY_DIGEST}
    lists = {"runId": "r-joined", "ts": "2026-11-01T00:00:00Z",
             "testedState": clean, "steps": [{"name": joined, "exit": 0}]}
    found = M.base_run([lists], head, (), [rel], suites=["tests/test_core.py"])
    check("jst6 a base run is found by an affected suite its joined step ran, "
          "under a name the asking run does not carry: %r"
          % ((found or {}).get("runId"),),
          (found or {}).get("runId") == "r-joined")


def _base_scope_cases(check):
    """A run of a task run's red steps at its base: no subject's evidence, and
    found as a base by the suites a derived step ran, not by its name."""
    base_scope = getattr(M, "BASE_SCOPE", None)
    phase_row = {"runId": "r-phase", "ts": "2026-11-01T00:00:00Z",
                 "scope": "phase", "phaseId": "P1"}
    base_row = {"runId": "r-base", "ts": "2026-11-02T00:00:00Z",
                "scope": base_scope, "phaseId": "P1"}
    check("bsc1 a base-scope row is keyed under no subject, even carrying a "
          "phaseId, so the newest phase row stays the phase's: %r"
          % ((base_scope, M.subject_key(base_row)),),
          base_scope is not None and M.subject_key(base_row) is None
          and M.latest_by_subject([phase_row, base_row])
          == {("phase", "P1"): phase_row})
    suites_of = getattr(M, "derived_step_suites", lambda _n: None)
    prefix = M.DERIVED_STEP_PREFIX
    spelled = [suites_of("%spython: tests/a.py, tests/b.py" % (prefix,)),
               suites_of("%sphase-gate: selftests" % (prefix,)),
               suites_of("selftests")]
    check("bsc2 a derived step's name is read for its suites, and the phase-gate "
          "arm and a declared step list none: %r" % (spelled,),
          spelled == [["tests/a.py", "tests/b.py"], [], []])
    head = "c0ffee12"
    clean = {"head": head, "dirtyDigest": M.CLEAN_DIRTY_DIGEST}
    lists = {"runId": "r-lists", "ts": "2026-11-01T00:00:00Z",
             "testedState": clean,
             "steps": [{"name": "%spython: tests/a.py" % (prefix,), "exit": 0}]}
    other = {"runId": "r-other", "ts": "2026-11-03T00:00:00Z",
             "testedState": clean, "steps": [{"name": "lint", "exit": 0}]}
    try:
        found = M.base_run([lists, other], head, (), ["%spython: tests/a.py, "
                                                      "tests/b.py" % (prefix,)],
                           suites=["tests/a.py"])
    except TypeError as exc:
        found = "base_run takes no suites: %s" % (exc,)
    check("bsc3 a base run is found by a suite its derived step's name lists, "
          "under a name the asking run does not carry, and a newer run of no "
          "step over that suite is passed over: %r" % (found,),
          isinstance(found, dict) and found.get("runId") == "r-lists")


# A red task run at `_KB_HEAD` whose one red step names one failing case, and
# the clean-tree run of that step at the same commit a base measurement records.
_KB_HEAD = "c0ffee12ab34"
_KB_SUITE = "tests/test_x.py"


def _kb_step(lines):
    return {"name": "sweep", "exit": 1, "failing": list(lines),
            "failingBasis": "the cases the house harness %s" % (M.NAMED_FAILING,),
            "failingSuites": [_KB_SUITE],
            "failingSuitesBasis": "the 1 suite file(s) the sweep %s"
                                  % (M.NAMED_FAILING,)}


def _kb_red(run_id, ts, head=_KB_HEAD, reading=None):
    row = _lr_row(run_id, ts, steps=[_kb_step(
        ["%s: FAIL x1 the case" % (_KB_SUITE,)])])
    row["testedState"] = dict(row["testedState"], head=head)
    # As `row_for` keeps a reading (`_base_red`): a word with no value is
    # left out, never written null.
    row[M.BASE_RED_KEY] = reading or {"head": head,
                                      "verdict": "no-base", "atBase": [],
                                      "introduced": [], "unknown": [],
                                      "basis": "no run recorded at base"}
    return row


def _kb_base(run_id, of, head=_KB_HEAD):
    return {"v": 1, "runId": run_id, "ts": "2026-11-18T04:30:00Z",
            "scope": M.BASE_SCOPE, "status": "failed", "durationMs": 5000,
            "startedAt": "2026-11-18T04:29:55Z", M.BASE_OF_KEY: of,
            "testedState": {"head": head, "dirtyDigest": M.CLEAN_DIRTY_DIGEST},
            "steps": [_kb_step(["%s: FAIL x1 the case" % (_KB_SUITE,)])]}


def _kept_base_cases(check):
    """(kb) A base measurement is kept in the plan, on the red task's record
    under the reading's own base commit, and read through the one reader as
    its ledger row was - so a later red at the same commit reads it with no
    ledger at all; it is carried while the subject's runs stay at that
    commit and dropped when they move."""
    rtg = _loader.load_script("run-test-gate.py", "rtg_kb")
    tmp = _harness.fixture_root("audit-evidence-kept-base-")
    ids = {"taskId": "P1.1", "phaseId": "P1"}
    keep = getattr(M, "keep_base", None)
    try:
        root, mpath, spath = _lr_project(tmp, "kept")
        red = _kb_red("R1", "2026-11-18T04:04:19Z")
        base = _kb_base("RB", "R1")
        M.write_record(root, mpath, "task", ids, M.run_record(red))
        got = keep(root, mpath, red, base) if keep else {"written": False,
                                                         "reason": "no keep_base"}
        read = M.read_rows(root, manifest_path=mpath)
        found = M.base_run(read["rows"], _KB_HEAD, ["P1.1"], ["sweep"])
        from_plan = rtg.base_red(red["steps"], _KB_HEAD, "P1.1", read["rows"])
        from_row = rtg.base_red(red["steps"], _KB_HEAD, "P1.1", [base])
        sources = [read["rowSources"][i] for i, r in enumerate(read["rows"])
                   if r.get("runId") == "RB"]
        check("kb1 A BASE KEPT ON THE RED'S RECORD IS READ AS ITS ROW WAS: with no "
              "ledger at all, the one reader gives the base run back as a "
              "base-scope row of no subject, and the base reading over it equals "
              "the reading over the ledger row - base-only, naming RB: write %r / "
              "sources %r / plan %r / row %r"
              % (got, sources, from_plan, from_row),
              got.get("written") is True and read.get("ledgerAbsent")
              and sources == [M.ROW_FROM_RECORD]
              and isinstance(found, dict) and found.get("runId") == "RB"
              and found.get("scope") == M.BASE_SCOPE
              and M.subject_key(found) is None
              and found.get(M.BASE_OF_KEY) == "R1"
              and from_plan == from_row and from_row.get("verdict") == "base-only"
              and from_plan.get("run") == "RB")

        # The subject's next red at the same commit replaces the record and
        # keeps the base; one at another commit drops it, as does a green.
        M.write_record(root, mpath, "task", ids, M.run_record(
            _kb_red("R2", "2026-11-18T05:00:00Z")))
        same = [r.get("runId") for r in M.read_rows(
            root, manifest_path=mpath)["rows"] if r.get("scope") == M.BASE_SCOPE]
        M.write_record(root, mpath, "task", ids, M.run_record(
            _kb_red("R3", "2026-11-18T06:00:00Z", head="beefbeef9999")))
        moved = [r.get("runId") for r in M.read_rows(
            root, manifest_path=mpath)["rows"] if r.get("scope") == M.BASE_SCOPE]
        check("kb2 THE KEPT BASE IS CARRIED BY THE COMMIT IT MEASURED: a newer red "
              "of the subject at the same base commit still reads RB, once; a "
              "red at another commit no longer carries it: same %r / moved %r"
              % (same, moved), same == ["RB"] and moved == [])

        red_steps = _kb_red("R4", "2026-11-18T07:00:00Z")["steps"]
        other = dict(red_steps[0], name="lint")
        measured = M.base_unmeasured(red_steps, _KB_HEAD, "P1.1", [base])
        unmeasured = M.base_unmeasured(red_steps + [other], _KB_HEAD, "P1.1",
                                       [base])
        nothing = M.base_unmeasured(red_steps, _KB_HEAD, "P1.1", [])
        own = M.base_unmeasured(red_steps, _KB_HEAD, "P1.1",
                                [dict(base, taskId="P1.1")])
        green = M.base_unmeasured([dict(red_steps[0], exit=0)], _KB_HEAD,
                                  "P1.1", [base])
        check("kb3 WHETHER A RED'S BASE IS MEASURED is read step by step off the "
              "run the base reading reads: none left when the kept run measured "
              "every red step; a red step it never ran is named (the twin); "
              "every red step with no run at that commit, or only the task's "
              "own; and None for a run with nothing red: %r"
              % ((measured, unmeasured, nothing, own, green),),
              measured == [] and unmeasured == ["lint"]
              and nothing == ["sweep"] and own == ["sweep"] and green is None)

        # A base step that reached no verdict measured nothing: timed out, or
        # killed by a signal. The answered base is the twin, still measured.
        silent = [M.base_unmeasured(red_steps, _KB_HEAD, "P1.1", [dict(
            base, steps=[dict(_kb_step([]), **change)])]) for change in (
                {"exit": None, "outcome": "timeout"}, {"exit": -9},
                {"exit": None})]
        answered = M.base_unmeasured(red_steps, _KB_HEAD, "P1.1", [base])
        check("kb4 A BASE STEP COUNTS AS MEASURED ONLY WHEN IT ANSWERED: one that "
              "timed out, was killed by a signal or recorded no exit leaves the "
              "red step unmeasured, so the base is measured again rather than "
              "read as green there; an answered base step still measures it: "
              "%r" % ((silent, answered),),
              silent == [["sweep"], ["sweep"], ["sweep"]] and answered == [])

        # A base of ANOTHER commit is kept on no record, and nothing is written.
        M.write_record(root, mpath, "task", ids, M.run_record(
            _kb_red("R5", "2026-11-18T08:00:00Z")))
        with open(spath, "rb") as fh:
            before = fh.read()
        elsewhere = keep(root, mpath, _kb_red("R5", "2026-11-18T08:00:00Z"),
                         _kb_base("RX", "R5", head="feedface0000")) if keep \
            else {"written": True, "reason": None}
        with open(spath, "rb") as fh:
            after = fh.read()
        check("kb5 keep_base HANDED A BASE OF ANOTHER COMMIT REFUSES: its "
              "sentence names the commit and the run, and the shard's bytes "
              "are what they were: %r" % (elsewhere,),
              elsewhere.get("written") is False
              and "feedface0000" in str(elsewhere.get("reason"))
              and "RX" in str(elsewhere.get("reason")) and before == after)
    except Exception as exc:                                   # noqa: BLE001
        check("kb0 the kept-base block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# A declared step whose base is measured suite by suite: the runner called bare,
# red naming the suites it failed, and the clean-tree runs at `_KB_HEAD` that
# ran that step's spelling over a suite list - each recorded under the base step
# name that carries the declared step and the list (`base_suites_step_name`).
_PS_SWEEP = "python3 tools/sweep.py"
_PS_A, _PS_B, _PS_C = "tests/test_a.py", "tests/test_b.py", "tests/test_c.py"


def _ps_red(suites, basis=None):
    return {"name": _PS_SWEEP, "command": _PS_SWEEP, "exit": 1,
            "failingSuites": list(suites),
            "failingSuitesBasis": basis if basis is not None else
            "the suite files the sweep %s" % (M.NAMED_FAILING,)}


def _ps_base(run_id, suites, ts="2026-11-18T05:00:00Z", head=_KB_HEAD,
             command=None, **step):
    name = (M.base_suites_step_name(_PS_SWEEP, suites)
            if hasattr(M, "base_suites_step_name")
            else "%s + %sbase: %s" % (_PS_SWEEP, M.DERIVED_STEP_PREFIX,
                                      ", ".join(suites)))
    ran = dict({"name": name, "exit": 0, "failingSuites": [],
                "failingSuitesBasis": "the suite files the sweep %s"
                                      % (M.NAMED_FAILING,),
                "command": command if command is not None
                else "%s %s" % (_PS_SWEEP, " ".join(suites))}, **step)
    return {"v": 1, "runId": run_id, "ts": ts, "scope": M.BASE_SCOPE,
            "status": "passed", "durationMs": 900, M.BASE_OF_KEY: "R1",
            "testedState": {"head": head, "dirtyDigest": M.CLEAN_DIRTY_DIGEST},
            "steps": [ran]}


def _per_suite_base_cases(check):
    """(bsu) A declared step measured at its base suite by suite is recorded
    under a base step name carrying the step and the suites it ran, and a
    later red of that step at the same commit is answered suite by suite -
    keyed by commit and suite - by the clean-tree runs that ran each suite. A
    base never answers for a suite it did not run: a suite it left out is
    named unmeasured, so it is measured rather than read as green there. With
    no per-suite base at the commit, or a red naming no suite, the step is
    answered whole, as it always was."""
    try:
        _per_suite_base_body(check)
    except Exception as exc:                                   # noqa: BLE001
        check("bsu0 the per-suite base block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)


def _per_suite_base_body(check):
    name_of = getattr(M, "base_suites_step_name", None)
    parts_of = getattr(M, "base_suites_of", None)
    step_of = getattr(M, "suite_base_step", None)
    run_of = getattr(M, "suite_base_run", None)
    head = _KB_HEAD

    name = name_of(_PS_SWEEP, [_PS_A, _PS_B]) if name_of else None
    parts = parts_of(name) if parts_of and name else None
    twins = ([parts_of(n) for n in (
        _PS_SWEEP, "%spython: %s" % (M.DERIVED_STEP_PREFIX, _PS_A),
        "%s + %spython: %s" % (_PS_SWEEP, M.DERIVED_STEP_PREFIX, _PS_A),
        "%s + %sbase: " % (_PS_SWEEP, M.DERIVED_STEP_PREFIX))]
        if parts_of else None)
    check("bsu1 THE PER-SUITE BASE STEP'S NAME is the declared step, then the "
          "base arm over its suite list, as a row on disk holds it; it reads "
          "back as (step, suites), lists those suites as a derived step's do, "
          "and is known to have run them and no other; a declared name, "
          "another arm, or an empty list reads as none: %r / %r / %r"
          % (name, parts, twins),
          name == "%s + %sbase: %s, %s" % (_PS_SWEEP, M.DERIVED_STEP_PREFIX,
                                           _PS_A, _PS_B)
          and parts == (_PS_SWEEP, [_PS_A, _PS_B])
          and M.derived_step_suites(name) == [_PS_A, _PS_B]
          and M.step_runs_suite({"name": name}, _PS_A)
          and not M.step_runs_suite({"name": name}, _PS_C)
          and twins == [None, None, None, None])

    kept_a = _ps_base("RA", [_PS_A])
    only_b = M.base_unmeasured([_ps_red([_PS_B])], head, "P1.1", [kept_a])
    found_b = run_of([kept_a], head, "P1.1", _ps_red([_PS_B]), _PS_B) \
        if run_of else "no suite_base_run"
    check("bsu2 RED-FIRST: A KEPT BASE THAT RAN ONLY ONE SUITE DOES NOT ANSWER "
          "ANOTHER: a later red of the same step at the same commit naming a "
          "suite that base never ran has that suite named unmeasured, and no "
          "run is found for it - judged by the step's name, it would read as "
          "measured and the suite as green at base: %r / %r"
          % (only_b, found_b),
          only_b == ["%s: %s" % (_PS_SWEEP, _PS_B)] and found_b is None)

    in_a = M.base_unmeasured([_ps_red([_PS_A])], head, "P1.1", [kept_a])
    found_a = run_of([kept_a], head, "P1.1", _ps_red([_PS_A]), _PS_A) \
        if run_of else "no suite_base_run"
    check("bsu3 THE ALLOW TWIN: a kept base that ran a suite answers a later red "
          "in that suite with nothing measured again, and the run found for it "
          "is that base: %r / %r" % (in_a, (found_a or {}).get("runId")
                                     if isinstance(found_a, dict) else found_a),
          in_a == [] and isinstance(found_a, dict)
          and found_a.get("runId") == "RA")

    steps = kept_a["steps"]
    whole = M.base_step(steps, _ps_red([_PS_A]))
    by_suite = [step_of(steps, _ps_red([_PS_A]), s) for s in (_PS_A, _PS_B)] \
        if step_of else None
    check("bsu4 A PER-SUITE BASE STEP NEVER ANSWERS FOR THE WHOLE STEP: the "
          "whole-step reader (`base_step`) finds nothing in it, so a reader "
          "comparing every red suite with one base step cannot charge a suite "
          "that step never ran; read suite by suite it answers the suite it "
          "listed and not the other: %r / %r"
          % (whole, [(s or {}).get("name") for s in by_suite or []]),
          whole is None and isinstance(by_suite, list)
          and by_suite[0] is steps[0] and by_suite[1] is None)

    kept_b = _ps_base("RB", [_PS_B], ts="2026-11-18T06:00:00Z")
    rows = [kept_a, kept_b]
    both = M.base_unmeasured([_ps_red([_PS_A, _PS_B])], head, "P1.1", rows)
    three = M.base_unmeasured([_ps_red([_PS_A, _PS_B, _PS_C])], head, "P1.1",
                              rows)
    elsewhere = M.base_unmeasured([_ps_red([_PS_A])], head, "P1.1",
                                  [_ps_base("RX", [_PS_A], head="feedface0000")])
    own = M.base_unmeasured([_ps_red([_PS_A])], head, "P1.1",
                            [dict(kept_a, taskId="P1.1")])
    dirty = M.base_unmeasured([_ps_red([_PS_A])], head, "P1.1", [dict(
        kept_a, testedState={"head": head, "dirtyDigest": "sha256:other"})])
    # Beside a per-suite base at the commit, the other suite's only run is of
    # another commit, the task's own, or a dirty tree: that suite stays named.
    beside = [M.base_unmeasured([_ps_red([_PS_A, _PS_B])], head, "P1.1",
                                [kept_a, other]) for other in (
        _ps_base("RX", [_PS_B], head="feedface0000"),
        dict(kept_b, taskId="P1.1"),
        dict(kept_b, testedState={"head": head, "dirtyDigest": "sha256:x"}))]
    check("bsu5 KEYED BY COMMIT AND SUITE: two kept bases at one commit, each "
          "over one suite, together answer a red naming both, and a third "
          "suite neither ran is the one named; a base of another commit, the "
          "task's own run, or a dirty tree answers no suite - asked for whole "
          "when it is the only per-suite base, and leaving its suite named "
          "beside one that answers the other: %r"
          % ((both, three, elsewhere, own, dirty, beside),),
          both == [] and three == ["%s: %s" % (_PS_SWEEP, _PS_C)]
          and elsewhere == [_PS_SWEEP] and own == [_PS_SWEEP]
          and dirty == [_PS_SWEEP]
          and beside == [["%s: %s" % (_PS_SWEEP, _PS_B)]] * 3)

    unnamed = M.base_unmeasured([_ps_red([_PS_A], basis="the tail of output")],
                                head, "P1.1", [kept_a])
    cut = M.base_unmeasured([_ps_red([_PS_A], basis="the suite files the sweep "
                                      "%s; %s" % (M.NAMED_FAILING, M.LIST_CUT))],
                            head, "P1.1", [kept_a])
    full = dict(kept_a, runId="RW", ts="2026-11-18T07:00:00Z", steps=[
        {"name": _PS_SWEEP, "command": _PS_SWEEP, "exit": 0}])
    whole_answers = M.base_unmeasured([_ps_red([_PS_B])], head, "P1.1",
                                      [kept_a, full])
    check("bsu6 THE FALLBACK IS THE WHOLE STEP: a red whose runner named no "
          "suite, or whose suites were cut at their bound, is asked for whole "
          "even beside a per-suite base; and a whole-step base answers every "
          "suite of the red, as it always did: %r"
          % ((unnamed, cut, whole_answers),),
          unnamed == [_PS_SWEEP] and cut == [_PS_SWEEP] and whole_answers == [])

    other_runner = M.base_unmeasured([_ps_red([_PS_A])], head, "P1.1", [
        _ps_base("RO", [_PS_A], command="python3 tools/other.py " + _PS_A)])
    with_option = M.base_unmeasured([_ps_red([_PS_A])], head, "P1.1", [
        _ps_base("RO", [_PS_A], command="%s --fast %s" % (_PS_SWEEP, _PS_A))])
    silent = [M.base_unmeasured([_ps_red([_PS_A])], head, "P1.1", [
        _ps_base("RS", [_PS_A], **change)]) for change in (
            {"exit": None, "outcome": "timeout"}, {"exit": -9}, {"exit": None})]
    no_command = M.base_unmeasured([_ps_red([_PS_A])], head, "P1.1", [
        _ps_base("RN", [_PS_A], command="")])
    check("bsu7 A PER-SUITE BASE STEP ANSWERS ONLY AS THE SAME CALL, AND ONLY "
          "WHEN IT ANSWERED: its command with its listed suites taken out must "
          "be the red step's own command, word for word - another runner or "
          "the same one with an option is another check - and one that timed "
          "out, was killed or left no exit measured nothing; a base step "
          "carrying no command is read by its name, as `base_step` reads one: "
          "%r" % ((other_runner, with_option, silent, no_command),),
          other_runner == ["%s: %s" % (_PS_SWEEP, _PS_A)]
          and with_option == ["%s: %s" % (_PS_SWEEP, _PS_A)]
          and silent == [["%s: %s" % (_PS_SWEEP, _PS_A)]] * 3
          and no_command == [])


def _foreground_bound_cases(check):
    """(fb, gm) the Bash tool's foreground bound is one constant, here, and
    every reader of it reads this one; and a gate's recorded mean - what the
    drive weighs against that bound - is its steps' means summed, unmeasured
    while any step is."""
    import ast
    lookup_path = _loader.script_path("audit-lookup.py")
    with open(lookup_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    bound_here = [n.lineno for n in tree.body
                  if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "FOREGROUND_BOUND_MS"
                          for t in n.targets)]
    held = getattr(M, "FOREGROUND_BOUND_MS", None)
    lookup = _loader.load_script("audit-lookup.py", modname="audit_lookup_fb",
                                 cache=False)
    said = None
    if isinstance(held, int):
        # A bound no default would be, so a reader holding its own copy prints
        # its own figure and not this one.
        try:
            M.FOREGROUND_BOUND_MS = 7000
            said = lookup.foreground_bound_line()
        finally:
            M.FOREGROUND_BOUND_MS = held
    check("fb1 the foreground bound is one constant in _evidence_io, audit-lookup "
          "binds none of its own, and the sentence audit-lookup prints follows "
          "this one when it changes: %r" % ((held, bound_here, said),),
          isinstance(held, int) and held > 0 and not bound_here
          and said is not None and "7 s" in said)
    past = getattr(M, "outlives_foreground", None)
    check("fb2 outlives_foreground reads that bound: a mean at it is not past "
          "it, one over it is, and no mean is not: %r"
          % ([past(v) for v in (held, (held or 0) + 1, None)]
             if past and held else None,),
          past is not None and isinstance(held, int)
          and [past(v) for v in (held, held + 1, None)] == [False, True, False])

    def mean(rows, names):
        return _harness.attempt(lambda: M.gate_mean_ms(rows, names))
    rows = [{"status": "passed",
             "steps": [{"name": "lint", "durationMs": 1000},
                       {"name": "unit", "durationMs": 3000}]},
            {"status": "failed",
             "steps": [{"name": "lint", "durationMs": 2000},
                       {"name": "slow", "exit": 0}]}]
    got = mean(rows, ["lint", "unit"])
    # 3000 + 1500 is the sum of the means; 6000 would be the sum of every
    # duration, and a count of 2 the step measured most often.
    check("gm1 gate_mean_ms is the sum of its steps' means beside the fewest "
          "runs any of them was measured over - (4500, 1): %r" % (got,),
          got[0] and got[1] == (4500, 1))
    partial, empty = mean(rows, ["lint", "slow"]), mean(rows, [])
    check("gm2 ...and None while any step has no measured run, and for a gate "
          "of no steps: %r / %r" % (partial, empty),
          partial == (True, None) and empty == (True, None))
    # A cancelled run of the slow step, timed: a mean over every row would give
    # the gate a mean, and a fast one, where none of its runs measured `slow`.
    aborted = rows + [{"status": "cancelled",
                       "steps": [{"name": "slow", "durationMs": 5}]},
                      {"status": "could-not-run",
                       "steps": [{"name": "unit", "durationMs": 1}]}]
    still = mean(aborted, ["lint", "unit"])
    unmeasured = mean(aborted, ["lint", "slow"])
    check("gm3 gate_mean_ms reads only rows whose status is passed or failed: a "
          "cancelled run of a step gives it no mean, and a could-not-run row "
          "moves none - (4500, 1) and None: %r / %r" % (still, unmeasured),
          still == (True, (4500, 1)) and unmeasured == (True, None))


def _selection_time_cases(check):
    """(sel) the time a gate run spent choosing what to run is a key of its own
    beside `durationMs`, never folded into it: the foreground decision, the
    doctor's budget and the usage comparisons all read `durationMs` as the
    steps alone, and a row written before the key existed carries none, which
    is a run whose selection was not measured rather than one that took no
    time.

    The key's spelling has no case of its own: sel3 writes `selectionMs` on a
    result and reads it back off the row under that literal, so a writer that
    spelled the key any other way is red there."""
    read = getattr(M, "selection_ms", None)

    # The two zero-like spellings a reader must keep apart: an absent key, and
    # a recorded zero. A reader using `row.get(key) or 0` passes the first half
    # and fails the second; one using `row.get(key, 0)` fails the first.
    readings = None
    if read is not None:
        readings = [_harness.attempt(lambda r=r: read(r))
                    for r in ({}, {"selectionMs": 0}, {"selectionMs": 250},
                              {"selectionMs": True}, {"selectionMs": -5},
                              {"selectionMs": "250"}, None)]
    check("sel2 a row without the key reads as NOT RECORDED (None), a recorded "
          "zero stays zero, and a bool, a negative or a string is not a "
          "duration: %r" % (readings,),
          readings == [(True, None), (True, 0), (True, 250), (True, None),
                       (True, None), (True, None), (True, None)])

    tmp = _harness.fixture_root("audit-evidence-selection-")
    try:
        proj = _project(os.path.join(tmp, "p"), {})
        base = {"status": "passed", "durationMs": 900, "failed": [],
                "ranTotal": None, "coverageBasis": "c", "treeBasis": "t",
                "treeMutated": [], "overlap": [],
                "steps": [{"name": "unit", "command": "pytest -q", "exit": 0,
                           "ran": None, "durationMs": 900}]}
        ident = {"runId": "S1", "attempt": 1, "via": "orchestrator"}
        timed = dict(base, selectionMs=420)
        new_row = M.row_for(proj, timed, "task", {"taskId": "P1.1",
                                                  "phaseId": "P1"}, ident,
                            published=["pytest -q"])
        old_row = M.row_for(proj, base, "task", {"taskId": "P1.1",
                                                 "phaseId": "P1"},
                            dict(ident, runId="S0"), published=["pytest -q"])
        check("sel3 a result carrying selectionMs puts it on the row, and "
              "durationMs is the steps' figure untouched; a result without it "
              "gets NO key - absent, not a written zero: %r"
              % ((new_row.get("selectionMs"), new_row.get("durationMs"),
                  "selectionMs" in old_row),),
              new_row.get("selectionMs") == 420
              and new_row.get("durationMs") == 900
              and "selectionMs" not in old_row
              and read is not None and read(old_row) is None)
        bad = M.row_for(proj, dict(base, selectionMs=True), "task",
                        {"taskId": "P1.1", "phaseId": "P1"},
                        dict(ident, runId="S2"), published=["pytest -q"])
        check("sel4 ...and a value that is not a duration is not carried: %r"
              % (bad.get("selectionMs"),), "selectionMs" not in bad)

        # ROWS AS THE WRITER BUILDS THEM, each from a result whose selection
        # is far larger than its step, so a writer that folded the selection
        # into a step's duration moves the steps' figures and the mean the
        # foreground decision reads by tens of seconds.
        written = []
        for i, ms in enumerate((1000, 3000)):
            res = dict(base, durationMs=ms, selectionMs=50000,
                       steps=[dict(base["steps"][0], durationMs=ms)])
            written.append(M.row_for(proj, res, "task",
                                     {"taskId": "P1.1", "phaseId": "P1"},
                                     dict(ident, runId="M%d" % i),
                                     published=["pytest -q"]))
        steps_ms = [[s.get("durationMs") for s in r.get("steps") or []]
                    for r in written]
        meaned = _harness.attempt(lambda: M.gate_mean_ms(written, ["unit"]))
        check("sel5 rows written from results carrying a 50 s selection keep "
              "each step's own duration, so gate_mean_ms over them is the steps' "
              "mean - (2000, 2) - with the selection beside it on each row: "
              "%r / %r / %r" % (steps_ms, meaned,
                                [r.get("selectionMs") for r in written]),
              steps_ms == [[1000], [3000]] and meaned == (True, (2000, 2))
              and [r.get("selectionMs") for r in written] == [50000, 50000])

        # The chain: an old-shaped row, then a new one, in one file.
        old_path = M.append_row(proj, M.row_for(
            proj, base, "task", {"taskId": "P1.1", "phaseId": "P1"},
            dict(ident, runId="C0"), published=["pytest -q"]))
        M.append_row(proj, M.row_for(
            proj, timed, "task", {"taskId": "P1.1", "phaseId": "P1"},
            dict(ident, runId="C1"), published=["pytest -q"]))
        with io.open(old_path, encoding="utf-8") as fh:
            written = [json.loads(ln) for ln in fh.read().splitlines()]
        verdict = M.verify(proj)
        check("sel6 the verifier accepts a chain holding a row without the key "
              "and a row with it, and the key was on the row BEFORE it was "
              "hashed - the stored hash is the hash of the row as written: %r"
              % ((verdict.get("ok"), verdict.get("rows"),
                  verdict.get("findings"),
                  [r.get("selectionMs") for r in written]),),
              verdict.get("ok") is True and verdict.get("rows") == 2
              and verdict.get("findings") == []
              and [r.get("selectionMs") for r in written] == [None, 420]
              and written[1]["hash"] == _journal_io.row_hash(written[1]))
        # The pair for sel6: the key is INSIDE the hash, so rewriting it is a
        # finding - a key carried beside the chain would verify either way.
        with io.open(old_path, encoding="utf-8") as fh:
            text = fh.read()
        with io.open(old_path, "w", encoding="utf-8") as fh:
            fh.write(text.replace('"selectionMs":420', '"selectionMs":1'))
        forged = M.verify(proj)
        check("sel7 ...and a rewritten selectionMs breaks the chain: %r"
              % ((forged.get("ok"), len(forged.get("findings") or [])),),
              text.count('"selectionMs":420') == 1
              and forged.get("ok") is False and forged.get("findings"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _lr_project(tmp, name):
    """A fresh sharded project under git, so the phase lock has a scheme: one
    phase, one task, an empty gate."""
    root = os.path.join(tmp, name)
    os.makedirs(os.path.join(root, "docs", "audit", "phases"))
    os.makedirs(os.path.join(root, ".claude"))
    with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    with open(mpath, "w") as fh:
        json.dump({"meta": {"version": 3}, "phases": [
            {"id": "P1", "title": "one", "shard": "phases/P1.json"}]}, fh)
    with open(os.path.join(root, "docs", "audit", "phases", "P1.json"), "w") as fh:
        json.dump({"id": "P1", "title": "one", "status": "in_progress",
                   "testGate": [], "tasks": [{"id": "P1.1", "title": "t",
                                              "status": "in_progress"}]}, fh)
    _harness.git(None, "init", "-q", root, prefix=("git",))
    return root, mpath, os.path.join(root, "docs", "audit", "phases", "P1.json")


def _lr_row(run_id, ts, steps=None, status="failed"):
    """A ledger row as `row_for` shapes one, with the fields a record reads."""
    return {"v": 1, "runId": run_id, "ts": ts, "scope": "task",
            "taskId": "P1.1", "phaseId": "P1", "status": status,
            "durationMs": 8125, "selectionMs": 2300,
            "startedAt": "2026-11-18T04:04:10Z", "failed": ["sweep"],
            "reuseKey": "sha256:key", "gateDigest": "sha256:gate",
            "gateSource": "task",
            "testedState": {"head": "abc123", "dirtyDigest": "sha256:d",
                            "tree": "sha256:t", "scopeDigest": "sha256:s"},
            "banners": [], "steps": steps if steps is not None else [
                {"name": "sweep", "exit": 1, "ran": 3, "measured": "measured",
                 "durationMs": 8000, "outcome": "failed",
                 "failing": ["FAIL x1 the case"], "failingBasis": "named"}]}


def _lr_shard(spath):
    with io.open(spath, encoding="utf-8") as fh:
        return json.load(fh)


# The real `audit-task.py`, run in a process of its own, with two seams the
# test reads and one it drives - never a stand-in that takes a lock by name:
# a file is dropped when the verb ASKS for the index lock and another when the
# lock answered, and with LR_PAUSE set its first write of the shard (made after
# its read, inside its locked section) waits for a `go` file. Patching the
# module attributes reaches every caller, because `_panel_write` and
# `_manifest_io` look both names up on the module at call time.
_LR_VERB_WRAPPER = r'''
import os, runpy, sys, time
sys.path.insert(0, os.environ["LR_SCRIPTS"])
import _output
_output.install_path()
import _locks, _manifest_io
SIG = os.environ["LR_SIGNAL_DIR"]
SHARD = os.path.realpath(os.environ["LR_SHARD"])
PAUSE = os.environ.get("LR_PAUSE") == "1"
def mark(name):
    open(os.path.join(SIG, name), "w").close()
real_acquire = _locks.acquire
def acquire(project, name, *a, **k):
    if name == "index":
        mark("asking")
    code = real_acquire(project, name, *a, **k)
    if name == "index":
        mark("acquired-%s" % (code,))
    return code
_locks.acquire = acquire
real_write = _manifest_io.atomic_write_text
held = []
def write(path, text):
    if PAUSE and not held and os.path.realpath(path) == SHARD:
        held.append(path)
        mark("reached")
        bound = time.time() + 60
        while not os.path.exists(os.path.join(SIG, "go")):
            if time.time() > bound:
                raise SystemExit("the test never let the verb go")
            time.sleep(0.01)
    return real_write(path, text)
_manifest_io.atomic_write_text = write
script = os.environ["LR_AUDIT_TASK"]
sys.argv = [script] + sys.argv[1:]
runpy.run_path(script, run_name="__main__")
'''

# How long a side that must NOT get through is watched for getting through.
# It bounds the observation, not the fix: under the fix the waiting side is
# blocked on the lock and cannot pass however long this is, and it stays well
# inside the lock's own wait so the blocked verb is not refused meanwhile.
_LR_WATCH_SECONDS = 1.5


def _lr_signal(sig, name, seconds=30):
    """Wait for the wrapper's `name` file -> True, or False past the bound."""
    bound = time.monotonic() + seconds
    while time.monotonic() < bound:
        if os.path.exists(os.path.join(sig, name)):
            return True
        time.sleep(0.01)
    return False


def _lr_acquired(sig):
    return [n for n in os.listdir(sig) if n.startswith("acquired-")]


def _lr_verb(tmp, root, spath, sig, pause):
    """Start the real `note` verb on P1.1 -> the Popen. The lock tokens this
    test process carries are dropped from the child's environment: a token
    is what re-enters a claim, and a child holding the recorder's token
    would be let in rather than excluded."""
    wrapper = os.path.join(tmp, "lr-verb-wrapper.py")
    with io.open(wrapper, "w", encoding="utf-8") as fh:
        fh.write(_LR_VERB_WRAPPER)
    env = dict((k, v) for k, v in os.environ.items() if k != _locks.TOKEN_ENV)
    env.update({"LR_SCRIPTS": _output.SCRIPTS_DIR, "LR_SIGNAL_DIR": sig,
                "LR_SHARD": spath, "LR_PAUSE": "1" if pause else "0",
                "LR_AUDIT_TASK": os.path.join(_output.SCRIPTS_DIR, "manifest",
                                              "audit-task.py")})
    return subprocess.Popen(
        [sys.executable, wrapper, "note", "P1.1", "--text", "the verb's write",
         "--project-dir", root], env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)


def _lr_dead_pid():
    """A pid that was this machine's a moment ago and is not now: a child
    started and reaped, so `_locks.judge` reads its claim as gone."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def _lr_outcome(proc, spath, landed, waited, out=b""):
    task = _lr_shard(spath)["tasks"][0]
    return {"verb": proc.returncode, "waited": waited,
            "landed": landed[0] if landed else None,
            "runId": (task.get("lastRun") or {}).get("runId"),
            "pointer": (task.get("testEvidence") or {}).get("runId"),
            "notes": [n.get("text") for n in task.get("notes") or []],
            "verbSaid": out.decode("utf-8", "replace")[-600:]}


def _lr_interleave_verb_first(tmp, name, writer, prepare=None):
    """The verb holds its lock, read done and write not made; `writer(root,
    manifest, shard)` is started then, on a thread. `waited` is that the
    writer had neither returned nor touched the shard by the time the verb was
    let go. `prepare(root, manifest, shard)` runs before the verb starts."""
    import threading
    root, mpath, spath = _lr_project(tmp, name)
    if prepare is not None:
        prepare(root, mpath, spath)
    sig = os.path.join(tmp, name + "-sig")
    os.makedirs(sig)
    proc = _lr_verb(tmp, root, spath, sig, pause=True)
    landed = []
    try:
        if not _lr_signal(sig, "reached"):
            proc.kill()
            out = proc.communicate()[0]
            return _lr_outcome(proc, spath, landed, None, out)
        with io.open(spath, "rb") as fh:
            before = fh.read()
        worker = threading.Thread(target=lambda: landed.append(
            _harness.attempt(lambda: writer(root, mpath, spath))))
        worker.start()
        worker.join(_LR_WATCH_SECONDS)
        with io.open(spath, "rb") as fh:
            untouched = fh.read() == before
        waited = worker.is_alive() and untouched
        open(os.path.join(sig, "go"), "w").close()
        out = proc.communicate(timeout=60)[0]
        worker.join(60)
        return _lr_outcome(proc, spath, landed, waited, out)
    finally:
        open(os.path.join(sig, "go"), "w").close()
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


def _lr_interleave_record_first(tmp, write, ids, rec):
    """The record write holds whatever it takes, read done and write not made;
    the real verb is started then. `waited` is that the verb asked for the
    index lock and had no answer from it while the record was held."""
    import threading
    import _manifest_io
    root, mpath, spath = _lr_project(tmp, "record-first")
    sig = os.path.join(tmp, "record-first-sig")
    os.makedirs(sig)
    target = os.path.realpath(spath)
    reached, go = threading.Event(), threading.Event()
    real_write = _manifest_io.atomic_write_text

    def paused(path, text):
        if (threading.current_thread().name == "lr-recorder"
                and os.path.realpath(path) == target and not reached.is_set()):
            reached.set()
            go.wait(60)
        return real_write(path, text)
    landed = []
    proc = None
    _manifest_io.atomic_write_text = paused
    try:
        worker = threading.Thread(name="lr-recorder", target=lambda: landed.append(
            _harness.attempt(lambda: write(root, mpath, "task", ids, rec,
                                           session_id="recorder", wait=30))))
        worker.start()
        if not reached.wait(30):
            go.set()
            worker.join(60)
            return {"verb": None, "waited": None, "landed": landed[0]
                    if landed else None, "runId": None, "notes": None,
                    "verbSaid": "the record write never reached its write"}
        proc = _lr_verb(tmp, root, spath, sig, pause=False)
        asked = _lr_signal(sig, "asking")
        bound = time.monotonic() + _LR_WATCH_SECONDS
        while time.monotonic() < bound and not _lr_acquired(sig):
            time.sleep(0.01)
        waited = asked and not _lr_acquired(sig)
        if not waited:
            # Whatever the verb got, it is let finish before the record is
            # released, so the order the case is about is the order that ran.
            proc.wait(60)
        go.set()
        worker.join(60)
        out = proc.communicate(timeout=60)[0]
        return _lr_outcome(proc, spath, landed, waited, out)
    finally:
        go.set()
        _manifest_io.atomic_write_text = real_write
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()


# A path of the shape the plan writer's scrubber reads as a home directory
# wherever the suite runs: the sweep points HOME at a scratch directory, so a
# fixture built from the live home would test a different detector arm.
_LR_MACHINE_PATH = "/Users/someone/work/tests/test_x.py"


def _last_run_cases(check):
    """(lr) The newest run of a task or a phase is one record in its shard.

    Every function is reached through `getattr`, so on a build that has none
    of them each case fails as itself rather than the block raising once."""
    tmp = _harness.fixture_root("audit-evidence-lastrun-")
    record_of = getattr(M, "run_record", None)
    write = getattr(M, "write_record", None)
    derive = getattr(M, "pointer_from_record", None)
    try:
        root, mpath, spath = _lr_project(tmp, "ptr")
        ids = {"taskId": "P1.1", "phaseId": "P1"}
        rec = _harness.attempt(lambda: record_of(
            _lr_row("R1", "2026-11-18T04:04:19Z"),
            lines={"machine": "this run had the machine to itself"},
            launch="tok-1"))
        rec = rec[1] if rec[0] else None
        done = _harness.attempt(lambda: write(root, mpath, "task", ids, rec))
        task = _lr_shard(spath)["tasks"][0]
        pointer = _harness.attempt(lambda: derive(task.get("lastRun")))
        check("lr1 a written record lands on the task as `lastRun`, and "
              "`testEvidence` beside it is EXACTLY the pointer derived from it - "
              "three keys, written in the same write: %r"
              % ((done, task.get("testEvidence"), pointer),),
              done[0] and done[1].get("written") is True
              and isinstance(task.get("lastRun"), dict)
              and task["lastRun"].get("runId") == "R1"
              and task["lastRun"].get("launch") == "tok-1"
              and pointer[0] and task.get("testEvidence") == pointer[1]
              and pointer[1] == {"runId": "R1", "status": "failed",
                                 "at": "2026-11-18T04:04:19Z"})
        body = _lr_shard(spath)
        body["tasks"][0].pop("testEvidence", None)
        with io.open(spath, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        rep = M.reconcile(root, mpath)
        task = _lr_shard(spath)["tasks"][0]
        check("lr2 a deleted pointer is restored by reconcile FROM THE RECORD - "
              "this ledger holds no row at all, so the record is the only "
              "source a restored pointer could have come from: %r"
              % ((rep.get("moved"), task.get("testEvidence")),),
              task.get("testEvidence") == {"runId": "R1", "status": "failed",
                                           "at": "2026-11-18T04:04:19Z"}
              and rep.get("moved") == ["task P1.1 -> R1"])
        again = M.reconcile(root, mpath)
        check("lr3 SECOND DIRECTION: a pointer that already equals the record "
              "is left alone and said as already pointing - the case that fails "
              "if every record subject were rewritten on every reconcile: %r"
              % ((again.get("moved"), again.get("already")),),
              again.get("moved") == [] and "task P1.1" in (again.get("already")
                                                           or []))

        # --- a REAL verb's write and a record write, interleaved ----------
        # Both orders, each made deterministic by a barrier rather than a
        # sleep: the side that goes first is stopped between its read and its
        # write until the test says go (`_lr_interleave_verb_first`,
        # `_lr_interleave_record_first`).
        rec2 = dict(rec or {}, runId="R2")
        a = _lr_interleave_verb_first(
            tmp, "verb-first", lambda r, m, _s: write(
                r, m, "task", ids, rec2, session_id="recorder", wait=30))
        check("lr4 A REAL VERB HOLDS ITS LOCKED SECTION, STOPPED BETWEEN ITS "
              "READ AND ITS WRITE, WHILE THE RECORD IS WRITTEN: the record "
              "write is still waiting when the verb is let go (it neither "
              "returned nor touched the shard), and afterwards both writes "
              "are in the shard - the verb's note once and the record: %r"
              % (a,),
              a["verb"] == 0 and a["waited"] is True
              and a["landed"] and a["landed"][0]
              and a["landed"][1].get("written") is True
              and a["runId"] == "R2" and a["notes"] == ["the verb's write"])
        b = _lr_interleave_record_first(tmp, write, ids, dict(rec or {},
                                                              runId="R3"))
        check("lr5 ...AND THE OTHER ORDER: the record write is stopped between "
              "its read and its write while the real verb is started; the verb "
              "asks for the shard's lock and does not get it until the record "
              "is written, and both land - the note is not written back over "
              "by the record's earlier read: %r" % (b,),
              b["verb"] == 0 and b["waited"] is True
              and b["landed"] and b["landed"][0]
              and b["landed"][1].get("written") is True
              and b["runId"] == "R3" and b["notes"] == ["the verb's write"])
        # The pointer and reconcile are the module's other two writers of the
        # shard, met the same way: the verb stopped after its read, the writer
        # started then. A writer that read the shard before its lock writes
        # that read back over the note.
        p = _lr_interleave_verb_first(
            tmp, "pointer-first", lambda r, m, _s: M.write_pointer(
                r, m, "task", ids, _lr_row("R4", "2026-11-18T05:00:00Z"),
                session_id="recorder", wait=30))
        check("lr4p ...THE POINTER'S WRITE, the same way: it waits for the "
              "verb, and both the note and the pointer are in the shard: %r"
              % (p,),
              p["verb"] == 0 and p["waited"] is True
              and p["landed"] and p["landed"][0]
              and p["landed"][1].get("written") is True
              and p["pointer"] == "R4" and p["notes"] == ["the verb's write"])

        def _reconcile_after_record(r, m, s):
            # The record lands first and its pointer is taken off, so the
            # reconcile has a pointer to restore while the verb holds the lock.
            return M.reconcile(r, m, session_id="recorder", wait=30)

        def _prepared(r, m, s):
            write(r, m, "task", ids, dict(rec or {}, runId="R5"))
            body = _lr_shard(s)
            body["tasks"][0].pop("testEvidence", None)
            with io.open(s, "w", encoding="utf-8") as fh:
                json.dump(body, fh)
        c = _lr_interleave_verb_first(tmp, "reconcile-first",
                                      _reconcile_after_record, prepare=_prepared)
        check("lr4r ...AND RECONCILE'S, the same way: the reconcile waits for "
              "the verb, restores the pointer from the record, and the note "
              "stays: %r" % (c,),
              c["verb"] == 0 and c["waited"] is True
              and c["landed"] and c["landed"][0]
              and c["landed"][1].get("moved") == ["task P1.1 -> R5"]
              and c["pointer"] == "R5" and c["runId"] == "R5"
              and c["notes"] == ["the verb's write"])

        # --- a lock held past the wait -----------------------------------
        hroot, hmpath, hspath = _lr_project(tmp, "held")
        _locks.acquire(hroot, "index", session="other", out=lambda *_a: None)
        with io.open(hspath, "rb") as fh:
            held_before = fh.read()
        refused = _harness.attempt(lambda: write(
            hroot, hmpath, "task", ids, rec, session_id="me", wait=0.3))
        with io.open(hspath, "rb") as fh:
            held_after = fh.read()
        _locks.release(hroot, "index", session="other", out=lambda *_a: None)
        why = refused[1].get("reason") or "" if refused[0] else ""
        check("lr6 the plan-file lock (`index`) another live run holds past "
              "the wait refuses the record with a sentence saying what happened "
              "before what to run, and the shard is byte for byte what it was: "
              "%r" % (refused,),
              refused[0] and refused[1].get("written") is False
              and "index lock" in why
              and 0 <= why.find("nothing was written to the plan")
              < why.find("re-run this gate")
              and held_after == held_before)
        proot, pmpath, pspath = _lr_project(tmp, "phase-held")
        _locks.acquire(proot, "phase-P1", session="other", out=lambda *_a: None)
        try:
            through = _harness.attempt(lambda: write(
                proot, pmpath, "task", ids, rec, session_id="me", wait=0.3))
        finally:
            _locks.release(proot, "phase-P1", session="other",
                           out=lambda *_a: None)
        check("lr6b SECOND DIRECTION: a PHASE lock another session holds - a "
              "claim on the phase's run, which no writer of the shard takes "
              "for a write - does not refuse the record: %r" % (through,),
              through[0] and through[1].get("written") is True
              and (_lr_shard(pspath)["tasks"][0].get("lastRun")
                   or {}).get("runId") == "R1")

        # --- a dead holder: what happened, then what to run ---------------
        droot, dmpath, dspath = _lr_project(tmp, "dead-holder")
        import platform as _pf
        dead = _lr_dead_pid()
        os.makedirs(_locks.lock_dir(droot), exist_ok=True)
        _locks._write_lock(os.path.join(_locks.lock_dir(droot), "index.lock"), {
            "sessionId": "gone", "pid": dead, "hostname": _pf.node(),
            "note": "a verb that died", "token": "tok-dead", "handedOff": False,
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        with io.open(dspath, "rb") as fh:
            dead_before = fh.read()
        stale = _harness.attempt(lambda: write(
            droot, dmpath, "task", ids, rec, session_id="me", wait=0.3))
        with io.open(dspath, "rb") as fh:
            dead_after = fh.read()
        said = stale[1].get("reason") or "" if stale[0] else ""
        order = [said.find(s) for s in (
            "looks abandoned", "nothing was written to the plan",
            "audit-lock.py release index --force", "re-run this gate")]
        check("lr6c A DEAD HOLDER of the plan-file lock is not taken over: the "
              "record is refused with the shard untouched, and the sentence says "
              "what happened and then what to run, in that order - abandoned, "
              "nothing written, release it, re-run this gate (pid %s): %r"
              % (dead, (order, said)),
              stale[0] and stale[1].get("written") is False
              and dead_after == dead_before
              and all(i >= 0 for i in order) and order == sorted(order)
              and os.path.exists(os.path.join(_locks.lock_dir(droot),
                                              "index.lock")))

        # --- what the record may hold, and how big it may get ------------
        wide = [{"name": "step-%02d" % (i,), "exit": 1, "ran": 1,
                 "outcome": "failed", "durationMs": 10 + i,
                 "failing": [_LR_MACHINE_PATH + " " + "x" * 900] * 50,
                 "failingBasis": "named", "teardown": "noise"}
                for i in range(M.MAX_STEPS + 9)]
        big = _harness.attempt(lambda: record_of(
            _lr_row("R3", "2026-11-18T04:04:19Z", steps=wide)))
        big = big[1] if big[0] else {}
        size = len(json.dumps(big, sort_keys=True))
        per_step = M.MAX_FAILING * (_journal_io.MAX_VALUE_CHARS + 8) + 600
        bound = M.MAX_STEPS * per_step + 4000
        check("lr7 the record's size is bounded by the gate's width: steps cut "
              "at MAX_STEPS with the cut counted, failing lines per step cut at "
              "MAX_FAILING and each at the journal's value bound, and every "
              "other key a row's step carries kept as the row holds it (the "
              "record carries what a reader of the row reads, "
              "RECORD_NOT_CARRIED) - %d bytes against a bound of %d: "
              "%r" % (size, bound, (len(big.get("steps") or []),
                                    big.get("stepsDropped"))),
              len(big.get("steps") or []) == M.MAX_STEPS
              and big.get("stepsDropped") == 9
              and all(len(s.get("failing") or []) <= M.MAX_FAILING
                      for s in big["steps"])
              and all(len(ln) <= _journal_io.MAX_VALUE_CHARS
                      for s in big["steps"] for ln in s.get("failing") or [])
              and all(s.get("teardown") == "noise" for s in big["steps"])
              and 0 < size <= bound)
        sroot, smpath, sspath = _lr_project(tmp, "scrub")
        raw = dict(rec or {}, runId="R4", steps=[
            {"name": "sweep", "exit": 1, "ran": 3, "outcome": "failed",
             "failing": ["FAIL t1 " + _LR_MACHINE_PATH]}])
        _harness.attempt(lambda: write(sroot, smpath, "task", ids, raw))
        with io.open(sspath, encoding="utf-8") as fh:
            text = fh.read()
        stored = (json.loads(text)["tasks"][0].get("lastRun") or {})
        step = (stored.get("steps") or [{}])[0]
        check("lr8 a machine path in a failing line reads SCRUBBED in the shard, "
              "as every string the shard write passes does, and the verdict "
              "fields beside it are untouched: %r" % ((step, stored.get("status")),),
              stored.get("runId") == "R4"
              and "/Users/someone" not in text
              and bool(step.get("failing"))
              and step.get("exit") == 1 and step.get("outcome") == "failed"
              and stored.get("status") == "failed"
              and stored.get("failed") == ["sweep"])

        # --- one file and per phase; the schema at both levels ------------
        flat = os.path.join(tmp, "flat")
        os.makedirs(os.path.join(flat, ".claude"))
        with open(os.path.join(flat, ".claude", "audit.config.json"), "w") as fh:
            json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
        os.makedirs(os.path.join(flat, "docs", "audit"))
        fpath = os.path.join(flat, "docs", "audit", "audit-plan.json")
        with open(fpath, "w") as fh:
            json.dump({"meta": {"version": 3}, "phases": [
                {"id": "P1", "title": "one", "status": "in_progress",
                 "testGate": [], "tasks": [{"id": "P1.1", "title": "t",
                                            "status": "in_progress"}]}]}, fh)
        _harness.git(None, "init", "-q", flat, prefix=("git",))
        put_task = _harness.attempt(lambda: write(flat, fpath, "task", ids, rec))
        put_phase = _harness.attempt(lambda: write(
            flat, fpath, "phase", {"phaseId": "P1"}, dict(rec or {}, runId="R5")))
        with io.open(fpath, encoding="utf-8") as fh:
            whole = json.load(fh)
        f_phase = whole["phases"][0]
        sharded = _lr_shard(spath)
        import _json_schema
        doc = _json_schema.load_document(os.path.join(
            _output.PLUGIN_ROOT, "schema", "audit-plan.schema.json"))
        verdicts = dict(
            (name, _json_schema.check_findings(doc["$defs"][level], value, doc,
                                               name))
            for name, level, value in (
                ("flat task", "task", f_phase["tasks"][0]),
                ("flat phase", "phase", f_phase),
                ("shard task", "task", sharded["tasks"][0]),
                ("bare task", "task", {"id": "P1.1", "title": "t",
                                       "status": "pending"})))
        bad = _json_schema.check_findings(
            doc["$defs"]["lastRun"], dict(rec or {}, steps="not a list"), doc,
            "lastRun")
        check("lr9 a ONE-FILE plan carries the record on its task and its phase "
              "as a per-phase plan does, and the published schema accepts "
              "`lastRun` on a task and on a phase, in both layouts, with nothing "
              "it left unread - a task without it is accepted unchanged, and a "
              "record whose steps are not a list is refused: %r"
              % ((put_task, put_phase, dict((k, v) for k, v in verdicts.items()),
                  bad[0]),),
              put_task[0] and put_task[1].get("written") is True
              and put_phase[0] and put_phase[1].get("written") is True
              and (f_phase["tasks"][0].get("lastRun") or {}).get("runId") == "R1"
              and (f_phase.get("lastRun") or {}).get("runId") == "R5"
              and f_phase.get("testEvidence", {}).get("runId") == "R5"
              and isinstance(sharded["tasks"][0].get("lastRun"), dict)
              and all(found == [] and not unread
                      for found, unread in verdicts.values())
              and bool(bad[0]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- a repeated verdict's record, and reconcile's pair -------------------------
# Read through `getattr` so a build without the key fails the cases that ask
# for it as themselves, rather than the block raising once.
_RV_UNREAD = getattr(M, "REPEAT_UNREAD_KEY", "repeatedRunUnread")


def _rv_repeat_row(run_id, ts, source_id, source_ts):
    """The ledger row of a WHOLE repeat of `source_id`, as `reused_result` and
    `row_for` shape one: no step ran, no start was measured, `durationMs` is
    the repeat's own (the identity and the lookup)."""
    row = _lr_row(run_id, ts, steps=[])
    row.pop("startedAt", None)
    row.update({"durationMs": 40, "verdictSource": "reused",
                "reusedFrom": {"runId": source_id, "ts": source_ts,
                               "status": "failed"}})
    return row


def _rv_task(spath):
    return _lr_shard(spath)["tasks"][0]


def _rv_steps(record):
    return [(s.get("name"), (s.get("reusedFrom") or {}).get("runId"),
             "durationMs" in s) for s in (record or {}).get("steps") or []]


def _repeat_record_cases(check):
    """(rv) A repeat's record carries the run it repeated - from the record it
    replaces when that is the run, from the ledger row otherwise - or says it
    could not; and reconcile leaves the pointer and the record on one run."""
    tmp = _harness.fixture_root("audit-evidence-repeat-")
    ids = {"taskId": "P1.1", "phaseId": "P1"}
    measured = _lr_row("RM", "2026-11-18T04:04:19Z")
    repeat = _rv_repeat_row("RR", "2026-11-18T05:00:00Z", "RM",
                            "2026-11-18T04:04:19Z")
    other = _lr_row("RX", "2026-11-18T03:00:00Z", steps=[
        {"name": "lint", "exit": 0, "ran": 1, "outcome": "passed",
         "durationMs": 10}], status="passed")
    try:
        # rv1: the run repeated IS the record this write replaces.
        root, mpath, spath = _lr_project(tmp, "in-record")
        M.write_record(root, mpath, "task", ids, M.run_record(measured))
        bare = M.run_record(repeat)
        got = M.write_record(root, mpath, "task", ids, bare)
        # As a reader resolves it: a whole repeat stores its copied steps once,
        # in the run it carries (`resolved_shared`, the rule `record_row` asks).
        rec = M.resolved_shared(_rv_task(spath).get("lastRun") or {})
        check("rv1 SOURCE IN THE REPLACED RECORD: a whole repeat built with no "
              "source carries the steps of the record it replaces - each "
              "naming RM, none keeping a duration of its own - and RM whole "
              "under `repeatedRun`, with the unread marker the bare record "
              "held gone: built=%r stored=%r"
              % (sorted(bare), (_rv_steps(rec), sorted(rec))),
              got.get("written") is True
              and _RV_UNREAD in bare and bare.get("steps") == []
              and _rv_steps(rec) == [("sweep", "RM", False)]
              and rec["steps"][0].get("failing") == ["FAIL x1 the case"]
              and (rec.get(M.REPEATED_RUN_KEY) or {}).get("runId") == "RM"
              and _RV_UNREAD not in rec)
        check("rv1b ...and its moments are the REPEAT's: no `startedAt` (it "
              "measured nothing), `durationMs` its own lookup's, while the run "
              "it repeated keeps its own start and length under "
              "`repeatedRun`: %r"
              % ((rec.get("startedAt"), rec.get("durationMs"),
                  (rec.get(M.REPEATED_RUN_KEY) or {}).get("startedAt"),
                  (rec.get(M.REPEATED_RUN_KEY) or {}).get("durationMs")),),
              "startedAt" not in rec and rec.get("durationMs") == 40
              and (rec.get(M.REPEATED_RUN_KEY) or {}).get("startedAt")
              == "2026-11-18T04:04:10Z"
              and (rec.get(M.REPEATED_RUN_KEY) or {}).get("durationMs") == 8125)

        # rv2: the record replaced is ANOTHER run; the ledger row is the source.
        root2, mpath2, spath2 = _lr_project(tmp, "in-ledger")
        M.write_record(root2, mpath2, "task", ids, M.run_record(other))
        M.write_record(root2, mpath2, "task", ids,
                       M.run_record(repeat, source=measured))
        rec2 = M.resolved_shared(_rv_task(spath2).get("lastRun") or {})
        check("rv2 SOURCE ONLY IN THE LEDGER: the record replaced is another "
              "run (RX), so the steps come from RM's ledger row handed as the "
              "source - RM's step, naming RM, and RM under `repeatedRun`, "
              "never RX's: %r" % ((_rv_steps(rec2), sorted(rec2)),),
              _rv_steps(rec2) == [("sweep", "RM", False)]
              and (rec2.get(M.REPEATED_RUN_KEY) or {}).get("runId") == "RM"
              and _RV_UNREAD not in rec2)

        # rv3: neither holds it.
        root3, mpath3, spath3 = _lr_project(tmp, "neither")
        M.write_record(root3, mpath3, "task", ids, M.run_record(other))
        M.write_record(root3, mpath3, "task", ids, M.run_record(repeat))
        rec3 = _rv_task(spath3).get("lastRun") or {}
        unread = rec3.get(_RV_UNREAD) or {}
        check("rv3 NEITHER HOLDS IT: no source and a replaced record of another "
              "run - the record keeps `steps: []` and SAYS so, naming RM and why, "
              "with no `repeatedRun` and none of RX's steps: %r" % (rec3,),
              rec3.get("steps") == [] and unread.get("runId") == "RM"
              and "RM" in (unread.get("basis") or "")
              and M.REPEATED_RUN_KEY not in rec3
              and rec3.get("verdictSource") == "reused")
        row3 = M.record_row(rec3, "task", "P1.1", "P1")
        check("rv3b ...and the reader of records meets the marker too: the run "
              "read back as its row carries it, so an empty `steps` there is not "
              "a run that ran no step: %r" % (sorted(row3),),
              (row3.get(_RV_UNREAD) or {}).get("runId") == "RM")
        measured_only = M.run_record(measured)
        check("rv3c SECOND DIRECTION: a MEASURED run carries neither key - the "
              "marker is a repeat's alone, and a writer that stamped it on every "
              "record would fail here: %r" % (sorted(measured_only),),
              _RV_UNREAD not in measured_only
              and M.REPEATED_RUN_KEY not in measured_only
              and _rv_steps(measured_only) == [("sweep", None, True)])

        # rv4: reconcile, when the ledger row is the newer run.
        root4, mpath4, spath4 = _lr_project(tmp, "reconcile-row")
        M.write_record(root4, mpath4, "task", ids, M.run_record(other))
        newer = _lr_row("RN", "2026-11-18T06:00:00Z")
        M.append_row(root4, newer)
        rep4 = M.reconcile(root4, mpath4)
        task4 = _rv_task(spath4)
        check("rv4 A LEDGER ROW NEWER THAN THE RECORD (a record write that was "
              "refused): reconcile moves the pointer AND rewrites the record "
              "from that row in one write, so `testEvidence` and `lastRun` "
              "name one run: %r"
              % ((rep4.get("moved"), task4.get("testEvidence"),
                  (task4.get("lastRun") or {}).get("runId")),),
              rep4.get("moved") == ["task P1.1 -> RN"]
              and (task4.get("testEvidence") or {}).get("runId") == "RN"
              and (task4.get("lastRun") or {}).get("runId") == "RN"
              and _rv_steps(task4.get("lastRun")) == [("sweep", None, True)])
        again4 = M.reconcile(root4, mpath4)
        check("rv4b ...and a second reconcile moves nothing: %r"
              % ((again4.get("moved"), again4.get("already")),),
              again4.get("moved") == []
              and again4.get("already") == ["task P1.1"])

        # rv5: the source is held ONLY as the subject's record (a clone whose
        # ledger never had it), the repeat's row is in the ledger and its
        # record write never happened. Reconcile replaces that very record, so
        # a lookup among ledger rows alone wrote the unread marker over the
        # only copy of the run the repeat names.
        root5, mpath5, spath5 = _lr_project(tmp, "reconcile-repeat")
        M.write_record(root5, mpath5, "task", ids, M.run_record(measured))
        M.append_row(root5, repeat)
        rep5 = M.reconcile(root5, mpath5)
        rec5 = M.resolved_shared(_rv_task(spath5).get("lastRun") or {})
        kept5 = M.row_by_run(M.read_rows(root5, manifest_path=mpath5)["rows"],
                             "RM")
        check("rv5 A REPEAT WHOSE SOURCE IS HELD ONLY AS THE RECORD IT REPLACES: "
              "reconcile writes RR's record CARRYING RM - RM's step naming RM, "
              "RM whole under `repeatedRun`, no unread marker - so RM is still "
              "readable after the record that held it is gone: moved=%r "
              "record=%r rm=%r"
              % (rep5.get("moved"), (_rv_steps(rec5), sorted(rec5)),
                 (kept5 or {}).get("runId")),
              rep5.get("moved") == ["task P1.1 -> RR"]
              and rec5.get("runId") == "RR"
              and (rec5.get(M.REPEATED_RUN_KEY) or {}).get("runId") == "RM"
              and _rv_steps(rec5) == [("sweep", "RM", False)]
              and _RV_UNREAD not in rec5
              and (kept5 or {}).get("runId") == "RM")
        root6, mpath6, spath6 = _lr_project(tmp, "write-repeat")
        M.write_record(root6, mpath6, "task", ids, M.run_record(measured))
        M.append_row(root6, repeat)
        M.write_record(root6, mpath6, "task", ids, M.record_carrying(
            root6, repeat, manifest_path=mpath6))
        rec6 = M.resolved_shared(_rv_task(spath6).get("lastRun") or {})
        check("rv5b ...and the record writer, on the same inputs, writes the "
              "same record - the two writers of a record agree on where a "
              "repeat's source is: reconcile=%r writer=%r"
              % (_rv_steps(rec5), _rv_steps(rec6)),
              _rv_steps(rec6) == _rv_steps(rec5) == [("sweep", "RM", False)]
              and (rec6.get(M.REPEATED_RUN_KEY) or {}).get("runId") == "RM")
        import ast
        with io.open(M.__file__, encoding="utf-8") as fh:
            tree5 = ast.parse(fh.read())
        callers5 = sorted(set(top.name for top in tree5.body
                              if isinstance(top, ast.FunctionDef)
                              for node in ast.walk(top)
                              if isinstance(node, ast.Call)
                              and getattr(node.func, "id", None)
                              == "repeat_source"))
        looked5 = sorted(set(top.name for top in tree5.body
                             if isinstance(top, ast.FunctionDef)
                             and top.name != "repeat_source"
                             for node in ast.walk(top)
                             if isinstance(node, ast.Call)
                             and getattr(node.func, "id", None)
                             == "repeat_carried"))
        check("rv5c ONE HELPER FINDS A REPEAT'S SOURCE: `repeat_source` is what "
              "the record writer, its look again under the lock, reconcile and "
              "reconcile's look under the lock all call, and the carrying "
              "itself (`repeat_carried`) is reached from no writer beside it: "
              "callers=%r carriers=%r" % (callers5, looked5),
              set(("record_carrying", "reconcile", "_put_record",
                   "_reconciled")) <= set(callers5)
              and set(looked5) <= set(("run_record", "_put_record",
                                       "_reconciled")))
    finally:
        _harness.remove_tree(tmp)


def _uw_holder(root):
    """A live claim on `index` held by another session: a child that sleeps,
    named as the holder -> (the Popen, for the caller to end, 0 once the claim
    is on disk). The claim is WRITTEN rather than acquired here: an acquire
    from this process records this process's token, and a writer of this
    process would then re-enter the claim as its own."""
    import platform
    child = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(120)"])
    ld = _locks.lock_dir(root)
    os.makedirs(ld, exist_ok=True)
    _locks._write_lock(os.path.join(ld, "index.lock"), {
        "sessionId": "another-session", "pid": child.pid,
        "hostname": platform.node(), "note": "another run",
        "token": "t-another", "handedOff": True, "perCall": False,
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return child, 0 if os.path.exists(os.path.join(ld, "index.lock")) else 1


def _uw_rejudge_cases(check, root, mpath, ids, rec):
    """(uw6, uw7) The dead-holder re-judging after the wait is for a holder the
    wait did not report live, and its answer is used as read: a holder found
    live again is the busy refusal, worded with the re-read's holder; a holder
    live for the whole wait never reaches the re-judging at all. `root` holds a
    live claim another session wrote (`_uw_holder`)."""
    real_state, real_acquire = M.shard_lock_state, M._locks.acquire
    asked = []

    def counted(*args, **kwargs):
        asked.append(True)
        return real_state(*args, **kwargs)
    M.shard_lock_state = counted
    try:
        got = M.write_record(root, mpath, "task", ids, rec, wait=0.2)
    finally:
        M.shard_lock_state = real_state
    check("uw7 A HOLDER LIVE FOR THE WHOLE WAIT NEVER REACHES THE DEAD-HOLDER "
          "RE-JUDGING: the lock's state is asked once, before the wait, and the "
          "refusal is the busy one: %r" % ((len(asked), got.get("reason")),),
          len(asked) == 1 and got.get("written") is False
          and M.index_lock_busy(got.get("reason") or ""))

    answers = [("held", "held by the opening read's holder"),
               ("held", "held by a run that took it during the wait")]

    def scripted(*_args, **_kwargs):
        return answers.pop(0) if answers else ("held", "asked a third time")
    M.shard_lock_state = scripted
    M._locks.acquire = lambda *_a, **_k: M._locks.E_STALE
    try:
        again = M.write_record(root, mpath, "task", ids, rec, wait=0.2)
    finally:
        M.shard_lock_state, M._locks.acquire = real_state, real_acquire
    reason = again.get("reason") or ""
    check("uw6 A HOLDER THE WAIT DID NOT REPORT LIVE, FOUND HELD AGAIN BY THE "
          "RE-READ, IS THE BUSY REFUSAL A CALLER WAITS ON, naming the re-read's "
          "holder - never the stale lock's sentence: %r" % (reason,),
          again.get("written") is False and M.index_lock_busy(reason)
          and "took it during the wait" in reason and answers == [])


def _unwritable_lock_cases(check):
    """(uw) A lock claim that cannot be WRITTEN is said as that, and refuses the
    work, for every writer through `write_plan_file`; a lock that is HELD is
    said as held, and is the one answer the drive waits out."""
    tmp = _harness.fixture_root("audit-evidence-unwritable-")
    ids = {"taskId": "P1.1", "phaseId": "P1"}
    rec = M.run_record(_lr_row("RU", "2026-11-18T04:04:19Z"))
    child = None
    try:
        root, mpath, spath = _lr_project(tmp, "unwritable")
        ld = _locks.lock_dir(root)
        os.makedirs(ld, exist_ok=True)
        with io.open(spath, "rb") as fh:
            before = fh.read()
        os.chmod(ld, 0o500)
        try:
            probe = os.path.join(ld, "probe")
            try:
                open(probe, "w").close()
                os.remove(probe)
                writable = True
            except OSError:
                writable = False
            got = M.write_record(root, mpath, "task", ids, rec, wait=0.2)
        finally:
            os.chmod(ld, 0o700)
        with io.open(spath, "rb") as fh:
            after = fh.read()
        if writable:
            # The precondition this case needs - a directory whose mode refuses
            # this process a write - is MEASURED by the probe write above, the
            # way the product meets it (a write that fails), and the skip is
            # taken on that measurement alone, never on the platform's name: a
            # machine whose probe is refused runs the case below. The Windows
            # runner's probe write succeeded (its run printed this reason under
            # COULD NOT RUN HERE), and so does a superuser's.
            _harness.skip(
                check, "uw1 an unwritable lock directory is refused with its "
                "own sentence", "a write into a directory of mode 0500 "
                "succeeded here (a superuser, or a filesystem that ignores the "
                "mode, as Windows does), so no claim can be made unwritable",
                writable)
        else:
            reason = got.get("reason") or ""
            check("uw1 A CLAIM THAT CANNOT BE WRITTEN HAS ITS OWN SENTENCE: the "
                  "record is refused (the work, not only the lock), the shard "
                  "is byte for byte as it was, and the refusal says the claim "
                  "could not be written and that this is NOT a report the lock "
                  "is held - never 'not free within': %r" % (reason,),
                  got.get("written") is False and after == before
                  and "could not be written" in reason
                  and "not a report that" in reason
                  and "not free within" not in reason
                  and "refuses the LOCK, not the work" not in reason
                  and not M.index_lock_busy(reason))
        root2, mpath2, spath2 = _lr_project(tmp, "held")
        child, code = _uw_holder(root2)
        got2 = M.write_record(root2, mpath2, "task", ids, rec, wait=0.2)
        reason2 = got2.get("reason") or ""
        check("uw2 SECOND DIRECTION: a claim another live run HOLDS is still "
              "said as held - 'not free within' - with none of the unwritable "
              "sentence, and it is the one refusal `index_lock_busy` reads as "
              "busy: %r" % ((code, reason2),),
              code == 0 and got2.get("written") is False
              and "not free within" in reason2
              and "could not be written" not in reason2
              and M.index_lock_busy(reason2)
              and M.index_lock_busy("  pointer:  NOT updated - " + reason2))
        check("uw3 ...and a refusal that names no lock at all (a ledger the run "
              "could not be written to) is not read as a busy lock: %r"
              % (M.index_lock_busy("GATE NOT RECORDED: the gate itself passed, "
                                   "but --record stored no evidence row"),),
              not M.index_lock_busy("GATE NOT RECORDED: the gate itself passed, "
                                    "but --record stored no evidence row"))
        # Asked of the sentence alone, so it runs where uw1 cannot make a
        # directory unwritable: a claim that could not be written tells nothing
        # about a holder, so the sentence may say a holder is not reported and
        # not that none was found.
        alone = M.unwritable_claim_reason(
            ["[audit-lock] cannot write the claim: Permission denied"],
            "nothing was written to the plan", "run it again")
        check("uw4 THE UNWRITABLE-CLAIM SENTENCE SAYS ONLY WHAT WAS ESTABLISHED: "
              "the claim could not be written and whether another run holds the "
              "lock was not established - never that nobody was found holding "
              "it: %r" % (alone,),
              "could not be written" in alone and "Permission denied" in alone
              and "was not established" in alone and "found" not in alone
              and "nobody" not in alone and not M.index_lock_busy(alone))
        # A holder alive when the write began and gone before the wait ends:
        # the lock answers stale, and the refusal is the stale lock's sentence
        # read then, never the busy one the opening read would have given.
        import threading
        root5, mpath5, spath5 = _lr_project(tmp, "dies")
        dying, code5 = _uw_holder(root5)
        # Reaped as well as killed: an unreaped child still answers a signal
        # probe, and would read as live.
        threading.Timer(0.6, lambda: (dying.kill(), dying.wait())).start()
        got5 = M.write_record(root5, mpath5, "task", ids, rec, wait=4)
        dying.wait()
        reason5 = got5.get("reason") or ""
        check("uw5 A HOLDER THAT DIES DURING THE WAIT IS NOT WORDED AS BUSY: the "
              "record is refused, the refusal says the lock looks abandoned and "
              "is not taken over, and neither the busy head nor 'held by another "
              "live run' is in it: %r" % ((code5, got5.get("written"), reason5),),
              code5 == 0 and got5.get("written") is False
              and "looks abandoned" in reason5
              and not M.index_lock_busy(reason5)
              and "held by another live run" not in reason5)
        _uw_rejudge_cases(check, root2, mpath2, ids, rec)
    except Exception as exc:                                   # noqa: BLE001
        check("uw0 the unwritable-lock block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        if child is not None:
            child.kill()
            child.wait()
        _harness.remove_tree(tmp)


# --- a write in the window before a writer's lock ----------------------------
# Each plan writer `_deps.PLAN_WRITERS` names is run here, in this process, as
# its command runs it, with ANOTHER writer's change landed at the moment the
# command first asks for the index lock - from inside the acquire, before the
# real one, so the window is the fixture's and never a sleep's. A writer that
# read the plan before that moment saves its read and the change is gone; one
# that reads behind the lock keeps it. The change is a run record in P1's shard
# (`record`) or a build command in the index (`index`), whichever file the
# writer under test writes.
_PA_RUN = "RW"


def _pa_quiet(*_a, **_k):
    return None


def _pa_index_window(root, mpath):
    at = _loader.load_script("audit-task.py")
    return at.main(["build-command", "pawindow", "--command", "echo window",
                    "--project-dir", root], out=_pa_quiet) == 0


def _pa_record_window(root, mpath):
    return M.write_record(root, mpath, "task", {"taskId": "P1.1",
                                                "phaseId": "P1"},
                          M.run_record(_lr_row(_PA_RUN, "2026-11-19T10:00:00Z")),
                          session_id="pa-window").get("written") is True


_PA_NOTE = "the window's own note"


def _pa_note_window(root, mpath):
    """The real `note` verb on P1.1: a change to the shard in a field no record
    writer touches, so a record writer under test and the window never write
    one value."""
    at = _loader.load_script("audit-task.py")
    return at.main(["note", "P1.1", "--text", _PA_NOTE, "--project-dir", root],
                   out=_pa_quiet) == 0


_PA_WINDOWS = {"index": _pa_index_window, "record": _pa_record_window,
               "note": _pa_note_window}


def _pa_kept(window, mpath, spath):
    """Whether the window's change is still in the plan."""
    if window == "record":
        return (_rv_task(spath).get("lastRun") or {}).get("runId") == _PA_RUN
    if window == "note":
        # Searched in the whole assembled plan: a moved task keeps its notes
        # under its new id.
        return _PA_NOTE in json.dumps(_mio_load(mpath))
    if callable(window):
        return None
    meta = _lr_shard(mpath).get("meta") or {}
    return "pawindow" in (meta.get("buildCommands") or {})


def _pa_run(root, mpath, spath, window, run):
    """`run()` with the window's change landed as the index lock is first
    asked for -> (run's answer, whether the window wrote, whether it is kept).
    `window` names one of `_PA_WINDOWS`, or is a `(root, mpath)` callable whose
    keeping the case judges itself (`kept` is then None)."""
    real = _locks.acquire
    seen = []

    def acquire(project, name, *a, **k):
        if name == M.SHARD_LOCK and not seen:
            # Marked before the write: the window's own writer takes this lock
            # too, and its acquire must reach the real one.
            seen.append(None)
            seen[0] = (window if callable(window)
                       else _PA_WINDOWS[window])(root, mpath)
        return real(project, name, *a, **k)
    _locks.acquire = acquire
    try:
        answer = run()
    finally:
        _locks.acquire = real
    return answer, seen == [True], _pa_kept(window, mpath, spath)


def _pa_project(tmp, name, phase_extra=None, index_extra=None):
    """`_lr_project`, with P1.1 carrying a gate entry and the stub and index
    extended by the case."""
    root, mpath, spath = _lr_project(tmp, name)
    body = _lr_shard(spath)
    body["tasks"][0]["tests"] = {"mode": "gate-only", "add": [],
                                 "gate": ["unit"], "expectRedFirst": False}
    body.update(phase_extra or {})
    with io.open(spath, "w", encoding="utf-8") as fh:
        json.dump(body, fh)
    index = _lr_shard(mpath)
    index["meta"]["buildCommands"] = {"unit": "echo unit"}
    index.update(index_extra or {})
    with io.open(mpath, "w", encoding="utf-8") as fh:
        json.dump(index, fh)
    return root, mpath, spath


def _pa_locked_bodies():
    """`[(line, body called, what encloses it)]` for every call of an
    audit-task `_locked_*` body that is NOT inside an `_under_lock(...)` call
    or another `_locked_*` body, and the order `_under_lock` takes its two
    steps in: (acquire line, body line)."""
    import ast
    path = os.path.join(_output.SCRIPTS_DIR, "manifest", "audit-task.py")
    with io.open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    loose, total = [], 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id.startswith("_locked_")):
            continue
        total += 1
        up = parent.get(node)
        while up is not None:
            if isinstance(up, ast.Call) and getattr(up.func, "id", None) \
                    == "_under_lock":
                break
            if isinstance(up, ast.FunctionDef) and up.name.startswith("_locked_"):
                break
            up = parent.get(up)
        if up is None:
            loose.append((node.lineno, node.func.id))
    door = [top for top in tree.body if isinstance(top, ast.FunctionDef)
            and top.name == "_under_lock"]
    order = (None, None)
    if door:
        takes = [n.lineno for n in ast.walk(door[0]) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", getattr(n.func, "id", None))
                 in ("_acquire_lock", "acquire", "acquire_index_lock")]
        runs = [n.lineno for n in ast.walk(door[0]) if isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "body"]
        order = (min(takes) if takes else None, min(runs) if runs else None)
    return loose, total, order


# The plan reads a door may make before its lock, each read for one question
# the body does not take from it, and why.
_PA_ONE_QUESTION = {
    "_gate_build_keys": "reads only `meta.buildCommands`' key names, to tell "
                        "whether a gate value is keys joined by commas; the body "
                        "reads the plan again under the lock for all it writes",
    "_stale_stub": "asks whether a phase's stub disagrees with its shard, only "
                   "to skip the lock when nothing is owed; `_mirror_locked` "
                   "reads both again under the lock and writes from that read"}
_PA_PLAN_READS = ("load_manifest", "read_json", "load_manifest_at", "_read_json",
                  "stale_stubs")
# The modules whose verbs hand a body to a lock function, and that function.
_PA_DOOR_MODULES = (("manifest/audit-task.py", "_under_lock"),
                    ("git/close-phase.py", "under_index_lock"))
# The writers that take the lock inline - no body handed to a lock function -
# which the door check cannot read, each with what holds it today.
_PA_INLINE_LOCKS = (
    "`_panel_write.apply_composition`, whose first pass reads before the lock by "
    "design and whose second reads again under it (pa11, and lu8 in "
    "tests/test__panel_write.py)",
    "`_proposals.run` (pa8)",
    "`_invariants.write_baseline`, the baseline written under `index` (its own "
    "row's reason; the baseline is not a plan file)")


def _pa_handed_bodies(lock_call, fn):
    """`set(id)` of the nodes a lock call RUNS UNDER THE LOCK: the body of every
    lambda inside its arguments, and the body statements of a def of the door
    handed to it by name. A lambda's defaults, a def's decorators and defaults,
    and every other argument expression - a `functools.partial`'s bound
    arguments among them - are evaluated in the door, before the lock."""
    import ast
    locked = set()
    for node in ast.walk(lock_call):
        if isinstance(node, ast.Lambda):
            locked |= set(id(n) for n in ast.walk(node.body))
    handed = set(a.id for a in list(lock_call.args)
                 + [k.value for k in lock_call.keywords]
                 if isinstance(a, ast.Name))
    for sub in ast.walk(fn):
        if isinstance(sub, ast.FunctionDef) and sub.name in handed:
            for stmt in sub.body:
                locked |= set(id(n) for n in ast.walk(stmt))
    return locked


def _pa_door_reads(modules=None):
    """`(doors, readers, [(door, line, what)])` over the door modules: every DOOR
    (a top-level function calling its module's lock function), every READER (a
    function whose own calls reach `_manifest_io`'s plan reads, followed through
    the module's own functions to a fixpoint), and each door that reads the plan
    outside what runs under the lock (`_pa_handed_bodies`) or declares a
    `global`, and each locked body declaring one - the ways a body could be
    handed a read taken outside the lock. Another door it calls is judged as a
    door itself. A plan read is a call of `_manifest_io`'s readers
    (`_PA_PLAN_READS`), so a door opening the plan's path itself - a bare
    `json.load(open(...))` - is not read as one, and this check passes it."""
    import ast
    doors_all, readers_all, found = [], set(), []
    for rel, lock_fn in modules or _PA_DOOR_MODULES:
        path = rel if os.path.isabs(rel) else os.path.join(_output.SCRIPTS_DIR,
                                                           *rel.split("/"))
        with io.open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        defs = dict((n.name, n) for n in tree.body if isinstance(n, ast.FunctionDef))
        doors = sorted(n for n, fn in defs.items() if n != lock_fn
                       and any(getattr(c.func, "id", None) == lock_fn
                               for c in _pa_calls(fn)))
        readers, grew = set(), True
        while grew:
            grew = False
            for name, fn in defs.items():
                if name not in readers and any(
                        _pa_plan_read(c) or getattr(c.func, "id", None) in readers
                        for c in _pa_calls(fn)):
                    readers.add(name)
                    grew = True
        for door in doors:
            fn = defs[door]
            locked = set()
            for c in _pa_calls(fn):
                if getattr(c.func, "id", None) == lock_fn:
                    locked |= _pa_handed_bodies(c, fn)
            for c in _pa_calls(fn):
                name = getattr(c.func, "id", None)
                if id(c) in locked or name in doors or name in _PA_ONE_QUESTION:
                    continue
                if _pa_plan_read(c) or name in readers:
                    found.append((door, c.lineno, name or c.func.attr))
            found.extend((door, n.lineno, "global %s" % (", ".join(n.names),))
                         for n in ast.walk(fn) if isinstance(n, ast.Global))
        for name, fn in defs.items():
            if name.startswith("_locked_") or name.endswith("_locked"):
                found.extend((name, n.lineno, "global %s" % (", ".join(n.names),))
                             for n in ast.walk(fn) if isinstance(n, ast.Global))
        doors_all.extend("%s:%s" % (rel.split("/")[-1], d) for d in doors)
        readers_all |= readers
    return doors_all, readers_all, found


# Doors handing a lock function their body, one per place a read can sit: in
# the door before the call, in a lambda's default, as a `functools.partial`'s
# bound argument, as a handed def's default - each evaluated BEFORE the lock -
# and inside the lambda's body and the handed def's body, which run under it.
_PA_DOOR_FIXTURE = (
    "import functools\n"
    "import _manifest_io as _mio\n\n\n"
    "def _read(p):\n"
    "    return _mio.read_json(p)\n\n\n"
    "def _body(plan):\n"
    "    return plan\n\n\n"
    "def early_direct(p):\n"
    "    plan = _read(p)\n"
    "    return _under_lock(p, lambda: _body(plan))\n\n\n"
    "def lambda_default(p):\n"
    "    return _under_lock(p, lambda _e=_read(p): _body(_e))\n\n\n"
    "def partial_arg(p):\n"
    "    return _under_lock(p, functools.partial(lambda e: _body(e), _read(p)))\n\n\n"
    "def def_default(p):\n"
    "    def run(e=_read(p)):\n"
    "        return _body(e)\n"
    "    return _under_lock(p, run)\n\n\n"
    "def in_lambda(p):\n"
    "    return _under_lock(p, lambda: _body(_read(p)))\n\n\n"
    "def in_def(p):\n"
    "    def run():\n"
    "        return _body(_read(p))\n"
    "    return _under_lock(p, run)\n")


def _pa_door_fixture_case(check):
    """(pa0c) What `_pa_door_reads` counts as run under the lock, on a fixture."""
    tmp = _harness.fixture_root("audit-evidence-doors-")
    try:
        path = os.path.join(tmp, "doors.py")
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(_PA_DOOR_FIXTURE)
        doors, _readers, early = _pa_door_reads(((path, "_under_lock"),))
        flagged = sorted(set(d for d, _l, _w in early))
        check("pa0c ONLY THE BODY HANDED TO THE LOCK RUNS UNDER IT: a read in the "
              "door, in a lambda's default, as a `functools.partial` argument and "
              "in a handed def's default is each a read before the lock, while a "
              "read inside the lambda's body or the handed def's body is not: "
              "%r of %r" % (flagged, doors),
              flagged == ["def_default", "early_direct", "lambda_default",
                          "partial_arg"] and len(doors) == 6)
    finally:
        _harness.remove_tree(tmp)


def _pa_calls(node):
    """Every Call under `node`."""
    import ast
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _pa_plan_read(call):
    """True for a call of one of `_manifest_io`'s plan reads."""
    import ast
    f = call.func
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
        and f.value.id in ("_mio", "_manifest_io") and f.attr in _PA_PLAN_READS


def _behind_lock_cases(check):
    """(pa) Every plan writer the lint's table names reads the plan behind the
    index lock: a change landed as it asks for the lock survives its write."""
    tmp = _harness.fixture_root("audit-evidence-behind-lock-")
    try:
        loose, total, order = _pa_locked_bodies()
        check("pa0 THE VERBS' DOOR, BY CALL POSITION ONLY: every call of an "
              "audit-task `_locked_*` body sits inside an `_under_lock(...)` "
              "call or another locked body, and `_under_lock` asks for the lock "
              "before it runs the body - which says where each verb's read CAN "
              "be, not that it is there; the pm cases run each write mechanism "
              "the verbs share with a change in the window: loose=%r of %d, "
              "order=%r" % (loose, total, order),
              total > 0 and loose == [] and None not in order
              and order[0] < order[1])
        doors, readers, early = _pa_door_reads()
        check("pa0b NO VERB'S DOOR HANDS ITS BODY A PLAN READ TAKEN BEFORE THE "
              "LOCK: no door of %s calls a plan reader outside what runs under "
              "the lock - the body of a lambda it hands over, or of a def it "
              "hands by name; a lambda's defaults and every other argument run "
              "in the door - and no door or locked body declares a `global`; a "
              "read for one question the body does not take is allowed by name "
              "(%s). It cannot see a read through a callee it cannot name (a "
              "method, `getattr`, a `_loader` sibling) or another module's "
              "function, a plan file opened and parsed in the door itself, a "
              "lambda called on the spot inside the lock call's arguments, nor "
              "the writers that take the lock inline, which their own cases "
              "hold: %s: %d doors, %d readers, early=%r"
              % (" and ".join(m for m, _f in _PA_DOOR_MODULES),
                 "; ".join("`%s` %s" % kv for kv in sorted(_PA_ONE_QUESTION.items())),
                 "; ".join(_PA_INLINE_LOCKS), len(doors), len(readers), early),
              len(doors) > 20 and "_read_plan" in readers
              and "close-phase.py:stamp_merged" in doors and early == [])
        _pa_door_fixture_case(check)

        at = _loader.load_script("audit-task.py")
        root, mpath, spath = _pa_project(tmp, "note")
        code, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: at.main(
            ["note", "P1.1", "--text", "the verb's own note",
             "--project-dir", root], out=_pa_quiet))
        notes = json.dumps(_rv_task(spath).get("notes") or "")
        check("pa1 `note` (`cmd_note`) THROUGH THE REAL VERB: a run record written as the "
              "verb asks for the lock is kept, and the verb's note landed: %r"
              % ((code, wrote, kept, "own note" in notes),),
              code == 0 and wrote and kept and "own note" in notes)

        sp = _loader.load_script("set-priority.py")
        root, mpath, spath = _pa_project(tmp, "build-command")
        code, wrote, kept = _pa_run(root, mpath, spath, "index", lambda: at.main(
            ["build-command", "own", "--command", "echo own",
             "--project-dir", root], out=_pa_quiet))
        own = "own" in ((_lr_shard(mpath).get("meta") or {})
                        .get("buildCommands") or {})
        check("pa2 AN INDEX WRITE THROUGH THE REAL VERB (`build-command`, "
              "`cmd_build_command`): a "
              "build command another writer put in the index as the verb asks "
              "for the lock is kept beside the verb's own: %r"
              % ((code, wrote, kept, own),),
              code == 0 and wrote and kept and own)

        root, mpath, spath = _pa_project(tmp, "set-priority")
        code, wrote, kept = _pa_run(root, mpath, spath, "index", lambda: sp.main(
            [mpath, "P1", "1", "--project-dir", root], out=_pa_quiet))
        stub = (_lr_shard(mpath).get("phases") or [{}])[0]
        check("pa3 `set-priority` (`cmd_set`): an index change landed as it asks for the "
              "lock is kept, and the tier is written: %r"
              % ((code, wrote, kept, stub.get("priority")),),
              code == 0 and wrote and kept and stub.get("priority") == 1)

        cp = _loader.load_script("close-phase.py")
        root, mpath, spath = _pa_project(tmp, "stamp")
        got, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: (
            cp.stamp_merged(mpath, "P1", project=root)))
        # The written path is compared as a FILE, not as a spelling: close-phase
        # joins the index's directory with the stub's `phases/P1.json`, and the
        # fixture joins its path part by part. The two spellings differ on
        # Windows - a Windows run printed the record writer's join of the same
        # two parts as `...\docs\audit\phases/P1.json` (lr1) - so a string
        # comparison was red there with the record kept.
        check("pa4 close-phase's merge stamp (`_stamp_locked`): a run record landed as it asks "
              "for the lock is kept, and `mergedAt` is written: %r"
              % ((_same_file(got[0], spath), wrote, kept,
                  _lr_shard(spath).get("mergedAt") is not None),),
              _same_file(got[0], spath) and wrote and kept
              and _lr_shard(spath).get("mergedAt") is not None,
              "written %r, the shard %r, on %s" % (got[0], spath, sys.platform))
        body = _lr_shard(spath)
        body["tasks"][0].pop("lastRun", None)
        body["tasks"][0].pop("testEvidence", None)
        with io.open(spath, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        got, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: (
            cp.record_merged_head(mpath, "P1", "a" * 40, project=root)))
        check("pa5 close-phase's merged head (`_head_locked`): a run record landed as it asks "
              "for the lock is kept, and `mergedHead` is written: %r"
              % ((got[1], wrote, kept, _lr_shard(spath).get("mergedHead")),),
              got[1] == "a" * 40 and wrote and kept
              and _lr_shard(spath).get("mergedHead") == "a" * 40)

        root, mpath, spath = _pa_project(tmp, "mirror")
        index = _lr_shard(mpath)
        index["phases"][0]["status"] = "pending"
        with io.open(mpath, "w", encoding="utf-8") as fh:
            json.dump(index, fh)
        got, wrote, kept = _pa_run(root, mpath, spath, "index", lambda: (
            cp.mirror_stub(mpath, "P1", root)))
        stub = (_lr_shard(mpath).get("phases") or [{}])[0]
        check("pa6 close-phase's stub mirror (`main`'s `_stamp`): an index change landed as it asks "
              "for the lock is kept, and the stub now mirrors its shard: %r"
              % ((got[0] == mpath, got[1], wrote, kept, stub.get("status")),),
              got[0] == mpath and wrote and kept
              and stub.get("status") == "in_progress", got[1])

        dg = _loader.load_script("derive-phase-gate.py")
        root, mpath, spath = _pa_project(tmp, "derive")
        index = _lr_shard(mpath)
        index["meta"]["phaseGate"] = {"mode": "shadow"}
        with io.open(mpath, "w", encoding="utf-8") as fh:
            json.dump(index, fh)
        said = []
        code, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: dg.main(
            [mpath, "P1", "--project-dir", root], out=said.append))
        derived = sorted(k for k in _lr_shard(spath)
                         if k in ("testGateDerived", "testGateBasis"))
        check("pa7 `derive-phase-gate` (`cmd_derive` and `_write_phase_fields`, "
              "shadow mode, which writes the derived "
              "fields beside the wide gate): a run record landed as it asks for "
              "the lock is kept, and the derived fields are written: %r"
              % ((code, wrote, kept, derived),),
              code == 0 and wrote and kept
              and derived == ["testGateBasis", "testGateDerived"],
              "\n".join(str(s) for s in said)[-600:])

        import _proposals
        parked = {"id": "PROP-1", "name": "n", "status": "proposed",
                  "origin": "audit:init", "createdISO": "2026-01-01T00:00:00Z",
                  "scope": "s", "benefit": "b", "openQuestions": [],
                  "payload": {"phase": {"id": "P2", "title": "Parked",
                                        "status": "pending", "tasks": [
                                            {"id": "P2.1", "title": "a",
                                             "status": "pending",
                                             "files": ["src/a.py"]}]}}}
        root, mpath, spath = _pa_project(tmp, "proposal",
                                         index_extra={"proposals": [parked]})
        got, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: (
            _proposals.run(mpath, "materialize", ["PROP-1"])))
        phases = [p.get("id") for p in _mio_load(mpath)["phases"]]
        check("pa8 a proposal materialized (`_proposals.run`, both doors: "
              "materialize-proposal and `proposal_action`): a "
              "run record landed as it asks for the lock is kept, and the "
              "parked phase is in the plan: %r"
              % ((got[0], wrote, kept, phases),),
              got[0] is True and wrote and kept and "P2" in phases)

        mj = _loader.load_script("migrate-json-encoding.py")
        root, mpath, spath = _pa_project(tmp, "encoding")
        index = _lr_shard(mpath)
        index["meta"]["note"] = u"café"
        chosen = _mio_document(index)
        with io.open(mpath, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2,
                      ensure_ascii=u"café" in chosen)
            fh.write("\n")
        code, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: mj.main(
            [mpath, "--project-dir", root], out=_pa_quiet))
        with io.open(mpath, encoding="utf-8") as fh:
            respelled = fh.read() == _mio_document(_lr_shard(mpath))
        check("pa9 `migrate-json-encoding` (`_locked_migrate`): a run record landed as it asks for "
              "the lock is kept, and the index is in the chosen escaping: %r"
              % ((code, wrote, kept, respelled),),
              code == 0 and wrote and kept and respelled)

        root, mpath, spath = _pa_project(tmp, "add")
        code, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: at.main(
            ["add", "A second task", "--phase", "P1", "--project-dir", root],
            out=_pa_quiet))
        ids = [t.get("id") for t in _lr_shard(spath).get("tasks") or []]
        check("pa10 `add` (`cmd_add`, and `_write_add`, which writes the shard itself): a run "
              "record landed as the verb asks for the lock is kept, and the "
              "new task is in the shard: %r" % ((code, wrote, kept, ids),),
              code == 0 and wrote and kept and "P1.2" in ids)

        pw = _loader.load_script("_panel_write.py")
        root, mpath, spath = _pa_project(tmp, "panel-save")
        got, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: (
            pw.apply_composition(root, {"tasks": {"P1.1": {"model": "opus"}}})))
        model = _rv_task(spath).get("model")
        check("pa11 the panel's save (`apply_composition`, writing through "
              "`_write_back`): a run record landed in the shard as it asks for "
              "the lock is kept, and the composition is saved: %r"
              % ((got.get("ok"), wrote, kept, model),),
              got.get("ok") is True and wrote and kept and model == "opus",
              "%r" % (got,))
        _plan_file_caller_cases(check, tmp)
        _verb_mechanism_cases(check, tmp, at)
    except Exception as exc:                                   # noqa: BLE001
        import traceback
        check("pa-x the behind-the-lock block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False, traceback.format_exc()[-900:])
    finally:
        _harness.remove_tree(tmp)


def _plan_file_caller_cases(check, tmp):
    """(pf) Each caller of `write_plan_file`, run as its command runs it, with
    another writer's change landed in the same plan file as it asks for the
    lock: the helper reads behind the lock (lk2), and these hold that no caller
    hands it a change computed from a read of its own taken before."""
    stamp = "2026-11-19T11:00:00Z"

    def shard_of(spath):
        return _lr_shard(spath)

    root, mpath, spath = _pa_project(tmp, "pc-record")
    got, wrote, kept = _pa_run(root, mpath, spath, "note", lambda: M.write_record(
        root, mpath, "phase", {"phaseId": "P1"},
        M.run_record(dict(_lr_row("PC1", stamp), scope="phase"))))
    own = (shard_of(spath).get(M.RECORD_KEY) or {}).get("runId")
    check("pf1 `write_record` (a phase's record): a note landed in the shard "
          "as it asks for the lock is kept, and the record is written: %r"
          % ((got.get("written"), wrote, kept, own),),
          got.get("written") is True and wrote and kept and own == "PC1",
          got.get("reason"))

    root, mpath, spath = _pa_project(tmp, "pc-pointer")
    got, wrote, kept = _pa_run(root, mpath, spath, "note", lambda: M.write_pointer(
        root, mpath, "phase", {"phaseId": "P1"},
        {"runId": "PC2", "status": "passed", "ts": stamp}))
    own = (shard_of(spath).get("testEvidence") or {}).get("runId")
    check("pf2 `write_pointer` (a phase's pointer): a note landed in the shard "
          "as it asks for the lock is kept, and the pointer is written: %r"
          % ((got.get("written"), wrote, kept, own),),
          got.get("written") is True and wrote and kept and own == "PC2",
          got.get("reason"))

    root, mpath, spath = _pa_project(tmp, "pc-base")
    red = _rk_rows(root)["red"]
    M.write_record(root, mpath, "task", _RK_TASK, M.run_record(red))
    got, wrote, kept = _pa_run(root, mpath, spath, "note", lambda: M.keep_base(
        root, mpath, red, _kb_base("PC3", "RK")))
    held = json.dumps(_rv_task(spath).get(M.RECORD_KEY) or {})
    check("pf3 `keep_base`: a note landed in the shard as it asks for the lock "
          "is kept, and the base run is kept on the red's record: %r"
          % ((got.get("written"), wrote, kept, "PC3" in held),),
          got.get("written") is True and wrote and kept and "PC3" in held,
          got.get("reason"))

    root, mpath, spath = _pa_project(tmp, "pc-reconcile")
    M.append_row(root, {"v": 1, "runId": "PC4", "ts": stamp, "scope": "phase",
                        "phaseId": "P1", "status": "passed", "steps": []})
    got, wrote, kept = _pa_run(root, mpath, spath, "note", lambda: M.reconcile(
        root, mpath))
    own = (shard_of(spath).get("testEvidence") or {}).get("runId")
    check("pf4 `reconcile` (`_reconcile_subject`, which points the subject): a "
          "note landed in the shard as it asks for the lock is kept, and the "
          "phase now points at its newest run: %r"
          % ((got.get("moved"), wrote, kept, own),),
          wrote and kept and own == "PC4", got)

    fg = _loader.load_script("full-gate.py", "fg_pc")
    root, mpath, spath = _pa_project(tmp, "pc-ci")
    record = {"runId": "905", "sha": "a" * 40, "at": stamp,
              "conclusion": "success"}
    got, wrote, kept = _pa_run(root, mpath, spath, "note", lambda: fg.write_ci(
        root, mpath, "P1", record))
    own = (shard_of(spath).get(fg.CI_KEY) or {}).get("runId")
    check("pf5 full-gate's `write_ci`: a note landed in the shard as it asks "
          "for the lock is kept, and the CI record is written: %r"
          % ((got.get("written"), wrote, kept, own),),
          got.get("written") is True and wrote and kept and own == "905",
          got.get("reason"))

    root, mpath = _fh_project(tmp, "pc-held", [_fh_started("P1")])
    a = _fh_commit(root, "a")
    b = _fh_commit(root, "b")
    _fh_put(root, dict(_fh_started("P1", [a], status="done"),
                       mergedAt="2026-01-01T00:00:00Z", mergedHead=a))
    spath = _fh_shard(root, "P1")
    green = _fh_row("pc-green", "2026-01-02T00:00:00Z", b, mpath)
    got, wrote, kept = _pa_run(root, mpath, spath, "record", lambda: _fh_hold(
        root, mpath, green))
    held = [h.get("runId") for h in
            (shard_of(spath).get(M.FULL_GATE_RUNS_KEY) or [])]
    check("pf6 `hold_full_run`: a run record landed in the merged phase's shard "
          "as it asks for the lock is kept, and the full run is held: %r"
          % ((got.get("held"), wrote, kept, held),),
          got.get("held") == ["P1"] and wrote and kept and held == ["pc-green"],
          got)

    root, mpath, spath = _pa_project(tmp, "pc-since")
    # A run on the ledger: the boundary is dated from the first recorded run.
    M.append_row(root, {"v": 1, "runId": "PF7", "ts": stamp, "scope": "phase",
                        "phaseId": "P1", "status": "passed", "steps": []})
    got, wrote, kept = _pa_run(root, mpath, spath, "index", lambda: (
        M.write_evidence_since(root, mpath, "P1")))
    since = (_lr_shard(mpath).get("meta") or {}).get("evidenceSince")
    check("pf7 `write_evidence_since` (run-test-gate's `_record_run` dates the "
          "plan through it): a build command landed in the index as it asks "
          "for the lock is kept, and the plan's first recording is dated: %r"
          % ((wrote, kept, since),),
          wrote and kept and bool(since), got)

    root, mpath, spath = _pa_project(tmp, "pc-full-record")
    full_row = M.row_for(root, {"status": "failed", "steps": [],
                                "testedState": {}}, M.FULL_SCOPE, {},
                         {"runId": "PF8", "ts": stamp})
    got, wrote, kept = _pa_run(root, mpath, spath, "index", lambda: (
        M.write_full_record(root, mpath, M.run_record(full_row))))
    meta = _lr_shard(mpath).get("meta") or {}
    check("pf8 `write_full_record` (run-test-gate's `_record_full_run` records "
          "a full run through it): a build command landed in the index as it "
          "asks for the lock is kept, the run is the plan's full-run record, "
          "and the boundary is dated by it: %r"
          % ((wrote, kept, (meta.get(M.FULL_RECORD_KEY) or {}).get("runId"),
              (meta.get(M.SINCE_KEY) or {}).get("runId")),),
          wrote and kept and got.get("written") is True
          and (meta.get(M.FULL_RECORD_KEY) or {}).get("runId") == "PF8"
          and (meta.get(M.SINCE_KEY) or {}).get("runId") == "PF8", got)


def _verb_mechanism_cases(check, tmp, at):
    """(pm) Each write mechanism the verbs' rows share beyond the ones pa1,
    pa2 and pa10 run - `_locked_move`, `_park_phase`, `_locked_batch_add` and
    `_locked_seed` - through the real verb, with a change in the window. For the
    seed the change is the whole plan: another writer creates it as the seed
    asks for the lock, after `_under_lock` found the path free."""
    root, mpath, spath = _pa_project(tmp, "pm-move")
    body = _lr_shard(spath)
    body["tasks"][0]["status"] = "pending"      # `move` refuses a running task
    with io.open(spath, "w", encoding="utf-8") as fh:
        json.dump(body, fh)
    index = _lr_shard(mpath)
    index["phases"].append({"id": "P2", "title": "two",
                            "shard": "phases/P2.json"})
    with io.open(mpath, "w", encoding="utf-8") as fh:
        json.dump(index, fh)
    with io.open(os.path.join(os.path.dirname(spath), "P2.json"), "w",
                 encoding="utf-8") as fh:
        json.dump({"id": "P2", "title": "two", "status": "pending",
                   "testGate": [], "tasks": []}, fh)
    said = []
    code, wrote, kept = _pa_run(root, mpath, spath, "note", lambda: at.main(
        ["move", "P1.1", "--to", "P2", "--project-dir", root], out=said.append))
    moved = [t.get("id") for p in _mio_load(mpath)["phases"]
             if p.get("id") == "P2" for t in p.get("tasks") or []]
    check("pm1 `move` (`cmd_move`, `_locked_move`): a note landed on the task as the verb "
          "asks for the lock is kept, under the task's new id: %r"
          % ((code, wrote, kept, moved),),
          code == 0 and wrote and kept and moved == ["P2.1"],
          "\n".join(str(s) for s in said)[-600:])

    root, mpath, spath = _pa_project(tmp, "pm-park")
    said = []
    code, wrote, kept = _pa_run(root, mpath, spath, "index", lambda: at.main(
        ["add-phase", "Parked idea", "--outcome", "o", "--park",
         "--project-dir", root], out=said.append))
    parked = [p.get("name") for p in _lr_shard(mpath).get("proposals") or []]
    check("pm2 `add-phase --park` (`cmd_phase_add`, `_park_phase`, which writes the index): a "
          "build command landed in the index as the verb asks for the lock is "
          "kept, and the proposal is parked: %r" % ((code, wrote, kept, parked),),
          code == 0 and wrote and kept and parked == ["Parked idea"],
          "\n".join(str(s) for s in said)[-600:])

    root, mpath, spath = _pa_project(tmp, "pm-batch")
    doc_path = os.path.join(root, "batch.json")
    with io.open(doc_path, "w", encoding="utf-8") as fh:
        json.dump({"request": "a batch", "openChoices": [],
                   "phase": {"title": "Batched", "desiredOutcome": "o"},
                   "tasks": [{"title": "bt", "files": ["src/b.ts"],
                              "tests": {"mode": "gate-only"}}]}, fh)
    said = []
    code, wrote, kept = _pa_run(root, mpath, spath, "index", lambda: at.main(
        ["add", "--from-file", doc_path, "--project-dir", root],
        out=said.append))
    titles = [p.get("title") for p in _mio_load(mpath)["phases"]]
    check("pm3 `add --from-file` (`_cmd_batch_add`, `_locked_batch_add`): a build command landed "
          "in the index as the verb asks for the lock is kept, and the batch's "
          "phase is in the plan: %r" % ((code, wrote, kept, titles),),
          code == 0 and wrote and kept and "Batched" in titles,
          "\n".join(str(s) for s in said)[-600:])

    root = os.path.join(tmp, "pm-seed")
    _project(root, {"manifestPath": "docs/audit/audit-plan.json"})
    _harness.git(None, "init", "-q", root, prefix=("git",))
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    theirs = json.dumps({"meta": {"version": 3}, "phases": []})

    def seeded_first(_root, _mpath):
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        with io.open(mpath, "w", encoding="utf-8") as fh:
            fh.write(theirs)
        return True
    said = []
    code, wrote, _k = _pa_run(root, mpath, None, seeded_first, lambda: at.main(
        ["seed", "--project-dir", root], out=said.append))
    with io.open(mpath, encoding="utf-8") as fh:
        now = fh.read()
    check("pm4 `seed` (`cmd_seed`, `_locked_seed`): a plan another writer created as the seed "
          "asks for the lock - the path was free at its door - is refused behind "
          "the lock with nothing written, the plan kept byte for byte: %r"
          % ((code, wrote, now == theirs),),
          code != 0 and wrote and now == theirs
          and any("nothing was written" in str(s) for s in said)
          and any("another writer created after seed looked" in str(s)
                  for s in said),
          "\n".join(str(s) for s in said)[-600:])
    _seed_occupant_case(check, tmp, at)


def _seed_occupant_case(check, tmp, at):
    """(pm5) What occupies the plan's path before seed starts is said as what it
    is - never as a plan that appeared while seed waited."""
    said_of = {}
    for kind in ("dangling link", "directory"):
        root = os.path.join(tmp, "pm-seed-" + kind.split()[0])
        _project(root, {"manifestPath": "docs/audit/audit-plan.json"})
        _harness.git(None, "init", "-q", root, prefix=("git",))
        mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        outside = os.path.join(tmp, "pm-seed-elsewhere.json")
        if kind == "directory":
            os.makedirs(mpath)
        else:
            try:
                os.symlink(outside, mpath)
            except (OSError, NotImplementedError) as exc:
                said_of[kind] = (None, "a symbolic link could not be made: %s" % (exc,))
                continue
        said = []
        code = at.main(["seed", "--project-dir", root], out=said.append)
        said_of[kind] = (code, " ".join(str(s) for s in said),
                         os.path.lexists(outside))
    link = said_of.get("dangling link")
    if link and link[0] is None:
        _harness.skip(check, "pm5 a dangling link at the plan's path is said as one",
                      link[1], True)
        link = None
    check("pm5 A PATH OCCUPIED BEFORE SEED STARTS IS SAID AS WHAT OCCUPIES IT: a "
          "directory and a dangling symbolic link are each refused with nothing "
          "written through them, named as a directory / a link to a missing file, "
          "and neither is called a plan that appeared while seed waited: %r"
          % (said_of,),
          said_of["directory"][0] != 0 and "a directory" in said_of["directory"][1]
          and "appeared" not in said_of["directory"][1]
          and "another writer" not in said_of["directory"][1]
          and (link is None or (link[0] != 0 and "symbolic link" in link[1]
                                and "does not exist" in link[1] and not link[2]
                                and "another writer" not in link[1])))


def _same_file(a, b):
    """Whether two path spellings name one file - separators, case where the
    platform folds it, and `..` normalized, never compared as strings."""
    if not a or not b:
        return False
    return (os.path.normcase(os.path.normpath(os.path.abspath(a)))
            == os.path.normcase(os.path.normpath(os.path.abspath(b))))


def _mio_load(path):
    import _manifest_io
    return _manifest_io.load_manifest(path)


def _mio_document(obj):
    import _manifest_io
    return _manifest_io.json_document(obj)


# The names a call writes a plan file through - `_manifest_io`'s writers.
_LK_SAVES = ("save_plan_json", "save_sharded", "save_single_file",
             "atomic_write_json", "raw_atomic_write_json", "atomic_write_text")


def _lk_calls(tree, names):
    """`[(enclosing top-level function, line, called name, first argument
    source)]` for every call of one of `names` in the module `tree`."""
    import ast
    found = []
    for top in tree.body:
        if not isinstance(top, (ast.FunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(top):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else None)
            if called in names:
                first = ast.dump(node.args[1]) if len(node.args) > 1 else None
                found.append((top.name, node.lineno, called, first))
    return found


def _shard_lock_ast_cases(check):
    """(lk) The one-helper rule, read off `_evidence_io`'s own AST: every save
    of a plan file and every lock taken is in `write_plan_file`, the read there
    comes after the lock, and the lock is the verbs' `index`."""
    import ast
    import _panel_write
    with io.open(M.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    saves = _lk_calls(tree, _LK_SAVES)
    takes = _lk_calls(tree, ("acquire",))
    # The shard is read through `plan_json` - `read_json`'s parse with every
    # key written twice marked - so either spelling of the read counts.
    reads = [c for c in _lk_calls(tree, ("read_json", "plan_json"))
             if c[0] == "write_plan_file"]
    check("lk1 NO FUNCTION IN _evidence_io SAVES A PLAN FILE OUTSIDE "
          "`write_plan_file`, and none takes a lock outside it: every save call "
          "and every acquire in the module's AST sits in that one function - a "
          "writer added beside it fails here by name: saves=%r acquires=%r"
          % (saves, takes),
          len(saves) == 1 and saves[0][0] == "write_plan_file"
          and len(takes) == 1 and takes[0][0] == "write_plan_file")
    check("lk2 ...and inside it the shard is READ after the lock is TAKEN - a "
          "read moved above the acquire is the lost update again: acquire at "
          "line %r, reads at %r"
          % ([t[1] for t in takes], [r[1] for r in reads]),
          len(takes) == 1 and len(reads) == 1 and reads[0][1] > takes[0][1])
    check("lk3 THE LOCK IS THE VERBS': `SHARD_LOCK` is the name every "
          "`audit-task.py` verb and the panel take for their writes "
          "(`_panel_write.LOCK_NAME`), and the acquire names it - not "
          "`phase-<id>`: %r"
          % ((getattr(M, "SHARD_LOCK", None), _panel_write.LOCK_NAME, takes),),
          getattr(M, "SHARD_LOCK", None) == _panel_write.LOCK_NAME == "index"
          and len(takes) == 1
          and takes[0][3] == ast.dump(ast.Name(id="SHARD_LOCK",
                                               ctx=ast.Load())))


# --- one reader over the shard records and the older rows ---------------------
# The runs both fixtures hold, oldest first. Each result is `run_gate`'s shape
# as `row_for` reads it, so the rows are the writer's own and the records are
# `run_record` over those rows - never a hand-written copy of either.
RI_H0 = "0" * 40
RI_H1 = "1" * 40


def _ri_step(name, exit_code=0, ms=1000, reader="house", **extra):
    step = {"name": name, "exit": exit_code, "ran": 3, "measured": "measured",
            "durationMs": ms, "suiteReader": reader}
    if exit_code:
        step.update(failing=["FAIL a1 the case"], failingBasis="named")
    step.update(extra)
    return step


def _ri_state(head, clean, scope):
    return {"head": head, "headBasis": "git rev-parse HEAD",
            "dirtyDigest": (M.CLEAN_DIRTY_DIGEST if clean
                            else "sha256:" + "d" * 64),
            "scopeDigest": scope, "scopeListDigest": "sha256:list-" + scope[-4:]}


def _ri_result(status, steps, state, key, verdict=None, reused=None):
    out = {"status": status, "durationMs": sum(
        s.get("durationMs") or 0 for s in steps if "reusedFrom" not in s),
           "failed": [s["name"] for s in steps if s.get("exit")],
           "steps": steps, "testedState": state, M.REUSE_KEY: key,
           "gateSource": "task", M.GATE_DIGEST_KEY: "sha256:gate",
           "banners": []}
    if verdict is not None:
        out[M.VERDICT_SOURCE] = verdict
    if reused is not None:
        out["reusedFrom"] = reused
    return out


# The joined step a phase run records: its declared entry and an affected
# step over one suite, as one call (`joined_step_name`).
RI_JOINED = M.joined_step_name("sweep", ["affected/narrow: tests/test_b.py"])


def ri_runs():
    """The fixture, as `(runId, ts, scope, ids, result)` oldest first: a task
    whose second run repeated its first whole (R2 of R1), a red task run on a
    clean base commit (R3), a task whose second run repeated one step of its
    first and measured the other (R6 of R5), and a phase run over a joined
    step on that base (R7)."""
    t11 = {"taskId": "P1.1", "phaseId": "P1"}
    t12 = {"taskId": "P1.2", "phaseId": "P1"}
    t13 = {"taskId": "P1.3", "phaseId": "P1"}
    return [
        ("R1", "2026-11-18T10:00:00Z", "task", t11, _ri_result(
            "passed", [_ri_step("lint", ms=1000, reader="none"),
                       _ri_step("sweep", ms=3000)],
            _ri_state(RI_H1, False, "sha256:scope-p111"), "sha256:k1")),
        ("R2", "2026-11-18T10:05:00Z", "task", t11, _ri_result(
            "passed", [], {}, "sha256:k1", verdict=M.REUSED,
            reused={"runId": "R1", "ts": "2026-11-18T10:00:00Z",
                    "status": "passed"})),
        ("R3", "2026-11-18T10:10:00Z", "task", t12, _ri_result(
            "failed", [_ri_step("sweep", exit_code=1, ms=2500,
                                failingSuites=["tests/test_a.py"],
                                failingSuitesBasis=M.NAMED_FAILING + " by the "
                                "runner's summary")],
            _ri_state(RI_H0, True, "sha256:scope-p112"), "sha256:k2")),
        ("R5", "2026-11-18T10:15:00Z", "task", t13, _ri_result(
            "passed", [_ri_step("lint", ms=2000), _ri_step("plan", ms=500)],
            _ri_state(RI_H1, False, "sha256:scope-p113"), "sha256:k3")),
        ("R6", "2026-11-18T10:20:00Z", "task", t13, _ri_result(
            "passed", [dict(_ri_step("lint"), reusedFrom={
                "runId": "R5", "ts": "2026-11-18T10:15:00Z"}),
                _ri_step("plan", ms=600)],
            _ri_state(RI_H1, False, "sha256:scope-p113"), "sha256:k3",
            verdict=M.PART_REUSED,
            reused={"runId": "R5", "ts": "2026-11-18T10:15:00Z",
                    "status": "passed"})),
        ("R7", "2026-11-18T10:25:00Z", "phase", {"phaseId": "P1"}, _ri_result(
            "passed", [_ri_step(RI_JOINED, ms=4000)],
            _ri_state(RI_H0, True, "sha256:scope-p1"), "sha256:k7")),
    ]


def ri_plan(root, tasks=4):
    """A sharded plan under `root`: one phase P1 of tasks P1.1-P1.<tasks>,
    gated on `sweep`; `(manifest path, {phase id: shard path})`."""
    _project(root, {"manifestPath": "docs/audit/audit-plan.json"})
    os.makedirs(os.path.join(root, "docs", "audit", "phases"), exist_ok=True)
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    shard = os.path.join(root, "docs", "audit", "phases", "P1.json")
    with io.open(shard, "w", encoding="utf-8") as fh:
        json.dump({"id": "P1", "title": "one", "status": "in_progress",
                   "testGate": ["sweep"],
                   "tasks": [{"id": "P1.%d" % (i,), "title": "t",
                              "status": "in_progress"}
                             for i in range(1, tasks + 1)]}, fh)
    with io.open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"version": 3}, "phases": [
            {"id": "P1", "title": "one", "shard": "phases/P1.json"}]}, fh)
    return mpath, {"P1": shard}


def ri_rows(root, runs=None):
    """Every run of `runs` (`ri_runs()`) as the ledger row `row_for` builds."""
    return [M.row_for(root, result, scope, ids, {
        "runId": run, "ts": ts, "startedAt": ts})
        for run, ts, scope, ids, result in (runs or ri_runs())]


def ri_put_record(shard, subject, record):
    """`record` onto `subject` (a task id, or None for the phase) of the shard
    at `shard`, its pointer beside it - the two keys `write_record` writes."""
    with io.open(shard, encoding="utf-8") as fh:
        body = json.load(fh)
    holder = body if subject is None else [
        t for t in body["tasks"] if t["id"] == subject][0]
    holder[M.RECORD_KEY] = record
    holder[M.POINTER_KEY] = M.pointer_from_record(record)
    with io.open(shard, "w", encoding="utf-8") as fh:
        json.dump(body, fh)


def ri_records_of(rows):
    """`{(scope, subject): record}` - each subject's NEWEST run as the record
    `run-test-gate.py --record` writes: `run_record` over its row, with the row
    of the run it repeats as `source`."""
    by_id = dict((r["runId"], r) for r in rows)
    return dict(
        (key, M.run_record(row, source=by_id.get(
            (row.get("reusedFrom") or {}).get("runId"))))
        for key, row in M.latest_by_subject(rows).items())


def ri_fixture(tmp, name, rows=True, records=True, runs=None):
    """`(project, manifest path, shards)` holding `runs` (`ri_runs()`) as ledger
    rows, as records, or as both."""
    root = os.path.join(tmp, name)
    mpath, shards = ri_plan(root)
    built = ri_rows(root, runs)
    if rows:
        for row in built:
            M.append_row(root, row, session_id="ri-fixture")
    if records:
        for (scope, subject), record in sorted(ri_records_of(built).items()):
            ri_put_record(shards["P1"], subject if scope == "task" else None,
                          record)
    return root, mpath, shards


def ri_answers(rows):
    """Every reader the task names, asked of `rows`: one dict, so a fixture of
    records and a fixture of rows are compared whole."""
    rows = list(rows or [])

    def run_of(row):
        return None if row is None else row.get("runId")

    def seen(row):
        return None if row is None else (
            row.get("status"), row.get(M.VERDICT_SOURCE),
            [s.get("name") for s in row.get("steps") or []
             if not M.step_repeated(s)],
            (row.get("testedState") or {}).get("scopeDigest"))
    return {
        "entries": sorted(str(r.get("runId")) for r in rows),
        "latest": dict(("%s %s" % k, run_of(v))
                       for k, v in M.latest_by_subject(rows).items()),
        "byRun": dict((rid, seen(M.row_by_run(rows, rid)))
                      for rid in ("R1", "R2", "R3", "R5", "R6", "R7", "R9")),
        "reuseWhole": run_of(M.reusable_run(
            rows, "task", {"taskId": "P1.1", "phaseId": "P1"}, "sha256:k1",
            ("passed",))),
        "reusePart": run_of(M.reusable_run(
            rows, "task", {"taskId": "P1.3", "phaseId": "P1"}, "sha256:k3",
            ("passed",), steps=["lint"])),
        "reuseOtherKey": run_of(M.reusable_run(
            rows, "task", {"taskId": "P1.1", "phaseId": "P1"}, "sha256:moved",
            ("passed",))),
        "partSources": M.repeated_step_sources(M.row_by_run(rows, "R6")),
        "parts": sorted(repr(M.step_parts(s.get("name")))
                        for r in rows for s in r.get("steps") or []
                        if not M.step_repeated(s)),
        "baseByName": run_of(M.base_run(rows, RI_H0[:12],
                                        exclude_tasks=["P1.1"],
                                        names=["sweep"])),
        "baseBySuite": run_of(M.base_run(rows, RI_H0, names=[],
                                         suites=["tests/test_b.py"])),
        "meanLint": M.gate_mean_ms(rows, ["lint"]),
        "meanGate": M.gate_mean_ms(rows, ["lint", "plan"]),
        "suiteKeys": M.suite_keys(rows),
    }


def _one_reader_cases(check):
    """(ri) Every reader of recorded runs answers the same from the shard
    records as from the older ledger rows they replace."""
    tmp = _harness.fixture_root("audit-evidence-onereader-")
    try:
        rroot, rm, _rs = ri_fixture(tmp, "rows", rows=True, records=False)
        croot, cm, _cs = ri_fixture(tmp, "records", rows=False, records=True)
        broot, bm, bshards = ri_fixture(tmp, "both", rows=True, records=True)
        from_rows = M.read_rows(rroot, manifest_path=rm)
        from_records = M.read_rows(croot, manifest_path=cm)
        a_rows = ri_answers(from_rows["rows"])
        a_records = ri_answers(from_records["rows"])
        differ = sorted(k for k in a_rows if a_rows[k] != a_records.get(k))
        check("ri1 THE TABLE: a plan holding each subject's newest run as its "
              "record and no ledger, and the same runs as ledger rows and no "
              "record, give the same latest-by-subject, by-run lookup, whole "
              "and part repeat, step parts, base reading, gate mean and suite "
              "keys - differing: %r; from records: %r" % (differ, a_records),
              differ == [] and a_rows["entries"] == ["R1", "R2", "R3", "R5",
                                                     "R6", "R7"])
        check("ri2 ...and the table is not vacuous: the whole repeat follows "
              "R2 back to the run that MEASURED it, the part repeat finds R5 "
              "for the step R6 only copied, R6 names R5 as that step's source, "
              "the base is R3 by name and R7 by suite, and the mean of lint is "
              "over R1 and R5's own measurements (R6's copy is no run of it): "
              "%r" % ((a_records["reuseWhole"], a_records["reusePart"],
                       a_records["partSources"], a_records["baseByName"],
                       a_records["baseBySuite"], a_records["meanLint"]),),
              a_records["reuseWhole"] == "R1" and a_records["reusePart"] == "R5"
              and a_records["partSources"] == [("lint", "R5")]
              and a_records["baseByName"] == "R3"
              and a_records["baseBySuite"] == "R7"
              and a_records["meanLint"] == (1500.0, 2)
              and a_records["latest"] == {"task P1.1": "R2", "task P1.2": "R3",
                                          "task P1.3": "R6", "phase P1": "R7"})
        check("ri3 a record whose reuse key is not the current key repeats "
              "nothing, from records as from rows: %r"
              % ((a_records["reuseOtherKey"], a_rows["reuseOtherKey"]),),
              a_records["reuseOtherKey"] is None
              and a_rows["reuseOtherKey"] is None)
        # --- one entry per run, and where each lives ----------------------
        ri_put_record(bshards["P1"], "P1.4", M.run_record(M.row_for(
            broot, _ri_result("passed", [_ri_step("lint", ms=700)],
                              _ri_state(RI_H1, False, "sha256:scope-p114"),
                              "sha256:k9"),
            "task", {"taskId": "P1.4", "phaseId": "P1"},
            {"runId": "R9", "ts": "2026-11-18T10:30:00Z"})))
        both = M.read_rows(broot, manifest_path=bm)
        ids = [str(r.get("runId")) for r in both["rows"]]
        where = dict((str(r.get("runId")), (src, f)) for r, src, f in zip(
            both["rows"], both.get("rowSources") or [], both["rowFiles"]))
        check("ri4 a run held as a ledger row AND as a record is ONE entry, "
              "and a run held only as a record is read too: each entry says "
              "where it came from, and `rowFiles` names the shard for a record "
              "where it names the ledger file for a row: %r" % (where,),
              sorted(ids) == ["R1", "R2", "R3", "R5", "R6", "R7", "R9"]
              and len(ids) == len(set(ids))
              and where.get("R9") == ("record", "docs/audit/phases/P1.json")
              and (where.get("R2") or ("",))[0] == "ledger"
              and str((where.get("R2") or ("", ""))[1]).endswith(".jsonl")
              and both.get("records") == 1 and both["files"] == 1)
        # --- the older directory, absent and present ----------------------
        check("ri5 a reader that finds NO evidence directory says so with a "
              "basis naming where it looked, and its rows are the records "
              "alone - never a zero counted over a directory that is not "
              "there: %r" % ((from_records.get("ledgerAbsent"),
                              from_records["files"]),),
              isinstance(from_records.get("ledgerAbsent"), str)
              and "docs/audit/evidence" in from_records["ledgerAbsent"]
              and from_records["files"] == 0
              and len(from_records["rows"]) == 6)
        check("ri6 SECOND DIRECTION: a project whose evidence directory exists "
              "carries no absence sentence - the case that fails if every "
              "reading said the directory was missing: %r"
              % (from_rows.get("ledgerAbsent", "<key missing>"),),
              "ledgerAbsent" in from_rows
              and from_rows["ledgerAbsent"] is None and from_rows["files"] == 1)
        # --- a group member's copy of the carrier's record ----------------
        groot, gmpath, gshards = ri_fixture(tmp, "group", rows=False)
        with io.open(gmpath, encoding="utf-8") as fh:
            index = json.load(fh)
        index["phases"].append({"id": "P2", "title": "two",
                                "shard": "phases/P2.json"})
        with io.open(gmpath, "w", encoding="utf-8") as fh:
            json.dump(index, fh)
        with io.open(gshards["P1"], encoding="utf-8") as fh:
            carried = json.load(fh)[M.RECORD_KEY]
        with io.open(os.path.join(os.path.dirname(gshards["P1"]), "P2.json"),
                     "w", encoding="utf-8") as fh:
            json.dump({"id": "P2", "title": "two", "status": "done",
                       "tasks": [], M.RECORD_KEY: dict(carried, gradedBy="P1"),
                       M.POINTER_KEY: dict(M.pointer_from_record(carried),
                                           gradedBy="P1")}, fh)
        sevens = [r for r in M.read_rows(groot, manifest_path=gmpath)["rows"]
                  if r.get("runId") == "R7"]
        check("ri7 a group member's copy of its carrier's record is the SAME "
              "run, read once and under the carrier - as the ledger holds it "
              "once, under the phase that ran it: %r"
              % ([(r.get("scope"), r.get("phaseId")) for r in sevens],),
              len(sevens) == 1 and sevens[0].get("phaseId") == "P1"
              and sevens[0].get("scope") == "phase")
        # --- a repeat whose source the record does not hold ---------------
        nroot, nm, nshards = ri_fixture(tmp, "bare-repeat", rows=False)
        with io.open(nshards["P1"], encoding="utf-8") as fh:
            bare = dict(json.load(fh)["tasks"][0][M.RECORD_KEY], steps=[])
        bare.pop(getattr(M, "REPEATED_RUN_KEY", "repeatedRun"), None)
        # Its steps are its own empty list, so the share no longer names
        # them: `steps` held beside a `steps` share is two values for one
        # field, which `share_problem` refuses (`ns2`).
        bare[M.SHARED_KEY] = [p for p in bare.get(M.SHARED_KEY) or []
                              if p != "steps"]
        ri_put_record(nshards["P1"], "P1.1", bare)
        lone = M.read_rows(nroot, manifest_path=nm)["rows"]
        repeat = M.row_by_run(lone, "R2") or {}
        check("ri8 a repeat whose record holds neither its source run nor its "
              "steps is read as the repeat it is - never as a measurement a "
              "later run could repeat, and the run it names is not invented: "
              "%r" % ([(r.get("runId"), r.get(M.VERDICT_SOURCE)) for r in lone
                       if r.get("taskId") == "P1.1"],),
              repeat.get(M.VERDICT_SOURCE) == M.REUSED
              and M.row_by_run(lone, "R1") is None
              and M.reusable_run(lone, "task", {"taskId": "P1.1",
                                                "phaseId": "P1"},
                                 "sha256:k1", ("passed",)) is None)
    finally:
        _harness.remove_tree(tmp)


# --- the record carries what a reader of the seam reads ------------------------
def _rs_row_for_keys():
    """Every top-level key `row_for` can write, read off its source: the keys
    of the dict it builds, each `row[<constant>] = ...`, and each `row[key]`
    whose `key` a loop takes from a tuple of constants. Read off the code
    rather than a run, because most keys are written only when a run has
    something to say, and a fixture would have to know every such case."""
    import ast
    with io.open(M.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            consts[node.targets[0].id] = node.value.value
    fn = [n for n in tree.body
          if isinstance(n, ast.FunctionDef) and n.name == "row_for"][0]

    def word(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        return None
    # Every loop over a tuple of constants under one variable name, unioned:
    # two loops may reuse a name, and a key either one writes is writable.
    found, loops = set(), {}
    for node in ast.walk(fn):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) \
                and isinstance(node.iter, ast.Tuple):
            loops.setdefault(node.target.id, []).extend(
                word(e) for e in node.iter.elts)
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "row" \
                    and isinstance(node.value, ast.Dict):
                found.update(word(k) for k in node.value.keys)
            if isinstance(target, ast.Subscript) \
                    and isinstance(target.value, ast.Name) \
                    and target.value.id == "row":
                index = target.slice
                if type(index).__name__ == "Index":       # the 3.8 wrapper
                    index = index.value
                if isinstance(index, ast.Name) and index.id in loops:
                    found.update(loops[index.id])
                else:
                    found.add(word(index))
    return found


def _rs_full_result():
    """A gate result carrying every field a run can leave on its row - the
    fields the record went without."""
    steps = [_ri_step("sweep", exit_code=1, ms=2000,
                      failingSuites=["tests/test_a.py"],
                      failingSuitesBasis=M.NAMED_FAILING + " by the summary",
                      outcomeBasis="exit 1", timeoutSeconds=600)]
    out = _ri_result("failed", steps, _ri_state(RI_H1, False, "sha256:s"),
                     "sha256:kfull", verdict=M.PART_REUSED,
                     reused={"runId": "RS", "ts": "2026-11-18T10:00:00Z",
                             "status": "passed"})
    out.update({
        M.SELECTION_KEY: 120, M.BASE_OF_KEY: "RT",
        "ranTotal": 3, "countsBasis": "3 checks the runner counted",
        "treeMutated": [" M src/moved.py"],
        "treeBasis": "1 changed path; 1 of 1 changed path(s) are declared",
        "overlap": ["src/moved.py", "src/other.py"],
        "coverageBasis": "2 path(s) the runner named",
        M.FOLLOWERS_KEY: [{"path": "docs/x.html", "recipe": "make x",
                           "owner": "tools/check-rendered-artifacts.py"}],
        "followersUnread": 1,
        M.GATE_REACH_KEY: {"gaps": [{"path": "src/lonely.py",
                                     "why": "no suite reached it",
                                     "suites": []}]},
        M.GATE_REACH_NOT_ASKED_KEY: "the reach was read for the declared "
                                    "files only",
        "cancelledBy": "SIGTERM",
        "attributionBasis": "the tree was dirty outside the work",
        # False, not True: the writer keeps the answer, not only a yes.
        M.RECORDER_HELD_KEY: False,
        M.BASE_RED_KEY: {"run": "RB", "head": RI_H0, "task": "P1.9",
                         "verdict": "introduced", "atBase": [],
                         "introduced": ["tests/test_a.py"], "unknown": [],
                         "basis": "base run RB passed it"},
        "muted": [{"test": "tests/test_m.py", "bugId": "BUG-1",
                   "until": "2026-12-01"}],
        "narrowed": {"listed": 2, "full": 9},
        "shadow": {"listed": 2, "full": 9, "missed": ["tests/test_z.py"]},
        M.LEFT_TO_PHASE_GATE_KEY: [{"name": "e2e", "arm": "declared",
                                    "basis": "phaseGateOnly", "matched": "e2e"}],
        "groupWith": ["P2"],
        # A full run's own: the plan's full-run record carries them.
        "selectionMiss": [{"test": "e2e/cart.spec.ts", "phases": ["P1"],
                           "sources": ["src/cart.ts"]}],
        "dirtyOutside": []})
    return out


def _record_sufficiency_cases(check):
    """(rs) The record carries what a reader of the one seam reads off a row:
    every key `row_for` can write is carried, or named in
    `RECORD_NOT_CARRIED` with the reason no reader of the seam needs it off a
    record; and a run read back from its record alone answers each carried
    key as its ledger row does."""
    tmp = _harness.fixture_root("audit-evidence-sufficient-")
    try:
        root = os.path.join(tmp, "p")
        ri_plan(root)
        skipped = getattr(M, "RECORD_NOT_CARRIED", None)
        writable = _rs_row_for_keys()
        row = M.row_for(root, _rs_full_result(), "task",
                        {"taskId": "P1.1", "phaseId": "P1"},
                        {"runId": "RF", "ts": "2026-11-18T11:00:00Z",
                         "startedAt": "2026-11-18T10:59:00Z", "via": "cli",
                         "attempt": 2, "sessionId": "s-1",
                         M.RUNNER_KEY: M.RUNNER_GATE,
                         "launch": "tok-RF"})
        back = M.record_row(M.run_record(row), "task", "P1.1", "P1")
        # The counts of what a row cut are written only when something was
        # cut, so a second row cuts every capped list once.
        many = dict(_rs_full_result(),
                    treeMutated=[" M src/m%d.py" % i
                                 for i in range(M.MAX_PATHS + 2)],
                    overlap=["src/o%d.py" % i for i in range(M.MAX_PATHS + 3)],
                    dirtyOutside=["?? d%d.txt" % i
                                  for i in range(M.MAX_PATHS + 1)],
                    selectionMiss=[{"test": "e2e/t%d.spec.ts" % i,
                                    "phases": ["P%d" % p
                                               for p in range(M.MAX_PATHS + 1)],
                                    "sources": ["src/s%d.ts" % s for s in
                                                range(M.MAX_PATHS + 2)]}
                                   for i in range(M.MAX_PATHS + 1)])
        many["steps"] = [_ri_step("s%d" % i) for i in range(M.MAX_STEPS + 1)]
        cut_row = M.row_for(root, many, "task",
                            {"taskId": "P1.1", "phaseId": "P1"},
                            {"runId": "RC", "ts": "2026-11-18T11:30:00Z"})
        cut_back = M.record_row(M.run_record(cut_row), "task", "P1.1", "P1")
        lost = sorted(set(
            [k for k in row if k not in (skipped or {})
             and back.get(k) != row[k]]
            + ["%s (cut row)" % k for k in cut_row
               if k not in (skipped or {}) and cut_back.get(k) != cut_row[k]]))
        check("rs1 THE TABLE: every key `row_for` can write is either named in "
              "RECORD_NOT_CARRIED with a reason or written by one of this "
              "case's two rows, so rs3 asks it of a record - neither: %r"
              % (sorted(k for k in writable if k is not None
                        and k not in (skipped or {}) and k not in row
                        and k not in cut_row),),
              isinstance(skipped, dict) and None not in writable
              and all(isinstance(v, str) and len(v) > 20
                      for v in skipped.values())
              and all(k in row or k in cut_row or k in skipped
                      for k in writable))
        check("rs2 ...and the table names no key the row cannot carry - a "
              "stale entry would excuse a key nobody writes: %r"
              % (sorted(k for k in (skipped or {}) if k not in writable
                        and k not in M.CHAIN_KEYS),),
              isinstance(skipped, dict)
              and all(k in writable or k in M.CHAIN_KEYS for k in skipped))
        check("rs3 a run read back from its RECORD alone answers every key it "
              "carries as its ledger row does - followers owed, the reach "
              "reading, the observations (tree moved, coverage), the base "
              "reading, the mutes - differing: %r" % (lost,),
              isinstance(skipped, dict) and lost == []
              and back.get(M.FOLLOWERS_KEY) == row.get(M.FOLLOWERS_KEY)
              and (back.get("observations") or {}).get("coverage")
              == ["src/moved.py", "src/other.py"]
              and back.get("treeMutated") == ["src/moved.py"]
              and back.get(M.GATE_REACH_KEY) == row.get(M.GATE_REACH_KEY)
              and back.get("launch") == "tok-RF")
        # --- the bound, and what goes first -------------------------------
        bound = getattr(M, "RECORD_MAX_BYTES", None)
        order = list(getattr(M, "RECORD_CUT_ORDER", ()) or ())
        wide = dict(_rs_full_result(), overlap=[
            "src/%s/%s.py" % ("d" * 40, i) for i in range(M.MAX_PATHS)])
        big = M.row_for(root, wide, "task", {"taskId": "P1.1", "phaseId": "P1"},
                        {"runId": "RW", "ts": "2026-11-18T11:00:00Z"})
        record = M.run_record(big, bound=(len(json.dumps(
            M.run_record(big, bound=10 ** 9), separators=(",", ":"))) - 1)
            if bound is not None else None)
        cut = record.get(getattr(M, "RECORD_CUT_KEY", "recordCut"))
        read = M.record_row(record, "task", "P1.1", "P1")
        check("rs4 A RECORD OVER ITS BOUND drops the first field of "
              "RECORD_CUT_ORDER - the coverage paths, which are reported and "
              "decide nothing - says so on the record, and its reader reads "
              "that field as cut, with a basis naming the bound, never as no "
              "comparison made: %r" % ((bound, order[:2], cut,
                                        (read.get("observations") or {})),),
              isinstance(bound, int) and "observations.coverage" in order
              and order.index("observations.coverage")
              < order.index("observations.treeMutated")
              and cut == ["observations.coverage"]
              and (read.get("observations") or {}).get("coverage") is None
              and "RECORD_MAX_BYTES" in str(
                  (read.get("observations") or {}).get("coverageBasis"))
              and read.get("treeMutated") == ["src/moved.py"])
        small = M.run_record(row)
        check("rs5 SECOND DIRECTION: a record under its bound is cut nothing "
              "and says nothing about a cut - the case that fails if every "
              "record were cut: %r" % (sorted(small),),
              getattr(M, "RECORD_CUT_KEY", "recordCut") not in small
              and (small.get("observations") or {}).get("coverage")
              == ["src/moved.py", "src/other.py"])
    finally:
        _harness.remove_tree(tmp)


def _sh_rows(root, reach_of_repeat):
    """`(source row, whole repeat row)`: a measured run carrying a reach
    reading and observations, and a whole repeat of it whose reach reading is
    `reach_of_repeat` and whose observations are the source's."""
    ids = {"taskId": "P1.1", "phaseId": "P1"}
    state = _ri_state(RI_H1, False, "sha256:s")
    obs = {"ranTotal": 3, "countsBasis": "3 checks the runner counted",
           "overlap": ["src/%s/o%d.py" % ("d" * 30, i) for i in range(4)],
           "coverageBasis": "4 path(s) the runner named"}
    measured = _ri_result("passed", [_ri_step("sweep")], state, "sha256:k")
    measured.update(obs, **{M.GATE_REACH_KEY: _sh_reach("a")})
    source = M.row_for(root, measured, "task", ids,
                       {"runId": "RS", "ts": "2026-11-18T10:00:00Z"})
    repeat = _ri_result("passed", [], state, "sha256:k", verdict=M.REUSED,
                        reused={"runId": "RS", "ts": "2026-11-18T10:00:00Z",
                                "status": "passed"})
    repeat.update(obs, **{M.GATE_REACH_KEY: reach_of_repeat})
    row = M.row_for(root, repeat, "task", ids,
                    {"runId": "RR", "ts": "2026-11-18T10:05:00Z"})
    return source, row


def _sh_reach(tag):
    return {"gaps": [{"path": "src/%s/lonely%d.py" % (tag, i),
                      "why": "no suite reached it", "suites": []}
                     for i in range(6)]}


def _shared_subtree_cases(check):
    """(sh) A repeat's record stores a subtree it shares with the run it
    carries once, and a reader of either place reads what it read before."""
    tmp = _harness.fixture_root("audit-evidence-shared-")
    key = getattr(M, "SHARED_KEY", "sharedWithRepeated")
    try:
        root = os.path.join(tmp, "p")
        ri_plan(root)
        source, row = _sh_rows(root, _sh_reach("a"))
        stored = M.run_record(row, source=source)
        # The record as it was written before the rule: carried and bounded,
        # every subtree in both places.
        whole = M.bounded_record(M.repeat_carried(M._record_of(row), source),
                                 M.RECORD_MAX_BYTES)
        read = [M.record_row(r, "task", "P1.1", "P1") for r in (stored, whole)]
        carried = [M.record_row(r[M.REPEATED_RUN_KEY], "task", "P1.1", "P1")
                   for r in (stored, whole)]
        check("sh1 STORED ONCE: a whole repeat's reach reading, equal to the "
              "run it carries, is held only there and named under the shared "
              "key - the record is smaller - and a reader of the repeat and a "
              "reader of the run it carries each read exactly what they read "
              "off the record holding both copies: %r"
              % ((stored.get(key), M.record_bytes(stored),
                  M.record_bytes(whole), read[0] == read[1],
                  carried[0] == carried[1]),),
              M.GATE_REACH_KEY in (stored.get(key) or [])
              and M.GATE_REACH_KEY not in stored
              # A whole repeat's steps are the carried run's: derived again,
              # each naming that run, rather than held twice.
              and "steps" in (stored.get(key) or []) and "steps" not in stored
              and [s.get(M.STEP_REUSED_KEY) for s in read[0]["steps"]]
              == [{"runId": "RS", "ts": "2026-11-18T10:00:00Z"}]
              and M.record_bytes(stored) < M.record_bytes(whole)
              and read[0] == read[1] and carried[0] == carried[1]
              and read[0].get(M.GATE_REACH_KEY) == row.get(M.GATE_REACH_KEY)
              and key not in read[0])
        source2, row2 = _sh_rows(root, _sh_reach("b"))
        differ = M.run_record(row2, source=source2)
        back = M.record_row(differ, "task", "P1.1", "P1")
        check("sh2 THEY DIFFER, BOTH KEPT: a repeat whose reach reading is not "
              "the carried run's keeps its own beside it, the shared key "
              "names no such path, and each reader reads its own: %r"
              % ((differ.get(key), sorted(differ)),),
              M.GATE_REACH_KEY in differ
              and M.GATE_REACH_KEY not in (differ.get(key) or [])
              and back.get(M.GATE_REACH_KEY) == _sh_reach("b")
              and differ[M.REPEATED_RUN_KEY].get(M.GATE_REACH_KEY)
              == _sh_reach("a"))
        measured = M.run_record(source)
        check("sh3 SECOND DIRECTION: a measured run carries no run, so its "
              "record shares nothing and names no shared path - the case that "
              "fails if every record were rewritten: %r" % (sorted(measured),),
              key not in measured
              and measured.get(M.GATE_REACH_KEY) == source.get(M.GATE_REACH_KEY))
        torn = json.loads(json.dumps(stored))
        torn[M.REPEATED_RUN_KEY].pop(M.GATE_REACH_KEY, None)
        lost = M.record_row(torn, "task", "P1.1", "P1")
        unresolved = getattr(M, "SHARED_UNRESOLVED_KEY", "sharedUnresolved")
        check("sh4 A SHARED PATH THE CARRIED RUN NO LONGER HOLDS is named as "
              "not given back, never read as a run with no reach reading said "
              "nothing about: %r" % ((lost.get(unresolved),),),
              lost.get(unresolved) == [M.GATE_REACH_KEY]
              and M.GATE_REACH_KEY not in lost)
    finally:
        _harness.remove_tree(tmp)


# --- every record the recorder composes, against the published schema --------
# Read with the reader `validate-manifest` reads the plan with, so the answer is
# the one a user's revalidation gives - never a second reading of the schema.
_RK_SCHEMA = os.path.join(_output.PLUGIN_ROOT, "schema", "audit-plan.schema.json")
_RK_TASK = {"taskId": "P1.1", "phaseId": "P1"}
_RK_PHASE = {"phaseId": "P1"}
_RK_SOURCE = {"runId": "RS", "ts": "2026-11-18T10:00:00Z",
              "startedAt": "2026-11-18T09:59:00Z"}
_RK_REUSED = {"runId": "RS", "ts": "2026-11-18T10:00:00Z", "status": "failed"}


def _rk_measured():
    """A measured run's gate result carrying every field a run can leave on
    its row (`_rs_full_result`, its repeat fields taken off) and a second step,
    so a part repeat has one to copy."""
    out = _rs_full_result()
    out.pop(M.VERDICT_SOURCE, None)
    out.pop("reusedFrom", None)
    out["steps"] = list(out["steps"]) + [_ri_step("lint", ms=700)]
    out["banners"] = ["a banner the run printed"]
    return out


def _rk_repeat(verdict, **extra):
    """A repeat of RS's result: whole (`M.REUSED`, no step ran) or part (the
    lint step copied, the sweep measured again)."""
    out = dict(_rk_measured(), **{M.VERDICT_SOURCE: verdict,
                                  "reusedFrom": dict(_RK_REUSED)})
    if verdict == M.REUSED:
        out["steps"] = []
    else:
        out["steps"] = [out["steps"][0], dict(out["steps"][1], reusedFrom={
            "runId": "RS", "ts": _RK_SOURCE["ts"]})]
    out.update(extra)
    return out


def _rk_rows(root):
    """Every ledger row a shape is composed from, as `row_for` builds it."""
    def row(result, run_id, ts, scope="task", identity=None):
        ids = _RK_TASK if scope == "task" else _RK_PHASE
        return M.row_for(root, result, scope, ids,
                         dict(identity or {}, runId=run_id, ts=ts))
    big = {"overlap": ["src/%s/c%d.py" % ("c" * 40, i)
                       for i in range(M.MAX_PATHS)],
           "treeMutated": [" M src/%s/m%d.py" % ("m" * 40, i)
                           for i in range(M.MAX_PATHS)]}
    reading = dict(_rs_full_result()[M.BASE_RED_KEY], head=_KB_HEAD,
                   verdict="no-base", run=None)
    many = _rk_measured()
    many["steps"] = [_ri_step("s%d" % i) for i in range(M.MAX_STEPS + 1)]
    return {
        "source": row(_rk_measured(), "RS", _RK_SOURCE["ts"],
                      identity={"startedAt": _RK_SOURCE["startedAt"]}),
        "part": row(_rk_repeat(M.PART_REUSED), "RP", "2026-11-18T10:05:00Z"),
        "whole": row(_rk_repeat(M.REUSED), "RR", "2026-11-18T10:06:00Z"),
        "differ": row(_rk_repeat(M.REUSED, **{M.GATE_REACH_KEY: _sh_reach("b")}),
                      "RD", "2026-11-18T10:07:00Z"),
        "other": row(_ri_result("passed", [_ri_step("lint")],
                                _ri_state(RI_H1, False, "sha256:s"), "sha256:o"),
                     "RX", "2026-11-18T09:00:00Z"),
        "many": row(many, "RM", "2026-11-18T10:08:00Z"),
        "big source": row(dict(_rk_measured(), **big), "RS",
                          _RK_SOURCE["ts"]),
        "big": row(_rk_repeat(M.PART_REUSED, **dict(
            big, **{M.BASE_RED_KEY: reading})), "RC", "2026-11-18T10:09:00Z"),
        "phase": row(_ri_result("passed", [_ri_step(RI_JOINED, ms=4000)],
                                _ri_state(RI_H0, True, "sha256:scope-p1"),
                                "sha256:k7"), "R7", "2026-11-18T10:25:00Z",
                     scope="phase"),
        "red": row(dict(_rk_measured(), testedState=dict(
            _ri_state(_KB_HEAD, False, "sha256:s")), **{M.BASE_RED_KEY: {
                "run": None, "head": _KB_HEAD, "verdict": "no-base",
                "atBase": [], "introduced": [], "unknown": [],
                "basis": "no run recorded at base"}}),
            "RK", "2026-11-18T10:10:00Z"),
    }


def _rk_shapes(rows):
    """`[(shape, scope, steps)]`: every record shape the recorder writes, each
    as the writes that compose it - a record written by `write_record`, or a
    call `(root, manifest)` of the writer's own (`keep_base`)."""
    rec, src = M.run_record, rows["source"]
    lines = {"machine": "this run had the machine to itself",
             "attribution": "the red is this run's own"}
    return [
        ("a measured run", "task", [rec(src, lines=lines, launch="tok-1")]),
        ("a part repeat", "task", [rec(rows["part"], source=src)]),
        ("a whole repeat sharing every equal subtree", "task",
         [rec(rows["whole"], source=src)]),
        ("a whole repeat keeping its own reach reading", "task",
         [rec(rows["differ"], source=src)]),
        ("a whole repeat of the record it replaces", "task",
         [rec(src), rec(rows["whole"])]),
        ("a repeat whose source neither holds", "task",
         [rec(rows["other"]), rec(rows["whole"])]),
        ("a run whose steps were cut at MAX_STEPS", "task", [rec(rows["many"])]),
        ("a record replacing launched runs", "task",
         [rec(src, launch="tok-A"), rec(rows["part"], source=src,
                                         launch="tok-B")]),
        ("a red carrying kept base runs", "task",
         [rec(rows["red"]), lambda root, mpath: M.keep_base(
             root, mpath, rows["red"], _kb_base("RB", "RK"))]),
        ("a phase-scope record", "phase", [rec(rows["phase"])]),
        ("a phase-scope whole repeat", "phase",
         [rec(rows["whole"], source=src)]),
    ]


def _rk_situations(root):
    """`[(situation, records)]` - the runs a gate meets beside `_rk_shapes`'
    ones, each a result as the runner leaves it, through `row_for` and the
    writer: a green, an empty gate, a run where no commit could be taken, a
    command not found, a step a signal killed and that ran again, muted
    steps."""
    def rec(result, run_id, minute):
        return M.run_record(M.row_for(root, result, "task", _RK_TASK, {
            "runId": run_id, "ts": "2026-11-18T12:%02d:00Z" % (minute,)}))
    state = _ri_state(RI_H1, True, "sha256:s")
    green = _ri_result("passed", [_ri_step("sweep")], state, "sha256:g")
    empty = _ri_result("empty-gate", [], state, "sha256:e")
    headless = _ri_result("passed", [_ri_step("sweep")],
                          {"head": None, "headBasis": "no commit yet",
                           "dirtyDigest": M.CLEAN_DIRTY_DIGEST,
                           "scopeDigest": None}, "sha256:h")
    missing = _ri_result("could-not-run", [_ri_step(
        "sweep", exit_code=127, ran=None, measured="not-knowable",
        outcome="could-not-run", outcomeBasis="no such command")], state,
        "sha256:m")
    signalled = _ri_result("passed", [_ri_step(
        "sweep", retriedAfterSignal="SIGKILL",
        retryBasis="the first attempt was killed by SIGKILL")], state,
        "sha256:k")
    mute = {"test": "tests/test_a.py::a1", "bugId": "BUG-1",
            "until": "2026-12-01"}
    muted = dict(_ri_result("passed", [_ri_step("sweep", muted=[mute])],
                            state, "sha256:u"), muted=[mute])
    return [("a green", [rec(green, "SG", 1)]),
            ("an empty gate", [rec(empty, "SE", 2)]),
            ("a run with no commit", [rec(headless, "SH", 3)]),
            ("a command not found", [rec(missing, "SM", 4)]),
            ("a step killed by a signal", [rec(signalled, "SK", 5)]),
            ("muted steps", [rec(muted, "SU", 6)]),
            ("a run repeated twice", [rec(green, "SG", 1),
                                      rec(green, "SG2", 7)])]


def _rk_compose(tmp, index, scope, steps):
    """`(stored record, stored pointer, refusals)` after `steps` ran against a
    fresh project; `refusals` names each write that did not land."""
    root, mpath, spath = _lr_project(tmp, "rk%d" % (index,))
    ids = _RK_TASK if scope == "task" else _RK_PHASE
    refused = []
    for step in steps:
        got = (step(root, mpath) if callable(step)
               else M.write_record(root, mpath, scope, ids, step))
        if not (isinstance(got, dict) and got.get("written") is True):
            refused.append(got)
    body = _lr_shard(spath)
    holder = body if scope == "phase" else body["tasks"][0]
    return holder.get(M.RECORD_KEY), holder.get(M.POINTER_KEY), refused


def _rk_cut_names(record):
    """The fields `record` names as cut, in `RECORD_CUT_ORDER`'s spelling: a
    cut of the carried run is named on that run's own record."""
    carried = record.get(M.REPEATED_RUN_KEY) or {}
    return (["%s.%s" % (M.REPEATED_RUN_KEY, n)
             for n in carried.get(M.RECORD_CUT_KEY) or []]
            + list(record.get(M.RECORD_CUT_KEY) or []))


def _rk_cut_walk(rows):
    """`[(fields this bound newly cut, record)]`: the record the writer
    finishes (`finished_record` - cut, then shared) at each bound from just
    under the record's whole size down, one entry per bound that cut more.
    The record is a part repeat whose own run and carried run hold every
    observation the order cuts, and whose reading keeps a base run, composed
    as `keep_base` composes one."""
    whole = M.resolved_shared(M.run_record(rows["big"], source=rows["big source"],
                                           bound=10 ** 9))
    reading = whole[M.BASE_RED_KEY]
    whole[M.BASE_RED_KEY] = M.with_kept_bases(reading, M.kept_bases(reading) + [
        M.kept_base(_kb_base("RB", "RC"))])
    out, before, bound = [], [], M.record_bytes(whole) - 1
    while bound > 0:
        cut = M.finished_record(json.loads(json.dumps(whole)), bound)
        names = _rk_cut_names(cut)
        new = [n for n in names if n not in before]
        if not new:
            break
        out.append((new, cut))
        before = names
        bound = M.record_bytes(M.resolved_shared(cut)) - 1
    return out


def _rk_dropped(before, after, where):
    """Every path `before` holds that `after` does not, at every depth - what
    the writer's table took off a record it was handed."""
    if isinstance(before, dict) and isinstance(after, dict):
        return [p for key, val in before.items()
                for p in (["%s.%s" % (where, key)] if key not in after
                          else _rk_dropped(val, after[key],
                                           "%s.%s" % (where, key)))]
    if isinstance(before, list) and isinstance(after, list):
        return [p for i, (b, a) in enumerate(zip(before, after))
                for p in _rk_dropped(b, a, "%s[%d]" % (where, i))]
    return []


def _rk_watched_egress():
    """`(calls, restore)`: every record handed to the writer's egress
    (`stored_record`) from now on is recorded in `calls` as `(paths it
    dropped,)` until `restore()` - so the composer's OWN record, before the
    table, is read, which a comparison of what was stored with its
    projection cannot see: both sides went through the one table."""
    real, calls = M.stored_record, []

    def watched(record):
        kept = real(record)
        calls.append(_rk_dropped(record, kept, M.RECORD_KEY))
        return kept

    M.stored_record = watched

    def restore():
        M.stored_record = real
    return calls, restore


def _rk_said(doc, ref, value, where):
    """Every line the schema reader says of `value` under `ref`: its findings,
    and each keyword it met and could not check - never read as a pass."""
    found, unread = _json_schema.check_findings({"$ref": ref}, value, doc, where)
    return [str(f) for f in found] + ["unread keyword %s" % (k,)
                                      for k in sorted(unread)]


def _rk_definitions(doc):
    """Every `lastRun` a `properties` table of the schema names, as the node it
    holds: one definition is one `$ref` everywhere it is placed."""
    out = []

    def walk(node, where):
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict) and M.RECORD_KEY in props:
                out.append((where, props[M.RECORD_KEY]))
            for key, val in node.items():
                walk(val, "%s/%s" % (where, key))
        elif isinstance(node, list):
            for val in node:
                walk(val, where)
    walk(doc, "#")
    return out


def _record_schema_cases(check):
    """(rk) Every record the recorder can write is one the published schema
    accepts, read by the schema reader `validate-manifest` uses. The shapes are
    composed THROUGH THE WRITER, and the tables that decide a record's shape -
    the cut order, the paths a repeat may share, the keys only a record holds -
    are read off the module, so an entry added to one is composed here or
    named as one the case could not compose."""
    tmp = _harness.fixture_root("audit-evidence-schema-")
    egress, restore = _rk_watched_egress()
    try:
        doc = _json_schema.load_document(_RK_SCHEMA)
        rows_root = os.path.join(tmp, "rows")
        ri_plan(rows_root)
        rows = _rk_rows(rows_root)
        stored, refused, pointers = [], [], []
        for i, (shape, scope, steps) in enumerate(_rk_shapes(rows)):
            record, pointer, said = _rk_compose(tmp, i, scope, steps)
            if said or not isinstance(record, dict):
                refused.append((shape, said))
                continue
            stored.append((shape, record))
            pointers.append((shape, pointer, M.pointer_from_record(record)))
        cuts = _rk_cut_walk(rows)
        stored.extend(("a record cut through %s" % (", ".join(names),), record)
                      for names, record in cuts)
        # ONE RECORD PER STATUS THE RUNNER CAN RECORD, the words read off the
        # published status table rather than listed here, each composed
        # through the writer as a run of that word.
        statuses = list(_ur_node(doc, ((_ur_node(doc, (doc.get("$defs") or {})
                                                .get("lastRun")).get("properties")
                                        or {}).get("status"))).get("enum") or [])
        composed_statuses = []
        for i, status in enumerate(statuses):
            row = M.row_for(rows_root, dict(_rk_measured(), status=status),
                            "task", _RK_TASK,
                            {"runId": "RW%d" % (i,), "ts": "2026-11-18T11:%02d:00Z"
                             % (i,)})
            record, _pointer, said = _rk_compose(
                tmp, 100 + i, "task", [M.run_record(row)])
            if said or not isinstance(record, dict):
                refused.append(("status %s" % (status,), said))
                continue
            stored.append(("a %s run" % (status,), record))
            composed_statuses.append(record.get("status"))
        # THE GROUP COPY, as group sign-off composes it: the carrier's record
        # (`_group_record`, the verb's own) taken onto a member naming the
        # carrier in `gradedBy` - the one expression the verb writes it with.
        verb = _loader.load_script("audit-task.py", "rk_audit_task")
        carrier = {"id": "P1", M.RECORD_KEY: M.run_record(rows["phase"])}
        carried = verb._group_record(rows_root, os.path.join(
            rows_root, "docs", "audit", "audit-plan.json"), None, carrier,
            M.pointer_from_record(carrier[M.RECORD_KEY]), rows["phase"])
        group_copy = dict(carried, gradedBy="P1") \
            if isinstance(carried, dict) else None
        if group_copy is None:
            refused.append(("the group copy", carried))
        else:
            stored.append(("a group member's copy", group_copy))
        # A TASK'S RUN ON ITS PHASE'S GATE, through the writer's own change:
        # the record lands on the task, saying the phase's gate measured it.
        fallback = dict(M.run_record(rows["phase"]), gateSource="phase")
        over, said, _answer = M._put_record(
            {"id": "P1", "tasks": [{"id": "P1.1"}]}, "phase",
            {"phaseId": "P1", "taskId": "P1.1"}, True, fallback)
        held_on = [t.get(M.RECORD_KEY) for t in (over or {}).get("tasks") or []
                   if isinstance(t.get(M.RECORD_KEY), dict)]
        if said or len(held_on) != 1 or M.RECORD_KEY in (over or {}):
            refused.append(("a task's run on its phase's gate", said))
        else:
            stored.append(("a task's run on its phase's gate", held_on[0]))
        refusals = dict((shape, lines) for shape, lines in (
            (shape, _rk_said(doc, "#/$defs/lastRun", record, M.RECORD_KEY))
            for shape, record in stored) if lines)
        check("rk1 THE INVARIANT: every record shape the recorder composes - "
              "measured, part and whole repeats, a record sharing each subtree "
              "it can share, one cut at every position of the cut order, kept "
              "base runs, replaced launches, a phase's, one run of each status "
              "the runner records, a group member's copy, a task's run on its "
              "phase's gate - is "
              "stored and is accepted by the published `lastRun`, read by the "
              "reader validate-manifest uses, with no keyword left unread: "
              "refused by the writer %r / refused by the schema %r / statuses "
              "%r of %r" % (refused, refusals, composed_statuses, statuses),
              refused == [] and refusals == {} and len(stored) > len(cuts)
              and len(statuses) >= 2 and composed_statuses == statuses
              and len(cuts) >= 1 and group_copy is not None)
        # THE TWO ARMS ARE EXCLUSIVE AND EACH WHOLE: a record holds its steps,
        # or names them shared with the run it carries - never both, never a
        # share with no run to give them back, never a share that is not a
        # list of paths. Each twin beside the shape the writer writes.
        shared = [r for _s, r in stored
                  if "steps" in (r.get(M.SHARED_KEY) or [])]
        own = [r for _s, r in stored if r.get("steps") is not None
               and M.SHARED_KEY not in r]
        arms = []
        if shared and own:
            whole, plain = shared[0], own[0]
            arms = [
                ("steps held AND shared", dict(whole, steps=[]), False),
                ("a share of steps with no run carried", dict(
                    (k, v) for k, v in whole.items()
                    if k != M.REPEATED_RUN_KEY), False),
                ("a share that is not a list", dict(dict(
                    (k, v) for k, v in plain.items() if k != "steps"),
                    **{M.SHARED_KEY: "steps"}), False),
                ("the writer's shared record", whole, True),
                ("the writer's own-steps record", plain, True)]
        verdicts = [(label, not _json_schema.check_findings(
            {"$ref": "#/$defs/lastRun"}, record, doc, M.RECORD_KEY)[0], want)
            for label, record, want in arms]
        check("rk8 RED-FIRST: `lastRun`'s two arms are exclusive (oneOf) and "
              "each whole - the share arm requires the run it is given back "
              "from and a list of paths: %r" % (verdicts,),
              len(verdicts) == 5
              and all(got == want for _l, got, want in verdicts))
        problems = [(shape, M.record_problem(record, doc))
                    for shape, record in stored]
        check("rk7 THE WRITER'S SHAPES ARE THE READER'S: every record the "
              "recorder composes above reads with no record problem, through "
              "the same check that names a malformed record unreadable - so "
              "\"the writer writes it\" implies \"the reader reads it\": %r"
              % ([p for p in problems if p[1] is not None],),
              len(problems) == len(stored) and len(problems) > len(cuts)
              and all(p is None for _s, p in problems))
        # THE TABLE IS ONE STATEMENT: what the writer stores is what the
        # reader projects, field for field - nothing the writer stores is
        # dropped by the projection, nothing refused - over every record
        # composed above and the situations a run meets beside them.
        situations = _rk_situations(rows_root)
        for i, (shape, steps) in enumerate(situations):
            record, _pointer, said = _rk_compose(tmp, 200 + i, "task", steps)
            if said or not isinstance(record, dict):
                refused.append((shape, said))
                continue
            stored.append((shape, record))
        dropped = sorted(set(p for paths in egress for p in paths))
        unequal = []
        for shape, record in stored:
            projected, why = M.project_record(record, "task")
            if why is not None or projected != M.resolved_shared(record) \
                    or M.stored_record(record) != record:
                unequal.append((shape, why, sorted(
                    set(M.resolved_shared(record)) ^ set(projected or {}))))
        check("pj1 THE WRITER'S RECORD IS ITS OWN PROJECTION: every record "
              "the writer stores - the shapes above, and an ordinary red, a "
              "green, an empty gate, a run with no commit, a command not "
              "found, a step killed by a signal and run again, muted steps, a "
              "fall-back task, a phase, a repeat, a red with its base runs - "
              "projects through `RECORD_GRAMMAR` to itself, and storing it "
              "again drops nothing; and the writer's egress took no field "
              "off any record the composer handed it, read before the table "
              "(a field the composer builds and the table omits is lost on "
              "both sides alike, which the comparison above cannot see): "
              "%d record(s); unequal %r; refused %r; egress calls %d, "
              "dropped %r"
              % (len(stored), unequal, refused[-3:], len(egress), dropped),
              unequal == [] and refused == []
              and len(stored) > len(cuts) + len(situations)
              and len(egress) >= len(stored) and dropped == [])

        cut_last = set(n for names, _r in cuts if len(names) == 1 for n in names)
        # What a repeat may share: a key of a measured record outside
        # `NEVER_SHARED_KEYS` holding a subtree - a dict or a list - longer
        # than the path naming it (`_shared_paths`' rule); and the steps, which
        # a whole repeat shares by derivation (the never-shared table's comment).
        measured = M.run_record(rows["source"])
        shareable = sorted(
            set(k for k, v in measured.items() if k not in M.NEVER_SHARED_KEYS
                and isinstance(v, (dict, list))
                and M.record_bytes(v) > M.record_bytes(k) + 1)
            | set(["steps"]))
        shared = set(p.split(".")[0] for _s, r in stored
                     for p in r.get(M.SHARED_KEY) or [])
        shaped = set()
        for _s, r in stored:
            shaped |= set(r) | set(r.get(M.REPEATED_RUN_KEY) or {})
            shaped |= set((r.get(M.BASE_RED_KEY) or {}))
        # A key only a record holds that no writer writes - the reader's own
        # marker for a share it could not give back - is the one left out.
        owed = (list(M._RECORD_SHAPED) + list(M.RECORD_LINE_KEYS)
                + [k for k in M.RECORD_ONLY_KEYS
                   if k != M.SHARED_UNRESOLVED_KEY]
                + [M.LAUNCH_KEY, M.BASE_RUNS_KEY])
        # EACH TABLE'S WALK IS ITS OWN CONJUNCT: what it reached must be the
        # whole table, in the table's order, so a walk emptied - or a table
        # emptied - fails here rather than passing as "nothing uncomposed".
        tables = {"RECORD_CUT_ORDER": (list(M.RECORD_CUT_ORDER), cut_last),
                  "shareable paths": (shareable, shared),
                  "record-shaped keys": (owed, shaped)}
        reached = dict((name, [e for e in table if e in seen])
                       for name, (table, seen) in tables.items())
        check("rk2 THE TABLES ARE COMPOSED: each entry of the cut order is the "
              "one field some bound newly cut, each path a repeat may share (a record's "
              "keys outside `NEVER_SHARED_KEYS`, and the steps) is shared by some "
              "record, and each key only a record holds is held by some record "
              "- each table against what its walk reached: %r"
              % (dict((n, [e for e in t if e not in reached[n]])
                      for n, (t, _s) in tables.items()),),
              all(len(table) > 1 and reached[name] == table
                  for name, (table, _seen) in tables.items()))

        ptr_said = [(shape, _rk_said(doc, "#/$defs/testEvidence", pointer,
                                     M.POINTER_KEY), pointer == derived)
                    for shape, pointer, derived in pointers]
        ptr_said += [(name, _rk_said(doc, "#/$defs/testEvidence",
                                     M.pointer_for(row), M.POINTER_KEY), True)
                     for name, row in sorted(rows.items())]
        check("rk3 THE POINTER FORMS: the pointer each write left beside its "
              "record is the one `pointer_from_record` derives from it, and it - "
              "and the pointer `pointer_for` makes of every row - is accepted by "
              "the published `testEvidence`: %r"
              % ([p for p in ptr_said if p[1] or not p[2]],),
              pointers and all(not lines and same
                               for _s, lines, same in ptr_said))

        whole = [r for s, r in stored
                 if s == "a whole repeat sharing every equal subtree"]
        whole = whole[0] if whole else {}
        bare = dict(M.run_record(rows["source"]))
        bare.pop("steps", None)
        other = dict(whole, **{M.SHARED_KEY: [
            p for p in whole.get(M.SHARED_KEY) or [] if p != "steps"]
            or [M.GATE_REACH_KEY]})
        other.pop("steps", None)
        twins = dict((name, _rk_said(doc, "#/$defs/lastRun", r, M.RECORD_KEY))
                     for name, r in (("no steps, nothing shared", bare),
                                     ("no steps, others shared", other)))
        check("rk4 SECOND DIRECTION: a record with no `steps` that does not "
              "name them as shared is REFUSED, each naming `lastRun.steps` - "
              "the case that fails if the schema excused an absent `steps` "
              "whatever the record shares: %r" % (twins,),
              "steps" in (whole.get(M.SHARED_KEY) or [])
              and all(any("%s.steps" % (M.RECORD_KEY,) in line for line in lines)
                      for lines in twins.values()))

        placed = _rk_definitions(doc)
        check("rk5 ONE DEFINITION: every place the schema names a `lastRun` - a "
              "task's and a phase's - is a `$ref` to `$defs/lastRun`, so the "
              "shape these records are held to is the one validate-manifest "
              "reads at each place: %r" % (placed,),
              len(placed) >= 2
              and all((node or {}).get("$ref") == "#/$defs/lastRun"
                      for _w, node in placed))

        said = ((((doc.get("$defs") or {}).get("lastRun") or {})
                 .get("properties") or {}).get(M.BASE_RED_KEY) or {}) \
            .get("description") or ""
        positions = [w for w in ("first key", "last key") if w in said]
        check("rk6 THE CUT ORDER IS THE TABLE'S TO SAY: the published "
              "description of `lastRun.baseRed` names `RECORD_CUT_ORDER` for "
              "which key a record over its bound loses, and claims no position "
              "of its own - kept base runs are cut where that table puts them, "
              "which a sentence naming a position contradicted: %r"
              % ((positions, said[-400:]),),
              "RECORD_CUT_ORDER" in said and positions == []
              and "%s.%s" % (M.BASE_RED_KEY, M.BASE_RUNS_KEY)
              in M.RECORD_CUT_ORDER)
    except Exception as exc:                                   # noqa: BLE001
        check("rk0 the record-schema block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        restore()
        _harness.remove_tree(tmp)


# --- a record no reader can read: said, never raised, never read as absent ----
# THE MALFORMED SHAPES ARE THE SCHEMA'S OWN. Every field `$defs/lastRun` types -
# and every field of what a well-formed record holds under it, one level of
# objects and the first step down - is given each JSON value the schema reader
# refuses there, in turn, and each required field is taken out: the walk is
# derived, so a field the schema gains is a shape here with nothing to add.
_UR_VALUES = (None, True, 7, 1.5, "a string", ["a"], {"k": "v"})
_UR_GONE = object()
_UR_FILE = "docs/audit/phases/P1.json"
_UR_RUN = "UR1"


def _ur_base():
    """A record as the writer writes it, of a passed run of P1.1."""
    return M.run_record(_lr_row(_UR_RUN, "2026-11-18T11:00:00Z",
                                status="passed"))


def _ur_node(doc, node):
    """`node` with its `$ref` chain followed, `{}` for anything not a schema."""
    for _hop in range(8):
        if not (isinstance(node, dict) and "$ref" in node):
            break
        node = _json_schema.resolve(node["$ref"], doc)
    return node if isinstance(node, dict) else {}


def _ur_put(base, path, value):
    """A NEW copy of `base` with `value` at `path` - or the key taken out."""
    rec = json.loads(json.dumps(base))
    holder = rec
    for part in path[:-1]:
        holder = holder[part]
    if value is _UR_GONE:
        holder.pop(path[-1], None)
    else:
        holder[path[-1]] = value
    return rec


def _ur_held(base, path):
    value = base
    for part in path:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and isinstance(part, int) \
                and part < len(value):
            value = value[part]
        else:
            return _UR_GONE
    return value


def _ur_shapes(doc, base):
    """`[(field, record)]` - `base` with each field the schema types given each
    value its node refuses, and each required field the record holds taken
    out, `field` the dotted path the reader is expected to name."""
    out = []

    def walk(node, path, label):
        node = _ur_node(doc, node)
        for key, child in sorted((node.get("properties") or {}).items()):
            cpath, clabel = path + [key], "%s.%s" % (label, key)
            for value in _UR_VALUES:
                if _json_schema.check_findings(child, value, doc, clabel)[0]:
                    out.append((clabel, _ur_put(base, cpath, value)))
            held, cnode = _ur_held(base, cpath), _ur_node(doc, child)
            if isinstance(held, dict) and cnode.get("properties"):
                walk(cnode, cpath, clabel)
            items = _ur_node(doc, cnode.get("items"))
            if isinstance(held, list) and held and isinstance(held[0], dict) \
                    and items.get("properties"):
                walk(items, cpath + [0], "%s[0]" % (clabel,))
        for key in node.get("required") or []:
            if _ur_held(base, path + [key]) is not _UR_GONE:
                out.append(("%s.%s" % (label, key),
                            _ur_put(base, path + [key], _UR_GONE)))
    walk((doc.get("$defs") or {}).get("lastRun"), [], M.RECORD_KEY)
    return out


def _ur_walked_shapes(base):
    """The shapes the schema leaves untyped and a reader walks all the same:
    the run a repeat carries, and a kept base run, each holding a record that
    is not the record's shape; `(field, record)` as `_ur_shapes` gives."""
    bad_run = dict(base, runId="UR0", steps=5)
    repeat = dict(base, **{M.VERDICT_SOURCE: M.PART_REUSED,
                           "reusedFrom": {"runId": "UR0"},
                           M.REPEATED_RUN_KEY: bad_run})
    based = dict(base, **{M.BASE_RED_KEY: {"head": "abc123", M.BASE_RUNS_KEY: [
        dict(base, runId="UR9", steps=5)]}})
    return [("%s.%s.steps" % (M.RECORD_KEY, M.REPEATED_RUN_KEY), repeat),
            ("%s.%s.%s[0].steps" % (M.RECORD_KEY, M.BASE_RED_KEY,
                                    M.BASE_RUNS_KEY), based)]


def _ur_said(read, field, scope="task", subject="P1.1"):
    """Whether `read` (`read_rows`' answer) names exactly one unreadable record,
    of `subject` in `_UR_FILE`, at `field`, and says it in the string channel."""
    found = read.get("unreadableRecords") or []
    strings = read.get("unreadablePlanFiles") or []
    return (len(found) == 1 and found[0].get("file") == _UR_FILE
            and found[0].get("scope") == scope
            and found[0].get("subject") == subject
            and str(found[0].get("field") or "").startswith(field)
            and any(_UR_FILE in s and field in s for s in strings))


def _ur_read(root, mpath):
    try:
        return M.read_rows(root, manifest_path=mpath), None
    except Exception as exc:                                   # noqa: BLE001
        return {}, "%s: %s" % (type(exc).__name__, exc)


def _ur_runs(read):
    return [str(r.get("runId")) for r in read.get("rows") or []]


def _unreadable_record_cases(check):
    """(ur) A record that is not the shape the published schema gives is said
    as unreadable - its plan file, its subject and the field - and its run is
    not read, while every other run is; no reader raises on it."""
    tmp = _harness.fixture_root("audit-evidence-unreadable-")
    try:
        doc = _json_schema.load_document(_RK_SCHEMA)
        root = os.path.join(tmp, "ur")
        mpath, shards = ri_plan(root)
        base = _ur_base()
        ri_put_record(shards["P1"], "P1.2", dict(base, runId="UR-OTHER"))
        ri_put_record(shards["P1"], "P1.1", base)
        clean, raised = _ur_read(root, mpath)
        check("ur1 ALLOW: the record the writer writes reads, with nothing "
              "named unreadable and its run among the rows: %r"
              % ((raised, clean.get("unreadableRecords"),
                  clean.get("unreadablePlanFiles"), _ur_runs(clean)),),
              raised is None and not clean.get("unreadableRecords")
              and not clean.get("unreadablePlanFiles")
              and _UR_RUN in _ur_runs(clean))
        shapes = _ur_shapes(doc, base)
        walked = _ur_walked_shapes(base)
        wrong = []
        for field, record in shapes + walked:
            ri_put_record(shards["P1"], "P1.1", record)
            read, raised = _ur_read(root, mpath)
            if raised or _UR_RUN in _ur_runs(read) \
                    or "UR-OTHER" not in _ur_runs(read) \
                    or not _ur_said(read, field):
                wrong.append((field, raised, read.get("unreadableRecords"),
                              read.get("unreadablePlanFiles")))
        fields = sorted(set(f for f, _r in shapes))
        check("ur2 EVERY FIELD THE SCHEMA TYPES, GIVEN EACH VALUE IT REFUSES, "
              "and each required field taken out, and the carried run and a "
              "kept base run each malformed: the read does not raise, the run "
              "is not read, the other task's run still is, and the record is "
              "named once - file, subject and field - in `unreadableRecords` "
              "and in the string channel. %d shape(s) over %d field(s); wrong: "
              "%r" % (len(shapes) + len(walked), len(fields), wrong[:6]),
              wrong == [] and len(fields) >= 20
              and all(any(f.startswith("%s.%s" % (M.RECORD_KEY, k))
                          for f in fields)
                      for k in ("runId", "status", "steps", "testedState",
                                "recordCut", "sharedWithRepeated")))
        ri_put_record(shards["P1"], None, dict(base, runId="UR-PHASE",
                                               steps=5))
        ri_put_record(shards["P1"], "P1.1", base)
        read, raised = _ur_read(root, mpath)
        check("ur3 A PHASE'S RECORD is named by its own place - scope phase, "
              "subject the phase - and the task's well-formed record beside it "
              "still reads: %r" % ((raised, read.get("unreadableRecords")),),
              raised is None and _ur_said(read, "%s.steps" % (M.RECORD_KEY,),
                                          scope="phase", subject="P1")
              and _UR_RUN in _ur_runs(read)
              and "UR-PHASE" not in _ur_runs(read))
        ri_put_record(shards["P1"], None, dict(base, runId="UR-PHASE"))
        listed = dict(base, **{M.SHARED_KEY: ["%s.inner" % (M.GATE_REACH_KEY,)],
                               M.GATE_REACH_KEY: ["a", "list"],
                               M.VERDICT_SOURCE: M.PART_REUSED,
                               "reusedFrom": {"runId": "UR0"},
                               M.REPEATED_RUN_KEY: dict(
                                   base, runId="UR0",
                                   **{M.GATE_REACH_KEY: {"inner": {"x": 1}}})})
        ri_put_record(shards["P1"], "P1.1", listed)
        read, raised = _ur_read(root, mpath)
        resolved = M.resolved_shared(listed)
        # The share is resolved before the record is projected: the path is
        # left unresolved and the field as it was, and the field - a list
        # where the writer writes an object - then makes the record one that
        # will not read, which is said, never raised.
        check("ur4 A SHARED PATH THROUGH A FIELD THAT IS NOT AN OBJECT is not "
              "given back and is named unresolved, never written over the "
              "field - and the record, holding that field in no shape the "
              "writer writes, is named unreadable rather than raised on: %r"
              % ((raised, resolved.get(M.SHARED_UNRESOLVED_KEY),
                  resolved.get(M.GATE_REACH_KEY),
                  read.get("unreadableRecords")),),
              raised is None
              and resolved.get(M.SHARED_UNRESOLVED_KEY)
              == ["%s.inner" % (M.GATE_REACH_KEY,)]
              and resolved.get(M.GATE_REACH_KEY) == ["a", "list"]
              and [e.get("subject") for e in read.get("unreadableRecords")
                   or [] if M.GATE_REACH_KEY in str(e.get("field"))]
              == ["P1.1"]
              and _UR_RUN not in _ur_runs(read))
        said = M.unreadable_records_sentence(
            [{"file": _UR_FILE, "scope": "task", "subject": "P1.%d" % (i,),
              "key": M.RECORD_KEY, "field": "lastRun.status",
              "why": "lastRun.status %r is not one of the words" % ("x" * 5000,)}
             for i in range(400)])
        check("ur5 THE ONE SENTENCE is bounded whatever the plan holds - four "
              "hundred records each naming a five-thousand-character value - "
              "and still names the first record's file, subject and field: "
              "%r" % (said,),
              len(said) < 4000 and _UR_FILE in said and "P1.1" in said
              and "lastRun.status" in said and "more" in said)
    except Exception as exc:                                   # noqa: BLE001
        check("ur0 the unreadable-record block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- a record's identity is where it sits, and one table keeps record keys out -
def _record_identity_cases(check):
    """(ri-id) `record_row` drops every key a record is defined not to carry
    before placement is applied, and the keys only a record holds are one
    table that the writer's copy of a row and the reader's copy of a record
    both leave out."""
    base = _ur_base()
    planted = dict(base, taskId="P1.2", scope="task", phaseId="PX",
                   ts="2001-01-01T00:00:00Z", v=9, prev="sha256:x",
                   hash="sha256:y")
    phase_row = M.record_row(planted, "phase", "P1", "P1")
    task_row = M.record_row(dict(planted, taskId="P9.9"), "task", "P1.1", "P1")
    check("id1 IDENTITY IS WHERE THE RECORD SITS: a phase's record carrying a "
          "task id, a scope, a phase id, a ts and the chain's keys reads as "
          "the phase's run with none of them, and a task's record naming "
          "another task reads as its own task's: %r / %r"
          % (dict((k, phase_row.get(k, "-")) for k in
                  ("scope", "taskId", "phaseId", "ts", "v", "prev", "hash")),
             dict((k, task_row.get(k, "-")) for k in
                  ("scope", "taskId", "phaseId"))),
          phase_row.get("scope") == "phase" and "taskId" not in phase_row
          and phase_row.get("phaseId") == "P1"
          and phase_row.get("ts") == base.get("at")
          and not any(k in phase_row for k in ("v", "prev", "hash"))
          and task_row.get("taskId") == "P1.1"
          and task_row.get("scope") == "task"
          and task_row.get("phaseId") == "P1")
    tmp = _harness.fixture_root("audit-evidence-identity-")
    try:
        root = os.path.join(tmp, "id")
        mpath, shards = ri_plan(root)
        ri_put_record(shards["P1"], None, planted)
        read = M.read_rows(root, manifest_path=mpath)
        bound = [r.get("runId") for r in read["rows"]
                 if M._same_subject(r, {"taskId": "P1.2", "phaseId": "P1"})]
        check("id2 ...so a task with no record of its own is bound to no "
              "run, with no ledger at all and the phase's record planting the "
              "task's id: %r" % (bound,),
              bound == [] and _UR_RUN in _ur_runs(read))
    finally:
        _harness.remove_tree(tmp)
    table = list(getattr(M, "RECORD_ONLY_KEYS", ()))
    given = list(getattr(M, "RECORD_ONLY_READ", ()))
    row = dict(_lr_row("ID1", "2026-11-18T11:00:00Z", status="passed"),
               **dict((k, ["planted"]) for k in table))
    written = M.run_record(row)
    held = dict(base, **dict((k, ["planted"]) for k in table))
    read_back = M.record_row(held, "task", "P1.1", "P1")
    check("id3 ONE TABLE OF THE KEYS ONLY A RECORD HOLDS, both directions: a "
          "row carrying each of them writes a record holding none, and a "
          "record holding each reads back as a row holding only the ones the "
          "reader gives back by name: table %r, given %r, written %r, read %r"
          % (table, given, [k for k in table if k in written],
             [k for k in table if k in read_back]),
          len(table) >= 6 and set(given) <= set(table)
          and [k for k in table if k in written] == []
          and sorted(k for k in table if k in read_back) == sorted(given))
    source_record = dict(M.run_record(_lr_row("ID0", "2026-11-18T10:00:00Z",
                                              status="passed"),
                                      launch="tok-src"),
                         **{M.REPLACED_KEY: [{"runId": "IDX", "launch": "tok-x",
                                              "status": "passed",
                                              "at": "2026-11-18T09:00:00Z"}],
                            M.SHARED_UNRESOLVED_KEY: ["gateReach"],
                            M.REPEAT_UNREAD_KEY: {"runId": "IDY",
                                                  "basis": "stale"}})
    source = M.record_row(source_record, "task", "P1.1", "P1")
    repeat = dict(_lr_row("ID2", "2026-11-18T11:00:00Z", status="passed"),
                  steps=[], **{M.VERDICT_SOURCE: M.REUSED,
                               "reusedFrom": {"runId": "ID0",
                                              "ts": "2026-11-18T10:00:00Z",
                                              "status": "passed"}})
    carried = M.resolved_shared(M.run_record(repeat, source=source)).get(
        M.REPEATED_RUN_KEY) or {}
    check("id4 A SOURCE READ BACK FROM A RECORD carries none of the keys only "
          "a record holds into the run a repeat carries - its replaced "
          "launches, its unresolved marker, its unread marker: %r"
          % ([k for k in table if k in carried],),
          carried.get("runId") == "ID0" and table
          and [k for k in table if k in carried] == [])


# --- the release guard refuses what its reader could not read ------------------
# THE REAL HOOK, AS A PROCESS, on a tag command it only reads: the payload is the
# one Claude Code hands a PreToolUse hook, and the deny is read off its stdout.
_UG_HOOK = os.path.join(_output.REPO_ROOT, ".claude", "hooks",
                        "guard-release.py")
_UG_INJECT = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ug_guard", sys.argv[1])
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
kind = sys.argv[2]
def boom(*_a, **_k):
    if kind == "SystemExit":
        raise SystemExit(0)
    if kind == "KeyboardInterrupt":
        raise KeyboardInterrupt()
    if kind == "RecursionError":
        raise RecursionError("injected recursion")
    if kind == "MemoryError":
        raise MemoryError()
    raise RuntimeError("injected where no record is read")
guard.read_bugs = boom
raise SystemExit(guard.main())
'''
_UG_KINDS = ("RuntimeError", "SystemExit", "KeyboardInterrupt",
             "RecursionError", "MemoryError")


def _ug_project(tmp, name):
    """A git project whose plan names a full gate and holds no merged phase and
    no bug, so nothing holds a release: `(root, manifest, shards)`."""
    root = os.path.join(tmp, name)
    mpath, shards = ri_plan(root)
    with io.open(mpath, encoding="utf-8") as fh:
        index = json.load(fh)
    index["meta"].update({"fullGate": ["full"],
                          "buildCommands": {"full": "true"}})
    index["bugs"] = []
    with io.open(mpath, "w", encoding="utf-8") as fh:
        json.dump(index, fh)
    _harness.git(None, "init", "-q", root, prefix=("git",))
    return root, mpath, shards


def _ug_payload(root, command="git tag v9.9.9"):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "session_id": "ug", "cwd": root,
                       "tool_input": {"command": command}})


def _ug_env(root):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = root
    return env


def _ug_run(root, stdin, argv=None):
    """`(exit, deny reason or None, stdout, stderr)` of the hook on `stdin`."""
    done = subprocess.run(argv or [sys.executable, _UG_HOOK], cwd=root,
                          env=_ug_env(root), input=stdin, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)
    reason = None
    try:
        said = json.loads(done.stdout or "null") or {}
        out = said.get("hookSpecificOutput") or {}
        if out.get("permissionDecision") == "deny":
            reason = str(out.get("permissionDecisionReason") or "")
    except ValueError:
        reason = None
    return done.returncode, reason, done.stdout, done.stderr


def _ug_closed_stdout(root, stdin):
    """`(exit, stderr)` of the hook with the read end of its stdout closed
    before it writes - a deny that cannot be written on stdout."""
    proc = subprocess.Popen([sys.executable, _UG_HOOK], cwd=root,
                            env=_ug_env(root), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        proc.stdout.close()
        proc.stdin.write(stdin.encode("utf-8"))
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return proc.returncode, err


def _ug_write_shard(shards, body_text):
    with io.open(shards["P1"], "w", encoding="utf-8") as fh:
        fh.write(body_text)


def _guard_unreadable_cases(check):
    """(ug) The release guard refuses when its reader could not read what the
    plan holds - each malformed record, a malformed held run, a shard that is
    not an object, a value too deep to parse - naming the file and the field;
    it refuses when its decision raises at all, whatever is raised; and it
    lets a well-formed plan with nothing held through."""
    tmp = _harness.fixture_root("audit-evidence-guard-unread-")
    try:
        doc = _json_schema.load_document(_RK_SCHEMA)
        root, _mpath, shards = _ug_project(tmp, "ug")
        base = _ur_base()
        with io.open(shards["P1"], encoding="utf-8") as fh:
            pristine = fh.read()
        ri_put_record(shards["P1"], "P1.1", base)
        code, reason, out, err = _ug_run(root, _ug_payload(root))
        check("ug1 ALLOW: a well-formed plan holding a well-formed record and "
              "nothing that holds a release lets the tag command through - no "
              "deny, exit 0 - the case that goes red on a guard that refuses "
              "everything: %r" % ((code, reason, out[-300:], err[-300:]),),
              code == 0 and reason is None and out.strip() == "")
        shapes = _ur_shapes(doc, base) + _ur_walked_shapes(base)
        missed = []
        for field, record in shapes:
            ri_put_record(shards["P1"], "P1.1", record)
            code, reason, out, err = _ug_run(root, _ug_payload(root))
            if code != 0 or reason is None or _UR_FILE not in reason \
                    or field not in reason or "Traceback" in err:
                missed.append((field, code, (reason or out)[-200:],
                               err[-200:]))
        check("ug2 RED-FIRST: EACH MALFORMED RECORD the schema's own fields "
              "derive, fed through the real hook on a tag command, is a DENY "
              "naming the plan file and the field, exit 0 and no traceback - "
              "%d shape(s); not denied as said: %r" % (len(shapes), missed[:4]),
              len(shapes) >= 40 and missed == [])
        ri_put_record(shards["P1"], "P1.1", base)
        code, reason, _o, _e = _ug_run(root, _ug_payload(root, "ls -la"))
        check("ug3 ALLOW: an ordinary command is never judged - over the same "
              "plan it is no deny: %r" % ((code, reason),),
              code == 0 and reason is None)
        held_shapes = [
            ("%s is not a list" % (M.FULL_GATE_RUNS_KEY,), 5,
             M.FULL_GATE_RUNS_KEY),
            ("a held run naming no run id", [{"runId": 5}],
             "%s[0].runId" % (M.FULL_GATE_RUNS_KEY,))]
        held_wrong = []
        for label, value, field in held_shapes:
            with io.open(shards["P1"], encoding="utf-8") as fh:
                body = json.load(fh)
            body[M.FULL_GATE_RUNS_KEY] = value
            _ug_write_shard(shards, json.dumps(body))
            code, reason, out, err = _ug_run(root, _ug_payload(root))
            if reason is None or field not in reason or _UR_FILE not in reason:
                held_wrong.append((label, code, (reason or out)[-200:]))
        check("ug4 A MALFORMED HELD FULL RUN - the value not a list, an entry "
              "naming no run id - is a deny naming the file and the key as "
              "the held-run reader names it: %r" % (held_wrong,),
              held_wrong == [])
        # A shard too deep to parse is named by the shard: the guard's
        # structure read asks each shard before the plan is assembled, so the
        # deny names the file to repair, never the index pointing at it.
        others = [("a shard that is valid JSON but not an object", "[1, 2]",
                   _UR_FILE),
                  ("a value nested too deep to parse",
                   '{"id": "P1", "tasks": [], "muted": %s1%s}'
                   % ("[" * 200000, "]" * 200000),
                   "%s, the shard phases[0] names, could not be read as JSON"
                   % (_UR_FILE,))]
        other_wrong = []
        for label, text, named in others:
            _ug_write_shard(shards, text)
            code, reason, out, err = _ug_run(root, _ug_payload(root))
            # The file is matched in either separator: the guard names a plan it
            # could not load by its `os.path.join` spelling, which on Windows
            # read `docs\audit\audit-plan.json could not be read` in CI, while
            # its structure check names the same file with `/`. Only the
            # platform's own separator is folded, so a deny naming another
            # file, or none, is still red.
            said = (reason or "").replace(os.sep, "/")
            if code != 0 or reason is None or named not in said \
                    or "Traceback" in err:
                # The WHOLE deny and stderr, and the platform: a row that is red
                # on one platform alone has to say which reader refused there.
                other_wrong.append((label, code, named, reason or out,
                                    err[-1500:]))
        check("ug5 A SHARD THAT IS NOT AN OBJECT, and one nested past what the "
              "parser takes, is a deny naming the plan file that would not "
              "read, exit 0: %r"
              % ([row[:3] for row in other_wrong],), other_wrong == [],
              "on %s (python %s, recursion limit %d): %r"
              % (sys.platform, sys.version.split()[0], sys.getrecursionlimit(),
                 other_wrong))
        _ug_write_shard(shards, pristine)
        ri_put_record(shards["P1"], "P1.1", dict(base, status="x" * 1000000))
        code, reason, _o, _e = _ug_run(root, _ug_payload(root))
        check("ug6 A HUGE VALUE in a malformed record is a deny that stays "
              "bounded - a million-character status - naming the field: "
              "%r chars" % (len(reason or ""),),
              code == 0 and reason is not None and len(reason) < 8000
              and "%s.status" % (M.RECORD_KEY,) in reason)
        ri_put_record(shards["P1"], "P1.1", base)
        injected = []
        for kind in _UG_KINDS:
            code, reason, out, err = _ug_run(
                root, _ug_payload(root),
                argv=[sys.executable, "-c", _UG_INJECT, _UG_HOOK, kind])
            injected.append((kind, code, reason is not None
                             and kind in (reason or ""), (reason or out)[-160:],
                             err[-160:]))
        check("ug7 RED-FIRST: AN ERROR WHERE NO RECORD IS READ - the bug read "
              "raising - is a deny naming what was raised, for every kind a "
              "decision can end in: an ordinary error, SystemExit, "
              "KeyboardInterrupt, RecursionError, MemoryError, each exit 0: %r"
              % (injected,),
              all(code == 0 and named for _k, code, named, _r, _e in injected))
        odd = []
        for text in ("[1, 2]", '"a string"', "7", "null"):
            code, reason, out, err = _ug_run(root, text)
            odd.append((text, code, reason, out.strip()[:80], err[-120:]))
        check("ug8 A PAYLOAD THAT IS NOT A TOOL CALL - JSON that is not an "
              "object - stays on the one fail-open branch it had: nothing to "
              "judge, exit 0, no output: %r" % (odd,),
              all(code == 0 and reason is None and said == ""
                  for _t, code, reason, said, _e in odd))
        ri_put_record(shards["P1"], "P1.1", dict(base, steps=5))
        code, err = _ug_closed_stdout(root, _ug_payload(root))
        check("ug9 A DENY THAT CANNOT BE WRITTEN ON STDOUT is written on stderr "
              "with exit 2, the code that blocks a PreToolUse call - never an "
              "exit that lets the command through: %r" % ((code, err[-300:]),),
              code == 2 and "[guard-release]" in err
              and "%s.steps" % (M.RECORD_KEY,) in err)
    except Exception as exc:                                   # noqa: BLE001
        check("ug0 the release-guard block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- every surface that reads runs says the unreadable record -----------------
# Five real commands, and the binding through its reader: each, over a plan
# carrying a malformed record, exits with no traceback and names the plan file,
# the subject and the field. EVERY SHAPE goes through the reader in-process
# (`ur2`); the commands take a SAMPLE derived from the same walk - the first,
# middle and last shape - because a full table of processes per shape is a
# minute of wall clock for one answer the reader already gave.
def _us_commands(root, mpath, out_dir):
    scripts = _output.SCRIPTS_DIR
    py = sys.executable
    return [
        ("status", [py, os.path.join(scripts, "status", "audit-status.py"),
                    mpath]),
        ("status --json", [py, os.path.join(scripts, "status",
                                            "audit-status.py"), mpath,
                           "--json"]),
        ("report", [py, os.path.join(scripts, "report", "render-report.py"),
                    mpath, "--out-dir", out_dir, "--format", "md"]),
        ("doctor", [py, os.path.join(scripts, "status", "audit-doctor.py"),
                    "--project", root]),
        ("panel state", [py, "-c",
                         "import sys,json;sys.path.insert(0,%r);"
                         "import _output;_output.install_path();"
                         "import _panel_state;"
                         "print(json.dumps(_panel_state.build_state(%r),"
                         "default=str))" % (scripts, root)]),
    ]


def _us_text(out_dir):
    said = []
    for name in sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []:
        with io.open(os.path.join(out_dir, name), encoding="utf-8",
                     errors="replace") as fh:
            said.append(fh.read())
    return "\n".join(said)


def _surface_unreadable_cases(check):
    """(us) Status, its --json, the report, the doctor, the panel's state
    payload and the binding, each over a plan carrying a malformed record,
    exit with no traceback and name the file, the subject and the field."""
    import _verdict_binding
    tmp = _harness.fixture_root("audit-evidence-surfaces-")
    try:
        doc = _json_schema.load_document(_RK_SCHEMA)
        base = _ur_base()
        shapes = _ur_shapes(doc, base)
        sample = [shapes[i] for i in sorted(set(
            [0, len(shapes) // 2, len(shapes) - 1]))] if shapes else []
        table, wrong, keyed = [], [], []
        for n, (field, record) in enumerate(sample):
            root, mpath, shards = _ug_project(tmp, "us%d" % (n,))
            ri_put_record(shards["P1"], "P1.1", record)
            out_dir = os.path.join(root, "out")
            for name, argv in _us_commands(root, mpath, out_dir):
                done = subprocess.run(argv, cwd=root, env=_ug_env(root),
                                      capture_output=True, text=True,
                                      encoding="utf-8", errors="replace",
                                      timeout=300)
                text = done.stdout + done.stderr + (
                    _us_text(out_dir) if name == "report" else "")
                named = (_UR_FILE in text and "P1.1" in text
                         and field in text)
                table.append((field, name, done.returncode,
                              "Traceback" in text, named))
                if "Traceback" in text or not named:
                    wrong.append((field, name, done.returncode, text[-300:]))
                if name == "status --json":
                    try:
                        keyed.append(json.loads(done.stdout).get(
                            "unreadableRecords"))
                    except ValueError:
                        keyed.append("unparsable: %r" % (done.stdout[-200:],))
            got = _verdict_binding.binding(
                root, {"taskId": "P1.1", "phaseId": "P1"}, ["sweep"], "task",
                [], mpath, "run the gate", "no gate here")
            said = got.get("sentence") or ""
            table.append((field, "binding", got.get("arm"), False,
                          _UR_FILE in said and field in said))
            if got.get("arm") != _verdict_binding.ARM_UNREADABLE \
                    or _UR_FILE not in said or field not in said:
                wrong.append((field, "binding", got.get("arm"), said[-300:]))
        check("us1 RED-FIRST: OVER A PLAN CARRYING A MALFORMED RECORD every "
              "surface exits with no traceback and names the plan file, the "
              "subject and the field - status, status --json, the report, "
              "the doctor, the panel's state payload - and the binding "
              "refuses on the unreadable arm saying the same: %d run(s) over "
              "%d sampled shape(s) of %d; wrong: %r"
              % (len(table), len(sample), len(shapes), wrong[:4]),
              len(sample) == 3 and len(table) == 18 and wrong == [])
        check("us2 ...and status --json carries them under "
              "`unreadableRecords`, one entry per record naming its file, "
              "scope, subject, key and field: %r" % (keyed,),
              len(keyed) == 3
              and all(isinstance(k, list) and len(k) == 1
                      and k[0].get("file") == _UR_FILE
                      and k[0].get("scope") == "task"
                      and k[0].get("subject") == "P1.1"
                      and k[0].get("key") == M.RECORD_KEY
                      and k[0].get("field") for k in keyed))
    except Exception as exc:                                   # noqa: BLE001
        check("us0 the surfaces block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- the full run a phase holds: the third place's answer, in the plan --------
# THE ORACLE IS THE ROWS. `_full_status_cases` is the table of full_status
# fixtures; `_fh_oracle` runs it with `full_status` watched, and at each call
# puts the same runs through the plan's own path - every run offered, oldest
# first, to `held_choice`, the one decision the writer makes - then asks
# `full_status` again of the runs the plan would hold alone. What is compared
# is derived per fixture (`_fh_kind`), never listed by hand.
FH_FULL = "word, run and basis"
FH_WORD_DISQUALIFIED = ("word alone: the run the rows' basis names cannot "
                        "certify, and the plan holds no run that cannot")
FH_WORD_FIRST = ("word alone: more than one run contains the merge, and the "
                 "plan keeps the first that certified it where the rows name "
                 "the newest")
_FH_GIT = ["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
           "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def _fh_full_rows(rows):
    return [r for r in rows or [] if isinstance(r, dict)
            and r.get("scope") == M.FULL_SCOPE]


def _fh_held_over(rows, phase, declared, git_root, run):
    """The runs the plan would hold for `phase` after every run of `rows` was
    recorded in the order of its moment - None when it would hold none."""
    held = None
    for row in M.oldest_first(_fh_full_rows(rows)):
        chosen = M.held_choice(phase, held, row, declared, git_root, run=run)
        if chosen is not None:
            held = chosen
    return held


def _fh_rows_of(held):
    """The rows `read_rows` gives back for a list of held runs."""
    return [r for r in (M.held_run_row(h) for h in held or []) if r]


def _fh_kind(rows, phase, declared, git_root, run, got):
    """Which of the three comparisons a fixture owes, from its own runs."""
    if not declared or not phase.get("mergedHead") or got.get("runId") is None:
        return FH_FULL
    deciding = M.row_by_run(rows, got["runId"])
    if deciding is None or M._full_disqualification(deciding,
                                                    declared) is not None:
        return FH_WORD_DISQUALIFIED
    if got["answer"] == _manifest_vocab.FULL_STATUS_WHOLE:
        containing = [
            r for r in _fh_full_rows(rows)
            if M._full_disqualification(r, declared) is None
            and M._worktrees.merged_into(
                git_root, phase["mergedHead"],
                (r.get("testedState") or {}).get("head"),
                run=run)["answer"] == M._worktrees.CONTAINED]
        if len(containing) > 1:
            return FH_WORD_FIRST
    return FH_FULL


def _fh_oracle():
    """`[entry]`, one per `full_status` call the fixture table makes: the
    rows' answer, the plan's answer and the comparison owed - or the error
    that stopped the plan's side of one."""
    captured, real = [], M.full_status

    def spy(rows, phase, git_root, full_commands, run=None):
        got = real(rows, phase, git_root, full_commands, run=run)
        try:
            ph = phase if isinstance(phase, dict) else {}
            declared = list(full_commands or [])
            held = _fh_held_over(rows, ph, declared, git_root, run)
            on_plan = dict(ph)
            if held is not None:
                on_plan[M.FULL_GATE_RUNS_KEY] = held
            mine = real(_fh_rows_of(held), on_plan, git_root, declared,
                        run=run)
            captured.append({"rows": got, "plan": mine,
                             "kind": _fh_kind(rows, ph, declared, git_root,
                                              run, got)})
        except Exception as exc:                               # noqa: BLE001
            captured.append({"error": "%s: %s" % (type(exc).__name__, exc)})
        return got
    M.full_status = spy
    try:
        _full_status_cases(lambda *_a, **_k: None)
    finally:
        M.full_status = real
    return captured


def _fh_commit(root, name):
    """A commit on the branch checked out at `root` -> its sha."""
    with open(os.path.join(root, "%s.txt" % (name,)), "w",
              encoding="utf-8") as fh:
        fh.write("%s\n" % (name,))
    _harness.git(root, "add", "--", "%s.txt" % (name,), prefix=_FH_GIT,
                 timeout=30)
    _harness.git(root, "commit", "-qm", name, prefix=_FH_GIT, timeout=30)
    return _harness.git(root, "rev-parse", "HEAD", prefix=_FH_GIT,
                        timeout=30).strip()


def _fh_project(tmp, name, phases, sharded=True):
    """A git repository holding a plan with `meta.fullGate` and no evidence
    directory at all -> `(root, mpath)`. The plan is written beside the
    repository's history, not into it: what a run's head contains is the
    commits the case makes."""
    root = os.path.join(tmp, name)
    os.makedirs(os.path.join(root, "docs", "audit", "phases"))
    _project(root, {"manifestPath": "docs/audit/audit-plan.json"})
    _harness.git(root, "init", "-q", prefix=_FH_GIT, timeout=30)
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    meta = {"version": 3, "fullGate": ["x"], "buildCommands": {"x": "echo x"}}
    if not sharded:
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump({"meta": meta, "phases": phases}, fh)
        return root, mpath
    stubs = []
    for ph in phases:
        stubs.append({"id": ph["id"], "title": ph.get("title") or ph["id"],
                      "shard": "phases/%s.json" % (ph["id"],)})
        _fh_put(root, ph)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "phases": stubs}, fh)
    return root, mpath


def _fh_shard(root, pid):
    return os.path.join(root, "docs", "audit", "phases", "%s.json" % (pid,))


def _fh_put(root, phase):
    with open(_fh_shard(root, phase["id"]), "w", encoding="utf-8") as fh:
        json.dump(phase, fh)


def _fh_get(root, pid):
    with open(_fh_shard(root, pid), encoding="utf-8") as fh:
        return json.load(fh)


def _fh_bytes(root):
    out = {}
    for dirpath, _dirs, names in os.walk(os.path.join(root, "docs")):
        for name in sorted(names):
            path = os.path.join(dirpath, name)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, root)] = fh.read()
    return out


def _fh_declared(mpath):
    return M.full_gate_commands(M._mio.load_manifest(mpath))


def _fh_row(run_id, ts, head, mpath, **kw):
    return _fs_row(run_id, ts, head, _fh_declared(mpath), **kw)


def _fh_hold(root, mpath, row, validator=None):
    """The writer, as `run-test-gate.py --full --record` calls it."""
    import _manifest_rules
    return M.hold_full_run(
        root, mpath, row, _fh_declared(mpath), root,
        validator if validator is not None else _manifest_rules.bound_validator(),
        _manifest_rules.SCHEMA_CODE_PREFIX)


def _fh_answer(root, mpath, pid):
    """`(full_status over the plan alone, the read)` for phase `pid`."""
    read = M.read_rows(root, manifest_path=mpath)
    phase = [p for p in M._mio.load_manifest(mpath)["phases"]
             if p.get("id") == pid][0]
    return (M.full_status(read["rows"], phase, root, _fh_declared(mpath)),
            read)


def _fh_started(pid, commits=(), status="in_progress"):
    return {"id": pid, "title": pid, "status": status,
            "tasks": [{"id": "%s.%d" % (pid, i + 1), "title": "t",
                       "status": "done", "commit": c}
                      for i, c in enumerate(commits)]}


def _fh_good_held(head="a" * 40):
    return M.held_run_record(_fs_row("run-held", "2026-01-02T00:00:00Z", head,
                                     ["echo x"]))


def _fh_head_git(table, default=1):
    """A fake git whose `merge-base --is-ancestor <a> <b>` answers by `b`."""
    def run(git_root, args, timeout=None):
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return (table.get(args[3], default), "", "")
        return (0, "", "")
    return run


def _full_held_cases(check):
    """(fh) A full run's answer for a phase is in the plan: the run a phase
    holds answers as the rows do, a later red removes nothing, and a held
    run that is not the shape the writer writes never certifies."""
    oracle = _fh_oracle()
    errors = [e["error"] for e in oracle if "error" in e]
    words = [(e["rows"], e["plan"]) for e in oracle if "error" not in e
             and e["rows"]["answer"] != e["plan"]["answer"]]
    fulls = [(e["rows"], e["plan"]) for e in oracle if "error" not in e
             and e["kind"] == FH_FULL
             and (e["rows"]["runId"], e["rows"]["basis"])
             != (e["plan"]["runId"], e["plan"]["basis"])]
    table = dict((k, sum(1 for e in oracle if e.get("kind") == k))
                 for k in (FH_FULL, FH_WORD_DISQUALIFIED, FH_WORD_FIRST))
    check("fh1 ACCEPTANCE 1: over every full_status fixture the table holds, "
          "the plan's own answer is the rows' word, and the rows' run and "
          "basis wherever the fixture owes them - comparisons %r; errors %r; "
          "word differs %r; run or basis differs %r"
          % (table, errors, words[:2], fulls[:2]),
          oracle and not errors and not words and not fulls
          and all(table.values()))

    tmp = _harness.fixture_root("audit-evidence-held-")
    try:
        # --- acceptance 2: a later red removes no certification ------------
        root, mpath = _fh_project(tmp, "r2", [_fh_started("P1")])
        a = _fh_commit(root, "a")
        b = _fh_commit(root, "b")
        _fh_put(root, dict(_fh_started("P1", [a], status="done"),
                           mergedAt="2026-01-01T00:00:00Z", mergedHead=a))
        green = _fh_row("run-green", "2026-01-02T00:00:00Z", b, mpath)
        got = _fh_hold(root, mpath, green)
        res, read = _fh_answer(root, mpath, "P1")
        held_list = _fh_get(root, "P1").get(M.FULL_GATE_RUNS_KEY) or []
        held = held_list[0] if len(held_list) == 1 else {}
        check("fh2 a green, measured, clean, verbatim full run is held by the "
              "merged phase its head contains, with its id, head and moment, "
              "and with no ledger at all the phase reads WHOLE from the plan: "
              "%r / %r / %r / ledger %r"
              % (got, held_list, res, read["ledgerAbsent"]),
              got["held"] == ["P1"] and held.get("runId") == "run-green"
              and held.get("head") == b
              and held.get("at") == "2026-01-02T00:00:00Z"
              and res["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
              and res["runId"] == "run-green" and read["ledgerAbsent"])
        before = _fh_bytes(root)
        for case, row in (
                ("fh3 ACCEPTANCE 2: a later RED full run on a head that "
                 "contains the phase",
                 _fh_row("run-red", "2026-01-03T00:00:00Z", b, mpath,
                         status="failed")),
                ("fh3b a later full run on a DIRTY tree",
                 _fh_row("run-dirty", "2026-01-04T00:00:00Z", b, mpath,
                         dirty_outside=["src/x.ts"])),
                ("fh3c a later full run that counted nothing",
                 _fh_row("run-none", "2026-01-05T00:00:00Z", b, mpath,
                         ran_total=0))):
            said = _fh_hold(root, mpath, row)
            res, _read = _fh_answer(root, mpath, "P1")
            check("%s holds nothing and leaves every plan byte as it was, so "
                  "the phase still reads WHOLE by the run that certified it: "
                  "%r / %r" % (case, said, res),
                  said["held"] == [] and said["notHeld"]
                  and _fh_bytes(root) == before
                  and res["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
                  and res["runId"] == "run-green")
        newer = _fh_row("run-green-2", "2026-01-06T00:00:00Z", b, mpath)
        said = _fh_hold(root, mpath, newer)
        check("fh4 a later GREEN run that also contains it changes nothing "
              "either - a certification is written once, so a full run does "
              "not rewrite every shard it contains: %r" % (said,),
              said["held"] == [] and said["kept"] == ["P1"]
              and _fh_bytes(root) == before)

        # --- acceptance 3: what cannot be asked reads unknown ---------------
        root3, mpath3 = _fh_project(tmp, "r3", [
            dict(_fh_started("P1"), status="done",
                 mergedAt="2026-01-01T00:00:00Z"),
            dict(_fh_started("P2"), status="done",
                 mergedAt="2026-01-01T00:00:00Z", mergedHead="e" * 40)])
        c = _fh_commit(root3, "c")
        _fh_hold(root3, mpath3, _fh_row("run-c", "2026-01-02T00:00:00Z", c,
                                        mpath3))
        nohead, _r = _fh_answer(root3, mpath3, "P1")
        unasked, _r = _fh_answer(root3, mpath3, "P2")
        check("fh5 ACCEPTANCE 3: from the plan alone a merged phase with no "
              "mergedHead reads UNKNOWN saying so, and one whose mergedHead "
              "git cannot relate to the held run's head reads UNKNOWN with "
              "git's could-not-ask: %r / %r" % (nohead, unasked),
              nohead["answer"] == _manifest_vocab.FULL_STATUS_UNKNOWN
              and "no mergedHead" in nohead["basis"]
              and unasked["answer"] == _manifest_vocab.FULL_STATUS_UNKNOWN
              and "could not be established" in unasked["basis"]
              and unasked["runId"] == "run-c")

        # --- a run on the phase branch's tip, then a landing ----------------
        for name, merge_commit in (("ff", False), ("merge", True)):
            proj, mp = _fh_project(tmp, "land-" + name, [_fh_started("P1")])
            base = _fh_commit(proj, "base")
            _harness.git(proj, "checkout", "-q", "-b", "p1", prefix=_FH_GIT,
                         timeout=30)
            tip = _fh_commit(proj, "work")
            _fh_put(proj, _fh_started("P1", [tip]))
            tip_run = _fh_row("run-tip", "2026-01-02T00:00:00Z", tip, mp)
            first = _fh_hold(proj, mp, tip_run)
            _harness.git(proj, "checkout", "-q", "main", prefix=_FH_GIT,
                         timeout=30)
            main_run = _fh_row("run-main", "2026-01-03T00:00:00Z", base, mp)
            second = _fh_hold(proj, mp, main_run)
            if merge_commit:
                _fh_commit(proj, "other")
                _harness.git(proj, "merge", "-q", "--no-ff", "-m", "land",
                             "p1", prefix=_FH_GIT, timeout=30)
            else:
                _harness.git(proj, "merge", "-q", "--ff-only", "p1",
                             prefix=_FH_GIT, timeout=30)
            landed = _harness.git(proj, "rev-parse", "HEAD", prefix=_FH_GIT,
                                  timeout=30).strip()
            _fh_put(proj, dict(_fh_get(proj, "P1"), status="done",
                               mergedAt="2026-01-04T00:00:00Z",
                               mergedHead=landed))
            mine, read = _fh_answer(proj, mp, "P1")
            phase = _fh_get(proj, "P1")
            rows_say = M.full_status([tip_run, main_run], phase, proj,
                                     _fh_declared(mp))
            if merge_commit:
                check("fh7 a run on the branch tip, then a MERGE COMMIT "
                      "landing: with no ledger the plan answers what the "
                      "rows of the same two runs answer, word, run and "
                      "basis: plan %r / rows %r" % (mine, rows_say),
                      (mine["answer"], mine["runId"], mine["basis"])
                      == (rows_say["answer"], rows_say["runId"],
                          rows_say["basis"])
                      and read["ledgerAbsent"])
            else:
                check("fh6 a run on the branch tip before it lands, a later "
                      "run on main that does not contain the branch, then a "
                      "FAST-FORWARD landing: the started phase held the tip "
                      "run and kept it beside the newer main run, and with "
                      "no ledger the phase reads WHOLE by the tip run, as "
                      "the rows do: %r / %r / held %r / plan %r / rows %r"
                      % (first, second, phase.get(M.FULL_GATE_RUNS_KEY),
                         mine, rows_say),
                      first["held"] == ["P1"] and second["held"] == ["P1"]
                      and sorted(h.get("runId") for h in
                                 phase.get(M.FULL_GATE_RUNS_KEY) or [])
                      == ["run-main", "run-tip"]
                      and mine["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
                      and mine["runId"] == "run-tip"
                      and rows_say["answer"] == mine["answer"]
                      and rows_say["runId"] == mine["runId"]
                      and read["ledgerAbsent"])

        # --- a phase started after the run is not certified by it -----------
        proj, mp = _fh_project(tmp, "later", [
            _fh_started("P1"), _fh_started("P2", status="pending")])
        one = _fh_commit(proj, "one")
        _fh_put(proj, _fh_started("P1", [one]))
        p2 = _fh_get(proj, "P2")
        p2["tasks"] = []
        _fh_put(proj, p2)
        early = _fh_row("run-early", "2026-01-02T00:00:00Z", one, mp)
        said = _fh_hold(proj, mp, early)
        two = _fh_commit(proj, "two")
        _fh_put(proj, dict(_fh_started("P2", [two]), status="done",
                           mergedAt="2026-01-03T00:00:00Z", mergedHead=two))
        mine, _read = _fh_answer(proj, mp, "P2")
        rows_say = M.full_status([early], _fh_get(proj, "P2"), proj,
                                 _fh_declared(mp))
        check("fh8 a phase still pending when a full run is recorded holds "
              "nothing of it, and once started and landed after that run it "
              "is not certified by it: PROVISIONAL from the plan, naming the "
              "run a started phase held, as the rows say: %r / plan %r / "
              "rows %r" % (said, mine, rows_say),
              said["held"] == ["P1"]
              and M.FULL_GATE_RUNS_KEY not in p2
              and mine["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and (mine["runId"], mine["basis"])
              == (rows_say["runId"], rows_say["basis"]))

        # --- never held by nobody: an unmerged started phase takes it --------
        proj, mp = _fh_project(tmp, "nobody", [
            dict(_fh_started("P1"), status="done",
                 mergedAt="2026-01-01T00:00:00Z"), _fh_started("P2")])
        x = _fh_commit(proj, "x")
        _fh_put(proj, dict(_fh_get(proj, "P1"), mergedHead=x))
        _fh_hold(proj, mp, _fh_row("run-x", "2026-01-02T00:00:00Z", x, mp))
        y = _fh_commit(proj, "y")
        said = _fh_hold(proj, mp, _fh_row("run-y", "2026-01-03T00:00:00Z", y,
                                          mp))
        check("fh9 a qualifying run is held by a started phase that holds "
              "nothing reading whole, even while every merged phase is "
              "certified already - the merged phase keeps its own: %r / P1 "
              "%r / P2 %r"
              % (said, _fh_get(proj, "P1").get(M.FULL_GATE_RUNS_KEY),
                 _fh_get(proj, "P2").get(M.FULL_GATE_RUNS_KEY)),
              said["held"] == ["P2"] and said["kept"] == ["P1"]
              and [h.get("runId") for h in
                   _fh_get(proj, "P1").get(M.FULL_GATE_RUNS_KEY) or []]
              == ["run-x"]
              and [h.get("runId") for h in
                   _fh_get(proj, "P2").get(M.FULL_GATE_RUNS_KEY) or []]
              == ["run-y"])
        read = M.read_rows(proj, manifest_path=mp)
        check("fh10 a run two phases hold is read once, as one full-scope "
              "run, and its row came from the plan: %r"
              % ([(r.get("runId"), s) for r, s in zip(read["rows"],
                                                      read["rowSources"])],),
              sorted(r.get("runId") for r in read["rows"]
                     if r.get("scope") == M.FULL_SCOPE) == ["run-x", "run-y"]
              and set(read["rowSources"]) == set([M.ROW_FROM_RECORD]))

        # --- what else could remove or falsify a certification --------------
        proj, mp = _fh_project(tmp, "falsify", [
            dict(_fh_started("P1"), status="done",
                 mergedAt="2026-01-01T00:00:00Z")])
        m1 = _fh_commit(proj, "m1")
        _fh_put(proj, dict(_fh_get(proj, "P1"), mergedHead=m1))
        cert = _fh_row("run-cert", "2026-01-02T00:00:00Z", m1, mp)
        _fh_hold(proj, mp, cert)
        m2 = _fh_commit(proj, "m2")
        _fh_put(proj, dict(_fh_get(proj, "P1"), mergedHead=m2,
                           mergedHeadAt="2026-01-03T00:00:00Z"))
        mine, _r = _fh_answer(proj, mp, "P1")
        rows_say = M.full_status([cert], _fh_get(proj, "P1"), proj,
                                 _fh_declared(mp))
        later = _fh_row("run-later", "2026-01-04T00:00:00Z", m2, mp)
        said = _fh_hold(proj, mp, later)
        again, _r = _fh_answer(proj, mp, "P1")
        check("fh11 a mergedHead RE-RECORDED past the held run's head reads "
              "PROVISIONAL from the plan exactly as from the rows, and the "
              "next run that contains the new head replaces the held run "
              "and reads WHOLE: plan %r / rows %r / %r / %r"
              % (mine, rows_say, said, again),
              mine["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and (mine["answer"], mine["runId"], mine["basis"])
              == (rows_say["answer"], rows_say["runId"], rows_say["basis"])
              and said["held"] == ["P1"]
              and again["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
              and again["runId"] == "run-later")

        gone = dict(_fh_get(proj, "P1"))
        gone[M.FULL_GATE_RUNS_KEY] = [dict(h, head="e" * 40)
                                      for h in gone[M.FULL_GATE_RUNS_KEY]]
        res = M.full_status(_fh_rows_of(gone[M.FULL_GATE_RUNS_KEY]), gone,
                            proj, _fh_declared(mp))
        check("fh12 a held run whose head the history no longer holds (a "
              "rewrite made it unreachable) reads UNKNOWN with git's "
              "could-not-ask, never WHOLE: %r" % (res,),
              res["answer"] == _manifest_vocab.FULL_STATUS_UNKNOWN
              and res["runId"] == "run-later")

        held_now = _fh_get(proj, "P1")
        for case, commands, said_word in (
                ("fh13 a meta.fullGate that GAINS an entry after the "
                 "certification", ["echo x", "echo y"], "1 OF 2"),
                ("fh13b a meta.fullGate REORDERED after the certification",
                 ["echo y"], "verbatim")):
            rows_side = M.full_status([later], held_now, proj, commands)
            plan_side = M.full_status(
                _fh_rows_of(held_now[M.FULL_GATE_RUNS_KEY]), held_now, proj,
                commands)
            check("%s reads as the rows read the certifying run against the "
                  "gate declared now - not whole, the same basis: plan %r / "
                  "rows %r" % (case, plan_side, rows_side),
                  plan_side["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
                  and said_word in plan_side["basis"]
                  and (plan_side["runId"], plan_side["basis"])
                  == (rows_side["runId"], rows_side["basis"]))

        # --- two runs recorded out of order ---------------------------------
        phase = {"id": "P1", "mergedHead": "m" * 40}
        git_by_head = _fh_head_git({"h-in": 0, "h-out": 1, "h-ask": 128})
        newer_out = M.held_run_record(_fs_row("run-n", "2026-01-05T00:00:00Z",
                                              "h-out", ["echo x"]))
        older_out = _fs_row("run-o", "2026-01-04T00:00:00Z", "h-out",
                            ["echo x"])
        held_in = M.held_run_record(_fs_row("run-i", "2026-01-01T00:00:00Z",
                                            "h-in", ["echo x"]))
        held_ask = M.held_run_record(_fs_row("run-a", "2026-01-01T00:00:00Z",
                                             "h-ask", ["echo x"]))
        def ids(chosen):
            return (None if chosen is None
                    else sorted(h.get("runId") for h in chosen))
        unchanged = [
            ids(M.held_choice(phase, [newer_out], older_out, ["echo x"], "/",
                              run=git_by_head)),
            ids(M.held_choice(phase, [held_in], _fs_row(
                "run-i2", "2026-01-09T00:00:00Z", "h-in", ["echo x"]),
                ["echo x"], "/", run=git_by_head))]
        changed = [
            ids(M.held_choice(phase, [held_ask], _fs_row(
                "run-o2", "2026-01-09T00:00:00Z", "h-out", ["echo x"]),
                ["echo x"], "/", run=git_by_head)),
            ids(M.held_choice(phase, [newer_out], _fs_row(
                "run-i3", "2026-01-02T00:00:00Z", "h-in", ["echo x"]),
                ["echo x"], "/", run=git_by_head)),
            ids(M.held_choice(phase, [held_ask], _fs_row(
                "run-a2", "2026-01-09T00:00:00Z", "h-ask", ["echo x"]),
                ["echo x"], "/", run=git_by_head))]
        check("fh14 RUNS RECORDED OUT OF ORDER keep the rows' walk: an older "
              "run of the same standing as the newest held one changes "
              "nothing, a held run that reads whole is never replaced, a "
              "could-not-ask is kept beside a newer definite does-not-contain, "
              "an older run that contains the merge is kept beside the newest, "
              "and a newer could-not-ask replaces an older one: unchanged %r / "
              "changed %r" % (unchanged, changed),
              unchanged == [None, None]
              and changed == [["run-a", "run-o2"], ["run-i3", "run-n"],
                              ["run-a2"]])

        # --- a held run that is not the writer's shape never certifies ------
        good = _fh_good_held()
        contains = _fh_head_git({}, default=0)
        allow = M.full_status([M.held_run_row(good)],
                              dict(phase, **{M.FULL_GATE_RUNS_KEY: [good]}),
                              "/", ["echo x"], run=contains)
        check("fh15 ALLOW: the shape the writer writes reads WHOLE when its "
              "head contains the merge, and its basis names no malformation: "
              "%r" % (allow,),
              allow["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
              and M.FULL_GATE_RUNS_KEY not in allow["basis"])
        bad = [
            ("a", "not a list", None),
            ("b", ["not an object"], "[0]"),
            ("c", [dict(good, status="failed")], "status"),
            ("d", [dict(good, status="verified")], "status"),
            ("e", [dict((k, v) for k, v in good.items() if k != "status")],
             "status"),
            ("f", [dict(good, digest="abc")], "digest"),
            ("g", [dict(good, digest="sha256:" + "Z" * 64)], "digest"),
            ("h", [dict(good, digest="sha1:" + "a" * 40)], "digest"),
            ("i", [dict(good, entries="1")], "entries"),
            ("j", [dict(good, entries=True)], "entries"),
            ("k", [dict(good, entries=0)], "entries"),
            ("l", [dict(good, runId="  ")], "runId"),
            ("m", [dict((k, v) for k, v in good.items() if k != "runId")],
             "runId"),
            ("n", [dict(good, head="")], "head"),
            ("o", [dict(good, head=7)], "head"),
            ("p", [dict(good, at="")], "at"),
            ("q", [dict((k, v) for k, v in good.items() if k != "at")], "at"),
        ]
        for letter, value, field in bad:
            rows = _fh_rows_of(value if isinstance(value, list) else [])
            res = M.full_status(rows,
                                dict(phase, **{M.FULL_GATE_RUNS_KEY: value}),
                                "/", ["echo x"], run=contains)
            check("fh16%s a held run malformed in `%s` is read as not held - "
                  "no row, not WHOLE - with a basis naming %s and the field: "
                  "%r / %r" % (letter, field or "the value",
                               M.FULL_GATE_RUNS_KEY, rows, res),
                  rows == []
                  and res["answer"] != _manifest_vocab.FULL_STATUS_WHOLE
                  and M.FULL_GATE_RUNS_KEY in res["basis"]
                  and (field is None or field in res["basis"]))

        # --- the plan file: one-file layout, refusal, schema, bound ---------
        proj, mp = _fh_project(tmp, "onefile", [
            dict(_fh_started("P1"), status="done",
                 mergedAt="2026-01-01T00:00:00Z")], sharded=False)
        o = _fh_commit(proj, "o")
        with open(mp, encoding="utf-8") as fh:
            body = json.load(fh)
        body["phases"][0]["mergedHead"] = o
        with open(mp, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        before = _fh_bytes(proj)
        refusing = _types_namespace(
            validate=lambda m, today=None: (
                ["rules.schema.x: refused"] if any(
                    M.FULL_GATE_RUNS_KEY in p for p in m.get("phases") or [])
                else [], []), unreadable=[])
        refused = _fh_hold(proj, mp, _fh_row("run-o", "2026-01-02T00:00:00Z",
                                             o, mp), validator=refusing)
        check("fh17 a plan the held run would not leave valid is refused "
              "before the save, every byte as it was, the refusal named: %r"
              % (refused,),
              refused["held"] == [] and refused["refused"]
              and "refused" in str(refused["refused"])
              and _fh_bytes(proj) == before)
        ok = _fh_hold(proj, mp, _fh_row("run-o", "2026-01-02T00:00:00Z", o,
                                        mp))
        res, _r = _fh_answer(proj, mp, "P1")
        check("fh18 in the one-file layout the held run goes on the phase "
              "in the plan file itself and reads WHOLE from it: %r / %r"
              % (ok, res),
              ok["held"] == ["P1"]
              and res["answer"] == _manifest_vocab.FULL_STATUS_WHOLE)

        doc = _json_schema.load_document(_RK_SCHEMA)
        # Every value the writer composes, read off the plan files it wrote.
        composed = []
        for base_dir, _dirs, names in os.walk(tmp):
            for name in names:
                if not name.endswith(".json") or "audit" not in base_dir:
                    continue
                with open(os.path.join(base_dir, name), encoding="utf-8") as fh:
                    try:
                        body = json.load(fh)
                    except ValueError:
                        continue
                for ph in ([body] if "tasks" in body else
                           body.get("phases") or []):
                    if isinstance(ph, dict) and M.FULL_GATE_RUNS_KEY in ph:
                        composed.append(("%s %s" % (name, ph.get("id")),
                                         ph[M.FULL_GATE_RUNS_KEY]))
        two = [h for _n, v in composed for h in v]
        wide_one = M.held_run_record(_fs_row(
            M.new_run_id(), "2026-12-31T23:59:59Z", "f" * 64,
            ["echo %d %s" % (i, "y" * 400) for i in range(M.MAX_STEPS)]))
        wide = [wide_one, dict(wide_one, runId=M.new_run_id())]
        composed.append(("widest", wide))
        said = dict((name, _rk_said(doc, "#/$defs/fullGateRuns", value,
                                    M.FULL_GATE_RUNS_KEY))
                    for name, value in composed)
        placed = ((doc["$defs"]["phase"].get("properties") or {})
                  .get(M.FULL_GATE_RUNS_KEY) or {}).get("$ref")
        check("fh19 every held value the writer composed in this block - "
              "one run or two - is accepted by the published `fullGateRuns`, "
              "read by validate-manifest's reader with no keyword unread, "
              "and the widest - two runs, a 64-hex head, every step of the "
              "widest gate - is %d bytes against the %d a shard's record is "
              "held to: %r / placed %r / composed %d"
              % (M.record_bytes(wide), M.RECORD_MAX_BYTES,
                 dict((k, v) for k, v in said.items() if v), placed,
                 len(composed)),
              all(not lines for lines in said.values())
              and len(composed) > 2 and any(len(v) == 2 for _n, v in composed)
              and two and placed == "#/$defs/fullGateRuns"
              and M.record_bytes(wide) <= M.RECORD_MAX_BYTES)
        refusals = dict((name, _rk_said(doc, "#/$defs/fullGateRuns", value,
                                        M.FULL_GATE_RUNS_KEY))
                        for name, value in (
                            ("no head", [dict((k, v) for k, v in
                                              wide_one.items() if k != "head")]),
                            ("a red status", [dict(wide_one, status="failed")]),
                            ("a bare digest", [dict(wide_one, digest="abc")]),
                            ("not a list", wide_one)))
        check("fh20 SECOND DIRECTION: the schema refuses a held run with no "
              "head, a status other than passed, a digest of another form, "
              "or a value that is not a list: %r" % (refusals,),
              all(lines for lines in refusals.values()))
    except Exception as exc:                                   # noqa: BLE001
        check("fh0 the held-run block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- a subject whose own record could not be read is never answered older -----
# THE REGRESSION, THROUGH THE REAL COMMANDS: a task (or the phase) whose newest
# record is a malformed red, and whose ledger holds an OLDER green of it. A
# reader that leaves the malformed record out finds the green as the subject's
# newest run, so a reconcile wrote it over the red and the status gate's
# failing-tests condition passed. Beside it, subject B (P1.2) holds an older
# record and the ledger a newer run of it - the subject reconcile must still
# move, so a malformed record of one subject stops nothing of another's.
_NU_FILE = "docs/audit/phases/P1.json"
_NU_RED, _NU_GREEN = "NU-RED", "NU-GR0"


def _nu_row(run_id, ts, status, scope="task", task="P1.1"):
    """A ledger row of `scope` (`task` of `task`, or the phase) - one sweep step
    with the exit `status` reads as."""
    row = _lr_row(run_id, ts, status=status, steps=[
        {"name": "sweep", "exit": 0 if status == "passed" else 1, "ran": 3,
         "measured": "measured", "durationMs": 8000}])
    row["failed"] = [] if status == "passed" else ["sweep"]
    if scope == "phase":
        row.pop("taskId", None)
        row["scope"] = "phase"
    else:
        row["taskId"] = task
    return row


def _nu_project(tmp, name, scope, malformed=True):
    """`(root, manifest, shard)` - the regression's fixture, with the red
    record of `scope`'s subject malformed or (`malformed` False) well-formed."""
    root = os.path.join(tmp, name)
    mpath, shards = ri_plan(root)
    _harness.git(None, "init", "-q", root, prefix=("git",))
    red = M.run_record(_nu_row(_NU_RED, "2026-11-18T12:00:00Z", "failed", scope))
    if malformed:
        red["steps"] = 5
    ri_put_record(shards["P1"], None if scope == "phase" else "P1.1", red)
    ri_put_record(shards["P1"], "P1.2", M.run_record(_nu_row(
        "NU-B-OLD", "2026-11-18T09:00:00Z", "passed", task="P1.2")))
    M.append_row(root, _nu_row(_NU_GREEN, "2026-11-18T08:00:00Z", "passed",
                               scope))
    M.append_row(root, _nu_row("NU-B-NEW", "2026-11-18T10:00:00Z", "passed",
                               task="P1.2"))
    return root, mpath, shards["P1"]


def _nu_holder(shard, subject):
    """The record and pointer `subject` (None: the phase) holds, as one
    canonical text - what a reconcile that left it alone leaves unchanged."""
    body = _lr_shard(shard)
    holder = body if subject is None else [
        t for t in body["tasks"] if t["id"] == subject][0]
    return json.dumps([holder.get(M.RECORD_KEY), holder.get(M.POINTER_KEY)],
                      sort_keys=True)


def _nu_env(root):
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    env["CLAUDE_PROJECT_DIR"] = root
    return env


def _nu_cmd(script, argv, root):
    """`(exit, stdout + stderr)` of the plugin's `script` run as a process."""
    done = subprocess.run([sys.executable, _loader.script_path(script)] + argv,
                          cwd=root, env=_nu_env(root), capture_output=True,
                          text=True, encoding="utf-8", timeout=300)
    return done.returncode, done.stdout + done.stderr


def _nu_reconcile(root, mpath):
    return _nu_cmd("run-test-gate.py", [mpath, "P1", "--project-dir", root,
                                        "--reconcile"], root)


def _nu_failing_gate(root, mpath):
    return _nu_cmd("audit-status.py", [mpath, "--gate", "--fail-on",
                                       "failing-tests"], root)


def _nu_scope_case(check, tmp, scope, label):
    """One red-first case: reconcile over the fixture of `scope` refuses the
    subject whose record is malformed, leaves it, and still moves B."""
    root, mpath, shard = _nu_project(tmp, "nu-" + scope, scope)
    subject = None if scope == "phase" else "P1.1"
    said = "phase P1" if scope == "phase" else "task P1.1"
    before = _nu_holder(shard, subject)
    gate_before, _g = _nu_failing_gate(root, mpath)
    code, out = _nu_reconcile(root, mpath)
    gate_after, gate_out = _nu_failing_gate(root, mpath)
    refused = [ln for ln in out.splitlines() if "REFUSED:" in ln and said in ln]
    check("%s RED-FIRST: reconcile at %s scope over a malformed newest red and "
          "an older green in the ledger leaves the record and pointer exactly, "
          "says nothing moved for %s, refuses it naming the plan file and the "
          "field, exits failing, and the status gate's failing-tests condition "
          "still fails: exit=%r gate %r->%r refused=%r out=%r"
          % (label, scope, said, code, gate_before, gate_after, refused,
             out[-600:]),
          code == 1 and _nu_holder(shard, subject) == before
          and ("moved:    %s" % (said,)) not in out
          and len(refused) == 1 and _NU_FILE in refused[0]
          and "%s.steps" % (M.RECORD_KEY,) in refused[0]
          and _NU_GREEN not in refused[0]
          and gate_before != 0 and gate_after != 0
          and "GATE PASSED" not in gate_out)
    return root, shard, out


def _newest_unreadable_cases(check):
    """(nu) A subject whose own record could not be read is never answered
    from an older run: reconcile refuses it at either scope and still moves
    every other subject; the one function answers newest-or-unreadable; every
    picker the tree holds goes through it."""
    tmp = _harness.fixture_root("audit-evidence-newest-")
    try:
        root, shard, out = _nu_scope_case(check, tmp, "task", "nu1")
        _nu_scope_case(check, tmp, "phase", "nu2")
        body = _lr_shard(shard)
        b_task = [t for t in body["tasks"] if t["id"] == "P1.2"][0]
        check("nu4 A MALFORMED RECORD OF ONE SUBJECT STOPS NOTHING OF ANOTHER'S: "
              "in the same reconcile, B's newer ledger run moves its pointer "
              "and rewrites its record: %r / %r"
              % ((b_task.get(M.POINTER_KEY) or {}).get("runId"),
                 [ln for ln in out.splitlines() if "P1.2" in ln]),
              "moved:    task P1.2 -> NU-B-NEW" in out
              and (b_task.get(M.POINTER_KEY) or {}).get("runId") == "NU-B-NEW"
              and (b_task.get(M.RECORD_KEY) or {}).get("runId") == "NU-B-NEW")

        # ALLOW: the same fixture well-formed reconciles as it always did - the
        # red record is newer than the ledger's green, so it is already where it
        # points, and B moves.
        croot, cmpath, cshard = _nu_project(tmp, "nu-clean", "task",
                                            malformed=False)
        cbefore = _nu_holder(cshard, "P1.1")
        ccode, cout = _nu_reconcile(croot, cmpath)
        cbody = _lr_shard(cshard)
        cb = [t for t in cbody["tasks"] if t["id"] == "P1.2"][0]
        ledger_b = [r for r in M.read_rows(croot, manifest_path=cmpath)["rows"]
                    if r.get("runId") == "NU-B-NEW"]
        check("nu3 ALLOW: a well-formed plan reconciles as before - exit 0, the "
              "red record already where it points and left exactly, B moved "
              "with its record the writer's own record of its ledger row, and "
              "nothing refused or unread: exit=%r out=%r"
              % (ccode, cout[-500:]),
              ccode == 0 and "already:  task P1.1" in cout
              and "moved:    task P1.2 -> NU-B-NEW" in cout
              and "REFUSED" not in cout and "UNREAD" not in cout
              and _nu_holder(cshard, "P1.1") == cbefore
              and len(ledger_b) == 1
              and cb.get(M.RECORD_KEY) == M.run_record(ledger_b[0]))

        # The one function, in-process: newest for a readable subject, the
        # unreadable record for one whose own record would not read.
        doc = _json_schema.load_document(_RK_SCHEMA)
        good = M.run_record(_nu_row("F-NEW", "2026-11-18T12:00:00Z", "failed"))
        bodies = [(_NU_FILE, {"id": "P1", "tasks": [
            {"id": "P1.1", M.RECORD_KEY: dict(good, steps=5)},
            {"id": "P1.2", M.RECORD_KEY: dict(good, runId="F-B")}],
            M.FULL_GATE_RUNS_KEY: 5})]
        lost = M.unreadable_records(bodies, doc)
        rows = [_nu_row("F-OLD", "2026-11-18T08:00:00Z", "passed"),
                _nu_row("NU-B-OLD", "2026-11-18T08:00:00Z", "passed",
                        task="P1.2"),
                _nu_row("NU-P-OLD", "2026-11-18T08:00:00Z", "passed",
                        scope="phase")]
        rows += [r for r, _l in M.records_of_bodies(bodies, doc)]
        ask = getattr(M, "newest_or_unreadable", None)
        got = dict((k, ask(rows, lost, k[0], k[1]) if ask else None)
                   for k in (("task", "P1.1"), ("task", "P1.2"),
                             ("phase", "P1"), ("task", "P9.9")))

        def run_of(answer):
            return ((answer or {}).get("row") or {}).get("runId")
        a11 = got[("task", "P1.1")] or {}
        check("nu5 THE ONE ANSWER, newest-or-unreadable: the subject whose own "
              "record is malformed answers no run and names its record (file, "
              "subject, field) with the shared sentence; the subject beside it "
              "answers its newest; a phase whose held full runs are malformed "
              "still answers its own newest run, since those are not its "
              "record; a subject with no run answers none and nothing "
              "unreadable: %r"
              % (dict(("%s %s" % k, (run_of(v), len((v or {}).get(
                  "unreadable") or []))) for k, v in got.items()),),
              ask is not None and run_of(a11) is None
              and [(e.get("file"), e.get("subject"), e.get("field"))
                   for e in a11.get("unreadable") or []]
              == [(_NU_FILE, "P1.1", "%s.steps" % (M.RECORD_KEY,))]
              and _NU_FILE in str(a11.get("sentence"))
              and run_of(got[("task", "P1.2")]) == "F-B"
              and not got[("task", "P1.2")].get("unreadable")
              and run_of(got[("phase", "P1")]) == "NU-P-OLD"
              and not got[("phase", "P1")].get("unreadable")
              and run_of(got[("task", "P9.9")]) is None
              and not got[("task", "P9.9")].get("unreadable")
              and got[("task", "P9.9")].get("sentence") is None)
        check("nu5b ...and for a readable subject it is the newest by moment, "
              "the run `latest_by_subject` keys, over every subject of the "
              "one-reader fixture: %r"
              % (sorted((k, run_of(ask(ri_rows(tmp), [], k[0], k[1])
                                   if ask else None), v.get("runId"))
                        for k, v in M.latest_by_subject(ri_rows(tmp)).items()),),
              ask is not None and all(
                  run_of(ask(ri_rows(tmp), [], k[0], k[1])) == v.get("runId")
                  for k, v in M.latest_by_subject(ri_rows(tmp)).items()))

        # UNDER THE LOCK: a record that became unreadable after the rows were
        # read is refused there too, never replaced by the older target.
        lbody = {"id": "P1", "tasks": [{"id": "P1.1", M.RECORD_KEY: dict(
            good, steps=5)}]}
        snapshot = json.dumps(lbody, sort_keys=True)
        written, problem, _ans = M._reconciled(
            lbody, "task", {"taskId": "P1.1", "phaseId": "P1"}, True,
            dict(_nu_row("F-OLD", "2026-11-18T08:00:00Z", "passed")),
            M.run_record(_nu_row("F-OLD", "2026-11-18T08:00:00Z", "passed")))
        check("nu7 UNDER THE LOCK THE SAME RULE: the shard as read under the lock "
              "holding a malformed record refuses that subject's write, naming "
              "the field, and the body is left as read: %r"
              % ((written is None, problem),),
              written is None and problem
              and "%s.steps" % (M.RECORD_KEY,) in str(problem)
              and json.dumps(lbody, sort_keys=True) == snapshot)
        _nu_picker_cases(check)
    except Exception as exc:                                   # noqa: BLE001
        check("nu0 the newest-or-unreadable block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# THE PICKERS, DERIVED BY WHAT THEY CALL. A function that reduces runs to one
# per subject (`latest_by_subject`), takes a subject's newest red
# (`newest_red_phase_row`, `red_after_green`) or the binding's newest
# (`_verdict_binding.newest`) answers "the newest run of a subject"; each must
# also ask `newest_or_unreadable`, or carry a row below saying why an older
# answer cannot come out of it. Read in both directions: a row naming a
# function that no longer calls a picker, or that now goes through the one
# answer, is stale.
_NU_PICKS = ("latest_by_subject", "newest_red_phase_row", "red_after_green")
_NU_LEFT = {
    ("governance/_verdict_binding.py", "red_after_green"):
        "the definition itself: it reads the rows it is handed, which "
        "`binding` hands only after the subject's own record was asked of "
        "`newest_or_unreadable`",
    ("governance/_verdict_binding.py", "member_red"):
        "OWED, NOT SAFE: a group member's own record that would not read is "
        "not handed to it - close-phase.py passes the records it read and not "
        "what that read lost - so a member's newest red in such a record is "
        "not seen, and its rows are still chosen by `_same_subject`, which "
        "counts a base run a member's task keeps; recorded as a finding for "
        "the owner of close-phase.py",
    ("governance/_verdict_binding.py", "signoff_moment"):
        "the newest `phase.verdict` JOURNAL row, a sign-off moment - not a "
        "run of any subject, and no plan record holds one",
    ("governance/_verdict_binding.py", "newest"):
        "the definition itself: `newest_row` under the binding's name, whose "
        "one caller is `signoff_moment`",
    ("governance/_evidence_io.py", "newest_or_unreadable"):
        "the one answer itself, which reduces with `latest_by_subject`",
    ("governance/_gate_derive.py", "newest_red_phase_row"):
        "the definition itself: its one caller, `derive-phase-gate.py`'s "
        "`_gather_facts`, asks `newest_or_unreadable` for the phase first",
    ("governance/_evidence_io.py", "latest_by_subject"):
        "the definition itself",
}


def _nu_pickers():
    """`{(rel, function): (calls a picker, calls the one answer)}` for every
    function under `scripts/` and `.claude/hooks/` that calls either."""
    import ast
    files = list(_output.py_files(_output.SCRIPTS_DIR))
    hooks = os.path.join(_output.REPO_ROOT, ".claude", "hooks")
    files += [(".claude/hooks/" + n, os.path.join(hooks, n))
              for n in sorted(os.listdir(hooks)) if n.endswith(".py")]
    out = {}
    for rel, path in files:
        with io.open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        newest_here = rel.endswith("_verdict_binding.py")
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            called = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    called.add(getattr(fn, "attr", None) or getattr(fn, "id",
                                                                  None))
            picks = set(_NU_PICKS) | (set(["newest"]) if newest_here
                                      else set())
            if node.name in picks:
                called.add(node.name)
            if called & (picks | set(["newest_or_unreadable"])):
                out[(rel.replace(os.sep, "/"), node.name)] = (
                    bool(called & picks), "newest_or_unreadable" in called)
    return out


def _nu_picker_cases(check):
    """(nu6) the pickers' rule, derived.

    WHAT IT CANNOT SEE: a function that filters runs to one subject by hand and
    takes `newest_row` (or `oldest_first(...)[-1]`) of them picks a subject's
    newest run without calling any name above, and is not derived - `newest_row`
    alone is also every by-run-id and by-launch lookup, which are not pickers.
    The author of such a function owes it the call to `newest_or_unreadable`,
    or a row in `_NU_LEFT`; nothing here finds it."""
    found = _nu_pickers()
    bypass = sorted(k for k, (_p, via) in found.items()
                    if not via and k not in _NU_LEFT)
    stale = sorted(k for k in _NU_LEFT
                   if k not in found or found[k][1])
    through = sorted(k for k, (_p, via) in found.items() if via)
    owed = set([("governance/_evidence_io.py", "reconcile"),
                ("status/audit-lookup.py", "run_lookup"),
                ("status/_doctor_completions.py", "check_evidence_pointers"),
                ("governance/_verdict_binding.py", "binding"),
                ("governance/derive-phase-gate.py", "_gather_facts")])
    check("nu6 every function that CALLS a named picker also asks "
          "`newest_or_unreadable`, derived from what each calls, unless a row "
          "says why; no row is stale, and reconcile, the lookup, the doctor, "
          "the binding and the phase-gate derivation are among them. BLIND to "
          "a reader that filters rows by hand and calls no picker - the "
          "property itself is held by the read (wh, bb), not by this list: "
          "bypass=%r stale=%r through=%r" % (bypass, stale, through),
          found and bypass == [] and stale == [] and owed <= set(through))


# --- the property at the source: what a read returns for an unreadable record --
# THE READ, NOT A LIST OF READERS. A subject whose own record would not read
# must have no row in what `read_rows` returns that ANY reader - however it
# filters - can take as that subject's newest run, verdict or repeat. So these
# cases ask the read's rows with every filter a reader has been seen to write by
# hand, beside the helpers, and each must never come back with the older green.
_WH_KEY = "sha256:wh-identity"
_WH_GREEN, _WH_RED = "WH-GREEN-OLD", "WH-RED-NEW"


def _wh_row(run_id, ts, status, scope="task", task="P1.1"):
    """`_nu_row` with one reuse identity, a fallback task's run (`scope`
    phase beside a `task`) spelled as the runner writes it."""
    row = _nu_row(run_id, ts, status, scope=scope, task=task)
    row["reuseKey"] = _WH_KEY
    if scope == "phase" and task is not None:
        row["taskId"] = task
    return row


def _wh_project(tmp, name, scope, malformed=True):
    """`(root, manifest, shard)` - subject `scope` (task P1.1, or the phase)
    holding its newest run as a red record (malformed unless told not), an
    OLDER green of the same identity in the ledger - the earliest run of all
    - and beside it the runs of other subjects: P1.2's own green, and, for
    the phase, a fallback run task P1.3 made on the phase's gate."""
    root = os.path.join(tmp, name)
    mpath, shards = ri_plan(root)
    task = None if scope == "phase" else "P1.1"
    red = M.run_record(_wh_row(_WH_RED, "2026-11-18T12:00:00Z", "failed",
                               scope=scope, task=task))
    if malformed:
        red["steps"] = 5
    ri_put_record(shards["P1"], task, red)
    for row in (_wh_row(_WH_GREEN, "2026-11-18T06:00:00Z", "passed",
                        scope=scope, task=task),
                _wh_row("WH-B", "2026-11-18T09:00:00Z", "passed", task="P1.2"),
                _wh_row("WH-FB", "2026-11-18T08:00:00Z", "passed",
                        scope="phase", task="P1.3")
                if scope == "phase" else
                _wh_row("WH-PH", "2026-11-18T07:00:00Z", "passed",
                        scope="phase", task=None)):
        M.append_row(root, row)
    return root, mpath, shards["P1"]


def _wh_answers(rows, ids, scope, subject):
    """What every reader of a subject's newest run takes from `rows`: the
    helpers, and the filters written by hand around them - each the row it
    picks (`reusable_run` included: the run a repeat would copy)."""
    import _verdict_binding
    mine_task = [r for r in rows if isinstance(r, dict)
                 and str(r.get("taskId")) == str(ids.get("taskId"))]
    mine_phase = [r for r in rows if isinstance(r, dict)
                  and r.get("scope") == "phase"
                  and str(r.get("phaseId")) == str(ids.get("phaseId"))
                  and not r.get("taskId")]
    same = [r for r in rows if isinstance(r, dict) and M._same_subject(r, ids)]
    return {
        "latest_by_subject": M.latest_by_subject(rows).get((scope, subject)),
        "newest_or_unreadable, asked with nothing said lost":
            M.newest_or_unreadable(rows, [], scope, subject)["row"],
        "reusable_run": M.reusable_run(rows, scope, ids, _WH_KEY,
                                       ("passed", "failed")),
        "by hand: its id": M.newest_row(mine_task if scope == "task"
                                        else mine_phase),
        "by hand: _same_subject": M.newest_row(same),
        "by hand: red_after_green": _verdict_binding.red_after_green(same),
        "by hand: oldest_first[-1]": (M.oldest_first(same) or [None])[-1],
    }


def _wh_picked(answers):
    return dict((k, (v or {}).get("runId") if isinstance(v, dict) else v)
                for k, v in answers.items())


def _withheld_cases(check):
    """(wh) The property held where rows are produced: after `read_rows`, a
    subject whose own record could not be read has no row a reader can take
    as its newest run, verdict or repeat - whatever the reader's filter - while
    the runs stay counted, the boundary never moves later, and a plan with
    nothing unreadable reads exactly as before."""
    tmp = _harness.fixture_root("audit-evidence-withheld-")
    try:
        ids = {"taskId": "P1.1", "phaseId": "P1"}
        root, mpath, _shard = _wh_project(tmp, "task", "task")
        read = M.read_rows(root, manifest_path=mpath)
        picked = _wh_picked(_wh_answers(read["rows"], ids, "task", "P1.1"))
        statuses = dict((k, (v or {}).get("status")) for k, v in
                        _wh_answers(read["rows"], ids, "task", "P1.1").items()
                        if isinstance(v, dict))
        croot, cmpath, _c = _wh_project(tmp, "task-oracle", "task",
                                        malformed=False)
        oracle = _wh_picked(_wh_answers(
            M.read_rows(croot, manifest_path=cmpath)["rows"], ids, "task",
            "P1.1"))
        asked = M.newest_or_unreadable(read["rows"], [], "task", "P1.1")
        check("wh1 RED-FIRST, THE PROPERTY AT THE SOURCE: a task whose newest "
              "red record will not read, an older green of the same identity "
              "in the ledger - no reader of what the read returns takes the "
              "green as the task's newest run, verdict or repeat, whatever it "
              "filters by, and none takes a passing row; the one question, "
              "asked with nothing said lost, still names the record: "
              "picked=%r statuses=%r named=%r"
              % (picked, statuses, [e.get("file") for e in asked["unreadable"]]),
              _WH_GREEN not in picked.values()
              and picked["reusable_run"] is None
              and "passed" not in statuses.values()
              and [e.get("file") for e in asked["unreadable"]]
              == ["docs/audit/phases/P1.json"]
              and all(v is not None for k, v in picked.items()
                      if k not in ("reusable_run", "by hand: red_after_green",
                                   "newest_or_unreadable, asked with nothing "
                                   "said lost")))
        check("wh2 ...THE ORACLE: the same fixture with the red record "
              "well-formed - every one of those readers takes the red, so the "
              "fixture tells the two apart: %r" % (oracle,),
              all(v == _WH_RED for v in oracle.values()))
        rows = read["rows"]
        green = [r for r in rows if r.get("runId") == _WH_GREEN]
        others = _wh_picked({"P1.2": M.latest_by_subject(rows).get(
            ("task", "P1.2")), "P1": M.latest_by_subject(rows).get(
            ("phase", "P1"))})
        check("wh3 ...AND NOTHING IS LOST: the older green is still read, once, "
              "with its moment and its steps - a tally still counts it - but "
              "names no subject; the read's three lists stay aligned; every "
              "other subject's newest is its own: green=%r lens=%r others=%r"
              % ([(M.subject_key(r), r.get("ts"), len(r.get("steps") or []))
                  for r in green],
                 (len(rows), len(read["rowFiles"]), len(read["rowSources"])),
                 others),
              len(green) == 1 and M.subject_key(green[0]) is None
              and green[0].get("ts") == "2026-11-18T06:00:00Z"
              and len(green[0].get("steps") or []) == 1
              and len(rows) == len(read["rowFiles"]) == len(read["rowSources"])
              and others == {"P1.2": "WH-B", "P1": "WH-PH"})
        bound = M.evidence_boundary(root, mpath)
        check("wh4 THE BOUNDARY NEVER MOVES LATER: the withheld green is the "
              "earliest run recorded, and the boundary is still its moment - "
              "a read that dropped it would date recording from a later run "
              "and widen the excuse: %r" % ((bound.get("at"),
                                             bound.get("sources")),),
              bound.get("at") == "2026-11-18T06:00:00Z")

        # THE PHASE: its record holds the phase's own runs alone - a task's
        # run on the phase's gate sits on the task (`_holders`) - so the
        # phase's own older runs are withheld and every task keeps its own
        # newest, the one it ran on the phase's gate included.
        proot, pmpath, _ps = _wh_project(tmp, "phase", "phase")
        prows = M.read_rows(proot, manifest_path=pmpath)["rows"]
        phase_picked = _wh_picked(_wh_answers(prows, {"phaseId": "P1"},
                                              "phase", "P1"))
        fb_ids = {"taskId": "P1.3", "phaseId": "P1"}
        fb_same = M.newest_row([r for r in prows
                                if M._same_subject(r, fb_ids)])
        fb_reuse = M.reusable_run(prows, "phase", fb_ids, _WH_KEY,
                                  ("passed", "failed"))
        fb_latest = M.latest_by_subject(prows).get(("task", "P1.3"))
        p12 = M.newest_row([r for r in prows if M._same_subject(
            r, {"taskId": "P1.2", "phaseId": "P1"})])
        check("wh5 RED-FIRST, AT PHASE SCOPE: the phase's newest record will not "
              "read - neither its older green nor the green a fallback task "
              "ran on the phase's gate is the phase's newest, verdict or "
              "repeat; and the lost record held no task's run, so that task's "
              "newest is still its own green, and P1.2's its own: phase=%r "
              "fallback=%r reuse=%r latest=%r P1.2=%r"
              % (phase_picked, (fb_same or {}).get("runId"),
                 (fb_reuse or {}).get("runId"),
                 (fb_latest or {}).get("runId"), (p12 or {}).get("runId")),
              _WH_GREEN not in phase_picked.values()
              and "WH-FB" not in phase_picked.values()
              and phase_picked["reusable_run"] is None
              and (fb_same or {}).get("runId") == "WH-FB"
              and (fb_reuse or {}).get("runId") == "WH-FB"
              and (fb_latest or {}).get("runId") == "WH-FB"
              and (p12 or {}).get("runId") == "WH-B")

        # NOTHING UNREADABLE, NOTHING CHANGED: the oracle fixture, this
        # repository's own plan and the committed example are read with no
        # row withheld and no row added for a record.
        marks = (getattr(M, "WITHHELD_KEY", "withheldFrom"),
                 getattr(M, "UNREADABLE_ROW_KEY", "unreadableRecord"))
        plain = {}
        for label, (proj, plan) in (
                ("oracle", (croot, cmpath)),
                ("this repository", (_output.REPO_ROOT, os.path.join(
                    _output.REPO_ROOT, "docs", "audit", "audit-plan.json"))),
                ("the example", (os.path.join(_output.REPO_ROOT, "examples",
                                              "acme-store"),
                                 os.path.join(_output.REPO_ROOT, "examples",
                                              "acme-store",
                                              "audit-plan.json")))):
            if not os.path.isfile(plan):
                plain[label] = "no plan"
                continue
            got = M.read_rows(proj, manifest_path=plan)
            plain[label] = (
                len(got["rows"]), len(got.get("unreadableRecords") or []),
                sum(1 for r in got["rows"] if any(m in r for m in marks)),
                sorted(set(got["rowSources"])))
        check("wh6 A PLAN WITH NOTHING UNREADABLE READS AS BEFORE: no row is "
              "withheld or added for a record, the sources are the ledger's "
              "and the records': %r" % (plain,),
              all(isinstance(v, tuple) and v[2] == 0
                  and set(v[3]) <= set([M.ROW_FROM_LEDGER, M.ROW_FROM_RECORD])
                  for v in plain.values() if v != "no plan")
              and plain["oracle"][1] == 0)

        # THE ORDER ITSELF, over a list a reader assembled by hand from more
        # than one subject: the row standing for a lost record is the newest
        # of any list holding it, after every dated row - the withholding
        # above means no filter by subject ever puts the two side by side.
        lost_row = next(r for r in prows if M.is_unreadable_row(r))
        dated = next(r for r in prows if not M.is_unreadable_row(r)
                     and M.stamp_moment(r.get("ts")) is not None)
        undated = dict(dated, ts="not a moment", runId="WH-UNDATED")
        order = [r.get("runId") for r in M.oldest_first([lost_row, dated,
                                                         undated])]
        check("wh7 RED-FIRST: oldest_first puts the row standing for a lost "
              "record after every dated and undated row, so the newest of a "
              "list holding it is that row: %r" % (order,),
              order == ["WH-UNDATED", dated.get("runId"), lost_row["runId"]]
              and M.newest_row([lost_row, dated]) is lost_row)
        # NO RUN IS A RECORD THAT WOULD NOT READ: a run's window is asked of
        # the other runs, and the row standing for a record is not one.
        me = dict(dated, runId="WH-ME", startedAt=dated["ts"])
        nowindow = dict(dated, runId="WH-NOWINDOW", ts=None, startedAt=None)
        beside = [lost_row, me, nowindow]
        unsure = [r.get("runId") for r in M.undecided_neighbours(
            beside, me, M.runner_of(me))]
        check("wh8 RED-FIRST: the runs that cannot be placed beside a run's "
              "window are runs - the row standing for a lost record is never "
              "among them, while a run with no window still is: %r (window %r)"
              % (unsure, M.window_of(me)[:2]),
              M.window_of(me)[0] is not None and unsure == ["WH-NOWINDOW"])
        # A TASK'S RUNS UNDER AN ID IT WAS MOVED FROM are its runs: a green
        # recorded under the old id is withheld with the rest.
        aroot, ampath, ashard = _wh_project(tmp, "alias", "task")
        with io.open(ashard, encoding="utf-8") as fh:
            body = json.load(fh)
        [t for t in body["tasks"] if t["id"] == "P1.1"][0]["movedFrom"] = {
            "id": "P2.7", "at": "2026-11-18T04:00:00Z"}
        with io.open(ashard, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        M.append_row(aroot, dict(_wh_row("WH-OLDID", "2026-11-18T05:00:00Z",
                                         "passed"), taskId="P2.7",
                                 phaseId="P2"))
        moved = dict((r.get("runId"), r) for r in
                     M.read_rows(aroot, manifest_path=ampath)["rows"])
        old = moved.get("WH-OLDID") or {}
        check("wh9 RED-FIRST: a task whose newest record will not read has "
              "its green recorded under the id it was moved from withheld "
              "too - no task id left on it, the old ids kept as measured: %r"
              % (dict((k, old.get(k)) for k in ("taskId", M.WITHHELD_KEY)),),
              "taskId" not in old and isinstance(old.get(M.WITHHELD_KEY), dict)
              and old[M.WITHHELD_KEY].get("taskId") == "P2.7")
    except Exception as exc:                                   # noqa: BLE001
        check("wh0 the withheld-rows block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- no reader reaches around the projection -------------------------------------
# A READER IS HANDED A SUBJECT'S RECORD ONLY AS ITS PROJECTION
# (`_evidence_io.project_record`, through `RECORD_GRAMMAR`), so a field the table
# does not hold is absent from everything any reader reads. What a parse can
# prove of that is DERIVED here, completely over what it reads: every LOAD of a
# subject's record key - `.get(K)` or `[K]`, K the literal "lastRun" or any name
# `RECORD_KEY` - in every `.py` under the plugin's `scripts/` and `hooks/` and
# this repository's `.claude/hooks/` sits in one of `_RF_DOORS`: the
# constructor, or a rule asked of the stored record. A store (`holder[K] = ...`)
# is a write, not a read, and a membership test (`K in holder`) reads whether
# the key is there and none of its value. WHAT IT CANNOT SEE: the key bound to another name
# first (`k = RECORD_KEY; holder[k]`), `getattr`, `operator.itemgetter`, a walk
# over a holder's `.items()`, the stored object handed on by a door that may
# read it, and any reader that is not Python.
_RF_DOORS = {
    ("_evidence_io", "_plan_records"):
        "the constructor: the one read that projects each record",
    ("_evidence_io", "READER_RULES"):
        "the rules, asked of the stored record before it is projected",
    ("_evidence_io", "reader_rule_problems"):
        "the rules' own channel: asks the published schema of the stored "
        "record, so a record the schema already refuses is said there once",
    ("audit-task", "_group_record"):
        "copies the carrier's stored record whole onto group members, where "
        "each copy is read through the projection - comparing only its "
        "runId with the pointer the binding already answered from it",
}
# Values a field is broken by, tried in order: the first its grammar refuses
# is the one planted.
_RF_BREAKERS = (7, "x", {"x": 1}, ["x"], True, None, [], "",
                "2026-11-20", "2026-11-20t12:00:00z", "Phase")


def _rf_sources():
    """`[(module, path)]` - every `.py` the reach-around proof reads."""
    roots = [os.path.join(_output.PLUGIN_ROOT, "scripts"), _output.HOOKS_DIR,
             os.path.join(_output.REPO_ROOT, ".claude", "hooks")]
    out = []
    for root in roots:
        for top, _dirs, files in os.walk(root):
            out.extend((name[:-3], os.path.join(top, name))
                       for name in sorted(files) if name.endswith(".py"))
    return out


def _rf_is_record_key(node):
    return (isinstance(node, ast.Constant) and node.value == M.RECORD_KEY) or (
        isinstance(node, ast.Name) and node.id == "RECORD_KEY") or (
        isinstance(node, ast.Attribute) and node.attr == "RECORD_KEY")


def _rf_reads(tree):
    """`[(enclosing, line)]` - every load of a record key in `tree`, named by
    the top-level function or assignment that holds it."""
    out = []
    for top in tree.body:
        name = (top.name if isinstance(top, (ast.FunctionDef, ast.ClassDef))
                else top.targets[0].id if isinstance(top, ast.Assign)
                and isinstance(top.targets[0], ast.Name) else "<module>")
        for node in ast.walk(top):
            index = None
            if isinstance(node, ast.Call) \
                    and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "get" and node.args:
                index = node.args[0]
            elif isinstance(node, ast.Subscript) \
                    and isinstance(node.ctx, ast.Load):
                index = node.slice
                if type(index).__name__ == "Index":       # the 3.8 wrapper
                    index = index.value
            if index is not None and _rf_is_record_key(index):
                out.append((name, node.lineno))
    return out


def _rf_leaves(grammar, path=(), seen_record=False):
    """`[(path, grammar)]` - every leaf `RECORD_GRAMMAR` holds, a list
    element at index 0; a nested run record (`("record",)`) is walked once,
    to its moment."""
    kind = grammar[0]
    if kind == "record":
        return [] if seen_record else [(path + ("at",), M._MOMENT)]
    if kind == "list":
        return _rf_leaves(grammar[1], path + ("0",), seen_record)
    if kind == "object":
        return [leaf for key, inner in grammar[1]
                for leaf in _rf_leaves(inner, path + (key,), seen_record)]
    return [(path, grammar)]


def _rf_lists(grammar, path=()):
    """`[(path, grammar)]` - every list `RECORD_GRAMMAR` holds that the
    writer writes only with something in it (a least length above 0)."""
    kind = grammar[0]
    if kind == "list":
        here = [(path, grammar)] if grammar[2] > 0 else []
        return here + _rf_lists(grammar[1], path + ("0",))
    if kind == "object":
        return [found for key, inner in grammar[1]
                for found in _rf_lists(inner, path + (key,))]
    return []


def _rf_put(record, path, value):
    holder = record
    for at, part in enumerate(path[:-1]):
        nxt = path[at + 1]
        if isinstance(holder, list):
            holder = holder[int(part)]
            continue
        if not isinstance(holder.get(part), (dict, list)):
            holder[part] = [{}] if nxt == "0" else {}
        holder = holder[part]
    if isinstance(holder, list):
        holder[int(path[-1])] = value
    else:
        holder[path[-1]] = value


def _rf_held(grammar):
    """A value `grammar` accepts, the fullest it can be: an object with every
    key its table names, a list of objects with one element (a list of
    anything else empty), a nested run record once - so one record reaches
    every object the table holds. None when no candidate is accepted."""
    kind = grammar[0]
    if kind == "record":
        return _rf_held(M.RECORD_GRAMMAR)
    if kind == "either":
        for inner in grammar[1]:
            got = _rf_held(inner)
            if M._project(got, inner, "x")[1] is None:
                return got
        return None
    if kind == "list":
        if grammar[1][0] in ("object", "record"):
            return [_rf_held(grammar[1])]
        return []
    if kind == "object":
        return dict((key, _rf_held(inner)) for key, inner in grammar[1]
                    if inner[0] != "record" and not (
                        inner[0] == "list" and inner[1][0] == "record"))
    said = grammar[1]
    words = said[len("one of "):].split(", ") if said.startswith("one of ") \
        else []
    for value in words + ["RN", "2026-11-18T12:00:00Z", 1, True, None]:
        if grammar[2](value):
            return value
    return None


def _rf_objects(value, grammar, path=()):
    """`[(path, grammar, object)]` - every object `value` holds where
    `grammar` says one sits, the record itself first."""
    kind = grammar[0]
    if kind == "record":
        grammar, kind = M.RECORD_GRAMMAR, "object"
    if kind == "either":
        for inner in grammar[1]:
            if M._project(value, inner, "x")[1] is None:
                return _rf_objects(value, inner, path)
        return []
    if kind == "list" and isinstance(value, list):
        return [found for i, item in enumerate(value)
                for found in _rf_objects(item, grammar[1], path + (str(i),))]
    if kind == "object" and isinstance(value, dict):
        named = dict(grammar[1])
        return [(path, grammar, value)] + [
            found for key, inner in sorted(value.items()) if key in named
            for found in _rf_objects(inner, named[key], path + (key,))]
    return []


def _rf_spelled(path):
    return M.RECORD_KEY + "".join(
        "[%s]" % (p,) if p.isdigit() else ".%s" % (p,) for p in path)


def _rf_full_record():
    """One record holding every object `RECORD_GRAMMAR` names, each with
    every field: the top level's table, a run it repeats and a base run it
    kept each holding the top level's table once more."""
    record = _rf_held(M.RECORD_GRAMMAR)
    record["gateSource"] = "task"
    nested = dict(_rf_held(M.RECORD_GRAMMAR), runId="RN-NESTED")
    record[M.REPEATED_RUN_KEY] = nested
    record[M.BASE_RED_KEY]["baseRuns"] = [dict(nested, runId="RN-BASE")]
    return record


def _rf_breaker(grammar):
    """The first of `_RF_BREAKERS` the leaf's grammar refuses, or None."""
    for value in _RF_BREAKERS:
        if M._project(value, grammar, "x")[1] is not None:
            return value
    return None


def _read_field_cases(check):
    """(rf) No reader reaches around the projection (rf1, derived over every
    source file), and every field the projection carries is held by its
    grammar (rf2, derived over the table): a record carrying it broken is
    refused, named by that field."""
    doc = _json_schema.load_document(_RK_SCHEMA)
    reads, files = [], 0
    for module, path in _rf_sources():
        with io.open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        files += 1
        reads.extend((module, name, line) for name, line in _rf_reads(tree))
    outside = [r for r in reads if (r[0], r[1]) not in _RF_DOORS]
    unused = [d for d in _RF_DOORS if d not in set((m, n) for m, n, _l in reads)]
    check("rf1 RED-FIRST, DERIVED: no reader reaches around the projection - "
          "every load of a subject's record key in %d source file(s) sits in "
          "the constructor or a rule (`_RF_DOORS`), and every door is still "
          "one: %d load(s); outside a door %r; doors no load uses %r"
          % (files, len(reads), outside, unused),
          outside == [] and unused == [] and files > 50
          and ("_evidence_io", "_plan_records") in set(
              (m, n) for m, n, _l in reads))
    # A selection miss names its suite, so a field planted beside it is the
    # one found broken rather than the suite it lacks.
    base = {"runId": "RF", "status": "failed", "at": "2026-11-18T12:00:00Z",
            "gateSource": "task", "steps": [{"name": "sweep", "exit": 1}],
            "testedState": {"head": "abc", "scopeDigest": None},
            "selectionMiss": [{"test": "e2e/cart.spec.ts"}]}
    leaves = _rf_leaves(M.RECORD_GRAMMAR)
    unheld, said = [], []
    for path, grammar in leaves:
        first = _rf_breaker(grammar)
        if first is None:
            unheld.append(("no breaker its grammar refuses", path))
            continue
        # Beside the first value refused: every moment given the shapes only
        # a hand writes, every enumerated word a near miss of its words.
        values = [first] + (
            ["2026-11-20", "2026-11-20t12:00:00z", "2026-13-20T12:00:00Z"]
            if grammar is M._MOMENT else []) + (
            ["Phase", "bogus"] if grammar[0] == "leaf"
            and grammar[1].startswith("one of ") else [])
        for value in values:
            record = json.loads(json.dumps(base))
            if path[-1] == "at" and len(path) > 1:
                # A run nested in the record (the one repeated, a kept base)
                # or a launch it replaced: the words its object carries.
                _rf_put(record, path[:-1] + ("runId",), "RN")
                _rf_put(record, path[:-1] + ("status",), "failed")
                if path[0] != "replacedLaunches":
                    _rf_put(record, path[:-1] + ("steps",), [])
            _rf_put(record, path, value)
            found = M.record_problem(record, doc, scope="task")
            spelled = "lastRun" + "".join(
                "[%s]" % (p,) if p.isdigit() else ".%s" % (p,) for p in path)
            if found is None or not found["field"].startswith(spelled):
                unheld.append((path, value, found))
            else:
                said.append(spelled)
    # A list the writer only writes holding something (`muted` names a mute
    # that excused a step), given none.
    for path, grammar in _rf_lists(M.RECORD_GRAMMAR):
        record = json.loads(json.dumps(base))
        _rf_put(record, path, [])
        found = M.record_problem(record, doc, scope="task")
        spelled = "lastRun" + "".join(
            "[%s]" % (p,) if p.isdigit() else ".%s" % (p,) for p in path)
        if found is None or not found["field"].startswith(spelled):
            unheld.append((path, [], found))
        else:
            said.append(spelled + "[]")
    # A field the table does not hold is read by nobody: it is not in what
    # the projection hands on, even planted beside a well-formed record.
    planted = dict(base, scope="phase", taskId="P9.9", phaseId="P9",
                   inventedByHand={"x": 1})
    projected, why = M.project_record(planted, "task")
    check("rf2 RED-FIRST, DERIVED: every leaf `RECORD_GRAMMAR` carries, given "
          "the first value its grammar refuses, makes the record unreadable "
          "named by that field - a bare date, a lowercase stamp and an "
          "unknown word included - and a key the table does not hold is "
          "carried into no row: %d leaf/leaves, %d breakage(s) held; unheld "
          "%r; planted keys carried %r (%s)"
          % (len(leaves), len(said), unheld[:6],
             sorted(set(projected or {}) - set(base)), why),
          unheld == [] and len(set(s for s in said if not s.endswith("[]")))
          == len(leaves) and len(leaves) > 60 and len(said) > len(leaves)
          and any(s.endswith("muted[]") for s in said)
          and why is None and projected == base
          and M.record_problem(base, doc, scope="task") is None)
    # EVERY OBJECT THE TABLE HOLDS, AT EVERY DEPTH, read off one record that
    # holds them all: each field it requires, taken away, makes the record
    # unreadable named by that field (rf3); a key it does not name, planted
    # in it, is kept by neither the writer's egress nor the projection (rf4).
    full = _rf_full_record()
    full_why = M.project_record(full, "task")[1]
    objects = _rf_objects(full, ("record",))
    unpinned, required = [], 0
    for path, grammar, _obj in objects:
        for key in grammar[2]:
            required += 1
            record = json.loads(json.dumps(full))
            holder = record
            for part in path:
                holder = holder[int(part)] if part.isdigit() else holder[part]
            del holder[key]
            why = M.project_record(record, "task")[1] or ""
            if not why.startswith("%s.%s is missing" % (_rf_spelled(path), key)):
                unpinned.append((_rf_spelled(path), key, why[:120]))
    check("rf3 RED-FIRST, DERIVED: every field an object of the table "
          "requires, at every depth - a repeated run's and a kept base run's "
          "`runId`, a mute's `test`, `bugId` and `until`, a follower's `path` "
          "and `owner` - taken away makes the record unreadable, named by "
          "that field: %d object(s), %d required field(s); the full record "
          "reads (%s); unpinned %r"
          % (len(objects), required, full_why, unpinned[:6]),
          full_why is None and unpinned == [] and required > 10
          and any(p[:1] == (M.REPEATED_RUN_KEY,) for p, _g, _o in objects)
          and any("baseRuns" in p and "muted" in p for p, _g, _o in objects))
    kept = []
    for path, _grammar, _obj in objects:
        record = json.loads(json.dumps(full))
        holder = record
        for part in path:
            holder = holder[int(part)] if part.isdigit() else holder[part]
        holder["inventedByHand"] = {"x": 1}
        stored = M.stored_record(record)
        projected = M.project_record(record, "task")[0]
        if stored != M.stored_record(full) or projected != \
                M.project_record(full, "task")[0]:
            kept.append(_rf_spelled(path))
    check("rf4 RED-FIRST, DERIVED: a key the table does not name, planted in "
          "any object it holds at any depth, is stored by neither the "
          "writer's egress (`stored_record`) nor handed on by the projection, "
          "and nothing else is touched: %d object(s); kept at %r"
          % (len(objects), kept[:6]),
          kept == [] and len(objects) > 10
          and M.stored_record(full) == full)
    # THE SHAPES A HAND EDIT LEAVES on the one field that decides whose run
    # a task's record holds, and on the moment every reader orders by -
    # through the read every reader takes (`read_rows`), the subject's older
    # green beside it in the ledger.
    tmp = _harness.fixture_root("audit-evidence-projection-")
    modes = (("gateSource missing", "gateSource", None),
             ("gateSource Phase", "gateSource", "Phase"),
             ("gateSource bogus", "gateSource", "nope"),
             ("at a bare date", "at", "2026-11-20"),
             ("at lowercase", "at", "2026-11-20t12:00:00z"),
             ("the record null", None, None))
    seen = []
    try:
        for i, (label, key, value) in enumerate(modes):
            root, mpath, spath = _lr_project(tmp, "pj%d" % (i,))
            green = dict(_lr_row("PJ-GREEN", "2026-11-18T03:00:00Z",
                                 status="passed"), failed=[])
            M.append_row(root, green)
            red = M.run_record(_lr_row("PJ-RED", "2026-11-18T04:00:00Z"))
            if key is None:
                red = None
            elif value is None:
                red.pop(key, None)
            else:
                red[key] = value
            ri_put_record(spath, "P1.1", red)
            read = M.read_rows(root, manifest_path=mpath)
            fields = [e.get("field") for e in read.get("unreadableRecords")
                      or []]
            mine = [r.get("runId") for r in read["rows"]
                    if r.get("taskId") == "P1.1"]
            seen.append((label, fields, mine))
    finally:
        _harness.remove_tree(tmp)
    wrong = [s for s in seen if s[1] != [
        "%s.%s" % (M.RECORD_KEY, k) if k else M.RECORD_KEY
        for _l, k, _v in modes if _l == s[0]]
             or "PJ-GREEN" in s[2] or "PJ-RED" in s[2]]
    check("pj2 RED-FIRST: a task's record whose `gateSource` is missing, "
          "capitalised or not a word the writer writes, or whose `at` is a "
          "bare date or a lowercase stamp, or that is null, is a record that "
          "will not read - "
          "named by that field - and the subject's older green is withheld, "
          "never its answer: %r; wrong %r" % (seen, wrong),
          len(seen) == len(modes) and wrong == [])
    _duplicate_key_cases(check, doc)


def _duplicate_key_cases(check, doc):
    """(dk) A record whose JSON writes one field twice is a record that will
    not read - at every read of a plan file a record is taken from: the walk
    (`plan_bodies`), the shard read under the lock (`write_plan_file`) and
    the branch tip (close-phase's `_tip_json`) - and the plan's own readers
    refuse the file through `_manifest_io`'s door."""
    tmp = _harness.fixture_root("audit-evidence-duplicate-")
    try:
        root = os.path.join(tmp, "dk")
        mpath, shards = ri_plan(root)
        red = M.run_record(_wh_row("DK-RED", "2026-11-18T12:00:00Z", "failed"))
        ri_put_record(shards["P1"], "P1.1", red)
        with io.open(shards["P1"], encoding="utf-8") as fh:
            text = fh.read()
        twice = text.replace('"status": "failed"',
                             '"status": "failed", "status": "passed"', 1)
        with io.open(shards["P1"], "w", encoding="utf-8") as fh:
            fh.write(twice)
        read = M.read_rows(root, manifest_path=mpath)
        lost = [(e.get("subject"), e.get("field"))
                for e in read.get("unreadableRecords") or []]
        try:
            M._mio.read_json(shards["P1"])
            plain_status = "read, a copy kept"
        except M._mio.DuplicateKeyError as exc:
            plain_status = exc.pointers
        check("dk1 RED-FIRST: a record writing `status` twice, the green word "
              "last, is a record that will not read - named by that field - "
              "never a green; the plan's other readers refuse the file through "
              "the door, naming the key: lost %r, picked %r, plain read %r"
              % (lost, [r.get("runId") for r in read["rows"]
                        if r.get("taskId") == "P1.1"], plain_status),
              lost == [("P1.1", "lastRun.status")]
              and isinstance(plain_status, list) and len(plain_status) == 1
              and plain_status[0].endswith("/lastRun/status")
              and not any(r.get("taskId") == "P1.1"
                          and r.get("status") == "passed"
                          for r in read["rows"]))
        # UNDER THE LOCK: the shard is read by the writer itself, so the
        # record it replaces is the unreadable one, never a passing record.
        seen = {}

        def change(body):
            task = [t for t in body["tasks"] if t["id"] == "P1.1"][0]
            seen["problem"] = M.record_problem(task[M.RECORD_KEY], doc)
            seen["readable"] = M.readable_record(task, task)
            return None, "a look, no write", None
        locked = M.write_plan_file(root, shards["P1"], change, "looking")
        # ...and the tip's read of the same file, as close-phase reads it.
        cp = _loader.load_script("close-phase.py", "dk_close_phase")
        with io.open(cp.__file__, encoding="utf-8") as fh:
            tip = [n for n in ast.walk(ast.parse(fh.read()))
                   if isinstance(n, ast.FunctionDef) and n.name == "_tip_json"]
        calls = set(n.func.attr for n in ast.walk(tip[0])
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)) if tip else set()
        parsed = M.plan_json_text(twice)
        task = [t for t in parsed["tasks"] if t["id"] == "P1.1"][0]
        # Under the lock the file is refused whole before any change sees
        # it; the record's own reader, asked of it as parsed, refuses it too.
        parsed_lock = M.plan_json(shards["P1"])
        held_task = [t for t in parsed_lock["tasks"] if t["id"] == "P1.1"][0]
        check("dk2 RED-FIRST: ...and so it is under the lock, where the writer "
              "refuses the file before any change is handed it and the record "
              "it would replace reads as none, and at the branch tip, whose "
              "reader parses through the same hook: lock %r / %r, tip reader "
              "calls %r, tip parse %r"
              % (locked.get("reason"), seen, sorted(calls),
                 M.record_problem(task[M.RECORD_KEY], doc)),
              locked.get("written") is False and seen == {}
              and "written twice" in (locked.get("reason") or "")
              and M.readable_record(held_task, held_task) is None
              and "plan_json_text" in calls
              and (M.record_problem(task[M.RECORD_KEY], doc) or {}).get(
                  "field") == "lastRun.status")
    except Exception as exc:                                   # noqa: BLE001
        check("dk0 the duplicate-key block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- the holder decides: its newest run, and an object it writes twice ------------
def _ho_rows(scope_red, key_red="sha256:key"):
    """An older green of task P1.1 on its own gate, and a newer red of it on
    the gate `scope_red` names, both under one identity unless `key_red`."""
    green = dict(_lr_row("HO-GREEN", "2026-11-18T04:00:00Z", status="passed"),
                 failed=[], steps=[{"name": "sweep", "exit": 0, "ran": 3,
                                    "measured": "checks", "durationMs": 10}])
    red = dict(_lr_row("HO-RED", "2026-11-18T05:00:00Z"), scope=scope_red,
               reuseKey=key_red,
               gateSource="phase" if scope_red == "phase" else "task")
    return green, red


def _holder_cases(check):
    """(ho) The newest run of the subject holding a record decides whether
    anything may be repeated for it, in both ledger states; a key the holder
    writes twice - its record's own key included, at any depth - makes its
    record unreadable at every read, the writer refuses to rewrite the file,
    and deleting the copy by hand then recording again is the way out."""
    ids = {"taskId": "P1.1", "phaseId": "P1"}
    statuses = frozenset(("passed", "failed"))
    tmp = _harness.fixture_root("audit-evidence-holder-")
    try:
        green, red = _ho_rows("phase")
        found = M.reusable_run([green, red], "task", ids, "sha256:key",
                               statuses)
        # THE OTHER LEDGER STATE: the newer red held only as the task's
        # record, the green only as a ledger row.
        root, mpath, spath = _lr_project(tmp, "ho-record")
        M.append_row(root, green)
        wrote = M.write_record(root, mpath, "phase", ids, M.run_record(red))
        rows = M.read_rows(root, manifest_path=mpath)["rows"]
        from_record = M.reusable_run(rows, "task", ids, "sha256:key",
                                     statuses)
        check("ho1 RED-FIRST: after a gate-source flip an older green on the "
              "task's own gate is never repeated over a newer red measured on "
              "the phase's gate - the holder's newest run decides - with the "
              "red as a ledger row, and as the task's record alone: %r"
              % ((found and found.get("runId"), wrote.get("written"),
                  from_record and from_record.get("runId"),
                  [(r.get("runId"), r.get("scope")) for r in rows]),),
              found is None and wrote.get("written") is True
              and from_record is None
              and any(r.get("runId") == "HO-RED" and r.get("scope") == "phase"
                      for r in rows))
        newer = dict(green, runId="HO-GREEN2", ts="2026-11-18T06:00:00Z")
        repeat = dict(green, runId="HO-REP", ts="2026-11-18T07:00:00Z",
                      **{M.VERDICT_SOURCE: M.REUSED,
                         "reusedFrom": {"runId": "HO-GREEN2"}})
        allowed = M.reusable_run([green, red, newer], "task", ids,
                                 "sha256:key", statuses)
        chained = M.reusable_run([green, red, newer, repeat], "task", ids,
                                 "sha256:key", statuses)
        check("ho2 ALLOW: same holder, same gate, the newest is the green - "
              "it is repeated, and so it still is after a repeat of it: %r"
              % ((allowed and allowed.get("runId"),
                  chained and chained.get("runId")),),
              (allowed or {}).get("runId") == "HO-GREEN2"
              and (chained or {}).get("runId") == "HO-GREEN2")
        # A KEY THE HOLDER WRITES TWICE: the task writes `lastRun` twice, the
        # green copy last - the shape a merge keeping both sides leaves.
        droot, dmpath, dspath = _lr_project(tmp, "ho-dup")
        M.write_record(droot, dmpath, "task", ids, M.run_record(
            dict(green, runId="HO-OLD", ts="2026-11-18T03:00:00Z")))
        body = _lr_shard(dspath)
        task = body["tasks"][0]
        red_text = json.dumps(M.run_record(dict(red, scope="task",
                                                gateSource="task")))
        green_text = json.dumps(M.run_record(green))
        text = json.dumps(body)
        held = json.dumps(task[M.RECORD_KEY])
        twice = text.replace('"%s": %s' % (M.RECORD_KEY, held),
                             '"%s": %s, "%s": %s' % (M.RECORD_KEY, red_text,
                                                     M.RECORD_KEY, green_text))
        with io.open(dspath, "w", encoding="utf-8") as fh:
            fh.write(twice)
        read = M.read_rows(droot, manifest_path=dmpath)
        lost = [(e.get("subject"), e.get("field"))
                for e in read.get("unreadableRecords") or []]
        picked = [r.get("runId") for r in read["rows"]
                  if r.get("taskId") == "P1.1"]
        tip = M._plan_records(M.plan_json_text(twice), M.record_schema()[0])
        _ev_validate = _loader.load_script("validate-manifest.py",
                                           "ho_validate")
        warned = _ev_validate.record_rule_warnings(dmpath, droot)
        check("ho3 RED-FIRST: a task writing its record's key twice, the "
              "green copy last, holds no readable record - at the walk, at "
              "the branch tip's parse, and in validate-manifest's warnings - "
              "and no green is picked: lost %r, picked %r, tip %r, warned %r"
              % (lost, picked, [(s, i, (p or {}).get("field"))
                                for s, i, _r, p in tip], warned[:1]),
              lost == [("P1.1", M.RECORD_KEY)]
              and "HO-GREEN" not in picked
              and [(s, (p or {}).get("field")) for s, _i, _r, p in tip]
              == [("task", M.RECORD_KEY)]
              and any("written twice" in str(w) for w in warned))
        before = io.open(dspath, encoding="utf-8").read()
        refused = M.write_record(droot, dmpath, "task", ids,
                                 M.run_record(dict(green, runId="HO-NEW",
                                                   ts="2026-11-18T08:00:00Z")))
        after = io.open(dspath, encoding="utf-8").read()
        check("ho4 RED-FIRST: the writer refuses to rewrite a file that "
              "writes a key twice rather than keeping one copy - the file "
              "byte for byte as it was, the sentence naming the key and the "
              "way out: %r" % (refused.get("reason"),),
              refused.get("written") is False and before == after
              and "written twice" in (refused.get("reason") or "")
              and "by hand" in (refused.get("reason") or "")
              and "--record" in (refused.get("reason") or ""))
        # THE WAY OUT: the copy not meant deleted by hand, then recorded.
        with io.open(dspath, "w", encoding="utf-8") as fh:
            fh.write(text.replace('"%s": %s' % (M.RECORD_KEY, held),
                                  '"%s": %s' % (M.RECORD_KEY, red_text)))
        again = M.write_record(droot, dmpath, "task", ids,
                               M.run_record(dict(green, runId="HO-NEW",
                                                 ts="2026-11-18T08:00:00Z")))
        read = M.read_rows(droot, manifest_path=dmpath)
        check("ho5 THE WAY OUT: with the copy deleted by hand, recording "
              "again writes the new run and the plan reads with nothing "
              "unreadable: %r" % ((again.get("written"), again.get("reason"),
                                   read.get("unreadableRecords")),),
              again.get("written") is True
              and not read.get("unreadableRecords")
              and "HO-NEW" in [r.get("runId") for r in read["rows"]])
        # AT ANY DEPTH: a step's name written twice inside the record, and a
        # phase's key written twice outside its tasks.
        deep = json.loads(red_text)
        deep_text = json.dumps(deep).replace(
            '"name": "sweep"', '"name": "sweep", "name": "other"', 1)
        nested = M.plan_json_text('{"id": "P1", "tasks": [{"id": "P1.1", '
                                  '"lastRun": %s}]}' % (deep_text,))
        phase_twice = M.plan_json_text(
            '{"id": "P1", "notes": {"a": 1, "a": 2}, "lastRun": %s, '
            '"tasks": [{"id": "P1.1", "lastRun": %s}]}'
            % (green_text, green_text))
        doc = M.record_schema()[0]
        deep_found = [(s, (p or {}).get("field"))
                      for s, _i, _r, p in M._plan_records(nested, doc)]
        phase_found = [(s, (p or {}).get("field"))
                       for s, _i, _r, p in M._plan_records(phase_twice, doc)]
        check("ho6 RED-FIRST: a key written twice deep in a record - a step's "
              "name - is found where it sits, and a phase writing a key twice "
              "outside its tasks loses its own record but not its task's: "
              "%r / %r" % (deep_found, phase_found),
              deep_found == [("task", "%s.steps[0].name" % (M.RECORD_KEY,))]
              and phase_found == [("phase", "notes.a"), ("task", None)])
        # THE OTHER SIDE OF THAT LINE: a task writing a key twice outside its
        # record is inside the phase's `tasks`, which each hold their own -
        # the task loses its record, the phase keeps its own.
        task_twice = M.plan_json_text(
            '{"id": "P1", "lastRun": %s, "tasks": [{"id": "P1.1", '
            '"notes": {"a": 1, "a": 2}, "lastRun": %s}]}'
            % (green_text, green_text))
        task_found = [(s, (p or {}).get("field"))
                      for s, _i, _r, p in M._plan_records(task_twice, doc)]
        check("ho8 RED-FIRST, THE OVER-FIRE: a task writing a key twice "
              "outside its record loses its own record and leaves its phase's "
              "readable - the phase's check stops at its `tasks`: %r"
              % (task_found,),
              task_found == [("phase", None), ("task", "notes.a")])
        # A TALLY'S VIEW: no placeholder row, a withheld run's ids given back.
        placeholder = M.unreadable_row({"scope": "task", "subject": "P1.1",
                                        "phase": "P1"})
        withheld = M._withheld_row(dict(green), {"file": "f", "scope": "task",
                                                 "subject": "P1.1",
                                                 "why": "x"})
        tally = M.measured_rows([placeholder, withheld, red])
        check("ho7 RED-FIRST: a tally reads no row standing for an unreadable "
              "record, and a withheld run under the work it measured: %r"
              % ([(r.get("runId"), r.get("taskId"), M.WITHHELD_KEY in r)
                  for r in tally],),
              [(r.get("runId"), r.get("taskId"), M.WITHHELD_KEY in r)
               for r in tally] == [("HO-GREEN", "P1.1", False),
                                   ("HO-RED", "P1.1", False)])
    except Exception as exc:                                   # noqa: BLE001
        check("ho0 the holder block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- a run is held by the subject it measured ------------------------------------
# A TASK WHOSE GATE FALLS BACK TO ITS PHASE'S writes its run onto its OWN
# record, which says the phase's gate measured it, so a reader of the plan alone
# gives the run back as the task's: the phase's own newest run is never erased
# by a task's, the phase is never bound by a task's green, and the task's red is
# never passed over for an older green of its own. No ledger in these fixtures
# but where a case says so.
def _hs_project(tmp, name):
    root = os.path.join(tmp, name)
    mpath, shards = ri_plan(root)
    return root, mpath, shards["P1"]


def _hs_bind(root, mpath, ids, source):
    import _verdict_binding
    who = ids.get("taskId") or ids.get("phaseId")
    got = _verdict_binding.binding(root, ids, ["sweep"], source, [], mpath,
                                   "record %s" % (who,), "no gate")
    return (got.get("state"), got.get("arm"),
            (got.get("row") or {}).get("runId"))


def _hs_sequence(tmp, label, phase_red):
    """`{phase, task, records, code, text}` - phase P1 measured (red when
    `phase_red`), a second later task P1.2 measured green on the phase's gate,
    both by the runner itself; the ledger removed unless `label` is "on"; the
    branch committed and close-phase asked, dry, from `main`. `phase` and
    `task` are the two run ids, `records` the run ids the phase's record and
    P1.2's hold."""
    root = os.path.join(tmp, "sequence-%s" % (label,))
    mpath, shards = _bb_plan(root, "phase")
    _bb_repo(root)
    fx = {"root": root, "mpath": mpath}
    phase = _bb_gate(fx, "P1", red=phase_red, again=True)[2]
    time.sleep(1.05 - time.time() % 1)
    task = _bb_gate(fx, "P1", "P1.2", again=True)[2]
    if label != "on":
        _harness.remove_tree(M.evidence_dir(root))
    with io.open(shards["P1"], encoding="utf-8") as fh:
        body = json.load(fh)
    records = ((body.get(M.RECORD_KEY) or {}).get("runId"),
               (_bb_holder(body, "P1.2").get(M.RECORD_KEY) or {}).get("runId"))
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-q", "-m", "runs")
    _harness.git(root, "checkout", "-q", "main")
    code, text = _bb_text(*_harness.run_script(
        _bb_script("plugins/audit/scripts/git/close-phase.py"),
        [mpath, "P1", "--project", root, "--dry-run", "--keep-branch"], root,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=root)))
    return {"phase": phase, "task": task, "records": records, "code": code,
            "text": text}


def _held_by_subject_cases(check):
    """(hs) A run is held by the subject it measured, read off the plan alone."""
    tmp = _harness.fixture_root("audit-evidence-held-by-")
    try:
        # One direction: the phase's own red, then a fallback task's green on
        # the phase's gate - the phase is not bound by the task's green.
        root, mpath, shard = _hs_project(tmp, "green-over-phase-red")
        ri_put_record(shard, None, M.run_record(_wh_row(
            "HS-PH-RED", "2026-11-18T08:00:00Z", "failed", scope="phase",
            task=None)))
        fb = _wh_row("HS-FB-GREEN", "2026-11-18T10:00:00Z", "passed",
                     scope="phase", task="P1.3")
        fb["gateSource"] = "phase"
        wrote = M.write_record(root, mpath, "phase",
                               {"phaseId": "P1", "taskId": "P1.3"},
                               M.run_record(fb))
        ledger_absent = not os.path.isdir(M.evidence_dir(root))
        rows = M.read_rows(root, manifest_path=mpath)["rows"]
        back = [(r.get("scope"), r.get("taskId"), r.get("phaseId"))
                for r in rows if r.get("runId") == "HS-FB-GREEN"]
        with io.open(shard, encoding="utf-8") as fh:
            body = json.load(fh)
        on = ((body.get(M.RECORD_KEY) or {}).get("runId"),
              [((t.get(M.RECORD_KEY) or {}).get("runId"),
                (t.get(M.POINTER_KEY) or {}).get("runId"))
               for t in body.get("tasks") or [] if t.get("id") == "P1.3"])
        phase = _hs_bind(root, mpath, {"phaseId": "P1"}, "phase")
        task = _hs_bind(root, mpath, {"taskId": "P1.3", "phaseId": "P1"},
                        "phase")
        # The task's binding is asked which run it reads: past the selection
        # the fixture's gate digest is not the declared gate's, so the arm
        # after it is the gate's, which is not what this case is about.
        check("hs1 RED-FIRST: a fallback task's green is written onto the "
              "TASK's record and pointer, never over the phase's own red, and "
              "read back as the task's run - the phase still answers from its "
              "own red, and the green is the run the task's binding reads: "
              "written=%r ledger absent=%r on (phase, P1.3)=%r read back=%r "
              "phase=%r task=%r"
              % (wrote.get("written"), ledger_absent, on, back, phase, task),
              wrote.get("written") and ledger_absent
              and on == ("HS-PH-RED", [("HS-FB-GREEN", "HS-FB-GREEN")])
              and back == [("phase", "P1.3", "P1")]
              and phase == ("refused", "red", "HS-PH-RED")
              and task[2] == "HS-FB-GREEN"
              and task[1] not in ("no-verdict", "unreadable"))

        # The other direction: the task's own older green, then its red on
        # the phase's gate - the task's binding sees the red.
        root, mpath, shard = _hs_project(tmp, "red-over-task-green")
        old = _wh_row("HS-T-GREEN", "2026-11-18T08:00:00Z", "passed",
                      task="P1.3")
        old.pop("gateSource", None)
        ri_put_record(shard, "P1.3", M.run_record(old))
        fb = _wh_row("HS-FB-RED", "2026-11-18T10:00:00Z", "failed",
                     scope="phase", task="P1.3")
        fb["gateSource"] = "phase"
        M.write_record(root, mpath, "phase", {"phaseId": "P1",
                                              "taskId": "P1.3"},
                       M.run_record(fb))
        task = _hs_bind(root, mpath, {"taskId": "P1.3", "phaseId": "P1"},
                        "phase")
        check("hs2 RED-FIRST, THE OTHER DIRECTION: the task's red on the phase's "
              "gate, written over its own older green on its own record, is "
              "what the task's binding sees - never that green: %r" % (task,),
              task == ("refused", "red", "HS-FB-RED"))

        # A record written before the phase's record kept who ran it is read
        # exactly as it was: the phase's run.
        root, mpath, shard = _hs_project(tmp, "previous-release")
        ri_put_record(shard, None, M.run_record(dict(_wh_row(
            "HS-OLD", "2026-11-18T08:00:00Z", "passed", scope="phase",
            task=None))))
        back = [(r.get("scope"), r.get("taskId"), r.get("phaseId"))
                for r in M.read_rows(root, manifest_path=mpath)["rows"]
                if r.get("runId") == "HS-OLD"]
        check("hs3 ALLOW: a phase record that names no task - every record "
              "written before this - is the phase's run, read as before: %r"
              % (back,), back == [("phase", None, "P1")])

        # The task's own record that would not read is replaced by a newer
        # run of the same task: re-recording its gate is the repair.
        root, mpath, shard = _hs_project(tmp, "repair-by-record")
        bad = M.run_record(_wh_row("HS-BAD", "2026-11-18T08:00:00Z", "failed",
                                   task="P1.3"))
        bad["steps"] = 5
        ri_put_record(shard, "P1.3", bad)
        fb = _wh_row("HS-FB-NEW", "2026-11-18T10:00:00Z", "failed",
                     scope="phase", task="P1.3")
        fb["gateSource"] = "phase"
        M.write_record(root, mpath, "phase", {"phaseId": "P1",
                                              "taskId": "P1.3"},
                       M.run_record(fb))
        read = M.read_rows(root, manifest_path=mpath)
        lost = [(e.get("scope"), e.get("subject"))
                for e in read.get("unreadableRecords") or []]
        task = _hs_bind(root, mpath, {"taskId": "P1.3", "phaseId": "P1"},
                        "phase")
        check("hs4 RED-FIRST: re-recording a fallback task whose own record "
              "would not read leaves no unreadable record of it behind - the "
              "run just recorded is newer than anything that record held - "
              "and the task's binding then answers from the new run: "
              "lost=%r task=%r" % (lost, task),
              lost == [] and task == ("refused", "red", "HS-FB-NEW"))

        # THE PHASE RECORDED AGAIN OVER ITS OWN RECORD THAT WOULD NOT READ:
        # that record held the phase's own runs alone, so the new run is the
        # phase's newest and every task keeps its own answer.
        root, mpath, shard = _hs_project(tmp, "phase-over-unread")
        bad = M.run_record(_wh_row("HS-PBAD", "2026-11-18T08:00:00Z",
                                   "failed", scope="phase", task=None))
        bad["steps"] = 5
        ri_put_record(shard, None, bad)
        old = _wh_row("HS-P13-OLD", "2026-11-18T06:00:00Z", "passed",
                      scope="phase", task="P1.3")
        old["gateSource"] = "phase"
        M.append_row(root, old)
        before = M.newest_row([r for r in M.read_rows(
            root, manifest_path=mpath)["rows"] if M._same_subject(
                r, {"phaseId": "P1"})])
        M.write_record(root, mpath, "phase", {"phaseId": "P1"}, M.run_record(
            dict(_wh_row("HS-PNEW", "2026-11-18T10:00:00Z", "failed",
                         scope="phase", task=None), gateSource="phase")))
        rows = M.read_rows(root, manifest_path=mpath)["rows"]
        p13 = M.newest_row([r for r in rows if M._same_subject(
            r, {"taskId": "P1.3", "phaseId": "P1"})])
        with io.open(shard, encoding="utf-8") as fh:
            record_keys = sorted(json.load(fh).get(M.RECORD_KEY) or {})
        phase_now = _hs_bind(root, mpath, {"phaseId": "P1"}, "phase")
        check("hs5 the phase's own record that would not read stands for the "
              "phase alone: before it is measured again the phase's newest is "
              "the row standing for it, and measured again the phase answers "
              "from its new red - while task P1.3 keeps its own green "
              "throughout, the lost record never having held a task's run: "
              "phase before %r, P1.3 newest %r, phase %r, record keys %r"
              % ((before or {}).get("runId"), (p13 or {}).get("runId"),
                 phase_now, record_keys),
              M.is_unreadable_row(before)
              and (p13 or {}).get("runId") == "HS-P13-OLD"
              and phase_now == ("refused", "red", "HS-PNEW")
              and "unreadHeld" not in record_keys)

        # A REPOSITORY WITH NO COMMIT YET: the run's head could not be taken,
        # and the record written for it is one its own reader accepts, so the
        # subject's runs are its own rather than withheld behind a record
        # the writer itself made unreadable.
        root, mpath, shard = _hs_project(tmp, "no-head")
        headless = _wh_row("HS-NOHEAD", "2026-11-18T08:00:00Z", "passed",
                           scope="phase", task=None)
        headless["testedState"] = {"head": None, "dirtyDigest": None,
                                   "scopeDigest": None}
        record = M.run_record(headless)
        said = M.record_problem(record, _json_schema.load_document(_RK_SCHEMA))
        M.write_record(root, mpath, "phase", {"phaseId": "P1"}, record)
        read = M.read_rows(root, manifest_path=mpath)
        check("hs6 RED-FIRST: a run measured where no head could be taken is "
              "recorded without one - not as null, which the published record "
              "refuses - so its own reader reads it back as the phase's run: "
              "problem %r, unreadable %r, state %r"
              % (said, read.get("unreadablePlanFiles"),
                 record.get("testedState")),
              said is None and not read.get("unreadablePlanFiles")
              and "head" not in (record.get("testedState") or {})
              and (record.get("testedState") or {}).get("scopeDigest", 0)
              is None)

        # THE SEQUENCE, THROUGH THE COMMANDS: the phase measured red, then a
        # task on the phase's gate measured green, then the branch closed -
        # with the ledger gone, the plan alone, and with it kept.
        said = {}
        for ledger, phase_red in (("off", True), ("on", True),
                                  ("off-green", False)):
            said[ledger] = _hs_sequence(tmp, ledger, phase_red)
        off, on, allow = said["off"], said["on"], said["off-green"]
        check("hs7 RED-FIRST, THE LEDGER OFF: phase P1 measured red, then task "
              "P1.2 measured green on the phase's gate, then the ledger gone - "
              "the phase's record still names its own red and the task's names "
              "its green, and close-phase refuses to land P1 on the task's "
              "run, naming the phase's red: records %r, close exit %r, said %r"
              % (off["records"], off["code"], off["text"][-500:]),
              off["records"] == (off["phase"], off["task"])
              and off["code"] != 0 and off["phase"] in off["text"]
              and off["task"] not in off["text"])
        check("hs8 ...THE LEDGER ON: the same sequence with every ledger line "
              "kept refuses the same way: records %r, close exit %r, said %r"
              % (on["records"], on["code"], on["text"][-500:]),
              on["records"] == (on["phase"], on["task"])
              and on["code"] != 0 and on["phase"] in on["text"]
              and on["task"] not in on["text"])
        check("hs9 ALLOW: the phase measured green, then the task green on the "
              "phase's gate, the ledger gone - close-phase lands P1 on the "
              "phase's own green, so the refusals above are about the red: "
              "records %r, close exit %r, said %r"
              % (allow["records"], allow["code"], allow["text"][-500:]),
              allow["records"] == (allow["phase"], allow["task"])
              and allow["code"] == 0 and allow["phase"] in allow["text"])
    except Exception as exc:                                   # noqa: BLE001
        check("hs0 the held-by-subject block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- one black-box case over every command that reads runs ---------------------
# THE COMMANDS ARE DERIVED, NOT LISTED. A reader is a function of the two modules
# that read runs which calls, in either of them, one of the seeds below or a
# reader; an entry point is a command file whose own code, or anything it imports
# from `scripts/`, calls a reader through the module that holds it. Each derived
# command has a row in `_BB_ENTRIES` - how it is run, or why it is not - and a
# row with no command, or a command with no row, is red by name (`bb-table`).
#
# WHAT THE DERIVATION CANNOT SEE: a module loaded by path (`_loader`) rather than
# imported, a command that parses ledger lines itself without the two modules,
# and a call through a name bound any other way than an import. It sees too much
# as well: a file is listed when anything it imports calls a reader, whether or
# not the command ever reaches that call - its row then says so.
_BB_READER_MODULES = ("_evidence_io", "_verdict_binding")
_BB_SEEDS = ("read_rows", "with_records", "records_of_bodies", "rows_of",
             "ledger_texts")
_BB_ENTRY_DIRS = (("plugins/audit/scripts", True), ("plugins/audit/hooks", False),
                  (".claude/hooks", False), ("tools", False),
                  ("tools/demo", False))
_BB_BRANCH = "audit/p1-demo"
_BB_CMD = ('"%s" -c "import os,sys; sys.exit(int(os.environ.get('
           '\'BB_RED\', \'0\')))"' % (sys.executable,))
_BB_RTG = os.path.join(_output.SCRIPTS_DIR, "governance", "run-test-gate.py")
# (variant, phase, task) - the subject whose newest red is held only as a
# record, an older green of the same content in the ledger.
_BB_VARIANTS = (("task", "P1", "P1.1"), ("phase", "P1", None),
                ("member", "P2", None), ("fallback", "P1", "P1.2"),
                ("ledger-absent", "P1", "P1.2"))


def _bb_parse(path):
    with io.open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), path)


def _bb_bound(tree):
    """`({name: module}, {name: (module, attr)})` - what each import in `tree`
    binds, function-level imports included."""
    mods, attrs = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods[a.asname or a.name.split(".")[0]] = a.name.split(".")[-1]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                attrs[a.asname or a.name] = (node.module.split(".")[-1], a.name)
    return mods, attrs


def _bb_calls(tree, readers, own=None):
    """Whether `tree` calls a reader: `alias.fn` through an import of a reader
    module, a name imported from one, or - inside reader module `own` - a
    reader of its own by bare name."""
    mods, attrs = _bb_bound(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and (mods.get(f.value.id), f.attr) in readers:
            return True
        if isinstance(f, ast.Name) and (attrs.get(f.id) in readers
                                        or (own, f.id) in readers):
            return True
    return False


def _bb_modules():
    """{basename: path} of every module under `scripts/`."""
    out = {}
    for d, _subs, files in os.walk(_output.SCRIPTS_DIR):
        for name in files:
            if name.endswith(".py"):
                out[name[:-3]] = os.path.join(d, name)
    return out


def _bb_readers(modules):
    """`{(module, function)}` - the seeds, then every top-level function of a
    reader module that calls one, to a fixpoint across both modules."""
    readers = set((m, s) for m in _BB_READER_MODULES for s in _BB_SEEDS)
    defs = dict((m, [n for n in _bb_parse(modules[m]).body
                     if isinstance(n, ast.FunctionDef)])
                for m in _BB_READER_MODULES)
    grew = True
    while grew:
        grew = False
        for m, nodes in defs.items():
            for node in nodes:
                if (m, node.name) not in readers \
                        and _bb_calls(node, readers, own=m):
                    readers.add((m, node.name))
                    grew = True
    return readers


def _bb_derived():
    """`(sorted repo-relative command paths that reach a reader, readers)`."""
    modules = _bb_modules()
    readers = _bb_readers(modules)
    memo = {}

    def reaches(path, seen):
        if path in memo:
            return memo[path]
        if path in seen:
            return False
        seen.add(path)
        tree = _bb_parse(path)
        hit = _bb_calls(tree, readers)
        if not hit:
            mods, attrs = _bb_bound(tree)
            names = set(mods.values()) | set(m for m, _a in attrs.values())
            hit = any(reaches(modules[n], seen) for n in sorted(names)
                      if n in modules and n not in _BB_READER_MODULES)
        memo[path] = hit
        return hit
    found = []
    for rel, deep in _BB_ENTRY_DIRS:
        top = os.path.join(_output.REPO_ROOT, *rel.split("/"))
        walk = os.walk(top) if deep else [(top, [], sorted(os.listdir(top)))]
        for d, _subs, files in walk:
            for name in sorted(files):
                if not name.endswith(".py") or name.startswith("_"):
                    continue
                path = os.path.join(d, name)
                if reaches(path, set()):
                    found.append(os.path.relpath(
                        path, _output.REPO_ROOT).replace(os.sep, "/"))
    return sorted(found), readers


def _bb_script(rel):
    return os.path.join(_output.REPO_ROOT, *rel.split("/"))


# Each derived command: `(argv for a fixture, variants, passing pattern)` -
# `argv(fx)` its arguments, `fx` the fixture `_bb_build` returns; the variants
# it answers about; the words that would be it passing the subject - or a
# string, the reason it is not run here.
def _bb_status(fx):
    return [fx["mpath"], "--json"]


_BB_ALL = tuple(v[0] for v in _BB_VARIANTS)
_BB_TASKS = ("task", "fallback", "ledger-absent")
_BB_ENTRIES = {
    "plugins/audit/scripts/governance/run-test-gate.py": (
        lambda fx: [fx["mpath"], fx["phase"]] + (
            ["--task", fx["task"]] if fx["task"] else []) + [
            "--record", "--project-dir", fx["root"]],
        _BB_ALL, r"GATE GREEN"),
    "plugins/audit/scripts/git/close-phase.py": (
        lambda fx: [fx["mpath"], fx["phase"], "--project", fx["root"],
                    "--dry-run", "--keep-branch"],
        ("phase", "member"), r"bound to run"),
    "plugins/audit/scripts/manifest/audit-task.py": (
        lambda fx: ["done", fx["task"], fx["mpath"], "--commit", fx["sha"],
                    "--project-dir", fx["root"], "--descriptive", "bb",
                    "--technical", "bb", "--verified-by", "bb"],
        _BB_TASKS, r"gate: bound"),
    "plugins/audit/scripts/status/audit-status.py": (_bb_status, _BB_ALL,
                                                      None),
    # `run latest` for the variant's subject: the lookup's own newest-run
    # pick, the one place a reader of this table asks a picker by name.
    "plugins/audit/scripts/status/audit-lookup.py": (
        lambda fx: [fx["mpath"], "--project", fx["root"], "run", "latest"] + (
            ["--task", fx["task"]] if fx["task"] else ["--phase", fx["phase"]]),
        _BB_ALL, None),
    "plugins/audit/scripts/status/audit-doctor.py": (
        lambda fx: ["--project", fx["root"]], _BB_ALL, None),
    "plugins/audit/scripts/report/render-report.py": (
        lambda fx: [fx["mpath"], "--out-dir", fx["out"], "--format", "md"],
        _BB_ALL, None),
    "plugins/audit/scripts/manifest/validate-manifest.py": (
        lambda fx: [fx["mpath"]], _BB_ALL, None),
    "plugins/audit/scripts/governance/derive-phase-gate.py": (
        "narrows a gate only under `meta.phaseGate.mode` with a runner and a "
        "listing declared; its one read of runs, "
        "`_gate_derive.newest_red_phase_row`, takes `failed` rows keyed to "
        "the phase, which neither a withheld run nor the row standing for a "
        "record is"),
    "plugins/audit/scripts/governance/propose-gates.py": (
        lambda fx: [fx["mpath"], "--project", fx["root"], "--json",
                    "--command", _BB_CMD], _BB_ALL, None),
    "plugins/audit/scripts/usage/audit-usage.py": (
        lambda fx: [fx["mpath"], "--project-dir", fx["root"], "--json"],
        _BB_ALL, None),
    "plugins/audit/scripts/governance/full-gate.py": (
        lambda fx: [fx["mpath"], "--project-dir", fx["root"]], _BB_ALL, None),
    "plugins/audit/scripts/panel/panel-server.py": (
        "a server; what it serves about runs is `_panel_state.build_state`, "
        "which this block runs in its place (`bb-panel-state`)"),
    "plugins/audit/scripts/governance/drive-phase.py": (
        "picks no subject's newest run of its own: its gate verdict is the "
        "runner's (`run-test-gate.py`, rows above), and each site reading "
        "recorded runs is named in `_BB_DRIVE_SITES` with why it cannot "
        "pick an older run for a subject (`bb-drive-sites`)"),
    "plugins/audit/scripts/governance/commit-task-work.py": (
        "commits a task's work over `task_binding`, the question "
        "`audit-task.py done` asks of the same fixture here; a commit needs "
        "a task worktree this fixture does not build"),
    "plugins/audit/scripts/manifest/migrate-json-encoding.py": (
        "listed through an import whose readers it never calls: it rewrites "
        "the plan's encoding"),
    "plugins/audit/scripts/manifest/repair-commits.py": (
        "listed through an import whose readers it never calls: it repairs "
        "task commits"),
    "plugins/audit/scripts/manifest/repair-tests-add.py": (
        "listed through an import whose readers it never calls: it repairs "
        "`tests.add`"),
    "plugins/audit/scripts/manifest/set-priority.py": (
        "listed through an import whose readers it never calls: it sets a "
        "phase's priority"),
    "tools/check-example-ledgers.py": (
        "holds the pointers every manifest this repository keeps caches to "
        "the runs the plans record and the frozen ledger rows hold, over "
        "this repository's own tree rather than a project's plan; its own "
        "suite's el31-el33 read a fixture's record"),
    "tools/gate-parity.py": (
        "reads this repository's workflow and gate slices, not a plan's "
        "runs"),
    "tools/plan-window.py": (
        "a maintainer's window over this repository's own plan, never run "
        "against a fixture"),
}


def _bb_plan(root, variant):
    """A sharded plan under `root`: P1 (its own gate; task P1.1 with a gate of
    its own, P1.2 on the phase's) and P2, both signed off on one branch."""
    _project(root, {"manifestPath": "docs/audit/audit-plan.json"})
    os.makedirs(os.path.join(root, "docs", "audit", "phases"))
    landing = "done" if variant in ("phase", "member") else "in_progress"
    p1 = {"id": "P1", "title": "one", "status": "in_progress",
          "branch": _BB_BRANCH, "baseRef": None, "mergedAt": None,
          "parentBranch": "main", "review": {"status": "passed"},
          "testGate": ["chk"], "tasks": [
              {"id": "P1.1", "title": "own gate", "status": landing,
               "tests": {"mode": "gate-only", "gate": ["chk"]},
               "files": ["src/a.py"]},
              {"id": "P1.2", "title": "the phase's gate", "status": landing,
               "files": ["src/b.py"]}]}
    if variant == "ledger-absent":
        p1["tasks"][1]["tests"] = {"mode": "gate-only", "gate": ["chk"]}
    p2 = {"id": "P2", "title": "two", "status": "in_progress",
          "branch": _BB_BRANCH, "baseRef": None, "mergedAt": None,
          "parentBranch": "main", "review": {"status": "passed"},
          "testGate": ["chk"], "tasks": [
              {"id": "P2.1", "title": "member", "status": "done",
               "files": ["src/c.py"]}]}
    if variant == "member":
        # Signed off in a group with P1 carrying it, as the parent holds it:
        # a landing asks the parent's plan which phases a run grades.
        p2[M.POINTER_KEY] = {"runId": "bb-group-run", "status": "passed",
                             "gradedBy": "P1"}
    shards = {}
    for body in (p1, p2):
        shards[body["id"]] = os.path.join(root, "docs", "audit", "phases",
                                          "%s.json" % (body["id"],))
        with io.open(shards[body["id"]], "w", encoding="utf-8") as fh:
            json.dump(body, fh)
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    with io.open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"version": 3, "developmentBranch": "main",
                            "buildCommands": {"chk": _BB_CMD}},
                   "fileIndex": {"src/a.py": ["P1.1"], "src/b.py": ["P1.2"],
                                 "src/c.py": ["P2.1"]},
                   "phases": [{"id": p, "title": p, "shard":
                               "phases/%s.json" % (p,)}
                              for p in ("P1", "P2")]}, fh)
    return mpath, shards


def _bb_text(code, out, err):
    return code, (out.decode("utf-8", "replace")
                  + err.decode("utf-8", "replace"))


def _bb_gate(fx, phase, task=None, red=False, again=False, extra=()):
    """`(exit, text, run id)` of one recorded gate run in the fixture."""
    env = dict(os.environ, BB_RED="1" if red else "0")
    args = ([fx["mpath"], phase] + (["--task", task] if task else [])
            + ["--record", "--project-dir", fx["root"]]
            + (["--no-reuse"] if again else []) + list(extra))
    code, text = _bb_text(*_harness.run_script(_BB_RTG, args, fx["root"],
                                               env=env))
    found = re.search(r"evidence: recorded ([^\s;]+)", text)
    return code, text, found.group(1) if found else None


def _bb_edit(path, change):
    with io.open(path, encoding="utf-8") as fh:
        body = json.load(fh)
    change(body)
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh)


def _bb_holder(body, task):
    return body if task is None else [t for t in body["tasks"]
                                      if t["id"] == task][0]


def _bb_repo(root):
    """The fixture's git under `root`, whose plan is already written: a
    base commit on `main`, then the phase branch with work on it, checked
    out."""
    _harness.git(None, "init", "-q", root)
    _harness.git(root, "checkout", "-q", "-b", "main")
    _harness.git(root, "config", "user.name", "bb")
    _harness.git(root, "config", "user.email", "bb@example.invalid")
    os.makedirs(os.path.join(root, "src"))
    for name in ("a", "b", "c"):
        with io.open(os.path.join(root, "src", "%s.py" % (name,)), "w",
                     encoding="utf-8") as fh:
            fh.write("BASE = 1\n")
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-q", "-m", "base")
    _harness.git(root, "checkout", "-q", "-b", _BB_BRANCH)
    for name in ("a", "b", "c"):
        with io.open(os.path.join(root, "src", "%s.py" % (name,)), "a",
                     encoding="utf-8") as fh:
            fh.write("WORK = 2\n")
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-q", "-m", "work")


# Each way the subject's record will not read, as the fixture plants it:
# `steps` not the schema's, an `at` that names no moment (`moment_problem`),
# and `status` written twice in the file, the green word last
# (`duplicate_key_problem`).
_BB_SHAPES = ("steps", "at", "duplicate")
_BB_DUP_MARK = "bb-duplicate-status"


def _bb_malform(path, task, shape):
    """Plant `shape` (`_BB_SHAPES`) in the record of `task` (the phase's when
    None) in the plan file at `path`."""
    def plant(body):
        record = _bb_holder(body, task)[M.RECORD_KEY]
        if shape == "steps":
            record["steps"] = 5
        elif shape == "at":
            record["at"] = "not a time"
        else:
            record["status"] = _BB_DUP_MARK
    _bb_edit(path, plant)
    if shape == "duplicate":
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace('"status": "%s"' % (_BB_DUP_MARK,),
                                  '"status": "failed", "status": "passed"'))


def _bb_build(tmp, variant, phase, task, malformed):
    """The fixture `variant` - its newest red held only as the record of the
    subject's holder, well-formed (`malformed` None) or broken in one of
    `_BB_SHAPES` - as `{root, mpath, phase, task, green, red, sha, holder,
    out, built}`."""
    root = os.path.join(tmp, "%s-%s" % (variant, malformed or "oracle"))
    mpath, shards = _bb_plan(root, variant)
    fx = {"root": root, "mpath": mpath, "phase": phase, "task": task,
          "variant": variant, "out": os.path.join(root, "out")}
    _bb_repo(root)
    built = []
    carrier = None
    if variant == "member":
        built.append(_bb_gate(fx, "P1", extra=["--also", "P2"]))
        carrier = built[-1][2]
    built.append(_bb_gate(fx, phase, task))
    fx["green"] = built[-1][2]
    # THE OLDER GREEN IN THE LEDGER is what a previous release left: no run
    # writes a row now, so the fixture writes the one that release would
    # have, the green as the reader gives it back, before the red replaces
    # its record.
    green_row = M.row_by_run(M.read_rows(root, manifest_path=mpath)["rows"],
                             fx["green"])
    M.append_row(root, dict(green_row))
    # A run is held by the subject it measured: a task's on the task, the
    # gate that measured it whichever.
    held_on = (phase, task)
    if variant == "ledger-absent":
        _bb_edit(shards["P1"], lambda b: _bb_holder(b, "P1.2").pop("tests"))
    # The red a second later than the green, never in the same second: a
    # stamp names whole seconds, and a tie would be decided by read order.
    time.sleep(1.05 - time.time() % 1)
    built.append(_bb_gate(fx, phase, task, red=True, again=True))
    fx["red"] = built[-1][2]
    fx["holder"] = (shards[held_on[0]], held_on[1])
    if variant == "member":
        _bb_edit(shards["P2"], lambda b: b.__setitem__(M.POINTER_KEY, {
            "runId": carrier, "status": "passed", "gradedBy": "P1"}))
    evidence = M.evidence_dir(root)
    if variant == "ledger-absent":
        _harness.remove_tree(evidence)
    else:
        for name in os.listdir(evidence):
            path = os.path.join(evidence, name)
            with io.open(path, encoding="utf-8") as fh:
                kept = [line for line in fh if fx["red"] not in line]
            with io.open(path, "w", encoding="utf-8") as fh:
                fh.writelines(kept)
    if malformed:
        _bb_malform(fx["holder"][0], fx["holder"][1], malformed)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-q", "-m", "runs")
    fx["sha"] = _harness.git(root, "rev-parse", "HEAD").strip()
    fx["built"] = [(code, run) for code, _text, run in built]
    return fx


def _bb_copy(fx, tmp, label):
    """`fx` over a fresh copy of its tree, for one command to run in."""
    root = os.path.join(tmp, label)
    shutil.copytree(fx["root"], root, symlinks=True)
    out = dict(fx, root=root, out=os.path.join(root, "out"))
    out["mpath"] = os.path.join(root, os.path.relpath(fx["mpath"], fx["root"]))
    out["holder"] = (os.path.join(root, os.path.relpath(fx["holder"][0],
                                                        fx["root"])),
                     fx["holder"][1])
    return out


def _bb_ledger(root):
    """Every ledger line under `root`, as text."""
    evidence = M.evidence_dir(root)
    lines = []
    for name in sorted(os.listdir(evidence)) if os.path.isdir(evidence) else []:
        with io.open(os.path.join(evidence, name), encoding="utf-8") as fh:
            lines.extend(fh.read().splitlines())
    return lines


def _bb_run(rel, spec, fx):
    """`(exit, text, written)` of the command `rel` over the copy `fx`:
    `written` the run ids the subject's holder now names and the ledger
    lines the command added."""
    argv, _variants, _passing = spec
    before = set(_bb_ledger(fx["root"]))
    if rel.endswith("close-phase.py"):
        _harness.git(fx["root"], "checkout", "-q", "main")
    code, text = _bb_text(*_harness.run_script(
        _bb_script(rel), argv(fx), fx["root"],
        env=dict(os.environ, BB_RED="1", CLAUDE_PROJECT_DIR=fx["root"])))
    if os.path.isdir(fx["out"]):
        text += "\n" + _us_text(fx["out"])
    with io.open(fx["holder"][0], encoding="utf-8") as fh:
        holder = _bb_holder(json.load(fh), fx["holder"][1])
    names = [str((holder.get(k) or {}).get("runId"))
             for k in (M.RECORD_KEY, M.POINTER_KEY)
             if isinstance(holder.get(k), dict)]
    added = [line for line in _bb_ledger(fx["root"]) if line not in before]
    return code, text, (names, added)


def _bb_untimed(value):
    """`value` with every `timing` member gone: a task's timing is the spend
    of each run it made, the older green's included - a tally, never an
    answer about which run is the task's verdict."""
    if isinstance(value, dict):
        return dict((k, _bb_untimed(v)) for k, v in value.items()
                    if k != "timing")
    if isinstance(value, list):
        return [_bb_untimed(v) for v in value]
    return value


def _bb_answer(text):
    """The part of a command's output that answers about runs: a JSON line is
    read without its timing (`_bb_untimed`); every other line as printed."""
    out = []
    for line in text.splitlines():
        try:
            out.append(json.dumps(_bb_untimed(json.loads(line))))
        except ValueError:
            out.append(line)
    whole = text.strip()
    if whole.startswith("{"):
        try:
            return json.dumps(_bb_untimed(json.loads(whole)))
        except ValueError:
            pass
    return "\n".join(out)


# The rows whose answer over the oracle IS the subject's newest run, so it
# names the oracle's red in every variant (`_black_box_cases`).
_BB_ORACLE_NAMES_RED = ("plugins/audit/scripts/status/audit-lookup.py",)
# EVERY FUNCTION OF THE DRIVE THAT READS RECORDED RUNS (calls its one read,
# `recorded_runs`), with why it cannot answer a subject from an older run -
# derived both ways by `bb-drive-sites`, so a new site has no reason until
# one is written here. "By id" is a run the drive's state or a row already
# named: a withheld row keeps its run id, and a lost record's row is found
# by its own.
_BB_BY_ID = ("looks up one run by the id the drive's state names "
             "(`row_by_run`), never a subject's newest")
_BB_DRIVE_SITES = {
    "ledger_row": _BB_BY_ID,
    "base_red_why": _BB_BY_ID,
    "gate_row_read": _BB_BY_ID + ", then the run it repeated (`measured_row`)",
    "red_status": _BB_BY_ID,
    "measure_launch": _BB_BY_ID + ", then the run it repeated",
    "run_followers": _BB_BY_ID + ", then the run it repeated",
    "repeat_said": _BB_BY_ID,
    "verdict_basis": "asks `stored_verdict_moved` about the run id the drive "
                     "holds, by that id",
    "repeated_measured": "follows a repeat to the run it repeated, by the "
                         "repeat's own `reusedFrom`",
    "red_at_base": "reads base runs (`base_run`), which no subject's record "
                   "holds and nothing withholds",
    "base_need": "reads base runs (`base_unmeasured`, `base_row_for`), which "
                 "no subject's record holds",
    "gate_in_background": "a mean of gate durations (`gate_mean_ms`), a tally "
                          "naming no subject's verdict",
    "new_gate_row": "a launch's own run, by its token among the rows its "
                    "subject holds (`holder_key`; block bz of "
                    "tests/test_drive_phase.py)",
    "gate_went_red": "a fix task's re-review, refusing on a lost record "
                     "(cases gu1 and gu2 of tests/test_drive_phase.py)",
    "held_green_moved": _BB_BY_ID + " (the `gated` mark's), then the run it "
                        "repeated; a row it cannot read binds nothing",
    "held_and_measured": _BB_BY_ID + " (the `gated` mark's), then the run it "
                         "repeated (`measured_row`); a repeat whose source is "
                         "gone binds nothing",
}


def _bb_drive_sites():
    """The drive's functions that call `recorded_runs`, by name."""
    drive = "plugins/audit/scripts/governance/drive-phase.py"
    tree = _bb_parse(_bb_script(drive))
    return sorted(f.name for f in ast.walk(tree)
                  if isinstance(f, ast.FunctionDef) and f.name != "recorded_runs"
                  and any(isinstance(n, ast.Call)
                          and isinstance(n.func, ast.Name)
                          and n.func.id == "recorded_runs"
                          for n in ast.walk(f)))


def _bb_wrong(rel, spec, fx, oracle, got):
    """What the command `rel` did wrong over the malformed fixture `fx`, its
    oracle's exit beside it: each of the four things it must not do."""
    _argv, _variants, passing = spec
    code, text, (names, added) = got
    text = _bb_answer(text)
    wrong = []
    if fx["green"] and fx["green"] in text:
        wrong.append("named the older run %s" % (fx["green"],))
    if passing and re.search(passing, text):
        wrong.append("said %r of the subject" % (passing,))
    if fx["green"] in names or any(fx["green"] in line for line in added):
        wrong.append("wrote the older run %s over the red (holder %r)"
                     % (fx["green"], names))
    if oracle[0] != 0 and code == 0:
        wrong.append("exited 0 where the oracle exited %r" % (oracle[0],))
    return wrong


def _bb_remedy(rel, spec, fx):
    """`(commands, their exits, exit after, why)` - the command `rel` refused
    over the malformed copy `fx`; each `run-test-gate.py` command its refusal
    printed is run exactly as printed (on the branch, committed there), then
    `rel` is asked again. `why` is "" when the answer after stands on a
    measured red, else what it said instead."""
    _code, text, _w = _bb_run(rel, spec, fx)
    # The commands the unreadable-record sentence names, and only those: the
    # caller's own sentence beside it names how to record the gate it asks.
    advice = re.search(r"measure and record the subject again with (.*?), or "
                       r"repair", text, re.S)
    commands = []
    for command in re.findall(r"`(run-test-gate\.py [^`\"]+)`",
                              advice.group(1) if advice else ""):
        if command not in commands:
            commands.append(command)
    _harness.git(fx["root"], "checkout", "-q", _BB_BRANCH)
    # THE DOOR'S REFUSAL (`_manifest_io.DuplicateKeyError`) comes before any
    # record is read, and its one step is the hand step: it names no command,
    # so the step itself is what was taken.
    door = "delete by hand the copy that is not meant" in text
    if door and not commands:
        commands.append("the door's hand step")
    by_hand = door or "delete by hand the copy of each key written twice" in text
    if by_hand:
        # THE HAND STEP THE ADVICE NAMES FIRST: each plan file saved with one
        # copy of every key - the first, the run's own word; the fixture
        # wrote the green after it, the copy not meant.
        plan_dir = os.path.dirname(fx["mpath"])
        for top, _dirs, files in os.walk(plan_dir):
            for name in files:
                if name.endswith(".json"):
                    path = os.path.join(top, name)
                    with io.open(path, encoding="utf-8") as fh:
                        once = json.load(fh, object_pairs_hook=lambda pairs:
                                         dict(reversed(pairs)))
                    with io.open(path, "w", encoding="utf-8") as fh:
                        json.dump(once, fh, indent=2)
    codes = []
    for command in commands:
        if not command.startswith("run-test-gate.py"):
            continue
        argv = command.split()
        code, said = _bb_text(*_harness.run_script(
            _BB_RTG, argv[1:], fx["root"],
            env=dict(os.environ, BB_RED="1", CLAUDE_PROJECT_DIR=fx["root"])))
        found = re.search(r"evidence: recorded ([^\s;]+)", said)
        row = M.row_by_run(M.read_rows(fx["root"], manifest_path=fx["mpath"])
                           ["rows"], found.group(1)) if found else None
        # A MEASUREMENT, never a repeat: the run the command recorded holds
        # its own verdict, `failed`. Once a copy is deleted by hand the
        # record reads again - the subject's own newest red - and a repeat
        # of THAT red is the answer the identity rule gives.
        measured = row is not None and row.get("status") == "failed" and (
            row.get(M.VERDICT_SOURCE) != M.REUSED or by_hand)
        codes.append(code if measured else ("not measured red", code,
                                            said[-300:]))
    _harness.git(fx["root"], "add", "-A")
    _harness.git(fx["root"], "commit", "-q", "-m", "measured again")
    after, again, _w = _bb_run(rel, spec, fx)
    why = ""
    if "could not be read" in again or "`failed`" not in again:
        why = again[-400:]
    return commands, codes, after, why


def _bb_panel(fx):
    """The panel's state payload over `fx`, in place of its server."""
    import _panel_state
    lines = []
    try:
        lines.append(json.dumps(_panel_state.build_state(fx["root"]),
                                default=str))
    except Exception as exc:                                   # noqa: BLE001
        lines.append("Traceback: %s: %s" % (type(exc).__name__, exc))
    return lines


def _black_box_cases(check):
    """(bb) A subject's newest red held only as its plan record, an older
    green of the same content in the ledger: every command that reads runs,
    over that record malformed, never gives the older run as the subject's
    answer, never a passing word for it, never writes the older run over the
    red, and never exits in success where the same plan with the record
    well-formed - the oracle - does not."""
    tmp = _harness.fixture_root("audit-evidence-black-box-")
    started = time.monotonic()
    try:
        derived, readers = _bb_derived()
        unplaced = [p for p in derived if p not in _BB_ENTRIES]
        stale = sorted(p for p in _BB_ENTRIES if p not in derived)
        check("bb-table EVERY COMMAND THAT READS RUNS HAS A ROW, AND EVERY ROW "
              "A COMMAND: %d derived over %d reader(s); with no row: %r; a row "
              "naming no command that reads runs: %r"
              % (len(derived), len(readers), unplaced, stale),
              len(derived) > 0 and ("_evidence_io", "read_rows") in readers
              and unplaced == [] and stale == [])
        sites = _bb_drive_sites()
        check("bb-drive-sites EVERY SITE OF THE DRIVE READING RECORDED RUNS "
              "HAS ITS REASON, AND EVERY REASON A SITE: %d site(s); with no "
              "reason %r; a reason naming no site %r"
              % (len(sites), [s for s in sites if s not in _BB_DRIVE_SITES],
                 sorted(s for s in _BB_DRIVE_SITES if s not in sites)),
              len(sites) > 0 and sites == sorted(_BB_DRIVE_SITES))
        builds = {}
        for variant, phase, task in _BB_VARIANTS:
            for malformed in (None,) + _BB_SHAPES:
                builds[(variant, malformed)] = _bb_build(tmp, variant, phase,
                                                         task, malformed)
        shapes = dict((k, (fx["built"], bool(fx["green"]), bool(fx["red"])))
                      for k, fx in builds.items())
        check("bb-fixture THE FIXTURE HOLDS WHAT IT SAYS: in each variant a "
              "green then a red were recorded, the green's run id and the "
              "red's both read off the runner: %r" % (shapes,),
              all(fx["green"] and fx["red"] and fx["green"] != fx["red"]
                  and fx["built"][-1][0] != 0 and fx["built"][-2][0] == 0
                  for fx in builds.values()))
        runs = dict((rel, spec) for rel, spec in sorted(_BB_ENTRIES.items())
                    if not isinstance(spec, str))
        n = [0]
        for rel, spec in sorted(runs.items()):
            wrong, seen = [], []
            for variant, _phase, _task in _BB_VARIANTS:
                if variant not in spec[1]:
                    continue
                got = {}
                for malformed in (None,) + _BB_SHAPES:
                    n[0] += 1
                    fx = _bb_copy(builds[(variant, malformed)], tmp,
                                  "run%d" % (n[0],))
                    got[malformed] = _bb_run(rel, spec, fx)
                said = []
                for shape in _BB_SHAPES:
                    said.extend("%s: %s" % (shape, w) for w in _bb_wrong(
                        rel, spec, builds[(variant, shape)], got[None],
                        got[shape]))
                    if "Traceback" in got[shape][1]:
                        said.append("%s: %s" % (shape, got[shape][1][-400:]))
                # A row whose oracle answers with the subject's newest run
                # must name that run there, or the row asks nothing.
                if rel in _BB_ORACLE_NAMES_RED and builds[(
                        variant, None)]["red"] not in got[None][1]:
                    said.append("the oracle's answer does not name its red "
                                "%s, so the row asks nothing: %r"
                                % (builds[(variant, None)]["red"],
                                   got[None][1][-300:]))
                seen.append((variant, got[None][0],
                             tuple(got[s][0] for s in _BB_SHAPES)))
                if said:
                    wrong.append((variant, said))
            name = os.path.basename(rel)[:-3]
            check("bb-%s RED-FIRST: %s, over a subject whose newest red is a "
                  "record that will not read - %s - never gives the older "
                  "green as its answer, never a passing word for it, writes "
                  "nothing putting the green over the red, and exits in "
                  "success only where the oracle does - exits (variant, "
                  "oracle, each shape) %r; wrong: %r"
                  % (name, rel, ", ".join(_BB_SHAPES), seen, wrong),
                  seen and wrong == [])
        remedy = []
        for variant, _phase, task in _BB_VARIANTS:
            rel = ("plugins/audit/scripts/manifest/audit-task.py" if task
                   else "plugins/audit/scripts/git/close-phase.py")
            for shape in _BB_SHAPES:
                n[0] += 1
                remedy.append(("%s/%s" % (variant, shape),) + _bb_remedy(
                    rel, _BB_ENTRIES[rel], _bb_copy(
                        builds[(variant, shape)], tmp,
                        "remedy%d" % (n[0],))))
        check("bb-remedy THE ADVICE MEASURES: over each variant malformed, the "
              "refusal's own steps, taken exactly as printed, measure the "
              "subject - a red, never a repeat, but where the advice first "
              "deletes a key's second copy by hand and the record's own red "
              "then reads, the door's refusal of a file writing a key twice "
              "naming that hand step alone - and the same refusal asked "
              "again stands on that red, naming no unreadable record: "
              "(variant, commands, their exits, exit after, why) %r"
              % (remedy,),
              all(cmds and all(c == 1 for c in codes) and after != 0
                  and why == "" for _v, cmds, codes, after, why in remedy))
        panel = []
        for (variant, shape), fx in sorted(builds.items(),
                                           key=lambda kv: str(kv[0])):
            if shape is None:
                continue
            text = _bb_answer("\n".join(_bb_panel(fx)))
            if fx["green"] in text or "Traceback" in text:
                panel.append((variant, shape, text[-300:]))
        check("bb-panel-state RED-FIRST: the panel's state payload, over each "
              "variant malformed, never names the older green and never "
              "raises: wrong %r" % (panel,), panel == [])
        took = time.monotonic() - started
        check("bb-cost THE BLOCK IS BOUNDED: %d command run(s) over %d "
              "fixture(s) in %.1fs, under the %ds bound"
              % (n[0], len(builds), took, _BB_BOUND), took < _BB_BOUND)
    except Exception as exc:                                   # noqa: BLE001
        check("bb0 the black-box block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# The block's wall-clock bound, set off two measured runs on a quiet machine
# with room for a loaded one; the case prints the time each run took.
_BB_BOUND = 600


def _never_shared_cases(check):
    """(ns) A share cannot rewrite a verdict: a shared path whose top key the
    writer never shares, and a shared path the record also holds, are each a
    problem of the record - one table, read by the writer and by the check.
    A shared tested state is a share the writer itself makes, part repeat
    and whole alike, so it stays legal; what it can and cannot make bind is
    `ns3`'s."""
    import _verdict_binding as VB
    doc = _json_schema.load_document(_RK_SCHEMA)
    table = tuple(getattr(M, "NEVER_SHARED_KEYS", ()))
    tmp = _harness.fixture_root("audit-evidence-shared-")
    try:
        root = os.path.join(tmp, "ns")
        os.makedirs(os.path.join(root, "src"))
        with io.open(os.path.join(root, "src", "a.py"), "w",
                     encoding="utf-8") as fh:
            fh.write("a = 1\n")
        rows = _rk_rows(root)

        def bind(record):
            bodies = [(_NU_FILE, {"id": "P1", "tasks": [
                {"id": "P1.1", M.RECORD_KEY: record}]})]
            return VB.binding(
                root, {"taskId": "P1.1", "phaseId": "P1"}, ["sweep"], "task",
                ["src/a.py"], os.path.join(root, "docs", "audit",
                                           "audit-plan.json"),
                "record it", "no gate", texts=[],
                records=M.records_of_bodies(bodies, doc),
                records_lost=M.unreadable_records(bodies, doc))
        whole = M.run_record(rows["whole"], source=rows["source"])
        part = M.run_record(rows["part"], source=rows["source"])
        check("ns0 ALLOW: the records the writer composes - a whole repeat and "
              "a part repeat sharing what it shares - read, and the whole one "
              "shares something: %r / %r"
              % (M.record_problem(whole, doc), M.record_problem(part, doc)),
              M.record_problem(whole, doc) is None
              and M.record_problem(part, doc) is None
              and len(whole.get(M.SHARED_KEY) or []) > 0)
        missed, bound = [], []
        for key in table:
            planted = dict(whole, **{M.SHARED_KEY: list(
                whole.get(M.SHARED_KEY) or []) + ([key] if key != "steps"
                                                  else ["steps.0"])})
            found = M.record_problem(planted, doc)
            if found is None or not str(found.get("field")).startswith(
                    "%s.%s" % (M.RECORD_KEY, M.SHARED_KEY)):
                missed.append((key, found))
            answer = bind(planted)
            if answer.get("state") == "bound" \
                    or answer.get("arm") != VB.ARM_UNREADABLE \
                    or M.SHARED_KEY not in str(answer.get("sentence")):
                bound.append((key, answer.get("state"), answer.get("arm")))
        plain = bind(whole)
        check("ns1 RED-FIRST: EVERY KEY THE WRITER NEVER SHARES, named in a "
              "record's share, makes the record unreadable at "
              "`lastRun.sharedWithRepeated`, and through the binding it refuses "
              "as unreadable naming the share, never binding - while the "
              "writer's own record is not refused as unreadable: table=%r "
              "missed=%r bound=%r plain=%r"
              % (table, missed, bound, (plain.get("arm"),
                                        str(plain.get("sentence"))[:160])),
              len(table) >= 10 and missed == [] and bound == []
              and all(k in table for k in ("runId", "at", "status"))
              and plain.get("arm") != VB.ARM_UNREADABLE)
        held = dict(whole, **{M.SHARED_KEY: list(whole.get(M.SHARED_KEY) or [])
                              + [M.GATE_REACH_KEY]})
        held[M.GATE_REACH_KEY] = {"unreached": ["src/hand.py"]}
        steps_too = dict(whole, steps=[{"name": "sweep", "exit": 0}])
        problems = [M.record_problem(held, doc),
                    M.record_problem(steps_too, doc)]
        check("ns2 A SHARED PATH THE RECORD ALSO HOLDS is a problem of the "
              "record - a reach reading written beside its share, and `steps` "
              "kept beside the `steps` share, the both-arms shape, whose "
              "sentence names `steps` and the share as what to repair: %r"
              % (problems,),
              all(p is not None for p in problems)
              and str(problems[0].get("field")).startswith(
                  "%s.%s" % (M.RECORD_KEY, M.SHARED_KEY))
              and "steps" in str(problems[1].get("why"))
              and M.SHARED_KEY in str(problems[1].get("why"))
              and "more than one" not in str(problems[1].get("why")))
        # A SHARED TESTED STATE, which the writer makes whenever a repeat's
        # equals its source's: the record then reads the carried run's state,
        # and the binding checks THAT against the work.
        here = _tree_stamp.scope_digest(root, ["src/a.py"])[0]
        gate = M.gate_digest(["sweep"], None)
        step = {"name": "sweep", "exit": 0, "ran": 3, "measured": "measured",
                "durationMs": 10}

        def ns_row(run_id, ts, digest, **extra):
            return dict(_lr_row(run_id, ts, steps=[dict(step)],
                                status="passed"), failed=[],
                        gateDigest=gate, testedState={"head": "abc",
                                                      "scopeDigest": digest},
                        **extra)
        src_ts = "2026-11-18T10:00:00Z"

        def ns_part(digest):
            return ns_row("NS-PART", "2026-11-18T10:05:00Z", digest, **{
                M.VERDICT_SOURCE: M.PART_REUSED,
                "reusedFrom": {"runId": "NS-SRC", "ts": src_ts,
                               "status": "passed"},
                "steps": [dict(step, reusedFrom={"runId": "NS-SRC",
                                                 "ts": src_ts})]})
        writers = {}
        for label, digest in (("these bytes", here),
                              ("other bytes", "sha256:other")):
            record = M.run_record(ns_part(digest), source=ns_row(
                "NS-SRC", src_ts, digest))
            writers[label] = (record, bind(record))
        own_other = M.run_record(ns_part("sha256:other"),
                                 source=ns_row("NS-SRC", src_ts, here))
        planted = dict(own_other, **{M.SHARED_KEY: list(
            own_other.get(M.SHARED_KEY) or []) + ["testedState"]})
        planted.pop("testedState", None)
        typed = dict(own_other, testedState={"head": "abc",
                                             "scopeDigest": here})
        said = dict((k, (v[1].get("state"), v[1].get("arm"),
                         "testedState" in (v[0].get(M.SHARED_KEY) or [])))
                    for k, v in writers.items())
        said.update({"own other": bind(own_other).get("state"),
                     "planted": bind(planted).get("state"),
                     "typed": bind(typed).get("state")})
        check("ns3 A SHARED TESTED STATE, which the writer itself makes, reads "
              "the carried run's state and the binding checks that: carried "
              "from a run of these bytes it binds, from a run of other bytes it "
              "is refused; a part repeat of other bytes holds its own state and "
              "is refused; and a share planted by hand onto it binds exactly as "
              "the same state written into the field by hand does - the share "
              "is no wider than the field it stands for: %r" % (said,),
              said["these bytes"] == ("bound", None, True)
              and said["other bytes"][0] == "refused" and said["other bytes"][2]
              and "testedState" not in (own_other.get(M.SHARED_KEY) or [])
              and said["own other"] == "refused"
              and M.record_problem(planted, doc) is None
              and said["planted"] == said["typed"] == "bound")
        # The writer over a record whose every field - the table's included -
        # equals the carried run's, each a subtree worth sharing.
        same = dict((key, {"same": ["x" * 40]}) for key in table
                    if key != M.REPEATED_RUN_KEY)
        same.update({"muted": {"same": ["y" * 40]}})
        written = M.shared_with_repeated(dict(same, **{
            M.REPEATED_RUN_KEY: dict(same)}))
        shared_tops = set(str(p).split(".")[0] for p in
                          written.get(M.SHARED_KEY) or [])
        check("ns4 ...AND THE WRITER READS THE SAME TABLE: over a record whose "
              "every field equals the carried run's, it shares a field the "
              "table does not name and none the table does: %r"
              % (sorted(shared_tops),),
              len(table) >= 10 and shared_tops == set(["muted"]))
    except Exception as exc:                                   # noqa: BLE001
        check("ns0b the shared-path block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- the release guard reads the plan's structure or refuses ------------------
_GS_INDEX = "docs/audit/audit-plan.json"
_GS_VALUES = (("object", {}), ("array", []), ("string", "x"), ("number", 5),
              ("boolean", True), ("null", None))


def _gs_def(doc, node):
    while isinstance(node, dict) and "$ref" in node:
        node = doc["$defs"][node["$ref"].split("/")[-1]]
    return node


def _gs_containers(doc):
    """`[(file, path, admitted type)]` - every container the guard reads to
    decide, its type read off the published schema. WHICH containers is the
    guard's reading (the plan, its phases and their tasks, its bugs); what
    each admits is the schema's. A sharded plan's tasks sit in the shard."""
    props = doc["properties"]
    phases, bugs = props["phases"], props["bugs"]
    phase = _gs_def(doc, phases["items"])
    tasks = phase["properties"]["tasks"]
    return [(_GS_INDEX, "meta", _gs_def(doc, props["meta"])["type"]),
            (_GS_INDEX, "phases", phases["type"]),
            (_GS_INDEX, "phases[0]", phase["type"]),
            (_NU_FILE, "tasks", tasks["type"]),
            (_NU_FILE, "tasks[0]", _gs_def(doc, tasks["items"])["type"]),
            (_GS_INDEX, "bugs", bugs["type"]),
            (_GS_INDEX, "bugs[0]", _gs_def(doc, bugs["items"])["type"])]


def _gs_plant(root, rel, path, value):
    """`value` at `path` (one key, or one key's first entry) of the plan file
    `rel` under `root`."""
    full = os.path.join(root, rel)
    with io.open(full, encoding="utf-8") as fh:
        body = json.load(fh)
    key, _sep, first = path.partition("[")
    if first:
        body[key] = (body.get(key) or [None])
        body[key] = [value] + body[key][1:]
    else:
        body[key] = value
    with io.open(full, "w", encoding="utf-8") as fh:
        json.dump(body, fh)


def _gs_guard():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gs_guard", _UG_HOOK)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


def _guard_structure_cases(check):
    """(gs) The release guard reads the plan's STRUCTURE or refuses: each
    container it reads, holding each JSON type its schema does not admit; a
    full gate the plugin's own reader would not take; a phase recording a
    merge head with no usable merge moment; a key written twice - each a deny
    naming the file and the place. A well-formed plan, one naming no full
    gate, one with no bugs and no merged phase, and the committed example and
    the demo starter, are read without one. And a deny that can be written
    nowhere still exits 2."""
    tmp = _harness.fixture_root("audit-evidence-guard-shape-")
    try:
        doc = _json_schema.load_document(_RK_SCHEMA)
        root, mpath, shards = _ug_project(tmp, "gs")
        texts = {}
        for rel in (_GS_INDEX, _NU_FILE):
            with io.open(os.path.join(root, rel), encoding="utf-8") as fh:
                texts[rel] = fh.read()

        def restore():
            for rel, text in texts.items():
                with io.open(os.path.join(root, rel), "w",
                             encoding="utf-8") as fh:
                    fh.write(text)

        def deny():
            code, reason, out, err = _ug_run(root, _ug_payload(root))
            return code, reason, (reason or out)[-260:], err[-200:]

        code, reason, _s, err = deny()
        check("gs1 ALLOW: the well-formed plan - a full gate, no bug, no merged "
              "phase - lets the tag command through: %r" % ((code, reason, err),),
              code == 0 and reason is None)
        containers = _gs_containers(doc)
        shapes, missed = 0, []
        for rel, path, admitted in containers:
            for kind, value in _GS_VALUES:
                if kind == admitted:
                    continue
                shapes += 1
                restore()
                _gs_plant(root, rel, path, value)
                code, reason, said, err = deny()
                if code != 0 or reason is None or rel not in reason \
                        or ("`%s` is %s" % (path, kind)) not in reason \
                        or "Traceback" in err:
                    missed.append((rel, path, kind, code, said, err))
        check("gs2 RED-FIRST: EVERY CONTAINER THE GUARD READS, holding every "
              "JSON type its schema does not admit, is a deny naming the file "
              "and the place - %d container(s), %d shape(s); not denied as "
              "said: %r" % (len(containers), shapes, missed[:3]),
              [a for _r, _p, a in containers] == [
                  "object", "array", "object", "array", "object", "array",
                  "object"]
              and shapes == 35 and missed == [])
        full = _gs_def(doc, doc["properties"]["meta"])["properties"]["fullGate"]
        gate_shapes = [(k, v) for k, v in _GS_VALUES if k != full["type"]]
        gate_shapes += [("an entry that is " + k, [v]) for k, v in _GS_VALUES
                        if k != full["items"]["type"]]
        gate_shapes += [("a blank entry", [""]), ("a spaces entry", ["   "])]
        gate_missed = []
        for label, value in gate_shapes:
            restore()
            with io.open(mpath, encoding="utf-8") as fh:
                index = json.load(fh)
            index["meta"]["fullGate"] = value
            with io.open(mpath, "w", encoding="utf-8") as fh:
                json.dump(index, fh)
            code, reason, said, err = deny()
            if code != 0 or reason is None or "meta.fullGate" not in reason \
                    or _GS_INDEX not in reason:
                gate_missed.append((label, code, said))
        check("gs3 RED-FIRST: A FULL GATE THE PLUGIN'S OWN READER WOULD NOT "
              "TAKE - not a list, an entry not a string, a blank entry - is a "
              "deny naming `meta.fullGate`, never read as no third place: "
              "%d shape(s); %r" % (len(gate_shapes), gate_missed),
              len(gate_shapes) == 12 and gate_missed == [])
        merge_missed = []
        for label, moment in (("absent", "-"), ("null", None), ("empty", ""),
                              ("not a moment", "soon"), ("a number", 5)):
            restore()
            with io.open(shards["P1"], encoding="utf-8") as fh:
                body = json.load(fh)
            body["mergedHead"] = "abc1234"
            if moment != "-":
                body["mergedAt"] = moment
            _ug_write_shard(shards, json.dumps(body))
            code, reason, said, err = deny()
            if code != 0 or reason is None or "P1" not in reason \
                    or "mergedAt" not in reason or "Traceback" in err:
                merge_missed.append((label, code, said))
        check("gs4 RED-FIRST: A PHASE RECORDING A MERGE HEAD WITH NO USABLE "
              "MERGE MOMENT - absent, null, empty, not a moment, a number - "
              "reads as unknown, never as unmerged: %r" % (merge_missed,),
              merge_missed == [])
        dup_missed = []
        for rel, key, old, new in (
                (_GS_INDEX, "bugs", '{', '{"bugs": [], '),
                (_NU_FILE, "id", '{"id": "P1"', '{"id": "P0", "id": "P1"')):
            restore()
            text = texts[rel].replace(old, new, 1)
            with io.open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
            code, reason, said, err = deny()
            if text == texts[rel] or code != 0 or reason is None \
                    or rel not in reason or ("`%s`" % (key,)) not in reason \
                    or "more than once" not in reason:
                dup_missed.append((rel, key, code, said))
        check("gs5 RED-FIRST: A KEY WRITTEN TWICE IN ONE OBJECT - in the index "
              "and in a shard - is a deny naming the file and the key, since "
              "which value the plan carries is not established: %r"
              % (dup_missed,), dup_missed == [])
        # ...AND INSIDE A RECORD: the guard refuses such a plan for itself,
        # whatever the plan's other readers make of the last copy.
        restore()
        ri_put_record(shards["P1"], "P1.1", dict(_ur_base(), status="failed"))
        with io.open(shards["P1"], encoding="utf-8") as fh:
            held = fh.read()
        twice = held.replace('"status": "failed"',
                             '"status": "failed", "status": "passed"', 1)
        with io.open(shards["P1"], "w", encoding="utf-8") as fh:
            fh.write(twice)
        code, reason, said, err = deny()
        check("gs9 RED-FIRST: a key written twice INSIDE A RUN RECORD is the "
              "guard's own deny of the plan, naming the shard and the key: %r"
              % ((code, said, err),),
              twice != held and code == 0 and reason is not None
              and _NU_FILE in reason and "`status`" in reason
              and "more than once" in reason)
        # A SHARD THAT WILL NOT READ is named by the shard, in the guard's
        # deny and in the bypass's message alike - not by the index.
        restore()
        _ug_write_shard(shards, "{not json")
        code, reason, said, err = deny()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gs_arm_release_bypass", os.path.join(
                os.path.dirname(_UG_HOOK), "arm-release-bypass.py"))
        arm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(arm)
        lists = arm.read_lists(root)
        told = arm.message(lists[0], lists[1], True)
        check("gs10 RED-FIRST: a shard that will not parse is named BY THE "
              "SHARD - in the guard's deny and in the bypass's message - "
              "never by the index pointing at it: deny %r; message %r"
              % ((code, said), told[:300]),
              code == 0 and reason is not None and _NU_FILE in reason
              and "could not be read as JSON" in reason
              and _NU_FILE in told and "could not be read as JSON" in told)
        # A SHARD THAT IS NOT THERE is said as missing, never as unparsed.
        restore()
        os.remove(shards["P1"])
        code, reason, said, err = deny()
        check("gs11 RED-FIRST: a shard the index names that does not exist is "
              "named by the shard and said as missing, never as JSON that "
              "would not parse: %r" % ((code, said),),
              code == 0 and reason is not None and _NU_FILE in reason
              and "does not exist" in reason
              and "could not be read as JSON" not in reason)
        # ALLOW: no third place at all - and then a recorded head without a
        # moment is asked nothing, as no merged phase is - and an empty one.
        allowed = []
        for label, gate in (("no fullGate", None), ("an empty fullGate", [])):
            restore()
            with io.open(mpath, encoding="utf-8") as fh:
                index = json.load(fh)
            if gate is None:
                index["meta"].pop("fullGate")
            else:
                index["meta"]["fullGate"] = gate
            with io.open(mpath, "w", encoding="utf-8") as fh:
                json.dump(index, fh)
            with io.open(shards["P1"], encoding="utf-8") as fh:
                body = json.load(fh)
            body["mergedHead"] = "abc1234"
            _ug_write_shard(shards, json.dumps(body))
            code, reason, _s, err = deny()
            allowed.append((label, code, reason))
        check("gs6 ALLOW: a plan naming no third place - no fullGate, or an "
              "empty one - is let through, its merged-head-only phase asked "
              "nothing: %r" % (allowed,),
              all(code == 0 and reason is None for _l, code, reason in allowed))
        # The committed example and the demo starter, through the guard's own
        # structural reader, in-process and read-only.
        restore()
        guard = _gs_guard()
        reader = getattr(guard, "plan_structure_problem", None)
        acme = os.path.join(tmp, "acme")
        src = os.path.join(_output.REPO_ROOT, "examples", "acme-store")
        os.makedirs(os.path.join(acme, "docs", "audit"))
        shutil.copy(os.path.join(src, "audit-plan.json"),
                    os.path.join(acme, "docs", "audit", "audit-plan.json"))
        shutil.copytree(os.path.join(src, "phases"),
                        os.path.join(acme, "docs", "audit", "phases"))
        demo = os.path.join(tmp, "demo")
        made = subprocess.run(
            [sys.executable, os.path.join(_output.REPO_ROOT, "tools", "demo",
                                          "gen-demo-manifest.py"),
             os.path.join(demo, "docs", "audit"), "--phases", "4",
             "--tasks", "3"], capture_output=True, text=True, timeout=120)
        readings = [(name, reader(project) if reader else "no reader")
                    for name, project in (("fixture", root), ("example", acme),
                                          ("demo starter", demo))]
        _gs_plant(root, _GS_INDEX, "phases", "x")
        planted = reader(root) if reader else None
        restore()
        check("gs7 ALLOW: the guard's structural reader takes the fixture, the "
              "committed example and the demo starter as they are, and names "
              "the planted shape: %r / %r / %r"
              % (readings, planted, made.returncode),
              made.returncode == 0
              and all(said is None for _n, said in readings)
              and planted is not None and "`phases` is string" in planted)
        # A DENY WRITTEN NOWHERE: stdout closed when the process starts (and,
        # beside it, the interpreter's own None stream), and then stderr too.
        ri_put_record(shards["P1"], "P1.1", dict(_ur_base(), steps=5))
        runner = ("import runpy, sys\nsys.argv = [sys.argv[1]]\n%s"
                  "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        closed = []
        for label, pre in (("stdout None", "sys.stdout = None\n"),
                           ("stdout and stderr None",
                            "sys.stdout = None\nsys.stderr = None\n")):
            code, _r, _o, err = _ug_run(
                root, _ug_payload(root),
                argv=[sys.executable, "-c", runner % (pre,), _UG_HOOK])
            closed.append((label, code, err))
        if os.name == "posix":
            code, _r, _o, err = _ug_run(root, _ug_payload(root), argv=[
                sys.executable, "-c",
                "import os, sys\nos.close(1)\n"
                "os.execv(sys.executable, [sys.executable, sys.argv[1]])\n",
                _UG_HOOK])
            closed.append(("fd 1 closed at exec", code, err))
        check("gs8 RED-FIRST: A DENY THAT CAN BE WRITTEN NOWHERE still exits 2 - "
              "stdout closed when the process starts, stdout None, and stdout "
              "and stderr both None - and says it on stderr when stderr "
              "takes it: %r" % ([(lab, c, e[:120]) for lab, c, e in closed],),
              len(closed) >= 2
              and all(code == 2 for _l, code, _e in closed)
              and all("[guard-release]" in err for label, _c, err in closed
                      if "stderr" not in label))
    except Exception as exc:                                   # noqa: BLE001
        check("gs0 the guard-structure block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


# --- a keep-both merge, then any verb ---------------------------------------------
# The shape a merge resolved by keeping both sides leaves: a task holding its
# newest red record, and after it a second copy of the key holding an older
# green. JSON's reader takes the last copy, so a verb that read the shard and
# saved it back would leave the green alone, and from then the lookup, the
# gate's reuse and `done` would answer from it. Every verb's save goes through
# `_manifest_io`'s door, which refuses the file; the ledger is read on and off.
def _kv_keep_both(tmp, name, ledger):
    """`(root, mpath, spath, ids, text)` - a sharded git project whose task
    P1.1 writes `lastRun` twice, the newer red first and an older green last;
    with `ledger`, the green's row is in the evidence ledger as well."""
    root, mpath, spath = _lr_project(tmp, name)
    ids = {"taskId": "P1.1", "phaseId": "P1"}
    green, red = _ho_rows("task")
    red = dict(red, scope="task", gateSource="task")
    M.write_record(root, mpath, "task", ids, M.run_record(red))
    if ledger:
        M.append_row(root, green)
    body = _lr_shard(spath)
    held = json.dumps(body["tasks"][0][M.RECORD_KEY])
    text = json.dumps(body)
    twice = text.replace('"%s": %s' % (M.RECORD_KEY, held),
                         '"%s": %s, "%s": %s' % (
                             M.RECORD_KEY, held, M.RECORD_KEY,
                             json.dumps(M.run_record(green))), 1)
    assert twice != text
    with io.open(spath, "w", encoding="utf-8") as fh:
        fh.write(twice)
    return root, mpath, spath, ids, twice


def _kv_verbs(root, mpath):
    """`[(label, script, argv)]` - verbs that save the plan, each aimed at the
    task the keep-both shape sits on."""
    return [
        ("note", "audit-task.py", ["note", "P1.1", "--text", "unrelated",
                                   "--project-dir", root]),
        ("block", "audit-task.py", ["block", "P1.1", "--reason", "waiting",
                                    "--project-dir", root]),
        ("done", "audit-task.py", ["done", "P1.1", "--no-change", "--reason",
                                   "nothing to change", "--project-dir",
                                   root]),
        ("the gate's record", "run-test-gate.py", [mpath, "P1", "--task",
                                                   "P1.1", "--record"]),
    ]


def _keep_both_verb_cases(check):
    """(kv) After a keep-both merge shape, no verb's save leaves the older
    copy for the gate to reuse, ledger on and off."""
    statuses = frozenset(("passed", "failed"))
    tmp = _harness.fixture_root("audit-evidence-keep-both-")
    try:
        env = dict((k, v) for k, v in os.environ.items()
                   if k not in ("CLAUDE_PROJECT_DIR", _locks.TOKEN_ENV))
        seen, after = [], []
        for ledger in (False, True):
            root, mpath, spath, ids, twice = _kv_keep_both(
                tmp, "kv-%s" % ("on" if ledger else "off"), ledger)
            for label, script, argv in _kv_verbs(root, mpath):
                code, out, err = _harness.run_script(
                    _loader.script_path(script), argv, root, env=env)
                said = (out + err).decode("utf-8", "replace").replace(
                    os.sep, "/")
                with io.open(spath, encoding="utf-8") as fh:
                    held = fh.read()
                seen.append((ledger, label, code != 0, held == twice,
                             "phases/P1.json" in said
                             and "/tasks/0/%s" % (M.RECORD_KEY,) in said
                             and "by hand" in said, said[-200:]))
            read = M.read_rows(root, manifest_path=mpath)
            reuse = M.reusable_run(read["rows"], "task", ids, "sha256:key",
                                   statuses)
            after.append((ledger, [r.get("runId") for r in read["rows"]
                                   if r.get("taskId") == "P1.1"
                                   and r.get("status") == "passed"],
                          reuse and reuse.get("runId"),
                          [(e.get("subject"), e.get("rule"))
                           for e in read.get("unreadableRecords") or []]))
        wrong = [s for s in seen if not (s[2] and s[3] and s[4])]
        check("kv1 RED-FIRST: after a keep-both merge leaves task P1.1 "
              "writing `lastRun` twice (the newer red first, an older green "
              "last), every verb that saves the plan - note, block, done, the "
              "gate's own record - refuses, the shard byte for byte as it "
              "was, naming the shard, the key and the hand step, ledger off "
              "and on: wrong %r of %d" % (wrong, len(seen)),
              len(seen) == 8 and not wrong)
        check("kv2 RED-FIRST: ...so the older copy is never left for the gate "
              "to reuse: no passing run of P1.1 is read, the reuse lookup "
              "finds none and the record is named unreadable as a key "
              "written twice, ledger off and on: %r" % (after,),
              [a[0] for a in after] == [False, True]
              and all(not a[1] and a[2] is None
                      and a[3] == [("P1.1", "duplicate-key")] for a in after))
    except Exception as exc:                                   # noqa: BLE001
        check("kv0 the keep-both block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


def _container_twice_cases(check):
    """(kv) A key written twice on an object that holds records below it - a
    phase's `tasks`, the index's `phases` - makes every record under it
    unreadable at every read of runs, and the validator names it, both
    layouts."""
    tmp = _harness.fixture_root("audit-evidence-container-twice-")
    try:
        doc = M.record_schema()[0]
        green, red = _ho_rows("task")
        red = dict(red, scope="task", gateSource="task")
        red_text = json.dumps(M.run_record(red))
        green_text = json.dumps(M.run_record(green))
        # The phase's `tasks` written twice: the first copy holds the newer
        # red, the last the same task with an older green.
        phase_text = ('{"id": "P1", "title": "one", "status": "in_progress", '
                      '"testGate": [], "tasks": [{"id": "P1.1", "title": "t", '
                      '"status": "in_progress", "lastRun": %s}], "tasks": '
                      '[{"id": "P1.1", "title": "t", "status": "in_progress", '
                      '"lastRun": %s}]}' % (red_text, green_text))
        tip = [(s, i, (p or {}).get("rule")) for s, i, _r, p
               in M._plan_records(M.plan_json_text(phase_text), doc)]
        root, mpath, spath = _lr_project(tmp, "kv-tasks")
        with io.open(spath, "w", encoding="utf-8") as fh:
            fh.write(phase_text)
        read = M.read_rows(root, manifest_path=mpath)
        lost = [(e.get("subject"), e.get("rule"))
                for e in read.get("unreadableRecords") or []]
        passed = [r.get("runId") for r in read["rows"]
                  if r.get("status") == "passed"]
        val = _loader.load_script("validate-manifest.py", "kv_validate")
        code, said = _kv_validate(val, mpath)
        check("kv3 RED-FIRST: a phase writing `tasks` twice - the newer red "
              "in the first copy, an older green in the last - holds no "
              "readable task record: the shard's walk and the branch tip's "
              "parse both name P1.1's record unreadable and read no green, "
              "and the validator names the key: tip %r, walk %r, passed %r, "
              "validator %r" % (tip, lost, passed, (code, said[-200:])),
              tip == [("task", "P1.1", "duplicate-key")]
              and lost == [("P1.1", "duplicate-key")] and not passed
              and code == 1 and "/tasks" in said and "phases/P1.json" in said)
        # The one-file layout: the index's `phases` written twice, the first
        # copy holding the newer red and the last the same phase with an
        # older green.
        phase = ('{"id": "P1", "title": "one", "status": "in_progress", '
                 '"testGate": [], "tasks": [{"id": "P1.1", "title": "t", '
                 '"status": "in_progress", "lastRun": %s}]}')
        plan = ('{"meta": {"version": 2}, "phases": [%s], "phases": [%s]}'
                % (phase % (red_text,), phase % (green_text,)))
        one = os.path.join(tmp, "kv-one")
        os.makedirs(os.path.join(one, ".claude"))
        with io.open(os.path.join(one, ".claude", "audit.config.json"), "w",
                     encoding="utf-8") as fh:
            json.dump({"manifestPath": "audit-plan.json"}, fh)
        one_path = os.path.join(one, "audit-plan.json")
        with io.open(one_path, "w", encoding="utf-8") as fh:
            fh.write(plan)
        read_one = M.read_rows(one, manifest_path=one_path)
        lost_one = [(e.get("subject"), e.get("rule"))
                    for e in read_one.get("unreadableRecords") or []]
        code_one, said_one = _kv_validate(val, one_path)
        check("kv4 RED-FIRST: ...and an index writing `phases` twice in the "
              "one-file layout leaves no record under it readable, the "
              "validator naming `/phases`: walk %r, validator %r"
              % (lost_one, (code_one, said_one[-200:])),
              lost_one and all(rule == "duplicate-key"
                               for _s, rule in lost_one)
              and code_one == 1 and "/phases" in said_one)
        # The checker's own list (`reader_rule_problems`), asked of the same
        # two plans' walked bodies directly: the validator now stops at the
        # key before it asks, so only a direct call reaches it.
        listed = [sorted((e["subject"], e["rule"]) for e in
                         M.reader_rule_problems(M.plan_bodies(p, r)[0]))
                  for p, r in ((mpath, root), (one_path, one))]
        check("kv6 RED-FIRST: ...and the checker's list of records the reader "
              "refuses names P1.1's record under each - the phase's `tasks` "
              "written twice, the index's `phases` written twice - as a key "
              "written twice: %r" % (listed,),
              listed == [[("P1.1", "duplicate-key")]] * 2)
        # THE OVER-FIRE: a phase writing a key twice that holds no record -
        # its title - leaves its tasks' records readable.
        title_twice = M.plan_json_text(
            '{"id": "P1", "title": "one", "title": "uno", "tasks": [{"id": '
            '"P1.1", "title": "t", "lastRun": %s}]}' % (red_text,))
        over = [(s, i, (p or {}).get("rule")) for s, i, _r, p
                in M._plan_records(title_twice, doc)]
        check("kv5 THE OVER-FIRE: a phase writing its title twice leaves its "
              "task's record readable - only a key whose value holds records "
              "takes the records under it: %r" % (over,),
              over == [("task", "P1.1", None)])
    except Exception as exc:                                   # noqa: BLE001
        check("kv0b the container block ran to its end (%s: %s)"
              % (type(exc).__name__, exc), False)
    finally:
        _harness.remove_tree(tmp)


def _kv_validate(val, path):
    """`(exit code, what validate-manifest printed)` for the plan at `path`."""
    buf, real = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = val.main([path])
    finally:
        sys.stdout = real
    return code, buf.getvalue().replace(os.sep, "/")


def _types_namespace(**kw):
    import types
    return types.SimpleNamespace(**kw)


def _plan_door_cases(check):
    """(pd) `plan_unreadable_records` - the ONE read of the run records a plan
    holds that are not the record's shape - names the record `plan_unreadable`
    names, resolves its project the way every reader does, and when the read
    itself raises answers a whole-plan entry rather than an empty list."""
    tmp = _harness.fixture_root("audit-evidence-plan-door-")
    try:
        root, mpath, shard = _wh_project(tmp, "bad", "task")
        croot, cmpath, _c = _wh_project(tmp, "ok", "task", malformed=False)
        said = M.plan_unreadable_records(mpath)
        base = M.plan_unreadable(mpath, root)
        clean = M.plan_unreadable_records(cmpath, croot)
        check("pd1 the door answers `plan_unreadable`'s own entries for a plan "
              "holding a record that will not read - with the project handed "
              "or resolved from the manifest - and no entry for a plan whose "
              "records all read: %r" % ([e.get("subject")
                                         for e in said["unreadableRecords"]],),
              said == base == M.plan_unreadable_records(mpath, root)
              and [e["subject"] for e in said["unreadableRecords"]] == ["P1.1"]
              and clean["unreadableRecords"] == [])
        real = M.plan_unreadable

        def _no_walk(manifest_path, project=None):
            raise OSError("plan walk refused (fixture)")
        M.plan_unreadable = _no_walk
        try:
            failed = M.plan_unreadable_records(mpath, root)
        finally:
            M.plan_unreadable = real
        entries = failed["unreadableRecords"]
        check("pd2 RED-FIRST: when the read cannot walk the plan the door "
              "answers ONE whole-plan entry (scope `plan`) naming the cause - "
              "never an empty list, which every reader would take for 'all "
              "records readable' - and the read is the real one again once "
              "the fixture's refusal is lifted: %r" % (entries,),
              len(entries) == 1 and entries[0]["scope"] == "plan"
              and "plan walk refused (fixture)" in entries[0]["why"]
              and failed["unreadablePlanFiles"] == []
              and M.unreadable_records_sentence(entries)
              and M.plan_unreadable_records(mpath, root) == base)
    finally:
        _harness.remove_tree(tmp)


def _plan_readers_cases(check):
    """(pk) The two readers beside `records_of_bodies`: the run a record that
    will not read still names (`unreadable_record_runs`), and the runs a plan
    records counted off the plan alone (`plan_run_entries`)."""
    doc = _json_schema.load_document(_RK_SCHEMA)
    good = M.run_record(_nu_row("PK-GOOD", "2026-11-18T12:00:00Z", "passed"))
    bodies = [(_NU_FILE, {"id": "P1", "tasks": [
        {"id": "P1.1", M.RECORD_KEY: good},
        {"id": "P1.2", M.RECORD_KEY: dict(good, runId="PK-BAD", status=7)},
        {"id": "P1.3", M.RECORD_KEY: dict(
            (k, v) for k, v in good.items() if k != "runId")}]})]
    got = M.unreadable_record_runs(bodies, doc, plan="docs/audit/p.json")
    lost = M.unreadable_records(bodies, doc, plan="docs/audit/p.json")
    check("pk1 a record that is not the record's shape still names its run: "
          "the corrupt record gives its run id and the entry "
          "`unreadable_records` gives it, the record that reads gives none, "
          "and one naming no run gives None - never a made-up id: %r"
          % (got,),
          [(e.get("subject"), run) for e, run in got]
          == [("P1.2", "PK-BAD"), ("P1.3", None)]
          and [e for e, _run in got] == lost
          and [e["field"] for e, _r in got] == ["%s.status" % M.RECORD_KEY,
                                                "%s.runId" % M.RECORD_KEY])
    check("pk2 ALLOW: bodies whose records all read name no unreadable run: %r"
          % (M.unreadable_record_runs([(_NU_FILE, {"id": "P1", "tasks": [
              {"id": "P1.1", M.RECORD_KEY: good}]})], doc),),
          M.unreadable_record_runs([(_NU_FILE, {"id": "P1", "tasks": [
              {"id": "P1.1", M.RECORD_KEY: good}]})], doc) == [])

    tmp = _harness.fixture_root("audit-evidence-plan-runs-")
    try:
        # THE FIXTURE THAT TELLS THE READERS APART: the ledger repeats the
        # record's own run, so `read_rows` counts that run as the ledger's
        # and `records` reads none while the plan records one.
        root, mpath, _shard = _wh_project(tmp, "ok", "task", malformed=False)
        M.append_row(root, _wh_row(_WH_RED, "2026-11-18T12:00:00Z", "failed"))
        read = M.read_rows(root, manifest_path=mpath)
        ran = [row.get("runId") for row, _l in M.plan_run_entries(mpath, root)]
        check("pk3 the runs a plan records are counted off the plan alone: "
              "the record's run is one even when a ledger row repeats it, "
              "where `read_rows`' `records` counts only the runs no ledger row "
              "also holds: %r / records=%r" % (ran, read.get("records")),
              ran == [_WH_RED] and read.get("records") == 0)
        broot, bmpath, _s = _wh_project(tmp, "bad", "task")
        check("pk4 ...and a record that will not read is no run of the "
              "plan's: %r" % ([r.get("runId") for r, _l in
                               M.plan_run_entries(bmpath, broot)],),
              M.plan_run_entries(bmpath, broot) == [])
    finally:
        _harness.remove_tree(tmp)


# --- the upgrade: records replace rows, and the frozen rows read as before -------
def _bu_ledger(root, rows):
    """Write `rows` as the previous release left them - one chained file under
    the evidence directory - and return that directory."""
    evdir = M.evidence_dir(root)
    os.makedirs(evdir, exist_ok=True)
    name = "2026-11.previous-release.jsonl"
    with io.open(os.path.join(evdir, name), "w", encoding="utf-8",
                 newline="\n") as fh:
        for linked in M.chain_file(rows, name):
            fh.write(_journal_io.canonical(linked) + "\n")
    return evdir


def _bu_meta(mpath, change):
    with io.open(mpath, encoding="utf-8") as fh:
        body = json.load(fh)
    change(body["meta"])
    with io.open(mpath, "w", encoding="utf-8") as fh:
        json.dump(body, fh)


def _bu_run(run_id, ts, task="P1.1"):
    """A green run of `task` stamped `ts`, as the ledger row `row_for` builds."""
    return M.row_for("/nowhere", {"status": "passed", "durationMs": 5,
                                  "failed": [], "steps": [{"name": "sweep",
                                                           "exit": 0}]},
                     "task", {"taskId": task, "phaseId": "P1"},
                     {"runId": run_id, "ts": ts, "startedAt": ts})


def _bu_gate(mpath):
    """`(exit, the GATE lines)` of audit-status's gate over the two conditions
    a recorded run feeds - the exit and the lines that state the verdict."""
    proc = subprocess.run(
        [sys.executable, _loader.script_path("audit-status.py"), mpath,
         "--gate", "--fail-on", "failing-tests,no-test-evidence"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True)
    said = (proc.stdout + "\n" + proc.stderr).splitlines()
    return proc.returncode, [ln for ln in said if ln.startswith("GATE ")]


def _boundary_upgrade_cases(check):
    """(bu) Across the upgrade that stops the rows: the evidence boundary never
    moves later, records beside no key leave it not established rather than
    absent, a plan's first record and its stamp are one write, and a plan and
    ledger of the previous release answer the same - with the ledger there and
    with it deleted."""
    tmp = _harness.fixture_root("audit-evidence-upgrade-")
    try:
        t0, t2, t3, t5 = ("2026-11-01T08:00:00Z", "2026-11-02T08:00:00Z",
                          "2026-11-03T08:00:00Z", "2026-11-05T08:00:00Z")
        # --- a ledger row beside records that keep replacing each other ------
        root = os.path.join(tmp, "replaced")
        mpath, shards = ri_plan(root)
        _bu_ledger(root, [_bu_run("R0", t0)])
        ri_put_record(shards["P1"], "P1.1", M.run_record(_bu_run("R2", t2)))
        first = M.evidence_boundary(root, mpath)
        ri_put_record(shards["P1"], "P1.1", M.run_record(_bu_run("R3", t3)))
        second = M.evidence_boundary(root, mpath)
        check("bu1 THE BOUNDARY NEVER MOVES LATER AS RECORDS REPLACE EACH "
              "OTHER: a plan with no key, a frozen ledger row at %s and a "
              "record replaced by a newer one - the boundary is the frozen "
              "row's moment before and after the replacement: %r / %r"
              % (t0, first, second),
              first["at"] == second["at"] == t0
              and first["sources"] == second["sources"]
              == {"key": None, "ledger": t0})

        # --- a record alone dates nothing ----------------------------------
        bare = os.path.join(tmp, "record-only")
        bare_path, bare_shards = ri_plan(bare)
        ri_put_record(bare_shards["P1"], "P1.1",
                      M.run_record(_bu_run("R2", t2)))
        alone = M.evidence_boundary(bare, bare_path)
        check("bu2 RECORDS BESIDE NO KEY AND NO LEDGER LEAVE THE BOUNDARY NOT "
              "ESTABLISHED, never absent: a plan holding a record at %s and "
              "neither a key nor a ledger says recorded runs exist, lists the "
              "start as unknown, and bounds it at the record from above - an "
              "`at` of None would excuse every gap in the plan: %r"
              % (t2, alone),
              alone["at"] == t2
              and alone["sources"] == {"key": None, "ledger": None}
              and alone["basis"].startswith(
                  "recorded runs exist and the boundary is not established")
              and len(alone["unknown"]) == 1
              and "not established" in alone["unknown"][0]
              and t2 in alone["unknown"][0])

        # --- the previous release's plan and ledger -------------------------
        prev = os.path.join(tmp, "previous")
        pv_path, pv_shards = ri_plan(prev)
        rows = ri_rows(prev)
        _bu_ledger(prev, rows)
        latest = M.latest_by_subject(rows)
        with io.open(pv_shards["P1"], encoding="utf-8") as fh:
            body = json.load(fh)
        body["status"] = "done"
        body[M.POINTER_KEY] = M.pointer_for(latest[("phase", "P1")])
        for task in body["tasks"]:
            task["status"] = "done"
            if ("task", task["id"]) in latest:
                task[M.POINTER_KEY] = M.pointer_for(latest[("task", task["id"])])
        with io.open(pv_shards["P1"], "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        _bu_meta(pv_path, lambda meta: meta.update(
            {M.SINCE_KEY: M.since_from_rows(rows)}))
        read = M.read_rows(prev, manifest_path=pv_path)
        derived = dict(("%s %s" % k, M.pointer_for(v))
                       for k, v in M.latest_by_subject(read["rows"]).items())
        stored = dict([("phase P1", body[M.POINTER_KEY])] + [
            ("task %s" % (t["id"],), t[M.POINTER_KEY])
            for t in body["tasks"] if M.POINTER_KEY in t])
        verified = M.verify(prev)
        held_gate = _bu_gate(pv_path)
        held_boundary = M.evidence_boundary(prev, pv_path)
        _harness.remove_tree(M.evidence_dir(prev))
        gone_gate = _bu_gate(pv_path)
        gone_boundary = M.evidence_boundary(prev, pv_path)
        check("bu4 A PLAN AND LEDGER OF THE PREVIOUS RELEASE: every pointer "
              "the plan stores is the one the reader derives from the frozen "
              "rows, and the ledger verifies: %r / %r / %r"
              % (derived, stored, (verified.get("ok"), verified.get("rows"))),
              derived == stored and len(stored) == 4
              and verified.get("ok") is True
              and verified.get("rows") == len(rows)
              and read.get("records") == 0)
        check("bu5 ...AND WITH THE LEDGER DELETED the two conditions a recorded "
              "run feeds (failing-tests, no-test-evidence) answer as they did, "
              "on the boundary the plan's key states - the gate is not vacuous, "
              "the red task fails it both times: %r / %r / %r / %r"
              % (held_gate, gone_gate, held_boundary["at"],
                 gone_boundary["at"]),
              held_gate == gone_gate and held_gate[0] == 1
              and any("failing-tests" in ln for ln in held_gate[1])
              and held_boundary["at"] == gone_boundary["at"]
              == M.since_from_rows(rows)["at"])

        # --- the one-time stamp: the run, and the frozen rows ---------------
        stamped = os.path.join(tmp, "stamped")
        st_path, _st = ri_plan(stamped)
        st_ev = _bu_ledger(stamped, [_bu_run("R0", t0)])
        got = M.write_evidence_since(stamped, st_path, "P1",
                                     run=_bu_run("R5", t5))
        _harness.remove_tree(st_ev)
        after = M.evidence_boundary(stamped, st_path)
        fresh = os.path.join(tmp, "fresh")
        fr_path, fr_shards = ri_plan(fresh)
        ri_put_record(fr_shards["P1"], "P1.2",
                      M.run_record(_bu_run("R2", t2, task="P1.2")))
        new = M.write_evidence_since(fresh, fr_path, "P1",
                                     run=_bu_run("R5", t5))
        again = M.write_evidence_since(fresh, fr_path, "P1",
                                       run=_bu_run("R9", "2026-11-09T08:00:00Z"))
        check("bu3 THE STAMP IS THE EARLIEST RUN THE PLAN HOLDS AND THE RUN "
              "BEING RECORDED: on a plan with no key the first run of this "
              "release stamps the frozen row's moment (%s), not its own, so "
              "with the ledger then deleted the boundary still stands there; "
              "with no ledger a record standing at %s is earlier than the run "
              "(%s) and dates the stamp - only ever earlier - and a later run "
              "moves nothing: %r / %r / %r / %r"
              % (t0, t2, t5, got, after, new, again),
              got["written"] is True and got["at"] == t0
              and after["at"] == t0 and after["sources"]["key"] == t0
              and new["written"] is True and new["at"] == t2
              and again["written"] is False and again["at"] == t2)

        # --- the record and the stamp are one write ------------------------
        ids = {"taskId": "P1.1", "phaseId": "P1"}
        one = os.path.join(tmp, "one-write")
        one_path, one_shards = ri_plan(one)
        # A git root is what gives a project its lock scheme.
        _harness.git(None, "init", "-q", one, prefix=("git",))

        def _stamp(path):
            with io.open(path, encoding="utf-8") as fh:
                return M.since_block(json.load(fh))

        def _held(shard, task="P1.1"):
            with io.open(shard, encoding="utf-8") as fh:
                body = json.load(fh)
            holder = body if task is None else [
                t for t in body["tasks"] if t["id"] == task][0]
            return holder.get(M.RECORD_KEY)
        _locks.acquire(one, "index", session="bu-holder", out=lambda *_a: None)
        busy = M.write_record(one, one_path, "task", ids,
                              M.run_record(_bu_run("R2", t2)),
                              session_id="bu-writer", wait=0.2)
        _locks.release(one, "index", session="bu-holder", out=lambda *_a: None)
        busy_state = (_stamp(one_path), _held(one_shards["P1"]))
        wrote = M.write_record(one, one_path, "task", ids,
                               M.run_record(_bu_run("R2", t2)),
                               session_id="bu-writer")
        first_stamp = _stamp(one_path)
        later = M.write_record(one, one_path, "task", ids,
                               M.run_record(_bu_run("R5", t5)),
                               session_id="bu-writer")
        since_rows = [r for r in _journal_io.read_all(one)
                      if r.get("action") == M.ACTION_SINCE]
        check("bu6 A PLAN'S FIRST RECORD AND ITS BOUNDARY ARE ONE WRITE: with "
              "the index lock held elsewhere neither lands; with it free the "
              "record's write stamps `meta.evidenceSince` at the run's own "
              "moment (%s) in the same locked write - nothing is left for a "
              "second acquisition to lose - and a later record leaves the "
              "stamp exactly where it stands, journalled once: busy=%r/%r "
              "wrote=%r stamp=%r later=%r rows=%r"
              % (t2, busy.get("written"), busy_state, wrote.get("since"),
                 first_stamp, later.get("since"), len(since_rows)),
              busy["written"] is False and busy_state == (None, None)
              and wrote["written"] is True
              and wrote.get("since") == {"written": True, "at": t2,
                                         "reason": None}
              and (first_stamp or {}).get("at") == t2
              and (first_stamp or {}).get("runId") == "R2"
              and later["written"] is True
              and later.get("since") == {"written": False, "at": t2,
                                         "reason": None}
              and _stamp(one_path) == first_stamp
              and (_held(one_shards["P1"]) or {}).get("runId") == "R5"
              and len(since_rows) == 1)

        flat = os.path.join(tmp, "one-file")
        _project(flat, {"manifestPath": "docs/audit/audit-plan.json"})
        os.makedirs(os.path.join(flat, "docs", "audit"), exist_ok=True)
        flat_path = os.path.join(flat, "docs", "audit", "audit-plan.json")
        with io.open(flat_path, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 3}, "phases": [
                {"id": "P1", "title": "one", "status": "in_progress",
                 "testGate": ["sweep"], "tasks": [
                     {"id": "P1.1", "title": "t", "status": "in_progress"}]}]},
                fh)
        flat_wrote = M.write_record(flat, flat_path, "task", ids,
                                    M.run_record(_bu_run("R3", t3)))
        with io.open(flat_path, encoding="utf-8") as fh:
            flat_body = json.load(fh)
        check("bu7 ...AND IN THE ONE-FILE LAYOUT THEY ARE ONE SAVE: the index "
              "is the phase body, so the stamp and the record land in the same "
              "bytes: %r / %r"
              % (flat_wrote.get("since"), M.since_block(flat_body)),
              flat_wrote["written"] is True
              and (M.since_block(flat_body) or {}).get("at") == t3
              and flat_body["phases"][0]["tasks"][0].get(
                  M.RECORD_KEY, {}).get("runId") == "R3")

        # --- records older than every frozen source ------------------------
        late = os.path.join(tmp, "late-ledger")
        late_path, late_shards = ri_plan(late)
        _bu_ledger(late, [_bu_run("R5", t5)])
        ri_put_record(late_shards["P1"], "P1.1",
                      M.run_record(_bu_run("R2", t2)))
        late_b = M.evidence_boundary(late, late_path)
        check("bu8 A RECORD EARLIER THAN THE LEDGER'S EARLIEST ROW, BESIDE NO "
              "KEY, IS NOT DATED BY THE LEDGER: recording began no later than "
              "the record (%s), so the ledger's %s would excuse work the plan "
              "shows was recordable - the boundary is not established, and "
              "bounded at the record: %r" % (t2, t5, late_b),
              late_b["at"] == t2
              and late_b["sources"] == {"key": None, "ledger": t5}
              and len(late_b["unknown"]) == 1
              and "not established" in late_b["unknown"][0]
              and late_b["basis"].startswith(
                  "recorded runs exist and the boundary is not established"))

        # --- what the gate makes of it ----------------------------------------
        gated = os.path.join(tmp, "gated")
        g_path, g_shards = ri_plan(gated)
        ri_put_record(g_shards["P1"], "P1.1", M.run_record(_bu_run("R3", t3)))
        with io.open(g_shards["P1"], encoding="utf-8") as fh:
            g_body = json.load(fh)
        g_body["tasks"][1].update(status="done", completedAt=t2)
        with io.open(g_shards["P1"], "w", encoding="utf-8") as fh:
            json.dump(g_body, fh)
        unstamped = _bu_gate(g_path)
        _bu_meta(g_path, lambda meta: meta.update(
            {M.SINCE_KEY: {"at": t3, "basis": M.SINCE_BASIS}}))
        stamped_gate = _bu_gate(g_path)
        check("bu9 NO-TEST-EVIDENCE DOES NOT EXCUSE ON A BOUNDARY THAT IS NOT "
              "ESTABLISHED: a done task finished at %s with no run, beside a "
              "record at %s and no key, fails the gate - the excuse rests on "
              "an unknown start, which the gate refuses - while the same plan "
              "stating its boundary at %s passes it: %r / %r"
              % (t2, t3, t3, unstamped, stamped_gate),
              unstamped[0] == 1
              and any("no-test-evidence" in ln for ln in unstamped[1])
              and stamped_gate[0] == 0)

        # --- a save that fails between the two files ------------------------
        def _failing_save(path_part):
            real = M._mio.save_plan_json

            def save(path, body, *a, **k):
                if path_part in os.path.abspath(path):
                    raise OSError("save refused by the fixture")
                return real(path, body, *a, **k)
            M._mio.save_plan_json = save
            return lambda: setattr(M._mio, "save_plan_json", real)

        def _bytes(path):
            with io.open(path, "rb") as fh:
                return fh.read()

        def _since_rows(root):
            return [r for r in _journal_io.read_all(root)
                    if r.get("action") == M.ACTION_SINCE]
        sf = os.path.join(tmp, "shard-fails")
        sf_path, sf_shards = ri_plan(sf)
        sf_before = (_bytes(sf_path), _bytes(sf_shards["P1"]))
        put_back = _failing_save(os.path.join("phases", "P1.json"))
        try:
            sf_got = M.write_record(sf, sf_path, "task", ids,
                                    M.run_record(_bu_run("RS", t2)))
        finally:
            put_back()
        check("bu10 THE SHARD'S SAVE FAILING SAVES NO STAMP: the record is "
              "saved before the index, so a refused shard leaves the index "
              "byte for byte as it was - no `meta.evidenceSince` naming a run "
              "no file holds, and no journal row claiming one: %r"
              % ((sf_got.get("written"), sf_got.get("reason"),
                  sf_got.get("since"), _stamp(sf_path), len(_since_rows(sf))),),
              sf_got["written"] is False
              and "cannot write" in str(sf_got.get("reason"))
              and (_bytes(sf_path), _bytes(sf_shards["P1"])) == sf_before
              and _stamp(sf_path) is None
              and (sf_got.get("since") or {}).get("written") is False
              and _since_rows(sf) == [])
        xf = os.path.join(tmp, "index-fails")
        xf_path, xf_shards = ri_plan(xf)
        xf_index = _bytes(xf_path)
        put_back = _failing_save(os.path.join("audit", "audit-plan.json"))
        try:
            xf_got = M.write_record(xf, xf_path, "task", ids,
                                    M.run_record(_bu_run("RX", t2)))
        finally:
            put_back()
        xf_boundary = M.evidence_boundary(xf, xf_path)
        check("bu11 ...AND THE INDEX'S SAVE FAILING AFTER THE SHARD'S LEAVES THE "
              "RECORD ALONE, said as it is: the record stands, the answer says "
              "no boundary was written and why - never what the change "
              "answered - no journal row claims a stamp, and the boundary "
              "reads as not established: %r"
              % ((xf_got.get("written"), xf_got.get("since"),
                  len(_since_rows(xf)), xf_boundary["basis"]),),
              xf_got["written"] is True
              and (_held(xf_shards["P1"]) or {}).get("runId") == "RX"
              and _bytes(xf_path) == xf_index
              and (xf_got.get("since") or {}).get("written") is False
              and "cannot write" in str((xf_got.get("since") or {}).get(
                  "reason"))
              and _since_rows(xf) == []
              and xf_boundary["basis"].startswith(
                  "recorded runs exist and the boundary is not established"))
    finally:
        _harness.remove_tree(tmp)


# --- what a red's base reading needs to be read again -------------------------
def _recorder_held_cases(check):
    """(rh) The two facts a red's base is judged by after its run - whether
    the red's tree held a write of the recorder's own, and which suites its
    reading left not comparable because the base did not carry those writes -
    are kept on the row and the record, and come back through the one door a
    reader reads a record by. Without them a reader of the plan cannot tell
    a red whose tree held no recorder write from one that held some, nor a
    `not-knowable` the recorder rule produced from one of any other cause."""
    held_key = getattr(M, "RECORDER_HELD_KEY", "recorderHeld")
    moved_key = getattr(M, "BASE_UNCARRIED_KEY", "uncarried")
    root = _harness.fixture_root("audit-evidence-held-")
    try:
        ri_plan(root)
        steps = [_ri_step("sweep", exit_code=1)]
        rows, back = {}, {}
        for held in (False, True, None):
            result = _ri_result("failed", steps,
                                _ri_state(RI_H1, False, "sha256:s"), "sha256:k")
            result[held_key] = held
            if held is True:
                result[M.BASE_RED_KEY] = {
                    "run": "RB", "head": RI_H0, "task": "P1.1",
                    "verdict": "not-knowable", "atBase": [], "introduced": [],
                    "unknown": ["tests/test_t.py (the base did not carry it)"],
                    moved_key: ["tests/test_t.py"]}
            row = M.row_for(root, result, "task", _RK_TASK,
                            {"runId": "RH%s" % (held,),
                             "ts": "2026-11-26T10:00:00Z"})
            rows[held] = row
            back[held] = M.project_record(M.run_record(row), "task")
    finally:
        _harness.remove_tree(root)
    check("rh1 A ROW AND ITS RECORD KEEP WHETHER THE RED'S TREE HELD A RECORDER "
          "WRITE - false kept as false, never dropped as falsy - and a run that "
          "could not say holds no key at all: %r"
          % ([(h, rows[h].get(held_key, "absent"),
               (back[h][0] or {}).get(held_key, "absent"), back[h][1])
              for h in (False, True, None)],),
          rows[False].get(held_key) is False and rows[True].get(held_key) is True
          and held_key not in rows[None]
          and back[False][1] is None and back[True][1] is None
          and (back[False][0] or {}).get(held_key) is False
          and (back[True][0] or {}).get(held_key) is True
          and held_key not in (back[None][0] or {}))
    reading = (back[True][0] or {}).get(M.BASE_RED_KEY) or {}
    check("rh2 THE SUITES A BASE THAT DID NOT CARRY THE RECORDER'S WRITES LEFT "
          "NOT COMPARABLE are kept on the red's reading, row and record alike, "
          "so a reader tells that not-knowable from one of any other cause; a "
          "reading with none holds no such key: %r / %r"
          % ((rows[True].get(M.BASE_RED_KEY) or {}).get(moved_key), reading),
          (rows[True].get(M.BASE_RED_KEY) or {}).get(moved_key)
          == ["tests/test_t.py"]
          and reading.get(moved_key) == ["tests/test_t.py"]
          and reading.get("verdict") == "not-knowable"
          and moved_key not in M._base_red(_output.REPO_ROOT, {
              "run": "RB", "verdict": "introduced",
              "introduced": ["tests/test_t.py"]}))


def _sweep_row_cases(check):
    """(swr) A step's sweep counts as a committed row keeps them, and as a
    reader gets them back: paths redacted, the list cut by the writer whatever
    the caller handed it, and only well-formed entries read back."""
    root = _output.REPO_ROOT
    outside = os.path.join(os.path.dirname(os.path.abspath(root)),
                           "elsewhere", "test_x.py")
    handed = {"total": 50, "files": [{"path": "tests/test_%03d.py" % (i,),
                                      "cases": 1}
                                     for i in range(M.MAX_PATHS + 2)]
              + [{"path": outside, "cases": 3}], "filesDropped": 4}
    row = M._step(root, {"name": "sweep", M.SWEEP_CASES_KEY: handed}, ())
    kept = row.get(M.SWEEP_CASES_KEY) or {}
    paths = [f.get("path") for f in kept.get("files") or []]
    check("swr1 THE WRITER CUTS AND COUNTS: a caller handing more files than "
          "the row's bound keeps `MAX_PATHS` of them, and `filesDropped` adds "
          "the ones cut here to the ones the caller already left out: %r"
          % ((kept.get("total"), len(paths), kept.get("filesDropped")),),
          kept.get("total") == 50 and len(paths) == M.MAX_PATHS
          and kept.get("filesDropped") == 4 + 3)
    short = M._step(root, {"name": "sweep", M.SWEEP_CASES_KEY: {
        "total": 3, "files": [{"path": outside, "cases": 3}]}}, ())
    short_paths = [f.get("path") for f in
                   (short.get(M.SWEEP_CASES_KEY) or {}).get("files") or []]
    check("swr2 A PATH OUTSIDE THE PROJECT IS REDACTED, never stored as this "
          "machine's spelling, and a list inside the bound says nothing was "
          "dropped: %r" % (short.get(M.SWEEP_CASES_KEY),),
          len(short_paths) == 1 and outside not in short_paths
          and "filesDropped" not in (short.get(M.SWEEP_CASES_KEY) or {}))
    step = {M.SWEEP_CASES_KEY: {"total": 9, "files": [
        {"path": "tests/a.py", "cases": 4}, {"path": "tests/b.py",
                                              "cases": True},
        {"path": None, "cases": 2}, "tests/c.py"]}}
    check("swr3 THE READER TAKES ONLY WHAT A COUNT CAN BE READ FOR: a flag is "
          "not a count, an entry naming no path names no file, and a step "
          "with no sweep counts gives none: %r"
          % ((M.sweep_file_cases(step), M.sweep_file_cases({"ran": 3})),),
          M.sweep_file_cases(step) == {"tests/a.py": 4}
          and M.sweep_file_cases({"ran": 3}) == {})


def _sweep_ok_text(paths, newline="\n"):
    """A sweep's output through its own row formats: one ok row per path, in
    the order given, and the summary line over them."""
    rows = ["sweep: %d files, 8 workers" % (len(paths),)]
    rows += ["  ok      %-58s %d cases  [0.4s]" % (p, i + 1)
             for i, p in enumerate(paths)]
    rows += ["", "%d/%d files ok, %d cases"
             % (len(paths), len(paths), sum(range(1, len(paths) + 1)))]
    return newline.join(rows) + newline


def _sweep_keep_cases(check):
    """(swk) A sweep's per-file counts put the files a caller asked to keep
    first, so the writer's cut at `MAX_PATHS` falls on the files nobody asked
    about - and never invents a count for a kept path the sweep did not print."""
    kept_path = "tests/test_zzz_declared.py"
    cut = 20
    others = ["tests/test_%03d.py" % (i,) for i in range(M.MAX_PATHS + cut - 1)]
    text = _sweep_ok_text(others + [kept_path])
    bare = M.sweep_cases(text)
    held = M.sweep_cases(text, keep=(kept_path,))
    bare_paths = [f["path"] for f in bare["files"]]
    held_paths = [f["path"] for f in held["files"]]
    # Fixture: the kept file sorts LAST of the whole list, so a sort-then-cut
    # drops it and a keep-first order does not; `cut` files go either way.
    check("swk1 A KEPT FILE SORTING LAST SURVIVES THE CUT: with no keep the "
          "sorted list is cut at `MAX_PATHS` and loses it, with it named the "
          "kept file leads the list and the same number of others are "
          "dropped, its count the one the sweep printed: %r"
          % ((kept_path in bare_paths, held_paths[0], len(held_paths),
              held.get("filesDropped")),),
          kept_path not in bare_paths and bare["files"][0]["path"]
          == "tests/test_000.py" and len(bare_paths) == M.MAX_PATHS
          and bare.get("filesDropped") == cut
          and held_paths[0] == kept_path and len(held_paths) == M.MAX_PATHS
          and held.get("filesDropped") == cut
          and held["files"][0] == {"path": kept_path, "cases": len(others) + 1}
          and held_paths[1:] == sorted(others)[:M.MAX_PATHS - 1]
          and held["total"] == bare["total"])
    check("swk2 NO KEEP LEAVES THE OLD ORDER, whether it is absent, empty or "
          "names nothing the sweep printed - and a kept path the sweep did "
          "not print is not given a row: %r"
          % ([f["path"] for f in M.sweep_cases(text, keep=())["files"]][:2],),
          M.sweep_cases(text, keep=()) == bare
          and M.sweep_cases(text, keep=["tests/test_never_ran.py"]) == bare)
    spellings = ("tests\\test_zzz_declared.py", "./tests/test_zzz_declared.py",
                 ".\\tests\\test_zzz_declared.py")
    twins = [M.sweep_cases(text, keep=(s,)) for s in spellings]
    crlf = M.sweep_cases(_sweep_ok_text(others + [kept_path], "\r\n"),
                         keep=(kept_path,))
    check("swk3 A BACKSLASH OR `./` TWIN OF THE PATH IS THE SAME FILE, and a "
          "CRLF-ended sweep reads the same as an LF one: %r"
          % ([[f["path"] for f in t["files"]][0] for t in twins],),
          all(t == held for t in twins) and crlf == held)
    low, mid = "tests/test_000.py", "tests/test_017.py"
    two = M.sweep_cases(text, keep=(kept_path, low, mid))
    two_rev = M.sweep_cases(text, keep=(mid, low, kept_path))
    two_paths = [f["path"] for f in two["files"]]
    rest = [p for p in sorted(others) if p not in (low, mid)]
    check("swk4 KEPT FILES COME FIRST SORTED AMONG THEMSELVES, then the rest "
          "sorted, whatever order the caller named them in: %r"
          % (two_paths[:5],),
          two == two_rev and two_paths[:3] == [low, mid, kept_path]
          and two_paths[3:] == rest[:M.MAX_PATHS - 3]
          and two.get("filesDropped") == cut)
    check("swk5 THE ONE PATH KEY turns a backslash into a slash and drops a "
          "leading `./`, and leaves a path that has neither as it was: %r"
          % ((M.sweep_path_key(".\\tests\\a.py"), M.sweep_path_key("./a/b.py"),
              M.sweep_path_key("a/b.py")),),
          M.sweep_path_key(".\\tests\\a.py") == "tests/a.py"
          and M.sweep_path_key("./a/b.py") == "a/b.py"
          and M.sweep_path_key("a/b.py") == "a/b.py")
    short = M.sweep_cases(_sweep_ok_text(["tests/test_b.py", "tests/test_a.py"]),
                          keep=("tests/test_b.py",))
    check("swk6 ALLOW: a sweep inside the bound keeps every file, the kept one "
          "first, and says nothing was dropped: %r" % (short,),
          [f["path"] for f in short["files"]]
          == ["tests/test_b.py", "tests/test_a.py"]
          and "filesDropped" not in short)


# A STAGED SUITE: each row is a block the sweep runs as a job of its own, on one
# slot, and replays in this order (`_harness.staged_main`), so the case ids,
# their order and the tally are a one-process run's. Run whole in one process,
# the suite reached the sweep's per-file timeout floor on a windows CI cell; a
# block's timeout is read off its own recorded figure instead. The rows keep the
# order the cases ran in before the table existed, one per top-level case
# function; each block starts in a process of its own.
STAGES = (("wh-block", "_withheld_cases"), ("rf-block", "_read_field_cases"),
          ("ho-block", "_holder_cases"), ("hs-block", "_held_by_subject_cases"),
          ("bb-block", "_black_box_cases"), ("nu-block", "_newest_unreadable_cases"),
          ("ns-block", "_never_shared_cases"), ("gs-block", "_guard_structure_cases"),
          ("ur-block", "_unreadable_record_cases"),
          ("id-block", "_record_identity_cases"),
          ("ug-block", "_guard_unreadable_cases"),
          ("us-block", "_surface_unreadable_cases"), ("fh-block", "_full_held_cases"),
          ("ev-block", "_cases"), ("rs-block", "_record_sufficiency_cases"),
          ("sh-block", "_shared_subtree_cases"), ("rk-block", "_record_schema_cases"),
          ("lr-block", "_last_run_cases"), ("rv-block", "_repeat_record_cases"),
          ("uw-block", "_unwritable_lock_cases"), ("pa-block", "_behind_lock_cases"),
          ("lk-block", "_shard_lock_ast_cases"), ("ri-block", "_one_reader_cases"),
          ("kb-block", "_kept_base_cases"), ("fg-block", "_foreground_bound_cases"),
          ("pr-block", "_part_repeat_cases"), ("lp-block", "_left_to_phase_gate_cases"),
          ("st-block", "_selection_time_cases"), ("bs-block", "_base_scope_cases"),
          ("js-block", "_joined_step_cases"), ("cf-block", "_claimed_followers_cases"),
          ("tk-block", "_tree_key_cases"), ("bn-block", "_banner_cases"),
          ("grr-block", "_gate_reach_row_cases"),
          ("pc-block", "_project_config_cases"), ("mr-block", "_moment_reader_cases"),
          ("rfg-block", "_runnable_full_gate_cases"),
          ("kv-block", "_keep_both_verb_cases"),
          ("kc-block", "_container_twice_cases"),
          ("pd-block", "_plan_door_cases"),
          ("bu-block", "_boundary_upgrade_cases"),
          ("pk-block", "_plan_readers_cases"),
          ("rh-block", "_recorder_held_cases"),
          ("bsu-block", "_per_suite_base_cases"),
          ("swr-block", "_sweep_row_cases"),
          ("swk-block", "_sweep_keep_cases"))
# The prefix of the directory a full run's blocks report into.
_STAGE_PREFIX = "evidence-io-stages-"


if __name__ == "__main__":
    safe_stdio()
    raise SystemExit(_harness.staged_main(sys.argv[1:], STAGES, globals(),
                                          _STAGE_PREFIX))
