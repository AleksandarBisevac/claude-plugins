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
import _manifest_io as MIO                         # noqa: E402  (the sharded WRITER)

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


# --- the two layouts ------------------------------------------------------------
# `layout` is a CHOICE, not a version: both shapes are current, and a link means the
# same thing in either. What differs is WHERE it sits. In the sharded layout the
# phase stub in the index keeps `id`/`title`/`shard` and nothing else, so a phase's
# own `ado` and every task's `ado` live in the shard BODY, while `bugs[]` stays in
# the index. That is what separates the two implementations of this command: a bare
# `json.load` of the index finds the bug link and none of the others, and reports the
# rest as work items no manifest claims - which is what a real board saw.
LAYOUT_SOURCE = {
    "meta": {"version": 2},
    "phases": [
        {"id": "P1", "title": "one", "status": "in_progress",
         "ado": {"id": 4001, "lastSyncedAt": SYNCED, "origin": "created"},
         "tasks": [{"id": "T1.1",
                    "ado": {"id": 5120, "lastSyncedAt": SYNCED,
                            "origin": "created"}}]},
        {"id": "P2", "title": "two", "status": "pending",
         "ado": {"id": 4002, "lastSyncedAt": SYNCED, "origin": "imported"},
         "tasks": [{"id": "T2.1",
                    "ado": {"id": 5121, "lastSyncedAt": SYNCED,
                            "origin": "imported"}}]},
    ],
    "bugs": [{"id": "BUG-7", "ado": {"id": 4890, "lastSyncedAt": SYNCED,
                                     "origin": "imported"}}],
}

# The ids the sharded index does NOT hold, and the one it does. Named rather than
# recounted per case, because `ed19a` checks the fixture's PREMISE against them: if
# the writer ever started mirroring `ado` into the stub, every case below would go on
# passing while testing nothing, and that case is what says so instead.
SHARD_HELD_IDS = (4001, 5120, 4002, 5121)
INDEX_HELD_ID = 4890

# One fetched item per link KIND, in that order, so a row that vanishes is visible as
# a missing kind and not merely as a smaller number. The phase was moved by somebody
# else after our sync, the task is ours to push, the bug agrees with the board.
LAYOUT_ITEMS = [
    {"id": 4001, "mapped": "Active",
     "fields": {"System.State": "Closed",
                "System.ChangedBy": {"displayName": "Ana Kovac"},
                "System.ChangedDate": "2026-08-21T19:40:00Z"}},
    {"id": 5120, "mapped": "Resolved",
     "fields": {"System.State": "Active",
                "System.ChangedBy": {"displayName": "AleksandarB"},
                "System.ChangedDate": "2026-08-21T17:10:00Z"}},
    {"id": INDEX_HELD_ID, "mapped": "Active",
     "fields": {"System.State": "Active", "System.ChangedDate": SYNCED}},
]


def _write_layouts(tmp):
    """`(single-file path, sharded index path)` for ONE document stored both ways.

    The sharded side is written by `_manifest_io.save_sharded` — the writer
    `/audit:migrate` ships — and not by hand. A hand-written index would encode what
    the author BELIEVES the layout is, and that belief is the thing under test here;
    going through the real writer means the fixture moves whenever the layout does.
    """
    single_dir = os.path.join(tmp, "single")
    sharded_dir = os.path.join(tmp, "sharded")
    os.makedirs(single_dir)
    os.makedirs(sharded_dir)
    single = os.path.join(single_dir, "audit-plan.json")
    with open(single, "w", encoding="utf-8") as fh:
        json.dump(LAYOUT_SOURCE, fh)
    sharded = os.path.join(sharded_dir, "audit-plan.json")
    MIO.save_sharded(sharded, LAYOUT_SOURCE)
    return single, sharded


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

        # --- the sharded layout, and the single-file one agreeing with it -------
        single, sharded = _write_layouts(tmp)
        items = _write(tmp, "layout-items.json", LAYOUT_ITEMS)

        with open(sharded, "r", encoding="utf-8") as fh:
            index_text = fh.read()
        check("ed19a THE FIXTURE'S PREMISE, checked rather than assumed: the "
              "sharded INDEX holds the bug's work-item id and none of the phase "
              "or task ones - those went into the shard bodies. If the writer "
              "ever mirrors `ado` up into the stub, this is what says so; without "
              "it every case below would keep passing while testing nothing: %r"
              % ([i for i in SHARD_HELD_IDS if str(i) in index_text],),
              str(INDEX_HELD_ID) in index_text
              and not [i for i in SHARD_HELD_IDS if str(i) in index_text])

        code, out, _err = _run([sharded, "--items", items, "--json"])
        try:
            sharded_payload = json.loads(out)
        except ValueError:
            sharded_payload = None
        check("ed19 THE DEFECT: on the sharded layout every fetched item finds its "
              "link, INCLUDING the phase's own and the task's, which live in a "
              "shard file the index only points at. Counted per kind, because a "
              "raw read of the index matches the bug alone and a bare row total "
              "would not say which two went missing: %r"
              % (None if sharded_payload is None
                 else [r.get("kind") for r in sharded_payload["result"]["rows"]],),
              code == 0 and isinstance(sharded_payload, dict)
              and [r["kind"] for r in sharded_payload["result"]["rows"]]
              == ["phase", "task", "bug"]
              and sharded_payload["summary"]["unlinked"] == 0)
        check("ed19b ...and the printed answer carries no NOT IN MANIFEST line at "
              "all - counted, not looked for, because that line is the exact "
              "wrong answer the raw read produced and one survivor is still wrong",
              _run([sharded, "--items", items])[1].count("NOT IN MANIFEST:") == 0)
        check("ed19c ...while the links nobody fetched are still named, one per "
              "shard-held item left over. The shard walk has to find them too, and "
              "a loader that read only the index would report nothing unfetched "
              "because it would believe the manifest has nothing in it",
              sorted(r["adoId"] for r in sharded_payload["result"]["unfetched"])
              == [4002, 5121])

        # THE NEGATIVE HALF OF ed19b. A "fix" that stopped emitting NOT IN MANIFEST
        # would pass every case above and would be the same silence one step over,
        # so the line must still fire on the sharded layout when it is TRUE.
        stranger_only = _write(tmp, "layout-stranger.json",
                               [{"id": 99999, "fields": {"System.State": "New"}}])
        code, out, _err = _run([sharded, "--items", stranger_only])
        check("ed20 a work item no sharded manifest link claims IS reported, "
              "exactly once - the shard walk must not turn the line off, only "
              "stop it firing on links it can now see",
              code == 0 and out.count("NOT IN MANIFEST:") == 1
              and "NOT IN MANIFEST: #99999" in out)

        code, out, _err = _run([single, "--items", items, "--json"])
        try:
            single_payload = json.loads(out)
        except ValueError:
            single_payload = None
        check("ed21 THE TWO LAYOUTS ARE ASSERTED TO AGREE, not assumed to: the "
              "same document stored single-file and sharded answers identically, "
              "rows and summary alike. Storage is a choice about files; it is not "
              "allowed to change what is true about somebody's board",
              code == 0 and single_payload is not None
              and single_payload == sharded_payload)
        check("ed21b ...and that agreement is not two empty answers agreeing - "
              "each side matched every fetched item and left the same links "
              "unfetched",
              single_payload is not None
              and single_payload["summary"]["total"] == len(LAYOUT_ITEMS)
              and single_payload["summary"]["external"] == 1
              and single_payload["summary"]["localAhead"] == 1)

        # A shard that will not open. Exit 2 and NOTHING on stdout: a table missing
        # a phase is the raw read's answer arrived at one layer down, and it reads
        # as a clean board for the half that was silently dropped.
        os.remove(os.path.join(tmp, "sharded", "phases", "P2.json"))
        code, out, err = _run([sharded, "--items", items])
        check("ed22 a shard that cannot be read is exit 2 naming THAT file, with "
              "no table at all - never a drift answer about the phases that "
              "happened to load: %r" % (err.strip()[-70:],),
              code == 2 and out == ""
              and err.startswith("ERROR: cannot read/parse manifest")
              and "P2.json" in err)
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
