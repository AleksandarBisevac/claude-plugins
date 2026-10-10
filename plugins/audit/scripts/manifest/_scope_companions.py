#!/usr/bin/env python3
"""
The files a task's change cannot avoid, derived from the repo and not from a guess.

WHY THIS IS A MODULE. A task that adds a dependency edits the package manifest and
the lockfile; one that adds a test outside the runner's include edits the runner's
config; one that adds user-facing strings edits every locale file. A synthesized
scope that names only the files the description mentions omits all three, and the
task widens its own scope mid-run. Whether the lockfile is the pnpm one or the npm
one, which directory holds the locales and whether the runner collects a path are
facts about the repo, so they are read off the disk here and the caller only has
to say which kind of change it is making.

THE JUDGEMENT IS THE CALLER'S, THE PATHS ARE THE REPO'S. The intent arrives as
structured flags (`dependencies`, `userStrings`, `tests` with `runner`); nothing is
inferred from prose. Every path returned exists on disk, and every one carries the
sentence that makes it a companion.

AN ABSENCE IS AN ANSWER, NOT A GAP. No lockfile, no locale directory, two candidate
locale directories, two ecosystems in one directory, a runner whose answer was
could-not-tell: each adds nothing and is reported in `notes`, so a caller that sees
an empty `companions` can tell "nothing is owed" from "nothing could be decided".
Only a definite `NOT_COLLECTED` from `_runner_collects` adds a runner config.

`derive(intent, repo, lister=None)` returns
`{"companions": [{"path", "kind", "basis"}], "notes": [sentence]}`, paths relative
to `repo` with `/` separators. A path already in `intent["files"]` is not returned
again. Its cases are in `plugins/audit/tests/test__scope_companions.py`.
"""

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

import _runner_collects  # noqa: E402

# (ecosystem, manifests that mark a package directory, lockfiles in preference order)
ECOSYSTEMS = (
    ("node", ("package.json",),
     ("pnpm-lock.yaml", "package-lock.json", "yarn.lock", "bun.lockb", "bun.lock")),
    ("python", ("pyproject.toml",), ("uv.lock", "poetry.lock")),
)
LOCALE_BASES = ("", "src", "public", "app")
LOCALE_DIRS = ("messages", "locales", "locale", "translations", "i18n", "lang")
LOCALE_EXTS = (".json", ".yaml", ".yml", ".po")
LOCALE_TAG = re.compile(r"^[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,4})?$")


def _join(*parts):
    return "/".join(p for p in parts if p)


def _exists(repo, rel):
    return os.path.isfile(os.path.join(repo, *rel.split("/")))


def _companion(path, kind, basis):
    return {"path": path, "kind": kind, "basis": basis}


# --- dependency ---------------------------------------------------------------

def _package_dirs(files, repo):
    """The directories whose manifest the intent's files sit under; the repo root
    when no file has one. Sorted, so the output order is the same on every run."""
    found = set()
    for rel in files or [""]:
        parts = rel.split("/")[:-1] if rel else []
        for depth in range(len(parts), -1, -1):
            here = "/".join(parts[:depth])
            if any(_exists(repo, _join(here, m)) for _, ms, _ in ECOSYSTEMS for m in ms):
                found.add(here)
                break
    return sorted(found) or [""]


def _lock_dir(repo, here, locks):
    """The nearest directory at or above `here` holding any of `locks`."""
    parts = here.split("/") if here else []
    for depth in range(len(parts), -1, -1):
        up = "/".join(parts[:depth])
        present = [lk for lk in locks if _exists(repo, _join(up, lk))]
        if present:
            return up, present
    return None, []


def _dependency_in(here, ecosystem, repo, names):
    where = here or "the repo root"
    candidates = [e for e in ECOSYSTEMS
                  if any(_exists(repo, _join(here, m)) for m in e[1])]
    if ecosystem:
        candidates = [e for e in candidates if e[0] == ecosystem]
    if not candidates:
        return [], ["no dependency manifest found at %s for %s%s; nothing added"
                    % (where, ", ".join(names), " (ecosystem %s)" % ecosystem if ecosystem else "")]
    if len(candidates) > 1:
        return [], ["ambiguous dependency manifest at %s (%s); name the ecosystem; nothing added"
                    % (where, ", ".join(e[0] for e in candidates))]
    eco, manifests, locks = candidates[0]
    manifest = next(_join(here, m) for m in manifests if _exists(repo, _join(here, m)))
    out = [_companion(manifest, "dependency-manifest",
                      "%s is the %s manifest a new dependency (%s) is declared in"
                      % (manifest, eco, ", ".join(names)))]
    lock_at, present = _lock_dir(repo, here, locks)
    notes = []
    if not present:
        return out, ["no lockfile (%s) on disk at or above %s; none added"
                     % (", ".join(locks), where)]
    for lk in present:
        path = _join(lock_at, lk)
        out.append(_companion(path, "lockfile",
                              "%s is on disk and records the resolved version of %s"
                              % (path, ", ".join(names))))
    if len(present) > 1:
        notes.append("more than one lockfile on disk (%s); all added because the repo "
                     "does not say which one is current" % ", ".join(present))
    return out, notes


def _dependencies(intent, repo):
    names = [str(n) for n in intent.get("dependencies") or []]
    if not names:
        return [], []
    out, notes = [], []
    for here in _package_dirs(intent.get("files") or [], repo):
        got, more = _dependency_in(here, intent.get("ecosystem"), repo, names)
        out.extend(got)
        notes.extend(more)
    return out, notes


# --- locales ------------------------------------------------------------------

def _locale_files(repo, rel):
    """Locale files in the directory `rel`: `<dir>/<tag>.<ext>`, and everything
    under `<dir>/<tag>/`. A name that is not a locale tag is not a locale file."""
    base = os.path.join(repo, *rel.split("/"))
    out = []
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        stem, ext = os.path.splitext(name)
        if os.path.isfile(full) and ext in LOCALE_EXTS and LOCALE_TAG.match(stem):
            out.append(_join(rel, name))
        elif os.path.isdir(full) and LOCALE_TAG.match(name):
            for root, dirs, names in os.walk(full):
                dirs.sort()
                for fname in sorted(names):
                    if os.path.splitext(fname)[1] in LOCALE_EXTS:
                        sub = os.path.relpath(os.path.join(root, fname), repo)
                        out.append(sub.replace(os.sep, "/"))
    return out


def _user_strings(intent, repo):
    if not intent.get("userStrings"):
        return [], []
    layouts = []
    for base in LOCALE_BASES:
        for name in LOCALE_DIRS:
            rel = _join(base, name)
            if os.path.isdir(os.path.join(repo, *rel.split("/"))):
                files = _locale_files(repo, rel)
                if files:
                    layouts.append((rel, files))
    if not layouts:
        return [], ["no locale directory detected (looked for %s under %s); no locale file added"
                    % ("/".join(LOCALE_DIRS), ", ".join(b or "." for b in LOCALE_BASES))]
    if len(layouts) > 1:
        return [], ["more than one locale directory (%s); which one holds the strings is not "
                    "guessed, so no locale file added" % ", ".join(r for r, _ in layouts)]
    rel, files = layouts[0]
    return [_companion(f, "locale", "%s is a locale file in %s/, and user-facing strings "
                                    "are owed in every locale" % (f, rel)) for f in files], []


# --- runner config ------------------------------------------------------------

def _runner_config(runner, repo):
    names = {"vitest": _runner_collects.VITEST_CONFIGS + _runner_collects.VITE_CONFIGS,
             "jest": _runner_collects.JEST_CONFIGS,
             "pytest": _runner_collects.PYTEST_CONFIG_FILES}.get(runner, ())
    return next((n for n in names if _exists(repo, n)), None)


def _tests(intent, repo, lister):
    tests = intent.get("tests") or []
    runner = intent.get("runner")
    out, notes = [], []
    for path in tests:
        got = _runner_collects.collects(path, runner, repo, lister=lister)
        answer = got["answer"]
        if answer == _runner_collects.COULD_NOT_TELL:
            notes.append("could not tell whether %s collects %s: %s; no runner config added"
                         % (runner, path, got["basis"]))
        elif answer == _runner_collects.COLLECTED:
            notes.append("%s collects %s (%s); no runner config added"
                         % (runner, path, got["basis"]))
        else:
            config = _runner_config(runner, repo)
            if config is None:
                notes.append("%s does not collect %s (%s) and no config file exists to "
                             "widen; none added" % (runner, path, got["basis"]))
            elif not any(c["path"] == config for c in out):
                out.append(_companion(config, "runner-config",
                                      "%s does not collect %s: %s" % (runner, path, got["basis"])))
    return out, notes


# --- the question -------------------------------------------------------------

def derive(intent, repo, lister=None):
    """Companions for `intent` in the repo at `repo`.

    `intent`: {"dependencies": [name], "ecosystem": "node"|"python"|... (optional),
    "userStrings": bool, "tests": [path], "runner": "vitest"|"jest"|"pytest",
    "files": [the task's declared files]}. A key left out asks nothing.
    `lister` is handed to `_runner_collects.collects` unchanged.
    """
    declared = set(intent.get("files") or [])
    companions, notes = [], []
    for found, more in (_dependencies(intent, repo),
                        _user_strings(intent, repo),
                        _tests(intent, repo, lister)):
        companions.extend(c for c in found
                          if c["path"] not in declared
                          and c["path"] not in [k["path"] for k in companions])
        notes.extend(more)
    return {"companions": companions, "notes": notes}


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if _output.selftest_requested(sys.argv[1:]):
        # Deliberately does NOT print the `N/M cases passed` contract - that literal
        # is how `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_scope_companions.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__scope_companions.py - run that file "
              "instead.")
        sys.exit(0)
    print(__doc__.strip())
