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

import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("gen-demo-manifest.py", modname="gen_demo_manifest")


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

        single = M.write_manifest(M.generate(n_phases=4, n_tasks=2, seed=11),
                                  os.path.join(tmp, "flat"), single_file=True)
        check("--single-file writes one manifest plus the config", len(single) == 2)
        flat = json.load(open(single[0], encoding="utf-8"))
        check("--single-file is meta.version 2", flat["meta"]["version"] == 2)
        f2, w2 = vm.validate(flat)
        check("the single-file form also validates clean", not f2 and not w2,
              "; ".join((f2 + w2)[:3]))

        check("CLI exits 2 on --phases 0", M.main([tmp, "--phases", "0"]) == 2)
        check("CLI exits 0 on a normal run",
              M.main([os.path.join(tmp, "cli"), "--phases", "5", "--tasks", "3"]) == 0)
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
