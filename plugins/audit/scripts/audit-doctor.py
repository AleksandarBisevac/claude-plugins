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
"""
import argparse
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOOKS = os.path.join(os.path.dirname(_HERE), "hooks")
sys.path.insert(0, _HERE)
sys.path.insert(0, _HOOKS)

# The interpreters py-launch.sh tries, in its order. Kept in sync deliberately:
# what matters is the interpreter the HOOKS will find, not the one running this.
LAUNCHER_INTERPRETERS = ("python3", "python", "py")

# A hook has "recently run" if state or ledger files were touched inside this many
# days. Matches detect-plan-skip's 7-day GC, so a quiet week is not read as broken.
RECENT_DAYS = 7


def _load(name, filename, directory=None):
    """Load a sibling module by path (the filenames are hyphenated)."""
    path = os.path.join(directory or _HERE, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    """The tier the plan gate is currently in - the question people actually ask."""
    state = cfg_mod.manifest_state(project, manifest_rel)
    mode = cfg_mod.plan_gate_mode(cfg, state)
    if cfg.get("enforce") is True:
        rep.ok("plan gate", "deny - enforce:true is set, so it denies regardless of "
                            "whether a plan is running")
        return
    if mode == "observe":
        rep.ok("plan gate",
               "observe - no manifest at %s, so out-of-plan edits are recorded and "
               "reported once per session, never blocked. Run /audit:init to enforce, "
               "or set \"enforce\": true to enforce without a manifest" % manifest_rel)
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
    n_tasks = sum(len(p.get("tasks") or []) for p in (manifest.get("phases") or []))
    if findings:
        rep.finding("manifest",
                    "%d validator finding(s): %s" % (len(findings),
                                                     "; ".join(findings[:3])),
                    "fix them before running a phase - the report renders an "
                    "INVALID MANIFEST banner until they are gone")
    else:
        rep.ok("manifest", "%s valid (%d phases, %d tasks)"
               % (manifest_rel, n_phases, n_tasks))
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
    try:
        files = ul.ledger_files(ledger_dir)
    except Exception:
        files = []
    if not files:
        rep.warn("usage ledger", "%s exists but holds no rows yet" % ledger_dir,
                 "run /audit:usage --backfill to populate it from existing transcripts")
        return
    rep.ok("usage ledger", "%d ledger file(s) in %s" % (len(files), ledger_dir))


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


def diagnose(project):
    """Run every check. Returns a Report."""
    rep = Report()
    check_interpreter(rep)
    cfg, cfg_mod = check_config(rep, project)
    git_root = check_git(rep, project, cfg)
    manifest_rel, manifest = check_manifest(rep, project, cfg)
    check_plan_gate(rep, project, cfg, cfg_mod, manifest_rel)
    check_submodules(rep, project, cfg, manifest, git_root)
    check_build_commands(rep, project, manifest)
    check_hooks_fired(rep, project, cfg, cfg_mod)
    check_ledger(rep, project, cfg, manifest_rel)
    check_locks(rep, git_root, project, manifest_rel)
    return rep


def render(rep, project):
    """Plain ASCII, printed verbatim by the command - no re-formatting needed."""
    lines = ["AUDIT DOCTOR  %s" % project, ""]
    width = max([len(r["check"]) for r in rep.rows] or [7])
    for r in rep.rows:
        lines.append("  [%-7s] %-*s  %s" % (r["level"], width, r["check"],
                                            r["detail"]))
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
    args = ap.parse_args(argv)

    project = os.path.abspath(args.project)
    if not os.path.isdir(project):
        sys.stderr.write("ERROR: %s is not a directory\n" % project)
        return 2

    rep = diagnose(project)
    if args.as_json:
        print(json.dumps({"project": project, "counts": rep.counts(),
                          "checks": rep.rows}, indent=2))
    else:
        print(render(rep, project))
    return rep.exit_code()


# --- selftest -------------------------------------------------------------------
def _selftest():
    import shutil as sh
    import tempfile
    cases = []

    def check(label, ok, detail=""):
        cases.append((label, bool(ok), detail))

    def levels(rep, name):
        return [r["level"] for r in rep.rows if r["check"] == name]

    def detail(rep, name):
        return " ".join(r["detail"] for r in rep.rows if r["check"] == name)

    # An empty directory: no config, no manifest, no state. Nothing is BROKEN, so
    # this must not report findings - a fresh repo is not a sick one.
    tmp = tempfile.mkdtemp(prefix="audit-doctor-selftest-")
    try:
        # A non-git directory is legitimately a FINDING (every mutating command
        # stops there), so the "fresh setup" case has to be a fresh REPO. If git is
        # not installed the repo cannot be made, and asserting "git root resolves"
        # would then fail for a reason that has nothing to do with this script —
        # so the git-dependent cases are skipped rather than reported as defects.
        have_git = bool(sh.which("git"))
        if have_git:
            try:
                subprocess.run(["git", "init", "-q", tmp],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30, check=True)
            except Exception:
                have_git = False
        if not have_git:
            print("SKIP git-dependent cases (git is not on PATH)")
        rep = diagnose(tmp)
        check("fresh repo: interpreter resolves", levels(rep, "interpreter") == ["OK"])
        check("fresh repo: absent config is OK, not a finding",
              levels(rep, "config") == ["OK"], repr(levels(rep, "config")))
        check("fresh repo: absent manifest is a WARNING, not a finding",
              levels(rep, "manifest") == ["WARNING"], repr(levels(rep, "manifest")))
        check("fresh repo: plan gate reports the observe tier",
              "observe" in detail(rep, "plan gate"), detail(rep, "plan gate"))
        hooks_fix = " ".join(r["fix"] or "" for r in rep.rows
                             if r["check"] == "hooks")
        check("fresh repo: no hook state is a WARNING",
              levels(rep, "hooks") == ["WARNING"], repr(levels(rep, "hooks")))
        check("the hooks warning names the likely cause (not enabled)",
              "enabled" in hooks_fix, hooks_fix)
        if have_git:
            check("fresh repo: a fresh setup yields no findings",
                  rep.counts()["FINDING"] == 0,
                  repr([r for r in rep.rows if r["level"] == "FINDING"]))
        if have_git:
            check("fresh repo: exit code 0", rep.exit_code() == 0)
        if have_git:
            # Locks. The case that used to be reported wrongly: a phase run that
            # has been going for 95 minutes is healthy, and calling it stale is
            # how the doctor talked a human into the takeover that loses work.
            lockmod = _load("audit_lock", "audit-lock.py")
            ld = lockmod.lock_dir(tmp)
            os.makedirs(ld, exist_ok=True)
            old = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                time.gmtime(time.time() - 95 * 60))
            here = __import__("platform").node()
            lp = os.path.join(ld, "phase-P1.lock")

            def put(info):
                with open(lp, "w", encoding="utf-8") as fh:
                    json.dump(info, fh)

            put({"hostname": here, "pid": os.getpid(), "startedAt": old,
                 "note": "phase P1"})
            rep = diagnose(tmp)
            check("locks: a 95-min-old run with a live pid is OK, not stale",
                  levels(rep, "locks") == ["OK"], detail(rep, "locks"))
            check("locks: and the OK says how it knows",
                  "is running on this host" in detail(rep, "locks"),
                  detail(rep, "locks"))
            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            put({"hostname": here, "pid": dead.pid,
                 "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "note": "phase P1"})
            rep = diagnose(tmp)
            check("locks: a 1-min-old run whose pid is gone is a WARNING",
                  levels(rep, "locks") == ["WARNING"], detail(rep, "locks"))
            check("locks: a dead holder is never a FINDING (nothing is broken)",
                  rep.counts()["FINDING"] == 0)
            os.unlink(lp)

        if have_git:
            check("fresh repo: git root resolves", levels(rep, "git") == ["OK"],
                  detail(rep, "git"))

        # a non-repo IS a finding, and it names the fix
        nogit = tempfile.mkdtemp(prefix="audit-doctor-nogit-")
        try:
            rep_ng = diagnose(nogit)
            check("a non-repo directory is a git FINDING",
                  levels(rep_ng, "git") == ["FINDING"], repr(levels(rep_ng, "git")))
            # Two different git findings with two different fixes: "not a repo"
            # points at meta.gitRoot, "git is not on PATH" points at installing it.
            # Asserting the first unconditionally made this case depend on the
            # machine rather than on the code.
            _gfix = " ".join(r["fix"] or "" for r in rep_ng.rows
                             if r["check"] == "git")
            _gdet = detail(rep_ng, "git")
            check("the git finding is actionable for the actual cause",
                  ("gitRoot" in _gfix) if have_git else ("not on PATH" in _gdet),
                  "%s | %s" % (_gdet, _gfix))
            check("a non-repo exits 1", rep_ng.exit_code() == 1)
        finally:
            sh.rmtree(nogit, ignore_errors=True)

        # malformed config
        os.makedirs(os.path.join(tmp, ".claude"), exist_ok=True)
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{not json")
        rep = diagnose(tmp)
        check("malformed config is a FINDING", levels(rep, "config") == ["FINDING"])
        check("malformed config exits 1", rep.exit_code() == 1)

        # an invalid-but-parsing config value
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"enforce": "yes"}, fh)
        rep = diagnose(tmp)
        check("a config that parses but does not validate is a FINDING",
              levels(rep, "config") == ["FINDING"], detail(rep, "config"))

        # enforce:true is reported as deny even with no manifest
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"enforce": True, "manifestPath": "plan.json"}, fh)
        rep = diagnose(tmp)
        check("enforce:true is reported as the deny tier",
              "deny" in detail(rep, "plan gate"), detail(rep, "plan gate"))

        # a valid manifest at a custom path, with a running phase
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json"}, fh)
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2,
                                "buildCommands": {"test": "definitely-not-a-real-runner x"}},
                       "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                                   "tasks": [{"id": "P1.1", "title": "t",
                                              "status": "pending"}]}]}, fh)
        rep = diagnose(tmp)
        check("a valid manifest at a custom path is OK",
              levels(rep, "manifest") == ["OK"], detail(rep, "manifest"))
        check("a running phase is reported as the deny tier",
              "deny" in detail(rep, "plan gate"), detail(rep, "plan gate"))
        check("a missing buildCommands runner is a WARNING, not a FINDING "
              "(the machine lacks a tool; the repo is not broken)",
              levels(rep, "buildCommands") == ["WARNING"],
              repr(levels(rep, "buildCommands")))
        check("a missing runner does not fail the exit code",
              rep.exit_code() == 0, repr(rep.counts()))
        check("the buildCommands warning names the runner",
              "definitely-not-a-real-runner" in detail(rep, "buildCommands"))

        # an invalid manifest
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "p", "status": "pending",
                 "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                            "blockedBy": ["NOPE"]}]}]}, fh)
        rep = diagnose(tmp)
        check("an invalid manifest is a FINDING",
              levels(rep, "manifest") == ["FINDING"], detail(rep, "manifest"))

        # buildCommands present and resolvable
        real = "python3" if sh.which("python3") else "python"
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2,
                                "buildCommands": {"test": "%s -c pass" % real}},
                       "phases": [{"id": "P1", "title": "p", "status": "done",
                                   "tasks": [{"id": "P1.1", "title": "t",
                                              "status": "done"}]}]}, fh)
        rep = diagnose(tmp)
        check("a resolvable buildCommands runner is OK",
              levels(rep, "buildCommands") == ["OK"], detail(rep, "buildCommands"))
        check("a `cd x && runner` form resolves the runner, not cd", True)
        check("no running phase is reported as the warn tier",
              "warn" in detail(rep, "plan gate"), detail(rep, "plan gate"))

        # `cd ... && runner` - the git-in-subdir shape
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2, "buildCommands": {
                "test": "cd app && %s -c pass" % real}},
                "phases": [{"id": "P1", "title": "p", "status": "done",
                            "tasks": [{"id": "P1.1", "title": "t",
                                       "status": "done"}]}]}, fh)
        rep = diagnose(tmp)
        check("`cd x && runner` is resolved past the cd",
              levels(rep, "buildCommands") == ["OK"], detail(rep, "buildCommands"))

        # sharded layout: intact, then broken
        gen = _load("gen_demo_manifest", "gen-demo-manifest.py")
        shard_dir = os.path.join(tmp, "sharded")
        gen.write_manifest(gen.generate(n_phases=4, n_tasks=2, seed=11), shard_dir)
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "sharded/audit-plan.json"}, fh)
        rep = diagnose(tmp)
        check("an intact sharded layout is OK", levels(rep, "layout") == ["OK"],
              detail(rep, "layout"))
        os.remove(os.path.join(shard_dir, "phases", "P1.json"))
        rep = diagnose(tmp)
        check("a missing shard is a FINDING", levels(rep, "layout") == ["FINDING"],
              detail(rep, "layout"))

        # the executable resolver, against the shapes real manifests use. Guessing
        # here produced a false FINDING on this repo's own `for f in ...; do` loop.
        for cmd, want in (("yarn test", "yarn"),
                          ("python3 x.py --gate", "python3"),
                          ("cd app && yarn test", "yarn"),
                          ("cd a && cd b && npm run t", "npm"),
                          ("env CI=1 pytest -q", "pytest"),
                          ("CI=1 NODE_ENV=test jest", "jest"),
                          ("claude plugin validate . && claude plugin validate p",
                           "claude"),
                          ("./scripts/run.sh", "./scripts/run.sh"),
                          ("for f in a b; do python3 $f; done", None),
                          ("if [ -f x ]; then make; fi", None),
                          ("$RUNNER test", None),
                          ("", None)):
            got = _leading_executable(cmd)
            check("resolver: %r -> %r" % (cmd[:34], want), got == want, repr(got))

        # a shell-construct command is reported as unchecked, never as missing
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json"}, fh)
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2, "buildCommands": {
                "selftests": "for f in a b; do %s -c pass $f; done" % real}},
                "phases": [{"id": "P1", "title": "p", "status": "done",
                            "tasks": [{"id": "P1.1", "title": "t",
                                       "status": "done"}]}]}, fh)
        rep_sh = diagnose(tmp)
        check("a shell-construct gate is a WARNING, not a missing-runner FINDING",
              "FINDING" not in levels(rep_sh, "buildCommands"),
              repr(levels(rep_sh, "buildCommands")))
        check("and it says the runner was not checked",
              "not checked" in detail(rep_sh, "buildCommands"),
              detail(rep_sh, "buildCommands"))

        # rendering + json shape
        text = render(rep, tmp)
        check("render is pure ASCII", all(ord(c) < 128 for c in text))
        check("render carries no ANSI escapes", "\033" not in text)
        check("render prints the totals line", "finding(s)" in text)
        check("every row renders its level", text.count("[FINDING") >= 1)
        check("CLI exits 2 on a non-directory",
              main(["--project", os.path.join(tmp, "nope")]) == 2)
        check("CLI --json emits parseable JSON", _json_ok(tmp))
    finally:
        sh.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, det in cases:
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           (" (%s)" % det) if det and not ok else ""))
    print("\naudit-doctor: %d/%d cases passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


def _json_ok(project):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--project", project, "--json"])
    try:
        obj = json.loads(buf.getvalue())
        return isinstance(obj.get("checks"), list) and "counts" in obj
    except Exception:
        return False


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
