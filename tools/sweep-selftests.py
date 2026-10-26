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

AND THE CHECKOUT'S OWN `.claude/` IS A THIRD, WATCHED BY LOOKING: neither directory
above is one a suite that finds its project by its own location ever touches, so a
suite doing that wrote its restore points and ignore lines into the real checkout
with the cwd and the home both spotless. It is read before the pool starts and after
it drains, and a write is pinned on a suite only when exactly one suite's run holds
the moment it happened - otherwise it is reported unattributed, naming every
candidate. A removal or a directory made with something in it has no time of its
own to read, so a removal is reported unattributed and the directory is reported
through what is in it. The run REFUSES TO START when its temp directory has a `.git`
above it (`scratch_refusal`), which is the prevention half of this watch; the
snapshot is the detection half. The comment above `CLAUDE_CHANNEL` has the rest,
including what is left out and why.

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
# budget - the sweep's `jobs` slots. A staged suite whose `STAGES` table the
# sweep reads has every block run as a job of its own, one slot each (`blocks,
# not suites`, below). One whose table it cannot read is run whole and holds
# several slots at once: up to `stage_grant(jobs)` of them, admitted in
# submission order with what is free when its turn comes (`slot_gate`), and the
# number it holds goes to the child in `STAGE_GRANT_VAR`, which
# `_harness.stage_workers()` reads. The name and the cap are `_harness.py`'s
# too; case bg0 fails when the two copies part.
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


# --- the checkout's own .claude/, the third watched directory --------------------
# THE TWO WATCHED DIRECTORIES ARE ONES THE RUNNER HANDS THE CHILD, and a suite that
# is handed neither and finds its project by its OWN location writes into neither.
# That is how a restore point and an ignore line appeared in the clone's `.claude/`
# during a whole-tree sweep with no layout command in sight: a suite resolved its
# project from where it sits, and the layout migration's backup went into the real
# checkout. The cwd and the home looked spotless because the write was never there.
#
# THE CHECKOUT'S `.claude/` IS THEREFORE WATCHED BY LOOKING, not by handing the
# child anything: one snapshot before the pool starts, one after it drains, and the
# difference is the finding. That is the only shape that works here - the directory
# is shared by every child at once, so a per-child planted file would be a lie about
# which child wrote.
#
# WHICH CHILD WROTE is read off the clock, and honestly. Every child records the
# wall-clock window it ran in, and a changed entry's own modification time says
# when it changed. Exactly one window holding that moment names the suite. Two or
# more windows - the normal case when twelve children run together - name NO suite:
# the finding is reported against `CLAUDE_ROW` with every candidate listed, and the
# fix is the re-run it prints (`--jobs 1`, where the windows cannot overlap). A
# change that falls in no window at all is reported the same way. Blaming whichever
# candidate sorted first would make a clean suite red on the day somebody else
# leaked, which is how a guard gets switched off.
#
# THE LIVE SESSION'S OWN SLOTS IN `state/` ARE LEFT OUT BY NAME, AND NOTHING ELSE IN
# IT IS. The sweep is usually typed from inside the session that writes them, and
# `state/` once was left out whole - which hid a suite that wrote its own file
# there, a blind spot a suite really wrote through. `CLAUDE_LIVE_WRITES` is the
# narrow table that replaced the row: a pattern per name the hooks and the drive
# give a slot, each with the writer and the observation that put it there. A name
# no row matches is a suite's, and a name a session starts to write that no row
# knows reddens the sweep until a row (with its evidence) is added - which is the
# direction a guard should fail in. Walking `state/` costs a listing of its names;
# the left-out ones are matched by name BEFORE any entry is stat'ed, so the
# hundreds a long-lived session accumulates (`ls .claude/state | wc -l` counts
# them) cost a match each and not a system call.
#
# THE REST OF THE LIVE SESSION'S RUNTIME DIRECTORIES ARE STILL NOT WATCHED:
# each row of `CLAUDE_UNWATCHED` says why it is left out, and a suite that writes
# under one of them is the blind spot of this guard. That table is where to narrow
# them, the way `state/` was.
#
# AND THE RUNNER REFUSES TO START WHEN ITS OWN SCRATCH IS INSIDE A CHECKOUT
# (`scratch_refusal`): every directory a child is handed is made under the temp
# directory, and one with a `.git` above it makes the children's world a part of a
# checkout - the cwd, the home and the fixtures all resolve into the tree this
# watch exists to protect. That is the prevention half; the snapshot is the
# detection half, for a suite that finds the checkout by its own location whatever
# the temp directory is.
CLAUDE_CHANNEL = "checkout .claude"
CLAUDE_ROW = ".claude/ (the checkout's own)"
_SID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SLOT = "(?:[.-][0-9a-f]+)*"
# Rows are `(pattern over the path below .claude/, an example name, the sentence)`.
# The example is a name the table must skip and a one-character misspelling of it
# must not be - case `cw10` drives every row that way. The sentence names the
# writer and the observation, re-derivable as `find .claude/state -maxdepth 1
# -mmin -240` while a session works: every pattern here was among what that listed
# in a live checkout, and a name that command did not list is not in this table.
CLAUDE_LIVE_WRITES = (
    ("^state/call-start-" + _SID + "(?:-[0-9a-f]+)?\\.json$",
     "state/call-start-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d.json",
     "the Pre pass's record of when a tool call started, one per call "
     "(CALL_START_FILE in hooks/_config.py)"),
    ("^state/journal-preimage-" + _SID + _SLOT + "\\.json$",
     "state/journal-preimage-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d-a1b2c3d4e5f60718"
     ".0123456789ab.json",
     "the pre-image slot the journal hook writes before a write and consumes "
     "after it (hooks/journal-writes.py), by far the most numerous entry listed"),
    ("^state/plan-gate-" + _SID + _SLOT + "\\.json$",
     "state/plan-gate-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d.a1b2c3d4e5f60718.json",
     "the plan gate's per-session slot (TRIVIAL_SLOT in hooks/_config.py)"),
    ("^state/bash-writes-" + _SID + "\\.json$",
     "state/bash-writes-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d.json",
     "the session slot guard-bash-writes keeps (BASH_WRITES_STATE_FILE in "
     "hooks/_config.py); the plugin sidecars sharing its prefix were not listed "
     "and are not left out"),
    ("^state/tdd-reminder-" + _SID + "\\.json$",
     "state/tdd-reminder-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d.json",
     "the reminder's once-per-session note (hooks/remind-tdd.py)"),
    ("^state/running-plugin-" + _SID + "\\.json$",
     "state/running-plugin-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d.json",
     "which plugin copy executes the hooks, rewritten on every prompt "
     "(RUNNING_STAMP in hooks/_config.py)"),
    ("^state/attempts(?:/|$)", "state/attempts/P1.1-abc.json",
     "the drive's per-task attempt record (ATTEMPT_DIR in "
     "scripts/governance/_scoped_commit.py)"),
    ("^state/briefs(?:/|$)", "state/briefs/P1.1-abc/20260101T000000Z.executor.md",
     "the briefs the drive hands its agents (BRIEFS_DIRNAME in "
     "scripts/manifest/_filed_returns.py)"),
    ("^state/drive(?:/|$)", "state/drive/P1.json",
     "the drive's per-phase progress record (DRIVE_DIRNAME in "
     "scripts/manifest/_filed_returns.py)"),
)
_LIVE_WRITES_RE = tuple(re.compile(row[0]) for row in CLAUDE_LIVE_WRITES)
CLAUDE_UNWATCHED = (
    ("logs", "hook logs the live session appends to"),
    ("usage", "the usage ledger the live session appends to"),
    ("worktrees", "linked worktrees the orchestrator creates and removes"),
    ("settings.local.json", "the user's own settings, edited by hand"),
    ("audit-panel.json", "the panel's pidfile, written by a running panel"),
    ("__pycache__", "bytecode the interpreter writes beside any module it imports"),
)

# The start of a child's window is widened by this much, because a filesystem
# stamps a modification time from a clock that can lag the one the window is read
# from. Only the START: a stamp is never later than the moment of the write. Small
# on purpose - every nanosecond of it makes a neighbouring child a candidate - and
# a filesystem coarser than this (FAT's two seconds) leaves a change with no
# window, which is reported loudly as unattributed and not missed.
CLAUDE_START_SLACK_NS = 20 * 1000 * 1000

# AT --jobs 1 the sweep waits this long after each child before the next one starts.
# The slack above widens a window's start, so two windows closer than it make the
# end of one and the start of the next candidates for the same stamp, and the
# re-run the unattributed row advises (`--jobs 1`) would then fail to name the
# writer in the one place it is supposed to. With the wait the windows cannot
# touch; the margin over the slack covers a clock read on either side of the wait.
CLAUDE_SERIAL_GAP_S = CLAUDE_START_SLACK_NS / 1e9 + 0.005


def claude_live_written(rel):
    """True when `rel` (a path below `.claude/`, with forward slashes) is a name
    the live session's hooks or the drive give a slot - a row of
    `CLAUDE_LIVE_WRITES` matches it."""
    return any(pattern.match(rel) for pattern in _LIVE_WRITES_RE)


def scratch_refusal(tmp, locate=None):
    """The sentence refusing a run whose temp directory lies inside a git checkout,
    or None when it does not.

    Every directory a child is handed is made under `tmp`, so a `.git` above it
    puts the child's cwd, home and fixtures inside a checkout - where a suite that
    finds its project by walking up from where it sits finds THAT checkout. The path
    is resolved first, so a symlinked temp root is judged by where it lies, and
    nothing else is tried: a temp directory the caller did not choose is not one
    to fall back to. `locate` is `_manifest_io.checkout_of` unless a case hands
    one in."""
    if locate is None:
        import _manifest_io
        locate = _manifest_io.checkout_of
    inside = locate(os.path.join(os.path.realpath(tmp), "x"))
    if inside is None:
        return None
    return ("the temp directory %s lies inside the git checkout %s (a .git is "
            "above it), so every scratch directory the children are handed would "
            "be inside a checkout and a suite that walks up for .git would find "
            "it; point TMPDIR at a directory with no .git above it"
            % (tmp, inside))


def claude_snapshot(repo):
    """{relative path: (kind, size, modification time in ns)} of the watched part of
    `repo`'s `.claude/`; `{}` when it holds none.

    An entry that vanishes between being listed and being stat'ed is skipped: that
    is a session removing it mid-walk, and the snapshot taken after reads it as
    absent, which is where the difference reports it.
    """
    top = os.path.join(repo, ".claude")
    skipped = set(name for name, _ in CLAUDE_UNWATCHED)
    seen = {}
    if not os.path.isdir(top):
        return seen
    for here, dirs, files in os.walk(top):
        # `__pycache__` is skipped wherever it sits; every other row names an
        # entry directly under `.claude/`, and a skills directory that happens to
        # hold a `state` of its own is still a suite's to leave alone.
        left = skipped if here == top else set(["__pycache__"])
        base = os.path.relpath(here, top).replace(os.sep, "/")

        def _rel(name):
            return name if base == "." else base + "/" + name
        # The live session's slots are matched by NAME here, before any entry is
        # stat'ed, and a directory of them is pruned whole.
        dirs[:] = sorted(d for d in dirs
                         if d not in left and not claude_live_written(_rel(d)))
        files = sorted(f for f in files
                       if f not in left and not claude_live_written(_rel(f)))
        entries = [(d, "dir") for d in dirs]
        entries.extend((f, "file") for f in files)
        for name, kind in entries:
            try:
                st = os.lstat(os.path.join(here, name))
            except OSError:
                continue
            seen[_rel(name)] = (kind, st.st_size if kind == "file" else 0,
                                st.st_mtime_ns)
    try:
        seen["."] = ("dir", 0, os.lstat(top).st_mtime_ns)
    except OSError:
        pass
    return seen


def claude_changes(before, after):
    """What differs between two snapshots: a list of
    `{"path", "text", "at"}`, sorted by path. `at` is the nanosecond the change
    happened, or None when the snapshots hold no time for it.

    A change is TIMED only by a stamp that is its own, and a change that has none
    says so (`"untimed"`, a sentence) rather than borrowing a neighbour's:

      * a file added or rewritten carries its own modification time;
      * a directory added with nothing in it carries its creation, and one added
        WITH something in it is not listed at all - what is in it is, and its own
        stamp moves with every entry put in later, so it would be timed by the
        last of them;
      * a DELETED entry leaves nothing behind to carry a time. The directory it
        left has a stamp, but that is the latest change there, whoever made it,
        so naming a suite from it was a guess presented as a reading.

    A directory's own stamp moving is no change - it follows from the entries
    below it, which are reported themselves.
    """
    found = []
    # Every directory above something that is new: those are not listed.
    holds_new = set()
    for rel in after:
        parent = rel
        while rel not in before and "/" in parent:
            parent = parent.rsplit("/", 1)[0]
            holds_new.add(parent)
    for rel in sorted(set(before) | set(after)):
        if rel == ".":
            continue
        was, now = before.get(rel), after.get(rel)
        shown = rel + ("/" if (now or was)[0] == "dir" else "")
        if now is None:
            found.append({"path": rel, "at": None,
                          "untimed": "a removal leaves no time of its own to read",
                          "text": "DELETED %s, which was there before it ran"
                                  % (shown,)})
        elif was is None or now[0] != was[0]:
            if now[0] == "dir" and rel in holds_new:
                continue
            word = "ADDED %s" % (shown,) if was is None else (
                "REWROTE %s, which was there before it ran" % (shown,))
            found.append({"path": rel, "text": word, "at": now[2]})
        elif now[0] == "file" and now[1:] != was[1:]:
            found.append({"path": rel, "text": "REWROTE %s, which was there before "
                                               "it ran" % (shown,), "at": now[2]})
    return found


def claude_verdicts(changes, windows):
    """`(by_suite, loose)`: each change given to the one suite whose window holds
    its moment, and every other change as a line naming who could have made it.

    `windows` is {suite path: (start ns, end ns)}, or {suite path: [(start ns,
    end ns), ...]} for a suite the sweep ran as several processes - one per
    block and the replay - so the gaps between them, when other suites ran,
    are not the suite's. `by_suite` is {path: [text]}.
    A pure function of its two arguments, so every branch is driven without a
    child.
    """
    by_suite, loose = {}, []
    for change in changes:
        at = change["at"]
        if change.get("untimed"):
            # NO SUITE IS NAMED for a change with no time of its own, however
            # many windows are open: a clock reading that is not there cannot
            # pick one, and a pick would blame whoever ran at the moment.
            loose.append("%s - unattributed: %s, so the clock cannot name a suite"
                         % (change["text"], change["untimed"]))
            continue
        who = [] if at is None else [
            p for p, spans in sorted(windows.items())
            if any(start - CLAUDE_START_SLACK_NS <= at <= end
                   for start, end in _spans(spans))]
        if len(who) == 1:
            by_suite.setdefault(who[0], []).append(change["text"])
        elif who:
            loose.append("%s - unattributed: %d suites were running at that moment "
                         "and any of them could have made it (%s)"
                         % (change["text"], len(who), ", ".join(who)))
        else:
            loose.append("%s - unattributed: no suite's run holds the moment it "
                         "changed, so a person or another process made it, or this "
                         "filesystem stamps times too coarsely to tell"
                         % (change["text"],))
    return by_suite, loose


def _spans(window):
    """A window as a list of `(start, end)` spans: one span is a list of one."""
    if window and isinstance(window[0], (tuple, list)):
        return list(window)
    return [window]


def claude_debris(findings):
    """A suite's share of the change, each line opening with the channel's name."""
    return ["%s: %s" % (CLAUDE_CHANNEL, f) for f in findings]


def claude_row(loose):
    """The row a change no single suite can be blamed for is reported against, or
    None when there is none. Red, and carrying the advice that turns it into a name
    where one can be had: the suites it lists, one at a time. A line that lists no
    suite - a removal - cannot be named that way, and the advice says so."""
    if not loose:
        return None
    return {"path": CLAUDE_ROW, "ok": False, "cases": 0, "output": "",
            "why": "changed while the sweep ran: %s. Re-run the suites a line "
                   "lists with --jobs 1 to name the one that wrote; a line that "
                   "lists none (a removal, a time nobody holds) is named by "
                   "whoever works on that path, not by the clock"
                   % ("; ".join(loose),)}


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
            locale_vars=None, os_name=None, extra=()):
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

    `extra` follows `--selftest` on the child's command line: one block of a
    staged suite, or its replay (`sweep`, for a suite run block by block).
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
    argv = [interpreter, os.path.join(repo, rel_path), "--selftest"] + list(extra)
    began = time.monotonic()
    # THE WALL-CLOCK WINDOW this child ran in, for `claude_verdicts`: the monotonic
    # reading above measures a duration and cannot be compared with a file's stamp.
    began_ns = time.time_ns()
    try:
        done = subprocess.run(argv, cwd=scratch, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
        code = done.returncode
        output = done.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        code, output = None, "did not finish within %ds" % (timeout,)
    except OSError as exc:
        code, output = None, "could not be started: %s" % (exc,)
    ended_ns = time.time_ns()
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
            "seconds": seconds, "grant": grant, "timeout": timeout,
            "began_ns": began_ns, "ended_ns": ended_ns}


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
        is no mode in which writing there is fine. A suite that ALSO exited
        non-zero is told for both in the one line - the code first, since the
        traceback printed below it is what a developer reads first, then what it
        left. The finding used to wait behind the exit code, so the first run
        taught nothing about it and a leak surfaced one fix later. The line names
        WHICH directory it landed in. A run that never finished (`code is None`)
        is not accused of the cwd and home fixtures its kill left - those are the
        kill's, not the suite's - but a write into the checkout's `.claude/` is
        still named, because no kill produces one.
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
        # The kill litters the cwd and the home it was handed, and only those: no
        # kill writes into the checkout's `.claude/`, so that channel's findings
        # are still the suite's and are named beside why it never finished.
        checkout = [f for f in debris if f.startswith(CLAUDE_CHANNEL + ": ")]
        if checkout:
            return row(False, "%s; and wrote outside the fixtures it makes for "
                              "itself: %s" % (output, "; ".join(checkout)))
        return row(False, output)
    if code != 0 and debris:
        return row(False, "exited %d; and wrote outside the fixtures it makes for "
                          "itself: %s" % (code, "; ".join(debris)))
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
    return set(staged_blocks(paths, repo))


def stage_labels(source):
    """The block labels of the `STAGES` table `source` assigns at module level,
    in order - read off the AST as a literal of `(label, function name)` string
    pairs - or None when there is no such table, it is not a literal of that
    shape, it is empty, or two rows share a label. None is not a refusal: the
    sweep then runs the suite whole, holding a grant (`stage_grant`)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "STAGES"):
            continue
        try:
            rows = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            return None
        shaped = isinstance(rows, (tuple, list)) and all(
            isinstance(row, (tuple, list)) and len(row) == 2
            and all(isinstance(part, str) for part in row) for row in rows)
        labels = [row[0] for row in rows] if shaped else []
        if not labels or len(set(labels)) != len(labels):
            return None
        return labels
    return None


def staged_blocks(paths, repo=None):
    """`{path: labels or None}` for each of `paths` that `is_staged`: the
    labels its blocks run under when the sweep can read its table
    (`stage_labels`), else None. A file that cannot be read is not staged."""
    repo = repo or REPO
    found = {}
    for path in paths:
        try:
            with io.open(os.path.join(repo, path), encoding="utf-8",
                         errors="replace") as fh:
                source = fh.read()
        except (IOError, OSError):
            continue
        if is_staged(source):
            found[path] = stage_labels(source)
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
    once every lower ticket has been admitted and at least one slot is free,
    takes up to `weight` of the free slots and returns how many it took;
    `done(taken)` gives them back.

    IN TICKET ORDER, never out of it. A cheap file allowed past a staged suite
    waiting for its slots would take the slot that suite was waiting on, and
    with enough cheap files behind it the suite would start last - the exact
    shape a costliest-first order exists to prevent.

    AND A FULL GRANT IS NEVER WAITED FOR WHILE A SLOT SITS FREE. The head used
    to wait until all `weight` of its slots were free, and every ticket behind
    it waited with it, so the slots already free stayed idle until the files
    holding the rest had finished: a staged suite admitted while another held
    most of the budget stalled the whole run behind it, and each suite split
    into blocks added one more such stall. Taking what is free, and telling the
    child the number (`STAGE_GRANT_VAR`), keeps the order and wastes no slot:
    the suite sizes its block pool from what it holds, and its timeout is
    calibrated to the same number (`file_timeout`). A weight above `slots`
    is read as `slots`, and a weight under one as one."""
    cond = threading.Condition()
    state = {"free": slots, "turn": 0}

    def wait(ticket, weight):
        weight = max(1, min(weight, slots))
        with cond:
            while state["turn"] != ticket or state["free"] < 1:
                cond.wait()
            taken = min(weight, state["free"])
            state["free"] -= taken
            state["turn"] += 1
            cond.notify_all()
        return taken

    def done(taken):
        with cond:
            state["free"] += max(1, min(taken, slots))
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


# --- blocks, not suites, as the unit the budget schedules ------------------------
# A STAGED SUITE THAT HELD SLOTS HELD THEM UNTIL ITS LAST BLOCK ENDED. Admitted with
# a grant, the heaviest suite ran its own pool on a fixed share of the budget
# from its first block to its last, while the cheap files queued for the rest
# and the share sat partly idle through its tail. So the sweep reads each staged
# suite's `STAGES` table (`stage_labels`) and runs every block as a job of its
# own, one slot each, out of the same budget and in the same ticket order as any
# file: a block is a child run by `run_one` like a file - its own scratch
# directory, home and git config, watched the same way - started as
# `--selftest --stage LABEL --cases-to PATH`. When the last block of a suite has
# ended, the thread that ran it starts the suite once more, on the slot it
# already holds, as `--selftest --replay LIST`; `_harness.replay_selftest` reads
# what every block wrote and prints the full run's cases, tally and exit code,
# so the file's row is graded by `grade` like any other. A suite whose table
# cannot be read as a literal runs whole on a grant, as before.
#
# ORDER: every job by its estimated cost, costliest first (`work_items`). A
# block's estimate is its file's recorded cost spread evenly over its blocks,
# since the table times files and not blocks; that is longest-first list
# scheduling over the budget, and it puts the heavy plain files ahead of a
# staged suite's many small blocks instead of behind all of them.
#
# A BLOCK'S TIMEOUT is its file's calibrated timeout at the slots a grant would
# have given it (`file_timeout` at `stage_grant(jobs)`), which is what a block
# was allowed when the suite ran its own pool, still cut by the deadline. The
# replay is allowed the floor.
def work_items(paths, costs, blocks):
    """`[(path, label or None)]`, the sweep's jobs in the order it submits
    them: one per block of each suite `blocks` gives labels for, one per any
    other file. Costliest estimate first, ties by path and then by the block's
    place in its table, so the order is a function of its arguments alone."""
    live = _live(costs or {}, paths)
    estimate = _median(live)
    jobs = []
    for path in set(paths):
        cost = cost_of(live, path, estimate)
        labels = blocks.get(path) or [None]
        jobs.extend((-cost / len(labels), path, at, label)
                    for at, label in enumerate(labels))
    return [(path, label) for _cost, path, _at, label in sorted(jobs)]


def block_entry(label, cases_path, ran):
    """What `_harness.replay_selftest` is told about one block the sweep ran:
    its label, the file it was told to write its cases to, its exit code and
    output, and - when it never finished or never started - why."""
    never = ran["code"] is None
    return {"label": label, "cases": cases_path, "code": ran["code"],
            "out": "" if never else ran["output"],
            "why": ran["output"] if never else ""}


def suite_ran(path, blocks_ran, replay):
    """The one result a suite run as blocks stands for, shaped as `run_one`'s
    is for a file: the replay's exit code and output, the debris of every
    block - each line naming its block - and of the replay, the seconds of
    them all (slot-seconds, since each held one slot), and the window of each
    process, for `claude_verdicts`.

    A BLOCK THAT NEVER FINISHED LEAVES NO DEBRIS ON THE FILE: what a kill
    leaves in its scratch is the kill's, the rule `grade` applies to a file,
    and the block is already a failing case in the replay."""
    debris = []
    for label, ran in blocks_ran:
        if ran["code"] is not None:
            debris.extend("block %s, %s" % (label, d) for d in ran["debris"])
    debris.extend(replay["debris"])
    spans = [(r["began_ns"], r["ended_ns"])
             for r in [ran for _label, ran in blocks_ran] + [replay]
             if "began_ns" in r]
    timed = [ran.get("seconds") for _label, ran in blocks_ran] + [
        replay.get("seconds")]
    return {"path": path, "code": replay["code"], "output": replay["output"],
            "debris": debris, "grant": 1, "blocks": len(blocks_ran),
            "seconds": sum(t for t in timed if t is not None),
            "timeout": max([ran.get("timeout") or 0
                            for _label, ran in blocks_ran] or [0]) or None,
            "windows": spans}


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
    blocks = staged_blocks(paths, repo)
    items = work_items(paths, costs, blocks)
    grant = stage_grant(jobs)
    wait, done = slot_gate(jobs)
    started = time.time()
    # Per staged suite run as blocks: the blocks still to end, and what each
    # one that has ended left, under one lock.
    lock = threading.Lock()
    pending_blocks = dict((p, {"left": len(labels), "ran": []})
                          for p, labels in blocks.items() if labels)

    def child(path, held, cap_timeout, extra=()):
        left = (None if deadline is None
                else max(1, int(deadline - (time.time() - started))))
        return run_one(path, repo, encoding,
                       cap_timeout if left is None else min(cap_timeout, left),
                       pycache, None, spaced, held,
                       locale_vars=locale_vars, os_name=os_name, extra=extra)

    def one_block(ticket, path, label):
        cases_path = os.path.join(box, "%d.json" % (ticket,))
        ran = child(path, 1, file_timeout(path, costs, timeout, grant,
                                          staged=True),
                    ("--stage", label, "--cases-to", cases_path))
        with lock:
            state = pending_blocks[path]
            state["ran"].append((label, cases_path, ran))
            state["left"] -= 1
            last = state["left"] == 0
        if not last:
            return None
        # THE LAST BLOCK OF THE SUITE TO END starts its replay, on the slot it
        # holds: the order the blocks ended in is the scheduler's, and the
        # replay puts them back in `STAGES` order.
        listed = os.path.join(box, "%d.replay.json" % (ticket,))
        with io.open(listed, "w", encoding="utf-8") as fh:
            json.dump([block_entry(lab, cp, r) for lab, cp, r in state["ran"]],
                      fh)
        replay = child(path, 1, timeout, ("--replay", listed))
        return suite_ran(path, [(lab, r) for lab, _cp, r in state["ran"]],
                         replay)

    def admitted(ticket, item):
        path, label = item
        # WHAT THE GATE GAVE, not what was asked: a staged suite run whole,
        # admitted while fewer than `grant` slots were free, holds those, is
        # told so, and has its timeout calibrated to them.
        whole_staged = path in blocks and label is None
        held = wait(ticket, grant if whole_staged else 1)
        try:
            if label is not None:
                return one_block(ticket, path, label)
            return child(path, held, file_timeout(path, costs, timeout, held,
                                                  staged=whole_staged))
        finally:
            # HELD THROUGH THE WAIT, so the next child cannot start inside it:
            # `CLAUDE_SERIAL_GAP_S` says why a serial run leaves a gap.
            if jobs == 1:
                time.sleep(CLAUDE_SERIAL_GAP_S)
            done(held)
    pycache = tempfile.mkdtemp(prefix="sp-run-")
    # WHERE EACH BLOCK WRITES ITS CASES and each replay reads the list of them:
    # the sweep's own directory, outside every watched one.
    box = tempfile.mkdtemp(prefix="sb-")
    # THE CHECKOUT'S OWN `.claude/`, read before the first child starts and after
    # the last one is done (`claude_verdicts` says why that is the only shape).
    watched = repo or REPO
    claude_before = claude_snapshot(watched)
    ran_all = []
    try:
        with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            # COSTLIEST FIRST, so the slowest job is never the last one
            # started, and admitted through ONE budget in that order.
            pending = [pool.submit(admitted, i, item)
                       for i, item in enumerate(items)]
            for fut in futures.as_completed(pending):
                ran = fut.result()
                if ran is not None:
                    ran_all.append(ran)
    finally:
        shutil.rmtree(pycache, ignore_errors=True)
        shutil.rmtree(box, ignore_errors=True)
    by_suite, loose = claude_verdicts(
        claude_changes(claude_before, claude_snapshot(watched)),
        # A child that never started (the spaced layout could not be built) ran
        # in no window and can be named for nothing.
        dict((r["path"], r["windows"] if "windows" in r
              else (r["began_ns"], r["ended_ns"])) for r in ran_all
             if r.get("windows") or "began_ns" in r))
    for ran in ran_all:
        graded = grade(ran["path"], ran["code"], ran["output"],
                       debris=ran["debris"]
                       + claude_debris(by_suite.get(ran["path"], [])))
        spans = ran.get("windows") or [(ran.get("began_ns"), ran.get("ended_ns"))]
        starts = [a for a, _b in spans if a is not None]
        ends = [b for _a, b in spans if b is not None]
        rows.append(dict(graded, seconds=ran.get("seconds"),
                         grant=ran.get("grant"), timeout=ran.get("timeout"),
                         blocks=ran.get("blocks"), windows=spans,
                         window=(min(starts) if starts else None,
                                 max(ends) if ends else None)))
    unnamed = claude_row(loose)
    if unnamed is not None:
        rows.append(unnamed)
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
TIMING = re.compile(r"^  (?:ok|FAILED)  +(\S+) .*  \[([0-9.]+)s"
                    r"(?:, (\d+) (slots|blocks))?\]$")


def timing(row):
    """`  [12.3s]` for a row a child ran - `  [12.3s, 3 slots]` when it held
    more than one, `  [912.3s, 40 blocks]` for a suite the sweep ran block by
    block, whose seconds are then the sum over its processes, each on one
    slot - and nothing for a row with no measurement. Printed on the loud form
    so a CI log carries every file's seconds and can be recorded
    (`--costs-from-log`) without a second run."""
    if row.get("seconds") is None:
        return ""
    if row.get("blocks"):
        return "  [%.1fs, %d blocks]" % (row["seconds"], row["blocks"])
    grant = row.get("grant") or 1
    return "  [%.1fs%s]" % (row["seconds"],
                            ", %d slots" % (grant,) if grant > 1 else "")


def costs_from_render(text):
    """{path: slot-seconds} read off the loud form's lines - the seconds times
    the slots printed beside them, or the seconds alone beside a count of
    blocks - for a log saved from a run elsewhere, a CI
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
            # A block-by-block suite's seconds are already slot-seconds.
            slots = int(match.group(3) or 1) if match.group(4) == "slots" else 1
            seconds = round(float(match.group(2)) * slots, 1)
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
    each number: which staged suites run whole holding several slots, the
    longest timeout the cost table gave any file over the floor, the deadline
    when one applies, and which staged suites run block by block and how many
    blocks that is."""
    found = staged_blocks(paths, repo)
    whole = sorted(p for p, labels in found.items() if not labels)
    split = sorted(p for p, labels in found.items() if labels)
    grant = stage_grant(jobs)
    longest = max([file_timeout(p, costs, floor, grant if p in found else 1,
                                staged=p in found, cap=deadline)
                   for p in paths] or [floor])
    return ("budget: %d slots; %d staged suites hold up to %d each (%s); per-file "
            "timeout %ds, up to %ds for a file the cost table times as heavy%s; "
            "%d staged suites run block by block, a slot a block, %d blocks "
            "(%s)\n"
            % (jobs, len(whole), stage_grant(jobs),
               ", ".join(os.path.basename(p) for p in whole) or "none",
               floor, longest,
               "" if deadline is None else
               "; every file named by %ds, the CI deadline" % (deadline,),
               len(split), sum(len(found[p]) for p in split),
               ", ".join(os.path.basename(p) for p in split) or "none"))


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
    refusal = scratch_refusal(tempfile.gettempdir())
    if refusal:
        sys.stderr.write("sweep-selftests: refusing to start - %s\n" % (refusal,))
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


def _claude_watch_cases(check):
    """The checkout's own `.claude/` as a watched directory, driven through
    `sweep()` over fixture checkouts built here.

    Every fixture suite finds its checkout from its OWN location, which is the
    mistake being modelled: a suite that resolves its project from where it sits
    instead of from its scratch. The checkout is a temp directory, so the real
    one is never written to, and it is removed in a `finally`.
    """
    contract = "sys.stdout.write('fixture: 1/1 cases passed\\n')\n"
    # The fixture's way of naming its checkout, written once. NOT `REPO`: the
    # point is a child that locates its project the way the faulty suites did.
    root = ("import os, sys, time\n"
            "ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "CL = os.path.join(ROOT, '.claude')\n"
            "def wait_for(path):\n"
            "    end = time.time() + 20\n"
            "    while not os.path.exists(path) and time.time() < end:\n"
            "        time.sleep(0.02)\n"
            "    return os.path.exists(path)\n")
    box = tempfile.mkdtemp(prefix="sweep-watch-")

    def _fresh(name):
        """A checkout of its own with `.claude/` holding two files and a suite dir."""
        repo = os.path.join(box, name)
        os.makedirs(os.path.join(repo, "tests"))
        os.makedirs(os.path.join(repo, ".claude"))
        io.open(os.path.join(repo, ".claude", "keep"), "w").write("original\n")
        io.open(os.path.join(repo, ".claude", "keep2"), "w").write("original\n")
        return repo

    def _suite(repo, name, body):
        io.open(os.path.join(repo, "tests", name), "w", encoding="utf-8").write(
            root + body + contract)
        return "tests/" + name

    try:
        # -- one suite alone writes a restore point, as the faulty suite did ----
        repo = _fresh("solo")
        a = _suite(repo, "quiet_a", "")
        w = _suite(repo, "writer",
                   "d = os.path.join(CL, 'audit-backups')\n"
                   "os.makedirs(d)\n"
                   "open(os.path.join(d, 'plan.bak-20260101T000000Z'), 'w')"
                   ".write('{}')\n"
                   "time.sleep(0.4)\n")
        b = _suite(repo, "quiet_b", "")
        rows = dict((r["path"], r) for r in sweep([a, w, b], jobs=1, repo=repo,
                                                  timeout=30))
        check("cw0 a suite that writes under the checkout's own .claude/ is RED "
              "and the finding NAMES it and the path it wrote - while the two "
              "suites run either side of it stay green, so the guard blames the "
              "writer and not whoever happened to run beside it: %r"
              % (dict((k, (v["ok"], v["why"])) for k, v in sorted(rows.items())),),
              len(rows) == 3 and not rows[w]["ok"]
              and "checkout .claude" in rows[w]["why"]
              and "audit-backups" in rows[w]["why"]
              and rows[a]["ok"] and rows[b]["ok"])

        # -- cw1 IS THE SECOND DIRECTION of cw0 ---------------------------------
        # cw0 passes against a guard that always fires. Suites that touch nothing,
        # over a checkout whose .claude/ holds files already, must come back green.
        repo = _fresh("clean")
        a = _suite(repo, "quiet_a", "")
        b = _suite(repo, "quiet_b", "open(os.path.join(CL, 'keep')).read()\n")
        rows = sweep([a, b], jobs=2, repo=repo, timeout=30)
        check("cw1 suites that only READ the checkout's .claude/ are green, and "
              "no extra row appears for it - the guard does not fire over a "
              "directory nobody wrote in: %r"
              % ([(r["path"], r["ok"], r["why"]) for r in rows],),
              len(rows) == 2 and all(r["ok"] for r in rows))

        # -- deletions and rewrites are findings too ----------------------------
        repo = _fresh("destroy")
        d = _suite(repo, "destroyer",
                   "os.remove(os.path.join(CL, 'keep'))\n"
                   "open(os.path.join(CL, 'keep2'), 'w').write('clobbered, longer\\n')\n"
                   "time.sleep(0.4)\n")
        rows = sweep([d], jobs=1, repo=repo, timeout=30)
        by_path = dict((r["path"], r) for r in rows)
        gone = by_path.get(CLAUDE_ROW)
        check("cw2 a suite that DELETES a file the checkout's .claude/ held and "
              "one that REWRITES another are both reported, in the two words the "
              "scratch directories use for them - but only the rewrite is pinned "
              "on the suite, because a removal leaves nothing that carries a time "
              "of its own (the directory above it keeps a stamp that any later "
              "change moves), so the deletion is a red row of its own that says "
              "so and names no suite: %r"
              % (dict((k, (v["ok"], v["why"])) for k, v in sorted(by_path.items())),),
              len(rows) == 2 and not by_path[d]["ok"]
              and "REWROTE keep2" in by_path[d]["why"]
              and "DELETED keep, " not in by_path[d]["why"]
              and by_path[d]["why"].count("checkout .claude: ") == 1
              and gone is not None and not gone["ok"]
              and "DELETED keep, " in gone["why"]
              and "no time of its own" in gone["why"]
              and d not in gone["why"])

        # -- two suites running together: the write is NOT pinned on either -----
        repo = _fresh("parallel")
        sig = os.path.join(box, "parallel-signals")
        os.makedirs(sig)
        p = _suite(repo, "writes_while_other_runs",
                   "open(%r, 'w').close()\n" % (os.path.join(sig, "p-up"),)
                   + "wait_for(%r)\n" % (os.path.join(sig, "q-up"),)
                   + "os.makedirs(os.path.join(CL, 'audit-backups'))\n"
                   "open(os.path.join(CL, 'audit-backups', 'z.bak'), 'w').write('x')\n"
                   "open(%r, 'w').close()\n" % (os.path.join(sig, "p-done"),))
        q = _suite(repo, "innocent_bystander",
                   "open(%r, 'w').close()\n" % (os.path.join(sig, "q-up"),)
                   + "wait_for(%r)\n" % (os.path.join(sig, "p-done"),))
        rows = dict((r["path"], r) for r in sweep([p, q], jobs=2, repo=repo,
                                                  timeout=30))
        extra = [r for r in rows.values() if r["path"] not in (p, q)]
        check("cw3 when two suites ran at the same moment a write cannot be "
              "pinned on either: BOTH suite rows stay green, and one extra row "
              "reports the write unattributed, naming the path and every suite "
              "that could have made it - never one picked at random: %r"
              % (dict((k, (v["ok"], v["why"])) for k, v in sorted(rows.items())),),
              len(rows) == 3 and rows[p]["ok"] and rows[q]["ok"]
              and len(extra) == 1 and not extra[0]["ok"]
              and "z.bak" in extra[0]["why"] and p in extra[0]["why"]
              and q in extra[0]["why"] and "unattributed" in extra[0]["why"])

        # -- what the live session writes there is not a suite's ----------------
        repo = _fresh("runtime")
        # `state/` is there before the sweep starts, as it is in any checkout a
        # session has already worked in: the directory itself is watched.
        os.makedirs(os.path.join(repo, ".claude", "state"))
        r_ = _suite(repo, "writes_runtime_state",
                    "os.makedirs(os.path.join(CL, 'logs'))\n"
                    "open(os.path.join(CL, 'logs', 'h.log'), 'w').write('x')\n"
                    # A NAME SPELLED OUT here, as `ls .claude/state` prints one,
                    # and not read off the table: a case that asks the table
                    # which names it skips passes whatever the table says.
                    "open(os.path.join(CL, 'state', "
                    "'call-start-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d.json'), "
                    "'w').write('{}')\n"
                    "time.sleep(0.4)\n")
        rows = sweep([r_], jobs=1, repo=repo, timeout=30)
        check("cw4 what the live session itself writes while a sweep runs - a "
              "hook's slot in state/ under a name the hooks give it, and the "
              "hook log directory - is left out of the watched set, so a sweep "
              "typed from inside a session is not reddened by it: %r"
              % ([(r["path"], r["why"]) for r in rows],),
              len(rows) == 1 and rows[0]["ok"])

        # -- cw9: state/ IS WATCHED, which is what cw4 used to hide ---------------
        # The whole directory was once left out, so a suite that wrote a file of
        # its own there was invisible. A name no hook gives a slot is a suite's.
        repo = _fresh("state-write")
        s_ = _suite(repo, "writes_state_file",
                    "os.makedirs(os.path.join(CL, 'state'))\n"
                    "open(os.path.join(CL, 'state', 'suite-made.json'), 'w')"
                    ".write('{}')\n"
                    "time.sleep(0.4)\n")
        rows = sweep([s_], jobs=1, repo=repo, timeout=30)
        check("cw9 a suite that writes a file of its own under the checkout's "
              ".claude/state/ is RED and the finding names the path - the "
              "directory is no longer left out wholesale, only the names the "
              "live session's hooks and the drive give their own slots: %r"
              % ([(r["path"], r["ok"], r["why"]) for r in rows],),
              len(rows) == 1 and not rows[0]["ok"]
              and "state/suite-made.json" in rows[0]["why"]
              and "checkout .claude" in rows[0]["why"])

        # -- cw11: THE FINDING IS NOT HIDDEN BY A NON-ZERO EXIT ------------------
        repo = _fresh("fails-and-writes")
        f_ = io.open(os.path.join(repo, "tests", "fails_and_writes"), "w",
                     encoding="utf-8")
        f_.write(root + "open(os.path.join(CL, 'stray.txt'), 'w').write('x')\n"
                 "time.sleep(0.4)\nsys.exit(3)\n")
        f_.close()
        rows = sweep(["tests/fails_and_writes"], jobs=1, repo=repo, timeout=30)
        check("cw11 a suite that exits non-zero AND wrote into the checkout's "
              ".claude/ is red for both, in one line: the exit code is named and "
              "so is the path - a developer fixing the exit code first used to "
              "learn of the write on the next run only: %r"
              % ([(r["path"], r["ok"], r["why"]) for r in rows],),
              len(rows) == 1 and not rows[0]["ok"]
              and "exited 3" in rows[0]["why"]
              and "stray.txt" in rows[0]["why"])

        # -- cw12: back-to-back suites at --jobs 1 are told apart by the clock ----
        repo = _fresh("serial")
        trio = [_suite(repo, "serial_%s" % n, "") for n in ("a", "b", "c")]
        rows = sweep(trio, jobs=1, repo=repo, timeout=30)
        spans = sorted(r["window"] for r in rows if "window" in r)
        gaps = [later[0] - earlier[1] for earlier, later in zip(spans, spans[1:])]
        check("cw12 at --jobs 1 the windows suites ran in are separated by more "
              "than the slack a stamp's lag is allowed: the slack widens a "
              "window's START, so adjacent windows that touch would make a write "
              "at the end of one a candidate for the next, and the re-run the "
              "unattributed row advises would not name the writer: gaps %r ns "
              "against slack %d ns" % (gaps, CLAUDE_START_SLACK_NS),
              len(spans) == 3 and len(gaps) == 2
              and all(g > CLAUDE_START_SLACK_NS for g in gaps))
    finally:
        remove_tree(box)

    # -- the snapshot reads the watched part and nothing else ------------------
    snap_box = tempfile.mkdtemp(prefix="sweep-snap-")
    try:
        none_at_all = claude_snapshot(snap_box)
        # THE LIVE SESSION'S NAMES ARE SPELLED OUT, as `ls .claude/state` prints
        # them: asking the table which names it skips would pass whatever it said.
        sid = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
        live = ["state/call-start-%s.json" % sid,
                "state/call-start-%s-a1b2c3d4e5f60718.json" % sid,
                "state/journal-preimage-%s-a1b2c3d4e5f60718.0123456789ab.json" % sid,
                "state/plan-gate-%s.a1b2c3d4e5f60718.json" % sid,
                "state/bash-writes-%s.json" % sid,
                "state/tdd-reminder-%s.json" % sid,
                "state/running-plugin-%s.json" % sid,
                "state/attempts/P1.1-abc.json", "state/briefs/P1.1-abc/b.md",
                "state/drive/P1.json"]
        theirs = ["state/s.json", "state/writer-token.json", "state/release-run.json",
                  "state/call-start-notauuid.json", "state/briefs-extra/x",
                  "state/bash-writes-plugin-%s.json" % sid]
        for rel in live + theirs + [
                "logs/l.log", "usage/u.jsonl", "worktrees/w/x",
                "hooks/__pycache__/cached", "skills/mine/state/kept",
                "audit-backups/p.bak", "hooks/h", ".gitignore"]:
            target = os.path.join(snap_box, ".claude", *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            io.open(target, "w").write("x")
        for rel in ("settings.local.json", "audit-panel.json", "settings.json"):
            io.open(os.path.join(snap_box, ".claude", rel), "w").write("{}")
        snap = claude_snapshot(snap_box)
        check("cw5 the snapshot of a checkout with no .claude/ is EMPTY, and of "
              "one with a live session's directories in it holds exactly the "
              "rest - what that session leaves out (logs, usage, worktrees and "
              "settings.local.json, the hook and drive slots in state/ under the "
              "names they give them), the panel pidfile and bytecode wherever it "
              "sits are absent, while a directory merely NAMED like one of them "
              "below the top, the restore-point directory this guard was written "
              "for and every OTHER file in state/ - a name no hook gives a slot, "
              "a near-miss of one - are present: %r" % (sorted(snap),),
              none_at_all == {}
              and sorted(k for k, v in snap.items() if v[0] == "file")
              == sorted([".gitignore", "audit-backups/p.bak", "hooks/h",
                         "settings.json", "skills/mine/state/kept",
                         "state/call-start-notauuid.json",
                         "state/bash-writes-plugin-%s.json" % sid,
                         "state/release-run.json", "state/s.json",
                         "state/writer-token.json", "state/briefs-extra/x"])
              and not [k for k in snap if k.split("/")[0] in
                       ("logs", "usage", "worktrees")
                       or "__pycache__" in k or k.endswith("local.json")
                       or k.endswith("panel.json")]
              and not [k for k in snap if k in live
                       or k.split("/")[:2] in (["state", "attempts"],
                                               ["state", "drive"])])

        # -- cw10: the table's own rows, driven one by one -------------------------
        # Each row carries an example name; it must be skipped, and so must it not
        # be once a character of it is wrong - a row whose pattern grew loose
        # enough to swallow a suite's file would otherwise stay green.
        examples = [row[1] for row in CLAUDE_LIVE_WRITES]
        misses = [x for x in examples if not claude_live_written(x)]
        swallowed = [x for x in examples
                     if claude_live_written(x.replace("state/", "state/x", 1))]
        check("cw10 every row of the live-session table skips the example it "
              "carries and does NOT skip the same name with a character wrong - "
              "so no row is dead and none swallows a suite's own file: missed "
              "%r, swallowed %r" % (misses, swallowed),
              len(examples) > 0 and misses == [] and swallowed == [])
    finally:
        remove_tree(snap_box)

    # -- the difference between two snapshots ----------------------------------
    before = {".": ("dir", 0, 50), "keep": ("file", 5, 10), "same": ("file", 5, 10),
              "touched": ("file", 5, 10), "sub": ("dir", 0, 10),
              "sub/gone": ("file", 5, 10), "doomed": ("dir", 0, 10),
              "doomed/inner": ("file", 5, 10), "swap": ("dir", 0, 10)}
    after = {".": ("dir", 0, 99), "same": ("file", 5, 10),
             "touched": ("file", 5, 77), "sub": ("dir", 0, 66),
             "new": ("file", 3, 88), "newdir": ("dir", 0, 89),
             "swap": ("file", 0, 90),
             "full": ("dir", 0, 91), "full/inner": ("dir", 0, 92),
             "full/inner/leaf": ("file", 1, 93)}
    got = dict((c["path"], c) for c in claude_changes(before, after))
    check("cw6 the difference names every kind of change once and times only what "
          "carries a time of its own - a file added, an EMPTY directory added "
          "(its stamp is its creation), a file rewritten with the SAME size (only "
          "its stamp moved), a directory replaced by a file; a directory added "
          "WITH something in it is not listed at all, since what is in it is and "
          "carries the time (its own stamp moves with every entry put in later); "
          "and two deletions, a file under a directory that survived and a whole "
          "subtree, which are listed UNTIMED with the reason - a removal leaves "
          "nothing to carry a time, and the stamp of the directory it left is "
          "just the latest change there; a directory whose own stamp merely "
          "moved, a file untouched and the root itself are NOT changes: %r"
          % (sorted((p, c["text"].split(" ")[0], c["at"]) for p, c in got.items()),),
          sorted(got) == ["doomed", "doomed/inner", "full/inner/leaf", "keep",
                          "new", "newdir", "sub/gone", "swap", "touched"]
          and got["new"]["text"] == "ADDED new" and got["new"]["at"] == 88
          and got["newdir"]["text"] == "ADDED newdir/" and got["newdir"]["at"] == 89
          and got["full/inner/leaf"]["at"] == 93
          and got["touched"]["text"].startswith("REWROTE touched") and got["touched"]["at"] == 77
          and got["swap"]["text"].startswith("REWROTE swap") and got["swap"]["at"] == 90
          and got["keep"]["text"].startswith("DELETED keep, ")
          and all(got[k]["at"] is None and "no time of its own" in got[k]["untimed"]
                  for k in ("keep", "sub/gone", "doomed", "doomed/inner")))

    # -- who made it: one window, several windows, none -------------------------
    sec = 10 ** 9
    windows = {"a": (1 * sec, 2 * sec), "b": (3 * sec, 4 * sec),
               "c": (int(1.5 * sec), int(2.5 * sec))}

    def _at(path, moment):
        return {"path": path, "text": "ADDED " + path, "at": moment}
    by_suite, loose = claude_verdicts(
        [_at("one", int(1.2 * sec)), _at("two", int(1.7 * sec)),
         _at("none", 9 * sec), _at("unstamped", None),
         _at("edge", 3 * sec - 1000 * 1000), _at("early", 3 * sec - 100 * 1000 * 1000)],
        windows)
    check("cw7 a change is given to a suite only when EXACTLY ONE window holds its "
          "moment: one inside a single window is that suite's (and the start of "
          "a window is widened by a stamp's lag, a millisecond before it counts "
          "but a tenth of a second does not); one inside two windows is reported "
          "unattributed naming BOTH, one inside none says so, and one with no "
          "stamp is not guessed at - the suite rows get nothing they did not "
          "earn: %r / %r" % (by_suite, loose),
          sorted(by_suite) == ["a", "b"] and by_suite["a"] == ["ADDED one"]
          and by_suite["b"] == ["ADDED edge"] and len(loose) == 4
          and "ADDED two - unattributed" in loose[0] and "a, c" in loose[0]
          and "ADDED none" in loose[1] and "no suite's run holds" in loose[1]
          and "ADDED unstamped" in loose[2] and "no suite's run holds" in loose[2]
          and "ADDED early" in loose[3] and "no suite's run holds" in loose[3])
    row = claude_row(loose)
    check("cw8 an unnamed change becomes ONE red row carrying every line and the "
          "re-run that names the writer, and no change at all becomes no row: %r"
          % (row,),
          claude_row([]) is None and row is not None and not row["ok"]
          and row["path"] == CLAUDE_ROW and "--jobs 1" in row["why"]
          and all(line in row["why"] for line in loose))

    # -- cw13: a change with no time of its own names no suite ------------------
    # The second direction of cw7: windows exist and one of them would hold any
    # moment a guess picked, so only the refusal keeps the suite rows clean.
    by_suite, loose = claude_verdicts(
        [{"path": "gone", "text": "DELETED gone, which was there before it ran",
          "at": None, "untimed": "a removal has no time of its own"}],
        {"a": (1 * sec, 2 * sec)})
    check("cw13 a removal is reported unattributed WITH its own reason and no "
          "suite is blamed, though a window is open that a guessed time would "
          "have fallen in: %r / %r" % (by_suite, loose),
          by_suite == {} and len(loose) == 1
          and "DELETED gone" in loose[0] and "no time of its own" in loose[0]
          and "no suite's run holds" not in loose[0])

    # -- cw14: a non-zero exit does not hide what the suite also wrote -----------
    g_both = grade("tests/x", 3, "Traceback\n",
                   debris=["checkout .claude: ADDED stray.txt"])
    g_code = grade("tests/x", 3, "Traceback\n")
    g_leak = grade("tests/x", 0, "1/1 cases passed\n",
                   debris=["checkout .claude: ADDED stray.txt"])
    g_late = grade("tests/x", None, "did not finish within 9s",
                   debris=["working directory: left behind: fixture"])
    check("cw14 a run that exited non-zero AND left a finding is red for both, "
          "code first and the finding after it, once each; the exit code alone "
          "and the finding alone read as they always did, and a run that never "
          "finished is not accused of the fixtures its kill left behind: "
          "%r / %r / %r / %r" % (g_both, g_code, g_leak, g_late),
          not g_both["ok"] and g_both["why"].startswith("exited 3")
          and g_both["why"].count("ADDED stray.txt") == 1
          and g_code["why"] == "exited 3"
          and g_leak["why"].startswith("wrote outside the fixtures")
          and g_late["why"] == "did not finish within 9s")

    # The kill exemption belongs to the two channels a kill litters (the cwd and
    # the home it was handed); no kill writes into the checkout's `.claude/`, so a
    # suite that wrote there and THEN hung is still named, and only that finding.
    g_hung = grade("tests/x", None, "did not finish within 9s",
                   debris=["checkout .claude: ADDED stray.txt"])
    g_hung_mixed = grade("tests/x", None, "did not finish within 9s",
                         debris=["working directory: left behind: fixture",
                                 "checkout .claude: ADDED stray.txt",
                                 "home directory: left behind: dot-probe"])
    check("cw14b a run that never finished but wrote into the checkout's .claude/ "
          "is red and NAMES the write, once, beside why it never finished; with "
          "the kill's own cwd and home leftovers alongside, only the .claude/ "
          "write is named: %r / %r" % (g_hung, g_hung_mixed),
          not g_hung["ok"] and g_hung["why"].count("ADDED stray.txt") == 1
          and "did not finish within 9s" in g_hung["why"]
          and not g_hung_mixed["ok"]
          and g_hung_mixed["why"].count("ADDED stray.txt") == 1
          and "left behind" not in g_hung_mixed["why"]
          and "dot-probe" not in g_hung_mixed["why"])

    # -- cw15: the sweep will not start where its scratch is inside a checkout ---
    ref_box = tempfile.mkdtemp(prefix="sweep-ref-")
    try:
        os.makedirs(os.path.join(ref_box, "co", ".git"))
        os.makedirs(os.path.join(ref_box, "co", "tmp"))
        os.makedirs(os.path.join(ref_box, "plain", "tmp"))
        inside = scratch_refusal(os.path.join(ref_box, "co", "tmp"))
        outside = scratch_refusal(os.path.join(ref_box, "plain", "tmp"))
    finally:
        remove_tree(ref_box)
    live_tmp = scratch_refusal(tempfile.gettempdir())
    check("cw15 a temp directory with a .git above it is REFUSED, naming both the "
          "directory and the checkout, because every scratch directory a child "
          "is handed is made there and a suite that finds its project by walking "
          "up for .git would find that checkout; one with none above it is "
          "not; and this machine's own temp directory passes, so the refusal "
          "is not already firing on every run: %r / %r / %r"
          % (inside, outside, live_tmp),
          inside is not None and "co" in inside and "tmp" in inside
          and ".git" in inside and outside is None and live_tmp is None)

    # The refusal is only worth anything if `main` ASKS it. `scratch_refusal` is
    # pinned above on its own; this drives `main` with the temp directory swapped
    # (what `tempfile.gettempdir()` answers), so a `main` that stopped calling it
    # turns red here. The clean directory is shown to get PAST the refusal by a
    # cheaper refusal further down (an unknown suite name), not by running a sweep.
    ref_main_box = tempfile.mkdtemp(prefix="sweep-refmain-")
    ref_main_was = tempfile.tempdir
    ref_main_err = sys.stderr
    ref_main = {}
    try:
        os.makedirs(os.path.join(ref_main_box, "co", ".git"))
        os.makedirs(os.path.join(ref_main_box, "co", "tmp"))
        os.makedirs(os.path.join(ref_main_box, "plain", "tmp"))
        for ref_name in ("co", "plain"):
            tempfile.tempdir = os.path.join(ref_main_box, ref_name, "tmp")
            sys.stderr = io.StringIO()
            ref_main[ref_name] = (main(["no-such-suite-for-the-refusal-case"]),
                                  sys.stderr.getvalue())
    finally:
        sys.stderr = ref_main_err
        tempfile.tempdir = ref_main_was
        remove_tree(ref_main_box)
    check("cw15b main() exits 2 with 'refusing to start - the temp directory' when "
          "its temp directory has a .git above it, and a temp directory with none "
          "does not take that exit - it reaches the next refusal (an unknown suite "
          "name) instead: %r" % (ref_main,),
          ref_main["co"][0] == 2
          and "refusing to start - the temp directory" in ref_main["co"][1]
          and "is not a suite this sweep covers" not in ref_main["co"][1]
          and "refusing to start - the temp directory" not in ref_main["plain"][1]
          and "is not a suite this sweep covers" in ref_main["plain"][1])

    # -- cw16: the three documents that describe the watched set say it ----------
    docs_text = {}
    for rel in ("CONTRIBUTING.md", os.path.join("tests", "_harness.py")):
        with io.open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            docs_text[rel] = " ".join(fh.read().lower().split())
    said = dict((rel, "third watched" in text and "checkout's own `.claude/`" in text
                 and "refuses to start" in text)
                for rel, text in docs_text.items())
    check("cw16 CONTRIBUTING.md and the docstring of tests/_harness.py "
          "fixture_root both describe the checkout's own .claude/ as a third "
          "watched directory and say the sweep refuses to start when its temp "
          "directory is inside a checkout - they listed two watched directories "
          "for as long as that was true: %r" % (said,),
          all(said.values()) and len(said) == 2)


def _cases(check):
    """Every branch of `grade` plus the two refusals, driven without a subprocess."""
    _suite_root_cases(check)
    _claude_watch_cases(check)
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
        taken = bg_wait(ticket, bg_weights[ticket])
        with bg_lock:
            bg_state["held"] += taken
            bg_state["peak"] = max(bg_state["peak"], bg_state["held"])
            bg_state["order"].append(ticket)
        time.sleep(0.05)
        with bg_lock:
            bg_state["held"] -= taken
        bg_done(taken)
    with futures.ThreadPoolExecutor(max_workers=4) as bg_pool:
        list(bg_pool.map(bg_task, range(len(bg_weights))))
    check("bg4 the slot gate never lets more than the budget be held at once and "
          "admits in ticket order - a cheap file cannot slip past a staged suite "
          "waiting for its slots: %r" % (bg_state,),
          bg_state["peak"] <= 4 and bg_state["peak"] >= 3
          and bg_state["order"] == list(range(len(bg_weights))))

    # THE HEAD TAKES WHAT IS FREE. Three plain files hold three of four slots;
    # a staged suite asking for three is admitted AT ONCE with the one left,
    # rather than waiting for all three while that slot idles. And the other
    # direction, which a gate that stopped counting would fail: with nothing
    # free the next ticket waits, and a head never takes more than is free or
    # more than it asked for.
    mg_wait, mg_done = slot_gate(4)
    mg_plain = [mg_wait(t, 1) for t in range(3)]
    mg_got = {}

    def mg_ask(ticket, weight):
        mg_got[ticket] = mg_wait(ticket, weight)
    mg_head = threading.Thread(target=mg_ask, args=(3, 3))
    mg_head.daemon = True
    mg_head.start()
    mg_head.join(2.0)
    mg_at_once = dict(mg_got)
    mg_next = threading.Thread(target=mg_ask, args=(4, 1))
    mg_next.daemon = True
    mg_next.start()
    mg_next.join(0.3)
    mg_blocked = 4 not in mg_got
    for _held in mg_plain:
        mg_done(_held)
    mg_head.join(2.0)
    mg_next.join(2.0)
    # In a thread with a bound, so a gate that waits for the full ask hangs
    # nothing and reads as the empty list it produced.
    mg_small_wait, _mg_small_done = slot_gate(4)
    mg_small = []
    mg_two = threading.Thread(target=lambda: mg_small.extend(
        [mg_small_wait(0, 2), mg_small_wait(1, 9)]))
    mg_two.daemon = True
    mg_two.start()
    mg_two.join(2.0)
    check("bg4b a staged suite at the head of the queue is admitted with the "
          "slots that are free, at least one, instead of waiting for its full "
          "grant while they idle; with none free the next ticket waits; a head "
          "takes no more than it asked for and no more than is free: plain %r, "
          "head at once %r, next blocked %r then %r, two heads on a fresh "
          "budget %r" % (mg_plain, mg_at_once, mg_blocked, mg_got, mg_small),
          mg_plain == [1, 1, 1] and mg_at_once == {3: 1}
          and mg_blocked and mg_got == {3: 1, 4: 1}
          and mg_small == [2, 2])

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
              "admitted with that many free, and one for any other file, gives "
              "the timed-heavy one its "
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
          bg_line.startswith("budget: 4 slots; 1 staged suites hold up to 3 each "
                             "(staged-suite); per-file timeout %ds"
                             % (DEFAULT_TIMEOUT,))
          and "up to %ds" % (300 * TIMEOUT_PER_COST,) in bg_line
          and "deadline" not in bg_line
          and "up to 500s" in bg_cut and "named by 500s" in bg_cut)

    # --- a suite split into blocks: every case kept, an empty block red -------
    # The same four cases written as ONE run and as TWO staged blocks, each run
    # through the sweep for real - the harness's own `staged_main`, its child
    # protocol and its replay - so a split that lost a block's cases, or counted
    # one twice, reads as a total that moved. The third file is the split with
    # one block emptied: a block that asserts nothing must turn its file red by
    # name, never pass as a block with nothing wrong in it.
    sb_head = ("import sys\n"
               "sys.path.insert(0, %r)\n"
               "import _harness\n\n\n"
               "def _a_cases(check):\n"
               "    check('ka1 the first block, first case', True)\n"
               "    check('ka2 the first block, second case', True)\n\n\n"
               % (os.path.join(REPO, "tests"),))
    sb_second = ("def _b_cases(check):\n"
                 "    check('kb1 the second block, first case', True)\n"
                 "    check('kb2 the second block, second case', True)\n\n\n")
    sb_staged = ("STAGES = (('a-block', '_a_cases'), ('b-block', '_b_cases'))\n"
                 "if __name__ == '__main__':\n"
                 "    raise SystemExit(_harness.staged_main(sys.argv[1:], STAGES, "
                 "globals(), 'sweep-sb-'))\n")
    sb_sources = {
        "whole-suite": sb_head + sb_second
        + "def _all(check):\n    _a_cases(check)\n    _b_cases(check)\n\n\n"
        "raise SystemExit(_harness.run(_all))\n",
        "split-suite": sb_head + sb_second + sb_staged,
        "hollow-suite": sb_head + "def _b_cases(check):\n    return None\n\n\n"
        + sb_staged,
    }
    sb_box = tempfile.mkdtemp(prefix="sweep-split-")
    try:
        for sb_name, sb_text in sb_sources.items():
            with io.open(os.path.join(sb_box, sb_name), "w", encoding="utf-8") as fh:
                fh.write(sb_text)
        sb_rows = dict((r["path"], r) for r in sweep(sorted(sb_sources), jobs=4,
                                                     repo=sb_box))
    finally:
        remove_tree(sb_box)
    sb_ids = ("ka1", "ka2", "kb1", "kb2")
    sb_seen = dict((k, (v["ok"], v["cases"],
                        [len(re.findall(r"(?m)^PASS %s " % (i,), v["output"]))
                         for i in sb_ids]))
                   for k, v in sb_rows.items())
    check("sb1 a staged suite split into blocks reports the same total case "
          "count through the sweep as the same cases run whole, each case once "
          "and every one passing, and the split one really ran as blocks: %r"
          % (sb_seen,),
          sb_seen.get("whole-suite") == (True, 4, [1, 1, 1, 1])
          and sb_seen.get("split-suite") == (True, 4, [1, 1, 1, 1])
          and sb_rows["split-suite"].get("blocks") == 2
          and "stage pool: 2 blocks run by the sweep" in sb_rows[
              "split-suite"]["output"],
          sb_rows.get("split-suite", {}).get("output", "")[-600:])
    sb_hollow = sb_rows.get("hollow-suite") or {}
    sb_out = sb_hollow.get("output") or ""
    check("sb2 ...and a block that asserts nothing is red by name: the file "
          "fails, the empty block is ONE failing case saying it did not report, "
          "and the other block's cases still ran and passed: %r"
          % ((sb_hollow.get("ok"), sb_hollow.get("why"), sb_hollow.get("cases")),),
          sb_hollow.get("ok") is False and sb_hollow.get("why") == "exited 1"
          and len(re.findall(r"(?m)^FAIL b-block DID NOT REPORT", sb_out)) == 1
          and len(re.findall(r"(?m)^FAIL ", sb_out)) == 1
          and [len(re.findall(r"(?m)^PASS %s " % (i,), sb_out))
               for i in ("ka1", "ka2")] == [1, 1]
          and CONTRACT.findall(sb_out)[-1:] == [("2", "3")],
          sb_out[-600:])

    # --- blocks, not suites, share the budget ----------------------------------
    # Two staged suites of three blocks each on a four-slot budget. Every block
    # labels its cases with the moments it slept between, so the run is read
    # off what the blocks themselves saw. The `b` blocks sleep far longer than
    # the `a` ones: with blocks as the unit, the first `b` block starts beside
    # the three `a` ones and the other two take the slots those free, so at
    # some moment two `b` blocks run at once; a suite admitted on a fixed share
    # - one slot, behind a suite holding three - runs its blocks one by one.
    bb_body = ("import sys, time\n"
               "sys.path.insert(0, %(tests)r)\n"
               "import _harness\n\n\n"
               "def _span(check, tag, nap):\n"
               "    t0 = time.time()\n"
               "    time.sleep(nap)\n"
               "    check('%%s1 first span=%%r' %% (tag, (t0, time.time())), True)\n"
               "    check('%%s2 second of %%s' %% (tag, tag), True)\n\n\n"
               "def _1_cases(check):\n    _span(check, '%(p)sa', %(nap)r)\n\n\n"
               "def _2_cases(check):\n    _span(check, '%(p)sb', %(nap)r)\n\n\n"
               "def _3_cases(check):\n    _span(check, '%(p)sc', %(nap)r)\n\n\n"
               "STAGES = (('one-block', '_1_cases'), ('two-block', '_2_cases'),\n"
               "          ('three-block', '_3_cases'))\n"
               "if __name__ == '__main__':\n"
               "    raise SystemExit(_harness.staged_main(sys.argv[1:], STAGES, "
               "globals(), 'sweep-bb-'))\n")
    bb_tests = os.path.join(REPO, "tests")
    bb_box = tempfile.mkdtemp(prefix="sweep-blocks-")
    try:
        for bb_name, bb_p, bb_nap in (("a-suite", "a", 0.3), ("b-suite", "b", 3.0)):
            with io.open(os.path.join(bb_box, bb_name), "w", encoding="utf-8") as fh:
                fh.write(bb_body % {"tests": bb_tests, "p": bb_p, "nap": bb_nap})
        bb_rows = dict((r["path"], r) for r in sweep(
            ["a-suite", "b-suite"], jobs=4, repo=bb_box, costs={}))
        bb_line = budget_line(["a-suite", "b-suite"], 4, {}, DEFAULT_TIMEOUT,
                              repo=bb_box)
    finally:
        remove_tree(bb_box)
    bb_spans = []
    for bb_path, bb_row in sorted(bb_rows.items()):
        for bb_got in re.findall(r"(?m)^PASS [ab][abc]1 first span=\(([0-9.]+), "
                                 r"([0-9.]+)\)", bb_row.get("output") or ""):
            bb_spans.append((bb_path, float(bb_got[0]), float(bb_got[1])))

    def bb_running(at):
        return [p for p, start, end in bb_spans if start <= at < end]
    bb_moments = [bb_running(start) for _p, start, _e in bb_spans]
    bb_ids = dict((p, [len(re.findall(r"(?m)^PASS %s%s%d " % (p[0], b, n),
                                      r.get("output") or ""))
                       for b in "abc" for n in (1, 2)])
                  for p, r in bb_rows.items())
    check("bb1 blocks of two staged suites share the worker budget: at some "
          "moment blocks of both run, at some moment two blocks of the suite "
          "started second run at once, never more blocks than slots - and no "
          "case is lost from either, each id printed once and every file "
          "green with its whole count: spans %r, ids %r, rows %r"
          % (bb_spans, bb_ids,
             dict((k, (v["ok"], v["cases"], v.get("blocks"), v.get("why")))
                  for k, v in bb_rows.items())),
          len(bb_spans) == 6
          and any("a-suite" in m and "b-suite" in m for m in bb_moments)
          and any(m.count("b-suite") >= 2 for m in bb_moments)
          and max(len(m) for m in bb_moments) <= 4
          and bb_ids == {"a-suite": [1] * 6, "b-suite": [1] * 6}
          and all(r["ok"] and r["cases"] == 6 and r.get("blocks") == 3
                  for r in bb_rows.values()))
    check("bb1b ...and the budget line names the suites it runs block by block "
          "and how many blocks that is: %r" % (bb_line,),
          bb_line.startswith("budget: 4 slots; 0 staged suites hold up to 3 "
                             "each (none);")
          and bb_line.rstrip().endswith("2 staged suites run block by block, "
                                        "a slot a block, 6 blocks (a-suite, "
                                        "b-suite)"))

    bb_table = ("STAGES = (('x-block', '_x_cases'), ('y-block', '_y_cases'))\n"
                "staged_main()\n")
    bb_labels = [stage_labels(bb_table),
                 stage_labels("STAGES = tuple(ROWS)\nstaged_main()\n"),
                 stage_labels("STAGES = (('x', '_a'), ('x', '_b'))\n"),
                 stage_labels("STAGES = ()\n"),
                 stage_labels("STAGES = (('x', '_a', 3),)\n"),
                 stage_labels("def f():\n    STAGES = (('x', '_a'),)\n"),
                 stage_labels("STAGES = (\n")]
    check("bb2 a staged suite's blocks are the labels of its `STAGES` literal, "
          "in order; a computed table, a repeated label, an empty or misshapen "
          "table, one not at module level and a file that does not parse give "
          "none, and such a suite runs whole on a grant: %r" % (bb_labels,),
          bb_labels == [["x-block", "y-block"], None, None, None, None, None,
                        None])
    bb_costs = {"heavy": 100.0, "split": 240.0, "light": 1.0}
    bb_order = work_items(["light", "split", "heavy"], bb_costs,
                          {"split": ["s1", "s2", "s3"]})
    bb_wide = work_items(["light", "split", "heavy"], dict(bb_costs, split=600.0),
                         {"split": ["s1", "s2", "s3"]})
    check("bb3 the jobs are ordered by estimate, costliest first: a block is "
          "its file's cost over its blocks, so three blocks of a 240-second "
          "suite go after a 100-second file, and three of a 600-second one "
          "before it; blocks keep their table's order: %r / %r"
          % (bb_order, bb_wide),
          bb_order == [("heavy", None), ("split", "s1"), ("split", "s2"),
                       ("split", "s3"), ("light", None)]
          and bb_wide == [("split", "s1"), ("split", "s2"), ("split", "s3"),
                          ("heavy", None), ("light", None)])
    bb_ran = [("one", {"code": 0, "debris": ["working directory: x"],
                       "seconds": 2.0, "timeout": 900, "began_ns": 10,
                       "ended_ns": 20, "output": ""}),
              ("two", {"code": None, "debris": ["home directory: y"],
                       "seconds": 900.0, "timeout": 900, "began_ns": 30,
                       "ended_ns": 40, "output": "did not finish within 900s"})]
    bb_replay = {"code": 1, "output": "0/1 cases " + "passed\n",
                 "debris": ["home directory: z"], "seconds": 0.5,
                 "began_ns": 50, "ended_ns": 60}
    bb_suite = suite_ran("s", bb_ran, bb_replay)
    bb_entries = [block_entry(lab, "c-%s" % (lab,), r) for lab, r in bb_ran]
    check("bb4 a suite run as blocks stands for one result: the replay's exit "
          "and output, the debris of each finished block naming the block and "
          "none from a killed one, the seconds of every process summed, one "
          "window each; the replay is told a killed block's why and not its "
          "output: %r / %r" % (bb_suite, bb_entries),
          bb_suite["code"] == 1 and bb_suite["output"] == bb_replay["output"]
          and bb_suite["debris"] == ["block one, working directory: x",
                                     "home directory: z"]
          and bb_suite["seconds"] == 902.5 and bb_suite["blocks"] == 2
          and bb_suite["grant"] == 1 and bb_suite["timeout"] == 900
          and bb_suite["windows"] == [(10, 20), (30, 40), (50, 60)]
          and bb_entries == [
              {"label": "one", "cases": "c-one", "code": 0, "out": "",
               "why": ""},
              {"label": "two", "cases": "c-two", "code": None, "out": "",
               "why": "did not finish within 900s"}])
    bb_slack = CLAUDE_START_SLACK_NS
    bb_win = {"blocks": [(0, 100), (10 * bb_slack, 10 * bb_slack + 100)],
              "other": (2 * bb_slack, 3 * bb_slack)}
    bb_by, bb_loose = claude_verdicts(
        [{"text": "gap", "at": 2 * bb_slack + 5},
         {"text": "inside", "at": 10 * bb_slack + 50}], bb_win)
    check("bb5 a suite run as several processes is a candidate for a change "
          "only inside one of their windows, not in the gaps between them, "
          "where another suite ran: %r / %r" % (bb_by, bb_loose),
          bb_by == {"other": ["gap"], "blocks": ["inside"]} and bb_loose == [])


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
    bb_buf = io.StringIO()
    render([dict(grade("a/split-suite", 0, "9/9 cases passed\n", set()),
                 seconds=912.34, grant=1, blocks=40)], 4, stream=bb_buf)
    bb_text = bb_buf.getvalue()
    check("bb6 a suite run block by block prints its summed seconds beside its "
          "count of blocks, and reads back as those seconds - already "
          "slot-seconds, never multiplied by the blocks: %r / %r"
          % (bb_text, costs_from_render(bb_text)),
          "[912.3s, 40 blocks]" in bb_text
          and costs_from_render(bb_text) == {"a/split-suite": 912.3})
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
          "live table, at the slots it asks for, reaches past it - so the "
          "deadline cuts a hang, or a staged suite admitted late with fewer "
          "slots, and never the margin a heavy file was given at its full "
          "grant: deadline %ds + setup %ds vs %r minutes; longest "
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
