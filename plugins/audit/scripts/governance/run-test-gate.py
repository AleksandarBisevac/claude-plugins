#!/usr/bin/env python3
"""Run a phase's test gate, and answer the two questions an exit code cannot.

F193, measured live. A docs task's gate was `pre-commit run --all-files`, which
`/audit:init` had read off the repo's own config. Running it MODIFIED five source
files the task does not own -- `isort` and `black` are fix-in-place, and they
reported `Passed` BECAUSE they rewrote them. Had the run reached its commit step,
a documentation task would have carried +33/-62 of backend reformatting.

Then the same run produced the opposite failure. Narrowed to
`pre-commit run --files <the task's two markdown files>`, every hook SKIPPED --
that repo configures Python hooks only. Exit 0, zero checks performed, and the
task went to `done` on it.

SO ONE DESIGN PRODUCED BOTH FAILURE MODES, AND THE EXIT CODE SEPARATED NEITHER
FROM A REAL VERDICT: a gate that did too much, and a gate that did nothing. This
script exists because the two questions that tell them apart are cheap and
nobody was asking either:

  * DID THE GATE CHANGE THE TREE? `git status --porcelain` before and after. A
    gate is a MEASUREMENT; one with side effects has answered a different
    question than the one asked, and a commit built on it carries work nobody
    reviewed. Any difference refuses the commit step regardless of the gate's own
    exit code.
  * DID ANYTHING ACTUALLY RUN? Runners that say so are read and the count is
    reported. `pre-commit` prints one line per hook and says `Skipped`; nothing
    read it. A count of zero is reported as `NO CHECK RAN`, which is not the same
    answer as green and must never be spelled like it.

WHY A SCRIPT AND NOT AN INSTRUCTION. `reference/orchestrator.md` could tell the
orchestrator to bracket the gate, and it would -- most of the time. That is the
argument `journal-writes.py` makes against a prompt in its own docstring: a rule
depending on the model remembering holds until a session forgets, a harness runs
a different orchestrator, or somebody adds a gate by hand next year. The bracket
lives in code so the gate cannot be run without it.

WHAT IT DOES NOT DO. It does not narrow the gate to the task's files. That is a
change to what a per-task gate MEANS, it would alter behaviour for every manifest
already written, and it is a decision rather than a repair -- so the refusal names
the option and leaves the choice to a human. What this guarantees is that neither
outcome is silent.

Exit codes:
  0  every command passed, the tree is unchanged, and at least one check ran
  1  a command failed, or the gate mutated the tree, or nothing ran
  2  the gate could not be asked (no manifest, no such phase)
"""
import argparse
import json
import os
import subprocess
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _manifest_io as _mio  # noqa: E402  (dual-format loader: single file OR shards)

E_OK, E_FAIL, E_ASK = 0, 1, 2

# --- how much did it do -------------------------------------------------------
# Runners that report their own step count, and the words they end a step with.
# Read as a COUNT and never as a verdict - the verdict is the exit code's job, and
# what was missing is the SIZE of the thing behind it. A runner absent from this
# table yields `None`, which is reported as "not knowable from this runner" and
# never as zero: guessing zero would refuse a passing gate, and guessing one would
# bless a skipped one.
_STEP_WORDS = {
    "pre-commit": ("Passed", "Failed", "Skipped"),
}


def _porcelain(project):
    """`git status --porcelain` as a set of lines, or None when git cannot answer.

    None is NOT an empty tree. A repository git refuses to describe is a basis
    this script does not have, and reporting that as "nothing changed" would be
    the false clean sheet the whole file exists to prevent.
    """
    try:
        out = subprocess.run(["git", "-C", project, "status", "--porcelain"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=60)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return set(ln for ln in out.stdout.decode("utf-8", "replace").splitlines()
               if ln.strip())


def ran_count(command, text):
    """How many checks a runner reported doing, or None when it does not say."""
    words = None
    for name, tup in sorted(_STEP_WORDS.items()):
        if name in command:
            words = tup
            break
    if words is None:
        return None
    passed, failed, _skipped = words
    ran = 0
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.endswith(passed) or stripped.endswith(failed):
            ran += 1
    return ran


def gate_of(manifest, phase_id):
    """`(commands, error)` -- `[(name, command)]` for one phase's resolved gate.

    Resolved through `meta.buildCommands` exactly as the orchestrator resolves it;
    a second resolution here would be a second answer to "what is this phase's
    gate". An entry naming no build command is carried through verbatim, because
    it may be a literal shell command and refusing it would make this script
    decide what a gate is allowed to be.
    """
    phases = [p for p in (manifest.get("phases") or [])
              if isinstance(p, dict) and p.get("id") == phase_id]
    if not phases:
        return None, "no phase %r in this manifest" % (phase_id,)
    entries = [e for e in (phases[0].get("testGate") or [])
               if isinstance(e, str) and e.strip()]
    build = ((manifest.get("meta") or {}).get("buildCommands") or {})
    if not isinstance(build, dict):
        build = {}
    return [(e, build.get(e, e)) for e in entries], None


def _shell(project, command):
    try:
        out = subprocess.run(command, shell=True, cwd=project,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=3600)
    except Exception as exc:
        return 127, "could not run: %s" % (exc,)
    return out.returncode, out.stdout.decode("utf-8", "replace")


def run_gate(project, commands, runner=None):
    """Run each command bracketed by a working-tree snapshot; return the answer.

    A dict rather than an exit code, for `verify-invariants.py`'s reason: a
    function that only returned a verdict could not be tested without building a
    repository around it, and `runner` is the seam the cases drive.
    """
    runner = runner or _shell
    before = _porcelain(project)
    steps = []
    for name, command in commands:
        code, text = runner(project, command)
        steps.append({"name": name, "command": command, "exit": code,
                      "ran": ran_count(command, text)})
    after = _porcelain(project)
    if before is None or after is None:
        mutated = []
        basis = "git could not describe the tree, so mutation is UNKNOWN"
    else:
        mutated = sorted(after - before)
        basis = "git described the tree before and after"
    counts = [s["ran"] for s in steps if s["ran"] is not None]
    return {"steps": steps, "mutated": mutated, "treeBasis": basis,
            "ranTotal": sum(counts) if counts else None,
            "failed": [s["name"] for s in steps if s["exit"] != 0]}


def render(res, out=print):
    """Print the answer and return the exit code it earns."""
    for step in res["steps"]:
        ran = step["ran"]
        out("  %-12s exit %-3d %s"
            % (step["name"], step["exit"],
               "%d check(s) ran" % ran if ran is not None
               else "check count not knowable from this runner"))
    code = E_OK
    if res["failed"]:
        out("GATE RED: %s" % ", ".join(res["failed"]))
        code = E_FAIL
    if res["mutated"]:
        # Said even when the gate also failed: two different facts, and a reader
        # who fixed the failure would otherwise meet the rewrite afterwards.
        out("GATE MUTATED THE TREE: %s" % ", ".join(res["mutated"]))
        out("  a gate is a measurement. Do NOT commit on this run - the diff now "
            "carries work no task owns and no review saw. Revert those files, "
            "then either use the read-only spelling of the check (`--check` "
            "rather than `--write`, `ruff check` rather than `ruff --fix`) or "
            "scope the gate to the task's own files.")
        code = E_FAIL
    if res["ranTotal"] == 0:
        out("NO CHECK RAN: every step reported zero checks. That is exit 0 and it "
            "is not a verdict - a gate that skipped everything and a gate that "
            "verified everything are the same exit code, and this is the one that "
            "cannot sign anything off.")
        code = E_FAIL
    if res["treeBasis"].startswith("git could not"):
        out("  basis: %s" % res["treeBasis"])
    if code == E_OK:
        out("GATE GREEN: %s, tree unchanged%s"
            % (", ".join(s["name"] for s in res["steps"]) or "no commands",
               "" if res["ranTotal"] is None
               else ", %d check(s) ran" % res["ranTotal"]))
    return code


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="run-test-gate.py", add_help=True)
    p.add_argument("manifest")
    p.add_argument("phase")
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_ASK if exc.code else E_OK
    project = args.project_dir or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(args.manifest))))
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        out("[run-test-gate] cannot read the manifest: %s" % exc)
        return E_ASK
    commands, err = gate_of(manifest, args.phase)
    if err:
        out("[run-test-gate] %s" % err)
        return E_ASK
    if not commands:
        # The EMPTY gate is a designed state (`audit-task.py:_phase_gate`), so it
        # is reported as itself rather than as a pass: sign-off rests on review
        # alone, and saying "green" here would claim a measurement nobody made.
        out("[run-test-gate] %s declares an EMPTY gate: nothing here can prove it "
            "done, so sign-off rests on review alone" % (args.phase,))
        return E_OK
    res = run_gate(project, commands)
    if args.as_json:
        out(json.dumps(res, indent=2, sort_keys=True))
        return E_FAIL if (res["failed"] or res["mutated"]
                          or res["ranTotal"] == 0) else E_OK
    out("[run-test-gate] %s: %d command(s)" % (args.phase, len(commands)))
    return render(res, out=out)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("run-test-gate.py: cases live in "
              "plugins/audit/tests/test_run_test_gate.py")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
