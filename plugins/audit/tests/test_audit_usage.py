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
        # uc (F-P-2): a row with no phase and no task is ordinary — ad-hoc
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

        # --- the rate basis, trimmed at the door (F160) ---------------------
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
        import platform as _pf
        import subprocess as _sp
        lockdir = os.path.dirname(M.acquire_lock(ledger, tmp)[0])
        lpath = os.path.join(lockdir, "usage.lock")
        check("lock: acquiring records this process's pid",
              json.load(open(lpath, encoding="utf-8")).get("pid") == os.getpid())
        got, err = M.acquire_lock(ledger, tmp)
        check("lock: a live backfill blocks the next one",
              got is None and "another usage backfill is running" in (err or ""))
        check("lock: and says on what basis", "pid %d" % os.getpid() in (err or ""))
        dead = _sp.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        with open(lpath, "w", encoding="utf-8") as fh:
            json.dump({"hostname": _pf.node(), "pid": dead.pid,
                       "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                  time.gmtime()),
                       "note": "usage backfill"}, fh)
        got, err = M.acquire_lock(ledger, tmp)
        check("lock: a crashed backfill does not block for the rest of the hour",
              got is not None and err is None)
        os.unlink(lpath)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_usage.py --selftest\n")
    raise SystemExit(2)
