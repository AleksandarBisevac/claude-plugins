#!/usr/bin/env python3
"""
Structural validator for the audit manifest — dependency-free (stdlib only).

Complements the JSON Schema (schema/audit-plan.schema.json) with the referential
checks a schema cannot express: unique ids, resolvable blockedBy/dependsOn,
dependency CYCLES, fileIndex integrity in BOTH directions, and reciprocal
bugs[] <-> task.bugId cross-links. Commands run it after EVERY manifest
mutation (the Edit-and-revalidate rule in reference/manifest-conventions.md).

Output classes:
  FINDING  — structural defect; the manifest is INVALID (exit 1).
  WARNING  — suspicious but tolerated (unknown/typo'd keys, pre-0.3 status
             combinations); exit stays 0 when there are only warnings.

Usage:
  python3 validate-manifest.py <manifest-path>
  python3 validate-manifest.py --selftest

Exit codes: 0 = valid (warnings allowed) · 1 = findings · 2 = usage error or
unreadable/unparseable file.

The core `validate(manifest)` is pure and never raises on arbitrary JSON input —
shape surprises become findings, not tracebacks.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)

STATUS = ("pending", "in_progress", "blocked", "done")
TESTS_MODE = ("tdd", "regression", "gate-only")
RISK = ("low", "med", "high", None)
BUG_STATUS = ("open", "triaged", "in_progress", "fixed", "wontfix")
BUG_ID_RE = re.compile(r"^BUG-\d+$")

# Known keys per level. Unknown keys are WARNINGS (typo catcher), never findings
# — additionalProperties stays permissive for forward/backward compatibility.
# The "legacy" names below were removed from the schema in v0.3.0 but remain
# silently accepted in pre-0.3 manifests.
KNOWN_ROOT = {"$schema", "meta", "phases", "fileIndex", "bugs", "deferred",
              "proposals"}
KNOWN_META = {"version", "repo", "title", "createdISO", "node",
              "developmentBranch", "branchPrefix", "gitRoot", "reviewSkill",
              "runtimeBoot", "nodePreamble", "commit", "buildCommands", "ado",
              # report rendering (render-report.py): narrative summary box +
              # custom output-file basename. Neither affects orchestration.
              "reportSummary", "reportBasename",
              # token metering, read by the COMMANDS (the hooks read their own
              # copy from .claude/audit.config.json — the plugin's standing split):
              # ledgerDir, showCost, pricingAsOf, pricing.
              "usage",
              # tolerated (older /audit:init wrote these; informational):
              "notes", "baseCommit",
              # workspaceRoot: 0.2.0-era name for gitRoot; audit.md reads it as
              # a fallback when meta.gitRoot is absent.
              "workspaceRoot",
              # legacy (pre-0.3, ignored by the orchestrator):
              "signOffChecklist", "autoMode", "modelPolicy", "testPolicy",
              "reviewPolicy", "skillsPolicy", "statusLegend"}
KNOWN_PHASE = {"id", "title", "status", "model", "blockedBy", "docs",
               "description", "desiredOutcome", "testGate", "baseRef", "branch",
               "mergedAt", "review", "reviewFindings", "summary", "tasks",
               # v0.16: per-phase review skill override + app/team area tag
               "reviewSkill", "area",
               # v0.15 sharded layout: an index stub points at its shard file and
               # may carry an optimistic parallel-run claim (both surface on the
               # assembled phase via _manifest_io):
               "shard", "claim",
               # legacy (pre-0.3):
               "signOff"}
# Recommended keys on a parallel-run claim (soft — missing ones are warnings).
CLAIM_KEYS = ("sessionId", "host", "branch")
KNOWN_TASK = {"id", "title", "status", "model", "skills", "blockedBy",
              "dependsOn", "files", "docs", "description", "tests", "outcome",
              "commit", "attempts", "maxAttempts", "startedAt", "completedAt",
              "risk", "verifiedBy", "bugId", "ado",
              # tolerated (older /audit:init wrote this; informational):
              "details"}
KNOWN_BUG = {"id", "title", "status", "severity", "reportedAt", "reportedBy",
             "description", "repro", "expected", "actual", "files", "taskId",
             "fixedIn", "notes", "ado"}


def _check_claim(phase, pwhere, findings, warnings):
    """Validate an optional parallel-run `claim` on a phase (v0.15 sharded layout).

    A claim records which session/host/branch is running a phase so concurrent work
    across machines is coordinated (and a same-phase double-claim shows up as a shard
    merge conflict). Shape errors are findings; a claim missing recommended keys, or one
    left on a finished phase (stale — should be released), is a warning."""
    if "claim" not in phase:
        return
    claim = phase.get("claim")
    if claim is None:
        return
    if not isinstance(claim, dict):
        findings.append("%s: claim must be an object {sessionId, host, branch, at}, got %s"
                        % (pwhere, type(claim).__name__))
        return
    missing = [k for k in CLAIM_KEYS if not claim.get(k)]
    if missing:
        warnings.append("%s: claim is missing %s — a claim should identify the "
                        "session/host/branch holding the phase" % (pwhere, ", ".join(missing)))
    if phase.get("status") in ("done", "blocked"):
        warnings.append("%s: has a claim but status is %r — a finished/blocked phase should "
                        "release its claim (stale claim)" % (pwhere, phase.get("status")))


def _strip_line_suffix(entry):
    """`a/b.tsx:291-294,308` -> `a/b.tsx` (same rule as hooks/_config.py)."""
    return str(entry).replace("\\", "/").split(":", 1)[0]


def _safe_list(val):
    """A blockedBy/dependsOn/tasks value coerced to a list for safe iteration.
    A non-list (notably a bare string, which must NEVER be iterated
    per-character) becomes []. The wrong-type diagnostic is emitted by the
    caller — this only keeps `validate()` from raising on hostile shapes."""
    return val if isinstance(val, list) else []


def _require_fields(obj, where, findings):
    ok = True
    for key in ("id", "title", "status"):
        if not obj.get(key):
            findings.append("%s: missing required '%s'" % (where, key))
            ok = False
    return ok


def _check_ado(obj, where, findings):
    """`ado` (written by /audit:sync) must be null or {id: int, url, lastSyncedAt}."""
    if "ado" not in obj:
        return
    ado = obj.get("ado")
    if ado is None:
        return
    if not isinstance(ado, dict):
        findings.append("%s: ado must be an object or null, got %s"
                        % (where, type(ado).__name__))
        return
    if "id" in ado and not isinstance(ado.get("id"), int):
        findings.append("%s: ado.id must be an integer work-item id, got %r"
                        % (where, ado.get("id")))


def _unknown_keys(obj, known, where, warnings):
    """Warn on keys we do not recognize; case-insensitive 'did you mean'."""
    if not isinstance(obj, dict):
        return
    lower = {k.lower(): k for k in known}
    for k in obj:
        ks = str(k)
        # "_" = internal, "$" = JSON-Schema keywords, "//" = comment convention
        if ks in known or ks.startswith(("_", "$", "//")):
            continue
        hint = lower.get(ks.lower())
        if hint:
            warnings.append("%s: unknown key '%s' — did you mean '%s'?"
                            % (where, ks, hint))
        else:
            warnings.append("%s: unknown key '%s' (typo? unknown keys are "
                            "ignored by the orchestrator)" % (where, ks))


def _cycle_findings(phases, findings):
    """Detect dependency cycles over the waits-on graph.

    Edges: task -> its blockedBy/dependsOn targets; phase -> its blockedBy
    targets; phase -> each of its tasks (a phase is done only after its tasks),
    which catches the task-blockedBy-its-own-phase deadlock.
    """
    edges = {}

    def add_edge(a, b):
        if a and b:
            edges.setdefault(a, []).append(b)

    for phase in phases:
        if not isinstance(phase, dict):
            continue
        pid = phase.get("id")
        for ref in _safe_list(phase.get("blockedBy")):
            if isinstance(ref, str):
                add_edge(pid, ref)
        for task in _safe_list(phase.get("tasks")):
            if not isinstance(task, dict):
                continue
            tid = task.get("id")
            add_edge(pid, tid)
            for ref in _safe_list(task.get("blockedBy")):
                if isinstance(ref, str):
                    add_edge(tid, ref)
            for ref in _safe_list(task.get("dependsOn")):
                if isinstance(ref, str):
                    add_edge(tid, ref)

    WHITE, GRAY, BLACK = 0, 1, 2
    color, reported = {}, set()
    for start in list(edges):
        if color.get(start, WHITE) != WHITE:
            continue
        stack = [(start, iter(edges.get(start, ())))]
        color[start] = GRAY
        path = [start]
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                path.pop()
                color[node] = BLACK
                continue
            c = color.get(nxt, WHITE)
            if c == GRAY:
                i = path.index(nxt) if nxt in path else len(path) - 1
                cyc = path[i:] + [nxt]
                key = frozenset(cyc)
                if key not in reported:
                    reported.add(key)
                    findings.append(
                        "dependency cycle (blockedBy/dependsOn can never be "
                        "satisfied): %s" % " -> ".join(str(x) for x in cyc))
            elif c == WHITE:
                color[nxt] = GRAY
                stack.append((nxt, iter(edges.get(nxt, ()))))
                path.append(nxt)


def validate(manifest):
    """Return (findings, warnings) — two lists of strings; empty findings = valid."""
    f, w = [], []
    if not isinstance(manifest, dict):
        return (["manifest root must be a JSON object"], w)

    _unknown_keys(manifest, KNOWN_ROOT, "manifest root", w)

    meta = manifest.get("meta")
    if not isinstance(meta, dict):
        f.append("meta: missing or not an object")
    else:
        _unknown_keys(meta, KNOWN_META, "meta", w)
        version = meta.get("version")
        if not isinstance(version, int) or isinstance(version, bool):
            # bool is an int subclass in Python — `true` must NOT pass as a version.
            f.append("meta.version: missing or not an integer")

    phases = manifest.get("phases")
    if not isinstance(phases, list):
        f.append("phases: missing or not an array")
        phases = []

    phase_ids, task_ids = [], []
    task_bug_links = []       # (twhere, task_id, bugId)
    task_by_id = {}
    task_files = {}           # task_id -> files list

    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            f.append("phases[%d]: not an object" % pi)
            continue
        pid = phase.get("id")
        pwhere = "phase %s" % (pid or ("phases[%d]" % pi))
        _require_fields(phase, pwhere, f)
        _unknown_keys(phase, KNOWN_PHASE, pwhere, w)
        if pid:
            phase_ids.append(pid)
        if phase.get("status") not in STATUS:
            f.append("%s: status %r not in %s" % (pwhere, phase.get("status"), list(STATUS)))
        _check_claim(phase, pwhere, f, w)

        tasks_val = phase.get("tasks")
        if "tasks" not in phase:
            w.append("%s: no 'tasks' key — the schema requires one (an empty "
                     "phase should carry an empty list)" % pwhere)
        elif not isinstance(tasks_val, list):
            f.append("%s: tasks must be an array, got %s"
                     % (pwhere, type(tasks_val).__name__))
        # A phase is 'done' only after sign-off, which requires every task done.
        # A done phase with a non-done task is a stale-status slip the schema
        # can't express (e.g. a hand-regenerated roadmap that flipped the phase
        # but not its tasks).
        if phase.get("status") == "done":
            not_done = [t.get("id") or "?" for t in _safe_list(tasks_val)
                        if isinstance(t, dict) and t.get("status") != "done"]
            if not_done:
                f.append("%s: status 'done' but %d task(s) are not done (%s) — a "
                         "phase is done only after ALL its tasks are (sign-off)"
                         % (pwhere, len(not_done), ", ".join(not_done[:6])))
        for ti, task in enumerate(_safe_list(tasks_val)):
            if not isinstance(task, dict):
                f.append("%s tasks[%d]: not an object" % (pwhere, ti))
                continue
            tid = task.get("id")
            twhere = "task %s" % (tid or ("%s.tasks[%d]" % (pwhere, ti)))
            _require_fields(task, twhere, f)
            _unknown_keys(task, KNOWN_TASK, twhere, w)
            if tid:
                task_ids.append(tid)
                task_by_id[tid] = task
                files = task.get("files")
                if isinstance(files, list) and files:
                    task_files[tid] = files
            if task.get("status") not in STATUS:
                f.append("%s: status %r not in %s" % (twhere, task.get("status"), list(STATUS)))
            if (phase.get("status") == "pending"
                    and task.get("status") == "in_progress"):
                w.append("%s is in_progress but its %s is still 'pending' — "
                         "pre-0.3 manifest? /audit:resume expects the phase to "
                         "be 'in_progress' too" % (twhere, pwhere))
            tests = task.get("tests")
            if "tests" in task and tests is not None and not isinstance(tests, dict):
                f.append("%s: tests must be an object with a 'mode', got %s"
                         % (twhere, type(tests).__name__))
            if isinstance(tests, dict) and tests.get("mode") not in TESTS_MODE:
                f.append("%s: tests.mode %r not in %s" % (twhere, tests.get("mode"), list(TESTS_MODE)))
            if "risk" in task and task.get("risk") not in RISK:
                f.append("%s: risk %r not in %s" % (twhere, task.get("risk"), ["low", "med", "high", None]))
            _check_ado(task, twhere, f)
            if task.get("bugId"):
                task_bug_links.append((twhere, tid, task["bugId"]))

    # -- unique ids across phases + tasks + bugs -------------------------------
    bugs = manifest.get("bugs")
    bug_list = bugs if isinstance(bugs, list) else []
    bug_ids = [b.get("id") for b in bug_list if isinstance(b, dict) and b.get("id")]
    bug_by_id = {b["id"]: b for b in bug_list
                 if isinstance(b, dict) and b.get("id")}

    all_ids = phase_ids + task_ids + bug_ids
    seen = set()
    for i in all_ids:
        if i in seen:
            f.append("duplicate id: %s" % i)
        seen.add(i)

    known = set(phase_ids) | set(task_ids)

    # -- blockedBy / dependsOn resolve + cycles ---------------------------------
    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        pwhere = "phase %s" % (phase.get("id") or ("phases[%d]" % pi))

        def _check_refs(refs_val, where, field, universe, kind):
            """Report a non-array value, a non-string entry (which would crash
            the set-membership test), or an unresolved id — never raise."""
            if refs_val is not None and not isinstance(refs_val, list):
                f.append("%s: %s must be an array, got %s"
                         % (where, field, type(refs_val).__name__))
            for ref in _safe_list(refs_val):
                if not isinstance(ref, str):
                    f.append("%s: %s entry must be a string id, got %r"
                             % (where, field, ref))
                elif ref not in universe:
                    f.append("%s: %s '%s' does not resolve to %s"
                             % (where, field, ref, kind))

        _check_refs(phase.get("blockedBy"), pwhere, "blockedBy", known,
                    "any task/phase")
        for ti, task in enumerate(_safe_list(phase.get("tasks"))):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or ("%s.tasks[%d]" % (pwhere, ti)))
            _check_refs(task.get("blockedBy"), twhere, "blockedBy", known,
                        "any task/phase")
            _check_refs(task.get("dependsOn"), twhere, "dependsOn", task_ids,
                        "a task")

    _cycle_findings(phases, f)

    # -- fileIndex integrity (both directions) -----------------------------------
    file_index = manifest.get("fileIndex")
    if isinstance(file_index, dict):
        stripped_index = {}
        for fpath, refs in file_index.items():
            key = _strip_line_suffix(fpath)
            bucket = stripped_index.setdefault(key, set())
            if not isinstance(refs, list):
                f.append("fileIndex['%s']: value must be an array of task ids, "
                         "got %s" % (fpath, type(refs).__name__))
                continue
            for ref in refs:
                if isinstance(ref, str):
                    bucket.add(ref)  # only hashable str ids enter the set
                if ref not in task_ids:
                    f.append("fileIndex['%s']: task '%s' does not exist" % (fpath, ref))
        for tid, files in task_files.items():
            for fentry in files:
                key = _strip_line_suffix(fentry)
                if tid not in stripped_index.get(key, set()):
                    f.append("task %s: file '%s' missing from fileIndex "
                             "(fileIndex['%s'] must include '%s')"
                             % (tid, fentry, key, tid))

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
        _unknown_keys(bug, KNOWN_BUG, bwhere, w)
        if bid and not BUG_ID_RE.match(str(bid)):
            f.append("%s: id must match BUG-<number>" % bwhere)
        if bug.get("status") not in BUG_STATUS:
            f.append("%s: status %r not in %s" % (bwhere, bug.get("status"), list(BUG_STATUS)))
        _check_ado(bug, bwhere, f)
        if bug.get("taskId"):
            if bug["taskId"] not in task_ids:
                f.append("%s: taskId '%s' does not resolve to a task" % (bwhere, bug["taskId"]))
            else:
                linked = task_by_id.get(bug["taskId"]) or {}
                if linked.get("bugId") != bid:
                    f.append("%s: taskId '%s' but that task's bugId is %r — "
                             "link must be reciprocal"
                             % (bwhere, bug["taskId"], linked.get("bugId")))

    for twhere, tid, bug_ref in task_bug_links:
        if bug_ref not in bug_ids:
            f.append("%s: bugId '%s' does not resolve to a bug" % (twhere, bug_ref))
        else:
            linked = bug_by_id.get(bug_ref) or {}
            if linked.get("taskId") != tid:
                f.append("%s: bugId '%s' but that bug's taskId is %r — "
                         "link must be reciprocal"
                         % (twhere, bug_ref, linked.get("taskId")))

    return (f, w)


def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: validate-manifest.py <manifest-path>\n")
        return 2
    try:
        manifest = _mio.load_manifest(argv[0])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (argv[0], exc))
        return 2

    try:
        findings, warnings = validate(manifest)
    except Exception as exc:  # defensive; validate() should never raise
        print("FINDING: internal validator error: %s" % exc)
        return 1

    for line in warnings:
        print("WARNING: " + line)

    if findings:
        for line in findings:
            print("FINDING: " + line)
        print("\nINVALID: %d finding(s) in %s" % (len(findings), argv[0]))
        return 1

    n_tasks = sum(len(p.get("tasks") or []) for p in manifest.get("phases", []) if isinstance(p, dict))
    print("OK: %s valid (%d phases, %d tasks, %d bugs%s)"
          % (argv[0], len(manifest.get("phases", [])), n_tasks,
             len(manifest.get("bugs") or []),
             ", %d warning(s)" % len(warnings) if warnings else ""))
    return 0


# --- selftest -------------------------------------------------------------------
def _valid_manifest():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P0", "title": "Phase", "status": "pending", "tasks": [
                {"id": "P0.1", "title": "Task", "status": "pending",
                 "tests": {"mode": "regression"}, "risk": "low",
                 "files": ["src/a.ts"],
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

    def check(name, expect_finding, mutate=None, *, expect_warning=None):
        m = copy.deepcopy(_valid_manifest())
        if mutate:
            mutate(m)
        findings, warnings = validate(m)
        if expect_finding is None:
            ok = findings == []
            detail = "expected clean, got %s" % (findings or "clean")
        else:
            ok = any(expect_finding in x for x in findings)
            detail = "expected finding ~%r in %s" % (expect_finding, findings)
        if ok and expect_warning is not None:
            ok = any(expect_warning in x for x in warnings)
            detail = "expected warning ~%r in %s" % (expect_warning, warnings)
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
          lambda m: m.update(fileIndex={"src/a.ts": ["GONE", "P0.1"]}))
    check("v12 dangling phase blockedBy", "blockedBy 'PX' does not resolve",
          lambda m: m["phases"][0].update(blockedBy=["PX"]))

    # --- new in 0.3.0: cycles ---
    check("c1 two-task dependsOn cycle", "dependency cycle",
          lambda m: (m["phases"][0]["tasks"][0].update(dependsOn=["P0.2"]),
                     m["phases"][0]["tasks"][1].update(dependsOn=["P0.1"])))
    check("c2 self-loop", "dependency cycle",
          lambda m: m["phases"][0]["tasks"][0].update(dependsOn=["P0.1"]))
    check("c3 task blockedBy its own phase", "dependency cycle",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy=["P0"]))
    check("c4 acyclic chain stays clean", None,
          lambda m: m["phases"][0]["tasks"][1].update(blockedBy=["P0.1"]))

    # --- new in 0.3.0: reciprocity ---
    check("r1 bug->task without task->bug", "link must be reciprocal",
          lambda m: m["phases"][0]["tasks"][1].pop("bugId"))
    check("r2 task->bug without bug->task", "link must be reciprocal",
          lambda m: m["bugs"][0].update(taskId=None))

    # --- new in 0.3.0: fileIndex bidirectional ---
    check("f1 task file missing from fileIndex", "missing from fileIndex",
          lambda m: m["phases"][0]["tasks"][0].update(files=["src/other.ts"]))
    check("f2 line-suffix entries match stripped", None,
          lambda m: m["phases"][0]["tasks"][0].update(files=["src/a.ts:10-20"]))

    # --- new in 0.3.0: tests must be an object ---
    check("t1 tests as string is a finding", "tests must be an object",
          lambda m: m["phases"][0]["tasks"][0].update(tests="tdd"))

    # --- new in 0.5.0: ado link shape ---
    check("a1 valid ado link stays clean", None,
          lambda m: m["phases"][0]["tasks"][0].update(
              ado={"id": 1234, "url": "https://dev.azure.com/o/p/_workitems/edit/1234",
                   "lastSyncedAt": "2026-07-07T00:00:00Z"}))
    check("a2 ado as string is a finding", "ado must be an object",
          lambda m: m["bugs"][0].update(ado="WI-1234"))
    check("a3 non-integer ado.id is a finding", "ado.id must be an integer",
          lambda m: m["phases"][0]["tasks"][0].update(ado={"id": "1234"}))
    check("a4 null ado stays clean", None,
          lambda m: m["bugs"][0].update(ado=None))

    # --- new in 0.3.0: warnings ---
    check("w1 unknown key warns with did-you-mean", None,
          lambda m: m["phases"][0]["tasks"][0].update(dependson=["P0.2"]),
          expect_warning="did you mean 'dependsOn'")
    check("w2 unknown key warns", None,
          lambda m: m["meta"].update(frobnicate=True),
          expect_warning="unknown key 'frobnicate'")
    check("w3 legacy meta keys stay silent", None,
          lambda m: m["meta"].update(signOffChecklist=["x"], statusLegend=["y"]))

    # w5: the 0.5.1/0.6.1-known keys must produce NEITHER findings NOR warnings
    m5 = copy.deepcopy(_valid_manifest())
    m5["meta"].update(gitRoot="test", notes="n")
    m5["phases"][0].update(description="d")
    m5["phases"][0]["tasks"][0].update(details="dt")
    f5, w5warn = validate(m5)
    noise = [x for x in w5warn if any(k in x for k in
             ("gitRoot", "description", "details", "notes"))]
    ok = f5 == [] and noise == []
    results.append(ok)
    print("%s w5 gitRoot/description/details/notes -> no findings, no warnings (%s)"
          % ("PASS" if ok else "FAIL", "clean" if ok else (f5 or noise)))
    check("w4 in_progress task in pending phase warns", None,
          lambda m: m["phases"][0]["tasks"][0].update(status="in_progress"),
          expect_warning="still 'pending'")

    # claim (v0.15 sharded parallel-run coordination)
    check("cl1 valid claim on an active phase stays clean", None,
          lambda m: m["phases"][0].update(
              claim={"sessionId": "s1", "host": "h1", "branch": "audit/p0", "at": "t"}))
    check("cl2 claim not an object is a finding", "claim must be an object",
          lambda m: m["phases"][0].update(claim="whoever"))
    check("cl3 claim missing keys warns", None,
          lambda m: m["phases"][0].update(claim={"at": "t"}),
          expect_warning="claim is missing")
    check("cl4 claim on a done phase warns (stale)", None,
          lambda m: (m["phases"][0].update(
              status="done", claim={"sessionId": "s", "host": "h", "branch": "b"}),
              [t.update(status="done") for t in m["phases"][0]["tasks"]]),
          expect_warning="stale claim")

    # v0.16 — per-phase reviewSkill override + area tag are known keys (no noise)
    m6 = copy.deepcopy(_valid_manifest())
    m6["phases"][0].update(reviewSkill="backend-review", area="backend")
    f6, w6 = validate(m6)
    noise6 = [x for x in w6 if "reviewSkill" in x or "area" in x]
    ok6 = f6 == [] and noise6 == []
    results.append(ok6)
    print("%s pp1 per-phase reviewSkill+area: no finding, no unknown-key warning (%s)"
          % ("PASS" if ok6 else "FAIL", "clean" if ok6 else (f6 or noise6)))

    # --- robustness: validate() must NEVER raise on hostile shapes, and the
    #     wrong-type diagnostics must be actionable (regression guard for the
    #     "never raises on arbitrary JSON" contract + schema drift) ---
    check("z1 blockedBy as a bare string is a finding (no per-char iteration)",
          "blockedBy must be an array",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy="P0"))
    check("z2 unhashable blockedBy entry reported, does not crash",
          "must be a string id",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy=[["x"]]))
    check("z3 unhashable dependsOn entry reported, does not crash",
          "must be a string id",
          lambda m: m["phases"][0]["tasks"][1].update(dependsOn=[{"k": "v"}]))
    check("z4 non-array fileIndex value is a finding",
          "must be an array of task ids",
          lambda m: m.update(fileIndex={"src/a.ts": "P0.1"}))
    check("z5 non-array tasks is a finding",
          "tasks must be an array",
          lambda m: m["phases"][0].update(tasks="P0.1"))
    check("z6 boolean version rejected (bool is not a valid int version)",
          "meta.version",
          lambda m: m["meta"].update(version=True))
    # removing tasks orphans fileIndex/bug links, so clear those too and assert
    # the bare "no tasks" case is a WARNING, not a hard finding
    check("z7 absent tasks warns but is not a hard finding", None,
          lambda m: (m.pop("fileIndex", None), m.pop("bugs", None),
                     m["phases"][0].pop("tasks", None)),
          expect_warning="no 'tasks' key")
    check("z8 done phase with a non-done task is a finding",
          "status 'done' but",
          lambda m: m["phases"][0].update(status="done"))

    # --- CLI exit codes: 0 valid · 1 findings · 2 usage/unreadable ---
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_valid_manifest(), fh)
    ok = main([path]) == 0
    results.append(ok)
    print("%s c5 CLI accepts valid file (exit 0)" % ("PASS" if ok else "FAIL"))
    bad = copy.deepcopy(_valid_manifest())
    bad["phases"][0]["tasks"][0]["status"] = "doing"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(bad, fh)
    ok = main([path]) == 1
    results.append(ok)
    print("%s c6 CLI reports findings (exit 1)" % ("PASS" if ok else "FAIL"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    ok = main([path]) == 2
    results.append(ok)
    print("%s c7 CLI rejects unparseable file (exit 2)" % ("PASS" if ok else "FAIL"))
    ok = main([]) == 2
    results.append(ok)
    print("%s c8 CLI usage error (exit 2)" % ("PASS" if ok else "FAIL"))
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
