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

import _machine_paths  # noqa: E402  (what a committed plan may not say, and its redaction)


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


def shard_body(phase):
    """`(body, moved)` -- what a shard file holds for an ASSEMBLED `phase`.

    THE ONE PLACE AN ASSEMBLED PHASE BECOMES A SHARD BODY. `_merge_phase` puts
    the stub's `INDEX_ONLY_FIELDS` onto every phase it assembles, so a writer
    that dumps a patched phase whole into its shard carries `priority` into a
    body where nothing reads it, and `index_only_in_bodies()` reports it on
    every later run. The stub's `shard` pointer is dropped for the same reason:
    the stub owns it. `moved` is `{field: value}` for each index-only field the
    phase carried, which is what a caller building the STUB needs.

    Returns a NEW dict; `phase` is never mutated."""
    body = dict(phase) if isinstance(phase, dict) else {}
    body.pop("shard", None)
    moved = dict((k, body.pop(k)) for k in INDEX_ONLY_FIELDS if k in body)
    return body, moved


def index_without_stub_claim(index, phase_id):
    """(index, dropped) -- `index` with `phase_id`'s stub carrying no `claim`.

    A FINISHED PHASE MUST LOSE ITS CLAIM IN BOTH HALVES. `_merge_phase` lets a
    stub's claim stand in for a body that has none, so a writer that pops the
    claim from the body alone leaves the phase claimed again the next time the
    manifest is assembled. A claim on a stub is legacy - the writers put it in
    the shard - but a plan written before that still carries one.

    Returns a NEW index (the stub list and the one stub copied, the rest
    shared) and the claim it dropped, or None when that stub held none, which
    is the caller's answer to whether the index needs writing at all. A stub
    whose claim is `null` is cleared too and answers `{}`, so the answer stays
    None for exactly the stub that was left alone."""
    stubs = (index or {}).get("phases") or []
    for i, stub in enumerate(stubs):
        if isinstance(stub, dict) and stub.get("id") == phase_id \
                and "claim" in stub:
            cleared = dict(stub)
            dropped = cleared.pop("claim")
            out = dict(index)
            out["phases"] = stubs[:i] + [cleared] + stubs[i + 1:]
            return out, dropped if dropped is not None else {}
    return index, None


def load_manifest_at(git_root, commit, rel):
    """The assembled plan as `commit` holds it, or None when it holds none.

    `rel` is the manifest's path relative to `git_root`. The directory beside it is
    exported whole, so a sharded plan arrives with its shards. The imports are
    local on purpose: this module sits on the hook path, and only the callers that
    ask a commit - a merge's resolve, a landing's settlement - pay for an archive.
    """
    import io
    import shutil
    import subprocess
    import tarfile
    rel_dir = os.path.dirname(rel) or "."
    try:
        r = subprocess.run(["git", "-C", git_root, "archive", "--format=tar", commit,
                            "--", rel_dir], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    tmp = tempfile.mkdtemp(prefix="audit-plan-at-")
    try:
        with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
            tar.extractall(tmp)
        path = os.path.join(tmp, rel)
        return load_manifest(path) if os.path.isfile(path) else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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


def stale_stubs(path):
    """`[(phase id, key, stub value, shard value)]` for every `_STUB_KEYS` value an
    index stub mirrors differently from its shard.

    `index_only_in_bodies`' reason, the other way round: the assembled manifest lets
    the body win, so by the time `validate()` sees it the stub's stale copy is gone -
    and the stub is exactly what a reader of the index alone is answered from. Asked
    here, where both halves are open, for `validate-manifest.py` to warn about and
    for the writers that re-mirror a stub to decide what moved. [] for the
    single-file layout and for an unreadable shard, for that function's reasons.
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
        for key in _STUB_KEYS:
            if key in body and stub.get(key) != body.get(key):
                out.append((stub.get("id") or body.get("id"), key, stub.get(key),
                            body.get(key)))
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


# --- where the manifest is -------------------------------------------------------
# One answer to "which file is the plan", for every script a command runs. A command
# document that handed its script a `<manifestPath>` placeholder made the model fill
# it in, and a thin command never reads the reference that states the default - so
# the model guessed, and said out loud that it had. The script answers instead.
DEFAULT_MANIFEST_REL = "docs/audit/audit-plan.json"
CONFIG_REL = ".claude/audit.config.json"


def _config_manifest_rel(cfg_path):
    """(rel, finding, problem) for the config file at `cfg_path`.

    `rel` is the `manifestPath` it names, or None. `finding` says what was seen
    there. `problem` is True - the resolver stops on it - only when the file
    exists and cannot be read as an object with a usable `manifestPath`: a config
    the user wrote is never silently swapped for the default.
    """
    if not os.path.isfile(cfg_path):
        return None, "absent", False
    try:
        cfg = read_json(cfg_path)
    except Exception as exc:
        return None, "unreadable: %s" % (exc,), True
    if not isinstance(cfg, dict):
        return None, "not a JSON object", True
    if "manifestPath" not in cfg:
        return None, "names no manifestPath", False
    rel = cfg["manifestPath"]
    if not isinstance(rel, str) or not rel.strip():
        return None, "manifestPath is not a non-empty string: %r" % (rel,), True
    return rel, "names manifestPath %r" % (rel,), False


def resolve_manifest(project, explicit=None):
    """Where the manifest is: the explicit argument, else the config's
    `manifestPath`, else `DEFAULT_MANIFEST_REL` - read against `project`, except
    an absolute `manifestPath`, which is used as given.

    Returns {"path", "source", "looked", "problem"}. `path` is None when no
    manifest exists where the rule points, and `looked` then lists every
    (place, what was found there) the answer was read from, so a refusal can name
    them. `source` is "argument", "config" or "default". An explicit argument is
    returned as given, unchecked: the caller's load reports a missing file with
    the path the user typed.

    A config naming a path that does not exist is NOT followed by the default:
    that would render some other plan than the one the project points at.
    """
    if explicit:
        return {"path": explicit, "source": "argument", "looked": [],
                "problem": None}
    cfg_path = os.path.join(project, *CONFIG_REL.split("/"))
    rel, finding, problem = _config_manifest_rel(cfg_path)
    looked = [(cfg_path, finding)]
    if problem:
        return {"path": None, "source": "config", "looked": looked,
                "problem": "%s: %s" % (cfg_path, finding)}
    source = "config" if rel is not None else "default"
    if rel is None:
        rel = DEFAULT_MANIFEST_REL
    # An absolute path is used as given - the hooks join it onto the project,
    # which keeps an absolute path whole - so both readers find the same file.
    cand = os.path.normpath(rel if os.path.isabs(rel)
                            else os.path.join(project, *rel.split("/")))
    if os.path.isfile(cand):
        return {"path": cand, "source": source, "looked": looked, "problem": None}
    looked.append((cand, "does not exist"))
    return {"path": None, "source": source, "looked": looked, "problem": None}


def describe_unresolved(resolved):
    """The refusal a command prints when `resolve_manifest` found nothing: every
    place it looked and what it saw there, then the two ways forward."""
    lines = ["no audit manifest found - looked at:"]
    lines.extend("  %s - %s" % (place, seen) for place, seen in resolved["looked"])
    lines.append("pass the manifest path as an argument, set manifestPath in %s, "
                 "or create a plan with /audit:init" % (CONFIG_REL,))
    return "\n".join(lines)


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


def moved_from_ids(task):
    """Every id `task` was moved from, newest first: `movedFrom.id`, then each
    `previous` link `move` nests inside it. A link that is not an object ends the
    chain. One walk, because the allocator (which must never mint one of these
    again) and the evidence readers (which join old-id runs to the live task)
    both need it."""
    out = []
    link = task.get("movedFrom") if isinstance(task, dict) else None
    while isinstance(link, dict) and link.get("id"):
        out.append(str(link.get("id")))
        link = link.get("previous")
    return out


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


def resolve_phase_id(manifest, wanted):
    """`(phaseId, error)` — the phase `wanted` names, or a sentence naming the ids.

    There was no shared resolver, so every script answered `/audit:phase 2`
    its own way and none of them mapped a bare integer to `P2`. A bare `<n>` is
    what an operator types when the plan is small and the ids are `P1`…`P9`, and
    the failure they got was whatever that script happened to print.

    THREE READINGS, TIGHTEST FIRST, and none of them guesses: exact, then
    case-insensitive (`p2` is not a different phase from `P2`), then a bare integer
    mapped onto `P<n>` — but ONLY when `P<n>` really exists. A `2` in a plan whose
    phases are `BF1`/`BF2` resolves to nothing rather than to something plausible,
    because a resolver that invents a phase is worse than one that refuses.

    The error NAMES the ids that exist. `close-phase.py` already printed `(have: …)`
    and that is the shape spread here rather than a second one invented: the reader
    of a failed lookup wants the alternatives, not a restatement of what they typed.
    """
    ids = [str(p.get("id")) for p in ((manifest or {}).get("phases") or [])
           if isinstance(p, dict) and p.get("id")]
    want = str(wanted or "").strip()
    if not want:
        return None, "no phase id given (have: %s)" % (", ".join(ids) or "none")
    if want in ids:
        return want, None
    folded = [pid for pid in ids if pid.lower() == want.lower()]
    if folded:
        return folded[0], None
    if want.isdigit():
        for candidate in ("P" + want, "P" + str(int(want))):
            if candidate in ids:
                return candidate, None
    return None, ("no phase %r in this manifest (have: %s)"
                  % (want, ", ".join(ids) or "none"))


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
        # The DERIVED status: a phase signed off with every task terminal is done
        # as a blocker too, and a phase only awaiting sign-off is not - unsigned
        # work does not release what waits on it.
        if ph.get("id"):
            status[ph["id"]] = effective_phase_status(ph)
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                status[t["id"]] = t.get("status")
    # DECISIONS ARE THE FOURTH KIND IN THIS MAP, and they are here rather than in
    # a resolver of their own because a second resolver would be a second answer
    # to "is this blocker settled". They carry the SAME status vocabulary phases
    # and tasks carry, so `TERMINAL` below reads them with no translation — which
    # is the property that makes a decision safe to name in `blockedBy` at all. A
    # kind with a private vocabulary would resolve and never clear, and a
    # dependency that cannot be cleared is a row that lies about what the plan is
    # waiting for. They are filled AFTER the phases for the same reason the tasks
    # are: document order decides a collision, and the validator reports the
    # duplicate id across all four kinds.
    decisions = manifest.get("decisions")
    for d in (decisions if isinstance(decisions, list) else []):
        if isinstance(d, dict) and d.get("id"):
            status[d["id"]] = d.get("status")
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


def gate_entries(phase, task=None):
    """`(entries, source)` - the gate entries that measure `task`, and WHOSE.

    The task's own `tests.gate` when it declares one, else the phase's
    `testGate`; `source` is `"task"` or `"phase"` accordingly. A gate cleared on
    purpose (`gate_cleared`) is the task's own EMPTY answer. Otherwise ABSENT, EMPTY
    AND ALL-BLANK ARE ONE ANSWER: a task with no `tests` block, one with
    `tests.gate: []` and one whose entries are all blank strings declare no gate
    and fall back, so the three cannot come to disagree about one question. Only
    non-blank string entries are returned, which is what a gate may run.

    HERE, AT THE BOTTOM LAYER, BECAUSE EVERY READER OF "WHICH GATE MEASURES
    THIS" MUST GIVE ONE ANSWER: `run-test-gate` (which resolves the entries into
    the commands it runs), `commit-task-work` (which binds a commit to that
    gate's verdict), the panel's gate badge, the report's gate-configured read
    and the demo generator. Entry points cannot import one another, and a second
    spelling of the fallback is how a task the runner measures by its phase's
    gate would read to another surface as gateless.

    The entries are returned as declared, unresolved: resolving them through
    `meta.buildCommands` is the runner's job.
    """
    if isinstance(task, dict):
        tests = task.get("tests")
        own = declared_gate_entries(tests.get("gate") if isinstance(tests, dict)
                                    else None)
        if own or gate_cleared(tests):
            return own, "task"
    phase = phase if isinstance(phase, dict) else {}
    return declared_gate_entries(phase.get("testGate")), "phase"


def gate_cleared(tests):
    """Whether a task's `tests` block records its gate as cleared ON PURPOSE.

    `--gate-clear` writes `tests.gateBasis: cleared`, and that empty gate is the
    caller's recorded decision: the task is measured by NO gate of its own, and
    the phase's `testGate` grades it at sign-off. It is the one exception to
    absent, empty and all-blank falling back to the phase - an empty gate that
    was chosen is an answer, not a missing one."""
    return isinstance(tests, dict) and tests.get("gateBasis") == "cleared"


def declared_gate_entries(entries):
    """ONE gate declaration (`testGate` or `tests.gate`) as the entries that will
    run: non-blank strings, in order.

    A non-list is [], a non-string entry is dropped (nothing resolves it and
    nothing runs it), and a blank string is dropped too - `["lint", ""]` and
    `["lint"]` run the same commands. Order is KEPT: entries run in the order
    they are written. `gate_entries` reads both declarations through this, and so
    does the validator's comparison of a task's gate with its phase's.
    """
    return [e for e in (entries if isinstance(entries, list) else [])
            if isinstance(e, str) and e.strip()]


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
# The statuses a PERSON wrote that no derivation may overwrite. `wontfix` says the
# report is real and the fix will not be made; `not_a_bug` says somebody
# investigated and the reported behaviour is correct. Both close the bug and
# neither means `fixed`, so a linked task going done must not relabel either of
# them — the tuple is what stops that from being a chain of `==` comparisons that
# learns the next word one call site at a time. It lives HERE rather than beside
# `_manifest_vocab.BUG_STATUS` because what it expresses is a property of the
# derivation below, and the derivation is this module's.
HUMAN_BUG_VERDICT = ("wontfix", "not_a_bug")


def effective_bug_status(bug, task_by_id):
    """A bug's status, DERIVING 'fixed' from its linked task.

    Lives at layer 1 because the rule had two homes that could drift:
    `audit-status.effective_bug_status` (layer 7) and `_report_html._bug_view`
    (layer 2), whose own docstring says it "mirrors" the other. Layer 2 cannot
    import layer 7, so that copy was STRUCTURAL rather than lazy — the only place
    one implementation can serve both readers is underneath them.

    The rule itself: a bug materialized into a task (`bug.taskId` <->
    `task.bugId`) reads 'fixed' once that task is done, whatever `bug.status`
    stores - the close that makes it so stores it too (`audit-task.py done`), but a
    plan closed before that, or by hand, still carries the old value and still
    reads 'fixed' here. A human verdict always wins — `HUMAN_BUG_VERDICT`
    above is the pair, and reading the tuple rather than testing one word is what
    keeps the second one from being learned here and nowhere else; an
    un-materialized bug keeps its reported status (open / triaged / in_progress).

    `task_by_id` is a parameter rather than something derived here so one caller
    builds the index once for a whole `bugs[]` sweep; `tasks_by_id(manifest)` is
    the index to pass.
    """
    stored = bug.get("status")
    if stored in HUMAN_BUG_VERDICT:
        return stored
    tid = bug.get("taskId")
    # The `if tid` guard is load-bearing, not defensive noise. An index built
    # WITHOUT the truthy-id filter (audit-status.py's ready-list index is one such)
    # carries a `None` key, and a bug with no `taskId` would then look that key up,
    # find a task, and read 'fixed'. `_report_html._bug_view` omits this guard.
    task = task_by_id.get(tid) if tid else None
    if isinstance(task, dict) and task.get("status") == "done":
        return "fixed"
    return stored


# --- derived phase status --------------------------------------------------------
# A PHASE'S STATUS IS DERIVED, the way a bug's already is, because the writer it
# relied on did not exist for every phase. `status: done` was written by hand at
# sign-off, on the phase branch, before `close-phase` merged it - so a phase worked
# on its parent branch had nothing to hand `close-phase`, and phases that finished
# stayed `in_progress` for ever, holding this repository's own plan gate in its
# denying tier across releases while every reader was correct by its own rule.
#
# The rule: a stored `done`/`cancelled` wins (a person or a sign-off wrote it).
# Otherwise a phase is `done` when every task is terminal, sign-off is RECORDED
# (`review.status` passed/skipped - the field `phase-signoff.md` writes), and, for a
# phase with a branch, the branch merged (`mergedAt`). Every task terminal without a
# recorded sign-off is SIGN-OFF DUE: finishing the work is not reviewing it.
SIGNOFF_VERDICTS = ("passed", "skipped")


def _phase_tasks(phase):
    """The phase's tasks, or None when any entry is not a task - an unreadable
    entry is a fault in the plan, and a fault is never a finished phase."""
    tasks = (phase or {}).get("tasks") or []
    if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
        return None
    return tasks


def _all_terminal(phase):
    tasks = _phase_tasks(phase)
    return bool(tasks) and all(t.get("status") in TERMINAL for t in tasks)


def signoff_recorded(phase):
    """True when the phase's review carries a sign-off verdict."""
    review = (phase or {}).get("review")
    return isinstance(review, dict) and review.get("status") in SIGNOFF_VERDICTS


def effective_phase_status(phase):
    """A phase's status, DERIVING `done` from its tasks, its recorded sign-off and,
    when it has a branch, its merge. Lives here, beside `effective_bug_status`, for
    that function's reason: the hooks, the status surfaces, the panel and the report
    all ask, and one answer underneath them is the only way they cannot disagree."""
    phase = phase or {}
    stored = phase.get("status")
    if stored in TERMINAL:
        return stored
    if (_all_terminal(phase) and signoff_recorded(phase)
            and (not phase.get("branch") or phase.get("mergedAt"))):
        return "done"
    return stored


def signoff_due(phase):
    """Every task terminal, no sign-off recorded, and the phase not closed - the
    state a finished phase waits in, and the one the plan gate must not read as a
    phase still running."""
    return (effective_phase_status(phase) not in TERMINAL and _all_terminal(phase)
            and not signoff_recorded(phase))


def phase_running(phase):
    """Whether this phase is work in flight - what the plan gate's denying tier is
    earned by. An in_progress task always is; a phase marked in_progress is while it
    has an open task or has no task yet. Merged, terminal, and only-sign-off-due
    phases are not: none of them has an edit left to make."""
    phase = phase or {}
    if phase.get("mergedAt") or effective_phase_status(phase) in TERMINAL:
        return False
    tasks = _phase_tasks(phase)
    if tasks is None:
        return phase.get("status") == "in_progress"
    if any(t.get("status") == "in_progress" for t in tasks):
        return True
    if phase.get("status") != "in_progress":
        return False
    return not tasks or any(t.get("status") not in TERMINAL for t in tasks)


def area_active(phase):
    """Whether a phase's AREA rules apply: while it runs, and while it awaits sign-off
    too. Wider than `phase_running` on purpose - sign-off's review and fix runs work
    in that area, and a capability policy that went quiet there would let them past
    it - while the plan gate's denying tier is not held by a phase with nothing left
    to edit. The hook and the panel's preview both ask this, so they cannot disagree."""
    if (phase or {}).get("mergedAt"):
        return False
    return phase_running(phase) or signoff_due(phase)


# --- stored against derived -------------------------------------------------------
# THE DERIVED VALUE IS ALSO STORED, because not every reader derives. An older
# plugin's hooks, `jq`, an agent reading the shard, a teammate reading the index stub
# all read `status` as written - and a phase that signed off while nothing wrote its
# status reads `in_progress` to every one of them, for ever. So each write that
# changes an input of the derivations above stores what they now answer, and this is
# the one question every such writer, the validator, `audit-lookup` and the `settle`
# verb ask: where does the stored value differ from the derived one, and on what
# basis. A stored terminal status wins inside the derivation, so a row here only
# ever moves a value TOWARDS the derived one and never overrides a person's verdict.

def phase_basis(phase):
    """The inputs `effective_phase_status` read, as a clause a reader can check."""
    phase = phase or {}
    stored = phase.get("status")
    if stored in TERMINAL:
        return "the stored %s wins" % (stored,)
    review = phase.get("review") if isinstance(phase.get("review"), dict) else {}
    tasks = _phase_tasks(phase)
    return ("%s, review.status %s, %s"
            % ("every task terminal" if _all_terminal(phase)
               else ("tasks unreadable" if tasks is None
                     else ("no task" if not tasks else "a task still open")),
               review.get("status") or "unset",
               ("mergedAt %s" % (phase["mergedAt"],)) if phase.get("mergedAt")
               else ("branch %s not merged" % (phase["branch"],)
                     if phase.get("branch") else "no branch")))


def _fix_task(bug, task_by_id):
    """The bug's linked task when it is done, else None."""
    tid = (bug or {}).get("taskId")
    task = task_by_id.get(tid) if tid else None
    return task if isinstance(task, dict) and task.get("status") == "done" else None


def bug_basis(bug, task_by_id):
    """The input `effective_bug_status` read, as a clause a reader can check."""
    bug = bug or {}
    if bug.get("status") in HUMAN_BUG_VERDICT:
        return "the stored %s is a person's verdict" % (bug["status"],)
    tid = bug.get("taskId")
    if not tid:
        return "no fix task linked"
    task = _fix_task(bug, task_by_id)
    if task is None:
        return "fix task %s is not done" % (tid,)
    return "fix task %s is done at %s" % (tid, task.get("commit") or "no commit")


def derived_disagreements(manifest):
    """[{"kind", "id", "field", "stored", "derived", "basis"}] -- every stored value
    a derivation answers differently, in plan order: a phase's `status`, and a
    bug's `status` and `fixedIn`.

    `fixedIn` is derived only where `fixed` is derived from the fix task, and only
    filled, never replaced: a recorded commit was put there by someone, and the
    task's commit is merely the plugin's reading of the same fact.
    """
    out = []
    if not isinstance(manifest, dict):
        return out
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        derived = effective_phase_status(ph)
        if derived != ph.get("status"):
            out.append({"kind": "phase", "id": ph.get("id"), "field": "status",
                        "stored": ph.get("status"), "derived": derived,
                        "basis": phase_basis(ph)})
    index = tasks_by_id(manifest)
    for bug in (manifest.get("bugs") or []):
        if not isinstance(bug, dict):
            continue
        derived = effective_bug_status(bug, index)
        if derived != bug.get("status"):
            out.append({"kind": "bug", "id": bug.get("id"), "field": "status",
                        "stored": bug.get("status"), "derived": derived,
                        "basis": bug_basis(bug, index)})
        task = _fix_task(bug, index)
        if (derived == "fixed" and task is not None and task.get("commit")
                and bug.get("status") not in HUMAN_BUG_VERDICT
                and not bug.get("fixedIn")):
            out.append({"kind": "bug", "id": bug.get("id"), "field": "fixedIn",
                        "stored": bug.get("fixedIn"), "derived": task["commit"],
                        "basis": bug_basis(bug, index)})
    return out


# --- writer (split a manifest into index + per-phase shards) ---------------------
# The index keeps the shared, rarely-churned data; each phase's full body becomes a
# shard. The phase STUB is minimal on purpose, and `status` is on it for the reason
# this module's own docstring and `reference/orchestrator.md` both give: execution
# order has to be computable WITHOUT opening a shard, which is the entire reason the
# sharded layout exists. The stub is a MIRROR and never the source of truth --
# `_merge_phase` lets the body win outright -- so a stub that has fallen behind
# costs a reader of the index alone a stale answer and costs the assembled manifest
# nothing.
#
# WHAT THIS IS NOT is a phase run writing the index on every task. The mirror is
# refreshed only when the value it copies actually MOVES (`audit-task._write_add`
# compares before it dirties the index), so it is written on a phase's own
# transitions rather than on the work inside them, and two phase branches still
# touch one stub each. A run `claim` stays out of the index entirely: it is
# per-run coordination with no reader that may not open the shard.
_STUB_KEYS = ("id", "title", "status")


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
        body, moved = shard_body(ph)
        stub.update(moved)
        shards[pid] = body
        index["phases"].append(stub)
    # AFTER the loop, off the stubs that were actually written — see the docstring.
    # `meta` is the dict already installed under `index["meta"]`, so this lands in
    # the position the key had (or at the end, when the source carried none), which
    # is where the unconditional stamp above it used to land.
    meta["version"] = LAYOUT_VERSION[layout_of(index)]
    # EVERY ROOT KEY SURVIVES THE SPLIT. This copied four named keys, so `decisions`
    # - in the schema - and any key a later release adds vanished on every sharded
    # save, while COMPATIBILITY promises unknown root keys are tolerated. The four
    # keep their place, so an existing index re-saves byte for byte; the rest
    # follow in the order the manifest holds them.
    for k in ("fileIndex", "bugs", "deferred", "proposals"):
        if k in manifest:
            index[k] = manifest[k]
    for k in manifest:
        if k not in index and k not in ("$schema", "meta", "phases"):
            index[k] = manifest[k]
    return index, shards


# --- atomic writing -------------------------------------------------------------
# THE ESCAPING IS CHOSEN HERE, ONCE, AND IT IS LITERAL UTF-8.
#
# A manifest has three writers and this plugin is only one of them. The other two
# are the operator's editor -- a session's Edit tool, a human's -- and whatever
# merge machinery git hands a conflict to, and both of those emit the character
# that was typed. Escaping to ASCII puts a backslash escape sequence in its place
# instead. So a plan whose title carries an em dash is rewritten wholesale every
# time the two writers
# alternate: the editor lands the character, the next plugin write escapes it
# back, and a shard merge that should have been the lines that moved becomes the
# lines that were re-spelled. That is the failure this direction is picked to end,
# and this plugin is the only one of the three writers that can be changed -- so
# it moves to what the other two already produce rather than asking them to escape.
#
# Nothing is bought by escaping on the other side. The stream is opened with an
# explicit `encoding="utf-8"` here and in `read_json`, so the bytes never depend on
# a locale; escaping to ASCII is for channels that are not eight-bit clean, and a
# file on disk is not one of those.
#
# WHAT THIS IS NOT. The journal's canonical row and the hook that appends to it
# also choose an escaping, and they are deliberately untouched by this: that string
# is a sha256 INPUT chaining one row to the next, not a document anybody diffs, and
# re-spelling it would break every chain already written.
# `_deps.json_encoding_violations()` holds the rule this block states, and it is
# scoped to this writer for exactly that reason.
def json_document(obj, indent=2):
    """The exact text a JSON document written by this plugin has: the chosen
    escaping, `indent`, and a trailing newline.

    THE ONE SPELLING, and it is a function rather than a line inside the writer
    because two callers need it. `atomic_write_json` writes what this returns;
    anything asking whether a file ALREADY has this shape compares against it
    instead of re-deriving the bytes, and re-deriving the bytes is how the
    second escaping arrived the first time.
    """
    return json.dumps(obj, indent=indent, ensure_ascii=False) + "\n"


def atomic_write_text(path, text):
    """Replace `path` with `text` atomically: a unique temp file (mkstemp, in the
    SAME directory as `path` so os.replace stays on one filesystem) is written
    and closed, then swapped into place with os.replace. No os.fsync is called,
    so this makes no durability promise across a power loss -- only that a
    reader never observes a partially-written file. The parent directory is
    created if missing. On any failure the temp file is removed (never left
    behind) and the exception propagates.

    THE TEMP NAME IS THIS CALL'S OWN. A name derived from the target alone is
    shared by every writer of that target, so a second writer running at once
    truncates the first one's temp, or moves it into place as its own, and one
    of the two writes is lost with both reporting success. `mkstemp` creates a
    name nobody else holds, which is the whole reason this is a function rather
    than three lines repeated beside each state file.

    Text mode, so the platform's line endings -- the shape every state file
    this plugin writes already has. `_deps.state_write_violations()` refuses an
    `os.replace` outside the sanctioned writers it lists, this one among them.
    """
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def atomic_write_json(path, obj, indent=2):
    """Write `obj` as JSON to `path` atomically, through `atomic_write_text` --
    the temp file, the replace and the cleanup are that function's, so there is
    one implementation of them.

    This is the ONE atomic-JSON-write implementation for the audit plugin, and it
    takes no encoding argument: the escaping is `json_document`'s, not the
    caller's -- see the block above for which way and why. `indent` stays a
    parameter because
    it is a shape a caller may legitimately want (a machine-read sidecar has no
    use for two spaces); every caller in this tree asks for the readable one.
    """
    atomic_write_text(path, json_document(obj, indent))


def _atomic_write_json(path, data):
    """Private alias for the in-file callers (`save_sharded`, `save_manifest`).
    It carries no encoding of its own — there is one encoding and the writer
    above holds it."""
    atomic_write_json(path, data, indent=2)


def _checkout_of(path):
    """The directory above `path` holding a `.git` (directory or file), else None.

    The scrub needs the checkout's root to tell an in-repo absolute path from a
    machine one, and a save is handed only the plan's path. A plan outside any
    checkout has no root to spell paths against, and then only the shapes that
    name a machine (a home directory, a scratch directory) are redacted."""
    here = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return here
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up


def scrubbed_plan(index_path, manifest):
    """`manifest` as the committed plan may say it: every string passed through
    `_machine_paths.scrubbed_values`, in a NEW structure.

    THE SAVE BOUNDARY IS THE ONLY PLACE THIS CAN BE HELD. A red helper's
    sandbox description, a runner's stderr and a hook's rendered change all land
    in the plan through callers that composed the text themselves, and a rule
    each caller must remember is a rule the next one does not know about. Text
    with no path in it comes back unchanged, so a clean plan is written
    byte for byte as before."""
    return _machine_paths.scrubbed_values(_checkout_of(index_path), manifest)


def save_plan_json(path, obj, indent=2):
    """Write one committed plan document (an index, a shard or a whole plan) at
    `path`: `scrubbed_plan` first, then `atomic_write_json`.

    THE ONE NAME A PLAN WRITER CALLS when it holds a single document rather than
    a manifest to split. A writer that must put back bytes it already holds
    (a restore from a snapshot) copies them and does not come through here;
    `atomic_write_json` stays the raw writer for files that are not the plan."""
    atomic_write_json(path, scrubbed_plan(path, obj), indent=indent)


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
    manifest = scrubbed_plan(index_path, manifest)
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
    _atomic_write_json(path, join_manifest(scrubbed_plan(path, manifest)))
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
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
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
