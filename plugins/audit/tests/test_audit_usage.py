#!/usr/bin/env python3
"""
The cases for `audit-usage.py`, moved out of it - an entry point.

`audit-usage.py` is hyphenated, so it comes through `_loader.load_script` and the
test file substitutes underscores (`test_audit_usage.py`); see
`test_migrate_manifest.py`, the pilot that established both halves of that rule.

`M` is the module under test. `_areas`, `_cli_fmt` and `_ui_theme` are imported the
way `audit-usage.py` imports them, because several cases compare the CLI's output
against those modules' own vocabulary and a second module object would be comparing
two copies. `M.ul` and `M.mio` - the two modules `audit-usage` itself loads by path -
stay spelled off `M`, which is where they live.

A straight move otherwise: not one case here reads `__file__`, rebinds a global or
builds a path off the file it sits in, so nothing changed meaning by moving.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import re
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _areas                                      # noqa: E402  (as audit-usage imports it)
import _cli_fmt                                    # noqa: E402
import _locks                                      # noqa: E402  (the one library the backfill lock comes from)
import _ui_theme as _theme                         # noqa: E402

M = _loader.load_script("audit-usage.py", modname="audit_usage")


# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil
    import tempfile

    # "This task is an outlier" is a claim; a claim whose basis is invisible
    # cannot be checked. Both branches must name their basis or their shortfall.
    check("band note: an active band states basis AND thresholds",
          "median / p90" in M.band_note(
              {"sufficient": True, "basis": "relative", "high": 5.59,
               "outlier": 35.4})
          and "$5.59" in M.band_note(
              {"sufficient": True, "basis": "relative", "high": 5.59,
               "outlier": 35.4}))
    check("band note: an absolute basis does not claim a percentile",
          "configured thresholds" in M.band_note(
              {"sufficient": True, "basis": "absolute", "high": 15, "outlier": 50}))
    check("band note: below the gate it says what is missing and how to opt out",
          M.band_note({"sufficient": False, "gate": 5, "sample": 4})
          == "band: not calibrated yet - needs 5 completed tasks, there are 4 "
             "(or set usage.bands.highUSD / outlierUSD for a fixed budget)")

    check("advice: silence when the evidence does not support a move",
          M.routing_advice_lines([]) == [])
    _al = "\n".join(M.routing_advice_lines([{
        "risk": "low", "from": "claude-opus-5", "to": "claude-sonnet-5",
        "tasks": 7, "fromMeanAttempts": 1.0, "atFromRates": 157.75,
        "atToRates": 94.65, "saving": 63.10, "savingPct": 40.0,
        "evidenceTasks": 5, "evidenceAttempts": 1.0}]))
    check("advice: the CLI carries the same numbers and the same caveat",
          "$63.10 less (40%)" in _al and "already run 5 task(s)" in _al
          and "upper bound, not a forecast" in _al)

    check("fmt: tokens scale", (M.fmt_tokens(942) == "942"
                                and M.fmt_tokens(214_300) == "214.3K"
                                and M.fmt_tokens(14_700_000) == "14.7M"
                                and M.fmt_tokens(2_000_000_000) == "2.0B"))
    check("fmt: cost rounds to cents", M.fmt_cost(42.1789) == "$42.18")
    check("fmt: sub-cent cost does not render as $0.00",
          M.fmt_cost(0.004) == "<$0.01")
    check("fmt: cost suppressed when disabled", M.fmt_cost(9.0, show=False) == "")
    # The two `bar(fraction)` unit cases that used to sit here are gone with the
    # function. Their golden values were frozen INTO _fmt's suite before either
    # call site moved (`fmt_bar: golden bar(0.5, 18)`, the over-100% clamp, the
    # negative clamp), so the pins relocated rather than being dropped — and this
    # file now pins the thing it actually owns instead: the rendered share cell,
    # which unit-testing `bar` never exercised. See the (sb) block below.
    check("fmt: table pads to the widest cell",
          M.table([("a", "1"), ("bbbb", "22")], ["k", "v"])[1].startswith("  a   "))
    check("fmt: empty table renders nothing", M.table([], ["k"]) == [])

    now = 1_754_000_000.0        # fixed instant; no wall-clock dependence
    check("since: relative days", M.resolve_since("7d", now) == M.resolve_since("7d", now))
    check("since: 7d is 7 days before today",
          M.resolve_since("7d", now) < M.today(now))
    check("since: weeks and months resolve",
          M.resolve_since("2w", now) < M.resolve_since("7d", now)
          and M.resolve_since("3m", now) < M.resolve_since("2w", now))
    check("since: absolute date passes through",
          M.resolve_since("2026-07-01") == "2026-07-01")
    check("since: None passes through", M.resolve_since(None) is None)

    # Built for the running platform, and matched as a SUBSTRING. `abspath` on
    # Windows prepends the current drive, so the strict slug is `D:-Users-x-repo`
    # — and `x in [list]` is exact membership, not containment, so the original
    # assertion could only ever pass on POSIX. The function was right; the test
    # was the thing tied to one operating system.
    _slug_path = os.path.abspath(os.path.join(os.sep, "Users", "x", "repo"))
    _slugs = M.project_slug_candidates(_slug_path)
    check("slug: strict candidate replaces separators",
          "-Users-x-repo" in _slugs[0], repr(_slugs))
    check("slug: no path separator survives in any candidate",
          all(os.sep not in s and "/" not in s for s in _slugs), repr(_slugs))

    tmp = tempfile.mkdtemp(prefix="audit-usage-selftest-")
    try:
        ledger = os.path.join(tmp, "usage")
        rows = []
        for day, task, model, author, out_tok in (
                ("2026-08-01T09", "P1.1", "claude-opus-5", "a@x.io", 1000),
                ("2026-08-01T14", "P1.2", "claude-haiku-4-5", "b@x.io", 500),
                ("2026-08-02T14", "P2.1", "claude-opus-5", "a@x.io", 2000)):
            counts = {"in": 10, "out": out_tok, "cacheW5m": 0, "cacheW1h": 0,
                      "cacheR": 100}
            row = {"ts": day, "author": author, "sessionId": "s-" + task,
                   "agentId": None, "agentType": "audit-executor",
                   "phaseId": task.split(".")[0], "taskId": task, "attr": "task",
                   "model": model, "branch": "audit/x", "repo": "demo", "msgs": 1}
            row.update(counts)
            row["costUSD"] = round(M.ul.price(counts, model), 6)
            rows.append(row)
        M.ul.append_rows(ledger, rows)

        manifest = {"meta": {"version": 2, "usage": {"ledgerDir": "usage"}},
                    "phases": [
                        {"id": "P1", "title": "Alpha",
                         "tasks": [{"id": "P1.1", "title": "one"},
                                   {"id": "P1.2", "title": "two"}]},
                        {"id": "P2", "title": "Beta",
                         "tasks": [{"id": "P2.1", "title": "three"}]}]}

        args = M.build_parser().parse_args([])
        args.ledger_dir = ledger
        loaded = M.ul.read_ledger(ledger)
        check("render: ledger round-trips through the CLI reader",
              len(loaded) == 3)

        text = M.render(loaded, args, manifest, "all time", True)
        check("render: header names the repo", "repo demo" in text)
        check("render: phase titles come from the manifest", "Alpha" in text
              and "Beta" in text)
        check("render: task titles surface in TOP TASKS", "three" in text)
        check("render: author section appears when authors differ",
              "BY AUTHOR" in text and "a@x.io" in text)
        check("render: both models listed",
              "claude-opus-5" in text and "claude-haiku-4-5" in text)
        # uc: a row with no phase and no task is ordinary — ad-hoc
        # edits, `#no-plan`, work outside the plan — and it used to print as
        # the ledger's storage key ("--   unattributed", "--      (no task)"),
        # three spellings of one fact across three surfaces. The word now comes
        # from the shared label map, so the CLI, the report and the panel say
        # the same thing.
        _uc_rows = list(loaded) + [dict(loaded[0], phaseId=None, taskId=None,
                                        attr="unattributed",
                                        sessionId="s-adhoc")]
        _uc_text = M.render(_uc_rows, args, manifest, "all time", True)
        check("uc: spend with no phase/task is named from the shared label map, "
              "and the storage key never reaches the terminal",
              _theme.UNCATEGORIZED in _uc_text
              and "unattributed" not in _uc_text
              and "(no task)" not in _uc_text)
        _args_attr = M.build_parser().parse_args(["--by", "attr"])
        _args_attr.ledger_dir = ledger
        _uc_attr = M.render(_uc_rows, _args_attr, manifest, "all time", True)
        check("uc: ...including the attribution table itself, where the bucket "
              "IS the row - the CLI's own `--attr unattributed` selector is "
              "untouched, because a flag is typed, not read",
              _theme.UNCATEGORIZED in _uc_attr
              and "unattributed" not in _uc_attr
              and "task" in _uc_attr.lower())

        check("render: trend section present", "TREND" in text
              and "peak hour" in text)
        check("render: pure ASCII output", all(ord(c) < 128 for c in text))
        check("render: no ANSI escapes", "\033" not in text)
        check("render: no box-drawing or emoji",
              not any(0x2500 <= ord(c) <= 0x27BF or ord(c) > 0x1F000
                      for c in text))
        check("render: cost shown by default", "equiv" in text)

        # The rate basis, third surface of the gap the HTML report carried until
        # 0.22.0: a cost printed with nothing saying what priced it.
        _mp = json.loads(json.dumps(manifest))
        _mp.setdefault("meta", {}).setdefault("usage", {})["pricingAsOf"] = "2026-08-06"
        _dated = M.render(loaded, args, _mp, "all time", True)
        check("render: a declared rate date is printed beside the costs",
              "rates as of 2026-08-06" in _dated)
        check("render: with none declared it says so and names the exit, rather "
              "than printing dollars that look pinned to a table nobody named",
              "undated rates" in text and "usage.pricingAsOf" in text)
        check("render: it never falls back to the default table's date - that "
              "would manufacture a basis instead of stating one",
              "rates as of" not in text)

        # --- the rate basis, trimmed at the door -----------------------------
        # The plan schema asks only `minLength: 1`, so a string of spaces
        # VALIDATES and this line tested it for truth: "rates as of" followed by
        # nothing. `rate_basis` is the one door both readers in this file go
        # through, so the cases drive it directly AND through the render.
        def _basis(raw):
            return M.rate_basis({"pricingAsOf": raw})

        def _rendered(raw):
            _m = json.loads(json.dumps(manifest))
            _m.setdefault("meta", {}).setdefault("usage", {})["pricingAsOf"] = raw
            return M.render(loaded, args, _m, "all time", True)
        check("render: a whitespace-only rate date is NOT a declaration - it "
              "collapses to None and the line says the rates are undated, "
              "rather than trailing off after 'rates as of': %r"
              % (_basis("   "),),
              _basis("   ") is None
              and "undated rates" in _rendered("   ")
              and "rates as of" not in _rendered("   "))
        check("render: ...and a PADDED date is trimmed rather than refused - "
              "the fixture that separates trimming from merely rejecting a "
              "blank, since a version carrying the raw value through would "
              "print the padding: %r" % (_basis(" 2026-08-06 "),),
              _basis(" 2026-08-06 ") == "2026-08-06"
              and "rates as of 2026-08-06" in _rendered(" 2026-08-06 "))
        check("render: ...and a hand-edited number is None rather than a "
              "raise - a render that raises is a report that does not print: "
              "%r" % (_basis(20260806),),
              _basis(20260806) is None
              and "undated rates" in _rendered(20260806))
        # THE OTHER-DIRECTION CASE, which looks vacuous and is the only one
        # that fails if the trim becomes an unconditional None.
        check("render: ...and a declared date is untouched, so the repair "
              "cannot have been 'never report a basis'",
              _basis("2026-08-06") == "2026-08-06")
        check("render: both readers in this file go through ONE door, so the "
              "terminal line and the --json payload cannot disagree about a "
              "value's whitespace",
              M.rate_basis({}) is None and M.rate_basis(None) is None)

        no_cost = M.render(loaded, args, manifest, "all time", False)
        check("render: --no-cost drops every dollar figure", "$" not in no_cost)
        check("render: --no-cost drops the rate basis too - with no dollars on "
              "screen it dates a table nothing visible came from",
              "rates" not in no_cost and "undated" not in no_cost)

        empty = M.render([], args, manifest, "all time", True)
        check("render: empty ledger explains itself, not a traceback",
              "No usage recorded" in empty and "backfill" in empty)
        check("render: and says nothing about rates when there is no spend to "
              "price - a basis announced for a claim never made is noise",
              "rates" not in empty and "undated" not in empty)

        args_by = M.build_parser().parse_args(["--by", "model"])
        args_by.ledger_dir = ledger
        one = M.render(loaded, args_by, manifest, "all time", True)
        check("render: --by renders one focused table",
              "MODEL" in one and "BY PHASE" not in one)

        args_f = M.build_parser().parse_args(["--phase", "P1"])
        check("filter: --phase narrows rows",
              len(M.apply_filters(loaded, args_f)) == 2)
        args_f = M.build_parser().parse_args(["--author", "b@x.io"])
        check("filter: --author narrows rows",
              len(M.apply_filters(loaded, args_f)) == 1)
        args_f = M.build_parser().parse_args(["--model", "haiku"])
        check("filter: --model matches on substring",
              len(M.apply_filters(loaded, args_f)) == 1)
        args_f = M.build_parser().parse_args(["--attr", "unattributed"])
        check("filter: --attr with no matches yields nothing",
              M.apply_filters(loaded, args_f) == [])

        check("ledger: --since bounds the window",
              len(M.ul.read_ledger(ledger, since="2026-08-02")) == 1)

        # --- manifest resolution ------------------------------------------------
        # This used to resolve docs/audit/audit-plan.json and nothing else, so a
        # project keeping its manifest elsewhere loaded none and then read every
        # project value off {} - showCost included. The shipped example is exactly
        # that project.
        _mr = os.path.join(tmp, "mres")
        os.makedirs(os.path.join(_mr, ".claude"), exist_ok=True)
        os.makedirs(os.path.join(_mr, "docs", "audit"), exist_ok=True)
        _elsewhere = os.path.join(_mr, "audit-plan.json")
        for _p in (_elsewhere, os.path.join(_mr, "docs", "audit", "audit-plan.json")):
            with open(_p, "w", encoding="utf-8") as fh:
                json.dump({"meta": {}, "phases": [], "bugs": []}, fh)
        _cfgp = os.path.join(_mr, ".claude", "audit.config.json")
        _noargs = M.build_parser().parse_args([])

        with open(_cfgp, "w", encoding="utf-8") as fh:
            json.dump({"manifestPath": "audit-plan.json"}, fh)
        check("manifest: a configured manifestPath is honoured, not just the "
              "default location",
              M.resolve_manifest_path(_noargs, _mr) == os.path.normpath(_elsewhere))
        check("manifest: an explicit argument still outranks the config",
              M.resolve_manifest_path(
                  M.build_parser().parse_args(["some/other.json"]), _mr)
              == "some/other.json")

        with open(_cfgp, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        check("manifest: a malformed config falls back instead of raising - the "
              "usage view is read-only and must not die on someone else's typo",
              M.resolve_manifest_path(_noargs, _mr)
              == os.path.normpath(os.path.join(_mr, M.DEFAULT_MANIFEST_REL)))
        os.remove(_cfgp)
        check("manifest: no config at all still finds the default location",
              M.resolve_manifest_path(_noargs, _mr)
              == os.path.normpath(os.path.join(_mr, M.DEFAULT_MANIFEST_REL)))

        with open(_cfgp, "w", encoding="utf-8") as fh:
            json.dump({"manifestPath": "nowhere/absent.json"}, fh)
        check("manifest: a configured path that does not exist falls back rather "
              "than reporting a file that is not there",
              M.resolve_manifest_path(_noargs, _mr)
              == os.path.normpath(os.path.join(_mr, M.DEFAULT_MANIFEST_REL)))
        check("manifest: nothing anywhere -> None, and the caller renders without "
              "project values rather than crashing",
              M.resolve_manifest_path(_noargs, os.path.join(tmp, "empty-proj")) is None)

        # --json path
        argv = ["--ledger-dir", ledger, "--project-dir", tmp, "--json"]
        import io
        buf, real = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            code = M.main(argv)
        finally:
            sys.stdout = real
        payload = json.loads(buf.getvalue())
        check("json: exits 0", code == 0)
        check("json: totals match the ledger",
              payload["totals"]["out"] == 3500)
        check("json: every grouping present",
              all(k in payload for k in ("byPhase", "byTask", "byModel",
                                         "byAuthor", "byAgent", "byDay",
                                         "byAttribution", "heatmap")))
        check("json: heatmap is 7x24",
              len(payload["heatmap"]) == 7 and len(payload["heatmap"][0]) == 24)

        # --- month bucket (mo) ----------------------------------------------
        check("mo1 --by month is a legal choice, derived from GROUP_KEYS",
              "month" in M.ul.GROUP_KEYS
              and M.build_parser().parse_args(["--by", "month"]).by == "month")
        args_mo = M.build_parser().parse_args(["--by", "month"])
        args_mo.ledger_dir = ledger
        mo_text = M.render(loaded, args_mo, manifest, "all time", True)
        check("mo2 --by month renders one focused monthly table",
              "MONTH" in mo_text and "2026-08" in mo_text
              and "BY PHASE" not in mo_text)
        check("mo3 the json payload carries byMonth",
              payload.get("byMonth", {}).get("2026-08", {}).get("out") == 3500)

        # --- monthly overview (ma) ------------------------------------------
        check("ma1 a single-month ledger shows no MONTHLY table - one row "
              "would restate the totals line",
              "MONTHLY" not in text)
        check("ma2 the json payload carries the monthly overview even then",
              payload.get("monthly", {}).get("months") == ["2026-08"])
        _l2 = os.path.join(tmp, "usage2")
        _extra = dict(rows[0])
        _extra["ts"] = "2026-07-20T10"
        _extra["sessionId"] = "s-jul"
        M.ul.append_rows(_l2, rows + [_extra])
        _loaded2 = M.ul.read_ledger(_l2)
        _man2 = json.loads(json.dumps(manifest))
        _man2["phases"][0]["tasks"][0]["status"] = "done"
        _man2["phases"][0]["tasks"][0]["completedAt"] = "2026-08-01T10:00:00Z"
        _man2["bugs"] = [{"id": "BUG-1", "status": "open",
                          "reportedAt": "2026-07-02T10:00:00Z"}]
        _mtext = M.render(_loaded2, args, _man2, "all time", True)
        check("ma3 a two-month ledger renders the MONTHLY table with both months",
              "MONTHLY" in _mtext and "2026-07" in _mtext and "2026-08" in _mtext)
        check("ma4 plan columns ride beside the ledger columns",
              "tasks done" in _mtext and "merged" in _mtext)
        check("ma5 the plan columns say they are project-wide and do not follow "
              "the filters",
              "do not follow the filters" in _mtext)
        check("ma6 the monthly table is plain ASCII",
              all(ord(c) < 128 for c in _mtext))
        check("ma7 --no-cost drops the monthly cost column too",
              "cost" not in "\n".join(
                  ln for ln in M.render(_loaded2, args, _man2, "all time",
                                      False).splitlines()
                  if "MONTHLY" in ln))

        # --- areas (da): read-time join, --area filter, BY AREA table -------
        # Area is a property of the PLAN: the same ledger re-reads differently
        # when a phase is re-tagged, and a project that never wrote an area
        # keeps today's dashboard byte for byte.
        check("da1 a plan with no area tags renders no BY AREA table",
              "BY AREA" not in text)
        _man_a = json.loads(json.dumps(manifest))
        _man_a["phases"][0]["area"] = "backend"
        _man_a["phases"][1]["area"] = ["backend", "web"]
        _atext = M.render(loaded, args, _man_a, "all time", True)
        check("da2 tagged phases render BY AREA with one row per tag",
              "BY AREA" in _atext and "backend" in _atext and "web" in _atext)
        check("da3 the multi-tag caveat prints exactly when a phase carries "
              "more than one tag - single-tag projects stay quiet",
              "sum past the total" in _atext)
        _man_b = json.loads(json.dumps(manifest))
        _man_b["phases"][0]["area"] = "backend"
        _btext = M.render(loaded, args, _man_b, "all time", True)
        check("da4 ...and stays silent when no phase is multi-tagged",
              "BY AREA" in _btext and "sum past the total" not in _btext)
        check("da5 spend of an untagged phase lands in an 'untagged' row that "
              "sorts last - a residue, not an area",
              "untagged" in _btext
              and _btext.index("untagged") > _btext.index("backend"))
        check("da6 the BY AREA table is plain ASCII",
              all(ord(c) < 128 for c in _atext))
        _tags_a = _areas.phase_tags(_man_a)
        args_da = M.build_parser().parse_args(["--area", "backend"])
        check("da7 --area keeps exactly the rows whose phase carries the tag",
              len(M.apply_filters(loaded, args_da, _tags_a)) == 3
              and len(M.apply_filters(
                  loaded, M.build_parser().parse_args(["--area", "web"]),
                  _tags_a)) == 1
              and M.apply_filters(
                  loaded, M.build_parser().parse_args(["--area", "nope"]),
                  _tags_a) == [])
        check("da8 --area untagged selects the spend no area owns",
              len(M.apply_filters(
                  loaded, M.build_parser().parse_args(["--area", "untagged"]),
                  _areas.phase_tags(_man_b))) == 1)
        check("da9 a no-tag plan's json byArea buckets everything untagged - "
              "an honest shape, not a missing key",
              payload.get("byArea", {}).get("untagged", {}).get("out") == 3500)
        _map = os.path.join(tmp, "area-plan.json")
        with open(_map, "w", encoding="utf-8") as fh:
            json.dump(_man_a, fh)
        buf2, real2 = io.StringIO(), sys.stdout
        sys.stdout = buf2
        try:
            code2 = M.main([_map, "--ledger-dir", ledger, "--project-dir", tmp,
                          "--json"])
        finally:
            sys.stdout = real2
        payload2 = json.loads(buf2.getvalue())
        check("da10 json byArea joins through the named manifest's tags",
              code2 == 0
              and payload2.get("byArea", {}).get("backend", {}).get("out") == 3500
              and payload2.get("byArea", {}).get("web", {}).get("out") == 2000)
        buf3, real3 = io.StringIO(), sys.stdout
        sys.stdout = buf3
        try:
            code3 = M.main([_map, "--ledger-dir", ledger, "--project-dir", tmp,
                          "--json", "--area", "web"])
        finally:
            sys.stdout = real3
        check("da11 --area narrows the whole json payload, totals included",
              code3 == 0
              and json.loads(buf3.getvalue())["totals"]["out"] == 2000)

        # --- markdown format (md): --format md for markdown surfaces --------
        # The /audit:usage command echoes stdout verbatim into a markdown
        # renderer, where the ASCII layout dies twice: runs of spaces fold,
        # and consecutive lines merge into one paragraph. md mode emits pipe
        # tables and bullets instead. ascii stays the default - terminals,
        # pipes and CI keep today's bytes.
        check("md1 the default format is ascii and carries no pipe tables",
              M.build_parser().parse_args([]).format == "ascii"
              and "|" not in text)
        args_md = M.build_parser().parse_args(["--format", "md"])
        args_md.ledger_dir = ledger
        md_text = M.render(loaded, args_md, manifest, "all time", True)
        check("md2 --format md renders pipe tables with an alignment row",
              "\n| BY PHASE |" in md_text and "---:" in md_text)
        check("md3 the header block is bulleted so markdown cannot merge its "
              "lines into one paragraph",
              md_text.startswith("**USAGE**") and "\n- **Total** " in md_text)
        check("md4 md output is still pure ASCII with no ANSI escapes",
              all(ord(c) < 128 for c in md_text) and "\033" not in md_text)
        args_by_md = M.build_parser().parse_args(["--by", "model",
                                                "--format", "md"])
        args_by_md.ledger_dir = ledger
        _one_md = M.render(loaded, args_by_md, manifest, "all time", True)
        check("md5 --by renders one focused md table",
              "\n| MODEL |" in _one_md and "BY PHASE" not in _one_md)
        check("md6 the trend renders as a table under a bold heading",
              "**TREND**" in md_text and "\n| day |" in md_text)
        check("md7 --no-cost drops the cost column in md too",
              "| cost |" in md_text
              and "| cost |" not in M.render(loaded, args_md, manifest,
                                           "all time", False))
        _man_p = json.loads(json.dumps(manifest))
        _man_p["phases"][0]["title"] = "Alpha | Beta"
        check("md8 a pipe inside a cell is escaped, not a column break",
              "Alpha \\| Beta" in M.render(loaded, args_md, _man_p,
                                         "all time", True))
        check("md9 the multi-tag area caveat survives in md",
              "sum past the total" in M.render(loaded, args_md, _man_a,
                                             "all time", True))
        check("md10 an empty ledger explains itself in md as well",
              "No usage recorded" in M.render([], args_md, manifest,
                                            "all time", True))
        _amd = "\n".join(M.routing_advice_lines([{
            "risk": "low", "from": "claude-opus-5", "to": "claude-sonnet-5",
            "tasks": 7, "fromMeanAttempts": 1.0, "atFromRates": 157.75,
            "atToRates": 94.65, "saving": 63.10, "savingPct": 40.0,
            "evidenceTasks": 5, "evidenceAttempts": 1.0}], fmt="md"))
        check("md11 advice lines are bullets in md so they stay separate lines",
              "**WHAT THE EVIDENCE SUPPORTS**" in _amd and "\n- " in _amd)
        buf4, real4 = io.StringIO(), sys.stdout
        sys.stdout = buf4
        try:
            code4 = M.main([_map, "--ledger-dir", ledger, "--project-dir", tmp,
                          "--json", "--format", "md"])
        finally:
            sys.stdout = real4
        check("md12 --json is format-agnostic - the payload stays json",
              code4 == 0
              and json.loads(buf4.getvalue())["totals"]["out"] == 3500)

        # --- color (co): --color through _cli_fmt ---------------------------
        # Plain mode must stay byte-identical to the pre-color dashboard: a
        # disabled painter is the identity, and every pre-color caller (this
        # selftest included) passes no painter at all. md never colors.
        check("co1 --color defaults to auto and accepts the three modes",
              M.build_parser().parse_args([]).color == "auto"
              and M.build_parser().parse_args(["--color", "always"]).color
              == "always"
              and M.build_parser().parse_args(["--color", "never"]).color
              == "never")
        check("co2 a never/off painter renders byte-identically to the "
              "pre-color dashboard",
              M.render(loaded, args, manifest, "all time", True,
                     pt=_cli_fmt.painter("never")) == text)
        _painted = M.render(loaded, args, manifest, "all time", True,
                          pt=_cli_fmt.painter("always"))
        check("co3 a painted dashboard carries ANSI and strips back to the "
              "plain bytes exactly - painting never changes content",
              "\033[" in _painted and _cli_fmt.strip(_painted) == text)
        check("co4 painted output is still pure ASCII (ANSI escapes are "
              "ASCII, so the cp1252 leg keeps passing)",
              all(ord(c) < 128 for c in _painted))
        check("co5 --format md never colors, even with an always painter - "
              "byte-identical to the unpainted md render",
              M.render(loaded, args_md, manifest, "all time", True,
                     pt=_cli_fmt.painter("always")) == md_text)
        check("co6 the paint lands on the section headers and notes (bold "
              "BY PHASE header row, dim band note)",
              "\033[1m  BY PHASE" in _painted and "\033[2m" in _painted)

        # --- shares and bars (sb): the two table call sites, through _fmt ----
        # Both tables used to divide by `grand = tot["tokens"] or 1`. That is
        # not a guard: it does not prevent a bad answer, it manufactures one.
        # Run verbatim it renders a row of 5 out of a total of 0 as "500%", and
        # every row of a zero-total ledger as "0%" - indistinguishable from a
        # measured zero. _fmt.share_pct owns the divide now and returns None,
        # which fmt_share renders as "?".
        #
        # Every case below reads the share CELLS, not the whole document: the
        # dashboard prints "(cache hit 0%)" in its header, so `"0%" in text` is
        # true on any ledger and asserts nothing. And each collects EVERY cell
        # rather than finding one - a sentinel that leaked into half the rows
        # would pass a presence assertion.
        _shares_re = re.compile(r"\[[#.]+\]\s+(\S+)")
        _zero_counts = {"in": 0, "out": 0, "cacheW5m": 0, "cacheW1h": 0,
                        "cacheR": 0, "costUSD": 0.0}
        _zero_rows = [dict(loaded[0], sessionId="s-z1", **_zero_counts),
                      dict(loaded[2], sessionId="s-z2", **_zero_counts)]
        # `_man_a` (the da block's tagged plan), not `manifest`: BY AREA is the
        # SECOND call site and it divides by its own `grand`. Rendered against an
        # untagged plan that table never appears, and its copy of the bug would
        # sit here uncaught while this case reported green.
        _ztext = M.render(_zero_rows, args, _man_a, "all time", True)
        _zshares = _shares_re.findall(_ztext)
        check("sb1 a ledger totalling zero tokens reports EVERY share as "
              "unmeasurable, not as a measured 0% - the `or 1` guard's answer",
              "BY AREA" in _ztext and len(_zshares) >= 6
              and set(_zshares) == {"?"}, repr(_zshares))
        _real_shares = _shares_re.findall(_atext)
        check("sb2 ...and a real ledger never shows the sentinel (the "
              "second-direction case: this one goes red if the guard becomes "
              "unconditional, and passes on the pre-fix code by construction)",
              "BY AREA" in _atext and len(_real_shares) >= 6
              and "?" not in _real_shares, repr(_real_shares))
        _mixed = list(loaded) + [dict(loaded[0], sessionId="s-zerorow",
                                      phaseId="P3", taskId="P3.9",
                                      **_zero_counts)]
        _mshares = _shares_re.findall(M.render(_mixed, args, _man_a,
                                             "all time", True))
        check("sb3 a genuinely empty row inside a real total still prints 0% - "
              "absent is not unmeasurable, and the sentinel must not spread",
              "0%" in _mshares and "?" not in _mshares, repr(_mshares))
        check("sb4 the share box is the same width at every fill, so the "
              "column stays a column",
              set(len(b) for b in re.findall(r"\[[#.]+\]", text)) == {20})
        # The trend, whose `peak = max(...) or 1` was the third `or 1`. With the
        # divisor forced to 1, `n == peak` could never hold on an all-zero
        # ledger; with the real peak it holds for every day, so the marker needs
        # its own guard. Labelling every empty day "peak 0" invents a high-water
        # mark, which is the same defect as the manufactured share.
        check("sb5 a trend with nothing in it names no peak day",
              "TREND" in _ztext and "peak 0" not in _ztext
              and "peak hour" in _ztext)
        check("sb6 ...while a real ledger still names its peak day",
              "peak " in text.split("TREND")[-1])
        _tiny = [dict(loaded[0], ts="2026-08-05T09", sessionId="s-big",
                      **dict(_zero_counts, out=1_000_000)),
                 dict(loaded[0], ts="2026-08-06T09", sessionId="s-tiny",
                      **dict(_zero_counts, out=1))]
        _ttext = M.render(_tiny, args, manifest, "all time", True)
        check("sb7 a real-but-tiny day still draws a cell (bar_cells' "
              "min_fill) - a day with spend must not render as a blank row",
              "\n  08-06  #" in _ttext, _ttext.split("TREND")[-1])
        check("sb8 ...and in md too, which builds the same sparkline a second "
              "time - one adopted call site does not vouch for the other",
              "| 08-06 | 1 | # |" in M.render(_tiny, args_md, manifest,
                                            "all time", True))

        # backfill on a project with no transcripts must fail cleanly, not crash
        args_b = M.build_parser().parse_args(["--backfill"])
        args_b.transcript_dir = os.path.join(tmp, "no-such-dir")
        code, msg = M.backfill(args_b, tmp, ledger, manifest, None)
        check("backfill: missing transcripts -> exit 2 with guidance",
              code == 2 and "--transcript-dir" in msg)

        # The backfill lock. It used to keep the next run out for a full hour
        # after a crash, and the file named nobody — so "delete it if that is
        # stale" was advice the human had no way to act on.
        #
        # AND IT USED TO BE A LOCK OF ITS OWN SHAPE IN THE SHARED LIBRARY'S OWN
        # DIRECTORY: it asked whether the name was there, judged the holder, and
        # then opened the path for writing. Two backfills can pass that
        # judgement between the read and the write, and the repair that closed
        # exactly that window for every other lock this product takes never
        # reached the one taker that was not calling the library. So the fixture
        # below is a REAL repository: the claim has to land where `audit-lock.py
        # status` and `/audit:doctor` can see it, or it is coordinating with
        # nothing.
        import platform as _pf
        import subprocess as _sp
        _lk = os.path.join(tmp, "lock-repo")
        os.makedirs(_lk)
        _sp.run(["git", "init", "-q", _lk], check=True,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        _shared = _locks.lock_dir(_lk)
        lpath = os.path.join(_shared, "%s.lock" % (M.LOCK_NAME,))
        got, err = M.acquire_lock(_lk)
        check("lock: the claim is the SHARED library's, under the name it "
              "issues - a lock nothing else can be refused by is not a lock: "
              "%r" % (lpath,),
              err is None and got.get("held") is True and got.get("release")
              and os.path.isfile(lpath) and _locks.valid_name(M.LOCK_NAME))
        # READ THROUGH THE LIBRARY'S OWN READER, which answers `{}` for a claim
        # that is not there rather than raising. A bare `open` here fails by
        # exception the moment the backfill stops taking the claim - which is
        # exactly when this case is supposed to fail by NAME, and a case that
        # reports by raising takes every case after it with it.
        check("lock: acquiring records this process's pid: %r"
              % (_locks.read_lock(lpath),),
              _locks.read_lock(lpath).get("pid") == os.getpid())
        check("lock: releasing gives the claim back", M.release_lock(_lk, got)
              is None and not os.path.exists(lpath))
        # A LIVE HOLDER THAT IS NOT THIS PROCESS. The claim names a pid the OS
        # can vouch for and a session this run is not, which is the only shape
        # that can be told from re-entry - and the sentence the caller gets is
        # the library's own, so the refusal reads the same wherever it is met.
        _locks._write_lock(lpath, {"hostname": _pf.node(), "pid": os.getppid(),
                                   "sessionId": "another-backfill",
                                   "startedAt": time.strftime(
                                       "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                   "note": "usage backfill"})
        got2, err2 = M.acquire_lock(_lk)
        check("lock: a live backfill blocks the next one, in the library's own "
              "words rather than a second sentence about the same refusal: %r"
              % (err2,),
              got2 is None and "held by a live run" in (err2 or ""))
        check("lock: and points at the door for who holds it - the terminal "
              "lines naming a host stay in the terminal",
              "audit-lock.py status" in (err2 or ""))
        # THE IDENTITY IS A PROCESS AND NOT A RUN, which is the half a shared
        # library made possible to get wrong. `acquire` hands a caller back a
        # lock it judges to be its own, and a backfill that claimed the RUN's
        # session id would be handed one a second backfill in the same session
        # is holding - both rewriting the same month files, each sure it had
        # the lock. This claim carries exactly that session id.
        _sid_prev = os.environ.get("CLAUDE_CODE_SESSION_ID")
        os.environ["CLAUDE_CODE_SESSION_ID"] = "one-claude-session"
        try:
            _locks._write_lock(lpath, {"hostname": _pf.node(),
                                       "pid": os.getppid(),
                                       "sessionId": "one-claude-session",
                                       "startedAt": time.strftime(
                                           "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                       "note": "usage backfill"})
            got_sid, err_sid = M.acquire_lock(_lk)
            check("lock: a second backfill in the SAME Claude session is still "
                  "refused - the run's id is not what holds this claim, and "
                  "lending it would make the one collision this lock exists for "
                  "read as re-entry: %r" % (err_sid,),
                  got_sid is None and "held by a live run" in (err_sid or ""))
        finally:
            if _sid_prev is None:
                os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            else:
                os.environ["CLAUDE_CODE_SESSION_ID"] = _sid_prev
        dead = _sp.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        _locks._write_lock(lpath, {"hostname": _pf.node(), "pid": dead.pid,
                                   "startedAt": time.strftime(
                                       "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                   "note": "usage backfill"})
        got3, err3 = M.acquire_lock(_lk)
        check("lock: a crashed backfill does not block for the rest of the "
              "hour - the retake is the library's takeover, which removes the "
              "judged claim only while it is still that claim: %r" % (err3,),
              got3 is not None and err3 is None and got3.get("release"))
        M.release_lock(_lk, got3)
        # THE THIRD ANSWER, said rather than papered over. A project with no
        # repository has no lock scheme and never had one, so there is nothing
        # to coordinate through - and a backfill that invented a second
        # mechanism there would be the very shape this consolidation removes.
        _nogit = os.path.join(tmp, "no-git-here")
        os.makedirs(_nogit)
        got4, err4 = M.acquire_lock(_nogit)
        check("lock: a project with no lock scheme is told so and proceeds, "
              "rather than being refused or quietly guarded by something the "
              "command line cannot see: %r" % (got4,),
              err4 is None and got4.get("held") is False
              and got4.get("release") is False
              and "no lock scheme" in (got4.get("why") or ""))
        check("lock: ...and releasing that handle takes nothing, because "
              "nothing was taken", M.release_lock(_nogit, got4) is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _harness.stage(check, "bw0 the backfill-window block", _backfill_window_cases)


# --- backfill against concurrent appenders -------------------------------------
# The metering hook appends to a month file with no lock while a backfill reads
# that file and then replaces it. Every case below puts a write INSIDE that
# window - deterministically through a seam, or by real concurrent processes -
# because a backfill run on a quiet ledger is green whether or not the window
# loses rows.
_BW_MONTH = "2026-10"
_BW_SID = "S-BF"
_BW_ENTRIES = 40


def _bw_entry(sid, mid, hour):
    return {"type": "assistant", "sessionId": sid,
            "timestamp": "%s-05T%02d:00:00Z" % (_BW_MONTH, hour),
            "gitBranch": "main",
            "message": {"id": mid, "model": "claude-sonnet-5",
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0}}}


def _bw_probe(sid, probe):
    return {"ts": "%s-05T12" % _BW_MONTH, "sessionId": sid,
            "attr": "unattributed", "model": "claude-sonnet-5", "msgs": 1,
            "in": 0, "out": 1, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0,
            "probeId": probe}


def _bw_fixture(root, old_rows):
    """A project with no repository (so no lock scheme to set up), one backfill
    transcript of `_BW_ENTRIES` one-token messages, and `old_rows` ledger rows
    of sessions the backfill does not re-read."""
    import types
    project = os.path.join(root, "proj")
    tdir = os.path.join(root, "transcripts")
    ledger = os.path.join(project, ".claude", "usage")
    os.makedirs(tdir)
    os.makedirs(project)
    with open(os.path.join(tdir, _BW_SID + ".jsonl"), "w", encoding="utf-8") as fh:
        for i in range(_BW_ENTRIES):
            fh.write(json.dumps(_bw_entry(_BW_SID, "%s-m%04d" % (_BW_SID, i),
                                          10 + i % 8)) + "\n")
    M.ul.append_rows(ledger, [dict(_bw_probe("S-OLD-%d" % (i % 7), "old-%d" % i))
                              for i in range(old_rows)])
    args = types.SimpleNamespace(transcript_dir=tdir, author_mode="none")
    return project, ledger, args


def _bw_probes(ledger):
    return [r.get("probeId") for r in M.ul.read_ledger(ledger) if r.get("probeId")]


def _bw_out(ledger, sid):
    return sum(int(r.get("out") or 0) for r in M.ul.read_ledger(ledger)
               if r.get("sessionId") == sid)


def _bw_with_seam(owner, name, wrapper, fn):
    """Run `fn()` with `owner.name` replaced by `wrapper(original)`, restored in
    `finally` so a case that raises cannot leave the seam installed.

    An attribute the module does not have is installed and then removed again,
    so a case run against code without it fails on its assertion rather than
    raising here and taking every later case with it."""
    missing = not hasattr(owner, name)
    original = getattr(owner, name, None)
    setattr(owner, name, wrapper(original))
    try:
        return fn()
    finally:
        if missing:
            delattr(owner, name)
        else:
            setattr(owner, name, original)


def _bw_append_before_rewrite(ledger, sid, probe):
    """A `rewrite_month` seam: another session appends a row once the backfill
    has read the month and before its rewrite runs."""
    fired = []

    def wrapper(original):
        def rewrite(ledger_dir, month, rows, *a, **kw):
            if month == _BW_MONTH and not fired:
                fired.append(M.ul.append_rows(ledger, [_bw_probe(sid, probe)]))
            return original(ledger_dir, month, rows, *a, **kw)
        return rewrite
    return wrapper, fired


def _bw_append_across_replace(ledger, sid, probe):
    """An `os.replace` seam: a writer OPENS the month file before the replace
    and writes its row after it - the shape of a metering hook descheduled
    between its open and its write. Its row lands in the file the replace just
    retired, which a re-read of the path can never see."""
    fired = []
    target = os.path.join(ledger, "%s.jsonl" % _BW_MONTH)

    def wrapper(original):
        def replace(src, dst, *a, **kw):
            if os.path.abspath(dst) != os.path.abspath(target) or fired:
                return original(src, dst, *a, **kw)
            fh = open(dst, "a", encoding="utf-8")
            try:
                return original(src, dst, *a, **kw)
            finally:
                fh.write(json.dumps(_bw_probe(sid, probe),
                                    separators=(",", ":"), sort_keys=True) + "\n")
                fh.close()
                fired.append(1)
        return replace
    return wrapper, fired


_BW_APPENDER = r"""
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
import usage_ledger as ul
ledger, k, stop, ready, out = sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
ids, i = [], 0
while not os.path.exists(stop):
    pid = "f%d-%06d" % (k, i)
    row = {"ts": "2026-10-05T12", "sessionId": "S-FOREIGN-%d" % k,
           "attr": "unattributed", "model": "claude-sonnet-5", "msgs": 1,
           "in": 0, "out": 1, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0,
           "probeId": pid}
    if ul.append_rows(ledger, [row]) == 1:
        ids.append(pid)
        if len(ids) == 1:
            open(ready, "w").close()
    i += 1
    time.sleep(0.001)
with open(out, "w") as fh:
    json.dump(ids, fh)
"""


def _bw_foreign_trial(root, appenders, old_rows):
    """One trial of appender PROCESSES writing rows for sessions the backfill
    does not re-read, for the whole of a backfill. -> (appended, lost, code)."""
    import subprocess as _sp
    project, ledger, args = _bw_fixture(root, old_rows)
    usage_dir = os.path.dirname(os.path.abspath(M.ul.__file__))
    stop = os.path.join(root, "stop")
    procs, outs, readies = [], [], []
    for k in range(appenders):
        out = os.path.join(root, "app%d.json" % k)
        ready = os.path.join(root, "ready%d" % k)
        outs.append(out)
        readies.append(ready)
        procs.append(_sp.Popen([sys.executable, "-c", _BW_APPENDER, usage_dir,
                                ledger, str(k), stop, ready, out]))
    try:
        deadline = time.time() + 30
        while (not all(os.path.exists(r) for r in readies)
               and time.time() < deadline and all(p.poll() is None for p in procs)):
            time.sleep(0.01)
        code, _msg = M.backfill(args, project, ledger, None, None)
        time.sleep(0.2)
    finally:
        open(stop, "w").close()
        for p in procs:
            try:
                p.wait(30)
            except _sp.TimeoutExpired:
                p.kill()
    appended = []
    for out in outs:
        try:
            with open(out, "r", encoding="utf-8") as fh:
                appended += json.load(fh)
        except (OSError, ValueError):
            pass
    present = set(_bw_probes(ledger))
    return len(appended), len([x for x in appended if x not in present]), code


def _backfill_window_cases(check):
    import ast
    import inspect
    root = _harness.fixture_root("audit-usage-bw-")

    # A row another session appends after the read and before the rewrite.
    r1 = os.path.join(root, "bw1")
    os.makedirs(r1)
    project, ledger, args = _bw_fixture(r1, 20)
    wrapper, fired = _bw_append_before_rewrite(ledger, "S-OTHER", "window-row")
    code, _msg = _bw_with_seam(M.ul, "rewrite_month", wrapper,
                               lambda: M.backfill(args, project, ledger, None, None))
    check("bw1 a row another session appends between backfill's read and its "
          "rewrite is in the ledger afterwards: fired=%r probes=%r"
          % (fired, sorted(p for p in _bw_probes(ledger) if p == "window-row")),
          code == 0 and fired == [1]
          and _bw_probes(ledger).count("window-row") == 1)

    # The same row, written through a descriptor opened before the replace.
    r2 = os.path.join(root, "bw2")
    os.makedirs(r2)
    project, ledger, args = _bw_fixture(r2, 20)
    wrapper, fired = _bw_append_across_replace(ledger, "S-OTHER", "late-row")
    code, _msg = _bw_with_seam(os, "replace", wrapper,
                               lambda: M.backfill(args, project, ledger, None, None))
    check("bw2 a row written to the month file through a descriptor opened "
          "before the replace survives the replace: fired=%r count=%d"
          % (fired, _bw_probes(ledger).count("late-row")),
          code == 0 and fired == [1]
          and _bw_probes(ledger).count("late-row") == 1)

    # Concurrent appender processes for foreign sessions, over repeated trials.
    totals = {"appended": 0, "lost": 0, "codes": []}
    for t in range(3):
        rt = os.path.join(root, "bw3-%d" % t)
        os.makedirs(rt)
        # The settle is raised for this case alone, so a loaded machine
        # descheduling an appender past the production settle cannot read as
        # a lost row: this case measures the carry, bw2 is the exact proof.
        appended, lost, code = _bw_with_seam(
            M.ul, "TAIL_SETTLE_S", lambda _orig: 0.3,
            lambda: _bw_foreign_trial(rt, 3, 4000))
        totals["appended"] += appended
        totals["lost"] += lost
        totals["codes"].append(code)
    check("bw3 appenders for sessions outside the backfill set, running during "
          "a backfill, lose no row across repeated trials: %r" % (totals,),
          totals["appended"] > 0 and totals["lost"] == 0
          and totals["codes"] == [0, 0, 0])

    # ALLOW TWINS. The carry must take only what the backfill did not re-read,
    # and only what arrived after its read: the mutations these catch are a
    # carry that keeps the backfill's own sessions (double count) and a carry
    # that re-reads the old file from its start (every old row twice).
    r4 = os.path.join(root, "bw4")
    os.makedirs(r4)
    project, ledger, args = _bw_fixture(r4, 20)
    wrapper, fired = _bw_append_before_rewrite(ledger, _BW_SID, "inset-row")
    code, _msg = _bw_with_seam(M.ul, "rewrite_month", wrapper,
                               lambda: M.backfill(args, project, ledger, None, None))
    check("bw4 a row of a session the backfill re-read, appended in the window, "
          "is not counted twice: out=%d of %d, carried=%d"
          % (_bw_out(ledger, _BW_SID), _BW_ENTRIES,
             _bw_probes(ledger).count("inset-row")),
          code == 0 and fired == [1] and _bw_out(ledger, _BW_SID) == _BW_ENTRIES
          and "inset-row" not in _bw_probes(ledger))
    old = [p for p in _bw_probes(ledger) if p.startswith("old-")]
    check("bw5 rows the backfill read before its rewrite are kept exactly once: "
          "%d of 20, %d distinct" % (len(old), len(set(old))),
          len(old) == 20 and len(set(old)) == 20)

    def _snapshot(path):
        return sorted(json.dumps(r, sort_keys=True) for r in M.ul.read_ledger(path))
    before = _snapshot(ledger)
    code2, _msg = M.backfill(args, project, ledger, None, None)
    check("bw6 a second backfill is still a no-op: %d rows before, %d after"
          % (len(before), len(_snapshot(ledger))),
          code2 == 0 and _snapshot(ledger) == before)

    # The Stop hook runs this every turn, so it stays lock-free. Read the
    # function rather than trust its docstring: any name carrying "lock", or an
    # OS locking module, in its body is a lock on that path.
    tree = ast.parse(inspect.getsource(M.ul.append_rows).lstrip())
    names = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                   | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
                   | {a.name for n in ast.walk(tree)
                      if isinstance(n, (ast.Import, ast.ImportFrom))
                      for a in n.names})
    lockish = [n for n in names if "lock" in n.lower() or n in ("fcntl", "msvcrt",
                                                               "flock", "lockf")]
    check("bw7 append_rows still takes no lock: %r" % (lockish,),
          bool(names) and not lockish)

    _bw_settle_cases(check, root)
    _bw_failed_rewrite_cases(check, root)


def _bw_replaces_open_file(root):
    """Whether this platform moves a file over one that is still open - the
    mechanism the held descriptor needs, probed rather than named."""
    a, b = os.path.join(root, "probe-a"), os.path.join(root, "probe-b")
    for path in (a, b):
        with open(path, "w") as fh:
            fh.write("x")
    held = open(b, "a")
    try:
        os.replace(a, b)
        return True
    except PermissionError:
        return False
    finally:
        held.close()


def _bw_settle_run(root, name, chunks):
    """Backfill with a writer that opened the month file before the replace and
    writes `chunks[i]` into it during the settle's i-th wait. -> (code, probes)."""
    import types
    rd = os.path.join(root, name)
    os.makedirs(rd)
    project, ledger, args = _bw_fixture(rd, 20)
    target = os.path.join(ledger, "%s.jsonl" % _BW_MONTH)
    writer = []
    waits = []

    def replace_wrapper(original):
        def replace(src, dst, *a, **kw):
            if os.path.abspath(dst) == os.path.abspath(target) and not writer:
                writer.append(open(dst, "ab"))
            return original(src, dst, *a, **kw)
        return replace

    def sleep(_seconds):
        if writer and len(waits) < len(chunks):
            writer[0].write(chunks[len(waits)])
            writer[0].flush()
        waits.append(1)

    fake_time = types.SimpleNamespace(sleep=sleep)
    try:
        code, _msg = _bw_with_seam(
            M.ul, "time", lambda _orig: fake_time,
            lambda: _bw_with_seam(os, "replace", replace_wrapper,
                                  lambda: M.backfill(args, project, ledger,
                                                     None, None)))
    finally:
        for fh in writer:
            fh.close()
    return code, _bw_probes(ledger)


def _bw_line(sid, probe):
    return (json.dumps(_bw_probe(sid, probe), separators=(",", ":"),
                       sort_keys=True) + "\n").encode("utf-8")


def _bw_settle_cases(check, root):
    if not _bw_replaces_open_file(root):
        _harness.skip(check, "bw8 the settle's quiet test", "this platform "
                      "refuses to replace an open file, so no descriptor is held "
                      "across the replace and there is no settle", True)
        _harness.skip(check, "bw9 the settle's partial line", "as bw8", True)
        return
    # A row of a session the backfill re-read lands in the retired file first:
    # it is dropped, but it is progress, so the settle must keep watching for
    # the foreign row that follows it.
    code, probes = _bw_settle_run(root, "bw8", [_bw_line(_BW_SID, "dropped"),
                                                _bw_line("S-OTHER", "after")])
    check("bw8 a dropped session's row during the settle does not end it - the "
          "foreign row after it is carried: %r" % (sorted(probes)[-3:],),
          code == 0 and probes.count("after") == 1 and "dropped" not in probes)
    line = _bw_line("S-OTHER", "halved")
    # The empty middle chunk is a wait in which nothing is written: no byte
    # arrives, but a line is still waiting for its newline, so it is not quiet.
    code, probes = _bw_settle_run(root, "bw9", [line[:20], b"", line[20:]])
    check("bw9 a half-written line during the settle does not end it, even "
          "across a wait with no byte - the row is carried whole once its "
          "newline lands: %d" % probes.count("halved"),
          code == 0 and probes.count("halved") == 1)


def _bw_failed_rewrite_cases(check, root):
    rd = os.path.join(root, "bw10")
    os.makedirs(rd)
    project, ledger, args = _bw_fixture(rd, 20)
    target = os.path.join(ledger, "%s.jsonl" % _BW_MONTH)

    def refuse(original):
        def replace(src, dst, *a, **kw):
            if os.path.abspath(dst) == os.path.abspath(target):
                raise OSError("simulated: the replace was refused")
            return original(src, dst, *a, **kw)
        return replace
    code, msg = _bw_with_seam(os, "replace", refuse,
                              lambda: M.backfill(args, project, ledger, None, None))
    cursor = M.ul.cursor_path(ledger, _BW_SID)
    strays = sorted(n for n in os.listdir(ledger) if n.endswith(".tmp"))
    check("bw10 a month whose rewrite failed is named, exits non-zero, leaves "
          "its sessions' cursors unsaved and no temp file: code=%r cursor=%r "
          "strays=%r msg=%r" % (code, os.path.exists(cursor), strays, msg),
          code != 0 and _BW_MONTH in (msg or "") and "[OK]" not in (msg or "")
          and not os.path.exists(cursor) and not strays
          and _bw_out(ledger, _BW_SID) == 0)
    # ALLOW TWIN: the same fixture with nothing refused succeeds, saves the
    # cursor and says OK - the mutation it catches is a backfill that holds
    # every cursor back, or reports failure, whatever happened.
    code, msg = M.backfill(args, project, ledger, None, None)
    check("bw11 the same backfill with nothing refused exits 0, says OK and "
          "saves the cursor: code=%r" % (code,),
          code == 0 and (msg or "").startswith("[OK]")
          and os.path.exists(cursor) and _bw_out(ledger, _BW_SID) == _BW_ENTRIES)
    _bw_spanning_cases(check, root)


_BW_PRIOR = "2026-09"


def _bw_meter_pass(ledger, transcript, sid):
    """What the metering hook does on its next turn: resume from the saved
    cursor (a missing one means a first sight, read from the start), append
    the rows it found, save the cursor it reached."""
    cursor = M.ul.load_cursor(ledger, sid)
    rows, cursor = M.ul.scan_transcripts(
        transcript, sid, cursor, None,
        {"backfillOnFirstRun": True, "maxScanBytes": float("inf")})
    M.ul.append_rows(ledger, rows)
    M.ul.save_cursor(ledger, sid, cursor)


def _bw_month_out(ledger, sid, month):
    return sum(int(r.get("out") or 0) for r in M.ul.read_ledger(ledger)
               if r.get("sessionId") == sid
               and M.ul.bucket_month(r.get("ts")) == month)


def _bw_spanning_cases(check, root):
    """A session with rows in two months, where one month's rewrite fails and
    the other's lands. The rewritten month already holds every row of the
    session, so its cursor is saved: holding it back sends the next metering
    pass over the whole transcript again, and the rewritten month counts the
    session twice. The failed month misses the session's rows until the next
    --backfill, which the failure message asks for."""
    rd = os.path.join(root, "bw12")
    os.makedirs(rd)
    project, ledger, args = _bw_fixture(rd, 20)
    transcript = os.path.join(args.transcript_dir, _BW_SID + ".jsonl")
    prior = 6
    with open(transcript, "a", encoding="utf-8") as fh:
        for i in range(prior):
            entry = _bw_entry(_BW_SID, "%s-p%04d" % (_BW_SID, i), 10 + i)
            entry["timestamp"] = "%s-20T%02d:00:00Z" % (_BW_PRIOR, 10 + i)
            fh.write(json.dumps(entry) + "\n")
    target = os.path.join(ledger, "%s.jsonl" % _BW_PRIOR)

    def refuse(original):
        def replace(src, dst, *a, **kw):
            if os.path.abspath(dst) == os.path.abspath(target):
                raise OSError("simulated: the replace was refused")
            return original(src, dst, *a, **kw)
        return replace
    code, msg = _bw_with_seam(os, "replace", refuse,
                              lambda: M.backfill(args, project, ledger, None, None))
    _bw_meter_pass(ledger, transcript, _BW_SID)
    rewritten = _bw_month_out(ledger, _BW_SID, _BW_MONTH)
    check("bw12 a session spanning a month that failed to rewrite and one that "
          "was rewritten is not counted twice in the rewritten month by the "
          "next metering pass: code=%r out=%d of %d msg=%r"
          % (code, rewritten, _BW_ENTRIES, msg),
          code != 0 and _BW_PRIOR in (msg or "") and _BW_MONTH not in (msg or "")
          and rewritten == _BW_ENTRIES)
    # The failed month's half of the trade: it waits for the next backfill,
    # and that backfill makes both months whole without doubling either.
    waiting = _bw_month_out(ledger, _BW_SID, _BW_PRIOR)
    code2, _msg2 = M.backfill(args, project, ledger, None, None)
    check("bw13 ...the failed month lacks the session's rows until the next "
          "--backfill, which restores them and leaves the rewritten month "
          "single-counted: before=%d after=%d/%d code=%r"
          % (waiting, _bw_month_out(ledger, _BW_SID, _BW_PRIOR),
             _bw_month_out(ledger, _BW_SID, _BW_MONTH), code2),
          waiting == 0 and code2 == 0
          and _bw_month_out(ledger, _BW_SID, _BW_PRIOR) == prior
          and _bw_month_out(ledger, _BW_SID, _BW_MONTH) == _BW_ENTRIES)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_usage.py --selftest\n")
    raise SystemExit(2)
