#!/usr/bin/env python3
"""
Cases for `governance/commit-manifest-index.py` — the verb that lands the shared
index without taking a phase's work with it (F269).

WHAT THIS FILE IS ABOUT, in one line: the commit carries the INDEX and nothing
else. Every case that proves it carried the index is paired with one that proves
it left the shard and the source alone, because either half on its own also
passes for a command that committed everything, or for one that committed
nothing. The pairs are asserted against a FRESH CLONE checked out at the commit
wherever the claim is "this is durable" — a clone copies the object database and
the refs and nothing else, so not a byte of the working tree can reach it.

THE FIXTURE IS `test__invariants.build()`, reused for the reason
`test_commit_audit_state.py` reuses it: that suite grades the commits this
command makes, and if the two started from different repositories the grader
would be reading a shape the writer never produces.

WHY THE SINGLE-FILE CASE IS EXIT 0. There the manifest IS the index, so the
ordinary commits already carry it and this route would commit the same bytes
twice — a refusal, and not a failure. A non-zero exit would make every
single-file sign-off read as failed, and a step that reports a healthy project as
broken is a step somebody deletes.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
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

M = _loader.load_script("commit-manifest-index.py", "cmi")

PHASE = "P1"
OWNED = "src/a.py"
SHARD_REL = "docs/audit/phases/P1.json"
INDEX_REL = "docs/audit/audit-plan.json"


# --- fixtures -----------------------------------------------------------------
class Repos(object):
    """A fresh repository per call, torn down at the end.

    NOT `test__invariants`' caching version: every case here MUTATES git - it
    commits - so two cases sharing a repository would be two cases sharing a
    history, and the second one's `HEAD` assertions would be about the first
    one's work.
    """

    def __init__(self):
        self.tmp = _harness.fixture_root("audit-commit-index-")
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


def _widen(fx):
    """What `/audit:task add --files` leaves behind: a `fileIndex` entry on the
    INDEX and the task's own `files` on the SHARD, the second already committed
    by step 4c and the first committable by nothing until now."""
    index = _mio.read_json(fx["manifest"])
    index["fileIndex"]["src/widened.py"] = ["P1.2"]
    TI._write_json(fx["manifest"], index)
    shard = _mio.read_json(fx["shard"])
    shard["tasks"][1]["files"] = list(shard["tasks"][1]["files"]) + \
        ["src/widened.py"]
    TI._write_json(fx["shard"], shard)


def _staged(fx):
    return [ln for ln in TI._git(fx["root"], "diff", "--cached",
                                 "--name-only").splitlines() if ln.strip()]


def _porcelain(fx):
    return [ln for ln in TI._git(fx["root"], "status",
                                 "--porcelain").splitlines() if ln.strip()]


def _carried(fx, sha):
    return [ln.strip() for ln in TI._git(fx["root"], "show", "--name-only",
                                         "--pretty=format:", sha).splitlines()
            if ln.strip()]


def _index_rows(fx):
    return [r for r in _journal_io.read_all(fx["root"])
            if r.get("action") == _invariants.ACTION_INDEX_COMMITTED]


# --- cases --------------------------------------------------------------------
def _cases(check):
    repos = Repos()
    try:
        # --- a widened scope, which is what actually dirties the index --------
        fx = repos.make()
        _widen(fx)
        before = _head(fx)
        code, text = _run(fx)
        after = _head(fx)
        check("cmi1 a `fileIndex` entry written into the shared index by a "
              "structural command is what nothing could commit: this makes one "
              "commit for it and reports its SHA: %r / %r" % (code, text),
              code == 0 and after != before and after[:12] in text)

        check("cmi2 ...and the commit carries the index and NOTHING else - "
              "asserted as the whole file list, not as 'the index is in there', "
              "because a commit that swept in the shard beside it also contains "
              "the index: %r" % (_carried(fx, after),),
              _carried(fx, after) == [INDEX_REL])

        clone = _clone_at(fx, after, repos.scratch("widened"))
        cloned_index = json.loads(_read(os.path.join(clone, INDEX_REL)))
        cloned_shard = json.loads(_read(os.path.join(clone, SHARD_REL)))
        check("cmi3 ...and the pair a clone proves: the entry IS in the committed "
              "index, and the shard's matching `files` widening is NOT - it was "
              "dirty in the same tree and stayed there, which is what keeps this "
              "commit off a parallel phase's path: %r / %r"
              % (sorted(cloned_index["fileIndex"]),
                 cloned_shard["tasks"][1]["files"]),
              "src/widened.py" in cloned_index["fileIndex"]
              and "src/widened.py" not in cloned_shard["tasks"][1]["files"])

        check("cmi4 ...and nothing was left staged for the next `git commit` to "
              "sweep up: the git index is empty and the shard still reports as "
              "modified in the tree: %r / %r" % (_staged(fx), _porcelain(fx)),
              _staged(fx) == []
              and any(ln.endswith(SHARD_REL) and ln[:2].strip()
                      for ln in _porcelain(fx)))

        # --- the trail ---------------------------------------------------------
        rows = _index_rows(fx)
        details = rows[0].get("details") if rows else {}
        check("cmi5 the commit anchors itself with exactly one journal row "
              "carrying the SHA and the phase - the only handle anything has on "
              "such a commit, since it is not a `task.commit` and the manifest "
              "does not name it: %r" % (details,),
              len(rows) == 1 and details.get("commit") == after
              and details.get("phaseId") == PHASE)

        check("cmi6 ...and both keys are on `_journal_io.DETAILS_KEYS`, checked "
              "rather than assumed: the allow-list silently DROPS a key it does "
              "not know, so a row could carry neither and this suite would still "
              "see an `audit.index.committed` action go by",
              "commit" in _journal_io.DETAILS_KEYS
              and "phaseId" in _journal_io.DETAILS_KEYS)

        subject = TI._git(fx["root"], "log", "-1", "--format=%s").strip()
        check("cmi7 the separating literal is a fixed SCOPE and the type is one "
              "conventional-commit tooling accepts. The scope is where nothing a "
              "manifest sets can reach - `meta.commit.type` chooses a task "
              "commit's TYPE and its scope is the phase id - so `git log --grep "
              "%s` tells this class from the other two for ever, and a repo with "
              "husky+commitlint still takes the commit: %r"
              % (M.COMMIT_SCOPE, subject),
              subject.startswith("%s(%s): " % (M.COMMIT_TYPE, M.COMMIT_SCOPE))
              and M.COMMIT_SCOPE not in ("", None, "audit-state")
              and PHASE in subject
              and M.COMMIT_TYPE in ("build", "chore", "ci", "docs", "feat", "fix",
                                    "perf", "refactor", "revert", "style", "test"))

        # --- called again ------------------------------------------------------
        code, text = _run(fx)
        check("cmi8 called again it makes NO commit and SAYS so rather than "
              "exiting quietly - an empty commit records nothing and buries the "
              "ones that do: %r / %r" % (code, _head(fx) == after),
              code == 0 and _head(fx) == after
              and M.NOTHING_UNCOMMITTED in text)

        check("cmi9 ...and it wrote no second journal row either, because there "
              "is nothing to anchor. The pair for cmi5: a row per invocation "
              "would make the trail a record of this command being run rather "
              "than of anything happening: %r" % (len(_index_rows(fx)),),
              len(_index_rows(fx)) == 1)

        # --- the reader agrees with the writer --------------------------------
        graded = _invariants.check_phase(
            _mio.load_manifest(fx["manifest"]), PHASE, fx["manifest"],
            fx["root"], fx["root"])
        scope = [c for c in graded["checks"] if c["name"] == "index-scope"][0]
        check("cmi10 the commit this command made is graded CLEAN by the check "
              "that did not make it - end to end, writer and reader, over one "
              "real repository. `examined` is asserted so a reader that stopped "
              "finding the row could not pass this as clean: %r / %r"
              % (scope["verdict"], scope["examined"]),
              scope["verdict"] == _invariants.CLEAN and scope["examined"] == 1
              and scope["breaches"] == [], scope["gaps"])

        # --- work already in the index ----------------------------------------
        blocked = repos.make(leave_dirty=True)
        _widen(blocked)
        TI._git(blocked["root"], "add", OWNED)
        blocked_head = _head(blocked)
        code, text = _run(blocked)
        check("cmi11 work already staged is REFUSED rather than swept into the "
              "commit: this verb promises to carry one file, and a commit that "
              "also carried somebody's half-finished source would be the failure "
              "the whole split exists to prevent: %r / %r" % (code, text),
              code == 1 and _head(blocked) == blocked_head
              and OWNED in text and "REFUSED" in text)

        check("cmi12 ...and the refusal changed nothing: what somebody else "
              "staged is still staged and the index is NOT, so their git index is "
              "exactly as they left it and there is no half-made state to unpick: "
              "%r" % (_staged(blocked),),
              _staged(blocked) == [OWNED])

        # --- what may be staged, as a list ------------------------------------
        listed = repos.make(leave_dirty=True)
        manifest = _mio.load_manifest(listed["manifest"])
        phase = _invariants.phase_of(manifest, PHASE)
        targets = M.stage_targets(phase, listed["manifest"], listed["root"])
        check("cmi13 the allow-list is the safety property, so it is asserted as "
              "a LIST and not inferred from a commit: it is the index alone, and "
              "the phase's shard and the task's files have no route onto it "
              "however dirty they are: %r" % (targets["paths"],),
              targets["paths"] == [INDEX_REL] and targets["sameFile"] is False
              and SHARD_REL not in targets["paths"]
              and OWNED not in targets["paths"])

        # The other layout, on the same repository. A phase with no `shard` key
        # lives in the manifest itself, and there the index IS the phase's file -
        # which is what `manifest_files` returning one path for both says, and is
        # the test this command uses rather than a filename guess.
        single_path = os.path.join(listed["audit"], "single.json")
        single = _mio.load_manifest(listed["manifest"])
        for stub in single["phases"]:
            stub.pop("shard", None)
        TI._write_json(single_path, single)
        flat = M.stage_targets(_invariants.phase_of(single, PHASE), single_path,
                               listed["root"])
        check("cmi14 ...and under the SINGLE-FILE layout it stages nothing and "
              "says which layout it is in: `manifest_files` returns the identity "
              "pair there, so the ordinary commits already carry the manifest and "
              "this route would commit the same bytes twice. cmi13 is the other "
              "half - only the two together say the identity pair is what "
              "decides: %r" % (flat,),
              flat["sameFile"] is True and flat["paths"] == []
              and flat["skipped"] == [])

        single_head = _head(listed)
        code, text = _run(listed, "--json")
        payload = json.loads(text)
        lines = []
        held = sys.stderr
        sys.stderr = io.StringIO()
        try:
            code_plain = M.main([single_path, PHASE, "--project",
                                 listed["root"]], out=lines.append)
        finally:
            sys.stderr = held
        text_plain = "\n".join(lines)
        check("cmi15 ...and driven END TO END on that manifest it refuses BY "
              "NAME, makes no commit, and still exits 0: a single-file project "
              "has done nothing wrong by calling this, and a non-zero exit would "
              "make every single-file sign-off read as failed. `--json` on the "
              "sharded manifest is the pair, so a machine reader can see a "
              "do-nothing outcome at all: %r / %r"
              % (code_plain, text_plain[-90:]),
              code_plain == 0 and _head(listed) == single_head
              and M.SINGLE_FILE_LAYOUT in text_plain
              and "single-file" in text_plain
              and code == 0 and payload["committed"] is False
              and payload["commit"] is None and payload["quiet"])

        # --- usage -------------------------------------------------------------
        code, _text = _run(fx, "--nope")
        check("cmi16 an unknown flag is a usage error (exit 2) and not a failure "
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
        check("cmi17 ...and so are a phase id that is not there and a manifest "
              "that will not load - neither is a repository this command failed "
              "to write, and both are exit 2: %r / %r" % (missing, unreadable),
              missing == 2 and unreadable == 2 and lines == [])

        # --- where the row points ---------------------------------------------
        row_target = _index_rows(fx)[0].get("target")
        check("cmi18 the row's target is the INDEX, which is what the commit "
              "carried, redacted the way every committed row is - an absolute "
              "path here would write somebody's home directory into a file that "
              "goes to a client: %r" % (row_target,),
              row_target == INDEX_REL and not os.path.isabs(str(row_target)))
    finally:
        repos.close()


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_commit_manifest_index.py --selftest\n")
    raise SystemExit(2)
