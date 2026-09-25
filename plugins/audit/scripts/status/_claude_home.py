#!/usr/bin/env python3
"""
Claude Code's own records of what it installed, read in one place.

`installed_plugins.json` and `known_marketplaces.json` are files Claude Code
writes under its home directory and does not document, so every reader here is
FAIL-OPEN: a record that is missing, unreadable or shaped differently comes back
as `None` beside the sentence saying why, and each caller says that the basis is
an undocumented file wherever it prints a fact drawn from one.

WHY A MODULE OF ITS OWN. `/audit:version` read these files first, and it is an
entry point, which nothing below it may import. `/audit:doctor`'s `plugin files`
row needs the same records - which commit a marketplace install was made from,
and where the clone that holds it lives - so the readers moved down to a layer
both can reach, rather than a second reader being written beside the first.
"""
import json
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

PLUGIN_NAME = "audit"
UNDOCUMENTED = "a file Claude Code writes and does not document"


# --- reading -------------------------------------------------------------------
def claude_home(env=None):
    """Claude Code's home: CLAUDE_CONFIG_DIR when set, else ~/.claude."""
    env = os.environ if env is None else env
    return env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"),
                                                         ".claude")


def read_json(path):
    """(document, why) - the parsed file, or None and the reason it is absent."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), ""
    except OSError as exc:
        return None, "%s could not be read (%s)" % (path, exc.strerror or exc)
    except ValueError as exc:
        return None, "%s is not JSON (%s)" % (path, exc)


def installed_plugins(home):
    doc, why = read_json(os.path.join(home, "plugins", "installed_plugins.json"))
    plugins = doc.get("plugins") if isinstance(doc, dict) else None
    return (plugins if isinstance(plugins, dict) else None), why


def marketplace_of(plugin_root, home):
    """(name, basis) - the marketplace this copy was installed from, or None.

    Read off Claude Code's install record for this exact path, else off the
    cache path it installs into (`plugins/cache/<marketplace>/<plugin>/<ver>`).
    A copy run from a checkout matches neither, and that is said."""
    plugins, _why = installed_plugins(home)
    target = os.path.realpath(plugin_root)
    for key, entries in sorted((plugins or {}).items()):
        name, _at, market = key.partition("@")
        if name != PLUGIN_NAME or not market:
            continue
        for entry in entries if isinstance(entries, list) else []:
            path = entry.get("installPath") if isinstance(entry, dict) else None
            if path and os.path.realpath(path) == target:
                return market, "installed_plugins.json names this path"
    parts = os.path.realpath(plugin_root).split(os.sep)
    if "cache" in parts:
        i = len(parts) - 1 - parts[::-1].index("cache")
        if len(parts) > i + 2 and parts[i + 2] == PLUGIN_NAME:
            return parts[i + 1], "the cache path this copy sits in"
    return None, ("this copy runs from %s, not from an installed marketplace copy"
                  % (plugin_root,))


def marketplace_facts(home, name):
    """What the marketplace clone offers, when it was refreshed, and whether it
    auto-updates - or why that could not be read."""
    doc, why = read_json(os.path.join(home, "plugins", "known_marketplaces.json"))
    entry = doc.get(name) if isinstance(doc, dict) else None
    if not isinstance(entry, dict):
        return {"name": name, "error": why or ("known_marketplaces.json has no %r"
                                               % (name,))}
    out = {"name": name, "lastUpdated": entry.get("lastUpdated"),
           "autoUpdate": entry.get("autoUpdate"),
           "location": entry.get("installLocation"), "offered": None,
           "basis": "known_marketplaces.json, %s" % UNDOCUMENTED}
    clone, sub, cwhy = marketplace_source(home, name)
    if clone is not None:
        pj, _pwhy = read_json(os.path.join(clone, sub, ".claude-plugin",
                                           "plugin.json"))
        offered = (pj or {}).get("version") if isinstance(pj, dict) else None
        out["offered"] = offered if isinstance(offered, str) else None
    if out["offered"] is None:
        out["offeredWhy"] = cwhy or ("the clone at %s names no %r plugin with a "
                                     "version" % (clone, PLUGIN_NAME))
    return out


def installed_copies(home, name):
    """Every installed copy of this plugin from `name`, by scope and project."""
    plugins, why = installed_plugins(home)
    if plugins is None:
        return None, why
    rows = []
    for entry in plugins.get("%s@%s" % (PLUGIN_NAME, name)) or []:
        if isinstance(entry, dict):
            rows.append({"scope": entry.get("scope"),
                         "project": entry.get("projectPath"),
                         "version": entry.get("version")})
    return rows, ""


def install_record(plugin_root, home):
    """`(record, why)` - Claude Code's install record for the copy at `plugin_root`.

    `record` is `{"marketplace", "installPath", "gitCommitSha", "version"}`, or
    None beside the reason. Matched on the resolved install path, because several
    projects can install one version into one cache directory and every one of
    those records names the same commit."""
    plugins, why = installed_plugins(home)
    if plugins is None:
        return None, why or "installed_plugins.json holds no plugins map"
    target = os.path.realpath(plugin_root)
    for key, entries in sorted(plugins.items()):
        name, _at, market = key.partition("@")
        if name != PLUGIN_NAME or not market:
            continue
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            path = entry.get("installPath")
            if path and os.path.realpath(path) == target:
                sha = entry.get("gitCommitSha")
                return {"marketplace": market, "installPath": path,
                        "version": entry.get("version"),
                        "gitCommitSha": sha if isinstance(sha, str) and sha
                        else None}, ""
    return None, ("installed_plugins.json records no install at %s"
                  % (plugin_root,))


def marketplace_source(home, name):
    """`(clone, subdir, why)` - where marketplace `name`'s clone lives and which
    directory of it holds this plugin, off `known_marketplaces.json` and the
    clone's own `marketplace.json`. `clone` is None beside the reason."""
    doc, why = read_json(os.path.join(home, "plugins", "known_marketplaces.json"))
    entry = doc.get(name) if isinstance(doc, dict) else None
    location = entry.get("installLocation") if isinstance(entry, dict) else None
    if not isinstance(location, str) or not location:
        return None, None, why or ("known_marketplaces.json records no clone "
                                   "for %r" % (name,))
    catalog, cwhy = read_json(os.path.join(location, ".claude-plugin",
                                           "marketplace.json"))
    plugins = catalog.get("plugins") if isinstance(catalog, dict) else None
    for plugin in plugins if isinstance(plugins, list) else []:
        if isinstance(plugin, dict) and plugin.get("name") == PLUGIN_NAME:
            source = plugin.get("source")
            if not isinstance(source, str):
                return None, None, ("the clone at %s names %r from a source that "
                                    "is not a path inside it" % (location,
                                                                 PLUGIN_NAME))
            sub = os.path.normpath(source).replace(os.sep, "/")
            return location, ("" if sub == "." else sub), ""
    return None, None, cwhy or ("the clone at %s names no %r plugin"
                                % (location, PLUGIN_NAME))


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_claude_home.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__claude_home.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
