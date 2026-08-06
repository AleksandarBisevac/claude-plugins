#!/usr/bin/env python3
"""
Headless status rollup + CI gate for the audit manifest — dependency-free (stdlib).

Turns the manifest into a machine-readable summary and, in gate mode, a CI
pass/fail signal — so a pipeline can block a merge on manifest state without
any Claude session involved.

Usage:
  audit-status.py <manifest> [--json] [--gate] [--fail-on <c1,c2,...>]
  audit-status.py --selftest

Modes (combinable; --json is the default when neither flag is given):
  --json    print the rollup as JSON
  --gate    evaluate fail conditions; exit 1 when any trips (prints a summary)

Conditions for --fail-on (comma list; the --gate default is
`invalid,open-high-bugs,blocked-tasks`):
  invalid          the structural validator reports findings
  open-high-bugs   high-or-worse severity bugs not yet fixed/wontfix
                   (high/critical/blocker/severe/fatal/urgent/sev0-1/s0-1/p0-1)
  open-bugs        ANY bug not yet fixed/wontfix
  blocked-tasks    any task with status "blocked"
  in-progress      any phase or task "in_progress" (for release-freeze gates)

Exit codes: 0 pass · 1 gate failed · 2 usage error / unreadable manifest
(matching validate-manifest.py's convention).
"""
import importlib.util
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)

CONDITIONS = ("invalid", "open-high-bugs", "open-bugs", "blocked-tasks",
              "in-progress")
DEFAULT_GATE = ("invalid", "open-high-bugs", "blocked-tasks")
CLOSED_BUG = ("fixed", "wontfix")

# "open-high-bugs" must catch high-severity-or-worse, not only the literal word
# "high" — a bug filed as critical/blocker/sev1/p0 is the LAST thing a merge
# gate should wave through. Severity is free-text, so normalise (lowercase,
# drop non-alphanumerics) and match a vocabulary of high-or-worse terms.
HIGH_SEVERITIES = frozenset({
    "high", "critical", "crit", "blocker", "severe", "fatal", "urgent",
    "sev0", "sev1", "s0", "s1", "p0", "p1",
})


def _is_high_severity(severity):
    """True for high-or-worse free-text severities (see HIGH_SEVERITIES)."""
    return re.sub(r"[^a-z0-9]", "", str(severity or "").lower()) in HIGH_SEVERITIES


def _load_validator():
    """Import validate-manifest.py (hyphenated filename) as a library."""
    spec = importlib.util.spec_from_file_location(
        "validate_manifest", os.path.join(_HERE, "validate-manifest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- submodule conflict detection (preflight guard) -----------------------------
# The orchestrator commits from ONE git repo (the resolved gitRoot). Files that
# live inside a git SUBMODULE belong to a separate nested repo — the parent
# cannot stage them ("Pathspec is in submodule"), so a task touching them would
# fail at commit time. This flags them up front.

def parse_gitmodules(text):
    """Submodule paths (git-root-relative) from a .gitmodules file's text."""
    paths = []
    for line in str(text).splitlines():
        s = line.strip()
        # `.gitmodules` uses `path = <dir>` inside each [submodule "..."] block
        if s.lower().startswith("path") and "=" in s:
            val = s.split("=", 1)[1].strip().replace("\\", "/").strip("/")
            if val:
                paths.append(val)
    return paths


def _strip_git_root(path, git_root):
    """Project-relative file -> git-root-relative (drop the gitRoot prefix and any
    `:line` suffix)."""
    p = str(path).replace("\\", "/").split(":", 1)[0]
    gr = str(git_root or "").replace("\\", "/").strip("/")
    if gr and (p == gr or p.startswith(gr + "/")):
        return p[len(gr) + 1:]
    return p


def submodule_conflicts(manifest, submodule_paths, git_root=""):
    """List of (task_id, file, submodule) for each task file that lives inside a
    submodule. `files` are project-relative (gitRoot-prefixed); `submodule_paths`
    are git-root-relative. Path-boundary safe: 'vendor/child' matches
    'vendor/child/x' but NOT 'vendor/child-other/x'."""
    subs = [str(s).replace("\\", "/").strip("/") for s in (submodule_paths or []) if s]
    out = []
    if not isinstance(manifest, dict):
        return out
    for ph in manifest.get("phases") or []:
        if not isinstance(ph, dict):
            continue
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            for f in t.get("files") or []:
                rel = _strip_git_root(f, git_root)
                for s in subs:
                    if rel == s or rel.startswith(s + "/"):
                        out.append((t.get("id"), f, s))
                        break
    return out


def ready_tasks(manifest):
    """Task ids ready to run — mirrors /audit's readiness rule: status pending,
    own blockedBy satisfied, own dependsOn all done, phase blockedBy satisfied
    ('satisfied' = referenced task/phase is done)."""
    if not isinstance(manifest, dict):
        return []
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    status = {}
    for ph in phases:
        if ph.get("id"):
            status[ph["id"]] = ph.get("status")
        for t in ph.get("tasks") or []:
            if isinstance(t, dict) and t.get("id"):
                status[t["id"]] = t.get("status")

    def satisfied(refs):
        return all(status.get(r) == "done" for r in (refs or []))

    out = []
    for ph in phases:
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict) or t.get("status") != "pending":
                continue
            if not satisfied(t.get("blockedBy")):
                continue
            if not satisfied(t.get("dependsOn")):
                continue
            if not satisfied(ph.get("blockedBy")):
                continue
            if t.get("id"):
                out.append(t["id"])
    return out


def _by_status(items):
    out = {}
    for it in items:
        s = it.get("status") if isinstance(it, dict) else None
        out[str(s)] = out.get(str(s), 0) + 1
    return out


def _by_status_values(values):
    out = {}
    for s in values:
        out[str(s)] = out.get(str(s), 0) + 1
    return out


def areas_of(area):
    """Normalize a phase's `area` (a string partition, a list of cross-cutting tags,
    or absent) to a list of tag strings — so a phase can belong to several areas
    (e.g. ['backend', 'security'])."""
    if isinstance(area, str):
        return [area] if area else []
    if isinstance(area, list):
        return [a for a in area if isinstance(a, str) and a]
    return []


def effective_bug_status(bug, task_by_id):
    """A bug's status, DERIVING 'fixed' from its linked task.

    The orchestrator never writes bugs[] during a run (that keeps the shared index
    untouched, so parallel phase branches merge clean). Instead a bug materialized
    into a task (bug.taskId <-> task.bugId) reads as 'fixed' once that task is done.
    A human-set 'wontfix' always wins; an un-materialized bug keeps its reported
    status (open/triaged/in_progress)."""
    stored = bug.get("status")
    if stored == "wontfix":
        return "wontfix"
    tid = bug.get("taskId")
    t = task_by_id.get(tid) if tid else None
    if isinstance(t, dict) and t.get("status") == "done":
        return "fixed"
    return stored


def usage_summary(manifest, manifest_path, project_dir=None):
    """Compact token-usage block for the rollup, or None when there is no ledger.

    Kept OUT of `rollup` so that function stays a pure dict -> dict transform; the
    ledger is I/O and belongs to the caller. Never raises: a missing, empty or
    unreadable ledger simply means no usage key, and every consumer treats that as
    "metering not in use" rather than an error."""
    try:
        spec = importlib.util.spec_from_file_location(
            "usage_ledger", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "usage_ledger.py"))
        ul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ul)
    except Exception:
        return None

    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    rel = (meta_usage.get("ledgerDir")
           if isinstance(meta_usage, dict) else None) or os.path.join(
               ".claude", "usage")
    if project_dir is None:
        # The manifest conventionally lives at docs/audit/<name>.json, so the repo
        # root is two levels up. CLAUDE_PROJECT_DIR wins when it is set.
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(manifest_path))))
    ledger_dir = rel if os.path.isabs(rel) else os.path.join(project_dir, rel)

    try:
        rows = ul.read_ledger(ledger_dir)
    except Exception:
        return None
    if not rows:
        return None
    try:
        total = ul.totals(rows)
        by_phase = ul.aggregate(rows, "phase")
        return {
            "ledgerDir": ledger_dir,
            "pricingAsOf": meta_usage.get("pricingAsOf")
            if isinstance(meta_usage, dict) else None,
            "showCost": bool(meta_usage.get("showCost", True))
            if isinstance(meta_usage, dict) else True,
            "totals": total,
            "byPhase": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                            "msgs": v["msgs"]} for k, v in by_phase.items()},
            "byModel": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                            "msgs": v["msgs"]}
                        for k, v in ul.aggregate(rows, "model").items()},
            "byAuthor": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                             "msgs": v["msgs"]}
                         for k, v in ul.aggregate(rows, "author").items()},
        }
    except Exception:
        return None


def rollup(manifest, findings, warnings, usage=None):
    """The machine-readable summary --json, render-report and the panel consume.

    `usage` is the optional block from `usage_summary()`; it is passed in rather
    than read here so this stays a pure dict -> dict transform."""
    if not isinstance(manifest, dict):
        manifest = {}  # non-object root -> empty rollup, never an AttributeError
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    tasks = [t for p in phases for t in (p.get("tasks") or [])
             if isinstance(t, dict)]
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    task_by_id = {t["id"]: t for t in tasks if t.get("id")}
    bug_eff = [effective_bug_status(b, task_by_id) for b in bugs]
    open_bugs = [b for b, s in zip(bugs, bug_eff) if s not in CLOSED_BUG]
    phase_entries = [{
        "id": p.get("id"), "title": p.get("title"),
        "status": p.get("status"), "area": areas_of(p.get("area")),
        "desiredOutcome": p.get("desiredOutcome"),
        "done": sum(1 for t in (p.get("tasks") or [])
                    if isinstance(t, dict) and t.get("status") == "done"),
        "total": sum(1 for t in (p.get("tasks") or []) if isinstance(t, dict)),
    } for p in phases]
    # group phases by each of their `area` tags (a phase with several tags counts
    # under each; untagged phases are simply not grouped)
    areas = {}
    for e in phase_entries:
        for a in e["area"]:
            g = areas.setdefault(a, {"phases": 0, "done": 0, "total": 0})
            g["phases"] += 1
            g["done"] += e["done"]
            g["total"] += e["total"]
    out = {
        "valid": not findings,
        "findings": len(findings),
        "warnings": len(warnings),
        "phases": phase_entries,
        "areas": areas,
        "tasks": {"total": len(tasks), "byStatus": _by_status(tasks)},
        "bugs": {"total": len(bugs), "byStatus": _by_status_values(bug_eff),
                 "open": len(open_bugs),
                 "openHighSeverity": sum(
                     1 for b in open_bugs
                     if _is_high_severity(b.get("severity")))},
        "ready": ready_tasks(manifest),
    }
    # Only present when a ledger exists, so consumers can treat "no key" as
    # "metering not in use" without a second probe.
    if usage:
        out["usage"] = usage
    return out


def evaluate_gate(summary, conditions):
    """Return the list of FAILED condition names."""
    failed = []
    for c in conditions:
        if c == "invalid" and not summary["valid"]:
            failed.append(c)
        elif c == "open-high-bugs" and summary["bugs"]["openHighSeverity"] > 0:
            failed.append(c)
        elif c == "open-bugs" and summary["bugs"]["open"] > 0:
            failed.append(c)
        elif c == "blocked-tasks" and summary["tasks"]["byStatus"].get(
                "blocked", 0) > 0:
            failed.append(c)
        elif c == "in-progress" and (
                summary["tasks"]["byStatus"].get("in_progress", 0) > 0
                or any(p.get("status") == "in_progress"
                       for p in summary["phases"])):
            failed.append(c)
    return failed


def _extract_opt(args, flag):
    """Pull `--flag value` out of args; return the value or None."""
    if flag in args:
        i = args.index(flag)
        if i + 1 >= len(args):
            return "__MISSING__"
        val = args[i + 1]
        del args[i:i + 2]
        return val
    return None


def main(argv):
    args = list(argv)
    want_json = "--json" in args
    want_gate = "--gate" in args
    for flag in ("--json", "--gate"):
        while flag in args:
            args.remove(flag)

    # --submodules <.gitmodules path> [--git-root <prefix>]: preflight guard,
    # exits 1 when a task file lives inside a submodule. Standalone mode.
    gitmodules = _extract_opt(args, "--submodules")
    git_root_prefix = _extract_opt(args, "--git-root") or ""
    if git_root_prefix == "__MISSING__":
        sys.stderr.write("usage: --git-root <prefix>\n")
        return 2

    conditions = list(DEFAULT_GATE)
    if "--fail-on" in args:
        i = args.index("--fail-on")
        if i + 1 >= len(args):
            sys.stderr.write("usage: --fail-on <%s>[,...]\n" % "|".join(CONDITIONS))
            return 2
        conditions = [c.strip() for c in args[i + 1].split(",") if c.strip()]
        unknown = [c for c in conditions if c not in CONDITIONS]
        if unknown:
            sys.stderr.write("unknown condition(s): %s (known: %s)\n"
                             % (", ".join(unknown), ", ".join(CONDITIONS)))
            return 2
        del args[i:i + 2]
    if len(args) != 1:
        sys.stderr.write(
            "usage: audit-status.py <manifest> [--json] [--gate] "
            "[--fail-on <c1,c2,...>] [--submodules <.gitmodules> [--git-root <prefix>]]\n")
        return 2

    try:
        manifest = _mio.load_manifest(args[0])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (args[0], exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: %s is not a JSON object (got %s)\n"
                         % (args[0], type(manifest).__name__))
        return 2

    if gitmodules is not None:
        if gitmodules == "__MISSING__":
            sys.stderr.write("usage: --submodules <path-to-.gitmodules>\n")
            return 2
        try:
            with open(gitmodules, "r", encoding="utf-8") as fh:
                sub_paths = parse_gitmodules(fh.read())
        except (FileNotFoundError, NotADirectoryError):
            sub_paths = []  # no .gitmodules => no submodules => clean
        except Exception as exc:
            sys.stderr.write("ERROR: cannot read %s: %s\n" % (gitmodules, exc))
            return 2
        conflicts = submodule_conflicts(manifest, sub_paths, git_root_prefix)
        if conflicts:
            for tid, f, sub in conflicts:
                print("SUBMODULE CONFLICT: task %s file '%s' is inside submodule '%s'"
                      % (tid, f, sub))
            print("\n%d task file(s) live inside a submodule — the orchestrator "
                  "cannot commit them from the parent repo. Point meta.gitRoot at "
                  "the submodule, or remove those files from the task(s)."
                  % len(conflicts))
            return 1
        print("OK: no task files inside submodules (%d submodule(s) checked)"
              % len(sub_paths))
        return 0

    vm = _load_validator()
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []

    summary = rollup(manifest, findings, warnings,
                     usage=usage_summary(manifest, args[0]))

    if want_gate:
        failed = evaluate_gate(summary, conditions)
        summary["gate"] = {
            "conditions": conditions,
            "failed": failed,
            "passed": [c for c in conditions if c not in failed],
        }

    if want_json or not want_gate:
        print(json.dumps(summary, indent=2))

    if want_gate:
        failed = summary["gate"]["failed"]
        if failed:
            for c in failed:
                detail = {
                    "invalid": "%d validator finding(s)" % summary["findings"],
                    "open-high-bugs": "%d open high-severity bug(s)"
                                      % summary["bugs"]["openHighSeverity"],
                    "open-bugs": "%d open bug(s)" % summary["bugs"]["open"],
                    "blocked-tasks": "%d blocked task(s)"
                                     % summary["tasks"]["byStatus"].get("blocked", 0),
                    "in-progress": "work in progress",
                }.get(c, "")
                print("GATE FAILED: %s (%s)" % (c, detail))
            return 1
        print("GATE PASSED: %s" % ", ".join(conditions))
    return 0


# --- selftest -------------------------------------------------------------------
def _fixture():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P1", "title": "Done phase", "status": "done", "tasks": [
                {"id": "P1.1", "title": "t", "status": "done",
                 "files": ["src/a.ts"]},
            ]},
            {"id": "P2", "title": "Next phase", "status": "pending",
             "blockedBy": ["P1"], "tasks": [
                 {"id": "P2.1", "title": "ready", "status": "pending",
                  "dependsOn": [], "files": ["src/b.ts"]},
                 {"id": "P2.2", "title": "waits", "status": "pending",
                  "dependsOn": ["P2.1"]},
             ]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["P2.1"]},
        "bugs": [
            {"id": "BUG-1", "title": "fixed one", "status": "fixed",
             "severity": "high"},
        ],
    }


def _selftest():
    import copy

    results = []
    vm = _load_validator()

    def summarize(m):
        findings, warnings = vm.validate(m)
        return rollup(m, findings, warnings)

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

    # (r) readiness mirrors /audit's rule
    s = summarize(_fixture())
    check("r1 ready = dependency-satisfied pending tasks", s["ready"] == ["P2.1"],
          repr(s["ready"]))
    m = copy.deepcopy(_fixture())
    m["phases"][0]["status"] = "pending"
    m["phases"][0]["tasks"][0]["status"] = "pending"
    s = summarize(m)
    check("r2 phase blockedBy gates readiness",
          "P2.1" not in s["ready"] and "P1.1" in s["ready"], repr(s["ready"]))

    # (ar) area tag(s) — normalized to a list, surfaced per phase + grouped in rollup;
    # a phase may carry several cross-cutting tags (e.g. ['mobile', 'security'])
    m = copy.deepcopy(_fixture())
    m["phases"][0]["area"] = "backend"                 # single string
    m["phases"][1]["area"] = ["mobile", "security"]    # cross-cutting tags
    s = summarize(m)
    check("ar1 area normalized to a list per phase",
          s["phases"][0]["area"] == ["backend"]
          and s["phases"][1]["area"] == ["mobile", "security"])
    check("ar2 areas grouping counts phases + tasks",
          set(s["areas"].keys()) == {"backend", "mobile", "security"}
          and s["areas"]["backend"]["phases"] == 1
          and s["areas"]["backend"]["total"] == s["phases"][0]["total"], repr(s["areas"]))
    check("ar3 a multi-tag phase counts under EACH of its areas",
          s["areas"]["mobile"]["phases"] == 1 and s["areas"]["security"]["phases"] == 1
          and s["areas"]["security"]["total"] == s["phases"][1]["total"], repr(s["areas"]))
    s0 = summarize(_fixture())
    check("ar4 untagged manifest -> empty areas (back-compat)", s0["areas"] == {})

    # (u) usage block — absent unless a ledger exists, so every existing consumer
    # keeps working untouched
    check("u1 no ledger -> no usage key (back-compat)",
          "usage" not in summarize(_fixture()))
    check("u2 rollup(usage=None) omits the key",
          "usage" not in rollup(_fixture(), [], [], usage=None))
    fake_usage = {"ledgerDir": "/tmp/x", "totals": {"tokens": 10, "costUSD": 1.0}}
    su = rollup(_fixture(), [], [], usage=fake_usage)
    check("u3 rollup passes a supplied usage block straight through",
          su["usage"] == fake_usage)
    check("u4 usage never perturbs the rest of the rollup",
          {k: v for k, v in su.items() if k != "usage"} == summarize(_fixture()))
    import tempfile as _tf
    _empty = _tf.mkdtemp(prefix="audit-status-usage-")
    try:
        check("u5 usage_summary tolerates a missing ledger dir",
              usage_summary({}, os.path.join(_empty, "a", "b", "m.json")) is None)
        os.makedirs(os.path.join(_empty, ".claude", "usage"), exist_ok=True)
        check("u6 usage_summary tolerates an empty ledger dir",
              usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                            project_dir=_empty) is None)
        with open(os.path.join(_empty, ".claude", "usage", "2026-08.jsonl"),
                  "w", encoding="utf-8") as _fh:
            _fh.write(json.dumps({
                "ts": "2026-08-06T07", "sessionId": "s1", "phaseId": "P1",
                "taskId": "P1.1", "attr": "task", "model": "claude-opus-5",
                "author": "a@b.c", "msgs": 1, "in": 10, "out": 20,
                "cacheW5m": 0, "cacheW1h": 0, "cacheR": 5, "costUSD": 0.5}) + "\n")
        u = usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                          project_dir=_empty)
        check("u7 usage_summary reads a real ledger",
              u and u["totals"]["tokens"] == 35 and u["totals"]["msgs"] == 1)
        check("u8 usage_summary groups by phase, model and author",
              "P1" in u["byPhase"] and "claude-opus-5" in u["byModel"]
              and "a@b.c" in u["byAuthor"])
        with open(os.path.join(_empty, ".claude", "usage", "2026-08.jsonl"),
                  "a", encoding="utf-8") as _fh:
            _fh.write("{ torn\n")
        check("u9 usage_summary survives a torn ledger line",
              usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                            project_dir=_empty)["totals"]["tokens"] == 35)
    finally:
        import shutil as _sh
        _sh.rmtree(_empty, ignore_errors=True)

    # (g) gate conditions
    s = summarize(_fixture())
    check("g1 clean manifest passes default gate",
          evaluate_gate(s, DEFAULT_GATE) == [])
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "open",
                      "severity": "high"})
    s = summarize(m)
    check("g2 open high-severity bug trips", "open-high-bugs" in
          evaluate_gate(s, DEFAULT_GATE))
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "triaged",
                      "severity": "low"})
    s = summarize(m)
    check("g3 low-sev open bug passes default but trips open-bugs",
          evaluate_gate(s, DEFAULT_GATE) == []
          and "open-bugs" in evaluate_gate(s, ("open-bugs",)))

    # (d) derived bug status — a bug materialized into a DONE task reads as fixed
    #     even though bugs[].status is still 'open' (the orchestrator never writes
    #     bugs[] during a run, so the index stays untouched for parallel phases).
    dm = {"meta": {"version": 2},
          "phases": [{"id": "P0", "title": "P", "status": "in_progress", "tasks": [
              {"id": "P0.1", "title": "fix", "status": "done", "bugId": "BUG-1"}]}],
          "bugs": [{"id": "BUG-1", "title": "b", "status": "open", "severity": "high",
                    "taskId": "P0.1"}]}
    s = summarize(dm)
    check("d1 bug on a done task derives fixed (index untouched)",
          s["bugs"]["byStatus"].get("fixed", 0) == 1 and s["bugs"]["open"] == 0
          and s["bugs"]["openHighSeverity"] == 0
          and evaluate_gate(s, ("open-high-bugs", "open-bugs")) == [], repr(s["bugs"]))
    dm2 = copy.deepcopy(dm)
    dm2["phases"][0]["tasks"][0]["status"] = "in_progress"
    s2 = summarize(dm2)
    check("d2 bug on a not-done task stays open",
          s2["bugs"]["open"] == 1 and s2["bugs"]["byStatus"].get("open", 0) == 1,
          repr(s2["bugs"]))
    m = copy.deepcopy(_fixture())
    m["phases"][1]["tasks"][0]["status"] = "blocked"
    s = summarize(m)
    check("g4 blocked task trips", "blocked-tasks" in
          evaluate_gate(s, DEFAULT_GATE))
    m = copy.deepcopy(_fixture())
    m["phases"][1]["tasks"][0]["status"] = "doing"  # invalid enum
    s = summarize(m)
    check("g5 validator findings trip invalid", "invalid" in
          evaluate_gate(s, DEFAULT_GATE) and s["valid"] is False)
    m = copy.deepcopy(_fixture())
    m["phases"][1]["status"] = "in_progress"
    s = summarize(m)
    check("g6 in-progress trips only when asked",
          evaluate_gate(s, DEFAULT_GATE) == []
          and "in-progress" in evaluate_gate(s, ("in-progress",)))

    # (g7) open-high-bugs catches high-OR-WORSE severities, not only "high"
    for sev in ("critical", "Blocker", "sev1", "P0", "URGENT", "sev-1"):
        m = copy.deepcopy(_fixture())
        m["bugs"].append({"id": "BUG-9", "title": "bad", "status": "open",
                          "severity": sev})
        s = summarize(m)
        check("g7 open %r bug trips open-high-bugs" % sev,
              "open-high-bugs" in evaluate_gate(s, DEFAULT_GATE))
    # a genuinely low severity must still NOT trip it (no false positive)
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-9", "title": "minor", "status": "open",
                      "severity": "low"})
    s = summarize(m)
    check("g8 open low-severity bug does NOT trip open-high-bugs",
          "open-high-bugs" not in evaluate_gate(s, DEFAULT_GATE))

    # (nd) a non-object manifest root must never crash the rollup path
    check("nd1 rollup on list root -> empty, no crash",
          rollup([], [], [])["tasks"]["total"] == 0)
    check("nd2 ready_tasks on None root -> [], no crash", ready_tasks(None) == [])
    check("nd3 submodule_conflicts on scalar root -> [], no crash",
          submodule_conflicts("nope", ["vendor/x"]) == [])

    # (j) --json output round-trips with the expected fields
    blob = json.loads(json.dumps(summarize(_fixture())))
    check("j1 rollup fields present",
          blob["tasks"]["total"] == 3 and blob["bugs"]["total"] == 1
          and blob["phases"][0]["done"] == 1 and blob["valid"] is True)

    # (s) submodule conflict detection
    check("s1 parse_gitmodules extracts paths", parse_gitmodules(
        '[submodule "vendor/child"]\n\tpath = vendor/child\n\turl = ../child\n'
        '[submodule "libs/x"]\n  path = libs/x\n  url = ../x\n')
        == ["vendor/child", "libs/x"])
    subm = {"meta": {"version": 2}, "phases": [{"id": "P0", "title": "p",
        "status": "pending", "tasks": [
            {"id": "P0.1", "title": "in submodule", "status": "pending",
             "files": ["vendor/child/src/foo.ts"]},
            {"id": "P0.2", "title": "boundary — NOT in submodule", "status": "pending",
             "files": ["vendor/child-other/x.ts"]},
            {"id": "P0.3", "title": "outside", "status": "pending",
             "files": ["src/app.ts"]},
        ]}]}
    conf = submodule_conflicts(subm, ["vendor/child"])
    check("s2 file inside submodule flagged", conf == [("P0.1", "vendor/child/src/foo.ts", "vendor/child")],
          repr(conf))
    check("s3 path-boundary: child-other NOT flagged",
          all(c[0] != "P0.2" for c in conf))
    # git_root prefix stripping: files are project-relative, submodules git-root-relative
    subm_gr = {"meta": {"version": 2}, "phases": [{"id": "P0", "title": "p",
        "status": "pending", "tasks": [{"id": "P0.1", "title": "t", "status": "pending",
        "files": ["test/vendor/child/src/foo.ts", "test/src/app.ts"]}]}]}
    conf_gr = submodule_conflicts(subm_gr, ["vendor/child"], git_root="test")
    check("s4 gitRoot prefix stripped before match",
          [c[0] for c in conf_gr] == ["P0.1"] and conf_gr[0][1].startswith("test/vendor"))
    check("s5 :line suffix tolerated", submodule_conflicts(
        {"meta": {}, "phases": [{"id": "P", "title": "p", "status": "pending",
         "tasks": [{"id": "P.1", "title": "t", "status": "pending",
                    "files": ["vendor/child/a.ts:10-20"]}]}]}, ["vendor/child"]) != [])

    # (c) CLI: exit codes 0 / 1 / 2
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_fixture(), fh)
    check("c1 CLI gate passes clean manifest (exit 0)",
          main([path, "--gate"]) == 0)
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "open",
                      "severity": "high"})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(m, fh)
    check("c2 CLI gate fails on open high bug (exit 1)",
          main([path, "--gate"]) == 1)
    check("c3 CLI usage error (exit 2)", main([]) == 2)
    check("c4 CLI unknown condition (exit 2)",
          main([path, "--gate", "--fail-on", "frobnicate"]) == 2)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    check("c5 CLI unreadable manifest (exit 2)", main([path, "--gate"]) == 2)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(["not", "an", "object"], fh)
    check("c5b CLI non-object JSON root (exit 2)", main([path, "--gate"]) == 2)
    os.unlink(path)

    # (cs) CLI --submodules mode
    fd, mpath = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(subm, fh)  # has P0.1 inside vendor/child
    fd, gm = tempfile.mkstemp(suffix=".gitmodules")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write('[submodule "vendor/child"]\n\tpath = vendor/child\n\turl = ../child\n')
    check("cs1 CLI flags submodule conflict (exit 1)",
          main([mpath, "--submodules", gm]) == 1)
    check("cs2 CLI clean when no .gitmodules (exit 0)",
          main([mpath, "--submodules", os.path.join(tempfile.gettempdir(), "nope.gitmodules")]) == 0)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"version": 2}, "phases": [{"id": "P", "title": "p",
            "status": "pending", "tasks": [{"id": "P.1", "title": "t",
            "status": "pending", "files": ["src/app.ts"]}]}]}, fh)
    check("cs3 CLI clean when no task in a submodule (exit 0)",
          main([mpath, "--submodules", gm]) == 0)
    os.unlink(mpath)
    os.unlink(gm)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
