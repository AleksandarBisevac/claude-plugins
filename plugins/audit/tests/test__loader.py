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

THE PROBE FIXTURE IS WRITTEN INTO THE REAL `scripts/` TREE, and there is no other
place it could go. `script_index()` deliberately has no `root` seam - it is built
from `_output.script_files()` precisely so the index and `install_path()`'s
directory list can never be pointed at two different trees - so "a basename one
directory down still resolves" is a claim that can only be tested by putting a `.py`
one directory down. Two throwaway directories are created, refreshed into the index,
asserted about, and removed in a `finally` with a final refresh; the last case checks
that the tree and the index are back to what they were, because a fixture that
outlives its case is one the next case silently inherits.

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
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader as M                                # noqa: E402


# --- helpers ------------------------------------------------------------------
def _raises_with(fn, *args):
    """True when `fn(*args)` raises AND the message names the path it tried.

    Two halves on purpose: "it raised" alone would pass on a bare
    `raise ImportError("nope")`, which is the version of this that sends the
    reader hunting instead of to the file."""
    try:
        fn(*args)
    except Exception as exc:                                  # noqa: BLE001
        return args[0] in str(exc)
    return False


def _raised(fn, *args):
    """`(type, message)` from a call expected to raise, or `(None, "")`.

    The TYPE is returned as well as the text because `script_path`'s three
    refusals are two different exception classes on purpose - a value that is not
    a basename is a caller error (`ValueError`) and a name that is not there is a
    resolution failure (`ImportError`) - and a case that only read the message
    would pass while the two were collapsed into one class.
    """
    try:
        fn(*args)
    except Exception as exc:                                  # noqa: BLE001
        return type(exc), str(exc)
    return None, ""


def _probe_dir(root, subdir, basename, body):
    """Write `<root>/<subdir>/<basename>` with `body`, and return its path.

    A throwaway `.py` under a REAL subdirectory of `scripts/` is the only fixture
    that can prove depth-independent resolution, because `script_index()` is built
    off the one real walk and takes no root seam - deliberately, so that the index
    and `install_path()`'s directory list cannot be pointed at two different trees.
    Every caller deletes it in a `finally` and refreshes the index on both sides.
    """
    directory = os.path.join(root, subdir)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    path = os.path.join(directory, basename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


# --- cases --------------------------------------------------------------------
def _cases(check):
    here = M._output.SCRIPTS_DIR

    # 0. LAZY, and this has to be asked FIRST: every case below resolves a
    # basename and would fill the memo. ~20 files import `_loader` at module level
    # and most never resolve anything, so a walk at import time is a cost paid for
    # an answer nobody asked for. Reads trivial and is the only case that fails if
    # the index is ever built beside `_CACHE = {}`.
    check("script_index(): not built at import - the memo is still empty after "
          "`import _loader`, before anything has resolved a name",
          M._INDEX == {})

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

    # 7b. load_script resolves BY BASENAME off the one recursive walk, not by
    # joining the scripts root. The two are the same string today - the tree is
    # flat - so the check is WHICH LIST the answer came from: every basename
    # `_output.script_files()` knows must resolve, and to that walk's own path.
    # Joining the root would keep passing here and would fail silently the day a
    # file moves, which is the whole failure this indirection exists to remove.
    _walked = dict((os.path.basename(_r), _p) for _r, _p in M._output.script_files())
    _resolved = M.load_script("_ui_theme.py", modname="loader_basename_probe",
                              cache=False).__file__
    check("load_script(): the file it loaded is the one the recursive walk names, "
          "not a path built by joining the scripts root: %r" % (_resolved,),
          os.path.realpath(_resolved)
          == os.path.realpath(_walked["_ui_theme.py"]))
    check("load_script(): a basename the walk does not know raises, and the "
          "message NAMES it - 'it raised' alone would pass on a bare "
          "`ImportError('nope')`, which sends the reader hunting instead",
          _raises_with(M.load_script, "no-such-sibling-xyz.py"))
    _ls_type, _ls_msg = _raised(M.load_script, "no-such-sibling-xyz.py")
    check("load_script(): ...and it is `script_path()`'s error, carrying the search "
          "COUNT - NOT `load()`'s 'cannot load module from <path>'. This is the "
          "case that goes red if the old join(SCRIPTS_DIR, basename) fallback comes "
          "back, since that also raises and also names the file: %r"
          % (_ls_msg[:110],),
          _ls_type is ImportError and "no script named" in _ls_msg
          and "cannot load module from" not in _ls_msg)

    # 7c. load_hooks_config takes the hooks directory from the one anchor. On a
    # flat tree that is the same string the old `join(dirname(_HERE), "hooks")`
    # produced, and this is the case that says so rather than assuming it.
    check("load_hooks_config(): _output.HOOKS_DIR is what the old "
          "`join(dirname(dirname(abspath(__file__))), 'hooks')` produced",
          M._output.HOOKS_DIR
          == os.path.join(os.path.dirname(os.path.dirname(
              os.path.abspath(M.__file__))), "hooks")
          and os.path.isfile(os.path.join(M._output.HOOKS_DIR, "_config.py")))

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
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # --- 9. the basename index ------------------------------------------------
    _walk = M._output.script_files()
    _index = M.script_index()
    check("script_index(): one key per basename the ONE recursive walk found, and "
          "no key the walk does not know - the index and install_path()'s "
          "directory list are built from the same `script_files()` so they cannot "
          "disagree about what is in the tree",
          set(_index) == set(os.path.basename(_r) for _r, _p in _walk))
    check("script_index(): every value is a LIST of absolute paths, so a second "
          "file claiming a name is VISIBLE rather than overwriting the first",
          _index
          and all(isinstance(_v, list) and _v
                  and all(os.path.isabs(_p) for _p in _v)
                  for _v in _index.values()))
    check("script_index(): the paths total the walk's own file count (%d), so a "
          "name is not quietly dropped on the way into the map" % (len(_walk),),
          sum(len(_v) for _v in _index.values()) == len(_walk))
    check("script_index(): memoised - a second call returns the identical dict "
          "rather than re-walking the tree",
          M.script_index() is _index)

    # --- 10. script_path: resolves, or refuses. Never guesses. ----------------
    _walked = dict((os.path.basename(_r), _p) for _r, _p in _walk)
    check("script_path(): a known basename resolves to the walk's own path",
          os.path.realpath(M.script_path("_ui_theme.py"))
          == os.path.realpath(_walked["_ui_theme.py"]))

    _miss_type, _miss_msg = _raised(M.script_path, "no-such-sibling-xyz.py")
    check("script_path(): a name that is not there raises ImportError NAMING the "
          "basename - a miss is not an invitation to build a path and try it: %r"
          % (_miss_msg[:110],),
          _miss_type is ImportError and "no-such-sibling-xyz.py" in _miss_msg)
    check("script_path(): ...and the message carries HOW MANY files were searched "
          "(%d), which is what tells 'you spelled it wrong' apart from 'the tree "
          "was never walked'. 0 and 41 are different problems and a message "
          "without the number cannot say which one this is" % (len(_walk),),
          ("%d .py file(s)" % len(_walk)) in _miss_msg and len(_walk) > 0)

    _sep_type, _sep_msg = _raised(M.script_path, "usage/core.py")
    check("script_path(): a value carrying a path separator is a ValueError naming "
          "the VALUE - not an ImportError about `core.py`, which is a name the "
          "caller never spelled: %r" % (_sep_msg[:110],),
          _sep_type is ValueError and "usage/core.py" in _sep_msg)
    check("script_path(): ...and it is refused BEFORE the lookup, so the directory "
          "is never silently dropped. This is the case that fails if the guard "
          "becomes an `os.path.basename()` call: `usage/_ui_theme.py` names a real "
          "file under a directory that does not exist, and must still raise",
          _raised(M.script_path, "usage/_ui_theme.py")[0] is ValueError)

    # --- 11. depth and collision, on a real subdirectory of scripts/ ----------
    # The mechanism cannot be proved on a flat tree: every "at any depth" claim
    # here is vacuously true until a file actually sits one directory down. The
    # fixture is written into the REAL scripts/ tree because `script_index()`
    # takes no root seam by design, and is removed in `finally` with the index
    # refreshed on both sides so no later case in this process sees it.
    _probe_a = "_loader_probe_a"
    _probe_b = "_loader_probe_b"
    _probe_name = "loader_depth_probe.py"
    try:
        _pa = _probe_dir(here, _probe_a, _probe_name, "PROBE = 'a'\n")
        M.script_index(refresh=True)
        check("script_path(): a .py one directory down resolves by BARE BASENAME - "
              "the folders under scripts/ are labels, not namespaces: %r"
              % (os.path.relpath(M.script_path(_probe_name), here),),
              os.path.realpath(M.script_path(_probe_name)) == os.path.realpath(_pa))
        _probe_mod = M.load_script(_probe_name, modname="loader_depth_probe",
                                   cache=False)
        check("load_script(): ...and it LOADS that file, so the whole path from a "
              "bare basename to a module object is depth-independent",
              getattr(_probe_mod, "PROBE", None) == "a"
              and os.path.realpath(_probe_mod.__file__) == os.path.realpath(_pa))

        _pb = _probe_dir(here, _probe_b, _probe_name, "PROBE = 'b'\n")
        M.script_index(refresh=True)
        _coll_type, _coll_msg = _raised(M.script_path, _probe_name)
        check("script_path(): two files claiming one basename is an ImportError, "
              "not a coin flip. Picking whichever the walk saw first is the ONE "
              "failure this design can produce silently - the wrong module under "
              "the right name: %r" % (_coll_msg[:90],),
              _coll_type is ImportError and "claimed by 2 files" in _coll_msg)
        check("script_path(): ...and the message names BOTH paths, because "
              "'a collision' the reader cannot locate is a message that only says "
              "a problem exists",
              _pa in _coll_msg and _pb in _coll_msg)
        check("load_script(): a collision refuses the LOAD too - the refusal lives "
              "in the resolver, so it cannot be routed around by the loader",
              _raised(M.load_script, _probe_name)[0] is ImportError)
    finally:
        for _d in (_probe_a, _probe_b):
            shutil.rmtree(os.path.join(here, _d), ignore_errors=True)
        M.script_index(refresh=True)

    check("the probe tree is gone and the index is back to what the real tree "
          "says - a fixture that outlives its case is a fixture the next case "
          "silently inherits",
          _probe_name not in M.script_index()
          and not os.path.isdir(os.path.join(here, _probe_a))
          and not os.path.isdir(os.path.join(here, _probe_b))
          and set(M.script_index()) == set(_index))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__loader.py --selftest\n")
    raise SystemExit(2)
