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

Contract: ALWAYS exits 0 and prints nothing. Any unexpected input or exception
also exits 0 — metering must never break legitimate work. Registered in
hooks.json with the `open` (fail-silent) launcher mode for the same reason.

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


def meter(data, ul=None, cfg=None, root=None):
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
        })

    written = ul.append_rows(ledger, rows)
    # Persist the cursor even when nothing was written, so an oversized first-sight
    # transcript records its skip-to-EOF offset instead of re-deciding every turn.
    ul.save_cursor(ledger, session_id, cursor)
    return written


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        meter(data)
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
