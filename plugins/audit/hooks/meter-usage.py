#!/usr/bin/env python3
"""
Stop / SubagentStop / SessionEnd meter — records token usage, blocks nothing.

Claude Code hands hooks a `transcript_path` but no token counts. The transcript
JSONL has them: every `assistant` entry carries `message.model` and a
`message.usage` block. This hook tails that file (plus the session's subagent
transcripts) from a saved byte offset, attributes each message to a phase/task,
and appends aggregated rows to the usage ledger.

All three events are just "go tail now" triggers — the scan is driven by file
offsets, not by the payload, so it stays correct regardless of which event fired
and regardless of whether SubagentStop ever names the subagent that finished:

  Stop         after each main-agent turn  -> near-real-time metering
  SubagentStop after a Task/Agent finishes -> picks up that subagent's transcript
  SessionEnd   final flush

Config: `.claude/audit.config.json` -> `usage` (see _config.DEFAULTS):
  enabled             bool — master switch (default true)
  ledgerDir           str  — where the ledger and its cursors live
  authorMode          str  — email (default) | name | hash | none
  backfillOnFirstRun  bool — scan a transcript's history the first time it is seen
  maxScanBytes        int  — ceiling on that first-sight scan, so this hook's 10s
                             timeout is never at risk. `/audit:usage --backfill`
                             does the unbounded pass instead.
  pricing             obj  — USD per million tokens; cost is computed and stored
                             at write time so a later rate change cannot rewrite
                             history.

State: `<ledgerDir>/.cursors/<session_id>.json` — per-file offsets plus the
resolved author. Deliberately NOT under `stateDir`: that tree is GC'd after 7 days
by detect-plan-skip.py, and a lost cursor would re-scan from offset 0 and
double-count. The author is resolved once per session and cached here, so the
single `git config` subprocess never lands in the hot path.

PRIVACY: rows carry counts, model ids, timestamps, branch and author — never
prompt or response CONTENT. Transcripts are opened read-only.

Contract: ALWAYS exits 0 and NEVER emits a decision. Any unexpected input or
exception also exits 0 — metering must never break legitimate work. Registered in
hooks.json with the `open` (fail-silent) launcher mode for the same reason.

The only exceptions to "prints nothing" are two `systemMessage`s, neither of which
is a decision:

  * when the task in flight passes the project's own outlier cost band, said once
    while there is still time to act;
  * on SessionEnd, one line saying what the session cost.

Both are advice and block nothing — and a Stop hook could not block even if it
wanted to, since `decision: "block"` there means "do not stop, keep going". A real
spend gate would belong on PreToolUse, like require-plan.py.

This hook carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_meter_usage.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `plugins/audit/tests/_harness.py`.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

# --- loading ------------------------------------------------------------------
def _load_ledger_lib():
    """Load `usage_ledger.py` by path, wherever it sits under `scripts/`.

    THE DIRECTORY IS NOT SPELLED HERE ANY MORE. It was
    `join(dirname(dirname(__file__)), "scripts")` plus a flat join with the
    filename, which is this hook's own depth AND the assumption that `scripts/` is
    flat, written down twice. `_config.find_script()` is the one resolver on this
    side of the layer wall — `hooks/` may not import `scripts/`, so `_output`'s
    anchors are out of reach, and one copy in `hooks/` is the fewest there can be.
    `_config` is already a hard module-level dependency of this file, so leaning on
    it adds no failure mode.

    A missing file raises here rather than returning None, which is the existing
    contract: `meter()` calls this only after `usage_enabled(cfg)` says the feature
    is on, and a ledger that is switched on but unloadable is worth a traceback.
    """
    path = _config.find_script("usage_ledger.py")
    spec = importlib.util.spec_from_file_location("usage_ledger", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- advisory + session summary -----------------------------------------------
def advise(ul, ledger, manifest, ucfg, cursor, rows):
    """The one thing this hook ever says out loud: that the task in flight has
    crossed the project's own outlier threshold, while there is still time to act.

    Advisory, never a gate. A `Stop` hook cannot gate anyway — in that contract
    `decision: "block"` means "do not stop, keep going", the exact inverse — so a
    spend gate would have to live on `PreToolUse` like require-plan.py. It is also
    the right call on the merits: a plan or test gate is recoverable, while
    stopping a task mid-edit on spend can strand a half-finished change.

    Fires ONCE per task per session, recorded in the cursor. A warning that
    repeats on every turn for the rest of a long task is a warning nobody reads.
    A later session warns again, which is intended: that is a fresh chance to act.

    Returns a message, or None — and None is the common case, so the ledger read
    is reached only when a warning is actually possible. Measured at 26 ms over a
    9-month, 8,740-row ledger, which is the cost of at most one Stop per task.
    """
    if not rows:
        return None
    tid = next((r.get("taskId") for r in reversed(rows) if r.get("taskId")), None)
    if not tid:
        return None
    warned = cursor.get("warnedTasks")
    if not isinstance(warned, list):
        warned = []
    if tid in warned:
        return None

    all_rows = ul.read_ledger(ledger)
    bands = ul.cost_bands(manifest, all_rows, ucfg)
    if ul.band_of(bands, tid) != "outlier":
        return None

    spent = sum(float(r.get("costUSD") or 0.0)
                for r in all_rows if r.get("taskId") == tid)
    warned.append(tid)
    cursor["warnedTasks"] = warned

    # The threshold is stated, because "this is an outlier" is a claim and a claim
    # whose basis is invisible cannot be argued with. Under showCost=false that
    # basis has to be described WITHOUT a figure — naming the threshold in dollars
    # would leak exactly what the setting exists to hide, which is how the first
    # version of this message failed.
    absolute = bands.get("basis") == "absolute"
    if ucfg.get("showCost", True):
        why = ("the configured outlier threshold of $%.2f" % bands["outlier"]
               if absolute
               else "this project's p90 completed task ($%.2f)" % bands["outlier"])
        head = "%s has cost $%.2f, past %s." % (tid, spent, why)
    else:
        why = ("the configured outlier threshold" if absolute
               else "this project's p90 completed task")
        mult = spent / bands["outlier"] if bands.get("outlier") else 0
        head = "%s is running %.1fx past %s." % (tid, mult, why)
    return ("[audit] %s Consider splitting it or re-scoping before the next "
            "attempt. This is advice, not a gate — nothing is blocked." % head)


def session_summary(ul, ledger, ucfg, session_id):
    """What this session cost, said once at the end.

    Immediate feedback where the work happened, rather than only in a dashboard
    you have to remember to open. The rows are written either way; this just says
    it out loud.

    Silent when the session recorded nothing, so a read-only session — asking a
    question, reading code — says nothing rather than reporting a row of zeros."""
    rows = [r for r in ul.read_ledger(ledger)
            if (r.get("sessionId") or "") == session_id]
    if not rows:
        return None
    tot = ul.totals(rows)
    if not tot["tokens"]:
        return None
    tasks = sorted({r.get("taskId") for r in rows if r.get("taskId")})
    bits = ["%s tokens" % _compact(tot["tokens"])]
    if ucfg.get("showCost", True):
        bits.append("~$%.2f" % tot["costUSD"])
    bits.append("%s messages" % "{:,}".format(tot["msgs"]))
    if tasks:
        bits.append("%d task(s): %s" % (len(tasks), ", ".join(tasks[:4])
                                        + (" +%d" % (len(tasks) - 4)
                                           if len(tasks) > 4 else "")))
    return "[audit] this session: " + " · ".join(bits)


# --- metering -----------------------------------------------------------------
def _compact(n):
    """Magnitudes are compact everywhere in this plugin — `3.2M`, never
    `3,230,000`. Mirrors _fmt_tokens in render-report.py and uTok in the panel."""
    n = int(n or 0)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= limit:
            return "%.1f%s" % (n / float(limit), suffix)
    return str(n)


def meter(data, ul=None, cfg=None, root=None, notices=None):
    """Scan, attribute and append. Returns the number of rows written (0 when
    disabled, when there is nothing new, or on any handled failure).

    Split out from `main` so the selftest can drive it with a fake payload."""
    root = Path(root) if root is not None else _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    if not _config.usage_enabled(cfg):
        return 0

    transcript = (data or {}).get("transcript_path")
    if not transcript or not os.path.isfile(transcript):
        return 0
    session_id = (data or {}).get("session_id") or os.path.splitext(
        os.path.basename(transcript))[0]

    ul = ul if ul is not None else _load_ledger_lib()
    ucfg = _config.usage_cfg(cfg)
    ledger = str(_config.ledger_dir(root, cfg))

    cursor = ul.load_cursor(ledger, session_id)
    if not cursor.get("author") and ucfg.get("authorMode") != "none":
        cursor["author"] = ul.resolve_author(root, ucfg.get("authorMode", "email"))

    # A missing or unreadable manifest is fine: attribution degrades to
    # `unattributed` rather than failing, so off-phase spend is still recorded.
    manifest = _config._load_manifest_assembled(
        Path(root) / (cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]))

    rows, cursor = ul.scan_transcripts(
        transcript, session_id, cursor, manifest,
        {
            "repo": os.path.basename(str(root)) or "repo",
            "pricing": ucfg.get("pricing"),
            "backfillOnFirstRun": bool(ucfg.get("backfillOnFirstRun", True)),
            "maxScanBytes": int(ucfg.get("maxScanBytes") or 33554432),
            # The other name this session answers to. `phase.claim.sessionId` is
            # written by the orchestrator from Bash, where the id available is
            # $CLAUDE_CODE_SESSION_ID; `session_id` above comes from this hook's
            # payload, and in a live session those are DIFFERENT values. Comparing
            # only the payload id could never match a claim, and the failure is
            # silent — orchestrator spend just stays `unattributed`. Used only to
            # match a claim; every ledger row still carries `session_id` itself.
            "sessionAliases": [os.environ.get("CLAUDE_CODE_SESSION_ID")],
        })

    written = ul.append_rows(ledger, rows)

    # Both messages are strictly additive: either can raise and metering still
    # stands. `notices` is an out-parameter rather than a changed return type so
    # the existing contract (`meter` -> rows written) survives untouched.
    if notices is not None:
        if written:
            try:
                note = advise(ul, ledger, manifest, ucfg, cursor, rows)
                if note:
                    notices.append(note)
            except Exception:
                pass
        # Only at the end, and only once — SessionEnd fires once per session,
        # while Stop fires every turn.
        if (data or {}).get("hook_event_name") == "SessionEnd":
            try:
                summary = session_summary(ul, ledger, ucfg, session_id)
                if summary:
                    notices.append(summary)
            except Exception:
                pass

    # Persist the cursor even when nothing was written, so an oversized first-sight
    # transcript records its skip-to-EOF offset instead of re-deciding every turn.
    # This also persists `warnedTasks`, which is what stops the advisory repeating.
    ul.save_cursor(ledger, session_id, cursor)
    return written


# --- cli ----------------------------------------------------------------------
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    notices = []
    try:
        meter(data, notices=notices)
    except Exception:
        pass
    # The ONLY output this hook ever produces, and it is a message to the user —
    # never a decision. Emitting it is itself wrapped, because a serialisation
    # failure must not turn a spend note into a broken hook.
    if notices:
        try:
            # Newline, not space: on SessionEnd both an outlier advisory and the
            # session summary can land at once, and run together they read as one
            # confused sentence.
            sys.stdout.write(json.dumps({"systemMessage": "\n".join(notices)}))
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("meter-usage.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_meter_usage.py - run that file instead.")
        raise SystemExit(0)
    main()
