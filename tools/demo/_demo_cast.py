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
them, which is the layer just above the anchor and is this file. It is a small module for a small fact,
and that is the right size: the alternative was not a bigger module, it was a
second copy of three email addresses that nothing would ever compare.

Fictional, and `.example` on purpose: RFC 2606 reserves that TLD precisely so a
fixture can carry an address that can never route to a real person.

This module carries no `--selftest` of its own; its cases live in
`tests/test__demo_cast.py` — see `tests/_harness.py`.
"""
import os
import sys

# The path bootstrap, adapted: this file lives in tools/demo/, outside scripts/, so
# the anchor is found by the known layout rather than by walking up for `_output.py`
# (the same shape as `tools/where.py`). `tools/demo/` goes on the path too, because
# the three demo files reach each other by bare basename.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(_here))
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
for _p in (_scripts, _here):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

DEFAULT_AUTHORS = ("alex@acme.example", "sara@acme.example", "milos@acme.example")


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
