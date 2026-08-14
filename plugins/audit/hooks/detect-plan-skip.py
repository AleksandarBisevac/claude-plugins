#!/usr/bin/env python3
"""
UserPromptSubmit hook — plan-first opt-out logger + config-error surfacing.

1. Bypass arming. Watches every submitted prompt for the bypass keyword
   (default `#no-plan`, overridable via `.claude/audit.config.json` →
   bypassKeyword, case-insensitive). When present, it ARMS a single-use
   plan-first bypass for the current session (see `_arm_bypass`):
     - writes <stateDir>/plan-bypass-<session_id>.json
       ({ts, reason, armedAtEpoch})
     - appends a line to <logsDir>/plan-bypass.log and a `bypass.armed` line
       to the gate events feed
     - tells the user (systemMessage) that the bypass is live and expires
       unused after 30 minutes (_config.BYPASS_TTL_SECONDS)
   The bypass is later CONSUMED (deleted — single-use) by require-plan.py's
   PostToolUse pass, after a non-trivial edit actually happened; unused past
   the TTL it is treated as never armed and cleaned up there.

2. Config-error surfacing. When `.claude/audit.config.json` exists but is
   malformed, _config.load() falls back to defaults and sets a `_configError`
   marker. A silently broken config means the project's custom secret patterns
   / custom rules / thresholds are NOT applied — so this hook warns the user
   ONCE per session (flag file <stateDir>/config-error-notified-<session>.json).

3. State GC. Session state files (`plan-gate-*`, `tdd-reminder-*`,
   `bash-writes-*`, `config-error-notified-*`, `plan-bypass-*`,
   `journal-preimage-*`, `owner-note-*`) are otherwise never deleted; this hook
   opportunistically removes ones older than 7 days on every prompt —
   stale-session leftovers (and forgotten armed bypasses) expire instead
   of accumulating.

This hook never blocks a prompt. Messages go out as JSON {"systemMessage": ...}
on stdout with exit 0.

Contract: always exit 0. Any unexpected input / exception also exits 0.
Run `python3 detect-plan-skip.py --selftest` to exercise the GC helper.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402


# --- state gc -----------------------------------------------------------------
_GC_PREFIXES = ("plan-gate-", "tdd-reminder-", "bash-writes-",
                "config-error-notified-", "plan-bypass-",
                # journal-writes.py's Pre-pass slot: it holds pre-image BYTES
                # and its normal lifecycle (Post pass consumes it) never runs
                # when a session dies between the two passes (F-B1).
                "journal-preimage-",
                # require-plan.py's ownership-advisory throttle (v0.34 D2):
                # which area tags this session has already been nudged about.
                "owner-note-")
_GC_MAX_AGE = 7 * 86400  # seconds


def _gc_state(state_dir: Path, now: float = None) -> int:
    """Delete session state files older than 7 days. Returns count removed.
    Best-effort — never raises."""
    removed = 0
    try:
        now = now if now is not None else time.time()
        for f in state_dir.glob("*.json"):
            if not f.name.startswith(_GC_PREFIXES):
                continue
            try:
                if now - f.stat().st_mtime > _GC_MAX_AGE:
                    f.unlink()
                    removed += 1
            except Exception:
                continue
    except Exception:
        pass
    return removed


# --- arming the bypass ----------------------------------------------------------
def _arm_bypass(state_dir: Path, logs_dir: Path, session_id: str,
                keyword: str, prompt: str) -> str:
    """Arm the single-use plan-first bypass; returns the systemMessage line.

    Extracted from main() so the TTL contract is testable (v0.34 B4). The slot
    carries `armedAtEpoch` as EPOCH SECONDS -- require-plan compares clock to
    clock, with no %z ISO parsing to get wrong -- and both the log line and the
    message say the bypass expires unused after 30 minutes, because a fact that
    changes what the keyword means belongs where the keyword is used."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    snippet = " ".join(prompt.split())[:120]
    minutes = _config.BYPASS_TTL_SECONDS // 60
    _config.ensure_local_dir(state_dir)
    _config.ensure_local_dir(logs_dir)
    with open(state_dir / ("plan-bypass-%s.json" % session_id), "w",
              encoding="utf-8") as fh:
        json.dump({"ts": ts, "reason": snippet,
                   "armedAtEpoch": int(time.time())}, fh)
    with open(logs_dir / "plan-bypass.log", "a", encoding="utf-8") as fh:
        fh.write("%s session=%s bypass armed (single-use, expires unused "
                 "after %d minutes): %s\n" % (ts, session_id, minutes, snippet))
    _config.append_gate_event(logs_dir, {
        "event": "bypass.armed", "reason": snippet, "sessionId": session_id})
    return ("[audit] Plan-first bypass ARMED (%s): the next non-trivial edit "
            "in this session proceeds without a manifest task (single-use, "
            "logged, expires in %d minutes if unused)." % (keyword, minutes))


# --- detection ----------------------------------------------------------------
def _prompt_text(data: dict) -> str:
    for key in ("prompt", "user_prompt", "message"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _observed_message(state_dir: Path, session_id: str, cfg=None) -> list:
    """One line naming what the plan gate would have blocked, then never again.

    The tally is written by require-plan.py's observe tier. It is reported once and
    marked notified rather than deleted, so the count keeps accumulating while the
    message does not repeat — a warning that reappears on every turn is a warning
    nobody reads, which is the same reasoning meter-usage applies to its per-task
    advisory. Returns [] on anything unexpected; this is an advisory path.

    WHY observe is in force decides what the line claims (v0.34 B1): with
    planGate: "observe" pinned, "this repo has no audit manifest" may be flatly
    false — the honest sentence names the knob and how to unpin it."""
    try:
        path = state_dir / ("plan-gate-observed-%s.json" % session_id)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as fh:
            tally = json.load(fh) or {}
        if not isinstance(tally, dict) or tally.get("notified"):
            return []
        files = [f for f in (tally.get("files") or []) if f]
        if not files:
            return []
        tally["notified"] = True
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(tally, fh)
        except Exception:
            pass
        shown = ", ".join(files[:3])
        more = "" if len(files) <= 3 else " (+%d more)" % (len(files) - 3)
        if _config.plan_gate_knob(cfg) == "observe":
            why = ("It is observing because planGate is set to \"observe\" in "
                   ".claude/audit.config.json - remove the key (or set it to "
                   "\"deny\") to enforce.")
        else:
            why = ("It is observing, not enforcing, because this repo has no "
                   "audit manifest - run /audit:init to turn enforcement on, or "
                   "set \"planGate\": \"deny\" in .claude/audit.config.json to "
                   "enforce without one.")
        return ["[audit] The plan gate would have held %d edit(s) this session: "
                "%s%s. %s" % (len(files), shown, more, why)]
    except Exception:
        return []


# --- cli ----------------------------------------------------------------------
def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    messages = []
    try:
        root = _config.repo_root(data)
        cfg = _config.load(root)
        session_id = str(data.get("session_id", "") or "no-session")
        state_dir = _config.state_dir(root, cfg)

        # --- 0. opportunistic GC of stale session state -----------------------
        _gc_state(state_dir)

        # --- 1. surface a malformed config, once per session -----------------
        err = cfg.get("_configError")
        if err:
            flag = state_dir / ("config-error-notified-%s.json" % session_id)
            if not flag.exists():
                try:
                    _config.ensure_local_dir(state_dir)
                    flag.write_text(json.dumps({"error": str(err)}),
                                    encoding="utf-8")
                except Exception:
                    pass
                messages.append(
                    "[audit] .claude/audit.config.json is malformed (%s). "
                    "Safe defaults are active — the project's custom secret "
                    "patterns, custom rules and thresholds are NOT applied. "
                    "Fix the file to restore them." % err)

        # --- 2. arm the single-use bypass when the keyword is present --------
        keyword = (cfg.get("bypassKeyword")
                   or _config.DEFAULTS["bypassKeyword"]).lower()
        prompt = _prompt_text(data)
        if keyword in prompt.lower():
            messages.append(_arm_bypass(state_dir, _config.logs_dir(root, cfg),
                                        session_id, keyword, prompt))

        # --- 3. report what the plan gate observed, once per session ----------
        # In a repo with no manifest the gate records rather than denies. Saying so
        # once is what makes that tier useful: it demonstrates the guard working on
        # the user's own edits instead of asserting authority over them. Silence
        # here would make observe indistinguishable from the plugin being off.
        messages.extend(_observed_message(state_dir, session_id, cfg=cfg))
    except Exception:
        sys.exit(0)

    if messages:
        try:
            print(json.dumps({"systemMessage": "\n".join(messages)}))
        except Exception:
            pass
    sys.exit(0)


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import tempfile

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

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

    removed = _gc_state(tmp, now=now)
    check("g1 stale state files removed", removed == 2
          and not stale.exists() and not stale_bypass.exists(),
          "removed=%d" % removed)
    check("g2 fresh state file kept", fresh.exists())
    check("g3 foreign json untouched", foreign.exists())
    check("g4 missing dir is a no-op", _gc_state(tmp / "nope") == 0)
    # F-B1: the journal pre-image slot holds file BYTES, and nothing deletes
    # it when a session dies between the Pre and Post passes - it must age
    # out with the rest of the session state instead of accumulating.
    stale_pre = tmp / "journal-preimage-dead-session.abcdef123456.json"
    stale_pre.write_text("{}", encoding="utf-8")
    os.utime(stale_pre, (old, old))
    check("g5 a stale journal pre-image slot is swept with the rest",
          _gc_state(tmp, now=now) == 1 and not stale_pre.exists())
    # D2: require-plan's ownership-advisory throttle (`owner-note-<sid>.json`)
    # is session state like the rest - a session that dies keeps its slot
    # forever unless this sweep knows the prefix.
    stale_note = tmp / "owner-note-dead-session.json"
    stale_note.write_text("{}", encoding="utf-8")
    os.utime(stale_note, (old, old))
    check("g6 a stale ownership-advisory throttle slot is swept with the rest",
          _gc_state(tmp, now=now) == 1 and not stale_note.exists())

    # (h) the observe tally is reported once and then stays quiet.
    sid = "obs-session"
    tally = tmp / ("plan-gate-observed-%s.json" % sid)
    check("h1 no tally -> no message", _observed_message(tmp, sid) == [])

    tally.write_text(json.dumps({"files": ["src/a.ts", "src/b.ts"]}),
                     encoding="utf-8")
    first = _observed_message(tmp, sid)
    check("h2 a tally produces exactly one message", len(first) == 1)
    check("h3 the message names the count and the files",
          first and "2 edit(s)" in first[0]
          and "src/a.ts" in first[0] and "src/b.ts" in first[0], repr(first))
    check("h4 the message points at both exits (/audit:init and planGate - the "
          "knob that replaced 'set enforce: true' in this sentence)",
          first and "/audit:init" in first[0] and "planGate" in first[0])
    check("h5 the same session is not told twice", _observed_message(tmp, sid) == [])
    check("h6 the tally survives so the count keeps accumulating", tally.exists())

    many = tmp / ("plan-gate-observed-%s.json" % "obs-many")
    many.write_text(json.dumps({"files": ["a", "b", "c", "d", "e"]}),
                    encoding="utf-8")
    msg = _observed_message(tmp, "obs-many")
    check("h7 long lists fold rather than dumping every path",
          msg and "(+2 more)" in msg[0], repr(msg))

    empty = tmp / ("plan-gate-observed-%s.json" % "obs-empty")
    empty.write_text(json.dumps({"files": []}), encoding="utf-8")
    check("h8 an empty tally says nothing",
          _observed_message(tmp, "obs-empty") == [])
    bad = tmp / ("plan-gate-observed-%s.json" % "obs-bad")
    bad.write_text("not json", encoding="utf-8")
    check("h9 a corrupt tally is ignored, never raised",
          _observed_message(tmp, "obs-bad") == [])
    check("h10 the tally prefix is one the GC already sweeps",
          tally.name.startswith(_GC_PREFIXES))

    # (h11+) WHY observe is in force decides what the message claims (v0.34 B1):
    # with planGate: "observe" pinned, "this repo has no audit manifest" may be
    # flatly false - the honest sentence names the knob and how to unpin it.
    knobbed = tmp / ("plan-gate-observed-%s.json" % "obs-knob")
    knobbed.write_text(json.dumps({"files": ["src/k.ts"]}), encoding="utf-8")
    kmsg = _observed_message(tmp, "obs-knob", cfg={"planGate": "observe"})
    check("h11 with the knob pinned, the message blames planGate, not a "
          "missing manifest",
          kmsg and 'planGate is set to "observe"' in kmsg[0]
          and "no audit manifest" not in kmsg[0], repr(kmsg))
    plain = tmp / ("plan-gate-observed-%s.json" % "obs-plain")
    plain.write_text(json.dumps({"files": ["src/p.ts"]}), encoding="utf-8")
    pmsg = _observed_message(tmp, "obs-plain", cfg={})
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
    try:
        bmsg = _arm_bypass(bsd, bld, "sess-b", "#no-plan",
                           "#no-plan   fix the flaky test  quickly")
    except Exception as exc:  # pragma: no cover (red before the extraction)
        bmsg = "EXC: %s" % exc
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
        _arm_bypass(tmp_i / "state", tmp_i / "logs", "s-i",
                    "#no-plan", "#no-plan quick fix")
        check("i1 arming the bypass leaves self-ignoring state and logs dirs",
              (tmp_i / "state" / ".gitignore").exists()
              and (tmp_i / "logs" / ".gitignore").exists())
    finally:
        _sh.rmtree(tmp_i, ignore_errors=True)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
