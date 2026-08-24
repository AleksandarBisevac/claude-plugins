#!/usr/bin/env python3
"""
Run every `--selftest` in the tree, in parallel, under the STRICTEST of the three
sweeps that used to exist.

    tools/sweep-selftests.py                     # the sweep, all cores but two
    tools/sweep-selftests.py --jobs 1            # serial, for a bisect
    tools/sweep-selftests.py --encoding cp1252   # the "can it print" pass
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

AND EVERY CHILD RUNS IN AN EMPTY DIRECTORY IT IS EXPECTED TO LEAVE EMPTY (F119). A
suite is run with its cwd AND `TMPDIR` pointed at a scratch directory holding one
file it did not put there, and the file is red if anything was added to that
directory, or the file that was already in it was removed or rewritten. Suites here
had been leaking git fixtures into whatever directory `TMPDIR` named for a long
time, and none of the gates could see it because `TMPDIR` is normally the system
temp. `run_one` and `scratch_debris` say what each half of that buys.

AND THE HOME DIRECTORY IS A SECOND WATCHED DIRECTORY (F138). `TMPDIR` closes the
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
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
SWEEP_DIRS = (
    os.path.join("plugins", "audit", "hooks"),
    os.path.join("plugins", "audit", "scripts"),
    os.path.join("plugins", "audit", "tests"),
    "tools",
)

# The contract every non-migrated suite must print. Kept as ONE pattern because the
# grader reads it twice with opposite expectations - present for a live suite,
# ABSENT for a migrated one - and two spellings of it would be two rules.
CONTRACT = re.compile(r"(\d+)/(\d+) cases passed")

# A file that has not finished by then is reported as a TIMEOUT rather than waited
# on forever. Neither old copy had one, so a hung selftest was indistinguishable
# from a slow machine and the sweep simply never returned.
DEFAULT_TIMEOUT = 300


# --- discovery ----------------------------------------------------------------
def sweep_files(repo=None):
    """Every `.py` under the swept directories, repo-relative, sorted.

    Delegates to `_output.py_files`, which is the same recursive walk the lints and
    `selftest_coverage()` use. A second implementation here is how CI's old flat
    glob came to disagree with the classifier about which files exist - a file in a
    subdirectory stopped being swept and nothing went red.
    """
    repo = repo or REPO
    out = []
    for rel_dir in SWEEP_DIRS:
        directory = os.path.join(repo, rel_dir)
        if not os.path.isdir(directory):
            continue
        for rel, _path in _output.py_files(directory):
            out.append("%s/%s" % (rel_dir.replace(os.sep, "/"), rel))
    return sorted(out)


def covered_paths():
    """The migrated set, from the classifier CI already asks - not a name transform.

    `covered_repo_paths()` is what `_output.py --covered` prints, so this runner and
    CI's old shell loop cannot disagree about which files are skipped. Returned as a
    set because the only question asked of it is membership.
    """
    return set(_output.covered_repo_paths())


# --- the scratch directory a child is run in ----------------------------------
# F119: a suite reached outside its own temp directory and destroyed what was there.
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


# --- removing that directory, and the copy that does it -----------------------
# ONE FACT, TWO HOMES, AND THIS SECTION IS BOTH THE COPY AND THE THING THAT
# COMPARES THEM. The fact is that git writes its loose objects READ-ONLY, so on
# windows the ordinary removal call cannot unlink them - and every caller here
# spells it `ignore_errors=True`, which means the removal had never worked there
# and nothing said so. `_harness.remove_tree()` is where that fact lives, with the
# measurement that chose it and the two cases that prove both of its directions.
REMOVAL_HELPER_HOME = os.path.join("plugins", "audit", "tests", "_harness.py")
REMOVAL_HELPER = "remove_tree"


def remove_tree(path):
    """`shutil.rmtree` that also works on a fixture containing a git repository.

    THE COPY, NOT THE HOME. `_harness.remove_tree()` under `plugins/audit/tests/`
    owns this - the measurement that chose the fallback order and the pair of
    cases proving both of its directions live there - and `removal_helper_drift()`
    below compares the two statement for statement so the copy cannot drift.

    WHY THIS RUNNER MAY NOT IMPORT THE HOME, which is the reason the copy is
    correct rather than merely cheap: that file is one of the files this sweep
    RUNS. A runner that imports its own subject in order to start cannot report
    that subject as red - a harness with a syntax error would arrive here as a
    traceback out of this module instead of as one failing row among the rest,
    and a checker that cannot start when the thing it checks is broken reports
    nothing at all. The import cost is the smaller half of the argument and is
    smaller than it reads: `_output.install_path()` above has already put
    `scripts/` and every subdirectory of it on this path, and the pool below is
    THREADS, so the import would be paid once per run rather than once per file.
    """
    shutil.rmtree(path, ignore_errors=True)
    if not os.path.exists(path):
        return
    for base, dirs, names in os.walk(path):
        for name in dirs + names:
            try:
                os.chmod(os.path.join(base, name), 0o700)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def _def_shape(source, name):
    """`(shape, problem)` for a module-level `def name` - exactly one is None.

    The shape is the function's statements dumped from the AST with the DOCSTRING
    DROPPED, and that narrowing is the whole reason a comparison of two copies can
    be written at all: the home and the copy have to say different things about
    themselves - one carries the measurement, the other carries the pointer and
    the reason it is a copy - while running the same statements. `ast.dump` keeps
    no line numbers either, so moving the function is not drift.

    A source that will not parse is REPORTED rather than skipped, because a
    comparison that quietly answers "they agree" about a file nobody could read is
    the silent pass this rule exists to prevent.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return None, "does not parse, so nothing can be compared: %s" % (exc,)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != name:
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        if not body:
            return None, "carries `%s` with nothing in it but a docstring" % (name,)
        return "\n".join(ast.dump(stmt) for stmt in body), None
    return None, "carries no module-level `def %s`" % (name,)


def removal_helper_drift(runner_source, home_source, name=REMOVAL_HELPER):
    """Why this runner's copy of `name` is not the home's any more, or None.

    A PURE FUNCTION OVER TWO TEXTS, so both directions are driven from strings
    rather than from files written into a temp directory - and so the case that
    reads the real tree is one call rather than a fixture that encodes the same
    assumption the copy does.

    The two sides are named apart in every message. "the runner's copy" and "the
    home" are two different repairs - delete the copy's divergence, or carry the
    home's change across - and a finding that said only "they differ" would leave
    a reader to guess which file is ahead.
    """
    runner, why = _def_shape(runner_source, name)
    if why is not None:
        return "the runner's copy %s" % (why,)
    home, why = _def_shape(home_source, name)
    if why is not None:
        return "the home %s" % (why,)
    if runner != home:
        return ("the runner's `%s` no longer runs the statements the home's does - "
                "one of the two was changed without the other" % (name,))
    return None

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
def run_one(rel_path, repo=None, encoding=None, timeout=DEFAULT_TIMEOUT,
            pycache=None):
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
    under its own channel (F138). It is allocated BESIDE the working one rather than
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

    stderr is folded into stdout (`2>&1`, as both old copies did) so a traceback
    lands in the same stream as the contract line, in order. Bytes are decoded with
    `replace`: under `--encoding cp1252` the child deliberately writes a legacy code
    page, and a runner that died decoding its output would be a runner that cannot
    run the pass it exists to run.
    """
    repo = repo or REPO
    env = dict(os.environ)
    if encoding:
        env["PYTHONIOENCODING"] = encoding
    # A SHORT PREFIX, deliberately. This directory becomes the root of every fixture
    # path the child builds, and windows still refuses a path past its own limit -
    # the deepest fixture in this tree is a git object under a linked worktree.
    scratch = tempfile.mkdtemp(prefix="sw-")
    home = tempfile.mkdtemp(prefix="sh-")
    owned = [scratch, home]
    for name in TEMP_VARS:
        env[name] = scratch
    env.update(home_env(home))
    if pycache is None:
        pycache = tempfile.mkdtemp(prefix="sp-")
        owned.append(pycache)
    env["PYTHONPYCACHEPREFIX"] = pycache
    for root in (scratch, home):
        io.open(os.path.join(root, SENTINEL), "wb").write(SENTINEL_BYTES)
    argv = [sys.executable, os.path.join(repo, rel_path), "--selftest"]
    try:
        done = subprocess.run(argv, cwd=scratch, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
        code = done.returncode
        output = done.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        code, output = None, "did not finish within %ds" % (timeout,)
    except OSError as exc:
        code, output = None, "could not be started: %s" % (exc,)
    # MEASURED BEFORE THE REMOVAL, so what the child left is read rather than
    # inferred from a cleanup that may itself have failed.
    debris = child_debris(scratch, home)
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
    return {"path": rel_path, "code": code, "output": output, "debris": debris}


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


def grade(rel_path, code, output, covered, encoding_pass=False, debris=()):
    """The verdict for one run, as a pure function of what the run produced.

    The rules, and the strictest reading of each of the two old copies:

      * a run that WROTE OUTSIDE ITS OWN FIXTURES - into the directory it was
        launched from, or into the home directory it was handed - is red whatever
        else it did, the encoding pass included. A suite that leaks a fixture leaks
        it in every pass, and there is no mode in which writing there is fine. It is
        read after the exit code because a suite that also went red has a traceback
        printed in full and a developer fixes that first; the leak is still waiting
        on the next run and this line still names it, and names WHICH of the two
        directories it landed in.
      * `encoding_pass` - a codec was forced, and the only claim is that the file
        can PRINT what it prints on a stream that cannot spell every character.
        Nothing is skipped and no contract is required, exactly as CI's second step
        had it: a migrated file's one-line pointer has to survive a legacy code page
        as much as a suite does.
      * a MIGRATED file (in `covered`) must exit 0 and must NOT print the contract.
        `selftest_coverage()` classifies by STRING LITERAL, so a file that assembles
        the line (`"0/0 cases " + "passed"`) reads as migrated while still printing
        it; this is the net under that blind spot.
      * every other file must exit 0 AND print the contract. This is the rule
        `verify.sh` did not have, and the reason a suite could be deleted from a
        file without anything going red locally.
    """
    def row(ok, why, cases=0, skipped=False):
        """One shape, built in one place, and it CARRIES the output it graded.

        Written as six dict literals first, and `render` then read an `output` key
        that only `sweep` bolted on afterwards - so a red row rendered through any
        other caller printed "(no output)" and hid the traceback. A row that leaves
        its evidence behind cannot develop that gap.
        """
        return {"path": rel_path, "ok": ok, "why": why, "cases": cases,
                "skipped": skipped, "output": output}

    if code is None:
        return row(False, output)
    if code != 0:
        return row(False, "exited %d" % (code,))
    if debris:
        return row(False, "wrote outside the fixtures it makes for itself: %s"
                          % ("; ".join(debris),))
    if encoding_pass:
        return row(True, None)
    claimed = cases_in(output)
    if rel_path in covered:
        if claimed is not None:
            return row(False, "listed as migrated but still prints the suite "
                              "contract")
        return row(True, None, skipped=True)
    if claimed is None:
        return row(False, "no --selftest (every hook, script, test and tool must carry one)")
    return row(True, None, cases=claimed)


# --- the sweep ----------------------------------------------------------------
def default_jobs(cpus=None):
    """All cores but two, and never below one.

    Two are left for the machine that is also running an editor and a browser gate;
    below one is not a number of workers.
    """
    cpus = cpus if cpus is not None else (os.cpu_count() or 1)
    return max(1, cpus - 2)


def sweep(paths, covered, jobs=None, repo=None, encoding=None,
          timeout=DEFAULT_TIMEOUT):
    """Run every path and return one graded row per file, sorted by path.

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
    pycache = tempfile.mkdtemp(prefix="sp-run-")
    try:
        with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            pending = [pool.submit(run_one, p, repo, encoding, timeout, pycache)
                       for p in paths]
            for fut in futures.as_completed(pending):
                ran = fut.result()
                rows.append(grade(ran["path"], ran["code"], ran["output"], covered,
                                  encoding_pass=bool(encoding),
                                  debris=ran["debris"]))
    finally:
        shutil.rmtree(pycache, ignore_errors=True)
    return sorted(rows, key=lambda r: r["path"])


def render(rows, jobs, encoding=None, stream=None):
    """Print the table, then every failure IN FULL, then the summary. Returns exit.

    That order is not cosmetic: `verify.sh` shows `tail -12` of a failed step, so
    the last lines have to be the ones that say what broke. Full output goes above
    the summary because a step that hides its output in exactly the case you need it
    is worse than one that prints everything - CI's old comment says so, and this
    keeps that promise.
    """
    out = stream if stream is not None else sys.stdout
    bad = [r for r in rows if not r["ok"]]
    total_cases = sum(r["cases"] for r in rows)
    skipped = [r for r in rows if r["skipped"]]

    label = "encoding pass (%s)" % (encoding,) if encoding else "sweep"
    out.write("%s: %d files, %d workers\n" % (label, len(rows), jobs))
    for row in rows:
        if row["skipped"]:
            out.write("  ok      %-58s cases live in tests/\n" % (row["path"],))
        elif row["ok"]:
            out.write("  ok      %-58s %d cases\n" % (row["path"], row["cases"]))
        else:
            out.write("  FAILED  %-58s %s\n" % (row["path"], row["why"]))
    for row in bad:
        out.write("\n--- %s: %s ---\n" % (row["path"], row["why"]))
        out.write(row.get("output") or "(no output)")
        if not (row.get("output") or "").endswith("\n"):
            out.write("\n")
    out.write("\n")
    if bad:
        for row in bad:
            out.write("FAIL  %s: %s\n" % (row["path"], row["why"]))
    out.write("%d/%d files ok, %d migrated to tests/, %d cases\n"
              % (len(rows) - len(bad), len(rows), len(skipped), total_cases))
    return 1 if bad else 0


# --- entry point --------------------------------------------------------------
def _flag_value(argv, name, fallback):
    """`--name X` or `--name=X`, or the fallback. Two spellings, one reader."""
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return fallback


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    encoding = _flag_value(argv, "--encoding", None)
    timeout = int(_flag_value(argv, "--timeout", DEFAULT_TIMEOUT))
    jobs = int(_flag_value(argv, "--jobs", default_jobs()))

    paths = sweep_files()
    covered = covered_paths()
    if not paths:
        sys.stderr.write("sweep-selftests: found no .py under %s - refusing to "
                         "report a green sweep over nothing\n"
                         % (", ".join(SWEEP_DIRS),))
        return 2
    if not covered:
        sys.stderr.write("sweep-selftests: the migrated set is EMPTY, so the "
                         "migrated-file rules below would assert nothing. Run "
                         "`_output.py --covered` and find out why.\n")
        return 2
    rows = sweep(paths, covered, jobs=jobs, encoding=encoding, timeout=timeout)
    return render(rows, jobs, encoding=encoding)


# --- selftest -----------------------------------------------------------------
def _cases(check):
    """Every branch of `grade` plus the two refusals, driven without a subprocess."""
    covered = set(["plugins/audit/scripts/_output.py"])
    live = "plugins/audit/tests/test__output.py"
    migrated = "plugins/audit/scripts/_output.py"

    g = grade(live, 0, "ALL PASS: 7/7 cases passed\n", covered)
    check("g0 a live suite that exits 0 and prints the contract is ok, and its "
          "case count is READ rather than assumed: %r" % (g,),
          g["ok"] and g["cases"] == 7 and not g["skipped"])

    g = grade(live, 0, "ran some things\n", covered)
    check("g1 THE RULE verify.sh DID NOT HAVE: exit 0 with no contract is a "
          "FAILURE, not a pass - this is the case that let a suite be "
          "deleted with nothing going red locally: %r" % (g,),
          (not g["ok"]) and "no --selftest" in g["why"])

    # A NAMED LOCAL, because the prose scan reads this file now: a positional `0`
    # immediately in front of a string that opens with the noun reads as a
    # cardinality claim. Reworded rather than the pattern widened.
    _moved = "cases moved to plugins/audit/tests/\n"
    g = grade(migrated, 0, _moved, covered)
    check("g2 a migrated file exits 0, prints a pointer, contributes no cases "
          "and is NOT required to print the contract: %r" % (g,),
          g["ok"] and g["skipped"] and g["cases"] == 0)

    g = grade(migrated, 0, "ALL PASS: 0/0 cases passed\n", covered)
    check("g3 the trap under selftest_coverage()'s string-literal blind spot: a "
          "file listed as migrated that STILL prints the contract is red: "
          "%r" % (g,),
          (not g["ok"]) and "still prints" in g["why"])

    g = grade(live, 1, "Traceback\n", covered)
    check("g4 a non-zero exit is red and the code is NAMED, so the summary line "
          "says what happened: %r" % (g,),
          (not g["ok"]) and g["why"] == "exited 1")

    g = grade(migrated, 0, "ALL PASS: 3/3 cases passed\n", covered,
              encoding_pass=True)
    check("g5 the encoding pass asserts ONLY that the file could print - the "
          "same file that is red at g3 is green here, which is what makes "
          "the two passes two different questions: %r" % (g,),
          g["ok"] and g["cases"] == 0)

    g = grade(live, None, "did not finish within 300s", covered)
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
    subdir = [p for p in found if p.count("/") > 3]
    check("d0 discovery is RECURSIVE and reaches files in subdirectories - a "
          "flat glob is how CI's old loop silently stopped running a whole "
          "directory (%d files, %d of them nested)"
          % (len(found), len(subdir)),
          len(found) > 100 and len(subdir) > 20)

    check("d1 the list is sorted and carries no duplicate, so two green runs "
          "produce byte-identical logs and a path is swept once",
          found == sorted(found) and len(found) == len(set(found)))

    cov = covered_paths()
    check("d2 the migrated set is non-empty and repo-relative, in the SAME "
          "spelling discovery produces - a set that never matches would make "
          "g2 and g3 vacuous and the sweep would silently weaken to the old "
          "exit-code-only rule (%d paths)" % (len(cov),),
          len(cov) > 50 and all(p.startswith("plugins/audit/")
                                for p in cov))

    overlap = cov & set(found)
    check("d3 ...and every migrated path IS one of the swept paths, which is "
          "the assertion that the two spellings agree rather than merely "
          "look alike (%d of %d matched)" % (len(overlap), len(cov)),
          len(overlap) == len(cov))

    check("j0 worker count leaves two cores and never drops below one, so a "
          "single-core runner still runs",
          default_jobs(14) == 12 and default_jobs(1) == 1
          and default_jobs(2) == 1)

    v = _flag_value(["--jobs", "4"], "--jobs", 99)
    w = _flag_value(["--jobs=4"], "--jobs", 99)
    check("f0 both flag spellings read the same value and the fallback survives "
          "an empty argv",
          v == "4" and w == "4" and
          _flag_value([], "--jobs", 99) == 99)

    buf = io.StringIO()
    code = render([grade(live, 0, "1/1 cases passed\n", covered),
                   grade("plugins/audit/scripts/_deps.py", 1, "boom\n", covered)], 4,
                  stream=buf)
    text = buf.getvalue()
    check("r0 a red render exits 1, names the file twice (table and summary), "
          "reproduces the child's output IN FULL, and ends with the counts "
          "so `tail -12` of a failed step is the useful part",
          code == 1 and text.count("FAIL") == 2
          and "boom" in text and text.rstrip().endswith("%d cases" % 1))

    buf = io.StringIO()
    code = render([grade(live, 0, "5/5 cases passed\n", covered)], 4, stream=buf)
    check("r1 a green render exits 0, says FAIL nowhere, and still prints the "
          "count - so 'all ok' and 'nothing ran' cannot read the same",
          code == 0 and "FAIL" not in buf.getvalue()
          and ("%d cases" % 5) in buf.getvalue())
    buf = io.StringIO()
    render([grade(migrated, 0, "moved\n", covered)], 4, stream=buf)
    check("r2 a migrated file is reported as SKIPPED with its reason rather "
          "than as a silent zero, which is the row CI printed by hand",
          "cases live in tests/" in buf.getvalue())

    # -- the scratch-directory rule, without a subprocess ----------------------
    g = grade(live, 0, "ALL PASS: 9/9 cases passed\n", covered,
              debris=["working directory: left behind: probe-fixture-a1b2"])
    check("h0 a suite that exits 0, prints the contract AND changed the "
          "directory it ran in is RED, and the row NAMES what it left - the "
          "row this runner could not produce while every child ran in the "
          "repository root: %r" % (g,),
          (not g["ok"]) and "probe-fixture-a1b2" in g["why"]
          and "wrote outside the fixtures" in g["why"])

    g = grade(migrated, 0, "moved\n", covered, encoding_pass=True,
              debris=["working directory: DELETED left-by-the-runner, which was "
                      "there before it ran"])
    check("h1 ...and the ENCODING pass is graded by the same rule, which is the "
          "one mode that skips every other check - a suite does not stop "
          "leaking because the codec changed: %r" % (g,),
          (not g["ok"]) and "DELETED" in g["why"])

    # -- the home directory, which is the second watched one (F138) ------------
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
    # AND THE WORK DIRECTORY IS REMOVED IN A `finally` (F119). This block used to
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

        # THE EXACT F119 SHAPE: a `mkdtemp` with no cleanup, in a child that
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

        # -- F138: the channel TMPDIR pinning alone cannot see ------------------
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

        # The WIRING, at the level that actually runs in CI. Everything above
        # proves `run_one` observes and `grade` judges; this is the only case that
        # fails if `sweep()` stops carrying the observation from one to the other.
        rows = sweep([leaks], covered, jobs=1, repo=work, timeout=30)
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
    _real = "plugins/audit/tests/test__cli_fmt.py"
    ran = run_one(_real, timeout=60)
    check("x4 a suite this repo actually ships leaves its scratch directory "
          "exactly as it found it (%s: exit %r, %r)"
          % (_real, ran["code"], ran["debris"]),
          ran["code"] == 0 and ran["debris"] == [])

    # -- the removal helper this runner keeps a copy of ------------------------
    # ONE FACT, TWO HOMES, AND THESE ARE WHAT COMPARE THEM. `remove_tree` above is
    # a copy of the one under `plugins/audit/tests/`, because this runner may not
    # import a file it is one of the runners OF. A copy with nothing watching it is
    # the divergence this repo keeps recording, so the copy only earns its place
    # while rm1 is here. The BEHAVIOUR of the algorithm is proven where it lives -
    # its own suite drives a read-only tree through it in both directions - and rm1
    # is what carries that proof across to this file.
    _home_src = io.open(os.path.join(REPO, REMOVAL_HELPER_HOME),
                        encoding="utf-8").read()
    _self_src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    _drift = removal_helper_drift(_self_src, _home_src)
    check("rm1 this runner's copy of `%s` still runs the statements the one in %s "
          "does. Nothing else compares them, so this case is the difference "
          "between a deliberate copy and a fork nobody noticed: %r"
          % (REMOVAL_HELPER, REMOVAL_HELPER_HOME, _drift),
          _drift is None)

    _one = ('def remove_tree(path):\n    """The home, with its measurement."""\n'
            '    shutil.rmtree(path)\n')
    _prose = ('def remove_tree(path):\n    """The copy, with its pointer."""\n'
              '    shutil.rmtree(path)\n')
    # rm2 LOOKS VACUOUS AND IS THE SECOND-DIRECTION CASE: it is the only one here
    # that fails if the comparison stops dropping docstrings and starts convicting
    # the arrangement it exists to police. It is also what the ALLOW row in
    # `tools/prove-gates.py` weakens `_def_shape` to prove.
    check("rm2 a difference that is ONLY the docstring is not drift. The home "
          "carries the measurement and the copy carries the reason it is a copy, "
          "so the two are REQUIRED to read differently while running the same "
          "statements",
          removal_helper_drift(_one, _prose) is None)

    _moved = ('def remove_tree(path):\n    """The copy, with its pointer."""\n'
              '    shutil.rmtree(path, ignore_errors=True)\n')
    _why = removal_helper_drift(_moved, _one)
    check("rm3 ...and a difference in the STATEMENTS is reported, naming the side "
          "it read as ahead - 'drop the copy's divergence' and 'carry the home's "
          "change across' are two repairs, and a bare 'they differ' chooses "
          "neither: %r" % (_why,),
          _why is not None and "runner" in _why)

    _bad = "def remove_tree(:\n"
    check("rm4 a side that will not PARSE is reported rather than skipped, and "
          "the report says which side - answering 'they agree' about a file "
          "nobody could read is the silent pass this rule exists to stop: %r"
          % (removal_helper_drift(_bad, _one),),
          (removal_helper_drift(_bad, _one) or "").startswith(
              "the runner's copy does not parse")
          and (removal_helper_drift(_one, _bad) or "").startswith(
              "the home does not parse"))

    check("rm5 ...and a side that has lost the function altogether is reported "
          "from both directions, which is what a rename leaves behind: %r"
          % (removal_helper_drift("x = 1\n", _one),),
          "no module-level" in (removal_helper_drift("x = 1\n", _one) or "")
          and "no module-level" in (removal_helper_drift(_one, "x = 1\n") or ""))



def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
