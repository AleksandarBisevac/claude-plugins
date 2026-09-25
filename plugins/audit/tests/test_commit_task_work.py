#!/usr/bin/env python3
"""
Cases for `governance/commit-task-work.py` — the verb that commits ONE task's
work and refuses the rest.

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
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _evidence_io                                # noqa: E402
import _invariants                                 # noqa: E402
import _journal_io                                 # noqa: E402
import _loader                                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402
import test__invariants as TI                      # noqa: E402  (the ONE git fixture)
# commitlint's default `subject-case`, transcribed ONCE and imported: the rule is
# commitlint's and belongs to none of the three writers, so a second
# transcription here is how they would come to be graded against two readings of
# it.
from test_commit_audit_state import HEADER_MAX_LENGTH, header_offences  # noqa: E402

M = _loader.load_script("commit-task-work.py", "ctw")
# THE REAL RECORDER, driven in-process. A verdict the commit is bound to has to be
# one `run-test-gate.py --record` wrote, or these cases would be grading the
# committer against a row shape the recorder never produces.
RTG = _loader.load_script("run-test-gate.py", "rtg_for_ctw")

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
        return TI.build(root, **opts)

    def scratch(self, name):
        return os.path.join(self.tmp, "scratch-%s" % (name,))

    def close(self):
        _harness.remove_tree(self.tmp)


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


def _clone_at(fx, sha, dest):
    """A fresh clone, checked out at `sha`. Returns the clone's path."""
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", fx["root"], dest],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    subprocess.run(["git", "-C", dest, "checkout", "--quiet", sha],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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


def _set_task(fx, files=None, gate=None, phase_gate=None):
    """Rewrite the fixture task's `files` and/or `tests.gate` in its shard, and
    the phase's `testGate` when `phase_gate` is given. Left uncommitted, which is
    what a task that widened its scope mid-run looks like."""
    shard = _mio.read_json(fx["shard"])
    task = [t for t in shard["tasks"] if t.get("id") == TASK][0]
    if files is not None:
        task["files"] = list(files)
    if gate is not None:
        task["tests"]["gate"] = list(gate)
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
def _cases(check):
    repos = Repos()
    try:
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
        check("ctw2 ...and the commit carries the task's declared file and the "
              "phase's manifest file and NOTHING else - asserted as the whole "
              "file list, because a commit that swept the sibling in beside them "
              "also contains both: %r" % (carried,),
              carried == sorted([OWNED, SHARD_REL]))

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
        check("ctw6 the commit anchors itself with exactly one journal row "
              "carrying the SHA, the task and the phase - between this commit "
              "and `/audit:task done` there is otherwise a commit nothing points "
              "at, and a run that dies in the gap leaves one for ever: %r"
              % (details,),
              len(rows) == 1 and details.get("commit") == after
              and details.get("taskId") == TASK
              and details.get("phaseId") == PHASE)
        check("ctw7 ...and all three keys are on `_journal_io.DETAILS_KEYS`, "
              "checked rather than assumed: the allow-list silently DROPS a key "
              "it does not know, so a row could carry none of them and the case "
              "above would still see the action go by",
              all(key in _journal_io.DETAILS_KEYS
                  for key in ("commit", "taskId", "phaseId")),
              repr(sorted(_journal_io.DETAILS_KEYS)))

        # --- the subject a commitlint repository will take ---------------------
        subject = TI._git(fx["root"], "log", "-1", "--format=%s").strip()
        check("ctw8 the scope is the TASK id and the type is the manifest's - "
              "which is what tells this class from its two siblings, whose scope "
              "is a phase id and whose type is a fixed literal: %r" % (subject,),
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
              and "commit-manifest-index" in text)
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
              "commit-manifest-index" not in text, repr(text))

        # --- nothing to do, and the two ways of it -----------------------------
        fx = repos.make()
        # The fixture leaves its last shard write uncommitted, which is what a
        # finished task really looks like - so it is put back here rather than
        # left, because the state under test is a tree with nothing in it for
        # this commit to carry and not a tree that happens to be dirty.
        TI._git(fx["root"], "checkout", "--", SHARD_REL)
        before = _head(fx)
        code, text = _run(fx)
        check("ctw15 a clean tree makes NO commit and says which of the "
              "do-nothing states it was - a stream of empty commits is how a "
              "record stops being read, and exit 0 because a healthy project "
              "reported as broken is a step somebody deletes: %r / %r"
              % (code, text),
              code == 0 and _head(fx) == before
              and "already in git" in text)

        # --- a declared file that is not there ---------------------------------
        fx = repos.make()
        _dirty_work(fx)
        _manifest, _phase, task = _phase_and_task(fx)
        shard = _mio.read_json(fx["shard"])
        shard["tasks"][0]["files"] = [OWNED, "src/not-written-yet.py",
                                      "src/a.py:10-20"]
        TI._write_json(fx["shard"], shard)
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
              _carried(fx, after) == sorted([OWNED, SHARD_REL]))

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
        check("ctw20 ...and a record directory that does not exist yet is "
              "REPORTED as skipped rather than silently dropped: 'it is outside "
              "the repository' and 'it is not there yet' leave the same commit "
              "behind while being different things to know: %r"
              % (targets["skipped"],),
              any(M.JOURNAL_LABEL in line for line in targets["skipped"])
              and any(M.EVIDENCE_LABEL in line for line in targets["skipped"]))

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
        check("ctw22 ...and the journal row this run appended is NOT in it, "
              "because it names the SHA and so could only be written afterwards "
              "- said on the run that creates the condition rather than met by "
              "an operator on the next one",
              not any(p.startswith("docs/audit/journal/")
                      for p in _carried(fx, after))
              or M.PREFIX in text, repr(_carried(fx, after)))

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
        check("ctw26 the conventional TYPE comes from `meta.commit.type` - a "
              "task commit carries implementation, so a project's own convention "
              "is the right one for it, unlike its two siblings whose types are "
              "fixed literals so `git log` can tell those classes apart",
              M.commit_message(TASK, "s", {"meta": {"commit": {"type": "fix"}}})[0]
              .startswith("fix(%s): " % (TASK,)),
              repr(M.commit_message(TASK, "s",
                                    {"meta": {"commit": {"type": "fix"}}})))
        check("ctw27 ...and the fallback is not `feat`: a default that claimed a "
              "feature on work nobody described would be a wrong word written by "
              "a default",
              M.DEFAULT_COMMIT_TYPE != "feat"
              and M.commit_message(TASK, "s", {})[0]
              .startswith("%s(%s): " % (M.DEFAULT_COMMIT_TYPE, TASK)),
              repr(M.commit_message(TASK, "s", {})))
        check("ctw28 the coauthor is its OWN paragraph rather than a second "
              "sentence of the subject line - a list is how it reaches git, one "
              "`-m` each, so the trailer is a trailer",
              M.commit_message(TASK, "s",
                               {"meta": {"commit": {"coauthor": "Co: x"}}})
              == ["chore(%s): %s - s" % (TASK, M.SUBJECT_LEAD), "Co: x"],
              repr(M.commit_message(TASK, "s",
                                    {"meta": {"commit": {"coauthor": "Co: x"}}})))

        # --- the refusal builder, both directions -------------------------------
        check("ctw29 SECOND-DIRECTION CASE: with nothing foreign there is NO "
              "refusal, so the caller's branch reads as a question rather than "
              "as a string test - a builder that always returned a sentence "
              "would refuse every run and pass every refusal case above",
              M.foreign_refusal([], {"indexRel": INDEX_REL}) is None
              and M.foreign_refusal(None, {"indexRel": INDEX_REL}) is None)
        _index_cases(check, repos)
        _verdict_cases(check, repos)
    finally:
        repos.close()


# --- what the index says: renames, deletions, ignored directories -----------
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
          "an override nobody can find afterwards is a gate quietly deleted: "
          "%r / %r" % (details, text),
          code == 0 and after != before and len(rows) == 1
          and details.get("commit") == after
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
          "and the output says the commit is bound to no verdict: the recorder "
          "writes no row for an empty gate, so requiring one would block the "
          "task for ever, and saying nothing would read as a green: %r / %r"
          % (code, text),
          code == 0 and _const('NO_GATE') in text)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_commit_task_work.py --selftest\n")
    raise SystemExit(2)
