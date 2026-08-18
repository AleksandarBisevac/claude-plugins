#!/usr/bin/env python3
"""
The cases for `validate-config.py` - the command, which is all that file is now.

Hyphenated, so the file name substitutes underscores and the module comes through
`_loader.load_script`; see `test_migrate_manifest.py` for that rule. `M` is the
module under test.

WHY THIS SUITE IS SHORT. It was 84 cases, when the rules lived in the same file.
They do not: `_panel_settings` (L2), `_panel_state` (L5) and `audit-doctor` (L7)
all needed them and all three reached this entry point with
`_loader.load_script("validate-config.py")` — three of the seventeen entries in
`_deps.KNOWN_LAYER_DEBT`, one of them from layer 2, the deepest inversion the
table had. The rules moved to `_config_rules.py`, their cases moved to
`test__config_rules.py`, and what is left here is the command's own contract: the
three-way exit code, and that it is a front end rather than a second validator.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _config_rules                               # noqa: E402

M = _loader.load_script("validate-config.py", modname="validate_config")


# --- cases --------------------------------------------------------------------
def _cases(check):
    # exit-code contract
    check("main usage error -> 2", M.main([]) == 2)
    check("main missing file -> 2", M.main(["/no/such/file.json"]) == 2)

    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        check("cc0 an empty config is valid and exits 0", M.main([path]) == 0)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"planGate": "sideways"}, fh)
        check("cc1 a findings config exits 1 - the half a `validate_config()` "
              "call alone would not catch, since a main() that printed the "
              "findings and returned 0 would still look right",
              M.main([path]) == 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("cc2 an unparseable file exits 2, not 1: it is a usage failure, "
              "not an invalid config", M.main([path]) == 2)
    finally:
        if os.path.exists(path):
            os.unlink(path)

    # --- the extraction contract ------------------------------------------------
    check("cc3 the command validates through `_config_rules` and not through a "
          "second copy - `M.validate_config` IS that module's own function "
          "object, so a re-implementation here fails by identity rather than by "
          "drifting: %r" % (getattr(M.validate_config, "__module__", None),),
          M.validate_config is _config_rules.validate_config)
    # The other direction: a facade that re-exported the key sets and enums would
    # put the rules' whole surface back on the command, which is what the layer
    # split was undoing. Reads vacuous next to cc3, and is the only case that
    # fails if the aliases creep back.
    _leaked = sorted(n for n in ("KNOWN_ROOT", "KNOWN_POLICY", "POLICY_KINDS",
                                 "KNOWN_POLICY_KIND", "PLAN_GATE_MODES",
                                 "AUTHOR_MODES", "IN_PROGRESS_POLICY",
                                 "STRICT_MANIFEST_STATE")
                     if hasattr(M, n))
    check("cc4 ...and it re-exports NONE of the rules' key sets or enums - the "
          "command's surface is `main` plus the one function it calls: %r"
          % (_leaked,),
          _leaked == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_validate_config.py --selftest\n")
    raise SystemExit(2)
