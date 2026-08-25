#!/usr/bin/env python3
"""
Put the manifest back to the truth after history was rewritten.

`hooks/guard-history-rewrite.py` refuses the commands that orphan a recorded
commit, and `/audit:doctor` reports one that resolves nowhere as a FINDING. This
is the third case: it happened anyway — the hook was off, the rewrite was done in
another clone, or somebody worked outside the audit checkout — and the manifest
now names commits git does not have.

WHAT IT DOES NOT DO IS THE POINT. It does not re-anchor. There is no search for a
commit with the same message or the same tree, because the commit the task was
verified against is gone and a plausible substitute makes the trail read as intact
when it is not. It sets each unreachable `task.commit` to `null` and writes a
JOURNAL ROW carrying what was there — so the manifest says "this commit is no
longer reachable", which is true, and the trail says when it stopped being
reachable and what it used to name.

Read-only by default. `--apply` is the only path that writes, and it holds the
index lock, revalidates BEFORE saving, and refuses rather than leave a half-
repaired manifest.

  repair-commits.py <manifest>              report what is unreachable (no writes)
  repair-commits.py <manifest> --apply      clear them, journal each one
  repair-commits.py <manifest> --json       machine-readable, either mode

Exit codes: 0 nothing unreachable (or the repair applied) - 1 unreachable commits
found in report mode, or a refused apply - 2 usage/read error.
"""
import json
import os
import sys
import time

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

import _commit_trail  # noqa: E402  (the shared question: is this SHA reachable?)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _locks  # noqa: E402  (the index lock, already the one implementation)
import _manifest_rules as _rules  # noqa: E402  (refuse rather than write invalid)
import _journal_io  # noqa: E402  (the trail this repair has to leave behind)

LOCK_NAME = "index"


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def project_of(mpath):
    """The root that owns the journal, the lock and the config.

    Derived UPWARD FROM THE MANIFEST, never from the manifest's own directory.
    `dirname(manifest)` is `docs/audit/`, and the journal then resolves
    `manifestPath` against it a second time and lands in
    `docs/audit/docs/audit/journal/` - which is what this did until it was run
    against a real repo. `audit-task._resolve_project` solved the same class
    (F-C-1) and this follows it.
    """
    here = os.path.dirname(os.path.abspath(mpath)) or "."
    for _ in range(8):
        if os.path.isdir(os.path.join(here, ".git")):
            return here
        nxt = os.path.dirname(here)
        if nxt == here:
            break
        here = nxt
    return os.path.dirname(os.path.abspath(mpath)) or "."


def git_root_of(manifest, mpath):
    """Where git runs: the project, plus meta.gitRoot when the workspace nests."""
    project = project_of(mpath)
    rel = ((manifest or {}).get("meta") or {}).get("gitRoot") or "."
    return project if rel == "." else os.path.abspath(os.path.join(project, rel))


def report(manifest, git_root):
    found = _commit_trail.dangling(manifest, git_root)
    rows = lambda k: [{"phaseId": p, "taskId": t, "commit": s}
                      for p, t, s in found[k]]                    # noqa: E731
    return {
        "missing": rows("missing"),
        "unreachable": rows("unreachable"),
        "unchecked": rows("unchecked"),
        # What --apply would clear: both broken classes. They differ in what a
        # HUMAN can still do (an unreachable commit is recoverable until gc), not
        # in what the manifest should say - it names a commit no ref reaches
        # either way, and saying so is the honest state.
        "lost": rows("missing") + rows("unreachable"),
        "recorded": len(_commit_trail.recorded(manifest)),
    }


def render(ans, applied=False):
    lines = []
    if ans["unchecked"]:
        # Named rather than folded into "clean": git could not be asked, and a
        # reader who cannot tell that from "every commit is present" will read
        # an unanswerable question as a good answer.
        lines.append("UNCHECKED: %d recorded commit(s) could not be verified "
                     "(no git, or git would not answer). This is not a clean "
                     "trail - it is an unasked question."
                     % (len(ans["unchecked"]),))
    if not ans["lost"]:
        lines.append("OK: all %d recorded task commit(s) still resolve."
                     % (ans["recorded"],))
        return "\n".join(lines)
    for row in ans["unreachable"]:
        lines.append("%s %s -> %s  (object still present, NO ref reaches it - "
                     "recoverable until git gc runs)"
                     % ("CLEARED " if applied else "FINDING:",
                        row["taskId"], row["commit"][:12]))
    for row in ans["missing"]:
        lines.append("%s %s -> %s  (not in this clone at all)"
                     % ("CLEARED " if applied else "FINDING:",
                        row["taskId"], row["commit"][:12]))
    if applied:
        lines.append("")
        lines.append("Cleared %d unreachable commit(s). Each is recorded in the "
                     "journal with the SHA it used to name - the manifest now "
                     "says the commit is unreachable, which is true, rather than "
                     "naming one that is not there." % (len(ans["lost"]),))
    else:
        lines.append("")
        lines.append("%d recorded commit(s) no longer resolve to anything a ref "
                     "reaches. If any is marked recoverable above, RESTORING A "
                     "BRANCH ONTO IT puts the trail back and is the better repair "
                     "- do that first. Otherwise re-run with --apply to clear "
                     "them and journal what was lost. Nothing here guesses a "
                     "replacement: a substitute found by matching commit messages "
                     "would make the trail read as intact when it is not."
                     % (len(ans["lost"]),))
    return "\n".join(lines)


def apply_repair(mpath, manifest, ans):
    """Clear under the lock, revalidate before saving, journal each cleared row."""
    project = project_of(mpath)
    lost = [(r["phaseId"], r["taskId"], r["commit"]) for r in ans["lost"]]
    # F188. THE RETURN VALUE IS A STATUS CODE, AND BOTH THINGS DONE WITH IT HERE
    # WERE WRONG. It was named `handle` and tested with `isinstance(..., dict)`,
    # which is never true of an int - so the release never ran and every write left
    # the index lock on disk, and the code was never read, so a refused acquire
    # fell into the write below and changed the manifest with no lock held. The
    # The refusal is `_locks`' own sentence and NOT its terminal lines: those name
    # the host a live pid runs on, which has no business in a returned payload.
    # A project with NO lock scheme is the third answer, and it is not a
    # refusal: `acquire` says `E_ERR` both for "not a git repository" and for
    # a real failure, and refusing on every non-zero code refused every write
    # in a non-git project - which the panel handles by falling back to a
    # working-tree lockfile and proceeding. Asked before acquiring, where the
    # answer is unambiguous.
    code = None
    if _locks.available(project):
        code = _locks.acquire(project, LOCK_NAME,
                              note="repair:commits",
                              out=lambda *_a, **_k: None)
        if not _locks.held(code):
            return False, _locks.refusal(code, LOCK_NAME)
    try:
        manifest, cleared = _commit_trail.clear(manifest, lost)
        findings, _warnings = _rules.validate(manifest)
        if findings:
            return False, ("the result would be invalid, so nothing was written: "
                           + "; ".join(findings[:3]))
        # Written back in whatever layout it arrived in - `_proposals._save`'s
        # rule, which is the only correct one under the sharded form: a phase
        # lives in a shard and a whole-file dump would flatten it.
        if _mio.is_sharded(_mio.read_json(mpath)):
            _mio.save_sharded(mpath, manifest)
        else:
            _mio.atomic_write_json(mpath, manifest)
    finally:
        if _locks.held(code):
            _locks.release(project, LOCK_NAME, out=lambda *_a, **_k: None)

    # The record. Fail-soft by the journal's own contract: a repair that
    # SUCCEEDED must not be reported as failed because the note about it could
    # not be written - but the failure is said, not swallowed.
    rel = os.path.relpath(mpath, project).replace(os.sep, "/")
    ok = bool(_journal_io.append(project, {
        "action": "trail.repair",
        # Persisted row: "/" separators regardless of platform, like every other
        # journal path.
        "target": rel,
        "summary": _commit_trail.summary(cleared),
        # `changes`, not an invented key. `normalise_details` DROPS anything
        # outside DETAILS_KEYS - by design, so a writer cannot decide the format
        # for every reader after it - and a `cleared` block was silently
        # discarded until this was run and the row read back.
        "details": {"changes": [{"id": c["taskId"], "field": "commit",
                                 "from": c["wasCommit"], "to": None}
                                for c in cleared]},
        "actor": {"sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                  "via": "cli"}},
        config={"manifestPath": rel}))
    return True, ("journaled" if ok else "NOT journaled (the journal is "
                  "unwritable or disabled) - the manifest was still repaired")


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write(__doc__.strip().split("  repair-commits.py")[0][-260:]
                         + "\n")
        return 2
    mpath = argv[0]
    as_json = "--json" in argv[1:]
    do_apply = "--apply" in argv[1:]
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:
        sys.stderr.write("cannot read %s: %s\n" % (mpath, exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("%s is not an object\n" % (mpath,))
        return 2

    ans = report(manifest, git_root_of(manifest, mpath))
    if not do_apply:
        print(json.dumps(ans, indent=1, sort_keys=True) if as_json
              else render(ans))
        return 1 if ans["lost"] else 0

    if not ans["lost"]:
        print(json.dumps(dict(ans, applied=False), indent=1, sort_keys=True)
              if as_json else render(ans))
        return 0
    ok, message = apply_repair(mpath, manifest, ans)
    if as_json:
        print(json.dumps(dict(ans, applied=ok, message=message),
                         indent=1, sort_keys=True))
    else:
        print(render(ans, applied=ok) if ok else ("REFUSED: " + message))
        if ok:
            print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("repair-commits.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_repair_commits.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
