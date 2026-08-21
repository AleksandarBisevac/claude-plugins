#!/usr/bin/env python3
"""
The two registries a plan can be wrong about without anything going red: the
`meta.areas` map and the capability policy — plus the runners a phase gate will
try to invoke.

Split out of `audit-doctor.py`, on that file's own
`# --- checks: policy & build ---` marker. What the three checks share is not a
subject but a KIND of question: each compares a declaration against the world it
claims to describe (a directory that exists, a skill this machine has, a binary
on PATH), and each answers with a WARNING at most, because "declared something
that is not here" is a gap in this machine or this checkout, never proof that
the repo is broken.

Layer 5, and `check_policy` is what sets the floor: it runtime-loads
`_panel_discovery` (layer 4) for the machine's skills/agents/MCP inventory, the
same walk the panel's rules view marks `dead` with, so the two surfaces cannot
disagree about which rule is inert. Everything else it reaches - `_policy`,
`_areas`, `usage_ledger` - is lower still.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__doctor_policy.py` - see
`plugins/audit/tests/_harness.py`.
"""
import os
import pathlib
import shutil
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

import _doctor_report as _base  # noqa: E402  (Report, the loader, the constants)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `audit-doctor.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
_load = _base._load
_HOOKS = _base._HOOKS
RECENT_DAYS = _base.RECENT_DAYS


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


# --- checks: build runners ------------------------------------------------------
def check_build_commands(rep, project, manifest):
    """Do the runners named in meta.buildCommands exist?

    Deliberately does NOT execute them. "command not found" at gate time is the
    failure the orchestrator explicitly refuses to burn a retry on, and it is
    detectable without running anything."""
    if not manifest:
        # NOT silent, and that was the defect. Every neighbour in this report names
        # an absent basis instead of vanishing - `ado` says the connector is
        # unconfigured, `journal` says no writes are recorded, `config` says the
        # safe defaults are active - and a row that simply disappears reads as
        # "checked, nothing to say". Reported from a repo carrying three plausible
        # runners: a dozen lines of report, not one of them about build, and the
        # reader reasonably concluded it was covered. The rule this broke is the
        # house rule: when the basis is missing, that is the thing to say.
        rep.ok("buildCommands",
               "no manifest yet, so there is no phase test gate to feed - "
               "meta.buildCommands is what it will read when there is one")
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
        print("_doctor_policy.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__doctor_policy.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
