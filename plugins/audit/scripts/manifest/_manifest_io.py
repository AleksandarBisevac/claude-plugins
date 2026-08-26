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

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__manifest_io.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
import json
import os
import sys
import tempfile

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


# The two values `meta.version` uses, and the layout each one names. The field is a
# SECOND, independent reading of something `is_sharded()` already answers by looking at
# the phase stubs, and the two agreed on the forward migration only because
# `split_manifest` happened to write the sharded number. A manifest whose stubs carry no
# `shard` while its version still names the sharded layout is single-file to everything
# here and sharded to `/audit:doctor`, so the number is not a free-floating stamp: it is
# a claim about the structure, and both writers below take it from this table.
LAYOUT_VERSION = {"single-file": 2, "sharded": 3}


def layout_of(data):
    """Which layout `data` - a parsed INDEX, before assembly - is stored in.

    `is_sharded()` with a name instead of a boolean, so a writer, a refusal message and
    a doctor line can all say the same word for the same shape rather than each
    restating a version number of its own.
    """
    return "sharded" if is_sharded(data) else "single-file"


def declared_layout(data):
    """The layout `data`'s `meta.version` CLAIMS, or None when it claims nothing.

    None rather than a default, and that is the whole point of the function: a manifest
    carrying no readable version has ONE reading of its layout, not two that agree, and
    a caller comparing this against `layout_of()` has to be able to tell "the two
    disagree" from "there is nothing here to disagree with". Defaulting to either name
    would let exactly the confusion this exists to expose come back wearing a missing
    field.

    A version this table does not list - an older stamp, or one some future layout
    takes - is None for the same reason: it names no layout THIS code can read or
    write, and guessing which one was meant is how a manifest gets converted the
    opposite way from the one that was asked for.
    """
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    version = meta.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        return None
    for name in sorted(LAYOUT_VERSION):
        if LAYOUT_VERSION[name] == version:
            return name
    return None


# Fields the INDEX owns outright in the sharded layout — a value found in a shard
# body is ignored, never merged. `claim` is the coordination field that fell back
# from the stub; `priority` is stricter than that and the difference is the point:
#
#   * the stub already carries `status`, so execution order is computable WITHOUT
#     opening a single shard — which is the entire reason the sharded layout exists;
#   * there is ONE writer. Priority is a structural field written under the index
#     lock, while a phase run touches only its own shard;
#   * two phases running in parallel therefore cannot collide on it.
#
# Ignored is not the same as dropped in silence: `index_only_in_bodies()` below
# reports a value sitting where nothing will read it, and `validate-manifest.py`
# prints it as a finding.
INDEX_ONLY_FIELDS = ("priority",)


def _merge_phase(stub, body):
    """Assemble one phase from its index `stub` and shard `body`.

    The shard body is the source of truth for the phase (status / tasks / branch /
    baseRef / ...). Identity and index-only coordination fields (`claim`) fall back
    from the stub when the body omits them. Returns a NEW dict; never mutates inputs.

    `INDEX_ONLY_FIELDS` are the exception to that fallback direction: the STUB wins
    outright and a body value is discarded, so the assembled manifest can never
    honour an ordering nobody could see without reading every shard.
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
        for k in INDEX_ONLY_FIELDS:
            merged.pop(k, None)
            if k in stub:
                merged[k] = stub.get(k)
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


def index_only_in_bodies(path):
    """`[(phase id, field)]` for every `INDEX_ONLY_FIELDS` value sitting in a shard.

    THE ONE QUESTION `validate()` CANNOT ASK. The validator is a pure
    `dict -> (findings, warnings)` over the ASSEMBLED manifest, and by the time a
    manifest is assembled the ignored value is gone — which is exactly the state
    the reader must be told about, because a `priority` written into a shard body
    looks like it was accepted and orders nothing. So the question is asked here,
    where both halves of the file are open, and `validate-manifest.py` folds the
    answer into its findings.

    Returns [] for the single-file layout (there are no bodies) and for an
    unreadable shard — a shard nobody can read is a louder failure that
    `load_manifest` already raises for its own callers, and inventing a finding
    about a file this function could not open would name the wrong defect.
    """
    try:
        data = _read_json(path)
    except Exception:
        return []
    if not is_sharded(data):
        return []
    base = os.path.dirname(os.path.abspath(path))
    out = []
    for stub in (data.get("phases") or []):
        if not isinstance(stub, dict) or "shard" not in stub:
            continue
        try:
            body = _read_json(os.path.join(base, stub["shard"]))
        except Exception:
            continue
        if not isinstance(body, dict):
            continue
        for field in INDEX_ONLY_FIELDS:
            if field in body:
                out.append((stub.get("id") or body.get("id"), field))
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


def status_index(manifest):
    """`{phase id or task id: status}` — what a `blockedBy`/`dependsOn` ref
    resolves through.

    Lives here, beside the other traversals, because it had two consumers that
    cannot import each other: `_status_facts` (L2) builds readiness from it and
    `_manifest_crossrefs` (L2) needs the same answer to say whether a PINNED
    phase is waiting on something unfinished. Two walks would be two answers,
    and the tie-breaks below are exactly the kind of detail one copy learns and
    the other does not.

    ONE id space, holding PHASES as well as tasks, is why this walk is hand-rolled
    rather than `iter_tasks`, and both halves of that matter:

      * a task may be blocked by a whole phase, INCLUDING a phase that carries no
        tasks of its own — and `iter_tasks` yields nothing at all for such a phase,
        so its status would be missing and every dependent task would read ready;
      * because phase and task ids share the map, WHICH ONE WINS on a collision is
        observable, and document order is what decides it here. Filling the phases
        in one pass and the tasks in another makes the task win instead. That is a
        `duplicate id` manifest either way (the validator reports it across phases
        + tasks + bugs), but this is the read-only surface that has to RENDER an
        invalid manifest rather than refuse it, so its tie-breaks are held fixed.
    """
    status = {}
    if not isinstance(manifest, dict):
        return status
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        if ph.get("id"):
            status[ph["id"]] = ph.get("status")
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                status[t["id"]] = t.get("status")
    return status


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


def recorded_attempt(task):
    """The attempt count this task RECORDS — zero included, absence not.

    THREE ANSWERS, NOT TWO, and that is the whole shape of this function. A
    recorded 0 is a value: two documented paths take the count back DOWN — the
    orchestrator reverts the increment after an infrastructure failure, and
    `/audit:run` resets a blocked or re-opened task — so zero is a thing the plan
    SAYS, not a gap in it. A MISSING or non-integer `attempts` is the other
    answer entirely: this task records nothing, and a number invented for it is a
    claim with no basis. Those return None, and every caller must spell that as
    absence rather than as a figure.

    `bool` is excluded explicitly: `True` is an `int` in Python, and a manifest
    carrying `attempts: true` would otherwise read as one attempt — the same trap
    the validator's own `id: true` case exists for.

    HERE RATHER THAN IN EITHER CALLER, because both `_usage_routing` (the mean
    attempts behind a routing recommendation) and the gate runner (the attempt an
    evidence row is stamped with) must read one field the same way, and they sit
    in layers that cannot import each other. The rule was written once as
    `int(t.get("attempts") or 1)` and answered 1 for a task the manifest says has
    0; a second copy of the repaired reading is how that comes back.
    """
    if not isinstance(task, dict):
        return None
    value = task.get("attempts")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


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
    this is defensive).

    IT IS NOT INJECTIVE and it cannot be: every character outside `[A-Za-z0-9._-]`
    collapses onto `_`, so distinct ids share a name. That is safe here only
    because `shard_name_collisions()` below is asked before anything is written —
    a sanitiser is allowed to lose information as long as somebody checks what it
    lost.
    """
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in str(pid))
    return safe or "phase"


def shard_rel_path(pid, shard_rel_dir="phases"):
    """Where a phase's body is stored, relative to the index. Posix separators —
    the value goes into the stub as a portable reference and `load_manifest`
    joins it back against the index's own directory.

    ONE DERIVATION, because there were three. `split_manifest` composed the
    stub's `shard` value, `save_sharded` rebuilt the same name from `_shard_name`
    to decide which file to open, and `migrate-manifest._preview` spelled it a
    third time with the directory hardcoded to the default. Three expressions of
    one filename are three chances for the index to point at a file the writer
    did not write, and the collision check below only means anything if it asks
    the same question the writer answers.
    """
    return "%s/%s.json" % (shard_rel_dir, _shard_name(pid))


def shard_name_collisions(manifest, shard_rel_dir="phases"):
    """`[(shard path, [phase ids])]` for every shard file more than one phase
    would be written to. `[]` when every phase gets a file of its own.

    THIS IS A DATA-LOSS CHECK, not a tidiness one. `_shard_name` maps `P/9` and
    `P_9` onto one basename, `save_sharded` writes the shards in document order,
    and the second body lands on the first. Nothing raises: the index still lists
    both stubs, both point at the surviving file, and `load_manifest` hands back
    a manifest carrying the same phase twice — id, title and tasks — while the
    phase that was overwritten is gone from disk entirely.

    CASE IS FOLDED, AND THAT IS THE SECOND WAY IN rather than a nicety. `P1` and
    `p1` survive `_shard_name` as different names and are one file on macOS and on
    Windows, which lose the phase exactly the way the sanitiser does — measured on
    darwin, where `os.path.normcase` is the identity and therefore answers this
    question wrong. Folding always, on every platform, is the portable answer for
    a document that travels: a plan that splits cleanly on a Linux runner must not
    lose a phase the first time a colleague on a laptop saves it. The cost is
    naming a pair that one filesystem could in fact keep apart, which is a rename
    the user can make; the alternative cost is a phase that is simply gone.

    Asked of the manifest and answered through `split_manifest`, so "which phases
    get a shard" is decided in the one place that decides it. A phase the split
    passes through untouched (no id, not a dict) has no file and cannot collide.

    Groups come back ordered by the folded path, the ids inside a group in
    document order, and the path REPORTED is the first spelling of it — so a
    refusal reads the same on every machine.
    """
    shards = split_manifest(manifest, shard_rel_dir)[1]
    grouped = {}
    for pid in shards:
        rel = shard_rel_path(pid, shard_rel_dir)
        grouped.setdefault(rel.casefold(), []).append((rel, pid))
    return [(grouped[key][0][0], [pid for _rel, pid in grouped[key]])
            for key in sorted(grouped) if len(grouped[key]) > 1]


def describe_shard_collisions(collisions):
    """The `ids -> file` clauses a refusal prints, joined into one string.

    Here rather than at each refusal because there are two of them and they name
    the same pairs: `save_sharded` (which protects every writer) and
    `/audit:migrate` (which has to answer a `--dry-run` that never reaches the
    writer). Two spellings of one sentence are how the preview and the run start
    describing different problems.
    """
    return "; ".join("phase ids %s -> %s" % (", ".join(str(i) for i in ids), rel)
                     for rel, ids in collisions)


def split_manifest(manifest, shard_rel_dir="phases"):
    """Split an ASSEMBLED manifest into (index_dict, {phaseId: shard_body}).

    index_dict holds `$schema`, `meta` (version set to the one that names the layout
    the index ACTUALLY reads as, from `LAYOUT_VERSION`), `fileIndex`,
    `bugs`, `deferred`, `proposals` and a lightweight `{id, title, shard}` stub per
    phase; each phase's full body (tasks + branch/baseRef/mergedAt/review/summary/
    claim/…) is the shard. `load_manifest` reverses this exactly (modulo
    meta.version).

    THE VERSION IS STAMPED FROM THE RESULT, NOT FROM THE DIRECTION OF TRAVEL, and
    that is the whole of the fix: a split with nothing to shard — no phases at all,
    or none carrying an id — produces an index with no `shard` pointer anywhere,
    which `is_sharded()` and therefore every consumer in this plugin reads as
    single-file. Stamping the sharded number on it regardless is how a manifest
    ends up with the two readings of its layout disagreeing at the moment it is
    written, before any caller has touched it: `/audit:doctor` reports the
    disagreement, and the next writer to ask `is_sharded()` inlines the document
    while the number goes on claiming otherwise. An `/audit:init` that parks every
    phase and is asked for the sharded layout reaches it in one step.

    So `declared_layout(index) == layout_of(index)` is an invariant of this
    function's output rather than a coincidence of which caller ran it."""
    index = {}
    if "$schema" in manifest:
        index["$schema"] = manifest["$schema"]
    meta = dict(manifest.get("meta") or {})
    index["meta"] = meta
    index["phases"] = []
    shards = {}
    for ph in manifest.get("phases", []):
        if not isinstance(ph, dict) or not ph.get("id"):
            index["phases"].append(ph)                 # defensive passthrough
            continue
        pid = ph["id"]
        rel = shard_rel_path(pid, shard_rel_dir)
        stub = {k: ph.get(k) for k in _STUB_KEYS if k in ph}
        stub["shard"] = rel
        # The index-only fields MOVE: into the stub, out of the body. A migration
        # that left `priority` in the shard would produce, in one step, exactly the
        # state `index_only_in_bodies()` exists to report.
        body = ph
        if any(k in ph for k in INDEX_ONLY_FIELDS):
            body = dict(ph)
            for k in INDEX_ONLY_FIELDS:
                if k in body:
                    stub[k] = body.pop(k)
        shards[pid] = body
        index["phases"].append(stub)
    # AFTER the loop, off the stubs that were actually written — see the docstring.
    # `meta` is the dict already installed under `index["meta"]`, so this lands in
    # the position the key had (or at the end, when the source carried none), which
    # is where the unconditional stamp above it used to land.
    meta["version"] = LAYOUT_VERSION[layout_of(index)]
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
    then the index — so a reader never sees an index pointing at a missing shard).

    IT REFUSES BEFORE THE FIRST WRITE when `shard_name_collisions()` reports one.
    Raising is the only honest answer available: renaming a shard to make room
    would move a file a parallel worktree may already be holding open, and writing
    anyway loses a phase in silence — the failure this guard exists for.

    THE GUARD IS HERE RATHER THAN IN THE CALLERS, and that placement is the fix.
    `/audit:phase add` grew a refusal of its own for the id it is about to mint,
    which covers the id that command allocates and nothing else: `/audit:migrate`,
    `/audit:init`, the panel and `/audit:propose materialize` all reach this
    function with a whole manifest and none of them asked. A rule enforced by
    every caller is a rule the next caller does not know about.

    Nothing is created before the check, so a refused save leaves the shard
    directory exactly as it found it — including not existing.
    """
    collisions = shard_name_collisions(manifest, shard_rel_dir)
    if collisions:
        raise ValueError(
            "refusing to write %s: %s. Two phase ids the shard filename cannot "
            "tell apart would be written to one file and the second would "
            "silently replace the first -- rename one of them. Filenames are "
            "compared without case, because a split that is clean on a "
            "case-sensitive volume loses a phase on macOS or Windows."
            % (index_path, describe_shard_collisions(collisions)))
    index, shards = split_manifest(manifest, shard_rel_dir)
    base = os.path.dirname(os.path.abspath(index_path))
    os.makedirs(os.path.join(base, shard_rel_dir), exist_ok=True)
    written = []
    for pid, body in shards.items():
        # Through `shard_rel_path` so the file opened here IS the file the stub
        # in `index` points at; the two used to be composed separately.
        p = os.path.join(base, shard_rel_path(pid, shard_rel_dir))
        _atomic_write_json(p, body)
        written.append(p)
    _atomic_write_json(index_path, index)
    written.append(index_path)
    return written


# --- joining shards back into one file -------------------------------------------
def _without_shard(phase):
    """A phase with no `shard` pointer, or the phase unchanged when it carries none.

    Not defensive noise. `_merge_phase` starts from the shard BODY, so a body that
    itself holds a `shard` key - a hand-edit, or a body written out of an index that
    was already sharded - hands that key straight through into the assembled phase.
    Written into a single file it would be a pointer to a file the single-file layout
    does not have, and `is_sharded()` would then read the result as sharded.
    """
    if not isinstance(phase, dict) or "shard" not in phase:
        return phase
    trimmed = dict(phase)
    trimmed.pop("shard", None)
    return trimmed


def join_manifest(manifest):
    """`split_manifest`'s counterpart: an ASSEMBLED manifest as the SINGLE-FILE layout.

    Returns a NEW dict - `meta.version` back down to the value that names the
    single-file layout, and no `shard` key on any phase. Never mutates the input.

    There is deliberately no merging here, and the shortness is the finding rather than
    a shortcut: `load_manifest` has already replaced every stub with its full body,
    `INDEX_ONLY_FIELDS` included, so the reverse of the split is a disciplined WRITE and
    not a second assembler. What this owns is the one thing assembly does NOT do -
    putting the version back - because a version still naming the sharded layout is
    precisely the state in which two readers of one file disagree about its shape.
    """
    out = dict(manifest)
    meta = dict(manifest.get("meta") or {})
    meta["version"] = LAYOUT_VERSION["single-file"]
    out["meta"] = meta
    phases = manifest.get("phases")
    if isinstance(phases, list):
        out["phases"] = [_without_shard(p) for p in phases]
    return out


def save_single_file(path, manifest):
    """Write an assembled `manifest` as ONE file in the single-file layout, atomically.

    Returns the list of written paths - one entry, the same shape `save_sharded`
    returns, so a caller can report either direction the same way.

    It writes, and nothing else. The shard files the index used to point at are still
    on disk afterwards and this does not touch them: what becomes of a user's files is
    the calling command's decision, and a writer that removed them here would make its
    own failure path unrecoverable - restoring the index is what undoes this write, and
    an index whose shards have been deleted restores to nothing.
    """
    _atomic_write_json(path, join_manifest(manifest))
    return [path]


def shard_dir_to_retire(index_data, index_path):
    """`(directory, reason)` - the ONE directory that goes dead once this index's shards
    are inlined, or `""` and the reason there is no such directory.

    Asked of the INDEX and never assumed to be `save_sharded`'s default: a `shard` value
    is whatever relative path the index happens to carry, and a caller about to move a
    directory aside must not move one it guessed at. `index_data` is the RAW index - the
    stubs, before assembly - because an assembled manifest has no pointers left to read.

    `""` always comes with a reason and never on its own. Three shapes reach it, all of
    them legitimate manifests and none with a directory of its own to retire: an index
    with no shard pointers, pointers spread over more than one directory, and pointers
    sitting in the index's own directory, which holds the manifest too.
    """
    base = os.path.dirname(os.path.abspath(index_path))
    phases = index_data.get("phases") if isinstance(index_data, dict) else None
    dirs = []
    for stub in (phases or []):
        if not isinstance(stub, dict) or not isinstance(stub.get("shard"), str):
            continue
        d = os.path.dirname(os.path.abspath(os.path.join(base, stub["shard"])))
        if d not in dirs:
            dirs.append(d)
    if not dirs:
        return "", "the index carries no shard pointer"
    if len(dirs) > 1:
        return "", ("the shards are spread over more than one directory (%s)"
                    % ", ".join(sorted(dirs)))
    if os.path.normcase(dirs[0]) == os.path.normcase(base):
        return "", ("the shards sit beside the index in %s, which holds the manifest too"
                    % (dirs[0],))
    return dirs[0], ""


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
