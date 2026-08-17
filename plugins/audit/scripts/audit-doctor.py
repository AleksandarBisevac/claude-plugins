#!/usr/bin/env python3
"""
Answer "is this working?" before you find out the hard way — stdlib only.

Every failure this reports was previously discoverable only by hitting it: a guard
silently off because no interpreter resolved, a gate command refusing because
`gitRoot` points at a non-repo, a phase that will die at commit time because a task
file lives inside a submodule, `buildCommands` naming a runner that is not installed,
metering writing nothing. The README covered these as Troubleshooting prose, which
is help you can only find once you already know the symptom.

    audit-doctor.py [--project DIR] [--json] [--selftest]

It reuses the checks that already exist rather than reimplementing them —
`validate-config.validate_config`, `validate-manifest.validate`,
`audit-status.submodule_conflicts`, `usage_ledger.find_ledger_dir` — so a rule can
never mean one thing here and another at the gate. The sharded-layout assertion
moved here out of ci.yml for the same reason: CI and this command now call one
implementation.

READ-ONLY BY CONSTRUCTION. It never writes, never takes a lock, and never runs a
`buildCommands` entry — it resolves the executable each one names and reports
whether it exists. A doctor that runs your test suite is not a diagnostic, it is a
build; and one that mutates state cannot be run on a repo mid-phase.

Output classes match the rest of the plugin:
  OK       — checked and healthy
  WARNING  — works, but something will bite later (exit stays 0)
  FINDING  — broken now (exit 1)
Exit: 0 healthy (warnings allowed) · 1 findings · 2 usage error.

This module carries no `--selftest` of its own any more; its 148 cases live in
`plugins/audit/tests/test_audit_doctor.py`, byte-identical labels and all — see
`plugins/audit/tests/_harness.py`. They moved WHOLE: 53 of them re-`diagnose()` one
temp repository that the suite mutates step by step, so the sequence is the test.
`_json_ok()` went with them (its only caller was one case). `_load()` stayed — it is
how the checks reach `audit-journal`, `audit-lock`, `audit-status`, `validate-config`
and `validate-manifest`, and those five edges are recorded in `_deps.KNOWN_LAYER_DEBT`.
The sixth, `gen-demo-manifest`, had exactly ONE call site and it was inside the suite;
that entry is deleted with this move rather than left to describe an edge the tree no
longer has.
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

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

_HOOKS = _output.HOOKS_DIR
sys.path.insert(0, _HOOKS)
import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _cli_fmt  # noqa: E402  (the one place CLI color lives - mode resolution + paint)

# The interpreters py-launch.sh tries, in its order. Kept in sync deliberately:
# what matters is the interpreter the HOOKS will find, not the one running this.
LAUNCHER_INTERPRETERS = ("python3", "python", "py")

# A hook has "recently run" if state or ledger files were touched inside this many
# days. Matches detect-plan-skip's 7-day GC, so a quiet week is not read as broken.
RECENT_DAYS = 7


# --- loader ---------------------------------------------------------------------
# Decision (P14.3 loader tidy): kept, not inlined. Over _loader.load() alone this
# adds two things every one of the ~15 call sites below would otherwise repeat:
# (1) a `directory` switch (most callers reach scripts/, three reach ../hooks/,
# via _HOOKS) instead of each call site building its own os.path.join, and
# (2) a fixed cache=False — every check re-reads its target fresh, which matters
# here specifically because `tests/test_audit_doctor.py` runs diagnose() repeatedly
# against ONE fixture project it mutates between calls, in ONE process, and a stale
# cached module would be indistinguishable from a real regression (which is also
# why that suite moved WHOLE). It does NOT shape errors: a load
# failure still propagates uncaught to the caller, same as _loader.load().
def _load(name, filename, directory=None):
    """Load a sibling module by path (the filenames are hyphenated).

    With no `directory` this goes through `_loader.load_script`, which resolves a
    scripts/ file by BASENAME wherever it sits; the three hooks/ callers pass
    `_HOOKS` and keep the explicit join, because `hooks/` is not on that walk."""
    if directory is None:
        return _loader.load_script(filename, modname=name, cache=False)
    return _loader.load(os.path.join(directory, filename), modname=name, cache=False)


# --- report ---------------------------------------------------------------------
class Report(object):
    """Collects results; knows nothing about how they are rendered."""

    def __init__(self):
        self.rows = []

    def add(self, level, check, detail, fix=None):
        self.rows.append({"level": level, "check": check, "detail": detail,
                          "fix": fix})

    def ok(self, check, detail):
        self.add("OK", check, detail)

    def warn(self, check, detail, fix=None):
        self.add("WARNING", check, detail, fix)

    def finding(self, check, detail, fix=None):
        self.add("FINDING", check, detail, fix)

    def counts(self):
        out = {"OK": 0, "WARNING": 0, "FINDING": 0}
        for r in self.rows:
            out[r["level"]] = out.get(r["level"], 0) + 1
        return out

    def exit_code(self):
        return 1 if self.counts()["FINDING"] else 0


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
        vc = _load("validate_config", "validate-config.py")
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        findings, warnings = vc.validate_config(raw)
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

    vm = _load("validate_manifest", "validate-manifest.py")
    findings, warnings = vm.validate(manifest)
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
    st = _load("audit_status", "audit-status.py")
    try:
        with open(gitmodules, "r", encoding="utf-8") as fh:
            paths = st.parse_gitmodules(fh.read())
        conflicts = st.submodule_conflicts(manifest, paths,
                                           git_root=cfg.get("gitRoot") or "")
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


# --- checks: policy & build -----------------------------------------------------
def check_areas(rep, project, cfg, manifest, manifest_rel):
    """The `meta.areas` registry against the tree it claims to describe (v0.28).

    Two failures, both of which look like nothing at all from inside the manifest:
    an area pointing at a directory that has been renamed or never existed, and a
    phase tagged with something the registry does not carry. Neither stops a run —
    areas are informational — so neither is a FINDING. Both are the shape of thing
    that is discovered months later, when someone asks why the backend reviewer
    never ran on the backend phases.

    Silent when the manifest registers no areas. Free-text tagging is the v0.16
    feature, still legal, still the normal case; a doctor that nagged every
    single-app repo about a monorepo registry it never asked for would be a doctor
    people stop running."""
    if not manifest:
        return
    ar = _load("_areas", "_areas.py")
    reg = ar.registry(manifest)
    if not reg:
        return
    missing = ar.missing_roots(manifest, project)
    if missing:
        rep.warn("areas",
                 "%d registered area(s) point at a directory that is not there: %s"
                 % (len(missing), ", ".join("%s -> %s" % (t, r)
                                            for t, r in missing[:3])),
                 "fix meta.areas[<tag>].root, or drop the area - roots are "
                 "relative to the project directory, like task.files")
    unreg = ar.unregistered_tags(manifest)
    if unreg:
        rep.warn("areas",
                 "%d phase tag(s) have no registry entry: %s"
                 % (len(unreg), ", ".join("%s uses %r" % (p, t)
                                          for p, t in unreg[:3])),
                 "add them to meta.areas, or fix the typo - an unregistered tag "
                 "still groups, but resolves to no reviewer and no skills")
    if not missing and not unreg:
        rep.ok("areas", "%d area(s) registered, %d phase tag(s), all resolving"
               % (len(reg), len(ar.used_tags(manifest))))
    # v0.34 D3: the advisory owner against the ledger's author column - the
    # one place the two identities can be compared, and the doctor is the one
    # honest home for the question (it has the ledger in hand; the offline
    # validator would false-alarm on every pre-first-run repo, new team
    # member and hash-mode project). Heavily gated: the ledger must HAVE
    # rows, authorMode must be an identity an owner could be written in
    # (email/name), and only then is an owner nobody has ever matched worth
    # a question. WARNING at most - identity drift is a coordination smell,
    # not a broken repo.
    owners = {}
    for tag, entry in reg.items():
        o = entry.get("owner")
        if isinstance(o, str) and o.strip():
            owners[tag] = o.strip()
    if not owners:
        return
    mode = ((cfg.get("usage") or {}).get("authorMode") or "email")
    if mode not in ("email", "name"):
        return
    authors = set()
    try:
        ul = _load("usage_ledger", "usage_ledger.py")
        ld = ul.find_ledger_dir(os.path.join(project, manifest_rel),
                                rel=(cfg.get("usage") or {}).get("ledgerDir"),
                                project_dir=project)
        if ld and os.path.isdir(ld):
            authors = {r.get("author") for r in ul.read_ledger(str(ld))
                       if r.get("author")}
    except Exception:
        authors = set()
    if not authors:
        return
    unseen = sorted(set(owners.values()) - authors)
    if unseen:
        rep.warn("areas",
                 "%d area owner(s) never appear in the ledger's author "
                 "column: %s - never seen yet?"
                 % (len(unseen), ", ".join(unseen[:3])),
                 "is this the identity git config reports for them? owners "
                 "join the ledger by usage.authorMode (git user.email under "
                 "'email', user.name under 'name') - written any other way, "
                 "the join never matches")


def check_policy(rep, project, cfg, cfg_mod, manifest, _discover=None):
    """The capability policy against the plan it governs, and against reality (v0.30).

    Deliberately does NOT re-report a policy that denies audit's own components:
    `validate_config` calls that a finding and `check_config` above has already
    printed it. Two rows for one defect is the same "second place status lives"
    problem one size down. Nor a pattern that matches ONLY audit's own: that is
    the same finding, and the dead-pattern row below counts audit's own names as
    installed precisely so it cannot restate it.

    v0.38 adds the third question a live environment can answer: does every
    pattern in the policy still NAME something? `_panel_discovery`'s inventory
    (skills/agents/MCP, this machine's) plus audit's own always-allowed names,
    matched by `_policy.dead_patterns` — the same walk the panel's rules view
    marks `dead` with, so the two surfaces cannot disagree about which rule is
    inert. One discovery scan per run, batched across kinds. `_discover` is the
    selftest's seam; None means the real scan.

    What is left is the pair of questions only this check can ask:

      * Does the plan reference a capability the policy would refuse? A review
        skill that is denied does not fail at save time or at validation time — it
        fails at the moment a phase reaches sign-off, which is the worst possible
        moment to discover it. Resolved through `_areas`, so the name checked is
        the effective one, and against each phase's OWN tags, so an area-scoped
        rule is judged as it will actually apply.
      * Has the guard hook ever run here? Subagents do not inherit parent hooks on
        every Claude Code version (anthropics/claude-code#43772). Where that is
        true the policy is advisory rather than enforced, and the only honest local
        evidence is the marker guard-capabilities.py leaves when it runs with a
        live policy. Absent, it says so instead of implying enforcement nobody has.
    """
    pol = _load("_policy", "_policy.py")
    policy = pol.policy_cfg(cfg)
    if not pol.is_active(policy):
        rep.ok("policy",
               "inert - every skill, subagent and MCP tool is allowed"
               + (" (policy.enabled is false)"
                  if (cfg.get("policy") or {}).get("enabled") is False else ""))
        return

    refused = []
    if manifest:
        ar = _load("_areas", "_areas.py")
        for phase in (manifest.get("phases") or []):
            if not isinstance(phase, dict):
                continue
            tags = ar.areas_of(phase.get("area"))
            pid = phase.get("id") or "?"
            skill, _basis = ar.resolve_review_skill(manifest, phase)
            wanted = [("%s review skill" % pid, skill)] if skill else []
            for task in (phase.get("tasks") or []):
                if not isinstance(task, dict):
                    continue
                for name in ar.resolve_skills(manifest, phase, task):
                    wanted.append(("%s skill" % (task.get("id") or pid), name))
            for where, name in wanted:
                v = pol.resolve(policy, "skills", name, active_tags=tags)
                if v["verdict"] == "violation":
                    refused.append("%s %r (%s)" % (where, name, v["basis"]))
    if refused:
        rep.warn("policy",
                 "%d capability reference(s) in the manifest would be refused: %s"
                 % (len(refused), "; ".join(refused[:3])),
                 "allow them in policy, or change what the plan asks for - a denied "
                 "review skill fails at phase sign-off, not before")

    # Dead patterns (v0.38): a rule that names nothing THIS machine has is a
    # quiet no-op - usually a typo, or a tool that was uninstalled. Fail-open,
    # twice over: a scan that raises says nothing, and a scan that found
    # NOTHING AT ALL says nothing - a working scan always sees audit's own
    # plugin tree, so a truly empty inventory means the scanner is broken, and
    # a doctor warning about every pattern there would be noise about the scan
    # rather than the policy.
    dead = []
    try:
        scan = _discover or _load("_panel_discovery",
                                  "_panel_discovery.py").discover
        found = scan(project)
    except Exception:
        found = None
    if isinstance(found, dict) and any(found.get(k) for k in pol.KINDS):
        for kind in pol.KINDS:
            if kind == "mcp":
                names = ["mcp__%s__*" % s for s in (found.get("mcp") or [])]
            else:
                names = [e.get("name") for e in (found.get(kind) or [])
                         if isinstance(e, dict) and e.get("name")]
            for tag, listname, pattern in pol.dead_patterns(policy, kind, names):
                where = ("policy.%s.%s" % (kind, listname) if tag is None
                         else "policy.%s.areas.%s.%s" % (kind, tag, listname))
                dead.append("%s %r" % (where, pattern))
    if dead:
        rep.warn("policy",
                 "%d pattern(s) match nothing installed here: %s - a typo, a "
                 "removed tool, or a tool a teammate has; a pattern that names "
                 "nothing decides nothing"
                 % (len(dead), "; ".join(dead[:3])),
                 "fix the name if it is a typo, or leave it if it is real "
                 "elsewhere - this is THIS machine's inventory, so a hint and "
                 "never a gate")

    try:
        gc_mod = _load("guard_capabilities", "guard-capabilities.py", _HOOKS)
        marker = os.path.join(str(cfg_mod.state_dir(pathlib.Path(project), cfg)),
                              gc_mod.SEEN_FILE)
        age_days = (time.time() - os.path.getmtime(marker)) / 86400.0
    except Exception:
        age_days = None
    if age_days is None or age_days > RECENT_DAYS:
        rep.warn("policy",
                 "the policy is active, but guard-capabilities has not run here%s - "
                 "your Claude Code version may not dispatch Skill/Task/MCP matchers "
                 "to plugin hooks, and inside a subagent it may not inherit them at "
                 "all (anthropics/claude-code#43772). The policy is then advisory"
                 % ("" if age_days is None else " for %.0f days" % age_days),
                 "use a skill or subagent in this project and re-run; if the marker "
                 "still does not appear, treat the policy as documentation and "
                 "enforce with Claude Code permission rules instead")
    elif not refused and not dead:
        # `age_days` cannot be None on this branch today, and the "%.1f" that used
        # to assume it still crashed under a mutation — which is how it was found.
        # A diagnostic that dies computing its own OK line reports the wrong thing
        # twice over: nothing about the policy, and a traceback that looks like the
        # defect. It states what it knows instead.
        when = ("%.1f day(s) ago" % age_days if age_days is not None
                else "at a time this check could not read")
        rep.ok("policy", "active and enforcing (onViolation: %s); the guard last "
                         "ran %s" % (policy.get("onViolation"), when))


def check_build_commands(rep, project, manifest):
    """Do the runners named in meta.buildCommands exist?

    Deliberately does NOT execute them. "command not found" at gate time is the
    failure the orchestrator explicitly refuses to burn a retry on, and it is
    detectable without running anything."""
    if not manifest:
        return
    cmds = ((manifest.get("meta") or {}).get("buildCommands") or {})
    if not isinstance(cmds, dict) or not cmds:
        rep.warn("buildCommands",
                 "meta.buildCommands is empty - phase test gates have nothing to run "
                 "and testGateGreen would pass vacuously",
                 "set meta.buildCommands (test/lint/build) in the manifest")
        return
    missing, unresolvable = [], []
    for name, cmd in cmds.items():
        exe = _leading_executable(str(cmd))
        if exe is None:
            unresolvable.append(name)
        elif not shutil.which(exe):
            missing.append("%s (%s)" % (name, exe))
    if missing:
        # WARNING, not FINDING. Every other finding here is a defect in the REPO —
        # an invalid manifest, a malformed config, broken shards, a gitRoot that is
        # not a repo. A runner that is not installed is a gap in THIS MACHINE, and
        # the two are not the same claim: CI's manifest job deliberately does not
        # install the Claude CLI, and calling that repo-broken failed the build over
        # a correct observation. Same lesson as the `for`-loop false positive, which
        # this under-applied.
        rep.warn("buildCommands",
                 "runner not on PATH here: %s - that gate cannot run on this "
                 "machine" % ", ".join(missing),
                 "install the runner if you intend to run gates here; a gate that "
                 "cannot run is reported as infrastructure failure, not a red test")
    else:
        checked = len(cmds) - len(unresolvable)
        rep.ok("buildCommands", "all %d resolvable runner(s) found on PATH" % checked)
    if unresolvable:
        # Saying "not checked" is the honest answer. Guessing produced a false
        # FINDING on this repo's own `for f in ...; do` loop, and a doctor that
        # cries wolf is worse than one that admits a limit.
        rep.warn("buildCommands",
                 "%s use shell constructs, so their runner cannot be resolved "
                 "statically - not checked" % ", ".join(sorted(unresolvable)))


def _leading_executable(cmd):
    """The program a shell command would actually run, or None if undecidable.

    Handles the two prefixes that appear in real manifests - `cd <dir> &&` for
    git-in-a-subdir and `VAR=value` / `env VAR=value` - and gives up on anything
    with shell control flow rather than reporting its keyword as a missing binary.
    """
    text = str(cmd).strip()
    if not text:
        return None
    # `cd app && yarn test` -> the runner is after the &&, not `cd`.
    while True:
        head = text.split(None, 1)[0] if text.split() else ""
        if head == "cd" and "&&" in text:
            text = text.split("&&", 1)[1].strip()
            continue
        break
    tokens = text.split()
    if not tokens:
        return None
    # strip `env` and leading VAR=value assignments
    idx = 0
    while idx < len(tokens) and (tokens[idx] == "env" or
                                 ("=" in tokens[idx]
                                  and not tokens[idx].startswith("-")
                                  and "/" not in tokens[idx].split("=", 1)[0])):
        idx += 1
    if idx >= len(tokens):
        return None
    exe = tokens[idx]
    shell_words = {"for", "while", "until", "if", "case", "do", "then", "else",
                   "fi", "done", "esac", "set", "eval", "exec", "source", ".",
                   "function", "trap", "shift", "return", "{", "(", "[", "[["}
    if exe in shell_words or exe.startswith(("$", "`", "(", "{")):
        return None
    if any(ch in exe for ch in "|;<>&*?"):
        return None
    return exe


# --- checks: hooks, ledger & trail ----------------------------------------------
def check_ado(rep, project, manifest):
    """The ADO connector's OPERATIONAL half (connector v2).

    The SHAPE of meta.ado is the validator's job (check_ado_meta) and reaches
    this report through check_manifest; what a shape-checker cannot see is
    covered here: whether the transport is present, which switches are in
    effect, whether the shipped state defaults aim at a process that may not
    define them, and what the manifest's links actually prove. Offline on
    purpose - a doctor that phoned ADO would be a doctor that needs
    credentials. Real states live in ADO, so the state-map row is exactly
    what it says: advisory."""
    meta = (manifest or {}).get("meta")
    ado = meta.get("ado") if isinstance(meta, dict) else None
    if ado is None:
        rep.ok("ado", "connector not configured (meta.ado absent) - "
               "/audit:sync and the orchestration echo are off")
        return
    if not isinstance(ado, dict):
        return  # a shape defect; check_manifest already carries the finding

    enabled = ado.get("enabled") is not False
    echo = enabled and ado.get("echo") is not False
    pbi = ado.get("phaseWorkItems") is not False
    sprint = ado.get("sprint") if isinstance(ado.get("sprint"), dict) else None
    if not enabled:
        rep.warn("ado",
                 "connector DISABLED (meta.ado.enabled: false) - push/pull "
                 "and the echo do nothing; links are kept and /audit:sync "
                 "status still reports them",
                 "re-enable in the panel's ADO card, or delete the key")
    else:
        pbi_note = ""
        if pbi and not (ado.get("types") or {}).get("pbi"):
            pbi_note = " (types.pbi auto-detected at the first phase push)"
        rep.ok("ado",
               "connector on (org %s, project %s) - echo %s, PBI-per-phase "
               "%s%s, sprint %s"
               % (ado.get("organization") or "?", ado.get("project") or "?",
                  "on" if echo else "off", "on" if pbi else "off", pbi_note,
                  ("resolves team %r" % sprint.get("team")) if sprint
                  else "static (iterationPath)"))

    # Transport: what a headless / CLI run stands on. MCP may still carry an
    # interactive session, which is why a missing az is a warning, never a
    # finding.
    if not shutil.which("az"):
        rep.warn("ado transport",
                 "az CLI is not on PATH - /audit:sync can still use the ADO "
                 "MCP tools when the session has them, else it stops",
                 "install azure-cli, then: az extension add --name azure-devops")
    else:
        try:
            out = subprocess.run(["az", "extension", "list", "--output",
                                  "json"], capture_output=True, text=True,
                                 timeout=15)
            names = [e.get("name") for e in json.loads(out.stdout or "[]")
                     if isinstance(e, dict)]
            if "azure-devops" in names:
                rep.ok("ado transport", "az + azure-devops extension present")
            else:
                rep.warn("ado transport",
                         "az is on PATH but the azure-devops extension is "
                         "not installed",
                         "az extension add --name azure-devops")
        except Exception as exc:
            rep.warn("ado transport",
                     "az is on PATH but `az extension list` did not answer "
                     "(%s) - transport unverified" % exc)

    # Live-gate F3: both stock processes force-clear Remaining Work at their
    # done state, so a configured write degrades to state-only there. Advisory
    # - the goal ("0 left") is met by the process itself.
    oc = ado.get("onComplete")
    if isinstance(oc, dict) and oc.get("remainingWork", 0) is not None:
        rep.warn("ado remaining work",
                 "onComplete.remainingWork is configured, but stock processes "
                 "(Scrum Done, Agile Closed) force-clear the field at done - "
                 "the write degrades to state-only there, and the process "
                 "empties the field by itself. The key matters only for "
                 "custom processes without the clear rule. Advisory only")

    # The Agile-only truth baked into the shipped defaults (D-7).
    if ado.get("stateMap") is None:
        rep.warn("ado state map",
                 "no meta.ado.stateMap: the built-in defaults name "
                 "Agile-process states (task done > Closed). Scrum tasks use "
                 "To Do/In Progress/Done, so a Scrum project should set the "
                 "map. Advisory only: real states live in ADO",
                 "set meta.ado.stateMap in the panel's ADO card")

    # What the links prove - int ids only, the validator's shape.
    linked = {"task": 0, "bug": 0, "phase": 0}
    newest = [None]

    def _note(item, kind):
        link = item.get("ado") if isinstance(item, dict) else None
        if isinstance(link, dict) and isinstance(link.get("id"), int) \
                and not isinstance(link.get("id"), bool):
            linked[kind] += 1
            ts = link.get("lastSyncedAt")
            if isinstance(ts, str) and (newest[0] is None or ts > newest[0]):
                newest[0] = ts

    mio = _load("_manifest_io", "_manifest_io.py")
    for ph in (manifest.get("phases") or []):
        if isinstance(ph, dict):
            _note(ph, "phase")
    # Two passes rather than a nested loop, because only ONE of them is a task
    # traversal: the phase pass must reach a phase that holds no tasks (its own
    # `ado` link is what is being counted), and `iter_tasks` yields nothing for
    # one. `_note` only ever increments a counter and takes a max, so the order
    # the three kinds are visited in cannot change the answer.
    for _, t in mio.iter_tasks(manifest):
        _note(t, "task")
    for b in (manifest.get("bugs") or []):
        _note(b, "bug")
    if not sum(linked.values()):
        rep.ok("ado links",
               "no item linked yet - configuration, not evidence; "
               "/audit:sync push writes the first links")
    else:
        rep.ok("ado links",
               "%d task(s), %d bug(s), %d phase(s) linked%s"
               % (linked["task"], linked["bug"], linked["phase"],
                  (" - newest sync %s" % newest[0]) if newest[0] else ""))


def check_hooks_fired(rep, project, cfg, cfg_mod):
    """Have the hooks ever actually run here?

    The most common silent failure is not a broken hook but an uninstalled or
    disabled plugin, which looks identical to a healthy one from inside the repo.
    A recently-written state file is the only local evidence a hook ran."""
    # state_dir joins with `/`, so it wants a Path rather than a str.
    state_dir = cfg_mod.state_dir(pathlib.Path(project), cfg)
    try:
        entries = [os.path.join(state_dir, f) for f in os.listdir(state_dir)]
        files = [f for f in entries if os.path.isfile(f)]
    except Exception:
        files = []
    if not files:
        rep.warn("hooks",
                 "no hook state under %s, so nothing here proves a guard has ever run"
                 % state_dir,
                 "check the plugin is installed AND enabled for this project "
                 "(/plugin -> Installed), then make one edit and re-run")
        return
    newest = max(os.path.getmtime(f) for f in files)
    age_days = (time.time() - newest) / 86400.0
    if age_days > RECENT_DAYS:
        rep.warn("hooks",
                 "newest hook state in %s is %.0f days old" % (state_dir, age_days),
                 "harmless if you have not worked here recently; otherwise verify "
                 "the plugin is still enabled")
    else:
        rep.ok("hooks", "%d state file(s) in %s, newest %.1f day(s) old"
               % (len(files), state_dir, age_days))


def check_ledger(rep, project, cfg, manifest_rel):
    """Is metering writing? find_ledger_dir returning None IS the signal."""
    usage = cfg.get("usage") or {}
    if usage.get("enabled") is False:
        rep.ok("usage ledger", "metering disabled in config (usage.enabled false)")
        return
    ul = _load("usage_ledger", "usage_ledger.py")
    try:
        ledger_dir = ul.find_ledger_dir(os.path.join(project, manifest_rel),
                                        rel=usage.get("ledgerDir"),
                                        project_dir=project)
    except Exception as exc:
        rep.warn("usage ledger", "could not locate a ledger: %s" % exc)
        return
    if not ledger_dir:
        rep.warn("usage ledger",
                 "no ledger directory found, so no spend has been recorded",
                 "metering starts once the hooks have run a turn; "
                 "/audit:usage --backfill reads transcripts already on disk")
        return
    # With a project dir in hand, find_ledger_dir answers where the ledger
    # WOULD live whether or not it exists yet (deliberate contract - see its
    # docstring). Missing and empty are different diagnoses: "exists but holds
    # no rows" about a directory nothing ever created is a false statement.
    if not os.path.isdir(ledger_dir):
        rep.warn("usage ledger",
                 "no ledger yet - it would live at %s; metering writes it on "
                 "the first metered turn" % ledger_dir,
                 "/audit:usage --backfill reads transcripts already on disk")
        return
    try:
        files = ul.ledger_files(ledger_dir)
    except Exception:
        files = []
    if not files:
        rep.warn("usage ledger", "%s exists but holds no rows yet" % ledger_dir,
                 "run /audit:usage --backfill to populate it from existing transcripts")
        return
    rep.ok("usage ledger", "%d ledger file(s) in %s" % (len(files), ledger_dir))


def _journal_never_committed(jr, directory):
    """(count, oldest_age_days, oldest_name) for journal files that have sat
    UNTRACKED for more than 7 days, or None when there is nothing to say.

    Rides audit-journal's own porcelain seam (`_git_status_sets`) -- one
    subprocess for the whole directory, the same batched read verify() uses
    (F-B3). Age by MTIME, not by the filename's month: a file opened on the
    30th is a day old on the 1st, and punishing it for its name teaches people
    the warning is noise. The 7-day line is the one the state GC already draws
    (_GC_MAX_AGE) -- older than any session state is allowed to live. Never
    raises; None on every inability to answer (no git, not a repository, no
    untracked files), because an unanswerable question is not a warning.

    Archive files count too: journal_files walks journal/archive/ (one level)
    and the porcelain's -uall expands untracked directories into files, so an
    untracked file is the same unanchored work wherever it sits. DECISION
    (pinned, v0.37 D): a file `git mv`ed into archive/ with the move staged
    but not yet committed says NOTHING here -- porcelain reports a staged
    rename as "R " (dirty), never "??" (untracked), and that classification is
    correct: the file's history IS committed, at its pre-move path, which the
    verify anchor still checks. The archive subcommand's own output already
    tells the user to commit the move; a second nag with a false name
    ("never committed" about a committed file) would teach people to ignore
    the true one.

    Keyed by JOURNAL-RELATIVE PATH, not basename (F-D-1): with archive/ the
    same basename can sit live (untracked) AND archived (tracked+committed),
    and a basename lookup let the committed twin inflate the count and
    mis-name the oldest. The path key counts exactly the untracked files,
    and `oldest` carries the journal-relative path so a live and an archived
    month can never read as one another."""
    try:
        if not directory or not os.path.isdir(directory):
            return None
        sets = jr._git_status_sets(directory)
        if not sets or not sets[1]:
            return None
        now = time.time()
        old = []
        for f in jr.journal_files(directory):
            rel = os.path.relpath(f, directory).replace(os.sep, "/")
            if rel not in sets[1]:
                continue
            try:
                age = now - os.stat(f).st_mtime
            except Exception:
                continue
            if age > 7 * 86400:
                old.append((age, rel))
        if not old:
            return None
        old.sort(reverse=True)
        return len(old), int(old[0][0] // 86400), old[0][1]
    except Exception:
        return None


def check_journal(rep, project, cfg, cfg_mod, git_root):
    """Does the audit trail still hold together? (v0.29)

    Delegates to `audit-journal.verify` rather than re-deriving the verdict — the
    same rule `check_locks` follows below, and for the same reason: a diagnostic
    with its own opinion about whether a chain is intact is a second implementation
    that can disagree with the one that matters.

    The grading is the honest one. A BROKEN chain is a FINDING: a row was edited,
    deleted or reordered, and that is not something that happens by accident.
    Everything else is a WARNING at most — a torn tail is a crash, and out-of-band
    drift means a document moved without an edit tool touching it, which is normal
    for a git checkout and only suspicious in context. An empty journal is neither:
    it is what every repo looks like before its first recorded write."""
    if not cfg_mod.journal_enabled(cfg):
        # Disabled is the user's own switch and never a finding. But rows on
        # disk mean the trail WAS running: saying plain OK graded "someone
        # turned it off mid-history" identically to "never used", and the
        # completion records quietly stopped being written. The chain itself is
        # deliberately not verified here -- a broken chain in a disabled
        # journal is not this run's business.
        has_rows = False
        try:
            jr = _load("audit_journal", "audit-journal.py")
            res = jr.verify(project)
            has_rows = bool(res.get("exists") and res.get("rows"))
        except Exception:
            has_rows = False
        if has_rows:
            rep.warn("journal",
                     "audit trail was running and has been turned off -- "
                     "completion records are no longer being written",
                     "set journal.enabled true to resume the trail; the "
                     "recorded history stays where it is")
        else:
            rep.ok("journal",
                   "audit trail disabled in config (journal.enabled false)")
        return
    try:
        jr = _load("audit_journal", "audit-journal.py")
        res = jr.verify(project)
    except Exception as exc:
        rep.warn("journal", "could not read the journal: %s" % exc,
                 "run `audit-journal.py verify` by hand to see why")
        return
    where = os.path.relpath(res.get("dir") or project, project)
    if not res.get("exists"):
        rep.ok("journal", "no writes recorded yet (%s does not exist)" % where)
        return
    # D4 / F-F1: the git anchor only pins committed history. An uncommitted
    # journal file younger than 7 days is the normal write-then-commit rhythm;
    # one older than that has been outliving every session state file while
    # the anchor protects none of it -- usually a gitignored or forgotten
    # directory. A WARNING, never a FINDING: a finding is positive evidence of
    # forgery, and an absent commit is evidence of nothing but absence.
    if git_root and shutil.which("git"):
        stale = _journal_never_committed(jr, res.get("dir"))
        if stale:
            n, days, oldest = stale
            rep.warn("journal",
                     "%d journal file(s) have never been committed (oldest "
                     "%s, %d day(s) old): the git anchor only pins committed "
                     "history" % (n, oldest, days),
                     "stage and commit the journal directory - it is designed "
                     "to be tracked; do not add it to .gitignore")
    if res.get("findings"):
        rep.finding("journal",
                    "the chain does not hold: %s" % "; ".join(res["findings"][:3]),
                    "run `audit-journal.py verify` for the full list; the journal "
                    "is append-only and a broken chain means a row was edited, "
                    "deleted or reordered")
        return
    if res.get("warnings"):
        rep.warn("journal",
                 "%d row(s) in %s chain cleanly, with %d warning(s): %s"
                 % (res.get("rows", 0), where, len(res["warnings"]),
                    "; ".join(res["warnings"][:2])),
                 "out-of-band drift is a document that changed with no row to "
                 "explain it - a git checkout, a script, or a shell write")
        return
    rep.ok("journal", "%d row(s) in %d file(s) under %s, chain intact"
           % (res.get("rows", 0), len(res.get("files") or []), where))


def _hours_between(a, b):
    """Hours between two ISO timestamps, or None when either cannot be read —
    an unreadable timestamp is a reason to say nothing, not to accuse."""
    try:
        import calendar

        def parse(s):
            return calendar.timegm(time.strptime(str(s)[:19],
                                                 "%Y-%m-%dT%H:%M:%S"))
        return abs(parse(a) - parse(b)) / 3600.0
    except Exception:
        return None


def check_completions(rep, project, cfg, manifest, manifest_rel, git_root,
                      deep=False):
    """Completion records against the manifest (workstream B). Read-only.

    The journal's `task.complete` rows are hook-emitted, one per status flip to
    done — the pipeline's receipt. A done task INSIDE their era with no record
    means the manifest was edited outside the pipeline or a record was removed:
    positive evidence, so a FINDING. A commit SHA git has never heard of is the
    same class. Everything the check cannot know is a WARNING at most, and the
    era is decided by the WATERMARK rule with no config knob: the first
    task.complete row's ts. Zero such rows means an older plugin wrote this
    history, and that is a single ok line, not a nag."""
    if not manifest:
        return
    try:
        jr = _load("audit_journal", "audit-journal.py")
        rows = jr.read_all(project)
    except Exception as exc:
        rep.warn("completions", "could not check: %s" % exc)
        return
    completes = [r for r in rows if r.get("action") == "task.complete"]
    if not completes:
        rep.ok("completions",
               "completion records not in use (older plugin wrote this history)")
        return
    watermark = min(str(r.get("ts") or "") for r in completes)
    recorded, row_ts, row_file = set(), {}, {}
    for r in completes:
        det = r.get("details") if isinstance(r.get("details"), dict) else {}
        tid = det.get("taskId")
        if tid:
            recorded.add(tid)
            row_ts.setdefault(tid, str(r.get("ts") or ""))
            if r.get("_file"):
                row_file.setdefault(tid, r["_file"])

    done, pre_era = [], 0
    mio = _load("_manifest_io", "_manifest_io.py")
    # The phase is not read here - only the tasks are joined against the journal -
    # so the pair is unpacked and dropped rather than kept beside a lookup.
    for _, task in mio.iter_tasks(manifest):
        if task.get("status") != "done":
            continue
        completed = task.get("completedAt")
        if not isinstance(completed, str) or completed < watermark:
            pre_era += 1            # older history: out of scope by watermark
            continue
        done.append(task)
    if pre_era:
        rep.ok("completions",
               "%d done task(s) predate the first completion record and are "
               "not checked (older plugin wrote that history)" % pre_era)
    if not done:
        if not pre_era:
            rep.ok("completions", "no done tasks in the completion-record era")
        return

    could_not = []
    missing = [t.get("id") for t in done if t.get("id") not in recorded]
    if missing:
        rep.finding("completions",
                    "%d task(s) marked done with no completion record: %s -- "
                    "the manifest was edited outside the pipeline or a record "
                    "was removed"
                    % (len(missing), ", ".join(str(x) for x in missing[:3])),
                    "run `audit-journal.py show` to see what WAS recorded; to "
                    "repair the trail, reopen the task and re-run it via "
                    "/audit:run")

    bad_sha, no_sha = [], []
    for t in done:
        sha = t.get("commit")
        if not sha:
            no_sha.append(str(t.get("id")))
            continue
        if not (git_root and shutil.which("git")):
            could_not.append("commit SHAs (no git)")
            break
        try:
            out = subprocess.run(["git", "-C", git_root, "rev-parse", "-q",
                                  "--verify", "%s^{commit}" % sha],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=15)
            if out.returncode != 0:
                bad_sha.append("%s (%s)" % (t.get("id"), str(sha)[:12]))
        except Exception:
            could_not.append("commit %s" % str(sha)[:12])
    if bad_sha:
        rep.finding("completions",
                    "the manifest names a commit git does not have: %s"
                    % ", ".join(bad_sha[:3]),
                    "a task.commit that resolves nowhere is a fabricated or "
                    "rewritten SHA -- check `git log` against the journal's "
                    "task.commit rows")
    if no_sha:
        rep.warn("completions",
                 "%d done task(s) carry no commit SHA: %s"
                 % (len(no_sha), ", ".join(no_sha[:3])),
                 "the orchestrator writes task.commit after each task commit; "
                 "a missing one usually means an interrupted run "
                 "(/audit:resume re-commits)")

    drift = []
    for t in done:
        gap = _hours_between(row_ts.get(t.get("id")), t.get("completedAt"))
        if gap is not None and gap > 24:
            drift.append("%s (%.0fh)" % (t.get("id"), gap))
    if drift:
        rep.warn("completions",
                 "completion record and completedAt disagree by more than 24h: %s"
                 % ", ".join(drift[:3]),
                 "the record and the manifest were not written together -- "
                 "worth a look, not proof of anything")

    unspent = []
    try:
        ul = _load("usage_ledger", "usage_ledger.py")
        usage = cfg.get("usage") or {}
        ledger_dir = ul.find_ledger_dir(os.path.join(project, manifest_rel),
                                        rel=usage.get("ledgerDir"),
                                        project_dir=project)
        lrows = ul.read_ledger(ledger_dir) if ledger_dir else []
        spent = {r.get("taskId") for r in lrows if r.get("taskId")}
        unspent = [str(t.get("id")) for t in done if t.get("id") not in spent]
    except Exception as exc:
        could_not.append("ledger coverage (%s)" % exc)
    if unspent:
        rep.warn("completions",
                 "%d completion-era done task(s) have no usage-ledger rows: %s"
                 % (len(unspent), ", ".join(unspent[:3])),
                 "the ledger is re-derivable from Claude Code's own read-only "
                 "transcripts: /audit:usage --backfill")

    if deep and git_root and shutil.which("git"):
        try:
            # realpath BOTH sides: on macOS the project arrives as /var/... while
            # git resolves its toplevel to /private/var/..., and a relpath across
            # that symlink is a pathspec outside the repository.
            jdir = os.path.realpath(jr.journal_dir(project))
            groot = os.path.realpath(git_root)
            jrel = os.path.relpath(jdir, groot)
            if jrel.startswith(".."):
                raise ValueError("journal dir %s is outside the git root" % jdir)
            unstaged = []
            for t in done:
                sha = t.get("commit")
                fname = row_file.get(t.get("id"))
                if not sha or not fname:
                    continue
                out = subprocess.run(["git", "-C", groot, "ls-tree", "-r",
                                      "--name-only", str(sha), "--", jrel],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, timeout=15)
                if (out.returncode == 0 and fname not in
                        out.stdout.decode("utf-8", "replace")):
                    unstaged.append("%s (%s)" % (t.get("id"), fname))
            if unstaged:
                rep.warn("completions",
                         "--deep: the task commit does not carry the journal "
                         "file that records it: %s" % ", ".join(unstaged[:3]),
                         "the orchestrator stages the journal dir with every "
                         "task commit; an absent file weakens the git "
                         "cross-anchor")
        except Exception as exc:
            could_not.append("deep journal-in-commit (%s)" % exc)

    if could_not:
        rep.warn("completions",
                 "could not check: %s" % "; ".join(sorted(set(could_not))[:3]))
    if not (missing or bad_sha or no_sha or drift or unspent or could_not):
        rep.ok("completions",
               "%d done task(s) in the completion-record era all carry chained "
               "records" % len(done))


def check_locks(rep, git_root, project, manifest_rel):
    """A held lock is why a command refuses; a stale one is why it refuses wrongly.

    Delegates to audit-lock.py rather than re-deriving the verdict. This used to
    call anything older than 60 minutes stale, which told the human a healthy
    90-minute phase run had crashed — the diagnostic manufacturing the very
    takeover that loses work. The lock script answers by probing the holder's pid
    on this host, and falls back to age only when it cannot.
    """
    if not (git_root and shutil.which("git")):
        rep.ok("locks", "no audit locks held")
        return
    try:
        lock = _load("audit_lock", "audit-lock.py")
        rows = lock.collect(git_root)
    except Exception as exc:
        rep.warn("locks", "could not read the lock directory: %s" % exc,
                 "run `audit-lock.py status` by hand to see what is held")
        return
    if not rows:
        rep.ok("locks", "no audit locks held")
        return
    abandoned = ["%s (%s)" % (r["name"], r["basis"]) for r in rows if not r["live"]]
    if abandoned:
        rep.warn("locks",
                 "lock(s) with no live holder: %s" % "; ".join(abandoned),
                 "a mutating /audit command will offer to take over; if no run is "
                 "live you can delete the file")
    else:
        rep.ok("locks", "%d lock(s) held by a live run: %s"
               % (len(rows), "; ".join("%s (%s)" % (r["name"], r["basis"])
                                       for r in rows)))


def check_local_artifacts(rep, project, cfg, cfg_mod, manifest, git_root):
    """Are the plugin's LOCAL artifacts staying out of git? (v0.35)

    Four artifacts are per-machine by design: the usage ledger (person
    identities, transcript cursors), stateDir (session scratch), logsDir
    (gate telemetry) and the panel pidfile (a LIVE session token). From 0.35
    every dir-creating writer drops a `*` .gitignore inside and the panel
    writes a targeted rule for its pidfile — this check catches what those
    cannot reach: files committed BEFORE the markers existed, and dirs made
    by older versions that no hook has touched since. WARNING at most: a
    tracked ledger is a privacy leak, not evidence of forgery. The journal
    is deliberately NOT in this list — it is the opposite kind of artifact
    and must stay tracked (check_journal warns about the reverse)."""
    if not git_root or not shutil.which("git"):
        rep.ok("hygiene", "not a git repository - local artifacts cannot "
               "reach version control")
        return
    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    ledger_rel = str(meta_usage.get("ledgerDir")
                     or os.path.join(".claude", "usage"))
    dirs = {
        "ledger": os.path.join(project, ledger_rel),
        "state": os.path.join(project, str(cfg.get("stateDir")
                                           or cfg_mod.DEFAULTS["stateDir"])),
        "logs": os.path.join(project, str(cfg.get("logsDir")
                                          or cfg_mod.DEFAULTS["logsDir"])),
    }
    pidfile = os.path.join(project, ".claude", "audit-panel.json")
    pid_base = os.path.basename(pidfile)
    try:
        out = subprocess.run(
            ["git", "ls-files", "--", pidfile] + sorted(dirs.values()),
            cwd=project, capture_output=True, text=True, timeout=30)
        tracked = [ln for ln in (out.stdout or "").splitlines() if ln.strip()]
    except Exception:
        rep.ok("hygiene", "git unavailable for the tracked-files check")
        return
    if any(ln.endswith(pid_base) for ln in tracked):
        rep.warn("hygiene",
                 "the panel pidfile (.claude/%s) is TRACKED in git - it "
                 "holds a live session token" % pid_base,
                 "git rm --cached it and commit; then restart the panel to "
                 "rotate the token the history already saw")
    others = [ln for ln in tracked if not ln.endswith(pid_base)]
    if others:
        rep.warn("hygiene",
                 "%d local file(s) tracked in git (ledger/state/logs are "
                 "per-machine: identities and session scratch), e.g. %s"
                 % (len(others), others[0]),
                 "git rm --cached them and commit; the dirs self-ignore "
                 "from 0.35 on, but an ignore cannot untrack history")
    unprotected = []
    for name, d in sorted(dirs.items()):
        if not os.path.isdir(d) \
                or os.path.exists(os.path.join(d, ".gitignore")):
            continue
        try:
            ig = subprocess.run(
                ["git", "check-ignore", "-q", "--", os.path.join(d, "x")],
                cwd=project, capture_output=True, timeout=30)
            if ig.returncode == 0:
                continue           # covered by the repo's own rules
        except Exception:
            pass
        unprotected.append(name)
    if unprotected:
        rep.warn("hygiene",
                 "local dir(s) not ignored yet: %s" % ", ".join(unprotected),
                 "any hook run makes them self-ignore (a `*` .gitignore "
                 "inside); or add them to .gitignore yourself")
    if not tracked and not unprotected:
        seen = sorted(n for n, d in dirs.items() if os.path.isdir(d))
        if seen or os.path.exists(pidfile):
            rep.ok("hygiene", "local artifacts stay out of git (%s)"
                   % ", ".join(seen or ["panel pidfile"]))
        else:
            rep.ok("hygiene", "no local artifacts yet (ledger, state, logs, "
                   "panel pidfile)")


# --- diagnose / render / cli ----------------------------------------------------
def diagnose(project, deep=False):
    """Run every check. Returns a Report. `deep` adds the journal-in-commit
    cross-check to check_completions (read-only, just slower)."""
    rep = Report()
    check_interpreter(rep)
    cfg, cfg_mod = check_config(rep, project)
    git_root = check_git(rep, project, cfg)
    manifest_rel, manifest = check_manifest(rep, project, cfg)
    check_plan_gate(rep, project, cfg, cfg_mod, manifest_rel)
    check_submodules(rep, project, cfg, manifest, git_root)
    check_areas(rep, project, cfg, manifest, manifest_rel)
    check_policy(rep, project, cfg, cfg_mod, manifest)
    check_build_commands(rep, project, manifest)
    check_ado(rep, project, manifest)
    check_hooks_fired(rep, project, cfg, cfg_mod)
    check_ledger(rep, project, cfg, manifest_rel)
    check_journal(rep, project, cfg, cfg_mod, git_root)
    check_completions(rep, project, cfg, manifest, manifest_rel, git_root,
                      deep=deep)
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
        lines.append("  No findings - warnings are things that will bite later.")
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
