#!/usr/bin/env python3
"""
Is the setup itself there — an interpreter, a git root, a config, a manifest?

Split out of `audit-doctor.py`. These six checks are the ones every other check
in the doctor is standing on: `check_config` returns the `cfg`/`cfg_mod` pair
the rest take as arguments, `check_git` returns the git root, `check_manifest`
returns the manifest and the path it was read from. That is why they are one
module rather than two — the file's own `# --- checks: environment ---` and
`# --- checks: config & manifest ---` markers are kept below, but the seam
between them is a heading, not a dependency, and nothing else in the doctor can
run before all six have.

It reuses the checks that already exist rather than reimplementing them, which
is also why the three imports below are IMPORTS and not `_load(...)` calls:
`_config_rules`, `_manifest_rules` and `_status_facts` are the library halves
that came out from under `validate-config.py`, `validate-manifest.py` and
`audit-status.py`, and reaching the commands instead is what put four entries in
`_deps.KNOWN_LAYER_DEBT` before those splits.

Layer 4, and the manifest rules are what set the floor: `_manifest_rules` sits
at layer 3 since it was cut into five, so its consumers cannot sit below 4.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__doctor_setup.py` - see
`plugins/audit/tests/_harness.py`.
"""
import json
import os
import shutil
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

import _doctor_report as _base  # noqa: E402  (Report, the loader, the constants)
import _manifest_rules  # noqa: E402  (the manifest rules, at layer 3 - imported, not loaded)
import _status_facts  # noqa: E402  (rollup/readiness/gate facts, at layer 2)
import _config_rules  # noqa: E402  (the audit.config.json rules, at layer 2)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `audit-doctor.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
_load = _base._load
_HOOKS = _base._HOOKS
LAUNCHER_INTERPRETERS = _base.LAUNCHER_INTERPRETERS


# --- checks: environment --------------------------------------------------------
def check_interpreter(rep):
    """Which interpreter the guard hooks will actually resolve.

    py-launch.sh walks python3 -> python -> py with shell builtins only. If none
    resolve, the blocking guards emit a manual-approval prompt rather than failing
    open - loud, but it means the guards are not enforcing anything."""
    found = [name for name in LAUNCHER_INTERPRETERS if shutil.which(name)]
    if not found:
        rep.finding("interpreter",
                    "none of %s is on PATH, so every guard hook falls back to a "
                    "manual-approval prompt and enforces nothing"
                    % ", ".join(LAUNCHER_INTERPRETERS),
                    "install Python 3 and make sure it is on the PATH Claude Code sees")
        return
    launcher = os.path.join(_HOOKS, "py-launch.sh")
    if not os.path.exists(launcher):
        rep.finding("interpreter", "py-launch.sh is missing from %s" % _HOOKS)
        return
    rep.ok("interpreter",
           "hooks will use %s (candidates on PATH: %s)" % (found[0], ", ".join(found)))


def check_git(rep, project, cfg):
    """The git root the orchestrator will run git against."""
    git_root = os.path.abspath(os.path.join(project, cfg.get("gitRoot") or "."))
    if not shutil.which("git"):
        rep.finding("git", "git is not on PATH; every mutating /audit command will stop")
        return None
    try:
        out = subprocess.run(["git", "-C", git_root, "rev-parse", "--show-toplevel"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=15)
    except Exception as exc:
        rep.finding("git", "could not run git in %s: %s" % (git_root, exc))
        return None
    if out.returncode != 0:
        rep.finding("git",
                    "%s is not a git repository" % git_root,
                    "set meta.gitRoot (and the gitRoot config key) to the repo's "
                    "path relative to this project, or run from inside the repo")
        return None
    top = out.stdout.decode("utf-8", "replace").strip()
    rep.ok("git", "git root resolves to %s" % top)
    return top


# --- checks: config & manifest --------------------------------------------------
def check_config(rep, project):
    """Config parses, validates, and which plan-gate tier it produces."""
    cfg_mod = _load("_config", "_config.py", _HOOKS)
    path = os.path.join(project, ".claude", "audit.config.json")
    cfg = cfg_mod.load(project)

    if not os.path.exists(path):
        rep.ok("config", "no .claude/audit.config.json - safe defaults are active")
    elif cfg.get("_configError"):
        rep.finding("config",
                    "%s is present but unreadable (%s), so the project's custom "
                    "patterns, rules and thresholds are NOT applied"
                    % (path, cfg["_configError"]),
                    "fix the JSON; /audit:* commands refuse until it parses")
    else:
        # `_config_rules` (layer 2), imported at the top rather than `_load(...)`-ed:
        # this file (L7) loading `validate-config.py` (L7) was one of the edges
        # `_deps.KNOWN_LAYER_DEBT` recorded.
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        findings, warnings = _config_rules.validate_config(raw)
        if findings:
            rep.finding("config", "; ".join(findings),
                        "fix the config, or run /audit:panel to edit it with "
                        "live validation")
        else:
            rep.ok("config", "%s parses and validates" % path)
        for w in warnings:
            rep.warn("config", w)
    return cfg, cfg_mod


def check_plan_gate(rep, project, cfg, cfg_mod, manifest_rel):
    """The tier the plan gate is currently in - the question people actually ask.

    When the tier is PINNED (planGate, or the legacy enforce), the line names the
    source: "deny" alone reads like evidence, and the whole point of a pinned
    tier is that the evidence did not choose it. planGate:"observe" beside a
    running phase gets a WARNING - it is the only setting that lowers the gate
    BELOW what the evidence would enforce, and someone who set it weeks ago
    deserves to hear that it is now the thing holding enforcement off."""
    state = cfg_mod.manifest_state(project, manifest_rel)
    mode = cfg_mod.plan_gate_mode(cfg, state)
    knob = cfg_mod.plan_gate_knob(cfg)
    if knob:
        if knob == "observe" and state.get("phaseRunning"):
            rep.warn("plan gate",
                     "observe - planGate: \"observe\" is pinned in "
                     ".claude/audit.config.json while a phase is in_progress, so "
                     "out-of-plan edits are only recorded - BELOW what the "
                     "evidence would enforce",
                     "remove planGate (or set it to \"deny\") to restore "
                     "enforcement while a phase runs")
        else:
            rep.ok("plan gate",
                   "%s - planGate: \"%s\" is pinned in .claude/audit.config.json, "
                   "so the tier is fixed regardless of what is running" % (mode,
                                                                           knob))
        return
    if cfg.get("enforce") is True:
        rep.ok("plan gate", "deny - enforce:true is set (legacy; planGate: "
                            "\"deny\" says the same and wins when both are "
                            "present), so it denies regardless of whether a plan "
                            "is running")
        return
    if mode == "observe":
        rep.ok("plan gate",
               "observe - no manifest at %s, so out-of-plan edits are recorded and "
               "reported once per session, never blocked. Run /audit:init to enforce, "
               "or set \"planGate\": \"deny\" to enforce without a manifest"
               % manifest_rel)
    elif mode == "warn":
        rep.ok("plan gate",
               "warn - a manifest exists but no phase is in_progress, so out-of-plan "
               "edits are advisory. Start a phase (/audit:next, /audit:phase) to enforce")
    else:
        rep.ok("plan gate",
               "deny - a phase is in_progress, so edits are held to the running plan")


def check_manifest(rep, project, cfg):
    """Manifest exists, assembles, validates, and its shards are intact."""
    manifest_rel = cfg.get("manifestPath") or "docs/audit/audit-plan.json"
    path = os.path.join(project, manifest_rel)
    if not os.path.exists(path):
        rep.warn("manifest",
                 "no manifest at %s - the pipeline commands have nothing to run"
                 % manifest_rel,
                 "run /audit:init to generate one, or copy "
                 "templates/audit-plan.starter.json")
        return manifest_rel, None

    mio = _load("_manifest_io", "_manifest_io.py")
    try:
        manifest = mio.load_manifest(path)
    except Exception as exc:
        rep.finding("manifest", "%s cannot be assembled: %s" % (manifest_rel, exc),
                    "check the index's shard refs and that every shard file exists")
        # A missing shard is exactly what makes assembly fail, so the layout check
        # is most useful here rather than skipped. It reads the index directly.
        _check_shards(rep, path, None)
        return manifest_rel, None

    # `_manifest_rules`, imported at the top rather than `_load(...)`-ed here:
    # this file (L7) loading `validate-manifest.py` (L7) was one of the edges
    # `_deps.KNOWN_LAYER_DEBT` recorded, and the rules now sit at layer 2 where
    # every consumer can import the one implementation.
    findings, warnings = _manifest_rules.validate(manifest)
    n_phases = len(manifest.get("phases") or [])
    # Counted through layer 1 rather than by hand, and the difference is not
    # cosmetic: the hand-rolled `sum(len(p.get("tasks")...))` had no isinstance
    # guard, so a manifest carrying a non-dict PHASE raised AttributeError here -
    # a doctor crashing on exactly the broken input the finding two lines below is
    # busy naming. The number is unchanged wherever it is printed: this line is
    # only read in the `else` branch, i.e. when the validator found nothing, and a
    # valid manifest has no malformed entry for `iter_tasks` to skip.
    n_tasks = sum(1 for _ in mio.iter_tasks(manifest))
    if findings:
        rep.finding("manifest",
                    "%d validator finding(s): %s" % (len(findings),
                                                     "; ".join(findings[:3])),
                    "fix them before running a phase - the report renders an "
                    "INVALID MANIFEST banner until they are gone")
    else:
        # Parked proposals are named here because a park-all /audit:init leaves
        # "0 phases, 0 tasks" - which reads as a dead plan unless the line says
        # the work is parked, not missing.
        n_parked = sum(1 for x in (manifest.get("proposals") or [])
                       if isinstance(x, dict) and x.get("status") == "proposed"
                       and isinstance(x.get("payload"), dict))
        # Same rule as audit-status's legacy footer (F-E3): a status outside
        # the proposals vocabulary is still tracked work and must be counted.
        n_legacy = sum(1 for x in (manifest.get("proposals") or [])
                       if isinstance(x, dict) and x.get("status")
                       not in ("proposed", "materialized", "dropped"))
        rep.ok("manifest", "%s valid (%d phases, %d tasks%s%s)"
               % (manifest_rel, n_phases, n_tasks,
                  ", %d parked proposal(s)" % n_parked if n_parked else "",
                  ", %d legacy proposal(s)" % n_legacy if n_legacy else ""))
    for w in warnings[:5]:
        rep.warn("manifest", w)

    _check_shards(rep, path, manifest)
    return manifest_rel, manifest


def _check_shards(rep, index_path, manifest):
    """Sharded layout integrity. Moved here from ci.yml so both call one copy."""
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            index = json.load(fh)
    except Exception:
        return
    if (index.get("meta") or {}).get("version") != 3:
        rep.ok("layout", "single-file layout (meta.version < 3); /audit:migrate "
                         "splits it into per-phase shards for parallel runs")
        return
    base = os.path.dirname(os.path.abspath(index_path))
    missing, mismatched = [], []
    for stub in index.get("phases") or []:
        shard = (stub or {}).get("shard")
        if not shard:
            missing.append("%s has no shard ref" % (stub or {}).get("id"))
            continue
        spath = os.path.join(base, shard)
        if not os.path.exists(spath):
            missing.append(shard)
            continue
        try:
            with open(spath, "r", encoding="utf-8") as fh:
                body = json.load(fh)
            if body.get("id") != stub.get("id") or "tasks" not in body:
                mismatched.append(shard)
        except Exception:
            mismatched.append(shard)
    if missing or mismatched:
        rep.finding("layout",
                    "sharded layout broken - missing: %s; mismatched: %s"
                    % (", ".join(missing[:3]) or "none",
                       ", ".join(mismatched[:3]) or "none"),
                    "restore the shard files, or re-run /audit:migrate")
    else:
        rep.ok("layout", "sharded layout intact (%d shards assemble)"
               % len(index.get("phases") or []))


def check_submodules(rep, project, cfg, manifest, git_root):
    """A task file inside a submodule kills the phase at commit time, not before."""
    if not manifest or not git_root:
        return
    gitmodules = os.path.join(git_root, ".gitmodules")
    if not os.path.exists(gitmodules):
        return
    # `_status_facts` (layer 2), imported at the top rather than `_load(...)`-ed:
    # this file (L7) loading `audit-status.py` (L7) was one of the edges
    # `_deps.KNOWN_LAYER_DEBT` recorded. Only the FACTS are wanted here — the
    # ~600 lines of human rendering that used to come with them never were.
    try:
        with open(gitmodules, "r", encoding="utf-8") as fh:
            paths = _status_facts.parse_gitmodules(fh.read())
        conflicts = _status_facts.submodule_conflicts(
            manifest, paths, git_root=cfg.get("gitRoot") or "")
    except Exception as exc:
        rep.warn("submodules", "could not check submodules: %s" % exc)
        return
    if conflicts:
        rep.finding("submodules",
                    "%d task file(s) live inside a submodule, which the parent repo "
                    "cannot stage: %s" % (len(conflicts),
                                          ", ".join("%s -> %s" % (c[0], c[1])
                                                    for c in conflicts[:3])),
                    "point meta.gitRoot at the submodule to audit it directly, or "
                    "drop those files from the task(s)")
    else:
        rep.ok("submodules", "no task files inside the %d submodule(s)" % len(paths))


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_doctor_setup.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__doctor_setup.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
