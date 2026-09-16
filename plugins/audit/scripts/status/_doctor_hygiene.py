#!/usr/bin/env python3
"""
The two questions about the working copy itself: what is HELD, and what is
LEAKING.

Split out of `audit-doctor.py`. `check_locks` names the lock a mutating
/audit command would refuse on, and `check_local_artifacts` names the
per-machine artifact that has got itself into git. Different subjects, one
scope: neither reads the manifest for anything but a path, both answer about
files that live BESIDE the plan rather than in it, and both shell out to git in
the same working copy. They are the last two rows of the report for the same
reason.

The journal is deliberately NOT in the local-artifact list - it is the opposite
kind of artifact and must stay tracked, which is the reverse warning
`_doctor_trail.check_journal` carries.

`check_locks` delegates to `_locks` rather than re-deriving the verdict: this
check once called anything older than 60 minutes stale, which told the human a
healthy 90-minute phase run had crashed - a diagnostic manufacturing the very
takeover that loses work.

Layer 3: `_locks` is at layer 1, `_doctor_report` at layer 2, and this module
loads nothing at runtime at all.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__doctor_hygiene.py` - see
`plugins/audit/tests/_harness.py`.
"""
import os
import pathlib
import shutil
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

import _locks  # noqa: E402  (lock paths + the liveness verdict, at layer 1)
import _branch  # noqa: E402  (where a phase's branch lands, at layer 1)
import _worktrees  # noqa: E402  (git's worktree list + the containment answer, L1)


# The panel's per-project files: basename, the label a row uses, WHY that row
# exists, and the repair it prints. ONE ROW PER FILE and not one row for both,
# because the repairs are different acts - a leaked token has to be ROTATED and a
# leaked traceback cannot be, so a reader handed the other file's repair does
# neither of them.
#
# The launch log is here for the same reason the pidfile is, arrived at from the
# other direction: the pidfile leaks a credential, and the log leaks the machine.
# It is the stderr of a detached launch, so what lands in it is whatever that
# launch died of - a traceback spelling absolute paths, and a home directory is a
# person's name on most of them. That is precisely what the committed-PII backstop
# exists for, and an ignore rule cannot reach a file that was committed before the
# rule was written.
#
# TWO HOMES, DECIDED RATHER THAN OVERLOOKED. The same basenames are spelled
# in `panel/panel-server.py` (`_PANEL_PRIVATE_FILES`), which is what writes their
# ignore rules, and `dh19` in `tests/test__doctor_hygiene.py` compares the two SETS
# rather than trusting either.
#
# The layer table is the reason usually given, and it is the weaker half of the
# argument: this module sits at layer 3, `panel-server` at 7, and `_panel_paths` --
# the panel module that would obviously own a filename -- is this module's own PEER
# at 3, which it may not import. A shared home would therefore have to be a NEW
# module at layer 2 or below.
#
# The reason that survives a layer-table change is what the tables hold. They
# answer different questions and merely share a key set: over there a rule git must
# honour and the note that goes above it, here what leaks and the repair for it --
# and the repairs differ, which is the ONE ROW PER FILE rule above. Merging the key
# set alone would NOT retire `dh19`, because a file added to a shared list and given
# prose on one side only is still a file that gets reported and never ignored, or
# ignored and never reported. A merge that leaves the check standing buys a pair of
# string literals for a module, a `_deps.LAYERS` row, a `PLUGIN-BUILD-GUIDE.md`
# section and -- if the prose were keyed off the shared list to force the issue --
# a KeyError at import inside a read-only diagnostic. So the names stay in two
# homes and the pin is the mechanism.
#
# Revisit when a THIRD reader of these names appears: at that point the pin is
# comparing pairs of pairs, and a keyed lookup off one shared list starts being
# worth the crash mode it brings.
_PANEL_FILES = (
    ("audit-panel.json", "panel pidfile",
     "it holds a live session token",
     "git rm --cached it and commit; then restart the panel to rotate the "
     "token the history already saw"),
    ("audit-panel.log", "panel launch log",
     "it is the stderr of a detached launch, so it carries whatever that "
     "launch died of - tracebacks naming absolute paths on this machine",
     "git rm --cached it and commit; the panel empties the file on every start "
     "that reaches listening, but emptying a file does not empty the history"),
)


# --- checks: an empty record is two different facts -------------------------------
# The files the gates leave behind, and the sentence each row needs when one of
# them holds nothing. Both live under `logsDir`; both are APPEND-ONLY records of
# something having happened, which is why an empty one is ambiguous in exactly the
# same way and is worth one shared answer rather than two.
_EMPTY_RECORDS = (
    ("gate events", None,
     "the plan gate has been asked and had nothing to refuse",
     "every edit this project saw was exempt, covered by an in_progress task, or "
     "small enough for the trivial allowance - the gate records a row on every "
     "other outcome, at every tier including observe"),
    ("bypass log", "plan-bypass.log",
     "no single-use plan-first bypass has ever been armed here",
     "arming writes a line the moment the keyword is typed, so an empty file is "
     "the good news it looks like"),
)


def _hooks_have_run(project, cfg, cfg_mod):
    """Has anything in this project's state directory been written by a hook?

    The same evidence `check_hooks_fired` grades, asked again here for a different
    question. It is the only local proof that a guard has run at all, and without
    it an empty record says nothing about the guards - which is the whole of the
    distinction below."""
    try:
        state_dir = cfg_mod.state_dir(pathlib.Path(project), cfg)
        return any(os.path.isfile(os.path.join(state_dir, name))
                   for name in os.listdir(state_dir))
    except Exception:
        return False


def _record_rows(path):
    """(rows, refusal) - non-blank lines in an append-only record, or why not.

    A missing file is zero rows and NOT a refusal: the gates create these on
    first write, so absence and emptiness are the same news once the question
    below has been answered. Anything else that stops the read IS a refusal,
    because then the record is not empty, it is unavailable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return (len([ln for ln in fh.read().splitlines() if ln.strip()]),
                    None)
    except FileNotFoundError:
        return (0, None)
    except OSError as exc:
        return (None, getattr(exc, "strerror", None) or exc.__class__.__name__)


def check_gate_feed(rep, project, cfg, cfg_mod):
    """An empty record is good news or it is no record at all, and they look alike.

    MEASURED IN THE FIELD, WHERE BOTH FILES STAYED EMPTY FOR A WHOLE PROGRAM and
    that was read as a clean run. It is indistinguishable from a gate that never
    ran: the hooks are not installed, the plugin is disabled for this project, or
    `logsDir` points somewhere else. Nothing about the file itself can tell those
    apart, and a reader who assumes the happy one has assumed away the failure
    that matters most.

    So the emptiness is graded on a BASIS outside the file - whether any hook has
    ever written state here - and the two answers are worded apart. With that
    evidence present the record means what it looks like; without it the row says
    NOT ESTABLISHED, which is this product's word for the difference and is not a
    softer way of saying "clean".

    GRADED AS A WARNING AND NOT A FINDING, for the reason `check_sandbox` spells
    out at length about the same shape: a finding asserts the guards are absent,
    absence is exactly what this cannot establish, and `/audit:doctor` exits
    non-zero on a finding - so a fresh install that has simply not edited anything
    yet would fail CI having asked for nothing. `check_hooks_fired` already carries
    the row for the missing evidence itself; this one carries what that missing
    evidence COSTS, which is the reading of these two files.
    """
    logs = cfg_mod.logs_dir(pathlib.Path(project), cfg)
    attested = _hooks_have_run(project, cfg, cfg_mod)
    for label, basename, good, why in _EMPTY_RECORDS:
        name = basename or cfg_mod.GATE_EVENTS_FILE
        rows, refusal = _record_rows(os.path.join(str(logs), name))
        if refusal is not None:
            rep.warn(label,
                     "%s could not be read (%s), so it is unavailable rather "
                     "than empty - nothing here can be counted either way"
                     % (name, refusal),
                     "check logsDir in .claude/audit.config.json and the "
                     "permissions on that directory")
            continue
        if rows:
            rep.ok(label, "%d row(s) in %s" % (rows, name))
            continue
        if attested:
            rep.ok(label, "%s is empty, and hooks have run in this project - so "
                          "%s (%s)" % (name, good, why))
            continue
        rep.warn(label,
                 "%s is empty AND no hook state exists here, so whether %s is "
                 "NOT ESTABLISHED - an empty record and a guard that never ran "
                 "look identical from the file" % (name, good),
                 "run /audit:doctor's hooks row first: check the plugin is "
                 "installed AND enabled for this project (/plugin -> Installed), "
                 "make one edit, and re-run")


# --- checks: locks & local artifacts --------------------------------------------
def check_locks(rep, git_root, project, manifest_rel):
    """A held lock is why a command refuses; a stale one is why it refuses wrongly.

    Delegates to audit-lock.py rather than re-deriving the verdict. This used to
    call anything older than 60 minutes stale, which told the human a healthy
    90-minute phase run had crashed — the diagnostic manufacturing the very
    takeover that loses work. The lock script answers by probing the holder's pid
    on this host, and falls back to age only when it cannot.
    """
    if not (git_root and shutil.which("git")):
        rep.ok("locks", "no audit locks held")
        return
    try:
        # `_locks` (layer 1), imported at the top rather than `_load(...)`-ed:
        # this file (L7) loading `audit-lock.py` (L7) was one of the edges
        # `_deps.KNOWN_LAYER_DEBT` recorded. The `try` stays — `collect` shells
        # out to git, and a git that hangs or a lock dir that cannot be listed is
        # still the failure this arm reports.
        rows = _locks.collect(git_root)
    except Exception as exc:
        rep.warn("locks", "could not read the lock directory: %s" % exc,
                 "run `audit-lock.py status` by hand to see what is held")
        return
    if not rows:
        rep.ok("locks", "no audit locks held")
        return
    abandoned = ["%s (%s)" % (r["name"], r["basis"]) for r in rows if not r["live"]]
    if abandoned:
        rep.warn("locks",
                 "lock(s) with no live holder: %s" % "; ".join(abandoned),
                 "a mutating /audit command will offer to take over; if no run is "
                 "live you can delete the file")
    else:
        rep.ok("locks", "%d lock(s) held by a live run: %s"
               % (len(rows), "; ".join("%s (%s)" % (r["name"], r["basis"])
                                       for r in rows)))


def check_worktrees(rep, git_root, manifest):
    """What was LEFT BEHIND — the third member of this module's family.

    `check_locks` answers what is HELD and `check_local_artifacts` what is LEAKING;
    a worktree whose branch already reached its parent is neither, and until this
    check existed nothing in the plugin ever looked. The residue is real and grows in
    one direction: `git worktree prune` clears a record and LEAVES ITS BRANCH, so
    every abandoned parallel run deposits an orphan branch too.

    THE COUNT IS COMPUTED, NEVER WRITTEN. `_output.prose_number_claims()` fails a
    present-tense number in a docstring for exactly this reason, and a diagnostic is
    the last place a stale figure belongs.

    IT REPORTS AND NEVER REAPS. The doctor is read-only by contract, so the remedy is
    the command that would do it — and that command is itself read-only until the
    human names a verb. `check_branch_naming` used to be the only merge probe here
    and its advice was "do NOT delete"; this is the other half of that sentence, and
    it is separate because the two answer different questions: that one asks whether
    a phase's PARENT has landed, this one whether the phase's own branch has.
    """
    if not (git_root and shutil.which("git")):
        rep.ok("worktrees", "git cannot be asked here, so nothing is claimed about "
                            "what earlier runs left behind")
        return
    listing = _worktrees.list_worktrees(git_root)
    if listing["error"]:
        rep.warn("worktrees", "git would not list the worktrees: %s"
                 % (listing["error"],),
                 "run `git worktree list --porcelain` by hand; an unreadable list "
                 "is not an empty one")
        return
    linked = [r for r in listing["trees"] if not r.get("isMain")]
    if not linked:
        rep.ok("worktrees", "no linked worktree exists, so there is nothing to "
                            "have been left behind")
        return

    meta = (manifest or {}).get("meta") or {}
    development = meta.get("developmentBranch") or _branch.DEFAULT_PARENT
    parent_by_branch = {}
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        name = phase.get("branch")
        if name:
            parent_by_branch[str(name)] = _branch.parent_branch(meta,
                                                                phase)["branch"]

    landed, unknown, prunable, foreign = [], [], [], []
    for rec in linked:
        if rec.get("prunable"):
            prunable.append(rec.get("path"))
            continue
        branch = rec.get("branch")
        if not branch:
            continue                       # detached: no branch to have landed
        # WHOSE IT IS, BEFORE WHETHER IT LANDED. A worktree the plugin did not
        # create is never swept, so reporting it as residue and pointing at `sweep`
        # would send the reader to a command that will decline. A remedy that does
        # not work is worse than none: it teaches people the tool is broken.
        if _worktrees.read_provenance(rec.get("path"))["ours"] is not True:
            foreign.append("%s (%s)" % (rec.get("path"), branch))
            continue
        parent = parent_by_branch.get(branch, development)
        answer = _worktrees.merged_into(git_root, branch, parent)["answer"]
        if answer == _worktrees.CONTAINED:
            landed.append("%s (%s -> %s)" % (rec.get("path"), branch, parent))
        elif answer == _worktrees.UNKNOWN:
            unknown.append("%s (%s)" % (rec.get("path"), branch))

    # `some_of` and not `"; ".join(...)`: a count in front of a list that has been
    # cut short is a claim the reader cannot verify, and
    # `truncated_evidence_violations()` fails it.
    # On a repository with a real backlog this line is otherwise hundreds of
    # characters wide and nobody reads the remedy at the end of it.
    if prunable:
        rep.warn("worktrees",
                 "%d worktree record(s) point at a directory that is gone: %s"
                 % (len(prunable), _output.some_of(prunable, sep="; ")),
                 "`git worktree prune` clears the records - note it LEAVES the "
                 "branches, which is how an orphan branch outlives its worktree")
    if unknown:
        # Named rather than folded into "nothing to do": a question git refused is
        # not an answer, and a reader who is not told will read silence as clean.
        rep.warn("worktrees",
                 "%d worktree(s) whose branch could not be compared with its "
                 "parent: %s" % (len(unknown), _output.some_of(unknown, sep="; ")),
                 "the parent branch may not exist in this clone; check "
                 "`phase.parentBranch` and `meta.developmentBranch`")
    if foreign:
        # A REPORT, NOT A FINDING, and the remedy is a hand command. These are
        # somebody's working copies; the plugin will not touch them, and telling the
        # reader that plainly is the whole content of this row.
        rep.warn("worktrees",
                 "%d worktree(s) this plugin did not create: %s"
                 % (len(foreign), _output.some_of(foreign, sep="; ")),
                 "nothing here will remove them. Take one down when you want it "
                 "gone: `/audit:worktree remove --path <dir>`")
    if landed:
        rep.warn("worktrees",
                 "%d worktree(s) this plugin created hold a branch that already "
                 "reached its parent: %s"
                 % (len(landed), _output.some_of(landed, sep="; ")),
                 "`/audit:worktree sweep` lists what may go and what stays and "
                 "why - it is read-only until you pass --apply and a verb")
    elif not prunable and not unknown and not foreign:
        rep.ok("worktrees",
               "%d linked worktree(s), none holding a branch that has already "
               "landed" % (len(linked),))


def check_local_artifacts(rep, project, cfg, cfg_mod, manifest, git_root):
    """Are the plugin's LOCAL artifacts staying out of git? (v0.35)

    Every artifact it looks at is per-machine by design: the usage ledger
    (person identities, transcript cursors), stateDir (session scratch),
    logsDir (gate telemetry), and the panel's own files in `_PANEL_FILES` —
    the pidfile (a LIVE session token) and the launch log (a dead launch's
    stderr, so absolute machine paths). From 0.35 every dir-creating writer
    drops a `*` .gitignore inside and the panel writes a targeted rule for
    each of its files — this check catches what those cannot reach: files
    committed BEFORE the markers existed, and dirs made by older versions
    that no hook has touched since. WARNING at most: a tracked ledger is a
    privacy leak, not evidence of forgery. The journal is deliberately NOT
    in this list — it is the opposite kind of artifact and must stay tracked
    (check_journal warns about the reverse)."""
    if not git_root or not shutil.which("git"):
        rep.ok("hygiene", "not a git repository - local artifacts cannot "
               "reach version control")
        return
    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    ledger_rel = str(meta_usage.get("ledgerDir")
                     or os.path.join(".claude", "usage"))
    dirs = {
        "ledger": os.path.join(project, ledger_rel),
        "state": os.path.join(project, str(cfg.get("stateDir")
                                           or cfg_mod.DEFAULTS["stateDir"])),
        "logs": os.path.join(project, str(cfg.get("logsDir")
                                          or cfg_mod.DEFAULTS["logsDir"])),
    }
    panel = [(base, label, why, fix,
              os.path.join(project, ".claude", base))
             for base, label, why, fix in _PANEL_FILES]
    panel_bases = set(row[0] for row in panel)
    try:
        out = subprocess.run(
            ["git", "ls-files", "--"] + [row[4] for row in panel]
            + sorted(dirs.values()),
            cwd=project, capture_output=True, text=True, timeout=30)
        tracked = [ln for ln in (out.stdout or "").splitlines() if ln.strip()]
    except Exception:
        rep.ok("hygiene", "git unavailable for the tracked-files check")
        return
    # BASENAME EQUALITY, not `endswith`. `audit-panel.json` is a suffix of
    # `stale-audit-panel.json`, which is somebody's own file and not this
    # plugin's - and the two rows below PARTITION the tracked list, so a name
    # matched loosely here is a name silently dropped from `others`.
    for base, label, why, fix, _path in panel:
        if any(os.path.basename(ln) == base for ln in tracked):
            rep.warn("hygiene",
                     "the %s (.claude/%s) is TRACKED in git - %s"
                     % (label, base, why), fix)
    others = [ln for ln in tracked if os.path.basename(ln) not in panel_bases]
    if others:
        rep.warn("hygiene",
                 "%d local file(s) tracked in git (ledger/state/logs are "
                 "per-machine: identities and session scratch), e.g. %s"
                 % (len(others), others[0]),
                 "git rm --cached them and commit; the dirs self-ignore "
                 "from 0.35 on, but an ignore cannot untrack history")
    unprotected = []
    for name, d in sorted(dirs.items()):
        if not os.path.isdir(d) \
                or os.path.exists(os.path.join(d, ".gitignore")):
            continue
        try:
            ig = subprocess.run(
                ["git", "check-ignore", "-q", "--", os.path.join(d, "x")],
                cwd=project, capture_output=True, timeout=30)
            if ig.returncode == 0:
                continue           # covered by the repo's own rules
        except Exception:
            pass
        unprotected.append(name)
    if unprotected:
        rep.warn("hygiene",
                 "local dir(s) not ignored yet: %s" % ", ".join(unprotected),
                 "any hook run makes them self-ignore (a `*` .gitignore "
                 "inside); or add them to .gitignore yourself")
    if not tracked and not unprotected:
        seen = sorted(n for n, d in dirs.items() if os.path.isdir(d))
        seen += [label for _base, label, _why, _fix, path in panel
                 if os.path.exists(path)]
        if seen:
            rep.ok("hygiene", "local artifacts stay out of git (%s)"
                   % ", ".join(seen))
        else:
            # NAMES WHAT IT LOOKED FOR, so "nothing found" cannot be read as
            # "nothing was checked" - the distinction this whole row exists to
            # keep.
            rep.ok("hygiene", "no local artifacts yet (ledger, state, logs, %s)"
                   % ", ".join(label for _b, label, _w, _f in _PANEL_FILES))


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
        print("_doctor_hygiene.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__doctor_hygiene.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
