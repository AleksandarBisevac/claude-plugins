#!/usr/bin/env python3
"""
The cases for `_doctor_completions.py` — the pipeline's receipts against the
plan they are receipts for.

The watermark is what most of these cases are really about. The era is decided
by the FIRST `task.complete` row's `ts` and by nothing else, so every fixture
here carries TWO records at different timestamps: with one record the min and
the max of the set are the same value, and a suite built on that cannot tell the
rule from its opposite.

The grading line is the other subject. Positive evidence is a FINDING (a done
task inside the era with no record; a commit SHA git has never heard of);
everything the check merely could not look up is a WARNING at most, and the
`could not check` row exists so an unanswered question is never reported as an
all-clear.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import shutil
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _doctor_completions as M                    # noqa: E402
import _doctor_report as base                      # noqa: E402  (the collector)
import _journal_io                                 # noqa: E402


def _levels(rep, name):
    return [r["level"] for r in rep.rows if r["check"] == name]


def _detail(rep, name):
    return " ".join(r["detail"] for r in rep.rows if r["check"] == name)


def _task(tid, **over):
    t = {"id": tid, "title": "t", "status": "done", "files": ["a.py"],
         "tests": {"mode": "regression"}, "risk": "low"}
    t.update(over)
    return t


def _manifest(tasks):
    return {"meta": {"version": 2, "title": "t"},
            "phases": [{"id": "P1", "title": "one", "status": "done",
                        "tasks": tasks}],
            "bugs": [], "fileIndex": {"a.py": [t["id"] for t in tasks]}}


# --- cases --------------------------------------------------------------------
def _cases(check):
    import tempfile

    # ------------------------------------------------------- _hours_between
    check("dc1 two timestamps a day apart are 24 hours, whichever way round "
          "they are given - the gap is a DISTANCE, and an unsigned one is what "
          "the 24h threshold reads: %r"
          % (M._hours_between("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),),
          M._hours_between("2026-01-01T00:00:00Z",
                           "2026-01-02T00:00:00Z") == 24.0
          and M._hours_between("2026-01-02T00:00:00Z",
                               "2026-01-01T00:00:00Z") == 24.0)
    unreadable = [M._hours_between(a, b) for a, b in
                  (("nope", "2026-01-01T00:00:00Z"),
                   ("2026-01-01T00:00:00Z", ""),
                   (None, "2026-01-01T00:00:00Z"), (7, 8))]
    check("dc2 an unreadable timestamp is None, not 0 - a gap of zero would "
          "read as 'they agree', which is an accusation the check has no basis "
          "for: %r" % (unreadable,), unreadable == [None, None, None, None])
    check("dc3 ...and a bare `YYYY-MM-DDTHH:MM:SS` with no Z still parses, "
          "because the parser reads the first 19 characters: %r"
          % (M._hours_between("2026-01-01T00:00:00", "2026-01-01T12:00:00"),),
          M._hours_between("2026-01-01T00:00:00",
                           "2026-01-01T12:00:00") == 12.0)

    # ----------------------------------------------------- check_completions
    have_git = bool(shutil.which("git"))
    if not have_git:
        print("SKIP git-dependent cases (git is not on PATH)")
    tmp = tempfile.mkdtemp(prefix="doctor-completions-")
    try:
        mrel = "docs/audit/audit-plan.json"
        os.makedirs(os.path.join(tmp, "docs", "audit"))

        rep = base.Report()
        M.check_completions(rep, tmp, {}, None, mrel, None)
        check("dc4 no manifest is SILENCE - there is nothing to join the "
              "records against", rep.rows == [])

        mf = _manifest([_task("P1.1", completedAt="2026-05-01T00:00:00Z")])
        rep = base.Report()
        M.check_completions(rep, tmp, {}, mf, mrel, None)
        check("dc5 a journal with NO completion records at all is one ok line "
              "saying an older plugin wrote this history - not a nag about "
              "every done task in it: %r" % (_detail(rep, "completions"),),
              _levels(rep, "completions") == ["OK"]
              and "not in use" in _detail(rep, "completions"))

        _journal_io.append(tmp, {"action": "task.complete", "actor": "p",
                                 "ts": "2026-03-01T00:00:00Z",
                                 "details": {"taskId": "P1.1"}})
        _journal_io.append(tmp, {"action": "task.complete", "actor": "p",
                                 "ts": "2026-09-01T00:00:00Z",
                                 "details": {"taskId": "P1.2"}})

        mf = _manifest([_task("P1.1", completedAt="2026-01-01T00:00:00Z")])
        rep = base.Report()
        M.check_completions(rep, tmp, {}, mf, mrel, None)
        check("dc6 a done task BEFORE the watermark is out of scope and said so "
              "- the watermark is the FIRST record's ts (2026-03), and this "
              "task predates it while sitting well before the second record "
              "too, so min and max give different verdicts here: %r"
              % (_detail(rep, "completions"),),
              "predate the first completion record" in _detail(rep, "completions"))

        mf = _manifest([_task("P1.1", completedAt="2026-05-01T00:00:00Z")])
        rep = base.Report()
        M.check_completions(rep, tmp, {}, mf, mrel, None)
        check("dc7 ...while one BETWEEN the two records is in scope and gets "
              "checked. The date is chosen to sit after the first record and "
              "before the second, so a `max` watermark would push this same "
              "task out of the era and a `min` one keeps it in: %r"
              % (_detail(rep, "completions"),),
              "predate the first completion record"
              not in _detail(rep, "completions")
              and "carry no commit SHA" in _detail(rep, "completions"))

        mf = _manifest([_task("P9.9", completedAt="2026-05-01T00:00:00Z")])
        rep = base.Report()
        M.check_completions(rep, tmp, {}, mf, mrel, None)
        check("dc8 a done task inside the era with NO record is a FINDING that "
              "names it and says what it means - the manifest was edited "
              "outside the pipeline, or a record was removed: %r"
              % (_detail(rep, "completions"),),
              "FINDING" in _levels(rep, "completions")
              and "P9.9" in _detail(rep, "completions")
              and "outside the pipeline" in _detail(rep, "completions"))

        mf = _manifest([_task("P1.1", completedAt="2026-05-01T00:00:00Z")])
        rep = base.Report()
        M.check_completions(rep, tmp, {}, mf, mrel, None)
        _fix = " ".join(r["fix"] or "" for r in rep.rows
                        if r["check"] == "completions")
        check("dc9 a done task carrying no commit SHA is a WARNING, never a "
              "FINDING, and the fix points at /audit:resume: %r"
              % (_detail(rep, "completions"),),
              "FINDING" not in _levels(rep, "completions")
              and "carry no commit SHA" in _detail(rep, "completions")
              and "/audit:resume" in _fix)

        mf = _manifest([_task("P1.1", completedAt="2026-05-01T00:00:00Z",
                              commit="0" * 40)])
        rep = base.Report()
        M.check_completions(rep, tmp, {}, mf, mrel, None)
        # The SHA arm now reports under its OWN check name. It moved out of
        # `completions` because it does not depend on the journal at all - and it
        # used to sit BELOW two journal-shaped early returns, so a repo with a
        # fresh or disabled journal got no commit verification whatever while
        # `completions` printed an OK line. The behaviour is the same claim; the
        # surface it is made on is different, so these cases follow it rather
        # than being deleted.
        check("dc10 with NO git root the trail arm reports that it could not "
              "verify, rather than passing - an unverifiable claim is not a "
              "verified one, and the WARNING carries the fix that names why "
              "(the detail is the claim; the fix is where 'no git' lives): %r"
              % (_detail(rep, "commit trail"),),
              "could not be verified" in _detail(rep, "commit trail")
              and "WARNING" in _levels(rep, "commit trail")
              and any("no git" in (r.get("fix") or "")
                      for r in rep.rows if r["check"] == "commit trail"),
              repr([r for r in rep.rows if r["check"] == "commit trail"]))
        check("dc11 ...and the all-clear line is suppressed while anything is "
              "unanswered. A filter that narrowed to nothing must never read as "
              "'everything checked out'",
              "chained records" not in _detail(rep, "completions"))

        if have_git:
            subprocess.run(["git", "init", "-q", tmp], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for k, v in (("user.email", "p@example.com"), ("user.name", "P")):
                subprocess.run(["git", "-C", tmp, "config", k, v], check=True)
            with open(os.path.join(tmp, "a.py"), "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "i"], check=True,
                           stdout=subprocess.DEVNULL)
            head = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"],
                                  stdout=subprocess.PIPE,
                                  check=True).stdout.decode().strip()

            # The ONLY fully clean fixture in this file: a real commit, a
            # completedAt inside 24h of the record, and a ledger row covering
            # the task. Every arm has to stay quiet for the all-clear to print.
            import _loader
            ul = _loader.load_script("usage_ledger.py", modname="dc_ledger")
            ledger = os.path.join(tmp, ".claude", "usage")
            ul.ensure_ledger_dir(ledger)
            ul.append_rows(ledger, [{"ts": "2026-03-01T00:00:00Z",
                                     "taskId": "P1.1", "author": "p",
                                     "model": "m", "inputTokens": 1,
                                     "outputTokens": 1}])
            mf = _manifest([_task("P1.1", completedAt="2026-03-01T00:00:00Z",
                                  commit=head)])
            rep = base.Report()
            M.check_completions(rep, tmp, {}, mf, mrel, tmp)
            check("dc12 a real commit resolves and the whole check comes out as "
                  "one ok line. THE OTHER-DIRECTION CASE for every arm at once: "
                  "it is what fails if any of them becomes unconditional: %r"
                  % (_detail(rep, "completions"),),
                  _levels(rep, "completions") == ["OK"]
                  and "chained records" in _detail(rep, "completions"))

            mf = _manifest([_task("P1.1", completedAt="2026-05-01T00:00:00Z",
                                  commit="d" * 40)])
            rep = base.Report()
            M.check_completions(rep, tmp, {}, mf, mrel, tmp)
            check("dc13 ...and a SHA git has never heard of is a FINDING naming "
                  "the task and the first 12 characters, on the trail check: %r"
                  % (_detail(rep, "commit trail"),),
                  "FINDING" in _levels(rep, "commit trail")
                  and "P1.1 (dddddddddddd)" in _detail(rep, "commit trail"))

            mf = _manifest([_task("P1.1", completedAt="2026-03-01T00:00:00Z")])
            rep = base.Report()
            M.check_completions(rep, tmp, {}, mf, mrel, tmp)
            check("dc14 a done task with no `commit` at all is a WARNING and "
                  "nothing more - an interrupted run is not a rewritten "
                  "history: %r" % (_detail(rep, "completions"),),
                  _levels(rep, "completions") == ["WARNING"]
                  and "carry no commit SHA" in _detail(rep, "completions"))

            mf = _manifest([_task("P1.1", completedAt="2026-03-05T00:00:00Z",
                                  commit=head)])
            rep = base.Report()
            M.check_completions(rep, tmp, {}, mf, mrel, tmp)
            check("dc15 a completedAt four days off the record it belongs to is "
                  "a WARNING that reports the gap in hours and says it is worth "
                  "a look rather than proof of anything: %r"
                  % (_detail(rep, "completions"),),
                  "disagree by more than 24h" in _detail(rep, "completions"))

            mf = _manifest([_task("P1.1", completedAt="2026-03-01T06:00:00Z",
                                  commit=head)])
            rep = base.Report()
            M.check_completions(rep, tmp, {}, mf, mrel, tmp)
            check("dc16 ...and six hours off is inside the threshold and silent. "
                  "The two fixtures straddle 24h, so a threshold moved in either "
                  "direction changes one of them: %r"
                  % (_detail(rep, "completions"),),
                  "disagree by more than 24h" not in _detail(rep, "completions"))

            mf = _manifest([_task("P1.1", completedAt="2026-03-01T00:00:00Z",
                                  commit=head),
                            _task("P1.9", completedAt="2026-03-02T00:00:00Z",
                                  commit=head)])
            rep = base.Report()
            M.check_completions(rep, tmp, {}, mf, mrel, tmp)
            check("dc17 the ledger-coverage arm names only the task with NO "
                  "rows. One of the two is covered and the other is not, so a "
                  "version comparing the sets the other way round reports the "
                  "wrong id: %r" % (_detail(rep, "completions"),),
                  "no usage-ledger rows: P1.9" in _detail(rep, "completions"))

            # ------------------------------------------------ --deep (F33)
            # The deep arm asks whether the task's own commit carries the
            # journal file that records it. Its finding was invisible to the
            # all-clear guard, so a run printed the warning and "all carry
            # chained records" side by side - the check contradicting itself in
            # two adjacent lines.
            #
            # `tmp`'s HEAD already CARRIES the journal (the rows were appended
            # before `git add -A` above), which makes it the control. The
            # defective fixture needs the opposite order, so it gets its own
            # repo: commit first, journal second, and then the commit's tree
            # cannot contain a file that did not exist when it was written.
            deep_tmp = tempfile.mkdtemp(prefix="doctor-completions-deep-")
            try:
                os.makedirs(os.path.join(deep_tmp, "docs", "audit"))
                subprocess.run(["git", "init", "-q", deep_tmp], check=True,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
                for k, v in (("user.email", "p@example.com"),
                             ("user.name", "P")):
                    subprocess.run(["git", "-C", deep_tmp, "config", k, v],
                                   check=True)
                with open(os.path.join(deep_tmp, "a.py"), "w",
                          encoding="utf-8") as fh:
                    fh.write("x = 1\n")
                subprocess.run(["git", "-C", deep_tmp, "add", "-A"], check=True,
                               stdout=subprocess.DEVNULL)
                subprocess.run(["git", "-C", deep_tmp, "-c",
                                "commit.gpgsign=false", "commit", "-q", "-m",
                                "i"], check=True, stdout=subprocess.DEVNULL)
                deep_head = subprocess.run(
                    ["git", "-C", deep_tmp, "rev-parse", "HEAD"],
                    stdout=subprocess.PIPE, check=True).stdout.decode().strip()
                for ts, tid in (("2026-03-01T00:00:00Z", "P1.1"),
                                ("2026-09-01T00:00:00Z", "P1.2")):
                    _journal_io.append(deep_tmp,
                                       {"action": "task.complete", "actor": "p",
                                        "ts": ts, "details": {"taskId": tid}})
                deep_ledger = os.path.join(deep_tmp, ".claude", "usage")
                ul.ensure_ledger_dir(deep_ledger)
                ul.append_rows(deep_ledger, [{"ts": "2026-03-01T00:00:00Z",
                                              "taskId": "P1.1", "author": "p",
                                              "model": "m", "inputTokens": 1,
                                              "outputTokens": 1}])
                deep_mf = _manifest([_task("P1.1",
                                           completedAt="2026-03-01T00:00:00Z",
                                           commit=deep_head)])

                rep = base.Report()
                M.check_completions(rep, deep_tmp, {}, deep_mf, mrel, deep_tmp,
                                    deep=True)
                check("dc18 --deep finds a commit that does not carry its own "
                      "journal file, and the all-clear is SUPPRESSED - a check "
                      "may not warn and report everything clean in the same "
                      "breath: %r" % (_detail(rep, "completions"),),
                      "does not carry the journal" in _detail(rep, "completions")
                      and "chained records" not in _detail(rep, "completions")
                      and "OK" not in _levels(rep, "completions"))

                rep = base.Report()
                M.check_completions(rep, deep_tmp, {}, deep_mf, mrel, deep_tmp,
                                    deep=False)
                check("dc19 ...and WITHOUT --deep that same fixture is one ok "
                      "line: the deep arm is opt-in and its verdict must not "
                      "leak into a shallow run: %r"
                      % (_detail(rep, "completions"),),
                      _levels(rep, "completions") == ["OK"]
                      and "chained records" in _detail(rep, "completions"))
            finally:
                shutil.rmtree(deep_tmp, ignore_errors=True)

            # THE OTHER DIRECTION, on the repo whose commit DOES carry the
            # journal: --deep has to stay silent and the all-clear has to
            # print. Suppressing it unconditionally would pass dc18 and fail
            # here, which is the whole reason this case exists.
            mf = _manifest([_task("P1.1", completedAt="2026-03-01T00:00:00Z",
                                  commit=head)])
            rep = base.Report()
            M.check_completions(rep, tmp, {}, mf, mrel, tmp, deep=True)
            check("dc20 --deep on a commit that DOES carry its journal file is "
                  "silent, and the all-clear still prints: %r"
                  % (_detail(rep, "completions"),),
                  _levels(rep, "completions") == ["OK"]
                  and "does not carry the journal"
                  not in _detail(rep, "completions")
                  and "chained records" in _detail(rep, "completions"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_completions.py --selftest\n")
    raise SystemExit(2)
