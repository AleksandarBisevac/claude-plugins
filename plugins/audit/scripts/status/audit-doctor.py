#!/usr/bin/env python3
"""
Answer "is this working?" before you find out the hard way — stdlib only.

Every failure this reports was previously discoverable only by hitting it: a guard
silently off because no interpreter resolved, a gate command refusing because
`gitRoot` points at a non-repo, a phase that will die at commit time because a task
file lives inside a submodule, `buildCommands` naming a runner that is not installed,
metering writing nothing. The README covered these as Troubleshooting prose, which
is help you can only find once you already know the symptom.

    audit-doctor.py [--project DIR] [--json] [--deep] [--selftest]

It reuses the checks that already exist rather than reimplementing them —
`_config_rules.validate_config`, `_manifest_rules.validate`,
`_status_facts.submodule_conflicts`, `usage_ledger.find_ledger_dir` — so a rule can
never mean one thing here and another at the gate. The sharded-layout assertion
moved here out of ci.yml for the same reason: CI and this command now call one
implementation.

READ-ONLY BY CONSTRUCTION. It never writes, never takes a lock, and never runs a
`buildCommands` entry — it resolves the executable each one names and reports
whether it exists. A doctor that runs your test suite is not a diagnostic, it is a
build; and one that mutates state cannot be run on a repo mid-phase.

Output classes match the rest of the plugin:
  OK       — checked and healthy
  WARNING  — works, but something will bite later; or a fact this read-only
             command may not establish, named as such rather than as its
             absence (`sandbox`, `secret rules`). Exit stays 0 either way
  FINDING  — broken now (exit 1)
Exit: 0 healthy (warnings allowed) · 1 findings · 2 usage error.

WHAT THIS FILE IS NOW: THE ORDER, AND THE PUBLIC SURFACE. It was 1,456 lines, and
the size was the symptom rather than the fault — the checks shared one file
because `diagnose()` calls every one of them. They are six modules now, cut where the
file's own section markers already cut it, and the 646-line `hooks, ledger &
trail` block cut again at the three seams inside it:

  `_doctor_report`       L2  the collector, the loader, the two constants
  `_doctor_ado`          L3  the connector's operational half
  `_doctor_hygiene`      L3  what is HELD (locks) and what is LEAKING (git)
  `_doctor_setup`        L4  interpreter, git, config, manifest, shards, submodules
  `_doctor_trail`        L4  hook state, the usage ledger, the journal chain
  `_doctor_completions`  L4  the `task.complete` receipts against the plan
  `_doctor_policy`       L5  areas, the capability policy, the build runners

What is left here is the one thing that could not go into a piece: `diagnose()`
decides the ORDER, and the order is not arbitrary — `check_config` produces the
`cfg`/`cfg_mod` pair, `check_git` the git root and `check_manifest` the manifest
that ten of the checks after them take as arguments, so those three run first and
in that sequence. `render()` and `main()` stayed with it because a report's ORDER
and its RENDERING are the same subject: the rows come out in the order this file
put them in.

AND THE NAMES. Every name those six modules hold is re-exported here, as a thin
module-level alias rather than a copy, because this module is what the suite and
the command both spell. `_manifest_rules` keeps a dozen aliases for the same
reason; the alternative was making every caller learn which of six files a check
now sits in, for a check that has not changed.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_audit_doctor.py`, byte-identical labels and all — see
`plugins/audit/tests/_harness.py`. They moved WHOLE: 53 of them re-`diagnose()` one
temp repository that the suite mutates step by step, so the sequence is the test.
`_json_ok()` went with them (its only caller was one case). `_load()` stayed in the
product — it is how the checks reach `_config` and `guard-capabilities` in
`hooks/`, and `_manifest_io`, `_areas`, `_policy`, `_panel_discovery` and
`usage_ledger` in `scripts/` — and it now lives in `_doctor_report` where all six
check modules can share the one definition.
"""
import argparse
import json
import os
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

import _cli_fmt  # noqa: E402  (the one place CLI color lives - mode resolution + paint)
import _doctor_report as _base  # noqa: E402  (Report, the loader, the constants)
import _doctor_setup as _setup  # noqa: E402  (interpreter, git, config, manifest)
import _doctor_policy as _policy_checks  # noqa: E402  (areas, policy, build runners)
import _doctor_ado as _ado  # noqa: E402  (the ADO connector's operational half)
import _doctor_trail as _trail  # noqa: E402  (hook state, ledger, journal chain)
import _doctor_completions as _completions  # noqa: E402  (the task.complete receipts)
import _doctor_hygiene as _hygiene  # noqa: E402  (locks, and local artifacts in git)

# --- the re-exported surface ----------------------------------------------------
# ALIASES, NOT COPIES. Each name below is the SAME object the module beside it
# defines, so there is one definition of every check and one of every constant.
# They exist because this module is what `tests/test_audit_doctor.py` loads and
# what `diagnose()` calls, and a split that made either of them learn which of six
# files a check moved to would be charging the caller for a change it did not ask
# for. `tests/test__doctor_report.py` pins the identity of the whole set with `is`,
# so a re-export that forks into a second definition fails by name.
Report = _base.Report
_load = _base._load
_HOOKS = _base._HOOKS
LAUNCHER_INTERPRETERS = _base.LAUNCHER_INTERPRETERS
RECENT_DAYS = _base.RECENT_DAYS

check_interpreter = _setup.check_interpreter
check_sandbox = _setup.check_sandbox
settings_sources = _setup.settings_sources
read_settings = _setup.read_settings
sandbox_state = _setup.sandbox_state
env_deny_rules = _setup.env_deny_rules
check_git = _setup.check_git
check_config = _setup.check_config
check_plan_gate = _setup.check_plan_gate
check_manifest = _setup.check_manifest
_check_shards = _setup._check_shards
check_submodules = _setup.check_submodules

check_areas = _policy_checks.check_areas
check_policy = _policy_checks.check_policy
check_build_commands = _policy_checks.check_build_commands
check_plan_skills = _policy_checks.check_plan_skills
check_branch_naming = _policy_checks.check_branch_naming
_leading_executable = _policy_checks._leading_executable

check_ado = _ado.check_ado

check_hooks_fired = _trail.check_hooks_fired
bash_state_shape = _trail.bash_state_shape
state_shape_drift = _trail.state_shape_drift
running_plugin_verdict = _trail.running_plugin_verdict
check_running_plugin = _trail.check_running_plugin
check_ledger = _trail.check_ledger
_journal_never_committed = _trail._journal_never_committed
check_journal = _trail.check_journal

_hours_between = _completions._hours_between
check_completions = _completions.check_completions
check_evidence_pointers = _completions.check_evidence_pointers

check_locks = _hygiene.check_locks
check_local_artifacts = _hygiene.check_local_artifacts


# --- diagnose / render / cli ----------------------------------------------------
def diagnose(project, deep=False):
    """Run every check. Returns a Report. `deep` adds the journal-in-commit
    cross-check to check_completions (read-only, just slower)."""
    rep = Report()
    check_interpreter(rep)
    # Next, because it is the same question one layer down: `check_interpreter`
    # asks whether the guards can run at all, and this asks whether the layer they
    # lean on is there. Neither takes the cfg/git/manifest trio, so both precede it.
    check_sandbox(rep, project)
    cfg, cfg_mod = check_config(rep, project)
    git_root = check_git(rep, project, cfg)
    manifest_rel, manifest = check_manifest(rep, project, cfg)
    check_plan_gate(rep, project, cfg, cfg_mod, manifest_rel)
    check_submodules(rep, project, cfg, manifest, git_root)
    check_areas(rep, project, cfg, manifest, manifest_rel)
    # ONE discovery scan for the two checks that need one. `check_policy`'s own
    # docstring sets that rule ("One discovery scan per run, batched across
    # kinds"), and F195 added a second reader of the same inventory - so the scan
    # is memoised here rather than each check calling it. Both take `_discover` as
    # a seam their selftests already use, so the sharing costs neither of them
    # their testability.
    _scanned = {}

    def _scan_once(proj, home=None):
        key = (proj, home)
        if key not in _scanned:
            mod = _policy_checks._load("_panel_discovery", "_panel_discovery.py")
            _scanned[key] = mod.discover(proj, home=home)
        return _scanned[key]

    check_policy(rep, project, cfg, cfg_mod, manifest, _discover=_scan_once)
    # F195: the skills the plan NAMES, against what this machine can find. Beside
    # `check_build_commands` on purpose - a runner that is not installed and a
    # reviewer that is not installed are the same claim, and they now read as a
    # pair instead of one warning and one silence.
    check_plan_skills(rep, project, manifest, _discover=_scan_once)
    check_build_commands(rep, project, manifest)
    check_branch_naming(rep, project, manifest, git_root)
    check_ado(rep, project, manifest)
    check_hooks_fired(rep, project, cfg, cfg_mod)
    # Directly after it, because they are one question asked twice: "hooks" says
    # whether anything has run here, and this says WHICH COPY ran it. Reading the
    # second without the first is how a guard several releases behind stayed
    # invisible while the command asked to name it answered about the
    # installation (F228).
    check_running_plugin(rep, project, cfg, cfg_mod)
    check_ledger(rep, project, cfg, manifest_rel)
    check_journal(rep, project, cfg, cfg_mod, git_root)
    check_completions(rep, project, cfg, manifest, manifest_rel, git_root,
                      deep=deep)
    check_evidence_pointers(rep, project, manifest)
    check_locks(rep, git_root, project, manifest_rel)
    check_local_artifacts(rep, project, cfg, cfg_mod, manifest, git_root)
    return rep


def render(rep, project, pt=None):
    """Plain ASCII, printed verbatim by the command - no re-formatting needed.

    `pt` is a _cli_fmt.Painter; None (every pre-color caller) means plain.
    Only the [OK]/[WARNING]/[FINDING] level tokens are painted - restrained
    on purpose - and a disabled painter returns its input unchanged, so
    plain mode stays byte-identical to the pre-color render."""
    pt = pt or _cli_fmt.PLAIN
    role = {"OK": "ok", "WARNING": "warn", "FINDING": "finding"}
    lines = ["AUDIT DOCTOR  %s" % project, ""]
    width = max([len(r["check"]) for r in rep.rows] or [7])
    for r in rep.rows:
        lines.append("  %s %-*s  %s" % (
            pt.paint("[%-7s]" % r["level"], role.get(r["level"], "")),
            width, r["check"], r["detail"]))
        if r["fix"]:
            lines.append("  %s  %s-> %s" % (" " * 9, " " * width, r["fix"]))
    c = rep.counts()
    lines.append("")
    lines.append("  %d ok - %d warning(s) - %d finding(s)"
                 % (c["OK"], c["WARNING"], c["FINDING"]))
    if c["FINDING"]:
        lines.append("  Findings are broken now. Fix those first.")
    elif c["WARNING"]:
        lines.append("  No findings - a warning will bite later, or names "
                     "something this command could not establish.")
    else:
        lines.append("  Healthy.")
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(
        prog="audit-doctor.py",
        description="Diagnose an audit plugin setup. Read-only.")
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--deep", action="store_true",
                    help="also verify each task commit carries the journal "
                         "file that records it (read-only, slower)")
    ap.add_argument("--color", choices=list(_cli_fmt.MODES), default="auto",
                    help="ANSI color for the terminal render (auto colors "
                         "only a TTY and respects NO_COLOR; --json never "
                         "colors)")
    args = ap.parse_args(argv)

    project = os.path.abspath(args.project)
    if not os.path.isdir(project):
        sys.stderr.write("ERROR: %s is not a directory\n" % project)
        return 2

    rep = diagnose(project, deep=args.deep)
    if args.as_json:
        print(json.dumps({"project": project, "counts": rep.counts(),
                          "checks": rep.rows}, indent=2))
    else:
        print(render(rep, project, pt=_cli_fmt.painter(args.color)))
    return rep.exit_code()


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to `main`, which would diagnose the
        # current directory and exit on its verdict. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-doctor.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_doctor.py - run that file instead.")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
