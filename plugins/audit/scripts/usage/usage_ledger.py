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

The repeats are not always identical. A main-session transcript's repeats of one id
are byte-identical; a SUBAGENT's are not — its `output_tokens` grows across the
repeats of an id, with or without a `stop_reason`, and keeping only the first entry
seen for an id counted it at a fraction of what it actually spent (measured on the
testbed and on this repo's own subagent transcripts: output summed from the first
line of each repeated id came in under half the sum from the final line). So the
cursor carries, for every id still in the ring, the per-field counts already added
to the ledger; a later entry for that id — same scan or a later one — adds only its
field-wise excess over those counts, never a negative figure, and never a second
message. An id that leaves the ring drops its counts with it. See `_scan_file` for
why that, and not "count only the final entry" or "trust `stop_reason`".

Attribution, highest precision first (nothing is ever dropped):

  1. task          - the subagent's `.meta.json` description starts with a task id.
                     Exact even when a phase runs several tasks in parallel, because
                     each subagent owns a separate transcript file.
                     An agent that is CONTINUED rather than replaced keeps that
                     description for ever, so a message handed to a running agent
                     may name the next task on its first line and everything it
                     spends afterwards lands there instead. A message naming no
                     task changes nothing: the description still answers.
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
`--backfill` re-scan produces the same shape as incremental metering. Summing
loses one thing a bucket cannot recover afterwards: how big any SINGLE turn
inside it was. `maxContext` is carried alongside the summed token fields for
exactly that reason — the largest `in + cacheW5m + cacheW1h + cacheR` seen
across the messages a row folds together, which is what lets a reader ask "how
much context was this run actually carrying" rather than only "how much did it
read in total". A row written before this field existed carries no such key at
all, which `_usage_economics.context_shape` reads as "cannot answer", never as
zero.

Storage (see the plugin README "Usage" section):

    <ledgerDir>/YYYY-MM.jsonl        append-only monthly ledger
    <ledgerDir>/.cursors/<sid>.json  per-session scan cursors + resolved author,
                                     and `cliCost`: the CLI's own last
                                     `cost-state` reading, kept by the scan
    <ledgerDir>/.notices/<sid>.json  which unpriced-model notices SessionStart
                                     already gave, per session and model

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
`tests/test_usage_ledger.py`, byte-identical labels and all - see
`tests/_harness.py`. `rx1`/`rx2` still count the re-export, now
against the module object a by-path loader hands back, which is what every
consumer actually holds.
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import errno
import sys
import time

# The month lock's two halves: one of these exists on every platform this runs on.
try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

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
# The module itself as well, for its private `_rate_via`: the `from` list below
# must name exactly the public names it re-exports, which a suite reads by AST.
import _usage_core as _core  # noqa: E402

# The re-export. These names were defined in this file until the split and are read
# off this module by audit-usage.py, _report_usage.py, _panel_state.py,
# audit-status.py, audit-doctor.py, panel-server.py, gen-demo-usage.py,
# hooks/_config.py and hooks/meter-usage.py. `_selftest` asserts the two lists below
# still cover every public name those modules define, so a name added down there and
# forgotten here fails by name instead of at a call site.
from _usage_core import (  # noqa: E402,F401  (re-exported, see above)
    DEFAULT_PRICING, GROUP_KEYS, LONG_PROMPT_RATES, LONG_PROMPT_SUFFIX,
    LONG_PROMPT_THRESHOLD_TOKENS, PRICING_AS_OF, PRICING_BASES,
    PRICING_SOURCE_URL, TOKEN_KEYS, UNTAGGED_AREA, aggregate, aggregate_area,
    bucket_date, bucket_hour, bucket_month, heatmap, hour_bucket, parse_ts, price,
    priced_at_read, pricing_divergences, pricing_provenance_divergences,
    rate_for_stamp, rates_for, resolve_pricing, rows_for_area, task_index,
    tiered_model_key, totals)
from _usage_coverage import (  # noqa: E402,F401  (re-exported, see above)
    MONTHLY_PLAN_KEYS, POOR_COVERAGE_PCT, coverage, monthly_activity)
from _usage_economics import (  # noqa: E402,F401  (re-exported, see above)
    BAND_ORDER, CANNOT_COMPARE, COST_BAND_PARAMS, MIN_TASKS_FOR_PROJECTION,
    ROUTING_BASIS, SIBLING_GATE, all_unpriced, band_of, context_shape,
    cost_bands, coverage_sentence, gate_catches, gate_reuse_comparison,
    gate_scope_comparison, phase_budgets, plan_cost_claim, rate_basis_phrase,
    retry_cost, sibling_spend_comparison, unit_economics, unpriced_phrase)
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
def main_transcript_path(session_id, home=None):
    """The MAIN-session transcript for `session_id`, or `None` when
    `session_id` is falsy or nothing matches.

    Found by globbing every project directory Claude Code knows about rather
    than by deriving the one project slug `audit-usage.py`'s own discovery
    needs: a session id is a UUID, so `<home>/projects/*/<sessionId>.jsonl`
    is unambiguous on its own and needs no project path at all - which is
    what lets a live orchestrator ask for its OWN transcript with nothing
    more than the session id Bash already has in its environment."""
    if not session_id:
        return None
    home = home or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    matches = sorted(glob.glob(os.path.join(home, "projects", "*",
                                            str(session_id) + ".jsonl")))
    return matches[0] if matches else None


def previous_session_transcript(data):
    """The most recently-modified OTHER main-session transcript beside a
    SessionStart payload's own `transcript_path` -> absolute path, or None.

    A SessionStart payload already names the right project directory in
    `transcript_path` - Claude Code resolved whatever slug scheme applies,
    so this walks SIBLINGS of it rather than re-deriving one. The payload's
    own `session_id` excludes that file by NAME, never by mtime: a brand new
    session's transcript may not exist on disk yet, and even if it does, an
    empty file just created can still sort newest on some filesystems.

    None when `transcript_path` is absent, its directory cannot be listed, or
    it holds no other `.jsonl` file - never raises."""
    transcript = (data or {}).get("transcript_path")
    if not transcript:
        return None
    session_id = str((data or {}).get("session_id") or "")
    base = os.path.dirname(transcript)
    try:
        names = os.listdir(base)
    except OSError:
        return None
    candidates = []
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        if os.path.splitext(name)[0] == session_id:
            continue
        path = os.path.join(base, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        candidates.append((mtime, path))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def current_context_size(transcript_path):
    """`(tokens, model, reason)` for the MOST RECENT assistant turn a MAIN
    transcript carries.

    `tokens` is `_context_of` applied to that turn's `message.usage` block -
    a SNAPSHOT of the last turn seen, never a running sum: what a next
    request would carry forward is set by the size of the last turn alone,
    not by everything that came before it. `model` is that same turn's
    `message.model`.

    `tokens` is `None` - never a number standing in for one that was not
    measured - when the file cannot be opened or carries no assistant usage
    yet; `reason` then names which, in words a caller can print as the
    basis for 'unknown'. `reason` is `None` only when `tokens` is a real
    reading."""
    last_usage, last_model, seen = None, None, False
    try:
        with open(transcript_path, "rb") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw.decode("utf-8", "replace"))
                except Exception:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant":
                    continue
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                last_usage, last_model, seen = usage, message.get("model"), True
    except OSError as exc:
        return None, None, "transcript %s cannot be read (%s)" % (
            transcript_path, exc)
    if not seen:
        return None, None, "transcript %s carries no assistant usage yet" % (
            transcript_path,)
    return _context_of(_usage_counts(last_usage)), last_model, None


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
# The id, then an optional hyphenated tail captured SEPARATELY: `P4.2-k7m` is a
# task minted off the development branch (`_id_shape`'s suffix), while
# `P4.1-fix the tab` is P4.1 followed by a word. Only the manifest can tell the
# two apart, so both readings are offered and MEMBERSHIP decides - which is also
# why the tail is any hyphenated word rather than the suffix's own pattern: that
# spelling lives in `_manifest_vocab`, which nothing on this per-tool-call hook
# path may load, and membership needs no second copy of it.
_TASK_ID_RE = re.compile(r"([A-Za-z]{1,4}\d+(?:-[0-9a-z]+)?\.\d+)(-[0-9a-z]+)?")

# A MESSAGE HANDED TO AN AGENT THAT IS ALREADY RUNNING, which is what an
# orchestrator sends instead of spawning a replacement. `origin.kind` is the only
# field that tells such an entry from the spawn prompt, from a tool result and
# from a skill the harness injected -- all of which are `type: "user"` too, and
# the first of which is also the only other `user` entry carrying no
# `toolUseResult`. Read out of live transcripts rather than assumed: every entry
# of these kinds carried a plain-string `message.content` opening with the lead
# line below, and the spawn prompt carried no `origin` at all.
CONTINUATION_ORIGINS = ("coordinator", "human")

# What the harness writes ahead of the sender's own text. The sender's first line
# is therefore the second line of the entry, and stripping this is what makes the
# convention writable by a human: "put the task id first" has to mean first in
# the message, not first after an envelope nobody typed. An envelope this does
# not recognise is left in place on purpose -- the first line is then the
# envelope, it names no task, and attribution stays where the spawn description
# put it, which is the direction that invents nothing.
CONTINUATION_LEADS = (
    "The coordinator sent a message while you were working:",
    "The user sent a new message while you were working:")


def message_text(entry):
    """The text of a transcript entry's message, as one string.

    Both content shapes, because the transcript uses both: a plain string for the
    messages this module reads, and a list of typed blocks elsewhere. A shape
    this does not know yields the empty string rather than a repr -- a repr would
    make a dict's key order part of what a task id is matched against.
    """
    message = (entry or {}).get("message") if isinstance(entry, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text") or "" for block in content
                       if isinstance(block, dict) and block.get("type") == "text")
    return ""


def continuation_line(entry):
    """The first line the SENDER wrote in a message handed to a running agent,
    or None when `entry` is not one of those.

    None for every other entry, and that is the whole discrimination: a spawn
    prompt, a tool result and an injected skill are all `type: "user"`, and
    reading any of them as a hand-off would move a task's spend onto whatever id
    happened to appear in a tool's output.
    """
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return None
    origin = entry.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    if kind not in CONTINUATION_ORIGINS:
        return None
    text = message_text(entry)
    for lead in CONTINUATION_LEADS:
        if text.startswith(lead):
            text = text[len(lead):]
            break
    for line in text.split("\n"):
        if line.strip():
            return line.strip()
    return None


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
        # `{task id: phase id}` is exactly what `_manifest_io` owns, down to the truthy-id
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
        for base, suffix in _TASK_ID_RE.findall(description[:64]):
            for candidate in ((base + suffix, base) if suffix else (base,)):
                if candidate in self.phase_of_task:
                    return candidate
        return None

    def task_from_handoff(self, entry):
        """The task a message sent to a RUNNING agent names on its first line,
        when it names one this manifest knows.

        THE SAME CONVENTION AS THE SPAWN DESCRIPTION, deliberately read by the
        same function: an agent given a second task keeps the transcript and the
        `.meta.json` of the first, so the description is the only label it has
        and every token it spends afterwards reads as the first task's. The
        follow-up message is the one place the second task can be named, and a
        convention that differed from the spawn description's would be a second
        thing for an orchestrator to remember and a second thing to get wrong.
        """
        return self.task_from_description(continuation_line(entry))

    def attribute(self, agent_meta, ts_epoch, handoff=None):
        """-> (phaseId, taskId, attribution). Never raises, never returns None.

        `handoff` is the task the last message to this agent named, and it comes
        FIRST because it is the more recent fact: the description says what the
        agent was spawned for, the hand-off says what it was asked for since. A
        hand-off naming nothing changes nothing -- the description still answers,
        which keeps a coarse attribution rather than inventing a precise one.
        """
        if handoff and handoff in self.phase_of_task:
            return self.phase_of_task.get(handoff), handoff, "task"
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
def is_model_id(model):
    """Whether `model` names a model at all. The host stamps its own
    placeholder turns (`<synthetic>`, the API-error stand-ins) with an id in
    angle brackets; those carry no price because they are not a model, so no
    surface may call one "unpriced". The scan skips them and the two
    unpriced-model checks leave them out, all through this one reading."""
    return isinstance(model, str) and bool(model) and not model.startswith("<")


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


# Tokens read for the FIRST time on a turn (and so newly written to cache) versus
# tokens pulled back OUT of the cache because they were already read on some
# earlier turn. Both are named here once so `_context_of` and every reader of a
# finished row agree on which raw fields make up which half.
NEW_KEYS = ("in", "cacheW5m", "cacheW1h")
REREAD_KEY = "cacheR"


def _context_of(counts):
    """The size of the prompt ONE turn actually carried: every token billed for
    it, read or re-read alike. `counts` is `_usage_counts`'s own return shape (or
    a ledger row, which carries the same four fields under the same names) —
    `out` is excluded on purpose, because generated tokens are not context a
    later turn has to carry forward."""
    return (sum(int(counts.get(k) or 0) for k in NEW_KEYS)
            + int(counts.get(REREAD_KEY) or 0))


def _pending_of(raw):
    """The cursor's per-id counted-so-far tally, keyed by message id, read
    defensively: a cursor written before this field existed has none, and an id
    it does not hold is read as a plain ring member — a repeat of it adds
    nothing rather than growing, exactly as the ring alone treated it."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for mid, counts in raw.items():
        if not isinstance(counts, dict):
            continue
        try:
            out[mid] = dict((k, max(0, int(counts.get(k) or 0))) for k in TOKEN_KEYS)
        except (TypeError, ValueError):
            continue
    return out


def _scan_file(path, file_cursor, attributor, agent_meta, opts):
    """Tail one transcript file from its cursor offset.

    Returns (groups, new_file_cursor). `groups` maps a row key to accumulated counts.
    Only COMPLETE lines are consumed — a trailing partial line stays unread so the
    next scan picks it up whole.

    Every id still inside the ring keeps its counted-so-far tally in the cursor's
    `pending` map, whether or not any entry seen for it carried a `stop_reason` —
    a later entry for that id contributes only its excess over that tally, field
    by field, and adds no second message. Gating the tally on `stop_reason` was
    the other way to do it, and it undercounts: a subagent's repeats of one id
    are not identical, `output_tokens` grows across them, and a non-null
    `stop_reason` on every entry (never a streaming partial) still left later,
    bigger entries counted as nothing. Counting final entries only was rejected
    too, since it loses a message whose stream was cut off before any final entry
    was written, along with every token that partial records. The ledger is
    append-only and a scan can end mid-repeat, so a correction has to be an
    addition: a row already written cannot be edited."""
    groups = {}
    prev = file_cursor if isinstance(file_cursor, dict) else {}
    recent = list(prev.get("recent") or [])
    pending = _pending_of(prev.get("pending"))
    # The task the last message to this agent named, carried between scans for the
    # reason the ring is: a scan reads only the new bytes, so the message that
    # moved attribution is usually in a chunk already consumed. Forgetting it
    # would put the rest of the second task's spend back on the first.
    handoff = prev.get("handoff") or None
    try:
        size = os.path.getsize(path)
    except OSError:
        return groups, prev
    offset = int(prev.get("offset") or 0)
    if size < int(prev.get("size") or 0):
        offset, recent, handoff = 0, [], None   # truncated or rotated -> start over
        pending = {}
    if offset == 0 and not prev:
        # First sight. Historic backfill is bounded so the 10s hook timeout is safe;
        # the unbounded pass is `audit-usage.py --backfill`, which has no timeout.
        if not opts.get("backfillOnFirstRun", True) or size > opts.get(
                "maxScanBytes", 33554432):
            offset = size
    if offset >= size:
        return groups, {"offset": size, "size": size, "recent": recent,
                        "pending": pending, "handoff": handoff}

    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
    except OSError:
        return groups, prev
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return groups, {"offset": offset, "size": size, "recent": recent,
                        "pending": pending, "handoff": handoff}
    consumed = cut + 1
    seen = set(recent)
    cost_state = None

    for raw in chunk[:cut].split(b"\n"):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue                     # a malformed line must never abort a scan
        if not isinstance(entry, dict):
            continue
        # Only on a SUBAGENT's transcript, which is what `agent_meta` being
        # present means. The main transcript's attribution comes from the phase
        # claim and the task windows, and a message in it is addressed to the
        # orchestrator rather than handing an executor a second task.
        if agent_meta and entry.get("type") == "user":
            named = attributor.task_from_handoff(entry)
            if named:
                handoff = named
            continue
        # The CLI writes its own cumulative cost reading into the MAIN
        # transcript only, so a subagent's file never supplies one; the last
        # in this chunk is the newest (see `read_cost_state`).
        if not agent_meta and entry.get("type") == "cost-state":
            cost_state = cost_state_of(entry)
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        mid = message.get("id")
        if not isinstance(usage, dict) or not mid:
            continue
        counted = pending.get(mid)
        if mid in seen and counted is None:
            continue                     # <- THE dedup. See module docstring.
        model = message.get("model") or ""
        if model and not is_model_id(model):
            continue                     # `<synthetic>` API-error placeholders
        ts = entry.get("timestamp")
        bucket = hour_bucket(ts)
        if bucket is None:
            continue
        counts = _usage_counts(usage)
        if counted is None:
            added = counts
        else:
            # Only the excess over what was already added to the ledger for
            # this id, never a negative: an earlier row cannot be taken back.
            added = dict((k, max(0, counts[k] - counted[k])) for k in TOKEN_KEYS)
        # The running per-field max for this id, kept for as long as it stays in
        # the ring — regardless of `stop_reason`, since a repeat's counts can
        # grow (a subagent transcript) with no streaming partial in sight.
        pending[mid] = dict((k, max(counts[k], (counted or counts)[k]))
                            for k in TOKEN_KEYS)
        if counted is None:
            seen.add(mid)
            recent.append(mid)
        elif not any(added.values()):
            continue                     # a repeat that adds nothing writes no row
        phase_id, task_id, attr = attributor.attribute(agent_meta, parse_ts(ts),
                                                       handoff=handoff)
        # A model the published page tiers by prompt size (today: Haiku 5.5)
        # is grouped and priced under a DISTINCT key once this message's own
        # prompt crosses the long-prompt threshold - see `tiered_model_key`.
        # Read off THIS message's counts, never the row's running sum, so a
        # tier decided by one big turn never silently reclassifies a whole
        # hour of small ones.
        priced_model = tiered_model_key(model, _context_of(counts))
        key = (bucket, agent_meta.get("_agentId"), agent_meta.get("agentType"),
               phase_id, task_id, attr, priced_model, entry.get("gitBranch"))
        slot = groups.get(key)
        if slot is None:
            slot = groups[key] = {k: 0 for k in TOKEN_KEYS}
            slot["msgs"] = 0
            slot["maxContext"] = 0
        for k, v in added.items():
            slot[k] += v
        if counted is None:
            slot["msgs"] += 1
        slot["maxContext"] = max(slot["maxContext"], _context_of(counts))

    if len(recent) > RECENT_IDS_CAP:
        recent = recent[-RECENT_IDS_CAP:]
    # An id that has left the ring can no longer be told apart from a new
    # message, so carrying its counted-so-far tally would only grow the cursor.
    kept = set(recent)
    pending = dict((mid, c) for mid, c in pending.items() if mid in kept)
    new_cursor = {"offset": offset + consumed, "size": size, "recent": recent,
                  "pending": pending, "handoff": handoff}
    if cost_state is not None:
        # Handed up for `scan_transcripts` to lift onto the session's cursor,
        # never kept in the per-file one.
        new_cursor["costState"] = cost_state
    return groups, new_cursor


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
    # The table's OWN date and source - never a rate itself, so these travel
    # with a row even when its model carries none (`rate` stamps None, these
    # two still stamp what the table it was checked against claimed to be).
    pricing_as_of = opts.get("pricingAsOf")
    pricing_source = opts.get("pricingSource")
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
            # The largest single turn folded into this row — see `_context_of`
            # and the module docstring for why a summed row cannot answer this
            # on its own, and why an OLD row simply has no such key rather than
            # a zero standing in for "not measured".
            row["maxContext"] = counts["maxContext"]
            # Priced at the rate in effect on the row's OWN date, and STAMPED
            # with that rate, its effectiveFrom (None for a flat/legacy row),
            # and the table's own source/asOf - so a later price change can
            # never rewrite this figure: `priced_at_read` prices a stamped
            # row from its own stamp, never from whatever table it is handed.
            at_date = bucket_date(bucket)
            rate, effective_from = rate_for_stamp(model, pricing, at_date)
            row["rate"] = rate
            row["rateEffectiveFrom"] = effective_from
            row["rateAsOf"] = pricing_as_of
            row["rateSource"] = pricing_source
            # Which entry answered, when it was the table's own `_default`
            # rather than a rate named for this model - the one stamp a reader
            # cannot recover later, since the table that priced the row may
            # have gained a named entry since. Written only then, the way
            # `priced_at_read` reports it: a row without the key was priced
            # at a named rate, or by a meter older than the key.
            if rate is not None and _core._rate_via(model, pricing) == "_default":
                row["rateVia"] = "_default"
            usd = price(counts, model, pricing, at=at_date)
            if usd is None:
                row["costUSD"] = None
                row["unpriced"] = True
            else:
                row["costUSD"] = round(usd, 6)
            rows.append(row)

    # The CLI's own figure for this session, recorded as the scan meets it so
    # a reader asks the cursor (`recorded_cost_state`) rather than a
    # transcript that may have moved. A scan whose new bytes carry none keeps
    # what an earlier one recorded; a session that never carried one has no
    # `cliCost` key at all.
    main_file = files.get(str(transcript_path))
    recorded = (main_file.pop("costState", None)
                if isinstance(main_file, dict) else None)
    if recorded is not None:
        cursor["cliCost"] = recorded
    cursor["files"] = files
    return rows, cursor


# --- the CLI's own cost reading ---------------------------------------------
# The CLI's long-context tier suffix, e.g. `claude-opus-5-5[1m]` - a DIFFERENT
# spelling of the same distinction this module's own `LONG_PROMPT_SUFFIX`
# (`:long-prompt`) makes, so a model id read off a `cost-state` entry has to
# be normalised before it is compared against a ledger row's `model`.
_CLI_TIER_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")


def strip_cli_tier(model):
    """The CLI's own `[...]` tier suffix stripped off a `cost-state` model id,
    e.g. `claude-opus-5-5[1m]` -> `claude-opus-5-5`. A model carrying none is
    returned unchanged."""
    return _CLI_TIER_SUFFIX_RE.sub("", model or "")


def _base_model(model):
    """A ledger row's `model` with THIS module's own tiering suffix stripped,
    so it compares against a `cost-state` model id on the same base name -
    never the rate, just the label the two sides agree on."""
    model = model or ""
    if model.endswith(LONG_PROMPT_SUFFIX):
        model = model[:-len(LONG_PROMPT_SUFFIX)]
    return model


def read_cost_state(transcript_path):
    """The last `cost-state` entry in a MAIN session transcript -> the CLI's
    own read of what that session cost, normalised to
    `{"totalCostUSD", "perModel": {baseModel: costUSD}, "hasUnknownModelCost"}`,
    or None when the file carries none or cannot be read.

    WHETHER `modelUsage` FOLDS IN SUBAGENT SPEND IS INFERRED, NOT MEASURED.
    The inference: on one recorded session the main transcript carried no
    `sonnet` turn while `modelUsage` named `claude-sonnet-5-5` with a
    non-zero `costUSD`, which only a subagent could have spent. The
    measurement that would settle it - per model, `modelUsage` costUSD
    against the ledger's per-model sum for that one session id, once with
    its subagent rows and once without - has not been made. That session's
    transcript is no longer on this machine. On 2026-10-15 the only session
    this repo's project directory held,
    `fb1bddcc-aedf-4720-99d2-ec2a15fdf289`, carried no `cost-state` entry at
    all (`grep -c '"type":"cost-state"'` on its `.jsonl` printed 0). The
    sessions of other projects that do carry one were not read, because the
    host refused a read across another project's transcripts. The same
    session's two sides were also seen to disagree in magnitude on every
    model, and compaction trimming the retained `.jsonl` while `cost-state`
    stays cumulative is a guess at why, not a finding. So no surface may
    treat the two figures' gap as either a stale price or a known cause.

    A `cost-state` entry is written only to the MAIN transcript - none of
    this project's own subagent `.jsonl` files carry one - so this never
    reads a subagent path. The meter records the same reading as it scans
    (`scan_transcripts` -> the cursor's `cliCost`); this whole-file read is
    for a session whose cursor holds none.

    Only the LAST entry is kept: `cost-state` is cumulative for the whole
    session, so an earlier one is a strict subset of a later one and never
    corrects it."""
    last = None
    try:
        with open(transcript_path, "rb") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw.decode("utf-8", "replace"))
                except Exception:
                    continue
                if isinstance(entry, dict) and entry.get("type") == "cost-state":
                    last = entry
    except OSError:
        return None
    if last is None:
        return None
    return cost_state_of(last)


def cost_state_of(entry):
    """One `cost-state` transcript entry -> `{"totalCostUSD", "perModel":
    {baseModel: costUSD}, "hasUnknownModelCost"}`: the one normalisation both
    the whole-file read (`read_cost_state`) and the meter's scan
    (`_scan_file`) apply, so the figure a cursor records and the figure a
    transcript re-read gives cannot drift apart."""
    model_usage = entry.get("modelUsage")
    per_model = {}
    if isinstance(model_usage, dict):
        for model, data in model_usage.items():
            if isinstance(data, dict) and "costUSD" in data:
                key = strip_cli_tier(model)
                per_model[key] = per_model.get(key, 0.0) + (data.get("costUSD") or 0.0)
    return {
        "totalCostUSD": entry.get("totalCostUSD"),
        "perModel": per_model,
        "hasUnknownModelCost": bool(entry.get("hasUnknownModelCost")),
    }


# How far the CLI's own figure and the plugin's own figure may differ, in
# absolute USD, before a reader is told they disagree - rounding alone (the
# CLI publishes more decimal places than any surface here prints) must never
# read as a divergence.
CLI_COST_TOLERANCE_USD = 0.01


def cli_cost_compare(rows, cost_state, tolerance=CLI_COST_TOLERANCE_USD):
    """The CLI's per-model cost beside the plugin's own, for one session's
    `rows` -> `{model: {"cliCostUSD", "pluginCostUSD", "agrees"}}`, over
    every model EITHER side has a reading for. `agrees` is True when both
    sides have a figure and they are within `tolerance` USD of each other -
    never when only one side has a reading, since there is nothing there to
    agree. Returns `{}` when `cost_state` is None (no `cost-state` entry was
    recorded for this session) - never a comparison manufactured from
    nothing."""
    if not cost_state:
        return {}
    plugin_cost = {}
    for row in rows:
        usd = row.get("costUSD")
        if usd is None:
            continue
        model = _base_model(row.get("model"))
        plugin_cost[model] = plugin_cost.get(model, 0.0) + usd
    cli_cost = cost_state.get("perModel") or {}
    out = {}
    for model in set(plugin_cost) | set(cli_cost):
        cli_usd = cli_cost.get(model)
        plugin_usd = plugin_cost.get(model)
        agrees = (cli_usd is not None and plugin_usd is not None
                 and abs(cli_usd - plugin_usd) <= tolerance)
        out[model] = {"cliCostUSD": cli_usd, "pluginCostUSD": plugin_usd,
                      "agrees": agrees}
    return out


def cli_cost_divergences(rows, cost_state, tolerance=CLI_COST_TOLERANCE_USD):
    """`cli_cost_compare`, narrowed to the models that do NOT agree - the two
    disagree, or one side has no reading at all for it."""
    return dict((model, {"cliCostUSD": v["cliCostUSD"],
                         "pluginCostUSD": v["pluginCostUSD"]})
               for model, v in cli_cost_compare(rows, cost_state, tolerance).items()
               if not v["agrees"])


# The CLI side's label, by where its figure came from. One home for the words,
# because `/audit:usage`, the report and the panel all print them beside a CLI
# figure, and the CLI's figure is called its estimate on every one of them -
# never the bill.
CLI_BASIS_METER = "the CLI's estimate, recorded at meter time"
CLI_BASIS_TRANSCRIPT = "the CLI's estimate, read from the transcript"
CLI_BASIS_UNTAGGED = "the CLI's estimate"

# What the CLI's cumulative figure counts that no transcript entry records, so a
# gap between the two sides is not read as the plugin missing rows it could have
# seen. Said once here for the same reason the basis words are.
CLI_COST_UNRECORDED = ("the CLI's figure includes requests no transcript entry "
                       "records (compaction, away summaries, titles, the "
                       "auto-mode classifier)")


def cli_basis(source):
    """The label for a CLI figure whose reading came from `source` - `meter`
    (the cursor the meter wrote) or `transcript` (read from the session's
    file now). Anything else is the bare name, never a guess at where the
    figure came from."""
    if source == "meter":
        return CLI_BASIS_METER
    if source == "transcript":
        return CLI_BASIS_TRANSCRIPT
    return CLI_BASIS_UNTAGGED


# --- ledger I/O -----------------------------------------------------------------
def _session_file(ledger_dir, sub, session_id):
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in str(session_id))
    return os.path.join(ledger_dir, sub, (safe or "session") + ".json")


def cursor_path(ledger_dir, session_id):
    return _session_file(ledger_dir, ".cursors", session_id)


def _read_dict(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_cursor(ledger_dir, session_id):
    return _read_dict(cursor_path(ledger_dir, session_id))


def recorded_cost_state(ledger_dir, session_id):
    """The CLI's own cost reading the meter recorded for `session_id` (the
    cursor's `cliCost`, shaped as `cost_state_of` answers), or None when its
    cursor holds none - never an empty reading standing in for 'not
    recorded'."""
    recorded = load_cursor(ledger_dir, session_id).get("cliCost")
    return recorded if isinstance(recorded, dict) else None


def cli_cost_entries(ledger_dir, rows):
    """`[{session, model, cliCostUSD, pluginCostUSD, pluginUnpriced, basis}]`
    - one entry per session and model where the CLI's own recorded figure
    (`recorded_cost_state`, the cursor's `cliCost`) and the plugin's reading
    of the same session's priced `rows` differ, through `cli_cost_divergences`.
    A model they agree on yields nothing, and so does a session whose cursor
    recorded no figure. `pluginUnpriced` says the plugin's side has no figure
    because no rate covers that model's tokens, which a reader must not take
    for a model the plugin never saw.

    Only the RECORDED figure: the report and the panel read this, and
    re-reading a transcript per render is the second parse the cursor exists
    to save. `/audit:usage` falls back to the transcript itself and labels the
    figure accordingly through `cli_basis`. Raises on what it cannot read; the
    caller decides whether a comparison going wrong costs its surface a line."""
    by_session = {}
    for r in rows:
        if r.get("sessionId"):
            by_session.setdefault(r["sessionId"], []).append(r)
    out = []
    for sid in sorted(by_session):
        state = recorded_cost_state(ledger_dir, sid)
        if not state:
            continue
        session_rows = by_session[sid]
        diffs = cli_cost_divergences(session_rows, state)
        for model in sorted(diffs):
            # Matched on the base name the comparison keys by: a ledger
            # model with the long-prompt tier suffix is the same model.
            model_rows = [r for r in session_rows
                          if (r.get("model") or "") in
                          (model, model + LONG_PROMPT_SUFFIX)]
            out.append({
                "session": sid, "model": model,
                "cliCostUSD": diffs[model]["cliCostUSD"],
                "pluginCostUSD": diffs[model]["pluginCostUSD"],
                "pluginUnpriced": all_unpriced(totals(model_rows)),
                "basis": cli_basis("meter")})
    return out


def cli_cost_outcome(ledger_dir, rows):
    """`(entries, reason)` - `cli_cost_entries` over the priced rows and
    None, or None and why the comparison could not be made. None, not `[]`:
    an empty list says every recorded CLI figure agreed, and a comparison
    that raised has said nothing of the kind. The reason is the exception
    itself, because a surface saying only that something failed leaves its
    reader nothing to look at. The report and the panel both call this, so
    the two cannot disagree on the case where the read failed. Contained so
    that one failing read costs the surface that line, never the whole
    Usage block."""
    try:
        return cli_cost_entries(ledger_dir, rows), None
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)


def start_notice_given(ledger_dir, session_id, model):
    """Whether SessionStart already told `session_id`'s reader that `model`
    is unpriced. Kept in its own file beside the cursors, never in a cursor:
    the fallback key is the PREVIOUS session, whose cursor another live
    session's meter may be rewriting, and a stale cursor written back re-scans
    from an old offset and double-counts."""
    models = _read_dict(_session_file(ledger_dir, ".notices", session_id)).get(
        "models")
    return isinstance(models, list) and model in models


def mark_start_notice(ledger_dir, session_id, model):
    """Record that `model`'s unpriced notice was given for `session_id`.
    True when it was written; False when it could not be (the notice may then
    repeat, which is the failure an advisory can afford)."""
    path = _session_file(ledger_dir, ".notices", session_id)
    models = _read_dict(path).get("models")
    models = sorted(set(models if isinstance(models, list) else []) | {model})
    try:
        ensure_ledger_dir(ledger_dir)
        _manifest_io.atomic_write_text(path, json.dumps({"models": models}))
        return True
    except Exception:
        return False


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
            with open(marker, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(LOCAL_IGNORE_MARKER)
    except Exception:
        pass


def save_cursor(ledger_dir, session_id, cursor):
    """Atomic, through `_manifest_io.atomic_write_text`, so a killed hook can never
    leave a half-written cursor that would re-scan from zero and double-count -
    and its temp file is this call's own, so a second writer of the same cursor
    cannot truncate it or move it into place."""
    path = cursor_path(ledger_dir, session_id)
    try:
        ensure_ledger_dir(ledger_dir)
        _manifest_io.atomic_write_text(path, json.dumps(cursor))
        return True
    except Exception:
        return False


def append_rows(ledger_dir, rows):
    """Append rows to their monthly ledger files.

    Rows are small (<~400 bytes) and each is written with a single O_APPEND write,
    so appenders never interleave with one another. Each month's open-write-close
    is made under that month's lock (`lock_month`), which is what a rewrite takes
    around its replace: where the platform refuses to replace a file some handle
    holds open, an append racing the replace would otherwise land in the file the
    replace retires. A lock not had within its wait, or one the filesystem
    refuses, is appended through anyway - a row written at risk beats a row
    dropped for certain. -> the rows known written: a month whose close failed
    counts none of its rows."""
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
        written += _append_locked(path, group)
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

    The walk is bounded twice:

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


def project_pricing(manifest, manifest_path=None, project_dir=None):
    """`resolve_pricing` for a project on disk: the manifest handed in, and the
    RAW `.claude/audit.config.json` of the project root `find_ledger_dir` places
    - an explicit `project_dir` as given, else the walk up from the manifest.

    The config is read as written, not through `hooks/_config.load`: that merge
    fills in the defaults' table, and the resolver could then no longer tell a
    project that declared a table from one that declared nothing. An absent,
    unreadable or non-object config is no config - the shipped table, the same
    answer `hooks/_config.load` gives the hooks for it."""
    config = None
    claude_dir = find_ledger_dir(manifest_path, ".claude", project_dir) \
        if (manifest_path or project_dir) else None
    if claude_dir:
        try:
            with open(os.path.join(claude_dir, "audit.config.json"),
                      encoding="utf-8") as fh:
                config = json.load(fh)
        except (OSError, ValueError):
            config = None
    return resolve_pricing(manifest, config if isinstance(config, dict) else None)


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


# How long the old file must stay quiet after a replace before its tail is
# taken as final, and how many quiet-checks a busy writer may extend it by.
TAIL_SETTLE_S = 0.02
TAIL_MAX_POLLS = 50
# Whether a replace goes through while a handle holds the file open. Windows
# refuses it, so there a rewrite lets go of its own descriptor before the replace
# rather than spinning the shared sharing-denial wait against itself.
REPLACE_PASSES_OPEN_FILE = os.name != "nt"
# How long the month's lock is waited for, polled at what interval. The wait
# sits between two bounds a case reads off the code: above the longest a rewrite
# can hold the lock through its replace (`_output.SHARING_WAIT_SECONDS`), so an
# append outlasts one; and well under the metering hook's own `timeout` in
# hooks.json, which kills the hook - and every row it had not yet written - when
# it runs out.
MONTH_LOCK_WAIT_S = 3.0
MONTH_LOCK_POLL_S = 0.005
# What `lock_month` answers for a lock file the filesystem will not lock at
# all: the caller goes on lock-free, as it would on a platform with no lock.
LOCK_UNAVAILABLE = "lock-unavailable"
# The errnos that mean "someone else holds it" - the only refusal worth waiting
# out. flock reports EWOULDBLOCK (EAGAIN on some systems); msvcrt.locking
# reports EACCES, or EDEADLOCK where the platform names one.
_CONTENDED = frozenset(e for e in (
    errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES,
    getattr(errno, "EDEADLOCK", None), getattr(errno, "EDEADLK", None))
    if e is not None)


# --- month lock ---

def month_lock_path(month_path):
    """The lock file beside a monthly file. It is never removed: unlinking a
    lock file someone is waiting on hands the next taker a second inode, and
    two holders. Its name does not end in `.jsonl`, the suffix every reader of
    the ledger directory selects on, so it is never read as rows."""
    return month_path + ".lock"


def _try_lock(fd):
    """One non-blocking attempt; raises OSError while another holder has it,
    and an OSError of another errno where the filesystem refuses locks.
    On a platform with neither module there is nothing to take, and that is
    the lock-free behaviour this file had before the lock existed."""
    if msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    elif fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def lock_month(month_path, wait_s=None):
    """Take the month's exclusive lock -> the descriptor holding it; None when
    it was held by another past `wait_s` or the lock file cannot be opened;
    `LOCK_UNAVAILABLE` at once when the filesystem refuses to lock it at all
    (an errno outside `_CONTENDED`), since waiting cannot change that answer
    and a wait spent on it is the metering hook's whole budget.

    An OS lock rather than a lock FILE's existence: the kernel releases it when
    its holder dies, so a killed backfill never leaves appenders waiting on a
    lock nobody holds."""
    wait_s = MONTH_LOCK_WAIT_S if wait_s is None else wait_s
    try:
        fd = os.open(month_lock_path(month_path),
                     os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
    except OSError:
        return None
    deadline = time.monotonic() + wait_s
    while True:
        try:
            _try_lock(fd)
            return fd
        except OSError as exc:
            if exc.errno not in _CONTENDED:
                os.close(fd)
                return LOCK_UNAVAILABLE
            if time.monotonic() >= deadline:
                os.close(fd)
                return None
        time.sleep(MONTH_LOCK_POLL_S)


def unlock_month(fd):
    if fd is None or fd == LOCK_UNAVAILABLE:
        return
    try:
        if msvcrt is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        elif fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        os.close(fd)


def _append_locked(path, rows):
    """Append `rows` to `path` under its month lock -> how many were written:
    all of them once the handle has closed without raising, else 0.

    The writes are buffered, so a row is on disk only after the flush that
    `close` makes; a count taken per write would report rows a failing close
    lost. A failure part-way may still leave some rows behind, so 0 means "not
    known written", which is what the carry's check needs to report a failure.
    The file is opened and closed inside the lock, so no handle an appender
    holds is open when a rewrite holding the lock replaces the file."""
    lock = lock_month(path)
    try:
        # LF on every platform, as the journal's appender writes it.
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(_row_line(row))
        return len(rows)
    except Exception:
        return 0
    finally:
        unlock_month(lock)


def _row_line(row):
    """One ledger row as the line every writer of a monthly file spells it."""
    return json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"


def _parse_rows(data, drop):
    """Ledger rows in `data` (bytes holding whole lines) whose session is not in
    `drop`. A line that does not parse is skipped, as `read_ledger` skips one."""
    rows = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("sessionId") not in drop:
            rows.append(row)
    return rows


def _drain(tail, final=False):
    """What the held old file gained since the last read -> `(rows, nbytes)`.

    Only complete lines are taken; a partial one waits in `tail["pending"]` for
    its newline, since a writer may be mid-write. `final` takes the remainder
    too, because after the last read nothing will complete it. `nbytes` is the
    raw count read, which is what says whether the file is still being written:
    the rows are filtered, so a dropped session's row or a half-written line
    reads as no rows while the file is anything but quiet."""
    fresh = tail["fh"].read()
    data = tail["pending"] + fresh
    cut = len(data) if final else data.rfind(b"\n") + 1
    tail["pending"] = data[cut:]
    return _parse_rows(data[:cut], tail["drop"]), len(fresh)


def _settle(tail):
    """Drain the retired file until one settle period passes with no byte added
    and no partial line waiting.

    A writer that opened the month file before the replace writes into the file
    the replace retired; the held descriptor is the only way left to read it.
    Bounded by `TAIL_MAX_POLLS`, so a writer that never stops cannot hold the
    backfill - its rows past the bound are the window this does not close."""
    rows, _n = _drain(tail)
    for _ in range(TAIL_MAX_POLLS):
        time.sleep(TAIL_SETTLE_S)
        more, nbytes = _drain(tail)
        rows += more
        if not nbytes and not tail["pending"]:
            break
    return rows + _drain(tail, final=True)[0]


def open_month(ledger_dir, month, drop):
    """Read one monthly file through a descriptor that stays open -> `(rows,
    tail)`, where `rows` are the rows whose session is not in `drop` and `tail`
    is what `rewrite_month` needs to keep rows appended after this read.

    When the file does not exist yet, `tail` holds no descriptor and
    `rewrite_month` creates the file and holds that one, from its start."""
    path = os.path.join(ledger_dir, "%s.jsonl" % month)
    try:
        fh = open(path, "rb")
    except FileNotFoundError:
        return [], {"fh": None, "pending": b"", "drop": set(drop), "path": path}
    data = fh.read()
    cut = data.rfind(b"\n") + 1
    return (_parse_rows(data[:cut], drop),
            {"fh": fh, "pending": data[cut:], "drop": set(drop), "path": path})


def _close_tail(tail):
    if tail and tail.get("fh") is not None:
        try:
            tail["fh"].close()
        except OSError:
            pass
        tail["fh"] = None


def rewrite_month(ledger_dir, month, rows, tail=None):
    """Replace one monthly file atomically. Used only by `--backfill`.

    The replace is made under the month's lock (`lock_month`), which every
    `append_rows` holds across its open-write-close: while it is held no such
    appender is mid-append and none holds the file open, so the last drain
    before the replace sees every row those appenders wrote, and a platform
    that refuses to replace a file some handle holds open is not refused by
    them. The lock is taken after the rows are read and released right after
    the replace, so appenders wait only for the write and the swap.

    With `tail` (from `open_month`) the rows appended to the old file since
    that read, of sessions the backfill did not re-read, are carried: into the
    new file before the replace, and - through the descriptor still open on the
    retired file - from a writer that does not take the lock (a copy of this
    file older than the lock), opened the path before the replace and wrote
    after it.

    A month with no file yet is created empty and held the same way: a writer
    that creates the path while the month is being rebuilt would otherwise write
    into a file nothing holds, and the replace would retire it unread. A replace
    that then fails leaves that empty file behind - it holds no row, so every
    reader sees the month as it was.

    Where the platform refuses to replace a file that is open
    (`REPLACE_PASSES_OPEN_FILE` false), the descriptor is drained to its end and
    closed BEFORE the replace, so the replace never meets the rewrite's own
    handle; a refusal it does meet is someone else's, and is waited out by the
    one retry every atomic write has (`_output.while_shared`), still under the
    lock. There a writer that does not take the lock can lose a row written
    between that last drain and the replace; one that takes it cannot.

    On a filesystem that refuses to lock at all (`LOCK_UNAVAILABLE`) the rewrite
    goes on without it, as every appender there does: the carry is then the
    descriptor's alone, as it was before the lock existed.

    -> True when the file was replaced and every carried row was appended;
    False when it was not replaced (the lock not had, or the replace refused
    throughout; the old file stands, no temp file is left) or when rows carried
    after the replace could not be appended."""
    path = os.path.join(ledger_dir, "%s.jsonl" % month)
    lock = None
    try:
        ensure_ledger_dir(ledger_dir)
        if tail is not None and tail.get("fh") is None:
            tail["fh"] = os.fdopen(os.open(path, os.O_RDONLY | os.O_CREAT
                                           | getattr(os, "O_BINARY", 0), 0o666),
                                   "rb")
        lock = lock_month(path)
        if lock is None:
            return False
        held = tail is not None and REPLACE_PASSES_OPEN_FILE
        rows = list(rows) + (_drain(tail, final=not held)[0]
                             if tail is not None else [])
        if not held:
            _close_tail(tail)
        _replace_rows(path, rows)
        unlock_month(lock)
        lock = None
        if tail is not None and tail.get("fh") is not None:
            carried = _settle(tail)
            if _append_locked(path, carried) != len(carried):
                return False
        return True
    except Exception:
        return False
    finally:
        unlock_month(lock)
        _close_tail(tail)


def _replace_rows(path, rows):
    """Replace `path` with `rows` - the one write-and-replace a month rewrite
    makes, through `_manifest_io.atomic_write_text`, whose temp file is this
    call's own. A failure removes that temp file and re-raises, so a refused
    replace leaves the old file standing and nothing beside it."""
    _manifest_io.atomic_write_text(path, "".join(_row_line(row) for row in rows))



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
        print("usage_ledger.py has no inline --selftest; its cases moved to "
              "tests/test_usage_ledger.py - run that file instead.")
        raise SystemExit(0)
    sys.stderr.write("usage: usage_ledger.py --selftest\n")
    raise SystemExit(2)
