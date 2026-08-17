#!/usr/bin/env python3
"""
The cases for `scripts/_help.py`, moved out of it - an importable helper.

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
    `scripts/_areas.py`, `scripts/_policy.py` and `scripts/audit-journal.py`,
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
    # `__file__`; it is `_output.PLUGIN_ROOT` now. Same string on a flat tree, and
    # this recomputes the OLD expression rather than asserting the new one reads
    # right - every citation case below resolves through it.
    check("pr1 plugin_root() is what the old `dirname(_HERE)` produced, and it is "
          "the plugin directory the schemas and reference pages hang off: %r"
          % (M.plugin_root(),),
          M.plugin_root()
          == os.path.dirname(os.path.dirname(os.path.abspath(M.__file__)))
          and os.path.basename(M.plugin_root()) == "audit"
          and os.path.isfile(os.path.join(M.plugin_root(), "schema",
                                          "audit-plan.schema.json")))
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
