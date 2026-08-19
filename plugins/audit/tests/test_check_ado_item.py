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
