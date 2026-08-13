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
`--selftest` pins determinism, referential integrity and that constraint.
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
        entry = {"root": "src/%s" % tag, "description": blurb[tag]}
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
            # both sides to show.
            if (pi + ti) % 3 == 0:
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


# --- selftest -------------------------------------------------------------------
def _selftest():
    import shutil
    import tempfile
    cases = []

    def check(label, ok, detail=""):
        cases.append((label, bool(ok), detail))

    m = generate(n_phases=12, n_tasks=6, seed=11)

    # determinism
    a = json.dumps(generate(n_phases=9, n_tasks=4, seed=11), sort_keys=True)
    b = json.dumps(generate(n_phases=9, n_tasks=4, seed=11), sort_keys=True)
    check("deterministic: two runs are byte-identical", a == b)
    check("seed changes the output",
          a != json.dumps(generate(n_phases=9, n_tasks=4, seed=12), sort_keys=True))

    # shape
    check("phase count honoured", len(m["phases"]) == 12)
    check("task count honoured", all(len(p["tasks"]) == 6 for p in m["phases"]))
    ids = [p["id"] for p in m["phases"]]
    check("phase ids unique", len(ids) == len(set(ids)))
    tids = [t["id"] for p in m["phases"] for t in p["tasks"]]
    check("task ids unique", len(tids) == len(set(tids)))

    # every status represented — the whole point of the fixture
    pst = {p["status"] for p in m["phases"]}
    check("all four phase statuses present",
          pst == {"done", "in_progress", "blocked", "pending"}, sorted(pst))
    tst = {t["status"] for p in m["phases"] for t in p["tasks"]}
    check("all four task statuses present",
          tst == {"done", "in_progress", "blocked", "pending"}, sorted(tst))
    check("exactly one in_progress phase",
          sum(1 for p in m["phases"] if p["status"] == "in_progress") == 1)

    # the constraint naive randomisation gets wrong
    bad = [p["id"] for p in m["phases"] if p["status"] == "done"
           and any(t["status"] != "done" for t in p["tasks"])]
    check("no done phase holds an unfinished task", not bad, bad)

    # done tasks carry the evidence the report renders
    done = [t for p in m["phases"] for t in p["tasks"] if t["status"] == "done"]
    check("done tasks have commit + completedAt",
          all(t.get("commit") and t.get("completedAt") for t in done))
    check("done tasks have a startedAt for the ledger generator to fill",
          all(t.get("startedAt") for t in done))

    # referential integrity
    fi = m["fileIndex"]
    check("fileIndex is bidirectional",
          all(t["id"] in fi.get(t["files"][0], [])
              for p in m["phases"] for t in p["tasks"]))
    linked = [b for b in m["bugs"] if b.get("taskId")]
    check("a reciprocal bug<->task link exists", len(linked) == 1)
    if linked:
        tid = linked[0]["taskId"]
        back = [t for p in m["phases"] for t in p["tasks"]
                if t["id"] == tid and t.get("bugId") == linked[0]["id"]]
        check("the linked task points back at the bug", len(back) == 1)
    bst = {b["status"] for b in m["bugs"]}
    check("bug lifecycle covers open/triaged/in_progress/wontfix",
          bst == {"open", "triaged", "in_progress", "wontfix"}, sorted(bst))

    # surfaces that need both states
    check("some tasks have skills and some do not",
          any("skills" in t for p in m["phases"] for t in p["tasks"])
          and any("skills" not in t for p in m["phases"] for t in p["tasks"]))
    budgets = [p.get("budgetUSD") for p in m["phases"] if p.get("budgetUSD")]
    check("some phases carry a budget and some do not",
          budgets and len(budgets) < len(m["phases"]))
    check("every budget is a positive number",
          all(isinstance(b, (int, float)) and not isinstance(b, bool) and b > 0
              for b in budgets))
    check("a phase is gated behind another",
          any(p.get("blockedBy") for p in m["phases"]))
    check("area tags present", all(p.get("area") for p in m["phases"]))
    # v0.34: the registry, with advisory owners. Owners are gen-demo-usage.py's
    # own ledger authors — read from that script, never restated — so the panel's
    # person header shows a real "owns:" line and doctor's owner-vs-ledger join
    # has a true match. One area stays ownerless: the no-owner case must render.
    used_tags = {p["area"] for p in m["phases"]}
    reg = m["meta"].get("areas") or {}
    ledger_authors = set(_loader.load_script(
        "gen-demo-usage.py", modname="gen_demo_usage").DEFAULT_AUTHORS)
    reg_owners = {k: v.get("owner") for k, v in reg.items() if "owner" in v}
    check("meta.areas registers every tag the phases use",
          used_tags <= set(reg), sorted(used_tags - set(reg)))
    check("advisory owners are the ledger's own authors, on some areas "
          "but not all",
          bool(reg_owners) and set(reg_owners.values()) <= ledger_authors
          and len(reg_owners) < len(reg), repr(reg_owners))

    # no wall-clock leaked in
    check("timestamps derive from the fixed base (no wall-clock)",
          m["meta"]["createdISO"] == "2026-04-01T09:00:00Z")

    # haiku is never routed to high risk
    check("no high-risk task is routed to haiku",
          not [t for p in m["phases"] for t in p["tasks"]
               if t.get("risk") == "high" and t.get("model") == "haiku"])

    # small-N edge: all four statuses still representable
    tiny = generate(n_phases=3, n_tasks=1, seed=11)
    check("edge: 3 phases still yield 3 distinct phase statuses",
          len({p["status"] for p in tiny["phases"]}) == 3)

    # round-trip through the real loader + the real validator
    tmp = tempfile.mkdtemp(prefix="gen-demo-manifest-selftest-")
    try:
        written = write_manifest(m, tmp)
        check("wrote an index + one shard per phase + the config",
              len(written) == len(m["phases"]) + 2)
        cfg_path = os.path.join(tmp, ".claude", "audit.config.json")
        check("a .claude/audit.config.json is written beside the manifest",
              os.path.exists(cfg_path))
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        check("the config points manifestPath at the generated manifest "
              "(without it the panel reports 'no manifest')",
              cfg.get("manifestPath") == "audit-plan.json", repr(cfg))
        vc = _loader.load_script("validate-config.py", modname="validate_config")
        cf, cw = vc.validate_config(cfg)
        check("the generated config passes the plugin's config validator",
              not cf and not cw, "; ".join((cf + cw)[:3]))
        mio = _load_manifest_io()
        back = mio.load_manifest(os.path.join(tmp, "audit-plan.json"))
        check("sharded round-trip preserves phase count",
              len(back["phases"]) == len(m["phases"]))
        check("sharded round-trip preserves task count",
              sum(len(p["tasks"]) for p in back["phases"])
              == sum(len(p["tasks"]) for p in m["phases"]))
        check("round-trip preserves phase status (shards carry it, stubs do not)",
              [p["status"] for p in back["phases"]]
              == [p["status"] for p in m["phases"]])

        vm = _loader.load_script("validate-manifest.py", modname="validate_manifest")
        findings, warnings = vm.validate(back)
        check("the plugin's own validator reports no findings", not findings,
              "; ".join(findings[:3]))
        check("the validator reports no warnings", not warnings,
              "; ".join(warnings[:3]))

        single = write_manifest(generate(n_phases=4, n_tasks=2, seed=11),
                                os.path.join(tmp, "flat"), single_file=True)
        check("--single-file writes one manifest plus the config", len(single) == 2)
        flat = json.load(open(single[0], encoding="utf-8"))
        check("--single-file is meta.version 2", flat["meta"]["version"] == 2)
        f2, w2 = vm.validate(flat)
        check("the single-file form also validates clean", not f2 and not w2,
              "; ".join((f2 + w2)[:3]))

        check("CLI exits 2 on --phases 0", main([tmp, "--phases", "0"]) == 2)
        check("CLI exits 0 on a normal run",
              main([os.path.join(tmp, "cli"), "--phases", "5", "--tasks", "3"]) == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, detail in cases:
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           (" (%s)" % detail) if detail and not ok else ""))
    print("\ngen-demo-manifest: %d/%d cases passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
