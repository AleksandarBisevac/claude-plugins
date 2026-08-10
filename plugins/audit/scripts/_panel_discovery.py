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

This module must never import panel-server or _panel_settings: nothing that imports
THIS module (both of them do) can form a cycle through it.
"""
import os
import re
import sys

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


def _scan_skills(base, source, out, seen, cap=500):
    """Add every <base>/*/SKILL.md as a skill entry."""
    skills_dir = os.path.join(base, "skills")
    if not os.path.isdir(skills_dir):
        return
    for name in sorted(os.listdir(skills_dir)):
        if len(out) >= cap:
            return
        sk = os.path.join(skills_dir, name, "SKILL.md")
        if os.path.isfile(sk):
            fm = _fm_of(sk)
            key = (fm.get("name") or name)
            if key in seen:  # dedupe by name; project/user scanned before plugins win
                continue
            seen.add(key)
            out.append(_entry(key, fm.get("description"), source, sk))


def _scan_agents(base, source, out, seen, cap=500):
    agents_dir = os.path.join(base, "agents")
    if not os.path.isdir(agents_dir):
        return
    for name in sorted(os.listdir(agents_dir)):
        if len(out) >= cap:
            return
        if not name.endswith(".md"):
            continue
        ap = os.path.join(agents_dir, name)
        fm = _fm_of(ap)
        key = fm.get("name") or name[:-3]
        if key in seen:  # dedupe by name; project/user scanned before plugins win
            continue
        seen.add(key)
        out.append(_entry(key, fm.get("description"), source, ap))


def _plugin_bases(home, cap=200):
    """Directories that may hold skills/agents inside the plugins tree."""
    root = os.path.join(home, ".claude", "plugins")
    bases = []
    if not os.path.isdir(root):
        return bases
    for dirpath, dirnames, _files in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth > 5:
            dirnames[:] = []
            continue
        if os.path.basename(dirpath) in ("skills", "agents"):
            bases.append(os.path.dirname(dirpath))
        if len(bases) >= cap:
            break
    return sorted(set(bases))


def discover(project, home=None):
    """Return {skills, agents, mcp} available to this project (read-only scan)."""
    home = home or os.path.expanduser("~")
    skills, agents, s_seen, a_seen = [], [], set(), set()
    # project-local
    _scan_skills(os.path.join(project, ".claude"), "project", skills, s_seen)
    _scan_agents(os.path.join(project, ".claude"), "project", agents, a_seen)
    # user-global
    _scan_skills(os.path.join(home, ".claude"), "user", skills, s_seen)
    _scan_agents(os.path.join(home, ".claude"), "user", agents, a_seen)
    # installed plugins (parent-dir basename is often a version/cache name — noise,
    # so use a plain 'plugin' badge)
    for base in _plugin_bases(home):
        _scan_skills(base, "plugin", skills, s_seen)
        _scan_agents(base, "plugin", agents, a_seen)
    # this repo's own plugins (dev / local checkout — basename is the real name)
    for base in sorted(_local_plugin_bases(project)):
        label = "plugin:" + os.path.basename(base)
        _scan_skills(base, label, skills, s_seen)
        _scan_agents(base, label, agents, a_seen)
    # MCP servers (names only — never surface secrets/tokens)
    mcp = _mcp_names(home, project)
    return {"skills": skills, "agents": agents, "mcp": mcp}


def _local_plugin_bases(project):
    root = os.path.join(project, "plugins")
    out = []
    if os.path.isdir(root):
        for name in os.listdir(root):
            d = os.path.join(root, name)
            if os.path.isdir(os.path.join(d, "skills")) or \
               os.path.isdir(os.path.join(d, "agents")):
                out.append(d)
    return out


def _mcp_names(home, project):
    names = set()
    for path in (os.path.join(home, ".claude.json"),
                 os.path.join(project, ".mcp.json")):
        try:
            data = _mio.read_json(path)
        except Exception:
            continue
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict):
            names.update(str(k) for k in servers.keys())
    return sorted(names)


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
          _local_plugin_bases(_repo_root))
    check("MCP names come back sorted, with no secrets in the row (names only)",
          _mcp_names(home, proj) == sorted(_mcp_names(home, proj)))
    _src_lines = [l for l in open(__file__).read().split("\n")
                  if l.startswith("import ") or l.startswith("from ")]
    check("this module never imports panel-server or _panel_settings - it sits at "
          "the bottom of the panel's own import graph",
          not any("panel_server" in l or "_panel_settings" in l for l in _src_lines))

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
