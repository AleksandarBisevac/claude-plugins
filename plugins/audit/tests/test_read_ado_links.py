#!/usr/bin/env python3
"""
The cases for `read-ado-links.py` — the manifest side of every ADO link.

WHAT IS PINNED HERE, and every one of these is a defect this command was written
for:

- **The read is the LOADER's.** On the sharded layout the file at `manifestPath` is
  an index whose phases are stubs, so a raw read finds the bugs' links and none of
  the phases' or tasks'. `rl4a` checks the fixture's own premise first — that the
  index really does hold only the bugs' ids — because without that check every
  layout case below would keep passing while testing nothing.
- **A translation nobody applies is worse than a missing one.** `rl12` runs the
  whole documented sequence, `explain-ado-drift.py` included, with and without this
  door in the middle: unstamped, the drift table reports `0 would overwrite a
  change made after our last sync` for a board where the answer is one. That is the
  number the push confirm gate exists for, and it is structurally zero without a
  `mapped` state to compare.
- **A configured `null` and an unmapped status are different answers.** `rl9` and
  `rl9b` are that pair: a `null` in `meta.ado.stateMap` is a DECISION to leave the
  card alone, a status nothing maps is a gap, and reporting both as "no state"
  would make a configured choice look like a defect.
- **A bug's pushable status is the DERIVED one.** `rl10`/`rl10b` are the two halves
  of `_manifest_io.effective_bug_status`: a materialized fix task that is done makes
  a stored `open` read `fixed`, and a human `wontfix` beats that. A hand translation
  reading `bug.status` maps a fixed bug to `New` and then calls the board's
  `Resolved` card ours to overwrite.
- **Narrowing to nothing must not read as "all clear".** `rl13` is the payload no
  link claims — exit 1, naming why — and `rl13c` is its paired positive: an EMPTY
  payload is exit 0, because nothing was asked about and the counts say so.
- **Two manifest items claiming one card is not a tie to break.** The `rl16` family
  walks every way that ends: they disagree and nothing is stamped, they agree and
  the duplicate is named anyway, or there is no duplicate and neither line fires.
  Nothing validates uniqueness of a work-item id, so this is the only surface that
  ever counts it.
- **Deliberately off the board is a CLASS, not a smaller kind of missing.** The
  `rl18`–`rl23` family is that partition: an item its plan keeps off a shared
  board is not counted unlinked, its tasks inherit that answer from
  `_ado_tracked` rather than from a second reading here, a bug is never in the
  class at all, and the three figures add up to the total for every kind so a
  reader can check the arithmetic instead of trusting it. `rl18d`, `rl21b` and
  `rl22b` are the other direction — the cases that go red when the class is
  widened until it swallows ordinary gaps, or a line becomes unconditional.
- **The third value is three-valued on purpose.** `rl21` holds where an
  unanswerable item goes: `unlinked`, never `untracked`, and named out loud.
  Being counted untracked is a licence to stop reporting a gap, and an item
  nothing had a basis to answer for has not earned one.
- **The command file is the other half of the fix.** `rl17` reads
  `commands/sync.md` and asserts every invocation of the drift door there is
  handed the STAMPED payload. The original defect was entirely in the prose, and
  a suite over this module alone would have stayed green through all of it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import re
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (the anchor: PLUGIN_ROOT)
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _ado_tracked as TRACKED                     # noqa: E402  (FIELD, spelled once)
import _manifest_io as MIO                         # noqa: E402  (the sharded WRITER)

# THE DEFECT WAS THE PROSE. Every function below was already right when the drift
# table reported nothing compared for a whole board: `commands/sync.md` simply
# never told the orchestrator to stamp the payload, and a suite over this module
# alone stayed green through all of it. `rl17` reads the command file.
DOC = os.path.join(_output.PLUGIN_ROOT, "commands", "sync.md")

M = _loader.load_script("read-ado-links.py", modname="read_ado_links")
# The door downstream, loaded so `rl12` can run the sequence `commands/sync.md`
# prints rather than a paraphrase of it. A case that asserted this file's own
# counts would prove the stamping and say nothing about what the stamping is FOR.
DRIFT = _loader.load_script("explain-ado-drift.py", modname="explain_ado_drift_rl")

SYNCED = "2026-08-21T18:02:00Z"


def _link(ado_id, origin="created"):
    return {"id": ado_id, "lastSyncedAt": SYNCED, "origin": origin}


# One document, holding every shape the translation has to answer for:
#   P1  in_progress, linked      -> a default (Agile `Active`)
#   P2  done, linked             -> a default, and the phase vocabulary's own row
#   T1.1 done, linked            -> the row a configured stateMap overrides below
#   T1.2 blocked, NOT linked     -> the unlinked half of the connector line
#   T2.1 done, linked            -> BUG-8's fix task, so `wontfix` has something to beat
#   BUG-7 open + fix task done   -> DERIVED `fixed`
#   BUG-8 wontfix + fix task done-> `wontfix` wins over the derivation
#   BUG-9 triaged, NOT linked    -> the unlinked half again, one kind over
SOURCE = {
    "meta": {"version": 2, "ado": {"organization": "test-audit-lab",
                                   "project": "audit-gate-scrum"}},
    "phases": [
        {"id": "P1", "title": "one", "status": "in_progress",
         "ado": _link(4001),
         "tasks": [{"id": "T1.1", "status": "done", "bugId": "BUG-7",
                    "ado": _link(5120)},
                   {"id": "T1.2", "status": "blocked"}]},
        {"id": "P2", "title": "two", "status": "done", "ado": _link(4002),
         "tasks": [{"id": "T2.1", "status": "done", "bugId": "BUG-8",
                    "ado": _link(5121, "imported")}]},
    ],
    "bugs": [
        {"id": "BUG-7", "status": "open", "taskId": "T1.1",
         "ado": _link(4890, "imported")},
        {"id": "BUG-8", "status": "wontfix", "taskId": "T2.1",
         "ado": _link(4891)},
        {"id": "BUG-9", "status": "triaged"},
    ],
}

# The ids the sharded INDEX does not hold, and the ones it does. Named rather than
# recounted per case, because `rl4a` checks them against the writer's real output:
# if `save_sharded` ever starts mirroring `ado` up into the stub, that case is what
# says so instead of every layout case below quietly testing nothing.
SHARD_HELD_IDS = (4001, 5120, 4002, 5121)
INDEX_HELD_IDS = (4890, 4891)

# `done` maps to `Done` and not to the default `Closed`, and `blocked` to nothing at
# all: two values chosen so a run that ignored the configuration and a run that read
# it cannot produce the same table.
CONFIGURED = {"task": {"done": "Done", "blocked": None},
              "phase": {"in_progress": "Committed"}}

# The board's side of three of those links: the phase somebody else closed after our
# sync, the task that is ours to push, and the bug that agrees with the board.
FETCHED = [
    {"id": 4001, "fields": {"System.State": "Closed",
                            "System.ChangedBy": {"displayName": "Ana Kovac"},
                            "System.ChangedDate": "2026-08-21T19:40:00Z"}},
    {"id": 5120, "fields": {"System.State": "Active",
                            "System.ChangedBy": {"displayName": "AleksandarB"},
                            "System.ChangedDate": "2026-08-21T17:10:00Z"}},
    {"id": 4890, "fields": {"System.State": "Resolved",
                            "System.ChangedDate": "2026-08-21T17:10:00Z"}},
]


# The per-ROW verdict `_ado_drift.verdict()` prints when no state was supplied.
# Spelled here once because both halves of `rl12` count it, and because the drift
# summary carries the same words at zero on purpose - a case counting the phrase
# over the whole output could not tell the two runs apart.
_UNCOMPARED = "state not compared (no mapped state supplied)"


def _write(tmp, name, payload):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _declaring_source():
    """SOURCE plus one phase declared OFF the board and one ordinary control.

    Neither new phase carries an `ado` link, so `linked` cannot move and every
    difference the cases below measure is the declaration's. P3 carries two
    tasks because INHERITANCE is the half a surface re-deriving the rule gets
    wrong - a version that read the key on phases only leaves them unlinked
    for ever - and P4 is the paired control: the same shape, no declaration,
    and it must stay `unlinked` or the class is swallowing whatever it reaches.
    """
    out = json.loads(json.dumps(SOURCE))
    out["phases"].append({"id": "P3", "title": "internal", "status": "pending",
                          TRACKED.FIELD: False,
                          "tasks": [{"id": "T3.1", "status": "pending"},
                                    {"id": "T3.2", "status": "pending"}]})
    out["phases"].append({"id": "P4", "title": "ordinary", "status": "pending",
                          "tasks": [{"id": "T4.1", "status": "pending"}]})
    return out


def _with_state_map(manifest, state_map):
    """A copy of `manifest` carrying `meta.ado.stateMap` — never a mutation of the
    module-level fixture, which every other case reads."""
    out = json.loads(json.dumps(manifest))
    out["meta"]["ado"]["stateMap"] = state_map
    return out


def _run(argv, module=None):
    """(exit code, stdout, stderr) — the printed answer is half the contract."""
    out, err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = (module or M).main(argv)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    return code, out.getvalue(), err.getvalue()


def _row(payload, kind, item_id):
    for row in payload["rows"]:
        if row["kind"] == kind and row["id"] == item_id:
            return row
    return None


def _cases(check):
    tmp = tempfile.mkdtemp(prefix="rl-")
    try:
        man = _write(tmp, "audit-plan.json", SOURCE)
        fetched = _write(tmp, "fetched.json", FETCHED)
        out_path = os.path.join(tmp, "mapped.json")

        # --- usage, and the flag pair that must not come apart -----------------
        for label, argv in (("no arguments at all", []),
                            ("a flag where the manifest goes", ["--json"]),
                            ("--items with nothing after it", [man, "--items"]),
                            ("--items followed by another flag",
                             [man, "--items", "--json"]),
                            ("--out with no --items to stamp",
                             [man, "--out", out_path])):
            code, printed, _err = _run(argv)
            check("rl1 usage error is exit 2 and prints nothing (%s): %r"
                  % (label, code), code == 2 and printed == "")
        code, printed, err = _run([man, "--items", fetched])
        check("rl2 --items without --out is REFUSED, not treated as a preview: a "
              "run that reported a translation and wrote no file is one forgotten "
              "flag away from the unstamped payload reaching the drift door, "
              "which is the whole defect: %r" % (err.strip()[:60],),
              code == 2 and printed == "" and "--items needs --out" in err)

        # --- unreadable input is never an empty answer -------------------------
        code, printed, err = _run([os.path.join(tmp, "nope.json")])
        check("rl3 a manifest that cannot be read is exit 2 saying so, never an "
              "inventory of zero links: %r" % (err.strip()[:50],),
              code == 2 and printed == ""
              and err.startswith("ERROR: cannot read/parse manifest"))
        notadict = _write(tmp, "notadict.json", ["nope"])
        code, printed, _err = _run([notadict])
        check("rl3b ...and a manifest whose root is a list is exit 2 too, not a "
              "table with nothing in it", code == 2 and printed == "")
        notalist = _write(tmp, "notalist.json", {"id": 4001})
        missing_out = os.path.join(tmp, "never-written.json")
        code, printed, err = _run([man, "--items", notalist,
                                   "--out", missing_out])
        check("rl3c a payload that is not a LIST is exit 2 and writes NO file - "
              "an unreadable input must not leave a plausible-looking payload on "
              "disk for the next command to trust",
              code == 2 and "wants a JSON list" in err
              and not os.path.exists(missing_out))

        # --- the loader, and the raw read this command exists to replace --------
        sharded_dir = os.path.join(tmp, "sharded")
        os.makedirs(sharded_dir)
        sharded = os.path.join(sharded_dir, "audit-plan.json")
        MIO.save_sharded(sharded, SOURCE)
        with open(sharded, "r", encoding="utf-8") as fh:
            index_text = fh.read()
        check("rl4a THE FIXTURE'S PREMISE, checked rather than assumed: the "
              "sharded INDEX carries the bugs' work-item ids and none of the "
              "phase or task ones. Without this, a writer that started mirroring "
              "`ado` into the stub would leave every case below green and "
              "meaningless: %r"
              % ([i for i in SHARD_HELD_IDS if str(i) in index_text],),
              all(str(i) in index_text for i in INDEX_HELD_IDS)
              and not [i for i in SHARD_HELD_IDS if str(i) in index_text])

        raw_links = len([1 for i in SHARD_HELD_IDS + INDEX_HELD_IDS
                         if str(i) in index_text])
        code, printed, _err = _run([sharded, "--json"])
        sharded_side = json.loads(printed)
        check("rl4 THE DEFECT: on the sharded layout the counts are the "
              "ASSEMBLED manifest's. Counted against what a raw read of the same "
              "index can see (%d links), because the failure mode is not an error "
              "- it is a smaller number with nothing to suggest it: %r"
              % (raw_links, sharded_side["counts"]["links"]),
              code == 0 and sharded_side["counts"]["links"] == 6
              and raw_links == len(INDEX_HELD_IDS))
        check("rl4b ...and the per-kind split is right on both sides of it, which "
              "a raw read gets wrong twice over: the phases and tasks it cannot "
              "see read as unlinked, not as missing: %r"
              % (sharded_side["kinds"],),
              sharded_side["kinds"]["phase"] == {"linked": 2, "unlinked": 0,
                                                 "untracked": 0, "total": 2}
              and sharded_side["kinds"]["task"] == {"linked": 2, "unlinked": 1,
                                                    "untracked": 0, "total": 3}
              and sharded_side["kinds"]["bug"] == {"linked": 2, "unlinked": 1,
                                                   "untracked": 0, "total": 3})
        code, printed, _err = _run([man, "--json"])
        single_side = json.loads(printed)
        check("rl5 the two layouts are asserted to AGREE, not assumed to: one "
              "document stored single-file and sharded answers identically. "
              "Storage is a choice about files and is not allowed to change what "
              "is true about somebody's board",
              code == 0 and single_side == sharded_side)
        check("rl5b ...and that is not two empty answers agreeing - each side "
              "found every link, and the items with no link are counted rather "
              "than absent: %r"
              % ({k: single_side["kinds"][k]["unlinked"] for k in M.KINDS},),
              single_side["counts"]["links"] == 6
              and sum(single_side["kinds"][k]["unlinked"]
                      for k in M.KINDS) == 2)

        os.remove(os.path.join(sharded_dir, "phases", "P2.json"))
        code, printed, err = _run([sharded])
        check("rl6 a shard that will not open is exit 2 NAMING that file, with no "
              "table at all: an inventory missing a phase is the raw read's wrong "
              "answer arrived at one layer down: %r" % (err.strip()[-40:],),
              code == 2 and printed == "" and "P2.json" in err)

        # --- the table itself: defaults, configuration, and neither -------------
        check("rl7 the built-in defaults are the Agile ones, per kind, and each "
              "row says which of the two answered it: %r"
              % ([(_row(single_side, "task", "T1.1") or {}).get("state"),
                  (_row(single_side, "phase", "P1") or {}).get("state")],),
              _row(single_side, "task", "T1.1")["state"] == "Closed"
              and _row(single_side, "phase", "P1")["state"] == "Active"
              and _row(single_side, "bug", "BUG-8")["state"] == "Closed"
              and all("built-in default" in r["basis"]
                      for r in single_side["rows"]))
        configured_man = _write(tmp, "configured.json",
                                _with_state_map(SOURCE, CONFIGURED))
        code, printed, _err = _run([configured_man, "--json"])
        conf_side = json.loads(printed)
        conf_task = _row(conf_side, "task", "T1.1")
        check("rl8 a configured stateMap BEATS the default and names itself as "
              "the basis - the fixture maps `done` to `Done` where the default is "
              "`Closed`, so a run that ignored the configuration cannot produce "
              "this table: %r" % (conf_task["state"],),
              conf_task["state"] == "Done"
              and conf_task["basis"] == "meta.ado.stateMap.task.done"
              and _row(conf_side, "phase", "P1")["state"] == "Committed")
        never_man = _write(tmp, "never.json",
                           _with_state_map(SOURCE,
                                           {"bug": {"wontfix": None}}))
        code, printed, _err = _run([never_man, "--json"])
        never_side = json.loads(printed)
        never_row = _row(never_side, "bug", "BUG-8")
        check("rl9 a `null` in the stateMap is a DECISION and not a gap: the row "
              "carries no state, is counted as `never`, and is NOT counted as a "
              "missing one - collapsing the two would make a configured choice "
              "look like a defect: %r" % (never_side["counts"],),
              never_row["state"] is None and never_row["never"] is True
              and never_side["counts"]["never"] == 1
              and never_side["counts"]["noState"] == 0)
        bogus = json.loads(json.dumps(SOURCE))
        bogus["phases"][0]["tasks"][0]["status"] = "reviewing"
        bogus_man = _write(tmp, "bogus.json", bogus)
        code, printed, _err = _run([bogus_man, "--json"])
        bogus_side = json.loads(printed)
        bogus_row = _row(bogus_side, "task", "T1.1")
        check("rl9b THE PAIRED NEGATIVE of rl9: a status nothing maps gets no "
              "invented state, is counted as a missing one and NOT as `never`, "
              "and says both places it looked: %r" % (bogus_row["basis"],),
              bogus_row["state"] is None and bogus_row["never"] is False
              and bogus_side["counts"]["noState"] == 1
              and bogus_side["counts"]["never"] == 0
              and "stateMap" in bogus_row["basis"]
              and "built-in defaults" in bogus_row["basis"])

        # --- the derived bug status, both halves --------------------------------
        bug7 = _row(single_side, "bug", "BUG-7")
        check("rl10 a bug whose fix task is done pushes its DERIVED status: the "
              "file says `open` and this says `fixed` -> `Resolved`. Reading "
              "`bug.status` gives `New`, which would report the board's Resolved "
              "card as ours to overwrite: %r" % (bug7["status"],),
              bug7["status"] == "fixed" and bug7["state"] == "Resolved"
              and "derived" in bug7["statusBasis"]
              and "T1.1" in bug7["statusBasis"])
        bug8 = _row(single_side, "bug", "BUG-8")
        check("rl10b ...and a human `wontfix` beats that derivation, which is the "
              "OTHER direction: BUG-8's fix task is done too, so a hand-written "
              "'task done means fixed' rule would map it to Resolved instead of "
              "Closed: %r" % (bug8["status"],),
              bug8["status"] == "wontfix" and bug8["state"] == "Closed"
              and bug8["statusBasis"] == "bug.status")
        code, printed, _err = _run([man])
        check("rl10c the derivation is NAMED where a person reads it, and counted "
              "even at zero - a status this table reports that the file does not "
              "carry looks like a typo until the basis is stated",
              code == 0 and printed.count("DERIVED: bug BUG-7") == 1
              and "1 status(es) derived" in printed)
        no_derivation = json.loads(json.dumps(SOURCE))
        no_derivation["bugs"][0]["taskId"] = None
        plain_man = _write(tmp, "plain.json", no_derivation)
        code, printed, _err = _run([plain_man])
        check("rl10d ...and with nothing derived the count is printed as zero "
              "with no DERIVED line under it - the second-direction case, since a "
              "line that always fires is as useless as one that never does",
              code == 0 and "0 status(es) derived" in printed
              and printed.count("DERIVED:") == 0)

        # --- stamping ----------------------------------------------------------
        code, printed, _err = _run([man, "--items", fetched, "--out", out_path])
        with open(out_path, "r", encoding="utf-8") as fh:
            stamped = json.load(fh)
        check("rl11 every entry a link claims comes back carrying `mapped`, the "
              "file is still the list the drift door reads, and the counts are "
              "printed: %r" % ([e.get("mapped") for e in stamped],),
              code == 0 and isinstance(stamped, list)
              and len(stamped) == len(FETCHED)
              # `.get`, not `[...]`: a version that stamps nothing must make
              # THIS case red and let the ones after it run - a KeyError here
              # would abort the suite and leave rl12 unproven against exactly
              # the mutation it exists for.
              and [e.get("mapped") for e in stamped] == ["Active", "Closed",
                                                         "Resolved"]
              and "3 stamped" in printed)
        check("rl11b ...and nothing else in the payload is touched: the fields "
              "the fetch wrote travel through unchanged, because the drift door "
              "reads `System.ChangedBy` and `System.ChangedDate` out of them",
              [e["fields"] for e in stamped] == [e["fields"] for e in FETCHED])

        # --- THE case the fault was recorded for -------------------------------
        drift_before = _run([man, "--items", fetched], module=DRIFT)[1]
        drift_after = _run([man, "--items", out_path], module=DRIFT)[1]
        check("rl12 THE WHOLE POINT, run as the command file prints it: without "
              "this door in the middle, `explain-ado-drift.py` compares nothing "
              "and reports `0 would overwrite` for a board where the answer is "
              "one. A zero nothing could have reached reads exactly like good "
              "news: %r" % (drift_before.count(_UNCOMPARED),),
              drift_before.count(_UNCOMPARED) == len(FETCHED)
              and "%d state not compared" % (len(FETCHED),) in drift_before
              and "0 would overwrite" in drift_before
              and "1 would overwrite" in drift_after
              # The ROW verdict, counted; the summary line prints the phrase at
              # zero by design, so counting it over the whole output would make
              # the fixed run indistinguishable from the broken one.
              and drift_after.count(_UNCOMPARED) == 0
              and "0 state not compared" in drift_after)
        check("rl12b ...and the row that would overwrite names the writer, which "
              "is only reachable once a state is there to compare: the verdict "
              "for an uncompared row says nothing about who moved the card",
              "Ana Kovac" in drift_after
              and "push would overwrite it" in drift_after
              and "push would overwrite it" not in drift_before)

        # --- narrowing to nothing, and the empty payload that is not that -------
        strangers = _write(tmp, "strangers.json",
                           [{"id": 99999, "fields": {"System.State": "New"}}])
        stranger_out = os.path.join(tmp, "stranger-mapped.json")
        code, printed, err = _run([man, "--items", strangers,
                                   "--out", stranger_out])
        check("rl13 a payload with entries in it and not one state to compare is "
              "EXIT 1 saying why: everything downstream would be a comparison "
              "with no basis, including the overwrite count the confirm gate "
              "reads: %r" % (err.strip()[:60],),
              code == 1 and err.startswith("ERROR: not one of the")
              and "nothing downstream can compare" in err
              and printed.count("NOT STAMPED: #99999 (no link)") == 1)
        check("rl13b ...and the file is still written, because the drift door has "
              "to be able to say NOT IN MANIFEST about that id rather than be "
              "handed a shorter payload that looks complete",
              os.path.exists(stranger_out)
              and json.load(open(stranger_out, "r", encoding="utf-8"))
              == [{"id": 99999, "fields": {"System.State": "New"}}])
        junk = _write(tmp, "junk.json",
                      [{"id": [1, 2], "fields": {}}, "not an object",
                       {"id": True, "fields": {}}])
        junk_out = os.path.join(tmp, "junk-mapped.json")
        code, printed, err = _run([man, "--items", junk, "--out", junk_out])
        check("rl13d a payload entry whose `id` is not a work-item id is NAMED "
              "and passed through - an unhashable one used to reach the claim "
              "lookup and raise, so a malformed payload came back as a traceback "
              "instead of as the row this command owes for everything it cannot "
              "place: %r" % (err.strip()[:40],),
              code == 1 and printed.count("NOT STAMPED") == 3
              and printed.count("(skipped)") == 1
              and printed.count("(no link)") == 2
              and os.path.exists(junk_out))
        empty = _write(tmp, "empty.json", [])
        empty_out = os.path.join(tmp, "empty-mapped.json")
        code, printed, err = _run([man, "--items", empty, "--out", empty_out])
        check("rl13c THE PAIRED POSITIVE: an EMPTY payload is exit 0 with its "
              "zeros printed. Nothing was asked about, which is a different "
              "answer from 'nothing could be answered' - and a rule that failed "
              "on both would refuse a board with no linked items at all",
              code == 0 and err == "" and "0 payload entry(s): 0 stamped" in printed)

        # --- re-running over an answer already given ----------------------------
        again_out = os.path.join(tmp, "again.json")
        code, printed, _err = _run([man, "--items", out_path, "--out", again_out])
        with open(again_out, "r", encoding="utf-8") as fh:
            again = json.load(fh)
        check("rl14 running it over its own output is idempotent - same payload, "
              "and nothing reported as restamped",
              code == 0 and again == stamped
              and "restamped" not in printed)
        wrong = [dict(FETCHED[0], mapped="Wrong")]
        wrong_path = _write(tmp, "wrong.json", wrong)
        wrong_out = os.path.join(tmp, "wrong-mapped.json")
        code, printed, _err = _run([man, "--items", wrong_path,
                                    "--out", wrong_out])
        with open(wrong_out, "r", encoding="utf-8") as fh:
            fixed = json.load(fh)
        check("rl14b ...while an entry carrying a DIFFERENT mapped state is "
              "restamped from the manifest and SAID so: a payload edited by hand "
              "between the two commands must not decide what the manifest means",
              code == 0 and fixed[0]["mapped"] == "Active"
              and printed.count("were restamped") == 1)

        # --- one card, two manifest items ---------------------------------------
        #
        # `T1.2` is the manifest's only unlinked task, so pointing it at BUG-7's
        # card makes exactly one contested id and leaves every other row alone.
        # `blocked` -> `Active` and the bug's derived `fixed` -> `Resolved`: two
        # DIFFERENT states, which is what makes this case able to tell a run that
        # refuses from a run that picks the first claimant.
        contested = json.loads(json.dumps(SOURCE))
        contested["phases"][0]["tasks"][1]["ado"] = _link(4890)
        contested_man = _write(tmp, "contested.json", contested)
        contested_out = os.path.join(tmp, "contested-mapped.json")
        code, printed, _err = _run([contested_man, "--items", fetched,
                                    "--out", contested_out])
        with open(contested_out, "r", encoding="utf-8") as fh:
            contested_items = json.load(fh)
        check("rl16 a work item TWO manifest items claim, disagreeing about its "
              "state, is left UNSTAMPED and both claimants are named - picking "
              "the one the walk reached first would push one item's status onto "
              "a card the other one owns, from a table that looks ordinary: %r"
              % ([e.get("mapped") for e in contested_items],),
              code == 0
              and [e.get("mapped") for e in contested_items]
              == ["Active", "Closed", None]
              and printed.count("NOT STAMPED: #4890 (contested)") == 1
              and printed.count("task T1.2") >= 1
              and printed.count("bug BUG-7") >= 1
              and "2 stamped" in printed and "1 contested" in printed)
        agree = json.loads(json.dumps(SOURCE))
        # T1.1 is `done` and BUG-8 is `wontfix`; both map to `Closed`, so the two
        # claimants AGREE. Same duplicate, opposite branch.
        agree["phases"][0]["tasks"][0]["ado"] = _link(4891)
        agree_man = _write(tmp, "agree.json", agree)
        agree_out = os.path.join(tmp, "agree-mapped.json")
        agree_fetched = _write(tmp, "agree-fetched.json",
                               [{"id": 4891, "fields": {"System.State": "New"}}])
        code, printed, _err = _run([agree_man, "--items", agree_fetched,
                                    "--out", agree_out])
        check("rl16b ...and when the two claimants MEAN the same state the entry "
              "IS stamped and the duplicate is still named: agreeing on a state "
              "does not make one card belonging to two items correct, and this "
              "is the only surface that ever counts it: %r"
              % (printed.splitlines()[-2:],),
              code == 0 and "1 stamped" in printed and "0 contested" in printed
              and printed.count("ALSO CLAIMED: #4891 stamped Closed") == 1)
        code, printed, _err = _run([man, "--items", fetched, "--out", out_path])
        check("rl16c THE SECOND DIRECTION, which is the one that goes red if "
              "either line ever fires unconditionally: a manifest where no card "
              "is claimed twice prints NEITHER line and counts zero, rather than "
              "reporting every ordinary row as shared",
              code == 0 and "0 contested" in printed
              and printed.count("ALSO CLAIMED") == 0
              and printed.count("NOT STAMPED") == 0)
        code, printed, _err = _run([contested_man])
        check("rl16d the INVENTORY says it too, counted even at zero and named "
              "by id - a table with two rows carrying one work-item id reads as "
              "a typo until the duplicate is stated: %r"
              % ([ln for ln in printed.splitlines() if "SHARED" in ln],),
              code == 0
              and printed.count("1 work item(s) claimed by more than one") == 1
              and printed.count("SHARED: #4890") == 1
              and "DISAGREE" in printed)
        code, printed, _err = _run([man])
        check("rl16e ...and its paired negative on the same surface: the clean "
              "manifest prints the count at ZERO with no SHARED line under it",
              code == 0
              and printed.count("0 work item(s) claimed by more than one") == 1
              and printed.count("SHARED:") == 0)

        # --- deliberately off the board is not the same as missing --------------
        #
        # `unlinked` was a SUBTRACTION - everything the manifest holds minus
        # everything carrying a link - so an item whose plan says it does not
        # belong on a shared board reported as a gap on every run, for ever. The
        # fixture's two new phases carry no link at all, so nothing below can
        # move because a link moved.
        declaring = _write(tmp, "declaring.json", _declaring_source())
        code, printed, _err = _run([declaring, "--json"])
        declaring_side = json.loads(printed)
        check("rl18 a phase declared off the board is NOT counted unlinked - it "
              "is its own class, and the subtraction that produced `unlinked` is "
              "what made one permanent false-positive row per such phase: %r"
              % (declaring_side["kinds"]["phase"],),
              code == 0
              and declaring_side["kinds"]["phase"] == {"linked": 2, "unlinked": 1,
                                                       "untracked": 1,
                                                       "total": 4})
        check("rl18b ...and its TASKS are not either, which is the half a second "
              "reading of the key gets wrong: the answer is inherited in "
              "`_ado_tracked`, so both of P3's tasks land in the third class "
              "while T1.2 and T4.1 stay ordinary gaps: %r"
              % (declaring_side["kinds"]["task"],),
              declaring_side["kinds"]["task"] == {"linked": 2, "unlinked": 2,
                                                  "untracked": 2, "total": 6})
        check("rl18c the three classes PARTITION the total for every kind, so a "
              "reader can add them up instead of trusting them - and an item "
              "counted in two classes at once makes this go red rather than "
              "quietly overshoot: %r" % (declaring_side["kinds"],),
              all(declaring_side["kinds"][k]["linked"]
                  + declaring_side["kinds"][k]["unlinked"]
                  + declaring_side["kinds"][k]["untracked"]
                  == declaring_side["kinds"][k]["total"] for k in M.KINDS))
        check("rl18d THE SECOND DIRECTION, which goes red if the class is ever "
              "widened until it over-fires: a manifest where nothing is declared "
              "reports ZERO untracked for every kind and the same unlinked "
              "figures it always did - an exemption that swallowed ordinary gaps "
              "would be the false negative traded for the false positive: %r"
              % ({k: single_side["kinds"][k] for k in M.KINDS},),
              all(single_side["kinds"][k]["untracked"] == 0 for k in M.KINDS)
              and sum(single_side["kinds"][k]["unlinked"] for k in M.KINDS) == 2)

        bug_declares = _declaring_source()
        # BUG-9 is the manifest's only unlinked bug, so if a bug could ever be
        # untracked this is the row that would move.
        bug_declares["bugs"][2][TRACKED.FIELD] = False
        bug_man = _write(tmp, "bug-declares.json", bug_declares)
        code, printed, _err = _run([bug_man, "--json"])
        bug_side = json.loads(printed)
        check("rl19 a BUG is never untracked, even carrying the key: the "
              "declaration is a property of a PHASE and a bug is owned by none, "
              "so `_ado_tracked` answers about no bug at all - and `kind_totals` "
              "still counts it, so the row stays a gap rather than vanishing: %r"
              % (bug_side["kinds"]["bug"],),
              code == 0
              and bug_side["kinds"]["bug"] == {"linked": 2, "unlinked": 1,
                                               "untracked": 0, "total": 3}
              and bug_side["kinds"]["bug"] == declaring_side["kinds"]["bug"])

        code, printed, _err = _run([man])
        check("rl20 the third figure is PRINTED for every kind including at "
              "zero - `bug` included, where the question does not apply, because "
              "a column that appears only when it is non-zero cannot be told "
              "from a column nobody computed: %r"
              % ([ln for ln in printed.splitlines() if "linked," in ln],),
              code == 0 and printed.count("deliberately untracked") == 3
              and "  phase 2 linked, 0 unlinked, 0 deliberately untracked "
                  "(2 in the manifest)" in printed
              and "  task  2 linked, 1 unlinked, 0 deliberately untracked "
                  "(3 in the manifest)" in printed
              and "  bug   2 linked, 1 unlinked, 0 deliberately untracked "
                  "(3 in the manifest)" in printed)
        code, declaring_printed, _err = _run([declaring])
        check("rl20b ...and it carries the real figures where there are some, on "
              "the same three lines - the number a reader sees is the number the "
              "JSON holds, not a second derivation: %r"
              % ([ln for ln in declaring_printed.splitlines()
                  if "linked," in ln],),
              code == 0
              and "  phase 2 linked, 1 unlinked, 1 deliberately untracked "
                  "(4 in the manifest)" in declaring_printed
              and "  task  2 linked, 2 unlinked, 2 deliberately untracked "
                  "(6 in the manifest)" in declaring_printed
              and "  bug   2 linked, 1 unlinked, 0 deliberately untracked "
                  "(3 in the manifest)" in declaring_printed)

        # --- the third value: an item nothing could answer for ------------------
        #
        # `adoTracked` is THREE-valued, and a key that is not a boolean is the
        # readable version of the third one. Such an item is NOT untracked: the
        # exemption is a licence to stop reporting a gap, and nothing here has a
        # basis to grant it. So it stays `unlinked` and is NAMED.
        unanswerable = _declaring_source()
        unanswerable["phases"].append({"id": "P5", "title": "typo",
                                       "status": "pending",
                                       TRACKED.FIELD: "nope",
                                       "tasks": [{"id": "T5.1",
                                                  "status": "pending"}]})
        unanswerable_man = _write(tmp, "unanswerable.json", unanswerable)
        code, printed, _err = _run([unanswerable_man])
        unanswerable_side = json.loads(_run([unanswerable_man, "--json"])[1])
        check("rl21 an item nothing could answer for is NOT given the untracked "
              "exemption - it stays counted as unlinked and is named on its own "
              "line, because a default chosen where the basis is missing is the "
              "confident wrong answer this feature exists to remove: %r"
              % (unanswerable_side["kinds"]["phase"],),
              code == 0
              and unanswerable_side["kinds"]["phase"] == {"linked": 2,
                                                          "unlinked": 2,
                                                          "untracked": 1,
                                                          "total": 5}
              and unanswerable_side["counts"]["unanswered"] == 2
              and printed.count("NOT ANSWERED: phase P5") == 1
              and printed.count("NOT ANSWERED: task T5.1") == 1
              and "2 plan item(s) whose %s could not be answered"
                  % (TRACKED.FIELD,) in printed)
        check("rl21b THE SECOND DIRECTION for that line: a manifest where every "
              "item IS answerable prints the figure at zero with nothing under "
              "it. A line that always fires says as little as one that never "
              "does, and this is the only case that catches it",
              "0 plan item(s) whose %s could not be answered"
              % (TRACKED.FIELD,) in declaring_printed
              and declaring_printed.count("NOT ANSWERED:") == 0)

        # --- declared off the board, and a card for it exists anyway ------------
        #
        # `link_inventory` is the authority on what `linked` means here, so the
        # link WINS and the item is counted linked - the card is there whatever
        # the plan now says. Counting it in both classes would make them
        # overshoot the total, so the leftover gets a line of its own instead.
        stale = _declaring_source()
        stale["phases"][2]["ado"] = _link(4003)
        stale_man = _write(tmp, "stale.json", stale)
        code, printed, _err = _run([stale_man])
        stale_side = json.loads(_run([stale_man, "--json"])[1])
        check("rl22 an item declared off the board that still carries a card is "
              "counted LINKED and named on its own line - a leftover nothing "
              "will push again and nothing will take down, and the one item the "
              "per-kind split cannot show: %r" % (stale_side["kinds"]["phase"],),
              code == 0
              and stale_side["kinds"]["phase"] == {"linked": 3, "unlinked": 1,
                                                   "untracked": 0, "total": 4}
              and stale_side["counts"]["untrackedLinked"] == 1
              and printed.count("STILL LINKED: phase P3") == 1
              and "1 item(s) declared off the board that still carry a link"
                  in printed
              and stale_side["kinds"]["phase"]["linked"]
                  + stale_side["kinds"]["phase"]["unlinked"]
                  + stale_side["kinds"]["phase"]["untracked"]
                  == stale_side["kinds"]["phase"]["total"])
        check("rl22b THE SECOND DIRECTION for that one too: the declaring "
              "manifest, whose off-board phase carries no card, prints the "
              "figure at zero with no line under it - so the line cannot become "
              "an unconditional note on every declared item",
              "0 item(s) declared off the board that still carry a link"
              in declaring_printed
              and declaring_printed.count("STILL LINKED:") == 0)

        # --- and all of it through the sharded layout ---------------------------
        declaring_dir = os.path.join(tmp, "declaring-sharded")
        os.makedirs(declaring_dir)
        declaring_sharded = os.path.join(declaring_dir, "audit-plan.json")
        MIO.save_sharded(declaring_sharded, _declaring_source())
        with open(declaring_sharded, "r", encoding="utf-8") as fh:
            declaring_index = fh.read()
        check("rl23 THE FIXTURE'S PREMISE, checked rather than assumed: the "
              "sharded INDEX carries neither the declaration nor one task id, so "
              "a reader reaching for `json.load` sees a phase that declares "
              "nothing and owns nothing. Without this the case below would stay "
              "green over a stub that happened to hold the key: %r"
              % (TRACKED.FIELD in declaring_index,),
              TRACKED.FIELD not in declaring_index
              and "T3.1" not in declaring_index
              and "T3.2" not in declaring_index
              and "P3" in declaring_index)
        code, printed, _err = _run([declaring_sharded, "--json"])
        check("rl23b ...and read through the loader the sharded layout reaches "
              "the tasks: the same document stored either way answers "
              "identically, which is what stops a raw read reporting a whole "
              "plan tracked by default with no task rows at all: %r"
              % (json.loads(printed)["kinds"]["task"],),
              code == 0 and json.loads(printed) == declaring_side
              and json.loads(printed)["kinds"]["task"]["untracked"] == 2)

        # --- no connector configured at all, and one switched off ---------------
        bare = _write(tmp, "bare.json", {"meta": {"version": 2},
                                         "phases": [], "bugs": []})
        code, printed, _err = _run([bare])
        check("rl15 a manifest with no meta.ado answers rather than refusing - "
              "the defaults are the answer, and the line says the map is not "
              "configured instead of leaving the reader to assume it is",
              code == 0 and "not configured" in printed
              and "0 link(s): 0 with a target state" in printed)
        disabled = _write(tmp, "disabled.json",
                          json.loads(json.dumps(SOURCE)))
        with open(disabled, "r", encoding="utf-8") as fh:
            off = json.load(fh)
        off["meta"]["ado"]["enabled"] = False
        disabled = _write(tmp, "disabled.json", off)
        code, printed, _err = _run([disabled, "--json"])
        check("rl15b ...and `enabled: false` does not gate it either: that flag "
              "stops WRITES, and this is the read-only lens an operator needs to "
              "decide whether to switch the connector back on",
              code == 0 and json.loads(printed) == single_side)
        # --- the procedure, which is the half that was actually broken --------
        with open(DOC, "r", encoding="utf-8") as fh:
            doc = fh.read()
        # Every place the command file invokes the drift door, and the payload it
        # names there. Read out of the document rather than asserted as a
        # sentence, because the defect was a step that named the UNSTAMPED file
        # and nothing anywhere compared the two descriptions.
        handed = [re.search(r"--items\s+([\w./<>-]+)",
                            doc[m.end():m.end() + 240])
                  for m in re.finditer(r"explain-ado-drift\.py", doc)]
        handed = [m.group(1) for m in handed if m]
        check("rl17 every invocation of the drift door in `commands/sync.md` is "
              "handed the STAMPED payload, counted rather than found: a step "
              "that passes `fetched.json` reports `state not compared` for the "
              "whole board and closes with the overwrite count at zero, which is "
              "the honest sentence printed where the procedure guaranteed the "
              "basis would be missing: %r" % (handed,),
              handed and all(name == "mapped.json" for name in handed))
        check("rl17b ...and this file is the door those steps run - named in "
              "both subcommands, and writing the payload they then read, so "
              "rl17 cannot be green on a document that reaches the drift door "
              "by no route at all",
              doc.count("read-ado-links.py") >= 2
              and doc.count("--items fetched.json --out mapped.json") == 2)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_read_ado_links.py --selftest\n")
    raise SystemExit(2)
