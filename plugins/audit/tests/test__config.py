#!/usr/bin/env python3
"""
The cases for `hooks/_config.py`, moved out of it - the config every other hook
imports, and the largest suite in the tree.

`_config.py` is importable by name, so `M` is a plain `import _config as M` rather
than a `_loader` load. Everything the suite touches is one of `_config`'s own
module-level names, which is why the transformation here was done by TOKEN and not
by regex: three case LABELS carry those names as prose (`e0 usage_cfg() does not
alias DEFAULTS`, `e2 tdd_reminder() ...`, and every `... does not alias DEFAULTS`),
and a text substitution would have rewritten the labels - which is a changed test.

TWO EXPRESSIONS HAD TO CHANGE MEANING TO MOVE, AND ONE FIXTURE HAD TO CHANGE NAME.

* `k10`'s subprocess probe passed `Path(__file__).resolve().parent` to a fresh
  interpreter as "the directory `_config.py` lives in". From `tests/` that is
  `tests/`, and the child's `import _config` would fail - the case would go red for
  the wrong reason. It is `Path(M.__file__).resolve().parent` now: the subject's own
  location, which is the hooks directory wherever this file is run from.
* the `g`/`h` groups' manifest-path fixture was literally called `M`. Assigning `M`
  anywhere inside `_cases` would make the name local for the entire function body,
  so every `M.<name>` before it raises UnboundLocalError. It is `MAN` here.
* `t5` keeps its `inspect.getsource(M.utc_stamp)` slice UNCHANGED - it splits the
  source on the triple-quote delimiter and takes the LAST part - and that is a
  decision rather than an oversight. `getsource` resolves by OBJECT, so the move
  costs it nothing. The split is not the forbidden `split(a)[1].split(b)[0]` shape:
  `[-1]` cannot raise, and it cannot silently WIDEN the region in the direction that
  matters. `utc_stamp`'s docstring uses the double form, and that delimiter cannot
  appear inside a string it delimits, so today the slice is exactly the body. Were
  the docstring ever re-delimited with the single form around an embedded double one,
  the slice would grow to include the tail of the DOCSTRING - and t5's two halves are
  "the body mentions time.gmtime()" and "the body never mentions localtime". A wider
  slice leaves the first half untouched (the body is always included) and can only
  make the second HARDER, because that docstring discusses `time.localtime()` at
  length. The fragility runs towards a false FAILURE, never towards a vacuous pass,
  which is the only direction that would justify rewriting a case that has been
  correct for its whole life.

THE ONE REBIND IS NOT THE `globals()` HAZARD: the `k` group swaps `os.replace` for a
spy, an attribute on the `os` module that `atomic_write_text` looks up at call time,
restored in a `finally`. No `globals()`, no `vars()`, no path built off the suite's
own directory.

THE CONSUMER-REPO FIXTURES NOW LIVE HERE, AND `_refs` IS SILENT ABOUT THEM BY DESIGN.
`g1` asserts that a consumer project's Python test filenames are exempt, and two of
those literals name a `tests/` directory that is somebody else's, not this plugin's.
`plugins/audit/tests` is an ANCHORED surface in `_refs.SURFACES` written for exactly
this arrival - a plugin path counts as a reference only with the `plugins/audit/`
anchor - and `_refs`' own `a6` is the case that goes red if that ever changes.

`_config.py` is the only file in the tree with no `safe_stdio()` in `__main__`: hooks
stay importless of `scripts/` on purpose, and `_output.entries_missing_guard()`
deliberately does not scan `hooks/`. It DOES scan `tests/`, so this file carries the
guard the way every other test file does. That is the boundary working, not an
inconsistency to tidy.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import time
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _config as M                                # noqa: E402  (the module under test)


# --- cases --------------------------------------------------------------------
def _cases(check):
    import platform
    import subprocess
    import tempfile

    # --- fs: the third copy of "where is scripts/", held true by READING -------
    # `hooks/` may import nothing from `scripts/` (`_deps` r5/r6, and there is no
    # allow-list any more), so `find_script()` cannot read `_output.SCRIPTS_DIR`
    # and walks from its own `__file__` instead. That is an irreducible third
    # derivation, the same shape as the pricing table above: it cannot be merged,
    # so it is pinned by comparing the two answers rather than by a comment in each
    # file claiming they agree.
    #
    # THIS IS THE MOST DANGEROUS FUNCTION IN THE FILE TO GET WRONG.
    # `_load_scripts_module` wraps its load in `except Exception: return None`, and
    # every caller reads None as "the feature is not installed". A wrong path there
    # does not raise - it silently switches off the capability policy, the journal,
    # the ledger and the sharded-manifest read, with every gate still green. So it
    # is tested directly, not through the features that depend on it.
    #
    # `M` is `hooks/_config.py` imported by name (see the module docstring), which
    # IS "loaded by path" in the only sense that matters here: `_harness` puts
    # `hooks/` on `sys.path` and the module resolves off its own `__file__`, the
    # same value a hook process gives it.
    import _output as _out

    _fs_names = sorted(os.path.basename(_r) for _r, _p in _out.script_files())
    _fs_found = dict((_n, M.find_script(_n)) for _n in _fs_names)
    _fs_missing = sorted(_n for _n in _fs_names if _fs_found[_n] is None)
    check("fs1 the hooks-side resolver finds EVERY basename `_output.script_files()`"
          " knows about - %d of them, and the list is the check: a resolver that "
          "narrowed to nothing would report no disagreement at all: %r"
          % (len(_fs_names), _fs_missing),
          _fs_names and not _fs_missing)
    _fs_wrong = sorted(_n for _n in _fs_names
                       if _fs_found[_n] is not None
                       and os.path.realpath(_fs_found[_n])
                       != os.path.realpath(dict((os.path.basename(_r), _p)
                                                for _r, _p in _out.script_files())[_n]))
    check("fs2 ...and resolves each one to the SAME FILE the scripts-side walk "
          "does, compared by realpath because the hooks side reaches it through "
          "`..`: %r" % (_fs_wrong,), not _fs_wrong)
    check("fs3 a basename that is not there returns None rather than a plausible "
          "path - `_load_scripts_module` turns any answer into a module or into "
          "None, so a confident wrong path is the one failure it cannot report",
          M.find_script("no-such-script-xyz.py") is None)
    # The recursion. `ui/` holds the report's CSS and script parts one directory
    # was written, so fs4 asked about the WALK through a non-`.py`; fs4b now asks the
    # question that was actually meant, because the four files this hook reaches have
    # since been filed under domains and a `.py` at depth is no longer hypothetical.
    # Both are kept: fs4 fails if the walk stops descending at all, fs4b if it
    # descends but the resolved path is wrong, and those are different defects.
    _fs_deep = M.find_script("shell.css")
    check("fs4 the walk is RECURSIVE - it reaches scripts/ui/report-css/shell.css, "
          "the property a `.py` filed one directory down depends on. Without it "
          "that file comes back None and reads as 'not installed': %r" % (_fs_deep,),
          _fs_deep is not None and os.path.isfile(_fs_deep)
          and os.path.basename(os.path.dirname(_fs_deep)) == "report-css")
    # THE FOUR THIS FILE ACTUALLY LOADS, and each one is now at depth. A flat
    # resolver returns None for all four, `_load_scripts_module` turns that into
    # None, and the capability policy, the journal, the ledger and the lock switch
    # themselves off with every gate still green. The expected DIRECTORY is spelled
    # out rather than derived: reading it back off the same walk would let a
    # resolver that has gone wrong agree with itself.
    _fs_domains = {"_policy.py": "governance", "audit-journal.py": "governance",
                   "audit-lock.py": "governance", "usage_ledger.py": "usage"}
    _fs_landed = dict((_n, M.find_script(_n)) for _n in sorted(_fs_domains))
    _fs_bad = sorted(_n for _n, _d in _fs_domains.items()
                     if _fs_landed[_n] is None
                     or not os.path.isfile(_fs_landed[_n])
                     or os.path.basename(os.path.dirname(_fs_landed[_n])) != _d)
    check("fs4b ...and every module `_load_scripts_module` loads is found IN ITS "
          "DOMAIN - _policy/audit-journal/audit-lock under governance/, "
          "usage_ledger under usage/. All four are at depth, so this is the case "
          "that goes red if the resolver is ever flattened again: %r" % (_fs_bad,),
          len(_fs_domains) == 4 and not _fs_bad)
    # The load is lazy now (k11), so this asks the accessor rather than reading a
    # module global - but it is the same claim, and it is the one that matters: a
    # resolver that quietly returns None is indistinguishable from `policy` never
    # having shipped, and every caller downstream reads that as "allow".
    check("fs5 `_load_scripts_module` really goes through it: the policy module "
          "resolves through the accessor, which is the fail-open that would "
          "otherwise be indistinguishable from `policy` never having shipped",
          M.policy_mod() is not None)

    tmp = Path(tempfile.mkdtemp(prefix="config-selftest-"))

    # (a) absent config → pure defaults, no error marker
    cfg = M.load(tmp)
    check("a1 absent config -> defaults, no _configError",
          cfg.get("trivialLineThreshold") == 80 and "_configError" not in cfg,
          repr(cfg.get("_configError")))

    # (b) valid override merges one level deep, keeps un-overridden siblings
    cdir = tmp / ".claude"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "audit.config.json").write_text(
        json.dumps({"trivialLineThreshold": 40,
                    "guardEdits": {"tokenVars": ["jwt"]}}),
        encoding="utf-8")
    cfg = M.load(tmp)
    check("b1 override merges",
          cfg["trivialLineThreshold"] == 40
          and cfg["guardEdits"]["tokenVars"] == ["jwt"]
          and cfg["guardEdits"]["customRules"] == []
          and "_configError" not in cfg)

    # (b2) the usage block merges per-key, and a partial `pricing` override keeps
    # the shipped rows for every model it doesn't mention
    (cdir / "audit.config.json").write_text(
        json.dumps({"usage": {"showCost": False,
                              "pricing": {"claude-opus-5": {"in": 9.0, "out": 9.0}}}}),
        encoding="utf-8")
    cfg = M.load(tmp)
    u = M.usage_cfg(cfg)
    check("b2 usage merges without dropping siblings",
          u["showCost"] is False and u["enabled"] is True
          and u["pricing"]["claude-opus-5"]["in"] == 9.0
          and u["pricing"]["claude-haiku-4-5"]["in"] == 1.0)
    check("b3 ledger_dir is repo-relative and outside stateDir",
          str(M.ledger_dir(tmp, cfg)).endswith(".claude/usage".replace("/", os.sep)))
    check("b4 usage_enabled defaults true", M.usage_enabled({}) is True)
    check("b5 usage_enabled honours an explicit false",
          M.usage_enabled({"usage": {"enabled": False}}) is False)

    # (c) malformed JSON → defaults + _configError (NOT silent)
    (cdir / "audit.config.json").write_text("{not json", encoding="utf-8")
    cfg = M.load(tmp)
    check("c1 malformed -> defaults + _configError",
          cfg["trivialLineThreshold"] == 80 and bool(cfg.get("_configError")))

    # (d) non-object root → defaults + _configError
    (cdir / "audit.config.json").write_text('["array"]', encoding="utf-8")
    cfg = M.load(tmp)
    check("d1 non-object root -> _configError", bool(cfg.get("_configError")))

    # (e) no aliasing: mutating a loaded cfg never corrupts DEFAULTS
    (cdir / "audit.config.json").unlink()
    cfg = M.load(tmp)
    cfg["exemptGlobs"].append("MUTATED")
    cfg["guardEdits"]["tokenVars"].append("MUTATED")
    cfg["tddReminder"]["sourceGlobs"].append("MUTATED")
    cfg["usage"]["pricing"]["_default"]["in"] = 999.0
    check("e0 usage_cfg() does not alias DEFAULTS",
          M.DEFAULTS["usage"]["pricing"]["_default"]["in"] == 5.0
          and M.usage_cfg({})["pricing"]["_default"]["in"] == 5.0)
    check("e1 loaded cfg does not alias DEFAULTS",
          "MUTATED" not in M.DEFAULTS["exemptGlobs"]
          and "MUTATED" not in M.DEFAULTS["guardEdits"]["tokenVars"]
          and "MUTATED" not in M.DEFAULTS["tddReminder"]["sourceGlobs"])
    tr = M.tdd_reminder({})
    tr["testGlobs"].append("MUTATED")
    check("e2 tdd_reminder() does not alias DEFAULTS",
          "MUTATED" not in M.DEFAULTS["tddReminder"]["testGlobs"])

    # (f) manifest_state + plan_gate_mode — the evidence the plan gate grades on.
    import shutil
    import tempfile
    tmp_f = Path(tempfile.mkdtemp(prefix="config-selftest-state-"))
    try:
        rel = "docs/audit/audit-plan.json"

        def write_manifest(obj, sharded=False):
            d = tmp_f / "docs" / "audit"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            if not sharded:
                (d / "audit-plan.json").write_text(json.dumps(obj), encoding="utf-8")
                return
            # index carries stubs with NO status; the shard bodies hold the truth
            idx = {"meta": {"version": 3}, "phases": []}
            (d / "phases").mkdir(exist_ok=True)
            for ph in obj["phases"]:
                idx["phases"].append({"id": ph["id"], "title": ph.get("title", ""),
                                      "shard": "phases/%s.json" % ph["id"]})
                (d / "phases" / ("%s.json" % ph["id"])).write_text(
                    json.dumps(ph), encoding="utf-8")
            (d / "audit-plan.json").write_text(json.dumps(idx), encoding="utf-8")

        st = M.manifest_state(tmp_f, rel)
        check("f1 no manifest -> exists False, phaseRunning False, no phase "
              "to name",
              st == {"exists": False, "phaseRunning": False,
                     "runningPhase": None}, repr(st))
        check("f2 no manifest -> observe", M.plan_gate_mode({}, st) == "observe")

        write_manifest({"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "p", "status": "done", "tasks": [
                {"id": "P1.1", "title": "t", "status": "done"}]}]})
        st = M.manifest_state(tmp_f, rel)
        check("f3 manifest with nothing running -> exists, not running, no "
              "phase to name",
              st == {"exists": True, "phaseRunning": False,
                     "runningPhase": None}, repr(st))
        check("f4 manifest, nothing running -> warn", M.plan_gate_mode({}, st) == "warn")

        write_manifest({"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
                {"id": "P1.1", "title": "t", "status": "pending"}]}]})
        st = M.manifest_state(tmp_f, rel)
        check("f5 in_progress phase -> phaseRunning", st["phaseRunning"] is True)
        check("f5b ...and the state NAMES the phase, so a denial can say which "
              "plan is holding the pen (F-F4)", st["runningPhase"] == "P1",
              repr(st))
        check("f6 manifest + running phase -> deny", M.plan_gate_mode({}, st) == "deny")

        # A task running under a phase that is not still counts as executing a plan.
        write_manifest({"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "p", "status": "pending", "tasks": [
                {"id": "P1.1", "title": "t", "status": "in_progress"}]}]})
        check("f7 in_progress TASK under a pending phase counts as running",
              M.manifest_state(tmp_f, rel)["phaseRunning"] is True)
        check("f7b ...and the task's OWNER phase is the one named",
              M.manifest_state(tmp_f, rel)["runningPhase"] == "P1")

        # The sharded trap: the index stub has no status, so a raw read sees None.
        write_manifest({"phases": [
            {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
                {"id": "P1.1", "title": "t", "status": "in_progress"}]}]}, sharded=True)
        idx_raw = json.loads((tmp_f / "docs" / "audit" / "audit-plan.json")
                             .read_text(encoding="utf-8"))
        check("f8 the sharded index really does hide status (guards the next case)",
              idx_raw["phases"][0].get("status") is None)
        check("f9 sharded layout: a running phase is still detected "
              "(assembled read, not the index)",
              M.manifest_state(tmp_f, rel)["phaseRunning"] is True)

        # enforce overrides every tier, including the one with no evidence at all.
        shutil.rmtree(tmp_f / "docs")
        st = M.manifest_state(tmp_f, rel)
        check("f10 enforce:true denies even with no manifest",
              M.plan_gate_mode({"enforce": True}, st) == "deny")
        check("f11 enforce:false is the graded default",
              M.plan_gate_mode({"enforce": False}, st) == "observe")
        check("f12 a non-bool enforce is ignored rather than trusted",
              M.plan_gate_mode({"enforce": "yes"}, st) == "observe")
        check("f13 enforce defaults to false", M.DEFAULTS["enforce"] is False)

        # --- the test-file exemption knows more than one language ------------
        # Found by running the pipeline end to end in a sandbox Python project:
        # the exemption exists so red-first TDD stays frictionless, and it only
        # recognised the JavaScript spelling — so the first act of a red-first
        # fix, writing the failing test, was DENIED for Python and Go.
        _eg = M.DEFAULTS["exemptGlobs"]
        for _rel, _why in (("tests/test_cart.py", "python, unittest/pytest default"),
                           ("tests/cart_test.py", "python suffix form"),
                           ("pkg/cart_test.go", "go - required by the toolchain"),
                           ("spec/cart_spec.rb", "ruby rspec"),
                           ("test/cart_test.exs", "elixir"),
                           ("src/cart.test.js", "js"),
                           ("src/cart.spec.ts", "ts")):
            check("x1 %s is exempt (%s)" % (_rel, _why), M.matches_exempt(_rel, _eg))
        # The exemption is for TEST FILES, not for anything with "test" in the name.
        # A wider glob here would quietly hand every file a bypass.
        for _rel in ("src/cart.py", "src/testimonials.py", "src/contest.py",
                     "src/protest_handler.go", "src/latest.py"):
            check("x2 %s is NOT exempt - 'test' inside a word is not a test file"
                  % _rel, not M.matches_exempt(_rel, _eg))

        # Never raises, and degrades to the least aggressive verdict.
        check("f14 manifest_state on garbage input still returns the safe shape",
              M.manifest_state(None, None) == {"exists": False,
                                             "phaseRunning": False,
                                             "runningPhase": None})
        check("f15 plan_gate_mode on garbage input degrades to observe",
              M.plan_gate_mode(None, None) == "observe")

        # --- planGate: pin a tier by hand (v0.34 B1) --------------------------
        # `planGate` set = that tier, whatever the evidence; absent = the graded
        # ladder above, unchanged. It beats the legacy `enforce` when both are
        # set, and a typo fails OPEN to the ladder rather than to deny.
        _none = {"exists": False, "phaseRunning": False}
        _running = {"exists": True, "phaseRunning": True}
        check("f16 planGate: 'deny' pins deny with no evidence at all",
              M.plan_gate_mode({"planGate": "deny"}, _none) == "deny")
        check("f17 planGate: 'observe' pins observe even while a phase runs - "
              "the one setting that LOWERS the gate below its evidence",
              M.plan_gate_mode({"planGate": "observe"}, _running) == "observe")
        check("f18 planGate: 'ask' is a tier of its own",
              M.plan_gate_mode({"planGate": "ask"}, _none) == "ask"
              and M.plan_gate_mode({"planGate": "ask"}, _running) == "ask")
        check("f19 planGate: 'warn' pins warn",
              M.plan_gate_mode({"planGate": "warn"}, _running) == "warn")
        check("f20 planGate beats enforce, in both directions",
              M.plan_gate_mode({"planGate": "observe", "enforce": True},
                             _running) == "observe"
              and M.plan_gate_mode({"planGate": "deny", "enforce": False},
                                 _none) == "deny")
        check("f21 a typo'd or non-string planGate fails OPEN to the ladder",
              M.plan_gate_mode({"planGate": "denny"}, _none) == "observe"
              and M.plan_gate_mode({"planGate": 1}, _running) == "deny"
              and M.plan_gate_knob({"planGate": "denny"}) is None
              and M.plan_gate_knob(None) is None)
        check("f22 absent means graded - the default is None, not a mode",
              M.DEFAULTS.get("planGate", "MISSING") is None
              and M.plan_gate_knob({}) is None
              and M.plan_gate_knob({"planGate": "warn"}) == "warn")
    finally:
        shutil.rmtree(tmp_f, ignore_errors=True)

    # (j) the journal — where it lives, and what counts as being inside it.
    # Resolved by delegating to scripts/audit-journal.py rather than re-deriving:
    # the module that owns the format owns its location, and the guards below refuse
    # hand edits to whatever it answers.
    tmp_j = Path(tempfile.mkdtemp(prefix="config-journal-"))
    try:
        cfg_j = M._deep_merge(M.DEFAULTS, {})
        check("j1 journal.enabled defaults true", M.journal_enabled({}) is True
              and M.DEFAULTS["journal"]["enabled"] is True)
        check("j2 an explicit false is honoured",
              M.journal_enabled({"journal": {"enabled": False}}) is False)
        check("j3 a non-bool is ignored rather than trusted (the `enforce` rule)",
              M.journal_enabled({"journal": {"enabled": "no"}}) is True)
        jd = M.journal_dir(tmp_j, cfg_j)
        check("j4 the journal sits beside the manifest by default",
              jd is not None and str(jd) == str(
                  tmp_j / "docs" / "audit" / "journal"), repr(jd))
        check("j5 journal.dir moves it",
              str(M.journal_dir(tmp_j, M._deep_merge(
                  M.DEFAULTS, {"journal": {"dir": "trail"}}))) == str(tmp_j / "trail"))
        check("j6 a moved manifest takes the journal with it",
              str(M.journal_dir(tmp_j, M._deep_merge(
                  M.DEFAULTS, {"manifestPath": "plan/audit.json"})))
              == str(tmp_j / "plan" / "journal"))
        check("j7 a path inside the journal is recognised, absolute or relative",
              M.in_journal(tmp_j, cfg_j, "docs/audit/journal/2026-08.a.jsonl")
              and M.in_journal(tmp_j, cfg_j,
                             str(tmp_j / "docs" / "audit" / "journal" / "x.jsonl")))
        check("j8 the manifest beside it is NOT inside it",
              not M.in_journal(tmp_j, cfg_j, "docs/audit/audit-plan.json")
              and not M.in_journal(tmp_j, cfg_j, "src/app.py"))
        check("j9 a sibling directory whose name merely starts the same is outside",
              not M.in_journal(tmp_j, cfg_j, "docs/audit/journal-notes/x.md"))
        # The guards ask THIS question, not `journal_dir`, so it has to read the
        # project's own setting rather than the default: a repo that moved its
        # journal would otherwise have the old location protected and the real one
        # wide open.
        _moved = M._deep_merge(M.DEFAULTS, {"journal": {"dir": "trail"}})
        check("j10 a moved journal is protected where it actually is",
              M.in_journal(tmp_j, _moved, "trail/2026-08.a.jsonl")
              and not M.in_journal(tmp_j, _moved,
                                 "docs/audit/journal/2026-08.a.jsonl"))
        check("j11 garbage in, False out", not M.in_journal(tmp_j, cfg_j, "")
              and not M.in_journal(None, None, None))
        # The delegation itself: this must be the journal module's answer, not a
        # second copy of the rule that can drift from it.
        _jmod = M._load_journal_lib()
        check("j12 the answer comes from audit-journal.py itself",
              _jmod is not None
              and str(jd) == _jmod.journal_dir(str(tmp_j), cfg_j))
    finally:
        shutil.rmtree(tmp_j, ignore_errors=True)

    # (k) the gate events feed (v0.34 B3): the gate's verdicts used to leave no
    # trace at all — only the bypass had a log. One compact line per verdict,
    # into logsDir (stateDir is GC territory; the journal is tamper-evidence,
    # and telemetry does not belong in a hash chain), self-trimming, never
    # raising.
    tmp_k = Path(tempfile.mkdtemp(prefix="config-gate-events-"))
    try:
        kld = tmp_k / "logs"
        M.append_gate_event(kld, {"event": "deny", "file": "src/a.ts",
                                "mode": "deny", "reason": "second file",
                                "sessionId": "sess-k"})
        kpath = kld / M.GATE_EVENTS_FILE
        try:
            klines = kpath.read_text(encoding="utf-8").splitlines()
            krow = json.loads(klines[0])
        except Exception:
            klines, krow = [], {}
        check("k1 one verdict, one compact parseable line, ts included",
              len(klines) == 1 and krow.get("event") == "deny"
              and krow.get("file") == "src/a.ts" and krow.get("mode") == "deny"
              and krow.get("sessionId") == "sess-k" and bool(krow.get("ts")),
              repr(klines[:1]))
        M.append_gate_event(kld, {"event": "warn", "invented": "nope",
                                "reason": None})
        krow2 = json.loads(kpath.read_text(encoding="utf-8").splitlines()[-1])
        check("k2 unknown keys are dropped and None values are omitted, so the "
              "row shape stays the contract's",
              set(krow2) <= {"ts", "event", "file", "mode", "reason",
                             "sessionId"} and "invented" not in krow2
              and "reason" not in krow2, repr(krow2))
        check("k3 garbage in, silence out - never a raise into a hook",
              M.append_gate_event(None, None) is None
              and M.append_gate_event(tmp_k / "logs2", "not a dict") is None)
        # The self-trim, deterministically: an already-oversized feed is
        # rewritten down to the newest ~400 lines by the very next append,
        # and that append's own row survives the rewrite as the newest line.
        big_line = json.dumps({"ts": "t", "event": "observe",
                               "file": "y" * 180})
        with open(kpath, "w", encoding="utf-8") as fh:
            fh.write((big_line + "\n") * 3000)          # ~650KB, over the cap
        check("k4a (fixture guard) the constructed feed really is over the cap",
              kpath.stat().st_size > M._GATE_EVENTS_MAX_BYTES)
        M.append_gate_event(kld, {"event": "deny", "file": "newest.ts"})
        klines = kpath.read_text(encoding="utf-8").splitlines()
        check("k4 past ~512KB the feed trims itself to the newest ~400 lines, "
              "and the newest row survives the rewrite",
              len(klines) == M._GATE_EVENTS_KEEP_LINES
              and kpath.stat().st_size < M._GATE_EVENTS_MAX_BYTES
              and json.loads(klines[-1]).get("file") == "newest.ts",
              repr((len(klines), kpath.stat().st_size)))

        # The temp file the trim goes through. The trim rewrites a file every
        # hook process shares, and one Edit tool call fans out to SEVEN hook
        # processes, so a fixed `path + ".tmp"` is two of them opening,
        # truncating and os.replace-ing the same file. Measured at 12-way
        # concurrency against this very feed: 1773 corrupt reads out of 4800
        # with the fixed name, 0 through atomic_write_text. k4 above cannot see
        # any of that - BOTH shapes rewrite the feed when nothing else is
        # running - so these cases judge the temp NAME instead, and what
        # happens when that one name is already someone else's.
        def overfill():
            with open(kpath, "w", encoding="utf-8") as fh:
                fh.write((big_line + "\n") * 3000)

        handed_over = []
        _real_replace = os.replace

        def _spy_replace(src, dst):
            handed_over.append(str(src))
            return _real_replace(src, dst)

        os.replace = _spy_replace
        try:
            overfill()
            M.append_gate_event(kld, {"event": "deny", "file": "trim-1.ts"})
            overfill()
            M.append_gate_event(kld, {"event": "deny", "file": "trim-2.ts"})
        finally:
            os.replace = _real_replace
        check("k5 two trims hand os.replace two DIFFERENT temp names, neither "
              "of them the colliding `path + \".tmp\"`, and both inside the "
              "feed's OWN directory - os.replace is atomic only within one "
              "filesystem, so a system-temp file would not be a swap at all",
              len(handed_over) == 2 and len(set(handed_over)) == 2
              and (str(kpath) + ".tmp") not in handed_over
              and all(os.path.dirname(t) == str(kld) for t in handed_over),
              repr(handed_over))
        check("k6 and neither trim leaves a temp file behind",
              [p.name for p in kld.iterdir() if p.name.endswith(".tmp")] == [])
        # What "another process already owns that name" looks like from in here.
        os.mkdir(str(kpath) + ".tmp")
        overfill()
        M.append_gate_event(kld, {"event": "deny", "file": "collide.ts"})
        klines = kpath.read_text(encoding="utf-8").splitlines()
        check("k7 the trim still lands when `path + \".tmp\"` is occupied - the "
              "naive writer opens that one fixed name, raises, and the "
              "fail-open except swallows the trim, so the feed grows without "
              "bound and nothing says so",
              len(klines) == M._GATE_EVENTS_KEEP_LINES
              and json.loads(klines[-1]).get("file") == "collide.ts",
              repr(len(klines)))
        os.rmdir(str(kpath) + ".tmp")   # so k9 below can judge ANY *.tmp left

        # The helper's own contract, both directions. It RAISES on failure -
        # a writer that returns quietly is how a caller reports success over a
        # file it never wrote...
        adir = tmp_k / "atomic"
        adir.mkdir()
        blocked = adir / "target"
        blocked.mkdir()                 # a DIRECTORY where the write must land
        raised = False
        try:
            M.atomic_write_text(blocked, "x")
        except Exception:
            raised = True
        check("k8 atomic_write_text raises on a failed write instead of "
              "reporting silence, and still leaves no temp file behind",
              raised and sorted(p.name for p in adir.iterdir()) == ["target"],
              repr((raised, sorted(p.name for p in adir.iterdir()))))
        # ...and that raise stops at append_gate_event, which is the fail-open
        # boundary. This is the case for the OTHER mutation: it goes red the day
        # the helper's failure is allowed to propagate into a blocking hook.
        def _exploding_replace(src, dst):
            raise IOError("no space left on device")

        os.replace = _exploding_replace
        try:
            overfill()
            hook_raised = False
            try:
                M.append_gate_event(kld, {"event": "deny", "file": "boom.ts"})
            except Exception:
                hook_raised = True
        finally:
            os.replace = _real_replace
        check("k9 a trim that cannot be swapped into place is silence, not a "
              "raise into the hook - the feed is telemetry, and blocking real "
              "work over a lost telemetry row is the worse failure",
              not hook_raised
              and [p.name for p in kld.iterdir()
                   if p.name.endswith(".tmp")] == [],
              repr(sorted(p.name for p in kld.iterdir())))

        # The helper's `tempfile` import is function-local on purpose: every
        # hook imports THIS module on every tool call, and one Edit starts seven
        # of them. Measured cold on 3.14: 18.2ms to import _config, 23.1ms with
        # `import tempfile` at module scope - ~5ms x 7 processes x every tool
        # call, to serve a rewrite that fires almost never. A subprocess is the
        # only way to ask: this selftest imported tempfile at its own top.
        # `Path(__file__).resolve().parent` meant "the directory _config.py
        # lives in" while this case sat inside _config.py. From `tests/` it
        # names `tests/`, and the child's `import _config` would fail - loud
        # here (returncode 1), but about the wrong thing. Spelled off the
        # SUBJECT's own `__file__`, which is the hooks directory wherever this
        # suite is run from.
        _probe = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); import _config; "
             "print('tempfile' in sys.modules)"
             % str(Path(M.__file__).resolve().parent)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check("k10 importing _config does not drag `tempfile` in - hooks that "
              "never rewrite anything pay nothing for the helper",
              _probe.returncode == 0
              and _probe.stdout.decode("utf-8", "replace").strip() == "False",
              repr(_probe.stdout[-80:]) + repr(_probe.stderr[-200:]))
    finally:
        shutil.rmtree(tmp_k, ignore_errors=True)

    # (k11) the same question as k10, asked of the heaviest passenger `_config`
    # ever carried. `_config` used to load `_policy.py` at MODULE scope purely to
    # copy its DEFAULTS into this file's own dict; loading it executes the whole
    # scripts-side module, whose pinned path preamble imports `_output`, which
    # imports `ast`. Every hook paid for it - measured at ~9 ms of the ~33 ms a
    # typical hook costs - and exactly one hook consults a policy, on a matcher
    # (Skill|Task|Agent|mcp__.*) that can never coincide with an edit or a shell
    # call. `ast` is a BUILD-TIME dependency: it is there for the house-style
    # lints, which no hook runs.
    #
    # The probe names both leaks rather than asserting one, because they arrive
    # together and the message has to say WHICH came back. Counted, not found:
    # an empty list is the only pass, so a second passenger added later fails
    # here by name instead of hiding behind the first.
    _leak = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import _config; "
         "print(','.join(m for m in ('ast', '_output') if m in sys.modules))"
         % str(Path(M.__file__).resolve().parent)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check("k11 importing _config does not execute the scripts-side policy module "
          "- no `ast`, no `_output`, on the hot path of every hook",
          _leak.returncode == 0
          and _leak.stdout.decode("utf-8", "replace").strip() == "",
          repr(_leak.stdout[-120:]) + repr(_leak.stderr[-200:]))

    # (p) the capability policy — the block itself lives in scripts/_policy.py and
    # is exercised there; what this file owns is the delegation and the one piece of
    # evidence a hook cannot get from the config alone: which areas are active.
    tmp_p = Path(tempfile.mkdtemp(prefix="config-policy-"))
    try:
        _pol = M.policy_mod()
        check("p1 the policy engine ships and is reachable from the hooks",
              _pol is not None)
        # p2 used to read `M.DEFAULTS.get("policy") == _pol.DEFAULTS`, back when
        # this file copied the engine's block into its own defaults at import. The
        # copy is gone (k11 says why), so the claim it was making has to be made
        # against the thing that always owned it: `policy_cfg` fills every kind in
        # from the ENGINE's defaults, so a project that names one kind still gets
        # the others. Same guarantee, asserted where it actually lives - and the
        # engine's block is now reachable ONLY through the accessor, which is the
        # property the second half pins.
        check("p2 the engine's own block is what fills an unnamed kind - one "
              "statement of what ships inert, and DEFAULTS no longer copies it",
              _pol is not None
              and M.policy_cfg({})["skills"] == _pol.DEFAULTS["skills"]
              and "policy" not in M.DEFAULTS)
        check("p3 the shipped default is inert, so the guard hook returns before "
              "it reads anything",
              _pol is not None and not _pol.is_active(M.policy_cfg({})))
        check("p4 a project's block merges through the engine, not by hand",
              M.policy_cfg({"policy": {"skills": {"default": "deny"}}})["skills"]
              == {"default": "deny", "allow": [], "deny": [], "areas": {}})
        # p5 asked whether `load()` handed out a policy block aliasing DEFAULTS.
        # `load()` no longer emits one at all, so the aliasing question moved to
        # the only place a caller can still reach the engine's dict: `policy_cfg`.
        # It must hand back a fresh block every time - a caller that edits its
        # result must not be editing what the next hook resolves against.
        _p = M.policy_cfg({})
        _p["skills"]["deny"].append("MUTATED")
        check("p5 a resolved policy does not alias the engine's defaults",
              "MUTATED" not in (_pol.DEFAULTS["skills"]["deny"] if _pol else [])
              and "MUTATED" not in M.policy_cfg({})["skills"]["deny"])

        rel = "docs/audit/audit-plan.json"

        def write_plan(phases, sharded=False):
            d = tmp_p / "docs" / "audit"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            if not sharded:
                (d / "audit-plan.json").write_text(
                    json.dumps({"meta": {"version": 2}, "phases": phases}),
                    encoding="utf-8")
                return
            idx = {"meta": {"version": 3}, "phases": []}
            (d / "phases").mkdir(exist_ok=True)
            for ph in phases:
                idx["phases"].append({"id": ph["id"], "title": ph.get("title", ""),
                                      "shard": "phases/%s.json" % ph["id"]})
                (d / "phases" / ("%s.json" % ph["id"])).write_text(
                    json.dumps(ph), encoding="utf-8")
            (d / "audit-plan.json").write_text(json.dumps(idx), encoding="utf-8")

        check("p6 no manifest -> no active areas, and no raise",
              M.active_area_tags(tmp_p, rel) == []
              and M.active_area_tags(None, None) == [])
        write_plan([{"id": "P1", "title": "a", "status": "done", "area": "api",
                     "tasks": [{"id": "P1.1", "status": "done"}]},
                    {"id": "P2", "title": "b", "status": "in_progress",
                     "area": ["web", "web"],
                     "tasks": [{"id": "P2.1", "status": "pending"}]}])
        check("p7 only the phases with work in progress count, deduped by the same "
              "normaliser the rest of the plugin uses",
              M.active_area_tags(tmp_p, rel) == ["web"],
              repr(M.active_area_tags(tmp_p, rel)))
        write_plan([{"id": "P1", "title": "a", "status": "pending", "area": "api",
                     "tasks": [{"id": "P1.1", "status": "in_progress"}]}])
        check("p8 a running TASK under a pending phase makes its area active - the "
              "same evidence the plan gate grades on",
              M.active_area_tags(tmp_p, rel) == ["api"])
        write_plan([{"id": "P1", "title": "a", "status": "in_progress",
                     "area": "api", "tasks": [{"id": "P1.1", "status": "pending"}]}],
                   sharded=True)
        check("p9 sharded layout: the areas are read from the ASSEMBLED manifest, "
              "or the index stubs' missing status would make every area rule "
              "silently inert", M.active_area_tags(tmp_p, rel) == ["api"])
        write_plan([{"id": "P1", "title": "a", "status": "in_progress",
                     "tasks": [{"id": "P1.1", "status": "pending"}]}])
        check("p10 an untagged running phase activates nothing",
              M.active_area_tags(tmp_p, rel) == [])
    finally:
        shutil.rmtree(tmp_p, ignore_errors=True)

    # (g) governing_lock — which of the two tiers covers a given write. This is the
    # map the enforcement rests on, so a path that should be governed and isn't
    # would silently un-enforce, and one that shouldn't be and is would deny work
    # that has nothing to do with the manifest.
    # Named `M` inline; renamed here because `M` is the module under test.
    # An assignment to `M` inside this function would make the name local for
    # the WHOLE body, and every `M.<name>` above it would raise
    # UnboundLocalError - loud, but a needless landmine.
    MAN = "audit/plan.json"
    check("g1 the index is the index tier", M.governing_lock(MAN, MAN) == "index")
    check("g2 a shard is its own phase's tier",
          M.governing_lock(MAN, "audit/phases/P1.json") == "phase-P1")
    check("g3 bugfix shards too",
          M.governing_lock(MAN, "audit/phases/BF12.json") == "phase-BF12")
    check("g4 a non-JSON file in phases/ is not a shard",
          M.governing_lock(MAN, "audit/phases/notes.txt") is None)
    check("g5 a nested path under phases/ is not a shard (no id with a slash)",
          M.governing_lock(MAN, "audit/phases/sub/P1.json") is None)
    check("g6 a sibling of the manifest is not governed",
          M.governing_lock(MAN, "audit/other.json") is None)
    check("g7 ordinary source is not governed",
          M.governing_lock(MAN, "src/app.py") is None)
    check("g8 the lockfile itself is not a governed WRITE",
          M.governing_lock(MAN, MAN + ".lock") is None)
    # A manifest at the repo root makes dirname('') — `phases/` must still work and
    # must not swallow the repo.
    check("g9 root manifest: its shards still resolve",
          M.governing_lock("plan.json", "phases/P1.json") == "phase-P1")
    check("g10 root manifest: nothing else does",
          M.governing_lock("plan.json", "src/app.py") is None
          and M.governing_lock("plan.json", "anything.json") is None)
    check("g11 garbage in, None out", M.governing_lock(None, None) is None
          and M.governing_lock("", "") is None)

    # (h) manifest_lock_conflict fail-open. Every one of these must return None:
    # an unattributable lock that could deny would brick legitimate work in a
    # plugin whose whole posture is to fail open.
    tmp_h = Path(tempfile.mkdtemp(prefix="config-lock-"))
    try:
        cfg_h = dict(M.DEFAULTS)
        check("h1 a path with no governing lock is never a conflict",
              M.manifest_lock_conflict(tmp_h, cfg_h, MAN, "src/app.py", "s") is None)
        check("h2 not a git repo -> no verdict",
              M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN, "s") is None)
        if not shutil.which("git"):
            print("SKIP h3-h7 (git is not on PATH)")
        else:
            subprocess.run(["git", "init", "-q", str(tmp_h)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            check("h3 a git repo with no lock -> no verdict",
                  M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN, "s") is None)
            lockmod = M._load_lock_lib()
            ld_h = Path(lockmod.lock_dir(str(tmp_h)))
            ld_h.mkdir(parents=True, exist_ok=True)

            def write_lock(**fields):
                with open(ld_h / "index.lock", "w", encoding="utf-8") as fh:
                    json.dump(fields, fh)

            write_lock(hostname=platform.node(), pid=os.getpid())
            check("h4 a lock with no sessionId -> no verdict",
                  M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN, "s") is None)
            write_lock(hostname=platform.node(), pid=os.getpid(), sessionId="s")
            check("h5 our own lock -> no verdict",
                  M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN, "s") is None)
            check("h6 a caller with no session id of its own -> no verdict",
                  M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN, "") is None)
            got = M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN, "other")
            check("h7 another live session -> a conflict, with its basis",
                  isinstance(got, dict) and got["live"] is True
                  and got["holder"] == "s" and bool(got["basis"]))

            # h8-h10: the identity split that nearly shipped a gate denying the
            # orchestrator its own writes. The lock is taken from Bash under
            # $CLAUDE_CODE_SESSION_ID; the hook is handed a DIFFERENT session_id in
            # its payload. Measured in a live session, they do not match. Every
            # identity that means "the same Claude Code process" must count as ours.
            _sid, _pid_env = (os.environ.get("CLAUDE_CODE_SESSION_ID"),
                              os.environ.get("CLAUDE_PID"))
            try:
                os.environ["CLAUDE_CODE_SESSION_ID"] = "from-bash"
                os.environ.pop("CLAUDE_PID", None)
                write_lock(hostname=platform.node(), pid=os.getpid(),
                           sessionId="from-bash")
                check("h8 a lock taken under the env session id is ours, even "
                      "though the hook is handed a different one",
                      M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN,
                                             "from-hook-payload") is None)
                # And the pid path, which survives any session-id shape at all.
                os.environ["CLAUDE_CODE_SESSION_ID"] = "something-else"
                os.environ["CLAUDE_PID"] = str(os.getpid())
                write_lock(hostname=platform.node(), pid=os.getpid(),
                           sessionId="from-bash")
                check("h9 or matched by $CLAUDE_PID when neither id lines up",
                      M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN, "from-hook") is None)
                # A genuinely different process must still conflict.
                write_lock(hostname=platform.node(), pid=os.getpid(),
                           sessionId="a-real-other-session")
                os.environ["CLAUDE_PID"] = str(os.getpid() + 1)
                got = M.manifest_lock_conflict(tmp_h, cfg_h, MAN, MAN, "from-hook")
                check("h10 but a genuinely different session still conflicts",
                      isinstance(got, dict) and got["holder"] == "a-real-other-session")
            finally:
                for k, v in (("CLAUDE_CODE_SESSION_ID", _sid),
                             ("CLAUDE_PID", _pid_env)):
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
    finally:
        shutil.rmtree(tmp_h, ignore_errors=True)

    # (i) ensure_local_dir: plugin-managed local dirs are self-ignoring --------
    # state/, logs/ and the ledger hold live tokens, person identities and
    # session scratch; none of it belongs in git. The dirs make THEMSELVES
    # ignored (a `*` .gitignore inside), because advising the user in help
    # text demonstrably did not happen on a real repo.
    tmp_i = Path(tempfile.mkdtemp(prefix="config-ignore-selftest-"))
    try:
        d_i = M.ensure_local_dir(tmp_i / "state")
        check("i1 ensure_local_dir creates the dir and a `*` .gitignore",
              d_i.is_dir() and (d_i / ".gitignore").read_text(
                  encoding="utf-8").splitlines()[-1] == "*")
        (d_i / ".gitignore").write_text("custom\n", encoding="utf-8")
        M.ensure_local_dir(d_i)
        check("i2 an existing marker is never overwritten - the file is the "
              "user's once it exists",
              (d_i / ".gitignore").read_text(encoding="utf-8") == "custom\n")
        (d_i / ".gitignore").unlink()
        M.ensure_local_dir(d_i)
        check("i3 a deleted marker returns on the next call - tracked files "
              "are immune to ignore rules, so this cannot override a "
              "deliberate `git add -f` tracking decision",
              (d_i / ".gitignore").exists())
        blocker = tmp_i / "blocker"
        blocker.write_text("", encoding="utf-8")
        got_i = M.ensure_local_dir(blocker / "sub")     # parent is a FILE
        check("i4 an uncreatable path never raises - hook context",
              isinstance(got_i, Path))
        M.append_gate_event(str(tmp_i / "logs"), {"event": "deny"})
        check("i5 append_gate_event's logs dir carries the marker",
              (tmp_i / "logs" / ".gitignore").exists())
    finally:
        shutil.rmtree(tmp_i, ignore_errors=True)

    # (q) A1 (v0.36): the test-file exemption stops at data formats.
    # `tsconfig.test.json` matched `**/*.test.*` and slipped the plan gate as a
    # "test file" (live find) — but it is build CONFIGURATION named like a test.
    # Tests are code; a pure data/markup format cannot be one, whatever its
    # name says.
    _eg_q = M.DEFAULTS["exemptGlobs"]
    for _rel_q in ("tsconfig.test.json", "conf/tsconfig.spec.json",
                   "docker-compose.test.yml", "ops/test_config.yaml",
                   "fixtures/test_data.json"):
        check("q1 %s is NOT exempt - a config/data file named like a test is "
              "not a test file" % _rel_q, not M.matches_exempt(_rel_q, _eg_q))
    for _rel_q in ("src/cart.test.ts", "src/Cart.spec.tsx", "tests/test_cart.py",
                   "pkg/cart_test.go", "spec/cart_spec.rb", "test/cart_test.exs"):
        check("q2 %s STAYS exempt - the multi-language width of the globs is "
              "deliberate" % _rel_q, M.matches_exempt(_rel_q, _eg_q))
    check("q3 a data fixture inside a test DIRECTORY still matches the "
          "directory globs - the carve-out is per-glob, not per-file",
          M.matches_exempt("app/tests/fixture.json",
                         M.DEFAULTS["tddReminder"]["testGlobs"]))
    check("q4 an explicit non-test glob still exempts the config it names - "
          "only test-suffix-shaped globs are carved out",
          M.matches_exempt("tsconfig.test.json", ["**/tsconfig.*"]))

    # (t) utc_stamp: the trailing Z and gmtime() are one fact -----------------
    # Every record a hook writes is stamped through this, and the bug it exists
    # to prevent is invisible to the obvious assertions: the same format built
    # from localtime also ends in "Z", is also 20 characters long, and also
    # strptimes cleanly. So t1/t2 are shape only and are NOT trusted to catch
    # it; t3 is the one that can, t4 proves t3 discriminates by feeding it the
    # bug on purpose, and t5 is what still fires where t4 cannot run.
    import calendar
    import inspect

    _UNREADABLE = 10 ** 9

    def _skew_from_utc(stamp):
        """Seconds between `stamp` READ AS UTC and the real UTC now. A stamp
        that will not parse returns a skew no threshold here can accept, never
        0 — an unreadable format is further from correct, not closer — and the
        return keeps the suite reporting cases instead of dying at t3."""
        try:
            parsed = time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return _UNREADABLE
        return abs(calendar.timegm(parsed) - int(time.time()))

    def _localtime_variant():
        """The fifth-and-a-half variant, written deliberately: right format,
        wrong clock. t4 asserts t3's check rejects THIS."""
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.localtime())

    # A non-UTC local zone, forced, because on a box whose local time IS UTC no
    # runtime observation can tell the two apart -- and every CI runner is on
    # UTC, which is precisely why this class of bug survives review and a green
    # pipeline. POSIX form ("XYZ-14" == UTC+14) rather than an Olson name, so no
    # tzdata is required; time.tzset is POSIX-only, hence the getattr.
    _tzset = getattr(time, "tzset", None)
    _tz_saved = os.environ.get("TZ")
    try:
        if _tzset is not None:
            os.environ["TZ"] = "XYZ-14"
            _tzset()
        _t_now = time.time()
        _local_offset = calendar.timegm(time.localtime(_t_now)) - int(_t_now)

        check("t1 utc_stamp ends in Z", M.utc_stamp().endswith("Z"),
              repr(M.utc_stamp()))
        _parsed = True
        try:
            time.strptime(M.utc_stamp(), "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            _parsed = False
        check("t2 utc_stamp parses back under exactly its own format, so a "
              "numeric offset or a dropped Z would be a parse error", _parsed,
              repr(M.utc_stamp()))
        check("t3 utc_stamp's digits ARE UTC - read as UTC they land on the "
              "current instant, not on local wall-clock time",
              _skew_from_utc(M.utc_stamp()) <= 2,
              "skew=%ds" % _skew_from_utc(M.utc_stamp()))
        if abs(_local_offset) < 60:
            # Not a pass: with local == UTC the two builds are identical, so
            # the case would be green while asserting nothing.
            print("SKIP t4 (local zone is UTC and TZ cannot be forced here - "
                  "the localtime variant is indistinguishable)")
        else:
            check("t4 and t3 discriminates: the same format built from "
                  "localtime FAILS it", _skew_from_utc(_localtime_variant()) > 2,
                  "offset=%ds skew=%ds" % (_local_offset,
                                           _skew_from_utc(_localtime_variant())))
        # The docstring names `time.localtime()` as the bug, so only what
        # follows the closing triple quote is judged. NOT `.replace(__doc__)`:
        # 3.13+ dedents and strips `__doc__` at compile time, so it is no longer
        # a substring of the source and the subtraction silently removes nothing
        # (seen red here). With no docstring, split() yields one part and the
        # whole body is judged, which is also correct. This is the only (t) case
        # that fires on Windows, where time.tzset does not exist and t4 skips.
        _src = inspect.getsource(M.utc_stamp).split('"""')[-1]
        check("t5 the helper's own body pairs Z with gmtime and never reaches "
              "for localtime", "time.gmtime()" in _src and "localtime" not in _src,
              repr(_src))
    finally:
        if _tzset is not None:
            if _tz_saved is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = _tz_saved
            _tzset()


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__config.py --selftest\n")
    raise SystemExit(2)
