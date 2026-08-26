#!/usr/bin/env python3
"""
The pipeline's receipts, joined against the plan they are receipts for.

Split out of `audit-doctor.py`. This is the one check in the doctor that
CORRELATES two records rather than inspecting one: the journal's hook-emitted
`task.complete` rows against the manifest's done tasks, plus the commit SHAs
those tasks name against what git actually has, plus the usage ledger's
coverage of the same task ids.

Its grading rule is why it stands alone. A done task INSIDE the record era with
no record is positive evidence that the manifest was edited outside the pipeline
- a FINDING - while everything the check merely could not look up is a WARNING
at most, and the era boundary is decided by the WATERMARK with no config knob:
the first `task.complete` row's ts. Zero such rows means an older plugin wrote
this history, and that is one ok line rather than a nag.

Layer 4, for the same reason `_doctor_trail` is: it runtime-loads `usage_ledger`
(layer 3) for the coverage arm. `_journal_io` (layer 1) is imported, not loaded.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__doctor_completions.py` - see
`plugins/audit/tests/_harness.py`.
"""
import os
import shutil
import subprocess
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

import _doctor_report as _base  # noqa: E402  (Report, the loader, the constants)
import _evidence_io  # noqa: E402  (the ledger this correlates the plan against)
import _journal_io  # noqa: E402  (read/verify the audit trail, at layer 1)
import _commit_trail  # noqa: E402  (is a recorded SHA still reachable?)

# A thin module-level alias, not a copy: the bodies below were moved out of
# `audit-doctor.py` unchanged, and an alias keeps them reading the same name
# while there is still exactly one definition of it. A case pins the identity.
_load = _base._load


# --- checks: completion records -------------------------------------------------
def _hours_between(a, b):
    """Hours between two ISO timestamps, or None when either cannot be read —
    an unreadable timestamp is a reason to say nothing, not to accuse."""
    try:
        import calendar

        def parse(s):
            return calendar.timegm(time.strptime(str(s)[:19],
                                                 "%Y-%m-%dT%H:%M:%S"))
        return abs(parse(a) - parse(b)) / 3600.0
    except Exception:
        return None


def _check_commit_trail(rep, manifest, git_root):
    """Is every recorded `task.commit` still reachable? Independent of the journal.

    Split out so it can run before the journal-shaped early returns above, and
    because `repair-commits.py` asks `_commit_trail` the same question: one
    implementation, two readers.
    """
    trail = _commit_trail.dangling(manifest, git_root)
    if trail["missing"]:
        rep.finding("commit trail",
                    "the manifest names a commit git does not have: %s"
                    % ", ".join("%s (%s)" % (t, s[:12])
                                for _p, t, s in trail["missing"][:3]),
                    "a task.commit that resolves nowhere is a fabricated SHA, or "
                    "one orphaned long enough ago for gc to collect it -- "
                    "`repair-commits.py <manifest>` reports them, and --apply "
                    "clears them with a journal row naming what was lost")
    if trail["unreachable"]:
        rep.finding("commit trail",
                    "%d recorded commit(s) exist but NO ref reaches them: %s"
                    % (len(trail["unreachable"]),
                       _output.some_of(["%s (%s)" % (t, s[:12])
                                        for _p, t, s
                                        in trail["unreachable"]])),
                    "history was rewritten. The objects are still here until git "
                    "gc runs, so RESTORING A BRANCH onto them puts the trail back "
                    "-- do that before `repair-commits.py --apply`, which only "
                    "records the loss")
    if trail["unchecked"]:
        # Not folded into silence: "git could not be asked" and "every commit is
        # present" are different states, and the second is what a reader assumes
        # from nothing at all.
        rep.warn("commit trail",
                 "%d recorded commit(s) could not be verified"
                 % (len(trail["unchecked"]),),
                 "no git on PATH, git would not answer, or this clone is SHALLOW "
                 "and the commit is past where it was cut -- an unasked question, "
                 "not a clean trail. `git fetch --unshallow` turns it into one")
    if not (trail["missing"] or trail["unreachable"] or trail["unchecked"]):
        n = len(_commit_trail.recorded(manifest))
        rep.ok("commit trail",
               "all %d recorded task commit(s) are reachable" % (n,)
               if n else "no task commit recorded yet - nothing to reach")


def check_evidence_pointers(rep, project, manifest):
    """The plan's `testEvidence` pointers against the ledger, both directions.

    ADVISORY, AND THAT IS THE DIVISION OF LABOUR. `evidence-committed` in
    `_invariants` asks the same question of what is COMMITTED and calls a mismatch
    a breach; this asks it of the working tree, where a mismatch is routine and
    repairable - a pointer refused by a live lock is a DESIGNED state, and the
    reconcile that fixes it is one command. So everything here is a warning at
    most, and a doctor that cannot read the ledger says so rather than clearing
    the plan.

    BOTH DIRECTIONS, because they are different problems with different repairs.
    A pointer naming a run no row carries means the plan refers to evidence this
    checkout does not have. A recorded run whose subject's pointer does not name
    it means the opposite: the record is ahead of the plan, which is exactly what
    a refused pointer leaves behind and exactly what `--reconcile` is for.
    """
    pointers = []
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        holders = [(phase, "phase", str(phase.get("id")))]
        holders += [(t, "task", str(t.get("id")))
                    for t in (phase.get("tasks") or []) if isinstance(t, dict)]
        for holder, scope, subject in holders:
            block = holder.get("testEvidence")
            if isinstance(block, dict) and block.get("runId"):
                pointers.append((scope, subject, str(block["runId"])))
    try:
        read = _evidence_io.read_rows(project)
        latest = _evidence_io.latest_by_subject(read["rows"])
    except Exception as exc:
        # NOT an ok line. A reader who could not open the ledger has cleared
        # nothing, and saying so is the whole point of the level.
        rep.warn("evidence", "could not read the evidence ledger, so the plan's "
                             "pointers were not checked: %s" % (exc,))
        return
    if not pointers and not read["rows"]:
        rep.ok("evidence", "no runs recorded and no pointers in the plan")
        return
    known = set(str(r.get("runId")) for r in read["rows"] if r.get("runId"))
    dangling = [(scope, subject, run) for scope, subject, run in pointers
                if run not in known]
    behind = []
    for (scope, subject), row in sorted(latest.items()):
        current = [r for s, sub, r in pointers if s == scope and sub == subject]
        if not current or current[0] != str(row.get("runId")):
            behind.append("%s %s" % (scope, subject))
    if read["unreadable"]:
        rep.warn("evidence", "%d ledger row(s) could not be read and were not "
                             "matched against any pointer"
                             % (read["unreadable"],))
    for scope, subject, run in dangling:
        rep.warn("evidence", "%s %s points at run %s, which no row in this "
                             "checkout's ledger carries - the plan refers to "
                             "evidence that is not here"
                             % (scope, subject, run))
    if behind:
        # NAMED IN FULL, never a count beside a sample. A number over a cut
        # list leaves a reader unable to tell whether they are seeing all of it,
        # which is the shape this repository lints for - and it caught this line.
        # Subject ids are short, and a plan with many of them has a reconcile
        # that is overdue, which is precisely what the reader should see.
        rep.warn("evidence", "the record is ahead of the plan for %s - what a "
                             "refused pointer leaves behind; "
                             "`run-test-gate.py --reconcile` catches it up"
                             % (", ".join(behind),))
    if not dangling and not behind and not read["unreadable"]:
        rep.ok("evidence", "%d pointer(s) in the plan, %d recorded run(s), and "
                           "every pointer names a run this checkout holds"
                           % (len(pointers), len(read["rows"])))


def check_completions(rep, project, cfg, manifest, manifest_rel, git_root,
                      deep=False):
    """Completion records against the manifest (workstream B). Read-only.

    The journal's `task.complete` rows are hook-emitted, one per status flip to
    done — the pipeline's receipt. A done task INSIDE their era with no record
    means the manifest was edited outside the pipeline or a record was removed:
    positive evidence, so a FINDING. A commit SHA git has never heard of is the
    same class. Everything the check cannot know is a WARNING at most, and the
    era is decided by the WATERMARK rule with no config knob: the first
    task.complete row's ts. Zero such rows means an older plugin wrote this
    history, and that is a single ok line, not a nag."""
    if not manifest:
        return
    # The trail check runs FIRST and unconditionally, because it does not depend
    # on the journal at all: `task.commit` is in the manifest, and git either
    # reaches it or does not. It used to sit below the two early returns, so a
    # repo whose journal was fresh or disabled got no SHA verification whatever -
    # and reported `completion records not in use` as an OK line while the
    # manifest named commits no ref could reach. A check that cannot run in a
    # common configuration is not a check.
    _check_commit_trail(rep, manifest, git_root)
    try:
        jr = _journal_io  # layer 1: imported, not loaded (KNOWN_LAYER_DEBT)
        rows = jr.read_all(project)
    except Exception as exc:
        rep.warn("completions", "could not check: %s" % exc)
        return
    completes = [r for r in rows if r.get("action") == "task.complete"]
    if not completes:
        rep.ok("completions",
               "completion records not in use (older plugin wrote this history)")
        return
    watermark = min(str(r.get("ts") or "") for r in completes)
    recorded, row_ts, row_file = set(), {}, {}
    for r in completes:
        det = r.get("details") if isinstance(r.get("details"), dict) else {}
        tid = det.get("taskId")
        if tid:
            recorded.add(tid)
            row_ts.setdefault(tid, str(r.get("ts") or ""))
            if r.get("_file"):
                row_file.setdefault(tid, r["_file"])

    done, pre_era = [], 0
    mio = _load("_manifest_io", "_manifest_io.py")
    # The phase is not read here - only the tasks are joined against the journal -
    # so the pair is unpacked and dropped rather than kept beside a lookup.
    for _, task in mio.iter_tasks(manifest):
        if task.get("status") != "done":
            continue
        completed = task.get("completedAt")
        if not isinstance(completed, str) or completed < watermark:
            pre_era += 1            # older history: out of scope by watermark
            continue
        done.append(task)
    if pre_era:
        rep.ok("completions",
               "%d done task(s) predate the first completion record and are "
               "not checked (older plugin wrote that history)" % pre_era)
    if not done:
        if not pre_era:
            rep.ok("completions", "no done tasks in the completion-record era")
        return

    could_not = []
    missing = [t.get("id") for t in done if t.get("id") not in recorded]
    if missing:
        rep.finding("completions",
                    "%d task(s) marked done with no completion record: %s -- "
                    "the manifest was edited outside the pipeline or a record "
                    "was removed"
                    % (len(missing), _output.some_of(missing)),
                    "run `audit-journal.py show` to see what WAS recorded; to "
                    "repair the trail, reopen the task and re-run it via "
                    "/audit:run")

    # The reachability question belongs to `_commit_trail`, which the repair
    # command asks too. It used to be a `rev-parse --verify` loop right here, and
    # that answered the WRONG QUESTION: verify says "is this object in the store",
    # so a `git reset --hard` that orphaned three task commits left all three
    # green until a `gc` ran, at which point they turned from recoverable into
    # gone with no event in between. Existence is not reachability.
    no_sha = [str(t.get("id")) for t in done if not t.get("commit")]
    trail = {"missing": [], "unreachable": []}
    if no_sha:
        rep.warn("completions",
                 "%d done task(s) carry no commit SHA: %s"
                 % (len(no_sha), _output.some_of(no_sha)),
                 "the orchestrator writes task.commit after each task commit; "
                 "a missing one usually means an interrupted run "
                 "(/audit:resume re-commits)")

    drift = []
    for t in done:
        gap = _hours_between(row_ts.get(t.get("id")), t.get("completedAt"))
        if gap is not None and gap > 24:
            drift.append("%s (%.0fh)" % (t.get("id"), gap))
    if drift:
        rep.warn("completions",
                 "completion record and completedAt disagree by more than 24h: %s"
                 % ", ".join(drift[:3]),
                 "the record and the manifest were not written together -- "
                 "worth a look, not proof of anything")

    unspent = []
    try:
        ul = _load("usage_ledger", "usage_ledger.py")
        usage = cfg.get("usage") or {}
        ledger_dir = ul.find_ledger_dir(os.path.join(project, manifest_rel),
                                        rel=usage.get("ledgerDir"),
                                        project_dir=project)
        lrows = ul.read_ledger(ledger_dir) if ledger_dir else []
        spent = {r.get("taskId") for r in lrows if r.get("taskId")}
        unspent = [str(t.get("id")) for t in done if t.get("id") not in spent]
    except Exception as exc:
        could_not.append("ledger coverage (%s)" % exc)
    if unspent:
        rep.warn("completions",
                 "%d completion-era done task(s) have no usage-ledger rows: %s"
                 % (len(unspent), _output.some_of(unspent)),
                 "the ledger is re-derivable from Claude Code's own read-only "
                 "transcripts: /audit:usage --backfill")

    # Initialised HERE rather than inside the `if deep:` block, and that placement
    # IS the fix for F33: the all-clear at the bottom of this function reads every
    # arm's result, and a name bound only inside the deep branch could not be read
    # there at all. So a --deep run printed "the task commit does not carry the
    # journal file" and "N done task(s) ... all carry chained records" side by side
    # - the check contradicting itself in two adjacent lines. A shallow run leaves
    # it empty, which is the right answer: the arm did not look.
    unstaged = []
    if deep and git_root and shutil.which("git"):
        try:
            # realpath BOTH sides: on macOS the project arrives as /var/... while
            # git resolves its toplevel to /private/var/..., and a relpath across
            # that symlink is a pathspec outside the repository.
            jdir = os.path.realpath(jr.journal_dir(project))
            groot = os.path.realpath(git_root)
            # A git PATHSPEC, which is POSIX-spelled on every platform: a
            # backslash one matches nothing, `ls-tree` then prints nothing
            # with a zero exit, and the absent-file branch below reports
            # every task as uncommitted.
            jrel = _output.posix_rel(jdir, groot)
            if jrel.startswith(".."):
                raise ValueError("journal dir %s is outside the git root" % jdir)
            for t in done:
                sha = t.get("commit")
                fname = row_file.get(t.get("id"))
                if not sha or not fname:
                    continue
                out = subprocess.run(["git", "-C", groot, "ls-tree", "-r",
                                      "--name-only", str(sha), "--", jrel],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, timeout=15)
                if (out.returncode == 0 and fname not in
                        out.stdout.decode("utf-8", "replace")):
                    unstaged.append("%s (%s)" % (t.get("id"), fname))
            if unstaged:
                rep.warn("completions",
                         "--deep: the task commit does not carry the journal "
                         "file that records it: %s" % ", ".join(unstaged[:3]),
                         "the orchestrator stages the journal dir with every "
                         "task commit; an absent file weakens the git "
                         "cross-anchor")
        except Exception as exc:
            could_not.append("deep journal-in-commit (%s)" % exc)

    if could_not:
        rep.warn("completions",
                 "could not check: %s" % "; ".join(sorted(set(could_not))[:3]))
    if not (missing or trail["missing"] or trail["unreachable"] or no_sha
            or drift or unspent or unstaged
            or could_not):
        rep.ok("completions",
               "%d done task(s) in the completion-record era all carry chained "
               "records" % len(done))


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_doctor_completions.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__doctor_completions.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
