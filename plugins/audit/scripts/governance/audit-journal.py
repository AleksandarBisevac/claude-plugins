#!/usr/bin/env python3
"""
The commands around the audit trail: append a row, verify the chain, show it, archive it.

    audit-journal.py append   --action <a> [--target <path>] [--summary <text>]
    audit-journal.py verify   [--json]
    audit-journal.py show     [--limit N] [--json] [--target <path>]
    audit-journal.py archive  [--before YYYY-MM]
    audit-journal.py merge    --file <journal file> [--ours F --theirs F]
                              [--dry-run] [--json]
    audit-journal.py sessions [--json]
      (every command takes --project DIR; default the current directory)

Exit codes: 0 healthy (warnings allowed) - 1 findings (the chain does not hold,
or a merge refused) - 2 usage error.

`merge` is the verb a journal conflict needs and did not have (F306). One writer
on two branches is ordinary while a phase is paused, and the per-writer file
split does not separate them -- so a landing phase produces one file with a
shared prefix and two tails, which cannot be resolved by editing because each
divergent row's hash covers a `prev` only its own side has. With no verb the
resolution keeps one tail and loses the other in a second parent nobody reads
again. It defaults to the two sides git already has (index stages 2 and 3 of
`--file`), so during a conflict it needs nothing but the path.

`sessions` answers the question a per-session file NAME cannot (F309): which
session wrote which file. The name carries the id the writer supplied, and the
hook that writes most rows is handed a different id from the one the session
reads from Bash -- so the mapping goes in the rows and this prints it.

The trail itself -- the row shape, the hash chain, where a journal lives, and what
`verify` actually checks -- is `_journal_io.py` at layer 1, imported below. It used
to be this file's body, and moving it was not tidying: `_help` (layer 3) and
`audit-doctor` (layer 7) both needed it and both reached this entry point through
`_loader`, two of the seventeen edges `_deps.KNOWN_LAYER_DEBT` recorded, and
`hooks/_config.py` was loading the whole command on every tool call to resolve one
directory path.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_audit_journal.py` - see `plugins/audit/tests/_harness.py`.
"""
import argparse
import json
import os
import sys
import time

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

import _journal_io  # noqa: E402  (the trail this command is a front end for)

# The trail, under the names this command has always called it by. NOT copies:
# `_journal_io` (layer 1) owns every one of them, and `tests/test_audit_journal.py`
# asks for them by hand, case by case, about the trail AS THIS COMMAND SEES IT.
# `tests/test__journal_io.py` pins each name to be that module's own object, so a
# second implementation here fails a case rather than drifting.
#
# THE LIST IS NO LONGER REMEMBERED, WHICH IS THE HALF THAT KEPT FAILING. Pinning
# each LISTED name proves none of them is a copy; it proves nothing about a name
# that was never listed, and a release added a row-shape constant here that nobody
# re-exported -- one fact, two homes, nothing comparing them. So
# `test__journal_io.py` now DERIVES the row-shape set from `_journal_io`'s own
# source: every public module-level constant that building a row can read, found by
# walking out from `_normalise`. A constant a row can carry and this file does not
# re-export fails that case BY NAME.
#
# The line that derivation draws is "can a row read it", and it is drawn there
# because that is the question this list exists to answer. It takes in the bounds,
# the versions, the allow-lists and the redaction vocabulary a row can end up
# carrying (`OUTSIDE_TOKEN`, `UNNAMED_PROGRAM`); it leaves out the writer-state
# vocabulary (`WRITER_TOKEN_FILE`, `PLUGIN_WRITE_*`, `MAX_WRITER_KEY_CHARS`), which
# names a gitignored scratch file that no row has ever read. The names below the
# derived set -- where a journal LIVES and how it is locked -- are here for the
# CLI's own reasons and stay hand-listed.
ROW_VERSION = _journal_io.ROW_VERSION
DETAILS_VERSION = _journal_io.DETAILS_VERSION
DETAILS_KEYS = _journal_io.DETAILS_KEYS
CHANGE_KEYS = _journal_io.CHANGE_KEYS
MAX_CHANGES = _journal_io.MAX_CHANGES
MAX_VALUE_CHARS = _journal_io.MAX_VALUE_CHARS
MAX_DETAILS_BYTES = _journal_io.MAX_DETAILS_BYTES
MAX_SUMMARY_CHARS = _journal_io.MAX_SUMMARY_CHARS
SUMMARY_TRUNCATED = _journal_io.SUMMARY_TRUNCATED
VALUE_TRUNCATED = _journal_io.VALUE_TRUNCATED
OUTSIDE_TOKEN = _journal_io.OUTSIDE_TOKEN
UNNAMED_PROGRAM = _journal_io.UNNAMED_PROGRAM
ENV_SESSION_VAR = _journal_io.ENV_SESSION_VAR
MAX_SESSION_ID_CHARS = _journal_io.MAX_SESSION_ID_CHARS
MERGE_ACTION = _journal_io.MERGE_ACTION
MERGE_VIA = _journal_io.MERGE_VIA
DEFAULT_DIRNAME = _journal_io.DEFAULT_DIRNAME
ARCHIVE_DIRNAME = _journal_io.ARCHIVE_DIRNAME
DEFAULT_MANIFEST = _journal_io.DEFAULT_MANIFEST
GENESIS = _journal_io.GENESIS
LOCK_STALE_SECONDS = _journal_io.LOCK_STALE_SECONDS
LOCK_WAIT_SECONDS = _journal_io.LOCK_WAIT_SECONDS
_MONTH_RE = _journal_io._MONTH_RE
_SAFE = _journal_io._SAFE

load_config = _journal_io.load_config
enabled = _journal_io.enabled
journal_dir = _journal_io.journal_dir
in_journal = _journal_io.in_journal
canonical = _journal_io.canonical
row_hash = _journal_io.row_hash
genesis_prev = _journal_io.genesis_prev
file_hash = _journal_io.file_hash
writer_id = _journal_io.writer_id
env_session_id = _journal_io.env_session_id
month_of = _journal_io.month_of
file_for = _journal_io.file_for
rows_from_text = _journal_io.rows_from_text
read_file = _journal_io.read_file
journal_files = _journal_io.journal_files
read_all = _journal_io.read_all
writer_of = _journal_io.writer_of
session_index = _journal_io.session_index
normalise_details = _journal_io.normalise_details
append = _journal_io.append
row_content = _journal_io.row_content
rows_digest = _journal_io.rows_digest
merge_rows = _journal_io.merge_rows
merge_text = _journal_io.merge_text
write_merged = _journal_io.write_merged
anchor_verdict = _journal_io.anchor_verdict
rows_unaccounted = _journal_io.rows_unaccounted
verify = _journal_io.verify
_normalise = _journal_io._normalise
_append = _journal_io._append
_git_status_sets = _journal_io._git_status_sets
_git_anchor_finding = _journal_io._git_anchor_finding


# --- commands -----------------------------------------------------------------
def cmd_append(args, out):
    project = os.path.abspath(args.project)
    config = load_config(project)
    if not enabled(config):
        out("[audit-journal] journal disabled (journal.enabled false) -- "
            "nothing written")
        return 0
    try:
        row, path = _append(project, {
            "action": args.action, "target": args.target or "",
            "summary": args.summary or "",
            "details": getattr(args, "_details", None),
            "actor": {"author": args.author, "sessionId": args.session,
                      "via": args.via}}, config=config)
    except Exception as exc:
        out("[audit-journal] could not append: %s" % exc)
        return 1
    # THE CLAIM `append_from_cli` LEAVES, left by hand here because this command
    # needs `row` for the line below and only the raising `_append` returns it
    # (F287). Without it the append this command just made is reported by
    # `guard-bash-writes` as a shell write into the append-only trail on the next
    # Bash command -- and this command is the one the guard's own notice names as
    # a legitimate writer, which made the notice contradict itself.
    _journal_io.record_plugin_write(project, config,
                                    _journal_io.CLI_JOURNAL_WRITER, path)
    out("[audit-journal] %s %s  %s" % (row["ts"], row["action"],
                                       row["hash"][:12]))
    return 0


def cmd_verify(args, out):
    project = os.path.abspath(args.project)
    res = verify(project)
    if args.as_json:
        out(json.dumps(res, indent=2, sort_keys=True))
        return 1 if res["findings"] else 0
    if not res["exists"]:
        out("[audit-journal] no journal yet at %s" % res["dir"])
        return 0
    for line in res["warnings"]:
        out("WARNING: " + line)
    for line in res["findings"]:
        out("FINDING: " + line)
    if res["findings"]:
        out("\nBROKEN: %d finding(s) across %d row(s) in %s"
            % (len(res["findings"]), res["rows"], res["dir"]))
        return 1
    out("OK: %d row(s) in %d file(s) chain cleanly%s"
        % (res["rows"], len(res["files"]),
           " (%d warning(s))" % len(res["warnings"]) if res["warnings"] else ""))
    return 0


# --- resolving a divergence, and reading a writer back to its session ---------
def _git_stage(path, stage):
    """The bytes of `path` at merge stage `stage` (2 = ours, 3 = theirs), or None.

    WHY GIT IS WHERE A MERGE'S TWO SIDES COME FROM BY DEFAULT. A journal
    divergence reaches a person as a merge conflict, so both sides are already
    in the index and neither has to be extracted by hand -- and that they are
    both in git is half of what makes re-chaining auditable rather than a
    rewrite: a reviewer can read either side and the merge commit holds both
    parents.

    None on every inability to ask, and the caller names which side it could not
    get. It must never fall back to the working copy: that file is the
    conflicted one, and merging it with one real side would union a side with
    itself and report the other's rows as absent."""
    import shutil
    import subprocess
    if not shutil.which("git"):
        return None
    d = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    try:
        res = subprocess.run(
            ["git", "-C", d, "show", ":%d:./%s" % (stage, name)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def _unreadable_refusal(base, unreadable):
    """The refusal for a target that is THERE and could not be read.

    Every grader below gets the same one, because the answer does not depend on
    which question was about to be asked: this command replaces that file, and
    an empty read standing in for its contents would clear the merge of
    everything the guard could not see."""
    return ("%s is there and could not be read (%s), so nothing here can say "
            "whether the merge still holds every row it has -- and this command "
            "replaces that file. Fix the read, or move the file aside on "
            "purpose, rather than being told the merge was fine."
            % (base, unreadable))


def _target_torn_faults(base, text):
    """Every reason the TARGET's own bytes cannot be graded at all, as refusals.

    F341, AND IT IS THE DOOR THE F328 REPAIR LEFT OPEN. `_merge_input_faults`
    refuses a torn or unparseable SIDE, and says why: those bytes are not a row,
    so a merge would drop them and say nothing. Nothing asked the same question
    of the file being OVERWRITTEN -- and it is the stronger case, because a side
    is only read while the target ceases to exist. `anchor_verdict` cannot ask
    it either: it drops `_unparseable` rows from `wanted` before comparing, so
    such a row can never be reported missing, and its docstring justifies that
    with "`verify`'s own per-row pass is what reports one in the WORKING copy" --
    true where the git anchor calls it, false here, where the working copy is
    about to be replaced. So the question is asked at this call site instead,
    and `anchor_verdict` keeps filtering.

    Driven before it was written: a live file whose last line a crashed writer
    left half-typed, merged with two sides holding the intact rows plus a new
    one, exited 0 saying `wrote <name>` with the truncated bytes gone and
    `verify` clean. A corrupted line mid-file -- which `verify` grades a FINDING
    -- went the same way.

    NOT ASKED ON THE `from_index` PATH, and that is a property of what the
    target IS there rather than a preference: a conflicted working copy is two
    stages with conflict markers between them, every marker line is an
    unparseable row, and the last of them makes the file torn by this same
    reading. Asking there would refuse every genuine conflict resolution, which
    is the measured premise `mg3c` holds and `mg3`/`mg2` would fail on."""
    rows, torn = rows_from_text(text)
    out = []
    if torn:
        out.append(
            "%s ends with a partial line -- a writer was interrupted there. "
            "Those bytes are not a row, so nothing can say whether the merge "
            "still holds them, and this command REPLACES that file: they would "
            "go with nothing in the output to say they were ever there. A merge "
            "refuses a torn SIDE for exactly this reason, and the target is the "
            "copy that ceases to exist. Truncate the partial line on purpose "
            "first if that is what you mean." % (base,))
    for i, row in enumerate(rows, 1):
        if row.get("_unparseable"):
            out.append(
                "%s line %s is not valid JSON, and this command replaces that "
                "file -- a line that is not a row is graded by nothing, so it "
                "would go silently. `verify` reports it as a finding; repair it "
                "before merging over it." % (base, row.get("_line") or i))
    return out


def _prior_merge_faults(base, text, side_rows):
    """The refusal for a target that ALREADY holds a resolution, or none.

    F342. Re-running `merge` on a file this verb has already resolved was
    refused with the wrong cause and the wrong advice: the previous
    `journal.merge` row is in neither stage, so the presence check reported it
    exactly as it reports a row somebody typed while resolving -- "Append it
    again after the merge", about a row nobody typed.

    AND WHICH SENTENCE YOU GOT DEPENDED ON THE CLOCK. `_merge_marker` stamps
    `max(last row, now)` at second resolution, so a re-run inside the same
    second reproduces the previous marker byte for byte and is accounted for,
    while a re-run a second later is not. Two runs, two verdicts, no change in
    the file. That is why this asks a question the freshly built result is not
    part of: is there a marker row in the target that NEITHER SIDE holds? Both
    sides are fixed inputs, so the answer is the same in every second.

    A REFUSAL AND NOT AN IDEMPOTENT RE-RUN, decided rather than defaulted to.
    Writing the fresh result would drop that marker row -- the trail's own
    record of the first resolution -- from an append-only file, which is the one
    thing this verb exists not to do; and it could only ever come out identical
    by landing in the same second, so a re-run that "worked" would be safe by
    luck. Fail closed, and say what is actually there."""
    verdict = rows_unaccounted(text, merge_text(side_rows))
    prior = [pair for pair in verdict["unaccounted"]
             if pair[1] == MERGE_ACTION]
    if not prior:
        return []
    return ["%s already holds a `%s` row (row %d) that NEITHER side holds, so "
            "this file has already been resolved by this command and the row "
            "recording that is the trail's only account of it. Re-running "
            "builds a fresh resolution and would replace that record rather "
            "than add to it, so nothing was written. If the resolution is the "
            "one you want, `git add` it and run `audit-journal.py verify`; to "
            "start over, restore the conflict (`git checkout --merge -- %s`) "
            "and run this again."
            % (base, MERGE_ACTION, prior[0][0], base)]


def _target_loss(base, verdict):
    """The reason the merge result would LOSE something the target holds.

    F328, AND IT WAS A DATA LOSS THAT PRINTED SUCCESS. `--file` names the target
    and seeds the chain from its basename; it was never READ INTO the merge. So a
    side that is a stale extract of this same file -- which is exactly what
    `--ours/--theirs` is for, a conflict resolved days ago -- produced a result
    holding only what the two extracts held, and `write_merged` replaced the live
    file with it. Every sentence this command printed was a claim about the two
    INPUTS and read as a claim about the FILE, `no row's content touched`
    included, so the loss was silent; `--dry-run` printed the same input-side
    counts and could not reveal it either.

    THE SAME QUESTION `verify` ALREADY TRUSTS. `anchor_verdict` is the greedy
    presence-and-order test the git anchor grades a commit with: every row the
    older copy held is still here, its content unchanged, in the same relative
    order. A merge MAY re-link -- that is the verb -- and MAY NOT lose a row, and
    that difference is precisely the line that test draws. One definition, so the
    thing that writes the file and the thing that grades it afterwards cannot
    disagree about what a lost row is.

    A REFUSAL AND NOT A REPAIR. Nothing here may reach into the target and union
    it in: the caller said which two sides they meant, the result would then hold
    rows neither side has, and a merge that quietly widened its own inputs is a
    worse surprise than the one it replaces.

    IT IS HANDED THE VERDICT RATHER THAN TAKING IT, because the read behind it
    is `write_merged`'s, made with the lock held (F340). A copy of that read
    here would be the read taken too early, which is the defect."""
    return ("row %d (%s) of %s is not in the merge result with its content "
            "intact and in order, and the result is what would replace that "
            "file. `--file` names the TARGET and seeds the chain -- it is never "
            "one of the two sides -- so a side that is a STALE EXTRACT of this "
            "file yields a result missing whatever the file gained since. The "
            "scan stops at the first such row, so this names one of them and "
            "not all: %s holds %d row(s) and the result holds %d. Re-extract "
            "--ours/--theirs from copies that hold everything this file now "
            "holds, or pass neither and let the merge take the two sides from "
            "the index."
            % (verdict["row"], verdict["action"], base, base,
               verdict["committedRows"], verdict["workingRows"]))


def _conflict_loss(base, text, merged):
    """The refusal for a CONFLICTED target the merge result would lose a row of.

    The `from_index` half of F328, and it is a narrower question than
    `_target_loss` asks. There the two sides are stages 2 and 3 of this very
    file, so git built the working copy out of them and no row that came from a
    stage can be missing from their union. What CAN be missing is a row somebody
    typed into the conflicted file while resolving it: that row is in neither
    stage, so the union never had it, and writing the union drops it.

    ORDER IS NOT THE QUESTION HERE, which is why this does not call
    `anchor_verdict`. A conflicted working copy is two stages concatenated with
    markers between them -- an order no chain ever had -- so an order-aware test
    refuses every genuine resolution. `_journal_io.rows_unaccounted` asks the
    one thing this path can get wrong, and says in its own docstring why
    presence is a set question here and a counting question one function up.

    A ROW THIS VERB ITSELF LEFT IS NOT A ROW SOMEBODY TYPED (F342), which is
    why the unaccounted rows are partitioned rather than counted. A previous
    resolution's `journal.merge` row is also in neither stage, and reporting it
    with the sentence above named the wrong cause and gave advice about a row
    nobody had typed -- while WHICH of the two the message named came down to
    the wall-clock second, because the marker's timestamp moves and the first
    unaccounted row is whichever sits earlier in the file. `_prior_merge_faults`
    has that half, on evidence that does not move; this keeps the half it was
    always about."""
    verdict = rows_unaccounted(text, merged)
    typed = [pair for pair in verdict["unaccounted"]
             if pair[1] != MERGE_ACTION]
    if not typed:
        return []
    return ["row %d (%s) of %s is in the file and in NEITHER side the index "
            "holds, so the merge result does not carry it and the result is "
            "what would replace that file. A row typed into a conflicted "
            "journal while resolving it is in no stage, so no union of the two "
            "stages can hold it: %s has %d such row(s). Append it again after "
            "the merge, or extract both sides yourself and pass --ours/--theirs "
            "so the row is in one of them."
            % (typed[0][0], typed[0][1], base, base, len(typed))]


def _target_faults(base, text, unreadable, merged, side_rows, from_index):
    """Every reason replacing the target's CURRENT bytes with `merged` must not
    happen, as refusal text -- the whole grade, in one list.

    CALLED FROM INSIDE THE LOCK `write_merged` HOLDS (F340), with the bytes that
    function read there. Nothing below re-reads the file: a second read would be
    a second answer, and the one that mattered would be whichever ran first.

    THE PRIOR-RESOLUTION REFUSAL IS REPORTED ALONGSIDE ON ONE PATH AND INSTEAD
    ON THE OTHER, and the two sides of the merge are why. From the INDEX the two
    sides are fixed by git and cannot be the caller's mistake, so a row the
    working copy holds and neither stage does is always something the operator
    did to that file -- typed it, or already ran this command -- and those are
    two separate acts that each need naming. On the TARGET path the caller
    CHOOSES the two sides and the commonest fault is that they are stale: a
    marker row they do not hold is then one more symptom of that, not a second
    act, and its advice (restore the conflict) points at a conflict that is not
    open. So there the row actually at risk wins, and the marker question is
    asked only when no other row is being lost -- which is also the only reading
    under which it is not the wall clock deciding, because the order-aware
    verdict holds or fails on the marker according to which SECOND the two runs
    landed in while `_prior_merge_faults` asks about the sides."""
    if unreadable is not None:
        return [_unreadable_refusal(base, unreadable)]
    if from_index:
        return (_prior_merge_faults(base, text, side_rows)
                + _conflict_loss(base, text, merged))
    out = _target_torn_faults(base, text)
    verdict = anchor_verdict(text, merged)
    if not verdict["held"] and verdict["action"] != MERGE_ACTION:
        out.append(_target_loss(base, verdict))
    else:
        out.extend(_prior_merge_faults(base, text, side_rows))
    return out


def _merge_json(res, dry_run, written, error):
    """The `--json` rendering of one merge, INCLUDING whether it wrote.

    F331: `--json` used to return BEFORE `write_merged`, so it printed
    `"ok": true` with a full row list over a file it had not touched -- and
    `--json --dry-run` printed byte-identical output, which left a caller no way
    at all to tell a write from a preview.

    THE REPAIR IS THAT `--json` WRITES, and the reason is which flag means what.
    The usage block lists the two as independent: `--json` is a RENDERING and
    `--dry-run` is the flag that means do not write. Making the rendering flag
    suppress the write would keep the promise false in the other direction, and
    a caller asking for machine-readable output has no way to ask for the
    operation as well. So the write happens, and the payload SAYS it happened --
    `written` is the fact, `dryRun` is why it may be false, and `error` carries
    the reason when the write itself failed.

    `text` is empty whenever `rows` is, exactly as `merge_rows` leaves it: a
    refused merge hands back no answer for a caller to write out by accident."""
    payload = dict(res, dryRun=bool(dry_run), written=bool(written),
                   text=merge_text(res["rows"]))
    if error is not None:
        payload["error"] = error
    return json.dumps(payload, indent=2, sort_keys=True)


def cmd_merge(args, out):
    """Resolve a divergence in one journal file by re-chaining the UNION of its
    two sides (F306).

    NOT BLOCKED BY `journal.enabled: false`, and that is deliberate: the switch
    governs whether new news is RECORDED, while this repairs a file that already
    exists and is already in conflict. Refusing here would leave the operator
    holding a conflicted file with no verb that admits to it.

    The marker row's `via` is `MERGE_VIA` and not `--via`: what wrote it is a
    fact about the operation rather than a caller's preference. `--author` and
    `--session` are still the caller's to supply, because who ran it is not
    something this can observe.

    `--json` renders the same operation and does not change it: only `--dry-run`
    withholds the write, and the payload says which of the two happened
    (`_merge_json`). The result is graded against the file it would replace --
    `_target_faults`, handed to `write_merged` and run there, with the lock
    held, on the bytes that same call read (F340).
    """
    project = os.path.abspath(args.project)
    config = load_config(project)
    target = (args.file or "").strip()
    if not target:
        out("[audit-journal] merge needs --file <journal file>: the file being "
            "resolved. Its BASENAME is what seeds the chain, so the result can "
            "only be written back under that name.")
        return 2
    path = os.path.normpath(target if os.path.isabs(target)
                            else os.path.join(project, target))
    name = os.path.basename(path)
    if not name.endswith(".jsonl"):
        out("[audit-journal] --file must name a .jsonl journal file (got %r)"
            % (name,))
        return 2
    # F343: AND IT MUST BE A FILE IN THE TRAIL, which the suffix does not say.
    # `in_journal` was already here and was called by nobody, so `--file
    # <basename>` -- exactly what an operator copies out of git's conflict
    # message -- resolved against the project root, found nothing there, and
    # got the answer a name holding no row gets: nothing to lose. The merge was
    # then written to that stray path. The live journal was untouched, `verify`
    # passed over a directory the file was not in, and `journal_files` cannot
    # see it, so every surface agreed nothing had happened.
    if not in_journal(project, path, config):
        out("[audit-journal] --file must name a file inside the journal "
            "directory (%s), and %r resolves to %s. A bare basename copied out "
            "of git's conflict message resolves against the project root, "
            "where a merge written under it is a file no reader of the trail "
            "ever looks at. Pass the path git printed, relative to the project "
            "root." % (journal_dir(project, config), target, path))
        return 2
    if bool(args.ours) != bool(args.theirs):
        out("[audit-journal] --ours and --theirs go together: pass both to "
            "merge two files you extracted yourself, or neither to take the "
            "two sides git already has (index stages 2 and 3 of --file).")
        return 2
    sides = []
    from_index = not args.ours
    if args.ours:
        for label, side in (("ours", args.ours), ("theirs", args.theirs)):
            if not os.path.isfile(side):
                out("[audit-journal] the %s side is not a file: %s"
                    % (label, side))
                return 2
            sides.append(read_file(side))
    else:
        for label, stage in (("ours", 2), ("theirs", 3)):
            blob = _git_stage(path, stage)
            if blob is None:
                out("[audit-journal] could not read the %s side "
                    "(git show :%d:./%s). Those two stages are what a "
                    "CONFLICTED merge leaves in the index, so this works while "
                    "the conflict is open -- past that, extract the two sides "
                    "yourself and pass --ours/--theirs."
                    % (label, stage, name))
                return 2
            sides.append(rows_from_text(blob.decode("utf-8", "replace")))
    torn = []
    for label, pair in (("ours", sides[0]), ("theirs", sides[1])):
        if pair[1]:
            torn.append(label)
    res = merge_rows(sides[0][0], sides[1][0], name,
                     actor={"author": args.author, "sessionId": args.session,
                            "via": MERGE_VIA},
                     torn=tuple(torn))
    # THE RESULT IS GRADED AGAINST THE FILE IT WOULD REPLACE (F328), and the
    # verdict joins the OTHER refusals rather than getting a shape of its own:
    # same `REFUSED:` line, same closing sentence, same exit code, and the
    # `--json` caller below sees it too. `rows` is emptied with it, because
    # `merge_rows` promises a refusal never also hands back a half-built answer.
    #
    # THE GRADING IS PASSED IN RATHER THAN RUN HERE, WHICH IS F340. It used to
    # run at this point -- before `write_merged` was called, and therefore
    # before the lock that write takes existed -- so a row appended between the
    # grading and `os.replace` was graded by nobody and deleted, with this
    # command printing `wrote <name>` and `verify` calling the survivors clean.
    # `write_merged` now takes the lock once and does read, grade and replace
    # inside it; what to refuse is still this file's question, and
    # `_target_faults` is the whole of it, `--dry-run` included so a preview
    # grades what a write would.
    #
    # ONE PATH IT DELIBERATELY DOES NOT ASK ABOUT: a target that is not there
    # yet. The read gives `""`, so the question answers itself -- a name that
    # holds no row cannot lose one. Not a branch, so there is no branch to get
    # wrong.
    #
    # AND THE `from_index` PATH ASKS A DIFFERENT ONE. There the two sides ARE
    # stages 2 and 3 of this very file -- git built the working copy out of
    # them, so no row that came from a stage can be missing from their union.
    # An order-aware test would refuse every genuine conflict resolution: that
    # working copy's parseable rows are the two stages concatenated with markers
    # between them, an order no chain ever had. The premise is measured rather
    # than argued -- the `mg3c` case asserts the verdict on that conflicted text
    # is NOT held, so an exemption resting on it goes red if it stops being
    # true -- and `_journal_io.rows_unaccounted` asks the presence-only question
    # that path CAN get wrong, beside `anchor_verdict` rather than as a second
    # comparator here, because `anchor_verdict` must keep asking about order:
    # order is what makes it able to catch a forgery.
    #
    # AND THE WRITE HAPPENS BEFORE ANYTHING IS RENDERED, so both renderings
    # report the same operation. It used to sit inside the human-readable tail,
    # which is how `--json` came to describe a write it had returned before
    # making (F331).
    written, error = False, None
    if res["ok"]:
        merged = merge_text(res["rows"])
        side_rows = list(sides[0][0]) + list(sides[1][0])

        def grade(text, unreadable):
            return _target_faults(name, text, unreadable, merged, side_rows,
                                  from_index)

        try:
            outcome = write_merged(path, merged, grade, dry_run=args.dry_run)
            written = outcome["written"]
            if outcome["refusals"]:
                res["refusals"] = list(res["refusals"]) + outcome["refusals"]
                res["rows"] = []
                res["ok"] = False
        except Exception as exc:
            error = str(exc)
    if not res["ok"]:
        if args.as_json:
            out(_merge_json(res, args.dry_run, False, None))
            return 1
        for line in res["refusals"]:
            out("REFUSED: " + line)
        out("\n[audit-journal] nothing written: %d refusal(s) in %s. A merge "
            "that dropped or reordered a row would be worse than the conflict "
            "it replaces, so it refuses rather than guessing."
            % (len(res["refusals"]), name))
        return 1
    if written:
        # The same claim `cmd_append` leaves: this write puts a journal file
        # into `git status`, and an unclaimed one is what `guard-bash-writes`
        # reports as a shell write into the append-only trail.
        _journal_io.record_plugin_write(project, config,
                                        _journal_io.CLI_JOURNAL_WRITER,
                                        path)
    if args.as_json:
        out(_merge_json(res, args.dry_run, written, error))
        return 1 if error is not None else 0
    for line in res["notes"]:
        out("NOTE: " + line)
    out("[audit-journal] %s: %d row(s) -- %d shared, %d only in ours, %d only "
        "in theirs, %d re-linked (`prev`/`hash` recomputed; no row's content "
        "touched)" % (name, len(res["rows"]), res["shared"], res["oursOnly"],
                      res["theirsOnly"], res["relinked"]))
    if args.dry_run:
        out("[audit-journal] --dry-run: %s left as it is" % (name,))
        return 0
    if error is not None:
        out("[audit-journal] could not write %s: %s" % (path, error))
        return 1
    # THE BASIS AND NOT THE HABIT. "both inputs are in git" is half of what
    # makes re-chaining auditable rather than a rewrite, and it is only true of
    # the sides that CAME from the index. Said unconditionally it would be a
    # claim this command cannot support about two files a caller extracted
    # itself -- so each source gets the sentence its own evidence supports.
    if from_index:
        out("[audit-journal] wrote %s. Both sides came from the index, so both "
            "are still in git and the merge commit holds both parents -- which "
            "is what makes this auditable rather than a rewrite. `git add` it, "
            "and run `audit-journal.py verify` before you commit." % (name,))
    else:
        out("[audit-journal] wrote %s from the two files you named. Nothing "
            "here can say whether those are in git, and that is the half that "
            "makes re-chaining auditable -- so keep both commits reachable, "
            "and run `audit-journal.py verify` before you commit." % (name,))
    return 0


def cmd_sessions(args, out):
    """Which session wrote which journal file (F309).

    The file name carries the writer id the ROW supplied, truncated to fit a
    name, and for the hook that writes most rows that is not the id the session
    reads from Bash. So the name cannot be read back to a session and this is
    what maps it."""
    project = os.path.abspath(args.project)
    res = session_index(project)
    if args.as_json:
        out(json.dumps(res, indent=2, sort_keys=True))
        return 0
    if not res["exists"]:
        out("[audit-journal] no journal yet at %s" % res["dir"])
        return 0
    if not res["files"]:
        out("[audit-journal] no journal files in %s -- nothing has written a "
            "row here yet" % res["dir"])
        return 0
    for ent in res["files"]:
        out("%s%s" % (ent["file"], "   <- this session" if ent["mine"] else ""))
        out("    %d row(s)%s"
            % (ent["rows"], ("  %s .. %s" % (ent["first"], ent["last"]))
               if ent["first"] else ""))
        out("    writer id in the name   %s" % (ent["writer"] or "(none)"))
        for label, pairs in (("actor.sessionId       ", ent["sessionIds"]),
                             ("actor.envSessionId    ", ent["envSessionIds"])):
            for value, times in pairs:
                out("    %s %s  (%d row(s))" % (label, value, times))
        if not ent["envSessionIds"]:
            # NOT "the ids agree": absent means one of two things and nothing
            # here can tell them apart, so it says both rather than picking the
            # reassuring one.
            out("    no actor.envSessionId on any row -- either the writer read "
                "the same id from its environment, or these rows predate the "
                "field; this cannot tell those apart")
    if not res["env"]:
        out("[audit-journal] $%s is not set here, so no file could be matched "
            "to the session running this" % ENV_SESSION_VAR)
    elif not res["mine"]:
        out("[audit-journal] $%s is %s and names none of the files above: this "
            "session has written no rows yet, or its rows predate the mapping "
            "field" % (ENV_SESSION_VAR, res["env"]))
    return 0


def cmd_archive(args, out):
    """Move whole month-files into <journal>/archive/ -- `git mv`, never a
    rewrite, because the hash chain survives only untouched bytes and the
    genesis seed is the file's BASENAME: a moved file verifies exactly as it
    did live, and git carries its committed history across the move so the
    git anchor keeps holding.

    Default: every month-file older than the current month. --before YYYY-MM
    archives strictly older months. The current month (and anything newer) is
    never archived -- it is still being written.

    DECISION (pinned, v0.37 D): an UNTRACKED file is moved with os.rename
    rather than refused. `git mv` fails on untracked files, and the reason
    git mv is the mechanism -- carrying COMMITTED history across the move --
    does not exist for a file with no committed past: a plain rename loses
    nothing the chain or the anchor ever had. The doctor's never-committed
    warning follows the file into archive/ and keeps nagging until it is
    committed, which is the honest state of affairs.
    """
    import shutil
    import subprocess

    def git(directory, *a):
        try:
            res = subprocess.run(["git", "-C", directory] + list(a),
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=30)
            return res.returncode, (res.stdout or b"").decode("utf-8",
                                                              "replace"), \
                (res.stderr or b"").decode("utf-8", "replace")
        except Exception as exc:
            return 1, "", str(exc)

    project = os.path.abspath(args.project)
    config = load_config(project)
    directory = journal_dir(project, config)
    current = time.strftime("%Y-%m", time.gmtime())
    before = (args.before or "").strip()
    if before and not _MONTH_RE.match(before):
        out("[audit-journal] --before must be YYYY-MM (got %r)" % before)
        return 2
    cutoff = before or current
    if cutoff > current:
        out("[audit-journal] --before %s reaches into the future; the current "
            "month and anything newer is still being written and is never "
            "archived -- archiving everything older than %s instead"
            % (before, current))
        cutoff = current
    if not os.path.isdir(directory):
        out("[audit-journal] nothing to archive: no journal at %s" % directory)
        return 0
    in_repo = False
    if shutil.which("git"):
        rc, txt, _err = git(directory, "rev-parse", "--is-inside-work-tree")
        in_repo = rc == 0 and txt.strip() == "true"
    if not in_repo:
        # The whole point of archiving by `git mv` is that committed history
        # follows the move and the git anchor keeps holding. No repository
        # means no history to carry -- and an archive that silently plain-moved
        # files here would teach people the operation is safe anywhere.
        out("[audit-journal] not inside a git repository (or git is not on "
            "PATH): archive moves files with `git mv` so their committed "
            "history follows the move and the git anchor keeps holding -- "
            "with no repository there is nothing to carry. Run `git init` "
            "and commit the journal first.")
        return 2
    moved, kept, failed = [], [], []
    arch = os.path.join(directory, ARCHIVE_DIRNAME)
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        month = name[:7]
        if not _MONTH_RE.match(month):
            kept.append("%s: kept -- no YYYY-MM month prefix to judge it by"
                        % name)
            continue
        if month >= cutoff:
            continue        # current/future months and >= --before stay live
        if os.path.exists(os.path.join(arch, name)):
            kept.append("%s: kept -- archive/%s already exists; refusing to "
                        "overwrite it (verify will warn about the duplicate)"
                        % (name, name))
            continue
        os.makedirs(arch, exist_ok=True)
        rc, _txt, _err = git(directory, "ls-files", "--error-unmatch",
                             "--", name)
        if rc == 0:
            rc2, _txt2, err2 = git(directory, "mv", name,
                                   "%s/%s" % (ARCHIVE_DIRNAME, name))
            if rc2 != 0:
                failed.append("%s: git mv failed (%s)"
                              % (name, err2.strip() or "unknown error"))
                continue
            moved.append("%s -> archive/%s (git mv; committed history "
                         "follows the move)" % (name, name))
        else:
            try:
                os.rename(os.path.join(directory, name),
                          os.path.join(arch, name))
            except OSError as exc:
                failed.append("%s: could not move (%s)" % (name, exc))
                continue
            moved.append("%s -> archive/%s (renamed; never committed, so "
                         "there was no git history to carry)" % (name, name))
    for line in kept:
        out("[audit-journal] " + line)
    for line in failed:
        out("[audit-journal] FAILED " + line)
    for line in moved:
        out("[audit-journal] archived " + line)
    if moved:
        out("[audit-journal] %d file(s) moved, 0 bytes rewritten: a hash "
            "chain survives only untouched bytes, and its seed is the file's "
            "basename, so every moved file verifies exactly as it did. "
            "Commit the archive/ directory so the git anchor pins it."
            % len(moved))
    elif not kept and not failed:
        out("[audit-journal] nothing to archive: no month-file older than %s "
            "in %s" % (cutoff, directory))
    return 1 if failed else 0


def cmd_show(args, out):
    project = os.path.abspath(args.project)
    rows = read_all(project)
    if args.target:
        rows = [r for r in rows if r.get("target") == args.target]
    if args.limit > 0:
        rows = rows[-args.limit:]
    if args.as_json:
        out(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if not rows:
        out("[audit-journal] no rows")
        return 0
    for r in rows:
        actor = r.get("actor") or {}
        out("%s  %-18s %-28s %s"
            % (r.get("ts"), r.get("action"), (r.get("target") or "")[-28:],
               actor.get("author") or actor.get("sessionId") or "unknown"))
        if r.get("summary"):
            out("    %s" % r["summary"])
    return 0


# --- the argument surface -----------------------------------------------------
def main(argv, out=print):
    p = argparse.ArgumentParser(prog="audit-journal.py", add_help=True)
    p.add_argument("command", choices=["append", "verify", "show", "archive",
                                       "merge", "sessions"])
    p.add_argument("--project", default=".")
    p.add_argument("--before", default="")
    p.add_argument("--action", default="")
    p.add_argument("--target", default="")
    p.add_argument("--summary", default="")
    p.add_argument("--details", default=None)
    p.add_argument("--file", default="")
    p.add_argument("--ours", default="")
    p.add_argument("--theirs", default="")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--via", default="cli")
    p.add_argument("--author", default=None)
    p.add_argument("--session", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not os.path.isdir(args.project):
        out("[audit-journal] not a directory: %s" % args.project)
        return 2
    if args.command == "append" and not args.action.strip():
        out("[audit-journal] append needs --action")
        return 2
    # --details is parsed HERE, before anything is written: malformed JSON is a
    # usage error (2), never a silently plain row -- a caller passing structured
    # news must find out it was dropped.
    args._details = None
    if args.command == "append" and args.details:
        try:
            parsed = json.loads(args.details)
        except Exception as exc:
            out("[audit-journal] --details is not valid JSON: %s" % exc)
            return 2
        if not isinstance(parsed, dict):
            out("[audit-journal] --details must be a JSON object")
            return 2
        args._details = parsed
    try:
        if args.command == "append":
            return cmd_append(args, out)
        if args.command == "verify":
            return cmd_verify(args, out)
        if args.command == "archive":
            return cmd_archive(args, out)
        if args.command == "merge":
            return cmd_merge(args, out)
        if args.command == "sessions":
            return cmd_sessions(args, out)
        return cmd_show(args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[audit-journal] internal error: %s" % exc)
        return 2


if __name__ == "__main__":
    from _output import safe_stdio       # same dir; sys.path[0] when run directly
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than falling through to `main`, which would read the flag
        # as an unknown command. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-journal.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_journal.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
