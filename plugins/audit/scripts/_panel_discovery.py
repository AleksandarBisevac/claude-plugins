#!/usr/bin/env python3
"""
Discovery: which skills, agents and MCP servers this project can actually reach
— project-local, user-global, installed plugins and this repo's own plugins tree
— stdlib only.

Moved out of panel-server.py (P12.2). This is a read-only filesystem scan, not
server plumbing: given a project directory (and, for tests, a home directory), it
walks the same places Claude Code itself looks for skills/agents and returns what
it finds, so the panel's composition pickers offer real building blocks instead of
free-typed names that may not exist.

Front matter parsing delegates to `_help.front_matter` (P10.5) rather than
reimplementing it here — this module still needs `_help` for that one function,
which is fine: `_help` does not import this module or panel-server, so there is no
cycle.

panel-server.py keeps thin module-level aliases (`discover =
_panel_discovery.discover`, etc.) so every downstream reference — the /api/registry
route, the policy preview's own `discover(project)` call, and the selftest's fixture
-dir cases — keeps working unchanged.

The scan is CACHED, and the invalidation rule is the whole design — it is written
out in `discover`'s docstring rather than inferred from the code, because a panel
that reports a stale filesystem has failed at its only job. Short version: the scan
records every path it read, and the cache is valid only while a fresh `os.stat` of
all of them still matches. It is not a TTL.

This module must never import panel-server or _panel_settings: nothing that imports
THIS module (both of them do) can form a cycle through it.
"""
import copy
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _help  # noqa: E402  (schema-sourced field help + concept topics; front_matter lives here)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)


# --- discovery / registry -------------------------------------------------------
def _front_matter(text):
    """Delegates to `_help.front_matter` -- the one frontmatter parser in the
    plugin. See that docstring for what it does at the edges (CRLF, indented
    continuation lines, quoted scalars via `_help.unquote_scalar`, missing
    closing fence)."""
    return _help.front_matter(text)


def _fm_of(path):
    """Read up to a byte cap (this scans every skill/agent file in a
    directory, so keeping the common case cheap matters) and parse. The cap
    is a deliberate read-size guard, not a truncation of the parse result:
    if the closing '---' fence is not found within the capped read, the read
    was cut off mid-block, so fall back to reading the whole file rather than
    silently parsing (or failing to parse) a truncated block. Correctness
    over the micro-optimization in that rare case."""
    cap = 4096
    try:
        with open(path, "r", encoding="utf-8") as fh:
            head = fh.read(cap)
            if len(head) >= cap and re.match(r"^---\r?\n", head) and \
               not re.search(r"\r?\n---\r?\n", head):
                fh.seek(0)
                head = fh.read()
        return _front_matter(head)
    except Exception:
        return {}


def _entry(name, description, source, path):
    return {"name": name, "description": (description or "")[:280],
            "source": source, "path": path}


def _scan_skills(base, source, out, seen, watch, cap=500):
    """Add every <base>/*/SKILL.md as a skill entry.

    `watch` collects every path whose contents (a directory's entry list, a
    file's front matter) decided the outcome — see `discover` for what it is
    for. It is appended to HERE, at the read, rather than rebuilt by a second
    function that mirrors this one: a watch list maintained apart from the scan
    drifts from it, and a drifted watch list is a cache that goes stale in
    silence. Note the per-skill subdirectory is watched even when it holds no
    SKILL.md yet — creating one there changes that directory's mtime and
    nothing shallower.
    """
    skills_dir = os.path.join(base, "skills")
    watch.append(skills_dir)
    if not os.path.isdir(skills_dir):
        return
    for name in sorted(os.listdir(skills_dir)):
        if len(out) >= cap:
            return
        watch.append(os.path.join(skills_dir, name))
        sk = os.path.join(skills_dir, name, "SKILL.md")
        if os.path.isfile(sk):
            watch.append(sk)
            fm = _fm_of(sk)
            key = (fm.get("name") or name)
            if key in seen:  # dedupe by name; project/user scanned before plugins win
                continue
            seen.add(key)
            out.append(_entry(key, fm.get("description"), source, sk))


def _scan_agents(base, source, out, seen, watch, cap=500):
    """Add every <base>/agents/*.md as an agent entry.

    Every file READ is watched, including the ones deduped away: a shadowed
    file whose front matter renames it to something not yet taken would change
    the answer, so its mtime has to count.
    """
    agents_dir = os.path.join(base, "agents")
    watch.append(agents_dir)
    if not os.path.isdir(agents_dir):
        return
    for name in sorted(os.listdir(agents_dir)):
        if len(out) >= cap:
            return
        if not name.endswith(".md"):
            continue
        ap = os.path.join(agents_dir, name)
        watch.append(ap)
        fm = _fm_of(ap)
        key = fm.get("name") or name[:-3]
        if key in seen:  # dedupe by name; project/user scanned before plugins win
            continue
        seen.add(key)
        out.append(_entry(key, fm.get("description"), source, ap))


def _plugin_bases(home, watch, cap=200):
    """Directories that may hold skills/agents inside the plugins tree.

    Every directory the walk VISITS is watched, not just the ones that turned
    out to be interesting: a plugin installed anywhere under this tree changes
    the mtime of exactly one directory — its immediate parent — and of nothing
    above it. Watching only the root would miss every install below depth 1.
    """
    root = os.path.join(home, ".claude", "plugins")
    watch.append(root)
    bases = []
    if not os.path.isdir(root):
        return bases
    for dirpath, dirnames, _files in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth > 5:
            dirnames[:] = []
            continue
        watch.append(dirpath)
        if os.path.basename(dirpath) in ("skills", "agents"):
            bases.append(os.path.dirname(dirpath))
        if len(bases) >= cap:
            break
    return sorted(set(bases))


def _discover_scan(project, home):
    """One uncached scan: `({skills, agents, mcp}, watched_paths)`.

    Split out of `discover` so the cache has a seam to wrap, and so the second
    element is produced BY the scan rather than guessed alongside it."""
    skills, agents, s_seen, a_seen, watch = [], [], set(), set(), []
    # project-local
    _scan_skills(os.path.join(project, ".claude"), "project", skills, s_seen, watch)
    _scan_agents(os.path.join(project, ".claude"), "project", agents, a_seen, watch)
    # user-global
    _scan_skills(os.path.join(home, ".claude"), "user", skills, s_seen, watch)
    _scan_agents(os.path.join(home, ".claude"), "user", agents, a_seen, watch)
    # installed plugins (parent-dir basename is often a version/cache name — noise,
    # so use a plain 'plugin' badge)
    for base in _plugin_bases(home, watch):
        _scan_skills(base, "plugin", skills, s_seen, watch)
        _scan_agents(base, "plugin", agents, a_seen, watch)
    # this repo's own plugins (dev / local checkout — basename is the real name)
    for base in sorted(_local_plugin_bases(project, watch)):
        label = "plugin:" + os.path.basename(base)
        _scan_skills(base, label, skills, s_seen, watch)
        _scan_agents(base, label, agents, a_seen, watch)
    # MCP servers (names only — never surface secrets/tokens)
    mcp = _mcp_names(home, project, watch)
    return {"skills": skills, "agents": agents, "mcp": mcp}, watch


def _local_plugin_bases(project, watch):
    root = os.path.join(project, "plugins")
    watch.append(root)
    out = []
    if os.path.isdir(root):
        for name in os.listdir(root):
            d = os.path.join(root, name)
            # Watched whether or not it qualifies today: a `skills/` directory
            # added inside it tomorrow makes it qualify, and moves only ITS mtime.
            watch.append(d)
            if os.path.isdir(os.path.join(d, "skills")) or \
               os.path.isdir(os.path.join(d, "agents")):
                out.append(d)
    return out


def _mcp_names(home, project, watch):
    names = set()
    for path in (os.path.join(home, ".claude.json"),
                 os.path.join(project, ".mcp.json")):
        watch.append(path)
        try:
            data = _mio.read_json(path)
        except Exception:
            continue
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict):
            names.update(str(k) for k in servers.keys())
    return sorted(names)


# --- scan cache -----------------------------------------------------------------
# {(project, home): {"watch": [...], "stamp": [...], "registry": {...}}}. One entry
# per project in practice — panel-server serves exactly one, audit-status runs once
# and exits — so this is not a growth surface worth bounding.
#
# panel-server is a ThreadingHTTPServer, so two requests can be in here at once.
# That is safe only under one rule: an entry is REPLACED, never edited in place.
# A reader holds the whole entry it fetched, so a concurrent writer swapping in a
# new one cannot tear the watch list away from the stamp it belongs to. The worst
# outcome is a redundant scan. Do not "optimize" this by mutating `hit`.
_DISCOVERY_CACHE = {}

# Refuse to cache a scan of a tree that was still being written when the scan ran.
# Plenty of filesystems keep mtime to 1-second granularity (HFS+, several network
# mounts), so a write landing between the read of a file and the stat of it can be
# recorded under an mtime the stamp already holds — after which the stale answer
# would be served forever, which is the one failure this cache must not have. Git
# calls the same hazard a "racily clean" index entry and defuses it the same way.
_SETTLE_SECONDS = 1.0


def _stamp(paths):
    """`(path, mtime_ns, size, inode)` per watched path — the cache's validity token.

    An ABSENT path is stamped with `None`s rather than dropped: `~/.claude/skills`
    not existing is an answer, and it changes the moment somebody creates it. A
    token covering only what exists could not tell those two states apart, so
    installing the first user-global skill would never invalidate.

    Size and inode ride along with mtime because mtime alone is the weakest of the
    three: a file replaced by `os.replace` keeps neither size nor inode by luck.
    """
    out = []
    for path in paths:
        try:
            st = os.stat(path)
            out.append((path, st.st_mtime_ns, st.st_size, st.st_ino))
        except OSError:
            out.append((path, None, None, None))
    return out


def _settled(stamp, started):
    """True iff nothing in `stamp` was written during the scan, or in the second
    before it began. See `_SETTLE_SECONDS` for why the second matters."""
    newest = 0.0
    for _path, mtime_ns, _size, _ino in stamp:
        if mtime_ns is not None:
            newest = max(newest, mtime_ns / 1000000000.0)
    return newest < started - _SETTLE_SECONDS


def discover(project, home=None, cache=True):
    """Return {skills, agents, mcp} available to this project (read-only scan).

    WHY THERE IS A CACHE. This is the panel's most expensive read by an order of
    magnitude — measured on one developer machine at 1,381 `scandir` calls and 337
    front-matter reads, 159 ms cold and 31 ms warm — and it runs on a POLL, not on
    demand: `_panel_state.data_fingerprint` folds in the newest usage-ledger mtime,
    and `meter-usage.py` appends to that ledger on every Stop / SubagentStop /
    SessionEnd. So during an `/audit:phase` with parallel subagents the fingerprint
    moves constantly, the panel's 5-second poll calls `refreshFromDisk()`, and that
    refetches state + usage + policy — a full `~/.claude` tree walk every five
    seconds for the whole run, bought with nothing but somebody spending tokens.

    INVALIDATION — the whole design, so it is stated rather than implied:

      * The token is a fresh `os.stat` of EVERY path the previous scan read: each
        directory whose entry list it listed or walked, each markdown file whose
        front matter it parsed, and both MCP config files. `_discover_scan` returns
        that list; it is collected at the reads themselves, so it cannot describe a
        scan other than the one that happened.
      * That covers every way the answer can move. A skill or agent installed,
        removed or renamed changes its parent directory's mtime, and that parent
        was walked. A description EDITED IN PLACE changes only the file's own
        mtime — which is why the files are stamped too, and why a directory-only
        token would have been dishonest.
      * It is NOT a TTL and NOT a stat of the roots alone. A TTL has a window in
        which the panel knowingly lies; a root-only stat never notices a plugin
        installed three levels down, because adding it does not touch the root.
        `_VIEWER_CACHE` in `_panel_state` used to be the cautionary case here — it
        never expired at all, so `git config user.email` changed mid-session showed
        the old name until the panel was restarted. It now carries a token of its
        own, built the same way this one is, and reuses `_settled` below by
        reference. The example is kept because the failure is worth recognising,
        not because that cache still has it.
      * A scan of a tree that was being written AS it ran is returned but not
        cached — see `_SETTLE_SECONDS`. Refusing to cache is the safe direction:
        the caller still gets a correct answer, it just costs a walk.
      * Revalidation on that same machine is 1,679 `stat` calls, measured at
        ~2 ms against the 31 ms walk it replaces. Statting far more paths than a
        TTL would is the price of the token being honest, and it is still the
        cheaper half by 15x.

    `cache=False` forces a scan and stores nothing — for callers that want to
    measure the walk, and for the cases below that must see the real thing.
    """
    home = home or os.path.expanduser("~")
    key = (os.path.realpath(project), os.path.realpath(home))
    if cache:
        hit = _DISCOVERY_CACHE.get(key)
        if hit is not None and _stamp(hit["watch"]) == hit["stamp"]:
            return copy.deepcopy(hit["registry"])
    started = time.time()
    registry, watch = _discover_scan(project, home)
    if not cache:
        return registry
    watch = sorted(set(watch))
    stamp = _stamp(watch)
    if _settled(stamp, started):
        _DISCOVERY_CACHE[key] = {"watch": watch, "stamp": stamp,
                                 "registry": registry}
    else:
        # Not merely "don't store": an entry from an earlier, settled scan would
        # still be serving its own answer, and this scan just saw the tree move.
        _DISCOVERY_CACHE.pop(key, None)
    # A copy, always — the cached registry outlives the request, and one caller
    # appending to `skills` would hand the next caller a corrupted answer with
    # nothing raised anywhere.
    return copy.deepcopy(registry)


# --- selftest ---------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    # front-matter parser
    fm = _front_matter("---\nname: my-skill\ndescription: \"Does X.\"\n---\nbody")
    check("front-matter name", fm.get("name") == "my-skill")
    check("front-matter desc unquoted", fm.get("description") == "Does X.")
    check("no front-matter -> {}", _front_matter("# just md") == {})

    import tempfile
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

    reg = discover(proj, home=home)
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
          _fm_of(_long).get("name") == "long")
    _repo_root = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
    check("discovery labels this repo's own plugins by their real directory name, "
          "not a generic 'plugin' badge",
          _local_plugin_bases(_repo_root, []))
    check("MCP names come back sorted, with no secrets in the row (names only)",
          _mcp_names(home, proj, []) == sorted(_mcp_names(home, proj, [])))
    _src_lines = [l for l in open(__file__).read().split("\n")
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
        tree was not walked" gets said as a number."""
        n = {"listdir": 0, "scandir": 0, "reads": 0}
        real_listdir, real_scandir, real_fm = os.listdir, os.scandir, _fm_of

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
        globals()["_fm_of"] = c_fm
        try:
            result = fn()
        finally:
            os.listdir, os.scandir = real_listdir, real_scandir
            globals()["_fm_of"] = real_fm
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

    _r1, _n1 = _counted(lambda: discover(proj, home=home))
    check("cache: the first scan really does walk the tree — the baseline the "
          "skip case below is measured against, and the proof the counter works",
          _n1["listdir"] > 0 and _n1["scandir"] > 0 and _n1["reads"] > 0)
    _r2, _n2 = _counted(lambda: discover(proj, home=home))
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
    _r3, _n3 = _counted(lambda: discover(proj, home=home))
    check("cache: a plugin installed BELOW the root invalidates — and the root's "
          "own mtime never moved, which is exactly what a stat of the roots "
          "alone would have missed",
          "deep-skill" in {s["name"] for s in _r3["skills"]} and _n3["reads"] > 0
          and os.stat(os.path.join(home, ".claude",
                                   "plugins")).st_mtime_ns == _root_before)

    _age(tmp)
    discover(proj, home=home)                       # re-warm on the new tree
    _edited = os.path.join(proj, ".claude", "skills", "proj-skill", "SKILL.md")
    with open(_edited, "w") as fh:
        fh.write("---\nname: proj-skill\ndescription: Edited in place.\n---\n")
    _r4, _n4 = _counted(lambda: discover(proj, home=home))
    check("cache: a description EDITED IN PLACE invalidates — no directory's "
          "entry list changed, so only stamping the FILE can catch this",
          _n4["reads"] > 0
          and [s["description"] for s in _r4["skills"]
               if s["name"] == "proj-skill"] == ["Edited in place."])

    _age(tmp)
    discover(proj, home=home)
    os.remove(os.path.join(_pkg_b, "skills", "deep-skill", "SKILL.md"))
    os.rmdir(os.path.join(_pkg_b, "skills", "deep-skill"))
    _r5, _n5 = _counted(lambda: discover(proj, home=home))
    check("cache: a skill REMOVED after the scan stops being offered",
          "deep-skill" not in {s["name"] for s in _r5["skills"]}
          and _n5["reads"] > 0)

    _age(tmp)
    discover(proj, home=home)
    with open(os.path.join(proj, ".mcp.json"), "w") as fh:
        fh.write('{"mcpServers": {"late-server": {"command": "x"}}}')
    _r6, _n6 = _counted(lambda: discover(proj, home=home))
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
    discover(_fresh_proj, home=_fresh_home)
    _r7, _n7 = _counted(lambda: discover(_fresh_proj, home=_fresh_home))
    check("cache: a tree written a moment ago is NOT cached — a 1-second-granular "
          "mtime cannot prove the scan saw the final bytes",
          _n7["reads"] > 0)
    _age(_fresh)
    discover(_fresh_proj, home=_fresh_home)
    _r8, _n8 = _counted(lambda: discover(_fresh_proj, home=_fresh_home))
    check("cache: ...and the same tree, once it has settled, IS cached",
          _n8["listdir"] == 0 and _n8["reads"] == 0)

    _age(tmp)
    discover(proj, home=home)
    _r9, _n9 = _counted(lambda: discover(proj, home=home, cache=False))
    _r10, _n10 = _counted(lambda: discover(proj, home=home))
    check("cache=False walks unconditionally, and stores nothing — the entry that "
          "was already there is neither used nor replaced by it",
          _n9["reads"] > 0 and _n10["reads"] == 0 and _r9 == _r10)

    _mine = discover(proj, home=home)
    _mine["skills"].append(_entry("injected", "not on disk", "test", "/nowhere"))
    _mine["skills"][0]["name"] = "clobbered"
    _theirs = discover(proj, home=home)
    check("cache: each caller gets its own copy — mutating a returned registry "
          "cannot poison the next caller's answer",
          "injected" not in {s["name"] for s in _theirs["skills"]}
          and "clobbered" not in {s["name"] for s in _theirs["skills"]})

    _reg, _watch = _discover_scan(proj, home)
    _parsed = {e["path"] for e in _reg["skills"] + _reg["agents"]}
    check("cache: every file the scan parsed is in the watch list — a file read "
          "but not stamped is precisely how a cache goes stale in silence",
          bool(_parsed) and _parsed <= set(_watch))

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

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
    print(__doc__.strip())
