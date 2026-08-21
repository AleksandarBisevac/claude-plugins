#!/usr/bin/env python3
"""
The cases for `explain-ado-drift.py` — the door, not the rule.

`test__ado_drift.py` proves the classification. What is left for the door is
everything a caller can get wrong and everything the printed answer promises:

- **Unreadable input is exit 2, never an empty table.** A payload that is not a
  list of items, a manifest that is not an object, a missing file — each answers
  "I could not read this" rather than "no drift here", because a table of zero rows
  reads as a clean board. That is the same reasoning `check-ado-item.py` writes
  down for its own exit 2, and the same defect class as `F-P-16`.
- **Exit 0 does not mean "nothing found".** The exit code says whether the QUESTION
  could be answered. `ed7` pins that a row which would overwrite somebody still
  exits 0 — because a refusal here would label the normal state of a shared board
  an error, and would be switched off within a day.
- **The line that matters is printed when it is ZERO too.** A count that appears
  only on bad news cannot be distinguished from a count that was not computed.
- **Nothing is silently dropped.** A fetched item no link claims, and a link whose
  item was not fetched, both appear by name in the printed answer.

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

M = _loader.load_script("explain-ado-drift.py", modname="explain_ado_drift")

SYNCED = "2026-08-21T18:02:00Z"

MANIFEST = {
    "meta": {"version": 3},
    "phases": [{"id": "P1", "title": "one",
                "ado": {"id": 4001, "lastSyncedAt": SYNCED, "origin": "created"},
                "tasks": [{"id": "T1.1",
                           "ado": {"id": 5120, "lastSyncedAt": SYNCED,
                                   "origin": "created"}}]}],
    "bugs": [{"id": "BUG-7", "ado": {"id": 4890, "lastSyncedAt": SYNCED,
                                     "origin": "imported"}}],
}

# The card somebody else closed after our sync, and the card that is ours to push.
EXTERNAL = {"id": 5120, "mapped": "Active",
            "fields": {"System.State": "Closed",
                       "System.ChangedBy": {"displayName": "Ana Kovac"},
                       "System.ChangedDate": "2026-08-21T19:40:00Z"}}
OURS = {"id": 4890, "mapped": "Resolved",
        "fields": {"System.State": "Active",
                   "System.ChangedBy": {"displayName": "AleksandarB"},
                   "System.ChangedDate": "2026-08-21T17:10:00Z"}}


def _write(tmp, name, payload):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _run(argv):
    """(exit code, stdout, stderr) — the printed answer is half the contract."""
    out, err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = M.main(argv)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    return code, out.getvalue(), err.getvalue()


def _cases(check):
    tmp = tempfile.mkdtemp(prefix="ead-")
    try:
        man = _write(tmp, "audit-plan.json", MANIFEST)
        both = _write(tmp, "items.json", [EXTERNAL, OURS])

        # --- usage and unreadable input ----------------------------------------
        for label, argv in (("no arguments at all", []),
                            ("a flag where the manifest goes", ["--items", man]),
                            ("--items with nothing after it", [man, "--items"]),
                            ("--items followed by another flag",
                             [man, "--items", "--json"])):
            code, out, _err = _run(argv)
            check("ed1 usage error is exit 2 and prints NO table (%s): %r"
                  % (label, code), code == 2 and out == "")

        code, _out, err = _run([os.path.join(tmp, "nope.json"), "--items", both])
        check("ed2 a manifest that cannot be read is exit 2 and says so on stderr: "
              "%r" % (err.strip()[:60],),
              code == 2 and err.startswith("ERROR: cannot read/parse manifest"))

        notalist = _write(tmp, "notalist.json", {"id": 5120})
        code, out, err = _run([man, "--items", notalist])
        check("ed3 a payload that is not a LIST is exit 2 with an empty stdout - "
              "answering 'no drift' about input we could not read is the "
              "confident-wrong-answer this command exists to avoid: %r"
              % (err.strip()[:70],),
              code == 2 and out == "" and "wants a JSON list" in err)

        notadict = _write(tmp, "notadict.json", ["nope"])
        code, out, _err = _run([notadict, "--items", both])
        check("ed4 ...and the same rule from the other side: a manifest that is a "
              "JSON list is exit 2, not an empty inventory",
              code == 2 and out == "")

        for raw in ("later", "-5", "1.5"):
            code, out, err = _run([man, "--items", both, "--tolerance", raw])
            check("ed5 --tolerance %r is refused rather than silently defaulted, "
                  "because a margin nobody chose is a margin nobody can check"
                  % (raw,),
                  code == 2 and out == "" and err.startswith("ERROR: --tolerance"))

        # --- the answer -------------------------------------------------------
        code, out, _err = _run([man, "--items", both])
        lines = [ln for ln in out.splitlines() if ln.strip()]
        # Anchored to the TABLE region (header, rule, then one row per matched
        # item). Counting a bare `task `/`bug ` prefix over the whole output
        # counts the advice block too, which is how the first version of this
        # case claimed two rows where there is one.
        check("ed6 the happy path exits 0 and prints a header, a rule, then one "
              "row per matched item, in manifest order: %r" % (lines[:4],),
              code == 0 and lines[0].startswith("kind")
              and set(lines[1]) <= set("- ")
              and lines[2].startswith("task ") and "#5120" in lines[2]
              and lines[3].startswith("bug ") and "#4890" in lines[3])
        check("ed7 EXIT 0 EVEN THOUGH one row would overwrite somebody: the code "
              "says whether the question could be answered, not what the answer "
              "was. A refusal here would call the normal state of a shared board "
              "an error", code == 0 and "would overwrite" in out)
        check("ed8 the external row names the writer and the moment, so the reader "
              "can go ask that person rather than guess",
              "Ana Kovac" in out and "2026-08-21T19:40:00Z" in out)
        check("ed9 ...and each row carries the card's ORIGIN, which is what lets a "
              "push plan say it is about to write to a card it did not create",
              "created here" in out and "imported from ADO" in out)
        check("ed10 the two rows draw DIFFERENT actions - the whole finding is "
              "that they used to draw one: %r"
              % ([ln for ln in lines if ln.startswith(("task T1.1", "bug BUG-7"))
                  and ":" in ln],),
              "bug BUG-7 (#4890): push" in out
              and "task T1.1 (#5120): reconcile deliberately" in out)
        check("ed11 the state cell shows the mapped status AND the ADO state, so "
              "the difference is legible without a second command",
              "Active -> Closed" in out and "Resolved -> Active" in out)

        # --- the zero case, and what was not looked at ------------------------
        only_sync = _write(tmp, "insync.json",
                           [{"id": 4890, "mapped": "Active",
                             "fields": {"System.State": "Active",
                                        "System.ChangedDate": SYNCED}}])
        code, out, _err = _run([man, "--items", only_sync])
        check("ed12 the overwrite count is printed when it is ZERO too - a number "
              "that appears only on bad news cannot be told apart from a number "
              "nobody computed", code == 0
              and "0 would overwrite a change made after our last sync" in out)
        check("ed13 ...and the items that were NOT fetched are named, because 'we "
              "did not look at it' and 'it is fine' are different answers",
              "NOT FETCHED: phase P1 -> #4001" in out
              and "NOT FETCHED: task T1.1 -> #5120" in out)
        check("ed14 a row with no drift draws no action line, so the advice block "
              "is not padded with rows that need nothing",
              "(#4890): push" not in out)

        stranger = _write(tmp, "stranger.json",
                          [{"id": 99999, "fields": {"System.State": "New"}}])
        code, out, _err = _run([man, "--items", stranger])
        check("ed15 a fetched work item no manifest link claims is reported by id, "
              "not dropped into a shorter table that looks complete",
              code == 0 and "NOT IN MANIFEST: #99999" in out)

        # --- machine readable -------------------------------------------------
        code, out, _err = _run([man, "--items", both, "--json"])
        try:
            payload = json.loads(out)
        except ValueError:
            payload = None
        check("ed16 --json is parseable and carries both halves: the rows and the "
              "summary a caller would otherwise recount itself",
              code == 0 and isinstance(payload, dict)
              and payload["summary"]["external"] == 1
              and payload["summary"]["localAhead"] == 1
              and len(payload["result"]["rows"]) == 2)
        check("ed17 ...and the tolerance in force travels in it, so a stored "
              "answer can be re-judged without guessing the margin",
              payload["result"]["tolerance"] == M._drift.DEFAULT_TOLERANCE_S)

        code, out, _err = _run([man, "--items", both, "--tolerance", "86400"])
        check("ed18 a margin wide enough to swallow the gap reclassifies the "
              "external row - which is the knob doing its job, and the case that "
              "would go red if --tolerance stopped being wired through",
              code == 0
              and "0 would overwrite a change made after our last sync" in out)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_explain_ado_drift.py --selftest\n")
    raise SystemExit(2)
