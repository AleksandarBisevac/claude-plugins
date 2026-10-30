#!/usr/bin/env python3
"""
Cases for `governance/commit-task-work.py` — the verb that commits ONE task's
work and refuses the rest, and with `--state` a phase's record and none of its
work.

WHAT THIS FILE IS ABOUT, in one line: the commit carries what the task DECLARES
and nothing else. Every case proving it carried a declared file is paired with
one proving it left a sibling's file alone, because either half on its own also
passes for a command that committed everything, or for one that committed
nothing. Where the claim is "this is durable" the pair is asserted against a
FRESH CLONE checked out at the commit — reading the working tree cannot tell a
file that was committed from one merely left lying there, which is the exact
distinction this command exists to draw.

THE FIXTURE IS `test__invariants.build()`, reused for its siblings' reason: that
suite GRADES the commits this command makes (`_invariants.commit_scope`), so if
the two started from different repositories the grader would be reading a shape
the writer never produces. The last case here closes that loop by running the
grader over a commit this command really made.

WHY THE REFUSALS ARE PAIRED WITH THE STAGED LIST. A command that refused every
run would pass a refusals-only suite while being useless, so the accepting case
sits beside each refusal — and the index refusal is asserted to be its OWN
sentence, because reporting the expensive mistake in the same words as a stray
README is what makes a reader skim past it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import platform
import re
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _evidence_io                                # noqa: E402
import _invariants                                 # noqa: E402
import _journal_io                                 # noqa: E402
import _loader                                     # noqa: E402
import _locks                                      # noqa: E402
import _manifest_io as _mio                        # noqa: E402
import _panel_write                                # noqa: E402
import _scoped_commit                              # noqa: E402
import test__invariants as TI                      # noqa: E402  (the ONE git fixture)
import test_audit_task as TAT                      # noqa: E402  (_remedy_verdict: the one
#                                                    predicate a refusal's ways past are held to)

M = _loader.load_script("commit-task-work.py", "ctw")
# THE REAL RECORDER, driven in-process. A verdict the commit is bound to has to be
# one `run-test-gate.py --record` wrote, or these cases would be grading the
# committer against a row shape the recorder never produces.
RTG = _loader.load_script("run-test-gate.py", "rtg_for_ctw")
# THE REAL `start`, for the same reason: the snapshot an attempt is attributed
# by is the one that verb records.
AT = _loader.load_script("audit-task.py", "at_for_ctw")

PHASE = "P1"
TASK = "P1.1"
OWNED = "src/a.py"
SIBLING = "src/b.py"
SHARD_REL = "docs/audit/phases/P1.json"
INDEX_REL = "docs/audit/audit-plan.json"
RECORD_DIRS = ("docs/audit/evidence", "docs/audit/journal")
IGNORED_DIR = "ign"
IGN_TRACKED = "ign/t.md"
IGN_UNTRACKED = "ign/new.md"
RENAMED = "src/a2.py"


# --- commitlint's default `subject-case`, transcribed --------------------------
# THE RULE, NOT A READING OF IT, transcribed once for both commits this verb
# makes. `@commitlint/config-conventional` sets `subject-case` to `never` these
# four: sentence-case, start-case, pascal-case, upper-case. `ensureCase` in
# `@commitlint/ensure` decides each one by TRANSFORMING the subject and asking
# whether the result IS the subject, so the transforms are what is written below
# and the assertion is the question commitlint asks.
#
# THE WORD SPLIT IS lodash's ONLY NEAR ENOUGH, AND IT CANNOT PRODUCE A FALSE PASS:
# each of the four transforms capitalises the subject's FIRST character, so a
# lowercase-initial subject differs from all four under any word split
# whatsoever. The only error a rougher splitter can make is a false RED.
_LODASH_WORDS_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|[0-9]+")


def _upper_first(text):
    return text[:1].upper() + text[1:]


def _sentence_case(text):
    return _upper_first(text.lower())


def _start_case(text):
    return " ".join(_upper_first(word)
                    for word in _LODASH_WORDS_RE.findall(text))


def _camel_case(text):
    words = [word.lower() for word in _LODASH_WORDS_RE.findall(text)]
    if not words:
        return ""
    return "".join([words[0]] + [_upper_first(w) for w in words[1:]])


def _pascal_case(text):
    return _upper_first(_camel_case(text))


def _upper_case(text):
    return text.upper()


FORBIDDEN_CASES = (("sentence-case", _sentence_case),
                   ("start-case", _start_case),
                   ("pascal-case", _pascal_case),
                   ("upper-case", _upper_case))

# `header-max-length`, another of the same default set.
HEADER_MAX_LENGTH = 100


def header_offences(header):
    """The names of the cases commitlint's default `subject-case` refuses
    `header`'s subject for. `[]` is the pass; `["no-subject"]` for a header
    with no `: ` or an empty subject, which equals every transform above and
    would otherwise read as four case violations."""
    subject = header.split(": ", 1)[1] if ": " in header else None
    if not subject:
        return ["no-subject"]
    return [name for name, transform in FORBIDDEN_CASES
            if transform(subject) == subject]


# --- fixtures -----------------------------------------------------------------
class Repos(object):
    """A fresh repository per call, torn down at the end.

    NOT `test__invariants`' caching version: every case here MUTATES git — it
    commits — so two cases sharing a repository would be two cases sharing a
    history, and the second one's `HEAD` assertions would be about the first
    one's work.
    """

    def __init__(self):
        self.tmp = _harness.fixture_root("audit-commit-task-")
        self.made = 0

    def make(self, **opts):
        self.made += 1
        root = os.path.join(self.tmp, "r%d" % (self.made,), "repo")
        os.makedirs(root)
        return _unclosed(_mirrored(TI.build(root, **opts)))

    def scratch(self, name):
        return os.path.join(self.tmp, "scratch-%s" % (name,))

    def close(self):
        _harness.remove_tree(self.tmp)


def _mirrored(fx):
    """`fx` with each index stub mirroring its committed shard, in a fixture
    commit of the index alone - the state the plugin's own writers keep
    (`_manifest_io.stale_stubs` reports any other). The shared builder commits
    stubs that disagree with their shards, and under the owned-part invariant
    every commit carrying a shard would then carry its stub's mirror too,
    which is right for a plan in that state and noise for a case about
    something else. The working tree is left as the builder left it."""
    index = _mio.read_json(fx["manifest"])
    moved = False
    for stub in index.get("phases") or []:
        shard = _invariants.json_at(fx["root"], "HEAD",
                                    "docs/audit/" + str(stub.get("shard", "")))
        for key in _mio._STUB_KEYS:
            if isinstance(shard, dict) and key in shard \
                    and stub.get(key) != shard[key]:
                stub[key] = shard[key]
                moved = True
    if moved and not TI._git(fx["root"], "status", "--porcelain", "--",
                             INDEX_REL).strip():
        TI._write_json(fx["manifest"], index)
        TI._git(fx["root"], "commit", "-q", "-m",
                "fixture: the stubs mirror their shards", "--", INDEX_REL)
    return fx


def _unclosed(fx):
    """`fx` with the task under test recorded `done` and NO commit yet, in the
    working shard - the older close order this suite's cases drive (status
    first, then the commit `done --commit` would record). The shared builder
    also writes P1.1's commit into that shard, which is a task already closed
    against it, and the committer refuses a work commit for one of those."""
    shard = _mio.read_json(fx["shard"])
    for task in shard.get("tasks") or []:
        if task.get("id") == TASK and task.get("status") == "done":
            task["commit"] = None
    TI._write_json(fx["shard"], shard)
    return fx


def _own_repos(fn):
    """A block of cases that builds its own `Repos`, so it can run as a stage of
    its own: `fn(check, repos)` becomes `(check)` and the repositories are torn
    down when it ends, however it ends."""
    def staged(check):
        repos = Repos()
        try:
            fn(check, repos)
        finally:
            repos.close()
    staged.__name__ = fn.__name__
    return staged


def _run(fx, task=TASK, *extra):
    """`(exitCode, printedText)` for one invocation, stderr swallowed.

    stderr is swallowed rather than left to escape because the usage cases
    deliberately provoke it, and a real ERROR line in the middle of a green suite
    reads to whoever is scrolling the log exactly like a failure.
    """
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main([fx["manifest"], task, "--project", fx["root"]]
                      + list(extra), out=lines.append)
    finally:
        sys.stderr = held
    return code, "\n".join(lines)


def _head(fx):
    return TI._head(fx["root"])


def _untrack_config(fx):
    """The fixture's `.claude/audit.config.json` stays on disk and leaves git's
    index, in a commit of its own: a project that does not commit it, which is
    the shape of a config a session or the panel creates."""
    TI._git(fx["root"], "rm", "--cached", "-q", "--",
            ".claude/audit.config.json")
    TI._git(fx["root"], "commit", "-q", "-m",
            "chore: the project does not commit its config")


def _clone_at(fx, sha, dest):
    """A fresh clone, checked out at `sha`. Returns the clone's path."""
    TI._git(None, "clone", "--quiet", "--no-hardlinks", fx["root"], dest)
    TI._git(dest, "checkout", "--quiet", sha)
    return dest


def _read(path):
    """The file's text, or None when it is not there — the two are different
    findings and a raised IOError would hide which case failed."""
    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (IOError, OSError):
        return None


def _write(path, text):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _staged(fx):
    return [ln for ln in TI._git(fx["root"], "diff", "--cached",
                                 "--name-only").splitlines() if ln.strip()]


def _carried(fx, sha):
    return sorted(ln.strip() for ln in
                  TI._git(fx["root"], "show", "--name-only", "--pretty=format:",
                          sha).splitlines() if ln.strip())


def _task_rows(fx):
    return [r for r in _journal_io.read_all(fx["root"])
            if r.get("action") == M.ACTION_TASK_COMMITTED]


def _row_files(fx, action=None):
    """The git-root-relative journal files holding a row of `action`."""
    action = action or M.ACTION_TASK_COMMITTED
    return sorted(set("docs/audit/journal/%s" % (r["_file"],)
                      for r in _journal_io.read_all(fx["root"])
                      if r.get("action") == action))


def _trailer_of(fx, sha):
    """The `Audit-Row` values the commit message of `sha` carries."""
    prefix = "%s: " % (_invariants.ROW_TRAILER,)
    return [ln[len(prefix):].strip() for ln in TI._git(
        fx["root"], "log", "-1", "--format=%B", sha).splitlines()
        if ln.startswith(prefix)]


def _dirty_work(fx):
    """What a finished task leaves: the declared file edited, a SIBLING task's
    file edited beside it, and a stray nobody declares.

    THE THREE TOGETHER ARE THE FIXTURE. With only the declared file, a command
    that staged the whole working tree would pass every case below; the sibling
    is the scope breach step 4c describes, and the stray is the "obviously part
    of the change" one.
    """
    _write(os.path.join(fx["root"], OWNED), "a = 2  # the task's own work\n")
    _write(os.path.join(fx["root"], SIBLING), "b = 2  # somebody else's task\n")
    _write(os.path.join(fx["root"], "src", "stray.py"), "stray = 1\n")


def _phase_and_task(fx, tid=TASK):
    manifest = _mio.load_manifest(fx["manifest"])
    for phase, task in _mio.iter_tasks(manifest):
        if task.get("id") == tid:
            return manifest, phase, task
    raise RuntimeError("fixture lost %s" % (tid,))


def _set_task(fx, files=None, gate=None, phase_gate=None, basis=None,
              rows=True):
    """Rewrite the fixture task's `files` and/or `tests.gate` (and
    `tests.gateBasis` when `basis` is given) in its shard, and the phase's
    `testGate` when `phase_gate` is given. Left uncommitted, which is what a task
    that widened its scope mid-run looks like.

    A widened `files` also writes the fileIndex rows it needs and, with
    `rows`, commits the index alone in a fixture commit, so a case about
    something else starts from a HEAD whose pair already validates.
    `rows=False` leaves the index as it was."""
    shard = _mio.read_json(fx["shard"])
    task = [t for t in shard["tasks"] if t.get("id") == TASK][0]
    if files is not None:
        task["files"] = list(files)
        if rows:
            index = _mio.read_json(fx["manifest"])
            for entry in files:
                refs = index["fileIndex"].setdefault(entry.split(":")[0], [])
                if TASK not in refs:
                    refs.append(TASK)
            TI._write_json(fx["manifest"], index)
            if TI._git(fx["root"], "status", "--porcelain", "--", INDEX_REL):
                TI._git(fx["root"], "commit", "-q", "-m",
                        "fixture: the widened scope's index rows", "--",
                        INDEX_REL)
    if gate is not None:
        task["tests"]["gate"] = list(gate)
    if basis is not None:
        task["tests"]["gateBasis"] = basis
    if phase_gate is not None:
        shard["testGate"] = list(phase_gate)
    TI._write_json(fx["shard"], shard)


def _gate(fx, manifest=None, task=TASK, set_apart=True, reuse=False):
    """Run the gate through `run-test-gate.py --record` and return `(code, text)`.

    `set_apart` commits the ledger and journal files the recording wrote, in a
    fixture commit of their own, so a case asserting a task commit's WHOLE file
    list is asserting the work and not the record beside it; the shard, which
    now carries the pointer, is left for the task commit as in a real run.
    `task=None` runs the PHASE-scope gate, which is what sign-off records.
    """
    argv = [manifest or fx["manifest"], PHASE, "--record",
            "--project-dir", fx["root"]]
    if task is not None:
        argv.extend(["--task", task])
    if not reuse:
        argv.append("--no-reuse")
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = RTG.main(argv, out=lines.append)
    finally:
        sys.stderr = held
    if set_apart:
        written = [ln[3:] for ln in TI._git(
            fx["root"], "status", "--porcelain", "-uall", "--",
            *RECORD_DIRS).splitlines() if ln.strip()]
        if written:
            TI._git(fx["root"], "add", "--", *written)
            TI._git(fx["root"], "commit", "-q", "-m",
                    "chore: the gate's record, set apart", "--", *written)
    return code, "\n".join(lines)


def _newest_row(fx, tid=TASK):
    rows = [r for r in _evidence_io.read_rows(fx["root"])["rows"]
            if r.get("taskId") == tid]
    return rows[-1] if rows else {}


def _ignored_dir(fx):
    """A `.gitignore`d directory holding one TRACKED file, committed.

    The tracked file is force-added once, which is how a project comes to track
    something under a directory it otherwise ignores - a vendored file, a
    skill under an ignored config tree.
    """
    _write(os.path.join(fx["root"], ".gitignore"), "%s/\n" % (IGNORED_DIR,))
    os.makedirs(os.path.join(fx["root"], IGNORED_DIR))
    _write(os.path.join(fx["root"], IGN_TRACKED), "v1\n")
    TI._git(fx["root"], "add", "--", ".gitignore")
    TI._git(fx["root"], "add", "-f", "--", IGN_TRACKED)
    TI._git(fx["root"], "commit", "-q", "-m",
            "fixture: a tracked file under an ignored directory", "--",
            ".gitignore", IGN_TRACKED)


def _const(name):
    """A constant of the command under test, or a string no output contains.

    So a case naming a sentence the command does not define yet FAILS on its own
    assertion instead of raising and taking every case after it down too.
    """
    return getattr(M, name, "\0no %s on this build" % (name,))


def _index_entries(fx):
    """The index as `ls-files -s` prints it: mode, blob, stage and path per
    entry - the bytes a restore has to have put back, not just the path list."""
    return TI._git(fx["root"], "ls-files", "-s").splitlines()


def _tree(fx, sha):
    return TI._git(fx["root"], "ls-tree", "-r", "--name-only", sha).split()


def _name_status(fx, sha):
    return TI._git(fx["root"], "show", "-M", "--name-status", "--format=",
                   sha).splitlines()


# --- cases --------------------------------------------------------------------
# The staged blocks each build their own repositories: one process per block.
@_own_repos
def _ordinary_cases(check, repos):
    """The ordinary run, its subject, the index and the foreign-path refusals."""
    # --- the ordinary run --------------------------------------------------
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    before = _head(fx)
    recorded_before = _phase_and_task(fx)[2].get("commit")
    code, text = _run(fx)
    after = _head(fx)
    check("ctw1 a finished task's work is committed and the SHA is REPORTED "
          "- `/audit:task done --commit <sha>` is the next step and a caller "
          "told 'committed' with nothing to pass it would close the task "
          "against no commit at all: %r / %r" % (code, text),
          code == 0 and after != before and after[:12] in text)

    carried = _carried(fx, after)
    check("ctw2 ...and the commit carries the task's declared file, the "
          "phase's manifest file and the journal file holding the row that "
          "names it, and NOTHING else - asserted as the whole file list, "
          "because a commit that swept the sibling in beside them also "
          "contains all three: %r" % (carried,),
          len(_row_files(fx)) == 1
          and carried == sorted([OWNED, SHARD_REL] + _row_files(fx)))

    clone = _clone_at(fx, after, repos.scratch("ordinary"))
    check("ctw3 ...and the pair a clone proves: the declared file's NEW bytes "
          "are in the commit, and the sibling task's edit and the undeclared "
          "stray are not - both sat modified in the same working tree and "
          "stayed there, which is the whole of what prose could not refuse: "
          "%r" % (_read(os.path.join(clone, OWNED)),),
          _read(os.path.join(clone, OWNED)) == "a = 2  # the task's own work\n"
          and _read(os.path.join(clone, SIBLING)) == "b = 1\n"
          and _read(os.path.join(clone, "src", "stray.py")) is None)

    check("ctw4 ...and nothing was left staged for the next `git commit` to "
          "sweep up, which is the condition step 4c's pathspec exists for: %r"
          % (_staged(fx),),
          _staged(fx) == [])

    check("ctw5 ...and it does NOT write `task.commit` - the SHA is only "
          "knowable after this commit and the shard is inside it, so writing "
          "it here would need a second commit or the amend step 4c forbids. "
          "`/audit:task done` records it and rides along with the next one. "
          "Asserted as UNCHANGED rather than absent, because the fixture's "
          "task already carries one and `is None` would have passed on a "
          "command that wrote nothing at all: %r -> %r"
          % (recorded_before, _phase_and_task(fx)[2].get("commit")),
          _phase_and_task(fx)[2].get("commit") == recorded_before
          and recorded_before != after)

    rows = _task_rows(fx)
    details = rows[0].get("details") if rows else {}
    nonce = details.get(_invariants.NONCE_KEY)
    resolved, _why = _invariants.commits_carrying(fx["root"], [nonce])
    check("ctw6 the commit anchors itself with exactly one journal row "
          "carrying a nonce, the task and the phase, and the nonce resolves "
          "to THIS commit through its `Audit-Row` trailer - between this "
          "commit and `/audit:task done` there is otherwise a commit nothing "
          "points at, and a run that dies in the gap leaves one for ever: "
          "%r -> %r" % (details, resolved),
          len(rows) == 1 and (resolved or {}).get(nonce) == [after]
          and _trailer_of(fx, after) == [nonce]
          and details.get("taskId") == TASK
          and details.get("phaseId") == PHASE)
    check("ctw7 ...and all three keys are on `_journal_io.DETAILS_KEYS`, "
          "checked rather than assumed: the allow-list silently DROPS a key "
          "it does not know, so a row could carry none of them and the case "
          "above would still see the action go by",
          all(key in _journal_io.DETAILS_KEYS
              for key in (_invariants.NONCE_KEY, "taskId", "phaseId")),
          repr(sorted(_journal_io.DETAILS_KEYS)))

    # --- the subject a commitlint repository will take ---------------------
    subject = TI._git(fx["root"], "log", "-1", "--format=%s").strip()
    check("ctw8 the scope is the TASK id and the type is the manifest's - "
          "which is what tells this class from the state commit, whose scope "
          "is a fixed literal with the phase id after it: %r" % (subject,),
          subject.startswith("chore(%s): %s" % (TASK, M.SUBJECT_LEAD))
          and TASK in subject)
    check("ctw9 ...and the SUBJECT git recorded is out of reach of every case "
          "commitlint's default `subject-case` forbids and inside its header "
          "cap: the id leading a lowercase sentence IS sentence-case, so the "
          "subject opens with a fixed lowercase word this command owns: %r"
          % (header_offences(subject),),
          header_offences(subject) == []
          and len(subject) <= HEADER_MAX_LENGTH)

    # --- the grader agrees with the writer ---------------------------------
    # THE LOOP THIS SUITE EXISTS TO CLOSE. `commit_scope` re-derives the same
    # allow-list from git afterwards, so a commit this command made must be
    # one that grader calls clean - the two lists are written against one
    # paragraph, and nothing but this compares them.
    _manifest, phase, task = _phase_and_task(fx)
    task["commit"] = after
    graded = _invariants.commit_scope(
        phase, fx["root"], ".", SHARD_REL, INDEX_REL,
        "docs/audit/journal", "docs/audit/evidence")
    check("ctw10 the invariant checker that GRADES these commits calls this "
          "one clean - the writer and the grader derive one allow-list twice "
          "and nothing else compares them: %r"
          % (graded.get("breaches"),),
          not graded.get("breaches"))

    # --- the index, which is its own refusal -------------------------------
    fx = repos.make()
    _dirty_work(fx)
    index = _mio.read_json(fx["manifest"])
    index["meta"]["title"] = "touched"
    TI._write_json(fx["manifest"], index)
    TI._git(fx["root"], "add", INDEX_REL)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw11 the manifest INDEX staged beforehand is refused, and the "
          "refusal NAMES it and says what it costs - two parallel phases "
          "conflicting on merge is the property the sharded layout was "
          "introduced to buy, and reporting that in the same words as a "
          "stray README is what makes a reader skim past it: %r" % (text,),
          code == 1 and INDEX_REL in text
          and "--state" in text)
    check("ctw12 ...and it refused BEFORE staging, so the git index is "
          "exactly as it was found and no commit was made - a refusal that "
          "had already staged the work would leave the tree in a state the "
          "operator did not ask for: %r / %r" % (_staged(fx), _head(fx)),
          _staged(fx) == [INDEX_REL] and _head(fx) == before)

    # --- and the generic foreign path, which is a different sentence -------
    fx = repos.make()
    _dirty_work(fx)
    TI._git(fx["root"], "add", "src/stray.py")
    before = _head(fx)
    code, text = _run(fx)
    check("ctw13 a path outside the allow-list that somebody else had staged "
          "is NAMED in the refusal: 'something is staged that should not be' "
          "sends a reader to find it, and finding it is the step that gets "
          "skipped: %r" % (text,),
          code == 1 and "src/stray.py" in text and _head(fx) == before)
    check("ctw14 ...and that sentence is NOT the index one - the two "
          "mistakes cost different things and a reader must be able to tell "
          "at a glance which they made",
          "--state" not in text, repr(text))

    # --- nothing to do, and the two ways of it -----------------------------
    fx = repos.make()
    # The fixture leaves its last shard write uncommitted, which is what a
    # finished task really looks like - so it is put back here rather than
    # left, because the state under test is a tree with nothing in it for
    # this commit to carry and not a tree that happens to be dirty. Committed
    # with the task still unclosed (`_unclosed`), so the case reaches the
    # do-nothing answer rather than the closed-task refusal ahead of it.
    TI._git(fx["root"], "checkout", "--", SHARD_REL)
    _unclosed(fx)
    TI._git(fx["root"], "commit", "-q", "-m", "fixture: P1.1 unclosed", "--",
            SHARD_REL)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw15 a clean tree makes NO commit and says which of the "
          "do-nothing states it was - a stream of empty commits is how a "
          "record stops being read, and exit 0 because a healthy project "
          "reported as broken is a step somebody deletes: %r / %r"
          % (code, text),
          code == 0 and _head(fx) == before
          and "already in git" in text)


@_own_repos
def _declared_cases(check, repos):
    """Declared files that are absent, the allow-list asked directly."""
    # --- a declared file that is not there ---------------------------------
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, files=[OWNED, "src/not-written-yet.py", "src/a.py:10-20"])
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    check("ctw16 a declared file that is neither on disk nor tracked is "
          "REPORTED and passed over rather than failing the commit - the "
          "red-first workflow names the case it will write before anything "
          "is there, and `git add` does not shrug at a pathspec matching "
          "nothing, it fails the whole staging call: %r / %r" % (code, text),
          code == 0 and after != before
          and "src/not-written-yet.py" in text)
    check("ctw17 ...and a `:line-range` suffix is stripped before the path "
          "reaches git, which has never heard of one - staging "
          "`a/b.py:10-20` would either fail or, worse, match nothing and "
          "leave the real file uncommitted: %r" % (_carried(fx, after),),
          _carried(fx, after) == sorted([OWNED, SHARD_REL]
                                        + _row_files(fx)))

    # --- and the other direction of that same test -------------------------
    fx = repos.make()
    os.remove(os.path.join(fx["root"], OWNED))
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    clone = _clone_at(fx, after, repos.scratch("deleted"))
    check("ctw17b SECOND-DIRECTION CASE: a declared file the task DELETED is "
          "absent from the working tree too, and staging it is exactly how "
          "the deletion gets committed. A skip rule reading the tree alone "
          "would pass every case above and silently drop every deletion a "
          "task ever makes: %r / %r" % (code, _carried(fx, after)),
          code == 0 and after != before
          and OWNED in _carried(fx, after)
          and _read(os.path.join(clone, OWNED)) is None)

    # --- the allow-list itself, asked directly -----------------------------
    fx = repos.make()
    manifest, phase, task = _phase_and_task(fx)
    targets = M.stage_targets(manifest, phase, task, fx["manifest"],
                              fx["root"], fx["root"])
    check("ctw18 the resolved allow-list is the task's declared files plus "
          "the phase's manifest file, and the manifest INDEX is carried "
          "APART so the refusal can name it as the specific mistake it is "
          "rather than as one more stray path: %r"
          % (targets["paths"], ),
          OWNED in targets["paths"] and SHARD_REL in targets["paths"]
          and INDEX_REL not in targets["paths"]
          and targets["indexRel"] == INDEX_REL)
    check("ctw19 ...and `declared` is the subset that came from the task's "
          "own `files`, kept apart so a refusal can say which half of the "
          "list a path failed against: %r" % (targets["declared"],),
          targets["declared"] == [OWNED])
    off = repos.make(journal_off=True)
    off_manifest, off_phase, off_task = _phase_and_task(off)
    off_targets = M.stage_targets(off_manifest, off_phase, off_task,
                                  off["manifest"], off["root"], off["root"])
    check("ctw20 ...and a record directory that does not exist yet is "
          "REPORTED as skipped rather than silently dropped: 'it is outside "
          "the repository' and 'it is not there yet' leave the same commit "
          "behind while being different things to know. The journal is the "
          "exception while it is on - the row this commit writes creates it "
          "and is carried from there - and the pair is the same journal "
          "turned off, where nothing will: %r / %r"
          % (targets["skipped"], off_targets["skipped"]),
          any(M.EVIDENCE_LABEL in line for line in targets["skipped"])
          and not any(M.JOURNAL_LABEL in line for line in targets["skipped"])
          and any(M.JOURNAL_LABEL in line
                  for line in off_targets["skipped"]))

    # --- the records, when there ARE records -------------------------------
    fx = repos.make(leave_dirty=True)
    _gate(fx, set_apart=False)
    code, text = _run(fx)
    after = _head(fx)
    check("ctw21 the evidence a failed gate wrote IS carried - the rows a "
          "commit's pointers name have to travel with the pointers, or a "
          "clone receives a plan referring to runs it does not have: %r"
          % (_carried(fx, after),),
          code == 0
          and any(p.startswith("docs/audit/evidence/")
                  for p in _carried(fx, after)))
    trail_dirty = [ln for ln in TI._git(fx["root"], "status",
                                        "--porcelain").splitlines()
                   if "docs/audit/journal/" in ln]
    check("ctw22 ...and so is the journal row this run appended, which "
          "names the commit by the trailer rather than by a SHA it could "
          "not know, so no journal file is left dirty behind the commit: "
          "%r / %r" % (_carried(fx, after), trail_dirty),
          set(_row_files(fx)) <= set(_carried(fx, after))
          and _row_files(fx) != [] and trail_dirty == [])


@_own_repos
def _declared_record_cases(check, repos):
    """A declared entry that is a record is carried as the record, never as the
    task's own work - the declared half is what the attempt check grades."""
    fx = repos.make()
    journal_file = RECORD_DIRS[1] + "/2026-10.declared.jsonl"
    sibling = "docs/audit/phases/P2.json"
    os.makedirs(os.path.join(fx["root"], RECORD_DIRS[1]), exist_ok=True)
    _write(os.path.join(fx["root"], journal_file), "{}\n")
    _set_task(fx, files=[OWNED, journal_file, SHARD_REL, INDEX_REL, sibling],
              rows=False)
    manifest, phase, task = _phase_and_task(fx)
    targets = M.stage_targets(manifest, phase, task, fx["manifest"],
                              fx["root"], fx["root"])
    check("a declared journal file, a declared phase shard and the sharded "
          "index are staged as records, not refused as declared work (none of "
          "them is in `declared`, which is the half the attempt check grades "
          "for older dirt; the journal file travels in its record directory "
          "and the shard as the phase's file): %r" % (targets,),
          journal_file not in targets["declared"]
          and SHARD_REL not in targets["declared"]
          and INDEX_REL not in targets["declared"]
          and RECORD_DIRS[1] in targets["paths"]
          and journal_file not in targets["paths"]
          and targets["paths"].count(SHARD_REL) == 1)
    check("a declared journal file, a declared phase shard and the sharded "
          "index are staged as records, not refused as declared work (the "
          "index rides the record rule, which carries it only for a bug link "
          "it completes, and another phase's shard is not this commit's at "
          "all - each passed over by name, not in silence): %r" % (targets,),
          INDEX_REL not in targets["paths"]
          and targets["indexRel"] == INDEX_REL
          and sibling not in targets["paths"]
          and sibling not in targets["declared"]
          and any(sibling in line for line in targets["skipped"])
          and any(INDEX_REL in line for line in targets["skipped"]))
    # The other direction: a rule that read every declared entry as a record
    # would pass both cases above and commit none of the task's work.
    check("a declared journal file, a declared phase shard and the sharded "
          "index are staged as records, not refused as declared work (ALLOW: "
          "the task's own file beside them is still its declared work, the "
          "only entry there): %r" % (targets["declared"],),
          targets["declared"] == [OWNED] and OWNED in targets["paths"])


@_own_repos
def _records_cases(check, repos):
    """The records carried, the single-file layout, usage and the message."""
    # --- the single-file layout --------------------------------------------
    fx = repos.make()
    single = _mio.load_manifest(fx["manifest"])
    single_path = os.path.join(fx["root"], "docs", "audit", "single.json")
    for phase in single.get("phases") or []:
        phase.pop("shard", None)
    TI._write_json(single_path, single)
    TI._git(fx["root"], "add", "docs/audit/single.json")
    TI._git(fx["root"], "commit", "-q", "-m", "chore: single-file layout")
    _dirty_work(fx)
    single["meta"]["title"] = "touched"
    TI._write_json(single_path, single)
    _gate(fx, manifest=single_path)
    single = _mio.load_manifest(single_path)
    manifest, phase, task = None, None, None
    for cand_phase, cand_task in _mio.iter_tasks(single):
        if cand_task.get("id") == TASK:
            manifest, phase, task = single, cand_phase, cand_task
    targets = M.stage_targets(manifest, phase, task, single_path,
                              fx["root"], fx["root"])
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main([single_path, TASK, "--project", fx["root"]],
                      out=lines.append)
    finally:
        sys.stderr = held
    carried = _carried(fx, _head(fx))
    check("ctw23 in the SINGLE-FILE layout the manifest IS the index, so the "
          "'do NOT stage the index' rule - which is about the SHARDED index a "
          "parallel phase would conflict on - must not refuse the manifest "
          "this commit is required to carry. `indexRel` is None and the file "
          "is in the commit: %r / %r / %r"
          % (targets["indexRel"], code, carried),
          targets["indexRel"] is None and code == 0
          and "docs/audit/single.json" in carried)

    # --- usage --------------------------------------------------------------
    fx = repos.make()
    code, _text = _run(fx, "P9.9")
    check("ctw24 a task id no phase holds is a USAGE error and not a failed "
          "commit - exit 2 is what says the caller typed something wrong "
          "rather than that git refused: %r" % (code,), code == 2)
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main([os.path.join(fx["root"], "no-such.json"), TASK,
                       "--project", fx["root"]], out=lines.append)
    finally:
        sys.stderr = held
    check("ctw25 ...and so is a manifest that will not load: %r" % (code,),
          code == 2)

    # --- the message, asked directly ----------------------------------------
    manifest, phase, task = _phase_and_task(fx)

    def task_message(task_id, subject, manifest, claims=None):
        return _scoped_commit.commit_message(
            *M.message_parts(task_id, subject, manifest), claims=claims)

    check("ctw26 the conventional TYPE comes from `meta.commit.type` - a "
          "task commit carries implementation, so a project's own convention "
          "is the right one for it, unlike a state commit whose type and "
          "scope are fixed literals so `git log` can tell the classes apart",
          task_message(TASK, "s", {"meta": {"commit": {"type": "fix"}}})[0]
          .startswith("fix(%s): " % (TASK,)),
          repr(task_message(TASK, "s",
                                {"meta": {"commit": {"type": "fix"}}})))
    check("ctw27 ...and the fallback is not `feat`: a default that claimed a "
          "feature on work nobody described would be a wrong word written by "
          "a default",
          M.DEFAULT_COMMIT_TYPE != "feat"
          and task_message(TASK, "s", {})[0]
          .startswith("%s(%s): " % (M.DEFAULT_COMMIT_TYPE, TASK)),
          repr(task_message(TASK, "s", {})))
    check("ctw28 the coauthor is its OWN paragraph rather than a second "
          "sentence of the subject line - a list is how it reaches git, one "
          "`-m` each, so the trailer is a trailer",
          task_message(TASK, "s",
                       {"meta": {"commit": {"coauthor": "Co: x"}}})
          == ["chore(%s): %s - s" % (TASK, M.SUBJECT_LEAD), "Co: x"],
          repr(task_message(TASK, "s",
                                {"meta": {"commit": {"coauthor": "Co: x"}}})))

    # --- both commits' messages, as they were before they shared one -------
    # THE EXPECTED LISTS ARE LITERALS read off the code at 571becfd, not built
    # from the constants the command owns: a case that composed its expectation
    # from `SUBJECT_LEAD` would pass for a command that changed the lead. The
    # long subject separates a bounded header from an unbounded one -- a state
    # commit cuts it to fit, a task commit never has.
    _long = "y" * 200
    _claims = "claims:\n1 x"
    _seen = [
        _scoped_commit.commit_message(M.state_header("P9", "why"), "Co: x"),
        _scoped_commit.commit_message(M.state_header("P9", None), None),
        _scoped_commit.commit_message(M.state_header("P9", _long), "Co: x"),
        task_message("P9.1", "why", {"meta": {"commit": {
            "type": "fix", "coauthor": "Co: x"}}}, claims=_claims),
        task_message("P9.1", None, {}),
        task_message("P9.1", _long, {}),
    ]
    _want = [
        ["chore(audit-state): phase P9 - why", "Co: x"],
        ["chore(audit-state): phase P9 - the record of a run, without the "
         "work it ran on"],
        ["chore(audit-state): phase P9 - " + "y" * 57 + " [truncated]", "Co: x"],
        ["fix(P9.1): audit - why", _claims, "Co: x"],
        ["chore(P9.1): audit - the task's own files, and the record beside "
         "them"],
        ["chore(P9.1): audit - " + _long],
    ]
    check("the shared commit_message gives the 571becfd message for a task "
          "commit and a state commit",
          _seen == _want,
          repr([(got, want) for got, want in zip(_seen, _want) if got != want]))

    # THE ORDER AND THE BLANKS, which the literal lists above cannot separate
    # from a composer that appends in another order: claims sit BETWEEN the
    # header and the trailer, and a blank value adds no paragraph at all.
    check("ctw25a the shared composer puts the claims between the header and "
          "the co-author trailer, and a blank claims or co-author adds none",
          _scoped_commit.commit_message("h", "Co: x", "claims:\n1 y")
          == ["h", "claims:\n1 y", "Co: x"]
          and _scoped_commit.commit_message("h", "  ", "") == ["h"]
          and _scoped_commit.commit_message("h", None) == ["h"],
          repr(_scoped_commit.commit_message("h", "Co: x", "claims:\n1 y")))

    check("ctw25b the one derivation of `meta.commit.coauthor` returns a string "
          "with something in it and None for every other shape - blank, absent, "
          "a number, a list, and a `commit` block that is not a mapping",
          _scoped_commit.coauthor_of({"meta": {"commit": {"coauthor": "Co: x"}}})
          == "Co: x"
          and all(_scoped_commit.coauthor_of(m) is None for m in (
              None, {}, {"meta": {"commit": {"coauthor": "  "}}},
              {"meta": {"commit": {"coauthor": 7}}},
              {"meta": {"commit": {"coauthor": ["Co: x"]}}},
              {"meta": {"commit": "Co: x"}},
              {"meta": {"commit": {}}})))

    # --- the refusal builder, both directions -------------------------------
    check("ctw29 SECOND-DIRECTION CASE: with nothing foreign there is NO "
          "refusal, so the caller's branch reads as a question rather than "
          "as a string test - a builder that always returned a sentence "
          "would refuse every run and pass every refusal case above",
          M.foreign_refusal([], {"indexRel": INDEX_REL}) is None
          and M.foreign_refusal(None, {"indexRel": INDEX_REL}) is None)


def _link_bug(fx, tid=TASK, bid="BUG-1"):
    """A bug linked to `tid` the way `audit-task.py add --bug` writes it: the
    task's `bugId` in the shard and the bug's `taskId` in the index, both
    uncommitted."""
    shard = _mio.read_json(fx["shard"])
    for task in shard["tasks"]:
        if task.get("id") == tid:
            task["bugId"] = bid
    TI._write_json(fx["shard"], shard)
    index = _mio.read_json(fx["manifest"])
    index["bugs"] = [{"id": bid, "title": "b", "status": "in_progress",
                      "taskId": tid}]
    TI._write_json(fx["manifest"], index)


@_own_repos
def _bug_link_cases(check, repos):
    """A task commit whose shard links a bug carries the index holding the
    link's other half, so the manifest it records validates - and an index
    change that is no bug link stays out of it."""
    import _manifest_rules as _rules
    fx = repos.make()
    _dirty_work(fx)
    _link_bug(fx)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    carried = _carried(fx, after) if after != before else []
    clone = _clone_at(fx, after, repos.scratch("bug-link"))
    findings = _rules.validate(_mio.load_manifest(
        os.path.join(clone, *INDEX_REL.split("/"))))[0]
    check("ctw82 RED-FIRST: a task commit whose shard links a bug records a "
          "manifest that VALIDATES - read off a fresh clone at the commit, "
          "where a shard carrying `bugId` beside an index whose bug names no "
          "task fails 'link must be reciprocal' - because the commit carries "
          "the index holding the other half: %r"
          % ((code, carried, findings[:2], text[-300:]),),
          code == 0 and INDEX_REL in carried and SHARD_REL in carried
          and findings == [])
    _manifest, phase, task = _phase_and_task(fx)
    task["commit"] = after
    graded = _invariants.commit_scope(
        phase, fx["root"], ".", SHARD_REL, INDEX_REL,
        "docs/audit/journal", "docs/audit/evidence")
    check("ctw83 ...and the grader agrees: `commit_scope` reads the same link "
          "off git and calls the commit clean: %r" % (graded.get("breaches"),),
          not graded.get("breaches"))
    check("ctw84 ...and the output says WHY the index rode along, naming the "
          "link, since a task commit carrying the index is otherwise the "
          "mistake its own refusal describes: %r" % (text[-400:],),
          "BUG-1" in text and INDEX_REL in text)

    # AN INDEX CHANGE THAT IS NO BUG LINK stays out of the commit.
    fx = repos.make()
    _dirty_work(fx)
    index = _mio.read_json(fx["manifest"])
    index["meta"]["title"] = "touched"
    TI._write_json(fx["manifest"], index)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    check("ctw85 SECOND-DIRECTION CASE: an index edited for any other reason "
          "is left out of the task commit and left dirty in the working tree "
          "for the phase's --state commit: %r" % ((code, text[-200:]),),
          code == 0 and after != before
          and INDEX_REL not in _carried(fx, after)
          and INDEX_REL in TI._git(fx["root"], "status", "--porcelain"))


WIDENED = "src/new.py"
OTHER_ROW = "src/d.py"


def _widen(fx, row=True):
    """P1.1's scope widened during its attempt to a new file, written: the
    shard declares it and, with `row`, the working index holds its row -
    neither committed, which is what `/audit:task scope` leaves."""
    _dirty_work(fx)
    _set_task(fx, files=[OWNED, WIDENED], rows=False)
    _write(os.path.join(fx["root"], WIDENED), "n = 1\n")
    if row:
        index = _mio.read_json(fx["manifest"])
        index["fileIndex"][WIDENED] = [TASK]
        TI._write_json(fx["manifest"], index)


def _validates_at(fx, sha, scratch):
    """`(findings, committedIndex)` read off a fresh clone at `sha`."""
    import _manifest_rules as _rules
    clone = _clone_at(fx, sha, scratch)
    path = os.path.join(clone, *INDEX_REL.split("/"))
    return (_rules.validate(_mio.load_manifest(path))[0],
            _mio.read_json(path))


@_own_repos
def _index_row_cases(check, repos):
    """A task whose scope was widened during its attempt is closed: the close
    carries the rows its shard needs beside it, so the committed pair never
    stops validating and no other verb runs first. An index row another phase
    has not committed stays out of the close, and a state commit carries the
    whole index only when the plan it records validates."""
    fx = repos.make()
    _widen(fx)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    carried = _carried(fx, after) if after != before else []
    check("ctw-ir1 a task widened by scope during its attempt, whose fileIndex "
          "row is not committed, COMMITS at its close in one commit, carrying "
          "the index beside the shard, and says why the index rode along, "
          "naming the row and the task: %r" % ((code, carried, text[-400:]),),
          code == 0 and _commits_between(fx, before, after) == 1
          and INDEX_REL in carried and SHARD_REL in carried
          and WIDENED in carried and "%s (%s)" % (WIDENED, TASK) in text)
    findings, committed = (_validates_at(fx, after, repos.scratch("ir-after"))
                           if after != before else (["no commit"], {}))
    check("ctw-ir2 ...and the commit is valid on its own, read off a fresh "
          "clone where validate-manifest finds nothing and the row names the "
          "task, with nothing left staged: %r" % ((findings[:2], _staged(fx)),),
          findings == [] and _staged(fx) == []
          and (committed.get("fileIndex") or {}).get(WIDENED) == [TASK])

    # THE ROWS ARE COMMITTED, and another phase's row is not.
    fx = repos.make()
    _widen(fx)
    TI._git(fx["root"], "commit", "-q", "-m", "fixture: the widened rows",
            "--", INDEX_REL)
    index = _mio.read_json(fx["manifest"])
    index["fileIndex"][OTHER_ROW] = ["P2.1"]
    TI._write_json(fx["manifest"], index)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    findings, committed = _validates_at(fx, after, repos.scratch("ir-other"))
    check("ctw-ir3 SECOND-DIRECTION CASE: with the widened rows committed the "
          "close commits, and it carries no index row belonging to another "
          "phase's uncommitted change - P2.1's row for %s is absent from the "
          "committed index and still uncommitted in the working tree: %r"
          % (OTHER_ROW, (code, text[-200:], findings[:2],
                         sorted(committed.get("fileIndex") or {})),),
          code == 0 and after != before and findings == []
          and INDEX_REL not in _carried(fx, after)
          and OTHER_ROW not in (committed.get("fileIndex") or {})
          and OTHER_ROW in _mio.read_json(fx["manifest"])["fileIndex"]
          and INDEX_REL in TI._git(fx["root"], "status", "--porcelain"))

    # THE WORKING INDEX LACKS THE ROW TOO.
    fx = repos.make()
    _widen(fx, row=False)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw-ir4 a widened shard whose row the WORKING index lacks as well "
          "is refused naming re-derivation first, since committing that index "
          "would carry no row: %r" % ((code, text[-400:]),),
          code == 1 and "%s (%s)" % (WIDENED, TASK) in text
          and "reindex" in text and _head(fx) == before)

    # THE SHARED QUESTION, asked directly.
    owed = getattr(_scoped_commit, "index_rows_owed", None)
    shard = _mio.read_json(fx["shard"])
    plain = json.loads(json.dumps(shard))
    plain["tasks"][0]["files"] = ["%s:1-2" % (OWNED,)]
    answer = (owed(TI.INDEX, shard), owed(TI.INDEX, plain)) if owed else None
    check("ctw-ir5 the shared check names the owed row as `(path, taskId)` and "
          "answers an empty list - not None - for a shard the index pairs, a "
          "`:line-range` entry matched by its path the way the validator "
          "matches it: %r" % (answer,),
          answer == ([(WIDENED, TASK)], []))

    # THE STATE COMMIT, in the other direction: a row ANOTHER phase's committed
    # shard needs. This phase's own rows are re-derived from its shard, so only
    # another phase's can be dropped.
    other_path, other_task = "src/c.py", "P2.1"
    fx = repos.make()
    index = _mio.read_json(fx["manifest"])
    del index["fileIndex"][other_path]
    index["meta"]["title"] = "touched"
    TI._write_json(fx["manifest"], index)
    before = _head(fx)
    scode, stext = _state(fx)
    after = _head(fx)
    held = (_mio.read_json(os.path.join(_clone_at(
        fx, after, repos.scratch("ir-drop")), *INDEX_REL.split("/")))
        if after != before else {})
    check("ctw-ir6 a state commit whose working index would drop a row another "
          "phase's committed shard still declares carries only the part this "
          "phase owns, naming the row: the committed index still holds the row "
          "and the title it had: %r" % ((scode, stext[-400:]),),
          scode == 0 and after != before
          and "%s (%s)" % (other_path, other_task) in stext
          and (held.get("fileIndex") or {}).get(other_path) == [other_task]
          and (held.get("meta") or {}).get("title") != "touched")
    index["fileIndex"][other_path] = [other_task]
    TI._write_json(fx["manifest"], index)
    scode, stext = _state(fx)
    later = _head(fx)
    whole = (_mio.read_json(os.path.join(_clone_at(
        fx, later, repos.scratch("ir-whole")), *INDEX_REL.split("/")))
        if later != after else {})
    check("ctw-ir7 ALLOW: the same index keeping that row is carried WHOLE by "
          "the next state commit, title included: %r" % ((scode, stext[-200:]),),
          scode == 0 and later != after and INDEX_REL in _carried(fx, later)
          and (whole.get("meta") or {}).get("title") == "touched")


@_own_repos
def _default_project_cases(check, repos):
    """No `--project`, run from a directory outside the repository: the project
    is the one the manifest is in, the same root the remedy it prints - a gate
    command with no project flag - resolves to."""
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    before = _head(fx)
    away = repos.scratch("elsewhere")
    os.makedirs(away)
    here = os.getcwd()
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        os.chdir(away)
        code = M.main([fx["manifest"], TASK], out=lines.append)
    finally:
        os.chdir(here)
        sys.stderr = held
    after = _head(fx)
    check("dp1 RED-FIRST: with no --project and the shell elsewhere, the work is "
          "committed in the manifest's own repository (mutation: default the "
          "project to the cwd -> red): %r" % ((code, lines[-3:]),),
          code == 0 and after != before)


# --- the executor's filed `claims`, carried into the commit message ----------
_CLAIMS = ("claims:\n1 src/a.py:1 is the change the subject names\n"
           "2 n/a - no check touched")


def _file_executor_return(fx, claims=None):
    """Start the fixture task and file its executor return for that start, the
    way `audit-task.py file-return` lays it down: under the evidence directory,
    at `_filed_returns.return_path`. Written here rather than through the verb,
    because the verb is not what this suite is about."""
    import _filed_returns
    shard = _mio.read_json(fx["shard"])
    task = [t for t in shard["tasks"] if t.get("id") == TASK][0]
    task["startedAt"] = "2026-01-01T00:00:00Z"
    TI._write_json(fx["shard"], shard)
    body = {"gates": {}, "outcome": {"technical": "t", "descriptive": "d"},
            "testsAdded": [], "stamp": "audit-stamp: v2 x",
            "redFirst": {"status": "not-attempted", "basis": "gate-only"}}
    if claims is not None:
        body["claims"] = claims
    path = _filed_returns.return_path(
        os.path.join(fx["root"], "docs", "audit", "evidence"), task, "executor")
    _filed_returns.file_once(path, json.dumps(body) + "\n")
    return path


def _message(fx, sha):
    return TI._git(fx["root"], "log", "-1", "--format=%B", sha).rstrip("\n")


def _git_trailer(fx, sha, key):
    """The values git ITSELF reads as `key` trailers of `sha`'s message - not a
    line scan, which would find a nonce git no longer treats as a trailer."""
    return [ln for ln in TI._git(
        fx["root"], "log", "-1",
        "--format=%%(trailers:key=%s,valueonly)" % (key,), sha).splitlines()
        if ln.strip()]


@_own_repos
def _claims_cases(check, repos):
    # The declared file alone: this return dates the task's start, and a stray
    # made after it is a change no running task answers for (ctw-at3).
    fx = repos.make()
    _file_executor_return(fx, claims=_CLAIMS)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # the task's own work\n")
    _gate(fx)
    code, text = _run(fx, TASK, "--subject", "the work")
    sha = _head(fx)
    paragraphs = _message(fx, sha).split("\n\n")
    check("cl1 a filed executor return carrying `claims` gives a commit whose "
          "message holds the block byte-identical as a paragraph of its own, "
          "after the subject and before the trailers: %r" % (paragraphs,),
          code == 0 and len(paragraphs) == 3 and paragraphs[1] == _CLAIMS
          and paragraphs[0].endswith("- the work"))
    rows = _task_rows(fx)
    nonce = ((rows[-1].get("details") or {}).get(_invariants.NONCE_KEY)
             if rows else None)
    check("cl3 ...and with claims and no co-author line, git still reads the "
          "Audit-Row trailer - `%%(trailers:key=Audit-Row,valueonly)` prints the "
          "nonce the row names. Joined onto the claims paragraph it would be a "
          "line git does not treat as a trailer: %r"
          % ((_git_trailer(fx, sha, _invariants.ROW_TRAILER), nonce),),
          nonce is not None
          and _git_trailer(fx, sha, _invariants.ROW_TRAILER) == [nonce])

    plain = repos.make()
    _file_executor_return(plain)
    _write(os.path.join(plain["root"], OWNED), "a = 2  # the task's own work\n")
    _gate(plain)
    pcode, _ptext = _run(plain, TASK, "--subject", "the work")
    psha = _head(plain)
    pparagraphs = _message(plain, psha).split("\n\n")
    check("cl2 SECOND DIRECTION: a filed return WITHOUT `claims` gives today's "
          "message - the subject and the row trailer, nothing between: %r"
          % (pparagraphs,),
          pcode == 0 and len(pparagraphs) == 2
          and pparagraphs[1].startswith(_invariants.ROW_TRAILER + ": "))

    # THE CHECKED READ: the row `drive-phase.py submit` appends after a filing
    # records the return's digest, and the commit reads the return through it.
    import _filed_returns
    edited = repos.make()
    epath = _file_executor_return(edited, claims=_CLAIMS)
    _journal_io.append_from_cli(edited["root"], _filed_returns.filed_return_row(
        epath, edited["root"], TASK, "executor", "not-attempted"))
    filed_rows = [r for r in _journal_io.read_all(edited["root"])
                  if r.get("action") == _filed_returns.RETURN_FILED_ACTION]
    recorded = filed_rows[-1].get("stateHash") if filed_rows else None
    with io.open(epath, "r", encoding="utf-8") as fh:
        body = json.load(fh)
    body["claims"] = _CLAIMS + "\n3 a line added after filing"
    _write(epath, json.dumps(body) + "\n")
    present = _filed_returns.return_digest(epath)
    _write(os.path.join(edited["root"], OWNED), "a = 2  # the task's own work\n")
    _gate(edited)
    before = _head(edited)
    ecode, etext = _run(edited, TASK, "--subject", "the work")
    check("cl4 the task commit's claims come from the checked read - a return "
          "edited after filing refuses the commit, naming both digests: %r"
          % ((ecode, recorded, present, etext[:500]),),
          recorded is not None and present != recorded and ecode == 1
          and recorded in etext and present in etext
          and _head(edited) == before and _staged(edited) == [])

    intact = repos.make()
    ipath = _file_executor_return(intact, claims=_CLAIMS)
    _journal_io.append_from_cli(intact["root"], _filed_returns.filed_return_row(
        ipath, intact["root"], TASK, "executor", "not-attempted"))
    _write(os.path.join(intact["root"], OWNED), "a = 2  # the task's own work\n")
    _gate(intact)
    icode, itext = _run(intact, TASK, "--subject", "the work")
    iparagraphs = _message(intact, _head(intact)).split("\n\n")
    check("cl5 ALLOW, the over-fire direction: the same return left as filed "
          "commits, its claims carried byte-identical: %r"
          % ((icode, itext[:300], iparagraphs),),
          icode == 0 and len(iparagraphs) == 3 and iparagraphs[1] == _CLAIMS)


# --- what the index says: renames, deletions, ignored directories -----------
@_own_repos
def _index_cases(check, repos):
    # A STAGED RENAME. `git mv` leaves the source path in HEAD and nowhere else -
    # not on disk, not in the index - so a skip rule asking only the index calls
    # it "never there" and the commit records a copy.
    fx = repos.make()
    _set_task(fx, files=[OWNED, RENAMED])
    TI._git(fx["root"], "mv", OWNED, RENAMED)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    tree = _tree(fx, after) if after != before else []
    check("ctw30 a declared path staged as the SOURCE of a rename is part of the "
          "commit: the commit records the rename, and the old path is no longer "
          "tracked - skipping it because the index no longer holds it leaves the "
          "new file added beside the old one, which is a copy: %r / %r / %r"
          % (code, tree, text),
          code == 0 and RENAMED in tree and OWNED not in tree
          and ("R100\t%s\t%s" % (OWNED, RENAMED)) in _name_status(fx, after))
    check("ctw31 ...and nothing is left staged, so neither half of the rename "
          "waits in the index for the next commit to sweep up: %r"
          % (_staged(fx),), _staged(fx) == [])
    check("ctw31b ...and the printed list names BOTH halves of the rename - with "
          "git's rename detection on, the staged list carries the new name "
          "alone and the path this change is about goes unreported: %r"
          % (text,),
          ("    %s" % (OWNED,)) in text.splitlines()
          and ("    %s" % (RENAMED,)) in text.splitlines())

    # ...AND A RENAME WHOSE SOURCE THE TASK DOES NOT DECLARE.
    fx = repos.make()
    _set_task(fx, files=[RENAMED])
    TI._git(fx["root"], "mv", OWNED, RENAMED)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw31c SECOND-DIRECTION CASE: a staged rename whose SOURCE is not "
          "declared is refused and the source NAMED - git lists a staged rename "
          "by its new name alone, so an index read with rename detection on "
          "never sees the deletion it carries, and the commit would record a "
          "copy while the deletion waits in the index: %r / %r" % (code, text),
          code == 1 and OWNED in text and _head(fx) == before)

    # A STAGED DELETION: the same HEAD-only shape, with no new path beside it.
    fx = repos.make()
    TI._git(fx["root"], "rm", "-q", "--", OWNED)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    check("ctw32 SECOND-DIRECTION CASE: a declared path whose deletion is already "
          "STAGED is committed as a deletion - `git add` refuses a path in HEAD "
          "alone, so it stays out of the staging call and inside the commit's "
          "pathspec, which is what records it: %r / %r"
          % (code, _name_status(fx, after) if after != before else text),
          code == 0 and after != before
          and ("D\t%s" % (OWNED,)) in _name_status(fx, after)
          and OWNED not in _tree(fx, after))

    # A TRACKED FILE UNDER AN IGNORED DIRECTORY.
    fx = repos.make()
    _ignored_dir(fx)
    _set_task(fx, files=[OWNED, IGN_TRACKED])
    _write(os.path.join(fx["root"], IGN_TRACKED), "v2\n")
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    carried = _carried(fx, after) if after != before else []
    check("ctw33 a TRACKED declared file under a gitignored directory is "
          "committed: the ignore rule is about untracked files, and `git add` "
          "naming the path refuses it while staging it anyway, so it is staged "
          "as the tracked file it is: %r / %r" % (code, text),
          code == 0 and IGN_TRACKED in carried and OWNED in carried
          and _staged(fx) == [])

    # AN UNTRACKED DECLARED FILE UNDER AN IGNORED DIRECTORY, beside real work.
    fx = repos.make()
    _ignored_dir(fx)
    _set_task(fx, files=[OWNED, IGN_UNTRACKED])
    _write(os.path.join(fx["root"], IGN_UNTRACKED), "new\n")
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)
    before = _head(fx)
    found = _index_entries(fx)
    code, text = _run(fx)
    check("ctw34 an UNTRACKED declared file under an ignored directory is "
          "refused BY NAME, with the decision handed back: adding it takes "
          "`-f`, and forcing past an ignore rule is the operator's call and "
          "never this command's: %r / %r" % (code, text),
          code == 1 and IGN_UNTRACKED in text and _const('IGNORED_HINT') in text
          and _head(fx) == before)
    check("ctw35 ...and the refusal leaves the git index exactly as it was "
          "found - the declared work beside the ignored file was not staged "
          "either, and the ignored file was not forced in: %r"
          % (_index_entries(fx) == found,),
          _index_entries(fx) == found
          and TI._git(fx["root"], "ls-files", "--", IGN_UNTRACKED).strip() == "")

    # ...AND THE SAME FILE ALONE, where nothing else is uncommitted.
    fx = repos.make()
    _ignored_dir(fx)
    _set_task(fx, files=[OWNED, IGN_UNTRACKED])
    TI._git(fx["root"], "add", "--", SHARD_REL)
    TI._git(fx["root"], "commit", "-q", "-m", "fixture: the widened scope",
            "--", SHARD_REL)
    _write(os.path.join(fx["root"], IGN_UNTRACKED), "new\n")
    before = _head(fx)
    code, text = _run(fx)
    check("ctw36 an untracked declared file under an ignored directory is NAMED "
          "even when it is the only thing uncommitted - `git status` does not "
          "list an ignored file, so reading it alone reports 'nothing "
          "uncommitted' over work that is sitting right there: %r / %r"
          % (code, text),
          code == 1 and IGN_UNTRACKED in text
          and "already in git" not in text and _head(fx) == before)

    # A FAILURE AFTER STAGING: a pre-commit hook that refuses.
    fx = repos.make()
    _dirty_work(fx)
    # One declared path the operator had ALREADY staged, at bytes older than
    # the working tree's: restoring "as found" means those bytes, not an
    # unstaged path.
    _write(os.path.join(fx["root"], OWNED), "a = 3  # staged by hand\n")
    TI._git(fx["root"], "add", "--", OWNED)
    _write(os.path.join(fx["root"], OWNED), "a = 4  # edited after\n")
    _gate(fx)
    hooks = os.path.join(fx["root"], ".git", "hooks")
    if not os.path.isdir(hooks):
        os.makedirs(hooks)
    _write(os.path.join(hooks, "pre-commit"), "#!/bin/sh\nexit 1\n")
    os.chmod(os.path.join(hooks, "pre-commit"), 0o755)
    TI._git(fx["root"], "config", "core.hooksPath", hooks)
    before = _head(fx)
    found = _index_entries(fx)
    code, text = _run(fx)
    check("ctw37 a commit git refuses AFTER staging puts the index back exactly "
          "as it was found - the entry the operator had staged at its own bytes "
          "included, and nothing this command staged left behind: %r / %r"
          % (code, text),
          code == 1 and _head(fx) == before and _index_entries(fx) == found)
    check("ctw38 ...and the refusal says the index was restored, because 'the "
          "index is still staged' and 'the index is as you left it' send a "
          "reader to opposite repairs: %r" % (text,),
          _const('INDEX_RESTORED') in text)


# --- the verdict the commit was measured under --------------------------------
@_own_repos
def _verdict_cases(check, repos):
    # A RED NEWEST VERDICT.
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=["false"])
    _gate(fx)
    red = _newest_row(fx)
    before = _head(fx)
    found = _index_entries(fx)
    code, text = _run(fx)
    check("ctw39 a task whose newest recorded gate verdict is not `passed` is "
          "NOT committed, and the refusal names the run and its word - the gate "
          "is what decides a task is done, and a commit that ignores it records "
          "red work as finished: %r / %r" % (red.get("status"), text),
          red.get("status") == "failed" and code == 1
          and red.get("runId") in text and _head(fx) == before
          and _index_entries(fx) == found)

    # ...OVERRIDDEN ON THE RECORD.
    reason = "the red step is a known flake outside this task"
    code, text = _run(fx, TASK, "--override-verdict", reason)
    after = _head(fx)
    rows = [r for r in _journal_io.read_all(fx["root"])
            if r.get("action") == _const('ACTION_VERDICT_OVERRIDDEN')]
    details = rows[-1].get("details") if rows else {}
    check("ctw40 an explicit override commits anyway and writes a journal row "
          "naming the commit, the run it went over and the operator's reason - "
          "an override nobody can find afterwards is a gate quietly deleted. "
          "The row is INSIDE the commit it names, keyed by the commit's "
          "trailer, so the override reaches every clone the commit does: "
          "%r / %r" % (details, text),
          code == 0 and after != before and len(rows) == 1
          and _trailer_of(fx, after) == [details.get(_invariants.NONCE_KEY)]
          and set(_row_files(fx, _const("ACTION_VERDICT_OVERRIDDEN")))
          <= set(_carried(fx, after))
          and details.get("runId") == red.get("runId")
          and details.get("reason") == reason)
    fx = repos.make()
    _dirty_work(fx)
    code, _text = _run(fx, TASK, "--override-verdict", "  ")
    check("ctw41 ...and an override with no reason is a USAGE error: the reason "
          "is the whole of what the row is for: %r" % (code,), code == 2)
    fx = repos.make(journal_off=True)
    _dirty_work(fx)
    before = _head(fx)
    code, text = _run(fx, TASK, "--override-verdict", reason)
    check("ctw42 ...and with the journal switched off the override is REFUSED "
          "before anything is staged, because it would be recorded nowhere: "
          "%r / %r" % (code, text),
          code == 1 and _head(fx) == before and _staged(fx) == [])

    # A PASSED VERDICT ON WORK THAT HAS SINCE CHANGED.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 3  # edited after the gate\n")
    before = _head(fx)
    code, text = _run(fx)
    check("ctw43 a `passed` verdict measured on declared files that have "
          "CHANGED since is refused as stale - the declared-work digest the "
          "recorder wrote no longer matches what would be committed, so the "
          "green is about bytes this commit does not carry: %r / %r"
          % (code, text),
          code == 1 and "scopeDigest" in text and _head(fx) == before)

    # NO VERDICT AT ALL, on a task that declares a gate.
    fx = repos.make()
    _dirty_work(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw44 a task with a gate and no recorded verdict is refused, and the "
          "refusal says how to record one: %r / %r" % (code, text),
          code == 1 and "--record" in text and _head(fx) == before)

    # A PHASE-SCOPE ROW IS NOT THE TASK'S VERDICT.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx, task=None)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw45 a PHASE-scope run - the sign-off gate, which carries no task id "
          "- is not credited to the task: it measured the phase and no task "
          "asked for it. Asserted on the NO-VERDICT sentence and not on the "
          "exit code alone, because a phase row credited to the task is also "
          "refused, as stale, whenever the phase declares more files than the "
          "task: %r / %r" % (code, text),
          code == 1 and "no gate verdict is recorded for %s" % (TASK,) in text
          and _head(fx) == before)

    # ...BUT A TASK MEASURED BY ITS PHASE'S GATE IS.
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=[])
    _gate(fx)
    fallback = _newest_row(fx)
    code, text = _run(fx)
    check("ctw46 SECOND-DIRECTION CASE: a task with no gate of its own, run with "
          "`--task` and measured by the phase's gate, IS bound by that verdict - "
          "the row says `gateSource: phase` beside the task id, and refusing it "
          "would refuse every task that inherits its gate: %r / %r"
          % (fallback.get("gateSource"), text),
          fallback.get("gateSource") == "phase" and code == 0
          and "committed" in text)

    # NEWEST WINS, in both directions.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _set_task(fx, gate=["false"])
    _gate(fx)
    code, text = _run(fx)
    check("ctw47 a green run followed by a red one is refused - the NEWEST "
          "verdict is the one the work stands under, not the best one: %r"
          % (code,), code == 1)
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=["false"])
    _gate(fx)
    _set_task(fx, gate=["test"])
    _gate(fx)
    code, text = _run(fx)
    check("ctw48 ...and a red run followed by a green one commits: the retry "
          "that went green is what the orchestrator commits on: %r / %r"
          % (code, text), code == 0)

    # A REPEATED VERDICT.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _gate(fx, reuse=True)
    repeated = _newest_row(fx)
    code, text = _run(fx)
    check("ctw49 a verdict the recorder REPEATED rather than re-measured is "
          "graded against the run that measured it - the repeat carries no "
          "tree state of its own and names its source, so refusing it would "
          "refuse every unchanged re-run: %r / %r"
          % (repeated.get("verdictSource"), text),
          repeated.get("verdictSource") == "reused" and code == 0)

    # A TASK NOTHING CAN MEASURE.
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=[], phase_gate=[])
    code, text = _run(fx)
    check("ctw50 a task whose gate is EMPTY - its own and its phase's - commits, "
          "and the output says the commit is bound to no verdict. No row is "
          "recorded in THIS fixture - the gate was never run - and an empty "
          "gate needs none to commit, while saying nothing would read as a "
          "green: %r / %r"
          % (code, text),
          code == 0 and _const('NO_GATE') in text)


# --- the recorded answer for an empty gate ------------------------------------
@_own_repos
def _empty_gate_cases(check, repos):
    # A TASK GATE CLEARED ON PURPOSE, WHOSE RECORDING WROTE AN EMPTY-GATE ROW.
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=[], basis="cleared")
    _gate(fx)
    recorded = _newest_row(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw70 a task whose gate was CLEARED, whose newest row is the "
          "empty-gate record `--record` wrote for it, commits - that row IS the "
          "recorded answer for a gate that is empty now, and refusing it left "
          "`--override-verdict` as the only way on: %r / %r"
          % (recorded.get("status"), text),
          recorded.get("status") == _const("VERDICT_EMPTY_GATE")
          and code == 0 and _head(fx) != before
          and _const("CLEARED_GATE").split("%s")[0] in text)
    check("ctw70b ...and its sentence is the CLEARED one: the fixture's phase "
          "declares a `testGate`, so 'nor its phase's `testGate` declares an "
          "entry' would be false here: %r" % (text,),
          "nor its phase's" not in text and "testGate" in text)

    # ...AND THE SAME ROW UNDER A GATE THAT HAS ENTRIES NOW.
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=[], basis="cleared")
    _gate(fx)
    _set_task(fx, gate=["test"], basis="declared")
    before = _head(fx)
    code, text = _run(fx)
    check("ctw71 SECOND-DIRECTION CASE: an empty-gate row under a gate that "
          "DECLARES entries now binds nothing - the gate changed after the "
          "measurement, and the refusal says so in the gate-mismatch words: "
          "%r / %r" % (code, text),
          code == 1 and "measured under the gate" in text
          and _head(fx) == before)

    check("ctw72 the committer's word for an empty-gate row is the recorder's "
          "own - two spellings of the status would make every such row read as "
          "an unknown verdict: %r / %r"
          % (_const("VERDICT_EMPTY_GATE"), RTG.EMPTY_GATE),
          _const("VERDICT_EMPTY_GATE") == RTG.EMPTY_GATE)


def _hook(fx, name, body):
    """Install `.git/hooks/<name>` with `body` and point git at it."""
    hooks = os.path.join(fx["root"], ".git", "hooks")
    if not os.path.isdir(hooks):
        os.makedirs(hooks)
    _write(os.path.join(hooks, name), "#!/bin/sh\n%s\n" % (body,))
    os.chmod(os.path.join(hooks, name), 0o755)
    TI._git(fx["root"], "config", "core.hooksPath", hooks)


def _kept_deletion(fx):
    """A declared file taken out of the index with `git rm --cached` and then
    ignored - the one path whose commit is built in a temporary index."""
    _ignored_dir(fx)
    _set_task(fx, files=[OWNED, IGN_TRACKED])
    TI._git(fx["root"], "rm", "-q", "--cached", "--", IGN_TRACKED)
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)


@_own_repos
def _kept_deletion_hook_cases(check, repos):
    # A HOOK THAT REFUSES, ON THE TEMPORARY-INDEX PATH.
    fx = repos.make()
    _kept_deletion(fx)
    _hook(fx, "pre-commit", "exit 1")
    found = _index_entries(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw80 on the kept-deletion path the project's `pre-commit` hook RUNS "
          "and can refuse: nothing is committed, and the real index is exactly "
          "as it was found - the refusal happened against the temporary one: "
          "%r / %r" % (code, text),
          code == 1 and _head(fx) == before and _index_entries(fx) == found)

    # ...AND A HOOK WHOSE SIDE EFFECT SHOWS IT RAN.
    fx = repos.make()
    _kept_deletion(fx)
    marker = os.path.join(fx["root"], "hook-ran.txt")
    _hook(fx, "pre-commit", "echo pre-commit >> \"%s\"" % (marker,))
    _hook(fx, "commit-msg", "echo commit-msg >> \"%s\"" % (marker,))
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    check("ctw81 ...and a hook that lets it through has visibly run - both "
          "`pre-commit` and `commit-msg` left their mark - on a commit that "
          "still carries exactly the deletion and the declared work: %r / %r"
          % (_read(marker), text),
          code == 0 and after != before
          and _read(marker) == "pre-commit\ncommit-msg\n"
          and ("D\t%s" % (IGN_TRACKED,)) in _name_status(fx, after))


@_own_repos
def _retired_red_cases(check, repos):
    # A RED, THEN THE GATE CLEARED, THEN RECORDED: the empty-gate row is the
    # newest row, and it must not retire the red.
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=["false"])
    _gate(fx)
    _set_task(fx, gate=[], basis="cleared")
    _gate(fx)
    newest = _newest_row(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw73 a red, then the gate cleared, then `--record`, then the commit "
          "is REFUSED - the empty-gate row is the newest row, and a red recorded "
          "under entries after the last green is retired only by a green or by "
          "an override with its reason: %r / %r"
          % (newest.get("status"), text),
          newest.get("status") == _const("VERDICT_EMPTY_GATE")
          and code == 1 and "after the last green" in text
          and _head(fx) == before)
    # ...AND A RED THAT A GREEN ALREADY RETIRED.
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=["false"])
    _gate(fx)
    _set_task(fx, gate=["test"])
    _gate(fx)
    _set_task(fx, gate=[], basis="cleared")
    _gate(fx)
    code, text = _run(fx)
    check("ctw74 SECOND-DIRECTION CASE: a red, then a green, then the gate "
          "cleared and recorded commits - the green retired the red before the "
          "gate was emptied: %r / %r" % (code, text),
          code == 0 and _const("CLEARED_GATE").split("%s")[0] in text)


def _set_build(fx, name, command):
    """Rewrite one `meta.buildCommands` entry in the fixture's index."""
    index = _mio.read_json(fx["manifest"])
    index.setdefault("meta", {}).setdefault("buildCommands", {})[name] = command
    TI._write_json(fx["manifest"], index)


@_own_repos
def _gate_identity_cases(check, repos):
    # WHAT AN ENTRY RUNS, CHANGED AFTER A GREEN.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _set_build(fx, "test", "true && true")
    before = _head(fx)
    code, text = _run(fx)
    check("ctw75 a `meta.buildCommands` edit that changes what an entry RUNS, "
          "made after a green, is a changed gate and refused - the entry's name "
          "held still while the gate became a different one: %r / %r"
          % (code, text),
          code == 1 and "measured under the gate" in text
          and _head(fx) == before)

    # A ROW THAT DROPPED STEPS FOR LENGTH, UNDER A GATE WIDENED PAST THEM. The
    # row is written by the recorder and then given the count a row with more
    # steps than it keeps carries; its gate digest is removed, so only the step
    # comparison is under test.
    def _dropped_row(gate_now):
        fx = repos.make()
        _dirty_work(fx)
        _gate(fx)
        newest = _newest_row(fx)

        def _dropped(row):
            row["stepsDropped"] = 1
            row.pop("gateDigest", None)
            return row
        _rewrite_row(fx, newest.get("runId"), _dropped)
        _set_task(fx, gate=gate_now)
        return _run(fx)
    code, text = _dropped_row(["test", "x", "y"])
    check("ctw76 a row that kept ONE step and dropped one is a gate of two, and "
          "it does not bind a gate of three - comparing only the kept steps "
          "ignored the count: %r / %r" % (code, text),
          code == 1 and "measured under the gate" in text)
    code, text = _dropped_row(["test", "x"])
    check("ctw77 SECOND-DIRECTION CASE: the same row binds a gate of two whose "
          "first entry is the step it kept: %r / %r" % (code, text),
          code == 0 and "committed" in text)

    # AN IGNORED DIRECTORY, DECLARED WHOLE, THAT HOLDS A TRACKED FILE.
    fx = repos.make()
    _ignored_dir(fx)
    _set_task(fx, files=[OWNED, IGNORED_DIR])
    _write(os.path.join(fx["root"], IGN_TRACKED), "v2\n")
    _write(os.path.join(fx["root"], IGN_UNTRACKED), "stays untracked\n")
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    check("ctw78 a declared DIRECTORY git ignores as a whole, holding a tracked "
          "edited file, is committed with that file - `check-ignore` does not "
          "report such a directory, and `git add -- <dir>` refuses it asking "
          "for -f - while the untracked file beside it stays out, never "
          "forced: %r / %r" % (code, text),
          code == 0 and after != before
          and IGN_TRACKED in _carried(fx, after)
          and IGN_UNTRACKED not in _carried(fx, after)
          and TI._git(fx["root"], "ls-files", "--", IGN_UNTRACKED).strip() == "")

    # A DECLARED DIRECTORY GIT LISTS NOTHING UNDER.
    fx = repos.make()
    _write(os.path.join(fx["root"], ".gitignore"), "*.log\n")
    TI._git(fx["root"], "add", "--", ".gitignore")
    TI._git(fx["root"], "commit", "-q", "-m", "fixture: ignore logs", "--",
            ".gitignore")
    os.makedirs(os.path.join(fx["root"], "hollow"))
    _write(os.path.join(fx["root"], "hollow", "only.log"), "ignored\n")
    # Beside a declared file that carries a change: a commit of records alone
    # is refused on its own rule (`ctw-ro3`), and this case asks only whether
    # the hollow directory is a defined entry of the digest the gate binds.
    _set_task(fx, files=["hollow", OWNED])
    _write(os.path.join(fx["root"], OWNED), "a = 2  # the task's own work\n")
    _gate(fx)
    code, text = _run(fx)
    check("ctw79 a declared directory git lists no file under is a DEFINED "
          "entry of the digest, not an unanswerable one - otherwise every "
          "re-record of such a task is refused and the override is the only "
          "way on: %r / %r" % (code, text),
          code == 0 and "not established" not in text)


@_own_repos
def _affected_gate_cases(check, repos):
    # A TASK GATE NARROWER THAN ITS PHASE'S, UNDER A DERIVED PHASE GATE. The
    # recorder adds the suites the task's change can break as steps of their
    # own (here the Python import-graph arm: `tests/test_a.py` imports the
    # task's `src/a.py`, and the spelling gives them a command), so the row
    # carries more steps than the task declares. Those are measured, not
    # declared, and must not read as a different gate.
    fx = repos.make()
    index = _mio.read_json(fx["manifest"])
    index["meta"]["buildCommands"]["wide"] = "true"
    # The spelling must not be the task's own `test` command (`true`) with a
    # path added: that entry would be the same runner unscoped, which already
    # runs every suite the step would, so no derived step would join the row.
    index["meta"]["phaseGate"] = {"derived": {"spelling": "true -- {paths}"}}
    TI._write_json(fx["manifest"], index)
    os.makedirs(os.path.join(fx["root"], "tests"))
    _write(os.path.join(fx["root"], "tests", "test_a.py"), "import a\n")
    _set_task(fx, gate=["test"], phase_gate=["test", "wide"])
    TI._git(fx["root"], "add", "--", INDEX_REL, SHARD_REL, "tests/test_a.py")
    TI._git(fx["root"], "commit", "-q", "-m",
            "fixture: a derived phase gate wider than the task's", "--",
            INDEX_REL, SHARD_REL, "tests/test_a.py")
    _dirty_work(fx)
    gate_code, gate_text = _gate(fx)
    row = _newest_row(fx)
    names = [str(s.get("name")) for s in (row.get("steps") or [])]
    derived = [n for n in names if n != "test"]
    before = _head(fx)
    code, text = _run(fx)
    check("ctw86 on a fixture plan with a derived phase gate, a green recorded "
          "run of a narrower task gate commits without --override-verdict: "
          "gate %r, row %r steps %r, commit %r / %r"
          % (gate_code, row.get("status"), names, code, text),
          gate_code == 0 and row.get("status") == "passed"
          and names[:1] == ["test"] and len(derived) >= 1
          and any("tests/test_a.py" in n for n in derived)
          and code == 0 and "committed" in text and _head(fx) != before
          and OWNED in _carried(fx, _head(fx)))


# --- helpers for editing a recorded ledger -------------------------------------
def _ledger_file_with(fx, needle):
    """The ledger file holding `needle`, and its lines."""
    directory = os.path.join(fx["root"], "docs", "audit", "evidence")
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        text = _read(path) or ""
        if needle in text:
            return path, text.splitlines()
    raise RuntimeError("no ledger file holds %r" % (needle,))


def _rewrite_row(fx, run_id, edit):
    """Rewrite the ledger row `run_id` through `edit(row)`, or drop it when
    `edit` returns None. The chain is not re-hashed: the reader under test does
    not verify it, and the cases are about what the committer reads."""
    path, lines = _ledger_file_with(fx, run_id)
    out = []
    for line in lines:
        # The row's OWN id, parsed: a repeat names its source in `reusedFrom`,
        # so a substring match would edit the repeat too.
        if run_id in line and json.loads(line).get("runId") == run_id:
            row = edit(json.loads(line))
            if row is None:
                continue
            line = json.dumps(row, sort_keys=True)
        out.append(line)
    _write(path, "\n".join(out) + "\n")


def _append_ledger(fx, text):
    """Append raw `text` to the newest ledger file."""
    directory = os.path.join(fx["root"], "docs", "audit", "evidence")
    path = os.path.join(directory, sorted(os.listdir(directory))[-1])
    with io.open(path, "a", encoding="utf-8") as fh:
        fh.write(text)
    return path


# --- the declared scope, normalised once ---------------------------------------
@_own_repos
def _scope_cases(check, repos):
    # A `:line-range` ENTRY EDITED AFTER A GREEN GATE.
    fx = repos.make()
    _set_task(fx, files=["%s:1-2" % (OWNED,)])
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 3  # after the gate\n")
    before = _head(fx)
    code, text = _run(fx)
    check("ctw51 a declared entry carrying a `:line-range` suffix is hashed as "
          "the FILE it names, so an edit after a green gate is refused as stale "
          "- with the suffix left on, both sides hashed a path that does not "
          "exist, called it missing, and agreed whatever happened to the file. "
          "Asserted on the CONTENTS sentence, because an unreadable digest is "
          "also a refusal and would pass a bare exit-code check: %r / %r"
          % (code, text),
          code == 1 and "CONTENTS" in text and _head(fx) == before)

    # A DIRECTORY ENTRY EDITED AFTER A GREEN GATE.
    fx = repos.make()
    _set_task(fx, files=["src"])
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 3  # after the gate\n")
    before = _head(fx)
    code, text = _run(fx)
    check("ctw52 a declared DIRECTORY is hashed as the files git lists under it, "
          "so an edit to one of them after a green gate is refused as stale - a "
          "directory has no bytes of its own, and hashing the entry read it as "
          "missing on both sides - and, unexpanded, reads as a path on disk "
          "that cannot be read, which is a refusal of a different kind: %r / %r"
          % (code, text),
          code == 1 and "CONTENTS" in text and _head(fx) == before)

    # A TASK THAT DECLARES ITS OWN SHARD.
    fx = repos.make()
    _set_task(fx, files=[OWNED, SHARD_REL])
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw53 a task that declares its OWN manifest file is not refused by its "
          "own recording - the pointer `--record` writes lands in that file after "
          "the digest is taken, so the digest leaves the recorder's paths out on "
          "both sides, as the content identity already did: %r / %r"
          % (code, text),
          code == 0 and _head(fx) != before
          and SHARD_REL in _carried(fx, _head(fx)))

    # ...AND IN THE SINGLE-FILE LAYOUT, where the file is the whole manifest.
    fx = repos.make()
    single = _mio.load_manifest(fx["manifest"])
    single_path = os.path.join(fx["root"], "docs", "audit", "single.json")
    single_rel = "docs/audit/single.json"
    for phase in single.get("phases") or []:
        phase.pop("shard", None)
    for phase, task in _mio.iter_tasks(single):
        if task.get("id") == TASK:
            task["files"] = [OWNED, single_rel]
    TI._write_json(single_path, single)
    TI._git(fx["root"], "add", "--", single_rel)
    TI._git(fx["root"], "commit", "-q", "-m", "chore: single-file layout", "--",
            single_rel)
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx, manifest=single_path)
    before = _head(fx)
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main([single_path, TASK, "--project", fx["root"]],
                      out=lines.append)
    finally:
        sys.stderr = held
    check("ctw53b ...and in the SINGLE-FILE layout, where the task declares the "
          "whole manifest the pointer is written into: %r / %r"
          % (code, lines),
          code == 0 and _head(fx) != before)

    # THE DECLARED LIST CHANGED, NOT THE FILES.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _write(os.path.join(fx["root"], "src", "added.py"), "added = 1\n")
    _set_task(fx, files=[OWNED, "src/added.py"])
    before = _head(fx)
    code, text = _run(fx)
    check("ctw54 a scope WIDENED after a green gate is refused and said to be a "
          "change to the declared LIST - 'the declared files have changed' is "
          "untrue when only the list did, and the repair is a gate run on the "
          "new scope: %r / %r" % (code, text),
          code == 1 and "declared file LIST" in text and _head(fx) == before)
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 3  # edited after the gate\n")
    code, text = _run(fx)
    check("ctw55 SECOND-DIRECTION CASE: an edit to a declared file under an "
          "unchanged list is said to be a change to the CONTENTS: %r" % (text,),
          code == 1 and "CONTENTS" in text and "LIST" not in text)

    # A RED VERDICT, AND THEN THE GATE EMPTIED.
    fx = repos.make()
    _dirty_work(fx)
    _set_task(fx, gate=["false"])
    _gate(fx)
    _set_task(fx, gate=[], phase_gate=[])
    before = _head(fx)
    code, text = _run(fx)
    check("ctw56 a task whose newest verdict is red and whose gate has since been "
          "EMPTIED is refused - the ledger is read before the gate is, and "
          "emptying a gate does not retire the red it last answered: %r / %r"
          % (code, text),
          code == 1 and "declares no gate now" in text and _head(fx) == before)

    # A GREEN VERDICT UNDER AN OLDER GATE.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _set_task(fx, gate=["test", "true"])
    before = _head(fx)
    code, text = _run(fx)
    check("ctw57 a `passed` verdict measured under a gate the task no longer "
          "declares is refused - widening the gate after a green would "
          "otherwise commit on a verdict about the narrower one: %r / %r"
          % (code, text),
          code == 1 and "measured under the gate" in text
          and _head(fx) == before)


# --- the branches each refusal and each allowance takes ------------------------
@_own_repos
def _branch_cases(check, repos):
    # A CONFLICT RESOLVED IN THE TREE BUT NOT ADDED.
    fx = repos.make()
    _write(os.path.join(fx["root"], OWNED), "a = stashed\n")
    TI._git(fx["root"], "stash", "-q")
    _write(os.path.join(fx["root"], OWNED), "a = other\n")
    TI._git(fx["root"], "commit", "-q", "-m", "fixture: other", "--", OWNED)
    subprocess.run(list(_harness.GIT) + ["-C", fx["root"], "stash", "pop", "-q"],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    conflicted = TI._git(fx["root"], "ls-files", "-s", "--", OWNED).count(OWNED)
    _write(os.path.join(fx["root"], OWNED), "a = resolved\n")
    _gate(fx)
    code, text = _run(fx)
    check("ctw58 a conflict resolved in the working tree and not yet added is "
          "committed - staging resolves it, as plain `git add` always did, and "
          "an index snapshot that refused an unmerged index would refuse every "
          "such commit: %r / %r" % (conflicted, text),
          conflicted == 3 and code == 0
          and _read(os.path.join(fx["root"], OWNED)) == "a = resolved\n"
          and OWNED in _carried(fx, _head(fx)))

    # AN INTENT-TO-ADD DECLARED FILE, AND A COMMIT A HOOK REFUSES.
    fx = repos.make()
    _set_task(fx, files=[OWNED, "src/ita.py"])
    _write(os.path.join(fx["root"], "src", "ita.py"), "ita = 1\n")
    TI._git(fx["root"], "add", "-N", "--", "src/ita.py")
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)
    hooks = os.path.join(fx["root"], ".git", "hooks")
    if not os.path.isdir(hooks):
        os.makedirs(hooks)
    _write(os.path.join(hooks, "pre-commit"), "#!/bin/sh\nexit 1\n")
    os.chmod(os.path.join(hooks, "pre-commit"), 0o755)
    TI._git(fx["root"], "config", "core.hooksPath", hooks)
    found = TI._git(fx["root"], "status", "--porcelain=v2", "--", "src/ita.py")
    code, text = _run(fx)
    check("ctw59 an INTENT-TO-ADD declared file is put back intent-to-add when "
          "the commit is refused - `git write-tree` dropped the flag, so the "
          "file came back as a staged empty one: %r / %r"
          % (found, TI._git(fx["root"], "status", "--porcelain=v2", "--",
                            "src/ita.py")),
          code == 1 and found.startswith("1 .A ")
          and TI._git(fx["root"], "status", "--porcelain=v2", "--",
                      "src/ita.py") == found)

    # THE OVERRIDE ROW FAILING, WHICH IS NOW BEFORE THE COMMIT.
    fx = repos.make()
    _dirty_work(fx)
    held_row = M.override_row
    M.override_row = lambda *args, **kwargs: False
    before = _head(fx)
    found = _index_entries(fx)
    try:
        code, text = _run(fx, TASK, "--override-verdict", "nothing was measured")
    finally:
        M.override_row = held_row
    anchors = [(r.get("details") or {}).get(_invariants.NONCE_KEY)
               for r in _task_rows(fx)]
    withdrawn = _invariants.withdrawn_nonces(_journal_io.read_all(fx["root"]))
    check("ctw60 an override whose row could NOT be written is REFUSED before "
          "anything is staged - the row is written ahead of the commit now, so "
          "no commit goes over its gate with nothing saying so - and the anchor "
          "row already written for it is withdrawn by its nonce: %r / %r / %r"
          % (code, text, anchors),
          code == 1 and _head(fx) == before and _index_entries(fx) == found
          and "could NOT be written" in text
          and len(anchors) == 1 and anchors[0] in withdrawn)

    # AN UNREADABLE LEDGER LINE THAT COULD BE THIS TASK'S.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    ledger = _append_ledger(fx, '{"taskId":"%s","status":\n{"v":1}\n' % (TASK,))
    before = _head(fx)
    code, text = _run(fx)
    check("ctw61 an unparseable ledger line carrying this task's id refuses, "
          "NAMING the file and line and the command that shows it: %r / %r"
          % (code, text),
          code == 1 and os.path.basename(ledger) in text
          and _const("VERIFY_COMMAND") in text and _head(fx) == before)
    # ...AND ONE THAT PROVABLY IS ANOTHER TASK'S.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _append_ledger(fx, '{"taskId":"P9.9","status":\n{"v":1}\n')
    code, text = _run(fx)
    check("ctw62 SECOND-DIRECTION CASE: an unparseable line whose `taskId` names "
          "ANOTHER task is passed over and said - one torn row elsewhere must not "
          "refuse every task commit in the project: %r / %r" % (code, text),
          code == 0 and "passed over" in text)
    # ...AND A TORN TAIL THAT PROVES NOTHING.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    _append_ledger(fx, '{"v":1,"ts":"2026')
    code, text = _run(fx)
    check("ctw63 ...and a torn last line that stops before any `taskId` refuses, "
          "because it could be this task's newest verdict: %r" % (code,),
          code == 1 and _const("VERIFY_COMMAND") in text)

    # A REPEATED VERDICT WHOSE SOURCE IS GONE.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    measured = _newest_row(fx)
    _gate(fx, reuse=True)
    _rewrite_row(fx, measured.get("runId"), lambda row: None)
    code, text = _run(fx)
    check("ctw64 a repeated verdict whose measured run is no longer in the "
          "ledger is refused - there is no tree state left to grade it against: "
          "%r / %r" % (code, text),
          code == 1 and "not in the ledger" in text)

    # A ROW WHOSE DIGEST COULD NOT BE TAKEN.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    newest = _newest_row(fx)

    def _no_digest(row):
        row.setdefault("testedState", {})["scopeDigest"] = None
        return row
    _rewrite_row(fx, newest.get("runId"), _no_digest)
    code, text = _run(fx)
    check("ctw65 a row whose declared-work digest is null is `unanswerable` and "
          "refused, never read as agreement: %r / %r" % (code, text),
          code == 1 and "not established" in text)

    # A TASK THAT DECLARES ONLY WHAT THE RECORDER WRITES.
    fx = repos.make()
    _set_task(fx, files=[SHARD_REL])
    _gate(fx)
    code, text = _run(fx)
    check("ctw66 a task declaring nothing but its own manifest file is bound on "
          "the verdict word alone and says so - its declared-work digest has "
          "nothing left in it: %r / %r" % (code, text),
          code == 0 and "declares no files the recorder does not write" in text)

    # AN OVERRIDE NOBODY NEEDED.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    code, text = _run(fx, TASK, "--override-verdict", "just in case")
    rows = [r for r in _journal_io.read_all(fx["root"])
            if r.get("action") == _const("ACTION_VERDICT_OVERRIDDEN")]
    check("ctw67 an override given over a verdict that binds is NOT recorded, "
          "and the output says it was not needed: %r / %r" % (code, text),
          code == 0 and "not needed" in text and rows == [])

    # AN IGNORED RECORD PATH.
    fx = repos.make()
    _write(os.path.join(fx["root"], ".gitignore"), "docs/audit/evidence/\n")
    TI._git(fx["root"], "add", "--", ".gitignore")
    TI._git(fx["root"], "commit", "-q", "-m", "fixture: ignore the evidence",
            "--", ".gitignore")
    _dirty_work(fx)
    _gate(fx, set_apart=False)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw68 a RECORD path git ignores is refused in its own words - it is a "
          "record this commit must carry, so 'drop it from the task's files' "
          "would be the wrong repair: %r / %r" % (code, text),
          code == 1 and "a record this commit is required to carry" in text
          and "drop it from the task's" not in text and _head(fx) == before)

    # A FILE TAKEN OUT OF THE INDEX AND THEN IGNORED.
    fx = repos.make()
    _ignored_dir(fx)
    _set_task(fx, files=[OWNED, IGN_TRACKED])
    TI._git(fx["root"], "rm", "-q", "--cached", "--", IGN_TRACKED)
    _write(os.path.join(fx["root"], OWNED), "a = 2\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    check("ctw69 a declared file removed with `git rm --cached` and then ignored "
          "is committed as the DELETION the operator made - HEAD still holds it, "
          "and '-f is yours to decide' is advice for a file nobody tracked: "
          "%r / %r" % (code, text),
          code == 0 and after != before
          and ("D\t%s" % (IGN_TRACKED,)) in _name_status(fx, after)
          and os.path.exists(os.path.join(fx["root"], IGN_TRACKED))
          and _staged(fx) == [])


def _cli(fx, *extra):
    """`(exit, stdout)` of this command run as the main loop runs it: a process,
    with the session's own variables dropped."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    done = subprocess.run(
        [sys.executable, _loader.script_path("commit-task-work.py"),
         fx["manifest"], TASK, "--project", fx["root"]] + list(extra),
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, encoding="utf-8")
    return done.returncode, done.stdout


@_own_repos
def _success_line_cases(check, repos):
    """A commit, said in one line naming the SHA it wrote; a refusal and
    `--verbose`, in full."""
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    code, short = _cli(fx, "--subject", "the work")
    lines = short.splitlines()
    head = _head(fx)
    check("sl1 a commit prints ONE line within the byte bound, naming the "
          "commit it wrote and the verdict it rests on: %r" % (short,),
          code == 0 and len(lines) == 1
          and len(lines[0].encode("utf-8")) <= 200
          and lines[0].startswith("[commit-task-work] committed %s"
                                  % (head[:12],))
          and "verdict: bound to run" in lines[0])
    vfx = repos.make()
    _dirty_work(vfx)
    _gate(vfx)
    vcode, verbose = _cli(vfx, "--subject", "the work", "--verbose")
    check("sl2 ...and `--verbose` prints what the command always printed: the "
          "headline, every path the commit carries, the journal row, the "
          "verdict: %r" % (verbose[:200],),
          vcode == 0 and len(verbose.splitlines()) > 3
          and verbose.startswith("[commit-task-work] committed %s"
                                 % (_head(vfx)[:12],))
          and "    %s" % (OWNED,) in verbose.splitlines())
    rfx = repos.make()
    _dirty_work(rfx)
    refused = _cli(rfx, "--subject", "the work")
    check("sl3 a refused commit - no gate verdict binds the work - prints in "
          "full, the same with `--verbose`: the deny twin of sl1: %r"
          % (refused[1][:200],),
          refused[0] != 0 and len(refused[1].splitlines()) > 1
          and refused == _cli(rfx, "--subject", "the work", "--verbose"))


def _restartable(fx):
    """The fixture's P1.1 put back to `pending` with no attempt spent, committed,
    so the real `start` verb can take it - the record of an attempt is what
    `start` writes, and a hand-made one would grade the committer against a
    shape the verb never produces."""
    shard = _mio.read_json(fx["shard"])
    task = [t for t in shard["tasks"] if t.get("id") == TASK][0]
    task.update({"status": "pending", "attempts": 0, "commit": None,
                 "completedAt": None, "startedAt": None})
    TI._write_json(fx["shard"], shard)
    TI._git(fx["root"], "add", "--", SHARD_REL)
    TI._git(fx["root"], "commit", "-q", "-m", "fixture: P1.1 restartable",
            "--", SHARD_REL)


def _start(fx):
    """`(code, text)` of `/audit:task start` on the fixture task, in-process."""
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = AT.main(["start", TASK, "--project-dir", fx["root"]],
                       out=lines.append)
    finally:
        sys.stderr = held
    return code, "\n".join(str(x) for x in lines)


@_own_repos
def _attempt_cases(check, repos):
    """A task commit carries exactly its attempt: a declared file's change that
    was there before `start` is refused rather than swept in, a change made
    after it is committed, and a file the attempt created outside every
    in_progress task's scope refuses the commit by name until the scope is
    widened or the file removed."""
    fx = repos.make()
    _restartable(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 9  # another task's dirt\n")
    scode, said = _start(fx)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw-at1 a declared file whose uncommitted change predates the task's "
          "start - the snapshot `start` recorded holds it at these bytes - is "
          "refused by name and nothing is committed or left staged: %r"
          % ((scode, said[-200:], code, text[:400]),),
          scode == 0 and code == 1 and OWNED in text
          and _const("PREDATES") in text and _head(fx) == before
          and _staged(fx) == [])
    verdict = TAT._remedy_verdict(fx["root"], text)
    check("ctw-at11 the predates refusal's ways past are commands no Bash "
          "guard of this plugin refuses in the same project - finish the task "
          "that made it, or commit the change on its own - and it names no "
          "stash: %r" % ((code, verdict, text[:700]),),
          code == 1 and TAT._remedies_pass(verdict)
          and any(" commit " in c and OWNED in c
                  for c in verdict["commands"])
          and "stash" not in text)
    # Its commit runs from anywhere in the project - `git -C` the root, since
    # the paths are the root's - with no placeholder in it.
    commits = [c for c in verdict["commands"] if "commit" in c and "git" in c]
    check("ctw-at12 the predates refusal's commit names the git root with "
          "`git -C` and carries no placeholder: %r" % (commits,),
          len(commits) == 1 and "git -C " in commits[0]
          and "<" not in commits[0])

    # THE MIXED REFUSAL - dirty at the start and changed during the attempt -
    # used to print no way past at all.
    fx = repos.make()
    _restartable(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 9  # another task's dirt\n")
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED),
           "a = 9  # another task's dirt\nb = 1  # and this attempt's\n")
    _gate(fx)
    code, text = _run(fx)
    verdict = TAT._remedy_verdict(fx["root"], text)
    check("ctw-at13 the mixed refusal names a way past no Bash guard refuses - "
          "a `git -C` commit of the file on its own, naming what it holds: %r"
          % ((scode, code, verdict, text[:700]),),
          scode == 0 and code == 1 and _const("MIXED") in text
          and TAT._remedies_pass(verdict)
          and any("git -C " in c and "commit" in c and OWNED in c
                  and "<" not in c for c in verdict["commands"]))

    # Whose work it is, when the plan says: a started, unfinished task
    # declaring the path is named - unblocked first when blocked - and in the
    # commit's message; a finished one, or one never attempted, is not.
    root = os.path.join(os.sep, "repo")
    plan = {"phases": [{"id": "P1", "tasks": [
        {"id": TASK, "files": [OWNED], "status": "in_progress", "attempts": 1},
        {"id": "P1.2", "files": [OWNED], "status": "blocked", "attempts": 1},
        {"id": "P1.3", "files": [OWNED], "status": "done", "attempts": 1},
        {"id": "P1.4", "files": [OWNED], "status": "pending", "attempts": 0},
        {"id": "P1.5", "files": [SIBLING], "status": "blocked",
         "attempts": 1}]}]}
    said = M.ways_past(plan, plan["phases"][0]["tasks"][0], root, root,
                       [OWNED], "uncommitted work from before the attempt")
    named = TAT._remedy_commands(said)
    check("ctw-at14 the ways past name the started, unfinished declarer of the "
          "path - its unblock and its id leading the commit message - and no "
          "finished, unattempted or unrelated task: %r" % ((said, named),),
          said.startswith("Finish P1.2 - unblocking it first")
          and any(c.startswith("/audit:task unblock P1.2 ") for c in named)
          and any(" commit -m 'P1.2: " in c for c in named)
          and not any(t in said for t in ("P1.3", "P1.4", "P1.5")))

    # A TASK COMMIT FOR A TASK THAT IS NOT RUNNING. Never started, and blocked
    # after a start: each is refused before anything is staged, naming the
    # status - a change in its file has no running attempt to belong to.
    seen = []
    fx = repos.make()
    _restartable(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 7  # nobody's attempt\n")
    before = _head(fx)
    code, text = _run(fx)
    seen.append(("pending", code, "pending, not in_progress" in text,
                 _head(fx) == before and _staged(fx) == []))
    fx = repos.make()
    _restartable(fx)
    scode, _said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 7  # written while blocked\n")
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        bcode = AT.main(["block", TASK, "--reason", "spent", "--project-dir",
                         fx["root"]], out=lambda *_a: None)
    finally:
        sys.stderr = held
    before = _head(fx)
    code, text = _run(fx)
    seen.append(("blocked", scode, bcode, code,
                 "blocked, not in_progress" in text,
                 _head(fx) == before and _staged(fx) == []))
    check("ctw-at15 a task commit for a task never started, and for one "
          "blocked after its start, is refused naming the status, with nothing "
          "committed or staged: %r" % (seen,),
          seen[0][1:] == (1, True, True)
          and seen[1][1:] == (0, 0, 1, True, True))

    # SECOND-DIRECTION CASE, for a guard widened to refuse every status but
    # in_progress: a `done` task - the older close order, status before the
    # commit, which the shared fixture builder still follows - commits.
    fx = repos.make()
    _write(os.path.join(fx["root"], OWNED), "a = 2  # the task's own work\n")
    _gate(fx)
    node = _mio.read_json(fx["shard"])["tasks"][0]
    code, text = _run(fx)
    check("ctw-at17 ALLOW: a task recorded `done` before its commit, with no "
          "commit recorded yet, still commits its work: %r"
          % ((node.get("status"), node.get("commit"), code, text[:200]),),
          node.get("status") == "done" and node.get("commit") is None
          and code == 0 and "committed" in text)

    # A TASK ALREADY CLOSED AGAINST ITS COMMIT has no attempt left to commit:
    # its start record went with the close, so a held edit of another task in
    # its file would be dated by mtime against the old start and swept in.
    fx = repos.make()
    closed = _head(fx)
    shard = _mio.read_json(fx["shard"])
    for t in shard["tasks"]:
        if t.get("id") == TASK:
            t.update({"commit": closed, "startedAt": "2026-01-01T00:00:00Z"})
        elif t.get("id") == "P1.2":
            t.update({"status": "blocked", "attempts": 1,
                      "files": [SIBLING, OWNED]})
    TI._write_json(fx["shard"], shard)
    index = _mio.read_json(fx["manifest"])
    index["fileIndex"][OWNED] = [TASK, "P1.2"]
    TI._write_json(fx["manifest"], index)
    TI._git(fx["root"], "add", "--", SHARD_REL, INDEX_REL)
    TI._git(fx["root"], "commit", "-q", "-m", "fixture: P1.1 closed", "--",
            SHARD_REL, INDEX_REL)
    _write(os.path.join(fx["root"], OWNED), "a = 5  # P1.2's unfinished edit\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw-at18 a work commit for a task already `done` against a recorded "
          "commit is refused naming that commit, over another task's held "
          "edit in its file, with nothing committed or staged: %r"
          % ((code, text[:500]),),
          code == 1 and closed[:7] in text and "done" in text
          and _head(fx) == before and _staged(fx) == [])

    # A DECLARED PATH NO START CAN DATE, shared with another started,
    # unfinished task: whose change it is cannot be told, so it is refused
    # and the other task named. The same with no other declarer is not.
    def undated(share):
        fx = repos.make()
        shard = _mio.read_json(fx["shard"])
        for t in shard["tasks"]:
            if t.get("id") == TASK:
                t.update({"status": "in_progress", "attempts": 1,
                          "commit": None, "completedAt": None,
                          "startedAt": None})
            elif t.get("id") == "P1.2":
                t.update({"status": "blocked", "attempts": 1,
                          "files": [SIBLING] + ([OWNED] if share else [])})
        TI._write_json(fx["shard"], shard)
        index = _mio.read_json(fx["manifest"])
        if share:
            index["fileIndex"][OWNED] = [TASK, "P1.2"]
        TI._write_json(fx["manifest"], index)
        TI._git(fx["root"], "add", "--", SHARD_REL, INDEX_REL)
        TI._git(fx["root"], "commit", "-q", "-m", "fixture: undated", "--",
                SHARD_REL, INDEX_REL)
        _write(os.path.join(fx["root"], OWNED), "a = 8  # whose?\n")
        _gate(fx)
        return _run(fx)
    code, text = undated(True)
    code2, text2 = undated(False)
    check("ctw-at16 a declared path no start can date, that another started, "
          "unfinished task also declares, is refused naming that task; with "
          "no other declarer the same path is not refused for it: %r"
          % ((code, text[:600], code2, text2[:300]),),
          code == 1 and _const("UNDATED_SHARED") in text and "P1.2" in text
          and _const("UNDATED_SHARED") not in text2)

    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    _gate(fx)
    code, text = _run(fx)
    check("ctw-at2 ALLOW: the same declared file changed AFTER the start is this "
          "attempt's work and is committed: %r" % ((scode, code, text[:300]),),
          scode == 0 and code == 0 and OWNED in _carried(fx, _head(fx)))

    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    _write(os.path.join(fx["root"], "src", "img.png"), "copied in\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    held = _head(fx)
    os.remove(os.path.join(fx["root"], "src", "img.png"))
    code2, text2 = _run(fx)
    check("ctw-at3 a file the attempt created outside every in_progress task's "
          "scope refuses the commit by name and offers widening the scope or "
          "removing it; removed, the commit goes through without it: %r"
          % ((scode, code, text[:400], code2, text2[:200]),),
          scode == 0 and code == 1 and "src/img.png" in text
          and "/audit:task scope" in text and held == before
          and _head(fx) != before and code2 == 0 and "src/img.png" not in _carried(fx, _head(fx)))

    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    _write(os.path.join(fx["root"], "src", "img.png"), "copied in\n")
    _set_task(fx, files=[OWNED, "src/img.png"])
    _gate(fx)
    code, text = _run(fx)
    check("ctw-at4 ...and widened to declare it, the same file is committed as "
          "the task's work: %r" % ((scode, code, text[:300]),),
          scode == 0 and code == 0
          and "src/img.png" in _carried(fx, _head(fx)))

    # The bash-write guard's record of what it refused as out of scope is read
    # as corroboration: a stray the snapshot found AND the guard recorded is
    # named as both; a record naming something else, or none, changes nothing.
    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    _write(os.path.join(fx["root"], "src", "img.png"), "copied in\n")
    state = M.attempt_state_dir(fx["root"], {})
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "bash-writes-sess.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"outOfScope": ["src/img.png", "src/elsewhere.png"]}, fh)
    with open(os.path.join(state, "bash-writes-plugin-sess.json"), "w",
              encoding="utf-8") as fh:
        json.dump(["not-a-session-slot"], fh)
    _gate(fx)
    code, text = _run(fx)
    check("ctw-at5 a stray the guard recorded as written outside scope is "
          "refused with the snapshot's reason AND the guard's record named; a "
          "recorded path that is not a stray this attempt left is not "
          "named: %r" % ((scode, code, text[:600]),),
          scode == 0 and code == 1 and "src/img.png" in text
          and "bash-write guard recorded" in text
          and "src/elsewhere.png" not in text)

    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    _write(os.path.join(fx["root"], "src", "img.png"), "copied in\n")
    _gate(fx)
    code, text = _run(fx)
    check("ctw-at6 with no guard record the refusal stands on the snapshot "
          "alone and says nothing of a guard: %r" % ((scode, code, text[:400]),),
          scode == 0 and code == 1 and "src/img.png" in text
          and "bash-write guard" not in text)

    # THE PLUGIN'S OWN STATE. A layout change parks a restore point under
    # `.claude/audit-backups/` and adds the ignore line for it to
    # `.claude/.gitignore`; neither is anything a session's tool call wrote,
    # and neither is the task's edit. One fixture holds every plugin-owned
    # shape beside an ordinary undeclared source file, so the refusal can be
    # seen to name the ordinary file ALONE (the over-fire mutation: a table
    # that waves through everything under `.claude/` or a refusal that lists
    # the plugin's paths too), and the close that follows must carry the
    # task's file, leave the plugin's paths out of the commit and name each.
    fx = repos.make()
    _untrack_config(fx)
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    claude = os.path.join(fx["root"], ".claude")
    backups, _ignored = _mio.ensure_backup_dir(fx["manifest"])
    restore = os.path.join(backups, "audit-plan.json.bak-20261022T100219Z")
    _write(restore, "{}\n")
    config_path = os.path.join(claude, "audit.config.json")
    held_config = _mio.read_json(config_path)
    held_config["executor"] = {"waveWidth": 3}
    _write(config_path, json.dumps(held_config, indent=2) + "\n")
    _write(os.path.join(fx["root"], "src", "img.png"), "copied in\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    held = _head(fx)
    os.remove(os.path.join(fx["root"], "src", "img.png"))
    code2, text2 = _run(fx)
    carried = _carried(fx, _head(fx))
    check("ctw-at7 a restore point under audit-backups/, the .gitignore line "
          "that hides it and a config file created mid-attempt do not refuse "
          "the close: an undeclared ordinary file still refuses, by name and "
          "alone; removed, the task's own file is committed, none of the "
          "plugin's paths is, and each is named as plugin-owned and left out: "
          "%r" % ((scode, code, text[:500], code2, text2[:700], carried),),
          scode == 0 and code == 1 and "src/img.png" in text
          and ".claude" not in [ln for ln in text.splitlines()
                                if ln.startswith("[commit-task-work] REFUSED")][0]
          and held == before and code2 == 0 and OWNED in carried
          and not [p for p in carried if p.startswith(".claude/")]
          and ".claude/.gitignore" in text2
          and ".claude/audit.config.json" in text2
          and "plugin-owned" in text2)
    # A REFUSAL STILL SAYS WHAT IT LEFT OUT. The ignore file is tracked in many
    # projects, so the close the operator retries after removing the ordinary
    # stray will leave the plugin's paths uncommitted; the refusal is where
    # they first read that, not only the commit that follows it.
    owned_lines = [ln for ln in text.splitlines()
                   if ln.startswith("  degraded: plugin-owned")]
    check("ctw-at19 the refusal over an ordinary stray also prints, on its own "
          "line, the plugin-owned paths that would be left out - the ignore "
          "file and the configuration file each named: %r" % (owned_lines,),
          code == 1 and len(owned_lines) == 1
          and ".claude/.gitignore" in owned_lines[0]
          and ".claude/audit.config.json" in owned_lines[0])

    # The a2 state: the ignore line had been reverted, so the restore point
    # itself is an untracked file git lists - and is named, not refused.
    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    backups = os.path.join(fx["root"], ".claude", _mio.BACKUP_DIR_NAME)
    os.makedirs(backups)
    restore_rel = ".claude/%s/audit-plan.json.bak-20261022T100219Z" % (
        _mio.BACKUP_DIR_NAME,)
    _write(os.path.join(fx["root"], restore_rel), "{}\n")
    _gate(fx)
    code, text = _run(fx)
    carried = _carried(fx, _head(fx))
    check("ctw-at8 a restore point git lists as untracked is not refused as "
          "the task's edit, is named in the close and is not carried: %r"
          % ((scode, code, text[:500], carried),),
          scode == 0 and code == 0 and restore_rel in text
          and restore_rel not in carried and OWNED in carried)

    # THE CONFIGURATION FILE THE PROJECT COMMITS IS A FILE A TASK CAN EDIT. The
    # fixture commits it, so editing it mid-attempt is an undeclared change:
    # refused by name at the commit, which is the other half of the close's
    # (`lo-po4`), and the same edit with the file untracked is `ctw-at7`'s
    # allow. Removed again, the commit goes through - the refusal was about that
    # file and nothing else.
    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    config_path = os.path.join(fx["root"], ".claude", "audit.config.json")
    edited_config = _mio.read_json(config_path)
    edited_config["executor"] = {"waveWidth": 3}
    _write(config_path, json.dumps(edited_config, indent=2) + "\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    held = _head(fx)
    refusal = [ln for ln in text.splitlines()
               if ln.startswith("[commit-task-work] REFUSED")]
    TI._git(fx["root"], "checkout", "-q", "--", ".claude/audit.config.json")
    code2, text2 = _run(fx)
    check("ctw-at10 a TRACKED configuration file edited during the attempt "
          "refuses the commit by name and commits nothing; put back, the "
          "task's file is committed: %r"
          % ((scode, code, refusal[:1], code2, text2[:300]),),
          scode == 0 and code == 1 and len(refusal) == 1
          and ".claude/audit.config.json" in refusal[0]
          and "plugin-owned" not in text and held == before and code2 == 0)

    # The table is the writers' as well as the check's: what the restore-point
    # writer creates - the directory and the ignore file it adds a line to - is
    # a row of it, so a rename in one place cannot leave the other behind. The
    # configuration file's row is named here too: `ctw-at7` reaches it only
    # through the close its edit would refuse, and this case says which row of
    # the table went missing.
    fx = repos.make()
    backups, _ignored = _mio.ensure_backup_dir(fx["manifest"])
    owned = _mio.plugin_owned_under(os.path.join(fx["root"], ".claude"))
    paths = [p for p, _why in owned]
    check("ctw-at9 the directory the restore-point writer creates, the "
          "ignore file it appends to and the configuration file are rows of "
          "the plugin-owned table the commit check reads, each with a reason: "
          "%r" % (owned,),
          backups in paths
          and os.path.join(fx["root"], ".claude", ".gitignore") in paths
          and os.path.join(fx["root"], ".claude", _mio.CONFIG_NAME) in paths
          and all(isinstance(why, str) and why for _p, why in owned))


CE_TEST = "tests/test_a.py"


def _owe_test(fx):
    """The fixture task names `CE_TEST` in its `tests.add` and declares it."""
    shard = _mio.read_json(fx["shard"])
    task = [t for t in shard["tasks"] if t.get("id") == TASK][0]
    task["tests"]["add"] = ["%s: the a case" % (CE_TEST,)]
    TI._write_json(fx["shard"], shard)
    _set_task(fx, files=[OWNED, CE_TEST])


@_own_repos
def _close_evidence_cases(check, repos):
    """A commit standing for a task's close refuses a return that attempted
    nothing over no declared change, and a `tests.add` file never written;
    real work with its test present commits."""
    fx = repos.make()
    _file_executor_return(fx)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw-ce1 a filed return whose red-first is `not-attempted`, with no "
          "change in any declared file - only the records pending - is refused "
          "by name and offers restart or cancel; nothing is committed or left "
          "staged: %r" % ((code, text[:500]),),
          code == 1 and "not-attempted" in text and "cancel" in text
          and "/audit:task start" in text and _head(fx) == before
          and _staged(fx) == [])

    fx = repos.make()
    _file_executor_return(fx)
    _owe_test(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # the task's own work\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw-ce2 a `tests.add` file absent at the commit refuses it by name, "
          "over a real change in a declared file: %r" % ((code, text[:500]),),
          code == 1 and CE_TEST in text and _head(fx) == before
          and _staged(fx) == [])

    fx = repos.make()
    _file_executor_return(fx)
    _owe_test(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # the task's own work\n")
    os.makedirs(os.path.join(fx["root"], "tests"), exist_ok=True)
    _write(os.path.join(fx["root"], CE_TEST), "assert True\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    carried = _carried(fx, _head(fx)) if _head(fx) != before else []
    check("ctw-ce3 ALLOW: the same `not-attempted` return beside a real change, "
          "with the `tests.add` file written, commits both: %r"
          % ((code, text[:300], carried),),
          code == 0 and OWNED in carried and CE_TEST in carried)


RECORDS_ONLY_CLAUSE = ("a task commit whose staged change holds only plan and "
                       "record files is refused, naming the declared files, "
                       "while an explicit no-change close still records")
ALL_NEW_CLAUSE = ("a task whose declared files are all new and absent from the "
                  "commit tree is refused under could-not-prove too")
# A declared file no fixture commit has ever held: the task's work is a NEW
# file, which a tree that never ran the task does not have.
FRESH = "src/fresh.py"


def _file_started_return(fx, status):
    """File an executor return for the task's REAL start, with red-first
    `status` - the start `audit-task.py start` recorded, not a made-up one, so
    the close verb that follows reads the same attempt."""
    import _filed_returns
    task = [t for t in _mio.read_json(fx["shard"])["tasks"]
            if t.get("id") == TASK][0]
    body = {"gates": {}, "outcome": {"technical": "t", "descriptive": "d"},
            "testsAdded": [], "stamp": "audit-stamp: v2 x",
            "redFirst": {"status": status, "basis": "the helper could not run"}}
    path = _filed_returns.return_path(
        os.path.join(fx["root"], "docs", "audit", "evidence"), task, "executor")
    _filed_returns.file_once(path, json.dumps(body) + "\n")


def _done_no_change(fx, reason):
    """`(code, text)` of `/audit:task done --no-change` on the fixture task."""
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = AT.main(["done", TASK, "--no-change", "--reason", reason,
                        "--project-dir", fx["root"]], out=lines.append)
    finally:
        sys.stderr = held
    return code, "\n".join(str(x) for x in lines)


@_own_repos
def _records_only_cases(check, repos):
    """A task commit standing for work refuses a change that is plan and record
    files only, whatever the red-first word says - the shape a task run in a
    tree that never held its work leaves - and names the no-change verb, which
    still closes a task whose answer really was that nothing needed to change."""
    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _file_started_return(fx, "could-not-prove")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    refused = (code, text, _head(fx), _staged(fx))
    dcode, dtext = _done_no_change(fx, "the declared file already does this")
    _manifest, _phase, task = _phase_and_task(fx)
    no_change = (task.get("outcome") or {}).get("noChange") or {}
    check("ctw-ro1 %s: %r" % (RECORDS_ONLY_CLAUSE, (
              scode, said[-200:], refused[0], refused[1][:600], dcode,
              dtext[-300:], task.get("status"), no_change)),
          scode == 0 and refused[0] == 1 and OWNED in refused[1]
          and "--no-change" in refused[1] and fx["root"] in refused[1]
          and refused[2] == before and refused[3] == []
          and dcode == 0 and task.get("status") == "done"
          and no_change.get("reason") == "the declared file already does this")

    # SECOND-DIRECTION CASE, for a refusal made unconditional: the same
    # `could-not-prove` return beside a real change in the declared file
    # commits it.
    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _file_started_return(fx, "could-not-prove")
    _write(os.path.join(fx["root"], OWNED), "a = 2  # the task's own work\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    carried = _carried(fx, _head(fx)) if _head(fx) != before else []
    check("ctw-ro2 ALLOW: the same `could-not-prove` return beside a change in "
          "the declared file commits it: %r" % ((scode, code, text[:300], carried),),
          scode == 0 and code == 0 and OWNED in carried)

    fx = repos.make()
    _set_task(fx, files=[FRESH])
    _restartable(fx)
    scode, said = _start(fx)
    _file_started_return(fx, "could-not-prove")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw-ro3 %s: %r" % (ALL_NEW_CLAUSE, (
              scode, said[-200:], code, text[:600], _head(fx) == before,
              _staged(fx))),
          scode == 0 and code == 1 and FRESH in text
          and "--no-change" in text and _head(fx) == before
          and _staged(fx) == [])

    # SECOND-DIRECTION CASE, for a refusal keyed on the declaration alone: the
    # same all-new declaration with the new file written commits it.
    fx = repos.make()
    _set_task(fx, files=[FRESH])
    _restartable(fx)
    scode, said = _start(fx)
    _file_started_return(fx, "could-not-prove")
    _write(os.path.join(fx["root"], FRESH), "fresh = 1  # the task's new file\n")
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    carried = _carried(fx, _head(fx)) if _head(fx) != before else []
    check("ctw-ro4 ALLOW: the same all-new declaration, its file written, "
          "commits it: %r" % ((scode, code, text[:300], carried),),
          scode == 0 and code == 0 and FRESH in carried)


@_own_repos
def _fixture_git_cases(check, repos):
    """A fixture git command that fails carries git's own stderr text."""
    fx = repos.make()
    dest = repos.scratch("fg-missing")
    try:
        _clone_at(fx, "0" * 40, dest)
        raised = None
    except Exception as exc:                  # noqa: BLE001 - the text is the subject
        raised = exc
    text = str(raised)
    check("ctw-fg1 a fixture git command that fails raises an error carrying "
          "git's own stderr text (a checkout of a commit that does not exist "
          "names it, not only the exit status): %r" % (text[:300],),
          raised is not None and "fatal:" in text and "failed" in text)
    check("ctw-fg2 ALLOW: a fixture git command that succeeds raises nothing "
          "and returns the clone's path",
          os.path.isdir(_clone_at(fx, _head(fx), repos.scratch("fg-ok"))))


def _fixture_git_prefixes():
    """`{label: argv prefix}` for every fixture git prefix the suites declare.

    Read off the modules themselves rather than restated here, so a prefix
    rewritten without the switch is seen by its value. A suite whose fixture
    git gains a new prefix owes a row here."""
    import test_hooks
    import test_integrate_task
    import test_run_test_gate
    return {"_harness.GIT": _harness.GIT,
            "_harness.WORKTREE_PAIR_GIT": _harness.WORKTREE_PAIR_GIT,
            "test_hooks._GIT": test_hooks._GIT,
            "test_integrate_task.GIT": test_integrate_task.GIT,
            "test_run_test_gate._PLAIN_GIT": test_run_test_gate._PLAIN_GIT,
            "test_run_test_gate._SM_GIT": test_run_test_gate._SM_GIT}


def _carries(prefix, setting):
    """Whether `prefix` passes `-c <setting>` as one adjacent pair."""
    words = list(prefix)
    return any(words[i] == "-c" and words[i + 1] == setting
               for i in range(len(words) - 1))


def _traced_commit_spawns(prefix, scratch):
    """`(commit traced, maintenance spawns)` for one fixture commit made with
    `prefix` under GIT_TRACE - the first so a trace that recorded nothing
    cannot read as a commit that spawned nothing."""
    repo = os.path.join(scratch, "repo")
    trace = os.path.join(scratch, "trace.log")
    _harness.git(None, "init", "-q", repo, prefix=prefix)
    _write(os.path.join(repo, "a.txt"), "a\n")
    _harness.git(repo, "add", "a.txt", prefix=prefix)
    # THE PREFIX ALONE IS MEASURED: the sweep hands every child its own config
    # pairs through `GIT_CONFIG_COUNT`, which switch the same keys off, so they
    # are taken out here or the deny twin could never see a spawn.
    env = dict((k, v) for k, v in os.environ.items()
               if k != "GIT_CONFIG_COUNT"
               and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")))
    env["GIT_TRACE"] = trace
    subprocess.run(list(prefix) + ["commit", "-q", "-m", "traced"], cwd=repo,
                   env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   stdin=subprocess.DEVNULL, timeout=_harness.GIT_TIMEOUT)
    lines = (_read(trace) or "").splitlines()
    committed = any("built-in: git" in ln and " commit " in ln for ln in lines)
    spawns = [ln for ln in lines if "run_command:" in ln
              and ("maintenance run" in ln or " gc " in ln)]
    return committed, spawns


def _no_maintenance_cases(check):
    """Fixture git starts no background maintenance in a fixture repository."""
    import tempfile
    prefixes = _fixture_git_prefixes()
    missing = sorted(label for label, prefix in prefixes.items()
                     if not (_carries(prefix, "maintenance.auto=false")
                             and _carries(prefix, "gc.auto=0")))
    switched = tempfile.mkdtemp(prefix="ctw-nm-")
    plain = tempfile.mkdtemp(prefix="ctw-nm-")
    try:
        committed, spawns = _traced_commit_spawns(_harness.GIT, switched)
        # The same commit without the switch, run in the foreground so the
        # control leaves no background process of its own behind.
        bare = (("git", "-c", "maintenance.autoDetach=false")
                + _harness.GIT[1 + len(_harness.NO_AUTO_MAINTENANCE):])
        bare_committed, bare_spawns = _traced_commit_spawns(bare, plain)
    finally:
        _harness.remove_tree(switched)
        _harness.remove_tree(plain)
    check("ctw-nm1 no fixture git call can spawn an auto gc - the shared prefix "
          "and every suite's own prefix carry gc.auto=0 - measured with "
          "GIT_TRACE on a heavy fixture (and maintenance.auto=false beside it: "
          "every fixture git prefix carries both settings, and a fixture commit "
          "traced with the shared prefix spawns no background maintenance; "
          "prefixes missing a setting %r, commit traced %r, spawns %r)"
          % (missing, committed, spawns),
          len(prefixes) == 6 and missing == [] and committed and spawns == [])
    check("ctw-nm2 SECOND-DIRECTION CASE: the same traced commit WITHOUT the "
          "switch does spawn maintenance, so the trace reading in ctw-nm1 can "
          "see a spawn and its empty list is not a trace that read nothing: "
          "commit traced %r, spawns %r" % (bare_committed, bare_spawns),
          bare_committed and len(bare_spawns) >= 1)


EARLIER_COMMIT_CLAUSE = ("a task whose declared work is already in an earlier "
                         "commit since its start is refused by a commit that "
                         "would carry records only, and the refusal names "
                         "`audit-task.py done <id> --commit <sha>`")


@_own_repos
def _earlier_commit_cases(check, repos):
    """The refusal of a records-only task commit points at the repair that fits:
    work committed since the start closes through `done --commit`, not through
    `--no-change` or a worktree to bring in."""
    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _file_started_return(fx, "could-not-prove")
    _write(os.path.join(fx["root"], OWNED), "a = 2  # the task's own work\n")
    TI._git(fx["root"], "add", "--", OWNED)
    TI._git(fx["root"], "commit", "-q", "-m", "the task's work, committed by hand",
            "--", OWNED)
    work = _head(fx)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    check("ctw-ro5 %s: %r" % (EARLIER_COMMIT_CLAUSE, (
              scode, said[-200:], code, text[:900], _head(fx) == before,
              _staged(fx))),
          scode == 0 and code == 1 and _head(fx) == before and _staged(fx) == []
          and "audit-task.py done %s --commit %s" % (TASK, work[:12]) in text
          and "--no-change" not in text and "bring it into" not in text)

    # SECOND-DIRECTION CASE, for advice made unconditional: with no earlier
    # commit holding the work the refusal still names `--no-change` and names
    # no `--commit`.
    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _file_started_return(fx, "could-not-prove")
    _gate(fx)
    code, text = _run(fx)
    check("ctw-ro6 ALLOW: a records-only refusal with no earlier commit of the "
          "work keeps naming `--no-change` and names no `--commit`: %r"
          % ((scode, code, text[:600]),),
          scode == 0 and code == 1 and "--no-change" in text
          and "--commit" not in text)


def _json_attempt(fx):
    """`(code, attempt)` - the `attempt` attribution of one `--json` run."""
    code, text = _run(fx, TASK, "--json")
    try:
        answer = json.loads(text)
    except ValueError:
        return code, None
    return code, (answer or {}).get("attempt")


@_own_repos
def _clean_at_start_cases(check, repos):
    """A refused commit's attribution names which of the strays changed during
    the attempt were CLEAN at its start - absent from the snapshot `start`
    recorded of every dirty path - so a caller that puts a path back to HEAD
    never puts back bytes the attempt did not write. With no snapshot nothing
    is clean at the start by any basis, and the list is empty."""
    fx = repos.make()
    _restartable(fx)
    # Dirty before the start, and touched again after it: a stray of mixed age.
    _write(os.path.join(fx["root"], "src", "dirty.txt"), "an owner's edit\n")
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    _write(os.path.join(fx["root"], "src", "dirty.txt"),
           "an owner's edit\nand the attempt's line\n")
    _write(os.path.join(fx["root"], "src", "img.png"), "copied in\n")
    _gate(fx)
    code, attempt = _json_attempt(fx)
    attempt = attempt or {}
    # The red for a list that is `during` itself: the stray of mixed age is in
    # `during` and must not be in `cleanAtStart`.
    check("ctw-cs1 the attribution of a refused commit lists, as cleanAtStart, "
          "the strays changed during the attempt that the start snapshot does "
          "not hold - the created file - and not the one dirty before the start "
          "and changed since: %r" % ((scode, code, attempt),),
          scode == 0 and code == 1
          and sorted(attempt.get("during") or []) == ["src/dirty.txt", "src/img.png"]
          and attempt.get("cleanAtStart") == ["src/img.png"])

    fx = repos.make()
    _restartable(fx)
    scode, said = _start(fx)
    _write(os.path.join(fx["root"], OWNED), "a = 2  # this attempt's work\n")
    _write(os.path.join(fx["root"], "src", "img.png"), "copied in\n")
    os.remove(_scoped_commit.attempt_record_path(
        M.attempt_state_dir(fx["root"], {}), TASK))
    _gate(fx)
    code, attempt = _json_attempt(fx)
    attempt = attempt or {}
    # The red for a list read off `during` whatever the basis: by mtime a
    # change is dated, never shown clean at the start.
    check("ctw-cs2 with no start snapshot the strays are dated by mtime and "
          "cleanAtStart is empty - present and [] - though the created file is "
          "in during: %r" % ((scode, code, attempt),),
          scode == 0 and code == 1 and "src/img.png" in (attempt.get("during") or [])
          and attempt.get("cleanAtStart") == []
          and bool(attempt.get("basis"))
          and attempt.get("basis") != _scoped_commit.BASIS_SNAPSHOT)


# --- one verb: the index rows ride with the shard, and the state commit -------
ADDED = "src/added.py"


def _add_task(fx, path=ADDED):
    """`(code, newTaskId)` of the real `/audit:task add` putting a task declaring
    `path` into the running phase - what it writes is the shard AND the index,
    both left uncommitted, and a hand-written fixture of that would grade the
    committer against a shape the verb never produces."""
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = AT.main(["add", "Added mid-phase", "--phase", PHASE, "--files",
                        path, "--project-dir", fx["root"]], out=lines.append)
    finally:
        sys.stderr = held
    added = [t.get("id") for t in _mio.read_json(fx["shard"])["tasks"]
             if path in (t.get("files") or [])]
    return code, (added[0] if added else None)


def _state(fx, *extra):
    """`(code, text)` of the one verb asked for a phase's STATE commit, in-process.
    A usage error is caught as its exit code so a build without the mode fails
    its own assertion instead of taking the stage down."""
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main([fx["manifest"], PHASE, "--state", "--project",
                       fx["root"]] + list(extra), out=lines.append)
    except SystemExit as exc:
        code = exc.code
    finally:
        sys.stderr = held
    return code, "\n".join(str(x) for x in lines)


def _commits_between(fx, older, newer):
    return int(TI._git(fx["root"], "rev-list", "--count",
                       "%s..%s" % (older, newer)).strip())


@_own_repos
def _one_verb_cases(check, repos):
    """A task added mid-phase writes the shard and the index; the next task
    commit carries both, the index limited to the rows the shard needs, and no
    other verb runs. The state commit after an interrupted run is the same verb,
    and it never carries a task's files."""
    # --- a task added to a running phase, then a task committed ---------------
    fx = repos.make()
    acode, added = _add_task(fx)
    _dirty_work(fx)
    # An index edit no shard needs, beside the added rows: it must stay out.
    index = _mio.read_json(fx["manifest"])
    index["meta"]["title"] = "touched"
    TI._write_json(fx["manifest"], index)
    _gate(fx)
    before = _head(fx)
    code, text = _run(fx)
    after = _head(fx)
    carried = _carried(fx, after) if after != before else []
    findings, committed = (_validates_at(fx, after, repos.scratch("ov-added"))
                           if after != before else (["no commit"], {}))
    check("ov1 RED-FIRST: after `/audit:task add` put %s into the running "
          "phase, the next task commit SUCCEEDS as one commit with no other "
          "verb run, carrying the shard and the index together, the committed "
          "index holding the added task's row and validating on a fresh clone: "
          "%r" % (added, (acode, code, carried, findings[:2], text[-300:]),),
          acode == 0 and bool(added) and code == 0
          and _commits_between(fx, before, after) == 1
          and SHARD_REL in carried and INDEX_REL in carried
          and (committed.get("fileIndex") or {}).get(ADDED) == [added]
          and findings == [])
    check("ov2 SECOND-DIRECTION CASE: the index the task commit carries is "
          "the parent's with the phase's own part derived, not the working "
          "file - the "
          "unrelated title edit is absent from the commit and still sitting "
          "in the working tree: %r"
          % ((committed.get("meta") or {}).get("title"),),
          after != before and INDEX_REL in carried
          and (committed.get("meta") or {}).get("title") != "touched"
          and _mio.read_json(fx["manifest"])["meta"]["title"] == "touched")
    _manifest, phase, task = _phase_and_task(fx)
    task["commit"] = after
    graded = _invariants.commit_scope(
        phase, fx["root"], ".", SHARD_REL, INDEX_REL,
        "docs/audit/journal", "docs/audit/evidence")
    check("ov3 ...and the grader reads the same commit and calls it clean: an "
          "index carried for the rows its shard needs is in scope: %r"
          % (graded.get("breaches"),),
          after != before and INDEX_REL in carried
          and not graded.get("breaches"))

    # --- the state commit after an interrupted run --------------------------
    fx = repos.make()
    acode, added = _add_task(fx)
    _dirty_work(fx)
    before = _head(fx)
    code, text = _state(fx)
    after = _head(fx)
    carried = _carried(fx, after) if after != before else []
    subject = TI._git(fx["root"], "log", "-1", "--format=%s").strip()
    findings, committed = (_validates_at(fx, after, repos.scratch("ov-state"))
                           if after != before else (["no commit"], {}))
    check("ov4 RED-FIRST: the state commit after an interrupted run is made by "
          "the same verb (`--state` with a phase id): one commit, an "
          "audit-state subject, carrying the shard and the index rows it needs, "
          "validating on a fresh clone: %r"
          % ((code, subject, carried, findings[:2], text[-300:]),),
          code == 0 and after != before
          and _commits_between(fx, before, after) == 1
          and subject.startswith("chore(audit-state): phase %s" % (PHASE,))
          and SHARD_REL in carried and INDEX_REL in carried
          and (committed.get("fileIndex") or {}).get(ADDED) == [added]
          and findings == [])
    clone = _clone_at(fx, after, repos.scratch("ov-state-files")) \
        if after != before else None
    check("ov5 ...and it never stages a task's files: the declared file, the "
          "sibling's and the stray are absent from the commit, their old bytes "
          "on the clone, and still modified in the working tree: %r"
          % (carried,),
          clone is not None
          and not any(p in carried for p in (OWNED, SIBLING, "src/stray.py"))
          and _read(os.path.join(clone, OWNED)) == "a = 1\n"
          and _read(os.path.join(fx["root"], OWNED))
          == "a = 2  # the task's own work\n"
          and _staged(fx) == [])

    # --- the folded entry points are gone, and nothing ships naming them -----
    gone = ("commit-" + "manifest-index.py", "commit-" + "audit-state.py")
    present = [n for n in gone
               if os.path.exists(os.path.join(_output.SCRIPTS_DIR,
                                              "governance", n))]
    naming = []
    for base, dirs, names in os.walk(_output.PLUGIN_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            path = os.path.join(base, name)
            with open(path, "rb") as fh:
                raw = fh.read()
            naming.extend("%s: %s" % (os.path.relpath(path, _output.PLUGIN_ROOT),
                                      n) for n in gone
                          if n[:-3].encode("ascii") in raw)
    check("ov6 the two folded entry points are deleted, and no file the plugin "
          "ships names either of them: %r" % ((present, naming[:6]),),
          present == [] and naming == [])


# --- the owned part of the index, against the parent the commit is made on ---
def _index_at(fx, sha):
    return _invariants.json_at(fx["root"], sha, INDEX_REL) or {}


def _commit_head_index(fx, edit, message):
    """Another session's commit of the index alone, on top of HEAD: HEAD's
    index with `edit` applied, committed, and the working file put back as it
    was - the shape of a commit that lands between this session's read of HEAD
    and its own commit."""
    working = _read(fx["manifest"])
    index = _index_at(fx, "HEAD")
    edit(index)
    TI._write_json(fx["manifest"], index)
    TI._git(fx["root"], "commit", "-q", "-m", message, "--", INDEX_REL)
    _write(fx["manifest"], working)
    return _head(fx)


def _move(fx, tid, target):
    """`(code, newId)` of the real `/audit:task move`."""
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = AT.main(["move", tid, "--to", target, "--project-dir",
                        fx["root"]], out=lines.append)
    finally:
        sys.stderr = held
    p2 = _mio.read_json(os.path.join(os.path.dirname(fx["shard"]),
                                     "%s.json" % (target,)))
    moved = [t.get("id") for t in p2.get("tasks") or []
             if ADDED in (t.get("files") or [])]
    return code, (moved[0] if moved else None)


@_own_repos
def _owned_index_cases(check, repos):
    """The one invariant: the part of the index a phase owns - its tasks'
    fileIndex rows, the bug links its shard completes, its stub's mirrored
    keys - equals what its shard derives, laid over the parent the commit is
    actually made on; everything else is that parent's."""
    # --- another session's index commit lands between the read and the commit
    fx = repos.make()
    _acode, added = _add_task(fx)
    _dirty_work(fx)
    _gate(fx)
    before = _head(fx)
    real = _scoped_commit.commit_with_rows
    moved = []

    def other_session_first(*args, **kwargs):
        moved.append(_commit_head_index(
            fx, lambda ix: ix["meta"].update({"title": "other session"}),
            "chore(audit-index): phase P2 - another session's index commit"))
        return real(*args, **kwargs)
    _scoped_commit.commit_with_rows = other_session_first
    try:
        code, text = _run(fx)
    finally:
        _scoped_commit.commit_with_rows = real
    after = _head(fx)
    landed = _index_at(fx, after)
    check("oi1 RED-FIRST: when another session's index commit lands after this "
          "commit read HEAD and before it commits, the index it carries is "
          "built on THAT commit - the other session's edit survives, beside the "
          "row this task's shard derives, and the commit's parent is the other "
          "session's: %r" % ((code, (landed.get("meta") or {}).get("title"),
                              (landed.get("fileIndex") or {}).get(ADDED),
                              text[-300:]),),
          code == 0 and bool(moved) and after not in (before, moved[0])
          and TI._git(fx["root"], "rev-parse", after + "^").strip() == moved[0]
          and (landed.get("meta") or {}).get("title") == "other session"
          and (landed.get("fileIndex") or {}).get(ADDED) == [added])

    # --- a state commit in its fallback carries this phase's stub mirror -----
    fx = repos.make()
    p2 = os.path.join(os.path.dirname(fx["shard"]), "P2.json")
    other = _mio.read_json(p2)
    other["tasks"].append(dict(other["tasks"][0], id="P2.2", status="pending",
                               files=["src/p22.py"]))
    TI._write_json(p2, other)
    index = _mio.read_json(fx["manifest"])
    index["fileIndex"]["src/p22.py"] = ["P2.2"]
    TI._write_json(fx["manifest"], index)
    shard = _mio.read_json(fx["shard"])
    shard["status"] = "done"
    TI._write_json(fx["shard"], shard)
    before = _head(fx)
    code, text = _state(fx, "--json")
    answer = json.loads(text) if text.startswith("{") else {}
    landed = _index_at(fx, _head(fx))
    stub = [s for s in landed.get("phases") or [] if s.get("id") == PHASE]
    check("oi2 RED-FIRST: a state commit whose working index is ahead of "
          "another phase's shard - so only this phase's part rides - still "
          "carries this phase's stub mirrored from its shard (the stamp a "
          "landing or sign-off writes), leaves the other phase's row out, and "
          "names what it left in `indexLeft` for its caller: %r"
          % ((code, stub[:1], answer.get("indexCarried"),
              answer.get("indexLeft")),),
          code == 0 and _head(fx) != before
          and answer.get("indexCarried") == "needs"
          and bool(stub) and stub[0].get("status") == "done"
          and "src/p22.py" not in (landed.get("fileIndex") or {})
          and any("P2.2" in line for line in answer.get("indexLeft") or []))

    # --- a task moved away takes its row with it ----------------------------
    fx = repos.make()
    _acode, added = _add_task(fx)
    _state(fx)
    mcode, new_id = _move(fx, added, "P2")
    code1, text1 = _state(fx)
    first = _head(fx)
    f1, idx1 = _validates_at(fx, first, repos.scratch("oi-move-1"))
    code2, _text2 = _state_main([fx["manifest"], "P2", "--state", "--project",
                                 fx["root"]])
    f2, idx2 = _validates_at(fx, _head(fx), repos.scratch("oi-move-2"))
    check("oi3 RED-FIRST: after `/audit:task move` takes %s to P2, P1's state "
          "commit drops the row naming it - its shard held the task and no "
          "longer derives it - and the plan it records validates; P2's then "
          "carries the row under the new id, valid too: %r"
          % (added, ((mcode, new_id, code1, code2), f1[:2], f2[:2],
                     (idx1.get("fileIndex") or {}).get(ADDED),
                     (idx2.get("fileIndex") or {}).get(ADDED), text1[-200:]),),
          mcode == 0 and bool(new_id) and code1 == 0 and code2 == 0
          and f1 == [] and f2 == []
          and added not in ((idx1.get("fileIndex") or {}).get(ADDED) or [])
          and (idx2.get("fileIndex") or {}).get(ADDED) == [new_id])

    # --- the grader's equality: needs plus one unrelated edit is a breach ----
    fx = repos.make()
    _acode, added = _add_task(fx)
    _dirty_work(fx)
    _gate(fx)
    code, _text = _run(fx)
    made = _head(fx)
    smuggled = _index_at(fx, made)
    smuggled["meta"]["title"] = "smuggled beside the rows"
    TI._write_json(fx["manifest"], smuggled)
    TI._git(fx["root"], "add", "--", INDEX_REL)
    TI._git(fx["root"], "commit", "-q", "--amend", "--no-edit")
    amended = _head(fx)
    _manifest, phase, task = _phase_and_task(fx)
    task["commit"] = amended
    graded = _invariants.commit_scope(
        phase, fx["root"], ".", SHARD_REL, INDEX_REL,
        "docs/audit/journal", "docs/audit/evidence")
    check("oi4 a task commit whose index carries the rows its shard derives AND "
          "one unrelated edit is a commit-scope breach naming the index - the "
          "derived part being right does not license the rest: %r"
          % (graded.get("breaches"),),
          code == 0 and amended != made
          and len(graded.get("breaches") or []) == 1
          and INDEX_REL in graded["breaches"][0])

    # --- the callers say what a state commit left ---------------------------
    cp = _loader.load_script("close-phase.py", "cp_for_ctw_left")
    dp = _loader.load_script("drive-phase.py", "dp_for_ctw_left")
    left = ["the rest of the manifest index stays uncommitted in the working "
            "tree: it names task P2.2"]
    real_verb = cp._commit_verb
    cp._commit_verb = lambda *a: ({"commit": "c" * 40, "indexLeft": left}, None)
    try:
        stamp = cp._commit_stamp("m.json", PHASE, "/nowhere", "main")
    finally:
        cp._commit_verb = real_verb
    printed = []
    cp._render_left(stamp, printed.append)
    sha, lines = dp._state_answer(json.dumps({"commit": "d" * 40,
                                              "indexLeft": left}))
    check("oi5 a landing's and a sign-off's caller print what the state commit "
          "left of the index beside the commit they report, and say nothing "
          "when it left nothing: %r" % ((stamp, printed, sha, lines),),
          stamp.get("landingCommitLeft") == left and len(printed) == 1
          and "P2.2" in printed[0] and sha == "d" * 40 and len(lines) == 1
          and "P2.2" in lines[0]
          and dp._state_answer(json.dumps({"commit": "e" * 40}))[1] == [])


# --- the state commit: the record of a run, without the work it ran on -------
# Every assertion about what was preserved is made against a FRESH CLONE at the
# commit, and every case proving it carried the record is paired with one
# proving it left the work alone: the clone still holds the committed baseline of
# `src/a.py`, the working tree still holds the failed fix, and the index is empty
# afterwards. Any one of those alone passes for a command that committed
# everything, or for one that committed nothing.
EVIDENCE_REL = "docs/audit/evidence/" + TI.EVIDENCE_NAME


def _porcelain(fx):
    return [ln for ln in TI._git(fx["root"], "status",
                                 "--porcelain").splitlines() if ln.strip()]


def _state_rows(fx):
    return [r for r in _journal_io.read_all(fx["root"])
            if r.get("action") == _invariants.ACTION_STATE_COMMITTED]


def _exhaust(fx):
    """Mark P1.2 blocked with its attempts spent, and record why - what step 4
    leaves when the gate stayed red to the last retry: the manifest moved, the
    code did not, and nothing commits."""
    shard = _mio.read_json(fx["shard"])
    task = shard["tasks"][1]
    task["status"] = "blocked"
    task["attempts"] = task["maxAttempts"]
    task["outcome"]["technical"] = "the gate stayed red on every attempt"
    TI._write_json(fx["shard"], shard)
    return shard


def _state_main(argv):
    """`(code, lines)` of `M.main(argv)`, stderr swallowed."""
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main(argv, out=lines.append)
    finally:
        sys.stderr = held
    return code, lines


@_own_repos
def _state_cases(check, repos):
    """A failed run's record committed by `--state`, its work left alone; the
    subject a commitlint repository takes; the do-nothing answers; a record
    outside the repository; the allow-list as a list; usage; the row."""
    fx = repos.make(leave_dirty=True)
    _exhaust(fx)
    before = _head(fx)
    code, text = _state(fx)
    after = _head(fx)
    check("cas1 a task that ran out of attempts leaves a red gate's evidence "
          "and a moved manifest with nothing to commit them - `--state` makes "
          "one commit and reports its SHA: %r / %r" % (code, text),
          code == 0 and after != before and after[:12] in text)

    clone = _clone_at(fx, after, repos.scratch("exhausted"))
    carried = _read(os.path.join(clone, EVIDENCE_REL))
    carried_row = json.loads(carried) if carried else {}
    check("cas2 ...and the failure rows are IN THE COMMIT, asserted from a "
          "fresh clone checked out at it: %r" % (carried_row,),
          carried_row.get("status") == "failed"
          and carried_row.get("runId") == TI.FAILED_RUN_ID
          and carried_row.get("taskId") == "P1.2")
    cloned_shard = json.loads(_read(os.path.join(clone, SHARD_REL)))
    check("cas3 ...and so is the manifest state that says why: the committed "
          "shard has P1.2 blocked with its attempts spent: %r"
          % (cloned_shard["tasks"][1]["status"],),
          cloned_shard["tasks"][1]["status"] == "blocked"
          and cloned_shard["tasks"][1]["attempts"]
          == cloned_shard["tasks"][1]["maxAttempts"])
    cloned_impl = _read(os.path.join(clone, OWNED))
    working_impl = _read(os.path.join(fx["root"], OWNED))
    check("cas4 ...and the WORK is not. The clone still holds the baseline "
          "`src/a.py` while the working tree holds the fix that failed - the "
          "pair, because 'the clone lacks the fix' also passes for a command "
          "that deleted it: %r / %r" % (cloned_impl, working_impl),
          cloned_impl == "a = 1\n"
          and working_impl == "a = 2  # the fix that failed\n")
    check("cas5 ...and it was never staged either: the index is empty and the "
          "tree still reports the file as modified: %r / %r"
          % (_staged(fx), _porcelain(fx)),
          _staged(fx) == []
          and any(ln.endswith(OWNED) and ln[:2].strip()
                  for ln in _porcelain(fx)))

    rows = _state_rows(fx)
    details = rows[0].get("details") if rows else {}
    nonce = details.get(_invariants.NONCE_KEY)
    resolved, _why = _invariants.commits_carrying(fx["root"], [nonce])
    check("cas6 the commit anchors itself with exactly one journal row "
          "carrying a nonce and the phase, and the nonce resolves to THIS "
          "commit through its trailer: %r -> %r" % (details, resolved),
          len(rows) == 1 and (resolved or {}).get(nonce) == [after]
          and _trailer_of(fx, after) == [nonce]
          and details.get("phaseId") == PHASE)
    check("cas7 ...and both keys are on `_journal_io.DETAILS_KEYS`, checked "
          "rather than assumed: the allow-list silently DROPS a key it does "
          "not know",
          _invariants.NONCE_KEY in _journal_io.DETAILS_KEYS
          and "phaseId" in _journal_io.DETAILS_KEYS)

    subject = TI._git(fx["root"], "log", "-1", "--format=%s").strip()
    check("cas8 the separating literal is a fixed SCOPE, not "
          "`meta.commit.type` - only a literal nothing in the manifest reaches "
          "can never collide with a task commit; the phase id stays in the "
          "subject: %r" % (subject,),
          subject.startswith("%s(%s): %s %s"
                             % (M.COMMIT_TYPE, M.COMMIT_SCOPE,
                                M.STATE_SUBJECT_LEAD, PHASE))
          and M.COMMIT_SCOPE not in ("", None) and PHASE in subject)
    check("cas8b ...and the type is one conventional-commit tooling accepts - "
          "a repo with husky+commitlint refuses an unknown type AFTER the files "
          "are staged: %r" % (M.COMMIT_TYPE,),
          M.COMMIT_TYPE in ("build", "chore", "ci", "docs", "feat", "fix",
                                  "perf", "refactor", "revert", "style", "test"))
    check("cas40 the header the scope reader checks a carrier by is the one "
          "this command writes, spelled from its own type and scope - two "
          "spellings would grade every real state commit as absorbed: %r"
          % (_invariants.STATE_HEADER,),
          _invariants.STATE_HEADER == "%s(%s): " % (M.COMMIT_TYPE,
                                                   M.COMMIT_SCOPE))
    was = "%s(%s): %s - %s" % (M.COMMIT_TYPE, M.COMMIT_SCOPE,
                               PHASE, M.STATE_DEFAULT_SUBJECT)
    check("cas8c ...and the SUBJECT git recorded is out of reach of every case "
          "commitlint's default `subject-case` forbids - the phase id leading a "
          "lowercase sentence IS sentence-case, so it opens with a fixed "
          "lowercase word: %r -> %r / the shape it replaced -> %r"
          % (subject, header_offences(subject), header_offences(was)),
          header_offences(subject) == []
          and header_offences(was) == ["sentence-case"])
    fired = dict((label, header_offences("chore(x): " + body))
                 for label, body in (
                     ("sentence-case", "P1 - the record of a run"),
                     ("start-case", "The Record Of A Run"),
                     ("pascal-case", "TheRecordOfARun"),
                     ("upper-case", "THE RECORD OF A RUN")))
    check("cas8d ...and that judgement can fire on each of the four, or cas8c "
          "is a green light from a check that may be asserting nothing: %r"
          % (fired,),
          all(label in names for label, names in fired.items())
          and fired["sentence-case"] == ["sentence-case"]
          and len(fired) == len(FORBIDDEN_CASES))
    composed = [M.state_header(PHASE, body) for body in
                ("preserved by hand after a red gate",
                 "Preserved by hand after a red gate")]
    check("cas8e ...and no `--subject` can put a capital, or the id, back in "
          "first position, and the id and the scope are still there: %r"
          % (composed,),
          all(header_offences(header) == [] and PHASE in header
              and header.startswith("%s(%s): %s %s - "
                                    % (M.COMMIT_TYPE, M.COMMIT_SCOPE,
                                       M.STATE_SUBJECT_LEAD, PHASE))
              for header in composed))
    check("cas8f ...and the header still fits commitlint's default "
          "`header-max-length`: %d against a limit of %d"
          % (len(subject), HEADER_MAX_LENGTH),
          len(subject) <= HEADER_MAX_LENGTH)
    spent = M.state_header(PHASE, "y" * (HEADER_MAX_LENGTH * 2))
    check("cas8g ...and a `--subject` longer than the whole budget is CUT "
          "rather than carried past it, and says it was cut: %r" % (spent,),
          len(spent) <= HEADER_MAX_LENGTH and header_offences(spent) == []
          and PHASE in spent
          and spent.startswith("%s(%s): %s %s - "
                               % (M.COMMIT_TYPE, M.COMMIT_SCOPE,
                                  M.STATE_SUBJECT_LEAD, PHASE))
          and spent.endswith(_scoped_commit.SUBJECT_TRUNCATED))

    code, text = _state(fx)
    check("cas9 called again it makes NO commit and says nothing is "
          "uncommitted - the row that anchored the last commit is inside it: "
          "%r / %r" % (code, text),
          code == 0 and _head(fx) == after
          and M.STATE_NOTHING_UNCOMMITTED in text
          and [ln for ln in _porcelain(fx) if "docs/audit/journal" in ln] == [])

    red = repos.make(leave_dirty=True)
    code, _text = _state(red)
    red_clone = _clone_at(red, _head(red), repos.scratch("red-gate"))
    red_shard = json.loads(_read(os.path.join(red_clone, SHARD_REL)))
    check("cas10 a phase whose sign-off gate went red commits its evidence "
          "while STAYING in_progress: %r" % (red_shard["status"],),
          code == 0 and red_shard["status"] == "in_progress"
          and _read(os.path.join(red_clone, EVIDENCE_REL)) is not None)

    quiet = repos.make()
    TI._git(quiet["root"], "add", SHARD_REL)
    TI._git(quiet["root"], "commit", "-q", "-m", "chore: settle the shard")
    settled = _head(quiet)
    code, text = _state(quiet)
    check("cas11 with nothing uncommitted no commit is made, and it SAYS so: "
          "%r / %r" % (code, text),
          code == 0 and _head(quiet) == settled
          and M.STATE_NOTHING_UNCOMMITTED in text)
    check("cas12 ...and it wrote no journal row either - the pair for cas6: %r"
          % (_state_rows(quiet),),
          _state_rows(quiet) == [])

    blocked = repos.make(leave_dirty=True)
    TI._git(blocked["root"], "add", OWNED)
    blocked_head = _head(blocked)
    code, text = _state(blocked)
    check("cas13 work already in the index is REFUSED rather than swept into "
          "the commit: %r / %r" % (code, text),
          code == 1 and _head(blocked) == blocked_head
          and OWNED in text and "REFUSED" in text)
    check("cas14 ...and the refusal changed nothing: the file somebody else "
          "staged is still staged and the evidence is NOT: %r"
          % (_staged(blocked),),
          _staged(blocked) == [OWNED])

    away = repos.make(evidence_outside=True)
    TI._evidence_file(away["audit"], "failed")
    code, text = _state(away)
    away_head = _head(away)
    away_clone = _clone_at(away, away_head, repos.scratch("outside"))
    check("cas15 an evidence directory outside the git root is degraded past "
          "and NAMED, and the commit still carries the manifest state: %r"
          % (text,),
          code == 0 and "degraded" in text
          and M.EVIDENCE_LABEL in text and "outside the git root" in text
          and _read(os.path.join(away_clone, SHARD_REL)) is not None)
    check("cas16 ...and the directory sitting at `docs/audit/evidence` was NOT "
          "carried instead - it is not this manifest's evidence: %r"
          % (_carried(away, away_head),),
          _read(os.path.join(away_clone, EVIDENCE_REL)) is None)

    listed = repos.make(leave_dirty=True)
    manifest = _mio.load_manifest(listed["manifest"])
    phase = _invariants.phase_of(manifest, PHASE)
    targets = M.state_targets(phase, listed["manifest"], listed["root"],
                              listed["root"])
    check("cas17 the allow-list is the safety property, asserted as a LIST: "
          "the phase's shard and the evidence directory are on it, the task's "
          "files are not, and the index is not on it before `state_index` "
          "decides what of it rides: %r" % (targets["paths"],),
          SHARD_REL in targets["paths"]
          and "docs/audit/evidence" in targets["paths"]
          and INDEX_REL not in targets["paths"]
          and OWNED not in targets["paths"]
          and all(not _invariants._under(OWNED, rel)
                  for rel in targets["paths"]))
    single_path = os.path.join(listed["audit"], "single.json")
    single = _mio.load_manifest(listed["manifest"])
    for stub in single["phases"]:
        stub.pop("shard", None)
    TI._write_json(single_path, single)
    flat = M.state_targets(_invariants.phase_of(single, PHASE), single_path,
                           listed["root"], listed["root"])
    check("cas18 ...and under the SINGLE-FILE layout the one manifest is what "
          "gets staged, because there the index is the phase's file: %r"
          % (flat["paths"],),
          "docs/audit/single.json" in flat["paths"]
          and SHARD_REL not in flat["paths"] and OWNED not in flat["paths"])
    with_trail = M.state_targets(
        _invariants.phase_of(_mio.load_manifest(fx["manifest"]), PHASE),
        fx["manifest"], fx["root"], fx["root"])
    check("cas19 the journal is on the list once it exists, and a journal that "
          "does not exist yet is NOT reported as skipped while the journal is "
          "on: %r / %r" % (with_trail["paths"], targets["skipped"]),
          "docs/audit/journal" in with_trail["paths"]
          and "docs/audit/journal" not in targets["paths"]
          and not any(M.JOURNAL_LABEL in line for line in targets["skipped"]))

    nowhere = os.path.dirname(listed["root"])
    code, answer = M.commit_state(manifest, phase, listed["manifest"],
                                  listed["root"], nowhere)
    check("cas21 pointed at a directory git will not describe, it refuses and "
          "says so - it does not read 'no foreign paths' out of an answer it "
          "never got: %r" % (answer["refused"],),
          code == 1 and answer["refused"] and not answer["committed"]
          and answer["quiet"] == "")

    graded = _invariants.check_phase(
        _mio.load_manifest(fx["manifest"]), PHASE, fx["manifest"],
        fx["root"], fx["root"])
    state = [c for c in graded["checks"] if c["name"] == "audit-state-scope"][0]
    check("cas22 the commit `--state` made is graded CLEAN by the check that "
          "did not make it, `examined` asserted so a reader that stopped "
          "finding the row could not pass this: %r" % (state["verdict"],),
          state["verdict"] == _invariants.CLEAN and state["examined"] == 1
          and state["breaches"] == [], state["gaps"])

    code, _text = _state(fx, "--nope")
    check("cas23 an unknown flag is a usage error (exit 2) and not a failure "
          "to commit (exit 1)", code == 2)
    missing, said = _state_main([fx["manifest"], "P404", "--state", "--project",
                                 fx["root"]])
    unreadable, said2 = _state_main([os.path.join(fx["root"], "no-such.json"),
                                     PHASE, "--state", "--project", fx["root"]])
    overriding, said3 = _state_main([fx["manifest"], PHASE, "--state",
                                     "--override-verdict", "why", "--project",
                                     fx["root"]])
    check("cas24 ...and so are a phase id that is not there, a manifest that "
          "will not load, and an override given to a commit that has no "
          "verdict - each exit 2 with nothing printed: %r"
          % ((missing, unreadable, overriding),),
          (missing, unreadable, overriding) == (2, 2, 2)
          and said == said2 == said3 == [])

    code, text = _state(quiet, "--json")
    payload = json.loads(text)
    check("cas25 --json prints the whole answer for a DO-NOTHING outcome too: "
          "%r" % (sorted(payload),),
          code == 0 and payload["committed"] is False
          and payload["quiet"] == M.STATE_NOTHING_UNCOMMITTED
          and payload["commit"] is None)

    row_target = _state_rows(fx)[0].get("target")
    check("cas26 the row's target is the EVIDENCE directory and deliberately "
          "not the phase's manifest file, which `_recorded_states` reads as a "
          "write: %r" % (row_target,),
          row_target == _journal_io.repo_relative_or_token(
              fx["root"], _evidence_io.evidence_dir(fx["root"]))
          and row_target != SHARD_REL)

    fresh = repos.make(leave_dirty=True)
    _exhaust(fresh)
    code, text = _state(fresh)
    nonce = _trailer_of(fresh, _head(fresh))
    check("cas27 the run that commits says the row naming the commit is INSIDE "
          "it and by which trailer, and the working tree agrees: %r" % (text,),
          code == 0 and len(nonce) == 1
          and _scoped_commit.ROW_CARRIED % (_invariants.ROW_TRAILER,
                                            nonce[0]) in text
          and [ln for ln in _porcelain(fresh)
               if "docs/audit/journal" in ln] == [])
    _journal_io.append(fresh["root"], {
        "action": "task.note", "actor": {"via": "fixture"},
        "target": "P1.2", "summary": "a row another writer left",
        "details": {"taskId": "P1.2", "phaseId": PHASE}})
    was = _head(fresh)
    code, text = _state(fresh)
    now = _head(fresh)
    again_code, again = _state(fresh)
    check("cas28 a journal holding only another writer's row is committed, and "
          "a second run finds nothing uncommitted: %r / %r" % (text, again),
          code == 0 and now != was and again_code == 0
          and _head(fresh) == now and M.STATE_NOTHING_UNCOMMITTED in again)

    silent = repos.make(leave_dirty=True, journal_off=True)
    _exhaust(silent)
    before_silent = _head(silent)
    code, text = _state(silent)
    check("cas29 ...and when NO row was written the commit says the trail "
          "could not be written, and claims no row and no trailer: %r"
          % (text,),
          code == 0 and _head(silent) != before_silent
          and _state_rows(silent) == []
          and _scoped_commit.ROW_NOT_WRITTEN in text
          and _invariants.ROW_TRAILER not in text
          and _trailer_of(silent, _head(silent)) == [])


@_own_repos
def _state_staging_cases(check, repos):
    """The shared staging driven through `--state`: a rename from outside the
    list, a commit a hook refuses after staging, an ignored record directory;
    and a phase ending clean after a task commit and a state commit."""
    fx = repos.make(leave_dirty=True)
    _exhaust(fx)
    TI._git(fx["root"], "mv", SIBLING, "docs/audit/evidence/moved.jsonl")
    before = _head(fx)
    code, text = _state(fx)
    check("cas30 a staged rename from OUTSIDE the allow-list into it is refused "
          "and its SOURCE named: %r / %r" % (code, text),
          code == 1 and SIBLING in text and _head(fx) == before)

    fx = repos.make(leave_dirty=True)
    _exhaust(fx)
    _hook(fx, "pre-commit", "exit 1")
    found = TI._git(fx["root"], "ls-files", "-s")
    before = _head(fx)
    code, text = _state(fx)
    check("cas31 a commit refused AFTER staging leaves the index exactly as it "
          "was found and says so: %r / %r" % (code, text),
          code == 1 and _head(fx) == before
          and TI._git(fx["root"], "ls-files", "-s") == found
          and _scoped_commit.INDEX_RESTORED in text)
    claimed = [(r.get("details") or {}).get(_invariants.NONCE_KEY)
               for r in _state_rows(fx)]
    withdrawn = _invariants.withdrawn_nonces(_journal_io.read_all(fx["root"]))
    graded = _invariants.check_phase(
        _mio.load_manifest(fx["manifest"]), PHASE, fx["manifest"], fx["root"],
        fx["root"])
    state = [c for c in graded["checks"] if c["name"] == "audit-state-scope"][0]
    check("cas36 ...and the row written for that commit before it was refused "
          "is WITHDRAWN by a row naming its nonce, and the reader grades "
          "nothing: %r / %r / %r" % (claimed, sorted(withdrawn),
                                     state["verdict"]),
          len(claimed) == 1 and claimed[0] in withdrawn
          and _scoped_commit.ROW_WITHDRAWN % (claimed[0],) in text
          and state["verdict"] == _invariants.NA and state["gaps"] == [])

    fx = repos.make(leave_dirty=True)
    _exhaust(fx)
    root = fx["root"]
    TI._git(root, "add", "-f", "--", EVIDENCE_REL)
    TI._git(root, "commit", "-q", "-m", "fixture: the evidence, tracked",
            "--", EVIDENCE_REL)
    _write(os.path.join(root, ".gitignore"), "docs/audit/evidence\n")
    TI._git(root, "add", "--", ".gitignore")
    TI._git(root, "commit", "-q", "-m", "fixture: ignore the evidence", "--",
            ".gitignore")
    with io.open(os.path.join(root, EVIDENCE_REL), "a", encoding="utf-8") as fh:
        fh.write('{"v":1,"runId":"another"}\n')
    before = _head(fx)
    code, text = _state(fx)
    after = _head(fx)
    check("cas33 a record DIRECTORY git ignores as a whole, holding a tracked "
          "edited file, is committed with it: %r / %r" % (code, text),
          code == 0 and after != before
          and EVIDENCE_REL in _carried(fx, after))

    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    code_task, _text_task = _run(fx)
    _exhaust(fx)
    code, text = _state(fx)
    head = _head(fx)
    check("cas34 after a task commit and then a state commit the journal row "
          "naming the LAST commit is not left in the working tree: task %r / "
          "state %r / %r" % (code_task, code, text),
          code_task == 0 and code == 0
          and [ln for ln in _porcelain(fx) if "docs/audit/journal" in ln] == [])
    nonces = _trailer_of(fx, head)
    clone = _clone_at(fx, head, repos.scratch("clean-end"))
    in_clone = [r for r in _journal_io.read_all(clone)
                if r.get("action") == _invariants.ACTION_STATE_COMMITTED]
    check("cas35 ...and the row is IN that commit, read from a fresh clone, "
          "keyed by the one nonce the commit's trailer carries: %r / %r"
          % (nonces, [(r.get("details") or {}) for r in in_clone]),
          len(nonces) == 1 and len(in_clone) == 1
          and (in_clone[0].get("details") or {}).get("commitNonce") == nonces[0]
          and "commit" not in (in_clone[0].get("details") or {}))


def _set_session(value):
    """Name the session the command-line writers read, or take the name away;
    returns what was there, for the restore - the suite runs inside a real
    session and would otherwise leave later cases writing under a fixture's
    session id."""
    held = os.environ.get(_journal_io.ENV_SESSION_VAR)
    if value is None:
        os.environ.pop(_journal_io.ENV_SESSION_VAR, None)
    else:
        os.environ[_journal_io.ENV_SESSION_VAR] = value
    return held


def _writers(fx, config):
    """The writer id each journal file's NAME carries - the file name is the
    claim, since where a row landed is what splits a session's trail."""
    directory = _journal_io.journal_dir(fx["root"], config)
    return sorted(set(_journal_io.writer_of(os.path.basename(path))
                      for path in _journal_io.journal_files(directory)))


def _structural_edit(fx, tid="P1.2", path="src/widened.py"):
    """What `/audit:task scope` leaves for an existing task: its file on the
    shard and the fileIndex row on the index, neither committed."""
    index = _mio.read_json(fx["manifest"])
    index["fileIndex"][path] = [tid]
    TI._write_json(fx["manifest"], index)
    shard = _mio.read_json(fx["shard"])
    task = [t for t in shard["tasks"] if t["id"] == tid][0]
    task["files"] = list(task["files"]) + [path]
    TI._write_json(fx["shard"], shard)


@_own_repos
def _state_index_cases(check, repos):
    """Which index a state commit carries: the whole working file when the plan
    it records validates, else only what this phase's shard needs, the rest
    named and left; the session the row is filed under; the history the
    retired index class left behind."""
    fx = repos.make()
    _structural_edit(fx)
    before = _head(fx)
    code, text = _state(fx)
    after = _head(fx)
    carried = _carried(fx, after) if after != before else []
    findings, committed = (_validates_at(fx, after, repos.scratch("ix-whole"))
                           if after != before else (["no commit"], {}))
    check("st-ix1 a structural edit - a fileIndex row and the shard declaring "
          "it - is committed by one state commit carrying the index beside the "
          "shard, the pair validating on a fresh clone with the row in it: %r"
          % ((code, carried, findings[:2]),),
          code == 0 and INDEX_REL in carried and SHARD_REL in carried
          and findings == [] and "src/widened.py" in (
              committed.get("fileIndex") or {})
          and _staged(fx) == [] and INDEX_REL not in "\n".join(_porcelain(fx)))

    # ANOTHER PHASE'S SHARD, UNCOMMITTED, NAMED BY THE INDEX.
    fx = repos.make()
    p2 = os.path.join(os.path.dirname(fx["shard"]), "P2.json")
    other = _mio.read_json(p2)
    other["tasks"].append(dict(other["tasks"][0], id="P2.2", status="pending",
                               files=["src/p22.py"]))
    TI._write_json(p2, other)
    index = _mio.read_json(fx["manifest"])
    index["fileIndex"]["src/p22.py"] = ["P2.2"]
    TI._write_json(fx["manifest"], index)
    before = _head(fx)
    code, text = _state(fx)
    after = _head(fx)
    check("st-ix2 an index naming a task another phase's UNCOMMITTED shard "
          "holds is left out of this phase's state commit - committed, it "
          "would record a plan that does not validate - and the output names "
          "the task and the shard to commit first, while the rest commits: %r"
          % ((code, text[-500:]),),
          code == 0 and after != before
          and INDEX_REL not in _carried(fx, after)
          and "P2.2" in text and "docs/audit/phases/P2.json" in text)
    scode, stext = _state_main([fx["manifest"], "P2", "--state", "--project",
                                fx["root"]])
    p2_head = _head(fx)
    check("st-ix3 SECOND DIRECTION: the state commit of the phase that holds it "
          "carries its shard and the whole index together: %r"
          % ((scode, stext[-3:]),),
          scode == 0 and p2_head != after
          and INDEX_REL in _carried(fx, p2_head)
          and "docs/audit/phases/P2.json" in _carried(fx, p2_head))

    # A NEW PHASE'S STUB, ITS SHARD NOT COMMITTED.
    fx = repos.make()
    index = _mio.read_json(fx["manifest"])
    index["phases"].append({"id": "P3", "title": "new phase",
                            "shard": "phases/P3.json"})
    TI._write_json(fx["manifest"], index)
    TI._write_json(os.path.join(os.path.dirname(fx["shard"]), "P3.json"),
                   {"id": "P3", "title": "new phase", "status": "pending",
                    "tasks": []})
    code, text = _state(fx)
    check("st-ix4 ...and so is a new phase's stub whose shard is not "
          "committed, named with that shard: %r" % ((code, text[-400:]),),
          code == 0 and INDEX_REL not in _carried(fx, _head(fx))
          and "P3" in text and "phases/P3.json" in text)
    scode, _stext = _state_main([fx["manifest"], "P3", "--state", "--project",
                                 fx["root"]])
    p3 = _carried(fx, _head(fx))
    check("st-ix5 ...and the new phase's own state commit carries its shard and "
          "its stub together: %r" % ((scode, p3),),
          scode == 0 and INDEX_REL in p3 and "docs/audit/phases/P3.json" in p3)

    # A ROW NAMING A TASK NO SHARD HOLDS IS DANGLING, NOT AHEAD.
    fx = repos.make()
    index = _mio.read_json(fx["manifest"])
    index["fileIndex"]["src/orphan.py"] = ["P9.9"]
    index["meta"]["title"] = "only the title moved"
    TI._write_json(fx["manifest"], index)
    shows = []
    real_git = _scoped_commit.run_git

    def counting(root, argv, *rest, **kw):
        if argv[:1] == ["show"]:
            shows.append(argv)
        return real_git(root, argv, *rest, **kw)
    _scoped_commit.run_git = counting
    try:
        code, text = _state(fx)
    finally:
        _scoped_commit.run_git = real_git
    check("st-ix6 git is asked to show a shard at HEAD only where that shard "
          "CHANGED and is not the one this commit carries - so P2's committed "
          "copy is never read: the cost is the change's, not the plan's: %r"
          % (shows,),
          code == 0 and not any("P2.json" in " ".join(a) for a in shows))
    check("st-ix7 ...and an index naming a task NO shard holds is not ahead of "
          "a shard - it is dangling, the validator's to report - so the index "
          "is carried whole: %r" % (text[-300:],),
          code == 0 and INDEX_REL in _carried(fx, _head(fx))
          and "P9.9" not in text)

    # THE SESSION THE ROW IS FILED UNDER.
    joined = repos.make()
    _structural_edit(joined)
    sid = "5cf0d3a2-1111-4c2b-9a77-9f0c1b2d3e4f"
    held = _set_session(sid)
    try:
        joined_code, _joined = _state(joined)
        joined_cfg = _journal_io.load_config(joined["root"])
        _journal_io.append_from_cli(joined["root"], {
            "action": "task.add",
            "actor": {"author": None, "sessionId": sid, "via": "cli"},
            "target": INDEX_REL, "summary": "a structural edit by the other "
            "command-line writer of this same session",
            "details": {"phaseId": PHASE}}, config=joined_cfg)
        joined_writers = _writers(joined, joined_cfg)
        joined_rows = _journal_io.read_all(joined["root"])
    finally:
        _set_session(held)
    check("st-ix8 a state commit and a structural edit made by the same "
          "session land in the SAME journal file, named for that session, and "
          "each row records it: %r / %r"
          % (joined_writers,
             [r.get("actor", {}).get("sessionId") for r in joined_rows]),
          joined_code == 0
          and joined_writers == [_journal_io.writer_id({"sessionId": sid})]
          and [r.get("actor", {}).get("sessionId") for r in joined_rows]
          == [sid, sid])
    lone = repos.make()
    _structural_edit(lone)
    held = _set_session(None)
    try:
        lone_code, _lone = _state(lone)
        lone_cfg = _journal_io.load_config(lone["root"])
        lone_writers = _writers(lone, lone_cfg)
        lone_token = _journal_io.writer_token(lone["root"], lone_cfg)
    finally:
        _set_session(held)
    check("st-ix9 ...and with no session named the row lands in the file named "
          "for the CHECKOUT's writer token: %r / %r" % (lone_writers,
                                                       lone_token),
          lone_code == 0 and bool(lone_token) and lone_writers == [lone_token])

    # THE HISTORY A RETIRED CLASS LEFT: index commits stay readable.
    old = repos.make()
    _structural_edit(old)
    TI._nonce_row(old["root"], _invariants.ACTION_INDEX_COMMITTED,
                  "0d0d000000000001", INDEX_REL)
    carrier = TI._commit_carrying(
        old["root"], [INDEX_REL, "docs/audit/journal"],
        "chore(audit-index): phase P1 - the shared index, carried alone so no "
        "phase's work rides with it", "0d0d000000000001")
    read = _invariants.index_commits(old["root"], PHASE, git_root=old["root"])
    graded = [c for c in _invariants.check_phase(
        _mio.load_manifest(old["manifest"]), PHASE, old["manifest"],
        old["root"], old["root"])["checks"] if c["name"] == "index-scope"][0]
    check("st-ix10 a manifest-index commit history holds - no writer makes the "
          "class any more - still resolves from its row and is graded clean "
          "by index-scope through the header those commits were written "
          "with: %r / %r / examined %r"
          % (read[0], graded["verdict"], graded["examined"]),
          read[0] == [carrier] and graded["verdict"] == _invariants.CLEAN
          and graded["examined"] == 1
          and _invariants.INDEX_HEADER == "chore(audit-index): ")

    # THE WORKING INDEX LACKS A ROW THE SHARD DECLARES.
    fx = repos.make(leave_dirty=True)
    _exhaust(fx)
    shard = _mio.read_json(fx["shard"])
    shard["tasks"][1]["files"] = list(shard["tasks"][1]["files"]) + [WIDENED]
    TI._write_json(fx["shard"], shard)
    before = _head(fx)
    code, text = _state(fx)
    _jcode, jtext = _state(fx, "--json")
    rows = json.loads(jtext).get("indexRows") if jtext.startswith("{") else None
    check("cas61 a shard declaring a file neither index has a row for is "
          "refused naming the row and `reindex`, HEAD unmoved and nothing "
          "staged: %r / %r" % ((code, text[-300:]), rows),
          code == 1 and "%s (P1.2)" % (WIDENED,) in text
          and "reindex" in text and _head(fx) == before and _staged(fx) == []
          and rows == [[WIDENED, "P1.2"]])
    # THE SECOND DIRECTION: a guard that fired unconditionally would refuse
    # every state commit, and only a shard owing nothing can show it.
    clean = repos.make(leave_dirty=True)
    _exhaust(clean)
    was = _head(clean)
    code, text = _state(clean)
    check("cas62 ...and a shard owing nothing commits with no refusal and no "
          "remedy named: %r" % ((code, text[-300:]),),
          code == 0 and _head(clean) != was and "reindex" not in text)


def _as_state_command(fx, *extra):
    """`(exitCode, stdout)` of `--state` run as the command `/audit:resume`
    runs on every resume - through `__main__`, where the one-line success
    output is wired and an in-process `main()` never reaches."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    done = subprocess.run([sys.executable, _loader.script_path(
        "commit-task-work.py"), fx["manifest"], PHASE, "--state", "--project",
        fx["root"]] + list(extra), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=120)
    return done.returncode, done.stdout.decode("utf-8", "replace")


@_own_repos
def _state_terse_cases(check, repos):
    """The main loop reads this verb's stdout on every resume, so a state
    commit is one line naming the commit; whatever the caller must still act
    on keeps the long form."""
    fx = repos.make(leave_dirty=True)
    _exhaust(fx)
    code, out = _as_state_command(fx)
    lines = out.splitlines()
    check("cas50 a state commit run as a command prints ONE line, carrying the "
          "SHA it made and how many paths it holds: %r" % (out,),
          code == 0 and len(lines) == 1 and _head(fx)[:12] in lines[0]
          and "path(s)" in lines[0]
          and _scoped_commit.ROW_CARRIED.split("%")[0] not in out)
    verbose = repos.make(leave_dirty=True)
    _exhaust(verbose)
    vcode, vout = _as_state_command(verbose, "--verbose")
    check("cas51 ...and `--verbose` prints the long form - the path list and "
          "the sentence saying the row is inside the commit: %r" % (vout,),
          vcode == 0 and len(vout.splitlines()) > 2
          and _head(verbose)[:12] in vout
          and _scoped_commit.ROW_CARRIED.split("%")[0] in vout)
    away = repos.make(evidence_outside=True)
    TI._evidence_file(away["audit"], "failed")
    acode, aout = _as_state_command(away)
    check("cas52 THE OVER-FIRE TWIN: a commit made past a degraded record keeps "
          "every line, the `degraded:` one first: %r" % (aout,),
          acode == 0 and "degraded:" in aout and len(aout.splitlines()) > 1
          and _head(away)[:12] in aout)
    quiet = repos.make()
    TI._evidence_file(quiet["audit"], "passed")
    TI._git(quiet["root"], "add", "-A")
    TI._git(quiet["root"], "commit", "-q", "-m", "chore: settle the records")
    qcode, qout = _as_state_command(quiet)
    check("cas53 nothing to commit is one line too, still saying that nothing "
          "was committed: %r" % (qout,),
          qcode == 0 and len(qout.splitlines()) == 1
          and "nothing uncommitted" in qout)


# --- the index lock, and the shard committed from the bytes its index came from
# The state commit writes the shared index, so it holds the index lock for the
# whole of the commit, as every other writer of the index does; and either
# commit stages the shard from the very read its index part was derived from,
# so a shard written between that read and the staging can only be left
# uncommitted, never committed without its rows.


def _index_claim_path(fx):
    return os.path.join(_locks.lock_dir(fx["root"]),
                        _panel_write.LOCK_NAME + ".lock")


def _plant_index_claim(fx, pid):
    """Another run's claim on the index lock, in the shape `_locks` writes for
    a process's own write: a token this process does not carry, a pid that is
    not this one, this host. Nobody but that run re-enters it."""
    path = _index_claim_path(fx)
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    _locks._write_lock(path, {
        "sessionId": "another-run", "pid": pid, "hostname": platform.node(),
        "note": "a structural write", "token": "t-another-run",
        "handedOff": False,
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return path


def _gone_pid():
    """The pid of a process that has already exited - a holder judged dead."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def _racing_add(fx, seen):
    """A stand-in for `_scoped_commit.stage` that, on its first call, runs the
    real `/audit:task add` into the running phase - a shard and index write
    landing after the commit decided what to carry and before it staged - and
    records what the index lock said at that moment; then stages as the real
    one does. `seen` collects `(addExit, claimHolderPid)` once."""
    real = M._scoped_commit.stage

    def racing(git_root, paths, kinds):
        if not seen:
            claim = _locks.read_lock(_index_claim_path(fx))
            acode, _added = _add_task(fx, path=CONCURRENT)
            seen.append((acode, (claim or {}).get("pid")))
        return real(git_root, paths, kinds)
    return real, racing


CONCURRENT = "src/concurrent.py"


def _added_ids(doc):
    return [t.get("id") for t in (doc or {}).get("tasks") or []
            if CONCURRENT in (t.get("files") or [])]


@_own_repos
def _index_lock_cases(check, repos):
    """The state commit takes the index lock in a sharded plan and answers a
    holder with the lock's own codes; a shard write landing mid-commit, on the
    state commit and the task commit alike, never splits the shard from its
    index rows at HEAD."""
    # A LIVE HOLDER. Another run is writing the index right now.
    fx = repos.make()
    _structural_edit(fx)
    claim = _plant_index_claim(fx, os.getppid())
    before = _head(fx)
    code, text = _state(fx)
    held = _locks.read_lock(claim) or {}
    check("lk1 RED-FIRST: a sharded plan whose index lock another LIVE run "
          "holds - the state commit exits with the lock's live-holder code, "
          "HEAD unmoved, nothing staged, and the holder's claim untouched: %r"
          % ((code, text[-300:], held.get("token")),),
          code == _locks.E_LIVE and _head(fx) == before and _staged(fx) == []
          and held.get("token") == "t-another-run")
    os.unlink(claim)

    # A DEAD HOLDER: refused as stale until a human says take it over.
    fx = repos.make()
    _structural_edit(fx)
    claim = _plant_index_claim(fx, _gone_pid())
    before = _head(fx)
    code, text = _state(fx)
    check("lk2 RED-FIRST: a holder whose process is gone is refused with the "
          "lock's stale code and the rerun it names, HEAD unmoved and nothing "
          "staged: %r" % ((code, text[-300:]),),
          code == _locks.E_STALE and "--takeover" in text
          and _head(fx) == before and _staged(fx) == []
          and os.path.exists(claim))
    tcode, ttext = _state(fx, "--takeover")
    after = _head(fx)
    findings, _doc = (_validates_at(fx, after, repos.scratch("lk-takeover"))
                      if after != before else (["no commit"], {}))
    check("lk3 ...and `--takeover` takes that claim, commits the structural "
          "edit as a pair validating on a fresh clone, and gives the lock "
          "back: %r" % ((tcode, ttext[-300:], findings[:2]),),
          tcode == 0 and after != before and findings == []
          and not os.path.exists(claim))

    # THE SECOND DIRECTION: a lock that refused with nobody holding it, or that
    # the commit kept after it finished, would block every next writer.
    fx = repos.make()
    _structural_edit(fx)
    before = _head(fx)
    code, text = _state(fx)
    check("lk4 OVER-FIRE TWIN: with no holder the state commit commits and "
          "leaves no claim behind: %r" % ((code, text[-300:]),),
          code == 0 and _head(fx) != before
          and not os.path.exists(_index_claim_path(fx)))

    # A SHARD WRITE LANDING DURING THE STATE COMMIT'S STAGING.
    fx = repos.make()
    _structural_edit(fx)
    seen = []
    real, racing = _racing_add(fx, seen)
    before = _head(fx)
    M._scoped_commit.stage = racing
    try:
        code, text = _state(fx)
    finally:
        M._scoped_commit.stage = real
    after = _head(fx)
    findings, _doc = (_validates_at(fx, after, repos.scratch("lk-state-race"))
                      if after != before else (["no commit"], {}))
    committed = _invariants.json_at(fx["root"], after, SHARD_REL)
    check("lk5 RED-FIRST: the state commit holds the index lock while it "
          "stages - the claim names this process at the moment staging "
          "begins: %r" % (seen,),
          len(seen) == 1 and seen[0][1] == os.getpid())
    check("lk6 RED-FIRST: a `/audit:task add` landing between the state "
          "commit's read and its staging cannot split the pair - HEAD "
          "validates on a fresh clone, the added task is not in the committed "
          "shard and is still in the working one: %r"
          % ((seen, code, findings[:2], text[-200:]),),
          len(seen) == 1 and seen[0][0] == 0 and code == 0 and after != before
          and findings == [] and _added_ids(committed) == []
          and len(_added_ids(_mio.read_json(fx["shard"]))) == 1)

    # THE SAME WINDOW ON A TASK COMMIT, which takes no lock by design: the
    # pair is held together by what is staged, not by who may write.
    fx = repos.make()
    _dirty_work(fx)
    _gate(fx)
    seen = []
    real, racing = _racing_add(fx, seen)
    before = _head(fx)
    M._scoped_commit.stage = racing
    try:
        code, text = _run(fx)
    finally:
        M._scoped_commit.stage = real
    after = _head(fx)
    findings, _doc = (_validates_at(fx, after, repos.scratch("lk-task-race"))
                      if after != before else (["no commit"], {}))
    committed = _invariants.json_at(fx["root"], after, SHARD_REL)
    check("lk7 RED-FIRST: a `/audit:task add` landing between the task "
          "commit's read and its staging cannot split the pair - the commit "
          "lands, HEAD validates on a fresh clone, the added task is not in "
          "the committed shard and is still in the working one: %r"
          % ((seen, code, findings[:2], text[-200:]),),
          len(seen) == 1 and seen[0][0] == 0 and code == 0 and after != before
          and findings == [] and _added_ids(committed) == []
          and len(_added_ids(_mio.read_json(fx["shard"]))) == 1)

    # THE SHARD PINNED TO ITS READ IS STILL WORK TO COMMIT. A state commit's
    # do-nothing answer that skipped every pinned path, as it rightly skips the
    # index `state_index` decides, would read a shard-only change as nothing
    # uncommitted and never carry it.
    fx = repos.make()
    TI._evidence_file(fx["audit"], "passed")
    TI._git(fx["root"], "add", "-A")
    TI._git(fx["root"], "commit", "-q", "-m", "chore: settle the records")
    _exhaust(fx)
    before = _head(fx)
    code, text = _state(fx)
    after = _head(fx)
    committed = _invariants.json_at(fx["root"], after, SHARD_REL) or {}
    check("lk8 a state commit whose only change is the shard - a task blocked "
          "with its attempts spent, no index row moved - commits the shard: %r"
          % ((code, text[-300:]),),
          code == 0 and after != before and SHARD_REL in _carried(fx, after)
          and committed.get("tasks", [{}, {}])[1].get("status") == "blocked")


def _state_json(fx, keep_tokens):
    """`(exitCode, stdout, stderr)` of `--state --json` run as a command, the
    way drive-phase and close-phase run it. `keep_tokens` passes this process's
    lock tokens down, as a child of a run holding the index lock inherits
    them."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE")
               and (keep_tokens or k != _locks.TOKEN_ENV))
    done = subprocess.run([sys.executable, _loader.script_path(
        "commit-task-work.py"), fx["manifest"], PHASE, "--state", "--project",
        fx["root"], "--json"], env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=120)
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _one_object(text):
    """The JSON object `text` is in its entirety, or None - a line ahead of
    the object, or after it, is no answer to a reader that parses stdout."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _unborn(fx):
    """`fx` with its history taken away: a repository on a branch with no
    commit yet, every plan file untracked - the state right after
    `/audit:init` in a fresh repository."""
    _harness.remove_tree(os.path.join(fx["root"], ".git"))
    for argv in (("init", "-q"), ("symbolic-ref", "HEAD", "refs/heads/main"),
                 ("config", "user.email", "fixture@example.com"),
                 ("config", "user.name", "Fixture"),
                 ("config", "commit.gpgsign", "false")):
        TI._git(fx["root"], *argv)
    return fx


@_own_repos
def _lock_json_cases(check, repos):
    """Under `--json` stdout is the one answer object whatever the lock said;
    a state commit lands on an unborn branch; a shard taken out of git by hand
    is not added back by the one-read pairing."""
    # A HOLD RE-ENTERED: the parent run holds the lock, the child inherits its
    # token, and the lock says so - on stderr, never ahead of the object.
    fx = repos.make()
    _structural_edit(fx)
    before = _head(fx)
    said = []
    outer = _panel_write.acquire_index_lock(
        fx["root"], _panel_write.read_config(fx["root"]),
        os.path.abspath(fx["manifest"]), False, said.append, "[outer]",
        "a parent run holding the index")
    try:
        code, stdout, stderr = _state_json(fx, keep_tokens=True)
    finally:
        _panel_write.release_index_lock(outer)
    answer = _one_object(stdout) or {}
    check("lk9 RED-FIRST: a `--state --json` run inside a parent's hold of the "
          "index lock prints ONE JSON object on stdout naming the commit it "
          "made, and the lock's re-entry line goes to stderr: %r"
          % ((isinstance(outer, dict), code, stdout[:200], stderr[:200]),),
          isinstance(outer, dict) and code == 0 and _head(fx) != before
          and answer.get("committed") is True
          and answer.get("commit") == _head(fx)
          and "already yours" in stderr and "already yours" not in stdout)

    # A REFUSAL: the answer is still one object, saying no commit was made.
    fx = repos.make()
    _structural_edit(fx)
    claim = _plant_index_claim(fx, os.getppid())
    before = _head(fx)
    code, stdout, stderr = _state_json(fx, keep_tokens=False)
    os.unlink(claim)
    answer = _one_object(stdout) or {}
    check("lk10 RED-FIRST: a `--state --json` run refused by a live holder "
          "exits with the lock's code and prints ONE JSON object saying "
          "nothing was committed, the lock's own lines on stderr: %r"
          % ((code, stdout[:300], stderr[:200]),),
          code == _locks.E_LIVE and _head(fx) == before
          and answer.get("committed") is False and not answer.get("commit")
          and answer.get("lockCode") == _locks.E_LIVE
          and bool(answer.get("refused")) and "HELD" in stderr)

    # AN UNBORN BRANCH: the shard pinned to its read still commits, as a root.
    fx = _unborn(repos.make())
    with io.open(fx["shard"], "rb") as fh:
        shard_bytes = fh.read()
    code, text = _state(fx)
    made = subprocess.run(["git", "rev-list", "--count", "--all"],
                          cwd=fx["root"], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout.decode().strip()
    shown = subprocess.run(["git", "show", "HEAD:%s" % (SHARD_REL,)],
                           cwd=fx["root"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    check("lk11 a state commit on a branch with no commit yet makes "
          "the root commit, carrying the shard at the bytes it was read as: %r"
          % ((code, made, text[-300:]),),
          code == 0 and made == "1" and shown.returncode == 0
          and shown.stdout == shard_bytes)

    # A SHARD TAKEN OUT OF GIT BY HAND, AND IGNORED, STAYS OUT.
    fx = repos.make()
    TI._git(fx["root"], "rm", "--cached", "-q", "--", SHARD_REL)
    with io.open(os.path.join(fx["root"], ".gitignore"), "a",
                 encoding="utf-8") as fh:
        fh.write(u"\n%s\n" % (SHARD_REL,))
    code, text = _state(fx)
    in_head = TI._git(fx["root"], "ls-tree", "HEAD", "--", SHARD_REL).strip()
    in_index = TI._git(fx["root"], "ls-files", "--", SHARD_REL).strip()
    check("lk12 a shard the user untracked and ignored is committed as the "
          "deletion git holds - not added back from its read - and stays on "
          "disk: %r" % ((code, in_head, in_index, text[-200:]),),
          code == 0 and in_head == "" and in_index == ""
          and os.path.exists(fx["shard"]))


STAGES = (("nm-block", "_no_maintenance_cases"),
          ("fg-block", "_fixture_git_cases"),("or-block", "_ordinary_cases"),("dc-block", "_declared_cases"),
          ("rc-block", "_records_cases"), ("ix-block", "_index_cases"),
          ("dr-block", "_declared_record_cases"),
          ("vd-block", "_verdict_cases"), ("sc-block", "_scope_cases"),
          ("br-block", "_branch_cases"), ("eg-block", "_empty_gate_cases"),
          ("rr-block", "_retired_red_cases"),
          ("gi-block", "_gate_identity_cases"),
          ("ag-block", "_affected_gate_cases"),
          ("kd-block", "_kept_deletion_hook_cases"),
          ("cl-block", "_claims_cases"), ("sl-block", "_success_line_cases"),
          ("dp-block", "_default_project_cases"),
          ("ae-block", "_attempt_cases"),
          ("cs-block", "_clean_at_start_cases"),
          ("bl-block", "_bug_link_cases"),
          ("ir-block", "_index_row_cases"),
          ("ce-block", "_close_evidence_cases"),
          ("ro-block", "_records_only_cases"),
          ("ec-block", "_earlier_commit_cases"),
          ("ov-block", "_one_verb_cases"),
          ("oi-block", "_owned_index_cases"),
          ("st-block", "_state_cases"),
          ("ss-block", "_state_staging_cases"),
          ("si-block", "_state_index_cases"),
          ("tr-block", "_state_terse_cases"),
          ("lk-block", "_index_lock_cases"),
          ("lj-block", "_lock_json_cases"))


if __name__ == "__main__":
    safe_stdio()
    raise SystemExit(_harness.staged_main(sys.argv[1:], STAGES, globals(),
                                          "ctw-stages-"))
