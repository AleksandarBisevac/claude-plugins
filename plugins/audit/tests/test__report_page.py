#!/usr/bin/env python3
"""
The cases for `_report_page.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `_report_md` is imported the way `_report_page` imports it,
because pg1 compares the page's embedded twin against what THAT module renders and
a second module object would be comparing two copies.

ONE CASE FORCED A REAL CHANGE, AND IT IS `pg2c`. It parses the subject's source and
proves the module reaches no entry point - no `import _loader`, no `".py"` literal a
loader call could carry. Inline it read `__file__` and then DELETED the `_selftest`
FunctionDef from `tree.body`, because the check's own `.endswith(".py")` literal
would otherwise have been reported as a finding about the module. Both halves change
meaning here: `__file__` is now this test file, which is not the subject, and there
is no `_selftest` left to delete - the filter would match nothing while the case
kept printing PASS. It reads `M.__file__` and scans the WHOLE module body, which is
strictly more than the inline version saw. Proven red by adding `import _loader` to
`_report_page.py` and again by adding a bare `"audit-status.py"` literal inside a
function - the shape the deleted filter used to hide.

It now cuts `_output.PATH_PREAMBLE` out of the source before parsing, because that
block - identical in every `.py` under `scripts/` - carries `"_output.py"` as the
marker its walk-up searches for. Subtracting one exact constant is not the same move
as the `_selftest` filter that was deleted above: that one narrowed by a PATTERN
which had stopped matching anything, while this removes a byte-for-byte block a lint
independently proves is present exactly once.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import base64
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (PATH_PREAMBLE, for pg2c)
from _output import safe_stdio                     # noqa: E402
import _report_page as M                           # noqa: E402
import _report_md                                  # noqa: E402  (as _report_page imports it)


# --- cases --------------------------------------------------------------------
def _cases(check):

    # WHAT IS NOT HERE, AND WHY. The ~230 cases that pin the rendered document —
    # its markup, its emission ORDER, the stylesheet and the embedded script —
    # live with render-report.py, because they read a report written by `main()`
    # into a temp directory and a fragment module cannot write one. Splitting
    # them across two files by which function happens to emit each string would
    # have made both suites unreadable and neither complete. What is asserted
    # here is what this module decides on its OWN: the two seams the split
    # created, and the vocabulary that came with it.
    _m = {"meta": {"title": "page", "repo": "r"}, "bugs": [], "phases": [
        {"id": "P1", "title": "one", "status": "done",
         "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                    "commit": "abc1234", "completedAt": "2026-01-02T00:00:00Z"}]},
        {"id": "P2", "title": "two", "status": "pending", "blockedBy": ["P1", "P3"],
         "tasks": [{"id": "P2.1", "title": "t", "status": "pending"}]}]}
    _s = {"valid": True, "findings": 0, "ready": ["P2.1"],
          "tasks": {"total": 2, "byStatus": {"done": 1, "pending": 1}},
          "bugs": {"total": 0, "open": 0, "openHighSeverity": 0},
          "phases": [{"id": "P1", "title": "one", "status": "done",
                      "done": 1, "total": 1},
                     {"id": "P2", "title": "two", "status": "pending",
                      "done": 0, "total": 1}]}

    # --- the _report_md seam ---------------------------------------------------
    # The one edge that makes _report_md non-optional for anyone taking this
    # file: the page carries the Markdown twin as its "Download .md" payload, so
    # the two modules ship together or the button downloads something else.
    # Decoded and compared whole rather than probed for a phrase — a truncated or
    # differently-built payload passes every `in` test the phrase version could
    # make.
    _doc = M.render_html(_m, _s, "b", None)
    _mark = 'window.AUDIT_MD_B64="'
    _i = _doc.index(_mark)
    _blob = _doc[_i + len(_mark):_doc.index('"', _i + len(_mark))]
    check("pg1 the page embeds the Markdown twin base64, byte-for-byte what "
          "_report_md renders for the same plan - the Download .md button is "
          "this edge, and a split that dropped _report_md would break it",
          base64.b64decode(_blob).decode("utf-8")
          == _report_md.render_md(_m, _s, None))
    check("pg1b ...under the basename it was given, so two reports in one "
          "directory do not both offer to save 'audit-report.md'",
          'window.AUDIT_MD_NAME="b.md"' in _doc)

    # --- the verdict seam ------------------------------------------------------
    # The gate lives in audit-status.py, an ENTRY POINT this module sits below.
    # Calling it here would be a helper reaching up, which is the one direction
    # _deps.layer_violations() refuses - and it reads _loader calls, so it would
    # see it. The verdict is therefore injected.
    _called = []

    def _fake_verdict(summary):
        _called.append(summary)
        return "blocked", ["1 blocked task"], ["invalid", "blocked-tasks"]

    _vh = M.render_html(_m, _s, "b", None, verdict=_fake_verdict)
    # Read off the hero's own opening tag, never the whole document: `data-gate`
    # is also a SELECTOR in the embedded stylesheet (`.overall[data-gate=
    # "clear"]`), so a whole-document substring is satisfied by the CSS alone and
    # would pass with no verdict rendered at all.
    _hero = re.compile(r'<section class="overall"[^>]*>')
    check("pg2 a supplied verdict is the word in the hero, with its conditions "
          "spelled in the reader's words and the flag names kept for typing",
          len(_called) == 1
          and 'data-gate="blocked"' in _hero.search(_vh).group(0)
          and ">Blocked</p>" in _vh
          and "1 blocked task" in _vh
          and "manifest validity, blocked tasks" in _vh
          and "--fail-on invalid,blocked-tasks" in _vh)
    # The other direction. A hero that manufactured "Clear" from a missing
    # verdict would pass pg2 and would be the worst possible defect in this
    # file: an unevaluated gate reading as a passing one.
    check("pg2b no verdict is reported as UNKNOWN, never as clear - an "
          "unevaluated gate that reads as a passing one is the one failure a "
          "verdict hero must not have",
          "data-gate" not in _hero.search(_doc).group(0)
          and ">Unknown</p>" in _doc
          and "The gate could not be evaluated." in _doc
          and ">Clear</p>" not in _doc)
    # The seam is only real if this module genuinely never reaches the entry
    # point, so it is asserted in the two shapes `_deps` itself reads: an
    # `import` of `_loader`, and a `"....py"` literal that a loader call could
    # carry. Read off the AST rather than grepped, because both the docstring
    # above and the hero's own `title="audit-status.py --gate ..."` mention the
    # names in prose that is not an edge.
    #
    # `M.__file__`, NOT `__file__`. Inline, that read the module's own source
    # because the suite lived in it; from `tests/` the same line reads THIS
    # file, which is not the subject - the case would be asserting that the TEST
    # imports no `_loader`, which is trivially true and stays true whatever
    # `_report_page.py` grows.
    #
    # The `_selftest` filter that used to sit here is GONE rather than
    # re-pointed, and its removal is the point. It existed so that this
    # function's own `.endswith(".py")` literal - which ends in `.py` - would
    # not be reported as a finding about the production module. There is no
    # `_selftest` in the file being read any more, so the filter would match
    # nothing: a filter that narrows to nothing while still reading as "all
    # clear" is the exact shape this repo refuses. Dropping it also makes the
    # scan STRICTER than it was, because the whole module body is now read.
    #
    # THE PINNED PATH PREAMBLE IS CUT OUT FIRST, and this is not the filter that
    # was just deleted wearing a new hat. That block is byte-identical in every
    # `.py` under `scripts/` and `_output.path_preamble_violations()` counts it,
    # so it is not part of what this module CHOSE to spell; the one `.py` literal
    # it carries is `"_output.py"`, the marker the walk-up searches for, which no
    # loader call can reach and which every scripts/ file would otherwise report.
    # Removing exactly that constant - not a pattern that could match a real
    # target - is what keeps the case about `_report_page.py`'s own reach.
    with open(os.path.abspath(M.__file__), "r", encoding="utf-8") as _fh:
        _src = _fh.read()
    _src = _src.replace(_output.PATH_PREAMBLE, "")
    _tree = ast.parse(_src)
    _imported = set()
    for _n in ast.walk(_tree):
        if isinstance(_n, ast.Import):
            for _a in _n.names:
                _imported.add(_a.name.split(".")[0])
        elif isinstance(_n, ast.ImportFrom) and not _n.level:
            _imported.add((_n.module or "").split(".")[0])
    _py_literals = sorted(set(
        _n.value for _n in ast.walk(_tree)
        if isinstance(_n, ast.Constant) and isinstance(_n.value, str)
        and _n.value.endswith(".py")))
    check("pg2c ...and this module can reach no entry point at all: it imports "
          "no _loader and spells no '.py' target, so the audit-status edge "
          "stays L7 -> L7 where KNOWN_LAYER_DEBT records it. %r"
          % (_py_literals,),
          "_loader" not in _imported and _py_literals == [])

    # --- the vocabulary that moved with the page -------------------------------
    check("pg3 density follows the data: a plan on day one has earned none of "
          "the optional columns, and ONE task filling one earns exactly it",
          M._present_columns({"phases": [{"tasks": [{"id": "x"}]}]}) == []
          and M._present_columns(_m) == ["commit", "done"])
    # Both directions on the one optional column that is empty for almost every
    # repo: it appears for a repo that syncs, and a task whose `ado` is not an
    # object does not manufacture it. Dropping the isinstance guard in
    # `_OPTIONAL_COLS` makes the getter raise, `_present_columns` swallows that
    # into "keep the column", and the second half goes red.
    check("pg3b the ADO column belongs to repos that actually sync to Azure "
          "DevOps - and a task whose `ado` is not an object does not conjure it",
          M._present_columns({"phases": [{"tasks": [{"ado": {"id": 7}}]}]})
          == ["ADO"]
          and M._present_columns(
              {"phases": [{"tasks": [{"ado": "not-an-object"}]}]}) == [])
    check("pg4 a phase is held only by blockers that are NOT done - the rail "
          "draws dependency, not a second copy of status",
          M._held_by(_m["phases"][1], {"P1"}) == ["P3"]
          and M._held_by(_m["phases"][1], {"P1", "P3"}) == []
          and M._held_by({}, set()) == [])
    check("pg5 counts are worded, and the irregular plural is the caller's to "
          "give (`1 phase` / `2 phases`, `1 open bug` / `0 open bugs`)",
          M._plural(1, "phase") == "1 phase" and M._plural(2, "phase") == "2 phases"
          and M._plural(0, "open bug") == "0 open bugs"
          and M._plural(2, "entry", "entries") == "2 entries")

    # --- one page, three surfaces ---------------------------------------------
    # `fragment=True` is the Artifact mode. The document-level pins live with
    # render-report; what is asserted here is the DIFFERENCE the flag makes,
    # counted in both directions so a flag that did nothing fails.
    _frag = M.render_html(_m, _s, "b", None, fragment=True)
    check("pg6 the fragment drops the document wrapper and the theme toggle "
          "(the host supplies both) and keeps everything else",
          not any(t in _frag.lower() for t in
                  ("<!doctype", "<html", "</html>", "<meta charset"))
          and 'id="audit-theme"' not in _frag
          and "<title>" in _frag and '<table class="phases"' in _frag
          and "<!doctype html>" in _doc and 'id="audit-theme"' in _doc)
    # css=... is how a project's compiled theme reaches the page; the default is
    # the shipped sheet. Counted, because a page carrying BOTH would be a
    # stylesheet fight the reader loses at random.
    _themed = M.render_html(_m, _s, "b", None, css="/*THEMED*/")
    check("pg7 a supplied stylesheet replaces the shipped one rather than "
          "joining it - two <style> blocks is a cascade race, not a theme",
          _themed.count("<style>") == 1 and "/*THEMED*/" in _themed
          and M._CSS not in _themed and M._CSS in _doc)

    # --- _phase_rows -----------------------------------------------------------
    # The rows one phase emits. `data-seg` on EVERY one of them is what the view
    # gate and the per-segment print isolation select by; a row missing it is a
    # row that neither can reach.
    _rows = M._phase_rows(_m["phases"][0], _s["phases"][0], "archived", 3, [],
                        {"P1"}, {})
    check("pg8 a phase emits its group row, its task-status filter row and one "
          "row per task, and every one of them carries the segment",
          _rows.count('<tr class="phase"') == 1
          and _rows.count('<tr class="taskfilter"') == 1
          and _rows.count('<tr class="task"') == 1
          and _rows.count('data-seg="archived"') == 4)  # 3 rows + the detail row
    check("pg8b a malformed task is skipped without taking the phase's other "
          "rows with it",
          M._phase_rows({"tasks": ["not-a-dict"]},
                      {"id": "P9", "title": "t", "status": "pending",
                       "done": 0, "total": 0},
                      "pending", 3, [], set(), {}).count("<tr ") == 2)
    # Every manifest string is untrusted JSON. The document-level x* cases prove
    # the whole page escapes; this proves the row builder does, which is where a
    # `%s` added later would land.
    _evil = M._phase_rows(
        {"tasks": [{"id": "<script>alert(1)</script>", "title": "t",
                    "status": "pending"}]},
        {"id": "<img src=x>", "title": "<b>", "status": "pending",
         "done": 0, "total": 1}, "pending", 3, [], set(), {})
    check("pg9 a hostile id or title is escaped where the row is built, not "
          "only somewhere further up - and it is escaped, not deleted",
          "<script>" not in _evil and "<img src=x>" not in _evil
          and "&lt;script&gt;" in _evil and "&lt;img src=x&gt;" in _evil
          and "&lt;b&gt;" in _evil)
    check("pg10 the compact row shows only the columns it was handed; the rest "
          "of what the plan HAS lives in the detail row",
          M._phase_rows(_m["phases"][0], _s["phases"][0], "archived", 5,
                      ["commit", "done"], {"P1"}, {}).count("<td") -
          _rows.count("<td") == 2
          and re.search(r'<tr class="taskdetail"', _rows) is not None)

    # --- the block seam: one return carries the anchor AND the nav entry --------
    # `render_html` used to hold a `sections` list and a `section()` closure that
    # both the nav and the anchors read, defended by a comment asking the next
    # reader to remember to call it. Each block now hands back `(parts, records)`
    # together, so the two halves are one value out of one place. These cases are
    # what makes that a checked contract rather than a nicer-looking one.
    _mb = dict(_m, bugs=[{"id": "BUG-1", "title": "b", "status": "open",
                          "severity": "high", "taskId": "P2.1"}])
    _sb = dict(_s, bugs={"total": 1, "open": 1, "openHighSeverity": 1})
    _blocks = [
        ("head", M._head_block(_m["meta"], None, False)),
        ("nojs", M._nojs_block()),
        ("topbar", M._topbar_block(_m, _m["meta"], _s, None, {})),
        ("invalid", M._invalid_block(dict(_s, valid=False, findings=2))),
        ("gate", M._gate_block(_m["meta"], _s, None)),
        ("phases", M._phases_block(_m, _s, {})),
        ("usage", M._usage_block(None)),
        ("bugs", M._bugs_block(_mb, _sb)),
        ("ready", M._ready_block(_m, _s)),
        ("tail", M._tail_block(_m, _s, None, "b", False)),
    ]
    # Orphans in BOTH directions would be invisible to a bare "no orphans"
    # assertion over an empty record list, so the anchors are listed out too: a
    # block that stopped returning its record reads as "nothing orphaned".
    _orphans = ["%s/%s" % (_name, _rec[0])
                for _name, (_parts, _recs) in _blocks for _rec in _recs
                if ('id="%s"' % _rec[0]) not in "\n".join(_parts)]
    _anchors = sorted(_rec[0] for _, (_p, _recs) in _blocks for _rec in _recs)
    check("pg11 every section record a block returns is carried by the HTML that "
          "same block returned - the nav entry and the anchor are one value from "
          "one place, so neither can exist without the other. %r / %r"
          % (_orphans, _anchors),
          _orphans == [] and _anchors == ["bugs", "gate", "phases", "ready"])
    # And the other direction, at the document: the nav lists exactly the
    # anchors, in emission order, and each resolves to exactly ONE id. Counted
    # rather than probed - two sections claiming one id is precisely the shape a
    # presence assertion cannot see.
    _nav = re.search(r'<nav class="snav".*?</nav>', _doc, re.S).group(0)
    _hrefs = re.findall(r'href="#([^"]+)"', _nav)
    check("pg12 the rendered nav links exactly the sections the page emitted, in "
          "emission order, and every link resolves to exactly one id. %r"
          % (_hrefs,),
          _hrefs == ["gate", "phases", "ready"]
          and all(_doc.count('id="%s"' % _a) == 1 for _a in _hrefs))
    # A block's parts are a LIST so that "contributes nothing" and "contributes
    # one empty line" stay different answers. The Usage block emits the second
    # when there is no ledger - the page has always carried that line - and
    # returning `[]` there moves a newline in every report without usage. Proven
    # red by making exactly that change: six of thirteen rendered fixtures moved.
    check("pg13 an absent ledger emits the Usage LINE and no nav entry ([\"\"], "
          "not []), while an absent bugs table and an empty ready list emit "
          "nothing at all - the two are different answers, not one",
          M._usage_block(None) == ([""], [])
          and M._bugs_block(dict(_m, bugs=[]), _s) == ([], [])
          and M._ready_block(_m, dict(_s, ready=[])) == ([], []))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__report_page.py --selftest\n")
    raise SystemExit(2)
