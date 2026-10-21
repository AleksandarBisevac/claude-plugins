#!/usr/bin/env python3
"""
The cases for `_clause_coverage.py` - whether a writer answered every clause the
task owes, and whether the path an answer cites is one the diff touches.

- **The numbering is one list.** `cc1` builds a task whose description numbers its
  own steps BEFORE the Acceptance marker and asserts the clauses come out as the
  `tests.add` entries first, then only the items after the marker. A numbering
  that read every `(n)` in the description, or put the acceptance items first,
  would number a different list than the one the writer was asked to answer.
- **Each gap is asserted as the exact set of clause numbers.** `cc3` omits clause 4
  and asserts the gap is `[4]` - not that clause 4 is among the gaps, which a check
  reporting every clause would also satisfy. `cc2` is the other direction: a
  complete answer has NO gap, so a check that always reported one goes red there.
- **A missing or unreadable answer is a gap of every clause.** `cc5` pins four
  shapes of it, among them an object that is present but not the message's last
  thing, because the closing line asks for the object LAST and an object in the
  middle of prose is a quotation, not the answer.
- **A cited path is read against the diff, nothing else.** `cc4` cites a file the
  diff does not touch and asserts the gap names it; `cc8` writes the same file
  three ways (`./x`, an absolute path under the tree, backslashes) and asserts all
  three are the file the diff touches, because a spelling that made a delivered
  clause look undelivered would resume a writer that had done the work.
- **`delivered: false` with a reason is an answer.** The writer's own words stay a
  claim; `cc7` asserts the clause is covered AND is reported as declined, so the
  drive can print it rather than let it pass unmentioned.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _clause_coverage as M                       # noqa: E402


DESCRIPTION = ("Do the thing. Steps: (1) read it, (2) write it. "
               "Acceptance: (1) the first item; (2) the second item.")


def _task():
    return {"description": DESCRIPTION,
            "tests": {"add": ["tests/a.py: one", "tests/b.py: two", "tests/c.py: three"]}}


def _answer(**entries):
    return "All done.\n" + json.dumps(entries, sort_keys=True)


def _delivered(path, line=3):
    return {"delivered": True, "file": path, "line": line}


def _full(paths):
    """A complete answer for five clauses, each citing the path at its index."""
    return dict((str(i + 1), _delivered(p)) for i, p in enumerate(paths))


PATHS = ["tests/a.py", "tests/b.py", "tests/c.py", "src/x.py", "src/y.py"]


def _gap_ns(result):
    return [g["n"] for g in result["gaps"]]


def _numbering_cases(check):
    clauses = M.task_clauses(_task())
    check("cc1 three tests.add entries then two Acceptance items are five clauses "
          "numbered one to five in that order, and the steps the description "
          "numbers before its Acceptance marker are not clauses: %r"
          % ([(c["n"], c["kind"]) for c in clauses],),
          [(c["n"], c["kind"]) for c in clauses]
          == [(1, "tests.add"), (2, "tests.add"), (3, "tests.add"),
              (4, "acceptance"), (5, "acceptance")]
          and clauses[3]["text"].startswith("the first item")
          and clauses[4]["text"].startswith("the second item"))


def _verdict_cases(check):
    clauses = M.task_clauses(_task())

    whole = M.check(clauses, _answer(**_full(PATHS)), PATHS)
    check("cc2 an answer covering all five clauses with every cited path in the "
          "diff is covered, with no gap and nothing declined (the allow case: a "
          "check that always reported a gap goes red here): %r" % (whole,),
          whole["covered"] is True and whole["gaps"] == []
          and whole["declined"] == [] and whole["owed"] == 5)

    partial = _full(PATHS)
    del partial["4"]
    omitted = M.check(clauses, _answer(**partial), PATHS)
    check("cc3 an answer omitting clause 4 is a gap naming exactly clause 4 as "
          "unanswered: %r" % (omitted,),
          omitted["covered"] is False and _gap_ns(omitted) == [4]
          and omitted["gaps"][0]["reason"] == "no-answer")

    outside = M.check(clauses, _answer(**_full(PATHS)),
                      [p for p in PATHS if p != "src/y.py"])
    check("cc4 a delivered answer citing a path the diff does not touch is a gap "
          "naming that clause and that path, and only that clause: %r"
          % (outside["gaps"],),
          outside["covered"] is False and _gap_ns(outside) == [5]
          and outside["gaps"][0]["reason"] == "path-not-in-diff"
          and outside["gaps"][0]["path"] == "src/y.py")

    good = json.dumps(_full(PATHS), sort_keys=True)
    shapes = [
        ("no JSON at all", "I finished everything and it all passes."),
        ("an unparsable object", 'Done.\n{"1": {"delivered": true, '),
        ("an object followed by more prose", "%s\nand then I kept talking." % (good,)),
        ("an object followed by prose that ends in braces",
         "%s\nlater I wrote {x}" % (good,)),
        ("a JSON array", "Done.\n[1, 2, 3]"),
        ("an empty message", ""),
    ]
    results = [(label, M.check(clauses, text, PATHS)) for label, text in shapes]
    check("cc5 no JSON, unparsable JSON, an object that is not the last thing "
          "(whether the prose after it ends in a brace or not), an array and an "
          "empty message are each a gap of EVERY clause, never covered: %r" % ([(label, r["covered"], _gap_ns(r)) for label, r in results],),
          all(r["covered"] is False and _gap_ns(r) == [1, 2, 3, 4, 5]
              and all(g["reason"] == "no-json" for g in r["gaps"])
              for _label, r in results))

    fenced = M.check(clauses, "Done.\n```json\n%s\n```\n" % (good,), PATHS)
    check("cc5b an object closed by a code fence is still the message's last "
          "object - the fence is not text the writer answered with: %r"
          % (fenced["gaps"],), fenced["covered"] is True)

    broken = _full(PATHS)
    broken["1"] = "yes, delivered"
    broken["2"] = {"delivered": True, "line": 4}
    broken["3"] = {"delivered": True, "file": "tests/c.py", "line": True}
    broken["4"] = {"delivered": False}
    broken["5"] = {"delivered": "true", "file": "src/y.py", "line": 2}
    malformed = M.check(clauses, _answer(**broken), PATHS)
    check("cc6 a string where an object belongs, a delivered answer with no file, "
          "a boolean standing as a line number, a not-delivered answer with no "
          "reason and a non-boolean delivered are each a malformed gap: %r"
          % ([(g["n"], g["reason"]) for g in malformed["gaps"]],),
          _gap_ns(malformed) == [1, 2, 3, 4, 5]
          and all(g["reason"] == "malformed" for g in malformed["gaps"]))

    zero_line = _full(PATHS)
    zero_line["1"] = _delivered("tests/a.py", 0)
    check("cc6b a line number below one cites no line: %r"
          % (M.check(clauses, _answer(**zero_line), PATHS)["gaps"],),
          _gap_ns(M.check(clauses, _answer(**zero_line), PATHS)) == [1])

    declined = _full(PATHS)
    declined["3"] = {"delivered": False, "reason": "needs the browser"}
    said = M.check(clauses, _answer(**declined), PATHS)
    check("cc7 a not-delivered answer that gives its reason is an answer: the "
          "clause is covered, and it is listed as declined so the drive can say "
          "so (the mutation this is for: declined counted as a gap resumes a "
          "writer that already told the truth): %r" % (said,),
          said["covered"] is True and said["gaps"] == [] and said["declined"] == [3])

    extra = _full(PATHS)
    extra["9"] = _delivered("src/z.py")
    unknown = M.check(clauses, _answer(**extra), PATHS)
    check("cc7b an entry for a clause the task does not number is neither a gap "
          "nor silently dropped: it is reported as unknown: %r" % (unknown,),
          unknown["covered"] is True and unknown["unknown"] == ["9"])


def _path_cases(check):
    clauses = M.task_clauses(_task())
    root = os.path.abspath(os.path.join(os.sep, "work", "tree"))
    spelled = _full(PATHS)
    spelled["1"] = _delivered("./tests/a.py")
    spelled["2"] = _delivered(os.path.join(root, "tests", "b.py"))
    spelled["3"] = _delivered("tests\\c.py")
    result = M.check(clauses, _answer(**spelled), PATHS, root=root)
    check("cc8 `./x`, an absolute path under the tree and a backslashed path are "
          "each the file the diff touches: %r" % (result["gaps"],),
          result["covered"] is True)

    elsewhere = _full(PATHS)
    elsewhere["2"] = _delivered(os.path.abspath(os.path.join(os.sep, "other", "tests", "b.py")))
    away = M.check(clauses, _answer(**elsewhere), PATHS, root=root)
    check("cc8b an absolute path OUTSIDE the tree is not the diff's file even "
          "though its tail matches: %r" % (away["gaps"],),
          _gap_ns(away) == [2] and away["gaps"][0]["reason"] == "path-not-in-diff")


def _empty_cases(check):
    none = M.check(M.task_clauses({"description": "no list here", "tests": {}}),
                   "nothing to answer", [])
    check("cc9 a task that numbers no clause owes no answer: covered, and the "
          "result says it owed nothing rather than that everything was answered: %r"
          % (none,),
          none["covered"] is True and none["owed"] == 0 and none["gaps"] == [])


def _resume_cases(check):
    clauses = M.task_clauses(_task())
    partial = _full(PATHS)
    del partial["4"]
    partial["5"] = _delivered("src/gone.py")
    result = M.check(clauses, _answer(**partial), PATHS)
    text = M.resume_text(result, clauses)
    check("cc10 the resume text names each uncovered clause with its number, its "
          "words and what was wrong, names the path that is not in the diff, and "
          "does not mention a clause that was answered: %r" % (text,),
          "clause 4" in text and "the first item" in text
          and "clause 5" in text and "src/gone.py" in text
          and "clause 1" not in text and "tests/a.py" not in text)
    check("cc10b a covered result has no resume text - an empty string, so a "
          "caller testing truthiness cannot resume a writer with nothing to say: %r"
          % (M.resume_text(M.check(clauses, _answer(**_full(PATHS)), PATHS), clauses),),
          M.resume_text(M.check(clauses, _answer(**_full(PATHS)), PATHS),
                        clauses) == "")


def _cases(check):
    _harness.stage(check, "cc-number", _numbering_cases)
    _harness.stage(check, "cc-verdict", _verdict_cases)
    _harness.stage(check, "cc-path", _path_cases)
    _harness.stage(check, "cc-empty", _empty_cases)
    _harness.stage(check, "cc-resume", _resume_cases)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__clause_coverage.py --selftest\n")
    raise SystemExit(2)
