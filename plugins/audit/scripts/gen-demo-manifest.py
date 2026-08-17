#!/usr/bin/env python3
"""
Synthetic LARGE audit manifest for demos, screenshots and CI — stdlib only.

Two of this repo's most visible artifacts were built from a manifest that was never
committed: `docs/demo-large.html` (the "big audit" scale demo) and the six
`docs/screenshots/panel-*.png`, which exist to back the claim that the composition
table stays usable at 50 phases x 20 tasks. Neither could be regenerated, so both
drifted — the panel shots still show three tabs against a UI that has four.

This generates that fixture on demand instead of storing it. Nothing it writes needs
committing: the same flags always produce the same bytes, so CI can build the
fixture, capture from it, and throw it away.

    gen-demo-manifest.py <out-dir> [--phases 50] [--tasks 20] [--seed 11]
                                   [--single-file] [--selftest]

WHAT IT DELIBERATELY CONTAINS. A fixture that only holds healthy rows exercises
none of the surfaces that matter, so this one carries every state a reader can
filter on: all four phase statuses and all four task statuses, a phase gated behind
another (`blockedBy`), cross-task `dependsOn`, budgets both under and over, `area`
tags so the monorepo grouping has something to group, tasks with and without
`skills` so the panel's "needs skills" filter has both sides, and a full bug
lifecycle including a reciprocal bug<->task link.

DETERMINISTIC BY CONSTRUCTION. A fixed seed, a fixed base date, no wall-clock. The
validator's rules are respected by construction rather than by luck — in
particular a `done` phase never contains an unfinished task, which is the
constraint that makes naive random status assignment produce an invalid manifest.
`plugins/audit/tests/test_gen_demo_manifest.py` pins determinism, referential
integrity and that constraint - this file carries no inline `--selftest` any
more, and its 42 cases live there with byte-identical labels.
"""
import argparse
import datetime
import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)

# --- demo vocab -----------------------------------------------------------------
# No wall-clock anywhere: every timestamp is derived from this.
BASE = datetime.datetime(2026, 4, 1, 9, 0, 0)

AREAS = ("backend", "web", "mobile", "infra")
RISKS = ("low", "med", "high")
# Mirrors the example manifest: haiku for low risk, sonnet for med, opus for high.
# The audit's own rule forbids haiku for `risk: high` — respected by construction.
RISK_MODEL = {"low": "haiku", "med": "sonnet", "high": "opus"}
TEST_MODES = ("tdd", "regression", "gate-only")

SKILL_POOL = ("clean-typescript", "pragmatic-testing", "web-security",
              "safe-incremental-refactor", "structured-code-review")

TITLE_VERBS = ("Harden", "Validate", "Escape", "Memoize", "Rate-limit", "Deduplicate",
               "Normalize", "Cache", "Instrument", "Guard", "Simplify", "Backfill")
TITLE_NOUNS = ("the checkout payload", "the session cookie", "the product query",
               "the catalog selector", "the auth middleware", "the price rounding",
               "the image pipeline", "the retry policy", "the audit log",
               "the feature flags", "the webhook handler", "the search index")


# --- generation -----------------------------------------------------------------
def _load_manifest_io():
    return _loader.load_script("_manifest_io.py", modname="_manifest_io")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(rng):
    return "".join(rng.choice("0123456789abcdef") for _ in range(7))


def _phase_plan(n_phases):
    """Assign a status to each phase so the mix is representative AND valid.

    Ordering is load-bearing. `done` phases come first because the validator
    rejects a done phase holding an unfinished task, and a reader scanning the
    composition table expects finished work above live work. Exactly one phase is
    `in_progress` — that is what the runtime permits and what makes the "resumable"
    line in `/audit:status` meaningful.
    """
    if n_phases < 4:                       # keep all four states representable
        return (["done"] * max(0, n_phases - 3)
                + ["in_progress", "blocked", "pending"][:n_phases])
    n_done = max(1, int(n_phases * 0.35))
    n_blocked = max(1, int(n_phases * 0.08))
    plan = ["done"] * n_done + ["in_progress"]
    plan += ["blocked"] * n_blocked
    plan += ["pending"] * (n_phases - len(plan))
    return plan[:n_phases]


def _task_statuses(phase_status, n_tasks, rng):
    """Task statuses consistent with the phase's own status."""
    if phase_status == "done":
        return ["done"] * n_tasks
    if phase_status == "in_progress":
        # A live phase mid-flight: some finished, one running, one stuck, rest queued.
        out = ["done"] * max(1, n_tasks // 3)
        if len(out) < n_tasks:
            out.append("in_progress")
        if len(out) < n_tasks:
            out.append("blocked")
        return (out + ["pending"] * (n_tasks - len(out)))[:n_tasks]
    return ["pending"] * n_tasks           # blocked + pending phases: nothing started


def _demo_areas():
    """The `meta.areas` registry, advisory owners included (v0.34).

    The owner identities are gen-demo-usage.py's own DEFAULT_AUTHORS, loaded from
    that script rather than restated here — an owner the ledger has never seen is
    exactly the mismatch /audit:doctor warns about, and this fixture exists to
    show the join working. `infra` stays ownerless on purpose: the no-owner case
    must render too. Every entry carries a root because the validator warns on a
    rootless area and the selftest holds the fixture to zero warnings.
    """
    authors = _loader.load_script("gen-demo-usage.py",
                                  modname="gen_demo_usage").DEFAULT_AUTHORS
    blurb = {"backend": "Service and API passes",
             "web": "Storefront web passes",
             "mobile": "Mobile app passes",
             "infra": "Build and deploy passes"}
    out = {}
    for i, tag in enumerate(AREAS):
        entry = {"root": "src/%s" % tag, "description": blurb[tag],
                 # v0.37 B1/B2: every area declares a house default, so every
                 # task RESOLVES to something (area-first merge on show in the
                 # panel) and the unresolved-skills advisory has nothing to say
                 # about a fixture that is supposed to validate silently.
                 "skills": [SKILL_POOL[i % len(SKILL_POOL)]]}
        if tag != "infra":
            entry["owner"] = authors[i % len(authors)]
        out[tag] = entry
    return out


def generate(n_phases=50, n_tasks=20, seed=11, repo="demo"):
    """Build an ASSEMBLED manifest dict (the sharded split happens on write)."""
    rng = random.Random(seed)
    statuses = _phase_plan(n_phases)
    phases, file_index, cursor = [], {}, BASE

    for pi, pstatus in enumerate(statuses, start=1):
        pid = "P%d" % pi
        area = AREAS[(pi - 1) % len(AREAS)]
        p_start = cursor
        cursor += datetime.timedelta(days=3)

        tasks = []
        for ti, tstatus in enumerate(_task_statuses(pstatus, n_tasks, rng), start=1):
            tid = "%s.%d" % (pid, ti)
            risk = RISKS[rng.randrange(len(RISKS))]
            started = p_start + datetime.timedelta(hours=4 * (ti - 1))
            rel = "src/%s/mod%02d_%02d.ts" % (area, pi, ti)
            task = {
                "id": tid,
                "title": "%s %s" % (TITLE_VERBS[(pi + ti) % len(TITLE_VERBS)],
                                    TITLE_NOUNS[(pi * 3 + ti) % len(TITLE_NOUNS)]),
                "status": tstatus,
                "model": RISK_MODEL[risk],
                "risk": risk,
                "files": [rel],
                "tests": {
                    "mode": TEST_MODES[(pi + ti) % len(TEST_MODES)],
                    "gate": ["yarn test --findRelatedTests %s" % rel],
                },
                "attempts": 0,
                "maxAttempts": 3,
            }
            # Only some tasks carry skills, so the panel's "needs skills" filter has
            # both sides to show. Exactly ONE task (P1.1) is explicitly opted
            # out (v0.37 B1): `skills: null` is the answer "none applies" that
            # also stops the area default, and the demo shows all three states.
            if pi == 1 and ti == 1:
                task["skills"] = None
            elif (pi + ti) % 3 == 0:
                task["skills"] = [SKILL_POOL[(pi + ti) % len(SKILL_POOL)]]
            # A within-phase dependency chain, so the readiness rule has real work.
            if ti > 1 and (pi + ti) % 5 == 0:
                task["dependsOn"] = ["%s.%d" % (pid, ti - 1)]

            if tstatus in ("done", "in_progress", "blocked"):
                task["startedAt"] = _iso(started)
                task["attempts"] = 1 if tstatus != "blocked" else 3
            if tstatus == "done":
                task["completedAt"] = _iso(started + datetime.timedelta(hours=3))
                task["commit"] = _sha(rng)
                task["verifiedBy"] = ["tests"]
                task["outcome"] = {
                    "technical": "Reworked %s and covered it with a regression test." % rel,
                    "descriptive": "The behaviour is now checked automatically.",
                }
            if tstatus == "blocked":
                task["outcome"] = {
                    "technical": "Gate red after 3 attempts; needs a human decision.",
                    "descriptive": "Left for review — the fix touches shared code.",
                }
            tasks.append(task)
            file_index.setdefault(rel, []).append(tid)

        phase = {
            "id": pid,
            "title": "%s pass %d" % (area.capitalize(), pi),
            "status": pstatus,
            "area": area,
            "desiredOutcome": (
                "Everything under src/%s that this phase touches is validated and "
                "covered by a test that would fail without the fix." % area),
            "testGate": ["yarn test --selectProjects %s" % area],
            "tasks": tasks,
        }
        # Budgets on a slice of phases only — an unbudgeted phase must render as
        # "no budget", never as a phase at zero, and the report needs both cases.
        if pi % 4 == 1:
            spendy = pstatus == "done" and pi % 8 == 1
            phase["budgetUSD"] = 18.0 if spendy else 60.0   # the 18.0 ones run over
        if pstatus == "done":
            phase["baseRef"] = _sha(rng)
            phase["branch"] = "audit/%s-%s" % (pid.lower(), area)
            phase["mergedAt"] = _iso(p_start + datetime.timedelta(days=2))
            phase["summary"] = (
                "Met the desired outcome: every touched file under src/%s is "
                "validated and the phase gate is green." % area)
            phase["review"] = {"status": "passed",
                               "outcome": "No actionable findings on the phase diff."}
        elif pstatus == "in_progress":
            phase["baseRef"] = _sha(rng)
            phase["branch"] = "audit/%s-%s" % (pid.lower(), area)
        elif pstatus == "blocked":
            phase["blockedBy"] = ["P%d" % max(1, pi - 1)]
        phases.append(phase)

    # Connector v2 (meta.ado): a linked phase and task, so the panel's ADO card
    # renders its 'linked' banner from EVIDENCE (links sync would have written)
    # and the browser check can assert it. Deterministic values on purpose —
    # the demo is regenerated, never stored.
    phases[0]["ado"] = {
        "id": 4700,
        "url": "https://dev.azure.com/demo-org/%s/_workitems/edit/4700" % repo,
        "lastSyncedAt": "2026-08-06T12:00:00Z"}
    phases[0]["tasks"][0]["ado"] = {
        "id": 4711,
        "url": "https://dev.azure.com/demo-org/%s/_workitems/edit/4711" % repo,
        "lastSyncedAt": "2026-08-06T12:05:00Z"}

    manifest = {
        "meta": {
            "version": 3,
            "repo": repo,
            "title": "%s — %d-phase scale audit" % (repo, n_phases),
            "createdISO": _iso(BASE),
            "developmentBranch": "main",
            "branchPrefix": "audit",
            "gitRoot": ".",
            "reportBasename": "demo-large",
            "reportSummary": (
                "A synthetic manifest at %d phases x %d tasks, generated to show that "
                "the report and the control panel stay legible at scale. Every phase "
                "and task status is represented, along with budgets, area tags, a "
                "gated phase and a full bug lifecycle."
                % (n_phases, n_tasks)),
            "buildCommands": {"test": "yarn test", "lint": "yarn lint",
                              "build": "yarn build"},
            # Declared, like the acme example declares it. Without it the demo
            # rendered real dollar figures and, since the renderer refuses to
            # invent a rate date, correctly labelled them "rates undated" — an
            # honest report of a badly-formed manifest, on the page that exists
            # to show what a well-formed one looks like. The fixture was the
            # defect there, not the renderer.
            "usage": {"ledgerDir": ".claude/usage", "showCost": True,
                      "pricingAsOf": "2026-08-06"},
            "areas": _demo_areas(),
            # Connector v2: configured so the ADO card has a form to show; the
            # links above make its banner read 'linked' rather than 'unverified'.
            "ado": {"organization": "demo-org", "project": repo,
                    "areaPath": None, "iterationPath": None,
                    "types": {"bug": "Bug", "task": "Task"},
                    "identityMap": {"dev@demo.example":
                                    "dev@demo-corp.example.com"}},
        },
        "phases": phases,
        "fileIndex": file_index,
        "bugs": _bugs(phases),
        "proposals": [],
    }
    return manifest


# --- bugs + output --------------------------------------------------------------
def _bugs(phases):
    """A full bug lifecycle, including one reciprocal bug<->task link.

    The link has to be reciprocal in both directions or the validator rejects it,
    and the linked task has to be a real id — which is why this runs after the
    phases exist rather than generating ids it hopes will be there.
    """
    linked = None
    for ph in phases:
        if ph.get("status") == "in_progress":
            for t in ph["tasks"]:
                if t["status"] == "in_progress":
                    linked = t
                    break
            break
    bugs = [
        {"id": "BUG-1", "title": "Product images 404 intermittently on Safari",
         "status": "open", "severity": "med",
         "reportedAt": _iso(BASE + datetime.timedelta(days=5)),
         "description": "Some catalog images fail to load on first paint in Safari.",
         "repro": "Open the catalog in Safari with an empty cache.",
         "expected": "Every image loads.", "actual": "Two or three 404 briefly."},
        {"id": "BUG-2", "title": "Checkout is slow on 3G mobile",
         "status": "triaged", "severity": "low",
         "reportedAt": _iso(BASE + datetime.timedelta(days=7)),
         "description": "Checkout takes over ten seconds on a throttled connection."},
        {"id": "BUG-4", "title": "Dark-mode label contrast below AA",
         "status": "wontfix", "severity": "low",
         "reportedAt": _iso(BASE + datetime.timedelta(days=11)),
         "notes": "Superseded by the design-token refresh; tracked there instead."},
    ]
    if linked is not None:
        bugs.insert(2, {
            "id": "BUG-3",
            "title": "Cart total off by one with stacked discounts",
            "status": "in_progress", "severity": "high",
            "reportedAt": _iso(BASE + datetime.timedelta(days=9)),
            "description": "Two stacked percentage discounts round the wrong way.",
            "repro": "Apply a 10% and a 5% discount to a 19.99 item.",
            "expected": "17.09", "actual": "17.10",
            "taskId": linked["id"],
        })
        linked["bugId"] = "BUG-3"
    return bugs


def write_config(out_dir):
    """Write `.claude/audit.config.json` pointing at the manifest we just wrote.

    Without this the fixture is unusable by the very surfaces it exists to
    photograph: `manifestPath` defaults to `docs/audit/audit-plan.json`, so the
    control panel opened on this directory reports "No manifest — run /audit:init"
    and the Overview tab renders its empty state. The committed acme example carries
    the same file for the same reason.
    """
    cfg_dir = os.path.join(out_dir, ".claude")
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, "audit.config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"manifestPath": "audit-plan.json"}, fh, indent=2)
        fh.write("\n")
    return path


def write_manifest(manifest, out_dir, single_file=False):
    mio = _load_manifest_io()
    os.makedirs(out_dir, exist_ok=True)
    index_path = os.path.join(out_dir, "audit-plan.json")
    if single_file:
        flat = dict(manifest)
        flat["meta"] = dict(manifest["meta"])
        flat["meta"]["version"] = 2
        with open(index_path, "w", encoding="utf-8") as fh:
            json.dump(flat, fh, indent=2, sort_keys=False)
            fh.write("\n")
        written = [index_path]
    else:
        written = mio.save_sharded(index_path, manifest)
    written.append(write_config(out_dir))
    return written


# --- cli ------------------------------------------------------------------------
def main(argv):
    ap = argparse.ArgumentParser(
        prog="gen-demo-manifest.py",
        description="Generate a deterministic large audit manifest for demos and screenshots.")
    ap.add_argument("out_dir")
    ap.add_argument("--phases", type=int, default=50)
    ap.add_argument("--tasks", type=int, default=20)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--repo", default="demo")
    ap.add_argument("--single-file", action="store_true",
                    help="write one file (meta.version 2) instead of index + shards")
    args = ap.parse_args(argv)

    if args.phases < 1 or args.tasks < 1:
        sys.stderr.write("ERROR: --phases and --tasks must be >= 1\n")
        return 2

    manifest = generate(n_phases=args.phases, n_tasks=args.tasks,
                        seed=args.seed, repo=args.repo)
    written = write_manifest(manifest, args.out_dir, single_file=args.single_file)
    n_tasks = sum(len(p["tasks"]) for p in manifest["phases"])
    print("wrote %d phase(s), %d task(s), %d bug(s) to %s"
          % (len(manifest["phases"]), n_tasks, len(manifest["bugs"]), args.out_dir))
    print("  %s" % written[-1])
    if len(written) > 1:
        print("  + %d shard(s)" % (len(written) - 1))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to main(), which would treat the
        # flag as an out-dir. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("gen-demo-manifest.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_gen_demo_manifest.py - run that file "
              "instead.")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
