#!/usr/bin/env python3
"""
What an install of the manifest merge driver consists of, and how to read one back.

Its own module because two layers ask the same question. `merge-manifest.py` (an
entry point) writes the install and prints its `status`; `/audit:doctor`'s setup
check (layer 4) must report the same facts, and a layer-4 module may not reach an
entry point. A second reading of "is this clone installed" inside the doctor would be
a second answer waiting to disagree with the verb's, so the pieces - which lines,
which config key, which shim and what it records - are named once, here. The shim's
text lives here too, beside the one function that parses it back.

Everything here reads git or the disk and returns values; nothing here writes.
"""
import os
import subprocess
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


DRIVER_NAME = "audit-manifest"
TAG = "[audit merge]"
ATTR_HEADER = "# audit plugin: merge the manifest by record (/audit:layout merge-driver)"
SHIM_REL = os.path.join("audit", "merge-manifest.sh")
SHIM_ROOT_KEY = "AUDIT_PLUGIN_ROOT="


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def line_ending(path):
    """"\\r\\n" when the file already uses CRLF, else "\\n". The install owns three
    lines of `.gitattributes`, not the file's spelling: rewriting a Windows
    checkout's endings would turn a three-line change into a whole-file diff."""
    if not os.path.isfile(path):
        return "\n"
    with open(path, "rb") as fh:
        return "\r\n" if b"\r\n" in fh.read() else "\n"


def sh_quote(text):
    """`text` as one single-quoted POSIX-sh word."""
    return "'" + text.replace("'", "'\\''") + "'"


def sh_unquote(word):
    """The inverse of `sh_quote`, and only of it - the shim is ours, so the one
    spelling it can hold is the one written above."""
    if len(word) >= 2 and word[0] == "'" and word[-1] == "'":
        return word[1:-1].replace("'\\''", "'")
    return word


# --- where the install lives -------------------------------------------------------
def git(project, *args):
    """(exit code, stripped stdout) of one git command run in `project`."""
    r = subprocess.run(["git", "-C", project] + list(args),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def locate(manifest):
    """{toplevel, common_dir, manifest_rel, shard_glob_rel} or an error string."""
    mdir = os.path.dirname(os.path.abspath(manifest))
    code, top = git(mdir, "rev-parse", "--show-toplevel")
    if code != 0 or not top:
        return None, "%s is not inside a git work tree" % (manifest,)
    code, common = git(mdir, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if code != 0 or not common:
        return None, "git could not name the common git dir (git 2.31+ is needed)"
    top = os.path.realpath(top)
    rel = os.path.relpath(os.path.realpath(os.path.abspath(manifest)), top)
    if rel.startswith(".."):
        return None, "%s is outside the work tree %s" % (manifest, top)
    rel = rel.replace(os.sep, "/")
    if any(ch in rel for ch in " \t\"\\#!*?[]"):
        return None, ("the manifest path %r holds a character a .gitattributes pattern "
                      "would have to quote; add the lines by hand" % (rel,))
    shard_dir = os.path.dirname(rel)
    shard_glob = (shard_dir + "/" if shard_dir else "") + "phases/*.json"
    return {"toplevel": top, "common_dir": os.path.realpath(common),
            "manifest_rel": rel, "shard_glob_rel": shard_glob}, ""


def attribute_lines(loc):
    """The lines install owns in `.gitattributes`: a header, the plan, its shards."""
    return [ATTR_HEADER,
            "%s merge=%s" % (loc["manifest_rel"], DRIVER_NAME),
            "%s merge=%s" % (loc["shard_glob_rel"], DRIVER_NAME)]



def shim_path(loc):
    """Under the git COMMON dir: outside the tree, shared by every worktree."""
    return os.path.join(loc["common_dir"], SHIM_REL)


def driver_value(loc):
    """The one string git config holds: the shim, never the versioned plugin cache."""
    return "sh %s %%O %%A %%B %%P" % (sh_quote(shim_path(loc)),)


def attributes_file(loc):
    """The work tree's root `.gitattributes`."""
    return os.path.join(loc["toplevel"], ".gitattributes")


def read_lines(path):
    """A file's lines, or [] when it does not exist."""
    if not os.path.isfile(path):
        return []
    return _read(path).splitlines()



# --- the shim, and reading it back -------------------------------------------------
def shim_text(plugin_root):
    """The POSIX-sh shim git config names. Builtins plus `git`, `cp`, `cmp`, `rm`.

    It keeps a copy of %A before running the driver, so a driver that dies before
    writing - an ImportError at start-up exits 1 like a real conflict does - is
    told apart from one that wrote its markers: %A unchanged after a non-zero exit
    means nobody wrote it, and the shim writes git's line merge itself."""
    quoted = sh_quote(plugin_root)
    return """#!/bin/sh
# Written by the audit plugin's merge-driver install. Re-run the install instead of
# editing: it records which plugin copy to run, and an upgrade moves that copy.
%s%s
driver="$AUDIT_PLUGIN_ROOT/scripts/manifest/merge-manifest.py"
pre="$2.audit-pre"
cp "$2" "$pre" 2>/dev/null
if [ -f "$driver" ]; then
  for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
      "$py" "$driver" driver "$@"
      rc=$?
      if [ "$rc" -eq 0 ]; then rm -f "$pre"; exit 0; fi
      if ! cmp -s "$2" "$pre"; then rm -f "$pre"; exit 1; fi
      echo "%s the driver exited $rc without writing $4 - falling back to a line merge" >&2
      break
    fi
  done
else
  echo "%s $driver is gone (the plugin moved or was upgraded) - falling back to a line merge; re-run the merge-driver install" >&2
fi
rm -f "$pre"
git merge-file -L ours -L base -L theirs "$2" "$1" "$3"
[ $? -eq 0 ] && exit 0
exit 1
""" % (SHIM_ROOT_KEY, quoted, TAG, TAG)


def status_facts(manifest):
    """Each piece of the install, read from disk and from git - never assumed."""
    loc, err = locate(manifest)
    if loc is None:
        return {"error": err}
    wanted = attribute_lines(loc)[1:]
    present = read_lines(attributes_file(loc))
    _code, driver = git(loc["toplevel"], "config", "--get", "merge.%s.driver" % (DRIVER_NAME,))
    shim = shim_path(loc)
    root = None
    if os.path.isfile(shim):
        for line in _read(shim).splitlines():
            if line.startswith(SHIM_ROOT_KEY):
                root = sh_unquote(line[len(SHIM_ROOT_KEY):])
    return {"attributes": all(w in present for w in wanted),
            "configured": driver == driver_value(loc),
            "driver_value": driver,
            "shim": os.path.isfile(shim),
            "shim_root": root,
            "shim_root_exists": bool(root) and os.path.isfile(
                os.path.join(root, "scripts", "manifest", "merge-manifest.py")),
            "manifest_rel": loc["manifest_rel"]}
