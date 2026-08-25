#!/usr/bin/env python3
"""
Terminal output that cannot be killed by a character it cannot spell, and the anchor
every other script finds itself by — stdlib only.

TWO JOBS, AND THE SECOND ONE IS WHY THIS FILE NEVER MOVES. `safe_stdio()` is the
first and the older one. The second is the path bootstrap: `SCRIPTS_DIR` and its
four companions below are the one written-down statement of where the tree's
directories are, `install_path()` puts `scripts/` AND every subdirectory of it
holding a `.py` on `sys.path`, and `PATH_PREAMBLE` is the block every other
`.py` here carries to reach this module without knowing how deep it sits.
`path_preamble_violations()` counts them. The consequence is worth stating where the
mechanism lives: the folders under `scripts/` are LABELS, NOT NAMESPACES — every
module is still reached by a bare basename, and basename uniqueness (enforced by
`_deps.layer_violations()`) is what holds the whole arrangement up.

Python does not degrade an unprintable character; it raises. When stdout is a PIPE on
Windows, its encoding is the machine's legacy code page (cp1252 on a US/EU runner), and
`print("✓")` there is not a missing tick — it is a `UnicodeEncodeError`, a traceback and
a non-zero exit, with everything the command was going to say still unsaid.

The console is not the problem: Python has written UTF-8 to the Windows console since
3.6. Only redirected output falls back to the code page, which is why this is invisible
until someone pipes, tees or captures — and CI captures everything.

`safe_stdio()` is the whole fix: reconfigure both streams to UTF-8, and set the error
handler to `replace` so that even a stream that cannot be reconfigured, or a consumer
that really is cp1252, gets a `?` instead of a crash. UTF-8 first and `replace` second is
deliberate — the common case (a UTF-8 capable consumer) gets the real character, and the
impossible case degrades one glyph instead of losing the whole run.

WHERE IT APPLIES. Every entry point under `scripts/` calls it as its first statement, and
that is enforced rather than remembered: `entries_missing_guard()` reads the directory and
names any `__main__` block that does not, so the selftest CI already runs fails the moment
a new script forgets. Ordering matters as much as adoption — the guard has to run before
the first `print`, so a script that calls it late is a script that still crashes on its
first line of output.

`hooks/` deliberately does NOT import this. A hook's product output is `json.dumps`, which
is `ensure_ascii` by default and therefore pure ASCII by construction; its only other
output is its own selftest. Keeping the hooks importless is worth more than the guard —
they run on every tool call, from a launcher that may not have this directory on its path.
CI runs the whole selftest sweep a second time under `PYTHONIOENCODING=cp1252`, which is
what actually covers them, and would catch a hook that started printing prose with a glyph
in it.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__output.py`, and it was the last of the forty-eight to move —
`selftest_coverage()` below is what classified the other forty-seven on the way. Two
things had to change for it to classify ITSELF correctly, both recorded where they were
made: `_CONTRACT` is assembled rather than spelled, and every docstring (not only the
module's) is dropped before the proxy reads a file's strings. `--covered` is production
and is what CI's sweep skips by, so it keeps working with no suite here at all.
"""

import ast
import hashlib
import json
import os
import sys

# --- the anchors ----------------------------------------------------------------
# THIS FILE IS THE MARKER, WHICH IS WHY IT IS THE ONE THAT NEVER MOVES. Every other
# `.py` under `scripts/` finds this directory by walking UP from its own `__file__`
# until it sees `_output.py` — the preamble `PATH_PREAMBLE` pins and
# `path_preamble_violations()` counts — so this FILE is the ONE place the tree's
# shape is written down: the anchors below, and `UI_DIR` further down beside the
# walk that needs it. A `dirname(dirname(...))` anywhere else is that
# file's own depth, hard-coded, and it is wrong the moment the file is moved.
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# scripts -> audit. `hooks/`, `tests/`, `commands/`, `agents/`, `schema/` and
# `.claude-plugin/plugin.json` all hang off this one; six files derived it for
# themselves before, each spelling its own distance from the plugin root.
PLUGIN_ROOT = os.path.dirname(SCRIPTS_DIR)

HOOKS_DIR = os.path.join(PLUGIN_ROOT, "hooks")

# `tests/` is a sibling of scripts/ and hooks/, not a subdirectory of either, so no
# existing walk reaches it and every lint that should cover it has to say so. The
# scope decision, recorded once here and again on each function: the DIALECT rules
# apply to tests too (`house_style_violations`, `entries_missing_guard`), because a
# test written with `typing` or a walrus is exactly as unrunnable on 3.8 as a script
# written that way, and a test that crashes on a cp1252 stream hides its own result.
TESTS_DIR = os.path.join(PLUGIN_ROOT, "tests")

# audit -> plugins -> the repo root. `covered_repo_paths()` needs it because CI's
# sweep speaks repo-relative paths, and `_refs` needs it because every `rel` it
# produces already starts with `plugins/audit/`. Both used to derive it separately,
# from their own `__file__`, which is two answers to a question with one.
REPO_ROOT = os.path.dirname(os.path.dirname(PLUGIN_ROOT))


# --- safe stdio ---------------------------------------------------------------
def posix_rel(path, start):
    """A `start`-relative path spelled with "/" on EVERY platform.

    `os.path.relpath` answers in the platform's separator, so the same phase shard
    is `phases/P3.json` in the index that stores it and `phases\\P3.json` in the
    line a Windows reader is shown. One file, two spellings, and the one nobody
    can search for is the one on screen.

    Every value that is PUBLISHED - reported to a human, put in `--json`, persisted,
    or handed to git as a pathspec - goes through here. Values used only to OPEN a
    file do not need it, because Python takes either separator; values compared
    against a manifest do, because the manifest holds this spelling.

    IT LIVES IN THE ANCHOR BECAUSE THE CALLERS ARE IN EVERY LAYER. It began in
    `_manifest_io`, which is layer 1 - and `_ui_theme`, which publishes a theme
    path, is layer 1 too, so it could not reach it without a sideways import. A
    helper the layering forbids half its callers from using is a helper half the
    tree will hand-roll instead, which is the duplication this exists to end.

    Backslashes are replaced UNCONDITIONALLY rather than only `os.sep`. Written as
    `os.sep` this is the identity on POSIX, so no case here could ask it anything
    and the body could be deleted without a suite going red - a check that can only
    fail on the platform nobody runs locally. The cost is a POSIX filename holding
    a literal backslash, which is respelled in what is REPORTED and never in what
    is opened; the same trade `_config.slashed()` takes in `hooks/`.
    """
    return os.path.relpath(path, start).replace("\\", "/")


def safe_stdio():
    """Make stdout/stderr unable to crash on a character they cannot spell.

    Idempotent, and never raises: a stream that has been replaced by a StringIO (which
    every selftest that captures output does) has no `reconfigure`, and a stream that has
    been detached has one that refuses. Neither is a reason to take the process down —
    the point of this function is that output problems stop being fatal.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # No reconfigure (StringIO), already detached, or a platform that refuses.
            # `replace` alone is still worth having if the encoding move is what failed.
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


# --- naming a bounded set without hiding the rest -------------------------------
# ONE renderer for every "N things: a, b, c" line this plugin prints, and F205 is
# why it is one. `_doctor_completions` told a live client repo that four tasks were
# marked done with no completion record and then named three of them. The COUNT was
# right - it always was, which is why nothing caught it - and the EVIDENCE was the
# truncated half, so the fourth name did not exist as far as that line was
# concerned. Every site with that shape carried its own hand-picked cap, so there
# was no one place to repair it and no way to keep the repair honest.
#
# THE BUDGET IS IN CHARACTERS, NOT ELEMENTS, and that is what let the caps collapse
# into one fact. The caps they came from disagreed because their elements do: a task
# id is short and a malformed manifest entry's repr is not, so an element count says
# nothing about how long the line comes out. A character budget says the thing every
# one of those caps was reaching for.
#
# THE FIRST ELEMENT IS ALWAYS SHOWN, however long it is. A budget that can drop
# everything turns a finding into a bare number, which is the same defect one step
# further along.
EVIDENCE_BUDGET = 160


def some_of(items, budget=None, sep=", ", render=None):
    """`items` rendered until `budget` is spent, then how many are NOT shown.

    Never silently short. The tail says how many were left out whenever anything
    was, so a count printed in front of this list and the list itself cannot
    disagree about how much of the set the reader is looking at — which is the
    only thing F205's reader needed and could not get.

    `render` is how one item becomes text: `repr` for the sites that used to hand
    a bounded list straight to `%r`, `str` otherwise.
    """
    show = render if render is not None else str
    limit = budget if budget is not None else EVIDENCE_BUDGET
    seq = list(items)
    shown, used = [], 0
    for item in seq:
        text = show(item)
        cost = len(text) + (len(sep) if shown else 0)
        if shown and used + cost > limit:
            break
        shown.append(text)
        used += cost
    left = len(seq) - len(shown)
    if left > 0:
        return "%s and %d more" % (sep.join(shown), left)
    return sep.join(shown)


# --- finding the files to check ------------------------------------------------
# The directory prefix `test__loader.py` writes its depth probes into. A PREFIX,
# so `_loader_probe_a` and `_loader_probe_b` are one fact rather than two.
LOADER_PROBE_DIR = "_loader_probe"


def py_files(directory):
    """Sorted `(relname, path)` for every `.py` under `directory`, RECURSIVELY.

    The recursion is the point. Both lints below used a flat `os.listdir`, and so
    did CI's selftest glob and `_deps`' scanners — which is why `CONTRIBUTING.md`
    had to carry a rule saying `.py` must stay one directory deep: a file dropped
    into a subdirectory silently stopped being checked. The hazard was never the
    subdirectory, it was the SILENCE. A recursive walk removes the hazard instead
    of forbidding the shape, and it costs nothing today because there is no `.py`
    in a subdirectory yet — this change is a no-op on the current tree and only
    ever matters for a file somebody adds later.

    `relname` is relative to `directory` and uses forward slashes, so a violation
    in `usage/core.py` reports as `usage/core.py` rather than as a bare `core.py`
    that could be any of several files once folders exist. Today, with everything
    flat, it is exactly the basename it always was.

    Sorted so the output is stable across filesystems; `os.walk` order is not.
    """
    found = []
    for root, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            rel = posix_rel(path, directory)
            found.append((rel, path))
    found.sort()
    return found



def lint_py_files(directory):
    """`py_files` minus another suite's transient fixture.

    THE DIFFERENCE IS WHO IS ASKING. `py_files` answers "what .py files exist",
    and RESOLUTION depends on that being the whole truth: `_loader.script_index()`
    walks it, and `test__loader.py` proves depth-independent resolution by writing
    two files under one basename into the REAL scripts/ tree - filtering them out
    of `py_files` broke exactly that, which is how this function came to exist.

    A LINT is asking a different question: what does this repository CARRY. A pair
    of files that exists for the width of one `finally` is not carried by anyone,
    and every lint walking beside that suite reported it - `_deps`' basename
    collisions and the guide enumeration both went red on a commit that was green
    the run before, which is the signature of a race rather than a defect.

    Scoped to the probe DIRECTORIES rather than to a basename: a name-based
    exemption would also hide a real `loader_depth_probe.py` somebody committed,
    while a directory named this narrowly cannot exist for another reason.
    """
    return [(rel, path) for rel, path in py_files(directory)
            if not rel.startswith(LOADER_PROBE_DIR)
            and "/" + LOADER_PROBE_DIR not in rel]


# --- the files this repo KEEPS -------------------------------------------------
# ONE walk for every rule that asks which files this repo holds. `_refs` wrote it,
# for the sweep-document rule and the published-fetch rule, and its own note says
# why there is only one: the second rule had a walk of its own and it was a hand
# list of four directory names, wrong in both directions at once. It reached
# whatever the browser tool had last left in the tree, so the candidate set moved
# with what had recently run on this machine rather than with anything in the
# commit, and it pruned `.claude/` wholesale, which held the tracked skills out of
# a rule that is precisely about a document publishing a fetch.
#
# IT LIVES HERE, AT THE ANCHOR, and that is the only thing about it that is new.
# `_refs` is at layer 1; the prose-number scan below is in this module at layer 0
# and needs the same answer, so a copy at layer 0 would be exactly the
# two-prune-lists defect one layer down. `_refs` keeps the names and delegates.
#
# `.claude/worktrees/` is the entry that makes the pruning necessary rather than
# tidy: it holds WHOLE CHECKOUTS of this repo - as many as there were recent
# agents. A scan that did not know about it would report every finding once per
# worktree, so the finding count would depend on nothing that is in the commit.
#
# Only the unambiguous half of the format is honoured: a line ending in `/` with no
# glob metacharacter names a directory. A pattern and a bare file path are the rest
# of gitignore, and reading them would be implementing it. The consequence is
# stated rather than hidden - an ignored FILE of a scanned extension stays a
# candidate, which is why the generated report has a row of its own in
# `PROSE_SCAN_EXEMPT`, and why an untracked scratch file of a scanned extension is
# scanned like any other. Being scanned by default is the property; the way to opt
# out is a row somebody wrote.
#
# `git ls-files` would answer "tracked" outright and may not be used: these suites
# are verified over a `git archive HEAD` export, which has no `.git` at all.
_IGNORE_GLOB_CHARS = "*?[]!"


def _ignored_dirs(root):
    """`(patterns, problem)` - the directory patterns `.gitignore` declares.

    Exactly one of the two is None. Falling back to "nothing is ignored" would walk
    the agent worktrees and report every finding once per copy, which is a wrong
    answer wearing the shape of a right one. `.gitignore` is tracked, so a tree
    without a readable one is broken rather than minimal.
    """
    try:
        with open(os.path.join(root, ".gitignore"), "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return None, ("unreadable, so the directories this repo does not keep "
                      "cannot be derived: %s" % exc)
    # `.git` is never IN `.gitignore` - git does not ignore its own directory - so it
    # is the one name here, and the only one this function spells.
    out = [".git"]
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or not line.endswith("/"):
            continue
        rel = line.strip("/")
        if not rel or [ch for ch in _IGNORE_GLOB_CHARS if ch in rel]:
            continue
        out.append(rel)
    return tuple(sorted(set(out))), None


def _ignored_files(root):
    """`(patterns, problem)` - the FILE paths `.gitignore` declares, same contract.

    The other half of `_ignored_dirs()`, and deliberately not merged with it: a rule
    whose subject is "what this repo keeps as source" wants ignored files SCANNED -
    an untracked scratch file of a scanned extension is scanned like any other, and
    the way to opt out is a row somebody wrote. A rule whose subject is a COMMITTED
    artifact wants them gone, because a scratch render is not a published page and a
    finding about one depends on what somebody last rendered here rather than on the
    commit.

    Two subjects, two candidate sets, one format read twice - which is why this is a
    separate reader taken by the rules that need it rather than a change to the walk
    every rule shares.

    Only the unambiguous half again: a line that does NOT end in `/` and carries no
    glob metacharacter names a file. Anything else is a pattern, and reading patterns
    would be implementing gitignore.
    """
    try:
        with open(os.path.join(root, ".gitignore"), "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return None, ("unreadable, so the files this repo does not keep "
                      "cannot be derived: %s" % exc)
    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.endswith("/"):
            continue
        rel = line.strip("/")
        if not rel or [ch for ch in _IGNORE_GLOB_CHARS if ch in rel]:
            continue
        out.append(rel)
    return tuple(sorted(set(out))), None


def _is_ignored(rel_dir, patterns):
    """Whether the directory at `rel_dir` is one the patterns name.

    Gitignore's anchoring rule, and the only part of it needed here: a pattern with
    no slash inside it matches a directory of that NAME at any depth
    (`__pycache__/`), one with a slash is anchored to the repo root
    (`.claude/usage/`). Collapsing the two would either prune every directory
    called `usage` or fail to prune the one that matters, and both readings look
    right in a review.
    """
    name = rel_dir.rsplit("/", 1)[-1]
    for pattern in patterns:
        if "/" in pattern:
            if rel_dir == pattern or rel_dir.startswith(pattern + "/"):
                return True
        elif name == pattern:
            return True
    return False


def kept_files(root, patterns, exts, drop=None):
    """Relative paths of every file of `exts` this repo KEEPS, sorted.

    `drop` is OPTIONAL and defaults to today's behaviour on purpose: ignored
    DIRECTORIES are always pruned, because one of them holds whole checkouts of this
    repo and a scan that walked them would report every finding once per agent.
    Ignored FILES are pruned only for a caller that asks, because whether they belong
    in the candidate set is a property of the RULE's subject and not of the walk -
    see `_ignored_files()`.

    Passing `drop` never widens the set, so a caller that adds it can only stop
    reporting things; a caller that forgets it keeps exactly the answer it had.
    """
    out = []
    for base, dirs, files in os.walk(root):
        rel_base = posix_rel(base, root)
        prefix = "" if rel_base == "." else rel_base + "/"
        dirs[:] = sorted(d for d in dirs if not _is_ignored(prefix + d, patterns))
        for name in sorted(files):
            if not name.endswith(exts):
                continue
            rel = prefix + name
            if drop and _is_ignored(rel, drop):
                continue
            out.append(rel)
    return sorted(out)


# --- which files a surface's pictures are OF ------------------------------------
# ONE walk for the question "does this committed screenshot still show the current
# UI", which is NOT the question the version stamp beside it answers. F85: commits
# landed under `scripts/ui/` after the last re-capture and the recorded version was
# still current, so `_refs.screenshot_capture_drift()` was green over stale pixels.
#
# Pixels cannot close that. F18 settled that a PNG is comparable only on the host
# that wrote it - font rasterisation has no environment variable - and
# `tools/capture-screenshots.mjs` declines three repairs by name in its own header.
# The SOURCES can: they are committed bytes, so a digest over them is
# host-independent by construction, where the rendered page (which paints the
# project path) is not.
#
# IT LIVES HERE, AT THE ANCHOR, for the same reason the kept-files walk above does:
# two readers at two layers. `_refs` at layer 1 holds the rule, and the capture asks
# for the same answer over a pipe. A copy in either would be the second
# implementation of "which files" that F85's round exists to remove.
#
# DERIVED, NEVER DECLARED. Membership comes off a part's own name, so a directory
# added under `ui/` is covered the day it lands - and a name that answers nobody is
# REPORTED rather than dropped, because a part no surface's digest covers is a part
# whose change no picture can ever be red about.
UI_DIR = os.path.join(SCRIPTS_DIR, "ui")

# The surfaces `ui/` is filed by, and the same names the capture's legs push.
UI_SURFACES = ("panel", "report")

# Documentation is excluded BY SUFFIX rather than assets admitted by one: a part
# wearing an unfamiliar extension must be reported, not silently unwatched. Read by
# `_ui_theme` too, which is the point - a doc suffix the digest honoured and
# `declared_asset_drift()` did not would be the same drift one directory over.
UI_DOC_EXT = (".md", ".txt")

# `shared/` ships in EVERY surface: `_report_ui._SCRIPT_PARTS` and
# `_panel_ui._JS_PARTS` both list its parts, ahead of every surface part.
_UI_SHARED = "shared"

# The token layer is a `.py` and it ships in BOTH pages - `TOKEN_CSS` heads the
# report's stylesheet and is substituted into the panel's, and neither sheet is even
# valid without it. So a colour or a spacing step moving there moves every picture,
# which is exactly what this must not sleep through.
#
# THE WHOLE FILE, not a list of its page-bearing constants. Such a list is a second
# home: it would need a row the day somebody adds the next constant, and the day it
# does not get one is the day this goes quiet. The cost is stated rather than
# hidden - an edit to a CSS lint in that file also asks for a re-capture. Measured
# before accepting it: of the commits that have touched the file, essentially every
# one was visual (tokens, palettes, contrast, the CSS part cuts), so the breadth is
# theoretical here rather than paid.
#
# `_panel_ui.py` and `_report_ui.py` are deliberately OUT. They hold part order and
# the `<style>`/`<script>` wrappers - no visual value - and both are already pinned
# by name in their assembly suites. Letting them in would oblige `_report_html.py`,
# then every module that emits markup, then the fixture manifests, and the rule
# would degenerate into "any commit reddens every picture". So the boundary is the
# assembled ASSETS, and the renderer is the stated limit rather than an oversight.
_UI_TOKEN_LAYER = "_ui_theme.py"


def ui_surfaces_of(rel):
    """Which surfaces the `ui/` part at `rel` ships in - `()` when its name answers
    nobody.

    THE FILING CONVENTION IS THE ANSWER: `panel/`, `panel-css/`, `report/` and
    `report-css/` name their surface, the root `panel.html` names it in its stem,
    and `shared/` ships in all of them. Reading it off the name is what keeps this
    from becoming a second list of parts beside the assemblers' - the thing that
    drifts. An unknown name returning `()` rather than a guess is what makes the
    caller able to report it.
    """
    part = rel.split("/")[0].split(".")[0]
    if part == _UI_SHARED:
        return UI_SURFACES
    return tuple(s for s in UI_SURFACES if part == s or part.startswith(s + "-"))


def ui_surface_sources(scripts_dir=None):
    """`{"root": dir, "sources": {surface: [rel, ...]}, "unassigned": [...],
    "error": None|str}`.

    Sorted throughout, so a digest taken over the result is stable across
    filesystems; `os.walk` order is not. `root` is the directory this answer is
    about, returned rather than re-joined by the caller: a walk and a digest that
    each joined their own `ui/` would be a comparison between two trees.

    `error` is set and `sources` left EMPTY for anything that would otherwise be
    answered by a set that narrowed to nothing - an unwalkable tree, a tree with no
    part in it, a surface with no part of its own. All three are how a moved or
    renamed directory presents, and a digest over the remainder would be stable,
    comparable and about a tree that is not there.
    """
    root = UI_DIR if scripts_dir is None else os.path.join(scripts_dir, "ui")
    walk_errors = []
    rels = []
    # `onerror` is the guard, not a courtesy: os.walk swallows an unreadable
    # directory by default, yielding nothing and raising nothing, so a missing tree
    # would arrive as "no sources" and the digest over it would read as agreement.
    for dirpath, dirnames, filenames in os.walk(root, onerror=walk_errors.append):
        dirnames.sort()
        rel_dir = posix_rel(dirpath, root)
        prefix = "" if rel_dir == "." else rel_dir + "/"
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith(UI_DOC_EXT):
                continue
            rels.append(prefix + name)
    if walk_errors:
        return {"root": root, "sources": {}, "unassigned": [],
                "error": "cannot be walked, so which files the pictures are of is "
                         "unknown rather than unchanged: %s" % (walk_errors[0],)}
    if not rels:
        return {"root": root, "sources": {}, "unassigned": [],
                "error": "holds no assembled part at all - a candidate set that "
                         "narrowed to nothing must not be spelled the same way as "
                         "a set that agrees"}
    sources = dict((surface, []) for surface in UI_SURFACES)
    unassigned = []
    for rel in sorted(rels):
        surfaces = ui_surfaces_of(rel)
        if not surfaces:
            unassigned.append(rel)
            continue
        for surface in surfaces:
            sources[surface].append(rel)
    # A part of its OWN, not a part at all. A surface left holding only `shared/`
    # is a surface nothing assembles any more, and its digest would still compute,
    # still be stable and still be comparable - so it would go on clearing every
    # picture of a page that is gone. That is the shape a renamed surface takes.
    orphaned = [s for s in UI_SURFACES
                if not [rel for rel in sources[s] if ui_surfaces_of(rel) == (s,)]]
    if orphaned:
        return {"root": root, "sources": {}, "unassigned": unassigned,
                "error": "holds no part of its own for %s - only parts shared with "
                         "another surface - so a digest for it would stand for "
                         "nothing" % (", ".join(orphaned),)}
    return {"root": root, "sources": sources, "unassigned": unassigned,
            "error": None}


def ui_surface_digests(scripts_dir=None):
    """`{"digests": {surface: hex}, "unassigned": [...], "error": None|str}`.

    The digest a committed screenshot's sidecar entry is compared against. Every
    member goes in as `name length\\n` and then its raw bytes - git's own framing,
    so no pair of names and contents can be reshuffled into the same stream - and
    the members are sorted, because a digest whose value depended on walk order
    would move between filesystems without a byte changing.

    BYTES, not decoded text: a digest is not a place to be lenient about encoding,
    and `read_asset`'s newline argument exists precisely because a CRLF checkout
    hands back different content than the file holds.

    A member that cannot be read empties `digests` and sets `error`. A digest over
    a PARTIAL set is a wrong answer wearing the shape of a right one - stable,
    comparable, and about a different tree than the one on disk.
    """
    found = ui_surface_sources(scripts_dir)
    if found["error"]:
        return {"digests": {}, "unassigned": found["unassigned"],
                "error": found["error"]}
    # The walk's own root and the walk's own token-layer sibling, never re-derived
    # here: `root` comes back from it for exactly this reason.
    ui_root = found["root"]
    token = os.path.join(os.path.dirname(ui_root), _UI_TOKEN_LAYER)
    members = dict(
        (surface,
         sorted([(rel, os.path.join(ui_root, rel.replace("/", os.sep)))
                 for rel in found["sources"][surface]]
                + [(_UI_TOKEN_LAYER, token)]))
        for surface in UI_SURFACES)
    digests = {}
    for surface in UI_SURFACES:
        sha = hashlib.sha256()
        for name, path in members[surface]:
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError as exc:
                return {"digests": {}, "unassigned": found["unassigned"],
                        "error": "%s cannot be read, so no digest can stand for "
                                 "what the pictures are of: %s" % (name, exc)}
            sha.update(("%s %d\n" % (name, len(data))).encode("utf-8"))
            sha.update(data)
        digests[surface] = sha.hexdigest()
    return {"digests": digests, "unassigned": found["unassigned"], "error": None}


# --- the path bootstrap -------------------------------------------------------
# Two memos, keyed by a fixed string rather than by the root, because ONLY the
# default root is ever cached: a caller handing in a fixture directory must not be
# able to poison what the real tree sees, nor to read a cached answer about a
# directory it never asked about. `_loader._CACHE` is the precedent for a module
# memo here; the rule against module STATE is about values a function writes that
# another function then reads as input, which neither of these is.
_SCRIPT_FILES_CACHE = {}
_INSTALLED_CACHE = {}

_CACHE_KEY = "default root"


def script_files(refresh=False, root=None):
    """`py_files(SCRIPTS_DIR)`, walked ONCE per process and memoised.

    Every `.py` under `scripts/` runs this walk at import time through the path
    preamble, so on a run that imports twenty modules the difference between
    memoised and not is twenty `os.walk`s of the same directory. `refresh=True` is
    for the one caller that has just written or deleted a file and needs the walk
    redone — every selftest that builds a fixture tree does.

    `root` is a TEST SEAM and is deliberately NOT cached: a fixture directory must
    neither poison the real tree's memo nor read it. Pass it and you get a fresh
    `py_files` every time, which is what a case mutating a temp directory needs
    anyway.
    """
    if root is not None:
        return py_files(root)
    if refresh or _CACHE_KEY not in _SCRIPT_FILES_CACHE:
        _SCRIPT_FILES_CACHE[_CACHE_KEY] = py_files(SCRIPTS_DIR)
    return _SCRIPT_FILES_CACHE[_CACHE_KEY]


def _py_dirs(root, refresh):
    """`[root] + every subdirectory of it holding a `.py``, root first, rest sorted.

    Derived from the walk rather than from a listing, which is what makes
    `scripts/ui/` drop out on its own: it holds CSS and JS and no `.py`, so no file
    in it contributes a directory. An editorial rule ("do not put `ui/` on the
    path") becomes a mechanical one, and the day somebody adds a `.py` there it
    joins the path because it earned it, not because a constant was updated.
    """
    base = os.path.abspath(root if root is not None else SCRIPTS_DIR)
    subs = set(os.path.dirname(os.path.abspath(path))
               for _rel, path in script_files(refresh=refresh, root=root))
    subs.discard(base)
    return [base] + sorted(subs)


def plugin_version():
    """The installed plugin's version, or "" when it cannot be read.

    Lives here because BOTH surfaces stamp it and the promotion rule says two
    readers move up: the report stamps the file it rendered, the panel stamps the
    build serving the page. One reader would have stayed put.

    Best-effort by construction: a missing or malformed plugin.json costs the
    stamp and never the page. A version that cannot be read is reported as
    absent rather than as a guess, and the callers omit the stamp entirely -
    a claim with no basis is not worth printing.
    """
    try:
        path = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")
        with open(path, "r", encoding="utf-8") as fh:
            version = json.load(fh).get("version")
        return version if isinstance(version, str) and version.strip() else ""
    except Exception:
        return ""


def install_path(refresh=False, root=None):
    """Put `SCRIPTS_DIR` and every subdirectory of it holding a `.py` on `sys.path`.

    THE ROOT ALONE IS NOT ENOUGH, and that is the whole reason this is a function
    rather than one `sys.path.insert`. There are ~81 module-level sibling imports in
    this tree. Put `_areas.py` in a `manifest/` folder and `_help.py` in a `config/`
    one, and `_help`'s `import _areas` needs `scripts/manifest/` on the path — not
    `scripts/`. So every directory that holds a `.py` goes on, which is exactly what
    makes the folders LABELS AND NOT NAMESPACES: one flat name-space, every module
    reached by bare basename, and `_deps.layer_violations()`' basename-uniqueness
    rule doing the load-bearing work.

    RETURNS THE LIST IT INSTALLED — never None, never empty, and the same list on
    every call. A caller that wants to know the bootstrap ran can assert on that
    instead of asserting that some import happened to work, which is a thing that
    can be true for reasons having nothing to do with this function.

    Idempotent: a directory already on `sys.path` is left where it is rather than
    inserted a second time. Order on a fresh path is root first, then the
    subdirectories sorted — inserting in reverse at the front is what produces it.
    """
    cached = root is None and not refresh and _CACHE_KEY in _INSTALLED_CACHE
    dirs = _INSTALLED_CACHE[_CACHE_KEY] if cached else _py_dirs(root, refresh)
    if root is None:
        _INSTALLED_CACHE[_CACHE_KEY] = dirs
    for directory in reversed(dirs):
        if directory not in sys.path:
            sys.path.insert(0, directory)
    return dirs


# --- the pinned preamble ------------------------------------------------------
# The name of this module, spelled once. The preamble searches for the FILE and the
# lint looks for calls on the MODULE, and those two spellings drifting apart is the
# kind of thing that turns a lint into decoration.
_ANCHOR_MODULE = "_output"

# THE ONE FILE THAT MUST NOT CARRY THE PREAMBLE, EXEMPTED BY NAME. Two reasons, and
# the second is the one that would have bitten silently: this module IS the marker
# the preamble walks up to find, so a copy here would be a bootstrap searching for
# itself; and this module holds `PATH_PREAMBLE` as a string, so a text count over
# its own source finds exactly one occurrence and would read as COMPLIANT. That is
# the same self-matching trap `_harness`' m1 needle and `_refs`' fixture constants
# each document — a scanner that lives in the tree it scans must not plant its own
# needle there.
_PREAMBLE_EXEMPT = "_output.py"

# Byte-identical in every `.py` under `scripts/` except this one, placed after the
# stdlib imports and above the first sibling import. Three things it deliberately
# does NOT do, each already known to break something here:
#
#   * it does not touch the `__main__` blocks. `from _output import safe_stdio`
#     stays exactly as it is: rewritten to `_output.safe_stdio()` it becomes an
#     `ast.Attribute` call, which `entries_missing_guard`'s `_call_lines` does not
#     recognise, and every entry point in the tree would be reported as unguarded.
#   * it carries no `# --- name ---` banner. `_deps._NAV_HEADER_RE` matches those at
#     column 0, so a banner in every file would let a 2,000-line module satisfy
#     `navigability_violations()` on boilerplate.
#   * it adds no graph edge. Every one of these files already reaches `_output`
#     through the `from _output import safe_stdio` in its `__main__`, which
#     `_deps._imported_sibling_names` counts — the fence draws `_areas -> _output`
#     although `_areas.py` had no module-level import of it. `--render`'s output is
#     therefore byte-identical across this change, and that was verified, not
#     assumed.
PATH_PREAMBLE = '''\
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
'''


def _install_path_line(tree):
    """Line of the module-level `_output.install_path()` statement, or None.

    Module level via `_straight_line`, which stops at every `def` boundary: a call
    buried in a function is a plan to bootstrap later, and later is after the sibling
    imports it was supposed to enable.
    """
    for stmt in _straight_line(tree.body):
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            continue
        func = stmt.value.func
        if (isinstance(func, ast.Attribute) and func.attr == "install_path"
                and isinstance(func.value, ast.Name)
                and func.value.id == _ANCHOR_MODULE):
            return stmt.lineno
    return None


def _first_sibling_import_line(tree, sibling_names):
    """Lowest line number at which `tree` imports a scripts/ sibling, or None.

    `_output` itself does not count — the preamble's own `import _output` is the
    line that makes every other import possible, so counting it would report every
    correctly-written file. Anywhere in the tree, not only module level: an import
    fifty lines inside a function still has to sit below the bootstrap textually,
    and every file here puts the preamble at the top, so a whole-tree scan is
    strictly the safer reading.

    `_deps._imported_sibling_names` walks the same node shapes and cannot be shared:
    `_deps` imports THIS module, not the other way round, so the layer rule forbids
    the edge that would let this call it. Different questions in any case — that one
    returns the names for the graph, this one returns a line number for an ordering.
    """
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bases = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            bases = [(node.module or "").split(".")[0]]
        else:
            continue
        for base in bases:
            if base in sibling_names and base != _ANCHOR_MODULE:
                lines.append(node.lineno)
    return min(lines) if lines else None


def _preamble_line_repeats(src):
    """Source line numbers where a line of `PATH_PREAMBLE` occurs after its first.

    WHOLE-LINE EQUALITY, NOT `in`, and that is the whole reason this could be added
    without exempting anything. `_loader.py` and `panel-server.py` both MENTION
    `_output.install_path()` in prose - a docstring sentence and a commented
    one-liner - so a substring count would convict two correct files, and the
    repair for that would be a widening nobody could hold. A repeat is a source
    line that IS a preamble line, spelled identically down to its indentation.

    Counting the LINES rather than a named tail is the deliberate choice: the tail
    is where the repeat happened to land this time, and a constant naming it would
    be a second copy of a fact whose home is `PATH_PREAMBLE`. Derived from the
    block itself, this catches a repeat of any part of it.
    """
    wanted = set(line for line in PATH_PREAMBLE.splitlines() if line.strip())
    seen = set()
    repeats = []
    for number, line in enumerate(src.splitlines(), 1):
        if line not in wanted:
            continue
        if line in seen:
            repeats.append(number)
        else:
            seen.add(line)
    return repeats


def path_preamble_violations(script_dir=None):
    """(relname, problem) for every `.py` under `scripts/` whose bootstrap is wrong.

    The ways to be wrong, and every one but the first is a reason this is not one
    `if PATH_PREAMBLE in src`:

      * NOT EXACTLY ONCE. Counted, not tested for membership — a doubled preamble is
        as wrong as a missing one (it is a second `install_path()` call and a second
        walk-up under two more leaked names), and `in` cannot tell one from two.
      * PARTIALLY REPEATED. Counting the WHOLE block finds one occurrence in a file
        that pastes the block once and then repeats its last two statements, because
        a doubled `import _output` / `_output.install_path()` tail is not the whole
        block — so the files under `panel/` carrying exactly that were reported by
        nothing, while the house rule said this function counted the preamble "once,
        never twice". It counted the TEXT once; the bootstrap ran twice. Every line
        of the block is therefore counted too, and each must occur once.
      * NO `install_path()` CALL AT MODULE LEVEL. A file could carry the text inside
        a docstring and satisfy a text count; this is read off the AST.
      * A SIBLING IMPORT ABOVE THE CALL. A preamble pasted below the imports it
        exists to enable is decoration: those imports resolved for some other
        reason, and the day that reason goes away the file breaks with the bootstrap
        sitting right there looking correct.

    `_output.py` is exempt BY NAME — see `_PREAMBLE_EXEMPT` for the two reasons,
    one of which is that a naive count over this file's own source reads as
    compliant.

    A file that cannot be read or parsed is a violation rather than a skip, the same
    rule `entries_missing_guard` and `house_style_violations` follow.
    """
    # `script_files()` is the RESOLUTION walk - `_loader` builds its index from it
    # and must see every real file - so the filtering happens here, where a LINT
    # is the one asking. Same rule as `lint_py_files`, applied to the memoised
    # list rather than re-walking for it.
    files = (lint_py_files(script_dir) if script_dir is not None
             else [(rel, path) for rel, path in script_files()
                   if not rel.startswith(LOADER_PROBE_DIR)
                   and "/" + LOADER_PROBE_DIR not in rel])
    sibling_names = set(os.path.basename(rel)[:-3] for rel, _path in files)
    violations = []
    for rel, path in files:
        if os.path.basename(rel) == _PREAMBLE_EXEMPT:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src, filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            violations.append((rel, "cannot be read or parsed: %s" % exc))
            continue
        found = src.count(PATH_PREAMBLE)
        if found != 1:
            violations.append((rel, "carries the pinned path preamble %d times, "
                                    "not once" % found))
        repeats = _preamble_line_repeats(src)
        if repeats:
            violations.append((rel, "repeats a line of the pinned path preamble at "
                                    "%s - a partial repeat is a second bootstrap, "
                                    "and counting the whole block reads it as "
                                    "compliant"
                                    % ", ".join(str(n) for n in repeats)))
        installed = _install_path_line(tree)
        first_sibling = _first_sibling_import_line(tree, sibling_names)
        if installed is None:
            violations.append((rel, "never calls %s.install_path() at module level"
                                    % _ANCHOR_MODULE))
        elif first_sibling is not None and first_sibling < installed:
            violations.append((rel, "imports a sibling on line %d, above the "
                                    "%s.install_path() on line %d - a bootstrap "
                                    "below the imports it exists to enable is "
                                    "decoration" % (first_sibling, _ANCHOR_MODULE,
                                                    installed)))
    return violations


# --- self-location lint -------------------------------------------------------
# `os.path.basename(__file__)` yields a NAME, not a location: `panel-server.py`
# prints its own filename in a usage line, which is depth-independent and stays
# legal. Every other read of `__file__` computes WHERE the file is, which is the
# thing this forbids.
_SELF_LOCATION_ALLOWED = "basename"


def _self_location_lines(tree):
    """Lines where `__file__` is read for anything but `os.path.basename(...)`."""
    named = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) != 1:
            continue
        func = node.func
        arg = node.args[0]
        if (isinstance(func, ast.Attribute) and func.attr == _SELF_LOCATION_ALLOWED
                and isinstance(arg, ast.Name) and arg.id == "__file__"):
            named.add(id(arg))
    return sorted(node.lineno for node in ast.walk(tree)
                  if isinstance(node, ast.Name) and node.id == "__file__"
                  and id(node) not in named)


def depth_sensitive_paths(script_dir=None):
    """(relname, line, what) for a `.py` under `scripts/` that locates ITSELF.

    THE RULE IS "NO `__file__` AT ALL", NOT "NO PARENT OF `__file__`", and the
    stronger form is the only one that works. The seventeen sites this replaced
    were almost all written in TWO steps —
    `_HERE = os.path.dirname(os.path.abspath(__file__))` on one line and
    `os.path.join(os.path.dirname(_HERE), "hooks")` two hundred lines later — so a
    lint that only looked for `dirname(dirname(...))` nested in ONE expression
    would have passed every single one of them. Once the two-step is legal there
    is no version of "one level is fine" that a lint can hold.

    What makes the strong form affordable is that the pinned preamble carries the
    ONLY `os.path.dirname(os.path.abspath(__file__))` left in the tree, and it is
    cut out before the scan — replaced by blank lines rather than deleted, so a
    violation still reports the line number the reader will open. Anything a file
    genuinely needs is on `_output`: `SCRIPTS_DIR`, `PLUGIN_ROOT`, `HOOKS_DIR`,
    `TESTS_DIR`, `REPO_ROOT`.

    `hooks/` IS NOT SCANNED. Hooks may not import `scripts/` (`_deps` r5/r6), so
    the anchors are out of their reach by design and `hooks/_config.find_script()`
    has to derive the directory from its own `__file__`. Reporting that would be
    demanding a fix the layer rule forbids — the same reason `redundant_constants`
    stops at a directory boundary.

    `_output.py` is exempt for the two reasons `_PREAMBLE_EXEMPT` records: it holds
    `PATH_PREAMBLE` as a string, and it is the file the anchors are defined in.
    """
    # `script_files()` is the RESOLUTION walk - `_loader` builds its index from it
    # and must see every real file - so the filtering happens here, where a LINT
    # is the one asking. Same rule as `lint_py_files`, applied to the memoised
    # list rather than re-walking for it.
    files = (lint_py_files(script_dir) if script_dir is not None
             else [(rel, path) for rel, path in script_files()
                   if not rel.startswith(LOADER_PROBE_DIR)
                   and "/" + LOADER_PROBE_DIR not in rel])
    blanked = "\n" * PATH_PREAMBLE.count("\n")
    violations = []
    for rel, path in files:
        if os.path.basename(rel) == _PREAMBLE_EXEMPT:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src.replace(PATH_PREAMBLE, blanked), filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            violations.append((rel, 0, "cannot be read or parsed: %s" % exc))
            continue
        for line in _self_location_lines(tree):
            violations.append((rel, line,
                               "reads __file__ outside the pinned preamble - a file "
                               "that locates itself carries its own depth; take the "
                               "directory from _output's anchors instead"))
    return violations


# --- entry-point guard check --------------------------------------------------
def _is_entry(node):
    """True for `if __name__ == "__main__":`, however the comparison is spelled."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    names = [node.test.left] + list(node.test.comparators)
    return (any(isinstance(n, ast.Name) and n.id == "__name__" for n in names)
            and any(isinstance(n, ast.Constant) and n.value == "__main__" for n in names))


def _straight_line(body):
    """Statements that run when `body` runs, in order — not the ones merely DEFINED.

    A `print` inside a `def` is not output; it is a plan to produce output later, after
    the entry block has already installed the guard. Descending into function and class
    bodies would flag every script in the directory for code that cannot run first, so
    this walks the executable spine (module level, `if`/`try`/`with`/loop bodies) and
    stops at every definition boundary.
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield stmt
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, field, None)
            if isinstance(inner, list):
                for sub in _straight_line(inner):
                    yield sub
        for handler in getattr(stmt, "handlers", []) or []:
            for sub in _straight_line(handler.body):
                yield sub


def _call_lines(stmts, func):
    return [s.lineno for s in stmts
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Name) and s.value.func.id == func]


def entries_missing_guard(dirs=None):
    """Names of .py files that run as a command but do not call safe_stdio() first.

    SCOPE: `scripts/` AND `tests/`, and deliberately not `hooks/` — hooks stay
    importless on purpose (see the module docstring) and are covered by CI's cp1252
    pass instead. `tests/` is in because a test file is run exactly the way a script
    is, prints far more prose than a script does, and would take its own result down
    with it on a Windows pipe; there is no reason it is exempt except that nothing
    used to look there.

    Returns a sorted list of names, each relative to the directory it was found in.
    Two ways to be listed, because both ship the same crash: never calling it, or
    calling it after something has already printed — a guard installed after the
    output it guards is decoration.

    "First" is judged on what EXECUTES, via `ast`, not on where text appears. Every one of
    these scripts defines printing functions hundreds of lines above its `__main__` block,
    so a textual "the call must precede the first `print(`" would name every one of them
    for code that cannot possibly run before the guard. The rule is: among the statements
    that actually run — module level, then the entry block — no `print` may precede the
    `safe_stdio()` call. A file that cannot be parsed is reported rather than skipped,
    since a syntax error is a worse thing to pass over in silence.
    """
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, TESTS_DIR)
    missing = []
    for d in dirs:
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                missing.append(name)
                continue
            entries = [n for n in tree.body if _is_entry(n)]
            if not entries:
                continue  # imported module: its importer holds the guard
            runs = list(_straight_line(tree.body))
            guards = _call_lines(runs, "safe_stdio")
            prints = _call_lines(runs, "print")
            if not guards or (prints and min(prints) < min(guards)):
                missing.append(name)
    return sorted(missing)


# --- house-style AST checks ---------------------------------------------------
# The four bans: legal Python 3.8, illegal in this repo, and none of them caught by a
# version gate (vermin flags syntax the interpreter cannot run at all — every one of
# these runs fine on 3.8, it is just not this repo's style). Named here once so the
# checker and its selftest cases both read the same list rather than two lists drifting.
_BANNED_MODULES = ("typing", "dataclasses")


def _house_style_violations_in_tree(tree, name):
    """(line, what) tuples for one already-parsed module — the part `ast.walk` can see.

    Walks the WHOLE tree, not the straight-line spine `entries_missing_guard` walks:
    a walrus or a banned import is just as much a style violation buried inside a
    function body as it is at module level, so nothing here stops at a def boundary.
    """
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.NamedExpr):
            found.append((node.lineno, "walrus operator (:=)"))
        elif isinstance(node, ast.arg) and node.annotation is not None:
            # EVERY annotated parameter is an `ast.arg`, whichever list it came
            # from - positional, keyword-only, positional-only, `*args`, `**kw` -
            # so one branch covers all five. Written as a walk over each
            # FunctionDef's arg lists first, which is how `*args: str` came to be
            # missed by a version that looked complete.
            found.append((node.lineno, "annotated parameter %r" % (node.arg,)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.returns is not None:
            found.append((node.returns.lineno,
                          "return annotation on %r" % (node.name,)))
        elif isinstance(node, ast.AnnAssign):
            found.append((node.lineno, "annotated assignment"))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                found.append((node.lineno, "from __future__ import"))
            elif node.module in _BANNED_MODULES:
                found.append((node.lineno, "from %s import" % node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _BANNED_MODULES:
                    found.append((node.lineno, "import %s" % alias.name))
    return [(name, line, what) for line, what in found]


def house_style_violations(dirs=None):
    """(filename, line, what) tuples for every banned construct under `dirs`.

    House style, not the 3.8 floor: walrus, `from __future__ import ...`, `typing`,
    `dataclasses` AND ANNOTATIONS are all legal on Python 3.8, so vermin's version
    gate cannot see any of them — they are banned by convention, and conventions
    drift unless something reads the AST.

    ANNOTATIONS WERE THE HALF THAT WAS MISSING, and `CLAUDE.md` named this function
    as their enforcer the whole time. Nothing detected them: not this (which read
    walrus and two import shapes), not vermin (they are 3.8-legal), not ruff (E9+F).
    The tree had accumulated 113 of them, every one in `hooks/`, before a mutation
    asked whether the check went red and it did not. All three shapes are covered now
    — parameter, return and assignment — because a rule stated as "no annotations"
    that reads only one of the three is the same defect one step smaller. Scans every `.py` under `scripts/`, `hooks/` AND `tests/`
    RECURSIVELY through `py_files`, the same walk `entries_missing_guard` uses — and
    for the same reason a file that will not parse is reported as a violation rather
    than skipped, since a syntax error is a worse thing to pass over in silence than
    any single banned import.

    `tests/` is in scope from the first day it existed. A test file is the most
    tempting place in the tree to reach for `typing` or a walrus — nothing ships it,
    so the usual argument feels weaker — and it is also the place where a 3.8
    violation costs most: the suite that would have caught the regression is itself
    the thing that will not start.
    """
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, HOOKS_DIR, TESTS_DIR)
    violations = []
    for d in dirs:
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError) as exc:
                violations.append((name, getattr(exc, "lineno", 0) or 0,
                                    "file does not parse: %s" % exc))
                continue
            violations.extend(_house_style_violations_in_tree(tree, name))
    return violations


def _module_string_constants(tree):
    """`{NAME: (value, line)}` for MODULE-LEVEL `NAME = "literal"` assignments.

    Module level only — `tree.body`, not `ast.walk`. A same-named local inside a
    function is a different name with a different lifetime, and folding the two
    together would report a constant as duplicated by a variable that shadows it
    for three lines.
    """
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant) \
                and isinstance(value.value, str):
            found[target.id] = (value.value, node.lineno)
    return found


def _names_read(tree):
    """Every name this module reads, as a bare name OR through an attribute.

    The attribute half matters: a constant nothing in its own file reads may still
    be another module's `panel_server.CONFIG_REL`, and deleting it would break a
    reader this file cannot see. Collecting `node.attr` across the tree is coarse —
    an unrelated `x.CONFIG_REL` counts — but it errs toward silence, which is the
    right direction for a lint whose remedy is DELETION.
    """
    read = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            read.add(node.id)
        elif isinstance(node, ast.Attribute):
            read.add(node.attr)
    return read


def redundant_constants(dirs=None):
    """(filename, line, what) for a constant that is BOTH duplicated and dead.

    `panel-server.py` declared `CONFIG_REL = ".claude/audit.config.json"` and never
    read it, while importing `_panel_state`, which declares the same name with the
    same value and actually uses it. Nothing was broken and nothing would ever have
    gone red — the copy simply sat there being a second place the fact could drift
    from, and a reader grepping for the name found two answers.

    Both halves of the test are load-bearing, and the rule is narrow ON PURPOSE:

    - **duplicated** — a lone constant is a constant, not a defect.
    - **never read in its own module** — a duplicate that IS read is a real
      dependency, and removing it is a refactor with call sites to move. That is a
      different job, and a lint whose fix is sometimes "delete" and sometimes
      "restructure" gets ignored. When this fires, deletion is always correct.
    - **same directory only** — `hooks/` may not import `scripts/`, so
      `hooks/_config.CONFIG_REL` and `_panel_state.CONFIG_REL` are an IRREDUCIBLE
      pair. Reporting them would be demanding a fix the layer rule forbids, and a
      lint that cries about something nobody may fix teaches people to skip it.
      That pair is held true by `_usage_core`'s pricing cases instead — read, not
      merged.

    Scanned per directory through `py_files`, so a file one level down counts.

    `tests/` is NOT scanned, unlike the two dialect lints above, and the asymmetry is
    the point: this lint's whole remedy is DELETION, and two test files legitimately
    declaring the same fixture string are two independent fixtures, not one fact with
    two homes. Widening it here would produce a stream of reports whose correct answer
    is "no", which is how a lint stops being read.
    """
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, HOOKS_DIR)
    violations = []
    for d in dirs:
        declared = {}
        unread = {}
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                # house_style_violations already reports an unparseable file by
                # name; saying it twice adds noise, not information.
                continue
            consts = _module_string_constants(tree)
            read = _names_read(tree)
            unread[name] = set(n for n in consts if n not in read)
            for const_name, (value, line) in consts.items():
                declared.setdefault((const_name, value), []).append((name, line))
        for (const_name, value), sites in sorted(declared.items()):
            if len(sites) < 2:
                continue
            others = [n for n, _ in sites]
            for name, line in sites:
                if const_name not in unread.get(name, ()):
                    continue
                elsewhere = ", ".join(n for n in others if n != name)
                violations.append((name, line,
                                   "%s = %r is never read here and is already "
                                   "declared in %s" % (const_name, value, elsewhere)))
    return violations


# --- a count whose own evidence was truncated ----------------------------------
# F205's shape, and the reason it needed a lint of its own rather than an extension
# of either prose scan. Those two read a number that nothing prints; here the number
# IS printed, from a live source, and it is the EVIDENCE BESIDE IT that was cut. The
# claim stayed true the whole time, which is exactly why no existing check could see
# the defect and why the repair had to be mechanical: the same shape had been written
# by hand at sites across the tree, each with its own cap, and a sweep done once by
# hand would have grown a new instance the next time somebody printed a count.
_TRUNCATED_EVIDENCE = ("a count of the whole set beside a bounded slice of it, and "
                       "nothing in the same sentence says what was left out - "
                       "render the list through _output.some_of()")


def _mod_operands(node):
    """The values a `%` format consumes: a tuple's elements, or the single value."""
    if isinstance(node.right, ast.Tuple):
        return list(node.right.elts)
    return [node.right]


def _len_keys(expr):
    """`{collection: lineno}` for every `len(X)` reached anywhere inside `expr`."""
    found = {}
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "len" and len(node.args) == 1:
            found.setdefault(ast.dump(node.args[0]), node.lineno)
    return found


def _prefix_slice_keys(expr):
    """`{collection: lineno}` for every bounded `X[:n]` reached inside `expr`.

    Keyed by every name the SLICED EXPRESSION mentions and not only by the whole
    of it, because `sorted(bad)[:3]` is still a bounded slice of `bad` — one of
    the spellings F205's siblings were written in, and the one a key built from
    the outermost expression alone walks straight past.

    The upper bound may be any expression, not just a literal. A cap held in a
    variable is the same cap, and the site that first proved that is the one
    already doing this correctly: `_warning_groups` slices to a `limit` argument
    and then states the remainder, so a rule reading only literals would have
    credited it for nothing and missed every sibling written that way.
    """
    found = {}
    for node in ast.walk(expr):
        if not isinstance(node, ast.Subscript):
            continue
        window = node.slice
        if not isinstance(window, ast.Slice) or window.upper is None \
                or window.lower is not None or window.step is not None:
            continue
        for inner in ast.walk(node.value):
            if isinstance(inner, (ast.Name, ast.Attribute, ast.Subscript)):
                found.setdefault(ast.dump(inner), node.lineno)
    return found


def _remainder_keys(expr):
    """The collections whose UNSHOWN part `expr` states, as `len(X) - <anything>`.

    STRUCTURAL RATHER THAN A SEARCH FOR THE WORDS. The tail phrase belongs to
    `some_of()` and to the two hand-written sites that predate it, and they do not
    agree on it — a lint reading for `and N more` would pin one wording and call
    the others defects, while this reads the only thing they have in common: the
    remainder is computed from the same count.
    """
    stated = set()
    for node in ast.walk(expr):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            stated.update(_len_keys(node.left))
    return stated


def truncated_evidence_violations(dirs=None):
    """(filename, line, what) for a count whose evidence was silently truncated.

    THE SHAPE, in one sentence: inside one `%` format, `len(X)` is interpolated,
    a bounded prefix slice of X is interpolated, and nothing in that same format
    states the remainder. All three halves are load-bearing:

    - **the count** — a bounded slice with no count beside it claims nothing, so
      `", ".join(drift[:3])` is a line this must stay quiet about. It is still a
      truncation, and a reader may still want the rest; it is not this defect,
      because nothing in it is untrue.
    - **the same collection** — `s[:12]` beside `len(trail["missing"])` is a SHA
      abbreviated for width, not evidence dropped from the set being counted.
    - **the remainder unstated** — `len(X) - n` anywhere in the same format is
      the repair, and `hooks/meter-usage.py` was written that way before this
      existed. A hook may not import `scripts/`, so it cannot reach `some_of()`
      and never will; reading the property rather than the wording is what keeps
      it correct instead of exempt.

    WHAT IT CANNOT SEE, in the same direction every scan in this file errs: a
    count and a slice that reach one sentence through two different format
    strings, a cap applied by a counting loop or by `islice` rather than by a
    slice, a truncated mapping, and any file outside `dirs` — `tools/` is not in
    the default, because the path to that directory already has two private homes
    and adding a third to widen a scope is a decision of its own. So a clean
    result means "none of this shape here", not "no truncated evidence".
    """
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, HOOKS_DIR, TESTS_DIR)
    violations = []
    for d in dirs:
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                # house_style_violations already reports an unparseable file by
                # name; saying it twice adds noise, not information.
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.BinOp) \
                        or not isinstance(node.op, ast.Mod):
                    continue
                if not (isinstance(node.left, ast.Constant)
                        and isinstance(node.left.value, str)):
                    continue
                counted, sliced, stated = {}, {}, set()
                for operand in _mod_operands(node):
                    counted.update(_len_keys(operand))
                    sliced.update(_prefix_slice_keys(operand))
                    stated.update(_remainder_keys(operand))
                for key in sorted(counted):
                    if key in sliced and key not in stated:
                        violations.append((name, sliced[key],
                                           _TRUNCATED_EVIDENCE))
    return sorted(violations)


# --- selftest coverage --------------------------------------------------------
# THE RULE WAS TRANSITIONAL AND IS NOT ANY MORE. While the move from inline
# `--selftest` blocks to `tests/` was under way it read "every `.py` under scripts/
# and hooks/ has EITHER an inline suite OR a file in tests/" - and a rule with an OR
# in it is exactly the shape that lets a file with NEITHER through, because the
# natural way to write it is `inline or covered` and that reads green for a file
# nobody has looked at. So nothing here has ever returned a boolean: every production
# file is placed in exactly one of four classes, and the caller asserts the COUNTS.
#
# Every one of them has moved, so the OR has nothing left to permit. `inline` is a
# DEFECT class beside `both` and `neither`: a file that ships a new inline suite is
# named here rather than quietly accepted as the other half of a choice that no
# longer exists. That is a real tightening and not bookkeeping - a suite added inline
# would be run by CI's sweep, would pass, and would leave `tests/` looking complete
# while one module's cases lived somewhere else entirely.
#
# `both` is a defect and not a belt-and-braces bonus: two suites for one module drift,
# and the day they disagree there is no answer to "which one is the test". `neither`
# is the file the OR-shaped rule hid.
#
# ASSEMBLED, NOT WRITTEN OUT, and the reason is this module's own classification. The
# proxy below asks whether a file's STRING CONSTANTS carry both `--selftest` and the
# contract; spelled as one literal here, `_CONTRACT` IS such a constant, `__main__`
# supplies the other, and this file classified ITSELF as carrying a suite - measured,
# `both: ['scripts/_output.py']`, on the first run after its cases moved out. Same
# self-matching class as `_harness`' m1 needle and `_refs`' fixture constants: a
# scanner that lives in the tree it scans must not plant its own needle there.
_CONTRACT = "cases " + "passed"

_TEST_PREFIX = "test_"

# The classes a build must be empty of. Named once, here, rather than re-spelled as a
# tuple of keys at each call site - the question "is `inline` a defect this week" has
# exactly one answer and it belongs beside the classifier that produces the classes.
_DEFECT_CLASSES = ("inline", "both", "neither", "orphans", "collisions", "unreadable")


def _test_name_for(rel):
    """The `tests/` filename that covers the production file `rel`.

    Hyphens become underscores because a hyphenated name is not importable and never
    will be: `import test_migrate-manifest` is a syntax error, so the entry points -
    which are hyphenated BY CONVENTION here, to mark a thing something invokes - could
    not otherwise have a test module at all. Stated in code, in one place, because CI
    and the guide both need the same answer and a rule spelled twice is a rule with a
    disagreement waiting in it.
    """
    return "%s%s.py" % (_TEST_PREFIX, os.path.basename(rel)[:-3].replace("-", "_"))


def _carries_inline_selftest(path):
    """True / False / None (unreadable or unparseable) for "this file has its own suite".

    Judged on the file's STRING LITERALS carrying both `--selftest` and the
    `N/M cases passed` contract - the same literal CI greps for in a suite's OUTPUT.
    A file with a `_selftest()` that never prints the contract is not counted as
    inline here, and is also a file CI already fails by name; the two agree about
    what a suite is, which is the only property this proxy has to have.

    READ OFF THE AST, AND NOT OFF THE TEXT, for a reason found the hard way: the
    first version matched the raw source, and the COMMENT this module's own migration
    added to each migrated file - "it deliberately does NOT print the `N/M cases
    passed` contract" - contains the literal, so two of the three pilots came back
    classified as `both`. A comment is not in the AST at all, which removes that
    whole class rather than asking the next person to phrase a comment carefully.

    EVERY DOCSTRING IS DROPPED, not only the module's, and the widening was forced by
    THIS module. The first version dropped `tree.body[0]` alone, on the argument that
    a module docstring is the one place a file legitimately DESCRIBES its suite ("its
    cases live in ...") and a description is not an implementation. That argument
    was right and under-applied: when `_output.py`'s own cases moved out it came back
    classified `both`, because two of ITS function docstrings - this one and
    `covered_repo_paths`' - spell the contract while explaining what the contract is.
    A string that is a STATEMENT is prose wherever it sits; a suite prints the
    contract, and a `print(...)` argument is not a statement. So the filter is "an
    `ast.Expr` whose value is a string", at any nesting depth, which removes the class
    instead of asking each future docstring to phrase itself around a lint.

    Both ways of being wrong here are loud - a suite misread as migrated is reported
    as `neither` or `both`, and a migrated file misread as inline is failed by CI's
    sweep for not printing the contract - so the proxy never fails silently.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=os.path.basename(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None
    prose = set(id(node.value) for node in ast.walk(tree)
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str))
    texts = [node.value for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and id(node) not in prose]
    return (any(_CONTRACT in t for t in texts)
            and any("--selftest" in t for t in texts))


def selftest_coverage(script_dir=None, hooks_dir=None, tests_dir=None):
    """Where every production suite lives right now — a classification, not a verdict.

    Returns a dict of sorted lists, keyed by what is true of a file rather than by
    whether it is allowed:

      covered     no inline suite, and `tests/test_<name>.py` exists — the ONLY
                  clean class, and since the migration finished, all of them
      inline      DEFECT: carries its own `--selftest` printing the contract and has
                  no test file. Clean while the migration ran and a regression now:
                  CI's sweep would run it, it would pass, and `tests/` would look
                  complete with one module's cases living somewhere else
      both        DEFECT: an inline suite AND a test file. Which one is the test?
      neither     DEFECT: no suite anywhere. The file the OR-shaped rule would hide
      orphans     DEFECT: a `tests/test_*.py` naming no production file that exists
      collisions  DEFECT: two production files mapping to one test name (`a-b.py`
                  and `a_b.py` both want `test_a_b.py`). `_deps` forbids two files
                  sharing a BASENAME; this is the same hazard one transform later
      unreadable  DEFECT: a production file that could not be read or parsed
      defects     every name in every defect class above, each tagged with the class
                  it fell into — so a caller asserts ONE thing and a failure names
                  the file rather than only a count
      total       how many production files were classified — `checked`, so that
                  "no defects" and "nothing was looked at" cannot print the same way

    Production names are kind-prefixed (`scripts/_cli_fmt.py`, `hooks/remind-tdd.py`)
    so a violation names a path the reader can open; orphans are named `tests/x.py`.
    `tests/_harness.py` is not a test file and is not an orphan candidate: the rule is
    about `test_*.py`, and the harness is the thing they all import.

    The end state is asserted, not hoped for: this returns 0 inline and every
    production file under `covered`, and the case that pins the `covered` list is the
    one that had to be edited to say so.
    """
    script_dir = script_dir or SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else HOOKS_DIR
    tests_dir = tests_dir if tests_dir is not None else TESTS_DIR

    test_files = set(rel for rel, _path in lint_py_files(tests_dir)
                     if os.path.basename(rel).startswith(_TEST_PREFIX))

    out = {"inline": [], "covered": [], "both": [], "neither": [],
           "orphans": [], "collisions": [], "unreadable": [], "defects": [],
           "total": 0}
    claimed = {}
    for kind, directory in (("scripts", script_dir), ("hooks", hooks_dir)):
        if not os.path.isdir(directory):
            continue
        for rel, path in lint_py_files(directory):
            named = "%s/%s" % (kind, rel)
            out["total"] += 1
            expected = _test_name_for(rel)
            claimed.setdefault(expected, []).append(named)
            inline = _carries_inline_selftest(path)
            if inline is None:
                out["unreadable"].append(named)
                continue
            covered = expected in test_files
            if inline and covered:
                out["both"].append(named)
            elif inline:
                out["inline"].append(named)
            elif covered:
                out["covered"].append(named)
            else:
                out["neither"].append(named)

    for name in sorted(test_files - set(claimed)):
        out["orphans"].append("tests/%s" % name)
    for expected in sorted(claimed):
        if len(claimed[expected]) > 1:
            out["collisions"].append("tests/%s <- %s"
                                     % (expected, ", ".join(sorted(claimed[expected]))))
    for key in ("inline", "covered", "both", "neither", "unreadable"):
        out[key].sort()
    out["defects"] = ["%s %s" % (cls, name)
                      for cls in _DEFECT_CLASSES for name in out[cls]]
    return out


# --- numbers written into prose -----------------------------------------------

# NO REGEX ON PURPOSE. This module is the anchor every other `.py` imports, and
# it deliberately carries only `ast`, `os` and `sys`; adding `re` here would put
# a compile on the import path of every hook that must start fast on every tool
# call. Word scanning is enough for shapes this narrow, and it is faster.
#
# The shapes below are PRESENT-TENSE claims. Historical prose ("down from the
# seventeen", "it stood at 70 that day") stays writable on purpose: the past
# tense is how a decision record explains itself, and forbidding it would push
# the rot into vaguer wording rather than removing it.
#
# THREE FAMILIES, EACH ADOPTED ONLY AFTER MEASURING ITS SITES AND HOW MANY WERE
# ALREADY WRONG. An extension that fires on forty correct lines is worse than no
# extension: it gets routed around, and then it is its own defect class.
#
#   cardinality  "its N cases", "N cases live in", "--selftest (N cases)"
#                51 sites when adopted, 9 already wrong.
#   persistence  "`NAME` stayed at N", "`NAME` is still N" - a claim that a
#                number HAS NOT CHANGED as of writing. 2 sites, BOTH wrong
#                (`KNOWN_LAYER_DEBT` written as 17 twice against a real 1: F43,
#                which is F39 one document over).
#   completeness "all N of them", "all N ... have/are" - a claim that a
#                collection's whole is N. 2 sites beyond the first shape, BOTH
#                wrong (48 against a real 83).
#
# TWO MORE WERE SURVEYED AND REFUSED - a measurement family and a before/after
# family - and what the survey found is in `prose_number_claims()`'s list of what
# this cannot see, beside the other gaps, because a refusal is only useful to the
# next author if it is filed where they will look for the shape.
#
# WHY EVERY ONE OF THEM TAKES "REMOVE THE NUMBER" AND NOT "REQUIRE THE BASIS".
# Both remedies satisfy the house rule on paper. What separated them was a
# measurement taken the day this was written: `CONTRIBUTING.md`'s files-over-500
# figure DOES name its basis -- `tools/count-ui-pins.py`, a command that really
# does print that number -- and it had rotted anyway, in both of its halves (it
# read 21 where the tool printed 22, and named `_deps.py` at 1,479 lines where
# the file held 1,621). A basis makes a claim CHECKABLE; only deleting the
# number makes it un-rottable, because nothing runs a command on a reader's
# behalf. So the basis stays the escape hatch for a number a reader genuinely
# acts on, and is not the remedy of choice for one that restates a live source.
_CASE_WORDS = ("cases", "case")


# --- a numeral, in either spelling ------------------------------------------------
# A count SPELLED OUT is the same claim as a count in digits, so it is read by the
# shapes above rather than by a grammar of its own. THE TABLE'S OMISSIONS ARE THE
# DESIGN. A bare number-word is not a claim, it is English, and the shapes are all
# that separates the two.
#
# WHERE THE BOUNDARY CAME FROM, and it is a measurement rather than taste. With the
# small words admitted as well, this lint and `_deps.doc_prose_numbers()` between
# them reported nineteen sites across `hooks/`, `scripts/` and the three prose
# documents on the day this landed - every one of them below `ten`, and only two were
# the defect. Of the rest: thirteen were an ANAPHOR pointing at an enumeration the
# reader can see in the same breath ("all three are honest about what they are:",
# and the three are the next lines), which is a number carrying its own basis; one
# was a RATE, one a UNIQUENESS claim whose sentence dies if the word goes, one a
# COUNTERFACTUAL about cases that do not exist, and one a noun compound the shape
# misread. Sixteen good sentences would have had to be rewritten to catch two
# marginal ones, and the pressure after that is to loosen a shape.
#
# At `ten` and above the same run reported four sites, and three had already rotted -
# two spellings of a check count that had grown by three, and a file count that had
# doubled. That is the hit rate the earlier families were adopted on.
#
# So the band under `ten` is an UNDER-count, and it is documented as one rather than
# closed. Widening it is the repair to refuse: a pattern loosened to admit prose
# stops catching the thing it exists for, and the case that would have noticed is
# the one being changed.
_NUMERAL_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy",
                 "eighty", "ninety")

# Read ONLY as the tail of a tens word, never on its own. A hyphenated compound is
# punctuation `_words()` has already dropped, so a tens word and its tail arrive as
# two tokens; without this the compounds this tree really writes would read as a
# number followed by an unrelated word and slip every shape.
_NUMERAL_TAILS = ("one", "two", "three", "four", "five", "six", "seven",
                  "eight", "nine")

_NUMERAL_WORDS = ("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
                  "sixteen", "seventeen", "eighteen", "nineteen",
                  "hundred", "thousand") + _NUMERAL_TENS

# NOT the same table as `config/_help._COUNT_WORDS`, and merging them would break
# both. That one RESOLVES a word to a number by its index, against a phrase a regex
# has already pinned, so it needs exactly the small words this one leaves out. This
# one RECOGNISES a numeral in arbitrary prose, where those same words are ambiguous.
# A single table serving both would have to be ordered and complete, which is the
# widening the second-direction case exists to stop.


def _numeral_span(w, i):
    """`(text, index past it)` if a numeral starts at `w[i]`, else None.

    ONE entry point for both spellings, so no shape can end up reading a digit and
    a word by different rules. Returns the text rather than the value: the finding
    quotes the claim back, and nothing here compares magnitudes.
    """
    tok = w[i]
    if tok.isdigit():
        return (tok, i + 1)
    if tok not in _NUMERAL_WORDS:
        return None
    if tok in _NUMERAL_TENS and w[i + 1:i + 2] and w[i + 1] in _NUMERAL_TAILS:
        return ("%s-%s" % (tok, w[i + 1]), i + 2)
    return (tok, i + 1)

# Token sequences that assert a number has not changed AS OF WRITING. The past
# tense of `stayed`/`remained` is not what makes them history: "it stayed at N"
# with no anchor to a past moment means "and it is N now", which is why
# `_deps.py`'s own F39 note classifies exactly that spelling as the defect.
# `was still N` and `stood at N` are deliberately absent - those ARE anchored to
# a past moment, and `pn4` pins them as writable.
#
# EVERY EXAMPLE IN THIS SECTION SPELLS ITS NUMBER `N` ON PURPOSE. A lint that
# scans the tree it lives in must not plant its own needle there - `_refs.py`
# learned it with fixture paths and this module learned it twice on its own
# first run. A real digit in an example below is a real finding, and exempting
# the file would be the wrong repair.
_PERSISTS = (
    ("unchanged", "at"),
    ("remained", "at"),
    ("remains", "at"),
    ("remain", "at"),
    ("stayed", "at"),
    ("staying", "at"),
    ("stays", "at"),
    ("is", "still"),
    ("are", "still"),
    ("remains",),
)

# A completeness claim is present-tense only when it carries one of these.
# "all N files CARRIED their own copy" is a sentence about the world before a
# migration and stays writable; "all N files HAVE moved" is a claim about now.
# A whitelist of auxiliaries is the only half of that distinction a word scanner
# can make honestly - there is no way to recognise an arbitrary past-tense verb
# without a lexicon, so the miss is documented rather than guessed at.
_PRESENT_AUX = ("is", "are", "has", "have")

_BASIS_MARKERS = ("python3", "grep", "for f in")


# A separator that stays INSIDE a token when digits flank it. Nothing else survives
# tokenizing, and the two characters are chosen rather than guessed: one makes a
# ratio, the other a decimal.
_NUMBER_SEPARATORS = "./"


def _is_digit_char(ch):
    """One CHARACTER, is it a digit - the tokenizer's question, not the shapes'.

    Named so that the two questions cannot be confused for one. `_numeral_span()`
    asks whether a TOKEN is a numeral and is the single entry point every shape
    reads its number through; this asks whether a character may hold a separator
    inside a token, which happens before any shape sees anything. A case counts
    both occurrences and would go red on a third, so a family added later cannot
    quietly grow a numeral reader of its own out of a character test.
    """
    return ch.isdigit()


def _words(line):
    """`line` as lowercase alphanumeric tokens - except a separator INSIDE a number.

    `7/7` and `0.01` come back as ONE token each rather than as two numerals, and a
    token carrying a separator is not a numeral to `_numeral_span()`. That is the
    whole rule, and it is a NARROWING adopted when the scan below stopped being
    scoped to `scripts/`: a ratio is a tally and a decimal is a measurement, and
    neither is a count of things.

    THE MEASUREMENT THAT BOUGHT IT. The tally this whole tree prints - the
    `<passed>/<total>` line every suite ends with - appears outside `scripts/` as a
    fixture, as a regex and as an asserted literal, in the sweep runner, the test
    harness and half a dozen suites. Not one of those is a claim about how many
    cases exist, and none of them can be reworded away: the bytes ARE the contract
    CI greps for. Without this rule the widened scan reported every one of them.

    WHAT IT GIVES UP, said rather than left to be found: a cardinality genuinely
    written as a fraction stops being read. Nobody writes one that way, and the
    direction is an under-count - the direction `prose_number_claims()` already
    documents as the only one these shapes can be wrong in.

    AN UNDERSCORE INSIDE A WORD IS THE SAME NARROWING, one character further. An
    identifier is one word, which is a fact about TEXT and not about Python - so
    this does not teach the scanner to read code, it stops it splitting a name into
    pieces that were never written. Without it a numeric index in front of
    `case_id(` yielded a numeral and the noun `case`, and the line reported itself
    as a cardinality claim with no prose on it at all. Measured across the derived
    set and three tree states before adopting: it removes exactly that hit and
    loses nothing.

    A THOUSANDS COMMA IS DELIBERATELY NOT HERE. A grouped number is still a count,
    so the comma keeps being dropped, which leaves two numerals and lets the second
    one keep whatever noun follows it. That is how a line pairing a line count with
    a case count still reports its live half.

    THE WALK ITSELF IS `_tokenize()`, which answers this question and the sentence
    question in one pass. This name stays the contract every shape reads and the
    cases pin.
    """
    return _tokenize(line)["words"]


# A sentence terminator, and it is read as one only where the character after it is
# not alphanumeric - which is what keeps `x.py has` one sentence while `x.py. Next`
# is two, with no table of abbreviations and no lookahead past one character.
_SENTENCE_ENDS = ".!?"


def _in_dot_run(text, i):
    """True if `text[i]` is one stop of an ellipsis rather than a sentence end.

    A run of stops is a MARKUP elision here, not a full stop - the panel's own
    docstring writes a tag pair with the body elided, and reading each stop as a
    boundary cut that one sentence into four, which threw away the past tense the
    sentence opened with and reported its history as a claim.
    """
    before = text[i - 1:i] if i else ""
    return text[i] == "." and "." in (before, text[i + 1:i + 2])


def _tokenize(line):
    """`{"words", "sentence"}` - `line`'s tokens, and which sentence each sits in.

    ONE walk for both answers, because they read the same characters and the
    hardest rule is shared: a separator kept INSIDE a number is not a sentence
    end. A second walk asking only about boundaries would be a second home for
    that rule, and the two would disagree about a decimal the first time either
    was edited.

    `sentence` is an ordinal PER TOKEN, parallel to `words`, rather than a list
    of sentences. Every shape below indexes the line's tokens positionally, so
    the tokens have to arrive as one flat list; which sentence a token sits in is
    an extra fact about it, not a different shape of the same data.
    """
    low = line.lower()
    words, sentence = [], []
    cur, index = [], 0
    for i, ch in enumerate(low):
        if ch.isalnum():
            cur.append(ch)
            continue
        if (ch in _NUMBER_SEPARATORS and cur and _is_digit_char(cur[-1])
                and _is_digit_char(low[i + 1:i + 2])):
            cur.append(ch)
            continue
        if ch == "_" and cur and low[i + 1:i + 2].isalnum():
            cur.append(ch)
            continue
        if cur:
            words.append("".join(cur))
            sentence.append(index)
            cur = []
        if (ch in _SENTENCE_ENDS and not low[i + 1:i + 2].isalnum()
                and not _in_dot_run(low, i)):
            index += 1
    if cur:
        words.append("".join(cur))
        sentence.append(index)
    return {"words": words, "sentence": sentence}


def _backtick_chunks(line):
    """The backticked spans of `line`, in order."""
    return line.split("`")[1::2] if "`" in line else []


def _carries_basis(line, following):
    """True if this claim names the command that re-derives it.

    `following` is the NEXT line, and it is read for one reason: prose wraps.
    Every document here is hard-wrapped, so "print it with" routinely ends a
    line and the command begins the next one. Judging the claim by its own line
    alone would call a claim that HAS satisfied the house rule a violation, and
    the repair for that false positive is to delete the basis - the exact
    opposite of what this is for.
    """
    for chunk in _backtick_chunks(line) + _backtick_chunks(following or ""):
        for marker in _BASIS_MARKERS:
            if marker in chunk:
                return True
    return False


def _names_code(line):
    """True if the line quotes a code identifier in backticks.

    THE GATE ON THE PERSISTENCE FAMILY, and it is the reason that family can be
    adopted at all. A persistence claim about a number with a live source is a
    claim about a NAMED thing in this tree, and this repo writes code names in
    backticks; a persistence claim with no code name on the line is prose about
    something the tree does not hold, where neither remedy fits. The measured
    case is `hooks/_config.py`: "the result is still N characters" is the width
    of an invariant format string in a counterfactual about `time.localtime()`,
    it is correct, removing the number would destroy the sentence, and it names
    no code on that line. Without this gate the shape would fire on it.

    A space inside the span means it is a command or a phrase (`_deps.py
    --render` is still a name by its first token, so the check is on the span
    having a spaceless form, not on the whole span).
    """
    for chunk in _backtick_chunks(line):
        if chunk.strip() and " " not in chunk.strip():
            return True
    return False


# Past-tense markers. The broadest family below ("N cases", with no "its" and no
# "live in" in front of it) is the only one wide enough to catch ordinary
# recollection, and recollection is exactly what a decision record is made of.
# Anything on this list means the SENTENCE is talking about THEN, so the number is
# not a claim about now and must stay writable. The sentence and not the line -
# `_historical_sentences()` below carries the two directions the line got wrong.
_PAST = ("was", "were", "had", "used", "stood", "down", "up", "once",
         "previously", "then", "before", "originally", "until", "old")


def _looks_historical(w):
    """True if these tokens are recollection rather than a present-tense claim."""
    for tok in w:
        if tok in _PAST:
            return True
    return False


# What a hard-wrapped sentence may trail after its stop: quotes, brackets and
# markdown emphasis. Without them a bolded sentence ending in a stop reads as
# unfinished, and the next line would inherit a tense that is not its own.
_SENTENCE_TAIL = " \t\"'`)]}*_"


def _ends_sentence(text):
    """True if `text` finishes a sentence, so a following line starts a new one."""
    tail = text.rstrip(_SENTENCE_TAIL)
    return bool(tail) and tail[-1] in _SENTENCE_ENDS


def _edge_sentences(text):
    """`{"first", "last"}` - the tokens of `text`'s opening and closing sentences.

    The two halves a wrap can join to: a line continues whatever sentence its
    predecessor left open, and leaves one open for its successor to finish. Both
    come from one tokenize because both are that walk's answer, and a text with no
    tokens yields two empty lists rather than None - there is nothing to join,
    which is an answer and not a failure.
    """
    tok = _tokenize(text or "")
    words, sent = tok["words"], tok["sentence"]
    if not words:
        return {"first": [], "last": []}
    return {"first": [w for w, k in zip(words, sent) if k == sent[0]],
            "last": [w for w, k in zip(words, sent) if k == sent[-1]]}


def _historical_sentences(line, preceding, following):
    """The ordinals of `line`'s sentences that read as recollection, not a claim.

    A SENTENCE, NEVER THE PHYSICAL LINE, and F76 is both directions of that
    difference, met on one day. A past marker in the sentence BEFORE the number -
    two clauses earlier on the same line, about something else entirely - was
    excusing a live count: the escape reading too widely. And a marker in the SAME
    sentence one line up was not reaching the number at all, because prose wraps:
    the escape reading too narrowly. One scope fixes both, and the first half is
    why this is not a loosening - a marker that used to excuse a whole line now
    excuses one sentence of it.

    The join reaches ONE line each way, the window `_carries_basis()` already
    reads and for the same reason. A sentence running further keeps its marker out
    of reach and its number reported, which is the direction a reader meets by
    disagreeing with a finding; the other direction is met by silence.
    """
    tok = _tokenize(line)
    words, sent = tok["words"], tok["sentence"]
    if not words:
        return set()
    before = ([] if _ends_sentence(preceding or "")
              else _edge_sentences(preceding)["last"])
    after = [] if _ends_sentence(line) else _edge_sentences(following)["first"]
    out = set()
    for s in set(sent):
        scope = [w for w, k in zip(words, sent) if k == s]
        if s == sent[0]:
            scope = before + scope
        if s == sent[-1]:
            scope = scope + after
        if _looks_historical(scope):
            out.add(s)
    return out


def _cardinality_claim(tok, historical):
    """"its N cases" / "N cases live in" / "--selftest (N cases)" / "all N of them".

    `historical` is the set of sentence ordinals `_historical_sentences()` read as
    recollection. It arrives as an argument rather than being derived here because
    that reading needs the neighbouring LINES, which a shape holding one line's
    tokens cannot see.
    """
    w, sent = tok["words"], tok["sentence"]
    for i in range(len(w)):
        span = _numeral_span(w, i)
        if span is None:
            continue
        num, end = span
        nxt = w[end] if end < len(w) else ""
        prv = w[i - 1] if i else ""
        if nxt in _CASE_WORDS:
            if prv == "its":
                return "its %s %s" % (num, nxt)
            if w[end + 1:end + 3] == ["live", "in"]:
                return "%s %s live in" % (num, nxt)
            if "selftest" in w[max(0, i - 4):i]:
                return "--selftest (%s %s)" % (num, nxt)
        # "all N of them", the shape selftest_coverage's own docstring used
        if prv == "all" and w[end:end + 2] == ["of", "them"]:
            return "all %s of them" % num
        # The BARE shape: a number sitting in front of "cases", however it is
        # introduced -- "the N cases in tests/", "across N cases", "the ~N cases
        # below". Every example here spells N on purpose: written with real
        # digits, this comment is itself a finding, and the first draft of it
        # was. Fix the example, never exempt the file.
        #
        # Adopted on the measurement, not on taste: eight sites, of which SEVEN
        # were already wrong -- two claiming a suite that has since grown by
        # forty-four, one short by ten, three short by twenty-one, one short by
        # forty-six. The eighth was correct that day, which is the whole
        # argument: it is one added case away from joining the other seven.
        #
        # This family is wide enough to catch ordinary recollection, so it is the
        # one that has to ask whether the SENTENCE is talking about THEN. Skipping
        # that check turns "it stood at N cases that day" into a violation and
        # makes the decision record unwritable. The sentence the NUMERAL sits in,
        # not the line: a marker two clauses back, about something else, used to
        # excuse a live count on the same line.
        if nxt in _CASE_WORDS or (nxt == "selftest" and w[end + 1:end + 2] and
                                  w[end + 1] in _CASE_WORDS):
            if sent[i] not in historical:
                return "%s cases" % num
    return None


def _persistence_claim(line, w):
    """"`NAME` stayed at N" / "`NAME` is still N" - F43's shape, and F39's."""
    if not _names_code(line):
        return None
    for i in range(len(w)):
        span = _numeral_span(w, i)
        if span is None:
            continue
        for phrase in _PERSISTS:
            n = len(phrase)
            if i >= n and tuple(w[i - n:i]) == phrase:
                return "%s %s" % (" ".join(phrase), span[0])
    return None


def _completeness_claim(w):
    """"all N <noun> have/are ..." - a cardinality for a whole, in the present.

    The auxiliary must fall within three tokens of the number. That window is
    not arbitrary: it separates "all N files have moved" (a claim about now)
    from "pins all N alias lines this module's names ARE re-exported through"
    (a count, and a relative clause seven tokens later that has nothing to do
    with it). Both spellings are in this tree, and a window of three is what
    tells them apart.
    """
    for i in range(len(w)):
        if not i or w[i - 1] != "all":
            continue
        span = _numeral_span(w, i)
        if span is None:
            continue
        num, end = span
        for aux in w[end:end + 3]:
            if aux in _PRESENT_AUX:
                return "all %s ... %s" % (num, aux)
    return None


def _prose_number_claim(line, following=None, preceding=None):
    """The claim's text if this line writes a present-tense number, else None.

    A line that names the command recomputing the number is NOT a finding: the
    house rule is that a claim carries the basis that makes it true, and such a
    line has done exactly that.

    `following` and `preceding` are the neighbouring PHYSICAL lines, and neither
    is decoration: every document here is hard-wrapped, so a claim's basis and
    the tense of the sentence carrying it both routinely land one line away from
    its number. Called with neither - which is what a caller handing over a
    single string means - this reads the line as one whole sentence.

    THIS IS THE ONLY DEFINITION OF THE SHAPES. `_deps` scans the documents and
    delegates here rather than restating them; a second copy of the pattern
    would be precisely the defect both scanners exist to catch, and a case in
    each suite asserts there is no second `def`.
    """
    if _carries_basis(line, following):
        return None
    tok = _tokenize(line)
    w = tok["words"]
    return (_cardinality_claim(tok, _historical_sentences(line, preceding, following))
            or _persistence_claim(line, w)
            or _completeness_claim(w))


# --- what the prose scan reads ------------------------------------------------
# DERIVED, NOT LISTED, and that is the whole of this section. The scanned set used
# to be a hand-written pair - `.py` under `hooks/` and `scripts/`, plus three named
# documents - so everything else in the repo was unguarded, and that is where the
# claims had gone: a part count in `scripts/ui/*/README.md` (three sites, two of
# them already wrong), a suite size in a `tests/` docstring (most of them wrong),
# and a file count in the prover under `tools/` - the directory holding the sweep
# runner, the gate parity check and the mutation table, every one of which exists
# to talk about counts. The tree's own counting tools were the unaudited part.
#
# So the set is now every `.py` and every `.md` the walk reaches, and a file added
# to this repo is scanned by default. Excluding one is a row below carrying a
# reason a reader can disagree with - the shape `tools/gate-parity.py` uses for a
# gate a side may legitimately not name, and `_refs.EXCLUDED` for the documents
# where a stale path is correct rather than broken.
#
# A row is a repo-relative path or, ending in `/`, a directory prefix.
PROSE_SCAN_EXEMPT = (
    ("CHANGELOG.md",
     "released history: a count in a shipped entry was true of that release, and "
     "rewriting released history to keep a lint quiet is worse than the lint"),
    ("docs/design/",
     "dated design records: they describe the tree as it was at the decision, so "
     "the numbers in them are history in the same way a past tense is"),
    ("docs/audit/audit-report.md",
     "generated from the manifest on every render, so a count in it is derived "
     "rather than written. It is also gitignored as a FILE, which this walk does "
     "not read, so without this row the finding set would move with whether "
     "anybody had rendered a report in this checkout"),
    ("plugins/audit/tests/test__output.py",
     "holds THIS scanner's own fixtures: every shape it recognises appears there "
     "as an argument spelled on purpose, because a text scanner can only be shown "
     "to fire by handing it the literal it must recognise. The house rule is to "
     "build a forbidden literal rather than write one, and here the literal IS "
     "the argument under test - building it would move the needle out of the "
     "fixture and into the assertion. The cost is the thing to disagree with: a "
     "genuinely stale count in this one suite is unguarded"),
    ("plugins/audit/tests/test__deps.py",
     "the same, for the document half - its cases hand the shapes to "
     "`_deps.doc_prose_numbers()` as fixture documents"),
)


def prose_scan_exemption(rel):
    """The declared reason `rel` is out of the prose scan, or None."""
    for path, why in PROSE_SCAN_EXEMPT:
        if path.endswith("/"):
            if rel.startswith(path):
                return why
        elif rel == path:
            return why
    return None


def prose_scan_set(exts, repo_root=None):
    """`{"paths", "candidates", "exempted", "problem"}` - what the prose scan reads.

    `problem` is a string or None, and it is the loud half. A tree whose
    `.gitignore` cannot be read yields no paths, and "read no files" must not print
    the way "found no claims" prints - which is the whole reason this returns the
    candidate count alongside the paths rather than just the paths.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    patterns, problem = _ignored_dirs(root)
    if problem is not None:
        return {"paths": [], "candidates": 0, "exempted": [],
                "problem": ".gitignore is %s" % problem}
    candidates = kept_files(root, patterns, tuple(exts))
    exempted = [rel for rel in candidates
                if prose_scan_exemption(rel) is not None]
    skip = set(exempted)
    return {"paths": [rel for rel in candidates if rel not in skip],
            "candidates": len(candidates), "exempted": exempted,
            "problem": None}


# Two terms, F69's shape, and adopted for F69's reason: an absolute floor answers
# "did this read return anything at all" and nothing more, so a set that had lost
# most of the tree would still clear it. The derived term measures the SCANNED set
# against the CANDIDATE set the same walk produced, which is the best available
# evidence of how big the real set is - and it is the term that fires when a row
# in the table above grows to swallow a directory.
#
# WHAT IT COUPLES, said rather than implied: if the walk itself collapses, both
# terms fall together and this stays green. That direction is not covered here and
# must not be, because a floor derived from the thing it measures cannot cover it -
# the cases hold the scanned set against a PLAIN recursive walk of the directories
# that have to exist, which needs no `.gitignore` and so cannot fail the same way.
SCAN_FLOOR_MINIMUM = 8
SCAN_FLOOR_DIVISOR = 2


def scan_floor(candidates):
    """The fewest files a prose scan may read before its result stops being evidence."""
    return max(SCAN_FLOOR_MINIMUM,
               (candidates + SCAN_FLOOR_DIVISOR - 1) // SCAN_FLOOR_DIVISOR)


def prose_claims_in(root, rels):
    """[(rel, lineno, claim), ...] - every claim in `rels`, read relative to `root`.

    ONE read loop for both halves of the scan. `_deps` keeps its own only for the
    caller that hands it absolute fixture paths; the tree is read here.

    An unreadable file is NAMED, never skipped - F21's rule. A skip would return
    the same empty list a clean file returns, and "nothing to report" would then
    mean either "clean" or "could not look".
    """
    out = []
    for rel in rels:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            out.append((rel, 0, "<unreadable: %s>" % exc))
            continue
        lines = text.split("\n")
        for lineno, line in enumerate(lines, 1):
            nxt = lines[lineno] if lineno < len(lines) else ""
            prv = lines[lineno - 2] if lineno >= 2 else ""
            claim = _prose_number_claim(line, nxt, prv)
            if claim is not None:
                out.append((rel, lineno, claim))
    return out


def prose_number_claims(repo_root=None):
    """[(relpath, lineno, text), ...] -- present-tense numbers written into prose.

    THE RULE: do not write the number. Every suite prints `N/M cases passed` on
    every run and CI runs all of them; `len(_deps.KNOWN_LAYER_DEBT)` is one
    command away; `selftest_coverage()['covered']` is another. The count already
    has a live source, so a copy in a docstring has no reader who acts on it and
    nothing comparing it. The pointer to the source is the informative half, and
    it stays.

    Measured when the first family was written, and the reason this is a lint
    rather than a round of corrections: **9 of the 51 such claims in the tree
    were already wrong** -- `_panel_page.py` said 285 against a real 325,
    `_refs.py` said 32 against 80, `guard-secrets-read.py` said 93 against 108,
    and `selftest_coverage`'s own docstring said 64 while 84 test files existed.
    Correcting them buys one green day: every one rots again the next time
    somebody adds a case, which is the entire point of adding cases. The two
    families added after it were measured the same way and were **4 sites, 4 of
    them already wrong** -- a hit rate that is itself the argument.

    MEASURED AGAIN WHEN THE LOCATION WIDENED, because a scan that fires on
    honest prose is a scan that gets routed around. Every hit the widened walk
    produced over this tree was read. The real claims were suite sizes in
    `tests/` docstrings and part counts in `scripts/ui/*/README.md`, most of them
    already wrong; the false positives were all ONE thing, the
    `<passed>/<total>` tally, appearing as a fixture, as a regex and as an
    asserted literal in the files whose job is that contract. Removing them is
    `_words()`'s interior-separator rule, which is a NARROWING - nothing that
    was already a finding stopped being one - and the rest were reworded or
    built rather than written, never admitted by loosening a shape.

    WHAT IT CANNOT SEE, stated rather than implied, and the direction matters
    more than the list:

      * a count spelled as one of the small number-words `_NUMERAL_WORDS`
        leaves out -- under `ten` the word is ordinary English machinery and
        the shapes cannot tell it from a count;
      * a claim whose NUMBER and whose SHAPE-WORD land on different lines --
        the basis and the SENTENCE the number sits in are both read across the
        wrap, but never the claim itself;
      * a MEASUREMENT -- a duration, a byte count, a line count. A units family
        was surveyed over this whole tree before being refused, and the refusal
        IS the measurement: on the widest vocabulary honest prose outran real
        claims by better than two to one, and on the narrowest defensible cut
        (size units, on a line naming code, the gate the persistence family
        uses) it still outran them. A size or a duration here is usually a
        threshold, a budget, a hypothetical, or a fact about somebody else's
        system, and in every one of those the number is what the sentence is
        for. `pn27` holds the lines that decided it, so adopting one without
        measuring again goes red;
      * a BEFORE/AFTER sentence -- "it was N lines and is M". The first number
        is history and legal for ever, the second is a live claim, and the tense
        that makes the first legal sits in the same sentence as the second,
        which is exactly why a reader trusts both. The `is N` shape that would
        reach it was surveyed too: real claims were about a quarter of its hits
        and the rest were arithmetic, format shapes and external facts. `pn28`;
      * a completeness claim with no auxiliary ("(all 64)", "all 8 viz slots"),
        because recognising an arbitrary present-tense verb needs a lexicon;
      * a persistence claim that names no code in backticks on its own line;
      * a number written with an interior separator -- `_words()` keeps a ratio
        and a decimal whole on purpose, and neither is then a numeral;
      * a file of an extension this does not read. `.py` is here and `.md` is
        `_deps.doc_prose_numbers()`; `.mjs`, `.js`, `.sh`, `.yml` and `.json`
        carry prose too and are read by nothing;
      * a file with a row in `PROSE_SCAN_EXEMPT`, which is the only remaining
        LOCATION gap and is the only one somebody had to write down.

    Every one of those is an UNDER-count. Over-counting is impossible with
    shapes this narrow, and under-counting is the quiet direction -- so a clean
    result means "none of the known shapes", not "no claims".
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    scan = prose_scan_set((".py",), root)
    if scan["problem"] is not None:
        # A read that could not happen is a finding, not an empty result.
        return [(".gitignore", 0, scan["problem"])]
    return sorted(prose_claims_in(root, scan["paths"]))


def covered_repo_paths(repo_root=None):
    """Repo-relative paths of the production files whose cases have moved to `tests/`.

    CI's selftest sweep reads this. A migrated file no longer prints the `N/M cases
    passed` contract, so the sweep has to skip it — and the skip list is derived from
    the same function that reports `neither`, rather than re-derived in shell, so the
    sweep cannot skip a file this lint has not accounted for.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    return [posix_rel(os.path.join(PLUGIN_ROOT, rel), root)
            for rel in selftest_coverage()["covered"]]


def write_lf_lines(lines, stream=None):
    """Write each of `lines` followed by ONE `\\n` byte, on every platform.

    `print()` was here, and `print()` on Windows emits `\\r\\n`: a text stream
    translates, so `--covered` was not a list of paths, it was a list of paths in the
    local line-ending dialect. CI pipes that through `tr '\\n' ' '`, which leaves a
    `\\r` glued to every path, so the membership test
    `case " $covered " in *" $f "*` matched nothing, every migrated file was run
    anyway, and the first of them printed its "cases moved to tests/" pointer instead
    of the contract. Green on ubuntu, red on windows, for a defect in neither.

    A MACHINE-READABLE LIST IS NOT PLATFORM-DEPENDENT DATA. The fix belongs at the
    producer, not in each consumer's `tr -d '\\r'`: `reconfigure(newline="")` turns
    the translation off for this write only. `safe_stdio()` is deliberately left
    alone — it runs in every script in the tree and changing what they all print to
    fix one flag's output would be a much larger blast radius than the bug.

    A stream with no `reconfigure` (a `StringIO`, which is what a selftest capture
    installs) does not translate in the first place, so the failure to reconfigure it
    is not a failure at all. Returns the stream it wrote to, so a case can inspect
    what actually happened rather than trust that something did.
    """
    out = stream if stream is not None else sys.stdout
    try:
        out.reconfigure(newline="")
    except (AttributeError, ValueError, OSError):
        pass
    out.write("".join("%s\n" % line for line in lines))
    return out


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the usage line, which would exit 2
        # with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how `selftest_coverage()`
        # above tells an inline suite from a migrated one, and this module is the
        # one file in the tree where getting that wrong would misclassify every
        # other file as well.
        print("_output.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__output.py - run that file instead.")
        raise SystemExit(0)
    if "--covered" in sys.argv[1:]:
        # CI's sweep asks this, one line per path, so its skip list comes from the
        # classifier that also reports `neither` rather than from a name transform
        # re-implemented in shell. Empty output is the correct answer before the
        # migration starts and after it ends for opposite reasons; `--selftest`'s
        # sc10/sc11 are what tell those two apart, not this flag.
        #
        # `write_lf_lines`, not `print`: this is machine-readable output and it is
        # LF on every platform. See that function for the Windows failure it fixes.
        write_lf_lines(covered_repo_paths())
        raise SystemExit(0)
    sys.stderr.write("usage: _output.py --selftest | --covered\n")
    raise SystemExit(2)
