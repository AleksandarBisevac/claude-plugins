#!/usr/bin/env python3
"""
The cases for `hooks/guard-secrets-read.py`, moved out of it - a hook, hyphenated.

The module comes through `_loader.load` by path out of `_harness.HOOKS_DIR`;
`_config` is imported directly, the way the hook imports it, because the fixtures are
built with `_config._deep_merge(_config.DEFAULTS, ...)`.

THE FIXTURE PATHS THAT NOW LIVE IN `tests/` ARE NOT REFERENCES, AND `_refs` KNOWS.
`s29`'s payload names a build script under a consumer's scripts directory and `b10`'s
names a hook under a consumer's hooks directory: both are text a CONSUMER's shell
command would carry, not paths into this plugin. The plugin's own `tests/` directory is
an ANCHORED surface in `_refs.SURFACES` for exactly this reason - a plugin path counts
as a reference only when it is written with the `plugins/audit/` anchor - so an
unanchored one inside this file is invisible to the lint, and `_refs`' own `a4` is the
case that goes red if that ever changes.

NOTHING ELSE HAD TO CHANGE MEANING TO MOVE: no `globals()`, no `vars()`, no `__file__`,
no path built off the suite's own directory, no `split(a)[1].split(b)[0]`. The hook
imports only `_config`, which every branch of `decide()` uses, so no import edge
retired with this suite.

THE DOMAIN WRAPPER STAYS HERE, RENAMED. `check(name, expected, data, use_cfg=None)` ran
`decide()` for the caller and printed `(expected X, got Y)` on every line; it is now
`_expect`, and that text is a harness DETAIL rendered only on failure. Eight further
cases hand-rolled `results.append(ok)` + `print("%s <label>")` pairs; they call `check`
now, and the `(%r)`-on-failure tails they built by hand are details too. Every label is
byte-identical.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _config                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "guard-secrets-read.py"),
                 modname="guard_secrets_read")


# --- cases --------------------------------------------------------------------
def _cases(check):
    """Exercise the decision core with fictional secret paths (never real files)."""
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    tmp = Path(tempfile.mkdtemp(prefix="guard-secrets-selftest-"))

    # Pin the project dir: repo_root prefers CLAUDE_PROJECT_DIR over the payload's
    # cwd, so unpinned this suite graded the shell plan gate against whatever
    # repository happened to be open.
    _prev_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    # The shell-write branch is a PLAN gate and is graded like require-plan's. The
    # cases that assert full enforcement say so explicitly.
    cfg_enforced = _config._deep_merge(cfg, {"enforce": True})

    def _expect(name, expected, data, use_cfg=None):
        """One case: run `decide` on `data` and compare its verdict to `expected`.

        Guarded through `_harness.attempt` rather than the hand-rolled
        `except Exception as exc: verdict = "EXC:%s"` the inline form carried, and
        the expected/got text that used to print on EVERY line is now a detail,
        rendered only when the case fails."""
        ok, got = _harness.attempt(M.decide, data, cfg=use_cfg or cfg)
        verdict = got[0] if ok else got
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    def read(fp):
        return {"tool_name": "Read", "tool_input": {"file_path": fp},
                "cwd": str(tmp)}

    def grep(pattern="x", path=None, glob=None):
        ti = {"pattern": pattern}
        if path is not None:
            ti["path"] = path
        if glob is not None:
            ti["glob"] = glob
        return {"tool_name": "Grep", "tool_input": ti, "cwd": str(tmp)}

    def bash(cmd):
        return {"tool_name": "Bash", "tool_input": {"command": cmd},
                "cwd": str(tmp)}

    # --- Read tool ---
    _expect("r1 Read .env blocked", "block", read("apps/foo/.env"))
    _expect("r2 Read .env.example allowed", "allow", read("apps/foo/.env.example"))
    _expect("r3 Read normal file allowed", "allow", read("apps/foo/index.ts"))

    # --- Grep tool ---
    _expect("g1 Grep path=.env blocked", "block", grep(pattern="X", path="apps/foo/.env"))
    _expect("g2 Grep glob=**/.env* blocked", "block", grep(pattern="T", glob="**/.env*"))
    _expect("g3 Grep glob=credentials* blocked", "block",
          grep(pattern="k", glob="credentials*"))
    _expect("g4 Grep path=.p12 blocked", "block", grep(pattern=".", path="ios/cert.p12"))
    _expect("g5 Grep .mobileprovision glob blocked", "block",
          grep(pattern=".", glob="**/*.mobileprovision"))
    _expect("g6 Grep .env.example path allowed", "allow",
          grep(pattern="X", path="apps/foo/.env.example"))
    _expect("g7 Grep normal source allowed", "allow",
          grep(pattern="useEffect", glob="**/*.tsx"))
    _expect("g8 Grep no path/glob allowed", "allow", grep(pattern="something"))

    # --- Bash inline-eval reads ---
    _expect("b1 python3 -c open(.env) blocked", "block",
          bash("python3 -c \"print(open('.env').read())\""))
    _expect("b3 node -e readFileSync(.env) blocked", "block",
          bash("node -e \"console.log(require('fs').readFileSync('.env','utf8'))\""))
    _expect("b5 ruby -e File.read(.env) blocked", "block",
          bash("ruby -e 'puts File.read(\".env\")'"))
    _expect("b7 python3 -c read p12 blocked", "block",
          bash("python3 -c \"open('cert.p12','rb').read()\""))
    _expect("b8 python3 -c innocent allowed", "allow", bash("python3 -c \"print(2+2)\""))
    _expect("b10 python selftest of a hook allowed", "allow",
          bash("python3 hooks/require-plan.py --selftest"))

    # --- Bash shell-verb reads ---
    _expect("b11 cat .env blocked", "block", bash("cat apps/foo/.env"))
    _expect("b12 printenv blocked", "block", bash("printenv"))

    # --- indirect reads: git show, source, dot-source, copy-verbs ---
    _expect("i1 git show HEAD:.env blocked", "block", bash("git show HEAD:.env"))
    _expect("i2 git cat-file -p HEAD:.env blocked", "block",
          bash("git cat-file -p HEAD:.env"))
    _expect("i3 git show of source file allowed", "allow",
          bash("git show HEAD:src/app.ts"))
    _expect("i4 source .env blocked", "block", bash("source .env && npm start"))
    _expect("i5 dot-source .env blocked", "block", bash(". .env && npm start"))
    _expect("i6 source nvm.sh allowed", "allow",
          bash("source ~/.nvm/nvm.sh && nvm use"))
    _expect("i7 cp .env to /tmp blocked", "block", bash("cp .env /tmp/e"))
    _expect("i8 mv secret keystore blocked", "block",
          bash("mv android/release.keystore /tmp/k"))
    _expect("i9 cp between source files allowed", "allow",
          bash("cp src/a.ts src/b.bak"))

    # --- SSH private keys + bare aws-style credentials ---
    _expect("k1 Read ~/.ssh/id_rsa (SSH private key) blocked", "block",
          read("~/.ssh/id_rsa"))
    _expect("k2 Read .ssh/id_ed25519 blocked", "block", read(".ssh/id_ed25519"))
    _expect("k3 Read id_rsa.pub (PUBLIC key) allowed", "allow",
          read(".ssh/id_rsa.pub"))
    _expect("k4 cat ~/.aws/credentials (bare, via Bash) blocked", "block",
          bash("cat ~/.aws/credentials"))
    _expect("k5 cat ~/.ssh/id_rsa via Bash blocked", "block",
          bash("cat ~/.ssh/id_rsa"))
    _expect("k6 Read client.pfx blocked", "block", read("certs/client.pfx"))
    _expect("k7 cat credentials.md (not a secret ext) allowed", "allow",
          bash("cat credentials.md"))

    # --- Listing NAMES stays allowed ---
    _expect("n1 ls .env* allowed", "allow", bash("ls .env*"))
    _expect("n4 find -name .env allowed", "allow", bash("find . -name '.env'"))

    # --- inline-eval WRITE heuristic ---
    _expect("w1 python -c write to .ts blocked", "block",
          bash("python3 -c \"open('src/foo/a.ts','w').write('x')\""))
    _expect("w4 python -c write to .claude path allowed", "allow",
          bash("python3 -c \"open('.claude/state/x.json','w').write('{}')\""))
    _expect("w5 node -e write to *.spec.ts allowed", "allow",
          bash("node -e \"fs.writeFileSync('src/foo/a.spec.ts','test')\""))
    # (w6/w7) F-A-1: the test-suffix exemption stops at data formats, exactly
    # as the Edit-path glob lists learned in v0.36 A1. `tsconfig.test.json` is
    # build configuration named like a test; the same file through Edit is
    # gated, and the eval-write backstop must not be the cheaper door.
    _expect("w6 python -c write to tsconfig.test.json blocked - a test-suffix "
          "name in a data format is config, not a test", "block",
          bash("python3 -c \"open('tsconfig.test.json','w').write('{}')\""))
    _expect("w7 python -c write to cart.test.ts stays exempt - a code-format "
          "test file keeps the exemption", "allow",
          bash("python3 -c \"open('cart.test.ts','w').write('x')\""))

    # --- shell writes into source files (plan-first backstop) ---
    _expect("s1 echo > source file blocked", "block",
          bash("echo 'x' > src/foo/a.ts"), use_cfg=cfg_enforced)
    _expect("s2 sed -i on source file blocked", "block",
          bash("sed -i 's/a/b/' src/app.ts"), use_cfg=cfg_enforced)
    _expect("s3 tee into source file blocked", "block",
          bash("cat patch.txt | tee src/app.py"), use_cfg=cfg_enforced)
    _expect("s4 heredoc redirect into source blocked", "block",
          bash("cat > src/gen.ts <<'EOF'\nexport {}\nEOF"), use_cfg=cfg_enforced)
    _expect("s5 append redirect into source blocked", "block",
          bash("echo '// x' >> src/app.go"), use_cfg=cfg_enforced)

    # (s-graded) the shell plan gate follows the same evidence tiers as
    # require-plan, so a file is treated the same whether the agent reaches for
    # `Edit` or for `sed -i`.
    _mdir = tmp / "docs" / "audit"
    _mdir.mkdir(parents=True, exist_ok=True)
    _mfile = _mdir / "audit-plan.json"

    _expect("s5a no manifest -> shell write observed, not blocked", "allow",
          bash("sed -i 's/a/b/' src/graded.ts"))

    _mfile.write_text(json.dumps({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "done",
         "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}]}),
        encoding="utf-8")
    _expect("s5b manifest, nothing running -> shell write not blocked", "allow",
          bash("sed -i 's/a/b/' src/graded.ts"))

    _mfile.write_text(json.dumps({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]}),
        encoding="utf-8")
    _expect("s5c manifest + running phase -> shell write blocked", "block",
          bash("sed -i 's/a/b/' src/graded.ts"))

    # Same running phase, but the file IS covered by its in_progress task: the gate
    # has nothing to object to, on any tier.
    _mfile.write_text(json.dumps({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P1.1", "title": "t", "status": "in_progress",
             "files": ["src/covered.ts"]}]}]}), encoding="utf-8")
    _expect("s5d a covered file is allowed at the deny tier", "allow",
          bash("sed -i 's/a/b/' src/covered.ts"))
    _expect("s5d2 an uncovered sibling is still blocked there", "block",
          bash("sed -i 's/a/b/' src/uncovered.ts"))

    # Secret detection is NOT graded — it needs no plan to be right, so it denies at
    # every tier including the one with no manifest at all.
    _expect("s5e reading .env is denied while the plan gate is at deny", "block",
          read(".env"))
    import shutil as _shutil
    _shutil.rmtree(tmp / "docs", ignore_errors=True)
    _expect("s5f .env is still denied with no manifest present", "block", read(".env"))
    _expect("s5g so is a credentials file", "block", read("config/credentials.json"))
    _expect("s5h and an ssh key", "block", read(".ssh/id_ed25519"))

    _expect("s6 redirect to log file allowed", "allow",
          bash("npm test > out.log 2>&1"))
    _expect("s7 redirect of grep output to /tmp allowed", "allow",
          bash("grep -r foo src/app.ts > /tmp/out.txt"))
    _expect("s8 write to exempt .md allowed", "allow",
          bash("echo hi > NOTES.md"))
    _expect("s9 write to test file allowed", "allow",
          bash("echo 'test' > src/foo/a.spec.ts"))
    _expect("s10 sed without -i (stdout) allowed", "allow",
          bash("sed 's/a/b/' src/app.ts"))

    # --- shell write covered by an in_progress task → allowed ---
    manifest_dir = tmp / "docs" / "audit"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "audit-plan.json").write_text(json.dumps({
        "meta": {"version": 2},
        "phases": [{"id": "P0", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P0.1", "title": "t", "status": "in_progress",
             "files": ["src/covered/mod.ts"], "tests": {"mode": "gate-only"}},
        ]}],
    }), encoding="utf-8")
    _expect("s11 sed -i on in_progress-covered file allowed", "allow",
          bash("sed -i 's/a/b/' src/covered/mod.ts"))
    _expect("s12 stdout `1>` into source file blocked", "block",
          bash("echo x 1> src/app.ts"))
    _expect("s13 clobber `>|` into source file blocked", "block",
          bash("echo x >| src/app.ts"))

    # (s14+) planGate parity (v0.34 B1): the shell-write branch follows the SAME
    # knob require-plan follows -- _help's gate page pins in prose that the two
    # halves grade identically, and an ask tier only one of them honours would
    # make that sentence a lie. The manifest fixture above still has phase P0
    # in_progress here, so 'observe while a phase runs' is a real pin, not a
    # vacuous one.
    cfg_ask = _config._deep_merge(_config.DEFAULTS, {"planGate": "ask"})
    _expect("s14 planGate:'ask' turns an uncovered shell write into ask", "ask",
          bash("sed -i 's/a/b/' src/uncovered-ask.ts"), use_cfg=cfg_ask)
    _expect("s15 a covered file is allowed at the ask tier", "allow",
          bash("sed -i 's/a/b/' src/covered/mod.ts"), use_cfg=cfg_ask)
    cfg_pin_obs = _config._deep_merge(_config.DEFAULTS, {"planGate": "observe"})
    _expect("s16 planGate:'observe' lets the shell write through while a phase "
          "runs (the same lowering require-plan honours)", "allow",
          bash("sed -i 's/a/b/' src/uncovered-observe.ts"), use_cfg=cfg_pin_obs)
    cfg_pin_deny = _config._deep_merge(_config.DEFAULTS, {"planGate": "deny",
                                                          "manifestPath":
                                                          "no/such/plan.json"})
    _expect("s17 planGate:'deny' blocks the shell write with no manifest at all",
          "block", bash("sed -i 's/a/b/' src/uncovered-deny.ts"),
          use_cfg=cfg_pin_deny)
    _expect("s18 secret reads are NOT graded - .env is refused at the ask tier "
          "too", "block", read(".env"), use_cfg=cfg_ask)
    # (s20+) what the shell refusal SAYS, by actual cause (F-F4) - the mirror
    # of require-plan's h group: this file used to claim "A phase is
    # in_progress" whether or not one was, on the same evidence tiers.
    def sdeny(use_cfg, cmd="sed -i 's/a/b/' src/blamed.ts"):
        ok, got = _harness.attempt(M.decide, bash(cmd), cfg=use_cfg)
        return got if ok else ("EXC", str(got))

    import shutil as _sh2
    _sh2.rmtree(tmp / "docs", ignore_errors=True)
    _v, _m = sdeny(cfg_enforced)
    check("s20 enforce:true with NO phase running blames the config, not a "
          "phantom phase",
          _v == "block" and "enforce: true" in _m and "legacy" in _m
          and "A phase is in_progress" not in _m, repr(_m))
    _v, _m = sdeny(_config._deep_merge(_config.DEFAULTS, {"planGate": "deny"}))
    check("s21 planGate:'deny' names the knob, exactly as require-plan does",
          _v == "block" and 'planGate is set to "deny"' in _m
          and "regardless of what is running" in _m, repr(_m))
    _mdir2 = tmp / "docs" / "audit"
    _mdir2.mkdir(parents=True, exist_ok=True)
    (_mdir2 / "audit-plan.json").write_text(json.dumps(
        {"meta": {"version": 2}, "phases": [
            {"id": "P7", "title": "p", "status": "in_progress",
             "tasks": [{"id": "P7.1", "title": "t", "status": "pending"}]}]}),
        encoding="utf-8")
    _v, _m = sdeny(cfg)
    check("s22 a real running phase is NAMED - 'phase P7', not 'a phase'",
          _v == "block" and "Phase P7 is in_progress" in _m, repr(_m))
    _sh2.rmtree(tmp / "docs", ignore_errors=True)

    # (s23+) F-B-1: the inline-eval heuristics judge each CLAUSE on its own
    # facts. A redirect in clause one plus an eval in clause two used to be read
    # as one command and denied — reproduced live with exactly s23's command
    # (a selftest run redirected to a log, then a harmless one-liner).
    _expect("s23 redirect in one clause + eval in another is NOT an eval-write",
          "allow",
          bash('python3 x.py --selftest >/tmp/out; '
               'python3 -c "import json; json.load(open(\'a.json\'))"'))
    _expect("s24 a genuine eval-write WITH a redirect in the same clause still "
          "denies", "block",
          bash('python3 -c "open(\'src/foo/gen.ts\',\'w\').write(\'x\')" '
               '>/tmp/out.log'))
    _expect("s25 a semicolon INSIDE the eval's quotes does not split the clause "
          "- the splitter is quote-aware, never looser for one clause", "block",
          bash('python3 -c "import os; '
               'open(\'src/foo/gen2.ts\',\'w\').write(\'x\')"'))
    _expect("s26 an eval-write that is the SECOND clause is still caught", "block",
          bash('echo x >/tmp/o; '
               'python3 -c "open(\'src/foo/gen3.ts\',\'w\').write(\'x\')"'))

    # (s27+) F-P-7: the eval-write backstop matched a WRITE CALL and a SOURCE
    # PATH anywhere in the same clause, never checking that the two were the
    # same thing. `>` inside the code (a comparison, or a redirect to /tmp) fed
    # the write half; the quoted name of the file being READ fed the target
    # half. Reported from a live repo: a read-only `python3 -c` over a .json
    # was refused as a source write, and the reader learned to route around the
    # guard with `jq`. A guard that cries on reads is a guard nobody reads.
    _expect("s27 a read-only one-liner over a .json is NOT a write, even with a "
          "comparison in it", "allow",
          bash('python3 -c "import json; d=json.load(open(\'package.json\')); '
               'print(len(d[\'scripts\'])>3)"'))
    _expect("s28 ...nor is one whose OUTPUT is redirected to a scratch file - the "
          "path it writes is not source, and shell redirects are the other "
          "backstop\'s business", "allow",
          bash('python3 -c "import json; print(json.load(open(\'pkg.json\'))[\'name\'])" '
               '> /tmp/name.txt'))
    _expect("s29 ...and reading a .py to print a line stays a read", "allow",
          bash('python3 -c "print(open(\'scripts/build.py\').read().splitlines()[0])"'))
    _expect("s30 the write half still denies when the WRITE ITSELF names source",
          "block",
          bash('python3 -c "json.dump(cfg, open(\'tsconfig.json\',\'w\'))"'))
    _expect("s31 ...including node, which names the target in the call", "block",
          bash('node -e "require(\'fs\').writeFileSync(\'src/gen.ts\', x)"'))
    _expect("s32 ...and a read of one file plus a write of another is a write",
          "block",
          bash('python3 -c "s=open(\'a.json\').read(); open(\'src/b.ts\',\'w\').write(s)"'))
    # The `>` alternative LEFT _WRITE_CALL with this fix, so the case it used to
    # cover is pinned here against the branch that actually owns it — a shell
    # redirect is _source_write_hit's grammar, graded like require-plan's gate.
    _expect("s33 an eval whose OUTPUT is redirected into source is still caught, "
          "by the shell-write branch rather than by the eval one", "block",
          bash('python3 -c "print(1)" > src/app.ts'), use_cfg=cfg_enforced)
    _expect("s34 _eval_write_targets names what a clause WRITES and nothing it "
          "merely mentions - the whole bug in one function",
          "allow" if (
              M._eval_write_targets(
                  'python3 -c "d=json.load(open(\'a.json\')); print(len(d)>2)"') == []
              and M._eval_write_targets(
                  'python3 -c "open(\'src/x.ts\',\'w\').write(1)"') == ["src/x.ts"]
          ) else "block", bash("true"))

    # The ask payload's SHAPE is the pinned contract (the dialog cannot be
    # driven by a selftest) - mirror of require-plan's g9 and of j1 below.
    _ap = json.loads(json.dumps(M._ask_payload("why")))
    _hso = _ap.get("hookSpecificOutput") or {}
    check("s19 the ask payload is a canonical PreToolUse 'ask' decision",
          _hso.get("hookEventName") == "PreToolUse"
          and _hso.get("permissionDecision") == "ask"
          and str(_hso.get("permissionDecisionReason", "")).startswith(
              "[guard-secrets-read]"))

    # --- extra pattern from config ---
    cfg_extra = _config._deep_merge(
        _config.DEFAULTS, {"secretPatterns": {"extra": [r"\.secretrc$"]}})
    _expect("x1 Read .secretrc (extra) blocked", "block", read("app/.secretrc"),
          use_cfg=cfg_extra)
    _expect("x2 Read normal (extra cfg) allowed", "allow", read("app/index.ts"),
          use_cfg=cfg_extra)

    # --- malformed / unhandled → allow ---
    _expect("u1 unhandled tool allowed", "allow",
          {"tool_name": "Glob", "tool_input": {"pattern": ".env"}, "cwd": str(tmp)})
    _expect("u2 empty input allowed", "allow", {"cwd": str(tmp)})

    # --- deny payload is canonical PreToolUse JSON ---
    blob = json.loads(json.dumps(M._deny_payload("why")))
    hso = blob.get("hookSpecificOutput") or {}
    check("j1 deny payload is canonical PreToolUse JSON",
          hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and str(hso.get("permissionDecisionReason", "")).startswith(
              "[guard-secrets-read]"))

    # (t) A4 (v0.36): deny/ask verdicts leave one line in the gate events feed,
    # require-plan's shape (v0.34 B3) — this guard's denials were invisible in
    # the feed the panel reads. Telemetry only: an allow writes nothing, and
    # the writer never raises into the hook.
    import shutil as _sh_t
    tmp_t = Path(tempfile.mkdtemp(prefix="guard-secrets-events-"))
    _prev_t = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_t)
    try:
        _feed = tmp_t / ".claude" / "logs" / "plan-gate-events.jsonl"

        def _rows():
            try:
                return [json.loads(x) for x in
                        _feed.read_text(encoding="utf-8").splitlines()]
            except Exception:
                return []

        _v, _ = M.decide({"tool_name": "Read",
                          "tool_input": {"file_path": "apps/x/.env"},
                          "session_id": "sess-t", "cwd": str(tmp_t)}, cfg=cfg)
        _rw = _rows()
        check("t1 a deny leaves ONE gate event line, named as this guard's",
              _v == "block" and len(_rw) == 1
              and _rw[-1].get("event") == "deny"
              and _rw[-1].get("mode") == "deny"
              and _rw[-1].get("file") == "apps/x/.env"
              and _rw[-1].get("sessionId") == "sess-t"
              and str(_rw[-1].get("reason", "")).startswith(
                  "guard-secrets-read:"), repr(_rw))
        _v, _ = M.decide({"tool_name": "Read",
                          "tool_input": {"file_path": "src/ok.ts"},
                          "session_id": "sess-t", "cwd": str(tmp_t)}, cfg=cfg)
        check("t2 an allow writes nothing - the feed records verdicts, not "
              "traffic", _v == "allow" and len(_rows()) == 1)
        _v, _ = M.decide(
            {"tool_name": "Bash",
             "tool_input": {"command": "sed -i 's/a/b/' src/t-ask.ts"},
             "session_id": "sess-t", "cwd": str(tmp_t)}, cfg=cfg_ask)
        _rw = _rows()
        check("t3 an ask verdict is recorded as ask.shown, the same event "
              "require-plan writes",
              _v == "ask" and len(_rw) == 2
              and _rw[-1].get("event") == "ask.shown"
              and _rw[-1].get("mode") == "ask", repr(_rw))
    finally:
        if _prev_t is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = _prev_t
        _sh_t.rmtree(tmp_t, ignore_errors=True)

    if _prev_project_dir is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = _prev_project_dir


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_secrets_read.py --selftest\n")
    raise SystemExit(2)
