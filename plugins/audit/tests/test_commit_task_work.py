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

PHASE = "P1"
TASK = "P1.1"
OWNED = "src/a.py"
SIBLING = "src/b.py"
SHARD_REL = "docs/audit/phases/P1.json"
INDEX_REL = "docs/audit/audit-plan.json"


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


# --- cases --------------------------------------------------------------------
def _cases(check):
    repos = Repos()
    try:
        # --- the ordinary run --------------------------------------------------
        fx = repos.make()
        _dirty_work(fx)
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
    finally:
        repos.close()


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_commit_task_work.py --selftest\n")
    raise SystemExit(2)
