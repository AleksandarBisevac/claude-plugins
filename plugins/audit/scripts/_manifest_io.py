#!/usr/bin/env python3
"""
Dual-format manifest loader for the audit plugin — dependency-free (stdlib only).

The audit manifest can be stored two ways, and this module makes both read as the
SAME in-memory dict so every downstream consumer stays format-agnostic:

  * LEGACY (single file): one JSON file whose `phases[]` hold full phase bodies,
    each with inline `tasks[]`. The original format; still fully supported forever.

  * SHARDED (index + per-phase shards): the file at `manifestPath` is an INDEX whose
    `phases[]` are lightweight STUBS — each `{id, title, status, shard, claim?}` with a
    `shard` pointing at a sibling file (e.g. "phases/P2.json") that holds the full phase
    body (`tasks[]`, `review`, `branch`, `baseRef`, `mergedAt`, `summary`, ...). The
    shared, rarely-churned data — `meta`, `bugs[]`, `fileIndex`, `deferred`, `proposals`
    — stays in the index.

Detection is structural: a manifest is SHARDED iff any phase stub carries a `shard`
key (a legacy phase never does). `load_manifest(path)` returns the assembled dict for
either format.

Why the split exists: a phase command loads only its own shard (fewer tokens), and two
parallel phase branches edit different shard files (no manifest merge conflict). All
whole-tree work (validate, rollup, readiness, render) assembles here, in Python, off the
model's context — so `audit-status.rollup` / `validate-manifest.validate` etc. keep their
pure `dict -> summary` contract unchanged.

I/O contract: `load_manifest` raises (like open()/json.load) on a missing or invalid
index/shard, so existing callers' `try/except -> exit 2` keeps working. Hooks that must
never raise use `load_manifest_safe` (returns {} on any error).
"""
import json
import os


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def is_sharded(data):
    """True iff `data` (a parsed index dict) uses the sharded layout — i.e. at least
    one phase is a stub carrying a `shard` reference. Legacy phases never have one."""
    if not isinstance(data, dict):
        return False
    phases = data.get("phases")
    if not isinstance(phases, list):
        return False
    return any(isinstance(p, dict) and "shard" in p for p in phases)


def _merge_phase(stub, body):
    """Assemble one phase from its index `stub` and shard `body`.

    The shard body is the source of truth for the phase (status / tasks / branch /
    baseRef / ...). Identity and index-only coordination fields (`claim`) fall back
    from the stub when the body omits them. Returns a NEW dict; never mutates inputs.
    """
    merged = dict(body) if isinstance(body, dict) else {}
    if isinstance(stub, dict):
        for k in ("id", "title"):
            if merged.get(k) is None:
                merged[k] = stub.get(k)
        if "status" not in merged and "status" in stub:
            merged["status"] = stub.get("status")
        if "claim" in stub and "claim" not in merged:
            merged["claim"] = stub.get("claim")
    return merged


def load_manifest(path):
    """Return the fully-assembled manifest dict for either storage format.

    LEGACY -> the parsed file unchanged. SHARDED -> the index with every `shard`
    stub replaced by its assembled phase body (read from a sibling file resolved
    relative to the index's directory). Raises on an unreadable/unparseable index
    or shard — callers already treat that as exit 2.
    """
    data = _read_json(path)
    if not is_sharded(data):
        return data
    base = os.path.dirname(os.path.abspath(path))
    assembled = []
    for stub in data.get("phases", []):
        if isinstance(stub, dict) and "shard" in stub:
            body = _read_json(os.path.join(base, stub["shard"]))
            assembled.append(_merge_phase(stub, body))
        else:
            assembled.append(stub)          # already an inline phase (mixed/defensive)
    out = dict(data)
    out["phases"] = assembled
    return out


def load_manifest_safe(path):
    """Like `load_manifest` but returns {} on ANY error — for the hooks' read path,
    which must never raise (a blocking guard degrades to 'no in-progress coverage'
    safely rather than crashing the tool call)."""
    try:
        result = load_manifest(path)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


# --- selftest -------------------------------------------------------------------
def _selftest():
    import tempfile
    import shutil

    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    legacy = {
        "meta": {"version": 2, "repo": "demo"},
        "phases": [
            {"id": "P1", "title": "Alpha", "status": "done",
             "baseRef": "abc", "branch": "audit/p1-alpha", "mergedAt": "t0",
             "review": {"model": "sonnet", "status": "done"},
             "tasks": [
                 {"id": "P1.1", "title": "t1", "status": "done",
                  "files": ["src/a.ts"], "commit": "sha1"},
             ]},
            {"id": "P2", "title": "Beta", "status": "in_progress",
             "baseRef": "def", "branch": "audit/p2-beta", "mergedAt": None,
             "review": {"model": "opus", "status": "pending"},
             "tasks": [
                 {"id": "P2.1", "title": "t2", "status": "in_progress",
                  "files": ["src/b.ts"], "commit": None},
                 {"id": "P2.2", "title": "t3", "status": "pending",
                  "files": ["src/c.ts"], "commit": None},
             ]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["P2.1"], "src/c.ts": ["P2.2"]},
        "bugs": [{"id": "BUG-1", "title": "b", "status": "open", "severity": "high"}],
    }

    tmp = tempfile.mkdtemp(prefix="manifest-io-selftest-")
    try:
        # 1. legacy round-trips unchanged
        legacy_path = os.path.join(tmp, "audit-plan.json")
        with open(legacy_path, "w", encoding="utf-8") as fh:
            json.dump(legacy, fh)
        check("legacy: is_sharded == False", is_sharded(legacy) is False)
        check("legacy: load == parsed file", load_manifest(legacy_path) == legacy)

        # 2. split into index + shards, then assemble == legacy (the key round-trip)
        shard_dir = os.path.join(tmp, "sharded")
        os.makedirs(os.path.join(shard_dir, "phases"))
        index = {k: v for k, v in legacy.items() if k != "phases"}
        index["meta"] = dict(legacy["meta"], version=3)
        index["phases"] = []
        for ph in legacy["phases"]:
            rel = os.path.join("phases", ph["id"] + ".json")
            with open(os.path.join(shard_dir, rel), "w", encoding="utf-8") as fh:
                json.dump(ph, fh)
            index["phases"].append(
                {"id": ph["id"], "title": ph["title"], "status": ph["status"],
                 "shard": rel})
        index_path = os.path.join(shard_dir, "audit-plan.json")
        with open(index_path, "w", encoding="utf-8") as fh:
            json.dump(index, fh)

        check("sharded: is_sharded(index) == True", is_sharded(index) is True)
        assembled = load_manifest(index_path)
        # meta.version differs (3 vs 2 by construction); compare the rest structurally
        check("sharded: phases assemble to full bodies",
              assembled["phases"] == legacy["phases"])
        check("sharded: fileIndex preserved", assembled["fileIndex"] == legacy["fileIndex"])
        check("sharded: bugs preserved", assembled["bugs"] == legacy["bugs"])
        check("sharded: no 'shard' key leaks into assembled phases",
              all("shard" not in p for p in assembled["phases"]))
        check("sharded: assembled task count == 3",
              sum(len(p["tasks"]) for p in assembled["phases"]) == 3)

        # 3. claim on a stub surfaces on the assembled phase
        index2 = json.loads(json.dumps(index))
        index2["phases"][1]["claim"] = {"sessionId": "s1", "host": "h", "branch": "audit/p2-beta"}
        index2_path = os.path.join(shard_dir, "audit-plan-claim.json")
        with open(index2_path, "w", encoding="utf-8") as fh:
            json.dump(index2, fh)
        asm2 = load_manifest(index2_path)
        check("claim: surfaces on assembled phase",
              asm2["phases"][1].get("claim", {}).get("sessionId") == "s1")

        # 4. missing shard: load_manifest raises, load_manifest_safe returns {}
        broken = json.loads(json.dumps(index))
        broken["phases"][0]["shard"] = os.path.join("phases", "GONE.json")
        broken_path = os.path.join(shard_dir, "audit-plan-broken.json")
        with open(broken_path, "w", encoding="utf-8") as fh:
            json.dump(broken, fh)
        raised = False
        try:
            load_manifest(broken_path)
        except Exception:
            raised = True
        check("missing shard: load_manifest raises", raised)
        check("missing shard: load_manifest_safe -> {}", load_manifest_safe(broken_path) == {})

        # 5. non-dict / unreadable safety
        check("safe: unreadable path -> {}", load_manifest_safe(os.path.join(tmp, "nope.json")) == {})
        check("is_sharded: non-dict -> False", is_sharded(["x"]) is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _manifest_io.py --selftest\n")
    raise SystemExit(2)
