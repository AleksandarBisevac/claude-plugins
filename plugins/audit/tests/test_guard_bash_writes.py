#!/usr/bin/env python3
"""
The cases for `hooks/guard-bash-writes.py`, moved out of it - a hook, hyphenated.

The module comes through `_loader.load` by path out of `_harness.HOOKS_DIR`;
`_config` is imported directly, the way the hook imports it.

K1 STILL DRIVES THE REAL WRITER, AND THAT IS WHY IT NEEDED THE ONE PATH FIX. The
`k` group exists because the plugin's OWN journal append lands in `git status` and
used to be blamed on the next shell command; the fix is a sidecar written by
`journal-writes.py` and read here, and `k1` loads that hook and runs its real
`post_entries` + `record_plugin_write` so the two sides cannot drift about where the
sidecar lives. The inline form reached it through
`os.path.dirname(os.path.abspath(__file__))` - the third shape the guide forbids
carrying literally, meaning "the hooks directory" only while the case sat in one.
From `tests/` it names `tests/journal-writes.py`, which does not exist. It is now
`_loader.load(os.path.join(_harness.HOOKS_DIR, "journal-writes.py"), cache=False)`:
the same fresh module object, found where the subject actually lives.

The `getattr(_jw, "record_plugin_write", ...)` inside that group is NOT the
introspection hazard - it names the loaded SUBJECT module, not `sys.modules[__name__]`,
and its swallowing default is deliberate (it is what let the red run fail the case
rather than crash the suite). The rest of the AST scan came back empty: no `globals()`,
no `vars()`, no other `__file__`, no `split(a)[1].split(b)[0]`.

NO IMPORT EDGE MOVED WITH IT, measured per CALL SITE. Three loader names left this
hook's AST - `_config._load_journal_lib`, `_config._load_lock_lib` and the
`importlib` load above - and none of them was a graph edge: the first two are calls
ON `_config`, whose own loads stay where they are and are still reached in production
through `_config.manifest_lock_conflict()`, and `_deps` does not model `hooks/` as
graph nodes at all (only the static hooks->scripts import ban).

THE DOMAIN WRAPPER STAYS HERE, RENAMED. `check(name, expected, data, ...)` ran
`decide()` for the caller and printed `(expected X, got Y)` on every line; it is now
`_expect`, and that text is a harness DETAIL rendered only on failure. Eleven further
cases hand-rolled `results.append(ok)` + `print("%s <label>")` pairs; they call
`check` now. Every label is byte-identical, including `k1`'s interpolated
`(got silent for ...)` tail.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _config                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "guard-bash-writes.py"),
                 modname="guard_bash_writes")


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = Path(tempfile.mkdtemp(prefix="bash-writes-selftest-"))
    sd = tmp / "state"
    sd.mkdir(parents=True, exist_ok=True)
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    # Pin repo_root regardless of the caller's session env (it checks
    # CLAUDE_PROJECT_DIR before stdin cwd).
    prev_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    def payload(tool, *, sid, file_path=None, command="x"):
        ti = {"command": command} if tool == "Bash" else {"file_path": file_path}
        return {"tool_name": tool, "tool_input": ti, "session_id": sid,
                "cwd": str(tmp)}

    def _expect(name, expected, data, dirty=None, use_cfg=None):
        """One case: run `decide` on `data` and compare its verdict to `expected`.

        Guarded through `_harness.attempt` rather than the hand-rolled
        `except Exception as exc: verdict = "EXC:%s"` the inline form carried, and
        the expected/got text that used to print on EVERY line is now a detail,
        rendered only when the case fails."""
        ok, got = _harness.attempt(M.decide, data, cfg=use_cfg or cfg,
                                   state_dir=sd, dirty=dirty)
        verdict = got[0] if ok else got
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    def seed(sid, *, use_cfg=None, state_dir=None, cwd=None, dirty=()):
        """Run the session's baseline pass (A2) with a known dirty set, so each
        case below tests ATTRIBUTION of new dirt, not the baseline itself
        (which the (m) group pins)."""
        data = payload("Bash", sid=sid)
        if cwd is not None:
            data["cwd"] = str(cwd)
        M.decide(data, cfg=use_cfg or cfg,
                 state_dir=state_dir if state_dir is not None else sd,
                 dirty=list(dirty))

    # (a) a bash-only new source file → warn once, then stays silent
    s = "bw-a"
    seed(s)
    _expect("a1 new dirty source file warns", "warn",
          payload("Bash", sid=s), dirty=["src/shell.ts"])
    _expect("a2 same file again is silent", "silent",
          payload("Bash", sid=s), dirty=["src/shell.ts"])

    # (b) tool-edited files never warn (they went through the gates)
    s = "bw-b"
    seed(s)
    _expect("b1 Edit records", "record",
          payload("Edit", sid=s, file_path="src/tool.ts"))
    _expect("b2 dirty tool-edited file is silent", "silent",
          payload("Bash", sid=s), dirty=["src/tool.ts"])

    # (c) exempt / non-source / manifest / lock → silent
    s = "bw-c"
    for _sid in (s, "bw-c2", "bw-c3", "bw-c4"):
        seed(_sid)
    _expect("c1 exempt .md silent", "silent",
          payload("Bash", sid=s), dirty=["NOTES.md"])
    _expect("c2 non-source ext silent", "silent",
          payload("Bash", sid="bw-c2"), dirty=["out.log"])
    _expect("c3 test file silent (exempt glob)", "silent",
          payload("Bash", sid="bw-c3"), dirty=["src/a.spec.ts"])
    _expect("c4 manifest + lock silent", "silent",
          payload("Bash", sid="bw-c4"),
          dirty=["docs/audit/audit-plan.json",
                 "docs/audit/audit-plan.json.lock"])

    # (d) in_progress-covered file → silent
    manifest_dir = tmp / "docs" / "audit"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "audit-plan.json").write_text(json.dumps({
        "meta": {"version": 2},
        "phases": [{"id": "P0", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P0.1", "title": "t", "status": "in_progress",
             "files": ["src/covered/mod.ts"], "tests": {"mode": "gate-only"}},
        ]}],
    }), encoding="utf-8")
    seed("bw-d")
    _expect("d1 in_progress-covered file silent", "silent",
          payload("Bash", sid="bw-d"), dirty=["src/covered/mod.ts"])

    # (e) two new files → one warn naming both; disabled config → silent
    s = "bw-e"
    seed(s)
    _e_ok, _e_got = _harness.attempt(M.decide, payload("Bash", sid=s), cfg=cfg,
                                     state_dir=sd,
                                     dirty=["src/one.py", "src/two.py"])
    verdict, detail = _e_got if _e_ok else ("EXC", str(_e_got))
    check("e1 one warning names every new file",
          verdict == "warn" and "src/one.py" in detail and "src/two.py" in detail,
          repr((verdict, detail)))
    cfg_off = _config._deep_merge(_config.DEFAULTS,
                                  {"bashWriteCheck": {"enabled": False}})
    _expect("e2 disabled config silent", "silent",
          payload("Bash", sid="bw-e2"), dirty=["src/x.ts"], use_cfg=cfg_off)

    # (m) A2 (v0.36): pre-existing dirt is the session's BASELINE, not the first
    # command's crime. On the first Bash pass of a session the guard cannot know
    # which dirty paths predate the command, so it seeds seenDirty silently and
    # only attributes dirt that appears AFTER that (live find: a real repo's
    # standing dirty files were all blamed on the session's first command).
    s = "bw-m1"
    _expect("m1 first pass: a pre-existing dirty source file is baseline, silent",
          "silent", payload("Bash", sid=s), dirty=["src/preexisting.ts"])
    _expect("m2 a NEW dirty file on a later pass is attributed and warned", "warn",
          payload("Bash", sid=s), dirty=["src/preexisting.ts", "src/fresh.ts"])
    s = "bw-m4"
    _expect("m4a an Edit-first session records through the edit branch", "record",
          payload("Edit", sid=s, file_path="src/tool-first.ts"))
    _expect("m4b ...and its first BASH pass still seeds the baseline silently - "
          "the flag lives in state, not in the state file's existence",
          "silent", payload("Bash", sid=s), dirty=["src/left-by-others.ts"])
    _expect("m4c ...while dirt after the baseline is still caught", "warn",
          payload("Bash", sid=s),
          dirty=["src/left-by-others.ts", "src/mine.ts"])

    # (j) the append-only journal. guard-edits REFUSES an edit tool here; a shell
    # write is the same act through the door that cannot be locked, so the only
    # honest thing left is to say it happened.
    for _sid in ("bw-j1", "bw-j4", "bw-j5"):
        seed(_sid)
    _j_ok, _j_got = _harness.attempt(
        M.decide, payload("Bash", sid="bw-j1"), cfg=cfg, state_dir=sd,
        dirty=["docs/audit/journal/2026-08.a.jsonl"])
    verdict, detail = _j_got if _j_ok else ("EXC", str(_j_got))
    check("j1 a shell write into the journal warns, and names the command that "
          "checks the chain",
          verdict == "warn" and "append-only audit journal" in detail
          and "audit-journal.py verify" in detail, repr((verdict, detail)))
    # The journal lives under docs/audit/, which is EXEMPT from the plan gate on
    # purpose — so a check that ran after the exempt globs would see nothing at all.
    check("j2 (and it really is inside an exempt path, which is what makes the "
          "order load-bearing)",
          _config.matches_exempt("docs/audit/journal/2026-08.a.jsonl",
                                 _config.DEFAULTS["exemptGlobs"]))
    _expect("j3 the same file again is silent - one warning per file per session",
          "silent", payload("Bash", sid="bw-j1"),
          dirty=["docs/audit/journal/2026-08.a.jsonl"])
    # Two classes at once are two facts, and reporting one would leave the other
    # to be found later by someone with no idea what caused it.
    _j4_ok, _j4_got = _harness.attempt(
        M.decide, payload("Bash", sid="bw-j4"), cfg=cfg, state_dir=sd,
        dirty=["docs/audit/journal/2026-08.a.jsonl", "src/two-at-once.py"])
    verdict, detail = _j4_got if _j4_ok else ("EXC", str(_j4_got))
    check("j4 a journal write and an unplanned source write are both reported",
          verdict == "warn" and "audit journal" in detail
          and "src/two-at-once.py" in detail, repr((verdict, detail)))
    _expect("j5 a neighbour whose name merely starts the same is ordinary work",
          "silent", payload("Bash", sid="bw-j5"),
          dirty=["docs/audit/journal-notes/why.md"])

    # (k) F-F3: the plugin's OWN journal append lands in git status too, and it
    # used to be blamed on the next shell command -- journal-writes appends a
    # row at PostToolUse, the journal file goes dirty, and the next Bash pass
    # reported "That shell command wrote into the append-only audit journal"
    # about a write the plugin itself made. The fix is a sidecar with ONE
    # writer (journal-writes), read here; k1 drives the REAL writer so the two
    # sides cannot drift about where the sidecar lives.
    # `os.path.dirname(os.path.abspath(__file__))` meant "the hooks directory"
    # while this case sat inside a hook; from `tests/` it names `tests/`, and the
    # load would die on a file that is not there. Spelled off `_harness.HOOKS_DIR`
    # so it keeps driving the REAL writer - which is the whole point of k1: the
    # two sides must not be able to drift about where the sidecar lives.
    # `cache=False` keeps the fresh module object the importlib form built.
    _jw = _loader.load(os.path.join(_harness.HOOKS_DIR, "journal-writes.py"),
                       modname="journal_writes_for_k", cache=False)
    kproj = tmp / "ff3"
    (kproj / "docs" / "audit").mkdir(parents=True, exist_ok=True)
    (kproj / "docs" / "audit" / "audit-plan.json").write_text(
        '{"meta":{"version":3}}', encoding="utf-8")
    ksd = kproj / ".claude" / "state"
    kcfg = _config._deep_merge(_config.DEFAULTS, {})
    ksid = "bw-k1"
    kdata = {"tool_name": "Edit", "session_id": ksid,
             "tool_input": {"file_path": "docs/audit/audit-plan.json",
                            "new_string": "x"},
             "cwd": str(kproj)}
    os.environ["CLAUDE_PROJECT_DIR"] = str(kproj)
    try:
        for _sid in (ksid, "bw-k2"):
            seed(_sid, use_cfg=kcfg, state_dir=ksd, cwd=kproj)
        _jmod = _config._load_journal_lib()
        _entries = _jw.post_entries(kdata, cfg=kcfg, root=str(kproj))
        _written = []
        for _e in _entries:
            _p = _jmod.append(str(kproj), _e, config=kcfg)
            if _p:
                # exactly the wiring journal-writes' main() performs after a
                # successful append; getattr so the RED run (before the
                # sidecar exists) fails the case instead of crashing the suite
                getattr(_jw, "record_plugin_write",
                        lambda *a: None)(str(kproj), kcfg, kdata, _p)
                _written.append(_p)
        _jrel = (_config.rel_path(kproj, _written[0]) if _written
                 else "append-failed")
        _kpayload = {"tool_name": "Bash", "tool_input": {"command": "x"},
                     "session_id": ksid, "cwd": str(kproj)}
        _k_ok, _k_got = _harness.attempt(M.decide, _kpayload, cfg=kcfg,
                                         state_dir=ksd, dirty=[_jrel])
        _v = _k_got[0] if _k_ok else _k_got
        check("k1 the plugin's own journal append is SILENT on the next "
              "Bash pass - the sidecar names it, so the shell is not blamed "
              "for it (got %s for %s)" % (_v, _jrel),
              bool(_written) and _v == "silent")
        # A journal write the sidecar does NOT name is still the guard's
        # business: that is the sed-shaped write the template exists for.
        _v2, _d2 = M.decide({"tool_name": "Bash",
                             "tool_input": {"command": "x"},
                             "session_id": "bw-k2", "cwd": str(kproj)},
                            cfg=kcfg, state_dir=ksd, dirty=[_jrel])
        check("k2 a session WITHOUT a sidecar entry still warns about the "
              "same journal file - the guard's purpose survives the fix",
              _v2 == "warn" and "append-only audit journal" in _d2,
              repr((_v2, _d2)))
        check("k3 the journal warning tells the reader how to read a clean "
              "verify: a fresh chained row was likely the plugin itself",
              "likely the plugin itself" in M.JOURNAL_TEMPLATE)
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    # (f) REAL git integration: init a repo, dirty it, no `dirty` injection
    s = "bw-f"
    _detail_f = ""
    gitrepo = tmp / "repo"
    (gitrepo / "src").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(gitrepo)
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(gitrepo), check=True,
                       capture_output=True, timeout=10)
        # baseline pass BEFORE the shell write exists (real git, no injection)
        M.decide({"tool_name": "Bash", "tool_input": {"command": "x"},
                  "session_id": s, "cwd": str(gitrepo)}, cfg=cfg, state_dir=sd)
        (gitrepo / "src" / "made-by-shell.go").write_text("package x\n",
                                                          encoding="utf-8")
        data = {"tool_name": "Bash", "tool_input": {"command": "x"},
                "session_id": s, "cwd": str(gitrepo)}
        verdict, detail = M.decide(data, cfg=cfg, state_dir=sd)
        ok = verdict == "warn" and "src/made-by-shell.go" in detail
    except Exception as exc:  # pragma: no cover
        ok = False
        _detail_f = "git integration error: %s" % exc
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    check("f1 real git status detects the shell write", ok, _detail_f)

    # (fl) A shell write to a manifest path held by another LIVE session. Through
    # Edit this is denied by require-plan; through `sed -i` it lands, and the only
    # honest thing left is to say who it landed on top of. Previously invisible
    # twice over: manifest_rel was skipped outright, and .json is not a source ext.
    import platform as _pf
    _detail_l = ""
    lockrepo = tmp / "lockrepo"
    (lockrepo / "audit" / "phases").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(lockrepo)
    cfg_lock = _config._deep_merge(_config.DEFAULTS,
                                   {"manifestPath": "audit/plan.json"})
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(lockrepo), check=True,
                       capture_output=True, timeout=10)
        lockdir = _config._load_lock_lib().lock_dir(str(lockrepo))
        os.makedirs(lockdir, exist_ok=True)
        with open(os.path.join(lockdir, "phase-P1.lock"), "w",
                  encoding="utf-8") as fh:
            json.dump({"hostname": _pf.node(), "pid": os.getpid(),
                       "sessionId": "sess-A", "note": "phase P1",
                       "startedAt": _config.utc_stamp()}, fh)
        # baseline passes BEFORE the shard write exists (real git, no injection)
        for _sid in ("sess-B", "sess-B2"):
            M.decide({"tool_name": "Bash", "tool_input": {"command": "x"},
                      "session_id": _sid, "cwd": str(lockrepo)},
                     cfg=cfg_lock, state_dir=sd)
        (lockrepo / "audit" / "phases" / "P1.json").write_text(
            '{"id":"P1"}\n', encoding="utf-8")
        data = {"tool_name": "Bash", "tool_input": {"command": "sed -i ..."},
                "session_id": "sess-B", "cwd": str(lockrepo)}
        verdict, detail = M.decide(data, cfg=cfg_lock, state_dir=sd)
        ok_l = (verdict == "warn" and "audit/phases/P1.json" in detail
                and "sess-A" in detail and "ANOTHER LIVE SESSION" in detail)
        # And the same write by the HOLDER is not a warning.
        with open(os.path.join(lockdir, "phase-P1.lock"), "r+",
                  encoding="utf-8") as fh:
            info = json.load(fh)
            info["sessionId"] = "sess-B"
            fh.seek(0), fh.truncate()
            json.dump(info, fh)
        data2 = {"tool_name": "Bash", "tool_input": {"command": "sed -i ..."},
                 "session_id": "sess-B2", "cwd": str(lockrepo)}
        v2, _ = M.decide(data2, cfg=cfg_lock, state_dir=sd)
        ok_own = v2 == "warn"          # sess-B2 is not the holder either
        data3 = {"tool_name": "Bash", "tool_input": {"command": "sed -i ..."},
                 "session_id": "sess-B", "cwd": str(lockrepo)}
        v3, _ = M.decide(data3, cfg=cfg_lock, state_dir=sd)
        ok_own = ok_own and v3 == "silent"
    except Exception as exc:  # pragma: no cover
        ok_l = ok_own = False
        _detail_l = "lock integration error: %s" % exc
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    check("fl1 a shell write onto another live session's shard is surfaced",
          ok_l, _detail_l)
    check("fl2 and the lock's own holder is not warned about its own write",
          ok_own, _detail_l)

    # (g) non-git directory → silent
    _expect("g1 non-git dir silent", "silent",
          payload("Bash", sid="bw-g"))

    # (h) NESTED gitRoot: project dir is NOT git, git repo is in a subdir.
    # With gitRoot config the guard runs git there and reports project-relative.
    _detail_h = ""
    proj = tmp / "proj"
    sub = proj / "sub"
    (sub / "src").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(proj)
    cfg_nested = _config._deep_merge(_config.DEFAULTS, {"gitRoot": "sub"})
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(sub), check=True,
                       capture_output=True, timeout=10)
        # baseline pass BEFORE the shell write exists (real git, no injection)
        M.decide({"tool_name": "Bash", "tool_input": {"command": "x"},
                  "session_id": "bw-h", "cwd": str(proj)},
                 cfg=cfg_nested, state_dir=sd)
        (sub / "src" / "shellmade.ts").write_text("export const x=1\n",
                                                  encoding="utf-8")
        data = {"tool_name": "Bash", "tool_input": {"command": "x"},
                "session_id": "bw-h", "cwd": str(proj)}
        verdict, detail = M.decide(data, cfg=cfg_nested, state_dir=sd)
        # project-relative path is gitRoot-prefixed: sub/src/shellmade.ts
        ok = verdict == "warn" and "sub/src/shellmade.ts" in detail
    except Exception as exc:  # pragma: no cover
        ok = False
        _detail_h = "nested git integration error: %s" % exc
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    check("h1 nested gitRoot: git runs in subdir, path project-relative",
          ok, _detail_h)

    if prev_env is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = prev_env

    # (i) session state lands in a self-ignoring dir
    import shutil as _sh
    tmp_i = Path(tempfile.mkdtemp(prefix="gbw-ignore-"))
    try:
        M._save_state(tmp_i / "state", "s-i",
                      {"toolEdited": [], "seenDirty": [], "warned": []})
        check("i1 _save_state's dir carries a `*` .gitignore",
              (tmp_i / "state" / ".gitignore").exists())
    finally:
        _sh.rmtree(tmp_i, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_bash_writes.py --selftest\n")
    raise SystemExit(2)
