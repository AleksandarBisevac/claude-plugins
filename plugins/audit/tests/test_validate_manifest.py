#!/usr/bin/env python3
"""
The cases for `scripts/validate-manifest.py`, moved out of it - an entry point.

`validate-manifest.py` is hyphenated, so it comes through `_loader.load_script`
and the test file substitutes underscores; see `test_migrate_manifest.py` for both
halves of that rule. `M` is the module under test.

TWO NAMES, BECAUSE THIS SUITE ALREADY HAD ITS OWN `check`. 102 of the 131 cases go
through a DOMAIN wrapper - `check(name, expect_finding, mutate=None, *,
expect_warning=None)` deep-copies the valid fixture, mutates it, runs `validate()`
and decides the verdict - and the harness docstring says such a wrapper stays with
the cases that need it rather than moving into the shared runner. It cannot ALSO be
called `check`, because the other 29 cases are direct verdicts, so the harness's
own callback is `record(label, cond, detail)` here and the wrapper calls it. Those
29 used to spell `results.append(ok)` followed by a hand-rolled `print`; they are
`record(...)` calls now, with the label and the detail split exactly where the
format string split them.

WHAT THE DETAIL CHANGE MEANS FOR THE OUTPUT. This file is one of the 18 that
carried a detail, and one of the few that printed it on a PASSING line too:
`PASS v1 valid manifest passes (clean)`. The harness prints a detail only on
failure, so the green lines are shorter by exactly that trailing group. The LABELS
are untouched, and the migration proof is stated in those terms - every new line is
the old line with that group removed, in the same order.

`_valid_manifest()` came with the suite. It sat under `validate-manifest.py`'s own
`# --- selftest ---` marker and had no caller anywhere else in the tree (checked by
name across `plugins/audit/`), so leaving it behind would have left a fixture
builder in a shipped CLI with nothing to build for.

NOTHING HERE READS SOURCE OR REBINDS A GLOBAL. The AST scan for the six shapes the
guide forbids carrying literally came back empty for this file: no `globals()`, no
`vars()`, no `__file__`, no `dirname(dirname(...))`, no `split(a)[1].split(b)[0]`.
It also loads no sibling through `_loader`, so no `KNOWN_LAYER_DEBT` entry moved
with it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("validate-manifest.py", modname="validate_manifest")


# --- the fixture every mutating case starts from ------------------------------
def _valid_manifest():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P0", "title": "Phase", "status": "pending", "tasks": [
                {"id": "P0.1", "title": "Task", "status": "pending",
                 "tests": {"mode": "regression"}, "risk": "low",
                 "files": ["src/a.ts"],
                 "blockedBy": [], "dependsOn": []},
                {"id": "P0.2", "title": "Task 2", "status": "pending",
                 "dependsOn": ["P0.1"], "bugId": "BUG-1"},
            ]},
        ],
        "fileIndex": {"src/a.ts": ["P0.1"]},
        "bugs": [
            {"id": "BUG-1", "title": "A bug", "status": "in_progress",
             "taskId": "P0.2"},
        ],
    }


# --- cases --------------------------------------------------------------------
def _cases(record):
    import copy

    def check(name, expect_finding, mutate=None, *, expect_warning=None):
        m = copy.deepcopy(_valid_manifest())
        if mutate:
            mutate(m)
        findings, warnings = M.validate(m)
        if expect_finding is None:
            ok = findings == []
            detail = "expected clean, got %s" % (findings or "clean")
        else:
            ok = any(expect_finding in x for x in findings)
            detail = "expected finding ~%r in %s" % (expect_finding, findings)
        if ok and expect_warning is not None:
            ok = any(expect_warning in x for x in warnings)
            detail = "expected warning ~%r in %s" % (expect_warning, warnings)
        record(name, ok, detail)

    check("v1 valid manifest passes", None)
    # ca (F-P-4): a phase can finish WITHOUT being done — the feature it was for
    # is dropped, part of the work landed, the phase closes. Industry calls that
    # cancelled (Linear "Canceled", Jira "Won't Do", GitHub "closed as not
    # planned", ADO "Removed"); the manifest's bugs already had `wontfix` and
    # phases/tasks had no way to say it, so plans carried dead phases as
    # `pending` forever or lied with `done`.
    check("ca1 cancelled is a legal task status", None,
          lambda m: m["phases"][0]["tasks"][0].update(status="cancelled"))
    check("ca2 cancelled is a legal phase status", None,
          lambda m: m["phases"][0].update(status="cancelled"))
    check("ca3 a done phase may hold cancelled tasks - dropping one task is not "
          "a reason a finished phase cannot sign off", None,
          lambda m: (m["phases"][0].update(status="done"),
                     [t.update(status="done") for t in m["phases"][0]["tasks"]],
                     m["phases"][0]["tasks"][0].update(status="cancelled")))
    check("ca4 ...but a done phase with UNFINISHED tasks is still a slip",
          "status 'done' but 1 task(s) are not finished",
          lambda m: (m["phases"][0].update(status="done"),
                     [t.update(status="done") for t in m["phases"][0]["tasks"]],
                     m["phases"][0]["tasks"][0].update(status="in_progress")))
    check("ca5 a claim on a cancelled phase is stale, exactly as on a done one",
          None,
          lambda m: m["phases"][0].update(
              status="cancelled",
              claim={"sessionId": "s", "host": "h", "branch": "b"}),
          expect_warning="stale claim")
    check("v2 bad task status", "status 'doing' not in",
          lambda m: m["phases"][0]["tasks"][0].update(status="doing"))
    check("v3 bad tests.mode", "tests.mode 'yolo' not in",
          lambda m: m["phases"][0]["tasks"][0]["tests"].update(mode="yolo"))
    check("v4 duplicate id", "duplicate id: P0.1",
          lambda m: m["phases"][0]["tasks"].append(
              {"id": "P0.1", "title": "dup", "status": "pending"}))
    check("v5 dangling dependsOn", "dependsOn 'P9.9' does not resolve",
          lambda m: m["phases"][0]["tasks"][1].update(dependsOn=["P9.9"]))
    check("v6 dangling bugs[].taskId", "taskId 'P9.9' does not resolve",
          lambda m: m["bugs"][0].update(taskId="P9.9"))
    check("v7 dangling task.bugId", "bugId 'BUG-99' does not resolve",
          lambda m: m["phases"][0]["tasks"][1].update(bugId="BUG-99"))
    check("v8 malformed bug id", "id must match BUG-<number>",
          lambda m: (m["bugs"][0].update(id="bug_one"),
                     m["phases"][0]["tasks"][1].update(bugId="bug_one")))
    check("v9 bad bug status", "status 'zombie' not in",
          lambda m: m["bugs"][0].update(status="zombie"))
    check("v10 missing meta.version", "meta.version",
          lambda m: m["meta"].pop("version"))
    check("v11 dangling fileIndex ref", "fileIndex['src/a.ts']: task 'GONE'",
          lambda m: m.update(fileIndex={"src/a.ts": ["GONE", "P0.1"]}))
    check("v12 dangling phase blockedBy", "blockedBy 'PX' does not resolve",
          lambda m: m["phases"][0].update(blockedBy=["PX"]))

    # --- new in 0.3.0: cycles ---
    check("c1 two-task dependsOn cycle", "dependency cycle",
          lambda m: (m["phases"][0]["tasks"][0].update(dependsOn=["P0.2"]),
                     m["phases"][0]["tasks"][1].update(dependsOn=["P0.1"])))
    check("c2 self-loop", "dependency cycle",
          lambda m: m["phases"][0]["tasks"][0].update(dependsOn=["P0.1"]))
    check("c3 task blockedBy its own phase", "dependency cycle",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy=["P0"]))
    check("c4 acyclic chain stays clean", None,
          lambda m: m["phases"][0]["tasks"][1].update(blockedBy=["P0.1"]))

    # --- new in 0.3.0: reciprocity ---
    check("r1 bug->task without task->bug", "link must be reciprocal",
          lambda m: m["phases"][0]["tasks"][1].pop("bugId"))
    check("r2 task->bug without bug->task", "link must be reciprocal",
          lambda m: m["bugs"][0].update(taskId=None))

    # --- new in 0.3.0: fileIndex bidirectional ---
    check("f1 task file missing from fileIndex", "missing from fileIndex",
          lambda m: m["phases"][0]["tasks"][0].update(files=["src/other.ts"]))
    check("f2 line-suffix entries match stripped", None,
          lambda m: m["phases"][0]["tasks"][0].update(files=["src/a.ts:10-20"]))

    # --- new in 0.3.0: tests must be an object ---
    check("t1 tests as string is a finding", "tests must be an object",
          lambda m: m["phases"][0]["tasks"][0].update(tests="tdd"))

    # --- new in 0.5.0: ado link shape ---
    check("a1 valid ado link stays clean", None,
          lambda m: m["phases"][0]["tasks"][0].update(
              ado={"id": 1234, "url": "https://dev.azure.com/o/p/_workitems/edit/1234",
                   "lastSyncedAt": "2026-07-07T00:00:00Z"}))
    check("a2 ado as string is a finding", "ado must be an object",
          lambda m: m["bugs"][0].update(ado="WI-1234"))
    check("a3 non-integer ado.id is a finding", "ado.id must be an integer",
          lambda m: m["phases"][0]["tasks"][0].update(ado={"id": "1234"}))
    check("a4 null ado stays clean", None,
          lambda m: m["bugs"][0].update(ado=None))

    # --- new in 0.3.0: warnings ---
    check("w1 unknown key warns with did-you-mean", None,
          lambda m: m["phases"][0]["tasks"][0].update(dependson=["P0.2"]),
          expect_warning="did you mean 'dependsOn'")
    check("w2 unknown key warns", None,
          lambda m: m["meta"].update(frobnicate=True),
          expect_warning="unknown key 'frobnicate'")
    check("w3 legacy meta keys stay silent", None,
          lambda m: m["meta"].update(signOffChecklist=["x"], statusLegend=["y"]))

    # w5: the 0.5.1/0.6.1-known keys must produce NEITHER findings NOR warnings
    m5 = copy.deepcopy(_valid_manifest())
    m5["meta"].update(gitRoot="test", notes="n")
    m5["phases"][0].update(description="d")
    m5["phases"][0]["tasks"][0].update(details="dt")
    f5, w5warn = M.validate(m5)
    noise = [x for x in w5warn if any(k in x for k in
             ("gitRoot", "description", "details", "notes"))]
    ok = f5 == [] and noise == []
    record("w5 gitRoot/description/details/notes -> no findings, no warnings",
           ok, "clean" if ok else (f5 or noise))
    check("w4 in_progress task in pending phase warns", None,
          lambda m: m["phases"][0]["tasks"][0].update(status="in_progress"),
          expect_warning="still 'pending'")

    # claim (v0.15 sharded parallel-run coordination)
    check("cl1 valid claim on an active phase stays clean", None,
          lambda m: m["phases"][0].update(
              claim={"sessionId": "s1", "host": "h1", "branch": "audit/p0", "at": "t"}))
    check("cl2 claim not an object is a finding", "claim must be an object",
          lambda m: m["phases"][0].update(claim="whoever"))
    check("cl3 claim missing keys warns", None,
          lambda m: m["phases"][0].update(claim={"at": "t"}),
          expect_warning="claim is missing")
    check("cl4 claim on a done phase warns (stale)", None,
          lambda m: (m["phases"][0].update(
              status="done", claim={"sessionId": "s", "host": "h", "branch": "b"}),
              [t.update(status="done") for t in m["phases"][0]["tasks"]]),
          expect_warning="stale claim")

    # v0.16 — per-phase reviewSkill override + area tag are known keys (no noise)
    m6 = copy.deepcopy(_valid_manifest())
    m6["phases"][0].update(reviewSkill="backend-review", area="backend")
    f6, w6 = M.validate(m6)
    noise6 = [x for x in w6 if "reviewSkill" in x or "area" in x]
    ok6 = f6 == [] and noise6 == []
    record("pp1 per-phase reviewSkill+area: no finding, no unknown-key "
           "warning",
           ok6, "clean" if ok6 else (f6 or noise6))

    # v0.28 — the meta.areas registry. The shape rules live in _areas.py and are
    # tested there; what is tested HERE is the wiring, and the one rule that only
    # exists at this level: a warning must never become a finding, because a
    # manifest that stops validating over an informational registry would take the
    # whole pipeline down with it.
    def with_areas(m, areas, area_tag=None):
        m["meta"]["areas"] = areas
        if area_tag is not None:
            m["phases"][0]["area"] = area_tag

    m_reg = copy.deepcopy(_valid_manifest())
    with_areas(m_reg, {"api": {"root": "src", "description": "the api",
                               "reviewSkill": "backend-review",
                               "skills": ["conv"]}}, "api")
    f_reg, w_reg = M.validate(m_reg)
    # The warning half has to be ASSERTED, not merely mentioned in the label: with
    # only `findings == []` checked, dropping `areas` from KNOWN_META left this
    # green while every registry in the world warned as a typo.
    ok_reg = f_reg == [] and not [x for x in w_reg if "areas" in x]
    record("ar1 a registered area is clean - no finding, and no unknown-key "
           "warning for meta.areas itself",
           ok_reg, "clean" if ok_reg else (f_reg or w_reg))
    check("ar2 a malformed registry IS a finding (shape is not informational)",
          "must be an object",
          lambda m: with_areas(m, {"api": "src"}, "api"))
    check("ar3 a tag with no entry warns, and only warns", None,
          lambda m: with_areas(m, {"api": {"root": "src"}}, "apu"),
          expect_warning="has no entry in meta.areas")
    m_free = copy.deepcopy(_valid_manifest())
    m_free["phases"][0]["area"] = ["anything", "at all"]
    f_free, w_free = M.validate(m_free)
    ok_free = f_free == [] and not any("meta.areas" in x for x in w_free)
    record("ar4 free-text tags with NO registry are silent - the v0.16 "
           "feature is not deprecated by this one",
           ok_free, "clean" if ok_free else (f_free or w_free))
    check("ar5 two areas disagreeing about the reviewer warns, naming the winner "
          "written order picked", None,
          lambda m: with_areas(m, {"a": {"root": "src", "reviewSkill": "ra"},
                                   "b": {"root": "src", "reviewSkill": "rb"}},
                               ["a", "b"]),
          expect_warning='"ra" (from area a) is the one that runs')
    check("ar5b an area that says 'tests are the signer' DISAGREES with one that "
          "names a reviewer, and the message is JSON-spelled - a reader who acts "
          "on it is editing a JSON file, where `None` is not a thing they can type",
          None,
          lambda m: with_areas(m, {"a": {"root": "src", "reviewSkill": None},
                                   "b": {"root": "src", "reviewSkill": "rb"}},
                               ["a", "b"]),
          expect_warning='a=null, b="rb"')
    check("ar6 an area with no root warns rather than failing", None,
          lambda m: with_areas(m, {"api": {"description": "d"}}, "api"),
          expect_warning="no 'root'")
    check("ar7 area as a number is a finding - it would silently belong to no "
          "group and resolve against no area", "area must be a tag or a list",
          lambda m: m["phases"][0].update(area=3))
    check("ar8 an empty tag inside the list is a finding",
          "every area tag must be a non-empty string",
          lambda m: m["phases"][0].update(area=["api", ""]))

    # --- robustness: validate() must NEVER raise on hostile shapes, and the
    #     wrong-type diagnostics must be actionable (regression guard for the
    #     "never raises on arbitrary JSON" contract + schema drift) ---
    check("z1 blockedBy as a bare string is a finding (no per-char iteration)",
          "blockedBy must be an array",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy="P0"))
    check("z2 unhashable blockedBy entry reported, does not crash",
          "must be a string id",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy=[["x"]]))
    check("z3 unhashable dependsOn entry reported, does not crash",
          "must be a string id",
          lambda m: m["phases"][0]["tasks"][1].update(dependsOn=[{"k": "v"}]))
    check("z4 non-array fileIndex value is a finding",
          "must be an array of task ids",
          lambda m: m.update(fileIndex={"src/a.ts": "P0.1"}))
    check("z5 non-array tasks is a finding",
          "tasks must be an array",
          lambda m: m["phases"][0].update(tasks="P0.1"))
    check("z6 boolean version rejected (bool is not a valid int version)",
          "meta.version",
          lambda m: m["meta"].update(version=True))
    # removing tasks orphans fileIndex/bug links, so clear those too and assert
    # the bare "no tasks" case is a WARNING, not a hard finding
    check("z7 absent tasks warns but is not a hard finding", None,
          lambda m: (m.pop("fileIndex", None), m.pop("bugs", None),
                     m["phases"][0].pop("tasks", None)),
          expect_warning="no 'tasks' key")
    check("z8 done phase with a non-done task is a finding",
          "status 'done' but",
          lambda m: m["phases"][0].update(status="done"))

    # --- v0.33: proposals[] lifecycle (parked phases) ---
    def parked(pid="PROP-1", phase_id="P1"):
        return {
            "id": pid, "name": "Security hardening", "status": "proposed",
            "origin": "audit:init", "createdISO": "2026-08-11T00:00:00Z",
            "scope": "src/", "benefit": "fewer injection paths",
            "openQuestions": [],
            "payload": {"phase": {
                "id": phase_id, "title": "Security hardening",
                "status": "pending",
                "tasks": [{"id": phase_id + ".1", "title": "Parameterize SQL",
                           "status": "pending", "tests": {"mode": "tdd"},
                           "files": ["src/db.ts"]}]}},
            "materializedAs": None, "materializedAt": None,
        }

    # pr1: a parked proposal is clean AND none of its keys warn as unknown —
    # asserted like ar1, or dropping a key from KNOWN_PROPOSAL goes unnoticed.
    m_pr = copy.deepcopy(_valid_manifest())
    m_pr["proposals"] = [parked()]
    f_pr, w_pr = M.validate(m_pr)
    noise_pr = [x for x in w_pr if "proposal" in x.lower()]
    ok_pr = f_pr == [] and noise_pr == []
    record("pr1 parked proposal: no finding, no unknown-key warning",
           ok_pr, "clean" if ok_pr else (f_pr or noise_pr))
    check("pr2 payload phase id colliding with a live phase is a finding",
          "reserved id 'P0' collides",
          lambda m: m.update(proposals=[parked(phase_id="P0")]))
    check("pr3 payload task id colliding with a live task is a finding",
          "reserved id 'P0.1' collides",
          lambda m: m.update(proposals=[
              dict(parked(), payload={"phase": {
                  "id": "P1", "title": "T", "status": "pending",
                  "tasks": [{"id": "P0.1", "title": "dup", "status": "pending"}]}})]))
    check("pr4 dangling materializedAs is a finding",
          "materializedAs 'P9' does not resolve",
          lambda m: m.update(proposals=[
              dict(parked(), status="materialized", materializedAs="P9")]))
    check("pr5 payload-bearing proposal with a bad status is a finding",
          "status 'parked' not in",
          lambda m: m.update(proposals=[dict(parked(), status="parked")]))
    # pr6: legacy free-form proposal (no payload) — warnings at most, NEVER a
    # finding. The back-compat pin: pre-0.33 wrote whatever it liked here.
    m_leg = copy.deepcopy(_valid_manifest())
    m_leg["proposals"] = [{"id": "modernize-build", "name": "Modernize build",
                           "status": "someday", "origin": "audit:init"}]
    f_leg, _w_leg = M.validate(m_leg)
    ok_leg = f_leg == []
    record("pr6 legacy free-form proposal: warnings at most, no finding",
           ok_leg, "clean" if ok_leg else f_leg)
    check("pr7a proposals as a string is a finding", "proposals: not an array",
          lambda m: m.update(proposals="later"))
    check("pr7b a non-object entry is a finding", "proposals[0]: not an object",
          lambda m: m.update(proposals=["later"]))
    check("pr8 duplicate PROP id is a finding", "duplicate proposal id: PROP-1",
          lambda m: m.update(proposals=[parked(), parked(phase_id="P2")]))
    # pr9: THE declined-init pin — meta + empty phases + parked proposals is a
    # fully valid manifest (the park-all write path of /audit:init).
    m_empty = {"meta": {"version": 2}, "phases": [], "fileIndex": {},
               "bugs": [], "proposals": [parked()]}
    f_empty, _w_empty = M.validate(m_empty)
    ok_empty = f_empty == []
    record("pr9 meta + empty phases + parked proposals validates clean",
           ok_empty, "clean" if ok_empty else f_empty)
    check("pr10 materializedAs set while status is still 'proposed' is a finding",
          "must be 'materialized'",
          lambda m: m.update(proposals=[dict(parked(), materializedAs="P0")]))
    check("pr11 two proposals reserving the same phase id is a finding",
          "already reserved by another proposal",
          lambda m: m.update(proposals=[parked(), parked(pid="PROP-2")]))
    # pr12: staged blockedBy — a ref to another proposal's reserved id is clean;
    # a ref naming nothing anywhere warns (staged, not live) but never fails.
    m_ref = copy.deepcopy(_valid_manifest())
    p_a, p_b = parked(), parked(pid="PROP-2", phase_id="P2")
    p_b["payload"]["phase"]["blockedBy"] = ["P1"]
    m_ref["proposals"] = [p_a, p_b]
    f_ref, w_ref = M.validate(m_ref)
    ok_ref = f_ref == [] and not any("blockedBy" in x for x in w_ref)
    record("pr12a staged blockedBy to another reserved id is clean",
           ok_ref, "clean" if ok_ref else (f_ref or w_ref))
    m_ref2 = copy.deepcopy(_valid_manifest())
    p_c = parked()
    p_c["payload"]["phase"]["blockedBy"] = ["P77"]
    m_ref2["proposals"] = [p_c]
    f_ref2, w_ref2 = M.validate(m_ref2)
    ok_ref2 = f_ref2 == [] and any("P77" in x for x in w_ref2)
    record("pr12b staged blockedBy naming nothing warns, never fails",
           ok_ref2, "clean+warned" if ok_ref2 else (f_ref2 or w_ref2))
    # pr13: a materialized proposal whose payload id now lives as a real phase
    # must NOT be reported as a collision (that collision is the SUCCESS state).
    m_mat = copy.deepcopy(_valid_manifest())
    mat = parked(phase_id="P0")
    mat.update(status="materialized", materializedAs="P0",
               materializedAt="2026-08-11T00:00:00Z")
    m_mat["proposals"] = [mat]
    f_mat, _w_mat = M.validate(m_mat)
    ok_mat = f_mat == []
    record("pr13 materialized proposal: live payload id is not a collision",
           ok_mat, "clean" if ok_mat else f_mat)

    # --- workstream B: task moves (id-prefix rule + movedFrom) ---
    # The id rule is the hand-move detector: /audit:task move renumbers a task
    # into its new phase, so an id that does not match its phase means someone
    # dragged the object by hand. A WARNING, never a finding -- legacy
    # manifests with free-form ids must not go red over bookkeeping.
    check("mv1 a task id that does not follow its phase's prefix warns only",
          None,
          lambda m: m["phases"][0]["tasks"].append(
              {"id": "ODD-7", "title": "stray", "status": "pending"}),
          expect_warning="does not follow its phase")
    m_mv = copy.deepcopy(_valid_manifest())
    m_mv["phases"][0]["tasks"][0]["movedFrom"] = {
        "id": "P3.4", "phase": "P3", "at": "2026-08-11T00:00:00Z"}
    f_mv, w_mv = M.validate(m_mv)
    noise_mv = [x for x in w_mv if "movedFrom" in x]
    ok_mv = f_mv == [] and noise_mv == []
    record("mv2 a well-formed movedFrom is clean - no finding, no unknown-key "
           "warning",
           ok_mv, "clean" if ok_mv else (f_mv or noise_mv))
    check("mv3 movedFrom that is not an object warns, and only warns", None,
          lambda m: m["phases"][0]["tasks"][0].update(movedFrom="P3.4"),
          expect_warning="movedFrom")
    check("mv3b movedFrom missing its keys warns, naming them", None,
          lambda m: m["phases"][0]["tasks"][0].update(movedFrom={"id": "P3.4"}),
          expect_warning="movedFrom is missing")
    check("mv4 movedFrom null is clean (the schema says object|null)", None,
          lambda m: m["phases"][0]["tasks"][0].update(movedFrom=None))
    # The base fixture itself must not warn: P0.1/P0.2 follow P0.
    _f_base, _w_base = M.validate(copy.deepcopy(_valid_manifest()))
    ok_base = _f_base == [] and not any("does not follow" in x
                                       for x in _w_base)
    record("mv5 existing well-formed ids produce no id-prefix warning",
           ok_base, "clean" if ok_base else (_f_base or _w_base))

    # --- md: intra-manifest model-id near-miss (typo detector) ---
    # WARNING only, and only for a value used EXACTLY once beside a
    # case-insensitive / edit-distance-1 neighbour used elsewhere in the
    # manifest or among meta.usage.pricing keys. Deliberately intra-manifest:
    # this validator is an offline shape-checker and never reads the config or
    # the ledger, so the three-source model hint lives in the panel instead.
    def _mk_md1(m):
        t = m["phases"][0]["tasks"]
        t[0]["model"] = "claude-opus-5"
        t[1]["model"] = "claude-opus-5"
        t.append({"id": "P0.3", "title": "typo", "status": "pending",
                  "model": "claude-opsu-5"})
    check("md1 a once-used model one edit from an established one warns",
          None, _mk_md1, expect_warning="'claude-opsu-5'")
    def _mk_md2(m):
        t = m["phases"][0]["tasks"]
        t[0]["model"] = "sonnet"
        t[1]["model"] = "Sonnet"
    check("md2 a case-only near-miss used once warns", None, _mk_md2,
          expect_warning="'Sonnet'")
    # md3: a clean single-model manifest never draws this (the mv5 pattern) --
    # there is no second spelling to near-miss against.
    m_md = copy.deepcopy(_valid_manifest())
    for _t in m_md["phases"][0]["tasks"]:
        _t["model"] = "claude-opus-5"
    f_md, w_md = M.validate(m_md)
    noise_md = [x for x in w_md if "model" in x]
    ok_md = f_md == [] and noise_md == []
    record("md3 a clean single-model manifest draws no model warning",
           ok_md, "clean" if ok_md else (f_md or noise_md))
    def _mk_md4(m):
        m["meta"]["usage"] = {"pricing": {"claude-haiku-4-5": {"in": 1.0}}}
        m["phases"][0]["tasks"][0]["model"] = "claude-haiku-45"
    check("md4 a once-used near-miss of a meta.usage.pricing key warns",
          None, _mk_md4, expect_warning="'claude-haiku-45'")
    # md5: a value used twice is an established spelling, not a slip -- even
    # one edit away from another established one.
    m_md5 = copy.deepcopy(_valid_manifest())
    _ts = m_md5["phases"][0]["tasks"]
    _ts[0]["model"] = "claude-opus-5"
    _ts[1]["model"] = "claude-opus-5"
    _ts.append({"id": "P0.3", "title": "x", "status": "pending",
                "model": "claude-opsu-5"})
    _ts.append({"id": "P0.4", "title": "y", "status": "pending",
                "model": "claude-opsu-5"})
    f_md5, w_md5 = M.validate(m_md5)
    noise_md5 = [x for x in w_md5 if "is used once" in x]
    ok_md5 = f_md5 == [] and noise_md5 == []
    record("md5 a spelling used twice is established, never flagged",
           ok_md5, "clean" if ok_md5 else (f_md5 or noise_md5))
    def _mk_md6(m):
        m["phases"][0]["review"] = {"model": "claude-opus5"}
        for t in m["phases"][0]["tasks"]:
            t["model"] = "claude-opus-5"
    check("md6 a phase review model near-missing the task model warns, "
          "naming the phase", None, _mk_md6, expect_warning="phase P0 review")

    # --- sk: unresolved-skills advisory (v0.37 B2) ---
    # WARNING only, and GATED: it exists only in a manifest that uses skills
    # somewhere (a non-empty task.skills, an explicit null, or an area that
    # declares defaults). A project ignoring the feature gets zero new lines --
    # and `skills: []` alone does NOT switch it on, because generators
    # initialize empty lists on every task.
    m_sk0 = copy.deepcopy(_valid_manifest())
    f_sk0, w_sk0 = M.validate(m_sk0)
    ok_sk0 = f_sk0 == [] and not any("skills" in x for x in w_sk0)
    record("sk1 a manifest that uses no skills anywhere draws no skills "
           "warning - the gate, and the back-compat pin",
           ok_sk0, "clean" if ok_sk0 else (f_sk0 or w_sk0))
    check("sk2 with skills in use, a task resolving to nothing warns, naming "
          "what was consulted and the three exits", None,
          lambda m: m["phases"][0]["tasks"][0].update(skills=["conv"]),
          expect_warning="task P0.2: no skills resolve")
    m_sk3 = copy.deepcopy(_valid_manifest())
    m_sk3["phases"][0]["tasks"][0]["skills"] = ["conv"]
    m_sk3["phases"][0]["tasks"][1]["skills"] = None
    f_sk3, w_sk3 = M.validate(m_sk3)
    ok_sk3 = f_sk3 == [] and not any("no skills resolve" in x for x in w_sk3)
    record("sk3 an explicit null is an ANSWER - the opted-out task is not "
           "'unresolved' and draws nothing",
           ok_sk3, "clean" if ok_sk3 else (f_sk3 or w_sk3))
    m_sk4 = copy.deepcopy(_valid_manifest())
    m_sk4["meta"]["areas"] = {"api": {"root": "src", "skills": ["conv"]}}
    m_sk4["phases"][0]["area"] = "api"
    f_sk4, w_sk4 = M.validate(m_sk4)
    ok_sk4 = f_sk4 == [] and not any("no skills resolve" in x for x in w_sk4)
    record("sk4 an area default RESOLVES - tasks under a skills-declaring "
           "area are covered, not warned about",
           ok_sk4, "clean" if ok_sk4 else (f_sk4 or w_sk4))
    check("sk5 the registry alone arms the gate: areas declare skills but the "
          "phase is untagged, so nothing reaches its tasks", None,
          lambda m: m["meta"].update(
              areas={"api": {"root": "src", "skills": ["conv"]}}),
          expect_warning="phase has no area tag")
    check("sk6 a wrong-typed task.skills warns (and only warns) - it is use "
          "evidence, and resolution loads nothing from it", None,
          lambda m: m["phases"][0]["tasks"][0].update(skills="conv"),
          expect_warning="skills must be an array")

    # --- sn: intra-manifest skill-name near-miss (the md detector, applied
    #     to skill names; inventory-based hints stay the panel's) ---
    def _sn_base(m, once, where="task"):
        t = m["phases"][0]["tasks"]
        t[0]["skills"] = ["python-conventions"]
        t[1]["skills"] = ["python-conventions"]
        if where == "task":
            t.append({"id": "P0.3", "title": "typo", "status": "pending",
                      "skills": [once]})
        else:
            m["meta"]["areas"] = {"api": {"root": "src", "skills": [once]}}
    check("sn1 a once-used skill one slip from an established one warns",
          None, lambda m: _sn_base(m, "pyton-conventions"),
          expect_warning="'pyton-conventions'")
    check("sn2 two slips warn too, on names long enough to carry them",
          None, lambda m: _sn_base(m, "pyton-conventons"),
          expect_warning="'pyton-conventons'")
    m_sn3 = copy.deepcopy(_valid_manifest())
    t_sn3 = m_sn3["phases"][0]["tasks"]
    t_sn3[0]["skills"] = ["web"]
    t_sn3[1]["skills"] = ["web"]
    t_sn3.append({"id": "P0.3", "title": "x", "status": "pending",
                  "skills": ["wasm"]})
    f_sn3, w_sn3 = M.validate(m_sn3)
    ok_sn3 = f_sn3 == [] and not any("near-miss" in x for x in w_sn3)
    record("sn3 two slips on SHORT names stay silent - 'web' vs 'wasm' is "
           "distance 2 and pure noise",
           ok_sn3, "clean" if ok_sn3 else (f_sn3 or w_sn3))
    m_sn4 = copy.deepcopy(_valid_manifest())
    t_sn4 = m_sn4["phases"][0]["tasks"]
    t_sn4[0]["skills"] = ["python-conventions"]
    t_sn4[1]["skills"] = ["python-conventions"]
    t_sn4.append({"id": "P0.3", "title": "x", "status": "pending",
                  "skills": ["pyton-conventions"]})
    t_sn4.append({"id": "P0.4", "title": "y", "status": "pending",
                  "skills": ["pyton-conventions"]})
    f_sn4, w_sn4 = M.validate(m_sn4)
    ok_sn4 = f_sn4 == [] and not any("near-miss" in x for x in w_sn4)
    record("sn4 a spelling used twice is established, never flagged - the md5 "
           "rule",
           ok_sn4, "clean" if ok_sn4 else (f_sn4 or w_sn4))
    check("sn5 an area-declared skill is a site too, and the warning names it",
          None, lambda m: _sn_base(m, "pyton-conventions", where="area"),
          expect_warning="meta.areas.api")

    # --- im: meta.ado.identityMap shape (v0.38 C) ---
    # Shape only: the map's USE is advisory (/audit:sync proposes, never
    # assigns), but a malformed map is a structural defect like any other
    # wrong type in this file. No email-shape policing -- an ADO identity is
    # whatever the org's directory says it is.
    def _with_imap(m, imap):
        m["meta"]["ado"] = {"organization": "o", "project": "p",
                            "identityMap": imap}

    # (ma) meta.ado itself has a shape - "ado": "org" used to draw neither
    # finding nor warning ("ado" sits in KNOWN_META; _check_ado covered only
    # item-level links), so _check_identity_map inherited the blind spot by
    # silently returning on a non-dict. F-C-1 of the v0.38 round.
    m_ma1 = copy.deepcopy(_valid_manifest())
    m_ma1["meta"]["ado"] = "my-org"
    f_ma1, _ = M.validate(m_ma1)
    ok_ma1 = any("meta: ado must be an object or null" in x for x in f_ma1)
    record("ma1 meta.ado as a bare string is a FINDING - a config that would "
           "be misread",
           ok_ma1)
    m_ma2 = copy.deepcopy(_valid_manifest())
    m_ma2["meta"]["ado"] = None
    f_ma2, w_ma2 = M.validate(m_ma2)
    ok_ma2 = not any("ado" in x for x in f_ma2 + w_ma2)
    record("ma2 meta.ado null (and absent) stays silent - an answer, not a "
           "miss",
           ok_ma2)

    m_im1 = copy.deepcopy(_valid_manifest())
    _with_imap(m_im1, {"alice@corp.dev": "alice@corp.example.com",
                       "bob@corp.dev": "bob@corp.example.com"})
    f_im1, w_im1 = M.validate(m_im1)
    noise_im1 = [x for x in w_im1 if "identityMap" in x]
    ok_im1 = f_im1 == [] and noise_im1 == []
    record("im1 a well-formed identityMap is clean - no finding, no warning",
           ok_im1, "clean" if ok_im1 else (f_im1 or noise_im1))
    check("im2 identityMap as a string is a finding",
          "identityMap: must be an object",
          lambda m: _with_imap(m, "alice=alice@corp.example.com"))
    check("im3 a non-string value is a finding",
          "value must be a non-empty ADO identity string",
          lambda m: _with_imap(m, {"alice@corp.dev": 42}))
    check("im4 an empty value is a finding",
          "value must be a non-empty ADO identity string",
          lambda m: _with_imap(m, {"alice@corp.dev": "  "}))
    check("im5 an empty key is a finding",
          "keys must be non-empty ledger identity strings",
          lambda m: _with_imap(m, {"": "alice@corp.example.com"}))
    check("im6 two keys sharing one ADO identity warn, and only warn", None,
          lambda m: _with_imap(m, {"alice@corp.dev": "shared@corp.example.com",
                                   "bob@corp.dev": "shared@corp.example.com"}),
          expect_warning="is the target of 2 ledger identities")
    check("im7 null identityMap is clean (an answer, like ado: null)", None,
          lambda m: _with_imap(m, None))
    m_im8 = copy.deepcopy(_valid_manifest())
    m_im8["meta"]["ado"] = {"organization": "o", "project": "p"}
    f_im8, w_im8 = M.validate(m_im8)
    noise_im8 = [x for x in w_im8 if "identityMap" in x]
    ok_im8 = f_im8 == [] and noise_im8 == []
    record("im8 meta.ado without an identityMap draws nothing - the "
           "back-compat pin",
           ok_im8, "clean" if ok_im8 else (f_im8 or noise_im8))

    # --- av: meta.ado connector v2 config shape ---
    # The v2 keys (enabled/echo/phaseWorkItems/stateMap/onComplete/comments/
    # sprint/pull) are checked by check_ado_meta -- ONE front door shared with
    # the panel's write_ado, so the CLI and the panel cannot disagree about
    # what a valid connector config is.
    def _with_ado(m, **kw):
        ado = {"organization": "o", "project": "p"}
        ado.update(kw)
        m["meta"]["ado"] = ado

    m_av1 = copy.deepcopy(_valid_manifest())
    _with_ado(m_av1, enabled=True, echo=False, phaseWorkItems=True,
              types={"bug": "Bug", "task": "Task", "pbi": None},
              stateMap={"task": {"done": "Review", "blocked": None},
                        "bug": {"fixed": "Resolved"}},
              onComplete={"remainingWork": 0},
              comments={"onBlocked": True, "onComplete": False},
              sprint={"team": "Web", "mode": "current"},
              pull={"areaPath": "Proj\\Team", "tags": ["repo-x"]})
    f_av1, w_av1 = M.validate(m_av1)
    noise_av1 = [x for x in w_av1 if "ado" in x]
    ok_av1 = f_av1 == [] and noise_av1 == []
    record("av1 a full well-formed v2 connector config is clean - no finding, "
           "no warning",
           ok_av1, "clean" if ok_av1 else (f_av1 or noise_av1))
    m_av2 = copy.deepcopy(_valid_manifest())
    m_av2["meta"]["ado"] = {"organization": "o", "project": "p",
                            "stateMap": None, "onComplete": None,
                            "comments": None, "sprint": None, "pull": None}
    f_av2, w_av2 = M.validate(m_av2)
    noise_av2 = [x for x in w_av2 if "ado" in x]
    ok_av2 = f_av2 == [] and noise_av2 == []
    record("av2 every nullable v2 key accepts null - an answer, not a miss",
           ok_av2, "clean" if ok_av2 else (f_av2 or noise_av2))
    check("av3 typo 'statemap' warns with did-you-mean", None,
          lambda m: _with_ado(m, statemap={"task": {"done": "Review"}}),
          expect_warning="did you mean 'stateMap'")
    check("av4 typo 'identitymap' warns with did-you-mean", None,
          lambda m: _with_ado(m, identitymap={"a": "b"}),
          expect_warning="did you mean 'identityMap'")
    check("av5 enabled as a string is a finding",
          "enabled: must be true or false",
          lambda m: _with_ado(m, enabled="yes"))
    check("av6 stateMap as a string is a finding",
          "stateMap: must be an object",
          lambda m: _with_ado(m, stateMap="done=Closed"))
    check("av7 a status key outside the vocabulary warns with did-you-mean",
          None,
          lambda m: _with_ado(m, stateMap={"task": {"Done": "Closed"}}),
          expect_warning="did you mean 'done'")
    check("av8 an empty stateMap value is a finding",
          "must be an ADO state name or null",
          lambda m: _with_ado(m, stateMap={"task": {"done": "  "}}))
    check("av9 negative remainingWork is a finding",
          "remainingWork: must be a number >= 0 or null",
          lambda m: _with_ado(m, onComplete={"remainingWork": -1}))
    check("av10 boolean remainingWork is a finding (bool is not a number "
          "here)",
          "remainingWork: must be a number >= 0 or null",
          lambda m: _with_ado(m, onComplete={"remainingWork": True}))
    check("av11 sprint without a team is a finding",
          "sprint: requires a non-empty 'team'",
          lambda m: _with_ado(m, sprint={"mode": "current"}))
    check("av12 sprint mode outside the enum is a finding",
          "sprint.mode: must be 'current'",
          lambda m: _with_ado(m, sprint={"team": "Web", "mode": "path"}))
    check("av13 an empty pull tag is a finding",
          "pull.tags: every tag must be a non-empty string",
          lambda m: _with_ado(m, pull={"tags": ["repo-x", ""]}))
    check("av14 comments.onBlocked as a string is a finding",
          "comments.onBlocked: must be true or false",
          lambda m: _with_ado(m, comments={"onBlocked": "yes"}))
    check("av15 a non-string types value is a finding",
          "types: every value must be a work-item type name",
          lambda m: _with_ado(m, types={"bug": 42}))
    # phase-level ado link (phaseWorkItems writes phase.ado)
    check("av16 a valid phase ado link stays clean", None,
          lambda m: m["phases"][0].update(
              ado={"id": 7, "url": None, "lastSyncedAt": None,
                   "iterationPath": "Proj\\Sprint 9"}))
    check("av17 phase ado as a string is a finding",
          "phase P0: ado must be an object",
          lambda m: m["phases"][0].update(ado="WI-7"))
    # F1 (live gate): phase PBIs have their OWN state vocabulary - a third
    # stateMap block, keyed by the same status names tasks use.
    check("av18 a stateMap.phase block is clean and known", None,
          lambda m: _with_ado(m, stateMap={"phase": {"done": "Done",
                                                     "in_progress": None}}))
    check("av19 an unknown status inside stateMap.phase warns did-you-mean",
          None,
          lambda m: _with_ado(m, stateMap={"phase": {"Done": "Done"}}),
          expect_warning="did you mean 'done'")
    # ENH-1: the personalizable provenance tag.
    check("av20 a custom tag is clean and null (no tag) is an answer", None,
          lambda m: _with_ado(m, tag="repo-storefront"))
    check("av21 tag null stays clean", None,
          lambda m: _with_ado(m, tag=None))
    check("av22 an empty tag string is a finding",
          "tag: must be a non-empty string or null",
          lambda m: _with_ado(m, tag="  "))

    # --- CLI exit codes: 0 valid · 1 findings · 2 usage/unreadable ---
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_valid_manifest(), fh)
    ok = M.main([path]) == 0
    record("c5 CLI accepts valid file (exit 0)",
           ok)
    bad = copy.deepcopy(_valid_manifest())
    bad["phases"][0]["tasks"][0]["status"] = "doing"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(bad, fh)
    ok = M.main([path]) == 1
    record("c6 CLI reports findings (exit 1)",
           ok)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    ok = M.main([path]) == 2
    record("c7 CLI rejects unparseable file (exit 2)",
           ok)
    ok = M.main([]) == 2
    record("c8 CLI usage error (exit 2)",
           ok)
    os.unlink(path)

    # --- ds: the seams validate() was decomposed along --------------------------
    # `validate()` was 354 lines threading seven accumulating locals through six
    # unrelated questions. It is orchestration now, and every question lives in a
    # piece that takes a NAMED index and returns its own (findings, warnings).
    # The 131 cases above prove the BEHAVIOUR is unchanged; these prove the seams
    # are the ones claimed, and each is reachable only because the piece became
    # callable — which is the other half of what the cut bought.
    _ds_phases = [
        {"id": "P0", "title": "Phase", "status": "pending", "tasks": [
            {"id": "P0.1", "title": "T", "status": "pending",
             "files": ["src/a.ts"]},
            {"id": "P0.2", "title": "T2", "status": "pending", "files": [],
             "bugId": "BUG-1"}]},
        {"id": "P1", "title": "Two", "status": "pending", "tasks": []},
    ]

    _f_ds1, _w_ds1 = M._check_meta({"meta": {"version": 2}, "phazes": []})
    record("ds1 _check_meta answers for the ROOT object's key vocabulary as "
           "well as for meta - one piece for the document's header, so the "
           "root's unknown-key warning does not go missing the moment "
           "validate() stops spelling it itself",
           _f_ds1 == [] and any("manifest root" in x and "phazes" in x
                                for x in _w_ds1),
           (_f_ds1, _w_ds1))
    _f_ds2, _w_ds2 = M._check_meta({"meta": "nope"})
    record("ds2 ...and a non-object meta is ONE finding: the guard returns "
           "instead of falling through to the version rule, which would name "
           "one defect twice",
           _f_ds2 == ["meta: missing or not an object"] and _w_ds2 == [],
           (_f_ds2, _w_ds2))

    _ix, _f_ds3, _w_ds3 = M._walk_phases(_ds_phases)
    record("ds3 _walk_phases hands back a NAMED index instead of five "
           "positional lists - the shape that made the cut possible at all: %r"
           % (sorted(_ix),),
           sorted(_ix) == ["bug_links", "phase_ids", "task_by_id",
                           "task_files", "task_ids"])
    record("ds4 ...and it carries what the four checks after it read: ids in "
           "DOCUMENT order, the task OBJECT for the reciprocity check, and "
           "each bug link as a (where, task, bug) triple",
           _ix["phase_ids"] == ["P0", "P1"]
           and _ix["task_ids"] == ["P0.1", "P0.2"]
           and _ix["task_by_id"]["P0.2"] is _ds_phases[0]["tasks"][1]
           and _ix["bug_links"] == [("task P0.2", "P0.2", "BUG-1")],
           _ix)
    record("ds5 ...and task_files holds only the tasks that CLAIM files - a "
           "`files: []` task is absent rather than mapped to [], because the "
           "fileIndex check walks it with .items() and an empty entry is a lap "
           "around nothing",
           _ix["task_files"] == {"P0.1": ["src/a.ts"]}, _ix["task_files"])
    # The accumulator rule in the direction that fails SILENTLY: a piece keeping
    # its answer in a list it did not build fresh returns the same list twice,
    # and the second caller reads the first caller's findings.
    _ix_a, _f_dsa, _w_dsa = M._walk_phases(_ds_phases)
    _f_dsa.append("scribbled on by a caller")
    _ix_b, _f_dsb, _w_dsb = M._walk_phases(_ds_phases)
    record("ds6 every call returns its OWN lists and its own index - writing "
           "to one caller's findings cannot reach the next caller's, which is "
           "exactly what passing the accumulator in used to permit",
           _f_dsb == [] and _w_dsb == [] and _f_dsa != _f_dsb
           and _ix_a is not _ix_b, (_f_dsa, _f_dsb))

    _ds_bug_rows = [{"id": "BUG-1", "title": "b", "status": "open"}, "junk",
                    {"title": "no id"}]
    record("ds7 _index_bugs is an index and not a check: a junk entry and an "
           "id-less bug are skipped silently, because bugs[]'s own rules "
           "belong to _check_bugs and two messages about one defect are how "
           "they start disagreeing",
           M._index_bugs({"bugs": _ds_bug_rows})
           == {"bug_list": _ds_bug_rows, "bug_ids": ["BUG-1"],
               "bug_by_id": {"BUG-1": _ds_bug_rows[0]}})
    _f_ds8, _w_ds8 = M._check_unique_ids(
        {"phase_ids": ["P0"], "task_ids": ["P0.1"], "bug_ids": ["P0.1"]})
    record("ds8 phases, tasks and bugs share ONE id namespace - a bug wearing "
           "a task's id IS a duplicate, and a _live_ids that unioned only the "
           "first two would report nothing here",
           _f_ds8 == ["duplicate id: P0.1"] and _w_ds8 == [], (_f_ds8, _w_ds8))

    _f_ds9, _w_ds9 = M._check_refs_and_cycles(
        [{"id": "P0", "title": "p", "status": "pending", "tasks": [
            {"id": "P0.1", "title": "t", "status": "pending",
             "blockedBy": ["P9"], "dependsOn": ["P9"]}]}],
        {"phase_ids": ["P0", "P9"], "task_ids": ["P0.1"]})
    record("ds9 the two universes stay apart across the seam: blockedBy may "
           "name a PHASE, dependsOn may name only a task - so one id in both "
           "fields is exactly one finding, and either way of swapping the "
           "arguments changes which one",
           _f_ds9 == ["task P0.1: dependsOn 'P9' does not resolve to a task"]
           and _w_ds9 == [], (_f_ds9, _w_ds9))

    _f_ds10, _w_ds10 = M._check_file_index(
        {"fileIndex": {"src/a.ts:10-20": ["P0.1"]}},
        {"task_ids": ["P0.1"], "task_files": {"P0.1": ["src/b.ts"]}})
    record("ds10 _check_file_index takes the BACKWARD direction from the index "
           "it is handed rather than re-walking phases it never sees - and the "
           "line suffix is still stripped on the way in, so the forward half "
           "of this fixture stays clean",
           _f_ds10 == ["task P0.1: file 'src/b.ts' missing from fileIndex "
                       "(fileIndex['src/b.ts'] must include 'P0.1')"]
           and _w_ds10 == [], (_f_ds10, _w_ds10))

    _ds_bug_m = {"bugs": [{"id": "BUG-1", "title": "b", "status": "open",
                           "taskId": "P0.1"}]}
    _ds_bix = {"task_ids": ["P0.1"], "task_by_id": {"P0.1": {"bugId": "BUG-2"}},
               "bug_links": []}
    _ds_bix.update(M._index_bugs(_ds_bug_m))
    _f_ds11, _w_ds11 = M._check_bugs(_ds_bug_m, _ds_bix)
    record("ds11 _check_bugs decides reciprocity from the index's task OBJECT, "
           "so a bug pointing at a task that points somewhere else is caught "
           "from the bug's end - the half neither record can see alone",
           len(_f_ds11) == 1 and "link must be reciprocal" in _f_ds11[0]
           and "'BUG-2'" in _f_ds11[0] and _w_ds11 == [], (_f_ds11, _w_ds11))

    _ds_prop_m = {"bugs": [{"id": "BUG-1", "title": "b", "status": "open"}],
                  "proposals": [{"id": "PROP-1", "name": "n",
                                 "status": "proposed",
                                 "payload": {"phase": {
                                     "id": "BUG-1", "title": "T",
                                     "status": "pending", "tasks": []}}}]}
    _ds_pix = {"phase_ids": [], "task_ids": []}
    _ds_pix.update(M._index_bugs(_ds_prop_m))
    _f_ds12, _w_ds12 = M._check_proposals(_ds_prop_m, _ds_pix)
    record("ds12 a parked payload id is measured against the WHOLE live "
           "namespace, bugs included - _live_ids is one function, so the "
           "reserved-id rule and the duplicate-id sweep cannot drift apart "
           "about what 'live' means",
           any("reserved id 'BUG-1' collides" in x for x in _f_ds12),
           (_f_ds12, _w_ds12))

    # The uniform contract, asserted over every direct child at once: a new
    # piece that returns a bare list (or writes into an argument) is named here
    # rather than discovered by the orchestrator folding None.
    _ds_m = _valid_manifest()
    # Snapshotted HERE and not beside ds14, which is where it was first written:
    # the pieces are already called once by ds13 below, so a snapshot taken after
    # that loop records the damage as the baseline and ds14 passes over a
    # manifest a piece really did edit. Caught by mutating _check_areas to
    # `setdefault("proposals", [])` and watching ds14 stay green.
    _ds_before = json.dumps(_ds_m, sort_keys=True)
    _ds_index, _, _ = M._walk_phases(_ds_m["phases"])
    _ds_index.update(M._index_bugs(_ds_m))
    _ds_calls = [("_check_meta", (_ds_m,)),
                 ("_check_areas", (_ds_m,)),
                 ("_check_unique_ids", (_ds_index,)),
                 ("_check_refs_and_cycles", (_ds_m["phases"], _ds_index)),
                 ("_check_model_typos", (_ds_m,)),
                 ("_check_skills", (_ds_m,)),
                 ("_check_skill_typos", (_ds_m,)),
                 ("_check_file_index", (_ds_m, _ds_index)),
                 ("_check_bugs", (_ds_m, _ds_index)),
                 ("_check_proposals", (_ds_m, _ds_index))]
    _ds_wrong = []
    for _n, _a in _ds_calls:
        _pair = getattr(M, _n)(*_a)
        if not (isinstance(_pair, tuple) and len(_pair) == 2
                and all(isinstance(_half, list) for _half in _pair)):
            _ds_wrong.append((_n, _pair))
    record("ds13 every direct child of validate() answers with the SAME "
           "(findings, warnings) pair - the four that used to be handed a list "
           "to write into included - so the orchestrator folds them all one "
           "way and a piece growing a hard rule needs no new signature: %r"
           % (_ds_wrong,),
           not _ds_wrong)
    for _n, _a in _ds_calls:
        getattr(M, _n)(*_a)
    record("ds14 ...and none of them writes to the manifest it was handed. It "
           "reads vacuous beside ds13 and is the only case that fails if a "
           "piece starts normalizing the document it was given to inspect",
           json.dumps(_ds_m, sort_keys=True) == _ds_before)
    _ds_dirty = copy.deepcopy(_valid_manifest())
    _ds_dirty["phases"][0]["tasks"][0]["status"] = "doing"
    _ds_one = M.validate(copy.deepcopy(_ds_dirty))
    _ds_two = M.validate(copy.deepcopy(_ds_dirty))
    record("ds15 validate() is repeatable across calls: one finding stays one "
           "finding the second time round, which is the case that goes red if "
           "any piece ever parks its answer in module state",
           _ds_one == _ds_two and len(_ds_one[0]) == 1, _ds_one)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_validate_manifest.py --selftest\n")
    raise SystemExit(2)
