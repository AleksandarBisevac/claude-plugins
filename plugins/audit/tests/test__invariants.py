#!/usr/bin/env python3
"""
The cases for `_invariants.py` — the post-hoc reader of the orchestrator's rules.

Every case here runs against a REAL git repository built in a temp directory, not
against a fake `git` that returns what the assertion wants. That is deliberate and
it is the whole reason this file is long: the module's claims are claims about what
git records, and a fake would encode the assumption rather than the behaviour. The
fixtures build a phase branch, commit two tasks the way `orchestrator.md` step 4c
says to, and then break exactly one thing per case.

WHAT EACH CASE HAD TO PROVE, and why the pairs exist. A check that has only been
seen green may be asserting nothing, so every rule is exercised in BOTH directions:
the clean fixture must say `clean` and the broken one must say `breach`, and the
breach cases COUNT what was found instead of asserting a substring is present —
"there is a line mentioning rogue.py" also passes when every file in the commit was
reported.

THE THIRD DIRECTION IS THE ONE THIS MODULE EXISTS FOR. `clean` and `breach` are not
the only two answers: a deleted branch reflog, an unmetered repository and a
manifest state no commit preserved each produce `no-basis` or `partial`, and a check
that folded those into `clean` would be the exact failure the README's enforcement
table was written to stop. Those cases are here too, and they assert the verdict is
NOT `clean` rather than only that a gap line exists.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import json
import os
import shutil
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _invariants as M                            # noqa: E402
import _journal_io                                 # noqa: E402
import _manifest_io as _mio                        # noqa: E402

BRANCH = "audit/p1-demo"
PARENT = "main"

INDEX = {
    "meta": {"version": 3, "repo": "fixture", "title": "fixture",
             "createdISO": "2026-01-01T00:00:00Z", "developmentBranch": PARENT,
             "branchPrefix": "audit", "gitRoot": ".", "reviewSkill": None,
             "runtimeBoot": None, "nodePreamble": None,
             "commit": {"type": "chore", "coauthor": None},
             "buildCommands": {"test": "true"}},
    "phases": [{"id": "P1", "title": "one", "shard": "phases/P1.json",
                "status": "pending"},
               {"id": "P2", "title": "two", "shard": "phases/P2.json",
                "status": "pending"}],
    # P2's file is here too. It is not decoration: without it EVERY committed
    # state is invalid, `manifest-revalidated` reports a breach on the clean
    # fixture, and the case that proves an INVALID state is caught would have been
    # passing on the fixture's own defect rather than on the thing it broke.
    "fileIndex": {"src/a.py": ["P1.1"], "src/b.py": ["P1.2"],
                  "src/c.py": ["P2.1"]},
    "deferred": {"note": "none", "target": None, "items": []},
    "proposals": [],
    "bugs": [],
}


def _task(tid, name, risk="low"):
    return {"id": tid, "title": tid, "status": "pending", "model": "sonnet",
            "skills": [], "blockedBy": [], "dependsOn": [], "files": [name],
            "docs": [], "description": "d",
            "tests": {"mode": "gate-only", "add": [], "expectRedFirst": False,
                      "gate": ["test"]},
            "outcome": {"technical": None, "descriptive": None},
            "commit": None, "attempts": 0, "maxAttempts": 3,
            "startedAt": None, "completedAt": None, "risk": risk,
            "verifiedBy": []}


def _phase(pid, tasks):
    return {"id": pid, "title": pid, "status": "pending", "model": "sonnet",
            "blockedBy": [], "desiredOutcome": "d", "testGate": ["test"],
            "baseRef": None, "branch": None, "mergedAt": None,
            "review": {"tool": None, "model": "sonnet", "status": "pending",
                       "findings": []},
            "summary": None, "tasks": tasks}


# --- fixtures -----------------------------------------------------------------
def _git(cwd, *args):
    """git, or the reason it failed — a fixture that half-built is not a fixture."""
    done = subprocess.run(["git"] + list(args), cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode != 0:
        raise RuntimeError("git %s failed in %s: %s"
                           % (" ".join(args), cwd,
                              done.stdout.decode("utf-8", "replace")[:300]))
    return done.stdout.decode("utf-8", "replace")


def _head(cwd, ref="HEAD"):
    return _git(cwd, "rev-parse", ref).strip()


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def build(root, rogue=False, index_in_task=False, haiku=False, bad_base=False,
          stash=False, push=False, invalid_state=False, no_base_ref=False,
          drop_branch=False, forced=False, journal_rows=0, parent_branch=None,
          journal_in_commit=False, journal_real=False,
          evidence_in_commit=False, evidence_near_miss=False):
    """A repo with one finished phase, broken in exactly the way the flags say.

    ONE BUILDER RATHER THAN ONE PER CASE, because the clean path has to be the
    same clean path every broken case starts from. A per-case fixture drifts, and
    then a `breach` case is passing because its fixture differs somewhere nobody
    is comparing.
    """
    audit = os.path.join(root, "docs", "audit")
    os.makedirs(os.path.join(audit, "phases"))
    os.makedirs(os.path.join(root, "src"))
    os.makedirs(os.path.join(root, ".claude"))
    _write_json(os.path.join(root, ".claude", "audit.config.json"),
                {"manifestPath": "docs/audit/audit-plan.json"})

    index = copy.deepcopy(INDEX)
    if parent_branch is not None:
        index["phases"][0]["parentBranch"] = parent_branch
    shard = _phase("P1", [_task("P1.1", "src/a.py"),
                          _task("P1.2", "src/b.py",
                                risk="high" if haiku else "low")])
    if parent_branch is not None:
        shard["parentBranch"] = parent_branch
    if haiku:
        shard["tasks"][1]["model"] = "haiku" if haiku == "declared" else "sonnet"
    other = _phase("P2", [_task("P2.1", "src/c.py")])
    index_path = os.path.join(audit, "audit-plan.json")
    shard_path = os.path.join(audit, "phases", "P1.json")
    _write_json(index_path, index)
    _write_json(shard_path, shard)
    _write_json(os.path.join(audit, "phases", "P2.json"), other)
    _write(os.path.join(root, "README.md"), "fixture\n")

    _git(root, "init", "-q")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/" + PARENT)
    _git(root, "config", "user.email", "fixture@example.com")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    base = _head(root)

    _git(root, "checkout", "-q", "-b", BRANCH)
    shard["branch"] = BRANCH
    shard["baseRef"] = base
    shard["status"] = "in_progress"

    # --- task P1.1 ------------------------------------------------------------
    _write(os.path.join(root, "src", "a.py"), "a = 1\n")
    shard["tasks"][0]["status"] = "done"
    _write_json(shard_path, shard)
    staged = ["src/a.py", "docs/audit/phases/P1.json"]
    if index_in_task:
        index["meta"]["title"] = "touched"
        _write_json(index_path, index)
        staged.append("docs/audit/audit-plan.json")
    if journal_in_commit:
        os.makedirs(os.path.join(audit, "journal"), exist_ok=True)
        _write(os.path.join(audit, "journal", "2026-08-fixture.jsonl"), "{}\n")
        staged.append("docs/audit/journal/2026-08-fixture.jsonl")
    if evidence_in_commit:
        os.makedirs(os.path.join(audit, "evidence"), exist_ok=True)
        _write(os.path.join(audit, "evidence", "2026-08-fixture.jsonl"), "{}\n")
        staged.append("docs/audit/evidence/2026-08-fixture.jsonl")
    if evidence_near_miss:
        # A SIBLING whose name merely starts the same way. The allow-list arm is a
        # prefix test, and a prefix test written without the separator swallows it.
        os.makedirs(os.path.join(audit, "evidence-notes"), exist_ok=True)
        _write(os.path.join(audit, "evidence-notes", "x.jsonl"), "{}\n")
        staged.append("docs/audit/evidence-notes/x.jsonl")
    _git(root, "add", *staged)
    _git(root, "commit", "-q", "-m", "chore(P1.1): audit - a")
    sha1 = _head(root)

    # --- task P1.2 ------------------------------------------------------------
    _write(os.path.join(root, "src", "b.py"), "b = 1\n")
    shard["tasks"][0]["commit"] = sha1
    shard["tasks"][1]["status"] = "done"
    if invalid_state:
        # A reference no task answers. The state COMMITTED here is invalid; the
        # working tree below is put back, so only the recorded state is wrong -
        # which is the only thing that separates this check from re-validating
        # the file that is already on disk.
        shard["tasks"][1]["dependsOn"] = ["P9.9"]
    _write_json(shard_path, shard)
    staged = ["src/b.py", "docs/audit/phases/P1.json"]
    if rogue:
        _write(os.path.join(root, "src", "rogue.py"), "rogue = 1\n")
        staged.append("src/rogue.py")
    _git(root, "add", *staged)
    _git(root, "commit", "-q", "-m", "chore(P1.2): audit - b")
    sha2 = _head(root)

    shard["tasks"][1]["commit"] = sha2
    shard["tasks"][1]["dependsOn"] = []
    if no_base_ref:
        shard["baseRef"] = None
    if bad_base:
        shard["baseRef"] = sha1               # on the phase branch, never on main
    _write_json(shard_path, shard)

    if forced:
        # Rewind and rebuild: the tip then moves to a commit the previous tip is
        # not an ancestor of, which is what a force leaves behind.
        _git(root, "reset", "--hard", "-q", sha1)
        _write(os.path.join(root, "src", "b.py"), "b = 2\n")
        _git(root, "add", "src/b.py")
        _git(root, "commit", "-q", "-m", "chore(P1.2): audit - b again")
    if stash:
        _write(os.path.join(root, "src", "a.py"), "a = 99\n")
        _git(root, "stash", "push", "-q", "-m", "wip")
    if push:
        remote = os.path.join(os.path.dirname(root), "remote.git")
        _git(root, "init", "-q", "--bare", remote)
        _git(root, "remote", "add", "origin", remote)
        _git(root, "push", "-q", "origin", BRANCH)
    if drop_branch:
        # What sign-off actually does, in its own order: commit the last shard
        # write, ff-merge into the parent, delete the branch. Discarding the
        # working tree instead would leave a manifest with no `task.commit` in
        # it, and every other check would then be answering about a phase that
        # never ran.
        _git(root, "add", "docs/audit/phases/P1.json")
        _git(root, "commit", "-q", "-m", "chore(P1): phase sign-off")
        _git(root, "checkout", "-q", PARENT)
        _git(root, "merge", "-q", "--ff-only", BRANCH)
        _git(root, "branch", "-q", "-d", BRANCH)

    if journal_rows or journal_real:
        d = os.path.join(audit, "journal")
        os.makedirs(d, exist_ok=True)
        rows = []
        if journal_real:
            # A row whose stateHash names bytes a commit DID preserve. Without
            # one, every row is unrecoverable and the coverage count reads the
            # same whether the module hashes the shard or the index - which is
            # exactly the bug this fixture exists to keep caught.
            probe = os.path.join(root, "state-probe.json")
            _write(probe, _git(root, "show", "%s:docs/audit/phases/P1.json" % sha1))
            rows.append(json.dumps({
                "v": 1, "ts": "2026-08-01T10:00:00Z", "action": "manifest.edit",
                "target": "docs/audit/phases/P1.json",
                "summary": "Edit wrote it",
                "stateHash": _journal_io.file_hash(probe)}))
            os.remove(probe)
        for i in range(journal_rows):
            rows.append(json.dumps({
                "v": 1, "ts": "2026-08-2%dT10:00:00Z" % (i % 10,),
                "action": "manifest.edit",
                "target": "docs/audit/phases/P1.json",
                "summary": "Edit wrote it",
                "stateHash": "sha256:%064d" % (i,)}))
        _write(os.path.join(d, "2026-08-rows.jsonl"), "\n".join(rows) + "\n")

    return {"root": root, "manifest": index_path, "shard": shard_path,
            "base": base, "sha1": sha1, "sha2": sha2}


class Repos(object):
    """Built once per option signature, torn down at the end.

    A cache rather than a fixture per case: several cases ask different questions
    of the same repository, and rebuilding it per case would multiply the git
    calls without changing a single answer.
    """

    def __init__(self):
        self.tmp = _harness.fixture_root("audit-inv-")
        self.made = {}

    def get(self, **opts):
        key = json.dumps(opts, sort_keys=True)
        if key not in self.made:
            root = os.path.join(self.tmp, "r%d" % (len(self.made),), "repo")
            os.makedirs(root)
            self.made[key] = build(root, **opts)
        return self.made[key]

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def _phase_answer(fx, ledger_dir=None, mutate=None):
    """`check_phase` over a fixture, with an optional in-memory manifest edit.

    `mutate` is how the both-directions cases are written: the same repository,
    one field changed, and the verdict must move. Editing the loaded manifest
    rather than the file keeps the git history — the other half of the evidence —
    identical between the two runs.
    """
    manifest = _mio.load_manifest(fx["manifest"])
    if mutate:
        mutate(manifest)
    return M.check_phase(manifest, "P1", fx["manifest"], fx["root"], fx["root"],
                         ledger_dir=ledger_dir)


def _check(answer, name):
    for c in answer["checks"]:
        if c["name"] == name:
            return c
    raise KeyError("no check named %r in %r"
                   % (name, [c["name"] for c in answer["checks"]]))


def _ledger(root, rows):
    """A ledger directory holding one month file, or the empty directory."""
    d = os.path.join(root, ".claude", "usage")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "2026-08.jsonl"), "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return d


def _row(task_id, model):
    return {"ts": "2026-08-21T10:00:00Z", "taskId": task_id, "phaseId": "P1",
            "model": model, "msgs": 1, "costUSD": 0.01}


# --- cases --------------------------------------------------------------------
def _cases(check):
    repos = Repos()
    try:
        clean = repos.get()

        # --- the verdict vocabulary -------------------------------------------
        check("iv1 `clean` is unreachable without something examined - a filter "
              "that narrowed to nothing says no-basis, which is the direction a "
              "boolean gets wrong",
              M.verdict_of([], [], 0, True) == M.NO_BASIS
              and M.verdict_of([], [], 3, True) == M.CLEAN)
        check("iv2 ...and a check that examined things but lost some evidence is "
              "`partial`, not `clean` - the middle answer that has to exist for "
              "the other two to mean anything",
              M.verdict_of([], ["gone"], 3, True) == M.PARTIAL
              and M.verdict_of(["b"], ["gone"], 3, True) == M.BREACH
              and M.verdict_of([], [], 0, False) == M.NA)
        check("iv3 every result carries its basis, and there is no way to build "
              "one without: `result()` takes it positionally",
              all(M.result(n, "b", [], [], 1)["basis"] == "b"
                  for n in M.CHECK_NAMES))

        # --- commit scope ------------------------------------------------------
        answer = _phase_answer(clean)
        scope = _check(answer, "commit-scope")
        check("iv4 the clean fixture's two task commits are examined and clean - "
              "and `examined` is asserted, so a fixture that stopped resolving "
              "its SHAs could not pass this as a clean phase: %r"
              % (scope["verdict"],),
              scope["verdict"] == M.CLEAN and scope["examined"] == 2
              and scope["breaches"] == [], scope["gaps"])

        rogue = repos.get(rogue=True)
        scope = _check(_phase_answer(rogue), "commit-scope")
        check("iv5 a file the task does not own is ONE breach, not a report of "
              "every file in the commit - counted, because 'a line mentions "
              "rogue.py' passes either way: %r" % (scope["breaches"],),
              len(scope["breaches"]) == 1
              and "src/rogue.py" in scope["breaches"][0]
              and "P1.2" in scope["breaches"][0])

        scope = _check(_phase_answer(clean, mutate=_drop_file), "commit-scope")
        check("iv6 ...and the OTHER direction: take `src/a.py` out of the task's "
              "`files` and the same clean commit becomes a breach. This is the "
              "case that fails if the allow-list stops being read at all: %r"
              % (scope["breaches"],),
              len(scope["breaches"]) == 1 and "src/a.py" in scope["breaches"][0])

        indexed = repos.get(index_in_task=True)
        scope = _check(_phase_answer(indexed), "commit-scope")
        check("iv7 staging the manifest INDEX in a task commit is its own breach "
              "with its own sentence - it is what makes parallel phases conflict, "
              "and reporting it as 'an unexpected path' would price it as a stray "
              "README: %r" % (scope["breaches"],),
              len(scope["breaches"]) == 1
              and "INDEX" in scope["breaches"][0])

        journalled = repos.get(journal_in_commit=True)
        scope = _check(_phase_answer(journalled), "commit-scope")
        check("iv8 the journal directory is allowed in a task commit - step 4c "
              "says to stage it, so a checker that called it unexpected would "
              "report every correct run: %r" % (scope["breaches"],),
              scope["breaches"] == [] and scope["verdict"] == M.CLEAN)

        evidenced = repos.get(evidence_in_commit=True)
        scope = _check(_phase_answer(evidenced), "commit-scope")
        check("iv40 ...and so is the EVIDENCE directory, for the same reason one "
              "noun over: a task commit stages it so a failed run's record "
              "reaches git at all, and an allow-list that did not know it would "
              "report every correct run as a breach: %r" % (scope["breaches"],),
              scope["breaches"] == [] and scope["verdict"] == M.CLEAN)

        nearby = repos.get(evidence_near_miss=True)
        scope = _check(_phase_answer(nearby), "commit-scope")
        check("iv41 ...and the arm is a PREFIX test, so its boundary is asserted "
              "in the over-firing direction too: a sibling directory whose name "
              "merely starts the same way is still a breach. Written because a "
              "prefix test that forgets the separator passes iv40 and admits the "
              "whole repository: %r" % (scope["breaches"],),
              len(scope["breaches"]) == 1
              and "docs/audit/evidence-notes/x.jsonl" in scope["breaches"][0])

        scope = _check(_phase_answer(clean, mutate=_fake_sha), "commit-scope")
        check("iv9 a recorded SHA git does not have is a GAP and no-basis, never "
              "a clean phase: nothing could be read, and the count says so: %r"
              % (scope["gaps"],),
              scope["verdict"] == M.NO_BASIS and scope["examined"] == 0
              and len(scope["gaps"]) == 2)

        scope = _check(_phase_answer(clean, mutate=_no_commits), "commit-scope")
        check("iv10 a phase with no recorded commit is not-applicable, which is "
              "not the same word as clean",
              scope["verdict"] == M.NA and scope["examined"] == 0)

        # --- branch history ----------------------------------------------------
        hist = _check(_phase_answer(clean), "branch-history")
        check("iv11 a live branch with clean history reads `clean`, over all three "
              "sources. The two standing limits of the method - one clone only, a "
              "dropped stash - are in the BASIS, not appended as gaps: a gap on "
              "every run would make this verdict unreachable, and a verdict "
              "nothing can reach is one nobody reads: %r %r"
              % (hist["verdict"], hist["gaps"]),
              hist["verdict"] == M.CLEAN and hist["breaches"] == []
              and hist["gaps"] == [] and hist["examined"] == 3)
        check("iv11b ...and both limits are still SAID, in the basis that travels "
              "with the verdict - dropped from the output altogether would be the "
              "other way to make this check dishonest: %r" % (hist["basis"][-90:],),
              "THIS clone only" in hist["basis"] and "DROPPED" in hist["basis"])

        stashed = repos.get(stash=True)
        hist = _check(_phase_answer(stashed), "branch-history")
        check("iv12 a stash taken on this branch is exactly one breach, naming "
              "the branch it was taken on: %r" % (hist["breaches"],),
              len(hist["breaches"]) == 1 and BRANCH in hist["breaches"][0]
              and "stash" in hist["breaches"][0])

        pushed = repos.get(push=True)
        hist = _check(_phase_answer(pushed), "branch-history")
        check("iv13 a branch that reached a remote is a breach naming the "
              "remote-tracking ref - the evidence a plain `git push` leaves, "
              "which no hook can refuse: %r" % (hist["breaches"],),
              len(hist["breaches"]) == 1
              and "refs/remotes/origin/" + BRANCH in hist["breaches"][0])

        forced = repos.get(forced=True)
        hist = _check(_phase_answer(forced), "branch-history")
        # Sliced on the sentence each half writes, not on a word both carry: the
        # ancestry line QUOTES the reflog message, so "reset:" appears in both and
        # a naive filter would count one line twice and still look right.
        ancestry = [b for b in hist["breaches"] if b.startswith("the branch tip moved")]
        worded = [b for b in hist["breaches"] if b.startswith("the branch reflog records")]
        check("iv14 a forced update is caught by ANCESTRY - the tip moved to a "
              "commit the old tip does not reach - and separately by the reflog's "
              "own word for it. Both fire here, and the ancestry half is the one "
              "that survives a rewrite spelled some other way: %r"
              % (hist["breaches"],),
              len(ancestry) == 1 and len(worded) == 1)

        dropped = repos.get(drop_branch=True)
        hist = _check(_phase_answer(dropped), "branch-history")
        # Sliced on the branch NAME, not on the words "no reflog". Written the
        # obvious way this case passed with the gap deleted: the stash caveat
        # printed on every run contains "no reflog entry", so the assertion was
        # matching a line that is always there. The mutation is what found it.
        named = [g for g in hist["gaps"] if ("has no reflog for " + BRANCH) in g]
        check("iv15 a branch deleted at sign-off takes its reflog with it, and "
              "the answer is a gap NAMING that branch - not clean. This is the "
              "single most common state a finished phase is in: %r"
              % (hist["gaps"],),
              hist["verdict"] != M.CLEAN and len(named) == 1)

        hist = _check(_phase_answer(clean, mutate=_no_branch), "branch-history")
        check("iv16 a phase that never cut a branch is not-applicable: there is "
              "no history, which is different from a clean one",
              hist["verdict"] == M.NA)

        # --- manifest revalidated ---------------------------------------------
        valid = _check(_phase_answer(clean), "manifest-revalidated")
        check("iv17 both committed manifest states are reassembled from git and "
              "re-validated, and they pass: %r %r"
              % (valid["verdict"], valid["breaches"]),
              valid["examined"] == 2 and valid["breaches"] == [])

        broken = repos.get(invalid_state=True)
        valid = _check(_phase_answer(broken), "manifest-revalidated")
        check("iv18 a state that was COMMITTED invalid is a breach naming the "
              "commit and the finding - and the working tree is valid in this "
              "fixture, so nothing but the recorded state could have produced it: "
              "%r" % (valid["breaches"],),
              len(valid["breaches"]) == 1
              and broken["sha2"][:12] in valid["breaches"][0])

        rowed = repos.get(journal_rows=3)
        valid = _check(_phase_answer(rowed), "manifest-revalidated")
        gap = [g for g in valid["gaps"] if "journal-recorded writes" in g]
        check("iv19 journal rows whose stateHash matches no state git preserved "
              "are COUNTED as the coverage gap - the honest half of a check that "
              "cannot see between two commits: %r" % (valid["gaps"],),
              len(gap) == 1 and "3 of the 3" in gap[0]
              and valid["verdict"] == M.PARTIAL)

        mixed = repos.get(journal_rows=1, journal_real=True)
        valid = _check(_phase_answer(mixed), "manifest-revalidated")
        gap = [g for g in valid["gaps"] if "journal-recorded writes" in g]
        check("iv39 ...and a row whose bytes a commit DID preserve is not counted "
              "against coverage: one of the two is recoverable, so the gap says "
              "so. This is the case that fails if the state hashed is the INDEX "
              "rather than the phase's own file - a mistake iv19 cannot see, "
              "because there every row is unrecoverable either way: %r"
              % (valid["gaps"],),
              len(gap) == 1 and "1 of the 2" in gap[0])

        valid = _check(_phase_answer(clean), "manifest-revalidated")
        check("iv20 ...and with no journal row at all it says THAT, rather than "
              "reporting full coverage over an empty set: %r" % (valid["gaps"],),
              any("holds no row" in g for g in valid["gaps"]))

        # --- high-risk model ---------------------------------------------------
        risky = _check(_phase_answer(clean), "high-risk-model")
        check("iv21 a phase with no high-risk task is not-applicable",
              risky["verdict"] == M.NA and risky["examined"] == 0)

        declared = repos.get(haiku="declared")
        risky = _check(_phase_answer(declared,
                                     ledger_dir=_ledger(declared["root"],
                                                        [_row("P1.2", "sonnet")])),
                       "high-risk-model")
        check("iv22 a high-risk task the MANIFEST routes to haiku is a breach "
              "even when the ledger says something else ran - the routing is "
              "wrong whatever happened to answer it: %r" % (risky["breaches"],),
              len(risky["breaches"]) == 1
              and "manifest routes it" in risky["breaches"][0])

        observed = repos.get(haiku="metered")
        led = _ledger(observed["root"],
                      [_row("P1.2", "claude-3-5-haiku-20241022")])
        risky = _check(_phase_answer(observed, ledger_dir=led), "high-risk-model")
        check("iv23 ...and the OTHER source: a manifest that says sonnet with a "
              "ledger row that says haiku is still a breach. This is the case a "
              "manifest-only check reports as compliance: %r"
              % (risky["breaches"],),
              len(risky["breaches"]) == 1
              and "ledger records" in risky["breaches"][0])

        compliant = repos.get(haiku="metered", journal_rows=1)
        risky = _check(_phase_answer(compliant,
                                     ledger_dir=_ledger(compliant["root"],
                                                        [_row("P1.2", "sonnet")])),
                       "high-risk-model")
        check("iv24 ...and a high-risk task metered on sonnet is clean, which is "
              "what makes iv23 a finding rather than a check that always fires: "
              "%r %r" % (risky["verdict"], risky["breaches"]),
              risky["verdict"] == M.CLEAN and risky["breaches"] == []
              and risky["examined"] == 1)

        risky = _check(_phase_answer(observed, ledger_dir=None),
                       "high-risk-model")
        check("iv25 with NO ledger the check is `partial` and says only the "
              "manifest's routing could be read - a spawn that ignored "
              "`task.model` leaves nothing here, and silence would have read as "
              "compliance: %r" % (risky["gaps"],),
              risky["verdict"] == M.PARTIAL
              and any("no usage ledger" in g for g in risky["gaps"]))

        empty = _ledger(repos.get(haiku="metered", drop_branch=True)["root"], [])
        risky = _check(_phase_answer(repos.get(haiku="metered", drop_branch=True),
                                     ledger_dir=empty), "high-risk-model")
        check("iv26 ...and a ledger with no row for THIS task names the task "
              "rather than passing it: the executor is spawned with the id in its "
              "description precisely so that a row would exist: %r"
              % (risky["gaps"],),
              risky["verdict"] == M.PARTIAL
              and any("P1.2" in g and "no row" in g for g in risky["gaps"]))

        # --- base ref ----------------------------------------------------------
        ref = _check(_phase_answer(clean), "base-ref")
        check("iv27 a phase cut from the development branch is clean, and the "
              "basis names the ancestry test AND the branch it resolved to - a "
              "verdict rendered against the wrong parent is the one mistake this "
              "check could otherwise make in silence: %r" % (ref["basis"],),
              ref["verdict"] == M.CLEAN and "is-ancestor" in ref["basis"]
              and "'main' (meta.developmentBranch)" in ref["basis"])

        wrong = repos.get(bad_base=True)
        ref = _check(_phase_answer(wrong), "base-ref")
        check("iv28 a baseRef that the parent branch does not contain is a "
              "breach - the phase was cut from somewhere else: %r"
              % (ref["breaches"],),
              len(ref["breaches"]) == 1
              and "not an ancestor" in ref["breaches"][0])

        missing = repos.get(no_base_ref=True)
        ref = _check(_phase_answer(missing), "base-ref")
        check("iv29 a branch with NO baseRef recorded is a breach rather than a "
              "gap: step 1b writes it before the branch is cut, so its absence is "
              "the rule being skipped, not evidence going missing: %r %r"
              % (ref["verdict"], ref["breaches"]),
              ref["verdict"] == M.BREACH and len(ref["breaches"]) == 1
              and "recorded no baseRef" in ref["breaches"][0])

        ref = _check(_phase_answer(clean, mutate=_unknown_parent), "base-ref")
        check("iv30 a parent branch this clone does not have is no-basis, and the "
              "line names the branch AND where the name came from: %r"
              % (ref["gaps"],),
              ref["verdict"] == M.NO_BASIS
              and any("no-such-branch" in g and "developmentBranch" in g
                      for g in ref["gaps"]))

        forked = repos.get(parent_branch=BRANCH)
        ref = _check(_phase_answer(forked), "base-ref")
        check("iv31 `phase.parentBranch` is what the check resolves against, not "
              "`meta.developmentBranch` - and the basis says so by naming the "
              "branch and the key. Both parents contain this baseRef, so the "
              "VERDICT cannot tell the two apart and only the basis can: %r"
              % (ref["basis"],),
              ref["verdict"] == M.CLEAN
              and ("%r (phase.parentBranch)" % BRANCH) in ref["basis"])

        ref = _check(_phase_answer(wrong, mutate=_parent_is_main), "base-ref")
        check("iv32 ...and the same repository with the parent forced back to "
              "main is a breach again, which is the pair that proves the resolver "
              "is what decides: %r" % (ref["breaches"],),
              len(ref["breaches"]) == 1)

        # --- folding -----------------------------------------------------------
        answer = _phase_answer(rogue)
        check("iv33 the phase answer prefixes every breach with the check that "
              "found it, so a caller printing the list alone still knows which "
              "rule was broken: %r" % (answer["breaches"],),
              all(b.split(":")[0] in M.CHECK_NAMES for b in answer["breaches"])
              and any(b.startswith("commit-scope:") for b in answer["breaches"]))
        check("iv34 ...and every declared check ran, in the declared order - a "
              "check silently dropped would otherwise shorten the list and "
              "shorten the breaches with it",
              [c["name"] for c in answer["checks"]] == list(M.CHECK_NAMES))

        missing_phase = M.check_phase(_mio.load_manifest(clean["manifest"]),
                                      "P404", clean["manifest"], clean["root"],
                                      clean["root"])
        check("iv35 an unknown phase id answers `found: False` rather than an "
              "empty clean report - the caller turns that into exit 2",
              missing_phase["found"] is False
              and missing_phase["breaches"] == [])

        manifest = _mio.load_manifest(rogue["manifest"])
        whole = M.check_manifest(manifest, rogue["manifest"], rogue["root"],
                                 rogue["root"])
        check("iv36 check_manifest looks only at phases that STARTED, and names "
              "the ones it skipped - 'no breaches' over a manifest whose phases "
              "were all skipped is a claim about nothing: %r %r"
              % (whole["checked"], whole["skipped"]),
              whole["checked"] == ["P1"] and whole["skipped"] == ["P2"])
        check("iv37 ...and its breaches carry the phase id as well as the check "
              "name, because a gate prints this list and nothing else: %r"
              % (whole["breaches"],),
              whole["breaches"]
              and all(b.startswith("P1 ") for b in whole["breaches"]))
        check("iv38 started_phases counts a recorded commit as started even with "
              "no branch left to look at - which is what a finished, merged and "
              "deleted phase looks like",
              M.started_phases({"phases": [
                  {"id": "A", "tasks": [{"id": "A.1", "commit": "abc"}]},
                  {"id": "B", "tasks": [{"id": "B.1"}]}]}) == ["A"])
    finally:
        repos.close()


# --- the in-memory mutations the both-directions cases use --------------------
def _drop_file(manifest):
    manifest["phases"][0]["tasks"][0]["files"] = []


def _fake_sha(manifest):
    for task in manifest["phases"][0]["tasks"]:
        task["commit"] = "0" * 40


def _no_commits(manifest):
    for task in manifest["phases"][0]["tasks"]:
        task["commit"] = None


def _no_branch(manifest):
    manifest["phases"][0]["branch"] = None


def _unknown_parent(manifest):
    manifest["meta"]["developmentBranch"] = "no-such-branch"


def _parent_is_main(manifest):
    manifest["phases"][0]["parentBranch"] = PARENT


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__invariants.py --selftest\n")
    raise SystemExit(2)
