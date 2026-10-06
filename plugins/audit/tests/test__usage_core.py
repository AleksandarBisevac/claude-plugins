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
import _usage_core as M                            # noqa: E402


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
    check("price: unknown model falls back to _default",
          M.rates_for("some-future-model")["in"]
          == M.DEFAULT_PRICING["_default"]["in"])
    check("price: non-string model falls back",
          M.rates_for(None)["in"] == M.DEFAULT_PRICING["_default"]["in"])
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
    _pp_extra["claude-future-9"] = dict(M.DEFAULT_PRICING["_default"])
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

    # Sonnet 5.5 has no row of its own: by longest prefix it is priced as
    # claude-sonnet-5, which is right only while the two carry the same rates.
    # The expected row is the page's own Sonnet 5.5 line, so a later correction
    # to claude-sonnet-5 alone goes red HERE and forces the choice between
    # giving Sonnet 5.5 its own row and confirming the two still agree.
    _pr_sonnet_5_5 = {"in": 2.0, "out": 10.0, "cacheW5m": 2.5, "cacheW1h": 4.0,
                      "cacheR": 0.2}
    check("pr6 claude-sonnet-5-5, priced through the claude-sonnet-5 row, still "
          "carries the rates the official page lists for Sonnet 5.5",
          M.rates_for("claude-sonnet-5-5") == _pr_sonnet_5_5
          and M.rates_for("claude-sonnet-5-5-20261001") == _pr_sonnet_5_5,
          "got %r" % (M.rates_for("claude-sonnet-5-5"),))

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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_core.py --selftest\n")
    raise SystemExit(2)
