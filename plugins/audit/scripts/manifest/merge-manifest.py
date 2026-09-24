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
  merge-manifest.py resolve   <conflicted manifest file> --renumber ours|theirs
  merge-manifest.py --selftest

Exit codes: driver - 0 merged cleanly, 1 conflicted (markers written). install /
uninstall - 0 done, 1 refused, 2 usage. status - 0 installed and current, 1 not
installed or stale, 2 usage.

This script carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_merge_manifest.py`.
"""
import argparse
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

import _id_refs  # noqa: E402  (rename: a renumbered id with every reference to it)
import _id_shape  # noqa: E402  (the next free id of each kind)
import _locks  # noqa: E402  (the index lock a structural write holds)
import _manifest_io as _mio  # noqa: E402
import _manifest_merge  # noqa: E402
import _merge_install as _mi  # noqa: E402
import _manifest_rules  # noqa: E402


DRIVER_NAME = _mi.DRIVER_NAME
_TAG = _mi.TAG

_USAGE = ("usage: merge-manifest.py driver <base> <ours> <theirs> [<path>]\n"
          "       merge-manifest.py install|uninstall <manifestPath> [--dry-run]\n"
          "       merge-manifest.py status <manifestPath>\n"
          "       merge-manifest.py resolve <conflicted file> --renumber ours|theirs")
_COLLISION = "the same id was added on both sides"


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
        if any(c["reason"].startswith(_COLLISION) for c in result["conflicts"]):
            lines.append("    an id minted on both sides is renumbered on the side you name, "
                         "with every reference to it: merge-manifest.py resolve %s "
                         "--renumber ours|theirs  (/audit:layout merge-driver resolve)"
                         % (label,))
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


# --- resolve: the collision the suffix cannot prevent ----------------------------
# Two clones minting on the development branch itself mint the same id, and which
# one keeps it depends on which was published first - a fact the merge cannot know
# and the operator can. So the operator names the side to renumber, and this does
# the rest the way the record merge does everything else: each id BOTH sides added
# with different content gets the next free id of its kind on the named side, with
# every reference on that side (`_id_refs`), and the three plans are merged again.
# On that side the id is unambiguous - it did not exist in the base - so renaming
# every occurrence there cannot repoint anything shared.
#
# THE THREE PLANS ARE READ FROM THE MERGE'S COMMITS, NOT FROM THE CONFLICTED FILE.
# In the sharded layout a phase minted on both sides with one title merges its
# index CLEANLY and conflicts only in the shard file both sides created, so git
# keeps no stages for the index at all. HEAD, MERGE_HEAD and their merge base hold
# every file of each plan, and the one loader assembles each.
# An ALIAS: `close-phase.py` asks a commit for the plan too, so the reader lives in
# `_manifest_io` beside the loader it wraps.
_plan_at = _mio.load_manifest_at


def _namespace(doc):
    ids = set(_id_refs.all_ids(doc))
    ids.update((p or {}).get("id") for p in (doc or {}).get("proposals") or [])
    ids.discard(None)
    return ids


def _collisions(base, ours, theirs):
    """Ids BOTH sides added, where the record merge reports a collision. Identical
    additions merge on their own and are not in this list."""
    added = (_namespace(ours) - _namespace(base)) & (_namespace(theirs) - _namespace(base))
    result = _manifest_merge.merge3(base, ours, theirs)
    conflicted = " ".join(c["path"] for c in result["conflicts"]
                          if c["reason"].startswith(_COLLISION))
    return sorted((i for i in added if "[%s]" % (i,) in conflicted),
                  key=_manifest_merge.natural_key)


def _phase_of(doc, ident):
    for phase in (doc or {}).get("phases") or []:
        if isinstance(phase, dict) and phase.get("id") == ident:
            return phase
    return None


def _renumbering(ids, side_doc, other_doc, suffix):
    """({old: new}, [ids no rule renumbers]) for the named side. Each new id is the
    next free one of its kind over BOTH sides, so it is fresh in the result; a phase
    takes its tasks with it."""
    combined = {"phases": list(side_doc.get("phases") or []) + list(other_doc.get("phases") or []),
                "bugs": list(side_doc.get("bugs") or []) + list(other_doc.get("bugs") or []),
                "proposals": (list(side_doc.get("proposals") or [])
                              + list(other_doc.get("proposals") or []))}
    taken = _namespace(side_doc) | _namespace(other_doc)
    mapping, refused = {}, []
    for old in ids:
        text = "%s" % (old,)
        phase = _phase_of(side_doc, old)
        if phase is not None:
            moved = _id_refs.phase_mapping(phase, _id_shape.next_phase_id(taken, None))
            mapping.update(moved)
            taken.update(moved.values())
            continue
        if text.startswith("BUG-"):
            new = _id_shape.next_bug_id(combined, suffix)
            combined["bugs"].append({"id": new})
        elif text.startswith("PROP-"):
            new = _id_shape.next_prop_id(combined, suffix)
            combined["proposals"].append({"id": new})
        elif "." in text:
            new = _id_shape.next_task_id(combined, text.rsplit(".", 1)[0], suffix,
                                         extra_ids=list(taken))
        else:
            refused.append(old)
            continue
        mapping[old] = new
        taken.add(new)
    return mapping, refused


def _render_plan(path, result, sharded):
    """[(file, text)] the merged plan is written as. Sharded, it is split first and
    each file rendered against the ONE conflict list, so a real disagreement left in
    a phase is a marker block in that phase's shard."""
    if not sharded:
        return [(path, _manifest_merge.render(result, _mio.json_document))]
    index, shards = _mio.split_manifest(result["doc"])
    base_dir = os.path.dirname(path)
    out = [(path, _manifest_merge.render({"doc": index, "conflicts": result["conflicts"]},
                                         _mio.json_document))]
    for pid, body in shards.items():
        out.append((os.path.join(base_dir, _mio.shard_rel_path(pid)),
                    _manifest_merge.render({"doc": body, "conflicts": result["conflicts"]},
                                           _mio.json_document)))
    return out


def resolve(path, side):
    """Renumber the collisions on `side`, re-merge the three plans, write the
    result. Returns (exit code, message)."""
    path = os.path.abspath(path)
    code, top = _mi.git(os.path.dirname(path), "rev-parse", "--show-toplevel")
    if code != 0 or not top:
        return 1, "%s refused: %s is not inside a git work tree" % (_TAG, path)
    top = os.path.realpath(top)
    rel = os.path.relpath(os.path.realpath(path), top).replace(os.sep, "/")
    code, _mh = _mi.git(top, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    if code != 0:
        return 1, ("%s refused: no merge is in progress, so there is no conflict to "
                   "resolve (resolve runs while `git merge` has stopped on the plan)"
                   % (_TAG,))
    code, base_c = _mi.git(top, "merge-base", "HEAD", "MERGE_HEAD")
    ours = _plan_at(top, "HEAD", rel)
    theirs = _plan_at(top, "MERGE_HEAD", rel)
    if ours is None or theirs is None:
        return 1, ("%s refused: %s is not a plan on both sides of this merge"
                   % (_TAG, rel))
    base = (_plan_at(top, base_c, rel) if code == 0 and base_c else None) or {}
    ids = _collisions(base, ours, theirs)
    if not ids:
        return 1, ("%s refused: no id in %s was minted on both sides; what conflicts "
                   "is a real disagreement, which the marker blocks show" % (_TAG, rel))
    named, other = (theirs, ours) if side == "theirs" else (ours, theirs)
    mapping, refused = _renumbering(ids, named, other, _id_shape.suffix_here(top, named))
    if refused:
        return 1, ("%s refused: %s cannot be renumbered by kind - rename it by hand"
                   % (_TAG, ", ".join("%s" % (r,) for r in refused)))
    renamed, count = _id_refs.rename(named, mapping)
    sides = (renamed, other) if side == "ours" else (other, renamed)
    result = _manifest_merge.merge3(base, sides[0], sides[1])
    files = _render_plan(path, result, _sharded_at(top, rel))
    lock = None
    if _locks.available(top):
        lock = _locks.acquire(top, "index", note="merge-driver resolve",
                              out=lambda *_a, **_k: None)
        if not _locks.held(lock):
            return 1, "%s refused: %s" % (_TAG, _locks.refusal(lock, "index"))
    try:
        for target, text in files:
            _write(target, text)
    finally:
        if _locks.took(lock):
            _locks.release(top, "index", out=lambda *_a, **_k: None)
    written = [os.path.relpath(t, top).replace(os.sep, "/") for t, _x in files]
    lines = ["%s %s: renumbered on %s (%d reference(s) rewritten):"
             % (_TAG, rel, side, count)]
    lines += ["    %s -> %s" % (old, mapping[old]) for old in ids]
    lines.append("    written: %s" % (", ".join(written),))
    if result["conflicts"]:
        lines.append("    %d conflict(s) remain - real disagreements, one marker block "
                     "each:" % (len(result["conflicts"]),))
        lines += ["    %s - %s" % (c["path"], c["reason"]) for c in result["conflicts"]]
        return 1, "\n".join(lines)
    if not _mio.is_sharded(result["doc"]):
        fresh = [f for f in _manifest_rules.validate(result["doc"])[0]]
        if fresh:
            lines.append("    the merged plan has finding(s) - resolve them before "
                         "committing:")
            lines += ["    %s" % (f,) for f in fresh]
            return 1, "\n".join(lines)
    lines.append("    next: validate-manifest.py on the plan, then `git add` the files "
                 "written and finish the merge. The renumbered side's commit messages "
                 "and journal rows still name the old id - they are history.")
    return 0, "\n".join(lines)


def _sharded_at(top, rel):
    """The layout of the plan HEAD holds, read off its raw index - the assembled
    plan carries no `shard` refs, and the working copy may be full of markers."""
    code, text = _mi.git(top, "show", "HEAD:%s" % (rel,))
    try:
        return code == 0 and _mio.is_sharded(json.loads(text))
    except ValueError:
        return False


# --- cli ------------------------------------------------------------------------
RENUMBER_SIDES = ("ours", "theirs")


def build_parser():
    """The option surface of every verb but `driver`, MODULE LEVEL so the command
    docs can be graded against it (`_help.command_choice_drift` asks argparse which
    values `--renumber` takes, rather than trusting the hint that advertises them).

    `driver` IS NOT PARSED HERE, and that is a safety property rather than an
    omission: argparse answers a malformed call with exit 2, and git reads any exit
    from 1 to 128 as "conflicted, %A is the result" - so a parse error would leave
    the file as ours with no markers. The driver keeps its own argument handling,
    which writes markers on every failure path."""
    ap = argparse.ArgumentParser(prog="merge-manifest.py",
                                 description="The audit manifest's git merge driver, "
                                             "its install, and the collision resolver.")
    ap.add_argument("verb", choices=["install", "uninstall", "status", "resolve"])
    ap.add_argument("manifest")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="install/uninstall: print what would be written, write nothing")
    ap.add_argument("--renumber", choices=list(RENUMBER_SIDES), default=None,
                    help="resolve: the side whose colliding ids are renumbered")
    return ap


def main(argv):
    if "--selftest" in argv:
        # It deliberately does NOT print the `N/M cases passed` contract - that string
        # is how `_output.selftest_coverage()` tells an inline suite from a moved one.
        print("merge-manifest.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_merge_manifest.py - run that file instead.")
        return 0
    if argv and argv[0] == "driver":
        return driver_main(argv[1:])
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if args.verb == "resolve":
        if args.renumber is None:
            sys.stderr.write("%s resolve needs --renumber ours|theirs: which side keeps "
                             "the id is the operator's call, never the tool's\n"
                             % (_TAG,))
            return 2
        code, msg = resolve(args.manifest, args.renumber)
    elif args.renumber is not None:
        sys.stderr.write("%s --renumber is read by resolve only\n" % (_TAG,))
        return 2
    elif args.verb == "install":
        code, msg = install(args.manifest, _output.PLUGIN_ROOT, dry_run=args.dry_run)
    elif args.verb == "uninstall":
        code, msg = uninstall(args.manifest, dry_run=args.dry_run)
    else:
        code, msg = status(args.manifest)
    (sys.stderr if code and args.verb != "status" else sys.stdout).write(msg + "\n")
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    raise SystemExit(main(sys.argv[1:]))
