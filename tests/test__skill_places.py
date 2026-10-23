#!/usr/bin/env python3
"""
The cases for `_skill_places.py` - the one answer to "where does a named skill live",
asked by the launcher that loads a task's skills into a session and by
`/audit:doctor`'s check of the names a plan uses.

What is pinned is the order and the refusals, each with a fixture that tells the
right reading from the wrong one: the same name written into the personal AND the
project directory with different bodies, so a resolver that took the wrong one of the
two returns the other's path; a plugin skill of the same bare name beside them, so a
`plugin:skill` that fell back to them is visible.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _skill_places as M                          # noqa: E402


def _put(base, name, body="body\n"):
    folder = os.path.join(base, name)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "SKILL.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    return path


def _cases(check):
    root = _harness.fixture_root("skill-places")
    tree = os.path.join(root, "tree")
    home = os.path.join(root, "home")
    plugin = os.path.join(root, "plugin")
    personal = _put(os.path.join(home, "skills"), "both", "PERSONAL\n")
    project = _put(os.path.join(tree, ".claude", "skills"), "both", "PROJECT\n")
    _put(os.path.join(home, "skills"), "only-personal")
    _put(os.path.join(tree, ".claude", "skills"), "only-project")
    own = _put(os.path.join(plugin, "skills"), "both", "PLUGIN\n")
    own_only = _put(os.path.join(plugin, "skills"), "only-plugin")

    def where(name, running="house"):
        return M.resolve_skill(name, tree, home, plugin, running)

    check("sp1 the places of a bare name are the personal skills, then the project's, "
          "then the running plugin's - Claude Code's documented 'personal over "
          "project', with the plugin last",
          M.skill_places("both", tree, home, plugin, "house")
          == ([personal, project, own], None))
    got = where("both")
    check("sp2 a name held by all three resolves to the PERSONAL copy: %r" % (got,),
          got["path"] == personal and got["source"] == "personal"
          and got["problem"] is None)
    check("sp3 ...and with the personal copy gone the project's is next, then the "
          "plugin's: the order is one a missing file walks down, not a pick",
          (os.remove(personal), where("both")["path"])[1] == project
          and (os.remove(project), where("both")["path"])[1] == own)
    check("sp4 a name only the project holds, and one only the plugin holds, resolve "
          "from there",
          where("only-project")["source"] == "project"
          and where("only-plugin")["path"] == own_only
          and where("only-plugin")["source"] == "plugin")
    check("sp5 a name that is nowhere resolves to NO path and says every place "
          "looked in, in order: %r" % (where("ghost"),),
          where("ghost")["path"] is None and where("ghost")["problem"] is None
          and len(where("ghost")["places"]) == 3
          and where("ghost")["places"][0].startswith(home))

    # --- plugin:skill -----------------------------------------------------------
    _put(os.path.join(home, "skills"), "only-plugin", "SHADOW\n")
    _put(os.path.join(tree, ".claude", "skills"), "only-plugin", "SHADOW\n")
    q = where("house:only-plugin")
    check("sp6 `plugin:skill` resolves from that plugin alone, although a personal "
          "and a project skill of the same bare name exist: %r" % (q,),
          q["path"] == own_only and q["source"] == "plugin")
    other = where("elsewhere:only-plugin")
    check("sp7 ...and another plugin's name resolves to nothing, with the shadows "
          "left unused: %r" % (other,),
          other["path"] is None and other["places"] == [])
    check("sp8 a running plugin whose name could not be read matches no qualified "
          "name",
          where("house:only-plugin", running=None)["path"] is None)

    # --- the names that are no skill name ---------------------------------------
    bad = [where(n)["problem"] for n in ("../escape", "a/b", ".hidden", "", "a:", ":b",
                                         "a:b:c")]
    check("sp9 a name that could leave the skills directories or is empty is a "
          "PROBLEM, never a path: %r" % (bad,), all(bad))

    # --- the scan inventory is the wider mode -----------------------------------
    gone = where("scanned")
    check("sp10 a bare name no directory holds is NOT found, however many other "
          "installed plugins ship it: there is one answer and no wider mode: %r"
          % (gone,),
          gone["found"] is False and gone["path"] is None and gone["source"] is None
          and gone["problem"] is None and len(gone["places"]) == 3)
    try:
        M.resolve_skill("scanned", tree, home, plugin, "house", inventory={})
        widened = True
    except TypeError:
        widened = False
    check("sp11 ...and the resolver takes no inventory argument, so a caller cannot "
          "ask for a second answer", not widened)
    seen_sources = set(where(n)["source"] for n in (
        "only-project", "only-personal", "only-plugin", "house:only-plugin", "scanned"))
    check("sp12 the only sources the resolver ever names are the three tiers (or "
          "none, for a name nothing holds): %r" % (sorted(seen_sources, key=str),),
          seen_sources == set(["project", "personal", "plugin", None]))

    # --- the running plugin's name ----------------------------------------------
    manifest = os.path.join(plugin, ".claude-plugin", "plugin.json")
    os.makedirs(os.path.dirname(manifest))
    check("sp14 an unreadable plugin.json gives no name rather than a guess",
          M.plugin_name(plugin) is None)
    with open(manifest, "w", encoding="utf-8") as fh:
        fh.write('{"name": "house"}')
    check("sp15 ...and a readable one gives its name", M.plugin_name(plugin) == "house")
    with open(manifest, "w", encoding="utf-8") as fh:
        fh.write('{"name": 7}')
    check("sp16 ...a name that is not a string is none", M.plugin_name(plugin) is None)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__skill_places.py --selftest\n")
    raise SystemExit(2)
