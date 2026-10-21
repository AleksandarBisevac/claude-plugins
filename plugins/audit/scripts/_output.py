#!/usr/bin/env python3
"""
Terminal output that cannot be killed by a character it cannot spell, and the anchor
every other script finds itself by - stdlib only.

TWO JOBS, AND THE SECOND ONE IS WHY THIS FILE NEVER MOVES. `safe_stdio()` is the
first and the older one. The second is the path bootstrap: `SCRIPTS_DIR` and its
four companions below are the one written-down statement of where the tree's
directories are, `install_path()` puts `scripts/` AND every subdirectory of it
holding a `.py` on `sys.path`, and `PATH_PREAMBLE` is the block every other
`.py` here carries to reach this module without knowing how deep it sits. The
consequence is worth stating where the mechanism lives: the folders under `scripts/`
are LABELS, NOT NAMESPACES - every module is still reached by a bare basename, and
basename uniqueness is what holds the whole arrangement up.

Python does not degrade an unprintable character; it raises. When stdout is a PIPE on
Windows, its encoding is the machine's legacy code page (cp1252 on a US/EU runner), and
printing a check mark there is not a missing glyph - it is a `UnicodeEncodeError`, a
traceback and a non-zero exit, with everything the command was going to say still
unsaid.

The console is not the problem: Python has written UTF-8 to the Windows console since
3.6. Only redirected output falls back to the code page, which is why this is invisible
until someone pipes, tees or captures - and CI captures everything.

`safe_stdio()` is the whole fix: reconfigure both streams to UTF-8, and set the error
handler to `replace` so that even a stream that cannot be reconfigured, or a consumer
that really is cp1252, gets a `?` instead of a crash. UTF-8 first and `replace` second is
deliberate - the common case (a UTF-8 capable consumer) gets the real character, and the
impossible case degrades one glyph instead of losing the whole run.

WHERE IT APPLIES. Every entry point under `scripts/` calls it as its first statement,
and that is enforced rather than remembered: `_output_lints.entries_missing_guard()`
reads the directory and names any `__main__` block that does not, so the sweep fails
the moment a new script forgets. Ordering matters as much as adoption - the guard has
to run before the first `print`.

`hooks/` deliberately does NOT import this. A hook's product output is `json.dumps`,
which is `ensure_ascii` by default and therefore pure ASCII by construction. Keeping
the hooks importless is worth more than the guard - they run on every tool call, from a
launcher that may not have this directory on its path. CI runs the whole sweep a second
time under `PYTHONIOENCODING=cp1252`, which is what actually covers them.

THE LINTS ARE NOT HERE. What judges the repository's own source - the dialect lints,
the preamble check, the prose-number scan, the selftest coverage classifier - is
development code and lives in `tools/lints/_output_lints.py`; this file holds only
what a shipped script asks of it. `PATH_PREAMBLE`, the text that check pins, moved
with the check, so the preamble every script carries is still the one `_output_lints`
counts.

This module carries no `--selftest`; its cases live in `tests/test__output.py`.
"""

import contextlib
import errno
import io
import json
import os
import shutil
import sys
import time

# --- the anchors ----------------------------------------------------------------
# THIS FILE IS THE MARKER, WHICH IS WHY IT IS THE ONE THAT NEVER MOVES. Every other
# `.py` under `scripts/` finds this directory by walking UP from its own `__file__`
# until it sees `_output.py` — the preamble `PATH_PREAMBLE` pins and
# `path_preamble_violations()` counts — so this FILE is the ONE place the tree's
# shape is written down: the anchors below, and `UI_DIR` further down beside the
# walk that needs it. A `dirname(dirname(...))` anywhere else is that
# file's own depth, hard-coded, and it is wrong the moment the file is moved.
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# scripts -> audit. `hooks/`, `commands/`, `agents/`, `schema/` and
# `.claude-plugin/plugin.json` all hang off this one; six files derived it for
# themselves before, each spelling its own distance from the plugin root.
PLUGIN_ROOT = os.path.dirname(SCRIPTS_DIR)

HOOKS_DIR = os.path.join(PLUGIN_ROOT, "hooks")

# audit -> plugins -> the repo root. `covered_repo_paths()` needs it because CI's
# sweep speaks repo-relative paths, and `_refs` needs it because every `rel` it
# produces already starts with `plugins/audit/`. Both used to derive it separately,
# from their own `__file__`, which is two answers to a question with one.
REPO_ROOT = os.path.dirname(os.path.dirname(PLUGIN_ROOT))

# `tests/` is at the REPOSITORY root, not inside the plugin: the installed copy of
# the plugin carries no suite, so a path the product derives from `PLUGIN_ROOT`
# can never reach one. No walk of `scripts/` or `hooks/` reaches it either, so every
# lint that should cover it has to say so. The scope decision, recorded once here
# and again on each function: the DIALECT rules apply to tests too
# (`house_style_violations`, `entries_missing_guard`), because a test written with
# `typing` or a walrus is exactly as unrunnable on 3.8 as a script written that way,
# and a test that crashes on a cp1252 stream hides its own result.
TESTS_DIR = os.path.join(REPO_ROOT, "tests")

# The two lint modules (`_deps`, `_refs`) are development code: they read the whole
# repository to judge it, and nothing the installed plugin runs imports them.
# `install_path()` NEVER puts this directory on `sys.path` - that is the point of
# keeping it out of `scripts/` - so a development caller (the harness, a tool) adds
# it itself, and the dialect lints below name it beside `TESTS_DIR` so moving the
# two modules out of `scripts/` did not take them out of the dialect rules.
LINTS_DIR = os.path.join(REPO_ROOT, "tools", "lints")


# --- safe stdio ---------------------------------------------------------------
def posix_rel(path, start):
    """A `start`-relative path spelled with "/" on EVERY platform.

    `os.path.relpath` answers in the platform's separator, so the same phase shard
    is `phases/P3.json` in the index that stores it and `phases\\P3.json` in the
    line a Windows reader is shown. One file, two spellings, and the one nobody
    can search for is the one on screen.

    Every value that is PUBLISHED - reported to a human, put in `--json`, persisted,
    or handed to git as a pathspec - goes through here. Values used only to OPEN a
    file do not need it, because Python takes either separator; values compared
    against a manifest do, because the manifest holds this spelling.

    IT LIVES IN THE ANCHOR BECAUSE THE CALLERS ARE IN EVERY LAYER. It began in
    `_manifest_io` - and `_ui_theme`, which publishes a theme path, is that
    module's layer-mate, so it could not reach it without a sideways import. A
    helper the layering forbids half its callers from using is a helper half the
    tree will hand-roll instead, which is the duplication this exists to end.

    Backslashes are replaced UNCONDITIONALLY rather than only `os.sep`. Written as
    `os.sep` this is the identity on POSIX, so no case here could ask it anything
    and the body could be deleted without a suite going red - a check that can only
    fail on the platform nobody runs locally. The cost is a POSIX filename holding
    a literal backslash, which is respelled in what is REPORTED and never in what
    is opened; the same trade `_config.slashed()` takes in `hooks/`.
    """
    return os.path.relpath(path, start).replace("\\", "/")


def safe_stdio():
    """Make stdout/stderr unable to crash on a character they cannot spell.

    Idempotent, and never raises: a stream that has been replaced by a StringIO (which
    every selftest that captures output does) has no `reconfigure`, and a stream that has
    been detached has one that refuses. Neither is a reason to take the process down —
    the point of this function is that output problems stop being fatal.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # No reconfigure (StringIO), already detached, or a platform that refuses.
            # `replace` alone is still worth having if the encoding move is what failed.
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


# --- which project a manifest belongs to ------------------------------------------
# The default home of a plan's committed record. A directory of this shape holds
# the manifest, its journal and its evidence - and never a project's own
# `.claude/`, which is the one fact `project_of_manifest` relies on.
RECORD_DIR_SHAPE = ("docs", "audit")


def _record_shaped(path):
    """True when `path` ends in `RECORD_DIR_SHAPE`, compared by name."""
    head, last = os.path.split(path)
    return (os.path.basename(head), last) == RECORD_DIR_SHAPE


def _record_zone(start):
    """The outermost record-shaped directory at or above `start`, stopping at
    the first ancestor holding `.git` - or None when there is none."""
    zone = None
    cur = start
    while True:
        if _record_shaped(cur):
            zone = cur
        if os.path.exists(os.path.join(cur, ".git")):
            return zone
        parent = os.path.dirname(cur)
        if parent == cur:
            return zone
        cur = parent


def _inside(path, top):
    """True when `path` is `top` or below it."""
    return top is not None and (path == top or path.startswith(top + os.sep))


def project_of_manifest(manifest_path):
    """The project root the manifest at `manifest_path` belongs to - the answer
    the gate's record and raw log, the report, the status read and the
    manifest-writing commands take when no root was named, so a command printed
    without `--project-dir` lands where its siblings do.
    `manifest_dirname_project_violations()` names a site deriving its own.

    The walk goes up from the manifest's own directory. A `.git` entry (a
    directory, or the file a linked worktree carries) is the git toplevel and
    always answers. A `.claude/` directory answers too, so a project nested
    inside a larger repository keeps its own root - EXCEPT inside the record
    directory (`docs/audit`, or a doubled `docs/audit/docs/audit`) at or above
    the manifest. A `.claude/` there is never a project's: it is what a run
    that sited itself by the manifest's own directory left behind, and
    accepting it made every later run answer `docs/audit` as the project and
    record into `docs/audit/docs/audit`, which nothing reads.

    MARKERLESS FALLBACK: with no `.git` and no acceptable `.claude/`, a manifest
    under a record-shaped directory belongs to that directory's grandparent,
    and any other to its own directory - inside the named manifest's tree
    either way, never another repository's.

    `--project-dir` is the caller's to honour before asking this; an
    environment variable is not consulted, because a named manifest says
    which tree it is in and a session's project may be another checkout.
    """
    start = os.path.dirname(os.path.abspath(manifest_path))
    zone = _record_zone(start)
    cur = start
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        if os.path.isdir(os.path.join(cur, ".claude")) and not _inside(cur, zone):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    if zone is not None:
        return os.path.dirname(os.path.dirname(zone))
    return start


# --- the success line ------------------------------------------------------------
# What a verb the main loop calls prints when it succeeded and nobody asked for more.
# Every line a verb prints is read back into a model's context on every call, and a
# success says one thing - what was done and which record now holds it - so the rest
# of today's text is paid for by a reader who already has the answer.
SUCCESS_LINE_BYTES = 200
VERBOSE_FLAG = "--verbose"
CLIPPED_MARK = " ... [clipped; --verbose prints all of it]"
# Flags under which the long form is the contract rather than a habit: a machine
# payload, and the help text argparse prints with exit 0.
LONG_FORM_FLAGS = ("--json", "-h", "--help")


def own_args(argv):
    """The arguments a command reads as its own: everything before the first `--`,
    after which a test command's flags belong to that command."""
    argv = list(argv)
    return argv[:argv.index("--")] if "--" in argv else argv


def without_verbose(argv):
    """`(verbose, argv)` with `--verbose` taken out of the command's own arguments.

    Only from before the first `--`: `stamp-verification.py red -- <command>`
    hands everything after it to a test runner, whose own `--verbose` is not this
    command's to remove.
    """
    argv = list(argv)
    head = own_args(argv)
    tail = argv[len(head):]
    verbose = VERBOSE_FLAG in head
    return verbose, [a for a in head if a != VERBOSE_FLAG] + tail


def clip_bytes(text, limit):
    """`text` cut to at most `limit` bytes of UTF-8, never inside a character."""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:max(limit, 0)].decode("utf-8", "ignore")


def success_line(text, keep=""):
    """`text` then `keep`, folded onto one line of at most `SUCCESS_LINE_BYTES`
    bytes of UTF-8.

    A line that does not fit is cut AND SAYS SO: the mark names `--verbose`, so a
    reader of the short form knows there is more and how to get it rather than
    taking the cut for the whole answer. The cut falls in `text`; `keep` - the
    record a verb wrote - is never cut, unless it alone leaves no room.
    """
    one = " ".join(str(text).split())
    kept = " ".join(str(keep).split())
    if kept and one:
        kept = " " + kept if not kept.startswith(";") else kept
    if len((one + kept).encode("utf-8")) <= SUCCESS_LINE_BYTES:
        return one + kept
    room = SUCCESS_LINE_BYTES - len((CLIPPED_MARK + kept).encode("utf-8"))
    if room <= 0:
        return success_line(one + kept)
    return clip_bytes(one, room).rstrip() + CLIPPED_MARK + kept


def terse_choice(code, lines, summarize):
    """The one line to print in place of `lines`, or None to print them all.

    None whenever the long form is owed: a non-zero exit is a refusal or a failure
    and prints in full, unchanged; and so does a success whose `summarize` answers
    None (the verb's own output carries something the caller must still act on) or
    raises (a summary that could not be made is no reason to hide the answer). An
    output that is already one line within the bound is kept exactly as it is,
    because a caller may be reading that line as a value.
    """
    if code != 0:
        return None
    if len(lines) == 1 and len(lines[0].encode("utf-8")) <= SUCCESS_LINE_BYTES:
        return lines[0]
    if not any(ln.strip() for ln in lines):
        return None
    try:
        picked = summarize(list(lines))
    except Exception:
        return None
    if isinstance(picked, tuple):
        # `(text, payload)`: a token the caller must carry byte for byte, which
        # a cut would make unreadable to the verb that parses it back. It is
        # printed whole, and is the one way a success line exceeds the bound.
        text, payload = picked
        return " ".join(p for p in (success_line(text), payload) if p) or None
    return success_line(picked) if picked else None


def terse_cli(run, argv, summarize, keep_verbose=False, long_form=()):
    """Run an entry point's `run(argv)` and print its success as one line.

    THE DOOR EVERY VERB THE MAIN LOOP CALLS GOES THROUGH, from its `__main__`
    only. `run` is the verb's `main`, unchanged: an in-process caller still gets
    today's text from it, and so does `--verbose` here, which calls it with stdout
    untouched. Otherwise stdout is held, and on success `summarize(lines)` names
    what was done and the record it wrote (see `terse_choice` for when the long
    form is printed instead). stderr is never held.

    `keep_verbose` is for a verb that already reads `--verbose` itself: the flag
    then reaches it, and asks for the same long form it always printed.
    `long_form` names a verb's own flags that keep the long form, unheld, beside
    `LONG_FORM_FLAGS`.
    """
    verbose, rest = without_verbose(argv)
    if keep_verbose and verbose:
        rest = list(argv)
    if verbose or any(f in own_args(rest)
                      for f in LONG_FORM_FLAGS + tuple(long_form)):
        return run(rest)
    held = io.StringIO()
    try:
        with contextlib.redirect_stdout(held):
            code = run(rest)
    except BaseException:
        # Whatever escaped, the text printed before it is still the caller's.
        sys.stdout.write(held.getvalue())
        raise
    text = held.getvalue()
    line = terse_choice(code, text.splitlines(), summarize)
    sys.stdout.write(text if line is None else line + "\n")
    return code


# --- removing a scratch tree ----------------------------------------------------
def remove_tree(path):
    """Remove the directory tree at `path`, read-only entries included; True when
    nothing is left there afterwards, an already-absent path among them.

    THE ONE HOME OF THIS FACT. `tests/_harness.py` binds its `remove_tree` to
    this function, `tools/_suite.py` re-exports that binding and the sweep runner
    binds it too; a repository hook keeps a copy because it may not import what
    it runs, and compares its copy against this body statement for statement.

    WHY NOT A PLAIN RMTREE. Git writes its loose objects READ-ONLY - measurably,
    in every `git init` plus commit a fixture builds. POSIX unlinks a file
    through its DIRECTORY's write bit, so a plain `shutil.rmtree` removes the
    repository and nobody ever noticed. Windows checks the read-only ATTRIBUTE
    on the file itself and `os.unlink` raises, so the same call leaves
    `.git/objects/**` behind - and with `ignore_errors=True`, the usual
    spelling, leaves it behind SILENTLY. That surfaced once
    `tools/sweep-selftests.py` began asserting the scratch directory is empty
    afterwards, confirmed by emulating the one rule that differs (unlink refuses
    a file with no owner-write bit).

    THE ORDINARY REMOVAL RUNS FIRST AND THE CHMOD PASS IS THE FALLBACK, so
    nothing is relaxed on the platform where nothing needed relaxing. Chmod'ing
    the tree up front would also remove it, and would quietly paper over a
    genuine permission failure on both platforms.

    THE FALLBACK NEVER GOES THROUGH A LINK. `os.chmod` on a symbolic link
    changes its TARGET, which may be any file on the machine, and `os.walk`
    over a path that is itself a link walks the tree it points at; so a link at
    `path` is left alone (it answers False, still there) and a link inside the
    tree is skipped by the chmod pass and removed as the link it is.

    NEITHER `onerror` NOR `onexc`: the first is deprecated and the second does
    not exist on the 3.8 floor. Asking whether the path survived needs neither.
    """
    shutil.rmtree(path, ignore_errors=True)
    if not os.path.lexists(path):
        return True
    if os.path.islink(path):
        return False
    # Top-down and lazy: a directory is made writable before it is descended
    # into.
    for base, dirs, names in os.walk(path):
        for entry in [base] + [os.path.join(base, name) for name in dirs + names]:
            if os.path.islink(entry):
                continue
            try:
                os.chmod(entry, 0o700)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.lexists(path)


# --- a name another process holds open -----------------------------------------
# Windows refuses a create, unlink, rename or replace of a name another process
# still has open - a reader of a lock, a breaker on its way out, a plan a reader is
# parsing - with a permission error, where POSIX lets the operation through. That
# refusal is CONTENTION: the holder lets go in milliseconds, and a writer that reads
# it as a refusal loses its write. So every concurrent writer's lock, breaker and
# replace goes through `while_shared`, which waits the denial out inside the
# deadline the operation already has; only the deadline passing makes it a
# refusal, and then the denial itself is raised, naming the file.
#
# THE ONE HOME OF THIS RULE, and it lives in the anchor because its callers are
# layer-mates that may not import each other: the plan writer (`_manifest_io`),
# the lock library (`_locks`) and the journal (`_journal_io`).
#
# What it cannot tell apart: a directory this process may not write answers with
# the same errno, so a real permission problem is refused at the deadline rather
# than at once. The cost of that is the bound, never a write.
SHARING_WAIT_SECONDS = 2.0      # the bound for a caller with no deadline of its own
SHARING_PAUSE_SECONDS = 0.02


def sharing_denied(exc):
    """True when `exc` is the refusal a name held open by another process gets.

    `EACCES` is the errno Windows maps its sharing and pending-delete refusals
    to. `EPERM` is deliberately not one: it is what a filesystem lacking the
    operation answers, and waiting cannot change that."""
    return isinstance(exc, OSError) and exc.errno == errno.EACCES


def while_shared(op, deadline=None, clock=time.monotonic):
    """`op()`'s answer, with a sharing denial retried until `deadline`.

    `deadline` is a moment on `clock`; None gives the operation
    SHARING_WAIT_SECONDS from now. Any other error propagates at once, and the
    denial propagates once the deadline has passed."""
    if deadline is None:
        deadline = clock() + SHARING_WAIT_SECONDS
    while True:
        try:
            return op()
        except OSError as exc:
            if not sharing_denied(exc) or clock() >= deadline:
                raise
        time.sleep(SHARING_PAUSE_SECONDS)


# --- naming a bounded set without hiding the rest -------------------------------
# ONE renderer for every "N things: a, b, c" line this plugin prints. `_doctor_completions`
# once told a live client repo that four tasks were
# marked done with no completion record and then named three of them. The COUNT was
# right - it always was, which is why nothing caught it - and the EVIDENCE was the
# truncated half, so the fourth name did not exist as far as that line was
# concerned. Every site with that shape carried its own hand-picked cap, so there
# was no one place to repair it and no way to keep the repair honest.
#
# THE BUDGET IS IN CHARACTERS, NOT ELEMENTS, and that is what let the caps collapse
# into one fact. The caps they came from disagreed because their elements do: a task
# id is short and a malformed manifest entry's repr is not, so an element count says
# nothing about how long the line comes out. A character budget says the thing every
# one of those caps was reaching for.
#
# THE FIRST ELEMENT IS ALWAYS SHOWN, however long it is. A budget that can drop
# everything turns a finding into a bare number, which is the same defect one step
# further along.
EVIDENCE_BUDGET = 160


def some_of(items, budget=None, sep=", ", render=None):
    """`items` rendered until `budget` is spent, then how many are NOT shown.

    Never silently short. The tail says how many were left out whenever anything
    was, so a count printed in front of this list and the list itself cannot
    disagree about how much of the set the reader is looking at — which is the
    only thing a reader needed and could not get.

    `render` is how one item becomes text: `repr` for the sites that used to hand
    a bounded list straight to `%r`, `str` otherwise.
    """
    show = render if render is not None else str
    limit = budget if budget is not None else EVIDENCE_BUDGET
    seq = list(items)
    shown, used = [], 0
    for item in seq:
        text = show(item)
        cost = len(text) + (len(sep) if shown else 0)
        if shown and used + cost > limit:
            break
        shown.append(text)
        used += cost
    left = len(seq) - len(shown)
    if left > 0:
        return "%s and %d more" % (sep.join(shown), left)
    return sep.join(shown)


# --- a finding and the rule that raised it -------------------------------------
# A validator finding is a SENTENCE to every reader that prints, joins, sorts or
# compares it, and it must stay one: the CLI, the panel, the gate and the suites all
# handle findings as strings. What the sentence cannot carry is WHICH RULE raised
# it, and a reader matching findings across runs - the invariant baseline - needs
# exactly that, because a sentence is reworded and a vocabulary it quotes grows.
#
# SO A FINDING IS A `str` WITH ONE MORE ATTRIBUTE, and that is the reason this is a
# class where the tree prefers functions: a subclass is the one shape every existing
# caller keeps reading unchanged, while the code travels with the value into the
# one reader that asks for it. Anything that rebuilds the text - concatenation,
# `%`, `.strip()` - gets a plain `str` back and the code is gone, which
# `finding_code` answers as None rather than guessing.
class Finding(str):
    """A validator finding's sentence, carrying `code`: the rule that raised it."""

    code = None


def finding(code, text):
    """The finding `text`, raised by the rule `code` - the one way one is built."""
    out = Finding(text)
    out.code = str(code)
    return out


def finding_code(line):
    """The rule code a finding carries, or None for a plain string."""
    return getattr(line, "code", None)


# --- finding the files to check ------------------------------------------------
# The directory prefix `test__loader.py` writes its depth probes into. A PREFIX,
# so `_loader_probe_a` and `_loader_probe_b` are one fact rather than two.
LOADER_PROBE_DIR = "_loader_probe"


def py_files(directory):
    """Sorted `(relname, path)` for every `.py` under `directory`, RECURSIVELY.

    The recursion is the point. Both lints below used a flat `os.listdir`, and so
    did CI's selftest glob and `_deps`' scanners — which is why `CONTRIBUTING.md`
    had to carry a rule saying `.py` must stay one directory deep: a file dropped
    into a subdirectory silently stopped being checked. The hazard was never the
    subdirectory, it was the SILENCE. A recursive walk removes the hazard instead
    of forbidding the shape, and it costs nothing today because there is no `.py`
    in a subdirectory yet — this change is a no-op on the current tree and only
    ever matters for a file somebody adds later.

    `relname` is relative to `directory` and uses forward slashes, so a violation
    in `usage/core.py` reports as `usage/core.py` rather than as a bare `core.py`
    that could be any of several files once folders exist. Today, with everything
    flat, it is exactly the basename it always was.

    Sorted so the output is stable across filesystems; `os.walk` order is not.
    """
    found = []
    for root, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            rel = posix_rel(path, directory)
            found.append((rel, path))
    found.sort()
    return found


def lint_py_files(directory):
    """`py_files` minus another suite's transient fixture.

    THE DIFFERENCE IS WHO IS ASKING. `py_files` answers "what .py files exist",
    and RESOLUTION depends on that being the whole truth: `_loader.script_index()`
    walks it, and `test__loader.py` proves depth-independent resolution with two
    files under one basename - filtering them out of `py_files` would break exactly
    that, which is why this is a separate function.

    A LINT is asking a different question: what does this repository CARRY. A pair
    of files that exists for the width of one `finally` is not carried by anyone,
    and every lint walking beside that suite reported it - `_deps`' basename
    collisions and the guide enumeration both went red on a commit that was green
    the run before, which is the signature of a race rather than a defect.

    Scoped to the probe DIRECTORIES rather than to a basename: a name-based
    exemption would also hide a real `loader_depth_probe.py` somebody committed,
    while a directory named this narrowly cannot exist for another reason.
    """
    return [(rel, path) for rel, path in py_files(directory)
            if not rel.startswith(LOADER_PROBE_DIR)
            and "/" + LOADER_PROBE_DIR not in rel]


# --- where a plugin `.py` moved to ----------------------------------------------
# `audit-task.py add` / `scope` refuse a `--files` entry naming a `.py` under the
# plugin that has moved, and `_refs.manifest_moved_files` asks the same question of
# the whole plan. They live HERE because the first is shipped and the second is
# development code: `_refs` left `scripts/` with the rest of the lint modules, and
# a shipped script importing it would have been an `ImportError` in every installed
# copy. The anchor is the one place both may reach.
PLUGIN_REL = "plugins/audit"


def py_index(repo_root, rel_root=None):
    """{basename: [repo-relative path, ...]} for every `.py` under one tree.

    Basename-keyed because that is the question a moved file poses: the recorded path
    is gone, is the FILE gone too or did it just move? `_deps` forbids two `.py`
    sharing a basename, so a list with more than one entry means the tree is broken
    in a way that lint reports by name.

    `rel_root` defaults to the plugin; `_refs.tool_basename_drift` asks the same
    question of each of its narrower trees in turn, and one walk answering for both
    is a walk that cannot drift from itself.
    """
    index = {}
    base = os.path.join(repo_root, (rel_root or PLUGIN_REL).replace("/", os.sep))
    for root, dirnames, filenames in os.walk(base):
        dirnames.sort()
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            index.setdefault(name, []).append(
                posix_rel(os.path.join(root, name), repo_root))
    return index


def is_plugin_py_path(path):
    """Whether `path` is a `.py` path under `plugins/audit/` at all - the one reading
    of "is this the plugin's business" `moved_file_target` and `_refs`'
    `manifest_moved_files` share."""
    prefix = PLUGIN_REL + "/"
    return isinstance(path, str) and path.endswith(".py") and path.startswith(prefix)


def moved_file_target(path, repo_root=None, index=None):
    """The new home `path` moved to, or None.

    None covers every reading that is NOT a move: `path` still exists there, it is
    not a plugin `.py` path (`is_plugin_py_path`), or no `.py` anywhere in the plugin
    shares its basename - a deletion, not a move, which `manifest_moved_files` files
    as `gone` rather than here.

    THE ONE READER OF THE QUESTION: `manifest_moved_files` asks it once per recorded
    path and `audit-task.py`'s `add`/`scope` once per `--files` entry about to be
    written, so a file that moved is reported the same way whether the plan already
    recorded it or an operator is about to. `index`, when given, is `py_index`'s
    map, so a caller asking about many paths builds it once.
    """
    if not is_plugin_py_path(path):
        return None
    root = repo_root if repo_root is not None else REPO_ROOT
    if os.path.isfile(os.path.join(root, path.replace("/", os.sep))):
        return None
    idx = index if index is not None else py_index(root)
    elsewhere = [p for p in idx.get(os.path.basename(path), ()) if p != path]
    return ", ".join(elsewhere) if elsewhere else None


# --- which files a surface's pictures are OF ------------------------------------
# ONE walk for the question "which parts of `scripts/ui/` does a surface assemble
# into its page", asked by whoever must report a part no surface claims. It is not
# the digest: whether a committed screenshot still shows the current UI is answered
# by `_surface_digest.py`, taken over the assembled page, because the page is what
# the picture is of and a hash over source bytes also moved when a comment did.
# That digest has to import the assembled pages, which sit above this layer, so it
# cannot live here; the walk can, and the digest asks it which parts are unplaced.
#
# DERIVED, NEVER DECLARED. Membership comes off a part's own name, so a directory
# added under `ui/` is covered the day it lands - and a name that answers nobody is
# REPORTED rather than dropped, because a part no surface's digest covers is a part
# whose change no picture can ever be red about.
UI_DIR = os.path.join(SCRIPTS_DIR, "ui")

# The surfaces `ui/` is filed by, and the same names the capture's legs push.
UI_SURFACES = ("panel", "report")

# Documentation is excluded BY SUFFIX rather than assets admitted by one: a part
# wearing an unfamiliar extension must be reported, not silently unwatched.
UI_DOC_EXT = (".md", ".txt")

# `shared/` ships in EVERY surface: `_report_ui._SCRIPT_PARTS` and
# `_panel_ui._JS_PARTS` both list its parts, ahead of every surface part.
_UI_SHARED = "shared"


def ui_surfaces_of(rel):
    """Which surfaces the `ui/` part at `rel` ships in - `()` when its name answers
    nobody.

    THE FILING CONVENTION IS THE ANSWER: `panel/`, `panel-css/`, `report/` and
    `report-css/` name their surface, the root `panel.html` names it in its stem,
    and `shared/` ships in all of them. Reading it off the name is what keeps this
    from becoming a second list of parts beside the assemblers' - the thing that
    drifts. An unknown name returning `()` rather than a guess is what makes the
    caller able to report it.
    """
    part = rel.split("/")[0].split(".")[0]
    if part == _UI_SHARED:
        return UI_SURFACES
    return tuple(s for s in UI_SURFACES if part == s or part.startswith(s + "-"))


def ui_surface_sources(scripts_dir=None):
    """`{"root": dir, "sources": {surface: [rel, ...]}, "unassigned": [...],
    "error": None|str}`.

    Sorted throughout, so a digest taken over the result is stable across
    filesystems; `os.walk` order is not. `root` is the directory this answer is
    about, returned rather than re-joined by the caller: a walk and a digest that
    each joined their own `ui/` would be a comparison between two trees.

    `error` is set and `sources` left EMPTY for anything that would otherwise be
    answered by a set that narrowed to nothing - an unwalkable tree, a tree with no
    part in it, a surface with no part of its own. All three are how a moved or
    renamed directory presents, and a digest over the remainder would be stable,
    comparable and about a tree that is not there.
    """
    root = UI_DIR if scripts_dir is None else os.path.join(scripts_dir, "ui")
    walk_errors = []
    rels = []
    # `onerror` is the guard, not a courtesy: os.walk swallows an unreadable
    # directory by default, yielding nothing and raising nothing, so a missing tree
    # would arrive as "no sources" and the digest over it would read as agreement.
    for dirpath, dirnames, filenames in os.walk(root, onerror=walk_errors.append):
        dirnames.sort()
        rel_dir = posix_rel(dirpath, root)
        prefix = "" if rel_dir == "." else rel_dir + "/"
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith(UI_DOC_EXT):
                continue
            rels.append(prefix + name)
    if walk_errors:
        return {"root": root, "sources": {}, "unassigned": [],
                "error": "cannot be walked, so which files the pictures are of is "
                         "unknown rather than unchanged: %s" % (walk_errors[0],)}
    if not rels:
        return {"root": root, "sources": {}, "unassigned": [],
                "error": "holds no assembled part at all - a candidate set that "
                         "narrowed to nothing must not be spelled the same way as "
                         "a set that agrees"}
    sources = dict((surface, []) for surface in UI_SURFACES)
    unassigned = []
    for rel in sorted(rels):
        surfaces = ui_surfaces_of(rel)
        if not surfaces:
            unassigned.append(rel)
            continue
        for surface in surfaces:
            sources[surface].append(rel)
    # A part of its OWN, not a part at all. A surface left holding only `shared/`
    # is a surface nothing assembles any more, and its digest would still compute,
    # still be stable and still be comparable - so it would go on clearing every
    # picture of a page that is gone. That is the shape a renamed surface takes.
    orphaned = [s for s in UI_SURFACES
                if not [rel for rel in sources[s] if ui_surfaces_of(rel) == (s,)]]
    if orphaned:
        return {"root": root, "sources": {}, "unassigned": unassigned,
                "error": "holds no part of its own for %s - only parts shared with "
                         "another surface - so a digest for it would stand for "
                         "nothing" % (", ".join(orphaned),)}
    return {"root": root, "sources": sources, "unassigned": unassigned,
            "error": None}


# --- the path bootstrap -------------------------------------------------------
# Two memos, keyed by a fixed string rather than by the root, because ONLY the
# default root is ever cached: a caller handing in a fixture directory must not be
# able to poison what the real tree sees, nor to read a cached answer about a
# directory it never asked about. `_loader._CACHE` is the precedent for a module
# memo here; the rule against module STATE is about values a function writes that
# another function then reads as input, which neither of these is.
_SCRIPT_FILES_CACHE = {}
_INSTALLED_CACHE = {}

_CACHE_KEY = "default root"


def script_files(refresh=False, root=None):
    """`py_files(SCRIPTS_DIR)`, walked ONCE per process and memoised.

    Every `.py` under `scripts/` runs this walk at import time through the path
    preamble, so on a run that imports twenty modules the difference between
    memoised and not is twenty `os.walk`s of the same directory. `refresh=True` is
    for the one caller that has just written or deleted a file and needs the walk
    redone — every selftest that builds a fixture tree does.

    `root` is a TEST SEAM and is deliberately NOT cached: a fixture directory must
    neither poison the real tree's memo nor read it. Pass it and you get a fresh
    `py_files` every time, which is what a case mutating a temp directory needs
    anyway.
    """
    if root is not None:
        return py_files(root)
    if refresh or _CACHE_KEY not in _SCRIPT_FILES_CACHE:
        _SCRIPT_FILES_CACHE[_CACHE_KEY] = py_files(SCRIPTS_DIR)
    return _SCRIPT_FILES_CACHE[_CACHE_KEY]


def _py_dirs(root, refresh):
    """`[root] + every subdirectory of it holding a `.py``, root first, rest sorted.

    Derived from the walk rather than from a listing, which is what makes
    `scripts/ui/` drop out on its own: it holds CSS and JS and no `.py`, so no file
    in it contributes a directory. An editorial rule ("do not put `ui/` on the
    path") becomes a mechanical one, and the day somebody adds a `.py` there it
    joins the path because it earned it, not because a constant was updated.
    """
    base = os.path.abspath(root if root is not None else SCRIPTS_DIR)
    subs = set(os.path.dirname(os.path.abspath(path))
               for _rel, path in script_files(refresh=refresh, root=root))
    subs.discard(base)
    return [base] + sorted(subs)


def plugin_version():
    """The installed plugin's version, or "" when it cannot be read.

    Lives here because BOTH surfaces stamp it and the promotion rule says two
    readers move up: the report stamps the file it rendered, the panel stamps the
    build serving the page. One reader would have stayed put.

    Best-effort by construction: a missing or malformed plugin.json costs the
    stamp and never the page. A version that cannot be read is reported as
    absent rather than as a guess, and the callers omit the stamp entirely -
    a claim with no basis is not worth printing.
    """
    try:
        path = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")
        with open(path, "r", encoding="utf-8") as fh:
            version = json.load(fh).get("version")
        return version if isinstance(version, str) and version.strip() else ""
    except Exception:
        return ""


def install_path(refresh=False, root=None):
    """Put `SCRIPTS_DIR` and every subdirectory of it holding a `.py` on `sys.path`.

    THE ROOT ALONE IS NOT ENOUGH, and that is the whole reason this is a function
    rather than one `sys.path.insert`. There are ~81 module-level sibling imports in
    this tree. Put `_areas.py` in a `manifest/` folder and `_help.py` in a `config/`
    one, and `_help`'s `import _areas` needs `scripts/manifest/` on the path — not
    `scripts/`. So every directory that holds a `.py` goes on, which is exactly what
    makes the folders LABELS AND NOT NAMESPACES: one flat name-space, every module
    reached by bare basename, and `_deps.layer_violations()`' basename-uniqueness
    rule doing the load-bearing work.

    RETURNS THE LIST IT INSTALLED — never None, never empty, and the same list on
    every call. A caller that wants to know the bootstrap ran can assert on that
    instead of asserting that some import happened to work, which is a thing that
    can be true for reasons having nothing to do with this function.

    Idempotent: a directory already on `sys.path` is left where it is rather than
    inserted a second time. Order on a fresh path is root first, then the
    subdirectories sorted — inserting in reverse at the front is what produces it.
    """
    cached = root is None and not refresh and _CACHE_KEY in _INSTALLED_CACHE
    dirs = _INSTALLED_CACHE[_CACHE_KEY] if cached else _py_dirs(root, refresh)
    if root is None:
        _INSTALLED_CACHE[_CACHE_KEY] = dirs
    for directory in reversed(dirs):
        if directory not in sys.path:
            sys.path.insert(0, directory)
    return dirs


# --- lines written LF on every platform ----------------------------------------
def write_lf_lines(lines, stream=None):
    """Write each of `lines` followed by ONE `\\n` byte, on every platform.

    `print()` on Windows emits `\\r\\n`: a text stream translates, so a list of paths
    printed that way is a list of paths in the local line-ending dialect, and a
    consumer that splits on `\\n` or pipes it through `tr` has a `\\r` glued to every
    entry. Green on ubuntu, red on windows, for a defect in neither.

    A MACHINE-READABLE LIST IS NOT PLATFORM-DEPENDENT DATA. The fix belongs at the
    producer, not in each consumer's `tr -d '\\r'`: `reconfigure(newline="")` turns
    the translation off for this write only. `safe_stdio()` is deliberately left
    alone - it runs in every script in the tree and changing what they all print to
    fix one list would be a much larger blast radius than the bug.

    A stream with no `reconfigure` (a `StringIO`, which is what a selftest capture
    installs) does not translate in the first place, so the failure to reconfigure it
    is not a failure at all. Returns the stream it wrote to, so a case can inspect
    what actually happened rather than trust that something did.
    """
    out = stream if stream is not None else sys.stdout
    try:
        out.reconfigure(newline="")
    except (AttributeError, ValueError, OSError):
        pass
    out.write("".join("%s\n" % line for line in lines))
    return out
