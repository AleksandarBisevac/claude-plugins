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

HOW MUCH A ROW MAY CARRY is a different question from what it may SAY, and it had
been answered on only one side. `details` is bounded three ways -- an allow-list,
a clip per value, a cap on the canonical block -- and a block that hits the cap
writes `truncated`, which sends the reader to `summary`. `summary` itself had no
bound at all, so the row pointed at a field nothing had checked. It goes through
`_clip_summary` now, and a summary that was cut SAYS it was cut: a reader cannot
otherwise tell a short sentence from a shortened one.

THE SAME SILENCE SAT ONE LEVEL DOWN. The clip per value had the bound and not the
marker, so a `details` value that was short and one that was cut read identically
-- in the one block that also sets `truncated` when it drops change entries, which
is what had taught a reader that these rows announce a cut. Both cuts go through
`_clip_marked` now and both say so in the same words; the per-value marker is
in-band and the block-level flag stays a claim about the change list, so the two
are never the same statement and cannot disagree.

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

THAT SPLIT ANSWERS "TWO WRITERS" AND NOT "TWO BRANCHES" (F306). The claim it was
sold on -- parallel work never conflicts on the journal -- holds for two writers
because they are two file names. It does not hold for ONE writer on two branches,
which is the ordinary state of a paused phase: the same name, the same month, a
shared prefix and a different tail on each side. That conflict cannot be resolved
by editing, because the divergent rows carry hashes computed over a `prev` that
only one side has, so `merge_rows` RE-CHAINS the union instead -- see the
`merging` section for why recomputing a link is not the forgery the chain exists
to catch, and for the three inputs it refuses rather than guesses at.

AND A WRITER ID IS NOT THE ID ITS SESSION KNOWS (F309). `writer_id` names the
file after the session id the WRITER supplied, and the hook that writes most rows
is handed a different id in its payload from the `$CLAUDE_CODE_SESSION_ID` the
same session reads from Bash (`hooks/_config._own_identities` measured the pair).
It is also truncated to fit a file name. So the name is opaque to the one reader
a per-session file exists for. Renaming is not the repair -- the name is the
chain's genesis seed and this trail is append-only -- so the row carries
`actor.envSessionId` when the environment names a different session, and
`session_index` reports the mapping. An opaque name stays opaque and becomes
resolvable.

Past months can be moved whole into `<journal dir>/archive/` by the `archive`
subcommand -- `git mv`, never a rewrite, because the chain seed is the file's
BASENAME and the hash chain survives only untouched bytes. Every reader
(verify, show, the doctor) sees archived files exactly as it sees live ones;
exactly one level deep, never a recursive walk.

ROW
    {"v", "ts", "actor": {"author", "sessionId", "via" [, "envSessionId"]},
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
write failed" -- and each records the returned path in a sidecar of its own
(`record_plugin_write`), so guard-bash-writes can tell the plugin's own append
from a shell write into the journal (F-F3 for the hook, F104 for the panel).
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
#
# `reason` IS on this list, and it was added on purpose rather than by reflex.
# `/audit:task cancel` and `/audit:phase cancel` both pass one, `commands/task.md`
# says the row carries it, and the allow-list dropped it in silence -- so the field
# was written, discarded, and believed by everything that read the document instead
# of the row. The three tests an addition has to pass are met here: it is a FIELD OF
# THE PLAN that moved (the sentence a cancel is justified by), not something the
# plugin observed about the machine; it is bounded like any other value by
# `MAX_VALUE_CHARS`; and it exposes nothing new, because `summary` already carries
# the same words verbatim into the same committed file. A key that fails any of
# those three does not belong here -- `command` is the standing example.
#
# `runId` IS on this list, and it passes the same three tests `reason` did. It is
# a FIELD OF THE PLAN that moved -- `task.testEvidence.runId` is a manifest key,
# not something the plugin observed about the machine; it is bounded like any
# other value by `MAX_VALUE_CHARS`; and it exposes nothing new, because the same
# id is written into the manifest this row is about. It is what lets a row in the
# committed evidence file be tied to a row in the chain without building a second
# chain to do it.
#
# `attempt` IS on this list, and it passes the same three tests. It is a FIELD OF
# THE PLAN -- `task.attempts` is a manifest key, not something the plugin observed
# about the machine; it is bounded like any other value; and it exposes nothing
# new, because the number is already in the manifest the row is about. What it is
# FOR is `/audit:task scope`, which since F271 accepts a WIDENING of `files` on a
# task that is already running: without the attempt on the row, a trail cannot
# tell a scope written before the work from one that grew during it, and every
# reader would take the second for the first. The spelling is `_evidence_io`'s
# singular `attempt` rather than the manifest's plural `attempts`, so the two
# records join on one field name instead of on two that differ by a letter.
DETAILS_KEYS = ("changes", "taskId", "phaseId", "field", "from", "to", "commit",
                "completedAt", "mergedAt", "fromId", "toId", "fromPhase",
                "toPhase", "reason", "truncated", "commandSha256", "commandBytes",
                "program", "cwd", "runId", "attempt")
CHANGE_KEYS = ("id", "field", "from", "to")
MAX_CHANGES = 12            # a diff bigger than this is a rewrite, not an edit
MAX_VALUE_CHARS = 120       # a value is evidence, not a payload
MAX_DETAILS_BYTES = 4096    # the whole block, canonically spelled
# `summary` was the one field of a row with no bound at all, while the `details`
# block beside it has three of them: an allow-list, a clip per value, and a cap on
# the whole block. The asymmetry was not merely untidy -- a `details` that hits its
# cap writes `truncated` and sends the reader to the summary, so a row was
# promising a fallback nothing had ever checked. A phase cancel is the case that
# made it concrete: its summary names every task the cancel cascaded to, and a wide
# phase writes every one of them into a file that is committed on purpose.
#
# NOT A LEAK, which is why this is a BOUND and not a redaction: a task id names
# neither a machine nor a person, and `_normalised_target`/`repo_relative_or_token`
# already own the questions that are about privacy. `MAX_VALUE_CHARS` is
# deliberately not reused for it -- a details value is one piece of evidence, while
# the summary is the whole sentence `audit-journal list` prints, and clipping it to
# a value's length would cut ordinary summaries that were never the problem.
MAX_SUMMARY_CHARS = 400
# ...AND A CUT SUMMARY SAYS SO. Every other bound in a row leaves something beside
# it that names the cut (`truncated` next to a shortened `changes` list); a summary
# is one string with nothing beside it, so a short one and a cut one would read
# identically -- a claim whose basis is missing, which is the failure this repo
# repeats most. The marker is spent OUT OF the bound rather than added on top of
# it, so `MAX_SUMMARY_CHARS` stays a fact about the field that a reader can measure
# instead of an approximation the marker pushes past.
SUMMARY_TRUNCATED = " [truncated]"
# ...AND SO DOES A CUT VALUE, in the same words and out of the same literal. `_clip`
# had been shortening a `details` value in silence, which inside THIS block is worse
# than it would be anywhere else: a change LIST that gets cut writes `truncated`
# beside itself, so a reader of these rows has already been taught that this row
# type announces a cut -- and then a value the clip shortened said nothing at all,
# leaving a short value and a shortened one identical in a file that is committed
# on purpose.
#
# IN-BAND, AND DELIBERATELY NOT A SECOND `truncated`. The block-level flag is a
# claim about the change LIST (or about the whole block hitting its cap); a marker
# inside one value is a claim about THAT VALUE. Spelling the second one as a key
# would make one word answer two questions, and a reader could no longer tell
# "entries were dropped" from "one string was shortened". The two cannot
# contradict each other because they are never the same statement.
#
# ONE LITERAL, TWO NAMES. The words are one fact -- how a cut in a committed row
# announces itself -- and each bound keeps a name that says which field it guards.
# The alias is what stops the two spellings drifting the way two copies of a string
# do; giving a value a different marker later means breaking this line on purpose,
# which is exactly the review that change deserves.
VALUE_TRUNCATED = SUMMARY_TRUNCATED
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


ENV_SESSION_VAR = "CLAUDE_CODE_SESSION_ID"
MAX_SESSION_ID_CHARS = 64       # a uuid is 36; longer than this is not an id


def env_session_id():
    """The session id in THIS PROCESS'S ENVIRONMENT, or None.

    A SESSION HAS MORE THAN ONE NAME, and that is the whole reason this exists
    (F309). Bash reads `$CLAUDE_CODE_SESSION_ID`; a hook is handed a DIFFERENT
    `session_id` in its payload, and `hooks/_config._own_identities` measured the
    pair in a live session rather than assuming they agree. The journal names its
    file after the id the writer supplied, so the hook that writes most rows
    names files after the payload id -- and a reader looking for the id their
    session knows finds no file by that name.

    WHY THIS IS A ROW AND NOT A RENAME. The file name is the chain's genesis seed
    (`genesis_prev`) and the trail is append-only, so a name cannot be corrected
    afterwards without breaking `verify` on every clone that already holds the
    file. Recording the other id is the repair that adds rather than rewrites,
    and a writing process is the only place both ids are visible at once: a hook
    subprocess inherits the environment its parent read.

    Sanitised and bounded because it lands in a committed row. It exposes nothing
    `actor.sessionId` does not already expose -- both are opaque per-session ids,
    neither names a machine -- and anything that is not that shape is dropped
    rather than substituted for."""
    raw = os.environ.get(ENV_SESSION_VAR) or ""
    safe = _SAFE.sub("-", str(raw).strip()).strip("-.")
    return safe[:MAX_SESSION_ID_CHARS].strip("-.") or None


def month_of(ts):
    return str(ts)[:7] if len(str(ts)) >= 7 else time.strftime("%Y-%m", time.gmtime())


def file_for(directory, ts, actor, fallback=None):
    return os.path.join(directory, "%s.%s.jsonl"
                        % (month_of(ts), writer_id(actor, fallback=fallback)))


# --- the plugin's own appends, declared to the guard (F-F3) -------------------
# An append puts a journal file into `git status`, and `guard-bash-writes` used to
# blame whatever shell command ran next. The fix is a sidecar naming the files the
# plugin itself wrote, which that guard subtracts before it reads the journal
# class. `journal-writes.py` has written one per SESSION since F-F3; the panel
# server is the plugin's other journal writer and is not a session at all, so it
# needs the same claim under a key of its own (F104).
#
# THIS IS THE SHARED HOME FOR THAT WRITE, and `journal-writes.py` still carries its
# own copy of it -- a hook may not import from `scripts/`, but it already loads
# THIS module (`_config._load_journal_lib`) to append at all, so it can be
# collapsed onto these two functions without gaining an edge. Until it is, the
# agreement between the two spellings is pinned by a case rather than asserted by
# a comment: a copy with a comment saying it is a copy is still a copy.
#
# `guard-bash-writes` reads these files and CANNOT share the derivation, because a
# hook importing `scripts/` is the one edge the layer rule forbids outright. Its
# reader is driven against this writer by a case for the same reason.
PLUGIN_WRITE_SIDECAR = "bash-writes-plugin-%s.json"
PLUGIN_WRITE_KEY = "pluginWrote"
MAX_WRITER_KEY_CHARS = 40

# The fixed key every CLI writer files under, mirrored in `guard-bash-writes` as
# `CLI_WRITER` (F287). A script run from Bash is handed no session id -- the id
# reaches a hook on its stdin payload and reaches argv nowhere -- so it cannot use
# the per-session slot `journal-writes.py` writes, and a key per process would
# fragment the claim exactly as it would have fragmented the panel's. One key for
# all of them is the shape the panel's own key already established.
CLI_JOURNAL_WRITER = "cli"


def plugin_write_sidecar(project, config, writer):
    """`<stateDir>/bash-writes-plugin-<writer>.json`, or None when there is no
    state directory to resolve it against.

    `stateDir` and not the journal directory: the claim is local, per-checkout
    scratch that ages out with the rest of the session state (the `bash-writes-`
    prefix is in `detect-plan-skip`'s GC tuple), while the journal is the
    opposite kind of artifact and stays tracked.

    Sanitised and clipped the way a session id is, because `writer` names a FILE
    and a caller that can write a separator into it can write outside the state
    directory."""
    mod = _config_mod()
    if mod is None:
        return None
    key = _SAFE.sub("-", str(writer or "")).strip("-.")[:MAX_WRITER_KEY_CHARS]
    key = key.strip("-.")
    if not key:
        return None
    try:
        state = mod.state_dir(mod.Path(project), config or {})
    except Exception:
        return None
    return os.path.join(str(state), PLUGIN_WRITE_SIDECAR % key)


def record_plugin_write(project, config, writer, path):
    """Note that `writer` -- a part of this plugin -- appended to journal file
    `path`. Returns the slot it wrote, or None. Never raises.

    ONE WRITER PER SLOT is the whole safety argument, and it is why `writer` is a
    parameter rather than a constant: hooks registered on one event run in
    parallel, so the session's slot and the panel's slot must be different files.
    Two writers on one slot would lose an entry, and a lost entry is a shell
    command blamed for the plugin's own append -- the fault this exists to close.

    The path is stored repo-relative, because that is the only spelling the guard
    can compare against a `git status` line."""
    mod = _config_mod()
    slot = plugin_write_sidecar(project, config, writer)
    if mod is None or slot is None or not path:
        return None
    try:
        rel = mod.rel_path(project, str(path))
    except Exception:
        return None
    wrote = []
    try:
        with open(slot, "r", encoding="utf-8") as fh:
            held = json.load(fh)
        if isinstance(held, dict) and isinstance(held.get(PLUGIN_WRITE_KEY), list):
            wrote = [str(x) for x in held[PLUGIN_WRITE_KEY]]
    except Exception:
        pass                     # no slot yet is the normal first-append state
    if rel in wrote:
        return slot
    wrote.append(rel)
    try:
        mod.ensure_local_dir(os.path.dirname(slot))
        with open(slot, "w", encoding="utf-8") as fh:
            json.dump({PLUGIN_WRITE_KEY: wrote}, fh)
    except Exception:
        return None
    return slot


# --- reading ------------------------------------------------------------------
def rows_from_text(text):
    """(rows, torn) for the CONTENTS of a journal file -- `read_file` over a path.

    SPLIT OUT BECAUSE TWO CALLERS DO NOT HAVE A PATH. The git anchor compares the
    working copy against `git show HEAD:<file>`, which arrives as bytes and never
    as a file, and `merge_rows` is handed rows a caller already read. Both need
    the SAME torn-tail rule and the same unparseable-row marker as a live read,
    and a second parser is how the anchor would come to disagree with `verify`
    about what a row even is."""
    rows, torn = [], False
    lines = str(text).splitlines()
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


def read_file(path):
    """(rows, torn). `torn` is True when the LAST line is not parseable JSON.

    A torn tail is what a crash mid-append leaves behind, and it is a different
    thing from a corrupted row: the chain up to it is intact and nothing has been
    hidden. Reported as a warning, and the rows before it still verify.

    An unreadable file is `([], False)` and not an exception: this is the read
    every consumer makes of every file it finds, and a directory listing that
    raced a `git mv` must not take `verify` down."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return [], False
    return rows_from_text(text)


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


def writer_of(basename):
    """The writer id a journal file's NAME carries, or "" when it carries none.

    `<YYYY-MM>.<writerId>.jsonl`, so the writer is everything between the first
    dot and the extension -- a session id may itself contain dots, which is why
    this partitions from the LEFT once and strips the suffix, rather than
    splitting on every dot and taking a field by number."""
    stem = basename[:-len(".jsonl")] if basename.endswith(".jsonl") else basename
    _month, _dot, wid = stem.partition(".")
    return wid


def _counted(values):
    """[(value, times)] for a list, most-seen first then alphabetically.

    A TOTAL ORDER BEFORE ANYTHING SERIALISES IT: a dict's key order varies per
    process, and this list is printed and JSON-dumped, so two runs over one
    journal would otherwise differ in the noise instead of in the news."""
    seen = {}
    for value in values:
        seen[value] = seen.get(value, 0) + 1
    return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))


def session_index(project, config=None):
    """Which session wrote which journal file -- the mapping a file NAME cannot
    carry (F309).

    Returns {"dir", "exists", "env", "files": [...], "mine": [names],
    "unmapped": [names]}, each file entry {"file", "writer", "rows", "first",
    "last", "sessionIds", "envSessionIds", "mine"}.

    WHAT MAKES A FILE "MINE" is asked through `writer_id`, the same function that
    NAMED the file, rather than by comparing prefixes here: the name is a
    sanitised 24-character slice of a session id, and a second opinion about how
    that slice is taken is how a report comes to disagree with the writer about
    which file is whose.

    `unmapped` is the honest gap and is reported rather than left as silence. A
    file whose rows carry no `envSessionId` is EITHER a file whose writer read
    the same id from its environment OR a file written before the field existed,
    and nothing here can tell those apart -- so it says both instead of implying
    the first."""
    config = load_config(project) if config is None else config
    directory = journal_dir(project, config)
    env = env_session_id()
    env_writer = writer_id({"sessionId": env}) if env else None
    out = {"dir": directory, "exists": os.path.isdir(directory), "env": env,
           "files": [], "mine": [], "unmapped": []}
    for path in journal_files(directory):
        where = _output.posix_rel(path, directory)
        rows, _torn = read_file(path)
        rows = [r for r in rows if not r.get("_unparseable")]
        sids, esids, stamps = [], [], []
        for row in rows:
            actor = row.get("actor") if isinstance(row.get("actor"), dict) else {}
            if actor.get("sessionId"):
                sids.append(str(actor["sessionId"]))
            if actor.get("envSessionId"):
                esids.append(str(actor["envSessionId"]))
            if row.get("ts"):
                stamps.append(str(row["ts"]))
        writer = writer_of(os.path.basename(path))
        known = set(sids) | set(esids)
        mine = bool(env) and (env in known or writer == env_writer)
        entry = {"file": where, "writer": writer, "rows": len(rows),
                 "first": min(stamps) if stamps else None,
                 "last": max(stamps) if stamps else None,
                 "sessionIds": _counted(sids), "envSessionIds": _counted(esids),
                 "mine": mine}
        out["files"].append(entry)
        if mine:
            out["mine"].append(where)
        if not esids:
            out["unmapped"].append(where)
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

    NEVER `os.path.relpath` HERE: this function takes a path from anywhere - a
    payload, a config, another drive - and across Windows drives `relpath` RAISES,
    so a redactor built on it hands its caller an exception where a token was
    wanted. A prefix comparison over resolved absolute paths has no such edge.

    SCOPED TO THIS FUNCTION, and it did not used to be. Written as a flat "never",
    it read as a rule about the module and was already false one function over:
    `verify_dir` derives a journal-relative `where` with `relpath`, legitimately,
    because both sides come from one directory walk and cannot be on two drives.
    A rule stated wider than it holds is the kind a later reader either obeys
    where it costs something or disbelieves where it matters.

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
def _clip_marked(text, limit, marker):
    """`text` bounded to `limit`, SAYING SO when it had to be cut.

    ONE RULE, BOTH BOUNDS. A `summary` and a `details` value are held to different
    budgets -- a value is one piece of evidence, a summary is the whole sentence
    `audit-journal list` prints -- but a cut announces itself identically in both,
    and the caller passes the pair so each call site still names the constant a
    reader can go and measure.

    The marker is spent OUT OF `limit` rather than added on top of it, so the bound
    stays a fact about the field instead of an approximation the marker pushes
    past.

    Returns the text unchanged when it fits, so the overwhelming majority of rows
    hash exactly as they did before either bound existed; only text that was
    already past its bound changes at all.
    """
    if len(text) <= limit:
        return text
    return text[:limit - len(marker)] + marker


def _clip(value):
    """One details value, bounded -- and saying so when it had to be cut.

    Strings are held to MAX_VALUE_CHARS; scalars pass; anything structured is
    spelled canonically first, so the bound applies to what would actually be
    written -- and so does the marker, which is the half that used to be missing:
    a canonical spelling cut mid-brace is not JSON any more and had nothing on it
    to say why."""
    if isinstance(value, str):
        return _clip_marked(value, MAX_VALUE_CHARS, VALUE_TRUNCATED)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    try:
        return _clip_marked(canonical(value), MAX_VALUE_CHARS, VALUE_TRUNCATED)
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
def _clip_summary(text):
    """The row's `summary`, bounded -- and saying so when it had to be cut.

    A one-line adapter onto `_clip_marked` so the field keeps a named home the
    row builder and its cases can point at; the rule it applies is shared with
    every `details` value one level down."""
    return _clip_marked(text, MAX_SUMMARY_CHARS, SUMMARY_TRUNCATED)


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
    happens, it just cannot resolve anything and says so.

    AND HOW MUCH IT MAY SAY: `summary` goes through `_clip_summary` here, the same
    way every `details` value goes through `_clip` one level down. It is the last
    field of the row that a caller could have used to write a payload into a
    committed file, and it was the field a truncated `details` block points at."""
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
        "summary": _clip_summary(str(entry.get("summary") or "")),
    }
    # F309: the OTHER name this session answers to, recorded ONLY when it is not
    # the one already above. A hook's payload `session_id` is what names the
    # file; `$CLAUDE_CODE_SESSION_ID` is what the session calls itself, and
    # without one row tying the two together no reader can group a session's
    # rows by the id they have. Absent means "the environment named no other
    # session" -- which is also what every row written before this field means,
    # and `session_index` says so rather than letting silence read as agreement.
    env_sid = env_session_id()
    if env_sid and env_sid != row["actor"]["sessionId"]:
        row["actor"]["envSessionId"] = env_sid
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


def append_from_cli(project, entry, config=None):
    """`append`, plus the claim a plugin script run from Bash owes the write
    guard (F287). Same return contract as `append`: the path, or False.

    WHAT NOT CLAIMING COSTS is a notice about the plugin's own write. An append
    puts a journal file into `git status`, and `guard-bash-writes` reports an
    unclaimed journal file as a shell write into the append-only trail -- so
    running `commit-audit-state.py` made the NEXT Bash command draw "that shell
    command wrote into the append-only audit journal", with `audit-journal.py
    verify` reporting the chain clean behind it. Nothing was broken and only a
    manual check could say so, which is the worst shape a warning takes.

    NOT A PATH EXEMPTION, and that is the design rather than an implementation
    detail: the guard subtracts the files a writer CLAIMED and never the journal
    directory, because a journal write nothing claims is the `sed`-shaped write
    the guard exists for. Exempting the path would delete the guard.

    THE CONFIG IS RESOLVED ONCE and handed to both halves. The claim's slot is
    `stateDir`-relative, so letting `append` load one config while the claim
    loaded another would file the claim where the guard is not looking -- silence
    dressed as evidence, and invisible from either side.

    Fail-soft on the claim by `append`'s own contract: a row that WAS written must
    not be reported as unwritten because the claim could not be left."""
    config = load_config(project) if config is None else config
    path = append(project, entry, config=config)
    if path:
        record_plugin_write(project, config, CLI_JOURNAL_WRITER, path)
    return path


# --- merging ------------------------------------------------------------------
# WHY RE-CHAINING IS NOT THE FORGERY THE CHAIN EXISTS TO CATCH, said here because
# it is the one question this section has to answer before any of it is allowed to
# run. Three things are true of it and none is true of a forgery:
#
#   1. NO ROW'S CONTENT CHANGES. `_rechain` carries every field of every row
#      through byte for byte and recomputes exactly two: `prev` and `hash`. Those
#      are LINKS -- they say where a row sits in a chain, not what happened -- and
#      `row_content()` is the unit that must survive, which is also the unit
#      `anchor_verdict()` checks across a commit. A forgery changes what a row
#      SAYS and recomputes the links to cover it; this changes only the links, and
#      the committed content of every row is still checkable afterwards.
#   2. NOTHING IS DROPPED AND NOTHING IS REORDERED. The output is the UNION of the
#      two inputs, each side's own recorded order preserved (`_merge_tails` is a
#      merge, never a sort), and where timestamp order cannot decide between two
#      rows the operation REFUSES instead of picking one.
#   3. BOTH INPUTS ARE IN GIT. A journal divergence is a merge conflict, so the
#      two sides are two commits that a reviewer can read, and the merge commit
#      holds both parents. The operation is auditable in the one place a rewrite
#      of history would have to be audited anyway.
#
# WHAT MADE IT NECESSARY (F306). One writer on two branches is ordinary while a
# phase is paused, and the per-writer file split does not separate them: same
# name, same month, a shared prefix and a different tail on each side. Nothing can
# resolve that by editing, because each divergent row's hash covers a `prev` only
# its own side has -- so the alternative to a merge verb is what actually happened,
# which is a resolution that keeps one tail and loses the other in a second parent
# nobody reads again.
MERGE_ACTION = "journal.merge"
MERGE_VIA = "merge"


def row_content(row):
    """The row's CONTENT: every field except the two link fields.

    THE UNIT NOTHING MAY CHANGE. `prev` and `hash` place a row in a chain;
    everything else is what the row says happened. A merge recomputes the first
    two and never the rest, and `anchor_verdict()` asks its question in exactly
    this unit -- one definition, so the writer and the verifier cannot disagree
    about what "the same row" means."""
    return canonical({k: v for k, v in row.items()
                      if k not in ("prev", "hash")})


def _merge_input_faults(rows, torn, side, name):
    """Every reason `side` cannot be an input to a merge, as refusal text.

    REFUSING AN ALREADY-BROKEN INPUT IS THE POINT, not defensiveness. Re-chaining
    recomputes `hash` over whatever content it is handed, so a row that does not
    hash to its own contents on the way IN comes out hashing perfectly -- the
    merge would have laundered an edited row into a chain that verifies, which is
    the one thing this trail must never do on purpose. Say the input was already
    broken and stop.

    A TORN TAIL IS REFUSED HERE AND ONLY WARNED ABOUT BY `verify`, and the two are
    not in conflict: a partial line is not a row, so `verify` can honestly say the
    rows before it are intact, while a merge that read past it would drop those
    bytes with nothing in the output to say they were ever there."""
    out = []
    if torn:
        out.append("%s ends with a partial line -- a writer was interrupted "
                   "there. Those bytes are not a row, so a merge would drop "
                   "them and say nothing; truncate the partial line on purpose "
                   "first if that is what you mean." % (side,))
    if not rows:
        out.append("%s holds no rows at all, so there is nothing to merge with "
                   "-- a side with no rows is not a divergence" % (side,))
        return out
    for i, row in enumerate(rows):
        if row.get("_unparseable"):
            out.append("%s line %d is not valid JSON -- the input was already "
                       "broken and a merge will not launder it"
                       % (side, row.get("_line") or (i + 1)))
            continue
        stored = row.get("hash")
        if not isinstance(stored, str) or stored != row_hash(row):
            out.append("%s row %d (%s) does not hash to its own contents -- it "
                       "was edited after it was written, so the input was "
                       "already broken. Re-chaining would recompute that hash "
                       "and hide it; nothing here will do that."
                       % (side, i + 1, row.get("action") or "?"))
    if out:
        return out
    first = str(rows[0].get("prev") or "")
    if first != genesis_prev(name):
        out.append("%s does not begin at the genesis of %r -- its first row's "
                   "`prev` is %r, and a chain seeded from that name would start "
                   "%r. Either this is a fragment rather than a whole file, or "
                   "it belongs under another name."
                   % (side, name, first, genesis_prev(name)))
    return out


def _common_prefix(ours, theirs):
    """How many leading rows the two sides SHARE, compared by hash.

    The hash is the right identity for this: it covers the row's content AND its
    `prev`, so two rows with equal hashes have equal content and equal history
    behind them. Comparing content alone would call two rows shared that sit on
    different pasts."""
    shared = 0
    for mine, yours in zip(ours, theirs):
        if mine.get("hash") != yours.get("hash"):
            break
        shared += 1
    return shared


def _tie_faults(ours_tail, theirs_tail):
    """(refusals, identical) for rows the two tails place at the SAME timestamp.

    WHY A TIE IS A REFUSAL AND NOT A COIN TOSS. Timestamp order is the only order
    a merge has -- the chain order of each tail is real but the two tails have no
    order BETWEEN them -- so two rows the timestamps cannot separate have no
    recorded order at all, anywhere. Picking one is inventing a history, and the
    invention is invisible afterwards because the output verifies either way.

    A TIE WITH IDENTICAL CONTENT IS NOT REFUSED and is not deduplicated either.
    Both copies are kept, because dropping one is a guess that two rows saying the
    same thing at the same second were one event, and the union of two files is
    the one answer that guesses nothing. The count is returned so the caller can
    say it out loud rather than leave it to be discovered.

    CROSS-SIDE ONLY. Two rows within one tail sharing a timestamp are already in a
    recorded order that the chain fixes, and this must not disturb it."""
    ours_at, theirs_at = {}, {}
    for row in ours_tail:
        ours_at.setdefault(str(row.get("ts") or ""), []).append(row_content(row))
    for row in theirs_tail:
        theirs_at.setdefault(str(row.get("ts") or ""), []).append(row_content(row))
    refusals, identical = [], 0
    for stamp in sorted(set(ours_at) & set(theirs_at)):
        mine, yours = sorted(ours_at[stamp]), sorted(theirs_at[stamp])
        if mine == yours:
            # Both sides' rows, because both are KEPT: a count of one side would
            # under-report what the note is about by half.
            identical += len(mine) + len(yours)
            continue
        refusals.append(
            "both copies carry a row at %s and they do not say the same thing, "
            "so nothing records which came first: one side has %s, the other "
            "has %s. Timestamp order is the only order a merge has, and it "
            "cannot separate these -- resolve it by hand rather than letting "
            "this pick one."
            % (stamp or "(no timestamp)",
               _output.some_of([_summarise_row(c) for c in mine]),
               _output.some_of([_summarise_row(c) for c in yours])))
    return refusals, identical


def _summarise_row(content):
    """`action(target)` for one canonical row content -- what a refusal names it by.

    Deliberately NOT the whole row: a refusal is read in a terminal, and the two
    fields that tell a reader which write they are looking at are the action and
    what it touched."""
    try:
        obj = json.loads(content)
    except Exception:
        return "(unreadable row)"
    return "%s(%s)" % (obj.get("action") or "?", obj.get("target") or "")


def _merge_tails(ours, theirs):
    """The two tails interleaved by timestamp, each side's OWN order preserved.

    A MERGE AND NEVER A SORT, and the difference is the whole guarantee. A sort
    keyed on `ts` would reorder a side against itself the moment its own rows are
    not in timestamp order -- which a caller-supplied `ts` allows and the archive
    cases in this suite's neighbour actually do -- and reordering a recorded chain
    is the failure this verb exists to avoid. Two pointers can only ever advance,
    so each side comes out in exactly the order it went in.

    A tie takes from `ours` first. That is safe rather than arbitrary because a
    tie whose contents differ was already refused by `_tie_faults`: the only ties
    reaching here say the same thing, so the two orders are the same reading."""
    out, i, j = [], 0, 0
    while i < len(ours) and j < len(theirs):
        if str(theirs[j].get("ts") or "") < str(ours[i].get("ts") or ""):
            out.append(theirs[j])
            j += 1
        else:
            out.append(ours[i])
            i += 1
    out.extend(ours[i:])
    out.extend(theirs[j:])
    return out


def _rechain(rows, name):
    """(rows, relinked): `rows` with `prev` and `hash` recomputed from `name`'s
    genesis forward, and how many rows that actually moved.

    `relinked` is MEASURED rather than assumed to be "everything after the
    divergence": the first row of a tail sits on the same `prev` it always had, so
    its hash is unchanged, and a caller that reported the whole tail as re-linked
    would be overstating what it did."""
    out, prev, relinked = [], genesis_prev(name), 0
    for row in rows:
        fresh = {k: v for k, v in row.items() if k not in ("prev", "hash")}
        fresh["prev"] = prev
        fresh["hash"] = row_hash(fresh)
        if fresh["hash"] != row.get("hash"):
            relinked += 1
        prev = fresh["hash"]
        out.append(fresh)
    return out, relinked


def _merge_marker(rows, name, actor, counts):
    """The row a merge leaves IN the file it merged, or None when there is nothing
    to record.

    THE FILE SAYS WHAT WAS DONE TO IT. Re-chaining is defensible only because it
    is auditable, and "read the merge commit" is a weaker answer than a row in the
    trail itself. Built through `_normalise` rather than by hand so the row shape
    has one home -- this is a journal row like any other, and a merge writing its
    own private shape would be the second opinion this module is arranged against.

    Its timestamp is the LATEST of now and the last row's, so the marker can never
    land before the rows it describes on a machine whose clock disagrees with the
    one that wrote them."""
    if not rows:
        return None
    latest = max([str(r.get("ts") or "") for r in rows] or [""])
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    marker = _normalise({
        "action": MERGE_ACTION, "target": "",
        "ts": latest if latest > now else now,
        "summary": ("re-chained %d row(s) of %s after a divergence: %d shared, "
                    "%d from one copy, %d from the other. Row contents "
                    "unchanged; only `prev`/`hash` recomputed. Inputs %s / %s."
                    % (len(rows), name, counts["shared"], counts["oursOnly"],
                       counts["theirsOnly"], counts["oursDigest"],
                       counts["theirsDigest"])),
        "actor": actor if isinstance(actor, dict) else {"via": MERGE_VIA}})
    marker["stateHash"] = None
    return marker


def merge_rows(ours, theirs, name, actor=None, torn=()):
    """The UNION of two divergent copies of ONE journal file, re-chained.

    `ours` and `theirs` are row lists as `read_file`/`rows_from_text` return them;
    `name` is the basename the chain is seeded from (`genesis_prev`), which is why
    the output has to be written back under that name and nowhere else. `torn`
    names the sides whose last line was partial. Returns

        {"ok", "refusals", "notes", "rows", "shared", "oursOnly", "theirsOnly",
         "relinked", "divergent", "identical", "name"}

    and `rows` is EMPTY whenever `ok` is false -- a refusal never also hands back
    a half-built answer for a caller to use by accident.

    EVERY PRECONDITION IS CHECKED BEFORE THE FIRST ROW IS RE-CHAINED, which is not
    a style choice here: the refusals are the whole value of the verb, and a
    validation interleaved with the work is a validation that can be reached with
    half the output already built.

    THE THREE REFUSALS IT EXISTS FOR, each with its own case next door:
      * a row that does not hash to its own contents (`_merge_input_faults`) --
        the input was already broken and re-chaining would hide it;
      * two rows at one timestamp saying different things (`_tie_faults`) --
        nothing records which came first;
      * no shared prefix at all -- two files that never had a common past are not
        a divergence, and unioning them would invent a history for both.

    NO DIVERGENCE IS A LEGITIMATE ANSWER, not an error: when one side's rows are a
    prefix of the other's, the longer side already contains every row of the
    shorter one, `relinked` is 0 and no marker row is added. There is nothing to
    re-chain and nothing to record about having done so."""
    refusals = list(_merge_input_faults(ours, "ours" in torn, "ours", name))
    refusals.extend(_merge_input_faults(theirs, "theirs" in torn, "theirs", name))
    out = {"ok": False, "refusals": refusals, "notes": [], "rows": [],
           "shared": 0, "oursOnly": 0, "theirsOnly": 0, "relinked": 0,
           "divergent": False, "identical": 0, "name": name}
    if refusals:
        return out
    shared = _common_prefix(ours, theirs)
    out["shared"] = shared
    if not shared:
        out["refusals"].append(
            "the two copies share no leading row at all, so this is not one "
            "file that diverged -- it is two unrelated chains. Their first rows "
            "are %s and %s. A union of those would invent a common past for "
            "both." % (_summarise_row(row_content(ours[0])),
                       _summarise_row(row_content(theirs[0]))))
        return out
    ours_tail, theirs_tail = ours[shared:], theirs[shared:]
    out["oursOnly"], out["theirsOnly"] = len(ours_tail), len(theirs_tail)
    undated = [r for r in ours_tail + theirs_tail if not str(r.get("ts") or "")]
    if undated:
        out["refusals"].append(
            "%d divergent row(s) carry no timestamp, and timestamp order is the "
            "only order a merge has between the two copies -- there is nowhere "
            "to put them: %s"
            % (len(undated),
               _output.some_of([_summarise_row(row_content(r))
                                for r in undated])))
        return out
    ties, identical = _tie_faults(ours_tail, theirs_tail)
    out["identical"] = identical
    if ties:
        out["refusals"].extend(ties)
        return out
    if not ours_tail or not theirs_tail:
        # One side is a prefix of the other: the longer copy already holds every
        # row of the shorter one, so the union IS that copy and no link moves.
        out["ok"] = True
        out["rows"] = list(ours if len(ours) >= len(theirs) else theirs)
        out["notes"].append(
            "no divergence: the %s copy already contains every row of the "
            "other, so nothing was re-chained and no `%s` row was added"
            % ("ours" if not theirs_tail else "theirs", MERGE_ACTION))
        return out
    out["divergent"] = True
    union = list(ours[:shared]) + _merge_tails(ours_tail, theirs_tail)
    chained, relinked = _rechain(union, name)
    # The marker is chained ON rather than re-chained WITH, so `relinked` stays a
    # count of rows whose link actually moved. A new row has no old hash to
    # differ from, and including it would have reported one more re-linked row
    # than the merge touched.
    marker = _merge_marker(chained, name, actor, {
        "shared": shared, "oursOnly": out["oursOnly"],
        "theirsOnly": out["theirsOnly"],
        "oursDigest": rows_digest(ours), "theirsDigest": rows_digest(theirs)})
    if marker is not None:
        marker["prev"] = chained[-1]["hash"]
        marker["hash"] = row_hash(marker)
        chained = chained + [marker]
    out["ok"] = True
    out["rows"] = chained
    out["relinked"] = relinked
    if identical:
        out["notes"].append(
            "%d row(s) sit at a timestamp both copies used and say the same "
            "thing; BOTH copies are kept, because dropping one is a guess that "
            "two identical rows were one event" % (identical,))
    return out


def rows_digest(rows):
    """A short digest over the CONTENT of a row list -- what a merge names its
    inputs by.

    Over content and not over the file's bytes: the two inputs of a merge differ
    in their links by definition, so a byte digest would only ever say they are
    different, while this says which rows each side held."""
    body = hashlib.sha256()
    for row in rows:
        body.update(row_content(row).encode("utf-8"))
    return body.hexdigest()[:12]


def merge_text(rows):
    """The bytes a merged journal file is written from -- one canonical row per
    line, exactly as `_append` writes one."""
    return "".join(canonical(row) + "\n" for row in rows)


def _read_target(path):
    """(text, unreadable): what `path` holds RIGHT NOW, before it is replaced.

    THE MISSING FILE AND THE UNREADABLE ONE ARE NOT THE SAME ANSWER, and
    collapsing them is how a guard goes quiet. A target that is not there yet
    holds no row, so there is nothing a merge could take from it and `""` is the
    truth rather than a fallback. A target that IS there and cannot be read is a
    question that could not be asked -- and the caller is about to overwrite
    that file, so `unreadable` carries the reason and the grader can refuse
    instead of being handed the reassuring empty answer.

    Deliberately not `read_file()`: that returns rows and swallows both cases
    into `([], False)`, which is right for a reader sweeping a directory and
    wrong for the one place that is about to replace the file.

    IT LIVES HERE RATHER THAN IN THE COMMAND BECAUSE OF WHERE IT IS CALLED FROM
    (F340). This read is the one `write_merged` makes with the lock already
    held; a copy of it in the command would be a read taken before the lock
    exists, which is the whole defect."""
    if not os.path.exists(path):
        return "", None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read(), None
    except Exception as exc:
        return "", str(exc)


def write_merged(path, text, grade=None, dry_run=False):
    """Write a merged journal file, under the SAME lock an append takes -- and
    GRADE it, against the bytes read inside that same hold.

    THE LOCK IS NOT OPTIONAL HERE, and it is the reason this write lives beside
    `_append` rather than in the command. An append reads the file's tail to
    learn its `prev`; a merge REPLACES that tail. Without the lock an append
    that had already read the old tail would land a row chained to a row this
    write just replaced -- a break that reads exactly like a deleted row, which
    is the false tamper verdict the lock exists to prevent.

    THAT ARGUMENT ONLY EVER COVERED HALF OF WHAT THE LOCK IS FOR (F340). The
    other half is the row itself. The command used to read the target, grade the
    result against it and only then call this -- so the read happened before any
    lock existed, and a row appended between the grading and `os.replace` was
    graded by nobody and deleted, at exit 0, with `verify` reporting the
    survivors chain cleanly. That is F328's signature moved from "the target was
    never read" to "the target was read too early", and the repair is that the
    read, the grading and the replace are ONE hold: `grade(text, unreadable)`
    is called with what this function read under the lock and returns the
    reasons the write must not happen. WHAT those reasons are belongs to the
    caller (`audit-journal.py` asks whether a row would be lost, whether the
    target is torn and whether it already holds a resolution); WHEN they are
    asked belongs here, because only here is the answer still true when the
    replace runs.

    `grade=None` writes UNGRADED, and the only caller that may pass None is one
    that is not replacing a live trail: `cmd_merge` always passes a grader.
    `dry_run` takes the lock and grades and does not write, so a preview is
    graded against a file nothing was appending to either.

    Returns {"written", "refusals", "path"} -- `written` is the fact, and
    `refusals` is why it may be false with no exception raised. It still RAISES
    on anything that stopped an attempted write: unlike `append`, this is not a
    record of a write that already succeeded -- it IS the write, and a caller
    told it was fine would go on to commit a conflicted file. A refusal is not
    that: nothing was attempted, and the reason is text a person has to read.

    Through a temporary file in the same directory, so an interrupted merge
    leaves either the old file or the new one and never half of each."""
    lock = _acquire(path)
    tmp = path + ".merged"
    try:
        refusals = []
        if grade is not None:
            current, unreadable = _read_target(path)
            refusals = list(grade(current, unreadable))
        if refusals or dry_run:
            return {"written": False, "refusals": refusals, "path": path}
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except Exception:
            # The half-written temporary goes, and the exception does not:
            # `journal_files` matches `.jsonl` so it would never be READ, but it
            # would sit in `git status` as an untracked file in the trail's own
            # directory, which is exactly the shape `guard-bash-writes` reports.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    finally:
        _release(lock)
    return {"written": True, "refusals": [], "path": path}


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


def rows_unaccounted(have_text, result_text):
    """Which parseable rows of `have_text` appear NOWHERE in `result_text`.

    -> {"missing", "row", "action", "unaccounted", "haveRows", "resultRows"}.
    `row`/`action` name the first one; `missing` is the count, so a caller can
    say "and N others" without a second pass.

    `unaccounted` IS ALL OF THEM, `(position, action)` in file order, because
    the count and the first one cannot be partitioned and the caller has to
    partition them (F342). A row somebody typed into a conflicted file while
    resolving it and a `journal.merge` row a previous run of the merge verb left
    behind are both "in neither stage", and they are two different findings with
    two different repairs -- and which of them `row` happens to name depended on
    the wall-clock second the two runs landed in, because the marker row's
    timestamp moves. Handing back the whole list is what lets the caller sort
    them by what they are rather than by which came first.

    PRESENCE ONLY, AND ORDER IS DELIBERATELY LEFT OUT OF THE QUESTION, which is
    what makes this a different function rather than a flag on
    `anchor_verdict`. Order is what lets that one catch a forgery, so it must
    not learn to ignore it. The caller here is the `from_index` merge, whose
    `have_text` is the CONFLICTED working copy -- two stages concatenated with
    markers between them, an order no chain ever had. Asking about order there
    refuses every genuine resolution; asking about presence catches the one
    thing that path can still lose, which is a row somebody typed into the
    conflicted file and that is therefore in neither stage.

    AND IT IS A SET QUESTION, NOT A COUNT, which is the opposite of the rule
    that applies one function up -- so the reason is here rather than left to
    look like the mistake `mu3` was about. A conflicted file legitimately
    carries the same row TWICE when both sides added identical content to their
    own tails, while the union that resolves it holds that row once. Counting
    would call that a loss and refuse a correct resolution. What is being
    guarded against is a row present in the file and absent from the result
    altogether, and set containment is exactly that question.
    """
    have_rows, _ht = rows_from_text(have_text)
    result_rows, _rt = rows_from_text(result_text)
    # An unparseable row cannot be compared with anything, and on this path the
    # conflict MARKERS are unparseable lines - so dropping them is not leniency,
    # it is the only reading available. `verify` reports an unparseable row in a
    # file it is asked about; this is not that question.
    wanted = [(row_content(r), r.get("action") or "?") for r in have_rows
              if not r.get("_unparseable")]
    held = set(row_content(r) for r in result_rows
               if not r.get("_unparseable"))
    # `row` is a POSITION and not the content, so a caller's sentence reads the
    # same way `anchor_verdict`'s does - one vocabulary for "which row", or the
    # two refusals this command can print would number things differently.
    gone = [(i, pair[1]) for i, pair in enumerate(wanted, 1)
            if pair[0] not in held]
    return {"missing": len(gone),
            "row": gone[0][0] if gone else None,
            "action": gone[0][1] if gone else None,
            "unaccounted": gone,
            "haveRows": len(wanted), "resultRows": len(held)}


def anchor_verdict(committed_text, working_text):
    """Does the working copy still hold every row the committed copy held?

    THE PROPERTY, and it is not the one this check used to assert:

        every row the committed copy holds is still in the working copy, with
        its CONTENT unchanged, in the same relative order.

    Returns {"held", "row", "action", "committedRows", "workingRows",
    "divergesAt", "extra"}. `row`/`action` name the first committed row that is
    gone or altered when `held` is false.

    WHY THE OLD PROXY HAD TO GO (F306). "`git show HEAD:<file>` is a byte-prefix
    of the working copy" stood in for append-only across commits, and it is a
    good proxy for as long as appending is the only thing that ever happens to
    the file. A merge is the other thing: resolving a divergence re-links every
    row after the divergence point, so the BYTES after that point are new while
    no row's content moved at all. The prefix relation cannot survive that -- and
    neither side of a divergence satisfies it either, which is why `verify`
    reported every sound resolution as broken and could tell nobody whether
    their resolution was sound.

    Content, order and presence are what the proxy was reaching for, and they are
    checkable directly. The BYTE prefix is still the fast path in
    `_git_anchor_finding` (it implies all three, and costs one comparison), so
    this runs only once the cheap answer has already failed.

    WHAT IT NO LONGER CATCHES, said plainly because a widening nobody states is
    a widening nobody checks: under the prefix rule a row could only be added at
    the END of the committed bytes, and under this one a row may be inserted
    BETWEEN committed rows -- which is exactly what a merge does with the other
    side's tail, and is therefore what could not be forbidden. A forger gains
    the ability to slip a fabricated row into the middle of a committed file.
    They already had the ability to append one, the whole file must still chain
    (`verify`'s per-row pass), and the merge that legitimately inserts rows
    leaves both parents in git plus a `journal.merge` row saying so. Insertion
    is reported as a WARNING rather than passing in silence, for that reason.

    Two ways this can be reached without a merge, both harmless and both
    covered: a file re-spelled by something that does not write canonical JSON,
    and a file whose committed copy is the pre-archive path. Neither changes a
    row's content, so both come back `held`.
    """
    committed_rows, _ct = rows_from_text(committed_text)
    working_rows, _wt = rows_from_text(working_text)
    # An unparseable committed row cannot be compared with anything, so it is
    # dropped from the question rather than counted as missing. `verify`'s own
    # per-row pass is what reports one in the WORKING copy.
    wanted = [(row_content(r), r.get("action") or "?") for r in committed_rows
              if not r.get("_unparseable")]
    have = [row_content(r) for r in working_rows if not r.get("_unparseable")]
    out = {"held": True, "row": None, "action": None,
           "committedRows": len(wanted), "workingRows": len(have),
           "divergesAt": None, "extra": len(have) - len(wanted)}
    at = 0
    for i, pair in enumerate(wanted):
        content, action = pair
        while at < len(have) and have[at] != content:
            at += 1
        if at >= len(have):
            out["held"] = False
            out["row"] = i + 1
            out["action"] = action
            return out
        at += 1
    same = 0
    for pair, mine in zip(wanted, have):
        if pair[0] != mine:
            break
        same += 1
    out["divergesAt"] = same + 1 if same < len(have) else None
    return out


def _anchor_warning(name, verdict, committed_at):
    """The warning text for a file whose committed rows all survived but whose
    BYTES moved. `verdict` is `anchor_verdict`'s answer, with `held` true.

    A FUNCTION RATHER THAN A FORMAT STRING AT THE RETURN, because this is the
    highest-stakes prose the module emits and nothing could reach it: it is
    built inside `_git_anchor_finding`, which needs a real repository, and the
    one gate that has one asserts the FINDING's text and not this. Both defects
    below were therefore invisible to every check in the tree.

    IT SENT THE READER TO A PLACE THAT MAY NOT EXIST. Re-linking a chain is what
    a merge resolution does, and a fabricated row spliced BETWEEN committed rows
    and re-chained produces exactly this shape -- every committed row still
    present, in order, with its content intact. `anchor_verdict`'s own docstring
    says so, in the passage about what the rule no longer catches. The text
    nonetheless read "the merge commit is where you check which side the extra
    rows came from", and under the second reading there is no merge commit at
    all. Nothing here can tell the two readings apart, so the warning says that
    and names the evidence that would -- two parents and a `journal.merge` row
    -- rather than assuming one of them.

    AND `divergesAt` CAN BE ABSENT, which is the other reading again: a file
    re-spelled by something that does not write canonical JSON diverges at no
    row at all, and the bytes differ while every row is the same row in the same
    order. The old text substituted the first row for the missing number and
    told the reader the copies part at the beginning -- a row number no reader
    could act on, about a divergence that did not happen. That case gets its own
    sentence, because "extra rows" is advice about rows that are not there."""
    if verdict["divergesAt"] is None:
        return (
            "%s is no longer byte-identical to its committed copy, and no row "
            "diverged: every committed row is still here, in order, with its "
            "content intact, and nothing arrived alongside them. Something "
            "rewrote the bytes without changing a single row -- a writer that "
            "does not spell canonical JSON is the ordinary cause (git show "
            "HEAD:%s)" % (name, committed_at))
    return (
        "%s is no longer byte-identical to its committed copy from row %d on, "
        "and no row's content changed: all %d committed row(s) are still here, "
        "in order, alongside %d more. Re-linking a chain is what "
        "`audit-journal.py merge` does to resolve a divergence -- and a row "
        "spliced between committed rows and re-chained looks exactly like this "
        "from here, so NOTHING IN THIS CHECK CAN TELL THOSE APART. Read the "
        "rows that arrived and find what put them there: a resolution leaves "
        "both sides in git as the parents of a merge commit and a `%s` row "
        "saying what it did, and rows that arrived with neither are rows "
        "nothing has accounted for (git show HEAD:%s)"
        % (name, verdict["divergesAt"], verdict["committedRows"],
           max(verdict["extra"], 0), MERGE_ACTION, committed_at))


def _git_anchor_finding(path):
    """The git anchor's VERDICT on one file: {"finding", "warning"}, or None.

    Once a journal file is committed, every row its committed copy holds must
    still be in the working copy, unchanged and in order -- append-only ACROSS
    commits, which is what makes "rewrite the whole file and recompute every
    hash" detectable (the forger must now rewrite git history too, on every
    clone that has it). `anchor_verdict` holds that rule and says why it is no
    longer the byte-prefix this function used to assert.

    THE NAME SAYS `finding` AND THE RETURN CARRIES A WARNING TOO, deliberately:
    two files this module may not edit name it in their own prose
    (`tools/check-git-pipeline.py`, `run-test-gate.py`), and a rename that left
    that prose pointing at nothing would cost more than the imprecision. Both
    keys are always present when anything is returned; None means the question
    could not be asked.

    Fail-open silently on every inability to check: no git binary, not a
    repository, an untracked file, `git show` erroring (tracked but not yet in
    HEAD) -- with one deliberate retry: a file in archive/ whose committed copy
    is not at its new path yet is anchored against the PRE-archive path one
    level up (see the comment at the seam). Line endings are normalised before
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
        if working.startswith(committed):
            # The fast path, and still the one almost every file takes: a byte
            # prefix implies presence, content and order all three, in one
            # comparison and with nothing parsed.
            return None
        verdict = anchor_verdict(committed.decode("utf-8", "replace"),
                                 working.decode("utf-8", "replace"))
        if not verdict["held"]:
            return {"finding": (
                "%s: the journal's committed past changed -- committed row %d "
                "(%s) is no longer in the working copy with its content "
                "intact. A row's CONTENT is what nothing may change; resolving "
                "a divergence recomputes only `prev` and `hash` (git show "
                "HEAD:%s)" % (name, verdict["row"], verdict["action"],
                              committed_at)), "warning": None}
        return {"finding": None,
                "warning": _anchor_warning(name, verdict, committed_at)}
    except Exception:
        return None


def verify(project, config=None):
    """Does the chain hold, and does the world still match its last row?

    Returns {"ok", "dir", "exists", "rows", "files": [...], "findings", "warnings"}.
    FINDINGS are breaks -- an edited row, a deleted or reordered one, a file that
    is not the file its genesis names, and a committed row that is no longer in
    the working copy with its content intact. WARNINGS are the honest maybes: a
    torn tail (a crash, not a cover-up), out-of-band drift (the document moved
    with no row to say why -- which is normal for anything the plugin did not
    write), and a file whose LINKS were recomputed while every committed row's
    content survived, which is what resolving a divergence does.

    THE GIT ANCHOR ASKS ABOUT ROWS AND NOT ABOUT BYTES since F306, and the two
    differ for exactly one operation: a merge re-links every row after the
    divergence point, so the bytes change where nothing a row says changes.
    `anchor_verdict` carries the property that replaced the byte prefix, what it
    stopped being able to forbid, and why. The byte prefix is still tried first
    and still settles almost every file.
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
        where = _output.posix_rel(path, directory)
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
            if anchor.get("finding"):
                entry["findings"].append(anchor["finding"])
            if anchor.get("warning"):
                entry["warnings"].append(anchor["warning"])
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


