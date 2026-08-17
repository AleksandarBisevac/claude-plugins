#!/usr/bin/env python3
"""
The cases for `panel-server.py`, moved out of it - an entry point.

`panel-server.py` is hyphenated, so it comes through `_loader.load_script` and the
test file substitutes underscores (`test_panel_server.py`); see
`test_migrate_manifest.py` for both halves of that rule. `M` is the module under
test - with a `load_script` module object there is nothing else to spell.

FOUR EXPRESSIONS READ SOURCE, AND ALL FOUR HAD TO BE RE-POINTED.

  * `_src_of_this_file()` was a three-line helper defined in this file, in
    `_panel_state.py` and in `_panel_write.py` - three identical copies of
    `open(__file__)`, and every one of their six call sites was inside a
    `--selftest`. Nothing in the product ever called one. Moved literally they would
    read the TEST file, where `def do_GET` does not appear: the slices below would
    raise, and the `"/api/help" not in _write_src` halves would have passed by
    describing an empty region. The three copies are gone from the product and the
    three suites share `_harness.module_source(M)`, which takes the module.
  * the do_GET / do_PUT slices were `_hsrc.split(a)[1].split(b)[0]`, whose two
    halves fail in opposite ways: a missing `a` raises, a missing `b` silently
    hands back the rest of the file. The second is the live hazard - the `do_PUT`
    slice terminates at `def _free_port` only because that happens to be the next
    top-level def, and the comment beside it has said so for a while. Both are
    `_harness.between()` now, which raises on either marker; `run()` turns the
    escape into a named failing case rather than a crash.
  * the `gt` case reads `_panel_state.py` and asserts `plan_gate_mode` appears
    between `def _gate_block` and `def _run_status`. That adjacency is a design
    constraint, not an accident, so the slice stays - re-pointed at the subject
    through `_harness.module_source(_panel_state)` rather than at a path built off
    this file's own directory, where `_panel_state.py` does not exist.

`_help` and `_manifest_io` are imported here the way `panel-server.py` imports them,
because these cases compare against those modules' own objects (`_help.payload()`,
`_mio.load_manifest`). `_panel_state` is imported for the `gt` slice alone.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _help                                       # noqa: E402  (as panel-server imports it)
import _manifest_io as _mio                        # noqa: E402  (as panel-server imports it)
import _panel_state                                # noqa: E402  (the `gt` source slice only)

M = _loader.load_script("panel-server.py", modname="panel_server")


# --- cases --------------------------------------------------------------------
def _cases(check):
    # the session token must never reach a terminal by accident
    check("token is redacted for anything that gets kept",
          M._redact_token("http://127.0.0.1:8791/?t=SECRETVALUE")
          == "http://127.0.0.1:8791/?t=<hidden>")
    check("redaction survives extra query params",
          "SECRET" not in M._redact_token("http://127.0.0.1:1/?t=SECRET&x=1"))
    check("redaction of a malformed url still hides a token",
          "SECRET" not in M._redact_token(None) + M._redact_token("t=SECRET"))

    # discovery (_scan_skills/_scan_agents/discover, the front-matter parser and
    # their fixture-dir cases) moved to _panel_discovery.py's own selftest (P12.2);
    # `discover` itself is still exercised indirectly below via `apply_composition`
    # writing a reviewSkill/skills value the same way the panel's picker would.
    tmp = tempfile.mkdtemp(prefix="panel-selftest-")
    proj = os.path.join(tmp, "proj")

    # path safety
    check("within: inside ok", M._within(proj, os.path.join(proj, ".claude/x")))
    check("within: escape refused", not M._within(proj, os.path.join(proj, "..", "evil")))

    # The write path's own cases -- the config and composition writers, the sharded
    # write-back, the lock refusal, the areas and policy PUTs, the change rows and
    # the journal -- moved to _panel_write.py's selftest (P12.4), with their labels.
    # The FIXTURE they built stays here: build_state, the viewer, runStatus and the
    # composition view below all read this project, and they are claims about what
    # the server serves rather than about what a save writes.
    M.write_config(proj, {"trivialLineThreshold": 40})
    mpath = M._manifest_path(proj, M.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    M._atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T",
                               "status": "pending"}]}]})
    M.apply_composition(proj, {"meta": {"reviewSkill": "user-skill"},
                             "tasks": {"P1.1": {"skills": ["user-skill"],
                                                "model": "opus"}}})

    # --- v0.31: the help endpoint ------------------------------------------------
    # The drawer that consumes this lands with panel c8; the endpoint ships now, and
    # is exercised here rather than left as untested code until it has a caller —
    # the one thing v0.29's journal call site taught, in the other direction.
    _help_pay = M.help_state()
    # Read the handler's own source, sliced at the method boundaries: counting the
    # string over the whole file would count this check as a route. THIS FILE, not
    # _panel_page.py — do_GET/do_PUT/do_POST stayed here when the page moved, so the
    # slices still read the code they are about.
    #
    # WARNING, DEFINITION ORDER: `_write_src` runs from `def do_PUT` to
    # `def _free_port`, i.e. it deliberately spans do_PUT AND do_POST — every route
    # that WRITES — and it ends there only because `_free_port` happens to be the
    # next top-level def after the handler class. Move `_free_port` (it reads like
    # lifecycle code and would look at home beside the pidfile) and the slice no
    # longer means what it says. It can no longer do so IN SILENCE: the hand-rolled
    # `.split("def _free_port")[0]` returned the whole rest of the file when that
    # marker went missing, and the "…not in _write_src" halves below then passed by
    # being vacuously true. `_harness.between()` raises on either marker, and
    # `run()` reports the escape as a named failing case. If you move `_free_port`,
    # re-point the boundary at whatever ends the class, and prove the case still
    # goes red by putting `/api/help` in do_PUT.
    _hsrc = _harness.module_source(M)
    _get_src = _harness.between(_hsrc, "def do_GET", "def do_PUT")
    _write_src = _harness.between(_hsrc, "def do_PUT", "def _free_port")
    check("GET /api/help is a route, and only a GET: help is a document, and a "
          "drawer that could write one would be a second config writer",
          'if path == "/api/help"' in _get_src and "/api/help" not in _write_src)
    check("PUT /api/ado is a write route, and only a write - the connector card "
          "saves through it, mirroring /api/areas; its read side rides "
          "composition.adoStatus in /api/state",
          'if path == "/api/ado"' in _write_src and "/api/ado" not in _get_src)
    check("...and it serves _help.payload() rather than a second assembly of the "
          "same thing", _help_pay == _help.payload())
    _hcfg = _help_pay["fields"]["config"]
    _unexplained = [p for p in M._settings_paths()
                    if not (_help.lookup(_hcfg, p) or {}).get("description")]
    check("every control the Settings form renders can be explained from the "
          "SCHEMA - the drawer's whole contract, and the reason none of this text "
          "is retyped here: %r" % (_unexplained,), not _unexplained)
    _hman = _help_pay["fields"]["manifest"]
    _uncomp = [k for k, p in _help_pay["composition"].items()
               if not (_help.lookup(_hman, p) or {}).get("description")]
    check("...and so can every composition lever, under the panel's own name for "
          "it: %r" % (_uncomp,), not _uncomp)
    check("the four concept pages arrive whole, so the drawer has topics and not "
          "just tooltips",
          sorted(t["id"] for t in _help_pay["topics"])
          == ["areas", "gate-tiers", "journal", "policy"]
          and all(t["title"] and t["paragraphs"] for t in _help_pay["topics"]))
    check("the guide agent's card rides along with the tools its own file grants, "
          "so an 'Ask audit:guide' hint cannot offer a capability it does not have",
          (_help_pay["agent"] or {}).get("name") == "guide"
          and (_help_pay["agent"] or {}).get("readOnly") is True
          and (_help_pay["agent"] or {}).get("model") == "haiku")
    check("the payload is documentation, not state: it names no path on this "
          "machine, so it cannot be read as a report about this project",
          M._output.SCRIPTS_DIR not in json.dumps(_help_pay)
          and M._output.PLUGIN_ROOT not in json.dumps(_help_pay))

    # --- who is looking --------------------------------------------------------
    _vw = M._viewer(proj, M.read_config(proj))
    check("the panel knows who is driving it, and in which mode",
          isinstance(_vw, dict) and set(_vw) == {"author", "mode"}
          and isinstance(_vw["mode"], str))
    check("viewer travels with the state, so the topbar can name the writer",
          isinstance(M.build_state(proj).get("viewer"), dict))
    _vprev = open(M._config_path(proj), encoding="utf-8").read()
    try:
        with open(M._config_path(proj), "w", encoding="utf-8") as fh:
            json.dump({"usage": {"authorMode": "none"}}, fh)
        _vn = M._viewer(proj, M.read_config(proj))
        # .get(), not [] — a viewer missing a key is the case the check above is
        # about, and a KeyError here would take the suite down before it printed.
        check("authorMode none means no name — a decision, not a failure",
              _vn.get("mode") == "none" and _vn.get("author") is None)
    finally:
        with open(M._config_path(proj), "w", encoding="utf-8") as fh:
            fh.write(_vprev)

    # build_state shape
    st = M.build_state(proj)
    check("build_state has rollup + composition",
          st["rollup"] is not None and "reviewSkill" in st["composition"]["meta"])
    check("build_state reports manifestPath", bool(st["manifestPath"]))
    check("build_state carries the bug rows the Overview lists",
          isinstance(st.get("bugs"), list)
          and M.build_state(tmp)["bugs"] == [])   # no manifest -> empty, never absent

    # D9 — runStatus ("who's running what"): per-phase lock + claim
    check("build_state has runStatus",
          isinstance(st.get("runStatus"), dict) and "phases" in st["runStatus"])
    # _lock_info's own cases (what a lock file says, and whether the run behind it
    # is alive) moved to _panel_state.py (P12.3).
    m2 = M._read_json(mpath)
    m2["phases"][0]["claim"] = {"sessionId": "sess-abcd1234", "host": "h", "branch": "audit/p1"}
    M._atomic_write_json(mpath, m2)
    st2 = M.build_state(proj)
    check("runStatus surfaces a phase claim from the manifest",
          ((st2["runStatus"]["phases"].get("P1") or {}).get("claim") or {}).get("sessionId")
          == "sess-abcd1234")
    check("runStatus phase lock is None when the git-dir lock isn't held (non-git tmp)",
          (st2["runStatus"]["phases"].get("P1") or {}).get("lock") is None)
    # D9, second half: the badges were a snapshot taken at page load, so a colleague
    # taking a phase lock in another worktree showed up only if you reloaded.
    check("D9: run status is served on its own endpoint, so the poll never has to "
          "refetch full state",
          "/api/runstatus" in M.UI_HTML
          and M._run_status(tmp, {}, {}) is not None)

    # v0.16 — composition view surfaces per-phase area (list) + reviewSkill;
    # a phase can carry cross-cutting tags (['backend','security'])
    m3 = M._read_json(mpath)
    m3["phases"][0].update(area=["backend", "security"], reviewSkill="backend-review")
    M._atomic_write_json(mpath, m3)
    cv = M._composition_view(_mio.load_manifest(mpath))
    check("composition view carries area list + reviewSkill",
          cv["phases"][0].get("area") == ["backend", "security"]
          and cv["phases"][0].get("reviewSkill") == "backend-review")
    st3 = M.build_state(proj)
    check("rollup normalizes area to a list + groups under each tag",
          st3["rollup"]["phases"][0].get("area") == ["backend", "security"]
          and "backend" in (st3["rollup"].get("areas") or {})
          and "security" in (st3["rollup"].get("areas") or {}))

    check("UI token injected as a quoted JS string",
          'const TOKEN="abc123"' in M.UI_HTML.replace("__AUDIT_TOKEN__", M._js("abc123")))
    # --- Settings: the whole config, named by what it does ---------------------
    # The coverage checks (SETTINGS_GROUPS/FIELD_HELP derived against
    # validate-config's own key sets) moved to _panel_settings.py's own selftest
    # (P12.1) — they need no UI_HTML and no server source. What stays here needs
    # one or the other.
    _vc = M._cores()[1]
    # `policy` is a root key with no control on this form, on purpose — the one
    # exemption, and it is stated rather than silently subtracted. It is not a
    # setting with a value; it is a rule set whose meaning is the verdict it
    # produces for each installed capability, which is what /api/policy serves and
    # what the **Policy tab** renders, switch by switch. A generic text box over it
    # would be a JSON editor wearing a label.
    _settings_exempt = {"policy"}
    check("the exempt key is served by its own endpoint instead of simply being "
          "missing from the panel",
          all('if path == "/api/%s"' % k in _harness.module_source(M)
              for k in _settings_exempt))
    check("gt: the server block behind that card is _run_status's, with the "
          "tier computed by the hooks' own functions",
          isinstance((M._run_status(proj, M.read_config(proj), {})
                      .get("gate") or {}).get("mode"), str)
          and "plan_gate_mode" in
          # The two defs are ADJACENT in _panel_state.py and must stay so: this
          # slice is the design constraint, not an accident of ordering, and
          # `between()` raises rather than widening if either marker moves.
          _harness.between(_harness.module_source(_panel_state),
                           "def _gate_block", "def _run_status"))
    check("usage.bands is a legitimate key now, so the pair the README documents "
          "no longer warns from the plugin's own validator",
          "bands" in _vc.KNOWN_USAGE
          and _vc.validate_config(
              {"usage": {"bands": {"highUSD": 4, "outlierUSD": 12}}}) == ([], []))

    check("th-p2 the page is dressed in THIS project's theme per request, and "
          "the template keeps the marker so it can be",
          '"/*__THEME_TOKENS__*/"' in _hsrc
          and "UI_TEMPLATE.replace(" in _hsrc
          and "/*__THEME_TOKENS__*/" in M.UI_TEMPLATE
          and "/*__THEME_TOKENS__*/" not in M.UI_HTML)
    check("...which the endpoint answers with the shape that resolved it, so the "
          "drawer can say a second pricing row is not a second field",
          _help.entry_for("usage.pricing.opus.in", "config")["key"]
          == "usage.pricing.<name>.in")
    check("a path nothing documents is found:false rather than a 404 - 'nothing "
          "describes this' is an answer, a 404 is indistinguishable from an "
          "install with no help endpoint at all",
          M.help_field("nothing.like.this", "config") ==
          {"found": False, "path": "nothing.like.this", "doc": "config"}
          and M.help_field("enforce", "config").get("found") is True)
    check("...and the document is one of the two shipped schemas, never a path "
          "someone put in a query string",
          M.help_field("enforce", "../../../etc/passwd").get("found") is False)
    # `.get`, not `[...]`: a response that stopped carrying the key is exactly what
    # these two are about, and a check that dies subscripting it exits 1 with a
    # traceback instead of a named failure — which is how a mutation goes red for
    # the wrong reason and proves nothing (F3, one level down).
    # The drawer prints these one after the other under two headings. Byte-equal
    # is not two voices, it is the same sentence twice — and it is the shape of
    # the duplication this whole endpoint exists to avoid.
    _cfgfields = _help.config_fields()
    _dupe = [p for p, t in M.FIELD_HELP.items()
             if (_help.lookup(_cfgfields, p) or {}).get("description") == t]
    check("no panel note is word-for-word the schema's own sentence: %r" % _dupe,
          not _dupe)
    _undoc = [p for p in M.FIELD_HELP
              if not (_help.lookup(_cfgfields, p) or {}).get("description")]
    check("...and every note is beside a field the schema describes, so the "
          "drawer never opens on a note with nothing to cite: %r" % _undoc,
          not _undoc)
    check("a quoted frontmatter value is unquoted by the one function that knows "
          "how, so the panel does not publish the escape either",
          M._front_matter("---\nname: x\ndescription: 'the plugin''s own README'\n"
                        "---\n")["description"] == "the plugin's own README"
          and M._front_matter("---\nname: don't\n---\n")["name"] == "don't")

    # --- phase budgets ------------------------------------------------------------
    # The client has no manifest, so budgets come off usage_state(); assert the
    # server side by exercising it rather than by grepping this file's own source.
    import shutil as _sh
    _bproj = tempfile.mkdtemp(prefix="panel-budget-")
    try:
        os.makedirs(os.path.join(_bproj, "docs", "audit"), exist_ok=True)
        with open(os.path.join(_bproj, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "A", "status": "done", "budgetUSD": 40,
                 "tasks": []},
                {"id": "P2", "title": "B", "status": "done", "budgetUSD": 0,
                 "tasks": []},
                {"id": "P3", "title": "C", "status": "done", "budgetUSD": True,
                 "tasks": []},
                {"id": "P4", "title": "D", "status": "done", "budgetUSD": "40",
                 "tasks": []},
                {"id": "P5", "title": "E", "status": "done", "tasks": []}]}, fh)
        # Seed a ledger so this exercises the POPULATED branch, not the stub.
        _bled = os.path.join(_bproj, ".claude", "usage")
        os.makedirs(_bled, exist_ok=True)
        with open(os.path.join(_bled, "2026-08.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": "2026-08-01T10", "sessionId": "s", "phaseId": "P1",
                "taskId": None, "attr": "phase", "model": "claude-opus-5",
                "author": "a@x", "msgs": 1, "in": 1, "out": 1, "cacheW5m": 0,
                "cacheW1h": 0, "cacheR": 0, "costUSD": 1.0}) + "\n")
        _bs = M.usage_state(_bproj)
        check("budgets ship from the server, and 0 / boolean / string / missing "
              "all mean NO budget — exactly as the validator treats them: %s"
              % repr(_bs.get("phaseBudgets")),
              _bs["phaseBudgets"] == {"P1": 40.0})
    finally:
        _sh.rmtree(_bproj, ignore_errors=True)
    # The no-ledger stub must carry every key the populated branch does, or a
    # fresh install hands the client `undefined` for half the tab.
    _eproj = tempfile.mkdtemp(prefix="panel-empty-")
    try:
        _es = M.usage_state(_eproj)
        check("the no-ledger stub has the same shape as a populated state",
              {"phaseBudgets", "bands", "taskMeta", "phaseTitles", "counts"}
              <= set(_es))
    finally:
        _sh.rmtree(_eproj, ignore_errors=True)

    # --- report export ------------------------------------------------------------
    # There is deliberately no path parameter on /report: the location is derived
    # from the project's own config, so there is nothing to traverse with. The
    # cases that RENDER a report moved to _panel_state.py (P12.3); what stays is
    # the route that reaches it and the button that opens it.
    #
    # F-P-8: this searched the WHOLE of this file's own source, so each literal
    # found the assertion line spelling it — the check matched itself, and renaming
    # the route in do_POST left the suite green while the routes it claims to guard
    # went unguarded. It reads the handler slices instead, which end at
    # `def _free_port` well before this line. That makes the DEFINITION ORDER
    # warning above this case's business too, and in the harder direction: a slice
    # that swallowed the rest of the file would swallow these literals as well, and
    # the check would go back to finding itself.
    check("the export route derives its path and takes no parameter — POST "
          "/api/report renders, GET /report serves what was written",
          'if path == "/api/report"' in _write_src
          and 'if path == "/report"' in _get_src
          and "paths = report_paths(project)" in _get_src)

    # --- v0.34 C5 (lv): live data - polling + fingerprint -----------------------
    # The fingerprint's own cases (stability, what moves it) live in
    # _panel_state.py; the out-of-band-write round trip is driven in
    # capture-screenshots.mjs --check. These pin the client wiring.
    check("lv: the fingerprint rides the runstatus PAYLOAD and stays OUT of "
          "runStatusKey - the D9 claim (the poll never has to refetch full "
          "state) stays literally true of the poll itself. gt: the GATE block "
          "is IN the key ({i,p,g}), so a fresh gate event repaints the card "
          "from the same payload",
          "function runStatusKey(rs){return JSON.stringify(rs&&{i:rs.index,"
          "p:rs.phases,g:rs.gate});}" in M.UI_HTML
          and isinstance(M._run_status(proj, M.read_config(proj), {})
                         .get("fingerprint"), str))

    # lifecycle: pidfile + stop/status (no socket needed)
    check("_pid_alive on this process is True", M._pid_alive(os.getpid()))
    check("_pid_alive on a bogus pid is False", not M._pid_alive(2147483000))
    M._write_pidfile(proj, {"pid": os.getpid(), "port": 1, "url": "http://x"})
    check("pidfile round-trips", (M._read_pidfile(proj) or {}).get("pid") == os.getpid())
    M._rm_pidfile(proj)
    check("status with no pidfile -> 0", M.status_panel(proj) == 0)
    check("stop with no pidfile -> 0", M.stop_panel(proj) == 0)
    # a stale pidfile (dead pid) is cleaned up, not treated as running
    M._write_pidfile(proj, {"pid": 2147483000, "port": 1, "url": "http://x"})
    check("stop clears a stale pidfile", M.stop_panel(proj) == 0
          and M._read_pidfile(proj) is None)

    # --- (i) the pidfile ignore rule is WRITTEN, not just claimed ---------------
    # The status line has said "it is gitignored; keep it that way" since the
    # panel learned to redact the URL - but nothing ever wrote the rule, and on
    # a real repo `git check-ignore` proved the token file one `git add .claude`
    # away from history. The plugin now ensures the rule itself.
    _gi = os.path.join(proj, ".claude", ".gitignore")
    try:
        os.remove(_gi)
    except OSError:
        pass
    M._write_pidfile(proj, {"pid": 1, "port": 1, "url": "http://x"})
    _gi_lines = []
    try:
        with open(_gi, encoding="utf-8") as fh:
            _gi_lines = [ln.strip() for ln in fh.read().splitlines()]
    except OSError:
        pass
    check("i1 writing the pidfile ensures a targeted .claude/.gitignore rule",
          "audit-panel.json" in _gi_lines)
    check("i2 the rule is targeted - nothing else in .claude is ignored",
          not any("*" == ln or "audit.config.json" in ln or "settings" in ln
                  for ln in _gi_lines))
    with open(_gi, "w", encoding="utf-8") as fh:
        fh.write("node_modules")            # pre-existing, NO trailing newline
    check("i3 appending to a newline-less .gitignore does not glue lines",
          M._ensure_pidfile_ignored(proj)
          and open(_gi, encoding="utf-8").read().splitlines()[0] == "node_modules")
    _n_before = open(_gi, encoding="utf-8").read().count("audit-panel.json")
    M._ensure_pidfile_ignored(proj)
    check("i4 re-ensuring is idempotent - no duplicate lines",
          open(_gi, encoding="utf-8").read().count("audit-panel.json")
          == _n_before == 1)
    _proj_bad = os.path.join(tmp, "badproj")
    os.makedirs(_proj_bad, exist_ok=True)
    with open(os.path.join(_proj_bad, ".claude"), "w", encoding="utf-8") as fh:
        fh.write("")                        # .claude is a FILE: rule unwritable
    check("i5 an unwritable rule reports False so callers warn instead of "
          "claiming", M._ensure_pidfile_ignored(_proj_bad) is False)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_panel_server.py --selftest\n")
    raise SystemExit(2)
