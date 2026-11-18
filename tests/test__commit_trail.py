#!/usr/bin/env python3
"""
The cases for `_commit_trail.py` — is a recorded commit still REACHABLE?

The suite exists because of one distinction, and every case here is a way of
holding it: **an object being in the store is not the same as a ref reaching it.**
`/audit:doctor` asked `git rev-parse --verify` alone, which answers the first
question, so a `git reset --hard` that orphaned three task commits left all three
verifying green — until a `gc` ran, at which point they turned from recoverable
into gone with no event in between for anyone to notice.

`t3` is that case, built on a real repo with a real reset, and it is the one that
would go red if the check ever slid back to existence.

The other load-bearing shape is that `clear()` NEVER re-anchors. There is no
search for a commit with the same message or tree, because a plausible substitute
makes the trail read as intact when it is not — so the cases assert the SHA
becomes null and that what was lost comes back to the caller to record.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _commit_trail as M                          # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _repo(tmp, name="r"):
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", repo], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test User")
    shas = []
    for n in range(3):
        with open(os.path.join(repo, "f%d.txt" % n), "w", encoding="utf-8") as fh:
            fh.write("x")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "c%d" % n)
        shas.append(_git(repo, "rev-parse", "HEAD").stdout.decode().strip())
    return repo, shas


def _manifest(*commits):
    return {"meta": {"version": 2},
            "phases": [{"id": "P0", "title": "t", "status": "done",
                        "tasks": [{"id": "P0.%d" % (i + 1), "title": "t",
                                   "status": "done", "commit": c}
                                  for i, c in enumerate(commits)]}]}


def _cases(check):
    check("t0 a manifest with no recorded commit answers all three classes "
          "empty rather than raising - nothing to reach is a state, not an error",
          M.dangling(_manifest(), None) == {"missing": [], "unreachable": [],
                                            "unchecked": []})
    tmp = _harness.fixture_root("qg-trail-")
    try:
        repo, shas = _repo(tmp)

        check("t1 a reachable commit is in NO class - the clean case, and the one "
              "that goes red if the check ever starts refusing everything",
              M.dangling(_manifest(shas[1]), repo)
              == {"missing": [], "unreachable": [], "unchecked": []})
        check("t2 a SHA git has never seen is MISSING - a fabricated id, or one "
              "orphaned long enough ago for gc to collect it",
              [t for _p, t, _s in M.dangling(
                  _manifest("0" * 40), repo)["missing"]] == ["P0.1"],
              repr(M.dangling(_manifest("0" * 40), repo)))

        # THE CASE THE MODULE EXISTS FOR.
        _git(repo, "reset", "--hard", shas[0])
        d = M.dangling(_manifest(shas[2]), repo)
        check("t3 EXISTENCE IS NOT REACHABILITY. After `git reset --hard`, the "
              "orphaned commit is still IN THE OBJECT STORE - `rev-parse "
              "--verify` finds it and reports green - but no ref reaches it. It "
              "must land in `unreachable`, and it must not be silently clean: "
              "this is the bug the doctor's old rev-parse loop could not see, "
              "and the window in which the damage is still recoverable",
              [t for _p, t, _s in d["unreachable"]] == ["P0.1"]
              and d["missing"] == [], repr(d))
        check("t3b ...and the proof the two questions really differ: git still "
              "resolves that same SHA as an object, so a check built on "
              "rev-parse alone would call this trail healthy",
              _git(repo, "rev-parse", "-q", "--verify",
                   "%s^{commit}" % shas[2]).returncode == 0)

        check("t4 no git means UNCHECKED, never clean. 'could not ask' and "
              "'everything is present' are different answers, and folding the "
              "first into the second reports a machine with no git as healthy",
              [t for _p, t, _s in
               M.dangling(_manifest(shas[1]), None)["unchecked"]] == ["P0.1"],
              repr(M.dangling(_manifest(shas[1]), None)))

        # --- clear: null, never a substitute -------------------------------
        man = _manifest(shas[2], shas[0])
        out, cleared = M.clear(man, [("P0", "P0.1", shas[2])])
        tasks = out["phases"][0]["tasks"]
        check("t5 clear() nulls the named task's commit and leaves the others "
              "alone - a repair that touched a healthy row would be worse than "
              "the damage",
              tasks[0]["commit"] is None and tasks[1]["commit"] == shas[0],
              repr([t["commit"] for t in tasks]))
        check("t6 ...and hands back WHAT WAS LOST, because the caller's job is to "
              "record it. A repair that erased the evidence of its own necessity "
              "would be the same silence one step later",
              cleared == [{"phaseId": "P0", "taskId": "P0.1",
                           "wasCommit": shas[2]}], repr(cleared))
        check("t7 NO RE-ANCHOR: the cleared task's commit is null and not some "
              "other SHA. A substitute found by matching messages or trees makes "
              "the trail read as intact when the commit it was verified against "
              "is gone - the gap IS the fact",
              tasks[0]["commit"] is None
              and shas[0] not in [str(t["commit"]) for t in tasks[:1]],
              repr(tasks[0]))
        # A bug's `fixedIn` stored off its fix task's commit goes with that commit;
        # one naming ANOTHER commit was put there by someone and is left alone.
        man = _manifest(shas[2], shas[0])
        man["bugs"] = [{"id": "BUG-1", "taskId": "P0.1", "fixedIn": shas[2]},
                       {"id": "BUG-2", "taskId": "P0.1", "fixedIn": shas[1]},
                       {"id": "BUG-3", "taskId": "P0.2", "fixedIn": shas[0]}]
        out_b, cleared_b = M.clear(man, [("P0", "P0.1", shas[2])])
        fixed_in = [b["fixedIn"] for b in out_b["bugs"]]
        check("t5b clear() also clears a bug's fixedIn that held the commit its fix "
              "task lost, names it in `cleared`, and leaves a fixedIn naming any "
              "other commit - and the bug of a healthy task - alone: %r / %r"
              % (fixed_in, cleared_b),
              fixed_in == [None, shas[1], shas[0]]
              and [c.get("bugId") for c in cleared_b] == [None, "BUG-1"]
              and M.changes_of(cleared_b)[1] == {"id": "BUG-1", "field": "fixedIn",
                                                 "from": shas[2], "to": None}
              and "BUG-1" in M.summary(cleared_b))
        check("t8 summary() names the task and the SHA it used to hold, so the "
              "journal row is readable without opening the manifest",
              "P0.1" in M.summary(cleared) and shas[2][:12] in M.summary(cleared),
              M.summary(cleared))
        check("t9 ...and an empty repair says so rather than producing an "
              "authoritative-looking empty sentence",
              "no recorded commit" in M.summary([]), M.summary([]))

        # --- a shallow clone cannot accuse ---------------------------------------
        # Driven against a REAL truncated clone rather than a stubbed predicate.
        # `--depth 1` is what `actions/checkout` does by default, and the SHA the
        # manifest records is deliberately one the graft cut away - so the fixture
        # reproduces the CI failure rather than describing it.
        # ITS OWN REPO, not the shared one. By this point an earlier case has
        # `reset --hard`ed the shared fixture onto its first commit, so a
        # `--depth 1` clone of it fetches exactly the SHA this case needs to be
        # missing - `--depth` is per REF, and that ref now points there. Reusing
        # it made t10 report `cut_resolves=True` and t11 pass for the wrong
        # reason. A fresh repo also leaves nothing behind for the cases after.
        f88_repo, f88_shas = _repo(tmp, "f88")
        shallow = os.path.join(tmp, "shallow")
        # `file://` is required: git says "--depth is ignored in local clones"
        # and silently hands back a FULL clone, which would make every case
        # below assert the opposite of what it says.
        _git(tmp, "clone", "-q", "--depth", "1", "file://" + f88_repo, shallow)
        cut = f88_shas[0]
        deep_ok = _git(shallow, "rev-parse", "-q", "--verify",
                       cut + "^{commit}").returncode == 0
        check("t10 the fixture really is truncated - a clone git calls shallow, "
              "whose HEAD is present and whose oldest recorded commit is past the "
              "cut. A fixture where every SHA resolves would pass under any "
              "grading, which is how this case would assert nothing",
              M.is_shallow(shallow) is True and M.is_shallow(f88_repo) is False
              and not deep_ok,
              "shallow=%r full=%r cut_resolves=%r"
              % (M.is_shallow(shallow), M.is_shallow(f88_repo), deep_ok))
        _cut_shallow = M.dangling(_manifest(cut), shallow)
        check("t11 a commit past the graft is UNCHECKED, never missing - in a "
              "shallow clone `rev-parse` failing says the object is past where "
              "the clone was cut, and `missing` is graded as fabricated-or-"
              "collected, whose own remedy (`repair-commits.py --apply`) NULLS "
              "the SHA. The old grading made the doctor advise destroying an "
              "intact trail",
              _cut_shallow["missing"] == [] and _cut_shallow["unreachable"] == []
              and len(_cut_shallow["unchecked"]) == 1, _cut_shallow)
        _cut_full = M.dangling(_manifest(cut), f88_repo)
        check("t12 ...and the SECOND DIRECTION, which is the one that fails if "
              "the fix becomes unconditional: the same manifest against the FULL "
              "clone still resolves clean, so a version that routed every "
              "negative to unchecked would report a healthy trail as unasked",
              _cut_full == {"missing": [], "unreachable": [], "unchecked": []},
              _cut_full)
        _bogus_full = M.dangling(_manifest("0" * 40), f88_repo)
        check("t13 ...and a genuinely fabricated SHA in a full clone is STILL "
              "missing. This is the accusation the fix must not soften, and it "
              "is what separates 'shallow' from 'silent'",
              len(_bogus_full["missing"]) == 1
              and _bogus_full["unchecked"] == [], _bogus_full)
        _bogus_shallow = M.dangling(_manifest("0" * 40), shallow)
        check("t14 a fabricated SHA in a SHALLOW clone is unchecked, and that is "
              "the cost stated rather than hidden: the fix cannot tell a lie from "
              "a truncation, so it declines to tell either. Named here so nobody "
              "later reads t13 as covering both clones",
              _bogus_shallow["missing"] == []
              and len(_bogus_shallow["unchecked"]) == 1, _bogus_shallow)
        _notrepo = os.path.join(tmp, "plain-dir")
        os.makedirs(_notrepo)
        _nr = M.dangling(_manifest("0" * 40), _notrepo)
        check("t16 the fail-safe direction, pinned where it has a CONSEQUENCE: a "
              "git_root that is a directory but not a repository makes "
              "is_shallow() answer None, and every recorded SHA is then "
              "unchecked. Without that, a place with no repository at all would "
              "report a fabricated commit - an accusation from a question that "
              "was never answerable: %r" % (_nr,),
              _nr["missing"] == [] and _nr["unreachable"] == []
              and len(_nr["unchecked"]) == 1)
        check("t15 git refusing to say is treated as shallow, not as full - "
              "guessing 'not truncated' would restore the false accusation on "
              "the machine least able to argue with it",
              M.is_shallow(os.path.join(tmp, "nope-not-a-repo")) is None)

        # --- resolve(): one SHA, before it is ever written ----------------------
        # `/audit:task done` grades the SHA it is HANDED, so it needs the
        # existence question asked of ONE id rather than of a manifest. Lifted
        # out of `dangling` rather than spelled a second time in the writer -
        # this module's docstring says why - so these cases pin that the lifted
        # function keeps every distinction the loop above was tested for, and
        # that `dangling` still answers exactly as it did.
        check("r1 a SHA this clone HAS is present, and one it has never seen is "
              "absent - the two answers the writer turns into 'write it' and "
              "'refuse'",
              M.resolve(f88_repo, f88_shas[2]) == "present"
              and M.resolve(f88_repo, "0" * 40) == "absent",
              repr((M.resolve(f88_repo, f88_shas[2]),
                    M.resolve(f88_repo, "0" * 40))))
        check("r2 THE DISTINCTION THAT MATTERS: the same fabricated SHA is "
              "UNCHECKED in a shallow clone and unchecked with no git root at "
              "all. A writer grading either as absent would refuse honest closes "
              "on CI's default checkout, and then send the operator to "
              "`repair-commits.py --apply`, which NULLS a trail that was intact",
              M.resolve(shallow, "0" * 40) == "unchecked"
              and M.resolve(None, f88_shas[2]) == "unchecked"
              and M.resolve(_notrepo, "0" * 40) == "unchecked",
              repr((M.resolve(shallow, "0" * 40), M.resolve(None, f88_shas[2]),
                    M.resolve(_notrepo, "0" * 40))))
        check("r3 ...and a POSITIVE survives the cut, which is the half a "
              "blanket 'shallow means unchecked' would lose: the shallow clone's "
              "own HEAD really is present, so the writer can still verify the "
              "SHA an operator just made there",
              M.resolve(shallow, _git(shallow, "rev-parse", "HEAD")
                        .stdout.decode().strip()) == "present")
        check("r4 the `cut` argument is the shallow verdict the caller already "
              "paid for, not a second opinion: forced True it turns the absent "
              "answer into unchecked and leaves the present one alone, which is "
              "exactly how `dangling` asks it once per call instead of once per "
              "row",
              M.resolve(f88_repo, "0" * 40, True) == "unchecked"
              and M.resolve(f88_repo, f88_shas[2], True) == "present"
              and M.resolve(f88_repo, "0" * 40, False) == "absent")

        # --- can_answer(): the question a GATE has to ask first ----------------
        # `resolve` is written for a diagnostic, which must not accuse on a
        # truncation. A gate reading the same three words has the opposite
        # failure available to it: every row unchecked and nothing to report is
        # indistinguishable from a clean set, so the truncation becomes the
        # reason the gate is green. These pin both directions of the predicate
        # that stops that.
        _cut_ok, _cut_why = M.can_answer(shallow)
        check("ca1 a truncated clone CANNOT answer, and the sentence says so "
              "with the way out in it - a gate handed this must stop rather "
              "than report a clean set it never compared: %r" % (_cut_why,),
              _cut_ok is False and isinstance(_cut_why, str)
              and "SHALLOW" in _cut_why and "unshallow" in _cut_why)
        _full_ok, _full_why = M.can_answer(f88_repo)
        check("ca2 ...and THE SECOND DIRECTION, which is the one that fails if "
              "the refusal is ever widened: a full clone answers yes with no "
              "sentence, so the gate runs. A predicate that refused here would "
              "refuse every honest checkout and be routed around within a day: "
              "%r" % (_full_why,),
              _full_ok is True and _full_why is None)
        _nr_ok, _nr_why = M.can_answer(_notrepo)
        _none_ok, _none_why = M.can_answer(None)
        check("ca3 a directory that is not a repository, and no root at all, are "
              "both refusals naming which question failed - the fail-safe "
              "direction, since guessing 'complete' here is what puts the "
              "accusation back on the machine least able to argue with it: "
              "%r / %r" % (_nr_why, _none_why),
              _nr_ok is False and _none_ok is False
              and isinstance(_nr_why, str) and isinstance(_none_why, str))

        # --- referenced(): every commit a manifest NAMES, not just the trail ---
        _wide = {"phases": [{"id": "P0", "baseRef": "aaa1",
                             "tasks": [{"id": "P0.1", "commit": "bbb2"},
                                       {"id": "P0.2", "commit": None}]}],
                 "bugs": [{"id": "BUG-1", "fixedIn": "ccc3"},
                          {"id": "BUG-2", "fixedIn": None}]}
        check("rf1 a manifest names a commit in three places and all three are "
              "returned with the field that named them - `recorded()` answers "
              "for the TRAIL and a reader of committed data needs the baseRef "
              "and the bug's fixedIn too: %r" % (M.referenced(_wide),),
              M.referenced(_wide) == [("P0", "baseRef", "aaa1"),
                                      ("P0.1", "commit", "bbb2"),
                                      ("BUG-1", "fixedIn", "ccc3")])
        _shard = {"id": "P2", "baseRef": "ddd4",
                  "tasks": [{"id": "P2.1", "commit": "eee5"}]}
        check("rf2 ...and a SHARD - one phase with no `phases` wrapper - is read "
              "too, because that is the layout a reader of tracked files meets "
              "before anything assembles it, while `recorded()` deliberately "
              "still answers nothing for it: %r / %r"
              % (M.referenced(_shard), M.recorded(_shard)),
              M.referenced(_shard) == [("P2", "baseRef", "ddd4"),
                                       ("P2.1", "commit", "eee5")]
              and M.recorded(_shard) == [])
    finally:
        _harness.remove_tree(tmp)


# --- the verdict a commit carries in its trailers ------------------------------
# THE RULE, as properties, before any case:
#   * a TRAILER COMMIT is one whose trailer block - as git itself parses it -
#     carries an `Audit-Task` key; any other commit is not one, and its verdict is
#     read the way it was before trailers existed;
#   * `Audit-Task` with no `Audit-Gate` is NO VERDICT RECORDED, never passed;
#   * a key repeated with one value reads as that value; repeated with different
#     values, empty, or an `Audit-Gate` that is not `<status>[ <digest>]`, reads
#     as nothing recorded for that key, with the defect named;
#   * a status word this build does not know is returned as itself;
#   * keys compare case-insensitively, as git's own trailer matching does;
#   * of two commits naming one task, the first `git log --topo-order` shows
#     wins (no other carrier descends from it), and the others are named.
SCHEMA = os.path.join(_output.PLUGIN_ROOT, "schema", "audit-plan.schema.json")


def _commit(repo, name, message):
    """Commit one new file under `message`, given whole through `-F`."""
    with open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
        fh.write(name)
    msg = os.path.join(repo, ".git", "msg-%s" % (name,))
    with open(msg, "w", encoding="utf-8") as fh:
        fh.write(message)
    _git(repo, "add", "--", name)
    _git(repo, "commit", "-q", "--cleanup=verbatim", "-F", msg)
    return _git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def _parsed(repo, sha):
    """`git interpret-trailers --parse` over the commit's message: git's own
    reading, as `(key, value)` lines."""
    body = _git(repo, "log", "-1", "--format=%B", sha).stdout
    out = subprocess.run(["git", "-C", repo, "interpret-trailers", "--parse"],
                         input=body, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL).stdout.decode()
    return [tuple(part.strip() for part in ln.split(":", 1))
            for ln in out.splitlines() if ":" in ln]


def _gate_enum():
    """The `testEvidence.status` enum the schema declares."""
    import json
    with open(SCHEMA, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("enum") and "passed" in node["enum"] \
                    and "empty-gate" in node["enum"]:
                found.append(tuple(node["enum"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(doc)
    return found


def _verdict_cases(check):
    tmp = _harness.fixture_root("qg-trailers-")
    try:
        repo, _shas = _repo(tmp, "vt")
        full = _commit(repo, "full", "feat(P1.1): audit - the work\n\n"
                       "Audit-Task: P1.1\nAudit-Gate: passed sha256:abc1\n"
                       "Audit-Run: run-1\nAudit-Row: 00aa\n")
        nogate = _commit(repo, "nogate", "feat(P1.2): audit - x\n\n"
                         "Audit-Task: P1.2\nAudit-Row: 00bb\n")
        unknown = _commit(repo, "unknown", "feat(P1.3): audit - x\n\n"
                          "Audit-Task: P1.3\nAudit-Gate: shimmering sha256:d\n"
                          "Audit-Run: run-3\n")
        prose = _commit(repo, "prose", "feat(P1.4): audit - x\n\n"
                        "Audit-Task: P1.4\nAudit-Gate: passed sha256:e\n\n"
                        "a closing paragraph that is not a trailer\n")
        same = _commit(repo, "same", "x\n\nAudit-Task: P1.5\n"
                       "Audit-Gate: passed sha256:f\nAudit-Gate: passed sha256:f\n")
        split = _commit(repo, "split", "x\n\nAudit-Task: P1.6\n"
                        "Audit-Gate: passed sha256:g\nAudit-Gate: failed sha256:g\n")
        empty = _commit(repo, "empty", "x\n\nAudit-Task: P1.7\nAudit-Gate:\n")
        malformed = _commit(repo, "malformed", "x\n\nAudit-Task: P1.8\n"
                            "Audit-Gate: passed sha256:h and more\n")
        folded = _commit(repo, "folded", "x\n\nAudit-Task: P1.9\n"
                         "Audit-Gate: failed sha256:i\n"
                         "Audit-Override: first half\n  second  half\n")
        lower = _commit(repo, "lower", "x\n\naudit-task: P1.10\n"
                        "audit-gate: failed sha256:j\n")
        bare = _commit(repo, "bare", "x\n\nAudit-Task: P1.11\n"
                       "Audit-Gate: passed\n")
        every = [full, nogate, unknown, prose, same, split, empty, malformed,
                 folded, lower, bare]
        got, why = M.verdicts_at(repo, every + ["0" * 40, full[:12]])
        v = got or {}

        def at(sha):
            return v.get(sha) or {}

        agree = []
        for sha in every:
            mine = M.trailer_pairs(_git(
                repo, "log", "-1", "--format=%(trailers:only,unfold)",
                sha).stdout.decode())
            agree.append(mine == _parsed(repo, sha))
        check("vt1 the reader's trailers are git's: for every fixture commit "
              "the pairs it reads equal `git interpret-trailers --parse` of the "
              "same message, the folded and repeated ones included: %r"
              % (agree,), all(agree) and len(agree) == len(every))
        check("vt2 a commit carrying every verdict name reads back its task, status, "
              "digest and run, as recorded and known: %r" % (at(full),),
              why == "" and at(full).get("task") == "P1.1"
              and at(full).get("status") == "passed"
              and at(full).get("digest") == "sha256:abc1"
              and at(full).get("run") == "run-1"
              and at(full).get("recorded") is True
              and at(full).get("known") is True)
        check("vt3 Audit-Task with NO Audit-Gate is no verdict recorded - "
              "status None and recorded False, never passed: %r" % (at(nogate),),
              at(nogate).get("task") == "P1.2" and at(nogate).get("status") is None
              and at(nogate).get("recorded") is False)
        check("vt4 a status word this build does not know is returned AS ITSELF "
              "and marked unknown, never folded into passed or failed: %r"
              % (at(unknown),),
              at(unknown).get("status") == "shimmering"
              and at(unknown).get("known") is False
              and at(unknown).get("recorded") is True)
        check("vt5 a commit whose Audit-Task line is not in its trailer block - "
              "prose followed by another paragraph - is NOT a trailer commit, "
              "because git does not read it as one: %r"
              % ((prose in v, M.verdict_of(_parsed(repo, prose))),),
              prose not in v and M.verdict_of(_parsed(repo, prose)) is None)
        check("vt6 a key repeated with ONE value reads as that value; repeated "
              "with two values reads as nothing recorded, the key named in the "
              "problem rather than either value picked: %r / %r"
              % (at(same), at(split)),
              at(same).get("status") == "passed" and at(same).get("recorded")
              and at(split).get("status") is None
              and at(split).get("recorded") is False
              and any("Audit-Gate" in p for p in at(split).get("problems") or []))
        check("vt7 an EMPTY Audit-Gate and one that is not `<status>[ "
              "<digest>]` are no verdict recorded, each with its defect named: "
              "%r / %r" % (at(empty), at(malformed)),
              at(empty).get("recorded") is False
              and at(malformed).get("recorded") is False
              and at(empty).get("problems") and at(malformed).get("problems"))
        parsed_override = [val for key, val in _parsed(repo, folded)
                           if key == "Audit-Override"]
        check("vt8 a FOLDED trailer reads as git unfolds it - the line break and "
              "its indent become one space - which is why the writer refuses a "
              "reason holding a line break rather than folding it: %r / %r"
              % (at(folded).get("override"), parsed_override),
              at(folded).get("override") == "first half second  half"
              and parsed_override == [at(folded).get("override")])
        check("vt9 keys compare case-insensitively, as git's own trailer "
              "matching does: %r" % (at(lower),),
              at(lower).get("task") == "P1.10" and at(lower).get("status") == "failed")
        check("vt10 an Audit-Gate of the status alone is a recorded verdict with "
              "no digest - the shape a row with no gate digest writes: %r"
              % (at(bare),),
              at(bare).get("status") == "passed" and at(bare).get("digest") is None
              and at(bare).get("recorded") is True)
        check("vt11 the batch read keys each answer by the SHA it was asked "
              "for: an abbreviated one is answered, a SHA git does not hold is "
              "absent rather than an error, and a plain commit is absent: %r"
              % (sorted(v),),
              at(full[:12]).get("task") == "P1.1" and "0" * 40 not in v
              and _shas[0] not in v)
        none_got, none_why = M.verdicts_at(os.path.join(tmp, "nowhere"), [full])
        check("vt12 a place git cannot read answers None with the sentence, "
              "never an empty map that reads as 'no commit carries a verdict': "
              "%r" % ((none_got, none_why),),
              none_got is None and isinstance(none_why, str) and none_why)
        check("vt13 asked about no commit at all it asks git nothing and answers "
              "empty - `git log` given no revision would read HEAD instead",
              M.verdicts_at(repo, []) == ({}, ""))

        # --- which of two commits naming one task -----------------------------
        older = _commit(repo, "older", "x\n\nAudit-Task: P9.1\n"
                        "Audit-Gate: failed sha256:k\nAudit-Run: r-old\n")
        newer = _commit(repo, "newer", "x\n\nAudit-Task: P9.1\n"
                        "Audit-Gate: passed sha256:k\nAudit-Run: r-new\n")
        tv, twhy = M.task_verdicts(repo)
        p91 = (tv or {}).get("P9.1") or {}
        check("vt14 of two commits naming one task the one `git log "
              "--topo-order` shows first wins - no other carrier descends from "
              "it - and the other is NAMED, never dropped: %r" % (p91,),
              twhy == "" and p91.get("sha") == newer and p91.get("run") == "r-new"
              and p91.get("superseded") == [older])
        check("vt15 ...and the walk lists only trailer commits: the prose "
              "commit's task is absent: %r" % (sorted(tv or {}),),
              "P1.4" not in (tv or {}) and "P1.1" in (tv or {}))

        # --- a project in a subdirectory of its repository ---------------------
        # The reader carries no path to git, so asked from a subdirectory it must
        # read exactly what it reads from the top.
        sub = os.path.join(repo, "nested", "project")
        os.makedirs(sub)
        with open(os.path.join(sub, "plan.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "the nested project")
        sub_at, sub_why = M.verdicts_at(sub, [full, nogate])
        sub_tv, _stw = M.task_verdicts(sub)
        sub_plan, _spw = M.plan_verdicts(
            {"phases": [{"id": "P1", "tasks": [
                {"id": "P1.1", "status": "done", "commit": full}]}]}, sub)
        top_tv, _ttw = M.task_verdicts(repo)
        check("vt19 a PROJECT IN A SUBDIRECTORY of its repository reads the same "
              "verdicts as the repository's top - by SHA, by task walk and by "
              "plan - because no path, the plan's or git's, is handed to git: "
              "%r / %r" % (sorted(sub_tv or {}), sorted(top_tv or {})),
              sub_why == "" and (sub_at or {}).get(full) == at(full)
              and (sub_at or {}).get(nogate) == at(nogate)
              and sub_tv == top_tv and "P9.1" in (sub_tv or {})
              and (sub_plan or {}).get("P1.1", {}).get("run") == "run-1")
        dir_tv, dir_why = M.task_verdicts(repo, "nested")
        check("vt20 a revision naming a DIRECTORY is refused, never read as a "
              "pathspec - the history of that directory alone would come back "
              "as if it were the walk asked for: %r" % ((dir_tv, dir_why),),
              dir_tv is None and isinstance(dir_why, str) and "nested" in dir_why)

        # --- a clone with no evidence directory --------------------------------
        ev_dir = os.path.join(repo, "docs", "audit", "evidence")
        os.makedirs(ev_dir)
        with open(os.path.join(ev_dir, "2026-11.x.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"runId": "run-1", "status": "failed"}\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "the ledger")
        clone = os.path.join(tmp, "clone")
        _git(tmp, "clone", "-q", repo, clone)
        _harness.remove_tree(os.path.join(clone, "docs", "audit", "evidence"))
        cv, _cwhy = M.verdicts_at(clone, [full])
        mine = (cv or {}).get(full) or {}
        check("vt16 in a CLONE whose evidence directory is removed - and whose "
              "ledger, while it was there, said otherwise - the reader returns "
              "the same task, status, digest and run: it reads git alone: %r"
              % (mine,),
              [mine.get(k) for k in ("task", "status", "digest", "run")]
              == ["P1.1", "passed", "sha256:abc1", "run-1"]
              and not os.path.isdir(os.path.join(clone, "docs", "audit",
                                                 "evidence")))

        # --- the plan's done tasks, read at their commits ----------------------
        plan = {"phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "done", "commit": full},
            {"id": "P1.2", "status": "done", "commit": nogate},
            {"id": "P1.3", "status": "in_progress", "commit": unknown},
            {"id": "P1.9", "status": "done", "commit": full},
            {"id": "P1.12", "status": "done", "commit": _shas[0]}]}]}
        pv, pwhy = M.plan_verdicts(plan, repo)
        pv = pv or {}
        check("vt17 a plan's DONE tasks are read at their recorded commits: a "
              "task whose commit carries its verdict has it, one whose commit "
              "names no gate has no verdict recorded, a task not done is not "
              "read, and a commit with no trailers gives nothing: %r"
              % (sorted(pv),),
              pwhy == "" and pv.get("P1.1", {}).get("status") == "passed"
              and pv.get("P1.2", {}).get("recorded") is False
              and "P1.3" not in pv and "P1.12" not in pv)
        check("vt18 a commit naming ANOTHER task is not this task's verdict: "
              "recorded False and the mismatch named, rather than one task's "
              "green lent to another: %r" % (pv.get("P1.9"),),
              pv.get("P1.9", {}).get("recorded") is False
              and any("P1.1" in p for p in pv.get("P1.9", {}).get("problems")
                      or []))

        # --- the writer, which must write only what this reader reads back -----
        row = {"runId": "run-7", "status": "passed", "gateDigest": "sha256:ff"}
        lines, refusal = M.verdict_trailers("P1.1", row)
        check("wt1 the writer names the task, the bound run's status and gate "
              "digest, and its run, in that order: %r" % (lines,),
              refusal is None and lines == ["Audit-Task: P1.1",
                                            "Audit-Gate: passed sha256:ff",
                                            "Audit-Run: run-7"])
        lines, refusal = M.verdict_trailers("P1.1", None)
        check("wt2 with no bound run it names the task alone - which the reader "
              "reads as no verdict recorded: %r" % (lines,),
              refusal is None and lines == ["Audit-Task: P1.1"])
        lines, refusal = M.verdict_trailers("P1.1", row, "first line\nsecond")
        check("wt3 an override reason holding a line break is REFUSED, the line "
              "named - git unfolds a folded trailer into one line, so the reason "
              "could not be carried verbatim: %r" % ((lines, refusal),),
              lines == [] and isinstance(refusal, str) and "line 2" in refusal)
        lines, refusal = M.verdict_trailers("P1.1", row, "carriage\rreturn")
        check("wt4 ...a carriage return the same way", lines == []
              and isinstance(refusal, str) and refusal)
        reason = "a: known flake  #42 - ok ü"
        lines, refusal = M.verdict_trailers("P1.1", row, reason)
        rt = _commit(repo, "roundtrip", "feat(P1.1): audit - x\n\n%s\n"
                     % ("\n".join(lines),))
        back = (M.verdicts_at(repo, [rt])[0] or {}).get(rt) or {}
        check("wt5 ROUND TRIP through git: what the writer writes, git parses "
              "and the reader reads back as the same task, status, digest, run "
              "and the override reason VERBATIM: %r" % (back,),
              refusal is None
              and [back.get(k) for k in ("task", "status", "digest", "run",
                                         "override")]
              == ["P1.1", "passed", "sha256:ff", "run-7", reason])
        check("wt6 the status words the reader knows are the schema's "
              "`testEvidence.status` enum, pinned by reading the schema: %r"
              % (_gate_enum(),),
              _gate_enum() and all(set(e) == set(M.GATE_WORDS)
                                   for e in _gate_enum()))
    finally:
        _harness.remove_tree(tmp)


def _selftest():
    def body(check):
        _cases(check)
        _verdict_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__commit_trail.py --selftest\n")
    raise SystemExit(2)
