#!/usr/bin/env python3
"""
Structural validator for the audit manifest — dependency-free (stdlib only).

Complements the JSON Schema (schema/audit-plan.schema.json) with the referential
checks a schema cannot express: unique ids, resolvable blockedBy/dependsOn,
fileIndex integrity, and the bugs[] <-> task.bugId cross-links. Commands run it
after EVERY manifest mutation (the Edit-and-revalidate rule in
reference/manifest-conventions.md).

Usage:
  python3 validate-manifest.py <manifest-path>   # exit 0 = valid; exit 1 = findings
  python3 validate-manifest.py --selftest

The core `validate(manifest)` is pure and never raises on arbitrary JSON input —
shape surprises become findings, not tracebacks.
"""
import json
import re
import sys

STATUS = ("pending", "in_progress", "blocked", "done")
TESTS_MODE = ("tdd", "regression", "gate-only")
RISK = ("low", "med", "high", None)
BUG_STATUS = ("open", "triaged", "in_progress", "fixed", "wontfix")
BUG_ID_RE = re.compile(r"^BUG-\d+$")


def _require_fields(obj, where, findings):
    ok = True
    for key in ("id", "title", "status"):
        if not obj.get(key):
            findings.append("%s: missing required '%s'" % (where, key))
            ok = False
    return ok


def validate(manifest):
    """Return a list of finding strings; empty list = valid."""
    f = []
    if not isinstance(manifest, dict):
        return ["manifest root must be a JSON object"]

    meta = manifest.get("meta")
    if not isinstance(meta, dict):
        f.append("meta: missing or not an object")
    elif not isinstance(meta.get("version"), int):
        f.append("meta.version: missing or not an integer")

    phases = manifest.get("phases")
    if not isinstance(phases, list):
        f.append("phases: missing or not an array")
        phases = []

    phase_ids, task_ids, task_bug_links = [], [], []

    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            f.append("phases[%d]: not an object" % pi)
            continue
        pid = phase.get("id")
        pwhere = "phase %s" % (pid or ("phases[%d]" % pi))
        _require_fields(phase, pwhere, f)
        if pid:
            phase_ids.append(pid)
        if phase.get("status") not in STATUS:
            f.append("%s: status %r not in %s" % (pwhere, phase.get("status"), list(STATUS)))

        for ti, task in enumerate(phase.get("tasks") or []):
            if not isinstance(task, dict):
                f.append("%s tasks[%d]: not an object" % (pwhere, ti))
                continue
            tid = task.get("id")
            twhere = "task %s" % (tid or ("%s.tasks[%d]" % (pwhere, ti)))
            _require_fields(task, twhere, f)
            if tid:
                task_ids.append(tid)
            if task.get("status") not in STATUS:
                f.append("%s: status %r not in %s" % (twhere, task.get("status"), list(STATUS)))
            tests = task.get("tests")
            if isinstance(tests, dict) and tests.get("mode") not in TESTS_MODE:
                f.append("%s: tests.mode %r not in %s" % (twhere, tests.get("mode"), list(TESTS_MODE)))
            if "risk" in task and task.get("risk") not in RISK:
                f.append("%s: risk %r not in %s" % (twhere, task.get("risk"), ["low", "med", "high", None]))
            if task.get("bugId"):
                task_bug_links.append((twhere, task["bugId"]))

    # -- unique ids across phases + tasks + bugs -------------------------------
    bugs = manifest.get("bugs")
    bug_list = bugs if isinstance(bugs, list) else []
    bug_ids = [b.get("id") for b in bug_list if isinstance(b, dict) and b.get("id")]

    all_ids = phase_ids + task_ids + bug_ids
    seen = set()
    for i in all_ids:
        if i in seen:
            f.append("duplicate id: %s" % i)
        seen.add(i)

    known = set(phase_ids) | set(task_ids)

    # -- blockedBy / dependsOn resolve ------------------------------------------
    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        pwhere = "phase %s" % (phase.get("id") or ("phases[%d]" % pi))
        for ref in phase.get("blockedBy") or []:
            if ref not in known:
                f.append("%s: blockedBy '%s' does not resolve to any task/phase" % (pwhere, ref))
        for ti, task in enumerate(phase.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or ("%s.tasks[%d]" % (pwhere, ti)))
            for ref in task.get("blockedBy") or []:
                if ref not in known:
                    f.append("%s: blockedBy '%s' does not resolve to any task/phase" % (twhere, ref))
            for ref in task.get("dependsOn") or []:
                if ref not in task_ids:
                    f.append("%s: dependsOn '%s' does not resolve to a task" % (twhere, ref))

    # -- fileIndex integrity -----------------------------------------------------
    file_index = manifest.get("fileIndex")
    if isinstance(file_index, dict):
        for fpath, refs in file_index.items():
            for ref in refs if isinstance(refs, list) else []:
                if ref not in task_ids:
                    f.append("fileIndex['%s']: task '%s' does not exist" % (fpath, ref))

    # -- bugs[] ------------------------------------------------------------------
    if bugs is not None and not isinstance(bugs, list):
        f.append("bugs: not an array")
    for bi, bug in enumerate(bug_list):
        if not isinstance(bug, dict):
            f.append("bugs[%d]: not an object" % bi)
            continue
        bid = bug.get("id")
        bwhere = "bug %s" % (bid or ("bugs[%d]" % bi))
        _require_fields(bug, bwhere, f)
        if bid and not BUG_ID_RE.match(str(bid)):
            f.append("%s: id must match BUG-<number>" % bwhere)
        if bug.get("status") not in BUG_STATUS:
            f.append("%s: status %r not in %s" % (bwhere, bug.get("status"), list(BUG_STATUS)))
        if bug.get("taskId") and bug["taskId"] not in task_ids:
            f.append("%s: taskId '%s' does not resolve to a task" % (bwhere, bug["taskId"]))

    for twhere, bug_ref in task_bug_links:
        if bug_ref not in bug_ids:
            f.append("%s: bugId '%s' does not resolve to a bug" % (twhere, bug_ref))

    return f


def main(argv):
    if len(argv) != 1:
        print("usage: validate-manifest.py <manifest-path>")
        return 1
    try:
        with open(argv[0], "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:
        print("FINDING: cannot read/parse %s: %s" % (argv[0], exc))
        return 1

    try:
        findings = validate(manifest)
    except Exception as exc:  # defensive; validate() should never raise
        print("FINDING: internal validator error: %s" % exc)
        return 1

    if findings:
        for line in findings:
            print("FINDING: " + line)
        print("\nINVALID: %d finding(s) in %s" % (len(findings), argv[0]))
        return 1

    n_tasks = sum(len(p.get("tasks") or []) for p in manifest.get("phases", []) if isinstance(p, dict))
    print("OK: %s valid (%d phases, %d tasks, %d bugs)"
          % (argv[0], len(manifest.get("phases", [])), n_tasks,
             len(manifest.get("bugs") or [])))
    return 0


# --- selftest -------------------------------------------------------------------
def _valid_manifest():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P0", "title": "Phase", "status": "pending", "tasks": [
                {"id": "P0.1", "title": "Task", "status": "pending",
                 "tests": {"mode": "regression"}, "risk": "low",
                 "blockedBy": [], "dependsOn": []},
                {"id": "P0.2", "title": "Task 2", "status": "pending",
                 "dependsOn": ["P0.1"], "bugId": "BUG-1"},
            ]},
        ],
        "fileIndex": {"src/a.ts": ["P0.1"]},
        "bugs": [
            {"id": "BUG-1", "title": "A bug", "status": "in_progress",
             "taskId": "P0.2"},
        ],
    }


def _selftest():
    import copy

    results = []

    def check(name, expect_finding, mutate=None):
        m = copy.deepcopy(_valid_manifest())
        if mutate:
            mutate(m)
        findings = validate(m)
        if expect_finding is None:
            ok = findings == []
            detail = "expected clean, got %s" % (findings or "clean")
        else:
            ok = any(expect_finding in x for x in findings)
            detail = "expected finding ~%r in %s" % (expect_finding, findings)
        results.append(ok)
        print("%s %s (%s)" % ("PASS" if ok else "FAIL", name, detail))

    check("v1 valid manifest passes", None)
    check("v2 bad task status", "status 'doing' not in",
          lambda m: m["phases"][0]["tasks"][0].update(status="doing"))
    check("v3 bad tests.mode", "tests.mode 'yolo' not in",
          lambda m: m["phases"][0]["tasks"][0]["tests"].update(mode="yolo"))
    check("v4 duplicate id", "duplicate id: P0.1",
          lambda m: m["phases"][0]["tasks"].append(
              {"id": "P0.1", "title": "dup", "status": "pending"}))
    check("v5 dangling dependsOn", "dependsOn 'P9.9' does not resolve",
          lambda m: m["phases"][0]["tasks"][1].update(dependsOn=["P9.9"]))
    check("v6 dangling bugs[].taskId", "taskId 'P9.9' does not resolve",
          lambda m: m["bugs"][0].update(taskId="P9.9"))
    check("v7 dangling task.bugId", "bugId 'BUG-99' does not resolve",
          lambda m: m["phases"][0]["tasks"][1].update(bugId="BUG-99"))
    check("v8 malformed bug id", "id must match BUG-<number>",
          lambda m: (m["bugs"][0].update(id="bug_one"),
                     m["phases"][0]["tasks"][1].update(bugId="bug_one")))
    check("v9 bad bug status", "status 'zombie' not in",
          lambda m: m["bugs"][0].update(status="zombie"))
    check("v10 missing meta.version", "meta.version",
          lambda m: m["meta"].pop("version"))
    check("v11 dangling fileIndex ref", "fileIndex['src/a.ts']: task 'GONE'",
          lambda m: m.update(fileIndex={"src/a.ts": ["GONE"]}))
    check("v12 dangling phase blockedBy", "blockedBy 'PX' does not resolve",
          lambda m: m["phases"][0].update(blockedBy=["PX"]))

    # CLI path: valid file -> exit 0; garbage file -> exit 1
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_valid_manifest(), fh)
    ok = main([path]) == 0
    results.append(ok)
    print("%s c1 CLI accepts valid file" % ("PASS" if ok else "FAIL"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    ok = main([path]) == 1
    results.append(ok)
    print("%s c2 CLI rejects unparseable file" % ("PASS" if ok else "FAIL"))
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
