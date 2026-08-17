#!/usr/bin/env python3
"""
The cases for `_report_html.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `_areas`, `_manifest_io` and `_ui_theme` are imported the
way the module under test imports them, because three cases assert IDENTITY
against them (`_tasks_by_id is _manifest_io.tasks_by_id`, `_areas_of is
_areas.areas_of`) or read a shared label - and an identity case only means
anything against the same module object production reached for.

A straight move otherwise: not one case here reads `__file__`, rebinds a global
or builds a path, so nothing in it changed meaning by sitting one directory over.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _report_html as M                           # noqa: E402
import _ui_theme as _theme                         # noqa: E402  (as _report_html imports it)
import _areas                                      # noqa: E402
import _manifest_io                                # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- e(): escaping is the whole point --------------------------------------
    check("e() escapes a script tag", M.e("<script>alert(1)</script>") ==
          "&lt;script&gt;alert(1)&lt;/script&gt;")
    check("e() escapes quotes (attribute context)",
          M.e('a "quoted" value') == "a &quot;quoted&quot; value")
    check("e() turns None into an empty string, not the word None",
          M.e(None) == "")
    check("e() stringifies non-strings before escaping", M.e(42) == "42")

    # --- _safe_url(): the one gate a URL passes before becoming an href -------
    check("_safe_url accepts https", M._safe_url("https://x.io/a") == "https://x.io/a")
    check("_safe_url accepts http", M._safe_url("http://x.io/a") == "http://x.io/a")
    check("_safe_url rejects javascript:", M._safe_url("javascript:alert(1)") is None)
    check("_safe_url rejects a bare string", M._safe_url("not a url") is None)
    check("_safe_url rejects None", M._safe_url(None) is None)

    # --- _report_basename(): sanitized to a bare filename ----------------------
    check("_report_basename prefers --basename over meta",
          M._report_basename({"reportBasename": "meta-name"}, "cli-name") == "cli-name")
    check("_report_basename falls back to meta.reportBasename",
          M._report_basename({"reportBasename": "meta-name"}, None) == "meta-name")
    check("_report_basename falls back to 'audit-report' with neither",
          M._report_basename({}, None) == "audit-report")
    check("_report_basename strips a leading path (cannot escape --out-dir)",
          M._report_basename({}, "../../etc/passwd") == "passwd")
    check("_report_basename tolerates a given extension",
          M._report_basename({}, "name.html") == "name")
    check("_report_basename strips characters outside [A-Za-z0-9-_]",
          M._report_basename({}, "a b!c") == "abc")

    # --- _tasks_by_id / _areas_of -----------------------------------------------
    _m = {"phases": [{"id": "P1", "tasks": [{"id": "P1.1", "title": "t"}]},
                     "not-a-dict"]}
    check("_tasks_by_id indexes every task across every phase",
          M._tasks_by_id(_m) == {"P1.1": {"id": "P1.1", "title": "t"}})
    check("_tasks_by_id tolerates a malformed phase entry",
          isinstance(M._tasks_by_id({"phases": [None, "x"]}), dict))
    check("_tasks_by_id is the shared implementation, not a copy of it",
          M._tasks_by_id is _manifest_io.tasks_by_id)
    # The ONE input the local copy answered differently: a JSON document whose
    # root is a list survives load_manifest unchanged, and `manifest.get(...)`
    # raised AttributeError on it — render-report crashed where it can now
    # render an empty report. A list is the fixture rather than None because
    # `None.get` and `[].get` both raise, and a list is the shape a real
    # hand-written manifest actually reaches the renderer as.
    def _index_of(manifest):
        """The index, or the raised exception's NAME — never a dict.

        The behaviour under test is "does not raise", so calling it bare would
        take the whole suite down with it and report nothing at all, including
        the ninety-odd cases that have nothing to do with this one. The
        exception name is a sentinel the success path can never produce.
        """
        try:
            return M._tasks_by_id(manifest)
        except Exception as exc:
            return type(exc).__name__

    check("_tasks_by_id returns {} for a non-object manifest root, where the "
          "local copy raised AttributeError",
          _index_of([{"id": "P1"}]) == {} and _index_of(None) == {})
    check("_areas_of wraps a bare string", M._areas_of("frontend") == ["frontend"])
    check("_areas_of passes a list of strings through, dropping junk",
          M._areas_of(["a", 1, "b", None]) == ["a", "b"])
    check("_areas_of returns [] for absent/other types", M._areas_of(None) == []
          and M._areas_of(3) == [])
    # The three cases above ALL pass on the pre-fix local copy — not one of them
    # repeats a tag or pads one, which is how the report kept drawing two chips
    # for `["api","api"]` while every other surface drew one, protected by a
    # green case. The three below are the ones that can tell the copy from
    # `_areas.areas_of`. The dedupe fixture is `["web","api","api"]` rather than
    # the alphabetical `["api","api","web"]` because a set-based dedupe answers
    # that one correctly by accident, and chip order is written order.
    check("_areas_of DEDUPES in written order - a repeated tag is one chip, not "
          "two (the local copy of this function shipped un-deduped)",
          M._areas_of(["api", "api"]) == ["api"]
          and M._areas_of(["web", "api", "api"]) == ["web", "api"])
    check("_areas_of TRIMS, so ' api' and 'api' are the same tag - written "
          "spacing must not split one area into two chips",
          M._areas_of([" api", "api"]) == ["api"]
          and M._areas_of(" frontend ") == ["frontend"])
    check("_areas_of is the shared implementation, not a copy of it",
          M._areas_of is _areas.areas_of)

    # --- _bug_view(): the shared derivation + this file's presentation ----------
    _tbi = {"T1": {"status": "done", "commit": "abc1234"}}
    check("_bug_view reads fixed from a done task when nothing is stored",
          M._bug_view({"taskId": "T1"}, _tbi) == ("fixed", "abc1234"))
    check("_bug_view prefers a stored fixedIn over the task's commit",
          M._bug_view({"taskId": "T1", "fixedIn": "manual"}, _tbi) ==
          ("fixed", "manual"))
    check("_bug_view leaves a wontfix bug alone even if its task is done",
          M._bug_view({"taskId": "T1", "status": "wontfix"}, _tbi) ==
          ("wontfix", "—"))
    check("_bug_view falls back to em dash with no task and no fixedIn",
          M._bug_view({"taskId": "nope", "status": "open"}, _tbi) == ("open", "—"))
    # The falsy-taskId guard this file did not have. The index is built the way
    # audit-status's ready list builds one — WITHOUT the truthy-id filter — so it
    # carries a falsy key, and the bug carries no taskId at all. Unguarded, the
    # lookup finds the ghost task, sees `done`, and reports a bug nobody linked to
    # anything as fixed in someone else's commit. Both stored statuses are
    # deliberately NOT "open": a broken implementation that fell back to "open"
    # would be indistinguishable from a correct one on that value.
    _tbi_unfiltered = {None: {"status": "done", "commit": "ghost1"},
                       "": {"status": "done", "commit": "ghost2"}}
    # The STATUS half must be the shared rule's answer on EVERY input, not merely
    # on a well-formed one. Swept rather than spot-checked: on the tidy rows the
    # old local copy agreed, and a single-fixture case would have been green
    # against exactly the implementation being replaced.
    check("_bug_view defers the status, without exception, to the one shared rule",
          all(M._bug_view(_b, _ix)[0] == _manifest_io.effective_bug_status(_b, _ix)
              for _b, _ix in (({"taskId": "T1", "status": "open"}, _tbi),
                              ({"taskId": "T1", "status": "wontfix"}, _tbi),
                              ({"taskId": "nope", "status": "triaged"}, _tbi),
                              ({"status": "triaged"}, _tbi_unfiltered),
                              ({"status": "in_progress", "taskId": ""},
                               _tbi_unfiltered))))
    check("_bug_view: a bug with NO taskId never matches a None key in an index "
          "built without the truthy-id filter",
          M._bug_view({"status": "triaged"}, _tbi_unfiltered) == ("triaged", "—"))
    check("_bug_view: an EMPTY taskId never matches an '' key either",
          M._bug_view({"status": "in_progress", "taskId": ""}, _tbi_unfiltered)
          == ("in_progress", "—"))
    # The decision on an empty stored `fixedIn`, in both directions. "" means
    # "nothing recorded" and falls through to the task's commit; a real string
    # wins over it. The commit here is a value the em-dash branch cannot produce
    # by accident, so the two readings disagree on a VALUE rather than on a type.
    check("_bug_view: an empty-string fixedIn means 'nothing recorded' and falls "
          "through to the linked task's commit",
          M._bug_view({"taskId": "T1", "fixedIn": ""}, _tbi) == ("fixed", "abc1234"))
    check("_bug_view: an empty fixedIn with no commit to borrow is the placeholder",
          M._bug_view({"taskId": "nope", "status": "triaged", "fixedIn": ""}, _tbi)
          == ("triaged", "—"))
    # The commit is borrowed only where the DERIVATION fired. A stored 'fixed' on
    # a task that is still running must not print that task's commit as the fix.
    check("_bug_view: a stored 'fixed' does not borrow a running task's commit",
          M._bug_view({"taskId": "T2", "status": "fixed"},
                    {"T2": {"status": "in_progress", "commit": "wip5678"}})
          == ("fixed", "—"))

    # --- chips / badges ----------------------------------------------------------
    check("_chip carries the machine value in the attribute and the label in text",
          M._chip("in_progress") == '<span class="chip" data-status="in_progress">%s</span>'
          % M.e(_theme.label("in_progress")))
    check("_chip_buttons humanizes vocabulary but not identifiers",
          "opus</button>" in M._chip_buttons(["opus"], "data-m", "fchip", humanize=False)
          and "opus</button>" not in M._chip_buttons(["done"], "data-s", "fchip"))
    check("_chip_buttons escapes a hostile status value",
          "&lt;script&gt;" in M._chip_buttons(["<script>"], "data-s", "fchip",
                                            humanize=False))
    check("_risk_chip renders only the three known levels",
          '<span class="rchip" data-risk="high">high</span>' == M._risk_chip("high")
          and M._risk_chip("HIGH") == M._risk_chip("high"))
    check("_risk_chip is an em dash for an unknown/null risk",
          '<span class="muted">—</span>' == M._risk_chip(None) == M._risk_chip("extreme"))

    # --- _ado_cell(): a link only when the url is safe --------------------------
    check("_ado_cell links a safe https ado url",
          M._ado_cell({"ado": {"id": 7, "url": "https://dev.azure.com/x/7"}}) ==
          '<a href="https://dev.azure.com/x/7">#7</a>')
    check("_ado_cell renders text-only for an unsafe url (never an href)",
          "href=" not in M._ado_cell({"ado": {"id": 7, "url": "javascript:alert(1)"}})
          and "#7" in M._ado_cell({"ado": {"id": 7, "url": "javascript:alert(1)"}}))
    check("_ado_cell is an em dash with no ado id",
          '<span class="muted">—</span>' == M._ado_cell({}))

    # --- _outcome_text(): descriptive over technical, truncated -----------------
    check("_outcome_text prefers descriptive over technical",
          M._outcome_text({"outcome": {"descriptive": "d", "technical": "t"}}) == "d")
    check("_outcome_text falls back to technical",
          M._outcome_text({"outcome": {"technical": "t"}}) == "t")
    _long = "x" * 100
    check("_outcome_text truncates past 70 chars with an ellipsis",
          M._outcome_text({"outcome": {"descriptive": _long}}) ==
          (_long[:70] + "…"))
    check("_outcome_text is '' with no outcome at all", M._outcome_text({}) == "")

    # --- _short_date() / _timing_cell() -----------------------------------------
    check("_short_date splits an ISO timestamp at T",
          M._short_date("2026-06-28T10:00:00Z") == "2026-06-28")
    check("_short_date passes a bare date through unchanged",
          M._short_date("2026-06-28") == "2026-06-28")
    check("_short_date is '' for None", M._short_date(None) == "")
    check("_timing_cell shows the completed date when done",
          "2026-07-09" in M._timing_cell({"completedAt": "2026-07-09T09:30:00Z"}))
    check("_timing_cell shows a muted started date when only started",
          "muted" in M._timing_cell({"startedAt": "2026-07-01T00:00:00Z"})
          and "2026-07-01" in M._timing_cell({"startedAt": "2026-07-01T00:00:00Z"}))
    check("_timing_cell is an em dash with neither",
          '<span class="muted">—</span>' == M._timing_cell({}))

    # --- _filter_attrs() / _filter_panel(): server-rendered filter state --------
    check("_filter_attrs emits only what is present",
          M._filter_attrs({}) == ""
          and 'data-model="opus"' in M._filter_attrs({"model": "opus"}))
    check("_filter_attrs cuts dates to their date part",
          'data-completed="2026-07-09"' in
          M._filter_attrs({"completedAt": "2026-07-09T09:30:00Z"}))
    _plain = {"phases": [{"tasks": [{"id": "t1"}]}]}
    check("_filter_panel is '' for a plan with no models and no dates",
          M._filter_panel(_plain) == "")
    _withmodel = {"phases": [{"tasks": [{"model": "opus"}]}]}
    check("_filter_panel renders the model chip row when a task has a model",
          'data-m="opus"' in M._filter_panel(_withmodel))
    _withdates = {"phases": [{"tasks": [
        {"startedAt": "2026-07-01T00:00:00Z", "completedAt": "2026-07-09T00:00:00Z"}]}]}
    check("_filter_panel's date range spans the earliest to the latest date",
          'min="2026-07-01" max="2026-07-09"' in M._filter_panel(_withdates))
    # D1: the Area chip row. A tag is enough on its own to earn the panel — the
    # plan below has no models and no dates — and the chips keep the tags'
    # first-seen order, deduped across phases by _areas.used_tags.
    _witharea = {"phases": [
        {"id": "P1", "area": "backend", "tasks": [{"id": "P1.1"}]},
        {"id": "P2", "area": ["web", "backend"], "tasks": []}]}
    _area_panel = M._filter_panel(_witharea)
    check("_filter_panel renders the Area chip row when any phase carries a tag "
          "(a tag alone earns the panel)",
          'id="audit-areas"' in _area_panel
          and 'class="fchip" data-a="backend"' in _area_panel
          and 'data-a="web"' in _area_panel)
    check("_filter_panel keeps area tags in first-seen order, deduped, spelled "
          "as identifiers rather than humanized",
          _area_panel.index('data-a="backend"') < _area_panel.index('data-a="web"')
          and _area_panel.count('data-a="backend"') == 1
          and ">backend</button>" in _area_panel)
    check("_filter_panel omits the Area row for a plan without tags",
          'id="audit-areas"' not in M._filter_panel(_withmodel))

    # --- _global_filter_row(): the sticky bar's compact filter line (C1/C2) ----
    _grow = M._global_filter_row(["b@x.io", "a@x.io"], ["api", "web"],
                               "2026-07-01", "2026-08-02")
    check("_global_filter_row renders author select, area select and the date "
          "pair with the data's own bounds",
          'id="audit-au-select"' in _grow and 'id="audit-area-select"' in _grow
          and 'id="audit-gfrom"' in _grow and 'id="audit-gto"' in _grow
          and _grow.count('min="2026-07-01" max="2026-08-02"') == 2)
    check("_global_filter_row keeps the callers' ordering (authors by spend, "
          "tags first-seen) instead of re-sorting identifiers",
          _grow.index('value="b@x.io"') < _grow.index('value="a@x.io"')
          and _grow.index('value="api"') < _grow.index('value="web"'))
    check("_global_filter_row offers the way back from a range (the All time "
          "reset, hidden until a range is on)",
          'id="audit-gclear" hidden' in _grow)
    check("_global_filter_row renders no author select for a single author "
          "(a set of one has nothing to filter)",
          'id="audit-au-select"' not in
          M._global_filter_row(["only@x.io"], ["api"], None, None))
    check("_global_filter_row is '' with nothing to filter by",
          M._global_filter_row([], [], None, None) == "")
    check("_global_filter_row escapes a hostile tag before it reaches an "
          "attribute",
          "&lt;script&gt;" in M._global_filter_row([], ["<script>"], None, None))

    # --- _ready_now_dl(): the Ready-now definition list (C4) --------------------
    _rm = {"phases": [
        {"id": "P1", "title": "Alpha", "status": "done", "area": ["api", "web"],
         "tasks": [{"id": "P1.1", "title": "done dep", "status": "done"}]},
        {"id": "P2", "title": "Beta", "status": "pending",
         "blockedBy": ["P1"],
         "tasks": [
             {"id": "P2.1", "title": "cleared one", "status": "pending",
              "blockedBy": ["P1.1"], "dependsOn": ["P1.1"]},
             {"id": "P2.2", "title": "free one", "status": "pending"}]}]}
    _rdl = M._ready_now_dl(_rm, ["P2.1", "P2.2"])
    check("_ready_now_dl is a definition list with one term per ready task, "
          "id and title both named",
          _rdl.startswith('<dl class="ready">')
          and _rdl.count("<dt>") == 2 and _rdl.count("<dd>") == 2
          and ">P2.1</code>" in _rdl and "<strong>cleared one</strong>" in _rdl)
    check("_ready_now_dl states the blockers that cleared, with the evidence",
          "depends on P1.1 (done)" in _rdl
          and "blocked by P1.1 (done)" in _rdl
          and "phase blocked by P1 (done)" in _rdl)
    _rdl_area = M._ready_now_dl(
        {"phases": [{"id": "P1", "area": "api",
                     "tasks": [{"id": "P1.1", "title": "t",
                                "status": "pending"}]}]}, ["P1.1"])
    # P2.2 above does NOT earn this line: its own list is empty but its PHASE
    # cleared a blocker, and that context is the more useful sentence. Only a
    # task with no blockers anywhere says nothing ever blocked it.
    check("_ready_now_dl says when nothing ever blocked a task, and only when "
          "nothing did (a cleared phase blocker still counts as context)",
          "Nothing blocked it" in _rdl_area
          and "Nothing blocked it" not in _rdl)
    check("_ready_now_dl carries the phase's area tags in the same chip style "
          "areas wear everywhere else",
          '<span class="area-tag">api</span>' in _rdl_area)
    check("_ready_now_dl names the phase the task sits in",
          'In <span class="mono">P2</span>' in _rdl)
    check("_ready_now_dl is '' for an empty list (the hero line is the empty "
          "state)", M._ready_now_dl(_rm, []) == "")
    check("_ready_now_dl escapes a hostile title",
          "&lt;script&gt;" in M._ready_now_dl(
              {"phases": [{"id": "P1", "tasks": [
                  {"id": "P1.1", "title": "<script>", "status": "pending"}]}]},
              ["P1.1"]))

    # --- _owner_map() / _area_tag_span(): advisory area owners (D4, v0.36) ------
    _own_m = {"meta": {"areas": {"api": {"owner": " ana@x.io "},
                                 "web": {"owner": None},
                                 "db": {"owner": 3},
                                 "ops": {"description": "no owner key"}}}}
    check("_owner_map keeps only tags declaring a non-empty string owner, "
          "trimmed - null, junk and undeclared all read as nobody",
          M._owner_map(_own_m) == {"api": "ana@x.io"})
    check("_owner_map is {} for a manifest without a registry",
          M._owner_map({}) == {} and M._owner_map(None) == {})
    check("_area_tag_span with no owner is byte-identical to the bare chip",
          M._area_tag_span("web", {"api": "a@x.io"})
          == '<span class="area-tag">web</span>')
    check("_area_tag_span with an owner wears the advisory suffix and the "
          "panel's exact title wording",
          M._area_tag_span("api", {"api": "ana@x.io"})
          == '<span class="area-tag" title="owner: ana@x.io">api'
             '<span class="aown"> — ana@x.io</span></span>')
    check("_area_tag_span escapes a hostile owner",
          "&lt;script&gt;" in M._area_tag_span("api", {"api": "<script>"})
          and "<script>" not in M._area_tag_span("api", {"api": "<script>"}))
    check("_chip_buttons titles: an entry in `titles` becomes the chip's title "
          "attribute, and an untitled chip keeps the pinned untitled shape",
          '<button type="button" class="fchip" data-a="api" '
          'title="owner: a@x.io" aria-pressed="false">api</button>'
          == M._chip_buttons(["api"], "data-a", "fchip", humanize=False,
                           titles={"api": "owner: a@x.io"})
          and '<button type="button" class="fchip" data-a="api" '
              'aria-pressed="false">api</button>'
          == M._chip_buttons(["api"], "data-a", "fchip", humanize=False))
    check("_filter_panel titles its area chips from the registry",
          'data-a="backend" title="owner: bo@x.io"' in M._filter_panel(
              dict(_witharea, meta={"areas": {"backend": {"owner": "bo@x.io"}}}))
          and 'title="owner:' not in _area_panel)
    check("_global_filter_row titles its options the same way, and only where "
          "an owner is declared",
          '<option value="api" title="owner: ana@x.io">api</option>'
          in M._global_filter_row([], ["api", "web"], None, None,
                                owners={"api": "ana@x.io"})
          and '<option value="web">web</option>'
          in M._global_filter_row([], ["api", "web"], None, None,
                                owners={"api": "ana@x.io"}))
    check("_ready_now_dl wears the same suffix on its tags",
          '<span class="aown"> — ro@x.io</span>' in M._ready_now_dl(
              {"meta": {"areas": {"api": {"owner": "ro@x.io"}}},
               "phases": [{"id": "P1", "area": "api",
                           "tasks": [{"id": "P1.1", "title": "t",
                                      "status": "pending"}]}]}, ["P1.1"]))

    # --- _seg_of(): the segment a phase row files under (D1, v0.36) -------------
    check("_seg_of maps in_progress and blocked to active, BOTH terminal states "
          "to the archive, and everything else - pending, unknown, None - to "
          "pending",
          M._seg_of("in_progress") == "active" and M._seg_of("blocked") == "active"
          and M._seg_of("done") == "archived" and M._seg_of("cancelled") == "archived"
          and M._seg_of("pending") == "pending"
          and M._seg_of("weird") == "pending" and M._seg_of(None) == "pending")
    check("VIEW_SEGS names the three views, and 'active' covers the two "
          "segments of unfinished work - a reader asking what is left means "
          "pending too",
          set(M.VIEW_SEGS) == {"active", "archived", "all"}
          and M.VIEW_SEGS["active"] == ("active", "pending")
          and M.VIEW_SEGS["all"] == M.SEG_ORDER)

    # --- tm / sha: the two table cells a reader has to ACT on --------------------
    check("tm the completion cell carries the clock, not just the day - two "
          "tasks finishing on one day is the case the column is read for",
          M._stamp("2026-06-28T10:04:59Z") == "2026-06-28 10:04"
          and M._stamp("2026-06-28") == "2026-06-28" and M._stamp(None) == ""
          and "2026-06-28 10:04" in M._timing_cell({"completedAt": "2026-06-28T10:04:59Z"}))
    check("tm ...and the full stamps stay on hover, both of them",
          "started 2026-06-28T09:00:00Z" in M._timing_cell(
              {"startedAt": "2026-06-28T09:00:00Z",
               "completedAt": "2026-06-28T10:04:59Z"}))
    check("sha the commit cell shows nine characters and copies FORTY - nine is "
          "not what cherry-pick wants",
          "abc1234de" in M._commit_cell({"commit": "abc1234de567890"})
          and 'data-copy="abc1234de567890"' in M._commit_cell(
              {"commit": "abc1234de567890"})
          and "btn-copy" in M._commit_cell({"commit": "abc1234de567890"}))
    check("sha a task with no commit gets an em dash and no button to press",
          "btn-copy" not in M._commit_cell({})
          and "\u2014" in M._commit_cell({"commit": "  "}))

    # --- _phase_meta_div() / _bar() ----------------------------------------------
    check("_phase_meta_div is '' with nothing to say",
          M._phase_meta_div({}) == "")
    check("_phase_meta_div joins present bits with a middot, all escaped",
          "branch audit/p1" in M._phase_meta_div({"branch": "audit/p1"})
          and "&lt;script&gt;" in M._phase_meta_div({"summary": "<script>"}))
    check("_bar computes a rounded percentage",
          '--w:50%' in M._bar(1, 2) and "1/2" in M._bar(1, 2))
    check("_bar is 0% for a zero total (never a ZeroDivisionError)",
          '--w:0%' in M._bar(0, 0) and "0/0" in M._bar(0, 0))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__report_html.py --selftest\n")
    raise SystemExit(2)
