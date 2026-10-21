#!/usr/bin/env python3
"""
The command around the manifest rules: read a file, print findings, pick an exit code.

The rules themselves are `_manifest_rules.py`, imported below. They used
to live in this file, and moving them was not tidying: four modules needed
`validate()` and reached it through `_loader.load_script("validate-manifest.py")`,
which is a helper and three peers all loading an entry point — four of
the seventeen edges `_deps.KNOWN_LAYER_DEBT` recorded. A rule four modules share
belongs below all four of them, not beside one.

Output classes:
  FINDING  — structural defect; the manifest is INVALID (exit 1).
  WARNING  — suspicious but tolerated (unknown/typo'd keys, pre-0.3 status
             combinations); exit stays 0 when there are only warnings.

Usage:
  python3 validate-manifest.py <manifest-path> [--verbose] [--strict]

`--strict` reads every line the published schema raises (the whole-plan check's
`rules.schema.*` and the bug values' `crossrefs.bugs.schema-*`) as a FINDING, so
the command rejects exactly the plans `ajv` rejects. Without it those lines are
warnings naming the release that refuses them, because `COMPATIBILITY.md`
promises that a plan which validates keeps validating inside the major line.

Run as a command, a VALID plan is said in one line: the OK line, naming
`--verbose` when there were warnings (`_output.terse_cli`). An invalid plan
prints in full, exactly as `main` prints it.

`--verbose` prints one line per warning. `main` without it groups the warnings
that differ only in the item they name (`_warning_groups`), because a rule that
fires once per task buried a priority warning nobody read on a real plan; every
elided line names this flag, so nothing is out of reach.

Which is why the OK line names WARNING LINES and ITEMS separately whenever the
collapse did something (`warning_tail`): the printed lines and the counted items
are deliberately different numbers, and a summary carrying only the second one
reads as the difference having been swallowed.

Exit codes: 0 = valid (warnings allowed) · 1 = findings · 2 = usage error or
unreadable/unparseable file.

This module carries no `--selftest` of its own any more; its cases live in
`tests/test_validate_manifest.py`, byte-identical labels and all —
see `tests/_harness.py`.
"""
import os
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

import _evidence_io as _ev  # noqa: E402  (the ledger: suite_keys, project/config resolution)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _manifest_rules  # noqa: E402  (the rules this command is a front end for)
import _warning_groups as _wg  # noqa: E402  (the shape a repeated warning prints in)

# ONE name, and the restraint is the point. Re-exporting the rules' internals here
# would put their whole surface back on an entry point, which is the shape the
# layer split was undoing — `render-report.py` aliases a dozen names for a suite
# that reads the assembled document and cannot be written any other way; this file
# has no such reason, so it takes none. `tests/test_validate_manifest.py` c10 fails
# if an alias creeps back.
validate = _manifest_rules.validate


# --- the summary's own arithmetic -----------------------------------------------
def warning_tail(n_lines, n_items):
    """How the OK line says how many warnings there were, from BOTH counts.

    TWO NUMBERS ONLY WHEN THEY DIFFER, because only then is there anything to
    reconcile. `collapse()` renders same-shape warnings as one line, so on a real
    plan the item count stopped being a count of anything on screen: a run that
    printed a pair of WARNING lines and closed with a total in the twenties read
    as the rest having been swallowed, and both numbers were true. The
    house rule is that a claim carries the basis that makes it true, and the
    basis for the item count is the collapse - so when the collapse did something
    the line says so, naming both.

    When nothing collapsed the two counts are one fact and the second number
    would be noise, so the count the reader can COUNT is printed on its own.
    """
    if not n_items:
        return ""
    if n_items == n_lines:
        return ", %d warning(s)" % (n_lines,)
    return ", %d warning line(s), %d item(s)" % (n_lines, n_items)


# --- cli ------------------------------------------------------------------------
def success_line(lines):
    """A valid plan's one line: the OK line, which names the file and counts the
    warnings, and - when there were any - the flag that prints them."""
    ok = [ln for ln in lines if ln.startswith("OK: ")]
    if len(ok) != 1:
        return None
    warned = any(ln.startswith("WARNING: ") for ln in lines)
    return ok[0] + (" - `--verbose` prints the warnings" if warned else "")


# The rule codes the published schema raises, whichever check raised them.
SCHEMA_CODES = ("rules.schema.", "crossrefs.bugs.schema-")


def is_schema_line(line):
    """True for a line the published schema raised (`SCHEMA_CODES`)."""
    return str(_output.finding_code(line) or "").startswith(SCHEMA_CODES)


def strict_split(findings, warnings):
    """(findings, warnings) with every schema warning moved to the findings -
    the `--strict` reading, which is the 4.0.0 one."""
    moved = [w for w in warnings if is_schema_line(w)]
    return (list(findings) + moved,
            [w for w in warnings if not is_schema_line(w)])


def main(argv):
    verbose = "--verbose" in argv
    strict = "--strict" in argv
    paths = [a for a in argv if a not in ("--verbose", "--strict")]
    if len(paths) != 1:
        sys.stderr.write("usage: validate-manifest.py <manifest-path> "
                         "[--verbose] [--strict]\n")
        return 2
    try:
        manifest = _mio.load_manifest(paths[0])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (paths[0], exc))
        return 2

    # The schema the plan is checked against is loaded HERE, once, so the rules
    # read no file; an unreadable one is this command's finding to report.
    schema, unreadable = _manifest_rules.load_validation_schema()
    try:
        findings, warnings = validate(manifest, schema=schema)
        findings = list(unreadable) + findings
    except Exception as exc:  # defensive; validate() should never raise
        print("FINDING: internal validator error: %s" % exc)
        return 1
    if strict:
        findings, warnings = strict_split(findings, warnings)

    # The one question `validate()` cannot be asked. It takes the ASSEMBLED
    # manifest, and an index-only field written into a shard body is already gone
    # by then - which is precisely the state worth saying out loud, because the
    # value LOOKS accepted and orders nothing. This command has the path, so it
    # asks `_manifest_io` where both halves of the file are open.
    warnings = list(warnings) + [
        "phase %s: %r sits in the shard body, where nothing reads it - it is an "
        "INDEX-ONLY field (the stub carries it so the order is computable "
        "without opening a shard); this copy was ignored"
        % (pid or "?", field)
        for pid, field in _mio.index_only_in_bodies(paths[0])]
    # ...and its mirror image: a stub whose copy of a shard's key has fallen behind.
    # The assembled manifest lets the body win, so `validate()` cannot see it either,
    # and the stub is what a reader of the index alone is answered from. One warning
    # per phase in the `phase <id>: <body>` shape with an id-free body, so the
    # collapse below prints a count and the first ids rather than every stub.
    stale = _mio.stale_stubs(paths[0])
    warnings = warnings + [
        "phase %s: index stub mirrors %s as %s while its shard holds %s - a reader "
        "of the index alone gets the stub's value; `%s` re-mirrors every stub, "
        "under the index lock"
        % (pid, key, "nothing" if was is None else was, now,
           _manifest_rules.SETTLE_COMMAND)
        for pid, key, was, now in stale]

    # A directory in a task's `files` covers every file under it. Whether an entry
    # IS a directory is the file system's to say, which `validate()` reads none
    # of; this command holds the manifest path, so it resolves the project and
    # hands the rules the test. A warning, never a finding: validation stays additive.
    project = _output.project_of_manifest(paths[0])
    warnings = warnings + _manifest_rules.directory_entry_warnings(
        manifest, lambda entry: os.path.isdir(os.path.join(project, entry)))

    # THE EVIDENCE ARM OF THE SAME 'RUNS NO SUITE' WARNING. `validate()` already
    # asked the CERTAIN arm with no evidence at all (`_manifest_rules._check_meta`
    # -> `phase_gate_suite_gap(manifest)`, `suite_keys=None`) - that answers only
    # a default left EMPTY after `meta.phaseGate.exclude`. This command is the one
    # caller that HAS the ledger, because it holds the manifest PATH
    # `_evidence_io.project_config_for` needs to resolve it; asked again only
    # when the certain arm stayed quiet, and only when `exclude` actually
    # declares something, so an ordinary plan with no `phaseGate` never pays for
    # a ledger read it has no question to ask of.
    _meta = manifest.get("meta") if isinstance(manifest, dict) else None
    _gate = (_meta or {}).get("phaseGate") if isinstance(_meta, dict) else None
    _exclude = (_gate or {}).get("exclude") if isinstance(_gate, dict) else None
    gap = _manifest_rules.phase_gate_suite_gap(manifest)
    if gap is None and isinstance(_exclude, list) and _exclude:
        _project, _config = _ev.project_config_for(paths[0])
        _read = _ev.read_rows(_project, _config)
        if _read["unreadable"]:
            # AN UNREADABLE LEDGER IS SAID, NEVER READ AS 'NO SUITE'. A torn
            # line, an unparseable row or a file this could not even open
            # means `suite_keys` would be computed over LESS than the ledger
            # actually holds - and the missing part is exactly as likely to be
            # the row that would have answered `running` as the one that
            # would not. THE CHOICE: `phase_gate_suite_gap` is not asked at
            # all here, rather than asked over the readable remainder and
            # presented as an answer the ledger cannot back - a partial read
            # is not a partial answer to THIS question, because one missing
            # row can flip `running` for the one key left after `exclude`.
            warnings = warnings + [
                "the evidence ledger could not be fully read (%s), so "
                "whether the phase gate runs a suite could not be checked "
                "against it - this is not 'phase gate runs no suite'"
                % (_output.some_of(
                    [_output.posix_rel(p, _project)
                     for p in _read["unreadableFiles"]]),)]
        else:
            gap = _manifest_rules.phase_gate_suite_gap(
                manifest, suite_keys=_ev.suite_keys(_read["rows"]))
    if gap is not None:
        warnings = warnings + [gap]

    # `hint` is this command's own spelling of the flag, because on its own
    # output "validate-manifest.py --verbose" would be telling the reader to run
    # what they just ran. The other four commands take the default.
    warning_lines = _wg.collapse(warnings, manifest, verbose=verbose,
                                 hint="--verbose")
    for line in warning_lines:
        print("WARNING: " + line)

    # FINDINGS ARE NOT COLLAPSED, and the refusal is deliberate: a finding stops
    # the command, every one of them has to be fixed, and the count already has a
    # line below that prints it. See `_warning_groups`'s docstring. Which is also
    # why THIS tail takes one number and the warning tail takes two: here the
    # printed lines and the counted items are the same list, so the number below
    # is one a reader can check by counting upwards.
    if findings:
        for line in findings:
            print("FINDING: " + line)
        print("\nINVALID: %d finding(s) in %s" % (len(findings), paths[0]))
        return 1

    n_tasks = sum(len(p.get("tasks") or []) for p in manifest.get("phases", []) if isinstance(p, dict))
    # BOTH COUNTS, from the lines that were actually printed rather than from a
    # second `collapse()` - re-collapsing here would be a second rendering, and
    # the whole defect was a summary describing a body it had not read.
    print("OK: %s valid (%d phases, %d tasks, %d bugs%s)"
          % (paths[0], len(manifest.get("phases", [])), n_tasks,
             len(manifest.get("bugs") or []),
             warning_tail(len(warning_lines), len(warnings))))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line,
                               keep_verbose=True))
