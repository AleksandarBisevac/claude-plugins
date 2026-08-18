#!/usr/bin/env python3
"""
The command around the config rules: read a file, print findings, pick an exit code.

The rules themselves are `_config_rules.py` (layer 2), imported below. They used
to live in this file, and moving them was not tidying: three modules needed them
and reached this entry point through `_loader.load_script("validate-config.py")` —
`_panel_settings` (layer 2!), `_panel_state` (layer 5) and `audit-doctor` (layer 7),
three of the seventeen edges `_deps.KNOWN_LAYER_DEBT` recorded, and the
`_panel_settings` one was the deepest inversion in the table.

Output classes:
  FINDING  — the config is INVALID / would be misread (exit 1).
  WARNING  — tolerated but suspicious (unknown/typo'd keys); exit stays 0.

Usage:
  python3 validate-config.py <config-path>

Exit codes: 0 = valid (warnings allowed) · 1 = findings · 2 = usage error or
unreadable/unparseable file.

This module carries no inline `--selftest` any more; its cases live in
`plugins/audit/tests/test_validate_config.py` — see `plugins/audit/tests/_harness.py`.
The flag is still accepted and still exits 0, pointing there.
"""
import json
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

import _config_rules  # noqa: E402  (the rules this command is a front end for)

# ONE name, the same restraint `validate-manifest.py` takes: re-exporting the
# rules' key sets and sub-checkers here would put their whole surface back on an
# entry point, which is the shape the layer split was undoing.
# `tests/test_validate_config.py` cc3 fails if an alias creeps back.
validate_config = _config_rules.validate_config


# --- cli ------------------------------------------------------------------------
def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: validate-config.py <config-path>\n")
        return 2
    try:
        with open(argv[0], "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (argv[0], exc))
        return 2

    try:
        findings, warnings = validate_config(obj)
    except Exception as exc:  # defensive; validate_config should never raise
        print("FINDING: internal validator error: %s" % exc)
        return 1

    for line in warnings:
        print("WARNING: " + line)
    if findings:
        for line in findings:
            print("FINDING: " + line)
        print("\nINVALID: %d finding(s) in %s" % (len(findings), argv[0]))
        return 1
    print("OK: %s valid%s"
          % (argv[0], " (%d warning(s))" % len(warnings) if warnings else ""))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("validate-config.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_validate_config.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
