#!/usr/bin/env python3
"""
Who is driving the panel: the identity `usage_ledger.resolve_author` resolves,
and the cache that keeps a `git config` shell-out off every `/api/state`.

Split out of `_panel_state.py` (U3.1). `_panel_paths`, one layer down, is
its deepest static reach, and it runtime-loads `usage_ledger`, a layer-mate,
which owns the identity's witness: the environment, the files, and their bytes.

THE `--name-only` SLICE LIVES HERE NOW. `tests/test__panel_viewer.py` slices this
file between the two git-config helpers below and fails unless the origin listing
runs with `--name-only`: a plain `--list` hands back every VALUE, and a git config
routinely holds credential helpers and tokens. Neither helper may be renamed
without re-pointing that slice, and `_harness.between()` raises rather than
widening it.

The two markers are deliberately NOT spelled out here. Naming them in this
docstring puts both strings ABOVE the code, so `between()` would take its slice
out of this paragraph -- a few dozen characters with no `--name-only` in them --
and the security case would go red for a reason that has nothing to do with the
flag. Found exactly that way while writing this file.

Stdlib only, Python 3.8 compatible.
"""
import os
import subprocess
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

import _loader                # noqa: E402  (the one path-importlib loader for scripts/)
import _panel_paths as _paths  # noqa: E402  (the shared base)

# Carried by module-level alias so every body below reads exactly as it did in
# `_panel_state`, where these four were siblings rather than imports.
_read_json = _paths._read_json


# --- who is looking at this panel -------------------------------------------------
# {(project, mode): {"watch": [...], "stamp": [...], "env": [...], "viewer": {...}}}.
# One entry per (project, mode): panel-server serves exactly one project, and the
# CLI callers (audit-task through _panel_write) run once and exit — so this is not
# a growth surface worth bounding.
#
# panel-server is a ThreadingHTTPServer, so two requests can be in here at once.
# That is safe under one rule: an entry is REPLACED, never edited in place. A
# reader holds the whole entry it fetched, so a concurrent writer swapping in a new
# one cannot tear the stamp away from the watch list it belongs to. The worst
# outcome is a redundant resolve. Do not "optimize" this by mutating the hit. Same
# rule, same reason, as `_panel_discovery._DISCOVERY_CACHE`.
_VIEWER_CACHE = {}

# The validity token is the BYTES of every watched file, through
# `usage_ledger.file_witness` - the same token `resolve_author`'s own memo keeps,
# so the two caches over one identity answer one question about it. Not
# `_panel_discovery`'s stat token: that cache watches a tree of hundreds of
# files, where reading them would cost the walk it saves, while this one
# watches a handful of small config files. Bytes need no settle window - a
# same-second rewrite changes them - so a fixture or an operator that has just
# written its config still gets its answer kept.
# The non-`GIT_` half of the environment the answer moves with: HOME and
# XDG_CONFIG_HOME decide WHERE the global config is, and USER/USERNAME ARE the
# answer when git has no identity to give. What reads it is
# `usage_ledger.identity_env`, off that module's own tuple; this name stays for
# `_panel_state`, which re-exports it, and a case in `test__panel_viewer.py`
# holds the two tuples equal rather than this comment.
_IDENTITY_ENV = ("HOME", "XDG_CONFIG_HOME", "USER", "USERNAME")


def _ledger():
    """`usage_ledger`, loaded by path: a layer-mate, so never imported."""
    return _loader.load_script("usage_ledger.py", modname="audit_usage_ledger")


def _identity_env():
    """The environment `resolve_author` reads, as sorted `(name, value)` pairs -
    `usage_ledger.identity_env`, the one statement of it: every `GIT_` variable,
    because that family decides which repository git finds and which files it
    opens and can carry config with no file involved (`GIT_CONFIG_COUNT`) -
    matched by PREFIX, so a variable a later git adds is covered - plus
    `_IDENTITY_ENV`. Pinned by value: none of these moves a file, so no file
    token could ever see one change.
    """
    return _ledger().identity_env()


def _git_config_origins(project):
    """The config files git ITSELF says it read for `project` — absolute ones only.

    Asked of git rather than reconstructed from its documented search order, because
    that order is not something this file can hold honestly: the system config lives
    wherever the build put it (on the machine this was written on, inside Xcode.app
    rather than /etc/gitconfig), and `includeIf "gitdir:…"` — the standard way to
    carry a second `user.email` for one tree — pulls in a path nothing here could
    predict. A config file that decides the identity and is not watched is exactly
    the stale answer this cache exists to have stopped having.

    `--name-only` is not a nicety. A plain `--list` also hands back every VALUE, and
    a git config routinely holds credential helpers and tokens; only the paths are
    wanted here, so only the paths are read.

    A RELATIVE origin (git spells the repo config `file:.git/config`) is dropped: it
    is relative to the repository top-level, not to `project`, and
    `_git_config_candidates` already stamps that same file from `project` and every
    ancestor — which is where it sits when `project` is a subdirectory.
    """
    try:
        res = subprocess.run(["git", "-C", str(project), "config", "--list",
                              "--show-origin", "--name-only"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5)
        text = (res.stdout or b"").decode("utf-8", "replace")
    except Exception:
        text = ""
    out = []
    for line in text.splitlines():
        if not line.startswith("file:"):
            continue
        path = line[len("file:"):].split("\t", 1)[0]
        if os.path.isabs(path):
            out.append(path)
    return out


def _git_config_candidates(project):
    """The config files that would decide the answer whether or not they exist
    yet - `usage_ledger.identity_files`, the one list of them.

    The half a token built only from what was READ cannot have, and the half that
    matters: `git config --global user.email` on a machine with no `~/.gitconfig`
    writes a file the previous resolve never opened. `file_witness` records an
    absent path as absent rather than dropping it, so one appearing is a change.

    Walking UP from `project` rather than testing it alone: `resolve_author` runs
    `git -C project`, and git searches upward for the repository, so a `.git` created
    anywhere above `project` is a place a repo-local identity can appear - and a
    `.git` FILE's `gitdir:` pointer, read on that walk, is where a linked
    worktree's own config lives.
    """
    return _ledger().identity_files(project)


def _resolve_viewer(project, mode):
    """One uncached resolve: `({author, mode}, watched_paths)`.

    Split out so the cache has a seam to wrap, and so the watch list is produced BY
    the resolve rather than guessed alongside it — `_panel_discovery._discover_scan`
    's shape, for the reason stated there: a watch list maintained apart from the
    read it describes drifts from it, and a drifted watch list is a cache that goes
    stale in silence.

    `mode: none` is deliberately NOT special-cased into an empty watch list, even
    though `resolve_author` returns before reading anything in that mode: knowing
    that here would be a second implementation of a rule that function owns, and the
    two would eventually disagree. Over-watching costs a resolve; under-watching
    costs a wrong name.

    `cache=False`, because this cache keeps the answer under a token that also
    watches every file git said it read (`_git_config_origins`), which the
    ledger's own memo does not; answering a miss here from that memo would let
    the narrower token decide. The one file that difference covers is a system
    config at a build-specific path holding no identity or include entry, which
    no case here can place, so this argument is defensive and no case tells it
    apart.
    """
    author = None
    try:
        author = _ledger().resolve_author(project, mode, cache=False)
    except Exception:
        author = None
    return ({"author": author, "mode": mode},
            _git_config_origins(project) + _git_config_candidates(project))


def _viewer(project, config):
    """Who is driving the panel: `{author, mode}`.

    Resolved by `usage_ledger.resolve_author` — the SAME function, reading the same
    `usage.authorMode` — rather than by asking git here. The two names have to be
    one string: the Usage tab offers a "my spend" filter that compares this value
    with the `author` column the ledger writes, and a second implementation would
    produce a filter that matches nothing on any project where the two disagreed
    (mode `hash`, say, or a repo-local `user.email`).

    `mode: none` is a real answer, not a failure: it means this project chose not
    to record who spent what, and the panel says so rather than inventing a name.

    WHY THERE IS A CACHE. A resolve shells out to git twice (`resolve_author`'s
    one `git config` read and the origin listing) and `build_state` calls this on
    EVERY `/api/state`, as `audit-task` does on every journal row it writes.

    INVALIDATION — the whole design, so it is stated rather than implied. This
    cache had none: keyed on `(project, mode)` and populated once, it never expired
    and was never invalidated, so `git config user.email` changed against a panel
    that had been up for hours kept answering with the old identity, and the Usage
    tab's "my spend" filter silently selected the wrong rows. A stale answer is
    worse than a slow one here — reflecting what is on disk is this panel's job.

      * The token is the BYTES of every file that can decide the answer
        (`usage_ledger.file_witness`): every ABSOLUTE origin `git config --list
        --show-origin` reports for this project (system, global, XDG, and whatever
        an `include`/`includeIf` pulled in), plus `_git_config_candidates` - the
        repo config of `project` and of each ancestor, the `.git` entries and the
        files behind a `gitdir:` pointer, and the global and system locations that
        do not exist yet. Absent paths are witnessed as absent, so `git config
        --global user.email` on a machine with no `~/.gitconfig` invalidates by
        CREATING one of them — the case a token built only from what was read
        gets wrong.
      * Plus the environment, BY VALUE (`_identity_env`): the `GIT_` family
        decides which repository and which files git opens and can carry the
        config with no file involved, `HOME`/`XDG_CONFIG_HOME` decide where the
        global one lives, and `USER`/`USERNAME` IS the answer when git has no
        identity to give. None of those moves a file, so no file token could see
        them.
      * `mode` stays in the KEY, not the token: it is read out of the project's own
        `.claude/audit.config.json`, which `build_state` re-reads per request, so a
        changed `usage.authorMode` arrives here as a different key already.
      * It is NOT a TTL. A TTL has a window in which the panel knowingly shows the
        wrong person's name, and a window short enough to be honest is short enough
        that the cache buys nothing. Reading a few small config files per call is
        the price of the token being honest, against the git processes a resolve
        starts.
      * A resolve whose files were being written AS it ran is returned but not
        kept: every path known before the resolve is read before AND after it,
        and an answer whose files moved under it would otherwise be kept under
        the edited bytes and serve the pre-edit name until the next edit. A path
        only the resolve's own answer names is read after it, which is the one
        window left. Bytes need no settle window - a same-second rewrite changes
        them - so a config written a moment ago is kept like any other.

    `_panel_discovery.discover`'s docstring cites this cache as the codebase's
    cautionary never-invalidating case. That citation is now historical and wants a
    one-line correction there.
    """
    cfg_mod = _paths.hooks_config()
    mode = str((cfg_mod.usage_cfg(config) or {}).get("authorMode") or "email")
    key = (os.path.realpath(project), mode)
    witness = _ledger().file_witness
    env = _identity_env()
    hit = _VIEWER_CACHE.get(key)
    if hit is not None and hit["env"] == env \
            and witness(hit["watch"]) == hit["stamp"]:
        return dict(hit["viewer"])
    known = sorted(set(_git_config_candidates(project))
                   | set(hit["watch"] if hit is not None else ()))
    before = witness(known)
    viewer, watch = _resolve_viewer(project, mode)
    watch = sorted(set(watch) | set(known))
    stamp = witness(watch)
    if _identity_env() == env and all(stamp[p] == before[p] for p in known):
        _VIEWER_CACHE[key] = {"watch": watch, "stamp": stamp, "env": env,
                              "viewer": viewer}
    else:
        # Not merely "do not store": an entry from an earlier resolve would
        # still be serving its own answer, and this resolve just saw an
        # identity file move.
        _VIEWER_CACHE.pop(key, None)
    # A copy, always — the cached dict outlives the request, and one caller writing
    # to the payload it was handed would corrupt the next caller's answer with
    # nothing raised anywhere.
    return dict(viewer)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
