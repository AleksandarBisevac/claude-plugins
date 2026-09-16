#!/usr/bin/env python3
"""
The identity of a tree at a moment, and whether a later tree is still that one.

WHY THIS IS A MODULE AND NOT A SECOND ANSWER. `run-test-gate.py` already had to
solve this for its own rows: a gate verdict is about a STATE, and `head` alone
cannot name that state because a task gate runs before the task commit. Its
answer is three fields - HEAD, a digest of the declared work, and a digest of
WHICH paths were dirty - each carried with the basis that bounds it. Those
functions are MOVED here unchanged rather than copied, so the fingerprint a gate
row records and the stamp an orchestrator carries in a report are the same
arithmetic over the same bytes. A second expression of "which tree was this"
would BE a second tree identity, and the first thing two of those do is disagree.

THE SECOND QUESTION IS: given a stamp taken earlier, is the tree still the one it
names? That is `compare()`, and its answer has THREE words and not two. `current`
and `stale` are the two a reader expects; `unestablished` is the one this tree's
vocabulary insists on - `porcelain()`'s None below, the doctor's
`running_plugin_verdict`, `_evidence_io`'s null check count are all the same
refusal, that a question which could not be asked must never be reported as the
comfortable answer. A stamp graded against a directory git will not describe is
not a stamp that matched.

AND THE THIRD IS THE ONE THE THREE FIELDS ABOVE CANNOT ANSWER: are the BYTES the
same? `content_digest()` is that question, and it exists because the fields above
were asked to carry a decision they cannot support - a verdict repeated instead
of re-measured. `DIRTY_LIMIT` below is why: a digest over which paths were dirty
says nothing about what is in them. So the content identity is built from a
different pair of git questions, it reads file bytes rather than status words,
and it is kept apart from the stamp rather than folded into it - a stamp is a
cheap discriminator carried in prose, and this is an expensive one nobody pastes
into a commit message.

AND A STALE ANSWER NAMES THE FIELD THAT MOVED. "Stale" on its own sends a reader
back to re-run everything; HEAD having moved, the declared work having changed,
and some path's dirty status having changed are three different repairs, and the
comparison already knows which of them happened.

WHAT A STAMP DOES NOT ESTABLISH IS PRINTED BESIDE IT, in `FIELD_LIMIT` below.
`DIRTY_LIMIT` is the sharpest of the three and it is inherited rather than
softened: the dirty digest records WHICH paths were dirty, never their contents,
so a rewrite of an already-dirty file outside the declared scope moves nothing
here. A stamp whose output implied otherwise would be worse than no stamp.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__tree_stamp.py`.
"""

import hashlib
import json
import os
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

import _journal_io  # noqa: E402  (the ONE canonical spelling and file digest)


# --- the tree as git describes it ---------------------------------------------
def porcelain(project):
    """`git status --porcelain -uall` as a set of lines, or None when git cannot answer.

    None is NOT an empty tree. A repository git refuses to describe is a basis
    this module does not have, and reporting that as "nothing changed" would be
    the false clean sheet the whole file exists to prevent.

    `-uall` IS THAT SAME REFUSAL, ONE CAUSE OVER. Git collapses a WHOLLY
    UNTRACKED directory to a single `?? dir/` entry, so without the flag a
    fix-in-place gate that CREATES a file inside one moves no line at all and the
    bracket answers `treeMutated == []` -- the value that means KNOWN CLEAN. That
    is not a corner: a subject tree nobody has committed yet, a first audit run,
    a brand-new source directory are all exactly it. Every other porcelain reader
    in this plugin already passes the flag and says why beside it
    (`_journal_io._git_status_sets`, `commit-audit-state`, `guard-bash-writes`);
    this was the reader that did not.

    AND IT DOES NOT MAKE THE BRACKET CONTENT-AWARE, which is the reading the flag
    invites and the one to refuse. Porcelain reports STATUS, never bytes: a file
    that was ALREADY untracked keeps its one `?? path` entry when a gate REWRITES
    it, with the flag exactly as without it. So a rewrite of an already-untracked
    file is invisible to this comparison either way -- `DIRTY_LIMIT` states the
    matching limit for an already-dirty TRACKED file further down -- and the
    limit is pinned by a case of its own, so nobody can read the flag as having
    repaired what it did not touch.
    """
    try:
        out = subprocess.run(["git", "-C", project, "status", "--porcelain",
                              "-uall"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=60)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return set(ln for ln in out.stdout.decode("utf-8", "replace").splitlines()
               if ln.strip())


# --- what state was actually tested -------------------------------------------
# `head` cannot answer this and never could. A TASK gate runs BEFORE the task
# commit, so a run executes against HEAD plus staged edits plus unstaged ones plus
# untracked files: two failed retries at one HEAD were indistinguishable, which
# defeats the point of recording retries. So `head` is demoted to what it actually
# is and a digest of the DECLARED work is recorded beside it.
#
# NOT A SECOND HASHING SUBSYSTEM. `_journal_io.canonical` is the one spelling this
# tree hashes with and `_journal_io.file_hash` is the one file digest; both are
# reused verbatim. What is new here is only WHICH bytes get fed to them.
HEAD_BASIS = ("repository HEAD at execution time; it does not identify the "
              "tested state, because a task gate runs before the task commit")

# THE LIMIT EACH FIELD CARRIES, AS A CONSTANT AND NOT AS A DOCSTRING SENTENCE.
# These are PRINTED - beside the stamp when it is taken and beside the field when
# it moves - and a docstring nobody renders would be a second statement of the
# same limit, free to drift from the one a reader actually sees. So the functions
# below point here rather than restating it.
SCOPE_LIMIT = ("the declared files' contents, exactly and nothing wider: two "
               "stamps sharing this digest measured identical declared-file "
               "contents, and a differing one means the declared work changed")
DIRTY_LIMIT = ("WHICH paths were dirty, never their contents. Editing an "
               "already-dirty file outside the declared scope moves neither "
               "this nor the scope digest, so this is a retry discriminator "
               "and not a reproducible snapshot of the repository")


def _head(project):
    """The short HEAD sha, or None when git will not say.

    None rather than a placeholder, for `porcelain`'s reason: a repository git
    cannot describe has not got a HEAD this run can name, and inventing one would
    put a false anchor on a real row."""
    try:
        out = subprocess.run(["git", "-C", project, "rev-parse", "--short", "HEAD"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=60)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "replace").strip() or None


def _digest(payload):
    """`sha256:<hex>` over one canonical spelling of `payload`, or None.

    The prefix is `file_hash`'s, so a reader meets one shape for every digest a
    row carries rather than having to know which field wears one."""
    try:
        return "sha256:" + hashlib.sha256(
            _journal_io.canonical(payload).encode("utf-8")).hexdigest()
    except Exception:
        return None


def scope_digest(project, owns):
    """`(digest, basis)` for the DECLARED work as it stands right now.

    EXACT FOR THE DECLARED SCOPE and nothing wider, which is the whole claim, and
    `SCOPE_LIMIT` is that sentence in the words the output prints.

    A MISSING FILE HASHES AS NULL RATHER THAN BEING DROPPED. Absent is itself
    evidence about the state under test, and skipping it would let a scope of
    three files and a scope of two share a digest.

    None when nothing is declared, the shape `coverage()` already uses one
    question over: a digest of an empty list is a real digest that would compare
    equal across every such run and read as agreement.
    """
    declared = [f for f in (owns or []) if isinstance(f, str) and f.strip()]
    if not declared:
        return None, ("the work under test declares no files, so there is "
                      "nothing to fingerprint")
    entries, missing = [], 0
    for rel in sorted(set(declared)):
        digest = _journal_io.file_hash(os.path.join(project, rel))
        if digest is None:
            missing += 1
        entries.append([rel, digest])
    return _digest(entries), ("%d declared file(s); %d read, %d missing"
                              % (len(entries), len(entries) - missing, missing))


def dirty_digest(before):
    """`(digest, basis)` over the porcelain lines taken BEFORE the run.

    Reuses the snapshot a caller already holds, so this costs no extra git call
    at all.

    WHAT IT DOES AND DOES NOT SAY is `DIRTY_LIMIT` above, which is the sentence
    the stamp prints; the limit is pinned by a case rather than left for a reader
    to discover.
    """
    if before is None:
        return None, "git could not describe the tree, so it has no fingerprint"
    return (_digest(sorted(before)),
            "git described the tree before the run; %d dirty path(s)"
            % (len(before),))


def tested_state(project, owns, before):
    """The three identity fields, each with the basis that bounds it."""
    scope, sbasis = scope_digest(project, owns)
    dirty, dbasis = dirty_digest(before)
    return {"head": _head(project), "headBasis": HEAD_BASIS,
            "scopeDigest": scope, "scopeBasis": sbasis,
            "dirtyDigest": dirty, "dirtyBasis": dbasis}


# --- the content identity: every byte git reports ------------------------------
# WHY NOT THE THREE FIELDS ABOVE. `DIRTY_LIMIT` says it in the words the stamp
# prints: that digest records WHICH paths were dirty and never their contents,
# and `SCOPE_LIMIT` is exact for the declared files and silent about everything
# else. Both are retry discriminators, which is all a gate row needed of them.
# A caller that skips work because "this tree was measured already" needs the
# other question, and answering it off those fields would skip a re-run after a
# real edit to any file the work does not declare.
#
# BUILT FROM WHAT GIT REPORTS, NEVER FROM A WALK WRITTEN HERE. A walk has to
# re-derive which files are ignored, and a second expression of "which files
# count" is the thing this module exists to prevent. Two questions, both of them
# git's own:
#
#   * `ls-files -s` is the INDEX - one entry per tracked path, carrying the blob
#     git already hashed. It covers a staged edit as well as a committed one,
#     which `rev-parse HEAD` cannot: a gate runs before the task commit, and on a
#     staged tree HEAD is not what the commands read.
#   * `ls-files --modified --deleted --others --exclude-standard` is everything
#     the worktree says differently from that index, with the ignore rules
#     applied by git. Those paths are the only ones whose BYTES are read, so the
#     cost is the size of the diff and not the size of the repository.
#
# AND BOTH ARE ASKED WITH `-z`. Git QUOTES a path it will not print raw - a
# control byte, a quote, and under the default `core.quotePath` every non-ASCII
# byte as an octal escape - so a reader of the unseparated output needs an
# unquoting rule, and a second such rule is a second answer about which file is
# which. NUL-separated output is printed verbatim and there is nothing to undo.
CONTENT_LIMIT = ("the bytes git reports from this directory: the index entry of "
                 "every tracked path, and the current content of every path git "
                 "names as differing from that index or as untracked and not "
                 "ignored. It does not reach a file git ignores, the inside of "
                 "a submodule, a package installed outside the tree, an "
                 "environment variable, the clock or the network")

# How many differing paths this identity will open before it refuses to answer.
# A REFUSAL RATHER THAN A SLOW ANSWER: the set is "everything git calls modified
# or untracked", which on a tree carrying an unignored dependency directory has
# no bound at all - and an identity that costs more than the measurement it saves
# is not one worth taking. Refusing leaves the caller measuring, which is the
# direction that cannot produce a wrong verdict.
CONTENT_READ_LIMIT = 4000

# One version in front of every identity this module mints. A later spelling of
# the payload would otherwise be free to collide with this one, and a collision
# here is a verdict repeated over a tree it was never taken on.
IDENTITY_VERSION = 1


def _git_fields(project, args):
    """git's NUL-separated output as a list of fields, or None when it will not
    answer.

    None for `porcelain`'s reason and with its force: an empty list is a real
    answer about a real tree, and handing one back for a directory git refused to
    describe is the false clean sheet this file is against.
    """
    try:
        out = subprocess.run(["git", "-C", project] + list(args),
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=120)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return [f for f in out.stdout.decode("utf-8", "replace").split("\0") if f]


def _outside(excluded):
    """A predicate: is this path under one of `excluded`?

    Prefix matching on a SEGMENT boundary, so `docs/audit` does not swallow
    `docs/audit-notes.md` - a silent widening here would drop real source out of
    the identity and is the direction that produces a wrong match.
    """
    prefixes = [p.strip("/") for p in (excluded or [])
                if isinstance(p, str) and p.strip()]

    def _drop(path):
        return any(path == pre or path.startswith(pre + "/") for pre in prefixes)
    return _drop


def content_digest(project, excluded=None):
    """`(digest, basis)` - one digest over every byte git reports, or None and why.

    `excluded` is the paths the CALLER writes and must not be judged by, as
    project-relative prefixes; they travel INSIDE the digest, so two identities
    taken over different subjects cannot come out equal and read as agreement.

    WHAT IT ESTABLISHES AND WHAT IT DOES NOT is `CONTENT_LIMIT`, which is the
    sentence a caller prints rather than a docstring nobody renders.

    IT DISCRIMINATES MORE FINELY THAN CONTENT IN ONE PLACE, and that is worth
    knowing rather than discovering: the same bytes staged and unstaged are two
    entries of different shapes here - git's blob id on one side, this file's own
    file digest on the other - so `git add` alone moves the answer. A caller
    reads that as "not the same tree" and measures again, which costs time and
    can never cost a wrong verdict; the reverse error is the one that cannot be
    afforded, so this is the side to be wrong on.
    """
    drop = _outside(excluded)
    index = _git_fields(project, ("ls-files", "-s", "-z"))
    differing = _git_fields(project, ("ls-files", "-z", "--modified",
                                      "--deleted", "--others",
                                      "--exclude-standard"))
    if index is None or differing is None:
        return None, ("git would not list this tree, so its content is not "
                      "established and nothing measured on it can be repeated")
    tracked = []
    for entry in index:
        head, sep, path = entry.partition("\t")
        if not sep:
            # REFUSED, NOT SKIPPED. Every `ls-files -s` entry carries a tab, so
            # one that does not means this output is not the output being read -
            # and dropping it would quietly narrow the identity to whatever git
            # happened to print.
            return None, ("git printed an index entry with no path in it (%r), "
                          "so this tree was not read whole" % (entry[:60],))
        if drop(path):
            continue
        tracked.append([path, head])
    paths = sorted(set(p for p in differing if not drop(p)))
    if len(paths) > CONTENT_READ_LIMIT:
        return None, ("%d path(s) differ from the index or are untracked, which "
                      "is more than this identity opens; the tree's content is "
                      "left unestablished rather than half-read"
                      % (len(paths),))
    current = [[p, _journal_io.file_hash(os.path.join(project, p))]
               for p in paths]
    left_out = sorted(set(p for p in (excluded or [])
                          if isinstance(p, str) and p.strip()))
    basis = ("git listed %d tracked path(s) and read %d path(s) that differ "
             "from the index or are untracked" % (len(tracked), len(current)))
    if left_out:
        basis = ("%s; %d path(s) the caller writes itself were left out: %s"
                 % (basis, len(left_out), _output.some_of(left_out)))
    return _digest([sorted(tracked), current, left_out]), basis


def identity_of(parts):
    """`<version>:<digest>` over `parts`, or None when nothing could be hashed.

    ONE SPELLING FOR EVERY IDENTITY MINTED HERE, so two of them cannot be hashed
    two ways, and the version is in FRONT of the digest rather than only inside
    it: a reader comparing two of these by eye has to be able to see that they
    are answers to the same question before they read the hex.
    """
    packed = _digest(parts)
    return None if packed is None else "%d:%s" % (IDENTITY_VERSION, packed)


# --- the stamp a verification carries ------------------------------------------
# A STAMP IS THE THREE IDENTITY FIELDS PLUS THE SCOPE THAT PRODUCED ONE OF THEM.
# The scope travels INSIDE the token rather than being re-typed at comparison
# time, and that is the difference between a check and a ceremony: a comparison
# handed a different file list silently answers about a different question, which
# is the exact failure - acting on a held model of state instead of a read of it -
# that this whole file is for.
STAMP_TOKEN = "audit-stamp:"

# One version, refused rather than guessed at when it is not this one. A token
# from a future spelling is a thing this code cannot read, and reading it
# optimistically is how "unestablished" quietly becomes "current".
STAMP_VERSION = 1

# The verdicts, and the reason there are three of them rather than two.
CURRENT = "current"
STALE = "stale"
UNESTABLISHED = "unestablished"

# ...and the per-field words the verdict is assembled from.
AGREES = "agrees"
MOVED = "moved"
UNANSWERABLE = "unanswerable"
NOT_DECLARED = "not-declared"

# The identity fields, in the order they are printed: the stamp's key, the key
# `tested_state` files its BASIS under, and the LIMIT that bounds what the field
# can say. One table, because a field added to the stamp and forgotten in the
# comparison or in the output is exactly the silence this file is against - and
# the basis key is in it rather than derived by concatenation, which is what
# produced a `basis: None` on two of the three fields the first time this ran.
FIELD_LIMIT = (("head", "headBasis", HEAD_BASIS),
               ("scopeDigest", "scopeBasis", SCOPE_LIMIT),
               ("dirtyDigest", "dirtyBasis", DIRTY_LIMIT))

IDENTITY_FIELDS = tuple(name for name, _key, _limit in FIELD_LIMIT)

VERDICT_HELP = {
    CURRENT: "every field git could answer still agrees with the stamp",
    STALE: "the tree has moved; the fields below say which part of it did",
    UNESTABLISHED: ("git could not answer for at least one field, so this stamp "
                    "could not be graded - which is NOT the same as unchanged"),
}


def declared_scope(owns):
    """The declared paths as a stamp stores them: non-blank strings, deduplicated,
    sorted.

    THE SAME NARROWING `scope_digest` APPLIES, spelled once and called twice,
    because a stamp whose stored scope and whose digest disagreed about which
    files were in play would be a stamp that cannot be re-derived."""
    return sorted(set(f for f in (owns or []) if isinstance(f, str) and f.strip()))


def take(project, owns):
    """`(stamp, state)` for `project` right now - the token, and the full basis.

    The stamp is the machine half, small enough for a commit message; `state` is
    `tested_state`'s dict, which carries the basis sentence for every field and is
    what the human rendering prints. Both come out of ONE reading of the tree, so
    the line a reader is shown and the token they paste cannot describe different
    moments."""
    before = porcelain(project)
    state = tested_state(project, owns, before)
    stamp = {"v": STAMP_VERSION, "scope": declared_scope(owns),
             "head": state["head"], "scopeDigest": state["scopeDigest"],
             "dirtyDigest": state["dirtyDigest"]}
    return stamp, state


def format_stamp(stamp):
    """The one line a report, a commit message or an agent's reply carries.

    One line because that is what survives being pasted into prose: a
    pretty-printed block loses its indentation in a quoted reply and stops
    parsing, and this token has to come back out of text somebody else wrote."""
    return "%s %s" % (STAMP_TOKEN,
                      json.dumps(stamp, sort_keys=True, separators=(",", ":")))


def parse_stamp(text):
    """`(stamp, problem)` - exactly one of the two is None.

    READS A STAMP OUT OF ARBITRARY TEXT, because that is where stamps live: a
    commit message, a report paragraph, an agent's reply. The token anchors it and
    the rest of that line is the JSON.

    TWO STAMPS IN ONE TEXT IS A REFUSAL, NOT A CHOICE. Picking the first or the
    last would be this module guessing which verification the reader meant, and a
    wrong guess here grades a claim against a tree it was never taken on. The
    caller is told to say which.
    """
    if not isinstance(text, str) or STAMP_TOKEN not in text:
        return None, ("no %r token in the text given, so there is no stamp to "
                      "grade" % (STAMP_TOKEN,))
    hits = [line for line in text.splitlines() if STAMP_TOKEN in line]
    if len(hits) > 1:
        return None, ("%d lines carry a %r token; pass the one stamp this claim "
                      "was taken with rather than the whole document"
                      % (len(hits), STAMP_TOKEN))
    tail = hits[0].split(STAMP_TOKEN, 1)[1].strip()
    try:
        stamp = json.loads(tail)
    except ValueError as exc:
        return None, "the text after %r is not JSON: %s" % (STAMP_TOKEN, exc)
    if not isinstance(stamp, dict):
        return None, ("the text after %r is %s, not an object"
                      % (STAMP_TOKEN, type(stamp).__name__))
    if stamp.get("v") != STAMP_VERSION:
        return None, ("this stamp is version %r and this code reads version %d; "
                      "re-take the verification rather than grading it against a "
                      "spelling nothing here can read"
                      % (stamp.get("v"), STAMP_VERSION))
    scope = stamp.get("scope")
    if not isinstance(scope, list) or any(not isinstance(f, str) for f in scope):
        return None, ("the stamp's `scope` is not a list of paths, so the scope "
                      "digest cannot be re-derived and no comparison would mean "
                      "anything")
    for name in IDENTITY_FIELDS:
        value = stamp.get(name)
        if value is not None and not isinstance(value, str):
            return None, ("the stamp's %r is %s; an identity field is a string or "
                          "null and nothing else" % (name, type(value).__name__))
    return stamp, None


def field_state(name, was, now, declared):
    """One field's word: it agrees, it moved, nothing could answer it, or nothing
    was ever declared for it to be about.

    NULL ON EITHER SIDE IS `unanswerable` AND NEVER `agrees`, which is the whole
    rule this function exists to hold. Two absent answers are two absences, not an
    agreement - the comparison `None == None` is True in Python and false in
    English, and reading it the Python way is how a tree git could not describe
    comes to be reported as a tree that had not changed.

    `not-declared` is separated from `unanswerable` because their causes differ
    and so do their repairs: a scope digest is null when the work declares no
    files, which is a thing the caller chose, and null when git could not read
    them, which is not."""
    if name == "scopeDigest" and not declared:
        return NOT_DECLARED
    if was is None or now is None:
        return UNANSWERABLE
    return AGREES if was == now else MOVED


def compare(stamp, project):
    """Is `project` still the tree `stamp` names? `{verdict, fields, now, state}`.

    THE SCOPE COMES OUT OF THE STAMP and never from the caller, so the comparison
    is over the same file set the stamp was taken over by construction.

    MOVED OUTRANKS UNANSWERABLE. A tree with one field moved and another
    unreadable HAS moved - that much is established - and reporting it as
    ungradeable would hide a fact already in hand. The reverse ordering is the one
    with a hole in it, which is the same asymmetry `running_plugin_verdict` draws
    when it lets drift outrank a matching stamp."""
    now, state = take(project, stamp.get("scope") or [])
    declared = bool(stamp.get("scope"))
    fields = []
    for name, basis_key, limit in FIELD_LIMIT:
        fields.append({"field": name, "was": stamp.get(name), "now": now.get(name),
                       "state": field_state(name, stamp.get(name), now.get(name),
                                            declared),
                       "basis": state.get(basis_key), "limit": limit})
    words = [f["state"] for f in fields]
    if MOVED in words:
        verdict = STALE
    elif UNANSWERABLE in words:
        verdict = UNESTABLISHED
    else:
        verdict = CURRENT
    return {"verdict": verdict, "fields": fields, "now": now, "state": state}


# --- rendering -----------------------------------------------------------------
def render_stamp(stamp, state):
    """The lines `take` prints: every field with its basis, then the token.

    THE BASIS IS ON EVERY FIELD, including the ones that answered. A reader who
    can see what makes a digest true can tell it from a field that was never
    filled in; one who is shown only the hex has to trust it."""
    lines = ["STAMP - the tree this verification was taken on"]
    width = max(len(name) for name in IDENTITY_FIELDS)
    for name, basis_key, limit in FIELD_LIMIT:
        value = stamp.get(name)
        basis = state.get(basis_key)
        lines.append("  %-*s  %s" % (width, name,
                                     value if value is not None
                                     else "(not knowable - see the basis)"))
        lines.append("      basis: %s" % (basis,))
        # HEAD's basis and HEAD's limit are ONE sentence - `HEAD_BASIS` is filed
        # as both - so it is printed once. Two identical lines under two
        # different labels read as two independent statements, which is a claim
        # this field cannot support twice.
        if limit != basis:
            lines.append("      says:  %s" % (limit,))
    lines.append("")
    lines.append("Carry this line with the claim - in the report, the commit "
                 "message, or the")
    lines.append("message back to the orchestrator:")
    lines.append("  %s" % (format_stamp(stamp),))
    return lines


def render_comparison(result):
    """The lines `compare` prints: the verdict, what each field said, the repair."""
    verdict = result["verdict"]
    lines = ["VERDICT: %s - %s" % (verdict, VERDICT_HELP[verdict])]
    width = max(len(name) for name in IDENTITY_FIELDS)
    for entry in result["fields"]:
        lines.append("  %-*s  %s" % (width, entry["field"], entry["state"]))
        if entry["state"] == MOVED:
            lines.append("      was:   %s" % (entry["was"],))
            lines.append("      now:   %s" % (entry["now"],))
        lines.append("      says:  %s" % (entry["limit"],))
    lines.append("")
    if verdict == STALE:
        lines.append("The claim this stamp was taken with is about a tree that no "
                     "longer exists.")
        lines.append("Re-take the verification on the tree as it is now. A stale "
                     "claim is re-taken,")
        lines.append("never argued with - the fields above say which part moved, "
                     "so the re-run")
        lines.append("need only be as wide as that.")
    elif verdict == UNESTABLISHED:
        lines.append("Nothing was established either way, and that is not a pass. "
                     "Fix what stopped")
        lines.append("git answering - a directory that is not a repository, a "
                     "worktree that has been")
        lines.append("removed - and compare again.")
    else:
        lines.append("Every field that could answer still agrees. The `says:` "
                     "lines above bound what")
        lines.append("that covers; nothing outside them was compared.")
    return lines
