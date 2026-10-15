#!/usr/bin/env python3
"""
The cases for `_usage_core.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

ONE CASE GROUP FORCED A REAL CHANGE, AND IT IS THE `ag` ALLOCATION COUNTER. Those
cases swap `_blank` for a counting stub, run `aggregate`, and assert the number of
allocations. Inline that was `globals()["_blank"] = _ag_counting_blank`, which
worked because the suite lived in the module whose global it was rebinding. From a
test file `globals()` is THIS module's namespace, so the literal line would patch a
name nothing calls: `aggregate` would keep calling the real `_blank`, every counter
would read 0, and ag4/ag5/ag7/ag8 would go red pointing at a defect that is not
there. It is `M._blank = ...` here - the same rebinding, named on the module that
owns it - and restored on `M` in the same `finally`. The eager ORACLE calls
`M._blank()` for the same reason: it has to see the stub, or ag8 (the case that
proves the counter fires at all) would be measuring nothing.

`_raises` came with the cases. It was a module-level helper in `_usage_core.py`, and
`agg: unknown group key raises` was its only caller anywhere in the tree.

`_load_hooks_pricing` reads `hooks/_config.py` by path. That is a read of a
CONFIGURATION module's data, and the path is spelled off `_harness.HOOKS_DIR`
rather than off this file - inline it was two `os.path.dirname` steps up from
`scripts/`, which from `tests/` would land on the plugin directory by coincidence.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _usage_core as M                           # noqa: E402


# --- helpers that moved with the cases ----------------------------------------
def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- pricing -----------------------------------------------------------
    check("price: exact model match",
          M.rates_for("claude-sonnet-5") is M.DEFAULT_PRICING["claude-sonnet-5"])
    check("price: longest-prefix match resolves a dated id",
          M.rates_for("claude-haiku-4-5-20251001")["out"] == 5.0)
    check("price: Fable/Mythos priced above Opus tier, not silently defaulted",
          M.rates_for("claude-fable-5")["out"] == 50.0
          and M.rates_for("claude-mythos-5")["out"] == 50.0)
    check("price: a Sonnet 4.x id does not fall through to the Opus default",
          M.rates_for("claude-sonnet-4-5")["out"] == 15.0)
    check("price: an unknown model is UNPRICED - None, never a fallback figure",
          M.rates_for("some-future-model") is None
          and M.price({"in": 1_000_000}, "some-future-model") is None)
    check("price: a non-string model is the same unknown-model case",
          M.rates_for(None) is None)
    one_m = {"in": 1_000_000, "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0}
    check("price: 1M input on opus-5 == $5.00",
          abs(M.price(one_m, "claude-opus-5") - 5.0) < 1e-9)
    both = {"in": 0, "out": 0, "cacheW5m": 1_000_000, "cacheW1h": 1_000_000,
            "cacheR": 0}
    check("price: both cache-write tiers priced apart (6.25 + 10.00)",
          abs(M.price(both, "claude-opus-5") - 16.25) < 1e-9)
    check("price: cache read on opus-5 is 0.1x base input",
          abs(M.price({"in": 0, "out": 0, "cacheW5m": 0, "cacheW1h": 0,
                       "cacheR": 1_000_000}, "claude-opus-5") - 0.5) < 1e-9)

    # --- pp: the rates that used to be kept true by two comments -----------
    # DEFAULT_PRICING and hooks/_config.py DEFAULTS["usage"]["pricing"] are the
    # same table, and each file's comment said it mirrored the other. Nothing
    # read either comment. They cannot be merged (hooks/ may
    # import nothing from scripts/, and the hook must price a model standalone),
    # so the agreement is pinned here instead - a TEST is the one place that is
    # allowed to look at both.
    def _deep_pricing_copy(table):
        return dict((model, dict(row)) for model, row in table.items())

    def _load_hooks_module():
        """`(module, error)` for hooks/_config.py, loaded BY PATH.

        NOT through `_loader.load_hooks_config()`: four lines of `importlib` do
        the same job with no shared cache this one call has any use for, and the
        point of the case is WHAT the file says, not how it was reached.

        The failure is RETURNED, never swallowed: a hooks config that would not
        load must land as a failing case of its own, not as an empty divergence
        list that reads exactly like agreement."""
        import importlib.util
        path = os.path.join(_harness.HOOKS_DIR, "_config.py")
        try:
            spec = importlib.util.spec_from_file_location(
                "audit_hooks_config_ledger_selftest", path)
            if spec is None or spec.loader is None:
                return None, "no import spec for %s" % path
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod, None
        except Exception as exc:     # any failure is reported, not absorbed
            return None, "%s: %s" % (type(exc).__name__, exc)

    def _load_hooks_pricing():
        """`(table, error)` for hooks/_config.py's own pricing map."""
        mod, err = _load_hooks_module()
        if err is not None:
            return None, err
        try:
            return mod.DEFAULTS["usage"]["pricing"], None
        except Exception as exc:     # a missing key is reported, not absorbed
            return None, "%s: %s" % (type(exc).__name__, exc)

    def _load_hooks_provenance():
        """`(provenance, error)` for hooks/_config.py's shipped date and source,
        in the shape `pricing_provenance_divergences()` reads."""
        mod, err = _load_hooks_module()
        if err is not None:
            return None, err
        try:
            return {"pricingAsOf": mod.DEFAULTS["usage"]["pricingAsOf"],
                    "source": mod.PRICING_SOURCE_URL}, None
        except Exception as exc:     # a missing name is reported, not absorbed
            return None, "%s: %s" % (type(exc).__name__, exc)

    # The second-direction case: a divergence checker that ALWAYS reports
    # something would fail every `pp` case below except this one, and this one
    # is the only case that goes red when it does.
    check("pp1 two identical tables diverge in nothing",
          M.pricing_divergences(M.DEFAULT_PRICING,
                                _deep_pricing_copy(M.DEFAULT_PRICING)) == [])
    # The expected line is built from the shipped rate rather than spelled as
    # a literal, so a correction to the table does not turn this case red
    # while the checker is still right. The drifted value is chosen off the
    # shipped one, so the two can never coincide and hide the drift.
    _pp_drift = _deep_pricing_copy(M.DEFAULT_PRICING)
    _pp_shipped = M.DEFAULT_PRICING["claude-sonnet-5"]["cacheW1h"]
    _pp_drift["claude-sonnet-5"]["cacheW1h"] = _pp_shipped + 0.5
    _pp_named = M.pricing_divergences(M.DEFAULT_PRICING, _pp_drift,
                                      "ledger", "hooks")
    check("pp2 one drifted rate is named down to model.rate WITH both values, "
          "and is the ONLY thing reported - a checker that just says 'the "
          "tables differ' sends someone diffing every rate by hand",
          _pp_named == ["claude-sonnet-5.cacheW1h: ledger %r vs hooks %r"
                        % (_pp_shipped, _pp_shipped + 0.5)],
          repr(_pp_named))
    _pp_gone = _deep_pricing_copy(M.DEFAULT_PRICING)
    del _pp_gone["claude-haiku-4-5"]
    check("pp3 a model present on one side only is named by model",
          M.pricing_divergences(M.DEFAULT_PRICING, _pp_gone, "ledger", "hooks")
          == ["claude-haiku-4-5: absent from hooks"])
    _pp_extra = _deep_pricing_copy(M.DEFAULT_PRICING)
    _pp_extra["claude-future-9"] = dict(M.DEFAULT_PRICING["claude-opus-5"])
    check("pp4 ...and so is a model only the OTHER side has, so the check reads "
          "both directions",
          M.pricing_divergences(M.DEFAULT_PRICING, _pp_extra, "ledger", "hooks")
          == ["claude-future-9: absent from ledger"])
    _pp_partial = _deep_pricing_copy(M.DEFAULT_PRICING)
    del _pp_partial["claude-opus-5"]["cacheR"]
    check("pp5 a missing RATE inside a row is named too, not just a missing row",
          M.pricing_divergences(M.DEFAULT_PRICING, _pp_partial, "ledger", "hooks")
          == ["claude-opus-5.cacheR: absent from hooks (ledger has 0.5)"])
    check("pp6 a table that is not a dict - the shape a failed load has - is "
          "REPORTED, never treated as empty-and-therefore-equal",
          M.pricing_divergences(M.DEFAULT_PRICING, None, "ledger", "hooks")
          == ["hooks is not a pricing table (NoneType)"]
          and M.pricing_divergences(None, M.DEFAULT_PRICING, "ledger", "hooks")
          == ["ledger is not a pricing table (NoneType)"])

    _hooks_pricing, _hooks_err = _load_hooks_pricing()
    check("pp7 hooks/_config.py loaded and carries DEFAULTS['usage']['pricing'] "
          "at all - its own case, so a load failure can never be mistaken for "
          "the tables agreeing",
          _hooks_err is None and isinstance(_hooks_pricing, dict)
          and len(_hooks_pricing) == len(M.DEFAULT_PRICING),
          _hooks_err or ("got %r" % (type(_hooks_pricing).__name__,)))
    _hooks_diff = M.pricing_divergences(M.DEFAULT_PRICING, _hooks_pricing,
                                        "usage_ledger.DEFAULT_PRICING",
                                        "hooks/_config.py")
    check("pp8 usage_ledger.DEFAULT_PRICING and hooks/_config.py "
          "DEFAULTS['usage']['pricing'] are identical, model for model and rate "
          "for rate - the duplication is deliberate, the agreement is now read",
          _hooks_diff == [], " | ".join(_hooks_diff))

    # --- pr: the shipped rates are the published ones ----------------------
    # Each expected row is transcribed from the pricing page named by
    # M.PRICING_SOURCE_URL on M.PRICING_AS_OF, written out in full rather than
    # derived from the table under test - a case that read its expectation off
    # DEFAULT_PRICING would agree with any typo in it.
    _pr_opus_5_5 = {"in": 4.0, "out": 20.0, "cacheW5m": 5.0, "cacheW1h": 8.0,
                    "cacheR": 0.2}
    _pr_fable_5_1 = {"in": 10.0, "out": 50.0, "cacheW5m": 12.5, "cacheW1h": 20.0,
                     "cacheR": 0.25}
    _pr_sonnet_5 = {"in": 2.0, "out": 10.0, "cacheW5m": 2.5, "cacheW1h": 4.0,
                    "cacheR": 0.2}
    _pr_opus_5 = {"in": 5.0, "out": 25.0, "cacheW5m": 6.25, "cacheW1h": 10.0,
                  "cacheR": 0.5}
    _pr_fable_5 = {"in": 10.0, "out": 50.0, "cacheW5m": 12.5, "cacheW1h": 20.0,
                   "cacheR": 1.0}
    check("pr1 claude-opus-5-5 and a dated claude-opus-5-5 id resolve to their "
          "own row, not claude-opus-5's - the longest prefix used to be "
          "claude-opus-5",
          M.rates_for("claude-opus-5-5") == _pr_opus_5_5
          and M.rates_for("claude-opus-5-5-20261001") == _pr_opus_5_5,
          "got %r / %r" % (M.rates_for("claude-opus-5-5"),
                           M.rates_for("claude-opus-5-5-20261001")))
    # The allow twin of pr1: a row that grew to swallow its neighbour (opus-5
    # rewritten with opus-5-5's rates) would satisfy pr1 and fail here.
    check("pr2 ...while claude-opus-5 and its dated ids keep Opus 5's own rates",
          M.rates_for("claude-opus-5") == _pr_opus_5
          and M.rates_for("claude-opus-5-20260301") == _pr_opus_5,
          "got %r" % (M.rates_for("claude-opus-5"),))
    check("pr3 claude-fable-5-1 and claude-mythos-5-1 carry their own cache-read "
          "rate, not the Fable 5 / Mythos 5 row's",
          M.rates_for("claude-fable-5-1") == _pr_fable_5_1
          and M.rates_for("claude-mythos-5-1") == _pr_fable_5_1
          and M.rates_for("claude-fable-5-1-20261001")["cacheR"] == 0.25,
          "got %r / %r" % (M.rates_for("claude-fable-5-1"),
                           M.rates_for("claude-mythos-5-1")))
    check("pr4 ...while claude-fable-5 and claude-mythos-5 keep their own read",
          M.rates_for("claude-fable-5") == _pr_fable_5
          and M.rates_for("claude-mythos-5") == _pr_fable_5,
          "got %r" % (M.rates_for("claude-fable-5"),))
    check("pr5 claude-sonnet-5 carries the rates the official page lists on the "
          "as-of date, cache tiers included",
          M.rates_for("claude-sonnet-5") == _pr_sonnet_5,
          "got %r" % (M.rates_for("claude-sonnet-5"),))

    # --- pv: the date and source travel with the table ---------------------
    _pv_ship = {"pricingAsOf": M.PRICING_AS_OF, "source": M.PRICING_SOURCE_URL}
    # The second-direction case, the same job pp1 does for the rates.
    check("pv1 two identical provenances diverge in nothing",
          M.pricing_provenance_divergences(_pv_ship, dict(_pv_ship)) == [])
    _pv_date = dict(_pv_ship, pricingAsOf="2000-01-01")
    check("pv2 a drifted date is named WITH both values, the way pp names a "
          "drifted rate",
          M.pricing_provenance_divergences(_pv_ship, _pv_date, "ledger", "hooks")
          == ["pricingAsOf: ledger %r vs hooks '2000-01-01'" % (M.PRICING_AS_OF,)],
          repr(M.pricing_provenance_divergences(_pv_ship, _pv_date,
                                                "ledger", "hooks")))
    _pv_url = dict(_pv_ship, source="https://example.invalid/pricing")
    check("pv3 ...and so is a drifted source URL",
          M.pricing_provenance_divergences(_pv_ship, _pv_url, "ledger", "hooks")
          == ["source: ledger %r vs hooks 'https://example.invalid/pricing'"
              % (M.PRICING_SOURCE_URL,)])
    check("pv4 a blank or missing field is REPORTED even when both sides share "
          "it - two empty dates agreeing is not a dated table",
          M.pricing_provenance_divergences({"pricingAsOf": "", "source": "u"},
                                           {"pricingAsOf": "", "source": "u"},
                                           "ledger", "hooks")
          == ["pricingAsOf: blank in ledger", "pricingAsOf: blank in hooks"]
          and M.pricing_provenance_divergences({"source": "u"},
                                               {"pricingAsOf": "d", "source": "u"},
                                               "ledger", "hooks")
          == ["pricingAsOf: blank in ledger"])
    check("pv5 a provenance that is not a dict is REPORTED, never read as "
          "agreement",
          M.pricing_provenance_divergences(_pv_ship, None, "ledger", "hooks")
          == ["hooks is not a pricing provenance (NoneType)"])
    _pv_hooks, _pv_err = _load_hooks_provenance()
    _pv_diff = (M.pricing_provenance_divergences(
        _pv_ship, _pv_hooks, "_usage_core", "hooks/_config.py")
        if _pv_err is None else [_pv_err])
    check("pv6 _usage_core and hooks/_config.py ship the same as-of date and "
          "source URL, and neither is blank",
          _pv_diff == [], " | ".join(_pv_diff))

    # Sonnet 5.5 and Haiku 5.5 carry their OWN rows now (fixtures/
    # pricing-page-2026-10-10.md is the checked-in excerpt both are transcribed
    # from) - Sonnet 5.5's cache-read rate is HALF of Sonnet 5's (0.10 vs 0.2),
    # so a case that let it fall through the longest-prefix match to Sonnet 5's
    # row would silently overcharge every Sonnet 5.5 cache read.
    _pr_sonnet_5_5 = {"in": 2.0, "out": 10.0, "cacheW5m": 2.5, "cacheW1h": 4.0,
                      "cacheR": 0.10}
    check("pr6 claude-sonnet-5-5 carries its OWN row (cacheR 0.10), not Sonnet "
          "5's (0.2) through the longest-prefix fallback",
          M.rates_for("claude-sonnet-5-5") == _pr_sonnet_5_5
          and M.rates_for("claude-sonnet-5-5-20261001") == _pr_sonnet_5_5
          and M.rates_for("claude-sonnet-5-5")["cacheR"]
          != M.rates_for("claude-sonnet-5")["cacheR"],
          "got %r" % (M.rates_for("claude-sonnet-5-5"),))
    # The checked-in excerpt pin: both new rows read exactly what the page
    # fixture quotes, so a later edit to either row that drifts from the page
    # is caught here rather than by eyeballing the table.
    _excerpt = os.path.join(_output.TESTS_DIR, "fixtures",
                            "pricing-page-2026-10-10.md")
    with open(_excerpt, encoding="utf-8") as _fh:
        _excerpt_text = _fh.read()
    check("pr7 claude-sonnet-5-5's cacheR and claude-haiku-5-5's in both equal "
          "the checked-in page excerpt (fixtures/pricing-page-2026-10-10.md), "
          "not a hand-retyped number",
          M.rates_for("claude-sonnet-5-5")["cacheR"] == 0.10
          and M.rates_for("claude-haiku-5-5")["in"] == 0.10
          and "$0.10 | $2.50 | $4 | $0.10 | $10" not in _excerpt_text  # sanity: no stray row
          and "$2 | $2.50 | $4 | $0.10 | $10" in _excerpt_text
          and "$0.10 | $0.125 | $0.20 | $0.01 | $0.50" in _excerpt_text)
    check("pr8 claude-haiku-5-5 carries its own row rather than falling to an "
          "unpriced/`_default` answer",
          M.rates_for("claude-haiku-5-5")
          == {"in": 0.10, "out": 0.50, "cacheW5m": 0.125, "cacheW1h": 0.20,
              "cacheR": 0.01})

    # --- dr: a model's entry may be a list of DATED rate rows ---------------
    _dr_old = {"in": 1.0, "out": 5.0, "cacheW5m": 1.25, "cacheW1h": 2.0,
               "cacheR": 0.1}
    _dr_new = {"in": 2.0, "out": 10.0, "cacheW5m": 2.5, "cacheW1h": 4.0,
               "cacheR": 0.2}
    _dr_table = {"claude-dated-9": [
        {"effectiveFrom": "2026-01-01", "rates": _dr_old},
        {"effectiveFrom": "2026-06-01", "rates": _dr_new},
    ], "claude-flat-9": dict(_dr_old)}
    check("dr1 a date BEFORE the later row's effectiveFrom prices at the "
          "earlier row",
          M.rates_for("claude-dated-9", _dr_table, "2026-03-01") == _dr_old)
    check("dr2 a date ON/AFTER the later row's effectiveFrom prices at it",
          M.rates_for("claude-dated-9", _dr_table, "2026-06-01") == _dr_new
          and M.rates_for("claude-dated-9", _dr_table, "2026-12-31") == _dr_new)
    check("dr3 a date BEFORE every row still prices at the earliest one, "
          "rather than pricing nothing",
          M.rates_for("claude-dated-9", _dr_table, "2020-01-01") == _dr_old)
    check("dr4 a flat legacy row (not a list) prices EVERY date the same",
          M.rates_for("claude-flat-9", _dr_table, "2020-01-01") == _dr_old
          and M.rates_for("claude-flat-9", _dr_table, "2099-01-01") == _dr_old)
    check("dr5 `price()` honours `at` the same way `rates_for()` does",
          abs(M.price({"in": 1_000_000}, "claude-dated-9", _dr_table,
                      "2026-03-01") - 1.0) < 1e-9
          and abs(M.price({"in": 1_000_000}, "claude-dated-9", _dr_table,
                          "2026-06-01") - 2.0) < 1e-9)

    # --- ds: `rate_for_stamp` is `rates_for` plus which dated row answered --
    check("ds1 a dated entry names the row's own effectiveFrom, not just "
          "its rates",
          M.rate_for_stamp("claude-dated-9", _dr_table, "2026-03-01")
          == (_dr_old, "2026-01-01")
          and M.rate_for_stamp("claude-dated-9", _dr_table, "2026-12-31")
          == (_dr_new, "2026-06-01"))
    check("ds2 a flat/legacy row carries no effectiveFrom - it is in effect "
          "always, so no single date names it",
          M.rate_for_stamp("claude-flat-9", _dr_table, "2020-01-01")
          == (_dr_old, None))
    check("ds3 an unknown model stamps (None, None), the same as rates_for",
          M.rate_for_stamp("some-future-model", _dr_table) == (None, None))

    # --- lp: Haiku 5.5's published long-prompt tier ------------------------
    check("lp1 a short prompt keeps the base model name",
          M.tiered_model_key("claude-haiku-5-5", 50_000) == "claude-haiku-5-5")
    check("lp2 a prompt crossing the threshold is tiered under a DISTINCT "
          "key, so an hour bucket never averages the two rates together",
          M.tiered_model_key("claude-haiku-5-5", 150_000)
          == "claude-haiku-5-5" + M.LONG_PROMPT_SUFFIX)
    check("lp3 the threshold itself is still the base tier (over, not at "
          "or over)",
          M.tiered_model_key("claude-haiku-5-5", M.LONG_PROMPT_THRESHOLD_TOKENS)
          == "claude-haiku-5-5")
    check("lp4 a model nothing tiers is never suffixed, however large its "
          "prompt",
          M.tiered_model_key("claude-opus-5", 500_000) == "claude-opus-5")
    _lp_resolved = M.resolve_pricing(None, None)["table"]
    _lp_tiered_key = "claude-haiku-5-5" + M.LONG_PROMPT_SUFFIX
    check("lp5 `resolve_pricing` lays the published long-prompt row into the "
          "table it hands back, so `rates_for` resolves the tiered key "
          "through its ordinary exact-match lookup",
          M.rates_for(_lp_tiered_key, _lp_resolved)
          == M.LONG_PROMPT_RATES["claude-haiku-5-5"])
    check("lp6 ...while DEFAULT_PRICING itself stays untouched - the tiered "
          "row is laid in by the resolver, never merged into the table "
          "pinned byte-for-byte against hooks/_config.py (pp8)",
          _lp_tiered_key not in M.DEFAULT_PRICING)

    # --- dp: DEFAULT_PRICING is DERIVED from hooks/_config.py, never a second
    # literal - pp7/pp8 above hold the two tables' CONTENTS equal, which a pair
    # of literals kept in sync by hand would also pass. This proves the
    # MECHANISM: `M._hooks_config` is the loaded module DEFAULT_PRICING is read
    # off, and running `_usage_core`'s own loader and reader over a
    # hooks/_config.py edited on its own (a scratch copy - the real file is
    # never touched) moves the figure.
    import shutil as _dp_shutil
    import tempfile as _dp_tempfile

    check("dp1 _usage_core keeps the loaded hooks module it derived from",
          hasattr(M, "_hooks_config")
          and getattr(M._hooks_config, "__file__", "").replace("\\", "/")
          .endswith("hooks/_config.py"))
    check("dp2 DEFAULT_PRICING is read OFF that loaded module, not a second "
          "literal kept in sync by hand",
          M.DEFAULT_PRICING == M._hooks_config.DEFAULTS["usage"]["pricing"])

    _dp_tmp = _dp_tempfile.mkdtemp(prefix="usage-core-dp-")
    try:
        _dp_copy = os.path.join(_dp_tmp, "_config.py")
        _dp_shutil.copyfile(os.path.join(_harness.HOOKS_DIR, "_config.py"),
                            _dp_copy)
        with open(_dp_copy, encoding="utf-8") as _fh:
            _dp_src = _fh.read()
        _dp_target = ('"claude-opus-5":     {"in":  5.0, "out": 25.0, '
                      '"cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5}')
        check("dp3 fixture assumption: the shipped row this case edits still "
              "reads what the case expects - a false pass here would hide a "
              "dp4 that proves nothing",
              _dp_src.count(_dp_target) == 1, _dp_src.count(_dp_target))
        _dp_edited = _dp_src.replace(
            _dp_target,
            _dp_target.replace('"in":  5.0', '"in": 4321.5'), 1)
        with open(_dp_copy, "w", encoding="utf-8") as _fh:
            _fh.write(_dp_edited)
        _dp_mod = M._load_hooks_config_module(_dp_copy)
        _dp_table, _dp_asof, _dp_url = M._shipped_pricing_from(_dp_mod)
        check("dp4 running _usage_core's OWN loader and reader over a "
              "hooks/_config.py edited on its own moves the figure "
              "DEFAULT_PRICING is built from (4321.5 for the edited row), "
              "while the live DEFAULT_PRICING keeps the shipped one - a "
              "hand-copied literal in _usage_core would not move",
              _dp_table["claude-opus-5"]["in"] == 4321.5
              and M.DEFAULT_PRICING["claude-opus-5"]["in"] != 4321.5)
        check("dp5 ...and over the UNEDITED file the same two calls reproduce "
              "DEFAULT_PRICING, PRICING_AS_OF and the source url exactly, so "
              "dp4's difference is the edit and nothing else",
              M._shipped_pricing_from(M._load_hooks_config_module())
              == (M.DEFAULT_PRICING, M.PRICING_AS_OF, M.PRICING_SOURCE_URL))
        check("dp6 the table handed back is a copy: it is not the loaded "
              "module's own dict",
              _dp_table is not _dp_mod.DEFAULTS["usage"]["pricing"])
    finally:
        _dp_shutil.rmtree(_dp_tmp, ignore_errors=True)

    # --- tp: the example config is a third copy of the shipped rates --------
    # It lists only some models, so only the rows it lists are compared; its
    # date and the source its usage note names are compared the way pv
    # compares the hooks copy, blank fields included.
    def _template_drift(tpl):
        usage = (tpl or {}).get("usage") if isinstance(tpl, dict) else None
        if not isinstance(usage, dict):
            return ["template carries no usage block"]
        rows = usage.get("pricing")
        if not isinstance(rows, dict) or not rows:
            return ["template lists no pricing rows"]
        shipped = dict((model, M.DEFAULT_PRICING[model]) for model in rows
                       if model in M.DEFAULT_PRICING)
        note = tpl.get("//usage") if isinstance(tpl.get("//usage"), str) else ""
        named = M.PRICING_SOURCE_URL if M.PRICING_SOURCE_URL in note else ""
        return (M.pricing_divergences(shipped, rows, "DEFAULT_PRICING", "template")
                + M.pricing_provenance_divergences(
                    {"pricingAsOf": M.PRICING_AS_OF, "source": M.PRICING_SOURCE_URL},
                    {"pricingAsOf": usage.get("pricingAsOf"), "source": named},
                    "_usage_core", "template"))

    def _load_template():
        import json
        path = os.path.join(_output.PLUGIN_ROOT, "templates",
                            "audit.config.example.json")
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh), None
        except (OSError, ValueError) as exc:     # reported, never read as agreement
            return None, "%s: %s" % (type(exc).__name__, exc)

    _tp, _tp_err = _load_template()
    _tp_diff = [_tp_err] if _tp_err is not None else _template_drift(_tp)
    check("tp1 the example config's listed rows, its pricingAsOf and the source "
          "its usage note names all match the shipped table",
          _tp_diff == [], " | ".join(_tp_diff))
    _tp_rows = (((_tp or {}).get("usage") or {}).get("pricing") or {})
    _tp_model = sorted(m for m in _tp_rows if not m.startswith("_"))[:1]
    _tp_bad = None
    if _tp_err is None and _tp_model:
        _tp_bad = dict(_tp, usage=dict(_tp["usage"], pricingAsOf="2000-01-01",
                                       pricing=dict(_tp_rows)))
        _tp_bad["usage"]["pricing"][_tp_model[0]] = dict(
            _tp_rows[_tp_model[0]], out=_tp_rows[_tp_model[0]]["out"] + 1.0)
    _tp_bad_diff = _template_drift(_tp_bad) if _tp_bad is not None else []
    check("tp2 ...and the comparison fires: a drifted listed rate and a drifted "
          "date are both named, so tp1 is not green over a check that reads "
          "nothing",
          bool(_tp_model)
          and any(d.startswith("%s.out:" % _tp_model[0]) for d in _tp_bad_diff)
          and any(d.startswith("pricingAsOf: _usage_core") for d in _tp_bad_diff),
          repr(_tp_bad_diff))
    _tp_blank = (dict(_tp, usage=dict(_tp["usage"], pricingAsOf="  "))
                 if _tp_err is None else None)
    check("tp3 a blank template date is reported, the way pv4 reports one",
          _tp_blank is not None
          and "pricingAsOf: blank in template" in _template_drift(_tp_blank),
          repr(_template_drift(_tp_blank)) if _tp_blank is not None else _tp_err)

    # --- timestamps --------------------------------------------------------
    check("ts: millisecond Z form parses",
          M.parse_ts("2026-08-06T07:20:10.266Z") is not None)
    check("ts: microsecond form parses",
          M.parse_ts("2026-08-06T07:20:10.266123Z") is not None)
    check("ts: offset form normalizes to UTC",
          M.parse_ts("2026-08-06T09:20:10+02:00")
          == M.parse_ts("2026-08-06T07:20:10Z"))
    check("ts: garbage -> None", M.parse_ts("not-a-date") is None)
    check("ts: hour bucket is UTC-normalized",
          M.hour_bucket("2026-08-06T09:20:10+02:00") == "2026-08-06T07")
    check("ts: bucket_month / bucket_date / bucket_hour",
          M.bucket_month("2026-08-06T07") == "2026-08"
          and M.bucket_date("2026-08-06T07") == "2026-08-06"
          and M.bucket_hour("2026-08-06T07") == 7)

    # --- aggregation -------------------------------------------------------
    # The row fixture below is the one the `ag` cases already carried; the `agg`
    # and `mo` cases read it too, because the scan output they used to run over
    # is produced by usage_ledger.py, one layer above this file.
    def _ag_row(ts, phase, tokens):
        return {"ts": ts, "phaseId": phase, "taskId": phase + ".1",
                "model": "claude-opus-5", "author": "a@x",
                "sessionId": "s-" + phase, "branch": "main", "attr": "task",
                "agentType": "audit-executor", "msgs": 1, "in": tokens,
                "out": 2 * tokens, "cacheW5m": 1, "cacheW1h": 2,
                "cacheR": 3, "costUSD": 0.125 * tokens}

    # Three day keys out of five rows: two buckets repeat (only a repeated
    # key can tell the eager and lazy versions apart) and one occurs once.
    # Every `ts` is distinct, so grouping by "hour" gives five keys for the
    # same rows - that is what makes ag5 below a real second direction.
    _ag_rows = [_ag_row("2026-08-01T09", "P1", 10),
                _ag_row("2026-08-01T10", "P1", 20),
                _ag_row("2026-08-01T11", "P2", 40),
                _ag_row("2026-08-02T09", "P2", 80),
                _ag_row("2026-08-03T09", "P3", 160)]

    agg_all = M.totals(_ag_rows)
    check("agg: tokens is the sum of every token key",
          agg_all["tokens"] == sum(agg_all[k] for k in M.TOKEN_KEYS))
    check("agg: cache hit pct in range",
          0.0 <= agg_all["cacheHitPct"] <= 100.0)
    check("agg: unknown group key raises",
          _raises(lambda: M.aggregate(_ag_rows, "nope")))
    by_attr = M.aggregate(_ag_rows, "attr")
    check("agg: every row carries an attribution bucket",
          sum(v["msgs"] for v in by_attr.values()) == agg_all["msgs"])
    grid = M.heatmap(_ag_rows)
    check("agg: heatmap is 7x24", len(grid) == 7 and len(grid[0]) == 24)
    check("agg: heatmap totals match",
          sum(sum(r) for r in grid) == agg_all["tokens"])
    # --- month bucket (mo) --------------------------------------------
    check("mo1 'month' is a first-class group key, so --by month and byMonth "
          "exist without their own code paths",
          "month" in M.GROUP_KEYS)
    by_month = M.aggregate(_ag_rows, "month")
    check("mo2 every row lands in its calendar month",
          by_month.get("2026-08", {}).get("msgs") == agg_all["msgs"])
    _mo_rows = [dict(_ag_rows[0], ts="2026-07-31T23"),
                dict(_ag_rows[0], ts="2026-08-01T00")]
    _mo = M.aggregate(_mo_rows, "month")
    check("mo3 a month boundary splits two adjacent hours into two months",
          set(_mo) == {"2026-07", "2026-08"}
          and _mo["2026-07"]["msgs"] == _mo["2026-08"]["msgs"])
    check("mo4 a garbled ts groups under 'unknown', never dropped",
          M.aggregate([dict(_ag_rows[0], ts=None)], "month")
          .get("unknown", {}).get("msgs") == _ag_rows[0]["msgs"])

    # --- aggregate_area (aa): the read-time area join ------------------
    # tags_by_phase arrives ready-made (_areas.phase_tags) - this module
    # must stay stdlib-only, so the join is data in, never an import.
    _aa_rows = [
        {"ts": "2026-08-01T10", "phaseId": "P1", "msgs": 1, "in": 10,
         "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 1.0},
        {"ts": "2026-08-02T10", "phaseId": "P2", "msgs": 1, "in": 20,
         "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 2.0},
        {"ts": "2026-08-03T10", "phaseId": "P3", "msgs": 1, "in": 40,
         "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 4.0},
        {"ts": "2026-08-04T10", "phaseId": "P9", "msgs": 1, "in": 80,
         "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 8.0},
        {"ts": "2026-08-05T10", "msgs": 1, "in": 160, "out": 0,
         "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "costUSD": 16.0},
    ]
    _aa_map = {"P1": ["backend"], "P2": ["backend", "web"], "P3": []}
    _aa = M.aggregate_area(_aa_rows, _aa_map)
    check("aa1 rows join to areas through their phase's tags",
          _aa.get("backend", {}).get("msgs") == 2
          and _aa.get("backend", {}).get("in") == 30
          and _aa.get("web", {}).get("in") == 20)
    check("aa2 a multi-tag phase counts under EACH tag, so per-tag figures "
          "can sum past the ledger total - renderers must say so",
          sum(v["msgs"] for v in _aa.values()) == 6
          and M.totals(_aa_rows)["msgs"] == 5)
    check("aa3 no-tag phase, unknown phase and phase-less row all land in "
          "'untagged', never dropped",
          _aa.get(M.UNTAGGED_AREA, {}).get("msgs") == 3
          and _aa.get(M.UNTAGGED_AREA, {}).get("in") == 280)
    check("aa4 the join is read-time: a re-tagged map re-attributes the SAME "
          "rows with no backfill",
          M.aggregate_area(_aa_rows, {"P1": ["mobile"]})
          .get("mobile", {}).get("in") == 10)
    check("aa5 empty rows are {}, and a None map buckets everything untagged "
          "rather than raising",
          M.aggregate_area([], _aa_map) == {}
          and M.aggregate_area(_aa_rows, None)
          .get(M.UNTAGGED_AREA, {}).get("msgs") == 5)
    check("aa6 rows_for_area selects exactly the rows aggregate_area counts "
          "under the tag - one join, two callers, no drift",
          M.totals(M.rows_for_area(_aa_rows, _aa_map, "backend"))["in"] == 30
          == _aa.get("backend", {}).get("in")
          and M.totals(M.rows_for_area(_aa_rows, _aa_map, "web"))["in"] == 20
          == _aa.get("web", {}).get("in"))
    check("aa7 ...including the untagged bucket, and an unknown tag is []",
          M.totals(M.rows_for_area(_aa_rows, _aa_map, "untagged"))["in"] == 280
          and M.rows_for_area(_aa_rows, _aa_map, "nope") == [])

    # --- ag: the lazy accumulator (a measured hot spot) -----------------
    # `acc.setdefault(k, _blank())` evaluates `_blank()` EAGERLY, so a dict
    # plus five `set()`s were built and discarded for every row whose key
    # already existed - 20,000 allocations to fill 50 day buckets, and
    # `aggregate` runs 11 times per report and per panel usage request.
    # THE TWO HALVES ARE PROVEN APART ON PURPOSE: an output assertion cannot
    # see an allocation (the eager version returns exactly the same dict),
    # and an allocation count cannot see a wrong number.
    def _aggregate_eager(rows, by):
        """The pre-fix body, kept as an ORACLE so "faster" can never quietly
        become "different". `M._blank` is looked up on the module at CALL time,
        so the counting stub below is what this runs through too - which is what
        makes ag8 a measurement rather than a restatement."""
        keyfn = M.GROUP_KEYS[by]
        acc = {}
        for row in rows:
            acc.setdefault(keyfn(row), M._blank())
            M._add(acc[keyfn(row)], row)
        return dict((k, M._finish(v)) for k, v in acc.items())

    def _aggregate_area_eager(rows, tags_by_phase):
        acc = {}
        for row in rows:
            for tag in M._row_area_tags(row, tags_by_phase):
                acc.setdefault(tag, M._blank())
                M._add(acc[tag], row)
        return dict((k, M._finish(v)) for k, v in acc.items())
    check("ag1 the fixture really does repeat keys - over rows that are all "
          "unique the two versions are indistinguishable and ag4 would pass "
          "on the bug",
          len(M.aggregate(_ag_rows, "day")) == 3 and len(_ag_rows) == 5)
    check("ag2 output is unchanged against the eager setdefault oracle, for "
          "every group key, over repeated keys / a single-occurrence key / "
          "an empty ledger",
          all(M.aggregate(_r, _by) == _aggregate_eager(_r, _by)
              for _r in (_ag_rows, _ag_rows[4:], [])
              for _by in sorted(M.GROUP_KEYS)))
    _ag_tags = {"P1": ["backend"], "P2": ["backend", "web"], "P3": []}
    check("ag3 ...and aggregate_area's output is unchanged too, including "
          "the multi-tag phase that allocated TWICE per row",
          all(M.aggregate_area(_r, _ag_tags) == _aggregate_area_eager(_r, _ag_tags)
              for _r in (_ag_rows, _ag_rows[4:], [])))

    # `_blank` is swapped for a counting stub and restored in `finally` -
    # the same technique audit-journal.py's selftest uses for its anchor
    # counter. THE COUNT IS THE DEFECT; nothing else in the suite can see it.
    # It is rebound ON `M`, not in this file's `globals()`: see the module
    # docstring for why the literal move would have measured nothing.
    _ag_calls = [0]
    _ag_real_blank = M._blank

    def _ag_counting_blank():
        _ag_calls[0] += 1
        return _ag_real_blank()

    M._blank = _ag_counting_blank
    try:
        _ag_calls[0] = 0
        M.aggregate(_ag_rows, "day")
        _ag_by_day = _ag_calls[0]
        _ag_calls[0] = 0
        M.aggregate(_ag_rows, "hour")
        _ag_by_hour = _ag_calls[0]
        _ag_calls[0] = 0
        M.aggregate([], "day")
        _ag_empty = _ag_calls[0]
        _ag_calls[0] = 0
        M.aggregate_area(_ag_rows, _ag_tags)
        _ag_area = _ag_calls[0]
        _ag_calls[0] = 0
        _aggregate_eager(_ag_rows, "day")
        _ag_eager_day = _ag_calls[0]
    finally:
        M._blank = _ag_real_blank

    check("ag4 `_blank()` is called once per KEY, not once per row: 3 "
          "allocations for 5 rows over 3 day buckets",
          _ag_by_day == 3, "got %d" % _ag_by_day)
    # The other direction. A "lazy" accumulator that reused ONE slot, or
    # allocated nothing, would satisfy ag4 by accident; it cannot satisfy
    # this, because here every row genuinely IS its own key.
    check("ag5 ...and once per row when every row is its own key, so ag4 is "
          "not passing on a version that stopped allocating at all",
          _ag_by_hour == 5, "got %d" % _ag_by_hour)
    check("ag6 an empty ledger allocates nothing", _ag_empty == 0,
          "got %d" % _ag_empty)
    check("ag7 aggregate_area allocates once per TAG (backend, web, "
          "untagged), not once per row x tag - 3, not 6",
          _ag_area == 3, "got %d" % _ag_area)
    # The counter itself is proven to fire: run the ORACLE through it and
    # watch the pre-fix number come back. Without this, ag4/ag7 could be
    # green because the stub was never installed.
    check("ag8 the counter is real - the eager oracle, measured the same "
          "way, still allocates once per ROW (5), which is the defect",
          _ag_eager_day == 5, "got %d" % _ag_eager_day)


    _resolver_cases(check)
    _read_price_cases(check)


# --- rt: every summed cost is priced at read time by the resolved table ---------
# A row priced when it was written at a rate no longer in any table, so the stored
# figure and the read-time figure disagree on every priced row: 1M input on opus-5
# stored at $15 (resolved table says $5), 1M output on sonnet-5 stored at $75
# (resolved: $10). The third row carries no token fields at all, so it cannot be
# priced again and must keep its stored $2.50.
def _rt_row(task, model, stored, **tokens):
    row = {"ts": "2026-09-01T10", "taskId": task, "phaseId": "P1",
           "model": model, "msgs": 1, "costUSD": stored}
    row.update(tokens)
    return row


def _rt_full(model, task, stored, key):
    tokens = dict((k, 0) for k in M.TOKEN_KEYS)
    tokens[key] = 1000000
    return _rt_row(task, model, stored, **tokens)


def _rt_price(rows, table):
    """`priced_at_read`'s answer, or None when it cannot answer - so a missing
    or raising function fails its cases by assertion, not by aborting."""
    fn = getattr(M, "priced_at_read", None)
    if fn is None:
        return None
    try:
        return fn(rows, table)
    except Exception:  # noqa: BLE001 - the case reports the absent answer
        return None


def _read_price_cases(check):
    shipped = M.resolve_pricing(None, None)["table"]
    ledger = [_rt_full("claude-opus-5", "T1", 15.0, "in"),
              _rt_full("claude-sonnet-5", "T2", 75.0, "out"),
              _rt_row("T1", "claude-opus-5", 2.5)]
    before = [dict(r) for r in ledger]
    got = _rt_price(ledger, shipped) or {}
    rows = got.get("rows") or []
    tot = M.totals(rows) if rows else {}
    check("rt1 a ledger whose stored costUSD came from another table sums at "
          "the resolved table's prices (5 + 10 + the kept 2.5), not the stored "
          "92.5: %r" % (tot.get("costUSD"),),
          abs((tot.get("costUSD") or 0) - 17.5) < 1e-9)
    by_task = M.aggregate(rows, "task") if rows else {}
    check("rt2 ...and per task too, which is what cost per task, the bands and "
          "the most-expensive table read: %r"
          % (dict((k, v["costUSD"]) for k, v in by_task.items()),),
          set(by_task) == {"T1", "T2"}
          and abs(by_task["T1"]["costUSD"] - 7.5) < 1e-9
          and abs(by_task["T2"]["costUSD"] - 10.0) < 1e-9)
    check("rt3 a row with no token fields keeps its stored figure and is "
          "counted as priced when written: %r" % (got.get("pricedWhenWritten"),),
          got.get("pricedWhenWritten") == 1 and len(rows) == 3
          and rows[2].get("costUSD") == 2.5)
    # The second direction: a guard that counted every row would pass rt3.
    clean = _rt_price(ledger[:2], shipped) or {}
    check("rt4 ...while a ledger whose every row carries its tokens counts "
          "none: %r" % (clean.get("pricedWhenWritten"),),
          clean.get("pricedWhenWritten") == 0
          and len(clean.get("rows") or []) == 2)
    partial = _rt_row("T3", "claude-opus-5", 4.0, **{"in": 1000000, "out": 0})
    part = _rt_price([partial], shipped) or {}
    check("rt5 a row missing some token fields cannot be priced whole, so it "
          "keeps its stored figure and is counted: %r" % (part,),
          part.get("pricedWhenWritten") == 1
          and (part.get("rows") or [{}])[0].get("costUSD") == 4.0)
    check("rt6 the ledger is never rewritten - the rows handed in keep the "
          "stored costUSD they were written with",
          ledger == before and bool(rows) and rows[0] is not ledger[0])
    check("rt7 an empty ledger prices to an empty list and counts nothing: %r"
          % (_rt_price([], shipped),),
          _rt_price([], shipped) == {"rows": [], "pricedWhenWritten": 0,
                                     "mix": {"stamped": 0, "readPriced": 0,
                                             "unpriced": 0, "unpricedTokens": 0,
                                             "unpricedModels": []}})

    # One row of each kind the read can meet, so every count is 1 and a count
    # read off the wrong kind cannot land on the right number by accident.
    # The unpriced row carries more tokens than the others so `unpricedTokens`
    # cannot be confused with a row count.
    _mx_stamped = dict(_rt_full("claude-opus-5", "T1", 9.0, "in"),
                       rate={"in": 3.0, "out": 0, "cacheW5m": 0,
                             "cacheW1h": 0, "cacheR": 0})
    _mx_unpriced = _rt_full("claude-nonesuch-1", "T4", 1.0, "out")
    _mx_unpriced["out"] = 2500000
    mixed = [_mx_stamped, _rt_full("claude-opus-5", "T2", 15.0, "in"),
             _rt_row("T3", "claude-opus-5", 2.5), _mx_unpriced]
    mx = _rt_price(mixed, shipped) or {}
    check("rt10 (one stamped, one priced again, one kept, one on a model with "
          "no rate) priced_at_read returns the count of each, and the four "
          "add up to the rows read: %r"
          % ({k: v for k, v in mx.items() if k != "rows"},),
          mx.get("pricedWhenWritten") == 1
          and mx.get("mix") == {"stamped": 1, "readPriced": 1, "unpriced": 1,
                                "unpricedTokens": 2500000,
                                "unpricedModels": ["claude-nonesuch-1"]}
          and len(mx.get("rows") or []) == 4)

    # --- rv: a row priced through a project's declared `_default` is labelled.
    _rv_table = {"claude-opus-5": dict(shipped["claude-opus-5"]),
                 "_default": {"in": 1.0, "out": 1.0, "cacheW5m": 0,
                              "cacheW1h": 0, "cacheR": 0}}
    check("rv1 _rate_via names _default only for a model no named entry answers",
          M._rate_via("claude-nonesuch-1", _rv_table) == "_default"
          and M._rate_via("claude-opus-5", _rv_table) is None
          and M._rate_via("claude-opus-5-1-20260101", _rv_table) is None)
    check("rv2 ...and a table with no _default (the shipped one) never does",
          M._rate_via("claude-nonesuch-1", shipped) is None
          and M._rate_via("claude-nonesuch-1") is None)
    _rv_rows = [_rt_full("claude-nonesuch-1", "T1", 0.0, "in"),
                _rt_full("claude-nonesuch-2", "T2", 0.0, "in"),
                _rt_full("claude-opus-5", "T3", 0.0, "in")]
    _rv_stamped = dict(_rt_full("claude-nonesuch-3", "T4", 0.0, "in"),
                       rate=dict(_rv_table["_default"]), rateVia="_default")
    _rv_mix = (_rt_price(_rv_rows + [_rv_stamped], _rv_table) or {}).get("mix", {})
    check("rv3 priced_at_read counts the rows a declared _default priced, "
          "stamped or read-priced, and names their models: %r" % (_rv_mix,),
          _rv_mix.get("viaDefault") == 3
          and _rv_mix.get("viaDefaultModels")
          == ["claude-nonesuch-1", "claude-nonesuch-2", "claude-nonesuch-3"])
    # Second direction: the label must not fire when nothing used _default.
    _rv_clean = (_rt_price(_rv_rows[2:], _rv_table) or {}).get("mix", {})
    check("rv4 a ledger no _default priced carries no viaDefault key at all: %r"
          % (_rv_clean,),
          "viaDefault" not in _rv_clean and "viaDefaultModels" not in _rv_clean)

    # A plan's table naming one model is laid over the shipped table model by
    # model, like a config table: an unnamed model keeps its shipped row rather
    # than falling to a `_default` the plan never declared.
    named = {"in": 1.5, "out": 7.5, "cacheW5m": 1.875, "cacheW1h": 3.0,
             "cacheR": 0.15}
    ans = M.resolve_pricing(
        {"meta": {"usage": {"pricing": {"claude-sonnet-5": named}}}}, None)
    table = ans.get("table") or {}
    haiku = M.rates_for("claude-haiku-4-5", table)
    check("rt8 a manifest table naming one model prices another at its shipped "
          "row, not at the _default: haiku out = %r" % (haiku.get("out"),),
          haiku == M.DEFAULT_PRICING["claude-haiku-4-5"]
          and abs(M.price({"out": 1000000}, "claude-haiku-4-5", table) - 5.0)
          < 1e-9)
    check("rt9 ...while the model it names is priced at the plan's row, and the "
          "basis stays `manifest`: %r" % (ans.get("basis"),),
          M.rates_for("claude-sonnet-5", table) == named
          and ans.get("basis") == "manifest")

    # --- rb: an UNSTAMPED row is priced by the table row in effect on ITS
    # OWN hour bucket - never by "now" - so two rows of one dated model, one
    # written in July and one in October, price at whichever rate was in
    # effect on each row's own date.
    _rb_old = {"in": 1.0, "out": 5.0, "cacheW5m": 1.25, "cacheW1h": 2.0,
               "cacheR": 0.1}
    _rb_new = {"in": 2.0, "out": 10.0, "cacheW5m": 2.5, "cacheW1h": 4.0,
               "cacheR": 0.2}
    _rb_table = {"claude-dated-9": [
        {"effectiveFrom": "2026-01-01", "rates": _rb_old},
        {"effectiveFrom": "2026-09-15", "rates": _rb_new},
    ]}

    def _rb_row(ts):
        tokens = dict((k, 0) for k in M.TOKEN_KEYS)
        tokens["in"] = 1_000_000
        row = {"ts": ts, "taskId": "TD", "phaseId": "P1",
               "model": "claude-dated-9", "msgs": 1, "costUSD": 0.0}
        row.update(tokens)
        return row

    _rb_july, _rb_october = _rb_row("2026-07-15T10"), _rb_row("2026-10-01T10")
    _rb_priced = M.priced_at_read([_rb_july, _rb_october], _rb_table)["rows"]
    check("rb1 the unstamped July row (before the rate changed) prices at "
          "the EARLIER row ($1/MTok input), not at 'now': %r"
          % (_rb_priced[0]["costUSD"],),
          abs(_rb_priced[0]["costUSD"] - 1.0) < 1e-9)
    check("rb2 ...while the unstamped October row of the SAME model prices "
          "at the LATER row ($2/MTok) that took effect in between - one "
          "model, two rows, two different rates: %r"
          % (_rb_priced[1]["costUSD"],),
          abs(_rb_priced[1]["costUSD"] - 2.0) < 1e-9)

    # --- rs: a STAMPED row is priced from its OWN stamp, never re-resolved -
    # the mechanism that keeps a rate change from rewriting history.
    _rs_written_at = {"in": 3.0, "out": 15.0, "cacheW5m": 3.75, "cacheW1h": 6.0,
                      "cacheR": 0.3}
    _rs_row = dict(_rb_row("2026-09-01T10"), rate=_rs_written_at,
                   rateEffectiveFrom=None, rateAsOf="2026-08-01",
                   rateSource="https://example.invalid/pricing")
    _rs_changed_table = {"claude-dated-9": {"in": 999.0, "out": 999.0,
                                            "cacheW5m": 999.0, "cacheW1h": 999.0,
                                            "cacheR": 999.0}}
    _rs_priced = M.priced_at_read([_rs_row], _rs_changed_table)["rows"]
    check("rs1 re-pricing a STAMPED row after the table changes completely "
          "returns the figure its OWN stamp names (3.0/MTok input), never "
          "the new table's (999.0): %r" % (_rs_priced[0]["costUSD"],),
          abs(_rs_priced[0]["costUSD"] - 3.0) < 1e-9)
    # The allow twin: a stamp of None (the row was unpriced when written)
    # must not fall back to the table either - it stays unpriced.
    _rs_unpriced_row = dict(_rb_row("2026-09-01T10"), rate=None,
                            rateEffectiveFrom=None, rateAsOf=None,
                            rateSource=None)
    _rs_unpriced = M.priced_at_read([_rs_unpriced_row], _rb_table)["rows"]
    check("rs2 a row stamped with NO rate (unpriced when written) stays "
          "unpriced at read time too, rather than being guessed from "
          "whatever table it is handed",
          _rs_unpriced[0].get("costUSD") is None
          and _rs_unpriced[0].get("unpriced") is True)


# --- rp: one price table per project, whichever surface asks -------------------
def _rp_ask(fn):
    """A surface's answer, or the exception it raised as a value - so a surface
    that cannot answer fails its case instead of aborting the suite."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - surfaced as the case's detail
        return {"error": repr(exc)}


def _rp_key(answer):
    """The part of an answer every surface must agree on."""
    if not isinstance(answer, dict) or "error" in answer:
        return answer
    return (answer.get("table"), answer.get("basis"), answer.get("asOf"),
            answer.get("source"))


def _resolver_cases(check):
    import json
    import shutil
    import tempfile
    import _loader

    ul = _loader.load_script("usage_ledger.py", modname="rp_usage_ledger",
                             cache=False)
    rl = _loader.load_script("_usage_load.py", modname="rp_usage_load",
                             cache=False)
    au = _loader.load_script("audit-usage.py", modname="rp_audit_usage",
                             cache=False)
    pu = _loader.load_script("_panel_usage.py", modname="rp_panel_usage",
                             cache=False)
    gd = _loader.load_script("gen-demo-usage.py", modname="rp_gen_demo_usage",
                             cache=False)
    mu = _loader.load(os.path.join(_harness.HOOKS_DIR, "meter-usage.py"),
                      "rp_meter_usage")

    # Every rate differs from the shipped sonnet row, and the manifest's row
    # differs from the config's, so no wrong precedence can match by accident.
    cfg_sonnet = {"in": 3.0, "out": 15.0, "cacheW5m": 3.75, "cacheW1h": 6.0,
                  "cacheR": 0.3}
    man_table = {"_default": {"in": 7.0, "out": 35.0, "cacheW5m": 8.75,
                              "cacheW1h": 14.0, "cacheR": 0.7},
                 "claude-sonnet-5": {"in": 1.5, "out": 7.5, "cacheW5m": 1.875,
                                     "cacheW1h": 3.0, "cacheR": 0.15}}
    # `_with_long_prompt_tiers` - every resolver answer carries the published
    # long-prompt row laid in, so the expected table here must too (lp5/lp6
    # hold that mechanism to account on its own; this is only the fixture
    # catching up to it).
    shipped = M._with_long_prompt_tiers(
        dict((k, dict(v)) for k, v in M.DEFAULT_PRICING.items()))
    overlay = dict(shipped)
    overlay["claude-sonnet-5"] = dict(cfg_sonnet)
    man_overlay = dict(shipped)
    man_overlay.update(man_table)

    projects = (
        # name, meta.usage, raw config (None = no file), expected answer
        ("config-only", {"pricingAsOf": "2026-07-01"},
         {"usage": {"pricingAsOf": " 2026-08-06 ",
                    "pricing": {"claude-sonnet-5": cfg_sonnet}}},
         (overlay, "config", "2026-08-06", None)),
        ("manifest", {"pricingAsOf": "2026-09-01", "pricing": man_table},
         {"usage": {"pricingAsOf": "2026-08-06",
                    "pricing": {"claude-sonnet-5": cfg_sonnet}}},
         (man_overlay, "manifest", "2026-09-01", None)),
        ("neither", {}, None,
         (shipped, "shipped", M.PRICING_AS_OF, M.PRICING_SOURCE_URL)),
    )
    root = tempfile.mkdtemp(prefix="usage-core-resolver-")
    try:
        for name, meta_usage, raw_cfg, want in projects:
            proj = os.path.join(root, name)
            for d in (".git", os.path.join(".claude", "usage"),
                      os.path.join("docs", "audit")):
                os.makedirs(os.path.join(proj, d))
            manifest = {"meta": {"version": 2, "repo": name,
                                 "usage": meta_usage}, "phases": []}
            mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
            with open(mpath, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh)
            if raw_cfg is not None:
                with open(os.path.join(proj, ".claude", "audit.config.json"),
                          "w", encoding="utf-8") as fh:
                    json.dump(raw_cfg, fh)

            def _bind(m=manifest, p=mpath, d=proj, c=raw_cfg):
                return (
                    ("core", lambda: M.resolve_pricing(m, c)),
                    ("usage_ledger", lambda: ul.project_pricing(m, p, d)),
                    ("report", lambda: rl._project_pricing(m, p, d, ul)),
                    ("/audit:usage", lambda: au.project_pricing(m, p, d)),
                    ("panel", lambda: pu._usage_pricing(ul, m, c or {})),
                    ("meter hook", lambda: mu._pricing(ul, m, d)),
                    ("demo generator", lambda: gd._load_pricing(m, p)),
                )

            answers = [(surface, _rp_key(_rp_ask(fn))) for surface, fn in _bind()]
            core = answers[0][1]
            check("rp-%s the resolver answers the %s table, dated %r, for a "
                  "project declaring %s: %r"
                  % (name, want[1], want[2], name, core),
                  core == want)
            apart = [(s, a) for s, a in answers if a != want]
            check("rp-%s ...and every surface that prices this project asks it "
                  "and gets the same table and basis back - apart: %r"
                  % (name, apart),
                  apart == [] and len(answers) == 7)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # The config overlay replaces a NAMED row whole and leaves every other row
    # shipped - the merge `hooks/_config.usage_cfg` applies.
    hooks_cfg = _loader.load_hooks_config(modname="rp_hooks_config", cache=False)
    raw = {"usage": {"pricing": {"claude-sonnet-5": {"in": 9.0}}}}
    got = _rp_ask(lambda: M.resolve_pricing({}, raw))
    # hooks/_config.usage_cfg has no notion of the long-prompt overlay (that
    # split lives in scripts/, which hooks/ may not import) - compared with it
    # laid in on both sides, the same way `resolve_pricing` lays it into
    # every table it hands back.
    check("rp-overlay a partial config row replaces the shipped row whole, "
          "exactly as usage_cfg merges it, and leaves the other rows shipped",
          isinstance(got, dict)
          and got.get("table") == M._with_long_prompt_tiers(
              hooks_cfg.usage_cfg(raw).get("pricing"))
          and got.get("table", {}).get("claude-haiku-4-5")
          == M.DEFAULT_PRICING["claude-haiku-4-5"])
    # The second direction: a declared-but-empty table is no declaration.
    got_e = _rp_ask(lambda: M.resolve_pricing(
        {"meta": {"usage": {"pricing": {}}}}, {"usage": {"pricing": {}}}))
    check("rp-empty an empty table in either place is not a declaration - the "
          "basis stays `shipped`: %r" % (_rp_key(got_e),),
          isinstance(got_e, dict) and got_e.get("basis") == "shipped")
    got_s = _rp_ask(lambda: M.resolve_pricing(None, None))
    check("rp-mutate the shipped answer is a copy - writing to it does not "
          "reprice the next caller",
          isinstance(got_s, dict) and isinstance(got_s.get("table"), dict)
          and got_s["table"] == M._with_long_prompt_tiers(M.DEFAULT_PRICING)
          and got_s["table"] is not M.DEFAULT_PRICING
          and got_s["table"]["claude-sonnet-5"]
          is not M.DEFAULT_PRICING["claude-sonnet-5"])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_core.py --selftest\n")
    raise SystemExit(2)
