#!/usr/bin/env python3
"""
The cases for `_evidence_view.py` - the report's only read of the evidence ledger.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `_report_page` and `_report_md` are here because the FIXTURE
is here: one plan, one ledger, one temp directory, and the cases that ask what the
load returns sit beside the cases that ask what the page does with it. Splitting
them would mean building the same seven-task plan twice and letting the two drift.

WHAT EVERY CASE IN THIS FILE IS GUARDING AGAINST IS A MERGE. Each of `ran`,
`treeMutated` and `coverage` is THREE-VALUED, and every one of them has a wrong
answer that a truthy test produces silently: a count nobody could take rendered as
zero, a tree nobody could describe rendered as clean, a coverage question nobody
could ask rendered as "no overlap". So the cases come in threes over ONE fixture
rather than in ones - `is None`, empty, and populated are asserted to differ from
each other, which is the only shape in which a collapse fails.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import base64
import json
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _evidence_view as M                         # noqa: E402
import _manifest_io                                # noqa: E402
import _output                                     # noqa: E402
import _report_html                                # noqa: E402
import _report_page                                # noqa: E402
import _report_md                                  # noqa: E402
import _status_facts                               # noqa: E402


# --- the fixture ---------------------------------------------------------------
def _plan():
    """One plan carrying every state the badge vocabulary can reach.

    Written as a literal rather than generated: the point of the fixture is that a
    reader can see, in one place, which task is supposed to answer which way.
    """
    return {
        "meta": {"version": 2, "title": "evidence", "repo": "r"},
        "bugs": [
            {"id": "B1", "title": "linked", "status": "open", "severity": "high",
             "taskId": "P1.2"},
            {"id": "B2", "title": "unlinked", "status": "open", "severity": "low"},
            {"id": "B3", "title": "points at nothing", "status": "open",
             "severity": "low", "taskId": "NOPE"},
        ],
        "phases": [
            {"id": "P1", "title": "One", "status": "in_progress",
             "testGate": ["make test"],
             "testEvidence": {"runId": "R-PH", "status": "passed",
                              "at": "2026-08-01T10:00:00Z"},
             "tasks": [
                 {"id": "P1.1", "title": "green", "status": "done",
                  "tests": {"mode": "tdd", "gate": ["pytest"]},
                  "testEvidence": {"runId": "R1", "status": "passed",
                                   "at": "2026-08-01T09:00:00Z"}},
                 {"id": "P1.2", "title": "red", "status": "in_progress",
                  "tests": {"mode": "tdd", "gate": ["pytest"]},
                  "testEvidence": {"runId": "R2", "status": "failed",
                                   "at": "2026-08-01T09:10:00Z"}},
                 {"id": "P1.3", "title": "nothing knowable", "status": "done",
                  "tests": {"mode": "tdd", "gate": ["pytest"]},
                  "testEvidence": {"runId": "R3", "status": "passed",
                                   "at": "2026-08-01T09:20:00Z"}},
                 {"id": "P1.4", "title": "nothing ran", "status": "done",
                  "tests": {"mode": "tdd", "gate": ["pytest"]},
                  "testEvidence": {"runId": "R4", "status": "no-checks",
                                   "at": "2026-08-01T09:30:00Z"}},
                 {"id": "P1.5", "title": "configured, never run",
                  "status": "pending",
                  "tests": {"mode": "tdd", "gate": ["pytest"]}},
                 {"id": "P1.6", "title": "points at a run nobody has",
                  "status": "done",
                  "tests": {"mode": "tdd", "gate": ["pytest"]},
                  "testEvidence": {"runId": "GONE", "status": "passed",
                                   "at": "2026-08-01T09:40:00Z"}},
             ]},
            # A phase with NO gate of its own, so its task's "no gate anywhere"
            # answer is a property of both declarations and not of one.
            {"id": "P2", "title": "Two", "status": "pending",
             "tasks": [{"id": "P2.1", "title": "ungated", "status": "pending"}]},
        ],
    }


def _rows():
    """The ledger behind that plan, one row per recorded run.

    THE THREE-VALUED FIELDS ARE SPREAD ACROSS TASKS ON PURPOSE. R1 is clean in
    every dimension, R2 populated in every dimension, R3 `None` in every dimension
    and R4 the positive zero - so any case that compares two of them is comparing
    exactly one distinction at a time.
    """
    return [
        {"v": 1, "runId": "R1", "ts": "2026-08-01T09:00:00Z", "scope": "task",
         "taskId": "P1.1", "phaseId": "P1", "status": "passed", "attempt": 1,
         "durationMs": 1200, "failed": [],
         "steps": [{"name": "unit", "exit": 0, "ran": 12, "durationMs": 1100,
                    "command": "pytest"}],
         "testedState": {"head": "abc1234def", "headBasis": "git rev-parse HEAD"},
         "observations": {"ranTotal": 12, "countsBasis": "the summary line",
                          "treeMutated": [], "treeBasis": "git described the tree",
                          "coverage": ["a.py"], "coverageBasis": "paths printed"},
         "treeMutated": []},
        # ...and an OLDER run of the same task, which is what History is for.
        {"v": 1, "runId": "R0", "ts": "2026-07-30T09:00:00Z", "scope": "task",
         "taskId": "P1.1", "phaseId": "P1", "status": "failed", "failed": ["unit"],
         "steps": [{"name": "unit", "exit": 1, "ran": 12, "durationMs": 900,
                    "commandSha256": "deadbeefcafe", "program": "pytest"}],
         "observations": {"ranTotal": 12, "treeMutated": [], "treeBasis": "b",
                          "coverage": ["a.py"], "coverageBasis": "c"},
         "treeMutated": []},
        {"v": 1, "runId": "R2", "ts": "2026-08-01T09:10:00Z", "scope": "task",
         "taskId": "P1.2", "phaseId": "P1", "status": "failed", "attempt": 2,
         "durationMs": 2200, "failed": ["unit"],
         "steps": [{"name": "unit", "exit": 1, "ran": 30, "durationMs": 2100,
                    "command": "pytest"}],
         "observations": {"ranTotal": 30, "treeMutated": ["src/x.py"],
                          "treeBasis": "git described the tree",
                          "coverage": [], "coverageBasis": "nothing owned"},
         "treeMutated": ["src/x.py"]},
        {"v": 1, "runId": "R3", "ts": "2026-08-01T09:20:00Z", "scope": "task",
         "taskId": "P1.3", "phaseId": "P1", "status": "passed", "durationMs": 50,
         "failed": [],
         "steps": [{"name": "lint", "exit": 0, "ran": None, "durationMs": 50,
                    "command": "ruff check"}],
         "observations": {"ranTotal": None, "treeMutated": None,
                          "treeBasis": "git could not describe the tree",
                          "coverage": None, "coverageBasis": "no paths printed"},
         "treeMutated": None},
        {"v": 1, "runId": "R4", "ts": "2026-08-01T09:30:00Z", "scope": "task",
         "taskId": "P1.4", "phaseId": "P1", "status": "no-checks", "durationMs": 40,
         "failed": [],
         "steps": [{"name": "unit", "exit": 0, "ran": 0, "durationMs": 40,
                    "command": "pytest -k nope"}],
         "observations": {"ranTotal": 0, "treeMutated": [], "treeBasis": "b",
                          "coverage": ["a.py"], "coverageBasis": "c"},
         "treeMutated": []},
        {"v": 1, "runId": "R-PH", "ts": "2026-08-01T10:00:00Z", "scope": "phase",
         "phaseId": "P1", "status": "passed", "durationMs": 500, "failed": [],
         "steps": [{"name": "gate", "exit": 0, "ran": 99, "durationMs": 500,
                    "command": "make test"}],
         "observations": {"ranTotal": 99, "treeMutated": [], "treeBasis": "b",
                          "coverage": ["a.py"], "coverageBasis": "c"},
         "treeMutated": []},
    ]


def _write_project(root, plan, rows):
    """Write a plan and its ledger where `_evidence_io` will look for them."""
    audit = os.path.join(root, ".claude", "audit")
    os.makedirs(os.path.join(audit, "evidence"), exist_ok=True)
    path = os.path.join(audit, "audit-plan.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh)
    with open(os.path.join(audit, "evidence", "2026-08.t.jsonl"), "w",
              encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def _markup(doc):
    """The document without its scripts - the embedded base64 twin carries the
    whole Markdown page, so a substring pin about MARKUP must not read it."""
    return re.sub(r"(?is)<script\b.*?</script\s*>", "", doc)


def _body(doc):
    """...and without the inline <style> either, for the NEGATIVE pins.

    F-C-1 one surface over. `data-tev` and `dt3` are both written in the report's
    stylesheet, which ships inline in every document, so `"data-tev" not in doc`
    is false on a page that renders none of this feature - the check would have
    been asserting the CSS exists. A negative over the wrong region is the defect
    this repository keeps paying for, so the region is cut out and named."""
    return re.sub(r"(?is)<style\b.*?</style\s*>", "", _markup(doc))


def _flagset(view):
    return set(k for k, _w in view["flags"])


# --- cases --------------------------------------------------------------------
def _cases(check):
    root = _harness.fixture_root("evidence-view")
    plan, rows = _plan(), _rows()
    path = _write_project(root, plan, rows)
    ev = M.load_evidence(plan, path, project_dir=root)
    T = ev["tasks"]

    # --- the load, and the one predicate that keeps an old report identical ---
    bare = json.loads(json.dumps(plan))
    for phase in bare["phases"]:
        phase.pop("testEvidence", None)
        for task in phase["tasks"]:
            task.pop("testEvidence", None)
    bare_path = _write_project(os.path.join(root, "bare"), bare, rows)
    check("ev1 a plan that points at NO recorded run loads as None - the column "
          "is not earned, and a manifest written before the field existed "
          "renders as it did",
          M.load_evidence(bare, bare_path,
                          project_dir=os.path.join(root, "bare")) is None)
    check("ev1b SECOND DIRECTION: the same plan with ONE pointer restored loads "
          "a model - so ev1 is answering about the pointer and not about a "
          "missing ledger, a missing directory or an import that failed",
          isinstance(ev, dict) and isinstance(T.get("P1.1"), dict))
    # A gate DECLARED and never run must not earn the column on its own: `bare`
    # still carries `tests.gate` on five tasks and `testGate` on P1.
    check("ev1c ...and a plan that declares gates it has never run still loads "
          "None - reading a declaration instead of a pointer would put a column "
          "of 'No evidence' on every manifest ever written",
          any(t.get("tests", {}).get("gate")
              for p in bare["phases"] for t in p["tasks"])
          and M.load_evidence(bare, bare_path,
                              project_dir=os.path.join(root, "bare")) is None)

    # --- the two verdicts ------------------------------------------------------
    check("ev2 a passing run renders as Passed, and the failing one over the "
          "SAME load renders as Failed - one fixture, two answers, so neither "
          "can be a constant",
          (T["P1.1"]["key"], T["P1.1"]["label"]) == ("passed", "Passed")
          and (T["P1.2"]["key"], T["P1.2"]["label"]) == ("failed", "Failed"))

    # --- `ran` is three-valued -------------------------------------------------
    check("ev3 a run whose count is NOT KNOWABLE says so and earns the "
          "'checks unknown' marker",
          "checks-unknown" in _flagset(T["P1.3"])
          and "not knowable" in _report_html._tev_checks_text(T["P1.3"]["row"]))
    check("ev3b ...and it never renders as a count. `0 check(s)` for a null is "
          "the exact merge this arm exists to refuse",
          "0" not in _report_html._tev_checks_text(T["P1.3"]["row"]))
    check("ev3c PAIRED NEGATIVE: a POSITIVE ZERO is a different answer - the "
          "status is No checks ran, the marker is absent because the count was "
          "reported, and the sentence says none ran",
          T["P1.4"]["key"] == "no-checks"
          and T["P1.4"]["label"] == "No checks ran"
          and "checks-unknown" not in _flagset(T["P1.4"])
          and _report_html._tev_checks_text(T["P1.4"]["row"]).startswith("none ran"))
    check("ev3d ...and a real count is neither of those two",
          _report_html._tev_checks_text(T["P1.1"]["row"]).startswith("12 ran")
          and "checks-unknown" not in _flagset(T["P1.1"]))

    # --- `treeMutated` is three-valued -----------------------------------------
    check("ev4 treeMutated None and treeMutated [] render DIFFERENTLY: one is "
          "'tree unknown', the other carries no marker at all",
          "tree-unknown" in _flagset(T["P1.3"])
          and "tree-unknown" not in _flagset(T["P1.1"])
          and "tree-mutated" not in _flagset(T["P1.1"]))
    check("ev4b ...and a populated list is the third answer, not the second",
          "tree-mutated" in _flagset(T["P1.2"])
          and "tree-unknown" not in _flagset(T["P1.2"]))
    check("ev4c the drawer says the same three things in words, and the two "
          "empty-looking ones do not share a sentence",
          _report_html._tev_paths_text(None, "unknown", "unchanged", "b", 0)
          != _report_html._tev_paths_text([], "unknown", "unchanged", "b", 0)
          and "unknown" in _report_html._tev_paths_text(None, "unknown",
                                                        "unchanged", "b", 0)
          and "unchanged" in _report_html._tev_paths_text([], "unknown",
                                                          "unchanged", "b", 0))

    # --- coverage is three-valued too ------------------------------------------
    check("ev5 coverage None is 'coverage unknown' and coverage [] is 'no "
          "overlap' - the question nobody asked and the question answered no",
          "coverage-unknown" in _flagset(T["P1.3"])
          and "no-overlap" not in _flagset(T["P1.3"])
          and "no-overlap" in _flagset(T["P1.2"])
          and "coverage-unknown" not in _flagset(T["P1.2"]))
    check("ev5b ...and a real overlap earns neither",
          not ({"no-overlap", "coverage-unknown"} & _flagset(T["P1.1"])))

    # --- the three ways there is no run ----------------------------------------
    check("ev6 a task with a configured gate and no pointer is No evidence",
          (T["P1.5"]["key"], T["P1.5"]["label"]) == ("no-evidence", "No evidence"))
    check("ev6b PAIRED: a task with no gate at either level is a DIFFERENT "
          "sentence, not the same grey - different key, different words, "
          "different reason",
          T["P2.1"]["key"] == "no-gate"
          and T["P2.1"]["label"] == "No gate configured"
          and T["P2.1"]["label"] != T["P1.5"]["label"]
          and T["P2.1"]["why"] != T["P1.5"]["why"])
    check("ev6c ...and the third of the three: a pointer naming a run no row "
          "carries is neither of the two above",
          T["P1.6"]["key"] == "dangling"
          and T["P1.6"]["label"] == "Pointer without evidence"
          and len({T["P1.5"]["key"], T["P2.1"]["key"], T["P1.6"]["key"]}) == 3)
    check("ev6d the phase's own gate is what makes P1.5 'configured' - the task "
          "declares one too, so the case that proves the FALLBACK is P1.6 in a "
          "phase with a gate against P2.1 in a phase without one",
          _report_html.tev_configured({}, plan["phases"][0]) is True
          and _report_html.tev_configured({}, plan["phases"][1]) is False)

    # --- history ---------------------------------------------------------------
    check("ev7 the runs before this one are attached, newest first, and the "
          "CURRENT run is not among them",
          [r["runId"] for r in T["P1.1"]["history"]] == ["R0"]
          and T["P1.2"]["history"] == [])
    check("ev7b ...and the history is rendered inside a <details class=\"more\">, "
          "which the print sheet already forces open",
          'details class="more' in _report_html._tev_history(T["P1.1"])
          and "R0" in _report_html._tev_history(T["P1.1"])
          and _report_html._tev_history(T["P1.2"]) == "")

    # --- the phase: BOTH, labelled apart ---------------------------------------
    P = ev["phases"]["P1"]
    check("ev8 a phase carries its OWN sign-off run and an aggregate over its "
          "tasks, as two values - merging them would claim a measurement "
          "nobody made",
          P["own"]["key"] == "passed"
          and dict((k, n) for k, _l, n in P["rollup"])
          == {"passed": 2, "failed": 1, "no-checks": 1, "dangling": 1,
              "no-evidence": 1})
    check("ev8b ...and the two are LABELLED APART in the markup, not run "
          "together into one number",
          "sign-off" in _report_html._tev_phase_marks(P)
          and "tasks" in _report_html._tev_phase_marks(P))
    check("ev8c a phase with no gate and no pointer still gets an entry, and "
          "its own mark says 'No gate configured' rather than borrowing its "
          "tasks' answer",
          ev["phases"]["P2"]["own"]["key"] == "no-gate")

    # --- the chip vocabularies -------------------------------------------------
    check("ev9 the status chips offer only the statuses this plan REACHED, in "
          "vocabulary order - a chip for a status no row reached is a control "
          "whose every use is a no-op",
          ev["keys"] == ["passed", "failed", "no-checks", "dangling",
                         "no-evidence", "no-gate"])
    check("ev9b ...and the observation chips are a SECOND list, holding markers "
          "and never statuses",
          ev["flags"] == ["tree-mutated", "tree-unknown", "no-overlap",
                          "coverage-unknown", "checks-unknown"]
          and not (set(ev["flags"]) & set(ev["keys"])))
    check("ev9c an unrecognised word keeps its place at the END rather than "
          "being sorted in among words this build understands",
          M._ordered({"passed", "zz-new", "failed"},
                     _report_html.TEV_ORDER) == ["passed", "failed", "zz-new"])

    # --- a ledger that is not there --------------------------------------------
    empty = _harness.fixture_root("evidence-view-empty")
    epath = _write_project(empty, plan, [])
    eev = M.load_evidence(plan, epath, project_dir=empty)
    check("ev10 a plan whose pointers name runs this checkout does not hold is "
          "DANGLING everywhere, not clean and not silent - and the phase's own "
          "pointer answers the same way",
          isinstance(eev, dict)
          and set(v["key"] for v in eev["tasks"].values())
          == {"dangling", "no-evidence", "no-gate"}
          and eev["phases"]["P1"]["own"]["key"] == "dangling")
    check("ev10b SECOND DIRECTION: with the ledger present those same three "
          "tasks answer with their runs' own words, so ev10 is about the "
          "missing rows and not about the pointers",
          T["P1.1"]["key"] == "passed" and eev["tasks"]["P1.1"]["key"] == "dangling")

    # --- which manifest's record ------------------------------------------------
    proj, cfg = M._project_and_config(path, root)
    check("ev11 the record is resolved from the manifest actually being "
          "rendered, not from the one a project's config names - a report of "
          "one plan must never show another plan's runs",
          proj == root
          and cfg["manifestPath"].replace("\\", "/")
          == ".claude/audit/audit-plan.json")

    # --- the rendered page ------------------------------------------------------
    summ = _status_facts.rollup(plan, [], [])
    doc = _report_page.render_html(plan, summ, "b", None, evidence=ev)
    mk = _markup(doc)
    plain = _report_page.render_html(plan, summ, "b", None)
    plain_body = _body(plain)
    check("ev12 INERT WITHOUT A MODEL: the same plan rendered with no evidence "
          "carries none of this feature in its markup - no attribute, no column, "
          "no chip row, no third drawer group. That is what keeps a manifest "
          "pointing at no run rendering as it always did, which is what "
          "tools/check-rendered-artifacts.py compares byte for byte",
          0 < len(plain_body) < len(plain)
          and "data-tev" not in plain_body
          and "test evidence" not in plain_body
          and "audit-tev" not in plain_body
          and "dt3" not in plain_body
          # The header too, and it is a separate clause because it fails on its
          # own input: a column earned from the POINTER alone renders a header
          # and a row of em dashes while carrying no attribute, no chip and no
          # drawer group - so every clause above stays true over it.
          and "<th data-col=\"tests\">" not in plain_body
          and plain != doc)
    check("ev12b ...and with the model it carries a column, earned the way "
          "every other optional column is",
          '<th data-col="tests">test gate</th>' in mk
          and "tests" in _report_page._present_columns(plan, ev)
          and "tests" not in _report_page._present_columns(bare, ev)
          and "tests" not in _report_page._present_columns(plan))
    check("ev13 every task row carries BOTH filter axes as separate attributes, "
          "and a task whose run observed nothing carries only the status one",
          'data-tev="failed" data-tev-flags="tree-mutated no-overlap"' in mk
          and 'data-tev="passed"' in mk
          and mk.count("data-tev-flags=") == 2)
    check("ev14 the drawer grows a THIRD labelled group rather than a second "
          "disclosure mechanism, and the two it already had are untouched",
          mk.count("<h4>test evidence</h4>") == 7
          and mk.count("<h4>meta</h4>") == 7
          and mk.count("<h4>task details</h4>") == 7
          and 'class="dtwrap dt3"' in mk)
    check("ev14b PAIRED NEGATIVE: without a model the drawer is still two "
          "groups and the wrapper carries no third-column modifier",
          "<h4>test evidence</h4>" not in plain_body
          and 'class="dtwrap"' in plain_body)
    check("ev15 the chips are SERVER-RENDERED under both ids, so a printed page "
          "and a reader with scripting off still see what can be filtered",
          'id="audit-tev"' in mk and 'id="audit-tevf"' in mk
          and 'class="fchip" data-tev="passed"' in mk
          and 'class="fchip" data-tevf="tree-mutated"' in mk)
    check("ev15b ...and they are humanised out of the evidence vocabulary, not "
          "shown as the machine keys the filter compares",
          ">No checks ran</button>" in mk and ">no-checks</button>" not in mk)
    check("ev16 a bug's evidence is DERIVED from its fixing task and carries "
          "the provenance that says so",
          "via P1.2" in mk
          and _report_html.tev_bug_view(plan["bugs"][0], T)[0] is T["P1.2"])
    check("ev16b ...and the two ways there is nothing to derive from are "
          "different sentences: no fix task at all, and a fix task this plan "
          "does not carry",
          "no fix task yet" in mk
          and _report_html.tev_bug_view(plan["bugs"][1], T)[1] == "no fix task yet"
          and "not in this plan" in _report_html.tev_bug_view(plan["bugs"][2], T)[1])

    # --- the Markdown twin ------------------------------------------------------
    md = _report_md.render_md(plan, summ, None, ev)
    md_plain = _report_md.render_md(plan, summ, None)
    check("ev17 the twin gains ONE column and keeps the machine spelling - it "
          "is a data table read by machines, and the badge words belong where a "
          "person reads them",
          "| id | title | status | model | risk | commit | done | tests | ADO |" in md
          and "| no-checks |" in md and "| No checks ran |" not in md)
    check("ev17b PAIRED NEGATIVE: with no model the twin is the table it always "
          "was - no header cell, no separator column, no cell",
          "| id | title | status | model | risk | commit | done | ADO |" in md_plain
          and "| tests |" not in md_plain
          and "| no-checks |" not in md_plain
          and md_plain != md)
    _mark = 'window.AUDIT_MD_B64="'
    _i = doc.index(_mark) + len(_mark)
    _blob = doc[_i:doc.index('"', _i)]
    check("ev17c ...and the page's embedded twin is the SAME string the twin "
          "renders for the same plan and the same evidence, so the Download .md "
          "button cannot drift from the page it was downloaded off",
          base64.b64decode(_blob).decode("utf-8") == md)

    _shipped_cases(check)


# --- the artifact this repository actually ships ------------------------------
def _shipped_cases(check):
    """The worked example, read off the tree rather than built here.

    THE ONE INTEGRITY CLAIM NOTHING ELSE MAKES. `examples/acme-store/` is the
    first COMMITTED evidence ledger in this project, and its plan points into it
    from four separate shard files. A `runId` on either side that the other does
    not answer to renders as `Pointer without evidence` - a state the example
    would then be teaching a reader is normal - and until this case the only thing
    that would have noticed was a full re-render compared byte for byte, which is
    a release step and not a per-change one.

    Read through `load_evidence`, because that is the function the report uses:
    a case that walked the JSON itself would be asserting its own reading of the
    pointer rule rather than the one that ships.
    """
    root = os.path.join(_output.REPO_ROOT, "examples", "acme-store")
    plan_path = os.path.join(root, "audit-plan.json")
    if not os.path.isfile(plan_path):
        # A tree without the example is not a failing example. Said out loud,
        # because a case that quietly skipped would read as a passing one.
        check("ev18 SKIPPED: this tree carries no examples/acme-store to check",
              True)
        return
    plan = _manifest_io.load_manifest(plan_path)
    shipped = M.load_evidence(plan, plan_path, project_dir=root)
    check("ev18 the shipped example points at a ledger that is actually there - "
          "`load_evidence` returns None when no subject points at a run at all, "
          "and every claim below would then be about an empty document",
          shipped is not None and shipped["rows"] > 0
          and shipped["unreadable"] == 0,
          repr(None if shipped is None
               else (shipped["rows"], shipped["files"],
                     shipped["unreadable"])))
    _bad = sorted([t for t, v in shipped["tasks"].items()
                   if v["key"] == "dangling"]
                  + [q for q, e in shipped["phases"].items()
                     if e["own"]["key"] == "dangling"])
    check("ev18b ...and NOT ONE of its pointers dangles: %r" % (_bad,),
          _bad == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__evidence_view.py --selftest\n")
    raise SystemExit(2)
