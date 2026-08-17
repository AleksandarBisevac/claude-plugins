#!/usr/bin/env python3
"""
The audit trail: an append-only, hash-chained record of every change to the plan
and the config -- dependency-free (stdlib).

    audit-journal.py append  --action <a> [--target <path>] [--summary <text>]
    audit-journal.py verify  [--json]
    audit-journal.py show    [--limit N] [--json] [--target <path>]
    audit-journal.py archive [--before YYYY-MM]
    audit-journal.py --selftest
      (every command takes --project DIR; default the current directory)

Exit codes: 0 healthy (warnings allowed) - 1 findings (the chain does not hold) -
2 usage error.

This module carries no `--selftest` of its own any more; its 112 cases live in
`plugins/audit/tests/test_audit_journal.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. Four of them (k5-k8) SWAP `_git_anchor_finding`
for a counting stub to prove the batched git-anchor pass is O(1 + dirty); they set
it on the module object now, so renaming that function breaks them loudly rather
than leaving them measuring a call that never happened.

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
    {"v", "ts", "actor": {"author", "sessionId", "via", "host"},
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
import argparse
import errno
import hashlib
import json
import os
import platform
import re
import sys
import time

ROW_VERSION = 1
# A row carrying a `details` block is v2. The version names the SHAPE of one row,
# not of the file: the hash covers whatever fields are present, so v1 and v2 rows
# interleave in one file with no migration and no flag day.
DETAILS_VERSION = 2
DETAILS_KEYS = ("changes", "taskId", "phaseId", "field", "from", "to", "commit",
                "completedAt", "mergedAt", "fromId", "toId", "fromPhase",
                "toPhase", "truncated")
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
_HERE = os.path.dirname(os.path.abspath(__file__))
_HOOKS = os.path.join(os.path.dirname(_HERE), "hooks")

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
def writer_id(actor):
    """A file-name-safe id for the writer -- its session, else host+pid.

    Sanitised and truncated because it goes into a PATH: a session id is supplied
    by the caller, and a caller that can write `../../etc/passwd` into a file name
    can write outside the journal directory."""
    actor = actor if isinstance(actor, dict) else {}
    raw = str(actor.get("sessionId") or "").strip()
    if not raw:
        raw = "%s-%d" % (platform.node() or "host", os.getpid())
    # Strip once BEFORE the slice (so leading rubbish does not spend the 24-char
    # budget) and once AFTER it (F-F2: a real UUID is 8-4-4-4-12, so the slice
    # ends exactly on its fourth dash, and a writer id with a trailing `-` or `.`
    # is one character away from reading as another writer's slot). The `or`
    # sits on the FINAL expression, for ids that are nothing but separators.
    safe = _SAFE.sub("-", raw).strip("-.")
    return safe[:24].strip("-.") or "writer"


def month_of(ts):
    return str(ts)[:7] if len(str(ts)) >= 7 else time.strftime("%Y-%m", time.gmtime())


def file_for(directory, ts, actor):
    return os.path.join(directory, "%s.%s.jsonl" % (month_of(ts), writer_id(actor)))


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


def normalise_details(details):
    """The v2 `details` block: allow-listed keys only, every value bounded, the
    whole block capped. Returns None when there is nothing worth keeping -- the
    row then stays v1, which is what lets old and new rows share a file.

    An unknown key is DROPPED rather than chained in: the hash covers whatever is
    in the row, so an inventive writer would otherwise decide the format for
    every reader that comes after it -- the same rule _normalise applies to the
    row itself."""
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
        else:
            out[key] = _clip(val)
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
def _normalise(entry):
    """The caller supplies the news; this file owns the shape.

    A writer passing an inventive key would otherwise decide the format, and the
    hash covers whatever is in the row -- so an unknown key would be chained in and
    every reader would have to cope with it."""
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
            "via": str(actor.get("via") or "unknown"),
            "host": str(actor.get("host") or platform.node() or "unknown"),
        },
        "action": str(entry.get("action") or "").strip(),
        "target": str(entry.get("target") or "").strip(),
        "summary": str(entry.get("summary") or ""),
    }
    details = normalise_details(entry.get("details"))
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
    row = _normalise(entry)
    directory = journal_dir(project, config)
    os.makedirs(directory, exist_ok=True)
    path = file_for(directory, row["ts"], row["actor"])

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


# --- commands -----------------------------------------------------------------
def cmd_append(args, out):
    project = os.path.abspath(args.project)
    config = load_config(project)
    if not enabled(config):
        out("[audit-journal] journal disabled (journal.enabled false) -- "
            "nothing written")
        return 0
    try:
        row, _path = _append(project, {
            "action": args.action, "target": args.target or "",
            "summary": args.summary or "",
            "details": getattr(args, "_details", None),
            "actor": {"author": args.author, "sessionId": args.session,
                      "via": args.via}}, config=config)
    except Exception as exc:
        out("[audit-journal] could not append: %s" % exc)
        return 1
    out("[audit-journal] %s %s  %s" % (row["ts"], row["action"],
                                       row["hash"][:12]))
    return 0


def cmd_verify(args, out):
    project = os.path.abspath(args.project)
    res = verify(project)
    if args.as_json:
        out(json.dumps(res, indent=2, sort_keys=True))
        return 1 if res["findings"] else 0
    if not res["exists"]:
        out("[audit-journal] no journal yet at %s" % res["dir"])
        return 0
    for line in res["warnings"]:
        out("WARNING: " + line)
    for line in res["findings"]:
        out("FINDING: " + line)
    if res["findings"]:
        out("\nBROKEN: %d finding(s) across %d row(s) in %s"
            % (len(res["findings"]), res["rows"], res["dir"]))
        return 1
    out("OK: %d row(s) in %d file(s) chain cleanly%s"
        % (res["rows"], len(res["files"]),
           " (%d warning(s))" % len(res["warnings"]) if res["warnings"] else ""))
    return 0


def cmd_archive(args, out):
    """Move whole month-files into <journal>/archive/ -- `git mv`, never a
    rewrite, because the hash chain survives only untouched bytes and the
    genesis seed is the file's BASENAME: a moved file verifies exactly as it
    did live, and git carries its committed history across the move so the
    git anchor keeps holding.

    Default: every month-file older than the current month. --before YYYY-MM
    archives strictly older months. The current month (and anything newer) is
    never archived -- it is still being written.

    DECISION (pinned, v0.37 D): an UNTRACKED file is moved with os.rename
    rather than refused. `git mv` fails on untracked files, and the reason
    git mv is the mechanism -- carrying COMMITTED history across the move --
    does not exist for a file with no committed past: a plain rename loses
    nothing the chain or the anchor ever had. The doctor's never-committed
    warning follows the file into archive/ and keeps nagging until it is
    committed, which is the honest state of affairs.
    """
    import shutil
    import subprocess

    def git(directory, *a):
        try:
            res = subprocess.run(["git", "-C", directory] + list(a),
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=30)
            return res.returncode, (res.stdout or b"").decode("utf-8",
                                                              "replace"), \
                (res.stderr or b"").decode("utf-8", "replace")
        except Exception as exc:
            return 1, "", str(exc)

    project = os.path.abspath(args.project)
    config = load_config(project)
    directory = journal_dir(project, config)
    current = time.strftime("%Y-%m", time.gmtime())
    before = (args.before or "").strip()
    if before and not _MONTH_RE.match(before):
        out("[audit-journal] --before must be YYYY-MM (got %r)" % before)
        return 2
    cutoff = before or current
    if cutoff > current:
        out("[audit-journal] --before %s reaches into the future; the current "
            "month and anything newer is still being written and is never "
            "archived -- archiving everything older than %s instead"
            % (before, current))
        cutoff = current
    if not os.path.isdir(directory):
        out("[audit-journal] nothing to archive: no journal at %s" % directory)
        return 0
    in_repo = False
    if shutil.which("git"):
        rc, txt, _err = git(directory, "rev-parse", "--is-inside-work-tree")
        in_repo = rc == 0 and txt.strip() == "true"
    if not in_repo:
        # The whole point of archiving by `git mv` is that committed history
        # follows the move and the git anchor keeps holding. No repository
        # means no history to carry -- and an archive that silently plain-moved
        # files here would teach people the operation is safe anywhere.
        out("[audit-journal] not inside a git repository (or git is not on "
            "PATH): archive moves files with `git mv` so their committed "
            "history follows the move and the git anchor keeps holding -- "
            "with no repository there is nothing to carry. Run `git init` "
            "and commit the journal first.")
        return 2
    moved, kept, failed = [], [], []
    arch = os.path.join(directory, ARCHIVE_DIRNAME)
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        month = name[:7]
        if not _MONTH_RE.match(month):
            kept.append("%s: kept -- no YYYY-MM month prefix to judge it by"
                        % name)
            continue
        if month >= cutoff:
            continue        # current/future months and >= --before stay live
        if os.path.exists(os.path.join(arch, name)):
            kept.append("%s: kept -- archive/%s already exists; refusing to "
                        "overwrite it (verify will warn about the duplicate)"
                        % (name, name))
            continue
        os.makedirs(arch, exist_ok=True)
        rc, _txt, _err = git(directory, "ls-files", "--error-unmatch",
                             "--", name)
        if rc == 0:
            rc2, _txt2, err2 = git(directory, "mv", name,
                                   "%s/%s" % (ARCHIVE_DIRNAME, name))
            if rc2 != 0:
                failed.append("%s: git mv failed (%s)"
                              % (name, err2.strip() or "unknown error"))
                continue
            moved.append("%s -> archive/%s (git mv; committed history "
                         "follows the move)" % (name, name))
        else:
            try:
                os.rename(os.path.join(directory, name),
                          os.path.join(arch, name))
            except OSError as exc:
                failed.append("%s: could not move (%s)" % (name, exc))
                continue
            moved.append("%s -> archive/%s (renamed; never committed, so "
                         "there was no git history to carry)" % (name, name))
    for line in kept:
        out("[audit-journal] " + line)
    for line in failed:
        out("[audit-journal] FAILED " + line)
    for line in moved:
        out("[audit-journal] archived " + line)
    if moved:
        out("[audit-journal] %d file(s) moved, 0 bytes rewritten: a hash "
            "chain survives only untouched bytes, and its seed is the file's "
            "basename, so every moved file verifies exactly as it did. "
            "Commit the archive/ directory so the git anchor pins it."
            % len(moved))
    elif not kept and not failed:
        out("[audit-journal] nothing to archive: no month-file older than %s "
            "in %s" % (cutoff, directory))
    return 1 if failed else 0


def cmd_show(args, out):
    project = os.path.abspath(args.project)
    rows = read_all(project)
    if args.target:
        rows = [r for r in rows if r.get("target") == args.target]
    if args.limit > 0:
        rows = rows[-args.limit:]
    if args.as_json:
        out(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if not rows:
        out("[audit-journal] no rows")
        return 0
    for r in rows:
        actor = r.get("actor") or {}
        out("%s  %-18s %-28s %s"
            % (r.get("ts"), r.get("action"), (r.get("target") or "")[-28:],
               actor.get("author") or actor.get("sessionId") or "unknown"))
        if r.get("summary"):
            out("    %s" % r["summary"])
    return 0


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="audit-journal.py", add_help=True)
    p.add_argument("command", choices=["append", "verify", "show", "archive"])
    p.add_argument("--project", default=".")
    p.add_argument("--before", default="")
    p.add_argument("--action", default="")
    p.add_argument("--target", default="")
    p.add_argument("--summary", default="")
    p.add_argument("--details", default=None)
    p.add_argument("--via", default="cli")
    p.add_argument("--author", default=None)
    p.add_argument("--session", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not os.path.isdir(args.project):
        out("[audit-journal] not a directory: %s" % args.project)
        return 2
    if args.command == "append" and not args.action.strip():
        out("[audit-journal] append needs --action")
        return 2
    # --details is parsed HERE, before anything is written: malformed JSON is a
    # usage error (2), never a silently plain row -- a caller passing structured
    # news must find out it was dropped.
    args._details = None
    if args.command == "append" and args.details:
        try:
            parsed = json.loads(args.details)
        except Exception as exc:
            out("[audit-journal] --details is not valid JSON: %s" % exc)
            return 2
        if not isinstance(parsed, dict):
            out("[audit-journal] --details must be a JSON object")
            return 2
        args._details = parsed
    try:
        if args.command == "append":
            return cmd_append(args, out)
        if args.command == "verify":
            return cmd_verify(args, out)
        if args.command == "archive":
            return cmd_archive(args, out)
        return cmd_show(args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[audit-journal] internal error: %s" % exc)
        return 2


if __name__ == "__main__":
    from _output import safe_stdio       # same dir; sys.path[0] when run directly
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than falling through to `main`, which would read the flag
        # as an unknown command. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-journal.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_journal.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
