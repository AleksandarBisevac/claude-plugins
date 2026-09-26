#!/usr/bin/env python3
"""
Cases for `governance/commit-manifest-index.py` — the verb that lands the shared
index without taking a phase's work with it.

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
import _scoped_commit as _scoped                   # noqa: E402  (the shared header bound)
import test__invariants as TI                      # noqa: E402  (the ONE git fixture)
# commitlint's default `subject-case`, transcribed ONCE and imported. The
# rule is commitlint's and belongs to neither writer, so a second transcription
# here is how these two commands would come to be graded against two readings of
# it - the same argument that keeps the staging discipline in `_scoped_commit`.
# `header_offences`' own ability to fire on each of the four is proven beside it,
# in `test_commit_audit_state`, for the same reason: one home, one proof.
from test_commit_audit_state import HEADER_MAX_LENGTH, header_offences  # noqa: E402

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


def _row_files(fx):
    """The git-root-relative journal files holding an index-commit row."""
    return sorted(set("docs/audit/journal/%s" % (r["_file"],)
                      for r in _index_rows(fx)))


def _set_session(value):
    """Name the session the command-line writers read, or take the name away.

    Returns what was there, which is what the restore takes back — the suite runs
    inside a real session on a developer's machine and inherits its id, so a case
    that only SET the variable would leave every case after it writing under a
    fixture's session id.
    """
    held = os.environ.get(_journal_io.ENV_SESSION_VAR)
    if value is None:
        os.environ.pop(_journal_io.ENV_SESSION_VAR, None)
    else:
        os.environ[_journal_io.ENV_SESSION_VAR] = value
    return held


def _writers(fx, config):
    """The writer id each journal file's NAME carries, sorted and deduplicated.

    THE FILE NAME IS THE CLAIM. Reading the rows would say what was written and
    never where it landed, and where it landed is the whole of what splits a
    session's trail.
    """
    directory = _journal_io.journal_dir(fx["root"], config)
    return sorted(set(_journal_io.writer_of(os.path.basename(path))
                      for path in _journal_io.journal_files(directory)))


def _task_verb_row(fx, config):
    """One row in the shape `/audit:task` appends, from the same session.

    THE OTHER COMMAND-LINE WRITER, spelled here rather than driven, because what
    is being compared is the ACTOR a Bash-run verb files under — and that shape
    is a literal in each of those verbs, not a function this suite could call.
    """
    return _journal_io.append_from_cli(fx["root"], {
        "action": "task.add",
        "actor": {"author": None,
                  "sessionId": os.environ.get(_journal_io.ENV_SESSION_VAR),
                  "via": "cli"},
        "target": _journal_io.repo_relative_or_token(fx["root"], fx["manifest"]),
        "summary": "a structural edit by the other command-line writer of this "
                   "same session",
        "details": {"phaseId": PHASE},
    }, config=config)


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

        check("cmi2 ...and the commit carries the index and the ONE journal "
              "file holding the row that names it, and NOTHING else - asserted "
              "as the whole file list, not as 'the index is in there', because a "
              "commit that swept in the shard beside it also contains the "
              "index: %r" % (_carried(fx, after),),
              len(_row_files(fx)) == 1
              and sorted(_carried(fx, after)) == sorted([INDEX_REL]
                                                        + _row_files(fx)))

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
        nonce = details.get(_invariants.NONCE_KEY)
        resolved, _why = _invariants.commits_carrying(fx["root"], [nonce])
        check("cmi5 the commit anchors itself with exactly one journal row "
              "carrying a nonce and the phase, and the nonce resolves to THIS "
              "commit through its trailer - the only handle anything has on "
              "such a commit, since it is not a `task.commit` and the manifest "
              "does not name it: %r -> %r" % (details, resolved),
              len(rows) == 1 and (resolved or {}).get(nonce) == [after]
              and details.get("phaseId") == PHASE)

        check("cmi6 ...and both keys are on `_journal_io.DETAILS_KEYS`, checked "
              "rather than assumed: the allow-list silently DROPS a key it does "
              "not know, so a row could carry neither and this suite would still "
              "see an `audit.index.committed` action go by",
              _invariants.NONCE_KEY in _journal_io.DETAILS_KEYS
              and "phaseId" in _journal_io.DETAILS_KEYS)

        graded = _invariants.check_phase(
            _mio.load_manifest(fx["manifest"]), PHASE, fx["manifest"],
            fx["root"], fx["root"])
        scope = [c for c in graded["checks"] if c["name"] == "index-scope"][0]
        check("cmi6b ...and `index-scope` grades that commit CLEAN, journal file "
              "and all, having FOUND it through the trailer - `examined` is "
              "asserted, so a reader that stopped resolving the nonce could not "
              "pass this as clean: %r / %r / %r"
              % (scope["verdict"], scope["breaches"], scope["gaps"]),
              scope["verdict"] == _invariants.CLEAN and scope["examined"] == 1
              and [ln for ln in _porcelain(fx) if "docs/audit/journal" in ln]
              == [])

        subject = TI._git(fx["root"], "log", "-1", "--format=%s").strip()
        check("cmi7 the separating literal is a fixed SCOPE and the type is one "
              "conventional-commit tooling accepts. The scope is where nothing a "
              "manifest sets can reach - `meta.commit.type` chooses a task "
              "commit's TYPE and its scope is the phase id - so `git log --grep "
              "%s` tells this class from the other two for ever, and a repo with "
              "husky+commitlint still takes the commit: %r"
              % (M.COMMIT_SCOPE, subject),
              subject.startswith("%s(%s): %s %s"
                                 % (M.COMMIT_TYPE, M.COMMIT_SCOPE,
                                    M.SUBJECT_LEAD, PHASE))
              and M.COMMIT_SCOPE not in ("", None, "audit-state")
              and PHASE in subject
              and M.COMMIT_TYPE in ("build", "chore", "ci", "docs", "feat", "fix",
                                    "perf", "refactor", "revert", "style", "test"))

        # --- the subject a commitlint repository will take ---------------------
        # THE SAME FAULT THIS FILE'S SIBLING HAD, and the reason it is asserted
        # separately rather than trusted from there: the two writers compose the
        # subject in two copies of one format string, so one of them can be
        # repaired while the other keeps shipping the shape husky refuses. The
        # old shape is built from THIS module's own constants, so the case cannot
        # go on comparing against a spelling this file has stopped emitting.
        was = "%s(%s): %s - %s" % (M.COMMIT_TYPE, M.COMMIT_SCOPE, PHASE,
                                   M.DEFAULT_SUBJECT)
        check("cmi7b ...and the SUBJECT git recorded is out of reach of every "
              "case commitlint's default `subject-case` forbids, rather than of "
              "the one that bit: the phase id leading a lowercase sentence IS "
              "sentence-case, so the subject opens with a fixed lowercase word "
              "this command owns and all of the forbidden cases capitalise a "
              "subject's first character: %r -> %r / the shape it replaced -> %r"
              % (subject, header_offences(subject), header_offences(was)),
              header_offences(subject) == []
              and header_offences(was) == ["sentence-case"])

        # THE CALLER CANNOT UNDO IT. The LOWERCASE `--subject` is the fixture that
        # separates the two implementations - without the fixed word ahead of it
        # that header is sentence-case again - and the phase id and scope are
        # asserted alongside, because deleting the id is the other way to stop
        # offending the case rules.
        composed = [M.commit_message(PHASE, text, None)[0] for text in
                    ("landed the index after a task add",
                     "Landed the index after a task add")]
        check("cmi7c ...and no `--subject` can put a capital, or the id, back in "
              "first position - the lowercase word is this command's and sits "
              "ahead of the caller's text, while the id stays uppercase where "
              "`git log` finds it: %r" % (composed,),
              all(header_offences(header) == [] and PHASE in header
                  and header.startswith("%s(%s): %s %s - "
                                        % (M.COMMIT_TYPE, M.COMMIT_SCOPE,
                                           M.SUBJECT_LEAD, PHASE))
                  for header in composed))

        check("cmi7d ...and the header still fits commitlint's default "
              "`header-max-length` - the longest default subject of the two "
              "writers is this one's, so it is the half of that budget worth "
              "watching, and the fixed word spent some of it: %d against a limit "
              "of %d" % (len(subject), HEADER_MAX_LENGTH),
              len(subject) <= HEADER_MAX_LENGTH)

        # ...AND A CALLER CANNOT SPEND WHAT IS LEFT OF IT. cmi7d measures the
        # DEFAULT subject, which this command chooses; `--subject` is the half it
        # does not, and nothing bounded it - so the rule that refuses a commit
        # AFTER the files are staged was reachable from the one direction the
        # fixed opening does not cover. The bound lives with the composer and the
        # transcription of commitlint's own rule stays here, so the two are
        # compared rather than one being read off the other.
        spent = M.commit_message(PHASE, "y" * (HEADER_MAX_LENGTH * 2), None)[0]
        check("cmi7e ...and a `--subject` longer than the whole budget is CUT "
              "rather than carried past it: the header still fits, still opens "
              "with this command's own words, still names the phase, and still "
              "offends none of the case rules - and the cut says so: %r"
              % (spent,),
              len(spent) <= HEADER_MAX_LENGTH and header_offences(spent) == []
              and PHASE in spent
              and spent.startswith("%s(%s): %s %s - "
                                   % (M.COMMIT_TYPE, M.COMMIT_SCOPE,
                                      M.SUBJECT_LEAD, PHASE))
              and spent.endswith(_scoped.SUBJECT_TRUNCATED))
        check("cmi7f ...and the budget the composer holds IS commitlint's, "
              "compared against this suite's own transcription of the rule "
              "rather than read out of the module it is grading: %d / %d"
              % (_scoped.HEADER_MAX_CHARS, HEADER_MAX_LENGTH),
              _scoped.HEADER_MAX_CHARS == HEADER_MAX_LENGTH)

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

        # --- where the row LANDS ----------------------------------------------
        # The append names the file after the writer's session, so a verb filing
        # no session puts its rows in a file of its own beside the one every
        # other command-line verb of that session writes. Driven end to end
        # against a real append in the task verb's shape: the split is only
        # visible where writers of one session are compared, and a case reading
        # this command's row alone would pass either way.
        joined = repos.make()
        _widen(joined)
        sid = "5cf0d3a2-1111-4c2b-9a77-9f0c1b2d3e4f"
        held = _set_session(sid)
        try:
            joined_code, _joined_text = _run(joined)
            joined_cfg = _journal_io.load_config(joined["root"])
            _task_verb_row(joined, joined_cfg)
            joined_writers = _writers(joined, joined_cfg)
            joined_rows = _journal_io.read_all(joined["root"])
        finally:
            _set_session(held)
        joined_actions = sorted(r.get("action") for r in joined_rows)
        joined_files = sorted(set(r.get("_file") for r in joined_rows))
        check("cmi19 an index commit and a structural edit made by the same "
              "session land in the SAME journal file, named for that session - "
              "a trail whose location depends on which verb wrote the row is one "
              "nobody reconstructs by hand: %r / %r / %r"
              % (joined_writers, joined_files, joined_actions),
              joined_code == 0
              and joined_writers == [_journal_io.writer_id({"sessionId": sid})]
              and len(joined_files) == 1
              and joined_actions == sorted([_invariants.ACTION_INDEX_COMMITTED,
                                            "task.add"]))

        check("cmi19b ...and the row itself records the session, which is what "
              "the file name is derived FROM - `session_index` is the only "
              "reader that can group a session's files, and it reads the rows: "
              "%r" % ([r.get("actor", {}).get("sessionId") for r in joined_rows],),
              [r.get("actor", {}).get("sessionId") for r in joined_rows]
              == [sid, sid])

        # A WRITER WITH NO SESSION IS THE PAIR, and it is the half a widened key
        # breaks: this verb runs from Bash and Bash is not always a session, so
        # the token that names the CHECKOUT has to stay reachable. Inventing a
        # session id here would put a machine's rows in a file that reads as
        # somebody's session for ever - the name is the chain's genesis seed and
        # cannot be corrected afterwards.
        lone = repos.make()
        _widen(lone)
        held = _set_session(None)
        try:
            lone_code, _lone_text = _run(lone)
            lone_cfg = _journal_io.load_config(lone["root"])
            lone_writers = _writers(lone, lone_cfg)
            lone_token = _journal_io.writer_token(lone["root"], lone_cfg)
        finally:
            _set_session(held)
        check("cmi20 ...and with no session named at all the row lands in the "
              "file named for the CHECKOUT's writer token, which is the fallback "
              "the session path may never displace: %r / %r"
              % (lone_writers, lone_token),
              lone_code == 0 and bool(lone_token)
              and lone_writers == [lone_token])

        # --- the index is committed only where the committed shards support it --
        # `/audit:task add` writes a task into the shard and its files into the
        # index. Committing the index first records a plan whose fileIndex names a
        # task no committed shard holds - a commit that fails validation.
        fx = repos.make()
        shard = _mio.read_json(fx["shard"])
        shard["tasks"].append(dict(shard["tasks"][0], id="P1.3", status="pending",
                                   files=["src/new.py"]))
        TI._write_json(fx["shard"], shard)
        index = _mio.read_json(fx["manifest"])
        index["fileIndex"]["src/new.py"] = ["P1.3"]
        TI._write_json(fx["manifest"], index)
        before = _head(fx)
        code, text = _run(fx)
        check("cmi21 an index naming a task its COMMITTED shard does not hold yet is "
              "refused, nothing is committed, and the refusal names the task and the "
              "shard to commit first: %r / %r" % (code, text),
              code != 0 and _head(fx) == before and "P1.3" in text
              and SHARD_REL in text and _staged(fx) == [])
        TI._git(fx["root"], "add", "--", SHARD_REL)
        TI._git(fx["root"], "commit", "-q", "-m", "the shard first")
        code, text = _run(fx)
        lone = _carried(fx, _head(fx))
        trail = [p for p in lone if p.startswith("docs/audit/journal/")]
        check("cmi22 SECOND DIRECTION: once the shard is committed the same index "
              "commits, alone but for the journal file holding its own row: "
              "%r / %r / %r" % (code, text, lone),
              code == 0 and sorted(lone) == sorted([INDEX_REL] + trail)
              and len(trail) == 1 and trail[0] in _row_files(fx))

        # THE SUBJECT CHANGED AND HISTORY DID NOT: a commit made under the
        # subject this class used to write is found by the same search as one
        # made now, because what finds the class is its scope.
        old_subject = ("%s(%s): %s %s - the shared index, carried alone so no "
                       "phase's work rides with it"
                       % (M.COMMIT_TYPE, M.COMMIT_SCOPE, M.SUBJECT_LEAD, PHASE))
        TI._git(fx["root"], "commit", "-q", "--allow-empty", "-m", old_subject)
        opening = "%s(%s): " % (M.COMMIT_TYPE, M.COMMIT_SCOPE)
        by_scope = TI._git(fx["root"], "log", "--format=%s", "--fixed-strings",
                           "--grep=" + opening).splitlines()
        check("cmi40 the index commit's subject now names the row it carries, "
              "and a commit under the OLD subject is still found by the search "
              "that finds this class - the scope, which did not move: %r"
              % (by_scope,),
              old_subject in by_scope
              and any(line.endswith(" - " + M.DEFAULT_SUBJECT)
                      for line in by_scope)
              and "row naming it" in M.DEFAULT_SUBJECT)

        fx = repos.make()
        index = _mio.read_json(fx["manifest"])
        index["phases"].append({"id": "P3", "title": "new phase",
                                "shard": "phases/P3.json"})
        TI._write_json(fx["manifest"], index)
        TI._write_json(os.path.join(os.path.dirname(fx["manifest"]), "phases",
                                    "P3.json"),
                       {"id": "P3", "title": "new phase", "status": "pending",
                        "tasks": []})
        before = _head(fx)
        code, text = _run(fx)
        check("cmi23 ...and so is an index whose new phase stub points at a shard "
              "that is not committed: %r / %r" % (code, text),
              code != 0 and _head(fx) == before and "P3" in text
              and "phases/P3.json" in text)

        fx = repos.make()
        _widen(fx)
        code, text = _run(fx)
        check("cmi24 CONTROL: widening an EXISTING task's scope still commits the "
              "index alone - the task is in the committed shard, only its files "
              "are not, which is the pairing sign-off settles: %r" % (text,),
              code == 0)

        fx = repos.make()
        index = _mio.read_json(fx["manifest"])
        index["fileIndex"]["src/orphan.py"] = ["P9.9"]
        TI._write_json(fx["manifest"], index)
        code, text = _run(fx)
        # The check asks git only about shards that CHANGED: a stub whose shard is
        # the committed one needs no `git show`, and a plan's phase count must not
        # set the lock-hold time of every index commit.
        fx = repos.make()
        index = _mio.read_json(fx["manifest"])
        index["meta"]["title"] = "only the title moved"
        TI._write_json(fx["manifest"], index)
        shows = []
        real_git = M._scoped_commit.run_git

        def counting(root, argv):
            if argv[:1] == ["show"]:
                shows.append(argv)
            return real_git(root, argv)
        M._scoped_commit.run_git = counting
        try:
            code, text = _run(fx)
        finally:
            M._scoped_commit.run_git = real_git
        # The fixture leaves P1's shard modified and P2's committed as it is.
        check("cmi26 git is asked to show a shard at HEAD only where that shard "
              "CHANGED - P1's, which the fixture left modified, and never P2's, whose "
              "committed copy is the working one: the cost is the change's, not the "
              "plan's: %r / %r" % (shows, text),
              code == 0 and shows == [["show", "HEAD:%s" % SHARD_REL]])

        check("cmi25 ...and an index naming a task NO shard holds, committed or not, "
              "is not this command's to refuse - it is not ahead of a shard, it is "
              "dangling, and the validator reports that: %r" % (text,),
              code == 0 and "P9.9" not in text)
        _staging_cases(check, repos)
    finally:
        repos.close()


# --- the shared staging, driven through this command ---------------------------
def _staging_cases(check, repos):
    # A RENAME INTO THE INDEX PATH FROM OUTSIDE THE ALLOW-LIST. HEAD must not
    # hold the index for git to call it a rename, so the fixture commits its
    # removal first.
    fx = repos.make()
    root = fx["root"]
    draft = "docs/audit/draft.json"
    # Committed from the index, not with a pathspec: a pathspec commit reads the
    # working tree, where the file still is, and records nothing.
    TI._git(root, "rm", "-q", "--cached", "--", INDEX_REL)
    TI._git(root, "commit", "-q", "-m", "fixture: the index not yet committed")
    os.rename(os.path.join(root, INDEX_REL), os.path.join(root, draft))
    TI._git(root, "add", "--", draft)
    TI._git(root, "commit", "-q", "-m", "fixture: a draft", "--", draft)
    TI._git(root, "mv", draft, INDEX_REL)
    before = _head(fx)
    code, text = _run(fx)
    check("cmi27 a staged rename from OUTSIDE the allow-list onto the index path "
          "is refused and its SOURCE named - with rename detection on, the index "
          "lists only the new name, which is allowed: %r / %r" % (code, text),
          code == 1 and draft in text and _head(fx) == before)

    # A COMMIT A HOOK REFUSES, AFTER STAGING.
    fx = repos.make()
    _widen(fx)
    hooks = os.path.join(fx["root"], ".git", "hooks")
    if not os.path.isdir(hooks):
        os.makedirs(hooks)
    with io.open(os.path.join(hooks, "pre-commit"), "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nexit 1\n")
    os.chmod(os.path.join(hooks, "pre-commit"), 0o755)
    TI._git(fx["root"], "config", "core.hooksPath", hooks)
    found = TI._git(fx["root"], "ls-files", "-s")
    before = _head(fx)
    code, text = _run(fx)
    check("cmi28 a commit refused AFTER staging leaves the index exactly as it "
          "was found and says so - it used to leave the index staged: %r / %r"
          % (code, text),
          code == 1 and _head(fx) == before
          and TI._git(fx["root"], "ls-files", "-s") == found
          and _scoped.INDEX_RESTORED in text)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_commit_manifest_index.py --selftest\n")
    raise SystemExit(2)
