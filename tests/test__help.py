#!/usr/bin/env python3
"""
The cases for `_help.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `_areas` and `_policy` are imported the way `_help.py`
imports them, because three cases compare against those modules' own objects
(`_areas.REVIEW_RULE`, `_policy.required_names()`).

TWO THINGS ABOUT THIS SUITE READ THE REPOSITORY, AND BOTH STILL RESOLVE.

  * the scripts directory was `_help.py`'s own `_HERE` constant, and the suite
    uses it as SCRATCH SPACE: `_helpfm.md` (a frontmatter fixture) and `_nope` (a
    plugin root that must not exist). Carried literally they would name `tests/` -
    which for scratch paths resolves correctly BY COINCIDENCE, and that is exactly
    the shape the guide says to spell about the subject instead. They read the ONE
    anchor through the module under test, so each one still says "beside the module
    under test".
  * `plugin_root()` is `_help.py`'s own function (now `_output.PLUGIN_ROOT`), so
    every case that reads a real document resolves off the SUBJECT's location.
    `pr1` is the case that goes red if it ever stops being the directory holding
    `scripts/`.

ONE IMPORT EDGE RETIRED WITH THIS MOVE. `s8`'s `import _panel_settings` was the
only thing in `_help.py` naming that module, and `_deps` walks the whole AST -
selftest included - so it was a real static edge until now. It was downward
(L3 -> L2), so no `KNOWN_LAYER_DEBT` entry went with it, but the generated module
map fence in `PLUGIN-BUILD-GUIDE.md` lost the line and was regenerated.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _areas                                      # noqa: E402  (as _help imports it)
import _policy                                     # noqa: E402  (as _help imports it)
import _help as M                                  # noqa: E402
import _help_lints as L                          # noqa: E402


# --- the payload under another platform's conventions --------------------------
# `GET /api/help` is fetched once per drawer session and parsed whole, and the
# tables behind its per-path form are built from the same sources, so the size of
# all of it is a serving cost that has a ceiling. The ceiling stays fixed; HEADROOM is the
# margin that has to stay free under it at all times. It is larger than the whole
# config table, so no single schema addition can be the byte that crosses the
# line: crossing it has to be a decision to spend the margin, made in this file,
# not a paragraph that happened to land last.
PAYLOAD_CAP = 200000
PAYLOAD_HEADROOM = 40000


def _payload_bytes(root=None):
    """Every byte `/api/help` can serve: the payload and the per-path tables that
    `entry_for` answers from. The tables left the payload, but the field text is the
    part a CRLF checkout or a backslash separator changes, so measuring the payload
    alone would stop watching the one thing the cap and the platform cases exist for."""
    return len(json.dumps([M.payload(root), M.tables(root)]))


def _crlf_root():
    """A plugin root whose schemas and agent files end every line in CRLF - the
    sources `payload()` reads, as a checkout that ignored `.gitattributes` would
    write them."""
    import shutil
    root = _harness.fixture_root("help-crlf-")
    src = M.plugin_root()
    for sub in ("schema", "agents"):
        shutil.copytree(os.path.join(src, sub), os.path.join(root, sub))
        for dirpath, _dirs, names in os.walk(os.path.join(root, sub)):
            for name in names:
                path = os.path.join(dirpath, name)
                with open(path, "rb") as fh:
                    data = fh.read().replace(b"\r\n", b"\n")
                with open(path, "wb") as fh:
                    fh.write(data.replace(b"\n", b"\r\n"))
    return root


def _backslash_payload_bytes():
    """The payload as built where `os.sep` is a backslash and `os.path.join`
    is Windows' own. Only the module under test sees the swap - its `os` and its
    `open` are replaced for the call and put back - and every real file access is
    handed a forward-slash path, which both platforms open, so the fixture
    changes how a path is SPELLED and never which file is read."""
    import ntpath
    import types
    real_os = M.os

    def fwd(path):
        return path.replace("\\", "/") if isinstance(path, str) else path

    shim_path = types.ModuleType("shim_path")
    shim_path.__dict__.update(real_os.path.__dict__)
    shim_path.join = ntpath.join
    shim_path.sep = "\\"
    for name in ("isfile", "isdir", "exists", "lexists"):
        shim_path.__dict__[name] = (lambda f: lambda p: f(fwd(p)))(
            getattr(real_os.path, name))
    shim_os = types.ModuleType("shim_os")
    shim_os.__dict__.update(real_os.__dict__)
    shim_os.path = shim_path
    shim_os.sep = "\\"
    shim_os.listdir = lambda p=".": real_os.listdir(fwd(p))
    M.os = shim_os
    M.open = lambda p, *a, **k: open(fwd(p), *a, **k)
    try:
        return _payload_bytes()
    finally:
        M.os = real_os
        del M.open


def _backslash_paths(node):
    """Every served string that spells a file path with a backslash between two
    path words. Walks the payload object itself, so the backslash is one
    character, not the doubled form `json.dumps` writes."""
    pat = re.compile(r"[\w.-]+\\[\w.-]+\.(?:json|md|py)\b")
    if isinstance(node, str):
        return [node] if pat.search(node) else []
    if isinstance(node, dict):
        return [h for v in node.values() for h in _backslash_paths(v)]
    if isinstance(node, (list, tuple)):
        return [h for v in node for h in _backslash_paths(v)]
    return []


def _run_with_nt_join(fn):
    """Run `fn()` while `os.path.join` spells every relative join Windows-style.
    The Windows join is bound BEFORE the swap: where `os.path` is `ntpath`,
    `ntpath.join` is the very attribute being replaced, so a lambda that looked it
    up at call time would call itself."""
    import ntpath
    _nt_join = ntpath.join
    _real_join = os.path.join
    os.path.join = lambda first, *rest: (
        _real_join(first, *rest) if os.path.isabs(first)
        else _nt_join(first, *rest))
    try:
        return fn()
    finally:
        os.path.join = _real_join


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- extraction ---------------------------------------------------------------
    cfg = L.config_fields()
    man = L.manifest_fields()
    check("s2 nested containers are walked, not just the top level",
          "tddReminder.throttleMinutes" in cfg and "usage.bands.highUSD" in cfg)
    check("s3 an array's items are spelled path[]",
          "guardEdits.customRules[].bannedPattern" in cfg)
    check("s4 an open map's keys are spelled path.<name>",
          "usage.pricing.<name>.in" in cfg)
    check("s5 an enum reaches the drawer, so it can show the legal values",
          cfg["tddReminder.inProgressPolicy"].get("enum") and
          "skip-gate-only" in cfg["tddReminder.inProgressPolicy"]["enum"])
    check("s6 a $ref resolves to the description it points at - `task.model` "
          "carries no words of its own, only a reference to the shared shape",
          "Model tier" in man["phases[].tasks[].model"]["description"])
    check("s7 every path the schema declares carries words - an undescribed key "
          "is a field the drawer opens on an empty page",
          not [p for p in ("manifestPath", "enforce", "journal.dir", "policy",
                           "meta.areas", "phases[].reviewSkill")
               if not cfg.get(p, man.get(p, {})).get("description")])

    # THE point of extracting rather than restating: the panel binds controls to
    # config paths, and every one of them must be documented by the schema. A new
    # setting that reaches the form without reaching the schema fails here.
    try:
        # _panel_settings is what actually owns _settings_paths() (P12.1, moved
        # out of panel-server.py). While this case lived in `_help.py` the import
        # had to stay LOCAL - `_deps` counts an import fifty lines inside a
        # function as an edge, and `_help` (L3) naming `_panel_settings` (L2) put
        # a test-only edge in the product's graph. From here it cannot: `tests/`
        # has no position in the import order. It stays inside the `try` for the
        # other half of the original reason - the `except` below turns a missing
        # panel into a NAMED failing case rather than an import error that takes
        # every remaining case with it.
        import _panel_settings
        bound = set(_panel_settings._settings_paths())
    except Exception as exc:                                # pragma: no cover
        bound = set()
        print("     (panel unavailable: %s)" % exc)
    check("s8 every setting the panel binds a control to is described by the "
          "schema - the drawer's whole contract",
          bound and not [p for p in bound if not (M.lookup(cfg, p) or {}).get(
              "description")],
          repr(sorted(p for p in bound if not (M.lookup(cfg, p) or {}).get(
              "description"))))
    check("s9 ...and every composition lever resolves too, under the panel's own "
          "name for it",
          not [k for k, p in M.COMPOSITION_PATHS.items()
               if not (M.lookup(man, p) or {}).get("description")],
          repr([k for k, p in M.COMPOSITION_PATHS.items()
                if not (M.lookup(man, p) or {}).get("description")]))

    # --- lookup -------------------------------------------------------------------
    check("l1 a concrete map key finds the shape's help",
          M.lookup(cfg, "usage.pricing.claude-opus-4.in") is
          cfg["usage.pricing.<name>.in"])
    check("l2 an array index finds the item's help - the SECOND custom rule is "
          "not a different field",
          M.lookup(cfg, "guardEdits.customRules.1.message") is
          cfg["guardEdits.customRules[].message"])
    check("l3 an unknown path is None rather than a guess",
          M.lookup(cfg, "nothing.like.this") is None)

    # --- folding a repeated shape ---------------------------------------------------
    # Every lookup below goes through `.get` and `getattr`: a build without the
    # fold must fail these cases by name, not abort the suite before the payload
    # cases run.
    _built = M.tables()
    _fields = _built.get("fields") or {}
    _aliases = _built.get("aliases") or {}
    _fold = getattr(M, "fold_repeats", lambda *a: None)
    _unalias = getattr(M, "unalias", lambda *a: None)
    _lost = ["this build serves no aliases"] if not _aliases else [
        (d, p) for d, full in (("config", cfg), ("manifest", man))
        for p, e in full.items()
        if {k: v for k, v in (M.lookup(_fields.get(d) or {}, p,
                                       _aliases.get(d)) or {}).items()
            if k not in ("topic", "default")} != e]
    check("fo1 folding loses nothing: every path the full extraction documents "
          "resolves through the served table and its aliases to the same words "
          "and shape", not _lost and _aliases.get("manifest"), repr(_lost[:5]))
    _twin = {"a": {"description": "A"}, "a.x": {"description": "X", "default": 1},
             "b": {"description": "B"}, "b.x": {"description": "X", "default": 1}}
    _sites = [("shape", "a"), ("shape", "b")]
    _diff = dict(_twin, **{"b.x": {"description": "X", "default": 2}})
    check("fo2 an equal second mount folds below its own entry, which keeps the "
          "referrer's words",
          _fold(_twin, _sites) == {
              "fields": {"a": _twin["a"], "a.x": _twin["a.x"], "b": _twin["b"]},
              "aliases": {"b": "a"}})
    # The other direction: a fold that ignored the subtree's contents would
    # serve the first mount's default for the second path.
    check("fo3 ...but a mount whose subtree differs - here a default - stays "
          "expanded", _fold(_diff, _sites) == {"fields": _diff, "aliases": {}})
    check("fo4 an alias rewrite that lands under another alias follows it, and "
          "the prefix's own entry is not rewritten",
          _unalias("p.q.s.u", {"p.q": "r", "r.s": "t"}) == "t.u"
          and _unalias("p.q", {"p.q": "r"}) == "p.q")
    _fo5 = M.entry_for("proposals.0.payload.phase.status", "manifest") or {}
    check("fo5 a folded path says which shape documents it",
          _fo5.get("key") == "phases[].status", repr(_fo5.get("key")))

    # `entry_for` is the ONE resolver, reachable over HTTP. The drawer asks it
    # instead of carrying a second copy of normalise_path in the browser.
    e1 = M.entry_for("usage.pricing.claude-opus-4.in", "config")
    check("e1 a concrete document path resolves, and says which SHAPE answered - "
          "'your second pricing row is not a second field' is the sentence",
          e1 and e1["path"] == "usage.pricing.claude-opus-4.in"
          and e1["key"] == "usage.pricing.<name>.in"
          and e1["entry"]["description"], repr(e1))
    e2 = M.entry_for("phases[].tasks[].model", "manifest")
    check("e2 the manifest table is reachable under its own name",
          e2 and e2["doc"] == "manifest" and "Model tier" in
          e2["entry"]["description"], repr(e2))
    check("e3 an exact path answers as itself, not as some shape it resembles",
          (M.entry_for("journal.dir") or {}).get("key") == "journal.dir")
    check("e4 the enrichment is the table's own - a lookup and the full table "
          "cannot describe one field differently",
          M.entry_for("trivialLineThreshold")["entry"] ==
          M.tables()["fields"]["config"]["trivialLineThreshold"])
    check("e5 an unknown path and an unknown document are both None, so the "
          "drawer says it has no entry rather than opening on nothing",
          M.entry_for("nothing.like.this") is None
          and M.entry_for("enforce", "../../etc/passwd") is None)

    # --- quoted frontmatter ---------------------------------------------------------
    check("q1 a doubled quote inside a single-quoted scalar is the ESCAPE, not "
          "two characters - the guide's own description carries one, and the "
          "drawer would print \"the plugin''s own README\"",
          M.unquote_scalar("'the plugin''s own README'") == "the plugin's own README")
    check("q2 ...and a backslash-escaped quote in a double-quoted one",
          M.unquote_scalar('"say \\"hi\\""') == 'say "hi"')
    check("q3 an unquoted apostrophe is a character, not a quote to strip",
          M.unquote_scalar("don't") == "don't" and M.unquote_scalar("'sup") == "'sup")
    check("q4 the shipped guide's card is clean - this is the string the drawer "
          "renders", "''" not in (M.guide_card() or {}).get("description", ""),
          repr((M.guide_card() or {}).get("description", ""))[:120])

    # --- defaults -----------------------------------------------------------------
    dflt = M.config_defaults()
    check("d1 defaults are flattened from the hooks' own DEFAULTS",
          dflt["trivialLineThreshold"] == 80 and dflt["gitRoot"] == "."
          and dflt["enforce"] is False)
    check("d2 a short list is shown - 'what do I get for free' is the question an "
          "empty box raises", isinstance(dflt.get("exemptGlobs"), list)
          and "**/*.test.*" in dflt["exemptGlobs"])
    check("d3 a rate table is not: its rows carry their own defaults",
          "usage.pricing" not in dflt)
    check("d4 the flattening walks containers rather than stopping at them",
          dflt["tddReminder.enabled"] is True
          and dflt["guardEdits.tokenVars"] == ["accessToken", "refreshToken",
                                               "idToken"])
    check("d5 a long list is dropped whole rather than truncated - a half-shown "
          "default is a wrong default",
          not M._showable(list(range(M._MAX_DEFAULT_ITEMS + 1)))
          and M._showable(list(range(M._MAX_DEFAULT_ITEMS))))

    # --- topics -------------------------------------------------------------------
    tps = {t["id"]: t for t in M.topics()}
    check("t1 four concept pages, each with a title and a summary",
          sorted(tps) == ["areas", "gate-tiers", "journal", "policy"]
          and all(t["title"] and t["summary"] and t["paragraphs"]
                  for t in tps.values()))
    gate = tps["gate-tiers"]["table"]["rows"]
    check("t2 the gate table is COMPUTED by plan_gate_mode, not typed - these are "
          "the hook's own answers, planGate rows included (v0.34: ask joins the "
          "ladder, and the pinned-tier rows are the knob's own verdicts)",
          [r[1] for r in gate] == ["Observe", "Warn", "Deny", "Deny", "Ask",
                                   "Deny"],
          repr(gate))
    check("t2c a manifest holding no phase and a plan holding phases with none "
          "running are two rows, warn and deny, and the deny row says the free "
          "file stays and names the command that adds a phase",
          "no phase" in gate[1][0] and gate[1][1] == "Warn"
          and "none running" in gate[2][0] and gate[2][1] == "Deny"
          and "free file" in gate[2][2] and "/audit:phase add" in gate[2][2],
          repr(gate[1:3]))
    check("t2b the page says what the knob is and that it beats the legacy flag",
          any("planGate" in p and "enforce" in p
              for p in tps["gate-tiers"]["paragraphs"]))
    check("t3 the areas rule is the pinned sentence itself, so the drawer cannot "
          "state a different one from the four docs",
          any(_areas.REVIEW_RULE in p for p in tps["areas"]["paragraphs"])
          and any(_areas.SKILLS_RULE in p for p in tps["areas"]["paragraphs"]))
    arows = tps["areas"]["table"]["rows"]
    check("t4 ...and the worked example is resolved, so a precedence change moves "
          "the page: the area answers P1, meta answers P2, and an explicit null "
          "on P3 is an answer",
          [r[1] for r in arows] == ["backend-review", "house-review", "— none —"]
          and [r[2] for r in arows] == ["area api", "meta", "phase"], repr(arows))
    check("t5 the executor skills in that example are area-first, deduped",
          arows[0][3] == "python-conventions, sql-review", repr(arows[0]))
    prows = tps["policy"]["table"]["rows"]
    check("t6 the policy example is resolved by the GUARD's resolver, in the "
          "guard's own words",
          [r[1] for r in prows] == ["Allowed", "Refused", "Allowed", "Allowed",
                                    "Refused"], repr([r[1] for r in prows]))
    check("t7 ...including the required rule, which no policy can override",
          "required by audit" in prows[0][2], repr(prows[0]))
    check("t8 deny beats allow: `code-danger` is refused although `code-*` "
          "allows it", "deny lists 'code-danger'" in prows[1][2], repr(prows[1]))
    check("t9 the four limits are NAMED and cited, never restated - one wording "
          "to keep true, and it lives in SECURITY.md",
          any(s.endswith("SECURITY.md") for s in tps["policy"]["sources"])
          and any("hooks cannot gate hooks" in p
                  for p in tps["policy"]["paragraphs"]))
    check("t10 the journal page's row shape comes from the writer that produces "
          "it", all(("`%s`" % k) in tps["journal"]["paragraphs"][0]
                    for k in ("v", "ts", "actor", "action", "target", "summary",
                              "stateHash", "prev", "hash")),
          tps["journal"]["paragraphs"][0])
    check("t11 ...and it says what verify can and cannot see, in the words the "
          "feature uses everywhere else",
          any("FINDING" in p and "WARNING" in p
              for p in tps["journal"]["paragraphs"])
          and any("smoke detector, not a vault" in p
                  for p in tps["journal"]["paragraphs"]))
    check("t12 every topic is JSON-serialisable - it is served over HTTP",
          isinstance(json.dumps(M.topics()), str))

    # --- citations ----------------------------------------------------------------
    # `plugin_root()` used to be `dirname(_HERE)`, spelled off this module's own
    # `__file__`; it is `_output.PLUGIN_ROOT` now. This case recomputed that OLD
    # expression, which was the right way to ask the question for exactly as long as
    # `_help.py` sat at the top of `scripts/`.
    #
    # IT NO LONGER DOES, AND THAT IS THE FINDING RATHER THAN AN INCONVENIENCE - the
    # same one `an7`/`an8` record in `test__output.py`. `dirname(dirname(__file__))`
    # is a claim about HOW DEEP A FILE SITS, and `_help.py` is now `scripts/config/`,
    # so the old expression yields `scripts/` and would fail a `plugin_root()` that is
    # perfectly correct. Recomputing it here would no longer measure "the anchor equals
    # what the old code produced"; it would measure that the old code is precisely the
    # thing the path preamble replaced.
    #
    # So the claim is respelled DEPTH-INDEPENDENTLY, and it is not weaker: the plugin
    # root is the directory holding `scripts/`, it is the one `_output` anchor rather
    # than a second computation of it, and it really carries the schemas every citation
    # below resolves against. A `plugin_root()` that drifted by one level fails all
    # three - which is what the old expression was there to catch.
    check("pr1 plugin_root() is the ONE `_output` anchor, and it is the plugin "
          "directory the schemas and reference pages hang off - asserted without "
          "respelling how deep this module sits, because it now sits in "
          "`scripts/config/` and the old `dirname(dirname(__file__))` would fail a "
          "correct answer: %r" % (M.plugin_root(),),
          M.plugin_root() == M._output.PLUGIN_ROOT
          and M.plugin_root() == os.path.dirname(M._output.SCRIPTS_DIR)
          and os.path.basename(M.plugin_root()) == "audit"
          and os.path.isfile(os.path.join(M.plugin_root(), "schema",
                                          "audit-plan.schema.json")))
    check("pr1b ...and this module really is AT DEPTH, so pr1 is not quietly asking "
          "the flat-tree question any more. The old expression is recomputed here "
          "purely to show it now disagrees - if `_help.py` ever returns to the top "
          "of `scripts/` this goes red and pr1's rewrite can be reconsidered",
          os.path.basename(os.path.dirname(os.path.abspath(M.__file__))) == "config"
          and os.path.dirname(os.path.dirname(os.path.abspath(M.__file__)))
          != M.plugin_root())
    check("pr2 ...and an explicit root still wins, which is what lets the two "
          "drift lints below be pointed at a fixture",
          M.plugin_root("/nowhere") == "/nowhere")
    # Nine fixtures, one per thing the lint can say. Fixtures rather than the real
    # module: mutating the shipped vocabulary to prove a lint would leave the tree
    # one exception away from shipping the mutation.
    _anch = (("KNOWN_X", "meta"),)

    def _probe(levels, sets, off):
        """Just the problems, against one anchor — the set name is `KNOWN_X` in
        every fixture, so carrying it into each expected list is noise."""
        return [p for _, p in L.vocab_drift(levels, sets, _anch, off)]
    check("v4 ...and a key the set holds that the schema does not, unexcused - a "
          "typo in the vocabulary is otherwise invisible",
          len(_probe({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a", "z"}}, {})) == 1
          and "'z' is in the set and not in the schema"
          in _probe({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a", "z"}}, {})[0])
    check("v5 an anchor that declares NOTHING is drift, not agreement - a renamed "
          "$def would otherwise turn that level into a comparison against nothing "
          "and pass for any set",
          _probe({"KNOWN_X": set()}, {"KNOWN_X": {"a"}}, {}) ==
          ["the anchor 'meta' declares no properties in audit-plan.schema.json - "
           "a comparison against nothing passes for any set"])
    check("v6 an exemption the schema has since grown is reported, so the list "
          "cannot keep excusing a key that is now real",
          _probe({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a"}},
                 {"KNOWN_X": {"a": "r"}}) ==
          ["OFF_SCHEMA excuses 'a', but the schema now declares it - drop the "
           "exemption"])
    check("v7 ...and one whose key the set no longer holds",
          _probe({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a"}},
                 {"KNOWN_X": {"q": "r"}}) ==
          ["OFF_SCHEMA excuses 'q', which the set no longer holds - drop the "
           "exemption"])
    check("v8 ...and a blank reason, because an exemption list without reasons is "
          "where a lint goes to die",
          _probe({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a", "z"}},
                 {"KNOWN_X": {"z": "  "}}) ==
          ["OFF_SCHEMA excuses 'z' with no reason"])
    check("v9 a KNOWN_* set with no anchor is named, so one added later cannot "
          "opt out of the check by being forgotten",
          _probe({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a"}, "KNOWN_Y": {"b"}}, {}) ==
          ["no SCHEMA_ANCHORS entry: nothing says where in "
           "audit-plan.schema.json this set is defined"])
    check("v10 ...an OFF_SCHEMA entry for a set nothing anchors, and an anchor "
          "naming a set the vocabulary does not have - the two halves of the "
          "table disagreeing in either direction",
          _probe({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a"}},
                 {"KNOWN_Z": {"b": "r"}}) ==
          ["OFF_SCHEMA excuses keys for a set SCHEMA_ANCHORS does not anchor"]
          and _probe({"KNOWN_X": {"a"}}, {}, {}) ==
          ["SCHEMA_ANCHORS anchors it at 'meta', but the vocabulary has no such "
           "set"])

    # --- the guide agent ----------------------------------------------------------
    cards = {c["name"]: c for c in M.agent_cards()}
    check("g1 every shipped agent is read off its own file",
          {"audit-executor", "audit-explorer", "audit-reviewer", M.GUIDE}
          <= set(cards), repr(sorted(cards)))
    guide = M.guide_card()
    check("g2 the guide's card carries the tools its FILE grants, so a hint "
          "cannot advertise a capability it does not have",
          guide and sorted(guide["tools"]) == sorted(M.READ_ONLY_TOOLS),
          repr(guide and guide["tools"]))
    # `(guide or {})`, not `guide[...]`: an install with no guide is exactly what a
    # deleted agent file looks like, and a check that dies subscripting None exits 1
    # with a traceback instead of naming the defect — which is how a mutation that
    # "goes red" ends up proving nothing.
    check("g4 the model and an effort of high or above are declared in the file",
          (guide or {}).get("model") == "haiku"
          and (guide or {}).get("effort") in ("high", "xhigh", "max"),
          repr(guide))
    check("g5 it is spelled the way a policy or a Task call would name it",
          (guide or {}).get("qualified") == "audit:guide")
    check("g6 an install without the agent gets None, not a hint pointing at "
          "nothing", M.guide_card(os.path.join(M._output.SCRIPTS_DIR, "_nope")) is None)
    check("g7 the guide is REQUIRED by the policy resolver, because it is read "
          "off the agents directory - so a deny-all policy cannot switch off the "
          "one thing that explains the policy",
          "audit:guide" in _policy.required_names()["agents"])

    # --- frontmatter --------------------------------------------------------------
    _fm = os.path.join(M._output.SCRIPTS_DIR, "_helpfm.md")
    try:
        with open(_fm, "w", encoding="utf-8") as fh:
            fh.write("---\nname: x\ndescription: 'a: b'\ntools: Read, Grep\n"
                     "---\nbody: not frontmatter\n")
        front = M._frontmatter(_fm)
        check("f1 a value containing a colon survives - every command in this "
              "plugin once loaded with EMPTY metadata for exactly that reason",
              front["description"] == "a: b", repr(front))
        check("f2 the body is not read as frontmatter", "body" not in front)
        with open(_fm, "w", encoding="utf-8") as fh:
            fh.write("no frontmatter here\n")
        check("f3 a file without frontmatter yields nothing rather than a guess",
              M._frontmatter(_fm) == {})
    finally:
        if os.path.exists(_fm):
            os.remove(_fm)

    # front_matter(text): the merged parser's edge cases (the one used to be
    # two -- _help._frontmatter and panel-server._front_matter -- that quietly
    # disagreed on these).
    check("f4 CRLF frontmatter parses the same as LF",
          M.front_matter("---\r\nname: x\r\ndescription: y\r\n---\r\nbody\r\n")
          == {"name": "x", "description": "y"})
    check("f5 a doubled single-quote inside a quoted scalar is the YAML escape, "
          "not a new field -- this is unquote_scalar's integration, not just "
          "its unit behavior",
          M.front_matter("---\ndescription: 'the plugin''s own README'\n---\n")
          == {"description": "the plugin's own README"})
    check("f6 an indented continuation line is skipped -- even one that looks "
          "like its own 'key: value' -- and the key after it still parses; "
          "this is the more-correct behavior of the two prior parsers",
          M.front_matter("---\nname: x\n  fake: not-a-field\ndescription: y\n"
                       "---\n") == {"name": "x", "description": "y"})
    check("f7 a frontmatter block over 4KB still parses in full -- nothing "
          "here caps the block itself, only a caller's read of the file",
          M.front_matter("---\n" + "".join(
              "key%03d: value%03d\n" % (i, i) for i in range(400)
          ) + "---\nbody\n") == dict(
              ("key%03d" % i, "value%03d" % i) for i in range(400)))
    check("f8 no closing fence yields {} rather than a partial parse",
          M.front_matter("---\nname: x\ndescription: y\n") == {})
    check("f9 text with no frontmatter fence at all yields {}",
          M.front_matter("just a body, no fence\n") == {})

    # --- the payload --------------------------------------------------------------
    pay = M.payload()
    _tbl = M.tables()["fields"]
    check("p1 the payload carries the topics, the agent, the lever map and the "
          "schema names - and the tables are read through tables()",
          set(pay) == {"composition", "topics", "agent", "schemas"}
          and _tbl["config"] and _tbl["manifest"]
          and len(pay["topics"]) == 4
          and (pay["agent"] or {}).get("name") == M.GUIDE)
    # The drawer asks `GET /api/help?path=` for each field it opens, so a whole
    # table in the payload is bytes sent for nobody. The oracle for "read" is the
    # drawer's own source: every key of the payload must be reached as `doc.<key>`
    # there, and no table may be.
    with open(os.path.join(M.plugin_root(), "scripts", "ui", "panel",
                           "help-drawer.js"), encoding="utf-8") as _fh:
        _drawer_reads = set(re.findall(r"\bdoc\.(\w+)", _fh.read()))
    _one = M.entry_for("trivialLineThreshold")
    check("the help payload carries no table the drawer does not read, and a "
          "field is answered through the per-path endpoint",
          not set(pay) - _drawer_reads
          and "fields" not in pay and "aliases" not in pay
          and (_one or {}).get("entry", {}).get("default") == 80
          and (_one or {}).get("entry") ==
          M.tables()["fields"]["config"]["trivialLineThreshold"],
          "payload keys %r, the drawer reads %r"
          % (sorted(pay), sorted(_drawer_reads)))
    check("p2 a field's default rides along, so an empty box means something",
          _tbl["config"]["trivialLineThreshold"]["default"] == 80)
    check("p3 fields link to the concept page that explains them",
          _tbl["config"]["policy.skills.deny"]["topic"] == "policy"
          and _tbl["config"]["journal.enabled"]["topic"] == "journal"
          and _tbl["config"]["enforce"]["topic"] == "gate-tiers"
          and _tbl["manifest"]["meta.areas"]["topic"] == "areas")
    check("p3b planGate is documented and opens the gate page, beside the "
          "legacy flag it replaces",
          _tbl["config"].get("planGate", {}).get("topic") == "gate-tiers"
          and "ask" in (_tbl["config"].get("planGate", {})
                        .get("enum") or []))
    check("p4 ...and every topic a field names exists",
          not [p for p, e in list(_tbl["config"].items())
               + list(_tbl["manifest"].items())
               if e.get("topic") and e["topic"] not in
               {t["id"] for t in pay["topics"]}])
    # Three builds, one size: natively, from CRLF sources, and with a backslash
    # separator. A payload a few bytes larger on one platform is how the cap was
    # crossed on one CI leg while the other read under it.
    _p5 = (_payload_bytes(), _payload_bytes(_crlf_root()),
           _backslash_payload_bytes())
    check("p5 the help payload measures the same on every platform and stays "
          "under its budget with stated headroom (native, CRLF sources and a "
          "backslash os.sep build one size, and at least PAYLOAD_HEADROOM bytes "
          "of PAYLOAD_CAP stay free)",
          len(set(_p5)) == 1 and _p5[0] <= PAYLOAD_CAP - PAYLOAD_HEADROOM,
          "native/crlf/backslash %r, cap %d, headroom owed %d"
          % (_p5, PAYLOAD_CAP, PAYLOAD_HEADROOM))
    # p5 swaps `os` at call time, after every module-level constant was bound with
    # the real separator, so it cannot see a path built at import. This loads the
    # module afresh while `os.path.join` is Windows' own, so import-time constants
    # are built the Windows way, then scans the strings it serves: a backslash
    # between two path words is a Windows spelling whatever built it. (Only the
    # served constants are scanned: `payload()` itself would try to open the
    # backslash path on a posix host.) The control
    # half feeds the scan a known Windows-spelled path - without it a scan that
    # matches nothing would pass over everything.
    import ntpath
    import _loader
    # Absolute anchors keep the real join so the import preamble can still find
    # its siblings on a posix host; every relative join is spelled Windows-style.
    _fresh = _run_with_nt_join(
        lambda: _loader.load(M.__file__, "_help_ntpath_probe", cache=False))
    _fresh_hits = _backslash_paths(
        {"schemas": dict(_fresh.SCHEMAS), "agent": _fresh.guide_card()})
    _control = _backslash_paths({"schemas": {"config": ntpath.join(
        "schema", "audit-config.schema.json")}})
    check("Spell SCHEMAS with '/' (load_schema already joins it under root, "
          "which opens on both platforms), as was done for the agent card's file "
          "(a module imported under Windows' os.path.join serves no "
          "backslash-separated plugin path, the scan flags one when present, "
          "and both schemas still open)",
          not _fresh_hits and len(_control) == 1
          and all(M.load_schema(k) for k in M.SCHEMAS),
          "fresh-import hits %r, control %r" % (_fresh_hits, _control))
    # Simulate a host whose `os.path` IS `ntpath` on a posix runner. A recursion
    # is caught and reported as a failure rather than aborting the suite.
    _sim_real_path = os.path
    _sim_join = ntpath.join
    _sim_out = None
    _sim_err = None
    os.path = ntpath
    try:
        _sim_out = _run_with_nt_join(lambda: os.path.join("schema", "x.json"))
    except RecursionError as exc:
        _sim_err = "RecursionError: %s" % exc
    finally:
        os.path = _sim_real_path
        ntpath.join = _sim_join
    check("the module-level backslash probe binds the real ntpath.join before "
          "swapping os.path.join, so on a host whose os.path is ntpath it does "
          "not call itself (os.path simulated as ntpath; the probe completes "
          "with no RecursionError and still flags the backslash control)",
          _sim_err is None and _sim_out == "schema\\x.json"
          and len(_control) == 1 and ntpath.join is _sim_join,
          "simulated join %r, error %r, control %r"
          % (_sim_out, _sim_err, _control))
    check("p6 it names where the field text came from, so a reader can go read "
          "the source", pay["schemas"]["config"].endswith(".json"))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__help.py --selftest\n")
    raise SystemExit(2)
