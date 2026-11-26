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
- **The reading drops nothing unsaid, and the expectation is not the reader's.**
  `cq8` builds descriptions from segments whose role it knows - items, parts left
  out, marker and numbering text, disturbances - and compares the reading and the
  line with what it built; the conservation subtraction counts the region's
  characters off the text, never off the reader's spans. `cq12` is the quiet twin
  of every clause: a plain list printing anything goes red there.
- **A bare marker word is prose unless a list numbered one opens under it.** `cw9`
  holds the lines that only begin with the word and must print nothing, `cw10`
  the heading and label over a list from one that the wide reading still takes;
  `cw11` generates plain lists whose prose holds the word and takes its
  expectation from the construction - which wrapped line begins with which word -
  never from the reader.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import math
import os
import re
import sys
import time

import _harness                                   # sets sys.path for scripts/ + hooks/
from _output import safe_stdio, some_of            # noqa: E402
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


def _reading(description):
    """(shape, items) of one description, as the clause reader reads it."""
    got = M.acceptance_reading(description)
    return got["shape"], got["items"]


def _shape_cases(check):
    """The shapes an Acceptance list is read in, and the silences.

    Every fixture is built so that a reader with one rule missing reads a
    DIFFERENT list: the line-start anchor dropped opens an item at a version
    number, the sequence rule dropped opens one at a nested line or a year,
    the unnumbered shape dropped reads prose as nothing, a whitespace tail read
    as text reads a blank marker as one item, and shapes allowed to mix read a
    parenthesised list's inner `1.` line as an item of its own.
    """
    md = "Do it.\nAcceptance:\n1. the first item\n2. the second item\n3. the third\n"
    check("cs1 a Markdown numbered list after the marker is one item per number, "
          "each the text after its number with surrounding whitespace removed, "
          "read by the line-start shape: %r" % (_reading(md),),
          _reading(md) == ("line-numbered",
                           ["the first item", "the second item", "the third"])
          and M.acceptance_items(md)
          == ["the first item", "the second item", "the third"])

    paren_close = "Acceptance:\n1) one thing\n2) another thing"
    check("cs1b a number closed by a parenthesis at a line start is the same "
          "shape: %r" % (_reading(paren_close),),
          _reading(paren_close) == ("line-numbered", ["one thing", "another thing"]))

    crlf = "Acceptance:\r\n1. first\r\n2. second\r\n"
    check("cs1c Windows line endings read the same items, with no carriage "
          "return left in any item: %r" % (_reading(crlf),),
          _reading(crlf) == ("line-numbered", ["first", "second"]))

    same_line = "Acceptance: 1. first\n2. second"
    check("cs1d a `1.` right after the marker on its own line opens item one: "
          "the marker ends a label, not a sentence: %r" % (_reading(same_line),),
          _reading(same_line) == ("line-numbered", ["first", "second"]))

    version_mid = ("Acceptance:\n1. bump to version 2. then rebuild\n"
                   "2. the decimal 3.5 stays as written")
    check("cs2 a number and a full stop in the MIDDLE of an item's line opens "
          "nothing - `2.` inside `version 2. then` stays inside item one (the "
          "line-start anchor's case): %r" % (_reading(version_mid),),
          _reading(version_mid)
          == ("line-numbered", ["bump to version 2. then rebuild",
                                "the decimal 3.5 stays as written"]))

    version_prose = ("Acceptance: ruff 1. and vermin 2. are both clean, "
                     "and coverage holds at 2.5 percent.")
    check("cs2b a marker followed by prose whose numbers all sit mid-sentence "
          "is one unnumbered item - no number opened anything: %r"
          % (_reading(version_prose),),
          _reading(version_prose)
          == ("unnumbered", ["ruff 1. and vermin 2. are both clean, and "
                             "coverage holds at 2.5 percent."]))

    nested = ("Acceptance:\n1. the first, which lists\n3. an aside that is not "
              "next\n2. the second")
    check("cs3 a line-start number that is NOT the next in sequence stays "
          "inside the item it sits in (the sequence rule's case): %r"
          % (_reading(nested),),
          _reading(nested)
          == ("line-numbered", ["the first, which lists\n3. an aside that is "
                                "not next", "the second"]))

    from_two = "Acceptance:\n2. the second\n3. the third"
    check("cs3b a list starting at 2 opens no numbered item - the first must "
          "be 1 - so it is read whole, as ONE unnumbered item, never as "
          "nothing: %r" % (_reading(from_two),),
          _reading(from_two) == ("unnumbered", ["2. the second\n3. the third"]))

    year = ("Acceptance: the release holds the fix it shipped in\n"
            "2026. The sweep is green.")
    check("cs3c a sentence that begins a line with a year and a full stop "
          "opens nothing; the text is one unnumbered item: %r" % (_reading(year),),
          _reading(year)
          == ("unnumbered", ["the release holds the fix it shipped in\n"
                             "2026. The sweep is green."]))

    year_twin = ("Acceptance: the release holds the fix it shipped in\n"
                 "1. The sweep is green.")
    check("cs3d TWIN of cs3c: the same text with `1.` at the line start opens "
          "item one there, so the year's silence is the sequence rule and not "
          "a reader that ignores line starts: %r" % (_reading(year_twin),),
          _reading(year_twin) == ("line-numbered", ["The sweep is green."]))

    paren_wins = ("Acceptance:\n(1) the list reads:\n1. an inner line\n"
                  "(2) the second")
    shape, items = _reading(paren_wins)
    check("cs4 a parenthesised list whose first item holds a line-start `1.` "
          "is read as parenthesised: two items, the inner line inside the "
          "first (the shapes do not mix): %r" % ((shape, items),),
          shape == "parenthesised" and len(items) == 2
          and "1. an inner line" in items[0]
          and items[1].startswith("the second"))

    plain = "Acceptance: the full sweep is green; ruff and vermin are clean."
    check("cs5 a marker followed by unnumbered text is exactly ONE item holding "
          "that text: %r" % (_reading(plain),),
          _reading(plain)
          == ("unnumbered",
              ["the full sweep is green; ruff and vermin are clean."]))

    padded = "Acceptance:\n\n  line one,\n\n  line two  \n\t"
    check("cs5b the unnumbered item is the text with SURROUNDING whitespace "
          "removed and nothing else changed - the inner blank line and indent "
          "stay: %r" % (_reading(padded),),
          _reading(padded) == ("unnumbered", ["line one,\n\n  line two"]))

    blank = "Do it.\nAcceptance:  \n\t\r\n  "
    check("cs6 a marker followed by nothing but whitespace yields NO item and "
          "no shape (the twin of cs5: a reader taking whitespace as text "
          "reads one item here): %r" % (_reading(blank),),
          _reading(blank) == (None, []) and M.acceptance_items(blank) == [])
    check("cs6b no marker at all yields no item and no shape: %r"
          % (_reading("no list here (1) a (2) b"),),
          _reading("no list here (1) a (2) b") == (None, []))

    paren = DESCRIPTION
    check("cs7 the parenthesised form reads as before and names its shape: %r"
          % (_reading(paren),),
          _reading(paren)[0] == "parenthesised"
          and M.acceptance_items(paren) == _reading(paren)[1]
          and len(_reading(paren)[1]) == 2)

    clauses = M.task_clauses({"description": md, "tests": {"add": ["tests/a.py: x"]}})
    check("cs8 task_clauses numbers a Markdown list's items after the tests.add "
          "entries, as acceptance clauses: %r"
          % ([(c["n"], c["kind"], c["text"]) for c in clauses],),
          [(c["n"], c["kind"], c["text"]) for c in clauses]
          == [(1, "tests.add", "tests/a.py: x"),
              (2, "acceptance", "the first item"),
              (3, "acceptance", "the second item"),
              (4, "acceptance", "the third")])


def _reading_line_cases(check):
    """The one line `add` and `scope` print about how acceptance was read."""
    md = "Acceptance:\n1. the first\n2. the second"
    plain = "Acceptance: the sweep is green."
    lines = [M.reading_line(md), M.reading_line(plain)]
    check("cs9 the reading line names the item count and the shape for a "
          "line-numbered list and for unnumbered text: %r" % (lines,),
          lines[0].startswith("acceptance: 2 items") and "numbered" in lines[0]
          and lines[1].startswith("acceptance: 1 item") and "unnumbered" in lines[1]
          and all("\n" not in ln for ln in lines))
    quiet = [M.reading_line(DESCRIPTION), M.reading_line("no marker"),
             M.reading_line("Acceptance:  ")]
    check("cs9b the parenthesised form and no marker print nothing - an empty "
          "string, so a caller printing it only when truthy adds no line - and "
          "a marker followed by nothing says no clause was read: %r" % (quiet,),
          quiet[:2] == ["", ""] and quiet[2].startswith("acceptance: no clause "
                                                        "was read"))


def _marker_cases(check):
    """Where the marker counts: opening a line or a sentence, outside a code
    fence, never inside a sentence or behind a backtick or a quote.

    Each deny row has its allow twin, so a reader that took the marker
    anywhere again (the deny rows go red) is told apart from one that took it
    nowhere (the twins go red).
    """
    one_line = ("Do it. Acceptance: (1) a passes (2) b passes. Notes: see the "
                "Acceptance: list above.")
    md_then = ("Do it.\nAcceptance:\n1. a passes\n2. b passes\n\nNotes: see the "
               "Acceptance: list above.")
    got = [_reading(one_line), _reading(md_then)]
    check("cr1 a marker mentioned inside a sentence opens no list, and the real "
          "list before it is read - in both shapes: %r" % (got,),
          got[0][0] == "parenthesised" and len(got[0][1]) == 2
          and got[0][1][0] == "a passes"
          and got[1][0] == "line-numbered" and len(got[1][1]) == 2
          and got[1][1][0] == "a passes" and got[1][1][1].startswith("b passes"))

    ticked = "Teach the reader that an `Acceptance:` list numbered `1.` is read too."
    quoted = "The brief must say \"Acceptance: see below\" verbatim.\n"
    check("cr2 a marker in backticks or inside a quotation is no marker: no "
          "shape and no item, and the line says no clause was read and names "
          "the mention: %r"
          % ([_reading(ticked), _reading(quoted), M.reading_line(ticked)],),
          _reading(ticked) == (None, []) and _reading(quoted) == (None, [])
          and all("no clause was read" in M.reading_line(d)
                  and "not read as a marker" in M.reading_line(d)
                  for d in (ticked, quoted)))

    sentence = "Do it. Acceptance: the sweep is green."
    bold = "Do it. **Acceptance:** (1) a (2) b"
    check("cr2b TWIN of cr2: a marker that opens a sentence part-way along a "
          "line still counts, bare or in bold: %r"
          % ([_reading(sentence), _reading(bold)],),
          _reading(sentence) == ("unnumbered", ["the sweep is green."])
          and _reading(bold) == ("parenthesised", ["a", "b"]))

    fenced = ("Do it.\nAcceptance:\n1. a\n2. b\n\nExample of a bad description:\n"
              "```\nAcceptance: none\n```\n")
    check("cr3 a marker inside a code fence after the real list opens nothing: "
          "the list is read, the reading line names no second marker, and it "
          "names the fenced word as a mention: %r"
          % ((_reading(fenced), M.reading_line(fenced)),),
          _reading(fenced)[0] == "line-numbered"
          and _reading(fenced)[1][0] == "a" and len(_reading(fenced)[1]) == 2
          and "Acceptance markers" not in M.reading_line(fenced)
          and '1 mention of the marker word not read as a marker, first '
              '"Acceptance: none"' in M.reading_line(fenced))

    bold_empty = "Do it.\n\n**Acceptance:**"
    heading_empty = "## Acceptance:\n\n## Notes\nnothing here"
    check("cr4 a bold marker with nothing after it, and a heading marker "
          "followed by another heading, yield no item - neither the closing "
          "asterisks nor the next section: %r"
          % ([_reading(bold_empty), _reading(heading_empty)],),
          _reading(bold_empty) == (None, []) and _reading(heading_empty) == (None, []))

    bold_list = "**Acceptance:**\n1. a\n2. b"
    heading_list = "## Acceptance:\n1. a\n2. b\n\n## Notes\nnothing here"
    check("cr4b TWIN of cr4: a bold marker and a heading marker over a real "
          "list read that list, and the heading after it ends the last item: %r"
          % ([_reading(bold_list), _reading(heading_list)],),
          _reading(bold_list) == ("line-numbered", ["a", "b"])
          and _reading(heading_list) == ("line-numbered", ["a", "b"]))


def _two_marker_cases(check):
    """More than one line-opening marker: the reading says so, and takes the
    one holding a numbered list when exactly one does, else the last."""
    first_holds = ("Acceptance:\n1. a passes\n2. b passes\n\n"
                   "Acceptance: see the list above.")
    line = M.reading_line(first_holds)
    check("cr5 two line-opening markers, the first holding the numbered list: "
          "that list is read, and the reading line names both markers and why "
          "it took the first: %r" % ((_reading(first_holds), line),),
          _reading(first_holds) == ("line-numbered", ["a passes", "b passes"])
          and "2 Acceptance markers" in line and "numbered list" in line
          and "\n" not in line)

    both_hold = "Acceptance: (1) old a (2) old b\nAcceptance: (1) new a"
    line_b = M.reading_line(both_hold)
    check("cr5b both markers hold a numbered list: the last is read, and the "
          "line says the last was taken: %r" % ((_reading(both_hold), line_b),),
          _reading(both_hold) == ("parenthesised", ["new a"])
          and "2 Acceptance markers" in line_b and "last" in line_b)

    neither = "Acceptance: first prose.\nAcceptance: second prose."
    check("cr5c neither marker holds a numbered list: the last is read as its "
          "one unnumbered item: %r" % (_reading(neither),),
          _reading(neither) == ("unnumbered", ["second prose."])
          and "2 Acceptance markers" in M.reading_line(neither))

    crlf = first_holds.replace("\n", "\r\n")
    check("cr5d Windows line endings read two markers the same: %r"
          % ((_reading(crlf), M.reading_line(crlf)),),
          _reading(crlf) == _reading(first_holds)
          and M.reading_line(crlf) == line)


def _shape_rule_cases(check):
    """A parenthesised number opens an item only at the body's start or after
    whitespace, and when both shapes yield items the one opening first is
    read and the other is named."""
    call = ("Acceptance:\n1. a bad flag ends the script with sys.exit(1)\n"
            "2. the sweep is green\n3. ruff is clean")
    check("cr6 a line-numbered list whose first item ends in a call with a "
          "literal argument is read as all three numbered items, the call "
          "inside item one: %r" % ((_reading(call), M.reading_line(call)),),
          _reading(call) == ("line-numbered",
                             ["a bad flag ends the script with sys.exit(1)",
                              "the sweep is green", "ruff is clean"])
          and M.reading_line(call).startswith("acceptance: 3 items"))

    prose_call = ("Acceptance: the hook ends with sys.exit(1) when refused; the "
                  "sweep is green.")
    check("cr6b a call glued to a word inside unnumbered text opens nothing: "
          "the whole text is one item: %r" % (_reading(prose_call),),
          _reading(prose_call)
          == ("unnumbered", ["the hook ends with sys.exit(1) when refused; the "
                             "sweep is green."]))

    spaced = ("Acceptance:\n1. the function returns (1) for an empty input\n"
              "2. the sweep is green\n3. ruff is clean")
    line = M.reading_line(spaced)
    check("cr6c a `(1)` after a space inside a numbered item does not win: the "
          "list opening first is read, all three items, and the line says the "
          "parenthesised shape would have given one item: %r"
          % ((_reading(spaced), line),),
          _reading(spaced)[0] == "line-numbered" and len(_reading(spaced)[1]) == 3
          and "parenthesised shape would give 1 item" in line)

    starts = ["Acceptance: (1) a\n(2) b", "Acceptance:(1) a (2) b"]
    check("cr6d TWIN of cr6: a `(1)` after whitespace or at the very start of "
          "the body still opens the parenthesised list: %r"
          % ([_reading(s) for s in starts],),
          all(_reading(s) == ("parenthesised", ["a", "b"]) for s in starts))

    substeps = "Acceptance: (1) do:\n1. x\n2. y\n(2) b"
    check("cr6e ALLOW: a parenthesised item holding sub-steps numbered `1.` "
          "`2.` stays one item, and a parenthesised list accounting for the "
          "whole body prints nothing: %r"
          % ((_reading(substeps), M.reading_line(substeps)),),
          _reading(substeps)[0] == "parenthesised"
          and len(_reading(substeps)[1]) == 2
          and "1. x" in _reading(substeps)[1][0]
          and "2. y" in _reading(substeps)[1][0]
          and M.reading_line(substeps) == "")


def _boundary_cases(check):
    """Item boundaries of the line-numbered shape, and what the reading line
    owes when the reading is not the plain one."""
    lead = "Acceptance: the suite is green on python 3.8, and:\n1. a\n2. b"
    line = M.reading_line(lead)
    check("cr7 text between the marker and the first item is left out of "
          "every item, and the line says so, quoting it: %r"
          % ((_reading(lead), line),),
          _reading(lead) == ("line-numbered", ["a", "b"])
          and "in no item" in line and "the suite is green" in line)

    paren_lead = ("Acceptance: the helper prints (1) and nothing else; the sweep "
                  "is green.")
    check("cr7b a parenthesised list with text before its `(1)` is not the "
          "plain reading, so the line is printed: %r"
          % (M.reading_line(paren_lead),),
          "in no item" in M.reading_line(paren_lead)
          and "the helper prints" in M.reading_line(paren_lead))

    restart = "Acceptance:\n1. a\n1. b\n1. c"
    check("cr8 a list numbered `1.` `1.` `1.` is three items, and the line "
          "says the numbering restarts: %r"
          % ((_reading(restart), M.reading_line(restart)),),
          _reading(restart) == ("line-numbered", ["a", "b", "c"])
          and "restart" in M.reading_line(restart))

    nested = ("Acceptance:\n1. the build:\n   1. compiles\n   2. links\n"
              "2. the sweep is green")
    check("cr9 a nested sub-step at a deeper indent opens no item: two items, "
          "the sub-steps inside the first: %r" % (_reading(nested),),
          _reading(nested) == ("line-numbered",
                               ["the build:\n   1. compiles\n   2. links",
                                "the sweep is green"]))

    section = ("Acceptance:\n1. a is green\n2. b is green\n\n## Out of scope\n"
               "Do not touch the panel.\n\nContext: the number is internal.")
    check("cr10 the last item ends at a following heading line: %r"
          % (_reading(section),),
          _reading(section) == ("line-numbered", ["a is green", "b is green"]))

    big = "Acceptance:\n1. a\n" + "9" * 5000 + ". b"
    big_paren = "Acceptance: (1) a (" + "9" * 5000 + ") b"
    try:
        got = [_reading(big), _reading(big_paren), M.reading_line(big)]
        raised = None
    except ValueError as exc:
        got, raised = None, exc
    check("cr11 a digit run at a line start or in parentheses past the "
          "interpreter's integer limit raises nothing and opens no item: %r"
          % ((got, raised),),
          raised is None and got[0][0] == "line-numbered" and len(got[0][1]) == 1
          and got[1][0] == "parenthesised" and len(got[1][1]) == 1)

    md = "Acceptance:\n1. the first\n2. the second"
    check("cr12 the reading line says who is held to the items: the writer on "
          "the headless-writer route (`executor.writerModel` set): %r"
          % (M.reading_line(md),),
          "executor.writerModel" in M.reading_line(md)
          and "headless-writer route" in M.reading_line(md))


def _items(description):
    return M.acceptance_reading(description)["items"]


# The words each clause of the reading line carries, as the line prints them.
# A case asserts the clause by these and its absence by the same words, so a
# clause printed for every description is told apart from one printed never.
_MENTION = "not read as a marker"
_NUMBER = "inside an item, not its opener"
_FENCE = "never closed"
_LEFT_OUT = "is in no item"
_NONE_READ = "no clause was read"


def _measured_cases(check):
    """The descriptions a review measured as read short or not at all with
    nothing printed - each now reads the items a reader counts, or prints a
    line naming what was left out or could be read another way."""
    mention = ("Acceptance:\n(1) a.\n(2) The doc is updated. Acceptance: lists "
               "stay numbered.\n(3) c\n(4) d")
    line = M.reading_line(mention)
    check("cq1 (a) a marker opening a sentence inside item two is a mention: all "
          "four items are read, and the line names the mention, quoted",
          _items(mention) == ["a.", "The doc is updated. Acceptance: lists stay "
                                    "numbered.", "c", "d"]
          and _MENTION in line and '"Acceptance: lists stay numbered."' in line,
          "%r / %r" % (_items(mention), line))

    wrapped = ("Acceptance:\n(1) the reader handles the\nAcceptance: marker "
               "anywhere\n(2) b\n(3) c")
    line = M.reading_line(wrapped)
    check("cq2 (b) a wrapped line opening with the marker is a second marker: "
          "the line names both and quotes the body it did not read as in no item",
          _items(wrapped) == ["the reader handles the"]
          and "2 Acceptance markers" in line and _LEFT_OUT in line
          and '"marker anywhere (2) b (3) c"' in line,
          "%r / %r" % (_items(wrapped), line))

    mid = ["Rules hold as stated - Acceptance: (1) a is true (2) b is true",
           "Build the thing; Acceptance: (1) a (2) b",
           "When done, Acceptance: (1) a (2) b"]
    got = [(_items(d), M.reading_line(d)) for d in mid]
    check("cq3 (c) a marker part-way along a line after a dash, a semicolon or a "
          "comma reads no item, and the line says no clause was read and quotes "
          "the mention",
          all(items == [] and _NONE_READ in ln and _MENTION in ln
              and '"Acceptance: (1) a' in ln for items, ln in got), "%r" % (got,))

    spans = ["```make test``` is the gate.\n\nAcceptance:\n(1) a\n(2) b",
             "Ex:\n````\n```\ninner\n````\nAcceptance:\n(1) a\n(2) b"]
    got = [(_items(d), M.reading_line(d)) for d in spans]
    check("cq4 (d) an inline span of three backticks at a line start opens no "
          "fence, and a four-backtick fence is not closed by a three-backtick "
          "line: both lists are read whole, and nothing is printed",
          all(items == ["a", "b"] and ln == "" for items, ln in got), "%r" % (got,))

    glued = [("Acceptance: (1) a;(2) b;(3) c", ["a;", "b;", "c"]),
             ("Acceptance: (1) a,(2) b", ["a,", "b"])]
    got = [_items(d) for d, _want in glued]
    check("cq5 (e) a parenthesised number straight after a semicolon or a comma "
          "opens an item",
          got == [want for _d, want in glued], "%r" % (got,))

    folds = [("Acceptance:\n(1) a\n(2) b\n(4) c\n(5) d", 2, '"(4) c"'),
             ("Acceptance:\n(1) a\n(2) b\n(2) c\n(3) d", 3, '"(2) c"'),
             ("Acceptance:\n1. a\n2. b\n4. c", 2, '"4. c"')]
    got = [(len(_items(d)), M.reading_line(d)) for d, _n, _q in folds]
    nested = ("Acceptance:\n1. the build:\n   1. compiles\n   2. links\n"
              "2. the sweep is green")
    check("cq6 (f) a skipped or repeated number - parenthesised or at a line "
          "start - stays in the item before it, and the line names it with the "
          "first one quoted; a nested sub-step at a deeper indent could open "
          "nothing by its position and is not named (the twin)",
          all(n == want and _NUMBER in ln and quote in ln
              for (n, ln), (_d, want, quote) in zip(got, folds))
          and len(_items(nested)) == 2 and _NUMBER not in M.reading_line(nested),
          "%r / %r" % (got, M.reading_line(nested)))

    variants = ["ACCEPTANCE:\n(1) a\n(2) b", "acceptance:\n(1) a\n(2) b",
                "Acceptance :\n(1) a\n(2) b",
                "Acceptance" + chr(0xFF1A) + "\n(1) a\n(2) b"]
    got = [(_items(d), M.reading_line(d)) for d in variants]
    check("cq7 (g) the marker in another case, with a space before its colon or "
          "with a full-width colon reads no item, and the line says no clause "
          "was read and quotes it",
          all(items == [] and _NONE_READ in ln and _MENTION in ln
              and ('"%s' % d.split("\n")[0]) in ln
              for (items, ln), d in zip(got, variants)), "%r" % (got,))


# --- the conservation case: generated descriptions -------------------------------
# A description is built from segments whose role the generator knows, so the
# expectation - which items, which parts left out, which clauses - comes from
# the text as it was built and never from the reader's own fields.
_GEN_ITEMS = ("a holds", "b holds", "c holds")
_GEN_BODIES = (
    # (label, text before the marker, the marker, separator before each number)
    ("own-lines", "Do it.\n\n", "Acceptance:", "\n"),
    ("paragraph", "Do it. ", "Acceptance:", " "),
    ("bold", "Do it.\n\n", "**Acceptance:**", "\n"),
)


def _gen(body, disturbance):
    """`{"text", "region", "items", "leftOut", "tokens", "clauses", "quiet"}`
    for one generated description. `region` is where the first marker starts;
    `tokens` the marker and numbering text the generator wrote into the region;
    `clauses` the departure clauses the description owes."""
    label, pre, marker, sep = body
    items = list(_GEN_ITEMS)
    lead, tail, left, clauses = "", "", [], set()
    if disturbance == "mention":
        items[1] += ". The doc is updated. Acceptance: lists stay numbered."
        clauses.add(_MENTION)
    elif disturbance == "glued":
        items[1] = "b calls sys.exit(1) and reads rows[0](2)"
    elif disturbance == "skip":
        items[2] += sep + "(5) e holds"
        clauses.add(_NUMBER)
    elif disturbance == "repeat":
        items[2] += sep + "(3) c again"
        clauses.add(_NUMBER)
    elif disturbance == "inline-span":
        pre = "```make test``` runs it.\n\n" + pre
    elif disturbance == "second-marker":
        tail = "\n\nAcceptance: see the list above."
        left.append("see the list above.")
    elif disturbance == "heading":
        tail = "\n\n## Notes\nNothing else is in scope."
        left.append("## Notes\nNothing else is in scope.")
    elif disturbance == "lead-in":
        lead = " the checks below hold:"
        left.append("the checks below hold:")
    elif disturbance == "unclosed-fence":
        items[2] += "\n```\nexample"
        clauses.add(_FENCE)
    elif disturbance == "variant-case":
        items[2] += "\n\nACCEPTANCE: also this."
        clauses.add(_MENTION)
    numbers = ["(%d)" % (i + 1) for i in range(len(items))]
    listed = "".join("%s%s %s" % (sep, n, it) for n, it in zip(numbers, items))
    text = pre + marker + lead + listed + tail
    tokens = [marker] + numbers
    if disturbance == "second-marker":
        tokens.append("Acceptance:")
    if left:
        clauses.add(_LEFT_OUT)
    if disturbance == "second-marker":
        clauses.add("2 Acceptance markers")
    return {"text": text, "region": len(pre), "items": items, "leftOut": left,
            "tokens": tokens, "clauses": clauses,
            "quiet": not clauses}


_GEN_DISTURBANCES = ("none", "mention", "glued", "skip", "repeat", "inline-span",
                     "second-marker", "heading", "lead-in", "unclosed-fence",
                     "variant-case")


def _nonspace(text):
    """The characters of `text` that are not whitespace, as a sorted list - a
    multiset two texts can be compared by."""
    return sorted(ch for ch in text if not ch.isspace())


def _gen_verdict(case):
    """The list of what the reader got wrong about one generated description,
    empty when nothing."""
    reading = M.acceptance_reading(case["text"])
    line = M.reading_line(case["text"])
    wrong = []
    if reading["items"] != case["items"]:
        wrong.append("items %r, built %r" % (reading["items"], case["items"]))
    got_left = sorted(part["text"] for part in reading.get("leftOut", []))
    if got_left != sorted(case["leftOut"]):
        wrong.append("left out %r, built %r" % (got_left, case["leftOut"]))
    for part in case["leftOut"]:
        start = '"%s' % (" ".join(part.split())[:12],)
        if start not in line:
            wrong.append("the line does not quote %s" % (start,))
    every = (_MENTION, _NUMBER, _FENCE, _LEFT_OUT, "2 Acceptance markers")
    for clause in every:
        if (clause in case["clauses"]) != (clause in line):
            wrong.append("clause %r %s" % (clause, "missing" if clause
                                           in case["clauses"] else "printed"))
    if case["quiet"] != (line == ""):
        wrong.append("quiet %s, line %r" % (case["quiet"], line))
    # CONSERVATION, the subtraction: every non-space character from the first
    # marker to the end is in an item the reader read or a part it names as
    # left out, or is the marker and numbering text the generator wrote.
    region = _nonspace(case["text"][case["region"]:])
    held = _nonspace("".join(reading["items"]
                             + [part["text"] for part in reading.get("leftOut", [])]
                             + case["tokens"]))
    if region != held:
        wrong.append("conservation: region holds %d non-space characters, items, "
                     "parts left out and tokens %d" % (len(region), len(held)))
    # The reader's own subtraction must agree that nothing was left over.
    if reading.get("unaccounted"):
        wrong.append("the reader's own remainder is %r" % (reading["unaccounted"],))
    return wrong


def _conservation_cases(check):
    """Every generated description reads its built items, names each part it
    left out, prints exactly the clauses its disturbance owes, and conserves
    every character after its first marker."""
    cases = [(body[0], d, _gen(body, d)) for body in _GEN_BODIES
             for d in _GEN_DISTURBANCES]
    wrong = [(b, d, w) for b, d, case in cases for w in [_gen_verdict(case)] if w]
    quiet = [(b, d) for b, d, case in cases if case["quiet"]]
    check("cq8 over %d generated descriptions (%d list bodies crossed with %d "
          "disturbances, %d of them built to print nothing) each reads the items "
          "it was built with, names every part left out, prints exactly the "
          "clauses it owes, and holds every non-space character after its first "
          "marker in an item, a named part or the marker and numbering text"
          % (len(cases), len(_GEN_BODIES), len(_GEN_DISTURBANCES), len(quiet)),
          not wrong and len(cases) == len(_GEN_BODIES) * len(_GEN_DISTURBANCES),
          "%r" % (wrong,))


def _correction_cases(check):
    """The three corrections, each with the twin that tells it from its
    opposite, and the plain lists that must stay quiet."""
    inside = ("Acceptance:\n(1) a holds.\n(2) b holds. Acceptance: is named in "
              "the doc.\n(3) c holds")
    paragraph = "Do it. Acceptance: (1) a holds (2) b holds"
    check("cq9 a marker opening a sentence inside an item does not end the list "
          "- three items - and a marker opening a sentence as the FIRST marker "
          "still starts one written as a paragraph (the twin)",
          len(_items(inside)) == 3 and _MENTION in M.reading_line(inside)
          and _items(paragraph) == ["a holds", "b holds"]
          and M.reading_line(paragraph) == "",
          "%r / %r" % ((_items(inside), M.reading_line(inside)), _items(paragraph)))

    opens = ['Acceptance: (1) a;(2) b', 'Acceptance: (1) a,(2) b',
             'Acceptance: (1) say "ok"(2) b', 'Acceptance: (1) a -(2) b']
    glued = ("Acceptance: (1) calls f(2), g_(2), 3(2), rows[0](2), h()(2) and "
             "m{x}(2)\n(2) b")
    got = [len(_items(d)) for d in opens]
    check("cq10 a parenthesised number after a semicolon, a comma, a quote or a "
          "dash opens an item; after a letter, an underscore, a digit or a "
          "closing bracket it does not, and that list prints nothing (the twin: "
          "a class widened to every character opens items at the calls)",
          got == [2, 2, 2, 2] and len(_items(glued)) == 2
          and _items(glued)[1] == "b" and M.reading_line(glued) == "",
          "%r / %r" % (got, (_items(glued), M.reading_line(glued))))

    fences = [
        ("inline span", "```make test``` is the gate.\n\nAcceptance:\n(1) a\n(2) b"),
        ("longer fence", "````\n```\nAcceptance:\n(1) x\n```\n````\n\nAcceptance:"
                         "\n(1) a\n(2) b"),
        ("tilde fence", "~~~~\n~~~\nAcceptance:\n(1) x\n~~~~\n\nAcceptance:\n(1) a"
                        "\n(2) b"),
        ("text after a closing fence",
         "```\nx\n``` not a close\nAcceptance:\n(1) x\n```\n\nAcceptance:\n(1) a"
         "\n(2) b"),
        ("info string", "```bash\nAcceptance:\n(1) x\n```\nAcceptance:\n(1) a\n(2) b"),
    ]
    got = [(label, _items(d)) for label, d in fences]
    unclosed = "Run:\n```\nmake\n\nAcceptance:\n(1) a"
    check("cq11 an inline span at a line start opens no fence; a fence is closed "
          "only by the same character, at least as long, with nothing after it; "
          "a marker inside a real fence is no marker (the twin); and a fence "
          "open at the end is named",
          all(items == ["a", "b"] for _label, items in got)
          and _items(unclosed) == [] and _FENCE in M.reading_line(unclosed)
          and _NONE_READ in M.reading_line(unclosed),
          "%r / %r" % (got, M.reading_line(unclosed)))

    plain = ["Do it.\n\nAcceptance:\n(1) a holds\n(2) b holds\n(3) c holds",
             "Do it. Acceptance: (1) a holds (2) b holds",
             "Acceptance:\n(1) the tool calls sys.exit(1) on error\n(2) b",
             "Acceptance:\n(1) rows[0](2) is read\n(2) b",
             "**Acceptance:**\n(1) a\n(2) b",
             DESCRIPTION]
    got = [(len(_items(d)), M.reading_line(d)) for d in plain]
    check("cq12 ALLOW: a plain parenthesised list - on its own lines, in one "
          "paragraph after a sentence, with a call or an index in an item, under "
          "a bold marker - prints nothing (the twin of every clause above: a "
          "clause printed for every description goes red here)",
          [ln for _n, ln in got] == [""] * len(plain)
          and [n for n, _ln in got] == [3, 2, 2, 2, 2, 2], "%r" % (got,))

    ticked = "Name the `Acceptance:` marker in the docs.\n\nAcceptance:\n(1) a\n(2) b"
    only = "Write an `Acceptance:` list later.\n(1) a\n(2) b"
    check("cq14 a marker word in backticks is a place the word occurs and was "
          "not counted: beside a real marker the list is read and the mention "
          "named; alone, the line says no clause was read",
          _items(ticked) == ["a", "b"] and _MENTION in M.reading_line(ticked)
          and _items(only) == [] and _NONE_READ in M.reading_line(only),
          "%r / %r" % (M.reading_line(ticked), M.reading_line(only)))

    plain_reading = M.acceptance_reading("Acceptance:\n(1) a\n(2) b")
    lost = dict(plain_reading, unaccounted=[{"at": 3, "text": "lost words here"}])
    said = M.describe_reading(lost)
    check("cq15 a reading whose own subtraction left text over - which no shape "
          "produces today - is never plain: the line names the stretch, quoted, "
          "while the same reading with nothing over prints nothing (the twin)",
          '1 stretch of text after the first marker in no item and in no part '
          'named here, first "lost words here"' in said
          and M.describe_reading(plain_reading) == "", "%r" % (said,))


def _hostile_cases(check):
    """The reader is called by add, scope and the drive's filing; it must
    answer every input, and in bounded time."""
    listed = "Acceptance:\n" + "".join("(%d) item\n" % i for i in range(1, 90001))
    inputs = [("empty", ""), ("None", None), ("a number", 42),
              ("a list", ["Acceptance: (1) a"]), ("a dict", {"description": 1}),
              ("only the marker", "Acceptance:"),
              ("the marker at the very end", "Do it. Acceptance:"),
              ("ten thousand line markers", "Acceptance:\n" * 10000),
              ("ten thousand markers on one line", "Do it. Acceptance: " * 10000),
              ("ten thousand mentions", "see `Acceptance:` " * 10000),
              ("ten thousand fences", "```\n" * 10000 + "Acceptance:\n(1) a"),
              ("a megabyte list", listed),
              ("a megabyte line", "Acceptance: (1) " + "a(1)b;" * 175000)]
    results = []
    for label, value in inputs:
        began = time.time()
        try:
            reading = M.acceptance_reading(value)
            line = M.reading_line(value)
            M.reading_summary(value)
            M.task_clauses({"description": value})
            ok = isinstance(reading["items"], list) and isinstance(line, str)
            why = ""
        except Exception as exc:                               # noqa: BLE001
            ok, why = False, "%s: %s" % (type(exc).__name__, exc)
        results.append((label, ok, round(time.time() - began, 2), why))
    slow = [r for r in results if r[2] > 10.0]
    check("cq13 every hostile input - empty, None, a non-string, only the "
          "marker, the marker at the end, ten thousand markers, mentions or "
          "fences, a megabyte description - returns a reading and a line, "
          "raising nothing, each inside ten seconds",
          all(ok for _l, ok, _t, _w in results) and not slow,
          "%r" % ([r for r in results if not r[1] or r[2] > 10.0] or results,))


# --- the wide reading: silent only on agreement -----------------------------------
# The words the wide reading's clause carries, as the line prints them. A case
# asserts the count and the parting line through these, so a clause printed for
# every description is told apart from one printed never.
_WIDE = "a wider reading of the same text finds"
_PART = "the two readings first part on line"


def _wide_said(line, count, at, quote):
    """Whether `line` carries the wide clause with this count, this parting line
    and this quoted text."""
    return ("%s %d item%s" % (_WIDE, count, "" if count == 1 else "s") in line
            and "%s %d: %s" % (_PART, at, quote) in line)


def _wide_measured_cases(check):
    """The shapes a third review measured as read short with nothing printed:
    each now prints a line giving what a wider reading finds and where the two
    readings part - while what the task is held to does not move."""
    continued = [
        ("Acceptance:\n(1) a holds\n(2) b holds\n3. c holds\n4. d holds", 4,
         '"3. c holds"'),
        ("Acceptance:\n(1) a holds\n(2) b holds\n3) c holds", 3, '"3) c holds"'),
        ("Acceptance:\n(1) a holds\n(2) b holds\n[3] c holds", 3, '"[3] c holds"'),
    ]
    got = [(len(_items(d)), M.reading_line(d)) for d, _n, _q in continued]
    check("cw1 (a) a parenthesised list continued by `3.`, `3)` or `[3]` at a line "
          "start still reads two items, and the line says a wider reading finds "
          "the count written and that the two part on line 4, quoted",
          all(n == 2 and _wide_said(ln, want, 4, quote)
              for (n, ln), (_d, want, quote) in zip(got, continued)), "%r" % (got,))

    body = "\n(1) a holds\n(2) b holds"
    spellings = ["**Acceptance**:", "## Acceptance", "Acceptance criteria:",
                 "**Acceptance criteria:**", "Acceptance -", "Acceptance" + chr(0xA0) + ":"]
    got = [(_items("Do it.\n\n" + s + body), M.reading_line("Do it.\n\n" + s + body))
           for s in spellings]
    check("cw2 (b) the marker with emphasis around the word, as a heading, with a "
          "second word before the colon, followed by a dash, or with a no-break "
          "space before the colon reads no item, and the line says no clause was "
          "read, that a wider reading finds two, and that they part on line 4",
          all(items == [] and _NONE_READ in ln
              and _wide_said(ln, 2, 4, '"(1) a holds"') for items, ln in got),
          "%r" % (got,))

    folded = [
        ("Acceptance:\n(1) a holds\n" + chr(0xFF08) + "2" + chr(0xFF09) + " b holds",
         1, 2, 3, '"' + chr(0xFF08) + "2" + chr(0xFF09) + ' b holds"'),
        ("Do it.\n\nAccep" + chr(0x200B) + "tance:\n(1) a holds\n(2) b holds",
         0, 2, 4, '"(1) a holds"'),
    ]
    got = [(len(_items(d)), M.reading_line(d)) for d, _s, _w, _l, _q in folded]
    # Full-width DIGITS in plain brackets are a digit run to the strict reading
    # already, so the two readings agree and nothing is printed: the twin that
    # tells a fold of the text from a line printed for every non-ASCII list.
    digits = "Acceptance:\n(1) a holds\n(" + chr(0xFF12) + ") b holds"
    check("cw3 (c) a number in full-width brackets and a character without width "
          "inside the marker word read short as before, and the line gives the "
          "wide count and the parting line quoted as written; full-width digits, "
          "which the strict reading reads, print nothing",
          all(n == strict and _wide_said(ln, wide, at, quote)
              for (n, ln), (_d, strict, wide, at, quote) in zip(got, folded))
          and len(_items(digits)) == 2 and M.reading_line(digits) == "",
          "%r / %r" % (got, M.reading_line(digits)))


def _wide_allow_cases(check):
    """The twins that stay silent - a wide reading that over-reads a plain list
    goes red here."""
    quiet = [
        ("parenthesised, own lines", "Do it.\n\nAcceptance:\n(1) a holds\n(2) b holds"),
        ("parenthesised, one paragraph", "Do it. Acceptance: (1) a holds (2) b holds"),
        ("wrapped item lines",
         "Acceptance:\n(1) a holds, and it keeps\n  holding on the next line\n(2) b"),
        ("calls inside an item",
         "Acceptance:\n(1) the tool calls sys.exit(1) and f(2) on error\n(2) b"),
        ("an index before a number", "Acceptance:\n(1) rows[0](2) is read\n(2) b"),
        ("sub-steps in an item", "Acceptance: (1) do:\n1. x\n2. y\n(2) b"),
        ("no marker word", "Do it.\n(1) a holds\n(2) b holds"),
        ("the word without a colon in prose",
         "The acceptance tests run nightly.\n\nAcceptance:\n(1) a\n(2) b"),
        # Away from a line's start the wide reading's marker holds its colon;
        # a sentence opening with the bare word is prose, and no list is there.
        ("the word opening a sentence with no colon",
         "Ship it. Acceptance is checked by the nightly job."),
    ]
    got = [(label, M.reading_line(d)) for label, d in quiet]
    numbered = ["Acceptance:\n1. a holds\n2. b holds",
                "Acceptance:\n1. the build:\n   1. compiles\n   2. links\n2. green"]
    lines = [M.reading_line(d) for d in numbered]
    check("cw4 ALLOW: a plain parenthesised list on its own lines and in one "
          "paragraph, wrapped item lines, `exit(1)` and `f(2)` in an item, an index "
          "glued before a number, sub-steps in an item and a description with no "
          "marker word print nothing; a plain list numbered at line starts, nested "
          "or not, prints its line with no wide clause",
          [ln for _l, ln in got] == [""] * len(quiet)
          and all(ln and _WIDE not in ln for ln in lines),
          "%r / %r" % ([g for g in got if g[1]], lines))


# The generated descriptions. Each marker spelling and each numbering form is a
# part the case places, so the count of items written is known from the
# construction and never from the reader.
_GEN_MARKERS = (
    # (spelling, strict) - strict: the reader holds a task to the list under it
    ("Acceptance:", True), ("**Acceptance:**", True), ("## Acceptance:", True),
    ("> Acceptance:", True),
    ("**Acceptance**:", False), ("## Acceptance", False),
    ("Acceptance criteria:", False), ("**Acceptance criteria:**", False),
    ("Acceptance -", False), ("Acceptance" + chr(0xA0) + ":", False),
    ("Accep" + chr(0x200B) + "tance:", False), ("ACCEPTANCE:", False),
    ("acceptance:", False), ("Acceptance :", False),
    (chr(0xFF21) + "cceptance:", False),
)


def _fullwidth(n):
    return "".join(chr(0xFF10 + int(d)) for d in str(n))


_GEN_FORMS = (
    # (name, opener for item n)
    ("paren", lambda n: "(%d)" % n),
    ("dot", lambda n: "%d." % n),
    ("close", lambda n: "%d)" % n),
    ("bracket", lambda n: "[%d]" % n),
    ("full-width brackets", lambda n: chr(0xFF08) + str(n) + chr(0xFF09)),
    ("full-width digits", lambda n: "(%s)" % (_fullwidth(n),)),
)
_GEN_WRITTEN = ("a holds", "b holds", "c holds")


def _gen_numberings():
    """`[(name, [form index per item])]`: every form alone, and every ordered
    pair of forms split after the first and after the second item."""
    alone = [(_GEN_FORMS[f][0], [f] * len(_GEN_WRITTEN)) for f in range(len(_GEN_FORMS))]
    mixed = [("%s then %s" % (_GEN_FORMS[a][0], _GEN_FORMS[b][0]),
              [a] * k + [b] * (len(_GEN_WRITTEN) - k))
             for a in range(len(_GEN_FORMS)) for b in range(len(_GEN_FORMS)) if a != b
             for k in (1, 2)]
    return alone + mixed


def _gen_wide(marker, numbering):
    """One generated description, its item lines at line starts."""
    lines = ["%s %s" % (_GEN_FORMS[f][1](n), item)
             for n, (f, item) in enumerate(zip(numbering, _GEN_WRITTEN), 1)]
    return "Do it.\n\n%s\n%s" % (marker, "\n".join(lines))


def _wide_generated_cases(check):
    """The rule itself, as a property over descriptions whose item count the
    case wrote: whenever the strict reading's count differs from it, a line is
    printed, and it says the wider reading finds the count written."""
    written = len(_GEN_WRITTEN)
    built = [(m, strict, name, _gen_wide(m, numbering))
             for m, strict in _GEN_MARKERS for name, numbering in _gen_numberings()]
    built += [(m, strict, "paragraph", "Do it. %s %s" % (m, " ".join(
        "(%d) %s" % (n, item) for n, item in enumerate(_GEN_WRITTEN, 1))))
        for m, strict in _GEN_MARKERS if strict and not m.startswith(("#", ">"))]
    silent_short, unsaid, plain_loud = [], [], []
    for marker, strict, name, text in built:
        count, line = len(_items(text)), M.reading_line(text)
        if count != written and not line:
            silent_short.append((marker, name, count))
        elif count != written and "%s %d items" % (_WIDE, written) not in line:
            unsaid.append((marker, name, count, line))
        if strict and name in ("paren", "paragraph") and (count != written or line):
            plain_loud.append((marker, name, count, line))
    check("cw5 over %d generated descriptions (%d marker spellings crossed with "
          "every numbering form alone and every ordered pair of forms mixed), none "
          "whose strict count differs from the count written is silent, each such "
          "line says the wider reading finds the count written, and a strict "
          "marker over a plain parenthesised list reads every item and prints "
          "nothing" % (len(built), len(_GEN_MARKERS)),
          not silent_short and not unsaid and not plain_loud,
          "silent %r / unsaid %r / plain printed %r"
          % (silent_short[:5], unsaid[:3], plain_loud[:3]))


# --- the wide reading's bare word, parting line and equal counts -----------------
# The words of the equal-count clause, as the line prints them, and the parting
# clause read back into its line number and its quote.
_SAME = "the same number of items, placed differently"
_PART_AT = re.compile(r'first part on line (\d+): "(.*?)"')


def _written_lines(text):
    """The description's lines as written: any line end ends a line."""
    return re.split(r"\r\n|\r|\n", text)


def _parting(text, line):
    """`(number, quote, the line of the text as written there)` named by the
    wide clause, or None when the line names no parting line."""
    found = _PART_AT.search(line)
    if not found:
        return None
    number, quote = int(found.group(1)), found.group(2)
    lines = _written_lines(text)
    there = lines[number - 1] if 0 < number <= len(lines) else None
    return number, quote, there


def _quotes_its_line(text, line, at):
    """Whether the wide clause names line `at` and quotes text that is on it."""
    got = _parting(text, line)
    if got is None or got[0] != at or got[2] is None:
        return False
    quote = got[1][:-3] if got[1].endswith("...") else got[1]
    return bool(quote.strip()) and quote.strip() in got[2]


_HEAD = "Do it.\n\nAcceptance:\n"


def _wide_bare_cases(check):
    """A bare marker word is a marker in the wider reading only where a list
    numbered from one opens under it; a line that merely begins with it is
    prose. Each prose row is a reading that took the word at any line start
    (the bug); each marker row is a reading that took it nowhere."""
    prose = [
        ("an item wrapping onto a line beginning with the word",
         _HEAD + "(1) a holds\n(2) the\nAcceptance tests stay green.\n(3) c holds", 3),
        ("the same in lower case",
         _HEAD + "(1) a holds\n(2) and\nacceptance is by the owner.\n(3) c holds", 3),
        ("the same with emphasis around the word",
         _HEAD + "(1) a holds\n(2) see\n**Acceptance** in the handbook\n(3) c holds", 3),
        ("the same with underscores around the word in lower case",
         _HEAD + "(1) a holds\n(2) see\n_acceptance_ in the handbook\n(3) c holds", 3),
        ("the last item ending on a line beginning with the word",
         _HEAD + "(1) a holds\n(2) the\nAcceptance tests stay green", 2),
        ("a closing paragraph after a blank line",
         _HEAD + "(1) a holds\n(2) b holds\n\nAcceptance is by the owner.", 2),
        ("a closing paragraph after no blank line, lower case",
         _HEAD + "(1) a holds\n(2) b holds\nacceptance testing is manual", 2),
        ("a list under it opening at three, not one",
         "Do it.\n\nAcceptance tests stay green.\n(3) c holds\n(4) d holds", 0),
        ("no marker at all and a prose line beginning with the word",
         "Fix it.\n\nAcceptance tests must stay green.", 0),
        ("no marker at all, lower case, a line after it",
         "Fix it.\nacceptance is by review\nand nothing else.", 0),
    ]
    got = [(label, len(_items(d)), M.reading_line(d)) for label, d, _n in prose]
    check("cw9 a line that only begins with the marker word, without its colon - "
          "an item wrapping onto it in either case of its first letter or with "
          "emphasis, the last item, a closing paragraph after a blank line or "
          "none, a line whose list opens at three, a description with no marker - "
          "reads the items written and prints nothing",
          [(n, ln) for _l, n, ln in got] == [(want, "") for _l, _d, want in prose],
          "%r" % ([g for g, (_l, _d, want) in zip(got, prose)
                   if (g[1], g[2]) != (want, "")],))

    marked = [
        ("a heading", "Do it.\n\n## Acceptance\n(1) a holds\n(2) b holds", 4),
        ("a heading in lower case", "Do it.\n\n## acceptance\n(1) a holds\n(2) b holds", 4),
        ("a label with a second word", "Do it.\n\nAcceptance criteria\n1. a holds\n2. b holds", 4),
        ("a bold label", "Do it.\n\n**Acceptance**\n(1) a holds\n(2) b holds", 4),
        ("a label with a word in brackets",
         "Do it.\n\nAcceptance (criteria)\n1) a holds\n2) b holds", 4),
        ("a blank line between the label and the list",
         "Do it.\n\nAcceptance criteria\n\n[1] a holds\n[2] b holds", 5),
        ("the list opening on the word's own line",
         "Do it.\n\nAcceptance (1) a holds\n(2) b holds", 3),
    ]
    got = [(label, M.reading_line(d)) for label, d, _at in marked]
    check("cw10 ALLOW: a heading or a label holding the bare word, in either case, "
          "with other words or none, and a list numbered from one opening under it "
          "or on its own line, is a marker to the wider reading: the line says no "
          "clause was read, that a wider reading finds two, and quotes the line "
          "where they part",
          all(_NONE_READ in ln and "%s 2 items" % (_WIDE,) in ln
              and _quotes_its_line(d, ln, at)
              for (_l, ln), (_l2, d, at) in zip(got, marked)),
          "%r" % (got,))


# Colon-less labels of several words, as a review wrote them over its lists.
_SAME_LINE_LABELS = ("Acceptance criteria", "**Acceptance criteria**",
                     "Acceptance checks (all required)", "acceptance criteria",
                     "## Acceptance criteria")


def _wide_same_line_cases(check):
    """A colon-less label is read the same way whether its list opens on its own
    line or on the next. Each said row is a reading that took label words only
    across a line break (the bug); each quiet row is a reading that took label
    words on the word's own line before any lone reference or version number."""
    # A dotted, closing-bracket or square-bracketed number part-way along a line
    # opens no item to either reading - `Acceptance (1) a 2. b` is one item to
    # the word alone too - so those lists, written on one line, read as one item.
    mid_line = ("paren", "full-width brackets", "full-width digits")
    built = []
    for label in _SAME_LINE_LABELS:
        for name, opener in _GEN_FORMS:
            for where, gap in (("same line", " "), ("next line", "\n")):
                tail = " %s a holds%s%s b holds" % (opener(1), gap, opener(2))
                want = 2 if gap == "\n" or name in mid_line else 1
                built.append(("%s, %s, second item on the %s" % (label, name, where),
                              "Do it.\n\n%s%s" % (label, tail), "Do it.\n\nAcceptance" + tail,
                              want))
    got = [(label, _items(t), M.reading_line(t), t, M.reading_line(alone), want)
           for label, t, alone, want in built]
    said = "%s %%d item" % (_WIDE,)
    wrong = [(label, items, ln) for label, items, ln, t, alone, want in got
             if not (items == [] and _NONE_READ in ln and said % want in ln
                     and said % want in alone and _quotes_its_line(t, ln, 3))]
    check("cw14 a colon-less label of several words - plain, emphasised, with a word "
          "in brackets, in lower case, as a heading - with a two-item list opening on "
          "its own line in every numbering form, the second item on that line or the "
          "next, reads no strict item, and the line says no clause was read, that a "
          "wider reading finds the items the word alone finds, and quotes the "
          "label's line (over %d descriptions)" % (len(built),),
          not wrong, some_of(wrong, render=repr))

    prose = [
        ("a parenthesised reference later in the line",
         "Fix it.\n\nAcceptance tests cover step (1) of the flow."),
        ("a bracketed citation later in the line",
         "Fix it.\n\nAcceptance testing follows the guideline [1] of the handbook."),
        ("a closing-bracket reference later in the line, lower case",
         "Fix it.\n\nacceptance runs after phase 1) of the rollout."),
        ("a numbered reference later in the line, then prose on the next",
         "Fix it.\n\nAcceptance criteria are listed in section 1. of the guide.\nThat is all."),
        ("a version number directly after the word",
         "Fix it.\n\nAcceptance 1.2 is the version in use."),
        ("a version number after label words",
         "Fix it.\n\nAcceptance suite 1.0 ships today."),
        ("a reference numbered one, then a reference numbered three in the same form",
         "Fix it.\n\nAcceptance tests cover step (1) and step (3) of the flow."),
    ]
    got = [(label, len(_items(d)), M.reading_line(d)) for label, d in prose]
    check("cw15 ALLOW: a prose line beginning with the marker word and holding one "
          "reference numbered one later in the line - parenthesised, bracketed, "
          "closing-bracket, dotted - or a version number, directly or after label "
          "words, or a reference numbered one whose next is not numbered two, reads "
          "no item and prints nothing",
          [(n, ln) for _l, n, ln in got] == [(0, "")] * len(prose),
          "%r" % ([g for g in got if (g[1], g[2]) != (0, "")],))

    fenced = [
        ("the word, then a fence opening, then an opener numbered one",
         "Fix it.\n\nAcceptance\n```\n(1) not a list\n(2) still not\n```\nmore prose"),
        ("label words, then a fence opening, then a dotted opener numbered one",
         "Fix it.\n\nAcceptance example\n```\n1. not a list\n2. still not\n```\nmore prose"),
        ("the word, then a tilde fence opening, then a bracketed opener",
         "Fix it.\n\nacceptance\n~~~\n[1] not a list\n[2] still not\n~~~\nmore prose"),
    ]
    # The fence's own opening line is the next line holding text, and it opens
    # no item, so a walk that steps over it is what this row goes red for; the
    # fence check behind it cannot be reached while the walk stops there.
    got = [(label, len(_items(d)), M.reading_line(d)) for label, d in fenced]
    check("cw16 ALLOW: the marker word, alone or with label words, followed on the "
          "next line by a code fence whose first line is an opener numbered one, is "
          "no marker: no item is read and nothing is printed",
          [(n, ln) for _l, n, ln in got] == [(0, "")] * len(fenced),
          "%r" % ([g for g in got if (g[1], g[2]) != (0, "")],))


def _wide_parting_cases(check):
    """The parting line holds text: blank lines, a line of blanks and carriage
    returns between the list and the continuing numbering do not move it."""
    forms = [("3.", "4."), ("3)", "4)"), ("[3]", "[4]"),
             (chr(0xFF08) + "3" + chr(0xFF09), chr(0xFF08) + "4" + chr(0xFF09))]
    gaps = [("one blank line", "\n", "\n\n"), ("two blank lines", "\n", "\n\n\n"),
            ("a line of blanks", "\n", "\n \t \n"),
            ("carriage returns and line feeds", "\r\n", "\r\n\r\n")]
    built = []
    for three, four in forms:
        for label, eol, gap in gaps:
            head = eol.join(["Do it.", "", "Acceptance:", "(1) a holds", "(2) b holds"])
            text = head + gap + "%s c holds%s%s d holds" % (three, eol, four)
            at = len(_written_lines(head + gap))
            built.append(("%s after %s" % (three, label), text, at, "%s c holds" % (three,)))
    got = [(label, len(_items(t)), M.reading_line(t)) for label, t, _at, _q in built]
    wrong = [(label, n, ln) for (label, n, ln), (_l, t, at, quote) in zip(got, built)
             if not (n == 2 and "%s 4 items" % (_WIDE,) in ln
                     and _quotes_its_line(t, ln, at)
                     and '%s %d: "%s"' % (_PART, at, quote) in ln)]
    check("cw12 a parenthesised list continued by each other numbering after a "
          "blank line, two, a line of blanks, or with carriage-return line ends "
          "reads two items, and the line names the continuing line as written "
          "and quotes its text, never a blank line (over %d descriptions)"
          % (len(built),), not wrong, some_of(wrong, render=repr))


def _wide_equal_cases(check):
    """Two readings that count the same and place the items differently are
    said as that. A comparison of counts alone is silent on every row here."""
    equal = [
        (_HEAD + "(1) a holds\n(2) b holds\n3. c holds\n(3) d holds", 3, 6,
         "3. c holds"),
        (_HEAD + "(1) a holds\n(2) b holds\n\n3. c holds\n\n(3) d holds", 3, 7,
         "3. c holds"),
    ]
    got = [(len(_items(t)), M.reading_line(t)) for t, _n, _at, _q in equal]
    check("cw13 two readings that find the same number of items with different "
          "text print a line saying a wider reading finds the same number, placed "
          "differently, with no count given as if it differed, naming and quoting "
          "the parting line",
          all(n == want and "%s %s" % (_WIDE, _SAME) in ln
              and not re.search(r"%s \d+ item" % (re.escape(_WIDE),), ln)
              and '%s %d: "%s"' % (_PART, at, quote) in ln
              for (n, ln), (_t, want, at, quote) in zip(got, equal)),
          "%r" % (got,))
    unequal = _HEAD + "(1) a holds\n(2) b holds\n3. c holds"
    check("cw13b TWIN of cw13: unequal counts keep their sentence - the wider "
          "count is given and the equal-count words are not",
          "%s 3 items" % (_WIDE,) in M.reading_line(unequal)
          and _SAME not in M.reading_line(unequal), "%r" % (M.reading_line(unequal),))


# The plain half of the generated case. Prose is drawn from a vocabulary holding
# the marker word in both cases of its first letter and in emphasis, wrapped at
# several widths by the construction itself, so it knows which wrapped line
# begins with which word. One pool also holds a number and its opener as a
# word; a description where the wrap put one of those at a line start may
# print, and every other one must print nothing.
_PLAIN_WORDS = ("the", "sweep", "is", "green", "and", "it", "holds", "by", "owner",
                "tests", "stay", "reader", "runs", "nightly", "exit(1)", "f(2)",
                "rows[0](2)", "version", "3.8", "under", "review.")
_PLAIN_WORD = ("acceptance", "Acceptance", "**Acceptance**", "acceptance.")
# No opener numbered one: the bare word followed by one IS a marker, by the rule.
_PLAIN_NUMBERED = ("2.", "3.", "2)")
_PLAIN_POOLS = (
    ("lower", _PLAIN_WORDS + ("acceptance",) * 6),
    ("upper", _PLAIN_WORDS + ("Acceptance",) * 6),
    ("both, with emphasis", _PLAIN_WORDS + _PLAIN_WORD * 2),
    ("both, with numbers", _PLAIN_WORDS + _PLAIN_WORD * 2 + _PLAIN_NUMBERED),
)
_PLAIN_WIDTHS = (24, 40, 56, 72)
_PLAIN_LAYOUTS = ("own lines", "closing paragraph", "closing line", "paragraph",
                  "no marker")


def _plain_prose(rng, pool, words):
    return " ".join(rng.choice(pool) for _ in range(words))


def _plain_build(rng, pool, width, layout):
    """`(text, items written, lines the wrap began)` for one plain description:
    the item count comes from the construction, and so does each wrapped
    line's first word."""
    import textwrap

    def wrap(text):
        return textwrap.wrap(text, width, break_long_words=False,
                             break_on_hyphens=False)
    count = rng.randint(2, 4)
    items = ["(%d) %s" % (n, _plain_prose(rng, pool, rng.randint(4, 18)))
             for n in range(1, count + 1)]
    pre = wrap(_plain_prose(rng, pool, rng.randint(3, 14)))
    if layout == "no marker":
        lines = pre + wrap(_plain_prose(rng, pool, rng.randint(3, 14)))
        return "\n".join(lines), 0, lines
    if layout == "paragraph":
        lines = wrap("%s. Acceptance: %s" % (" ".join(pre), " ".join(items)))
        return "\n".join(lines), count, lines
    item_lines = [ln for item in items for ln in wrap(item)]
    lines = pre + ["", "Acceptance:"] + item_lines
    if layout == "closing paragraph":
        lines += [""] + wrap(_plain_prose(rng, pool, rng.randint(3, 12)))
    elif layout == "closing line":
        lines += wrap(_plain_prose(rng, pool, rng.randint(3, 12)))
    return "\n".join(lines), count, lines


def _wide_plain_generated_cases(check):
    """Generated plain lists whose prose holds the marker word are silent unless
    the construction put a number and its opener at a line start."""
    import random
    rng = random.Random(1739)
    built = []
    for pool_name, pool in _PLAIN_POOLS:
        for width in _PLAIN_WIDTHS:
            for layout in _PLAIN_LAYOUTS:
                for _ in range(12):
                    text, count, lines = _plain_build(rng, pool, width, layout)
                    firsts = [ln.split()[0] for ln in lines if ln.split()]
                    numbered = any(w in _PLAIN_NUMBERED for w in firsts)
                    built.append((pool_name, width, layout, text, count, numbered,
                                  firsts))
    loud, short = [], []
    for pool_name, width, layout, text, count, numbered, _f in built:
        got, line = len(_items(text)), M.reading_line(text)
        if got != count:
            short.append((pool_name, width, layout, got, count, text))
        if line and not numbered:
            loud.append((pool_name, width, layout, line[:160], text))
    held = [b for b in built if not b[5]]
    began = set(w for b in held for w in b[6] if w in _PLAIN_WORD)
    check("cw11 over %d generated plain lists (%d word pools, %d widths, %d "
          "layouts) whose prose holds the marker word in both cases of its first "
          "letter and in emphasis, each reads the items built, and every one whose "
          "wrapped lines begin with no number and its opener prints nothing; the "
          "construction began wrapped lines with each spelling of the word"
          % (len(built), len(_PLAIN_POOLS), len(_PLAIN_WIDTHS), len(_PLAIN_LAYOUTS)),
          not loud and not short and began == set(_PLAIN_WORD),
          "loud %d: %s / short %d: %s / began %r"
          % (len(loud), some_of(loud, render=repr), len(short),
             some_of(short, render=repr), sorted(began)))


def _conservation_check_cases(check):
    """The check that no text after the first marker is left outside every item
    and every named part - called directly on spans the case builds, and shown
    to be what turns a forgetful reading's line red."""
    text = "head words lost words here tail words"
    gap = (text.index("lost"), text.index(" tail"))
    covered = [(0, text.index(" lost")), (text.index("tail"), len(text))]
    found = M._unaccounted(text, (0, len(text)), covered)
    whole = M._unaccounted(text, (0, len(text)), covered + [gap])
    check("cw6 the conservation check, given spans that leave a gap, names exactly "
          "that gap, and given spans that cover everything names none (the twin)",
          found == [gap] and whole == [], "%r / %r" % (found, whole))

    description = "Acceptance: the lead text, then\n(1) a\n(2) b"
    keep_left, keep_check = M._left_part, M._unaccounted

    def forgetful(*_args):
        return []

    def answered():
        reading = M.acceptance_reading(description)
        line = M.reading_line(description)
        return (bool(reading["unaccounted"])
                and reading["unaccounted"][0]["text"].startswith("the lead text")
                and '1 stretch of text after the first marker in no item and in no '
                    'part named here, first "the lead text, then"' in line), line
    try:
        M._left_part = forgetful
        named, line = answered()
        M._unaccounted = lambda *_args: []
        silenced, quiet_line = answered()
    finally:
        M._left_part, M._unaccounted = keep_left, keep_check
    check("cw7 a reading whose shapes forget a part (the left-out parts made to "
          "name nothing) has the forgotten stretch named by the check and quoted "
          "by the line; with the check answering nothing the same assertion is "
          "red, so silencing it cannot pass",
          named and not silenced, "%r / %r" % (line, quiet_line))


# The timing. A kind fails when its time grows as more than the WIDE_POWER of the
# length over the whole series of lengths - `_growth_exponent`, a time under
# WIDE_FLOOR read as the floor; no one step is judged ALONE, because a shared
# runner's noise lands on one length and a reading faster than linear shows at
# every doubling - or when its last step is over WIDE_STEP and the last two
# lengths, measured again in the same child with fresh rounds, are over it again:
# the slope reads a reading that is linear until its last doubling and quadratic
# there (ratios 2, 2, 4) as 1.3, and a single step cannot tell the noise a CI run
# recorded on a linear reading (2.92x and 3.00x at the last doubling) from growth,
# but a second measurement can - noise that landed on a length once has to land on
# it again to confirm the step. A
# last step the second measurement does not confirm is green, and one that was
# over the bound with no second measurement given is a fault of its own, never a
# pass. The kind also fails when the longest takes more than WIDE_CEILING seconds or holds more
# than WIDE_BYTES per character of input at its peak, or when its child is still running at
# WIDE_DEADLINE - a kill is a failure, never a skip. The time is the child's
# processor time per reading, taken by `_harness.growth_series`: the readings of
# one length are repeated until their total is long enough for the clock's step
# (on windows a process-time reading steps in 1/64 s, so one short reading reads
# as no time or a whole step), and the least of its rounds is kept - a loaded
# machine stretches the wall clock of one length and not the next, while the work
# a reading does is what grows with its length. A length the helper could not
# measure by WIDE_SERIES_DEADLINE, counted from the child's start, is a failure
# that names it.
WIDE_UNITS = tuple(1250 * 2 ** k for k in range(4))
WIDE_POWER = 1.5
# Between the worst last step CI recorded on a linear reading (3.00x) and a
# quadratic doubling (4x): the middle of the two, half a step from each.
WIDE_STEP = 3.5
WIDE_FLOOR = 1e-3
WIDE_CEILING = 1.0
WIDE_BYTES = 2000
WIDE_DEADLINE = 60.0
WIDE_SERIES_DEADLINE = 45.0
WIDE_MIN_SECONDS = 0.02
WIDE_ROUNDS = 3
_WIDE_TIMER = r'''
import json, sys, time, tracemalloc
began = time.perf_counter()
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import _harness
import _clause_coverage as M
import test__clause_coverage as T
KINDS = (
    ("list numbers on one line", lambda n: "Acceptance: (1) a" + " (1)" * n),
    ("line-start numbers after one line", lambda n: "Acceptance:\n(1) a" + " 3." * n),
    ("mentions on one line", lambda n: "Acceptance:\n(1) a " + "acceptance : " * n),
    ("markers on one line", lambda n: "Do it. Acceptance: " * n),
)
job = json.loads(sys.argv[3])
out = []
for label, make in KINDS:
    left = max(0.0, job["deadline"] - (time.perf_counter() - began))
    got = _harness.growth_series(M.reading_line, [make(n) for n in job["units"]],
                                 clock=time.process_time, clock_name="process_time",
                                 min_seconds=job["min_seconds"], rounds=job["rounds"],
                                 deadline=left)

    def again():
        left = max(0.0, job["deadline"] - (time.perf_counter() - began))
        return _harness.growth_series(M.reading_line,
                                      [make(n) for n in job["units"][-2:]],
                                      clock=time.process_time, clock_name="process_time",
                                      min_seconds=job["min_seconds"], rounds=job["rounds"],
                                      deadline=left)
    second = (T.last_step_again(got["seconds"], again)
              if got["fault"] is None and len(got["seconds"]) == len(job["units"]) else None)
    text = make(job["units"][-1])
    tracemalloc.start()
    M.reading_line(text)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    out.append({"kind": label, "seconds": got["seconds"], "repeats": got["repeats"],
                "floor": got["floor"], "fault": got["fault"], "peak": peak,
                "chars": len(text),
                "again": None if second is None else
                {"seconds": second["seconds"], "fault": second["fault"]}})
print(json.dumps(out))
'''


def _growth_exponent(seconds):
    """The exponent p in time ~ length ** p over the whole series: the least-squares
    slope of log2 time over log2 length, which for lengths that double is the slope
    over the position in the series.

    Not the steepest step: a reading that grows faster than linear grows at every
    doubling, so every length votes for it, while one length a loaded runner stretched
    moves one step and only a share of the slope - a linear series with one length 2.5
    times too slow reads 1.4, a step read alone reads 5x. Not the last time over the
    first either, which is two lengths and so still the noise of either of them in
    full. A time under WIDE_FLOOR reads as the floor.

    The slope is also the reason it cannot be the only judgement: a reading linear
    until its last doubling and quadratic there (ratios 2, 2, 4) reads 1.3 and
    passes it, so the last step is judged beside it - `last_step_again`, and
    `_last_step_faults` for what the second measurement makes of it."""
    logs = [math.log2(max(s, WIDE_FLOOR)) for s in seconds]
    middle = (len(logs) - 1) / 2.0
    spread = sum((i - middle) ** 2 for i in range(len(logs)))
    return sum((i - middle) * y for i, y in enumerate(logs)) / spread


def _last_step(seconds):
    """The last doubling's ratio, the earlier time read as the floor when it is under it."""
    return seconds[-1] / max(seconds[-2], WIDE_FLOOR)


def last_step_again(seconds, measure):
    """`measure()` - the last two lengths measured once more - when the last step of
    `seconds` is over WIDE_STEP, and None, without calling it, when it is not. The
    child calls this with the second measurement, so the decision to take one is the
    one these cases pin without a clock."""
    if len(seconds) < 2 or _last_step(seconds) <= WIDE_STEP:
        return None
    return measure()


def _last_step_faults(kind, secs, again):
    """The sentence a last step over WIDE_STEP earns, given what measuring the last two
    lengths again returned (None: it was not measured again, which is a fault and not a
    pass). Empty when the second measurement is within the bound."""
    first = _last_step(secs)
    if again is None:
        return ["%s took %.2fx for its last doubling, over %gx, and was not measured again"
                % (kind, first, WIDE_STEP)]
    if again["fault"] is not None or len(again["seconds"]) != 2:
        return ["%s took %.2fx for its last doubling, over %gx, and could not be measured "
                "again: %s" % (kind, first, WIDE_STEP, again["fault"] or "it read %d lengths"
                               % (len(again["seconds"]),))]
    second = _last_step(again["seconds"])
    if second <= WIDE_STEP:
        return []
    return ["%s took %.2fx for its last doubling (length %d to %d) and %.2fx when that doubling "
            "was measured again, over %gx both times"
            % (kind, first, WIDE_UNITS[-2], WIDE_UNITS[-1], second, WIDE_STEP)]


def _run_faults(run):
    """The sentences one kind's measured run earns, empty when it is within every bound."""
    kind = run["kind"]
    if run["fault"] is not None:
        return ["%s could not be measured: %s" % (kind, run["fault"])]
    secs = run["seconds"]
    if len(secs) != len(WIDE_UNITS):
        return ["%s was measured at %d of %d lengths" % (kind, len(secs), len(WIDE_UNITS))]
    faults = []
    steps = [b / max(a, WIDE_FLOOR) for a, b in zip(secs, secs[1:])]
    exponent = _growth_exponent(secs)
    if exponent > WIDE_POWER:
        faults.append("%s grew as length ** %.2f (%s per doubling), over %r readings a length"
                      % (kind, exponent, ", ".join("%.2fx" % g for g in steps),
                         run["repeats"]))
    elif _last_step(secs) > WIDE_STEP:
        faults.extend(_last_step_faults(kind, secs, run.get("again")))
    if secs[-1] > WIDE_CEILING:
        faults.append("%s took %.3fs at the longest" % (kind, secs[-1]))
    if run["peak"] > WIDE_BYTES * run["chars"]:
        faults.append("%s held %d bytes for %d characters" % (kind, run["peak"], run["chars"]))
    return faults


def _series_from(first, ratios):
    """The seconds of a series that starts at `first` and grows by each ratio in turn."""
    out = [first]
    for ratio in ratios:
        out.append(out[-1] * ratio)
    return out


def _wide_series_cases(check):
    """The growth judged over fixed series of seconds, with no child and no clock."""
    def run(seconds, peak=0, chars=1, fault=None, repeats=None, again=None):
        return {"kind": "k", "seconds": seconds, "repeats": repeats or [1] * len(seconds),
                "fault": fault, "peak": peak, "chars": chars, "again": again}

    def pair(step):
        """What measuring the last two lengths again returns when their step is `step`."""
        return {"seconds": [0.0625, 0.0625 * step], "fault": None}

    ci_windows = _series_from(0.05, (2.04, 1.53, 2.92))
    ci_linux = _series_from(0.05, (1.17, 1.43, 3.00))
    noisy_end = _series_from(0.02, (2.0, 2.0, 5.0))
    linear = _series_from(0.01, (2.0, 2.0, 2.0))
    allowed = {"windows run": ci_windows, "linux run": ci_linux,
               "one length 2.5 times too slow on a linear reading": noisy_end,
               "a linear reading": linear, "no time at all": [0.0] * 4,
               "no time and then a hair above the floor": [0.0, 0.0, 0.0, WIDE_FLOOR * 0.6]}
    # The one series here whose last step is over WIDE_STEP (5.0x) is given the
    # second measurement a linear reading would give; the rest are under it and
    # are given none, so a judgement that asked for one anyway reads red here.
    said = {name: _run_faults(run(s, again=pair(2.0) if s is noisy_end else None))
            for name, s in allowed.items()}
    check("cw17 the two series a release-tier CI run recorded red (windows 2.04x, 1.53x, "
          "2.92x; linux 1.17x, 1.43x, 3.00x), a linear reading with one length 2.5 times "
          "too slow, a clean linear one and two under the floor are all judged green",
          all(not v for v in said.values()), repr(said))

    quadratic = _series_from(0.002, (4.0, 4.0, 4.0))
    late = _series_from(0.01, (2.0, 4.0, 4.0))
    cubic = _series_from(0.001, (8.0, 8.0, 8.0))
    denied = {"quadratic": quadratic, "linear then quadratic over the last two doublings": late,
              "cubic": cubic}
    got = {name: _run_faults(run(s)) for name, s in denied.items()}
    exponents = [_growth_exponent(s) for s in (linear, quadratic, late)]
    check("cw18 a quadratic series, one that is linear and then quadratic over its last two "
          "doublings and a cubic one are each judged red by exactly one growth sentence, "
          "and the exponent read off a linear series is 1 and off a quadratic one is 2",
          all(len(v) == 1 and "grew as length" in v[0] for v in got.values())
          and abs(exponents[0] - 1.0) < 1e-9 and abs(exponents[1] - 2.0) < 1e-9
          and exponents[2] > WIDE_POWER, "%r / %r" % (got, exponents))

    ceiling = _run_faults(run([0.15, 0.3, 0.6, WIDE_CEILING * 1.2]))
    at_ceiling = _run_faults(run([0.125, 0.25, 0.5, WIDE_CEILING]))
    heavy = _run_faults(run(linear, peak=WIDE_BYTES * 100 + 1, chars=100))
    at_bytes = _run_faults(run(linear, peak=WIDE_BYTES * 100, chars=100))
    short = _run_faults(run(linear[:3]))
    cut = _run_faults(run([], fault="the deadline passed"))
    check("cw19 the longest length over WIDE_CEILING seconds, a peak over WIDE_BYTES per "
          "character, a series short of its lengths and a measurement the helper refused "
          "are each one fault; the ceiling and the byte bound themselves are within "
          "bounds (the twins)",
          len(ceiling) == 1 and "at the longest" in ceiling[0] and at_ceiling == []
          and len(heavy) == 1 and "held" in heavy[0] and at_bytes == []
          and len(short) == 1 and "3 of 4 lengths" in short[0]
          and len(cut) == 1 and "could not be measured" in cut[0],
          "%r / %r / %r / %r / %r / %r" % (ceiling, at_ceiling, heavy, at_bytes, short, cut))

    check("cw20 the lengths double, which is what reading a slope per doubling as an "
          "exponent of the length takes for granted",
          all(b == 2 * a for a, b in zip(WIDE_UNITS, WIDE_UNITS[1:])), repr(WIDE_UNITS))

    # A reading linear until its last doubling and quadratic there: the slope
    # passes it, so the last step is the only thing that can say.
    late_only = _series_from(0.01, (2.0, 2.0, 4.0))
    confirmed = _run_faults(run(late_only, again=pair(4.0)))
    noise = _run_faults(run(late_only, again=pair(2.0)))
    unasked = _run_faults(run(late_only))
    refused = _run_faults(run(late_only, again={"seconds": [], "fault": "the deadline passed"}))
    check("cw21 a series linear until its last doubling and quadratic there (ratios 2, 2, 4), "
          "which the slope reads under WIDE_POWER, is red with one sentence naming its last "
          "doubling when measuring the last two lengths again also finds 4x, and green when "
          "the second measurement finds 2x (noise); with no second measurement given, or one "
          "the helper refused, it is red with its own sentence and never a pass",
          _growth_exponent(late_only) <= WIDE_POWER
          and len(confirmed) == 1 and "last doubling" in confirmed[0]
          and "4.00x" in confirmed[0] and "measured again" in confirmed[0]
          and noise == []
          and len(unasked) == 1 and "was not measured again" in unasked[0]
          and len(refused) == 1 and "the deadline passed" in refused[0],
          "%r / %r / %r / %r" % (confirmed, noise, unasked, refused))

    # The bound itself, in binary-exact numbers so the ratio is exactly WIDE_STEP.
    at_step = [0.0625, 0.0625, 0.125, 0.0625 * 2 * WIDE_STEP]
    just_over = [0.0625, 0.0625, 0.125, 0.125 * 3.6]
    at_bound = _run_faults(run(at_step))
    held = _run_faults(run(just_over, again=pair(WIDE_STEP)))
    over_twice = _run_faults(run(just_over, again=pair(3.6)))
    check("cw22 the bound itself: a last step exactly at WIDE_STEP needs no second "
          "measurement and is within bounds, one just over it that the second measurement "
          "finds exactly at WIDE_STEP is within bounds, and one the second measurement "
          "finds just over it is red (the twins of the bound)",
          at_step[-1] / at_step[-2] == WIDE_STEP and 3.6 > WIDE_STEP
          and at_bound == [] and held == []
          and len(over_twice) == 1 and "last doubling" in over_twice[0],
          "%r / %r / %r" % (at_bound, held, over_twice))

    calls = []

    def counting(seconds, answer):
        """What last_step_again made of `seconds`, and how many times it measured."""
        before = len(calls)
        got = last_step_again(seconds, lambda: calls.append(1) or answer)
        return got, len(calls) - before

    again_sentinel = pair(4.0)
    under = {"windows run": ci_windows, "linux run": ci_linux, "a linear reading": linear,
             "at the bound": at_step, "no time and then a hair above the floor":
                 allowed["no time and then a hair above the floor"], "one length": [0.5]}
    quiet = {name: counting(s, again_sentinel) for name, s in under.items()}
    asked = {name: counting(s, again_sentinel)
             for name, s in {"late": late_only, "noisy end": noisy_end}.items()}
    check("cw23 a last step at or under WIDE_STEP is never measured again (no call, nothing "
          "returned), and a last step over it is measured once and the answer is what the "
          "judgement is given",
          all(v == (None, 0) for v in quiet.values())
          and all(v == (again_sentinel, 1) for v in asked.values()),
          "%r / %r" % (quiet, asked))


def _wide_timing_cases(check):
    """The reading's time at doubling lengths, in a child killed at a deadline."""
    import subprocess
    job = {"units": list(WIDE_UNITS), "deadline": WIDE_SERIES_DEADLINE,
           "min_seconds": WIDE_MIN_SECONDS, "rounds": WIDE_ROUNDS}
    argv = [sys.executable, "-c", _WIDE_TIMER, _harness.TESTS_DIR,
            os.path.dirname(M.__file__), json.dumps(job)]
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=WIDE_DEADLINE)
        killed, out, err = False, done.stdout, done.stderr
    except subprocess.TimeoutExpired as exc:
        killed, out, err = True, exc.stdout or b"", exc.stderr or b""
    try:
        runs = json.loads(out.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        runs = None
    faults = []
    if killed:
        faults.append("killed at the %gs deadline" % (WIDE_DEADLINE,))
    elif not isinstance(runs, list) or not runs:
        faults.append("no answer: %s" % (" ".join(err.decode("utf-8", "replace")
                                                    .split())[-300:],))
    else:
        for run in runs:
            faults.extend(_run_faults(run))
    check("cw8 the reading's processor time over list numbers, line-start numbers, mentions "
          "and markers on one line at %d doubling lengths grows as at most the "
          "WIDE_POWER of the length over the whole series (the slope of log time over "
          "log length), has no last doubling over WIDE_STEP that measuring the last two "
          "lengths again confirms, stays under WIDE_CEILING seconds and WIDE_BYTES "
          "per character at the longest, in a child killed at WIDE_DEADLINE"
          % (len(WIDE_UNITS),),
          not faults, "%s" % ("; ".join(faults),))


def _cases(check):
    _harness.stage(check, "cw-measured", _wide_measured_cases)
    _harness.stage(check, "cw-allow", _wide_allow_cases)
    _harness.stage(check, "cw-generated", _wide_generated_cases)
    _harness.stage(check, "cw-bare", _wide_bare_cases)
    _harness.stage(check, "cw-same", _wide_same_line_cases)
    _harness.stage(check, "cw-plain", _wide_plain_generated_cases)
    _harness.stage(check, "cw-part", _wide_parting_cases)
    _harness.stage(check, "cw-equal", _wide_equal_cases)
    _harness.stage(check, "cw-conserve", _conservation_check_cases)
    _harness.stage(check, "cw-series", _wide_series_cases)
    _harness.stage(check, "cw-timing", _wide_timing_cases)
    _harness.stage(check, "cc-shape", _shape_cases)
    _harness.stage(check, "cc-marker", _marker_cases)
    _harness.stage(check, "cc-two", _two_marker_cases)
    _harness.stage(check, "cc-rule", _shape_rule_cases)
    _harness.stage(check, "cc-bound", _boundary_cases)
    _harness.stage(check, "cc-line", _reading_line_cases)
    _harness.stage(check, "cc-number", _numbering_cases)
    _harness.stage(check, "cc-verdict", _verdict_cases)
    _harness.stage(check, "cc-path", _path_cases)
    _harness.stage(check, "cc-empty", _empty_cases)
    _harness.stage(check, "cc-resume", _resume_cases)
    _harness.stage(check, "cq-measured", _measured_cases)
    _harness.stage(check, "cq-conserve", _conservation_cases)
    _harness.stage(check, "cq-correct", _correction_cases)
    _harness.stage(check, "cq-hostile", _hostile_cases)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__clause_coverage.py --selftest\n")
    raise SystemExit(2)
