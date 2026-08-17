#!/usr/bin/env python3
"""
The cases for `scripts/audit-status.py`, moved out of it - an entry point.

`audit-status.py` is hyphenated, so it comes through `_loader.load_script` and the
test file substitutes underscores; see `test_migrate_manifest.py` for both halves
of that rule. `M` is the module under test. `_manifest_io` and `_cli_fmt` are
imported here the way `audit-status.py` imports them, because `si4`/`si8` compare
against `_manifest_io`'s own objects by IDENTITY and the `col` group paints with
`_cli_fmt`'s own painter.

TWO NAMES, BECAUSE THIS SUITE OWNS A GUARD OF ITS OWN. Every case here goes
through a wrapper that keeps the id LETTER SPACE honest: two groups sharing a
token (`pp`, then `s`) once shadowed each other in this output and in every grep
of it, so `check` keys the token to the source line that issued it and fails only
when a SECOND site claims the same one. That wrapper has to stay with the cases,
so the harness's own callback is `_record(label, cond, detail)` here and the
wrapper calls it. `sys._getframe(1).f_lineno` still reads the line of whatever
called `check`, which is this file's body rather than `audit-status.py`'s - the
absolute numbers move, the equality the guard is built on does not.

`_fixture()` came with the suite: it sat under `audit-status.py`'s own
`# --- selftest ---` marker and had no caller anywhere else in the tree.

WHAT DID *NOT* HAVE TO CHANGE, CHECKED RATHER THAN ASSUMED. The AST scan for the
six shapes the guide forbids carrying literally found no `globals()`, no `vars()`,
no `__file__` and no path built off this suite's own directory. It did find three
`split(a)[1]` / `split(b)[0]` expressions - `s27`, `s32` and `s31` - and they are
NOT the shape the guide is about: they slice `render_status()`'s RENDERED TEXT,
which reads the same from any directory, and all three are `x not in <slice>` or a
`repr()` for a detail, so a marker that went missing WIDENS the region and makes
the claim harder to satisfy rather than vacuous. `_harness.between()` would raise
on `s31`'s `BUGS` marker, which a short render is entitled not to have; the naive
form is the correct one here and stays.

`audit-status.py` keeps its two `_loader` edges (`validate-manifest` through
`_load_validator`, `usage_ledger` through `usage_summary`) - both are production
call sites, so its `KNOWN_LAYER_DEBT` entry is untouched by this move.

THE LAST LINE CHANGED, AND IT IS A FIX. This suite printed `ALL PASS` / `SELFTEST
FAILED` already, so the tally reads exactly as it did.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as audit-status imports it)
import _cli_fmt                                    # noqa: E402  (as audit-status imports it)

M = _loader.load_script("audit-status.py", modname="audit_status")


# --- the fixture most cases start from ----------------------------------------
def _fixture():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P1", "title": "Done phase", "status": "done", "tasks": [
                {"id": "P1.1", "title": "t", "status": "done",
                 "files": ["src/a.ts"]},
            ]},
            {"id": "P2", "title": "Next phase", "status": "pending",
             "blockedBy": ["P1"], "tasks": [
                 {"id": "P2.1", "title": "ready", "status": "pending",
                  "dependsOn": [], "files": ["src/b.ts"]},
                 {"id": "P2.2", "title": "waits", "status": "pending",
                  "dependsOn": ["P2.1"]},
             ]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["P2.1"]},
        "bugs": [
            {"id": "BUG-1", "title": "fixed one", "status": "fixed",
             "severity": "high"},
        ],
    }


# --- cases --------------------------------------------------------------------
def _cases(_record):
    import copy

    vm = M._load_validator()

    def summarize(m):
        findings, warnings = vm.validate(m)
        return M.rollup(m, findings, warnings)

    # One id token, one check group. Two groups sharing a letter shadow each
    # other in this output and in every grep of it (the `pp` collision shipped
    # exactly that way, then `s` collided again between the render group and
    # the submodule group). A parameterized check looping over fixtures reuses
    # its id legitimately - from ONE call site - so the guard keys the token to
    # where it was issued and fails only when a SECOND site claims it.
    _check_sites = {}

    def check(name, ok, detail=""):
        token = (name.split() or [name])[0]
        site = sys._getframe(1).f_lineno
        if _check_sites.setdefault(token, site) != site:
            ok, detail = False, ("duplicate check id %r - already used at "
                                 "line %d, rename one group"
                                 % (token, _check_sites[token]))
        _record(name, ok, detail)

    # ca (F-P-4): cancelled is TERMINAL. A plan whose dropped work still gates
    # everything behind it deadlocks — nothing is ready, and no command can make
    # it ready without lying about what happened.
    _ca = copy.deepcopy(_fixture())
    _ca["phases"][0]["tasks"][0]["status"] = "cancelled"
    _ca["phases"][0]["status"] = "cancelled"
    _cas = summarize(_ca)
    check("ca1 a task waiting on CANCELLED work becomes ready, rather than "
          "waiting forever on something nobody will do",
          "P2.1" in _cas["ready"], repr(_cas["ready"]))
    check("ca2 ...and nothing lists it as still waiting",
          "P2.1" not in M.unmet_refs(_ca), repr(M.unmet_refs(_ca)))
    check("ca3 cancelled tasks are counted under their own status, never folded "
          "into done",
          _cas["tasks"]["byStatus"].get("cancelled") == 1
          and _cas["tasks"]["byStatus"].get("done", 0)
              == summarize(_fixture())["tasks"]["byStatus"].get("done", 0) - 1,
          repr(_cas["tasks"]["byStatus"]))
    check("ca4 the phase entry carries its cancelled count beside done/total, so "
          "a progress bar can say 'and two were dropped' instead of rounding up",
          _cas["phases"][0]["cancelled"] == 1
          and _cas["phases"][0]["done"] + _cas["phases"][0]["cancelled"]
              <= _cas["phases"][0]["total"], repr(_cas["phases"][0]))
    check("ca5 the text view has a marker of its own for it - [x] would say the "
          "work landed", M._marker("cancelled") == "[-]"
          and M._marker("cancelled") != M._marker("done"))

    # (r) readiness mirrors /audit's rule
    s = summarize(_fixture())
    check("r1 ready = dependency-satisfied pending tasks", s["ready"] == ["P2.1"],
          repr(s["ready"]))
    m = copy.deepcopy(_fixture())
    m["phases"][0]["status"] = "pending"
    m["phases"][0]["tasks"][0]["status"] = "pending"
    s = summarize(m)
    check("r2 phase blockedBy gates readiness",
          "P2.1" not in s["ready"] and "P1.1" in s["ready"], repr(s["ready"]))

    # (ar) area tag(s) — normalized to a list, surfaced per phase + grouped in rollup;
    # a phase may carry several cross-cutting tags (e.g. ['mobile', 'security'])
    m = copy.deepcopy(_fixture())
    m["phases"][0]["area"] = "backend"                 # single string
    m["phases"][1]["area"] = ["mobile", "security"]    # cross-cutting tags
    s = summarize(m)
    check("ar1 area normalized to a list per phase",
          s["phases"][0]["area"] == ["backend"]
          and s["phases"][1]["area"] == ["mobile", "security"])
    check("ar2 areas grouping counts phases + tasks",
          set(s["areas"].keys()) == {"backend", "mobile", "security"}
          and s["areas"]["backend"]["phases"] == 1
          and s["areas"]["backend"]["total"] == s["phases"][0]["total"], repr(s["areas"]))
    check("ar3 a multi-tag phase counts under EACH of its areas",
          s["areas"]["mobile"]["phases"] == 1 and s["areas"]["security"]["phases"] == 1
          and s["areas"]["security"]["total"] == s["phases"][1]["total"], repr(s["areas"]))
    s0 = summarize(_fixture())
    check("ar4 untagged manifest -> empty areas (back-compat)", s0["areas"] == {})
    # A repeated tag used to count its phase twice under that one tag, so a phase
    # that was 1-of-1 done read 2/2 in the per-area totals — a completion figure
    # over 100% on the one surface a monorepo reader looks at first.
    m_dup = copy.deepcopy(_fixture())
    m_dup["phases"][0]["area"] = ["backend", "backend", " backend "]
    s_dup = summarize(m_dup)
    check("ar5 a tag repeated on one phase counts once, and matches trimmed",
          s_dup["phases"][0]["area"] == ["backend"]
          and s_dup["areas"]["backend"]["phases"] == 1
          and s_dup["areas"]["backend"]["total"] == s_dup["phases"][0]["total"],
          repr(s_dup["areas"]))

    # (ut) the cross-cutting blind spot (v0.37 B3): a phase with NO area tag in
    # a project that REGISTERS areas is a phase every area default (skills,
    # reviewer, owner) silently skips. ONE aggregated advisory line in BY AREA,
    # never one per phase.
    m_ut = copy.deepcopy(_fixture())
    m_ut["meta"]["areas"] = {"backend": {"root": "src", "skills": ["conv"]}}
    m_ut["phases"][0]["area"] = "backend"          # P2 stays untagged
    _txt_ut = M.render_status(m_ut, M.rollup(m_ut, [], []))
    check("ut1 a registered-areas project with untagged phases gets ONE "
          "advisory line - area defaults do not apply there",
          _txt_ut.count("area defaults (skills, reviewer, owner) do not apply")
          == 1, _txt_ut)
    m_ufree = copy.deepcopy(_fixture())
    m_ufree["phases"][0]["area"] = "backend"       # free-text tag, no registry
    _txt_ufree = M.render_status(m_ufree, M.rollup(m_ufree, [], []))
    check("ut2 free-text tagging with NO registry stays quiet - there are no "
          "defaults to miss", "do not apply" not in _txt_ufree)
    m_uall = copy.deepcopy(m_ut)
    for _p in m_uall["phases"]:
        _p["area"] = "backend"
    _txt_uall = M.render_status(m_uall, M.rollup(m_uall, [], []))
    check("ut3 every phase tagged -> no advisory and no untagged row",
          "do not apply" not in _txt_uall and "untagged" not in _txt_uall)

    # (u) usage block — absent unless a ledger exists, so every existing consumer
    # keeps working untouched
    check("u1 no ledger -> no usage key (back-compat)",
          "usage" not in summarize(_fixture()))
    # --- (s) the human status renderer -------------------------------------------------
    _fx = _fixture()
    _sum = M.rollup(_fx, [], [])
    _txt = M.render_status(_fx, _sum)

    check("s1 render is pure ASCII (the fixture carries no non-ascii data)",
          all(ord(c) < 128 for c in _txt))
    check("s2 render carries no ANSI escapes", "\033" not in _txt)
    check("s3 render has no box-drawing or emoji",
          not any(0x2500 <= ord(c) <= 0x27BF or ord(c) > 0x1F000 for c in _txt))
    check("s4 the overall line names tasks, phases, bugs and ready",
          "tasks done" in _txt and "phases signed off" in _txt
          and "open bug(s)" in _txt and "ready now" in _txt)
    check("s5 every status marker is used for the statuses present",
          "[x] P1.1" in _txt and "[ ] P2.1" in _txt)
    check("s6 the column header appears exactly once, not per phase",
          _txt.count("waiting on") == 1, str(_txt.count("waiting on")))
    # The base fixture's P1 is `done`, so P2's gate is SATISFIED and there is
    # nothing to report — asserting otherwise tested the wrong premise. A genuinely
    # unmet gate needs an unfinished P1.
    _fx_gate = copy.deepcopy(_fx)
    _fx_gate["phases"][0]["status"] = "in_progress"
    _fx_gate["phases"][0]["tasks"][0]["status"] = "in_progress"
    _txt_g = M.render_status(_fx_gate, M.rollup(_fx_gate, [], []))
    check("s7 a blocked phase says what it waits on",
          "blocked by: P1" in _txt_g, _txt_g)
    check("s8 a task inherits its phase's gate in 'waiting on'",
          "P1 (phase)" in _txt_g)
    check("s8b a satisfied gate reports nothing rather than an empty warning",
          "blocked by:" not in _txt)
    check("s9 a task waiting on a sibling names it", "P2.1" in _txt)
    check("s10 the ready list carries a copy-pasteable run command",
          "/audit:run P2.1" in _txt)
    check("s11 no usage line when metering is absent", "usage:" not in _txt)

    # usage line: present, and honest about showCost
    _u = {"ledgerDir": "/tmp/x", "showCost": True,
          "totals": {"tokens": 1234567, "costUSD": 4.5},
          "byPhase": {"P2": {"tokens": 500, "costUSD": 1.0}}}
    _txt_u = M.render_status(_fx, M.rollup(_fx, [], [], usage=_u))
    check("s12 usage line appears when a ledger exists", "usage: 1.2M tok" in _txt_u)
    check("s13 usage line shows cost when showCost is true", "equiv" in _txt_u)
    _u2 = dict(_u, showCost=False)
    _txt_u2 = M.render_status(_fx, M.rollup(_fx, [], [], usage=_u2))
    check("s14 cost is withheld when showCost is false "
          "(naming dollars would leak what the setting hides)",
          "equiv" not in _txt_u2 and "usage:" in _txt_u2)
    check("s15 no 'this phase' clause when nothing is running",
          "this phase" not in _txt_u)
    # The rate basis. It belongs on THIS surface in particular: the budget lines
    # printed under it are what the preflight check acts on, and a number that can
    # stop a phase should say what priced it.
    check("s15a the rate basis is stated when the manifest declares one",
          "rates as of 2026-08-06" in M.render_status(
              _fx, M.rollup(_fx, [], [], usage=dict(_u, pricingAsOf="2026-08-06"))))
    check("s15b and says so when it does not, rather than printing dollars that "
          "look pinned to a table nobody named",
          "rates undated" in _txt_u and "usage.pricingAsOf" in _txt_u)
    check("s15c it never falls back to the default table's date - that would "
          "manufacture a basis instead of stating one",
          "rates as of" not in _txt_u)
    check("s15d withheld with the dollars when showCost is false",
          "rates" not in _txt_u2)
    check("s15e and silent when there is no spend to price at all",
          "rates" not in M.render_status(
              _fx, M.rollup(_fx, [], [], usage=dict(_u, totals={"tokens": 0}))))

    # a running phase gets the phase clause and the RESUMABLE line
    _fx_run = copy.deepcopy(_fx)
    _fx_run["phases"][1]["status"] = "in_progress"
    _fx_run["phases"][1]["branch"] = "audit/p2-next"
    _txt_r = M.render_status(_fx_run, M.rollup(_fx_run, [], [], usage=_u))
    check("s16 a running phase adds the 'this phase' clause",
          "this phase 500" in _txt_r)
    check("s17 an interrupted phase is flagged as resumable",
          "RESUMABLE" in _txt_r and "/audit:resume" in _txt_r)
    check("s18 the phase branch is shown", "audit/p2-next" in _txt_r)

    # invalid manifest must be stated, not implied
    _txt_bad = M.render_status(_fx, M.rollup(_fx, ["boom"], []))
    check("s19 an invalid manifest is stated in the render",
          "INVALID MANIFEST" in _txt_bad)

    # open bugs, and the ready-fix cross-link
    check("s20 a closed bug is not listed as open",
          "BUG-1" not in _txt.split("BUGS")[-1] if "BUGS" in _txt else True)
    _fx_bug = copy.deepcopy(_fx)
    _fx_bug["bugs"] = [{"id": "BUG-9", "title": "live one", "status": "open",
                        "severity": "high", "taskId": "P2.1"}]
    _txt_b = M.render_status(_fx_bug, M.rollup(_fx_bug, [], []))
    check("s21 an open bug is listed", "BUG-9" in _txt_b)
    check("s22 a bug whose fix is ready says so",
          "its fix is READY: /audit:run P2.1" in _txt_b)

    # truncation must not read as corruption
    check("s23 clipping marks elision rather than cutting mid-word",
          M._clip("Fix BUG-3: cart total off-by-one with stacked discounts", 44)
          .endswith("...")
          and not M._clip("Fix BUG-3: cart total off-by-one with stacked", 44)
          .endswith(" ..."))
    check("s24 short text is never clipped", M._clip("short", 44) == "short")

    # an empty plan must not crash or lie
    _empty = {"meta": {"version": 2}, "phases": []}
    _txt_e = M.render_status(_empty, M.rollup(_empty, [], []))
    check("s25 an empty manifest renders without raising", "AUDIT" in _txt_e)
    check("s26 an empty manifest says nothing is ready rather than showing a list",
          "nothing" in _txt_e)

    # A wide-open plan folds the ready list and states the count. Silent truncation
    # would read as "that is all of them" — the worst failure for a to-do list.
    _many = {"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "wide", "status": "pending", "tasks": [
            {"id": "P1.%d" % i, "title": "t%d" % i, "status": "pending"}
            for i in range(1, 40)]}]}
    _txt_m = M.render_status(_many, M.rollup(_many, [], []))
    check("s27 the ready list states the true total, not the shown count",
          "READY NOW  39 task(s)" in _txt_m, _txt_m.split("READY NOW")[1][:60])
    check("s28 the fold is announced with the remainder",
          "and %d more" % (39 - M.READY_LIST_MAX) in _txt_m)
    check("s29 the fold points at the command that runs the next one",
          "/audit:next" in _txt_m)
    _shown = [ln for ln in _txt_m.split("\n") if "run: /audit:run" in ln]
    check("s30 exactly READY_LIST_MAX rows are listed",
          len(_shown) == M.READY_LIST_MAX, str(len(_shown)))

    # (sp) proposals — parked phases must surface in status, not only in the file
    _fx_p = copy.deepcopy(_fx)
    _fx_p["proposals"] = [
        {"id": "PROP-1", "name": "Security hardening", "status": "proposed",
         "payload": {"phase": {"id": "P3", "title": "Security hardening",
                               "status": "pending",
                               "tasks": [{"id": "P3.1", "title": "t",
                                          "status": "pending"}]}}},
        {"id": "PROP-2", "name": "Old idea", "status": "dropped"},
    ]
    _sum_p = M.rollup(_fx_p, [], [])
    check("sp1 no proposals -> no PROPOSALS block (back-compat)",
          "PROPOSALS" not in _txt)
    check("sp4 rollup carries proposals {total, byStatus, parked}",
          _sum_p.get("proposals", {}).get("total") == 2
          and _sum_p.get("proposals", {}).get("parked") == 1
          and _sum_p.get("proposals", {}).get("byStatus", {}).get("proposed") == 1,
          repr(_sum_p.get("proposals")))
    _txt_p = M.render_status(_fx_p, _sum_p)
    check("sp2 a parked proposal renders id, reserved phase, task count and the "
          "materialize command",
          "PROP-1" in _txt_p and "P3 (1 task" in _txt_p
          and "/audit:propose materialize PROP-1" in _txt_p,
          _txt_p.split("PROPOSALS")[-1][:120] if "PROPOSALS" in _txt_p else _txt_p[-120:])
    check("sp5 materialized/dropped proposals are not listed as parked",
          "PROP-2" not in _txt_p)
    # a legacy free-form parked entry is listed but gets no materialize command
    # (there is no payload to materialize)
    _fx_leg = copy.deepcopy(_fx)
    _fx_leg["proposals"] = [{"id": "modernize-build", "name": "Modernize build",
                             "status": "proposed"}]
    _txt_leg = M.render_status(_fx_leg, M.rollup(_fx_leg, [], []))
    check("sp6 a legacy parked entry lists without a materialize command",
          "modernize-build" in _txt_leg
          and "materialize modernize-build" not in _txt_leg)
    # A status OUTSIDE the vocabulary (proposed|materialized|dropped) is the
    # truly invisible class: hand-written or older-init entries carry statuses
    # like "open", and the parked filter silently dropped them from a surface
    # whose whole job is that nothing tracked goes unseen.
    _fx_out = copy.deepcopy(_fx)
    _fx_out["proposals"] = [{"id": "modernize-build", "name": "Modernize build",
                             "status": "open"}]
    _txt_out = M.render_status(_fx_out, M.rollup(_fx_out, [], []))
    check("sp7 a proposal whose status is outside the vocabulary is surfaced "
          "as a legacy footer, not silently dropped",
          "PROPOSALS" in _txt_out
          and "+1 legacy proposal(s) (free-form) - /audit:propose list"
              in _txt_out,
          _txt_out[-200:])
    _empty_p = {"meta": {"version": 2}, "phases": [],
                "proposals": _fx_p["proposals"][:1]}
    _txt_ep = M.render_status(_empty_p, M.rollup(_empty_p, [], []))
    check("sp3 an empty plan with parked proposals points at /audit:propose",
          "parked proposal" in _txt_ep and "/audit:propose" in _txt_ep,
          _txt_ep[:200])
    _few = {"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "narrow", "status": "pending", "tasks": [
            {"id": "P1.1", "title": "t", "status": "pending"}]}]}
    # --phase scopes the listing without rescoping the totals.
    _p1 = M.render_status(_fx, _sum, only_phase="P1")
    check("s32 --phase lists only that phase",
          "P1.1" in _p1 and "P2.1" not in _p1.split("READY NOW")[0])
    check("s33 --phase says the totals stay whole-plan",
          "totals above are whole-plan" in _p1)
    check("s34 --phase keeps the whole-plan overall line",
          "1/2 tasks done" in _p1 or "tasks done" in _p1)
    check("s35 no scope note when unscoped",
          "scoped to phase" not in _txt)

    check("s31 a short list is not annotated as folded",
          "more" not in M.render_status(_few, M.rollup(_few, [], []))
          .split("READY NOW")[1].split("BUGS")[0])

    # --- (col) color: --color through _cli_fmt -----------------------------------
    # Plain mode must stay byte-identical to the pre-color render: a disabled
    # painter is the identity, and every pre-color caller (this selftest
    # included) passes no painter at all. --json and --gate output stay plain.
    check("col1 a never/off painter renders byte-identically to the "
          "pre-color render",
          M.render_status(_fx, _sum, pt=_cli_fmt.painter("never")) == _txt)
    _painted = M.render_status(_fx, _sum, pt=_cli_fmt.painter("always"))
    check("col2 a painted render carries ANSI and strips back to the plain "
          "bytes exactly - painting never changes content",
          "\033[" in _painted and _cli_fmt.strip(_painted) == _txt)
    check("col3 the paint lands on the section headers (bold AUDIT title, "
          "bold READY NOW)",
          _painted.startswith("\033[1mAUDIT")
          and "\033[1m  READY NOW" in _painted)
    check("col4 the invalid-manifest banner is painted as a finding",
          "\033[31m  INVALID MANIFEST" in M.render_status(
              _fx, M.rollup(_fx, ["boom"], []), pt=_cli_fmt.painter("always")))
    check("col5 painted output is still pure ASCII (ANSI escapes are ASCII, "
          "so the cp1252 leg keeps passing)",
          all(ord(c) < 128 for c in _painted))

    # --- (h) the words a person reads (v0.28) -----------------------------------
    # `in_progress` is how a status travels; it is not how it should ever arrive.
    # The report and the panel have humanised statuses since c3/c2 — the terminal,
    # which is the surface an actual run is watched on, still printed the machine
    # spelling in three places.
    _fx_h = copy.deepcopy(_fx)
    _fx_h["phases"][1]["status"] = "in_progress"
    _fx_h["phases"][1]["tasks"][0]["status"] = "in_progress"
    _fx_h["bugs"] = [{"id": "BUG-9", "title": "live", "status": "in_progress",
                      "severity": "high"}]
    _txt_h = M.render_status(_fx_h, M.rollup(_fx_h, [], []))
    check("h1 no machine status spelling survives anywhere in the render - "
          "the phase row, the task table, the bug list and the RESUMABLE line",
          "in_progress" not in _txt_h, _txt_h)
    check("h2 ...and the words are actually there, in each of the four places",
          "In progress" in _txt_h.split("task")[0] or "In progress" in _txt_h,
          _txt_h)
    check("h3 the phase row reads as words",
          re.search(r"P2\s+Next phase\s+In progress", _txt_h) is not None, _txt_h)
    check("h4 the RESUMABLE line reads as a sentence, not as an identifier",
          "is in progress" in _txt_h, _txt_h)
    check("h5 the bug list humanises its own status vocabulary",
          re.search(r"BUG-9\s+In progress", _txt_h) is not None, _txt_h)
    check("h6 the markers are unchanged - they are the legend commands/status.md "
          "documents, and they key off the machine value",
          "[~] P2.1" in _txt_h and "[x] P1.1" in _txt_h)

    # --- (e) area + effective reviewer (v0.28) ----------------------------------
    _fx_a = copy.deepcopy(_fx)
    _fx_a["meta"]["reviewSkill"] = "house-review"
    _fx_a["meta"]["areas"] = {"api": {"root": "src", "reviewSkill": "backend-review"},
                              "web": {"root": "web"}}
    _fx_a["phases"][0]["area"] = ["api", "web"]
    _fx_a["phases"][1]["area"] = "web"
    _txt_a = M.render_status(_fx_a, M.rollup(_fx_a, [], []))
    check("e1 a phase prints its area tags, which the terminal never showed at all",
          "area: api, web" in _txt_a, _txt_a)
    check("e2 the effective reviewer is resolved, not left to the reader",
          "review: backend-review (area api)" in _txt_a, _txt_a)
    check("e3 a phase whose areas answer nothing falls through to meta, and says so",
          "review: house-review (meta)" in _txt_a, _txt_a)
    _fx_a2 = copy.deepcopy(_fx_a)
    _fx_a2["phases"][0]["reviewSkill"] = "phase-review"
    check("e4 a phase override is named as the phase's own",
          "review: phase-review (phase)" in
          M.render_status(_fx_a2, M.rollup(_fx_a2, [], [])))
    check("e5 an ordinary single-app repo pays nothing for this: no tags and no "
          "reviewer means no line", "area:" not in _txt and "review:" not in _txt)
    _fx_a3 = copy.deepcopy(_fx)
    _fx_a3["phases"][0]["area"] = "solo"
    _txt_a3 = M.render_status(_fx_a3, M.rollup(_fx_a3, [], []))
    check("e6 tags print without a registry - registration is optional",
          "area: solo" in _txt_a3 and "review:" not in _txt_a3, _txt_a3)
    check("e7 the scope line stays pure ASCII like the rest of the render",
          all(ord(c) < 128 for c in _txt_a))

    # --- (ba) BY AREA block (D2) ------------------------------------------------
    # The per-area rollup has been computed and shipped in --json since the tags
    # existed; the terminal never printed it. These pin the printed block to the
    # SAME rollup, never a re-derivation.
    check("ba1 no area tags -> no BY AREA block (back-compat)",
          "BY AREA" not in _txt)
    _fx_ba = copy.deepcopy(_fx)
    _fx_ba["phases"][0]["area"] = "backend"
    _fx_ba["phases"][1]["area"] = ["backend"]
    _txt_ba = M.render_status(_fx_ba, M.rollup(_fx_ba, [], []))
    check("ba2 a tagged plan renders per-tag phases, tasks and a bar",
          "BY AREA" in _txt_ba
          and re.search(r"backend\s+2 phase\(s\)\s+\[[#.]+\] 1/3 tasks",
                        _txt_ba) is not None,
          _txt_ba.split("BY AREA")[-1][:160] if "BY AREA" in _txt_ba
          else _txt_ba[-160:])
    check("ba3 the header counts tags and tagged phases",
          "BY AREA  1 tag(s) - 2 of 2 phase(s) tagged" in _txt_ba, _txt_ba)
    check("ba4 a fully tagged single-tag plan gets no untagged footer and no "
          "caveat - nothing to warn about",
          "untagged" not in _txt_ba and "counts under each" not in _txt_ba,
          _txt_ba)
    _fx_bm = copy.deepcopy(_fx)
    _fx_bm["phases"][0]["area"] = ["mobile", "security"]   # P2 stays untagged
    _txt_bm = M.render_status(_fx_bm, M.rollup(_fx_bm, [], []))
    check("ba5 a multi-tag phase shows the same figures under EACH of its tags",
          re.search(r"mobile\s+1 phase\(s\)\s+\[[#.]+\] 1/1 tasks",
                    _txt_bm) is not None
          and re.search(r"security\s+1 phase\(s\)\s+\[[#.]+\] 1/1 tasks",
                        _txt_bm) is not None, _txt_bm)
    check("ba6 untagged phases get a footer row with the same figures",
          re.search(r"untagged\s+1 phase\(s\)\s+\[[#.]+\] 0/2 tasks",
                    _txt_bm) is not None, _txt_bm)
    check("ba7 the multi-tag caveat is stated - per-area sums can pass the total",
          "counts under each" in _txt_bm
          and "exceed the plan total" in _txt_bm, _txt_bm)
    check("ba8 the block stays pure ASCII like the rest of the render",
          all(ord(c) < 128 for c in _txt_bm))
    check("ba9 a fully done area draws a full bar - the same bar helper as the "
          "phase rows", "[############] 1/1 tasks" in _txt_bm, _txt_bm)
    # ba10+ (v0.34 D3): the advisory owner reaches the two places this command
    # answers from - the rollup (--json) and the BY AREA rows - from the SAME
    # registry read, so the terminal and the machine cannot disagree about who
    # to coordinate with.
    _fx_bo = copy.deepcopy(_fx)
    _fx_bo["phases"][0]["area"] = "backend"
    _fx_bo["phases"][1]["area"] = "ops"
    _fx_bo["meta"]["areas"] = {"backend": {"root": "src", "owner": "jane@x.com"},
                               "ops": {"root": "infra"}}
    _s_bo = M.rollup(_fx_bo, [], [])
    _txt_bo = M.render_status(_fx_bo, _s_bo)
    check("ba10 the rollup carries the registry owner per area, and only for "
          "areas that DECLARE one - no key means no claim",
          _s_bo["areas"]["backend"].get("owner") == "jane@x.com"
          and "owner" not in _s_bo["areas"]["ops"], repr(_s_bo["areas"]))
    check("ba11 the BY AREA row suffixes the owner after the figures, and an "
          "ownerless area gets no suffix",
          re.search(r"backend\s+1 phase\(s\)\s+\[[#.]+\] \d/\d tasks "
                    r"- jane@x\.com", _txt_bo) is not None
          and re.search(r"ops\s+1 phase\(s\)\s+\[[#.]+\] \d/\d tasks -",
                        _txt_bo) is None, _txt_bo)
    _fx_bn = copy.deepcopy(_fx_bo)
    _fx_bn["meta"]["areas"]["backend"]["owner"] = None
    _s_bn = M.rollup(_fx_bn, [], [])
    check("ba12 an explicit null owner is 'nobody' - carried as null in the "
          "rollup, no suffix in the render",
          "owner" in _s_bn["areas"]["backend"]
          and _s_bn["areas"]["backend"]["owner"] is None
          and " tasks - " not in M.render_status(_fx_bn, _s_bn),
          repr(_s_bn["areas"]))
    check("ba13 the owner suffix stays pure ASCII like the rest of the render",
          all(ord(c) < 128 for c in _txt_bo))

    # --- (b) budget as a gate --------------------------------------------------
    def _with_budgets(*phase_rows):
        """A summary carrying only the budget block the gate reads."""
        return {"valid": True, "findings": 0, "warnings": 0, "phases": [],
                "tasks": {"total": 0, "byStatus": {}},
                "bugs": {"total": 0, "byStatus": {}, "open": 0,
                         "openHighSeverity": 0},
                "ready": [],
                "usage": {"showCost": True, "totals": {"tokens": 1, "costUSD": 1.0},
                          "budgets": {"phases": list(phase_rows)}}}

    _over = {"id": "P2", "title": "t", "budget": 25.0, "spent": 32.5,
             "pct": 130.0, "over": True}
    _warn = {"id": "P1", "title": "t", "budget": 40.0, "spent": 34.0,
             "pct": 85.0, "over": False}
    _fine = {"id": "P3", "title": "t", "budget": 40.0, "spent": 4.0,
             "pct": 10.0, "over": False}
    _none = {"id": "P4", "title": "t", "budget": None, "spent": 9.0,
             "pct": None, "over": False}

    check("b1 over-budget trips at 100%+",
          M.evaluate_gate(_with_budgets(_over), ["over-budget"]) == ["over-budget"])
    check("b2 over-budget does NOT trip at 85%",
          M.evaluate_gate(_with_budgets(_warn), ["over-budget"]) == [])
    check("b3 budget-80 trips at 85%",
          M.evaluate_gate(_with_budgets(_warn), ["budget-80"]) == ["budget-80"])
    check("b4 budget-80 does not trip at 10%",
          M.evaluate_gate(_with_budgets(_fine), ["budget-80"]) == [])
    check("b5 a phase with no budget never trips either condition",
          M.evaluate_gate(_with_budgets(_none), ["over-budget", "budget-80"]) == [])
    check("b6 no usage block at all trips nothing (a repo without metering)",
          M.evaluate_gate(M.rollup(_fixture(), [], []),
                        ["over-budget", "budget-80"]) == [])
    check("b7 neither budget condition is in the default gate "
          "(spend is a signal, not a defect someone else's merge fails on)",
          "over-budget" not in M.DEFAULT_GATE and "budget-80" not in M.DEFAULT_GATE)
    check("b8 both are accepted by --fail-on",
          "over-budget" in M.CONDITIONS and "budget-80" in M.CONDITIONS)

    check("b9 the gate detail names the phase and both numbers, not just a count",
          "P2" in M._budget_detail(_with_budgets(_over), 100.0)
          and "130%" in M._budget_detail(_with_budgets(_over), 100.0)
          and "$25.00" in M._budget_detail(_with_budgets(_over), 100.0))
    check("b10 the detail folds beyond three phases",
          "+1 more" in M._budget_detail(
              _with_budgets(dict(_over, id="A"), dict(_over, id="B"),
                            dict(_over, id="C"), dict(_over, id="D")), 100.0))
    check("b11 breaches are ordered worst-first",
          M._budget_detail(_with_budgets(_warn, _over), 80.0).startswith("P2"))

    # the rendered budget lines
    _bl = M.render_status({"meta": {}, "phases": []}, _with_budgets(_over, _warn, _none))
    check("b12 an over-budget phase is flagged OVER", "OVER" in _bl)
    check("b13 a phase past the warn threshold is flagged WARN", "WARN" in _bl)
    check("b14 an unbudgeted phase is footnoted, not drawn at 0%",
          "declare none" in _bl and "not phases at zero" in _bl)
    check("b15 the overrun percentage is shown uncapped",
          "130%" in _bl)
    _bl_nb = M.render_status({"meta": {}, "phases": []}, _with_budgets(_none))
    check("b16 nothing is rendered when no phase declares a budget",
          "budget" not in _bl_nb)
    _sum_nc = _with_budgets(_over)
    _sum_nc["usage"]["showCost"] = False
    check("b17 budget lines are withheld when showCost is false",
          "budget" not in M.render_status({"meta": {}, "phases": []}, _sum_nc))

    # --- (zb) the four bars, at the edges the old divides guarded by hand -------
    # All four are `_fmt.fmt_bar(part, whole, width)` now; this file no longer
    # runtime-loads audit-usage.py to borrow a `bar(fraction)` that made each
    # caller do its own divide. fmt_bar draws an EMPTY BOX when `whole` is 0,
    # deliberately not the "?" fmt_share returns: every bar here prints its own
    # `done/total` right beside it, so the denominator contradicts an empty bar.
    # A share string travels alone and has nothing to contradict it.
    _zb_empty = {"meta": {"version": 2}, "phases": []}
    _zb_txt = M.render_status(_zb_empty, M.rollup(_zb_empty, [], []))
    check("zb1 a plan with zero tasks draws an empty box beside its own 0/0 - "
          "not a full bar, not a traceback",
          "[" + "." * 18 + "]  0/0 tasks done" in _zb_txt, _zb_txt[:200])
    _zb_ph = {"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "no tasks at all", "status": "pending",
         "area": "backend", "tasks": []}]}
    _zb_pt = M.render_status(_zb_ph, M.rollup(_zb_ph, [], []))
    # Anchored on the PHASE HEAD line, not on the document: the BY AREA row two
    # blocks down prints an identical `[............] 0/0`, so a bare `in _zb_pt`
    # passes on the area row alone and says nothing about the phase bar.
    check("zb2 a phase carrying no tasks draws an empty 12-cell box beside 0/0",
          re.search(r"\n  P1\s+no tasks at all\s+\S+\s+\[\.{12}\] 0/0",
                    _zb_pt) is not None, _zb_pt)
    check("zb3 ...and its BY AREA row, which divides by the same zero, does too",
          re.search(r"backend\s+1 phase\(s\)\s+\[\.{12}\] 0/0 tasks",
                    _zb_pt) is not None,
          _zb_pt.split("BY AREA")[-1][:160] if "BY AREA" in _zb_pt else _zb_pt)
    # The budget bar's whole is the literal 100 (a percentage IS a hundred-cell
    # bar), so it can never divide by zero — its edge is the other one. Count the
    # cells rather than asserting a substring: an UNCLAMPED bar still contains a
    # full box, it just runs past the bracket, which is what fmt_bar's clamp is
    # for and what `bar(pct / 100.0, 12)` used to do by clamping the fraction.
    _zb_line = [ln for ln in _bl.splitlines() if ln.startswith("  budget P2")]
    _zb_box = re.search(r"\[([#.]*)\]", _zb_line[0]) if _zb_line else None
    check("zb4 a 130%-of-budget phase fills its 12-cell box exactly and no "
          "further, while the percentage itself stays uncapped",
          _zb_box is not None and _zb_box.group(1) == "#" * 12
          and "130%" in _zb_line[0], repr(_zb_line))
    _zb_partial = [re.search(r"\[([#.]*)\]", ln).group(1)
                   for ln in _bl.splitlines() if ln.startswith("  budget P1")]
    check("zb5 ...and the 85% phase beside it draws a PARTIAL box, so zb4 is "
          "not passing on a bar that is simply always full",
          _zb_partial == ["#" * 10 + "." * 2], repr(_zb_partial))

    check("u2 rollup(usage=None) omits the key",
          "usage" not in M.rollup(_fixture(), [], [], usage=None))
    fake_usage = {"ledgerDir": "/tmp/x", "totals": {"tokens": 10, "costUSD": 1.0}}
    su = M.rollup(_fixture(), [], [], usage=fake_usage)
    check("u3 rollup passes a supplied usage block straight through",
          su["usage"] == fake_usage)
    check("u4 usage never perturbs the rest of the rollup",
          {k: v for k, v in su.items() if k != "usage"} == summarize(_fixture()))
    import tempfile as _tf
    _empty = _tf.mkdtemp(prefix="audit-status-usage-")
    try:
        check("u5 usage_summary tolerates a missing ledger dir",
              M.usage_summary({}, os.path.join(_empty, "a", "b", "m.json")) is None)
        os.makedirs(os.path.join(_empty, ".claude", "usage"), exist_ok=True)
        check("u6 usage_summary tolerates an empty ledger dir",
              M.usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                            project_dir=_empty) is None)
        with open(os.path.join(_empty, ".claude", "usage", "2026-08.jsonl"),
                  "w", encoding="utf-8") as _fh:
            _fh.write(json.dumps({
                "ts": "2026-08-06T07", "sessionId": "s1", "phaseId": "P1",
                "taskId": "P1.1", "attr": "task", "model": "claude-opus-5",
                "author": "a@b.c", "msgs": 1, "in": 10, "out": 20,
                "cacheW5m": 0, "cacheW1h": 0, "cacheR": 5, "costUSD": 0.5}) + "\n")
        u = M.usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                          project_dir=_empty)
        check("u7 usage_summary reads a real ledger",
              u and u["totals"]["tokens"] == 35 and u["totals"]["msgs"] == 1)
        check("u8 usage_summary groups by phase, model and author",
              "P1" in u["byPhase"] and "claude-opus-5" in u["byModel"]
              and "a@b.c" in u["byAuthor"])
        with open(os.path.join(_empty, ".claude", "usage", "2026-08.jsonl"),
                  "a", encoding="utf-8") as _fh:
            _fh.write("{ torn\n")
        check("u9 usage_summary survives a torn ledger line",
              M.usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                            project_dir=_empty)["totals"]["tokens"] == 35)
    finally:
        import shutil as _sh
        _sh.rmtree(_empty, ignore_errors=True)

    # (g) gate conditions
    s = summarize(_fixture())
    check("g1 clean manifest passes default gate",
          M.evaluate_gate(s, M.DEFAULT_GATE) == [])
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "open",
                      "severity": "high"})
    s = summarize(m)
    check("g2 open high-severity bug trips", "open-high-bugs" in
          M.evaluate_gate(s, M.DEFAULT_GATE))
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "triaged",
                      "severity": "low"})
    s = summarize(m)
    check("g3 low-sev open bug passes default but trips open-bugs",
          M.evaluate_gate(s, M.DEFAULT_GATE) == []
          and "open-bugs" in M.evaluate_gate(s, ("open-bugs",)))

    # (d) derived bug status — a bug materialized into a DONE task reads as fixed
    #     even though bugs[].status is still 'open' (the orchestrator never writes
    #     bugs[] during a run, so the index stays untouched for parallel phases).
    dm = {"meta": {"version": 2},
          "phases": [{"id": "P0", "title": "P", "status": "in_progress", "tasks": [
              {"id": "P0.1", "title": "fix", "status": "done", "bugId": "BUG-1"}]}],
          "bugs": [{"id": "BUG-1", "title": "b", "status": "open", "severity": "high",
                    "taskId": "P0.1"}]}
    s = summarize(dm)
    check("d1 bug on a done task derives fixed (index untouched)",
          s["bugs"]["byStatus"].get("fixed", 0) == 1 and s["bugs"]["open"] == 0
          and s["bugs"]["openHighSeverity"] == 0
          and M.evaluate_gate(s, ("open-high-bugs", "open-bugs")) == [], repr(s["bugs"]))
    dm2 = copy.deepcopy(dm)
    dm2["phases"][0]["tasks"][0]["status"] = "in_progress"
    s2 = summarize(dm2)
    check("d2 bug on a not-done task stays open",
          s2["bugs"]["open"] == 1 and s2["bugs"]["byStatus"].get("open", 0) == 1,
          repr(s2["bugs"]))
    m = copy.deepcopy(_fixture())
    m["phases"][1]["tasks"][0]["status"] = "blocked"
    s = summarize(m)
    check("g4 blocked task trips", "blocked-tasks" in
          M.evaluate_gate(s, M.DEFAULT_GATE))
    m = copy.deepcopy(_fixture())
    m["phases"][1]["tasks"][0]["status"] = "doing"  # invalid enum
    s = summarize(m)
    check("g5 validator findings trip invalid", "invalid" in
          M.evaluate_gate(s, M.DEFAULT_GATE) and s["valid"] is False)
    m = copy.deepcopy(_fixture())
    m["phases"][1]["status"] = "in_progress"
    s = summarize(m)
    check("g6 in-progress trips only when asked",
          M.evaluate_gate(s, M.DEFAULT_GATE) == []
          and "in-progress" in M.evaluate_gate(s, ("in-progress",)))

    # (g7) open-high-bugs catches high-OR-WORSE severities, not only "high"
    for sev in ("critical", "Blocker", "sev1", "P0", "URGENT", "sev-1"):
        m = copy.deepcopy(_fixture())
        m["bugs"].append({"id": "BUG-9", "title": "bad", "status": "open",
                          "severity": sev})
        s = summarize(m)
        check("g7 open %r bug trips open-high-bugs" % sev,
              "open-high-bugs" in M.evaluate_gate(s, M.DEFAULT_GATE))
    # a genuinely low severity must still NOT trip it (no false positive)
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-9", "title": "minor", "status": "open",
                      "severity": "low"})
    s = summarize(m)
    check("g8 open low-severity bug does NOT trip open-high-bugs",
          "open-high-bugs" not in M.evaluate_gate(s, M.DEFAULT_GATE))

    # (nd) a non-object manifest root must never crash the rollup path
    check("nd1 rollup on list root -> empty, no crash",
          M.rollup([], [], [])["tasks"]["total"] == 0)
    check("nd2 ready_tasks on None root -> [], no crash", M.ready_tasks(None) == [])
    check("nd3 submodule_conflicts on scalar root -> [], no crash",
          M.submodule_conflicts("nope", ["vendor/x"]) == [])

    # (j) --json output round-trips with the expected fields
    blob = json.loads(json.dumps(summarize(_fixture())))
    check("j1 rollup fields present",
          blob["tasks"]["total"] == 3 and blob["bugs"]["total"] == 1
          and blob["phases"][0]["done"] == 1 and blob["valid"] is True)

    # (sm) submodule conflict detection (renamed from s1-s5, which collided
    # with the render group's s1-s5 above - the guard in check() now trips
    # on any repeat)
    check("sm1 parse_gitmodules extracts paths", M.parse_gitmodules(
        '[submodule "vendor/child"]\n\tpath = vendor/child\n\turl = ../child\n'
        '[submodule "libs/x"]\n  path = libs/x\n  url = ../x\n')
        == ["vendor/child", "libs/x"])
    subm = {"meta": {"version": 2}, "phases": [{"id": "P0", "title": "p",
        "status": "pending", "tasks": [
            {"id": "P0.1", "title": "in submodule", "status": "pending",
             "files": ["vendor/child/src/foo.ts"]},
            {"id": "P0.2", "title": "boundary — NOT in submodule", "status": "pending",
             "files": ["vendor/child-other/x.ts"]},
            {"id": "P0.3", "title": "outside", "status": "pending",
             "files": ["src/app.ts"]},
        ]}]}
    conf = M.submodule_conflicts(subm, ["vendor/child"])
    check("sm2 file inside submodule flagged", conf == [("P0.1", "vendor/child/src/foo.ts", "vendor/child")],
          repr(conf))
    check("sm3 path-boundary: child-other NOT flagged",
          all(c[0] != "P0.2" for c in conf))
    # git_root prefix stripping: files are project-relative, submodules git-root-relative
    subm_gr = {"meta": {"version": 2}, "phases": [{"id": "P0", "title": "p",
        "status": "pending", "tasks": [{"id": "P0.1", "title": "t", "status": "pending",
        "files": ["test/vendor/child/src/foo.ts", "test/src/app.ts"]}]}]}
    conf_gr = M.submodule_conflicts(subm_gr, ["vendor/child"], git_root="test")
    check("sm4 gitRoot prefix stripped before match",
          [c[0] for c in conf_gr] == ["P0.1"] and conf_gr[0][1].startswith("test/vendor"))
    check("sm5 :line suffix tolerated", M.submodule_conflicts(
        {"meta": {}, "phases": [{"id": "P", "title": "p", "status": "pending",
         "tasks": [{"id": "P.1", "title": "t", "status": "pending",
                    "files": ["vendor/child/a.ts:10-20"]}]}]}, ["vendor/child"]) != [])
    # sm6: this walk is `_mio.iter_tasks` now, so the skip of a non-dict phase and
    # a non-dict task is inherited rather than spelled here. Both malformed shapes
    # sit BEFORE the good task on purpose: a version that raised on either would
    # never reach the row this asserts, so the case separates "skipped" from
    # "happened to come last".
    check("sm6 a non-dict phase and a non-dict task are skipped, and the real "
          "conflict behind them is still reported",
          M.submodule_conflicts(
              {"meta": {}, "phases": [
                  "not-a-phase",
                  {"id": "P", "title": "p", "status": "pending", "tasks": [
                      "not-a-task",
                      {"id": "P.1", "title": "t", "status": "pending",
                       "files": ["vendor/child/a.ts"]}]}]},
              ["vendor/child"]) == [("P.1", "vendor/child/a.ts", "vendor/child")])

    # (si) `_status_index` — the one id space readiness resolves through, and the
    # reason it is NOT driven by `_mio.iter_tasks`.
    _si_m = {"meta": {}, "phases": [
        # A phase with NO tasks at all. `iter_tasks` yields nothing for it, so an
        # index built from `iter_tasks` alone would not know this phase exists.
        {"id": "P0", "title": "groundwork", "status": "done"},
        {"id": "P1", "title": "next", "status": "pending", "tasks": [
            {"id": "P1.1", "title": "t", "status": "pending", "blockedBy": ["P0"]}]},
    ]}
    check("si1 the index carries a phase that has no tasks of its own",
          M._status_index(_si_m).get("P0") == "done")
    # si2 is si1's consequence, and it is the one that separates the two
    # implementations by VALUE: the blocking phase is DONE, so a missing entry
    # reads `None`, `None not in TERMINAL`, and the task silently stops being
    # ready. A `pending` blocker would leave both versions saying "not ready".
    check("si2 a task blocked by a task-less DONE phase is ready",
          M.ready_tasks(_si_m) == ["P1.1"])
    check("si3 ...and unmet_refs agrees there is nothing left to wait on",
          "P1.1" not in M.unmet_refs(_si_m), repr(M.unmet_refs(_si_m)))
    # si4: ONE implementation of the bug<->task rule, not a copy that agrees
    # today. `_report_html` reaches the same object from layer 2; this pins that
    # layer 7 did not quietly grow its own again.
    check("si4 effective_bug_status IS _manifest_io's, not a second copy",
          M.effective_bug_status is _mio.effective_bug_status)
    # si5-si7: this command RENDERS a manifest the validator has already faulted,
    # so blockedBy holds whatever the file holds. Each of these three shapes used
    # to end the whole run: a non-hashable ref died inside `status.get` itself,
    # and a hashable non-string survived the lookup only to die in the `", ".join`
    # that builds the column. Driven through render_status, not through the
    # helper, because the join is where it actually died.
    # The non-hashable ref is FIRST, and it stays first — but the reason has
    # CHANGED, and the old reason is worth recording because it is the kind that
    # rots. `ready_tasks.satisfied()` used to be `all(status.get(r) in TERMINAL
    # for r in refs)`, and `all()` short-circuits: with the non-hashable entry
    # LAST it stopped at the `None` and never reached it, so the pre-fix code
    # neither crashed nor changed its answer and si7 passed while asserting
    # nothing. That was found by reverting `satisfied()` and watching the suite
    # stay green. There is no `all()` on that path any more — it is
    # `not _mio.unsatisfied(refs, status)`, which visits every ref — so today
    # BOTH orderings discriminate. First is kept as the strictly harder input,
    # and against the day someone reintroduces a short-circuiting form; a reader
    # looking for the `all()` this used to name would not find it and would
    # reasonably conclude the ordering no longer matters.
    _bad_ref_m = {"meta": {"version": 2}, "phases": [{
        "id": "P1", "title": "p", "status": "in_progress",
        "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                   "blockedBy": [[1, 2], None, 7]}]}]}
    try:
        _bad_out = M.render_status(_bad_ref_m, M.rollup(_bad_ref_m, [], []))
    except Exception as _exc:
        _bad_out = "RAISED %s: %s" % (type(_exc).__name__, _exc)
    check("si5 a malformed blockedBy ref does not take the command down: %r"
          % (_bad_out[:60],),
          not _bad_out.startswith("RAISED"))
    check("si6 ...and each malformed ref is SHOWN, so the reader learns WHICH "
          "entry the validator is complaining about",
          "None" in _bad_out and "7" in _bad_out and "[1, 2]" in _bad_out)
    try:
        _bad_ready = M.ready_tasks(_bad_ref_m)
    except Exception as _exc:
        _bad_ready = "RAISED %s: %s" % (type(_exc).__name__, _exc)
    check("si7 ...and READINESS survives it too and still calls the task not "
          "ready - a separate code path from the column above, with its own copy "
          "of the same lookup: %r" % (_bad_ready,),
          isinstance(_bad_ready, list) and "P1.1" not in _bad_ready)
    check("si8 readiness and the unmet column come from _manifest_io, so the "
          "terminal-state rule cannot drift back apart",
          _mio.unsatisfied(["X"], {"X": "cancelled"}) == []
          and M.unmet_refs({"meta": {}, "phases": [{
              "id": "P1", "status": "in_progress", "tasks": [
                  {"id": "P1.1", "status": "cancelled"},
                  {"id": "P1.2", "status": "pending",
                   "blockedBy": ["P1.1"]}]}]}).get("P1.2") is None)

    # (c) CLI: exit codes 0 / 1 / 2
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_fixture(), fh)
    check("c1 CLI gate passes clean manifest (exit 0)",
          M.main([path, "--gate"]) == 0)
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "open",
                      "severity": "high"})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(m, fh)
    check("c2 CLI gate fails on open high bug (exit 1)",
          M.main([path, "--gate"]) == 1)
    check("c3 CLI usage error (exit 2)", M.main([]) == 2)
    check("c4 CLI unknown condition (exit 2)",
          M.main([path, "--gate", "--fail-on", "frobnicate"]) == 2)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    check("c5 CLI unreadable manifest (exit 2)", M.main([path, "--gate"]) == 2)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(["not", "an", "object"], fh)
    check("c5b CLI non-object JSON root (exit 2)", M.main([path, "--gate"]) == 2)
    os.unlink(path)

    # (cs) CLI --submodules mode
    fd, mpath = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(subm, fh)  # has P0.1 inside vendor/child
    fd, gm = tempfile.mkstemp(suffix=".gitmodules")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write('[submodule "vendor/child"]\n\tpath = vendor/child\n\turl = ../child\n')
    check("cs1 CLI flags submodule conflict (exit 1)",
          M.main([mpath, "--submodules", gm]) == 1)
    check("cs2 CLI clean when no .gitmodules (exit 0)",
          M.main([mpath, "--submodules", os.path.join(tempfile.gettempdir(), "nope.gitmodules")]) == 0)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"version": 2}, "phases": [{"id": "P", "title": "p",
            "status": "pending", "tasks": [{"id": "P.1", "title": "t",
            "status": "pending", "files": ["src/app.ts"]}]}]}, fh)
    check("cs3 CLI clean when no task in a submodule (exit 0)",
          M.main([mpath, "--submodules", gm]) == 0)
    os.unlink(mpath)
    os.unlink(gm)

    # (cc) the --color flag end to end through main()
    fd, cpath = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_fixture(), fh)
    import contextlib as _ctx
    import io as _io

    def _cli_out(argv):
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            code = M.main(argv)
        return code, buf.getvalue()

    _c_def, _o_def = _cli_out([cpath])
    _c_nev, _o_nev = _cli_out([cpath, "--color", "never"])
    _c_alw, _o_alw = _cli_out([cpath, "--color", "always"])
    check("cc1 CLI --color never output is byte-identical to the default "
          "piped render (auto through a pipe is already plain)",
          _c_def == 0 and _c_nev == 0 and _o_def == _o_nev
          and "\033" not in _o_def)
    check("cc2 CLI --color always paints and strips back to the plain bytes",
          _c_alw == 0 and "\033[" in _o_alw
          and _cli_fmt.strip(_o_alw) == _o_def)
    check("cc3 an unknown --color value is a usage error (exit 2)",
          M.main([cpath, "--color", "sometimes"]) == 2)
    os.unlink(cpath)

    # --- (dv) --json --discovery: the init/task suggestion helper (v0.38 B) ------
    # The bare --json payload is a machine surface other tooling already parses;
    # dv1 pins it BYTE-for-byte to the pure rollup dump so the new flag can never
    # leak into it. Everything discovery-shaped hides behind --discovery.
    fd, dpath = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_fixture(), fh)
    _m_dv = _mio.load_manifest(dpath)
    _f_dv, _w_dv = vm.validate(_m_dv)
    _exp_dv = json.dumps(M.rollup(_m_dv, _f_dv, _w_dv,
                                usage=M.usage_summary(_m_dv, dpath)),
                         indent=2) + "\n"
    _c_dj, _o_dj = _cli_out([dpath, "--json"])
    check("dv1 bare --json output is byte-identical to the pure rollup dump - "
          "the pre-flag payload, pinned",
          _c_dj == 0 and _o_dj == _exp_dv)
    check("dv2 bare --json payload carries no discovery key",
          "discovery" not in json.loads(_o_dj))
    _c_dd, _o_dd = _cli_out([dpath, "--json", "--discovery"])
    _blob_dd = json.loads(_o_dd) if _c_dd == 0 else {}
    check("dv3 --json --discovery is valid JSON and gains the discovery block "
          "with skills and agents lists",
          _c_dd == 0 and isinstance(_blob_dd.get("discovery"), dict)
          and isinstance(_blob_dd["discovery"].get("skills"), list)
          and isinstance(_blob_dd["discovery"].get("agents"), list),
          _o_dd[:200])
    check("dv4 apart from the discovery key the flagged payload is the bare "
          "payload exactly - the flag only ADDS",
          {k: v for k, v in _blob_dd.items() if k != "discovery"}
          == json.loads(_o_dj))
    check("dv5 --discovery without --json is a usage error (exit 2) - it "
          "enriches the machine payload only",
          M.main([dpath, "--discovery"]) == 2)
    os.unlink(dpath)

    # hermetic project/home fixtures for the block itself
    _dtmp = tempfile.mkdtemp(prefix="audit-status-disc-")
    try:
        _dproj = os.path.join(_dtmp, "proj")
        _dhome = os.path.join(_dtmp, "home")
        os.makedirs(_dproj)
        os.makedirs(_dhome)
        check("dv6 an empty inventory is empty lists, never an error",
              M.discovery_block(_dproj, home=_dhome)
              == {"skills": [], "agents": []})
        _dsk = os.path.join(_dproj, ".claude", "skills", "big-skill")
        os.makedirs(_dsk)
        with open(os.path.join(_dsk, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nname: big-skill\ndescription: "
                     + "x" * 5000 + "\n---\n")
        _drows = M.discovery_block(_dproj, home=_dhome)["skills"]
        check("dv7 a discovered row carries exactly name/description/source "
              "(no path leak) with the description clipped to discovery's cap",
              bool(_drows)
              and set(_drows[0]) == {"name", "description", "source"}
              and _drows[0]["name"] == "big-skill"
              and len(_drows[0]["description"]) <= M.DISCOVERY_DESC_CAP,
              repr(_drows[:1]))
        _dfail = M.discovery_block(None)
        check("dv8 a discovery failure fails OPEN: empty lists plus a one-line "
              "error, never an exception through the status surface",
              set(_dfail) == {"skills", "agents", "error"}
              and _dfail["skills"] == [] and _dfail["agents"] == []
              and isinstance(_dfail["error"], str) and _dfail["error"]
              and "\n" not in _dfail["error"], repr(_dfail))
    finally:
        import shutil as _sh_dv
        _sh_dv.rmtree(_dtmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_status.py --selftest\n")
    raise SystemExit(2)
