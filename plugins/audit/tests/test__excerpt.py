#!/usr/bin/env python3
"""
The cases for `_excerpt.py` - how a failing tool's output is quoted in a sentence.

WHAT IS PINNED, and why each one is here rather than trusted:

- **Both ends survive.** The fixture puts a distinct token at each end and the
  failing check in the middle, so a head-only cut, a tail-only cut and a cut that
  keeps neither end each fail a different case.
- **A cut says so, and says how much.** A short output and a shortened one must
  not read alike, and the count is checked against the text actually dropped.
- **Text that fits is returned whole**, so the marker is not unconditional.
- **The failure lines are the ones from the dropped middle**, deduplicated and
  bounded, with the overflow counted.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _excerpt as M                               # noqa: E402


def _cases(check):
    fits = "short output\n"
    check("ex1 text that fits comes back stripped and whole, with no marker: %r"
          % (M.excerpt(fits),),
          M.excerpt(fits) == "short output" and M.excerpt(None) == ""
          and M.excerpt("x" * (M.HEAD_CHARS + M.TAIL_CHARS)) == "x" * (
              M.HEAD_CHARS + M.TAIL_CHARS))

    middle = "".join("[STARTED] step %d\n" % (i,) for i in range(60))
    text = "HEADTOKEN begins\n" + middle + "✖ prettier failed on lib/a.ts\n" \
        + middle + "TAILTOKEN ends"
    got = M.excerpt(text)
    dropped = len(text) - M.HEAD_CHARS - M.TAIL_CHARS
    check("ex2 a long output keeps its head AND its tail, so neither a head-only "
          "nor a tail-only cut passes: %r" % (got,),
          got.startswith("HEADTOKEN") and got.endswith("TAILTOKEN ends")
          and len(got) <= M.MAX_CHARS)
    check("ex3 ...says how many chars it dropped, counted off the text and not "
          "typed: %r" % (got,),
          "[... %d chars elided" % (dropped,) in got)
    check("ex4 ...and rescues the failure line from the dropped middle, which "
          "neither end held: %r" % (got,),
          "prettier failed on lib/a.ts" in got
          and "prettier failed" not in text[:M.HEAD_CHARS]
          and "prettier failed" not in text[-M.TAIL_CHARS:])

    quiet = "A" * 50 + "\n" + "b\n" * 400 + "Z" * 50
    check("ex5 a dropped middle with no failure line gets the count and no list "
          "- the allow case for ex4, which fails if the list is unconditional: %r"
          % (M.excerpt(quiet),),
          "failure lines" not in M.excerpt(quiet) and "elided" in M.excerpt(quiet))

    many = "head\n" + "".join("FAIL case %d\n" % (i % 6,) for i in range(40)) \
        + "z" * 300
    kept, more = M.failure_lines(many)
    check("ex6 failure lines are distinct and bounded, the overflow counted "
          "rather than hidden: %r / %d" % (kept, more),
          len(kept) == M.MAX_LINES and len(set(kept)) == len(kept) and more == 3
          and "(+3 more)" in M.excerpt(many))

    check("ex7 every shape the tools print is a failure line: lint-staged's "
          "cross, a runner's FAIL, node's ERR_ code and a plain error",
          all(M.failure_lines("x\n%s\ny" % (ln,))[0]
              for ln in ("✖ lint", "FAIL a.test", "ERR_MODULE_NOT_FOUND",
                         "TypeError: bad")))

    check("ex8 reason_of takes the first stream that says anything, so the "
          "err-or-out idiom keeps its meaning, and an all-blank pair is empty: "
          "%r" % (M.reason_of("  \n", "out text"),),
          M.reason_of("", "out text") == "out text"
          and M.reason_of("err", "out") == "err"
          and M.reason_of(None, "  ") == "")

    check("ex9 is_excerpt recognises what excerpt produced and nothing else - a "
          "writer sizing a field from it must not mistake free text for a quoted "
          "output: %r" % (M.excerpt(text)[:40],),
          M.is_excerpt(M.excerpt(text)) and not M.is_excerpt(text)
          and not M.is_excerpt(fits) and not M.is_excerpt(None)
          and not M.is_excerpt("chars elided"))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__excerpt.py --selftest\n")
    raise SystemExit(2)
