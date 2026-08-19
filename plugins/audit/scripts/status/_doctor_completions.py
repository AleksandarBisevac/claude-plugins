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
import _journal_io  # noqa: E402  (read/verify the audit trail, at layer 1)

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
                    % (len(missing), ", ".join(str(x) for x in missing[:3])),
                    "run `audit-journal.py show` to see what WAS recorded; to "
                    "repair the trail, reopen the task and re-run it via "
                    "/audit:run")

    bad_sha, no_sha = [], []
    for t in done:
        sha = t.get("commit")
        if not sha:
            no_sha.append(str(t.get("id")))
            continue
        if not (git_root and shutil.which("git")):
            could_not.append("commit SHAs (no git)")
            break
        try:
            out = subprocess.run(["git", "-C", git_root, "rev-parse", "-q",
                                  "--verify", "%s^{commit}" % sha],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=15)
            if out.returncode != 0:
                bad_sha.append("%s (%s)" % (t.get("id"), str(sha)[:12]))
        except Exception:
            could_not.append("commit %s" % str(sha)[:12])
    if bad_sha:
        rep.finding("completions",
                    "the manifest names a commit git does not have: %s"
                    % ", ".join(bad_sha[:3]),
                    "a task.commit that resolves nowhere is a fabricated or "
                    "rewritten SHA -- check `git log` against the journal's "
                    "task.commit rows")
    if no_sha:
        rep.warn("completions",
                 "%d done task(s) carry no commit SHA: %s"
                 % (len(no_sha), ", ".join(no_sha[:3])),
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
                 % (len(unspent), ", ".join(unspent[:3])),
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
            jrel = os.path.relpath(jdir, groot)
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
    if not (missing or bad_sha or no_sha or drift or unspent or unstaged
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
