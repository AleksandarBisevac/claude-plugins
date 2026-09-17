#!/usr/bin/env python3
"""
Put a plan's `tests.add` entries into the shape the rule requires, without
inventing a path for the ones that name none.

The schema asks for `"<path>: <what it asserts>"`, because that leading path is
what `/audit:task add` and `scope` carry into a task's `files` and into the
`fileIndex` - and `_invariants.commit_scope` grades a task's commit against that
list. An entry written as a plain sentence therefore leaves the case file outside
the scope the work is graded against, the validator says so on every unfinished
`tdd` task, and it becomes a refusal at the next major. Every plan generated
before the commands prescribed the shape carries entries like that, and an
announcement with no migration behind it strands all of them.

WHAT IT REPAIRS, AND WHAT IT HANDS BACK. The only path it will ever write is one
the entry ITSELF already spells: an entry mentioning `tests/cart.spec.ts` in its
prose is rewritten to open with it. An entry that mentions no path, or mentions
more than one, is REPORTED with the task that holds it and the command that fixes
it by hand. Nothing is derived from the task's `files`, from a naming convention
or from the phase - a sentence is visibly not a path, a wrong path is not, and
the wrong one is the worse thing to leave in a field that grants commit scope.

THE REWRITE ONLY EVER PREPENDS. The entry comes back as the tail of its own
replacement, so nothing its author wrote is lost and the result can be checked by
looking at it. That is also what makes it safe on a task already under way: what
`/audit:task scope`'s append-only rule protects is a grading that reads `files`
backwards, and a prefix can only ADD to the paths an entry names.

`files` AND `fileIndex` ARE NOT TOUCHED, deliberately. They are `audit-task.py`'s
to derive, re-derived there on every `add` and `scope`, and a second writer of the
index is how two writers come to disagree about it. So this repairs the entries,
and the next scope of the task carries their paths into the scope.

Read-only by default. `--apply` is the only path that writes, and it holds the
index lock, revalidates BEFORE saving, and refuses rather than leave a half-
repaired manifest.

  repair-tests-add.py <manifest>            report what is owed (no writes)
  repair-tests-add.py <manifest> --apply    rewrite the derivable ones, journal
  repair-tests-add.py <manifest> --json     machine-readable, either mode

Exit codes: 0 every graded entry names a file (nothing owed, or the repair left
none owed) - 1 entries still need a hand, or a refused apply - 2 usage/read error.

This script carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_repair_tests_add.py` (hyphens become underscores - a
hyphenated name is not importable).
"""
import json
import os
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

import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _locks  # noqa: E402  (the index lock, already the one implementation)
import _manifest_rules as _rules  # noqa: E402  (the shape rule AND refuse-before-save)
import _journal_io  # noqa: E402  (the trail a write into the plan has to leave)

LOCK_NAME = "index"

# What a reader is told to do about an entry this cannot repair, keyed by the
# verdict that produced it. ONE ROW PER VERDICT and not one sentence for both,
# because the two are repaired differently: an entry naming no file needs somebody
# to decide where the case goes, and one naming several needs somebody to say which
# of them holds it. A reader handed the other one's advice does neither.
OWED_REASON = {
    _rules.REPAIR_UNNAMED:
        "names no file at all, so there is nothing here to move to the front - "
        "the file the case will live in has to be decided",
    _rules.REPAIR_AMBIGUOUS:
        "names more than one file, and which of them holds the case is not "
        "something this can read out of the sentence",
}


# --- reading the plan -------------------------------------------------------------
def project_of(mpath):
    """The root that owns the journal, the lock and the config.

    Derived UPWARD FROM THE MANIFEST, never from the manifest's own directory:
    `dirname(manifest)` is `docs/audit/`, and the journal then resolves
    `manifestPath` against it a second time and lands in
    `docs/audit/docs/audit/journal/`. `repair-commits.py` carries the same walk
    for the same reason, and it was a real run rather than a case that found it
    there.
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


def rows_for(manifest):
    """Every graded `tests.add` entry that is not already in the shape, in order.

    THE FILTER IS THE VALIDATOR'S OWN (`tests_add_graded`), asked rather than
    restated, so this cannot offer to repair an entry nothing complained about
    nor skip one that is warned about every run. A settled task is exempt there
    and therefore exempt here: its entries describe work already judged.

    A row carries the task's `status` because that is what tells a reader whether
    the rewrite lands on work already under way - a fact about the row, not a
    reason to skip it.
    """
    rows = []
    for phase, task in _mio.iter_tasks(manifest):
        if not _rules.tests_add_graded(task):
            continue
        entries = (task.get("tests") or {}).get("add")
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            verdict, replacement = _rules.tests_add_repair(entry)
            if verdict == _rules.REPAIR_NAMED:
                continue
            rows.append({"phaseId": phase.get("id"), "taskId": task.get("id"),
                         "status": task.get("status"), "index": i,
                         "verdict": verdict, "entry": entry,
                         "replacement": replacement})
    return rows


def graded_entries(manifest):
    """How many entries the rule above actually looked at.

    THE VACUITY BASIS, and the reason it is returned rather than inferred: a plan
    of behaviour-preserving work has no graded entry at all, and "nothing owed"
    over nothing read is a different answer from "nothing owed" over a plan full
    of them. The render says which of the two it is.
    """
    seen = 0
    for _phase, task in _mio.iter_tasks(manifest):
        if not _rules.tests_add_graded(task):
            continue
        entries = (task.get("tests") or {}).get("add")
        seen += len(entries) if isinstance(entries, list) else 0
    return seen


def report(manifest):
    rows = rows_for(manifest)
    return {
        "rewrite": [r for r in rows if r["verdict"] == _rules.REPAIR_REWRITE],
        "owed": [r for r in rows if r["verdict"] != _rules.REPAIR_REWRITE],
        "graded": graded_entries(manifest),
    }


# --- writing ----------------------------------------------------------------------
def rewrite(manifest, rows):
    """Apply the rewritable rows in place; return the ones that landed.

    MATCHED ON THE ENTRY'S TEXT AND NOT ONLY ON ITS INDEX. The rows were read off
    this same document, so the index is right - but an index is right only while
    nothing has moved, and a repair that wrote the replacement over whatever now
    sits at that position would be a silent edit of a different entry. The text
    check costs a comparison and makes the write unable to hit the wrong line.
    """
    wanted = {}
    for row in rows:
        if row["verdict"] == _rules.REPAIR_REWRITE:
            wanted.setdefault((row["taskId"], row["index"]), row)
    applied = []
    for _phase, task in _mio.iter_tasks(manifest):
        entries = (task.get("tests") or {}).get("add")
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            row = wanted.get((task.get("id"), i))
            if row is None or row["entry"] != entry:
                continue
            entries[i] = row["replacement"]
            applied.append(row)
    return applied


def apply_repair(mpath, manifest, ans):
    """Rewrite under the lock, revalidate before saving, journal what moved.

    TWO REFUSALS, WORDED APART, because they are two different situations and a
    reader handed the wrong one goes looking in the wrong place. A plan that
    ALREADY has findings is refused before anything is touched, and the message
    says the repair is not what broke it - the same reading `migrate-manifest.py`
    takes of its own source. A plan the rewrite would break is refused after,
    with a sentence that says so. Collapsing them into "the result would be
    invalid" is what makes an operator go hunting for a bug in the migration
    over a plan that was already failing to validate.
    """
    project = project_of(mpath)
    before, _bw = _rules.validate(manifest)
    if before:
        return False, ("the plan already has validator finding(s) and the "
                       "repair is not what put them there, so nothing was "
                       "written - fix the plan first, then re-run: "
                       + "; ".join(before[:3])), []
    # The lock is asked for only where there is one to ask for: `acquire` answers
    # the same error for "not a git repository" as for a real failure, so refusing
    # on every non-zero code would refuse every write in a project with no lock
    # scheme at all.
    code = None
    if _locks.available(project):
        code = _locks.acquire(project, LOCK_NAME,
                              note="repair:tests-add",
                              out=lambda *_a, **_k: None)
        if not _locks.held(code):
            return False, _locks.refusal(code, LOCK_NAME), []
    try:
        applied = rewrite(manifest, ans["rewrite"])
        findings, _warnings = _rules.validate(manifest)
        if findings:
            return False, ("the repair would have made the plan invalid, so "
                           "nothing was written: "
                           + "; ".join(findings[:3])), []
        # Written back in whatever layout it arrived in: a phase lives in a shard
        # under the sharded form, and a whole-file dump would flatten it.
        if _mio.is_sharded(_mio.read_json(mpath)):
            _mio.save_sharded(mpath, manifest)
        else:
            _mio.atomic_write_json(mpath, manifest)
    finally:
        if _locks.held(code):
            _locks.release(project, LOCK_NAME, out=lambda *_a, **_k: None)

    # The record. Fail-soft by the journal's own contract - a repair that
    # SUCCEEDED must not be reported as failed because the note about it could not
    # be written - but the failure is said, not swallowed. `append_from_cli`
    # because this is a script an operator runs from Bash, and an append no writer
    # claims is what the Bash guard reports as a shell write into the trail.
    # Persisted row: "/" separators regardless of platform, like every other
    # journal path.
    rel = _output.posix_rel(mpath, project)
    touched = []
    for row in applied:
        if row["taskId"] not in touched:
            touched.append(row["taskId"])
    ok = bool(_journal_io.append_from_cli(project, {
        "action": "scope.repair",
        "target": rel,
        "summary": "tests.add rewritten to open with the path each entry "
                   "already named, on %s" % (_output.some_of(touched),),
        # `changes`, and the keys `normalise_details` keeps - anything outside
        # them is dropped by design, so an invented key ships an empty block.
        "details": {"changes": [{"id": row["taskId"], "field": "tests.add",
                                 "from": row["entry"],
                                 "to": row["replacement"]}
                                for row in applied]},
        "actor": {"sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                  "via": "cli"}},
        config={"manifestPath": rel}))
    return True, ("journaled" if ok else "NOT journaled (the journal is "
                  "unwritable or disabled) - the manifest was still "
                  "repaired"), applied


# --- rendering --------------------------------------------------------------------
def _where(row):
    return "%s [%s] entry %d" % (row["taskId"] or "?", row["status"] or "?",
                                 row["index"])


def render(ans, applied=None):
    """Plain ASCII. `applied` is the rows that actually moved, or None in report
    mode - the difference decides the tense, and a row that did not move must
    never be printed in the past tense."""
    lines = []
    moved = [] if applied is None else applied
    for row in ans["rewrite"]:
        landed = applied is not None and row in moved
        lines.append("%s %s" % ("REWROTE " if landed else "REWRITABLE:",
                                _where(row)))
        lines.append("    was: %s" % (row["entry"],))
        lines.append("    now: %s" % (row["replacement"],))
    for row in ans["owed"]:
        lines.append("FOR A HUMAN: %s - %s"
                     % (_where(row), OWED_REASON.get(row["verdict"], "?")))
        lines.append("    %r" % (row["entry"],))
    if not lines:
        if not ans["graded"]:
            # NOT folded into "clean". A plan of behaviour-preserving work has no
            # entry this rule reaches, and a reader who cannot tell that from "they
            # all name a file" has read an unasked question as a good answer.
            return ("NOTHING GRADED: no unfinished `tdd` task carries a "
                    "tests.add entry, so this rule reached nothing here.")
        return ("OK: every tests.add entry the rule grades already opens with "
                "the path its case will live in.")
    lines.append("")
    if applied is None:
        if ans["rewrite"]:
            lines.append("Re-run with --apply to rewrite the entries above that "
                         "already spell their path. The sentence is kept whole "
                         "and the path is put in front of it, so nothing its "
                         "author wrote is lost.")
        if ans["owed"]:
            lines.append("The rest name no file this can read, and nothing here "
                         "will guess one: a path nobody typed reaches `files` "
                         "and the fileIndex, where a sentence at least reads as "
                         "the prose it is. Repair each with `/audit:task scope "
                         "<taskId> --tests-add \"<path>: <what it asserts>\"`, "
                         "passing the task's other entries in the same call - "
                         "the flag replaces the list.")
    else:
        lines.append("The paths came out of the entries themselves. `files` and "
                     "the fileIndex are untouched - they are re-derived by "
                     "`/audit:task scope`, which is the one writer of them.")
        if ans["owed"]:
            lines.append("The entries marked FOR A HUMAN are unchanged and still "
                         "draw the validator's warning.")
    return "\n".join(lines)


# --- cli --------------------------------------------------------------------------
def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write("usage: repair-tests-add.py <manifest> [--apply] "
                         "[--json]\n")
        return 2
    mpath = argv[0]
    as_json = "--json" in argv[1:]
    do_apply = "--apply" in argv[1:]
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:                                   # noqa: BLE001
        sys.stderr.write("cannot read %s: %s\n" % (mpath, exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("%s is not an object\n" % (mpath,))
        return 2

    ans = report(manifest)
    if not do_apply or not ans["rewrite"]:
        # Nothing to write is reported in the present tense either way, and the
        # verdict is the same question in both modes: does every graded entry
        # name a file now?
        print(json.dumps(dict(ans, applied=False), indent=1, sort_keys=True)
              if as_json else render(ans))
        return 1 if (ans["rewrite"] or ans["owed"]) else 0

    ok, message, applied = apply_repair(mpath, manifest, ans)
    if as_json:
        print(json.dumps(dict(ans, applied=ok, message=message,
                              rewritten=applied), indent=1, sort_keys=True))
    else:
        print(render(ans, applied=applied) if ok else ("REFUSED: " + message))
        if ok:
            print(message)
    if not ok:
        return 1
    return 1 if ans["owed"] else 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("repair-tests-add.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_repair_tests_add.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
