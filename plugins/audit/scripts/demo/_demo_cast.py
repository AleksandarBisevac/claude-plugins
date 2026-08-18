#!/usr/bin/env python3
"""
The people the demo fixtures are attributed to — one tuple, because two generators must agree.

`gen-demo-usage.py` stamps every synthetic ledger row with one of these authors.
`gen-demo-manifest.py` hands the same identities out as `meta.areas[*].owner`. The
demo exists to show the surfaces working, and one of the things it shows is
`/audit:doctor`'s owner-versus-ledger join: an area owner the ledger has never
seen is exactly the mismatch that check reports. If the two files disagreed about
who these people are, the shipped demo would render that warning on itself.

So the tuple is a contract between two modules, not a private constant — and
until now the way `gen-demo-manifest` honoured it was
`_loader.load_script("gen-demo-usage.py").DEFAULT_AUTHORS`: one entry point
loading another to read one name off it, the last of the seventeen edges
`_deps.KNOWN_LAYER_DEBT` recorded. A fact two modules share belongs below both of
them, which is layer 1 and is this file. It is a small module for a small fact,
and that is the right size: the alternative was not a bigger module, it was a
second copy of three email addresses that nothing would ever compare.

Fictional, and `.example` on purpose: RFC 2606 reserves that TLD precisely so a
fixture can carry an address that can never route to a real person.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__demo_cast.py` — see `plugins/audit/tests/_harness.py`.
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

DEFAULT_AUTHORS = ("alex@acme.example", "sara@acme.example", "milos@acme.example")


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_demo_cast.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__demo_cast.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
