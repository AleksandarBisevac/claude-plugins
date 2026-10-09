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
  2  usage error - the manifest will not load, the shard path is not a file,
     or `--project-dir` was given and the manifest does not sit under it

Without `--project-dir` the project is the manifest's own
(`_panel_write.project_of_manifest`) - never the directory the command was
typed in.

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

import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)
import _evidence_io as _ev  # noqa: E402  (evidence_dir, verify_rows - the one chain)
import _journal_io  # noqa: E402  (config loading, rows_from_text)
import _loader  # noqa: E402  (script_path: the printed full-gate.py, never loaded)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _panel_write  # noqa: E402  (project_of_manifest: the project a named manifest is in)

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
    in a shell. The caller hands both paths in absolute for the same reason,
    and canonical (`canonical_manifest`) so one project prints one command."""
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
def _lexically_under(path, directory):
    """True when `path` sits at or below `directory` as SPELLED, no link
    followed - the relation `project_of_manifest` walks, from the manifest up
    through its parents as typed."""
    path, directory = os.path.abspath(path), os.path.abspath(directory)
    try:
        return os.path.commonpath([path, directory]) == directory
    except ValueError:
        return False


def _is_under(path, directory):
    """True when `path` sits at or below `directory` either as spelled or with
    both resolved through symlinks.

    RESOLVED, because a temp directory reached through a link is still the
    directory it names. AS SPELLED, because a directory between the manifest
    and its project may itself be a link leaving the project -
    `<T>/docs/audit` pointing elsewhere - and that manifest is still `<T>`'s:
    it is the project the walk without `--project-dir` names for it, so the
    pair this command prints for it must be one this check accepts back."""
    if _lexically_under(path, directory):
        return True
    return _lexically_under(os.path.realpath(path),
                            os.path.realpath(directory))


def resolve_project(manifest_path, project_dir):
    """`(project, manifest, refusal)` - the project this import writes into
    and the manifest spelled beside it, or why it will not.

    WITHOUT `--project-dir` the project is the one the MANIFEST belongs to,
    by the plugin's one answer to that question,
    `_panel_write.project_of_manifest` - the answer `audit-task.py` reads for
    a named manifest: the first ancestor holding `.claude/` or `.git`, and
    without one `<T>` for the default `<T>/docs/audit/<file>` layout or the
    manifest's own directory anywhere else. A count of directories up from
    the file is right for the default layout alone. The
    current directory is not asked: an import typed from anywhere else would
    otherwise land the shard in a ledger the manifest's plan never reads, and
    print a `--learn-from` command pairing that plan with the wrong ledger.

    WITH `--project-dir`, a manifest that does not sit under it is refused:
    the printed command would pair one project's plan with another's ledger,
    and there is no reading of the pair that is not a mistake.

    The project returned is resolved through symlinks either way, and the
    manifest beside it is spelled from that same unresolved project by
    `canonical_manifest`, so the two cannot be computed apart."""
    manifest_abs = os.path.abspath(manifest_path)
    if project_dir is None:
        project = _panel_write.project_of_manifest(manifest_abs)
    else:
        project = os.path.abspath(project_dir)
        if not _is_under(manifest_abs, project):
            return project, manifest_abs, (
                "the manifest %s is not under --project-dir %s - the shard "
                "would land in one project's ledger and be learned from into "
                "another's plan. Pass the directory the manifest belongs to, "
                "or leave --project-dir out and the manifest's own project is "
                "used" % (manifest_abs, project))
    return (os.path.realpath(project),
            canonical_manifest(manifest_abs, project), "")


def canonical_manifest(manifest_path, project):
    """The manifest spelled the one way this command prints it beside
    `project` - the project as found or typed, NOT yet resolved.

    ONE SPELLING PER DIRECTORY, WHATEVER THE CALL SHAPE. A relative manifest
    is made absolute off the current directory, and the current directory
    comes back from the operating system in its own spelling - physical on
    POSIX however it was reached, the short 8.3 form on Windows when that is
    how it was entered - while an absolute manifest or a `--project-dir`
    comes back as typed. Left alone, one project printed two different
    commands depending on how the import was typed.

    UNDER THE PROJECT IT IS PRINTED WITH. A manifest spelled below `project`
    is the resolved project joined with the manifest's path below the
    UNRESOLVED one, so a link between the two - `<T>/docs/audit` pointing out
    of `<T>` - is kept as a path inside `<T>` rather than followed out of it.
    Resolving the manifest's directory on its own would print a manifest that
    is not under the printed `--project-dir`. A manifest reached only through
    resolution (`--project-dir` typed in another spelling of the same
    directory) has no such path, and takes its directory resolved instead.

    The file's own name is not followed either way: a manifest that is itself
    a link stays the file this import was handed, not wherever it points."""
    manifest_abs = os.path.abspath(manifest_path)
    if _lexically_under(manifest_abs, project):
        return os.path.join(os.path.realpath(project),
                            os.path.relpath(manifest_abs,
                                            os.path.abspath(project)))
    return os.path.join(os.path.realpath(os.path.dirname(manifest_abs)),
                        os.path.basename(manifest_abs))


def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="import-evidence.py", add_help=True, allow_abbrev=False,
        description="Bring a CI build's evidence ledger file into this "
                    "checkout whole, after its own chain verifies.")
    parser.add_argument("manifest")
    parser.add_argument("shard", help="the ledger file a CI build published")
    parser.add_argument("--project-dir", dest="project_dir", default=None,
                        help="the directory holding .claude/ and the records "
                             "(default: the project the manifest belongs to - "
                             "the nearest directory above it holding .claude/ "
                             "or .git, else <T> for <T>/docs/audit/<file>, "
                             "else the manifest's own directory); the "
                             "manifest must sit under it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return _claude_home.attach_usage_hint(parser)


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

    project, manifest_path, refusal = resolve_project(args.manifest,
                                                      args.project_dir)
    if refusal:
        sys.stderr.write("ERROR: %s\n" % (refusal,))
        return E_USAGE
    # ABSOLUTE, so the printed command does not depend on the directory it
    # is pasted into; CANONICAL, so it does not depend on how it was typed.
    code, answer = import_shard(project, args.shard,
                                manifest_path=manifest_path)
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        render(answer, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("import-evidence.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_import_evidence.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
