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
session began before an upgrade. It belongs here rather than beside
`check_interpreter` for the reason above: the answer is not something this
process can look up, it is something a hook left on disk.

`check_journal` delegates to the journal's own `verify` rather than re-deriving
the verdict - the rule `check_locks` follows too, and for the same reason: a
diagnostic with its own opinion about whether a chain is intact is a second
implementation that can disagree with the one that matters.

AND WHAT KEEPS HAPPENING, NOT ONLY WHAT IS TRUE NOW. Every check above answers a
question about a single moment; `check_task_restarts` and `check_gate_patterns`
fold the WHOLE trail into a claim about a repeated fact instead - a task started
more times than any other, a gate that has run repeatedly and never once failed.
Both carry the same discipline: a trail too short to support the claim says so,
graded a WARNING and never a FINDING, because a fresh install that has asked for
nothing must not fail a build for having no history yet - and one occurrence is
never printed as a pattern.

Layer 4, and the ledger is what sets the floor: `check_ledger` runtime-loads
`usage_ledger` (layer 3), so this cannot sit below 4. `_journal_io` (layer 1) and
`_evidence_io` (layer 2) are imported rather than loaded - the trail's library
half came out from under `audit-journal.py` for exactly that reason, and the
gate-pattern check reads the same evidence tally `propose-gates.py` folds into a
plan proposal rather than re-deriving it a second time.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__doctor_trail.py` - see
`plugins/audit/tests/_harness.py`.
"""
import calendar
import json
import os
import pathlib
import posixpath
import shlex
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
import _evidence_io  # noqa: E402  (the ledger tally, at layer 2)
import _fmt  # noqa: E402  (human_duration, at layer 1)
import _manifest_io  # noqa: E402  (signoff_recorded, declared_gate_entries, layer 1)
import _manifest_vocab  # noqa: E402  (the FULL_STATUS words, one vocabulary)
import _usage_core  # noqa: E402  (parse_ts, the ledger's own ISO reading, layer 1)
import _worktrees  # noqa: E402  (_git, the one git runner at layer 1)

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



# --- checks: which copy of the plugin ran them ----------------------------------
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


def running_plugin_verdict(here, stamps, drift, unreadable=None, now=None):
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
    live, history = split_history(stamps, here, now)
    others = [st for st in live if not _same_copy(st, here)]
    basis = (["stamp"] if others else []) + (["state shape"] if drift else [])
    if basis:
        return {"verdict": "differ", "basis": basis, "others": others,
                "drift": drift, "history": history}
    if live and not (unreadable or []):
        return {"verdict": "match", "basis": ["stamp"], "others": [],
                "drift": [], "history": history}
    return {"verdict": "unestablished", "basis": [], "others": [], "drift": [],
            "history": history}


def _copy_key(stamp):
    """One installation, as `_same_copy` reads it. A stamp naming no root is its
    own copy, because it names nothing another stamp could be the same as."""
    root = stamp.get("root") or ""
    if not root:
        return ("", stamp.get("version") or "", stamp.get("session") or "")
    return (os.path.realpath(root), stamp.get("version") or "")


# How long a session may go without a guarded tool call and still be counted as
# running. A stamp's mtime is refreshed by `guard-secrets-read` on Read, Grep,
# Bash and MCP calls, at most once a `RUNNING_STAMP_REFRESH_SECONDS` apart
# (`hooks/_config.py`), and one Bash call may run for the host's ten-minute
# limit with no hook firing; the bound is more than twice that sum, so a busy
# session is never filed as history between two refreshes.
IDLE_BOUND_SECONDS = 30 * 60


def split_history(stamps, here, now=None):
    """`(live, history)` - every stamp, split on each copy's OWN age.

    A stamp's mtime is the last prompt or guarded tool call of the session that
    wrote it. A copy other than `here` whose newest stamp is older than
    `IDLE_BOUND_SECONDS` has made no guarded tool call for longer than a live
    session goes between two: its stamps are HISTORY, named and aged. Every
    other stamp is LIVE. Measured from `now`, never from another stamp: the
    session asking for this row has always just prompted, and grading the rest
    against it would call every session mid-turn on another copy history - the
    stale copy this row exists to find. Stamps naming `here` are never history;
    an old one is no evidence of drift."""
    clock = time.time() if now is None else now
    newest = {}
    for st in stamps:
        key = _copy_key(st)
        if key not in newest or st.get("mtime", 0) > newest[key]:
            newest[key] = st.get("mtime", 0)

    def idle(st):
        return (not _same_copy(st, here)
                and clock - newest[_copy_key(st)] > IDLE_BOUND_SECONDS)
    return ([st for st in stamps if not idle(st)],
            [st for st in stamps if idle(st)])


def _age(seconds):
    """A stamp's age as a reader says it, in the largest whole unit."""
    seconds = max(0, int(seconds))
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = seconds // size
            return "%d %s%s" % (n, unit, "" if n == 1 else "s")
    return "%d second%s" % (seconds, "" if seconds == 1 else "s")


def _stamp_file(state_dir, cfg_mod, stamp):
    return os.path.join(str(state_dir),
                        cfg_mod.RUNNING_STAMP % (stamp.get("session") or ""))


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


def check_running_plugin(rep, project, cfg, cfg_mod, now=None):
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
    clock = time.time() if now is None else now
    state = running_plugin_verdict(here, read["stamps"], drift, torn, now=clock)
    torn_clause = ("; %d stamp(s) here could not be read (%s)"
                   % (len(torn), _output.some_of(torn)) if torn else "")

    def aged(stamp):
        return "%s old" % (_age(clock - stamp.get("mtime", clock)),)

    history = state["history"]
    history_clause = ""
    if history:
        history_clause = (
            "; history, no guarded tool call within the %d-minute bound - "
            "ended, or idle waiting on its user: %s - prune by "
            "deleting %s (session stamps are local scratch, and a session still "
            "running that copy re-stamps on its next prompt or tool call)"
            % (IDLE_BOUND_SECONDS // 60,
               _output.some_of(["%s naming %s, %s" % (
                cfg_mod.RUNNING_STAMP % h.get("session"), _copy_name(h), aged(h))
                for h in history]),
               _output.some_of([_stamp_file(state_dir, cfg_mod, h)
                                for h in history])))

    if state["verdict"] == "differ":
        parts = ["the hooks in this project ran from %s (last active %s ago, "
                 "inside the %d-minute idle bound - may still be running)"
                 % (_copy_name(c), _age(clock - c.get("mtime", clock)),
                    IDLE_BOUND_SECONDS // 60)
                 for c in _distinct(sorted(state["others"],
                                           key=lambda st: -st.get("mtime", 0)))]
        parts.extend(_drift_phrase(d) for d in state["drift"])
        rep.warn("running plugin",
                 "%s, while this command is running %s (basis: %s)%s%s"
                 % ("; ".join(parts), _copy_name(here), ", ".join(state["basis"]),
                    torn_clause, history_clause),
                 _STALE_FIX)
        return
    if state["verdict"] == "match":
        live = [st for st in read["stamps"] if st not in history
                and _same_copy(st, here)]
        rep.ok("running plugin",
               "%d live session stamp(s) in %s, every one naming %s - the copy "
               "this command is running from - the newest %s%s"
               % (len(live), state_dir, _copy_name(here),
                  aged((live or read["stamps"])[0]), history_clause))
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
    subprocess for the whole directory, the same batched read verify() uses.
    Age by MTIME, not by the filename's month: a file opened on the
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

    Keyed by JOURNAL-RELATIVE PATH, not basename: with archive/ the
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


# The `verify` warning classes that need DIFFERENT repair text, each keyed on a
# distinctive fragment of the sentence `_journal_io` writes for it.
#
# MATCHING ON TEXT IS THE DELIBERATE CHOICE. The alternative is to ask
# `anchor_verdict` again from here, which is a second opinion about whether a
# chain is intact — the one thing this module refuses to have. The cost is a
# coupling to another module's wording, and what pays for it is that the cases
# build a REAL re-linked file, a REAL re-spelled one, a REAL torn tail and a
# REAL out-of-band edit and read the class back out: a reworded warning goes red
# in `test__doctor_trail.py` rather than silently losing its advice and falling
# back to the wrong cause.
#
# EVERY FRAGMENT IS UNIQUE TO ONE BRANCH OF THE SENTENCE IT CLASSIFIES, and that
# is a correctness requirement rather than tidiness. `_anchor_warning` does not
# write one sentence:
# rows arrived after a committed one, or the bytes were re-spelled with no row
# moving at all — and both open with "no longer byte-identical to its committed
# copy", which is what `relink` used to key on. A re-spelled file therefore drew
# advice telling its operator to go and read the extra rows, about a file that
# has none: the same defect exactly, one level up. So no class may key on the
# shared opening; each keys on the half that says what happened. A rewording
# that removes every fragment of a class drops the warning to the unrecognised
# pointer below, which is the safe direction to fail in — a pointer says nothing
# false, and the cases go red either way.
#
# WHAT WOULD REPLACE ALL OF THIS is a `kind` on the warning itself, set where
# the sentence is written and read here instead of its prose. Until
# `_journal_io` carries one, this table is the strongest thing available from
# outside it, and the cases are what hold it.
_JOURNAL_WARNING_CLASSES = (
    ("relink", ("are still here, in order, alongside",
                "Read the rows that arrived"),
     "a RE-LINKED chain is a file whose committed rows all survived while the "
     "bytes after one of them are new. `audit-journal.py merge` does exactly "
     "that to resolve a divergence - and so does splicing a fabricated row in "
     "among rows that are already committed: NOTHING HERE CAN TELL THOSE "
     "APART, and neither a merge commit nor a `journal.merge` row is required "
     "for this warning to be the harmless one. Read the extra rows yourself "
     "(`audit-journal.py show`) and confirm a merge you know about is what put "
     "them there (`git log --merges -- <the journal file>`)"),
    ("respelled", ("and no row diverged", "nothing arrived alongside them"),
     "a RE-SPELLED file is one whose bytes moved while every row stayed where "
     "it was: nothing diverged and nothing arrived, so there are no extra rows "
     "to go and read and `audit-journal.py show` has none to show you. Compare "
     "the bytes instead (`git diff -- <the journal file>`) and find the writer "
     "that does not spell canonical JSON - this plugin writes one canonical "
     "row per line on every path it appends or merges through, so the "
     "re-spelling came from something else"),
    ("drift", ("an edit the journal never saw", "records it as it was"),
     "out-of-band drift is a document that changed with no row to explain it - "
     "a git checkout, a script, or a shell write"),
    ("torn", ("ends with a partial line",),
     "a torn tail is an interrupted writer, not a cover-up - the rows before "
     "it are intact and nothing was hidden by it"),
)

_NO_CLASS_FIX = ("this check has no repair text for that warning; run "
                 "`audit-journal.py verify` for the full list")

# ...AND THE WARNING ITSELF, WHICH IS THE HALF THAT WAS MISSING. The detail line
# beside this fix spends a fixed budget on the warning list and elides the tail
# (`_output.some_of`), so a warning with no repair text here that is also elided
# there reached the operator NOWHERE: a pointer saying "that warning" names
# nothing they can go and look at. An unrecognised warning is precisely the one
# worth reading - a recognised class is one somebody has already thought about,
# while this one is a sentence `verify` learned to write that nothing here has
# caught up with. The budget is deliberately not widened for it: `some_of` is
# shared, it says how many it left out, and quoting the unclassed warnings beside
# their own pointer is the narrower repair.
_UNRECOGNISED_LEAD = "the warning(s) nothing here recognised"


def journal_warning_advice(warnings):
    """{"kinds", "fix"} — what to say about a `verify` warning list.

    ONE FIX LINE PER CLASS THAT IS PRESENT, and never a line about a class that
    is not. This was a single unconditional sentence about out-of-band drift,
    and the journal-merge verb made that sentence confidently wrong for the
    class it introduced: a row inserted between committed rows is not a git
    checkout and not a shell write, so an operator sent looking for one finds
    nothing and learns that the row is noise.

    A warning whose class is in NONE of the rows above gets a POINTER and no
    cause. The rule this file works under is that a claim carries the basis that
    makes it true — a cause guessed to fill the gap is the same defect as the
    sentence this replaces, only quieter.

    THE POINTER IS PER WARNING, NOT PER LIST. It used to be emitted only
    when NOTHING in the list matched, so an unrecognised warning standing beside
    a recognised one was dropped without a word — and `verify` emits classes
    that have no row here, the same basename living and archived at once among
    them, so that is the ordinary company an unrecognised warning keeps rather
    than a corner.

    AND THE POINTER NOW CARRIES THE WARNING IT IS ABOUT, which is the rest of
    that repair. A pointer saying "that warning" named nothing, while the detail
    line beside it spends a fixed budget on the list and elides the tail — so the
    unrecognised warning was in neither place and the operator was told only that
    something they could not see had no repair text. `_UNRECOGNISED_LEAD` carries
    why that is the warning worth the room.

    EVERY BRANCH HERE IS ONE SOMETHING CAN REACH, which is the other repair. The
    pointer used to be appended on `unclassed or not lines`, and the second
    operand could not decide anything: a non-empty list with no class matched
    leaves every warning unclassed, so the first operand had already fired, and
    the only input the second answers for is the empty list — which
    `check_journal` never passes. One operand standing in for a branch nobody
    could see fire is the shape this file's own cases exist to refuse, so the
    empty list is its own branch and its own case. A caller with nothing to
    explain is still handed a place to look rather than an empty string."""
    kinds, lines, classed = [], [], set()
    for kind, fragments, advice in _JOURNAL_WARNING_CLASSES:
        hits = [i for i, text in enumerate(warnings)
                if any(frag in text for frag in fragments)]
        if not hits:
            continue
        kinds.append(kind)
        lines.append(advice)
        classed.update(hits)
    unclassed = [text for i, text in enumerate(warnings) if i not in classed]
    if unclassed:
        lines.append("%s. %s: %s"
                     % (_NO_CLASS_FIX, _UNRECOGNISED_LEAD,
                        _output.some_of(unclassed, sep="; ")))
    elif not warnings:
        lines.append(_NO_CLASS_FIX)
    return {"kinds": kinds, "fix": "; also: ".join(lines)}


ANCHOR_CHECK = "journal anchor"


def _anchor_row(rep, res):
    """What pinned the chain, as its own row -- or that nothing did.

    ITS OWN QUESTION, AND THEREFORE ITS OWN ROW. `journal` answers whether the
    rows still hold together; this answers what that verdict was checked
    AGAINST, and the two come apart in the state worth reporting: a chain over
    files no committed copy was read for verifies perfectly and establishes
    much less. `verify` has answered this per file since the anchor learnt to
    say it could not ask -- and only `audit-journal.py verify` rendered it, so
    an operator who opened the doctor instead saw exactly what they saw before.
    Fixing a silence on one of two surfaces that read the same fact moves it.

    A WARNING AND NEVER A FINDING. A finding exits this command non-zero, and
    an unestablished basis is not evidence that anything is wrong: a repository
    whose journal simply has not been committed yet would fail a build having
    asked for nothing and found nothing. `check_running_plugin` grades the same
    shape of answer the same way, at length.

    BOTH DIRECTIONS ARE SAID. A row that only ever spoke up when something was
    unanchored would be a check nobody could see pass, and "the anchor held over
    every file" is the sentence that makes the warning mean something when it
    does come.
    """
    files = res.get("files") or []
    if not files:
        return
    unanchored = res.get("unanchored") or []
    if not unanchored:
        rep.ok(ANCHOR_CHECK,
               "%d journal file(s) were compared against their committed copy"
               % (len(files),))
        return
    rep.warn(ANCHOR_CHECK,
             "the git anchor could not be asked about %d of %d journal file(s), "
             "so the chain was verified over files no committed copy pins: %s"
             % (len(unanchored), len(files),
                _output.some_of(["%s (%s)" % (where, why)
                                 for where, why in unanchored], sep="; ")),
             "nothing was found here, because nothing was looked at - this is "
             "not a claim that anything is wrong. The journal is designed to be "
             "tracked and committed, which is what gives the anchor something "
             "to compare; `audit-journal.py verify` prints the reason beside "
             "each file")


def check_journal(rep, project, cfg, cfg_mod, git_root):
    """Does the audit trail still hold together? (v0.29)

    Delegates to `audit-journal.verify` rather than re-deriving the verdict — the
    same rule `check_locks` follows below, and for the same reason: a diagnostic
    with its own opinion about whether a chain is intact is a second implementation
    that can disagree with the one that matters.

    The grading is the honest one. A BROKEN chain is a FINDING: a row was edited,
    deleted or reordered, and that is not something that happens by accident.
    Everything else is a WARNING at most, and those are not one thing: a torn
    tail is a crash; out-of-band drift is a recorded document moving without an
    edit tool touching it, which is normal for a git checkout; and a RE-LINKED
    chain is a file whose committed rows all survived while the bytes after one
    of them are new — which is what `audit-journal.py merge` does, and
    also what splicing a fabricated row in among committed rows does. This check
    cannot tell them apart. A RE-SPELLED file is the quieter neighbour of that
    last one and not the same class: the bytes moved and no row did, so there is
    nothing that arrived to read. `journal_warning_advice` is where each
    class gets repair text that is true OF IT rather than one sentence that was
    true of only one of them, and a warning it does not recognise gets a
    pointer instead of a guessed cause. An empty journal is neither: it is what
    every repo looks like before its first recorded write.

    AND WHAT THE VERDICT WAS CHECKED AGAINST IS A ROW OF ITS OWN, because it is
    a different question with a different answer: `_anchor_row` carries it, and
    until it existed only `audit-journal.py verify` ever said which."""
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
        # A directory that is not there reads as "nothing has been recorded yet"
        # ONLY while git agrees there was nothing. `verify` asks what the index
        # still holds under that path before it gives up on the walk, so a
        # journal removed whole comes back with findings and no directory - and
        # reporting that as a clean never-used project is the same silence the
        # findings were added to break, one layer up.
        if res.get("findings"):
            rep.finding("journal",
                        "%s is not there and git still tracks what was in it: %s"
                        % (where, "; ".join(res["findings"][:3])),
                        "the trail is committed on purpose - restore it with "
                        "`git checkout -- %s` and run `audit-journal.py verify`, "
                        "or read `git log --diff-filter=D -- %s` for what "
                        "removed it" % (where, where))
            return
        rep.ok("journal", "no writes recorded yet (%s does not exist)" % where)
        return
    # D4: the git anchor only pins committed history. An uncommitted
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
    _anchor_row(rep, res)
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
                 journal_warning_advice(res["warnings"])["fix"])
        return
    rep.ok("journal", "%d row(s) in %d file(s) under %s, chain intact"
           % (res.get("rows", 0), len(res.get("files") or []), where))


# --- checks: patterns, not only state -------------------------------------------
# EVERYTHING ABOVE THIS MARKER ANSWERS "IS IT TRUE NOW." A single journal row or
# a single ledger row is a fact about one moment, and folding many of them into
# "this keeps happening" is a different claim that needs its own floor: ONE
# OCCURRENCE IS NOT A PATTERN, so a check below must say a claim could not be
# established rather than rounding a thin trail up into one. That is a WARNING,
# never a FINDING - a fresh install that has asked for nothing must not fail a
# build for having no history yet, the same rule `check_running_plugin` and
# `_anchor_row` already grade by above.
RESTART_FLOOR = 2  # fewer `task.start` rows for one id is a single run, not a restart pattern


def task_start_counts(rows):
    """`{taskId: count}` of `task.start` journal rows, keyed by `details.taskId`.

    `target` is the shard path a start landed in, and several tasks in one
    phase share it - `details.taskId` is the identity this question is about,
    the same reason `_journal_cancel` (audit-task.py) puts a task id in
    `details` instead of leaving a reader to re-derive it from the row's
    target."""
    counts = {}
    for row in (rows or []):
        if row.get("action") != "task.start":
            continue
        tid = (row.get("details") or {}).get("taskId")
        if not tid:
            continue
        counts[tid] = counts.get(tid, 0) + 1
    return counts


def check_task_restarts(rep, project, config=None):
    """Has any task needed to be started more times than the rest?

    A STATE can only say a task IS `in_progress`; this is the question that
    needs the whole trail, because a snapshot cannot count how many times
    something happened. `attempts` on the manifest already carries the same
    number for one task at a time - this is what the JOURNAL can say about
    every task at once, which is what makes it a pattern rather than a fact
    about whichever task a reader happened to open.

    ONE OCCURRENCE IS NOT A PATTERN: a task started exactly once, which is the
    ordinary path for nearly all of them, prints no restart claim at all
    beyond the OK line below the floor. A trail with no `task.start` rows at
    all is NOT ESTABLISHED rather than clean - a manifest that has never
    started a task has not earned an OK about restarts, it has earned a
    warning saying the question cannot be answered yet."""
    try:
        rows = _journal_io.read_all(project, config)
    except Exception as exc:
        rep.warn("task restarts", "could not read the journal: %s" % (exc,))
        return
    counts = task_start_counts(rows)
    if not counts:
        rep.warn("task restarts",
                 "no `task.start` rows recorded yet, so a restart pattern "
                 "cannot be established",
                 "the row is written on every task start; start one and "
                 "re-check")
        return
    repeated = sorted(
        ((tid, n) for tid, n in counts.items() if n >= RESTART_FLOOR),
        key=lambda kv: (-kv[1], kv[0]))
    if not repeated:
        rep.ok("task restarts",
               "%d task(s) have a recorded start; none reaches the floor a "
               "restart pattern needs" % (len(counts),))
        return
    worst_id, worst_n = repeated[0]
    others = ", ".join("%s (%d)" % (tid, n) for tid, n in repeated[1:])
    detail = ("%s has the most recorded starts of any task (%d) - the "
             "pattern this trail can actually support" % (worst_id, worst_n))
    if others:
        detail += "; also past the floor: %s" % (others,)
    rep.warn("task restarts", detail,
             "each start is its own `task.start` row - `audit-journal.py "
             "show` reads them back, or open the task and read `attempts`")


def _read_gate_rows(project, manifest_rel):
    """`(eproject, econfig, rows, failure, unreadable)` off the evidence ledger
    the manifest at `manifest_rel` points to - the ONE read
    `check_gate_patterns`, `check_gate_economy` and `check_shadow_recall`
    all open with, so none of the three can resolve the ledger a different
    way the day `project_config_for` learns a new rule.

    `failure` is the sentence to warn with, or `None` when the read
    succeeded - `eproject`/`econfig`/`rows` are `None` exactly when it is not.
    TWO STEPS, TWO SENTENCES: failing to find where the ledger lives is
    `_manifest_vocab.LEDGER_LOCATION_FAILED`, failing to read it once found is
    `LEDGER_READ_FAILED`. Every surface fills those same templates, and one
    `try` around both steps would word a location failure as a read nobody
    made. `unreadable` is `_evidence_io.read_rows`'s own count of rows or
    files it could not parse, always `0` when `failure` is set (nothing was
    read at all)
    and NEVER folded into an empty `rows`: a caller that only checked
    `rows` for zero would read a torn ledger as a clean one that simply has
    no history yet, which is the exact silence `check_shadow_recall` is
    written to refuse."""
    manifest_path = os.path.join(project, manifest_rel or
                                 "docs/audit/audit-plan.json")
    try:
        eproject, econfig = _evidence_io.project_config_for(
            manifest_path, project_dir=project)
    except Exception as exc:
        return (None, None, None,
                _manifest_vocab.LEDGER_LOCATION_FAILED % (exc,), 0)
    try:
        read = _evidence_io.read_rows(eproject, econfig)
    except Exception as exc:
        return None, None, None, _manifest_vocab.LEDGER_READ_FAILED % (exc,), 0
    return (eproject, econfig, read.get("rows") or [], None,
            read.get("unreadable") or 0)


def _gate_tally_classes(rows, names):
    """Classify every gate `name` in `names` by ONE reading of
    `_evidence_io.gate_tally` - the per-name tally loop `check_gate_patterns`
    and `check_gate_economy` both need, walked once so a second walk can
    never disagree with the first about which names are thin, which never
    failed and which did.

    `{"thin": [name, ...], "never_failed": [(name, ran), ...],
      "failed": [name, ...]}`. "thin" is below `MIN_HISTORY_RUNS` - not
    established either way, in `names` order. "failed" is past the floor
    with at least one recorded failure - never folded into a never-failed
    claim by either caller. "never_failed" is past the floor with zero
    recorded failures, `(name, ran)` in `names` order."""
    thin, never_failed, failed = [], [], []
    for name in names:
        ran, failed_n = _evidence_io.gate_tally(rows, name)
        if ran < _evidence_io.MIN_HISTORY_RUNS:
            thin.append(name)
        elif failed_n == 0:
            never_failed.append((name, ran))
        else:
            failed.append(name)
    return {"thin": thin, "never_failed": never_failed, "failed": failed}


def check_gate_patterns(rep, project, manifest_rel, config=None):
    """Has any gate run enough times to say it has never once failed?

    Reuses `_evidence_io.gate_tally`/`gate_names_seen` - the same tally
    `propose-gates.py` folds into a plan proposal - because "this gate has
    never failed" is one fact whether it is read at proposal time or at
    doctor time, and a second reading of one ledger is free to disagree with
    the first the day a step key changes shape.

    A STATE cannot tell an operator they are paying for a gate that never
    catches anything; only the trail can. ONE OCCURRENCE IS NOT A PATTERN
    here either - a gate that has run fewer times than the floor a verdict
    needs is NOT ESTABLISHED, named as such, and never folded into either the
    clean OK or the never-failed warning."""
    eproject, econfig, rows, failure, _unreadable = _read_gate_rows(
        project, manifest_rel)
    if failure is not None:
        rep.warn("gate patterns", failure)
        return
    names = _evidence_io.gate_names_seen(rows)
    if not names:
        rep.warn("gate patterns",
                 "no evidence rows recorded yet, so a gate's pass/fail "
                 "pattern cannot be established",
                 "run a phase gate to start recording; a pattern needs "
                 "repeated runs past the floor")
        return
    classes = _gate_tally_classes(rows, names)
    thin = classes["thin"]
    if classes["never_failed"]:
        never_failed = ["%s (ran %d)" % (name, ran)
                        for name, ran in classes["never_failed"]]
        rep.warn("gate patterns",
                 "past the floor and never failed once, which is a "
                 "candidate to drop rather than keep paying for: %s"
                 % ("; ".join(never_failed),),
                 "the rows are in the evidence ledger at %s"
                 % (_evidence_io.evidence_dir(eproject, econfig),))
        return
    checked = len(names) - len(thin)
    if thin and checked:
        rep.warn("gate patterns",
                 "%d gate(s) checked past the floor with no never-failed "
                 "pattern; still below the floor: %s"
                 % (checked, ", ".join(thin)),
                 "the pattern becomes checkable once each has run past the "
                 "floor")
        return
    if thin:
        rep.warn("gate patterns",
                 "recorded but below the floor a verdict needs, so no "
                 "never-failed pattern can be established yet: %s"
                 % (", ".join(thin),),
                 "the pattern becomes checkable once each has run past the "
                 "floor")
        return
    rep.ok("gate patterns",
           "%d gate(s) checked past the floor; none goes without a failure"
           % (checked,))


def _gate_economy_remedies(name, phases, phase_gate_always):
    """The commands that stop the NEXT doctor run from finding `name` again.

    One `/audit:phase retarget <id> --gate-drop <name>` per phase not yet
    signed off whose `testGate` still carries it (a signed-off phase's gate
    already ran what it is going to run - retargeting it changes nothing a
    reader can act on), plus the line that stops a phase that does not exist
    yet from getting `name` in the first place: a NEW phase's gate is built
    by `_manifest_phases.phase_gate_default` off `meta.phaseGate.exclude`, so
    retargeting every phase already on the plan is not enough to keep the
    next one from repeating this. `meta.phaseGate.always` OUTRANKS
    `exclude` there (`phase_gate_default`'s own rule: always puts a key back
    IN even when exclude names it), so an entry still listed in `always`
    would keep coming back with the exclude line alone - named as its own
    remedy rather than silently assumed fixed."""
    out = [
        "/audit:phase retarget %s --gate-drop %s" % (phase.get("id"), name)
        for phase in (phases or [])
        if isinstance(phase, dict) and not _manifest_io.signoff_recorded(phase)
        and name in _manifest_io.declared_gate_entries(phase.get("testGate"))
    ]
    out.append("add it to meta.phaseGate.exclude")
    if name in (phase_gate_always or []):
        out.append("take it out of meta.phaseGate.always")
    return out


def check_gate_economy(rep, project, manifest_rel, manifest, config=None):
    """Has any gate that never fails also gotten too expensive to keep
    paying for?

    `check_gate_patterns` names a gate that never catches anything; this
    asks the other question a state can never answer - not "did it ever
    fail" but "what did it cost" - and grades ONLY the entries the pattern
    check would already call a candidate to drop, because a gate that has
    failed at least once earns its keep whatever it costs.

    NO `meta.gateBudgetMs` MEANS NOTHING IS GRADED ON COST, said as an OK
    row rather than silence: the budget is an opt-in declaration
    (`_manifest_phases._check_phase_gate`), and a plan that never declared
    one has not been told its gates are cheap - it has been told nothing.

    MEAN, NEVER TOTAL. `_evidence_io.gate_cost_ms` sums every recorded run;
    dividing by the number of runs that actually contributed a `durationMs`
    (`_evidence_io.gate_cost_measured`) is what makes the number comparable
    to a budget written for one run, and comparing the total instead would
    flag an entry that has simply run MANY times at a perfectly ordinary
    cost each. `gate_tally`'s `ran` is NOT that denominator - it counts
    every matching step whether or not it carries a `durationMs`, so a
    history mixing measured and unmeasured runs would dilute `total / ran`
    downward and could hide a gate that is over budget on the runs actually
    measured.

    UNMEASURED IS NOT CHEAP. A step that never carried a `durationMs` -
    `gate_cost_ms` returning `None` - says nothing about what it costs, and
    folding that silence into the OK count would be the same overclaim
    `gate_cost_ms`'s own docstring refuses: absent means unmeasured, never
    zero. Named on its own line instead.

    A REMEDY THAT NAMES A COMMAND, not only a fact: `_gate_economy_remedies`
    is what turns "this costs too much" into something an operator can run.

    ADVISORY, ALWAYS - like every check in this module's second half, this
    grades a repeated pattern rather than a single moment, and a WARNING
    here changes nothing about the exit code."""
    meta = (manifest or {}).get("meta") if isinstance(manifest, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    budget = meta.get("gateBudgetMs")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        rep.ok("gate economy",
               "no budget declared (meta.gateBudgetMs), so no gate entry is "
               "graded on cost")
        return
    eproject, econfig, rows, failure, _unreadable = _read_gate_rows(
        project, manifest_rel)
    if failure is not None:
        rep.warn("gate economy", failure)
        return
    names = _evidence_io.gate_names_seen(rows)
    if not names:
        rep.warn("gate economy",
                 "no evidence rows recorded yet, so no gate entry can be "
                 "graded on cost",
                 "run a phase gate to start recording; cost is only graded "
                 "past the floor a pattern needs")
        return
    classes = _gate_tally_classes(rows, names)
    phase_gate = meta.get("phaseGate")
    phase_gate = phase_gate if isinstance(phase_gate, dict) else {}
    always = [a for a in (phase_gate.get("always") or []) if isinstance(a, str)]
    phases = (manifest or {}).get("phases") or []
    over, graded, unmeasured = [], 0, []
    for name, ran in classes["never_failed"]:
        total = _evidence_io.gate_cost_ms(rows, name)
        measured = _evidence_io.gate_cost_measured(rows, name)
        if total is None or not measured:
            unmeasured.append(name)
            continue
        graded += 1
        mean = total / float(measured)
        if mean > budget:
            over.append((name, ran, mean))
    if over:
        lines, fixes = [], []
        for name, ran, mean in over:
            lines.append(
                "%s (ran %d, mean %s, budget %s)"
                % (name, ran, _fmt.human_duration(int(round(mean))),
                   _fmt.human_duration(budget)))
            fixes.append("%s: %s" % (name, "; ".join(
                _gate_economy_remedies(name, phases, always))))
        rep.warn("gate economy",
                 "past the floor, never failed, and costing more than the "
                 "declared budget: %s" % ("; ".join(lines),),
                 " | ".join(fixes))
        return
    detail = ("%d gate(s) checked past the floor and never failed; none "
             "costs more than the %s budget" % (graded,
                                                 _fmt.human_duration(budget)))
    if unmeasured:
        detail += ("; %d unmeasured (no recorded durationMs): %s"
                   % (len(unmeasured), ", ".join(unmeasured)))
    rep.ok("gate economy", detail)


def _pct(numerator, denominator):
    """A share as a reader reads one - whole-number percent, never a bare
    ratio a decimal point could hide a rounding difference inside."""
    return "%d%%" % round(100.0 * numerator / denominator)


def check_shadow_recall(rep, project, manifest_rel, manifest, config=None):
    """While a phase's sign-off gate is still derived IN SHADOW, would the
    derived set have caught what actually failed?

    TWO DIFFERENT RECALLS, because they answer two different questions and a
    single number would blur them - the definitions are Meta's own, from the
    predictive-test-selection paper this feature's design cites:

      TEST recall   - of every FAILING SUITE seen across every shadow run,
                      what share did the derived set list? Suite-weighted: a
                      run with three failing suites contributes three to
                      both the numerator's ceiling and the denominator, not
                      one. `sum(listed) / sum(full)` over the ledger.
      CHANGE recall - of every RED shadow run - `shadow.full > 0`, meaning
                      at least one failing suite was actually seen, never
                      every row that merely carries a `shadow` key - what
                      share had at least one failing suite the derived set
                      listed? Run-weighted, on purpose: a change either got
                      SOME signal from the derived set or it got none, and a
                      run with many failing suites must not outweigh one
                      with a single failing suite in THIS count the way it
                      rightly does in the other.

    `run-test-gate.shadow_gate_claim` never records a row with `full == 0`
    TODAY - it returns `None` on an empty failing-suite list, so every row
    this reads currently already is red. The filter is kept anyway, because
    the definition itself says "RED shadow run" and not "every recorded
    shadow row": a future writer that started recording a green wide run
    (to carry a `narrowed`-style claim, say) would otherwise silently dilute
    CHANGE recall's denominator with runs that had nothing to catch,
    without this file's own tests ever seeing the difference.

    COUNTING RUNS WHERE SUITES ARE OWED IS THE BUG THIS SPLIT EXISTS TO
    REFUSE. A history with several failing suites in one run and one in
    another, where every run "caught" at least one, reads as a PERFECT
    per-run share if the shares are averaged - while the suite-weighted
    figure is lower whenever a run's uncaught suites outnumber its caught
    one, and only the second is what an operator deciding whether to trust
    the derived set for REAL coverage needs. `check_gate_economy`'s
    mean-vs-total split above is the same lesson about a different pair of
    numbers.

    COMPUTED FROM THE LEDGER EVERY TIME, NEVER WRITTEN ANYWHERE: this is a
    read of history, not a new fact stapled onto a phase or a row.

    NO `meta.phaseGate.mode` MEANS NOTHING IS DERIVED, so there is nothing to
    grade recall over - said as an OK row rather than silence, the same rule
    `check_gate_economy` follows for `meta.gateBudgetMs`: a row that simply
    stopped appearing would read as "checked and clean" to a doctor render
    nobody diffs against yesterday's.

    A MODE DECLARED WITH NO SHADOW ROW YET IS ALSO AN OK ROW, not a warning
    that recall could not be established - `run-test-gate.shadow_gate_claim`
    only ever records `shadow` on a row that observed a REAL failure, so a
    project that has not hit one yet has asked the question honestly and
    gotten "none recorded" rather than failed to earn an answer.

    AN UNREADABLE LEDGER IS SAID, NEVER READ AS "NO SHADOW RUNS" - the same
    distinction `check_gate_patterns` and `check_gate_economy` draw for the
    same evidence read, because folding "could not open the file" into "the
    file has nothing in it" tells an operator their coverage is thin when
    the true problem is that this check could not look. TWO WAYS A LEDGER
    CAN BE UNREADABLE, and both are WARNINGS that print no recall: a read
    that failed outright (a directory it cannot even list), worded by
    `_read_gate_rows` through the vocabulary's templates, is one, and
    `_evidence_io.read_rows`'s own `unreadable` count on an otherwise
    successful read - a torn line, a file that would not decode - is the
    other, worded as the partial read it is. A row lost to the second is not
    a row that never existed, and folding it into "none recorded" is the same
    overclaim the first branch exists to refuse.

    ADVISORY, ALWAYS, LIKE EVERY CHECK IN THIS MODULE'S SECOND HALF - the row
    carries the same remedy sentence whatever the two numbers say, because
    NO THRESHOLD HERE DECIDES ANYTHING: the plan's own `mode` switch is
    the only thing that turns shadow into enforce, and that is a judgement
    call this command has no basis to make for its reader."""
    meta = (manifest or {}).get("meta") if isinstance(manifest, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    phase_gate = meta.get("phaseGate")
    phase_gate = phase_gate if isinstance(phase_gate, dict) else {}
    mode = phase_gate.get("mode")
    if not mode:
        rep.ok("shadow recall",
               "no meta.phaseGate.mode declared, so no derivation is "
               "declared and there is nothing to grade recall over")
        return
    eproject, econfig, rows, failure, unreadable = _read_gate_rows(
        project, manifest_rel)
    if failure is not None:
        rep.warn("shadow recall", failure)
        return
    # A DIFFERENT FACT FROM THE FAILURE ABOVE, so its own words: the ledger
    # WAS read, and some of it could not be parsed.
    if unreadable:
        rep.warn("shadow recall",
                 "the evidence ledger was only partly readable: %d row(s) or file(s) "
                 "could not be parsed - recall is not printed over a "
                 "ledger this check could not fully read"
                 % (unreadable,))
        return
    shadow_rows = [r for r in (rows or [])
                   if isinstance(r.get("shadow"), dict)]
    if not shadow_rows:
        rep.ok("shadow recall",
               "meta.phaseGate.mode is %r but no shadow run is recorded yet "
               "- none recorded, so test and change recall cannot be "
               "measured" % (mode,))
        return
    total_listed = sum(r["shadow"].get("listed") or 0 for r in shadow_rows)
    total_full = sum(r["shadow"].get("full") or 0 for r in shadow_rows)
    # CHANGE recall's denominator is RED shadow runs - `full > 0` - never
    # every row carrying a `shadow` key: see the docstring's note on why the
    # filter is kept even though no writer today emits a green one.
    red_rows = [r for r in shadow_rows if (r["shadow"].get("full") or 0) > 0]
    hits = sum(1 for r in red_rows if (r["shadow"].get("listed") or 0) > 0)
    n_runs = len(red_rows)
    rep.warn("shadow recall",
             "test recall %s (%d/%d failing suite(s) across every shadow "
             "run the derived gate would have listed), change recall %s "
             "(%d/%d red shadow run(s) with at least one failing suite the "
             "derived gate listed)"
             % (_pct(total_listed, total_full) if total_full else "n/a",
                total_listed, total_full,
                _pct(hits, n_runs) if n_runs else "n/a", hits, n_runs),
             "set meta.phaseGate.mode to \"enforce\" when this recall is "
             "enough - nothing switches it for you")


# --- checks: the third place -----------------------------------------------------
FULL_RUN_CHECK = "full run"


def _run_age(ts):
    """A recorded run's own `ts` (`%Y-%m-%dT%H:%M:%SZ`), read the way `_age`
    above already turns seconds into a reader's phrase - or None when the
    timestamp is not that shape, which the caller says out loud rather than
    printing an age for a run whose `ts` it could not parse."""
    try:
        epoch = calendar.timegm(time.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None
    return _age(time.time() - epoch)


_SETTLE_FIX = ("/audit:review %s --full to record a fresh full run against "
              "this phase's mergedHead, or run the pre-push/CI step that "
              "records one")


def check_full_run(rep, project, manifest_rel, manifest, git_root, config=None):
    """Is this plan's THIRD PLACE - a full, out-of-band run - saying every
    merged phase is WHOLE, or does something here still need settling?

    REUSES `_evidence_io.full_status` RATHER THAN RE-DERIVING IT, the same
    rule every check in this module follows for the evidence ledger: a
    second opinion about whether a phase's merge is backed by a whole full
    run is a second implementation that can disagree with the one that
    matters (`status`, `report` and the panel all read the same function).

    NO `meta.fullGate` MEANS NOTHING IS ASKED, said as an OK row rather than
    silence - the same rule `check_gate_economy` and `check_shadow_recall`
    already follow for their own opt-in switch: a plan that never declared a
    third place has not been told it is missing one, it has been told there
    is nothing to ask.

    THE UNREADABLE-LEDGER BRANCH COMES BEFORE ANY FIGURE, exactly where
    `check_gate_patterns`, `check_gate_economy` and `check_shadow_recall`
    put it - a torn ledger is not "nothing recorded", and folding it into
    that silence would tell an operator their merges are unproven when the
    true problem is that this check could not look.

    EVERY MERGED PHASE - `_evidence_io.merged_phase`, the one predicate the
    status, the report and the panel call too, never an effective status of
    done, which a phase can read without ever having merged - IS ASKED,
    WHOLE OR NOT: a PROVISIONAL phase gets a WARNING
    naming the command that would settle it, an UNKNOWN phase gets a
    WARNING naming `full_status`'s own basis (no `mergedHead` recorded, or
    that git itself could not answer ancestry). Neither is folded into the
    other, because they are different questions with different remedies -
    one names a run to go and record, the other names a fact this plan
    cannot yet ask.

    A ROW THAT FAILED A WHOLE-BEARING RULE IS NAMED WITH THE RULE IT
    FAILED, and this check never re-derives that sentence: it is already
    `full_status`'s own basis for a PROVISIONAL answer (the newest full run
    was on a dirty tree, counted nothing, or ran a different set of
    commands than `meta.fullGate` declares now) - printing it a second way
    here would be the second implementation this whole check exists to
    refuse.

    THE ALLOW ROW NAMES THE RUN: when every merged phase reads WHOLE, one OK
    row carries the newest whole-bearing full run's id, head and age - a
    reader told only "everything is fine" has been told less than a reader
    told which run makes that true and how long ago it ran.

    ADVISORY, ALWAYS - like every check in this module, this changes nothing
    about the exit code; the release guard is the one place a PROVISIONAL
    phase actually blocks anything."""
    manifest = manifest if isinstance(manifest, dict) else {}
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    full_commands = [c for _name, c in
                     _evidence_io.resolved_commands(manifest, meta.get("fullGate"))]
    if not full_commands:
        rep.ok(FULL_RUN_CHECK, "no third place declared (meta.fullGate)")
        return
    _eproject, _econfig, rows, failure, unreadable = _read_gate_rows(
        project, manifest_rel)
    if failure is not None:
        rep.warn(FULL_RUN_CHECK, failure)
        return
    # A DIFFERENT FACT FROM THE FAILURE ABOVE, so its own words: the ledger
    # WAS read, and some of it could not be parsed.
    if unreadable:
        rep.warn(FULL_RUN_CHECK,
                 "the evidence ledger was only partly readable: %d row(s) or file(s) "
                 "could not be parsed - the third place is not graded over "
                 "a ledger this check could not fully read" % (unreadable,))
        return
    merged = [p for p in (manifest.get("phases") or [])
             if _evidence_io.merged_phase(p)]
    if not merged:
        rep.ok(FULL_RUN_CHECK,
               "meta.fullGate is declared but no phase has merged yet")
        return
    results = [(p, _evidence_io.full_status(rows, p, git_root, full_commands))
              for p in merged]
    provisional = [(p, r) for p, r in results
                  if r["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL]
    unknown = [(p, r) for p, r in results
              if r["answer"] == _manifest_vocab.FULL_STATUS_UNKNOWN]
    whole = [(p, r) for p, r in results
            if r["answer"] == _manifest_vocab.FULL_STATUS_WHOLE]
    for p, r in provisional:
        rep.warn(FULL_RUN_CHECK,
                 "phase %s is PROVISIONAL: %s" % (p.get("id"), r["basis"]),
                 _SETTLE_FIX % (p.get("id"),))
    for p, r in unknown:
        rep.warn(FULL_RUN_CHECK,
                 "phase %s is UNKNOWN: %s" % (p.get("id"), r["basis"]))
    if provisional or unknown:
        return
    run_ids = set(r.get("runId") for _p, r in whole if r.get("runId"))
    candidates = [row for row in (rows or [])
                 if isinstance(row, dict)
                 and row.get("scope") == _evidence_io.FULL_SCOPE
                 and row.get("runId") in run_ids]
    candidates.sort(key=lambda row: str(row.get("ts") or ""), reverse=True)
    if candidates:
        newest = candidates[0]
        head = (newest.get("testedState") or {}).get("head")
        age = _run_age(newest.get("ts"))
        rep.ok(FULL_RUN_CHECK,
               "%d merged phase(s) read whole against the newest "
               "whole-bearing full run %s (head %s)%s"
               % (len(whole), newest.get("runId"), head,
                  ", %s old" % age if age else ""))
        return
    rep.ok(FULL_RUN_CHECK, "%d merged phase(s) read whole" % (len(whole),))


# --- checks: learned couplings -------------------------------------------------
COUPLING_CHECK = "coupling"

# How many GREEN WHOLE-BEARING full runs a coupling may go without catching
# anything before this check names it as a candidate for `uncouple`. Counted in
# runs, never in days: only a full run runs every coupled test, so a stretch
# with no full run has not exercised a coupling at all and must not age it.
# Large enough that a run of unrelated changes does not make a young coupling
# look dead; small enough that one whose sources moved on is named while
# somebody still remembers why it was learned. Printed beside every candidate
# as the basis, because a threshold nobody can see is a verdict nobody can
# argue with.
UNCOUPLE_AFTER_FULL_RUNS = 10

_UNCOUPLE_FIX = "audit-task.py uncouple --test %s"
_NEVER_FOR_YOU = (" - never run for you: dropping a coupling narrows the "
                  "sign-off gate, which is a judgement this check has no "
                  "basis to make")
_GIT_TIMEOUT = 30


def _coupling_entries(coupling):
    """The entries of `meta.coupling` that name a test - the key `uncouple`
    drops an entry by, so an entry without one has no command to offer."""
    return [e for e in coupling if isinstance(e, dict)
            and isinstance(e.get("test"), str) and e.get("test").strip()]


def _norm(path):
    """A coupled path in the spelling `git ls-files` prints it back in."""
    return posixpath.normpath(path.strip().replace("\\", "/"))


def _outside_repository(path):
    """Whether `path` leaves the project before git is asked about it - a
    parent-relative path or an absolute one (either slash, or a drive
    letter). The coupling verb accepts both shapes, and git refuses a WHOLE
    `ls-files` batch over one of them, so it is split out first rather than
    left to switch the tracking check off for every other coupling."""
    norm = _norm(path)
    return (norm == ".." or norm.startswith("../") or norm.startswith("/")
            or (len(norm) > 1 and norm[1] == ":"))


def _coupling_paths(entry):
    """The test first, then every source that reads as a path."""
    sources = entry.get("sources") if isinstance(entry.get("sources"), list) else []
    return [entry["test"]] + [s for s in sources
                              if isinstance(s, str) and s.strip()]


def tracked_among(project, paths):
    """`(tracked, why)` - which of `paths` git tracks under `project`, from
    ONE `git ls-files` over all of them, or `(None, why)` when git could not
    be asked.

    ONE CALL, NOT ONE PER PATH: a plan keeps learning couplings, and a
    doctor that spawned git per path would pay for every one of them on
    every run. Run through `_worktrees._git`, the one git runner below this
    layer, rather than a second subprocess path of its own.
    `--literal-pathspecs` because a coupled path is a file name, never a
    pattern - a bracket in a name must not widen the question into a glob
    that some OTHER tracked file answers. A path that git prints back
    beneath (a directory) counts as tracked, because something under it is.
    Paths outside the repository must be split out by the caller
    (`_outside_repository`) - git refuses the whole batch over one.

    `why` IS THE BASIS for the fail-open branch: git absent, not a
    repository, or a timeout are each said in git's own words rather than
    read as "nothing is tracked", which would name every coupling at once."""
    wanted = sorted(set(_norm(p) for p in paths))
    if not wanted:
        return set(), None
    code, out, err = _worktrees._git(
        project, ["--literal-pathspecs", "ls-files", "-z", "--"] + wanted,
        timeout=_GIT_TIMEOUT)
    if code is None:
        return None, "git ls-files could not run (%s)" % (err,)
    if code != 0:
        said = (err or "").strip()
        return None, ("git ls-files exited %d: %s"
                      % (code, said.splitlines()[0] if said else "no message"))
    listed = [n for n in (out or "").split("\0") if n]
    return set(p for p in wanted
               if p in listed or any(n.startswith(p + "/") for n in listed)), None


def _uncouple_fix(test):
    """The command that drops `test`'s entry, and why it is not run here."""
    return (_UNCOUPLE_FIX % (shlex.quote(test),)) + _NEVER_FOR_YOU


def _check_coupling_tracking(rep, project, entries, git_root):
    """A coupling naming a path git does not track - or one outside the
    repository, which git cannot track at all - is a WARNING with the
    command that drops it: never dropped here, and never folded into the
    ageing verdict, because a file that is gone is a different fact from a
    test that has stopped catching anything."""
    outside = dict((e["test"], [p for p in _coupling_paths(e)
                                if _outside_repository(p)]) for e in entries)
    for entry in entries:
        if outside[entry["test"]]:
            rep.warn(COUPLING_CHECK,
                     "meta.coupling entry for %s names %s outside the "
                     "repository - git cannot track it, so the coupling can "
                     "neither run nor catch anything"
                     % (entry["test"], _output.some_of(outside[entry["test"]])),
                     _uncouple_fix(entry["test"]))
    paths = [p for e in entries for p in _coupling_paths(e)
             if not _outside_repository(p)]
    if not paths:
        return
    by_hand = "git ls-files -- %s" % (" ".join(
        shlex.quote(p) for p in sorted(set(_norm(p) for p in paths))),)
    if not git_root:
        rep.warn(COUPLING_CHECK,
                 "whether the coupled paths are tracked was not checked: "
                 "this project is not a git repository (or git could not "
                 "find its root)", by_hand)
        return
    tracked, why = tracked_among(project, paths)
    if tracked is None:
        rep.warn(COUPLING_CHECK,
                 "whether the coupled paths are tracked was not checked: %s"
                 % (why,), by_hand)
        return
    flagged = 0
    for entry in entries:
        gone = [p for p in _coupling_paths(entry)
                if not _outside_repository(p) and _norm(p) not in tracked]
        if not gone:
            continue
        flagged += 1
        rep.warn(COUPLING_CHECK,
                 "meta.coupling entry for %s names %s that git does not "
                 "track - the coupling points at a file that is gone or was "
                 "never committed, so it can neither run nor catch anything"
                 % (entry["test"], _output.some_of(gone)),
                 _uncouple_fix(entry["test"]))
    if not flagged and not any(outside.values()):
        rep.ok(COUPLING_CHECK,
               "every path the %d coupling(s) name is tracked by git (one "
               "git ls-files over %d path(s))"
               % (len(entries), len(set(_norm(p) for p in paths))))


def coupling_age(entry, run_moments):
    """`(runs, field, why)` - how many green measured full runs (their
    moments in `run_moments`) came strictly AFTER the entry was last
    caught, or learned when it never was.

    `lastCaught` OUTRANKS `learnedAt`: a coupling that caught a failure
    yesterday earned its place yesterday, however long ago it was learned.
    `runs` is None and `why` the basis when neither field reads as a moment -
    an entry that cannot be aged is said, never read as a fresh one."""
    field = "lastCaught" if entry.get("lastCaught") else "learnedAt"
    stamp = entry.get(field)
    if not stamp:
        return None, field, "it carries neither lastCaught nor learnedAt"
    moment = _usage_core.parse_ts(stamp)
    if moment is None:
        return None, field, "its %s %r does not read as a moment" % (field, stamp)
    return sum(1 for m in run_moments if m > moment), field, None


def _measured_run_moments(rows, full_commands):
    """The moment of every GREEN MEASURED full run in `rows` - the ledger's
    own rule (`_evidence_io._measurement_disqualification`), never a second
    reading of it: a red run, a repeated verdict, a dirty tree or a different
    command set is not a run that gave a coupling the chance to catch
    anything. A missing tested head is: the run still measured the gate, and
    the head only matters to what commit it can vouch for, which ageing
    never asks.

    `(moments, undated)`: a green measured row whose `ts` does not parse
    cannot be placed before or after a coupling, so it ages nothing - and
    `undated` COUNTS those rows so the caller says so, rather than printing
    a run count quietly narrower than the ledger it read."""
    moments, undated = [], 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if _evidence_io._measurement_disqualification(
                row, full_commands) is not None:
            continue
        moment = _usage_core.parse_ts(row.get("ts"))
        if moment is None:
            undated += 1
        else:
            moments.append(moment)
    return moments, undated


def _undated_note(undated):
    """The clause every ageing row carries when some green run could not be
    placed in time - empty when none."""
    if not undated:
        return ""
    return ("; %d green measured full run(s) carry a ts that does not parse, "
            "so they age nothing" % (undated,))


def _relearn_fix(entry):
    """Drop, THEN learn again. `couple` over a test that already carries an
    entry only widens its sources and keeps `learnedAt`, so `couple` alone
    would leave the very field this warning is about untouched."""
    test = shlex.quote(entry["test"])
    sources = ",".join(s for s in _coupling_paths(entry)[1:])
    return ("audit-task.py uncouple --test %s, then audit-task.py couple "
            "--test %s --sources %s --basis-run <runId of a full run it "
            "failed in> to learn it again (couple alone only widens an "
            "existing entry and keeps its learnedAt)"
            % (test, test, shlex.quote(sources) if sources else "<paths>"))


def _check_coupling_ageing(rep, project, manifest_rel, manifest, meta, entries):
    """Which couplings have gone `UNCOUPLE_AFTER_FULL_RUNS` green measured
    full runs without catching anything - named as CANDIDATES, never
    dropped."""
    full_commands = [c for _name, c in
                     _evidence_io.resolved_commands(manifest, meta.get("fullGate"))]
    if not full_commands:
        rep.ok(COUPLING_CHECK,
               "no meta.fullGate declared, so no run measured it and no "
               "coupling can be aged against one")
        return
    _eproject, _econfig, rows, failure, unreadable = _read_gate_rows(
        project, manifest_rel)
    if failure is not None:
        rep.warn(COUPLING_CHECK, failure)
        return
    if unreadable:
        rep.warn(COUPLING_CHECK,
                 "the evidence ledger was only partly readable: %d row(s) or "
                 "file(s) could not be parsed - no coupling is aged over a "
                 "ledger this check could not fully read" % (unreadable,))
        return
    moments, undated = _measured_run_moments(rows, full_commands)
    basis = "UNCOUPLE_AFTER_FULL_RUNS = %d" % (UNCOUPLE_AFTER_FULL_RUNS,)
    aged, unageable = [], []
    for entry in entries:
        runs, field, why = coupling_age(entry, moments)
        if runs is None:
            unageable.append((entry, why))
        else:
            aged.append((entry["test"], runs, field))
    candidates = [a for a in aged if a[1] >= UNCOUPLE_AFTER_FULL_RUNS]
    if candidates:
        rep.warn(COUPLING_CHECK,
                 "CANDIDATE for uncouple - %s: no failure caught across at "
                 "least %s green measured full run(s) (%s)%s"
                 % ("; ".join("%s (%d run(s) since its %s)" % (t, n, f)
                              for t, n, f in candidates),
                    UNCOUPLE_AFTER_FULL_RUNS, basis, _undated_note(undated)),
                 "; ".join(_UNCOUPLE_FIX % (shlex.quote(t),)
                           for t, _n, _f in candidates) + _NEVER_FOR_YOU)
    if unageable:
        rep.warn(COUPLING_CHECK,
                 "cannot be aged against the full runs: %s"
                 % ("; ".join("%s (%s)" % (e["test"], why)
                              for e, why in unageable),),
                 "; ".join(_relearn_fix(e) for e, _why in unageable)
                 + _NEVER_FOR_YOU)
    if candidates or unageable:
        return
    rep.ok(COUPLING_CHECK,
           "%d coupling(s) aged over %d green measured full run(s); "
           "none has gone %s of them uncaught (%s), the oldest %d%s"
           % (len(aged), len(moments), UNCOUPLE_AFTER_FULL_RUNS, basis,
              max(n for _t, n, _f in aged), _undated_note(undated)))


def check_couplings(rep, project, manifest_rel, manifest, git_root, config=None):
    """Is every learned coupling still about files that exist, and is any of
    them no longer catching anything?

    TWO QUESTIONS, NEVER ONE: a coupling naming a path git does not track
    (one batched `git ls-files`), or one outside the repository, is broken
    NOW; one that has not caught a
    failure across `UNCOUPLE_AFTER_FULL_RUNS` green measured full runs
    may merely be quiet. The first is a WARNING naming the path, the second a
    CANDIDATE with the constant printed as its basis, and both carry the
    exact `audit-task.py uncouple --test <path>` that would act on them.

    NEITHER IS EVER REMOVED HERE. `audit-task.py` is the only writer of
    `meta.coupling`, and removal narrows the gate a phase signs off on -
    a doctor that pruned on its own would be deciding coverage for its
    reader.

    FAIL-OPEN, BECAUSE ADVISORY: no git root or no git on PATH is a WARNING
    saying the tracking half was NOT CHECKED (with the command to ask by
    hand), never a crash and never an OK claiming every path is tracked; an
    unreadable ledger is worded by `_read_gate_rows` through the same
    vocabulary templates every other ledger check here uses.

    NO `meta.coupling` IS AN OK ROW, not silence - the same rule
    `check_full_run` follows for its own opt-in field. `config` is accepted
    for the signature every trail check shares and read by nothing yet."""
    manifest = manifest if isinstance(manifest, dict) else {}
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    coupling = meta.get("coupling")
    if not coupling:
        rep.ok(COUPLING_CHECK,
               "no meta.coupling learned, so there is no coupling to check")
        return
    if not isinstance(coupling, list):
        rep.warn(COUPLING_CHECK,
                 "meta.coupling is a %s, not an array, so no entry could be "
                 "read" % (type(coupling).__name__,),
                 "validate-manifest.py names the shape it expects")
        return
    entries = _coupling_entries(coupling)
    if not entries:
        rep.warn(COUPLING_CHECK,
                 "meta.coupling holds %d entr(ies) and none names a test, so "
                 "none can be checked or uncoupled" % (len(coupling),),
                 "validate-manifest.py names the shape it expects")
        return
    _check_coupling_tracking(rep, project, entries, git_root)
    _check_coupling_ageing(rep, project, manifest_rel, manifest, meta, entries)


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
