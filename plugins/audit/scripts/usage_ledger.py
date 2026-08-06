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
                     `phase.claim.sessionId == sessionId`.
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
"""
import calendar
import glob
import hashlib
import json
import os
import re
import subprocess
import time

# --- pricing --------------------------------------------------------------------
# USD per MILLION tokens. Mirrors hooks/_config.py DEFAULTS["usage"]["pricing"] so
# this module is usable standalone (backfill, selftest) without a config file.
# Cache rates follow the published multipliers off base input: write 1.25x at the
# 5-minute TTL, 2x at the 1-hour TTL, read 0.1x.
#
# `_default` is Opus-tier on purpose: an unrecognized model is far more likely to be
# a new frontier release than a cheap one, and over-stating spend is the safer error
# for a cost display. Anything a project actually runs should get its own row.
DEFAULT_PRICING = {
    "_default":          {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-fable-5":    {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
    "claude-mythos-5":   {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
    "claude-opus-5":     {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-8":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-7":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-6":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-opus-4-5":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
    "claude-sonnet-5":   {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
    "claude-sonnet-4-6": {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
    "claude-sonnet-4-5": {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
    "claude-haiku-4-5":  {"in":  1.0, "out":  5.0, "cacheW5m":  1.25, "cacheW1h":  2.0, "cacheR": 0.1},
}

TOKEN_KEYS = ("in", "out", "cacheW5m", "cacheW1h", "cacheR")

# How many recently-seen message ids the cursor carries between scans. Duplicates of
# one `message.id` are always adjacent in the file, so a small ring is enough to cover
# a chunk boundary that splits a run of duplicates.
RECENT_IDS_CAP = 500


def rates_for(model, pricing=None):
    """Resolve the price row for `model`: exact match, then LONGEST matching prefix
    (so a dated id like `claude-haiku-4-5-20251001` resolves to `claude-haiku-4-5`),
    then `_default`. Never raises."""
    table = pricing if isinstance(pricing, dict) and pricing else DEFAULT_PRICING
    fallback = table.get("_default") or DEFAULT_PRICING["_default"]
    if not isinstance(model, str) or not model:
        return fallback
    row = table.get(model)
    if isinstance(row, dict):
        return row
    best, best_len = None, -1
    for key, row in table.items():
        if key.startswith("_") or not isinstance(row, dict):
            continue
        if model.startswith(key) and len(key) > best_len:
            best, best_len = row, len(key)
    return best if best is not None else fallback


def price(counts, model, pricing=None):
    """USD for one bag of token counts. `counts` uses the TOKEN_KEYS names."""
    r = rates_for(model, pricing)
    total = 0.0
    for k in TOKEN_KEYS:
        try:
            total += float(counts.get(k) or 0) * float(r.get(k) or 0)
        except (TypeError, ValueError, AttributeError):
            continue
    return total / 1_000_000.0


# --- timestamps -----------------------------------------------------------------
# Hand-rolled so the parse is identical on Python 3.8+ (datetime.fromisoformat only
# learned to accept a trailing `Z` in 3.11, and is picky about fractional digits).
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d+))?(Z|z|[+-]\d{2}:?\d{2})?$")


def parse_ts(value):
    """ISO-8601 -> epoch seconds (float, UTC). None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, tz = m.groups()
    try:
        epoch = float(calendar.timegm(
            (int(y), int(mo), int(d), int(hh), int(mm), int(ss), 0, 0, 0)))
    except (ValueError, OverflowError):
        return None
    if frac:
        epoch += float("0." + frac)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        try:
            epoch -= sign * (int(body[:2]) * 3600 + int(body[2:4]) * 60)
        except ValueError:
            return None
    return epoch


def hour_bucket(value):
    """ISO-8601 -> `YYYY-MM-DDTHH` in UTC. None when unparseable.

    Rows are keyed by this, which is what gives the report an exact day x hour
    heatmap and keeps a full backfill shaped like incremental metering."""
    epoch = parse_ts(value)
    if epoch is None:
        return None
    g = time.gmtime(epoch)
    return "%04d-%02d-%02dT%02d" % (g.tm_year, g.tm_mon, g.tm_mday, g.tm_hour)


def bucket_month(bucket):
    """`YYYY-MM-DDTHH` -> `YYYY-MM` (the ledger file it belongs in)."""
    return bucket[:7] if isinstance(bucket, str) and len(bucket) >= 7 else "unknown"


def bucket_date(bucket):
    return bucket[:10] if isinstance(bucket, str) and len(bucket) >= 10 else ""


def bucket_hour(bucket):
    """`YYYY-MM-DDTHH` -> int hour, or None."""
    try:
        return int(bucket[11:13])
    except (TypeError, ValueError, IndexError):
        return None


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


class Attributor(object):
    """Maps one transcript entry to (phaseId, taskId, attribution).

    Built once per scan from the assembled manifest plus the session id. Holding the
    task-id set makes description parsing safe: a description is only read as a task
    label when it actually names a task this manifest knows about."""

    def __init__(self, manifest, session_id):
        self.session_id = session_id
        self.phase_of_task = {}
        self.task_windows = []          # (taskId, startEpoch, endEpoch or None)
        self.claimed_phase = None
        phases = [p for p in ((manifest or {}).get("phases") or [])
                  if isinstance(p, dict)]
        for ph in phases:
            pid = ph.get("id")
            for t in (ph.get("tasks") or []):
                if not isinstance(t, dict) or not t.get("id"):
                    continue
                self.phase_of_task[t["id"]] = pid
            claim = ph.get("claim")
            if (isinstance(claim, dict) and session_id
                    and claim.get("sessionId") == session_id):
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
    attributor = Attributor(manifest, session_id)
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


def save_cursor(ledger_dir, session_id, cursor):
    """Atomic (temp + os.replace) so a killed hook can never leave a half-written
    cursor that would re-scan from zero and double-count."""
    path = cursor_path(ledger_dir, session_id)
    try:
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
        os.makedirs(ledger_dir, exist_ok=True)
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


def find_ledger_dir(manifest_path, rel=None, project_dir=None):
    """Locate the ledger for a manifest, or None when there isn't one.

    Searches UPWARD from the manifest's own directory for the first ancestor that
    contains `rel`. The obvious alternative — assume the manifest lives at
    `<project>/docs/audit/<name>.json` and go three levels up — is wrong for any
    other layout, and it fails DANGEROUSLY rather than loudly: pointed at
    `examples/acme-store/audit-plan.json` it resolves to the enclosing repo and
    silently renders THAT project's spend under the example's name.

    Returning None when nothing is found is deliberate. A missing ledger means the
    Usage section renders as nothing, which is honest; a guessed one means a report
    full of confident numbers about the wrong project.
    """
    rel = rel or os.path.join(".claude", "usage")
    if project_dir:                       # an explicit CLAUDE_PROJECT_DIR always wins
        return rel if os.path.isabs(rel) else os.path.join(project_dir, rel)
    if os.path.isabs(rel):
        return rel if os.path.isdir(rel) else None
    try:
        here = os.path.dirname(os.path.abspath(manifest_path))
    except Exception:
        return None
    seen = set()
    while here and here not in seen:
        seen.add(here)
        candidate = os.path.join(here, rel)
        if os.path.isdir(candidate):
            return candidate
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
        os.makedirs(ledger_dir, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, separators=(",", ":"),
                                    sort_keys=True) + "\n")
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# --- aggregation ----------------------------------------------------------------
_SET_FIELDS = ("sessions", "authors", "models", "tasks", "phases")


def _blank():
    slot = {k: 0 for k in TOKEN_KEYS}
    slot["msgs"] = 0
    slot["costUSD"] = 0.0
    for f in _SET_FIELDS:
        slot["_" + f] = set()
    return slot


def _add(slot, row):
    for k in TOKEN_KEYS:
        try:
            slot[k] += int(row.get(k) or 0)
        except (TypeError, ValueError):
            pass
    try:
        slot["msgs"] += int(row.get("msgs") or 0)
    except (TypeError, ValueError):
        pass
    try:
        slot["costUSD"] += float(row.get("costUSD") or 0.0)
    except (TypeError, ValueError):
        pass
    for field, key in (("sessions", "sessionId"), ("authors", "author"),
                       ("models", "model"), ("tasks", "taskId"),
                       ("phases", "phaseId")):
        value = row.get(key)
        if value:
            slot["_" + field].add(value)


def _finish(slot):
    out = {k: slot[k] for k in TOKEN_KEYS}
    out["msgs"] = slot["msgs"]
    out["costUSD"] = round(slot["costUSD"], 6)
    out["tokens"] = sum(slot[k] for k in TOKEN_KEYS)
    for f in _SET_FIELDS:
        out[f] = len(slot["_" + f])
    cached = out["cacheR"]
    billed = out["in"] + out["cacheW5m"] + out["cacheW1h"] + cached
    out["cacheHitPct"] = round(100.0 * cached / billed, 1) if billed else 0.0
    return out


GROUP_KEYS = {
    "phase": lambda r: r.get("phaseId") or "--",
    "task": lambda r: r.get("taskId") or "--",
    "model": lambda r: r.get("model") or "unknown",
    "author": lambda r: r.get("author") or "unknown",
    "agent": lambda r: r.get("agentType") or "orchestrator",
    "day": lambda r: bucket_date(r.get("ts")) or "unknown",
    "hour": lambda r: r.get("ts") or "unknown",
    "session": lambda r: r.get("sessionId") or "unknown",
    "branch": lambda r: r.get("branch") or "--",
    "attr": lambda r: r.get("attr") or "unattributed",
}


def totals(rows):
    slot = _blank()
    for row in rows:
        _add(slot, row)
    return _finish(slot)


def aggregate(rows, by):
    """Group rows by one of GROUP_KEYS -> {key: finished totals}. Unknown `by`
    raises KeyError, which the CLI turns into a usage error."""
    keyfn = GROUP_KEYS[by]
    acc = {}
    for row in rows:
        acc.setdefault(keyfn(row), _blank())
        _add(acc[keyfn(row)], row)
    return {k: _finish(v) for k, v in acc.items()}


def heatmap(rows):
    """7x24 day-of-week x hour token grid. grid[0] is Monday, matching
    `time.gmtime().tm_wday`."""
    grid = [[0] * 24 for _ in range(7)]
    for row in rows:
        bucket = row.get("ts")
        epoch = parse_ts((bucket or "") + ":00:00Z")
        hour = bucket_hour(bucket)
        if epoch is None or hour is None:
            continue
        wday = time.gmtime(epoch).tm_wday
        grid[wday][hour] += sum(int(row.get(k) or 0) for k in TOKEN_KEYS)
    return grid


# --- analytics ------------------------------------------------------------------
# Pure `rows -> dict` functions. Every one of these is easy to compute and easy to
# present dishonestly, so the guard against that lives HERE rather than in each
# renderer — a wrong number that three surfaces agree on is worse than no number.

MAX_SERIES = 8              # categorical hue cap; past this the tail folds
MIN_TASKS_FOR_PROJECTION = 5
POOR_COVERAGE_PCT = 50.0


def task_index(manifest):
    """{taskId: task dict} across every phase."""
    out = {}
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                out[t["id"]] = t
    return out


def _tokens(row):
    return sum(int(row.get(k) or 0) for k in TOKEN_KEYS)


def _cost(row):
    try:
        return float(row.get("costUSD") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def series(rows, dim, bucket="day", top=MAX_SERIES, metric="tokens"):
    """Time series per entity, ready for a multi-line chart.

    Past `top` entities the tail folds into a single `other` entry rather than
    generating a 9th hue nothing can distinguish — the categorical palette is only
    validated to 8 slots, so this is a correctness bound, not a style preference.

    Returns {buckets, entities:[{key, values, total}], folded, metric}.
    """
    keyfn = GROUP_KEYS[dim]
    valfn = _tokens if metric == "tokens" else _cost
    per = {}
    seen_buckets = set()
    for row in rows:
        b = bucket_date(row.get("ts")) if bucket == "day" else (row.get("ts") or "")
        if not b:
            continue
        seen_buckets.add(b)
        k = keyfn(row)
        per.setdefault(k, {})
        per[k][b] = per[k].get(b, 0) + valfn(row)
    buckets = sorted(seen_buckets)
    ranked = sorted(per.items(), key=lambda kv: -sum(kv[1].values()))
    keep, tail = ranked[:top], ranked[top:]
    entities = [{"key": k, "total": sum(v.values()),
                 "values": [v.get(b, 0) for b in buckets]} for k, v in keep]
    if tail:
        merged = {}
        for _, v in tail:
            for b, n in v.items():
                merged[b] = merged.get(b, 0) + n
        entities.append({"key": "other", "total": sum(merged.values()),
                         "values": [merged.get(b, 0) for b in buckets]})
    return {"buckets": buckets, "entities": entities, "folded": len(tail),
            "metric": metric}


def compare(rows, since, until):
    """This window vs the one immediately before it, same length.

    Returns None for `prior` and every delta when there is nothing to compare
    against — a first-run dashboard must not invent a '+100%'."""
    start, end = parse_ts((since or "") + "T00:00:00Z"), \
        parse_ts((until or "") + "T23:59:59Z")
    current = [r for r in rows
               if (not since or bucket_date(r.get("ts")) >= since)
               and (not until or bucket_date(r.get("ts")) <= until)]
    out = {"current": totals(current), "prior": None, "deltas": {}, "window": None}
    if start is None or end is None or end <= start:
        return out
    span = end - start
    p_start, p_end = start - span, start
    prior = []
    for r in rows:
        t = parse_ts((bucket_date(r.get("ts")) or "") + "T00:00:00Z")
        if t is not None and p_start <= t < p_end:
            prior.append(r)
    if not prior:
        return out
    pt = totals(prior)
    out["prior"] = pt
    for key in ("tokens", "costUSD", "msgs", "out"):
        before = pt.get(key) or 0
        now = out["current"].get(key) or 0
        out["deltas"][key] = (100.0 * (now - before) / before) if before else None
    out["window"] = {"since": since, "until": until}
    return out


def cache_profile(rows):
    """Cache economics, stated as RATES rather than an invented saving.

    Deliberately returns no "you saved $N": without caching you would not have made
    the same calls at the same volume, so that number is a fabricated counterfactual.
    `inputCostVsFreshPct` is a real rate comparison — what the input side actually
    bills as a share of what the identical token volume would bill at fresh-input
    rates — and is safe to show."""
    slot = {k: 0 for k in TOKEN_KEYS}
    per_phase = {}
    for row in rows:
        for k in TOKEN_KEYS:
            slot[k] += int(row.get(k) or 0)
        pid = row.get("phaseId") or "--"
        p = per_phase.setdefault(pid, {k: 0 for k in TOKEN_KEYS})
        for k in TOKEN_KEYS:
            p[k] += int(row.get(k) or 0)

    def hit(d):
        billed = d["in"] + d["cacheW5m"] + d["cacheW1h"] + d["cacheR"]
        return (100.0 * d["cacheR"] / billed) if billed else 0.0

    by_phase = {pid: round(hit(d), 1) for pid, d in per_phase.items()}
    worst = min(by_phase.items(), key=lambda kv: kv[1]) if by_phase else None
    # Rate comparison against the fresh-input price of the SAME volume.
    actual = fresh = 0.0
    for row in rows:
        r = rates_for(row.get("model"))
        vol = (int(row.get("in") or 0) + int(row.get("cacheW5m") or 0)
               + int(row.get("cacheW1h") or 0) + int(row.get("cacheR") or 0))
        actual += (int(row.get("in") or 0) * r["in"]
                   + int(row.get("cacheW5m") or 0) * r["cacheW5m"]
                   + int(row.get("cacheW1h") or 0) * r["cacheW1h"]
                   + int(row.get("cacheR") or 0) * r["cacheR"])
        fresh += vol * r["in"]
    return {
        "hitPct": round(hit(slot), 1),
        "readTokens": slot["cacheR"],
        "writeTokens": slot["cacheW5m"] + slot["cacheW1h"],
        "freshTokens": slot["in"],
        "inputCostVsFreshPct": round(100.0 * actual / fresh, 1) if fresh else 100.0,
        "byPhase": by_phase,
        "worstPhase": worst,
    }


def _percentile(values, p):
    """Nearest-rank percentile on a sorted list. Stdlib only, no numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[idx]


def unit_economics(manifest, rows):
    """Cost per completed task, and what the remaining work would cost at that rate.

    The projection is SUPPRESSED below `MIN_TASKS_FOR_PROJECTION` completed tasks and
    is always a p25-p75 RANGE rather than a point estimate. A confident forecast off
    three samples is worse than no forecast."""
    tasks = task_index(manifest)
    cost_by_task = {}
    for row in rows:
        tid = row.get("taskId")
        if tid:
            cost_by_task[tid] = cost_by_task.get(tid, 0.0) + _cost(row)
    done = [c for tid, c in cost_by_task.items()
            if (tasks.get(tid) or {}).get("status") == "done"]
    remaining = sum(1 for t in tasks.values()
                    if t.get("status") in ("pending", "in_progress", "blocked"))
    out = {
        "completed": len(done), "remaining": remaining,
        "gate": MIN_TASKS_FOR_PROJECTION, "sufficient": len(done) >= MIN_TASKS_FOR_PROJECTION,
        "costPerTask": round(sum(done) / len(done), 4) if done else None,
        "p25": None, "p75": None, "projection": None,
        "mostExpensive": sorted(
            ((tid, round(c, 4), (tasks.get(tid) or {}).get("attempts"))
             for tid, c in cost_by_task.items() if tid in tasks),
            key=lambda x: -x[1])[:5],
    }
    if not out["sufficient"]:
        return out
    p25, p75 = _percentile(done, 25), _percentile(done, 75)
    out["p25"], out["p75"] = round(p25, 4), round(p75, 4)
    out["projection"] = {"low": round(p25 * remaining, 2),
                         "high": round(p75 * remaining, 2)}
    return out


BAND_ORDER = ("typical", "high", "outlier")


def cost_bands(manifest, rows, cfg=None):
    """Sort tasks into `typical` / `high` / `outlier` by what they cost.

    Deliberately NOT called a risk band: manifest tasks already carry `risk`, which
    is the risk of the CHANGE (and is what `routing` compares within). Two different
    axes wearing one word would make both impossible to discuss.

    The thresholds are the project's own median and p90 by default, so this means
    something on day one with no configuration and re-calibrates as the work grows.
    A team with a real budget can pin absolute numbers in
    `usage.bands.{highUSD,outlierUSD}` instead; `basis` says which is in force, and
    the callers print the thresholds, because a band whose definition is invisible
    is a number nobody can argue with.

    Two guards:

    * Below `MIN_TASKS_FOR_PROJECTION` completed tasks the relative basis returns
      NOTHING — percentiles off three samples are noise, and a confidently wrong
      band is worse than no band. The absolute basis has no such gate: a configured
      threshold is an opinion the user already holds.
    * Thresholds come from COMPLETED tasks only, because a half-finished task's cost
      is not comparable. They are then applied to every task including in-flight
      ones, which is what lets the metering hook warn while there is still time to
      act.
    """
    band_cfg = ((cfg or {}).get("bands") or {}) if isinstance(cfg, dict) else {}
    tasks = task_index(manifest)
    cost_by_task = {}
    for row in rows:
        tid = row.get("taskId")
        if tid and tid in tasks:
            cost_by_task[tid] = cost_by_task.get(tid, 0.0) + _cost(row)

    out = {"basis": None, "high": None, "outlier": None, "byTask": {},
           "counts": {b: 0 for b in BAND_ORDER}, "sample": 0,
           "gate": MIN_TASKS_FOR_PROJECTION, "sufficient": False}

    hi, out_ = band_cfg.get("highUSD"), band_cfg.get("outlierUSD")
    try:
        hi = float(hi) if hi is not None else None
        out_ = float(out_) if out_ is not None else None
    except (TypeError, ValueError):      # a garbled config must not classify
        hi = out_ = None
    if hi is not None and out_ is not None and 0 < hi <= out_:
        out.update(basis="absolute", high=hi, outlier=out_, sufficient=True)
    else:
        done = [c for tid, c in cost_by_task.items()
                if (tasks.get(tid) or {}).get("status") == "done"]
        out["sample"] = len(done)
        if len(done) < MIN_TASKS_FOR_PROJECTION:
            return out
        out.update(basis="relative", sufficient=True,
                   high=round(_percentile(done, 50), 4),
                   outlier=round(_percentile(done, 90), 4))

    for tid, cost in cost_by_task.items():
        band = ("outlier" if cost > out["outlier"]
                else "high" if cost > out["high"] else "typical")
        out["byTask"][tid] = band
        out["counts"][band] += 1
    return out


def phase_budgets(manifest, rows):
    """Spend against `phase.budgetUSD`, for the phases that declare one.

    Ties spend to the PLAN rather than to the calendar, which is the comparison a
    manifest-driven pipeline can make and a date-range dashboard cannot.

    Phases without a budget are returned too, with `budget: None` — the surfaces
    need to render them as "—". Defaulting an absent budget to zero would paint
    every unbudgeted phase as infinitely over, and defaulting it to the spend
    would paint every one as exactly on target; both are lies about a phase whose
    owner simply never set a number.

    `pct` is uncapped on purpose: a phase at 130% should read 130%, not a bar
    pinned at full with the overrun hidden."""
    spent = {}
    for row in rows:
        pid = row.get("phaseId") or "--"
        spent[pid] = spent.get(pid, 0.0) + _cost(row)

    out, budgeted, total_budget, total_spent = [], 0, 0.0, 0.0
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict) or not ph.get("id"):
            continue
        pid = ph["id"]
        raw = ph.get("budgetUSD")
        budget = (float(raw) if isinstance(raw, (int, float))
                  and not isinstance(raw, bool) and raw > 0 else None)
        used = round(spent.get(pid, 0.0), 4)
        if budget is not None:
            budgeted += 1
            total_budget += budget
            total_spent += used
        out.append({
            "id": pid, "title": ph.get("title") or "", "status": ph.get("status"),
            "budget": budget, "spent": used,
            "pct": round(100.0 * used / budget, 1) if budget else None,
            "over": bool(budget and used > budget),
        })
    return {"phases": out, "budgeted": budgeted,
            "totalBudget": round(total_budget, 4) if budgeted else None,
            "totalSpent": round(total_spent, 4) if budgeted else None,
            "anyOver": any(p["over"] for p in out)}


def band_of(bands, task_id):
    """The band for one task, or None when banding is suppressed/unknown."""
    if not bands or not bands.get("sufficient"):
        return None
    return (bands.get("byTask") or {}).get(task_id)


def retry_cost(manifest, rows):
    """Spend on retried tasks and spend on blocked tasks — reported SEPARATELY.

    These are not summed into a single "waste" figure and the retried number is not
    called waste at all. The ledger buckets by hour, not by attempt, so there is no
    per-attempt token boundary: a task that took three attempts and then landed did
    not waste three attempts' worth. Only the BLOCKED number is unambiguous spend
    with no outcome."""
    tasks = task_index(manifest)
    total = retried = blocked = 0.0
    retried_ids, blocked_ids = set(), set()
    for row in rows:
        c = _cost(row)
        total += c
        tid = row.get("taskId")
        t = tasks.get(tid) if tid else None
        if not t:
            continue
        try:
            attempts = int(t.get("attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts > 1:
            retried += c
            retried_ids.add(tid)
        if t.get("status") == "blocked":
            blocked += c
            blocked_ids.add(tid)
    return {
        "totalCost": round(total, 4),
        "retriedCost": round(retried, 4), "retriedTasks": len(retried_ids),
        "retriedPct": round(100.0 * retried / total, 1) if total else 0.0,
        "blockedCost": round(blocked, 4), "blockedTasks": len(blocked_ids),
        "blockedPct": round(100.0 * blocked / total, 1) if total else 0.0,
        # Explicit so no renderer is tempted to add the two together.
        "overlaps": len(retried_ids & blocked_ids),
    }


RISK_ORDER = ("high", "med", "low", "unrated")


def routing(manifest, rows, pricing=None):
    """Cost per completed task and mean attempts, per model, WITHIN a risk band.

    Deliberately NOT a spend-share / task-share ratio. Tasks are not equal-sized —
    the plugin's own guidance routes hard work to the strong model on purpose and
    warns that a cheap botched attempt costs more than one clean expensive pass. A
    bare ratio would show that working system as a problem and push users toward
    exactly the routing the docs warn against. Comparing within a risk band is the
    only comparison that means anything.

    Models come from the LEDGER (what actually ran), never from the manifest's
    `model` field, which is a provider-agnostic tier name in a different namespace."""
    tasks = task_index(manifest)
    acc = {}
    for row in rows:
        tid = row.get("taskId")
        t = tasks.get(tid) if tid else None
        if not t:
            continue
        risk = t.get("risk") or "unrated"
        model = row.get("model") or "unknown"
        cell = acc.setdefault((risk, model),
                              {"cost": 0.0, "tasks": {},
                               "counts": {k: 0 for k in TOKEN_KEYS}})
        cell["cost"] += _cost(row)
        cell["tasks"][tid] = t
        # Kept so the counterfactual below can re-price the SAME tokens at another
        # model's rates. Cost alone cannot do that.
        for k in TOKEN_KEYS:
            cell["counts"][k] += int(row.get(k) or 0)
    by_risk, counts_by = {}, {}
    for (risk, model), cell in acc.items():
        n = len(cell["tasks"])
        attempts = [int(t.get("attempts") or 1) for t in cell["tasks"].values()]
        by_risk.setdefault(risk, {})[model] = {
            "tasks": n,
            "cost": round(cell["cost"], 4),
            "costPerTask": round(cell["cost"] / n, 4) if n else None,
            "meanAttempts": round(sum(attempts) / float(len(attempts)), 2)
            if attempts else None,
        }
        counts_by[(risk, model)] = cell["counts"]
    return {
        "byRisk": by_risk,
        "risks": [r for r in RISK_ORDER if r in by_risk],
        "models": sorted({m for cells in by_risk.values() for m in cells}),
        "advice": _routing_advice(by_risk, counts_by, pricing),
    }


MIN_ROUTING_EVIDENCE = 3    # tasks needed on BOTH models, in that band, in this repo
ATTEMPT_TOLERANCE = 0.2     # a cheaper model that retries more is not cheaper
MIN_ADVICE_SAVING_USD = 1.0
MIN_ADVICE_SAVING_PCT = 10.0


def _has_rates(model, pricing=None):
    """True only when the price table names this model. `rates_for` falls back to
    `_default` for anything unknown, and recommending a move onto a model whose
    price is a guess would be worse than saying nothing."""
    table = pricing if isinstance(pricing, dict) and pricing else DEFAULT_PRICING
    fallback = table.get("_default") or DEFAULT_PRICING["_default"]
    return rates_for(model, pricing) is not fallback


def _routing_advice(by_risk, counts_by, pricing=None):
    """Where the ledger's own evidence supports moving work to a cheaper model.

    Every condition here exists to stop this becoming the glib advice the routing
    table was built to avoid:

    * WITHIN one risk band only. The plugin routes hard work to the strong model
      on purpose; comparing across bands would flag that working system as a fault.
    * The cheaper model must already have run `MIN_ROUTING_EVIDENCE` tasks in that
      band IN THIS REPO. Without that, "sonnet would be cheaper" is a price-list
      observation, not a finding — of course it is cheaper, it is also different.
    * Its mean attempts must be no worse than the incumbent's (plus a small
      tolerance). A cheap model that retries twice is not cheaper, and the retry
      analytics right above this say exactly that.
    * Both models must have real rates in the table, never a `_default` guess.
    * The saving must clear both a percentage and an absolute floor, or the advice
      is noise dressed as insight.

    Both sides are priced at TODAY's rates on the same token counts, so the two
    numbers share one rate epoch — comparing a historical cost against a current
    price list would be a different (and wrong) sum. The result is an upper bound,
    not a forecast: a different model would not emit the same tokens.
    """
    out = []
    for risk, cells in by_risk.items():
        ranked = sorted(cells.items(), key=lambda kv: -(kv[1]["cost"]))
        for model, cell in ranked:
            if cell["tasks"] < MIN_ROUTING_EVIDENCE or not _has_rates(model, pricing):
                continue
            counts = counts_by.get((risk, model)) or {}
            at_from = price(counts, model, pricing)
            best = None
            for other, ocell in cells.items():
                if other == model:
                    continue
                if ocell["tasks"] < MIN_ROUTING_EVIDENCE or not _has_rates(other, pricing):
                    continue
                if (ocell["meanAttempts"] or 0) > (cell["meanAttempts"] or 0) \
                        + ATTEMPT_TOLERANCE:
                    continue
                at_other = price(counts, other, pricing)
                saving = at_from - at_other
                if saving < MIN_ADVICE_SAVING_USD:
                    continue
                if at_from <= 0 or 100.0 * saving / at_from < MIN_ADVICE_SAVING_PCT:
                    continue
                if best is None or saving > best[1]:
                    best = (other, saving, at_other, ocell)
            if best:
                other, _saving, at_other, ocell = best
                # Round FIRST, then derive — so the three figures reconcile on
                # screen. Rounding each independently let 25.01 - 15.00 print as a
                # saving of 10.00, which is a cent nobody can account for in a
                # module whose whole claim is that its numbers can be checked.
                af, at = round(at_from, 2), round(at_other, 2)
                out.append({
                    "risk": risk, "from": model, "to": other,
                    "tasks": cell["tasks"],
                    "fromMeanAttempts": cell["meanAttempts"],
                    "atFromRates": af,
                    "atToRates": at,
                    "saving": round(af - at, 2),
                    "savingPct": round(100.0 * (af - at) / af, 1) if af else 0.0,
                    "evidenceTasks": ocell["tasks"],
                    "evidenceAttempts": ocell["meanAttempts"],
                })
    out.sort(key=lambda a: -a["saving"])
    return out


def coverage(rows):
    """How much spend the attribution layers actually resolved.

    A dashboard where 90% is `unattributed` is not showing you your phases — it is
    showing you one big bucket. This drives a visible warning rather than letting
    every other chart quietly mean nothing."""
    by_attr, total = {}, 0
    for row in rows:
        n = _tokens(row)
        total += n
        by_attr[row.get("attr") or "unattributed"] = \
            by_attr.get(row.get("attr") or "unattributed", 0) + n
    if not total:
        return {"total": 0, "byAttr": {}, "attributedPct": 0.0,
                "taskLevelPct": 0.0, "warn": False}
    unattributed = by_attr.get("unattributed", 0)
    return {
        "total": total,
        "byAttr": {k: round(100.0 * v / total, 1) for k, v in by_attr.items()},
        "attributedPct": round(100.0 * (total - unattributed) / total, 1),
        "taskLevelPct": round(100.0 * by_attr.get("task", 0) / total, 1),
        "warn": (100.0 * unattributed / total) > POOR_COVERAGE_PCT,
    }


# --- selftest -------------------------------------------------------------------
def _selftest():
    import shutil
    import tempfile

    cases = []

    def check(label, cond, detail=""):
        cases.append((label, bool(cond), detail))

    # --- pricing -----------------------------------------------------------
    check("price: exact model match",
          rates_for("claude-sonnet-5")["in"] == 3.0)
    check("price: longest-prefix match resolves a dated id",
          rates_for("claude-haiku-4-5-20251001")["out"] == 5.0)
    check("price: Fable/Mythos priced above Opus tier, not silently defaulted",
          rates_for("claude-fable-5")["out"] == 50.0
          and rates_for("claude-mythos-5")["out"] == 50.0)
    check("price: a Sonnet 4.x id does not fall through to the Opus default",
          rates_for("claude-sonnet-4-5")["out"] == 15.0)
    check("price: unknown model falls back to _default",
          rates_for("some-future-model")["in"] == DEFAULT_PRICING["_default"]["in"])
    check("price: non-string model falls back",
          rates_for(None)["in"] == DEFAULT_PRICING["_default"]["in"])
    one_m = {"in": 1_000_000, "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0}
    check("price: 1M input on opus-5 == $5.00",
          abs(price(one_m, "claude-opus-5") - 5.0) < 1e-9)
    both = {"in": 0, "out": 0, "cacheW5m": 1_000_000, "cacheW1h": 1_000_000,
            "cacheR": 0}
    check("price: both cache-write tiers priced apart (6.25 + 10.00)",
          abs(price(both, "claude-opus-5") - 16.25) < 1e-9)
    check("price: cache read is 0.1x base input",
          abs(price({"in": 0, "out": 0, "cacheW5m": 0, "cacheW1h": 0,
                     "cacheR": 1_000_000}, "claude-opus-5") - 0.5) < 1e-9)

    # --- timestamps --------------------------------------------------------
    check("ts: millisecond Z form parses",
          parse_ts("2026-08-06T07:20:10.266Z") is not None)
    check("ts: microsecond form parses",
          parse_ts("2026-08-06T07:20:10.266123Z") is not None)
    check("ts: offset form normalizes to UTC",
          parse_ts("2026-08-06T09:20:10+02:00") == parse_ts("2026-08-06T07:20:10Z"))
    check("ts: garbage -> None", parse_ts("not-a-date") is None)
    check("ts: hour bucket is UTC-normalized",
          hour_bucket("2026-08-06T09:20:10+02:00") == "2026-08-06T07")
    check("ts: bucket_month / bucket_date / bucket_hour",
          bucket_month("2026-08-06T07") == "2026-08"
          and bucket_date("2026-08-06T07") == "2026-08-06"
          and bucket_hour("2026-08-06T07") == 7)

    # --- usage normalization ----------------------------------------------
    counts = _usage_counts({
        "input_tokens": 2, "output_tokens": 264,
        "cache_creation_input_tokens": 24813,
        "cache_creation": {"ephemeral_1h_input_tokens": 24813,
                           "ephemeral_5m_input_tokens": 0},
        "cache_read_input_tokens": 22494})
    check("usage: cache tiers split from the breakdown",
          counts["cacheW1h"] == 24813 and counts["cacheW5m"] == 0)
    fallback = _usage_counts({"cache_creation_input_tokens": 900})
    check("usage: missing breakdown bills the whole write at the 5m rate",
          fallback["cacheW5m"] == 900 and fallback["cacheW1h"] == 0)
    # Observed in real transcripts: total 0 but the breakdown still reports a 1h
    # figure. Trusting the breakdown there inflated cache-write spend by 2,494
    # tokens across one session, so the total must clamp it.
    stale = _usage_counts({"cache_creation_input_tokens": 0,
                           "cache_creation": {"ephemeral_1h_input_tokens": 145,
                                              "ephemeral_5m_input_tokens": 0}})
    check("usage: breakdown exceeding the total is clamped to the total",
          stale["cacheW5m"] + stale["cacheW1h"] == 0)
    partial = _usage_counts({"cache_creation_input_tokens": 100,
                             "cache_creation": {"ephemeral_1h_input_tokens": 400,
                                                "ephemeral_5m_input_tokens": 0}})
    check("usage: over-reported 1h tier clamps without going negative",
          partial["cacheW1h"] == 100 and partial["cacheW5m"] == 0)
    check("usage: negative / garbage counts clamp to 0",
          _usage_counts({"input_tokens": -5, "output_tokens": "x"})["in"] == 0)

    # --- attribution -------------------------------------------------------
    manifest = {"phases": [
        {"id": "P3", "title": "Sharding",
         "claim": {"sessionId": "sess-1"},
         "tasks": [
             {"id": "P3.1", "status": "done",
              "startedAt": "2026-08-06T07:00:00Z",
              "completedAt": "2026-08-06T07:30:00Z"},
             {"id": "P3.2", "status": "in_progress",
              "startedAt": "2026-08-06T07:10:00Z"},
         ]},
        {"id": "P4", "title": "Panel", "tasks": [{"id": "P4.1", "status": "pending"}]},
    ]}
    att = Attributor(manifest, "sess-1")
    check("attr: claimed phase found via claim.sessionId",
          att.claimed_phase is not None and att.claimed_phase["id"] == "P3")
    check("attr: subagent description yields an exact task id",
          att.attribute({"description": "P3.2 shard writer"}, None)
          == ("P3", "P3.2", "task"))
    check("attr: a task id from another phase still resolves",
          att.attribute({"description": "P4.1 panel tab"}, None)
          == ("P4", "P4.1", "task"))
    check("attr: description naming no known task is ignored",
          att.attribute({"description": "Z9.9 nonsense"},
                        parse_ts("2026-08-06T06:00:00Z"))[2] == "phase")
    check("attr: main session outside every window -> phase",
          att.attribute({}, parse_ts("2026-08-06T06:00:00Z")) == ("P3", None, "phase"))
    check("attr: single matching window -> window attribution",
          att.attribute({}, parse_ts("2026-08-06T07:05:00Z"))
          == ("P3", "P3.1", "window"))
    check("attr: overlapping parallel windows collapse to the phase",
          att.attribute({}, parse_ts("2026-08-06T07:20:00Z"))
          == ("P3", None, "phase"))
    unclaimed = Attributor(manifest, "sess-other")
    check("attr: unclaimed session -> unattributed, never dropped",
          unclaimed.attribute({}, parse_ts("2026-08-06T07:20:00Z"))
          == (None, None, "unattributed"))
    check("attr: subagent label still works for an unclaimed session",
          unclaimed.attribute({"description": "P3.2 x"}, None)
          == ("P3", "P3.2", "task"))

    # --- author ------------------------------------------------------------
    check("author: none mode returns None", resolve_author(".", "none") is None)
    h = resolve_author(".", "hash")
    check("author: hash mode is pseudonymous and stable",
          isinstance(h, str) and h.startswith("anon-")
          and h == resolve_author(".", "hash"))

    tmp = tempfile.mkdtemp(prefix="usage-ledger-selftest-")
    try:
        # --- scanning: the dedup trap -------------------------------------
        proj = os.path.join(tmp, "projects")
        os.makedirs(proj)
        main = os.path.join(proj, "sess-1.jsonl")

        def entry(mid, ts, out_tokens, model="claude-opus-5"):
            return json.dumps({
                "type": "assistant", "timestamp": ts, "gitBranch": "audit/p3",
                "message": {"id": mid, "model": model, "usage": {
                    "input_tokens": 1, "output_tokens": out_tokens,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 10}}})

        with open(main, "w", encoding="utf-8") as fh:
            # msg-A repeated 3x (the real-world shape), msg-B once
            for _ in range(3):
                fh.write(entry("msg-A", "2026-08-06T07:20:10.266Z", 100) + "\n")
            fh.write(entry("msg-B", "2026-08-06T07:25:00Z", 50) + "\n")
            fh.write("{ this line is not json\n")
            fh.write(json.dumps({"type": "user", "message": {}}) + "\n")

        opts = {"repo": "demo", "backfillOnFirstRun": True}
        rows, cur = scan_transcripts(main, "sess-1", {}, manifest, opts)
        agg = totals(rows)
        check("scan: repeated message.id counted ONCE (out == 150, not 350)",
              agg["out"] == 150, "got %s" % agg["out"])
        check("scan: msgs counts unique messages", agg["msgs"] == 2)
        check("scan: malformed line tolerated, scan continues", agg["in"] == 2)
        check("scan: non-assistant entries ignored", agg["tokens"] == 2 + 150 + 20)

        # --- scanning: cursor resume --------------------------------------
        rows2, cur2 = scan_transcripts(main, "sess-1", cur, manifest, opts)
        check("scan: re-scan with cursor yields nothing new", rows2 == [])
        with open(main, "a", encoding="utf-8") as fh:
            fh.write(entry("msg-C", "2026-08-06T08:05:00Z", 7) + "\n")
        rows3, cur3 = scan_transcripts(main, "sess-1", cur2, manifest, opts)
        check("scan: appended entry picked up incrementally",
              totals(rows3)["out"] == 7)
        check("scan: new hour lands in its own bucket",
              rows3 and rows3[0]["ts"] == "2026-08-06T08")

        # --- scanning: duplicate split across a chunk boundary -------------
        split_path = os.path.join(proj, "sess-split.jsonl")
        with open(split_path, "w", encoding="utf-8") as fh:
            fh.write(entry("msg-D", "2026-08-06T07:00:00Z", 11) + "\n")
        r_a, c_a = scan_transcripts(split_path, "sess-1", {}, manifest, opts)
        with open(split_path, "a", encoding="utf-8") as fh:
            fh.write(entry("msg-D", "2026-08-06T07:00:00Z", 11) + "\n")
        r_b, _ = scan_transcripts(split_path, "sess-1", c_a, manifest, opts)
        check("scan: duplicate spanning two scans is caught by the recent ring",
              totals(r_a + r_b)["out"] == 11,
              "got %s" % totals(r_a + r_b)["out"])

        # --- scanning: partial trailing line -------------------------------
        partial = os.path.join(proj, "sess-partial.jsonl")
        with open(partial, "w", encoding="utf-8") as fh:
            fh.write(entry("msg-E", "2026-08-06T07:00:00Z", 5) + "\n")
            fh.write(entry("msg-F", "2026-08-06T07:00:00Z", 5)[:20])  # torn
        r_p, c_p = scan_transcripts(partial, "sess-1", {}, manifest, opts)
        check("scan: torn trailing line is not consumed",
              totals(r_p)["out"] == 5)
        with open(partial, "a", encoding="utf-8") as fh:
            fh.write(entry("msg-F", "2026-08-06T07:00:00Z", 5)[20:] + "\n")
        r_p2, _ = scan_transcripts(partial, "sess-1", c_p, manifest, opts)
        check("scan: completed line is picked up on the next pass",
              totals(r_p2)["out"] == 5)

        # --- scanning: subagents + parallel attribution --------------------
        sub = os.path.join(proj, "sess-1", "subagents")
        os.makedirs(sub)
        for aid, task, out_tokens in (("a1", "P3.1", 1000), ("a2", "P3.2", 2000)):
            with open(os.path.join(sub, "agent-%s.jsonl" % aid), "w",
                      encoding="utf-8") as fh:
                fh.write(entry("m-%s" % aid, "2026-08-06T07:20:00Z",
                               out_tokens, "claude-haiku-4-5") + "\n")
            with open(os.path.join(sub, "agent-%s.meta.json" % aid), "w",
                      encoding="utf-8") as fh:
                json.dump({"agentType": "audit-executor",
                           "description": "%s do the thing" % task,
                           "toolUseId": "toolu_x", "spawnDepth": 1}, fh)
        rows4, _ = scan_transcripts(main, "sess-1", cur3, manifest, opts)
        by_task = aggregate(rows4, "task")
        check("scan: parallel subagents attributed to distinct tasks",
              by_task.get("P3.1", {}).get("out") == 1000
              and by_task.get("P3.2", {}).get("out") == 2000)
        check("scan: subagent agentType recorded",
              all(r["agentType"] == "audit-executor" for r in rows4))
        check("scan: subagent model priced separately from the orchestrator",
              aggregate(rows4, "model").get("claude-haiku-4-5", {}).get("msgs") == 2)

        # --- backfill sizing guard ----------------------------------------
        rows5, _ = scan_transcripts(
            main, "sess-1", {}, manifest,
            {"repo": "demo", "backfillOnFirstRun": True, "maxScanBytes": 10})
        check("scan: oversized transcript on first sight skips history",
              rows5 == [])
        rows6, _ = scan_transcripts(
            main, "sess-1", {}, manifest,
            {"repo": "demo", "backfillOnFirstRun": False})
        check("scan: backfillOnFirstRun=False starts at EOF", rows6 == [])

        # --- ledger I/O ----------------------------------------------------
        ledger = os.path.join(tmp, "usage")
        all_rows, _ = scan_transcripts(main, "sess-1", {}, manifest, opts)
        n = append_rows(ledger, all_rows)
        check("ledger: append writes one line per row", n == len(all_rows))
        check("ledger: monthly file named after the bucket",
              os.path.isfile(os.path.join(ledger, "2026-08.jsonl")))
        back = read_ledger(ledger)
        check("ledger: round-trips", totals(back) == totals(all_rows))
        check("ledger: --since filters by date",
              totals(read_ledger(ledger, since="2026-08-06"))["msgs"]
              == totals(back)["msgs"])
        check("ledger: --since in the future returns nothing",
              read_ledger(ledger, since="2099-01-01") == [])
        check("ledger: --until in the past returns nothing",
              read_ledger(ledger, until="1999-01-01") == [])
        with open(os.path.join(ledger, "2026-08.jsonl"), "a",
                  encoding="utf-8") as fh:
            fh.write("{ torn line\n")
        check("ledger: torn line tolerated on read",
              totals(read_ledger(ledger)) == totals(all_rows))

        # --- cursor persistence -------------------------------------------
        save_cursor(ledger, "sess-1", {"author": "a@b.c", "files": {}})
        check("cursor: round-trips",
              load_cursor(ledger, "sess-1").get("author") == "a@b.c")
        check("cursor: missing cursor -> {}",
              load_cursor(ledger, "nope") == {})
        # Ledger discovery must never GUESS. The fixed-depth version of this
        # resolved examples/acme-store/audit-plan.json to the enclosing repo and
        # rendered that project's spend under the example's name.
        deep = os.path.join(tmp, "proj", "docs", "audit")
        os.makedirs(os.path.join(tmp, "proj", ".claude", "usage"), exist_ok=True)
        os.makedirs(deep, exist_ok=True)
        flat = os.path.join(tmp, "proj", "sub")
        os.makedirs(os.path.join(flat, ".claude", "usage"), exist_ok=True)
        check("discover: docs/audit/<m>.json finds the repo-root ledger",
              find_ledger_dir(os.path.join(deep, "m.json"), ".claude/usage")
              == os.path.join(tmp, "proj", ".claude", "usage"))
        check("discover: a manifest beside its own ledger prefers THAT one",
              find_ledger_dir(os.path.join(flat, "m.json"), ".claude/usage")
              == os.path.join(flat, ".claude", "usage"))
        check("discover: no ledger anywhere -> None, never a guessed ancestor",
              find_ledger_dir(os.path.join(tmp, "elsewhere", "m.json"),
                              ".claude/nonexistent") is None)
        check("discover: an explicit project dir always wins",
              find_ledger_dir(os.path.join(flat, "m.json"), ".claude/usage",
                              os.path.join(tmp, "proj"))
              == os.path.join(tmp, "proj", ".claude", "usage"))

        check("cursor: lives outside stateDir, next to the ledger",
              os.path.isfile(os.path.join(ledger, ".cursors", "sess-1.json")))

        # --- backfill idempotency ------------------------------------------
        month_rows = read_ledger(ledger)
        before = totals(month_rows)
        fresh, _ = scan_transcripts(main, "sess-1", {}, manifest, opts)
        kept = [r for r in month_rows if r.get("sessionId") != "sess-1"]
        rewrite_month(ledger, "2026-08", kept + fresh)
        check("backfill: rebuild is idempotent (totals unchanged)",
              totals(read_ledger(ledger)) == before)

        # --- aggregation ----------------------------------------------------
        agg_all = totals(all_rows)
        check("agg: tokens is the sum of every token key",
              agg_all["tokens"] == sum(agg_all[k] for k in TOKEN_KEYS))
        check("agg: cache hit pct in range",
              0.0 <= agg_all["cacheHitPct"] <= 100.0)
        check("agg: unknown group key raises",
              _raises(lambda: aggregate(all_rows, "nope")))
        by_attr = aggregate(all_rows, "attr")
        check("agg: every row carries an attribution bucket",
              sum(v["msgs"] for v in by_attr.values()) == agg_all["msgs"])
        grid = heatmap(all_rows)
        check("agg: heatmap is 7x24", len(grid) == 7 and len(grid[0]) == 24)
        check("agg: heatmap totals match", sum(sum(r) for r in grid) == agg_all["tokens"])

        # --- analytics: the honesty guards --------------------------------
        def mkrow(day, model, author, task, phase, attr, cost, out_tok=100,
                  cr=1000, cw=100, fin=10):
            return {"ts": "2026-08-%02dT10" % day, "model": model, "author": author,
                    "taskId": task, "phaseId": phase, "attr": attr,
                    "sessionId": "s1", "agentType": "audit-executor", "msgs": 1,
                    "in": fin, "out": out_tok, "cacheW5m": cw, "cacheW1h": 0,
                    "cacheR": cr, "costUSD": cost}

        man = {"phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "done", "risk": "high", "attempts": 1},
            {"id": "P1.2", "status": "done", "risk": "high", "attempts": 3},
            {"id": "P1.3", "status": "done", "risk": "low", "attempts": 1},
            {"id": "P1.4", "status": "done", "risk": "low", "attempts": 1},
            {"id": "P1.5", "status": "done", "risk": "med", "attempts": 1},
            {"id": "P1.6", "status": "blocked", "risk": "med", "attempts": 3},
            {"id": "P1.7", "status": "pending", "risk": "low"},
        ]}]}
        ar = [
            mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
            mkrow(2, "claude-opus-5", "a@x", "P1.2", "P1", "task", 30.0),
            mkrow(3, "claude-haiku-4-5", "b@x", "P1.3", "P1", "task", 1.0),
            mkrow(4, "claude-haiku-4-5", "b@x", "P1.4", "P1", "task", 2.0),
            mkrow(5, "claude-sonnet-5", "c@x", "P1.5", "P1", "task", 5.0),
            mkrow(6, "claude-sonnet-5", "c@x", "P1.6", "P1", "task", 7.0),
            mkrow(7, "claude-opus-5", "a@x", None, None, "unattributed", 4.0),
        ]

        # series: top-N fold
        s = series(ar, "model")
        check("series: buckets sorted, one value per bucket per entity",
              s["buckets"] == sorted(s["buckets"])
              and all(len(e["values"]) == len(s["buckets"]) for e in s["entities"]))
        check("series: values sum back to each entity total",
              all(sum(e["values"]) == e["total"] for e in s["entities"]))
        many = [mkrow(1, "m%02d" % i, "a@x", None, None, "unattributed", 1.0)
                for i in range(12)]
        sm = series(many, "model", top=8)
        check("series: past 8 entities the tail folds into 'other', never a 9th hue",
              len(sm["entities"]) == 9 and sm["entities"][-1]["key"] == "other"
              and sm["folded"] == 4)
        check("series: folding preserves the grand total",
              sum(e["total"] for e in sm["entities"]) == sum(_tokens(r) for r in many))

        # compare: no prior period -> no invented delta
        c_none = compare(ar, "2026-08-01", "2026-08-07")
        check("compare: no prior window -> prior None and no deltas",
              c_none["prior"] is None and c_none["deltas"] == {})
        c_some = compare(ar, "2026-08-05", "2026-08-07")
        check("compare: a real prior window yields deltas",
              c_some["prior"] is not None and "tokens" in c_some["deltas"])
        check("compare: a zero-valued prior metric yields None, not a division blow-up",
              compare(ar, "2026-08-01", "2026-08-02")["deltas"] in ({}, None)
              or all(v is None or isinstance(v, float)
                     for v in compare(ar, "2026-08-05", "2026-08-07")["deltas"].values()))

        # cache_profile: rates, never a fabricated dollar saving
        cp = cache_profile(ar)
        check("cache: reports a hit rate and a rate comparison",
              0 <= cp["hitPct"] <= 100 and 0 < cp["inputCostVsFreshPct"] <= 100)
        check("cache: exposes NO fabricated dollar saving",
              not any("sav" in k.lower() or k.endswith("USD") for k in cp))
        check("cache: per-phase rates and a worst phase for the story",
              "P1" in cp["byPhase"] and cp["worstPhase"] is not None)

        # unit_economics: the sample gate
        few = unit_economics({"phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "done"}]}]},
            [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 5.0)])
        check("unit: projection SUPPRESSED below the sample gate",
              few["projection"] is None and few["sufficient"] is False
              and few["gate"] == MIN_TASKS_FOR_PROJECTION)
        ue = unit_economics(man, ar)
        check("unit: 5 completed tasks clears the gate", ue["sufficient"] is True)
        check("unit: projection is a p25-p75 RANGE, never a point estimate",
              ue["projection"] and ue["projection"]["low"] <= ue["projection"]["high"])
        check("unit: only DONE tasks count toward cost-per-task",
              ue["completed"] == 5)
        check("unit: remaining counts pending + in_progress + blocked",
              ue["remaining"] == 2)
        check("unit: most-expensive list carries attempts for context",
              ue["mostExpensive"] and len(ue["mostExpensive"][0]) == 3)

        # routing advice: fires only when THIS repo's own evidence supports it.
        # Both fixtures above route one model per band, so neither produces advice
        # — a well-routed project getting silence is the point, not a gap.
        def band(model, n, attempts, out_tok, risk="low", first=0):
            man_tasks = [{"id": "R%s%d" % (model[7:10], i), "status": "done",
                          "risk": risk, "attempts": attempts} for i in range(n)]
            rws = [mkrow(1 + first, model, "a@x", t["id"], "PR", "task", 0.0,
                         out_tok=out_tok) for t in man_tasks]
            return man_tasks, rws

        o_t, o_r = band("claude-opus-5", 5, 1, 200_000)
        s_t, s_r = band("claude-sonnet-5", 4, 1, 200_000)
        rman = {"phases": [{"id": "PR", "tasks": o_t + s_t}]}
        adv = routing(rman, o_r + s_r)["advice"]
        check("advice: a within-band cheaper model with real evidence is named",
              len(adv) == 1 and adv[0]["from"] == "claude-opus-5"
              and adv[0]["to"] == "claude-sonnet-5" and adv[0]["risk"] == "low",
              adv)
        # The three figures must reconcile EXACTLY: a reader who subtracts the two
        # displayed costs has to land on the displayed saving, to the cent.
        check("advice: both sides priced on the SAME tokens at today's rates, and "
              "the arithmetic on screen adds up exactly",
              adv and adv[0]["atFromRates"] > adv[0]["atToRates"] > 0
              and adv[0]["saving"] == round(
                  adv[0]["atFromRates"] - adv[0]["atToRates"], 2)
              and adv[0]["savingPct"] == round(
                  100.0 * adv[0]["saving"] / adv[0]["atFromRates"], 1),
              adv)
        check("advice: it carries the in-repo evidence it rests on",
              adv and adv[0]["evidenceTasks"] == 4
              and adv[0]["evidenceAttempts"] == 1.0 and adv[0]["tasks"] == 5)

        # Each gate, alone, must silence it.
        s2_t, s2_r = band("claude-sonnet-5", 2, 1, 200_000)
        check("advice: SILENT when the cheaper model has too little in-repo "
              "evidence (a price list is not a finding)",
              routing({"phases": [{"id": "PR", "tasks": o_t + s2_t}]},
                      o_r + s2_r)["advice"] == [])
        s3_t, s3_r = band("claude-sonnet-5", 4, 2, 200_000)
        check("advice: SILENT when the cheaper model retries more — a model that "
              "needs two attempts is not cheaper",
              routing({"phases": [{"id": "PR", "tasks": o_t + s3_t}]},
                      o_r + s3_r)["advice"] == [])
        tiny_o, tiny_or = band("claude-opus-5", 5, 1, 100)
        tiny_s, tiny_sr = band("claude-sonnet-5", 4, 1, 100)
        check("advice: SILENT when the saving is below the absolute floor",
              routing({"phases": [{"id": "PR", "tasks": tiny_o + tiny_s}]},
                      tiny_or + tiny_sr)["advice"] == [])
        x_t, x_r = band("claude-mystery-9", 4, 1, 200_000)
        check("advice: SILENT for a model with no real rates — never recommend a "
              "move onto a price that is a _default guess",
              _has_rates("claude-mystery-9") is False
              and routing({"phases": [{"id": "PR", "tasks": o_t + x_t}]},
                          o_r + x_r)["advice"] == [])
        # Cross-band comparison is the thing the whole table exists to refuse.
        hi_t, hi_r = band("claude-sonnet-5", 4, 1, 200_000, risk="high")
        check("advice: never compares ACROSS risk bands",
              all(a["risk"] == "low" for a in routing(
                  {"phases": [{"id": "PR", "tasks": o_t + hi_t}]},
                  o_r + hi_r)["advice"]))

        # cost_bands: the same sample gate, and a name that does not collide
        cb = cost_bands(man, ar)
        check("bands: 5 completed tasks clears the gate on the relative basis",
              cb["basis"] == "relative" and cb["sufficient"] is True
              and cb["sample"] == 5)
        _ti = task_index(man)
        _done_cost = {}
        for _r in ar:
            _t = _r.get("taskId")
            if _t and (_ti.get(_t) or {}).get("status") == "done":
                _done_cost[_t] = _done_cost.get(_t, 0.0) + _r["costUSD"]
        _dc = list(_done_cost.values())
        check("bands: thresholds ARE the project's own median and p90 "
              "(computed from completed tasks only)",
              cb["high"] == round(_percentile(_dc, 50), 4)
              and cb["outlier"] == round(_percentile(_dc, 90), 4)
              and cb["high"] <= cb["outlier"])
        check("bands: every classified task lands in exactly one band",
              sum(cb["counts"].values()) == len(cb["byTask"])
              and set(cb["byTask"].values()) <= set(BAND_ORDER))
        cb_few = cost_bands({"phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "done"}]}]},
            [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 5.0)])
        check("bands: SUPPRESSED below the gate — no basis, no classification",
              cb_few["basis"] is None and cb_few["sufficient"] is False
              and cb_few["byTask"] == {}
              and cb_few["gate"] == MIN_TASKS_FOR_PROJECTION)
        check("bands: band_of returns None while suppressed, so callers cannot "
              "accidentally render a band that was never computed",
              band_of(cb_few, "P1.1") is None and band_of(None, "P1.1") is None)
        # A configured threshold is an opinion the user already holds, so it needs
        # no sample — but a malformed one must never classify anything.
        cb_abs = cost_bands(cb_few and {"phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "done"}]}]},
            [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 40.0)],
            {"bands": {"highUSD": 5, "outlierUSD": 20}})
        check("bands: an absolute basis needs no sample and is labelled as such",
              cb_abs["basis"] == "absolute" and cb_abs["sufficient"] is True
              and cb_abs["byTask"]["P1.1"] == "outlier")
        for bad in ({"highUSD": "x", "outlierUSD": 20}, {"highUSD": 50, "outlierUSD": 10},
                    {"highUSD": 0, "outlierUSD": 10}, {"highUSD": 5}):
            got = cost_bands(man, ar, {"bands": bad})
            if got["basis"] != "relative":
                break
        else:
            bad = None
        check("bands: a garbled or inverted threshold pair falls back to the "
              "relative basis instead of classifying wrongly", bad is None)
        check("bands: the word 'risk' is not reused — that axis already exists",
              "risk" not in cb and set(BAND_ORDER) == {"typical", "high", "outlier"})

        # phase_budgets: an absent budget is "—", never 0% and never 100%.
        # Explicit rows, so the assertions do not silently depend on what some
        # other fixture happens to price out to.
        _brows = [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
                  mkrow(2, "claude-opus-5", "a@x", "P2.1", "P2", "task", 13.0),
                  mkrow(3, "claude-opus-5", "a@x", None, "P3", "phase", 99.0)]
        pb = phase_budgets({"phases": [
            {"id": "P1", "title": "Alpha", "budgetUSD": 40, "tasks": []},
            {"id": "P2", "title": "Beta", "budgetUSD": 10, "tasks": []},
            {"id": "P3", "title": "Gamma", "tasks": []}]}, _brows)
        _byid = {p["id"]: p for p in pb["phases"]}
        check("budget: a phase without one reports None, not zero",
              _byid["P3"]["budget"] is None and _byid["P3"]["pct"] is None
              and _byid["P3"]["over"] is False and _byid["P3"]["spent"] == 99.0)
        check("budget: spend is summed per phase from the ledger",
              _byid["P1"]["spent"] == 10.0 and _byid["P1"]["pct"] == 25.0
              and _byid["P1"]["over"] is False)
        check("budget: pct is uncapped so an overrun reads as an overrun",
              _byid["P2"]["pct"] == 130.0 and _byid["P2"]["over"] is True)
        check("budget: totals cover only the phases that declared a budget "
              "(P3's 99.0 must not inflate them)",
              pb["budgeted"] == 2 and pb["totalBudget"] == 50.0
              and pb["totalSpent"] == 23.0 and pb["anyOver"] is True)
        check("budget: a zero, negative, boolean or string budget is no budget",
              all(phase_budgets({"phases": [dict(
                  {"id": "P1", "tasks": []}, budgetUSD=bad)]},
                  ar)["phases"][0]["budget"] is None
                  for bad in (0, -5, True, False, "40", None)))
        check("budget: no budgets anywhere -> totals are None, not 0",
              phase_budgets({"phases": [{"id": "P1", "tasks": []}]},
                            ar)["totalBudget"] is None)

        # retry_cost: retried and blocked reported apart, never summed
        rc = retry_cost(man, ar)
        check("retry: retried and blocked are SEPARATE figures",
              rc["retriedCost"] == 37.0 and rc["blockedCost"] == 7.0)
        check("retry: no combined 'waste' key exists to be misread",
              not any("waste" in k.lower() for k in rc))
        check("retry: the overlap between the two sets is stated, not hidden",
              rc["overlaps"] == 1)
        check("retry: percentages are of total spend",
              abs(rc["retriedPct"] - 100.0 * 37.0 / 59.0) < 0.2)

        # routing: within-risk comparison, no bare ratio
        rt = routing(man, ar)
        check("routing: grouped by risk band, then model",
              "high" in rt["byRisk"] and "claude-opus-5" in rt["byRisk"]["high"])
        check("routing: exposes NO spend-share/task-share ratio",
              not any("ratio" in k.lower() for cells in rt["byRisk"].values()
                      for cell in cells.values() for k in cell))
        check("routing: carries cost-per-task and mean attempts per cell",
              rt["byRisk"]["high"]["claude-opus-5"]["costPerTask"] == 20.0
              and rt["byRisk"]["high"]["claude-opus-5"]["meanAttempts"] == 2.0)
        check("routing: models come from the LEDGER, not manifest tiers",
              all(m.startswith("claude-") for m in rt["models"]))
        check("routing: risks are ordered high -> low, not alphabetical",
              rt["risks"] == ["high", "med", "low"])

        # coverage
        cv = coverage(ar)
        check("coverage: task-level share never exceeds attributed share",
              0 < cv["taskLevelPct"] <= cv["attributedPct"] <= 100)
        # phase-level spend is attributed but NOT task-level — the gap between the
        # two numbers is exactly the orchestrator's own turns
        cv2 = coverage(ar + [mkrow(8, "claude-opus-5", "a@x", None, "P1", "phase", 3.0)])
        check("coverage: phase-attributed spend counts as attributed, not task-level",
              cv2["taskLevelPct"] < cv2["attributedPct"])
        check("coverage: shares across attribution buckets sum to 100",
              abs(sum(cv2["byAttr"].values()) - 100.0) < 0.2, repr(cv2["byAttr"]))
        check("coverage: does not warn on a well-attributed ledger",
              cv["warn"] is False)
        bad = coverage([mkrow(1, "m", "a@x", None, None, "unattributed", 1.0)])
        check("coverage: warns when unattributed dominates",
              bad["warn"] is True and bad["attributedPct"] == 0.0)
        check("coverage: empty ledger is not a crash", coverage([])["total"] == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, detail in cases:
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           (" (%s)" % detail) if (detail and not ok) else ""))
    print("\nusage_ledger: %d/%d cases passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: usage_ledger.py --selftest\n")
    raise SystemExit(2)
