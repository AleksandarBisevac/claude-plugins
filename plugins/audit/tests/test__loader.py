#!/usr/bin/env python3
"""
The cases for `scripts/_loader.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

THIS IS THE MODULE THE HARNESS ITSELF LEANS ON: `_harness` puts `scripts/` on the
path, and the two hyphenated-script test files reach their subject through
`M.load` / `M.load_script`. So a break here shows up as every other test file
failing to import, not as this file going red - which is why the whole sweep, not
just this suite, is the check that matters after touching it.

ONE EXPRESSION HAD TO CHANGE, because it named the file it lives in. Case 4 loads
one file under two spellings (`x.py` and `./x.py`) to prove both hit one cache
entry, and inline it wrote `os.path.basename(__file__)` - which WAS `_loader.py`.
Carried over literally, that would spell `scripts/test__loader.py`, a file that
does not exist, and the case would fail on a missing file instead of testing the
cache key. It reads `os.path.basename(M.__file__)` here: still derived from the
module rather than hard-coded, and still the same file it always loaded.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader as M                                # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    here = M._HERE

    # 1. loading a real sibling returns a module carrying a known attribute.
    mod = M.load(os.path.join(here, "_ui_theme.py"), cache=False)
    check("load(): sibling module carries a known attribute (TOKEN_CSS)",
          hasattr(mod, "TOKEN_CSS"))

    # 2. cache=True: two calls return the SAME object (identity).
    a = M.load(os.path.join(here, "_ui_theme.py"), modname="loader_selftest_cache")
    b = M.load(os.path.join(here, "_ui_theme.py"), modname="loader_selftest_cache")
    check("cache=True: repeat load() returns the identical object", a is b)

    # 3. cache=False: a fresh object every call, and the cached copy untouched.
    c = M.load(os.path.join(here, "_ui_theme.py"), modname="loader_selftest_cache",
               cache=False)
    check("cache=False: returns a DIFFERENT object than the cached one", c is not a)
    d = M.load(os.path.join(here, "_ui_theme.py"), modname="loader_selftest_cache")
    check("cache=False call did not disturb the shared cache entry", d is a)

    # 4. two different paths to the same file hit the same cache entry.
    dotted = os.path.join(here, ".", os.path.basename(M.__file__))
    plain = os.path.join(here, os.path.basename(M.__file__))
    e = M.load(dotted, modname="loader_selftest_realpath")
    f = M.load(plain, modname="loader_selftest_realpath")
    check("realpath key: './x.py' and 'x.py' share one cache entry", e is f)

    # 5. missing file raises.
    raised_type = None
    try:
        M.load(os.path.join(here, "does-not-exist-selftest.py"), cache=False)
    except Exception as exc:                              # noqa: BLE001
        raised_type = type(exc)
    check("missing file raises (got %r)" % (raised_type,),
          raised_type is not None)

    # 6. sys.modules is never polluted.
    before = set(sys.modules.keys())
    M.load(os.path.join(here, "_ui_theme.py"), modname="loader_selftest_sysmod",
           cache=False)
    after = set(sys.modules.keys())
    check("sys.modules gains no new entries", after == before)

    # 7. load_script + load_hooks_config resolve correctly.
    ls = M.load_script("_ui_theme.py", modname="loader_selftest_script")
    check("load_script(): resolves a sibling in the scripts dir",
          hasattr(ls, "TOKEN_CSS"))
    hc = M.load_hooks_config()
    check("load_hooks_config(): resolves ../hooks/_config.py (has DEFAULTS)",
          hasattr(hc, "DEFAULTS"))

    # 8. a file that raises at exec time propagates, and does not poison the cache.
    tmp_dir = tempfile.mkdtemp(prefix="loader-selftest-")
    bad_path = os.path.join(tmp_dir, "bad_module.py")
    with open(bad_path, "w", encoding="utf-8") as fh:
        fh.write("raise RuntimeError('boom')\n")
    exec_raised = False
    try:
        M.load(bad_path, modname="loader_selftest_bad")
    except Exception:                                      # noqa: BLE001
        exec_raised = True
    check("exec-time failure propagates rather than being swallowed",
          exec_raised)
    check("exec-time failure does not poison the cache",
          os.path.realpath(bad_path) not in M._CACHE)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__loader.py --selftest\n")
    raise SystemExit(2)
