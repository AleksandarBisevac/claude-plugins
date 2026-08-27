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
              "The row is assembled from named fields, which is what makes "
              "'no runner output is ever written here' a property of the WRITER "
              "rather than a habit every call site has to remember: %r"
              % (sorted(row),),
              "rawOutput" not in row
              and "SENTINEL" not in _journal_io.canonical(row))

        check("ev11 the row carries the identity a reader joins on, and the "
              "scope it was measured at - a run recorded without saying whose "
              "it was could never be pointed back at the plan",
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

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__evidence_io.py --selftest\n")
    raise SystemExit(2)
