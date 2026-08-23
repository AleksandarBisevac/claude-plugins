#!/usr/bin/env python3
"""
Synthetic LARGE audit manifest for demos, screenshots and CI — stdlib only.

Two of this repo's most visible artifacts were built from a manifest that was never
committed: `docs/demo-large.html` (the "big audit" scale demo) and the
`docs/screenshots/panel-*.png` set, which exists to back the claim that the
composition table stays usable at 50 phases x 20 tasks. Neither could be
regenerated, so both drifted — on the day this file was written the panel shots
showed three tabs against a UI that had already grown a fourth.

That clause is history and is now written as history. It stood here in the present
tense, carrying two live counts ("the six panel-*.png" and "a UI that has four"),
long after both went wrong: there are sixteen shots today, the UI has six tabs, and
the shots have matched it ever since they became regenerable. Nothing lints prose,
so the only numbers that belong in it are the ones that cannot rot.

This generates that fixture on demand instead of storing it. Nothing it writes needs
committing: the same flags always produce the same bytes, so CI can build the
fixture, capture from it, and throw it away.

    gen-demo-manifest.py <out-dir> [--phases 50] [--tasks 20] [--seed 11]
                                   [--single-file] [--selftest]

WHAT IT DELIBERATELY CONTAINS. A fixture that only holds healthy rows exercises
none of the surfaces that matter, so this one carries every state a reader can
filter on: all four phase statuses and all four task statuses, a phase gated behind
another (`blockedBy`) and a task gated behind a phase, cross-task `dependsOn`,
budgets both under and over, `area` tags so the monorepo grouping has something to
group, tasks with and without `skills` so the panel's "needs skills" filter has
both sides, all three levels of the review-skill chain plus the explicit null that
stops it, sign-off with and without findings, work deferred out of scope, a parked
proposal and a materialized one, and every bug state `_manifest_vocab.BUG_STATUS`
defines including the reciprocal bug<->task links.

WHAT KEEPS THAT LIST HONEST. Not this paragraph — prose is not linted, and the
fixture had drifted 54 fields behind the schema before anything noticed.
`schema_coverage()` below derives the field set FROM THE SCHEMA FILE and requires
every field to be either carried here or named in `SCHEMA_EXEMPTIONS` with the
reason it is not, so a field added to the schema tomorrow arrives as a gap.

WHAT IT DELIBERATELY DOES NOT CONTAIN — AND CAN BE ASKED TO. `phase.claim` is a
live lease, and this generator's default output is what the committed
`docs/demo-large.html` and panel screenshots are rendered from, so the default
carries none. `generate(with_claim=True)` stamps one, for a suite that throws its
fixture away, and there is no CLI flag that reaches it. That opt-in is what makes
the exemption a policy about publishing rather than a gap in the generator, and it
is the only thing that puts a fixture in front of
`_manifest_phases._check_claim`. See the section above `_claim_for`.

DETERMINISTIC BY CONSTRUCTION. A fixed seed, a fixed base date, no wall-clock. The
validator's rules are respected by construction rather than by luck — in
particular a `done` phase never contains an unfinished task, which is the
constraint that makes naive random status assignment produce an invalid manifest.
`plugins/audit/tests/test_gen_demo_manifest.py` pins determinism, referential
integrity, schema coverage and that constraint - this file carries no inline
`--selftest` any more, and its cases live there with byte-identical labels. The
count they once stood at is deliberately not written here: it rots, and this
docstring has already carried two numbers that did.
"""
import argparse
import datetime
import json
import os
import random
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

import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _demo_cast  # noqa: E402  (the demo's author identities, shared with gen-demo-usage)

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


def _tests_add(mode, rel):
    """The tests a task promises to author, in the wording its MODE gives them.

    `audit-task.py` writes `expectRedFirst = mode == "tdd"` beside this list, and
    the schema says the list's meaning is mode-dependent. So the two must be
    generated together or the fixture would ship a manifest that disagrees with
    itself about what its own tests are for.
    """
    if mode == "tdd":
        return ["a failing repro for %s: it must go red on current code" % rel]
    if mode == "regression":
        return ["a guard locking %s's corrected behaviour" % rel]
    return []                              # gate-only authors no test at all


def _review_findings(area, pi, tasks):
    """Sign-off findings in the STRUCTURED shape `agents/audit-reviewer.md` emits.

    The schema tolerates a plain string for back-compat and prefers the object;
    the demo shows the preferred one, because a fixture is also documentation of
    what to write. Each finding names a real file from the phase it belongs to -
    a `file` pointing nowhere is the kind of detail a reader checks first.
    """
    graded = ("low", "med", "high")
    return [{"id": i + 1,
             "severity": graded[(pi + i) % len(graded)],
             "file": "%s:%d-%d" % (task["files"][0], 12 + 7 * i, 20 + 7 * i),
             "issue": "The %s path is not covered for the empty-input case."
                      % area,
             "resolution": "Covered by the gate added in %s." % task["id"]}
            for i, task in enumerate(tasks[:2])]


def _phase_model(tasks):
    """The phase's DEFAULT executor tier, or None when there is no basis.

    The schema reads `model` as the tier the orchestrator spawns, and a task's
    own `model` overrides it - so a phase declares the tier its TYPICAL task
    needs, which is the modal risk among its tasks. Ties break upward, because
    the audit's own routing rule forbids haiku on high risk: a default that
    over-serves is recoverable, one that under-serves is a rule violation.

    "The riskiest task" was tried first and measured: at five tasks a phase
    almost always holds one `high`, so all 40 phases came out `opus` and the
    orchestrator ledger was as uniform as the DEFAULT_MODEL fallback it replaced
    - a basis, but one that answers the same for everybody, which is how a
    derived value quietly becomes a constant again.

    A phase with no risk-bearing task has NO basis, so it declares no tier.
    Falling back to a plausible-looking one is what this whole change is against.
    """
    risks = [t.get("risk") for t in tasks if t.get("risk") in RISK_MODEL]
    if not risks:
        return None
    modal = max(RISKS, key=lambda r: (risks.count(r), RISKS.index(r)))
    return RISK_MODEL[modal]


def _demo_areas():
    """The `meta.areas` registry, advisory owners included (v0.34).

    The owner identities are `_demo_cast.DEFAULT_AUTHORS`, imported rather than
    restated — an owner the ledger has never seen is exactly the mismatch
    /audit:doctor warns about, and this fixture exists to show the join working.
    They used to be read off `gen-demo-usage.py` through `_loader`, which is one
    entry point loading another for one name: the last of the seventeen edges
    `_deps.KNOWN_LAYER_DEBT` recorded. `infra` stays ownerless on purpose: the
    no-owner case must render too. Every entry carries a root because the
    validator warns on a rootless area and the selftest holds the fixture to zero
    warnings.
    """
    authors = _demo_cast.DEFAULT_AUTHORS
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
        # The MIDDLE of `phase.reviewSkill ?? areas[tag].reviewSkill ??
        # meta.reviewSkill`, and the level a monorepo actually uses: backend and
        # mobile get different reviewers because they are different codebases.
        # Not every area declares one — an area that stays silent is what makes
        # the fall-through to meta.reviewSkill observable.
        if tag in ("backend", "mobile"):
            entry["reviewSkill"] = SKILL_POOL[(i + 1) % len(SKILL_POOL)]
        out[tag] = entry
    return out


# --- the lease, on request and never in the published fixture --------------------
# `phase.claim` is the one region of the schema `SCHEMA_EXEMPTIONS` below holds back
# on POLICY rather than on capability, and telling those two apart is the whole
# point of this section.
#
# A claim is a LIVE LEASE — which session, on which host, on which branch is running
# this phase right now — released when the phase finishes. The DEFAULT output of
# this generator is what `docs/demo-large.html` and the `docs/screenshots/panel-*`
# set are built from, and both are COMMITTED. A lease in that output publishes a
# demo permanently held by a session that does not exist, `/audit:doctor` reports it
# as a stale claim on the page that exists to show a healthy run, and `claim.host`
# publishes whoever generated it.
#
# Every word of that is about what this generator PUBLISHES; none of it is about
# what it can produce. So the lease is available on request and by nothing else:
# `generate(with_claim=True)` stamps one, and there is deliberately NO CLI FLAG that
# reaches it. Every command that produces a committed artifact — the scale-demo step
# in `.github/workflows/ci.yml`, `tools/capture-screenshots.mjs` — goes through
# `main()`, so the absence of the flag is what keeps `docs/` lease-free
# structurally, rather than by anyone remembering. A flag would put the published
# mistake one word away on the command line and buy nothing: nobody wants a claimed
# demo, and the one caller that needs a lease is a suite that deletes its fixture in
# a `finally`.
#
# WHY THE OPT-IN EXISTS AT ALL. Without it `_manifest_phases._check_claim` had no
# fixture that reached it: its first statement is `if "claim" not in phase: return`,
# so the validator's walk over this fixture entered and returned on every phase at
# every size. That is a traversal, not coverage — and it left the exemption above
# unfalsifiable, because nothing could show the generator was holding the lease back
# rather than unable to produce one.
#
# EVERY VALUE IS A FIXED LITERAL OR DERIVED FROM THE FIXTURE. Nothing here reads the
# machine, the environment or the clock, and that is a structural property rather
# than a matter of care: `tests/test_gen_demo_manifest.py` parses this file and
# fails on an identifier that could reach any of them. The `.invalid` top-level
# domain is reserved by RFC 2606, so "resolves to nobody" is a fact about the name.
CLAIM_HOST = "runner.demo.invalid"
CLAIM_SESSION_PREFIX = "demo-session"


def _claim_for(phase):
    """The lease a phase is entitled to, or None when it is entitled to none.

    Only an `in_progress` phase holds one. `_manifest_phases._check_claim` warns
    about a claim left on a done, blocked or cancelled phase, so stamping one there
    would make the fixture demonstrate the warning instead of the feature.

    `at` is the moment the session picked the phase up, taken from the phase's own
    earliest task start: the fixture already knows when work on the phase began, and
    a second timestamp invented beside it would be a figure with no basis. A phase
    with no started task, or no branch to name, has no such moment — it gets no
    lease rather than a filled-in one.
    """
    if phase.get("status") != "in_progress":
        return None
    starts = sorted(t.get("startedAt") for t in phase.get("tasks") or []
                    if t.get("startedAt"))
    if not starts or not phase.get("branch"):
        return None
    return {
        "sessionId": "%s-%s" % (CLAIM_SESSION_PREFIX, str(phase.get("id")).lower()),
        "host": CLAIM_HOST,
        "branch": phase["branch"],
        "at": starts[0],
    }


def _stamp_claims(phases):
    """Attach a lease to every phase entitled to one; returns the ids stamped.

    Raises rather than returning an empty list. A `with_claim=True` that stamped
    nothing would hand back a claim-free manifest under a name saying otherwise,
    and a case asserting "the validator walks the lease clean" over that document
    would be asserting nothing — the exact silent pass this fixture exists to end.
    """
    stamped = []
    for phase in phases:
        claim = _claim_for(phase)
        if claim is None:
            continue
        phase["claim"] = claim
        stamped.append(phase.get("id"))
    if not stamped:
        raise ValueError(
            "with_claim=True stamped no lease: no phase was in_progress with a "
            "branch and a started task, so there was no basis for one - and a "
            "claim-free manifest returned under this flag would read as coverage "
            "of a path nothing entered")
    return stamped


def generate(n_phases=50, n_tasks=20, seed=11, repo="demo", with_claim=False):
    """Build an ASSEMBLED manifest dict (the sharded split happens on write).

    `with_claim` stamps the parallel-run lease on the one `in_progress` phase. It
    is OFF for every published artifact and no CLI flag turns it on — the section
    comment above `_claim_for` says why, and `SCHEMA_EXEMPTIONS` records what the
    default fixture therefore does not carry. It draws nothing from `rng` and runs
    after the loop, so the default bytes are the same bytes either way.
    """
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
            mode = TEST_MODES[(pi + ti) % len(TEST_MODES)]
            task = {
                "id": tid,
                "title": "%s %s" % (TITLE_VERBS[(pi + ti) % len(TITLE_VERBS)],
                                    TITLE_NOUNS[(pi * 3 + ti) % len(TITLE_NOUNS)]),
                "status": tstatus,
                "model": RISK_MODEL[risk],
                "risk": risk,
                "files": [rel],
                "tests": {
                    "mode": mode,
                    # `add` and `expectRedFirst` are the two halves of the TDD
                    # contract and they only mean anything together: the same
                    # sentence in `add` describes a test that must FAIL first
                    # under 'tdd' and a guard written AFTER the fix under
                    # 'regression'. `gate-only` adds no test, so its `add` is
                    # empty on purpose - the fixture carries that case too,
                    # because an always-populated list never shows it.
                    "add": _tests_add(mode, rel),
                    "expectRedFirst": mode == "tdd",
                    "gate": ["yarn test --findRelatedTests %s" % rel],
                },
                "attempts": 0,
                "maxAttempts": 3,
            }
            # Prose and reference links on a SLICE of tasks, never all of them:
            # the report has to render a task with a description and a task
            # without one, and a fixture where every optional field is always
            # present shows only half of what the surfaces do.
            if (pi + ti) % 2 == 0:
                task["description"] = (
                    "%s so the behaviour is pinned by a test rather than by "
                    "convention." % task["title"])
            if (pi + ti) % 7 == 0:
                task["docs"] = ["docs/architecture/%s.md" % area]
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
            # ...and the other kind of wait, which is not the same rule wearing a
            # second name: `dependsOn` orders tasks inside a phase, `blockedBy` is
            # the HARD GATE that can name a PHASE. A task waiting on the previous
            # phase is the documented use, and the readiness list has to show both
            # or a reader cannot tell them apart.
            if pi > 1 and tstatus == "pending" and (pi + ti) % 9 == 0:
                task["blockedBy"] = ["P%d" % (pi - 1)]

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
        # F34: the tier this phase's ORCHESTRATOR runs at. It was absent, and
        # `gen-demo-usage` maps an absent tier through
        # `TIER_TO_MODEL.get(tier, DEFAULT_MODEL)` - which cannot fail, so all 148
        # orchestrator rows of the 40x5 demo (31% of 482) printed
        # `claude-sonnet-5` as though the manifest had chosen it. A model
        # attribution produced by a fallback is a claim with no basis, on the page
        # this project uses to show what it does.
        tier = _phase_model(tasks)
        if tier:
            phase["model"] = tier
        if pi % 3 == 1:
            phase["description"] = (
                "Free-text context for the %s pass: what a reader needs to know "
                "before opening the tasks." % area)
        if pi % 5 == 2:
            phase["docs"] = ["docs/architecture/%s.md" % area,
                             "docs/runbooks/%s-oncall.md" % area]
        # The middle of the documented resolution chain
        # (phase.reviewSkill ?? areas[tag].reviewSkill ?? meta.reviewSkill) needs
        # all three levels present to be visible at all. An explicit null is the
        # fourth state and not a miss: it is how a phase says "tests sign this
        # one off", and it STOPS the fallback rather than deferring to it.
        if pi % 6 == 3:
            phase["reviewSkill"] = SKILL_POOL[pi % len(SKILL_POOL)]
        elif pi % 6 == 0:
            phase["reviewSkill"] = None
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
            # Sign-off carries the evidence that makes "passed" mean something:
            # who signed (tool), at which tier (model), and — on some phases —
            # the findings that were raised and resolved before it passed. A
            # review that only ever says "no findings" shows the reviewer's
            # empty state and nothing else, so the fixture carries both.
            phase["review"] = {
                "tool": "audit-reviewer",
                "model": RISK_MODEL["high"],
                "status": "passed",
                "outcome": "No actionable findings on the phase diff.",
                "findings": [],
            }
            if pi % 4 == 1:
                phase["review"]["findings"] = _review_findings(area, pi, tasks)
                phase["review"]["outcome"] = (
                    "%d finding(s) raised on the phase diff and resolved before "
                    "sign-off." % len(phase["review"]["findings"]))
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
        # The sprint a push stamped this item into. Recorded so `/audit:status`
        # can report sprint DRIFT after a rollover — which it cannot do from
        # `meta.ado.iterationPath`, because that is the mode, not the stamp.
        "iterationPath": "%s\\Sprint 12" % repo,
        "lastSyncedAt": "2026-08-06T12:00:00Z",
        # Where the card came from. BOTH values appear across the fixture's three
        # links (this one and the task below were created by a push; the bug's was
        # imported), because a state the fixture does not carry is a state no
        # surface renders and no gate can assert — the reasoning that put a
        # `dropped` proposal in here too.
        "origin": "created"}
    phases[0]["tasks"][0]["ado"] = {
        "id": 4711,
        "url": "https://dev.azure.com/demo-org/%s/_workitems/edit/4711" % repo,
        "lastSyncedAt": "2026-08-06T12:05:00Z",
        "origin": "created"}

    # After the loop and outside it: the lease draws nothing from `rng`, so the
    # default run's bytes cannot move whichever way this flag is set.
    if with_claim:
        _stamp_claims(phases)

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
            # The build/runtime half of the configuration, which the orchestrator
            # prose reads and the committed acme example already declares. The
            # demo declared none of it, so the scale page showed a project with
            # no commit convention, no node hint and no smoke gate — three
            # answers a real audit always has, even when the answer is null.
            "commit": {"type": "fix", "coauthor": None},
            "node": "20.x",
            "nodePreamble": None,
            "runtimeBoot": {"appRootPath": "src",
                            "launch": "yarn dev --port 4173",
                            "verify": "GET http://localhost:4173/health is 200"},
            # The BOTTOM of the review-skill chain: the default reviewer when
            # neither the phase nor its area names one. Spelled from SKILL_POOL
            # so panel discovery resolves it — a name nothing on disk answers to
            # draws "discovery knows no such skill" across the screenshots.
            "reviewSkill": SKILL_POOL[4],
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
        # Work this audit decided NOT to do, which is a result and not an
        # omission: /audit:status prints it and the acme example carries it.
        "deferred": {
            "note": "Out of scope for this cycle — tracked for the next audit.",
            "target": "the Q3 platform audit",
            "items": [
                "Move the storefront catalog page to server components",
                {"title": "Replace the bespoke retry wrapper with the platform one",
                 "reason": "Blocked on the platform release that ships it.",
                 "target": "the Q3 platform audit"},
            ],
        },
        "proposals": _proposals(n_phases),
    }
    return manifest


# --- schema coverage -------------------------------------------------------------
# The fixture is what the project SHOWS. A schema field it never carries is a
# feature nobody sees working, and the gap is invisible because nothing compares
# the two documents: the demo sat ~54 fields behind the schema for four releases
# and no check could say so.
#
# THE FIELD SET IS DERIVED FROM THE SCHEMA FILE, never typed here. A hand-typed
# list goes stale exactly the way the fixture did - `_manifest_vocab.KNOWN_*` is
# the second copy that already exists - so a field added to the schema tomorrow
# shows up here as an unexplained gap rather than passing forever.
#
# Every gap is then one of two things and never a third: covered by the fixture,
# or named below with the reason it is not. A lint that skips quietly is the thing
# this repo keeps rediscovering, so `schema_coverage()` also reports STALE
# exemptions - an excuse for a field the schema dropped, or for one the fixture now
# carries, is a reason nobody is paying and it has to go.
ROOT_OWNER = "<root>"
SCHEMA_REL = ("schema", "audit-plan.schema.json")

# Fields whose VALUE the coverage walk records but does not enter. `payload` is a
# whole phase parked losslessly inside a proposal — same `$ref`s, same task and
# `tests` shapes — so walking into it lets a phase NOBODY RUNS answer for the live
# plan. Measured: deleting `tests.add` from every live task left the lint green,
# because the parked payload still carried one. A fixture exists to show the
# surfaces working, and no surface renders a staged payload.
OPAQUE_FIELDS = frozenset(["proposal.payload"])

SCHEMA_EXEMPTIONS = {
    "<root>.$schema":
        "names a URL so an EDITOR can validate a document while a human types it. "
        "This fixture is generated into a temp directory, rendered, and thrown "
        "away - nothing ever opens it. Stamping it means either a fourth "
        "hand-typed copy of the schema URL (there is no shared constant) or file "
        "I/O inside a generate() documented as pure; CI validates the generated "
        "manifest against the schema BY PATH instead.",
    "meta.branch":
        "the branch-naming convention. It decides what `git switch -c` is handed "
        "and NOTHING the demo renders: the report and the panel show a phase's "
        "`branch` string, which this fixture already carries verbatim, not the "
        "template that produced it. Carrying a template here would exercise "
        "`_branch.compose` against a fixture nobody branches from - the real "
        "coverage is `tests/test__branch.py`, which composes names, and "
        "`test_resolve_branch.py`, which runs the door. REVISIT when the panel "
        "grows a meta.branch card: the demo is where its screenshot comes from.",
    "phase.parentBranch":
        "which branch THIS phase forks from and merges into. Absent means "
        "`meta.developmentBranch`, which is the answer for every phase in this "
        "fixture and for most phases anywhere. Setting it on a demo phase would "
        "name a story branch that does not exist in a generated manifest nobody "
        "clones, so the field would be decoration rather than a demonstration.",
    "phase.branchType":
        "the `{type}` segment. Same reason as `meta.branch`: it is an input to a "
        "name, and the name itself is what the fixture carries and the report "
        "renders.",
    "phase.shard":
        "written by `_manifest_io.split_manifest` onto the INDEX stub, never by "
        "this generator. `generate()` returns the ASSEMBLED manifest, in which a "
        "shard pointer would name a file that form does not have; the write path "
        "is pinned by the sharded round-trip cases.",
    "phase.claim":
        "a LIVE lease: which session, host and branch is running this phase right "
        "now, released when the phase finishes. The DEFAULT output is what "
        "docs/demo-large.html and the panel screenshots are built from and both "
        "are committed, so a lease there publishes a demo permanently held by a "
        "session that does not exist, and /audit:doctor reports it as a stale "
        "claim on the page that exists to show a healthy run. THIS IS A POLICY "
        "ABOUT WHAT IS PUBLISHED, NOT A GAP IN THE GENERATOR: "
        "generate(with_claim=True) stamps one for a suite that throws its fixture "
        "away, and no CLI flag reaches it. See the section above _claim_for.",
    "phase.priority":
        "which phase the pipeline reaches for first among the work that is "
        "ALREADY ready. Absent is not a gap here, it is the demonstrated state: "
        "the fixture's whole point is a plan running in written order, and a pin "
        "in it would reorder the ready list under a report and a panel whose "
        "committed screenshots show that order. The field is index-only, so in "
        "the sharded form it would also have to be stamped on a stub this "
        "generator does not build. Coverage lives in tests/test__priority.py "
        "(the comparator) and tests/test_set_priority.py (the write). REVISIT "
        "when the panel's phase row grows a priority badge worth a screenshot.",
    "phase.adoParent":
        "which EXISTING Azure DevOps work item this phase hangs under. The "
        "fixture carries no `meta.ado` at all - the demo is a plan, not a "
        "connected board - so a parent id here would name a work item in a "
        "project the demo does not have, and every surface that renders it "
        "would print a link to nothing. Coverage is "
        "tests/test__ado_parent.py (the resolution and the hierarchy tiers) "
        "and tests/test_resolve_ado_parent.py (the door). REVISIT when the "
        "demo grows a connector card worth a screenshot, which is the same "
        "trigger meta.branch carries.",
    "task.adoParent":
        "the same field one level down, honoured only when "
        "meta.ado.phaseWorkItems is false. Same reason and same revisit "
        "trigger as phase.adoParent: without a meta.ado there is no project "
        "for an id to mean anything in.",
    "adoParent.id":
        "a field of adoParent, which this fixture does not take. An id is the "
        "one part that cannot be invented: it names a real work item on a real "
        "board, and a made-up one in a published demo is a link readers "
        "follow into a 404.",
    "adoParent.type":
        "a field of adoParent, which this fixture does not take: it is the "
        "BASIS for the backlog-rank check, and a type name with no project "
        "behind it grades against a hierarchy nobody fetched.",
    "adoParent.title":
        "a field of adoParent, which this fixture does not take: the title of "
        "a work item this demo does not link to is not a fact about the demo.",
    "adoParent.url":
        "a field of adoParent, which this fixture does not take: a URL into an "
        "organization the demo does not have is the one thing worse than an "
        "absent link, because it looks clickable.",
    "adoParent.source":
        "a field of adoParent, which this fixture does not take. Absent means "
        "unrecorded, which is the honest state for a declaration nobody "
        "wrote; stamping 'declared' here would put a provenance on nothing.",
    "adoParent.observedAt":
        "a field of adoParent, which this fixture does not take: the moment a "
        "basis nobody observed was observed is not a fact, and this generator "
        "is deterministic with no wall-clock by construction.",
    "claim.at":
        "a field of phase.claim, which the default fixture does not take: the "
        "timestamp a lease nobody holds would carry is not a fact about the demo. "
        "Under with_claim it is the phase's own earliest task start.",
    "claim.branch":
        "a field of phase.claim, which the default fixture does not take: the "
        "branch a lease nobody holds would name is not a fact about the demo. "
        "Under with_claim it is the phase's own branch, not a second invention.",
    "claim.host":
        "a field of phase.claim, which the default fixture does not take: a host "
        "name is the one part of a claim that would publish whoever generated it. "
        "Under with_claim it is CLAIM_HOST, a reserved .invalid name that resolves "
        "to nobody, and the suite parses this file to keep it that way.",
    "claim.sessionId":
        "a field of phase.claim, which the default fixture does not take: a "
        "session id invented for a published fixture is exactly the stale claim "
        "/audit:doctor reports. Under with_claim it is CLAIM_SESSION_PREFIX and "
        "the phase id, in a document no artifact is rendered from.",
    "phase.reviewFindings":
        "the schema itself calls it legacy (pre-plugin manifests), informational, "
        "and not read by the orchestrator. Measured: no reader anywhere under "
        "scripts/, hooks/, commands/ or agents/ - only the schema and "
        "`_manifest_vocab.KNOWN_PHASE`. The demo shows what the plugin does.",
    "review.preExistingNotCharged":
        "defined by the schema and by nothing else - no reader, no writer, and not "
        "even a `_manifest_vocab` entry. A fixture value would demonstrate nothing.",
    "task.movedFrom":
        "written by /audit:task move, and its whole purpose is to let a reader join "
        "HISTORICAL ledger rows filed under the task's old id. `gen-demo-usage.py` "
        "derives the demo's ledger from THIS manifest's current ids, so a "
        "`movedFrom` here would advertise a join to rows the demo does not have - "
        "the fixture would contradict itself.",
}


def load_schema():
    """The manifest JSON Schema, read from the plugin's own copy.

    By path from `_output.PLUGIN_ROOT` rather than from `__file__`: this file may
    sit at any depth under `scripts/` and `depth_sensitive_paths()` forbids the
    alternative.
    """
    path = os.path.join(_output.PLUGIN_ROOT, *SCHEMA_REL)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _deref(schema, node):
    """(def name, node) after following `$ref`; name is None for an inline node."""
    name, cur, hops = None, node, 0
    while isinstance(cur, dict) and "$ref" in cur and hops < 20:
        name = str(cur["$ref"]).split("/")[-1]
        cur = (schema.get("$defs") or {}).get(name) or {}
        hops += 1
    return (name, cur)


def _property_maps(node):
    """Every `properties` map a node contributes - its own and each oneOf/anyOf
    branch's, because `finding` declares its object shape inside a oneOf."""
    if not isinstance(node, dict):
        return []
    out = []
    if isinstance(node.get("properties"), dict):
        out.append(node["properties"])
    for branch in list(node.get("oneOf") or []) + list(node.get("anyOf") or []):
        if isinstance(branch, dict) and isinstance(branch.get("properties"), dict):
            out.append(branch["properties"])
    return out


def schema_fields(schema):
    """Every `<owner>.<field>` the schema DEFINES; owner is `<root>` or a $def name.

    Owners are named things only. An object the schema spells out inline - the
    sub-keys of `meta.ado`, of `meta.usage` - has no name to attribute a field to,
    and attributing them to the parent would count `meta.organization` as a `meta`
    field the schema never declared.
    """
    out = set()
    for props in _property_maps(schema):
        for key in props:
            out.add("%s.%s" % (ROOT_OWNER, key))
    for name, node in (schema.get("$defs") or {}).items():
        for props in _property_maps(node):
            for key in props:
                out.add("%s.%s" % (name, key))
    return out


def _walk_fields(schema, node, data, owner, out):
    """Record `<owner>.<field>` for every schema-declared key `data` carries.

    Descending into an INLINE object drops the owner (None), which is the same
    rule `schema_fields` applies from the other side; a `$ref` picks a new one up.
    An `OPAQUE_FIELDS` entry is recorded and then not entered.
    """
    name, cur = _deref(schema, node)
    if name is not None:
        owner = name
    if not isinstance(cur, dict):
        return
    for branch in list(cur.get("oneOf") or []) + list(cur.get("anyOf") or []):
        _walk_fields(schema, branch, data, owner, out)
    props = cur.get("properties") if isinstance(cur.get("properties"), dict) else {}
    if isinstance(data, dict):
        extra = cur.get("additionalProperties")
        for key, val in data.items():
            if key in props:
                field = "%s.%s" % (owner, key) if owner is not None else None
                if field is not None:
                    out.add(field)
                if field in OPAQUE_FIELDS:
                    continue
                _walk_fields(schema, props[key], val, None, out)
            elif isinstance(extra, dict):
                _walk_fields(schema, extra, val, None, out)
    if isinstance(data, list) and isinstance(cur.get("items"), dict):
        for item in data:
            _walk_fields(schema, cur["items"], item, None, out)


def manifest_fields(manifest, schema=None):
    """Every `<owner>.<field>` the manifest actually CARRIES (presence, not value:
    `skills: null` is an answer and counts, which is the point of that key)."""
    schema = load_schema() if schema is None else schema
    out = set()
    _walk_fields(schema, schema, manifest, ROOT_OWNER, out)
    return out


def schema_coverage(manifest, schema=None):
    """What the fixture exercises, what it skips on purpose, and what it just misses.

    `gaps` is the answer the lint reads: a schema field the fixture does not carry
    and `SCHEMA_EXEMPTIONS` does not explain. `stale` is the same question
    backwards, and it is what stops the exemption list becoming a place to put
    things: an entry naming a field the schema no longer defines, or one the
    fixture now carries, is an unpaid reason.
    """
    schema = load_schema() if schema is None else schema
    defined = schema_fields(schema)
    carried = manifest_fields(manifest, schema) & defined
    exempt = set(SCHEMA_EXEMPTIONS)
    return {"defined": sorted(defined),
            "covered": sorted(carried),
            "exempt": sorted((exempt & defined) - carried),
            "gaps": sorted(defined - carried - exempt),
            "stale": sorted((exempt - defined) | (exempt & carried))}


# --- proposals + bugs + output ---------------------------------------------------
def _proposals(n_phases):
    """Parked phases: what /audit:init synthesized and the user did not approve.

    ALL THREE states, because each is validated by DIFFERENT rules and a fixture
    carrying two of them proves two thirds of the feature. A still-PROPOSED
    payload RESERVES its phase and task ids (allocation counts them alongside live
    ids), so its phase sits one past the last live one; a MATERIALIZED record has
    already become a live phase, so its payload id is the live id on purpose and
    `materializedAs` has to name a phase that exists; a DROPPED record must carry
    a `notes` justification, which the validator now requires rather than trusting
    a command's prose to have asked for it.

    The dropped one is here rather than exempted from the schema-coverage lint
    because this fixture is what the panel screenshots and docs/demo-large.html
    are rendered from: a state absent here is a state no rendered surface ever
    shows and no browser gate can assert. An archive nobody can see is the defect
    the drop pair exists to prevent.
    """
    parked = "P%d" % (n_phases + 1)
    props = [{
        "id": "PROP-1",
        "name": "Observability pass",
        "status": "proposed",
        "origin": "audit:init",
        "createdISO": _iso(BASE + datetime.timedelta(days=1)),
        "scope": "src/infra, src/backend",
        "benefit": "Every failing request can be traced to the call that made it.",
        "technicalNote": "Needs the tracing SDK pinned before the first task runs.",
        "openQuestions": ["Which sampling rate does the platform team run?"],
        "materializedAs": None,
        "materializedAt": None,
        "payload": {"phase": {
            "id": parked,
            "title": "Observability pass",
            "status": "pending",
            "area": "infra",
            "desiredOutcome": "Traces and structured logs on every request path.",
            "testGate": ["yarn test --selectProjects infra"],
            "tasks": [{"id": "%s.%d" % (parked, i),
                       "title": "Instrument the %s boundary" % tag,
                       "status": "pending", "model": RISK_MODEL["med"],
                       "risk": "med", "files": ["src/infra/trace_%02d.ts" % i],
                       "tests": {"mode": "regression",
                                 "add": ["a guard asserting the span is emitted"],
                                 "expectRedFirst": False,
                                 "gate": ["yarn test --selectProjects infra"]},
                       "attempts": 0, "maxAttempts": 3}
                      for i, tag in enumerate(("http", "queue"), start=1)],
        }},
    }]
    if n_phases < 2:
        return props            # nothing live for a materialized record to name
    props.append({
        "id": "PROP-2",
        "name": "Web storefront pass",
        "status": "materialized",
        "origin": "audit:init",
        "createdISO": _iso(BASE + datetime.timedelta(days=1)),
        "scope": "src/web",
        "benefit": "The storefront's own passes stop riding on the backend phase.",
        "technicalNote": "Materialized unchanged; the payload is kept as the record.",
        "openQuestions": [],
        "materializedAs": "P2",
        "materializedAt": _iso(BASE + datetime.timedelta(days=2)),
        "payload": {"phase": {"id": "P2", "title": "Web pass 2",
                              "status": "pending", "area": "web", "tasks": []}},
    })
    props.append({
        "id": "PROP-3",
        "name": "Rewrite the importer in Rust",
        "status": "dropped",
        "origin": "audit:init",
        "createdISO": _iso(BASE + datetime.timedelta(days=1)),
        "scope": "src/import",
        "benefit": "Faster imports.",
        "technicalNote": "Parked, then declined.",
        "openQuestions": [],
        # The drop pair. `notes` is REQUIRED once status is dropped: a dropped
        # proposal is history rather than a deletion, so it has to say why.
        "notes": "declined - the importer is being replaced wholesale in Q4, so "
                 "rewriting it first is work with no reader",
        "droppedAt": _iso(BASE + datetime.timedelta(days=3)),
        "payload": {"phase": {"id": "P%d" % (n_phases + 2),
                              "title": "Importer rewrite",
                              "status": "pending", "tasks": []}},
    })
    return props


def _first_task(phases, phase_status, task_status):
    """The first task in document order matching (phase status, task status).

    Two nested loops with a break out of each were how this used to find the one
    task a bug links to, and it could only ever find one thing. Naming the pair it
    matches on lets a second link ask for a different one without a second copy of
    the walk.
    """
    for ph in phases:
        if ph.get("status") != phase_status:
            continue
        for task in ph.get("tasks") or []:
            if task.get("status") == task_status:
                return task
    return None


def _bugs(phases):
    """A full bug lifecycle, including two reciprocal bug<->task links.

    The link has to be reciprocal in both directions or the validator rejects it,
    and the linked task has to be a real id — which is why this runs after the
    phases exist rather than generating ids it hopes will be there.

    "Full" now means what `_manifest_vocab.BUG_STATUS` means. It did not: the
    fixture stopped at four of the five states and skipped `fixed`, so the only
    terminal state that carries EVIDENCE — `fixedIn`, the commit of the task that
    closed it — was the one state the demo never rendered.
    """
    running = _first_task(phases, "in_progress", "in_progress")
    closed = _first_task(phases, "done", "done")
    bugs = [
        {"id": "BUG-1", "title": "Product images 404 intermittently on Safari",
         "status": "open", "severity": "med", "reportedBy": "qa",
         "reportedAt": _iso(BASE + datetime.timedelta(days=5)),
         "description": "Some catalog images fail to load on first paint in Safari.",
         "repro": "Open the catalog in Safari with an empty cache.",
         "expected": "Every image loads.", "actual": "Two or three 404 briefly.",
         "files": ["src/web/image_pipeline.ts"]},
        {"id": "BUG-2", "title": "Checkout is slow on 3G mobile",
         "status": "triaged", "severity": "low", "reportedBy": "support",
         "reportedAt": _iso(BASE + datetime.timedelta(days=7)),
         "description": "Checkout takes over ten seconds on a throttled connection.",
         "files": ["src/web/checkout.ts", "src/backend/pricing.ts"]},
        {"id": "BUG-4", "title": "Dark-mode label contrast below AA",
         "status": "wontfix", "severity": "low", "reportedBy": "design",
         "reportedAt": _iso(BASE + datetime.timedelta(days=11)),
         "notes": "Superseded by the design-token refresh; tracked there instead."},
    ]
    if running is not None:
        bugs.insert(2, {
            "id": "BUG-3",
            "title": "Cart total off by one with stacked discounts",
            "status": "in_progress", "severity": "high", "reportedBy": "qa",
            "reportedAt": _iso(BASE + datetime.timedelta(days=9)),
            "description": "Two stacked percentage discounts round the wrong way.",
            "repro": "Apply a 10% and a 5% discount to a 19.99 item.",
            "expected": "17.09", "actual": "17.10",
            "files": ["src/backend/pricing.ts"],
            "taskId": running["id"],
            # The connector's third link kind. The phase and task links below
            # prove the panel's ADO banner reads EVIDENCE; a bug link is what
            # /audit:sync writes for the tracker's own bug type.
            "ado": {"id": 4722,
                    "url": "https://dev.azure.com/demo-org/demo/_workitems/edit/4722",
                    "lastSyncedAt": "2026-08-06T12:10:00Z",
                    # `imported`: a bug somebody else filed on the board, adopted
                    # by `pull bugs`. The other two links say `created`, so the
                    # fixture carries both origins and the doctor's split cannot
                    # be asserted from a single-value fixture that proves nothing.
                    "origin": "imported"},
        })
        running["bugId"] = "BUG-3"
    if closed is not None:
        bugs.append({
            "id": "BUG-5",
            "title": "Logout leaves the session cookie in place",
            "status": "fixed", "severity": "high", "reportedBy": "security",
            "reportedAt": _iso(BASE + datetime.timedelta(days=3)),
            "description": "The session cookie survives logout and still authenticates.",
            "repro": "Log in, log out, replay the old cookie.",
            "expected": "Logout clears the cookie and kills the server session.",
            "actual": "The old cookie still authenticates.",
            "files": ["src/backend/auth_middleware.ts"],
            "taskId": closed["id"],
            # The evidence that makes `fixed` different from `wontfix`: the
            # commit of the task that closed it, taken from that task rather
            # than invented, so the report's link lands somewhere real.
            "fixedIn": closed.get("commit"),
        })
        closed["bugId"] = "BUG-5"
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
