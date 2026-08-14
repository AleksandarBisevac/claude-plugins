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


# --- selftest -----------------------------------------------------------------
def _selftest():
    import shutil
    import tempfile

    results = []

    def check(name, cond, detail=""):
        results.append(bool(cond))
        print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                           (" (%s)" % detail) if detail and not cond else ""))

    def run(argv, project):
        lines = []
        code = main(argv + ["--project", project], out=lines.append)
        return code, "\n".join(lines)

    def _month_shift(n):
        """YYYY-MM for `n` months before the current month. Computed, never
        hardcoded -- a hardcoded date goes red the day the calendar catches
        up with it (the doctor's F-A1 lesson)."""
        t = time.gmtime()
        y, m = t.tm_year, t.tm_mon - n
        while m < 1:
            y, m = y - 1, m + 12
        return "%04d-%02d" % (y, m)

    tmp = tempfile.mkdtemp(prefix="audit-journal-")
    try:
        proj = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(proj, "docs", "audit"))
        cfg = {"manifestPath": "docs/audit/audit-plan.json"}

        # --- a1: where it lands, without being told ---------------------------
        # Derived from manifestPath rather than hardcoded: a repo that moved its
        # plan must not end up with the record of it somewhere else.
        check("a1 the journal sits beside the manifest by default",
              journal_dir(proj, cfg)
              == os.path.join(proj, "docs/audit".replace("/", os.sep), "journal"))
        check("a2 journal.dir overrides it",
              journal_dir(proj, {"journal": {"dir": "audit-trail"}})
              == os.path.join(proj, "audit-trail"))
        check("a2b a root-level manifestPath does not leave a `./` segment in the "
              "returned path (BUG-2: mixed separators on Windows, `proj/./journal` "
              "on POSIX)",
              journal_dir(proj, {"manifestPath": "audit.json"})
              == os.path.normpath(os.path.join(proj, DEFAULT_DIRNAME)))
        check("a2c the default-manifest shape is normalized too",
              journal_dir(proj, cfg)
              == os.path.normpath(os.path.join(proj, "docs", "audit", "journal")))
        check("a3 enabled by default, and an explicit false is honoured",
              enabled({}) is True and enabled({"journal": {"enabled": False}}) is False)
        check("a4 a non-bool `enabled` is ignored rather than trusted "
              "(the rule `enforce` already follows)",
              enabled({"journal": {"enabled": "false"}}) is True)

        # --- b: one row, and what is in it ------------------------------------
        ok = append(proj, {"action": "config.write", "target": "cfg.json",
                           "summary": "1 change(s): x", "actor": {
                               "author": "dev@example.com", "sessionId": "s-one",
                               "via": "panel"}}, config=cfg)
        d = journal_dir(proj, cfg)
        files = journal_files(d)
        # F-F3: success is the PATH of the file the row landed in, not a bare
        # True -- the journal-writes hook records that path in its sidecar so
        # guard-bash-writes can tell the plugin's own append from a shell write.
        # Truthiness is unchanged, so every caller that boolean-tests survives.
        check("b1 append() reports success as the path it wrote, and writes "
              "exactly one file",
              isinstance(ok, str) and ok == files[0] and len(files) == 1,
              repr((ok, files)))
        check("b2 the file is <month>.<writer>.jsonl",
              os.path.basename(files[0]).endswith(".s-one.jsonl")
              and os.path.basename(files[0])[:7] == time.strftime("%Y-%m",
                                                                  time.gmtime()))
        rows, torn = read_file(files[0])
        r0 = rows[0]
        check("b3 the row carries the contract's fields and nothing invented",
              set(r0) == {"v", "ts", "actor", "action", "target", "summary",
                          "stateHash", "prev", "hash"}, repr(sorted(r0)))
        check("b4 the actor keeps who, how and where",
              r0["actor"]["author"] == "dev@example.com"
              and r0["actor"]["via"] == "panel"
              and r0["actor"]["sessionId"] == "s-one"
              and bool(r0["actor"]["host"]))
        check("b5 the first row's prev is derived from the FILE NAME, so a file "
              "cannot be renamed into another writer's slot and still verify",
              r0["prev"] == genesis_prev(os.path.basename(files[0])))
        check("b6 the row hashes to its own contents", r0["hash"] == row_hash(r0)
              and not torn)
        check("b7 a target that does not exist leaves stateHash null, rather than "
              "a hash of nothing", r0["stateHash"] is None)

        # --- c: the chain -----------------------------------------------------
        append(proj, {"action": "composition.write", "target": "m.json",
                      "summary": "two", "actor": {"sessionId": "s-one",
                                                  "via": "panel"}}, config=cfg)
        rows, _ = read_file(files[0])
        check("c1 the second row chains to the first",
              len(rows) == 2 and rows[1]["prev"] == rows[0]["hash"])
        res = verify(proj, cfg)
        check("c2 a clean chain verifies with no findings",
              res["ok"] and res["rows"] == 2 and not res["findings"],
              repr(res["findings"]))

        def rewrite(path, rows_):
            with open(path, "w", encoding="utf-8") as fh:
                for r in rows_:
                    fh.write(canonical(r) + "\n")

        # An edited row: the summary says something else and the hash no longer
        # covers it. This is the case the whole file exists for.
        edited = [dict(rows[0]), dict(rows[1])]
        edited[0]["summary"] = "nothing happened"
        rewrite(files[0], edited)
        res = verify(proj, cfg)
        check("c3 an edited row is a FINDING that names the row and the reason",
              not res["ok"] and any("edited after it was written" in f
                                    for f in res["findings"]), repr(res["findings"]))
        # And the forger who fixes the hash of the row they edited is caught by
        # the NEXT row's prev -- which is the entire point of chaining.
        edited[0]["hash"] = row_hash(edited[0])
        rewrite(files[0], edited)
        res = verify(proj, cfg)
        check("c4 ...and re-hashing that row alone still breaks the chain at the "
              "row after it",
              not res["ok"] and any("does not follow the row before it" in f
                                    for f in res["findings"]), repr(res["findings"]))

        rewrite(files[0], rows)                       # back to the honest pair
        check("c5 restored, it verifies again", verify(proj, cfg)["ok"])

        rewrite(files[0], [rows[1]])                  # first row deleted
        res = verify(proj, cfg)
        check("c6 a deleted row is a FINDING (the survivor's prev names a row that "
              "is not there)", not res["ok"])
        rewrite(files[0], [rows[1], rows[0]])         # reordered
        res = verify(proj, cfg)
        check("c7 a reordered pair is a FINDING", not res["ok"])
        rewrite(files[0], rows)

        # A torn tail is a crash, not a cover-up: warn, do not accuse.
        with open(files[0], "a", encoding="utf-8") as fh:
            fh.write('{"v":1,"action":"half-writ')
        res = verify(proj, cfg)
        check("c8 a torn last line is a WARNING, and the rows before it still "
              "verify", res["ok"] and res["rows"] == 2
              and any("partial line" in w for w in res["warnings"]),
              repr(res))
        rewrite(files[0], rows)

        # A file copied into another writer's name: every prev still matches its
        # predecessor, so ONLY the genesis binding catches this.
        twin = os.path.join(d, os.path.basename(files[0]).replace("s-one", "s-two"))
        shutil.copyfile(files[0], twin)
        res = verify(proj, cfg)
        check("c9 a file copied under another writer's name is caught by the "
              "genesis binding, which is the only thing that can see it",
              not res["ok"] and any("renamed" in f for f in res["findings"]),
              repr(res["findings"]))
        os.unlink(twin)
        check("c10 and removing the copy makes it clean again", verify(proj, cfg)["ok"])

        # --- d: out-of-band drift --------------------------------------------
        tgt = os.path.join(proj, "docs", "audit", "audit-plan.json")
        with open(tgt, "w", encoding="utf-8") as fh:
            fh.write('{"meta":{"version":3}}')
        append(proj, {"action": "manifest.edit",
                      "target": "docs/audit/audit-plan.json",
                      "summary": "wrote it", "actor": {"sessionId": "s-one",
                                                       "via": "hook"}}, config=cfg)
        res = verify(proj, cfg)
        check("d1 a target recorded and untouched raises nothing",
              res["ok"] and not res["warnings"], repr(res["warnings"]))
        with open(tgt, "w", encoding="utf-8") as fh:
            fh.write('{"meta":{"version":3},"phases":[]}')
        res = verify(proj, cfg)
        check("d2 a target changed with no row to explain it is a WARNING, not a "
              "finding - an out-of-band write is not proof of a cover-up",
              res["ok"] and any("never saw" in w for w in res["warnings"]),
              repr(res["warnings"]))
        os.unlink(tgt)
        check("d3 a target that has been deleted says so",
              any("no longer exists" in w for w in verify(proj, cfg)["warnings"]))

        # --- e: fail-soft, and the safety of a caller-supplied id -------------
        # Every one of these goes through `_soft`, because "never raises" is the
        # contract and an exception escaping here would kill this suite with a
        # traceback instead of failing the case that is about it — red for the
        # wrong reason proves nothing.
        def _soft(entry, config=cfg, project=proj):
            try:
                return append(project, entry, config=config)
            except Exception as exc:                   # pragma: no cover
                return "it raised: %s" % exc

        check("e1 a row with no action is refused rather than written blank",
              _soft({"summary": "x"}) is False)
        check("e2 a disabled journal writes nothing and says False, so a caller "
              "reports `not logged` rather than a failed save",
              _soft({"action": "x"}, config={"journal": {"enabled": False}}) is False)
        check("e3 garbage in, False out - never an exception into the writer",
              _soft(None) is False and _soft("not a dict") is False)
        check("e4 an unwritable journal dir is False, not a crash",
              _soft({"action": "x"}, config={"journal": {"dir": "\0bad"}},
                    project=os.path.join(tmp, "no-such-project")) is False)
        # A session id is supplied by the caller and lands in a PATH.
        check("e5 a writer id cannot escape the journal directory",
              writer_id({"sessionId": "../../etc/passwd"}) == "etc-passwd"
              and "/" not in writer_id({"sessionId": "a/b"})
              and os.sep not in writer_id({"sessionId": "a" + os.sep + "b"}))
        check("e6 a writer with no session id still gets a stable file name",
              bool(writer_id({})) and writer_id({}) == writer_id({}))
        check("e7 a long session id is truncated (a file name is not unbounded)",
              len(writer_id({"sessionId": "x" * 200})) == 24)
        # F-F2: the truncation itself can END on `-` or `.`. A real UUID is
        # 8-4-4-4-12, so its 24-char slice ends exactly on the fourth dash --
        # every real session got a writer id with a trailing `-`, and a rename
        # of that file (or a hand copy that drops the dash) reads as another
        # writer's slot. Strip AFTER the slice too; the first strip still
        # handles leading rubbish before the slice spends its budget on it.
        check("e8 a real UUID's writer id does not end on a dash",
              writer_id({"sessionId": "abcd1234-ef56-7890-abcd-123456789012"})
              == "abcd1234-ef56-7890-abcd",
              repr(writer_id({"sessionId":
                              "abcd1234-ef56-7890-abcd-123456789012"})))
        check("e8b the boundary id whose 24th char is the dash is trimmed, "
              "not kept",
              writer_id({"sessionId": "a" * 23 + "-" + "b" * 10}) == "a" * 23,
              repr(writer_id({"sessionId": "a" * 23 + "-" + "b" * 10})))
        check("e8c a pathological id of nothing but separators still gets a "
              "stable name",
              writer_id({"sessionId": "." * 40}) == "writer"
              and writer_id({"sessionId": "-.-.-.-" * 10}) == "writer")

        # --- f: two writers, two files, one clean journal ---------------------
        two = os.path.join(tmp, "two")
        os.makedirs(two)
        for sid in ("alpha", "beta"):
            for i in range(2):
                append(two, {"action": "config.write", "summary": "%s-%d" % (sid, i),
                             "actor": {"sessionId": sid, "via": "panel"}},
                       config={"journal": {"dir": "j"}})
        res = verify(two, {"journal": {"dir": "j"}})
        check("f1 two writers write two files - one shared file would conflict on "
              "every worktree merge",
              len(res["files"]) == 2 and res["rows"] == 4 and res["ok"],
              repr(res))
        check("f2 read_all returns every row, oldest first, tagged with its file",
              len(read_all(two, {"journal": {"dir": "j"}})) == 4
              and all(r.get("_file") for r in
                      read_all(two, {"journal": {"dir": "j"}})))

        # --- g: the lock ------------------------------------------------------
        gproj = os.path.join(tmp, "lockrepo")
        os.makedirs(gproj)
        gcfg = {"journal": {"dir": "j"}}
        append(gproj, {"action": "a", "actor": {"sessionId": "s"}}, config=gcfg)
        gpath = journal_files(journal_dir(gproj, gcfg))[0]
        held = gpath + ".lock"
        with open(held, "w", encoding="utf-8") as fh:
            fh.write("")
        t0 = time.time()
        check("g1 a held lock declines the append rather than racing it - a torn "
              "chain reads as tampering, which is worse than a missing row",
              append(gproj, {"action": "b", "actor": {"sessionId": "s"}},
                     config=gcfg) is False)
        check("g2 ...and it gives up in bounded time", time.time() - t0 < 10)
        os.utime(held, (time.time() - 600, time.time() - 600))
        check("g3 a lock left behind by a dead writer is stolen, not waited on "
              "forever (and success is the written path)",
              isinstance(append(gproj, {"action": "c",
                                        "actor": {"sessionId": "s"}},
                                config=gcfg), str))
        check("g4 the stolen-lock append still chains cleanly",
              verify(gproj, gcfg)["ok"])
        check("g5 the lock file is not left lying in the journal directory",
              not os.path.exists(held))

        # --- h: canonical form ------------------------------------------------
        check("h1 canonical JSON is stable regardless of key order",
              canonical({"b": 1, "a": [1, {"d": 2, "c": 3}]})
              == canonical({"a": [1, {"c": 3, "d": 2}], "b": 1}))
        check("h2 the hash ignores the `hash` field itself (or nothing could ever "
              "verify)",
              row_hash({"a": 1, "hash": "x"}) == row_hash({"a": 1, "hash": "y"}))
        check("h3 canonical output is pure ASCII, so a cp1252 stream cannot kill "
              "a writer", canonical({"a": "café"}).isascii())

        # --- i: the CLI -------------------------------------------------------
        cproj = os.path.join(tmp, "cli")
        os.makedirs(os.path.join(cproj, "docs", "audit"))
        code, txt = run(["verify"], cproj)
        check("i1 verify with no journal at all is 0 and says so, not an error",
              code == 0 and "no journal yet" in txt, txt)
        code, txt = run(["append", "--action", "config.write", "--summary", "hi"],
                        cproj)
        check("i2 append prints the row it wrote", code == 0 and "config.write" in txt)
        code, txt = run(["verify"], cproj)
        check("i3 verify is 0 on a clean chain and counts the rows",
              code == 0 and "OK: 1 row(s)" in txt, txt)
        code, txt = run(["show"], cproj)
        check("i4 show prints the row", code == 0 and "config.write" in txt)
        code, txt = run(["show", "--json"], cproj)
        check("i5 show --json is parseable and carries the chain fields",
              code == 0 and json.loads(txt)[0]["hash"])
        code, txt = run(["append"], cproj)
        check("i6 append with no action is a usage error (2), not a blank row",
              code == 2, txt)
        _lines = []
        check("i7 a missing project is a usage error",
              main(["verify", "--project",
                    os.path.join(tmp, "not-a-directory")],
                   out=_lines.append) == 2, "\n".join(_lines))
        # Break it, and prove the CLI's exit code moves with the verdict: this is
        # the code CI and the doctor act on.
        jf = journal_files(journal_dir(cproj))[0]
        rows, _ = read_file(jf)
        rows[0]["summary"] = "tampered"
        rewrite(jf, rows)
        code, txt = run(["verify"], cproj)
        check("i8 verify EXITS 1 on a broken chain (grepping the text is how three "
              "false pass reports happened)", code == 1 and "FINDING" in txt, txt)
        code, txt = run(["verify", "--json"], cproj)
        check("i9 verify --json keeps the exit code and reports ok:false",
              code == 1 and json.loads(txt)["ok"] is False)
        code, txt = run(["nonsense"], cproj)
        check("i10 an unknown command is a usage error", code == 2)

        # --- j: row v2 -- the optional `details` block ------------------------
        # The hash covers whatever fields are present, so a v1 row and a v2 row
        # share a file with no migration; everything here pins that claim.
        jproj = os.path.join(tmp, "v2")
        os.makedirs(jproj)
        jcfg = {"journal": {"dir": "j"}}
        ok = append(jproj, {"action": "manifest.edit", "target": "plan.json",
                            "summary": "P1.1: status in_progress->done",
                            "details": {"taskId": "P1.1", "phaseId": "P1",
                                        "from": "in_progress", "to": "done"},
                            "actor": {"sessionId": "s-v2", "via": "hook"}},
                    config=jcfg)
        jrows = read_all(jproj, jcfg)
        jrow = jrows[-1] if jrows else {}
        check("j1 a row can carry details, and the allow-listed keys survive the "
              "round trip",
              isinstance(ok, str) and jrow.get("details") == {
                  "taskId": "P1.1", "phaseId": "P1",
                  "from": "in_progress", "to": "done"},
              repr(jrow.get("details")))
        jclean = {k: v for k, v in jrow.items() if k != "_file"}
        check("j2 a details row is v2, hashes to its own contents, and verifies",
              jrow.get("v") == 2 and jclean.get("hash") == row_hash(jclean)
              and verify(jproj, jcfg)["ok"], repr(jrow))
        append(jproj, {"action": "manifest.edit", "target": "plan.json",
                       "summary": "plain", "actor": {"sessionId": "s-v2",
                                                     "via": "hook"}}, config=jcfg)
        jrows = read_all(jproj, jcfg)
        check("j3 a row without details stays v1 with the v1 key set - the new "
              "shape is opt-in per row, not a migration",
              jrows[-1].get("v") == 1 and "details" not in jrows[-1]
              and set(jrows[-1]) - {"_file"} == {
                  "v", "ts", "actor", "action", "target", "summary",
                  "stateHash", "prev", "hash"}, repr(sorted(jrows[-1])))
        check("j3b ...and the mixed file still chains cleanly",
              verify(jproj, jcfg)["ok"] and verify(jproj, jcfg)["rows"] == 2)

        # A file an OLDER plugin wrote -- hand-built v1 rows -- then a v2 row
        # appended by THIS code, chaining onto the old tail.
        fixdir = os.path.join(tmp, "v1fixture")
        os.makedirs(os.path.join(fixdir, "j"))
        fpath = os.path.join(fixdir, "j", "%s.s-old.jsonl"
                             % time.strftime("%Y-%m", time.gmtime()))
        prev_h = genesis_prev(os.path.basename(fpath))
        hand = []
        for i in range(2):
            r = {"v": 1, "ts": "2020-01-01T00:00:0%dZ" % i,
                 "actor": {"author": None, "sessionId": "s-old", "via": "hook",
                           "host": "h"},
                 "action": "manifest.edit", "target": "", "summary": "old %d" % i,
                 "stateHash": None, "prev": prev_h}
            r["hash"] = row_hash(r)
            prev_h = r["hash"]
            hand.append(r)
        rewrite(fpath, hand)
        fixcfg = {"journal": {"dir": "j"}}
        check("j4 a pre-v2 fixture file verifies untouched",
              verify(fixdir, fixcfg)["ok"]
              and verify(fixdir, fixcfg)["rows"] == 2,
              repr(verify(fixdir, fixcfg)))
        append(fixdir, {"action": "manifest.edit", "target": "",
                        "summary": "new", "details": {"taskId": "P9.1"},
                        "actor": {"sessionId": "s-old", "via": "hook"}},
               config=fixcfg)
        resv = verify(fixdir, fixcfg)
        vrows, _ = read_file(fpath)
        check("j5 a v2 row appended after v1 rows chains onto the old tail in "
              "the SAME file",
              resv["ok"] and resv["rows"] == 3 and len(resv["files"]) == 1
              and vrows[-1].get("v") == 2
              and vrows[-1].get("prev") == hand[-1]["hash"], repr(resv))

        # The allow-list, the bounds, and the cap.
        append(jproj, {"action": "x", "summary": "s",
                       "details": {"taskId": "T", "invented": "nope"},
                       "actor": {"sessionId": "s-v2"}}, config=jcfg)
        check("j6 an unknown details key is dropped, not chained in",
              read_all(jproj, jcfg)[-1].get("details") == {"taskId": "T"},
              repr(read_all(jproj, jcfg)[-1].get("details")))
        check("j6b a details dict with ONLY unknown keys leaves a plain v1 row",
              normalise_details({"invented": 1}) is None
              and normalise_details("not a dict") is None
              and normalise_details(None) is None)
        append(jproj, {"action": "x", "summary": "s",
                       "details": {"from": "x" * 500},
                       "actor": {"sessionId": "s-v2"}}, config=jcfg)
        check("j7 a long value is truncated to %d chars" % MAX_VALUE_CHARS,
              read_all(jproj, jcfg)[-1].get("details", {}).get("from") == "x" * 120)
        many = [{"id": "P1.%d" % i, "field": "status", "from": "a", "to": "b"}
                for i in range(20)]
        det = normalise_details({"changes": many})
        check("j8 a change list is capped at %d and says it was truncated"
              % MAX_CHANGES,
              isinstance(det, dict) and len(det.get("changes") or []) == 12
              and det.get("truncated") is True, repr(det))
        huge = {"changes": [{"id": "P1.%d" % i, "field": "outcome",
                             "from": "a" * 120, "to": "b" * 120}
                            for i in range(12)],
                "taskId": "t" * 120, "phaseId": "p" * 120, "commit": "c" * 120,
                "completedAt": "d" * 120, "fromId": "e" * 120, "toId": "f" * 120,
                "fromPhase": "g" * 120, "toPhase": "h" * 120}
        det = normalise_details(huge)
        check("j9 a details block over %d bytes collapses to a truncation marker "
              "that still says how many changes there were" % MAX_DETAILS_BYTES,
              det == {"truncated": True, "changes": 12}, repr(det))
        check("j9b the marker itself is under the cap",
              len(canonical({"truncated": True, "changes": 12})
                  .encode("utf-8")) < MAX_DETAILS_BYTES)

        # The CLI.
        c2proj = os.path.join(tmp, "cli2")
        os.makedirs(c2proj)
        code, txt = run(["append", "--action", "task.move",
                         "--details", '{"fromId":"P1.1","toId":"P2.4"}'], c2proj)
        check("j10 append --details writes the row (exit 0)", code == 0, txt)
        code, txt = run(["show", "--json"], c2proj)
        got = json.loads(txt)[-1] if code == 0 else {}
        check("j10b ...and show --json carries it back out",
              got.get("details") == {"fromId": "P1.1", "toId": "P2.4"}
              and got.get("v") == 2, repr(got))
        code, txt = run(["append", "--action", "x", "--details", "{not json"],
                        c2proj)
        check("j11 malformed --details is a usage error (2), not a silent plain "
              "row", code == 2, txt)
        code, txt = run(["append", "--action", "x", "--details", '["a list"]'],
                        c2proj)
        check("j11b a non-object --details is a usage error too", code == 2, txt)
        check("j11c neither wrote anything",
              verify(c2proj)["rows"] == 1, repr(verify(c2proj)))
        append(c2proj, {"action": "x", "summary": "s", "details": "a string",
                        "actor": {"sessionId": "s"}})
        check("j12 a non-dict details via the API is ignored, the row stays v1",
              read_all(c2proj)[-1].get("v") == 1
              and "details" not in read_all(c2proj)[-1])

        # --- k: the git anchor -------------------------------------------------
        # A forger who rewrites the whole file and recomputes every hash forward
        # produces a chain that verifies -- the module docstring admits it. What
        # they cannot rewrite from here is git history: once the journal is
        # committed, `git show HEAD:<file>` must be a byte-prefix of the working
        # copy (append-only across commits).
        import subprocess
        if not shutil.which("git"):
            print("SKIP k1-k4 (git is not on PATH)")
        else:
            gdir = os.path.join(tmp, "gitrepo")
            os.makedirs(os.path.join(gdir, "docs", "audit"))

            def git(*args):
                return subprocess.run(
                    ["git", "-C", gdir, "-c", "user.email=t@t",
                     "-c", "user.name=t"] + list(args),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30)

            git("init", "-q")
            gcfg = {"manifestPath": "docs/audit/audit-plan.json"}
            append(gdir, {"action": "manifest.edit", "target": "",
                          "summary": "one",
                          "actor": {"sessionId": "s-git", "via": "hook"}},
                   config=gcfg)
            gfile = journal_files(journal_dir(gdir, gcfg))[0]
            resk = verify(gdir, gcfg)
            check("k1 an untracked journal is silent - no finding, no warning "
                  "(fail-open: no git anchor is not evidence of anything)",
                  resk["ok"] and not resk["warnings"], repr(resk))
            git("add", ".")
            git("commit", "-q", "-m", "journal")
            append(gdir, {"action": "manifest.edit", "target": "",
                          "summary": "two",
                          "actor": {"sessionId": "s-git", "via": "hook"}},
                   config=gcfg)
            check("k2 the committed copy is a byte-prefix of the working file, "
                  "so appending after a commit stays clean",
                  verify(gdir, gcfg)["ok"], repr(verify(gdir, gcfg)))
            with open(gfile, "rb") as fh:
                pristine = fh.read()
            grows, _ = read_file(gfile)
            forged, prev_f = [], genesis_prev(os.path.basename(gfile))
            for r in grows:
                r = dict(r)
                if not forged:
                    r["summary"] = "nothing happened"
                r["prev"] = prev_f
                r["hash"] = row_hash({k: v for k, v in r.items()
                                      if k != "hash"})
                prev_f = r["hash"]
                forged.append(r)
            rewrite(gfile, forged)
            resk = verify(gdir, gcfg)
            check("k3 a full rewrite with recomputed hashes chains cleanly and "
                  "is STILL a FINDING - the committed past changed",
                  not resk["ok"]
                  and any("committed past changed" in f
                          for f in resk["findings"]), repr(resk["findings"]))
            with open(gfile, "wb") as fh:
                fh.write(pristine)
            check("k4 restored byte-for-byte, it verifies again",
                  verify(gdir, gcfg)["ok"], repr(verify(gdir, gcfg)))

            # k5-k8 (F-B3): the anchor is BATCHED - one porcelain per
            # directory decides who pays the single-file check. Fixture: two
            # committed-clean writer files + one committed-then-appended one.
            append(gdir, {"action": "manifest.edit", "target": "",
                          "summary": "w2", "actor": {"sessionId": "s-git-2",
                                                     "via": "hook"}},
                   config=gcfg)
            append(gdir, {"action": "manifest.edit", "target": "",
                          "summary": "w3", "actor": {"sessionId": "s-git-3",
                                                     "via": "hook"}},
                   config=gcfg)
            git("add", ".")
            git("commit", "-q", "-m", "all writers committed")
            _orig_anchor = _git_anchor_finding
            _anchor_calls = []

            def _counting_anchor(path):
                _anchor_calls.append(os.path.basename(path))
                return _orig_anchor(path)

            globals()["_git_anchor_finding"] = _counting_anchor
            try:
                resk = verify(gdir, gcfg)
                check("k5 tracked-and-clean files never pay the single-file "
                      "check - committed equals working, the prefix holds "
                      "trivially",
                      resk["ok"] and _anchor_calls == [],
                      repr((_anchor_calls, resk["findings"])))
                append(gdir, {"action": "manifest.edit", "target": "",
                              "summary": "three",
                              "actor": {"sessionId": "s-git", "via": "hook"}},
                       config=gcfg)
                _anchor_calls.clear()
                resk = verify(gdir, gcfg)
                check("k6 a committed-then-appended file is the ONLY one that "
                      "pays git show, and it still verifies - O(1+dirty)",
                      resk["ok"]
                      and _anchor_calls == [os.path.basename(gfile)],
                      repr((_anchor_calls, resk["findings"])))
                with open(gfile, "rb") as fh:
                    pristine2 = fh.read()
                grows2, _ = read_file(gfile)
                forged2, prev_f2 = [], genesis_prev(os.path.basename(gfile))
                for r in grows2:
                    r = dict(r)
                    if not forged2:
                        r["summary"] = "nothing happened here either"
                    r["prev"] = prev_f2
                    r["hash"] = row_hash({k: v for k, v in r.items()
                                          if k != "hash"})
                    prev_f2 = r["hash"]
                    forged2.append(r)
                rewrite(gfile, forged2)
                resk = verify(gdir, gcfg)
                check("k7 a rewritten committed row is STILL a FINDING through "
                      "the batched path - batching skips the clean, never the "
                      "guilty",
                      not resk["ok"]
                      and any("committed past changed" in f
                              for f in resk["findings"]),
                      repr(resk["findings"]))
                with open(gfile, "wb") as fh:
                    fh.write(pristine2)
                check("k8 restored byte-for-byte, the batched pass is green "
                      "again", verify(gdir, gcfg)["ok"],
                      repr(verify(gdir, gcfg)["findings"]))
            finally:
                globals()["_git_anchor_finding"] = _orig_anchor

            # k9-k10 (F-D-1): status keys are JOURNAL-RELATIVE PATHS, not
            # basenames. The journal dir here sits three levels deep
            # (docs/audit/journal), so these go red if porcelain's
            # repo-root-relative paths are ever mapped onto the directory
            # wrongly: an archived file the batch cannot see never pays the
            # anchor, and a forged archive twin would sail through.
            jdir9 = journal_dir(gdir, gcfg)
            aname9 = os.path.basename(gfile)
            apath9 = os.path.join(jdir9, "archive", aname9)
            os.makedirs(os.path.join(jdir9, "archive"))
            shutil.copyfile(gfile, apath9)
            git("add", ".")
            git("commit", "-q", "-m", "archive twin committed")
            with open(apath9, "rb") as fh:
                pristine9 = fh.read()
            arows9, _ = read_file(apath9)
            forged9, prev9 = [], genesis_prev(aname9)
            for r in arows9:
                r = dict(r)
                if not forged9:
                    r["summary"] = "nothing happened"
                r["prev"] = prev9
                r["hash"] = row_hash({k: v for k, v in r.items()
                                      if k != "hash"})
                prev9 = r["hash"]
                forged9.append(r)
            rewrite(apath9, forged9)
            resk = verify(gdir, gcfg)
            aent9 = [e for e in resk["files"]
                     if e["file"] == "archive/" + aname9]
            check("k9 a forged ARCHIVED twin of a live basename is caught "
                  "through the batched path - the twin answers for ITSELF, "
                  "its live namesake cannot answer for it (F-D-1)",
                  not resk["ok"] and aent9
                  and any("committed past changed" in f
                          for f in aent9[0]["findings"]),
                  repr(resk["findings"]))
            with open(apath9, "wb") as fh:
                fh.write(pristine9)
            resk = verify(gdir, gcfg)
            check("k10 restored byte-for-byte the batch is green again, and "
                  "only the duplicate-basename WARNING remains (the "
                  "collision state itself, already named by verify)",
                  resk["ok"] and not resk["findings"]
                  and any("double-count" in w for w in resk["warnings"]),
                  repr((resk["findings"], resk["warnings"])))

        # --- l: the archive/ subdirectory -------------------------------------
        # journal_files sees `<journal>/archive/` -- EXACTLY one level, never a
        # walk. The chain seed is the file's BASENAME (genesis_prev), so a file
        # MOVED into archive/ byte-for-byte verifies exactly as it did live:
        # that is the entire design of the git-mv archive (untouched bytes,
        # same name, different directory).
        lproj = os.path.join(tmp, "arch")
        os.makedirs(lproj)
        lcfg = {"journal": {"dir": "j"}}
        old_month = _month_shift(2)
        for i, summ in enumerate(("old-1", "old-2")):
            append(lproj, {"action": "manifest.edit", "target": "",
                           "summary": summ,
                           "ts": "%s-01T00:00:0%dZ" % (old_month, i),
                           "actor": {"sessionId": "s-old", "via": "hook"}},
                   config=lcfg)
        append(lproj, {"action": "manifest.edit", "target": "",
                       "summary": "live",
                       "actor": {"sessionId": "s-new", "via": "hook"}},
               config=lcfg)
        ldir = journal_dir(lproj, lcfg)
        pre = verify(lproj, lcfg)
        check("l1 the fixture verifies green BEFORE archiving",
              pre["ok"] and pre["rows"] == 3, repr(pre))
        lold = os.path.join(ldir, "%s.s-old.jsonl" % old_month)
        lnew_name = "%s.s-new.jsonl" % time.strftime("%Y-%m", time.gmtime())
        with open(lold, "rb") as fh:
            lbytes = fh.read()
        os.makedirs(os.path.join(ldir, "archive"))
        lapath = os.path.join(ldir, "archive", os.path.basename(lold))
        os.rename(lold, lapath)
        check("l2 journal_files sees the archive/ subdirectory, live files "
              "first",
              [os.path.relpath(p, ldir).replace(os.sep, "/")
               for p in journal_files(ldir)]
              == [lnew_name, "archive/%s.s-old.jsonl" % old_month],
              repr(journal_files(ldir)))
        deepdir = os.path.join(ldir, "archive", "deep")
        os.makedirs(deepdir)
        with open(os.path.join(deepdir, "0000-01.x.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write("{}\n")
        check("l3 exactly ONE level: a file nested below archive/ is not a "
              "journal file (minimal scope, not a tree walk)",
              all(os.sep + "deep" + os.sep not in p
                  for p in journal_files(ldir)), repr(journal_files(ldir)))
        res = verify(lproj, lcfg)
        check("l4 the chain verifies green AFTER the move -- untouched bytes "
              "under the same basename seed the same genesis",
              res["ok"] and res["rows"] == 3, repr(res))
        check("l5 verify reports the archived file AS archive/<name>, so a "
              "live and an archived month cannot read as one another",
              any(e["file"] == "archive/%s.s-old.jsonl" % old_month
                  for e in res["files"])
              and any(e["file"] == lnew_name for e in res["files"]),
              repr([e["file"] for e in res["files"]]))
        arows, _ = read_file(lapath)
        arows2 = [dict(r) for r in arows]
        arows2[0]["summary"] = "nothing happened"
        rewrite(lapath, arows2)
        res = verify(lproj, lcfg)
        check("l6 a broken chain INSIDE archive/ is still a FINDING, and it "
              "names the archive/ path",
              not res["ok"] and any("archive/" in f and "edited after" in f
                                    for f in res["findings"]),
              repr(res["findings"]))
        with open(lapath, "wb") as fh:
            fh.write(lbytes)
        check("l7 restored byte-for-byte, the archived file is green again",
              verify(lproj, lcfg)["ok"],
              repr(verify(lproj, lcfg)["findings"]))
        shutil.copyfile(lapath, lold)
        res = verify(lproj, lcfg)
        check("l8 the same basename live AND archived is a WARNING naming the "
              "duplication (its rows double-count)",
              res["ok"] and any("archive/" in w and "double-count" in w
                                for w in res["warnings"]),
              repr(res["warnings"]))
        os.unlink(lold)
        check("l9 read_all includes archived rows, tagged with the BASENAME "
              "(_file feeds the doctor's deep check, which greps commit trees "
              "where the file was still live)",
              len(read_all(lproj, lcfg)) == 3
              and any(r.get("_file") == os.path.basename(lold)
                      for r in read_all(lproj, lcfg)),
              repr([r.get("_file") for r in read_all(lproj, lcfg)]))

        # --- m: the `archive` subcommand ---------------------------------------
        # `git mv`, never a rewrite: the hash chain survives only untouched
        # bytes, and git carries the file's committed history across the move
        # so the git anchor keeps holding.
        m0 = os.path.join(tmp, "norepo")
        os.makedirs(os.path.join(m0, ".claude"))
        with open(os.path.join(m0, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"journal": {"dir": "j"}}')
        append(m0, {"action": "manifest.edit", "target": "",
                    "summary": "old", "ts": old_month + "-01T00:00:00Z",
                    "actor": {"sessionId": "s-m", "via": "hook"}},
               config={"journal": {"dir": "j"}})
        code, txt = run(["archive"], m0)
        check("m1 outside a git repository archive REFUSES (usage error 2) "
              "and says why: git mv is the mechanism, no repo means no "
              "history to carry",
              code == 2 and "git mv" in txt and "git init" in txt, txt)
        check("m1b ...and nothing moved",
              os.path.isfile(os.path.join(m0, "j", "%s.s-m.jsonl" % old_month))
              and not os.path.isdir(os.path.join(m0, "j", "archive")),
              repr(os.listdir(os.path.join(m0, "j"))))
        if not shutil.which("git"):
            print("SKIP m2-m10 (git is not on PATH)")
        else:
            mdir = os.path.join(tmp, "archrepo")
            os.makedirs(os.path.join(mdir, ".claude"))
            with open(os.path.join(mdir, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                fh.write('{"journal": {"dir": "j"}}')

            def mgit(*a):
                return subprocess.run(
                    ["git", "-C", mdir, "-c", "user.email=t@t",
                     "-c", "user.name=t"] + list(a),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=30)

            mgit("init", "-q")
            mcfg = {"journal": {"dir": "j"}}
            for i in range(2):
                append(mdir, {"action": "manifest.edit", "target": "",
                              "summary": "old %d" % i,
                              "ts": "%s-01T00:00:0%dZ" % (old_month, i),
                              "actor": {"sessionId": "s-arch", "via": "hook"}},
                       config=mcfg)
            append(mdir, {"action": "manifest.edit", "target": "",
                          "summary": "live",
                          "actor": {"sessionId": "s-arch", "via": "hook"}},
                   config=mcfg)
            mgit("add", ".")
            mgit("commit", "-q", "-m", "journal committed")
            mold = os.path.join(mdir, "j", "%s.s-arch.jsonl" % old_month)
            mlive = os.path.join(mdir, "j", "%s.s-arch.jsonl"
                                 % time.strftime("%Y-%m", time.gmtime()))
            with open(mold, "rb") as fh:
                mbytes = fh.read()
            msha = hashlib.sha256(mbytes).hexdigest()
            pre = verify(mdir, mcfg)
            code, txt = run(["archive"], mdir)
            march = os.path.join(mdir, "j", "archive",
                                 "%s.s-arch.jsonl" % old_month)
            same_bytes = False
            if os.path.isfile(march):
                with open(march, "rb") as fh:
                    same_bytes = (hashlib.sha256(fh.read()).hexdigest()
                                  == msha)
            check("m2 archive moves the past month into archive/ and leaves "
                  "the bytes untouched (sha256-identical)",
                  code == 0 and same_bytes and not os.path.exists(mold), txt)
            check("m2b the current month stays live -- still being written, "
                  "never archived", os.path.isfile(mlive),
                  repr(journal_files(os.path.join(mdir, "j"))))
            check("m2c the output says what moved and why mv-not-rewrite "
                  "matters (the chain survives only untouched bytes)",
                  "git mv" in txt and "untouched bytes" in txt, txt)
            st = mgit("status", "--porcelain").stdout.decode("utf-8",
                                                             "replace")
            check("m3 the move is a STAGED RENAME -- git followed it, nothing "
                  "was deleted-and-recreated",
                  any(line.startswith("R ") for line in st.splitlines()), st)
            post = verify(mdir, mcfg)
            check("m4 chain verify is green before AND after: same rows, no "
                  "findings",
                  pre["ok"] and post["ok"]
                  and pre["rows"] == post["rows"] == 3,
                  repr((pre["rows"], post["rows"], post["findings"])))
            code, txt = run(["archive"], mdir)
            check("m5 a second run is idempotent: exit 0 and a calm "
                  "nothing-to-archive line",
                  code == 0 and "nothing to archive" in txt, txt)
            # The staged-rename window: HEAD has no copy at the NEW path yet,
            # so a whole-file rewrite here would slip past a naive anchor. The
            # committed past sits one level up, at the pre-archive path, and
            # the anchor must follow it there.
            frows, _ = read_file(march)
            forged, fprev = [], genesis_prev(os.path.basename(march))
            for r in frows:
                r = dict(r)
                if not forged:
                    r["summary"] = "nothing happened"
                r["prev"] = fprev
                r["hash"] = row_hash({k: v for k, v in r.items()
                                      if k != "hash"})
                fprev = r["hash"]
                forged.append(r)
            rewrite(march, forged)
            res = verify(mdir, mcfg)
            check("m6 a full rewrite of the archived file DURING the "
                  "staged-rename window is STILL a FINDING -- the anchor "
                  "follows the move back to the pre-archive path",
                  not res["ok"] and any("committed past changed" in f
                                        for f in res["findings"]),
                  repr(res["findings"]))
            with open(march, "wb") as fh:
                fh.write(mbytes)
            check("m6b restored byte-for-byte, green again",
                  verify(mdir, mcfg)["ok"],
                  repr(verify(mdir, mcfg)["findings"]))
            mgit("add", "-A")
            mgit("commit", "-q", "-m", "the archive commit")
            check("m7 after the archive commit the moved file anchors at its "
                  "NEW path and still verifies", verify(mdir, mcfg)["ok"],
                  repr(verify(mdir, mcfg)["findings"]))
            # Untracked files and --before. DECISION (pinned): an untracked
            # file is MOVED with os.rename rather than refused -- git mv fails
            # on untracked files, and the reason git mv is the mechanism
            # (carrying COMMITTED history across the move) does not exist for
            # a file with no committed past; a plain rename loses nothing.
            old3, old1 = _month_shift(3), _month_shift(1)
            for mo in (old3, old1):
                append(mdir, {"action": "manifest.edit", "target": "",
                              "summary": "untracked " + mo,
                              "ts": mo + "-01T00:00:00Z",
                              "actor": {"sessionId": "s-un", "via": "hook"}},
                       config=mcfg)
            code, txt = run(["archive", "--before", old1], mdir)
            check("m8 --before archives strictly OLDER months only: %s "
                  "moves, %s stays" % (old3, old1),
                  code == 0
                  and os.path.isfile(os.path.join(
                      mdir, "j", "archive", "%s.s-un.jsonl" % old3))
                  and os.path.isfile(os.path.join(
                      mdir, "j", "%s.s-un.jsonl" % old1)), txt)
            check("m8b an untracked file is MOVED (renamed), and the output "
                  "says there was no git history to carry",
                  "renamed" in txt and "no git history" in txt, txt)
            check("m8c ...and the untracked move still verifies green",
                  verify(mdir, mcfg)["ok"],
                  repr(verify(mdir, mcfg)["findings"]))
            code, txt = run(["archive", "--before", "not-a-month"], mdir)
            check("m9 a malformed --before is a usage error (2) naming the "
                  "shape", code == 2 and "YYYY-MM" in txt, txt)
            future = "%04d-01" % (time.gmtime().tm_year + 1)
            code, txt = run(["archive", "--before", future], mdir)
            check("m9b a future --before is clamped out loud -- the current "
                  "month and anything newer is never archived",
                  code == 0 and "never archived" in txt
                  and os.path.isfile(mlive), txt)
            # A live file re-created for an archived month (a late append):
            # never overwritten -- the refusal is printed, verify warns.
            append(mdir, {"action": "manifest.edit", "target": "",
                          "summary": "late row for an archived month",
                          "ts": old_month + "-15T00:00:00Z",
                          "actor": {"sessionId": "s-arch", "via": "hook"}},
                   config=mcfg)
            res = verify(mdir, mcfg)
            check("m10 a re-created live file for an archived month is the "
                  "duplicate WARNING, not a silent double count",
                  res["ok"] and any("double-count" in w
                                    for w in res["warnings"]),
                  repr(res["warnings"]))
            code, txt = run(["archive"], mdir)
            check("m10b archive refuses to overwrite an existing archive "
                  "file -- the live one is kept and the refusal printed",
                  code == 0 and "refusing to overwrite" in txt
                  and os.path.isfile(mold), txt)
            os.unlink(mold)
            check("m10c with the duplicate gone the journal reads clean "
                  "again",
                  verify(mdir, mcfg)["ok"]
                  and not verify(mdir, mcfg)["warnings"],
                  repr(verify(mdir, mcfg)["warnings"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    from _output import safe_stdio       # same dir; sys.path[0] when run directly
    safe_stdio()
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
