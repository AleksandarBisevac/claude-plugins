#!/usr/bin/env python3
"""
The cases for `_panel_settings.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

ONE CASE CHANGED SHAPE, AND IT IS THE COVERAGE DIFF. Inline, the case that compares
the bound control paths against validate-config's own key sets was followed by a bare
`if _bound != _expected: print("     missing: ...")` pair - a diagnostic that ran
BETWEEN two `check()` calls, so it printed above a report the suite had not emitted
yet. `_harness.run()` already owns exactly that job through `check(label, cond,
detail)`, which renders on FAILURE only, so the two prints are now that detail. The
label is byte-identical and the information is the same strings; what changed is that
it can no longer print above the report it belongs to. Proven red: dropping a field
from `SETTINGS_GROUPS` fails the case with `missing: ['usage.currency'] | unknown: []`
on the FAIL line.

`_validate_config()` stays a call on `M`: it caches into `M._VC`, and the module's own
`_cfg_enums()` reads that cache. A local copy here would load `validate-config.py` a
second time and the cases would then compare two module objects that merely agree.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _panel_settings as M                        # noqa: E402
import _usage_economics as _ue                     # noqa: E402  (rate_basis_phrase)


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- Settings: the whole config, named by what it does ---------------------
    # The claim this tab makes is "here is the configuration". It was not true: the
    # form covered part of the config and nothing anywhere said which part, so the
    # `usage.*` block and four of five `tddReminder.*` keys were invisible on the one
    # surface built to make them legible.
    #
    # The expected set is DERIVED from validate-config's own key sets rather than
    # listed here. A hand-kept list would be a third place to forget a key — the
    # exact failure this chunk exists to fix, one level up.
    _vc = M._validate_config()
    _containers = {"secretPatterns": _vc.KNOWN_SECRET, "guardEdits": _vc.KNOWN_GUARD,
                   "bashWriteCheck": _vc.KNOWN_BASHW, "tddReminder": _vc.KNOWN_TDD,
                   "usage": _vc.KNOWN_USAGE, "journal": _vc.KNOWN_JOURNAL,
                   "evidence": _vc.KNOWN_EVIDENCE,
                   "priority": _vc.KNOWN_PRIORITY,
                   "executor": _vc.KNOWN_EXECUTOR,
                   "review": _vc.KNOWN_REVIEW, "ci": _vc.KNOWN_CI}
    # `policy` is a root key with no control on this form, on purpose — the one
    # kind of exemption, and it is stated rather than silently subtracted. It is
    # not a setting with a value; it is a rule set whose meaning is the verdict it
    # produces for each installed capability, which is what /api/policy serves and
    # what the **Policy tab** renders, switch by switch. The exemption is pinned
    # below: it must name a key the validator actually knows, or it would silently
    # excuse nothing. (panel-server.py's own selftest confirms it is served by its
    # own endpoint — that needs the server's source, so it stays there.)
    #
    # `enforce` (v0.34 B1) is exempt for the opposite reason: it IS editable from
    # this form, through the planGate control — the select's preset reads the
    # legacy flag, and saving rewrites it as planGate while deleting enforce. A
    # second, dedicated checkbox would be two controls writing one gate, free to
    # disagree about it. The check below pins that the planGate control exists,
    # so this exemption cannot outlive the control that justifies it.
    #
    # `ui` (th) is exempt for the policy reason, not the enforce one: it
    # HAS a surface, and that surface is the Appearance tab — a token editor
    # with a live preview, light/dark pairs and a contrast check. A text field
    # here holding a theme name beside it would be a second control writing the
    # same key, free to disagree with the tab about which theme is on.
    _settings_exempt = {"policy", "enforce", "ui"}
    _expected = {k for k in _vc.KNOWN_ROOT
                 if k not in _containers and k not in _settings_exempt}
    for _parent, _keys in _containers.items():
        _expected |= {"%s.%s" % (_parent, k) for k in _keys}
    # `ci.cadence` is itself an object, edited leaf by leaf (the settings paths
    # are dotted at any depth), so its own keys are expected instead of it.
    _expected.discard("ci.cadence")
    _expected |= {"ci.cadence.%s" % (k,) for k in _vc.KNOWN_CI_CADENCE}
    check("the Settings exemption names a real config key - an exemption for a key "
          "the validator has never heard of excuses nothing and hides the next one",
          _settings_exempt <= _vc.KNOWN_ROOT)
    # The container map above IS hand-kept — there is no machine link from a
    # top-level key to the set of keys inside it — so the one thing it can get
    # wrong is naming a container the validator has never heard of. Then the
    # derived set would keep expecting `journal.*` after `journal` was dropped from
    # KNOWN_ROOT, and this whole check would agree with itself about a key the
    # hooks ignore.
    check("every container the form groups is a real top-level key",
          set(_containers) <= _vc.KNOWN_ROOT)
    _bound = set(M._settings_paths())
    # The diagnostic the inline suite printed between two cases is this detail -
    # `_harness` renders it on failure only, which is where it was wanted anyway.
    check("Settings binds a control to EVERY key the validator accepts - the "
          "missing ones were the whole usage block and most of tddReminder",
          _bound == _expected,
          "missing: %s | unknown: %s"
          % (sorted(_expected - _bound), sorted(_bound - _expected)))
    check("every bound setting has help text, and no help text names a key the "
          "validator does not know",
          set(M.FIELD_HELP) == _bound)
    check("no path is bound twice (a duplicate would render two controls writing "
          "the same key)", len(M._settings_paths()) == len(_bound))
    # Named by what they DO, with the key beside them. Every heading used to BE a
    # JSON path, uppercased by the h2 rule: "GUARDEDITS.TOKENVARS". That reads as a
    # config dump and assumes the schema the reader came here to learn.
    for _g in M.SETTINGS_GROUPS:
        for _f in _g["fields"]:
            check("%r is labelled %r rather than shown as a bare key"
                  % (_f["path"], _f["label"]),
                  bool(_f["label"]) and _f["label"] != _f["path"]
                  and not _f["label"][0].islower())
    check("the groups are the decisions the config makes, not one list",
          tuple(g["id"] for g in M.SETTINGS_GROUPS)
          == ("paths", "guards", "tdd", "usage", "journal", "priority",
              "portability", "executor", "review", "ci")
          and all(g["blurb"] for g in M.SETTINGS_GROUPS))
    check("the audit trail's card states the limit of the claim, where someone "
          "deciding whether to rely on it will read it",
          "not tamper-proof" in dict(
              (g["id"], g["blurb"]) for g in M.SETTINGS_GROUPS)["journal"])
    check("no blurb writes markdown - they are rendered as text, so a backtick "
          "reaches the screen as a backtick",
          not any("`" in g["blurb"] or "**" in g["blurb"]
                  for g in M.SETTINGS_GROUPS))

    # --- the write allow-lists ---------------------------------------------------
    check("the meta form keys exclude the api-only ones",
          set(M._META_FORM_KEYS) == set(M._META_KEYS) - set(M._META_API_ONLY))
    check("areas is meta-only and api-only, not a phase or task key",
          "areas" in M._META_KEYS and "areas" in M._META_API_ONLY
          and "areas" not in M._PHASE_KEYS and "areas" not in M._TASK_KEYS)

    # The enforce exemption's justification, pinned: the planGate control is on
    # the form, custom-rendered (planGateField owns the legacy-flag rewrite).
    _pg = [f for g in M.SETTINGS_GROUPS for f in g["fields"]
           if f["path"] == "planGate"]
    check("enforce is exempt BECAUSE planGate's control edits it - that control "
          "must exist, custom, or the exemption excuses a hole",
          len(_pg) == 1 and _pg[0]["kind"] == "custom")

    # --- _cfg_enums --------------------------------------------------------------
    check("the enum choices ARE the validator's tuples, not a copy of them",
          set(M._cfg_enums()["inProgressPolicy"]) == set(_vc.IN_PROGRESS_POLICY)
          and set(M._cfg_enums()["authorMode"]) == set(_vc.AUTHOR_MODES))
    check("the planGate tiers reach the form from the validator's own tuple, "
          "in escalation order",
          M._cfg_enums()["planGate"] == list(_vc.PLAN_GATE_MODES))
    _hcfg = _loader.load_hooks_config(modname="audit__panel_settings_hooks_cfg")
    check("the runsGate readings reach the form from the validator's own "
          "tuple, and that tuple is still the hooks' own vocabulary - a "
          "mirror pinned in both directions rather than a second typed-out "
          "copy free to drift on its own schedule",
          M._cfg_enums()["runsGate"] == list(_vc.RUNS_GATE_MODES)
          and tuple(_vc.RUNS_GATE_MODES) == tuple(_hcfg.RUNS_GATE_MODES))
    check("ps1 the review.perTask words reach the form from the validator's "
          "own tuple, which is the hooks' own vocabulary",
          M._cfg_enums()["perTask"] == list(_vc.REVIEW_PER_TASK_MODES)
          and tuple(_vc.REVIEW_PER_TASK_MODES)
          == tuple(_hcfg.REVIEW_PER_TASK_MODES))
    # The round cap's control: a whole-number box whose floor is the
    # validator's own - a form that let 0 through would write a config the
    # validator then refuses by name.
    _mr = [f for g in M.SETTINGS_GROUPS for f in g["fields"]
           if f["path"] == "review.maxRounds"]
    check("ps2 review.maxRounds is one whole-number control with a floor of 1, "
          "in the review group, and the floor is one the validator accepts while "
          "the step below it is refused: %r" % (_mr,),
          len(_mr) == 1 and _mr[0]["kind"] == "int" and _mr[0].get("min") == 1
          and _mr[0] in [f for g in M.SETTINGS_GROUPS if g["id"] == "review"
                         for f in g["fields"]]
          and not _vc.validate_config({"review": {"maxRounds": 1}})[0]
          and _vc.validate_config({"review": {"maxRounds": 0}})[0])
    _mrh = M.FIELD_HELP.get("review.maxRounds") or ""
    check("ps3 its help text says what the cap does - asks once with the open "
          "findings - names all three answers, and that 0 is refused: %r"
          % (_mrh,),
          "asks once" in _mrh and "carry" in _mrh
          and "one more round" in _mrh and "accepting them open" in _mrh
          and "0 is refused" in _mrh)
    _ci = [f for g in M.SETTINGS_GROUPS if g["id"] == "ci" for f in g["fields"]]
    check("ps4 the ci group edits the cadence's two numbers leaf by leaf and the "
          "workflow, with the floors the validator accepts and refuses: %r"
          % (_ci,),
          [f["path"] for f in _ci] == ["ci.cadence.closes", "ci.cadence.hours",
                                        "ci.workflow"]
          and not _vc.validate_config({"ci": {"cadence": {"closes": 1}}})[0]
          and _vc.validate_config({"ci": {"cadence": {"closes": 0}}})[0]
          and "0 is refused" in M.FIELD_HELP["ci.cadence.closes"])
    check("_cfg_enums() is JSON-serializable (panel-server bakes it into UI_HTML "
          "with json.dumps)", json.dumps(M._cfg_enums(), sort_keys=True))

    # --- usage.pricingAsOf's help must say what rate_basis_phrase ACTUALLY does ---
    # `rate_basis_phrase` is the one resolver every cost surface prints its phrase
    # through - the README is worded off its real branches, and this field's help
    # has to agree with the same branches rather than retyping an independent
    # story. Driven through the real function, not a copy of its strings, so a
    # future change to the resolver's wording fails THIS case rather than leaving
    # the help text to quietly stop matching it.
    _help = M.FIELD_HELP["usage.pricingAsOf"]
    _config_undated = _ue.rate_basis_phrase(
        {"basis": "config", "asOf": "", "source": ""})
    _shipped_dated = _ue.rate_basis_phrase(
        {"basis": "shipped", "asOf": "2026-01-01", "source": "a pricing page"})
    check("the resolver says 'rates undated' of this project's OWN undated "
          "usage.pricing table (basis=config) - the field this help text is for",
          "rates undated" in _config_undated
          and "usage.pricingAsOf" in _config_undated)
    check("...and never of the shipped table, which already carries its own date",
          "undated" not in _shipped_dated)
    check("usage.pricingAsOf's help text matches those two branches: it dates "
          "the config's own usage.pricing table, is printed only when THAT "
          "table priced the rows, and 'rates undated' is never claimed of the "
          "shipped table",
          "project's usage.pricing table" in _help
          and "priced the rows" in _help
          and "never" in _help and "shipped table" in _help
          # The old sentence's false claim: that an unset field leaves BOTH
          # surfaces saying "undated" regardless of which table priced the
          # rows - true only when the project table is the one in force.
          and "both say the rates are undated" not in _help)


def _ladder_cases(check):
    # The expected phrase is rebuilt here from the hooks' own table, step by
    # step, not read back from the helper under test; the words per step are the
    # ones the plugin README's planGate row uses.
    import os
    _ladder = _loader.load_hooks_config().PLAN_GATE_LADDER
    _words = {"no-manifest": "no manifest", "no-phase": "no phase",
              "nothing-running": "phases, none running",
              "phase-running": "a phase running"}
    _expect = " -> ".join(
        "%s%s (%s)" % (tier, " past the free file" if step == "nothing-running"
                       else "", _words[step]) for step, tier in _ladder)
    _help = M.FIELD_HELP["planGate"]
    _schema = json.load(open(os.path.join(
        M._output.PLUGIN_ROOT, "schema", "audit-config.schema.json"),
        encoding="utf-8"))["properties"]["planGate"]["description"]
    check("the panel's planGate help and the config schema's description state "
          "the ladder derived from PLAN_GATE_LADDER, so a plan with phases and "
          "none running reads as deny past the free file on every surface "
          "(each surface carries the ladder rebuilt step by step from the table)",
          _expect in _help and _expect in _schema
          and M.plan_gate_ladder_phrase() == _expect,
          "expect=%r help-has=%r schema-has=%r"
          % (_expect, _expect in _help, _expect in _schema))
    check("...and neither surface keeps the old second rung, 'warn' for a "
          "manifest with nothing running, which the ladder no longer has",
          "manifest, nothing running" not in _help + _schema
          and "manifest but nothing running" not in _help + _schema,
          "help=%r" % _help[:200])
    check("...the helper has words for every step the ladder holds, so a step "
          "added there cannot be rendered under its bare identifier",
          all(step in _words for step, _t in _ladder)
          and all(w in M.plan_gate_ladder_phrase() for w in _words.values()))


# Every spelling the retired rung (a plan with phases and none running only
# warns) has been written in. Matched on text with whitespace collapsed and
# backticks dropped, so a line wrap or a code span does not hide one.
_RETIRED_RUNG_SPELLINGS = (
    r"(manifest|plan) but (no phase|nothing|none)",
    r"no phase (is )?(in_progress|running)",
    r"(nothing|none) (is )?running",
)

# Documents allowed to keep the old wording, each with the reason the case
# checks: a row without a reason, or naming a path the walk no longer reaches,
# fails the case instead of silently widening the allowance.
_RETIRED_RUNG_ALLOWED = (
    ("CHANGELOG.md",
     "released history: an entry describes the ladder of the release it shipped in"),
    ("docs/essays/",
     "a dated essay: it describes the ladder as it stood when it was written"),
)


def _retired_rung_hits(text):
    """Spans of `text` stating the retired rung: one of the spellings with the
    `warn` tier beside it, with no `deny` and no sentence end between them. The
    current ladder holds the same words (`phases, none running`) under `deny`,
    which is why the tier beside the words is what decides."""
    import re
    flat = re.sub(r"\s+", " ", text.replace("`", ""))
    low = flat.lower()
    hits = []
    for pat in _RETIRED_RUNG_SPELLINGS:
        for m in re.finditer(pat, low):
            before = low[max(0, m.start() - 60):m.start()]
            after = low[m.end():m.end() + 60]
            # A comma ends the clause before the words (a tier named in the
            # previous clause is not the tier of these); after them the tier
            # may follow in the same clause, so only a sentence end stops it.
            for stop in ("deny", ". ", "; ", ", "):
                if stop in before:
                    before = before[before.rindex(stop) + len(stop):]
            for stop in ("deny", ". ", "; "):
                if stop in after:
                    after = after[:after.index(stop)]
            if "warn" in before or "warn" in after:
                hits.append(flat[max(0, m.start() - 40):m.end() + 40])
    return hits


def _retired_rung_cases(check):
    import os
    # Second direction: the detector must see every old spelling beside warn,
    # and stay quiet over the current ladder, which holds the same words
    # under deny. Without these an always-quiet or always-firing detector
    # would pass the scan below.
    _old = (
        "with a manifest but no phase `in_progress` it warns, and it denies",
        "warn with a manifest but no phase in_progress, deny once a phase runs",
        "manifest but no phase\n`in_progress` -> `warn` (PostToolUse)",
        "a plan with nothing running only warns",
        "warns while none running, denies later",
    )
    _new = (
        "observe (no manifest) -> warn (no phase) -> deny past the free file "
        "(phases, none running) -> deny (a phase running)",
        "with a manifest holding no phase it warns, with phases and none "
        "running it denies past the session's free file",
        "a project with a plan but no phase running now gets refusals past its "
        "free file; pin planGate to warn to keep the old behaviour",
    )
    check("the retired-rung detector sees each old spelling beside the warn tier",
          all(_retired_rung_hits(t) for t in _old),
          "quiet on: %r" % [t for t in _old if not _retired_rung_hits(t)])
    check("...and stays quiet over the current ladder, whose words are the same "
          "under deny",
          not any(_retired_rung_hits(t) for t in _new),
          "fired on: %r" % [t for t in _new if _retired_rung_hits(t)])

    _scan = M._output.prose_scan_set((".md",), table=_RETIRED_RUNG_ALLOWED)
    _root = M._output.REPO_ROOT
    check("...the allowances each carry a reason and name a document the walk "
          "still reaches, and the walk read the tree",
          _scan["problem"] is None and _scan["paths"]
          and all(why.strip() for _p, why in _RETIRED_RUNG_ALLOWED)
          and all(any(c == p or (p.endswith("/") and c.startswith(p))
                      for c in _scan["exempted"])
                  for p, _w in _RETIRED_RUNG_ALLOWED),
          "problem=%r paths=%d exempted=%r"
          % (_scan["problem"], len(_scan["paths"]), _scan["exempted"]))
    _texts = [(rel, open(os.path.join(_root, rel), encoding="utf-8").read())
              for rel in _scan["paths"]]
    _texts.append(("plugins/audit/schema/audit-config.schema.json",
                   open(os.path.join(M._output.PLUGIN_ROOT, "schema",
                                     "audit-config.schema.json"),
                        encoding="utf-8").read()))
    _found = [(rel, h) for rel, t in _texts for h in _retired_rung_hits(t)]
    check("no shipped document or schema text states the retired ladder rung in "
          "any spelling (no phase in_progress, nothing running, but no phase "
          "running) as the tier for a plan with phases",
          not _found, "found: %r" % _found)


def _selftest():
    return _harness.run(lambda check: (_cases(check), _ladder_cases(check),
                                       _retired_rung_cases(check)))


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_settings.py --selftest\n")
    raise SystemExit(2)
