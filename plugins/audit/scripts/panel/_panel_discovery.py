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

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__panel_discovery.py`, byte-identical labels and all -
see `plugins/audit/tests/_harness.py`. One of them parses THIS file and fails if
it ever grows an import of panel-server or _panel_settings.
"""
import copy
import os
import re
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


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_discovery.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__panel_discovery.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
