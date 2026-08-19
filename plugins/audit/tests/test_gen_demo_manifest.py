#!/usr/bin/env python3
"""
The cases for `gen-demo-manifest.py`, moved out of it - the entry-point shape.

Hyphenated, so the file name substitutes underscores and the module comes through
`_loader.load_script`; see `test_migrate_manifest.py` for that rule. `M` is the
module under test.

`_loader` is imported under its own name, the way `gen-demo-manifest.py` itself
imports it, because several cases load OTHER production scripts through it -
`gen-demo-usage.py` for the ledger's author list, `validate-config.py` and
`validate-manifest.py` to run the plugin's real validators over the generated
fixture. Those are loads of modules, not reads of their source; the fixture is
asserted against the same validators a user's manifest meets.

Every path is either under one `tempfile.mkdtemp()`, removed in `finally`, or
resolved by `_loader` from `scripts/`. Nothing is derived from this file's location.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("gen-demo-manifest.py", modname="gen_demo_manifest")

# Identifiers that could reach the machine the generator runs on, the account
# running it, the clock, or a random id. `claim.host` is the one field of a lease
# that would publish the first of those, and the generator's own docstring claims
# the third ("no wall-clock"); neither was a checkable property before this.
_BANNED_MODULES = ("socket", "uuid", "platform", "getpass", "pwd", "time",
                   "subprocess")
_BANNED_NAMES = ("gethostname", "getfqdn", "gethostbyname", "uname", "getlogin",
                 "getuser", "environ", "getenv", "now", "utcnow", "today")


# --- source scanner -----------------------------------------------------------
def _machine_reads(src):
    """Sorted identifiers in `src` that reach the machine, the account or the clock.

    AST, and the parser is doing two things a substring scan cannot. The banned
    words have to be SPELLABLE in the comments and docstrings that explain why they
    are banned, and a text scan finds them there; and `datetime.timedelta` contains
    the substring `time.time`, so a text scan reports the fixture's own arithmetic
    as a wall-clock read. Both were measured on this file before this function
    replaced the grep that produced them.

    WHAT IT CANNOT SEE, and the direction is the same for every item — it
    UNDER-counts, so a clean result means "none of the known spellings", never "no
    machine read":

      * a name assembled at runtime (`getattr(os, "envi" + "ron")`) - nothing
        static reads that;
      * an identity source whose spelling is in neither tuple;
      * a read performed by a module this file imports rather than by this file -
        the scan takes one source text, and `_loader`, `_output` and `_demo_cast`
        are not it;
      * a value read out of a FILE the generator opens, which is not an identifier
        at all.
    """
    hits = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BANNED_MODULES:
                    hits.add(root)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _BANNED_MODULES:
                hits.add(root)
        elif isinstance(node, ast.Attribute):
            if node.attr in _BANNED_NAMES:
                hits.add(node.attr)
        elif isinstance(node, ast.Name):
            if node.id in _BANNED_NAMES:
                hits.add(node.id)
    return sorted(hits)


def _cli_claim_options(src):
    """Sorted `add_argument` option strings in `src` that mention a claim.

    The lease has no argv path on purpose, and that absence is what keeps `docs/`
    claim-free structurally rather than by anyone remembering. Read from the AST so
    the reason can say the word.

    WHAT IT CANNOT SEE, under-counting in every case: an option that does not spell
    "claim" (`--lease`, `--live`), an option string built by concatenation, and any
    route to a lease that is not an `add_argument` at all. The behavioural case at
    the end of this suite covers the last of those for the command AS IT STANDS by
    loading what `main()` wrote; neither case can cover a caller reaching
    `generate(with_claim=True)` from Python by hand, and nothing in the tree
    compares the committed `docs/demo-large.html` to a fresh render byte for byte
    (CI asserts its CONTENT, deliberately, because the render stamps a wall-clock).
    So a lease could still reach a published page by that route, and this suite
    would stay green - which is the honest shape of the guarantee.
    """
    out = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "add_argument":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if "claim" in arg.value.lower():
                    out.add(arg.value)
    return sorted(out)


# --- cases --------------------------------------------------------------------
def _cases(check):
    m = M.generate(n_phases=12, n_tasks=6, seed=11)

    # determinism
    a = json.dumps(M.generate(n_phases=9, n_tasks=4, seed=11), sort_keys=True)
    b = json.dumps(M.generate(n_phases=9, n_tasks=4, seed=11), sort_keys=True)
    check("deterministic: two runs are byte-identical", a == b)
    check("seed changes the output",
          a != json.dumps(M.generate(n_phases=9, n_tasks=4, seed=12),
                          sort_keys=True))

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
    check("two reciprocal bug<->task links exist - the live one and the fixed "
          "one, which are closed by different rules", len(linked) == 2)
    unpaired = [b["id"] for b in linked
                if not [t for p in m["phases"] for t in p["tasks"]
                        if t["id"] == b["taskId"] and t.get("bugId") == b["id"]]]
    check("every linked task points back at its bug: %r" % (unpaired,),
          bool(linked) and unpaired == [])
    bst = {b["status"] for b in m["bugs"]}
    # The vocabulary, asked of the vocabulary. The literal set that stood here
    # named four of the five states and read as complete, so the fixture could
    # skip `fixed` — the only terminal state carrying evidence (`fixedIn`) —
    # and this case agreed with it.
    vocab = _loader.load_script("_manifest_vocab.py",
                                modname="manifest_vocab_demo_bugs")
    check("the bug lifecycle covers every state _manifest_vocab.BUG_STATUS "
          "defines, not a literal list that can fall behind it",
          bst == set(vocab.BUG_STATUS),
          "fixture=%r vocab=%r" % (sorted(bst), sorted(vocab.BUG_STATUS)))
    fixed = [b for b in m["bugs"] if b.get("status") == "fixed"]
    check("...and a fixed bug carries the commit that closed it, taken from the "
          "task it links to rather than invented",
          bool(fixed) and all(
              b.get("fixedIn")
              and b["fixedIn"] == ({t["id"]: t for p in m["phases"]
                                    for t in p["tasks"]}
                                   .get(b.get("taskId"), {})).get("commit")
              for b in fixed),
          repr([(b["id"], b.get("fixedIn")) for b in fixed]))

    # surfaces that need both states
    check("some tasks have skills and some do not",
          any("skills" in t for p in m["phases"] for t in p["tasks"])
          and any("skills" not in t for p in m["phases"] for t in p["tasks"]))
    # v0.37 B1: the fixture shows all three skill states - a list, the absent
    # key ("unconsidered"), and exactly one explicit null (the opt-out), so the
    # panel's opted-out chip and the needs-skills distinction have a live
    # subject in the committed screenshots.
    check("exactly one task is explicitly opted out of skills (null)",
          sum(1 for p in m["phases"] for t in p["tasks"]
              if "skills" in t and t["skills"] is None) == 1)
    check("every area declares a default skill, so the unresolved-skills "
          "advisory stays silent on a fixture meant to validate quietly",
          all(isinstance(v.get("skills"), list) and v["skills"]
              for v in m["meta"]["areas"].values()))
    # The review-skill chain is only observable if every level of it is present:
    # `phase.reviewSkill ?? areas[tag].reviewSkill ?? meta.reviewSkill`, plus the
    # explicit null that STOPS the fallback rather than deferring to it. Asked
    # through the product's own resolver, so this reads the rule rather than
    # restating it.
    areas_lib = _loader.load_script("_areas.py", modname="areas_demo_review")
    resolved = [areas_lib.resolve_review_skill(m, p) for p in m["phases"]]
    # Sources of a NAMED reviewer, not of any answer. Measured: the set of raw
    # sources was satisfied by the explicit null alone, so deleting every
    # phase-level override left this green - the case was reading the null as
    # proof that phases can override, which is the opposite of what it says.
    named_sources = {src for skill, src in resolved if skill}
    check("the demo exercises every level of the review-skill chain with a NAMED "
          "reviewer - phase override, area default and meta fallback",
          {"phase", "meta"} <= named_sources
          and any(str(s).startswith("area ") for s in named_sources),
          sorted(named_sources))
    check("...including the explicit null, which is the answer 'tests sign this "
          "one off' and not a missing value",
          any(skill is None and "reviewSkill" in p
              for (skill, _src), p in zip(resolved, m["phases"])))

    # `tests.add` and `tests.expectRedFirst` are one contract in two keys: the
    # same sentence in `add` means "must fail first" under tdd and "written after
    # the fix" under regression, and `expectRedFirst` is what says which.
    # `audit-task.py` writes `expectRedFirst = mode == "tdd"`; a fixture that
    # disagreed would document the opposite of what the product does. Presence
    # alone does not catch that - measured, by setting it to a constant False.
    _tests = [(t["id"], t["tests"]) for p in m["phases"] for t in p["tasks"]]
    _mismatched = [tid for tid, ts in _tests
                   if ts.get("expectRedFirst") != (ts.get("mode") == "tdd")]
    check("expectRedFirst agrees with the test mode on every task, the way "
          "/audit:task add writes the pair: %r" % (_mismatched[:5],),
          bool(_tests) and _mismatched == [])
    check("...and both values of expectRedFirst occur, so the pairing is "
          "observed rather than satisfied by one constant",
          {ts.get("expectRedFirst") for _tid, ts in _tests} == {True, False})
    # Every reviewer the fixture names must be a name the screenshot fixture's
    # HOME declares, which is `SKILL_POOL` (tools/capture-screenshots.mjs
    # BIG_USER_SKILLS). A reviewer outside the pool draws "discovery knows no
    # such skill" across the committed panel shots - a defect the fixture would
    # have invented for itself.
    named = {p["reviewSkill"] for p in m["phases"]
             if p.get("reviewSkill")} | {m["meta"]["reviewSkill"]} | {
        a["reviewSkill"] for a in m["meta"]["areas"].values()
        if a.get("reviewSkill")}
    outside = sorted(named - set(M.SKILL_POOL))
    check("every reviewSkill the fixture spells is in SKILL_POOL, the set the "
          "screenshot fixture's HOME declares: %r" % (outside,),
          bool(named) and outside == [])

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

    # The date printed beside a dollar figure is a CLAIM, and its basis is the
    # rate table the figure was priced from. This fixture declares no
    # `usage.pricing` of its own, so it is priced by the SHIPPED table, and the
    # only place that table's date is written down is hooks/_config.py's DEFAULTS.
    # Restating it here as a literal is deliberate - a derived date would move the
    # demo's bytes silently the day rates change, which is exactly the drift a
    # published artifact must not do quietly - so this case is what keeps the copy
    # honest. Measured before it existed: setting the literal to "2019-01-01" left
    # every suite in the tree green, with the demo page dating its costs eight
    # years off the table that produced them.
    hooks_cfg = _loader.load_hooks_config(modname="hooks_config_demo_rates")
    shipped_as_of = (hooks_cfg.DEFAULTS.get("usage") or {}).get("pricingAsOf")
    demo_as_of = (m["meta"].get("usage") or {}).get("pricingAsOf")
    check("the demo dates its rates to the SHIPPED table's own pricingAsOf - it "
          "declares no pricing table of its own, so any other date prints a basis "
          "the numbers did not come from",
          bool(shipped_as_of) and demo_as_of == shipped_as_of,
          "demo=%r shipped=%r" % (demo_as_of, shipped_as_of))

    # --- schema coverage (F35) ---------------------------------------------
    # The fixture is what the project SHOWS, so a schema field it never carries
    # is a feature nobody sees working. Measured before this existed: 129 fields
    # defined, 75 carried, 54 missing - and nothing in the tree could say so.
    # The field set comes out of the schema FILE, so a field added there tomorrow
    # arrives here as a gap rather than passing forever.
    schema = M.load_schema()
    cov = M.schema_coverage(m, schema)
    # Vacuity first, and it is not ceremony: every case below is a set
    # comparison, and all of them pass over an empty schema. A filter that
    # narrowed to nothing would read as "all clear".
    check("the coverage lint reads a schema that actually declares fields - "
          "an empty field set makes every case below vacuously green",
          len(cov["defined"]) > 100, len(cov["defined"]))
    check("...and it observes the fixture rather than the schema twice over",
          len(cov["covered"]) > 100,
          "covered=%d of %d" % (len(cov["covered"]), len(cov["defined"])))
    check("every schema field the demo fixture does not carry has an explicit, "
          "reasoned exemption in gen-demo-manifest.SCHEMA_EXEMPTIONS: %r"
          % (cov["gaps"],), cov["gaps"] == [])
    check("...and no exemption is stale - one naming a field the schema dropped, "
          "or one the fixture now carries, is a reason nobody pays: %r"
          % (cov["stale"],), cov["stale"] == [])
    _mute = sorted(k for k, v in M.SCHEMA_EXEMPTIONS.items()
                   if not (isinstance(v, str) and len(v.strip()) >= 40))
    check("every exemption states a reason, not a shrug: %r" % (_mute,),
          bool(M.SCHEMA_EXEMPTIONS) and _mute == [])
    # The property that makes the lint worth having, asked directly: a field
    # ADDED to the schema must arrive as a gap. Asked with a doctored copy of
    # the real schema rather than by editing the file, because the claim is
    # about the derivation being live - a lint built from a snapshot of today's
    # fields would pass this suite for ever while the schema moved underneath it.
    _grown = json.loads(json.dumps(schema))
    _grown["$defs"]["phase"]["properties"]["hypotheticalNewField"] = {"type": "string"}
    _grown_gaps = M.schema_coverage(m, _grown)["gaps"]
    # Stated as a DIFFERENCE rather than as an equality against the whole gap
    # list: an equality here goes red for every unrelated gap as well, which
    # makes it a second copy of the case above instead of an independent one.
    check("a field added to the schema arrives as an unexplained gap - the field "
          "set is read from the schema, not snapshotted",
          sorted(set(_grown_gaps) - set(cov["gaps"]))
          == ["phase.hypotheticalNewField"], repr(_grown_gaps[:4]))
    # ...and the mirror: a field REMOVED from the schema must strand its
    # exemption rather than leaving a reason nobody reads.
    _shrunk = json.loads(json.dumps(schema))
    del _shrunk["$defs"]["phase"]["properties"]["reviewFindings"]
    check("a field dropped from the schema strands its exemption",
          "phase.reviewFindings" in M.schema_coverage(m, _shrunk)["stale"],
          repr(M.schema_coverage(m, _shrunk)["stale"]))

    # A parked proposal's `payload` is a whole phase, `$ref`s and all, so a walk
    # that ENTERED it would let a phase nobody runs answer for the live plan.
    # Measured before OPAQUE_FIELDS existed: deleting `tests.add` from every live
    # task left the lint green, because the payload still carried one. Asked on a
    # copy, because the claim is about the walk rather than today's fixture.
    _hollow = json.loads(json.dumps(m))
    for _p in _hollow["phases"]:
        for _t in _p["tasks"]:
            (_t.get("tests") or {}).pop("add", None)
    check("a parked proposal's payload does not answer for the live plan - the "
          "walk records `proposal.payload` and does not enter it",
          "tests.add" in M.schema_coverage(_hollow, schema)["gaps"],
          repr(M.schema_coverage(_hollow, schema)["gaps"][:4]))
    _payload_tasks = [_t for _x in _hollow["proposals"]
                      for _t in (((_x.get("payload") or {}).get("phase") or {})
                                 .get("tasks") or [])]
    check("...and the payload still carries the field that was stripped, so the "
          "case above is about the walk and not about an empty payload",
          bool(_payload_tasks)
          and any("add" in (_t.get("tests") or {}) for _t in _payload_tasks))

    # The owner rule, asserted from the other side: an inline object's keys
    # (meta.ado's `organization`, meta.usage's `showCost`) belong to no named
    # def, and attributing them to the parent would report coverage of `meta`
    # fields the schema never declared.
    _stray = sorted(M.manifest_fields(m, schema) - set(cov["defined"]))
    check("the walker attributes nothing the schema does not declare - inline "
          "objects contribute no fields to their parent: %r" % (_stray,),
          _stray == [])

    # --- the lease, and the exemption that holds it back (F48) --------------
    # `phase.claim` and its fields are the one region SCHEMA_EXEMPTIONS holds
    # back on POLICY: the default output is rendered into committed artifacts,
    # so a lease there publishes a demo permanently held by a session that does
    # not exist and `claim.host` publishes whoever generated it. That reason is
    # about publishing, and nothing showed it was about publishing rather than
    # about the generator being unable to produce a claim at all - while
    # `_manifest_phases._check_claim` had no fixture that reached it: its first
    # statement is `if "claim" not in phase: return`, so the validator's walk
    # over this fixture entered and returned on every phase at every size.
    _claim_exempt = sorted(k for k in M.SCHEMA_EXEMPTIONS
                           if k == "phase.claim" or k.startswith("claim."))
    _claimed = M.generate(n_phases=12, n_tasks=6, seed=11, with_claim=True)
    _claim_cov = M.schema_coverage(_claimed, schema)
    _newly = sorted(set(_claim_cov["covered"]) - set(cov["covered"]))
    check("with_claim covers EXACTLY the %d schema field(s) SCHEMA_EXEMPTIONS "
          "holds back for the lease and nothing else, which is what makes the "
          "exemption a policy about the published artifact rather than a gap in "
          "the generator: %r" % (len(_claim_exempt), _newly),
          bool(_claim_exempt) and _newly == _claim_exempt,
          "exempt=%r" % (_claim_exempt,))
    check("...and every one of those exemptions goes STALE against that same "
          "document, which is why coverage is measured on the DEFAULT fixture: "
          "an exemption for a field the fixture carries is a reason nobody pays",
          sorted(_claim_cov["stale"]) == _claim_exempt, _claim_cov["stale"])

    # Determinism, both halves. The lease must not draw from `rng`, and it must
    # not move a byte of the default run - `docs/demo-large.html` (ci.yml's
    # 40x5 scale demo) and the `docs/screenshots/panel-*` set are rendered from
    # that run and are committed.
    check("with_claim is deterministic: two runs are byte-identical",
          json.dumps(M.generate(n_phases=9, n_tasks=4, seed=11, with_claim=True),
                     sort_keys=True)
          == json.dumps(M.generate(n_phases=9, n_tasks=4, seed=11,
                                   with_claim=True), sort_keys=True))
    _bare = json.loads(json.dumps(_claimed))
    _dropped = 0
    for _p in _bare["phases"]:
        _dropped += 1 if _p.pop("claim", None) is not None else 0
    check("...and it moves no default byte: dropping the %d lease(s) from a "
          "with_claim run reproduces the default run exactly, so nothing "
          "rendered from this fixture into docs/ moves" % (_dropped,),
          _dropped > 0
          and json.dumps(_bare, sort_keys=True) == json.dumps(m, sort_keys=True))

    _leased = [p for p in _claimed["phases"] if "claim" in p]
    check("exactly one phase holds the lease and it is the LIVE one - a claim "
          "on a finished phase is the stale-claim warning, not the feature: %r"
          % ([(p["id"], p["status"]) for p in _leased],),
          len(_leased) == 1 and _leased[0]["status"] == "in_progress")
    _lease = _leased[0]["claim"]
    _starts = sorted(t["startedAt"] for t in _leased[0]["tasks"]
                     if t.get("startedAt"))
    check("...and every value has a basis: the branch is the phase's own, `at` "
          "is its own earliest task start, and the host is the reserved "
          "RFC 2606 .invalid name that resolves to nobody",
          _lease["branch"] == _leased[0].get("branch")
          and bool(_starts) and _lease["at"] == _starts[0]
          and _lease["host"] == M.CLAIM_HOST
          and M.CLAIM_HOST.endswith(".invalid"), repr(_lease))
    check("...and `_claim_for` refuses a phase with no basis rather than "
          "filling one in - no started task, and no branch to name",
          M._claim_for({"id": "P1", "status": "in_progress", "branch": "b",
                        "tasks": [{"id": "P1.1"}]}) is None
          and M._claim_for({"id": "P1", "status": "in_progress",
                            "tasks": [{"id": "P1.1", "startedAt": "x"}]}) is None
          and M._claim_for({"id": "P1", "status": "done", "branch": "b",
                            "tasks": [{"id": "P1.1", "startedAt": "x"}]}) is None)
    _stamp_err = None
    try:
        M._stamp_claims([{"id": "P1", "status": "pending", "tasks": []}])
    except ValueError as exc:                      # the documented contract
        _stamp_err = str(exc)
    check("...and stamping nothing is an ERROR, not an empty list: a "
          "claim-free manifest returned under with_claim would make every case "
          "above assert a path nothing entered",
          bool(_stamp_err) and "no basis" in _stamp_err, repr(_stamp_err))

    # `claim.host` is the one field of a lease that would publish whoever ran
    # the generator, and "we were careful" is not a property. Read the source.
    _gdm_src = open(_loader.script_path("gen-demo-manifest.py"),
                    encoding="utf-8").read()
    check("the source scanner sees a machine read when there is one, and does "
          "not invent one - the measurement that makes the case below mean "
          "something rather than being an empty parse",
          _machine_reads("import socket\nh = socket.gethostname()\n")
          == ["gethostname", "socket"]
          and _machine_reads("import datetime\nx = datetime.datetime.utcnow()\n")
          == ["utcnow"]
          and _machine_reads("import datetime\nd = datetime.timedelta(days=1)\n")
          == [])
    _reads = _machine_reads(_gdm_src)
    check("...and gen-demo-manifest.py performs none of them, so `claim.host` "
          "CANNOT publish the machine that generated the fixture and no "
          "timestamp anywhere comes from the clock: %r" % (_reads,),
          _reads == [])
    _cli_claim = _cli_claim_options(_gdm_src)
    check("no argv reaches the lease: every committed artifact goes through "
          "main() (ci.yml's scale-demo step, tools/capture-screenshots.mjs), so "
          "the absence of a flag is what keeps docs/ claim-free structurally "
          "rather than by habit: %r" % (_cli_claim,), _cli_claim == [])
    check("...and the scanner would see such a flag if one were added - it "
          "reads add_argument's own option strings, so this is a measurement",
          _cli_claim_options(
              "p.add_argument('--with-claim', action='store_true')\n")
          == ["--with-claim"])

    # F34: every phase declares the tier its orchestrator runs at. Without it
    # `gen-demo-usage` mapped `None` through `TIER_TO_MODEL.get(tier,
    # DEFAULT_MODEL)` and all 148 orchestrator rows in the 40x5 demo printed
    # `claude-sonnet-5` as though the manifest had chosen it - a model
    # attribution produced by a fallback, which is a claim with no basis.
    _tierless = [p["id"] for p in m["phases"] if not p.get("model")]
    check("every phase declares phase.model, so no orchestrator ledger row is "
          "attributed by gen-demo-usage's DEFAULT_MODEL fallback: %r"
          % (_tierless[:5],),
          len(m["phases"]) > 1 and _tierless == [])
    # ...and it is a DERIVED tier, not a constant: the phase declares the tier
    # its TYPICAL task needs, which a task's own `model` then overrides. A
    # generator that stamped one literal on every phase satisfies the case above
    # and puts the fallback back by hand.
    _by_phase = {p["id"]: p["model"] for p in m["phases"]}
    _expected = {p["id"]: M.RISK_MODEL[max(
        M.RISKS, key=lambda r, ts=p["tasks"]: (
            [t["risk"] for t in ts].count(r), M.RISKS.index(r)))]
        for p in m["phases"]}
    check("phase.model is the modal risk of the phase's own tasks - a basis, "
          "not a default", _by_phase == _expected,
          repr(sorted(k for k in _expected if _by_phase.get(k) != _expected[k])))
    # The measurement that sent the first basis back: "the riskiest task" is
    # also derived, and at five tasks per phase it answered `opus` for all 40 —
    # as uniform as the fallback it replaced. A derived value that answers the
    # same for everybody has become a constant again, so the spread is pinned.
    check("...and the fixture spans more than one orchestrator tier, so the "
          "by-model chart has something to separate",
          len(set(_by_phase.values())) > 1, sorted(set(_by_phase.values())))
    _big = M.generate(n_phases=40, n_tasks=5, seed=11)
    _big_tiers = sorted({p["model"] for p in _big["phases"]})
    check("...at the 40x5 scale the published demo is rendered from, too - "
          "where the first basis tried collapsed to a single tier",
          len(_big_tiers) > 1, _big_tiers)

    # haiku is never routed to high risk
    check("no high-risk task is routed to haiku",
          not [t for p in m["phases"] for t in p["tasks"]
               if t.get("risk") == "high" and t.get("model") == "haiku"])

    # small-N edge: all four statuses still representable
    tiny = M.generate(n_phases=3, n_tasks=1, seed=11)
    check("edge: 3 phases still yield 3 distinct phase statuses",
          len({p["status"] for p in tiny["phases"]}) == 3)

    # round-trip through the real loader + the real validator
    tmp = tempfile.mkdtemp(prefix="gen-demo-manifest-selftest-")
    try:
        written = M.write_manifest(m, tmp)
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
        mio = M._load_manifest_io()
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

        # --- F48: the claim path, end to end ----------------------------
        # generate -> split into shards -> load back -> the real validator's
        # walk. This is the leg nothing had: `_check_claim` returns on its
        # first line when a phase carries no claim, so the walk above proves
        # only that it was called.
        cdir = os.path.join(tmp, "leased")
        M.write_manifest(_claimed, cdir)
        cidx = json.load(open(os.path.join(cdir, "audit-plan.json"),
                              encoding="utf-8"))
        _stub_claims = [p.get("id") for p in cidx["phases"] if "claim" in p]
        check("the lease is written into the phase SHARD and not mirrored onto "
              "the index stub - that is what makes a same-phase double-claim a "
              "shard merge conflict instead of a silent overwrite: %r"
              % (_stub_claims,), _stub_claims == [])
        _shard_rel = [p["shard"] for p in cidx["phases"]
                      if p.get("id") == _leased[0]["id"]]
        _shard = json.load(open(os.path.join(cdir, _shard_rel[0]),
                                encoding="utf-8"))
        check("...and the shard body carries it, which is the round-trip leg "
              "the hand-built stub fixture in test__manifest_io.py does not "
              "take", bool(_shard_rel)
              and (_shard.get("claim") or {}).get("host") == M.CLAIM_HOST,
              repr(_shard.get("claim")))

        cback = mio.load_manifest(os.path.join(cdir, "audit-plan.json"))
        _held = [p for p in cback["phases"] if p.get("claim")]
        cf, cw = vm.validate(cback)
        check("the lease survives the split and reassembly and the real "
              "validator walks it clean: %d phase(s) claimed, %d finding(s), "
              "%d warning(s)" % (len(_held), len(cf), len(cw)),
              len(_held) == 1 and not cf and not cw,
              "; ".join((cf + cw)[:3]))

        # A clean walk over a lease and a clean walk over no lease print the
        # same nothing, so the case above is only evidence if the SAME document
        # goes red when the lease goes wrong. Two controls, one per branch of
        # `_check_claim` a demo fixture can reach.
        _stale_doc = json.loads(json.dumps(cback))
        _finished = [p for p in _stale_doc["phases"] if p["status"] == "done"]
        _finished[0]["claim"] = dict(_held[0]["claim"])
        _sf, _sw = vm.validate(_stale_doc)
        check("...control: the same lease on a DONE phase draws the stale-claim "
              "warning - which is exactly what a committed fixture would "
              "publish, and the reason SCHEMA_EXEMPTIONS holds phase.claim back",
              bool(_finished) and not _sf
              and len(_sw) == 1 and "stale claim" in _sw[0],
              "; ".join((_sf + _sw)[:3]))
        _thin_doc = json.loads(json.dumps(cback))
        _thin = [p for p in _thin_doc["phases"] if p.get("claim")][0]
        del _thin["claim"]["host"]
        _tf, _tw = vm.validate(_thin_doc)
        check("...control: dropping `host` from the round-tripped lease draws "
              "exactly one warning naming it, so the clean result above is a "
              "walk that ENTERED `_check_claim` rather than one that returned "
              "on its first line",
              not _tf and len(_tw) == 1 and "claim is missing host" in _tw[0],
              "; ".join((_tf + _tw)[:3]))

        single = M.write_manifest(M.generate(n_phases=4, n_tasks=2, seed=11),
                                  os.path.join(tmp, "flat"), single_file=True)
        check("--single-file writes one manifest plus the config", len(single) == 2)
        flat = json.load(open(single[0], encoding="utf-8"))
        check("--single-file is meta.version 2", flat["meta"]["version"] == 2)
        f2, w2 = vm.validate(flat)
        check("the single-file form also validates clean", not f2 and not w2,
              "; ".join((f2 + w2)[:3]))

        check("CLI exits 2 on --phases 0", M.main([tmp, "--phases", "0"]) == 2)
        cli_dir = os.path.join(tmp, "cli")
        check("CLI exits 0 on a normal run",
              M.main([cli_dir, "--phases", "5", "--tasks", "3"]) == 0)
        # The behavioural half of "no argv reaches the lease": the AST case
        # above says no flag exists, this says the command as it stands writes
        # a claim-free fixture. Both, because a flag is not the only way one
        # could arrive.
        cli_doc = mio.load_manifest(os.path.join(cli_dir, "audit-plan.json"))
        cli_claims = [p["id"] for p in cli_doc["phases"] if p.get("claim")]
        check("...and what it wrote holds no lease, which is the property "
              "every committed artifact depends on: %r" % (cli_claims,),
              bool(cli_doc["phases"]) and cli_claims == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_gen_demo_manifest.py --selftest\n")
    raise SystemExit(2)
