#!/usr/bin/env python3
"""
Cases for `governance/commit-audit-state.py` — the verb that makes a failed run's
record durable without committing the run.

WHAT THIS FILE IS ABOUT, in one line: the difference between "it is in the tree"
and "it is in the commit". Every assertion about what was preserved is made
against a FRESH CLONE checked out at the commit, never against the working tree
the command ran in — a clone copies the object database and the refs and nothing
else, so not a byte of that tree can reach it. The two claims are not the same
one, and the whole point of this command is the second.

THE PAIRS, AND WHY EACH HALF EXISTS. The command has exactly one thing it must
never do, so every case that proves it carried the record is paired with one that
proves it left the work alone: the clone still holds the committed baseline of
`src/a.py`, the working tree still holds the failed fix, and the index is empty
afterwards. Any one of those alone passes for a command that committed
everything, or for one that committed nothing.

THE FIXTURE IS `test__invariants.build()`, reused rather than rebuilt. That suite
grades the commits this command makes; if the two started from different
repositories the grader would be reading a shape the writer never produces.
`build()` grew four flags for this file, and they are documented beside it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
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

M = _loader.load_script("commit-audit-state.py", "cas")

PHASE = "P1"
OWNED = "src/a.py"
SHARD_REL = "docs/audit/phases/P1.json"
INDEX_REL = "docs/audit/audit-plan.json"
EVIDENCE_REL = "docs/audit/evidence/" + TI.EVIDENCE_NAME


# --- fixtures -----------------------------------------------------------------
class Repos(object):
    """A fresh repository per call, torn down at the end.

    NOT `test__invariants`' caching version: every case here MUTATES git - it
    commits - so two cases sharing a repository would be two cases sharing a
    history, and the second one's `HEAD` assertions would be about the first
    one's work.
    """

    def __init__(self):
        self.tmp = _harness.fixture_root("audit-commit-state-")
        self.made = 0

    def make(self, **opts):
        self.made += 1
        root = os.path.join(self.tmp, "r%d" % (self.made,), "repo")
        os.makedirs(root)
        return TI.build(root, **opts)

    def scratch(self, name):
        path = os.path.join(self.tmp, "scratch-%s" % (name,))
        return path

    def close(self):
        _harness.remove_tree(self.tmp)


def _run(fx, *extra):
    """`(exitCode, printedText)` for one invocation, stderr swallowed.

    stderr is swallowed rather than left to escape because the usage cases
    deliberately provoke it, and a real ERROR line in the middle of a green suite
    reads to whoever is scrolling the log exactly like a failure.
    """
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main([fx["manifest"], PHASE, "--project", fx["root"]]
                      + list(extra), out=lines.append)
    finally:
        sys.stderr = held
    return code, "\n".join(lines)


def _head(fx):
    return TI._head(fx["root"])


def _clone_at(fx, sha, dest):
    """A fresh clone, checked out at `sha`. Returns the clone's path.

    THE ONLY WAY TO ASSERT WHAT A COMMIT CARRIES. Reading the working tree the
    command ran in cannot tell a file that was committed from one that was merely
    left lying there, which is the exact distinction every case below turns on.
    """
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", fx["root"], dest],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    subprocess.run(["git", "-C", dest, "checkout", "--quiet", sha],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return dest


def _read(path):
    """The file's text, or None when it is not there - the two are different
    findings and a raised IOError would hide which case failed."""
    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (IOError, OSError):
        return None


def _exhaust(fx):
    """Mark P1.2 blocked with its attempts spent, and record why.

    What `orchestrator.md` step 4 leaves behind when the gate stayed red to the
    last retry: the manifest moved, the code did not, and nothing commits.
    """
    shard = _mio.read_json(fx["shard"])
    task = shard["tasks"][1]
    task["status"] = "blocked"
    task["attempts"] = task["maxAttempts"]
    task["outcome"]["technical"] = "the gate stayed red on every attempt"
    TI._write_json(fx["shard"], shard)
    return shard


def _staged(fx):
    return [ln for ln in TI._git(fx["root"], "diff", "--cached",
                                 "--name-only").splitlines() if ln.strip()]


def _porcelain(fx):
    return [ln for ln in TI._git(fx["root"], "status",
                                 "--porcelain").splitlines() if ln.strip()]


def _state_rows(fx):
    return [r for r in _journal_io.read_all(fx["root"])
            if r.get("action") == _invariants.ACTION_STATE_COMMITTED]


# --- cases --------------------------------------------------------------------
def _cases(check):
    repos = Repos()
    try:
        # --- a task that exhausted its attempts -------------------------------
        fx = repos.make(leave_dirty=True)
        _exhaust(fx)
        before = _head(fx)
        code, text = _run(fx)
        after = _head(fx)
        check("cas1 a task that ran out of attempts leaves a red gate's evidence "
              "and a moved manifest with nothing to commit them - this makes one "
              "commit and reports its SHA: %r / %r" % (code, text),
              code == 0 and after != before and after[:12] in text)

        clone = _clone_at(fx, after, repos.scratch("exhausted"))
        carried = _read(os.path.join(clone, EVIDENCE_REL))
        carried_row = json.loads(carried) if carried else {}
        check("cas2 ...and the failure rows are IN THE COMMIT, asserted from a "
              "fresh clone checked out at it rather than from the tree the "
              "command ran in. 'it is in the tree' and 'it is in the commit' are "
              "different claims and only the second one is durable: %r"
              % (carried_row,),
              carried_row.get("status") == "failed"
              and carried_row.get("runId") == TI.FAILED_RUN_ID
              and carried_row.get("taskId") == "P1.2")

        cloned_shard = json.loads(_read(os.path.join(clone, SHARD_REL)))
        check("cas3 ...and so is the manifest state that says why: the committed "
              "shard has P1.2 blocked with its attempts spent, which is the half "
              "of the record that makes the evidence readable: %r"
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

        check("cas5 ...and it was never staged either, so nothing is left behind "
              "for the next `git commit` to sweep up: the index is empty and the "
              "tree still reports the file as modified: %r / %r"
              % (_staged(fx), _porcelain(fx)),
              _staged(fx) == []
              and any(ln.endswith(OWNED) and ln[:2].strip()
                      for ln in _porcelain(fx)))

        # --- the trail ---------------------------------------------------------
        rows = _state_rows(fx)
        details = rows[0].get("details") if rows else {}
        check("cas6 the commit anchors itself with exactly one journal row "
              "carrying the SHA and the phase - the only handle anything has on "
              "such a commit, since it is not a `task.commit` and the manifest "
              "does not name it: %r" % (details,),
              len(rows) == 1 and details.get("commit") == after
              and details.get("phaseId") == PHASE)

        check("cas7 ...and both keys are on `_journal_io.DETAILS_KEYS`, checked "
              "rather than assumed: the allow-list silently DROPS a key it does "
              "not know, so a row could carry neither and this suite would still "
              "see an `audit.state.committed` action go by",
              "commit" in _journal_io.DETAILS_KEYS
              and "phaseId" in _journal_io.DETAILS_KEYS)

        subject = TI._git(fx["root"], "log", "-1", "--format=%s").strip()
        check("cas8 the commit type is a fixed literal and not `meta.commit.type` "
              "- the manifest may set that to anything, so only a literal is a "
              "spelling a task commit can never collide with, and `git log "
              "--grep` can tell the two apart for ever: %r" % (subject,),
              subject.startswith("%s(%s):" % (M.COMMIT_TYPE, PHASE))
              and not subject.startswith("chore(")
              and M.COMMIT_TYPE != "chore")

        # --- called again ------------------------------------------------------
        code, text = _run(fx)
        check("cas9 called again it makes NO commit and says which do-nothing "
              "state it is in: the only thing left uncommitted is the row that "
              "anchored the last commit, and committing that would need a row of "
              "its own and never stop: %r / %r" % (code, _head(fx) == after),
              code == 0 and _head(fx) == after and M.ONLY_THE_TRAIL in text
              and M.NOTHING_UNCOMMITTED not in text)

        # --- a red sign-off gate ----------------------------------------------
        red = repos.make(leave_dirty=True)
        code, _text = _run(red)
        red_head = _head(red)
        red_clone = _clone_at(red, red_head, repos.scratch("red-gate"))
        red_shard = json.loads(_read(os.path.join(red_clone, SHARD_REL)))
        check("cas10 a phase whose sign-off gate went red commits its evidence "
              "while STAYING in_progress - the record moves and the phase does "
              "not, which is the state step 4 leaves and the one nothing else "
              "preserves: %r" % (red_shard["status"],),
              code == 0 and red_shard["status"] == "in_progress"
              and _read(os.path.join(red_clone, EVIDENCE_REL)) is not None)

        # --- nothing uncommitted ----------------------------------------------
        quiet = repos.make()
        TI._git(quiet["root"], "add", SHARD_REL)
        TI._git(quiet["root"], "commit", "-q", "-m", "chore: settle the shard")
        settled = _head(quiet)
        code, text = _run(quiet)
        check("cas11 with nothing uncommitted no commit is made, and it SAYS so "
              "rather than exiting quietly: an empty commit records nothing and "
              "buries the ones that do: %r / %r" % (code, text),
              code == 0 and _head(quiet) == settled
              and M.NOTHING_UNCOMMITTED in text and M.ONLY_THE_TRAIL not in text)

        check("cas12 ...and it wrote no journal row either, because there is "
              "nothing to anchor. The pair for cas6: a row per invocation would "
              "make the trail a record of this command being run rather than of "
              "anything happening: %r" % (_state_rows(quiet),),
              _state_rows(quiet) == [])

        # --- work already in the index ----------------------------------------
        blocked = repos.make(leave_dirty=True)
        TI._git(blocked["root"], "add", OWNED)
        blocked_head = _head(blocked)
        code, text = _run(blocked)
        check("cas13 work already in the index is REFUSED rather than swept into "
              "the commit - the one thing this verb promises never to carry is "
              "sitting there staged, and committing it would be the failure the "
              "whole design exists to prevent: %r / %r" % (code, text),
              code == 1 and _head(blocked) == blocked_head
              and OWNED in text and "REFUSED" in text)

        check("cas14 ...and the refusal changed nothing: the file somebody else "
              "staged is still staged and the evidence is NOT, so the operator's "
              "index is exactly as they left it and there is no half-made state "
              "to unpick: %r" % (_staged(blocked),),
              _staged(blocked) == [OWNED])

        # --- a record outside the repository ----------------------------------
        away = repos.make(evidence_outside=True)
        TI._evidence_file(away["audit"], "failed")
        code, text = _run(away)
        away_head = _head(away)
        away_clone = _clone_at(away, away_head, repos.scratch("outside"))
        check("cas15 an evidence directory outside the git root is degraded past "
              "and NAMED, the sentence step 4c already writes for the journal: "
              "the commit still carries the manifest state, and the line says "
              "which record went missing: %r" % (text,),
              code == 0 and "degraded" in text
              and M.EVIDENCE_LABEL in text and "outside the git root" in text
              and _read(os.path.join(away_clone, SHARD_REL)) is not None)

        check("cas16 ...and the directory sitting at `docs/audit/evidence` was "
              "NOT carried instead. It is not this manifest's evidence - the "
              "config points elsewhere - so a commit that grabbed it would be "
              "preserving somebody else's record and calling it this one's: %r"
              % (TI._git(away["root"], "show", "--name-only",
                         "--pretty=format:", away_head).split(),),
              _read(os.path.join(away_clone, EVIDENCE_REL)) is None)

        # --- what may be staged, as a list ------------------------------------
        listed = repos.make(leave_dirty=True)
        manifest = _mio.load_manifest(listed["manifest"])
        phase = _invariants.phase_of(manifest, PHASE)
        targets = M.stage_targets(manifest, phase, listed["manifest"],
                                  listed["root"], listed["root"])
        check("cas17 the allow-list is the safety property, so it is asserted as "
              "a LIST and not inferred from a commit: the phase's shard and the "
              "evidence directory are on it, the task's files are not, and "
              "nothing downstream can widen it: %r" % (targets["paths"],),
              SHARD_REL in targets["paths"]
              and "docs/audit/evidence" in targets["paths"]
              and INDEX_REL not in targets["paths"]
              and OWNED not in targets["paths"]
              and all(not M._under(OWNED, rel) for rel in targets["paths"]))

        # The other layout, on the same repository. A phase with no `shard` key
        # lives in the manifest itself, and there the index IS the phase's file -
        # so the pair below is what pins `manifest_files` as the thing that
        # decides, rather than a filename this command guessed.
        single_path = os.path.join(listed["audit"], "single.json")
        single = _mio.load_manifest(listed["manifest"])
        for stub in single["phases"]:
            stub.pop("shard", None)
        TI._write_json(single_path, single)
        flat = M.stage_targets(single, _invariants.phase_of(single, PHASE),
                               single_path, listed["root"], listed["root"])
        check("cas18 ...and under the SINGLE-FILE layout the one manifest is what "
              "gets staged, because there the index is the phase's file. cas17 is "
              "the other half: sharded, the index is refused and the shard is "
              "taken, and only the two together say `manifest_files` decides: %r"
              % (flat["paths"],),
              "docs/audit/single.json" in flat["paths"]
              and SHARD_REL not in flat["paths"]
              and OWNED not in flat["paths"])

        # `fx`, not `listed`: its journal directory EXISTS, because the run at
        # the top of this suite created it. Asked of a repository that has no
        # journal yet, both halves below would hold over an empty answer.
        with_trail = M.stage_targets(_mio.load_manifest(fx["manifest"]),
                                     _invariants.phase_of(
                                         _mio.load_manifest(fx["manifest"]),
                                         PHASE),
                                     fx["manifest"], fx["root"], fx["root"])
        check("cas19 the journal is on the list AND named apart on it, "
              "because it is the one entry that may be carried and may not "
              "trigger a commit. cas9 is what the separation buys; this is the "
              "field it rests on: %r" % (with_trail,),
              with_trail["journal"] == "docs/audit/journal"
              and "docs/audit/journal" in with_trail["paths"]
              and targets["journal"] is None)

        # --- git cannot answer -------------------------------------------------
        nowhere = os.path.dirname(listed["root"])
        blind, blind_why = M.foreign_staged(nowhere, ["docs/audit"])
        seen, seen_why = M.foreign_staged(blocked["root"], ["docs/audit"])
        check("cas20 an index git will not describe yields a REASON and never an "
              "empty list, and the pair is over the same function: the real "
              "repository returns the staged path with no reason, the one git "
              "cannot read returns no paths and says why. Read as 'nothing "
              "foreign' the second answer is what lets a staged source file into "
              "the commit: %r / %r" % (blind_why, seen),
              blind == [] and blind_why
              and seen == [OWNED] and seen_why == "")

        code, answer = M.commit_state(manifest, phase, listed["manifest"],
                                      listed["root"], nowhere)
        check("cas21 pointed at a directory git will not describe, it refuses and "
              "says so - it does not read 'no foreign paths' out of an answer it "
              "never got, which is the false clean sheet that would let a staged "
              "source file through: %r" % (answer["refused"],),
              code == 1 and answer["refused"] and not answer["committed"]
              and answer["quiet"] == "")

        # --- the reader agrees with the writer --------------------------------
        graded = _invariants.check_phase(
            _mio.load_manifest(fx["manifest"]), PHASE, fx["manifest"],
            fx["root"], fx["root"])
        state = [c for c in graded["checks"]
                 if c["name"] == "audit-state-scope"][0]
        check("cas22 the commit this command made is graded CLEAN by the check "
              "that did not make it - end to end, writer and reader, over one "
              "real repository. `examined` is asserted so a reader that stopped "
              "finding the row could not pass this as clean: %r"
              % (state["verdict"],),
              state["verdict"] == _invariants.CLEAN and state["examined"] == 1
              and state["breaches"] == [], state["gaps"])

        # --- usage -------------------------------------------------------------
        code, _text = _run(fx, "--nope")
        check("cas23 an unknown flag is a usage error (exit 2) and not a failure "
              "to commit (exit 1) - a caller retrying on 1 would loop for ever on "
              "a typo", code == 2)

        lines = []
        held = sys.stderr
        sys.stderr = io.StringIO()
        try:
            missing = M.main([fx["manifest"], "P404", "--project", fx["root"]],
                             out=lines.append)
            unreadable = M.main([os.path.join(fx["root"], "no-such.json"), PHASE,
                                 "--project", fx["root"]], out=lines.append)
        finally:
            sys.stderr = held
        check("cas24 ...and so are a phase id that is not there and a manifest "
              "that will not load - neither is a repository this command failed "
              "to write, and both are exit 2: %r / %r" % (missing, unreadable),
              missing == 2 and unreadable == 2 and lines == [])

        # --- json --------------------------------------------------------------
        code, text = _run(quiet, "--json")
        payload = json.loads(text)
        check("cas25 --json prints the whole answer for a DO-NOTHING outcome too, "
              "not only for a commit: a machine reader that could see only the "
              "commits could never tell 'nothing to do' from 'the command never "
              "ran': %r" % (sorted(payload),),
              code == 0 and payload["committed"] is False
              and payload["quiet"] == M.NOTHING_UNCOMMITTED
              and payload["commit"] is None)

        # --- where the row points ---------------------------------------------
        row_target = _state_rows(fx)[0].get("target")
        check("cas26 the row's target is the EVIDENCE directory and deliberately "
              "not the phase's manifest file: `_recorded_states` reads every row "
              "naming that file as a WRITE to it, and a commit is not an edit - "
              "pointing it there would manufacture a gap in manifest-revalidated "
              "out of a state that was in fact preserved: %r" % (row_target,),
              row_target == _journal_io.repo_relative_or_token(
                  fx["root"], _evidence_io.evidence_dir(fx["root"]))
              and row_target != SHARD_REL)
    finally:
        repos.close()


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_commit_audit_state.py --selftest\n")
    raise SystemExit(2)
