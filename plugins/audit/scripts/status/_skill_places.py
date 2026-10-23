#!/usr/bin/env python3
"""
Where a named skill lives - the one answer, asked by the launcher that loads a task's
skills into the session it starts (`run-agent-session.py`) and by `/audit:doctor`'s
check of the skill names a plan uses (`_doctor_policy.check_plan_skills`).

WHY ONE FUNCTION. The launcher searched the project, then the user's directory; doctor
asked a machine-wide scan whether the name existed anywhere. Two answers to one
question is how doctor goes green over a name the launcher then refuses to start with,
or the reverse - and the order they disagreed about was the one thing Claude Code
documents. Docs, code.claude.com/docs/en/skills, "Resolve skills that share a name":
"Enterprise over personal, and personal over project", with plugin skills namespaced
`plugin-name:skill-name` beside the local ones. The docs say nothing about a local skill
shadowing a plugin's, so a `plugin:skill` name is read from that plugin only: falling
back to a personal or project skill of the same bare name would load something the plan
did not name.

THE ORDER for a bare name is the user's skills (`<claude home>/skills`), the tree's
`.claude/skills`, then the running plugin's own `skills/`. The enterprise tier is not
searched: nothing here can read where a managed install keeps it, and it would outrank
the first of these.

NO SECOND MODE. Doctor once passed the machine-wide scan as a wider fallback, so a bare
name that was only some other installed plugin's skill resolved in doctor and was
refused by the launcher - the green-then-refused shape this module exists to remove. A
session loads a bare name from the places above and nothing else, so there is exactly
one answer and both callers read it. What the scan can still add is a sentence
about a name this refuses; that is doctor's wording and stays there.

Nothing here reads the environment: the home, the tree and the plugin root arrive as
arguments, and `_claude_home.claude_home()` is how a caller finds the first of them.
This module carries no `--selftest` of its own; its cases live in
`tests/test__skill_places.py`.
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

# A skill name, or either half of `plugin:skill`. It becomes a directory name under
# three roots, so a separator, a dot-only name or a leading dot never reaches a path.
SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# --- the running plugin ----------------------------------------------------------
def plugin_name(plugin_root):
    """The name in the plugin's own manifest, or None when it cannot be read - then
    no `plugin:skill` name matches, and a caller says so."""
    path = os.path.join(plugin_root, ".claude-plugin", "plugin.json")
    try:
        with open(path, encoding="utf-8") as fh:
            name = json.load(fh).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name else None


# --- where a name can live -------------------------------------------------------
def _labelled_places(name, tree, user_home, plugin_root, running):
    """`([(source, path), ...], problem)`: the SKILL.md paths for `name`, in the
    order they win, each beside the tier it belongs to - or the reason the name is no
    skill name at all."""
    head, sep, tail = name.partition(":")
    parts = [head, tail] if sep else [head]
    if not all(SKILL_NAME.match(p) for p in parts):
        return [], "%r is not a skill name (letters, digits, '.', '_' and '-', "\
                   "optionally as plugin:skill)" % name
    own = ("plugin", os.path.join(plugin_root, "skills", parts[-1], "SKILL.md"))
    if sep:
        return ([own] if head == running else []), None
    return [("personal", os.path.join(user_home, "skills", name, "SKILL.md")),
            ("project", os.path.join(tree, ".claude", "skills", name, "SKILL.md")),
            own], None


def skill_places(name, tree, user_home, plugin_root, running):
    """`(places, problem)`: the SKILL.md paths a session in `tree` would read `name`
    from, in the order it prefers them, or the reason `name` is no skill name. A
    qualified name has one place when its plugin is the running one and none when it
    is not."""
    labelled, problem = _labelled_places(name, tree, user_home, plugin_root, running)
    return [path for _source, path in labelled], problem


def resolve_skill(name, tree, user_home, plugin_root, running):
    """`{"found", "path", "source", "places", "problem"}` for one name.

    `found` is the answer; `path` is the SKILL.md it was found at; `source` is
    `personal`, `project` or `plugin`. `places` is every path looked in, in order, so
    a refusal can name them, and `problem` is the reason the name is no skill name -
    `found` is then False. A name nothing holds has `found` False and `problem` None:
    two different answers, kept apart.
    """
    labelled, problem = _labelled_places(name, tree, user_home, plugin_root, running)
    places = [path for _source, path in labelled]
    if problem:
        return {"found": False, "path": None, "source": None, "places": [],
                "problem": problem}
    for source, path in labelled:
        if os.path.isfile(path):
            return {"found": True, "path": path, "source": source, "places": places,
                    "problem": None}
    return {"found": False, "path": None, "source": None, "places": places,
            "problem": None}
