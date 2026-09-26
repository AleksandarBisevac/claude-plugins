#!/usr/bin/env python3
"""
Which build of the plugin is running, and whether a newer one is published.

A plugin cannot ask Claude Code which copy of it is loaded - that is not a
documented interface - so the answer is assembled from what can be read, each
fact beside the file or service it came from:

  running      the plugin.json of the copy this command runs from
  marketplace  what the marketplace clone offers, when it was refreshed, and
               whether it auto-updates - Claude Code's own records under its home
               directory, which it writes and does not document
  installed    every installed copy of this plugin, by scope and project
  published    the newest release on the repository plugin.json names - one
               unauthenticated GET to the GitHub API, skipped by --offline

WHY EACH LINE CARRIES ITS SOURCE: two of them read undocumented files and one
asks the network, and any of the three can be missing, stale or unreachable. A
line that could not be read says why instead of being dropped, and the verdict
is drawn only from what was read - an unreachable release is "could not be
asked", never "up to date".

ADVISORY: exit 0 whenever it could answer, 1 when a newer release is published
(so a script can ask), 2 on a usage error. Never a gate.

Usage:
  audit-version.py [--offline] [--json]
"""
import json
import os
import re
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

import _claude_home as _home  # noqa: E402  (Claude Code's own install records, fail-open)

E_OK, E_NEWER, E_USAGE = 0, 1, 2
RELEASES_API = "https://api.github.com/repos/%s/%s/releases/latest"
FETCH_TIMEOUT = 5                  # seconds: the one network call waits no longer


# --- reading ---------------------------------------------------------------------
# The Claude-home readers live one layer down in `_claude_home`, where the doctor
# reaches them too; these names are that module's, not copies of it.
claude_home = _home.claude_home
marketplace_of = _home.marketplace_of
marketplace_facts = _home.marketplace_facts
installed_copies = _home.installed_copies
read_json = _home.read_json
PLUGIN_NAME = _home.PLUGIN_NAME


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)"
                     r"(?:-([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*))?"
                     r"(?:\+[0-9A-Za-z.-]+)?$")


def parse_version(text):
    """A version as semver orders it, or None for anything that is not one.

    `v3.1.0`, `3.1.0-beta.2`, `3.1.0+build.7`. A pre-release sorts BEFORE its
    release - a running `3.1.0-beta` is not up to date with a published `3.1.0` -
    its identifiers numerically where they are numbers and a number before a word;
    build metadata does not order at all. Anything else after the numbers is not a
    version, and a caller reports that rather than comparing it to a default."""
    m = _SEMVER.match(str(text or "").strip())
    if not m:
        return None
    core = tuple(int(g) for g in m.groups()[:3])
    if m.group(4) is None:
        return core + ((1,),)
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p)
                for p in m.group(4).split("."))
    return core + ((0,) + ids,)


def running(plugin_root=None):
    """The copy this command runs from: its version and where it was read."""
    root = plugin_root or _output.PLUGIN_ROOT
    path = os.path.join(root, ".claude-plugin", "plugin.json")
    doc, why = read_json(path)
    version = (doc or {}).get("version") if isinstance(doc, dict) else None
    return {"version": version if isinstance(version, str) else None,
            "root": root, "basis": path if doc is not None else why,
            "repository": (doc or {}).get("repository")
            if isinstance(doc, dict) else None}


def _github_repo(repository):
    m = re.match(r"^https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
                 str(repository or "").strip())
    return (m.group(1), m.group(2)) if m else None


def _http_get_json(url, timeout):
    """GET `url` and parse it. Imported here: only a run that asks the network
    pays for the HTTP stack."""
    import urllib.request
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "quality-gates-audit-version"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_release(repository, fetch=None, timeout=FETCH_TIMEOUT):
    """The newest published release of `repository`, or why it could not be asked."""
    repo = _github_repo(repository)
    if repo is None:
        return {"error": "plugin.json's repository (%r) is not a GitHub URL, so "
                         "there is no release feed to ask" % (repository,)}
    url = RELEASES_API % repo
    try:
        doc = (fetch or _http_get_json)(url, timeout)
    except Exception as exc:
        return {"error": "%s could not be asked (%s)" % (url, exc)}
    tag = doc.get("tag_name") if isinstance(doc, dict) else None
    if not isinstance(tag, str) or parse_version(tag) is None:
        return {"error": "%s answered no release tag that reads as a version" % url}
    return {"tag": tag, "publishedAt": doc.get("published_at"),
            "url": doc.get("html_url"), "basis": "the GitHub releases API (%s)" % url}


# --- deciding ------------------------------------------------------------------
def verdict(run, market, published):
    """(exit, sentence) from what was READ - never from a default."""
    have = parse_version(run.get("version"))
    newest = parse_version((published or {}).get("tag"))
    if have is None:
        return E_OK, "the running version could not be read, so nothing is compared"
    if newest is None:
        offered = parse_version((market or {}).get("offered"))
        if offered is not None and offered > have:
            return E_NEWER, ("the marketplace clone already offers %s - the "
                             "published release could not be asked"
                             % (market.get("offered"),))
        return E_OK, ("the newest published release could not be asked, so "
                      "whether this is the newest is not known")
    if newest > have:
        return E_NEWER, "a newer release is published: %s" % (published["tag"],)
    if newest < have:
        return E_OK, ("running ahead of the newest published release (%s) - an "
                      "unreleased build" % (published["tag"],))
    return E_OK, "up to date with the newest published release"


def update_steps(market_name, newer):
    """The documented commands, named for this marketplace."""
    if not market_name or not newer:
        return []
    return ["claude plugin marketplace update %s" % market_name,
            "claude plugin update %s@%s" % (PLUGIN_NAME, market_name),
            "then restart Claude Code (or run /reload-plugins)"]


def collect(offline=False, fetch=None, home=None, plugin_root=None):
    """Every fact this command reports, each with its basis."""
    home = home or claude_home()
    run = running(plugin_root)
    name, name_basis = marketplace_of(run["root"], home)
    market = marketplace_facts(home, name) if name else None
    copies, copies_why = installed_copies(home, name) if name else (None, "")
    published = ({"error": "not asked: --offline"} if offline
                 else latest_release(run.get("repository"), fetch=fetch))
    code, sentence = verdict(run, market, published)
    return {"running": run, "marketplaceName": name,
            "marketplaceBasis": name_basis, "marketplace": market,
            "installed": copies, "installedWhy": copies_why,
            "published": published, "verdict": sentence, "exit": code,
            "update": update_steps(name, code == E_NEWER)}


# --- rendering -----------------------------------------------------------------
def render(facts):
    run, market, pub = facts["running"], facts["marketplace"], facts["published"]
    lines = ["audit plugin version",
             "  running      %s   (%s)" % (run.get("version") or "unknown",
                                          run.get("basis"))]
    if market is None:
        lines.append("  marketplace  none - %s" % (facts["marketplaceBasis"],))
    elif market.get("error"):
        lines.append("  marketplace  %s - %s" % (market["name"], market["error"]))
    else:
        auto = market.get("autoUpdate")
        lines.append("  marketplace  %s offers %s - refreshed %s, auto-update %s   "
                     "(%s)" % (market["name"], market.get("offered") or "unknown",
                               market.get("lastUpdated") or "never recorded",
                               "on" if auto is True else ("off" if auto is False
                                                          else "not recorded"),
                               market["basis"]))
        if market.get("offeredWhy"):
            lines.append("               offered version: %s" % market["offeredWhy"])
    have = parse_version(run.get("version"))
    for copy in facts.get("installed") or []:
        theirs = parse_version(copy.get("version"))
        # NO DEFAULT FOR A VERSION THAT DOES NOT READ AS ONE: it is not older, it is
        # not comparable, and the line says which.
        if theirs is None:
            mark = "  (version not comparable)"
        elif have is not None and theirs < have:
            mark = "  (older than the running copy)"
        else:
            mark = ""
        lines.append("  installed    %s %s%s%s" % (
            copy.get("scope") or "?", copy.get("version") or "?",
            (" in %s" % copy["project"]) if copy.get("project") else "", mark))
    if facts.get("installedWhy"):
        lines.append("  installed    %s" % facts["installedWhy"])
    if pub.get("error"):
        lines.append("  published    %s" % pub["error"])
    else:
        lines.append("  published    %s, %s - %s   (%s)" % (
            pub["tag"], (pub.get("publishedAt") or "undated")[:10],
            pub.get("url") or "", pub["basis"]))
    lines.append("  verdict      %s" % facts["verdict"])
    for step in facts["update"]:
        lines.append("    %s" % step)
    if market and market.get("autoUpdate") is False:
        lines.append("  auto-update is off for %s: turn it on in /plugin > "
                     "Marketplaces, or set \"autoUpdate\": true on the marketplace "
                     "in settings" % (market["name"],))
    return "\n".join(lines)


def main(argv, fetch=None, home=None, plugin_root=None, out=print):
    args = list(argv)
    unknown = [a for a in args if a not in ("--offline", "--json")]
    if unknown:
        sys.stderr.write("usage: audit-version.py [--offline] [--json] "
                         "(unknown: %s)\n" % " ".join(unknown))
        return E_USAGE
    facts = collect(offline="--offline" in args, fetch=fetch, home=home,
                    plugin_root=plugin_root)
    out(json.dumps(facts, indent=1, sort_keys=True) if "--json" in args
        else render(facts))
    return facts["exit"]


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("audit-version.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_audit_version.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
