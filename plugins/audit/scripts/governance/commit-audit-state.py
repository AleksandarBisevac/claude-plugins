#!/usr/bin/env python3
"""Commit any uncommitted audit state, or say there is none.

WHY THIS EXISTS. Test evidence is written beside the manifest and is meant to be
COMMITTED -- it is the record somebody hands to a client. But the orchestrator
commits on success and only on success: a red gate leaves `status =
"in_progress"` and explicitly does NOT commit (`reference/orchestrator.md`
step 4), an infrastructure failure takes a STOP path that commits nothing either,
and the sign-off commit happens once every gate is green. So the rows that say
`failed`, `gate-mutated`, `timed-out`, `cancelled` and `could-not-run` -- exactly
the history the evidence file exists to preserve -- can sit in a working tree for
ever. `gate-mutated` belongs on that list for a reason of its own: the run passed
every command, so nothing about the WORK stopped the commit, and what did is the
gate having rewritten the files it was grading -- which the orchestrator answers by
reverting and re-running, leaving the row that recorded it behind.

THE GAP IS NARROWER THAN "EVERY FAILURE", AND SAYING SO IS THE POINT. A task
commit stages the evidence directory, so it carries every row written since the
last commit: a run that fails at attempt one and succeeds at attempt two is
already durable, its failure included. What is NOT durable is a run whose task or
phase never subsequently commits at all. This command is for that case, and it is
safe to call when there is no such case -- a spurious call is a no-op that says
so.

WHAT IT STAGES, AND WHAT IT MUST NEVER STAGE. Three paths: the phase's manifest
file (the shard when sharded, else the single manifest), the journal directory
and the evidence directory. The task's `files` are NOT on that list and cannot be
put on it. That exclusion is the whole design -- a failed task's code is not
committed, and a verb that could sweep it in on the way to preserving a record
would be a commit nobody reviewed, made on the one path where nobody was going to
look.

HOW THE EXCLUSION IS ENFORCED RATHER THAN INTENDED. Paths are staged
EXPLICITLY, each by what git holds for it and never `git add -A`, the index is
read back and compared against the same allow-list BEFORE anything is
committed, and the commit carries the list as its pathspec - all of it
`_scoped_commit.stage_and_commit`, which also puts the index back as it was
found on any refusal after staging. The index is also read BEFORE staging: work
somebody else had already staged would otherwise ride along, and refusing
before touching anything leaves no half-made state to unpick. `_invariants`'
`audit-state-scope` check then re-derives the same rule from git after the fact,
so the commits this makes are graded by something that did not make them.

A DIRECTORY OUTSIDE `gitRoot` IS DEGRADED PAST, NOT FAILED ON -- the same
sentence step 4c already writes for the journal: if it is outside the repository
it cannot be committed, so proceed without it and say which one went missing.

NEVER AN EMPTY COMMIT. Nothing staged means no commit and a line saying there was
nothing to commit, because a stream of empty commits is how a record stops being
read.

THE ROW NAMING THE COMMIT IS INSIDE IT. The row is written first, keyed by a
nonce the commit message carries as its `Audit-Row` trailer, and the journal
directory it lands in is on the allow-list - `_scoped_commit.commit_with_rows`.
So a clone holding the commit holds the row, `audit-state-scope` finds the commit
from the row by that trailer, and the run leaves no trail behind it.

WHICH IS WHY A DIRTY JOURNAL ALONE IS WORK TO DO. When the row landed after the
commit, committing a journal-only change would have needed a row of its own,
outside that commit, and never stopped; a row inside its commit terminates, so
journal rows another writer left - a hook, an `/audit:task` verb - are carried
like the other two records. A second run finds nothing uncommitted and says so.

Usage:
  commit-audit-state.py <manifest> <phaseId> [--project DIR] [--subject TEXT]
                        [--json]

Exit codes:
  0  it ran - it committed, or there was nothing uncommitted and it said which
  1  it could not - git refused, or the index already held work this commit may
     not carry
  2  usage error - the manifest will not load, or there is no such phase
"""
import argparse
import json
import os
import shutil
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

import _evidence_io  # noqa: E402  (where the evidence record lives)
import _invariants  # noqa: E402  (the phase lookup, the git root, the action name)
import _journal_io  # noqa: E402  (where the trail lives, and the append)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _scoped_commit  # noqa: E402  (the staging discipline and the answer shape, shared with the index commit)

E_OK, E_FAIL, E_USAGE = 0, 1, 2

# A FIXED LITERAL SEPARATES THIS FROM A TASK COMMIT, and it is not decoration. A
# task commit's type comes from `meta.commit.type`, which a manifest may set to
# anything -- so the separator has to be something nothing in the manifest can
# reach, and `git log --grep audit-state` then tells the two apart for ever. A
# reader who meets one of these in a log has to be able to tell, without opening
# it, that it carries no implementation.
#
# THE LITERAL IS THE SCOPE, NOT THE TYPE, and that is a reversal of the
# original spelling with its trigger named. `audit-state(P1):` put the literal in
# the TYPE position, which made it an unknown conventional-commit type -- and a
# repository with husky+commitlint rejects the commit AFTER this script has staged
# the files, leaving the caller to finish by hand. Reported from a live run; the
# first decision never weighed it. `chore` is in commitlint's default type-enum so
# the commit lands, and the scope is where `meta.commit.type` cannot reach, since
# a task commit's scope is its phase id. Both properties kept, one spelling
# changed. The phase id moves into the subject, where it is still greppable.
COMMIT_TYPE = "chore"
COMMIT_SCOPE = "audit-state"
DEFAULT_SUBJECT = "the record of a run, without the work it ran on"

# THE SUBJECT OPENS WITH A FIXED LOWERCASE WORD, AND THE STANDARD IT MEETS
# IS THE WHOLE OF commitlint's DEFAULT `subject-case` RULE. The fix above moved
# the literal into the scope so the default `type-enum` would take the commit,
# and the
# very next default rule refused it anyway: `subject-case` forbids a subject that
# IS sentence-case, start-case, pascal-case or upper-case, and `P6 - the record of
# a run` is sentence-case exactly -- commitlint asks whether
# `upperFirst(subject.toLowerCase())` equals the subject, and with the phase id
# leading and nothing else capitalised, it does. Reported from the field a second
# time with the same consequence as the first: the record stayed staged and
# somebody committed it by hand.
#
# SO THE PROPERTY IS AIMED AT EVERY ONE OF THOSE CASES AND NOT AT THE ONE THAT BIT,
# because meeting the defaults a rule at a time is what made this a second visit.
# Each of them is COMPUTED by a transform that capitalises the subject's first
# character -- `toUpperCase()`, `upperFirst()` of the lowercased string,
# `upperFirst()` of the camel-cased one, and lodash `startCase`, which capitalises
# every word including the first -- so a subject whose first character is a
# lowercase letter cannot equal any of them, whatever else it contains.
#
# THE WORD IS THIS COMMAND'S AND NOT THE CALLER'S, which is what makes that
# unconditional: it sits ahead of `--subject`, so no subject anybody passes can put
# a capital, or a phase id, back into first position. It is also NOT read from
# `meta.commit` -- see `commit_message()` for why the manifest is the wrong place
# to ask.
#
# `phase` RATHER THAN A NEW WORD, because the orchestrator's own subjects already
# open with a lowercase one: `phase sign-off ...` at sign-off and `audit - ...` on
# a task commit (`reference/orchestrator.md`, *Phase sign-off* and *Execute the
# task*). That is why neither of those was ever bitten by this rule, and it makes
# the record read like the commits either side of it.
#
# AND THE PHASE ID STAYS UPPERCASE, one word further in. Lowercasing it would
# spell a phase id differently here from every other surface in the product; the id
# was never what the rule objected to, its POSITION was.
SUBJECT_LEAD = "phase"

# What every line this command prints is stamped with. A constant because the
# renderer is `_scoped_commit`'s and takes it as an argument -- the lines are
# shared with the index commit and the NAME is the only thing that may differ.
PREFIX = "[commit-audit-state]"

# The three things this commit may carry, each with the word its line is reported
# under. Ordered as the commit stages them, which is also the order step 4c names
# them in: the plan, then the trail, then the evidence.
MANIFEST_LABEL = "the phase's manifest file"
JOURNAL_LABEL = "the journal directory"
EVIDENCE_LABEL = "the evidence directory"


# --- git ----------------------------------------------------------------------
# ALIASES, NOT COPIES, and `_deps` attributes the edge to the import above. Each
# is a step of the discipline a committing command owes -- the answer shape, the
# working-tree read that decides before staging, the index read that refuses
# before it -- and `commit-manifest-index.py` owes the
# same one over a different list. `_scoped_commit` owns them; a second spelling
# here is how one of the two commands comes to permit a path the other refuses,
# and the names are kept so a reader who knows this file still finds them here.
_answer = _scoped_commit.answer
uncommitted = _scoped_commit.uncommitted
foreign_staged = _scoped_commit.foreign_staged


# --- what this commit may carry -----------------------------------------------
def _rel_inside(path, git_root):
    """`path` relative to `git_root`, or None when it is outside it.

    `_invariants._rel` rather than a second expression of it, for the reason that
    module states: a manifest or a record living outside the git root cannot be
    committed at all, and a caller that treated the escape as a `../..` path would
    compare it against a `git show` listing that can never contain it. Two answers
    to "is this inside the repository" is how a guard comes to allow a path its
    reader forbids.
    """
    return _invariants._rel(path, git_root)


def stage_targets(manifest, phase, manifest_path, project, git_root, config=None):
    """`{"paths", "journal", "skipped"}` - the allow-list for THIS phase, resolved.

    `paths` are git-root-relative and exist on disk; `skipped` carries one
    sentence per thing that could not be reached, naming which one it was and
    why. A skip is REPORTED and never silent: "the evidence directory was
    outside the repository" and "the evidence directory does not exist" leave the
    same commit behind, and only one of them is a problem somebody should fix.

    A JOURNAL DIRECTORY THAT DOES NOT EXIST YET IS NOT A SKIP while the journal
    is on: the row this commit writes creates it, and `commit_with_rows` carries
    what it created. Said as missing, the line would be false on the one run
    that makes it true.

    THE LIST IS THE SAFETY PROPERTY. Nothing downstream widens it - the staging
    call takes these paths and the index verification takes this same list - so a
    file the task owns has no route into the commit even if it is sitting in the
    working tree beside them.
    """
    config = _journal_io.load_config(project) if config is None else config
    _index_abs, phase_file_abs = _invariants.manifest_files(manifest_path, phase)
    wanted = [(MANIFEST_LABEL, phase_file_abs),
              (JOURNAL_LABEL, _journal_io.journal_dir(project, config)),
              (EVIDENCE_LABEL, _evidence_io.evidence_dir(project, config))]
    paths, skipped = [], []
    for label, absolute in wanted:
        rel = _rel_inside(absolute, git_root)
        if rel is None:
            skipped.append("%s lives outside the git root, so it cannot be "
                           "committed - proceeding without it" % (label,))
            continue
        if not os.path.exists(absolute):
            if not (label == JOURNAL_LABEL and _journal_io.enabled(config)):
                skipped.append("%s does not exist yet, so there is nothing of it "
                               "to stage" % (label,))
            continue
        if rel not in paths:
            paths.append(rel)
    # `kinds` is how each path is staged, `_scoped_commit.classify`'s answer;
    # every path here exists on disk, which is what the loop above required.
    kinds = _scoped_commit.classify(git_root, [(rel, True) for rel in paths])
    # A directory `classify` leaves unclassified holds no file git would
    # commit, and as a pathspec it would fail the whole commit.
    for rel in [p for p in paths if p not in kinds]:
        skipped.append("%s is a directory holding no file git would commit, so "
                       "there is nothing of it to stage" % (rel,))
    paths = [p for p in paths if p in kinds]
    return {"paths": paths, "skipped": skipped, "kinds": kinds}


def _foreign_after_staging(foreign):
    """The sentence for a path that arrived THROUGH the staging, naming it."""
    return ("staging produced paths outside the allow-list (%s), so nothing was "
            "committed" % (", ".join(foreign),))


# One predicate, one signature, and it is `_invariants._under` rather than a
# second expression of it. The rule -- a path IS the entry or sits inside it, with
# the separator, so `evidence-notes/` is not inside `evidence/` -- has to be the
# same on both sides of this pair: the writer decides what may be staged and the
# checker decides what was allowed, and two spellings is how a guard comes to
# permit a path its reader forbids.
_under = _invariants._under
_under_any = _scoped_commit.under_any


# --- the commit ---------------------------------------------------------------
def commit_message(phase_id, subject, coauthor):
    """The message paragraphs: a conventional subject, and the co-author trailer.

    A LIST RATHER THAN ONE STRING, because that is how it reaches git: one `-m`
    per paragraph, so the trailer is a trailer and not a second sentence of the
    subject line.

    `SUBJECT_LEAD` COMES FIRST AND NOTHING MAY BE PUT AHEAD OF IT - that position
    is the whole of the fixed-lowercase-subject repair above, and the constant
    says why.

    AND THE SHAPE IS UNCONDITIONAL, deliberately NOT read from `meta.commit`. The
    manifest cannot answer the question: that block holds `{type, coauthor}` - a
    default conventional TYPE and a trailer - and records nothing about which
    commitlint rules a repository configures, so a writer consulting it would be
    guessing from a field about something else. It could not answer it even in
    principle: husky is installed after `/audit:init` as often as before it, and a
    manifest may be written by hand. And there is nothing to gate - a subject that
    satisfies commitlint's defaults is a perfectly good subject where nothing
    enforces them, so the alternative is a second shape that runs only on the
    machines nobody tests on. Reading a field to decide whether to be correct is
    also what the scope-not-type reversal above spent its removal on: the
    separating literal is fixed
    precisely so a manifest cannot move this commit's spelling.

    THE CALLER'S HALF IS BOUNDED BY THE SAME RULE SET, through the bound its
    sibling command shares with this one. The header this builds has to survive
    commitlint for the reason the type and the lead already do - a repository that
    refuses it does so AFTER the files are staged - and the length is the one of
    those rules whose remaining budget a caller, not this command, spends.
    """
    lines = [_scoped_commit.fitted_header(
        "%s(%s): %s %s - " % (COMMIT_TYPE, COMMIT_SCOPE, SUBJECT_LEAD, phase_id),
        subject or DEFAULT_SUBJECT)]
    if coauthor:
        lines.append(str(coauthor))
    return lines


def _phase_id(phase):
    return str((phase or {}).get("id"))


def _coauthor(manifest):
    block = ((manifest or {}).get("meta") or {}).get("commit")
    value = block.get("coauthor") if isinstance(block, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def record_row(project, phase_id, nonce, config=None):
    """Anchor the commit in the trail. Returns the file the row landed in, or False.

    WRITTEN BEFORE THE COMMIT AND CARRIED BY IT, so it names the commit by
    `nonce` - the value of the commit's `Audit-Row` trailer - and not by a SHA,
    which does not exist yet and could not be inside the commit it hashes.

    THE TARGET IS THE EVIDENCE DIRECTORY AND DELIBERATELY NOT THE PHASE'S MANIFEST
    FILE. `_invariants._recorded_states` reads every row naming that file as a
    WRITE to it and counts the ones whose bytes no commit preserved; this row
    records a COMMIT, not an edit, and pointing it at the shard would inflate that
    denominator and manufacture a gap in `manifest-revalidated` out of a state
    that was in fact preserved.

    REDACTED THE WAY EVERY COMMITTED ROW IS, through `repo_relative_or_token`: an
    evidence directory configured outside the repository would otherwise write an
    absolute path -- somebody's home directory -- into a file that goes to a
    client.

    FAIL-SOFT, `_journal_io.append`'s own contract: a commit that HAPPENED must
    not be reported as not having happened because the trail could not be written.

    `append_from_cli`, NOT `append`: this command is run from Bash, so its
    append put the journal file into `git status` and `guard-bash-writes` had
    nothing claiming it -- the next shell command drew a notice about a row this
    plugin had just written, with `audit-journal.py verify` reporting the chain
    clean behind it.
    """
    config = _journal_io.load_config(project) if config is None else config
    target = _journal_io.repo_relative_or_token(
        project, _evidence_io.evidence_dir(project, config))
    return _journal_io.append_from_cli(project, {
        "action": _invariants.ACTION_STATE_COMMITTED,
        "actor": {"via": "commit-audit-state"},
        "target": target,
        "summary": "audit state for %s committed as the commit carrying "
                   "`%s` - the record of a run with none of its work"
                   % (phase_id, _scoped_commit.row_trailer(nonce)),
        "details": {_invariants.NONCE_KEY: nonce, "phaseId": str(phase_id)},
    }, config=config)


# The two ways this command does nothing, worded APART because they are different
# states of the world and a reader acts on them differently. Folded into one line
# they would both read as "all clear", and the second one is the state a repository
# sits in permanently by design.
NOTHING_UNCOMMITTED = ("nothing uncommitted: the phase's manifest file, the "
                       "journal and the evidence are already in git. No commit "
                       "was made, because an empty one records nothing and "
                       "buries the ones that do.")
def render(answer, out=print):
    """Print what happened, in the order somebody reading a terminal needs it.

    The lines are `_scoped_commit`'s, because the index commit prints the same
    ones under a different name: two verbs reporting a refusal in two shapes
    teach a reader that the shape means something, and here it does not.
    """
    return _scoped_commit.render(answer, PREFIX, out=out)


# --- cli ----------------------------------------------------------------------
def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="commit-audit-state.py", add_help=True, allow_abbrev=False,
        description="Commit any uncommitted audit state for one phase, or say "
                    "there is none.")
    parser.add_argument("manifest")
    parser.add_argument("phase")
    parser.add_argument("--project", default=".",
                        help="the directory holding .claude/ and the records "
                             "(default: the current directory)")
    parser.add_argument("--subject", default=None,
                        help="the commit subject after the conventional prefix; "
                             "say what the run was, not what this script does")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def commit_state(manifest, phase, manifest_path, project, git_root, subject=None,
                 config=None):
    """`(exitCode, answer)` - do the thing and say what happened. Prints nothing.

    A PAIR RATHER THAN AN EXIT CODE, for `run-test-gate.run_gate`'s reason: a
    function that returned only a verdict could not be exercised without a
    terminal around it, and every branch below is a branch a case has to reach.
    """
    config = _journal_io.load_config(project) if config is None else config
    targets = stage_targets(manifest, phase, manifest_path, project, git_root,
                            config=config)
    allowed, skipped = targets["paths"], targets["skipped"]

    # BEFORE STAGING, so a refusal leaves the index exactly as it was found. Work
    # somebody else had already staged would otherwise be swept into a commit
    # whose entire promise is that it carries none.
    foreign, why = foreign_staged(git_root, allowed)
    if why:
        return E_FAIL, _answer(skipped, refused=why)
    if foreign:
        return E_FAIL, _answer(
            skipped, foreign=foreign,
            refused="the index already holds paths this commit may not carry. An "
                    "audit-state commit stages the record and never the work, so "
                    "it refuses rather than sweeping them in - unstage them and "
                    "re-run")
    # AHEAD OF THE DO-NOTHING ANSWERS: `git status` does not list an ignored
    # file, so an ignored record would otherwise read as "nothing uncommitted".
    ignored = _scoped_commit.ignored_records(targets["kinds"])
    if ignored:
        return E_FAIL, _answer(skipped, refused=ignored)
    if not allowed:
        return E_OK, _answer(skipped, quiet=NOTHING_UNCOMMITTED)

    # DECIDED BEFORE ANYTHING IS STAGED. Both do-nothing answers are reached from
    # here with the index untouched, so declining costs nothing and undoes nothing.
    pending, why = uncommitted(git_root, allowed)
    if why:
        return E_FAIL, _answer(skipped, refused=why)
    if not pending:
        return E_OK, _answer(skipped, quiet=NOTHING_UNCOMMITTED)

    # STAGED, READ BACK AND COMMITTED BY `_scoped_commit.commit_with_rows`, the
    # one sequence every scoped commit shares: the row naming the commit
    # written first and carried, each path staged by what git holds for it, the
    # index read back against this same list, a commit with the list as its
    # pathspec, the index put back as it was found on any refusal after staging,
    # and the row withdrawn when no commit was made. The read-back is the only
    # check that can see a path that arrived through one of these directories
    # rather than past them.
    #
    # NO SECOND EMPTY-INDEX GUARD. `pending` above already answered "is there
    # anything to commit"; `git commit` refuses an empty index on its own, and
    # that refusal is reported like any other.
    phase_id = _phase_id(phase)
    done = _scoped_commit.commit_with_rows(
        git_root, allowed, targets["kinds"],
        commit_message(phase_id, subject, _coauthor(manifest)),
        _foreign_after_staging,
        lambda nonce: ([record_row(project, phase_id, nonce, config=config)],
                       ""),
        lambda nonce, why: _scoped_commit.withdraw(
            project, config, nonce, "commit-audit-state",
            {"phaseId": phase_id}, why))
    staged = done["staged"]
    if not done["committed"]:
        return E_FAIL, _answer(skipped, staged=staged, foreign=done["foreign"],
                               refused=done["refused"], done=done)
    sha = done["sha"]
    if sha and done["refused"]:
        # Committed on a HEAD that moved underneath: reported, never undone.
        return E_FAIL, _answer(skipped, committed=True, commit=sha,
                               staged=staged, refused=done["refused"],
                               journalled=done["journalled"], done=done)
    if not sha:
        # The commit exists and this process cannot name it. A failure rather
        # than a success with a blank field: nothing downstream can be handed a
        # SHA, and the row inside the commit reaches it only by its trailer.
        return E_FAIL, _answer(
            skipped, committed=True, staged=staged,
            journalled=done["journalled"], done=done,
            refused="%s; the row inside it names it by `%s`"
                    % (done["refused"], _scoped_commit.row_trailer(
                        done["nonce"]) if done["nonce"] else "nothing"))
    return E_OK, _answer(skipped, committed=True, commit=sha, staged=staged,
                         journalled=done["journalled"], done=done)


def main(argv, out=print):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK

    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n"
                         % (args.manifest, exc))
        return E_USAGE
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: manifest %s is not a JSON object\n"
                         % (args.manifest,))
        return E_USAGE
    phase = _invariants.phase_of(manifest, args.phase)
    if phase is None:
        known = [str(p.get("id")) for p in (manifest.get("phases") or [])
                 if isinstance(p, dict)]
        sys.stderr.write("ERROR: no phase %r in %s (have: %s)\n"
                         % (args.phase, args.manifest, ", ".join(known)))
        return E_USAGE

    project = os.path.abspath(args.project)
    git_root = _invariants.git_root_for(manifest, project)
    if not shutil.which("git"):
        out("%s git is not on PATH, so audit state cannot be committed at all. "
            "Nothing was staged." % (PREFIX,))
        return E_FAIL

    code, answer = commit_state(manifest, phase, args.manifest, project,
                                git_root, subject=args.subject)
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        render(answer, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("commit-audit-state.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_commit_audit_state.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
