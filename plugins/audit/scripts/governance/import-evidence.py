#!/usr/bin/env python3
"""Bring a CI build's own evidence ledger file into this checkout, whole.

WHY THIS EXISTS. `run-test-gate.py --record` writes an evidence row on the
machine that ran the gate. A CI runner is such a machine, and its ledger file
never reaches a clone by any route `git` did not carry - it is gitignored
scratch on the runner unless something copies it out. Until now the only way
to bring one home was a hand copy, and a hand copy verifies nothing: a byte
changed in transit, a line torn by a truncated artifact download, a shard
somebody typed over another writer's file under the same name - none of that
would be visible before the row was trusted.

WHAT "WHOLE" MEANS. This command never rewrites a row, never re-chains a file
and never merges two files under one name into a third. It reads the shard,
proves its own chain holds (`_evidence_io.verify_rows`, the SAME verifier
`audit-journal.py` and the doctor already trust - a second implementation here
would be a second opinion about what tampering looks like), and then copies
the bytes unchanged. A file already sitting under that name is compared byte
for byte: identical bytes is the same import arriving twice and is not an
error; different bytes under one basename is refused outright, because the
chain's own genesis is SEEDED from the basename (`_journal_io.genesis_prev`) -
two different chains sharing one name is exactly the substitution that seed
exists to catch, and silently picking a winner between them would be this
command inventing the finding instead of reporting it.

ONE RUN, ONE ROW. A shard under a NEW name whose runIds the ledger already
holds is refused too, naming each id and the file holding it, and so is a
shard repeating a runId among its own rows, naming the shard itself: every
reader of the directory counts rows, so the same run twice is counted twice.
A ledger that cannot be read in full refuses the import rather than reading as
empty - the check could not be made, and that is what the refusal says.

WHAT A RED FULL ROW ASKS OF YOU. A CI build records its full run and throws
its checkout away, so nothing learned from a red full run could be kept there.
After a successful import this command prints, for each imported row that is
full scope and red, the `python3 <full-gate.py> <manifest> --learn-from <runId>`
command that files what the run taught into this checkout's plan - both paths
absolute, so it runs as printed from any directory - printed, never run:
bringing a file in whole is not consent to write the plan.

WHAT IT DOES NOT PROVE. A ledger is evidence, not authentication. A new shard
starts at its own genesis the moment somebody names a file that way, so a
verified chain says the rows were not edited AFTER the file was written and
says nothing about who wrote it. The commit that carries the imported file
into this repository is the authorship trail; this command's own report says
so, every time, so a reader is not left assuming a green import means a
verified writer.

Usage:
  import-evidence.py <manifest> <shard.jsonl> [--json] [--project-dir DIR]

Exit codes:
  0  the file was copied whole, or an identical copy was already there
  1  the chain does not hold, a different file already holds that name, a
     run it carries is already in the ledger under another file or repeated
     inside the shard, or the ledger could not be read in full to ask
  2  usage error - the manifest will not load, or the shard path is not a file

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_import_evidence.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
import os
import shlex
import sys
import tempfile

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

import _evidence_io as _ev  # noqa: E402  (evidence_dir, verify_rows - the one chain)
import _journal_io  # noqa: E402  (config loading, rows_from_text)
import _loader  # noqa: E402  (script_path: the printed full-gate.py, never loaded)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)

E_OK, E_FAIL, E_USAGE = 0, 1, 2

PREFIX = "[import-evidence]"

AUTHENTICATION_NOTE = (
    "a ledger is evidence, not authentication: a new shard starts at its own "
    "genesis, so nothing here proves who wrote it, and the commit that "
    "carries it is the authorship trail")


# --- the import itself ----------------------------------------------------------
def _empty_answer(basename):
    """The shape every refusal and every success share, before the fields that
    differ are filled in - so a caller reading one key never meets a KeyError
    on the branch that never sets it."""
    return {"imported": False, "alreadyImported": False, "path": None,
           "basename": basename, "runIds": [], "refused": "", "duplicates": [],
           "learnFrom": []}


def learn_from_commands(rows, manifest_path, project):
    """The `full-gate.py --learn-from` command for each red full row in
    `rows`, in shard order - PRINTED, NEVER RUN.

    WHY HERE AND NOT IN CI. A CI build records its full run into its own shard
    and throws the checkout away, so learning there would file a coupling and
    a bug into a plan nobody keeps; the checkout that imports the shard is the
    first one that keeps what is written. Running it from this command would
    make an import write the plan, which is a different consent from bringing
    a file in whole.

    Red is `_evidence_io.row_is_red`, the runner's own reading.
    `manifest_path` is the one this import was given and `project` the one it
    resolved, so the command names the plan and the ledger this import just
    wrote into.

    RUNNABLE AS PRINTED, from any directory: the interpreter is spelled out
    and the script is the absolute path `_loader.script_path` resolves by
    basename - the resolution `full-gate.py` itself uses for
    `run-test-gate.py` - because a bare `full-gate.py` is 'command not found'
    in a shell. The caller hands both paths in absolute for the same reason."""
    script = shlex.quote(_loader.script_path("full-gate.py"))
    return ["python3 %s %s --learn-from %s --project-dir %s"
            % (script, shlex.quote(manifest_path),
               shlex.quote(str(row.get("runId"))), shlex.quote(project))
            for row in rows
            if row.get("scope") == _ev.FULL_SCOPE
            and _ev.row_is_red(row) and row.get("runId")]


def held_runs(project, config):
    """`(heldBy, unreadable)` - which ledger file already holds each runId, and
    which files could not be read in full.

    ONE READ, `_evidence_io.read_rows`, the reader every consumer of this
    directory trusts: its `rowFiles` names the file each row came from, and its
    `unreadableFiles` is the verdict on what was lost. A second walk to name the
    holder would be a second decode, free to disagree with this one about
    whether a file holds a row at all.
    """
    ledger = _ev.read_rows(project, config)
    held = {}
    for row, name in zip(ledger["rows"], ledger["rowFiles"]):
        run_id = str(row.get("runId") or "")
        if run_id and run_id not in held:
            held[run_id] = name
    return held, list(ledger["unreadableFiles"])


def duplicates_of(rows, held, basename):
    """Every runId in `rows` that is already a run - held by a ledger file, or
    carried by an earlier row of this same shard (`basename` is then the
    holder) - once each, in shard order, with the file holding it. A row
    carrying no runId is no claim to a run and so cannot duplicate one."""
    earlier, reported, out = set(), set(), []
    for row in rows:
        run_id = str(row.get("runId") or "")
        if not run_id:
            continue
        holder = held.get(run_id) or (basename if run_id in earlier else None)
        earlier.add(run_id)
        if holder is None or run_id in reported:
            continue
        reported.add(run_id)
        out.append({"runId": run_id, "file": holder})
    return out


def unreadable_refusal(paths):
    """The refusal for a ledger that could not be read in full, carrying the
    step that clears each of the causes `read_rows` folds into one list - a
    file that would not open, a byte that is not UTF-8, a torn tail, a bad
    line before the end. It cannot tell which one a file has, so it names all
    of them and points at the command that does; a refusal naming no next step
    would block every later import with nothing to act on.

    THE UNDECODABLE-BYTE REMEDY SAYS ONLY WHAT `verify` PRINTS for it: the
    codec's own message, which names the first such byte and its offset in
    the file's bytes - there is no line number to send the reader to."""
    return (
        "the duplicate-run check could not be made: %s could not be read in "
        "full, and a run lost there could be one this shard carries again. "
        "`audit-journal.py verify` names the cause for each file. A file that "
        "could not be opened at all (a permission, a lock, a path that is not "
        "a file) is cleared by making it readable and re-running the import. "
        "A file holding a byte that is not UTF-8 text is lost whole, every run "
        "in it: `verify` names the first such byte and its position, counted "
        "in bytes from the start of the file, not a line. It is cleared by "
        "restoring the file from its committed copy, or by removing that byte "
        "on purpose once you have read the row it sits in, and re-running the "
        "import. "
        "If a file ends with a partial line, a writer was interrupted there - "
        "those bytes are not a row. Truncate the partial line on purpose and "
        "re-run the import. Any other line that is not valid JSON is a "
        "corrupted row, which `verify` reports by line: restore the file from "
        "its committed copy, or remove that line on purpose once you have read "
        "it, and re-run the import."
        % (", ".join(paths),))


def import_shard(project, shard_path, config=None, manifest_path=None):
    """`(exitCode, answer)` - verify `shard_path`'s chain and copy it whole into
    this project's evidence directory. Writes nothing on a refusal.

    With `manifest_path`, a successful import's `learnFrom` carries the
    command for each red full row it holds (`learn_from_commands`), built off
    the rows this call already parsed rather than a second read of the file.

    THE VERIFIER IS BORROWED, NOT WRITTEN TWICE. `_evidence_io.verify_rows` is
    the one place a broken chain, an edited row or a corrupted mid-file line is
    graded; a second walk here would be free to disagree with it the first time
    either changed.

    A TORN LAST LINE IS CHECKED SEPARATELY, because `verify_rows` grades ROWS
    and a torn tail never becomes one - `_journal_io.rows_from_text` reports it
    as `torn` and leaves no row behind to carry a finding. Left unchecked, a
    shard truncated mid-download would import everything before the cut with
    no word said about what did not arrive.

    ATOMIC BY CONSTRUCTION: the bytes land in a temp file inside the SAME
    directory, and only `os.replace` gives the final name - so a reader who
    lists the directory mid-import sees either nothing or the whole file,
    never a partial one.
    """
    config = _journal_io.load_config(project) if config is None else config
    basename = os.path.basename(shard_path)
    answer = _empty_answer(basename)
    try:
        with open(shard_path, "rb") as fh:
            raw = fh.read()
    except Exception as exc:
        answer["refused"] = "cannot read %r (%s)" % (shard_path, exc)
        return E_FAIL, answer
    try:
        text = _ev.ledger_decode(raw)
    except Exception as exc:
        answer["refused"] = "%s is not UTF-8 text (%s)" % (basename, exc)
        return E_FAIL, answer
    rows, torn = _journal_io.rows_from_text(text)
    if torn:
        answer["refused"] = (
            "%s: the last line is not valid JSON - a recorded run was cut off "
            "mid-write, and nothing after that point can be trusted" % (basename,))
        return E_FAIL, answer
    verdict = _ev.verify_rows(rows, basename)
    if verdict["findings"]:
        answer["refused"] = verdict["findings"][0]
        return E_FAIL, answer
    run_ids = [str(row.get("runId") or "?") for row in rows
              if not row.get("_unparseable")]
    learn = (learn_from_commands([r for r in rows if not r.get("_unparseable")],
                                 manifest_path, project)
             if manifest_path else [])
    directory = _ev.evidence_dir(project, config)
    dest = os.path.join(directory, basename)
    if os.path.isfile(dest):
        try:
            with open(dest, "rb") as fh:
                existing = fh.read()
        except Exception as exc:
            answer["refused"] = "%s already exists and could not be read (%s)" % (
                dest, exc)
            return E_FAIL, answer
        if existing == raw:
            answer["imported"] = True
            answer["alreadyImported"] = True
            answer["path"] = dest
            answer["runIds"] = run_ids
            answer["learnFrom"] = learn
            return E_OK, answer
        answer["refused"] = (
            "%s already holds a different file under this name - the chain's "
            "genesis is seeded from the basename alone, so two files sharing "
            "one name would read as one chain with two genesis rows"
            % (dest,))
        return E_FAIL, answer
    # A run is one run whichever file carries it: every reader of this
    # directory counts rows, so a second copy - under another name, or a
    # second row inside this shard - is a second count. Checked after the
    # same-name branch, which is why the identical re-import above never
    # meets it, and before anything is written.
    held, unreadable = held_runs(project, config)
    if unreadable:
        answer["refused"] = unreadable_refusal(unreadable)
        return E_FAIL, answer
    duplicates = duplicates_of([r for r in rows if not r.get("_unparseable")],
                               held, basename)
    if duplicates:
        answer["duplicates"] = duplicates
        answer["refused"] = (
            "%s carries run(s) that are already runs - imported, each would be "
            "counted twice:\n%s" % (basename, "\n".join(
                "  runId %s already in %s" % (d["runId"], d["file"])
                for d in duplicates)))
        return E_FAIL, answer
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix="." + basename + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, dest)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise
    answer["imported"] = True
    answer["path"] = dest
    answer["runIds"] = run_ids
    answer["learnFrom"] = learn
    return E_OK, answer


def render(answer, out=print):
    """Print what happened, in the order somebody reading a terminal needs it."""
    if answer.get("refused"):
        out("%s REFUSED: %s" % (PREFIX, answer["refused"]))
        return
    if answer.get("alreadyImported"):
        out("%s %s is already imported (%d byte-identical row(s), unchanged)"
            % (PREFIX, answer["basename"], len(answer["runIds"])))
    else:
        out("%s brought %s in whole (%d row(s))"
            % (PREFIX, answer["basename"], len(answer["runIds"])))
    for run_id in answer["runIds"]:
        out("  runId %s" % (run_id,))
    out("  %s" % (AUTHENTICATION_NOTE,))
    for command in answer.get("learnFrom") or []:
        out("%s a red full run is learned from here, not where it ran: %s"
            % (PREFIX, command))


# --- cli ------------------------------------------------------------------------
def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="import-evidence.py", add_help=True, allow_abbrev=False,
        description="Bring a CI build's evidence ledger file into this "
                    "checkout whole, after its own chain verifies.")
    parser.add_argument("manifest")
    parser.add_argument("shard", help="the ledger file a CI build published")
    parser.add_argument("--project-dir", dest="project_dir", default=".",
                        help="the directory holding .claude/ and the records "
                             "(default: the current directory)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv, out=print):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK

    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n"
                         % (args.manifest, exc))
        return E_USAGE
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: manifest %s is not a JSON object\n"
                         % (args.manifest,))
        return E_USAGE
    if not os.path.isfile(args.shard):
        sys.stderr.write("ERROR: %s is not a file\n" % (args.shard,))
        return E_USAGE

    project = os.path.abspath(args.project_dir)
    # ABSOLUTE, so the printed command does not depend on the directory it
    # is pasted into.
    code, answer = import_shard(project, args.shard,
                                manifest_path=os.path.abspath(args.manifest))
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        render(answer, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("import-evidence.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_import_evidence.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
