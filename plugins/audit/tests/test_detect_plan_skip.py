#!/usr/bin/env python3
"""
The cases for `hooks/detect-plan-skip.py`, moved out of it - a hook, hyphenated.

`detect-plan-skip.py` is a hook AND hyphenated, so it comes through `_loader.load`
by path out of `_harness.HOOKS_DIR` - not `_loader.load_script`, which resolves
against `scripts/`. `M` is the module under test; `_config` is imported directly,
the way the hook itself imports it, because `b4` asks about `_config`'s own
constant rather than about anything the hook re-exports.

NOTHING IN THIS SUITE HAD TO CHANGE MEANING TO MOVE. The AST scan for the six
shapes the guide forbids carrying literally came back empty: no `globals()` and no
`vars()` (nothing is stubbed - every case drives the real function against a temp
directory), no `__file__`, no path built off the suite's own directory, and no
`split(a)[1].split(b)[0]`. The hook loads no sibling through `_loader` and imports
only `_config`, which `main()` and `_arm_bypass()` both use in production, so no
graph edge left with the suite.

The `check(name, ok, detail="")` this file used is the harness's shape already -
including the "detail on failure only" rule - so the call sites are unchanged.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _config                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "detect-plan-skip.py"),
                 modname="detect_plan_skip")


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = Path(tempfile.mkdtemp(prefix="plan-skip-selftest-"))
    now = time.time()
    old = now - 8 * 86400

    stale = tmp / "plan-gate-dead-session.json"
    stale.write_text("{}", encoding="utf-8")
    os.utime(stale, (old, old))
    stale_bypass = tmp / "plan-bypass-dead-session.json"
    stale_bypass.write_text("{}", encoding="utf-8")
    os.utime(stale_bypass, (old, old))
    fresh = tmp / "tdd-reminder-live-session.json"
    fresh.write_text("{}", encoding="utf-8")
    foreign = tmp / "unrelated.json"
    foreign.write_text("{}", encoding="utf-8")
    os.utime(foreign, (old, old))

    removed = M._gc_state(tmp, now=now)
    check("g1 stale state files removed", removed == 2
          and not stale.exists() and not stale_bypass.exists(),
          "removed=%d" % removed)
    check("g2 fresh state file kept", fresh.exists())
    check("g3 foreign json untouched", foreign.exists())
    check("g4 missing dir is a no-op", M._gc_state(tmp / "nope") == 0)
    # F-B1: the journal pre-image slot holds file BYTES, and nothing deletes
    # it when a session dies between the Pre and Post passes - it must age
    # out with the rest of the session state instead of accumulating.
    stale_pre = tmp / "journal-preimage-dead-session.abcdef123456.json"
    stale_pre.write_text("{}", encoding="utf-8")
    os.utime(stale_pre, (old, old))
    check("g5 a stale journal pre-image slot is swept with the rest",
          M._gc_state(tmp, now=now) == 1 and not stale_pre.exists())
    # D2: require-plan's ownership-advisory throttle (`owner-note-<sid>.json`)
    # is session state like the rest - a session that dies keeps its slot
    # forever unless this sweep knows the prefix.
    stale_note = tmp / "owner-note-dead-session.json"
    stale_note.write_text("{}", encoding="utf-8")
    os.utime(stale_note, (old, old))
    check("g6 a stale ownership-advisory throttle slot is swept with the rest",
          M._gc_state(tmp, now=now) == 1 and not stale_note.exists())

    # (h) the observe tally is reported once and then stays quiet.
    sid = "obs-session"
    tally = tmp / ("plan-gate-observed-%s.json" % sid)
    check("h1 no tally -> no message", M._observed_message(tmp, sid) == [])

    tally.write_text(json.dumps({"files": ["src/a.ts", "src/b.ts"]}),
                     encoding="utf-8")
    first = M._observed_message(tmp, sid)
    check("h2 a tally produces exactly one message", len(first) == 1)
    check("h3 the message names the count and the files",
          first and "2 edit(s)" in first[0]
          and "src/a.ts" in first[0] and "src/b.ts" in first[0], repr(first))
    check("h4 the message points at both exits (/audit:init and planGate - the "
          "knob that replaced 'set enforce: true' in this sentence)",
          first and "/audit:init" in first[0] and "planGate" in first[0])
    check("h5 the same session is not told twice",
          M._observed_message(tmp, sid) == [])
    check("h6 the tally survives so the count keeps accumulating", tally.exists())

    many = tmp / ("plan-gate-observed-%s.json" % "obs-many")
    many.write_text(json.dumps({"files": ["a", "b", "c", "d", "e"]}),
                    encoding="utf-8")
    msg = M._observed_message(tmp, "obs-many")
    check("h7 long lists fold rather than dumping every path",
          msg and "(+2 more)" in msg[0], repr(msg))

    empty = tmp / ("plan-gate-observed-%s.json" % "obs-empty")
    empty.write_text(json.dumps({"files": []}), encoding="utf-8")
    check("h8 an empty tally says nothing",
          M._observed_message(tmp, "obs-empty") == [])
    bad = tmp / ("plan-gate-observed-%s.json" % "obs-bad")
    bad.write_text("not json", encoding="utf-8")
    check("h9 a corrupt tally is ignored, never raised",
          M._observed_message(tmp, "obs-bad") == [])
    check("h10 the tally prefix is one the GC already sweeps",
          tally.name.startswith(M._GC_PREFIXES))

    # (h11+) WHY observe is in force decides what the message claims (v0.34 B1):
    # with planGate: "observe" pinned, "this repo has no audit manifest" may be
    # flatly false - the honest sentence names the knob and how to unpin it.
    knobbed = tmp / ("plan-gate-observed-%s.json" % "obs-knob")
    knobbed.write_text(json.dumps({"files": ["src/k.ts"]}), encoding="utf-8")
    kmsg = M._observed_message(tmp, "obs-knob", cfg={"planGate": "observe"})
    check("h11 with the knob pinned, the message blames planGate, not a "
          "missing manifest",
          kmsg and 'planGate is set to "observe"' in kmsg[0]
          and "no audit manifest" not in kmsg[0], repr(kmsg))
    plain = tmp / ("plan-gate-observed-%s.json" % "obs-plain")
    plain.write_text(json.dumps({"files": ["src/p.ts"]}), encoding="utf-8")
    pmsg = M._observed_message(tmp, "obs-plain", cfg={})
    check("h12 without the knob, observe still means 'no manifest', and the "
          "message says so",
          pmsg and "no audit manifest" in pmsg[0], repr(pmsg))

    # (b) arming the bypass, extracted and testable (v0.34 B4): the slot
    # carries armedAtEpoch (epoch seconds - require-plan compares clock to
    # clock, no ISO %z parsing), and both the log line and the systemMessage
    # state the 30-minute unused-expiry out loud.
    bdir = tmp / "arm"
    bsd = bdir / "state"
    bld = bdir / "logs"
    t0 = time.time()
    # Guarded through `_harness.attempt` rather than the hand-rolled
    # `except Exception as exc: bmsg = "EXC: %s"` this case shipped with. The
    # two say the same thing about a raise, and the harness's form also carries
    # the exception TYPE, which a bare `str(exc)` does not - see `_harness`'s
    # docstring for why the per-case guard exists at all beside `run()`'s.
    _b_ok, bmsg = _harness.attempt(M._arm_bypass, bsd, bld, "sess-b", "#no-plan",
                                   "#no-plan   fix the flaky test  quickly")
    bslot = bsd / "plan-bypass-sess-b.json"
    try:
        bobj = json.loads(bslot.read_text(encoding="utf-8"))
    except Exception:
        bobj = {}
    check("b1 the slot carries the reason snippet AND armedAtEpoch as epoch "
          "seconds",
          isinstance(bobj.get("armedAtEpoch"), int)
          and t0 - 5 <= bobj["armedAtEpoch"] <= time.time() + 5
          and "fix the flaky test" in str(bobj.get("reason")), repr(bobj))
    try:
        blog = (bld / "plan-bypass.log").read_text(encoding="utf-8")
    except Exception:
        blog = ""
    check("b2 the log line says single-use and names the 30-minute expiry",
          "bypass armed" in blog and "30 minutes" in blog
          and "single-use" in blog, repr(blog))
    check("b3 the systemMessage says single-use, logged, expires in 30 "
          "minutes if unused",
          "#no-plan" in str(bmsg) and "single-use" in str(bmsg)
          and "expires in 30 minutes if unused" in str(bmsg), repr(bmsg))
    check("b4 the TTL is _config's constant, not a config key or a second "
          "number", getattr(_config, "BYPASS_TTL_SECONDS", None) == 30 * 60)
    try:
        bevents = [json.loads(line) for line in
                   (bld / _config.GATE_EVENTS_FILE).read_text(
                       encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        bevents = []
    check("b5 arming drops a bypass.armed line into the gate events feed "
          "(v0.34 B3) - the arm was previously visible only in the bypass log",
          len(bevents) == 1 and bevents[0].get("event") == "bypass.armed"
          and bevents[0].get("sessionId") == "sess-b", repr(bevents))

    # (i) local dirs are self-ignoring - state/logs never belong in git
    import shutil as _sh
    tmp_i = Path(tempfile.mkdtemp(prefix="dps-ignore-"))
    try:
        M._arm_bypass(tmp_i / "state", tmp_i / "logs", "s-i",
                      "#no-plan", "#no-plan quick fix")
        check("i1 arming the bypass leaves self-ignoring state and logs dirs",
              (tmp_i / "state" / ".gitignore").exists()
              and (tmp_i / "logs" / ".gitignore").exists())
    finally:
        _sh.rmtree(tmp_i, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_detect_plan_skip.py --selftest\n")
    raise SystemExit(2)
