#!/usr/bin/env python3
"""
Synthetic usage ledger for demos, screenshots and CI — dependency-free (stdlib only).

The audit examples ship a manifest but no spend, so every usage chart rendered
against them is empty and every screenshot shows a feature that looks broken. This
generates a ledger that is *consistent with a real manifest*: task ids that exist,
phase ids that exist, and timestamps inside each task's own startedAt/completedAt
window. Point it at `examples/acme-store/audit-plan.json` and the report's Usage
section fills with something worth looking at.

It is also the fixture that lets CI render the example and assert the section is
actually there, rather than only asserting the output file is non-empty.

DETERMINISTIC BY CONSTRUCTION. A fixed seed, no wall-clock, no unseeded random.
Two runs produce byte-identical output, so the committed ledger is reviewable in a
diff and a regeneration that changes nothing shows as no change. `--selftest` pins
that, along with referential integrity against the manifest.

    gen-demo-usage.py <manifest> [--out-dir DIR] [--seed N] [--authors a,b,c]
                                 [--adhoc-days N] [--stdout] [--selftest]

MANIFEST TIERS vs LEDGER MODEL IDS. A manifest records a *tier* ("opus") because
`meta.model` is documented as illustrative and provider-agnostic; a transcript
records the concrete id Claude Code actually ran ("claude-opus-5"). This generator
maps the former to the latter exactly as the runtime does, which is why analytics
must join on taskId and read the model from the LEDGER — never map tiers.
"""
import argparse
import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


def _load_ledger_lib():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "usage_ledger", os.path.join(_HERE, "usage_ledger.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_manifest_io():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_manifest_io", os.path.join(_HERE, "_manifest_io.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Manifest tier -> the concrete model id a transcript would record.
TIER_TO_MODEL = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5",
}
DEFAULT_MODEL = "claude-sonnet-5"

DEFAULT_AUTHORS = ("alex@acme.example", "sara@acme.example", "milos@acme.example")

# Rough per-hour token shape, scaled by task risk. Cache read dominates because a
# stable prompt prefix is the normal case — that is what makes the cache-hit tile
# read ~95%+ on a healthy run.
RISK_SCALE = {"high": 2.2, "med": 1.0, "low": 0.45, None: 1.0}


def _hours(ul, start_iso, end_iso, fallback_hours=6):
    """Hour buckets covering a task window, inclusive of the start hour."""
    start = ul.parse_ts(start_iso)
    if start is None:
        return []
    end = ul.parse_ts(end_iso) if end_iso else None
    if end is None or end < start:
        end = start + fallback_hours * 3600
    out, t = [], start
    while t <= end:
        bucket = ul.hour_bucket(_iso(t))
        if bucket and (not out or out[-1] != bucket):
            out.append(bucket)
        t += 3600
    return out


def _iso(epoch):
    import time as _t
    g = _t.gmtime(epoch)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        g.tm_year, g.tm_mon, g.tm_mday, g.tm_hour, g.tm_min, g.tm_sec)


def _counts(rng, scale, cache_hit=0.97):
    """One hour of plausible spend. `cache_hit` is the share of INPUT volume served
    from cache — dropping it is what makes a phase's cache tile visibly collapse."""
    out = int(rng.uniform(3_000, 22_000) * scale)
    fresh_in = int(rng.uniform(200, 1_600) * scale)
    written = int(rng.uniform(8_000, 60_000) * scale)
    # solve read from the target hit rate: read / (read + fresh + written) = hit
    billed_uncached = fresh_in + written
    read = int(billed_uncached * cache_hit / max(1e-6, 1.0 - cache_hit))
    w1h = int(written * rng.uniform(0.0, 0.7))
    return {"in": fresh_in, "out": out, "cacheW5m": written - w1h,
            "cacheW1h": w1h, "cacheR": read}


def _author_for(key, authors):
    """Stable author per task — the same task always belongs to the same person, so
    regenerating never reshuffles the by-author chart."""
    return authors[sum(ord(c) for c in str(key)) % len(authors)]


def generate(manifest, seed=7, authors=DEFAULT_AUTHORS, adhoc_days=0, repo="demo"):
    """Return ledger rows for `manifest`. Pure: no I/O, no clock."""
    ul = _load_ledger_lib()
    rng = random.Random(seed)
    rows = []

    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    # One phase gets a degraded cache rate so that chart has a story: the phase
    # holding a blocked task, where repeated retries churned the prompt prefix.
    churned = None
    for ph in phases:
        if any(isinstance(t, dict) and t.get("status") == "blocked"
               for t in (ph.get("tasks") or [])):
            churned = ph.get("id")
            break

    def emit(bucket, phase_id, task_id, attr, tier, author, agent_type,
             agent_id, scale, hit):
        counts = _counts(rng, scale, hit)
        row = {
            "ts": bucket, "author": author, "sessionId": "sess-%s" % (phase_id or "adhoc"),
            "agentId": agent_id, "agentType": agent_type,
            "phaseId": phase_id, "taskId": task_id, "attr": attr,
            "model": TIER_TO_MODEL.get(tier, DEFAULT_MODEL),
            "branch": ("audit/%s" % phase_id.lower()) if phase_id else "main",
            "repo": repo, "msgs": rng.randint(2, 9),
        }
        row.update(counts)
        row["costUSD"] = round(ul.price(counts, row["model"]), 6)
        rows.append(row)

    for ph in phases:
        pid = ph.get("id")
        hit = 0.62 if pid == churned else rng.uniform(0.94, 0.985)
        for task in (ph.get("tasks") or []):
            if not isinstance(task, dict) or not task.get("startedAt"):
                continue          # pending tasks have not spent anything yet
            tid = task.get("id")
            author = _author_for(tid, authors)
            scale = RISK_SCALE.get(task.get("risk"), 1.0)
            # A retried task really did burn more: scale by attempts.
            attempts = task.get("attempts") or 1
            scale *= 1.0 + 0.55 * max(0, int(attempts) - 1)
            buckets = _hours(ul, task.get("startedAt"), task.get("completedAt"))
            for i, bucket in enumerate(buckets):
                emit(bucket, pid, tid, "task", task.get("model"), author,
                     "audit-executor", "a%s%d" % (str(tid).replace(".", ""), i),
                     scale, hit)
                # the orchestrator's own turns around each task
                if i % 3 == 0:
                    emit(bucket, pid, None, "phase", ph.get("model"), author,
                         None, None, 0.30, hit)

    # A slice of genuinely off-pipeline work (ad-hoc edits, #no-plan). This is not
    # decoration: it is what keeps the attribution-coverage tile from reading a
    # fake 100%, and it is spread across the WHOLE span rather than only on days a
    # task ran — because ad-hoc work is continuous while phase work is bursty. It
    # also rotates the model, since an ad-hoc session uses whatever model is
    # configured, which is how the cheaper tiers show up at all when every low-risk
    # task in the manifest is still pending.
    if adhoc_days > 0 and rows:
        ul_local = _load_ledger_lib()
        days = sorted({r["ts"][:10] for r in rows})
        first, last = ul_local.parse_ts(days[0] + "T00:00:00Z"), \
            ul_local.parse_ts(days[-1] + "T00:00:00Z")
        span_days = max(1, int((last - first) / 86400))
        step = max(1, span_days // adhoc_days)
        tiers = ("haiku", "sonnet", "opus", "haiku", "fable")
        for i in range(adhoc_days):
            day = _iso(first + i * step * 86400)[:10]
            for j, hour in enumerate((11, 16)):
                emit("%sT%02d" % (day, hour), None, None, "unattributed",
                     tiers[(i * 2 + j) % len(tiers)],
                     authors[(i + j) % len(authors)], None, None,
                     0.35, 0.90)

    rows.sort(key=lambda r: (r["ts"], r.get("phaseId") or "~",
                             r.get("taskId") or "~", r["model"]))
    return rows


def write_ledger(rows, out_dir):
    """Write rows to monthly NDJSON, replacing whatever was there. Sorted and
    compact so a regeneration diff shows only real changes."""
    ul = _load_ledger_lib()
    by_month = {}
    for row in rows:
        by_month.setdefault(ul.bucket_month(row["ts"]), []).append(row)
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for month, group in sorted(by_month.items()):
        path = os.path.join(out_dir, "%s.jsonl" % month)
        with open(path, "w", encoding="utf-8") as fh:
            for row in group:
                fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
        written.append(path)
    return written


def main(argv):
    ap = argparse.ArgumentParser(
        prog="gen-demo-usage.py",
        description="Generate a deterministic synthetic usage ledger for a manifest.")
    ap.add_argument("manifest")
    ap.add_argument("--out-dir", default=None,
                    help="default: <manifest dir>/.claude/usage")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--authors", default=",".join(DEFAULT_AUTHORS))
    ap.add_argument("--adhoc-days", type=int, default=18,
                    help="sampling points of off-pipeline (unattributed) work across the\n                          span. The default reproduces the committed example ledger.")
    ap.add_argument("--stdout", action="store_true",
                    help="print rows instead of writing files")
    args = ap.parse_args(argv)

    mio = _load_manifest_io()
    try:
        manifest = mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read %s: %s\n" % (args.manifest, exc))
        return 2

    repo = ((manifest.get("meta") or {}).get("repo")) or "demo"
    rows = generate(manifest, seed=args.seed,
                    authors=tuple(a.strip() for a in args.authors.split(",") if a.strip()),
                    adhoc_days=args.adhoc_days, repo=repo)
    if not rows:
        sys.stderr.write(
            "ERROR: no rows generated — every task in %s lacks startedAt, so there "
            "is no window to fill.\n" % args.manifest)
        return 2

    if args.stdout:
        for row in rows:
            print(json.dumps(row, separators=(",", ":"), sort_keys=True))
        return 0

    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.abspath(args.manifest)), ".claude", "usage")
    written = write_ledger(rows, out_dir)
    ul = _load_ledger_lib()
    tot = ul.totals(rows)
    print("wrote %d row(s) to %s" % (len(rows), out_dir))
    for p in written:
        print("  %s" % p)
    print("  %s tokens, $%.2f equiv, %d msgs, %d model(s), %d author(s)"
          % ("{:,}".format(tot["tokens"]), tot["costUSD"], tot["msgs"],
             tot["models"], tot["authors"]))
    return 0


# --- selftest -------------------------------------------------------------------
def _selftest():
    import shutil
    import tempfile

    cases = []

    def check(label, ok, detail=""):
        cases.append((label, bool(ok), detail))

    ul = _load_ledger_lib()
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

    rows_a = generate(manifest, seed=7, adhoc_days=2)
    rows_b = generate(manifest, seed=7, adhoc_days=2)
    check("determinism: two runs are byte-identical",
          json.dumps(rows_a, sort_keys=True) == json.dumps(rows_b, sort_keys=True))
    check("determinism: a different seed gives different output",
          json.dumps(generate(manifest, seed=8, adhoc_days=2), sort_keys=True)
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
        written = write_ledger(rows_a, tmp)
        check("io: monthly files written", len(written) == 2)
        back = ul.read_ledger(tmp)
        check("io: round-trips through the real ledger reader",
              ul.totals(back)["tokens"] == ul.totals(rows_a)["tokens"])
        first = open(written[0], encoding="utf-8").read()
        write_ledger(generate(manifest, seed=7, adhoc_days=2), tmp)
        check("io: regenerating produces an identical file (no diff churn)",
              open(written[0], encoding="utf-8").read() == first)

        empty = {"meta": {}, "phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "pending"}]}]}
        check("edge: a manifest with no started tasks yields no rows",
              generate(empty) == [])
        check("edge: CLI exits 2 on a manifest that cannot produce rows",
              main([os.path.join(tmp, "nope.json")]) == 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, detail in cases:
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           (" (%s)" % detail) if detail and not ok else ""))
    print("\ngen-demo-usage: %d/%d cases passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
