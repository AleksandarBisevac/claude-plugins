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
import stat
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
# docs/research/benchmark-design.md 4.2 gives the benchmark's skill set, but for one
# skill's directory rather than every copied directory at once, with paths written
# with `/` on every platform, and with the line ends of the instruction files read
# alike (below).
#
# THE READER LOOKS BEFORE IT READS, so what it does is bounded by the ceilings and
# not by what the directory holds. Every entry is `lstat`ed first. Only a regular
# file - or a link that stays inside the directory and leads to one - is opened,
# without following a link and without blocking, its kind and identity checked
# again on the open descriptor, and read in chunks; any other kind (a FIFO, whose
# open blocks for ever, a socket, a device, a dangling link, a link to a directory,
# whose files would be counted twice or not at all) makes the directory unreadable,
# by name and kind, never opened. A file's size is compared with what is left of
# `MAX_SKILL_BYTES` before it is opened, and the read stops past it whatever the
# size said; every entry met - file, directory or link - counts toward
# `MAX_SKILL_ENTRIES`, a directory's listing included. A name that cannot be written
# as UTF-8 (possible on linux) or holds a line break (it would forge a line) is
# unreadable too. A directory past a ceiling is not a skill, and hashing it would
# stall every dispatch.
#
# LINE ENDINGS: AN ALLOW LIST, NOT A DENY LIST. A carriage return changes what a
# script does - `cd dir\r` fails and the script carries on in its caller's
# directory, `set -e\r` sets nothing - and a batch file needs CRLF, so the kinds of
# file whose CR must be kept are unbounded and no list of them can be complete. So
# only the instruction files have CRLF read as LF (`NORMALISED_SUFFIXES`, compared
# without regard to case: Markdown, which is read by a model, where a CR before a
# LF changes nothing it is told); every other file is hashed as its bytes, and a
# lone CR is kept everywhere. The cost: a checkout that converts line endings
# (`core.autocrlf`, `eol=crlf`) changes the digest of a skill that ships anything
# but Markdown, and the remedy is the repository's own - mark the skill's directory
# as not text for git, so no checkout converts it.
#
# NO DIGEST is the third answer, never a match. Every file counts, a `__pycache__` a
# skill's script left behind included: a cache beside its source file is code
# python runs in the source's place when the cache's header matches, so leaving
# caches out of the digest would leave a hole. That is why the plugin's own session
# runner starts its child unable to write one (`run-agent-session.py`), and why a
# mismatch names the entries a tool rather than an author writes (`TOOL_WRITTEN`).
# What the digest does not see: a file's mode (an executable bit), an empty
# directory, and a CR before a LF in a Markdown file.
MAX_SKILL_ENTRIES = 1000
MAX_SKILL_BYTES = 32 * 1024 * 1024
NORMALISED_SUFFIXES = (".md",)
_CHUNK = 64 * 1024
# What a read past the byte ceiling answers, worded once by `skill_digest`: a
# value no reason sentence can be.
_OVER = object()
# The entries a tool rather than an author writes, by name at any depth, with what
# to do about each. Each is still counted (above); a mismatch names the ones found.
TOOL_WRITTEN = (
    ("__pycache__", "a bytecode cache python writes when a script of the skill "
                    "imports another - remove it, and run the skill's scripts with "
                    "PYTHONDONTWRITEBYTECODE=1"),
    (".DS_Store", "the folder settings macOS Finder writes - remove it"),
    (".git", "a git checkout's own metadata, so the skill is a clone - copy its "
             "files out of the clone instead"),
)
DIGEST = re.compile(r"^[0-9a-f]{64}$")
PIN_KEYS = ("sha256", "source")
# The reader's four answers for one pinned name.
PIN_ANSWERS = ("match", "mismatch", "not-found", "unreadable")


class PinStop(ValueError):
    """A pinned skill about to be handed out is not the bytes pinned; the message
    is the stop. A ValueError because that is what the drive turns into a stop
    (`drive-phase.py one_next`), so a hand-out that raises it stops `next` there."""


def _no_digest(problem, files=0, tool_written=()):
    return {"digest": None, "files": files, "problem": problem,
            "toolWritten": list(tool_written), "kept": None}


def _inside(path, root):
    """True when `path` is `root` or under it, both already real paths."""
    try:
        return os.path.commonpath([os.path.normcase(path),
                                   os.path.normcase(root)]) == os.path.normcase(root)
    except ValueError:
        return False


def _kind(mode):
    """The kind of an entry whose mode is `mode`, in the words a refusal uses."""
    for test, word in ((stat.S_ISREG, "regular file"), (stat.S_ISDIR, "directory"),
                       (stat.S_ISLNK, "link"), (stat.S_ISFIFO, "FIFO"),
                       (stat.S_ISSOCK, "socket"), (stat.S_ISCHR, "character device"),
                       (stat.S_ISBLK, "block device")):
        if test(mode):
            return word
    return "entry of a kind this reader does not know"


def _name_problem(rel):
    """Why `rel` cannot be a line of the digest, or None."""
    if "\n" in rel or "\r" in rel:
        return "the file name %r holds a line break" % (rel,)
    try:
        rel.encode("utf-8")
    except UnicodeError:
        return "the file name %r cannot be written as UTF-8" % (rel,)
    return None


def _is_normalised(rel):
    """True for a file whose CRLF is read as LF: `NORMALISED_SUFFIXES`."""
    return rel.lower().endswith(NORMALISED_SUFFIXES)


def _read_file(path, rel, seen, budget, keep):
    """`(sha256, size, kept bytes or None, problem)` for one regular file whose
    `stat` was `seen`: opened without following a link and without blocking,
    checked to be that same regular file, read in chunks and stopped past
    `budget` bytes. With `keep` true the raw bytes are handed back too."""
    flags = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0))
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        return None, 0, None, "%s could not be read: %s" % (rel, exc)
    try:
        now = os.fstat(fd)
        if not stat.S_ISREG(now.st_mode) or not os.path.samestat(now, seen):
            return None, 0, None, "%s changed while it was read" % (rel,)
        sha, size, kept, carry = hashlib.sha256(), 0, [] if keep else None, b""
        normalise = _is_normalised(rel)
        while True:
            chunk = os.read(fd, _CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > budget:
                return None, size, None, _OVER
            if kept is not None:
                kept.append(chunk)
            if normalise:
                # A CR that ends a chunk may be the first half of a CRLF.
                chunk = carry + chunk
                carry = b"\r" if chunk.endswith(b"\r") else b""
                chunk = (chunk[:-1] if carry else chunk).replace(b"\r\n", b"\n")
            sha.update(chunk)
        sha.update(carry)
    except OSError as exc:
        return None, 0, None, "%s could not be read: %s" % (rel, exc)
    finally:
        os.close(fd)
    return sha.hexdigest(), size, (b"".join(kept) if keep else None), None


def _file_target(full, rel, root, seen):
    """`(path to read, its stat, problem)` for an entry that is no directory: a
    regular file is itself, a link inside the directory to one is its target, and
    anything else is the problem naming it and its kind - never opened."""
    if stat.S_ISREG(seen.st_mode):
        return full, seen, None
    if not stat.S_ISLNK(seen.st_mode):
        return None, None, "%s is a %s, not a regular file - it was not opened" % (
            rel, _kind(seen.st_mode))
    target = os.path.realpath(full)
    if not _inside(target, root):
        return None, None, "%s is a link leading out of the directory, to %s" % (
            rel, target)
    try:
        led = os.stat(target)
    except OSError:
        return None, None, "%s is a link to %s, which is not there" % (rel, target)
    if stat.S_ISDIR(led.st_mode):
        return None, None, "%s is a link to a directory" % (rel,)
    if not stat.S_ISREG(led.st_mode):
        return None, None, ("%s is a link to %s, a %s, not a regular file - it was "
                            "not opened" % (rel, target, _kind(led.st_mode)))
    return target, led, None


def _listing(here, met, max_entries):
    """`(names, met, problem)`: the entries of directory `here`, sorted, with the
    running count of entries met - read no further than the ceiling allows."""
    names = []
    try:
        with os.scandir(here) as it:
            for entry in it:
                met += 1
                if met > max_entries:
                    return [], met, ("more than %d entries - files, directories "
                                     "and links - more than a skill holds"
                                     % (max_entries,))
                names.append(entry.name)
    except OSError as exc:
        return [], met, "a directory under it could not be listed: %s" % (exc,)
    return sorted(names), met, None


def skill_digest(folder, max_entries=MAX_SKILL_ENTRIES, max_bytes=MAX_SKILL_BYTES,
                 keep=None):
    """`{"digest", "files", "problem", "toolWritten", "kept"}` for a skill's
    directory: the digest defined above, or None with the reason it has none.
    `toolWritten` is every `TOOL_WRITTEN` entry met, by relative path. `keep` is
    the path of one file to hand back as `kept` - the raw bytes that were hashed,
    so a caller showing that file shows what was hashed without reading it again;
    None when it was not among the files read."""
    root = os.path.realpath(folder)
    if not os.path.isdir(root):
        return _no_digest("%s is not a directory" % (folder,))
    try:
        wanted = os.stat(keep) if keep else None
    except OSError:
        wanted = None
    lines, used, met, tool, kept, stack = [], 0, 0, [], None, [""]
    marks = [name for name, _why in TOOL_WRITTEN]
    while stack:
        top = stack.pop()
        names, met, problem = _listing(os.path.join(root, *top.split("/")) if top
                                       else root, met, max_entries)
        for name in names:
            if problem:
                break
            rel = "%s/%s" % (top, name) if top else name
            full = os.path.join(root, *rel.split("/"))
            problem = _name_problem(rel)
            if problem:
                break
            if name in marks:
                tool.append(rel)
            try:
                seen = os.lstat(full)
            except OSError as exc:
                problem = "%s could not be read: %s" % (rel, exc)
                break
            if stat.S_ISDIR(seen.st_mode):
                stack.append(rel)
                continue
            path, target, problem = _file_target(full, rel, root, seen)
            if problem:
                break
            if target.st_size > max_bytes - used:
                problem = _OVER
                break
            sha, size, raw, problem = _read_file(
                path, rel, target, max_bytes - used,
                wanted is not None and os.path.samestat(target, wanted))
            if problem:
                break
            lines.append("%s %s\n" % (rel, sha))
            used += size
            kept = raw if raw is not None else kept
        if problem:
            return _no_digest("more than %d bytes - more than a skill holds"
                              % (max_bytes,) if problem is _OVER else problem,
                              len(lines), tool)
    joined = "".join(sorted(lines)).encode("utf-8")
    return {"digest": hashlib.sha256(joined).hexdigest(), "files": len(lines),
            "problem": None, "toolWritten": sorted(tool), "kept": kept}


def pin_verdict(name, pin, tree, user_home, plugin_root, running, pinned_as=None):
    """The one reader of one pin: `{"name", "pinnedAs", "answer", "path", "places",
    "pinned", "found", "source", "problem", "toolWritten", "skillMd"}`. `answer` is
    one of `PIN_ANSWERS`; `path` is the SKILL.md `resolve_skill` found for `name`
    (None when not found), `places` every path looked in, `found` the directory's
    digest (None unless it could be read whole) and `problem` why there is none.
    `pinnedAs` is the spelling the pin is written under when it is not `name`'s
    (`covering_pins`). `toolWritten` is every `TOOL_WRITTEN` entry the directory
    holds, and `skillMd` the raw bytes of the SKILL.md that were hashed, so a
    caller that shows the file shows exactly those. A name the resolver cannot
    place - another plugin's skill, one bundled with Claude Code - is
    `not-found`: a pin says the skill is a reviewed copy on disk, and nothing here
    can read that one."""
    pin = pin if isinstance(pin, dict) else {}
    hit = resolve_skill(name, tree, user_home, plugin_root, running)
    base = {"name": name, "pinnedAs": pinned_as if pinned_as != name else None,
            "path": hit["path"], "places": hit["places"],
            "pinned": pin.get("sha256"), "found": None, "source": pin.get("source"),
            "problem": hit["problem"], "toolWritten": [], "skillMd": None}
    if not hit["found"]:
        return dict(base, answer="not-found")
    got = skill_digest(os.path.dirname(hit["path"]), keep=hit["path"])
    if got["digest"] is None:
        return dict(base, answer="unreadable", problem=got["problem"])
    return dict(base, found=got["digest"], toolWritten=got["toolWritten"],
                skillMd=got["kept"],
                answer="match" if got["digest"] == base["pinned"] else "mismatch")


# The way through every stop: restore, or review and re-pin. Dropping the pin is
# deliberately not offered - it is the one remedy that makes the check say nothing.
_STOP_REMEDY = ("Restore the pinned bytes there, or review the diff and re-pin the "
                "skill to the reviewed digest in meta.skillPins; nothing was handed out.")


def _tool_written_words(rels):
    """The sentence naming the tool-written entries a changed directory holds, or
    "" when it holds none."""
    why = dict(TOOL_WRITTEN)
    if not rels:
        return ""
    return (" Its directory holds entries a tool rather than an author writes, the "
            "likely difference: %s. Each is still counted - a cache beside its source "
            "is code python runs, and a checkout's metadata is bytes in the directory."
            % ("; ".join("%s (%s)" % (rel, why[rel.rsplit("/", 1)[-1]])
                         for rel in rels),))


def stop_words(verdict):
    """The stop for one verdict that is not a match: the skill (and the spelling it
    is pinned under, when another), the path read (or every place looked in), the
    pinned digest and the found one, the tool-written entries a changed directory
    holds, and the remedy."""
    v = verdict
    source = " (pin source: %s)" % (v["source"],) if v.get("source") else ""
    if v.get("pinnedAs"):
        source = " (pinned as %s)%s" % (v["pinnedAs"], source)
    if v["answer"] == "mismatch":
        return ("the skill %s is pinned, and the copy an agent or a session would "
                "load is not the bytes pinned: %s has digest %s, the plan pinned %s%s."
                "%s %s" % (v["name"], v["path"], v["found"], v["pinned"], source,
                           _tool_written_words(v.get("toolWritten")), _STOP_REMEDY))
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


# --- a pin is about a directory ------------------------------------------------------
# A pin holds the DIRECTORY its name resolves to, not the name's spelling: the bare
# name and the running plugin's `plugin:skill` reach one directory when no personal
# or project copy shadows the bare one, and on a volume that folds case another
# case of the name reaches it too. So the question asked of each name about to be
# handed out is whether the directory it resolves to is one a pin's name resolves
# to - compared by the file system's own identity of the two (`os.path.samestat`:
# device and inode), which needs neither a spelling nor a real path that keeps
# case. A pinned spelling that resolves nowhere still holds that same spelling, so
# a hand-out of it is the pin's `not-found` stop, not a pass.
def _directory_of(name, tree, user_home, plugin_root, running):
    """The `stat` of the directory `name` resolves to, or None."""
    hit = resolve_skill(name, tree, user_home, plugin_root, running)
    if not hit["found"]:
        return None
    try:
        return os.stat(os.path.dirname(hit["path"]))
    except OSError:
        return None


def covering_pins(names, pins, tree, user_home, plugin_root, running=None):
    """`[(name, pin name), ...]`: for each of `names`, in order and once, every
    pin that holds it - written under the same spelling, or resolving to the
    directory the name resolves to. An unpinned name has no row."""
    if not isinstance(pins, dict) or not pins:
        return []
    if running is None:
        running = plugin_name(plugin_root)
    order = sorted(pins, key=str)
    where = dict((p, _directory_of(p, tree, user_home, plugin_root, running))
                 for p in order if is_skill_name(p))
    out, seen = [], []
    for name in names:
        if name in seen:
            continue
        seen.append(name)
        here = _directory_of(name, tree, user_home, plugin_root, running)
        out.extend((name, p) for p in order
                   if p == name or (here is not None and where.get(p) is not None
                                    and os.path.samestat(here, where[p])))
    return out


def pin_verdicts(names, pins, tree, user_home, plugin_root):
    """Every verdict a hand-out of `names` is owed: one per name and pin that
    holds it (`covering_pins`), in the order named."""
    if not isinstance(pins, dict) or not pins:
        return []
    running = plugin_name(plugin_root)
    return [pin_verdict(name, pins[p], tree, user_home, plugin_root, running,
                        pinned_as=p)
            for name, p in covering_pins(names, pins, tree, user_home, plugin_root,
                                         running)]


def pin_stops(names, pins, tree, user_home, plugin_root):
    """The verdicts that stop a hand-out of `names`: each `pin_verdicts` answer
    that is not a match. An unpinned name is not asked, and neither is a pin no
    name among `names` resolves to."""
    return [v for v in pin_verdicts(names, pins, tree, user_home, plugin_root)
            if v["answer"] != "match"]


def pin_directory_problems(pins, tree, user_home, plugin_root):
    """One sentence per directory that two or more pins resolve to with different
    digests - one of them is not the reviewed bytes, whichever spelling a hand-out
    uses; [] when there is none. Pins whose shape is wrong are
    `pin_shape_problems`' to report and are not asked here."""
    if not isinstance(pins, dict):
        return []
    running = plugin_name(plugin_root)
    groups = []
    for p in sorted(pins, key=str):
        value = pins[p]
        if not (is_skill_name(p) and isinstance(value, dict)):
            continue
        here = _directory_of(p, tree, user_home, plugin_root, running)
        if here is None:
            continue
        for group in groups:
            if os.path.samestat(group[0], here):
                group[1].append((p, value.get("sha256")))
                break
        else:
            groups.append((here, [(p, value.get("sha256"))]))
    return ["meta.skillPins: %s resolve to one directory, %s, and pin different "
            "digests (%s) - one of them is not the reviewed bytes"
            % (" and ".join(p for p, _d in held),
               os.path.dirname(resolve_skill(held[0][0], tree, user_home, plugin_root,
                                             running)["path"]),
               ", ".join("%s: %s" % (p, d) for p, d in held))
            for _here, held in groups if len(set(d for _p, d in held)) > 1]


def _bare(name):
    """`skill` of `plugin:skill`, or the name itself."""
    head, sep, tail = name.partition(":")
    return tail if sep else head


def unused_pins(pins, used):
    """The pins of `pins` no name in `used` can be a spelling of, sorted. Judged by
    the name alone - validation reads no file - and leaning to silence: a used
    name with the same bare name, in any case and under any plugin, keeps a pin
    from being called unused, so this misses a pin only another plugin's skill of
    that name seems to use. Which DIRECTORY a hand-out reaches is judged by
    `covering_pins`, never by this."""
    if not isinstance(pins, dict):
        return []
    spoken = set(_bare(n).lower() for n in used if isinstance(n, str))
    return [p for p in sorted(pins, key=str)
            if isinstance(p, str) and _bare(p).lower() not in spoken]


def require_pins(names, manifest, tree, user_home, plugin_root):
    """`names`, unchanged, when every pinned one among them is the bytes `manifest`
    pins; otherwise raises `PinStop` with each stop's words. A plan with no
    `meta.skillPins` asks nothing - no file is read for it. A malformed key stops
    too: the validator refuses it, and a pin that cannot be read is no reason to
    hand the skill out; so do two pins on one directory that disagree."""
    names = list(names)
    pins = skill_pins(manifest)
    if pins is None:
        return names
    problems = pin_shape_problems(pins) or pin_directory_problems(
        pins, tree, user_home, plugin_root)
    if problems:
        raise PinStop("meta.skillPins cannot be read, so no pinned skill is handed "
                      "out: %s" % ("; ".join(problems),))
    stops = pin_stops(names, pins, tree, user_home, plugin_root)
    if stops:
        raise PinStop("\n".join(stop_words(v) for v in stops))
    return names


def pin_flags(names, manifest, tree, user_home, plugin_root):
    """`--skill-pin NAME=DIGEST` for each of `names` a pin holds (`covering_pins`),
    in order, under the spelling handed out - what the session runner is handed
    beside its `--skill` flags. [] for a plan with no pins, with no file read, so
    its command is the one it always was."""
    pins = skill_pins(manifest)
    if not isinstance(pins, dict) or not pins:
        return []
    return [flag for name, p in covering_pins(names, pins, tree, user_home,
                                              plugin_root)
            if isinstance(pins[p], dict)
            for flag in ("--skill-pin", "%s=%s" % (name, pins[p].get("sha256")))]
