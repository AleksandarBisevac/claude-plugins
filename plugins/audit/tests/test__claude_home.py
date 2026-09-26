#!/usr/bin/env python3
"""
The cases for `_claude_home.py` - Claude Code's own install records, read in one
place so `/audit:version` and `/audit:doctor` cannot come to read them apart.

Both files are undocumented, so what is pinned is the fail-open contract: a record
that is missing, malformed or shaped differently comes back as None beside a
sentence naming why, never as an empty answer that reads like "nothing
installed". No case reads the real Claude home: every home is a fixture tree.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _claude_home as M                           # noqa: E402
import _loader                                     # noqa: E402

V = _loader.load_script("audit-version.py", modname="audit_version_for_home")


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(doc, str):
            fh.write(doc)
        else:
            json.dump(doc, fh)


def _home(root, source="./plugins/audit", sha="a" * 40):
    home = os.path.join(root, "claude-home")
    clone = os.path.join(home, "plugins", "marketplaces", "qg")
    _write(os.path.join(clone, ".claude-plugin", "marketplace.json"),
           {"plugins": [{"name": "audit", "source": source}]})
    _write(os.path.join(home, "plugins", "known_marketplaces.json"),
           {"qg": {"installLocation": clone}})
    cache = os.path.join(home, "plugins", "cache", "qg", "audit", "1.0.0")
    os.makedirs(cache)
    _write(os.path.join(home, "plugins", "installed_plugins.json"),
           {"version": 2, "plugins": {"audit@qg": [
               {"scope": "project", "projectPath": "/elsewhere",
                "installPath": "/somewhere/else", "gitCommitSha": "b" * 40},
               {"scope": "user", "installPath": cache, "version": "1.0.0",
                "gitCommitSha": sha}]}})
    return home, cache, clone


def _cases(check):
    root = _harness.fixture_root("claude-home-")
    home, cache, clone = _home(root)

    rec, why = M.install_record(cache, home)
    check("ch1 the install record is the one naming THIS copy's path, carrying "
          "its marketplace and recorded commit - not the first record for the "
          "plugin, which names another project's copy: %r" % ((rec, why),),
          rec is not None and rec["marketplace"] == "qg"
          and rec["gitCommitSha"] == "a" * 40 and why == "")
    miss, why = M.install_record(os.path.join(root, "unrecorded"), home)
    check("ch2 a copy no record names is None beside a sentence saying so: %r"
          % ((miss, why),),
          miss is None and "records no install" in why)
    gone, why = M.install_record(cache, os.path.join(root, "no-home"))
    check("ch3 FAIL-OPEN: a home with no installed_plugins.json is None beside "
          "the read's own reason, never an empty record: %r" % ((gone, why),),
          gone is None and "could not be read" in why)
    _write(os.path.join(root, "torn", "plugins", "installed_plugins.json"), "{ no")
    torn, why = M.install_record(cache, os.path.join(root, "torn"))
    check("ch4 ...and a malformed one says it is not JSON: %r" % ((torn, why),),
          torn is None and "not JSON" in why)

    got = M.marketplace_source(home, "qg")
    check("ch5 the marketplace source is the clone known_marketplaces.json names "
          "and the plugin's directory inside it, normalised to a git pathspec: %r"
          % (got,),
          got == (clone, "plugins/audit", ""))
    unknown = M.marketplace_source(home, "nope")
    check("ch6 a marketplace the record does not know is None beside why: %r"
          % (unknown,),
          unknown[0] is None and "nope" in unknown[2])
    home_root, _c, _cl = _home(os.path.join(root, "rooted"), source=".")
    check("ch7 a plugin published at the clone's root is the empty subdirectory, "
          "which archives the whole commit rather than a directory named '.': %r"
          % (M.marketplace_source(home_root, "qg"),),
          M.marketplace_source(home_root, "qg")[1] == "")

    moved = [name for name in ("claude_home", "marketplace_of",
                               "marketplace_facts", "installed_copies",
                               "read_json", "PLUGIN_NAME")
             if getattr(V, name, None) is not getattr(M, name)]
    check("ch8 `/audit:version` reads through THIS module rather than a copy of "
          "it - every reader it names is this module's own object, so the two "
          "commands cannot come to read the records apart: %r" % (moved,),
          moved == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__claude_home.py --selftest\n")
    raise SystemExit(2)
