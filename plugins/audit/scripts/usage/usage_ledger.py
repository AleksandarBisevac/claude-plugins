#!/usr/bin/env python3
"""
Token-usage metering core for the audit plugin — dependency-free (stdlib only).

Claude Code does NOT hand token counts to hooks. What it DOES hand every hook is
`transcript_path`, and the transcript JSONL is the ground truth: each `assistant`
entry carries `message.model` plus a `message.usage` block (input / output /
cache_creation / cache_read) alongside `timestamp`, `gitBranch` and `sessionId`.
Subagent (Task/Agent) work lands in a sibling tree:

    <projects>/<slug>/<sessionId>.jsonl                     <- main session
    <projects>/<slug>/<sessionId>/subagents/agent-<id>.jsonl  <- one per subagent
    <projects>/<slug>/<sessionId>/subagents/agent-<id>.meta.json
        { "agentType": "audit-executor", "description": "P3.2 shard writer",
          "toolUseId": "toolu_...", "spawnDepth": 1 }

THE ONE CORRECTNESS TRAP: a single `message.usage` block is REPEATED across every
transcript entry that shares its `message.id` (measured: 1543 assistant entries vs
655 unique ids in one real transcript). Summing entries naively overcounts spend by
~2.4x. Everything here dedups by `message.id` — within a scan, and across scans via
a bounded ring carried in the cursor. `_selftest` pins this.

Attribution, highest precision first (nothing is ever dropped):

  1. task          - the subagent's `.meta.json` description starts with a task id.
                     Exact even when a phase runs several tasks in parallel, because
                     each subagent owns a separate transcript file.
  2. phase         - main-session (orchestrator) spend, matched on
                     `phase.claim.sessionId` against ANY name this session answers
                     to (see `_session_ids`): the claim is written from Bash under
                     $CLAUDE_CODE_SESSION_ID while the meter is driven by its hook
                     payload's id, and those are not the same value.
  3. window        - no subagent label, but exactly one task's
                     [startedAt, completedAt] window contains the entry timestamp.
  4. unattributed  - everything else (ad-hoc edits, `#no-plan`, work outside any
                     phase). Still recorded, tagged with branch / repo / author.

Rows are aggregated per HOUR BUCKET, so the ledger keeps enough resolution for the
report's trend line and day x hour heatmap while staying small, and so a full
`--backfill` re-scan produces the same shape as incremental metering.

Storage (see the plugin README "Usage" section):

    <ledgerDir>/YYYY-MM.jsonl        append-only monthly ledger
    <ledgerDir>/.cursors/<sid>.json  per-session scan cursors + resolved author

Cursors live NEXT TO the ledger rather than in `stateDir` on purpose: `stateDir` is
garbage-collected after 7 days by detect-plan-skip.py, and losing a cursor mid-session
would re-scan from offset 0 and double-count.

This module never writes the manifest and never reads prompt CONTENT — only counts,
model ids, timestamps, branch and author.

WHAT LIVES HERE, AND WHAT MOVED. This file owns the SCAN: who spent the tokens,
where the transcripts are, which phase or task an entry belongs to, and the
append-only ledger on disk. Underneath it sit `_usage_core` (the price table, the
hour bucket, the roll-ups, and the three per-row/per-plan readers) and the four
modules that hold what a pile of rows MEANS — `_usage_spend`, `_usage_economics`,
`_usage_routing`, `_usage_coverage`. Those four were one file, `_usage_analytics`,
until it reached 955 lines; it was cut on its own section markers at U3.2 and its
benchmark went with `_usage_bench`, which is the one piece that sits BESIDE this
module rather than below it. Every public name the five define is RE-EXPORTED here,
because nothing imports this module by name: every consumer loads `usage_ledger.py`
by path and reads attributes off the module object, so the module object has to keep
serving all of them. The `rx` selftest cases are what say so.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_usage_ledger.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. `rx1`/`rx2` still count the re-export, now
against the module object a by-path loader hands back, which is what every
consumer actually holds.
"""
import glob
import hashlib
import json
import os
import re
import subprocess
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

import _manifest_io  # noqa: E402  (one home for reading a manifest's shape)

# The re-export. These names were defined in this file until the split and are read
# off this module by audit-usage.py, _report_usage.py, _panel_state.py,
# audit-status.py, audit-doctor.py, panel-server.py, gen-demo-usage.py,
# hooks/_config.py and hooks/meter-usage.py. `_selftest` asserts the two lists below
# still cover every public name those modules define, so a name added down there and
# forgotten here fails by name instead of at a call site.
from _usage_core import (  # noqa: E402,F401  (re-exported, see above)
    DEFAULT_PRICING, GROUP_KEYS, TOKEN_KEYS, UNTAGGED_AREA, aggregate,
    aggregate_area, bucket_date, bucket_hour, bucket_month, heatmap, hour_bucket,
    parse_ts, price, pricing_divergences, rates_for, rows_for_area, task_index,
    totals)
from _usage_coverage import (  # noqa: E402,F401  (re-exported, see above)
    MONTHLY_PLAN_KEYS, POOR_COVERAGE_PCT, coverage, monthly_activity)
from _usage_economics import (  # noqa: E402,F401  (re-exported, see above)
    BAND_ORDER, COST_BAND_PARAMS, MIN_TASKS_FOR_PROJECTION, band_of, cost_bands,
    phase_budgets, retry_cost, unit_economics)
from _usage_routing import (  # noqa: E402,F401  (re-exported, see above)
    ATTEMPT_TOLERANCE, MIN_ADVICE_SAVING_PCT, MIN_ADVICE_SAVING_USD,
    MIN_ROUTING_EVIDENCE, RISK_ORDER, routing)
from _usage_spend import (  # noqa: E402,F401  (re-exported, see above)
    MAX_SERIES, cache_profile, compare, series)


# --- author ---------------------------------------------------------------------
def resolve_author(repo_root, mode="email"):
    """Who spent the tokens. `git config user.email` -> `user.name` -> $USER ->
    'unknown'. Called ONCE per session (the result is cached in the cursor), so the
    single subprocess never shows up in the hook's hot path.

    modes: email | name | hash (short sha256 — pseudonymous but still groupable) |
    none (drops author attribution entirely)."""
    if mode == "none":
        return None
    order = ["user.name"] if mode == "name" else ["user.email", "user.name"]
    value = ""
    for key in order:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo_root), "config", "--get", key],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
            value = (out.stdout or b"").decode("utf-8", "replace").strip()
        except Exception:
            value = ""
        if value:
            break
    if not value:
        value = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    if mode == "hash":
        return "anon-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return value



# --- transcript discovery -------------------------------------------------------
def subagent_dir(transcript_path):
    """`.../<sessionId>.jsonl` -> `.../<sessionId>/subagents`.

    Derived from the transcript path rather than the hook's `session_id` because the
    directory is named after the transcript basename — which stays correct even if a
    hook payload ever reports a different id."""
    base, _ = os.path.splitext(str(transcript_path))
    return os.path.join(base, "subagents")


def read_agent_meta(jsonl_path):
    """The `.meta.json` beside a subagent transcript, or {} when absent/broken."""
    meta_path = jsonl_path[:-len(".jsonl")] + ".meta.json" \
        if jsonl_path.endswith(".jsonl") else jsonl_path + ".meta.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def agent_id_of(jsonl_path):
    """`agent-a2465aa3.jsonl` -> `a2465aa3`."""
    name = os.path.basename(str(jsonl_path))
    if name.endswith(".jsonl"):
        name = name[:-len(".jsonl")]
    return name[len("agent-"):] if name.startswith("agent-") else name


# --- attribution ----------------------------------------------------------------
_TASK_ID_RE = re.compile(r"([A-Za-z]{1,4}\d+\.\d+)")


def _session_ids(session_id, aliases=None):
    """Normalise "who am I" to a set, because a session has more than one name.

    `phase.claim.sessionId` is written by the ORCHESTRATOR, from Bash, where the
    id available is `$CLAUDE_CODE_SESSION_ID`. This module is driven by
    `meter-usage.py`, which takes `session_id` from its HOOK PAYLOAD. Measured in
    a live session those are different values, so comparing one to the other can
    only ever fail — and it fails silently, as spend that quietly stays
    `unattributed` instead of landing on the phase that claimed the session.

    Nothing here can make the two ids equal, so the reader accepts either.
    `meter-usage` passes both; a single string still works for every other caller.
    """
    out = {str(session_id)} if session_id else set()
    for a in (aliases or ()):
        if a:
            out.add(str(a))
    return out


class Attributor(object):
    """Maps one transcript entry to (phaseId, taskId, attribution).

    Built once per scan from the assembled manifest plus the session id. Holding the
    task-id set makes description parsing safe: a description is only read as a task
    label when it actually names a task this manifest knows about."""

    def __init__(self, manifest, session_id, session_aliases=None):
        """`session_id` is the canonical id; `session_aliases` are other names the
        same session answers to, used ONLY to match a `phase.claim` — see
        `_session_ids`. The canonical id is what lands on every ledger row, so it
        stays a plain string and the ledger's shape is unchanged."""
        self.session_id = session_id
        self.session_ids = _session_ids(session_id, session_aliases)
        # `{task id: phase id}` is exactly what layer 1 owns, down to the truthy-id
        # filter this loop used to spell out — and `task_from_description` reads it
        # as a MEMBERSHIP set, so an id-less task admitted under a falsy key would
        # be a task id this manifest does not know.
        self.phase_of_task = _manifest_io.phase_of_task(manifest)
        self.task_windows = []          # (taskId, startEpoch, endEpoch or None)
        self.claimed_phase = None
        phases = [p for p in ((manifest or {}).get("phases") or [])
                  if isinstance(p, dict)]
        for ph in phases:
            claim = ph.get("claim")
            if (isinstance(claim, dict) and self.session_ids
                    and claim.get("sessionId") in self.session_ids):
                self.claimed_phase = ph
        if self.claimed_phase:
            for t in (self.claimed_phase.get("tasks") or []):
                if not isinstance(t, dict) or not t.get("id"):
                    continue
                if t.get("status") not in ("in_progress", "done"):
                    continue
                start = parse_ts(t.get("startedAt"))
                if start is None:
                    continue
                self.task_windows.append(
                    (t["id"], start, parse_ts(t.get("completedAt"))))

    def task_from_description(self, description):
        """Leading task id in a subagent's Agent `description`, when it names a task
        this manifest knows. `reference/orchestrator.md` asks the orchestrator to
        prefix the description with the task id precisely so this works."""
        if not isinstance(description, str):
            return None
        for candidate in _TASK_ID_RE.findall(description[:64]):
            if candidate in self.phase_of_task:
                return candidate
        return None

    def attribute(self, agent_meta, ts_epoch):
        """-> (phaseId, taskId, attribution). Never raises, never returns None."""
        if agent_meta:
            tid = self.task_from_description(agent_meta.get("description"))
            if tid:
                return self.phase_of_task.get(tid), tid, "task"
        if self.claimed_phase is not None:
            pid = self.claimed_phase.get("id")
            if ts_epoch is not None:
                hits = [tid for tid, start, end in self.task_windows
                        if start <= ts_epoch and (end is None or ts_epoch <= end)]
                if len(hits) == 1:
                    return pid, hits[0], "window"
            return pid, None, "phase"
        return None, None, "unattributed"


# --- scanning -------------------------------------------------------------------
# How many recently-seen message ids the cursor carries between scans. Duplicates of
# one `message.id` are always adjacent in the file, so a small ring is enough to cover
# a chunk boundary that splits a run of duplicates.
RECENT_IDS_CAP = 500


def _usage_counts(usage):
    """Normalize a transcript `message.usage` block into TOKEN_KEYS.

    `cache_creation_input_tokens` is the total; `cache_creation` breaks it into the
    5-minute and 1-hour TTL tiers, which are priced differently.

    The TOTAL is authoritative — it is the billed field — and the two do disagree in
    practice. Real transcripts contain entries with `cache_creation_input_tokens: 0`
    whose breakdown still reports a non-zero 1-hour figure; trusting the breakdown
    there inflates cache-write spend. So the breakdown is clamped to the total, and
    any unexplained remainder is billed at the cheaper 5-minute rate rather than
    guessed high. A missing breakdown means the whole amount at the 5-minute rate."""
    def n(value):
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    created = n(usage.get("cache_creation_input_tokens"))
    detail = usage.get("cache_creation")
    w5m = w1h = 0
    if isinstance(detail, dict):
        w5m = n(detail.get("ephemeral_5m_input_tokens"))
        w1h = n(detail.get("ephemeral_1h_input_tokens"))
    if w5m + w1h != created:
        w1h = min(w1h, created)
        w5m = max(0, created - w1h)
    return {
        "in": n(usage.get("input_tokens")),
        "out": n(usage.get("output_tokens")),
        "cacheW5m": w5m,
        "cacheW1h": w1h,
        "cacheR": n(usage.get("cache_read_input_tokens")),
    }


def _scan_file(path, file_cursor, attributor, agent_meta, opts):
    """Tail one transcript file from its cursor offset.

    Returns (groups, new_file_cursor). `groups` maps a row key to accumulated counts.
    Only COMPLETE lines are consumed — a trailing partial line stays unread so the
    next scan picks it up whole."""
    groups = {}
    prev = file_cursor if isinstance(file_cursor, dict) else {}
    recent = list(prev.get("recent") or [])
    try:
        size = os.path.getsize(path)
    except OSError:
        return groups, prev
    offset = int(prev.get("offset") or 0)
    if size < int(prev.get("size") or 0):
        offset, recent = 0, []          # truncated or rotated -> start over
    if offset == 0 and not prev:
        # First sight. Historic backfill is bounded so the 10s hook timeout is safe;
        # the unbounded pass is `audit-usage.py --backfill`, which has no timeout.
        if not opts.get("backfillOnFirstRun", True) or size > opts.get(
                "maxScanBytes", 33554432):
            offset = size
    if offset >= size:
        return groups, {"offset": size, "size": size, "recent": recent}

    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
    except OSError:
        return groups, prev
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return groups, {"offset": offset, "size": size, "recent": recent}
    consumed = cut + 1
    seen = set(recent)

    for raw in chunk[:cut].split(b"\n"):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue                     # a malformed line must never abort a scan
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        mid = message.get("id")
        if not isinstance(usage, dict) or not mid or mid in seen:
            continue                     # <- THE dedup. See module docstring.
        seen.add(mid)
        recent.append(mid)
        model = message.get("model") or ""
        if model.startswith("<"):
            continue                     # `<synthetic>` API-error placeholders
        ts = entry.get("timestamp")
        bucket = hour_bucket(ts)
        if bucket is None:
            continue
        phase_id, task_id, attr = attributor.attribute(agent_meta, parse_ts(ts))
        key = (bucket, agent_meta.get("_agentId"), agent_meta.get("agentType"),
               phase_id, task_id, attr, model, entry.get("gitBranch"))
        slot = groups.get(key)
        if slot is None:
            slot = groups[key] = {k: 0 for k in TOKEN_KEYS}
            slot["msgs"] = 0
        for k, v in _usage_counts(usage).items():
            slot[k] += v
        slot["msgs"] += 1

    if len(recent) > RECENT_IDS_CAP:
        recent = recent[-RECENT_IDS_CAP:]
    return groups, {"offset": offset + consumed, "size": size, "recent": recent}


def scan_transcripts(transcript_path, session_id, cursor, manifest, opts):
    """Tail the main transcript plus every subagent transcript for this session.

    Returns (rows, new_cursor). Rows are ledger-ready dicts; the cursor carries a
    per-file offset so the next call is O(new bytes) rather than O(file)."""
    opts = opts or {}
    cursor = dict(cursor or {})
    files = dict(cursor.get("files") or {})
    attributor = Attributor(manifest, session_id,
                            session_aliases=opts.get("sessionAliases"))
    pricing = opts.get("pricing")
    author = cursor.get("author")
    repo = opts.get("repo")

    targets = [(str(transcript_path), {})]
    for path in sorted(glob.glob(os.path.join(
            subagent_dir(transcript_path), "agent-*.jsonl"))):
        meta = dict(read_agent_meta(path))
        meta["_agentId"] = agent_id_of(path)
        targets.append((path, meta))

    rows = []
    for path, agent_meta in targets:
        groups, files[path] = _scan_file(
            path, files.get(path), attributor, agent_meta, opts)
        for key, counts in groups.items():
            (bucket, agent_id, agent_type, phase_id,
             task_id, attr, model, branch) = key
            row = {
                "ts": bucket, "author": author, "sessionId": session_id,
                "agentId": agent_id, "agentType": agent_type,
                "phaseId": phase_id, "taskId": task_id, "attr": attr,
                "model": model, "branch": branch, "repo": repo,
                "msgs": counts["msgs"],
            }
            for k in TOKEN_KEYS:
                row[k] = counts[k]
            # Price at WRITE time and store the result, so a later rate change never
            # silently rewrites history.
            row["costUSD"] = round(price(counts, model, pricing), 6)
            rows.append(row)

    cursor["files"] = files
    return rows, cursor


# --- ledger I/O -----------------------------------------------------------------
def cursor_path(ledger_dir, session_id):
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in str(session_id))
    return os.path.join(ledger_dir, ".cursors", (safe or "session") + ".json")


def load_cursor(ledger_dir, session_id):
    try:
        with open(cursor_path(ledger_dir, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


LOCAL_IGNORE_MARKER = "# audit plugin: local state - do not commit\n*\n"


def ensure_ledger_dir(ledger_dir):
    """mkdir -p the ledger dir and make it self-ignoring: a `*` .gitignore
    dropped inside on creation (re-created if deleted; an existing marker is
    never overwritten, and tracked files are immune to ignore rules, so a
    deliberate `git add -f` loses nothing). The ledger holds person identities
    and per-machine cursors - never git material. Scripts-side twin of
    hooks/_config.ensure_local_dir; the two sides do not import each other
    by design. makedirs errors propagate (callers already handle them); a
    marker that cannot be written is skipped, not an error."""
    os.makedirs(ledger_dir, exist_ok=True)
    marker = os.path.join(ledger_dir, ".gitignore")
    try:
        if not os.path.exists(marker):
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write(LOCAL_IGNORE_MARKER)
    except Exception:
        pass


def save_cursor(ledger_dir, session_id, cursor):
    """Atomic (temp + os.replace) so a killed hook can never leave a half-written
    cursor that would re-scan from zero and double-count."""
    path = cursor_path(ledger_dir, session_id)
    try:
        ensure_ledger_dir(ledger_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cursor, fh)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def append_rows(ledger_dir, rows):
    """Append rows to their monthly ledger files.

    Rows are small (<~400 bytes) and each is written with a single O_APPEND write,
    which is what lets parallel worktrees meter concurrently with no lock. Only
    `--backfill` (which rewrites) ever takes one."""
    if not rows:
        return 0
    by_month = {}
    for row in rows:
        by_month.setdefault(bucket_month(row.get("ts")), []).append(row)
    written = 0
    try:
        ensure_ledger_dir(ledger_dir)
    except Exception:
        return 0
    for month, group in by_month.items():
        path = os.path.join(ledger_dir, "%s.jsonl" % month)
        try:
            with open(path, "a", encoding="utf-8") as fh:
                for row in group:
                    fh.write(json.dumps(row, separators=(",", ":"),
                                        sort_keys=True) + "\n")
                    written += 1
        except Exception:
            continue
    return written


def _native(path):
    """A path in this platform's own separator, whatever separator it arrived in.

    `ledgerDir` is authored by a human in JSON — the shipped default is the literal
    `".claude/usage"` — so on Windows `os.path.join` hands back
    `C:\\proj\\.claude/usage`. That opens directories fine, which is exactly why it
    survives: it is wrong only where paths are COMPARED or PRINTED, and both happen.
    `audit-status.py` puts this string in the `ledgerDir` field of the JSON the panel
    reads, and the report prints it. `panel-server.py` already normalises the manifest
    path for the same reason; this is that rule, applied where it was missing.
    """
    return os.path.normpath(path) if path else path


def _home():
    """The user's home directory — a seam, so the selftest can point the walk
    guard in `find_ledger_dir` at a fixture home instead of the real one."""
    return os.path.expanduser("~")


def find_ledger_dir(manifest_path, rel=None, project_dir=None):
    """Locate the ledger for a manifest, or None when there isn't one.

    Searches UPWARD from the manifest's own directory for the first ancestor that
    contains `rel`. The obvious alternative — assume the manifest lives at
    `<project>/docs/audit/<name>.json` and go three levels up — is wrong for any
    other layout, and it fails DANGEROUSLY rather than loudly: pointed at
    `examples/acme-store/audit-plan.json` it resolves to the enclosing repo and
    silently renders THAT project's spend under the example's name.

    The walk is bounded twice (F-E1):

      * It stops at the first ancestor containing `.git` — directory OR file,
        because worktrees and submodules mark themselves with a gitfile. A
        manifest inside a repo either has its ledger inside that repo or has no
        ledger; whatever sits above the repo root belongs to another project.
      * It never answers with a path under `~/.claude` — Claude Code's own
        global state, present on nearly every machine that ever ran it, which
        made it exactly the confident-numbers-about-the-wrong-project failure
        this function exists to avoid.

    Verifying candidate rows' `repo` key against the manifest's project was
    considered instead and rejected: the recorded repo path is a weak identity —
    renaming or moving a checkout changes it, so that check would turn every
    renamed clone's true ledger into a false negative. The bound keeps the
    decision about WHERE a ledger may live, never about what its rows claim.

    An explicit `project_dir` skips the walk and is answered as given, even
    before the directory exists — the pre-first-run path is deliberate (it is
    how doctor names where the ledger WOULD live).

    Returning None when nothing is found is deliberate. A missing ledger means the
    Usage section renders as nothing, which is honest; a guessed one means a report
    full of confident numbers about the wrong project.
    """
    rel = rel or os.path.join(".claude", "usage")
    if project_dir:                       # an explicit CLAUDE_PROJECT_DIR always wins
        return _native(rel if os.path.isabs(rel)
                       else os.path.join(project_dir, rel))
    if os.path.isabs(rel):
        return _native(rel) if os.path.isdir(rel) else None
    try:
        here = os.path.dirname(os.path.abspath(manifest_path))
    except Exception:
        return None
    try:
        home_claude = os.path.realpath(os.path.join(_home(), ".claude"))
    except Exception:
        home_claude = None
    seen = set()
    while here and here not in seen:
        seen.add(here)
        candidate = os.path.join(here, rel)
        if os.path.isdir(candidate):
            real = os.path.realpath(candidate)
            if home_claude is None or (real != home_claude and
                                       not real.startswith(home_claude + os.sep)):
                return _native(candidate)
        # The repo boundary is tested AFTER the candidate, so a repo root
        # holding both `.git` and the ledger still answers with the ledger.
        if os.path.exists(os.path.join(here, ".git")):
            return None
        here = os.path.dirname(here)
    return None


def ledger_files(ledger_dir):
    try:
        return sorted(glob.glob(os.path.join(ledger_dir, "[0-9]*.jsonl")))
    except Exception:
        return []


def read_ledger(ledger_dir, since=None, until=None):
    """All rows in `ledgerDir`, optionally bounded by `since`/`until` (YYYY-MM-DD).

    Months outside the window are skipped by filename before any parsing."""
    rows = []
    smonth = since[:7] if isinstance(since, str) and len(since) >= 7 else None
    umonth = until[:7] if isinstance(until, str) and len(until) >= 7 else None
    for path in ledger_files(ledger_dir):
        month = os.path.basename(path)[:-len(".jsonl")]
        if smonth and month < smonth:
            continue
        if umonth and month > umonth:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue          # tolerate a torn line, keep the rest
                    if not isinstance(row, dict):
                        continue
                    date = bucket_date(row.get("ts"))
                    if since and date and date < since:
                        continue
                    if until and date and date > until:
                        continue
                    rows.append(row)
        except OSError:
            continue
    return rows


def rewrite_month(ledger_dir, month, rows):
    """Replace one monthly file atomically. Used only by `--backfill`."""
    path = os.path.join(ledger_dir, "%s.jsonl" % month)
    tmp = path + ".tmp"
    try:
        ensure_ledger_dir(ledger_dir)
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, separators=(",", ":"),
                                    sort_keys=True) + "\n")
        os.replace(tmp, path)
        return True
    except Exception:
        return False



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
        print("usage_ledger.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_usage_ledger.py - run that file instead.")
        raise SystemExit(0)
    sys.stderr.write("usage: usage_ledger.py --selftest\n")
    raise SystemExit(2)
