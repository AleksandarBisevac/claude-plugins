#!/usr/bin/env python3
"""
UserPromptSubmit hook — plan-first opt-out logger + config-error surfacing.

1. Bypass arming. Watches every submitted prompt for the bypass keyword
   (default `#no-plan`, overridable via `.claude/audit.config.json` →
   bypassKeyword, case-insensitive). When present, it ARMS a single-use
   plan-first bypass for the current session:
     - writes <stateDir>/plan-bypass-<session_id>.json ({ts, reason})
     - appends a line to <logsDir>/plan-bypass.log
     - tells the user (systemMessage) that the bypass is live
   The bypass is later CONSUMED (deleted — single-use) by require-plan.py's
   PostToolUse pass, after a non-trivial edit actually happened.

2. Config-error surfacing. When `.claude/audit.config.json` exists but is
   malformed, _config.load() falls back to defaults and sets a `_configError`
   marker. A silently broken config means the project's custom secret patterns
   / custom rules / thresholds are NOT applied — so this hook warns the user
   ONCE per session (flag file <stateDir>/config-error-notified-<session>.json).

3. State GC. Session state files (`plan-gate-*`, `tdd-reminder-*`,
   `bash-writes-*`, `config-error-notified-*`, `plan-bypass-*`) are otherwise
   never deleted; this hook opportunistically removes ones older than 7 days
   on every prompt — stale-session leftovers (and forgotten armed bypasses)
   expire instead of accumulating.

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
                "config-error-notified-", "plan-bypass-")
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


# --- detection ----------------------------------------------------------------
def _prompt_text(data: dict) -> str:
    for key in ("prompt", "user_prompt", "message"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _observed_message(state_dir: Path, session_id: str) -> list:
    """One line naming what the plan gate would have blocked, then never again.

    The tally is written by require-plan.py's observe tier. It is reported once and
    marked notified rather than deleted, so the count keeps accumulating while the
    message does not repeat — a warning that reappears on every turn is a warning
    nobody reads, which is the same reasoning meter-usage applies to its per-task
    advisory. Returns [] on anything unexpected; this is an advisory path."""
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
        return ["[audit] The plan gate would have held %d edit(s) this session: "
                "%s%s. It is observing, not enforcing, because this repo has no "
                "audit manifest — run /audit:init to turn enforcement on, or set "
                "\"enforce\": true in .claude/audit.config.json to enforce without "
                "one." % (len(files), shown, more)]
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
                    state_dir.mkdir(parents=True, exist_ok=True)
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
            ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
            snippet = " ".join(prompt.split())[:120]

            logs_dir = _config.logs_dir(root, cfg)
            state_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)

            with open(state_dir / ("plan-bypass-%s.json" % session_id), "w",
                      encoding="utf-8") as fh:
                json.dump({"ts": ts, "reason": snippet}, fh)

            with open(logs_dir / "plan-bypass.log", "a", encoding="utf-8") as fh:
                fh.write("%s session=%s bypass armed: %s\n"
                         % (ts, session_id, snippet))

            messages.append(
                "[audit] Plan-first bypass ARMED (%s): the next non-trivial "
                "edit in this session proceeds without a manifest task "
                "(single-use, logged)." % keyword)

        # --- 3. report what the plan gate observed, once per session ----------
        # In a repo with no manifest the gate records rather than denies. Saying so
        # once is what makes that tier useful: it demonstrates the guard working on
        # the user's own edits instead of asserting authority over them. Silence
        # here would make observe indistinguishable from the plugin being off.
        messages.extend(_observed_message(state_dir, session_id))
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
    check("h4 the message points at both exits (/audit:init and enforce)",
          first and "/audit:init" in first[0] and "enforce" in first[0])
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

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
