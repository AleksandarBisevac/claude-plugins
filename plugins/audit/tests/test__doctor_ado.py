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

The `da24`–`da30` family is the same rule applied one question earlier: an item a
plan deliberately keeps off the board carries no link and never will, so the
links row owes that figure or it reports a plan working as designed as a plan
half of which was never pushed. `_ado_tracked` owns the answer and the task
inheritance — `da30` pins that this file holds no literal of the key at all, so
there is no second reading here to drift from the one `/audit:sync status`
prints. `da27` is the other direction, and `da29` holds the third value apart
from both of the others.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import shutil
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ado_tracked as TRACKED                     # noqa: E402  (FIELD, spelled once)
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


# A value no author would write, so `declared=None` can still mean "the key is
# present and holds null" if a case ever needs it. A plain default would make the
# absent case and the null case one case wearing two names.
_ABSENT = object()


def _plus_phase(manifest, pid, tasks=2, declared=_ABSENT):
    """`manifest` with one more phase, optionally declaring the key.

    `declared` is written through UNTOUCHED so a case can hand it a value that is
    not a boolean - the readable version of the third answer, where nothing has a
    basis to say either way. The phase carries TASKS because inheritance is the
    half that separates a row reading the module from a row reading the key.
    """
    phase = {"id": pid, "title": pid, "status": "pending",
             "tasks": [{"id": "%s.%d" % (pid, n + 1), "title": "t",
                        "status": "pending", "files": ["b.py"],
                        "tests": {"mode": "regression"}, "risk": "low"}
                       for n in range(tasks)]}
    if declared is not _ABSENT:
        phase[TRACKED.FIELD] = declared
    manifest["phases"].append(phase)
    return manifest


# --- cases --------------------------------------------------------------------
def _cases(check):
    def probed(manifest, az=None, probe=None):
        """`(rep, stderr_text)` - `run` plus the stream the notice goes to.

        `az=None` means az is not on PATH; a string means it is. `probe` stands
        in for `subprocess.run` on the branch that shells out, and it stays None
        for every case about the OFFLINE half - those pass `az=None`, so nothing
        here can reach the real Azure CLI. See this file's docstring, and
        `test_audit_doctor`'s note about `az` writing into the operator's home
        directory.

        The stderr text is returned rather than the rows alone because F158's
        progress notice is NOT a report row and cannot be one: every row is
        collected and rendered after all the checks have run, which is after the
        wait the notice is about.
        """
        rep = base.Report()
        saved_which = shutil.which
        saved_run = M.subprocess.run
        saved_err = sys.stderr
        sys.stderr = io.StringIO()

        def fake(name, *a, **k):
            return az if name == "az" else saved_which(name, *a, **k)
        shutil.which = fake
        if probe is not None:
            M.subprocess.run = probe
        try:
            M.check_ado(rep, "/nowhere", manifest)
            return rep, sys.stderr.getvalue()
        finally:
            shutil.which = saved_which
            M.subprocess.run = saved_run
            sys.stderr = saved_err

    def run(manifest, az=None):
        """The rows alone, for the cases that are not about the probe."""
        return probed(manifest, az=az)[0]

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

    # --- the probe says what it is waiting for, and for how long (F158) ---
    # `az` on PATH is the one place this read-only command waits on a
    # third-party CLI. The bound was always there; what was missing was saying
    # so, so these cases are about STDERR rather than about a row.
    _ado_on = {"organization": "o", "project": "p"}

    def _installed(*_a, **_k):
        class _Out(object):
            stdout = '[{"name": "azure-devops"}]'
        return _Out()

    def _times_out(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd=["az"], timeout=M.AZ_PROBE_SECONDS)

    def _explodes(*_a, **_k):
        raise OSError("no such file")

    _r_ok, _err_ok = probed(_manifest(ado=_ado_on), az="/usr/bin/az",
                            probe=_installed)
    check("da15c the probe announces itself BEFORE it waits, and names the "
          "bound it is waiting under - a bounded wait nobody is told about "
          "reads as a hang for exactly as long as the bound: %r" % (_err_ok,),
          "az extension list" in _err_ok
          and "bound %ds" % M.AZ_PROBE_SECONDS in _err_ok)
    check("da15d ...on STDERR, because `audit-doctor --json` prints one JSON "
          "document on stdout and a `Report` row could not carry this anyway "
          "- rows render after every check has run, which is after the wait: "
          "%r" % (_err_ok,),
          _err_ok.startswith("[audit]") and _err_ok.endswith("\n"))
    check("da15e ...and the probe still reports what it found, so the notice "
          "is an addition and not a replacement: %r"
          % (_detail(_r_ok, "ado transport"),),
          _levels(_r_ok, "ado transport") == ["OK"]
          and "azure-devops extension present" in _detail(_r_ok,
                                                          "ado transport"))
    # THE OTHER-DIRECTION CASE, and it is the one that looks vacuous: it passes
    # on the pre-fix code by construction, and it is the only case that fails if
    # the notice becomes unconditional and every doctor run on a machine with no
    # az announces a wait that never happens.
    _r_none, _err_none = probed(_manifest(ado=_ado_on), az=None)
    check("da15f no az means no wait, so there is nothing to announce - the "
          "notice must not fire on the branch that never shells out: %r"
          % (_err_none,),
          _err_none == "")
    _r_slow, _err_slow = probed(_manifest(ado=_ado_on), az="/usr/bin/az",
                                probe=_times_out)
    check("da15g the bound FIRING is its own row naming the number the reader "
          "just waited out - a slow CLI and a broken one are different facts "
          "wanting different next moves: %r" % (_detail(_r_slow,
                                                        "ado transport"),),
          _levels(_r_slow, "ado transport") == ["WARNING"]
          and "within %ds" % M.AZ_PROBE_SECONDS in _detail(_r_slow,
                                                           "ado transport"))
    check("da15h ...and it stays a WARNING: a doctor whose diagnostic timed "
          "out has learned nothing about the repo, which is not the same as "
          "having found something broken in it",
          not [r for r in _r_slow.rows if r["level"] == "FINDING"])
    _r_bad, _err_bad = probed(_manifest(ado=_ado_on), az="/usr/bin/az",
                              probe=_explodes)
    check("da15i ...while any OTHER failure keeps the old wording and carries "
          "the exception, rather than claiming a timeout that did not happen. "
          "The two rows are different strings, which is what makes the report "
          "tell them apart: %r" % (_detail(_r_bad, "ado transport"),),
          "no such file" in _detail(_r_bad, "ado transport")
          and "within %ds" % M.AZ_PROBE_SECONDS not in _detail(
              _r_bad, "ado transport"))
    check("da15j ...and the announced bound IS the bound the call is made "
          "with - one constant, because a wait announced as one length and "
          "cut at another is worse than an unannounced wait",
          M.PROBE_NOTICE.count("%d") == 1
          and M.announce_probe.__doc__ is not None
          and "timeout=AZ_PROBE_SECONDS" in _harness.module_source(M))

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

    # --- the origin split, which is answerable offline -------------------------
    rep = run(_manifest(ado={"organization": "o", "project": "p"},
                        task_link={"id": 1, "origin": "created"},
                        phase_link={"id": 2, "origin": "imported"},
                        bug_link={"id": 3}))
    _links = _detail(rep, "ado links")
    check("da21 the row splits the links by ORIGIN, so a reader can see how many "
          "of these cards this plugin made and how many it adopted - the "
          "provenance TAG cannot answer that, because a push merges it onto every "
          "item it touches: %r" % (_links,),
          "1 created here" in _links and "1 imported" in _links)
    check("da22 ...and the UNRECORDED ones are counted out loud. A link written "
          "before `origin` existed is not 'created' - defaulting it would put this "
          "plugin's name on a card somebody else made, which is the one wrong "
          "answer available here: %r" % (_links,),
          "1 of unknown origin" in _links
          and "link written before the field existed" in _links)
    check("da23 the three figures account for every counted link, so none can be "
          "quietly dropped into a category that is not printed",
          "3 phase(s)" not in _links
          and "1 task(s), 1 bug(s), 1 phase(s) linked" in _links)

    # --- who the plan keeps off the board, which links alone cannot show -------
    #
    # An item a plan deliberately keeps off a shared board carries no link and
    # never will, so a row printing links alone reports a plan working exactly as
    # designed as a plan half of which was never pushed. That is the figure
    # nobody would otherwise see, which is why it belongs on this row.
    _ado_on = {"organization": "o", "project": "p"}
    rep = run(_plus_phase(_manifest(ado=dict(_ado_on)), "P2", tasks=2,
                          declared=False))
    check("da24 a phase the plan keeps off the board is reported as its OWN "
          "figure, and its TASKS are counted with it - the inheritance comes "
          "from `_ado_tracked`, so a row that read the key on phases alone "
          "reports two fewer than the plan declares: %r"
          % (_detail(rep, "ado links"),),
          "3 item(s) the PLAN declares off the board" in _detail(rep, "ado links"))
    check("da25 ...and the row NAMES the key, so a reader who wants the other "
          "half of the plan off the board knows what to set rather than being "
          "told a number and left to search for it: %r"
          % (_detail(rep, "ado links"),),
          "phases[].%s: false" % (TRACKED.FIELD,) in _detail(rep, "ado links")
          and "tasks inherit" in _detail(rep, "ado links"))

    rep = run(_plus_phase(_manifest(ado=dict(_ado_on),
                                    task_link={"id": 1},
                                    phase_link={"id": 2},
                                    bug_link={"id": 3}),
                          "P2", tasks=2, declared=False))
    check("da26 the figure rides the LINKED branch too, not only the empty one - "
          "a plan that has pushed some of itself and keeps the rest off the "
          "board is exactly the reader this row is for: %r"
          % (_detail(rep, "ado links"),),
          "1 task(s), 1 bug(s), 1 phase(s) linked" in _detail(rep, "ado links")
          and "3 item(s) the PLAN declares off the board"
              in _detail(rep, "ado links"))

    rep = run(_plus_phase(_manifest(ado=dict(_ado_on)), "P2", tasks=2))
    check("da27 THE SECOND DIRECTION: a plan that declares nothing prints the "
          "figure at ZERO rather than omitting it. A count that appears only "
          "when it is non-zero cannot be told from a count nobody took - and "
          "this is the case that goes red if the class ever widens until every "
          "unpushed item reads as deliberate: %r" % (_detail(rep, "ado links"),),
          "0 item(s) the PLAN declares off the board" in _detail(rep, "ado links")
          and "0 nothing could answer for" in _detail(rep, "ado links"))

    _bug_declares = _manifest(ado=dict(_ado_on))
    _bug_declares["bugs"] = [{"id": "BUG-1", "title": "b", "status": "open",
                              TRACKED.FIELD: False}]
    rep = run(_bug_declares)
    check("da28 a BUG carrying the key does not move the figure: the declaration "
          "is a property of a PHASE, a bug is owned by none, and answering "
          "`off the board` for one would be this plugin claiming a card it never "
          "created: %r" % (_detail(rep, "ado links"),),
          "0 item(s) the PLAN declares off the board" in _detail(rep, "ado links"))

    rep = run(_plus_phase(_plus_phase(_manifest(ado=dict(_ado_on)), "P2",
                                      tasks=2, declared=False),
                          "P3", tasks=1, declared="nope"))
    check("da29 an item nothing could answer for is counted APART and never as "
          "off the board: the key is three-valued, and folding the third value "
          "into either of the other two is the false confidence this whole "
          "feature removes. Both figures print, so a reader shown one cannot "
          "read it as the whole: %r" % (_detail(rep, "ado links"),),
          "3 item(s) the PLAN declares off the board" in _detail(rep, "ado links")
          and "2 nothing could answer for" in _detail(rep, "ado links"))

    # da31 exists because two surfaces print a number under the same word and the
    # numbers legitimately DIFFER. `read-ado-links` partitions by link, so a phase
    # declared off the board that still carries a work item is `linked` there and
    # off-board here; the gap is exactly the still-linked items. Measured on a
    # three-phase fixture where one is declared off and already carries #4242: the
    # connector line reported one untracked phase, this figure reported four items.
    # Both are right about their own question, and a reader comparing them with no
    # basis on either side would be right to call it a bug — so the basis is the
    # thing under test, not the count.
    _reconcile = _detail(rep, "ado links")
    check("da31 the figure names WHAT IT COUNTS and where the other partition "
          "lives, because `read-ado-links` answers the same word by link and gets "
          "a different number: %r" % (_reconcile,),
          "the PLAN declares off the board" in _reconcile
          and "counted from the declaration, not from links" in _reconcile
          and "read-ado-links.py" in _reconcile)

    _src = _harness.module_source(M)
    check("da30 and the ANSWER is not re-derived here, the way the link walk "
          "above is not: this file spells the key through the module's own "
          "constant and holds no literal of it, so there is no second reading to "
          "drift from the one `/audit:sync status` prints: %r"
          % (TRACKED.FIELD in _src,),
          TRACKED.FIELD not in _src
          and "_tracked.inventory(" in _src and "_tracked.counts(" in _src)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_ado.py --selftest\n")
    raise SystemExit(2)
