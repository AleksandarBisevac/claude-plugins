#!/usr/bin/env python3
"""Every COMMITTED rendered artifact must match what its source renders today.

WHY THIS EXISTS. `examples/acme-store/acme-store-audit.html` is the report a new
user opens first, and it carried the pre-F28 `aria-label`s -- the ones a speech
user cannot reach -- for as long as it took somebody to notice, because the
source was fixed and the artifact was not. CI did render the example, to a temp
directory, and grepped THAT. A check that renders its own copy can never see a
committed file drift; it proves the renderer works, which was never in doubt.

WHY IT COULD NOT HAVE BEEN WRITTEN BEFORE. The report stamped wall-clock, so no
two renders agreed and a byte comparison was impossible. `_report_page._stamp_time`
now honours SOURCE_DATE_EPOCH, and this tool sets it to the stamp it reads out of
the committed file -- so a byte-identical result proves the ONLY thing that
differed was the clock, and any other difference is real drift.

`docs/demo-large.html` is covered too, and it costs one extra step: it renders
from a GENERATED fixture, so the check regenerates that fixture first and relies
on the generator being deterministic as well as the renderer. Comparing against a
fixture this tool did not build would report drift that is not drift.

TWO ARMS, BECAUSE THERE ARE TWO QUESTIONS. The comparison above is against the file
ON DISK, which is the right question while you are iterating: is the render current
before I stage anything. `uncommitted()` asks the release's question -- does the
COMMIT carry what is on disk -- because nothing did, and a re-render left unstaged
went green here while a `git archive` of the commit still held the old bytes. They are
reported apart: one is repaired by re-rendering and the other by committing, and a
reader has to know which went red.

WHAT IT STILL DOES NOT COVER, and the direction: an artifact nobody listed in
`ARTIFACTS`. That is an UNDER-count -- the quiet direction -- so a clean run means
"the artifacts in the table are current", not "every committed artifact is".

`docs/index.html` IS such an artifact and is left out ON PURPOSE, which is the half
of that sentence nobody had written down. It is a BYTE COPY of the committed example
report, so the honest way to cover it is a COMPOSITION rather than a row: this tool
proves the example still matches a fresh render, and a plain `cmp` proves the copy is
still the copy. Fresh source plus proven copy is a fresh copy. Adding it to
`ARTIFACTS` instead would have two gates render one published page from two different
inputs, which is how two gates come to disagree about one file.

A composition is only sound while both halves exist, and nothing stated it -- so each
half read as incomplete alone. The other half is therefore DECLARED here, in
`COPY_PROVEN`, and CHECKED: `copy_check_missing()` reads the files that are supposed
to carry that `cmp` and reports one that no longer does. A clean run now says "the
table is current AND the copy check this tool defers to is still there", which is the
only version of the claim a reader can act on.

WHEN SOMETHING IS STALE IT PRINTS THE COMMAND THAT REFRESHES IT, beside the artifact
rather than in a document somewhere else. The scale demo's recipe is BUILT from the
very flags `_fixture_argv()` renders with, so the instructions cannot drift from the
comparison the way a hand-copied recipe does -- and the recipe already existed by
hand, in more than one file, on the day this was added.

Run it:   python3 tools/check-rendered-artifacts.py
          python3 tools/check-rendered-artifacts.py --how       # just the recipes
          python3 tools/check-rendered-artifacts.py --selftest
Exit 0 when every artifact is current, the commit carries what the working tree
holds, and the copy check is still in place; 1 naming each artifact that is stale,
each page the commit does not carry, and each declared copy check that has gone; 2 on
a usage error. A page nobody could look up in `HEAD` is named rather than counted
either way, and a run that could look up NONE of them exits 1 saying so. Nothing is
written to the repo -- it renders into a temporary directory.
"""

import calendar
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# --- what is compared, and what is deliberately deferred ---------------------
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STAMP = re.compile(r"generated (\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}) UTC")

# (committed artifact, manifest, project dir, refresh command). The project dir is
# what CLAUDE_PROJECT_DIR must be for the render to find the ledger beside the plan.
# The refresh command rides along because a red gate that does not say how to go
# green is how a releaser learns a follower list one failure at a time.
ARTIFACTS = [
    ("examples/acme-store/acme-store-audit.html",
     "examples/acme-store/audit-plan.json", "examples/acme-store",
     "examples/report.sh"),
    ("examples/acme-store/acme-store-audit.md",
     "examples/acme-store/audit-plan.json", "examples/acme-store",
     "examples/report.sh"),
]

# Rendered from a fixture this tool generates rather than from a committed
# manifest, so it carries its own entry: (artifact, rendered basename). Its refresh
# command is GENERATED rather than listed, by `demo_refresh_command()`.
GENERATED_ARTIFACTS = [
    ("docs/demo-large.html", "demo-large.html"),
]

# The flags the scale demo's fixture is generated with, in ONE place because two
# readers need them: the render this tool compares against, and the recipe it prints
# for a human. A recipe naming different flags from the comparison sends a releaser
# off to produce bytes this very tool then rejects.
DEMO_FIXTURE_FLAGS = ("--phases", "40", "--tasks", "5")

# THE OTHER HALF OF THIS TOOL'S COVERAGE, DECLARED SO IT CAN BE CHECKED.
# (copy, source, the files that must prove it) -- a committed page that is a byte
# copy of another committed page, and where the `cmp` proving that lives. Confirmed
# live: re-render the example without refreshing the copy and the `cmp` goes red at
# the exact byte of the version stamp.
#
# WHY A DECLARATION AND NOT A ROW IN `ARTIFACTS`: see the docstring. The short of it
# is that a byte copy has no source of its own to be rendered from, so a row would
# mean rendering the example twice and calling the second render a different file.
COPY_PROVEN = [
    ("docs/index.html", "examples/acme-store/acme-store-audit.html",
     (".github/workflows/ci.yml", "tools/verify.sh")),
]

# `cmp` as a whole word: `cmp -s a b` and `if ! cmp -s a b; then` are the same step
# spelled for two runners, and neither side's flags are this rule's business.
_CMP_WORD = re.compile(r"\bcmp\b")


def stamp_epoch(text):
    """The artifact's own generation stamp as epoch seconds, or None.

    None is never treated as "fine": an artifact with no stamp cannot be
    compared, and the caller reports that rather than skipping it. Silence about
    a file nobody could check is the failure this whole tool is about.
    """
    m = _STAMP.search(text)
    if not m:
        return None
    parts = [int(x) for x in m.groups()]
    return calendar.timegm((parts[0], parts[1], parts[2],
                            parts[3], parts[4], 0, 0, 0, 0))


# --- how to go green: the recipe printed beside a stale artifact -------------
def _fixture_argv(project):
    """The generator call that builds the scale demo's fixture, as argv.

    Split out of `_build_demo_fixture()` for one reason: it is the only place the
    fixture flags are SPENT, and a case can compare it against the recipe printed
    for a human. Two spellings of those flags is the drift this whole file exists
    to catch, one directory over.
    """
    scripts = os.path.join(REPO, "plugins", "audit", "scripts")
    return ([sys.executable, os.path.join(scripts, "demo", "gen-demo-manifest.py"),
             project] + list(DEMO_FIXTURE_FLAGS))


def demo_refresh_command():
    """The shell that regenerates `docs/demo-large.html`, built from those flags.

    A STRING AND NOT A DOCUMENT. This recipe already existed by hand elsewhere in
    the tree when it was written here, which is exactly how the flags come to
    disagree with the comparison above. Built from `DEMO_FIXTURE_FLAGS` so it
    cannot.

    It renders into the fixture directory and copies only the HTML: the render also
    writes a Markdown twin that this repo does not commit, so an `--out-dir docs`
    would leave an untracked file behind every time.
    """
    return ("d=$(mktemp -d)\n"
            "python3 plugins/audit/scripts/demo/gen-demo-manifest.py \"$d\" %s\n"
            "python3 plugins/audit/scripts/demo/gen-demo-usage.py"
            " \"$d/audit-plan.json\"\n"
            "CLAUDE_PROJECT_DIR=$d python3"
            " plugins/audit/scripts/report/render-report.py \\\n"
            "  \"$d/audit-plan.json\" --out-dir \"$d\"\n"
            "cp \"$d/demo-large.html\" docs/demo-large.html"
            % (" ".join(DEMO_FIXTURE_FLAGS),))


def refresh_for(rel):
    """The command that regenerates one committed artifact, or None.

    None, never "": a printer renders an empty string as a blank line and a reader
    reads a blank line as "nothing to do here", which is the opposite of what an
    artifact with no recorded recipe means. The caller says so in words instead.
    """
    for row in ARTIFACTS:
        if row[0] == rel:
            return row[3]
    for gen_rel, _basename in GENERATED_ARTIFACTS:
        if gen_rel == rel:
            return demo_refresh_command()
    return None


# --- the other half of the coverage, read rather than assumed ----------------
def _proves_copy(text, copy_rel, source_rel):
    """How many RUNNABLE lines of `text` compare that pair with `cmp`.

    A COUNT AND NOT A BOOLEAN. "Is there one" cannot tell a file that lost the step
    from a reader that never worked, and this reader has a specific way of being
    wrong: both sides describe the step in prose directly above it, so a scan that
    counted comments would go on passing after the step itself was deleted.
    """
    n = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if (_CMP_WORD.search(stripped) and copy_rel in stripped
                and source_rel in stripped):
            n += 1
    return n


def copy_check_missing(repo_root=None):
    """[(copy, side, problem), ...] -- a declared copy check that is not there.

    This is what makes the docstring's "covered by composition" a fact rather than
    a sentence. A file it cannot read is a finding too: "I could not tell" and "it
    is still there" must not print the same way, or the day the path changes this
    starts clearing a check nobody ran.
    """
    root = repo_root if repo_root is not None else REPO
    out = []
    for copy_rel, source_rel, sides in COPY_PROVEN:
        for side in sides:
            path = os.path.join(root, side.replace("/", os.sep))
            try:
                with io.open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError) as exc:
                out.append((copy_rel, side,
                            "cannot be read, so nothing here can say whether it "
                            "still proves the copy: %s" % (exc,)))
                continue
            if _proves_copy(text, copy_rel, source_rel) == 0:
                out.append((copy_rel, side,
                            "no longer compares it with %s, so the reason %s is "
                            "left out of ARTIFACTS has gone - restore the cmp, or "
                            "stop deferring to it"
                            % (source_rel, copy_rel)))
    return out


# --- rendering, and the byte comparison ---------------------------------------
def _build_demo_fixture(work):
    """Generate the scale demo's fixture, deterministically, and return its dir.

    The fixture is seeded, so two runs produce identical bytes; that is what lets
    the artifact rendered from it be compared at all. Returns None when a step
    exits non-zero, which the caller reports rather than treating as "no drift".
    """
    project = os.path.join(work, "demo")
    os.makedirs(project)
    scripts = os.path.join(REPO, "plugins", "audit", "scripts")
    steps = [
        _fixture_argv(project),
        [sys.executable, os.path.join(scripts, "demo", "gen-demo-usage.py"),
         os.path.join(project, "audit-plan.json")],
    ]
    for step in steps:
        if subprocess.call(step, cwd=REPO, stdout=open(os.devnull, "w"),
                           stderr=subprocess.STDOUT) != 0:
            return None
    return project


def render_args(project, manifest_name="audit-plan.json"):
    """ABSOLUTE `(manifest, project)` for a render, and never a relative pair.

    THE ROUND TRIP THIS REPLACES WORKED BY ACCIDENT. The caller used to make the
    pair relative with `os.path.relpath(..., REPO)` so `_render` could rejoin it
    to `REPO` - a no-op whenever the path was under the repo, and a `ValueError:
    path is on mount 'C:', start on mount 'D:'` when it was not. A generated
    fixture lives in a temp directory, and on Windows a temp directory routinely
    sits on a different drive from the checkout, so CI raised where every POSIX run
    had quietly normalised the `../../..` back to the right place.

    `relpath` is the only operation in that chain that can fail on a path, so the
    repair is to never perform it: absolute in, absolute out, nothing re-based.
    """
    return os.path.join(project, manifest_name), project


def _render(manifest, project, out_dir, epoch):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = project
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    script = os.path.join(REPO, "plugins", "audit", "scripts", "report",
                          "render-report.py")
    return subprocess.call(
        [sys.executable, script, manifest,
         "--out-dir", out_dir],
        cwd=REPO, env=env,
        stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)


def gen_workdirs(work, index):
    """(fixture root, render output) for the Nth generated artifact.

    INDEXED, because they were two fixed names. The keyed renders above already
    number theirs `r0`, `r1`, ... and the generated half - written when the table
    had one row and still has - reused `gen` and `genout` for every row it walked.
    A SECOND entry in that table therefore did not compare wrongly: it raised
    `FileExistsError` out of `os.makedirs` on the row after the first, which is a
    gate that stops working the day somebody adds the artifact it was widened for.
    Not silent, and not reachable today; a shape that cannot be entered twice is
    still a shape nobody can extend.
    """
    return (os.path.join(work, "gen%d" % (index,)),
            os.path.join(work, "genout%d" % (index,)))


def drifted(artifacts=None, generated=None):
    """[(path, detail), ...] -- committed artifacts a fresh render disagrees with.

    `generated` is a parameter for one reason: the second entry in that table is
    what `gen_workdirs()` exists for, and a case that hands this two rows is the
    only thing that proves the walk survives one.
    """
    out = []
    work = tempfile.mkdtemp(prefix="audit-fresh-")
    try:
        rendered = {}
        for rel, manifest, project, _refresh in (artifacts or ARTIFACTS):
            path = os.path.join(REPO, rel)
            try:
                with io.open(path, "r", encoding="utf-8") as fh:
                    committed = fh.read()
            except (OSError, UnicodeDecodeError):
                out.append((rel, "cannot be read, so nothing here can compare it"))
                continue
            epoch = stamp_epoch(committed)
            if epoch is None:
                out.append((rel, "carries no generation stamp, so a fresh render "
                                 "cannot be pinned to its clock"))
                continue
            key = (manifest, project, epoch)
            if key not in rendered:
                sub = os.path.join(work, "r%d" % len(rendered))
                os.makedirs(sub)
                if _render(os.path.join(REPO, manifest),
                           os.path.join(REPO, project), sub, epoch) != 0:
                    out.append((rel, "the renderer exited non-zero on %s" % manifest))
                    continue
                rendered[key] = sub
            fresh_path = os.path.join(rendered[key], os.path.basename(rel))
            if not os.path.exists(fresh_path):
                out.append((rel, "a fresh render produced no such file"))
                continue
            with io.open(fresh_path, "r", encoding="utf-8") as fh:
                fresh = fh.read()
            if fresh != committed:
                out.append((rel, "%d committed bytes vs %d rendered; the clock is "
                                 "pinned, so this is real drift"
                            % (len(committed), len(fresh))))
        for index, row in enumerate(GENERATED_ARTIFACTS if generated is None
                                    else generated):
            rel, basename = row
            path = os.path.join(REPO, rel)
            try:
                with io.open(path, "r", encoding="utf-8") as fh:
                    committed = fh.read()
            except (OSError, UnicodeDecodeError):
                out.append((rel, "cannot be read, so nothing here can compare it"))
                continue
            epoch = stamp_epoch(committed)
            if epoch is None:
                out.append((rel, "carries no generation stamp"))
                continue
            fixture_dir, sub = gen_workdirs(work, index)
            project = _build_demo_fixture(fixture_dir)
            if project is None:
                out.append((rel, "the fixture generator exited non-zero, so this "
                                 "artifact could not be compared at all"))
                continue
            os.makedirs(sub)
            _fx_manifest, _fx_project = render_args(project)
            if _render(_fx_manifest, _fx_project, sub, epoch) != 0:
                out.append((rel, "the renderer exited non-zero on the generated "
                                 "fixture"))
                continue
            fresh_path = os.path.join(sub, basename)
            if not os.path.exists(fresh_path):
                out.append((rel, "a fresh render produced no such file"))
                continue
            with io.open(fresh_path, "r", encoding="utf-8") as fh:
                fresh = fh.read()
            if fresh != committed:
                out.append((rel, "%d committed bytes vs %d rendered from a "
                                 "regenerated fixture; the clock is pinned, so "
                                 "this is real drift"
                            % (len(committed), len(fresh))))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out


# --- ...and the same pages, asked what the COMMIT carries ---------------------
# THE OTHER QUESTION, AND IT IS A DIFFERENT ONE. Everything above compares a fresh
# render with the file ON DISK, which is the right question in the iteration loop: a
# releaser wants to know the render is current before staging anything. Nobody was
# asking the release's question. Re-render, leave the result unstaged, and every
# check here goes green while the commit still carries the old bytes - which happened
# in this repository, to four published documents at once, and only a `git archive` of
# the commit, where no working tree exists, showed the drift. In a worktree the arm
# above cannot tell "rendered and committed" from "rendered and forgotten", and
# forgetting is the failure mode it was built for.
#
# WHY THIS COMPARES HEAD WITH THE DISK RATHER THAN WITH A SECOND RENDER. The sketch
# was HEAD against a fresh render. Byte equality is transitive and the arm above
# already proves `disk == fresh`, so `HEAD == disk` completes it: fresh working tree
# plus committed working tree is a fresh commit. That is the same COMPOSITION
# `COPY_PROVEN` above is built on, it costs no second render (the demo's fixture
# alone is the expensive half of this tool), and - the reason that decided it - the
# finding is the actionable one. "The working tree holds a render the commit does not
# carry" names the repair; "HEAD disagrees with a fresh render" leaves a reader to
# work out whether to re-render or to commit.
#
# The two arms are reported APART because they fail for different reasons and are
# repaired differently, and a reader has to know which one went red.
#
# WHAT IT READS. `git cat-file blob` and not `git show`: `show` is diff machinery and
# will run a `diff.textconv` filter somebody has configured globally, which would make
# this tool's answer a property of the operator's `~/.gitconfig`. A blob is the bytes,
# and the bytes are what a `git archive` of the commit hands out.
_HEAD = "HEAD"


def committed_subjects():
    """Every published page this tool has an opinion about, in one list.

    DERIVED FROM THE TABLES ABOVE, never a fourth table. The two render tables plus
    the byte copies this tool defers on - and the copies belong here precisely
    because their `cmp` is a working-tree comparison too, so the copy could be
    re-made and left uncommitted exactly the way its source could.
    """
    return _tabled_artifacts() + [copy_rel for copy_rel, _s, _sides in COPY_PROVEN]


def _as_text(raw):
    """A git blob decoded the way `drifted()` reads the file on disk.

    UNIVERSAL NEWLINES, deliberately: the arm above reads its files in TEXT mode, so
    that is its notion of equality, and an arm that were stricter would report a line
    ending as drift on a machine where the checkout has them. Matching it exactly is
    what keeps the composition sound - two comparisons over one definition of "the
    same bytes".
    """
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _git(root, args):
    """(returncode, stdout bytes, stderr text), or None when git could not be run.

    None rather than a fabricated non-zero code: "git refused" and "there is no git
    here" send a reader to two different places, and a caller that could not tell
    them apart would print one of them for the other.
    """
    try:
        proc = subprocess.Popen(["git", "-C", root] + list(args),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    out, err = proc.communicate()
    return (proc.returncode, out, err.decode("utf-8", "replace").strip())


def head_unavailable(root):
    """Why HEAD cannot be asked of this tree, or None -- asked ONCE per run.

    Once, because the answer is a property of the tree rather than of a page, and
    because a per-page git failure would otherwise be reported as "this artifact is
    not committed" for every artifact in turn - one cause wearing as many findings as
    the table is long.
    """
    got = _git(root, ["rev-parse", "--verify", "-q", _HEAD + "^{commit}"])
    if got is None:
        return ("git could not be run here at all, so nothing in this tree can say "
                "what a commit of it would carry")
    code, _out, err = got
    if code != 0:
        # GIT'S OWN WORDS ARE THE DETAIL, because the two shapes this covers - not a
        # repository at all, and a repository with no commit yet - are repaired
        # differently and only git knows which one this is. A frame that named one of
        # them would be wrong half the time.
        return ("git would not resolve %s here (%s), so there is no commit for the "
                "working tree to be compared against"
                % (_HEAD, err or "no detail given"))
    return None


def head_text(root, rel):
    """(text, problem) -- what HEAD tracks at `rel`. Exactly one of the two is None.

    A PATH THAT IS NOT IN HEAD IS A PROBLEM, NOT AN EMPTY FILE. An artifact added in
    the commit being prepared has no blob yet, which is a legitimate state and is
    still "could not look": the caller must be able to say so rather than compare the
    working tree against nothing and call the result agreement.
    """
    posix = rel.replace(os.sep, "/")
    spec = "%s:%s" % (_HEAD, posix)
    exists = _git(root, ["cat-file", "-e", spec])
    if exists is None:
        return None, "git could not be run here at all"
    if exists[0] != 0:
        return None, ("is not in %s - nothing has committed it yet, so this run "
                      "cleared it of nothing" % (_HEAD,))
    got = _git(root, ["cat-file", "blob", spec])
    if got is None:
        return None, "git could not be run here at all"
    code, out, err = got
    if code != 0:
        return None, ("git tracks something at this path in %s but would not hand "
                      "over the bytes (%s)" % (_HEAD, err or "no detail given"))
    try:
        return _as_text(out), None
    except UnicodeDecodeError as exc:
        return None, ("the committed bytes do not decode as UTF-8, so they cannot "
                      "be compared with a file this tool reads as text: %s" % (exc,))


def uncommitted(repo_root=None, subjects=None):
    """{"differs", "unlooked", "compared", "subjects"} -- what the commit is missing.

    THREE OUTCOMES PER PAGE AND NOT TWO, which is the whole point of this arm. It
    matched, it differs, or nobody could look - and the third must never be spelled
    like the first. `compared` is the count of pages that really were compared, so a
    caller can refuse to print a clean verdict over a run that cleared nothing;
    `check-committed-pii.py`'s `domain-unavailable` is the same refusal one tool over.
    """
    root = repo_root if repo_root is not None else REPO
    rels = list(committed_subjects() if subjects is None else subjects)
    stopped = head_unavailable(root)
    if stopped is not None:
        return {"differs": [], "unlooked": [(rel, stopped) for rel in rels],
                "compared": 0, "subjects": rels}
    differs, unlooked, compared = [], [], 0
    for rel in rels:
        tracked, problem = head_text(root, rel)
        if problem is not None:
            unlooked.append((rel, problem))
            continue
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with io.open(path, "r", encoding="utf-8") as fh:
                working = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            unlooked.append((rel, "is in %s but cannot be read from the working "
                                  "tree, so the pair cannot be compared: %s"
                             % (_HEAD, exc)))
            continue
        compared += 1
        if tracked != working:
            differs.append((rel, "%d byte(s) at %s vs %d in the working tree - the "
                                 "commit does not carry what is on disk"
                            % (len(tracked), _HEAD, len(working))))
    return {"differs": differs, "unlooked": unlooked, "compared": compared,
            "subjects": rels}


def committed_report(result):
    """([lines], exit code) for one `uncommitted()` answer.

    PURE, so a case reads exactly what a caller reads rather than a fixture of it -
    and so the "cleared nothing" branch can be driven without taking git away from
    the machine running the suite.

    A PAGE NOBODY COULD LOOK AT IS NOT A FAILURE; A RUN THAT LOOKED AT NONE OF THEM
    IS. An artifact being added by the very commit this runs in has no blob yet, and
    failing there would train a releaser to ignore this. But a tree where git cannot
    be asked produces that same silence for every page at once, and silence over the
    whole set is a check that ran and cleared nothing - which must never read as
    clean.
    """
    lines = []
    for rel, detail in result["differs"]:
        lines.append("UNCOMMITTED %s - %s" % (rel, detail))
        lines.append("      stage this file and commit it; a fresh render nobody "
                     "committed is what a `git archive` of the commit will not have")
    for rel, why in result["unlooked"]:
        lines.append("COULD NOT LOOK %s - %s" % (rel, why))
    if not result["compared"]:
        lines.append("NOTHING WAS COMPARED AGAINST %s: this arm cleared none of the "
                     "page(s) it was given, so the absence of an UNCOMMITTED line "
                     "above says nothing about what the commit carries" % (_HEAD,))
        return lines, 1
    if result["differs"]:
        return lines, 1
    tail = ("" if not result["unlooked"] else
            ", and the rest could not be looked at and are named above")
    lines.append("OK: %d of %d published page(s) are byte-identical to what %s "
                 "tracks%s" % (result["compared"], len(result["subjects"]),
                               _HEAD, tail))
    return lines, 0


# --- selftest -----------------------------------------------------------------
def _cases(check):
    # TWO COMPUTATIONS, NOT ONE, and the reason is what this case used to be: it
    # compared the parse against a constant that its own arithmetic cancelled back
    # to a round number the parse never returns, then said `or ... is not None`.
    # The equality was false on every run and the case passed on the `or`, so what
    # it asserted was "parsing did not crash" while claiming to assert the epoch.
    _ra_stamp = "generated 2023-11-14 22:13 UTC"
    _ra_want = calendar.timegm((2023, 11, 14, 22, 13, 0, 0, 0, 0))
    # F89. The pair a render is given must be ABSOLUTE and must not be re-based on
    # the repo, because a generated fixture lives in a temp directory and on Windows
    # a temp directory routinely sits on another drive - where `relpath` raises
    # rather than returning something wrong. The old form made the pair relative to
    # REPO so `_render` could rejoin it; these two cases are what fail if anyone
    # reintroduces that, and they fail on every platform rather than only the one
    # that raised.
    #
    # ONE ALLOCATED ROOT FOR BOTH PROBE PATHS, AND NEITHER CHILD IS EVER CREATED.
    # Both were fixed names hung off the shared system temp root: one standing for
    # a fixture outside the checkout, one for a root that cannot be read. A name
    # nobody allocated is a name another process can be using, and ra11's whole
    # claim is that its root is unreadable - a stray directory of that name turns it
    # into a different case without anybody being told. Allocating the parent makes
    # the two names this run's; leaving the children uncreated is what keeps them
    # meaning what the cases say they mean.
    _probe_root = tempfile.mkdtemp(prefix="audit-fresh-probe-")
    try:
        _fx = os.path.join(_probe_root, "fixture")
        _ra_manifest, _ra_project = render_args(_fx)
        _ra_unreadable = copy_check_missing(os.path.join(_probe_root,
                                                         "no-such-root"))
    finally:
        shutil.rmtree(_probe_root, ignore_errors=True)
    check("ra6 a render is handed ABSOLUTE paths - the relative pair this replaces "
          "was rejoined to REPO by the callee, which is a no-op under the repo and "
          "a ValueError across drives: %r" % ((_ra_manifest, _ra_project),),
          os.path.isabs(_ra_manifest) and os.path.isabs(_ra_project))
    check("ra7 ...and neither is re-based on REPO, so a fixture OUTSIDE the "
          "checkout comes back as itself: the manifest hangs off the project and "
          "the project is unchanged",
          _ra_project == _fx
          and _ra_manifest == os.path.join(_fx, "audit-plan.json")
          and not _ra_manifest.startswith(REPO))
    check("ra1 a stamp is read back as the epoch that produced it, so a render "
          "pinned to it reproduces the same minute: %r vs %r"
          % (stamp_epoch(_ra_stamp), _ra_want),
          stamp_epoch(_ra_stamp) == _ra_want)
    check("ra2 a round trip through time.gmtime lands on the same string, which "
          "is what makes the byte comparison exact rather than approximate",
          time.strftime("%Y-%m-%d %H:%M UTC",
                        time.gmtime(stamp_epoch("generated 2026-08-19 20:16 UTC")))
          == "2026-08-19 20:16 UTC")
    check("ra3 an artifact with NO stamp is reported, never skipped - a file "
          "nobody could compare must not read like a file that matched",
          stamp_epoch("no stamp anywhere in here") is None)
    check("ra4 the table names artifacts that exist, or this tool is checking "
          "files that are not there",
          all(os.path.exists(os.path.join(REPO, rel))
              for rel, _m, _p, _r in ARTIFACTS)
          and all(os.path.exists(os.path.join(REPO, rel))
                  for rel, _b in GENERATED_ARTIFACTS))

    # --- the coverage this tool DEFERS, and the recipes it prints -------------
    # F122. The docstring above says docs/index.html is covered by a byte-copy
    # check somewhere else. These cases are what stop that from being a sentence:
    # the page must be declared as a copy, must stay OUT of the render tables, and
    # the check it defers to must still exist on every side that declares it.
    _tabled = _tabled_artifacts()
    _copies = [c for c, _s, _sides in COPY_PROVEN]
    check("ra8 a page that is a BYTE COPY of another is declared as a copy and is "
          "in NEITHER render table - covering it with a row would have two gates "
          "render one published page from two inputs, which is how two gates come "
          "to disagree about one file: %r vs %r" % (_copies, _tabled),
          "docs/index.html" in _copies
          and _copies != []
          and [c for c in _copies if c in _tabled] == [])
    _gaps = copy_check_missing()
    check("ra9 ...and the check it defers to is still there on every side that "
          "declares it, so 'covered by composition' is checkable rather than "
          "asserted: %r" % (_gaps,), _gaps == [])
    _pair = ("docs/index.html", "examples/acme-store/acme-store-audit.html")
    _cmp_line = "cmp -s %s %s\n" % _pair
    check("ra10 ...and that reader is not one that always answers yes. A "
          "COMMENTED-OUT cmp proves nothing - both sides describe this step in "
          "prose right above it, so counting comments would go on passing after "
          "the step was deleted - a cmp naming only one of the pair is not a "
          "comparison of the pair, and two of them count as two",
          _proves_copy(_cmp_line, *_pair) == 1
          and _proves_copy("# " + _cmp_line, *_pair) == 0
          and _proves_copy("cmp -s %s other/file.html\n" % (_pair[0],),
                           *_pair) == 0
          and _proves_copy(_cmp_line + _cmp_line, *_pair) == 2)
    check("ra11 an unreadable side is REPORTED rather than cleared: 'I could not "
          "tell' and 'it is still there' printing the same way is how this "
          "starts clearing a check nobody ran: %r" % (_ra_unreadable,),
          len(_ra_unreadable)
          == sum(len(sides) for _c, _s, sides in COPY_PROVEN))

    _argv = _fixture_argv("PROJECT")
    _recipe = demo_refresh_command()
    check("ra12 the recipe printed for a stale scale demo names the flags the "
          "comparison actually renders with - both are spent from one constant, "
          "because a recipe that drifts sends a releaser to produce bytes this "
          "very tool then rejects: %r" % (_argv[-len(DEMO_FIXTURE_FLAGS):],),
          _argv[-len(DEMO_FIXTURE_FLAGS):] == list(DEMO_FIXTURE_FLAGS)
          and " ".join(DEMO_FIXTURE_FLAGS) in _recipe
          and "cp \"$d/demo-large.html\" docs/demo-large.html" in _recipe)
    check("ra13 every artifact in the tables carries the command that refreshes "
          "it, and one that carries none comes back None - a printer renders an "
          "empty string as a blank line and a reader reads that as 'nothing to "
          "do here'",
          all(refresh_for(rel) for rel in _tabled)
          and len(_tabled) == len(ARTIFACTS) + len(GENERATED_ARTIFACTS)
          and refresh_for("docs/no-such-artifact.html") is None)
    # The live one, and it is deliberately last for the reader rather than for the
    # stream: the shared runner prints nothing until every case has run, so a slow
    # render delays the whole report and the ordering buys no early news. What it
    # does buy is a report whose expensive case is the last line before the tally.
    _live = drifted()
    check("ra5 every committed rendered artifact matches what its source renders "
          "today - %r" % (_live,), _live == [])

    # THE SECOND ROW, DRIVEN FOR REAL. The generated half of the walk built its
    # fixture and its output under two FIXED names, so the row after the first
    # raised out of `os.makedirs` before it compared anything - a gate that stops
    # working on the day the table it walks is extended. The same row twice is the
    # cheapest fixture that tells the two versions apart: both compare clean under
    # the fix, and the second one cannot start under the bug. A raise is caught and
    # named here rather than left to abort the suite, because "the walk collided"
    # and "an artifact drifted" are different findings.
    _g0 = GENERATED_ARTIFACTS[0]
    try:
        _twice = drifted(artifacts=[], generated=(_g0, _g0))
        _collision = None
    except OSError as exc:
        _twice, _collision = None, "%s: %s" % (type(exc).__name__, exc)
    check("ra5b a SECOND entry in the generated table is walked rather than "
          "colliding with the first: each row gets its own fixture root and its "
          "own render output, the way the keyed renders above already number "
          "theirs: %r / %r" % (_collision, _twice),
          _collision is None and _twice == [])
    _dirs = gen_workdirs("/probe/work", 0) + gen_workdirs("/probe/work", 1)
    check("ra5c ...and that is a property of the derivation, not of this one "
          "fixture: two indices give four distinct directories under one root, "
          "so a version ignoring its index fails here as well as above: %r"
          % (_dirs,),
          len(set(_dirs)) == 4
          and all(d.startswith("/probe/work") for d in _dirs))

    _head_cases(check)


# --- the commit's half of the selftest ----------------------------------------
_HEAD_FX_REL = "docs/probe-report.html"
_HEAD_FX_ABSENT = "docs/probe-never-committed.html"


def _head_fixture(text):
    """A real git repository holding `_HEAD_FX_REL` at `text`, COMMITTED.

    COMMITTED AND NOT MERELY STAGED, which is the one thing that separates this
    fixture from the one `check-committed-pii.py` builds: `git ls-files` reads the
    index, and this arm reads a blob out of a commit. Identity is passed per command
    rather than configured, because the suite runs with HOME pointed away from the
    machine and a `git config --global` would write into a directory the runner then
    fails the file for having touched.

    The caller removes the directory.
    """
    root = tempfile.mkdtemp(prefix="audit-head-fx-")
    path = os.path.join(root, _HEAD_FX_REL.replace("/", os.sep))
    os.makedirs(os.path.dirname(path))
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    ident = ["-c", "user.name=probe", "-c", "user.email=probe@example.invalid",
             "-c", "commit.gpgsign=false"]
    for args in (["init", "-q"], ["add", "-A"],
                 ident + ["commit", "-q", "-m", "fixture"]):
        subprocess.check_call(["git", "-C", root] + args,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    return root


def _write_working(root, rel, text):
    """Overwrite one file in the fixture's WORKING TREE and stage nothing."""
    path = os.path.join(root, rel.replace("/", os.sep))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _head_cases(check):
    """F221. The arm that asks what the COMMIT carries, driven against real git.

    Split out of `_cases` because it allocates a repository per case and the
    allocation has to be undone in `finally`; folding it in would put four
    `try`/`finally` blocks inside a function that already has one.
    """
    _subjects = committed_subjects()
    _tabled = _tabled_artifacts()
    _copies = [c for c, _s, _sides in COPY_PROVEN]
    check("ra14 the pages this arm asks about are DERIVED from the tables above and "
          "from the copies this tool defers on - a fourth hand list of the same "
          "files is what the first two already disagreed about once, and the copies "
          "belong here because their `cmp` compares the working tree too: %r"
          % (_subjects,),
          _subjects == _tabled + _copies
          and "docs/index.html" in _subjects
          and len(set(_subjects)) == len(_subjects))

    _fx_text = "<html>the committed render</html>\n"
    root = _head_fixture(_fx_text)
    try:
        _clean = uncommitted(root, subjects=[_HEAD_FX_REL])
        # THE SECOND-DIRECTION CASE, and it is the one that looks vacuous. An arm
        # that fired unconditionally would satisfy ra16 below for ever while
        # refusing every commit anybody ever made, and nothing else here fails on
        # it: a working tree that matches its commit is the state this arm must be
        # SILENT about.
        check("ra15 a page whose bytes are the bytes the commit carries is silent, "
              "and the run says how many pages it really compared: %r" % (_clean,),
              _clean["differs"] == [] and _clean["unlooked"] == []
              and _clean["compared"] == 1)

        # THE SCENARIO F221 IS ABOUT, driven rather than described: re-render, leave
        # the result unstaged. The arm above this one compares the fresh render with
        # the file ON DISK and is perfectly satisfied; the commit still carries the
        # old bytes, and a `git archive` of it - which has no working tree at all -
        # is what a reader downloads.
        _write_working(root, _HEAD_FX_REL, "<html>the fresh render</html>\n")
        _dirty = uncommitted(root, subjects=[_HEAD_FX_REL])
        check("ra16 a page re-rendered and left UNSTAGED is reported - the working "
              "tree is what the arm above compares and it is satisfied, so nothing "
              "else in this tool can see that the commit still holds the old bytes: "
              "%r" % (_dirty,),
              [rel for rel, _d in _dirty["differs"]] == [_HEAD_FX_REL]
              and _dirty["unlooked"] == [] and _dirty["compared"] == 1
              and "does not carry what is on disk" in _dirty["differs"][0][1])

        # STAGED IS NOT COMMITTED, and this is where a check built on `git status`
        # or on the index would go quiet: `git add` makes the working tree and the
        # index agree while `HEAD` is untouched, and `HEAD` is what gets archived.
        subprocess.check_call(["git", "-C", root, "add", "-A"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _staged = uncommitted(root, subjects=[_HEAD_FX_REL])
        check("ra17 ...and STAGING it does not clear it, which is what makes this a "
              "question about the commit rather than about the index: %r" % (_staged,),
              [rel for rel, _d in _staged["differs"]] == [_HEAD_FX_REL]
              and _staged["compared"] == 1)

        _absent = uncommitted(root, subjects=[_HEAD_FX_ABSENT])
        check("ra18 a page that is in no commit at all is 'could not look' and NOT "
              "'agrees' - an artifact added by the very commit being prepared has no "
              "blob yet, and comparing a working tree against nothing must not be "
              "counted as a comparison: %r" % (_absent,),
              _absent["differs"] == []
              and [rel for rel, _w in _absent["unlooked"]] == [_HEAD_FX_ABSENT]
              and _absent["compared"] == 0
              and "is not in HEAD" in _absent["unlooked"][0][1])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # A DIRECTORY THAT IS NOT A REPOSITORY, allocated rather than named, for the
    # reason the probe root above `ra6` is allocated: a fixed name is a name another
    # process can be using, and this case's whole claim is that git has nothing to
    # answer with here.
    _no_git = tempfile.mkdtemp(prefix="audit-head-nogit-")
    try:
        _refused = uncommitted(_no_git, subjects=[_HEAD_FX_REL, _HEAD_FX_ABSENT])
    finally:
        shutil.rmtree(_no_git, ignore_errors=True)
    check("ra19 a tree git cannot be asked about produces one refusal per page and "
          "NO comparisons - and the reason is asked once, so a single cause does not "
          "arrive wearing as many findings as the table is long: %r" % (_refused,),
          _refused["differs"] == []
          and len(_refused["unlooked"]) == 2
          and _refused["compared"] == 0
          and len(set(w for _r, w in _refused["unlooked"])) == 1)

    # The verdict, read as a caller reads it. PURE inputs, so the branch that must
    # refuse a clean answer can be driven without taking git away from this machine.
    _quiet_lines, _quiet_code = committed_report(_refused)
    check("ra20 a run that compared NOTHING does not read as clean: no page "
          "differed, and that is exactly the shape of a check nobody could run - so "
          "it says so and exits non-zero, the refusal `check-committed-pii.py` "
          "spells `domain-unavailable`: %r" % (_quiet_code,),
          _quiet_code == 1
          and any("NOTHING WAS COMPARED" in line for line in _quiet_lines)
          and not any(line.startswith("OK:") for line in _quiet_lines))
    _partial = {"differs": [], "unlooked": [(_HEAD_FX_ABSENT, "is not in HEAD")],
                "compared": 1, "subjects": [_HEAD_FX_REL, _HEAD_FX_ABSENT]}
    _part_lines, _part_code = committed_report(_partial)
    check("ra21 ...but one page nobody could look up among several that were "
          "compared is NOT a failure, and the OK line carries both numbers rather "
          "than letting partial coverage read as full: %r" % (_part_lines,),
          _part_code == 0
          and any(line.startswith("COULD NOT LOOK") for line in _part_lines)
          and any(line.startswith("OK: 1 of 2 ") for line in _part_lines))
    _bad_lines, _bad_code = committed_report(
        {"differs": [(_HEAD_FX_REL, "differs")], "unlooked": [], "compared": 1,
         "subjects": [_HEAD_FX_REL]})
    check("ra22 ...and a page the commit does not carry fails, naming the repair "
          "that is NOT another render - which is the whole reason the two arms are "
          "printed apart: %r" % (_bad_lines,),
          _bad_code == 1
          and any(line.startswith("UNCOMMITTED") for line in _bad_lines)
          and any("commit it" in line for line in _bad_lines))

    # The live one. It is a claim about THIS checkout and it is the last thing here
    # for the reason `ra5` is last in the block above.
    _live = uncommitted()
    check("ra23 every published page this tool has an opinion about is byte-"
          "identical to what the commit carries, and every one of them really was "
          "compared: %r" % (_live,),
          _live["differs"] == [] and _live["unlooked"] == []
          and _live["compared"] == len(_live["subjects"]))


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


# --- cli ------------------------------------------------------------------------
def _tabled_artifacts():
    """Every artifact this tool compares, in the order it compares them."""
    return ([rel for rel, _m, _p, _r in ARTIFACTS]
            + [rel for rel, _b in GENERATED_ARTIFACTS])


def _write_recipe(rel):
    """Print how to refresh one artifact, or say that nothing records it."""
    how = refresh_for(rel)
    if how is None:
        sys.stdout.write("      nothing here records how to refresh this "
                         "artifact - add the command beside its table row\n")
        return
    for line in how.split("\n"):
        sys.stdout.write("      %s\n" % (line,))


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return _selftest()
    if "--how" in argv:
        for rel in _tabled_artifacts():
            sys.stdout.write("%s\n" % (rel,))
            _write_recipe(rel)
        for copy_rel, source_rel, _sides in COPY_PROVEN:
            sys.stdout.write("%s (a byte copy, checked by cmp not by a render)\n"
                             % (copy_rel,))
            sys.stdout.write("      refresh %s FIRST, then\n" % (source_rel,))
            sys.stdout.write("      cp %s %s\n" % (source_rel, copy_rel))
        sys.stdout.write("\nevery page above is also compared with what %s tracks. "
                         "A refreshed page nobody committed is reported UNCOMMITTED "
                         "and the repair is `git add` plus a commit, not another "
                         "render.\n" % (_HEAD,))
        return 0
    bad = drifted()
    for rel, detail in bad:
        sys.stdout.write("STALE %s - %s\n" % (rel, detail))
        _write_recipe(rel)
    # THE SECOND ARM, PRINTED APART FROM THE FIRST. A page can be stale on disk, or
    # current on disk and absent from the commit, and the two are repaired by
    # different acts - so they are two blocks of output rather than one word.
    head_lines, head_code = committed_report(uncommitted())
    for line in head_lines:
        sys.stdout.write(line + "\n")
    # The claim this tool makes about what it does NOT compare. Reported beside the
    # drift rather than in the docstring alone, because "docs/index.html is covered
    # by a cmp elsewhere" stops being true the moment that cmp goes, and a docstring
    # cannot notice.
    gaps = copy_check_missing()
    for copy_rel, side, problem in gaps:
        sys.stdout.write("UNCOVERED %s - %s %s\n" % (copy_rel, side, problem))
    if bad:
        sys.stdout.write("\n%d committed artifact(s) no longer match their source. "
                         "Re-render with the command printed under each, and commit "
                         "the result.\n" % len(bad))
    if bad or gaps or head_code:
        return 1
    sys.stdout.write("OK: %d committed artifact(s) match a fresh render, and every "
                     "byte copy this tool defers on is still compared where it says "
                     "it is\n" % (len(ARTIFACTS) + len(GENERATED_ARTIFACTS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
