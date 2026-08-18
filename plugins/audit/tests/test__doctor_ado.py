#!/usr/bin/env python3
"""
The cases for `_doctor_ado.py` — the ADO connector's OPERATIONAL half.

`shutil.which` is stubbed throughout, and it is not optional here: the transport
rows depend on whether THIS machine has `az` installed, and a suite that asked
the real PATH would say different things on a laptop and on a CI runner. The
stub is also what keeps the cases offline — the real `az extension list` is a
subprocess, and a doctor that phoned ADO would be a doctor that needs
credentials.

The SHAPE of `meta.ado` is `_manifest_ado.check_ado_meta`'s job and reaches the
report through `check_manifest`. Nothing here re-checks it; a non-dict block is
asserted to be SILENT, because a second row for one defect is the "second place
status lives" problem one size down.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import shutil
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _doctor_ado as M                            # noqa: E402
import _doctor_report as base                      # noqa: E402  (the collector)


def _levels(rep, name):
    return [r["level"] for r in rep.rows if r["check"] == name]


def _detail(rep, name):
    return " ".join(r["detail"] for r in rep.rows if r["check"] == name)


def _manifest(ado=None, task_link=None, phase_link=None, bug_link=None):
    task = {"id": "P1.1", "title": "t", "status": "done", "files": ["a.py"],
            "tests": {"mode": "regression"}, "risk": "low"}
    if task_link is not None:
        task["ado"] = task_link
    phase = {"id": "P1", "title": "one", "status": "done", "tasks": [task]}
    if phase_link is not None:
        phase["ado"] = phase_link
    bugs = []
    if bug_link is not None:
        bugs = [{"id": "BUG-1", "title": "b", "status": "open",
                 "ado": bug_link}]
    meta = {"version": 2, "title": "t"}
    if ado is not False:
        meta["ado"] = ado
    return {"meta": meta, "phases": [phase], "bugs": bugs,
            "fileIndex": {"a.py": ["P1.1"]}}


# --- cases --------------------------------------------------------------------
def _cases(check):
    def run(manifest, az=None):
        """`az=None` means az is not on PATH; a string means it is."""
        rep = base.Report()
        saved = shutil.which

        def fake(name, *a, **k):
            return az if name == "az" else saved(name, *a, **k)
        shutil.which = fake
        try:
            M.check_ado(rep, "/nowhere", manifest)
        finally:
            shutil.which = saved
        return rep

    rep = run(_manifest(ado=False))
    check("da1 no `meta.ado` is an ok line SAYING the connector is off, not "
          "silence: 'not configured' is an answer someone is looking for: %r"
          % (_detail(rep, "ado"),),
          _levels(rep, "ado") == ["OK"]
          and "not configured" in _detail(rep, "ado"))
    check("da2 ...and it stops there - no transport row, no state-map row, no "
          "links row. A connector that is off has nothing to be diagnosed "
          "about: %r" % ([r["check"] for r in rep.rows],),
          [r["check"] for r in rep.rows] == ["ado"])

    rep = run(_manifest(ado="nope"))
    check("da3 a non-object `meta.ado` says NOTHING here: the shape is "
          "`check_ado_meta`'s finding and `check_manifest` already carries it, "
          "and two rows for one defect is one status living in two places: %r"
          % (rep.rows,), rep.rows == [])

    rep = run(_manifest(ado={"organization": "o", "project": "p"}))
    check("da4 a configured connector names the org and project, and the "
          "switches that are in effect - a row that said only 'on' would be a "
          "verdict with no basis: %r" % (_detail(rep, "ado"),),
          _levels(rep, "ado") == ["OK"]
          and "org o, project p" in _detail(rep, "ado")
          and "echo on" in _detail(rep, "ado")
          and "PBI-per-phase on" in _detail(rep, "ado"))
    check("da5 ...and an untyped PBI says the type is auto-detected at the first "
          "phase push, rather than reading as a gap: %r" % (_detail(rep, "ado"),),
          "auto-detected" in _detail(rep, "ado"))

    rep = run(_manifest(ado={"organization": "o", "project": "p",
                             "types": {"pbi": "Product Backlog Item"}}))
    check("da6 ...and a typed one drops that note. THE OTHER-DIRECTION CASE: it "
          "goes red if the note becomes unconditional and every configured "
          "project is told its type is unknown: %r" % (_detail(rep, "ado"),),
          "auto-detected" not in _detail(rep, "ado"))

    rep = run(_manifest(ado={"organization": "o", "project": "p",
                             "enabled": False}))
    check("da7 `enabled: false` is a WARNING - links are kept and status still "
          "reports them, but push/pull and the echo do nothing: %r"
          % (_detail(rep, "ado"),),
          _levels(rep, "ado") == ["WARNING"]
          and "DISABLED" in _detail(rep, "ado"))

    rep = run(_manifest(ado={"organization": "o", "project": "p",
                             "echo": False}))
    check("da8 `echo: false` is not a disabled connector - the row still reads "
          "OK and says 'echo off'. The fixture separates the two switches, "
          "which a version folding them together cannot survive: %r"
          % (_detail(rep, "ado"),),
          _levels(rep, "ado") == ["OK"] and "echo off" in _detail(rep, "ado"))

    rep = run(_manifest(ado={"organization": "o", "project": "p",
                             "sprint": {"team": "T", "mode": "current"}}))
    check("da9 a sprint block names the TEAM it resolves through; without one "
          "the row says static (iterationPath): %r" % (_detail(rep, "ado"),),
          "resolves team 'T'" in _detail(rep, "ado"))
    check("da10 ...and the static case says so instead: %r"
          % (_detail(run(_manifest(ado={"organization": "o", "project": "p"})),
                     "ado"),),
          "static (iterationPath)" in _detail(
              run(_manifest(ado={"organization": "o", "project": "p"})), "ado"))

    # --- the two advisory rows -------------------------------------------
    rep = run(_manifest(ado={"organization": "o", "project": "p"}))
    check("da11 no `stateMap` draws the Agile-only warning: the shipped defaults "
          "name Agile states, a Scrum project uses To Do/In Progress/Done, and "
          "the row says 'advisory only: real states live in ADO': %r"
          % (_detail(rep, "ado state map"),),
          _levels(rep, "ado state map") == ["WARNING"]
          and "Advisory only" in _detail(rep, "ado state map"))
    rep = run(_manifest(ado={"organization": "o", "project": "p",
                             "stateMap": {"task": {"done": "Closed"}}}))
    check("da12 ...and a project that HAS set one is not told about it. THE "
          "OTHER-DIRECTION CASE for an advisory that would otherwise nag every "
          "run: %r" % (rep.rows,),
          _levels(rep, "ado state map") == [])

    rep = run(_manifest(ado={"organization": "o", "project": "p",
                             "onComplete": {"remainingWork": 0}}))
    check("da13 a configured `onComplete.remainingWork` warns that both stock "
          "processes force-clear the field at done, so the write degrades to "
          "state-only there: %r" % (_detail(rep, "ado remaining work"),),
          _levels(rep, "ado remaining work") == ["WARNING"]
          and "force-clear" in _detail(rep, "ado remaining work"))
    rep = run(_manifest(ado={"organization": "o", "project": "p"}))
    check("da14 ...and a connector that never configured it hears nothing: %r"
          % (_levels(rep, "ado remaining work"),),
          _levels(rep, "ado remaining work") == [])

    # --- transport --------------------------------------------------------
    rep = run(_manifest(ado={"organization": "o", "project": "p"}), az=None)
    _fix = " ".join(r["fix"] or "" for r in rep.rows
                    if r["check"] == "ado transport")
    check("da15 az missing is a WARNING and never a finding: the MCP tools can "
          "still carry an interactive session, so a headless gap is not a "
          "broken repo: %r" % (_detail(rep, "ado transport"),),
          _levels(rep, "ado transport") == ["WARNING"]
          and "not on PATH" in _detail(rep, "ado transport"))
    check("da15b ...and the FIX carries the extension install, not only the CLI "
          "one - `az` alone cannot talk to ADO, and a fix that stopped at "
          "azure-cli would send the reader back for a second round: %r"
          % (_fix,),
          "az extension add --name azure-devops" in _fix)

    # --- what the links prove --------------------------------------------
    rep = run(_manifest(ado={"organization": "o", "project": "p"}))
    check("da16 no linked item is an ok line saying so IN THOSE WORDS - "
          "'configuration, not evidence' is the distinction the row exists for: "
          "%r" % (_detail(rep, "ado links"),),
          "configuration, not evidence" in _detail(rep, "ado links"))

    rep = run(_manifest(ado={"organization": "o", "project": "p"},
                        task_link={"id": 1,
                                   "lastSyncedAt": "2026-01-01T00:00:00Z"},
                        phase_link={"id": 2,
                                    "lastSyncedAt": "2026-03-03T00:00:00Z"},
                        bug_link={"id": 3,
                                  "lastSyncedAt": "2026-02-02T00:00:00Z"}))
    check("da17 links are counted per KIND, and a phase link is counted even "
          "though `iter_tasks` yields nothing for a phase - the two passes are "
          "what make that true: %r" % (_detail(rep, "ado links"),),
          "1 task(s), 1 bug(s), 1 phase(s) linked" in _detail(rep, "ado links"))
    check("da18 ...and the newest `lastSyncedAt` wins across all three kinds. "
          "The three timestamps are deliberately out of visiting order, so a "
          "version taking the min or the last-seen names a different one: %r"
          % (_detail(rep, "ado links"),),
          "newest sync 2026-03-03T00:00:00Z" in _detail(rep, "ado links"))

    rep = run(_manifest(ado={"organization": "o", "project": "p"},
                        task_link={"id": True}))
    check("da19 `\"id\": true` is NOT a link. bool is an int subclass, so the "
          "isinstance test alone would count it, and a connector reporting one "
          "linked task where there are none is worse than reporting zero: %r"
          % (_detail(rep, "ado links"),),
          "no item linked yet" in _detail(rep, "ado links"))
    check("da20 ...and neither is a STRING id, which is what a hand-edited "
          "manifest most often carries: %r"
          % (_detail(run(_manifest(ado={"organization": "o", "project": "p"},
                                   task_link={"id": "7"})), "ado links"),),
          "no item linked yet" in _detail(
              run(_manifest(ado={"organization": "o", "project": "p"},
                            task_link={"id": "7"})), "ado links"))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_ado.py --selftest\n")
    raise SystemExit(2)
