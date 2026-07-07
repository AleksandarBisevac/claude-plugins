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
  open-high-bugs   bugs with severity "high" not yet fixed/wontfix
  open-bugs        ANY bug not yet fixed/wontfix
  blocked-tasks    any task with status "blocked"
  in-progress      any phase or task "in_progress" (for release-freeze gates)

Exit codes: 0 pass · 1 gate failed · 2 usage error / unreadable manifest
(matching validate-manifest.py's convention).
"""
import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

CONDITIONS = ("invalid", "open-high-bugs", "open-bugs", "blocked-tasks",
              "in-progress")
DEFAULT_GATE = ("invalid", "open-high-bugs", "blocked-tasks")
CLOSED_BUG = ("fixed", "wontfix")


def _load_validator():
    """Import validate-manifest.py (hyphenated filename) as a library."""
    spec = importlib.util.spec_from_file_location(
        "validate_manifest", os.path.join(_HERE, "validate-manifest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ready_tasks(manifest):
    """Task ids ready to run — mirrors /audit's readiness rule: status pending,
    own blockedBy satisfied, own dependsOn all done, phase blockedBy satisfied
    ('satisfied' = referenced task/phase is done)."""
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


def rollup(manifest, findings, warnings):
    """The machine-readable summary both --json and render-report consume."""
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    tasks = [t for p in phases for t in (p.get("tasks") or [])
             if isinstance(t, dict)]
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    open_bugs = [b for b in bugs if b.get("status") not in CLOSED_BUG]
    return {
        "valid": not findings,
        "findings": len(findings),
        "warnings": len(warnings),
        "phases": [{
            "id": p.get("id"), "title": p.get("title"),
            "status": p.get("status"),
            "desiredOutcome": p.get("desiredOutcome"),
            "done": sum(1 for t in (p.get("tasks") or [])
                        if isinstance(t, dict) and t.get("status") == "done"),
            "total": sum(1 for t in (p.get("tasks") or [])
                         if isinstance(t, dict)),
        } for p in phases],
        "tasks": {"total": len(tasks), "byStatus": _by_status(tasks)},
        "bugs": {"total": len(bugs), "byStatus": _by_status(bugs),
                 "open": len(open_bugs),
                 "openHighSeverity": sum(
                     1 for b in open_bugs
                     if str(b.get("severity", "")).lower() == "high")},
        "ready": ready_tasks(manifest),
    }


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


def main(argv):
    args = list(argv)
    want_json = "--json" in args
    want_gate = "--gate" in args
    for flag in ("--json", "--gate"):
        while flag in args:
            args.remove(flag)
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
            "[--fail-on <c1,c2,...>]\n")
        return 2

    try:
        with open(args[0], "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (args[0], exc))
        return 2

    vm = _load_validator()
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []

    summary = rollup(manifest, findings, warnings)

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

    # (j) --json output round-trips with the expected fields
    blob = json.loads(json.dumps(summarize(_fixture())))
    check("j1 rollup fields present",
          blob["tasks"]["total"] == 3 and blob["bugs"]["total"] == 1
          and blob["phases"][0]["done"] == 1 and blob["valid"] is True)

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
    os.unlink(path)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
