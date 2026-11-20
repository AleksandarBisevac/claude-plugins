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
import hashlib
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
def is_skill_name(name):
    """True for a bare skill name or `plugin:skill`, each half a `SKILL_NAME`."""
    if not isinstance(name, str):
        return False
    head, sep, tail = name.partition(":")
    return all(SKILL_NAME.match(p) for p in ([head, tail] if sep else [head]))


def _labelled_places(name, tree, user_home, plugin_root, running):
    """`([(source, path), ...], problem)`: the SKILL.md paths for `name`, in the
    order they win, each beside the tier it belongs to - or the reason the name is no
    skill name at all."""
    if not is_skill_name(name):
        return [], "%r is not a skill name (letters, digits, '.', '_' and '-', "\
                   "optionally as plugin:skill)" % name
    head, sep, tail = name.partition(":")
    parts = [head, tail] if sep else [head]
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


# --- the copy a session loads, graded for a clone --------------------------------
# What each tier means for a clone of the tree, worded the way
# `_panel_discovery.grade_entry` words the same tier. That module grades what the
# machine scan saw; this grades the copy `resolve_skill` found, which is the copy a
# session loads, and the two must not disagree about one tier -
# `tests/test__skill_places.py` holds them to the same answer. A home directory
# never travels; a project skill is graded as committed, as the scan grades it; the
# plugin tier here is only ever the RUNNING plugin's own skill, which travels with
# the plugin that runs the plan.
_TIER_VERDICTS = {
    "personal": (False, "a session loads the personal copy at %s, which lives in "
                        "a home directory no clone carries"),
    "project": (True, "a session loads the project copy at %s, committed under "
                      ".claude/, so a clone gets it"),
    "plugin": (True, "a session loads the running plugin's own copy at %s, and "
                     "that plugin is what runs the plan"),
}


def same_file(first, second):
    """True iff both paths are given and name one file, symlinks resolved. The one
    comparison of a scan entry's path against the path `resolve_skill` found."""
    if not first or not second:
        return False
    return os.path.normcase(os.path.realpath(first)) == \
        os.path.normcase(os.path.realpath(second))


def loaded_verdict(entry, hit):
    """`{"travels", "basis", "graded"}` for the copy a session loads, or None when
    no copy is known at all.

    `entry` is the machine scan's record for the name (`travels`, `travelsBasis`,
    `path`) or None; `hit` is `resolve_skill`'s answer. The scan keeps ONE copy per
    name in its own order and may read another home than the resolver, so its
    verdict can describe a file nobody loads. It stands only when it is about the
    resolved file, or when nothing resolved and the scan's copy is the only one the
    name can mean (`graded` "scan"). Otherwise the resolved file is graded by the
    tier it was found in (`graded` "tier") - a personal copy, found under another
    home or under a directory the scan read differently, does not travel, whatever
    the scan said about the copy it kept.

    `travels` is True, False or None; None is UNKNOWN and never folded into False.
    """
    found = bool(hit and hit.get("found"))
    if entry is not None and (not found
                              or same_file(entry.get("path"), hit.get("path"))):
        return {"travels": entry.get("travels"),
                "basis": entry.get("travelsBasis") or "no basis was recorded",
                "graded": "scan"}
    if not found:
        return None
    tier = _TIER_VERDICTS.get(hit.get("source"))
    if tier is None:
        return {"travels": None,
                "basis": "found at %s in the tier %r, which this grading does not "
                         "know, so whether it travels is UNKNOWN"
                         % (hit.get("path"), hit.get("source")),
                "graded": "tier"}
    return {"travels": tier[0], "basis": tier[1] % (hit.get("path"),),
            "graded": "tier"}


# --- the pinned bytes ------------------------------------------------------------
# A plan may pin a skill it names (`meta.skillPins`): `{name: {"sha256": <digest>,
# "source": <free text>}}`. The digest is of the skill's DIRECTORY - the one holding
# the SKILL.md `resolve_skill` found, so the copy judged is the copy a session would
# load - because a skill's scripts and references are as much its instructions as
# its SKILL.md.
#
# THE DIGEST. SHA-256 over the sorted lines `<relative posix path> <sha256 of the
# file>\n`, one per file under the directory, UTF-8 - the shape
# docs/research/benchmark-design.md 4.2 gives the benchmark's skill set, with three
# differences: one skill's directory rather than every copied directory at once,
# paths written with `/` on every platform, and line ends read alike. A file holding
# no NUL byte is hashed with each CRLF taken as LF, so a checkout that converted
# line endings (`core.autocrlf`, `eol=crlf`) answers the digest the pinning checkout
# did. The cost: a change that only adds or removes a CR before a LF is not seen,
# in a text file or in a binary one that happens to hold no NUL byte. A lone CR is
# kept, as git keeps it.
#
# NO DIGEST is the third answer, never a match: a file that cannot be read, a link
# leading out of the directory, a link to a directory (its files would be counted
# twice or not at all), a file name holding a line break (it would forge a line),
# or more files or bytes than `MAX_SKILL_FILES`/`MAX_SKILL_BYTES` - a directory that
# size is not a skill, and hashing it would stall every dispatch. Every file counts,
# a `__pycache__` a skill's script left behind included: a cached module is code a
# session can run.
MAX_SKILL_FILES = 1000
MAX_SKILL_BYTES = 32 * 1024 * 1024
DIGEST = re.compile(r"^[0-9a-f]{64}$")
PIN_KEYS = ("sha256", "source")
# The reader's four answers for one pinned name.
PIN_ANSWERS = ("match", "mismatch", "not-found", "unreadable")


class PinStop(ValueError):
    """A pinned skill about to be handed out is not the bytes pinned; the message
    is the stop. A ValueError because that is what the drive turns into a stop
    (`drive-phase.py one_next`), so a hand-out that raises it stops `next` there."""


def _no_digest(problem, files=0):
    return {"digest": None, "files": files, "problem": problem}


def _inside(path, root):
    """True when `path` is `root` or under it, both already real paths."""
    try:
        return os.path.commonpath([os.path.normcase(path),
                                   os.path.normcase(root)]) == os.path.normcase(root)
    except ValueError:
        return False


def _file_line(full, rel, root):
    """`(line, size, problem)` for one file of a skill's directory."""
    if "\n" in rel or "\r" in rel:
        return None, 0, "the file name %r holds a line break" % (rel,)
    if os.path.islink(full) and not _inside(os.path.realpath(full), root):
        return None, 0, "%s is a link leading out of the directory, to %s" % (
            rel, os.path.realpath(full))
    try:
        with open(full, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return None, 0, "%s could not be read: %s" % (rel, exc)
    data = raw if b"\0" in raw else raw.replace(b"\r\n", b"\n")
    return "%s %s\n" % (rel, hashlib.sha256(data).hexdigest()), len(raw), None


def skill_digest(folder, max_files=MAX_SKILL_FILES, max_bytes=MAX_SKILL_BYTES):
    """`{"digest", "files", "problem"}` for a skill's directory: the digest
    defined above, or None with the reason the directory has none."""
    root = os.path.realpath(folder)
    if not os.path.isdir(root):
        return _no_digest("%s is not a directory" % (folder,))
    lines, size, failed = [], 0, []
    for here, dirs, files in os.walk(root, onerror=failed.append):
        for name in sorted(dirs):
            if os.path.islink(os.path.join(here, name)):
                return _no_digest("%s is a link to a directory" % (os.path.relpath(
                    os.path.join(here, name), root).replace(os.sep, "/"),), len(lines))
        for name in sorted(files):
            full = os.path.join(here, name)
            line, raw, problem = _file_line(
                full, os.path.relpath(full, root).replace(os.sep, "/"), root)
            if problem:
                return _no_digest(problem, len(lines))
            lines.append(line)
            size += raw
            if len(lines) > max_files:
                return _no_digest("more than %d files - more than a skill holds"
                                  % (max_files,), len(lines))
            if size > max_bytes:
                return _no_digest("more than %d bytes - more than a skill holds"
                                  % (max_bytes,), len(lines))
    if failed:
        return _no_digest("a directory under it could not be listed: %s"
                          % (failed[0],), len(lines))
    joined = "".join(sorted(lines)).encode("utf-8")
    return {"digest": hashlib.sha256(joined).hexdigest(), "files": len(lines),
            "problem": None}


def pin_verdict(name, pin, tree, user_home, plugin_root, running):
    """The one reader of one pin: `{"name", "answer", "path", "places", "pinned",
    "found", "source", "problem"}`. `answer` is one of `PIN_ANSWERS`; `path` is the
    SKILL.md `resolve_skill` found (None when not found), `places` every path looked
    in, `found` the directory's digest (None unless it could be read whole) and
    `problem` why there is none. A name the resolver cannot place - another
    plugin's skill, one bundled with Claude Code - is `not-found`: a pin says the
    skill is a reviewed copy on disk, and nothing here can read that one."""
    pin = pin if isinstance(pin, dict) else {}
    hit = resolve_skill(name, tree, user_home, plugin_root, running)
    base = {"name": name, "path": hit["path"], "places": hit["places"],
            "pinned": pin.get("sha256"), "found": None, "source": pin.get("source"),
            "problem": hit["problem"]}
    if not hit["found"]:
        return dict(base, answer="not-found")
    got = skill_digest(os.path.dirname(hit["path"]))
    if got["digest"] is None:
        return dict(base, answer="unreadable", problem=got["problem"])
    return dict(base, found=got["digest"],
                answer="match" if got["digest"] == base["pinned"] else "mismatch")


# The way through every stop: restore, or review and re-pin. Dropping the pin is
# deliberately not offered - it is the one remedy that makes the check say nothing.
_STOP_REMEDY = ("Restore the pinned bytes there, or review the diff and re-pin the "
                "skill to the reviewed digest in meta.skillPins; nothing was handed out.")


def stop_words(verdict):
    """The stop for one verdict that is not a match: the skill, the path read (or
    every place looked in), the pinned digest and the found one, and the remedy."""
    v = verdict
    source = " (pin source: %s)" % (v["source"],) if v.get("source") else ""
    if v["answer"] == "mismatch":
        return ("the skill %s is pinned, and the copy an agent or a session would "
                "load is not the bytes pinned: %s has digest %s, the plan pinned %s%s. %s"
                % (v["name"], v["path"], v["found"], v["pinned"], source, _STOP_REMEDY))
    if v["answer"] == "unreadable":
        return ("the skill %s is pinned to %s%s, and its directory at %s could not be "
                "read whole (%s), so it has no digest: found none. %s"
                % (v["name"], v["pinned"], source, v["path"], v["problem"],
                   _STOP_REMEDY))
    where = (", ".join(v["places"]) if v["places"] else
             v["problem"] or "no place: a plugin-qualified name is read only from "
             "the running plugin's own skills/")
    return ("the skill %s is pinned to %s%s, and no copy is found where its bytes "
            "can be read - looked in %s: found none. A pin says the skill is a "
            "reviewed copy on disk. %s" % (v["name"], v["pinned"], source, where,
                                           _STOP_REMEDY))


def pin_shape_problems(pins):
    """What makes `meta.skillPins` (`pins`) no set of pins, one sentence per pin at
    fault; [] when it is absent (None) or well-formed."""
    if pins is None:
        return []
    if not isinstance(pins, dict):
        return ["meta.skillPins is not an object of skill name to pin"]
    out = []
    for name in sorted(pins, key=str):
        value = pins[name]
        if not is_skill_name(name):
            out.append("meta.skillPins: %s is not a skill name" % (name,))
        elif not isinstance(value, dict):
            out.append("meta.skillPins: %s is not an object {sha256, source}" % (name,))
        elif sorted(set(value) - set(PIN_KEYS)):
            out.append("meta.skillPins: %s carries %s, which a pin does not have"
                       % (name, ", ".join(sorted(set(value) - set(PIN_KEYS)))))
        elif not (isinstance(value.get("sha256"), str)
                  and DIGEST.match(value["sha256"])):
            out.append("meta.skillPins: %s sha256 %r is not a SHA-256 hex digest "
                       "(64 lowercase hex characters)" % (name, value.get("sha256")))
        elif "source" in value and not isinstance(value["source"], str):
            out.append("meta.skillPins: %s source is not text" % (name,))
    return out


def skill_pins(manifest):
    """`meta.skillPins` as written, or None when the plan has no such key - the one
    reading of the key."""
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    return meta.get("skillPins") if isinstance(meta, dict) else None


def pin_stops(names, pins, tree, user_home, plugin_root):
    """The verdicts that stop a hand-out of `names`: one per PINNED name among them
    whose answer is not a match, in the order named. An unpinned name is not asked,
    and neither is a pin for a name not among `names`."""
    if not isinstance(pins, dict) or not pins:
        return []
    running = plugin_name(plugin_root)
    asked = [n for i, n in enumerate(names) if n in pins and n not in names[:i]]
    verdicts = [pin_verdict(n, pins[n], tree, user_home, plugin_root, running)
                for n in asked]
    return [v for v in verdicts if v["answer"] != "match"]


def require_pins(names, manifest, tree, user_home, plugin_root):
    """`names`, unchanged, when every pinned one among them is the bytes `manifest`
    pins; otherwise raises `PinStop` with each stop's words. A plan with no
    `meta.skillPins` asks nothing. A malformed key stops too: the validator refuses
    it, and a pin that cannot be read is no reason to hand the skill out."""
    names = list(names)
    pins = skill_pins(manifest)
    if pins is None:
        return names
    problems = pin_shape_problems(pins)
    if problems:
        raise PinStop("meta.skillPins cannot be read, so no pinned skill is handed "
                      "out: %s" % ("; ".join(problems),))
    stops = pin_stops(names, pins, tree, user_home, plugin_root)
    if stops:
        raise PinStop("\n".join(stop_words(v) for v in stops))
    return names


def pin_flags(names, manifest):
    """`--skill-pin NAME=DIGEST` for each pinned name among `names`, in order - what
    the session runner is handed beside its `--skill` flags. [] for a plan with no
    pins, so its command is the one it always was."""
    pins = skill_pins(manifest)
    if not isinstance(pins, dict):
        return []
    return [flag for i, n in enumerate(names)
            if n in pins and n not in names[:i] and isinstance(pins[n], dict)
            for flag in ("--skill-pin", "%s=%s" % (n, pins[n].get("sha256")))]
