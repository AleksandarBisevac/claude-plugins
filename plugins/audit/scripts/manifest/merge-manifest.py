#!/usr/bin/env python3
"""
The git merge driver for the audit manifest, and the verb that installs it.

Without it every branch that adds a record - a phase, a task, a bug, a `fileIndex`
row - conflicts with every other branch that added one, because each writer appends
at the same tail. The records never disagree; the lines do. With it, git hands the
three versions to `_manifest_merge.merge3`, which matches records by id, and the only
conflicts left are the ones a person has to decide - rendered as marker blocks around
those records alone, not around every append point in the file.

WHAT GIT DOES WITH A DRIVER, measured with git 2.50.1 on 2026-09-24 in throwaway
repositories (every outcome below was driven, not read off the documentation):
  - exit 0: the file is whatever the driver wrote to %A, and the path is resolved;
  - any exit from 1 to 128: the path is CONFLICTED and the file is whatever %A holds.
    A driver that fails WITHOUT writing leaves %A as OURS WITH NO MARKERS - a
    `git add` then drops the other side silently. So every failure path here writes
    markers before it exits, and the shim below covers the paths Python cannot;
  - an exit above 128 aborts the whole merge (`failed to execute internal merge`),
    so this never exits above 1;
  - a missing driver command behaves as the silent case above, which is why git
    config names the shim and never this file;
  - a path whose attribute names a driver the clone has NOT configured falls back
    to git's own line merge with markers. That is what makes the committed
    `.gitattributes` line safe for a teammate who has not installed.
  - `merge-tree --write-tree`, `cherry-pick` and `rebase` all run the driver; it
    runs at the top of the work tree and `%P` is the path relative to it.

WHY A SHIM. `CLAUDE_PLUGIN_ROOT` names a versioned cache directory that moves on
every upgrade, and git config holds a string. So `install` writes a POSIX-sh shim
under the git common dir - outside the tree, shared by every worktree of the clone,
like the audit locks - recording the plugin root it was installed from. When that
root is gone, or Python is, or the driver dies before writing, the shim runs
`git merge-file` itself and says to re-run install.

Usage:
  merge-manifest.py driver <base %O> <ours %A> <theirs %B> [<path %P>]
  merge-manifest.py install   <manifestPath> [--dry-run]
  merge-manifest.py uninstall <manifestPath> [--dry-run]
  merge-manifest.py status    <manifestPath>
  merge-manifest.py --selftest

Exit codes: driver - 0 merged cleanly, 1 conflicted (markers written). install /
uninstall - 0 done, 1 refused, 2 usage. status - 0 installed and current, 1 not
installed or stale, 2 usage.

This script carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_merge_manifest.py`.
"""
import json
import os
import subprocess
import sys
import tempfile

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

import _manifest_io as _mio  # noqa: E402
import _manifest_merge  # noqa: E402
import _merge_install as _mi  # noqa: E402
import _manifest_rules  # noqa: E402


DRIVER_NAME = _mi.DRIVER_NAME
_TAG = _mi.TAG

_USAGE = ("usage: merge-manifest.py driver <base> <ours> <theirs> [<path>]\n"
          "       merge-manifest.py install|uninstall <manifestPath> [--dry-run]\n"
          "       merge-manifest.py status <manifestPath>")


# --- the driver -----------------------------------------------------------------
def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write(path, text, newline=None):
    """Replace `path` atomically - git reads %A back the moment this exits.

    `newline=""` writes `text` byte for byte. The manifest keeps the platform's
    text mode, as every other writer of it in this plugin does; `.gitattributes`
    and the shim do not - the first keeps whatever endings it already had, and the
    second is a shell script, which a CR would break on every line."""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _line_merge(base_p, ours_p, theirs_p):
    """git's own line merge, with markers - what the file would hold had no driver
    been configured. Falls back to one whole-file block when git itself cannot be
    run, because a failure path that writes nothing leaves %A silently as ours."""
    try:
        r = subprocess.run(["git", "merge-file", "-p", "-L", "ours", "-L", "base",
                            "-L", "theirs", ours_p, base_p, theirs_p],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if 0 <= r.returncode < 128:
            return r.stdout.decode("utf-8", "replace")
    except OSError:
        pass
    ours, theirs = _read(ours_p), _read(theirs_p)
    return "<<<<<<< ours\n%s%s=======\n%s%s>>>>>>> theirs\n" % (
        ours, "" if ours.endswith("\n") else "\n",
        theirs, "" if theirs.endswith("\n") else "\n")


def _kind(doc):
    """single-file / index / shard / other - which of the three shapes git handed us."""
    if not isinstance(doc, dict):
        return "other"
    if isinstance(doc.get("phases"), list):
        return "index" if _mio.is_sharded(doc) else "single-file"
    if isinstance(doc.get("tasks"), list):
        return "shard"
    return "other"


def _new_findings(merged, ours, theirs):
    """Findings the MERGE introduced. A finding either input already carried is not
    the merge's to report: refusing on it would make a plan with one standing
    finding unmergeable for ever."""
    before = set(_manifest_rules.validate(ours)[0]) | set(_manifest_rules.validate(theirs)[0])
    return [f for f in _manifest_rules.validate(merged)[0] if f not in before]


def run_driver(base_p, ours_p, theirs_p, path_label):
    """Merge in place into `ours_p`. Returns (exit code, message lines)."""
    label = path_label or os.path.basename(ours_p)
    texts = [_read(p) for p in (base_p, ours_p, theirs_p)]
    # git hands an EMPTY %O on an add/add - both sides created the file. That is
    # a state, not a malformed input, so it is told apart before parsing.
    added_both = not texts[0].strip()
    try:
        docs = [None if added_both and i == 0 else json.loads(t)
                for i, t in enumerate(texts)]
    except ValueError as exc:
        _write(ours_p, _line_merge(base_p, ours_p, theirs_p))
        return 1, ["%s %s: a side is not valid JSON (%s) - fell back to a line merge "
                   "with conflict markers" % (_TAG, label, exc)]

    if added_both and _kind(docs[1]) == "shard":
        result = _manifest_merge.collision(
            docs[1], docs[2], "this phase shard was created on both sides - one phase "
                              "id minted on two branches")
    else:
        if added_both:
            docs[0] = {}
        result = _manifest_merge.merge3(docs[0], docs[1], docs[2])
    text = _manifest_merge.render(result, _mio.json_document)
    counts = "ours %d, theirs %d record(s) changed" % (result["counts"]["ours"],
                                                       result["counts"]["theirs"])
    notes = []
    if _mio.json_document(docs[1]) != texts[1]:
        notes.append("%s %s: our side was not in the plugin's JSON spelling, so lines "
                     "neither side changed may be re-spelled in the result" % (_TAG, label))

    if result["conflicts"]:
        _write(ours_p, text)
        lines = ["%s %s: %d record conflict(s) left for you (%s):"
                 % (_TAG, label, len(result["conflicts"]), counts)]
        lines += ["    %s - %s" % (c["path"], c["reason"]) for c in result["conflicts"]]
        lines.append("    each is one marker block; every other record is already merged. "
                     "Resolve, then run validate-manifest.py on the plan.")
        return 1, notes + lines

    kind = _kind(docs[1])
    if kind == "single-file":
        fresh = _new_findings(result["doc"], docs[1], docs[2])
        _write(ours_p, text)
        if fresh:
            return 1, notes + ["%s %s: merged by record (%s), but the result has %d "
                               "finding(s) neither side had - the path is left "
                               "conflicted so it is not committed unread:"
                               % (_TAG, label, counts, len(fresh))] + \
                ["    %s" % (f,) for f in fresh]
        return 0, notes + ["%s %s: merged by record (%s); validated - no new findings"
                           % (_TAG, label, counts)]
    _write(ours_p, text)
    basis = ("a sharded index or shard cannot be validated alone - run "
             "validate-manifest.py on the index once the merge completes"
             if kind in ("index", "shard") else
             "not a manifest shape this driver knows, merged as plain JSON")
    return 0, notes + ["%s %s: merged by record (%s); %s" % (_TAG, label, counts, basis)]


def driver_main(argv):
    if len(argv) < 3:
        sys.stderr.write(_USAGE + "\n")
        return 1        # never 2+: git reads any exit above 128 as abort, and 2 is noise
    base_p, ours_p, theirs_p = argv[0], argv[1], argv[2]
    label = argv[3] if len(argv) > 3 else ""
    try:
        code, lines = run_driver(base_p, ours_p, theirs_p, label)
    except Exception as exc:                                   # noqa: BLE001
        # A crash must still leave markers: git would otherwise keep %A as ours.
        try:
            _write(ours_p, _line_merge(base_p, ours_p, theirs_p))
        finally:
            sys.stderr.write("%s %s: the record merge failed (%s: %s) - fell back to a "
                             "line merge with conflict markers\n"
                             % (_TAG, label or ours_p, type(exc).__name__, exc))
        return 1
    sys.stderr.write("".join(line + "\n" for line in lines))
    return code


# --- install --------------------------------------------------------------------
def _without_ours(lines, ours):
    return [ln for ln in lines if ln not in ours]


def plan_install(loc, plugin_root):
    """What install would write: {attributes: text, shim: text, driver: value}."""
    ours = _mi.attribute_lines(loc)
    kept = _without_ours(_mi.read_lines(_mi.attributes_file(loc)), ours)
    while kept and kept[-1] == "":
        kept.pop()
    eol = _mi.line_ending(_mi.attributes_file(loc))
    text = eol.join(kept + ([""] if kept else []) + ours) + eol
    return {"attributes": text, "shim": _mi.shim_text(plugin_root),
            "driver": _mi.driver_value(loc)}


def install(manifest, plugin_root, dry_run=False):
    loc, err = _mi.locate(manifest)
    if loc is None:
        return 1, "%s refused: %s" % (_TAG, err)
    plan = plan_install(loc, plugin_root)
    lines = ["%s %s the record merge for %s:" % (_TAG, "would install" if dry_run else
                                                   "installed", loc["manifest_rel"]),
             "  .gitattributes  %s  (commit it: it is what tells every clone which "
             "driver the manifest takes)" % (_mi.attributes_file(loc),),
             "  shim            %s  (records plugin root %s)" % (_mi.shim_path(loc), plugin_root),
             "  git config      merge.%s.driver = %s  (this clone only - every teammate "
             "installs once)" % (DRIVER_NAME, plan["driver"])]
    if dry_run:
        return 0, "\n".join(lines)
    _write(_mi.attributes_file(loc), plan["attributes"], newline="")
    os.makedirs(os.path.dirname(_mi.shim_path(loc)), exist_ok=True)
    _write(_mi.shim_path(loc), plan["shim"], newline="")
    for key, value in (("name", "audit manifest - merge by record"),
                       ("driver", plan["driver"])):
        code, out = _mi.git(loc["toplevel"], "config", "--local",
                         "merge.%s.%s" % (DRIVER_NAME, key), value)
        if code != 0:
            return 1, "%s refused: git config failed: %s" % (_TAG, out)
    return 0, "\n".join(lines)


def uninstall(manifest, dry_run=False):
    loc, err = _mi.locate(manifest)
    if loc is None:
        return 1, "%s refused: %s" % (_TAG, err)
    lines = ["%s %s the record merge for %s" % (_TAG, "would remove" if dry_run else
                                                "removed", loc["manifest_rel"])]
    if dry_run:
        return 0, "\n".join(lines)
    attrs = _mi.attributes_file(loc)
    current = _mi.read_lines(attrs)
    kept = _without_ours(current, _mi.attribute_lines(loc))
    if kept != current:
        while kept and kept[-1] == "":
            kept.pop()
        if kept:
            eol = _mi.line_ending(attrs)
            _write(attrs, eol.join(kept) + eol, newline="")
        else:
            os.remove(attrs)
    if os.path.isfile(_mi.shim_path(loc)):
        os.remove(_mi.shim_path(loc))
    _mi.git(loc["toplevel"], "config", "--local", "--remove-section", "merge.%s" % (DRIVER_NAME,))
    return 0, "\n".join(lines)



def status(manifest):
    f = _mi.status_facts(manifest)
    if "error" in f:
        return 1, "%s %s" % (_TAG, f["error"])
    ok = f["attributes"] and f["configured"] and f["shim"] and f["shim_root_exists"]
    lines = ["%s %s for %s" % (_TAG, "installed" if ok else "NOT fully installed",
                               f["manifest_rel"]),
             "  .gitattributes names the driver:  %s" % ("yes" if f["attributes"] else "no"),
             "  this clone configures it:         %s" % ("yes" if f["configured"] else
                                                          "no (%s)" % (f["driver_value"] or
                                                                       "unset",)),
             "  shim present:                     %s" % ("yes" if f["shim"] else "no"),
             "  shim's plugin root still exists:  %s" % (
                 "yes (%s)" % f["shim_root"] if f["shim_root_exists"] else
                 "no (%s) - re-run install" % (f["shim_root"] or "none recorded",))]
    return (0 if ok else 1), "\n".join(lines)


# --- cli ------------------------------------------------------------------------
def main(argv):
    if "--selftest" in argv:
        # It deliberately does NOT print the `N/M cases passed` contract - that string
        # is how `_output.selftest_coverage()` tells an inline suite from a moved one.
        print("merge-manifest.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_merge_manifest.py - run that file instead.")
        return 0
    if not argv:
        sys.stderr.write(_USAGE + "\n")
        return 2
    verb, rest = argv[0], argv[1:]
    if verb == "driver":
        return driver_main(rest)
    dry = "--dry-run" in rest
    rest = [a for a in rest if a != "--dry-run"]
    if verb not in ("install", "uninstall", "status") or len(rest) != 1:
        sys.stderr.write(_USAGE + "\n")
        return 2
    if verb == "install":
        code, msg = install(rest[0], _output.PLUGIN_ROOT, dry_run=dry)
    elif verb == "uninstall":
        code, msg = uninstall(rest[0], dry_run=dry)
    else:
        code, msg = status(rest[0])
    (sys.stderr if code and verb != "status" else sys.stdout).write(msg + "\n")
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    raise SystemExit(main(sys.argv[1:]))
