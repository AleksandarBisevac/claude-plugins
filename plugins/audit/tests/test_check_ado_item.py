#!/usr/bin/env python3
"""
The cases for `check-ado-item.py` — the gate `/audit:sync push` knocks on.

The rule lives in `_ado_conventions` and has its own suite; what is pinned HERE
is the door: the exit-code contract, that the manifest's `meta.ado.conventions`
is what gets applied, and — the case that matters most — that **"this board has
no standard" and "checked, clean" are different answers**. A caller that cannot
tell them apart reads an unconfigured board as a conforming one, which is the
quiet failure this whole feature exists to prevent.

Exit 1 rather than a warning is deliberate and pinned: `SECURITY.md` splits
advisory paths (fail open) from guards (fail loud), and a work item that lands
on someone's board looking foreign cannot be un-landed.

The other half arrived with `meta.ado.fields`: this command MERGES before it
grades, so it is also where the payload to send comes from. `ci15` asserts both
directions of that on one board — the payload the connector can build refused,
and the same payload passing once the template supplies what the board asks for
— because a pass alone could equally mean the conformance check broke.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("check-ado-item.py", modname="check_ado_item")

BOARD = {"descriptionMustContain": {"Task": ["Done when"]},
         "tagVocabulary": {"type": ["refactor"]},
         "requireParent": True}

GOOD = {"type": "Task",
        "fields": {"System.Description": "Done when: CI green.",
                   "System.Tags": "type:refactor"},
        "parent": 103205}
# Breaks all three rules on purpose: no skeleton marker, a tag whose prefix is
# outside the vocabulary, and no parent. Written this way after an earlier
# version carried NO tags and produced two violations rather than three - an
# absent tag list is nothing to reject, which is correct and made the case's own
# claim ("three rules are broken") false.
BAD = {"type": "Task", "fields": {"System.Description": "Merge it.",
                                  "System.Tags": "area:dashboard"}}


def _write(tmp, name, obj):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def _run(argv):
    """(exit code, stdout) — the printed answer is half this command's contract."""
    buf, real = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = M.main(argv)
    finally:
        sys.stdout = real
    return code, buf.getvalue()


# --- cases --------------------------------------------------------------------
def _cases(check):
    # exit-code contract, before anything about conventions
    check("ci0 no arguments is a usage error, not an accidental pass",
          M.main([]) == 2)
    tmp = tempfile.mkdtemp(prefix="qg-adoitem-")
    try:
        item_good = _write(tmp, "good.json", GOOD)
        item_bad = _write(tmp, "bad.json", BAD)

        # The item is READABLE here on purpose. An earlier version passed
        # /no/such/item.json too, so the 2 could come from either read - and it
        # did: mutating the manifest branch to fail open left this case green,
        # because the item's failure produced the same 2. A case that can pass
        # for a reason other than the one it names is not a case.
        check("ci1 an unreadable MANIFEST is 2, and only the manifest can "
              "produce it here - never a silent fall-through to 'conforms'",
              M.main(["/no/such/manifest.json", "--item", item_good]) == 2)
        _broken = os.path.join(tmp, "broken.json")
        with open(_broken, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("ci1b ...and unparseable counts as unreadable, since a manifest "
              "that cannot be read carries no conventions to apply either",
              M.main([_broken, "--item", item_good]) == 2)
        m_std = _write(tmp, "with.json", {"meta": {"ado": {"conventions": BOARD}}})
        m_none = _write(tmp, "without.json", {"meta": {"ado": {}}})
        m_bare = _write(tmp, "bare.json", {})

        check("ci2 --item naming a file that does not exist is 2, not 'conforms'",
              M.main([m_std, "--item", os.path.join(tmp, "nope.json")]) == 2)

        code, out = _run([m_std, "--item", item_good])
        check("ci3 a conforming item exits 0 and says which manifest's rules it "
              "was measured against: %r" % (out.strip()[:70],),
              code == 0 and "conforms" in out)

        # F-P-16: exit 2, and specifically NOT 1. A 1 says "this item does not
        # belong on the board"; saying that about a payload we could not read
        # is the confident wrong answer the guard exists to stop.
        item_fetched = _write(tmp, "fetched.json", {
            "id": 31, "rev": 3, "url": "https://dev.azure.com/o/_apis/wit/workItems/31",
            "fields": {"System.WorkItemType": "Task", "System.Tags": "audit-plugin"}})
        check("ci14 a work item fetched from ADO is refused as the wrong SHAPE "
              "(2), not accused of breaking the board's rules (1)",
              M.main([m_std, "--item", item_fetched]) == 2)

        code, out = _run([m_std, "--item", item_bad])
        check("ci4 a non-conforming item exits 1 and REFUSES rather than warning "
              "- a created work item cannot be un-created: %r"
              % (out.strip()[-60:],),
              code == 1 and "do NOT create" in out)
        check("ci5 ...and every violation is printed, not just the first: three "
              "rules are broken here and three lines say so",
              out.count("FINDING:") == 3, out)

        # THE case: two different zeros must not read the same.
        code_none, out_none = _run([m_none, "--item", item_bad])
        check("ci6 a board with no conventions exits 0 for an item that would "
              "fail every rule - there is no standard to meet",
              code_none == 0)
        check("ci7 ...and SAYS so rather than printing the clean message: "
              "'nothing was checked' and 'checked, clean' are different "
              "answers, and a caller that cannot tell them apart reads an "
              "unconfigured board as a conforming one",
              "no standard" in out_none and "conforms" not in out_none)
        _, out_clean = _run([m_std, "--item", item_good])
        check("ci8 ...proven by the two messages differing, not by reading one",
              out_none.strip() != out_clean.strip())

        check("ci9 a manifest with no meta.ado at all is the same answer, not a "
              "crash - the connector being unconfigured is legal",
              M.main([m_bare, "--item", item_bad]) == 0)

        # --json: same verdict, machine-readable, and it carries the distinction
        code, out = _run([m_std, "--item", item_bad, "--json"])
        payload = json.loads(out)
        check("ci10 --json keeps the exit code and reports the same verdict",
              code == 1 and payload["conforms"] is False
              and len(payload["violations"]) == 3)
        code, out = _run([m_none, "--item", item_bad, "--json"])
        payload = json.loads(out)
        check("ci11 ...and `hasStandard` is what makes the two zeros "
              "distinguishable to a script, not only to a reader",
              code == 0 and payload["conforms"] is True
              and payload["hasStandard"] is False)

        # stdin, because the orchestrator holds the payload in hand
        real = sys.stdin
        sys.stdin = io.StringIO(json.dumps(BAD))
        try:
            check("ci12 the payload may arrive on stdin ('-'), which is how a "
                  "caller that built it in memory passes it without a temp file",
                  M.main([m_std, "--item", "-"]) == 1)
        finally:
            sys.stdin = real

        # --- meta.ado.fields: the gate SUPPLIES before it grades ------------
        # The board fixture asks for a field the connector cannot write, which
        # is the situation this whole key exists for: without a template the
        # gate refuses every CREATE and the push creates nothing.
        _needs = {"requiredFields": {"Task": ["Microsoft.VSTS.Common.Activity"]}}
        _tpl = {"Task": {"Microsoft.VSTS.Common.Activity": "Development"}}
        m_nofields = _write(tmp, "nofields.json",
                            {"meta": {"ado": {"conventions": _needs}}})
        m_fields = _write(tmp, "fields.json",
                          {"meta": {"ado": {"conventions": _needs,
                                            "fields": _tpl}}})
        item_plain = _write(tmp, "plain.json",
                            {"type": "Task", "fields": {"System.Title": "x"},
                             "parent": 1})

        # BOTH halves asserted. Without the refusal the pass below could come
        # from a broken conformance check rather than from the merge.
        code_no, out_no = _run([m_nofields, "--item", item_plain])
        code_yes, out_yes = _run([m_fields, "--item", item_plain])
        check("ci15 the payload the connector can build is REFUSED by this "
              "board, and the same payload passes once meta.ado.fields supplies "
              "the field - the gate can now be honest about the board: %r"
              % (out_no.strip()[:60],),
              code_no == 1 and code_yes == 0)
        check("ci16 ...and the merge is PRINTED, because a payload the caller "
              "does not know it has to send is a green gate and a "
              "non-conforming item: %r" % (out_yes.strip()[:70],),
              out_yes.count("MERGED:") == 1
              and out_yes.count("Microsoft.VSTS.Common.Activity=") == 1)

        # --json is where a script gets the payload to send.
        _, out = _run([m_fields, "--item", item_plain, "--json"])
        payload = json.loads(out)
        # Read with .get rather than indexing: a mutation that drops the merge
        # must make this case REPORT, not raise and take the rest of the suite's
        # unprinted output with it.
        _sent = (payload.get("payload") or {}).get("fields") or {}
        check("ci17 --json hands back the merged payload under `payload`, which "
              "is what the create must send: %r" % (_sent,),
              _sent.get("Microsoft.VSTS.Common.Activity") == "Development"
              and payload.get("fieldsAdded") == _tpl["Task"]
              and payload.get("fieldsSkipped") == {})
        _, out = _run([m_std, "--item", item_good, "--json"])
        payload = json.loads(out)
        check("ci18 ...and with no meta.ado.fields it is the payload that came "
              "in, unchanged - 'this key is absent' as an equality rather than "
              "as a promise",
              payload.get("payload") == GOOD and payload.get("fieldsAdded") == {})

        # Absent and explicit null are one answer, and neither adds a byte.
        m_null = _write(tmp, "null.json",
                        {"meta": {"ado": {"conventions": BOARD,
                                          "fields": None}}})
        _, out_null = _run([m_null, "--item", item_good])
        _, out_absent = _run([m_std, "--item", item_good])
        # The manifest path is IN the message, so the two are compared with it
        # normalised away - the claim is about the merge lines, not about which
        # file was named.
        check("ci19 an absent block and an explicit null print the SAME thing, "
              "and neither prints a merge line - which is what 'today's "
              "behaviour exactly' means where a reader can see it: %r"
              % (out_null.strip()[:50],),
              out_null.replace(m_null, "<m>") == out_absent.replace(m_std, "<m>")
              and out_absent.count("MERGED") == 0
              and out_null.count("MERGED") == 0)

        # A malformed template is the config's fault, not the item's.
        m_ro = _write(tmp, "ro.json",
                      {"meta": {"ado": {"conventions": BOARD,
                                        "fields": {"Task": {
                                            "System.Parent": 7}}}}})
        check("ci20 a meta.ado.fields naming a readOnly field is exit 2 and "
              "specifically NOT 1: a 1 says the ITEM does not belong on the "
              "board, and a config we refused to apply is not the item's fault",
              M.main([m_ro, "--item", item_good]) == 2)
        m_reserved = _write(tmp, "reserved.json",
                            {"meta": {"ado": {"fields": {"Task": {
                                "System.Title": "hijack"}}}}})
        check("ci21 ...and a template naming a field the connector maps is the "
              "same refusal, rather than a silent 0 on a board with no "
              "conventions at all - the two blocks are graded independently",
              M.main([m_reserved, "--item", item_good]) == 2)

        # --- F106: --item and --fetched over the SAME bytes -----------------
        # The row is the one measured live (`test-audit-lab/DC application` work
        # item #121, parent #101): top-level keys `fields` and `id`, the parent
        # INSIDE `fields`, no REST marker anywhere. This is what
        # `/audit:sync status` step 5 hands the gate, and feeding it to --item
        # produced "must hang under a parent work item, and this one carries
        # none" about an item whose parent is set.
        ROW = {"id": 121,
               "fields": {"System.Parent": 101,
                          "System.WorkItemType": "Issue",
                          "System.Title": "Add the audit trail",
                          "System.State": "To Do",
                          "System.Tags": "audit-plugin"}}
        _b121 = {"requireParent": True,
                 "requiredFields": {"Issue": ["System.Title"]},
                 "tagVocabulary": {"*": ["audit-plugin"]}}
        m_121 = _write(tmp, "board121.json",
                       {"meta": {"ado": {"conventions": _b121}}})
        row_one = _write(tmp, "row.json", ROW)
        row_list = _write(tmp, "rows.json", [ROW])
        # A board the SAME row fails, so the wording and the count cases below
        # have a run with findings in it to read. Asserting "no create verdict"
        # over a conforming run proves nothing: there is no verdict line there
        # to be wrong, and a mutation that appended "do NOT create this item" to
        # the violation line survived exactly that version of the case.
        _needs121 = {"requiredFields": {
                         "Issue": ["Microsoft.VSTS.Scheduling.RemainingWork"]},
                     "descriptionMustContain": {"Issue": ["Done when"]}}
        m_needs = _write(tmp, "needs121.json",
                         {"meta": {"ado": {"conventions": _needs121}}})
        code_n, out_n = _run([m_needs, "--fetched", row_one])

        check("ci22 the batched row a real fetch produces is refused as the "
              "wrong SHAPE (2) by --item even though it carries no REST marker "
              "- the marker was never the tell, and F106 is the shape that "
              "slipped past it",
              M.main([m_121, "--item", row_one]) == 2)
        code_f, out_f = _run([m_121, "--fetched", row_one])
        check("ci23 ...while --fetched grades the SAME bytes and the parent "
              "finding is gone: the verdict was undone by translating the "
              "payload, not by loosening the rule: %r" % (out_f.strip()[:70],),
              code_f == 0 and out_f.count("conforms") == 1
              and "carries none" not in out_f)
        check("ci24 ...and a run that DOES find violations still delivers no "
              "CREATE verdict, because nobody is creating an item that is "
              "already on the board - read over the failing run, since the "
              "clean one has no verdict line to get wrong: %r"
              % (out_n.strip().splitlines()[:1],),
              out_n.count("violation(s)") == 1 and "do NOT create" not in out_n
              and "do NOT create" not in out_f)
        check("ci25 ...closing with the line `status` step 5 prints, so the "
              "count comes from the command rather than from prose that has to "
              "tally it: %r" % (out_f.strip().splitlines()[-1:],),
              out_f.count("conventions: 1 of 1 linked item(s) conform") == 1)
        check("ci26 the item LIST goes to --fetched, and handing it to --item is "
              "a 2 rather than a conformance verdict about a list",
              M.main([m_121, "--item", row_list]) == 2
              and M.main([m_121, "--fetched", row_list]) == 0)

        # THE SILENT HALF, over the board defined above. `requiredFields` and
        # `descriptionMustContain` are both keyed by the work item type, so on
        # the untranslated shape they checked NOTHING - the row came back with
        # one violation (a parent it has) and none of the rules the board
        # actually cares about. Both directions are asserted over one row: it
        # conforms to `_b121` and fails this one.
        check("ci27 the type-scoped rules really RUN on a fetched row now - both "
              "of them fire on the item that fails both, where the untranslated "
              "payload passed them in silence: %r" % (out_n.strip()[:60],),
              code_n == 1 and out_n.count("FINDING:") == 2
              and out_n.count("RemainingWork") == 1
              and out_n.count("Done when") == 1)

        # A row the gate cannot read is a ROW, not a skip, and not a pass.
        rows_mixed = _write(tmp, "mixed.json",
                            [ROW, {"id": 123,
                                   "fields": {"System.Title": "no type here"}}])
        code_m, out_m = _run([m_121, "--fetched", rows_mixed])
        check("ci28 a row whose payload carries no System.WorkItemType is NAMED "
              "and counted apart, never dropped and never counted as "
              "conforming: %r" % (out_m.strip().splitlines()[-1:],),
              out_m.count("NOT GRADED") == 2
              and out_m.count("conventions: 1 of 2 linked item(s) conform") == 1)
        check("ci29 ...and it takes the exit code to 2, because a row nothing "
              "graded is a missing basis rather than a milder verdict",
              code_m == 2)

        # An empty payload must not read as a clean board.
        rows_none = _write(tmp, "none.json", [])
        code_e, out_e = _run([m_121, "--fetched", rows_none])
        check("ci30 an empty fetched payload SAYS that nothing was checked "
              "rather than printing a clean count nobody could act on: %r"
              % (out_e.strip()[:60],),
              code_e == 0 and "nothing was checked" in out_e
              and "conforms" not in out_e)

        # The PARTIAL payload is refused by name: `--json` omits a chunk that
        # timed out, so grading it would report a whole board from a fetch that
        # lost part of it.
        partial = _write(tmp, "partial.json",
                         {"items": [ROW],
                          "failures": [{"status": "timed_out"}]})
        check("ci31 `fetch-ado-items.py --json` is refused (2) and `--out` named "
              "instead - a chunk that timed out is simply absent from `items`, "
              "and grading that reads as a clean board for exactly those ids",
              M.main([m_121, "--fetched", partial]) == 2)

        # meta.ado.fields is a CREATE template and is NOT merged here.
        _tpl121 = {"Issue": {"Microsoft.VSTS.Scheduling.RemainingWork": 3}}
        m_tpl = _write(tmp, "tpl121.json",
                       {"meta": {"ado": {"conventions": {"requiredFields": {
                           "Issue": [
                               "Microsoft.VSTS.Scheduling.RemainingWork"]}},
                           "fields": _tpl121}}})
        item_issue = _write(tmp, "issue.json",
                            {"type": "Issue", "fields": {"System.Title": "x"}})
        check("ci32 --fetched does NOT merge meta.ado.fields, and the pair is "
              "the proof: the create path PASSES because the template will be "
              "sent, while the board row is refused because the board really "
              "does not carry that field - merging there would grade a fiction",
              M.main([m_tpl, "--item", item_issue]) == 0
              and M.main([m_tpl, "--fetched", row_one]) == 1)

        check("ci33 exactly one input flag is required: naming both is a usage "
              "error rather than a guess about which shape was meant",
              M.main([m_121, "--item", row_one, "--fetched", row_one]) == 2
              and M.main([m_121]) == 2)
        # The exit code alone cannot see this: a filename of `--json` fails to
        # open and produces the same 2. So the PARSE is asserted, and `-` is
        # asserted in the same case because it is a VALUE (stdin) - a mutation
        # that refused every dash-leading value would otherwise look correct.
        check("ci34 ...and a flag whose value is the NEXT flag is refused at "
              "parse time rather than opened as a file called `--json`, while "
              "`-` stays a value",
              M.flag_value([m_121, "--fetched", "--json"], "--fetched") is None
              and M.flag_value([m_121, "--fetched", "-"], "--fetched") == "-"
              and M.main([m_121, "--fetched", "--json"]) == 2)
        _, out_ns = _run([m_none, "--fetched", row_one])
        check("ci35 a board with no conventions gets the same 'nothing was "
              "checked' sentence on this path as on the other one, so the two "
              "zeroes stay apart here too: %r" % (out_ns.strip()[:50],),
              "no standard" in out_ns and "conforms" not in out_ns)
        _, out_j = _run([m_121, "--fetched", rows_mixed, "--json"])
        _payload = json.loads(out_j)
        check("ci36 --json carries the same split a script has to read: which "
              "rows were graded, which were not, and how many conform",
              _payload["conforming"] == 1 and _payload["graded"] == 1
              and _payload["notGradeable"] == 1 and _payload["total"] == 2
              and _payload["conforms"] is False)

        # --- F120: the one kind push creates without a parent ---------------
        # BOARD requires a parent, and this is the payload `/audit:sync push
        # bugs` builds: a bug create, with no `parent` key, because push hangs
        # phases and tasks and names no third kind. It used to come back "must
        # hang under a parent work item, and this one carries none" — exit 1,
        # at create time, on a board that could then never receive a bug.
        BUGP = {"type": "Bug", "fields": {"System.Description": "Panel drops it.",
                                          "System.Tags": "type:refactor"}}
        item_bug = _write(tmp, "bug.json", BUGP)
        code_b, out_b = _run([m_std, "--item", item_bug])
        check("ci37 a bug create is no longer refused for the parent push was "
              "never going to supply - the gate reads requireParent as every "
              "item THIS PLUGIN PARENTS, which is what push implements: %r"
              % (out_b.strip()[-60:],),
              code_b == 0 and "carries none" not in out_b)
        check("ci38 ...and it SAYS the rule was skipped rather than passing in "
              "silence: this board wants a parent on every card and cannot have "
              "one here, which is the sentence its operator is owed: %r"
              % (out_b.strip()[:60],),
              out_b.count("NOTE: `requireParent` was NOT applied") == 1
              and out_b.count("NOTE:") == 1)
        # THE SECOND DIRECTION, and the only case that fails if the exemption
        # becomes unconditional: a kind push DOES parent is refused as before,
        # over the same board and the same missing parent.
        item_noparent = _write(tmp, "noparent.json",
                               {"type": "Task",
                                "fields": {"System.Description": "Done when: x.",
                                           "System.Tags": "type:refactor"}})
        code_t, out_t = _run([m_std, "--item", item_noparent])
        check("ci39 ...while a TASK with no parent on that same board is still "
              "refused, and draws no NOTE - the narrowing is by KIND, not the "
              "rule giving up: %r" % (out_t.strip()[-50:],),
              code_t == 1 and out_t.count("carries none") == 1
              and out_t.count("NOTE:") == 0)
        _, out_bj = _run([m_std, "--item", item_bug, "--json"])
        _pj = json.loads(out_bj)
        check("ci40 --json carries it as `parentRuleExemption` and NOT as a "
              "violation, so a script reading `conforms` gets the verdict and "
              "one reading this gets the whole of it",
              _pj.get("conforms") is True and _pj.get("violations") == []
              and "requireParent" in (_pj.get("parentRuleExemption") or ""))
        _, out_tj = _run([m_std, "--item", item_noparent, "--json"])
        check("ci41 ...and it is null for the kind that IS graded, which is what "
              "a script reads to tell 'no rule was skipped' from 'the key is "
              "not there'",
              json.loads(out_tj).get("parentRuleExemption") is None)
        # The exempt TYPE NAME comes from the board, not from this plugin.
        m_renamed = _write(tmp, "renamed.json",
                           {"meta": {"ado": {"conventions": BOARD,
                                             "types": {"bug": "Defect"}}}})
        item_defect = _write(tmp, "defect.json", dict(BUGP, type="Defect"))
        check("ci42 `meta.ado.types.bug` names the exempt type, so a board that "
              "renamed it exempts the new name and refuses the old one - both "
              "halves, since a baked-in constant passes the first",
              M.main([m_renamed, "--item", item_defect]) == 0
              and M.main([m_renamed, "--item", item_bug]) == 1)
        # ...and the exemption does not switch the gate off for that kind.
        m_bugrules = _write(tmp, "bugrules.json",
                            {"meta": {"ado": {"conventions": dict(
                                BOARD, **{"descriptionMustContain": {
                                    "Bug": ["Repro:"]}})}}})
        code_r, out_r = _run([m_bugrules, "--item", item_bug])
        check("ci43 every OTHER rule still grades that bug - the skeleton fires "
              "on the payload ci37 passes, so one rule narrowed and the gate "
              "did not stop reading the kind: %r" % (out_r.strip()[:60],),
              code_r == 1 and out_r.count("FINDING:") == 1
              and "Repro:" in out_r)
        # The --fetched side of the same rule, over a Bug row already on the
        # board with no System.Parent. Counted, not merely found: the NOTE has
        # to appear once and the row still has to be tallied as conforming.
        bug_row = _write(tmp, "bugrow.json",
                         [{"id": 77,
                           "fields": {"System.WorkItemType": "Bug",
                                      "System.Title": "already there",
                                      "System.Description": "x",
                                      "System.Tags": "type:refactor"}}])
        code_fb, out_fb = _run([m_std, "--fetched", bug_row])
        check("ci44 a Bug already ON the board with no parent is reported as "
              "conforming with the same NOTE, not as a violation - this "
              "connector could never have parented that card either: %r"
              % (out_fb.strip().splitlines()[-1:],),
              code_fb == 0 and out_fb.count("NOTE:") == 1
              and out_fb.count("conventions: 1 of 1 linked item(s) conform") == 1)

        # The rule is READ from the manifest, not baked in.
        m_other = _write(tmp, "other.json", {"meta": {"ado": {"conventions": {
            "descriptionMustContain": {"Task": ["Acceptance"]}}}}})
        code, out = _run([m_other, "--item", item_good])
        check("ci13 the standard applied is the one in THAT manifest: an item "
              "that conforms to one board is refused by another, which is what "
              "makes this a board property rather than a plugin opinion: %r"
              % (out.strip()[:60],), code == 1 and "Acceptance" in out)
    finally:
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_check_ado_item.py --selftest\n")
    raise SystemExit(2)
