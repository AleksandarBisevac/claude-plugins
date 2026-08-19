#!/usr/bin/env python3
"""
The cases for `gen-demo-usage.py`, moved out of it - the entry-point shape.

Hyphenated, so the file name substitutes underscores and the module comes through
`_loader.load_script`; see `test_migrate_manifest.py` for that rule. `M` is the
module under test - and here, as there, there is nothing else to spell, because
`load_script` hands back a module object.

`ul` is `usage_ledger`, reached through `M._load_ledger_lib()` rather than imported
here: that helper is the module's own way of loading it (`cache=False`, its own
modname), and the cases assert the generator's output against the SAME reader the
generator's callers use.

Every path in this suite is either a literal fixture or lives under one
`tempfile.mkdtemp()`, removed in `finally`. Nothing is derived from this file's
own location.

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

M = _loader.load_script("gen-demo-usage.py", modname="gen_demo_usage")


# --- cases --------------------------------------------------------------------
def _cases(check):
    ul = M._load_ledger_lib()
    manifest = {
        "meta": {"version": 2, "repo": "demo"},
        "phases": [
            {"id": "P1", "title": "Alpha", "model": "opus", "tasks": [
                {"id": "P1.1", "status": "done", "risk": "high", "model": "opus",
                 "attempts": 1, "startedAt": "2026-06-02T09:00:00Z",
                 "completedAt": "2026-06-02T15:00:00Z"},
                {"id": "P1.2", "status": "done", "risk": "low", "model": "haiku",
                 "attempts": 1, "startedAt": "2026-06-08T10:00:00Z",
                 "completedAt": "2026-06-08T12:00:00Z"}]},
            {"id": "P2", "title": "Beta", "model": "sonnet", "tasks": [
                {"id": "P2.1", "status": "blocked", "risk": "med", "model": "sonnet",
                 "attempts": 3, "startedAt": "2026-07-13T09:00:00Z"},
                {"id": "P2.2", "status": "pending", "risk": "low", "model": "haiku"}]},
        ],
    }

    rows_a = M.generate(manifest, seed=7, adhoc_days=2)
    rows_b = M.generate(manifest, seed=7, adhoc_days=2)
    check("determinism: two runs are byte-identical",
          json.dumps(rows_a, sort_keys=True) == json.dumps(rows_b, sort_keys=True))
    check("determinism: a different seed gives different output",
          json.dumps(M.generate(manifest, seed=8, adhoc_days=2), sort_keys=True)
          != json.dumps(rows_a, sort_keys=True))

    task_ids = {t["id"] for p in manifest["phases"] for t in p["tasks"]}
    phase_ids = {p["id"] for p in manifest["phases"]}
    check("integrity: every taskId exists in the manifest",
          all(r["taskId"] in task_ids for r in rows_a if r["taskId"]))
    check("integrity: every phaseId exists in the manifest",
          all(r["phaseId"] in phase_ids for r in rows_a if r["phaseId"]))
    check("integrity: pending tasks (no startedAt) spend nothing",
          not any(r["taskId"] == "P2.2" for r in rows_a))

    windows = {"P1.1": ("2026-06-02T09", "2026-06-02T15")}
    inside = [r for r in rows_a if r["taskId"] == "P1.1"]
    check("integrity: rows land inside the task's own window",
          inside and all(windows["P1.1"][0] <= r["ts"] <= windows["P1.1"][1]
                         for r in inside))

    models = {r["model"] for r in rows_a}
    check("shape: manifest tiers map to concrete ledger model ids",
          "claude-opus-5" in models and "claude-haiku-4-5" in models
          and not any(m in ("opus", "haiku", "sonnet") for m in models))

    # The two generators share a VOCABULARY as well as a cast. `gen-demo-manifest`
    # stamps a TIER on every task; this file maps it through
    # `TIER_TO_MODEL.get(tier, DEFAULT_MODEL)`, which cannot fail. A tier it has
    # never heard of is not an error - it is a row relabelled DEFAULT_MODEL - so a
    # drift between the two files crashes nothing and leaves the demo's by-model
    # chart quietly wrong. Measured before this case existed: mutating
    # `RISK_MODEL["high"]` from "opus" to "mythos" kept every suite in the tree
    # green while 132 opus rows became sonnet and the demo's total spend fell from
    # $414.28 to $291.66. The cast has `_demo_cast` and a case; the vocabulary had
    # neither.
    gdm = _loader.load_script("gen-demo-manifest.py",
                              modname="gen_demo_manifest_tiers")
    demo_manifest = gdm.generate(n_phases=8, n_tasks=3, seed=11)
    tiers = sorted({t.get("model") for p in demo_manifest["phases"]
                    for t in p["tasks"] if t.get("model")})
    unmapped = [t for t in tiers if t not in M.TIER_TO_MODEL]
    check("agreement: every tier the demo manifest stamps is one this generator "
          "maps - an unmapped tier is silently relabelled %s, never an error"
          % (M.DEFAULT_MODEL,),
          bool(tiers) and unmapped == [],
          "tiers=%r unmapped=%r" % (tiers, unmapped))

    # ...and every id it can emit must price at its OWN row. `rates_for` falls
    # back to `_default`, which is Opus-tier on purpose, so a renamed or retired
    # model id does not fail either - it silently re-prices the demo UPWARD
    # (mutating "claude-sonnet-5" to "claude-sonnet-6" took the same fixture from
    # $414.28 to $461.08 with every suite green, because "cost is priced per row
    # and non-zero" above is satisfied by the fallback). Asked through the real
    # resolver rather than by looking the key up here, so a dated id like
    # `claude-haiku-4-5-20251001` still counts as priced; identity against the
    # `_default` ROW is what separates the two, because its numbers are EQUAL to
    # Opus's and a value comparison would call the fallback a match.
    fallback = ul.DEFAULT_PRICING["_default"]
    emitted = sorted(set(M.TIER_TO_MODEL.values()) | set([M.DEFAULT_MODEL]))
    unpriced = [mid for mid in emitted if ul.rates_for(mid) is fallback]
    check("pricing: every model id this generator can emit resolves to its own "
          "rate row - one that does not lands on the Opus-tier `_default` and "
          "overstates the demo's spend without failing anything",
          bool(emitted) and unpriced == [],
          "emitted=%r unpriced=%r" % (emitted, unpriced))
    check("shape: more than one author appears",
          len({r["author"] for r in rows_a}) > 1)
    check("shape: an author is stable for a given task",
          len({r["author"] for r in rows_a if r["taskId"] == "P1.1"}) == 1)
    attrs = {r["attr"] for r in rows_a}
    check("shape: task, phase and unattributed buckets all present",
          {"task", "phase", "unattributed"} <= attrs, repr(attrs))

    by_task = ul.aggregate([r for r in rows_a if r["attr"] == "task"], "task")
    check("shape: a 3-attempt task generates more OUTPUT than a low-risk 1-attempt one",
          by_task["P2.1"]["out"] > by_task["P1.2"]["out"])
    # Worth pinning, because it is counter-intuitive and it constrains how the
    # dashboards may present things: cache-read volume dwarfs every other tier, so
    # a well-cached small task can out-TOTAL a heavy retried one. Raw token totals
    # are therefore not a valid cross-task comparator — output tokens and cost are.
    check("shape: raw totals can invert across cache regimes (why cost is the comparator)",
          by_task["P1.2"]["tokens"] > by_task["P2.1"]["tokens"]
          and by_task["P1.2"]["out"] < by_task["P2.1"]["out"],
          "P1.2 tok=%d out=%d vs P2.1 tok=%d out=%d" % (
              by_task["P1.2"]["tokens"], by_task["P1.2"]["out"],
              by_task["P2.1"]["tokens"], by_task["P2.1"]["out"]))

    p2 = [r for r in rows_a if r["phaseId"] == "P2" and r["attr"] == "task"]
    p1 = [r for r in rows_a if r["phaseId"] == "P1" and r["attr"] == "task"]
    check("shape: the blocked phase has a visibly degraded cache hit rate",
          ul.totals(p2)["cacheHitPct"] < ul.totals(p1)["cacheHitPct"] - 20,
          "P2 %.1f vs P1 %.1f" % (ul.totals(p2)["cacheHitPct"],
                                  ul.totals(p1)["cacheHitPct"]))
    check("shape: cost is priced per row and non-zero",
          all(r["costUSD"] > 0 for r in rows_a))

    tmp = tempfile.mkdtemp(prefix="gen-demo-usage-selftest-")
    try:
        written = M.write_ledger(rows_a, tmp)
        check("io: monthly files written", len(written) == 2)
        back = ul.read_ledger(tmp)
        check("io: round-trips through the real ledger reader",
              ul.totals(back)["tokens"] == ul.totals(rows_a)["tokens"])
        first = open(written[0], encoding="utf-8").read()
        M.write_ledger(M.generate(manifest, seed=7, adhoc_days=2), tmp)
        check("io: regenerating produces an identical file (no diff churn)",
              open(written[0], encoding="utf-8").read() == first)

        empty = {"meta": {}, "phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "pending"}]}]}
        check("edge: a manifest with no started tasks yields no rows",
              M.generate(empty) == [])
        check("edge: CLI exits 2 on a manifest that cannot produce rows",
              M.main([os.path.join(tmp, "nope.json")]) == 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_gen_demo_usage.py --selftest\n")
    raise SystemExit(2)
