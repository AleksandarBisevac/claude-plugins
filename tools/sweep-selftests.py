#!/usr/bin/env python3
"""
Run every `--selftest` in the tree, in parallel, under the STRICTEST of the three
sweeps that used to exist.

    tools/sweep-selftests.py                     # the sweep, all cores but two (every core under CI=true)
    tools/sweep-selftests.py PATH [PATH ...]     # only these suites, repo-relative; any other path is refused
    tools/sweep-selftests.py --shard 2/3         # the second of three cost-balanced parts
    tools/sweep-selftests.py --record-costs .github/sweep-costs.json   # write per-file timings
    tools/sweep-selftests.py --costs-from-log LOG --platform win32 --record-costs .github/sweep-costs.json
                                                 # ...or read them off a saved CI log
    tools/sweep-selftests.py --jobs 1            # serial, for a bisect
    tools/sweep-selftests.py --encoding cp1252   # the sweep again on a legacy code page: stdio codec AND, where faithful, a non-UTF-8 locale
    tools/sweep-selftests.py --quiet             # failures and totals; no per-file lines
    tools/sweep-selftests.py --spaced            # TMPDIR and interpreter under a spaced symlink
    tools/sweep-selftests.py --encoding cp1252 --spaced   # both conditions in one execution
    tools/sweep-selftests.py --selftest          # this file's own cases

WHY THIS EXISTS. The sweep was written twice - once in `tools/verify.sh` and once
inlined in `.github/workflows/ci.yml` - and the two copies did not check the same
things. `verify.sh` asserted the EXIT CODE and nothing else. CI additionally
required the `N/M cases passed` contract, applied the `--covered` skip, and carried
the trap that a migrated file must NOT print the contract. So a file that exited 0
having asserted nothing at all was GREEN locally and RED in CI - the exact "passes
locally, fails in CI" class this repo keeps a whole skill about, living inside the
tool built to stop forgotten steps.

Two copies of a procedure is one copy and one lie. This is the one copy: both
callers run this file, so a rule added here is added to both at once.

AND IT IS PARALLEL, which is why replacing the loop beat tightening it. Measured
before this file existed: 181 files, 56.3s end to end, because `<python> <file>
--selftest` is a process start plus an import graph and the serial loop paid both
181 times while thirteen cores idled. The work is subprocess-bound, so THREADS are
the right pool - the GIL is released across `subprocess.run`, and a process pool
would only add a second layer of interpreter starts.

`sys.executable`, not `python3` or `python`. The two old copies disagreed about
that too: `verify.sh` said `python3` and CI said `python`, so on a machine where
those are different interpreters the local sweep and the CI sweep were not testing
the same thing. The child is whatever is running this file.

OUTPUT IS COLLECTED AND PRINTED SORTED, never interleaved. A parallel runner whose
log is in completion order is a log you cannot diff against yesterday's, and
"which file was it" is the first question a red sweep has to answer.

AND EVERY CHILD RUNS IN AN EMPTY DIRECTORY IT IS EXPECTED TO LEAVE EMPTY. A
suite is run with its cwd AND `TMPDIR` pointed at a scratch directory holding one
file it did not put there, and the file is red if anything was added to that
directory, or the file that was already in it was removed or rewritten. Suites here
had been leaking git fixtures into whatever directory `TMPDIR` named for a long
time, and none of the gates could see it because `TMPDIR` is normally the system
temp. `run_one` and `scratch_debris` say what each half of that buys.

AND THE HOME DIRECTORY IS A SECOND WATCHED DIRECTORY. `TMPDIR` closes the
channel a leaked `mkdtemp` uses; an absolute path under `$HOME` was still invisible,
and this product's state lives exactly there - a config tree, a usage ledger, a
panel pidfile - so a suite that resolves one of them wrongly writes somewhere no
gate was looking. `HOME` is therefore pinned per child alongside every other name a
home lookup reads, and what a child leaves there is reported by its own channel.
`home_env` is the table and says why setting one of them is not enough. The day it
landed it found a suite shelling out to the real Azure CLI, which wrote into the
operator's home directory on any machine with `az` installed - CI's ubuntu runner
among them.

AND THE INTERPRETER'S BYTECODE CACHE IS SENT SOMEWHERE ELSE, which is not a detail:
macOS's system python writes a shadow cache under the HOME it is given for every
script it runs, so a suite that started a grandchild by the bare name `python3`
dirtied the watched directory through no fault of its own. `PYTHONPYCACHEPREFIX`
moves every interpreter's cache - rather than one platform's spelling of it - out of
both watched trees, which is the same move `TMPDIR` makes and is the alternative to
an exemption whose premise would have to be re-checked per platform. It also makes
this file's older claim true: the sweep really cannot damage the checkout it is
testing, where before it wrote a `__pycache__` into every directory it swept. Shared
across the run rather than allocated per child, because a cache nobody may reuse is
not a cache - on a cold tree the compile lands once instead of once per file.
"""
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent import futures

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`.
# Same shape as `tools/where.py`, and for the same reason.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

_output.install_path()

# The coverage classifier is development code under `tools/lints/`, which
# `install_path()` never puts on the path.
_lints = os.path.join(REPO, "tools", "lints")
if _lints not in sys.path:
    sys.path.insert(0, _lints)

import _output_lints  # noqa: E402  (selftest_coverage: which modules have a suite)

# The directories a sweep covers. A tuple so nothing can append to it at runtime.
#
# `tools/` IS ONE OF THEM, and that was the fix for a class rather than a file.
# Three tools here carried no cases at all - they printed a sentence saying a tool
# under `tools/` needs none - and nothing noticed, because the sweep walked only the
# plugin. That is the same silence CI's globbed sweep was written to end for
# `scripts/`: adding a file and adding a line to a list are two acts, and only one of
# them was ever enforced. A tool without a suite now fails this sweep by name.
#
# It also means every tool suite runs HERE and nowhere else. `verify.sh` and `ci.yml`
# each carried a `--selftest` line per tool for a while; the sweep covers them on
# both sides, and one path to a check beats two.
# `.claude/hooks/` IS ONE OF THEM TOO, for the same reason one step later. This
# repository's own hooks - the release guard whose docstring calls itself fail-loud
# because what it protects is irreversible, and the hook that asks a commit for its
# claims - each carried a suite that nothing ran: the sweep walked the plugin and
# `tools/`, so a change that broke either shipped green. Nothing compares this
# tuple with the documents that enumerate the roots; a root added here owes its
# mention in each of them to its author.
#
# THE SHIPPED PLUGIN IS NOT ONE OF THEM ANY MORE, and that is the point of this tuple
# losing two rows: a shipped module answers no `--selftest`, so there is nothing to run
# there. What the sweep asks of `hooks/` and `scripts/` is the question that stays
# true - does every module have a suite in `tests/`, or a named exemption - and
# `coverage_findings` asks it.
SWEEP_DIRS = (
    "tests",
    "tools",
    os.path.join(".claude", "hooks"),
)

# The contract every swept suite must print.
CONTRACT = re.compile(r"(\d+)/(\d+) cases passed")

# A file that has not finished by then is reported as a TIMEOUT rather than waited
# on forever. Neither old copy had one, so a hung selftest was indistinguishable
# from a slow machine and the sweep simply never returned.
DEFAULT_TIMEOUT = 300

# --- one concurrency budget ---------------------------------------------------
# The sweep runs files side by side, and a STAGED suite (one whose `__main__` is
# `_harness.staged_main`) runs its own blocks side by side as well. Two pools
# sized apart from each other were sized for two different machines: the sweep's
# for every core, the suite's for a share of the cores as if nothing else ran.
# On a four-core CI runner that let a staged suite be squeezed onto two cores
# while three sweep workers held the rest, and run 38370435884 killed
# `test_drive_phase.py` at the per-file cap on windows that way. So there is ONE
# budget - the sweep's `jobs` slots - and a staged suite holds several of them
# at once: `stage_grant(jobs)` of them, admitted in submission order, so while it
# runs nothing else can take its cores, and the number goes to the child in
# `STAGE_GRANT_VAR`, which `_harness.stage_workers()` reads. The name and the
# cap are `_harness.py`'s too; case bg0 fails when the two copies part.
STAGE_GRANT_VAR = "SWEEP_STAGE_GRANT"
FILE_TIMEOUT_VAR = "SWEEP_FILE_TIMEOUT"
STAGE_GRANT_MAX = 6
# THE PER-FILE TIMEOUT IS A HANG DETECTOR, calibrated per file from the cost
# table rather than one cap for every file: `DEFAULT_TIMEOUT` (or `--timeout`)
# is the floor, and a file the table records as heavy gets this many times its
# recorded slot-seconds over the slots it holds now (`file_timeout`). So the
# table decides two things, the shard split and these timeouts, and a stale
# one can cost both: balance, and a timeout too tight for a file that grew past
# this factor of its entry. It cannot cost coverage, and staleness by OMISSION
# cannot tighten anything - a staged suite the table does not time is given the
# largest timeout any entry would get at the same slots, an ordinary file the
# floor. The table is recorded from windows logs (`--costs-from-log`), the
# platform that binds, and keeps the longer timing when a log carries a file
# twice, so its seconds already carry that platform's slowness and the factor
# covers only how one windows run differs from another. Across runs
# 38379717433 and 38382182020, plain and cp1252 cells both, no file timed at
# 20s or more varied by more than 1.51x between its four timings, and a
# factor of three over the longest of them is about twice that spread.
# Re-derive it from the same comparison when the table is re-recorded.
TIMEOUT_PER_COST = 3
# ...AND THE SWEEP NAMES A HUNG FILE BEFORE THE CI RUNNER KILLS THE JOB. A
# runner that reaches the job's `timeout-minutes` cancels it and names no
# step, let alone a file, so on a CI runner (`sweep_deadline`) every file's
# timeout is cut to what is left of `SWEEP_DEADLINE` seconds from the sweep's
# start: a file that starts late, behind a staged suite that held the slots,
# is given only the remainder. The arithmetic, against the `selftests` job's
# `timeout-minutes: 26` in ci.yml = 1560s: `CI_SETUP_ALLOWANCE` for what the
# cell does besides the sweep - checkout of the whole history, setup-python,
# the post steps, and this runner's own discovery and render (the windows
# cells of runs 38379717433 and 38382182020 spent 12-18s before the sweep
# step and under 5s after it) - leaves 1440s, and the deadline sits 60s under
# that, so the render that names the hung file has a minute to print it. The
# deadline in turn sits above the heaviest calibrated timeout the table gives
# (tt5 prints it), so it cuts a hang and never a heavy file's margin; when
# this table was recorded that file was `test_drive_phase.py` at 1347s, which
# is what moved the job from 25 minutes to 26 and no further. Case tt5 reads
# the job's figure out of ci.yml and the table off disk, and fails when any of
# the three stops fitting.
SWEEP_DEADLINE = 1380
CI_SETUP_ALLOWANCE = 120

# THE SPACED LEG. A user's temp directory, home or virtualenv can sit under a path
# holding a space, and a path reached through a link is spelled two ways by
# `realpath`. Every suite here had only ever run under a space-free temp root, so a
# fixture that built a shell command from an unquoted path was a different command
# on such a machine and nothing here could say so. `--spaced` runs the whole sweep
# with `TMPDIR` (and its two Windows spellings) under a path holding a space that is
# reached through a symlink whose target is NOT the link's own suffix-extension -
# `/tmp` -> `/private/tmp` is the shape macOS already tests, and it is the easy one
# - and with the interpreter itself launched through a spaced path, which is how a
# virtualenv under a spaced directory looks to a child that re-runs `sys.executable`.
#
# A FILE EXEMPT FROM THE LEG NAMES WHY: `{path: reason}`, the reason being the
# product defect or the fixture that makes the suite red under a spaced path. A
# row is a debt with its cause written down, and it leaves the table when the
# cause does. Each row is checked to still name a swept file, and a table that
# holds a row again has to be named in `gate-parity.py`'s audited tables, whose
# derivation sees only a table with rows in it.
SPACED_EXEMPT = {}


# --- discovery ----------------------------------------------------------------
def sweep_files(repo=None):
    """Every `.py` under the swept directories that carries its own suite, repo-relative,
    sorted.

    Delegates to `_output.py_files`, which is the same recursive walk the lints and
    `selftest_coverage()` use. A second implementation here is how CI's old flat
    glob came to disagree with the classifier about which files exist - a file in a
    subdirectory stopped being swept and nothing went red.

    The development modules whose cases live in `tests/` (`tools/lints/`, the demo
    generators and the two benchmarks) are left out: they answer no `--selftest`, and
    `coverage_findings` is what accounts for them.
    """
    repo = repo or REPO
    out = []
    for rel_dir in SWEEP_DIRS:
        directory = os.path.join(repo, rel_dir)
        if not os.path.isdir(directory):
            continue
        for rel, _path in _output.py_files(directory):
            out.append("%s/%s" % (rel_dir.replace(os.sep, "/"), rel))
    elsewhere = set(_output_lints.suite_elsewhere_paths(repo))
    return sorted(p for p in out if p not in elsewhere)


# WHERE A SUITE USED TO LIVE, and may not again. The suites left the plugin because the
# installed copy of it must carry none, so a `.py` that reappears under the old
# directory is a suite that ships in every install AND one this sweep no longer
# walks: green, and not run. A directory that is only listed in `SWEEP_DIRS` cannot
# say that - a walk that does not look somewhere reports nothing about it - so the
# retired roots are named and asked about directly.
RETIRED_SUITE_DIRS = (
    os.path.join("plugins", "audit", "tests"),
)


def retired_suite_files(repo):
    """Every `.py` still (or again) under a `RETIRED_SUITE_DIRS` root, repo-relative.

    A retired directory that is merely EMPTY is not a finding: an installed copy
    left behind by a checkout that predates the move holds `__pycache__` and
    nothing else, and a lint that fired on it would be one the next maintainer
    deletes.

    `repo` is REQUIRED, and not for tidiness: a function that takes no argument
    and walks the tree is read by `prove-gates.py` as a load-bearing gate owing
    rows in both of its tables, and this is a precondition `main()` refuses on,
    not a lint the tree's own rules grade.
    """
    out = []
    for rel_dir in RETIRED_SUITE_DIRS:
        directory = os.path.join(repo, rel_dir)
        if not os.path.isdir(directory):
            continue
        for rel, _path in _output.py_files(directory):
            out.append("%s/%s" % (rel_dir.replace(os.sep, "/"), rel))
    return sorted(out)


def retired_suite_refusal(retired):
    """The refusal naming `retired` (`retired_suite_files()`'s answer), or None
    when there is nothing under a retired directory."""
    if not retired:
        return None
    return ("sweep-selftests: %s - a `.py` under a directory suites left, which "
            "this sweep does not walk, so it would be green and never run; move "
            "it under %s" % (", ".join(retired), ", ".join(
                d.replace(os.sep, "/") for d in SWEEP_DIRS)))


def coverage_findings(coverage=None):
    """`(findings, total)`: one line per module the repository carries without a suite
    of its own and without a named exemption, and how many modules were looked at.

    THIS IS THE SWEEP'S HALF OF THE SHIPPED PLUGIN. It does not run a shipped module
    and does not read one for a contract line; it asks `selftest_coverage()` - the one
    classifier - and reports every defect class it names (`uncovered`, `stale_exempt`,
    `orphans`, `collisions`). `total` rides with the findings so that "no findings"
    and "looked at nothing" cannot read the same: `main` refuses a total of zero.

    `coverage` is the classifier's answer, handed in by a case that builds a tree of
    its own; None asks about this checkout.
    """
    found = coverage if coverage is not None else _output_lints.selftest_coverage()
    return list(found["defects"]), found["total"]


# --- the scratch directory a child is run in ----------------------------------
# A suite reached outside its own temp directory and destroyed what was there.
# The suite that was blamed had no `subprocess` in it at all - what it had was a
# fixture root allocated with `tempfile.mkdtemp()` and never removed. That is
# invisible on a developer's machine, because `mkdtemp` answers to `TMPDIR` and
# `TMPDIR` is the system temp, where a stray `.git/` and `docs/` tree joins
# thousands of others. Point `TMPDIR` at the directory you are working in - which an
# agent sandbox does, and which this runner now does deliberately - and the same
# suite deposits a git repository beside your files and leaves it there.
#
# THE FILE PLACED BEFORE THE RUN IS THE DESTRUCTIVE HALF. A directory checked only
# for strays reports a suite that DELETED what was already in it as perfectly clean,
# and deleting a developer's work is the sharper of the two failures. So something
# is put there first, and it has to come back with its bytes intact.
SENTINEL = "left-by-the-runner"
SENTINEL_BYTES = b"a selftest must not write outside the fixtures it makes itself\n"

# Every variable a temp allocator reads. All three, because `tempfile` reads TMP and
# TEMP on windows and TMPDIR everywhere else, and a variable left unpinned is a
# lookup that quietly finds the shared directory again.
TEMP_VARS = ("TMPDIR", "TMP", "TEMP")

# ...and every variable that answers "where does this user keep their things". The
# reasoning for each is in `home_env`, which is also where the windows pair that
# cannot simply be listed gets derived.
HOME_VARS = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
             "XDG_CACHE_HOME", "XDG_STATE_HOME", "APPDATA", "LOCALAPPDATA")


def home_env(home):
    """`home` under every name a home-directory lookup reads.

    ONE SETTING IS NOT ENOUGH, which is the whole reason this is a table rather than
    a line. `HOME` alone leaves the `XDG_*` roots pointing at the real home on linux
    - they are set independently there - `USERPROFILE` pointing at it on windows,
    and `HOMEDRIVE`/`HOMEPATH`, which git for windows joins by hand, pointing at it
    on both. Each of those is a lookup that walks straight past the directory this
    runner is watching, and the suites run on ubuntu AND windows.

    THE WINDOWS PAIR IS DERIVED FROM THE PATH rather than listed, so the two halves
    cannot disagree: joining them gives `home` back by construction. On POSIX the
    split yields an empty drive and the whole path, and nothing reads either name
    there - setting them is inert rather than wrong, and one code path beats a
    platform branch nobody runs on the other platform.
    """
    out = dict((name, home) for name in HOME_VARS)
    drive, tail = os.path.splitdrive(home)
    out["HOMEDRIVE"] = drive
    out["HOMEPATH"] = tail
    return out


# --- what a child inherits from the caller, which is not a directory ----------
# THE DIRECTORIES ABOVE WERE NOT THE WHOLE OF THE AMBIENT STATE. The rest of the
# caller's environment went through untouched, and what was in it made a local
# sweep green over suites CI's ubuntu runner turned red: the Claude session a sweep
# is usually typed from, which the lock and journal code read as a live holder and
# an actor; git's SYSTEM configuration, which on a mac pins a default branch no bare
# runner has; and git's habit of guessing an identity from the hostname when none
# is configured, which a runner with no hostname identity refuses. A suite that
# leaned on any of them passed here and failed there.
#
# THE SESSION FAMILY IS DERIVED BY PREFIX, not listed, because the harness adds
# members to it and a list would be one release behind. The names outside the
# prefix are listed with their reason: `CLAUDECODE` is the harness's own marker that
# a process was spawned by it, and `AUDIT_LOCK_TOKENS` is how a lock holder hands
# its claims to its children - a sweep typed from inside a held run would hand
# every suite a claim it never took. Nothing is allowed through by name: CI's
# runners carry none of this family, and a suite that needs one of them sets it.
SESSION_PREFIX = "CLAUDE_"
SESSION_NAMES = ("CLAUDECODE", "AUDIT_LOCK_TOKENS")

# AN IDENTITY THE CALLER EXPORTS IS AMBIENT TOO. Refusing git's guess closes only
# half of it: a developer with one of these exported hands every suite an identity
# a bare runner never has, and a suite that commits without configuring its own
# goes green here and red there. The list is the "Git Commits" section of `git(1)`,
# exactly - the other `GIT_*` names (`GIT_DIR`, `GIT_TERMINAL_PROMPT`, ...) are not
# identity and pass through. Only what THIS runner inherits is filtered: a suite
# that sets one of these for its own child builds that child's environment itself.
GIT_IDENTITY_NAMES = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
                      "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
                      "GIT_COMMITTER_DATE", "EMAIL")

# NO DEFAULT BRANCH AND NO IDENTITY ARE PINNED, deliberately. Refusing the host's
# answers is the whole move; supplying the runner's own would hide a suite that
# still leans on the host behind a value only this runner provides. The host's
# global config is out of reach already - HOME is a scratch directory with no
# `.gitconfig` in it. `GIT_CONFIG_COUNT` rather than a file planted in that home,
# because a planted file is one more thing the home channel would have to excuse;
# the one git these pairs cannot reach gets a file outside it, below the table.
#
# NO BACKGROUND HOUSEKEEPING EITHER, and this is the one place that reaches every
# git a suite starts. A commit, merge or fetch ends by spawning a DETACHED
# `git maintenance run --auto` that outlives the command, so it can still be
# working in a fixture repository while the suite reads or deletes it. A fixture
# prefix switches it off only for the suites that use the prefix, and many call
# bare `git`. `maintenance.auto` stops the spawn - `gc.auto` alone does not - and
# `gc.auto` stops the direct `gc --auto` an older git runs instead. The protocol
# these pairs travel by is read by git 2.31 and later; the selftest asks the
# child's own git to read `maintenance.auto` back, so a runner with an older git
# fails there rather than housekeeping in silence.
GIT_ENV = (("GIT_CONFIG_NOSYSTEM", "1"),
           ("GIT_CONFIG_COUNT", "3"),
           ("GIT_CONFIG_KEY_0", "user.useConfigOnly"),
           ("GIT_CONFIG_VALUE_0", "true"),
           ("GIT_CONFIG_KEY_1", "maintenance.auto"),
           ("GIT_CONFIG_VALUE_1", "false"),
           ("GIT_CONFIG_KEY_2", "gc.auto"),
           ("GIT_CONFIG_VALUE_2", "0"))

# THE CALLER'S OWN PAIRS IN THAT PROTOCOL ARE DROPPED before the runner's are laid
# on, so the runner's set is the whole of it. Overwriting alone would win every
# index the runner writes and leave the caller's higher ones in the child, where a
# suite that appends a pair by raising the count would read them as its own.
_GIT_CONFIG_PAIR_RE = re.compile(r"^GIT_CONFIG_(?:COUNT|KEY_\d+|VALUE_\d+)$")

# THE ONE GIT THAT SET NEVER REACHES: receive-pack, on a push to a local path.
# git's local transport clears `GIT_CONFIG_COUNT` and `GIT_CONFIG_PARAMETERS`
# before it starts the remote side, so the receiving repository ends the push
# with a detached `git maintenance run --auto` the pairs above were meant to stop
# - traced on git 2.53, the push's own `-c` switches lost the same way. A file
# named by `GIT_CONFIG_GLOBAL` does reach it, so the runner writes one per child
# holding `receive.autogc=false`, the key receive-pack itself reads before it
# starts any housekeeping (the same trace: that key alone took the spawn to zero).
#
# THAT KEY ALONE, not the pairs' keys copied in. Every other git is already
# switched off by the pairs, and a suite that measures its own fixture prefix
# takes the pairs out to see the spawn its deny twin needs; a second copy of
# `maintenance.auto` here would switch that twin off behind its back.
#
# IN A DIRECTORY OF ITS OWN, OUTSIDE BOTH WATCHED CHANNELS, which is the half
# the comment above this table turned down when it chose the pairs over a file
# planted in the child's home. And the file is checked back afterwards the way a
# channel's planted file is: with it in place, a suite's `git config --global`
# writes here instead of into the watched home, and an unchecked file would be a
# leak the home channel used to catch going quiet.
#
# A SUITE THAT POINTS `GIT_CONFIG_GLOBAL` ELSEWHERE for its own git wins for that
# git, as it should - the pairs above still reach every git that is not a local
# push's receiving side, and the suite has chosen what its push side reads.
GIT_GLOBAL_CONFIG_NAME = "config"
GIT_GLOBAL_CONFIG = b"[receive]\n\tautogc = false\n"
GIT_GLOBAL_CHANNEL = "git global config"


def is_session_var(name):
    """True when `name` is the Claude session's, and a child must not see it."""
    return name.startswith(SESSION_PREFIX) or name in SESSION_NAMES


def is_ambient_identity(name):
    """True when `name` hands git an identity a bare runner would not have."""
    return name in GIT_IDENTITY_NAMES


def is_ambient_git_config(name):
    """True when `name` carries a config pair the caller set through git's
    environment protocol, which the runner's own set replaces whole."""
    return bool(_GIT_CONFIG_PAIR_RE.match(name))


def ambient_env(environ):
    """The caller's environment minus the session, any exported git identity and
    any git config pairs of its own, with git's host answers refused and its
    background housekeeping off.

    A NEW MAPPING, never the caller's: `run_one` layers the directory pins on top of
    this, and the process's own environment is shared with every other thread of
    the sweep.
    """
    out = dict((k, v) for k, v in environ.items()
               if not is_session_var(k) and not is_ambient_identity(k)
               and not is_ambient_git_config(k))
    out.update(GIT_ENV)
    return out


def git_global_env(root):
    """`GIT_CONFIG_GLOBAL` pointed at the runner's own config, written into `root`.

    `root` is a directory this runner allocated for the file alone, so what
    `git_global_debris` reads back afterwards is this file and nothing else.
    """
    path = os.path.join(root, GIT_GLOBAL_CONFIG_NAME)
    with io.open(path, "wb") as fh:
        fh.write(GIT_GLOBAL_CONFIG)
    out = {}
    out["GIT_CONFIG_GLOBAL"] = path
    return out


def git_global_debris(root):
    """What a run did to the runner's global git config, each finding naming it.

    `scratch_debris` with the config file as the planted one, so a suite that ran
    `git config --global`, or deleted the file, is named in the same three words a
    watched channel's findings use.
    """
    return ["%s: %s" % (GIT_GLOBAL_CHANNEL, finding) for finding in
            scratch_debris(root, GIT_GLOBAL_CONFIG_NAME, GIT_GLOBAL_CONFIG)]


def scratch_debris(root, sentinel=SENTINEL, expected=SENTINEL_BYTES):
    """What a run left in, took from, or rewrote about its scratch directory.

    An observation, not a verdict - `grade()` decides what it means, for the same
    reason `run_one` and `grade` were split in the first place.

    Every one of the three findings is spelled differently on purpose. "left a
    fixture behind", "deleted a file that was already here" and "rewrote a file that
    was already here" are three different bugs with three different repairs, and a
    checker that collapsed them into "dirty" would send every reader to look for a
    leak.
    """
    try:
        left = sorted(os.listdir(root))
    except OSError as exc:
        return ["its scratch directory is unreadable afterwards: %s" % (exc,)]
    found = []
    if sentinel not in left:
        found.append("DELETED %s, which was there before it ran" % (sentinel,))
    else:
        body, why = None, None
        try:
            body = io.open(os.path.join(root, sentinel), "rb").read()
        except OSError as exc:
            why = "made %s unreadable: %s" % (sentinel, exc)
        if why is not None:
            found.append(why)
        elif body != expected:
            found.append("REWROTE %s, which was there before it ran" % (sentinel,))
    # THE NARROWING, and the one thing an over-firing version of this check gets
    # wrong: the runner's own file is not debris. Stop excluding it and every clean
    # suite in the tree is reported as having dirtied its directory - which is what
    # the ALLOW row in `tools/prove-gates.py` weakens this line to prove.
    strays = [name for name in left if name != sentinel]
    if strays:
        found.append("left behind: %s" % (", ".join(strays),))
    return found


# --- removing that directory ---------------------------------------------------
# The fact is that git writes its loose objects READ-ONLY, so on windows the
# ordinary removal call cannot unlink them - and every caller here spells it
# `ignore_errors=True`, which means the removal had never worked there and nothing
# said so. `_output.remove_tree()` in the scripts anchor is where that fact lives,
# with the measurement that chose it; `_harness` binds its own name to that function
# rather than holding a body, and so does this runner.
#
# THIS RUNNER USED TO KEEP A COPY. It was written while the home was
# `tests/_harness.py`, a file this sweep RUNS and so may not import to start: a
# harness with a syntax error would have arrived as a traceback out of this module
# instead of as one failing row. The home is the anchor now, which this runner
# imports above to start at all, so the reason for a copy is gone and so is the copy
# - a body kept beside its home with nothing comparing the two is a fork waiting.
remove_tree = _output.remove_tree


# The two watched directories, and the word a finding about each opens with. They
# are kept apart for the reason `scratch_debris` spells its three findings three
# ways: "it wrote where it was launched" and "it wrote into the home directory it
# was given" are two different bugs with two different repairs, and a reader who
# cannot tell them apart goes looking for the wrong one first.
CHANNELS = ("working directory", "home directory")


def child_debris(work, home):
    """What a run left in EITHER watched directory, each finding naming its channel.

    One walk per channel and one list out, because `grade` judges the run and not
    the directory: a suite is red if it wrote outside the fixtures it makes for
    itself, wherever it did it.
    """
    out = []
    for label, root in zip(CHANNELS, (work, home)):
        out.extend("%s: %s" % (label, finding) for finding in scratch_debris(root))
    return out


# --- running (impure) and grading (pure) --------------------------------------
def spaced_layout(holder):
    """`(scratch, interpreter)` built inside `holder` for the spaced leg.

    `scratch` holds a space and is reached THROUGH a symlink (`holder/via` ->
    `holder/real`), so its resolved spelling is `holder/real/...`: the link's name
    is not a suffix of the target's, the opposite of `/tmp` -> `/private/tmp`.
    `interpreter` is a symlink to `sys.executable` under a directory that holds a
    space, which keeps a virtualenv's behaviour (the environment is found from the
    path the interpreter was started by, not from where the link points).
    Raises OSError where symlinks cannot be made.
    """
    real = os.path.join(holder, "real")
    os.makedirs(real)
    os.symlink(real, os.path.join(holder, "via"))
    scratch = os.path.join(holder, "via", "s p")
    os.makedirs(scratch)
    pydir = os.path.join(holder, "py dir")
    os.makedirs(pydir)
    interpreter = os.path.join(pydir, "python3")
    os.symlink(sys.executable, interpreter)
    return scratch, interpreter


# What `open()` and `subprocess(text=True)` consult when no encoding is named is the
# locale's preferred encoding, not PYTHONIOENCODING. C locale plus the UTF-8 mode
# switched off makes it ASCII on POSIX - and on linux it makes the FILESYSTEM
# encoding ASCII too, while macOS keeps UTF-8 file names under it, as windows
# does. Windows legs already run under a legacy code page and are left as they are.
LEGACY_LOCALE_VARS = {"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0"}
LOCALE_PROBE = ("import locale, sys; "
                "print(locale.getpreferredencoding(False)); "
                "print(sys.getfilesystemencoding())")


def host_os():
    """The one place the machine running the sweep names itself; everything
    below takes an `os_name` and `main` hands this in."""
    return os.name


def locale_pins(os_name, encoding, locale_vars=None):
    """The environment additions a `--encoding` pass makes: the child's stdio
    codec everywhere, plus the locale pins `locale_vars` names - which, when
    it is None, are `LEGACY_LOCALE_VARS` on POSIX and none on windows, and
    when it is empty are none, which is what `locale_decision` hands a
    platform the pins would misrepresent.

    A function of the `os_name` it is asked about and never of the machine
    running it; the host's own value is passed in once, from `main`."""
    if not encoding:
        return {}
    pins = {"PYTHONIOENCODING": encoding}
    if locale_vars is not None:
        pins.update(locale_vars)
    elif os_name != "nt":
        pins.update(LEGACY_LOCALE_VARS)
    return pins


def _is_utf8(name):
    return name.lower().replace("-", "").replace("_", "") in ("utf8", "utf8sig")


def _spelled(locale_vars):
    return " ".join("%s=%s" % kv for kv in sorted(locale_vars.items()))


def locale_decision(os_name, reported, encoding, locale_vars=None):
    """`{"locale", "problem", "line"}` - what a `--encoding` pass pins, given
    what a child under the pins `reported` as `(preferred, filesystem)`.

    PURE, so every platform's answer is a case on any one of them. `locale` is
    the pins to hand `locale_pins` (empty: none); `problem` refuses the pass,
    else None; `line` is the sentence the run prints saying which half ran and
    why. Kept only where the pin is FAITHFUL to the platform it stands for - a
    non-UTF-8 preferred encoding with UTF-8 file names. A pin that also makes
    file names non-UTF-8 is stricter than any runner and wrong: the stdio half
    runs alone there, and the line says so. A preferred encoding still UTF-8
    under the pins is a pass that would claim a legacy encoding it never had,
    and is refused.
    """
    pinned = LEGACY_LOCALE_VARS if locale_vars is None else locale_vars
    if os_name == "nt":
        return {"locale": {}, "problem": None,
                "line": "encoding pass: only the stdio half was set (codec %s) - "
                        "windows is given no locale pins and is not asked; its "
                        "children run under the code page the system gives "
                        "them" % (encoding,)}
    preferred, filesystem = reported
    if _is_utf8(preferred):
        return {"locale": {}, "line": "",
                "problem": "could-not-run: a legacy-encoding pass needs children "
                           "whose preferred encoding is not UTF-8, and the probe "
                           "saw %s under %s" % (preferred, _spelled(pinned))}
    if not _is_utf8(filesystem):
        return {"locale": {}, "problem": None,
                "line": "encoding pass: only the stdio half ran (codec %s) - "
                        "under %s a child reported filesystem encoding %s as "
                        "well as preferred encoding %s, and a pin that makes "
                        "file names non-UTF-8 stands for no platform this pass "
                        "simulates, so the locale is not pinned"
                        % (encoding, _spelled(pinned), filesystem, preferred)}
    return {"locale": dict(pinned), "problem": None,
            "line": "encoding pass: both halves ran - stdio codec %s, and the "
                    "locale pinned (%s), under which a child reported "
                    "preferred encoding %s and filesystem encoding %s"
                    % (encoding, _spelled(pinned), preferred, filesystem)}


def legacy_locale_verdict(environ=None, locale_vars=None, interpreter=None,
                          encoding="cp1252", os_name=None):
    """`locale_decision`'s answer for a child of this machine, plus `reported`:
    the `(preferred, filesystem)` pair it gave, or None where none was asked.

    ASKED, not assumed: a pass that claims a legacy encoding while its children run
    UTF-8 is the silent pass this exists to end, and one that pins a platform no
    runner has is the loud wrong one. The probe sees the same filtered
    environment a suite does. Windows is not probed - it is not given the pins.
    A probe that cannot answer refuses the pass as could-not-run.
    """
    os_name = host_os() if os_name is None else os_name
    if os_name == "nt":
        return dict(locale_decision("nt", None, encoding, locale_vars),
                    reported=None)
    env = ambient_env(os.environ if environ is None else environ)
    env.update(locale_pins(os_name, encoding, locale_vars))
    try:
        done = subprocess.run([interpreter or sys.executable, "-c",
                               LOCALE_PROBE], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"locale": {}, "line": "", "reported": None,
                "problem": "could-not-run: the locale probe failed to run: %s"
                           % (exc,)}
    said = done.stdout.decode("utf-8", "replace").split()
    if done.returncode != 0 or len(said) != 2:
        return {"locale": {}, "line": "", "reported": None,
                "problem": "could-not-run: the locale probe exited %d and said "
                           "%r, not a preferred and a filesystem encoding"
                           % (done.returncode, " ".join(said))}
    reported = (said[0], said[1])
    return dict(locale_decision(os_name, reported, encoding, locale_vars),
                reported=reported)


def run_one(rel_path, repo=None, encoding=None, timeout=DEFAULT_TIMEOUT,
            pycache=None, environ=None, spaced=False, grant=1,
            locale_vars=None, os_name=None):
    """Run one file's `--selftest` in a scratch directory and report what happened.

    Split from `grade` on purpose: everything below this line is a decision about
    text and an exit code, and a decision that needs no subprocess is a decision a
    selftest can drive through every branch. That split is why this file can prove
    its own strictness instead of only being seen passing.

    THE CHILD'S CWD IS AN EMPTY DIRECTORY, NOT THE REPOSITORY. A suite has no
    business reading or writing the directory it was launched from, and running them
    all from the repository root is what let that go unnoticed - a fixture written
    relative to the cwd landed among the tracked tree and read as an ordinary
    working copy. It also means the sweep cannot damage the checkout it is testing.
    The path handed to the interpreter becomes absolute for the same move.

    AND `TMPDIR` IS PINNED TO THAT SAME DIRECTORY, which is the half that does the
    work. An empty cwd on its own catches nothing: fixtures here are allocated with
    `tempfile.mkdtemp()`, so a leaked one goes to the system temp and the cwd comes
    back spotless. All three spellings are set because CI runs this on windows,
    where `tempfile` reads `TMP` and `TEMP` rather than `TMPDIR`.

    THE HOME DIRECTORY IS A SECOND SUCH DIRECTORY, watched the same way and reported
    under its own channel. It is allocated BESIDE the working one rather than
    inside it: nesting would add two characters to the root of every fixture path a
    child builds, and windows still refuses a path past its own limit - the deepest
    fixture in this tree is a git object under a linked worktree.

    AND `PYTHONPYCACHEPREFIX` POINTS AT NEITHER. An interpreter writes bytecode
    where its own configuration says, and macOS's system python says "under the
    HOME I was given" - so without this a child that merely started a grandchild
    named `python3` would be convicted of leaking. `pycache` is threaded from the
    caller so one run shares one cache; a call that passes none gets its own and
    pays a cold compile, which is right for the handful of direct calls in the
    cases below and wrong for a sweep of the whole tree.

    AND WHAT IS NOT A DIRECTORY IS FILTERED TOO. `ambient_env` drops the Claude
    session's variables and any git identity the caller exports, and refuses git's
    system config and its guessed identity,
    so a suite sees what a bare runner shows it. `GIT_CONFIG_GLOBAL` names a
    file of this runner's in a directory of its own, the one switch a local
    push's receiving side still reads, and the file is checked back afterwards. `environ` is the caller's
    environment, threaded rather than read so a case can plant a session variable
    without writing to the process's own.

    stderr is folded into stdout (`2>&1`, as both old copies did) so a traceback
    lands in the same stream as the contract line, in order. Bytes are decoded with
    `replace`: under `--encoding cp1252` the child deliberately writes a legacy code
    page, and a runner that died decoding its output would be a runner that cannot
    run the pass it exists to run.

    AND THE CHILD IS TOLD WHAT IT HOLDS: `grant` slots of the sweep's budget in
    `STAGE_GRANT_VAR` and its `timeout` in `FILE_TIMEOUT_VAR`, set over whatever
    the caller's environment carried, so a staged suite sizes its block pool and
    its block timeouts from this run rather than from a sweep around this one.
    """
    repo = repo or REPO
    env = ambient_env(os.environ if environ is None else environ)
    env.update(locale_pins(host_os() if os_name is None else os_name,
                           encoding, locale_vars))
    env[STAGE_GRANT_VAR] = str(grant)
    env[FILE_TIMEOUT_VAR] = str(timeout)
    # A SHORT PREFIX, deliberately. This directory becomes the root of every fixture
    # path the child builds, and windows still refuses a path past its own limit -
    # the deepest fixture in this tree is a git object under a linked worktree.
    scratch = tempfile.mkdtemp(prefix="sw-")
    home = tempfile.mkdtemp(prefix="sh-")
    owned = [scratch, home]
    interpreter = sys.executable
    if spaced:
        # `scratch` becomes the HOLDER and the child's directory moves inside it, so
        # the one removal below takes the whole layout.
        try:
            holder = scratch
            scratch, interpreter = spaced_layout(holder)
        except OSError as exc:
            for root in owned:
                remove_tree(root)
            return {"path": rel_path, "code": None, "debris": [],
                    "output": "could not build the spaced layout: %s" % (exc,)}
    for name in TEMP_VARS:
        env[name] = scratch
    env.update(home_env(home))
    if pycache is None:
        pycache = tempfile.mkdtemp(prefix="sp-")
        owned.append(pycache)
    env["PYTHONPYCACHEPREFIX"] = pycache
    # PER CHILD, not shared like the cache prefix: a suite's `git config --global`
    # lands in this file, and a shared one would hand that write to every sibling.
    gitconf = tempfile.mkdtemp(prefix="sg-")
    owned.append(gitconf)
    env.update(git_global_env(gitconf))
    for root in (scratch, home):
        io.open(os.path.join(root, SENTINEL), "wb").write(SENTINEL_BYTES)
    argv = [interpreter, os.path.join(repo, rel_path), "--selftest"]
    began = time.monotonic()
    try:
        done = subprocess.run(argv, cwd=scratch, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
        code = done.returncode
        output = done.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        code, output = None, "did not finish within %ds" % (timeout,)
    except OSError as exc:
        code, output = None, "could not be started: %s" % (exc,)
    seconds = time.monotonic() - began
    # MEASURED BEFORE THE REMOVAL, so what the child left is read rather than
    # inferred from a cleanup that may itself have failed.
    debris = child_debris(scratch, home) + git_global_debris(gitconf)
    # THE COPY OF THE REMOVAL HELPER, not a plain `rmtree`. A child that built a
    # git fixture in here left loose objects that windows will not unlink, and the
    # plain call - which every caller spells `ignore_errors=True` - would leave the
    # tree behind and say nothing. This run is usually one already reported red, so
    # the leftover would land in the system temp rather than in anybody's working
    # directory; that is a reason to be quiet about it, not a reason to leave it.
    # EVERY directory this run allocated, not just the scratch: the home and the
    # bytecode prefix are watched too, and leaving them is the leak the guard
    # beside this line reports. `remove_tree` rather than a plain call, because a
    # child that built a git fixture left loose objects windows will not unlink.
    for root in owned:
        remove_tree(root)
    return {"path": rel_path, "code": code, "output": output, "debris": debris,
            "seconds": seconds, "grant": grant, "timeout": timeout}


def cases_in(output):
    """How many cases the contract claims, or None if it makes no claim.

    The LAST match, not the first: CI read `tail -1` and then grepped it, so a file
    printing a per-section line before its total would have had the total counted.
    Reading the last match keeps that answer and stops depending on the total being
    physically last.
    """
    found = CONTRACT.findall(output or "")
    if not found:
        return None
    return int(found[-1][0])


def grade(rel_path, code, output, debris=()):
    """The verdict for one run, as a pure function of what the run produced.

    ONE GRADE FOR EVERY LEG. A forced codec or a spaced path changes what a child
    runs under, never the rules its run is read by, so this takes no word about
    the leg. The codec leg used to drop the contract, on the reasoning that it asked
    only whether a file could print; but a suite that catches its own
    `UnicodeEncodeError` and exits 0 without its contract IS that failure, and a
    grade without the contract called it green. Every file is run on every leg, so
    the stricter grade narrows nothing the codec leg reached.

    The rules, and the strictest reading of each of the two old copies:

      * a run that WROTE OUTSIDE ITS OWN FIXTURES - into the directory it was
        launched from, or into the home directory it was handed - is red whatever
        else it did. A suite that leaks a fixture leaks it on every leg, and there
        is no mode in which writing there is fine. It is
        read after the exit code because a suite that also went red has a traceback
        printed in full and a developer fixes that first; the leak is still waiting
        on the next run and this line still names it, and names WHICH of the two
        directories it landed in.
      * every file must exit 0 AND print the contract. This is the rule
        `verify.sh` did not have, and the reason a suite could be deleted from a
        file without anything going red locally.
    """
    def row(ok, why, cases=0):
        """One shape, built in one place, and it CARRIES the output it graded.

        Written as six dict literals first, and `render` then read an `output` key
        that only `sweep` bolted on afterwards - so a red row rendered through any
        other caller printed "(no output)" and hid the traceback. A row that leaves
        its evidence behind cannot develop that gap.
        """
        return {"path": rel_path, "ok": ok, "why": why, "cases": cases,
                "output": output}

    if code is None:
        return row(False, output)
    if code != 0:
        return row(False, "exited %d" % (code,))
    if debris:
        return row(False, "wrote outside the fixtures it makes for itself: %s"
                          % ("; ".join(debris),))
    claimed = cases_in(output)
    if claimed is None:
        return row(False, "no --selftest (every test and tool the sweep runs must "
                          "carry one)")
    return row(True, None, cases=claimed)


# --- the sweep ----------------------------------------------------------------
def default_jobs(cpus=None, environ=None):
    """All cores but two on a workstation, every core on a CI runner, never below one.

    Two are left for the machine that is also running an editor and a browser gate;
    below one is not a number of workers. A CI runner (`CI=true`, which GitHub
    Actions sets on every job) has nobody typing on it, and keeping two of its four
    cores idle is what made the windows leg print `2 workers` and take twice as long.
    """
    cpus = cpus if cpus is not None else (os.cpu_count() or 1)
    if on_ci(environ):
        return max(1, cpus)
    return max(1, cpus - 2)


def on_ci(environ=None):
    """True on a CI runner - `CI=true`, which GitHub Actions sets on every job."""
    environ = os.environ if environ is None else environ
    return environ.get("CI", "").strip().lower() == "true"


def sweep_deadline(environ=None):
    """`SWEEP_DEADLINE` on a CI runner, else None: the deadline exists to beat
    a job limit, and a workstation run has no runner to be killed by."""
    return SWEEP_DEADLINE if on_ci(environ) else None


def stage_grant(jobs):
    """The slots a staged suite holds out of a sweep's `jobs`: all but one, so
    the cheap files keep one lane while it runs, at least two and never more
    than `STAGE_GRANT_MAX` - and never more than the budget, so a one-worker
    bisect still runs it, its blocks one at a time."""
    return max(1, min(jobs, STAGE_GRANT_MAX, max(2, jobs - 1)))


def is_staged(source):
    """True when `source` hands its run to `staged_main` - a call to it, by
    name or as an attribute, read off the AST, so a docstring or a fixture
    string naming it does not count and a file that cannot parse is not one."""
    if "staged_main" not in source:
        return False
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name == "staged_main":
            return True
    return False


def staged_paths(paths, repo=None):
    """The subset of `paths` (repo-relative) that `is_staged`; a file that
    cannot be read is not one, and the sweep then runs it on one slot."""
    repo = repo or REPO
    found = set()
    for path in paths:
        try:
            with io.open(os.path.join(repo, path), encoding="utf-8",
                         errors="replace") as fh:
                source = fh.read()
        except (IOError, OSError):
            continue
        if is_staged(source):
            found.add(path)
    return found


def file_timeout(path, costs, floor=DEFAULT_TIMEOUT, slots=1, staged=False,
                 cap=None):
    """Seconds `path` may run when it holds `slots`: `TIMEOUT_PER_COST` times its
    recorded slot-seconds spread over those slots, never under `floor`, and
    never over `cap` when one is given.

    A file the table does not time is the stale-table case, and it must never
    be given LESS than a recorded file would: a staged suite (`staged`) with no
    entry gets the largest timeout any entry - a ghost's included, which is
    what a rename leaves behind - would get at the same slots, and an ordinary
    file the floor, which is what every untimed light file needs."""
    costs = costs or {}

    def calibrated(cost):
        return int(-(-TIMEOUT_PER_COST * cost // max(1, slots)))
    if path in costs:
        seconds = calibrated(costs[path])
    elif staged and costs:
        seconds = max(calibrated(c) for c in costs.values())
    else:
        seconds = floor
    seconds = max(floor, seconds)
    return seconds if cap is None else min(cap, seconds)


def slot_gate(slots):
    """`(wait, done)` over a budget of `slots`. `wait(ticket, weight)` returns
    once every lower ticket has been admitted and `weight` slots are free, and
    takes them; `done(weight)` gives them back.

    IN TICKET ORDER, never out of it. A cheap file allowed past a staged suite
    waiting for its slots would take the slot that suite was waiting on, and
    with enough cheap files behind it the suite would start last - the exact
    shape a costliest-first order exists to prevent. A weight above `slots`
    would wait forever, so it is read as `slots`."""
    cond = threading.Condition()
    state = {"free": slots, "turn": 0}

    def wait(ticket, weight):
        weight = min(weight, slots)
        with cond:
            while state["turn"] != ticket or state["free"] < weight:
                cond.wait()
            state["free"] -= weight
            state["turn"] += 1
            cond.notify_all()

    def done(weight):
        with cond:
            state["free"] += min(weight, slots)
            cond.notify_all()
    return wait, done


# --- shards: one leg split across several CI jobs -----------------------------
# A leg run as ONE job is as slow as the whole tree on one runner. `--shard I/N`
# runs the I-th of N parts, and the parts are built so that running all N runs
# every file exactly once (`sh0`) - whatever the cost table says, because the table
# only decides WHERE a file goes, never WHETHER. It also sets each file's timeout
# (`file_timeout`, above), so a stale table can cost balance and a timeout too
# tight for a file that grew past `TIMEOUT_PER_COST` times its entry, and never
# coverage. Staleness by omission costs neither a timeout nor a red sweep: an
# entry naming a file no longer swept is ignored by the split, a swept file with
# no entry is estimated for it and given a timeout no tighter than a recorded
# file of its kind (tt0), and `table_notes()` reports either as a note.
#
# BALANCED BY RECORDED COST, not by count. The staged suites take minutes while
# most files take a second, so an even count can put two of them in one part and
# leave that job the critical path of the whole run. The split is greedy
# least-loaded over the files heaviest first, which keeps the heaviest in different
# parts while there are parts to spare (`sh2`) and bounds any two parts' loads
# within the single costliest file (`sh3`).
#
# THE COSTS ARE RECORDED, NOT TYPED: `--record-costs .github/sweep-costs.json` writes
# what a run measured, per file, as SLOT-SECONDS - wall seconds times the slots of
# the budget the file held - so a staged suite weighs what it took out of a cell
# and not only how long it ran. They are one platform's seconds, the table's
# `platform` field says which, and it is recorded from windows because that
# platform binds: the split reads only how files compare to each other, which
# holds across machines far better than any one figure does, but a timeout
# reads the figure itself, and a darwin figure under-states a windows file.
# KEPT UNDER `.github/`, not beside this file: it is CI's input, and a table of
# repo paths under `tools/` would be read as basename references by `_refs`'
# tool-name lint, which resolves names against the plugin's trees alone.
COSTS_PATH = os.path.join(REPO, ".github", "sweep-costs.json")


def load_costs(path):
    """`({repo-relative path: seconds}, problem)` - problem is None when read.

    A missing or unreadable table is a problem the caller PRINTS, not a reason to
    refuse: every file then costs the same estimate and the split degrades to an
    even count, which still covers every file once."""
    try:
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError) as exc:
        return {}, "no cost table read from %s (%s)" % (path, exc)
    costs = data.get("costs") if isinstance(data, dict) else None
    if not isinstance(costs, dict) or not all(
            isinstance(v, (int, float)) for v in costs.values()):
        return {}, "%s carries no `costs` object of numbers" % (path,)
    return dict((k, float(v)) for k, v in costs.items()), None


def _median(costs):
    values = sorted(costs.values())
    return values[(len(values) - 1) // 2] if values else 1.0


def table_notes(costs, paths):
    """Advisory lines about a cost table against the swept `paths` - [] when it fits.

    What is wrong with a table here is a note to print, never a failure:
    entries naming a file no longer swept (ignored by the split), and a table
    timing too few of the swept files to balance by. Neither tightens a
    timeout - `file_timeout` gives an untimed file no less than a recorded one
    of its kind - so neither is a reason to turn a sweep red."""
    swept = set(paths)
    ghosts = sorted(set(costs) - swept)
    notes = []
    if ghosts:
        notes.append("%d cost entries name files no longer swept and are "
                     "ignored: %s" % (len(ghosts), ", ".join(ghosts[:5])
                                      + (" ..." if len(ghosts) > 5 else "")))
    timed = len(swept & set(costs))
    if swept and timed * 2 <= len(swept):
        notes.append("the cost table times only %d of %d swept files; the "
                     "rest are estimated at its median - re-record it with "
                     "--record-costs" % (timed, len(swept)))
    return notes


def _live(costs, paths):
    """`costs` restricted to `paths`: a ghost entry must not move the median."""
    swept = set(paths)
    return dict((k, v) for k, v in costs.items() if k in swept)


def cost_of(costs, path, estimate=None):
    """The recorded cost of `path`, or the table's median for a file never timed.

    The median and not zero: zero would make every new file free, and a split
    that thinks a file is free piles all of them into whichever part is lightest."""
    if path in costs:
        return costs[path]
    return _median(costs) if estimate is None else estimate


def run_order(paths, costs):
    """`paths` costliest first, ties by path - the order a shard submits them in,
    so its slowest suite starts at once and the rest fill the workers beside it."""
    costs = _live(costs, paths)
    estimate = _median(costs)
    return sorted(set(paths), key=lambda p: (-cost_of(costs, p, estimate), p))


def shard_paths(paths, costs, count):
    """`count` lists, each sorted, that partition `paths` - part I-1 is shard I/N.

    Greedy least-loaded over `run_order`, a tie going to the part holding fewer
    files and then to the lower index, so the split is a function of the set of
    paths and the table alone. The file-count tie-break is what keeps a part from
    staying empty when costs round to zero."""
    costs = _live(costs, paths)
    estimate = _median(costs)
    loads = [0.0] * count
    parts = [[] for _ in range(count)]
    for path in run_order(paths, costs):
        at = min(range(count), key=lambda k: (loads[k], len(parts[k]), k))
        parts[at].append(path)
        loads[at] += cost_of(costs, path, estimate)
    return [sorted(part) for part in parts]


def parse_shard(text):
    """`(index, count)` for `I/N` with 1 <= I <= N, else None."""
    match = re.match(r"^([0-9]+)/([0-9]+)$", text or "")
    if not match:
        return None
    index, count = int(match.group(1)), int(match.group(2))
    if count < 1 or not 1 <= index <= count:
        return None
    return index, count


def costs_from_rows(rows):
    """{path: slot-seconds, rounded} for every row a run timed - its wall seconds
    times the slots it held, so a staged suite's cost is what it took out of
    the budget and not only how long it ran; an exempt row has none."""
    return dict((r["path"], round(r["seconds"] * (r.get("grant") or 1), 1))
                for r in rows if r.get("seconds") is not None)


def record_costs(path, rows, swept, jobs, platform=None):
    """Write the cost table: this run's timings over the table already at `path`,
    keeping only files the sweep still reaches, so one shard's run refreshes its
    own files and a deleted file leaves the table. `platform` is where the
    timings were taken - this machine's unless they were read off another's
    log."""
    old, _problem = load_costs(path)
    merged = dict((k, v) for k, v in old.items() if k in swept)
    merged.update(costs_from_rows(rows))
    data = {"about": "Per-file slot-seconds of each `--selftest` - wall "
                     "seconds times the slots of the sweep's budget the file "
                     "held - written by "
                     "`python3 tools/sweep-selftests.py --record-costs "
                     ".github/sweep-costs.json`, or from a saved windows CI "
                     "log with `--costs-from-log`. `--shard` reads how files "
                     "compare, to balance the parts, and each file's timeout "
                     "is a multiple of its own figure; re-record when the "
                     "split it prints looks lopsided or a file has grown.",
            "platform": platform or sys.platform, "workers": jobs,
            "costs": merged}
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, indent=1, sort_keys=True) + "\n")


def exempt_row(rel_path, reason):
    """The row for a file the spaced leg does not run: ok, no cases, the reason."""
    return {"path": rel_path, "ok": True, "why": None, "cases": 0,
            "output": "", "exempt": reason}


def sweep(paths, jobs=None, repo=None, encoding=None,
          timeout=DEFAULT_TIMEOUT, spaced=False, exempt=None, costs=None,
          deadline=None, locale_vars=None, os_name=None):
    """Run every path and return one graded row per file, sorted by path.

    `locale_vars` is the encoding pass's locale pins as `locale_decision`
    settled them, handed to every child (`locale_pins`).

    `costs` orders the submissions (`run_order`) and sets each file's timeout
    (`file_timeout`); each row carries the `seconds` its child took, which
    `--record-costs` writes down, and the slots it held (`grant`). `deadline`,
    seconds from this call, cuts each file's timeout to what is left of it when
    the file is admitted, so a file that hangs is named by then however late it
    started (`sweep_deadline`).

    `exempt` is the spaced leg's table, `SPACED_EXEMPT` unless a caller hands
    one in; it is read on the spaced leg only.

    Sorted on the way out rather than printed on the way in: completion order is
    whatever the scheduler decided this run, and a log that reorders itself between
    two green runs cannot be diffed.

    ONE BYTECODE CACHE FOR THE WHOLE RUN, allocated here and removed here.
    `run_one` sends every child's cache outside both watched directories, and a
    per-child one would mean every file in the tree compiling the same import graph
    from source. Shared, the compile lands on whichever child reaches a module
    first. CPython writes a `.pyc` through a temporary file and a rename, so the
    workers can share it without a lock.
    """
    jobs = jobs or default_jobs()
    rows = []
    if not spaced:
        exempt = {}
    elif exempt is None:
        exempt = SPACED_EXEMPT
    rows.extend(exempt_row(p, exempt[p]) for p in paths if p in exempt)
    paths = [p for p in paths if p not in exempt]
    order = run_order(paths, costs or {})
    staged = staged_paths(order, repo)
    grant = stage_grant(jobs)
    wait, done = slot_gate(jobs)
    started = time.time()

    def admitted(ticket, path):
        weight = grant if path in staged else 1
        wait(ticket, weight)
        left = (None if deadline is None
                else max(1, int(deadline - (time.time() - started))))
        try:
            return run_one(path, repo, encoding,
                           file_timeout(path, costs, timeout, weight,
                                        staged=path in staged, cap=left),
                           pycache, None, spaced, weight,
                           locale_vars=locale_vars, os_name=os_name)
        finally:
            done(weight)
    pycache = tempfile.mkdtemp(prefix="sp-run-")
    try:
        with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            # COSTLIEST FIRST, so the slowest suite is never the last one
            # started, and admitted through ONE budget in that order.
            pending = [pool.submit(admitted, i, p) for i, p in enumerate(order)]
            for fut in futures.as_completed(pending):
                ran = fut.result()
                graded = grade(ran["path"], ran["code"], ran["output"],
                               debris=ran["debris"])
                rows.append(dict(graded, seconds=ran.get("seconds"),
                                 grant=ran.get("grant"),
                                 timeout=ran.get("timeout")))
    finally:
        shutil.rmtree(pycache, ignore_errors=True)
    return sorted(rows, key=lambda r: r["path"])


def _render_tail(rows, bad, total_cases, out):
    """Every failure IN FULL, the fail list, then the one-line summary.

    Shared by `render` and `render_quiet`: both grade the same rows, and this
    is the tail either form reads off them once the inventory line above it -
    loud or none - has been decided. That order is not cosmetic: `verify.sh`
    shows `tail -12` of a failed step, so the last lines have to be the ones
    that say what broke. Full output goes above the summary because a step
    that hides its output in exactly the case you need it is worse than one
    that prints everything - CI's old comment says so, and this keeps that
    promise.
    """
    for row in bad:
        out.write("\n--- %s: %s ---\n" % (row["path"], row["why"]))
        out.write(row.get("output") or "(no output)")
        if not (row.get("output") or "").endswith("\n"):
            out.write("\n")
    out.write("\n")
    if bad:
        for row in bad:
            out.write("FAIL  %s: %s\n" % (row["path"], row["why"]))
    for row in rows:
        if row.get("exempt"):
            out.write("EXEMPT %s: %s\n" % (row["path"], row["exempt"]))
    out.write("%d/%d files ok, %d cases\n"
              % (len(rows) - len(bad), len(rows), total_cases))
    return 1 if bad else 0


def _leg_label(encoding, spaced):
    """The heading a leg prints under, so two legs' logs are told apart.

    A leg run under BOTH conditions names both: the codec's heading alone would
    file a spaced, cp1252 run under the codec leg, and a red row there would be
    read as a codec fault when the path may be what broke it. Each single
    condition keeps the heading it always had."""
    parts = []
    if encoding:
        parts.append("encoding pass (%s)" % (encoding,))
    if spaced:
        parts.append("spaced sweep")
    return ", ".join(parts) or "sweep"


def render(rows, jobs, encoding=None, stream=None, spaced=False):
    """Print the table, then every failure IN FULL, then the summary. Returns exit.

    THE LOUD FORM, UNCHANGED: one line per file whatever it did, because a
    human bisecting a red run wants the inventory of every file the sweep
    touched and not only the ones that failed.
    """
    out = stream if stream is not None else sys.stdout
    bad = [r for r in rows if not r["ok"]]
    total_cases = sum(r["cases"] for r in rows)

    label = _leg_label(encoding, spaced)
    out.write("%s: %d files, %d workers\n" % (label, len(rows), jobs))
    for row in rows:
        if row.get("exempt"):
            out.write("  exempt  %-58s not run on this leg\n" % (row["path"],))
        elif row["ok"]:
            out.write("  ok      %-58s %d cases%s\n"
                      % (row["path"], row["cases"], timing(row)))
        else:
            out.write("  FAILED  %-58s %s%s\n"
                      % (row["path"], row["why"], timing(row)))
    return _render_tail(rows, bad, total_cases, out)


# The suffix `timing()` writes, as a pattern `costs_from_render()` reads back.
TIMING = re.compile(r"^  (?:ok|FAILED)  +(\S+) .*  \[([0-9.]+)s(?:, (\d+) slots)?\]$")


def timing(row):
    """`  [12.3s]` for a row a child ran - `  [12.3s, 3 slots]` when it held
    more than one - and nothing for a row with no measurement. Printed on the
    loud form so a CI log carries every file's seconds and can be recorded
    (`--costs-from-log`) without a second run."""
    if row.get("seconds") is None:
        return ""
    grant = row.get("grant") or 1
    return "  [%.1fs%s]" % (row["seconds"],
                            ", %d slots" % (grant,) if grant > 1 else "")


def costs_from_render(text):
    """{path: slot-seconds} read off the loud form's lines - the seconds times
    the slots printed beside them - for a log saved from a run elsewhere, a CI
    cell's. A FAILED line counts too: a timeout's seconds say how long the file
    was allowed, which is a floor for its cost. A file printed more than once -
    logs of two legs or two runs, read as one text - keeps its LONGEST timing,
    since the table sets timeouts and the slower run is the one they must fit."""
    found = {}
    for line in text.splitlines():
        # A CI log prefixes every line with a timestamp; the row starts after it.
        at = line.find("  ok  ")
        if at < 0:
            at = line.find("  FAILED  ")
        if at < 0:
            continue
        match = TIMING.match(line[at:].rstrip())
        if match:
            path = match.group(1).replace("\\", "/")
            seconds = round(float(match.group(2)) * int(match.group(3) or 1), 1)
            found[path] = max(seconds, found.get(path, seconds))
    return found


def render_quiet(rows, jobs, encoding=None, stream=None, spaced=False):
    """Print every failure, the totals, and nothing per passing file.

    Measured across this release's agent transcripts, shell output is the
    largest single source of material entering an agent's context, larger
    than every file read put together - and the loud form's one line per
    file, printed whether or not it has anything to say, is most of it. This
    is a second spelling of the same run and not a second run: `render` and
    this both grade the identical rows `sweep()` returned, so nothing here
    can change which files failed - only the inventory line above the tail
    either form shares through `_render_tail`.
    """
    out = stream if stream is not None else sys.stdout
    bad = [r for r in rows if not r["ok"]]
    total_cases = sum(r["cases"] for r in rows)

    label = _leg_label(encoding, spaced)
    out.write("%s: %d files, %d workers\n" % (label, len(rows), jobs))
    return _render_tail(rows, bad, total_cases, out)


def report_coverage(findings, accounted, named=None, out=None):
    """Print the coverage verdict and return its exit code: 1 when a module has no
    suite and no named exemption, else 0.

    ONE LINE WHEN CLEAN - what it looked at, so a pass names its subject - and one per
    finding otherwise, in the `FAIL  <what>: <why>` spelling the gate runner reads a red
    file by. A run NAMED to a handful of files asks nothing of the rest of the tree, so
    a path argument skips this verdict instead of failing a one-file run over a gap
    elsewhere; the full sweep, which is what CI and `verify.sh` run, always asks.
    """
    out = out if out is not None else sys.stdout
    if named:
        return 0
    if not findings:
        out.write("coverage: %d shipped and development modules, each with a suite "
                  "in tests/ or a named exemption\n" % (accounted,))
        return 0
    for line in findings:
        out.write("FAIL  coverage: %s\n" % (line,))
    out.write("coverage: %d finding(s) over %d modules - a module needs "
              "tests/test_<name>.py or a row in `COVERAGE_EXEMPT` saying why not\n"
              % (len(findings), accounted))
    return 1


# --- entry point --------------------------------------------------------------
def _flag_value(argv, name, fallback):
    """`--name X` or `--name=X`, or the fallback. Two spellings, one reader."""
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return fallback


# The flags that take a value, so the word after one is that value and never a
# suite path. A flag missing here would have its value read as a path and be
# refused by name, which is the loud direction to fail in.
VALUE_FLAGS = ("--encoding", "--timeout", "--jobs", "--shard", "--record-costs",
               "--costs-from-log", "--platform", "--workers")


def named_suites(argv, swept):
    """`(paths, refusal)` - the suites `argv` names, sorted and once each, `[]`
    when it names none (the whole tree runs), or `(None, why)`.

    ONE SPELLING: a repo-relative POSIX path, as `sweep_files()` prints it and as
    a listing's `{paths}` is filled. A path the sweep does not cover is REFUSED,
    every such path named - a name dropped and the rest run would report green
    over a suite that never ran, and the whole tree run in its place would be
    the silence this replaced, where every word after the flags was ignored.
    `--shard` splits the whole tree by cost, so with a list it has no meaning.
    """
    named, skip = [], False
    for arg in argv:
        if skip:
            skip = False
        elif arg in VALUE_FLAGS:
            skip = True
        elif not arg.startswith("-"):
            named.append(arg)
    known = set(swept)
    unknown = [p for p in named if p not in known]
    if unknown:
        return None, ("sweep-selftests: %s %s not a suite this sweep covers - "
                      "name a repo-relative path under %s, as `sweep_files()` "
                      "lists it; nothing was run"
                      % (", ".join(unknown), "is" if len(unknown) == 1 else "are",
                         ", ".join(d.replace(os.sep, "/") for d in SWEEP_DIRS)))
    if named and _flag_value(argv, "--shard", None) is not None:
        return None, ("sweep-selftests: --shard splits the whole tree and a "
                      "named list is already the part to run - pass one or the "
                      "other; nothing was run")
    return sorted(set(named)), None


def marker_gate(git_dir, out, err):
    """Exit code 2 when a mutating gate sweep holds the tree, else None.

    A live (or unreadable) marker refuses, because the tree is mid-mutation and every
    red this run printed would be about the mutation; a stale one is ignored on the
    record so a killed run does not wedge every sweep after it."""
    from _suite import marker_state
    seen = marker_state(git_dir)
    if seen["state"] == "live":
        err.write("sweep-selftests: refusing to start - %s says a mutating sweep "
                  "(pid %d, since %s) is rewriting the tree; a run now reads "
                  "mid-mutation files and reports false reds. Wait for it, or stop "
                  "it.\n" % (seen["path"], seen["pid"], seen["started"]))
        return 2
    if seen["state"] == "unreadable":
        err.write("sweep-selftests: refusing to start - %s exists but cannot be "
                  "read, so whether a mutating sweep is live is unknown; remove it "
                  "if none is.\n" % (seen["path"],))
        return 2
    if seen["state"] == "stale":
        out.write("sweep-selftests: ignoring stale marker %s (pid %d is gone, "
                  "started %s)\n" % (seen["path"], seen["pid"], seen["started"]))
    return None


def _positive(text):
    """`text` as a count of at least one, or None."""
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None
    return value if value >= 1 else None


def budget_line(paths, jobs, costs, floor, repo=None, deadline=None):
    """The one line saying how this run shares its budget, with the basis of
    each number: which files hold several slots, the longest timeout the cost
    table gave any file over the floor, and the deadline when one applies."""
    found = staged_paths(paths, repo)
    staged = sorted(found)
    grant = stage_grant(jobs)
    longest = max([file_timeout(p, costs, floor, grant if p in found else 1,
                                staged=p in found, cap=deadline)
                   for p in paths] or [floor])
    return ("budget: %d slots; %d staged suites hold %d each (%s); per-file "
            "timeout %ds, up to %ds for a file the cost table times as heavy%s\n"
            % (jobs, len(staged), stage_grant(jobs),
               ", ".join(os.path.basename(p) for p in staged) or "none",
               floor, longest,
               "" if deadline is None else
               "; every file named by %ds, the CI deadline" % (deadline,)))


def record_from_log(log, record, platform, workers):
    """Exit code of `--costs-from-log LOG`: the per-file seconds a saved loud
    log printed, merged into the table at `--record-costs` - which, with
    `--platform`, both being named, is required: a table whose timings came off
    another machine's log must say which one."""
    if not record or not platform:
        sys.stderr.write("sweep-selftests: --costs-from-log needs --record-costs "
                         "PATH and --platform NAME (the machine the log came "
                         "from)\n")
        return 2
    try:
        with io.open(log, encoding="utf-8", errors="replace") as fh:
            found = costs_from_render(fh.read())
    except (IOError, OSError) as exc:
        sys.stderr.write("sweep-selftests: cannot read %s: %s\n" % (log, exc))
        return 2
    if not found:
        sys.stderr.write("sweep-selftests: %s carries no timed row - nothing "
                         "recorded\n" % (log,))
        return 2
    rows = [{"path": p, "seconds": v} for p, v in sorted(found.items())]
    record_costs(record, rows, set(sweep_files()), workers, platform=platform)
    sys.stdout.write("recorded %d files' seconds from %s into %s (%s)\n"
                     % (len(rows), log, record, platform))
    return 0


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    from _suite import git_dir_of
    git_dir = git_dir_of(REPO)
    refused = marker_gate(git_dir, sys.stdout, sys.stderr) if git_dir else None
    if refused is not None:
        return refused
    encoding = _flag_value(argv, "--encoding", None)
    timeout = int(_flag_value(argv, "--timeout", DEFAULT_TIMEOUT))
    jobs = int(_flag_value(argv, "--jobs", default_jobs()))
    shard_text = _flag_value(argv, "--shard", None)
    shard = parse_shard(shard_text) if shard_text is not None else None
    if shard_text is not None and shard is None:
        sys.stderr.write("sweep-selftests: --shard takes I/N with 1 <= I <= N, "
                         "got %r\n" % (shard_text,))
        return 2
    record = _flag_value(argv, "--record-costs", None)
    from_log = _flag_value(argv, "--costs-from-log", None)
    if from_log is not None:
        return record_from_log(from_log, record,
                               _flag_value(argv, "--platform", None),
                               _positive(_flag_value(argv, "--workers", None)))
    # THE INVENTORY, MADE OPTIONAL. One line per file whether or not it has
    # anything to say is most of what this run puts into an agent's context;
    # `--quiet` keeps the failures and the totals and drops the rest. A human
    # bisecting a red run still has the loud form, unchanged, as the default.
    quiet = "--quiet" in argv
    spaced = "--spaced" in argv
    if spaced and os.name == "nt":
        sys.stderr.write("sweep-selftests: --spaced needs symlinks the Windows "
                         "runner does not grant; refusing rather than reporting "
                         "a leg that did not run\n")
        return 2

    refusal = retired_suite_refusal(retired_suite_files(REPO))
    if refusal:
        sys.stderr.write(refusal + "\n")
        return 2
    paths = sweep_files()
    findings, accounted = coverage_findings()
    if not paths:
        sys.stderr.write("sweep-selftests: found no .py under %s - refusing to "
                         "report a green sweep over nothing\n"
                         % (", ".join(SWEEP_DIRS),))
        return 2
    if not accounted:
        sys.stderr.write("sweep-selftests: the coverage classifier looked at NO "
                         "module, so a clean answer from it would assert nothing. "
                         "Ask `_output_lints.selftest_coverage()` why.\n")
        return 2
    named, refusal = named_suites(argv, paths)
    if refusal:
        sys.stderr.write(refusal + "\n")
        return 2
    costs, cost_problem = load_costs(COSTS_PATH)
    swept = set(paths)
    if named:
        paths = named
    for note in table_notes(costs, paths):
        sys.stdout.write("note: %s\n" % (note,))
    if shard is not None:
        index, count = shard
        whole = len(paths)
        paths = shard_paths(paths, costs, count)[index - 1]
        timed = len([p for p in paths if p in costs])
        # THE BASIS OF THE SPLIT, printed with it: which table, and how much of
        # this part it actually timed rather than estimated.
        sys.stdout.write("shard %d/%d: %d files of the %d swept, split by %s "
                         "(%d timed there, %d estimated at its median)\n"
                         % (index, count, len(paths), whole,
                            cost_problem or os.path.relpath(COSTS_PATH, REPO),
                            timed, len(paths) - timed))
        if not paths:
            sys.stderr.write("sweep-selftests: shard %d/%d holds no file - "
                             "refusing to report a green part over nothing\n"
                             % (index, count))
            return 2
    locale_vars = None
    os_name = host_os()
    if encoding:
        verdict = legacy_locale_verdict(encoding=encoding, os_name=os_name)
        if verdict["problem"]:
            sys.stderr.write("sweep-selftests: %s\n" % (verdict["problem"],))
            return 2
        # Which half of the pass runs here, and why, printed with it: a pass
        # narrowed to its stdio half is never a silent narrowing.
        sys.stdout.write("%s\n" % (verdict["line"],))
        locale_vars = verdict["locale"]
    deadline = sweep_deadline()
    sys.stdout.write(budget_line(paths, jobs, costs, timeout, deadline=deadline))
    rows = sweep(paths, jobs=jobs, encoding=encoding, timeout=timeout,
                 spaced=spaced, costs=costs, deadline=deadline,
                 locale_vars=locale_vars, os_name=os_name)
    if record:
        record_costs(record, rows, swept, jobs)
    code = (render_quiet if quiet else render)(rows, jobs, encoding=encoding,
                                               spaced=spaced)
    return max(code, report_coverage(findings, accounted, named))


# --- selftest -----------------------------------------------------------------
def _suite_root_cases(check):
    """Where the sweep looks for suites, and the directory it must never be asked to
    forget: the suites sit at the repository root, and a `.py` that shows up again
    under the retired plugin directory is refused by name."""
    swept = sweep_files()
    retired_prefix = "/".join(("plugins", "audit", "tests")) + "/"
    check("sr1 the sweep walks the suites at the repository root: `tests` is a "
          "swept directory, a real suite and the harness are in what it "
          "lists, and nothing it lists sits under the old plugin directory - "
          "a root that was renamed in SWEEP_DIRS but not on disk would list "
          "none of them: %r" % (SWEEP_DIRS,),
          "tests" in SWEEP_DIRS and retired_prefix.rstrip("/") not in
          [d.replace(os.sep, "/") for d in SWEEP_DIRS]
          and "tests/test__output.py" in swept and "tests/_harness.py" in swept
          and not [p for p in swept if p.startswith(retired_prefix)])

    # BUILT, NOT SPELLED: `tool_basename_drift` reads a `.py` basename literal under
    # `tools/` as a reference to a file that must exist, and this one exists only
    # for the width of the `try`.
    back_name = "test_back" + ".py"
    scratch = tempfile.mkdtemp(prefix="sweep-retired-")
    try:
        retired_dir = os.path.join(scratch, *retired_prefix.rstrip("/").split("/"))
        os.makedirs(os.path.join(retired_dir, "__pycache__"))
        with open(os.path.join(retired_dir, "__pycache__", "x.pyc"), "wb") as fh:
            fh.write(b"")
        quiet = retired_suite_files(scratch)
        with open(os.path.join(retired_dir, back_name), "w") as fh:
            fh.write("print('1/1 cases passed')\n")
        back = retired_suite_files(scratch)
        refusal = retired_suite_refusal(back)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    # THE ALLOW TWIN comes first in the label's logic: a directory that holds only
    # bytecode is an old checkout's leftover and must not be refused, or the rule
    # would be one a maintainer deletes the first time it fires on a stale cache.
    check("sr2 a retired suite directory that holds no `.py` is quiet, and one "
          "that holds a suite is REFUSED BY NAME - the file and the directories "
          "the suite belongs under are both in the message, and the sweep exits "
          "2 on it rather than running green over a file it never walks: "
          "%r / %r / %r" % (quiet, back, refusal),
          quiet == [] and retired_suite_refusal(quiet) is None
          and back == [retired_prefix + back_name]
          and refusal is not None and retired_prefix + back_name in refusal
          and "tests" in refusal and "never run" in refusal)

    real = retired_suite_files(REPO)
    check("sr3 THE LIVE CLAIM: this checkout holds no `.py` under the retired "
          "suite directory, so the refusal above is not already firing on the "
          "tree it protects: %r" % (real,), real == [])


def _cases(check):
    """Every branch of `grade` plus the two refusals, driven without a subprocess."""
    _suite_root_cases(check)
    live = "tests/test__output.py"

    g = grade(live, 0, "ALL PASS: 7/7 cases passed\n")
    check("g0 a live suite that exits 0 and prints the contract is ok, and its "
          "case count is READ rather than assumed: %r" % (g,),
          g["ok"] and g["cases"] == 7)

    g = grade(live, 0, "ran some things\n")
    check("g1 THE RULE verify.sh DID NOT HAVE: exit 0 with no contract is a "
          "FAILURE, not a pass - this is the case that let a suite be "
          "deleted with nothing going red locally: %r" % (g,),
          (not g["ok"]) and "no --selftest" in g["why"])

    # NO FILE IS CLASSIFIED MIGRATED. A development module whose cases live in
    # `tests/` used to be graded "ok, skipped" when it printed a pointer and no
    # contract; the sweep no longer runs such a file at all (`sweep_files` leaves it
    # out and `coverage_findings` accounts for it), so one that reaches `grade` with
    # a pointer and no contract is a file the sweep was never meant to run and is
    # red like any other. Named locals, because the prose scan reads this file.
    _moved = "cases moved to tests/\n"
    g = grade("tools/lints/_deps.py", 0, _moved)
    check("g2 a file with a pointer and no contract is RED and carries no `skipped` "
          "word - the `migrated` grade is gone, so a file that is not in the "
          "development-module set cannot hide behind it: %r" % (g,),
          (not g["ok"]) and "no --selftest" in g["why"] and "skipped" not in g)

    # THE SWEEP'S HALF OF THE SHIPPED PLUGIN, driven over trees of its own. A tree is
    # built per case and the classifier is asked about IT through its keyword
    # arguments, so the real checkout's answer cannot make a case green.
    # The fixture's module names are BUILT: `tool_basename_drift` reads a `.py` basename
    # written under `tools/` as a reference to a file that must exist.
    _ext = "." + "py"
    _na, _nl, _nh = "_a" + _ext, "lonely" + _ext, "h" + _ext
    _cov_root = tempfile.mkdtemp(prefix="sweep-coverage-")
    try:
        def _tree(shipped, hooks, tests):
            for sub_dir, names in (("scripts", shipped), ("hooks", hooks),
                                   ("tests", tests)):
                os.makedirs(os.path.join(_cov_root, sub_dir), exist_ok=True)
                for name in names:
                    with open(os.path.join(_cov_root, sub_dir, name), "w") as fh:
                        fh.write("\n")
            return dict(script_dir=os.path.join(_cov_root, "scripts"),
                        hooks_dir=os.path.join(_cov_root, "hooks"),
                        tests_dir=os.path.join(_cov_root, "tests"))
        _kw = _tree([_na, _nl], [_nh], ["test_" + _na, "test_" + _nh])
        _found, _total = coverage_findings(_output_lints.selftest_coverage(**_kw))
        _buf = io.StringIO()
        _code = report_coverage(_found, _total, out=_buf)
        _kw_ok = dict(_kw, exempt={"scripts/" + _nl: "no logic of its own"})
        _found_ok, _total_ok = coverage_findings(
            _output_lints.selftest_coverage(**_kw_ok))
        _buf_ok = io.StringIO()
        _code_ok = report_coverage(_found_ok, _total_ok, out=_buf_ok)
        _code_named = report_coverage(_found, _total, named=["tests/x" + _ext],
                                      out=io.StringIO())
    finally:
        shutil.rmtree(_cov_root, ignore_errors=True)
    check("g3 A SHIPPED MODULE WITH NEITHER tests/test_<name>.py NOR A NAMED "
          "EXEMPTION IS RED: the finding names the file in the `FAIL  <what>: <why>` "
          "spelling the gate runner reads, the exit is 1, and the tally rides along "
          "so a clean answer is not an empty one: %r" % (_buf.getvalue(),),
          _found == ["uncovered scripts/" + _nl] and _total == 3
          and _code == 1
          and "FAIL  coverage: uncovered scripts/" + _nl in _buf.getvalue())
    check("g3b ...the allow direction, which is the half that fails if the check "
          "were made to fire on everything: the same module with a NAMED exemption "
          "is clean, exits 0 and says how many modules it looked at - and a run "
          "NAMED to a few files asks nothing of the rest of the tree: %r"
          % (_buf_ok.getvalue(),),
          _found_ok == [] and _total_ok == 3 and _code_ok == 0
          and "FAIL" not in _buf_ok.getvalue()
          and ("%d shipped" % 3) in _buf_ok.getvalue()
          and _code_named == 0)
    _real_found, _real_total = coverage_findings()
    check("g3c the real checkout: every shipped and development module has a suite "
          "or a named exemption, and the classifier looked at more than a handful "
          "- %r" % (_real_found,), _real_found == [] and _real_total > 100)

    g = grade(live, 1, "Traceback\n")
    check("g4 a non-zero exit is red and the code is NAMED, so the summary line "
          "says what happened: %r" % (g,),
          (not g["ok"]) and g["why"] == "exited 1")

    # The cases that pin one grade for every leg are further down, with real
    # children: the codec is forced in `run_one`, so they have to go through
    # `sweep`.

    g = grade(live, None, "did not finish within 300s")
    check("g6 a timeout is a NAMED failure, not a wait - neither old copy had "
          "one, so a hung suite and a slow machine printed the same nothing: "
          "%r" % (g,),
          (not g["ok"]) and "did not finish" in g["why"])

    n = cases_in("part one: 2/2 cases passed\nALL PASS: 41/41 cases passed\n")
    check("c0 the count comes from the LAST contract line, matching CI's "
          "`tail -1 | grep`: a per-section line before the total must not be "
          "what gets counted (got %r, and 2 would mean the first)" % (n,),
          n == 41)

    check("c1 no contract reads as NO CLAIM (None), which is what g1 turns into "
          "a failure - if this returned 0 the two would be the same answer",
          cases_in("nothing here") is None)

    found = sweep_files()
    # RECURSION IS PROVEN ON A TREE OF ITS OWN: the real swept directories are flat
    # now that the plugin's nested domains are not among them, so a real tree could
    # no longer tell a recursive walk from a flat glob.
    _d_root = tempfile.mkdtemp(prefix="sweep-discovery-")
    try:
        for _rel in ("tests/test_flat" + _ext, "tests/deep/er/test_nested" + _ext,
                     "tools/lints/_not_swept" + _ext):
            os.makedirs(os.path.dirname(os.path.join(_d_root, _rel)), exist_ok=True)
            with open(os.path.join(_d_root, _rel), "w") as _fh:
                _fh.write("\n")
        _nested = sweep_files(_d_root)
        # The exclusion list asked about the FIXTURE: its paths are relative to the
        # fixture, never to the repository this suite runs in.
        _d_else = _output_lints.suite_elsewhere_paths(_d_root)
    finally:
        shutil.rmtree(_d_root, ignore_errors=True)
    check("d0 discovery is RECURSIVE and reaches files in subdirectories - a "
          "flat glob is how CI's old loop silently stopped running a whole "
          "directory: %r, over a real walk that found %d files"
          % (_nested, len(found)),
          "tests/deep/er/test_nested" + _ext in _nested
          and "tests/test_flat" + _ext in _nested and len(found) > 100)

    check("d0b the exclusion list is rooted at the repository it is asked about: "
          "a development module that exists only in a fixture repo is left out "
          "of that fixture's sweep, and the fixture's list holds no path "
          "climbing out of it (rooting the walk at THIS repo relpaths across "
          "drives on Windows and yields `../` paths on posix): %r, list %r"
          % ("tools/lints/_not_swept" + _ext in _nested, _d_else),
          "tools/lints/_not_swept" + _ext not in _nested
          and "tools/lints/_not_swept" + _ext in _d_else
          and not [p for p in _d_else if p.startswith("..")])

    check("d1 the list is sorted and carries no duplicate, so two green runs "
          "produce byte-identical logs and a path is swept once",
          found == sorted(found) and len(found) == len(set(found)))

    _elsewhere = set(_output_lints.suite_elsewhere_paths())
    check("d2 the sweep runs no shipped module and none of the development modules "
          "whose cases live in tests/: nothing under the plugin, `tools/lints/`, "
          "`tools/demo/` or either benchmark is listed, and the suites and tools "
          "that DO carry a suite still are - a path left in would be graded for a "
          "contract it never prints",
          not [p for p in found if p.startswith("plugins/")]
          and not [p for p in found if p in _elsewhere]
          and "tools/sweep-selftests.py" in found
          and "tests/test__output.py" in found)

    check("d3 ...and what it leaves out is real and spelled the way discovery spells "
          "paths, which is the assertion that the two agree rather than merely look "
          "alike: every omitted path exists, and none of them is in the walk (%d "
          "omitted)" % (len(_elsewhere),),
          _elsewhere and all(os.path.isfile(os.path.join(REPO, p)) for p in _elsewhere)
          and "tools/lints/_deps.py" in _elsewhere and not (_elsewhere & set(found)))

    check("j0 worker count leaves two cores and never drops below one, so a "
          "single-core runner still runs",
          default_jobs(14, {}) == 12 and default_jobs(1, {}) == 1
          and default_jobs(2, {}) == 1)

    v = _flag_value(["--jobs", "4"], "--jobs", 99)
    w = _flag_value(["--jobs=4"], "--jobs", 99)
    check("f0 both flag spellings read the same value and the fallback survives "
          "an empty argv",
          v == "4" and w == "4" and
          _flag_value([], "--jobs", 99) == 99)

    buf = io.StringIO()
    code = render([grade(live, 0, "1/1 cases passed\n"),
                   grade("tools/lints/_deps.py", 1, "boom\n")], 4,
                  stream=buf)
    text = buf.getvalue()
    check("r0 a red render exits 1, names the file twice (table and summary), "
          "reproduces the child's output IN FULL, and ends with the counts "
          "so `tail -12` of a failed step is the useful part",
          code == 1 and text.count("FAIL") == 2
          and "boom" in text and text.rstrip().endswith("%d cases" % 1))

    buf = io.StringIO()
    code = render([grade(live, 0, "5/5 cases passed\n")], 4, stream=buf)
    check("r1 a green render exits 0, says FAIL nowhere, and still prints the "
          "count - so 'all ok' and 'nothing ran' cannot read the same",
          code == 0 and "FAIL" not in buf.getvalue()
          and ("%d cases" % 5) in buf.getvalue())
    buf = io.StringIO()
    render([grade(live, 0, "5/5 cases passed\n")], 4, stream=buf)
    check("r2 the summary line says how many files were ok and how many cases ran, "
          "and carries no `migrated` clause - there is no such class to count, and "
          "the gate runner reads the line with that clause optional: %r"
          % (buf.getvalue().splitlines()[-1],),
          buf.getvalue().splitlines()[-1] == "%d/%d files ok, %d cases" % (1, 1, 5)
          and "migrated" not in buf.getvalue())

    # -- render_quiet prints failures and totals, never a passing file --------
    _rows_mix = [grade(live, 0, "1/1 cases passed\n"),
                 grade("tools/lints/_deps.py", 1, "boom\n")]
    buf_rq = io.StringIO()
    code_rq = render_quiet(_rows_mix, 4, stream=buf_rq)
    text_rq = buf_rq.getvalue()
    check("rq0 THE QUIET FORM matches the LOUD FORM (r0) on the VERDICT - the "
          "same exit code, the failing file's own header, its output IN "
          "FULL, and the final counts - because a quiet run is a second "
          "spelling of the same run and not a second run: %r" % (text_rq,),
          code_rq == 1 and "FAIL" in text_rq and "boom" in text_rq
          and text_rq.rstrip().endswith("%d cases" % 1))
    check("rq1 ...and drops the PASSING file's own inventory line, which is "
          "the whole of what this form is for: %r" % (text_rq,),
          live not in text_rq)

    buf_rq_green = io.StringIO()
    render_quiet([grade(live, 0, "5/5 cases passed\n")], 4,
                 stream=buf_rq_green)
    check("rq2 a wholly green quiet render names no file at all - not even the "
          "one that passed - and still prints the count, so a caller reading "
          "only this output can still tell 'nothing failed' from 'nothing "
          "ran': %r" % (buf_rq_green.getvalue(),),
          live not in buf_rq_green.getvalue()
          and "FAIL" not in buf_rq_green.getvalue()
          and ("%d cases" % 5) in buf_rq_green.getvalue())

    buf_rq_two = io.StringIO()
    render_quiet(_rows_mix, 4, stream=buf_rq_two)
    check("rq3 the quiet form's summary line is the loud form's: the gate runner "
          "reads one spelling of it: %r" % (buf_rq_two.getvalue().splitlines()[-1],),
          buf_rq_two.getvalue().splitlines()[-1]
          == "%d/%d files ok, %d cases" % (1, 2, 1))

    # -- the scratch-directory rule, without a subprocess ----------------------
    g = grade(live, 0, "ALL PASS: 9/9 cases passed\n",
              debris=["working directory: left behind: probe-fixture-a1b2"])
    check("h0 a suite that exits 0, prints the contract AND changed the "
          "directory it ran in is RED, and the row NAMES what it left - the "
          "row this runner could not produce while every child ran in the "
          "repository root: %r" % (g,),
          (not g["ok"]) and "probe-fixture-a1b2" in g["why"]
          and "wrote outside the fixtures" in g["why"])

    g = grade("tools/lints/_deps.py", 0, "ALL PASS: 1/1 cases passed\n",
              debris=["working directory: DELETED left-by-the-runner, which was "
                      "there before it ran"])
    check("h1 ...and every file is graded by the same rule, a pointer-only one "
          "included - a file does not stop leaking because its cases live "
          "elsewhere: %r" % (g,),
          (not g["ok"]) and "DELETED" in g["why"])

    # -- the home directory, which is the second watched one ------------
    _where = os.path.join("SOMEWHERE", "else")
    _pinned = home_env(_where)
    _needed = set(["HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                   "XDG_CACHE_HOME", "XDG_STATE_HOME", "HOMEDRIVE", "HOMEPATH"])
    # NAMED HERE rather than read off HOME_VARS: a case that asserts the table
    # against itself passes whatever the table says, including a table that lost
    # every XDG entry. These are the lookups that must be closed, written out.
    check("hv0 every name a home lookup reads is pinned and not just HOME - the "
          "XDG roots are set independently on linux, USERPROFILE is what windows "
          "reads, and git for windows joins HOMEDRIVE with HOMEPATH by hand, so "
          "any one left alone walks straight past the watched directory: %r"
          % (sorted(_pinned),),
          _needed.issubset(set(_pinned))
          and all(_pinned[n] == _where for n in HOME_VARS)
          and os.path.join(_pinned["HOMEDRIVE"], _pinned["HOMEPATH"]) == _where)

    # -- the rest of the caller's environment -------------------------------
    _caller = {"CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_PLUGIN_ROOT": "/p",
               "CLAUDECODE": "1", "AUDIT_LOCK_TOKENS": "t",
               "PATH": "/bin", "MY_CLAUDE_NOTE": "kept", "CLAUDEX_NOTE": "kept",
               "GIT_CONFIG_NOSYSTEM": "0"}
    _before = dict(_caller)
    _amb = ambient_env(_caller)
    check("se0 the session family is dropped by PREFIX and the names outside "
          "it by name, so a member the harness adds later is dropped without a "
          "list growing: %r" % (sorted(_amb),),
          not any(k in _amb for k in ("CLAUDE_CODE_SESSION_ID",
                                      "CLAUDE_PLUGIN_ROOT", "CLAUDECODE",
                                      "AUDIT_LOCK_TOKENS")))
    # se1 IS THE SECOND DIRECTION: se0 passes against a filter that drops
    # everything, or one that matches the prefix anywhere in a name.
    check("se1 ...and nothing else is: a name that merely CONTAINS the prefix, "
          "or starts with the prefix minus its separator, passes through with "
          "PATH: %r" % (_amb,),
          _amb.get("PATH") == "/bin" and _amb.get("MY_CLAUDE_NOTE") == "kept"
          and _amb.get("CLAUDEX_NOTE") == "kept")
    check("se2 git's system config is switched off and identity guessing refused "
          "OVER whatever the caller carried, and no branch or identity is "
          "supplied in their place: %r"
          % (dict((k, v) for k, v in _amb.items() if k.startswith("GIT_")),),
          _amb.get("GIT_CONFIG_NOSYSTEM") == "1"
          and _amb.get("GIT_CONFIG_KEY_0") == "user.useConfigOnly"
          and _amb.get("GIT_CONFIG_VALUE_0") == "true"
          and not any(k in _amb for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                                          "GIT_COMMITTER_NAME",
                                          "GIT_COMMITTER_EMAIL"))
          and "init.defaultBranch" not in _amb.values())
    check("se3 ...and the caller's mapping is left as it was, because it is the "
          "process environment every thread of the sweep shares",
          _caller == _before)

    _ident = dict((n, "x") for n in GIT_IDENTITY_NAMES)
    _ident.update({"GIT_DIR": "/r/.git", "GIT_TERMINAL_PROMPT": "0"})
    _amb = ambient_env(_ident)
    # NAMED HERE rather than read off GIT_IDENTITY_NAMES, as hv0 does for the home
    # table: a case asserting the tuple against itself passes a tuple that lost
    # half its members.
    check("se4 every identity name in git's own list is dropped when the caller "
          "exports it: %r" % (sorted(_amb),),
          not any(k in _amb for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                                      "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME",
                                      "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
                                      "EMAIL")))
    # se5 IS THE SECOND DIRECTION of se4: a filter over the whole `GIT_` prefix
    # passes se4 and takes the repository a caller pointed at with it.
    check("se5 ...and a GIT_ name that is not identity is left alone: %r"
          % (dict((k, v) for k, v in _amb.items()
                  if k in ("GIT_DIR", "GIT_TERMINAL_PROMPT")),),
          _amb.get("GIT_DIR") == "/r/.git"
          and _amb.get("GIT_TERMINAL_PROMPT") == "0")

    # THE CALLER CARRIES A CONFIG SET OF ITS OWN, through the same protocol: a
    # higher count, an index the runner also writes holding the opposite value, and
    # an index past the runner's count. A runner that only overwrites leaves that
    # last pair in the child, where any suite that appends to the count reads it.
    _cfg = {"PATH": "/bin", "GIT_CONFIG_COUNT": "6",
            "GIT_CONFIG_KEY_1": "maintenance.auto", "GIT_CONFIG_VALUE_1": "true",
            "GIT_CONFIG_KEY_5": "core.hooksPath", "GIT_CONFIG_VALUE_5": "/caller"}
    _amb = ambient_env(_cfg)
    _gitcfg = dict((k, v) for k, v in _amb.items()
                   if k.startswith("GIT_CONFIG_") and k != "GIT_CONFIG_NOSYSTEM")
    try:
        _count = int(_amb.get("GIT_CONFIG_COUNT", ""))
    except ValueError:
        _count = -1
    _settings = [(_amb.get("GIT_CONFIG_KEY_%d" % (i,)),
                  _amb.get("GIT_CONFIG_VALUE_%d" % (i,)))
                 for i in range(max(_count, 0))]
    _encoded = set(["GIT_CONFIG_COUNT"]) | set(
        "GIT_CONFIG_%s_%d" % (part, i) for part in ("KEY", "VALUE")
        for i in range(max(_count, 0)))
    _keys = [k for k, _ in _settings]
    # NAMED HERE rather than read off GIT_ENV, as hv0 and se4 do: a case asserting
    # the table against itself passes a table that lost the two keys. COUNTED, not
    # found - a set where `maintenance.auto` appears twice is one git resolves by
    # whichever index comes last.
    check("every sweep child's environment carries maintenance.auto=false and "
          "gc.auto=0 through GIT_CONFIG_COUNT, so no git process in any suite "
          "spawns detached maintenance, and the isolation documents name the "
          "family (gm0 the runner's set is the whole of the protocol a child "
          "sees - both keys once each beside the identity refusal, the count "
          "covering exactly them, and none of the caller's pairs left over): %r"
          % (_gitcfg,),
          _keys.count("maintenance.auto") == 1 and _keys.count("gc.auto") == 1
          and ("maintenance.auto", "false") in _settings
          and ("gc.auto", "0") in _settings
          and ("user.useConfigOnly", "true") in _settings
          and set(_gitcfg) == _encoded)

    # A fixture, NOT this file: `run_one` appends `--selftest`, so pointing it at
    # this module would have it run its own suite, which runs this case, which
    # spawns it again. Written that way first; a hermetic child is both safe and a
    # sharper test, because the expected output is chosen rather than incidental.
    # NO `.py` SUFFIX on the fixture, deliberately. `_refs.tool_basename_drift()`
    # holds that every `.py` basename literal under `tools/` must name a file that
    # exists, and it scans prose and code alike with no exception list - a rule
    # worth keeping, because stale prose misleads a reader as far as a stale argv
    # misleads a process. A fixture this file CREATES is not a reference to a repo
    # script, and `sys.executable <path>` does not care about the extension, so the
    # honest fix is a name that makes no claim rather than an exemption.
    #
    # AND THE WORK DIRECTORY IS REMOVED IN A `finally`. This block used to
    # end with a bare `mkdtemp()` and no cleanup, so the runner that now refuses a
    # leaking suite was itself one of the leaking files.
    work = tempfile.mkdtemp(prefix="sweep-selftest-")

    def _fixture(name, body):
        """One child script, written and handed back by absolute path."""
        path = os.path.join(work, name)
        io.open(path, "w", encoding="utf-8").write(body)
        return path

    _CONTRACT_LINE = "sys.stdout.write('fixture: 1/1 cases passed\\n')\n"
    try:
        child = _fixture("fixture_child",
                         "import sys\n"
                         "sys.stdout.write('fixture: 4/4 cases passed\\n')\n")
        ran = run_one(child, timeout=30)
        check("x0 run_one really starts a child and captures its stream, and the "
              "grader reads the child's OWN number back out - so the impure half "
              "is exercised and 4 could not have come from anywhere else "
              "(exit %r, read %r)" % (ran["code"], cases_in(ran["output"])),
              ran["code"] == 0 and cases_in(ran["output"]) == 4)

        io.open(child, "w", encoding="utf-8").write("import sys; sys.exit(3)\n")
        ran = run_one(child, timeout=30)
        check("x0b ...and the child's exit code is carried through unchanged "
              "rather than collapsed to 0/1, which is what makes g4's message "
              "name a real number (got %r)" % (ran["code"],),
              ran["code"] == 3)

        missing = os.path.join(work, "sweep-no-such-file-xyz")
        ran = run_one(missing, timeout=5)
        check("x1 a file that cannot run reports a failure rather than an empty "
              "green row (code %r)" % (ran["code"],),
              ran["code"] != 0)

        # THE EXACT LEAK SHAPE: a `mkdtemp` with no cleanup, in a child that
        # otherwise passes. It leaks into `TMPDIR`, not into the cwd, which is why
        # an empty working directory on its own would report this as clean.
        leaks = _fixture("fixture_leaks",
                         "import sys, tempfile\n"
                         "tempfile.mkdtemp(prefix='probe-fixture-')\n"
                         + _CONTRACT_LINE)
        ran = run_one(leaks, timeout=30)
        check("x2 a child that exits 0 and prints the contract but leaves a "
              "fixture in TMPDIR is reported, the finding names what was left "
              "AND which of the two watched directories it landed in - ONE "
              "finding, so a checker that also invented one about the planted "
              "file, or one about the untouched home directory, would not read "
              "as this: %r" % (ran["debris"],),
              ran["code"] == 0 and len(ran["debris"]) == 1
              and ran["debris"][0].startswith("working directory: ")
              and "probe-fixture-" in ran["debris"][0])

        # The DESTRUCTIVE half, which is the sharper one: a directory judged only
        # by what appeared in it calls this run spotless.
        kills = _fixture("fixture_destroys",
                         "import os, sys\n"
                         "os.remove(os.path.join(os.getcwd(), %r))\n" % (SENTINEL,)
                         + _CONTRACT_LINE)
        ran = run_one(kills, timeout=30)
        check("x2b a child that DELETES the file that was already in the "
              "directory is reported, and says so in words that cannot be "
              "confused with a leak - a deletion and a leak are not one repair: %r"
              % (ran["debris"],),
              ran["code"] == 0 and len(ran["debris"]) == 1
              and "DELETED" in ran["debris"][0]
              and "left behind" not in ran["debris"][0])

        edits = _fixture("fixture_rewrites",
                         "import io, os, sys\n"
                         "io.open(os.path.join(os.getcwd(), %r), 'wb')" % (SENTINEL,)
                         + ".write(b'clobbered')\n"
                         + _CONTRACT_LINE)
        ran = run_one(edits, timeout=30)
        check("x2c ...and one that REWRITES it in place is reported too, which "
              "a check comparing only the list of names cannot see: %r"
              % (ran["debris"],),
              ran["code"] == 0 and len(ran["debris"]) == 1
              and "REWROTE" in ran["debris"][0])

        # x2d LOOKS VACUOUS AND IS THE SECOND-DIRECTION CASE. Every case above
        # passes against a `scratch_debris` that reports EVERYTHING - including the
        # file this runner plants itself - and that version turns the whole tree
        # red for nothing. This is the only case that fails when the guard becomes
        # unconditional, and it is what the ALLOW row in `tools/prove-gates.py`
        # weakens `strays` to prove.
        quiet = _fixture("fixture_quiet", "import sys\n" + _CONTRACT_LINE)
        ran = run_one(quiet, timeout=30)
        check("x2d a child that touches nothing produces NO finding, in EITHER "
              "watched directory, so neither planted file is read as the "
              "child's debris: %r" % (ran["debris"],),
              ran["code"] == 0 and ran["debris"] == [])

        # -- the channel TMPDIR pinning alone cannot see ------------------
        # THE CHILD WRITES ONLY IF THE HOME IT WAS HANDED CARRIES THE PLANTED
        # FILE, and that guard is not caution - it is what makes this case safe to
        # run. A fixture that wrote to `~` unconditionally would litter a real home
        # directory on exactly the run where the pin FAILED, which is the run this
        # case exists to catch. Written this way it goes red instead, because a
        # child that found somebody's real home writes nothing and leaves no
        # debris to report.
        homer = _fixture("fixture_home_leak",
                         "import os, sys\n"
                         "h = os.path.expanduser('~')\n"
                         "if os.path.isfile(os.path.join(h, %r)):\n" % (SENTINEL,)
                         + "    os.mkdir(os.path.join(h, 'dot-claude-probe'))\n"
                         + _CONTRACT_LINE)
        ran = run_one(homer, timeout=30)
        check("x5 a child that writes an absolute path under `~` is reported, "
              "and the finding names the HOME channel rather than the working "
              "one - the leak an empty cwd and a pinned TMPDIR both miss, and "
              "the one this product invites because its state lives there: %r"
              % (ran["debris"],),
              ran["code"] == 0 and len(ran["debris"]) == 1
              and ran["debris"][0].startswith("home directory: ")
              and "dot-claude-probe" in ran["debris"][0])

        # The same rule through a DIFFERENT variable, because HOME is not the only
        # name a config lookup reads and a version that pinned only HOME would pass
        # x5 for ever while leaving this wide open on linux.
        xdg = _fixture("fixture_xdg_leak",
                       "import os, sys\n"
                       "d = os.environ.get('XDG_CONFIG_HOME') or ''\n"
                       "if d and os.path.isfile(os.path.join(d, %r)):\n"
                       % (SENTINEL,)
                       + "    os.mkdir(os.path.join(d, 'audit-probe'))\n"
                       + _CONTRACT_LINE)
        ran = run_one(xdg, timeout=30)
        check("x6 ...and a child that resolves its config directory through "
              "XDG_CONFIG_HOME instead lands in the same watched directory: a "
              "lookup pinned by one variable and not the others is a lookup that "
              "finds the real home on the platform that reads the other one: %r"
              % (ran["debris"],),
              ran["code"] == 0 and len(ran["debris"]) == 1
              and ran["debris"][0].startswith("home directory: ")
              and "audit-probe" in ran["debris"][0])

        # The interpreter's own writes, which are NOT the suite's. macOS's system
        # python puts a shadow bytecode cache under the HOME it is handed for every
        # script it runs, so without this pin a suite that started a grandchild
        # named `python3` was convicted of a leak it did not commit - and the
        # alternative, an exemption for one platform's spelling of a cache
        # directory, has a premise that would need re-checking on every other.
        pyc = _fixture("fixture_pycache",
                       "import os, sys\n"
                       "for k, v in (('prefix', sys.pycache_prefix),\n"
                       "             ('home', os.path.expanduser('~')),\n"
                       "             ('cwd', os.getcwd())):\n"
                       "    sys.stdout.write('%s=%s\\n' % (k, v))\n"
                       + _CONTRACT_LINE)
        ran = run_one(pyc, timeout=30)
        _seen = dict(line.split("=", 1) for line in ran["output"].splitlines()
                     if "=" in line)
        check("x7 the child's bytecode cache is pinned OUTSIDE both watched "
              "directories, so an interpreter that writes one under the home it "
              "is given cannot be read as the suite having leaked there: %r"
              % (_seen,),
              ran["code"] == 0 and _seen.get("prefix") not in (None, "", "None")
              and not _seen["prefix"].startswith(_seen["home"])
              and not _seen["prefix"].startswith(_seen["cwd"]))

        # -- what a child inherits that is not a directory -----------------
        # THE SESSION IS PLANTED, not read off this process: CI's runners carry
        # none of it, so a case that relied on the caller's own environment would
        # pass there against a runner that filters nothing. `GIT_CONFIG_NOSYSTEM`
        # is planted as "0" so a runner that merely passes the caller's value
        # through reads differently from one that pins it. The pass-through name is
        # chosen to CONTAIN the prefix without starting with it, which is what a
        # filter matching anywhere in the name would wrongly drop.
        envprobe = _fixture("fixture_env",
                            "import json, os, subprocess, sys\n"
                            "r = subprocess.run(['git', 'var', "
                            "'GIT_COMMITTER_IDENT'], stdout=subprocess.PIPE, "
                            "stderr=subprocess.PIPE)\n"
                            "e = os.environ\n"
                            "sys.stdout.write('ENV=' + json.dumps({\n"
                            "    'session': sorted(k for k in e if "
                            "k.startswith('CLAUDE') or k == 'AUDIT_LOCK_TOKENS'),\n"
                            "    'identity': sorted(k for k in e if k in %r),\n"
                            % (list(GIT_IDENTITY_NAMES),)
                            + "    'prompt': e.get('GIT_TERMINAL_PROMPT'),\n"
                            "    'own': subprocess.run(['git', 'var', "
                            "'GIT_AUTHOR_IDENT'], stdout=subprocess.PIPE, "
                            "stderr=subprocess.PIPE, env=dict(e, "
                            "GIT_AUTHOR_NAME='Own Fixture', "
                            "GIT_AUTHOR_EMAIL='own@fixture.invalid'))"
                            ".stdout.decode('utf-8', 'replace'),\n"
                            "    'nosystem': e.get('GIT_CONFIG_NOSYSTEM'),\n"
                            "    'ident': r.returncode,\n"
                            "    'kept': e.get('SWEEP_CLAUDE_PROBE'),\n"
                            "    'path': e.get('PATH'),\n"
                            "    'home': os.path.expanduser('~'),\n"
                            "    'tmp': os.path.realpath(e.get('TMPDIR') or ''),\n"
                            "    'cwd': os.path.realpath(os.getcwd())}) + '\\n')\n"
                            + _CONTRACT_LINE)
        _planted = dict(os.environ)
        _planted.update({"CLAUDE_CODE_SESSION_ID": "sweep-probe-session",
                         "CLAUDE_PID": str(os.getpid()),
                         "CLAUDECODE": "1",
                         "AUDIT_LOCK_TOKENS": "sweep-probe-token",
                         "GIT_CONFIG_NOSYSTEM": "0",
                         "SWEEP_CLAUDE_PROBE": "kept",
                         "GIT_TERMINAL_PROMPT": "0"})
        # EVERY IDENTITY NAME IS EXPORTED BY THE CALLER, which is the developer
        # this case is about. x10 therefore reads a refused GUESS only when the
        # exported identity was dropped first - a runner that passes it through
        # turns x10 red beside x12, and that is the class, not a confusion of it.
        _planted.update(dict((n, "sweep-probe-%s@ambient.invalid" % (n.lower(),))
                             for n in GIT_IDENTITY_NAMES
                             if not n.endswith("_DATE")))
        _planted.update({"GIT_AUTHOR_DATE": "@1700000000 +0000",
                         "GIT_COMMITTER_DATE": "@1700000000 +0000"})
        ran = run_one(envprobe, timeout=30, environ=_planted)
        _env = {}
        for line in ran["output"].splitlines():
            if line.startswith("ENV="):
                _env = json.loads(line[len("ENV="):])
        # What the messages print: the report without PATH, which is long and is
        # compared rather than read - or, when the child reported nothing, what it
        # printed instead, so a dead child is not a row of empty dicts.
        _shown = (dict((k, v) for k, v in _env.items() if k != "path")
                  if _env else ran["output"][-400:])
        check("x8 a child sees NONE of the Claude session it was typed from - the "
              "prefix family, the harness marker and a lock holder's tokens - "
              "which the lock and journal code otherwise read as a live holder "
              "and an actor that a bare runner never has: %r" % (_shown,),
              ran["code"] == 0 and bool(_env) and _env.get("session") == [])
        check("x9 ...git's SYSTEM config is switched off in the child, overriding "
              "the value the caller carried, so a default branch the host's git "
              "pins cannot reach a suite: %r" % (_env.get("nosystem"),),
              bool(_env) and _env.get("nosystem") == "1")
        check("x10 ...and git refuses to GUESS an identity: with no configured "
              "user a child's `git var GIT_COMMITTER_IDENT` fails as it does on a "
              "runner, instead of answering with the host name: exit %r"
              % (_env.get("ident"),),
              bool(_env) and _env.get("ident") not in (None, 0))
        check("x12 ...and an identity the caller EXPORTS does not reach the child "
              "either - every name git's own documentation lists for a commit's "
              "identity is absent, so a suite that commits without configuring "
              "one cannot borrow the developer's: %r" % (_env.get("identity"),),
              bool(_env) and _env.get("identity") == [])
        # x13 AND x14 ARE THE SECOND DIRECTION of x12. A filter over every `GIT_*`
        # name passes x12 and takes `GIT_DIR` and its neighbours with it; a filter
        # applied to what a SUITE builds for its own child would break every
        # fixture that commits with an identity it set itself.
        check("x13 ...while a GIT_ name that is not identity still passes through "
              "from the caller: GIT_TERMINAL_PROMPT=%r" % (_env.get("prompt"),),
              bool(_env) and _env.get("prompt") == "0")
        check("x14 ...and an identity a child sets for ITS OWN child reaches it - "
              "only what the sweep inherits is filtered: %r" % (_env.get("own"),),
              bool(_env) and "Own Fixture <own@fixture.invalid>"
              in (_env.get("own") or ""))
        # x11 IS THE SECOND DIRECTION: every case above passes against a runner
        # that hands the child an EMPTY environment, which would kill every suite
        # that shells out by name. It is also the one that fails when the filter
        # matches the prefix anywhere in a name rather than at its start.
        check("x11 ...while everything else still reaches the child: PATH and a "
              "name that merely contains the prefix pass through, and the cwd, "
              "TMPDIR and home isolation are still in force (PATH identical: "
              "%r): %r" % (_env.get("path") == os.environ.get("PATH"), _shown),
              bool(_env) and _env.get("kept") == "kept"
              and _env.get("path") == os.environ.get("PATH")
              and _env.get("tmp") == _env.get("cwd")
              and _env.get("home") not in (None, os.path.expanduser("~"),
                                           _env.get("cwd")))

        # -- background maintenance, asked of the git the child really runs -----
        # A SUITE THAT CALLS BARE GIT, with no shared fixture prefix: the class the
        # runner's own setting exists for, since a prefix only reaches the suites
        # that use it. The commit is traced and the spawn counted off git's own
        # `run_command:` line, once per commit. The deny twin runs the same commit
        # with the runner's config set taken out again and
        # `maintenance.autoDetach=false`, so the one maintenance run it is expected
        # to start runs in the foreground and is finished before its repository is
        # removed - a detached one would outlive the fixture, which is the very
        # thing being switched off.
        maint = _fixture(
            "fixture_maint",
            "import json, os, shutil, subprocess, sys, tempfile\n"
            "def spawns(env, extra):\n"
            "    root = tempfile.mkdtemp(prefix='gm-')\n"
            "    wt = os.path.join(root, 'wt')\n"
            "    trace = os.path.join(root, 'trace')\n"
            "    git = ['git', '-c', 'user.name=Fixture', '-c',\n"
            "           'user.email=fixture@fixture.invalid', '-c',\n"
            "           'commit.gpgsign=false'] + extra\n"
            "    try:\n"
            "        subprocess.run(['git', 'init', '-q', wt], env=env, check=True)\n"
            "        with open(os.path.join(wt, 'a'), 'w') as fh:\n"
            "            fh.write('a')\n"
            "        subprocess.run(git + ['-C', wt, 'add', 'a'], env=env,\n"
            "                       check=True)\n"
            "        subprocess.run(git + ['-C', wt, 'commit', '-qm', 'a'],\n"
            "                       env=dict(env, GIT_TRACE=trace), check=True)\n"
            "        with open(trace, encoding='utf-8', errors='replace') as fh:\n"
            "            return sum(1 for line in fh if\n"
            "                       'run_command: git maintenance run' in line)\n"
            "    finally:\n"
            "        shutil.rmtree(root, ignore_errors=True)\n"
            "env = dict(os.environ)\n"
            "bare = dict((k, v) for k, v in env.items()\n"
            "            if k != 'GIT_CONFIG_COUNT'\n"
            "            and not k.startswith('GIT_CONFIG_KEY_')\n"
            "            and not k.startswith('GIT_CONFIG_VALUE_'))\n"
            "seen = subprocess.run(['git', 'config', '--get', 'maintenance.auto'],\n"
            "                      stdout=subprocess.PIPE, env=env)\n"
            "ver = subprocess.run(['git', '--version'], stdout=subprocess.PIPE)\n"
            "sys.stdout.write('MAINT=' + json.dumps({\n"
            "    'version': ver.stdout.decode('utf-8', 'replace').strip(),\n"
            "    'reads': seen.stdout.decode('utf-8', 'replace').strip(),\n"
            "    'with': spawns(env, []),\n"
            "    'without': spawns(bare, ['-c', 'maintenance.autoDetach=false'])})\n"
            "    + '\\n')\n"
            + _CONTRACT_LINE)
        ran = run_one(maint, timeout=60)
        _mt = {}
        for line in ran["output"].splitlines():
            if line.startswith("MAINT="):
                _mt = json.loads(line[len("MAINT="):])
        _mshown = _mt or ran["output"][-400:]
        check("gm1 ...a traced commit in a suite that calls bare git, with no "
              "shared prefix, spawns NO maintenance under the runner's "
              "environment, and that child's git reads the runner's value back "
              "through the protocol: %r" % (_mshown,),
              ran["code"] == 0 and bool(_mt) and _mt.get("with") == 0
              and _mt.get("reads") == "false")
        # gm2 IS THE SECOND DIRECTION of gm1: a trace that is never written, or a
        # match string git never prints, reads zero spawns under any environment.
        # The same commit without the runner's set must spawn exactly one.
        check("gm2 ...while the same commit with the runner's set taken out spawns "
              "exactly one, so gm1's zero is a count that could have been "
              "otherwise: %r" % (_mshown,),
              ran["code"] == 0 and bool(_mt) and _mt.get("without") == 1)

        # The WIRING, at the level that actually runs in CI. Everything above
        # proves `run_one` observes and `grade` judges; this is the only case that
        # fails if `sweep()` stops carrying the observation from one to the other.
        rows = sweep([leaks], jobs=1, repo=work, timeout=30)
        check("x3 sweep() carries the observation into the graded row - the case "
              "that fails if run_one and grade are both right and nothing hands "
              "the answer across: %r" % (rows,),
              len(rows) == 1 and not rows[0]["ok"]
              and "probe-fixture-" in rows[0]["why"])
    finally:
        # THE SAME HELPER `run_one` USES, so this file holds one answer to "remove
        # a directory" rather than two. Nothing here is read-only today; a second
        # spelling beside the first is how that stops being true unnoticed.
        remove_tree(work)

    # A REAL SUITE FROM THIS TREE, end to end. The cases above are all driven by
    # fixtures this file wrote, and a hand-written fixture encodes the same
    # assumption the checker does; this one asserts the property about a file
    # somebody else maintains. It is also the case `tools/prove-gates.py` reddens
    # by planting a leak in that suite, which is what makes this guard proven
    # rather than merely seen passing.
    _real = "tests/test__cli_fmt.py"
    ran = run_one(_real, timeout=60)
    check("x4 a suite this repo actually ships leaves its scratch directory "
          "exactly as it found it (%s: exit %r, %r)"
          % (_real, ran["code"], ran["debris"]),
          ran["code"] == 0 and ran["debris"] == [])

    # -- the spaced leg ---------------------------------------------------------
    sp_work = tempfile.mkdtemp(prefix="sweep-spaced-")
    try:
        sp_holder = os.path.join(sp_work, "h")
        os.makedirs(sp_holder)
        sp_scratch, sp_interp = spaced_layout(sp_holder)
        sp_real = os.path.realpath(sp_scratch)
        sp_rel_link = os.path.relpath(sp_scratch, sp_holder)
        sp_rel_real = os.path.relpath(sp_real, os.path.realpath(sp_holder))
        check("sp1 the spaced scratch holds a space and is reached THROUGH a "
              "symlink whose target is not a suffix-extension of the link: the "
              "link spells %r and the resolved path spells %r, so a fixture "
              "that compares or rebuilds one spelling from the other is caught "
              "where `/tmp` -> `/private/tmp` would hide it"
              % (sp_rel_link, sp_rel_real),
              " " in sp_scratch and os.path.islink(os.path.dirname(sp_scratch))
              and sp_rel_link != sp_rel_real
              and not sp_real.endswith(sp_scratch)
              and sp_rel_real.split(os.sep)[0] != sp_rel_link.split(os.sep)[0])
        sp_ran = subprocess.run([sp_interp, "-c", "print(6 * 7)"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check("sp2 the interpreter the leg hands a child sits under a directory "
              "holding a space and still starts: %r %r"
              % (sp_interp, sp_ran.stdout),
              " " in sp_interp and sp_ran.returncode == 0
              and sp_ran.stdout.strip() == b"42")

        sp_child = os.path.join(sp_work, "spaced_child")
        io.open(sp_child, "w", encoding="utf-8").write(
            "import os, subprocess, sys\n"
            "tmp = os.environ['TMPDIR']\n"
            "bare = subprocess.run('test -d ' + tmp, shell=True).returncode\n"
            "word = subprocess.run('test -d ' + __import__('shlex').quote(tmp),"
            " shell=True).returncode\n"
            "sys.stdout.write('TMP=' + tmp + '\\nBARE=%d\\nQUOTED=%d\\n'"
            " % (bare, word))\n"
            "sys.stdout.write('fixture: 1/1 cases passed\\n')\n")
        sp_got = dict(line.split("=", 1) for line in run_one(
            sp_child, timeout=60, spaced=True)["output"].splitlines()
            if "=" in line)
        sp_tmp = sp_got.get("TMP", "")
        # The word-splitting half is a property of a POSIX shell: on Windows
        # `shell=True` is cmd.exe, which has no `test`, so both words exit
        # non-zero and say nothing about splitting. The TMPDIR half (a space,
        # reached through the link, spelt with the platform's separator) holds
        # on every platform and is still asserted there.
        sp_posix = os.name != "nt"
        if not sp_posix:
            print("sp3: skipping the unquoted-vs-quoted shell word check on "
                  "Windows - cmd.exe has no `test` and splits words by its own "
                  "rules; the TMPDIR space-and-link half is still asserted")
        check("sp3 a child run with `spaced` sees a TMPDIR holding a space and "
              "a link, an UNQUOTED path in a shell command is a different "
              "command there (exit %s) while the quoted word names the "
              "directory (exit %s) - the defect class the leg exists to keep "
              "measured (the shell half is POSIX-only): %r"
              % (sp_got.get("BARE"), sp_got.get("QUOTED"), sp_tmp),
              " " in sp_tmp and (os.sep + "via" + os.sep) in sp_tmp
              and (not sp_posix
                   or (sp_got.get("BARE") not in (None, "0")
                       and sp_got.get("QUOTED") == "0")))

        # A TABLE OF THE CASE'S OWN, because the shipped one may be empty and
        # a case that borrowed its first row would then assert nothing.
        sp_exempt = "/".join(("tests", "absent" + ".py"))
        sp_table = {sp_exempt: "a scratch row: the file does not exist in this "
                               "scratch repository, so running it is red"}
        sp_rows = sweep([sp_exempt], jobs=1, repo=sp_work, timeout=30,
                        spaced=True, exempt=sp_table)
        sp_plain = sweep([sp_exempt], jobs=1, repo=sp_work, timeout=30,
                         exempt=sp_table)
        check("sp4 a file the spaced leg exempts is reported as exempt with its "
              "reason and is not run there (it does not exist in this scratch "
              "repository, so running it would be red), while the same path on "
              "the ordinary leg IS run: %r" % (sp_rows,),
              len(sp_rows) == 1 and sp_rows[0]["ok"]
              and sp_rows[0].get("exempt") == sp_table[sp_exempt]
              and len(sp_plain) == 1 and not sp_plain[0]["ok"])
        sp_repaired = ("tests/test__machine_paths.py",
                       "tests/test__journal_io.py",
                       "tests/test__evidence_io.py",
                       "tests/test__manifest_io.py",
                       "tests/test_audit_task.py",
                       "tests/test_stamp_verification.py",
                       "tests/_harness.py")
        check("sp6 the spaced leg runs the scrub, stamp-verification and "
              "harness suites - the machine-path scrub, NODE_OPTIONS reading "
              "and the harness fixtures read a path holding a space as one "
              "path, so no row excuses them: %r"
              % (sorted(set(sp_repaired) & set(SPACED_EXEMPT)),),
              not set(sp_repaired) & set(SPACED_EXEMPT))
        sp_swept = set(sweep_files())
        check("sp5 every exemption names a file the sweep reaches and carries a "
              "reason, so a row cannot outlive its file or excuse it silently: "
              "%r" % (sorted(set(SPACED_EXEMPT) - sp_swept),),
              set(SPACED_EXEMPT) <= sp_swept
              and all(len(r) > 40 for r in SPACED_EXEMPT.values()))
    finally:
        remove_tree(sp_work)

    # -- one grade for every leg, read through real children -------------------
    # A fixture repository of its own: `sweep` joins `repo` with each path, and
    # these paths name files that exist only here. Every child reports the codec
    # its stdout really has and the TMPDIR it was handed, so a case can tell a
    # condition that reached the child from one that was only asked for.
    en_work = tempfile.mkdtemp(prefix="sweep-codec-")
    try:
        def _en(rel, body):
            """One child under the fixture repository, by repo-relative path."""
            path = os.path.join(en_work, *rel.split("/"))
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            io.open(path, "w", encoding="utf-8").write(body)
            return rel

        _says = ("import os, sys\n"
                 "sys.stdout.write('ENC=' + str(sys.stdout.encoding) + '\\n')\n"
                 "sys.stdout.write('TMP=' + os.environ.get('TMPDIR', '') + '\\n')\n")
        en_live = _en("tests/test_en_live",
                      _says + "sys.stdout.write('fixture: 3/3 cases passed\\n')\n")
        en_mute = _en("tests/test_en_mute",
                      _says + "sys.stdout.write('ran, and said nothing\\n')\n")
        # THE CODEC FAILURE A CONTRACT-FREE GRADE CANNOT SEE: the suite meets a
        # character the page lacks, swallows the error and exits 0.
        en_glyph = _en("tests/test_en_glyph",
                       _says + "try:\n"
                       "    sys.stdout.write('\\u2713\\n')\n"
                       "except UnicodeEncodeError:\n"
                       "    sys.exit(0)\n"
                       "sys.stdout.write('fixture: 1/1 cases passed\\n')\n")
        # A pointer-only file: there is no migrated grade to excuse it, so it is red
        # on this leg exactly as it is on the plain one.
        en_pointer = _en("tools/_en_pointer",
                         _says + "sys.stdout.write('cases moved to tests/\\n')\n")
        en_paths = [en_live, en_mute, en_glyph, en_pointer]

        def _en_rows(spaced):
            """{path: row} for the fixtures, swept under cp1252 (and `spaced`)."""
            return dict((r["path"], r) for r in sweep(
                en_paths, jobs=2, repo=en_work, timeout=60,
                encoding="cp1252", spaced=spaced))

        def _en_tmp(row):
            """The TMPDIR the child reported, or the empty string."""
            for line in (row.get("output") or "").splitlines():
                if line.startswith("TMP="):
                    return line[len("TMP="):]
            return ""

        en_rows = _en_rows(False)
        en_l, en_m, en_g, en_v = [en_rows.get(p) or {} for p in en_paths[:4]]
        check("a cp1252 leg reds a contract-free suite and a pointer-only file, and "
              "counts a live suite's cases, exactly as "
              "the plain leg does: the codec really reached the child (%r), the "
              "live suite's cases are COUNTED rather than zeroed (%r), a suite "
              "that exits 0 without its contract is red (%r), so is one that "
              "swallowed its own UnicodeEncodeError and exited 0 - the codec "
              "failure a grade without the contract called green (%r) - and a "
              "file that prints a pointer and no contract is red too, there being "
              "no migrated grade to excuse it (%r)"
              % ("ENC=cp1252" in (en_l.get("output") or ""), en_l.get("cases"),
                 en_m.get("why"), en_g.get("why"), en_v.get("why")),
              "ENC=cp1252" in (en_l.get("output") or "")
              and en_l.get("ok") is True and en_l.get("cases") == 3
              and en_m.get("ok") is False
              and "no --selftest" in (en_m.get("why") or "")
              and en_g.get("ok") is False
              and "no --selftest" in (en_g.get("why") or "")
              and en_v.get("ok") is False
              and "no --selftest" in (en_v.get("why") or ""))

        # THE SUMMARY SAYS WHAT WAS GRADED. The codec leg is rendered off the
        # rows it really produced, so the line it prints is the count it took:
        # the live suite's own cases and nothing else (three files are red and
        # count as none). The plain leg's line is rendered off rows whose answer
        # is known independently.
        en_sum = io.StringIO()
        render_quiet([en_rows[p] for p in sorted(en_rows)], 2,
                     encoding="cp1252", stream=en_sum)
        en_sum_line = [ln for ln in en_sum.getvalue().splitlines()
                       if "files ok" in ln]
        en_plain = io.StringIO()
        render_quiet([grade(live, 0, "ALL PASS: 7/7 cases passed\n")], 2,
                     stream=en_plain)
        en_plain_line = [ln for ln in en_plain.getvalue().splitlines()
                         if "files ok" in ln]
        check("the codec leg's summary line carries the file and case counts it "
              "took, and the plain leg's summary is unchanged: the "
              "codec leg's reads %r and the plain leg's %r"
              % (en_sum_line, en_plain_line),
              en_sum_line == ["1/4 files ok, %d cases" % (3,)]
              and en_plain_line == ["1/1 files ok, %d cases" % (7,)])

        en_both = _en_rows(True)
        en_bl, en_bm, en_bg = [en_both.get(p) or {} for p in en_paths[:3]]
        en_btmp = _en_tmp(en_bl)
        en_bhead = io.StringIO()
        render([en_both[p] for p in sorted(en_both)], 2, encoding="cp1252",
               stream=en_bhead, spaced=True)
        en_bhead = en_bhead.getvalue().splitlines()[0]
        check("a combined --encoding cp1252 --spaced child sees both conditions "
              "and the leg heading names both: the child reports the forced "
              "codec AND a TMPDIR holding a space reached through the link "
              "(%r), its cases are counted (%r), the two contract-free suites "
              "are red there too (%r, %r), each single condition keeps the "
              "heading it always had, and the combined run's own heading "
              "reads %r"
              % (en_btmp, en_bl.get("cases"), en_bm.get("why"),
                 en_bg.get("why"), en_bhead),
              "ENC=cp1252" in (en_bl.get("output") or "")
              and " " in en_btmp and (os.sep + "via" + os.sep) in en_btmp
              and en_bl.get("ok") is True and en_bl.get("cases") == 3
              and en_bm.get("ok") is False and en_bg.get("ok") is False
              and _leg_label(None, False) == "sweep"
              and _leg_label("cp1252", False) == "encoding pass (cp1252)"
              and _leg_label(None, True) == "spaced sweep"
              and en_bhead.startswith("encoding pass (cp1252), spaced sweep: "))
    finally:
        remove_tree(en_work)

    # --- --shard I/N: a deterministic, cost-balanced split of the file list ---
    sh_full = sweep_files()
    sh_costs, sh_problem = load_costs(COSTS_PATH)
    sh_bad = []
    for sh_n in range(1, 5):
        sh_parts = shard_paths(sh_full, sh_costs, sh_n)
        sh_seen = [p for part in sh_parts for p in part]
        if not (len(sh_parts) == sh_n and all(sh_parts)
                and len(sh_seen) == len(set(sh_seen))
                and set(sh_seen) == set(sh_full)):
            sh_bad.append(sh_n)
    check("sh0 for N in 1..4 the shards of the LIVE file list are N non-empty, "
          "disjoint parts whose union is exactly the full sweep - so running "
          "every shard runs every file once: bad N = %r" % (sh_bad,),
          sh_bad == [] and len(sh_full) > 100)

    sh_rev = list(reversed(sh_full))
    check("sh1 the split is deterministic and independent of the order the "
          "list arrives in, so every CI job computes the same shards",
          all(shard_paths(sh_full, sh_costs, n) == shard_paths(sh_rev, sh_costs, n)
              for n in range(1, 5)))

    # A table of the case's own: the four heaviest are far above the rest, so a
    # split that put two of them together is visibly unbalanced.
    sh_paths = ["t/f%02d" % i for i in range(20)]
    sh_table = dict((p, 1.0) for p in sh_paths)
    sh_heavy = sh_paths[3:7]
    for p in sh_heavy:
        sh_table[p] = 100.0
    sh_spread = []
    for sh_n in range(2, 5):
        parts = shard_paths(sh_paths, sh_table, sh_n)
        holding = [len([p for p in part if p in sh_heavy]) for part in parts]
        if max(holding) - min(holding) > 1:
            sh_spread.append((sh_n, holding))
    check("sh2 the costliest files are SPREAD across shards - with four files "
          "a hundred times heavier than the rest, no shard holds two of them "
          "while another holds none, for N in 2..4: %r" % (sh_spread,),
          sh_spread == [])

    # ONE suite as heavy as nine others together: least-loaded keeps it ALONE in
    # its part, while dealing the files out in turn would hand it four companions.
    sh_one = dict(("u/f%d" % i, 10.0) for i in range(9))
    sh_one["u/big"] = 100.0
    sh_alone = shard_paths(sorted(sh_one), sh_one, 2)
    check("sh8 the heaviest suite gets its part to itself while the others "
          "together weigh less than it - the property that gives the slowest "
          "staged suite its runner's cores: %r" % (sh_alone,),
          ["u/big"] in sh_alone and len(sh_alone[1 - sh_alone.index(["u/big"])]) == 9)

    sh_loads = []
    for sh_n in range(2, 5):
        parts = shard_paths(sh_full, sh_costs, sh_n)
        loads = [sum(cost_of(sh_costs, p) for p in part) for part in parts]
        top = max(cost_of(sh_costs, p) for p in sh_full)
        if max(loads) - min(loads) > top:
            sh_loads.append((sh_n, loads, top))
    check("sh3 on the live list and the committed cost table, no two shards' "
          "recorded loads differ by more than the single costliest file - the "
          "bound a greedy least-loaded split guarantees: %r" % (sh_loads,),
          sh_loads == [])

    check("sh4 --shard reads I/N and refuses what names no shard: %r"
          % ([parse_shard(v) for v in ("1/3", "3/3")],),
          parse_shard("1/3") == (1, 3) and parse_shard("3/3") == (3, 3)
          and all(parse_shard(v) is None
                  for v in ("0/3", "4/3", "3", "x/3", "1/0", "", "-1/3")))

    sh_est = cost_of({"a": 2.0, "b": 4.0, "c": 9.0}, "new")
    check("sh5 a file the table has never timed is ESTIMATED at the table's "
          "median, not zero - a zero would pile every new file into one shard "
          "(got %r)" % (sh_est,),
          sh_est == 4.0 and cost_of({}, "new") == 1.0)

    sh_order = run_order(sh_paths, sh_table)
    check("sh6 a shard runs its costliest files FIRST, so the slowest suite "
          "starts at once and the rest pack around it: %r" % (sh_order[:4],),
          sorted(sh_order[:4]) == sorted(sh_heavy)
          and sorted(sh_order) == sorted(sh_paths))

    check("sh7 the committed cost table LOADS - a stale one is never a failure "
          "(sh9 and sh10 hold that), so only an unreadable table is red here "
          "(%s)" % (sh_problem or "read",),
          sh_problem is None)

    # A table naming a file that is gone and missing one that is swept: the split
    # still covers every swept file once, ignores the ghost, and says so.
    sh_ghost = dict((p, 1.0) for p in sh_paths[:10])
    sh_ghost["t/renamed-away"] = 500.0
    sh_ghost_parts = shard_paths(sh_paths, sh_ghost, 3)
    sh_ghost_seen = sorted(p for part in sh_ghost_parts for p in part)
    sh_ghost_plain = shard_paths(
        sh_paths, dict((p, 1.0) for p in sh_paths[:10]), 3)
    check("sh9 a table naming a file no longer swept and omitting swept ones "
          "still partitions the swept list exactly once, and the ghost entry "
          "does not move any file: %r" % (sh_ghost_parts,),
          sh_ghost_seen == sorted(sh_paths) and "t/renamed-away" not in sh_ghost_seen
          and sh_ghost_parts == sh_ghost_plain)

    sh_notes = table_notes(sh_ghost, sh_paths)
    check("sh10 a stale or partial table is REPORTED as notes, never as a "
          "failure: ghost entries named, and thin coverage said: %r"
          % (sh_notes,),
          len(sh_notes) == 2 and "t/renamed-away" in sh_notes[0]
          and table_notes(dict((p, 1.0) for p in sh_paths), sh_paths) == []
          and table_notes({}, []) == [])
    # The live table's notes are advisory: printed, never a case.
    for sh_note in table_notes(sh_costs, sh_full):
        sys.stdout.write("note: %s\n" % (sh_note,))

    check("j1 a CI runner gets EVERY core and a workstation keeps two free: "
          "%r" % ([default_jobs(4, {"CI": "true"}), default_jobs(4, {})],),
          default_jobs(4, {"CI": "true"}) == 4 and default_jobs(4, {}) == 2
          and default_jobs(4, {"CI": "false"}) == 2
          and default_jobs(1, {"CI": "true"}) == 1)

    rc_rows = [{"path": "a", "seconds": 1.234}, {"path": "b", "seconds": 7.0},
               {"path": "c", "exempt": "x"},
               {"path": "d", "seconds": 10.0, "grant": 3}]
    rc_got = costs_from_rows(rc_rows)
    check("rc0 a recorded run's costs are the per-file slot-seconds it measured - "
          "seconds times the slots held - rounded, and a file the leg did not "
          "run is not given a cost: %r" % (rc_got,),
          rc_got == {"a": 1.2, "b": 7.0, "d": 30.0})

    # --- one concurrency budget: staged suites hold several slots ------------
    import importlib.util
    bg_spec = importlib.util.spec_from_file_location(
        "sweep_harness_bg", os.path.join(REPO, "tests", "_harness.py"))
    bg_h = importlib.util.module_from_spec(bg_spec)
    bg_spec.loader.exec_module(bg_h)
    check("bg0 the grant's variable names and cap are the ones `_harness.py` "
          "reads - two copies, held together here: %r"
          % ([bg_h.STAGE_GRANT_VAR, bg_h.FILE_TIMEOUT_VAR, bg_h.STAGE_WORKERS],),
          bg_h.STAGE_GRANT_VAR == STAGE_GRANT_VAR
          and bg_h.FILE_TIMEOUT_VAR == FILE_TIMEOUT_VAR
          and bg_h.STAGE_WORKERS == STAGE_GRANT_MAX)
    # TWO COPIES OF ONE SETTING, held together the way bg0 holds the grant: the
    # harness prefix serves a suite run outside the sweep, the runner's set serves
    # every suite inside it, and a key dropped from one would leave the two runs of
    # one suite housekeeping differently.
    _prefix = list(bg_h.NO_AUTO_MAINTENANCE)
    _prefixed = sorted(_prefix[i + 1] for i in range(0, len(_prefix), 2)
                       if _prefix[i] == "-c")
    _runner = dict(GIT_ENV)
    _set = sorted("%s=%s" % (_runner["GIT_CONFIG_KEY_%d" % (i,)],
                             _runner["GIT_CONFIG_VALUE_%d" % (i,)])
                  for i in range(int(_runner.get("GIT_CONFIG_COUNT", "0")))
                  if "GIT_CONFIG_KEY_%d" % (i,) in _runner)
    check("gm3 ...the harness prefix a suite outside the sweep uses switches off "
          "the same keys the runner's set does: prefix %r, runner %r"
          % (_prefixed, _set),
          _prefixed == ["gc.auto=0", "maintenance.auto=false"]
          and all(p in _set for p in _prefixed))
    bg_grants = dict((j, stage_grant(j)) for j in (1, 2, 3, 4, 5, 8, 12, 64))
    check("bg1 a staged suite holds all but one of the budget's slots, at least "
          "two, at most the cap, never more than the budget: %r" % (bg_grants,),
          bg_grants == {1: 1, 2: 2, 3: 2, 4: 3, 5: 4, 8: STAGE_GRANT_MAX,
                        12: STAGE_GRANT_MAX, 64: STAGE_GRANT_MAX})
    bg_src = {
        "attr": "import _harness\nraise SystemExit(_harness.staged_main([], (), {}, 'p'))\n",
        "name": "from _harness import staged_main\nstaged_main([], (), {}, 'p')\n",
        "string": "X = 'staged_main(argv)'\n",
        "define": "def staged_main(argv):\n    return 0\n",
        "broken": "staged_main(\n",
    }
    bg_seen = dict((k, is_staged(v)) for k, v in bg_src.items())
    check("bg2 a staged suite is one that CALLS `staged_main`, read off the AST - "
          "a string or a definition naming it is not, and neither is a file "
          "that does not parse: %r" % (bg_seen,),
          bg_seen == {"attr": True, "name": True, "string": False,
                      "define": False, "broken": False})
    bg_live = staged_paths(sweep_files())
    check("bg2b ...and over the live tree the staged suites are found and the "
          "harness that defines the runner is not: %r" % (sorted(bg_live),),
          "tests/test_drive_phase.py" in bg_live
          and "tests/_harness.py" not in bg_live)
    bg_costs = {"heavy": 450.0, "light": 10.0}
    bg_to = [file_timeout("heavy", bg_costs), file_timeout("light", bg_costs),
             file_timeout("never", bg_costs),
             file_timeout("heavy", bg_costs, 9000),
             file_timeout("heavy", {"heavy": 225.1}),
             file_timeout("heavy", bg_costs, slots=3)]
    check("bg3 a file's timeout is the floor, or `TIMEOUT_PER_COST` times its "
          "recorded slot-seconds over the slots it holds when that is longer - "
          "rounded up, never under the floor, the floor for a file never "
          "timed: %r" % (bg_to,),
          bg_to == [450 * TIMEOUT_PER_COST, DEFAULT_TIMEOUT, DEFAULT_TIMEOUT,
                    9000, int(-(-225.1 * TIMEOUT_PER_COST // 1)),
                    450 * TIMEOUT_PER_COST // 3]
          and min(bg_to[0], bg_to[4], bg_to[5]) > DEFAULT_TIMEOUT)

    bg_wait, bg_done = slot_gate(4)
    bg_lock = threading.Lock()
    bg_state = {"held": 0, "peak": 0, "order": []}
    bg_weights = [3, 1, 1, 3, 1, 1, 2]

    def bg_task(ticket):
        weight = bg_weights[ticket]
        bg_wait(ticket, weight)
        with bg_lock:
            bg_state["held"] += weight
            bg_state["peak"] = max(bg_state["peak"], bg_state["held"])
            bg_state["order"].append(ticket)
        time.sleep(0.05)
        with bg_lock:
            bg_state["held"] -= weight
        bg_done(weight)
    with futures.ThreadPoolExecutor(max_workers=4) as bg_pool:
        list(bg_pool.map(bg_task, range(len(bg_weights))))
    check("bg4 the slot gate never lets more than the budget be held at once and "
          "admits in ticket order - a cheap file cannot slip past a staged suite "
          "waiting for its slots: %r" % (bg_state,),
          bg_state["peak"] <= 4 and bg_state["peak"] >= 3
          and bg_state["order"] == list(range(len(bg_weights))))

    bg_box = tempfile.mkdtemp(prefix="sweep-budget-")
    try:
        bg_body = ("import os\n"
                   "print('grant=' + str(os.environ.get(%r)) + ' timeout=' + "
                   "str(os.environ.get(%r)))\n"
                   "print('1/1 cases passed')\n"
                   % (STAGE_GRANT_VAR, FILE_TIMEOUT_VAR))
        with io.open(os.path.join(bg_box, "plain-suite"), "w", encoding="utf-8") as fh:
            fh.write(bg_body)
        with io.open(os.path.join(bg_box, "staged-suite"), "w", encoding="utf-8") as fh:
            fh.write(bg_body + "if False:\n    staged_main()\n")
        bg_one = run_one("plain-suite", repo=bg_box, timeout=77, grant=3,
                         environ=dict(os.environ, **{STAGE_GRANT_VAR: "9"}))
        check("bg5 a child is told the slots it holds and its timeout, over any "
              "grant the caller's environment carried: %r" % (bg_one["output"],),
              "grant=3 timeout=77" in bg_one["output"])
        bg_rows = dict((r["path"], r) for r in sweep(
            ["plain-suite", "staged-suite"], jobs=4, repo=bg_box,
            costs={"staged-suite": 900.0}))
        check("bg6 the sweep holds `stage_grant(jobs)` slots for a staged suite "
              "and one for any other file, gives the timed-heavy one its "
              "calibrated timeout, and tells each child so: %r"
              % (dict((k, (v.get("grant"), v.get("timeout"), v.get("output")))
                      for k, v in bg_rows.items()),),
              bg_rows["staged-suite"]["grant"] == 3
              and "grant=3 timeout=%d" % (300 * TIMEOUT_PER_COST,)
              in bg_rows["staged-suite"]["output"]
              and bg_rows["plain-suite"]["grant"] == 1
              and "grant=1 timeout=%d" % (DEFAULT_TIMEOUT,)
              in bg_rows["plain-suite"]["output"]
              and all(r["ok"] for r in bg_rows.values()))
        bg_line = budget_line(["plain-suite", "staged-suite"], 4, {"staged-suite": 900.0},
                              DEFAULT_TIMEOUT, repo=bg_box)
        bg_cut = budget_line(["plain-suite", "staged-suite"], 4, {"staged-suite": 900.0},
                             DEFAULT_TIMEOUT, repo=bg_box, deadline=500)
    finally:
        remove_tree(bg_box)
    check("bg6b the budget line says what each number came from - the slots, "
          "which suites hold several and how many, the floor and the longest "
          "calibrated timeout: %r" % (bg_line,),
          bg_line.startswith("budget: 4 slots; 1 staged suites hold 3 each "
                             "(staged-suite); per-file timeout %ds"
                             % (DEFAULT_TIMEOUT,))
          and "up to %ds" % (300 * TIMEOUT_PER_COST,) in bg_line
          and "deadline" not in bg_line
          and "up to 500s" in bg_cut and "named by 500s" in bg_cut)

    bg_buf = io.StringIO()
    render([dict(grade("a/heavy-suite", 0, "2/2 cases passed\n", set()),
                 seconds=123.45, grant=3),
            dict(grade("a/light-suite", 0, "1/1 cases passed\n", set()),
                 seconds=0.5, grant=1),
            dict(grade("a/hung-suite", None, "did not finish within 300s", set()),
                 seconds=300.04, grant=1),
            grade("a/untimed-suite", 0, "1/1 cases passed\n", set())],
           4, stream=bg_buf)
    bg_text = bg_buf.getvalue()
    bg_ci = "\n".join("2026-10-13T08:43:25.2Z " + line.replace("a/", "a\\")
                      for line in bg_text.splitlines())
    bg_read = [costs_from_render(bg_text), costs_from_render(bg_ci)]
    check("bg7 the loud form prints each file's seconds - and the slots it held "
          "when more than one - and those lines read back as slot-seconds, from a CI "
          "log's timestamped, back-slashed lines too, a timeout's included and "
          "an untimed row left out: %r / %r" % (bg_text, bg_read),
          "[123.5s, 3 slots]" in bg_text and "[0.5s]" in bg_text
          and bg_read[0] == bg_read[1]
          == {"a/heavy-suite": 370.5, "a/light-suite": 0.5, "a/hung-suite": 300.0})
    bg_twice = costs_from_render(bg_text + "\n" + bg_text.replace(
        "[123.5s, 3 slots]", "[23.5s, 3 slots]").replace("[0.5s]", "[9.0s]"))
    check("bg7b a log carrying one file twice - two legs, two runs - records the "
          "LONGER of its timings, whichever came first, because the table is "
          "what sets a timeout and the slower run is the one it must fit: %r"
          % (bg_twice,),
          bg_twice.get("a/heavy-suite") == 370.5
          and bg_twice.get("a/light-suite") == 9.0)

    # --- a stale table never tightens a timeout; a deadline names a hang ------
    tt_box = tempfile.mkdtemp(prefix="sweep-deadline-")
    try:
        tt_ok = "print('1/1 cases passed')\n"
        tt_files = {
            "plain-suite": tt_ok,
            "staged-suite": tt_ok + "if False:\n    staged_main()\n",
            "a-slow": "import time\ntime.sleep(1.5)\n" + tt_ok,
            "b-quick": tt_ok,
            "hung": "import time\ntime.sleep(60)\n" + tt_ok,
        }
        for tt_name, tt_body in tt_files.items():
            with io.open(os.path.join(tt_box, tt_name), "w",
                         encoding="utf-8") as fh:
                fh.write(tt_body)
        # The table times neither suite: its one entry names a file that is
        # gone (a ghost - the shape a rename leaves). 1000 slot-seconds over
        # the three slots the staged suite holds is well above the floor at
        # any factor of one or more, so the floor and the calibrated figure
        # cannot coincide.
        tt_rows = dict((r["path"], r) for r in sweep(
            ["plain-suite", "staged-suite"], jobs=4, repo=tt_box,
            costs={"renamed-away": 1000.0}))
        tt_want = int(-(-TIMEOUT_PER_COST * 1000.0 // 3))
        check("tt0 a STAGED suite the cost table does not time gets the largest "
              "timeout any entry in it would be given at the same slots - a "
              "ghost's included - never the floor, while an untimed ordinary "
              "file gets the floor: %r"
              % (dict((k, v.get("timeout")) for k, v in tt_rows.items()),),
              tt_rows["staged-suite"].get("timeout") == tt_want
              and tt_want > DEFAULT_TIMEOUT
              and tt_rows["plain-suite"].get("timeout") == DEFAULT_TIMEOUT
              and all(r["ok"] for r in tt_rows.values()))
        tt_heavy = {"heavy": 1500.0, "light": 10.0}
        tt_to = [file_timeout("new", tt_heavy, slots=3, staged=True),
                 file_timeout("new", tt_heavy, slots=3, staged=False),
                 file_timeout("heavy", tt_heavy, slots=3, staged=True),
                 file_timeout("new", {}, slots=3, staged=True),
                 file_timeout("new", tt_heavy, slots=3, staged=True, cap=400)]
        check("tt1 ...and directly: a staged file with no entry is never given "
              "less than the heaviest recorded staged file holding the same "
              "slots, an ordinary one gets the floor, an empty table gives the "
              "floor, and a cap bounds every answer: %r" % (tt_to,),
              tt_to == [int(-(-TIMEOUT_PER_COST * 1500.0 // 3)), DEFAULT_TIMEOUT,
                        int(-(-TIMEOUT_PER_COST * 1500.0 // 3)), DEFAULT_TIMEOUT,
                        400]
              and tt_to[0] > DEFAULT_TIMEOUT)

        tt_late = dict((r["path"], r) for r in sweep(
            ["a-slow", "b-quick"], jobs=1, repo=tt_box,
            costs={"a-slow": 100.0}, deadline=60))
        check("tt2 under a deadline a file started late is given only what is "
              "left of it - one worker, so `b-quick` starts after `a-slow`'s "
              "1.5s and gets under the 60s the first file got: %r"
              % (dict((k, v.get("timeout")) for k, v in tt_late.items()),),
              tt_late["a-slow"].get("timeout") <= 60
              and tt_late["b-quick"].get("timeout") < 60
              and all(r["ok"] for r in tt_late.values()))
        tt_t0 = time.time()
        tt_hung = sweep(["hung"], jobs=1, repo=tt_box, deadline=3)[0]
        tt_took = time.time() - tt_t0
        check("tt3 a file that hangs past the deadline is NAMED as a timeout "
              "when the deadline falls, not waited on until its own calibrated "
              "timeout - which is what lets the sweep say which file hung "
              "before the CI job's own limit kills it: %r after %.1fs"
              % (tt_hung.get("why"), tt_took),
              tt_hung["ok"] is False
              and "did not finish within" in (tt_hung.get("why") or "")
              and tt_took < 30)
    finally:
        remove_tree(tt_box)

    tt_env = [sweep_deadline({"CI": "true"}), sweep_deadline({"CI": "false"}),
              sweep_deadline({})]
    check("tt4 the deadline applies on a CI runner, where a job limit exists to "
          "beat, and nowhere else - a workstation run has no runner to be "
          "killed by: %r" % (tt_env,),
          tt_env == [SWEEP_DEADLINE, None, None])
    tt_ci_path = os.path.join(REPO, ".github", "workflows", "ci.yml")
    with io.open(tt_ci_path, encoding="utf-8") as fh:
        tt_ci = fh.read()
    tt_job = re.search(r"^  selftests:\n(?:    .*\n)*?    timeout-minutes: (\d+)",
                       tt_ci, re.M)
    tt_minutes = int(tt_job.group(1)) if tt_job else None
    tt_costs, _tt_problem = load_costs(COSTS_PATH)
    tt_live = sweep_files()
    tt_staged = staged_paths(tt_live)
    tt_grant = stage_grant(4)
    tt_most = max(file_timeout(p, tt_costs, DEFAULT_TIMEOUT,
                               tt_grant if p in tt_staged else 1,
                               staged=p in tt_staged)
                  for p in tt_live)
    check("tt5 the deadline plus the setup allowance fits inside the `selftests` "
          "job's own timeout-minutes in ci.yml, so a hung file is named before "
          "the runner cancels the job, and no file's CALIBRATED timeout on the "
          "live table reaches past it - so the deadline cuts only a hang, not the "
          "margin a heavy file was given: deadline %ds + setup %ds vs %r minutes; longest "
          "file timeout %ds" % (SWEEP_DEADLINE, CI_SETUP_ALLOWANCE, tt_minutes,
                                tt_most),
          tt_minutes is not None
          and SWEEP_DEADLINE + CI_SETUP_ALLOWANCE < tt_minutes * 60
          and tt_most <= SWEEP_DEADLINE)

    # --- a mutating gate sweep holds a marker; this sweep refuses to read the tree ---
    import _suite
    mk_box = tempfile.mkdtemp(prefix="sweep-marker-")
    try:
        mk_dead = subprocess.Popen([sys.executable, "-c", "pass"])
        mk_dead.wait()
        mk_out, mk_err = io.StringIO(), io.StringIO()
        check("mk0 no marker: the sweep proceeds and says nothing",
              marker_gate(mk_box, mk_out, mk_err) is None
              and mk_out.getvalue() == "" and mk_err.getvalue() == "")

        _suite.hold(mk_box, pid=os.getpid())
        mk_out, mk_err = io.StringIO(), io.StringIO()
        mk_code = marker_gate(mk_box, mk_out, mk_err)
        check("mk1 a LIVE marker refuses with exit 2 and names the marker file and "
              "the pid: %r" % (mk_err.getvalue(),),
              mk_code == 2 and _suite.MARKER_NAME in mk_err.getvalue()
              and str(os.getpid()) in mk_err.getvalue())

        _suite.hold(mk_box, pid=mk_dead.pid)
        mk_out, mk_err = io.StringIO(), io.StringIO()
        mk_code = marker_gate(mk_box, mk_out, mk_err)
        check("mk2 a marker whose pid is DEAD is ignored - the sweep proceeds - and "
              "says that it did: %r / %r" % (mk_out.getvalue(), mk_err.getvalue()),
              mk_code is None and "stale" in mk_out.getvalue()
              and str(mk_dead.pid) in mk_out.getvalue())
    finally:
        remove_tree(mk_box)

    # --- a named list of suites: exactly those, under the same grading -------
    # Three halves, because each fails alone. The reading of argv (a flag's
    # VALUE is not a path; an unknown path is refused by name, never dropped);
    # the run (the named files and no other, each graded by the rule a whole
    # sweep applies - the contract and the scratch-directory watch included);
    # and the wiring through `main`, which a correct reader and a correct
    # sweep would both pass with `main` still running the whole tree.
    nl_title = ("a sweep given suite paths runs exactly those (graded by the "
                "same rules, contract and debris included) and refuses a path "
                "that is not a suite in the tree, naming it")
    # Fixture names carry no extension: the interpreter runs a path whatever it
    # is called, and a name ending in the Python one would read as a reference.
    nl_swept = ["tests/test_a", "tools/b", "tools/c",
                "tools/d"]
    nl_read = named_suites(["--jobs", "3", "tools/c", "--quiet",
                            "tests/test_a", "--timeout=9",
                            "--encoding", "cp1252", "tools/c"], nl_swept)
    nl_whole = named_suites(["--jobs", "3", "--record-costs", "tools/b",
                             "--quiet"], nl_swept)
    nl_unknown = named_suites(["tools/b", "README.md", "tools/gone"],
                              nl_swept)
    nl_shard = named_suites(["--shard", "1/3", "tools/b"], nl_swept)
    nl_box = tempfile.mkdtemp(prefix="sweep-named-")
    try:
        nl_bodies = {
            "ok": "print('ALL PASS: 2/2 cases passed')\n",
            "silent": "print('ran some things')\n",
            "leaky": ("open('left-here.txt', 'w').write('x')\n"
                      "print('ALL PASS: 1/1 cases passed')\n"),
            "unnamed": "print('ALL PASS: 1/1 cases passed')\n",
        }
        for nl_name, nl_body in nl_bodies.items():
            with io.open(os.path.join(nl_box, nl_name), "w",
                         encoding="utf-8") as nl_fh:
                nl_fh.write(nl_body)
        nl_named, nl_why = named_suites(["leaky", "silent", "ok"],
                                        sorted(nl_bodies))
        nl_rows = dict((r["path"], r) for r in sweep(
            nl_named or [], jobs=2, repo=nl_box, timeout=30))
    finally:
        remove_tree(nl_box)
    nl_refused = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--jobs", "2",
         "tools/not-a-suite"], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=120)
    nl_real = "tests/test__cli_fmt.py"
    nl_ran = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--jobs", "2", nl_real],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    nl_text = nl_ran.stdout.decode("utf-8", "replace")
    nl_err = nl_refused.stderr.decode("utf-8", "replace")
    nl_rowlines = [ln.split()[1] for ln in nl_text.splitlines()
                   if ln.startswith("  ok ") or ln.startswith("  FAILED ")]
    check("%s: read %r, whole %r, unknown %r, shard %r; rows %r; refused exit "
          "%r %r / out %r; real exit %r rows %r tail %r"
          % (nl_title, nl_read, nl_whole, nl_unknown, nl_shard,
             dict((p, (r["ok"], r["why"])) for p, r in nl_rows.items()),
             nl_refused.returncode, nl_err[-200:],
             nl_refused.stdout.decode("utf-8", "replace")[-120:],
             nl_ran.returncode, nl_rowlines, nl_text[-160:]),
          nl_read == (["tests/test_a", "tools/c"], None)
          and nl_whole == ([], None)
          and nl_unknown[0] is None
          and "README.md" in (nl_unknown[1] or "")
          and "tools/gone" in (nl_unknown[1] or "")
          and "tools/b" not in (nl_unknown[1] or "")
          and nl_shard[0] is None and "--shard" in (nl_shard[1] or "")
          and nl_why is None
          and sorted(nl_rows) == ["leaky", "ok", "silent"]
          and nl_rows["ok"]["ok"] and nl_rows["ok"]["cases"] == 2
          and not nl_rows["silent"]["ok"]
          and "no --selftest" in (nl_rows["silent"]["why"] or "")
          and not nl_rows["leaky"]["ok"]
          and "left-here.txt" in (nl_rows["leaky"]["why"] or "")
          and nl_refused.returncode == 2
          and "tools/not-a-suite" in nl_err
          and b"sweep:" not in nl_refused.stdout
          and nl_ran.returncode == 0 and nl_rowlines == [nl_real]
          and "1/1 files ok" in nl_text)

    # --- the legacy pass also changes the locale, and checks that it took -----
    # The suite reads a file holding valid UTF-8 with no encoding named. Under a
    # UTF-8 locale that is fine, so a pass that only set the stdio codec never saw
    # the defect; under the legacy locale it must raise. The second suite names its
    # encoding and must pass under both. The pins are the ones this machine's
    # verdict settles, as `main` hands them on: where it keeps the stdio half
    # only (windows, linux's C locale) the bare suite's verdict is not asserted.
    ll_title_a = ("under --encoding cp1252 a child suite that reads a UTF-8 file "
                  "with no encoding fails where the locale is pinned, and the "
                  "same suite naming its encoding passes")
    ll_title_b = ("a legacy-encoding pass whose child still reports UTF-8 as its "
                  "preferred encoding is refused as could-not-run where the pins "
                  "are applied, naming the encoding it saw, and windows, given "
                  "none, is neither asked nor refused")
    ll_verdict = legacy_locale_verdict(environ=os.environ)
    ll_box = tempfile.mkdtemp(prefix="sweep-locale-")
    try:
        with io.open(os.path.join(ll_box, "data"), "wb") as ll_fh:
            ll_fh.write(u"café".encode("utf-8"))
        ll_head = ("import os\n"
                   "p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "
                   "'data')\n")
        ll_bodies = {
            "bare": ll_head + "t = open(p).read()\n"
                    "print('ALL PASS: 1/1 cases passed')\n",
            "named": ll_head + "t = open(p, encoding='utf-8').read()\n"
                     "print('ALL PASS: 1/1 cases passed')\n",
        }
        for ll_name, ll_body in ll_bodies.items():
            with io.open(os.path.join(ll_box, ll_name), "w",
                         encoding="utf-8") as ll_fh:
                ll_fh.write(ll_body)
        # The plain half is given a UTF-8 environment explicitly: this suite may
        # itself be running under the legacy pass, and inheriting its pins would
        # make the "reads fine under UTF-8" premise false.
        ll_utf8 = dict(os.environ, LC_ALL="C.UTF-8", PYTHONUTF8="1")
        ll_plain = dict((n, run_one(n, repo=ll_box, timeout=30, environ=ll_utf8))
                        for n in ("bare", "named"))
        ll_legacy = dict((r["path"], r) for r in sweep(
            ["bare", "named"], jobs=2, repo=ll_box, timeout=30,
            encoding="cp1252", locale_vars=ll_verdict["locale"]))
    finally:
        remove_tree(ll_box)
    check("%s (pins %r: plain %r, legacy %r)" % (
              ll_title_a, ll_verdict["locale"],
              dict((p, r["code"]) for p, r in ll_plain.items()),
              dict((p, (r["ok"], r["why"])) for p, r in ll_legacy.items())),
          ll_verdict["problem"] is None
          and ll_plain["bare"]["code"] == 0 and ll_plain["named"]["code"] == 0
          and ll_legacy["named"]["ok"]
          and (not ll_verdict["locale"] or (
              not ll_legacy["bare"]["ok"]
              and "exited" in ll_legacy["bare"]["why"])))

    ll_good = legacy_locale_verdict(environ=os.environ)
    ll_bad = legacy_locale_verdict(
        environ=os.environ, locale_vars={"PYTHONUTF8": "1", "LC_ALL": "C.UTF-8"})
    # Each platform's own contract, asserted rather than skipped: windows is
    # given no pins and asked nothing, so neither run refuses there.
    if os.name == "nt":
        ll_b_ok = (ll_good["problem"] is None and ll_bad["problem"] is None
                   and ll_good["reported"] is None and not ll_good["locale"])
    else:
        ll_b_ok = (ll_good["problem"] is None and ll_bad["problem"] is not None
                   and "could-not-run" in ll_bad["problem"]
                   and ("utf-8" in ll_bad["problem"].lower()
                        or "utf8" in ll_bad["problem"].lower()))
    check("%s (on %s: honest %r, UTF-8 child %r)"
          % (ll_title_b, os.name, ll_good, ll_bad), ll_b_ok)

    # --- the pin is kept only where it is faithful ----------------------------
    # Fed the pair each platform's child REPORTED under the pins (measured:
    # macOS a non-UTF-8 preferred encoding with UTF-8 file names, linux's C
    # locale ASCII for both, windows not asked). A pin that also makes file
    # NAMES ASCII simulates no platform, so linux runs the stdio half only and
    # says so. The macOS row is there for the other direction: a decision that
    # never pins would pass every other row.
    ll_title_c = ("the legacy-encoding pass pins a locale only where the child "
                  "then has a non-UTF-8 preferred encoding and a UTF-8 "
                  "filesystem encoding, and says which half ran where it cannot")
    ll_rows = {
        "macos": locale_decision("posix", ("US-ASCII", "utf-8"), "cp1252"),
        "linux": locale_decision("posix", ("ANSI_X3.4-1968", "ascii"), "cp1252"),
        "windows": locale_decision("nt", None, "cp1252"),
        "utf8": locale_decision("posix", ("UTF-8", "utf-8"), "cp1252"),
    }
    ll_os = {"macos": "posix", "linux": "posix", "windows": "nt", "utf8": "posix"}
    ll_pins = dict((k, locale_pins(ll_os[k], "cp1252", v["locale"]))
                   for k, v in ll_rows.items() if v["problem"] is None)
    ll_live = legacy_locale_verdict(environ=os.environ)
    check("%s (%r; pins %r; this machine %r)" % (ll_title_c, ll_rows, ll_pins,
                                                 ll_live),
          ll_rows["macos"]["problem"] is None
          and ll_rows["macos"]["locale"] == LEGACY_LOCALE_VARS
          and ll_pins["macos"].get("LC_ALL") == "C"
          and "both halves" in ll_rows["macos"]["line"]
          and ll_rows["linux"]["problem"] is None
          and ll_rows["linux"]["locale"] == {}
          and "LC_ALL" not in ll_pins["linux"]
          and ll_pins["linux"].get("PYTHONIOENCODING") == "cp1252"
          and "only the stdio half" in ll_rows["linux"]["line"]
          and "ascii" in ll_rows["linux"]["line"]
          and ll_rows["windows"]["problem"] is None
          and ll_rows["windows"]["locale"] == {}
          and "only the stdio half" in ll_rows["windows"]["line"]
          and "windows" in ll_rows["windows"]["line"]
          and ll_rows["utf8"]["problem"] is not None
          and "could-not-run" in ll_rows["utf8"]["problem"]
          and (os.name == "nt" or (ll_live["reported"] is not None
                                   and len(ll_live["reported"]) == 2)))


    # --- the pins are a function of the platform asked about ------------------
    # Each platform's pins computed for every os_name the table holds, so a
    # host that is one of them cannot stand in for another. The windows asking
    # for a macOS-shaped verdict is the row that goes red when the host's own
    # os.name leaks back in; the posix asking for windows's empty verdict is
    # the other direction, where pins must not appear from nowhere.
    ll_mac = locale_decision("posix", ("US-ASCII", "utf-8"), "cp1252")
    ll_posix_default = locale_pins("posix", "cp1252")
    ll_mac_on_nt = locale_pins("nt", "cp1252", ll_mac["locale"])
    ll_mac_on_posix = locale_pins("posix", "cp1252", ll_mac["locale"])
    ll_win_on_posix = locale_pins("posix", "cp1252",
                                  locale_decision("nt", None, "cp1252")["locale"])
    ll_win_default = locale_pins("nt", "cp1252")
    check("the pins for a platform are the same whichever host computes them "
          "(%r %r %r %r %r)" % (ll_posix_default, ll_mac_on_nt, ll_mac_on_posix,
                                ll_win_on_posix, ll_win_default),
          ll_mac_on_nt == ll_mac_on_posix
          and ll_mac_on_nt == dict(LEGACY_LOCALE_VARS, PYTHONIOENCODING="cp1252")
          and ll_posix_default == ll_mac_on_posix
          and ll_win_on_posix == {"PYTHONIOENCODING": "cp1252"}
          and ll_win_default == {"PYTHONIOENCODING": "cp1252"}
          and locale_pins("nt", None) == {})


def _selftest():
    from _suite import run         # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
