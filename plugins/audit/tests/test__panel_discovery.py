#!/usr/bin/env python3
"""
The cases for `scripts/_panel_discovery.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

THREE EXPRESSIONS COULD NOT MOVE LITERALLY, AND TWO OF THEM FAIL SILENTLY.

  * `_counted()` swapped the module's front-matter reader for a counting stub with
    `globals()["_fm_of"] = c_fm`. From here that binds a name nothing calls: every
    `reads` count would be 0, and the four cases that read `_n["reads"] > 0` would go
    red while the two that read `== 0` would go green ON A BROKEN CACHE. It is
    `M._fm_of = c_fm` now, restored on `M` in the same `finally`. `os.listdir` and
    `os.scandir` stay patched on `os` itself, which is the same module object the
    subject imported, so those two needed no change.
  * `open(__file__)` meant "this module's source" for the case that forbids an import
    of panel-server or _panel_settings. From here it reads THIS file, which imports
    neither and never will - a case that can only pass. It is `M.__file__`.
  * `os.path.dirname(...)` three deep off `_HERE` meant the repo root. `scripts/` and
    `tests/` are both one level under the plugin directory, so the literal move would
    have been right by coincidence; it is spelled off `_harness.SCRIPTS_DIR` instead.

Both silent ones were run in their literal form first: the `globals()` one turns
`cache: the first scan really does walk the tree` red with 0 reads while leaving the
skip case green, and the `__file__` one stays green after `import panel_server` is
planted in the subject.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import shutil
import sys
import tempfile
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _panel_discovery as M                       # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # front-matter parser
    fm = M._front_matter("---\nname: my-skill\ndescription: \"Does X.\"\n---\nbody")
    check("front-matter name", fm.get("name") == "my-skill")
    check("front-matter desc unquoted", fm.get("description") == "Does X.")
    check("no front-matter -> {}", M._front_matter("# just md") == {})

    tmp = tempfile.mkdtemp(prefix="panel-discovery-selftest-")
    proj = os.path.join(tmp, "proj")
    home = os.path.join(tmp, "home")
    # a project skill + agent
    os.makedirs(os.path.join(proj, ".claude", "skills", "proj-skill"))
    with open(os.path.join(proj, ".claude", "skills", "proj-skill", "SKILL.md"), "w") as fh:
        fh.write("---\nname: proj-skill\ndescription: Project skill.\n---\n")
    os.makedirs(os.path.join(proj, ".claude", "agents"))
    with open(os.path.join(proj, ".claude", "agents", "proj-agent.md"), "w") as fh:
        fh.write("---\nname: proj-agent\ndescription: Project agent.\n---\n")
    # a user-global skill
    os.makedirs(os.path.join(home, ".claude", "skills", "user-skill"))
    with open(os.path.join(home, ".claude", "skills", "user-skill", "SKILL.md"), "w") as fh:
        fh.write("---\nname: user-skill\n---\n")

    reg = M.discover(proj, home=home)
    names = {s["name"] for s in reg["skills"]}
    check("discovery finds project skill", "proj-skill" in names)
    check("discovery finds user skill", "user-skill" in names)
    check("discovery finds project agent",
          any(a["name"] == "proj-agent" for a in reg["agents"]))
    check("discovery labels source",
          any(s["source"] == "project" for s in reg["skills"]) and
          any(s["source"] == "user" for s in reg["skills"]))

    # --- isolation cases (P12.2): moved-module boundaries stay real ------------
    _long = os.path.join(tmp, "long-skill.md")
    with open(_long, "w") as fh:
        fh.write("---\nname: long\ndescription: " + ("x" * 5000) + "\n---\nbody")
    check("_fm_of's fallback read actually parses a fence past the 4096-byte cap",
          M._fm_of(_long).get("name") == "long")
    # scripts/ -> audit -> plugins -> the repo root. Off `_harness.SCRIPTS_DIR`,
    # not off this file: tests/ sits at the same depth, so the literal form would
    # be correct only by coincidence.
    _repo_root = os.path.dirname(os.path.dirname(
        os.path.dirname(_harness.SCRIPTS_DIR)))
    check("discovery labels this repo's own plugins by their real directory name, "
          "not a generic 'plugin' badge",
          M._local_plugin_bases(_repo_root, []))
    check("MCP names come back sorted, with no secrets in the row (names only)",
          M._mcp_names(home, proj, []) == sorted(M._mcp_names(home, proj, [])))
    _src_lines = [l for l in open(M.__file__).read().split("\n")
                  if l.startswith("import ") or l.startswith("from ")]
    check("this module never imports panel-server or _panel_settings - it sits at "
          "the bottom of the panel's own import graph",
          not any("panel_server" in l or "_panel_settings" in l for l in _src_lines))

    # --- the scan cache: invalidation, in BOTH directions -----------------------
    # A stale registry is worse than a slow one, so neither direction is taken on
    # trust: the walk must be skipped when the tree is unchanged, and must re-run
    # when it is not. Every case below counts filesystem calls rather than timing
    # anything — a wall-clock assertion is flaky on a loaded machine and cannot say
    # WHICH work was skipped.
    def _counted(fn):
        """`(result, {listdir, scandir, reads})` for one call of `fn`.

        os.scandir is the engine under os.walk, so counting it is how "the plugins
        tree was not walked" gets said as a number.

        `_fm_of` is rebound ON `M` - it is the SUBJECT's global that `_discover_scan`
        resolves at call time, and this file's `globals()` is not it."""
        n = {"listdir": 0, "scandir": 0, "reads": 0}
        real_listdir, real_scandir, real_fm = os.listdir, os.scandir, M._fm_of

        def c_listdir(*a, **kw):
            n["listdir"] += 1
            return real_listdir(*a, **kw)

        def c_scandir(*a, **kw):
            n["scandir"] += 1
            return real_scandir(*a, **kw)

        def c_fm(path):
            n["reads"] += 1
            return real_fm(path)

        os.listdir, os.scandir = c_listdir, c_scandir
        M._fm_of = c_fm
        try:
            result = fn()
        finally:
            os.listdir, os.scandir = real_listdir, real_scandir
            M._fm_of = real_fm
        return result, n

    def _age(root, seconds=5):
        """Backdate a fixture tree so `_settled` will accept a scan of it.

        Needed because the settle guard is doing its job: a tree written
        milliseconds ago is deliberately NOT cached. Aging the fixture is the
        honest way to reach the cached path, and the guard itself is checked in
        both directions further down."""
        when = time.time() - seconds
        for dirpath, dirnames, filenames in os.walk(root):
            for name in filenames + dirnames:
                os.utime(os.path.join(dirpath, name), (when, when))
        os.utime(root, (when, when))

    # A real plugins tree, so os.walk actually runs and `scandir == 0` below is a
    # claim about work skipped rather than work that never existed.
    _pkg_a = os.path.join(home, ".claude", "plugins", "marketplace", "pkg-a")
    os.makedirs(os.path.join(_pkg_a, "skills", "plug-skill"))
    with open(os.path.join(_pkg_a, "skills", "plug-skill", "SKILL.md"), "w") as fh:
        fh.write("---\nname: plug-skill\ndescription: From a plugin.\n---\n")
    os.makedirs(os.path.join(_pkg_a, "agents"))
    with open(os.path.join(_pkg_a, "agents", "plug-agent.md"), "w") as fh:
        fh.write("---\nname: plug-agent\ndescription: From a plugin.\n---\n")
    _age(tmp)

    _r1, _n1 = _counted(lambda: M.discover(proj, home=home))
    check("cache: the first scan really does walk the tree — the baseline the "
          "skip case below is measured against, and the proof the counter works",
          _n1["listdir"] > 0 and _n1["scandir"] > 0 and _n1["reads"] > 0)
    _r2, _n2 = _counted(lambda: M.discover(proj, home=home))
    # THE SECOND-DIRECTION CASE. It looks vacuous and it is the only one that
    # fails if invalidation becomes unconditional (a bare recompute, a stamp that
    # never compares equal) — the cache would still be correct and would have
    # bought nothing.
    check("cache: with nothing changed on disk the second call lists no "
          "directory, walks no tree and reads no front matter",
          _n2["listdir"] == 0 and _n2["scandir"] == 0 and _n2["reads"] == 0)
    check("cache: ...and hands back the same answer it computed the first time",
          _r2 == _r1)

    # THE FIRST-DIRECTION CASES: the tree moves, the cached answer must not
    # survive it. Four separate routes, because each invalidates through a
    # different part of the watch list.
    _root_before = os.stat(os.path.join(home, ".claude", "plugins")).st_mtime_ns
    _pkg_b = os.path.join(home, ".claude", "plugins", "marketplace", "pkg-b")
    os.makedirs(os.path.join(_pkg_b, "skills", "deep-skill"))
    with open(os.path.join(_pkg_b, "skills", "deep-skill", "SKILL.md"), "w") as fh:
        fh.write("---\nname: deep-skill\ndescription: Installed after the scan.\n---\n")
    _r3, _n3 = _counted(lambda: M.discover(proj, home=home))
    check("cache: a plugin installed BELOW the root invalidates — and the root's "
          "own mtime never moved, which is exactly what a stat of the roots "
          "alone would have missed",
          "deep-skill" in {s["name"] for s in _r3["skills"]} and _n3["reads"] > 0
          and os.stat(os.path.join(home, ".claude",
                                   "plugins")).st_mtime_ns == _root_before)

    _age(tmp)
    M.discover(proj, home=home)                     # re-warm on the new tree
    _edited = os.path.join(proj, ".claude", "skills", "proj-skill", "SKILL.md")
    with open(_edited, "w") as fh:
        fh.write("---\nname: proj-skill\ndescription: Edited in place.\n---\n")
    _r4, _n4 = _counted(lambda: M.discover(proj, home=home))
    check("cache: a description EDITED IN PLACE invalidates — no directory's "
          "entry list changed, so only stamping the FILE can catch this",
          _n4["reads"] > 0
          and [s["description"] for s in _r4["skills"]
               if s["name"] == "proj-skill"] == ["Edited in place."])

    _age(tmp)
    M.discover(proj, home=home)
    os.remove(os.path.join(_pkg_b, "skills", "deep-skill", "SKILL.md"))
    os.rmdir(os.path.join(_pkg_b, "skills", "deep-skill"))
    _r5, _n5 = _counted(lambda: M.discover(proj, home=home))
    check("cache: a skill REMOVED after the scan stops being offered",
          "deep-skill" not in {s["name"] for s in _r5["skills"]}
          and _n5["reads"] > 0)

    _age(tmp)
    M.discover(proj, home=home)
    with open(os.path.join(proj, ".mcp.json"), "w") as fh:
        fh.write('{"mcpServers": {"late-server": {"command": "x"}}}')
    _r6, _n6 = _counted(lambda: M.discover(proj, home=home))
    check("cache: a file that did not EXIST when the scan ran invalidates when it "
          "appears — absent paths are stamped, not dropped from the token",
          "late-server" in _r6["mcp"])

    # The settle guard, both ways. Its whole purpose is to refuse a scan of a tree
    # that was still being written, so a case that only ever saw it accept would
    # be asserting nothing.
    _fresh = os.path.join(tmp, "fresh")
    _fresh_home = os.path.join(_fresh, "home")
    _fresh_proj = os.path.join(_fresh, "proj")
    os.makedirs(os.path.join(_fresh_home, ".claude", "skills", "s1"))
    os.makedirs(_fresh_proj)
    with open(os.path.join(_fresh_home, ".claude", "skills", "s1", "SKILL.md"),
              "w") as fh:
        fh.write("---\nname: s1\n---\n")
    M.discover(_fresh_proj, home=_fresh_home)
    _r7, _n7 = _counted(lambda: M.discover(_fresh_proj, home=_fresh_home))
    check("cache: a tree written a moment ago is NOT cached — a 1-second-granular "
          "mtime cannot prove the scan saw the final bytes",
          _n7["reads"] > 0)
    _age(_fresh)
    M.discover(_fresh_proj, home=_fresh_home)
    _r8, _n8 = _counted(lambda: M.discover(_fresh_proj, home=_fresh_home))
    check("cache: ...and the same tree, once it has settled, IS cached",
          _n8["listdir"] == 0 and _n8["reads"] == 0)

    _age(tmp)
    M.discover(proj, home=home)
    _r9, _n9 = _counted(lambda: M.discover(proj, home=home, cache=False))
    _r10, _n10 = _counted(lambda: M.discover(proj, home=home))
    check("cache=False walks unconditionally, and stores nothing — the entry that "
          "was already there is neither used nor replaced by it",
          _n9["reads"] > 0 and _n10["reads"] == 0 and _r9 == _r10)

    _mine = M.discover(proj, home=home)
    _mine["skills"].append(M._entry("injected", "not on disk", "test", "/nowhere"))
    _mine["skills"][0]["name"] = "clobbered"
    _theirs = M.discover(proj, home=home)
    check("cache: each caller gets its own copy — mutating a returned registry "
          "cannot poison the next caller's answer",
          "injected" not in {s["name"] for s in _theirs["skills"]}
          and "clobbered" not in {s["name"] for s in _theirs["skills"]})

    _reg, _watch = M._discover_scan(proj, home)
    _parsed = {e["path"] for e in _reg["skills"] + _reg["agents"]}
    check("cache: every file the scan parsed is in the watch list — a file read "
          "but not stamped is precisely how a cache goes stale in silence",
          bool(_parsed) and _parsed <= set(_watch))

    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_discovery.py --selftest\n")
    raise SystemExit(2)
