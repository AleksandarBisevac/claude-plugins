#!/usr/bin/env python3
"""
The cases for `_panel_write.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

TWENTY OF THESE LABELS BEGIN `"...and "`. Each is a sentence fragment that only
means anything beside the case above it ("a valid theme is written" / "...and the
panel now serves it, compiled"). They moved as PAIRS, adjacent and in order - the
whole block moved verbatim, so ordering was preserved by construction rather than
by care, and the migration proof compares the label list as an ORDERED sequence and
not only as a multiset.

THREE EXPRESSIONS COULD NOT MOVE LITERALLY.

  * `_src_of_this_file()` - the third copy of an `open(__file__)` helper (the others
    were in `panel-server.py` and `_panel_state.py`), every call site inside a
    `--selftest` and none in the product. All three copies are gone; this reads
    `_harness.module_source(M)`, which takes the module, so the "never imports
    panel-server" case parses the SUBJECT and not this file - which imports
    panel-server's own siblings and would have answered about the wrong module.
  * `os.path.join(_HERE, "panel-server.py")` - `_HERE` was `scripts/`; from `tests/`
    that path does not exist, so the read would have raised. It is
    `_loader.script_path("panel-server.py")` now - a joined `SCRIPTS_DIR` would keep
    working right up until `panel-server.py` moved into a subdirectory, and would
    then fail as a missing file rather than as the resolvable name it is. The 17
    exact alias lines it looks for keep their
    literal `"\n%s = _panel_write.%s\n"` form: that exact text is what catches a
    rename, and a fuzzier match would accept the very drift it exists to find.
  * `[n for n in _moved if n in globals()]` - INTROSPECTION about the subject
    ("is every name it took actually defined here"). This file defines none of the
    17, so the literal form fails loudly rather than silently; it is still asking
    the wrong module, and it is `hasattr(M, n)`.

`_manifest_io`, `_panel_state`, `_policy` and `_ui_theme` are imported here the way
`_panel_write.py` imports them, because these cases compare against those modules'
own objects - the shared journal memo case is an `is` comparison, so a second module
object would make it meaningless.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ado_parent as _adop                        # noqa: E402  (the no-declaration marker)
import _loader                                     # noqa: E402  (script_path: resolve a sibling by basename)
import _manifest_io as _mio                        # noqa: E402  (as _panel_write imports it)
import _panel_state                                # noqa: E402  (as _panel_write imports it)
import _policy                                     # noqa: E402  (as _panel_write imports it)
import _ui_theme as _theme                         # noqa: E402  (as _panel_write imports it)
import _panel_write as M                           # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- every POST endpoint refuses a body that is not an object --------------
    # A CLASS-LEVEL case, and derived from the SERVER'S OWN ROUTE TABLE rather than
    # from a list written here: a hand-list covers the endpoints somebody remembered
    # and the next one added is silently out of scope. That is not hypothetical -
    # `proposal_action` was the one endpoint of the seven that checked the type with
    # `body or {}` instead of `isinstance`, so a POST of `"x"` (valid JSON, wrong
    # type, truthy) reached `.get` and raised. `panel-server` wraps only the JSON
    # PARSE in a try/except, so the AttributeError took the request handler down
    # rather than being answered.
    import re
    import shutil as _sh0
    import tempfile as _tf0
    # Its OWN fixture, cleaned in its own `finally`. The suite builds a project
    # further down, and borrowing it would make this block depend on running after
    # it - the ordering trap a stray fixture already sprang once today.
    _pb_tmp = _tf0.mkdtemp(prefix="panel-write-body-")
    _pb_proj = os.path.join(_pb_tmp, "proj")
    os.makedirs(os.path.join(_pb_proj, ".claude"), exist_ok=True)
    _srv = os.path.join(_harness.SCRIPTS_DIR, "panel", "panel-server.py")
    with open(_srv, "r", encoding="utf-8") as _fh:
        _server_src = _fh.read()
    # THE FUNCTION NAMES ONLY, and deliberately not a path -> name map. Two things
    # were learned writing this:
    #
    #   * the optional `_panel_write.` prefix is not cosmetic. Six routes call the
    #     aliased name and ONE calls it through the module - and that was the
    #     endpoint with the defect. A pattern requiring a bare name found six and
    #     read as complete; a derived list is only as derived as its pattern, and
    #     the missing one is never the one you would have guessed.
    #   * pairing each name with the path above it needs a gap that cannot cross
    #     another route, and the lazy version silently paired `/api/state` with
    #     `write_config`. The paths add nothing to what is asserted here, so the
    #     honest fix is to stop capturing what cannot be paired correctly rather
    #     than to print a map that is wrong.
    _routes = re.findall(
        r'self\._json\(200,\s*(?:_panel_write\.)?([A-Za-z_]\w*)'
        r'\(project,\s*body\)\)', _server_src)
    check("pb0 the route table was READ, not assumed - %d POST endpoint(s) take a "
          "body. An empty list here would make every case below vacuous, which is "
          "the shape a regex that stopped matching produces" % (len(_routes),),
          len(_routes) >= 6, repr(_routes))
    _unresolved = [n for n in _routes if not callable(getattr(M, n, None))]
    check("pb1 ...and every one of them resolves in this module, so nothing the "
          "server routes is quietly skipped: %r" % (_unresolved,),
          _unresolved == [])
    _broken = []
    try:
        for _name in _routes:
            _fn = getattr(M, _name, None)
            if not callable(_fn):
                continue
            for _bad in ("a string", 42, True):
                try:
                    _got = _fn(_pb_proj, _bad)
                except Exception as _exc:
                    _broken.append((_name, _bad, type(_exc).__name__))
                    break
                if not (isinstance(_got, dict) and _got.get("ok") is False
                        and _got.get("findings")):
                    _broken.append((_name, _bad, repr(_got)[:40]))
                    break
    finally:
        _sh0.rmtree(_pb_tmp, ignore_errors=True)
    check("pb2 a TRUTHY non-object body is refused by every one of them with the "
          "same {ok:false, findings:[...]} shape the front end reads - a string, a "
          "number and a bool, because `body or {}` catches only the falsy ones and "
          "those three are exactly what it lets through: %r" % (_broken,),
          _broken == [])

    import shutil as _shutil
    import tempfile

    # The read side this write path shares state with, reached the way panel-server
    # reaches it, so a case about the shared journal memo is about the real thing.
    areas_state = _panel_state.areas_state
    journal_state = _panel_state.journal_state
    policy_state = _panel_state.policy_state

    tmp = tempfile.mkdtemp(prefix="panel-write-selftest-")
    proj = os.path.join(tmp, "proj")

    # --- th (F-P-6): the Appearance tab's two calls -------------------------
    _thp = tempfile.mkdtemp(prefix="audit-theme-write-")
    os.makedirs(os.path.join(_thp, ".claude"), exist_ok=True)
    _st = M.theme_state(_thp)
    check("th-w1 an unthemed project reports the default, and ships the "
          "vocabulary AND the default values the editor measures against",
          _st["source"] == "default" and _st["theme"] == {}
          and _st["default"] == _theme.DEFAULT_THEME
          and [g["key"] for g in _st["groups"]][:2] == ["brand", "status"]
          and "charts" in _st["locked"])
    _good = {"--accent": {"$value": "#7c3aed", "$dark": "#a78bfa"},
             "--radius": {"$value": "2px"}}
    _res = M.write_theme(_thp, {"theme": _good, "name": "midnight"})
    check("th-w2 a valid theme is written, and the change rows name the token "
          "AND the mode - the same dotted vocabulary every other save answers in",
          _res.get("ok")
          and any(r["field"].startswith("--accent") and "light" in r["field"]
                  for r in _res["applied"])
          and any(r["field"] == "--radius" for r in _res["applied"]))
    check("th-w3 ...and the panel now serves it, compiled",
          "--accent:#7c3aed" in _theme.token_css_for(_thp, M.read_config(_thp))[0]
          and M.theme_state(_thp)["source"] == "project")
    _bad = M.write_theme(_thp, {"theme": {"--accent": {"$value": "red;}body{x:y}",
                                                     "$dark": "#fff"}}})
    check("th-w4 a value that is not a value is refused BEFORE the write, and "
          "the file on disk is untouched", not _bad.get("ok")
          and _bad["findings"]
          and "--accent:#7c3aed" in _theme.token_css_for(_thp, M.read_config(_thp))[0])
    _dim = M.write_theme(_thp, {"theme": dict(
        _good, **{"--text": {"$value": "#dddddd", "$dark": "#222222"}})})
    check("th-w5 an unreadable CONTRAST is a warning and is written anyway - "
          "the reader's own panel is the reader's call",
          _dim.get("ok") and any("below" in w for w in _dim.get("warnings") or []))
    _rst = M.write_theme(_thp, {"reset": True})
    check("th-w6 reset REMOVES the file rather than writing a theme that "
          "happens to equal the default - the next reader sees 'no project "
          "theme', not 'a theme that says nothing'",
          _rst.get("ok")
          and not os.path.isfile(os.path.join(_thp, ".claude",
                                              _theme.THEME_FILENAME))
          and M.theme_state(_thp)["source"] == "default")
    _hist = M.write_theme(_thp, {"theme": _good,
                               "history": [{"t": i} for i in range(150)]})
    with open(os.path.join(_thp, ".claude", _theme.THEME_FILENAME),
              encoding="utf-8") as _fh:
        _raw = json.loads(_fh.read())
    check("th-w7 the undo trail rides the file so Undo survives a reload, and "
          "it is capped where it is WRITTEN - an unbounded trail in a file "
          "somebody commits grows without anyone deciding to keep it",
          _hist.get("ok") and len(_raw["history"]) == 100
          and _raw["history"][-1] == {"t": 149}
          and _raw["tokens"]["--accent"]["$value"] == "#7c3aed")
    # --- th: layout, Save as, switching (second increment) ------------------
    _lres = M.write_theme(_thp, {"theme": {}, "layout": {"density": "compact"}})
    check("th-w8 the density is saved with the theme and reaches the compiled "
          "sheet - one decision over eight spacing steps",
          _lres.get("ok")
          and any(r["field"] == "layout · density" and r["to"] == "compact"
                  for r in _lres["applied"])
          and "--sp-3:.8rem" in _theme.token_css_for(_thp, M.read_config(_thp))[0])
    # A CHANGE ROW MUST DESCRIBE A CHANGE. `_layout_changes` compared the raw
    # values while the row printed both through `or "comfortable"`, so saving a
    # theme with no density from a panel that sends the default explicitly emitted
    # `layout · density: comfortable -> comfortable`. Found by the differential
    # test that holds this function equal to the panel's `tLayChanges`, which
    # normalises both sides - so the dialog showed nothing and the save reported a
    # row, the exact mismatch `appliedDiff` exists to notice.
    check("th-w8b absent and 'comfortable' are the same density, so no row is "
          "emitted for the pair - a row whose from equals its to is a save "
          "reporting a change nobody made: %r"
          % (M._layout_changes({}, {"density": "comfortable", "order": {}}),),
          M._layout_changes({}, {"density": "comfortable", "order": {}}) == []
          and M._layout_changes({"density": "comfortable"}, {}) == [])
    check("th-w8c ...while a real density change is still one row, with both "
          "ends named",
          M._layout_changes({}, {"density": "spacious"})
          == [{"target": "theme", "field": "layout · density",
               "from": "comfortable", "to": "spacious"}])
    # And the row can never be a no-op by construction, over every pair the
    # densities allow. The check on the check: a fix that returned [] always would
    # pass th-w8b and fail this.
    _dens = [None, "comfortable", "compact", "spacious"]
    _pairs = [(b, a) for b in _dens for a in _dens]
    _noop = [(b, a) for b, a in _pairs
             for r in M._layout_changes({} if b is None else {"density": b},
                                        {} if a is None else {"density": a})
             if r["from"] == r["to"]]
    _rows = sum(len(M._layout_changes({} if b is None else {"density": b},
                                      {} if a is None else {"density": a}))
                for b, a in _pairs)
    check("th-w8d no density pair produces a row whose from equals its to, over "
          "all %d pairs, and %d real rows were produced (noop: %r)"
          % (len(_pairs), _rows, _noop),
          not _noop and _rows >= 6)

    check("th-w9 ...and it comes back in the state the editor reads",
          M.theme_state(_thp)["layout"].get("density") == "compact"
          and M.theme_state(_thp)["densities"] == ["comfortable", "compact",
                                                 "spacious"])
    _ores = M.write_theme(_thp, {"theme": {},
                               "layout": {"density": "compact",
                                          "order": {"over": ["ready", "phases"]}}})
    check("th-w10 a card order is a decision, and reads as one in the change "
          "rows rather than as JSON",
          _ores.get("ok")
          and any(r["field"] == "layout · order · over" and "ready" in str(r["to"])
                  for r in _ores["applied"]))
    check("th-w11 an invalid density is refused with the theme it came in with",
          not M.write_theme(_thp, {"theme": {},
                                 "layout": {"density": "roomy"}}).get("ok"))
    _sa = M.write_theme(_thp, {"theme": {"--accent": {"$value": "#111111",
                                                    "$dark": "#eeeeee"}},
                             "saveAs": "Midnight Blue"})
    check("th-w12 Save as writes a NAMED copy and points the config at it - "
          "'keep this one and wear it' is two writes, and half of it would be a "
          "half-done state",
          _sa.get("ok") and _sa.get("savedAs") == "Midnight Blue"
          and os.path.isfile(os.path.join(_thp, ".claude", "themes",
                                          "midnight-blue.json"))
          and (M.read_config(_thp).get("ui") or {}).get("theme")
          == ".claude/themes/midnight-blue.json"
          and M.theme_state(_thp)["theme"]["--accent"]["$value"] == "#111111")
    check("th-w13 the saved themes are listed beside the built-in, from disk",
          [t["name"] for t in M.theme_state(_thp)["saved"]][0] == "slate-teal"
          and any(t["name"] == "midnight-blue"
                  for t in M.theme_state(_thp)["saved"]))
    _use = M.write_theme(_thp, {"use": "slate-teal"})
    check("th-w14 switching to the built-in is a one-key config edit, and the "
          "saved file is left where it is",
          _use.get("ok")
          and not (M.read_config(_thp).get("ui") or {}).get("theme")
          and os.path.isfile(os.path.join(_thp, ".claude", "themes",
                                          "midnight-blue.json")))
    _shutil.rmtree(_thp, ignore_errors=True)

    # config write: valid then invalid
    res = M.write_config(proj, {"trivialLineThreshold": 40})
    check("write valid config ok", res["ok"] and os.path.isfile(M._config_path(proj)))
    check("config on disk matches", M.read_config(proj).get("trivialLineThreshold") == 40)
    res = M.write_config(proj, {"trivialLineThreshold": 0})
    check("write invalid config rejected (not written)",
          not res["ok"] and M.read_config(proj).get("trivialLineThreshold") == 40)

    # manifest + composition patch
    mpath = M._manifest_path(proj, M.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    manifest = {"meta": {"version": 2, "reviewSkill": None},
                "phases": [{"id": "P1", "title": "P", "status": "pending",
                            "review": {"model": "sonnet"},
                            "tasks": [{"id": "P1.1", "title": "T",
                                       "status": "pending"}]}]}
    M._atomic_write_json(mpath, manifest)

    res = M.apply_composition(proj, {"meta": {"reviewSkill": "user-skill"},
                                   "tasks": {"P1.1": {"skills": ["user-skill"], "model": "opus"}}})
    check("composition patch applied", res["ok"])
    saved = M._read_json(mpath)
    check("reviewSkill written", saved["meta"]["reviewSkill"] == "user-skill")
    check("task skills written", saved["phases"][0]["tasks"][0]["skills"] == ["user-skill"])
    check("task model written", saved["phases"][0]["tasks"][0]["model"] == "opus")
    check("non-composition data preserved",
          saved["phases"][0]["title"] == "P" and saved["meta"]["version"] == 2)

    # structural edits refused
    res = M.apply_composition(proj, {"phases": {"P1": {"title": "HACKED"}}})
    check("structural phase edit refused", not res["ok"] and
          M._read_json(mpath)["phases"][0]["title"] == "P")
    res = M.apply_composition(proj, {"bugs": []})
    check("unknown patch section refused", not res["ok"])
    res = M.apply_composition(proj, {"tasks": {"P9.9": {"model": "x"}}})
    check("unknown task id refused", not res["ok"])

    # a patch that would make the manifest invalid is rejected + not written
    res = M.apply_composition(proj, {"tasks": {"P1.1": {"skills": "notalist"}}})
    check("bad skills type refused", not res["ok"])

    # v0.37 B1: null is a WRITABLE value — the chips UI's "none applies" — and
    # it must land in the FILE as null (the opt-out that stops the area
    # fallback), not be refused as a bad type or flattened to [].
    res = M.apply_composition(proj, {"tasks": {"P1.1": {"skills": None}}})
    _t_null = M._read_json(mpath)["phases"][0]["tasks"][0]
    check("skills null written - the opt-out lands in the file as null",
          res["ok"] and "skills" in _t_null and _t_null["skills"] is None)
    check("...and its change row reads list -> null through the view's own "
          "three-state normaliser",
          any(r.get("field") == "skills" and r.get("from") == ["user-skill"]
              and r.get("to") is None for r in res.get("applied") or []))
    res = M.apply_composition(proj, {"tasks": {"P1.1": {"skills": None}}})
    check("null on an already-opted-out task is unchanged, not a change - "
          "null and [] are two values, not one",
          res["ok"] and res.get("unchanged") is True)
    res = M.apply_composition(proj, {"tasks": {"P1.1": {"skills": []}}})
    _t_back = M._read_json(mpath)["phases"][0]["tasks"][0]
    check("clearing the opt-out back to [] round-trips, with the row null -> []",
          res["ok"] and _t_back["skills"] == []
          and any(r.get("field") == "skills" and r.get("from") is None
                  and r.get("to") == [] for r in res.get("applied") or []))
    # Put the fixture back the way the cases below expect it.
    M.apply_composition(proj, {"tasks": {"P1.1": {"skills": ["user-skill"]}}})

    # lock respected
    open(mpath + ".lock", "w").close()
    res = M.apply_composition(proj, {"meta": {"reviewSkill": "x"}})
    check("write refused while locked", not res["ok"] and res.get("locked"))
    os.remove(mpath + ".lock")

    # --- the SHARDED layout ---------------------------------------------------
    # Everything above ran on a single-file manifest, and that is exactly why this
    # was broken in the field for so long: this repo's own manifest and the shipped
    # example are both sharded, and there the writer read the raw INDEX. Its phases
    # are stubs with no tasks in them, so every task edit was refused as "unknown
    # task" for a task the panel had just listed, phase edits went into a stub the
    # next load discards, and a meta-only save died on validator findings about
    # stubs missing fields stubs are not supposed to have.
    _sproj = tempfile.mkdtemp(prefix="panel-sharded-")
    try:
        M._atomic_write_json(M._config_path(_sproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _sm = M._manifest_path(_sproj, M.read_config(_sproj))
        os.makedirs(os.path.dirname(_sm), exist_ok=True)
        _full = {"meta": {"version": 3, "reviewSkill": None},
                 "phases": [
                     {"id": "P1", "title": "One", "status": "pending",
                      "review": {"model": "sonnet"},
                      "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                     {"id": "P2", "title": "Two", "status": "pending",
                      "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]}
        _mio.save_sharded(_sm, _full)
        _idx = M._read_json(_sm)
        check("sharded fixture really is sharded", _mio.is_sharded(_idx))
        _p2shard = os.path.join(os.path.dirname(_sm), _idx["phases"][1]["shard"])
        _p2_before = open(_p2shard, "rb").read()

        res = M.apply_composition(_sproj, {
            "meta": {"reviewSkill": "sk"},
            "phases": {"P1": {"reviewModel": "opus"}},
            "tasks": {"P1.1": {"model": "haiku", "skills": ["a"]}}})
        check("sharded: a task the panel listed can actually be edited", res["ok"])
        check("sharded: the response names the layout it wrote",
              res.get("layout") == "sharded")
        _re = _mio.load_manifest(_sm)
        _p1 = [p for p in _re["phases"] if p["id"] == "P1"][0]
        check("sharded: task model + skills survive a reload",
              _p1["tasks"][0].get("model") == "haiku"
              and _p1["tasks"][0].get("skills") == ["a"])
        check("sharded: per-phase review model lands in the shard, not the stub "
              "that _merge_phase throws away",
              _p1.get("review", {}).get("model") == "opus")
        check("sharded: meta lands on the index", _re["meta"]["reviewSkill"] == "sk")
        # The whole point of shards is that two phase branches never touch the same
        # file. A writer that rewrites every shard would renormalize files nobody
        # edited and manufacture exactly the conflicts the layout exists to avoid.
        check("sharded: an untouched phase's shard is not rewritten at all",
              open(_p2shard, "rb").read() == _p2_before)
        check("sharded: only the touched files are reported written",
              sorted(res.get("written") or []) == sorted(
                  [os.path.relpath(os.path.join(os.path.dirname(_sm),
                                                _idx["phases"][0]["shard"]), _sproj),
                   os.path.relpath(_sm, _sproj)]))
        # A meta-only save used to fail with ~22 findings about phase stubs.
        res = M.apply_composition(_sproj, {"meta": {"reviewSkill": "sk2"}})
        check("sharded: a meta-only save is not blocked by findings about stubs",
              res["ok"] and not res.get("findings"))
        check("sharded: unknown task still refused", not M.apply_composition(
            _sproj, {"tasks": {"P9.9": {"model": "x"}}})["ok"])
    finally:
        _shutil.rmtree(_sproj, ignore_errors=True)

    # --- v0.28: the areas registry over HTTP ------------------------------------
    # The GET cases (registry as stored, tags a phase uses, the typo case) moved to
    # _panel_state.py (P12.3); the WRITE path is what is exercised here.
    # `meta` lives on the INDEX in a sharded manifest, so a registry save must
    # touch the index and nothing else. That is the whole reason this goes through
    # apply_composition rather than writing the file itself: a second writer here
    # would be a second implementation of the targeted write-back, and the way it
    # would fail is by rewriting shards on a branch nobody is on.
    _aproj = tempfile.mkdtemp(prefix="panel-areas-")
    try:
        M._atomic_write_json(M._config_path(_aproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _am = M._manifest_path(_aproj, M.read_config(_aproj))
        os.makedirs(os.path.dirname(_am), exist_ok=True)
        os.makedirs(os.path.join(_aproj, "services", "api"), exist_ok=True)
        _mio.save_sharded(_am, {
            "meta": {"version": 3,
                     "areas": {"api": {"root": "services/api", "description": "d",
                                       "reviewSkill": "backend-review"},
                               "unused": {"root": "services/api"}}},
            "phases": [
                {"id": "P1", "title": "One", "status": "pending", "area": "api",
                 "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                {"id": "P2", "title": "Two", "status": "pending", "area": "apu",
                 "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]})
        _aidx = M._read_json(_am)
        _ashard = os.path.join(os.path.dirname(_am), _aidx["phases"][0]["shard"])
        _ashard_before = open(_ashard, "rb").read()

        _bad = M.write_areas(_aproj, {"areas": {"api": "services/api"}})
        check("areas PUT refuses a malformed registry, naming the entry",
              not _bad["ok"] and any("must be an object" in f
                                     for f in _bad["findings"]))
        check("...and a refused areas PUT wrote nothing",
              M._read_json(_am)["meta"]["areas"].get("api") == {
                  "root": "services/api", "description": "d",
                  "reviewSkill": "backend-review"})
        # The shape is checked BEFORE the manifest is opened, and this is the case
        # that proves it rather than merely restating the validator: with a
        # manifest that cannot be parsed at all, the writer can only report the
        # parse error — so a caller who sent a bad body would be told nothing about
        # it, fix the manifest, and hit the same wall a second time.
        _saved = open(_am, "rb").read()
        with open(_am, "wb") as _fh:
            _fh.write(b"{ this is not json")
        _both = M.write_areas(_aproj, {"areas": {"api": "services/api"}})
        check("a malformed registry is named even when the manifest itself cannot "
              "be read - one round trip, both problems",
              not _both["ok"] and any("must be an object" in f
                                      for f in _both["findings"]))
        check("...while a WELL-formed registry over an unreadable manifest reports "
              "the manifest, so the two failures are never confused",
              any("cannot parse manifest" in f for f in
                  M.write_areas(_aproj, {"areas": {"api": {"root": "x"}}})["findings"]))
        with open(_am, "wb") as _fh:
            _fh.write(_saved)

        _res = M.write_areas(_aproj, {"areas": {"api": {"root": "services/api"},
                                              "web": {"root": "services/api"}}})
        check("areas PUT writes through the one composition writer", _res["ok"])
        check("areas PUT echoes the change as a row the confirm flow can print",
              [r["field"] for r in _res.get("applied") or []] == ["areas"])
        check("areas PUT touches the INDEX only - meta lives there, and rewriting "
              "a phase shard would manufacture a conflict on a branch nobody is on",
              _res.get("written") == [os.path.relpath(_am, _aproj)]
              and open(_ashard, "rb").read() == _ashard_before)
        _after = M._read_json(_am)["meta"]["areas"]
        check("areas PUT replaces the registry wholesale, so dropping an area is "
              "an ordinary edit rather than something the API cannot express",
              set(_after) == {"api", "web"})
        check("...and the dropped area's phase tag now reads unregistered",
              {t["tag"]: t["registered"] for t in areas_state(_aproj)["tags"]}
              == {"api": True, "apu": False, "web": True})
        check("areas PUT accepts the bare registry as well as {areas: ...} - both "
              "readings of 'PUT the areas' are reasonable",
              M.write_areas(_aproj, {"api": {"root": "services/api"}})["ok"])
        _res = M.write_areas(_aproj, {"areas": {}})
        check("areas PUT can empty the registry", _res["ok"]
              and M._read_json(_am)["meta"]["areas"] == {})
        check("a save that changes nothing still writes nothing",
              M.write_areas(_aproj, {"areas": {}}).get("unchanged") is True)
        _st2 = areas_state(_aproj)
        check("with no registry the tags list is still the truth about the phases",
              [t["tag"] for t in _st2["tags"]] == ["api", "apu"]
              and not any(t["registered"] for t in _st2["tags"]))
        _res = M.write_areas(_aproj, {"areas": {"api": {"root": "services/gone"}}})
        check("a root that is not on disk is written and WARNED about, not "
              "refused - the doctor reports it; the panel does not veto it",
              _res["ok"] and not areas_state(_aproj)["tags"][0]["rootExists"])
    finally:
        _shutil.rmtree(_aproj, ignore_errors=True)

    # --- connector v2: meta.ado over HTTP ---------------------------------------
    # The `areas` pattern applied to the second API-only meta key: validated by
    # the SAME check_ado_meta the CLI validator runs (one front door — the panel
    # and the CLI cannot disagree), written through the one composition writer,
    # index-only on a sharded manifest, DOTTED presence-aware change rows so the
    # card's confirm list and the server's echo are two readings of one edit.
    _oproj = tempfile.mkdtemp(prefix="panel-ado-")
    try:
        M._atomic_write_json(M._config_path(_oproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _om = M._manifest_path(_oproj, M.read_config(_oproj))
        os.makedirs(os.path.dirname(_om), exist_ok=True)
        _mio.save_sharded(_om, {
            "meta": {"version": 3},
            "phases": [{"id": "P1", "title": "One", "status": "pending",
                        "tasks": [{"id": "P1.1", "title": "T1",
                                   "status": "pending"}]}]})
        _oidx = M._read_json(_om)
        _oshard = os.path.join(os.path.dirname(_om),
                               _oidx["phases"][0]["shard"])
        _oshard_before = open(_oshard, "rb").read()

        _bad = M.write_ado(_oproj, {"ado": {"organization": "o", "project": "p",
                                          "sprint": {"mode": "current"}}})
        check("ado PUT refuses through the validator's own front door "
              "(check_ado_meta), naming the defect",
              not _bad["ok"] and any("sprint: requires a non-empty 'team'" in f
                                     for f in _bad["findings"]))
        check("...and a refused ado PUT wrote nothing",
              "ado" not in M._read_json(_om)["meta"])
        _res = M.write_ado(_oproj, {"ado": {"organization": "o", "project": "p",
                                          "enabled": False}})
        check("ado PUT writes through the one composition writer, INDEX only",
              _res["ok"]
              and _res.get("written") == [os.path.relpath(_om, _oproj)]
              and open(_oshard, "rb").read() == _oshard_before
              and M._read_json(_om)["meta"]["ado"]["enabled"] is False)
        check("ado PUT echoes DOTTED rows, one per leaf that moved",
              sorted(r["field"] for r in _res.get("applied") or [])
              == ["ado.enabled", "ado.organization", "ado.project"])
        _res2 = M.write_ado(_oproj, {"ado": {"organization": "o",
                                           "project": "p"}})
        check("dropping a key is presence-aware - enabled deleted draws its "
              "own row (deleting the key is how 'use the default' is written)",
              _res2["ok"]
              and [r["field"] for r in _res2.get("applied") or []]
              == ["ado.enabled"]
              and "enabled" not in M._read_json(_om)["meta"]["ado"])
        check("an ado save that changes nothing writes nothing",
              M.write_ado(_oproj, {"ado": {"organization": "o", "project": "p"}}
                        ).get("unchanged") is True)
        check("ado PUT accepts the bare object as well as {ado: ...}",
              M.write_ado(_oproj, {"organization": "o2", "project": "p"})["ok"]
              and M._read_json(_om)["meta"]["ado"]["organization"] == "o2")
        _res3 = M.write_ado(_oproj, {"ado": None})
        check("ado: null is a legal PUT - the connector reads off; item links "
              "are sync's records, not this config's, and stay",
              _res3["ok"] and M._read_json(_om)["meta"]["ado"] is None)
        # `meta.ado.fields` has no CONTROL on the connector card yet, and this is
        # the pair of cases that says the SERVER half is nonetheless finished:
        # the endpoint writes the key and refuses a bad one through the same
        # front door the CLI uses. Without them "the panel supports it" would
        # rest on `write_ado` replacing the object wholesale, which is a reading
        # of the code rather than a fact about the endpoint.
        _tpl = {"Task": {"Microsoft.VSTS.Common.Activity": "Development"}}
        _resf = M.write_ado(_oproj, {"ado": {"organization": "o", "project": "p",
                                             "fields": _tpl}})
        # .get, not indexing: the mutation this case is for DROPS the key, and
        # a KeyError would take the suite's unprinted output with it instead of
        # naming the one thing that broke.
        _stored = (M._read_json(_om)["meta"].get("ado") or {}).get("fields")
        check("ado PUT writes meta.ado.fields, which no control on the card "
              "edits - the endpoint is the whole server side of that key: %r"
              % (_stored,),
              _resf["ok"] and _stored == _tpl)
        _badf = M.write_ado(_oproj, {"ado": {"organization": "o", "project": "p",
                                             "fields": {"Task": {
                                                 "System.Parent": 7}}}})
        check("...and a template naming a readOnly field is refused there too, "
              "through check_ado_meta rather than a second opinion: %r"
              % (_badf.get("findings"),),
              not _badf["ok"]
              and len([f for f in _badf.get("findings") or [] if "readOnly" in f]) == 1
              and (M._read_json(_om)["meta"].get("ado") or {}).get("fields")
              == _tpl)
        # THE DOTTED ROW IS THE RIGHT ROW, and this case is what makes that a
        # decision rather than an accident. An ADO reference name carries dots,
        # so one template leaf flattens to `ado.fields.<type>.<reference name>`
        # - a path with more segments than the object has levels. It is left
        # exactly so: the row's `field` is a PATH into the file and nothing ever
        # splits it back, while shortening it to the last segment would print a
        # `Custom.Severity` and a `Microsoft.VSTS.Common.Severity` identically -
        # two manifest keys, one row, which is the collision `_ado_fields._norm`
        # exists to refuse. The hazard dots really do carry is in `setPath` /
        # `delPath`, which DO split, and the answer there is not to use them.
        _resd = M.write_ado(_oproj, {"ado": {
            "organization": "o", "project": "p",
            "fields": {"Task": {"Microsoft.VSTS.Common.Activity": "Deployment",
                                "Microsoft.VSTS.Scheduling.OriginalEstimate": 4}}}})
        check("adf1 a template key carrying dots flattens to ONE row per LEAF, "
              "keeping the reference name whole - a row per dotted segment "
              "would describe a document that does not exist: %r"
              % (sorted(r["field"] for r in _resd.get("applied") or []),),
              _resd["ok"]
              and sorted(r["field"] for r in _resd.get("applied") or [])
              == ["ado.fields.Task.Microsoft.VSTS.Common.Activity",
                  "ado.fields.Task.Microsoft.VSTS.Scheduling.OriginalEstimate"])
        check("adf2 ...and the key round-trips unshredded, with its value's "
              "TYPE intact: an estimate that came back as the string \"4\" "
              "would be refused by a board that requires a number",
              (M._read_json(_om)["meta"].get("ado") or {}).get("fields")
              == {"Task": {"Microsoft.VSTS.Common.Activity": "Deployment",
                           "Microsoft.VSTS.Scheduling.OriginalEstimate": 4}})
    finally:
        _shutil.rmtree(_oproj, ignore_errors=True)

    # --- v0.30: the capability policy ------------------------------------------
    # The rule-listing cases that are a pure function of the block, and the
    # enforcement-marker cases, moved to _panel_state.py (P12.3).
    # The resolution lives in _policy and is exercised there. What is checked here
    # is that this endpoint SHOWS what the guard hook will DO — same function, same
    # active areas — and that the one writer refuses what the validator refuses.
    # The GET half stays beside the PUT half rather than following the rest of the
    # read side: every one of these rows is read back AFTER a write_policy call,
    # off the fixture that write built, and splitting them would mean two copies of
    # that fixture asserting two halves of one round trip.
    _pproj = tempfile.mkdtemp(prefix="panel-policy-")
    try:
        os.makedirs(os.path.join(_pproj, ".claude"), exist_ok=True)
        # The capabilities this fixture resolves verdicts for are CREATED here,
        # project-local, rather than whatever `discover` happens to find on the
        # machine. A check that names `code-reviewer` because this laptop has one
        # installed is a check about the laptop: green here, absent on CI, and
        # silently vacuous either way.
        os.makedirs(os.path.join(_pproj, ".claude", "agents"), exist_ok=True)
        for _name in ("code-reviewer", "random-agent", "audit-executor"):
            with open(os.path.join(_pproj, ".claude", "agents", _name + ".md"),
                      "w", encoding="utf-8") as _fh:
                _fh.write("---\nname: %s\ndescription: fixture\n---\n" % _name)
        M._atomic_write_json(os.path.join(_pproj, ".mcp.json"),
                           {"mcpServers": {"prod-db": {"command": "x"}}})
        M._atomic_write_json(M._config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _pm = M._manifest_path(_pproj, M.read_config(_pproj))
        os.makedirs(os.path.dirname(_pm), exist_ok=True)
        M._atomic_write_json(_pm, {
            "meta": {"version": 2, "areas": {"api": {"root": "."}}},
            "phases": [
                {"id": "P1", "title": "One", "status": "in_progress", "area": "api",
                 "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                {"id": "P2", "title": "Two", "status": "pending", "area": "web",
                 "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]})

        _ps = policy_state(_pproj)
        check("policy GET reports the shipped block as inert, so a repo that never "
              "opted in is not shown a governance surface that governs nothing",
              _ps["active"] is False and _ps["stored"] is None
              and _ps["policy"]["skills"]["default"] == "allow")
        check("policy GET resolves a verdict for every kind, even inert",
              set(_ps["resolved"]) == set(_policy.KINDS))
        check("policy GET reports the ACTIVE areas, which is what scopes an area "
              "rule - and only the phases with work in progress count",
              _ps["activeAreas"] == ["api"] and "web" in _ps["areas"])

        _bad = M.write_policy(_pproj, {"skills": {"default": "denied"}})
        check("policy PUT refuses a misspelled default in the policy's own words",
              not _bad["ok"] and any("policy.skills.default" in f
                                     for f in _bad["findings"]))
        check("...and a refused policy PUT wrote nothing",
              M.read_config(_pproj).get("policy") is None)
        # The policy is checked BEFORE the config is assembled, and this is the case
        # that proves it rather than restating the validator: with an unrelated
        # finding already in the file, a writer that only validated the assembled
        # config would answer with both — and the caller, who sent a policy, would
        # be told about a threshold they did not touch.
        M._atomic_write_json(M._config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json",
                            "trivialLineThreshold": 0})
        _only = M.write_policy(_pproj, {"skills": {"default": "denied"}})
        check("a bad policy is reported ALONE, even when the config it would join "
              "already has a finding of its own",
              not _only["ok"]
              and all(f.startswith("policy.") for f in _only["findings"]),
              )
        M._atomic_write_json(M._config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _req = M.write_policy(_pproj, {"agents": {"deny": ["audit:*"]}})
        check("policy PUT refuses a policy denying audit's own components - the "
              "line would not take effect, so saving it would leave a file that "
              "says something untrue",
              not _req["ok"] and any("not deniable" in f for f in _req["findings"]))
        check("...and that refusal is the VALIDATOR's, so the panel and the CLI "
              "cannot disagree about what is saveable",
              any("not deniable" in f for f in
                  M._cores()[1].validate_config({"policy": {"agents": {
                      "deny": ["audit:*"]}}})[0]))

        _res = M.write_policy(_pproj, {"skills": {"default": "deny",
                                                "allow": ["dataviz"]}})
        check("policy PUT writes through the one config writer", _res["ok"])
        check("...which echoes the change as rows the confirm flow can print",
              any(r["field"].startswith("policy.")
                  for r in _res.get("applied") or []),
              )
        check("...and reports the journal outcome like every other save",
              "journaled" in _res)
        check("the block landed in the config file itself",
              M.read_config(_pproj)["policy"]["skills"]["default"] == "deny")
        check("a save that changes nothing writes nothing",
              M.write_policy(_pproj, {"skills": {"default": "deny",
                                               "allow": ["dataviz"]}}
                           ).get("unchanged") is True)
        check("policy PUT accepts {policy: ...} as well as the bare block",
              M.write_policy(_pproj, {"policy": {"skills": {"default": "allow"}}})["ok"])
        check("policy PUT can empty the block back to inert",
              M.write_policy(_pproj, {})["ok"]
              and policy_state(_pproj)["active"] is False)

        # The preview IS the guard's answer. Asserted against _policy.resolve rather
        # than against a second expectation written here: a check whose oracle is a
        # copy of the thing under test proves only that two copies agree.
        # `deny: ["*"]` would be refused by the writer — it matches audit's own
        # names — so the deny-everything shape is written the way the validator
        # accepts it: a default of deny, which `resolve` reaches only after the
        # required check has already let audit's own through.
        M.write_policy(_pproj, {"skills": {"default": "deny", "allow": ["dataviz"]},
                              "agents": {"default": "deny",
                                         "areas": {"api": {"allow": ["code-*"]},
                                                   "web": {"allow": ["never-*"]}}}})
        _ps = policy_state(_pproj)
        _pol = _policy.policy_cfg(M.read_config(_pproj))
        _rows = _ps["resolved"]["agents"]
        # `.get`, not `[...]`: a row that is missing is exactly what a broken
        # endpoint returns, and a KeyError exits 1 without naming which check
        # noticed — indistinguishable from a suite that crashed for another reason.
        _by_pre = lambda rows: {r["name"]: r for r in rows}       # noqa: E731
        check("every resolved row is exactly what the guard hook would decide, "
              "including the basis it would print",
              bool(_rows) and all(
                  r["verdict"] == _policy.resolve(
                      _pol, "agents", r["name"], active_tags=["api"])["verdict"]
                  and r["basis"] == _policy.resolve(
                      _pol, "agents", r["name"], active_tags=["api"])["basis"]
                  for r in _rows))
        check("audit's own agent is marked required and allowed through a policy "
              "that denies everything - and it is the FIXTURE's copy, not one this "
              "machine happens to have installed",
              (_by_pre(_rows).get("audit-executor") or {}).get("required") is True
              and (_by_pre(_rows).get("audit-executor") or {}).get("verdict")
              == "allow")
        check("somebody else's agent under the same policy resolves to a violation",
              (_by_pre(_rows).get("random-agent") or {}).get("verdict")
              == "violation")
        # The preview must apply the ACTIVE areas, not merely the project-wide
        # rules: `api` has a phase in progress and `web` does not, so one area's
        # allow list is in force and the other's is not. Resolved with no active
        # areas at all, every one of these rows would read "violation".
        _by = _by_pre(_rows)
        check("an area's allow list is applied because that area has work in "
              "progress, and the row says which area answered",
              (_by.get("code-reviewer") or {}).get("verdict") == "allow"
              and (_by.get("code-reviewer") or {}).get("area") == "api",
              )
        check("...while an area with nothing running grants nothing",
              all(r["area"] != "web" for r in _rows))
        check("an MCP row is a STAND-IN for the whole server and says so, since "
              "what is discoverable is a server name and a policy matches tool "
              "names - and there IS a row, so this is not vacuously true",
              "mcp__prod-db__*" in [r["name"] for r in _ps["resolved"]["mcp"]]
              and all(r["standIn"] and r["name"].startswith("mcp__")
                      and r["name"].endswith("__*")
                      for r in _ps["resolved"]["mcp"]))

        # --- panel c7: what the switchboard needs beyond the verdicts ----------
        # The switches on that form can only write EXACT names. Everything else a
        # policy may legally contain — a glob, a rule for something nobody has
        # installed, a rule for a dormant area — is invisible to them, and the PUT
        # replaces the block WHOLESALE. A rule the form cannot show is therefore a
        # rule it would silently destroy, which is why the raw block travels too.
        _rules = _ps["rules"]["agents"]
        check("every pattern in the block is reported, in the order resolve reads "
              "them: deny before allow, project before area",
              [(r["scope"], r["list"], r["pattern"]) for r in _rules]
              == [("api", "allow", "code-*"), ("web", "allow", "never-*")])
        # Counted against `_policy.matches` over the rows this endpoint served, not
        # against a number written here: the machine running this has its own agents
        # installed, and "code-* matches exactly one" would be a claim about the
        # laptop — true here, false on CI, and vacuous either way.
        _codes = [r["name"] for r in _rows if _policy.matches(r["name"], ["code-*"])]
        check("...and each says what it matches TODAY, through the same matcher the "
              "guard matches with",
              "code-reviewer" in _codes
              and [r["n"] for r in _rules if r["pattern"] == "code-*"]
              == [len(_codes)])
        # A rule that matches nothing is the one a table of capabilities cannot
        # show at all, and the one most likely to be a typo. Dropping it here would
        # be the form quietly deleting it on the next save.
        check("a pattern matching nothing installed is still listed, and says it "
              "matches nothing rather than being left out",
              [r["n"] for r in _rules if r["pattern"] == "never-*"] == [0])

        # Every area a rule can be aimed at, and whether it decides anything today.
        _ainfo = {a["tag"]: a for a in _ps["areaInfo"]}
        check("the area columns cover every tag a rule could name, and mark which "
              "are live - an area rule is inert until that area has work in "
              "progress, and a column that does not say so is a trap",
              sorted(_ainfo) == _ps["areas"]
              and _ainfo["api"]["active"] is True
              and _ainfo["web"]["active"] is False)
        check("...and say which of them the registry actually knows, since a rule "
              "may legitimately be written for a free-text tag",
              _ainfo["api"]["registered"] is True
              and _ainfo["web"]["registered"] is False)

    finally:
        _shutil.rmtree(_pproj, ignore_errors=True)

    check("meta.areas is on the composition allow-list, so it goes through the "
          "writer that locks, validates and journals", "areas" in M._META_KEYS
          and M._reject_unknown({"meta": {"areas": {}}}) is None)
    check("...and nothing else was let in with it",
          M._reject_unknown({"meta": {"phases": {}}}) is not None)

    # --- c6: what a save would change, who is making it, and the record of it ---
    # The rows the confirm dialog lists ARE the rows the server echoes as
    # `applied`; the client compares the two. Everything below is about those two
    # lists being computable from the same pair of values. (The dialog's own half —
    # the JS that builds them — is pinned in panel-server, beside UI_HTML.)
    check("a leaf path per row, not a block per row",
          M._flat_paths({"usage": {"bands": {"highUSD": 1}}, "enforce": True})
          == {"usage.bands.highUSD": 1, "enforce": True})
    check("an empty object is a leaf, so emptying a block is still a change",
          M._flat_paths({"usage": {}}) == {"usage": {}})
    check("a list is a leaf: a changed list is one row, not one row per element",
          M._flat_paths({"secretPatterns": {"extra": ["a", "b"]}})
          == {"secretPatterns.extra": ["a", "b"]})
    # The WHOLE path, not the leaf's own name: `highUSD` alone would not say which
    # of the settings called that had moved.
    check("config diff names the dotted path and both sides",
          M._config_changes({"usage": {"bands": {"highUSD": 1}}},
                          {"usage": {"bands": {"highUSD": 2}}})
          == [{"target": "config", "field": "usage.bands.highUSD",
               "from": 1, "to": 2}])
    check("config diff: an untouched key is not a change",
          M._config_changes({"a": 1, "b": 2}, {"a": 1, "b": 3})
          == [{"target": "config", "field": "b", "from": 2, "to": 3}])
    # Deleting a key is how "use the default" is written, and a key whose value was
    # already null would vanish from a diff that only compared .get() results.
    check("config diff: removing a null key is still a change",
          [r["field"] for r in M._config_changes({"x": None}, {})] == ["x"])

    _cm = _mio.load_manifest(mpath)
    check("composition diff reads `from` off the manifest, not off the patch",
          M._composition_changes(_cm, {"tasks": {"P1.1": {"model": "haiku"}}})
          == [{"target": "P1.1", "field": "model",
               "from": "opus", "to": "haiku"}])
    check("composition diff drops a field set back to what it already held",
          M._composition_changes(_cm, {"tasks": {"P1.1": {"model": "opus"}}}) == [])
    check("composition diff covers meta and the per-phase review model",
          [(r["target"], r["field"]) for r in M._composition_changes(_cm, {
              "meta": {"reviewSkill": "other"},
              "phases": {"P1": {"reviewModel": "haiku"}}})]
          == [("meta", "reviewSkill"), ("P1", "review model")])
    check("composition diff skips an unknown id (the patch refuses it a line later)",
          M._composition_changes(_cm, {"tasks": {"P9.9": {"model": "x"}}}) == [])
    # The `from` side has to be the value the FORM shows. _composition_view turns a
    # missing skills key into [], so reading the raw None here would make adding a
    # skill read as `null -> [a]` on the server and `[] -> [a]` in the browser, and
    # the panel would warn about a disagreement that is only a normalisation.
    _nos = {"meta": {}, "phases": [{"id": "PX", "tasks": [{"id": "PX.1"}]}]}
    check("composition diff normalises skills exactly as the view does",
          M._composition_changes(_nos, {"tasks": {"PX.1": {"skills": ["a"]}}})
          == [{"target": "PX.1", "field": "skills", "from": [], "to": ["a"]}]
          and _panel_state._composition_view(_nos)["tasks"][0]["skills"] == [])
    check("composition diff: an empty skills list set to empty is not a change",
          M._composition_changes(_nos, {"tasks": {"PX.1": {"skills": []}}}) == [])

    # The response the client compares against.
    res = M.apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("a composition save echoes exactly what it applied",
          res["ok"] and res["applied"] == [{"target": "P1.1", "field": "model",
                                            "from": "opus", "to": "sonnet"}])
    _mtime = os.path.getmtime(mpath)
    res = M.apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("a save that changes nothing writes nothing and says so",
          res["ok"] and res.get("unchanged") is True and res["applied"] == []
          and res.get("written") == [] and os.path.getmtime(mpath) == _mtime)
    _cfg_now = M.read_config(proj)
    res = M.write_config(proj, dict(_cfg_now))
    check("the same rule for the config: nothing changed, nothing written",
          res["ok"] and res.get("unchanged") is True and res["applied"] == [])
    res = M.write_config(proj, dict(_cfg_now, trivialLineThreshold=41))
    check("a config save echoes the dotted path it changed",
          res["ok"] and res["applied"] == [
              {"target": "config", "field": "trivialLineThreshold",
               "from": 40, "to": 41}])

    # --- the journal call site ---------------------------------------------------
    # This call site shipped in v0.28, one release BEFORE audit-journal.py, and was
    # exercised against the stubs below so it would not be untested code in the
    # meantime. The module is here now, so the last case in this block is the real
    # thing end to end — but the stubs stay: they are the only way to reach the two
    # fail-soft branches, and "the journal is absent" is still what an older
    # install looks like.
    _saved_j0 = dict(M._JOURNAL)
    try:
        M._JOURNAL.update({"tried": True, "mod": None})
        check("no journal on this install -> journaled false, and it says WHY",
              M._journal(proj, M.read_config(proj), "config.write", "x", [])
              == {"journaled": False, "journaledWhy": "unavailable"})
    finally:
        M._JOURNAL.clear()
        M._JOURNAL.update(_saved_j0)
    check("...and on THIS install there is one, so the load resolves to the "
          "module rather than to None (the case above is a simulation now)",
          M._journalmod() is not None and hasattr(M._journalmod(), "append"))

    class _JStub(object):
        rows = []

        @staticmethod
        def append(project, entry):
            _JStub.rows.append((project, entry))
            return True

    class _JBroken(object):
        @staticmethod
        def append(project, entry):
            raise RuntimeError("disk on fire")

    _saved_j = dict(M._JOURNAL)
    try:
        M._JOURNAL.update({"tried": True, "mod": _JStub})
        _rows = [{"target": "P1.1", "field": "model",
                  "from": "opus", "to": "sonnet"}]
        out = M._journal(proj, M.read_config(proj), "composition.write", "m.json", _rows)
        _ent = _JStub.rows[-1][1] if _JStub.rows else {}
        check("with a journal present the row is appended and reported",
              out == {"journaled": True} and len(_JStub.rows) == 1)
        check("the journal row carries the contract's fields, not this file's",
              _ent.get("action") == "composition.write"
              and _ent.get("target") == "m.json"
              and set(_ent) == {"action", "target", "summary", "actor"})
        check("the actor is the viewer, tagged with how the write arrived",
              (_ent.get("actor") or {}).get("via") == "panel"
              and (_ent.get("actor") or {}).get("sessionId") == M._panel_session())
        check("the changes travel in the summary the row does have room for",
              "P1.1 model: opus -> sonnet" in (_ent.get("summary") or "")
              and (_ent.get("summary") or "").startswith("1 change(s)"))
        # The stub is swapped into a memo the READ side owns, and this is the case
        # that says the two are one object rather than two: `journal_state` has to
        # see the same install this writer sees, or each side would be testing a
        # journal the other does not have.
        check("the stub the writer swapped in is the module the READ side resolves "
              "to - one memo, reached by identity, not a copy per module",
              M._JOURNAL is _panel_state._JOURNAL
              and _panel_state._journalmod() is _JStub)
        M._JOURNAL.update({"tried": True, "mod": _JBroken})
        # Caught HERE as well: "fail-soft" means the exception does not leave
        # _journal, so a version that let it through would take this suite down
        # with a traceback instead of failing the one case that is about it.
        try:
            _fs = M._journal(proj, M.read_config(proj), "x", "y", [])
        except Exception as exc:                                # pragma: no cover
            _fs = "it raised: %s" % exc
        check("a journal that throws never breaks the write it is recording",
              _fs == {"journaled": False, "journaledWhy": "failed"})
        M._JOURNAL.update({"tried": True, "mod": _JStub})
        _JStub.rows = []
        res = M.apply_composition(proj, {"tasks": {"P1.1": {"model": "opus"}}})
        check("a real save appends one row and reports journaled",
              res["ok"] and res.get("journaled") is True and len(_JStub.rows) == 1)

        # Both `by_tid` indexes are `_mio.tasks_by_id` now, which excludes a task
        # whose id is falsy: an index is a lookup BY IDENTITY, and an entry with
        # no identity is a validator finding rather than a key. What changes is
        # only WHICH refusal comes back -- a manifest holding such a task is
        # refused end to end either way (the validator names the missing id a few
        # lines later in `apply_composition`) -- so this pins the more precise of
        # the two, and pins that the task NEXT to it still patches, which is the
        # direction that would go wrong if the filter were too wide.
        def _nid_fixture():
            return {"meta": {}, "phases": [
                {"id": "P1", "status": "in_progress", "tasks": [
                    {"id": "", "status": "pending", "model": "sonnet"},
                    {"id": "P1.1", "status": "pending", "model": "sonnet"}]}]}

        check("an empty-id task is not addressable by a composition patch - "
              "refused by name rather than written to",
              M.apply_composition_patch(_nid_fixture(),
                                      {"tasks": {"": {"model": "opus"}}})
              == "unknown task ''")
        _nid = _nid_fixture()
        check("...while the task beside it, which HAS an id, still patches",
              M.apply_composition_patch(_nid, {"tasks": {"P1.1": {"model": "opus"}}})
              is None
              and _nid["phases"][0]["tasks"][1]["model"] == "opus"
              and _nid["phases"][0]["tasks"][0]["model"] == "sonnet")

        # `_heal_phase_status` walks (phase, task) PAIRS now, so a phase with
        # more than one running task is visited more than once. Two running
        # tasks is the fixture that separates "one row per phase" from "one row
        # per running task" -- with a single task both versions agree, and the
        # rows go to the confirm dialog and the journal, where a duplicate would
        # read as two edits nobody made. The `pending` phase behind them is the
        # second direction: it must produce NO row, or the walk is healing
        # everything it touches.
        _hp = {"phases": [
            {"id": "P1", "status": "pending", "tasks": [
                {"id": "P1.1", "status": "in_progress"},
                {"id": "P1.2", "status": "in_progress"}]},
            {"id": "P2", "status": "pending", "tasks": [
                {"id": "P2.1", "status": "pending"}]},
        ]}
        _hrows = M._heal_phase_status(_hp)
        check("heal: a phase with TWO running tasks heals exactly once, and a "
              "phase with none is left alone",
              _hrows == [{"target": "P1", "field": "status",
                          "from": "pending", "to": "in_progress"}]
              and _hp["phases"][0]["status"] == "in_progress"
              and _hp["phases"][1]["status"] == "pending")

        # --- the write heals "task in_progress, phase pending" (v0.37 A4) ----
        # The validator's warning stays as the backstop for hand edits; at the
        # plugin's own write site the class dies: a manifest a save persists
        # never leaves a phase 'pending' around a task that is already
        # running, and the journal row for that write says so.
        _hproj = tempfile.mkdtemp(prefix="panel-heal-")
        try:
            M._atomic_write_json(M._config_path(_hproj),
                               {"manifestPath": "docs/audit/audit-plan.json"})
            _hm = M._manifest_path(_hproj, M.read_config(_hproj))
            os.makedirs(os.path.dirname(_hm), exist_ok=True)
            M._atomic_write_json(_hm, {
                "meta": {"version": 2},
                "phases": [
                    {"id": "P1", "title": "One", "status": "pending",
                     "tasks": [{"id": "P1.1", "title": "T1",
                                "status": "in_progress"}]},
                    {"id": "P2", "title": "Two", "status": "in_progress",
                     "tasks": [{"id": "P2.1", "title": "T2",
                                "status": "in_progress"}]}]})
            _JStub.rows = []
            _hres = M.apply_composition(_hproj,
                                      {"tasks": {"P1.1": {"model": "opus"}}})
            _hdoc = M._read_json(_hm)
            check("heal: a save that persists an in_progress task under a "
                  "pending phase flips the phase in the SAME write",
                  _hres.get("ok") is True
                  and _hdoc["phases"][0]["status"] == "in_progress")
            check("heal: the healed row is reported apart from `applied`, so "
                  "the confirm-echo comparison keeps meaning what it says",
                  _hres.get("healed") == [{"target": "P1", "field": "status",
                                           "from": "pending",
                                           "to": "in_progress"}]
                  and all(r.get("field") != "status"
                          for r in _hres.get("applied") or []))
            _hsum = (_JStub.rows[-1][1].get("summary")
                     if _JStub.rows else "") or ""
            check("heal: the journal row for that write says so",
                  "P1 status: pending -> in_progress" in _hsum)
            check("heal: a phase already in_progress is untouched",
                  _hdoc["phases"][1]["status"] == "in_progress"
                  and all(r.get("target") != "P2"
                          for r in _hres.get("healed") or []))
        finally:
            _shutil.rmtree(_hproj, ignore_errors=True)

        # Sharded: a phase's status lives in its own shard, so the heal must
        # write a shard the patch never touched -- or it would claim a heal
        # the next load cannot see.
        _hs = tempfile.mkdtemp(prefix="panel-heal-sharded-")
        try:
            M._atomic_write_json(M._config_path(_hs),
                               {"manifestPath": "docs/audit/audit-plan.json"})
            _hsm = M._manifest_path(_hs, M.read_config(_hs))
            os.makedirs(os.path.dirname(_hsm), exist_ok=True)
            _mio.save_sharded(_hsm, {
                "meta": {"version": 3},
                "phases": [
                    {"id": "P1", "title": "One", "status": "pending",
                     "tasks": [{"id": "P1.1", "title": "T1",
                                "status": "pending"}]},
                    {"id": "P2", "title": "Two", "status": "pending",
                     "tasks": [{"id": "P2.1", "title": "T2",
                                "status": "in_progress"}]}]})
            _hres2 = M.apply_composition(_hs,
                                       {"tasks": {"P1.1": {"model": "opus"}}})
            _hp2 = [p for p in _mio.load_manifest(_hsm)["phases"]
                    if p["id"] == "P2"][0]
            check("heal: sharded - the healed phase's shard is written even "
                  "when the patch never touched that phase",
                  _hres2.get("ok") is True
                  and _hp2["status"] == "in_progress"
                  and any("P2" in w for w in _hres2.get("written") or []))
        finally:
            _shutil.rmtree(_hs, ignore_errors=True)
    finally:
        M._JOURNAL.clear()
        M._JOURNAL.update(_saved_j)

    # --- ...and the same path with the REAL module behind it (v0.29) ------------
    # The stubs above prove the call site. They cannot prove that a save produces a
    # row anyone can verify, which is the only claim this feature actually makes —
    # so this drives the panel's own writer, then asks audit-journal.py, not the
    # panel, whether the chain holds.
    _jmod = M._journalmod()
    _before = len(_jmod.read_all(proj, M.read_config(proj)))
    res = M.apply_composition(proj, {"tasks": {"P1.1": {"model": "haiku"}}})
    _after = _jmod.read_all(proj, M.read_config(proj))
    check("a real composition save appends a real row and says it was logged",
          res.get("journaled") is True and len(_after) == _before + 1)
    _row = _after[-1] if _after else {}
    check("the row names the change in the same words the dialog showed",
          "P1.1 model:" in (_row.get("summary") or "")
          and "haiku" in (_row.get("summary") or ""))
    check("...and it names the panel as the writer, with the viewer as the author",
          (_row.get("actor") or {}).get("via") == "panel"
          and (_row.get("actor") or {}).get("author")
          == M._viewer(proj, M.read_config(proj)).get("author"))
    check("the row records the manifest as it stood after the write - which is "
          "what makes a later change with no row to explain it visible",
          bool(_row.get("stateHash")))
    _jv = _jmod.verify(proj, M.read_config(proj))
    check("the chain the panel wrote verifies",
          _jv["ok"] and not _jv["findings"])
    _jst = journal_state(proj)
    check("GET /api/journal reports the rows newest first, with the verdict beside "
          "them - a list with no verdict invites trust, a verdict with no list is "
          "a claim about something you cannot see",
          _jst["available"] and _jst["verify"]["ok"]
          and _jst["rows"] and _jst["rows"][0].get("hash") == _row.get("hash"))
    check("...and the verdict counts the rows the reader actually sees - a "
          "hardcoded `ok` beside a list nobody checked is the failure this "
          "endpoint exists to avoid",
          _jst["verify"]["rows"] == len(_after) and _jst["verify"]["exists"])
    check("...and it says where the journal is, relative to the project",
          isinstance(_jst["dir"], str) and not os.path.isabs(_jst["dir"]))
    _saved_j2 = dict(M._JOURNAL)
    try:
        M._JOURNAL.update({"tried": True, "mod": None})
        _jst0 = journal_state(proj)
        check("an install with no journal module answers `not available` rather "
              "than 404 - there being no journal here is an answer",
              _jst0["available"] is False and _jst0["rows"] == []
              and _jst0["verify"] is None)
    finally:
        M._JOURNAL.clear()
        M._JOURNAL.update(_saved_j2)
    # A config save is journalled too, under its own action.
    _cfg_j = M.read_config(proj)
    M.write_config(proj, dict(_cfg_j, trivialLineThreshold=43))
    _acts = [r.get("action") for r in _jmod.read_all(proj, M.read_config(proj))]
    check("a config save is recorded under its own action - the rules changing is "
          "not the same event as the plan changing",
          "config.write" in _acts and "composition.write" in _acts)
    # Off means off, on both surfaces.
    M.write_config(proj, dict(M.read_config(proj), journal={"enabled": False}))
    _n_off = len(_jmod.read_all(proj, M.read_config(proj)))
    res = M.apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("with journal.enabled false a save still succeeds, writes no row, and "
          "does NOT claim to have been logged",
          res["ok"] and res.get("journaled") is False
          and len(_jmod.read_all(proj, M.read_config(proj))) == _n_off)
    M.write_config(proj, dict(M.read_config(proj), journal={"enabled": True}))

    check("a change renders the same way for the journal as for the dialog",
          M._fmt_change({"target": "P1.2", "field": "model",
                       "from": None, "to": "opus"}) == "P1.2 model: (unset) -> opus"
          and M._fmt_change({"target": "P1.2", "field": "skills",
                           "from": [], "to": ["a"]}) == 'P1.2 skills: [] -> ["a"]')
    check("on a skills row, null is the OPT-OUT, not '(unset)' - the journal "
          "must record the one deliberate answer as an answer",
          M._fmt_change({"target": "P1.2", "field": "skills",
                       "from": [], "to": None})
          == "P1.2 skills: [] -> null (opted out)"
          and M._fmt_change({"target": "P1.2", "field": "model",
                           "from": None, "to": "opus"})
          == "P1.2 model: (unset) -> opus")
    check("...including a boolean, which the browser spells `true` and str() "
          "spells `True` - a value nobody can type into the JSON file they are "
          "being told about",
          M._fmt_change({"target": "config", "field": "enforce",
                       "from": False, "to": True})
          == "config enforce: false -> true")
    check("a number is not quoted and a string is not JSON-escaped - the line is "
          "prose about a JSON file, not JSON",
          M._fmt_change({"target": "config", "field": "trivialLineThreshold",
                       "from": 40, "to": 41})
          == "config trivialLineThreshold: 40 -> 41"
          and "\"opus\"" not in M._fmt_change({"target": "t", "field": "model",
                                             "from": "a", "to": "opus"}))

    # --- the Plan gate card's prune (POST /api/gate-events/prune) --------------
    # ONE RULE, TWO DOORS. What is proven here is that the panel adds no rule of
    # its own: the same `_gate_feed.prune` the command runs, over the project's
    # OWN config, with the endpoint's contract on top (an object body, a threshold
    # that can be read). The classification itself has its cases in
    # `test__gate_feed.py` and is deliberately not restated here.
    import shutil as _sh1
    import tempfile as _tf1
    _gf_tmp = _tf1.mkdtemp(prefix="panel-write-gatefeed-")
    _gf_out = _tf1.mkdtemp(prefix="panel-write-outside-")
    try:
        import _gate_feed as _gf
        _gf_proj = os.path.join(_gf_tmp, "proj")
        _gf_logs = os.path.join(_gf_proj, ".claude", "logs")
        os.makedirs(_gf_logs, exist_ok=True)
        _gf_in = json.dumps({"ts": "2026-08-20T10:00:00Z", "event": "deny",
                             "file": "src/app.ts"}, sort_keys=True,
                            separators=(",", ":"))
        _gf_bad = json.dumps({"ts": "2026-08-20T10:00:01Z", "event": "deny",
                              "file": os.path.join(_gf_out, "probe.py")},
                             sort_keys=True, separators=(",", ":"))
        _gf_feed = os.path.join(_gf_logs, "plan-gate-events.jsonl")

        def _seed_feed():
            with open(_gf_feed, "w", encoding="utf-8") as _fh1:
                _fh1.write(_gf_in + "\n" + _gf_bad + "\n")

        _seed_feed()
        _gf_dry = M.prune_gate_events(_gf_proj, {"dryRun": True})
        with open(_gf_feed, "r", encoding="utf-8") as _fh1:
            _gf_after_dry = _fh1.read()
        check("gp1 a dryRun POST returns the counts the confirm dialog needs and "
              "writes nothing - the out-of-repository row is still in the file "
              "once afterwards: %r" % (_gf_dry,),
              _gf_dry["ok"] is True and _gf_dry["removed"] == 1
              and _gf_dry["kept"] == 1 and _gf_dry["wrote"] is False
              and _gf_after_dry.count(_gf_out) == 1)

        _gf_real = M.prune_gate_events(_gf_proj, {})
        with open(_gf_feed, "r", encoding="utf-8") as _fh1:
            _gf_after = _fh1.read()
        check("gp2 ...and the real POST removes exactly that row, leaving the "
              "in-repository one - counted on both sides, so a prune that "
              "emptied the feed would fail here rather than look clean: %r"
              % (_gf_real,),
              _gf_real["wrote"] is True and _gf_real["removed"] == 1
              and _gf_after.count(_gf_out) == 0
              and _gf_after == _gf_in + "\n")

        _gf_bad_days = M.prune_gate_events(_gf_proj, {"olderThanDays": 0})
        _gf_bad_type = M.prune_gate_events(_gf_proj, {"olderThanDays": "30"})
        _gf_bool = M.prune_gate_events(_gf_proj, {"olderThanDays": True})
        check("gp3 a threshold that cannot be read is REFUSED rather than "
              "coerced or ignored - it is the one input here that decides how "
              "much history goes, and `True` is refused too because bool is an "
              "int in Python and would silently mean one day: %r"
              % ([_gf_bad_days, _gf_bad_type, _gf_bool],),
              [r["ok"] for r in (_gf_bad_days, _gf_bad_type, _gf_bool)]
              == [False, False, False]
              and all(len(r["findings"]) == 1
                      for r in (_gf_bad_days, _gf_bad_type, _gf_bool)))
        _gf_ok_days = M.prune_gate_events(_gf_proj, {"olderThanDays": 1})
        check("gp4 ...while a whole number of days at least 1 is accepted, which "
              "is what says gp3 refuses the VALUE and not the key: %r"
              % (_gf_ok_days,),
              _gf_ok_days["ok"] is True and _gf_ok_days["olderThanDays"] == 1)

        _seed_feed()
        _gf_direct = _gf.prune(_gf_proj, M.read_config(_gf_proj), dry_run=True)
        _seed_feed()
        _gf_endpoint = M.prune_gate_events(_gf_proj, {"dryRun": True})
        check("gp5 the endpoint IS the rule: the same project through "
              "`_gate_feed.prune` directly answers identically, so the panel "
              "holds no second opinion about what a prune removes: %r"
              % ((_gf_direct, _gf_endpoint),), _gf_direct == _gf_endpoint)
    finally:
        _sh1.rmtree(_gf_tmp, ignore_errors=True)
        _sh1.rmtree(_gf_out, ignore_errors=True)

    # --- isolation cases (P12.4): the moved boundary stays real -----------------
    _src = _harness.module_source(M)
    _imports = [l for l in _src.split("\n")
                if l.startswith("import ") or l.startswith("from ")]
    check("this module never imports panel-server - the write path sits BELOW the "
          "server and ABOVE the read side, so nothing here can form a cycle",
          not any("panel_server" in l or "panel-server" in l for l in _imports))
    _panel_src = open(_loader.script_path("panel-server.py"),
                      encoding="utf-8").read()
    _moved = ["_atomic_write_json", "write_policy", "write_areas", "_panel_session",
              "_acquire_write_lock", "_release_write_lock", "_flat_paths",
              "_config_changes", "_composition_changes", "_fmt_change", "_journal",
              "write_config", "_reject_unknown", "apply_composition_patch",
              "_touched_phase_ids", "_write_back", "apply_composition"]
    _unaliased = [n for n in _moved
                  if "\n%s = _panel_write.%s\n" % (n, n) not in _panel_src]
    check("every name this module took is aliased back in panel-server, so a route "
          "or a selftest that still spells it there resolves to THIS one: %r"
          % (_unaliased,), not _unaliased)
    check("...and every one of them is actually defined here rather than merely "
          "expected: %r" % ([n for n in _moved if not hasattr(M, n)],),
          len([n for n in _moved if hasattr(M, n)]) == len(_moved))
    # The journal memo, pinned from this side too: panel-server aliases _panel_STATE's
    # dict, this module reaches the same one, and all three are one object. Two
    # memos would be two answers to "is there a journal on this install".
    check("the journal memo is the read side's, shared by identity with "
          "panel-server rather than copied into a third dict",
          M._JOURNAL is _panel_state._JOURNAL
          and "\n_JOURNAL = _panel_state._JOURNAL\n" in _panel_src)

    # --- phase priority: one rule, two writers --------------------------------
    # The panel writes priority as COMPOSITION (the class of the per-task model
    # and skills it already writes), so the panel's boundary does not move. What
    # is legal is NOT decided here: both writers ask `_priority.tier_one_holder`,
    # which is the Policy tab's arrangement applied to a second feature.
    import shutil as _sh2
    import tempfile as _tf2
    import _priority as _prio
    _pp_tmp = _tf2.mkdtemp(prefix="panel-write-priority-")
    try:
        _pp_proj = os.path.join(_pp_tmp, "proj")
        os.makedirs(os.path.join(_pp_proj, ".claude"))
        os.makedirs(os.path.join(_pp_proj, "docs", "audit"))
        _pp_mpath = os.path.join(_pp_proj, "docs", "audit", "audit-plan.json")
        with open(os.path.join(_pp_proj, ".claude", "audit.config.json"),
                  "w", encoding="utf-8") as _fh:
            json.dump({"manifestPath": "docs/audit/audit-plan.json"}, _fh)
        _pp_manifest = {"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "One", "status": "pending",
             "tasks": [{"id": "P1.1", "title": "a", "status": "pending"}]},
            {"id": "P2", "title": "Two", "status": "pending",
             "tasks": [{"id": "P2.1", "title": "b", "status": "pending"}]}]}
        _mio.save_sharded(_pp_mpath, _pp_manifest)
        _pp_shard = os.path.join(_pp_proj, "docs", "audit", "phases", "P2.json")
        _pp_before = open(_pp_shard, "rb").read()

        res = M.apply_composition(_pp_proj, {"phases": {"P2": {"priority": 1}}})
        check("pp1 the panel writes a phase priority, and echoes it as an "
              "ordinary composition row",
              res["ok"] and res["applied"] == [{"target": "P2",
                                                "field": "priority",
                                                "from": None, "to": 1}],
              repr(res))
        with open(_pp_mpath, encoding="utf-8") as _fh:
            _pp_idx = json.load(_fh)
        check("pp2 ...onto the INDEX STUB, which is what makes the order "
              "computable without opening a shard",
              _pp_idx["phases"][1].get("priority") == 1,
              repr(_pp_idx["phases"][1]))
        check("pp3 ...and the SHARD is byte-identical: a priority-only save "
              "must not renormalise a file nobody edited, which is how the "
              "sharded layout manufactures a merge conflict",
              open(_pp_shard, "rb").read() == _pp_before)
        check("pp4 ...and only the index is reported as written",
              [w for w in res["written"] if w.endswith("P2.json")] == [],
              repr(res["written"]))

        res = M.apply_composition(_pp_proj, {"phases": {"P1": {"priority": 1}}})
        check("pp5 a second holder of tier 1 is REFUSED by the panel too, and "
              "the refusal names the holder - a UI that promised a write the "
              "CLI refuses is the drift this shares a function to prevent",
              not res["ok"] and any("P2 already holds it" in f
                                    for f in res["findings"]), repr(res))
        with open(_pp_mpath, encoding="utf-8") as _fh:
            check("pp6 ...and nothing was written",
                  json.load(_fh)["phases"][0].get("priority") is None)

        # PARITY, on the same input. Both writers are handed a manifest where P2
        # holds tier 1 and both are asked to give it to P1; the answers must be
        # the same KIND of answer, and they are because they come from the same
        # function.
        _sp = _loader.load_script("set-priority.py", modname="set_priority_parity")
        _cli_lines = []
        _cli_code = _sp.main([_pp_mpath, "P1", "1"], out=_cli_lines.append)
        check("pp7 PARITY: the CLI refuses the same write, names the same "
              "holder, and both verdicts come from `_priority.tier_one_holder` "
              "- pinned by identity, so a second implementation on either side "
              "fails here rather than being discovered by a user",
              _cli_code == 2
              and any("P2 already holds priority 1" in ln for ln in _cli_lines)
              and M._priority.tier_one_holder is _prio.tier_one_holder
              and _sp._priority.tier_one_holder is _prio.tier_one_holder,
              repr(_cli_lines))
        check("pp8 SECOND-DIRECTION CASE: with tier 1 free BOTH writers accept "
              "it. This is what goes red if either side starts refusing every "
              "pin - the refusal above would then be reading nothing",
              M.apply_composition(_pp_proj,
                                  {"phases": {"P1": {"priority": 2}}})["ok"]
              and _sp.main([_pp_mpath, "P1", "--clear"],
                           out=lambda *_a: None) == 0)

        for bad in ("1", 0, -2, True, 1.5):
            res = M.apply_composition(_pp_proj, {"phases": {"P1": {"priority": bad}}})
            check("pp9 %r is refused with a reason, never written as a tier"
                  % (bad,),
                  not res["ok"] and any("positive integer" in f
                                        for f in res["findings"]), repr(res))
        M.apply_composition(_pp_proj, {"phases": {"P1": {"priority": 3}}})
        res = M.apply_composition(_pp_proj, {"phases": {"P1": {"priority": None}}})
        check("pp10 null is the CLEAR - the same spelling the task skills "
              "opt-out uses, and what a select can send for 'no pin'",
              res["ok"], repr(res))
        with open(_pp_mpath, encoding="utf-8") as _fh:
            check("pp11 ...and the KEY is removed rather than set to null, "
                  "because an absent priority is how a phase says unprioritised",
                  "priority" not in json.load(_fh)["phases"][0])
        check("pp12 `priority` is in the phase write allow-list, so this whole "
              "block is exercising a field a patch may legally name",
              "priority" in M._PHASE_KEYS, repr(M._PHASE_KEYS))

        # --- the asymmetry, asserted in ONE place --------------------------
        # `priority: null` PRUNES the key and `adoParent: null` STORES it, and
        # the two sit in one case on purpose: they are the same spelling in the
        # same patch section meaning opposite things, and a reader who met them
        # a hundred lines apart would reasonably assume the second was a bug.
        # The reason is that null is a VALUE for adoParent - "hangs under
        # nothing, even when the fallback is set" - so pruning it would silently
        # restore the fallback, which is the exact override the field exists to
        # undo. Priority has no such meaning: an absent priority IS
        # unprioritised, so there is nothing for a stored null to say.
        _ap_res = M.apply_composition(
            _pp_proj, {"phases": {"P1": {"adoParent": None, "priority": 4}}})
        _ap_res2 = M.apply_composition(
            _pp_proj, {"phases": {"P1": {"priority": None}}})
        with open(_pp_mpath, encoding="utf-8") as _fh:
            _ap_idx = json.load(_fh)
        _ap_shard = os.path.join(_pp_proj, "docs", "audit", "phases", "P1.json")
        with open(_ap_shard, encoding="utf-8") as _fh:
            _ap_body = json.load(_fh)
        check("pp13 THE ASYMMETRY: `adoParent: null` is STORED (null is the "
              "answer 'hangs under nothing') while `priority: null` still "
              "PRUNES (an absent priority is how a phase says unprioritised) - "
              "one case, because the difference is deliberate: %r"
              % (_ap_body.get("adoParent", "<<missing>>"),),
              _ap_res["ok"] and _ap_res2["ok"]
              and "adoParent" in _ap_body and _ap_body["adoParent"] is None
              and "priority" not in _ap_idx["phases"][0])
        _ap_res3 = M.apply_composition(
            _pp_proj, {"phases": {"P1": {"adoParent": {"id": 41,
                                                       "type": "Feature",
                                                       "source": "declared"}}}})
        check("pp14 ...and the row for that store is not a no-op: an ABSENT "
              "declaration reads as the use-fallback marker on the `from` side, "
              "so 'use the fallback -> nowhere' is a change the dialog shows "
              "rather than a null that looks like it was already there: %r"
              % (_ap_res["applied"],),
              {"target": "P1", "field": "adoParent",
               "from": _adop.use_fallback(), "to": None} in _ap_res["applied"])
        with open(_ap_shard, encoding="utf-8") as _fh:
            _ap_body3 = json.load(_fh)
        check("pp15 a declaration is stored whole - the BASIS travels with the "
              "id, because a stored bare number is the plugin's guess about a "
              "board it never looked at: %r" % (_ap_body3.get("adoParent"),),
              _ap_res3["ok"]
              and _ap_body3["adoParent"] == {"id": 41, "type": "Feature",
                                             "source": "declared"})
        _ap_clear = M.apply_composition(
            _pp_proj, {"phases": {"P1": {"adoParent": _adop.use_fallback()}}})
        with open(_ap_shard, encoding="utf-8") as _fh:
            _ap_body4 = json.load(_fh)
        check("pp16 the use-fallback marker DELETES the key, which is the one "
              "of the three states JSON cannot spell in a patch any other way",
              _ap_clear["ok"] and "adoParent" not in _ap_body4,
              repr(_ap_body4.get("adoParent", "<<absent>>")))
        for _apbad, _apwhy in (({"id": "41"}, "a string id"),
                               ({"id": 0}, "a zero id"),
                               ({"type": "Feature"}, "no id at all"),
                               (7, "a bare number")):
            _apr = M.apply_composition(
                _pp_proj, {"phases": {"P1": {"adoParent": _apbad}}})
            check("pp17 %s is refused with the SHAPE CHECK'S own words rather "
                  "than written and left for the validator to find later: %r"
                  % (_apwhy, _apr.get("findings")),
                  not _apr["ok"]
                  # `refused: ` is the prefix `apply_composition` puts on an
                  # APPLIER's refusal, and the manifest validator's own findings
                  # do not carry it. Without this clause the case passed with
                  # the shape check deleted, because the validator refuses these
                  # too - a case that could not tell "named at the door" from
                  # "found in the wall of findings afterwards", which is the
                  # whole difference the applier exists to make.
                  and _apr["findings"][0].startswith("refused: ")
                  and any("adoParent" in f for f in _apr["findings"]))
        with open(_ap_shard, encoding="utf-8") as _fh:
            check("pp18 ...and none of those four refusals wrote anything: the "
                  "phase still holds the declaration pp16 cleared",
                  "adoParent" not in json.load(_fh))
        check("pp19 `adoParent` is in the phase write allow-list, so this whole "
              "block is exercising a field a patch may legally name",
              "adoParent" in M._PHASE_KEYS, repr(M._PHASE_KEYS))
    finally:
        _sh2.rmtree(_pp_tmp, ignore_errors=True)

    _shutil.rmtree(tmp, ignore_errors=True)

def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_write.py --selftest\n")
    raise SystemExit(2)
