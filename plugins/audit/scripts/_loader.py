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

This module carries no `--selftest` of its own any more; its 11 cases live in
`plugins/audit/tests/test__loader.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
import importlib.util
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

_CACHE = {}


# --- module loading ---------------------------------------------------------
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
    """`load()` of `basename` WHEREVER it sits under `scripts/`.

    BY BASENAME, NOT BY DIRECTORY, and that is the half that lets a file move. The
    folders under `scripts/` are labels, not namespaces: `_output.install_path()`
    puts every one of them on `sys.path`, so `import x` already resolves by
    basename, and this resolves the same way rather than through a
    `join(SCRIPTS_DIR, basename)` that would look one directory too high the day
    somebody files a script under `usage/`. The answer is unique because
    `_deps.layer_violations()` fails a tree in which two `.py` share a basename.

    A basename that matches nothing falls through to `SCRIPTS_DIR`, so the error is
    `load()`'s own "cannot load module from <path>" — which names the path that was
    tried. Raising something different here would replace a message that locates
    the problem with one that only says it exists.
    """
    for rel, path in _output.script_files():
        if os.path.basename(rel) == basename:
            return load(path, modname=modname, cache=cache)
    return load(os.path.join(_output.SCRIPTS_DIR, basename),
                modname=modname, cache=cache)


def load_hooks_config(modname=None, cache=True):
    """`load()` of `hooks/_config.py`, off the one anchor rather than off `..`."""
    path = os.path.join(_output.HOOKS_DIR, "_config.py")
    return load(path, modname=modname or "audit_loaded_hooks_config", cache=cache)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_loader.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__loader.py - run that file instead.")
        raise SystemExit(0)
    sys.stderr.write("usage: _loader.py --selftest\n")
    raise SystemExit(2)
