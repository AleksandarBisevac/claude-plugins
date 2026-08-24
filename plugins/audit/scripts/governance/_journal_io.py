#!/usr/bin/env python3
"""
The audit trail itself: reading, appending to and verifying the hash-chained record.

An append-only record of every change to the plan and the config -- dependency-free
(stdlib). `audit-journal.py` is the command around this; every subcommand it has is
an adapter onto a function here.

WHY THIS IS NOT `audit-journal.py` ANY MORE. Two modules that are not commands
needed the trail: `_help` (layer 3) normalises one row to show the reader what a
journal row looks like, and `audit-doctor` reads, verifies and lists the files.
Both reached it through `_loader`, which `_deps.layer_violations()` counts as a
real edge, so two of the seventeen entries in `KNOWN_LAYER_DEBT` were this file
being loaded as a library -- one of them by a layer-3 helper reaching up four
layers. `hooks/_config.py` loaded it too, on every tool call, to ask one question:
where does the journal live. Layer 1 is where all three can have it, and it is low
enough because nothing here reaches past `_output`.

`journal_dir` is the reason the hook cares, and the reason the module is worth
being small: a guard that runs on every Edit should not execute an argument parser
and four subcommand bodies to resolve a path.

Exit codes belong to the command, not here: `verify()` returns a dict with `ok`
and `findings`, and `audit-journal.py` turns that into 0 or 1.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__journal_io.py` -- see `plugins/audit/tests/_harness.py`.
Four of them (k5-k8) SWAP `_git_anchor_finding` for a counting stub to prove the
batched git-anchor pass is O(1 + dirty); they set it on the module object, so
renaming that function breaks them loudly rather than leaving them measuring a
call that never happened.

WHAT IT IS FOR
Until now nothing recorded WHO changed the plan, WHEN, or to WHAT. The panel wrote
the manifest, `/audit` wrote it, a hand edit wrote it, and afterwards the only
evidence was `git log` -- which says nothing at all when the manifest is not
committed, and nothing about the config, which most repos gitignore. Two questions
had no answer: "who moved this task to done?" and "has anything been changed behind
the pipeline's back?"

TAMPER-EVIDENT, NOT TAMPER-PROOF. This is the honest claim and it is worth stating
in the module that makes it. Every row carries the hash of the row before it, so
editing, deleting or reordering a row breaks the chain at that point and `verify`
names it. What it CANNOT do is stop someone rewriting the whole file: with no
secret key -- and there is nowhere on a user's machine to keep one that the same
user cannot read -- a forger who recomputes every hash forward produces a chain
that verifies. Deleting the file is the same class of act, and is deliberately
loud rather than silent: `verify` sees the rows it names go missing, and the
committed journal is a file in git history.

So the threat it addresses is the realistic one: a quiet edit, an accidental
truncation, an out-of-band write nobody meant to hide. It is a smoke detector,
not a vault. SECURITY.md says the same thing in the same words.

WHAT A ROW MAY NOT CARRY. Because the trail is COMMITTED on purpose -- the doctor
warns when it is not -- every row is a file that ships, and a row carrying a
user's home directory put machine identity into a repository that goes to clients
(CWE-532). So a command is stored as a digest, a byte length and a program name;
a cwd is stored relative to the repo or not at all; and `actor.host` is not
stored, because nothing ever read it: `verify()` does not, no surface renders it,
and `actor.sessionId` already carries the per-session identity it was decorating.
A field with a reader has a redaction question; a field with none has a deletion
answer. See the `redaction` section below for why substituting known strings was
measured and rejected.

THE CEILING ON `commandSha256`, which is the one digest here that is not a chain
link. It is UNSALTED, deliberately and unavoidably: unsalted is what makes it
useful -- "was it this command?" is answered by hashing your candidate -- and a
salt this repository could ship would be published with it, while a salt kept per
machine would be readable by the same user it hid things from. So a SHORT command
drawn from the obvious vocabulary is recoverable by anyone willing to enumerate
that vocabulary. What this does buy is that a command's ARGUMENTS -- paths, host
names, tokens, the parts that identify a person -- are never written down at all.
That is friction and data minimisation, not anonymisation, and it must not be
sold as the second.

FILE LAYOUT
    <journal dir>/<YYYY-MM>.<writerId>.jsonl        (default <manifest dir>/journal)

One file per writer per month, and the per-writer split is not cosmetic: two
sessions in two git worktrees append at the same time, and a single shared file
would conflict on every merge -- the one thing the sharded manifest layout exists
to avoid. Sitting next to the manifest, the journal is committable by the same
commit that carries the change it records.

Past months can be moved whole into `<journal dir>/archive/` by the `archive`
subcommand -- `git mv`, never a rewrite, because the chain seed is the file's
BASENAME and the hash chain survives only untouched bytes. Every reader
(verify, show, the doctor) sees archived files exactly as it sees live ones;
exactly one level deep, never a recursive walk.

ROW
    {"v", "ts", "actor": {"author", "sessionId", "via"},
     "action", "target", "summary", "stateHash", "prev", "hash"}

`hash` is sha256 over the canonical JSON of the row WITHOUT `hash`. `prev` is the
previous row's `hash`; the first row's `prev` is derived from the file's own base
name, so a file cannot be renamed into another writer's slot and still verify.
`stateHash` is the sha256 of `target` as it stood immediately after the write --
which is what lets `verify` notice a document that changed with no row to explain
it (out-of-band drift).

FAIL-SOFT BY CONTRACT. `append()` returns the path of the file the row landed in
(truthy) on success, False on failure, and never raises: a save that SUCCEEDED
must never be reported as failed because the journal was unwritable. The callers
(panel PUTs, the journal-writes hook) treat False as "not logged", never as "the
write failed" -- and the hook records the returned path in its per-session
sidecar, so guard-bash-writes can tell the plugin's own append from a shell
write into the journal (F-F3).
"""
import errno
import hashlib
import json
import os
import re
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

ROW_VERSION = 1
# A row carrying a `details` block is v2. The version names the SHAPE of one row,
# not of the file: the hash covers whatever fields are present, so v1 and v2 rows
# interleave in one file with no migration and no flag day.
DETAILS_VERSION = 2
# The command keys (P0-S) are the ones here that describe something the plugin did
# NOT do. Every other key names a field of the plan that moved; these name a Bash run
# that went around the harness sandbox, which no guard can prevent and which was
# previously invisible to every surface. They are clipped by the same
# MAX_VALUE_CHARS as any other value -- a value is evidence, not a payload, and a row
# that carried a whole script would be a log.
#
# `command` IS NOT ON THIS LIST, and its absence IS the fix rather than an omission.
# A committed row carried a shell assignment whose value was the user's home spelled
# as a directory name, which is CWE-532 in a file that is committed on purpose. An
# allow-list is the only place that closes such a channel BY CONSTRUCTION: with
# `command` off it, no writer -- this hook, the panel, `audit-task.py`, or
# `audit-journal.py --details` -- can put command text in a row, and no writer has to
# remember to filter. `command_facts()` supplies what replaces it.
DETAILS_KEYS = ("changes", "taskId", "phaseId", "field", "from", "to", "commit",
                "completedAt", "mergedAt", "fromId", "toId", "fromPhase",
                "toPhase", "truncated", "commandSha256", "commandBytes",
                "program", "cwd")
CHANGE_KEYS = ("id", "field", "from", "to")
MAX_CHANGES = 12            # a diff bigger than this is a rewrite, not an edit
MAX_VALUE_CHARS = 120       # a value is evidence, not a payload
MAX_DETAILS_BYTES = 4096    # the whole block, canonically spelled
DEFAULT_DIRNAME = "journal"
ARCHIVE_DIRNAME = "archive"
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DEFAULT_MANIFEST = "docs/audit/audit-plan.json"
GENESIS = "genesis:"
LOCK_STALE_SECONDS = 30     # after this a lock is assumed to belong to a dead writer
LOCK_WAIT_SECONDS = 2.0
_HOOKS = _output.HOOKS_DIR

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


# --- config -------------------------------------------------------------------
def _config_mod():
    """hooks/_config.py, or None. It owns the defaults; this module must not grow
    a second opinion about what `journal.enabled` means."""
    try:
        if _HOOKS not in sys.path:
            sys.path.insert(0, _HOOKS)
        import _config                                   # noqa: E402
        return _config
    except Exception:
        return None


def load_config(project):
    """The merged config for `project`. Never raises; {} if nothing is readable."""
    mod = _config_mod()
    if mod is not None:
        try:
            return mod.load(project)
        except Exception:
            pass
    try:
        with open(os.path.join(project, ".claude", "audit.config.json"),
                  "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def enabled(config):
    """`journal.enabled`, default true. A non-bool is ignored rather than trusted --
    the same rule the plan gate applies to `enforce`."""
    try:
        block = (config or {}).get("journal")
        if isinstance(block, dict) and isinstance(block.get("enabled"), bool):
            return block["enabled"]
    except Exception:
        pass
    return True


def journal_dir(project, config=None):
    """Absolute path of the journal directory.

    `journal.dir` when set, else `<manifest dir>/journal` -- derived from
    `manifestPath` rather than hardcoded, so a repo that moved its plan does not
    end up with the record of it somewhere else entirely.
    """
    config = load_config(project) if config is None else config
    block = (config or {}).get("journal")
    rel = block.get("dir") if isinstance(block, dict) else None
    if isinstance(rel, str) and rel.strip():
        return os.path.normpath(os.path.join(project, rel.strip()))
    manifest = (config or {}).get("manifestPath") or DEFAULT_MANIFEST
    return os.path.normpath(os.path.join(project, os.path.dirname(str(manifest)) or ".",
                        DEFAULT_DIRNAME))


def in_journal(project, path, config=None):
    """True when `path` (absolute or project-relative) is inside the journal dir."""
    try:
        d = os.path.realpath(journal_dir(project, config))
        p = path if os.path.isabs(path) else os.path.join(project, path)
        p = os.path.realpath(p)
        return p == d or p.startswith(d + os.sep)
    except Exception:
        return False


# --- hashing ------------------------------------------------------------------
def canonical(obj):
    """One spelling per value, so two machines hash the same row identically."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def row_hash(row):
    body = {k: v for k, v in row.items() if k != "hash"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def genesis_prev(basename):
    """The chain's anchor, derived from the file's own name.

    Without this a whole file could be copied over another writer's file and still
    verify perfectly -- every row's `prev` would still match its predecessor, and
    the substitution would be invisible."""
    return GENESIS + hashlib.sha256(str(basename).encode("utf-8")).hexdigest()


def file_hash(path):
    """sha256:<hex> of a file's bytes, or None when there is nothing to hash."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except Exception:
        return None


# --- writer identity ----------------------------------------------------------
def has_session(actor):
    """Whether `writer_id` will take the session path.

    ONE PREDICATE, ONE HOME. `_append` needs the answer before `writer_id` does,
    to avoid minting and PERSISTING a token for a writer that will never use one
    -- and asking it twice, in two spellings, is how the two come to disagree
    about which writer is which and a month's rows land in two files."""
    actor = actor if isinstance(actor, dict) else {}
    return bool(str(actor.get("sessionId") or "").strip())


WRITER_TOKEN_FILE = "writer-token.json"
_TOKEN_RE = re.compile(r"^[0-9a-f]{16}$")


def writer_token(project, config=None):
    """This checkout's stable, unguessable id for a writer with no session, or
    None when nothing could be stored.

    WHAT IT REPLACES AND WHY THAT MATTERED MOST. The fallback below used to be
    `platform.node()`, which put a laptop's name in the committed FILE NAME --
    and `genesis_prev()` seeds the chain from exactly those bytes, so unlike
    every other field a name committed there can never be corrected afterwards
    without breaking `verify()` on every clone that already holds the file. It
    is the one leak in this module with no repair path, which is why it gets
    persistent state rather than the cheapest possible constant.

    RANDOM, NOT DERIVED. Anything derived from the machine -- a hash of the host
    name, of the MAC, of the home directory -- is only as private as the input's
    search space, and those spaces are small enough to enumerate. Random bytes
    have no input to guess, and the id is not required to MEAN anything: its
    whole job is to be different from another checkout's.

    Persisted under `stateDir`, which `ensure_local_dir` makes self-ignoring on
    creation, so the token is gitignored without a consumer having to know it
    exists. Not named for a session, so the state GC (which matches session
    prefixes) leaves it alone -- a token that expired would fragment one month's
    trail into a new file each time.

    Returns None rather than a substitute when the token cannot be read OR
    written: the caller falls back to the pid, and a journal that cannot name
    its writer must still be written."""
    mod = _config_mod()
    if mod is None:
        return None
    try:
        state = mod.state_dir(mod.Path(project), config or {})
        path = os.path.join(str(state), WRITER_TOKEN_FILE)
    except Exception:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            held = json.load(fh)
        if isinstance(held, dict) and _TOKEN_RE.match(str(held.get("token") or "")):
            return str(held["token"])
    except Exception:
        pass
    minted = os.urandom(8).hex()
    try:
        mod.ensure_local_dir(state)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"token": minted}, fh)
    except Exception:
        # NOT `return minted`. An unpersisted token is a NEW writer id on the
        # next process, so a month's rows would scatter across files that each
        # look like a different machine -- which is worse than the pid form the
        # caller falls back to, and looks identical to it until somebody counts
        # the files.
        return None
    return minted


def writer_id(actor, fallback=None):
    """A file-name-safe id for the writer -- its session, else `fallback`, else
    this process's pid.

    Sanitised and truncated because it goes into a PATH: a session id is supplied
    by the caller, and a caller that can write `../../etc/passwd` into a file name
    can write outside the journal directory.

    NO I/O HERE, which is why the token arrives as an argument: this is called to
    NAME a file and it is called from a test with a literal, so reaching for
    persistent state inside it would make every case that names a writer depend
    on a directory being writable. `_append` resolves the token; `writer_token`
    explains what it is. The sessionId path is untouched -- a session id is
    already opaque, and the byte-for-byte identity of that path has a case."""
    actor = actor if isinstance(actor, dict) else {}
    if has_session(actor):
        raw = str(actor.get("sessionId")).strip()
    else:
        raw = str(fallback or "").strip() or ("writer-%d" % os.getpid())
    # Strip once BEFORE the slice (so leading rubbish does not spend the 24-char
    # budget) and once AFTER it (F-F2: a real UUID is 8-4-4-4-12, so the slice
    # ends exactly on its fourth dash, and a writer id with a trailing `-` or `.`
    # is one character away from reading as another writer's slot). The `or`
    # sits on the FINAL expression, for ids that are nothing but separators.
    safe = _SAFE.sub("-", raw).strip("-.")
    return safe[:24].strip("-.") or "writer"


def month_of(ts):
    return str(ts)[:7] if len(str(ts)) >= 7 else time.strftime("%Y-%m", time.gmtime())


def file_for(directory, ts, actor, fallback=None):
    return os.path.join(directory, "%s.%s.jsonl"
                        % (month_of(ts), writer_id(actor, fallback=fallback)))


# --- reading ------------------------------------------------------------------
def read_file(path):
    """(rows, torn). `torn` is True when the LAST line is not parseable JSON.

    A torn tail is what a crash mid-append leaves behind, and it is a different
    thing from a corrupted row: the chain up to it is intact and nothing has been
    hidden. Reported as a warning, and the rows before it still verify."""
    rows, torn = [], False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except Exception:
        return rows, torn
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            if i == len(lines) - 1:
                torn = True
                continue
            rows.append({"_unparseable": True, "_line": i + 1})
            continue
        rows.append(obj if isinstance(obj, dict) else
                    {"_unparseable": True, "_line": i + 1})
    return rows, torn


def journal_files(directory):
    """Every journal file in `directory`, plus `directory/archive/` -- exactly
    ONE level, deliberately not a walk: `archive/` is the single subdirectory
    this module itself creates (the `archive` subcommand git-mv's whole
    month-files into it), so it is the only place a journal file can
    legitimately be, and a general recursion would sweep in anything a user
    nested under the journal and make every consumer pay O(tree) for it.

    Sorted as full paths, so live files come first (a month name starts with a
    digit, `archive/` with a letter). The chain seed stays the BASENAME either
    way (see genesis_prev), which is why a `git mv` into archive/ leaves every
    chain verifying unchanged: untouched bytes under the same name."""
    try:
        out = [os.path.join(directory, n) for n in os.listdir(directory)
               if n.endswith(".jsonl")]
        arch = os.path.join(directory, ARCHIVE_DIRNAME)
        try:
            out.extend(os.path.join(arch, n) for n in os.listdir(arch)
                       if n.endswith(".jsonl"))
        except Exception:
            pass                     # no archive/ yet is the normal state
        return sorted(out)
    except Exception:
        return []


def read_all(project, config=None):
    """Every row in the journal, oldest first, each tagged with its file."""
    directory = journal_dir(project, config)
    out = []
    for path in journal_files(directory):
        rows, _torn = read_file(path)
        for r in rows:
            if r.get("_unparseable"):
                continue
            r = dict(r)
            r["_file"] = os.path.basename(path)
            out.append(r)
    out.sort(key=lambda r: (str(r.get("ts") or ""), r.get("_file") or ""))
    return out


# --- the lock around one file's tail -----------------------------------------
# Two appends by the SAME writer (a panel save while a hook fires, say) both read
# the last row for `prev`, and without this both would write the same `prev` --
# producing a break that reads exactly like a deleted row. A false tamper verdict
# is worse than a missing row, so when the lock cannot be taken the append is
# declined rather than risked.
def _acquire(path):
    lock = path + ".lock"
    deadline = time.time() + LOCK_WAIT_SECONDS
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            return lock
        except OSError as exc:
            if exc.errno not in (errno.EEXIST,):
                raise
        try:
            if time.time() - os.path.getmtime(lock) > LOCK_STALE_SECONDS:
                os.unlink(lock)         # its writer is gone; do not wait forever
                continue
        except OSError:
            pass
        if time.time() >= deadline:
            raise IOError("journal is locked by another writer: %s" % lock)
        time.sleep(0.02)


def _release(lock):
    try:
        os.unlink(lock)
    except OSError:
        pass


# --- redaction: what a committed row is allowed to say -------------------------
# EVERYTHING IN THIS SECTION RUNS BEFORE `row_hash()`, and that is not a detail of
# the ordering -- it is the only window there is. A row cannot be corrected after it
# is written without breaking the chain for every clone that already holds the file,
# so a field that leaks is a field that leaks permanently.
#
# THE OBVIOUS DESIGN IS OUT, and it was measured rather than waved away. Substituting
# known strings -- the user name, $HOME, $TMPDIR -- into placeholders is the shape
# build tooling uses for reproducible paths, and every input domain reachable here
# breaks it: a path belonging to ANOTHER project keeps its whole layout, because the
# repo prefix never fires; a user named `tmp` turns `/tmp/build` into nonsense,
# because a sequential rewriter rescans its own output; a user named `al` turns
# `npm install` into `npm inst<user>l`, because substring matching has no token
# boundary; a container with `HOME=/` rewrites every separator in the string.
#
# So the rule is: answer a STRUCTURAL question structurally -- a path either is
# inside this repo or is not, and both ends of that map are known -- refuse to store
# what has no structural answer, and leave transform knowledge (dash-joined, `%2F`,
# backslash) to the DETECTOR in `tools/check-committed-pii.py`. A detector may
# over-flag, because a human reads it; a rewriter that under-redacts says nothing at
# all, and the thing it missed is already committed.

OUTSIDE_TOKEN = "<outside-repo>"
UNNAMED_PROGRAM = "(unnamed)"
# A program name and nothing that could be a path or an assignment. The row that
# started this begins with a shell assignment whose value is an absolute path, so a
# naive "first token" summary would have put the entire leaking path into the one
# field meant to be safe. `=` and `/` are excluded for that reason, not for tidiness.
_PROGRAM_RE = re.compile(r"^[A-Za-z0-9._+-]{1,32}$")


def program_token(command):
    """The first token of `command` when it is plainly a program name, else
    `UNNAMED_PROGRAM`.

    Fails toward the safe constant, the same direction `panel-server._redact_token`
    fails in: anything the shape does not recognise is replaced rather than passed
    through, because the inputs that do not look like a program name are exactly the
    ones carrying something else."""
    text = command if isinstance(command, str) else str(command or "")
    head = text.strip().split(None, 1)[:1]
    if head and _PROGRAM_RE.match(head[0]):
        return head[0]
    return UNNAMED_PROGRAM


def command_facts(command):
    """What a row may say about a command it is no longer allowed to store.

    The digest is over the command AS RECEIVED and never over the clipped form: a
    digest of a truncated command answers a different question from the one a reader
    believes they are asking, and afterwards the two are indistinguishable. The byte
    length is the UTF-8 length for the same reason -- it is what was hashed."""
    text = command if isinstance(command, str) else str(command or "")
    raw = text.encode("utf-8")
    return {"commandSha256": hashlib.sha256(raw).hexdigest(),
            "commandBytes": len(raw),
            "program": program_token(text)}


def repo_relative_or_token(project, path):
    """`path` as a repo-relative posix path, `"."` at the root, else `OUTSIDE_TOKEN`.

    DELIBERATELY NOT `hooks/_config.within_root()`, which asks the same question and
    documents the OPPOSITE failure direction: it answers True for input it cannot
    resolve, because for a gate "I could not tell" must leave the gate where it
    already was. Here that same answer would write a raw home directory into a
    committed file, so every unresolvable, empty or outside case lands on the token.
    Same question, opposite failure direction, on purpose -- this is a note against
    somebody later noticing the resemblance and deduplicating the two back together.

    NEVER `os.path.relpath`: across Windows drives it RAISES, and a redactor that
    raises hands its caller an exception where a token was wanted. A prefix
    comparison over resolved absolute paths has no such edge.

    Case is compared EXACTLY, which is the other place the direction shows: on a
    case-insensitive volume a differently-spelled inside path is called outside and
    the row loses information, where a case-insensitive compare would have to slice
    the root off a path it only approximately matched.
    """
    if not project or not isinstance(path, str):
        # A NON-STRING IS THE TOKEN, and this is not defensive typing. `_clip`
        # spells a list or a dict canonically, so a redactor that accepted one
        # would be handed `["/Users/..."]` -- a string that is not absolute, which
        # joins onto the repo root and comes back looking repo-relative with the
        # home directory still inside it. The type is the only thing that tells
        # those apart, and only before something stringifies it.
        return OUTSIDE_TOKEN
    try:
        root = os.path.realpath(str(project))
        raw = path.replace("\\", "/")
        if not raw:
            return OUTSIDE_TOKEN
        full = os.path.realpath(raw if os.path.isabs(raw)
                                else os.path.join(root, raw))
    except Exception:
        return OUTSIDE_TOKEN
    root = root.rstrip(os.sep) or root
    if full == root:
        return "."
    if not full.startswith(root + os.sep):
        return OUTSIDE_TOKEN
    return full[len(root) + 1:].replace(os.sep, "/")


# --- details (row v2) ---------------------------------------------------------
def _clip(value):
    """One details value, bounded. Strings are truncated to MAX_VALUE_CHARS;
    scalars pass; anything structured is spelled canonically first, so the bound
    applies to what would actually be written."""
    if isinstance(value, str):
        return value[:MAX_VALUE_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    try:
        return canonical(value)[:MAX_VALUE_CHARS]
    except Exception:
        return None


def normalise_details(details, project=None):
    """The v2 `details` block: allow-listed keys only, every value bounded, the
    whole block capped. Returns None when there is nothing worth keeping -- the
    row then stays v1, which is what lets old and new rows share a file.

    An unknown key is DROPPED rather than chained in: the hash covers whatever is
    in the row, so an inventive writer would otherwise decide the format for
    every reader that comes after it -- the same rule _normalise applies to the
    row itself.

    `project` is what turns `cwd` from a machine path into a repo-relative one.
    Without it there is no map, and no map means the token: a caller that cannot
    say where the repo is does not thereby earn the right to have the raw path
    written down."""
    if not isinstance(details, dict):
        return None
    out = {}
    for key in DETAILS_KEYS:
        if key not in details:
            continue
        val = details[key]
        if key == "changes":
            if not isinstance(val, list):
                continue
            kept = []
            for change in val[:MAX_CHANGES]:
                if not isinstance(change, dict):
                    continue
                kept.append({k: _clip(change.get(k)) for k in CHANGE_KEYS
                             if k in change})
            out["changes"] = kept
            if len(val) > MAX_CHANGES:
                out["truncated"] = True
        elif key == "truncated":
            if val is True:
                out["truncated"] = True
        elif key == "cwd":
            # REDACT, THEN BOUND, and never the other way round. A clip at
            # MAX_VALUE_CHARS landing mid-path leaves a prefix of somebody's home
            # directory: still enough to identify them, no longer enough to match
            # any rule that would have caught it. Both orderings look correct in
            # review, which is why the ordering has a case of its own.
            out["cwd"] = _clip(repo_relative_or_token(project, val))
        else:
            out[key] = _clip(val)
    if "command" in details:
        # `command` is no longer in DETAILS_KEYS, so the loop above dropped it;
        # these are what a row carries in its place. Derived from the value AS
        # GIVEN -- the loop never saw it, so the digest is of the whole command
        # rather than of what a clip would have left.
        out.update(command_facts(details["command"]))
    if not out:
        return None
    try:
        if len(canonical(out).encode("utf-8")) > MAX_DETAILS_BYTES:
            n_changes = (len(details.get("changes"))
                         if isinstance(details.get("changes"), list) else 0)
            return {"truncated": True, "changes": n_changes}
    except Exception:
        return None
    return out


# --- appending ----------------------------------------------------------------
def _normalised_target(target, project):
    """`target`, with an absolute INSIDE-repo spelling collapsed to repo-relative.

    Safe here because `_append` hashes the target's bytes afterwards and both
    spellings resolve to one file, so `stateHash` is unchanged by the rewrite.

    AN ABSOLUTE OUTSIDE-REPO TARGET IS LEFT ALONE, deliberately and against the
    instinct: it is `verify()`'s drift-map KEY and `file_hash()`'s argument, so
    collapsing it to a constant would make two different files share one key and
    invent drift between them. A leak this reader can see beats a wrong answer it
    cannot, and `tools/check-committed-pii.py` reports the case instead.
    """
    text = str(target or "").strip()
    if not (project and os.path.isabs(text)):
        return text
    rel = repo_relative_or_token(project, text)
    return text if rel == OUTSIDE_TOKEN else rel


def _normalise(entry, project=None):
    """The caller supplies the news; this file owns the shape.

    A writer passing an inventive key would otherwise decide the format, and the
    hash covers whatever is in the row -- so an unknown key would be chained in and
    every reader would have to cope with it.

    It also owns what the row is allowed to SAY, which is the same argument one
    level down: a writer that could put a machine path in a committed row would be
    deciding the privacy of every repository this plugin ships into. `project` is
    what makes the path questions answerable; without it the redaction still
    happens, it just cannot resolve anything and says so."""
    entry = entry if isinstance(entry, dict) else {}
    actor = entry.get("actor")
    actor = dict(actor) if isinstance(actor, dict) else {}
    row = {
        "v": ROW_VERSION,
        "ts": str(entry.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                   time.gmtime())),
        "actor": {
            "author": actor.get("author") if isinstance(actor.get("author"), str)
            else None,
            "sessionId": str(actor.get("sessionId")) if actor.get("sessionId")
            else None,
            # NO `host`. It was written on every row and read by nothing -- not
            # by `verify()`, not by the report, not by the panel, not by the
            # doctor -- while naming the machine of whoever ran the plugin, in a
            # file that is committed on purpose. A digest was the reflex and it
            # was the wrong answer twice over: it keeps a field nobody wants, and
            # an unsalted hash of a name from a vendor's default scheme is
            # enumerable in seconds, so it would have read as protection while
            # providing nearly none. A supplied `host` is dropped like any other
            # key this shape does not know.
            "via": str(actor.get("via") or "unknown"),
        },
        "action": str(entry.get("action") or "").strip(),
        "target": _normalised_target(entry.get("target"), project),
        "summary": str(entry.get("summary") or ""),
    }
    details = normalise_details(entry.get("details"), project=project)
    if details is not None:
        row["v"] = DETAILS_VERSION
        row["details"] = details
    if not row["action"]:
        raise ValueError("a journal row must name an action")
    return row


def _append(project, entry, config=None):
    """The real append. Returns (row, path). Raises on anything that stopped
    it -- `append` is the fail-soft wrapper the writers call."""
    config = load_config(project) if config is None else config
    if not enabled(config):
        raise IOError("journal disabled (journal.enabled false)")
    row = _normalise(entry, project=project)
    directory = journal_dir(project, config)
    os.makedirs(directory, exist_ok=True)
    # The token is resolved ONLY when there is no session id, so an ordinary
    # append neither reads nor creates state it will not use.
    path = file_for(directory, row["ts"], row["actor"],
                    fallback=None if has_session(row["actor"])
                    else writer_token(project, config))

    # The state the write produced, so a later change with no row to explain it is
    # visible. Resolved against the project, since `target` is repo-relative.
    if row["target"]:
        tgt = row["target"]
        row["stateHash"] = file_hash(tgt if os.path.isabs(tgt)
                                     else os.path.join(project, tgt))
    else:
        row["stateHash"] = None

    lock = _acquire(path)
    try:
        rows, _torn = read_file(path)
        tail = [r for r in rows if not r.get("_unparseable")]
        row["prev"] = (tail[-1].get("hash") if tail
                       else genesis_prev(os.path.basename(path)))
        row["hash"] = row_hash(row)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(canonical(row) + "\n")
    finally:
        _release(lock)
    return row, path


def append(project, entry, config=None):
    """Append one row. Returns the absolute path of the file the row landed in
    (truthy) on success, False on failure, and NEVER raises -- see the module
    note: a write that succeeded must not be reported as failed because the
    record of it could not be written.

    The path, not True (F-F3): the journal-writes hook records it in a
    per-session sidecar so guard-bash-writes can tell the plugin's own append
    from a shell write into the journal. Every caller that boolean-tests the
    result is unchanged -- a non-empty path is truthy."""
    try:
        _row, path = _append(project, entry, config=config)
        return path
    except Exception:
        return False


# --- verifying ----------------------------------------------------------------
def _git_status_sets(directory):
    """One `git status --porcelain -z -uall` for a whole journal directory:
    (dirty, untracked) sets of JOURNAL-RELATIVE PATHS ("/" separators:
    "<name>" for a live file, "archive/<name>" for an archived one), or None
    when the question cannot be asked at all (no git binary, not a
    repository, git errored).

    This is F-B3's batching seam, shared with the doctor's journal-hygiene
    check: verify() used to pay `git ls-files` + `git show` per journal file,
    every file, every call -- O(files) subprocesses over a directory that is
    almost entirely tracked-and-clean. A file porcelain does not mention is
    byte-identical to HEAD, so the committed copy is a prefix of the working
    copy TRIVIALLY and the single-file primitive has nothing left to prove.
    `git show` is then paid only for tracked-but-dirty files -- the 0-2 active
    writers of the moment -- O(1 + dirty).

    Paths, not basenames (F-D-1): with archive/ the same basename can sit
    live AND archived, and under basename keys the tracked archive twin
    answered for the untracked live file -- the doctor's never-committed
    check counted both and could name the wrong one as oldest. Porcelain
    prints repo-root-relative paths, so one extra `rev-parse --show-prefix`
    (still O(1) per call) maps them onto the directory; an entry outside the
    directory is dropped -- it can never name a journal file. Rename/copy
    entries contribute both sides: a stale side costs one redundant
    single-file check and can never hide one. `-uall` so an untracked
    directory is expanded into its files rather than collapsed to one `dir/`
    line (the doctor's check needs the files). Fail-open: None means "ask
    per file", exactly the pre-batch behaviour."""
    try:
        import shutil
        import subprocess
        if not shutil.which("git"):
            return None
        pfx = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--show-prefix"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        if pfx.returncode != 0:
            return None
        prefix = (pfx.stdout or b"").decode("utf-8", "replace").strip()
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        out = subprocess.run(
            ["git", "-C", directory, "status", "--porcelain", "-z", "-uall",
             "--", "."],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        if out.returncode != 0:
            return None

        def rel(p):
            p = p.rstrip("/")
            if not prefix:
                return p
            return p[len(prefix):] if p.startswith(prefix) else None

        dirty, untracked = set(), set()
        tokens = (out.stdout or b"").decode("utf-8", "replace").split("\0")
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            i += 1
            if len(tok) < 4 or tok[2] != " ":
                continue
            xy, p = tok[:2], rel(tok[3:])
            if xy == "??":
                if p is not None:
                    untracked.add(p)
            else:
                if p is not None:
                    dirty.add(p)
                if xy[0] in ("R", "C") and i < len(tokens):
                    q = rel(tokens[i])
                    if q is not None:
                        dirty.add(q)
                    i += 1
        return dirty, untracked
    except Exception:
        return None


def _git_anchor_finding(path):
    """The git anchor: once a journal file is committed, its committed copy must
    be a byte-prefix of the working copy -- append-only ACROSS commits, which is
    what makes "rewrite the whole file and recompute every hash" detectable
    (the forger must now rewrite git history too, on every clone that has it).

    Returns the FINDING text, or None. Fail-open silently on every inability to
    check: no git binary, not a repository, an untracked file, `git show`
    erroring (tracked but not yet in HEAD) -- with one deliberate retry: a file
    in archive/ whose committed copy is not at its new path yet is anchored
    against the PRE-archive path one level up (see the comment at the seam). Line endings are normalised before
    the compare -- on Windows the working file is CRLF while an autocrlf
    checkout commits LF, and a false accusation is the one failure mode this
    check must never have."""
    try:
        import shutil
        import subprocess
        if not shutil.which("git"):
            return None
        d = os.path.dirname(os.path.abspath(path))
        name = os.path.basename(path)
        probe = subprocess.run(
            ["git", "-C", d, "ls-files", "--error-unmatch", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if probe.returncode != 0:
            return None
        shown = subprocess.run(["git", "-C", d, "show", "HEAD:./%s" % name],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=10)
        committed_at = name
        if shown.returncode != 0 or not shown.stdout:
            # The archive seam (v0.37 D): a file `git mv`ed into archive/
            # whose move is staged but NOT yet committed has no committed copy
            # at its new path -- but its committed past sits one level up, at
            # the pre-archive path, and git ls-files (the index) already
            # vouched the file is tracked. Anchoring against the parent copy
            # closes the window in which a whole-file rewrite would otherwise
            # slip between the mv and its commit. Only for a directory
            # literally named archive/ -- the one subdirectory this module
            # itself creates; everything else keeps the plain fail-open.
            if os.path.basename(d) != ARCHIVE_DIRNAME:
                return None
            shown = subprocess.run(["git", "-C", d, "show", "HEAD:../%s" % name],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, timeout=10)
            if shown.returncode != 0 or not shown.stdout:
                return None
            committed_at = "%s (its pre-archive path)" % name
        committed = shown.stdout.replace(b"\r\n", b"\n")
        with open(path, "rb") as fh:
            working = fh.read().replace(b"\r\n", b"\n")
        if not working.startswith(committed):
            return ("%s: the journal's committed past changed -- a committed "
                    "row was edited or removed (git show HEAD:%s is not a "
                    "prefix of the working copy)" % (name, committed_at))
    except Exception:
        return None
    return None


def verify(project, config=None):
    """Does the chain hold, and does the world still match its last row?

    Returns {"ok", "dir", "exists", "rows", "files": [...], "findings", "warnings"}.
    FINDINGS are breaks -- an edited row, a deleted or reordered one, a file that
    is not the file its genesis names. WARNINGS are the honest maybes: a torn tail
    (a crash, not a cover-up) and out-of-band drift (the document moved with no row
    to say why -- which is normal for anything the plugin did not write).
    """
    config = load_config(project) if config is None else config
    directory = journal_dir(project, config)
    out = {"ok": True, "dir": directory, "exists": os.path.isdir(directory),
           "rows": 0, "files": [], "findings": [], "warnings": [],
           "enabled": enabled(config)}
    if not out["exists"]:
        return out
    # F-B3: one porcelain for the whole directory decides which files pay the
    # single-file anchor check. None = git unavailable, ask per file (the
    # primitive fails open on its own); a path in neither set is tracked and
    # clean, so the committed copy equals the working copy and the prefix
    # holds trivially; untracked files are skipped for the same reason the
    # primitive skips them (no committed past = nothing to anchor to).
    # Keyed by journal-relative path (F-D-1) -- `where` below, never the
    # basename, so a live and an archived twin never answer for one another.
    status_sets = _git_status_sets(directory)
    latest = {}                    # target -> (ts, stateHash, file)
    seen_names = {}                # basename -> [journal-relative paths]
    for path in journal_files(directory):
        name = os.path.basename(path)
        # Display identity vs chain identity (v0.37 archive): `where` is the
        # journal-relative path ("archive/<name>" for an archived file), so a
        # live and an archived month can never read as one another in a report
        # -- while the GENESIS SEED below stays the basename, which is exactly
        # what lets a git-mv'd file keep verifying: untouched bytes, same name.
        where = os.path.relpath(path, directory).replace(os.sep, "/")
        seen_names.setdefault(name, []).append(where)
        rows, torn = read_file(path)
        entry = {"file": where, "rows": 0, "findings": [], "warnings": []}
        prev = genesis_prev(name)
        for i, row in enumerate(rows):
            if row.get("_unparseable"):
                entry["findings"].append(
                    "%s line %d is not valid JSON, and it is not the last line -- "
                    "a row was corrupted" % (where, row.get("_line") or (i + 1)))
                prev = None
                continue
            entry["rows"] += 1
            stored = row.get("hash")
            if not isinstance(stored, str) or stored != row_hash(row):
                entry["findings"].append(
                    "%s row %d (%s) does not hash to its own contents -- it was "
                    "edited after it was written"
                    % (where, i + 1, row.get("action") or "?"))
            elif prev is not None and row.get("prev") != prev:
                entry["findings"].append(
                    "%s row %d (%s) does not follow the row before it -- a row was "
                    "deleted, reordered, or this file was renamed"
                    % (where, i + 1, row.get("action") or "?"))
            prev = stored if isinstance(stored, str) else None
            tgt = row.get("target")
            if tgt and (tgt not in latest
                        or str(row.get("ts") or "") >= latest[tgt][0]):
                latest[tgt] = (str(row.get("ts") or ""), row.get("stateHash"),
                               where)
        if torn:
            entry["warnings"].append(
                "%s ends with a partial line -- a writer was interrupted. The rows "
                "before it are intact; nothing was hidden by it." % where)
        if status_sets is None:
            anchor = _git_anchor_finding(path)
        elif where in status_sets[0]:
            anchor = _git_anchor_finding(path)
        else:
            anchor = None
        if anchor:
            entry["findings"].append(anchor)
        out["rows"] += entry["rows"]
        out["findings"].extend(entry["findings"])
        out["warnings"].extend(entry["warnings"])
        out["files"].append(entry)

    # The same basename live AND archived: both chains verify (same genesis
    # seed), but every consumer that sums rows now counts the month twice.
    # A WARNING, not a finding -- an interrupted or hand-made copy is not
    # tampering, and the `archive` subcommand itself refuses to create this.
    for name, places in sorted(seen_names.items()):
        if len(places) > 1:
            out["warnings"].append(
                "%s exists more than once (%s) -- the same basename seeds the "
                "same chain, so its rows double-count; keep exactly one "
                "(a hand copy or an interrupted archive, never something "
                "`archive` produces)" % (name, ", ".join(places)))

    for tgt, (_ts, state, name) in sorted(latest.items()):
        if not state:
            continue
        path = tgt if os.path.isabs(tgt) else os.path.join(project, tgt)
        now = file_hash(path)
        if now is None:
            out["warnings"].append(
                "%s no longer exists, and %s records it as it was" % (tgt, name))
        elif now != state:
            out["warnings"].append(
                "%s has changed since the last row that recorded it (%s) -- an "
                "edit the journal never saw" % (tgt, name))
    out["ok"] = not out["findings"]
    return out


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio       # same dir; sys.path[0] when run directly
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_journal_io.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__journal_io.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())


