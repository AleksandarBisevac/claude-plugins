#!/usr/bin/env python3
"""
Who is driving the panel: the identity `usage_ledger.resolve_author` resolves,
and the cache that keeps a `git config` shell-out off every `/api/state`.

Split out of `_panel_state.py` (U3.1). Layer 4: `_panel_paths` and
`_panel_discovery` at 3 are its deepest static reach, and it runtime-loads
`usage_ledger` at 3.

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
import time

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

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _loader                # noqa: E402  (the one path-importlib loader for scripts/)
import _panel_discovery       # noqa: E402  (skills/agents/MCP registry scan)
import _panel_paths as _paths  # noqa: E402  (the shared base, at layer 3)

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

# The validity token and the settle rule are `_panel_discovery`'s, by REFERENCE and
# not by copy: both caches guard the same class of thing — a file a human edits by
# hand, on filesystems whose mtime is often 1-second granular — and two
# implementations of "has anything moved" is two answers to it. See `_stamp` there
# for why size and inode ride along with mtime, and `_SETTLE_SECONDS` for the race
# a same-second write opens.
_stamp = _panel_discovery._stamp
_settled = _panel_discovery._settled

# The non-`GIT_CONFIG*` half of the environment the answer moves with: HOME and
# XDG_CONFIG_HOME decide WHERE the global config is, and USER/USERNAME ARE the
# answer when git has no identity to give.
_IDENTITY_ENV = ("HOME", "XDG_CONFIG_HOME", "USER", "USERNAME")


def _identity_env():
    """The environment `resolve_author` reads, as sorted `(name, value)` pairs.

    Every `GIT_CONFIG*` variable, because that family decides which files git opens
    at all (`GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_NOSYSTEM`) and can
    carry the config with no file involved (`GIT_CONFIG_COUNT` plus
    `GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n`) — matched by PREFIX rather than listed,
    so a variable a later git adds to that family is covered without this file being
    edited. Pinned by value: none of these moves any file's mtime, so no stat could
    ever see one change.
    """
    return sorted((k, v) for k, v in os.environ.items()
                  if k.startswith("GIT_CONFIG") or k in _IDENTITY_ENV)


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
    """The config files that do NOT exist yet but would decide the answer if one
    appeared.

    The half a token built only from what was READ cannot have, and the half that
    matters: `git config --global user.email` on a machine with no `~/.gitconfig`
    writes a file the previous resolve never opened. `_stamp` records an absent path
    as absent rather than dropping it, so one appearing is a mismatch.

    Walking UP from `project` rather than testing it alone: `resolve_author` runs
    `git -C project`, and git searches upward for the repository, so a `.git` created
    anywhere above `project` is a place a repo-local identity can appear.
    """
    home = os.environ.get("HOME") or os.path.expanduser("~")
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    out = [os.environ.get("GIT_CONFIG_GLOBAL") or os.path.join(home, ".gitconfig"),
           os.path.join(xdg, "git", "config"),
           os.environ.get("GIT_CONFIG_SYSTEM") or "/etc/gitconfig"]
    seen = set()
    node = os.path.realpath(project)
    while node not in seen:
        seen.add(node)
        out.append(os.path.join(node, ".git", "config"))
        out.append(os.path.join(node, ".git", "config.worktree"))
        node = os.path.dirname(node)
    return out


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
    """
    author = None
    try:
        ul = _loader.load_script("usage_ledger.py", modname="audit_usage_ledger")
        author = ul.resolve_author(project, mode)
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

    WHY THERE IS A CACHE. `resolve_author` shells out to git (up to two
    `git config --get` runs) and `build_state` calls this on EVERY `/api/state`.

    INVALIDATION — the whole design, so it is stated rather than implied. This
    cache had none: keyed on `(project, mode)` and populated once, it never expired
    and was never invalidated, so `git config user.email` changed against a panel
    that had been up for hours kept answering with the old identity, and the Usage
    tab's "my spend" filter silently selected the wrong rows. A stale answer is
    worse than a slow one here — reflecting what is on disk is this panel's job.

      * The token is a fresh `os.stat` of every file that can decide the answer:
        every ABSOLUTE origin `git config --list --show-origin` reports for this
        project (system, global, XDG, and whatever an `include`/`includeIf` pulled
        in), plus the repo config of `project` and of each ancestor, plus the
        global and system locations that do not exist yet. Absent paths are stamped
        as absent, so `git config --global user.email` on a machine with no
        `~/.gitconfig` invalidates by CREATING one of them — the case a token built
        only from what was read gets wrong.
      * Plus the environment, BY VALUE (`_identity_env`): `GIT_CONFIG_*` decides
        which files git opens and can carry the config with no file involved,
        `HOME`/`XDG_CONFIG_HOME` decide where the global one lives, and
        `USER`/`USERNAME` IS the answer when git has no identity to give. None of
        those moves a file's mtime, so no stat could see them.
      * `mode` stays in the KEY, not the token: it is read out of the project's own
        `.claude/audit.config.json`, which `build_state` re-reads per request, so a
        changed `usage.authorMode` arrives here as a different key already.
      * It is NOT a TTL. A TTL has a window in which the panel knowingly shows the
        wrong person's name, and a window short enough to be honest is short enough
        that the cache buys nothing. Measured on this repo on one developer
        machine: 16 watched paths, revalidated in 0.05 ms, against the 30 ms the
        resolve costs (module load plus up to three `git config` runs). Statting
        more paths than a TTL would is the price of the token being honest, and it
        is still the cheaper half by 600x.
      * A resolve whose files were being written AS it ran is returned but not
        cached (`_settled`): mtime is 1-second granular on plenty of filesystems,
        so an edit landing in the same second as the read can be stamped under an
        mtime the token already holds — after which the pre-edit name would be
        served forever, which is the original bug wearing a smaller window.
        Refusing to cache is the safe direction: the caller still gets the right
        answer, it just costs a resolve.

    `_panel_discovery.discover`'s docstring cites this cache as the codebase's
    cautionary never-invalidating case. That citation is now historical and wants a
    one-line correction there.
    """
    cfg_mod = _paths.hooks_config()
    mode = str((cfg_mod.usage_cfg(config) or {}).get("authorMode") or "email")
    key = (os.path.realpath(project), mode)
    env = _identity_env()
    hit = _VIEWER_CACHE.get(key)
    if hit is not None and hit["env"] == env \
            and _stamp(hit["watch"]) == hit["stamp"]:
        return dict(hit["viewer"])
    started = time.time()
    viewer, watch = _resolve_viewer(project, mode)
    watch = sorted(set(watch))
    stamp = _stamp(watch)
    if _settled(stamp, started):
        _VIEWER_CACHE[key] = {"watch": watch, "stamp": stamp, "env": env,
                              "viewer": viewer}
    else:
        # Not merely "do not store": an entry from an earlier, settled resolve
        # would still be serving its own answer, and this resolve just saw an
        # identity file move.
        _VIEWER_CACHE.pop(key, None)
    # A copy, always — the cached dict outlives the request, and one caller writing
    # to the payload it was handed would corrupt the next caller's answer with
    # nothing raised anywhere.
    return dict(viewer)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_viewer.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__panel_viewer.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
