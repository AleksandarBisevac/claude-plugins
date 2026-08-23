#!/usr/bin/env python3
"""
The cases for `hooks/require-plan.py`, moved out of it - a hook, hyphenated, and the
one this repo dogfoods hardest: it is the gate that decides whether an edit happens.

The module comes through `_loader.load` by path out of `_harness.HOOKS_DIR`;
`_config` is imported directly, the way the hook imports it, because the fixtures
build configs from `_config.DEFAULTS` and the `o` group swaps `resolve_author` on the
module `_config._ledger_lib()` hands back.

SEVEN WRAPPERS WENT IN, TWO CAME OUT. `check`, `check_custom`, `check_graded` and
`check_knob` each re-implemented the same try/except around `decide` and printed
`(expected X, got Y)` on EVERY line; they now share one `_verdict()` built on
`_harness.attempt`, and that text is a DETAIL the harness renders only on failure.
`lkok`, `hok` and `ocheck` were already `check(label, cond, detail="")` with detail on
failure only - the exact contract `_harness` measured into the shared runner - so they
are simply bound to it. Seventeen further cases hand-rolled
`results.append(ok)` + `print("%s <label>")`; they call `check` now. The first
wrapper's name is `_expect` here, because `check` is the harness's.

THE ONE REBIND IS NOT THE `globals()` HAZARD. The `o` group swaps `resolve_author` on
the ledger module, and that module is fetched through `_config._ledger_lib()` - the
same cached object the production `_owner_note` path resolves the author through - so
it is seen from `tests/` exactly as it was from beside the hook, and it is restored in
a `finally`. Nothing here reads `globals()` or `vars()`, there is no `__file__`, no
path built off the suite's own directory, and no `split(a)[1].split(b)[0]`.

NO IMPORT EDGE MOVED WITH THIS SUITE, measured per CALL SITE. The `lk` group is the
only place in the file that named `_config._load_lock_lib()` directly, so that call
site left the hook - but the load it performs lives in `_config.py`, and production
still reaches it on every gated manifest write through
`_config.manifest_lock_conflict()`, which `decide()`'s lock branch calls. `_deps` does
not model `hooks/` as graph nodes at all (only the static hooks->scripts import ban),
so no `KNOWN_LAYER_DEBT` entry could have retired here even if one had.

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

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "require-plan.py"),
                 modname="require_plan")


# --- cases --------------------------------------------------------------------
def _cases(check):
    import platform
    import shutil

    tmp = Path(tempfile.mkdtemp(prefix="require-plan-selftest-"))
    sd = tmp / "state"
    ld = tmp / "logs"
    sd.mkdir(parents=True, exist_ok=True)
    ld.mkdir(parents=True, exist_ok=True)
    cfg = dict(_config.DEFAULTS)  # generic defaults, no project specifics

    # Pin the project dir. `decide` resolves the root via _config.repo_root, which
    # prefers CLAUDE_PROJECT_DIR over the payload's cwd — so run inside a real
    # session this suite was reading THIS repository's manifest. That was harmless
    # while the verdict ignored the manifest; now that its existence selects the
    # tier, an unpinned run would grade against whatever repo happens to be open.
    _prev_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    # Most cases below predate evidence grading and assert the fully-enforced
    # behaviour, so they run with enforce:true. The tiers themselves are exercised
    # by group (k), against real manifest fixtures.
    cfg["enforce"] = True

    def write_manifest(obj):
        """Write a manifest at the default manifestPath inside the temp project."""
        d = tmp / "docs" / "audit"
        d.mkdir(parents=True, exist_ok=True)
        (d / "audit-plan.json").write_text(json.dumps(obj), encoding="utf-8")

    def clear_manifest():
        shutil.rmtree(tmp / "docs", ignore_errors=True)

    session = "selftest-session-1"
    big = "\n".join("line %d" % i for i in range(120))  # 120 lines > 80

    def payload(tool, file_path, *, new_string=None, old_string=None,
                content=None, edits=None, new_source=None, sid=session):
        ti = {}
        if tool == "NotebookEdit":
            ti["notebook_path"] = file_path
        else:
            ti["file_path"] = file_path
        if content is not None:
            ti["content"] = content
        if new_string is not None:
            ti["new_string"] = new_string
        if old_string is not None:
            ti["old_string"] = old_string
        if edits is not None:
            ti["edits"] = edits
        if new_source is not None:
            ti["new_source"] = new_source
        return {"tool_name": tool, "tool_input": ti, "session_id": sid,
                "cwd": str(tmp)}

    def _verdict(data, use_cfg, event="PreToolUse"):
        """`decide`'s verdict, or the exception text - the guard all four of
        this suite's wrappers hand-rolled, now borrowed from `_harness`."""
        ok, got = _harness.attempt(M.decide, data, cfg=use_cfg, state_dir=sd,
                                   logs_dir=ld, event=event)
        return got[0] if ok else got

    def _expect(name, expected, data, event="PreToolUse"):
        verdict = _verdict(data, cfg, event)
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    # (a) exempt paths → allow
    _expect("a1 .md file", "allow", payload("Write", "README.md", content="hi"))
    _expect("a2 manifest json (docs/audit/**)", "allow",
          payload("Write", "docs/audit/x.json", content="{}"))
    _expect("a3 *.spec.ts", "allow",
          payload("Write", "src/foo/bar.spec.ts", content="test('x',()=>{})"))

    # (q) A1 (v0.36): a build config named like a test is NOT a test file. With
    # the gate enforced, `tsconfig.test.json` used to ride the `**/*.test.*`
    # exemption straight through; a real test file keeps it.
    _expect("q1 tsconfig.test.json is gated - config, not a test", "block",
          payload("Edit", "tsconfig.test.json", new_string=big,
                  sid="selftest-session-q1"))
    _expect("q2 a real test file stays exempt", "allow",
          payload("Edit", "src/foo/cart.test.ts", new_string=big,
                  sid="selftest-session-q1"))

    # (a4-a6) the manifest + its lock are never gated, even with a custom
    # manifestPath OUTSIDE the exempt globs
    cfg_custom = dict(cfg)
    cfg_custom["manifestPath"] = "planning/plan.json"

    def check_custom(name, expected, data):
        verdict = _verdict(data, cfg_custom)
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    check_custom("a4 custom-path manifest edit allowed", "allow",
                 payload("Edit", "planning/plan.json", new_string=big,
                         sid="selftest-session-a4"))
    check_custom("a5 custom-path lockfile allowed", "allow",
                 payload("Write", "planning/plan.json.lock", content="{}",
                         sid="selftest-session-a4"))
    # a5b-a5d: the SHARDS of a custom-path manifest. The orchestrator writes
    # `<manifest dir>/phases/<phaseId>.json` on every bookkeeping step, and exact
    # equality with manifestPath does not match those. At the default path it
    # worked by accident — `docs/audit/**` swallows the shards — so a phase run on
    # a custom sharded path died one step in, right after phase entry set
    # `in_progress` and flipped the gate to deny. Found by running the pipeline in
    # a sandbox whose manifest was not at the default path.
    check_custom("a5b custom-path phase shard allowed", "allow",
                 payload("Edit", "planning/phases/P1.json", new_string=big,
                         sid="selftest-session-a5b"))
    check_custom("a5c custom-path bugfix shard allowed", "allow",
                 payload("Edit", "planning/phases/BF1.json", new_string=big,
                         sid="selftest-session-a5c"))
    # Scoped to phases/*.json, NOT to the manifest's directory: a manifest at the
    # repo root would make that directory `.` and bypass the gate for everything.
    check_custom("a5d a non-shard file beside the manifest is still gated", "block",
                 payload("Edit", "planning/notes.json", new_string=big,
                         sid="selftest-session-a5d"))
    check_custom("a5e a non-JSON file inside phases/ is still gated", "block",
                 payload("Edit", "planning/phases/notes.txt", new_string=big,
                         sid="selftest-session-a5e"))
    check_custom("a6 sibling file still gated", "block",
                 payload("Write", "planning/other.json", content=big,
                         sid="selftest-session-a6"))

    # (lk) The concurrency lock, ENFORCED. Everything above decides whether an edit
    # is in the plan; this decides whether this session is the one holding the pen.
    # It is the only denial here that is not about the plan, so it gets pinned in
    # both directions and on every fail-open path — an unattributable lock that
    # could deny would brick legitimate work in a plugin that fails open by design.
    import subprocess as _sp
    _git = shutil.which("git")
    if not _git:
        print("SKIP lk* (git is not on PATH)")
    else:
        lkroot = Path(tempfile.mkdtemp(prefix="require-plan-lock-"))
        _sp.run([_git, "init", "-q", str(lkroot)], check=True,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        (lkroot / "audit" / "phases").mkdir(parents=True, exist_ok=True)
        # From DEFAULTS, not from `cfg` — earlier cases mutate that dict (enforce),
        # and the lock check must be pinned independently of whichever plan tier
        # happens to be in force when this block runs.
        lkcfg = dict(_config.DEFAULTS)
        lkcfg["manifestPath"] = "audit/plan.json"
        lockdir = Path(_config._load_lock_lib().lock_dir(str(lkroot)))
        lockdir.mkdir(parents=True, exist_ok=True)

        def put_lock(name, **fields):
            info = {"hostname": platform.node(),
                    "startedAt": _config.utc_stamp(), "note": "phase run"}
            info.update(fields)
            with open(lockdir / (name + ".lock"), "w", encoding="utf-8") as fh:
                json.dump(info, fh)

        # `lkok` was already the harness's shape - a label and a condition -
        # so it is simply `check`. These are plain assertions about the TEXT of
        # a refusal, which is the part a human acts on.
        lkok = check

        def lk(name, expected, rel, sid, event="PreToolUse"):
            data = payload("Edit", str(lkroot / rel), new_string=big, sid=sid)
            data["cwd"] = str(lkroot)
            data["hook_event_name"] = event
            got, msg = M.decide(data, cfg=lkcfg, state_dir=sd, logs_dir=ld,
                                event=event)
            check(name, got == expected,
                  "expected %s, got %s" % (expected, got))
            return msg

        _prev_lk = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(lkroot)
        try:
            lk("lk0 no lock at all -> the shard is writable", "allow",
               "audit/phases/P1.json", "sess-B")

            # A live holder. os.getpid() is a pid that is certainly running.
            put_lock("phase-P1", sessionId="sess-A", pid=os.getpid())
            msg = lk("lk1 another LIVE session's phase lock denies the shard", "block",
                     "audit/phases/P1.json", "sess-B")
            lkok("lk1b the denial names the holder", "sess-A" in msg)
            lkok("lk1c and the basis for calling it live", "is running on this host" in msg)
            lkok("lk1d and the one command that resolves it",
                  "audit-lock.py\" acquire phase-P1 --takeover" in msg)
            lk("lk2 the holder itself still writes freely", "allow",
               "audit/phases/P1.json", "sess-A")
            lk("lk3 a lock on P1 says nothing about P2", "allow",
               "audit/phases/P2.json", "sess-B")
            lk("lk4 nor about the index", "allow", "audit/plan.json", "sess-B")

            # An abandoned holder is not a denial case: nobody is writing against
            # you, so blocking would add friction after a crash and protect nothing.
            dead = _sp.Popen([sys.executable, "-c", "pass"]); dead.wait()
            put_lock("phase-P1", sessionId="sess-A", pid=dead.pid)
            msg = lk("lk5 an ABANDONED holder warns instead of denying", "warn",
                     "audit/phases/P1.json", "sess-B")
            lkok("lk5b the warning still says the lock is there",
                  "no longer running" in msg and "--takeover" in msg)

            # Fail-open paths. Each of these must allow, and each is a different
            # reason the lock cannot be attributed to anyone.
            put_lock("phase-P1", pid=os.getpid())
            lk("lk6 a lock with no sessionId can never deny", "allow",
               "audit/phases/P1.json", "sess-B")
            put_lock("phase-P1", sessionId="sess-A", pid=os.getpid())
            lk("lk7 nor can it deny a session with no id of its own", "allow",
               "audit/phases/P1.json", "")
            with open(lockdir / "phase-P1.lock", "w", encoding="utf-8") as fh:
                fh.write("{not json")
            lk("lk8 an unreadable lock allows", "allow",
               "audit/phases/P1.json", "sess-B")

            # The index tier, and the boundary: a lock governs manifest paths only.
            os.unlink(lockdir / "phase-P1.lock")
            put_lock("index", sessionId="sess-A", pid=os.getpid())
            msg = lk("lk9 a live index lock denies an index write", "block",
                     "audit/plan.json", "sess-B")
            lkok("lk9b and names the index tier", "index lock" in msg)
            lk("lk10 but not a shard write", "allow", "audit/phases/P1.json", "sess-B")
            msg = lk("lk11 an ordinary source file is untouched by the lock",
                     "observe", "src/other.py", "sess-B")
            # Not `"lock" not in msg`: "blocked" contains "lock". Assert on the
            # phrases the lock verdict actually uses.
            lkok("lk11b and its verdict talks about the plan, never the lock",
                 "would have blocked" in msg
                 and "under the" not in msg and "audit-lock.py" not in msg)

            # Post cannot deny; main() is what enforces that, so pin it there.
            put_lock("phase-P1", sessionId="sess-A", pid=os.getpid())
            lk("lk12 the verdict is the same on the Post pass", "block",
               "audit/phases/P1.json", "sess-B", event="PostToolUse")
            lkok("lk12b but main() prints no deny payload on Post",
                  "PostToolUse" in M._warn_payload("x")["hookSpecificOutput"]["hookEventName"])
        finally:
            if _prev_lk is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = _prev_lk
            shutil.rmtree(lkroot, ignore_errors=True)

    # (b) transactional slot: Pre allows but does NOT record; the matching Post
    #     records; only then does a second distinct file block.
    sess_b = "selftest-session-b"
    p_first = payload("Write", "src/foo/a.ts", content="export const a = 1;",
                      sid=sess_b)
    _expect("b1 first small file (Pre) allowed", "allow", p_first)
    gate = sd / ("plan-gate-%s.json" % sess_b)
    check("b2 Pre did NOT record the slot", not gate.exists())
    _expect("b3 second small file BEFORE any Post still allowed", "allow",
          payload("Write", "src/foo/b.ts", content="export const b = 2;", sid=sess_b))
    _expect("b4 Post records the slot", "allow", p_first, event="PostToolUse")
    check("b5 Post recorded the slot", gate.exists())
    _expect("b6 second distinct file after Post blocks", "block",
          payload("Write", "src/foo/b.ts", content="export const b = 2;", sid=sess_b))
    _expect("b7 same first file again allowed", "allow", p_first)

    # (c) magnitude: many lines, single-line blob, deletion-heavy edit
    _expect("c1 large new file blocks", "block",
          payload("Write", "src/foo/huge.ts", content=big, sid="selftest-session-c"))
    _expect("c2 single-line 20k-char blob blocks", "block",
          payload("Write", "src/foo/min.js", content="x" * 20000,
                  sid="selftest-session-c2"))
    _expect("c3 deletion-heavy edit blocks", "block",
          payload("Edit", "src/foo/mod.ts", new_string="// removed",
                  old_string=big + big, sid="selftest-session-c3"))
    _expect("c4 big NotebookEdit blocks", "block",
          payload("NotebookEdit", "notebooks/train.ipynb", new_source=big,
                  sid="selftest-session-c4"))
    _expect("c5 small NotebookEdit is the free slot", "allow",
          payload("NotebookEdit", "notebooks/train.ipynb", new_source="print(1)",
                  sid="selftest-session-c5"))

    # (d) with no in_progress task (empty tmp manifest), an uncovered file blocks
    _expect("d1 uncovered file blocks", "block",
          payload("Edit", "src/example/module.ts", new_string=big,
                  sid="selftest-session-d"))

    # (e) armed bypass: Pre observes without consuming; Post consumes + logs
    sess_e = "selftest-session-e"
    bp = sd / ("plan-bypass-%s.json" % sess_e)
    bp.write_text(json.dumps({"ts": M._now_iso(), "reason": "selftest"}),
                  encoding="utf-8")
    p_bypass = payload("Write", "src/foo/bypassed.ts", content=big, sid=sess_e)
    _expect("e1 armed bypass (Pre) allows", "allow", p_bypass)
    check("e2 Pre left the bypass armed", bp.exists())
    _expect("e3 Post consumes the bypass", "allow", p_bypass, event="PostToolUse")
    check("e4 bypass consumed (single-use)", not bp.exists())

    # (f) bypass consumption writes to the provided logs_dir
    log_file = ld / "plan-bypass.log"
    wrote = log_file.exists() and "session=%s" % sess_e in log_file.read_text(
        encoding="utf-8")
    check("f1 bypass logged to provided logs_dir", wrote)

    # (j) deny payload is canonical PreToolUse JSON
    blob = json.loads(json.dumps(M._deny_payload("why")))
    hso = blob.get("hookSpecificOutput") or {}
    check("j1 deny payload is canonical PreToolUse JSON",
          hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and str(hso.get("permissionDecisionReason", ""))
          .startswith("[require-plan]"))

    # (k) evidence grading. Same out-of-policy edit at each tier; only the amount
    #     the gate knows changes. cfg_graded drops the enforce override the rest of
    #     this suite uses.
    cfg_graded = dict(cfg)
    cfg_graded["enforce"] = False

    def check_graded(name, expected, data, event="PreToolUse"):
        verdict = _verdict(data, cfg_graded, event)
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    def offending(sid):
        return payload("Edit", "src/graded/mod.ts", new_string=big, sid=sid)

    clear_manifest()
    check_graded("k1 no manifest -> observe, never block", "observe",
                 offending("selftest-k1"))

    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "done",
         "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}]})
    check_graded("k2 manifest present, nothing running -> warn", "warn",
                 offending("selftest-k2"))

    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]})
    check_graded("k3 manifest + running phase -> block", "block",
                 offending("selftest-k3"))

    # A covered file is allowed on the strictest tier — grading changes only the
    # verdict for edits that were already out of policy.
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P1.1", "title": "t", "status": "in_progress",
             "files": ["src/graded/covered.ts"]}]}]})
    check_graded("k4 a covered file is allowed even at the deny tier", "allow",
                 payload("Edit", "src/graded/covered.ts", new_string=big,
                         sid="selftest-k4"))
    check_graded("k5 an exempt glob is allowed at the deny tier", "allow",
                 payload("Write", "README.md", content=big, sid="selftest-k5"))

    # The free small-file slot survives grading, on every tier.
    clear_manifest()
    check_graded("k6 a first small file is still allowed under observe", "allow",
                 payload("Write", "src/graded/small.ts", content="const a = 1;",
                         sid="selftest-k6"))

    # Observe records at Post so the next prompt can report it once; Pre does not.
    clear_manifest()
    obs_sid = "selftest-k7"
    obs_file = sd / ("plan-gate-observed-%s.json" % obs_sid)
    check_graded("k7 observe on Pre writes no tally", "observe",
                 offending(obs_sid))
    check("k8 Pre leaves the observe tally unwritten", not obs_file.exists())
    check_graded("k9 observe on Post still observes", "observe",
                 offending(obs_sid), event="PostToolUse")
    try:
        tally = json.loads(obs_file.read_text(encoding="utf-8"))
    except Exception:
        tally = {}
    check("k10 Post records the file in the observe tally (%r)"
          % (tally.get("files"),),
          tally.get("files") == ["src/graded/mod.ts"])

    # The tally name has to fall under the existing GC prefixes or it leaks forever.
    check("k11 the tally filename is swept by detect-plan-skip's GC prefixes",
          obs_file.name.startswith("plan-gate-"))
    check("k12 the tally does not collide with the free-file slot",
          obs_file.name != ("plan-gate-%s.json" % obs_sid))

    # enforce:true restores the pre-0.20 behaviour on the weakest evidence.
    check_graded("k13 enforce:false with no manifest observes", "observe",
                 offending("selftest-k13"))
    cfg_enforced = dict(cfg_graded)
    cfg_enforced["enforce"] = True
    verdict = _verdict(offending("selftest-k14"), cfg_enforced)
    check("k14 enforce:true blocks with no manifest at all (expected block, "
          "got %s)" % (verdict,), verdict == "block")

    # The warn payload must not be a permissionDecision — emitting `allow` would
    # auto-approve the tool call and bypass the user's own prompt.
    wp = json.loads(json.dumps(M._warn_payload("why")))
    hso = wp.get("hookSpecificOutput") or {}
    check("k15 warn is additionalContext on Post, never a permissionDecision",
          "permissionDecision" not in hso
          and hso.get("hookEventName") == "PostToolUse"
          and str(hso.get("additionalContext", ""))
          .startswith("[require-plan]"))

    # (g) the planGate knob, and the ask tier (v0.34 B1). Everything above
    # step 6 is untouched by pinning a tier: an exempt file, a covered file and
    # the first small file are allowed on EVERY tier, ask included (the k4/k5
    # rule, re-proven under the knob).
    def check_knob(name, expected, data, use_cfg=None, event="PreToolUse"):
        verdict = _verdict(data, use_cfg, event)
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    cfg_ask = dict(cfg_graded)
    cfg_ask["planGate"] = "ask"
    clear_manifest()
    check_knob("g1 planGate:'ask' turns an out-of-policy edit into ask", "ask",
               offending("selftest-g1"), use_cfg=cfg_ask)
    check_knob("g2 an exempt file is allowed at the ask tier", "allow",
               payload("Write", "README.md", content=big, sid="selftest-g2"),
               use_cfg=cfg_ask)
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P1.1", "title": "t", "status": "in_progress",
             "files": ["src/graded/covered.ts"]}]}]})
    check_knob("g3 a covered file is allowed at the ask tier", "allow",
               payload("Edit", "src/graded/covered.ts", new_string=big,
                       sid="selftest-g3"), use_cfg=cfg_ask)
    clear_manifest()
    check_knob("g4 the first small file is still free under ask", "allow",
               payload("Write", "src/graded/small.ts", content="const a=1;",
                       sid="selftest-g4"), use_cfg=cfg_ask)
    cfg_pin_deny = dict(cfg_graded)
    cfg_pin_deny["planGate"] = "deny"
    check_knob("g5 planGate:'deny' blocks with no manifest at all", "block",
               offending("selftest-g5"), use_cfg=cfg_pin_deny)
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]})
    cfg_pin_obs = dict(cfg_graded)
    cfg_pin_obs["planGate"] = "observe"
    check_knob("g6 planGate:'observe' observes even while a phase runs", "observe",
               offending("selftest-g6"), use_cfg=cfg_pin_obs)
    cfg_both = dict(cfg_graded)
    cfg_both.update(planGate="observe", enforce=True)
    check_knob("g7 planGate beats enforce when both are set", "observe",
               offending("selftest-g7"), use_cfg=cfg_both)
    check_knob("g8 ask is the verdict on the Post pass too - main() is what "
               "turns it into silence (the edit happened = the human approved)",
               "ask", offending("selftest-g8"), use_cfg=cfg_ask,
               event="PostToolUse")
    clear_manifest()

    # The ask payload's SHAPE is the pinned contract - the dialog itself cannot
    # be driven by a selftest (mirror of j1 and k15).
    ap = json.loads(json.dumps(M._ask_payload("why")))
    hso = ap.get("hookSpecificOutput") or {}
    check("g9 the ask payload is a canonical PreToolUse 'ask' decision",
          hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "ask"
          and str(hso.get("permissionDecisionReason", "")).startswith(
              "[require-plan]"))

    # main() routing: Pre prints the ask payload; Post prints nothing (silence
    # is the approval record - the gate event feed carries the trace).
    import io as _io
    gproj = Path(tempfile.mkdtemp(prefix="require-plan-ask-"))
    (gproj / ".claude").mkdir(parents=True, exist_ok=True)
    (gproj / ".claude" / "audit.config.json").write_text(
        json.dumps({"planGate": "ask"}), encoding="utf-8")

    def drive_main(event):
        _stdin, _stdout = sys.stdin, sys.stdout
        cap = _io.StringIO()
        code = None
        _prev = os.environ.get("CLAUDE_PROJECT_DIR")
        try:
            sys.stdin = _io.StringIO(json.dumps(
                {"tool_name": "Edit", "session_id": "ask-main",
                 "hook_event_name": event,
                 "tool_input": {"file_path": "src/asked.ts", "new_string": big},
                 "cwd": str(gproj)}))
            sys.stdout = cap
            os.environ["CLAUDE_PROJECT_DIR"] = str(gproj)
            try:
                M.main()
            except SystemExit as exc:
                code = exc.code
        finally:
            sys.stdin, sys.stdout = _stdin, _stdout
            if _prev is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = _prev
        return code, cap.getvalue()

    code, spoke = drive_main("PreToolUse")
    try:
        blob = json.loads(spoke) if spoke.strip() else {}
    except Exception:
        blob = {}
    check("g10 main() on Pre prints the ask payload and exits 0",
          code in (0, None) and (blob.get("hookSpecificOutput") or {})
          .get("permissionDecision") == "ask")
    code, spoke = drive_main("PostToolUse")
    check("g11 main() on Post prints NOTHING for ask - the edit happening "
          "IS the approval", code in (0, None) and spoke == "")
    shutil.rmtree(gproj, ignore_errors=True)

    # (h) what a refusal SAYS, by actual cause (F-F4), and the bypass TTL (B4).
    # The deny used to claim "A phase is in_progress" whether or not one was -
    # enforce:true with an empty repo produced a sentence that was flatly false,
    # and nothing pinned the text, which is how the bug shipped.
    def deny_msg(use_cfg, sid):
        try:
            return M.decide(offending(sid), cfg=use_cfg, state_dir=sd,
                          logs_dir=ld)
        except Exception as exc:  # pragma: no cover
            return ("EXC", str(exc))

    # `hok` and `ocheck` below were already `check(label, cond, detail="")`,
    # detail rendered on failure only - the exact contract `_harness` measured
    # into the shared runner, so they are that runner.
    hok = check

    clear_manifest()
    cfg_leg = dict(cfg_graded)
    cfg_leg["enforce"] = True
    v, m = deny_msg(cfg_leg, "selftest-h1")
    hok("h1 enforce:true with NO phase running blames the config, not a "
        "phantom phase",
        v == "block" and "enforce: true" in m and "legacy" in m
        and "A phase is in_progress" not in m, repr(m))
    cfg_pin = dict(cfg_graded)
    cfg_pin["planGate"] = "deny"
    v, m = deny_msg(cfg_pin, "selftest-h2")
    hok("h2 planGate:'deny' names the knob and says it holds regardless of "
        "what is running",
        v == "block" and 'planGate is set to "deny"' in m
        and "regardless of what is running" in m, repr(m))
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P3", "title": "p", "status": "in_progress",
         "tasks": [{"id": "P3.1", "title": "t", "status": "pending"}]}]})
    v, m = deny_msg(cfg_graded, "selftest-h3")
    hok("h3 a real running phase is NAMED - 'phase P3', not 'a phase'",
        v == "block" and "Phase P3 is in_progress" in m, repr(m))
    hok("h4 the refusal tells an agent to ask the human and NOT to recommend "
        "the bypass",
        "ask the human" in m and "do not recommend the bypass" in m, repr(m))
    hok("h5 ...and states the bypass facts: the HUMAN types it, single-use, "
        "logged, 30-minute expiry",
        "HUMAN" in m and "single-use" in m and "30 minutes" in m
        and "Agents cannot arm it" in m, repr(m))
    clear_manifest()

    # The TTL itself (require-plan's half: honouring it). Armed slots carry
    # armedAtEpoch (written by detect-plan-skip); older than the TTL = never
    # armed, deleted + logged on the Post pass; a legacy slot without the
    # field is honoured WITHOUT a TTL.
    sess_h = "selftest-h-ttl"
    bp_h = sd / ("plan-bypass-%s.json" % sess_h)
    p_ttl = payload("Write", "src/ttl/big.ts", content=big, sid=sess_h)
    bp_h.write_text(json.dumps({"ts": M._now_iso(), "reason": "fresh",
                                "armedAtEpoch": int(time.time())}),
                    encoding="utf-8")
    v, _m = M.decide(p_ttl, cfg=cfg, state_dir=sd, logs_dir=ld)
    hok("h6 a fresh armed bypass still allows on Pre", v == "allow")
    stale_epoch = int(time.time()) - _config.BYPASS_TTL_SECONDS - 120
    bp_h.write_text(json.dumps({"ts": M._now_iso(), "reason": "stale",
                                "armedAtEpoch": stale_epoch}),
                    encoding="utf-8")
    v, _m = M.decide(p_ttl, cfg=cfg, state_dir=sd, logs_dir=ld)
    hok("h7 an EXPIRED bypass does not arm - the edit is gated as if none "
        "existed (Pre leaves the file for Post to clean)",
        v == "block" and bp_h.exists(), repr(v))
    v, _m = M.decide(p_ttl, cfg=cfg, state_dir=sd, logs_dir=ld,
                     event="PostToolUse")
    log_txt = ((ld / "plan-bypass.log").read_text(encoding="utf-8")
               if (ld / "plan-bypass.log").exists() else "")
    hok("h8 the Post pass deletes the expired slot and logs 'expired unused'",
        v == "block" and not bp_h.exists()
        and "expired unused" in log_txt, repr((v, bp_h.exists())))
    bp_h.write_text(json.dumps({"ts": M._now_iso(), "reason": "legacy"}),
                    encoding="utf-8")
    v, _m = M.decide(p_ttl, cfg=cfg, state_dir=sd, logs_dir=ld)
    hok("h9 a legacy slot without armedAtEpoch is honoured WITHOUT a TTL "
        "(fail-open; the 7-day GC still sweeps it)", v == "allow")
    try:
        bp_h.unlink()
    except Exception:
        pass

    # (i) the gate events feed (v0.34 B3). Verdicts used to leave NO trace -
    # only the bypass had a log - so each branch now drops one compact line
    # into <logsDir>/plan-gate-events.jsonl. Pre records only what has no Post
    # (deny, ask.shown); everything else lands when the edit actually happened.
    def feed(p):
        f = p / _config.GATE_EVENTS_FILE
        if not f.exists():
            return []
        return [json.loads(line) for line in
                f.read_text(encoding="utf-8").splitlines() if line.strip()]

    clear_manifest()
    ild = tmp / "ev-observe"
    M.decide(offending("selftest-i1"), cfg=cfg_graded, state_dir=sd, logs_dir=ild)
    hok("i1 observe on Pre leaves no event - Pre records only deny/ask.shown",
        feed(ild) == [], repr(feed(ild)))
    M.decide(offending("selftest-i1"), cfg=cfg_graded, state_dir=sd,
             logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i2 observe on Post leaves ONE observe event naming file and session",
        len(rows) == 1 and rows[0].get("event") == "observe"
        and rows[0].get("file") == "src/graded/mod.ts"
        and rows[0].get("sessionId") == "selftest-i1", repr(rows))
    ild = tmp / "ev-deny"
    v, _m = M.decide(offending("selftest-i3"), cfg=cfg_pin, state_dir=sd,
                     logs_dir=ild)
    rows = feed(ild)
    hok("i3 a deny is recorded on Pre - there is no Post after a denial",
        v == "block" and len(rows) == 1 and rows[0].get("event") == "deny"
        and rows[0].get("mode") == "deny", repr(rows))
    ild = tmp / "ev-ask"
    M.decide(offending("selftest-i4"), cfg=cfg_ask, state_dir=sd, logs_dir=ild)
    M.decide(offending("selftest-i4"), cfg=cfg_ask, state_dir=sd,
             logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i4 ask leaves ask.shown on Pre and ask.approved on Post - the "
        "approval's only durable trace",
        [r.get("event") for r in rows] == ["ask.shown", "ask.approved"],
        repr(rows))
    ild = tmp / "ev-warn"
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "done",
         "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}]})
    v, m = M.decide(offending("selftest-i5"), cfg=cfg_graded, state_dir=sd,
                    logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i5 warn on Post leaves a warn event",
        v == "warn" and [r.get("event") for r in rows] == ["warn"], repr(rows))
    hok("i6 the warn text LEADS with the relay instruction - the cheap half "
        "of visibility, the feed is the durable half",
        m.startswith("Tell the human this verbatim before continuing"),
        repr(m[:80]))
    clear_manifest()
    ild = tmp / "ev-bypass"
    sess_i = "selftest-i7"
    bp_i = sd / ("plan-bypass-%s.json" % sess_i)
    bp_i.write_text(json.dumps({"ts": M._now_iso(), "reason": "x",
                                "armedAtEpoch": int(time.time())}),
                    encoding="utf-8")
    p_i = payload("Write", "src/ev/i7.ts", content=big, sid=sess_i)
    M.decide(p_i, cfg=cfg, state_dir=sd, logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i7 a consumed bypass is bypass.consumed",
        [r.get("event") for r in rows] == ["bypass.consumed"], repr(rows))
    bp_i.write_text(json.dumps({"ts": M._now_iso(), "reason": "x",
                                "armedAtEpoch": stale_epoch}), encoding="utf-8")
    M.decide(p_i, cfg=cfg, state_dir=sd, logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i8 an expired one is bypass.expired",
        rows and rows[-1].get("event") == "bypass.expired", repr(rows))
    ild = tmp / "ev-trivial"
    M.decide(payload("Write", "src/ev/small.ts", content="const a=1;",
                     sid="selftest-i9"), cfg=cfg_graded, state_dir=sd,
             logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i9 the recorded first small file is allow.trivial - the free slot is "
        "part of the gate's story too",
        [r.get("event") for r in rows] == ["allow.trivial"], repr(rows))
    ild = tmp / "ev-quiet"
    M.decide(payload("Write", "README.md", content=big, sid="selftest-i10"),
             cfg=cfg_graded, state_dir=sd, logs_dir=ild,
             event="PostToolUse")
    hok("i10 an exempt path leaves no feed line - the feed is verdicts, not "
        "an access log", feed(ild) == [])

    # (o) the ownership advisory on the covered path (v0.34 D2). Advisory by
    # construction: it rides additionalContext on the Post pass, never a
    # permissionDecision — Pre never speaks, no tier can turn it into a block,
    # and silence is the default in every direction (no owner declared
    # anywhere, explicit null, author matches, authorMode none). The git
    # subprocess behind the author is paid only past every cheaper gate, which
    # the call counter below pins.
    _ledmod = _config._ledger_lib()
    _orig_resolve = getattr(_ledmod, "resolve_author", None) if _ledmod else None
    _calls = {"n": 0}

    def _fake_resolve(_root, mode="email"):
        _calls["n"] += 1
        return None if mode == "none" else "sam@x.com"

    ocheck = check

    if _ledmod is None:
        print("SKIP o* (usage_ledger module unavailable)")
    else:
        _ledmod.resolve_author = _fake_resolve
        try:
            def own_phase(pid, area, files):
                return {"id": pid, "title": "p", "status": "in_progress",
                        "area": area,
                        "tasks": [{"id": pid + ".1", "title": "t",
                                   "status": "in_progress", "files": files}]}

            write_manifest({"meta": {"version": 2, "areas": {
                "api": {"root": "services/api", "owner": "jane@x.com"},
                "web": {"root": "apps/web", "owner": "sam@x.com"},
                "lib": {"root": "lib", "owner": None},
                "sec": {"root": "sec", "owner": "raj@x.com"}}},
                "phases": [
                    own_phase("P1", "api", ["src/own/a.ts", "src/own/a2.ts"]),
                    own_phase("P2", "web", ["src/own/b.ts"]),
                    own_phase("P3", "lib", ["src/own/c.ts"]),
                    own_phase("P4", "sec", ["src/own/d.ts"])]})
            sess_o = "selftest-own-1"
            overdicts = []

            def own(file, sid=sess_o, event="PreToolUse", use_cfg=None):
                v, m = M.decide(
                    payload("Edit", file, new_string=big, sid=sid),
                    cfg=use_cfg if use_cfg is not None else cfg_graded,
                    state_dir=sd, logs_dir=ld, event=event)
                overdicts.append(v)
                return v, m

            v, m = own("src/own/a.ts")
            ocheck("o1 Pre never speaks: a covered file with a mismatched owner "
                   "is a plain allow, and the author subprocess is never paid",
                   v == "allow" and _calls["n"] == 0, repr((v, _calls["n"])))
            v, m = own("src/own/a.ts", event="PostToolUse")
            ocheck("o2 Post on a mismatch is a warn with the measured wording - "
                   "heads-up, phase, area, owner, author, fine to continue",
                   v == "warn" and m.startswith("heads-up, not a gate:")
                   and "src/own/a.ts belongs to phase P1 (area 'api')" in m
                   and "whose owner is jane@x.com" in m
                   and "you are recorded as sam@x.com" in m
                   and "Fine to continue" in m
                   and "say so in the handoff" in m, repr((v, m)))
            note_file = sd / ("owner-note-%s.json" % sess_o)
            ocheck("o3 the throttle slot exists and its name starts with "
                   "'owner-note-' - the prefix detect-plan-skip's GC sweeps",
                   note_file.exists()
                   and note_file.name.startswith("owner-note-"),
                   repr(note_file))
            v, m = own("src/own/a2.ts", event="PostToolUse")
            ocheck("o4 the same session+area warns ONCE - a second covered edit "
                   "in the same area stays quiet",
                   v == "allow", repr((v, m)))
            v, m = own("src/own/d.ts", event="PostToolUse")
            ocheck("o5 a DIFFERENT area in the same session warns again - the "
                   "throttle is per session+area, not per session",
                   v == "warn" and "area 'sec'" in m
                   and "raj@x.com" in m, repr((v, m)))
            v, m = own("src/own/a.ts", sid="selftest-own-2",
                       event="PostToolUse")
            ocheck("o6 a NEW session is told once too - the note is session "
                   "state, not repo state",
                   v == "warn" and "jane@x.com" in m, repr((v, m)))
            v, m = own("src/own/b.ts", sid="selftest-own-3",
                       event="PostToolUse")
            ocheck("o7 the owner editing their own area hears nothing",
                   v == "allow", repr((v, m)))
            n_before = _calls["n"]
            v, m = own("src/own/c.ts", sid="selftest-own-3",
                       event="PostToolUse")
            ocheck("o8 an explicit null owner is 'nobody owns this' - silent, "
                   "and the author subprocess is never paid for it",
                   v == "allow" and _calls["n"] == n_before, repr((v, m)))
            cfg_none = _config._deep_merge(cfg_graded,
                                           {"usage": {"authorMode": "none"}})
            v, m = own("src/own/a.ts", sid="selftest-own-4",
                       event="PostToolUse", use_cfg=cfg_none)
            ocheck("o9 authorMode 'none' turns the advisory off silently - a "
                   "project that refuses attribution is not nudged about it",
                   v == "allow", repr((v, m)))
            write_manifest({"meta": {"version": 2, "areas": {
                "api": {"root": "services/api"}}},
                "phases": [own_phase("P1", "api", ["src/own/a.ts"])]})
            n_before = _calls["n"]
            v, m = own("src/own/a.ts", sid="selftest-own-5",
                       event="PostToolUse")
            ocheck("o10 no owner declared ANYWHERE is the default-off: silent, "
                   "zero cost past the manifest read, no knob needed",
                   v == "allow" and _calls["n"] == n_before, repr((v, m)))
            ocheck("o11 the advisory can never harden: every verdict above was "
                   "allow or warn, never block or ask",
                   overdicts and set(overdicts) <= {"allow", "warn"},
                   repr(overdicts))
            clear_manifest()
        finally:
            if _orig_resolve is not None:
                _ledmod.resolve_author = _orig_resolve

    if _prev_project_dir is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = _prev_project_dir

    # (p) _ensure_dir yields self-ignoring local dirs
    tmp_ig = Path(tempfile.mkdtemp(prefix="rp-ignore-"))
    try:
        M._ensure_dir(tmp_ig / "state")
        check("p1 _ensure_dir drops a `*` .gitignore - state and logs "
              "never belong in git",
              (tmp_ig / "state" / ".gitignore").exists())
    finally:
        shutil.rmtree(tmp_ig, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_require_plan.py --selftest\n")
    raise SystemExit(2)
