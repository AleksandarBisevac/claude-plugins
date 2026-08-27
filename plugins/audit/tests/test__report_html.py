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
# `_report_html` may NOT import this - the two are layer-mates and the import
# graph refuses the edge - so the evidence-gap vocabulary is spelled in both and
# compared HERE. A suite may import anything, which is what makes this the only
# place the two spellings can be held equal.
import _status_facts                                # noqa: E402


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
    _one = M._global_filter_row(["only@x.io"], ["api"], None, None)
    check("_global_filter_row renders no author select for a single author "
          "(a set of one has nothing to filter)",
          'id="audit-au-select"' not in _one)
    # ...but the header still ANSWERS "who worked on this". Reported by a reader
    # who wanted Author beside Area/From/To and, on a solo project, found the
    # whole control missing. A one-option dropdown would be a control whose every
    # use is a no-op - the same defect as a status chip the view can never
    # satisfy - so the bar states the name instead of offering to filter by it.
    check("_global_filter_row STATES the single author rather than offering a "
          "dropdown that could only pick the value it already shows",
          'id="audit-au-only"' in _one and "only@x.io" in _one
          and "Author" in _one
          and "nothing to filter between" in _one)
    check("...and that value is escaped like every other identifier here",
          "&lt;b&gt;" in M._global_filter_row(["<b>"], [], None, None)
          and "<b>" not in M._global_filter_row(["<b>"], [], None, None)
             .replace("&lt;b&gt;", ""))
    check("...and no authors at all still renders nothing, because there is no "
          "fact to state either",
          'id="audit-au-only"' not in M._global_filter_row([], ["api"], None, None))
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
    check("_phase_meta_div leads with the priority pin - the only bit that "
          "answers WHEN this runs rather than what it is",
          M._phase_meta_div({"priority": 2, "branch": "audit/p1"})
          .index("priority 2")
          < M._phase_meta_div({"priority": 2, "branch": "audit/p1"})
          .index("branch audit/p1"),
          M._phase_meta_div({"priority": 2, "branch": "audit/p1"}))
    check("...and a `priority` the run does not honour draws NO badge, because "
          "it is read through `_priority.tier_of` rather than off the field - a "
          "badge from the raw value would advertise a pin nothing follows",
          M._phase_meta_div({"priority": "2"}) == ""
          and M._phase_meta_div({"priority": 0}) == "",
          M._phase_meta_div({"priority": "2"}))
    check("SECOND-DIRECTION CASE: an unpinned phase's sub-line is what it always "
          "was. Reads vacuous, and is the only case that fails if the badge "
          "becomes unconditional and every phase grows a 'priority None'",
          M._phase_meta_div({"branch": "audit/p1"}) == M._phase_meta_div(
              {"branch": "audit/p1", "priority": None}),
          M._phase_meta_div({"branch": "audit/p1"}))

    # --- any_phase_pinned() / phase_ranks(): the sort option's basis ------------
    # The rank the page hands its sort control, and the one predicate that
    # decides whether the control is offered at all. Both halves have to come
    # from ONE answer: a select with no ranks on the rows is a dropdown that
    # reorders nothing, and ranks with no select is dead weight.
    _pinned = {"phases": [{"id": "A"}, {"id": "B", "priority": 3},
                          {"id": "C"}, {"id": "D", "priority": 1}]}
    check("pr-h1 phase_ranks puts the pinned phases first by tier and leaves the "
          "rest in manifest order - D (tier 1), then B (tier 3), then A and C "
          "where they were written",
          M.phase_ranks(_pinned) == [2, 1, 3, 0],
          repr(M.phase_ranks(_pinned)))
    # ABSENT MEANS ZERO, COMPUTED rather than described. dd60a11 shipped two case
    # labels that named the ordering a mutation produces and named it wrongly, so
    # the naive comparator is built here and the two are compared - a computed
    # disagreement cannot rot into agreement the way a sentence can.
    _items = _pinned["phases"]
    _as_zero = [0] * len(_items)
    for _r, _i in enumerate(sorted(range(len(_items)),
                                   key=lambda i: (_items[i].get("priority") or 0, i))):
        _as_zero[_i] = _r
    check("pr-h1b ...and an absent tier is a CLASS, not tier 0: under a "
          "comparator that read a missing priority as zero this same plan ranks "
          "differently, which is what makes the fixture able to tell the two "
          "implementations apart at all",
          M.phase_ranks(_pinned) != _as_zero,
          "honoured=%r  absent-as-zero=%r" % (M.phase_ranks(_pinned), _as_zero))
    check("pr-h2 ...and the ranks are positional against the SAME filtered list "
          "the rollup and the table rows are zipped from, so a non-dict entry "
          "cannot slide the alignment by one",
          M.phase_ranks({"phases": ["junk", {"id": "B", "priority": 1},
                                    {"id": "A"}]}) == [0, 1],
          repr(M.phase_ranks({"phases": ["junk", {"id": "B", "priority": 1},
                                         {"id": "A"}]})))
    check("pr-h3 a tier the run does not honour is not a pin: read through "
          "_priority.tier_of, so `priority: \"1\"` and `priority: 0` leave the "
          "plan with nothing to sort by and the control unoffered",
          M.any_phase_pinned({"phases": [{"id": "A", "priority": "1"},
                                         {"id": "B", "priority": 0}]}) is False
          and M.phase_ranks({"phases": [{"id": "A", "priority": "1"}]}) == [])
    check("pr-h4 SECOND-DIRECTION CASE: a plan with no priority at all gets NO "
          "ranks, so no row grows the attribute and no control is drawn. Reads "
          "vacuous, passes by construction on the code before the sort option, "
          "and is the one case that fails if an absent tier ever becomes tier 0 "
          "- which would pin every phase in every plan ever rendered",
          M.phase_ranks({"phases": [{"id": "A"}, {"id": "B"}]}) == []
          and M.any_phase_pinned({"phases": [{"id": "A"}, {"id": "B"}]}) is False
          and M.any_phase_pinned({}) is False)


    # --- tv: the test-gate vocabulary, and the derivation behind the badge ----
    # THE BADGE IS THE STATUS AND THE MARKERS ARE NOT. Every case below is a
    # PAIR over one input: change exactly one field and assert the answer moves,
    # because the failure this whole area guards against is two states rendering
    # alike.
    check("tv1 a pointer with no runId points at nothing, so it reads as no "
          "block at all - and one WITH a runId reads as a pointer, so this is "
          "not a function that always answers None",
          M.tev_pointer({"testEvidence": {"status": "passed"}}) is None
          and M.tev_pointer({"testEvidence": {"runId": "R"}}) == {"runId": "R"}
          and M.tev_pointer({}) is None
          and M.tev_pointer("not-a-dict") is None)
    check("tv2 a gate is configured when the TASK declares one, when its PHASE "
          "declares one, and not when neither does - absent and empty are one "
          "answer, exactly as run-test-gate.gate_of takes them",
          M.tev_configured({"tests": {"gate": ["x"]}}, {}) is True
          and M.tev_configured({}, {"testGate": ["x"]}) is True
          and M.tev_configured({"tests": {"gate": []}}, {"testGate": []}) is False
          and M.tev_configured({}, {}) is False)

    # `ran` / `treeMutated` / `coverage`: one row, one field moved at a time.
    def _row(**over):
        obs = {"ranTotal": 3, "treeMutated": [], "coverage": ["a.py"]}
        obs.update(over)
        return {"status": "passed", "observations": obs,
                "treeMutated": obs["treeMutated"]}

    check("tv3 treeMutated None is 'tree unknown' and treeMutated [] is NO "
          "marker at all - a truthy test would make these one answer, which is "
          "the merge run-test-gate refuses in its own renderer",
          ("tree-unknown", "tree unknown") in M.tev_flags(_row(treeMutated=None))
          and not [k for k, _w in M.tev_flags(_row(treeMutated=[]))
                   if k.startswith("tree-")])
    check("tv3b ...and a populated list is the third answer",
          ("tree-mutated", "tree mutated")
          in M.tev_flags(_row(treeMutated=["a.py"])))
    check("tv4 coverage None is 'coverage unknown' and coverage [] is 'no "
          "overlap' - the question nobody could ask against the question "
          "answered no",
          ("coverage-unknown", "coverage unknown")
          in M.tev_flags(_row(coverage=None))
          and ("no-overlap", "no overlap") in M.tev_flags(_row(coverage=[]))
          and not [k for k, _w in M.tev_flags(_row(coverage=["a.py"]))
                   if k in ("no-overlap", "coverage-unknown")])
    check("tv5 ranTotal None earns 'checks unknown' and a POSITIVE ZERO does "
          "not - zero is a count the runner really reported and null is no "
          "count at all",
          ("checks-unknown", "checks unknown") in M.tev_flags(_row(ranTotal=None))
          and "checks-unknown" not in [k for k, _w in M.tev_flags(_row(ranTotal=0))]
          and "checks-unknown" not in [k for k, _w in M.tev_flags(_row(ranTotal=3))])

    _ptr = {"runId": "R", "status": "passed", "at": "t"}
    check("tv6 the three no-run states are three keys, three sentences and "
          "three different sets of words - never one grey blob",
          [M.tev_view(None, None, True)["key"],
           M.tev_view(None, None, False)["key"],
           M.tev_view(_ptr, None, True)["key"]]
          == ["no-evidence", "no-gate", "dangling"]
          and len({M.tev_view(None, None, True)["why"],
                   M.tev_view(None, None, False)["why"],
                   M.tev_view(_ptr, None, True)["why"]}) == 3)
    # --- tv6b..tv6g: the evidence boundary, as the badge tells it ------------
    # FOUR SENTENCES WHERE THERE WERE THREE. `No evidence` used to answer for
    # work finished before this plan could record anything, which is the state a
    # mid-flight adopter's plan is FULL of - and it reads as neglect while the
    # gate reports green. The class is `_status_facts.evidence_gap`'s, never
    # re-derived here, so the badge and the gate's verdict cannot disagree.
    check("tv6b the gap classes and the badge keys are ONE table, total over "
          "`_status_facts.GAP_CLASSES` - a class added there without a word "
          "here would render as a class this build silently calls `no-evidence`",
          sorted(M.TEV_GAP_KEYS) == sorted(_status_facts.GAP_CLASSES),
          "%r vs %r" % (sorted(M.TEV_GAP_KEYS),
                        sorted(_status_facts.GAP_CLASSES)))
    check("tv6b2 ...and so is the table of REASONS, which is keyed by the class "
          "and not by the badge key precisely because two classes share one word",
          sorted(M._TEV_GAP_WHY) == sorted(_status_facts.GAP_CLASSES),
          repr(sorted(M._TEV_GAP_WHY)))
    check("tv6c each class earns a different SENTENCE, and two of the three a "
          "different word - `sinceBoundary` shares `No evidence` on purpose, "
          "because its repair is the same one and its reason is not",
          len(set(M._TEV_GAP_WHY.values())) == len(M._TEV_GAP_WHY)
          and sorted(set(M.TEV_GAP_KEYS.values())) == ["before-recording",
                                                       "no-evidence", "undated"])
    check("tv6c2 ...and the class that shares the word does not share the "
          "sentence with the subject NOBODY classified - 'why was my neighbour "
          "excused and this one not' is the question a mid-flight reader has",
          M.tev_view(None, None, True,
                     gap=_status_facts.GAP_SINCE, basis="B")["why"]
          != M.tev_view(None, None, True, gap=None)["why"]
          and M.tev_view(None, None, True,
                         gap=_status_facts.GAP_SINCE,
                         basis="B")["label"]
          == M.tev_view(None, None, True, gap=None)["label"])
    check("tv6d a done subject with a gate and no pointer reads `Before "
          "recording` when the boundary excused it and `No evidence` when it "
          "did not - the two are what a reader acts on differently",
          M.tev_view(None, None, True,
                     gap=_status_facts.GAP_BEFORE)["label"] == "Before recording"
          and M.tev_view(None, None, True,
                         gap=_status_facts.GAP_SINCE)["label"] == "No evidence"
          and M.tev_view(None, None, True, gap=None)["label"] == "No evidence")
    check("tv6e ...and the third class is said too: `undated` is a FAILURE the "
          "gate names apart, and a reader shown `No evidence` for it is sent to "
          "run a gate when the repair is to set the completion stamp",
          M.tev_view(None, None, True,
                     gap=_status_facts.GAP_UNDATED)["key"] == "undated"
          and M.tev_view(None, None, True,
                         gap=_status_facts.GAP_UNDATED)["label"]
          != M.TEV_LABELS["no-evidence"])
    check("tv6f a subject NOTHING GRADES stays `No gate configured` whatever "
          "the boundary says - a gate that was never declared could not have "
          "run before OR after recording began, so the boundary changes no "
          "repair here",
          [M.tev_view(None, None, False, gap=g)["key"]
           for g in _status_facts.GAP_CLASSES] == ["no-gate"] * 3)
    check("tv6g the excuse carries the BASIS that licenses it, and says so when "
          "it was handed none - an excuse with nothing behind it is the claim "
          "this whole mechanism exists to refuse",
          "the earliest recorded run is X" in M.tev_view(
              None, None, True, gap=_status_facts.GAP_BEFORE,
              basis="the earliest recorded run is X")["why"]
          and "no basis" in M.tev_view(
              None, None, True, gap=_status_facts.GAP_BEFORE)["why"])
    check("tv6h a gap class this build does not know is NAMED rather than "
          "folded into `no-evidence`, the same reading tv8 takes of a status "
          "word from a newer plugin",
          M.tev_view(None, None, True, gap="afterTheHeatDeath")["known"] is False
          and M.tev_view(None, None, True,
                         gap="afterTheHeatDeath")["key"] == "afterTheHeatDeath"
          and M.tev_view(None, None, True,
                         gap=_status_facts.GAP_BEFORE)["known"] is True)
    check("tv7 the LEDGER decides the verdict, not the cached pointer: a "
          "pointer saying passed over a row saying failed renders Failed",
          M.tev_view({"runId": "R", "status": "passed"},
                     {"status": "failed"}, True)["key"] == "failed"
          and M.tev_view({"runId": "R", "status": "failed"},
                         {"status": "passed"}, True)["key"] == "passed")
    check("tv8 a word this build does not know is NAMED, never folded into "
          "failed - the schema promises the enum may gain members",
          M.tev_view(_ptr, {"status": "sandbagged"}, True)["key"] == "sandbagged"
          and M.tev_view(_ptr, {"status": "sandbagged"}, True)["known"] is False
          and M.tev_view(_ptr, {"status": "failed"}, True)["known"] is True)
    check("tv8b ...and it still renders words a person can read rather than "
          "an empty badge",
          M.tev_view(_ptr, {"status": "sandbagged"}, True)["label"] == "Sandbagged"
          and M.tev_view(_ptr, {"status": ""}, True)["label"]
          == "Unrecognised status")
    check("tv9 the badge carries the STATUS and the markers are rendered "
          "beside it, so a run that failed AND rewrote the tree says both",
          M._tev_cell(M.tev_view(_ptr, _row(status="failed", treeMutated=["a"]),
                                 True)).count("<span") == 2
          and 'data-tev="failed"' in M._tev_cell(
              M.tev_view(_ptr, dict(_row(treeMutated=["a"]), status="failed"), True))
          and 'data-tevf="tree-mutated"' in M._tev_cell(
              M.tev_view(_ptr, dict(_row(treeMutated=["a"]), status="failed"), True)))
    check("tv9b ...and a clean run carries the badge alone, so tv9 is counting "
          "a marker and not counting spans",
          M._tev_cell(M.tev_view(_ptr, _row(), True)).count("<span") == 1)
    check("tv10 the rollup counts in vocabulary order with an unknown word "
          "last, rather than alphabetically - `cancelled` above `passed` reads "
          "as a ranking nobody chose",
          [k for k, _l, _n in M.tev_rollup(
              [{"key": "no-gate", "flags": []}, {"key": "zz", "flags": []},
               {"key": "failed", "flags": []}, {"key": "passed", "flags": []},
               {"key": "passed", "flags": []}])]
          == ["passed", "failed", "no-gate", "zz"]
          and M.tev_rollup([{"key": "passed", "flags": []},
                            {"key": "passed", "flags": []}])[0][2] == 2)
    check("tv11 the row's two filter axes are two attributes, and a task with "
          "no observations carries only the first",
          M._filter_attrs({}, M.tev_view(_ptr, _row(treeMutated=["a"]), True))
          == ' data-tev="passed" data-tev-flags="tree-mutated"'
          and M._filter_attrs({}, M.tev_view(_ptr, _row(), True))
          == ' data-tev="passed"'
          and M._filter_attrs({}) == "")
    check("tv12 a bug borrows its fixing task's view and says so; with no task "
          "id, and with an id this plan does not carry, it says two different "
          "things and neither of them is a verdict",
          M.tev_bug_view({"taskId": "T1"}, {"T1": {"key": "failed"}})[1] == "T1"
          and M.tev_bug_view({"taskId": None}, {})[0] is None
          and M.tev_bug_view({"taskId": "T9"}, {})[1] != M.tev_bug_view(
              {"taskId": None}, {})[1])
    check("tv13 the chip factory humanises out of the table it is HANDED, so "
          "the evidence chips read as English while the manifest's own chips "
          "are untouched by the new argument",
          ">No checks ran</button>" in M._chip_buttons(
              ["no-checks"], "data-tev", "fchip", mapping=M.TEV_LABELS)
          and M._chip_buttons(["done"], "data-ps", "fchip")
          == M._chip_buttons(["done"], "data-ps", "fchip", mapping=None))



def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__report_html.py --selftest\n")
    raise SystemExit(2)
