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
# TWO HOMES, DECIDED RATHER THAN OVERLOOKED (F148). The same basenames are spelled
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
