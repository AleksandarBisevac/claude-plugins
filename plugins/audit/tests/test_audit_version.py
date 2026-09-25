#!/usr/bin/env python3
"""
The cases for `audit-version.py` - which build is running, and whether a newer
one is published.

WHAT IS PINNED, and why each one is here rather than trusted:

- **Every fact carries where it was read, and a fact that could not be read says
  why.** Two of the sources are files Claude Code writes and does not document,
  and one is the network; each can be missing, malformed or unreachable, and a
  line that silently vanished would read as "nothing to report".
- **The verdict is drawn only from what was read.** An unreachable release feed
  is "could not be asked", never "up to date" - the default this command must
  not fall back to.
- **--offline never touches the network**, proven by a fetch that fails the case
  if it is called at all.
- **The update commands appear only when a newer release is known and the
  marketplace is known**, named for that marketplace.

No case reads the real Claude home or the network: the home is a fixture tree
and the fetch is injected.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (entry points load by name)

M = _loader.load_script("audit-version.py")


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(doc, str):
            fh.write(doc)
        else:
            json.dump(doc, fh)


def _home(root, auto=True, offered="3.1.0", copies=None, market="quality-gates"):
    """A Claude home holding a marketplace clone, its record and install records.
    Returns (home, installed plugin root)."""
    home = os.path.join(root, "claude-home")
    clone = os.path.join(home, "plugins", "marketplaces", market)
    _write(os.path.join(clone, ".claude-plugin", "marketplace.json"),
           {"name": market, "plugins": [{"name": "audit", "source": "./plugins/audit"}]})
    _write(os.path.join(clone, "plugins", "audit", ".claude-plugin", "plugin.json"),
           {"name": "audit", "version": offered})
    _write(os.path.join(home, "plugins", "known_marketplaces.json"),
           {market: {"installLocation": clone, "lastUpdated": "2026-09-24T10:42:01Z",
                     "autoUpdate": auto}})
    installed = os.path.join(home, "plugins", "cache", market, "audit", "3.0.1")
    _write(os.path.join(installed, ".claude-plugin", "plugin.json"),
           {"name": "audit", "version": "3.0.1",
            "repository": "https://github.com/owner/repo"})
    rows = copies if copies is not None else [
        {"scope": "user", "installPath": installed, "version": "3.0.1"},
        {"scope": "project", "projectPath": "/work/old", "installPath": "/x",
         "version": "2.0.1"}]
    _write(os.path.join(home, "plugins", "installed_plugins.json"),
           {"version": 2, "plugins": {"audit@%s" % market: rows}})
    return home, installed


def _release(tag="v3.1.0"):
    def fetch(url, timeout):
        return {"tag_name": tag, "published_at": "2026-09-30T00:00:00Z",
                "html_url": "https://github.com/owner/repo/releases/tag/" + tag}
    return fetch


def _cases(check):
    root = _harness.fixture_root("audit-version")
    try:
        home, plug = _home(root)

        run = M.running(plug)
        check("v1 the running version is read from the copy's own plugin.json, and "
              "the line names that file: %r" % (run,),
              run["version"] == "3.0.1" and run["basis"].endswith("plugin.json"))
        gone = M.running(os.path.join(root, "nowhere"))
        check("v1b ...and a copy whose plugin.json cannot be read reports no version "
              "and says why, instead of guessing one: %r" % (gone["basis"],),
              gone["version"] is None and "could not be read" in gone["basis"])

        check("v2 versions compare as numbers, with or without a leading v, and a "
              "tag that is not a version is None",
              M.parse_version("v3.10.0") > M.parse_version("3.9.1")
              and M.parse_version("release-candidate") is None)

        name, basis = M.marketplace_of(plug, home)
        check("v3 the marketplace is found from Claude Code's install record for this "
              "exact path: %r" % ((name, basis),),
              name == "quality-gates" and "installed_plugins.json" in basis)
        home2, plug2 = _home(os.path.join(root, "bycache"), copies=[])
        name2, basis2 = M.marketplace_of(plug2, home2)
        check("v3b ...else from the cache path the copy sits in: %r" % ((name2, basis2),),
              name2 == "quality-gates" and "cache path" in basis2)
        name3, basis3 = M.marketplace_of(os.path.join(root, "checkout"), home)
        check("v3c ...and a copy run from a checkout names no marketplace and says "
              "where it runs from: %r" % (basis3,),
              name3 is None and "not from an installed marketplace copy" in basis3)

        mk = M.marketplace_facts(home, "quality-gates")
        check("v4 the marketplace line reads what the clone OFFERS, when it was "
              "refreshed and whether it auto-updates, naming the undocumented file: %r"
              % (mk,),
              mk["offered"] == "3.1.0" and mk["autoUpdate"] is True
              and mk["lastUpdated"] and "does not document" in mk["basis"])
        check("v4b ...a marketplace the record does not hold is an error that names "
              "it, not an empty line",
              "has no 'other'" in M.marketplace_facts(home, "other").get("error", ""))
        broken = os.path.join(root, "broken-home")
        _write(os.path.join(broken, "plugins", "known_marketplaces.json"), "{not json")
        check("v4c ...and a malformed record says it is not JSON",
              "not JSON" in M.marketplace_facts(broken, "quality-gates")["error"])

        copies, why = M.installed_copies(home, "quality-gates")
        check("v5 every installed copy is listed by scope, project and version",
              [(c["scope"], c["version"]) for c in copies]
              == [("user", "3.0.1"), ("project", "2.0.1")] and why == "")
        check("v5b ...and an unreadable install record says why",
              M.installed_copies(os.path.join(root, "empty"), "quality-gates")[0] is None)

        pub = M.latest_release("https://github.com/owner/repo", fetch=_release())
        check("v6 the newest release is read from the repository plugin.json names, "
              "with the API it asked: %r" % (pub,),
              pub["tag"] == "v3.1.0" and "api.github.com/repos/owner/repo" in pub["basis"])

        def down(url, timeout):
            raise OSError("network is unreachable")
        err = M.latest_release("https://github.com/owner/repo", fetch=down)
        check("v6b ...an unreachable feed is named with the URL and the reason: %r"
              % (err,),
              "could not be asked" in err["error"] and "unreachable" in err["error"])
        check("v6c ...a repository that is not on GitHub has no feed, and says so",
              "not a GitHub URL" in M.latest_release("https://example.org/x",
                                                    fetch=_release())["error"])
        check("v6d ...and a release whose tag is not a version is refused, not "
              "compared",
              "error" in M.latest_release("https://github.com/owner/repo",
                                          fetch=_release("nightly")))

        v = M.verdict
        check("v7 equal versions are up to date",
              v({"version": "3.1.0"}, None, {"tag": "v3.1.0"})
              == (M.E_OK, "up to date with the newest published release"))
        check("v7b a newer published release exits 1 and names the tag",
              v({"version": "3.0.1"}, None, {"tag": "v3.1.0"})[0] == M.E_NEWER
              and "v3.1.0" in v({"version": "3.0.1"}, None, {"tag": "v3.1.0"})[1])
        check("v7c a build ahead of the newest release says it is unreleased",
              "ahead" in v({"version": "3.2.0"}, None, {"tag": "v3.1.0"})[1])
        unknown = v({"version": "3.0.1"}, {"offered": "3.0.1"}, {"error": "x"})
        check("v7d SECOND DIRECTION: an unanswered feed is NEVER up to date - it says "
              "the question could not be asked: %r" % (unknown,),
              unknown[0] == M.E_OK and "could not be asked" in unknown[1]
              and "up to date" not in unknown[1])
        check("v7e ...unless the marketplace clone already offers a newer version, "
              "which is itself the answer",
              v({"version": "3.0.1"}, {"offered": "3.1.0"}, {"error": "x"})[0]
              == M.E_NEWER)

        def forbidden(url, timeout):
            raise AssertionError("--offline asked the network")
        off = M.collect(offline=True, fetch=forbidden, home=home, plugin_root=plug)
        check("v8 --offline never calls the network, and says the release was not "
              "asked: %r" % (off["published"],),
              off["published"] == {"error": "not asked: --offline"})

        facts = M.collect(fetch=_release(), home=home, plugin_root=plug)
        text = M.render(facts)
        check("v9 a newer release prints the documented update commands, named for "
              "this marketplace:\n%s" % (text,),
              "claude plugin marketplace update quality-gates" in text
              and "claude plugin update audit@quality-gates" in text)
        check("v9b ...and an older installed copy is flagged as older",
              "2.0.1 in /work/old  (older than the running copy)" in text)
        same = M.render(M.collect(fetch=_release("v3.0.1"), home=home, plugin_root=plug))
        check("v9c SECOND DIRECTION: up to date prints no update commands",
              "claude plugin update" not in same)
        home_off, plug_off = _home(os.path.join(root, "autooff"), auto=False)
        off_text = M.render(M.collect(fetch=_release(), home=home_off,
                                      plugin_root=plug_off))
        check("v9d auto-update OFF says how to turn it on; ON says nothing of the kind",
              "auto-update is off for quality-gates" in off_text
              and "auto-update is off" not in text)

        lines = []
        code = M.main(["--json"], fetch=_release(), home=home, plugin_root=plug,
                      out=lines.append)
        doc = json.loads(lines[0])
        check("v10 --json is one parseable object carrying every fact and the exit "
              "it returned: %r" % (sorted(doc),),
              code == M.E_NEWER and doc["exit"] == code
              and {"running", "marketplace", "installed", "published", "verdict",
                   "update"} <= set(doc))
        check("v10b an unknown flag is a usage error",
              M.main(["--frobnicate"], fetch=_release(), home=home,
                     plugin_root=plug, out=lambda _s: None) == M.E_USAGE)

        env_home = M.claude_home({"CLAUDE_CONFIG_DIR": "/custom/home"})
        check("v11 CLAUDE_CONFIG_DIR moves the Claude home, as Claude Code honours it",
              env_home == "/custom/home"
              and M.claude_home({}).endswith(os.path.join("", ".claude")))
    finally:
        _harness.remove_tree(root)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_version.py --selftest\n")
