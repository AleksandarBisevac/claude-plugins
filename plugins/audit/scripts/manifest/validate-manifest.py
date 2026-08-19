#!/usr/bin/env python3
"""
The command around the manifest rules: read a file, print findings, pick an exit code.

The rules themselves are `_manifest_rules.py` (layer 2), imported below. They used
to live in this file, and moving them was not tidying: four modules needed
`validate()` and reached it through `_loader.load_script("validate-manifest.py")`,
which is an L5 helper and three L7 peers all loading an L7 entry point — four of
the seventeen edges `_deps.KNOWN_LAYER_DEBT` recorded. A rule four modules share
belongs below all four of them, not beside one.

Output classes:
  FINDING  — structural defect; the manifest is INVALID (exit 1).
  WARNING  — suspicious but tolerated (unknown/typo'd keys, pre-0.3 status
             combinations); exit stays 0 when there are only warnings.

Usage:
  python3 validate-manifest.py <manifest-path>

Exit codes: 0 = valid (warnings allowed) · 1 = findings · 2 = usage error or
unreadable/unparseable file.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_validate_manifest.py`, byte-identical labels and all —
see `plugins/audit/tests/_harness.py`.
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

import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _manifest_rules  # noqa: E402  (the rules this command is a front end for)

# ONE name, and the restraint is the point. Re-exporting the rules' internals here
# would put their whole surface back on an entry point, which is the shape the
# layer split was undoing — `render-report.py` aliases a dozen names for a suite
# that reads the assembled document and cannot be written any other way; this file
# has no such reason, so it takes none. `tests/test_validate_manifest.py` c10 fails
# if an alias creeps back.
validate = _manifest_rules.validate


# --- cli ------------------------------------------------------------------------
def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: validate-manifest.py <manifest-path>\n")
        return 2
    try:
        manifest = _mio.load_manifest(argv[0])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (argv[0], exc))
        return 2

    try:
        findings, warnings = validate(manifest)
    except Exception as exc:  # defensive; validate() should never raise
        print("FINDING: internal validator error: %s" % exc)
        return 1

    for line in warnings:
        print("WARNING: " + line)

    if findings:
        for line in findings:
            print("FINDING: " + line)
        print("\nINVALID: %d finding(s) in %s" % (len(findings), argv[0]))
        return 1

    n_tasks = sum(len(p.get("tasks") or []) for p in manifest.get("phases", []) if isinstance(p, dict))
    print("OK: %s valid (%d phases, %d tasks, %d bugs%s)"
          % (argv[0], len(manifest.get("phases", [])), n_tasks,
             len(manifest.get("bugs") or []),
             ", %d warning(s)" % len(warnings) if warnings else ""))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("validate-manifest.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_validate_manifest.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
