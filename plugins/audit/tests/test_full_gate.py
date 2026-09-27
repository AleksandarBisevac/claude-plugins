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


def _full_repo(name, fullgate=("ok",), buildcommands=None):
    """A committed git repository whose plan declares `meta.fullGate` (or does
    not, when `fullgate=None`) - the same fixture shape
    `test_run_test_gate.py`'s `_full_repo` builds, kept independent here
    rather than imported: a test file reaching into another test file's
    private helper is the same sideways edge `_deps.layer_violations()`
    refuses between production modules.
    """
    root = _harness.fixture_root("full-gate-")
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, ".claude"))
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
    for arg in (["add", "--", "docs", ".claude"],
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


def _selftest():
    def body(check):
        _delegation_cases(check)
        _end_to_end_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_full_gate.py --selftest\n")
    raise SystemExit(2)
