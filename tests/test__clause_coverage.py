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

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import time

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


def _cases(check):
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
