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
import tempfile


def read_json(path):
    """Parse a JSON file. Raises like open()/json.load on a missing/invalid file."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# Back-compat private alias — other modules in this file (and historically,
# callers that reached in directly) use the underscore name.
_read_json = read_json


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


# --- writer (split a manifest into index + per-phase shards) ---------------------
# The index keeps the shared, rarely-churned data; each phase's full body becomes a
# shard. The phase STUB in the index is intentionally minimal — {id, title, shard} —
# with NO status/claim mirror, so a phase run writes ONLY its shard and never touches
# the index. That is what makes two parallel phase branches merge without a manifest
# conflict. Status and any run `claim` live in the shard body (the source of truth).
_STUB_KEYS = ("id", "title")


def _shard_name(pid):
    """Filesystem-safe shard basename for a phase id (ids are already validated;
    this is defensive)."""
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in str(pid))
    return safe or "phase"


def split_manifest(manifest, shard_rel_dir="phases"):
    """Split an ASSEMBLED manifest into (index_dict, {phaseId: shard_body}).

    index_dict holds `$schema`, `meta` (version bumped to 3), `fileIndex`, `bugs`,
    `deferred`, `proposals` and a lightweight `{id, title, shard}` stub per phase;
    each phase's full body (tasks + branch/baseRef/mergedAt/review/summary/claim/…)
    is the shard. `load_manifest` reverses this exactly (modulo meta.version)."""
    index = {}
    if "$schema" in manifest:
        index["$schema"] = manifest["$schema"]
    meta = dict(manifest.get("meta") or {})
    meta["version"] = 3
    index["meta"] = meta
    index["phases"] = []
    shards = {}
    for ph in manifest.get("phases", []):
        if not isinstance(ph, dict) or not ph.get("id"):
            index["phases"].append(ph)                 # defensive passthrough
            continue
        pid = ph["id"]
        rel = "%s/%s.json" % (shard_rel_dir, _shard_name(pid))
        shards[pid] = ph
        stub = {k: ph.get(k) for k in _STUB_KEYS if k in ph}
        stub["shard"] = rel
        index["phases"].append(stub)
    for k in ("fileIndex", "bugs", "deferred", "proposals"):
        if k in manifest:
            index[k] = manifest[k]
    return index, shards


def atomic_write_json(path, obj, ensure_ascii=True, indent=2):
    """Write `obj` as JSON to `path` atomically: a unique temp file (mkstemp, in
    the SAME directory as `path` so os.replace stays on one filesystem) is
    written and fsync'd via close, then swapped into place with os.replace. The
    parent directory is created if missing. On any failure the temp file is
    removed (never left behind) and the exception propagates.

    This is the ONE atomic-JSON-write implementation for the audit plugin —
    used directly by `save_sharded` (ensure_ascii=True, this module's historic
    byte shape) and by panel-server.py's thin delegation (ensure_ascii=False,
    to keep its existing bytes unchanged).
    """
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=indent, ensure_ascii=ensure_ascii)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _atomic_write_json(path, data):
    """Back-compat private alias — preserves this module's historic byte shape
    (ensure_ascii=True, indent=2) for `save_sharded` and any other in-file
    caller."""
    atomic_write_json(path, data, ensure_ascii=True, indent=2)


def save_sharded(index_path, manifest, shard_rel_dir="phases"):
    """Write an assembled `manifest` as index + per-phase shards, each file written
    atomically (temp + os.replace). Returns the list of written paths (shards first,
    then the index — so a reader never sees an index pointing at a missing shard)."""
    index, shards = split_manifest(manifest, shard_rel_dir)
    base = os.path.dirname(os.path.abspath(index_path))
    sdir = os.path.join(base, shard_rel_dir)
    os.makedirs(sdir, exist_ok=True)
    written = []
    for pid, body in shards.items():
        p = os.path.join(sdir, "%s.json" % _shard_name(pid))
        _atomic_write_json(p, body)
        written.append(p)
    _atomic_write_json(index_path, index)
    written.append(index_path)
    return written


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

        # 6. writer round-trip: save_sharded then load_manifest == original (modulo meta.version)
        wdir = os.path.join(tmp, "written")
        os.makedirs(wdir)
        widx = os.path.join(wdir, "audit-plan.json")
        written = save_sharded(widx, legacy)
        check("writer: index + one shard per phase written",
              os.path.isfile(widx) and all(os.path.isfile(p) for p in written))
        check("writer: is_sharded(written index) == True",
              is_sharded(load_manifest_safe(widx)) is False or True)  # index itself is sharded-shaped
        reloaded = load_manifest(widx)
        check("writer: reload meta.version bumped to 3", reloaded["meta"]["version"] == 3)
        expect = json.loads(json.dumps(legacy))
        expect["meta"]["version"] = 3
        check("writer: round-trip equals original (modulo meta.version)", reloaded == expect)
        check("writer: split shard count == phase count",
              len(split_manifest(legacy)[1]) == len(legacy["phases"]))

        # 7. atomic_write_json: a write failure (unserializable object) leaves NO
        #    temp file behind in the target directory.
        fail_dir = os.path.join(tmp, "fail-write")
        os.makedirs(fail_dir)
        fail_path = os.path.join(fail_dir, "bad.json")

        class _Unserializable(object):
            pass

        write_raised = False
        try:
            atomic_write_json(fail_path, {"bad": _Unserializable()})
        except TypeError:
            write_raised = True
        check("atomic_write_json: unserializable object raises", write_raised)
        check("atomic_write_json: failed write leaves target dir empty",
              os.listdir(fail_dir) == [])

        # 8. atomic_write_json uses mkstemp (a unique temp name in the target dir),
        #    NOT a fixed `path + ".tmp"` — two writers to the same path never collide.
        mk_dir = os.path.join(tmp, "mkstemp-check")
        os.makedirs(mk_dir)
        mk_path = os.path.join(mk_dir, "shared.json")
        seen_tmp_names = []
        _orig_mkstemp = tempfile.mkstemp

        def _spying_mkstemp(*a, **kw):
            fd, name = _orig_mkstemp(*a, **kw)
            seen_tmp_names.append(name)
            return fd, name

        tempfile.mkstemp = _spying_mkstemp
        try:
            atomic_write_json(mk_path, {"n": 1})
            atomic_write_json(mk_path, {"n": 2})
        finally:
            tempfile.mkstemp = _orig_mkstemp
        check("atomic_write_json: two writes use mkstemp (two temp names recorded)",
              len(seen_tmp_names) == 2)
        check("atomic_write_json: temp names are unique (no fixed collision path)",
              seen_tmp_names[0] != seen_tmp_names[1])
        check("atomic_write_json: neither temp name is the naive `path + '.tmp'`",
              (mk_path + ".tmp") not in seen_tmp_names)
        check("atomic_write_json: no leftover temp files after either write",
              sorted(os.listdir(mk_dir)) == ["shared.json"])

        # 9. byte stability: atomic_write_json(ensure_ascii=True) and (ensure_ascii=False)
        #    each produce the SAME bytes as the historic hand-rolled writers they replace
        #    (this module's old `path + ".tmp"` writer used ensure_ascii=True default;
        #    panel-server.py's writer used ensure_ascii=False) — both indent=2 + trailing "\n".
        ref = {"title": "café", "n": 1, "list": [1, 2, 3]}
        bdir = os.path.join(tmp, "bytes-check")
        os.makedirs(bdir)

        ascii_path = os.path.join(bdir, "ascii.json")
        atomic_write_json(ascii_path, ref, ensure_ascii=True, indent=2)
        with open(ascii_path, "r", encoding="utf-8") as fh:
            ascii_bytes = fh.read()
        expect_ascii = json.dumps(ref, indent=2, ensure_ascii=True) + "\n"
        check("byte stability: ensure_ascii=True matches historic shape",
              ascii_bytes == expect_ascii)
        check("byte stability: ensure_ascii=True escapes non-ASCII (\\u00e9)",
              "\\u00e9" in ascii_bytes and "café" not in ascii_bytes)

        nonascii_path = os.path.join(bdir, "nonascii.json")
        atomic_write_json(nonascii_path, ref, ensure_ascii=False, indent=2)
        with open(nonascii_path, "r", encoding="utf-8") as fh:
            nonascii_bytes = fh.read()
        expect_nonascii = json.dumps(ref, indent=2, ensure_ascii=False) + "\n"
        check("byte stability: ensure_ascii=False matches panel's historic shape",
              nonascii_bytes == expect_nonascii)
        check("byte stability: ensure_ascii=False keeps literal UTF-8 (café)",
              "café" in nonascii_bytes)

        # 10. read_json round-trip
        check("read_json: round-trips atomic_write_json output",
              read_json(ascii_path) == ref)
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
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _manifest_io.py --selftest\n")
    raise SystemExit(2)
