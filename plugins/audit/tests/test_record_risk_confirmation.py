#!/usr/bin/env python3
"""
The cases for `record-risk-confirmation.py` — the high-risk gate answered before the
run, and the bounding that keeps that from being the gate deleted.

`record-risk-confirmation.py` is hyphenated, so it comes through `_loader.load_script`
and this file substitutes underscores; `test_set_priority.py` is the precedent for both
halves of that rule. Every fixture lives under one `tempfile.mkdtemp()` removed in a
single `finally`.

WHAT IS PINNED, and why each one is here rather than trusted:

- **THE COVERED SET IS AN EQUALITY, NOT A MEMBERSHIP.** Every scope case asserts the
  whole list, because "the id I expected is in there" passes just as happily on a
  command that covered the entire plan — which is precisely the mutation this feature
  has to survive. The `c` block is built so that a widening in any one of the three
  narrowings (the phase, `risk: "high"`, open work only) puts a DIFFERENT id in the
  list and turns a case red: the fixture carries a high-risk task in a sibling phase,
  a `med` task beside the covered one, and a `done` high-risk task in the same phase.

- **A blank answer, an unknown phase and a phase with nothing to confirm are three
  different refusals**, and none of them writes a row. The last one is the one worth
  spelling out: an empty confirmation would be a standing permission with no subject.

- **An unreadable manifest is NOT the "nothing to confirm" refusal.** The safe loader
  answers `{}` for a file that will not parse, and `{}` reaches the empty-covered-set
  branch — so the command would tell an operator their phase was clear when the truth
  is that nothing was read. The case pins the two messages apart.

- **The words go in BYTE FOR BYTE.** The fixture value carries a trailing space and
  punctuation a smoother would tidy, because a paraphrase is what the rule this
  follows exists to forbid.

- **A journal that is off is exit 1 and NOT recorded**, not a silent success. The row
  is the whole deliverable here, which is the opposite of `close-phase`'s fail-soft
  append, and a caller that read "0" would proceed believing it had an answer.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _journal_io                                 # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("record-risk-confirmation.py",
                        modname="record_risk_confirmation")

# The operator's own words, chosen to tell a verbatim write from a tidied one: a
# trailing space, a double space, and an em dash a smoother would normalise.
WORDS = "Ship it  — I am off the keyboard until Monday. "


def _base_manifest():
    """One phase whose three tasks differ in exactly the fields the scope reads, and
    a sibling phase carrying a high-risk task of its own.

    P1.1 is the answer's subject. P1.2 is high-risk and DONE, P1.3 is open and `med`,
    P2.1 is open and high-risk in another phase — one per narrowing, so a widening of
    any one of them changes the list rather than leaving it alone.
    """
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P1", "title": "One", "status": "pending", "tasks": [
                {"id": "P1.1", "title": "a", "status": "pending", "risk": "high"},
                {"id": "P1.2", "title": "b", "status": "done", "risk": "high"},
                {"id": "P1.3", "title": "c", "status": "pending", "risk": "med"},
            ]},
            {"id": "P2", "title": "Two", "status": "pending", "tasks": [
                {"id": "P2.1", "title": "d", "status": "pending", "risk": "high"},
            ]},
        ],
    }


# --- cases --------------------------------------------------------------------
# Letters taken in this file (NEW file -- fresh letter space): c (the covered set,
# which is the safety property), r (the row), e (refusals), f (fail-loud), j (output).
def _cases(check):
    root = tempfile.mkdtemp(prefix="record-risk-confirmation-selftest-")

    def project(manifest=None, journal_enabled=None):
        """A project directory with a manifest and a `.claude/` the journal finds."""
        d = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(d, ".claude"))
        os.makedirs(os.path.join(d, "docs", "audit"))
        cfg = {"manifestPath": "docs/audit/audit-plan.json"}
        if journal_enabled is not None:
            cfg["journal"] = {"enabled": journal_enabled}
        with open(os.path.join(d, ".claude", "audit.config.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        mpath = os.path.join(d, "docs", "audit", "audit-plan.json")
        data = manifest if manifest is not None else _base_manifest()
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        return d, mpath

    def run(argv):
        lines = []
        code = M.main(argv, out=lines.append)
        return code, "\n".join(lines)

    def rows(proj):
        return [r for r in _journal_io.read_all(proj)
                if r.get("action") == M.ACTION_RISK_CONFIRMED]

    try:
        # --- the covered set: the whole safety property ------------------------
        d, mp = project()
        code, out = run([mp, "P1", "--confirm-high-risk", WORDS, "--json"])
        answer = json.loads(out) if code == 0 else {}
        check("c1 the answer covers EXACTLY the open high-risk tasks of the phase "
              "it was given about. Asserted as an equality: 'P1.1 is in the list' "
              "passes just as well on a command that covered the whole plan, which "
              "is the mutation this feature exists to survive",
              code == 0 and answer.get("covered") == ["P1.1"],
              "%r %r" % (code, answer.get("covered")))
        check("c2 ...so P2.1 is NOT in it. A high-risk task in a SIBLING phase is "
              "work the operator was not looking at when they answered; covering it "
              "would let one answer discharge the gate in a phase nobody opened",
              "P2.1" not in (answer.get("covered") or []),
              repr(answer.get("covered")))
        check("c3 ...and P1.3 is not, though it sits in the named phase: the gate "
              "asks about `risk: \"high\"`, and an answer that covered `med` too "
              "would answer a question nobody put",
              "P1.3" not in (answer.get("covered") or []),
              repr(answer.get("covered")))
        check("c4 ...and P1.2 is not, though it is high-risk in the named phase: it "
              "is DONE, so it has no commit left to confirm, and listing it would "
              "make the answer look wider than the work it can reach",
              "P1.2" not in (answer.get("covered") or []),
              repr(answer.get("covered")))

        cancelled = _base_manifest()
        cancelled["phases"][0]["tasks"][1]["status"] = "cancelled"
        d2, mp2 = project(manifest=cancelled)
        _code, out2 = run([mp2, "P1", "--confirm-high-risk", WORDS, "--json"])
        check("c5 `cancelled` is terminal for this exactly as `done` is - both come "
              "from `_manifest_io.TERMINAL` rather than from a list written here, so "
              "a third terminal state would be covered the day it is added",
              json.loads(out2).get("covered") == ["P1.1"], repr(out2[:120]))

        grown = _base_manifest()
        grown["phases"][0]["tasks"].append(
            {"id": "P1.4", "title": "e", "status": "pending", "risk": "high"})
        check("c6 a task that becomes high-risk AFTER the answer is not in the "
              "answer: the same call over a grown phase returns a different list, "
              "which is what makes the row a record of what was asked rather than a "
              "rule that goes on answering",
              M.covered_tasks(_base_manifest(), "P1") == ["P1.1"]
              and M.covered_tasks(grown, "P1") == ["P1.1", "P1.4"],
              repr(M.covered_tasks(grown, "P1")))

        # --- the row -----------------------------------------------------------
        check("r1 exactly ONE row is appended, and it carries its own action and "
              "the phase as its target - a row borrowed from another verb would "
              "answer a different question under a familiar word",
              len(rows(d)) == 1
              and rows(d)[0].get("action") == "risk.confirmed"
              and rows(d)[0].get("target") == "P1",
              repr([(r.get("action"), r.get("target")) for r in rows(d)]))
        check("r2 the operator's words are in the row BYTE FOR BYTE - trailing "
              "space, double space and em dash included. The fixture is chosen so a "
              "strip() or a smoother disagrees with a verbatim write",
              (rows(d)[0].get("details") or {}).get("reason") == WORDS,
              repr((rows(d)[0].get("details") or {}).get("reason")))
        check("r3 ...and the summary names every covered id, so a reader of the "
              "trail alone can see WHAT was answered for and not only that "
              "something was",
              "P1.1" in str(rows(d)[0].get("summary")),
              repr(rows(d)[0].get("summary")))
        check("r4 ...and the chain still holds after the append",
              _journal_io.verify(d).get("findings") == [],
              repr(_journal_io.verify(d).get("findings")))
        check("r5 the row's `phaseId` is a structured detail, not prose a reader "
              "has to parse back out of the summary",
              (rows(d)[0].get("details") or {}).get("phaseId") == "P1",
              repr(rows(d)[0].get("details")))

        # --- refusals ----------------------------------------------------------
        d3, mp3 = project()
        code, out = run([mp3, "P1", "--confirm-high-risk", "   "])
        check("e1 a blank answer is a usage error and writes NOTHING. The value IS "
              "the confirmation, so there is nothing to record and a row saying "
              "somebody answered would be the trail's worst shape",
              code == 2 and rows(d3) == [] and "blank" in out,
              "%r %r" % (code, out[:90]))

        code, out = run([mp3, "P9", "--confirm-high-risk", WORDS])
        check("e2 an unknown phase is a usage error that NAMES the ids that exist",
              code == 2 and "P1" in out and "P2" in out and rows(d3) == [],
              "%r %r" % (code, out[:110]))

        code, out = run([mp3, "p1", "--confirm-high-risk", WORDS])
        check("e3 ...and `p1` is P1, through the shared resolver rather than a "
              "fourth answer invented here",
              code == 0 and len(rows(d3)) == 1, "%r %r" % (code, out[:90]))

        clear = {"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "One", "status": "pending", "tasks": [
                {"id": "P1.1", "title": "a", "status": "pending", "risk": "low"}]}]}
        d4, mp4 = project(manifest=clear)
        code, out = run([mp4, "P1", "--confirm-high-risk", WORDS])
        check("e4 a phase with no open high-risk task is REFUSED, not recorded as "
              "an empty row: a confirmation with no subject is a standing "
              "permission that answers for whatever appears next",
              code == 2 and rows(d4) == [] and "nothing for a confirmation" in out,
              "%r %r" % (code, out[:130]))

        only_done = {"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "One", "status": "pending", "tasks": [
                {"id": "P1.1", "title": "a", "status": "done", "risk": "high"}]}]}
        d5, mp5 = project(manifest=only_done)
        code, _out = run([mp5, "P1", "--confirm-high-risk", WORDS])
        check("e5 ...and a phase whose only high-risk task is already done reaches "
              "that same refusal, which is the terminal narrowing seen from the "
              "other side",
              code == 2 and rows(d5) == [], repr(code))

        d6, mp6 = project()
        with open(mp6, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        code, out = run([mp6, "P1", "--confirm-high-risk", WORDS])
        check("e6 an unreadable manifest says SO, and is not the 'nothing to "
              "confirm' refusal. The safe loader answers {} for a file that will "
              "not parse, and {} reaches the empty-covered-set branch - which would "
              "tell an operator their phase was clear when nothing was read",
              code == 2 and "cannot read/parse" in out
              and "nothing for a confirmation" not in out,
              "%r %r" % (code, out[:130]))

        # --- fail-loud ---------------------------------------------------------
        d7, mp7 = project(journal_enabled=False)
        code, out = run([mp7, "P1", "--confirm-high-risk", WORDS])
        check("f1 a journal that is OFF is exit 1 and says the confirmation was not "
              "recorded. The row is the whole deliverable here - the opposite of "
              "close-phase's fail-soft append, where the merge had already happened "
              "- so a 0 would leave the caller believing it held an answer",
              code == 1 and "would leave no record" in out,
              "%r %r" % (code, out[:130]))

        # --- output ------------------------------------------------------------
        d8, mp8 = project()
        code, out = run([mp8, "P1", "--confirm-high-risk", WORDS])
        check("j1 the human block prints the covered ids and the operator's own "
              "words back, which is this command's answer to a shell that ate a "
              "clause: the operator reads their sentence before the run proceeds",
              code == 0 and "P1.1" in out and WORDS.strip() in out,
              "%r %r" % (code, out[:160]))
        check("j2 ...and it prints what is NOT covered. A flag called `confirm` "
              "reads as a blanket permission, and the line saying otherwise is the "
              "difference between a gate answered and a gate deleted",
              "NOT covered" in out and "still stop and ask" in out, repr(out[-200:]))
        check("j3 --json carries the same answer as data, row path included",
              json.loads(run([mp8, "P1", "--confirm-high-risk", WORDS, "--json"])[1])
              .get("row", "").endswith(".jsonl"), "")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_record_risk_confirmation.py --selftest\n")
    raise SystemExit(2)
