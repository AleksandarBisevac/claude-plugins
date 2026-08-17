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

This module also owns READING that shape once it is assembled — `iter_tasks`,
`tasks_by_id`, `phase_of_task` and `effective_bug_status`. It is not a second
responsibility: those answers were being re-derived by hand in twenty files, and a
re-derivation of a shape is a second opinion about that shape. Owning the layout and
owning the traversal of it is one job, and layer 1 is the only place both the layer-2
report fragments and the layer-7 commands can reach.

I/O contract: `load_manifest` raises (like open()/json.load) on a missing or invalid
index/shard, so existing callers' `try/except -> exit 2` keeps working. Hooks that must
never raise use `load_manifest_safe` (returns {} on any error).

This module carries no `--selftest` of its own any more; its 64 cases live in
`plugins/audit/tests/test__manifest_io.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
import json
import os
import tempfile


# --- reading + assembly ---------------------------------------------------------
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


# --- traversal ------------------------------------------------------------------
# Malformed entries are SKIPPED here, not reported. That is deliberate and it is the
# behaviour every hand-rolled loop already had: a non-dict phase or a non-dict task is
# a VALIDATOR finding — `validate-manifest` names it, with its path — and a traversal
# helper that raised instead would take down every read-only consumer (status, report,
# panel, doctor) of a manifest the validator is already about to fail. Skipping is not
# a silent pass because a louder reader owns exactly this class of defect.


def iter_tasks(manifest):
    """Yield `(phase, task)` for every task in the manifest, in document order.

    Exists so consumers stop re-deriving "every task, and which phase it came
    from". The PAIR is the point: the phase carries the area, the branch and the
    review, so a loop that yielded bare tasks had to look its phase back up by id —
    which is how a second, subtly different index gets built.

    A phase with no tasks yields NOTHING — there is no `(phase, None)` pair — so a
    caller counting or listing phases must read `manifest["phases"]` and not this.
    That covers a missing `tasks` key, an empty list, and a `tasks` value that is
    not a list at all.

    A non-dict `manifest` (a JSON document whose root is a list survives
    `load_manifest` unchanged) yields nothing rather than raising AttributeError,
    matching `audit-status.rollup`'s stance on a non-object root.
    """
    if not isinstance(manifest, dict):
        return
    for phase in (manifest.get("phases") or []):
        if not isinstance(phase, dict):
            continue
        for task in (phase.get("tasks") or []):
            if isinstance(task, dict):
                yield phase, task


def tasks_by_id(manifest):
    """`{task id: task}` — the ONE id -> task index.

    Three files built this by hand and a fourth built it WITHOUT the truthy-id
    filter, so a task missing its `id` became a `None` key that a bug carrying no
    `taskId` could then match. Tasks with a falsy id are excluded for that reason:
    an index is a lookup BY IDENTITY, and an entry with no identity has no place in
    one — it is a validator finding, not a key.

    A duplicate id resolves LAST-wins, the plain dict-comprehension semantics every
    hand-rolled copy already had. This does not reconcile duplicates and must not:
    `validate-manifest` is what reports them, and a lookup that silently merged two
    tasks would hide the thing being reported.
    """
    return {t["id"]: t for _, t in iter_tasks(manifest) if t.get("id")}


def phase_of_task(manifest):
    """`{task id: phase id}` — which phase owns each task.

    Kept apart from `tasks_by_id` because the answer wanted here is an ID, not a
    phase body: a caller that only needs "where does this task live" (a bug row's
    phase link, a readiness line) would otherwise hold every phase dict — tasks
    included — alive to read one field out of it.

    Same truthy-id filter and same LAST-wins duplicate rule as `tasks_by_id`, so
    the two indexes always have an identical key set; a caller may zip them.
    """
    return {t["id"]: p.get("id") for p, t in iter_tasks(manifest) if t.get("id")}


# --- readiness ------------------------------------------------------------------
# The statuses that mean the work will not move again. `cancelled` is the second
# one and it arrived later, which is exactly how the rule ended up written three
# ways: `audit-status` and `validate-manifest` each declared this tuple, and
# `audit-task._waiting_on` tested `!= "done"` and never followed. A task blocked
# by a CANCELLED task was therefore ready according to `/audit:status` and still
# waiting according to `/audit:task add` — the same manifest, two answers.
TERMINAL = ("done", "cancelled")


def unsatisfied(refs, status_by_id):
    """Which of `refs` are not settled yet, each as a string safe to print.

    `status_by_id` maps phase AND task ids to their status; a ref naming neither
    is unsatisfied, because nothing says it is finished.

    THE REFS ARE UNVALIDATED INPUT. This runs on the read-only surfaces whose job
    is to render a manifest the validator has already faulted, so `blockedBy`
    holds whatever the file holds. Two things went wrong when each caller did its
    own `status_by_id.get(r)`:

    - a NON-HASHABLE ref (`blockedBy: [[1, 2]]`) raised `TypeError` inside `.get`
      itself, taking down `audit-status` entirely;
    - a hashable non-string (`null`, `7`) survived the lookup and was carried out
      to a `", ".join(...)` that then died on it.

    So every ref that is not a string is reported as unsatisfied — it names no
    task, so nothing can ever settle it — and rendered with `repr` rather than
    dropped. Dropping would be the worse bug: the row would go quietly blank and
    the reader would never learn WHICH entry the validator is complaining about.
    A crash and a silent blank are both worse than showing `None` in the column.
    """
    out = []
    for ref in (refs or []):
        if not isinstance(ref, str):
            out.append(repr(ref))
        elif status_by_id.get(ref) not in TERMINAL:
            out.append(ref)
    return out


# --- derived bug status ---------------------------------------------------------
def effective_bug_status(bug, task_by_id):
    """A bug's status, DERIVING 'fixed' from its linked task.

    Lives at layer 1 because the rule had two homes that could drift:
    `audit-status.effective_bug_status` (layer 7) and `_report_html._bug_view`
    (layer 2), whose own docstring says it "mirrors" the other. Layer 2 cannot
    import layer 7, so that copy was STRUCTURAL rather than lazy — the only place
    one implementation can serve both readers is underneath them.

    The rule itself: the orchestrator never writes `bugs[]` during a run (that
    leaves the shared index untouched, so parallel phase branches merge clean), so
    a bug materialized into a task (`bug.taskId` <-> `task.bugId`) reads 'fixed'
    once that task is done. A human-set 'wontfix' always wins; an un-materialized
    bug keeps its reported status (open / triaged / in_progress).

    `task_by_id` is a parameter rather than something derived here so one caller
    builds the index once for a whole `bugs[]` sweep; `tasks_by_id(manifest)` is
    the index to pass.
    """
    stored = bug.get("status")
    if stored == "wontfix":
        return "wontfix"
    tid = bug.get("taskId")
    # The `if tid` guard is load-bearing, not defensive noise. An index built
    # WITHOUT the truthy-id filter (audit-status.py's ready-list index is one such)
    # carries a `None` key, and a bug with no `taskId` would then look that key up,
    # find a task, and read 'fixed'. `_report_html._bug_view` omits this guard.
    task = task_by_id.get(tid) if tid else None
    if isinstance(task, dict) and task.get("status") == "done":
        return "fixed"
    return stored


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


# --- atomic writing -------------------------------------------------------------
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


# --- sharded save ---------------------------------------------------------------
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


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_manifest_io.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__manifest_io.py - run that file instead.")
        raise SystemExit(0)
    sys.stderr.write("usage: _manifest_io.py --selftest\n")
    raise SystemExit(2)
