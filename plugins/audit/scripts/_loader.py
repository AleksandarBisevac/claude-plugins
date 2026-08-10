#!/usr/bin/env python3
"""
The one way scripts/ loads a sibling script as a library — stdlib only.

Before this module, `scripts/` carried roughly fourteen hand-rolled copies of the
same three lines (`importlib.util.spec_from_file_location` + `module_from_spec` +
`exec_module`), and they had already drifted into FIVE different caching policies:
a per-caller global memo dict (panel-server.py's `_cores`), no cache at all —
reload every call (audit-status.py's `_load_validator`, `_load_usage_fmt`),
swallow-on-failure with no cache (audit-status.py's `usage_summary`), a
selftest-only reload with a name chosen to avoid colliding with a real import
(_help.py's `_config_mod` / `_journal_mod`), and a bare-except "return None on
any failure" variant (hooks/_config.py's `_load_scripts_module`). Each copy was
a fresh chance to get the caching policy, the module name or the failure mode
subtly wrong, and nothing could see the fourteen disagree because each only
ever checked itself.

ONE caching policy: `load(path, cache=True)` keeps a single process-wide memo
keyed by `os.path.realpath(path)` — so two different SPELLINGS of the same file
(`./x.py` vs `scripts/x.py`) hit the same cache entry, and identity (`is`) holds
across repeat calls. Pass `cache=False` for the rare caller that wants a FRESH
module object (e.g. a selftest reloading a target under mutation) without
disturbing the shared cache other callers rely on.

`sys.modules` is NEVER touched. A script loaded this way keeps a name that is
deliberately namespaced and NOT `import`-able by a plain `import <name>`
elsewhere — polluting the real module table would let an unrelated `import`
statement silently pick up a hyphenated script loaded as a library (or a stale
cached copy from a different path), which is exactly the kind of cross-talk a
single loader must not introduce while removing fourteen ad-hoc ones.

Failures are NOT swallowed here. A missing file or a module that raises during
`exec_module` propagates to the caller. Callers that want a soft-fail (like
`hooks/_config.py`'s "the feature this module owns is not installed") catch it
themselves at the call site — that decision belongs to the caller, not to a
shared loader silently deciding for all of them.

WHY hooks/ KEEPS ITS OWN TWO COPIES (`_load_scripts_module` in hooks/_config.py,
and the loader inlined in hooks/remind-tdd.py). Hooks run on EVERY tool call,
launched by a process that may not have this `scripts/` directory on its own
`sys.path` — a hook cannot depend on `scripts/_loader.py` at module import time
without risking the same "not installed" failure it exists to degrade gracefully
from. Hooks stay import-light and self-contained by design (see `_output.py`'s
docstring for the parallel reasoning about why hooks skip `safe_stdio()`); this
module is for `scripts/`-to-`scripts/` (and `scripts/`-to-`hooks/`) loading only.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

_CACHE = {}


def _default_modname(path):
    """A name derived from the file's basename, sanitized so it cannot collide
    with a real importable module: dots and hyphens (illegal in a plain
    `import` statement) become underscores, and a leading digit gets a prefix."""
    base = os.path.basename(str(path))
    stem = base[:-3] if base.endswith(".py") else base
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in stem)
    if not safe:
        safe = "module"
    if safe[0].isdigit():
        safe = "_" + safe
    return "audit_loaded_" + safe


def load(path, modname=None, cache=True):
    """Load the Python file at `path` as a module object and return it.

    The ONE caching policy: keyed by `os.path.realpath(path)`, so two different
    spellings of the same file share one cache entry. `cache=True` (default)
    returns the SAME object on every call for the same path (`is` holds).
    `cache=False` builds and returns a FRESH module object every time, and does
    not read or write the shared cache.

    `sys.modules` is never registered — see the module docstring.

    Raises on a missing file or a module that raises during `exec_module`; a
    file that fails to exec is never cached (the next call gets a clean retry).
    """
    real = os.path.realpath(str(path))
    if cache and real in _CACHE:
        return _CACHE[real]

    name = modname or _default_modname(real)
    spec = importlib.util.spec_from_file_location(name, real)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load module from %r" % (real,))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # may raise; nothing cached if it does

    if cache:
        _CACHE[real] = mod
    return mod


def load_script(basename, modname=None, cache=True):
    """`load()` of `basename` in this same directory (the scripts dir)."""
    return load(os.path.join(_HERE, basename), modname=modname, cache=cache)


def load_hooks_config(modname=None, cache=True):
    """`load()` of `../hooks/_config.py`, relative to this file."""
    path = os.path.join(os.path.dirname(_HERE), "hooks", "_config.py")
    return load(path, modname=modname or "audit_loaded_hooks_config", cache=cache)


# --- selftest ---------------------------------------------------------------
def _selftest():
    import tempfile

    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    # 1. loading a real sibling returns a module carrying a known attribute.
    mod = load(os.path.join(_HERE, "_ui_theme.py"), cache=False)
    check("load(): sibling module carries a known attribute (TOKEN_CSS)",
          hasattr(mod, "TOKEN_CSS"))

    # 2. cache=True: two calls return the SAME object (identity).
    a = load(os.path.join(_HERE, "_ui_theme.py"), modname="loader_selftest_cache")
    b = load(os.path.join(_HERE, "_ui_theme.py"), modname="loader_selftest_cache")
    check("cache=True: repeat load() returns the identical object", a is b)

    # 3. cache=False: a fresh object every call, and the cached copy untouched.
    c = load(os.path.join(_HERE, "_ui_theme.py"), modname="loader_selftest_cache",
             cache=False)
    check("cache=False: returns a DIFFERENT object than the cached one", c is not a)
    d = load(os.path.join(_HERE, "_ui_theme.py"), modname="loader_selftest_cache")
    check("cache=False call did not disturb the shared cache entry", d is a)

    # 4. two different paths to the same file hit the same cache entry.
    dotted = os.path.join(_HERE, ".", os.path.basename(__file__))
    plain = os.path.join(_HERE, os.path.basename(__file__))
    e = load(dotted, modname="loader_selftest_realpath")
    f = load(plain, modname="loader_selftest_realpath")
    check("realpath key: './x.py' and 'x.py' share one cache entry", e is f)

    # 5. missing file raises.
    raised_type = None
    try:
        load(os.path.join(_HERE, "does-not-exist-selftest.py"), cache=False)
    except Exception as exc:                              # noqa: BLE001
        raised_type = type(exc)
    check("missing file raises (got %r)" % (raised_type,),
          raised_type is not None)

    # 6. sys.modules is never polluted.
    before = set(sys.modules.keys())
    load(os.path.join(_HERE, "_ui_theme.py"), modname="loader_selftest_sysmod",
         cache=False)
    after = set(sys.modules.keys())
    check("sys.modules gains no new entries", after == before)

    # 7. load_script + load_hooks_config resolve correctly.
    ls = load_script("_ui_theme.py", modname="loader_selftest_script")
    check("load_script(): resolves a sibling in the scripts dir",
          hasattr(ls, "TOKEN_CSS"))
    hc = load_hooks_config()
    check("load_hooks_config(): resolves ../hooks/_config.py (has DEFAULTS)",
          hasattr(hc, "DEFAULTS"))

    # 8. a file that raises at exec time propagates, and does not poison the cache.
    tmp_dir = tempfile.mkdtemp(prefix="loader-selftest-")
    bad_path = os.path.join(tmp_dir, "bad_module.py")
    with open(bad_path, "w", encoding="utf-8") as fh:
        fh.write("raise RuntimeError('boom')\n")
    exec_raised = False
    try:
        load(bad_path, modname="loader_selftest_bad")
    except Exception:                                      # noqa: BLE001
        exec_raised = True
    check("exec-time failure propagates rather than being swallowed",
          exec_raised)
    check("exec-time failure does not poison the cache",
          os.path.realpath(bad_path) not in _CACHE)

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _loader.py --selftest\n")
    raise SystemExit(2)
