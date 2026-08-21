#!/usr/bin/env python3
"""
The cases for `_help.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `_areas` and `_policy` are imported the way `_help.py`
imports them, because three cases compare against those modules' own objects
(`_areas.REVIEW_RULE`, `_policy.required_names()`).

THREE THINGS ABOUT THIS SUITE READ THE REPOSITORY, AND ALL THREE STILL RESOLVE.

  * the scripts directory was `_help.py`'s own `_HERE` constant, and the suite
    used it four times as SCRATCH SPACE: `_helpdoc/` and `_helpagents/` (fake
    plugin roots the two drift lints are pointed at), `_helpfm.md` (a frontmatter
    fixture) and `_nope` (a plugin root that must not exist). Carried literally
    they would name `tests/` - which for scratch paths resolves correctly BY
    COINCIDENCE, and that is exactly the shape the guide says to spell about the
    subject instead. They read the ONE anchor through the module under test, so
    each one still says "beside the module under test".
  * `plugin_root()` is `_help.py`'s own function (now `_output.PLUGIN_ROOT`), so every
    case that reads a real document - `source_drift()` over `README.md`,
    `SECURITY.md`, `../../PLUGIN-BUILD-GUIDE.md` and the `reference/` pages,
    `agent_doc_drift()` over `agents/*.md` - resolves off the SUBJECT's location
    and needed no change at all. Verified rather than assumed: `M.plugin_root()`
    is `plugins/audit` when this file is run from `tests/`, and `c1`/`a1` are the
    cases that go red if it ever is not.
  * three of the citations `c1` checks are the plugin-relative literals
    `_areas.py`, `_policy.py` and `audit-journal.py`,
    written out in `_help.topics()`. They stay literals and stay in the PRODUCT:
    they are among the only places in the tree that assert a `scripts/` path
    exists, and going red when one of those files is renamed is the feature.

ONE IMPORT EDGE RETIRED WITH THIS MOVE. `s8`'s `import _panel_settings` was the
only thing in `_help.py` naming that module, and `_deps` walks the whole AST -
selftest included - so it was a real static edge until now. It was downward
(L3 -> L2), so no `KNOWN_LAYER_DEBT` entry went with it, but the generated module
map fence in `PLUGIN-BUILD-GUIDE.md` lost the line and was regenerated.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _areas                                      # noqa: E402  (as _help imports it)
import _policy                                     # noqa: E402  (as _help imports it)
import _manifest_vocab as _vocab                   # noqa: E402  (as _help imports it)
import _help as M                                  # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- extraction ---------------------------------------------------------------
    cfg = M.config_fields()
    man = M.manifest_fields()
    check("s1 the config schema yields dotted paths with their own words",
          cfg["usage.pricingAsOf"]["description"].startswith("Date the pricing")
          or "pricing" in cfg["usage.pricingAsOf"]["description"],
          repr(cfg.get("usage.pricingAsOf")))
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
        # the remaining 59 cases with it.
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
    check("e4 the enrichment is the payload's own - a lookup and the full payload "
          "cannot describe one field differently",
          M.entry_for("trivialLineThreshold")["entry"] ==
          M.payload()["fields"]["config"]["trivialLineThreshold"])
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
          [r[1] for r in gate] == ["Observe", "Warn", "Deny", "Ask", "Deny"],
          repr(gate))
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

    drift = M.source_drift()
    check("c1 every citation resolves to a file and, where it names one, to a "
          "real heading: %r" % (drift,), not drift)
    _fake = os.path.join(M._output.SCRIPTS_DIR, "_helpdoc")
    os.makedirs(_fake, exist_ok=True)
    try:
        with open(os.path.join(_fake, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("# audit\n\n## Something else entirely\n")
        _d = M.source_drift(_fake)
        check("c2 the citation lint can fail - a renamed heading is caught rather "
              "than shipped as a dead link",
              len([x for x in _d if x[2] == "no heading with that anchor"]) >= 3,
              repr(_d))
    finally:
        import shutil
        shutil.rmtree(_fake, ignore_errors=True)

    # --- the manifest vocabulary against the schema -------------------------------
    # `_manifest_vocab`'s KNOWN_* sets restate vocabulary this schema owns, and the
    # comparison lives here because the walk does: the vocabulary is at layer 1 and
    # `fields()` is at layer 2, so it could not reach up for it. The cases that
    # assert the SHIPPED sets agree are in `test__manifest_vocab.py`, beside the
    # thing a reader is editing; these prove the comparison itself can fail, which
    # a green-only lint never does.
    check("v1 an anchor yields the properties ONE level under it - `types` and "
          "not `types.bug`, which belongs to a different question",
          M._direct_children(man, "meta.ado") >= {"organization", "types",
                                                  "stateMap"}
          and "types.bug" not in M._direct_children(man, "meta.ado")
          and "bug" not in M._direct_children(man, "meta.ado"),
          repr(sorted(M._direct_children(man, "meta.ado"))))
    check("v2 ...the document root is the empty anchor, and `<name>` is a SHAPE "
          "rather than a key anybody writes, so it is dropped",
          M._direct_children(man, "") == {"$schema", "meta", "phases", "bugs",
                                          "deferred", "fileIndex", "proposals"}
          and "<name>" not in M._direct_children(man, "fileIndex"),
          repr(sorted(M._direct_children(man, ""))))
    # Nine fixtures, one per thing the lint can say. Fixtures rather than the real
    # module: mutating the shipped vocabulary to prove a lint would leave the tree
    # one exception away from shipping the mutation.
    _anch = (("KNOWN_X", "meta"),)

    def _probe(levels, sets, off):
        """Just the problems, against one anchor — the set name is `KNOWN_X` in
        every fixture, so carrying it into each expected list is noise."""
        return [p for _, p in M.vocab_drift(levels, sets, _anch, off)]

    check("v3 a property the schema declares and the set does not is named, with "
          "its anchor - the failure that prompted this whole check",
          _probe({"KNOWN_X": {"a", "b"}}, {"KNOWN_X": {"a"}}, {}) ==
          ["meta.b is in the schema and not in the set - add it, or the "
           "typo-catcher warns about a real key"])
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
    check("v11 ...and an agreeing table says nothing at all - the case that fails "
          "if any of v3-v10 is firing on everything",
          M.vocab_drift({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a"}}, _anch, {}) == [])
    check("v12 `vocab_sets()` reads the sets OFF the module rather than listing "
          "them, so v9 has something to catch",
          M.vocab_sets(_vocab) == dict((n, getattr(_vocab, n)) for n in
                                       ("KNOWN_ROOT", "KNOWN_META", "KNOWN_ADO",
                                        "KNOWN_BRANCH",
                                        "KNOWN_PHASE", "KNOWN_TASK", "KNOWN_BUG",
                                        "KNOWN_PROPOSAL")),
          repr(sorted(M.vocab_sets(_vocab))))

    # --- the RECOMMENDED subsets, which are checked the other way round -----------
    # `vocab_drift()` asks for coverage; `subset_drift()` asks only for containment,
    # because a set whose job is to name SOME of a level's keys would fail a coverage
    # check while behaving perfectly. Same fixture discipline: the shipped tuple is
    # never mutated, so the tree is never one exception away from shipping a mutation.
    _sub = (("CLAIM_X", "phases[].claim"),)

    def _sprobe(levels, sets):
        """Just the problems, against one anchor — the set is `CLAIM_X` in every
        fixture, so carrying its name into each expected list is noise."""
        return [p for _, p in M.subset_drift(levels, sets, _sub)]

    check("v13 a key the set recommends and the schema does not declare is named "
          "with its anchor - the typo that would otherwise stop the key being "
          "asked for at all, in silence",
          _sprobe({"CLAIM_X": {"sessionId", "host"}},
                  {"CLAIM_X": ("sessionID", "host")}) ==
          ["phases[].claim.sessionID is recommended by this set and not declared "
           "by the schema - a typo here does not warn, it stops the key being "
           "asked for at all"])
    # THE CASE THE WHOLE SPLIT EXISTS FOR. If this ever goes red the check has
    # started failing the correct state, which is how a guard gets routed around.
    _lv = {"CLAIM_X": {"sessionId", "host", "branch", "at"}}
    _st = {"CLAIM_X": ("sessionId", "host", "branch")}
    check("v14 a PROPER subset says nothing - the schema declaring `at` and the "
          "set not recommending it is the rule working; the coverage check on the "
          "same fixture DOES name it, which is the difference between the two",
          M.subset_drift(_lv, _st, _sub) == []
          and [p for _, p in M.vocab_drift(_lv, _st, _sub, {})
               if "phases[].claim.at is in the schema" in p],
          repr((M.subset_drift(_lv, _st, _sub),
                M.vocab_drift(_lv, _st, _sub, {}))))
    check("v15 an anchor that declares NOTHING is named AS ITSELF - it would fail "
          "either way, since every key is then undeclared, so what this buys is the "
          "diagnosis: a renamed $def reads as one move in the schema instead of "
          "three typos in the vocabulary",
          _sprobe({"CLAIM_X": set()}, {"CLAIM_X": ("sessionId",)}) ==
          ["the anchor 'phases[].claim' declares no properties in "
           "audit-plan.schema.json - a containment check against nothing passes "
           "for any set"])
    check("v16 ...and an EMPTY SET is the direction that would otherwise PASS - "
          "containment over no keys holds vacuously while the rule reading it asks "
          "for nothing, so emptying the tuple silently disables the warning it "
          "feeds. This is the asymmetric half of v15",
          _sprobe({"CLAIM_X": {"sessionId"}}, {"CLAIM_X": ()}) ==
          ["the set is empty, so the rule reading it asks for nothing and reports "
           "no key missing - indistinguishable from every key being present"])
    check("v17 a *_KEYS subset with no anchor is named, and an anchor naming a "
          "subset the vocabulary does not have - the two halves of the table "
          "disagreeing in either direction",
          _sprobe({"CLAIM_X": {"a"}}, {"CLAIM_X": ("a",), "OTHER_KEYS": ("b",)}) ==
          ["no SUBSET_ANCHORS entry: nothing says which schema level this "
           "recommended subset is drawn from"]
          and _sprobe({"CLAIM_X": {"a"}}, {}) ==
          ["SUBSET_ANCHORS anchors it at 'phases[].claim', but the vocabulary has "
           "no such set"])
    check("v18 `vocab_subsets()` reads them OFF the module by the `*_KEYS` suffix, "
          "so v17 has something to catch - and the VALUE enumerations beside them "
          "(STATUS, RISK, the *_RE patterns) are not swept in as key sets",
          M.vocab_subsets(_vocab) == {"CLAIM_KEYS": _vocab.CLAIM_KEYS},
          repr(sorted(M.vocab_subsets(_vocab))))

    # --- the vocabularies that are LITERALS AT THEIR CALL SITE --------------------
    # A third shape, and the one neither table above can reach: the `meta.ado`
    # sub-objects have no named set anywhere, so `vocab_sets()` and `vocab_subsets()`
    # are blind to both of them and the vocabulary is the ARGUMENT a call passes.
    # Fixtures again, and for the reason v3-v18 use them: proving a lint by mutating
    # what it guards leaves the tree one exception away from carrying the mutation.
    _src = ('def check_it(ado, w):\n'
            '    _unknown_keys(ado, {"team", "mode"}, "meta.ado.sprint", w)\n'
            '    _unknown_keys(ado, set(vocab), "meta.ado.stateMap", w)\n'
            '    _unknown_keys(ado, KNOWN_ADO, "meta.ado", w)\n'
            '    _unknown_keys(ado, {"x"}, "%s" % kind, w)\n')
    _scan = M.inline_vocabularies({"a.py": _src})
    check("v19 a literal vocabulary is read off the CALL, with the file and line it "
          "is written on - and the three shapes beside it are declined, because a "
          "computed set needs a value the parser does not have and a NAMED one is "
          "`schema_vocab_drift()`'s question rather than this one",
          _scan == {"found": {"meta.ado.sprint":
                              {"keys": {"team", "mode"},
                               "sites": [("a.py:2", ("mode", "team"))]}},
                    "problems": []}, repr(_scan))
    _bad = M.inline_vocabularies({"a.py": "def (:\n"})
    check("v20 ...and a file the parser cannot read is NAMED rather than skipped: "
          "silence there would shrink what the scan looked at without shrinking the "
          "claim made about it",
          _bad["found"] == {} and len(_bad["problems"]) == 1
          and _bad["problems"][0][0] == "a.py"
          and "does not parse" in _bad["problems"][0][1], repr(_bad))
    _two = M.inline_vocabularies(
        {"a.py": '_unknown_keys(o, {"team"}, "meta.ado.sprint", w)\n',
         "b.py": '_unknown_keys(o, {"team", "mode"}, "meta.ado.sprint", w)\n'})
    check("v21 two call sites for one level are unioned AND their disagreement is "
          "named - a union on its own would hide the fork it was built out of, "
          "which is the failure a second copy of a vocabulary always is",
          _two["found"]["meta.ado.sprint"]["keys"] == {"team", "mode"}
          and [p for _w, p in M.inline_drift({"meta.ado.sprint": {"team", "mode"}},
                                             _two["found"], ("meta.ado.sprint",))]
          == ["call sites pass different vocabularies for this level, so one of "
              "them is already wrong: a.py:1 ['team'], b.py:1 ['mode', 'team']"],
          repr(_two))

    _ianch = ("meta.ado.sprint",)

    def _iprobe(levels, found):
        """Just the problems, against one anchor — the path is `meta.ado.sprint` in
        every fixture, so carrying it into each expected list is noise."""
        return [p for _w, p in M.inline_drift(levels, found, _ianch)]

    def _site(*keys):
        """One call site passing `keys`, shaped as `inline_vocabularies()` returns."""
        return {"keys": set(keys), "sites": [("a.py:1", tuple(sorted(keys)))]}

    check("v22 a property the schema declares and no call site names is reported "
          "with its path - the literal is the `known` argument of `_unknown_keys`, "
          "so a key missing from it makes the validator warn about a real key",
          _iprobe({"meta.ado.sprint": {"team", "mode"}},
                  {"meta.ado.sprint": _site("team")}) ==
          ["meta.ado.sprint.mode is in the schema and no call site names it - add "
           "it, or the typo-catcher warns about a real key"])
    check("v23 ...and ONE typo lands as BOTH problems, which is what a typo here "
          "actually costs: the real key stops being recognised and the misspelling "
          "starts being accepted",
          _iprobe({"meta.ado.sprint": {"team", "mode"}},
                  {"meta.ado.sprint": _site("team", "moed")}) ==
          ["meta.ado.sprint.mode is in the schema and no call site names it - add "
           "it, or the typo-catcher warns about a real key",
           "'moed' is passed here and the schema does not declare it at "
           "meta.ado.sprint - add it to the schema, or the key it was meant to be "
           "is the one going unwarned"])
    check("v24 a declared level with NO call site is the direction that would "
          "otherwise pass in silence: a comparison over nothing found reports "
          "nothing wrong, so deleting the call reads exactly like agreement",
          _iprobe({"meta.ado.sprint": {"team"}}, {}) ==
          ["declared here, but no `_unknown_keys()` call under scripts/ passes a "
           "literal set at this path - the check has stopped covering the level, "
           "which is not the same as finding it clean"])
    check("v25 ...and an anchor that declares no properties is named AS ITSELF, so "
          "a renamed level reads as one move in the schema rather than as a "
          "vocabulary full of typos",
          _iprobe({"meta.ado.sprint": set()}, {"meta.ado.sprint": _site("team")}) ==
          ["the anchor declares no properties in audit-plan.schema.json - a "
           "comparison against nothing passes for any set"])
    check("v26 a literal found at a path INLINE_ANCHORS does not declare is named "
          "with its site, so a nested vocabulary added later cannot opt out of the "
          "check by being forgotten - the half a hand-written table cannot do",
          _iprobe({"meta.ado.sprint": {"team"}},
                  {"meta.ado.sprint": _site("team"),
                   "meta.ado.pull": _site("tags")}) ==
          ["an inline vocabulary at a.py:1 that INLINE_ANCHORS does not declare - a "
           "level nothing compares is where this whole class of drift starts"])
    check("v27 ...and a level that agrees says nothing at all - the case that fails "
          "if any of v22-v26 has started firing on everything",
          M.inline_drift({"meta.ado.sprint": {"team", "mode"}},
                         {"meta.ado.sprint": _site("team", "mode")}, _ianch) == [])

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
    check("g3 the guide is mechanically read-only - an answering agent with an "
          "edit tool would be a writer with no plan, no lock and no journal row",
          M.guide_is_read_only() and (guide or {}).get("readOnly") is True)
    # `(guide or {})`, not `guide[...]`: an install with no guide is exactly what a
    # deleted agent file looks like, and a check that dies subscripting None exits 1
    # with a traceback instead of naming the defect — which is how a mutation that
    # "goes red" ends up proving nothing.
    check("g4 it is cheap by declaration: the model and effort are in the file",
          (guide or {}).get("model") == "haiku"
          and (guide or {}).get("effort") == "low", repr(guide))
    check("g5 it is spelled the way a policy or a Task call would name it",
          (guide or {}).get("qualified") == "audit:guide")
    check("g6 an install without the agent gets None, not a hint pointing at "
          "nothing", M.guide_card(os.path.join(M._output.SCRIPTS_DIR, "_nope")) is None)
    check("g7 the guide is REQUIRED by the policy resolver, because it is read "
          "off the agents directory - so a deny-all policy cannot switch off the "
          "one thing that explains the policy",
          "audit:guide" in _policy.required_names()["agents"])

    # --- agent enumeration in the docs --------------------------------------------
    adrift = M.agent_doc_drift()
    check("a1 every doc that enumerates the agents names all of them, and any "
          "count it states agrees with the directory: %r" % (adrift,), not adrift)
    _fake2 = os.path.join(M._output.SCRIPTS_DIR, "_helpagents")
    os.makedirs(os.path.join(_fake2, "agents"), exist_ok=True)
    try:
        for _n in ("alpha", "beta"):
            with open(os.path.join(_fake2, "agents", _n + ".md"), "w",
                      encoding="utf-8") as fh:
                fh.write("---\nname: %s\ntools: Read\n---\nbody\n" % _n)
        with open(os.path.join(_fake2, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("It ships three pinned-tool agents, one of them alpha.\n")
        _d2 = M.agent_doc_drift(_fake2)
        check("a2 the lint catches an agent no doc mentions",
              any("does not name the beta agent" in x[1] for x in _d2), repr(_d2))
        check("a3 ...and a count that has gone stale, which is how this one "
              "actually rots", any("says 'three' pinned-tool agents" in x[1]
                                   for x in _d2), repr(_d2))
    finally:
        import shutil
        shutil.rmtree(_fake2, ignore_errors=True)

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
    check("p1 the payload carries both schemas' fields, the topics and the agent",
          set(pay) == {"fields", "composition", "topics", "agent", "schemas"}
          and pay["fields"]["config"] and pay["fields"]["manifest"]
          and len(pay["topics"]) == 4
          and (pay["agent"] or {}).get("name") == M.GUIDE)
    check("p2 a field's default rides along, so an empty box means something",
          pay["fields"]["config"]["trivialLineThreshold"]["default"] == 80)
    check("p3 fields link to the concept page that explains them",
          pay["fields"]["config"]["policy.skills.deny"]["topic"] == "policy"
          and pay["fields"]["config"]["journal.enabled"]["topic"] == "journal"
          and pay["fields"]["config"]["enforce"]["topic"] == "gate-tiers"
          and pay["fields"]["manifest"]["meta.areas"]["topic"] == "areas")
    check("p3b planGate is documented and opens the gate page, beside the "
          "legacy flag it replaces",
          pay["fields"]["config"].get("planGate", {}).get("topic") == "gate-tiers"
          and "ask" in (pay["fields"]["config"].get("planGate", {})
                        .get("enum") or []))
    check("p4 ...and every topic a field names exists",
          not [p for p, e in list(pay["fields"]["config"].items())
               + list(pay["fields"]["manifest"].items())
               if e.get("topic") and e["topic"] not in
               {t["id"] for t in pay["topics"]}])
    check("p5 the whole payload is JSON, and small enough to serve on every open "
          "of a drawer", len(json.dumps(pay)) < 200000, len(json.dumps(pay)))
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
