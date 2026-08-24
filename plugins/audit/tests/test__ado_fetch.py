#!/usr/bin/env python3
"""
The cases for `_ado_fetch.py` — the rule, not the door.

`test_fetch_ado_items.py` proves the command. What is left for the rule is the
three things a prose instruction could not be held to, which is why this module
exists at all:

- **The chunk boundary is walked AT the size, not under it.** A chunker tested only
  with fewer ids than the limit passes with `size` ignored entirely. The cases below
  sit at `size - 1`, `size`, `size + 1` and `2 * size`, because those are where an
  off-by-one lives and nowhere else is.
- **The ceiling is on the WIQL TEXT.** `WIQL_MAX_CHARS` is the invariant and
  `DEFAULT_CHUNK` is only an operating point far below it, so the length is measured
  every time rather than inferred from a count of ids.
- **A bound produces a NAMED outcome, never a hang and never a bare empty list.**
  `TIMED_OUT` and `OK` with no rows are different answers about the same board, and
  a caller that cannot tell them apart will print a clean table for a board it never
  reached.

Every positive here is paired with its negative: a chunk that fits is *not* reported
oversized, a call that succeeds is *not* reported as timed out, and an id that came
back is *not* listed as missing.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ado_fetch as M                             # noqa: E402
import _ado_conventions as _conv                   # noqa: E402  (F106: the shape
#   this module PRODUCES is graded by that one, and the cases below hand it the
#   producer's own return value rather than a fixture that resembles it)

SYNCED = "2026-08-21T18:02:00Z"

# Links in the three places a manifest puts them, so `linked_ids` is proven to walk
# all three rather than whichever one the fixture happened to fill.
MANIFEST = {
    "meta": {"version": 2, "ado": {"organization": "acme", "project": "store"}},
    "phases": [{"id": "P1", "title": "one",
                "ado": {"id": 4001, "lastSyncedAt": SYNCED},
                "tasks": [{"id": "T1.1", "ado": {"id": 5120}},
                          {"id": "T1.2"}]}],
    "bugs": [{"id": "BUG-7", "ado": {"id": 4890}}],
}


class _Done(object):
    """A completed-process stand-in: the three attributes `run_chunk` reads."""

    def __init__(self, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _rows(*ids):
    """Board rows in the shape `az boards query` really returns (measured)."""
    return "[%s]" % (",".join(
        '{"id": %d, "fields": {"System.Id": %d, "System.State": "Active",'
        ' "System.ChangedBy": {"displayName": "Ana Kovac",'
        ' "uniqueName": "ana@example.com"},'
        ' "System.ChangedDate": "2026-08-22T10:51:38.37Z"}}' % (i, i)
        for i in ids),)


def _ok_runner(*ids):
    def run(_argv, _timeout):
        return _Done(0, _rows(*ids))
    return run


def _timeout_runner(argv, timeout):
    raise subprocess.TimeoutExpired(argv, timeout)


def _cases(check):
    # --- the chunk boundary, AT the size -------------------------------------
    size = 7
    for count, want in ((size - 1, [size - 1]), (size, [size]),
                        (size + 1, [size, 1]), (2 * size, [size, size])):
        got = [len(group) for group in M.chunk_ids(list(range(count)), size)]
        check("af1 %d id(s) at chunk %d split as %r - the boundary is walked AT "
              "the size and one past it, which is the only place an off-by-one "
              "lives; a chunker tested only below the limit passes with the "
              "limit ignored" % (count, size, got), got == want)

    check("af2 ...and nothing is lost or reordered in the split: the groups "
          "concatenate back to the input, in the input's order",
          [i for group in M.chunk_ids(list(range(20)), size) for i in group]
          == list(range(20)))

    check("af3 an empty id list is NO queries, not one query asking for nothing "
          "- an `IN ()` would be a syntax error sent to a board for no reason",
          M.chunk_ids([], size) == [])

    check("af4 a repeated id is sent ONCE: two manifest items may legitimately "
          "link the same work item, and asking twice returns one row for two "
          "requests, which reads downstream as an item that went missing",
          M.chunk_ids([5, 5, 6, 5, 7], size) == [[5, 6, 7]])

    for bad in (0, -1, None):
        try:
            M.chunk_ids([1, 2], bad)
            refused = False
        except ValueError:
            refused = True
        check("af5 a chunk size of %r is REFUSED, not silently defaulted - a "
              "limit nobody chose is a limit nobody can check, and 0 would loop "
              "forever" % (bad,), refused)

    # --- the ceiling is on the TEXT ------------------------------------------
    narrow = M.wiql_for(list(range(1, 201)))
    check("af6 a full default-size chunk of ordinary ids is FAR inside the "
          "service's ceiling (%d of %d characters) - that headroom is the whole "
          "reason the operating point is an id count rather than the limit "
          "itself" % (len(narrow), M.WIQL_MAX_CHARS),
          len(narrow) < M.WIQL_MAX_CHARS // 4)
    check("af7 ...and it is NOT reported oversized. The negative half of af8: a "
          "checker that always fired would pass af8 and make every query a "
          "refusal", M.oversized_queries([narrow]) == [])

    # Ids wide enough to blow the text budget at a size a COUNT-based rule would
    # wave through. This is the fixture that separates the two implementations.
    wide = [10 ** 17 + i for i in range(2000)]
    long_query = M.wiql_for(wide)
    over = M.oversized_queries([narrow, long_query])
    check("af8 a chunk whose ids are WIDE is caught by measuring the text, even "
          "though its id COUNT is smaller than one that fits - the ceiling is on "
          "characters (VS403309), so a count-based rule would send this and read "
          "the service's refusal back instead: %r" % (over,),
          len(over) == 1 and over[0][0] == 1
          and over[0][1] > M.WIQL_MAX_CHARS)

    check("af9 the SELECT list is built FROM `FIELDS`, so the query and the "
          "contract cannot disagree: every field appears in the clause exactly "
          "once",
          all(M.select_clause().count("[%s]" % (name,)) == 1
              for name in M.FIELDS)
          and M.select_clause().count(",") == len(M.FIELDS) - 1)
    check("af10 ...and `System.Parent` is IN it. Step 3b reads the parent off "
          "these rows, and `az boards query` returns the named fields and no "
          "others - dropping it would make every item look unparented rather "
          "than fail", "System.Parent" in M.FIELDS
          and "[System.Parent]" in M.select_clause())

    # --- which ids get asked for ---------------------------------------------
    ids = M.linked_ids(MANIFEST)
    check("af11 every linked item is asked for, from all three places a manifest "
          "puts a link - phase, task and bug - and the unlinked task is not: %r"
          % (ids,), ids == [4001, 5120, 4890])
    shape = M.plan(MANIFEST, 200)
    check("af12 the plan says how many of HOW MANY carry a link, so an empty "
          "fetch reads as 'nothing here is linked' and never as 'checked "
          "everything, all clear': %r" % (shape["linkedOf"],),
          shape["linkedOf"] == (3, 4))
    check("af13 ...and it carries the org and project off `meta.ado`, so the "
          "call is not assembled from a second reading of the manifest",
          shape["organization"] == "acme" and shape["project"] == "store")

    # --- the bound, as a NAMED outcome ---------------------------------------
    late = M.run_chunk("acme", "store", [1, 2], timeout=5,
                       runner=_timeout_runner)
    check("af14 A BOUND THAT EXPIRES IS A NAMED OUTCOME, not a hang and not an "
          "empty answer: status is %r, the ids with no news are carried, and the "
          "detail says how long it waited" % (late["status"],),
          late["status"] == M.TIMED_OUT and late["rows"] == []
          and late["ids"] == [1, 2] and "5s" in late["detail"])

    empty = M.run_chunk("acme", "store", [1, 2], timeout=5,
                        runner=_ok_runner())
    check("af15 THE PAIR THAT MAKES af14 MEAN SOMETHING: a board that answers "
          "with NO rows is `%s` and not `%s`. Both produce an empty list, and a "
          "caller that cannot tell them apart prints a clean table for a board "
          "it never reached" % (M.OK, M.TIMED_OUT),
          empty["status"] == M.OK and empty["rows"] == []
          and empty["status"] != late["status"])

    good = M.run_chunk("acme", "store", [4001, 5120], timeout=5,
                       runner=_ok_runner(4001, 5120))
    check("af16 a successful chunk is `%s` with its rows - the positive half, "
          "which is what fails if the status became unconditional in the other "
          "direction" % (M.OK,),
          good["status"] == M.OK and len(good["rows"]) == 2)

    broke = M.run_chunk("acme", "store", [1], timeout=5,
                        runner=lambda a, t: _Done(1, "", "ERROR: TF400813"))
    check("af17 a non-zero exit is `%s` and KEEPS what the tool said, rather than "
          "reporting an empty board" % (M.CALL_FAILED,),
          broke["status"] == M.CALL_FAILED and "TF400813" in broke["detail"])

    junk = M.run_chunk("acme", "store", [1], timeout=5,
                       runner=lambda a, t: _Done(0, "not json at all"))
    check("af18 output that is not JSON is `%s`, never an empty row list - exit "
          "0 with unreadable stdout is the shape that reads as a clean board"
          % (M.UNPARSEABLE,), junk["status"] == M.UNPARSEABLE)

    notalist = M.run_chunk("acme", "store", [1], timeout=5,
                           runner=lambda a, t: _Done(0, '{"id": 1}'))
    check("af19 ...and JSON that is not a LIST of rows is the same refusal, from "
          "the other side", notalist["status"] == M.UNPARSEABLE)

    huge = M.run_chunk("acme", "store", wide, timeout=5,
                       runner=_ok_runner())
    check("af20 a chunk past the ceiling is refused BEFORE the call, naming the "
          "length and the remedy - sending it and reading VS403309 back would "
          "spend the round trip to learn what the length already said",
          huge["status"] == M.REFUSED_TOO_LONG
          and str(M.WIQL_MAX_CHARS) in huge["detail"]
          and "VS403309" in huge["detail"]
          and "lower the chunk size" in huge["detail"])
    check("af20b ...and that refusal happened without running anything: the "
          "runner handed in would have answered OK, so a refusal here can only "
          "come from the length check", huge["rows"] == [])

    # --- what came back, and what did not ------------------------------------
    items = M.as_items([{"id": 4001, "fields": {"System.State": "Active"}}])
    check("af21 rows become the `{id, fields}` payload `explain-ado-drift.py "
          "--items` reads, and `mapped` is NOT invented here - that is the "
          "stateMap translation `sync.md` owns, and a second copy is a second "
          "answer",
          items == [{"id": 4001, "fields": {"System.State": "Active"}}])

    # F106: THE PRODUCER'S OWN RETURN VALUE, handed to the guard built for
    # exactly this false accusation. A fixture that merely resembled a fetch was
    # what let it through - `rest_payload_reason` keyed off `rev`/`url`/`_links`/
    # `relations`, `as_items` strips all four, and the item that HAD a parent was
    # refused for carrying none. The row below is the live shape (work item #121,
    # parent #101). This case is why a marker key was NOT added here: the guard
    # keys off the absent `type` instead, so trimming another field cannot bring
    # the false verdict back.
    _live = M.as_items([{"id": 121,
                         "fields": {"System.Parent": 101,
                                    "System.WorkItemType": "Issue",
                                    "System.Title": "Add the audit trail",
                                    "System.Tags": "audit-plugin"}}])
    check("af21b what THIS function returns is refused by the conformance gate "
          "as an ungradeable shape - not a fixture resembling a fetch, the "
          "producer's own value: %r"
          % ((_conv.rest_payload_reason(_live[0]) or "")[:40],),
          len(_live) == 1 and _conv.rest_payload_reason(_live[0]) is not None)
    _ready = _conv.as_gradable_item(_live[0])
    check("af21c ...and the translation of that same row IS gradeable, with the "
          "parent read out of fields[\"System.Parent\"] where this SELECT puts "
          "it - so status can still ask the question, through one door",
          _conv.rest_payload_reason(_ready) is None
          and _ready.get("parent") == 101 and _ready.get("type") == "Issue")

    gone = M.missing_ids([4001, 5120, 4890], [{"id": 4001, "fields": {}}])
    check("af22 an id asked for that no row came back for is NAMED, in the order "
          "it was asked - a work item deleted or moved out of the project is a "
          "thing to say, and dropping it leaves a shorter table looking "
          "complete: %r" % (gone,), gone == [5120, 4890])
    check("af23 THE PAIR: an id that DID come back is not listed as missing, so "
          "af22 is reading the rows rather than echoing the request",
          M.missing_ids([4001], [{"id": 4001, "fields": {}}]) == [])

    # --- the whole fetch ------------------------------------------------------
    whole = M.fetch(MANIFEST, size=2, timeout=5, runner=_ok_runner(4001, 5120))
    check("af24 a fetch over more ids than one chunk holds makes MORE THAN ONE "
          "call and keeps every row: the second chunk's runner answers with the "
          "same rows here, which is why the count is what proves the second call "
          "happened at all: %d item(s) from %d chunk(s)"
          % (len(whole["items"]), len(whole["plan"]["chunks"])),
          len(whole["plan"]["chunks"]) == 2 and len(whole["items"]) == 4)

    partial = M.fetch(MANIFEST, size=2, timeout=5, runner=_timeout_runner)
    check("af25 when every chunk times out the result is not an empty success: "
          "`failures` carries one entry per chunk and `items` is empty, so the "
          "caller can say WHICH ids it has no news about",
          len(partial["failures"]) == 2 and partial["items"] == []
          and all(f["status"] == M.TIMED_OUT for f in partial["failures"]))
    # --- the organization spelling, which a live run found and no fixture could -
    # Every case above uses a made-up org and none of them reaches `az`, so the
    # manifest's value could be passed through verbatim and stay green forever.
    # It was, and every call against a real board failed: `az boards query` wants
    # the URI and `connect` records whatever the operator typed.
    check("af27 a BARE organization name becomes the URI `az` demands. This is "
          "the live regression: `--organization must be specified. The value "
          "should be the URI...` was the answer to every call while the whole "
          "suite was green: %r" % (M.org_url("test-audit-lab"),),
          M.org_url("test-audit-lab") == "https://dev.azure.com/test-audit-lab")
    check("af28 THE PAIR: an organization already written as a URL is passed "
          "through, NOT prefixed a second time. A repair that prepended "
          "unconditionally would pass af27 and break every manifest that stores "
          "the full form: %r" % (M.org_url("https://dev.azure.com/acme"),),
          M.org_url("https://dev.azure.com/acme")
          == "https://dev.azure.com/acme"
          and M.org_url("https://dev.azure.com/acme/")
          == "https://dev.azure.com/acme")
    for blank in (None, "", "   "):
        argv = M.az_argv(blank, "store", "SELECT 1")
        check("af29 an organization of %r OMITS the flag rather than sending an "
              "empty value - `az devops configure --defaults` can answer, and an "
              "empty string is a value `az` would try to use" % (blank,),
              M.org_url(blank) is None and "--org" not in argv
              and "--project" in argv)
    live = M.az_argv("test-audit-lab", "DC application", "SELECT 1")
    check("af30 ...and the assembled call carries the URI, the project verbatim "
          "(spaces and all - it is one argv entry, never a shell string) and "
          "`--only-show-errors`: %r" % (live[:7],),
          "https://dev.azure.com/test-audit-lab" in live
          and "DC application" in live and "--only-show-errors" in live)

    check("af26 THE PAIR: a fetch whose calls all succeed reports NO failures - "
          "the case that goes red if `failures` became unconditional, which is "
          "the mutation af25 alone cannot catch", whole["failures"] == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ado_fetch.py --selftest\n")
    raise SystemExit(2)
