#!/usr/bin/env python3
"""Cases for `governance/full-gate.py`.

WHAT THIS FILE IS ABOUT, in one line: before this script existed, there was no
single third-place command a pre-push hook could call - it would have had to
spell out `run-test-gate.py <m> --full --record` itself, and decide on its own
what a plan with no `meta.fullGate` means for a push that must not block. So
its exit code could never BE the full run's: nothing produced one at all.

TWO KINDS OF CASE. The delegation cases (fgd*) replace `M._stream_subprocess`
with a seam that records the command it was asked to run and returns a canned
exit code - proving this file builds the RIGHT command and passes its exit
code through unchanged, without paying for a real child process. The
end-to-end cases (fge*) run the real subprocess against a real git repository,
the same fixture shape `test_run_test_gate.py`'s `_full_repo` uses, because
"does a write actually land and get printed" is a question only a real run
answers.
"""
import json
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (script_path: resolve by basename)
import _evidence_io as _ev_io                      # noqa: E402  (read_rows, evidence_dir)

M = _loader.load_script("full-gate.py", "full_gate")

# THE SUITES A FAKED RUNNER NAMES ARE TRACKED FILES of the fixture, as a real
# runner's are: a miss is filed under the one tracked path its spelling pins
# to (`_evidence_io.pin_suite`), so a suite git does not track couples nothing.
_TRACKED_SUITES = ("tests/test_cart.py", "tests/test_old.py",
                   "tests/test_stale.py", "backend/tests/test_x.py",
                   "pkg1/tests/x.test.js", "pkg2/tests/x.test.js")


def _full_repo(name, fullgate=("ok",), buildcommands=None):
    """A committed git repository whose plan declares `meta.fullGate` (or does
    not, when `fullgate=None`) - the same fixture shape
    `test_run_test_gate.py`'s `_full_repo` builds, kept independent here
    rather than imported: a test file reaching into another test file's
    private helper is the same sideways edge `_deps.layer_violations()`
    refuses between production modules. `_TRACKED_SUITES` are committed
    beside the plan.
    """
    root = _harness.fixture_root("full-gate-")
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, ".claude"))
    for suite in _TRACKED_SUITES:
        os.makedirs(os.path.join(root, os.path.dirname(suite)), exist_ok=True)
        with open(os.path.join(root, suite), "w") as fh:
            fh.write("# %s\n" % (suite,))
    with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    meta = {"version": 3,
           "buildCommands": buildcommands or {"ok": "true", "bad": "false"}}
    if fullgate is not None:
        meta["fullGate"] = list(fullgate)
    with open(mpath, "w") as fh:
        json.dump({"meta": meta,
                  "phases": [{"id": "P1", "title": "one", "status": "in_progress",
                             "tasks": []}]}, fh)
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tops = sorted(set(s.split("/", 1)[0] for s in _TRACKED_SUITES))
    for arg in (["add", "--", "docs", ".claude"] + tops,
                ["-c", "user.email=fixture@example.com",
                 "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", root] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return root, mpath


def _delegation_cases(check):
    # --- the no-fullGate branch never invokes the subprocess at all --------
    root, mpath = _full_repo("no-gate", fullgate=None)
    try:
        called = []
        real = M._stream_subprocess
        M._stream_subprocess = lambda cmd, out: called.append(cmd) or 0
        try:
            lines = []
            code = M.main([mpath], out=lines.append)
        finally:
            M._stream_subprocess = real
        check("fgd1 RED-FIRST: a plan with no meta.fullGate exits 0 with the "
              "sentence and never reaches the subprocess seam - the mutation "
              "'exit 2 instead' is the one this case is written to catch: "
              "%r" % (lines,),
              code == M.E_OK and called == []
              and any("no meta.fullGate declared" in ln for ln in lines))
    finally:
        _harness.remove_tree(root)

    # --- the declared branch builds run-test-gate.py --full --record -------
    root2, mpath2 = _full_repo("gate")
    try:
        called = []
        real = M._stream_subprocess
        M._stream_subprocess = lambda cmd, out: called.append(cmd) or 0
        try:
            code = M.main([mpath2, "--writer", "ci-9", "--project-dir", "/tmp/x"],
                          out=(lambda _l: None))
        finally:
            M._stream_subprocess = real
        cmd = called[0] if called else []
        check("fgd2 the built command names run-test-gate.py by basename "
              "(never imported), carries --full --record, and passes "
              "--writer/--project-dir through unchanged rather than "
              "re-parsing them: %r" % (cmd,),
              code == M.E_OK and len(called) == 1
              and os.path.basename(cmd[1]) == "run-test-gate.py"
              and cmd[2] == mpath2
              and "--full" in cmd and "--record" in cmd
              and "ci-9" in cmd and "/tmp/x" in cmd)
    finally:
        _harness.remove_tree(root2)

    # --- the runner's exit code is this file's exit code, unchanged --------
    root3, mpath3 = _full_repo("red")
    try:
        real = M._stream_subprocess
        M._stream_subprocess = lambda cmd, out: 1
        try:
            code = M.main([mpath3], out=(lambda _l: None))
        finally:
            M._stream_subprocess = real
        check("fgd3 RED-FIRST: a red runner's exit code (1) is this file's "
              "own exit code - the mutation 'always return 0' is the one "
              "this case is written to catch: %d" % (code,),
              code == 1)
    finally:
        _harness.remove_tree(root3)

    # --- an unreadable manifest is a usage error, not a silent success -----
    lines = []
    code = M.main([os.path.join(root2, "nowhere.json")], out=lines.append)
    check("fgd4 a manifest that will not load is a usage error (exit 2), and "
          "says so: %r" % (lines,),
          code == M.E_USAGE and any("cannot read the manifest" in ln for ln in lines))


def _end_to_end_cases(check):
    # --- a green declared fullGate delegates to a REAL run-test-gate.py ----
    root, mpath = _full_repo("e2e-green", buildcommands={"ok": "true"})
    try:
        lines = []
        code = M.main([mpath, "--project-dir", root], out=lines.append)
        text = "\n".join(lines)
        rows = _ev_io.read_rows(root)["rows"]
        full_rows = [r for r in rows if r.get("scope") == "full"]
        check("fge1 a real full-gate.py run against a real run-test-gate.py "
              "exits 0, prints the runner's own FULL GATE GREEN line (a "
              "write that is not printed is the mutation this catches), and "
              "leaves a scope-full evidence row behind: %r" % (full_rows,),
              code == M.E_OK and "FULL GATE GREEN" in text
              and len(full_rows) == 1)
    finally:
        _harness.remove_tree(root)

    # --- a red declared fullGate is red end to end, never swallowed --------
    root_r, mpath_r = _full_repo("e2e-red", buildcommands={"ok": "false"})
    try:
        lines = []
        code = M.main([mpath_r, "--project-dir", root_r], out=lines.append)
        text = "\n".join(lines)
        check("fge2 RED-FIRST: a red command reaches full-gate.py as a "
              "non-zero exit and the runner's own FULL GATE RED line, not a "
              "success this file invented on top of a red run: %r" % (text,),
              code != M.E_OK and "FULL GATE RED" in text)
    finally:
        _harness.remove_tree(root_r)

    # --- --writer plumbs through to the real evidence file it names --------
    root_w, mpath_w = _full_repo("e2e-writer")
    try:
        code = M.main([mpath_w, "--project-dir", root_w, "--writer", "ci-77"],
                      out=(lambda _l: None))
        names = os.listdir(_ev_io.evidence_dir(root_w))
        check("fge3 --writer reaches the real evidence file, exactly as a "
              "direct run-test-gate.py --writer call would: %r" % (names,),
              code == M.E_OK and any("ci-77" in n for n in names))
    finally:
        _harness.remove_tree(root_w)


# --- learning from a red full run ---------------------------------------------
# THE RUNNER IS FAKED, THE VERBS ARE REAL. A real selection miss needs merged
# phases, derived gates and an earlier measured full run - the runner's own
# suite owns that question. What THIS file owes is the second half: given the
# row a full run recorded, does it file the coupling and the bug through the
# real `audit-task.py`, and nothing else. So the seam below plays the runner
# (it appends the row and prints the runner's own `evidence: recorded` line)
# and hands every other command to the real subprocess.
_NAMED_BASIS = ("suite files pytest %s, read from its FAILED <path> lines"
                % (_ev_io.NAMED_FAILING,))
_TAIL_BASIS = ("no runner reader named a suite; the failure was read off the "
               "tail of the output")


def _git_head(root):
    return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                          check=True, stdout=subprocess.PIPE,
                          universal_newlines=True).stdout.strip()


def _learn_repo(name):
    """A committed fixture whose plan already couples `tests/test_old.py` -
    the suite a `--caught` is owed for when a full run names it failing."""
    root, mpath = _full_repo(name, buildcommands={"ok": "false"})
    with open(mpath) as fh:
        plan = json.load(fh)
    plan["meta"]["coupling"] = [{
        "test": "tests/test_old.py", "sources": ["src/old.py"],
        "basis": {"runId": "RUN-EARLIER", "head": _git_head(root),
                  "phases": ["P1"]},
        "learnedAt": "2026-01-01T00:00:00Z"}]
    with open(mpath, "w") as fh:
        json.dump(plan, fh)
    return root, mpath


def _fake_runner(root, run_id, code, steps, misses=None, printed=None,
                 status="failed", append=True):
    """A `_stream_subprocess` stand-in: for `run-test-gate.py` it appends one
    full row (unless `append` is False) and prints the runner's own evidence
    line; every other command (the `audit-task.py` verbs) runs for real."""
    real = M._stream_subprocess

    def seam(cmd, out):
        if os.path.basename(cmd[1]) != "run-test-gate.py":
            return real(cmd, out)
        row = {"v": 1, "runId": run_id, "ts": _ev_io._now(), "scope": "full",
               "status": status,
               "testedState": {"head": _git_head(root)}, "steps": steps}
        if misses is not None:
            row["selectionMiss"] = misses
        if append:
            _ev_io.append_row(root, row)
        out(printed if printed is not None
            else "  evidence: recorded %s" % (run_id,))
        out("FULL GATE RED" if code else "FULL GATE GREEN")
        return code
    return seam, real


def _drive(root, mpath, seam, real):
    lines = []
    M._stream_subprocess = seam
    try:
        code = M.main([mpath, "--project-dir", root], out=lines.append)
    finally:
        M._stream_subprocess = real
    return code, lines


def _plan_facts(root, mpath):
    """(coupling by test, bugs, journal actions) as the plan and the trail
    hold them after the run."""
    import _journal_io
    with open(mpath) as fh:
        plan = json.load(fh)
    coupling = dict((e.get("test"), e)
                    for e in (plan.get("meta") or {}).get("coupling") or [])
    actions = [r.get("action") for r in _journal_io.read_all(root)]
    return coupling, plan.get("bugs") or [], actions


def _learning_cases(check):
    # --- a named miss ends with a coupling, a bug, and a catch ------------
    root, mpath = _learn_repo("learn-miss")
    try:
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_cart.py", "tests/test_old.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        misses = [{"test": "tests/test_cart.py", "phases": ["P1"],
                   "sources": ["src/cart.py"]}]
        seam, real = _fake_runner(root, "RUN-FG-MISS", 1, steps, misses)
        code, lines = _drive(root, mpath, seam, real)
        coupling, bugs, actions = _plan_facts(root, mpath)
        cart = coupling.get("tests/test_cart.py") or {}
        titles = [b.get("title") for b in bugs]
        # READ WITH A FALLBACK so the red on a full-gate that learns nothing
        # is an observed empty plan, not a missing attribute raising first.
        title_of = getattr(M, "bug_title", lambda t: "SELECTION MISS: %s" % (t,))
        check("fgl1 RED-FIRST: a full run whose runner named a selection "
              "miss ends with a coupling for the suite (sources and basis "
              "from the row), exactly one bug naming it, and one journal row "
              "each - before this, the plan held neither: %r"
              % ((cart, titles, actions),),
              cart.get("sources") == ["src/cart.py"]
              and (cart.get("basis") or {}).get("runId") == "RUN-FG-MISS"
              and (cart.get("basis") or {}).get("phases") == ["P1"]
              and titles == [title_of("tests/test_cart.py")]
              and bugs[0].get("files") == ["tests/test_cart.py"]
              and actions.count("coupling.learned") == 1
              and actions.count("bug.add") == 1)
        check("fgl2 the already-coupled suite the runner named failing gets "
              "its catch (`couple --caught`), and the suite coupled only "
              "now does not - a coupling learned from a run is not a catch "
              "by that run: %r" % ((coupling.get("tests/test_old.py"),
                                   actions),),
              actions.count("coupling.caught") == 1
              and bool((coupling.get("tests/test_old.py") or {})
                       .get("lastCaught"))
              and "lastCaught" not in cart)
        check("fgl3 RED-FIRST: a learned miss still blocks the push - the "
              "exit is the runner's (1), and the output says the miss was "
              "learned and the run is still red; the mutation 'exit 0 once "
              "learned' is the one this catches: %r" % ((code, lines),),
              code == 1
              and any("still red" in ln for ln in lines))

        # --- the same miss again: nothing filed twice ---------------------
        seam2, real2 = _fake_runner(root, "RUN-FG-MISS-2", 1, steps, misses)
        code2, lines2 = _drive(root, mpath, seam2, real2)
        coupling2, bugs2, actions2 = _plan_facts(root, mpath)
        check("fgl4 a second red run carrying the same miss files no second "
              "bug and no second coupling, and says which open bug already "
              "tracks it: %r" % ((len(bugs2), actions2, lines2),),
              code2 == 1 and len(bugs2) == 1
              and actions2.count("bug.add") == 1
              and actions2.count("coupling.learned") == 1
              and any("already open" in ln and bugs2[0].get("id") in ln
                      for ln in lines2))
    finally:
        _harness.remove_tree(root)

    # --- a tail-basis red writes nothing -----------------------------------
    root_t, mpath_t = _learn_repo("learn-tail")
    try:
        # THE ROW IS FORGED TO CARRY A MISS the runner would never write on a
        # tail basis, so the mutation 'act on the row's miss or its failing
        # lines without asking whether the runner NAMED the suite' turns this
        # red rather than passing on a row with nothing in it.
        steps = [{"name": "ok", "exit": 1,
                  "failing": ["FAILED tests/test_cart.py::test_total"],
                  "failingBasis": "the last lines of the output",
                  "failingSuites": ["tests/test_cart.py", "tests/test_old.py"],
                  "failingSuitesBasis": _TAIL_BASIS}]
        misses = [{"test": "tests/test_cart.py", "phases": ["P1"],
                   "sources": ["src/cart.py"]}]
        seam, real = _fake_runner(root_t, "RUN-FG-TAIL", 1, steps, misses)
        code, lines = _drive(root_t, mpath_t, seam, real)
        coupling, bugs, actions = _plan_facts(root_t, mpath_t)
        check("fgl5 RED-FIRST: a red run whose runner did not NAME the "
              "failing suites writes nothing - no coupling, no bug, no catch, "
              "no journal row - exits with the runner's code, and says why "
              "with the step's own basis: %r" % ((code, lines, actions),),
              code == 1 and "tests/test_cart.py" not in coupling
              and bugs == [] and actions == []
              and any("not learned" in ln and _TAIL_BASIS in ln
                      for ln in lines))
    finally:
        _harness.remove_tree(root_t)

    # --- a green run writes nothing ----------------------------------------
    root_g, mpath_g = _learn_repo("learn-green")
    try:
        # ALLOW CASE, and the row is deliberately inconsistent with the exit:
        # it names a failing suite and a miss. The runner's exit code is the
        # verdict, so the mutation 'learn whatever the exit' is what this
        # case is here to turn red.
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_cart.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        misses = [{"test": "tests/test_cart.py", "phases": ["P1"],
                   "sources": ["src/cart.py"]}]
        seam, real = _fake_runner(root_g, "RUN-FG-GREEN", 0, steps, misses,
                                  status="passed")
        code, lines = _drive(root_g, mpath_g, seam, real)
        coupling, bugs, actions = _plan_facts(root_g, mpath_g)
        check("fgl6 ALLOW CASE: a green run writes nothing and exits 0: %r"
              % ((code, actions, lines),),
              code == 0 and "tests/test_cart.py" not in coupling
              and bugs == [] and actions == [])
    finally:
        _harness.remove_tree(root_g)

    # --- a miss whose sources were cut is not coupled from the prefix ------
    root_c, mpath_c = _learn_repo("learn-cut")
    try:
        kept = ["src/m%02d.py" % (i,) for i in range(_ev_io.MAX_PATHS)]
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_cart.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        misses = [{"test": "tests/test_cart.py", "phases": ["P1"],
                   "sources": kept, "sourcesDropped": 3}]
        seam, real = _fake_runner(root_c, "RUN-FG-CUT", 1, steps, misses)
        code, lines = _drive(root_c, mpath_c, seam, real)
        coupling, bugs, actions = _plan_facts(root_c, mpath_c)
        check("fgl7 RED-FIRST: a miss whose sources the row cut is NOT "
              "coupled from the kept prefix (that would narrow the suite "
              "silently) - the bug is still filed, and the output says the "
              "sources were cut and where the full list lives: %r"
              % ((coupling.get("tests/test_cart.py"), actions, lines),),
              code == 1 and "tests/test_cart.py" not in coupling
              and actions.count("coupling.learned") == 0
              and actions.count("bug.add") == 1 and len(bugs) == 1
              and "sourcesDropped" in (bugs[0].get("description") or "")
              and any("no couple" in ln and "sourcesDropped" in ln
                      and "P1" in ln for ln in lines))
    finally:
        _harness.remove_tree(root_c)

    # --- a run that was not recorded leaves nothing to act on --------------
    root_n, mpath_n = _learn_repo("learn-unrecorded")
    try:
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_cart.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        misses = [{"test": "tests/test_cart.py", "phases": ["P1"],
                   "sources": ["src/cart.py"]}]
        seam, real = _fake_runner(
            root_n, "RUN-FG-LOST", 1, steps, misses,
            printed="  evidence: NOT recorded - the ledger is read-only")
        code, lines = _drive(root_n, mpath_n, seam, real)
        _coupling, bugs, actions = _plan_facts(root_n, mpath_n)
        check("fgl8 a runner that printed 'evidence: NOT recorded' is not "
              "second-guessed from the ledger (a row there is some other "
              "run's): nothing is written, and the output says why: %r"
              % ((actions, lines),),
              code == 1 and bugs == [] and actions == []
              and any("NOT recorded" in ln and ln.startswith(M.PREFIX)
                      for ln in lines))
    finally:
        _harness.remove_tree(root_n)

    # --- no evidence line: this run's row, never an earlier one ------------
    root_f, mpath_f = _learn_repo("learn-fallback")
    try:
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_cart.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        # AN EARLIER RUN at the same head, carrying a miss for another suite:
        # the fallback bounded by the head alone would pick this one too.
        _ev_io.append_row(root_f, {
            "v": 1, "runId": "RUN-FG-OLD", "ts": "2026-01-01T00:00:00Z",
            "scope": "full", "status": "failed",
            "testedState": {"head": _git_head(root_f)},
            "steps": [dict(steps[0], failingSuites=["tests/test_stale.py"])],
            "selectionMiss": [{"test": "tests/test_stale.py",
                               "phases": ["P1"], "sources": ["src/s.py"]}]})
        misses = [{"test": "tests/test_cart.py", "phases": ["P1"],
                   "sources": ["src/cart.py"]}]
        seam, real = _fake_runner(root_f, "RUN-FG-QUIET", 1, steps, misses,
                                  printed="  (no evidence line)")
        code, lines = _drive(root_f, mpath_f, seam, real)
        coupling, bugs, _actions = _plan_facts(root_f, mpath_f)
        check("fgl10 a runner that printed no evidence line is read off the "
              "newest full row stamped since this run began - the miss it "
              "carries is learned, and an earlier run's is not: %r"
              % ((sorted(coupling), [b.get("title") for b in bugs]),),
              code == 1 and "tests/test_cart.py" in coupling
              and "tests/test_stale.py" not in coupling
              and [b.get("title") for b in bugs]
              == [M.bug_title("tests/test_cart.py")])
    finally:
        _harness.remove_tree(root_f)

    # --- a verb that refuses is relayed, and changes no exit ---------------
    root_v, mpath_v = _learn_repo("learn-refused")
    try:
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_cart.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        misses = [{"test": "tests/test_cart.py", "phases": ["P9"],
                   "sources": ["src/cart.py"]}]
        seam, real = _fake_runner(root_v, "RUN-FG-REFUSED", 1, steps, misses)
        code, lines = _drive(root_v, mpath_v, seam, real)
        coupling, bugs, actions = _plan_facts(root_v, mpath_v)
        check("fgl11 a couple the verb refuses (its --phases names no phase "
              "of this plan) is printed with the verb's own refusal and exit "
              "code, the bug is still filed, and the exit is still the "
              "runner's: %r" % ((code, actions, lines[-1:]),),
              code == 1 and "tests/test_cart.py" not in coupling
              and actions == ["bug.add"]
              and any("--phases names" in ln for ln in lines)
              and any("couple for tests/test_cart.py exited 2" in ln
                      for ln in lines)
              and "learning verb(s) failed" in lines[-1])
    finally:
        _harness.remove_tree(root_v)

    _since_bound_cases(check)
    _named_catch_cases(check)
    _ambiguous_catch_cases(check)
    _learning_failure_cases(check)

    # --- the bug's words are the runner's own remedy's --------------------
    rtg = _loader.load_script("run-test-gate.py", "run_test_gate_for_full")
    miss = {"test": "tests/test_cart.py", "phases": ["P1", "P2"],
            "sources": ["src/cart.py"]}
    remedy = rtg._miss_remedy(miss, "RUN-X", "abc1234",
                              "/plan/docs/audit/audit-plan.json", "/plan")
    import shlex
    check("fgl9 the bug full-gate files carries the title and description "
          "the runner's printed remedy spells, so a bug filed by hand from "
          "that line and one filed here are the same bug: %r" % (remedy,),
          shlex.quote(M.bug_title(miss["test"])) in remedy
          and shlex.quote(M.bug_description(miss, "RUN-X", "abc1234"))
          in remedy)


def _parse(ts):
    import _usage_core
    return _usage_core.parse_ts(ts)


def _since(rows, started):
    """`_newest_full_since`'s runId, or the exception it raised - read so a
    version taking a different start shape is an observed red, not a crash
    that hides every case after it."""
    try:
        row = M._newest_full_since(rows, started)
    except Exception as exc:                               # noqa: BLE001
        return "raised %s" % (type(exc).__name__,)
    return row.get("runId") if row else None


def _since_bound_cases(check):
    # --- no evidence line and no row of this run: an earlier row is not it --
    root, mpath = _learn_repo("learn-no-row")
    try:
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_stale.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        _ev_io.append_row(root, {
            "v": 1, "runId": "RUN-FG-EARLIER", "ts": "2026-01-01T00:00:00Z",
            "scope": "full", "status": "failed",
            "testedState": {"head": _git_head(root)}, "steps": steps,
            "selectionMiss": [{"test": "tests/test_stale.py",
                               "phases": ["P1"], "sources": ["src/s.py"]}]})
        seam, real = _fake_runner(root, "RUN-FG-NONE", 1, steps,
                                  printed="  (no evidence line)", append=False)
        code, lines = _drive(root, mpath, seam, real)
        coupling, bugs, actions = _plan_facts(root, mpath)
        check("fgl12 RED-FIRST: the runner printed no evidence line and "
              "recorded no row, and the ledger holds an EARLIER red full row "
              "at the same head carrying a miss - nothing is written, and "
              "the output says no full row was stamped since the start; the "
              "mutation 'newest full row, unbounded' files the stale miss: %r"
              % ((code, actions, lines),),
              code == 1 and actions == [] and bugs == []
              and "tests/test_stale.py" not in coupling
              and any("no full row stamped since" in ln for ln in lines))
    finally:
        _harness.remove_tree(root)

    # --- the bound is a moment, never a spelling ---------------------------
    start = _parse("2026-09-27T18:05:46Z")

    def full(run_id, ts):
        return {"runId": run_id, "scope": "full", "ts": ts}

    got = [_since([full("FRAC", "2026-09-27T18:05:46.500Z")], start),
           _since([full("OFFSET", "2026-09-27T18:05:46+00:00")], start),
           _since([full("BAD", "yesterday")], start),
           _since([full("BEFORE", "2026-09-27T18:05:45Z")], start)]
    check("fgl13 RED-FIRST: a fractional ts and a +00:00 spelling of the start "
          "second are both since it; an unparseable ts and an earlier moment "
          "are not - text comparison misses the first two: %r" % (got,),
          got == ["FRAC", "OFFSET", None, None])
    newest = _since([full("OFFSET-LATER-TEXT", "2026-09-27T20:05:59+02:00"),
                     full("Z-LATER-MOMENT", "2026-09-27T18:06:00Z")], start)
    check("fgl14 RED-FIRST: the newest row is the latest MOMENT - "
          "20:05:59+02:00 sorts after 18:06:00Z as text and is a second "
          "earlier as time: %r" % (newest,),
          newest == "Z-LATER-MOMENT")
    try:
        floored = M.start_moment(start + 0.7)
    except Exception as exc:                               # noqa: BLE001
        floored = "raised %s" % (type(exc).__name__,)
    same = (_since([full("SAME-SECOND", "2026-09-27T18:05:46Z")], floored)
            if not isinstance(floored, str) else floored)
    check("fgl15 the start is floored to the whole second the runner stamps "
          "at, so a row written in the same second as a start taken later "
          "within it is still this run's (the mutation 'unfloored start' "
          "loses it): %r" % ((floored, same),),
          floored == start and same == "SAME-SECOND")


def _named_catch_cases(check):
    # --- a runner naming the suite relative to its own directory ------------
    root, mpath = _learn_repo("learn-relative")
    try:
        steps = [{"name": "ok", "exit": 1, "failingSuites": ["test_old.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        seam, real = _fake_runner(root, "RUN-FG-REL", 1, steps, misses=[])
        code, lines = _drive(root, mpath, seam, real)
        asked = [ln for ln in lines if ln.startswith(
            "%s learning: audit-task.py couple --caught for " % (M.PREFIX,))]
        coupling, _bugs, actions = _plan_facts(root, mpath)
        check("fgl16 RED-FIRST: a runner that names the coupled suite "
              "relative to its own directory (test_old.py for the plan's "
              "tests/test_old.py) is matched by the path-suffix reading the "
              "misses use, the catch is asked for under the PLAN'S key, and "
              "audit-task records it there - one coupling.caught row and a "
              "lastCaught on tests/test_old.py, no entry for test_old.py: "
              "%r" % ((code, asked, actions, sorted(coupling)),),
              code == 1 and asked == [
                  "%s learning: audit-task.py couple --caught for "
                  "tests/test_old.py" % (M.PREFIX,)]
              and actions == ["coupling.caught"]
              and bool((coupling.get("tests/test_old.py") or {})
                       .get("lastCaught"))
              and "test_old.py" not in coupling)
    finally:
        _harness.remove_tree(root)


def _ambiguous_catch_cases(check):
    # --- one bare name, two coupled suites carrying it ---------------------
    root, mpath = _learn_repo("learn-ambiguous")
    try:
        with open(mpath) as fh:
            plan = json.load(fh)
        head = _git_head(root)
        plan["meta"]["coupling"] = [
            {"test": test, "sources": [src],
             "basis": {"runId": "RUN-EARLIER", "head": head,
                       "phases": ["P1"]},
             "learnedAt": "2026-01-01T00:00:00Z"}
            for test, src in (("pkg_a/tests/test_c.py", "pkg_a/c.py"),
                              ("pkg_b/tests/test_c.py", "pkg_b/c.py"))]
        with open(mpath, "w") as fh:
            json.dump(plan, fh)
        steps = [{"name": "ok", "exit": 1, "failingSuites": ["test_c.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        seam, real = _fake_runner(root, "RUN-FG-AMBIG", 1, steps, misses=[])
        code, lines = _drive(root, mpath, seam, real)
        coupling, _bugs, actions = _plan_facts(root, mpath)
        said = [ln for ln in lines
                if ln.startswith("%s no catch credited for test_c.py"
                                 % (M.PREFIX,))]
        check("fgl18 RED-FIRST: one failure the runner named only as "
              "test_c.py, with pkg_a/ and pkg_b/tests/test_c.py both "
              "coupled, credits NEITHER - no couple --caught, no lastCaught, "
              "no journal row - says so naming both candidates, and exits "
              "with the runner's code: %r" % ((code, actions, said),),
              code == 1 and actions == []
              and not any(e.get("lastCaught") for e in coupling.values())
              and len(said) == 1
              and "pkg_a/tests/test_c.py" in said[0]
              and "pkg_b/tests/test_c.py" in said[0]
              and "still red" in lines[-1])
    finally:
        _harness.remove_tree(root)


def _learning_failure_cases(check):
    # --- a malformed row cannot take the runner's verdict with it ----------
    root, mpath = _learn_repo("learn-malformed")
    try:
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_cart.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        misses = [{"test": "tests/test_cart.py", "phases": ["P1"],
                   "sources": ["src/cart.py", 7]}]
        seam, real = _fake_runner(root, "RUN-FG-BAD", 1, steps, misses)
        try:
            code, lines = _drive(root, mpath, seam, real)
        except Exception as exc:                           # noqa: BLE001
            code, lines = "raised %s" % (type(exc).__name__,), []
        check("fgl17 RED-FIRST: a selectionMiss whose sources hold a "
              "non-string makes learning raise - main prints one learned-"
              "nothing line naming it, then the still-red line, and exits "
              "with the runner's code rather than a traceback: %r"
              % ((code, lines[-2:]),),
              code == 1 and len(lines) >= 2
              and lines[-2].startswith("%s learned nothing: " % (M.PREFIX,))
              and "still red" in lines[-1])
    finally:
        _harness.remove_tree(root)


# --- learning from a run recorded elsewhere -------------------------------------
# A CI build records its full run into its own shard and the shard is imported
# later; `--learn-from <runId>` is the only door through which that row teaches.
# The seam below records every command it is handed and REFUSES to play the
# runner: `--learn-from` runs nothing, so any call naming run-test-gate.py is the
# bug, and the audit-task verbs still run for real.
def _no_runner_seam():
    real = M._stream_subprocess
    runner_calls = []

    def seam(cmd, out):
        if os.path.basename(cmd[1]) == "run-test-gate.py":
            runner_calls.append(cmd)
            out("FULL GATE RED")
            return 1
        return real(cmd, out)
    return seam, real, runner_calls


def _learn_from(root, mpath, run_id, extra=None):
    """`(code, lines, runner_calls)` for `main` asked to learn from `run_id`."""
    seam, real, runner_calls = _no_runner_seam()
    lines = []
    M._stream_subprocess = seam
    try:
        code = M.main([mpath, "--project-dir", root, "--learn-from", run_id]
                      + list(extra or []), out=lines.append)
    finally:
        M._stream_subprocess = real
    return code, lines, runner_calls


def _imported_row(root, run_id, status="failed", scope="full", misses=None,
                  steps=None):
    """A red (or `status`) row as an imported CI shard holds it: written under
    a `ci-` writer's own file, never through this checkout's session shard.

    THE STEP READS AS FAILING WHATEVER `status` SAYS, so a green row is
    deliberately inconsistent with it: `status` is the verdict the refusal
    reads, and a row whose steps could teach nothing would let the mutation
    'drop the green refusal' pass by learning nothing anyway."""
    steps = steps if steps is not None else [
        {"name": "ok", "exit": 1,
         "failingSuites": ["tests/test_cart.py", "tests/test_old.py"],
         "failingSuitesBasis": _NAMED_BASIS}]
    row = {"v": 1, "runId": run_id, "ts": _ev_io._now(), "scope": scope,
           "status": status, "testedState": {"head": _git_head(root)},
           "steps": steps,
           "selectionMiss": misses if misses is not None else [
               {"test": "tests/test_cart.py", "phases": ["P1"],
                "sources": ["src/cart.py"]}]}
    _ev_io.append_row(root, row, writer="ci-imported")
    return row


def _prefixed(lines):
    return [ln for ln in lines if ln.startswith(M.PREFIX)]


def _learn_from_cases(check):
    # --- an imported red full row teaches, and nothing is run --------------
    root, mpath = _learn_repo("learn-from")
    try:
        _imported_row(root, "RUN-CI-RED")
        code, lines, runner_calls = _learn_from(root, mpath, "RUN-CI-RED")
        coupling, bugs, actions = _plan_facts(root, mpath)
        cart = coupling.get("tests/test_cart.py") or {}
        check("fglf1 RED-FIRST: --learn-from over an imported red full row "
              "with a named miss files the coupling, the bug and the catch "
              "the red branch would, exits 0, and never invokes the runner - "
              "the mutation 'run the full gate anyway' is what the empty "
              "runner list is here for: %r"
              % ((code, runner_calls, actions, lines[-1:]),),
              code == M.E_OK and runner_calls == []
              and cart.get("sources") == ["src/cart.py"]
              and (cart.get("basis") or {}).get("runId") == "RUN-CI-RED"
              and [b.get("title") for b in bugs]
              == ["SELECTION MISS: tests/test_cart.py"]
              and actions.count("coupling.learned") == 1
              and actions.count("bug.add") == 1
              and actions.count("coupling.caught") == 1
              and "lastCaught" not in cart)
        # --- the same run again: nothing new is filed ---------------------
        code2, lines2, runner_calls2 = _learn_from(root, mpath, "RUN-CI-RED")
        coupling2, bugs2, actions2 = _plan_facts(root, mpath)
        check("fglf2 learning twice from one run files nothing new - no "
              "second bug, no second coupling, no second catch row - exits "
              "0 and says the bug is already open: %r"
              % ((code2, actions2, _prefixed(lines2)),),
              code2 == M.E_OK and runner_calls2 == []
              and len(bugs2) == 1 and actions2 == actions
              and any("already open" in ln and bugs2[0].get("id") in ln
                      for ln in lines2))
    finally:
        _harness.remove_tree(root)

    # --- refusals: each is one reason line, a non-zero exit, and no write --
    root_r, mpath_r = _learn_repo("learn-from-refused")
    try:
        _imported_row(root_r, "RUN-CI-GREEN", status="passed")
        _imported_row(root_r, "RUN-CI-PHASE", scope="phase")
        refused = {}
        for run_id in ("RUN-CI-MISSING", "RUN-CI-GREEN", "RUN-CI-PHASE"):
            refused[run_id] = _learn_from(root_r, mpath_r, run_id)
        _coupling, bugs, actions = _plan_facts(root_r, mpath_r)
        said = dict((k, _prefixed(v[1])) for k, v in refused.items())
        check("fglf3 a run id the ledger does not hold is refused, exit 1, "
              "with one line naming it: %r" % (refused["RUN-CI-MISSING"][:2],),
              refused["RUN-CI-MISSING"][0] == M.E_FAIL
              and len(said["RUN-CI-MISSING"]) == 1
              and "RUN-CI-MISSING" in said["RUN-CI-MISSING"][0]
              and "no run" in said["RUN-CI-MISSING"][0])
        # THE ROW NAMES A MISS AND A NAMED FAILING SUITE on purpose, so the
        # mutation 'drop the green refusal' files a coupling and a bug here
        # instead of passing on a row that could teach nothing anyway.
        check("fglf4 RED-FIRST: a green full row is refused, exit 1, saying a "
              "green run has nothing to teach - even though the row carries "
              "a miss: %r" % (refused["RUN-CI-GREEN"][:2],),
              refused["RUN-CI-GREEN"][0] == M.E_FAIL
              and len(said["RUN-CI-GREEN"]) == 1
              and "passed" in said["RUN-CI-GREEN"][0]
              and "nothing to teach" in said["RUN-CI-GREEN"][0])
        check("fglf5 a red row that is not full scope is refused, exit 1, "
              "naming its scope: %r" % (refused["RUN-CI-PHASE"][:2],),
              refused["RUN-CI-PHASE"][0] == M.E_FAIL
              and len(said["RUN-CI-PHASE"]) == 1
              and "'phase'" in said["RUN-CI-PHASE"][0])
        check("fglf6 no refusal ran the runner or wrote to the plan: %r"
              % ((actions, bugs),),
              actions == [] and bugs == []
              and all(v[2] == [] for v in refused.values()))
    finally:
        _harness.remove_tree(root_r)

    # --- an unreadable ledger is named, never read as 'no such run' --------
    root_u, mpath_u = _learn_repo("learn-from-unreadable")
    try:
        ev = _ev_io.evidence_dir(root_u)
        os.makedirs(ev)
        torn = os.path.join(ev, "2026-09.ci-torn.jsonl")
        with open(torn, "wb") as fh:
            fh.write(b'{"runId": "RUN-CI-TORN", "scope": "full"')
        code, lines, runner_calls = _learn_from(root_u, mpath_u, "RUN-CI-TORN")
        said = _prefixed(lines)
        check("fglf7 a run id the readable ledger lacks, while a ledger file "
              "could not be read in full, is refused, exit 1, naming that "
              "file - the run may be on the line the read lost: %r" % (said,),
              code == M.E_FAIL and runner_calls == [] and len(said) == 1
              and "docs/audit/evidence/2026-09.ci-torn.jsonl" in said[0])
    finally:
        _harness.remove_tree(root_u)

    # --- a verb that refuses makes --learn-from exit 1 ---------------------
    # fgl11's fixture: `--phases` names a phase this plan does not hold, so
    # audit-task refuses the couple while the bug-add still lands.
    root_v, mpath_v = _learn_repo("learn-from-refused-verb")
    try:
        _imported_row(root_v, "RUN-CI-VERB", misses=[
            {"test": "tests/test_cart.py", "phases": ["P9"],
             "sources": ["src/cart.py"]}])
        code, lines, runner_calls = _learn_from(root_v, mpath_v, "RUN-CI-VERB")
        coupling, _bugs, actions = _plan_facts(root_v, mpath_v)
        check("fglf9 RED-FIRST: under --learn-from a verb audit-task refuses "
              "is printed with its exit code and makes the exit 1 - there is "
              "no runner's verdict to keep, so the failed learning is the "
              "answer; the bug still lands: %r" % ((code, lines[-1:]),),
              code == M.E_FAIL and runner_calls == []
              and "tests/test_cart.py" not in coupling
              and "bug.add" in actions
              and any("couple for tests/test_cart.py exited 2" in ln
                      for ln in lines)
              and lines[-1].startswith("%s learning from run RUN-CI-VERB ran "
                                       % (M.PREFIX,))
              and lines[-1].endswith("failed, printed above"))
    finally:
        _harness.remove_tree(root_v)

    # --- a ledger read that raises is a refusal quoting the error ---------
    root_x, mpath_x = _learn_repo("learn-from-raise")
    try:
        _imported_row(root_x, "RUN-CI-RAISE")
        real_read = _ev_io.read_rows

        def raising_read(project, config=None):
            raise OSError("the reader under test refused the ledger")
        _ev_io.read_rows = raising_read
        try:
            code, lines, runner_calls = _learn_from(root_x, mpath_x,
                                                    "RUN-CI-RAISE")
        finally:
            _ev_io.read_rows = real_read
        _coupling, bugs, actions = _plan_facts(root_x, mpath_x)
        said = _prefixed(lines)
        check("fglf10 RED-FIRST: a ledger read that raises refuses --learn-from, "
              "exit 1, in one line saying the ledger could not be read and "
              "quoting the reader's own error - never read as an empty "
              "ledger's 'no such run': %r" % (said,),
              code == M.E_FAIL and runner_calls == [] and actions == []
              and bugs == [] and len(said) == 1
              and "the evidence ledger could not be read" in said[0]
              and "the reader under test refused the ledger" in said[0])
    finally:
        _harness.remove_tree(root_x)

    # --- --learn-from beside --writer is a usage error ---------------------
    root_w, mpath_w = _learn_repo("learn-from-writer")
    try:
        _imported_row(root_w, "RUN-CI-W")
        code, lines, runner_calls = _learn_from(
            root_w, mpath_w, "RUN-CI-W", extra=["--writer", "ci-1"])
        _coupling, bugs, actions = _plan_facts(root_w, mpath_w)
        check("fglf8 --learn-from with --writer exits 2 (a learning run "
              "records no row, so a writer names nothing), runs nothing and "
              "writes nothing: %r" % ((code, lines),),
              code == M.E_USAGE and runner_calls == [] and actions == []
              and bugs == [])
    finally:
        _harness.remove_tree(root_w)


# --- a row's own miss is never its catch ----------------------------------------
# A suite a row lists in its `selectionMiss` is one no derived gate ran - the row
# says so itself - so crediting it as a catch by that row would record the
# coupling as having done work the same row says nothing did.
def _cart_caught(root, mpath):
    coupling, _bugs, _actions = _plan_facts(root, mpath)
    return (coupling.get("tests/test_cart.py") or {}).get("lastCaught")


def _catch_rule_cases(check):
    # --- two imported rows naming the same miss, learned in both orders ----
    for first, second in (("RUN-A", "RUN-B"), ("RUN-B", "RUN-A")):
        root, mpath = _learn_repo("own-miss-%s" % (first,))
        try:
            _imported_row(root, "RUN-A")
            _imported_row(root, "RUN-B")
            _learn_from(root, mpath, first)
            code, lines, _runner = _learn_from(root, mpath, second)
            said = [ln for ln in lines if ln.startswith(
                "%s no catch credited for tests/test_cart.py in run %s"
                % (M.PREFIX, second))]
            check("fgc1 RED-FIRST: %s then %s, both recording the miss "
                  "tests/test_cart.py - the second is NOT credited with a "
                  "catch of the coupling the first taught (no lastCaught), "
                  "and one line says its own row lists the suite as a miss: "
                  "%r" % (first, second, (code, _cart_caught(root, mpath),
                                          said)),
                  code == M.E_OK and _cart_caught(root, mpath) is None
                  and len(said) == 1 and "selectionMiss" in said[0])
        finally:
            _harness.remove_tree(root)

    # --- the red branch: a miss that WIDENS a coupling is not its catch ----
    root_w, mpath_w = _learn_repo("own-miss-widen")
    try:
        with open(mpath_w) as fh:
            plan = json.load(fh)
        plan["meta"]["coupling"].append({
            "test": "tests/test_cart.py", "sources": ["src/cart.py"],
            "basis": {"runId": "RUN-EARLIER", "head": _git_head(root_w),
                      "phases": ["P1"]},
            "learnedAt": "2026-01-01T00:00:00Z"})
        with open(mpath_w, "w") as fh:
            json.dump(plan, fh)
        steps = [{"name": "ok", "exit": 1,
                  "failingSuites": ["tests/test_cart.py", "tests/test_old.py"],
                  "failingSuitesBasis": _NAMED_BASIS}]
        misses = [{"test": "tests/test_cart.py", "phases": ["P1"],
                   "sources": ["src/cart.py", "src/tax.py"]}]
        seam, real = _fake_runner(root_w, "RUN-FG-WIDEN", 1, steps, misses)
        code, lines = _drive(root_w, mpath_w, seam, real)
        coupling, _bugs, _actions = _plan_facts(root_w, mpath_w)
        cart = coupling.get("tests/test_cart.py") or {}
        check("fgc2 RED-FIRST: a red run whose miss widens an existing "
              "coupling runs the widening `couple` and credits no catch to "
              "that suite, while the coupled suite it did not list as a miss "
              "is still credited: %r" % ((code, cart,
                                         coupling.get("tests/test_old.py")),),
              code == 1
              and cart.get("sources") == ["src/cart.py", "src/tax.py"]
              and "lastCaught" not in cart
              and bool((coupling.get("tests/test_old.py") or {})
                       .get("lastCaught")))
    finally:
        _harness.remove_tree(root_w)

    # --- ALLOW: a later run that fails a coupled suite it does not list ----
    # The mutation 'never credit a coupled suite at all' is what this is for.
    root_a, mpath_a = _learn_repo("own-miss-allow")
    try:
        _imported_row(root_a, "RUN-R1")
        _learn_from(root_a, mpath_a, "RUN-R1")
        _imported_row(root_a, "RUN-R2", misses=[])
        code, lines, _runner = _learn_from(root_a, mpath_a, "RUN-R2")
        check("fgc3 ALLOW: RUN-R2 fails tests/test_cart.py, coupled by RUN-R1, "
              "and does NOT list it as a miss - so the catch is credited: %r"
              % ((code, _cart_caught(root_a, mpath_a)),),
              code == M.E_OK and bool(_cart_caught(root_a, mpath_a)))
    finally:
        _harness.remove_tree(root_a)


# --- a runner's spelling, pinned to one tracked path before anything is filed --
def _pinned_learning_cases(check):
    # --- the runner names the suite from its own directory -----------------
    # The plan already couples backend/tests/test_x.py; the runner (started in
    # backend/tests) printed test_x.py, and the row's miss carries that
    # spelling. The one tracked path it pins to is what gets coupled and filed.
    root, mpath = _learn_repo("pin-relative")
    try:
        with open(mpath) as fh:
            plan = json.load(fh)
        plan["meta"]["coupling"].append({
            "test": "backend/tests/test_x.py", "sources": ["src/old.py"],
            "basis": {"runId": "RUN-EARLIER", "head": _git_head(root),
                      "phases": ["P1"]},
            "learnedAt": "2026-01-01T00:00:00Z"})
        with open(mpath, "w") as fh:
            json.dump(plan, fh)
        _imported_row(root, "RUN-PIN-REL", steps=[
            {"name": "ok", "exit": 1, "failingSuites": ["test_x.py"],
             "failingSuitesBasis": _NAMED_BASIS}], misses=[
            {"test": "test_x.py", "phases": ["P1"], "sources": ["src/new.py"]}])
        code, lines, _runner = _learn_from(root, mpath, "RUN-PIN-REL")
        coupling, bugs, actions = _plan_facts(root, mpath)
        check("fgp1 RED-FIRST: a miss the runner spelled test_x.py WIDENS the "
              "plan's backend/tests/test_x.py coupling and files its bug under "
              "that tracked path - no coupling and no bug file is ever the "
              "raw spelling: %r"
              % ((code, sorted(coupling),
                  (coupling.get("backend/tests/test_x.py") or {})
                  .get("sources"), [(b.get("title"), b.get("files"))
                                    for b in bugs], actions),),
              code == M.E_OK and "test_x.py" not in coupling
              and (coupling.get("backend/tests/test_x.py") or {})
              .get("sources") == ["src/old.py", "src/new.py"]
              and [(b.get("title"), b.get("files")) for b in bugs]
              == [("SELECTION MISS: backend/tests/test_x.py",
                   ["backend/tests/test_x.py"])]
              and "lastCaught" not in coupling["backend/tests/test_x.py"])
    finally:
        _harness.remove_tree(root)

    # --- one spelling, two sibling packages --------------------------------
    root_s, mpath_s = _learn_repo("pin-sibling")
    try:
        _imported_row(root_s, "RUN-PIN-SIB", steps=[
            {"name": "ok", "exit": 1, "failingSuites": ["tests/x.test.js"],
             "failingSuitesBasis": _NAMED_BASIS}], misses=[
            {"test": "tests/x.test.js", "phases": ["P1"],
             "sources": ["pkg1/src/x.js"]}])
        code, lines, _runner = _learn_from(root_s, mpath_s, "RUN-PIN-SIB")
        coupling, bugs, actions = _plan_facts(root_s, mpath_s)
        said = [ln for ln in lines if ln.startswith(
            "%s no couple for tests/x.test.js" % (M.PREFIX,))]
        check("fgp2 RED-FIRST: a miss spelled tests/x.test.js, which both "
              "pkg1/ and pkg2/tests/x.test.js end in, couples NOTHING, still "
              "files its bug naming no file, and one line says why naming "
              "both candidates: %r"
              % ((code, sorted(coupling), [(b.get("title"), b.get("files"))
                                          for b in bugs], said),),
              code == M.E_OK and sorted(coupling) == ["tests/test_old.py"]
              and actions.count("coupling.learned") == 0
              and [(b.get("title"), b.get("files")) for b in bugs]
              == [("SELECTION MISS: tests/x.test.js", [])]
              and len(said) == 1 and "pkg1/tests/x.test.js" in said[0]
              and "pkg2/tests/x.test.js" in said[0])
    finally:
        _harness.remove_tree(root_s)

    # --- the red branch names a ledger file it could not read in full ------
    rows = [{"runId": "RUN-OTHER", "scope": "full",
             "ts": "2026-09-27T18:05:46Z"}]
    lost = ["docs/audit/evidence/2026-09.ci-1.jsonl"]
    started = _parse("2026-09-27T18:05:40Z")
    _row, rec = M.find_row(rows, ["  evidence: recorded RUN-GONE"], started,
                           lost)
    _row, since = M.find_row([], ["  (no evidence line)"], started, lost)
    _row, clean = M.find_row(rows, ["  evidence: recorded RUN-GONE"], started,
                             [])
    check("fgp3 RED-FIRST: a run the readable rows do not hold is never "
          "called absent while a ledger file was read with losses - both "
          "lookups name the file; with none lost, no such clause: %r"
          % ((rec, since, clean),),
          lost[0] in (rec or "") and lost[0] in (since or "")
          and "could not be read in full" in (rec or "")
          and "could not be read in full" not in (clean or "x"))

    # --- which project a manifest outside the default layout belongs to ----
    root_p = _harness.fixture_root("full-gate-layout-")
    try:
        os.makedirs(os.path.join(root_p, "plans"))
        os.makedirs(os.path.join(root_p, ".claude"))
        mpath_p = os.path.join(root_p, "plans", "plan.json")
        with open(mpath_p, "w") as fh:
            json.dump({"meta": {"version": 3, "fullGate": ["ok"],
                                "buildCommands": {"ok": "true"}},
                       "phases": []}, fh)
        called = []
        real = M._stream_subprocess
        M._stream_subprocess = lambda cmd, out: called.append(cmd) or 0
        try:
            code = M.main([mpath_p], out=(lambda _l: None))
        finally:
            M._stream_subprocess = real
        cmd = called[0] if called else []
        at = cmd.index("--project-dir") + 1 if "--project-dir" in cmd else 0
        check("fgp4 RED-FIRST: a manifest at <root>/plans/plan.json, <root> "
              "holding .claude/, resolves the project the plugin's way "
              "(`_panel_write.project_of_manifest`) and hands it to the "
              "runner - never the directory three levels up: %r" % (cmd,),
              code == M.E_OK and at
              and os.path.realpath(cmd[at]) == os.path.realpath(root_p))
    finally:
        _harness.remove_tree(root_p)


# --- --learn-from's exit when learning itself goes wrong -----------------------
def _learn_from_exit_cases(check):
    # --- a row whose learning raises -----------------------------------------
    root, mpath = _learn_repo("learn-from-raises")
    try:
        _imported_row(root, "RUN-CI-BAD", misses=[
            {"test": "tests/test_cart.py", "phases": ["P1"],
             "sources": ["src/cart.py", 7]}])
        try:
            code, lines, _runner = _learn_from(root, mpath, "RUN-CI-BAD")
        except Exception as exc:                           # noqa: BLE001
            code, lines = "raised %s" % (type(exc).__name__,), []
        said = [ln for ln in lines if "learning raised" in ln]
        check("fglf11 RED-FIRST: a row whose learning raises (a non-string "
              "source) exits 1 with one 'learning raised' line naming the "
              "error, never a traceback: %r" % ((code, said),),
              code == M.E_FAIL and len(said) == 1
              and said[0].startswith("%s learned nothing from run RUN-CI-BAD"
                                     % (M.PREFIX,)))
    finally:
        _harness.remove_tree(root)

    # --- the plan cannot be re-read after main loaded it ---------------------
    root_p, mpath_p = _learn_repo("learn-from-reread")
    try:
        _imported_row(root_p, "RUN-CI-REREAD")
        real_load = M._mio.load_manifest
        calls = []

        def second_fails(path):
            calls.append(path)
            if len(calls) > 1:
                raise ValueError("the loader under test refused a re-read")
            return real_load(path)
        M._mio.load_manifest = second_fails
        try:
            code, lines, _runner = _learn_from(root_p, mpath_p, "RUN-CI-REREAD")
        finally:
            M._mio.load_manifest = real_load
        said = [ln for ln in lines if "could not be re-read" in ln]
        check("fglf12 RED-FIRST: a plan that cannot be re-read for learning "
              "exits 1 with one line saying so and quoting the loader: %r"
              % ((code, said),),
              code == M.E_FAIL and len(said) == 1
              and "the loader under test refused a re-read" in said[0])
    finally:
        _harness.remove_tree(root_p)

    # --- a red row whose steps name nothing -----------------------------------
    root_n, mpath_n = _learn_repo("learn-from-unnamed")
    try:
        _imported_row(root_n, "RUN-CI-TAIL", misses=[], steps=[
            {"name": "ok", "exit": 1, "failingSuites": ["tests/test_cart.py"],
             "failingSuitesBasis": _TAIL_BASIS}])
        code, lines, _runner = _learn_from(root_n, mpath_n, "RUN-CI-TAIL")
        said = _prefixed(lines)
        check("fglf13 RED-FIRST: a red row whose runner named no suite ends in "
              "the 'learned nothing ... each line above says why' line, after "
              "the line giving the step's basis, and exits 0 - the learning "
              "ran and found nothing to file: %r" % ((code, said),),
              code == M.E_OK and len(said) >= 2
              and _TAIL_BASIS in said[-2]
              and said[-1] == ("%s learned nothing from run RUN-CI-TAIL: each "
                               "line above says why" % (M.PREFIX,)))
    finally:
        _harness.remove_tree(root_n)


def _selftest():
    def body(check):
        _delegation_cases(check)
        _end_to_end_cases(check)
        _learning_cases(check)
        _learn_from_cases(check)
        _catch_rule_cases(check)
        _pinned_learning_cases(check)
        _learn_from_exit_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_full_gate.py --selftest\n")
    raise SystemExit(2)
