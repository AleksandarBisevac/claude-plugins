#!/usr/bin/env python3
"""
Stamp a verification with the tree it was taken on, and grade that stamp later.

WHAT THIS IS FOR, from failures that all look like carelessness and are all one
structure: somebody acted on a HELD MODEL of state instead of a read of it. Case
counts quoted after the patch they described had landed on a different tree. A
patch taken against a branch that had moved, silently reverting a sibling's work,
caught only because a number dropped. A gate that was green, an edit that landed,
and the green still being cited afterwards. None of those is a lapse of care - a
verification is a claim about a tree, and a claim that does not carry its tree
cannot be told from one that is still true.

THE GATE ALREADY SOLVED THIS FOR ITS OWN ROWS. `run-test-gate.py` records three
identity fields on every run because an exit code cannot say WHICH state it was
about. `_tree_stamp` is that arithmetic, moved so this command and that one share
it rather than agree by coincidence; what this adds is the second question - is
the tree still the one the stamp names - and the third answer, that git may not be
able to say.

WHAT EACH FIELD DOES NOT DO, so nobody has to discover it. The dirty digest
records WHICH paths were dirty and never their contents, so on its own a rewrite
of an already-dirty file outside the declared scope - a sibling's in-flight edit,
in a tree several executors share - moves nothing. The `content` field is what
reads those bytes: `_tree_stamp.content_digest` over the tree, with the paths this
plugin's own recorder writes left out (`recorder_exclusion` below), and a bounded
per-path list beside it so a stale answer can NAME the path that moved. Every
field prints its limit beside itself, on the way in and on the way out, and a
version-1 stamp - which has no content field - says so when it is compared.

AND IT IS NOT THE DOCTOR. `/audit:doctor` already reports two neighbouring
things - that the hooks running in this session are an OLDER installed copy of the
plugin, and what an abandoned worktree has left behind - and neither is repeated
here. Those are questions about the INSTALLATION; this is a question about the
TREE, and a claim taken while the doctor was warning about a stale copy is a claim
whose stamp is worth having beside that warning rather than instead of it.

Usage:
  stamp-verification.py take    [--project DIR] [--files A [B ...]]
                                [--manifest M --task T] [--json]
  stamp-verification.py compare [--project DIR] [--stamp TEXT | --stamp-file F]
                                [--json]
  stamp-verification.py red     [--project DIR] --manifest M --task T
                                [--case ID|LABEL ...] [--introduces SYMBOL ...]
                                [--deps-from DIR] [--timeout S] [--json]
                                -- <test command>

  `compare` reads the stamp from stdin when neither --stamp nor --stamp-file is
  given, so a report or a commit message can be piped straight in.

Exit codes:
  0  compare: current - every field git could answer still agrees
     take:    the stamp was taken
  1  compare: STALE - the tree has moved, and the output names which field did
  3  compare: unestablished - git could not answer, so nothing was graded
  2  usage error, an unreadable manifest, a task id that is not there, or a stamp
     this code cannot read
  red: 0 proved - 1 not red (the test passed in the throwaway) - 3 could not
     prove (no case of the task's own failed an assertion, the run could not run,
     or it was interrupted) - 4 the throwaway tree could not be removed - 2 as
     above, and for a task with no test file, a symbol that is not an
     identifier, or a command that names the shared tree

RED IS THE THIRD ACTION, AND THE ONE THAT BUILDS SOMETHING. It proves a new test
can fail by running it in a throwaway tree - HEAD, with the task's test files
copied from the working tree over it - so nobody has to put code without the fix
back into a tree siblings are editing. The `red` section below says what it writes
and how the removal is checked.

WHY THREE CODES AND NOT TWO. `unestablished` must not share an exit code with
either neighbour. Sharing 0 makes an unanswerable comparison read as "unchanged",
which is the false clean sheet the whole design refuses; sharing 1 makes it read
as "the tree moved", which sends a reader to re-run work that may be perfectly
current. A caller that only wants a pass/fail gets it by testing for 0.

`take` and `compare` mutate nothing: no lock is taken, no file is written, and
git is only read. `red` never writes the working tree it is pointed at; it writes a
temp directory and the worktree registration for it, and removes both on every
path but SIGKILL, which no process can catch - the `red` section says what is
reported instead.

RED UNDER JEST AND VITEST - THE DESIGN, BUILT. Each part below says it is
built: `red` reads a jest or vitest tally, names its failing cases, credits one
to the task by its title chain, runs HEAD's baseline with a new jest or vitest
test file absent (3), and links the ignored dependency directories in (4). It
was written here, before the code, so that the tasks that
build it share one answer to each question below rather than each settling its
own; a case of the implementing work is what makes each paragraph true, and
until one exists the paragraph is a plan. Nothing enforces that order; whoever
builds a part rewrites its paragraph into the present tense in the same change.

(1) ONE READER OF RUNNER OUTPUT, AT LAYER 1 - BUILT.
`scripts/governance/_runner_output.py` owns every reading of what a test runner
printed, imported by both entry points and by nothing below them; it reaches
nothing but `_output`, which is what puts it at layer 1. Moved there, not
copied, from `run-test-gate.py`: `_SUMMARY_READERS`, `_SUMMARY_PAIR`,
`_NO_TESTS`, `summary_reader`, `summary_readers`, `summary_count`,
`_FAILURE_READERS`, `_ANSI`, `_JEST_SUITE_HEADER`, `JEST_EXEC_ERROR`,
`jest_failures` and `_VITEST_FAIL_LINE`; and from here the tally and case
readers (`TALLY_READERS`, `CASE_READERS` and their regexes). `failing_suites`
and its path filters are still `run-test-gate`'s, because they read
`_evidence_io`'s limits and that module sits above layer 1. The gate's pytest
summary row and `red`'s pytest tally are two patterns, not one (the end of the
next paragraph says why). `read_tally`, `failing_cases` and `jest_failures`
strip every terminal escape from the text once, on entry (`plain_text`), so a
runner forced into colour through a pipe (`FORCE_COLOR`) reads as it does
without it.

THE PER-CASE ASSERTION FLAG - BUILT. `_runner_output` now holds the tally and
case readers, and each jest or vitest case it reads carries `assertion`, true
only where the runner says an assertion failed, exactly as `failing_cases`
does for the other runners. Read off this output, observed on 2026-10-06 (the
versions are in the history below):
  jest   - a bullet `● outer › inner › adds` under a `FAIL <path>` header. The
           first non-blank line under it is the matcher hint
           (`expect(received).toBe(expected)`) for an `expect` failure, a hint
           naming the call (`assert(received)`,
           `assert.strictEqual(received, expected)`,
           `assert.throws(function)`; jest 30.5.2 on 2026-10-07) for
           `node:assert` - never an `AssertionError` line - and the
           exception (`TypeError: boom`) for a body that threw. Only the
           first two set the flag. `● Test suite failed to run` never sets it: the suite
           did not load, and its cause is the line under the heading.
  vitest - a `FAIL  <path> > outer > inner > adds` line under `Failed Tests`,
           followed by the error line: `AssertionError: ...` for an `expect`
           failure (chai's class) and for `node:assert`, the exception for a
           throw. Only `AssertionError` sets the flag. A
           `FAIL  <path> [ <path> ]` line under `Failed Suites` is a suite that
           never ran a test and never sets it.
The tally reads jest's `Tests:` line and vitest's `Tests` line through the
moved summary readers, and counts each suite that failed to run as a failure
with no case, so a run whose only failure is a crashed suite is
`collection-error`, never `red`. `command_runner` knows `jest` and `vitest` as
program basenames; a wrapper (`npm test`, `npx vitest`) names no runner and
the output decides. The house, pytest and unittest patterns moved unchanged,
so the two pytest summary patterns are still two: taking their union changes
what `red` reads, and is left to a change of its own.

(2) WHICH CASE IS THE TASK'S: THE HEADER PATH AND THE TITLE CHAIN - BUILT. A jest or
vitest case is identified by the suite path its `FAIL` header or line names
and its title chain - the `describe` titles and the test's own, split on
jest's ` › ` or vitest's ` > `. The path locates it in a declared test file
the way `case_site` locates a pytest node: relative to the throwaway's root,
or, where a config moved the root (a monorepo package), by a suffix that
matches exactly one declared test file and no other file; none or several
locate nothing.

The declared file's working-tree copy must define a test with exactly that
chain, and CREDIT IS REFUSED where any test file in HEAD's tree with a jest or
vitest test name (`_is_js_test_path`) holds the same title chain whose test
body is identical - the equivalent of the ast-identical def `credit_problem`
looks for (`_js_credit_problem`). `ast` reads only Python, so JS/TS source is
read by a SMALL STDLIB TOKENIZER (`js_test_cases`) rather than a text-level
reading: a regex cannot find which `test(` call sits inside which
`describe(` callback, because brackets inside strings, template literals,
comments and regex literals throw the nesting off; a tokenizer that knows
those token kinds can. It records each `describe` / `test` / `it` call, with
its chain, and keeps the test's argument tokens - comments and whitespace
dropped - as the body two copies are compared by. It fails CLOSED: a
declared file it cannot read with every literal closed and every bracket
balanced credits nothing, and such a HEAD file refuses every case whose
title it may hold (`_js_unread_holding`), because a misread HEAD copy would
otherwise look like no HEAD copy at all. A title built at run time - `.each`,
a template literal with `${}`, a variable - has no chain in the source; such
a case is refused credit by name, and so is a literal case a run-time title
of the same file could also fill in (a template's literal parts and a
`.each` format's text are matched; anything else matches every title at its
depth). JSX text and a regex literal right after `)` are the tokenizer's
known blind spots: a misreading either unbalances the file, which is refused,
or misreads HEAD's copy and the working tree's alike, so an unchanged body
still compares equal.

(3) THE BASELINE: A NEW FILE IS ABSENT, NOT AN EMPTY STUB - BUILT. HEAD's own run
lays each declared test file new at HEAD over as an empty file, and under
pytest that is what keeps a command naming the file runnable. Both JS runners
were driven on 2026-10-06, in a scratch directory outside this repository:
  jest 30.4.2, an installed copy in another local project, used read-only
  through `node <copy>/bin/jest.js --ci`, node v22.22.3:
    an empty test file                   -> `● Test suite failed to run` /
                                            `Your test suite must contain at
                                            least one test.`, exit 1
    the same, with --passWithNoTests     -> the same failure, exit 1
    no test file at all                  -> `No tests found, exiting with
                                            code 1`, exit 1
    no test file, with --passWithNoTests -> `No tests found, exiting with
                                            code 0`, exit 0
    a named path with no file behind it  -> `No tests found, exiting with
                                            code 1`, exit 1
  vitest 4.1.10, this repository's own `node_modules`, `vitest run`:
    an empty test file                   -> `FAIL  empty.test.js` /
                                            `Error: No test suite found in
                                            file ...`, exit 1
    the same, with --passWithNoTests     -> `Test Files  1 passed`,
                                            `Tests  no tests`, exit 0
    no test file at all                  -> `No test files found, exiting
                                            with code 1`, exit 1
    no test file, with --passWithNoTests -> `No test files found, exiting
                                            with code 0`, exit 0
    a named path with no file behind it  -> `No test files found, exiting
                                            with code 1`, exit 1
So an empty stub is RED under jest whatever the flag, and red under vitest
unless the command passes `--passWithNoTests`: HEAD's baseline would never be
green and every proof would be `could-not-prove`. So a new test file
`_is_js_test_path` reads as jest's or vitest's is left ABSENT in HEAD's run -
the reset already removes it - and the stub stays the rule for the Python
runners; the payload's `baseline` names which way each new file went. The
baseline is then green on exit 0, or on exit 1 with the runner's own
no-test-file sentence quoted above and no tally counting a case or a failure
(`_js_none_found`), read only when a file was left absent: the JS counterpart
of pytest's exit 5, and read off the sentence for the same reason - the exit
code alone is the one a crash gives too. `--passWithNoTests` is NOT added to
the command: under jest it does not rescue an empty stub, the absent file
makes the stub question moot for both runners, and a flag appended to a
wrapper's argv (`npm test`) reaches the wrapper rather than the runner.
Measured once per runner and version, on one machine.

(4) DEPENDENCIES: `--deps-from <dir>`, DEFAULTING TO `--project` - BUILT. The
throwaway holds tracked files only, so a suite that imports from
`node_modules` or runs from an in-repo `.venv` cannot load there. `red` asks
git, in `--deps-from`, for its ignored directories
(`ls-files --others --ignored --exclude-standard --directory`) and takes each
named `node_modules` or `.venv`, at any depth, whose parent directory exists
at HEAD and holds no link into the tree (`dependency_plan`). A dependency
directory is reproduced in the
throwaway as a real directory of per-entry symlinks into the source, rebuilt
after each reset, and never as one link to the whole directory: the cache
entries a runner writes (`.cache`; `.vite`, where vitest 4.1.10 was seen on
2026-10-06 to write `vitest/<hash>/results.json` after every run; and
`.vite-temp`, which this repository's own `node_modules` holds) are left out of
the links, so a runner that writes one creates it in the throwaway's real
directory. The basis names every directory linked and every one skipped, with
the reason (`deps_clause`).

THE LEAKS A LINK OPENS, each named and none left implicit:
  - a WORKSPACE LINK - an entry whose real path lands inside `--deps-from` or
    the project but outside every dependency directory (an npm or pnpm
    workspace package, a `pip install -e` path in a `.pth` file or an
    editable finder) - would load the SHARED tree's implementation into a
    run that is meant to see HEAD's. The directory holding one is not linked
    (`workspace_links`): its reason, naming the entry, goes into the plan's
    skipped list, which the basis prints, and the run is made without it. A
    command that never needed the directory - a unittest run by the system
    python beside an in-repo `.venv` - still proves; one that did fails for
    want of it, and the basis says which directory was left out and why. The
    scan reads only the entries that can be such a link - each top-level
    entry and each entry of a top-level `@scope` directory, and the `.pth` and
    `__editable__` files directly under a site-packages directory - never a
    walk of every installed file, and it stops at the deadline. The
    directory is not re-pointed at the throwaway's own copy of the package,
    because that copy lacks the package's own ignored build output, and the
    run would then fail for a reason that is not the test's.
  - CACHES WRITTEN BACK THROUGH A LINK. The cache directories above stay in
    the throwaway; jest's `cacheDirectory` follows `TMPDIR` (its
    `--showConfig` said so on 2026-10-06), which is the per-run directory
    `_isolated_env` already makes; bytecode under a linked `.venv`
    is not written, because every run already carries
    `PYTHONDONTWRITEBYTECODE`. Anything else a runner writes into a linked
    package lands in the shared tree, and the basis says that this is not
    watched.
  - REMOVAL MUST NOT FOLLOW A LINK. The reset's `git clean -ffdx` and the
    final `shutil.rmtree` both unlink a symlink rather than descend through
    it, or a cleanup would delete the shared tree's dependencies; the case
    that holds it keeps a sentinel file behind a link and asserts it survives
    every reset and the removal.

`.npmrc`. The jest and vitest binaries read none; npm, npx and pnpm, wrapping
them, do. A TRACKED project `.npmrc` arrives with HEAD. An untracked one, and
the user's own, do NOT reach the fresh home: the user's file carries registry
credentials and this helper does not read or copy a credential file. Each is
named as dropped in the basis when it exists - an existence check, never a
read - and `NPM_CONFIG_USERCONFIG`, in either case, is dropped from the run's
environment so that sentence stays true. A wrapper that then needs the
registry fails, and the result is `could-not-prove`.

WHAT THIS DESIGN ADDRESSES, from what was observed on 2026-10-06:
  - vitest's red being `could-not-prove` for want of `node_modules` in the
    throwaway: (4), with (1) to (3) to read the run once it can start.
  - a new jest or vitest test file turning HEAD's baseline red as an empty
    suite: (3).
  - an inline suite under `tools/`, whose test file is its implementation
    file, so no HEAD-versus-fix split exists: NOT addressed; left to a later
    task.
  - the removal cases that kill a run (SIGTERM, SIGKILL) failing inside the
    helper's own throwaway, so HEAD reads red there: NOT addressed, and its
    cause is not diagnosed here; left to a later task.
  - a stamp compare going stale because the evidence ledger the first
    `--record` creates is left out of `content` but still moves the dirty
    digest: NOT addressed - it is a `_tree_stamp` question, not a `red` one;
    left to a later task.
"""
import argparse
import ast
import datetime
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings

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

import _tree_stamp  # noqa: E402  (the ONE tree identity, shared with run-test-gate)
import _evidence_io  # noqa: E402  (recorded_paths: what the recorder writes, left out)
import _manifest_io as _mio  # noqa: E402  (dual-format loader: single file OR shards)
import _proc_group  # noqa: E402  (a child tree stopped whole; a stop signal as an exception)
import _locks  # noqa: E402  (pid_alive: whether a leftover throwaway's owner still runs)
import _worktrees  # noqa: E402  (git's worktree list read, and two spellings of one tree compared)
import _runner_output  # noqa: E402  (every reading of what a test runner printed, shared with run-test-gate)
import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)

USAGE = ("usage: stamp-verification.py take|compare|red [--project DIR] ...\n")

E_STALE, E_USAGE, E_UNESTABLISHED = 1, 2, 3

# The verdict -> exit code map, as a table rather than as three `if`s in `main`.
# One place decides what a word is worth, so the docstring above, the cases, and
# the caller cannot come to disagree about which answer exits 0.
EXIT_FOR = {_tree_stamp.CURRENT: 0,
            _tree_stamp.STALE: E_STALE,
            _tree_stamp.UNESTABLISHED: E_UNESTABLISHED}


def task_files(manifest, task_id):
    """`(files, problem)` - the paths one task declares. Exactly one is None.

    THE SCOPE COMES OFF THE PLAN AND NOT OFF A HAND-TYPED LIST wherever a plan
    exists, because the hand-typed list is the held model of state this command
    is about. A task that declares no files is NOT an error - it is a stamp with
    no scope digest, and `take` says so rather than inventing one."""
    for _phase, task in _mio.iter_tasks(manifest):
        if str(task.get("id")) != str(task_id):
            continue
        return [f for f in (task.get("files") or []) if isinstance(f, str)], None
    known = [str(t.get("id")) for _p, t in _mio.iter_tasks(manifest)]
    return None, ("no task %r in this manifest (have: %s)"
                  % (task_id, ", ".join(known) if known else "none"))


def resolve_scope(args):
    """`(files, problem)` - what this invocation declares, from either source.

    BOTH SOURCES AT ONCE IS A REFUSAL. A `--files` list beside a `--task` is two
    answers to "which work is this about", and silently preferring one would put
    the wrong scope under a right-looking digest - the failure in miniature."""
    if args.task and args.files:
        return None, ("--files and --task both name the work under test; pass "
                      "one, because a digest over the wrong file set is a stamp "
                      "about the wrong claim")
    if args.task:
        if not args.manifest:
            return None, "--task needs --manifest to resolve the task's files"
        try:
            manifest = _mio.load_manifest(args.manifest)
        except Exception as exc:
            return None, "cannot read/parse %s: %s" % (args.manifest, exc)
        if not isinstance(manifest, dict):
            return None, "manifest %s is not a JSON object" % (args.manifest,)
        return task_files(manifest, args.task)
    return list(args.files or []), None


def recorder_exclusion(project, manifest):
    """`(excluded, label, note)` - the paths the recorder writes, the manifest
    spelling the stamp stores, and a sentence for any write left IN.

    THE SAME DERIVATION ON BOTH SIDES. `take` passes `--manifest` as given and
    `compare` passes the `manifest` the stamp stored, and both go through here to
    `_evidence_io.recorded_paths` - the one list of what this plugin writes into
    a tree. Left in, the first journal row or manifest write after a stamp would
    move its content field and every stamp would go stale on the orchestrator's
    own bookkeeping. `manifest` is an absolute path or None; `label` is it
    project-relative where it sits inside the project, so a stamp compared from
    another working directory finds it (`stored_manifest`). `note` is None unless
    `recorded_paths` reported a write it could not exclude, which is said rather
    than absorbed."""
    root = os.path.abspath(project)
    path, label = manifest or None, None
    if path:
        rel = _output.posix_rel(os.path.realpath(path), os.path.realpath(root))
        label = path if rel == ".." or rel.startswith("../") else rel
    excluded, dropped = _evidence_io.recorded_paths(root, path)
    note = None
    if dropped:
        note = ("%d recorder write(s) could not be left out and stay inside the "
                "content field: %s"
                % (len(dropped), _output.some_of([d for d, _why in dropped])))
    return excluded, label, note


def stored_manifest(project, label):
    """The absolute path a stamp's stored `manifest` names, or None.

    The inverse of `recorder_exclusion`'s `label`: relative means relative to the
    project, never to whichever directory `compare` happens to run from."""
    if not isinstance(label, str) or not label.strip():
        return None
    return label if os.path.isabs(label) else os.path.join(
        os.path.abspath(project), label)


def read_stamp_text(args, stdin=None):
    """`(text, problem)` - the document the stamp is somewhere inside.

    STDIN IS THE DEFAULT because that is the shape the caller already has: a
    commit message, a report paragraph, an agent's reply. `parse_stamp` finds the
    token in it, and refuses a document carrying two."""
    if args.stamp is not None and args.stamp_file is not None:
        return None, "pass --stamp or --stamp-file, not both"
    if args.stamp is not None:
        return args.stamp, None
    if args.stamp_file is not None:
        try:
            with open(args.stamp_file, "r", encoding="utf-8") as fh:
                return fh.read(), None
        except (OSError, UnicodeDecodeError) as exc:
            return None, "cannot read %s: %s" % (args.stamp_file, exc)
    stream = stdin if stdin is not None else sys.stdin
    try:
        return stream.read(), None
    except Exception as exc:
        return None, "cannot read the stamp from stdin: %s" % (exc,)


# --- red: a red-first proof in a throwaway tree --------------------------------
# PROVING A TEST CAN FAIL MEANS RUNNING IT AGAINST CODE WITHOUT THE FIX, and the
# only way the briefs used to offer was to put that code back in the shared
# working tree - undo the fix, or write HEAD's copy over the file - for as long
# as the run took. In a tree siblings are editing that is a write over their
# ground, and a host refused it beside a sibling's uncommitted work. So the proof
# is made somewhere else: a `git worktree add --detach` of HEAD in a temp
# directory, with the working tree's copy of the task's TEST files laid over it
# and its implementation files left at HEAD. HEAD's own test files run FIRST,
# before any file of the task's is laid over - each declared test file new at
# HEAD written as an EMPTY file, or left absent where it is a jest or vitest
# one, so the same command reaches what the task's run reaches minus the new
# files' content - and must be green; then the task's run
# must be red, the fix run - the task's tests on the working tree's
# implementation - green, and only a failure the runner locates in a declared
# test file, whose named class defines it with no ast-identical def of that class
# chain and name anywhere in HEAD's test files (for jest and vitest: whose
# title chain it defines, with no identical test body under that chain in
# HEAD's test files), is the task's. Every run is made in the throwaway reset to HEAD with an isolated
# environment of its own, so the runs differ only in the files laid over. What
# that cannot see - state reached by an absolute path or the shared git
# directory, network state, a flaky HEAD case - is named in the guide.
#
# WHAT IT WRITES, AND WHAT IT CANNOT PROMISE, so nobody has to discover it.
# `git worktree add` registers the throwaway in the repository's administrative
# directory; the `finally` below removes that registration with the directory and
# then asks git whether either is still there, and a registration it could not
# remove is its own exit code. SIGINT and SIGTERM are turned into an exception so
# that `finally` runs, and the run's whole process group is torn down on a timeout
# or an interrupt, so no grandchild writes into a directory being removed.
# SIGKILL cannot be caught: a run killed that way leaves its throwaway, and the
# next `red` REPORTS it by name, never prunes it - it may be another run's, still
# going. The throwaway also shares the repository's git directory, so a test that
# runs git in its own cwd (a stash, a config write, a branch) writes shared refs;
# the environment is scrubbed of what points at the shared tree, but a test's own
# git commands are its own.
E_PROVED, E_NOT_RED, E_CANNOT_PROVE, E_LEFT_BEHIND = 0, 1, 3, 4

# The words this command writes, each one the schema's `redFirst.status` enum
# declares. A green run has no word here on purpose: a test that passes without
# the fix is work left to do, not an outcome to record.
RED_PROVED = "proved"
RED_CANNOT = "could-not-prove"
RED_WORDS = (RED_PROVED, RED_CANNOT)

V_RED, V_GREEN = "red", "green"
V_COLLECT, V_NO_TALLY, V_NOT_RUN = "collection-error", "no-tally", "could-not-run"
V_MIXED = "mixed-tally"

# The host's Bash tool gives a command at most this many seconds, and a helper it
# kills never reaches its own `finally`. The default stays under it with room for
# the teardown, so the helper's own timeout is the one that fires.
HOST_BASH_LIMIT = 600
DEFAULT_TIMEOUT = 480
# ONE deadline, `--timeout`, starts before anything runs and covers every git
# call that builds or reads the throwaway and every run - HEAD's own, the task's,
# the second (`--introduces`) and the fix run: each stage gets what the earlier
# ones left. `_isolated_run` makes no run, and `_isolate` starts neither of the
# reset's git calls, with less than a whole second left, so none of those is
# started past the deadline on the one-second floor a timeout is given. The
# git calls before the throwaway exists (listing and reading HEAD's files,
# building it) keep that floor and can overrun it by up to a second each. What happens after the deadline has to fit in
# the rest of the host's limit, so it is bounded and summed here: one teardown
# of a timed-out run (`_proc_group.GRACE_SECONDS` for SIGTERM, again for
# SIGKILL, again for the drain - at most one run can time out, because each
# later run is made only when the one before it finished and a second is
# left), and the removal's two git calls, each capped at `REMOVE_GIT_TIMEOUT`.
# Copying files and deleting the temp directory are local and are not budgeted.
REMOVE_GIT_TIMEOUT = 10
TEARDOWN_MARGIN = 3 * _proc_group.GRACE_SECONDS + 2 * REMOVE_GIT_TIMEOUT
MAX_TIMEOUT = HOST_BASH_LIMIT - TEARDOWN_MARGIN

# Every throwaway's temp directory starts with this, which is how a leftover from
# a run nobody could clean up is recognised in `git worktree list`.
THROWAWAY_PREFIX = "audit-red-"
# ...and the file in that directory naming the process that made it, which is
# what tells a stranded throwaway from one a sibling's run is still using.
OWNER_FILE = "owner.json"

# What the child's environment loses: these variables whole, and - by PATH, not
# by substring - every other value that IS a path under the shared root, or the
# entries of a path list that are. A variable that merely mentions the root in
# text, or names a sibling directory sharing its prefix, is kept.
SCRUBBED_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "PYTHONPATH", "CLAUDE_PROJECT_DIR")

# A task's declared file is a TEST file when `tests.add` names it or its path has
# the conventional test shape; everything else it declares is implementation and
# stays at HEAD. The split is printed with every run, because it decides what the
# red is a red OF.
_TEST_DIRS = ("tests", "test", "__tests__", "spec")
_TEST_NAME = re.compile(r"^(test_.+|.+_test\.[^.]+|.+\.(test|spec)\.[^.]+)$")

# --- the tally a verdict is read from ---
# `red` needs a COUNT and a NAME: at least one test collected, and at least one
# named case failing an ASSERTION. Both are read by `_runner_output`, the one
# reader of what a test runner printed, shared with `run-test-gate`; the names
# below ARE that module's objects, not copies of them.
house_case_id = _runner_output.house_case_id
_unittest_tally = _runner_output._unittest_tally
failing_cases = _runner_output.failing_cases
read_tally = _runner_output.read_tally

# With no tally, a traceback ending in one of these is a run that never reached an
# assertion; any other tally-less failure is `no-tally`, a crash nobody classified.
_COMPILE_ERROR = re.compile(r"^\s*(?:E\s+)?(SyntaxError|IndentationError|TabError|"
                            r"ImportError|ModuleNotFoundError|NameError|"
                            r"AttributeError)\b", re.M)
_ERROR_LINE = re.compile(r"^\s*(\w*(?:Error|Exception)\b.*)$", re.M)
# pytest prints a collection error's exception behind an `E   ` gutter.
_FINAL_ERROR = re.compile(r"^\s*(?:E\s+)?([A-Za-z_][\w.]*(?:Error|Exception)):\s?(.*)$",
                          re.M)

# The error classes a missing symbol produces. A syntax error never qualifies: it
# is the test's own text failing to parse, and it survives any fix.
INTRODUCES_CLASSES = ("ImportError", "ModuleNotFoundError", "AttributeError",
                      "NameError")
_SYMBOL_SHAPE = re.compile(r"^[A-Za-z_][\w.]*$")


def classify_run(code, text, cmd=None):
    """`(verdict, tally)` for one run: `green` / `red` / `collection-error` /
    `mixed-tally` / `no-tally`. Exit 0 is `green` whatever the output says."""
    tally = read_tally(text, cmd)
    if code == 0:
        return V_GREEN, tally
    if tally is None:
        return (V_COLLECT if _COMPILE_ERROR.search(text) else V_NO_TALLY), None
    if tally["runner"] is None:
        return V_MIXED, tally
    if tally["collected"] > 0 and tally["assertions"] > 0:
        return V_RED, tally
    return V_COLLECT, tally


def final_error(text):
    """`(class, message, line)` of the last exception line a run printed, or None."""
    hits = _FINAL_ERROR.findall(text)
    if not hits:
        return None
    cls, message = hits[-1]
    return cls.split(".")[-1], message.strip(), "%s: %s" % (cls, message.strip())


def qualifying_error(text, symbol):
    """The final error line when it is a missing-symbol error NAMING `symbol` whole
    - the runtime quotes the name it could not find - else None."""
    err = final_error(text)
    if err is None or err[0] not in INTRODUCES_CLASSES:
        return None
    quoted = ("'%s'" % (symbol,), '"%s"' % (symbol,))
    return err[2] if any(q in err[1] for q in quoted) else None


# --- which files the throwaway takes from where ---
def find_task(manifest, task_id):
    """`(task, problem)` - one task by id. Exactly one is None."""
    for _phase, task in _mio.iter_tasks(manifest):
        if str(task.get("id")) == str(task_id):
            return task, None
    return None, "no task %r in this manifest" % (task_id,)


def _is_test_path(rel, named):
    parts = rel.replace("\\", "/").split("/")
    return (rel in named or any(p in _TEST_DIRS for p in parts[:-1])
            or bool(_TEST_NAME.match(parts[-1])))


def split_scope(task):
    """`(implementation, tests)` - the task's declared files, in declared order."""
    files = [f for f in (task.get("files") or []) if isinstance(f, str)]
    adds = (task.get("tests") or {}).get("add") or []
    named = set(str(a).split(":", 1)[0].strip() for a in adds if isinstance(a, str))
    tests = [f for f in files if _is_test_path(f, named)]
    return [f for f in files if f not in tests], tests


def _under(value, roots):
    """Whether `value` is one of `roots` or a path beneath one - a separator
    boundary, so `/repo-other` is not under `/repo`."""
    if not value or not os.path.isabs(value):
        return False
    spellings = set((value, os.path.realpath(value)))
    return any(v == r or v.startswith(r.rstrip("/\\") + sep)
               for v in spellings for r in roots for sep in ("/", os.sep))


# An option string - NODE_OPTIONS, PYTEST_ADDOPTS - is not a path to rewrite, but
# a runner reads the paths inside it: split on whitespace, `=` and the path-list
# separator to find them.
_TOKEN_SPLIT = re.compile(r"[\s=%s]+" % (re.escape(os.pathsep),))


def child_env(root, environ=None):
    """`(env, dropped, naming)` - the environment without what reaches the shared
    tree, and the kept variables that still NAME a path under it.

    `SCRUBBED_ENV` goes whole; any other variable whose value IS a path under the
    root goes; a path list keeps its other entries and loses the ones under the
    root, so an in-repo `.venv/bin` leaves PATH without taking PATH with it.
    `dropped` names every variable and every list entry removed. A value that is
    not itself a path but carries one under the root - an option string such as
    `--require /repo/test/setup.js` - is kept and listed in `naming`, because a
    runner reads it as a path into the shared tree and the basis must say so."""
    source = os.environ if environ is None else environ
    roots = [r for r in set((root, os.path.realpath(root))) if r]
    env, dropped, naming = {}, [], []
    for key in sorted(source):
        value = source[key]
        if key in SCRUBBED_ENV:
            dropped.append(key)
            continue
        parts = value.split(os.pathsep) if os.pathsep in value else [value]
        gone = [p for p in parts if _under(p, roots)]
        if not gone:
            env[key] = value
            if any(_under(tok, roots) for tok in _TOKEN_SPLIT.split(value)):
                naming.append(key)
        elif len(parts) == 1 or len(gone) == len(parts):
            dropped.append(key)
        else:
            env[key] = os.pathsep.join(p for p in parts if p not in gone)
            dropped.extend("%s entry %s" % (key, p) for p in gone)
    return env, dropped, naming


def _git_env():
    """This process's environment without git's own redirections, so the helper's
    git reads the repository `-C` names and nothing an environment points at."""
    return dict((k, v) for k, v in os.environ.items() if not k.startswith("GIT_"))


def _git(root, args, timeout=120, strip=True):
    """`(code, text)` for one git call; the hooks path points nowhere, so no hook
    the repository carries runs on the throwaway's behalf. `strip=False` keeps
    the output as git wrote it, for a file's contents.

    `core.autocrlf` is pinned off because the throwaway is checked out by these
    calls, and a system or user config setting it - Git for Windows ships one
    that does, and `_git_env` drops the variable that would skip it - would
    rewrite HEAD's line endings on checkout: the run would then grade bytes HEAD
    does not hold, and `_head_text`, which reads the blob, would disagree with
    the file the run read. A `.gitattributes` the repository commits still
    applies; that conversion is HEAD's own. No call here reads the shared tree's
    status, so the pin changes nothing there."""
    try:
        out = subprocess.run(["git", "-C", root, "-c",
                              "core.hooksPath=%s" % os.devnull,
                              "-c", "core.autocrlf=false"] + list(args),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=timeout, env=_git_env())
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "%s" % (exc,)
    text = out.stdout.decode("utf-8", "replace")
    return out.returncode, text.strip() if strip else text


def _head_text(root, rel, timeout=120):
    """HEAD's bytes of `rel` as text, or None when HEAD has no such file."""
    code, text = _git(root, ["show", "HEAD:%s" % (rel,)], timeout=timeout,
                      strip=False)
    return text if code == 0 else None


def _wt_text(root, rel):
    try:
        with open(os.path.join(root, *rel.split("/")), "r", encoding="utf-8",
                  errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _names(text, word):
    """Whether `text` carries `word` as a whole name, not inside a longer one."""
    return bool(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(word), text or ""))


def introduced(root, implementation, symbol, deadline=None):
    """`(holds, basis)` - the STATIC half of whether this task introduces `symbol`:
    absent, as a whole name, from HEAD's copy of every declared implementation
    file (content and path, so a new module counts), and present in the working
    tree's copy of at least one. The half that decides is the second run, in
    `run_red`: with the working tree's implementation copied in, the error the
    first run ended on must be gone."""
    heads = dict((rel, _head_text(root, rel, timeout=max(1, _left(deadline))
                                  if deadline is not None else 120))
                 for rel in implementation)
    at_head = [rel for rel, text in heads.items()
               if text is not None and (_names(rel, symbol) or _names(text, symbol))]
    if at_head:
        return False, ("%r is not introduced by this task: HEAD already carries it "
                       "in %s" % (symbol, ", ".join(at_head)))
    in_wt = [rel for rel in implementation
             if (_names(rel, symbol) and _wt_text(root, rel) is not None)
             or _names(_wt_text(root, rel), symbol)]
    if not in_wt:
        return False, ("%r is not introduced by this task: no declared "
                       "implementation file in the working tree carries it" % (symbol,))
    return True, ("absent from HEAD's %s and present in the working tree's %s"
                  % (", ".join(implementation), ", ".join(in_wt)))


# --- which failing case is the task's own: the baseline is GREEN ---
# Whether a case is new cannot be read off the test file's source, and seven
# review rounds each found another way to read it off two runs' output while
# HEAD's own run was red - a label rebuilt, a case relabelled, a run that stopped
# quietly, a file the task's run rewrote. So the red is credited only against a
# GREEN baseline: HEAD's own test files, run with the same command on HEAD's code
# in an isolated clean throwaway, must pass. With that, every failure of the
# task's run comes from the task's change to the tests, and all of them are its
# own; the fix run then shows each one passes with the working tree's code.
NARROW = ("the command is already red (or unreadable) at HEAD - narrow it to the "
          "task's cases")
# What jest (`No tests found, ...`) and vitest (`No test files found, ...`) print
# when no test file matched - the sentence the design note's (3) records them
# printing, exit 1, for a command naming only a file that is not there.
_JS_NO_TESTS = re.compile(r"^[ \t]*No test(?:s| files) found, exiting with code \d+",
                          re.M)


def _js_none_found(head, tally):
    """Whether HEAD's run is jest's or vitest's no-test-file answer: exit 1, the
    runner's own sentence, no tally counting a case or a failure - and only for
    a run that left a new test file absent, which is what makes "nothing
    matched" the expected answer rather than a misnamed path."""
    if head["code"] != 1 or not head.get("absent"):
        return False
    if not _JS_NO_TESTS.search(_runner_output.plain_text(head["text"])):
        return False
    return tally is None or (tally["runner"] is not None and not tally["collected"]
                             and not tally["failed"])


def baseline_problem(head, cmd):
    """Why HEAD's own run is not a GREEN baseline, or None when it is.

    `head` is `{"code", "text", "problem", "absent"}` of HEAD's own test files
    run on HEAD's code, FIRST, in a fresh throwaway and an isolated
    environment, with every declared test file new at HEAD laid over as an
    EMPTY file - or, for a jest or vitest test file (`_is_js_test_path`), left
    ABSENT and named in `absent`, since both runners fail an empty suite - so
    the same command reaches what the task's run reaches, however it is
    spelled, minus the new files' content. Green is exit 0 with no failure
    counted, or the runner's own no-tests-ran exit 5 - which a command naming
    only new files legitimately gives, and pytest gives when `-k` deselects
    every case - read as ONE runner's tally counting no case run and no
    failure; or, with a file left absent, jest's or vitest's no-test-file
    sentence (`_js_none_found`), their counterpart of that exit 5. The text
    alone is not read: a red run followed by an empty one prints "NO TESTS
    RAN" too, and a mixed tally counts nothing because it reads no cases.

    The stubs and the absent files remove the new files' CONTENT, and with it
    everything that content reaches - a HEAD case a new file imports, inherits
    or loads is not run here. `credit_problem` is what keeps such a case from
    being credited."""
    if head is None:
        return "HEAD's own run was not made - %s" % (NARROW,)
    if head.get("problem"):
        return "HEAD's own run could not be made (%s) - %s" % (head["problem"], NARROW)
    tally = read_tally(head["text"], cmd)
    if head["code"] == 5 and tally is not None and tally["runner"] is not None \
            and not tally["collected"] and not tally["failed"]:
        return None
    if _js_none_found(head, tally):
        return None
    if head["code"] != 0 or (tally is not None and (tally["runner"] is None
                                                    or tally["failed"])):
        return ("HEAD's own tests on HEAD's code are not green (%s) - %s"
                % (_decisive_line(head["text"], tally), NARROW))
    return None


def fix_problem(fix, cmd, task_tally):
    """Why the fix run does not show every failing case passing with the
    working tree's code, or None. The fix run must be green and must have run
    at least as many cases as the task's run, so a case that failed cannot
    have gone missing instead of passing."""
    if fix is None:
        return "the fix run was not made"
    if fix.get("problem"):
        return "the fix run could not be made: %s" % (fix["problem"],)
    tally = read_tally(fix["text"], cmd)
    if fix["code"] != 0 or tally is None or tally["runner"] is None or tally["failed"]:
        return ("with the working tree's implementation the task's tests do not all "
                "pass (%s), so the red is not one the fix turns green"
                % (_decisive_line(fix["text"], tally),))
    if tally["collected"] < task_tally["collected"]:
        return ("the fix run collected %d case(s) and the task's run %d, so a "
                "failing case may be missing rather than passing"
                % (tally["collected"], task_tally["collected"]))
    return None


def _is_named(failure, name):
    """Whether `--case NAME` names this failing case: its id, or its label as
    printed, with or without the detail a house FAIL line appends after a
    ` (` - read in place, so a long detail costs no prefix copies."""
    label = failure.get("label") or ""
    return (name == failure.get("id") or name == label
            or (label.startswith(name) and label.startswith(" (", len(name))))


_RUNNER_MODULES = ("unittest", "pytest")


def _house_script(cmd):
    """The script a `python <file>.py ...` or `python -m <module>` command runs,
    as the path it was spelled with, or None - for `-c`, and for `-m` naming a
    runner rather than a test module."""
    args = [str(a) for a in (cmd or ())]
    if args and args[0].endswith(".py"):
        return args[0]
    if not args or not os.path.basename(args[0]).startswith("python"):
        return None
    i = 1
    while i < len(args):
        if args[i] in ("-X", "-W"):
            i += 2
            continue
        if args[i] == "-c":
            return None
        if args[i] == "-m":
            module = args[i + 1] if i + 1 < len(args) else ""
            if not module or module.split(".")[0] in _RUNNER_MODULES:
                return None
            return module.replace(".", "/") + ".py"
        if not args[i].startswith("-"):
            return args[i]
        i += 1
    return None


def _as_rel(path, roots):
    """`path` as a repository-relative posix path: `./` and `..` folded, an
    absolute path made relative to the first of `roots` it lies under; None
    for an absolute path under none of them."""
    if not path:
        return None
    if os.path.isabs(path):
        for root in roots:
            rel = os.path.relpath(path, root)
            if rel != os.pardir and not rel.startswith(os.pardir + os.sep):
                path = rel
                break
        else:
            return None
    return posixpath.normpath(path.replace(os.sep, "/"))


def _one_declared(path, tests, others=(), real_path=False):
    """The ONE declared test file `path` names, or None.

    Equal to it, or ending with `/` + it, since a runner prints paths and
    modules relative to its own top directory (`unittest discover -s tests`
    prints `test_new`). A trailing match is refused when two declared files
    share the tail. And a match is refused when `others` - every other file in
    HEAD's tree and in the throwaway - holds one equal to `path` or ending with
    it: the runner may have loaded that one, and the name cannot say which.
    That holds for an EXACT match too unless `real_path` says `path` is a path
    the runner resolved against its working directory (a pytest node id);
    a unittest module is resolved through sys.path, so `test_old` names
    whichever `test_old.py` came first on it. `others` None means they could
    not be listed, and then only a real path's exact match is read."""
    if not path:
        return None
    tail = "/" + path
    if real_path and path in tests:
        return path
    hits = [t for t in tests if t == path or t.endswith(tail)]
    if len(hits) != 1 or others is None:
        return None
    if any(o == path or o.endswith(tail) for o in others if o != hits[0]):
        return None
    return hits[0]


def case_site(failure, runner, tests, cmd, roots=(), others=()):
    """`(rel, classes, name)` - the declared test file the runner locates this
    failure in, the class chain it names there and the case's name - or None
    when the runner locates it in no declared test file. A pytest node id
    gives `path::Class::name`; unittest -v gives `mod.Class` (nested classes
    qualified: the longest prefix naming a declared file is the module), or
    `__main__` when the command runs a declared file as a script; a house run
    is located only as the one declared script its command runs, with
    `classes` None, because its FAIL lines carry no location at all. A jest or
    vitest case is located by the suite path its `FAIL` header or line prints,
    read as a real path, so an exact match is the file and a tail matches only
    when exactly one declared file ends with it and no other file does (a config
    that moved the root prints a path relative to a package); `classes` is its
    describe titles and `name` the test's own title. A suite that never ran a
    test has no chain and is located nowhere."""
    if runner in JS_RUNNERS:
        chain = list(failure.get("chain") or [])
        rel = _one_declared(_as_rel(failure.get("suite"), roots), tests, others,
                            real_path=True)
        return (rel, chain[:-1], chain[-1]) if rel and chain else None
    name = (failure.get("id") or "").split("[")[0]
    script = _as_rel(_house_script(cmd), roots)
    if runner == "pytest":
        parts = (failure.get("label") or "").split("::")
        rel = _one_declared(_as_rel(parts[0], roots), tests, others, real_path=True)
        return (rel, parts[1:-1], name) if rel and len(parts) > 1 else None
    if runner == "unittest":
        qual = failure.get("qual") or (
            (failure.get("module") or "").split(".") if failure.get("module") else [])
        if not failure.get("qual") and failure.get("cls"):
            qual = qual + [failure["cls"]]
        if qual[:1] == ["__main__"]:
            return (script, qual[1:], name) if script in tests else None
        for cut_at in range(len(qual), 0, -1):
            rel = _one_declared("/".join(qual[:cut_at]) + ".py", tests, others)
            if rel:
                return rel, qual[cut_at:], name
        return None
    if runner == "house" and script in tests:
        return script, None, name
    return None


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _target_names(target):
    """The names an assignment target binds: a Name, and the Names inside a
    Tuple, List or Starred - never a Name under an Attribute or a Subscript,
    which binds nothing (`New.maxDiff = None` leaves `New` bound as it was)."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _target_names(elt)]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


# The statements whose nested block is a body of its own: a binding in the
# block is not read (a named limit), only what their header binds.
_COMPOUND = ("For", "AsyncFor", "While", "If", "With", "AsyncWith", "Try",
             "TryStar", "Match")


def _header(stmt):
    """The expressions of `stmt` evaluated in the body `stmt` stands in: the
    whole of a simple statement; the header of a compound one; a def's or a
    class's decorators, defaults, bases and keywords."""
    kind = type(stmt).__name__
    if isinstance(stmt, _DEFS):
        args = stmt.args
        return list(stmt.decorator_list) + list(args.defaults) + [
            d for d in args.kw_defaults if d is not None]
    if isinstance(stmt, ast.ClassDef):
        return list(stmt.decorator_list) + list(stmt.bases) + [
            k.value for k in stmt.keywords]
    if kind in ("For", "AsyncFor"):
        return [stmt.iter]
    if kind in ("While", "If"):
        return [stmt.test]
    if kind in ("With", "AsyncWith"):
        return [item.context_expr for item in stmt.items]
    if kind == "Match":
        return [stmt.subject]
    if kind in _COMPOUND:
        return []
    return [stmt]


def _walrus_names(nodes):
    """The names a walrus in `nodes` binds in their own scope: a lambda is a
    scope of its own and is not entered; a comprehension is, since a walrus
    in it binds in the enclosing scope."""
    out, stack = [], list(nodes)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.NamedExpr):
            out.extend(_target_names(node.target))
        stack.extend(ast.iter_child_nodes(node))
    return out


def _pattern_names(pattern):
    """The capture names of a match pattern (read by node name, which keeps
    this file free of 3.10-only attributes)."""
    out = []
    for node in ast.walk(pattern):
        kind = type(node).__name__
        if kind in ("MatchAs", "MatchStar") and getattr(node, "name", None):
            out.append(node.name)
        elif kind == "MatchMapping" and getattr(node, "rest", None):
            out.append(node.rest)
    return out


def _bound_names(stmt):
    """Every name the statement `stmt` binds in the body it stands in."""
    kind = type(stmt).__name__
    names = []
    if isinstance(stmt, _DEFS + (ast.ClassDef,)):
        names.append(stmt.name)
    elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
        names.extend("*" if a.name == "*" else (a.asname or a.name.split(".")[0])
                     for a in stmt.names)
    elif isinstance(stmt, (ast.Assign, ast.Delete)):
        names.extend(n for t in stmt.targets for n in _target_names(t))
    elif isinstance(stmt, ast.AugAssign) or (isinstance(stmt, ast.AnnAssign)
                                             and stmt.value is not None):
        names.extend(_target_names(stmt.target))
    elif kind in ("For", "AsyncFor"):
        names.extend(_target_names(stmt.target))
    elif kind in ("With", "AsyncWith"):
        names.extend(n for item in stmt.items if item.optional_vars is not None
                     for n in _target_names(item.optional_vars))
    elif kind == "Match":
        names.extend(n for case in stmt.cases for n in _pattern_names(case.pattern))
    return names + _walrus_names(_header(stmt))


def _binds(stmt, name):
    """Whether the statement `stmt`, standing in a body, binds `name` there:
    a def or a class of that name; an import binding it, or a `*` import,
    which may; a Name target of an assignment, an annotated assignment with a
    value, an augmented assignment or a `del`, read through tuples, lists and
    starred but never under an attribute or a subscript; a `for` target; a
    `with ... as`; a match capture; or a walrus in the statement outside a
    lambda. A binding inside a compound statement's own block is not read."""
    names = _bound_names(stmt)
    return name in names or "*" in names


def _last_binding(body, name):
    """The LAST statement of `body` that binds `name`, or None."""
    found = [stmt for stmt in body if _binds(stmt, name)]
    return found[-1] if found else None


def _parse(text):
    """The module ast of `text`, or None; a warning the parse raises (an
    invalid escape in a file this reads) is not printed."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return ast.parse(text or "")
        except (SyntaxError, ValueError):
            return None


def _definition(text, classes, name):
    """The ast node of the def `name` in the class chain `classes` of `text`
    (module level when the chain is empty), or None.

    Each name is read as the body's LAST top-level binding of it: a class of
    the chain must be last bound by its `class` statement, and the case by its
    `def`. So any binding `_binds` reads after the def - in the class body, or
    of the class name at module level - means it is not the def that runs; so
    does a later statement at any level of the chain that `_replaces` the case
    on its class (an assignment to `<chain>.<case>`, or a `setattr` naming it
    literally), while any other attribute or subscript assignment binds
    nothing; and a def in a string, in another class or merely inherited is
    not it either. A binding inside the block of a compound statement is not
    read, and neither is a decorator that returns another function or a
    `setattr` whose name is computed."""
    tree = _parse(text)
    if tree is None:
        return None
    body, trail = tree.body, []
    for cls in classes:
        node = _last_binding(body, cls)
        if not isinstance(node, ast.ClassDef):
            return None
        trail.append((body, node))
        body = node.body
    node = _last_binding(body, name)
    if not isinstance(node, _DEFS):
        return None
    trail.append((body, node))
    for depth, (level, anchor) in enumerate(trail):
        path = list(classes[depth:]) + [name]
        later = level[[id(stmt) for stmt in level].index(id(anchor)) + 1:]
        if any(_replaces(stmt, path) for stmt in later):
            return None
    return node


def _dotted(node):
    """The dotted path an expression spells - `New.test_x` is
    `["New", "test_x"]` - or None for anything but names and attributes."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return head + [node.attr] if head is not None else None
    return None


def _attribute_targets(target):
    """The Attribute targets of an assignment target, read through tuples,
    lists and starred."""
    if isinstance(target, ast.Attribute):
        return [target]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [a for elt in target.elts for a in _attribute_targets(elt)]
    if isinstance(target, ast.Starred):
        return _attribute_targets(target.value)
    return []


def _replaces(stmt, path):
    """Whether `stmt` replaces the case at `path` - the class chain as seen
    from the body `stmt` stands in, then the case's name - on its class: an
    assignment of any kind to that exact attribute path, or a
    `setattr(<chain>, '<name>', ...)` with that literal name. Another
    attribute (`New.maxDiff = None`), another object or a longer path does
    not, and a name setattr computes is not read."""
    if len(path) < 2:
        return False
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
    elif isinstance(stmt, (ast.AugAssign, ast.AnnAssign)):
        targets = [stmt.target]
    else:
        targets = []
    if any(_dotted(a) == path for t in targets for a in _attribute_targets(t)):
        return True
    stack = list(_header(stmt))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Call) and _dotted(node.func) == ["setattr"] \
                and len(node.args) >= 2 and _dotted(node.args[0]) == path[:-1] \
                and isinstance(node.args[1], ast.Constant) \
                and node.args[1].value == path[-1]:
            return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def test_definitions(texts):
    """`{(classes, name, ast dump): rel}` of every def in each file of `texts`
    (`{rel: text}`), at module level and in every class chain: the cases HEAD
    already has, keyed so a move or a copy of one is found wherever it lands.
    A file that does not parse contributes nothing."""
    out = {}
    for rel in sorted(texts):
        tree = _parse(texts[rel])
        stack = [((), tree.body if tree is not None else [])]
        while stack:
            chain, body = stack.pop()
            for stmt in body:
                if isinstance(stmt, _DEFS):
                    out.setdefault((chain, stmt.name, ast.dump(stmt)), rel)
                elif isinstance(stmt, ast.ClassDef):
                    stack.append((chain + (stmt.name,), stmt.body))
    return out


# --- which jest or vitest case a JS/TS test file defines ---
# `ast` reads only Python, so a jest or vitest case is read off its source by a
# small tokenizer: a regex cannot tell which `test(` sits inside which
# `describe(` callback once a string, a template literal, a comment or a regex
# literal holds a bracket. It knows those token kinds, so the brackets it counts
# are the code's. What it reads is each `describe` / `test` / `it` call (any
# `.only`, `.skip` ... between the name and the paren), its title chain, and its
# argument tokens - comments and whitespace dropped - as the body two copies are
# compared by. A file it cannot read with every bracket balanced and every
# literal closed is None, never an empty file: a misread HEAD copy must not look
# like no HEAD copy at all. JSX text and a regex literal right after `)` are
# blind spots; a misreading of either surfaces as an unbalanced file (refused)
# or as the same misreading of both copies (compared alike).
JS_RUNNERS = ("jest", "vitest")
_JS_TEST_FILE = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")
_JS_SOURCE = re.compile(r"\.[cm]?[jt]sx?$")
_JS_CALLS = ("describe", "test", "it")
_JS_IDENT = re.compile(r"[A-Za-z_$\u0080-\uffff][\w$\u0080-\uffff]*")
_JS_NUMBER = re.compile(r"\.?\d[\w.]*")
# After one of these a `/` starts a regex literal; after a name, a number, `)`
# or `]` it divides.
_JS_REGEX_AFTER = ("return", "typeof", "instanceof", "in", "of", "new", "delete",
                   "void", "throw", "case", "do", "else", "yield", "await")
_JS_OPEN = {"(": ")", "[": "]", "{": "}"}
_JS_ESCAPE = re.compile(r"\\(u\{[0-9A-Fa-f]+\}|u[0-9A-Fa-f]{4}|x[0-9A-Fa-f]{2}|"
                        r"\r\n|[\s\S])")
_JS_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
                      "v": "\v", "0": "\0", "\n": "", "\r\n": "", "\r": ""}
# The placeholders jest and vitest fill a `.each` title with.
_JS_EACH_FORMAT = re.compile(r"%[psdifjoO#$%]|\$[\w.]+")


def _js_unescape(body):
    """A string literal's value, its escapes decoded."""
    def one(hit):
        esc = hit.group(1)
        if esc[0] == "u" and len(esc) > 1:
            return chr(int(esc[1:].strip("{}"), 16))
        if esc[0] == "x" and len(esc) == 3:
            return chr(int(esc[1:], 16))
        return _JS_SIMPLE_ESCAPES.get(esc, esc)
    return _JS_ESCAPE.sub(one, body)


def _js_quoted_end(src, i):
    """The index past the string literal opening at `src[i]`; ValueError when
    it is not closed on its line."""
    quote, j = src[i], i + 1
    while j < len(src):
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == quote:
            return j + 1
        if ch == "\n":
            break
        j += 1
    raise ValueError("an unterminated string at offset %d" % (i,))


def _js_template_end(src, i):
    """`(end, chunks)` - the index past the template literal opening at
    `src[i]`, and its literal text decoded, split at each `${}` substitution
    (one chunk when it holds none)."""
    j, start, chunks = i + 1, i + 1, []
    while j < len(src):
        ch = src[j]
        if ch == "\\":
            j += 2
        elif ch == "`":
            return j + 1, chunks + [_js_unescape(src[start:j])]
        elif src.startswith("${", j):
            chunks.append(_js_unescape(src[start:j]))
            _tokens, j = _js_scan(src, j + 2, inside=True)
            start = j
        else:
            j += 1
    raise ValueError("an unterminated template literal at offset %d" % (i,))


def _js_regex_end(src, i):
    """The index past the regex literal opening at `src[i]`, flags included."""
    j, in_class = i + 1, False
    while j < len(src) and src[j] != "\n":
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            flags = _JS_IDENT.match(src, j + 1)
            return flags.end() if flags else j + 1
        j += 1
    raise ValueError("an unterminated regex literal at offset %d" % (i,))


def _js_regex_may_start(tokens):
    if not tokens:
        return True
    kind, raw = tokens[-1][0], tokens[-1][1]
    if kind == "id":
        return raw in _JS_REGEX_AFTER
    return kind == "p" and raw not in (")", "]")


def _js_scan(src, i=0, inside=False):
    """`(tokens, end)` - `[(kind, raw, value)]` from `src[i]` on, kinds `id`,
    `num`, `str` (a quoted string or a template with no substitution, `value`
    its decoded text), `tpl` (a template with one, `value` its literal text
    split at each substitution), `re` and `p` (one
    punctuation character). `inside` scans a `${}` substitution and stops past
    the `}` that closes it. ValueError on a literal or comment left open."""
    tokens, depth, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
        elif src.startswith("//", i):
            nl = src.find("\n", i)
            i = n if nl < 0 else nl
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            if end < 0:
                raise ValueError("an unterminated comment at offset %d" % (i,))
            i = end + 2
        elif ch in "'\"":
            end = _js_quoted_end(src, i)
            tokens.append(("str", src[i:end], _js_unescape(src[i + 1:end - 1])))
            i = end
        elif ch == "`":
            end, chunks = _js_template_end(src, i)
            tokens.append(("tpl", src[i:end], chunks) if len(chunks) > 1
                          else ("str", src[i:end], chunks[0]))
            i = end
        elif ch == "/" and _js_regex_may_start(tokens):
            end = _js_regex_end(src, i)
            tokens.append(("re", src[i:end], None))
            i = end
        else:
            word = _JS_IDENT.match(src, i) or _JS_NUMBER.match(src, i)
            if word:
                kind = "num" if word.group(0)[0] in ".0123456789" else "id"
                tokens.append((kind, word.group(0), None))
                i = word.end()
                continue
            if inside and ch == "}" and depth == 0:
                return tokens, i + 1
            depth += {"{": 1, "}": -1}.get(ch, 0)
            tokens.append(("p", ch, None))
            i += 1
    if inside:
        raise ValueError("an unterminated template substitution")
    return tokens, i


def _js_pairs(tokens):
    """`{open index: close index}` of every bracket, or None when they do not
    balance."""
    pairs, stack = {}, []
    for k, (kind, raw, _v) in enumerate(tokens):
        if kind != "p":
            continue
        if raw in _JS_OPEN:
            stack.append(k)
        elif raw in (")", "]", "}"):
            if not stack or _JS_OPEN[tokens[stack[-1]][1]] != raw:
                return None
            pairs[stack.pop()] = k
    return pairs if not stack else None


def _js_title_token(tokens, open_at, close_at):
    """The token a call's first argument is when it is a lone `str` or `tpl`
    literal, else None."""
    first, after = open_at + 1, open_at + 2
    if first < close_at and tokens[first][0] in ("str", "tpl") \
            and tokens[after][1] in (",", ")") and tokens[after][0] == "p":
        return tokens[first]
    return None


def _js_title(tokens, open_at, close_at):
    """The literal title a call's first argument spells, or None when the
    title is built at run time."""
    token = _js_title_token(tokens, open_at, close_at)
    return token[2] if token is not None and token[0] == "str" else None


def _js_title_pattern(tokens, open_at, close_at, each):
    """The regex a title built at run time matches, or None when nothing of
    it is literal: a template's literal parts with anything between them, and
    a `.each` title format with anything in place of each placeholder."""
    token = _js_title_token(tokens, open_at, close_at)
    if token is None:
        return None
    parts = token[2] if token[0] == "tpl" else [token[2]]
    if each:
        parts = [p for part in parts for p in _JS_EACH_FORMAT.split(part)]
    return "^" + "[\\s\\S]*".join(re.escape(p) for p in parts) + "$"


def js_test_cases(text):
    """`{"tests": [(chain, body)], "dynamic": [chain]}` of a JS/TS test file,
    or None when it cannot be read with every literal closed and every bracket
    balanced. `chain` is the tuple of describe titles and the test's own;
    `body` the tuple of the test call's argument tokens. A `dynamic` chain is
    one some element of which is built at run time (`.each`, a template with a
    substitution, a variable): that element is `("~", pattern)`, the pattern
    the regex `_js_title_pattern` reads off a template or a `.each` format,
    and None for anything else."""
    try:
        tokens, _end = _js_scan(text or "")
    except (ValueError, IndexError):
        return None
    pairs = _js_pairs(tokens)
    if pairs is None:
        return None
    tests, dynamic, scopes, k = [], [], [], 0
    while k < len(tokens):
        while scopes and scopes[-1][0] < k:
            scopes.pop()
        kind, raw, _v = tokens[k]
        if kind != "id" or raw not in _JS_CALLS or (
                k and tokens[k - 1][0] == "p" and tokens[k - 1][1] == "."):
            k += 1
            continue
        j, each = k + 1, False
        while j + 1 < len(tokens) and tokens[j][1] == "." and tokens[j + 1][0] == "id":
            each = each or tokens[j + 1][1] == "each"
            j += 2
        if j >= len(tokens) or tokens[j][1] != "(" or tokens[j][0] != "p":
            k += 1
            continue
        open_at = j
        if each:
            table_close = pairs[j]
            if table_close + 1 >= len(tokens) or tokens[table_close + 1][1] != "(":
                k = j + 1
                continue
            open_at = table_close + 1
        close_at = pairs[open_at]
        title = None if each else _js_title(tokens, open_at, close_at)
        element = title if title is not None else (
            "~", _js_title_pattern(tokens, open_at, close_at, each))
        parent = scopes[-1][1] if scopes else ()
        chain = parent + (element,)
        if raw == "describe":
            scopes.append((close_at, chain))
        elif any(not isinstance(e, str) for e in chain):
            dynamic.append(chain)
        else:
            tests.append((chain, tuple(t[1] for t in tokens[open_at + 1:close_at])))
        k = open_at + 1
    return {"tests": tests, "dynamic": dynamic}


def _js_chain_matches(pattern_chain, chain):
    """Whether a `dynamic` chain could be filled in as `chain`."""
    if len(pattern_chain) != len(chain):
        return False
    for element, title in zip(pattern_chain, chain):
        if isinstance(element, str):
            if element != title:
                return False
        elif element[1] is not None and not re.match(element[1], title):
            return False
    return True


def js_test_definitions(texts):
    """`{"defs": {(chain, body): rel}, "unread": {rel: text}}` of each file of
    `texts` (`{rel: text}`): the jest and vitest cases HEAD already has, keyed so
    a copy of one is found wherever it lands, and the files `js_test_cases`
    could not read, kept whole so a case they might hold is refused."""
    defs, unread = {}, {}
    for rel in sorted(texts):
        cases = js_test_cases(texts[rel])
        if cases is None:
            unread[rel] = texts[rel]
            continue
        for chain, body in cases["tests"]:
            defs.setdefault((chain, body), rel)
    return {"defs": defs, "unread": unread}


# A title holding one of these may be spelled in source by an escape, so a file
# the tokenizer could not read is not searched for it - it is assumed to hold it.
_JS_TITLE_ESCAPABLE = re.compile("[\"'`\\\\\u0080-\U0010ffff]")


def _js_unread_holding(unread, title):
    """The unreadable HEAD test files that may hold a test titled `title`."""
    if _JS_TITLE_ESCAPABLE.search(title):
        return sorted(unread)
    return sorted(rel for rel, text in unread.items() if title in (text or ""))


def _js_credit_problem(site, scope):
    """Why a located jest or vitest case is NOT the task's own, or None.

    The declared file's working-tree copy must define a test with exactly that
    title chain, and no test of it built at run time may fill in the same chain
    - otherwise which of them failed cannot be told. Then no test file in HEAD's
    tree may hold a test with that chain whose body is the same token for token:
    that is HEAD's case, unchanged, wherever it now sits. A HEAD test file the
    tokenizer cannot read refuses every case whose title it may hold."""
    rel, describes, name = site
    chain = tuple(describes) + (name,)
    where = "%s (%s)" % (rel, " > ".join(chain))
    cases = js_test_cases(scope["wt"].get(rel))
    if cases is None:
        return ("%s could not be read as JS/TS source with every literal closed and "
                "every bracket balanced, so which tests it defines cannot be told"
                % (rel,))
    built = [c for c in cases["dynamic"] if _js_chain_matches(c, chain)]
    bodies = [body for c, body in cases["tests"] if c == chain]
    if built:
        return ("%s builds a test title at run time (`.each`, a template or a "
                "variable) that may be this one, so which test failed cannot be "
                "told" % (where,))
    if not bodies:
        return "%s defines no test with that title chain" % (where,)
    head = scope.get("head_js")
    if head is None:
        return "HEAD's test files could not be read to tell an edit from HEAD's case"
    same = [head["defs"][(chain, b)] for b in bodies if (chain, b) in head["defs"]]
    if same:
        return ("its test body in %s is unchanged from HEAD's %s (the same title "
                "chain and tokens) - HEAD's case" % (where, same[0]))
    held = _js_unread_holding(head["unread"], name)
    if held:
        return ("HEAD's %s could not be read as JS/TS source and may hold this "
                "case, so it is not credited" % (", ".join(held),))
    return None


def credit_problem(failure, runner, scope):
    """Why this failing case is NOT the task's own, or None when it is.

    `scope` is `{"tests", "cmd", "roots", "wt", "head_defs", "head_modules",
    "others"}`: the
    declared test files, the command, the roots a spelled path is relative
    to, each declared test file's working-tree text, `test_definitions` and
    the `module_key`s of every test file in HEAD's tree (None when it could not
    be read), and every
    other file in HEAD's tree and the throwaway. The case must be located in
    ONE declared test file (`case_site`); under pytest and unittest that
    file's named class must define it (`_definition`); and no test file
    anywhere in HEAD's tree may hold an ast-identical def under the same class
    chain and name - because the baseline stubs only NEW files, so a HEAD case
    a new file imports, a moved file carries or a copy repeats is reached by
    nothing else. Layout and comments do not count as a change; any edit to
    the def's ast does. A house run carries no definitions, so the one script
    it runs is compared whole: a script identical to one of HEAD's test files
    is HEAD's suite, moved or copied. A jest or vitest case is judged by
    `_js_credit_problem`, its title chain and test body standing in for the
    class chain and the def."""
    site = case_site(failure, runner, scope["tests"], scope["cmd"],
                     scope.get("roots", ()), scope.get("others", ()))
    if site is None:
        return "the runner locates it in no declared test file"
    if runner in JS_RUNNERS:
        return _js_credit_problem(site, scope)
    rel, classes, name = site
    if classes is None:
        modules = scope.get("head_modules")
        if modules is None:
            return "HEAD's test files could not be read to tell a new suite from HEAD's"
        same = modules.get(module_key(scope["wt"].get(rel)))
        if same is not None:
            return ("%s is identical to HEAD's %s (the same module ast) - a house run "
                    "of it prints HEAD's cases" % (rel, same))
        return None
    where = "%s%s" % (rel, "".join(" class " + c for c in classes))
    node = _definition(scope["wt"].get(rel), classes, name)
    if node is None:
        return "%s does not define it in %s" % (where, "that class" if classes
                                                 else "the module")
    defs = scope.get("head_defs")
    if defs is None:
        return "HEAD's test files could not be read to tell an edit from HEAD's case"
    same = defs.get((tuple(classes), name, ast.dump(node)))
    if same is not None:
        return ("its definition in %s is unchanged from HEAD's %s (the same class "
                "chain, name and ast) - HEAD's case" % (where, same))
    return None


def _cat_blobs(root, rels, deadline):
    """`(texts, problem)` - HEAD's text of each of `rels`, read by ONE
    `git cat-file --batch` under the deadline."""
    rels = [r for r in rels if "\n" not in r]
    if not rels:
        return {}, None
    try:
        out = subprocess.run(
            ["git", "-C", root, "-c", "core.hooksPath=%s" % os.devnull, "cat-file",
             "--batch"], input="".join("HEAD:%s\n" % r for r in rels).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=max(1, _left(deadline)), env=_git_env())
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "git could not read HEAD's test files: %s" % (exc,)
    data, at, texts = out.stdout, 0, {}
    for rel in rels:
        end = data.find(b"\n", at)
        if end < 0:
            return None, "git cat-file stopped before %s" % (rel,)
        head = data[at:end].decode("utf-8", "replace").split()
        at = end + 1
        if len(head) == 3 and head[1] == "blob" and head[2].isdigit():
            size = int(head[2])
            texts[rel] = data[at:at + size].decode("utf-8", "replace")
            at += size + 1
        elif not head or head[-1] != "missing":
            return None, "git cat-file answered %r for %s" % (" ".join(head), rel)
    return texts, None


def module_key(text):
    """What makes two test files the same file: the ast of the module, so
    layout and comments do not count - or, for one that does not parse, its
    text."""
    tree = _parse(text)
    return ast.dump(tree) if tree is not None else "text:" + (text or "")


def _is_js_test_path(rel, named):
    """A jest or vitest test file: a `.test.`/`.spec.` JS/TS name, or a JS/TS
    file under `__tests__` or among the declared `named`."""
    parts = rel.split("/")
    return bool(_JS_TEST_FILE.search(rel)) or (bool(_JS_SOURCE.search(rel)) and (
        rel in named or "__tests__" in parts[:-1]))


def head_tree(root, named, deadline):
    """`(files, defs, modules, js)` - every path in HEAD's tree;
    `test_definitions` of the `.py` test files among them (`_is_test_path`,
    the declared `named` counting as tests); `{module_key: rel}` of the same
    files, for a house run, whose cases carry no definition to compare; and
    `js_test_definitions` of the jest and vitest test files
    (`_is_js_test_path`). Any is None when git could not answer under the
    deadline, which the credit reads as a refusal, never as "nothing"."""
    code, text = _git(root, ["ls-tree", "-r", "-z", "--name-only", "HEAD"],
                      timeout=max(1, _left(deadline)), strip=False)
    if code != 0:
        return None, None, None, None
    files = [p for p in text.split("\0") if p]
    tests = [p for p in files if p.endswith(".py") and _is_test_path(p, named)]
    js_tests = [p for p in files if _is_js_test_path(p, named)]
    texts, problem = _cat_blobs(root, tests + js_tests, deadline)
    if problem is not None:
        return files, None, None, None
    modules = {}
    for rel in sorted(tests):
        if rel in texts:
            modules.setdefault(module_key(texts[rel]), rel)
    py_texts = dict((rel, texts[rel]) for rel in tests if rel in texts)
    js_texts = dict((rel, texts[rel]) for rel in js_tests if rel in texts)
    return files, test_definitions(py_texts), modules, js_test_definitions(js_texts)


def _throwaway_files(path):
    """Every file in the throwaway, relative and `/`-separated, `.git` left out."""
    out = []
    for top, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if d != ".git"]
        rel = os.path.relpath(top, path).replace(os.sep, "/")
        out.extend(n if rel == "." else rel + "/" + n for n in names)
    return out


def _test_texts(root, tests):
    """`{rel: text}` of each declared test file in the working tree; "" for
    one that is not there or cannot be read."""
    out = {}
    for rel in tests:
        try:
            with open(os.path.join(root, *rel.split("/")), encoding="utf-8",
                      errors="replace") as fh:
                out[rel] = fh.read()
        except OSError:
            out[rel] = ""
    return out


def own_failures(failing, cases, runner=None, scope=None):
    """`(own, refused)` - the failing cases that failed an assertion and that
    `credit_problem` credits to the task, narrowed to those `--case` names;
    and the `--case` names that name none of them. Without a `runner` the
    credit is not asked."""
    asserting = [f for f in failing if f["assertion"] and (f["id"] or f["label"])
                 and (runner is None or credit_problem(f, runner, scope) is None)]
    refused = [c for c in cases if not any(_is_named(f, c) for f in asserting)]
    if cases:
        asserting = [f for f in asserting if any(_is_named(f, c) for c in cases)]
    return asserting, refused


def _names_shared_tree(cmd, root, project):
    """The arguments that reach into the shared tree - by any spelling of its
    root, or as a path that resolves under it."""
    spellings = set(p for p in (root, os.path.realpath(root), project,
                                os.path.realpath(project)) if p)
    real = os.path.realpath(root) + os.sep
    return [a for a in cmd
            if any(s in a for s in spellings)
            or (os.path.isabs(a) and os.path.realpath(a).startswith(real))]


# --- dependencies: the ignored directories linked into the throwaway ---
# The throwaway holds tracked files only, so a suite importing from
# `node_modules` or run from an in-repo `.venv` cannot start there. These are
# linked in from `--deps-from` ENTRY BY ENTRY into a real directory, never as one
# link to the whole directory: a new entry a runner creates beside them lands in
# the throwaway, and the cache entries below are not linked at all, so their
# writes stay there too. A write INTO a linked entry still lands in the source;
# the basis says so rather than claiming it is watched.
DEP_DIRS = ("node_modules", ".venv")
DEP_CACHES = (".cache", ".vite", ".vite-temp")
# A quoted absolute path in an editable install's finder module.
_QUOTED = re.compile(r"""["']([^"'\n]+)["']""")


def dep_rels(listing):
    """The dependency directories in git's NUL-separated ignored listing, the
    outermost only: one nested inside another is reached through its parent's
    link already."""
    rels = sorted(set(e.rstrip("/") for e in listing.split("\0")
                      if e.rstrip("/") and e.rstrip("/").split("/")[-1] in DEP_DIRS))
    return [r for r in rels if not any(r.startswith(o + "/") for o in rels)]


def _editable_paths(path):
    """The absolute paths an editable install points the interpreter at: the
    path lines of a `.pth` file, the quoted paths of an `__editable__` finder."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    if path.endswith(".pth"):
        found = [ln.strip() for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith(("#", "import"))]
    else:
        found = _QUOTED.findall(text)
    return [p for p in found if os.path.isabs(p)]


def _listing(path):
    """The sorted entry names of directory `path`, or [] when it is none."""
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _site_packages(top):
    """Every site-packages directory a virtualenv at `top` can hold:
    `lib/python<X.Y>/site-packages` (and `lib64`) on POSIX,
    `Lib/site-packages` on Windows. Each directory once: on a filesystem that
    ignores case, `lib` and `Lib` are one directory."""
    out, seen = [], set()
    for lib in ("lib", "lib64", "Lib"):
        base = os.path.join(top, lib)
        for site in [os.path.join(base, v, "site-packages") for v in _listing(base)
                     if v.startswith("python")] + [os.path.join(base, "site-packages")]:
            if not os.path.isdir(site) or os.path.islink(site):
                continue
            st = os.stat(site)
            if (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino))
                out.append(site)
    return out


def _link_candidates(top):
    """`[(path, kind)]` - the only entries under the dependency directory `top`
    that can carry a link into the tree: each top-level entry and each entry of
    a top-level `@scope` directory (where npm, pnpm and yarn put a workspace
    package's link), as `link`; and each `.pth` or `__editable__` file directly
    under a site-packages directory (where `pip install -e` leaves its path),
    as `editable`. Nothing inside a package is opened, which is what keeps the
    scan to a listing per directory rather than a walk of every installed file."""
    out = []
    for name in _listing(top):
        full = os.path.join(top, name)
        out.append((full, "link"))
        if name.startswith("@") and os.path.isdir(full) and not os.path.islink(full):
            out.extend((os.path.join(full, n), "link") for n in _listing(full))
    for site in _site_packages(top):
        out.extend((os.path.join(site, n), "editable") for n in _listing(site)
                   if n.endswith(".pth") or n.startswith("__editable__"))
    return out


def workspace_links(source, rels, roots, deadline):
    """`(links, problem)` - `links` is `[(entry, target)]`, every link and every
    editable-install path among `_link_candidates` of the dependency
    directories `rels` of `source` that lands inside `roots` but outside every
    one of those directories: a workspace package, which would load the shared
    tree's implementation into a run meant to see HEAD's. The scan stops when
    `deadline` passes, and the answer is then `(None, problem)`, never a
    partial list read as complete."""
    deps = [os.path.realpath(os.path.join(source, *r.split("/"))) for r in rels]

    def into_tree(target):
        real = os.path.realpath(target)
        return _under(real, roots) and not _under(real, deps)

    out = []
    for rel in rels:
        top = os.path.join(source, *rel.split("/"))
        for full, kind in _link_candidates(top):
            if _left(deadline) < 1:
                return None, ("the run timed out: no time was left of the deadline "
                              "to scan %s for links into the tree" % (rel,))
            shown = "%s/%s" % (rel, os.path.relpath(full, top).replace(os.sep, "/"))
            if os.path.islink(full):
                if into_tree(full):
                    out.append((shown, os.path.realpath(full)))
            elif kind == "editable" and os.path.isfile(full):
                out.extend((shown, p) for p in _editable_paths(full) if into_tree(p))
    return out, None


def _npmrc_state(root, deadline):
    """What becomes of each `.npmrc` that exists - an existence check, never a
    read, since the user's carries registry credentials."""
    _c, tracked = _git(root, ["ls-tree", "--name-only", "HEAD", "--", ".npmrc"],
                       timeout=max(1, _left(deadline)))
    said = []
    if tracked.strip() == ".npmrc":
        said.append("the project's tracked .npmrc carried with HEAD")
    elif os.path.isfile(os.path.join(root, ".npmrc")):
        said.append("the project's untracked .npmrc dropped")
    if os.path.isfile(os.path.join(os.path.expanduser("~"), ".npmrc")):
        said.append("the user's ~/.npmrc dropped (every run has a fresh home)")
    return said or ["no .npmrc to carry or drop"]


def dependency_plan(source, root, deadline):
    """`(plan, problem)` - which ignored dependency directories of `source` are
    linked into a throwaway of `root`, which are skipped and why, and what
    becomes of each `.npmrc`. A directory is linked only where its parent
    exists at `root`'s HEAD and no entry of it links into the tree
    (`workspace_links`): such a directory is skipped, the entry named as its
    reason, and the run proceeds without it - a command that never needed it
    still proves, and one that did fails for want of it, which the basis says."""
    code, top = _git(source, ["rev-parse", "--show-toplevel"],
                     timeout=max(1, _left(deadline)))
    if code != 0:
        return None, "--deps-from %s is not inside a git repository: %s" % (source, top)
    code, listing = _git(top, ["ls-files", "-z", "--others", "--ignored",
                               "--exclude-standard", "--directory"],
                         timeout=max(1, _left(deadline)), strip=False)
    if code != 0:
        return None, "git could not list %s's ignored directories: %s" % (top, listing)
    rels = [r for r in dep_rels(listing)
            if os.path.isdir(os.path.join(top, *r.split("/")))]
    parents = sorted(set(posixpath.dirname(r) for r in rels) - set([""]))
    at_head = set()
    if parents:
        code, text = _git(root, ["ls-tree", "-z", "--name-only", "HEAD", "--"]
                          + parents, timeout=max(1, _left(deadline)), strip=False)
        at_head = set(p for p in text.split("\0") if p) if code == 0 else set()
    placed = [r for r in rels if posixpath.dirname(r) in at_head | set([""])]
    skipped = [(r, "its parent directory is not at HEAD")
               for r in rels if r not in placed]
    roots = sorted(set((top, os.path.realpath(top), root, os.path.realpath(root))))
    links, problem = workspace_links(top, placed, roots, deadline)
    if problem is not None:
        return None, problem
    into = {}
    for entry, target in links:
        owner = max((r for r in placed if entry.startswith(r + "/")), key=len)
        into.setdefault(owner, []).append("%s -> %s" % (entry, target))
    skipped += [(r, "it holds a link into the shared tree, through which HEAD's "
                    "run would read the working tree's implementation: %s"
                    % ("; ".join(into[r]),)) for r in placed if r in into]
    return {"source": top, "linked": [r for r in placed if r not in into],
            "skipped": skipped, "npmrc": _npmrc_state(root, deadline)}, None


def link_dependencies(path, plan):
    """Link each planned directory into the throwaway at `path`, entry by entry,
    leaving out `DEP_CACHES` and anything HEAD already put there. Returns the
    problem, or None."""
    for rel in (plan or {}).get("linked") or []:
        src = os.path.join(plan["source"], *rel.split("/"))
        dst = os.path.join(path, *rel.split("/"))
        try:
            if not os.path.isdir(dst):
                os.makedirs(dst)
            for name in sorted(os.listdir(src)):
                target = os.path.join(dst, name)
                if name in DEP_CACHES or os.path.lexists(target):
                    continue
                entry = os.path.join(src, name)
                os.symlink(entry, target, target_is_directory=os.path.isdir(entry))
        except OSError as exc:
            return "could not link %s into the throwaway: %s" % (rel, exc)
    return None


def deps_clause(plan):
    """The basis clause naming what was linked, from where, what a runner may
    write back through, what was skipped and what became of each `.npmrc`."""
    if plan is None:
        return ""
    src = plan["source"]
    if plan["linked"]:
        said = ("dependencies linked from %s, entry by entry: %s - %s are not "
                "linked and a new entry a runner makes beside the links stays in "
                "the throwaway, but a write into a linked entry lands in %s and is "
                "not watched" % (src, ", ".join(plan["linked"]), ", ".join(DEP_CACHES),
                                 ", ".join(os.path.join(src, *r.split("/"))
                                           for r in plan["linked"])))
    else:
        said = "no ignored dependency directory linked from %s" % (src,)
    if plan["skipped"]:
        said += "; not linked: %s" % ("; ".join("%s (%s)" % s for s in plan["skipped"]),)
    return "; %s; %s" % (said, "; ".join(plan["npmrc"]))


# --- the throwaway tree itself ---
def leftover_throwaways(root, timeout=120):
    """`[{"path", "state", "pid"}]` - registered worktrees whose path carries
    `THROWAWAY_PREFIX`, each graded by the process its `OWNER_FILE` names:
    `running` while that process is alive (a sibling's `red`, still going),
    `left-behind` once it is gone, `unknown` with no owner record. Reported,
    never pruned. A reused pid reads as `running`, the safe direction."""
    code, listing = _git(root, ["worktree", "list", "--porcelain"], timeout=timeout)
    if code != 0:
        return []
    out = []
    for ln in listing.splitlines():
        if not ln.startswith("worktree "):
            continue
        path = ln[len("worktree "):]
        if not any(part.startswith(THROWAWAY_PREFIX)
                   for part in path.replace("\\", "/").split("/")):
            continue
        pid = None
        try:
            with open(os.path.join(os.path.dirname(path), OWNER_FILE), "r",
                      encoding="utf-8") as fh:
                pid = json.load(fh).get("pid")
        except (OSError, ValueError, AttributeError):
            pid = None
        alive = _locks.pid_alive(pid) if pid is not None else None
        out.append({"path": path, "pid": pid,
                    "state": {True: "running", False: "left-behind"}.get(alive,
                                                                         "unknown")})
    return out


def leftover_line(left):
    """One leftover throwaway as the human output says it: what its owner record
    establishes, and never more."""
    if left["state"] == "running":
        return "registered by a run still going (pid %s) - not pruned" % (left["pid"],)
    if left["state"] == "left-behind":
        return ("LEFT BEHIND by an earlier run (pid %s is gone) - not pruned"
                % (left["pid"],))
    return ("registered by another run - left behind, or still running (no owner "
            "record) - not pruned")


def holder_base(root, platform=None, environ=None):
    """A temp directory OUTSIDE the shared tree, or None. A TMPDIR pointing inside
    the repository would put the throwaway worktree where siblings' `git status`
    sees it, so the environment's own temp variables and then the platform's own
    temp directories are tried next - on every platform, since a Windows host
    whose temp directory sits in the repository needs the fallback as much as a
    POSIX one does. `platform` and `environ` default to `os.name` and
    `os.environ`, read at call time; passing them selects a platform's branch
    without changing the process's own."""
    environ = os.environ if environ is None else environ
    roots = [r for r in set((root, os.path.realpath(root))) if r]
    candidates = [tempfile.gettempdir()] + [environ.get(name) for name in
                                            ("TMPDIR", "TEMP", "TMP")]
    candidates += _platform_temp_dirs(platform, environ)
    for cand in candidates:
        if (cand and os.path.isdir(cand) and os.access(cand, os.W_OK)
                and not _under(os.path.abspath(cand), roots)):
            return cand
    return None


def _platform_temp_dirs(platform=None, environ=None):
    """The temp directories a platform keeps whatever its environment says:
    the per-user one under the local application data and the system one on
    Windows, `/tmp` and `/var/tmp` elsewhere. `platform` and `environ` default
    to `os.name` and `os.environ`, read at call time."""
    platform = os.name if platform is None else platform
    environ = os.environ if environ is None else environ
    if platform != "nt":
        return ["/tmp", "/var/tmp"]
    local = environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")
    system = environ.get("SystemRoot") or environ.get("SYSTEMROOT")
    return [os.path.join(local, "Temp")] + ([os.path.join(system, "Temp")]
                                            if system else [])


def _build_throwaway(root, path, tests, timeout=120):
    """`(copied, problem)`: HEAD checked out at `path`, the tests laid over it."""
    code, text = _git(root, ["worktree", "add", "--detach", "--quiet", path, "HEAD"],
                      timeout=timeout)
    if code != 0:
        return [], "git could not build the throwaway tree: %s" % (text,)
    return _lay_over(root, path, tests), None


def _lay_over(root, path, rels):
    """Copy each of `rels` from the working tree into the throwaway; one the
    working tree no longer has is removed there. Returns what was copied."""
    copied = []
    for rel in rels:
        src = os.path.join(root, *rel.split("/"))
        dst = os.path.join(path, *rel.split("/"))
        if not os.path.isfile(src):
            if os.path.isfile(dst):
                os.remove(dst)
            continue
        if not os.path.isdir(os.path.dirname(dst)):
            os.makedirs(os.path.dirname(dst))
        shutil.copyfile(src, dst)
        copied.append(rel)
    return copied


def _remove_throwaway(root, holder, path):
    """True only when the directory is gone AND git no longer lists it.

    The removal is asked of git whether or not the build got as far as
    registering the tree, because a build that died half way is exactly the
    case in which nobody knows."""
    _git(root, ["worktree", "remove", "--force", path], timeout=REMOVE_GIT_TIMEOUT)
    shutil.rmtree(holder, ignore_errors=True)
    code, listing = _git(root, ["worktree", "list", "--porcelain"],
                         timeout=REMOVE_GIT_TIMEOUT)
    listed = code != 0 or still_listed(listing, path)
    return not os.path.exists(holder) and not listed


def still_listed(listing, path, resolve=None):
    """Whether `git worktree list --porcelain` output still names `path`.

    Each record's path is compared as a PATH, both sides resolved, never
    searched for as text: git prints its own spelling - forward slashes and
    long names on Windows, a resolved path through a symlink - while `path` is
    this platform's, so a substring test answers "gone" for a tree git still
    lists, and answers "listed" for a sibling whose path merely begins with
    this one. `resolve` defaults to the resolved, case-folded path."""
    fn = resolve if resolve is not None else _canonical_path
    return any(_worktrees.same_tree(rec["path"], path, fn)
               for rec in _worktrees.parse_list(listing))


def _canonical_path(path):
    """One spelling per directory: resolved, and case-folded where the platform
    folds case."""
    return os.path.normcase(os.path.realpath(path))


def _run_in(path, cmd, timeout, env):
    """`(code, text, problem)` for the command, run in the throwaway as a process
    group, so a timeout or an interrupt stops everything it started."""
    try:
        proc = subprocess.Popen(cmd, cwd=path, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env,
                                **_proc_group.group_kwargs())
    except OSError as exc:
        return None, "", "the command could not start: %s" % (exc,)
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        confirmed = _proc_group.tear_down(proc)
        text = _proc_group.drain(proc)
        return None, text, ("the run timed out after %s s and its process group "
                            "was torn down%s" % (timeout, "" if confirmed else
                                                 " (not confirmed)"))
    except BaseException:
        _proc_group.tear_down(proc)
        _proc_group.drain(proc)
        raise
    return proc.returncode, (out or b"").decode("utf-8", "replace"), None


_TALLY_KEYS = {"house": "cases ", "pytest": " in ", "unittest": "Ran ",
               "jest": "Tests:", "vitest": "Tests "}
# Said in place of a decisive line when neither reader matched. A line chosen
# by its position - the last one is often a package manager's update notice
# printed after the run - would name an unrelated line as the run's cause.
NO_READER = ("no tally or error reader matched its output, so no line of it is "
             "quoted as decisive")
NO_OUTPUT = "the run printed no output"


def _decisive_line(text, tally):
    """The line a reader checks the verdict against: the tally, else the error,
    else a sentence saying no reader matched - never a line picked by position."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if tally is not None and tally["runner"] in _TALLY_KEYS:
        hits = [ln for ln in lines if _TALLY_KEYS[tally["runner"]] in ln]
        if hits:
            return hits[-1]
    errors = _ERROR_LINE.findall(text)
    if errors:
        return errors[-1].strip()
    return NO_READER if lines else NO_OUTPUT


def _ids(cases):
    return _output.some_of(["%s (%s)" % (c["id"] or c["label"] or "?", c["why"])
                            for c in cases])


def _refused_clause(refused):
    """The basis clause for the `--case` names that name no failing case."""
    return ("; --case %s names no case that failed an assertion in this run"
            % (", ".join(refused),) if refused else "")


def red_verdict(run, ctx):
    """`(exit, verdict, block, note)` - what the run in the throwaway proved.

    `run` is `{"cmd", "code", "text", "problem", "second", "head", "fix"}`;
    `second` is the `--introduces` re-run with the working tree's
    implementation copied in, `head` the baseline - HEAD's own test files on
    HEAD's code, made FIRST in the fresh throwaway with the new declared test
    files as empty stubs, the jest and vitest ones among them (`absent`) left
    out instead - and `fix` the task's test files on the working tree's code,
    made when the task's run is red on a green baseline. Every run has an
    isolated environment of its own. `ctx` is `{"root", "implementation",
    "tests", "cases", "symbols", "dropped", "new", "absent", "head_files",
    "head_defs", "head_modules", "head_js", "path"}` - `head_tree`'s answer,
    and the throwaway's path."""
    at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    shown = " ".join(run["cmd"])
    env_clause = "; run without %s" % (", ".join(ctx["dropped"]) or "nothing",)
    if ctx.get("naming"):
        env_clause += ("; kept, naming the shared root: %s - the run may have read "
                       "shared-tree files through it" % (", ".join(ctx["naming"]),))
    env_clause += deps_clause(ctx.get("deps"))
    if run["problem"] is not None:
        return E_CANNOT_PROVE, V_NOT_RUN, {
            "status": RED_CANNOT, "at": at,
            "basis": "`%s` in a throwaway tree at HEAD: %s%s"
                     % (shown, run["problem"], env_clause)}, None
    code, text = run["code"], run["text"]
    verdict, tally = classify_run(code, text, run["cmd"])
    line = _decisive_line(text, tally)
    where = "`%s` in a throwaway tree at HEAD exited %d" % (shown, code)
    if verdict == V_GREEN:
        return E_NOT_RED, verdict, None, (
            "%s (%s): the test PASSED in the throwaway - HEAD's implementation with "
            "this task's test files, run with %s removed from its environment - so "
            "it proves nothing yet; fix the test, there is no redFirst word to "
            "record for this%s" % (where, line, ", ".join(ctx["dropped"]) or "nothing",
                                   deps_clause(ctx.get("deps"))))
    failing = (failing_cases(text, tally["runner"])
               if tally is not None and tally["runner"] is not None else [])
    how = "HEAD's own tests green on HEAD's code"
    absent = ctx.get("absent") or []
    stubbed = [rel for rel in ctx.get("new") or [] if rel not in absent]
    if stubbed:
        how += (", its declared test files new at HEAD (%s) laid over as empty "
                "files" % (", ".join(stubbed),))
    if absent:
        how += (", its declared jest or vitest test files new at HEAD (%s) left "
                "absent" % (", ".join(absent),))
    if ctx["cases"]:
        how = "named by --case, " + how
    baseline = baseline_problem(run.get("head"), run["cmd"])
    if verdict == V_RED:
        problem = baseline or fix_problem(run.get("fix"), run["cmd"], tally)
        if problem is not None:
            return E_CANNOT_PROVE, verdict, {
                "status": RED_CANNOT, "at": at,
                "basis": "%s with failing cases %s, but %s - %s%s"
                         % (where, _ids(failing), problem, line, env_clause)}, None
        files = ctx.get("head_files")
        others = (None if files is None else sorted(
            (set(files) | set(_throwaway_files(ctx["path"]) if ctx.get("path") else ()))
            - set(ctx["tests"])))
        scope = {"tests": ctx["tests"], "cmd": run["cmd"],
                 "roots": tuple(r for r in (ctx["root"], ctx.get("path")) if r),
                 "wt": _test_texts(ctx["root"], ctx["tests"]),
                 "head_defs": ctx.get("head_defs"),
                 "head_modules": ctx.get("head_modules"),
                 "head_js": ctx.get("head_js"), "others": others}
        own, refused = own_failures(failing, ctx["cases"], tally["runner"], scope)
        refused_clause = _refused_clause(refused)
        uncredited = "; ".join(
            "%s: %s" % (f["label"] or f["id"], why) for f, why in
            ((f, credit_problem(f, tally["runner"], scope)) for f in failing
             if f["assertion"]) if why)
        if not own and not ctx["cases"]:
            rule = (("whose working-tree copy defines its title chain, with no "
                     "test of that chain and identical body in HEAD's test files")
                    if tally["runner"] in JS_RUNNERS else
                    ("whose named class defines it, with no identical def in "
                     "HEAD's test files"))
            return E_CANNOT_PROVE, verdict, {
                "status": RED_CANNOT, "at": at,
                "basis": "%s with failing cases %s, but none is the task's own (%s) "
                         "- a case is the task's only when the runner locates it in "
                         "a declared test file (%s) %s - %s%s"
                         % (where, _ids(failing), uncredited or "none asserted",
                            ", ".join(ctx["tests"]), rule, line, env_clause)}, None
        if own:
            return E_PROVED, verdict, {
                "status": RED_PROVED, "at": at,
                "basis": "%s with %d of %d collected tests failing an assertion, "
                         "the task's own among them (%s), each passing with the "
                         "working tree's implementation - %s: %s%s%s"
                         % (where, tally["assertions"], tally["collected"], how,
                            _ids(own), line, refused_clause, env_clause)}, None
        return E_CANNOT_PROVE, verdict, {
            "status": RED_CANNOT, "at": at,
            "basis": "%s, but no case --case names failed an assertion as the "
                     "task's own: %s%s - %s%s%s"
                     % (where, _ids(failing),
                        " (%s)" % (uncredited,) if uncredited else "", line,
                        refused_clause, env_clause)}, None
    why_not = [baseline] if baseline and verdict == V_COLLECT else []
    for symbol in (ctx["symbols"] if verdict == V_COLLECT and not baseline else ()):
        holds, why = introduced(ctx["root"], ctx["implementation"], symbol,
                                ctx.get("deadline"))
        error = qualifying_error(text, symbol)
        second = run.get("second")
        if not holds:
            why_not.append(why)
        elif error is None:
            why_not.append("the run's final error is not an %s naming %r: %s"
                           % ("/".join(INTRODUCES_CLASSES), symbol,
                              (final_error(text) or ("", "", "none"))[2]))
        elif second is None or second.get("problem"):
            why_not.append("the second run could not be made: %s"
                           % ((second or {}).get("problem") or "not attempted",))
        elif error in second["text"]:
            why_not.append("with the working tree's implementation copied in, a "
                           "second run still ends on %r, so the error is not the "
                           "absence this task fills" % (error,))
        elif classify_run(second["code"], second["text"],
                          run["cmd"])[0] not in (V_GREEN, V_RED):
            why_not.append("with the working tree's implementation copied in, a "
                           "second run lost %r but still reached no assertion "
                           "(%s), so the test is broken with the fix too"
                           % (error, _decisive_line(second["text"], None)))
        else:
            return E_PROVED, verdict, {
                "status": RED_PROVED, "at": at,
                "basis": "%s on %r, and the task introduces %r: %s; a second run "
                         "with the working tree's implementation copied in exited "
                         "%s without that error, its tests reaching their "
                         "assertions%s" % (where, error, symbol, why,
                                           second["code"], env_clause)}, None
    if verdict == V_MIXED:
        reason = ("its output carries the tallies of more than one runner (%s) and "
                  "the command names none of them, so which runner ran - and "
                  "whose failing cases are its own - cannot be told"
                  % ("; ".join("%s: %s" % (r, _decisive_line(text, {"runner": r}))
                               for r in tally["mixed"]),))
    elif verdict == V_COLLECT:
        reason = "no test was collected or none reached an assertion"
    else:
        reason = ("its output carries no test tally this command reads, so an "
                  "assertion failure cannot be told from a crash - no test is "
                  "known to have been collected")
    if failing:
        reason += "; failing without an assertion: %s" % (_ids(failing),)
    return E_CANNOT_PROVE, verdict, {
        "status": RED_CANNOT, "at": at,
        "basis": "%s, but %s: %s%s%s" % (where, reason, line,
                                         ("; " + "; ".join(why_not)) if why_not
                                         else "", env_clause)}, None


def _at_head(root, rels, deadline):
    """`(present, problem)` - which of `rels` HEAD holds, asked of git under
    the one deadline."""
    code, text = _git(root, ["ls-tree", "-z", "--name-only", "HEAD", "--"]
                      + list(rels), timeout=max(1, _left(deadline)), strip=False)
    if code != 0:
        return None, "git could not list HEAD's files: %s" % (text,)
    # NUL-separated: without -z git quotes a path that is not plain ASCII, and a
    # quoted path matches no declared one - HEAD's file would read as absent.
    return set(p for p in text.split("\0") if p) & set(rels), None


def _isolate(path, deadline):
    """Reset the throwaway to HEAD exactly - `checkout -f` and `clean -ffdx`, so
    nothing an earlier run wrote or rewrote there, tracked or not, survives.
    Returns the problem, or None. Each git call is started only with a whole
    second of the deadline left, so none runs past it on the one-second floor
    a timeout is given."""
    for args in (["checkout", "-f", "HEAD", "--", "."], ["clean", "-ffdxq"]):
        if _left(deadline) < 1:
            return "the run timed out: no time was left of the deadline for the reset"
        code, text = _git(path, args, timeout=max(1, _left(deadline)))
        if code != 0:
            return "git could not reset the throwaway to HEAD: %s" % (text,)
    return None


def _timed_run(path, cmd, deadline, timeout, env):
    """`{"code", "text", "problem", "seconds"}` for one more run in the
    throwaway, within what is left of the deadline."""
    left = _left(deadline)
    started = time.time()
    if left < 1:
        code, text, problem = None, "", ("the run timed out: no time was left of "
                                         "the %s-second deadline" % (timeout,))
    else:
        code, text, problem = _run_in(path, cmd, left, env)
    return {"code": code, "text": text, "problem": problem,
            "seconds": round(time.time() - started, 2)}


# Every name a home-directory lookup reads - the same table
# `tools/sweep-selftests.py` isolates its children with (a case pins that the two
# agree): `HOME` alone leaves the XDG roots at the real home on linux and
# `USERPROFILE` on windows, and git for windows joins `HOMEDRIVE`/`HOMEPATH`.
HOME_VARS = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
             "XDG_CACHE_HOME", "XDG_STATE_HOME", "APPDATA", "LOCALAPPDATA")


def _isolated_env(env, scratch, tag):
    """`env` for ONE run: a new empty home under every name in `HOME_VARS`
    plus the windows drive/path pair, a TMPDIR/TMP/TEMP of its own and no user
    site-packages. Every run gets new directories, so the runs differ only in
    the files laid over the throwaway - nothing one run or the caller's
    environment holds reaches another."""
    home = tempfile.mkdtemp(prefix=tag + "-home-", dir=scratch)
    tmp = tempfile.mkdtemp(prefix=tag + "-tmp-", dir=scratch)
    drive, tail = os.path.splitdrive(home)
    out = dict(env)
    out.update(dict((name, home) for name in HOME_VARS))
    out.update({"HOMEDRIVE": drive, "HOMEPATH": tail, "PYTHONNOUSERSITE": "1",
                "TMPDIR": tmp, "TMP": tmp, "TEMP": tmp})
    return out


def _isolated_run(root, path, rels, cmd, deadline, timeout, env, scratch, tag,
                  stubs=(), deps=None):
    """`(run, copied)` - the throwaway reset to HEAD, `rels` laid over it from
    the working tree, each of `stubs` written as an EMPTY file and the `deps`
    plan's directories linked in again - the reset removed them - and the
    command run in an isolated environment. With less than a second of the
    deadline left no run is made at all - not even the reset's git calls,
    which would otherwise run past it."""
    if _left(deadline) < 1:
        return {"code": None, "text": "", "seconds": 0.0,
                "problem": "the run timed out: no time was left of the "
                           "%s-second deadline" % (timeout,)}, []
    problem = _isolate(path, deadline)
    if problem is not None:
        return {"code": None, "text": "", "problem": problem, "seconds": 0.0}, []
    copied = _lay_over(root, path, rels)
    for rel in stubs:
        dst = os.path.join(path, *rel.split("/"))
        if not os.path.isdir(os.path.dirname(dst)):
            os.makedirs(os.path.dirname(dst))
        open(dst, "w").close()
    problem = link_dependencies(path, deps)
    if problem is not None:
        return {"code": None, "text": "", "problem": problem, "seconds": 0.0}, copied
    return _timed_run(path, cmd, deadline, timeout,
                      _isolated_env(env, scratch, tag)), copied


def _wants_second(code, text, symbols, cmd=None):
    """Whether a second run is owed: a collection error some named symbol's
    missing-symbol error could explain."""
    verdict, _t = classify_run(code, text, cmd) if code is not None else (None, None)
    return verdict == V_COLLECT and any(qualifying_error(text, s) for s in symbols)


def _left(deadline):
    """Whole seconds left before `deadline`; 0 or less when it has passed."""
    return int(deadline - time.time())


def _red_scope(args, cmd, deadline):
    """`(scope, problem)` - everything `red` needs before it builds anything."""
    if not cmd:
        return None, "red needs the test command after `--`"
    if not (args.task and args.manifest) or args.files:
        return None, ("red takes its scope off the plan: pass --manifest and "
                      "--task, and no --files")
    if not 1 <= args.timeout <= MAX_TIMEOUT:
        return None, ("--timeout %s is outside 1..%d: one deadline covers every run, "
                      "and it must leave the host's %d-second Bash limit room for "
                      "the teardown, or the host kills the helper before its own "
                      "cleanup runs" % (args.timeout, MAX_TIMEOUT, HOST_BASH_LIMIT))
    bad = [s for s in args.introduces if not _SYMBOL_SHAPE.match(s)]
    if bad:
        return None, ("--introduces takes an identifier (letters, digits, `_`, "
                      "`.`), and %r is not one - a fragment is a substring of "
                      "outputs it has nothing to do with" % (bad[0],))
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        return None, "cannot read/parse %s: %s" % (args.manifest, exc)
    task, problem = find_task(manifest if isinstance(manifest, dict) else {},
                              args.task)
    if problem is not None:
        return None, problem
    implementation, tests = split_scope(task)
    if not tests:
        return None, ("task %s declares no test file, so a throwaway at HEAD "
                      "would prove nothing about this task's test" % (args.task,))
    code, root = _git(os.path.abspath(args.project), ["rev-parse", "--show-toplevel"],
                      timeout=max(1, _left(deadline)))
    if code != 0:
        return None, "%s is not inside a git repository: %s" % (args.project, root)
    named = _names_shared_tree(cmd, root, os.path.abspath(args.project))
    if named:
        return None, ("the command names the shared tree (%s); give its paths "
                      "relative to the tree root so they resolve inside the "
                      "throwaway - an interpreter inside the tree (.venv) is "
                      "untracked and absent there too" % (", ".join(named),))
    present = [t for t in tests if os.path.isfile(os.path.join(root, *t.split("/")))]
    if not present:
        return None, ("none of task %s's test files (%s) is in the working tree, "
                      "so a throwaway would hold HEAD alone"
                      % (args.task, ", ".join(tests)))
    deps, problem = dependency_plan(os.path.abspath(args.deps_from or args.project),
                                    root, deadline)
    if problem is not None:
        return None, problem
    return {"root": root, "implementation": implementation, "tests": present,
            "declared": tests, "deps": deps}, None


def _arm():
    """Arm the interrupt handlers where Python allows it (the main thread)."""
    try:
        return _proc_group.arm_interrupt()
    except ValueError:
        return None


def run_red(args, cmd, out):
    """`red`: prove a red in a throwaway tree and print the `redFirst` block."""
    deadline = time.time() + args.timeout
    scope, problem = _red_scope(args, cmd, deadline)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    root = scope["root"]
    leftovers = leftover_throwaways(root, timeout=max(1, _left(deadline)))
    env, dropped, naming = child_env(root)
    # The runs swap files in place, and a copy of the same size written in the
    # same second as the one it replaces leaves a cached bytecode file Python
    # still trusts - in the tree or under PYTHONPYCACHEPREFIX alike. So no run
    # writes one, and none is there to be read.
    env = dict(env, PYTHONDONTWRITEBYTECODE="1")
    # The user's npm config carries registry credentials; a run's fresh home
    # leaves it behind, and so must a variable pointing straight at it.
    for key in sorted(k for k in env if k.lower() == "npm_config_userconfig"):
        del env[key]
        dropped.append(key)
    deps = scope["deps"]
    _c, head = _git(root, ["rev-parse", "HEAD"], timeout=max(1, _left(deadline)))
    base = holder_base(root)
    if base is None:
        sys.stderr.write("ERROR: every temp directory this machine offers is inside "
                         "the shared tree %s, and a throwaway there would be a "
                         "worktree siblings see; set TMPDIR outside it\n" % (root,))
        return E_USAGE
    holder = tempfile.mkdtemp(prefix=THROWAWAY_PREFIX, dir=base)
    path = os.path.join(holder, "tree")
    try:
        with open(os.path.join(holder, OWNER_FILE), "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid()}, fh)
    except OSError:
        pass
    run = {"cmd": cmd, "code": None, "text": "", "problem": None, "second": None,
           "head": None, "fix": None}
    state = {"new": [], "absent": [], "head_files": None, "head_defs": None,
             "head_modules": None, "head_js": None}
    copied = []
    previous = _arm()
    try:
        try:
            present, run["problem"] = _at_head(root, scope["declared"], deadline)
            if run["problem"] is None:
                state["new"] = sorted(set(scope["tests"]) - present)
                # jest and vitest fail an empty suite, so a new file of theirs
                # is left absent - the reset already removes it - and the
                # stub stays the rule for every other runner.
                state["absent"] = [rel for rel in state["new"]
                                   if _is_js_test_path(rel, set(scope["tests"]))]
                (state["head_files"], state["head_defs"], state["head_modules"],
                 state["head_js"]) = head_tree(
                    root, set(scope["tests"]), deadline)
                _copied, run["problem"] = _build_throwaway(
                    root, path, [], timeout=max(1, _left(deadline)))
            if run["problem"] is None and _left(deadline) < 1:
                run["problem"] = ("the run timed out: building the throwaway spent "
                                  "the %s-second deadline" % (args.timeout,))
            if run["problem"] is None:
                run["head"], _c = _isolated_run(
                    root, path, [], cmd, deadline, args.timeout, env, holder,
                    "baseline", stubs=[rel for rel in state["new"]
                                       if rel not in state["absent"]], deps=deps)
                run["head"]["absent"] = state["absent"]
            if run["problem"] is None:
                task, copied = _isolated_run(root, path, scope["declared"], cmd,
                                             deadline, args.timeout, env, holder,
                                             "task", deps=deps)
                run["code"], run["text"], run["problem"] = (
                    task["code"], task["text"], task["problem"])
            if run["problem"] is None and _wants_second(run["code"], run["text"],
                                                        args.introduces, cmd):
                run["second"], _c = _isolated_run(
                    root, path, scope["declared"] + scope["implementation"], cmd,
                    deadline, args.timeout, env, holder, "second", deps=deps)
            verdict1 = (classify_run(run["code"], run["text"], cmd)[0]
                        if run["problem"] is None and run["code"] is not None
                        else None)
            if verdict1 == V_RED and baseline_problem(run["head"], cmd) is None:
                run["fix"], _c = _isolated_run(
                    root, path, scope["declared"] + scope["implementation"], cmd,
                    deadline, args.timeout, env, holder, "fix", deps=deps)
        except KeyboardInterrupt as exc:
            run["problem"] = ("interrupted by %s before the run finished; the "
                              "run's process group was torn down"
                              % (exc or "an interrupt",))
        exit_code, verdict, block, note = red_verdict(run, {
            "root": root, "implementation": scope["implementation"],
            "tests": scope["tests"], "cases": args.case,
            "symbols": args.introduces, "dropped": dropped, "naming": naming,
            "new": state["new"], "absent": state["absent"],
            "head_files": state["head_files"],
            "head_defs": state["head_defs"],
            "head_modules": state["head_modules"],
            "head_js": state["head_js"], "path": path,
            "deadline": deadline, "deps": deps})
    finally:
        removed = _remove_throwaway(root, holder, path)
        if previous is not None:
            _proc_group.disarm_interrupt(previous)
    payload = {"verdict": verdict, "redFirst": block, "note": note,
               "atHead": scope["implementation"], "copied": copied,
               "leftovers": leftovers,
               "dependencies": {"source": deps["source"], "linked": deps["linked"],
                                "skipped": [list(s) for s in deps["skipped"]],
                                "npmrc": deps["npmrc"]},
               "baseline": {"stubbed": [rel for rel in state["new"]
                                        if rel not in state["absent"]],
                            "absent": state["absent"]},
               "environment": {"dropped": dropped, "naming": naming,
                               "set": ["%s=%s" % (k, env[k]) for k in
                                       ("PYTHONDONTWRITEBYTECODE",) if k in env]},
               "throwaway": {"path": path, "head": head, "removed": removed},
               "run": {"argv": cmd, "exit": run["code"],
                       "outputTail": run["text"].splitlines()[-20:],
                       "second": None if run["second"] is None else
                       {"exit": run["second"]["code"],
                        "outputTail": run["second"]["text"].splitlines()[-20:]},
                       "head": _run_record(run["head"]),
                       "fix": _run_record(run["fix"])}}
    if args.as_json:
        out(json.dumps(payload, indent=2, sort_keys=True))
    else:
        out("red-first: %s (throwaway at HEAD %s, removed: %s)"
            % (verdict, (head or "?")[:12], "yes" if removed else "NO"))
        out("  at HEAD: %s" % (", ".join(scope["implementation"]) or "(none declared)"))
        out("  from the working tree: %s" % (", ".join(copied) or "(none)"))
        out("  environment: inherited, without %s" % (", ".join(dropped) or "nothing"))
        out("  dependencies:%s" % (deps_clause(deps)[1:],))
        if naming:
            out("  kept, naming the shared root: %s" % (", ".join(naming),))
        for left in leftovers:
            out("  %s: %s" % (leftover_line(left), left["path"]))
        out(note if block is None else "redFirst: %s" % (json.dumps(block),))
    if not removed:
        sys.stderr.write("ERROR: the throwaway tree at %s could not be removed; "
                         "`git worktree list` names what is left\n" % (path,))
        return E_LEFT_BEHIND
    return exit_code


def _run_record(extra):
    """What the payload keeps of one of `red`'s extra runs, or None."""
    if extra is None:
        return None
    return {"exit": extra["code"], "seconds": extra["seconds"],
            "problem": extra["problem"],
            "outputTail": extra["text"].splitlines()[-20:]}


def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="stamp-verification.py", add_help=True, allow_abbrev=False,
        description="Stamp a verification with the tree it was taken on, and "
                    "grade that stamp against the tree now.")
    parser.add_argument("action", choices=("take", "compare", "red"))
    parser.add_argument("--project", default=".",
                        help="the tree to stamp or to grade against "
                             "(default: the current directory)")
    parser.add_argument("--files", nargs="*", default=[],
                        help="the paths the work under test declares; `take` only")
    parser.add_argument("--manifest", default=None,
                        help="a manifest to read --task's files out of")
    parser.add_argument("--task", default=None,
                        help="a task id whose `files` become the declared scope")
    parser.add_argument("--stamp", default=None,
                        help="the text carrying the stamp; `compare` only")
    parser.add_argument("--stamp-file", dest="stamp_file", default=None,
                        help="a file carrying the stamp; `compare` only")
    parser.add_argument("--introduces", action="append", default=[],
                        help="a symbol the task creates; `red` only - a compile "
                             "or collection error counts as red only when the "
                             "task introduces a symbol the run names")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="seconds every run `red` makes may take together; `red` only")
    parser.add_argument("--case", action="append", default=[],
                        help="the id or full label of a case the task added; "
                             "`red` only - a red "
                             "counts only when one of the task's own cases "
                             "fails an assertion")
    parser.add_argument("--deps-from", dest="deps_from", default=None,
                        help="the checkout whose ignored node_modules and .venv "
                             "directories are linked into the throwaway; `red` only "
                             "(default: --project)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    # An older cached copy asked for a newer action would otherwise answer with a
    # bare "invalid choice" that reads as "this helper does not exist".
    return _claude_home.attach_usage_hint(parser)


def run_take(args, out):
    """`take`: read the tree once, print the fields with their bases and the token."""
    files, problem = resolve_scope(args)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    project = os.path.abspath(args.project)
    excluded, label, note = recorder_exclusion(
        project, os.path.abspath(args.manifest) if args.manifest else None)
    stamp, state = _tree_stamp.take(project, files, excluded=excluded,
                                    manifest=label)
    if note:
        state["contentBasis"] = "%s; %s" % (state.get("contentBasis"), note)
    if args.as_json:
        out(json.dumps({"stamp": stamp, "state": state,
                        "line": _tree_stamp.format_stamp(stamp)},
                       indent=2, sort_keys=True))
    else:
        out("\n".join(_tree_stamp.render_stamp(stamp, state)))
    return 0


def run_compare(args, out, stdin=None):
    """`compare`: grade a stamp against the tree now, in one of three words."""
    if args.files or args.task:
        # The scope rides INSIDE the stamp. Accepting a second one here would let
        # a comparison quietly answer about a different file set than the stamp
        # was taken over, which is the whole defect this command exists to catch.
        sys.stderr.write("ERROR: compare takes its scope from the stamp, so "
                         "--files/--task would be a second answer to which work "
                         "this is about\n")
        return E_USAGE
    text, problem = read_stamp_text(args, stdin=stdin)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    stamp, problem = _tree_stamp.parse_stamp(text)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    project = os.path.abspath(args.project)
    excluded, _label, note = recorder_exclusion(
        project, stored_manifest(project, stamp.get("manifest")))
    result = _tree_stamp.compare(stamp, project, excluded=excluded)
    if note:
        result["state"]["contentBasis"] = "%s; %s" % (
            result["state"].get("contentBasis"), note)
    if args.as_json:
        out(json.dumps(result, indent=2, sort_keys=True))
    else:
        out("\n".join(_tree_stamp.render_comparison(result)))
    return EXIT_FOR[result["verdict"]]


def main(argv, out=print, stdin=None):
    argv = list(argv)
    # Everything after the first `--` is the red run's command, kept away from the
    # parser so a test command's own flags are never read as this command's.
    cmd = argv[argv.index("--") + 1:] if "--" in argv else None
    argv = argv[:argv.index("--")] if "--" in argv else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    if args.action == "red":
        return run_red(args, cmd, out)
    if cmd is not None:
        sys.stderr.write("ERROR: only `red` takes a command after `--`\n")
        return E_USAGE
    if args.action == "take":
        return run_take(args, out)
    return run_compare(args, out, stdin=stdin)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    # Only this command's own flags: after `--` a `--selftest` belongs to the red
    # run's test command.
    _own = sys.argv[1:sys.argv.index("--")] if "--" in sys.argv else sys.argv[1:]
    if "--selftest" in _own:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("stamp-verification.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_stamp_verification.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
