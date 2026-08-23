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
# --- the tagged fixture tables ------------------------------------------------
# HOISTED SO THE TAGS ARE ADDRESSABLE DATA. Each tag names its fixture's
# construct so a mutation row can point at one case; an index would renumber
# every fixture below an inserted one and the row would still resolve, to a
# different construct. The tags therefore have to be distinct, and `tag1` below
# is what says so - the harness cannot: all fixtures in one loop share a single
# `check()` CALL SITE, which is exactly the shape `label_faults` is right to stay
# silent about, so a duplicated tag here would otherwise be caught only by
# `prove-gates.py` refusing a row that happened to name it.
DNP_CASES = (("stderr", "cat a.py 2>/dev/null", True),
             ("stdout", "ls -la 1>/dev/null", True),
             ("piped", "grep -rn x . 2>/dev/null | head -5", True),
             ("bare", "cat a.py >/dev/null", True),
             # separates "is /dev/null" from "starts with /dev/null"
             ("baksuffix", "cat a.py >/dev/null.bak", False),
             # a real destination must survive the /dev/null strip
             ("realdest", "grep x a.py > hits.txt 2>/dev/null", False),
             ("append", "echo x >> notes.md", False))

EXP_CASES = (("execcat", "find . -name x -exec cat {} +", True),
             ("execgrep", "find . -type f -exec grep -l foo {} \\;", True),
             ("execrm", "find . -type f -exec rm {} \\;", False),
             ("execsh", "find . -type f -exec sh -c 'cat x' \\;", False),
             ("execdir", "find . -type f -execdir chmod +x {} +", False),
             ("okrm", "find . -type f -ok rm {} \\;", False),
             # a clause with no command proves nothing
             ("execbare", "find . -name x -exec", False),
             ("delete", "find . -name x -delete", False))

RWP_CASES = (("gitstatus", "git status --porcelain", True),
             ("greppipe", "grep -rn x plugins | head -5", True),
             ("catpipe", "cat a.py | wc -l", True),
             ("gitadd", "git add .", False),
             ("redirect", "echo hi > f.txt", False),
             ("tee", "cat a | tee b", False),
             ("finddelete", "find . -name x -delete", False),
             ("npminstall", "npm install", False),
             ("empty", "", False))


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

    def plant_plan(project_dir):
        """A manifest that exists with nothing running — the middle rung.

        F52 graded the plan-coverage class on `plan_gate_mode`, so a fixture with
        no manifest is now on the observe rung and reports nothing. The (f) and
        (h) fixtures below are about REAL git integration and nested-gitRoot path
        handling, and neither can be proven by a silence that the grading would
        produce whatever git did. They opt in, so their subject is still theirs.
        """
        d = Path(project_dir) / "docs" / "audit"
        d.mkdir(parents=True, exist_ok=True)
        (d / "audit-plan.json").write_text(json.dumps({
            "meta": {"version": 2},
            "phases": [{"id": "P0", "title": "p", "status": "done", "tasks": [
                {"id": "P0.1", "title": "t", "status": "done"}]}],
        }), encoding="utf-8")

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
    #
    # The plan is planted first because F52 graded the plan-coverage class: with
    # no manifest this fixture is on the observe rung and every case here would
    # pass through silence, testing nothing. The (gr) group owns that rung.
    plant_plan(tmp)
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
    plant_plan(gitrepo)
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
    ok_h2 = False
    proj = tmp / "proj"
    sub = proj / "sub"
    (sub / "src").mkdir(parents=True, exist_ok=True)
    plant_plan(proj)
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
        # F84 asks git which tree a command ran in, from the command's own cwd,
        # and `gitRoot` is what that REFINES rather than replaces. h1 covers the
        # cwd git cannot answer for at all (the project dir is not a repo, so the
        # declaration stands); this covers the cwd it CAN answer for - a
        # subdirectory of the declared git root - where the answer must come back
        # as the watched tree and the monorepo write must still be reported.
        M.decide({"tool_name": "Bash", "tool_input": {"command": "x"},
                  "session_id": "bw-h2", "cwd": str(sub / "src")},
                 cfg=cfg_nested, state_dir=sd)
        (sub / "src" / "deeper.ts").write_text("export const d=1\n",
                                               encoding="utf-8")
        _vh2, _dh2 = M.decide({"tool_name": "Bash",
                               "tool_input": {"command": "x"},
                               "session_id": "bw-h2",
                               "cwd": str(sub / "src")},
                              cfg=cfg_nested, state_dir=sd)
        ok_h2 = _vh2 == "warn" and "sub/src/deeper.ts" in _dh2
    except Exception as exc:  # pragma: no cover
        ok = ok_h2 = False
        _detail_h = "nested git integration error: %s" % exc
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    check("h1 nested gitRoot: git runs in subdir, path project-relative",
          ok, _detail_h)
    check("h2 ...and a command run INSIDE that git root is recognised as the "
          "watched tree, so the monorepo write is still reported - gitRoot is "
          "refined by git's answer, never replaced by it", ok_h2, _detail_h)

    # (wt) F84: WHICH TREE DID THE COMMAND RUN IN. `_config.repo_root` answers
    # where the CONFIG lives, and CLAUDE_PROJECT_DIR wins there on purpose - a
    # worktree should not need its own copy of the project's config. It stays
    # pinned to the primary checkout while an agent works inside a git worktree,
    # so `git status` ran in one tree while the command ran in another and that
    # tree's dirt was handed to this command. Reported live: a read-only sweep in
    # an agent worktree was told it had modified source files a parallel session
    # was editing in the primary checkout - clean in the worktree, dirty in the
    # primary tree.
    #
    # TWO REAL TREES, not an injected `dirty` list and not a stubbed
    # `command_tree`. The whole question is what git says about a linked worktree,
    # and a fake here would encode the assumption under test instead of checking
    # it. Paths are compared by BASENAME and by phrase, never byte for byte:
    # `--show-toplevel` answers with forward slashes on Windows while `str(Path)`
    # does not, and CI runs both platforms.
    _detail_wt = ""
    _wt_ok = _wt_named = _wt_own = _wt_once = _wt_ro = _wt_sep = False
    wta = tmp / "wt-primary"
    (wta / "src").mkdir(parents=True, exist_ok=True)
    plant_plan(wta)
    wtb = tmp / "wt-linked"
    wtsep = tmp / "wt-separate"
    wtsd = wta / ".claude" / "state"
    os.environ["CLAUDE_PROJECT_DIR"] = str(wta)
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(wta), check=True,
                       capture_output=True, timeout=20)
        subprocess.run(["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "base"],
                       cwd=str(wta), check=True, capture_output=True, timeout=20)
        subprocess.run(["git", "worktree", "add", "-q", str(wtb), "-b",
                        "wt-phase"], cwd=str(wta), check=True,
                       capture_output=True, timeout=30)
        wtsep.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=str(wtsep), check=True,
                       capture_output=True, timeout=20)

        def _wt(sid, cwd, command="python3 tools/gen.py"):
            return M.decide({"tool_name": "Bash",
                             "tool_input": {"command": command},
                             "session_id": sid, "cwd": str(cwd)},
                            cfg=cfg, state_dir=wtsd)

        # baseline from the watched tree, while it is still clean of source
        _wt("bw-wt", wta)
        # a parallel session dirties the WATCHED tree, and the linked worktree
        # stays clean - which is the shape that was verified in the report
        (wta / "src" / "theirs.ts").write_text("export const x=1\n",
                                               encoding="utf-8")
        _v, _d = _wt("bw-wt", wtb)
        # Counted, not merely absent: the pre-fix notice names the path exactly
        # once, so zero occurrences is the discriminating measurement.
        _wt_ok = (_v == "warn" and _d.count("src/theirs.ts") == 0
                  and "cannot say what the command wrote" in _d)
        _wt_named = (os.path.basename(str(wtb)) in _d
                     and "linked worktree of the same repository" in _d)
        _v1b, _d1b = _wt("bw-wt", wtb)
        # The REASON, not just the verdict: a repeat pass is silent on the
        # pre-fix hook too (the path had already been warned about), so
        # `== "silent"` alone passed with the fix removed.
        _wt_once = _v1b == "silent" and "already said" in _d1b
        # THE OTHER DIRECTION, and it is the one that looks vacuous: a fix that
        # decided EVERY command ran elsewhere would pass the three above and
        # retire the guard. The same dirt, seen from the watched tree, is still
        # reported by name.
        _wt("bw-wt2", wta)
        (wta / "src" / "mine.ts").write_text("export const y=1\n",
                                             encoding="utf-8")
        _v2, _d2 = _wt("bw-wt2", wta)
        _wt_own = _v2 == "warn" and "src/mine.ts" in _d2
        # A read-only command from another tree costs neither a notice nor the
        # `git rev-parse` behind one: the proof about the OPERATION answers first,
        # which is what keeps an ordinary sweep in a worktree quiet.
        _wt("bw-wt3", wta)
        (wta / "src" / "third.ts").write_text("export const z=1\n",
                                              encoding="utf-8")
        _v3, _d3 = _wt("bw-wt3", wtb, command="grep -rn theirs src")
        _wt_ro = _v3 == "silent" and "read-only command" in _d3
        # ...and a checkout that is not a worktree of this repository is named as
        # what it is. Without this the phrase could be hard-coded and nobody
        # would know which branch produced it.
        _wt("bw-wt4", wta)
        _v4, _d4 = _wt("bw-wt4", wtsep)
        _wt_sep = _v4 == "warn" and "separate git repository" in _d4
    except Exception as exc:  # pragma: no cover
        _detail_wt = "worktree integration error: %s" % exc
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    check("wt1 THE REPORTED BUG: a command run in a linked worktree is not "
          "handed the watched tree's dirt - the notice names no path, because "
          "the guard never looked at the tree the command ran in",
          _wt_ok, _detail_wt)
    check("wt2 ...and it names BOTH trees plus how it knows, so the reader can "
          "act on it", _wt_named, _detail_wt)
    check("wt3 the plain claim survives for the tree the guard DOES watch - the "
          "second-direction case for wt1, which a fix that always cried "
          "'another tree' would fail", _wt_own, _detail_wt)
    check("wt4 the other-tree notice is said once per tree, not on every shell "
          "call from it", _wt_once, _detail_wt)
    check("wt5 a read-only command from another tree is absorbed by the "
          "operation proof before the tree question is ever asked",
          _wt_ro, _detail_wt)
    check("wt6 an unrelated checkout is called a separate repository, not a "
          "worktree - the branch `--git-common-dir` decides",
          _wt_sep, _detail_wt)

    # (dn) `2>/dev/null` is the most ordinary read idiom there is, and the
    # blanket "any `>` is hostile" check read it as a write - which put
    # `cat x 2>/dev/null` back on the watched side and handed it the blame for a
    # second session's file. THIS IS THE CASE THE REPORT ASKED FOR: seed the
    # baseline, then let a file appear while `cat` runs, and expect nothing said.
    # It is spelled WITH the redirect on purpose - plain `cat` was already
    # covered by (rw), so a case without it would have been green from the start.
    s = "bw-dn"
    seed(s)
    _expect("dn1 `cat ... 2>/dev/null` is a read, so a file that appeared while "
            "it ran is not attributed to it", "silent",
            payload("Bash", sid=s, command="cat tools/where.py 2>/dev/null"),
            dirty=["src/second-session.ts"])
    # THE OTHER DIRECTION. Without it, deleting the `>` check entirely would pass
    # dn1: the exemption is for /dev/null, not for redirection.
    s = "bw-dn2"
    seed(s)
    _expect("dn2 ...while a redirect to a real FILE is still watched", "warn",
            payload("Bash", sid=s,
                    command="cat tools/where.py > src/second-session.ts"),
            dirty=["src/second-session.ts"])
    # A TAG PER FIXTURE, NAMING THE CONSTRUCT, not the loop index: an index
    # renumbers every fixture below an inserted one and a mutation row then still
    # resolves - to a different construct than it was written for. The family
    # carries a digit because `_harness.case_id()` is what makes an id
    # addressable at all, and a token with no digit is indistinguishable from an
    # English word.
    for _tag, _cmd, _want in DNP_CASES:
        check("dnp1-%s %r is %s" % (_tag, _cmd, "provably read-only" if _want
                                    else "watched"),
              M._command_is_read_only(_cmd) == _want)

    # (ex) `-exec` was a blanket write flag, so `find ... -exec cat {} +` - a
    # read - was unprovable and inherited the whole dirty set. What decides is
    # the command the clause runs.
    s = "bw-ex"
    seed(s)
    _expect("ex1 `find ... -exec cat {} +` is judged by the command it runs, "
            "which reads", "silent",
            payload("Bash", sid=s,
                    command="find plugins -name '*.py' -exec cat {} +"),
            dirty=["src/second-session.ts"])
    # THE OTHER DIRECTION: the same shape running a writer stays watched, so this
    # is not "-exec is fine now".
    s = "bw-ex2"
    seed(s)
    _expect("ex2 ...and the same shape running a WRITER is still watched",
            "warn",
            payload("Bash", sid=s,
                    command="find plugins -name '*.py' -exec cp {} /tmp +"),
            dirty=["src/second-session.ts"])
    for _tag, _cmd, _want in EXP_CASES:
        check("exp1-%s %r is %s" % (_tag, _cmd, "provably read-only" if _want
                                    else "watched"),
              M._command_is_read_only(_cmd) == _want)

    # (os) THE STRUCTURAL HALF. A command that is not provably read-only used to
    # inherit EVERY path that appeared since the last snapshot, and this product
    # advertises parallel phases - several sessions writing in one checkout. The
    # evidence was already on disk and unread: every session keeps its own
    # bash-writes-<sid>.json naming what it edited through the gated tools. An
    # ISOLATED state dir, because which sibling state files exist IS the fixture.
    osd = tmp / "state-os"
    osd.mkdir(parents=True, exist_ok=True)

    def _other(sid, *, tool_edited=(), warned=(), older_than=None):
        """Write a sibling session's state file, optionally back-dated behind
        `older_than` so it falls outside the window this pass covers."""
        p = osd / ("bash-writes-%s.json" % sid)
        with open(str(p), "w", encoding="utf-8") as fh:
            json.dump({"toolEdited": list(tool_edited), "seenDirty": [],
                       "warned": list(warned), "baselined": True}, fh)
        if older_than is not None:
            t = os.path.getmtime(str(older_than)) - 60
            os.utime(str(p), (t, t))
        return p

    s = "bw-os"
    seed(s, state_dir=osd)
    _other("sess-other", tool_edited=["src/theirs.ts"])
    _os_ok, _os_got = _harness.attempt(
        M.decide, payload("Bash", sid=s, command="python3 tools/gen.py"),
        cfg=cfg, state_dir=osd, dirty=["src/theirs.ts"])
    _osv, _osdet = _os_got if _os_ok else ("EXC", str(_os_got))
    check("os1 a file another session edited in this window is attributed to "
          "THAT session, not to this command, and the detail names it",
          _osv == "silent" and "sess-other" in _osdet, repr((_osv, _osdet)))

    s = "bw-os2"
    seed(s, state_dir=osd)
    _other("sess-other2", tool_edited=["src/unrelated.ts"])
    _ok2, _got2 = _harness.attempt(
        M.decide, payload("Bash", sid=s, command="python3 tools/gen.py"),
        cfg=cfg, state_dir=osd, dirty=["src/nobody-claims.ts"])
    _v2, _d2 = _got2 if _ok2 else ("EXC", str(_got2))
    check("os2 ...while a file NOBODY claims is still reported, with the "
          "authorship claim dropped - which is what the evidence supports",
          _v2 == "warn" and "src/nobody-claims.ts" in _d2
          and "CANNOT say the command wrote them" in _d2
          and "sess-other2" in _d2,
          repr((_v2, _d2)))

    s = "bw-os3"
    seed(s, state_dir=osd)
    _other("sess-stale", tool_edited=["src/stale-claim.ts"],
           older_than=osd / ("bash-writes-%s.json" % s))
    _ok3, _got3 = _harness.attempt(
        M.decide, payload("Bash", sid=s, command="python3 tools/gen.py"),
        cfg=cfg, state_dir=osd, dirty=["src/stale-claim.ts"])
    _v3, _d3 = _got3 if _ok3 else ("EXC", str(_got3))
    check("os3 a claim by a session that did nothing in this window does NOT "
          "exonerate - the evidence is bound to the window the dirt appeared in",
          _v3 == "warn" and "src/stale-claim.ts" in _d3, repr((_v3, _d3)))
    # THE OTHER DIRECTION for the hedge itself: with nobody else in the window
    # the guard still makes the plain authorship claim. A hedge that fired
    # unconditionally would pass os2 and fail here.
    check("os4 ...and with no other session in the window the plain claim is "
          "still made - the hedge is evidence-driven, not unconditional",
          "That shell command modified source file" in _d3, repr(_d3))
    # seenDirty is not authorship: every session records every dirty path it
    # SEES, so reading it as a claim would let two sessions exonerate each other
    # for a file neither wrote.
    s = "bw-os5"
    seed(s, state_dir=osd)
    _other("sess-seer", tool_edited=[])
    with open(str(osd / "bash-writes-sess-seer.json"), "r+",
              encoding="utf-8") as fh:
        _seer = json.load(fh)
        _seer["seenDirty"] = ["src/seen-only.ts"]
        fh.seek(0), fh.truncate()
        json.dump(_seer, fh)
    _ok5, _got5 = _harness.attempt(
        M.decide, payload("Bash", sid=s, command="python3 tools/gen.py"),
        cfg=cfg, state_dir=osd, dirty=["src/seen-only.ts"])
    _v5, _d5 = _got5 if _ok5 else ("EXC", str(_got5))
    check("os5 another session merely HAVING SEEN the path is not a claim to "
          "have written it", _v5 == "warn" and "src/seen-only.ts" in _d5,
          repr((_v5, _d5)))

    if prev_env is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = prev_env

    # (sr) WHICH ROOT THE STATE DIRECTORY IS RESOLVED FROM, which is the coupling
    # F84 sits on. `stateDir` is the CONFIG question: `_config.state_dir` is
    # `root / cfg["stateDir"]`, the value comes out of the project's config file,
    # and the plugin tells consumers to gitignore it at the project root. Two
    # features depend on every session in that directory resolving the SAME root:
    #
    #   * `_other_sessions` (the (os) group, 9b45c54) subtracts a peer's claim
    #     from THIS tree's dirt. Narrow the directory per tree and a same-checkout
    #     peer becomes invisible, so a write another session made comes back as
    #     this command's - and every worktree case still passes.
    #   * the F-F3 sidecar (the (k) group) has ONE writer, `journal-writes`, which
    #     resolves the directory the same way. Move one and not the other and the
    #     guard reads an empty sidecar, which is indistinguishable from "the plugin
    #     appended nothing" - F-F3 reopened in the quiet direction.
    #
    # NOTHING HERE INJECTS `state_dir`. Every other group in this file passes it,
    # so the resolution itself has never been under test; and in a fixture whose
    # git root IS the project dir the two candidate directories coincide and any
    # mutation is invisible. So the fixture is a monorepo: `gitRoot: "sub"` puts
    # `<proj>/.claude/state` and `<proj>/sub/.claude/state` in different places,
    # which is the one shape where resolving from the tree instead of the project
    # can be seen at all.
    _detail_sr = ""
    _sr_peer = _sr_plain = _sr_one_dir = False
    srp = tmp / "sr-proj"
    srsub = srp / "sub"
    (srsub / "src").mkdir(parents=True, exist_ok=True)
    plant_plan(srp)
    cfg_sr = _config._deep_merge(_config.DEFAULTS, {"gitRoot": "sub"})
    _sr_real = srp / ".claude" / "state"
    _sr_narrowed = srsub / ".claude" / "state"
    os.environ["CLAUDE_PROJECT_DIR"] = str(srp)
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(srsub), check=True,
                       capture_output=True, timeout=20)

        def _sr(sid):
            return M.decide({"tool_name": "Bash",
                             "tool_input": {"command": "python3 tools/gen.py"},
                             "session_id": sid, "cwd": str(srp)}, cfg=cfg_sr)

        _sr("sr-a")
        (srsub / "src" / "theirs.ts").write_text("export const x=1\n",
                                                 encoding="utf-8")
        _peer = _sr_real / "bash-writes-sr-peer.json"
        _config.ensure_local_dir(_sr_real)
        with open(str(_peer), "w", encoding="utf-8") as fh:
            json.dump({"toolEdited": ["sub/src/theirs.ts"], "seenDirty": [],
                       "warned": [], "baselined": True}, fh)
        # Forward, not backward: the peer must have acted INSIDE the window this
        # pass covers, and a tie counts as outside on a coarse-mtime filesystem.
        _mine = _sr_real / "bash-writes-sr-a.json"
        _t = os.path.getmtime(str(_mine)) + 60
        os.utime(str(_peer), (_t, _t))
        _v, _d = _sr("sr-a")
        _sr_peer = _v == "silent" and "sr-peer" in _d
        # The second direction, and the one that would quietly disappear: with the
        # peer file exactly where it is, a path NOBODY claims is still reported.
        # Without it, a change that read every sibling as a claim on everything
        # would pass the case above.
        _sr("sr-b")
        (srsub / "src" / "nobody.ts").write_text("export const y=1\n",
                                                 encoding="utf-8")
        _v2, _d2 = _sr("sr-b")
        _sr_plain = _v2 == "warn" and "sub/src/nobody.ts" in _d2
        # F-F3's one directory, driven through the REAL writer the way (k) does -
        # `_jw` is the module loaded there - and then read with the guard's OWN
        # reader out of the directory the guard actually wrote its state into.
        # Asserted as a non-empty set naming the appended row, because "the
        # plugin's write was not blamed" is vacuously true of an empty sidecar.
        _srsid = "sr-ff3"
        _srdata = {"tool_name": "Edit", "session_id": _srsid,
                   "tool_input": {"file_path": "docs/audit/audit-plan.json",
                                  "new_string": "x"}, "cwd": str(srp)}
        _srjrel = None
        for _e in _jw.post_entries(_srdata, cfg=cfg_sr, root=str(srp)):
            _p = _config._load_journal_lib().append(str(srp), _e, config=cfg_sr)
            if _p:
                _jw.record_plugin_write(str(srp), cfg_sr, _srdata, _p)
                _srjrel = _config.rel_path(srp, _p)
        _sr(_srsid)
        _slots = [d / ("bash-writes-%s.json" % _srsid)
                  for d in (_sr_real, _sr_narrowed)]
        _landed = [s for s in _slots if s.exists()]
        _pw = M._plugin_wrote(_landed[0].parent, _srsid) if _landed else set()
        _sr_one_dir = (len(_landed) == 1 and _landed[0].parent == _sr_real
                       and _srjrel is not None and _srjrel in _pw)
    except Exception as exc:  # pragma: no cover
        _detail_sr = "state-root integration error: %s" % exc
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    check("sr1 a same-checkout peer's claim is found through the REAL state "
          "directory - resolved from the project dir, not from the git tree",
          _sr_peer, _detail_sr)
    check("sr2 ...while a path no peer claims is still reported from that same "
          "directory - the second-direction case for sr1",
          _sr_plain, _detail_sr)
    check("sr3 the guard's own state file and journal-writes' F-F3 sidecar land "
          "in ONE directory, and the guard's reader finds a NON-EMPTY set there "
          "naming the row the plugin appended", _sr_one_dir, _detail_sr)

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

    # (rw) F-P-24: a command that cannot write is not the author of new dirt.
    #
    # Reported twice in one session, both times for a pure `git ls-files` + `grep`
    # over a file a SECOND session had just created. The guard was diffing the tree
    # against its own last snapshot, so "new" meant "new to me", not "written by
    # this call" - and with two agents in one checkout that is a guaranteed false
    # accusation rather than an edge case.
    s = "bw-rw"
    seed(s)
    _expect("rw1 a read-only command is not blamed for a file that appeared "
            "beside it (the reported bug: git ls-files + grep)", "silent",
            payload("Bash", sid=s,
                    command="git ls-files --others | grep -n foo"),
            dirty=["src/other-session.ts"])
    # THE HALF THAT MATTERS. Without it, deleting the whole guard would pass rw1.
    s = "bw-rw2"
    seed(s)
    _expect("rw2 ...while the SAME new file still warns when the command could "
            "have written it - the fix removes an excuse, not the guard", "warn",
            payload("Bash", sid=s, command="python3 tools/gen.py"),
            dirty=["src/other-session.ts"])
    # And the sed spelling from the second report, which reads by default and
    # writes only with -i.
    s = "bw-rw3"
    seed(s)
    _expect("rw3 `sed -n` reads and is not blamed", "silent",
            payload("Bash", sid=s, command="sed -n '1,20p' tools/where.py"),
            dirty=["src/other-session.ts"])
    s = "bw-rw4"
    seed(s)
    _expect("rw4 ...but `sed -i` writes, so it is", "warn",
            payload("Bash", sid=s, command="sed -i 's/a/b/' src/other-session.ts"),
            dirty=["src/other-session.ts"])

    # (rwp) the predicate itself, so a spelling cannot quietly join either side.
    for _tag, _cmd, _want in RWP_CASES:
        check("rwp1-%s %r is %s" % (_tag, _cmd or "(empty)",
                                    "provably read-only" if _want else "watched"),
              M._command_is_read_only(_cmd) == _want)

    # (rwq) F51/F56: the predicate decided on RAW TEXT, so a shell metacharacter
    # sitting inside a quoted SEARCH PATTERN was read as shell syntax. Grepping
    # for `>` or `&&` or `${` is not a redirect, a background job or an expansion,
    # and this is a repo whose most ordinary command greps its own source.
    #
    # Several spellings, one cause, and the two directions fail at different
    # lines: the hostile scan runs over the whole string before anything is
    # split, and the splitter is a regex that cuts inside quotes. `xargs` is
    # simply absent from the allowlist with a reader on either side of it, and fd
    # duplication (`2>&1`) names no file at all - the old `/dev/null` regex could
    # not see it, so its `&` reached the hostile scan and every stderr-merging
    # read was watched.
    #
    # THE LAST PAIRS ARE THE OTHER DIRECTION, and they are why this group cannot
    # be judged by the read side alone: `sed` takes its suffix ATTACHED, so an
    # exact-token flag match sees `-i.bak` as an ordinary argument and calls a
    # real in-place write a read. On a BSD `sed` that is the only spelling that
    # works, so the form that goes unseen is the form anyone here would type.
    for _tag, _cmd, _want in (
            ("gtinpat", 'grep -n "cost > 5" f.py', True),
            ("andinpat", 'grep -n "a && b" f.py', True),
            ("expinpat", 'grep -n "${VAR}" f.py', True),
            ("subinpat", 'grep -n "$(date)" f.py', True),
            ("heredocinpat", 'grep -rn "<<EOF" f.py', True),
            ("altinpat", 'grep -n "READ_ONLY\\|read_only" f.py | head', True),
            ("xargswc", 'find . -name "*.py" | xargs wc -l', True),
            ("fdmerge", 'grep x f.py 2>&1', True),
            ("devnullmerge", 'ls >/dev/null 2>&1', True),
            ("fdtostderr", 'grep x f.py >&2', True),
            ("xargsgrep", 'ls | xargs -0 grep -l x', True),
            ("sedattached", 'sed -i.bak s/a/b/ f.py', False),
            ("sedlongform", 'sed --in-place=.bak s/a/b/ f.py', False),
            ("realredirect", 'echo hi > f.py', False),
            ("devnullprefix", 'cat a > /dev/null.bak', False),
            ("execsedi", 'find . -exec sed -i s/a/b/ {} +', False),
            ("unbalanced", 'grep -n "unbalanced f.py', False),
            # Putting `xargs` on the allowlist to fix the read side opened three
            # writes on the other: its command was never judged. Recursion, the
            # way `-exec` is judged — and these cases are the only reason the
            # regression was seen at all, which is F55 in one group.
            ("xargsrm", 'find . -name "*.tmp" | xargs rm', False),
            ("xargsrmf", 'find . | xargs -n1 rm -f', False),
            ("xargsmv", 'ls | xargs -I{} mv {} /tmp', False),
            ("xargsbare", 'xargs', False)):
        check("rwq1-%s %r is %s" % (_tag, _cmd,
                               "provably read-only" if _want else "watched"),
              M._command_is_read_only(_cmd) == _want)

    # (gr) F52: the plan-coverage class is GRADED, like the plan gate beside it.
    #
    # `require-plan.py` resolves evidence into a tier through
    # `_config.plan_gate_mode` so that installing the plugin does not start acting
    # in projects that never opted in — the README says so as a promise. This hook
    # never called it. It asked `in_progress_files`, which returns an empty set
    # both for "no manifest" and for "a manifest with nothing running", so a repo
    # with no plan read as a repo where nothing is covered and every shell write
    # in it was reported. With F51 live that meant a stranger's first `grep`.
    _gr = tmp / "noplan"
    (_gr / "src").mkdir(parents=True, exist_ok=True)

    def _gr_decide(sid, dirty, use_cfg=None):
        data = {"tool_name": "Bash", "tool_input": {"command": "x"},
                "session_id": sid, "cwd": str(_gr)}
        M.decide(dict(data), cfg=use_cfg or cfg, state_dir=sd, dirty=[])
        return M.decide(data, cfg=use_cfg or cfg, state_dir=sd, dirty=list(dirty))

    _prev_gr = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(_gr)
    try:
        _v, _d = _gr_decide("bw-gr1", ["src/stranger.ts"])
        check("gr1 no manifest: the plan-coverage class says nothing, because "
              "there is no plan for it to be uncovered by", _v == "silent",
              repr((_v, _d)))
        # THE HALF THAT MATTERS. Without it, deleting the class would pass gr1.
        _v, _d = _gr_decide("bw-gr2", ["docs/audit/journal/2026-08.a.jsonl"])
        check("gr2 ...while the journal class in the SAME plan-less repo still "
              "reports - only plan coverage is graded, because only it needs a "
              "plan to mean anything",
              _v == "warn" and "audit journal" in _d, repr((_v, _d)))
        cfg_enforced = _config._deep_merge(_config.DEFAULTS, {"enforce": True})
        _v, _d = _gr_decide("bw-gr3", ["src/stranger.ts"], use_cfg=cfg_enforced)
        check("gr3 `enforce: true` reports with no manifest at all - the escape "
              "hatch someone chose, rather than a default that surprises them",
              _v == "warn" and "src/stranger.ts" in _d, repr((_v, _d)))
        plant_plan(_gr)
        _v, _d = _gr_decide("bw-gr4", ["src/stranger.ts"])
        check("gr4 ...and the same file in the same repo warns once it HAS a "
              "plan - the grading removes a claim, not the guard",
              _v == "warn" and "src/stranger.ts" in _d, repr((_v, _d)))
    finally:
        if _prev_gr is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = _prev_gr
    # THE GUARD FOR THE TAGS THEMSELVES, and it has to live here. Every fixture
    # in one of those tables goes through a single `check()` call site, so
    # `_harness.label_faults()` is right to say nothing about a repeated id
    # there - that is the legitimate family shape. A duplicated TAG would
    # therefore be invisible until `prove-gates.py` refused a row that happened
    # to name it, which is late and only if somebody wrote such a row.
    _tag_tables = (("dnp1", DNP_CASES), ("exp1", EXP_CASES), ("rwp1", RWP_CASES))
    _tag_ids = ["%s-%s" % (_fam, _row[0]) for _fam, _rows in _tag_tables
                for _row in _rows]
    _tag_dupes = sorted(set(_i for _i in _tag_ids if _tag_ids.count(_i) > 1))
    _tag_unaddressable = [_i for _i in _tag_ids if _harness.case_id(_i + " x") is None]
    check("tag1 every tagged fixture prints a distinct, addressable case id - the "
          "point of a tag over an index, and a property no shared rule can check "
          "for a one-call-site family: %r / %r"
          % (_tag_dupes, _tag_unaddressable),
          _tag_dupes == [] and _tag_unaddressable == []
          and all(_rows for _fam, _rows in _tag_tables))
    # (gt) the git call itself, pinned as data rather than spied on.
    #
    # `-uall` is LOAD-BEARING and measured: on a fixture of 4000 untracked,
    # unignored files it costs ~86 ms against ~19 ms for `-unormal`, and it is the
    # only spelling that names a new source file inside a NEW directory. `-unormal`
    # collapses that to `?? src/`, which `_is_source` does not recognise as source,
    # so the warning would simply vanish - speed bought with silence, which is the
    # one trade this repo does not make. The case says so, because the next person
    # to profile this hook will reach for the same flag.
    #
    # `--no-optional-locks` is NOT a speed change (measured: no difference). It
    # stops `git status` taking the index lock, which matters precisely because
    # this plugin's headline feature is phases running in parallel worktrees. It
    # must sit BEFORE the subcommand: after it, git exits with `unknown option`.
    _argv = list(M.GIT_STATUS_ARGV)
    check("gt1 `-uall` is still there - the flag that names a new source file "
          "inside a new directory",
          "-uall" in _argv and "-unormal" not in _argv and "-uno" not in _argv)
    check("gt2 `--no-optional-locks` precedes the subcommand, which is the only "
          "placement git accepts",
          "--no-optional-locks" in _argv
          and _argv.index("--no-optional-locks") < _argv.index("status"))

    # (to) a timeout is not "no git here".
    #
    # `_git_dirty` caught every failure into one `return None`, and `decide` read
    # that as "not a git repo / git unusable" and went SILENT. A repo big enough to
    # blow the 5 s budget therefore ran with the guard permanently off and was never
    # told - the exact shape `no-silent-pass` calls a filter narrowing to nothing and
    # reading as all clear. The two outcomes need distinct sentinels.
    _real_git_dirty = M._git_dirty
    try:
        M._git_dirty = lambda root: (None, "timeout")
        s = "bw-to"
        _ok_to, _got_to = _harness.attempt(
            M.decide, payload("Bash", sid=s, command="python3 tools/gen.py"),
            cfg=cfg, state_dir=sd)
        # Asserted on substance, not wording: it must say the guard is off, and it
        # must name a way out. A notice that reports a failure without either is
        # the thing this repo calls a claim with no basis.
        check("to1 a git-status timeout is reported, not swallowed as 'no repo', "
              "and the notice says the guard is off and how to restore it",
              _ok_to and _got_to[0] == "warn"
              and "NOT being detected" in _got_to[1]
              and ".gitignore" in _got_to[1]
              and "bashWriteCheck.enabled" in _got_to[1],
              repr(_got_to))
        # The other direction: a real "not a git repo" must STAY silent. Without
        # this, making every git failure warn would pass to1 and flood any
        # non-git project with a notice it can do nothing about.
        M._git_dirty = lambda root: (None, "no-repo")
        _ok_ng, _got_ng = _harness.attempt(
            M.decide, payload("Bash", sid="bw-to2", command="python3 tools/gen.py"),
            cfg=cfg, state_dir=sd)
        check("to2 ...while a genuine non-git directory stays silent - the "
              "second-direction case for to1",
              _ok_ng and _got_ng[0] == "silent", repr(_got_ng))
        # And the timeout notice fires ONCE: a hook that repeats it on every shell
        # call in a big repo is a hook people turn off.
        M._git_dirty = lambda root: (None, "timeout")
        _ok_2, _got_2 = _harness.attempt(
            M.decide, payload("Bash", sid=s, command="python3 tools/gen2.py"),
            cfg=cfg, state_dir=sd)
        check("to3 ...and it is said once per session, not on every shell call",
              _ok_2 and _got_2[0] == "silent", repr(_got_2))
    finally:
        M._git_dirty = _real_git_dirty

    # The import weight of this hook - the Edit lane returns at "record" without
    # ever reaching git, so `subprocess` must not be imported at module scope - is
    # NOT asserted here. It has ONE home, and it is the per-hook budget in
    # `tools/bench-hooks.py --gate`, which asks the same question of every hook
    # instead of this one: run that after touching the imports at the top of
    # guard-bash-writes.py.


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_bash_writes.py --selftest\n")
    raise SystemExit(2)
