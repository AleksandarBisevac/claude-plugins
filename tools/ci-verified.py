#!/usr/bin/env python3
"""Has a run of this workflow already passed this exact commit?

    tools/ci-verified.py --repo OWNER/NAME --workflow ci.yml --sha SHA \\
        --run-id ID [--exempt-job NAME ...] [--output FILE]
    tools/ci-verified.py --selftest

WHY. A phase reaches `main` as a commit a dispatch on its `ci/` branch has already
run through the whole workflow. The push to `main` then ran it again, on the same
bytes, and the second draw could only add a red the first did not have - a Windows
intermittent on a commit already shown green. This asks the question the second
run should ask first, so ci.yml's `verified` job can skip the others and name the
run that verified the commit instead.

WHAT COUNTS AS VERIFIED - `decide()`, and each half of it is a refusal when it
does not hold:

  * a run of THIS workflow file (`path`), on exactly this commit (`head_sha`);
  * not the run asking (`--run-id`);
  * completed, with conclusion `success`;
  * its job list readable, holding at least one job that is not exempt;
  * and every job `success`. A job skipped by a condition reports success to the
    run, so a run whose jobs were skipped - by this very check, on an earlier push -
    would otherwise vouch for the next one with nothing behind it. A skipped job is
    not a passed one.

`--exempt-job` names the jobs a run may have skipped by design: this check's own
job (it runs on a push only) and a job only the release tier runs. An exempt job
that RAN and did not pass still refuses the run; exempt means "may be absent",
never "may be red".

"COULD NOT ASK" IS NOT "VERIFIED". No `gh`, no token, a rate limit, an answer that
is not JSON: each is printed as the reason the commit is NOT verified, and every
job runs. This check's failure mode is a run that was not needed, never a skip that
was not earned.

Exit codes: 0 a verdict was reached and printed (verified or not; the output file
gets `verified=<run id>`, or `verified=` with nothing after it) - 2 usage error. A
refusal to vouch is a verdict, not an error, so it is not a red job either.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

GH_BIN = "gh"

USAGE = ("usage: ci-verified.py --repo OWNER/NAME --workflow FILE --sha SHA "
         "--run-id ID [--exempt-job NAME ...] [--output PATH] | --selftest\n")


# --- asking GitHub ------------------------------------------------------------
def gh_api(path):
    """`(payload, problem)` for one read-only `gh api` GET; exactly one is None."""
    if shutil.which(GH_BIN) is None:
        return None, "gh is not on PATH"
    try:
        proc = subprocess.Popen(
            [GH_BIN, "api", "-H", "Accept: application/vnd.github+json", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
    except OSError as exc:
        return None, "gh could not be started: %s" % (exc,)
    if proc.returncode != 0:
        text = err.decode("utf-8", "replace").strip().splitlines()
        return None, "gh api %s exited %d: %s" % (
            path, proc.returncode, text[-1] if text else "(no message)")
    try:
        return json.loads(out.decode("utf-8", "replace")), None
    except ValueError:
        return None, "gh api %s did not answer with JSON" % (path,)


def runs_path(repo, workflow, sha):
    """This workflow file's completed runs on one commit."""
    return ("repos/%s/actions/workflows/%s/runs?head_sha=%s&status=completed"
            "&per_page=50" % (repo, workflow, sha))


def jobs_path(repo, run_id):
    """The jobs of a run's latest attempt."""
    return ("repos/%s/actions/runs/%s/jobs?filter=latest&per_page=100"
            % (repo, run_id))


# --- the verdict --------------------------------------------------------------
def _is_exempt(name, exempt):
    """A job is exempt by its id-like name, alone or with a matrix suffix."""
    return any(name == e or name.startswith(e + " (") for e in exempt)


def _job_problem(jobs, exempt):
    """Why a readable job list does not prove its run, or None."""
    counted = [j for j in jobs if not _is_exempt(j.get("name") or "", exempt)]
    if not counted:
        return "holds no job besides the exempt ones, so it proved nothing"
    bad = ["%s=%s" % (j.get("name"), j.get("conclusion"))
           for j in counted if j.get("conclusion") != "success"]
    bad += ["%s=%s" % (j.get("name"), j.get("conclusion"))
            for j in jobs if _is_exempt(j.get("name") or "", exempt)
            and j.get("conclusion") not in ("success", "skipped")]
    if bad:
        return "has jobs that did not pass (a skipped job is not a passed " \
               "one): %s" % (", ".join(bad),)
    return None


def decide(sha, workflow, self_run, runs, jobs_of, exempt=()):
    """`{"verified": run id or None, "why": [reason per refused run], "problem"}`.

    `runs` is the API's run list, or None when it could not be asked; `jobs_of`
    maps a run id to its job list, or to None when that list could not be read.
    Newest first, so the run named is the latest proof rather than any one.
    """
    if runs is None:
        return {"verified": None, "why": [],
                "problem": "could not ask GitHub for this workflow's runs"}
    path = ".github/workflows/%s" % (workflow,)
    why = []
    for run in sorted(runs, key=lambda r: r.get("id") or 0, reverse=True):
        rid = run.get("id")
        if str(rid) == str(self_run):
            why.append("run %s is the run asking" % (rid,))
            continue
        if run.get("head_sha") != sha:
            why.append("run %s is on %s, not this commit"
                       % (rid, run.get("head_sha")))
            continue
        if run.get("path") != path:
            why.append("run %s is of %s, not %s" % (rid, run.get("path"), path))
            continue
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            why.append("run %s is %s/%s" % (rid, run.get("status"),
                                            run.get("conclusion")))
            continue
        jobs = jobs_of.get(rid)
        if not isinstance(jobs, list):
            why.append("run %s: its job list could not be read" % (rid,))
            continue
        problem = _job_problem(jobs, exempt)
        if problem is not None:
            why.append("run %s %s" % (rid, problem))
            continue
        return {"verified": rid, "why": why, "problem": None}
    if not runs:
        why.append("no completed run of %s is listed for this commit" % (path,))
    return {"verified": None, "why": why, "problem": None}


def ask_github(repo, workflow, sha, api=None):
    """`(runs, jobs_of)` as `decide()` reads them; `runs` is None when the
    listing could not be had, and a run whose jobs could not be had maps to
    None, so neither silence reaches `decide()` as an empty list."""
    ask = api if api is not None else gh_api
    listing, problem = ask(runs_path(repo, workflow, sha))
    runs = (listing or {}).get("workflow_runs") if problem is None else None
    if not isinstance(runs, list):
        return None, {}
    jobs_of = {}
    for run in runs:
        if run.get("head_sha") != sha or run.get("conclusion") != "success":
            continue
        got, why = ask(jobs_path(repo, run.get("id")))
        jobs = (got or {}).get("jobs") if why is None else None
        jobs_of[run.get("id")] = jobs if isinstance(jobs, list) else None
    return runs, jobs_of


def verdict_lines(sha, answer):
    """What the step prints: a VERIFIED line naming the run, or NOT VERIFIED
    with every reason, ending on what the workflow does about it."""
    if answer["verified"] is not None:
        return ["VERIFIED %s by run %s" % (sha, answer["verified"]),
                "the other jobs of this run are skipped; that run is the evidence"]
    lines = ["NOT VERIFIED %s: %s" % (sha, r)
             for r in ([answer["problem"]] if answer["problem"] else [])
             + answer["why"]]
    return lines + ["every job runs"]


# --- the command --------------------------------------------------------------
def parse_argv(argv):
    """`(options, problem)` - exactly one of the two is None."""
    single = ("--repo", "--workflow", "--sha", "--run-id", "--output")
    opts = {"exempt-job": []}
    rest = list(argv)
    while rest:
        flag = rest.pop(0)
        if flag not in single and flag != "--exempt-job":
            return None, "unknown argument %s" % (flag,)
        if not rest:
            return None, "%s needs a value" % (flag,)
        value = rest.pop(0)
        if flag == "--exempt-job":
            opts["exempt-job"].append(value)
        else:
            opts[flag[2:]] = value
    for need in ("repo", "workflow", "sha", "run-id"):
        if not opts.get(need):
            return None, "--%s is required" % (need,)
    return opts, None


def write_output(path, run_id):
    """Append `verified=<id>`, empty when not verified, in GITHUB_OUTPUT's form."""
    with io.open(path, "a", encoding="utf-8") as fh:
        fh.write("verified=%s\n" % ("" if run_id is None else run_id,))


def main(argv=None, api=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return _selftest()
    opts, problem = parse_argv(argv)
    if problem is not None:
        sys.stderr.write("ci-verified.py: %s\n%s" % (problem, USAGE))
        return 2
    runs, jobs_of = ask_github(opts["repo"], opts["workflow"], opts["sha"], api)
    answer = decide(opts["sha"], opts["workflow"], opts["run-id"], runs, jobs_of,
                    exempt=tuple(opts["exempt-job"]))
    for line in verdict_lines(opts["sha"], answer):
        sys.stdout.write(line + "\n")
    if opts.get("output"):
        write_output(opts["output"], answer["verified"])
    return 0


# --- selftest -----------------------------------------------------------------
_CLAUSE = ("a run whose jobs are all success verifies the SHA; a skipped job, "
           "another commit's run, another workflow file's run, the asking run, "
           "an unreadable job list and could-not-ask each refuse")
_SHA = "a" * 40
_OTHER_SHA = "b" * 40
_WORKFLOW = "ci.yml"
_SELF = 900


def _run(run_id, sha=_SHA, path=".github/workflows/ci.yml", status="completed",
         conclusion="success"):
    return {"id": run_id, "head_sha": sha, "path": path, "status": status,
            "conclusion": conclusion}


def _jobs(*pairs):
    return [{"name": name, "status": "completed", "conclusion": conclusion}
            for name, conclusion in pairs]


_GREEN = _jobs(("selftests (ubuntu-latest, plain 1)", "success"),
               ("selftests (windows-latest, plain 1)", "success"),
               ("lint + e2e (ubuntu-latest)", "success"))


def _ask(runs, jobs_of, exempt=("verified",)):
    return decide(_SHA, _WORKFLOW, _SELF, runs, jobs_of, exempt=exempt)


def _cases(check):
    got = _ask([_run(101)], {101: _GREEN})
    check("cv1 %s (every job of run 101 is success, so it verifies: %r)"
          % (_CLAUSE, got), got["verified"] == 101)

    skipped = _jobs(("selftests (ubuntu-latest, plain 1)", "success"),
                    ("lint + e2e (ubuntu-latest)", "skipped"))
    got = _ask([_run(102)], {102: skipped})
    check("cv2 %s (a run with a skipped job is not evidence - GitHub reports a "
          "skipped job's run as a success: %r)" % (_CLAUSE, got),
          got["verified"] is None and got["problem"] is None
          and any("skipped" in why for why in got["why"]))

    got = _ask([_run(103, sha=_OTHER_SHA)], {103: _GREEN})
    check("cv3 %s (another commit's green run vouches for nothing: %r)"
          % (_CLAUSE, got), got["verified"] is None)

    got = _ask([_run(104, path=".github/workflows/pages.yml")], {104: _GREEN})
    check("cv4 %s (another workflow file's green run vouches for nothing: %r)"
          % (_CLAUSE, got), got["verified"] is None)

    got = _ask([_run(_SELF)], {_SELF: _GREEN})
    check("cv5 %s (the asking run cannot vouch for itself: %r)"
          % (_CLAUSE, got), got["verified"] is None)

    got = _ask([_run(105)], {105: None})
    check("cv6 %s (a run whose job list could not be read is not evidence: %r)"
          % (_CLAUSE, got),
          got["verified"] is None and any("could not be read" in why
                                           for why in got["why"]))

    got = _ask(None, {})
    check("cv7 %s (could not ask GitHub at all is a refusal that says so, not "
          "an empty answer: %r)" % (_CLAUSE, got),
          got["verified"] is None and got["problem"] is not None)

    # THE ALLOW SIDE of the refusals above, so a guard that refused everything
    # would go red here: the guard's own job and a release-tier job are skipped
    # on a run that did not ask for them, and they do not spoil it.
    tiered = _jobs(("verified", "skipped"),
                   ("selftests (ubuntu-latest, plain 1)", "success"),
                   ("resample (windows-latest)", "skipped"))
    got = _ask([_run(106)], {106: tiered}, exempt=("verified", "resample"))
    check("cv8 %s (an exempt job - the guard itself, a release-tier job - may "
          "be skipped without spoiling the run: %r)" % (_CLAUSE, got),
          got["verified"] == 106)

    red_exempt = _jobs(("selftests (ubuntu-latest, plain 1)", "success"),
                       ("resample (windows-latest)", "failure"))
    got = _ask([_run(107)], {107: red_exempt}, exempt=("verified", "resample"))
    check("cv9 %s (...but an exempt job that RAN and failed spoils it: %r)"
          % (_CLAUSE, got), got["verified"] is None)

    got = _ask([_run(108)], {108: []})
    check("cv10 %s (a run with no jobs at all is not a run whose jobs all "
          "passed: %r)" % (_CLAUSE, got), got["verified"] is None)

    got = _ask([_run(109, status="in_progress", conclusion=None)],
               {109: _GREEN})
    check("cv11 %s (a run that has not completed is not evidence: %r)"
          % (_CLAUSE, got), got["verified"] is None)

    got = _ask([_run(110), _run(111)], {110: skipped, 111: _GREEN})
    check("cv12 %s (one refused run does not hide another that verifies: %r)"
          % (_CLAUSE, got), got["verified"] == 111)

    # --- the command around decide(): what it asks, prints and writes ---------
    def fake_api(runs=None, jobs=None, fail=None):
        seen = []

        def ask(path):
            seen.append(path)
            if fail is not None and fail in path:
                return None, "HTTP 403: rate limit"
            if "/jobs?" in path:
                rid = int(path.split("/runs/")[1].split("/")[0])
                return {"jobs": (jobs or {}).get(rid, [])}, None
            return {"workflow_runs": runs if runs is not None else []}, None
        ask.seen = seen
        return ask

    api = fake_api([_run(201)], {201: _GREEN})
    runs, jobs_of = ask_github("o/n", _WORKFLOW, _SHA, api)
    got = decide(_SHA, _WORKFLOW, _SELF, runs, jobs_of)
    check("cv13 %s (asked through the API seam, run 201 verifies, the runs "
          "were listed for this workflow file and commit only, and jobs were "
          "read for the latest attempt: %r)" % (_CLAUSE, api.seen),
          got["verified"] == 201
          and api.seen[0] == runs_path("o/n", _WORKFLOW, _SHA)
          and "head_sha=%s" % (_SHA,) in api.seen[0]
          and api.seen[1:] == [jobs_path("o/n", 201)]
          and "filter=latest" in api.seen[1])

    runs, jobs_of = ask_github("o/n", _WORKFLOW, _SHA, fake_api(fail="/runs?"))
    lines = verdict_lines(_SHA, decide(_SHA, _WORKFLOW, _SELF, runs, jobs_of))
    check("cv14 %s (a listing that could not be had prints NOT VERIFIED with the "
          "reason, and every job runs: %r)" % (_CLAUSE, lines),
          runs is None and lines[0].startswith("NOT VERIFIED")
          and "could not ask" in lines[0] and lines[-1] == "every job runs")

    runs, jobs_of = ask_github("o/n", _WORKFLOW, _SHA,
                               fake_api([_run(202)], fail="/jobs?"))
    got = decide(_SHA, _WORKFLOW, _SELF, runs, jobs_of)
    check("cv15 %s (a job list the API refused reaches decide() as unreadable, "
          "never as an empty list: %r / %r)" % (_CLAUSE, jobs_of, got),
          jobs_of == {202: None} and got["verified"] is None)

    handle, box = tempfile.mkstemp(prefix="ci-verified-out-")
    os.close(handle)
    try:
        write_output(box, 61)
        write_output(box, None)
        with io.open(box, encoding="utf-8") as fh:
            text = fh.read()
    finally:
        os.remove(box)
    check("cv16 the output file gets `verified=<id>` when verified and an EMPTY "
          "value when not, which is what the workflow's condition reads: %r"
          % (text,), text == "verified=61\nverified=\n")

    opts, problem = parse_argv(["--repo", "o/n", "--workflow", "ci.yml",
                                "--sha", _SHA])
    opts2, problem2 = parse_argv(["--repo", "o/n", "--workflow", "ci.yml",
                                  "--sha", _SHA, "--run-id", "9", "--wat", "x"])
    opts3, _p3 = parse_argv(["--repo", "o/n", "--workflow", "ci.yml", "--sha",
                             _SHA, "--run-id", "9", "--exempt-job", "verified",
                             "--exempt-job", "resample"])
    check("cv17 a missing --run-id and an unknown argument are usage errors, and "
          "--exempt-job collects every name it is given: %r / %r / %r"
          % (problem, problem2, (opts3 or {}).get("exempt-job")),
          opts is None and "--run-id" in problem and opts2 is None
          and "--wat" in problem2
          and opts3["exempt-job"] == ["verified", "resample"])


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    raise SystemExit(main())
