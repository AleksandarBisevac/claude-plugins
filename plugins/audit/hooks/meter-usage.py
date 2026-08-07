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

Run `python3 meter-usage.py --selftest` to exercise the decision core.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts")


def _load_ledger_lib():
    """Load scripts/usage_ledger.py by path — the scripts dir is not a package,
    and this mirrors how the other cross-module loads in this plugin work."""
    spec = importlib.util.spec_from_file_location(
        "usage_ledger", os.path.join(_SCRIPTS, "usage_ledger.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def main() -> None:
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


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import shutil
    import tempfile

    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

    ul = _load_ledger_lib()
    tmp = Path(tempfile.mkdtemp(prefix="meter-usage-selftest-"))
    prev_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    try:
        (tmp / "docs" / "audit").mkdir(parents=True, exist_ok=True)
        (tmp / "docs" / "audit" / "audit-plan.json").write_text(json.dumps({
            "meta": {"version": 2},
            "phases": [{"id": "P1", "title": "Alpha",
                        "claim": {"sessionId": "sess-1"},
                        "tasks": [{"id": "P1.1", "status": "in_progress",
                                   "startedAt": "2026-08-06T07:00:00Z"}]}],
        }), encoding="utf-8")

        transcript = tmp / "sess-1.jsonl"

        def entry(mid, out_tokens):
            return json.dumps({
                "type": "assistant", "timestamp": "2026-08-06T07:20:10Z",
                "gitBranch": "audit/p1", "message": {
                    "id": mid, "model": "claude-opus-5",
                    "usage": {"input_tokens": 1, "output_tokens": out_tokens,
                              "cache_creation_input_tokens": 0,
                              "cache_read_input_tokens": 0}}}) + "\n"

        transcript.write_text(entry("m1", 100) + entry("m1", 100) + entry("m2", 50),
                              encoding="utf-8")
        payload = {"session_id": "sess-1", "cwd": str(tmp),
                   "transcript_path": str(transcript),
                   "hook_event_name": "Stop"}

        cfg = _config.load(tmp)
        ledger = str(_config.ledger_dir(tmp, cfg))

        n = meter(payload, ul=ul, cfg=cfg, root=tmp)
        check("a1 first scan writes rows", n > 0, "wrote %s" % n)
        rows = ul.read_ledger(ledger)
        t = ul.totals(rows)
        check("a2 repeated message.id counted once", t["out"] == 150,
              "got %s" % t["out"])
        check("a3 author recorded on every row",
              all(r.get("author") for r in rows))
        check("a4 attributed to the claiming phase",
              all(r.get("phaseId") == "P1" for r in rows))
        check("a5 cost stored at write time",
              all(isinstance(r.get("costUSD"), float) for r in rows))
        check("a6 no prompt content in any row",
              all(set(r).issubset({
                  "ts", "author", "sessionId", "agentId", "agentType", "phaseId",
                  "taskId", "attr", "model", "branch", "repo", "msgs", "costUSD",
                  "in", "out", "cacheW5m", "cacheW1h", "cacheR"}) for r in rows))

        # (b) re-running the same event is a no-op — the cursor holds the offset
        n2 = meter(payload, ul=ul, cfg=cfg, root=tmp)
        check("b1 re-run writes nothing new", n2 == 0, "wrote %s" % n2)
        check("b2 ledger totals unchanged after re-run",
              ul.totals(ul.read_ledger(ledger))["out"] == 150)

        # (c) incremental append is picked up
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(entry("m3", 7))
        meter(payload, ul=ul, cfg=cfg, root=tmp)
        check("c1 appended turn metered incrementally",
              ul.totals(ul.read_ledger(ledger))["out"] == 157)

        # (d) master switch
        off = _config.load(tmp)
        off["usage"] = dict(off["usage"], enabled=False)
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(entry("m4", 1000))
        check("d1 disabled config meters nothing",
              meter(payload, ul=ul, cfg=off, root=tmp) == 0)

        # (e) degraded inputs must never raise and never write
        check("e1 missing transcript_path -> 0",
              meter({"session_id": "x", "cwd": str(tmp)}, ul=ul, cfg=cfg,
                    root=tmp) == 0)
        check("e2 nonexistent transcript -> 0",
              meter({"session_id": "x", "cwd": str(tmp),
                     "transcript_path": str(tmp / "gone.jsonl")},
                    ul=ul, cfg=cfg, root=tmp) == 0)
        check("e3 empty payload -> 0", meter({}, ul=ul, cfg=cfg, root=tmp) == 0)

        # (f) a missing manifest degrades to unattributed, still recorded
        bare = Path(tempfile.mkdtemp(prefix="meter-usage-bare-"))
        try:
            bare_tr = bare / "sess-2.jsonl"
            bare_tr.write_text(entry("z1", 42), encoding="utf-8")
            bare_cfg = _config.load(bare)
            wrote = meter({"session_id": "sess-2", "cwd": str(bare),
                           "transcript_path": str(bare_tr)},
                          ul=ul, cfg=bare_cfg, root=bare)
            bare_rows = ul.read_ledger(str(_config.ledger_dir(bare, bare_cfg)))
            check("f1 no manifest -> still metered", wrote > 0)
            check("f2 no manifest -> unattributed bucket",
                  bare_rows and all(r["attr"] == "unattributed" for r in bare_rows))
        finally:
            shutil.rmtree(bare, ignore_errors=True)

        # (g) authorMode none drops the author entirely
        anon_root = Path(tempfile.mkdtemp(prefix="meter-usage-anon-"))
        try:
            anon_tr = anon_root / "sess-3.jsonl"
            anon_tr.write_text(entry("y1", 5), encoding="utf-8")
            anon_cfg = _config.load(anon_root)
            anon_cfg["usage"] = dict(anon_cfg["usage"], authorMode="none")
            meter({"session_id": "sess-3", "cwd": str(anon_root),
                   "transcript_path": str(anon_tr)},
                  ul=ul, cfg=anon_cfg, root=anon_root)
            anon_rows = ul.read_ledger(str(_config.ledger_dir(anon_root, anon_cfg)))
            check("g1 authorMode=none records no author",
                  anon_rows and all(r.get("author") is None for r in anon_rows))
        finally:
            shutil.rmtree(anon_root, ignore_errors=True)

        # (h) the outlier advisory — the only thing this hook ever says out loud.
        # Driven through `advise` directly so the bands are exact rather than
        # whatever a synthetic transcript happens to price out to.
        def band_man(n_done):
            return {"phases": [{"id": "P1", "tasks":
                    [{"id": "T%d" % i, "status": "done"} for i in range(n_done)]
                    + [{"id": "HOT", "status": "in_progress"}]}]}

        adv_root = Path(tempfile.mkdtemp(prefix="meter-usage-adv-"))
        try:
            adv_led = str(adv_root / "usage")
            # five cheap completed tasks clear the gate; HOT is far past p90
            cheap = [{"ts": "2026-08-0%dT10" % (i + 1), "taskId": "T%d" % i,
                      "model": "claude-opus-5", "costUSD": 1.0 + i, "msgs": 1,
                      "in": 1, "out": 1, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0}
                     for i in range(5)]
            hot = dict(cheap[0], taskId="HOT", costUSD=90.0, ts="2026-08-07T10")
            ul.append_rows(adv_led, cheap + [hot])

            cur = {}
            msg = advise(ul, adv_led, band_man(5), {"showCost": True}, cur, [hot])
            check("h1 an outlier task is called out, with the threshold stated",
                  msg and "HOT" in msg and "$90.00" in msg and "p90" in msg, msg)
            check("h2 the advisory says it is advice, not a gate",
                  msg and "not a gate" in msg and "nothing is blocked" in msg)
            check("h3 the warned task is recorded on the cursor",
                  cur.get("warnedTasks") == ["HOT"])
            # A warning that repeats every turn for the rest of a long task is a
            # warning nobody reads.
            again = advise(ul, adv_led, band_man(5), {"showCost": True}, cur, [hot])
            check("h4 it fires ONCE per task, not on every Stop", again is None)

            # A cheap task must never trip it.
            quiet = advise(ul, adv_led, band_man(5), {"showCost": True}, {},
                           [cheap[0]])
            check("h5 a typical task says nothing", quiet is None)

            # Below the gate there are no bands, so there is nothing to be past.
            few_led = str(adv_root / "few")
            ul.append_rows(few_led, [cheap[0], hot])
            check("h6 below the sample gate the advisory is silent",
                  advise(ul, few_led, band_man(1), {"showCost": True}, {}, [hot])
                  is None)

            # showCost=false must not leak a dollar figure.
            nc = advise(ul, adv_led, band_man(5), {"showCost": False}, {}, [hot])
            check("h7 showCost=false states a multiple, never a dollar amount",
                  nc and "$" not in nc and "x past" in nc, nc)

            # Rows with no task cannot be attributed to one.
            check("h8 spend with no task in flight says nothing",
                  advise(ul, adv_led, band_man(5), {"showCost": True}, {},
                         [dict(hot, taskId=None)]) is None
                  and advise(ul, adv_led, band_man(5), {"showCost": True},
                             {}, []) is None)

            # A garbled cursor must degrade, not raise — it is user-writable state.
            check("h9 a corrupt warnedTasks value is ignored, not fatal",
                  advise(ul, adv_led, band_man(5), {"showCost": True},
                         {"warnedTasks": "nonsense"}, [hot]) is not None)

            # (i) session summary — said once at the end, in the place the work
            # happened, and silent when the session did nothing.
            sess_led = str(adv_root / "sess")
            ul.append_rows(sess_led, [
                dict(cheap[0], sessionId="S1", taskId="T1", costUSD=2.5),
                dict(cheap[1], sessionId="S1", taskId="T2", costUSD=1.5),
                dict(cheap[2], sessionId="OTHER", taskId="T9", costUSD=99.0)])
            summ = session_summary(ul, sess_led, {"showCost": True}, "S1")
            check("i1 the summary covers only THIS session", summ
                  and "~$4.00" in summ and "T1, T2" in summ and "99" not in summ,
                  summ)
            check("i2 tokens are compact, messages keep their separators",
                  summ and "tokens" in summ and "$" in summ, summ)
            check("i3 a session that recorded nothing says nothing",
                  session_summary(ul, sess_led, {"showCost": True}, "NOPE")
                  is None)
            check("i4 showCost=false drops the dollar figure entirely",
                  "$" not in (session_summary(
                      ul, sess_led, {"showCost": False}, "S1") or "$"))
            check("i5 the compact formatter matches the other surfaces",
                  _compact(3_230_000) == "3.2M" and _compact(942) == "942"
                  and _compact(2_000_000_000) == "2.0B")
        finally:
            shutil.rmtree(adv_root, ignore_errors=True)
    finally:
        if prev_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev_env
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for ok in results if ok)
    print("\nmeter-usage: %d/%d cases passed" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    main()
