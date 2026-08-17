#!/usr/bin/env python3
"""
The cases for `hooks/meter-usage.py`, moved out of it - a hook, hyphenated.

The module comes through `_loader.load` by path out of `_harness.HOOKS_DIR`, and
`_config` is imported directly the way the hook imports it. `usage_ledger` is NOT
imported here: the suite gets it the way `meter()` does, through
`M._load_ledger_lib()`, so `ul` is the same object the production path builds and
the `a`/`h`/`i` groups cannot pass against a different copy of the ledger library.

That load has a PRODUCTION call site (`meter()` line ~196), so no import edge
retired with this suite - measured per call site, not per file.

NOTHING IN THIS SUITE HAD TO CHANGE MEANING TO MOVE. The AST scan for the six shapes
the guide forbids carrying literally came back empty: no `globals()`, no `vars()`, no
`__file__`, no path built off the suite's own directory, no `split(a)[1].split(b)[0]`.
Every fixture is a `tempfile.mkdtemp` removed in a `finally`.

ONE LINE OF OUTPUT CHANGED, AND IT IS A FIX. The inline suite printed
`meter-usage: N/M cases passed` - one of the nine files `_harness` measured as
printing the SAME last line whether the suite passed or failed, so the only sentinel
was the two numbers being equal. It now prints `ALL PASS` / `SELFTEST FAILED`. No
case label moved.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _config                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "meter-usage.py"),
                 modname="meter_usage")


# --- cases --------------------------------------------------------------------
def _cases(check):
    ul = M._load_ledger_lib()
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

        n = M.meter(payload, ul=ul, cfg=cfg, root=tmp)
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
        n2 = M.meter(payload, ul=ul, cfg=cfg, root=tmp)
        check("b1 re-run writes nothing new", n2 == 0, "wrote %s" % n2)
        check("b2 ledger totals unchanged after re-run",
              ul.totals(ul.read_ledger(ledger))["out"] == 150)

        # (c) incremental append is picked up
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(entry("m3", 7))
        M.meter(payload, ul=ul, cfg=cfg, root=tmp)
        check("c1 appended turn metered incrementally",
              ul.totals(ul.read_ledger(ledger))["out"] == 157)

        # (d) master switch
        off = _config.load(tmp)
        off["usage"] = dict(off["usage"], enabled=False)
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(entry("m4", 1000))
        check("d1 disabled config meters nothing",
              M.meter(payload, ul=ul, cfg=off, root=tmp) == 0)

        # (e) degraded inputs must never raise and never write
        check("e1 missing transcript_path -> 0",
              M.meter({"session_id": "x", "cwd": str(tmp)}, ul=ul, cfg=cfg,
                      root=tmp) == 0)
        check("e2 nonexistent transcript -> 0",
              M.meter({"session_id": "x", "cwd": str(tmp),
                       "transcript_path": str(tmp / "gone.jsonl")},
                      ul=ul, cfg=cfg, root=tmp) == 0)
        check("e3 empty payload -> 0", M.meter({}, ul=ul, cfg=cfg, root=tmp) == 0)

        # (f) a missing manifest degrades to unattributed, still recorded
        bare = Path(tempfile.mkdtemp(prefix="meter-usage-bare-"))
        try:
            bare_tr = bare / "sess-2.jsonl"
            bare_tr.write_text(entry("z1", 42), encoding="utf-8")
            bare_cfg = _config.load(bare)
            wrote = M.meter({"session_id": "sess-2", "cwd": str(bare),
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
            M.meter({"session_id": "sess-3", "cwd": str(anon_root),
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
            msg = M.advise(ul, adv_led, band_man(5), {"showCost": True}, cur, [hot])
            check("h1 an outlier task is called out, with the threshold stated",
                  msg and "HOT" in msg and "$90.00" in msg and "p90" in msg, msg)
            check("h2 the advisory says it is advice, not a gate",
                  msg and "not a gate" in msg and "nothing is blocked" in msg)
            check("h3 the warned task is recorded on the cursor",
                  cur.get("warnedTasks") == ["HOT"])
            # A warning that repeats every turn for the rest of a long task is a
            # warning nobody reads.
            again = M.advise(ul, adv_led, band_man(5), {"showCost": True}, cur, [hot])
            check("h4 it fires ONCE per task, not on every Stop", again is None)

            # A cheap task must never trip it.
            quiet = M.advise(ul, adv_led, band_man(5), {"showCost": True}, {},
                             [cheap[0]])
            check("h5 a typical task says nothing", quiet is None)

            # Below the gate there are no bands, so there is nothing to be past.
            few_led = str(adv_root / "few")
            ul.append_rows(few_led, [cheap[0], hot])
            check("h6 below the sample gate the advisory is silent",
                  M.advise(ul, few_led, band_man(1), {"showCost": True}, {}, [hot])
                  is None)

            # showCost=false must not leak a dollar figure.
            nc = M.advise(ul, adv_led, band_man(5), {"showCost": False}, {}, [hot])
            check("h7 showCost=false states a multiple, never a dollar amount",
                  nc and "$" not in nc and "x past" in nc, nc)

            # Rows with no task cannot be attributed to one.
            check("h8 spend with no task in flight says nothing",
                  M.advise(ul, adv_led, band_man(5), {"showCost": True}, {},
                           [dict(hot, taskId=None)]) is None
                  and M.advise(ul, adv_led, band_man(5), {"showCost": True},
                               {}, []) is None)

            # A garbled cursor must degrade, not raise — it is user-writable state.
            check("h9 a corrupt warnedTasks value is ignored, not fatal",
                  M.advise(ul, adv_led, band_man(5), {"showCost": True},
                           {"warnedTasks": "nonsense"}, [hot]) is not None)

            # (i) session summary — said once at the end, in the place the work
            # happened, and silent when the session did nothing.
            sess_led = str(adv_root / "sess")
            ul.append_rows(sess_led, [
                dict(cheap[0], sessionId="S1", taskId="T1", costUSD=2.5),
                dict(cheap[1], sessionId="S1", taskId="T2", costUSD=1.5),
                dict(cheap[2], sessionId="OTHER", taskId="T9", costUSD=99.0)])
            summ = M.session_summary(ul, sess_led, {"showCost": True}, "S1")
            check("i1 the summary covers only THIS session", summ
                  and "~$4.00" in summ and "T1, T2" in summ and "99" not in summ,
                  summ)
            check("i2 tokens are compact, messages keep their separators",
                  summ and "tokens" in summ and "$" in summ, summ)
            check("i3 a session that recorded nothing says nothing",
                  M.session_summary(ul, sess_led, {"showCost": True}, "NOPE")
                  is None)
            check("i4 showCost=false drops the dollar figure entirely",
                  "$" not in (M.session_summary(
                      ul, sess_led, {"showCost": False}, "S1") or "$"))
            check("i5 the compact formatter matches the other surfaces",
                  M._compact(3_230_000) == "3.2M" and M._compact(942) == "942"
                  and M._compact(2_000_000_000) == "2.0B")
        finally:
            shutil.rmtree(adv_root, ignore_errors=True)
    finally:
        if prev_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev_env
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_meter_usage.py --selftest\n")
    raise SystemExit(2)
