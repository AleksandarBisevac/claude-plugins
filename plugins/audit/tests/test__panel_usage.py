#!/usr/bin/env python3
"""
The cases for `_panel_usage.py` - the Usage tab's facts, the one manifest read
per request, and the single key list both of its branches return.

Moved out of `test__panel_state.py` at U3.1, with the code it covers. `M` is the
module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as the module imports it)
import _panel_paths as _paths                     # noqa: E402  (the shared base)
import _panel_usage as M            # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import pathlib                                 # noqa: F401  (used by moved cases)
    import shutil
    import tempfile

    _src = _harness.module_source(M)

    def _atomic_write_json(path, obj):
        """The selftest's own fixture writer -- straight through `_manifest_io`,
        the implementation panel-server's `_atomic_write_json` delegates to."""
        _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)

    tmp = tempfile.mkdtemp(prefix="panel-usage-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
    _atomic_write_json(_paths._config_path(proj), {"trivialLineThreshold": 40})
    mpath = _paths._manifest_path(proj, _paths.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T", "status": "pending"},
                              {"id": "P1.2", "title": "T2", "status": "pending"}]}]})

    u = M.usage_state(proj)
    check("usage_state on a project with no ledger is empty, not an error",
          u["facts"] == [] and u["totalRows"] == 0 and "ledgerDir" in u)
    led = os.path.join(proj, ".claude", "usage")
    os.makedirs(led, exist_ok=True)
    with open(os.path.join(led, "2026-08.jsonl"), "w", encoding="utf-8") as fh:
        for i, (model, author) in enumerate(
                (("claude-opus-5", "a@x.io"), ("claude-haiku-4-5", "b@x.io"))):
            fh.write(json.dumps({
                "ts": "2026-08-0%dT1%d" % (i + 1, i), "sessionId": "s%d" % i,
                "phaseId": "P1", "taskId": "P1.%d" % (i + 1), "attr": "task",
                "model": model, "author": author, "agentType": "audit-executor",
                "msgs": 2, "in": 5, "out": 100, "cacheW5m": 0, "cacheW1h": 0,
                "cacheR": 50, "costUSD": 0.25}) + "\n")
        fh.write("{ torn line\n")
    u = M.usage_state(proj)
    check("usage_state reads the ledger into positional facts",
          len(u["facts"]) == 2 and u["fields"][0] == "ts"
          and len(u["facts"][0]) == len(u["fields"]))
    check("usage_state tolerates a torn ledger line", u["totalRows"] == 2)
    check("usage_state carries phase titles for labelling",
          isinstance(u["phaseTitles"], dict))
    check("usage_state does not roll up a small ledger", u["rolled"] is False)
    check("usage facts carry no prompt content — only dimensions and counts",
          all(len(f) == 10 for f in u["facts"]))
    # --- one manifest read per /api/usage ---------------------------------------
    # The payload answers five questions about ONE document (titles/taskMeta/
    # budgets, routingAdvice, monthlyPlan, phaseAreas, areaOwners) and each used to
    # re-read it — on a sharded plan that is 1 index + 1 file per phase, per
    # question. COUNTED rather than asserted-present: a source pin cannot tell one
    # call from five, which is exactly the regression this guards.
    _lms_calls = [0]
    _real_lms = _mio.load_manifest_safe

    def _counting_lms(path):
        _lms_calls[0] += 1
        return _real_lms(path)

    _mio.load_manifest_safe = _counting_lms
    try:
        _hoisted = M.usage_state(proj)
    finally:
        _mio.load_manifest_safe = _real_lms
    check("usage_state reads the manifest exactly ONCE for all five of its "
          "manifest-derived fields (each used to re-read it)",
          _lms_calls[0] == 1)
    check("counting the reads did not change the payload",
          _hoisted == u)
    # The other direction, and the one that looks vacuous: "read once" must mean
    # once PER REQUEST, not once per process. A manifest memoized across requests
    # would satisfy the count above and then serve a stale plan forever — the
    # `_VIEWER_CACHE` failure — so edit the plan on disk and require the next
    # response to carry it.
    _m_before = _mio.load_manifest_safe(mpath)
    try:
        _m_edited = json.loads(json.dumps(_m_before))
        _m_edited["phases"][0]["title"] = "Retitled between requests"
        _atomic_write_json(mpath, _m_edited)
        check("the single read is per REQUEST — a plan edited between two calls "
              "shows up in the second",
              M.usage_state(proj)["phaseTitles"].get("P1")
              == "Retitled between requests")
    finally:
        _atomic_write_json(mpath, _m_before)
    check("...and restoring the plan restores the payload",
          M.usage_state(proj)["phaseTitles"].get("P1") == "P")

    _saved = M._MAX_FACTS
    try:
        M._MAX_FACTS = 1
        ru = M.usage_state(proj)
        check("oversized ledger rolls hourly facts up to daily, and says so",
              ru["rolled"] is True and all(len(f[0]) == 10 for f in ru["facts"]))
    finally:
        M._MAX_FACTS = _saved
    _cfg_path = os.path.join(proj, ".claude", "audit.config.json")
    _prev_cfg = (open(_cfg_path, encoding="utf-8").read()
                 if os.path.isfile(_cfg_path) else None)
    try:
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"enabled": False, "showCost": False}}, fh)
        du = M.usage_state(proj)
        check("usage_state reports metering off so the tab can explain itself",
              du["enabled"] is False and du["showCost"] is False)
        # The empty branch's own comment requires it: every key the populated
        # branch returns must appear here too, or a fresh install reads undefined.
        check("the no-ledger shape carries pricingAsOfDeclared as well, so a "
              "fresh install does not read undefined",
              "pricingAsOfDeclared" in du and du["pricingAsOfDeclared"] is False)
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"pricingAsOf": "2026-01-02"}}, fh)
        check("a declared date is reported as declared, and travels with it",
              M.usage_state(proj)["pricingAsOfDeclared"] is True
              and M.usage_state(proj)["pricingAsOf"] == "2026-01-02")
        # --- F168: the rate basis, trimmed at the door -------------------------
        # `_declared_as_of` decides on the TRIMMED config value and this payload
        # served the MERGED one as typed, so the two disagreed about one config
        # value inside one dict literal. The fixture is padded rather than clean
        # on purpose: an unpadded date passes on both versions of the code, so it
        # cannot tell the fix from the bug. The case above is the other half of
        # that pair - it is what fails if the trim ever eats a legitimate date.
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"pricingAsOf": "  2026-01-02  "}}, fh)
        _pad = M.usage_state(proj)
        check("pa1 a PADDED date is trimmed where the config becomes plugin "
              "data. usage-view.js prints 'rates as of ' + this value verbatim, "
              "so serving it as typed puts the padding on the tab: %r"
              % (_pad["pricingAsOf"],),
              _pad["pricingAsOf"] == "2026-01-02"
              and _pad["pricingAsOfDeclared"] is True)
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"pricingAsOf": "   "}}, fh)
        _blank = M.usage_state(proj)
        check("pa2 ...and a whitespace-only one collapses to None - the shape "
              "absence already has - rather than shipping a TRUTHY empty string "
              "beside a flag saying this project declared nothing, which is the "
              "second kind of empty the other three readers were taught not to "
              "serve: %r" % (_blank["pricingAsOf"],),
              _blank["pricingAsOf"] is None
              and _blank["pricingAsOfDeclared"] is False)
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"pricingAsOf": 20260102}}, fh)
        check("pa3 a hand-edited NUMBER answers None instead of raising - the "
              "trim sits inside the payload's own dict literal, so an exception "
              "there costs the whole Usage tab and not one line of context",
              M.usage_state(proj)["pricingAsOf"] is None
              and M.usage_state(proj)["pricingAsOfDeclared"] is False)
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"showCost": True}}, fh)
        _dd = M.usage_state(proj)
        check("an undeclared one still carries the merged default as the VALUE, "
              "flagged as undeclared - the client decides, the server does not lie",
              _dd["pricingAsOfDeclared"] is False and _dd["pricingAsOf"])
    finally:
        if _prev_cfg is None:
            os.remove(_cfg_path)
        else:
            with open(_cfg_path, "w", encoding="utf-8") as fh:
                fh.write(_prev_cfg)

    # --- monthlyPlan (C2): the Monthly card's server-shipped plan half ----------
    # The ledger half of that card is recomputed in the browser under the current
    # filters; the plan half cannot be (the client has no manifest), so it ships
    # here. Key parity first: the empty branch must carry every key the populated
    # branch returns — the pinned rule beside the empty dict — so a fresh install
    # reads {} and never undefined.
    _mp_empty = M.usage_state(os.path.join(tmp, "no-such-proj"))
    check("usage_state ships monthlyPlan in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          _mp_empty["facts"] == [] and "monthlyPlan" in _mp_empty
          and _mp_empty["monthlyPlan"] == {})
    with open(mpath, encoding="utf-8") as _fh:
        _orig_manifest = json.load(_fh)
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2},
            "phases": [{"id": "P1", "title": "P", "status": "done",
                        "mergedAt": "2026-08-06T10:00:00Z",
                        "tasks": [{"id": "P1.1", "title": "T", "status": "done",
                                   "completedAt": "2026-08-03T10:00:00Z"}]}],
            "bugs": [{"id": "BUG-1", "status": "open",
                      "reportedAt": "2026-07-02T10:00:00Z", "taskId": "P1.1"}]})
        _mp = M.usage_state(proj)
        check("the populated branch derives monthlyPlan from the manifest "
              "through monthly_activity - completedAt/reportedAt/mergedAt "
              "buckets, bugsFixed via the linked done task",
              _mp["monthlyPlan"].get("2026-08", {}).get("tasksCompleted") == 1
              and _mp["monthlyPlan"].get("2026-08", {}).get("phasesMerged") == 1
              and _mp["monthlyPlan"].get("2026-07", {}).get("bugsReported") == 1
              and _mp["monthlyPlan"].get("2026-08", {}).get("bugsFixed") == 1)
    finally:
        _atomic_write_json(mpath, _orig_manifest)

    # --- phaseAreas (D4): the Usage tab's area filter join map ------------------
    # The client attributes spend to areas in a read-time join (row.phaseId ->
    # phase.area tags), so the map ships with the facts. Key parity again: BOTH
    # branches carry the key, and an untagged phase maps to [] rather than being
    # missing, so the client can tell "known phase, no tags" from "phase the
    # plan never heard of".
    check("usage_state ships phaseAreas in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          "phaseAreas" in _mp_empty and _mp_empty["phaseAreas"] == {})
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2},
            "phases": [
                {"id": "P1", "title": "A", "status": "done",
                 "area": ["backend", "sec"], "tasks": []},
                {"id": "P2", "title": "B", "status": "pending", "tasks": []}]})
        check("the populated branch derives phaseAreas through _areas."
              "phase_tags - a multi-tag phase keeps every tag, an untagged "
              "phase maps to [], not missing",
              M.usage_state(proj).get("phaseAreas")
              == {"P1": ["backend", "sec"], "P2": []})
    finally:
        _atomic_write_json(mpath, _orig_manifest)

    # --- areaOwners (v0.34 D3): the advisory owner per registered area ----------
    # panel.js joins UF.author against these values for the person header's
    # "owns:" line and titles the area select options. Key parity again - the
    # sibling case beside phaseAreas', because a key in one branch only is an
    # `undefined` that ships on every fresh install.
    check("usage_state ships areaOwners in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          "areaOwners" in _mp_empty and _mp_empty["areaOwners"] == {})
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2,
                     "areas": {"backend": {"root": "src",
                                           "owner": " jane@x.com "},
                               "sec": {"root": "sec", "owner": None},
                               "web": {"root": "web"}}},
            "phases": [{"id": "P1", "title": "A", "status": "done",
                        "area": ["backend", "sec"], "tasks": []}]})
        check("the populated branch maps tag -> trimmed owner through _areas."
              "registry - only tags that DECLARE a non-null owner enter the "
              "map, so null ('nobody') and undeclared read the same to the UI",
              M.usage_state(proj).get("areaOwners") == {"backend": "jane@x.com"})
    finally:
        _atomic_write_json(mpath, _orig_manifest)
    # --- up: the /api/usage payload has ONE key list ----------------------------
    # `usage_state` used to end in two dict literals - an `empty` one for the
    # no-data path and a populated one - spelling the same eighteen keys twice
    # with nothing comparing them, and `counts` spelling the same eight twice one
    # level down. A key present in one only is an `undefined` in the panel that
    # shows up on a repo with NO LEDGER: only on a fresh install, i.e. only for a
    # new user and never for anyone in a position to notice. It had already
    # happened three times - monthlyPlan, phaseAreas and areaOwners each carry a
    # case above pinning that ONE key by name. up1 is the general form of those
    # three: it fails on the next key, not on a key someone thought to name.
    _up_empty = M.usage_state(os.path.join(tmp, "no-such-proj-for-parity"))
    _up_full = M.usage_state(proj)
    check("up1 the no-ledger branch and the populated one ship the SAME key "
          "set - compared whole, not as a subset, and counted so a key cannot "
          "hide behind a duplicate: %r"
          % (sorted(set(_up_empty) ^ set(_up_full)),),
          set(_up_empty) == set(_up_full)
          and len(_up_empty) == len(_up_full) == 18
          and _up_full["facts"] and not _up_empty["facts"])
    check("up2 ...and one level down, where `counts` was the second literal "
          "nobody was comparing either: %r"
          % (sorted(set(_up_empty["counts"]) ^ set(_up_full["counts"])),),
          set(_up_empty["counts"]) == set(_up_full["counts"])
          and len(_up_full["counts"]) == 8)
    _up_default = M._usage_shape()
    _up_differs = sorted(k for k in _up_default
                         if _up_empty[k] != _up_default[k])
    check("up3 the no-ledger branch IS _usage_shape with only the "
          "CONFIG-derived keys overridden - it writes no data key of its own, "
          "so a key added to the shape reaches it without anyone remembering "
          "to add it twice: %r" % (_up_differs,),
          set(_up_differs) <= {"enabled", "ledgerDir", "showCost",
                               "pricingAsOf", "pricingAsOfDeclared", "bands"})
    _up_ok, _up_msg = _harness.attempt(M._usage_shape, phaseTitle={})
    check("up4 _usage_shape REFUSES a key the payload has no room for - a "
          "typo'd override is the exact defect it exists to prevent, and "
          "accepting it would put the key in one branch only",
          _up_ok is False and "phaseTitle" in _up_msg, _up_msg)
    # THE SECOND DIRECTION, and the SILENT one. A shape that refuses every
    # override is loud - nothing renders and the escape names itself. A shape
    # that quietly stops APPLYING them is not: every response ships the empty
    # defaults, the tab paints a blank Usage page, and no error is raised
    # anywhere. That is the mutation this case is here for.
    check("up5 ...and a key it DOES have is not merely allowed but APPLIED - "
          "reads vacuous beside up4, and is the case that fails if the shape "
          "ever hands back its defaults while accepting the overrides",
          M._usage_shape(rolled=True, totalRows=7)["rolled"] is True
          and M._usage_shape(rolled=True, totalRows=7)["totalRows"] == 7)
    _up_scribble = M._usage_shape()
    _up_scribble["phaseTitles"]["P9"] = "scribbled by a caller"
    _up_scribble["counts"]["phases"] = 99
    check("up6 the shape is rebuilt per call - a module-level template would "
          "hand every request the SAME empty dicts, and one response written "
          "to would arrive in the next one",
          M._usage_shape()["phaseTitles"] == {}
          and M._usage_shape()["counts"]["phases"] == 0)
    check("up7 `fields` is the one key whose VALUE legitimately differs "
          "between the branches: the ten column names beside the facts, and "
          "[] when there are no rows to read against them. Same key, so the "
          "client never reads undefined; different value, so it can still "
          "tell the two apart",
          _up_empty["fields"] == [] and _up_full["fields"] == list(M._FACT_FIELDS)
          and len(_up_full["facts"][0]) == len(M._FACT_FIELDS))
    check("up8 _ledger_counts answers with the same eight keys whether it is "
          "handed rows or nothing - which is what lets _usage_shape use the "
          "empty call as its default instead of a second literal - and 'no "
          "days at all' stays None rather than becoming a date",
          set(M._ledger_counts([])) == set(M._ledger_counts(
              [{"ts": "2026-08-01T10", "phaseId": "P1", "taskId": "P1.1",
                "model": "m", "author": "a", "sessionId": "s"}]))
          and M._ledger_counts([{"ts": "2026-08-01T10", "sessionId": "s"}])
          == {"phases": 0, "tasks": 0, "models": 0, "authors": 0,
              "sessions": 1, "days": 1, "from": "2026-08-01",
              "to": "2026-08-01"}
          and M._ledger_counts([])["from"] is None)
    _up_rows = [{"ts": "2026-08-01T10", "phaseId": "P1", "taskId": "P1.1",
                 "model": "m", "author": "a", "agentType": "g", "attr": "task",
                 "in": 5, "out": 10, "msgs": 2, "costUSD": 0.25},
                {"ts": "2026-08-01T11", "phaseId": "P1", "taskId": "P1.1",
                 "model": "m", "author": "a", "agentType": "g", "attr": "task",
                 "in": 1, "out": 1, "msgs": 1, "costUSD": 0.25}]
    _up_hourly, _up_seen = M._usage_facts(_up_rows, ("in", "out"), False)
    _up_daily, _ = M._usage_facts(_up_rows, ("in", "out"), True)
    check("up9 the fold keys hourly rows apart and rolls them together when "
          "asked: two hours of one task are TWO facts unrolled and ONE rolled, "
          "with tokens, cost and msgs summed rather than the later row winning",
          len(_up_hourly) == 2 and len(_up_daily) == 1 and _up_seen == 2
          and _up_daily[0][0] == "2026-08-01" and _up_daily[0][7] == 17
          and round(_up_daily[0][8], 6) == 0.5 and _up_daily[0][9] == 3,
          (_up_hourly, _up_daily))
    check("up10 _usage_manifest_slice resets all THREE dicts together on a "
          "shape surprise - here the first phase is readable and the second "
          "has an unhashable id, and a half-built slice would label one phase "
          "and silently drop the other with nothing saying which happened",
          M._usage_manifest_slice({"phases": [
              {"id": "P1", "title": "readable", "budgetUSD": 5},
              {"id": ["unhashable"], "title": "boom"}]}) == ({}, {}, {}))
    check("up11 _usage_derived is fail-soft per BLOCK and keyed by payload "
          "name: with the ledger module gone entirely, routing and monthly "
          "come back empty while the two area blocks still answer - one broken "
          "card costs the tab that card, never the tab",
          M._usage_derived(None, {
              "meta": {"areas": {"a": {"root": "s", "owner": " jo@x "}}},
              "phases": [{"id": "P1", "area": "a", "tasks": []}]}, [], {})
          == {"routingAdvice": [], "monthlyPlan": {},
              "phaseAreas": {"P1": ["a"]}, "areaOwners": {"a": "jo@x"}})


    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_usage.py --selftest\n")
    raise SystemExit(2)
