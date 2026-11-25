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

Exit codes: driver - 0 merged cleanly, 1 conflicted (markers written). install /
uninstall - 0 done, 1 refused, 2 usage. status - 0 installed and current, 1 not
installed or stale, 2 usage. resolve - 0 written, 1 refused (nothing written: no
merge, no collision, a plan one of the merge's commits holds that cannot be read, a
busy lock, or a plan file holding a write it did not account for - see "what resolve
may write over") or written with conflicts or findings left, 2 usage.

This script carries no `--selftest` of its own; its cases live in
`tests/test_merge_manifest.py`.
"""
import argparse
import os
import posixpath
import shutil
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

import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)
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


def _write(path, text, newline="\n"):
    """Replace `path` atomically - git reads %A back the moment this exits.

    A PLAN FILE IS LF ON EVERY PLATFORM, as `_manifest_io.atomic_write_text` writes
    it: a text-mode handle's own default writes CRLF on Windows, so a resolved or
    driver-merged plan would differ byte for byte from the same plan written by any
    other writer, and read as a whole-file change in git. `newline=""` writes `text` byte for byte, for `.gitattributes` and the shim:
    the first keeps whatever endings it already had, and the second is a shell
    script, which a CR would break on every line."""
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
            text = r.stdout.decode("utf-8", "replace")
            # A LINE MERGE THAT COMES OUT CLEAN CAN STILL WRITE A KEY TWICE -
            # each side adding the same key in a different hunk - and git would
            # commit it. Such a text is written as the one block below instead.
            if not _written_twice_in(text):
                return text
    except OSError:
        pass
    ours, theirs = _read(ours_p), _read(theirs_p)
    return "<<<<<<< ours\n%s%s=======\n%s%s>>>>>>> theirs\n" % (
        ours, "" if ours.endswith("\n") else "\n",
        theirs, "" if theirs.endswith("\n") else "\n")


def _written_twice_in(text):
    """The JSON pointers of the keys `text` writes twice, as the door names them
    - [] for text that writes each once or is not JSON (markers)."""
    try:
        return _mio.parse_json_text(text)[1]
    except ValueError:
        return []


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


def _base_unknown(base):
    """`[(label, pointer)]` - where the merge base writes a key twice, so its
    value there is unknown (`_mio.without_written_twice`): `label` in the
    record merge's own spelling (`phases[P1].tasks`), `pointer` the key's JSON
    pointer in the base."""
    out = []
    for path, unknown in _mio.unknown_in_base(base):
        parts = []
        for p in path:
            if isinstance(p, tuple):
                parts.append("[%s]" % (p[1],))
            else:
                parts.append(("." if parts else "") + "%s" % (p,))
        out.append(("".join(parts) or "(document)", unknown.pointer))
    return out


def _under(label, conflict_path):
    """True when the record merge's conflict at `conflict_path` is at, inside
    or AROUND the value the base left unknown at `label` - a unit spelled
    `parent.{a,b}` included when one of its keys is that value. Around: a
    record one side deleted while the other kept it is "changed on the other
    side" only against a base that is known, and a record holding an unknown
    value is not."""
    if conflict_path == label or conflict_path.startswith(label + "[") \
            or conflict_path.startswith(label + "."):
        return True
    if conflict_path != "(document)" and (
            label.startswith(conflict_path + "[")
            or label.startswith(conflict_path + ".")):
        return True
    parent, _sep, key = label.rpartition(".")
    head = parent + "." if parent else ""
    if conflict_path.startswith(head + "{") and conflict_path.endswith("}"):
        return key in conflict_path[len(head) + 1:-1].split(",")
    return False


def _base_unknown_reason(pointer):
    return ("the merge base writes %s twice, so what it held there is not "
            "established and the two sides differ - keep the one meant by hand "
            "(nothing is renumbered: the base cannot say whether a record here "
            "was added on a side or was there before)" % (pointer,))


def _mark_base_unknown(conflicts, unknown):
    """Each conflict at or inside a value the base left unknown, reworded to
    say so: never "added on both sides", which would offer a renumbering of
    a record that may be one record held two ways."""
    for c in conflicts:
        for label, pointer in unknown:
            if _under(label, c["path"]):
                c["reason"] = _base_unknown_reason(pointer)
                break
    return conflicts


def run_driver(base_p, ours_p, theirs_p, path_label):
    """Merge in place into `ours_p`. Returns (exit code, message lines)."""
    label = path_label or os.path.basename(ours_p)
    texts = [_read(p) for p in (base_p, ours_p, theirs_p)]
    # git hands an EMPTY %O on an add/add - both sides created the file. That is
    # a state, not a malformed input, so it is told apart before parsing.
    added_both = not texts[0].strip()
    try:
        parsed = [(None, []) if added_both and i == 0 else _mio.parse_json_text(t)
                  for i, t in enumerate(texts)]
    except ValueError as exc:
        _write(ours_p, _line_merge(base_p, ours_p, theirs_p))
        return 1, ["%s %s: a side is not valid JSON (%s) - fell back to a line merge "
                   "with conflict markers" % (_TAG, label, exc)]
    # A SIDE THAT WRITES A KEY TWICE is not merged by record: its parse keeps
    # the last copy, and merging that would write one copy back with the other
    # dropped unsaid. It is left to the person, as markers, with the key named.
    # THE BASE is not a side: it is read only to tell which side changed what
    # and is never written back, so a key it alone writes twice (committed,
    # then repaired on both branches) reads as UNKNOWN there - the sides
    # settle it, or conflict at it, and no id under it is offered for
    # renumbering (`_mio.without_written_twice`, `_mark_base_unknown`).
    twice = [(side, pointer) for side, (_doc, found)
             in zip(("ours", "theirs"), parsed[1:]) for pointer in found]
    if twice:
        _write(ours_p, _line_merge(base_p, ours_p, theirs_p))
        return 1, ["%s %s: %s %s written twice - which copy is meant is not "
                   "established, so nothing was merged by record; fell back to a "
                   "line merge with conflict markers: delete by hand the copy "
                   "that is not meant" % (_TAG, label, ", ".join(
                       "%s on %s" % (pointer, side) for side, pointer in twice),
                       "is" if len(twice) == 1 else "are")]
    docs = [doc for doc, _found in parsed]
    docs[0] = _mio.without_written_twice(docs[0])

    if added_both and _kind(docs[1]) == "shard":
        result = _manifest_merge.collision(
            docs[1], docs[2], "this phase shard was created on both sides - one phase "
                              "id minted on two branches")
    else:
        if added_both:
            docs[0] = {}
        result = _manifest_merge.merge3(docs[0], docs[1], docs[2])
        _mark_base_unknown(result["conflicts"], _base_unknown(docs[0]))
    text = _manifest_merge.render(result, _mio.json_document)
    # The door asks the text before %A is written; one that writes a key twice
    # raises, and `driver_main` falls back to the line merge, which never
    # leaves such a text clean (`_line_merge`).
    _mio.check_plan_text(ours_p, text)
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
    # An id under a container the base writes twice is never counted here:
    # the base holds an `UnknownInBase` there, so the record merge conflicts
    # on the whole container and reports no collision inside it.
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
    rel = _tree_rel(top, path)
    code, _mh = _mi.git(top, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    if code != 0:
        return 1, ("%s refused: no merge is in progress, so there is no conflict to "
                   "resolve (resolve runs while `git merge` has stopped on the plan)"
                   % (_TAG,))
    code, base_c = _mi.git(top, "merge-base", "HEAD", "MERGE_HEAD")
    base_rev = base_c if code == 0 and base_c else None
    plans = {}
    for rev, name in (("HEAD", "HEAD"), ("MERGE_HEAD", "MERGE_HEAD"),
                      (base_rev, "the merge base")):
        try:
            # The base is read as the driver reads it: only to compare, so a
            # key it alone writes twice is absent there, never refused.
            plans[name] = (_plan_at(top, rev, rel,
                                    as_base=(name == "the merge base"))
                           if rev else None)
        except (OSError, ValueError, AttributeError, TypeError, KeyError) as exc:
            return 1, ("%s refused: nothing was written - the plan %s holds at %s (its "
                       "index or one of its phase files) cannot be read: %s"
                       % (_TAG, name, rel, exc))
    ours, theirs = plans["HEAD"], plans["MERGE_HEAD"]
    if ours is None or theirs is None:
        return 1, ("%s refused: %s is not a plan on both sides of this merge"
                   % (_TAG, rel))
    base = plans["the merge base"] or {}
    ids = _collisions(base, ours, theirs)
    if not ids:
        foreign = _foreign_records(top, path, rel, (base, ours, theirs))
        unknown = _base_unknown(base)
        return 1, ("%s refused: no id in %s was minted on both sides; what conflicts "
                   "is a real disagreement, which the marker blocks show%s%s"
                   % (_TAG, rel, "" if not unknown else
                      " - the merge base writes %s twice, so whether a record "
                      "under it was added on a side or was there before is not "
                      "established, and none is renumbered: keep by hand the "
                      "copy each block means" % (_output.some_of(
                          [p for _l, p in unknown]),),
                      _foreign_lines(foreign, "nothing was written, and ")))
    named, other = (theirs, ours) if side == "theirs" else (ours, theirs)
    mapping, refused = _renumbering(ids, named, other, _id_shape.suffix_here(top, named))
    if refused:
        return 1, ("%s refused: %s cannot be renumbered by kind - rename it by hand"
                   % (_TAG, ", ".join("%s" % (r,) for r in refused)))
    renamed, count = _id_refs.rename(named, mapping)
    sides = (renamed, other) if side == "ours" else (other, renamed)
    result = _manifest_merge.merge3(base, sides[0], sides[1])
    files = _render_plan(path, result, _sharded_at(top, rel))
    # A record of the renumbered side is that side's under its new id as much as
    # under its old one: the plan files hold the old id until resolve writes, and
    # the new one once it has.
    foreign = _foreign_records(top, path, rel, (base, ours, theirs, renamed))
    lock = None
    if _locks.available(top):
        lock = _locks.acquire(top, "index", note="merge-driver resolve",
                              out=lambda *_a, **_k: None)
        if not _locks.held(lock):
            return 1, "%s refused: %s" % (_TAG, _locks.refusal(lock, "index"))
    try:
        # Decided for every target before the first is written: a refusal that
        # came after some files were already replaced would leave the plan half
        # merged and the stray write gone anyway.
        answer = _merge_answer(top)
        strays, problem = _stray_targets(top, files, base_rev, answer)
        if problem:
            return 1, "%s refused: nothing was written - %s" % (_TAG, problem)
        if strays:
            return 1, _stray_refusal(strays, answer) + _foreign_lines(foreign, "")
        # THE DOOR asks every text before the first is written: one that
        # writes a key twice refuses the whole write.
        try:
            for target, text in files:
                _mio.check_plan_text(target, text)
        except _mio.DuplicateKeyError as exc:
            return 1, "%s refused: %s" % (_TAG, exc)
        for target, text in files:
            _write(target, text)
    finally:
        if _locks.took(lock):
            _locks.release(top, "index", out=lambda *_a, **_k: None)
    written = [_tree_rel(top, t) for t, _x in files]
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


# --- what resolve may write over --------------------------------------------------
# `resolve` builds every file from git's commits and never reads the work tree, so
# a plan write made while the merge is stopped - a gate's run record landing in a
# shard the merge left clean, which the evidence writer does because it reads only
# that shard, or a person's edit inside a marker block - would be replaced without
# a word. So under the index lock, every writer of the plan taking the same lock, a
# target is written over ONLY when the work tree holds there nothing, the text
# resolve is about to write (which lets a resolve stopped part way be run again
# rather than refused for ever by its own first write), or what git's merge left.
# Anything else is a STRAY, and one stray refuses the whole write. Markers in a file
# say nothing about whether someone typed between them, so a conflicted file is held
# to the same equality as a clean one. A marker line may differ from the answer's
# only in its LABEL, and only when that label is one git would have written there
# (`_label_judge`): git's line merge names the commits as `git merge` was typed,
# which nothing asked afterwards can repeat, so a label is accepted when it names
# the commit its marker stands for - HEAD's for `<<<<<<<`, MERGE_HEAD's for
# `>>>>>>>`, a merge base for `|||||||` - or is this driver's own label. Anything
# else on a marker line, a note or a trailing space, is a difference. The marker
# run is as long as the file's `conflict-marker-size` attribute says. A symbolic
# link is a stray whatever it points to: writing would put a regular file where
# the link was and leave its target as it is.
#
# WHAT THE MERGE LEFT IS GIT'S OWN ANSWER. `git merge-tree --write-tree HEAD
# MERGE_HEAD` merges the two commits again with no work tree and no index - the
# same merge machinery, so its merge bases, its diff algorithm and this driver where
# the clone configures it - and writes only objects. Each target's blob in that
# tree is read as checkout would write it (`cat-file --filters`) and compared as
# text read with universal newlines, as `_held_text` reads the work tree, so a CRLF
# or filtered checkout is the same text; a file that differs as text is still what
# the merge left when `git add` would store it as that blob (`_as_merge_left`).
# Nothing in the index or the work tree is
# read to make it, so `git add`, `git add -u`, `git restore --staged`, `git checkout
# -- <path>`, `git update-index` and a second resolve cannot move it; the index is
# read only to choose which command a refusal names (`_put_back`). Whether git can
# give that answer is decided by asking it, never by its version string, as
# `audit-task.py`'s merge check asks it: an exit other than 0 (clean) or 1
# (conflicted) - a git before 2.38 has no `--write-tree` - takes the fallback.
#
# THE FALLBACK REBUILDS THE MERGE FROM ITS COMMITS, path by path (`_rebuilt`): one
# blob where the sides agree or one side alone changed it, otherwise the content
# merge rerun - this driver, or `git merge-file` with the repository's conflict
# style and the file's marker size - with its result read through the
# same filters. It cannot know what git's merge did otherwise: a merge base git
# built from several, the histogram diff merge-ort runs where `git merge-file` uses
# myers, an `-X` option. A file git merged differently is then a stray, refused and
# never written over, and the refusal says the reference was rebuilt and why.
#
# Measured with git 2.53.0 on 2026-11-19 and 2026-11-20 in throwaway repositories:
# `git stash` is refused while a path is unmerged, and once everything is staged it
# ends the merge (MERGE_HEAD gone, so resolve refuses for want of one). `git merge
# -X ours` with the driver configured stops on the plan as the merge without the
# option does, and resolve completes; without the driver `-X ours` decides every
# conflicting hunk and the merge does not stop.
_UNREADABLE = object()
# The labels this driver's own line merge writes (`_line_merge`), by marker kind.
_DRIVER_LABELS = {"<": "ours", "|": "base", ">": "theirs"}
# The label git gives a base it merged from several.
_VIRTUAL_BASE_LABEL = "merged common ancestors"


def _tree_rel(top, path):
    """`path` relative to the work tree `top` (a realpath), `/`-separated. Its
    DIRECTORY goes through realpath, or a plan reached through a symlinked
    directory is named `../../..`; the file itself does not, or a plan file that
    is a link is named by wherever the link points."""
    here = os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(path))),
                        os.path.basename(path))
    return os.path.relpath(here, top).replace(os.sep, "/")


def _marker_size(top, rel):
    """The length of `rel`'s conflict markers: its `conflict-marker-size`
    attribute, or git's 7 when the attribute names no positive number."""
    _c, out = _mi.git(top, "check-attr", "conflict-marker-size", "--", rel)
    value = out.rsplit(": ", 1)[-1].strip() if out else ""
    return int(value) if value.isdigit() and int(value) > 0 else 7


def _marker(line, size):
    """`(kind, label)` of a conflict marker line of `size` - kind `<`, `|`, `>`,
    label None when the marker carries none - or None for any other line. The
    `=======` separator carries no label and is compared as any line is."""
    for kind in "<|>":
        run = kind * size
        if line == run:
            return kind, None
        if line.startswith(run + " ") and not line.startswith(run + kind):
            return kind, line[size + 1:]
    return None


def _label_judge(top):
    """`ok(kind, label)` - True when `label` is one git's merge, or this driver,
    would write on a `kind` marker of this merge: the driver's own label, HEAD or
    MERGE_HEAD by name, git's virtual-base label, or a revision (a `rev:path`
    label's `rev`) naming the commit the marker stands for. Git is asked only
    when a label needs it, and once per label."""
    asked, expected = {}, {}
    names = {"<": ("HEAD",), ">": ("MERGE_HEAD",), "|": (_VIRTUAL_BASE_LABEL,)}

    def commit(rev):
        if rev not in asked:
            code, oid = _mi.git(top, "rev-parse", "-q", "--verify",
                                "%s^{commit}" % (rev,))
            asked[rev] = oid.strip() if code == 0 and oid else None
        return asked[rev]

    def stands_for(kind):
        if kind not in expected:
            if kind == "|":
                _c, bases = _mi.git(top, "merge-base", "--all", "HEAD", "MERGE_HEAD")
                expected[kind] = set(ln.strip() for ln in (bases or "").splitlines()
                                     if ln.strip())
            else:
                expected[kind] = set([commit(names[kind][0])]) - set([None])
        return expected[kind]

    def ok(kind, label):
        if label is None:
            return False
        if label == _DRIVER_LABELS[kind] or label in names[kind]:
            return True
        rev = label.split(":", 1)[0]
        if not rev or rev != rev.strip() or rev.startswith("-") or " " in rev:
            return False
        found = commit(rev)
        return found is not None and found in stands_for(kind)
    return ok


def _same_as_left(held, left, size, ok):
    """True when `held` is the text `left` (the merge's answer), a marker line
    differing only by a label `ok` accepts on the HELD side; any other
    difference, on a marker line or off it, is a difference. The answer's own
    label is not judged: it is git's, or the rebuild's scratch name."""
    if held == left:
        return True
    if held is None or held is _UNREADABLE or left is None:
        return False
    mine, theirs = held.split("\n"), left.split("\n")
    if len(mine) != len(theirs):
        return False
    for a, b in zip(mine, theirs):
        if a == b:
            continue
        ma, mb = _marker(a, size), _marker(b, size)
        if not (ma and mb and ma[0] == mb[0] and ok(*ma)):
            return False
    return True


def _held_text(path):
    """What `path` holds, read the way `_write` wrote it; None when it is absent."""
    try:
        return _read(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return _UNREADABLE


def _git_bytes(top, *args):
    """(exit code, stdout bytes, stderr text) of one git command - unstripped, since
    a blob's last newline is part of what is compared."""
    try:
        r = subprocess.run(["git", "-C", top] + list(args), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    except OSError as exc:
        return 127, b"", "%s" % (exc,)
    return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace").strip()


def _as_text(raw):
    """Bytes as text with every line ending read as `\\n` - how `_held_text` reads
    the work tree, so a CRLF checkout and an LF blob compare equal."""
    return raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


def _blob_of(top, rev, rel):
    """The blob id `rev` holds at `rel`, or None when it holds no such path."""
    if not rev:
        return None
    code, oid = _mi.git(top, "rev-parse", "-q", "--verify", "%s:%s" % (rev, rel))
    return oid if code == 0 and oid else None


def _blob_text(top, oid, rel, filtered):
    """(the blob's text, problem) - when `filtered`, as checkout would write it at
    `rel` and read back as `_held_text` reads the work tree (`_as_text`); else as
    git stores it, which is what a merge is run over."""
    argv = (("cat-file", "--filters", "--path=%s" % (rel,), oid) if filtered
            else ("cat-file", "blob", oid))
    code, raw, err = _git_bytes(top, *argv)
    if code != 0:
        return None, ("git could not show %s's blob %s (`git %s` exited %d: %s)"
                      % (rel, oid, " ".join(argv[:2]), code, err or "no message"))
    return (_as_text(raw) if filtered else raw.decode("utf-8", "replace")), None


def _merge_answer(top):
    """{"tree", "conflicted", "why"} - git's own merge of HEAD and MERGE_HEAD,
    asked again: `tree` the tree it wrote and `conflicted` the paths it stopped
    on; `tree` None when git could not answer, `why` then saying what it said."""
    code, raw, err = _git_bytes(top, "merge-tree", "--write-tree", "-z", "HEAD",
                                "MERGE_HEAD")
    parts = raw.decode("utf-8", "replace").split("\0")
    tree = parts[0].strip()
    if code not in (0, 1) or not tree:
        return {"tree": None, "conflicted": frozenset(),
                "why": "`git merge-tree --write-tree` answered %d: %s"
                       % (code, (err or "no message").split("\n")[0])}
    conflicted = set()
    for part in parts[1:]:
        if not part:
            break
        conflicted.add(part.split("\t", 1)[-1])
    return {"tree": tree, "conflicted": frozenset(conflicted), "why": None}


def _content_merge(top, rel, sides):
    """(merged text, conflicted, problem) - the content merge git runs for `rel`
    when both sides changed it, rerun over the stored blobs `sides` (base, ours,
    theirs; '' for a base that lacks the path), in a scratch directory outside
    the work tree."""
    _c, attr = _mi.git(top, "check-attr", "merge", "--", rel)
    value = attr.rsplit(": ", 1)[-1].strip() if attr else "unspecified"
    _c, configured = _mi.git(top, "config", "--get", "merge.%s.driver" % (value,))
    if value in ("unset", "binary"):
        return sides[1], True, None
    if configured and value != DRIVER_NAME:
        return None, False, ("%s is merged by the driver `%s`, which resolve cannot "
                             "rerun to know what the merge left" % (rel, value))
    scratch = tempfile.mkdtemp(prefix="audit-resolve-reference-")
    try:
        paths = []
        for tag, text in zip(("O", "A", "B"), sides):
            p = os.path.join(scratch, tag)
            _write(p, text, newline="")
            paths.append(p)
        if configured:
            try:
                code, _lines = run_driver(paths[0], paths[1], paths[2], rel)
            except Exception:                                   # noqa: BLE001
                # What `driver_main` writes when the record merge raises.
                _write(paths[1], _line_merge(*paths))
                code = 1
            return _read(paths[1]), code != 0, None
        # As git's merge writes the conflict: the repository's conflict style
        # (a diff3 or zdiff3 block carries the base's lines) and the marker
        # length the file's attribute asks for.
        _c, style = _mi.git(top, "config", "--get", "merge.conflictStyle")
        style_arg = {"diff3": ["--diff3"], "zdiff3": ["--zdiff3"]}.get(
            (style or "").strip().lower(), [])
        try:
            r = subprocess.run(["git", "merge-file", "-p"] + style_arg
                               + ["--marker-size", str(_marker_size(top, rel)),
                                  paths[1], paths[0], paths[2]],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            return None, False, "git merge-file could not be run (%s)" % (exc,)
        if not 0 <= r.returncode < 128:
            return None, False, ("git merge-file exited %d over %s's sides"
                                 % (r.returncode, rel))
        return r.stdout.decode("utf-8", "replace"), r.returncode != 0, None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _reference(top, base_c, rel, answer):
    """{text, conflicted, oid, rebuilt} of what the merge left at `rel`, or None
    when it left no such path -> (that, problem). Read off git's own answer
    (`_merge_answer`) when there is one, else rebuilt from the commits; `oid` is
    the blob that holds the text, so a refusal can stage it back."""
    if not answer["tree"]:
        return _rebuilt(top, base_c, rel)
    oid = _blob_of(top, answer["tree"], rel)
    if oid is None:
        return None, None
    text, problem = _blob_text(top, oid, rel, True)
    if problem:
        return None, problem
    return {"text": text, "conflicted": rel in answer["conflicted"], "oid": oid,
            "rebuilt": False}, None


def _rebuilt(top, base_c, rel):
    """`_reference`'s answer where git could not give its own: the merge decided
    path by path as git's three-way merge decides it, from the commits."""
    b, o, t = (_blob_of(top, rev, rel) for rev in (base_c, "HEAD", "MERGE_HEAD"))
    conflicted = False
    if o == t:
        chosen = o
    elif b == o:
        chosen = t
    elif b == t:
        chosen = o
    elif o is None or t is None:
        # Changed on one side and deleted on the other: git stops, leaving the
        # changed side in the work tree.
        chosen, conflicted = o or t, True
    else:
        sides = []
        for oid in (b, o, t):
            if oid is None:
                sides.append("")
                continue
            text, problem = _blob_text(top, oid, rel, False)
            if problem:
                return None, problem
            sides.append(text)
        text, conflicted, problem = _content_merge(top, rel, sides)
        if problem:
            return None, problem
        # Stored as an object (never a file of the tree), so it is read through
        # the same filters as every other blob, and a refusal can stage it back.
        r = subprocess.run(["git", "-C", top, "hash-object", "-w", "--no-filters",
                            "--stdin"], input=text.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        chosen = r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""
        if not chosen:
            return None, ("git could not store the rebuilt merge of %s (`git "
                          "hash-object` exited %d)" % (rel, r.returncode))
    if chosen is None:
        return None, None
    text, problem = _blob_text(top, chosen, rel, True)
    if problem:
        return None, problem
    return {"text": text, "conflicted": conflicted, "oid": chosen,
            "rebuilt": True}, None


def _put_back(top, rel, merged, ok=None):
    """The commands that put `rel` back as the merge left it. Read off the index,
    which is why they choose words only and decide nothing: still unmerged there,
    `checkout -m` re-creates the conflict; staged as the merge's own text, a plain
    checkout is that text; staged as anything else, the merge's blob is staged
    first and then checked out."""
    ok = ok or _label_judge(top)
    code, out = _mi.git(top, "ls-files", "-s", "--", rel)
    stages = [ln.split()[:3] for ln in out.splitlines() if ln.strip()] if code == 0 else []
    if any(len(s) == 3 and s[2] != "0" for s in stages):
        return ("git checkout -m -- %s" % (rel,),)
    staged = stages[0][1] if stages and len(stages[0]) == 3 else None
    if staged and staged == merged["oid"]:
        return ("git checkout -- %s" % (rel,),)
    if staged:
        text, _p = _blob_text(top, staged, rel, True)
        if text is not None and _same_as_left(text, merged["text"],
                                              _marker_size(top, rel), ok):
            return ("git checkout -- %s" % (rel,),)
    mode = (stages[0][0] if stages and len(stages[0]) == 3 else "100644")
    return ("git update-index --cacheinfo %s,%s,%s" % (mode, merged["oid"], rel),
            "git checkout -- %s" % (rel,))


def _as_merge_left(top, target, rel, held, merged, ok=None):
    """True when `target` holds what the merge left at `rel`: the same text, a
    marker's label aside where git would have written that label
    (`_same_as_left`), or the same blob once cleaned as `git add` would clean
    it (`hash-object --path`, which writes nothing) - how git itself tells a file
    unchanged, so a file a plan writer wrote LF and unfiltered into a tree that
    checks out otherwise is not a change."""
    if _same_as_left(held, merged["text"], _marker_size(top, rel),
                     ok or _label_judge(top)):
        return True
    code, raw, _err = _git_bytes(top, "hash-object", "--path=%s" % (rel,), "--", target)
    return code == 0 and raw.decode("utf-8", "replace").strip() == merged["oid"]


def _stray_targets(top, files, base_c, answer):
    """([(rel, what it holds, (the commands that put it back))], problem) - the
    targets holding bytes resolve cannot account for. `problem` is a sentence
    when git could not be asked, and then nothing may be written."""
    strays, ok = [], _label_judge(top)
    for target, text in files:
        rel = _tree_rel(top, target)
        linked = os.path.islink(target)
        held = _held_text(target)
        if not linked and (held is None or held == text):
            continue
        merged, problem = _reference(top, base_c, rel, answer)
        if problem:
            return [], ("git could not say what the merge left at %s - %s"
                        % (rel, problem))
        if merged is None:
            strays.append((rel, "not in git's merge result, and not what resolve "
                                "writes there",
                           ("move %s out of the work tree - the merge did not leave "
                            "it, so nothing puts it back" % (rel,),)))
        elif linked:
            strays.append((rel, "a symbolic link - writing would put a regular file "
                                "where the link is and leave what it points to as "
                                "it is", _put_back(top, rel, merged, ok)))
        elif _as_merge_left(top, target, rel, held, merged, ok):
            continue
        elif merged["conflicted"]:
            strays.append((rel, "changed since git's merge left its conflict markers "
                                "there", _put_back(top, rel, merged, ok)))
        else:
            strays.append((rel, "changed since git's merge left it clean",
                           _put_back(top, rel, merged, ok)))
    return strays, None


def _stray_refusal(strays, answer):
    """The refusal for targets resolve would overwrite unaccounted - each named,
    with the way on that is true: put the file back, which discards the write.
    Where git could not give its own answer, it says so and what the rebuilt one
    cannot know."""
    lines = ["%s refused: nothing was written - %d plan file(s) hold bytes neither "
             "git's merge left there nor resolve wrote, and writing the merged plan "
             "would replace them:" % (_TAG, len(strays))]
    lines += ["    %s - %s" % (rel, held) for rel, held, _fix in strays]
    if not answer["tree"]:
        lines.append("    what the merge left was rebuilt from its commits, because "
                     "git could not merge them again here (%s). The rebuild takes "
                     "the one merge base `git merge-base` names, `git merge-file`'s "
                     "myers diff and no `-X` option, so a file git's merge made "
                     "otherwise is named above too, and the commands below put "
                     "back the rebuilt text" % (answer["why"],))
    lines.append("    a write made while the merge is stopped cannot be committed with "
                 "it, and no command here carries it into the merged plan. To go on, "
                 "put each file back, which DISCARDS what it holds, then run resolve "
                 "again:")
    lines += ["      %s" % (step,) for _rel, _held, fix in strays for step in fix]
    lines.append("    what a discarded write held: a task or phase run's record is "
                 "that run's only copy, so it comes back by running the gate again "
                 "with --record once the merge is committed; `run-test-gate.py "
                 "<manifestPath> <phaseId> --reconcile` re-points a subject only at "
                 "a run its records or an evidence row still hold (a full run's, or "
                 "an earlier release's). Anything else is made again by running the "
                 "verb that wrote it. To keep the bytes as they are, copy the file "
                 "out of the work tree first.")
    return "\n".join(lines)


# --- a record neither side wrote ---------------------------------------------------
# The record merge keeps a value that is ONE ACCOUNT whole (`_manifest_merge.
# MERGE_UNITS`): a run record and its pointer, a CI run, a sign-off's verdict. A
# person resolving by hand can still type one together from both sides - one side's
# run id beside the other side's status. `resolve` never writes over such a file -
# it is a stray, or the merge holds no collision to renumber - but neither refusal
# says which record it is. So each plan file is read as it stands, every marker block
# still in it read once as its ours lines and once as its theirs lines (a diff3 base
# section dropped), and each reading compared, whole value by whole value, with the
# same file in the base, ours, theirs and - once resolve has renumbered a side - that
# side renumbered. A run recorded while the merge was stopped is named the same way:
# it too is neither side's. A file both sides hold alike that still parses to what
# they hold is passed over after one parse - that is most shards of a sharded plan,
# and walking each cost the resolver seconds - while one that differs from it is
# walked like any other. A file that does not parse in a reading is skipped - what
# the edit left unreadable is the plan reader's to report, not this one's.
def _readings(text, size):
    """`text` with each marker block kept as one side - [ours' reading, theirs'
    reading], or [text] when it holds no marker. A diff3 base section is dropped."""
    lines = text.split("\n")
    if not any(_marker(ln, size) for ln in lines):
        return [text]
    out = []
    for side in ("<", ">"):
        kept, mode = [], None
        for ln in lines:
            mark = _marker(ln, size)
            if mark and mark[0] in "<|":
                mode = mark[0]
            elif ln == "=" * size and mode:
                mode = ">"
            elif mark and mark[0] == ">":
                mode = None
            elif mode is None or mode == side:
                kept.append(ln)
        out.append("\n".join(kept))
    return out


def _foreign_records(top, path, rel, plans):
    """[(plan file, record path)] of every whole value a plan file in the work tree
    holds that none of `plans` - base, ours, theirs, then any side renumbered -
    holds in that file. A file the sides hold alike is walked only when it no
    longer parses to what they hold."""
    files = [(path, rel, tuple(plans))]
    if _sharded_at(top, rel):
        parts = [_mio.split_manifest(plan or {}) for plan in plans]
        files = [(path, rel, tuple(index for index, _shards in parts))]
        for pid in sorted(set(pid for _index, shards in parts for pid in shards),
                          key=_manifest_merge.natural_key):
            shard_rel = _mio.shard_rel_path(pid)
            files.append((os.path.join(os.path.dirname(path), shard_rel),
                          posixpath.join(posixpath.dirname(rel), shard_rel),
                          tuple(shards.get(pid) for _index, shards in parts)))
    found = []
    for target, label, sides in files:
        held = _held_text(target)
        if held is None or held is _UNREADABLE:
            continue
        if all(s == sides[1] for s in sides[2:]) and _parsed(held) == sides[1]:
            # Both sides hold this file alike and it still holds what they hold:
            # nothing in it can be neither side's, and one parse says so without
            # walking it.
            continue
        for reading in _readings(held, _marker_size(top, label)):
            try:
                doc = _mio.parse_json_text(reading)[0]
            except ValueError:
                continue
            for f in _manifest_merge.foreign_values(sides[0], sides[1], sides[2], doc,
                                                    also=sides[3:]):
                if (label, f["path"]) not in found:
                    found.append((label, f["path"]))
    return found


def _parsed(text):
    """`text` as JSON, or None when it is not - a file holding markers is not."""
    try:
        return _mio.parse_json_text(text)[0]
    except ValueError:
        return None


def _foreign_lines(foreign, lead):
    """The lines a refusal adds for `foreign` - '' when there is none. `lead` opens
    the sentence: a refusal that has not said nothing was written says it here."""
    if not foreign:
        return ""
    lines = ["", "    %s%d record(s) in the plan files are "
                 "neither side's nor the base's - one account the merge keeps whole, "
                 "assembled from both sides by hand or written while the merge was "
                 "stopped:" % (lead, len(foreign))]
    lines += ["      %s: %s" % (label, where) for label, where in foreign]
    lines.append("    keep one side's block of each whole, or, for a run, record it "
                 "again once the merge is committed")
    return "\n".join(lines)


def _sharded_at(top, rel):
    """The layout of the plan HEAD holds, read off its raw index - the assembled
    plan carries no `shard` refs, and the working copy may be full of markers."""
    code, text = _mi.git(top, "show", "HEAD:%s" % (rel,))
    try:
        return code == 0 and _mio.is_sharded(_mio.parse_json_text(text)[0])
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
    return _claude_home.attach_usage_hint(ap)


def main(argv):
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
