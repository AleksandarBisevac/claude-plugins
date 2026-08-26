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
import _panel_settings as M                        # noqa: E402


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
                   "priority": _vc.KNOWN_PRIORITY}
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
    # `ui` (th, F-P-6) is exempt for the policy reason, not the enforce one: it
    # HAS a surface, and that surface is the Appearance tab — a token editor
    # with a live preview, light/dark pairs and a contrast check. A text field
    # here holding a theme name beside it would be a second control writing the
    # same key, free to disagree with the tab about which theme is on.
    _settings_exempt = {"policy", "enforce", "ui"}
    _expected = {k for k in _vc.KNOWN_ROOT
                 if k not in _containers and k not in _settings_exempt}
    for _parent, _keys in _containers.items():
        _expected |= {"%s.%s" % (_parent, k) for k in _keys}
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
          == ("paths", "guards", "tdd", "usage", "journal", "priority")
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
    check("_cfg_enums() is JSON-serializable (panel-server bakes it into UI_HTML "
          "with json.dumps)", json.dumps(M._cfg_enums(), sort_keys=True))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_settings.py --selftest\n")
    raise SystemExit(2)
