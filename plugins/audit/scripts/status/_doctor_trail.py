#!/usr/bin/env python3
"""
Has anything actually run here, and does what it wrote still hold together?

Split out of `audit-doctor.py`'s 646-line `hooks, ledger & trail` section. One
question asked several ways, and every way of asking it is a file this machinery
left behind: hook state files are the only local evidence a guard ever fired,
ledger files the only local evidence metering ever wrote, the journal chain the
only local evidence a completion was ever recorded. Each is silent-by-default
when the machinery has simply never run, and each says WHICH of "never started"
and "stopped" it is looking at, because those are different diagnoses and only
one of them is a problem.

`check_running_plugin` asks the same question of the plugin itself -- WHICH COPY
ran the hooks, which is not the copy this command is running from whenever a
session began before an upgrade (F228). It belongs here rather than beside
`check_interpreter` for the reason above: the answer is not something this
process can look up, it is something a hook left on disk.

`check_journal` delegates to the journal's own `verify` rather than re-deriving
the verdict - the rule `check_locks` follows too, and for the same reason: a
diagnostic with its own opinion about whether a chain is intact is a second
implementation that can disagree with the one that matters.

Layer 4, and the ledger is what sets the floor: `check_ledger` runtime-loads
`usage_ledger` (layer 3), so this cannot sit below 4. `_journal_io` (layer 1) is
imported rather than loaded - the trail's library half came out from under
`audit-journal.py` for exactly that reason.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__doctor_trail.py` - see
`plugins/audit/tests/_harness.py`.
"""
import json
import os
import pathlib
import shutil
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

# Thin module-level aliases, not copies: the bodies below were moved out of
# `audit-doctor.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
_load = _base._load
_HOOKS = _base._HOOKS
RECENT_DAYS = _base.RECENT_DAYS


# --- checks: hook state & the usage ledger --------------------------------------
def check_hooks_fired(rep, project, cfg, cfg_mod):
    """Have the hooks ever actually run here?

    The most common silent failure is not a broken hook but an uninstalled or
    disabled plugin, which looks identical to a healthy one from inside the repo.
    A recently-written state file is the only local evidence a hook ran."""
    # state_dir joins with `/`, so it wants a Path rather than a str.
    state_dir = cfg_mod.state_dir(pathlib.Path(project), cfg)
    try:
        entries = [os.path.join(state_dir, f) for f in os.listdir(state_dir)]
        files = [f for f in entries if os.path.isfile(f)]
    except Exception:
        files = []
    if not files:
        rep.warn("hooks",
                 "no hook state under %s, so nothing here proves a guard has ever run"
                 % state_dir,
                 "check the plugin is installed AND enabled for this project "
                 "(/plugin -> Installed), then make one edit and re-run")
        return
    newest = max(os.path.getmtime(f) for f in files)
    age_days = (time.time() - newest) / 86400.0
    if age_days > RECENT_DAYS:
        rep.warn("hooks",
                 "newest hook state in %s is %.0f days old" % (state_dir, age_days),
                 "harmless if you have not worked here recently; otherwise verify "
                 "the plugin is still enabled")
    else:
        rep.ok("hooks", "%d state file(s) in %s, newest %.1f day(s) old"
               % (len(files), state_dir, age_days))


def check_ledger(rep, project, cfg, manifest_rel):
    """Is metering writing? find_ledger_dir returning None IS the signal."""
    usage = cfg.get("usage") or {}
    if usage.get("enabled") is False:
        rep.ok("usage ledger", "metering disabled in config (usage.enabled false)")
        return
    ul = _load("usage_ledger", "usage_ledger.py")
    try:
        ledger_dir = ul.find_ledger_dir(os.path.join(project, manifest_rel),
                                        rel=usage.get("ledgerDir"),
                                        project_dir=project)
    except Exception as exc:
        rep.warn("usage ledger", "could not locate a ledger: %s" % exc)
        return
    if not ledger_dir:
        rep.warn("usage ledger",
                 "no ledger directory found, so no spend has been recorded",
                 "metering starts once the hooks have run a turn; "
                 "/audit:usage --backfill reads transcripts already on disk")
        return
    # With a project dir in hand, find_ledger_dir answers where the ledger
    # WOULD live whether or not it exists yet (deliberate contract - see its
    # docstring). Missing and empty are different diagnoses: "exists but holds
    # no rows" about a directory nothing ever created is a false statement.
    if not os.path.isdir(ledger_dir):
        rep.warn("usage ledger",
                 "no ledger yet - it would live at %s; metering writes it on "
                 "the first metered turn" % ledger_dir,
                 "/audit:usage --backfill reads transcripts already on disk")
        return
    try:
        files = ul.ledger_files(ledger_dir)
    except Exception:
        files = []
    if not files:
        rep.warn("usage ledger", "%s exists but holds no rows yet" % ledger_dir,
                 "run /audit:usage --backfill to populate it from existing transcripts")
        return
    rep.ok("usage ledger", "%d ledger file(s) in %s" % (len(files), ledger_dir))



# --- checks: which copy of the plugin ran them (F228) ---------------------------
# WHAT EACH SIDE CAN HONESTLY KNOW, established before anything was designed
# around it. This command knows the copy it is ITSELF running from, off
# `_output`'s anchor. It does NOT know the hooks' root: a hook is a different
# process, and the harness substitutes `${CLAUDE_PLUGIN_ROOT}` into hooks.json's
# command strings rather than exporting it, so the variable is absent from this
# process's environment and there is nothing here to read. Disk is the whole
# channel, and there are two things on it.
#
#   * A STAMP, written by detect-plan-skip on every prompt (`_config.
#     stamp_running_plugin`). It names a root and a version, so it can establish
#     agreement -- the only one of the two that can.
#   * The SHAPE of what the guards wrote. `guard-bash-writes` saves a fixed key
#     set; a slot missing a key the copy running THIS command writes was written
#     by a copy that did not have it. That is the evidence a stale cached copy
#     was identified by in the incident this check exists for, and it is the only
#     arm that works against a copy too old to have ever stamped anything.
#     It can refute agreement and never confirm it.
#
# So a shape that matches is not an answer, and neither is an empty state
# directory. Both land in the third outcome, which says so.
def bash_state_shape(mod):
    """What the copy running THIS command writes into a guard-bash-writes slot.

    `mod` is that copy's `guard-bash-writes`, and every field is read off it
    rather than restated here: the key set from its own `default_state()`, the
    two file-name prefixes from its own templates. A literal here would be a
    second statement of that file's shape and would drift the first time a key
    was added over there -- which is the very drift this check reads."""
    return {"keys": sorted(mod.default_state().keys()),
            "prefix": mod.STATE_FILE.split("%s")[0],
            "sidecar": mod.PLUGIN_SIDECAR.split("%s")[0]}


def state_shape_drift(state_dir, shape):
    """Guard state files in `state_dir` a DIFFERENT copy of the plugin wrote.

    `[{"file", "missing", "extra"}]`, one entry per slot whose top-level keys are
    not the ones `shape` names -- `missing` for keys the copy running this
    command writes and the file does not have (an older writer), `extra` for keys
    the file has and this copy does not know (a different, newer one). [] means
    every slot read matched, which is NOT the same as "the same copy wrote them":
    a copy from a release that changed no key is indistinguishable here, and the
    caller grades an empty list accordingly.

    Sidecars are skipped by name. They share the session slots' prefix and hold a
    single unrelated key, so counting one would report drift on every project
    that has ever journalled a write."""
    out = []
    try:
        entries = sorted(os.listdir(str(state_dir)))
    except Exception:
        return out
    expected = set(shape["keys"])
    for name in entries:
        if name.startswith(shape["sidecar"]) or not name.startswith(shape["prefix"]):
            continue
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(str(state_dir), name), "r",
                      encoding="utf-8") as fh:
                obj = json.load(fh)
        except Exception:
            # A torn slot says nothing about which copy wrote it, and the guard
            # that owns the file already treats an unreadable one as absent.
            continue
        if not isinstance(obj, dict):
            continue
        got = set(obj.keys())
        if got == expected:
            continue
        out.append({"file": name, "missing": sorted(expected - got),
                    "extra": sorted(got - expected)})
    return out


def _same_copy(a, b):
    """True when two records name one installation - root AND version.

    Both, because either alone reads a real case wrong: an in-place upgrade
    replaces the version under one root, and two roots can legitimately hold the
    same version (a checkout beside an installed copy). An empty root is never
    equal to anything -- it is a stamp that named no root, not a match."""
    root_a = (a or {}).get("root") or ""
    root_b = (b or {}).get("root") or ""
    if not root_a or not root_b:
        return False
    return (os.path.realpath(root_a) == os.path.realpath(root_b)
            and ((a or {}).get("version") or "") == ((b or {}).get("version") or ""))


def running_plugin_verdict(here, stamps, drift, unreadable=None):
    """Which copy is executing the hooks, and WHAT MAKES THAT SAYABLE.

    `{"verdict", "basis", "others", "drift"}` where verdict is one of:

      "differ"        - a stamp names a copy that is not `here`, or a state file's
                        shape proves one did. `basis` names which of the two said
                        so; both can.
      "match"         - at least one copy stamped itself, every stamp names
                        `here`, and every stamp could be read. A positive claim
                        with a positive basis.
      "unestablished" - nothing stamped and nothing drifted, or a stamp was there
                        and could not be read. THIS IS NOT "match": an empty state
                        directory, a shape that happens to agree and a torn stamp
                        are all silence about the same question, and a check that
                        cleared nothing must not read as clean.

    A TORN STAMP BLOCKS AGREEMENT AND NOT REFUTATION, which is the asymmetry that
    makes the third outcome mean something. It is a session whose copy this
    command could not name, so "every stamp names `here`" has stopped being true
    of everything on disk -- while a copy already refuted by another stamp or by a
    file's shape stays refuted whatever the unreadable one said.

    Drift outranks a matching stamp rather than being hidden by it, for the same
    reason. Sessions in one checkout can run different copies -- that is the
    situation this whole check is about -- so one session stamping agreement says
    nothing about the one beside it that never stamped at all."""
    others = [st for st in stamps if not _same_copy(st, here)]
    basis = (["stamp"] if others else []) + (["state shape"] if drift else [])
    if basis:
        return {"verdict": "differ", "basis": basis, "others": others,
                "drift": drift}
    if stamps and not (unreadable or []):
        return {"verdict": "match", "basis": ["stamp"], "others": [],
                "drift": []}
    return {"verdict": "unestablished", "basis": [], "others": [], "drift": []}


def _copy_name(copy):
    """A copy as a reader can act on it: the version when it has one, the root
    always. A copy whose stamp carried no version is NAMED as unversioned rather
    than printed as `plugin ` with a hole where the number goes."""
    version = (copy or {}).get("version") or ""
    root = (copy or {}).get("root") or "an unrecorded path"
    return ("plugin %s (%s)" % (version, root) if version
            else "a copy that records no version (%s)" % (root,))


def _distinct(copies):
    """`copies` with duplicates folded, order kept. Several sessions running one
    installation are one fact about one copy, not one fact per session."""
    seen, out = [], []
    for c in copies:
        key = (os.path.realpath(c.get("root") or "."), c.get("version") or "")
        if key in seen:
            continue
        seen.append(key)
        out.append(c)
    return out


def _drift_phrase(drift):
    """One state file's shape as a sentence about the copy that wrote it.

    Both directions are said, because they are different diagnoses: a slot
    missing a key was written by a copy that predates it, and a slot carrying one
    this copy does not know was written by a copy that postdates it. Neither is
    reported as the other."""
    said = []
    if drift["missing"]:
        said.append("without %s, which this copy writes on every save"
                    % ", ".join(drift["missing"]))
    if drift["extra"]:
        said.append("carrying %s, which this copy never writes"
                    % ", ".join(drift["extra"]))
    return "%s was written %s" % (drift["file"], " and ".join(said))


_STALE_FIX = ("start a new Claude Code session to pick the installed copy up - "
              "CLAUDE_PLUGIN_ROOT is fixed when a session starts and a running "
              "session cannot be made to reload it")


def check_running_plugin(rep, project, cfg, cfg_mod):
    """Is the plugin protecting this repo the one this command is describing?

    ADVISORY, ALWAYS. Every outcome here is OK or WARNING and never a FINDING:
    a session running an older copy is a thing to tell somebody, and turning
    this diagnostic into something that exits non-zero would make a routine
    consequence of how the harness loads plugins fail a CI run.

    The row names both sides in every branch, including the one that establishes
    nothing -- the copy this command is running from is the half that is always
    knowable, and a reader who is told only that the other half is unknown has
    been told nothing they can act on."""
    state_dir = cfg_mod.state_dir(pathlib.Path(project), cfg)
    here = {"root": _output.PLUGIN_ROOT, "version": _output.plugin_version()}
    read = cfg_mod.running_plugin_stamps(state_dir)
    try:
        shape = bash_state_shape(_load("guard_bash_writes",
                                       "guard-bash-writes.py", _HOOKS))
        drift = state_shape_drift(state_dir, shape)
    except Exception as exc:
        # The shape arm needs this copy's own guard to say what a slot looks
        # like. Losing it costs the arm that can refute agreement, so it is
        # said out loud rather than folded into a quieter verdict below.
        rep.warn("running plugin",
                 "could not read this copy's own state-file shape (%s), so the "
                 "hooks could only be compared by stamp" % (exc,))
        drift = []
    torn = read["unreadable"]
    state = running_plugin_verdict(here, read["stamps"], drift, torn)
    torn_clause = ("; %d stamp(s) here could not be read (%s)"
                   % (len(torn), _output.some_of(torn)) if torn else "")

    if state["verdict"] == "differ":
        parts = ["the hooks in this project ran from %s" % _copy_name(c)
                 for c in _distinct(state["others"])]
        parts.extend(_drift_phrase(d) for d in state["drift"])
        rep.warn("running plugin",
                 "%s, while this command is running %s (basis: %s)%s"
                 % ("; ".join(parts), _copy_name(here), ", ".join(state["basis"]),
                    torn_clause),
                 _STALE_FIX)
        return
    if state["verdict"] == "match":
        rep.ok("running plugin",
               "%d session stamp(s) in %s, every one naming %s - the copy this "
               "command is running from"
               % (len(read["stamps"]), state_dir, _copy_name(here)))
        return
    if torn:
        seen = ("%d stamp(s) here could not be read (%s)"
                % (len(torn), _output.some_of(torn)))
        if read["stamps"]:
            seen += ", and the %d that could all name it" % (len(read["stamps"]),)
        fix = ("session stamps are local scratch - delete the unreadable one(s) "
               "under %s and the next prompt in each live session rewrites its "
               "own" % (state_dir,))
    else:
        seen = "nothing here names the plugin copy that ran the hooks"
        fix = ("a session running a copy that stamps itself writes %s in %s on "
               "its next prompt; until one has, this row clears nothing"
               % (cfg_mod.RUNNING_STAMP_PREFIX + "<session>.json", state_dir))
    rep.warn("running plugin",
             "%s, so whether it is %s - the copy this command is running from - "
             "is NOT ESTABLISHED, which is not the same as agreeing"
             % (seen, _copy_name(here)), fix)


# --- checks: the audit trail ----------------------------------------------------
def _journal_never_committed(jr, directory):
    """(count, oldest_age_days, oldest_name) for journal files that have sat
    UNTRACKED for more than 7 days, or None when there is nothing to say.

    Rides audit-journal's own porcelain seam (`_git_status_sets`) -- one
    subprocess for the whole directory, the same batched read verify() uses
    (F-B3). Age by MTIME, not by the filename's month: a file opened on the
    30th is a day old on the 1st, and punishing it for its name teaches people
    the warning is noise. The 7-day line is the one the state GC already draws
    (_GC_MAX_AGE) -- older than any session state is allowed to live. Never
    raises; None on every inability to answer (no git, not a repository, no
    untracked files), because an unanswerable question is not a warning.

    Archive files count too: journal_files walks journal/archive/ (one level)
    and the porcelain's -uall expands untracked directories into files, so an
    untracked file is the same unanchored work wherever it sits. DECISION
    (pinned, v0.37 D): a file `git mv`ed into archive/ with the move staged
    but not yet committed says NOTHING here -- porcelain reports a staged
    rename as "R " (dirty), never "??" (untracked), and that classification is
    correct: the file's history IS committed, at its pre-move path, which the
    verify anchor still checks. The archive subcommand's own output already
    tells the user to commit the move; a second nag with a false name
    ("never committed" about a committed file) would teach people to ignore
    the true one.

    Keyed by JOURNAL-RELATIVE PATH, not basename (F-D-1): with archive/ the
    same basename can sit live (untracked) AND archived (tracked+committed),
    and a basename lookup let the committed twin inflate the count and
    mis-name the oldest. The path key counts exactly the untracked files,
    and `oldest` carries the journal-relative path so a live and an archived
    month can never read as one another."""
    try:
        if not directory or not os.path.isdir(directory):
            return None
        sets = jr._git_status_sets(directory)
        if not sets or not sets[1]:
            return None
        now = time.time()
        old = []
        for f in jr.journal_files(directory):
            rel = _output.posix_rel(f, directory)
            if rel not in sets[1]:
                continue
            try:
                age = now - os.stat(f).st_mtime
            except Exception:
                continue
            if age > 7 * 86400:
                old.append((age, rel))
        if not old:
            return None
        old.sort(reverse=True)
        return len(old), int(old[0][0] // 86400), old[0][1]
    except Exception:
        return None


def check_journal(rep, project, cfg, cfg_mod, git_root):
    """Does the audit trail still hold together? (v0.29)

    Delegates to `audit-journal.verify` rather than re-deriving the verdict — the
    same rule `check_locks` follows below, and for the same reason: a diagnostic
    with its own opinion about whether a chain is intact is a second implementation
    that can disagree with the one that matters.

    The grading is the honest one. A BROKEN chain is a FINDING: a row was edited,
    deleted or reordered, and that is not something that happens by accident.
    Everything else is a WARNING at most — a torn tail is a crash, and out-of-band
    drift means a document moved without an edit tool touching it, which is normal
    for a git checkout and only suspicious in context. An empty journal is neither:
    it is what every repo looks like before its first recorded write."""
    if not cfg_mod.journal_enabled(cfg):
        # Disabled is the user's own switch and never a finding. But rows on
        # disk mean the trail WAS running: saying plain OK graded "someone
        # turned it off mid-history" identically to "never used", and the
        # completion records quietly stopped being written. The chain itself is
        # deliberately not verified here -- a broken chain in a disabled
        # journal is not this run's business.
        has_rows = False
        try:
            jr = _journal_io  # layer 1: imported, not loaded (KNOWN_LAYER_DEBT)
            res = jr.verify(project)
            has_rows = bool(res.get("exists") and res.get("rows"))
        except Exception:
            has_rows = False
        if has_rows:
            rep.warn("journal",
                     "audit trail was running and has been turned off -- "
                     "completion records are no longer being written",
                     "set journal.enabled true to resume the trail; the "
                     "recorded history stays where it is")
        else:
            rep.ok("journal",
                   "audit trail disabled in config (journal.enabled false)")
        return
    try:
        jr = _journal_io  # layer 1: imported, not loaded (KNOWN_LAYER_DEBT)
        res = jr.verify(project)
    except Exception as exc:
        rep.warn("journal", "could not read the journal: %s" % exc,
                 "run `audit-journal.py verify` by hand to see why")
        return
    where = _output.posix_rel(res.get("dir") or project, project)
    if not res.get("exists"):
        rep.ok("journal", "no writes recorded yet (%s does not exist)" % where)
        return
    # D4 / F-F1: the git anchor only pins committed history. An uncommitted
    # journal file younger than 7 days is the normal write-then-commit rhythm;
    # one older than that has been outliving every session state file while
    # the anchor protects none of it -- usually a gitignored or forgotten
    # directory. A WARNING, never a FINDING: a finding is positive evidence of
    # forgery, and an absent commit is evidence of nothing but absence.
    if git_root and shutil.which("git"):
        stale = _journal_never_committed(jr, res.get("dir"))
        if stale:
            n, days, oldest = stale
            rep.warn("journal",
                     "%d journal file(s) have never been committed (oldest "
                     "%s, %d day(s) old): the git anchor only pins committed "
                     "history" % (n, oldest, days),
                     "stage and commit the journal directory - it is designed "
                     "to be tracked; do not add it to .gitignore")
    if res.get("findings"):
        rep.finding("journal",
                    "the chain does not hold: %s" % "; ".join(res["findings"][:3]),
                    "run `audit-journal.py verify` for the full list; the journal "
                    "is append-only and a broken chain means a row was edited, "
                    "deleted or reordered")
        return
    if res.get("warnings"):
        rep.warn("journal",
                 "%d row(s) in %s chain cleanly, with %d warning(s): %s"
                 % (res.get("rows", 0), where, len(res["warnings"]),
                    _output.some_of(res["warnings"], sep="; ")),
                 "out-of-band drift is a document that changed with no row to "
                 "explain it - a git checkout, a script, or a shell write")
        return
    rep.ok("journal", "%d row(s) in %d file(s) under %s, chain intact"
           % (res.get("rows", 0), len(res.get("files") or []), where))


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
        print("_doctor_trail.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__doctor_trail.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
