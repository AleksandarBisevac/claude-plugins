#!/usr/bin/env python3
"""
The cases for `_task_outputs.py` — what a task's `outputs` pattern may be, and
what an honoured one reaches.

Pure string work over patterns, so there is no fixture directory below.

WHAT IS PINNED, and why each one is here rather than trusted:

- **Both directions of the bound, on every spelling.** The refusals are the
  feature: a pattern whose head is not a literal directory name reaches the whole
  repository, and honouring one would switch the plan gate off through the door
  built to keep it on. So every refused spelling has a case AND the accepting
  case sits beside it — a rule that refused everything would pass a
  refusals-only suite and make the key useless.
- **The refusal NAMES the entry.** A list-level "one of your patterns is too
  wide" sends the reader back to guess which, so the sentence is asserted to
  carry the pattern rather than merely to be non-empty.
- **`*` does not cross a separator and `**` does.** `fnmatch` over the whole
  string gets this wrong in the dangerous direction — it hands a reader who typed
  one star the entire subtree — so both spellings are pinned against the same
  path.
- **`honoured` is the only door.** `output_covers` does not re-grade, by
  contract, so the case that matters is that a refused pattern never reaches it:
  `honoured` drops it, and the two together are what the plan gate relies on.
- **The rule is off `_manifest_vocab`'s import graph.** That module's own `mv37`
  holds the premise from its side; this holds the other half — that the thing the
  hook loads is this module and that it reaches nothing but `_output`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _task_outputs as M                          # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402
import _deps                                       # noqa: E402


def _cases(check):
    # --- what is accepted, first, so a rule that refuses everything is red ------
    for good in ("docs/**", "docs/audit/evidence/**", "docs/reports/*.md",
                 "docs", "docs/", "build/out/**/*.json", "a-dir/b_dir/c.d"):
        check("to1 %r is anchored at a literal directory name, so it may be "
              "honoured" % (good,),
              M.output_pattern_problem(good) is None,
              repr(M.output_pattern_problem(good)))

    # --- and what is refused, one case per spelling, each naming the entry ------
    for bad, why_word in (("**", "the repository itself"),
                          ("**/*.md", "the repository itself"),
                          (".", "the repository itself"),
                          ("", "empty"),
                          ("   ", "empty"),
                          ("*/x", "a pattern segment"),
                          ("*.md", "a pattern segment"),
                          ("?ocs/**", "a pattern segment"),
                          ("[ab]/**", "a pattern segment"),
                          ("/etc/passwd", "the filesystem root"),
                          ("~/notes/**", "a home path"),
                          ("../sibling/**", "a `..` segment"),
                          ("docs/../../etc/**", "a `..` segment")):
        problem = M.output_pattern_problem(bad)
        check("to2 %r is refused (%s)" % (bad, why_word),
              isinstance(problem, str) and bool(problem.strip()),
              repr(problem))
    check("to3 ...and the refusal NAMES the entry rather than saying a pattern "
          "somewhere in the list was too wide - a refusal read beside a list has "
          "to say which line to fix",
          all(repr(bad) in (M.output_pattern_problem(bad) or "")
              for bad in ("**", "*/x", "/etc/passwd", "~/x/**", "../y/**", "")),
          repr(M.output_pattern_problem("*/x")))
    for bad in (None, 7, [], {}, True):
        check("to4 %r is not a pattern at all and is refused rather than "
              "raising - a manifest this did not write may carry anything"
              % (bad,),
              isinstance(M.output_pattern_problem(bad), str),
              repr(M.output_pattern_problem(bad)))
    check("to5 a backslash spelling is respelled before the head is read, so a "
          "Windows-written pattern is graded by the same rule rather than "
          "reading as one long literal segment",
          M.output_pattern_problem("docs\\audit\\**") is None
          and M.output_pattern_problem("..\\x\\**") is not None,
          repr((M.output_pattern_problem("docs\\audit\\**"),
                M.output_pattern_problem("..\\x\\**"))))

    # --- what an honoured pattern reaches --------------------------------------
    check("tc1 `**` spans directories",
          M.output_covers("docs/**", "docs/a/b/c.md")
          and M.output_covers("docs/**", "docs/a.md"))
    check("tc2 ...and `*` does NOT - one star is the directory's own entries, "
          "and an fnmatch over the whole string would hand a reader who typed "
          "one star the entire subtree instead",
          M.output_covers("docs/*", "docs/a.md")
          and not M.output_covers("docs/*", "docs/a/b.md"),
          repr((M.output_covers("docs/*", "docs/a.md"),
                M.output_covers("docs/*", "docs/a/b.md"))))
    check("tc3 a trailing `/` is the directory spelling `files` already uses and "
          "means the same as `/**`",
          M.output_covers("docs/", "docs/a/b.md")
          and M.output_covers("docs/", "docs/a.md"))
    check("tc4 a bare directory name covers only ITSELF, not its contents - the "
          "two spellings are different declarations and the looser one has to be "
          "asked for",
          M.output_covers("docs", "docs")
          and not M.output_covers("docs", "docs/a.md"),
          repr((M.output_covers("docs", "docs"),
                M.output_covers("docs", "docs/a.md"))))
    check("tc5 a sibling directory whose name merely STARTS with the pattern's "
          "is not covered - the match is per segment, so `docs` does not reach "
          "`docs-old`",
          not M.output_covers("docs/**", "docs-old/a.md")
          and not M.output_covers("docs/**", "adocs/a.md"))
    check("tc6 an extension pattern under an anchored head matches within the "
          "segment and nothing else",
          M.output_covers("docs/reports/*.md", "docs/reports/q3.md")
          and not M.output_covers("docs/reports/*.md", "docs/reports/q3.html")
          and not M.output_covers("docs/reports/*.md", "docs/q3.md"))
    check("tc7 `**` in the MIDDLE spans any number of segments including none",
          M.output_covers("build/**/out.json", "build/out.json")
          and M.output_covers("build/**/out.json", "build/a/b/out.json")
          and not M.output_covers("build/**/out.json", "build/a/out.txt"))
    check("tc8 an empty pattern or an empty path covers nothing, and neither "
          "raises - False is the safe answer and is the one a gate reads as "
          "'still uncovered'",
          not M.output_covers("", "docs/a.md") and not M.output_covers("docs/**", "")
          and not M.output_covers(None, None))
    check("tc9 a Windows-spelled TARGET is matched by the same pattern - the "
          "plan gate is handed whatever the payload said, and a separator is not "
          "a declaration",
          M.output_covers("docs/**", "docs\\a\\b.md"))

    # --- the list doors --------------------------------------------------------
    clean = ["docs/**", "evidence/*.jsonl"]
    dirty = ["docs/**", "**", "*/x", "evidence/*.jsonl"]
    check("tl1 `output_problems` is empty for a clean list",
          M.output_problems(clean) == [], repr(M.output_problems(clean)))
    check("tl2 ...and reports one row per bad entry, each carrying the entry "
          "itself so the writer can quote it back",
          [p for p, _why in M.output_problems(dirty)] == ["**", "*/x"],
          repr(M.output_problems(dirty)))
    for shape in (None, "docs/**", 7, {}):
        check("tl3 %r is not a list, and the WRONG TYPE is the owning level's "
              "finding rather than a second sentence about one mistake from "
              "here" % (shape,),
              M.output_problems(shape) == [], repr(M.output_problems(shape)))
    check("tl4 `honoured` keeps the clean entries in document order",
          M.honoured(clean) == clean, repr(M.honoured(clean)))
    check("tl5 ...and DROPS every entry `output_problems` reports, which is the "
          "property the plan gate rests on: a plan carrying a whole-tree pattern "
          "covers nothing extra, rather than covering everything",
          M.honoured(dirty) == ["docs/**", "evidence/*.jsonl"],
          repr(M.honoured(dirty)))
    check("tl6 ...and the two doors agree by construction on the same list - a "
          "kept entry is one with no problem and a dropped one is one with a "
          "problem, asserted rather than assumed because they are what the "
          "writer and the reader each ask",
          (set(M.honoured(dirty)) | set(p for p, _w in M.output_problems(dirty)))
          == set(dirty)
          and not (set(M.honoured(dirty))
                   & set(p for p, _w in M.output_problems(dirty))))
    for shape in (None, "docs/**", 7):
        check("tl7 `honoured` of %r is empty, so a malformed key honours "
              "nothing" % (shape,),
              M.honoured(shape) == [], repr(M.honoured(shape)))
    check("tl8 SECOND-DIRECTION CASE: `honoured` of a list whose every entry is "
          "refused is EMPTY and not the list - a version that dropped nothing "
          "would pass every case above, because every one of them has at least "
          "one clean entry to show",
          M.honoured(["**", ".", "/etc", "../x"]) == [],
          repr(M.honoured(["**", ".", "/etc", "../x"])))

    # --- where the rule lives, and where it must not ---------------------------
    check("tx1 the rule is NOT on `_manifest_vocab` - that module's SCHEMA_ANCHORS "
          "comment declines to derive its enums from the schema partly because "
          "nothing on the per-tool-call hook path loads it, and `mv37` walks the "
          "graph to hold that. A path rule the plan gate must ask would have "
          "spent the premise for an unrelated reason",
          not any(hasattr(_vocab, name)
                  for name in ("output_pattern_problem", "output_covers",
                               "output_problems", "honoured")),
          repr([n for n in dir(_vocab) if n.startswith("output")]))
    _edges, _broken = _deps.import_graph()
    _reaches = sorted(b for a, b in _edges if a == "_task_outputs")
    check("tx2 ...and this module reaches nothing but the anchor, which is what "
          "makes it cheap enough for a hook to load by path on every uncovered "
          "write: %r" % (_reaches,),
          _reaches == ["_output"], repr((_reaches, _broken)))
    check("tx3 `_deps` places it, so the import-graph lint has an opinion about "
          "it rather than reporting it unplaced",
          "_task_outputs" in [m for layer in _deps.LAYERS for m in layer],
          repr([m for layer in _deps.LAYERS for m in layer][:3]))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__task_outputs.py --selftest\n")
    raise SystemExit(2)
