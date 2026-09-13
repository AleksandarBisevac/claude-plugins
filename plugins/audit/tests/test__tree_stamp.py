#!/usr/bin/env python3
"""
The cases for `_tree_stamp.py` — the tree identity, and the three-word comparison.

The three identity fields themselves were `run-test-gate.py`'s before they were
this module's, and `test_run_test_gate.py` still drives them where they are
recorded: through a real gate run, against a real repository. What is asserted
here is what the MOVE and the new question added.

- **A null never compares equal to a null.** `field_state` is where the whole
  design lives or dies: `None == None` is True in Python and false in English,
  and reading it the Python way is exactly how a directory git could not describe
  comes back reported as a directory that had not changed. Both orders and the
  both-null case are separate cases, because a version that special-cased one
  side passes the other.
- **A stale answer names the field.** Three fields, three repairs. The cases
  change one thing at a time and assert both halves — the field that moved AND
  the fields that held — because asserting only the mover passes against a
  comparison that reports everything as moved.
- **The inherited limit is pinned, not described.** `DIRTY_LIMIT` says the digest
  records which paths were dirty and never their contents, and `tsl2` is the case
  that rewrites an already-dirty file outside the declared scope and watches
  nothing move. A limit that is only written down is a limit nobody has checked.
- **Moved outranks unanswerable.** A tree with one field moved and another
  unreadable HAS moved, and reporting that as ungradeable would hide a fact
  already in hand.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _tree_stamp as M                            # noqa: E402


def _git(repo, *args):
    """A git command that must succeed, with the identity a fresh runner lacks.

    `-c user.*` on every invocation rather than a `git config` pass: a CI runner
    has no global identity, and a fixture that depends on the operator having one
    is a fixture that is green here and red there."""
    subprocess.run(["git", "-C", repo,
                    "-c", "user.email=fixture@example.invalid",
                    "-c", "user.name=fixture",
                    "-c", "commit.gpgsign=false"] + list(args),
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def _write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def _seeded_repo(prefix):
    """A repository with one commit in it, so HEAD is a sha and not an unborn ref."""
    root = _harness.fixture_root(prefix)
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.join(root, "src"))
    _write(os.path.join(root, "src", "mine.py"), "v = 1\n")
    _write(os.path.join(root, "src", "theirs.py"), "w = 1\n")
    _git(root, "add", "src/mine.py", "src/theirs.py")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _states(result):
    """`{field: word}` off a `compare()` result - the shape every case reads."""
    return dict((entry["field"], entry["state"]) for entry in result["fields"])


# --- the token: written, carried in prose, read back --------------------------
def _token_cases(check):
    check("tsk1 `declared_scope` drops the blanks and the non-strings, "
          "deduplicates and sorts - the SAME narrowing `scope_digest` applies, "
          "because a stamp whose stored scope and whose digest disagreed about "
          "which files were in play could not be re-derived: %r"
          % (M.declared_scope(["b.py", "a.py", "b.py", "  ", "", None, 7]),),
          M.declared_scope(["b.py", "a.py", "b.py", "  ", "", None, 7])
          == ["a.py", "b.py"])

    stamp = {"v": M.STAMP_VERSION, "scope": ["a.py"], "head": "abc1234",
             "scopeDigest": "sha256:aa", "dirtyDigest": "sha256:bb"}
    line = M.format_stamp(stamp)
    check("tsk2 the stamp is ONE line - a pretty-printed block loses its "
          "indentation in a quoted reply and stops parsing, and this token has "
          "to survive being pasted into text somebody else wrote: %r" % (line,),
          "\n" not in line and line.startswith(M.STAMP_TOKEN))
    back, problem = M.parse_stamp(
        "gates green, counts 219/219.\n%s\nsigned off." % (line,))
    check("tsk3 ...and it comes back out of the middle of a paragraph unchanged, "
          "which is the only place a stamp ever lives: %r / %r" % (back, problem),
          problem is None and back == stamp)

    none_stamp, none_problem = M.parse_stamp("gates green, nothing else.")
    check("tsk4 text carrying no token is a REFUSAL that names the token, not an "
          "empty stamp that would then grade as `current` against anything: %r"
          % (none_problem,),
          none_stamp is None and M.STAMP_TOKEN in (none_problem or ""))

    two_stamp, two_problem = M.parse_stamp("%s\nand later\n%s" % (line, line))
    check("tsk5 TWO tokens in one document is a refusal and not a choice. First "
          "or last would be this module guessing which verification the reader "
          "meant, and a wrong guess grades a claim against a tree it was never "
          "taken on: %r" % (two_problem,),
          two_stamp is None and "2 lines" in (two_problem or ""))

    future = dict(stamp)
    future["v"] = M.STAMP_VERSION + 1
    fut_stamp, fut_problem = M.parse_stamp(M.format_stamp(future))
    check("tsk6 a stamp from a spelling this code cannot read is refused rather "
          "than read optimistically - reading it hopefully is how "
          "`unestablished` quietly becomes `current`: %r" % (fut_problem,),
          fut_stamp is None and str(M.STAMP_VERSION) in (fut_problem or ""))

    bad_json = M.parse_stamp("%s not json at all" % (M.STAMP_TOKEN,))
    bad_root = M.parse_stamp("%s [1, 2]" % (M.STAMP_TOKEN,))
    no_scope = dict(stamp)
    no_scope["scope"] = "a.py"
    bad_scope = M.parse_stamp(M.format_stamp(no_scope))
    bad_field = dict(stamp)
    bad_field["head"] = 7
    bad_head = M.parse_stamp(M.format_stamp(bad_field))
    check("tsk7 every malformed shape is refused by its own sentence, because "
          "'this stamp is unreadable' and 'this stamp says the tree moved' are "
          "different instructions to the reader: %r"
          % ([p for _s, p in (bad_json, bad_root, bad_scope, bad_head)],),
          all(s is None and p for s, p in
              (bad_json, bad_root, bad_scope, bad_head)))


# --- a field's word, which is where the whole design lives --------------------
def _field_cases(check):
    check("tsf1 equal is `agrees` and differing is `moved` - the ordinary pair, "
          "asserted so the cases below are not the only thing keeping this "
          "function honest",
          M.field_state("head", "aaa", "aaa", True) == M.AGREES
          and M.field_state("head", "aaa", "bbb", True) == M.MOVED)

    was_null = M.field_state("head", None, "aaa", True)
    now_null = M.field_state("head", "aaa", None, True)
    both_null = M.field_state("head", None, None, True)
    check("tsf2 A NULL ON EITHER SIDE IS `unanswerable`, NEVER `agrees`, and all "
          "three orders are cases because a version special-casing one side "
          "passes the other. Two absent answers are two absences, not an "
          "agreement - `None == None` is True in Python and false in English: "
          "%r / %r / %r" % (was_null, now_null, both_null),
          (was_null, now_null, both_null)
          == (M.UNANSWERABLE, M.UNANSWERABLE, M.UNANSWERABLE))

    check("tsf3 a scope digest is `not-declared` when the work declares no "
          "files, which is a thing the CALLER chose - separated from "
          "`unanswerable`, which is git failing, because the two have different "
          "repairs",
          M.field_state("scopeDigest", None, None, False) == M.NOT_DECLARED
          and M.field_state("scopeDigest", None, None, True) == M.UNANSWERABLE)

    state = M.tested_state(os.getcwd(), [], None)
    missing = [key for _f, key, _limit in M.FIELD_LIMIT if key not in state]
    check("tsf4 every field's BASIS KEY names a key `tested_state` really files, "
          "read off the table rather than built by concatenation. The first run "
          "of this module printed `basis: None` under two of the three fields "
          "for exactly that reason: %r" % (missing,),
          missing == [] and set(M.IDENTITY_FIELDS) <= set(state))

    check("tsf5 the limit `dirty_digest` inherited is stated in the same words "
          "it was written in, because the stamp PRINTS it and a softened "
          "paraphrase would be the stamp overclaiming: %r" % (M.DIRTY_LIMIT,),
          "WHICH paths were dirty, never their contents" in M.DIRTY_LIMIT)

    check("tsf6 every verdict the module declares has a sentence to print beside "
          "it - derived from the words themselves, so a fourth verdict cannot be "
          "added and left rendering bare",
          set(M.VERDICT_HELP) == set((M.CURRENT, M.STALE, M.UNESTABLISHED)))


# --- the comparison, against a real repository --------------------------------
def _tree_cases(check):
    repo = _seeded_repo("tree-stamp-selftest-")
    mine = os.path.join(repo, "src", "mine.py")
    theirs = os.path.join(repo, "src", "theirs.py")
    owns = ["src/mine.py"]

    stamp, state = M.take(repo, owns)
    check("tst1 a stamp on a real repository answers all three fields, and "
          "carries the basis for each beside it: %r"
          % ([stamp.get(f) is not None for f in M.IDENTITY_FIELDS],),
          all(stamp.get(f) is not None for f in M.IDENTITY_FIELDS)
          and all(state.get(key) for _f, key, _l in M.FIELD_LIMIT))

    quiet = M.compare(stamp, repo)
    check("tst2 THE ALLOW CASE: a tree nothing has touched grades `current`, and "
          "every field says so. A stamp that cried stale on a quiet tree would "
          "be ignored inside a day, so this is the case a widened comparison has "
          "to break: %r / %r" % (quiet["verdict"], _states(quiet)),
          quiet["verdict"] == M.CURRENT
          and set(_states(quiet).values()) == set((M.AGREES,)))

    check("tst3 ...and `current` rests on at least one field that AGREED, never "
          "on a comparison where nothing was asked. HEAD is always in play, so a "
          "`current` with no agreeing field would be silence reading as clean",
          M.AGREES in [e["state"] for e in quiet["fields"]])

    _write(mine, "v = 2\n")
    edited = M.compare(stamp, repo)
    check("tst4 editing a DECLARED file is `stale`, and the scope digest is what "
          "moved. Both halves asserted: a comparison that reported every field "
          "as moved would pass on the first half alone: %r / %r"
          % (edited["verdict"], _states(edited)),
          edited["verdict"] == M.STALE
          and _states(edited)["scopeDigest"] == M.MOVED
          and _states(edited)["head"] == M.AGREES)

    _write(mine, "v = 1\n")
    stamp2, _state2 = M.take(repo, owns)
    _write(os.path.join(repo, "stray.txt"), "a sibling made this\n")
    strayed = M.compare(stamp2, repo)
    check("tst5 a file appearing OUTSIDE the declared scope moves the dirty "
          "digest and leaves the scope digest alone - the two answer different "
          "questions, and the reader needs to know which one it was: %r / %r"
          % (strayed["verdict"], _states(strayed)),
          strayed["verdict"] == M.STALE
          and _states(strayed)["dirtyDigest"] == M.MOVED
          and _states(strayed)["scopeDigest"] == M.AGREES)

    # THE INHERITED LIMIT, EXERCISED RATHER THAN DESCRIBED. `theirs.py` is
    # already dirty and outside the declared scope, so rewriting it changes no
    # porcelain LINE and no declared byte. This case exists so nobody can read
    # the stamp as a snapshot of the repository.
    _write(theirs, "w = 2\n")
    stamp3, _state3 = M.take(repo, owns)
    _write(theirs, "w = 3\n")
    limited = M.compare(stamp3, repo)
    check("tsl2 A REWRITE OF AN ALREADY-DIRTY FILE OUTSIDE THE DECLARED SCOPE "
          "MOVES NOTHING, which is `DIRTY_LIMIT` in the flesh: porcelain reports "
          "STATUS and never bytes. The stamp is a retry discriminator, not a "
          "reproducible snapshot, and this is the case that stops the docstring "
          "being the only thing saying so: %r / %r"
          % (limited["verdict"], _states(limited)),
          limited["verdict"] == M.CURRENT
          and _states(limited)["dirtyDigest"] == M.AGREES
          and _states(limited)["scopeDigest"] == M.AGREES)

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second")
    stamp4, _state4 = M.take(repo, owns)
    _write(mine, "v = 9\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "third")
    moved_head = M.compare(stamp4, repo)
    check("tst6 a branch that MOVED is stale by its head, which is the failure "
          "that silently reverted a sibling's work: a patch taken against a tree "
          "that is no longer there: %r / %r"
          % (moved_head["verdict"], _states(moved_head)),
          moved_head["verdict"] == M.STALE
          and _states(moved_head)["head"] == M.MOVED)


# --- the tree git will not describe -------------------------------------------
def _unknowable_cases(check):
    plain = _harness.fixture_root("tree-stamp-nogit-")
    _write(os.path.join(plain, "a.txt"), "not a repository\n")

    check("tsu1 `porcelain` answers None for a directory that is not a "
          "repository - None is NOT an empty tree, and reporting it as one would "
          "be the false clean sheet this whole module is against",
          M.porcelain(plain) is None)

    stamp, state = M.take(plain, ["a.txt"])
    check("tsu2 a stamp taken where git cannot answer carries nulls and the "
          "sentence that says why, rather than a placeholder that would put a "
          "false anchor on a real claim: %r / %r"
          % (stamp.get("head"), state.get("dirtyBasis")),
          stamp.get("head") is None and stamp.get("dirtyDigest") is None
          and "git could not describe the tree" in (state.get("dirtyBasis") or ""))

    verdict = M.compare(stamp, plain)
    check("tsu3 THE THIRD ANSWER: grading that stamp against that same directory "
          "is `unestablished` and NOT `current`. Nothing changed and nothing "
          "could be asked are two different reports, and only one of them lets a "
          "reader go on citing the claim: %r / %r"
          % (verdict["verdict"], _states(verdict)),
          verdict["verdict"] == M.UNESTABLISHED
          and _states(verdict)["head"] == M.UNANSWERABLE)

    repo = _seeded_repo("tree-stamp-rank-")
    owns = ["src/mine.py"]
    real, _state = M.take(repo, owns)
    # One field unanswerable, one field genuinely moved. Built by blanking the
    # dirty digest on a stamp that is otherwise real, because the two conditions
    # do not co-occur naturally in one directory.
    mixed = dict(real)
    mixed["dirtyDigest"] = None
    _write(os.path.join(repo, "src", "mine.py"), "v = 42\n")
    ranked = M.compare(mixed, repo)
    check("tsu4 MOVED OUTRANKS UNANSWERABLE. A tree with one field moved and "
          "another unreadable HAS moved - that much is established - and "
          "reporting it as ungradeable would hide a fact already in hand: %r / %r"
          % (ranked["verdict"], _states(ranked)),
          ranked["verdict"] == M.STALE
          and _states(ranked)["dirtyDigest"] == M.UNANSWERABLE
          and _states(ranked)["scopeDigest"] == M.MOVED)


# --- what the reader is shown -------------------------------------------------
def _render_cases(check):
    repo = _seeded_repo("tree-stamp-render-")
    owns = ["src/mine.py"]
    stamp, state = M.take(repo, owns)
    lines = M.render_stamp(stamp, state)
    text = "\n".join(lines)
    check("tsr1 the stamp print carries the BASIS for every field, not only the "
          "hex. A reader who can see what makes a digest true can tell it from a "
          "field nobody wired up; one shown only the value has to trust it: %r"
          % (text.count("basis:"),),
          text.count("basis:") == len(M.IDENTITY_FIELDS)
          and M.format_stamp(stamp) in text)

    check("tsr2 ...and HEAD's basis is printed ONCE. It is filed as both the "
          "basis and the limit, and two identical lines under two labels read as "
          "two independent statements - a claim this field cannot support twice",
          text.count(M.HEAD_BASIS) == 1)

    _write(os.path.join(repo, "src", "mine.py"), "v = 5\n")
    stale_text = "\n".join(M.render_comparison(M.compare(stamp, repo)))
    check("tsr3 a stale render names the field, shows what it WAS and what it IS "
          "now, and says the repair. 'Stale' with no cause sends the reader to "
          "re-run everything: %r" % (stale_text.splitlines()[:1],),
          "scopeDigest" in stale_text and "was:" in stale_text
          and "now:" in stale_text and "re-taken" in stale_text)

    plain = _harness.fixture_root("tree-stamp-render-nogit-")
    dead, dead_state = M.take(plain, [])
    dead_text = "\n".join(M.render_comparison(M.compare(dead, plain)))
    check("tsr4 ...and the unestablished render says in words that it is not a "
          "pass, because the one thing a reader must not take from it is "
          "permission to go on citing the claim: %r"
          % (dead_text.splitlines()[:1],),
          "not a pass" in dead_text
          and M.UNESTABLISHED in dead_text
          and "(not knowable" in "\n".join(M.render_stamp(dead, dead_state)))


def _cases(check):
    _harness.stage(check, "tsk", _token_cases)
    _harness.stage(check, "tsf", _field_cases)
    _harness.stage(check, "tst", _tree_cases)
    _harness.stage(check, "tsu", _unknowable_cases)
    _harness.stage(check, "tsr", _render_cases)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__tree_stamp.py --selftest\n")
    raise SystemExit(2)
