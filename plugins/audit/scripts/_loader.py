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

RESOLUTION IS BY BASENAME AT ANY DEPTH, AND IT NEVER GUESSES. `script_index()` is
one `{basename: [abspath, ...]}` map built from `_output.script_files()` — the same
recursive walk `install_path()` derives its directory list from, so the index and
`sys.path` can never disagree about what is in the tree. `script_path()` reads it
and RAISES in both directions: nothing with that name, or two files claiming it.
Neither is a case where a plausible answer exists to fall back to, and the second
is the one this design could otherwise get wrong SILENTLY — see `script_path` for
the argument and for its cross-reference to `_deps.layer_violations()`, which
fails the BUILD on the same rule that this fails a RUN on.

WHY hooks/ KEEPS ITS OWN TWO COPIES (`_load_scripts_module` in hooks/_config.py,
and the loader inlined in hooks/remind-tdd.py). Hooks run on EVERY tool call,
launched by a process that may not have this `scripts/` directory on its own
`sys.path` — a hook cannot depend on `scripts/_loader.py` at module import time
without risking the same "not installed" failure it exists to degrade gracefully
from. Hooks stay import-light and self-contained by design (see `_output.py`'s
docstring for the parallel reasoning about why hooks skip `safe_stdio()`); this
module is for `scripts/`-to-`scripts/` (and `scripts/`-to-`hooks/`) loading only.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__loader.py` - see `plugins/audit/tests/_harness.py`. The
eleven that migrated kept byte-identical labels; the block that proves the basename
index (depth, both refusals, and the fixture that puts a real `.py` one directory
down) was added there, because a claim about resolution at depth cannot be tested
from a tree where nothing sits at depth.
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

# The basename index, memoised under a fixed key exactly as `_output`'s two path
# memos are, and for the reason recorded there: only ONE tree is ever cached, so
# nothing a caller passes can poison what the real tree sees. A module memo is not
# the module STATE the house style bans — nothing here writes a value another
# function then reads as input; `_CACHE` above is the same shape and the precedent.
_INDEX = {}

_INDEX_KEY = "default tree"

# Every spelling of a directory separator on this platform, as a tuple so the guard
# in `script_path` reads as one question. `os.altsep` is `/` on Windows and None on
# POSIX (where `os.sep` already IS `/`), so the literal is not redundant: it is what
# makes `usage/core.py` a ValueError on a machine whose `os.sep` is a backslash.
_SEPARATORS = tuple(sorted(set(s for s in ("/", os.sep, os.altsep) if s)))


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


# --- resolving a basename ---------------------------------------------------
def script_index(refresh=False):
    """`{basename: [abspath, ...]}` for every `.py` under `scripts/`, at ANY depth.

    BUILT FROM `_output.script_files()`, not from its own walk, and that is the
    point rather than a convenience: `install_path()` derives the directories it
    puts on `sys.path` from the same walk, so the set of files this can resolve and
    the set of directories `import` can resolve are one fact. Two walks would be two
    answers to "what is in the tree", and the day they disagreed a module would be
    importable and unloadable (or the reverse) with nothing able to say why.

    LAZY, NOT AT IMPORT. `_loader` is imported at module level by ~20 files, most of
    which never resolve a basename at all — a walk at import time would be a cost
    every one of them pays for an answer most of them never ask for. `refresh=True`
    rebuilds it AND the underlying walk, for the one caller that has just written or
    deleted a file.

    A LIST PER NAME, NEVER A PATH. A second file claiming a name has to be VISIBLE;
    a dict of `name -> path` would keep whichever the walk happened to see last and
    there would be nothing left to report. `_deps._module_files()` carries the same
    list-not-entry decision for the same reason, one directory scan earlier.
    """
    if refresh or _INDEX_KEY not in _INDEX:
        index = {}
        for rel, path in _output.script_files(refresh=refresh):
            index.setdefault(os.path.basename(rel), []).append(os.path.abspath(path))
        _INDEX[_INDEX_KEY] = index
    return _INDEX[_INDEX_KEY]


def script_path(basename):
    """The absolute path of `basename` WHEREVER it sits under `scripts/`.

    RAISES, NEVER GUESSES. Three refusals, and there is no fallback join behind any
    of them:

      * NOTHING WITH THAT NAME -> `ImportError` naming the basename AND how many
        files were searched. The count is not decoration: "not found among 41" is a
        typo in a filename, "not found among 0" is a tree that was never walked
        (a consumer's half-installed plugin, a `scripts/` that is not where the
        anchor says it is), and a caller staring at the message has to be able to
        tell those two apart. A retry on `join(SCRIPTS_DIR, basename)` would turn
        both into a `FileNotFoundError` about a path that was never going to exist.
      * TWO FILES WITH THAT NAME -> `ImportError` naming BOTH paths. Picking the one
        the walk saw first is the only failure this design can produce SILENTLY: the
        wrong module, loaded under the right name, behaving plausibly. `_deps
        .layer_violations()` already refuses the same tree at BUILD time (a `.py`
        basename must be unique across `scripts/`, because `import` and this
        function both resolve by basename) — but that lint has never run inside a
        consumer's installed plugin, so restating it here is not a duplicate rule,
        it is the same rule enforced where the load actually happens.
      * A VALUE CARRYING A PATH SEPARATOR -> `ValueError` naming the value. The
        index is keyed by basename, so `usage/core.py` would either miss (and report
        a name nobody spelled) or, worse, be silently reduced to `core.py` and
        resolved out of a different directory than the caller wrote down. Dropping a
        directory the caller spelled is how a caller comes to believe the directory
        mattered.
    """
    text = str(basename)
    if any(sep in text for sep in _SEPARATORS):
        raise ValueError("audit plugin: script_path() takes a BASENAME and %r "
                         "carries a directory separator. The index is keyed by "
                         "basename - the folders under scripts/ are labels, not "
                         "namespaces - so the directory you spelled would be "
                         "dropped rather than honoured" % (text,))
    index = script_index()
    found = index.get(text) or []
    if not found:
        raise ImportError("audit plugin: no script named %r among the %d .py file(s) "
                          "found under %s. (0 searched means the walk found nothing "
                          "at all - a tree that is not there - which is a different "
                          "problem from a misspelled name)"
                          % (text, sum(len(paths) for paths in index.values()),
                             _output.SCRIPTS_DIR))
    if len(found) > 1:
        raise ImportError("audit plugin: the basename %r is claimed by %d files "
                          "(%s) - `import` and _loader both resolve by basename, so "
                          "picking one here would load the WRONG module under the "
                          "RIGHT name. `_deps.layer_violations()` fails the build on "
                          "this same rule; this is it holding at run time"
                          % (text, len(found), ", ".join(found)))
    return found[0]


def load_script(basename, modname=None, cache=True):
    """`load()` of `basename` WHEREVER it sits under `scripts/`.

    BY BASENAME, NOT BY DIRECTORY, and that is the half that lets a file move. The
    folders under `scripts/` are labels, not namespaces: `_output.install_path()`
    puts every one of them on `sys.path`, so `import x` already resolves by
    basename, and this resolves the same way rather than through a
    `join(SCRIPTS_DIR, basename)` that would look one directory too high the day
    somebody files a script under `usage/`.

    The resolution and its two refusals live in `script_path()`; this is `load()`
    of whatever that returns. There is deliberately no fallback on a miss - see
    `script_path` for why a retry against `SCRIPTS_DIR` would turn a typo into a
    plausible-looking error about a path nothing ever put a file at.
    """
    return load(script_path(basename), modname=modname, cache=cache)


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
