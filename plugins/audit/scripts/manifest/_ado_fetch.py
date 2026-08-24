#!/usr/bin/env python3
"""
Reading the linked side of a board in ONE query per chunk, with a bound on each.

`/audit:sync status` said "batch-fetch the ADO side" and then named
`az boards work-item show`, which takes a single `--id` and rejects a comma list.
An instruction that asks for a batch and names a per-item command cannot be
obeyed: the run loops, and every linked item pays a fresh CLI start-up. On a real
board that was 62 linked items and eleven minutes.

Measured on the lab board rather than reasoned about: a per-item `show` loop cost
roughly half a second an item, where ONE `az boards query` over the same ids
answered for all of them in about the time of a single `show`. That is a per-ITEM
constant against a per-CALL one, so the gap widens with the board and never closes.

WHY THIS IS A MODULE AND NOT A PARAGRAPH IN `sync.md`. The chunk size, the field
list and the bound are the three things a prose instruction cannot be held to - and
the defect above was precisely a prose instruction nothing could check. Here they
are values with cases against them: `plugins/audit/tests/test__ado_fetch.py` walks
the chunk boundary AT the size rather than under it, and proves the bound produces a
NAMED outcome instead of a hang.

THE LIMIT IS ON THE WIQL TEXT, NOT ON A COUNT OF IDS, which is the whole reason
`DEFAULT_CHUNK` is an operating point and `WIQL_MAX_CHARS` is the invariant. The
service refuses with `VS403309: Query WIQL text length exceeded the limit. It should
contain no more than 32000 characters.`, so how many ids fit depends on how wide they
are and how long the `SELECT` list is. A chunk sized AT the boundary would start
refusing the day the board's ids grew a digit; `oversized_queries()` therefore checks
the text every time rather than trusting the count, and the caller refuses that chunk
by name rather than sending it and reading the service's error back.

THE FIELD LIST IS A CONTRACT AND LIVES HERE ONLY. `az boards query` returns exactly
the fields the `SELECT` names and no others, so a field dropped from `FIELDS` comes
back absent and reads as "the board does not have one". Every consumer of a fetched
item reads out of this one tuple - `sync.md` steps 3, 3b, 4 and 5, push step 2c, and
`_ado_drift` behind it - and the documents point at it instead of restating it.

TWO SHAPES ARE MEASURED AND NOT ASSUMED (`verifying-external-behavior`), because
existing steps already depend on them:

  * `System.ChangedBy` comes back from a WIQL row as the identity OBJECT
    (`displayName`, `uniqueName`) and `System.ChangedDate` as an ISO stamp with
    fractional seconds and a trailing `Z` - the same shapes a plain `show` returns.
    That is what lets `_ado_drift.changed_by` read either, and it is why this is a
    drop-in for the per-item fetch rather than a second parser.
  * `System.Parent` comes back with no `--expand relations`, and the KEY IS ABSENT
    when the item has no parent - never `null`. The parent-drift cell rests on
    exactly that: "the board hangs it nowhere" and "we did not ask" are different
    answers.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__ado_fetch.py`.
"""
import json
import os
import subprocess
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _ado_drift as _drift  # noqa: E402  (link_inventory: WHICH ids to fetch)

# --- the contract ---------------------------------------------------------------

# What every consumer of a fetched item reads, in the order the SELECT names them.
# ADD to this, never trim it: `az boards query` returns the named fields and no
# others, so a field dropped here comes back ABSENT from every row and is
# indistinguishable from a board that does not carry it.
FIELDS = ("System.Id", "System.WorkItemType", "System.Title", "System.State",
          "System.Parent", "System.ChangedBy", "System.ChangedDate",
          "System.Tags", "System.IterationPath")

# The service's own ceiling, quoted from its refusal (`VS403309`). On the TEXT of
# the query - not on a count of ids, which is why it is checked and not assumed.
WIQL_MAX_CHARS = 32000

# Ids per query. An operating point, deliberately far below the ceiling above so
# that id width and SELECT length cannot push a chunk over it; not the limit itself.
DEFAULT_CHUNK = 200

# Seconds one chunk may take. Generous rather than tight on purpose: a live round
# trip measured well under two seconds, so a call wanting more than an order of
# magnitude beyond that is not slow, it is stuck.
DEFAULT_TIMEOUT_S = 60

# The outcomes a fetch can end in. Distinct sentinels, because "the board returned
# no rows for these ids" and "the board did not answer" are different answers and
# only the first is safe to act on.
OK = "ok"
TIMED_OUT = "timed_out"
CALL_FAILED = "call_failed"
UNPARSEABLE = "unparseable"
REFUSED_TOO_LONG = "refused_too_long"


def select_clause():
    """The `SELECT` list, built from `FIELDS` so the two can never disagree."""
    return ", ".join("[%s]" % (name,) for name in FIELDS)


def chunk_ids(ids, size=DEFAULT_CHUNK):
    """`ids` in order, de-duplicated, in groups of at most `size`.

    Order is preserved rather than sorted: the caller's order is manifest order,
    and a table that comes back in a different order than the plan it was made from
    is a table somebody has to re-sort to read. De-duplication is not cosmetic -
    two manifest items may legitimately link the SAME work item (a bug materialized
    as a task), and sending the id twice would return one row for two requests and
    read as a missing item.
    """
    if size is None or size < 1:
        raise ValueError("chunk size must be a positive whole number, got %r"
                         % (size,))
    seen = set()
    ordered = []
    for one in (ids or []):
        if one in seen:
            continue
        seen.add(one)
        ordered.append(one)
    return [ordered[i:i + size] for i in range(0, len(ordered), size)]


def wiql_for(ids):
    """The query text for one chunk. Every field in `FIELDS`, and nothing else."""
    return ("SELECT %s FROM WorkItems WHERE [System.Id] IN (%s)"
            % (select_clause(), ",".join(str(one) for one in (ids or []))))


def too_long(text):
    """True iff this query text is past the service's ceiling.

    The ONE place the comparison is written. `oversized_queries` reports over a
    whole plan and `run_chunk` refuses one call, and when those were two `>` of
    their own, a mutation that disabled the first left the second still firing -
    which is a rule with two opinions waiting to disagree.
    """
    return len(text or "") > WIQL_MAX_CHARS


def oversized_queries(queries):
    """`[(index, length)]` for every query past `WIQL_MAX_CHARS`.

    Checked rather than assumed for the reason in the module docstring: the ceiling
    is on characters, so a chunk that fits today stops fitting when the board's ids
    grow a digit. Returning the LENGTHS and not a boolean is what lets the caller
    say how far over it went, which is the difference between "raise the chunk" and
    "this SELECT list is too long".
    """
    return [(i, len(text)) for i, text in enumerate(queries or [])
            if too_long(text)]


def linked_ids(manifest):
    """Every distinct work-item id the manifest links, in manifest order.

    `_drift.link_inventory` is the one walk that answers this, and it goes through
    `_manifest_io.iter_tasks` - so a SHARDED manifest's phase-held links are in here
    exactly as a single-file one's are, provided the caller assembled it.
    """
    out = []
    seen = set()
    for row in _drift.link_inventory(manifest):
        if row["adoId"] in seen:
            continue
        seen.add(row["adoId"])
        out.append(row["adoId"])
    return out


def ado_of(manifest):
    """`meta.ado`, or `{}` - tolerant on the way down like the other doors."""
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    ado = meta.get("ado") if isinstance(meta, dict) else None
    return ado if isinstance(ado, dict) else {}


def plan(manifest, size=DEFAULT_CHUNK):
    """What would be fetched, in how many calls, before any call is made.

    Returns `{ids, chunks, queries, oversized, organization, project, linkedOf}`.
    `linkedOf` is `(linked, total)` so a caller can say `0 of N item(s) carry a
    link` - an empty fetch has to read as "there is nothing linked here", never as
    "checked everything, all clear", which is the same silence one layer up.
    """
    ids = linked_ids(manifest)
    groups = chunk_ids(ids, size)
    queries = [wiql_for(group) for group in groups]
    ado = ado_of(manifest)
    total = len(_manifest_item_count(manifest))
    return {"ids": ids, "chunks": groups, "queries": queries,
            # The size that was CONFIGURED, not the size the first chunk happened
            # to come out at. Those agree only on a full chunk, and reporting the
            # second as "the limit" tells a board with three linked items that its
            # limit is three - a number that is not what its label says.
            "chunk": size,
            "oversized": oversized_queries(queries),
            "organization": ado.get("organization"),
            "project": ado.get("project"),
            "linkedOf": (len(ids), total)}


def _manifest_item_count(manifest):
    """Every phase, task and bug id - the denominator for "N of M are linked"."""
    out = []
    for phase in ((manifest or {}).get("phases") or []):
        if isinstance(phase, dict):
            out.append(("phase", phase.get("id")))
            for task in (phase.get("tasks") or []):
                if isinstance(task, dict):
                    out.append(("task", task.get("id")))
    for bug in ((manifest or {}).get("bugs") or []):
        if isinstance(bug, dict):
            out.append(("bug", bug.get("id")))
    return out


# --- making the call ------------------------------------------------------------

# Where a bare organization name lives. Spelled once, because the moment a second
# call site builds this string the two can disagree about the trailing slash.
ADO_HOST = "https://dev.azure.com"


def org_url(organization):
    """`meta.ado.organization` as the URI `az` demands, from either spelling.

    FOUND BY A LIVE RUN, not by reading. `meta.ado.organization` legitimately holds
    a BARE NAME - that is what `connect` records when the operator types one - and
    `az boards query` refuses it: "--organization must be specified. The value
    should be the URI of your Azure DevOps organization". Passing the manifest's
    value through verbatim therefore failed every call on a real board while every
    fixture with a made-up org passed, because no fixture ever reached `az`.

    `_ado_connect.org_key` is the inverse of this and already documents both forms
    reaching the plugin; this is the direction nothing had needed until a call was
    actually assembled here.

    None for nothing usable, so the caller OMITS the flag and lets
    `az devops configure --defaults` answer, rather than sending an empty string
    that `az` reads as a value.
    """
    if not isinstance(organization, str) or not organization.strip():
        return None
    text = organization.strip().rstrip("/")
    if "://" in text:
        return text
    return "%s/%s" % (ADO_HOST, text)


def az_argv(organization, project, wiql):
    """The `az boards query` argument list for one chunk.

    `--only-show-errors` is not decoration: the CLI writes upgrade and extension
    notices to stderr on every call, and suppressing them is what leaves a real
    `ERROR:` line legible there. stdout was always the JSON alone.
    """
    argv = ["az", "boards", "query"]
    org = org_url(organization)
    if org:
        argv += ["--org", org]
    if project:
        argv += ["--project", str(project)]
    return argv + ["--only-show-errors", "--output", "json", "--wiql", wiql]


def run_chunk(organization, project, ids, timeout=DEFAULT_TIMEOUT_S,
              runner=None):
    """One chunk, bounded. `{status, rows, detail, seconds}` - never a bare list.

    THE BOUND IS THE POINT. A read-only command that advertises itself as safe can
    otherwise block forever with nothing on screen, and a hang is worse than a
    failure: a failure names what happened, a hang says nothing and the operator
    cannot tell a slow board from a dead one. So expiry is a NAMED status
    (`TIMED_OUT`) carrying the ids that did not answer, and it is never the same
    value an empty-but-successful answer produces (`OK` with `rows == []`).

    `runner` exists for the cases: it is handed the argv and the timeout and returns
    a completed-process-shaped object. Production passes nothing.
    """
    wiql = wiql_for(ids)
    if too_long(wiql):
        return {"status": REFUSED_TOO_LONG, "rows": [], "ids": list(ids),
                "detail": ("the query for these %d id(s) is %d characters and the "
                           "service refuses anything past %d (VS403309) - lower the "
                           "chunk size"
                           % (len(ids), len(wiql), WIQL_MAX_CHARS))}
    argv = az_argv(organization, project, wiql)
    call = runner if runner is not None else _run_subprocess
    try:
        done = call(argv, timeout)
    except subprocess.TimeoutExpired:
        return {"status": TIMED_OUT, "rows": [], "ids": list(ids),
                "detail": ("`az boards query` over %d id(s) did not answer within "
                           "%ds" % (len(ids), timeout))}
    except Exception as exc:
        return {"status": CALL_FAILED, "rows": [], "ids": list(ids),
                "detail": "could not run `az boards query`: %s" % (exc,)}
    if getattr(done, "returncode", 1) != 0:
        # stdout is kept, never discarded: a tool that exits non-zero may still have
        # written the answer, and throwing it away loses the only useful half.
        return {"status": CALL_FAILED, "rows": [], "ids": list(ids),
                "detail": ("`az boards query` exited %s: %s"
                           % (done.returncode,
                              (getattr(done, "stderr", "") or
                               getattr(done, "stdout", "") or "").strip()[:400]))}
    try:
        rows = json.loads(getattr(done, "stdout", "") or "null")
    except ValueError as exc:
        return {"status": UNPARSEABLE, "rows": [], "ids": list(ids),
                "detail": "`az boards query` did not return JSON: %s" % (exc,)}
    if not isinstance(rows, list):
        return {"status": UNPARSEABLE, "rows": [], "ids": list(ids),
                "detail": ("`az boards query` returned %s, not a list of rows"
                           % (type(rows).__name__,))}
    return {"status": OK, "rows": rows, "ids": list(ids), "detail": ""}


def _run_subprocess(argv, timeout):
    """`az`, with stdin closed so a credential prompt becomes an error, not a wait."""
    return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=timeout)


def as_items(rows):
    """Board rows as the `{id, fields}` payload `explain-ado-drift.py --items` reads.

    `mapped` is deliberately NOT added here. It is the manifest status translated
    through `meta.ado.stateMap`, `commands/sync.md` owns that table, and a second
    copy would be a second answer - the same split `_ado_drift` already documents.
    """
    out = []
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        fields = row.get("fields")
        ident = row.get("id")
        if not isinstance(fields, dict):
            fields = {}
        if ident is None:
            ident = fields.get("System.Id")
        out.append({"id": ident, "fields": fields})
    return out


def missing_ids(sent, rows):
    """Ids asked for that no row came back for, in the order they were asked.

    Not an error and not dropped either: a work item deleted or moved out of the
    project is a thing to SAY. Silently returning the shorter list would make the
    table look complete, which is the defect this whole area keeps producing.
    """
    got = set()
    for item in as_items(rows):
        if item["id"] is not None:
            got.add(item["id"])
    return [one for one in (sent or []) if one not in got]


def fetch(manifest, size=DEFAULT_CHUNK, timeout=DEFAULT_TIMEOUT_S, runner=None):
    """Every linked item, chunked and bounded. `{items, chunks, failures, plan}`.

    `failures` is a list and not a flag: one chunk timing out while the rest answer
    is a PARTIAL result, and the caller has to be able to say which ids it has no
    news about rather than printing a table that reads as the whole board.
    """
    shape = plan(manifest, size)
    items, failures, missing = [], [], []
    for group in shape["chunks"]:
        outcome = run_chunk(shape["organization"], shape["project"], group,
                            timeout=timeout, runner=runner)
        if outcome["status"] != OK:
            failures.append(outcome)
            continue
        items.extend(as_items(outcome["rows"]))
        missing.extend(missing_ids(group, outcome["rows"]))
    return {"items": items, "failures": failures, "missing": missing,
            "plan": shape}
