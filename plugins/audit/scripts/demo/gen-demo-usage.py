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
diff and a regeneration that changes nothing shows as no change.
`plugins/audit/tests/test_gen_demo_usage.py` pins that, along with referential
integrity against the manifest - this file carries no inline `--selftest` any
more, and its cases live there with byte-identical labels. The count they once
stood at is deliberately not written here, because a count in prose rots.

WHAT `DEFAULT_MODEL` COSTS, AND WHY IT IS PINNED FROM THE OTHER SIDE.
`TIER_TO_MODEL.get(tier, DEFAULT_MODEL)` cannot fail, so a phase that declares no
tier does not produce an error - it produces a row attributed to sonnet. That is
how 148 of the 40x5 demo's 482 rows came to print `claude-sonnet-5` as though the
manifest had chosen it (F34). The fallback is still right for an ad-hoc row, which
genuinely has no manifest tier to read; what it must never do is stand in for a
declaration the manifest should have made, and the case that catches that compares
each orchestrator row against its own phase's declared tier rather than looking for
the fallback's VALUE - sonnet is also a legitimate answer.

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
import _demo_cast  # noqa: E402  (the demo's author identities, shared with gen-demo-manifest)


# --- loading --------------------------------------------------------------------
def _load_ledger_lib():
    return _loader.load_script("usage_ledger.py", modname="usage_ledger",
                                cache=False)


def _load_manifest_io():
    return _loader.load_script("_manifest_io.py", modname="_manifest_io",
                                cache=False)


# --- vocab + scale --------------------------------------------------------------
# Manifest tier -> the concrete model id a transcript would record.
TIER_TO_MODEL = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5",
}
DEFAULT_MODEL = "claude-sonnet-5"

# `_demo_cast` (layer 1) owns these: `gen-demo-manifest.py` hands the same
# identities out as area owners, and the demo's whole point is that the doctor's
# owner-versus-ledger join has something to match. Spelled here under the name
# this file has always used, because `generate()`'s default argument is part of
# its signature.
DEFAULT_AUTHORS = _demo_cast.DEFAULT_AUTHORS

# Rough per-hour token shape, scaled by task risk. Cache read dominates because a
# stable prompt prefix is the normal case — that is what makes the cache-hit tile
# read ~95%+ on a healthy run.
RISK_SCALE = {"high": 2.2, "med": 1.0, "low": 0.45, None: 1.0}


# --- generation -----------------------------------------------------------------
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

    mio = _load_manifest_io()
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    # One phase gets a degraded cache rate so that chart has a story: the phase
    # holding a blocked task, where repeated retries churned the prompt prefix.
    # `iter_tasks` is document order, so the FIRST blocked task it yields is in
    # the first phase holding one — the phase the old break-out-of-two-loops
    # found. Nothing here draws from `rng`, so the sequence below is untouched.
    churned = next((p.get("id") for p, t in mio.iter_tasks(manifest)
                    if t.get("status") == "blocked"), None)

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


# --- cli ------------------------------------------------------------------------
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


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to main(), which would treat the
        # flag as a manifest path. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("gen-demo-usage.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_gen_demo_usage.py - run that file instead.")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
