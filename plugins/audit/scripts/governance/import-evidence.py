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
  1  the chain does not hold, or a different file already holds that name
  2  usage error - the manifest will not load, or the shard path is not a file

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_import_evidence.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
import os
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
           "basename": basename, "runIds": [], "refused": ""}


def import_shard(project, shard_path, config=None):
    """`(exitCode, answer)` - verify `shard_path`'s chain and copy it whole into
    this project's evidence directory. Writes nothing on a refusal.

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
        text = raw.decode("utf-8")
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
            return E_OK, answer
        answer["refused"] = (
            "%s already holds a different file under this name - the chain's "
            "genesis is seeded from the basename alone, so two files sharing "
            "one name would read as one chain with two genesis rows"
            % (dest,))
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
    code, answer = import_shard(project, args.shard)
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
