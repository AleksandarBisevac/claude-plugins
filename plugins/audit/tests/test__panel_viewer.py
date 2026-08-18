#!/usr/bin/env python3
"""
The cases for `_panel_viewer.py` - who is driving the panel, and the identity
cache, in BOTH directions.

THE `--name-only` CASE IS A SECURITY CLAIM AND IT LIVES HERE NOW.
`_git_config_origins` must run `git config --list --name-only`: a plain
`--list` hands back every VALUE, and a git config routinely holds credential
helpers and tokens. The case asserts the flag appears between `def
_git_config_origins` and `def _git_config_candidates`, through
`_harness.between()`, which RAISES on either marker rather than silently
widening the slice to the rest of the file - where `--name-only` appears
anyway and the case would pass while guarding nothing.

Moved out of `test__panel_state.py` at U3.1, with the code it covers. `M` is the
module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as the module imports it)
import _panel_paths as _paths                     # noqa: E402  (the shared base)
import _panel_viewer as M           # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import pathlib                                 # noqa: F401  (used by moved cases)
    import shutil
    import tempfile

    _src = _harness.module_source(M)

    def _atomic_write_json(path, obj):
        """The selftest's own fixture writer -- straight through `_manifest_io`,
        the implementation panel-server's `_atomic_write_json` delegates to."""
        _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)

    tmp = tempfile.mkdtemp(prefix="panel-viewer-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
    _atomic_write_json(_paths._config_path(proj), {"trivialLineThreshold": 40})
    mpath = _paths._manifest_path(proj, _paths.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T", "status": "pending"},
                              {"id": "P1.2", "title": "T2", "status": "pending"}]}]})

    # --- who is looking: the identity cache, in BOTH directions -----------------
    # A stale answer here is worse than a slow one: the Usage tab's "my spend"
    # filter compares this name against the ledger's `author` column, so an
    # identity that went out of date silently selects the wrong rows. Neither
    # direction is taken on trust. Every case COUNTS resolves rather than timing
    # anything — a wall-clock assertion is flaky on a loaded machine and cannot say
    # WHICH work was skipped.
    #
    # The fixture owns its whole git identity: GIT_CONFIG_NOSYSTEM plus a
    # GIT_CONFIG_GLOBAL under the temp dir, and USER/USERNAME both set (Windows
    # reads the second), so nothing about this machine's real config can decide a
    # case here — the `no-silent-pass` ambient-state rule, on the two CI platforms.
    _vtmp = tempfile.mkdtemp(prefix="state-viewer-")
    _venv_keys = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
                  "XDG_CONFIG_HOME", "USER", "USERNAME")
    _venv_saved = {k: os.environ.get(k) for k in _venv_keys}
    _real_resolve_viewer = M._resolve_viewer
    _resolves = [0]

    def _counting_resolve(project, mode):
        _resolves[0] += 1
        return _real_resolve_viewer(project, mode)

    def _vwrite(path, email, settled=True):
        """Write a git config carrying one identity.

        Backdated by default because the settle guard is doing its job: a file
        written this millisecond is deliberately NOT cached, so aging it is the
        honest way to reach the cached path. `settled=False` is how the guard's
        own case reaches the other branch."""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[user]\n\temail = %s\n" % email)
        if settled:
            _when = time.time() - 5
            os.utime(path, (_when, _when))

    try:
        M._resolve_viewer = _counting_resolve
        _vproj = os.path.join(_vtmp, "proj")
        os.makedirs(_vproj)
        _vglobal = os.path.join(_vtmp, "gitconfig-global")
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        os.environ["GIT_CONFIG_GLOBAL"] = _vglobal
        os.environ["XDG_CONFIG_HOME"] = os.path.join(_vtmp, "xdg")
        os.environ["USER"] = os.environ["USERNAME"] = "fixture-user"
        os.environ.pop("GIT_CONFIG_SYSTEM", None)

        _vwrite(_vglobal, "alice@example.com")
        _resolves[0] = 0
        _v1 = M._viewer(_vproj, {})
        check("viewer: the first call really does resolve — the baseline the skip "
              "case below is measured against, and the proof the counter works",
              _v1 == {"author": "alice@example.com", "mode": "email"}
              and _resolves[0] == 1)
        _resolves[0] = 0
        _v2 = M._viewer(_vproj, {})
        # THE SECOND-DIRECTION CASE. It looks vacuous and it is the only one that
        # fails if invalidation becomes unconditional (a token that never compares
        # equal, a bare recompute): the answer would still be right, and the cache
        # would have bought nothing.
        check("viewer: with no identity file and no environment moved, the second "
              "call resolves NOTHING and hands back the same answer",
              _resolves[0] == 0 and _v2 == _v1)

        # THE BUG ITSELF (F-P): `git config user.email` edited under a running
        # panel. The old cache was keyed on (project, mode) and populated once, so
        # this returned alice forever.
        _vwrite(_vglobal, "bob@example.com")
        _resolves[0] = 0
        _v3 = M._viewer(_vproj, {})
        check("viewer: user.email changed IN PLACE under a running process is "
              "picked up — the whole bug: no directory listing changed, so only "
              "stamping the config FILE can catch this",
              _v3["author"] == "bob@example.com" and _resolves[0] == 1)

        # The environment half. With no git identity anywhere, resolve_author's
        # answer IS $USER — a value no stat of any file could ever see move.
        _vlater = os.path.join(_vtmp, "gitconfig-later")
        os.environ["GIT_CONFIG_GLOBAL"] = _vlater          # nothing there yet
        M._viewer(_vproj, {})                                # warm on the new env
        _resolves[0] = 0
        _v4 = M._viewer(_vproj, {})
        check("viewer: a project whose git knows no identity falls back to the "
              "environment, and that answer caches too",
              _v4["author"] == "fixture-user" and _resolves[0] == 0)
        os.environ["USER"] = os.environ["USERNAME"] = "someone-else"
        _resolves[0] = 0
        _v5 = M._viewer(_vproj, {})
        check("viewer: the environment is pinned BY VALUE - USER changed moves no "
              "file's mtime, so a stat-only token would have served the old name",
              _v5["author"] == "someone-else" and _resolves[0] == 1)

        # THE TTL-KILLER. The winning config file did not EXIST when the answer was
        # resolved, so a token covering only what was read (or a plain TTL) cannot
        # know it appeared.
        M._viewer(_vproj, {})                                # re-warm, settled
        _resolves[0] = 0
        _vwrite(_vlater, "carol@example.com")
        _v6 = M._viewer(_vproj, {})
        check("viewer: a config file that did not EXIST at resolve time "
              "invalidates when it appears — absent paths are stamped, never "
              "dropped from the token",
              _v6["author"] == "carol@example.com" and _resolves[0] == 1)

        # The settle guard, both ways. A case that only ever saw it accept would be
        # asserting nothing.
        _vfresh = os.path.join(_vtmp, "gitconfig-fresh")
        os.environ["GIT_CONFIG_GLOBAL"] = _vfresh
        _vwrite(_vfresh, "dave@example.com", settled=False)
        M._viewer(_vproj, {})
        _resolves[0] = 0
        _v7 = M._viewer(_vproj, {})
        check("viewer: an identity file written a moment ago is NOT cached — a "
              "1-second-granular mtime cannot prove the resolve saw the final "
              "bytes, and serving the pre-edit name forever is the original bug",
              _v7["author"] == "dave@example.com" and _resolves[0] == 1)
        _vsettle = time.time() - 5
        os.utime(_vfresh, (_vsettle, _vsettle))
        M._viewer(_vproj, {})                                # re-warm, now settled
        _resolves[0] = 0
        _v8 = M._viewer(_vproj, {})
        check("viewer: ...and the same file, once it has settled, IS cached",
              _v8["author"] == "dave@example.com" and _resolves[0] == 0)

        _vmine = M._viewer(_vproj, {})
        _vmine["author"] = "clobbered"
        check("viewer: each caller gets its own copy — writing to a returned "
              "viewer cannot poison the next caller's answer",
              M._viewer(_vproj, {})["author"] == "dave@example.com")

        # The watch list is what the RESOLVE read, plus what it would have read.
        # A file consulted but not stamped is precisely how a cache goes stale in
        # silence, so the two halves are checked against each other rather than
        # trusted from the docstring.
        _vwatch = _real_resolve_viewer(_vproj, "email")[1]
        check("viewer: the winning config file is in the watch list, and so is the "
              "repo config of the project and of its parent — the places a "
              "repo-local user.email can appear when the panel is opened on a "
              "subdirectory",
              _vfresh in _vwatch
              and os.path.join(os.path.realpath(_vproj), ".git", "config")
              in _vwatch
              and os.path.join(os.path.realpath(_vtmp), ".git", "config")
              in _vwatch)
        check("viewer: the origin list carries PATHS only - `--name-only`, because "
              "a plain --list also hands back every value and a git config "
              "routinely holds credential helpers and tokens",
              "--name-only" in _harness.between(
                  _src, "def _git_config_origins", "def _git_config_candidates"))
    finally:
        M._resolve_viewer = _real_resolve_viewer
        for _k, _v in _venv_saved.items():
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v
        shutil.rmtree(_vtmp, ignore_errors=True)

    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_viewer.py --selftest\n")
    raise SystemExit(2)
