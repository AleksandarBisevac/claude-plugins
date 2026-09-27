#!/usr/bin/env python3
"""Every COMMITTED rendered artifact must match what its source renders today.

WHY THIS EXISTS. `examples/acme-store/acme-store-audit.html` is the report a new
user opens first, and it carried OUTDATED `aria-label`s -- the ones a speech
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

AND THEY ARE ASKED AT DIFFERENT MOMENTS. Before a commit, the commit's question is red
for as long as a re-rendered page is uncommitted - every change that re-renders a page
with this repo's own recipe, until its commit. So `--selftest` - which the pre-commit
sweep runs - and `--before-commit` ask the fresh render alone, `--against-commit` asks
HEAD alone, and a run with no flag asks both. After a commit, `tools/verify.sh
--release` (`--against-commit`) and a no-flag run by hand are where the HEAD arm can
catch a page committed without its re-render. CI runs with no flag, but there the
checkout IS the commit, so that arm cannot fire. `arm_verdict()` names an arm a run
left out rather than going quiet about it, and `run_arms()` reads which arms the runner
and the workflow really ask.

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

Run it:   python3 tools/check-rendered-artifacts.py                   # both arms
          python3 tools/check-rendered-artifacts.py --before-commit   # the render
          python3 tools/check-rendered-artifacts.py --against-commit  # HEAD
          python3 tools/check-rendered-artifacts.py --how       # just the recipes
          python3 tools/check-rendered-artifacts.py --selftest
Exit 0 when every arm the run asks is clean and the copy check is still in place; 1
naming each artifact that is stale, each page the commit does not carry, and each
declared copy check that has gone; 2 on a usage error (an unknown flag, or both arm
flags at once). A page nobody could look up in `HEAD` is named rather than counted
either way, and a run that could look up NONE of them exits 1 saying so. Nothing is
written to the repo -- it renders into a temporary directory.
"""

import ast
import calendar
import io
import os
import re
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

    IT IS A GIT REPOSITORY, and the generator is what makes it one: the page shows
    a merged phase WHOLE only when git answers that a full run's head contains
    that merge, and a directory with no repository can only answer "could not be
    asked". The history is written as loose objects dated from the plan, so its
    commits - and the shas the page prints - are the same on every run. Nothing
    here runs git to build it, which is why the recipe below needs no step of its
    own for it; ra24 is what fails if the fixture stops being one.
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
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        remove_tree(work)
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


# --- which run asks which question --------------------------------------------
# THE COMMIT'S QUESTION IS THE WRONG ONE TO ASK BEFORE THE COMMIT. The fresh-render
# arm is a question about the working tree and holds at any moment. The HEAD arm is a
# question about a commit: asked of a working tree that is about to BECOME that
# commit, it is red for as long as a re-rendered page is uncommitted - which is every
# task that re-renders a page with this repo's own recipe, right up to the commit a
# gate has to be green before. That is where the HEAD arm used to sit - live in
# `--selftest`, which the pre-commit sweep runs - and every task that regenerated a
# page could only land by overriding the verdict.
#
# WHERE IT CAN CATCH SOMETHING. After a commit: a re-render committed without its
# page staged is what the arm exists for, and `tools/verify.sh --release` or a no-flag
# run by hand is where it is found before a push. On CI it cannot fire - the checkout
# IS the commit - so CI's no-flag run holds it only as the same call everybody makes;
# the fresh-render arm is what goes red there on a stale committed page.
#
# So each run names the arms it asks, and a run that leaves one out says so in its
# output rather than printing a verdict that reads as covering both:
#   * `--before-commit` - the fresh render only. The sweep (through `--selftest`,
#     which asks `SELFTEST_ARMS`) and a plain or `--affected` `tools/verify.sh` run.
#   * `--against-commit` - HEAD only. `tools/verify.sh --release`, whose plain half
#     has already asked the fresh render on the same tree.
#   * no flag - both. CI, and a run by hand after a commit.
# `run_arms()` reads those calls out of the runner and the workflow, so a flag moved
# on either is a failing case here rather than a sentence that stopped being true.
FRESH_ARM = "fresh"
HEAD_ARM = "head"
ALL_ARMS = (FRESH_ARM, HEAD_ARM)
BEFORE_COMMIT_ARMS = (FRESH_ARM,)
AGAINST_COMMIT_ARMS = (HEAD_ARM,)
ARM_FLAGS = (("--before-commit", BEFORE_COMMIT_ARMS),
             ("--against-commit", AGAINST_COMMIT_ARMS))
# What `--selftest` asks of this checkout. The sweep that runs it is pre-commit.
SELFTEST_ARMS = BEFORE_COMMIT_ARMS


def arms_for(argv):
    """(arms, problem) for a command line. Exactly one of the two is None.

    A flag this tool does not know is a problem and not a no-op: an unknown flag
    used to fall through to the full run, so a mistyped `--before-comit` would ask
    the very question it was typed to leave out. Both flags at once name no run.
    """
    known = [flag for flag, _arms in ARM_FLAGS]
    unknown = [a for a in argv if a not in known]
    if unknown:
        return None, "unknown argument(s): %s" % (" ".join(unknown),)
    picked = [arms for flag, arms in ARM_FLAGS if flag in argv]
    if len(picked) > 1:
        return None, ("%s asks the working tree and %s asks the commit; with no "
                      "flag at all this tool asks both" % tuple(known))
    return (picked[0] if picked else ALL_ARMS), None


# --- which arms the runner and the workflow really ask --------------------------
# AN EXACT-LINE PIN, NOT A PARSER. Reading shell and YAML by hand kept leaving one
# more spelling that read silently wrong - an `echo` of the call among them - so
# nothing here interprets either file. Every non-comment line that names
# this tool must, with its indentation stripped - and in ci.yml an optional leading
# `- ` and `run:` - EQUAL one of the call lines in `_CALL_LINES`, or it is refused
# by line. Beyond the exact line, `_context_problem` checks two things and no more:
# the line before its command - the nearest code line above the runner's `run
# "<label>"` wrapper, or above the call when there is none, may not contain `&`,
# `|`, a backslash or `#` anywhere (`_FORBIDDEN_ABOVE`; a plain `run: |` opener is
# exempt) - and, in ci.yml, its YAML context:
# a one-line `run:` with no deeper continuation, or a line in a plain `run: |`
# block. `run_arms()` then says which file, and which part of verify.sh, holds each
# exact line.
#
# DELIBERATELY STRICT: that rule reads no shell, so a correct but unusual line above
# a call is refused loudly rather than read.
#
# THE LIMITS, WHICH ARE WHAT A TEXT CHECK IS. It does not decide whether the line
# is reached at all: control flow above it - an `exit 0`, a `false && {`, an `if
# false; then ... fi` - is not read, and the release arm itself is a call inside an
# `if`. And it does not tell a call from an exact call line that some construct
# makes DATA rather than a command - a heredoc, a string opened on an earlier line,
# an array literal, arithmetic, or another key's block text. The second only
# matters if the real call is also removed, because ra29 pins each exact line to
# exactly one place - a second copy fails it too. Lines are split the way the shell
# splits them, at a newline only (`shell_lines`), and only space and tab count as
# blanks anywhere in the reader (`_BLANKS`).
_THIS_TOOL = "tools/check-rendered-artifacts.py"
_VERIFY_REL = "tools/verify.sh"
_CI_REL = ".github/workflows/ci.yml"
# THE SHELL'S BLANKS: space and tab, and nothing else. Every strip, split and
# pattern in the runner reader names them, because Python's no-argument forms and a
# regex's `\s` also take NBSP, a form feed, the Unicode separators and a carriage
# return - none of which the shell treats as a blank. ra29k reads the reader's AST
# for a helper that forgets.
_BLANKS = " \t"
_RELEASE_OPEN = re.compile(r'^if \[ "\$RELEASE" -eq 1 \]; then[ \t]*$')
_CALL_LINES = (("python3 %s" % (_THIS_TOOL,), ALL_ARMS),
               ("python3 %s --before-commit" % (_THIS_TOOL,), BEFORE_COMMIT_ARMS),
               ("python3 %s --against-commit" % (_THIS_TOOL,), AGAINST_COMMIT_ARMS))
_YAML_ONE_LINE = re.compile(r"^([ \t]*(?:-[ \t]+)?)run:[ \t]+(?P<call>.*)$")
_YAML_LITERAL = re.compile(r"^[ \t]*(?:-[ \t]+)?run:[ \t]*\|[-+]?[ \t]*$")
_RUNNER_WRAPPER = re.compile(r'^run "[^"]*" \\$')


def _indent(line):
    return len(line) - len(line.lstrip(_BLANKS))


def _next_value_line(lines, index):
    """The first line after `index` that is neither blank nor a full-line comment,
    or None."""
    for line in lines[index + 1:]:
        if line.strip(_BLANKS) and not _is_full_line_comment(line):
            return line
    return None


def _opener(lines, index):
    """The nearest earlier non-blank line indented less than line `index`, or None."""
    depth = _indent(lines[index])
    for line in reversed(lines[:index]):
        if line.strip(_BLANKS) and _indent(line) < depth:
            return line
    return None


# THE LINE BEFORE A CALL'S COMMAND MAY NOT CARRY ANY OF THESE, ANYWHERE. Deciding
# whether a `&&`, `|` or backslash on that line really continues into the call means
# lexing shell - comments, quotes, escapes - and every lexer written here leaked. So
# the rule is deliberately strict: a correct but unusual line above a call is
# refused loudly rather than read, and the repair is to move the call or the line.
_FORBIDDEN_ABOVE = ("&", "|", "\\", "#")


def _code_above(lines, index):
    """The index of the nearest earlier line that is neither blank nor a full-line
    comment, or None."""
    for k in range(index - 1, -1, -1):
        if lines[k].strip(_BLANKS) and not _is_full_line_comment(lines[k]):
            return k
    return None


def _is_full_line_comment(line):
    """A line whose first non-space character is `#` - in shell it never continues
    a command, whatever it ends in."""
    return line.lstrip(_BLANKS).startswith("#")


def _context_problem(lines, index, yaml):
    """Why the exact call line at `index` is not what runs there, or None.

    The call's command starts at the runner's wrapper - `run "<label>"` ended by a
    backslash - when that is the line directly above, and at the call line
    otherwise. The nearest earlier CODE line before that start (blank lines and
    full-line comments skipped) must contain none of `_FORBIDDEN_ABOVE`, anywhere;
    in ci.yml a plain `run: |` opener there is the block's edge and is exempt. In
    YAML the call is also read only (a) as a one-line `run: <call>` whose next
    value line is indented no deeper than the key, or (b) as a line whose nearest
    less-indented line is a plain `run: |`, `|-` or `|+` opener.
    """
    number = index + 1
    first = index
    if index > 0 and _RUNNER_WRAPPER.match(lines[index - 1].strip(_BLANKS)):
        first = index - 1
    before = _code_above(lines, first)
    if (before is not None and yaml and _YAML_LITERAL.match(lines[before])):
        before = None
    if before is not None and any(ch in lines[before] for ch in _FORBIDDEN_ABOVE):
        return ("lines %d to %d: line %d is the code line before the command that "
                "carries the call on line %d, and it contains one of %s - this check "
                "reads no shell, so such a line is refused rather than guessed at; "
                "put a plain command line (or none) directly above the call"
                % (before + 1, number, before + 1, number,
                   " ".join("`%s`" % (ch,) for ch in _FORBIDDEN_ABOVE)))
    if not yaml:
        return None
    one = _YAML_ONE_LINE.match(lines[index])
    if one:
        below = _next_value_line(lines, index)
        if below is not None and _indent(below) > len(one.group(1)):
            return ("line %d: the `run:` value continues onto a deeper line, so "
                    "what runs is not this line alone" % (number,))
        return None
    opener = _opener(lines, index)
    if opener is None or not _YAML_LITERAL.match(opener):
        return ("line %d: the call is not inside a plain `run: |` block (nor a "
                "one-line `run:`), so what runs is not this line as written"
                % (number,))
    return None


def shell_lines(text):
    """`text` split into lines the way the shell splits it: at a newline and at
    nothing else. `str.splitlines()` also breaks at a carriage return, a form feed,
    a vertical tab, the separators and NEL, none of which the shell treats as a line
    break - so a call hidden after one of them would read as its own line. The file
    is opened with `newline=""` for the same reason. One splitter serves both
    `call_lines` and `release_lines`, so their line numbers agree."""
    return text.split("\n")


def call_lines(text, yaml=False):
    """[(line number, arms or refusal)] for every non-comment line naming the tool.

    A line is read only if it EQUALS an exact call line (indentation stripped, and
    in YAML an optional leading `- ` and `run:`) AND `_context_problem` finds
    nothing - the second half catches the real call whose flag sits on another
    line. A refusal is a STRING naming the line, so a caller cannot read a line
    this check does not know as a call that asks nothing.
    """
    known = dict(_CALL_LINES)
    lines = shell_lines(text)
    out = []
    for index, line in enumerate(lines):
        number = index + 1
        bare = line.strip(_BLANKS)
        if not bare or bare.startswith("#") or _THIS_TOOL not in bare:
            continue
        if yaml:
            one = _YAML_ONE_LINE.match(line)
            bare = (one.group("call").strip(_BLANKS) if one
                    else re.sub(r"^-[ \t]+", "", bare, count=1))
        arms = known.get(bare)
        if arms is None:
            out.append((number,
                        "line %d names %s but is not one of the exact call lines "
                        "this tool knows (%s) - write the call as one of them, and "
                        "keep the name off any other line that is not a comment"
                        % (number, _THIS_TOOL,
                           "; ".join("`%s`" % (c,) for c, _a in _CALL_LINES))))
            continue
        problem = _context_problem(lines, index, yaml)
        out.append((number, arms if problem is None else problem))
    return out


def release_lines(text):
    """(first, last) line numbers of the runner's `--release` block, or None.

    The block opens on `if [ "$RELEASE" -eq 1 ]; then` and closes on the first `fi`
    at the start of a line after it. None when no block was found, so a runner that
    lost it is not read as one whose release asks nothing.
    """
    lines = shell_lines(text)
    opens = [i for i, line in enumerate(lines) if _RELEASE_OPEN.match(line)]
    if not opens:
        return None
    closes = [i for i in range(opens[0] + 1, len(lines)) if lines[i] == "fi"]
    if not closes:
        return None
    return opens[0] + 1, closes[0] + 1


def run_arms(repo_root=None):
    """{"plain", "release", "ci"}: [(line, arms or refusal)] each part holds.

    None for a part that could not be read - the file, or verify.sh's release
    block - so "found no call" and "could not look" never print the same way.
    """
    root = repo_root if repo_root is not None else REPO
    texts = {}
    for rel in (_VERIFY_REL, _CI_REL):
        try:
            with io.open(os.path.join(root, rel.replace("/", os.sep)),
                         encoding="utf-8", newline="") as fh:
                texts[rel] = fh.read()
        except (OSError, UnicodeDecodeError):
            texts[rel] = None
    ci = (call_lines(texts[_CI_REL], yaml=True)
          if texts[_CI_REL] is not None else None)
    if texts[_VERIFY_REL] is None:
        return {"plain": None, "release": None, "ci": ci}
    verify = call_lines(texts[_VERIFY_REL])
    block = release_lines(texts[_VERIFY_REL])
    if block is None:
        return {"plain": verify, "release": None, "ci": ci}
    inside = [c for c in verify if block[0] <= c[0] <= block[1]]
    return {"plain": [c for c in verify if c not in inside], "release": inside,
            "ci": ci}


def _recipe_lines(rel):
    """How to refresh one artifact, or a sentence saying that nothing records it."""
    how = refresh_for(rel)
    if how is None:
        return ["      nothing here records how to refresh this artifact - add the "
                "command beside its table row"]
    return ["      %s" % (line,) for line in how.split("\n")]


def arm_verdict(arms, root=None, subjects=None, drift=None):
    """([lines], exit code) for the named arms, and a line for each arm left out.

    PURE AT THE SEAMS a case needs: `drift` stands in for the render (a callable
    returning `drifted()`'s shape) and `root`/`subjects` point the HEAD arm at a
    fixture repository. An arm not asked is NAMED as not asked, because a run that
    printed nothing about the commit would read exactly like one whose commit
    carried every page.
    """
    lines, code = [], 0
    if FRESH_ARM in arms:
        bad = drifted() if drift is None else drift()
        for rel, detail in bad:
            lines.append("STALE %s - %s" % (rel, detail))
            lines.extend(_recipe_lines(rel))
        if bad:
            lines.append("%d committed artifact(s) no longer match their source. "
                         "Re-render with the command printed under each, and commit "
                         "the result." % (len(bad),))
            code = 1
        else:
            lines.append("OK: %d committed artifact(s) match a fresh render"
                         % (len(_tabled_artifacts()),))
    else:
        lines.append("NOT ASKED: whether the pages match a fresh render - this run "
                     "asks only what %s carries; `--before-commit` asks the "
                     "render" % (_HEAD,))
    if HEAD_ARM in arms:
        head_lines, head_code = committed_report(uncommitted(root, subjects))
        lines.extend(head_lines)
        code = max(code, head_code)
    else:
        lines.append("NOT ASKED: whether %s carries these pages - before a commit "
                     "it is red while any re-rendered page is uncommitted; after "
                     "one, `--against-commit` asks it (`tools/verify.sh --release` "
                     "runs that), and so does a run with no flag" % (_HEAD,))
    return lines, code


# --- selftest -----------------------------------------------------------------
def _cases(check):
    # TWO COMPUTATIONS, NOT ONE, and the reason is what this case used to be: it
    # compared the parse against a constant that its own arithmetic cancelled back
    # to a round number the parse never returns, then said `or ... is not None`.
    # The equality was false on every run and the case passed on the `or`, so what
    # it asserted was "parsing did not crash" while claiming to assert the epoch.
    _ra_stamp = "generated 2023-11-14 22:13 UTC"
    _ra_want = calendar.timegm((2023, 11, 14, 22, 13, 0, 0, 0, 0))
    # The pair a render is given must be ABSOLUTE and must not be re-based on
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
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        remove_tree(_probe_root)
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
    # The docstring above says docs/index.html is covered by a byte-copy
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
    #
    # IT ASKS `SELFTEST_ARMS`: this suite runs in the pre-commit sweep, and asking
    # it what the commit carries made every task that re-rendered a page red until
    # its own commit existed. ra25 asserts the constant leaves HEAD out; ra30 fails
    # on any git call this suite makes against this checkout while it runs.
    _live_lines, _live_code = arm_verdict(SELFTEST_ARMS)
    check("ra5 every committed rendered artifact matches what its source renders "
          "today - %r" % (_live_lines,), _live_code == 0)

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

    # THE FIXTURE IS A REPOSITORY GIT ITSELF RESOLVES, asked through this tool's
    # own git reader rather than by looking for a `.git` directory: a directory
    # git will not open is the state the page's UNKNOWN-for-everything came from.
    _repo_root = tempfile.mkdtemp(prefix="audit-fresh-repo-")
    try:
        _repo = _build_demo_fixture(_repo_root)
        _why = ("the fixture generator exited non-zero" if _repo is None
                else head_unavailable(_repo))
    finally:
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        remove_tree(_repo_root)
    check("ra24 the scale demo's fixture is a git repository whose HEAD git "
          "resolves, so the render can ask whether a full run contains a "
          "merge at all: %r" % (_why,), _why is None)

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
    """The arm that asks what the COMMIT carries, driven against real git.

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

        # THE SCENARIO THIS ARM EXISTS FOR, driven rather than described: re-render, leave
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
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        remove_tree(root)

    # A DIRECTORY THAT IS NOT A REPOSITORY, allocated rather than named, for the
    # reason the probe root above `ra6` is allocated: a fixed name is a name another
    # process can be using, and this case's whole claim is that git has nothing to
    # answer with here.
    _no_git = tempfile.mkdtemp(prefix="audit-head-nogit-")
    try:
        _refused = uncommitted(_no_git, subjects=[_HEAD_FX_REL, _HEAD_FX_ABSENT])
    finally:
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        remove_tree(_no_git)
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

    # NO LIVE CASE FOR THIS ARM, ON PURPOSE. It used to end here asking whether THIS
    # checkout's commit carries every page, and this suite runs before a commit
    # exists - see "which run asks which question" above. The live question is the
    # CLI's, and `_arm_cases` pins which run asks it.
    _arm_cases(check)


def _arm_cases(check):
    """Which run asks which question, driven over one real repository.

    The fixture is the state that used to fail the pre-commit sweep: a page whose
    working-tree bytes are the fresh render (the render is stood in for by `drift`,
    because what is under test is the choice of arms, not the renderer) and whose
    commit still holds the bytes from before the re-render.
    """
    _old = "<html>the render before this change</html>\n"
    _new = "<html>the render this change made</html>\n"
    def _matches_render():
        return []

    def _stale():
        return [(_HEAD_FX_REL, "differs from a fresh render")]

    root = _head_fixture(_old)
    try:
        _write_working(root, _HEAD_FX_REL, _new)
        _pre_lines, _pre_code = arm_verdict(BEFORE_COMMIT_ARMS, root=root,
                                            subjects=[_HEAD_FX_REL],
                                            drift=_matches_render)
        _neither_lines, _neither_code = arm_verdict(BEFORE_COMMIT_ARMS, root=root,
                                                    subjects=[_HEAD_FX_REL],
                                                    drift=_stale)
        _ci_arms = arms_for([])[0]
        _ci_lines, _ci_code = arm_verdict(_ci_arms, root=root,
                                          subjects=[_HEAD_FX_REL],
                                          drift=_matches_render)
        _rel_arms = arms_for(["--against-commit"])[0]
        _rel_lines, _rel_code = arm_verdict(_rel_arms, root=root,
                                            subjects=[_HEAD_FX_REL],
                                            drift=_stale)
    finally:
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        remove_tree(root)

    def _count(lines, prefix):
        return len([line for line in lines if line.startswith(prefix)])

    check("ra25 a page re-rendered by the change being prepared - current against "
          "a fresh render, not yet in HEAD - passes the before-commit arms, which "
          "are the ones this suite asks; they say the commit was NOT ASKED rather "
          "than going quiet about it: %r" % (_pre_lines,),
          _pre_code == 0
          and _count(_pre_lines, "UNCOMMITTED") == 0
          and _count(_pre_lines, "NOT ASKED") == 1
          and HEAD_ARM not in SELFTEST_ARMS
          and HEAD_ARM not in BEFORE_COMMIT_ARMS)
    # THE OTHER DIRECTION of ra25: an arm set that dropped the render along with the
    # commit would pass ra25 for ever while checking nothing at all.
    check("ra26 ...but a page matching NEITHER a fresh render nor HEAD still fails "
          "the before-commit arms, once, as STALE: %r" % (_neither_lines,),
          _neither_code == 1 and _count(_neither_lines, "STALE") == 1)
    check("ra27 ...and the run CI makes (no flag) and the one `verify.sh --release` "
          "makes (`--against-commit`) both still fail on a page the commit does "
          "not carry: %r / %r" % (_ci_lines, _rel_lines),
          _ci_code == 1 and _count(_ci_lines, "UNCOMMITTED") == 1
          and _rel_code == 1 and _count(_rel_lines, "UNCOMMITTED") == 1
          and _count(_rel_lines, "STALE") == 0)
    _both, _both_problem = arms_for(["--before-commit", "--against-commit"])
    _typo, _typo_problem = arms_for(["--before-comit"])
    check("ra28 the flags map to the arms they name, no flag asks both, and a "
          "mistyped or contradictory flag is a usage error rather than a quiet "
          "fall-through to some other run: %r" % ((_both_problem, _typo_problem),),
          arms_for([]) == (ALL_ARMS, None)
          and arms_for(["--before-commit"]) == (BEFORE_COMMIT_ARMS, None)
          and arms_for(["--against-commit"]) == (AGAINST_COMMIT_ARMS, None)
          and _both is None and _both_problem is not None
          and _typo is None and "--before-comit" in (_typo_problem or ""))

    # THE CALLS THE RUNS REALLY MAKE, pinned by exact line. gate-parity names a gate
    # by its script and ignores its flags, so without this a flag moved on either
    # file left every check here green. Each exact line sits in exactly one place.
    _runs = run_arms()
    _found = dict((part, None if calls is None else [c for _n, c in calls])
                  for part, calls in _runs.items())
    check("ra29 each run carries its exact call line, exactly once and nothing else "
          "naming this tool: verify.sh's plain run `--before-commit`, its --release "
          "block `--against-commit`, ci.yml the line with no flag: %r" % (_runs,),
          _found == {"plain": [BEFORE_COMMIT_ARMS],
                     "release": [AGAINST_COMMIT_ARMS], "ci": [ALL_ARMS]})
    _fx_runner = ("run \"x\" \\\n  python3 %s --before-commit\n"
                  "if [ \"$RELEASE\" -eq 1 ]; then\n"
                  "  python3 %s --against-commit\n"
                  "fi\n" % ((_THIS_TOOL,) * 2))
    # A form feed inside the block is no line break to the shell, so it must not
    # move the block's end either.
    _fx_ff = ("run \"x\" \\\n  python3 %s --before-commit\n"
              "if [ \"$RELEASE\" -eq 1 ]; then\n"
              "  echo a\x0cb\n"
              "  python3 %s --against-commit\n"
              "fi\n" % ((_THIS_TOOL,) * 2))
    # THE FILES ARE READ AS THE SHELL READS THEM: a carriage return written into
    # verify.sh stays inside its line. Opened with universal newlines it would
    # become a line break, and the call after it would read as the plain run's.
    _cr_root = tempfile.mkdtemp(prefix="audit-cr-runs-")
    try:
        for rel, body in (
                (_VERIFY_REL, 'run "x" \\\n: \r  python3 %s --before-commit\n'
                              'if [ "$RELEASE" -eq 1 ]; then\n'
                              '  python3 %s --against-commit\nfi\n'
                              % ((_THIS_TOOL,) * 2)),
                (_CI_REL, "        run: |\n          python3 %s\n" % (_THIS_TOOL,))):
            path = os.path.join(_cr_root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(path))
            with io.open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(body)
        _cr_runs = run_arms(_cr_root)
    finally:
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        remove_tree(_cr_root)
    check("ra29j a carriage return inside verify.sh's call line stays inside it when "
          "the file is read, so the plain run is refused by line rather than read "
          "as `--before-commit`: %r" % (_cr_runs,),
          len(_cr_runs["plain"] or []) == 1
          and isinstance(_cr_runs["plain"][0][1], str)
          and "line 2 " in _cr_runs["plain"][0][1]
          and [c for _n, c in _cr_runs["release"] or []] == [AGAINST_COMMIT_ARMS]
          and [c for _n, c in _cr_runs["ci"] or []] == [ALL_ARMS])
    # THE SHELL'S BLANKS ARE SPACE AND TAB, AND NOTHING ELSE. Python's no-argument
    # strip and split, and a regex's `\s`, also take NBSP, a form feed, the Unicode
    # separators and a carriage return - so every helper the runner reader reaches
    # must name its blanks. Read off the AST, so the next helper is covered too.
    _blank_leaks = _reader_blank_leaks()
    check("ra29k no function the runner reader reaches strips, splits or matches "
          "whitespace the shell does not: no argument-less strip/lstrip/rstrip/split, "
          "no splitlines, and no `\\s` in the reader's patterns: %r" % (_blank_leaks,),
          _blank_leaks == [])
    _planted_leak = ("def call_lines(text):\n    return _helper(text)\n"
                     "def _helper(text):\n    return text.strip()\n"
                     "def unrelated(text):\n    return text.split()\n")
    _seen = _reader_blank_leaks(_planted_leak)
    check("ra29l ...and that walk follows the reader's calls: a no-argument strip in a "
          "helper `call_lines` reaches is reported by its function and line, while "
          "the same kind of call in a function the reader never reaches is not: %r"
          % (_seen,), _seen == ["_helper:4 .strip()"])
    check("ra29b the release block is found by its opening and closing lines, and a "
          "runner with none reads as None rather than as a release asking nothing: "
          "%r" % ((release_lines(_fx_runner),),),
          release_lines(_fx_runner) == (3, 5)
          and release_lines("python3 %s\n" % (_THIS_TOOL,)) is None
          and release_lines(_fx_ff) == (3, 6))
    # THE EXACT-LINE PIN, both directions. Read: each call line in `_CALL_LINES`,
    # indentation stripped, and in YAML a leading `- ` and `run:`.
    _t = _THIS_TOOL
    _read_ok = {
        "plain": (_pinned("  python3 %s --before-commit\n" % (_t,)),
                  [BEFORE_COMMIT_ARMS]),
        "no flag": (_pinned("python3 %s\n" % (_t,)), [ALL_ARMS]),
        "tabs": (_pinned("\tpython3 %s --against-commit  \n" % (_t,)),
                 [AGAINST_COMMIT_ARMS]),
        "comment": (_pinned("# python3 %s --against-commit\n" % (_t,)), []),
        "yaml item": (_pinned("      - run: python3 %s\n" % (_t,), yaml=True),
                      [ALL_ARMS]),
        "yaml key": (_pinned("        run: python3 %s --before-commit\n" % (_t,),
                             yaml=True), [BEFORE_COMMIT_ARMS]),
        "yaml block line": (_pinned("        run: |\n"
                                    "          set -e\n"
                                    "          python3 %s --against-commit\n"
                                    % (_t,), yaml=True), [AGAINST_COMMIT_ARMS]),
        "yaml |- block": (_pinned("      - run: |-\n          python3 %s\n"
                                  % (_t,), yaml=True), [ALL_ARMS]),
        "yaml |+ block": (_pinned("      - run: |+\n\n          python3 %s "
                                  "--before-commit\n" % (_t,), yaml=True),
                          [BEFORE_COMMIT_ARMS]),
        "yaml one-line, comment below": (
            _pinned("      - run: python3 %s --before-commit\n"
                    "          # a note, not part of the value\n" % (_t,),
                    yaml=True), [BEFORE_COMMIT_ARMS]),
        "runner wrapper": (_pinned('run "x" \\\n  python3 %s --before-commit\n'
                                   % (_t,)), [BEFORE_COMMIT_ARMS]),
        "comments ending in a continuation": (_pinned(
            "# a note that ends in a backslash \\\n# and one that ends in &&\n"
            'run "x" \\\n  python3 %s --before-commit\n' % (_t,)),
            [BEFORE_COMMIT_ARMS]),
        "a comment ending in a backslash right above": (_pinned(
            "# a note that ends in a backslash \\\n  python3 %s --against-commit\n"
            % (_t,)), [AGAINST_COMMIT_ARMS]),
        "a call right under `run: |`": (_pinned(
            "      - run: |\n          python3 %s --against-commit\n" % (_t,),
            yaml=True), [AGAINST_COMMIT_ARMS]),
        "a finished command above": (_pinned(
            "set -e\n\n  python3 %s --against-commit\n" % (_t,)),
            [AGAINST_COMMIT_ARMS]),
    }
    _wrong = dict((k, got) for k, (got, want) in _read_ok.items() if got != want)
    check("ra29g each exact call line the tool knows is read as its arms - no "
          "flag, `--before-commit`, `--against-commit` - after its indentation, "
          "and in YAML a leading `- ` and `run:`, are stripped; a comment line is "
          "no call: wrongly read %r" % (_wrong,), _wrong == {})
    # Refused: every other non-comment line naming the tool, each by its line -
    # the echo is the one that reads as a call by accident.
    _refuse = [
        "echo Running: python3 %s --against-commit" % (_t,),
        "ls %s" % (_t,),
        "python3 %s --against-commit 2>&1" % (_t,),
        "python3 -u %s" % (_t,),
        "python3 %s --before-commit --against-commit" % (_t,),
        "python3 ./%s" % (_t,),
        "run: python3 %s" % (_t,),
    ]
    _yaml_refuse = ['      - run: "python3 %s"' % (_t,),
                    "      - name: python3 %s" % (_t,)]
    _not_refused = [line for line in _refuse
                    if not _refused_once(_pinned("x\n" + line + "\n"))]
    _not_refused += [line for line in _yaml_refuse
                     if not _refused_once(_pinned("x\n" + line + "\n", yaml=True))]
    check("ra29h every other non-comment line that names the tool is REFUSED by "
          "its line - an `echo` of the call, a mention, a redirection, an "
          "interpreter flag, both flags, another spelling of the path, a `run:` "
          "prefix outside YAML, a quoted or foreign YAML value: not refused %r"
          % (_not_refused,), _not_refused == [])
    # THE REAL CALL WITH ITS FLAG ELSEWHERE: the line reads as the no-flag call
    # while what runs is another command. In YAML, a flag on a continuation line of
    # the run's own value; in shell, a call continued from a line that is not the
    # runner's wrapper, so the tool never runs at all.
    _continued = {
        "folded >": _pinned("      - run: >\n          python3 %s\n"
                            "          --against-commit\n" % (_t,), yaml=True),
        "folded >-": _pinned("      - run: >-\n          python3 %s\n"
                             "          --against-commit\n" % (_t,), yaml=True),
        "plain, continued": _pinned("      - run: python3 %s\n"
                                    "          --against-commit\n" % (_t,),
                                    yaml=True),
        "echo \\": _pinned('echo "x" \\\n  python3 %s --against-commit\n' % (_t,)),
        ": \\": _pinned(': \\\n  python3 %s --against-commit\n' % (_t,)),
    }
    # THE LINE BEFORE THE COMMAND - above the wrapper, or above the call when there
    # is none - may not contain `&`, `|`, a backslash or `#`: every spelling a review
    # found that hid a continuation there, refused without reading any shell.
    # (line the refusal must name, fixture)
    _chained = {
        "echo \\ above the wrapper": (1, _pinned(
            'echo "x" \\\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        ": \\ above the wrapper": (1, _pinned(
            ': \\\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "true || above the wrapper": (1, _pinned(
            'true ||\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "true || above the call": (1, _pinned(
            "true ||\n  python3 %s --against-commit\n" % (_t,))),
        "echo x | above the call": (1, _pinned(
            "echo x |\n\n  python3 %s --against-commit\n" % (_t,))),
        "false && # comment above the wrapper": (1, _pinned(
            'false && # skip\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "true || # comment above the call": (1, _pinned(
            "true || # c\n  python3 %s --against-commit\n" % (_t,))),
        "echo x | # comment above the call": (1, _pinned(
            "echo x | # c\n  python3 %s --against-commit\n" % (_t,))),
        "a quoted # before && above the call": (1, _pinned(
            'echo "a # b" &&\n  python3 %s --against-commit\n' % (_t,))),
        "&&# with no space": (1, _pinned(
            'false &&# c\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "||# with no space": (1, _pinned(
            'false ||# c\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "|# with no space": (1, _pinned(
            'echo x |# c\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "an escaped double quote": (1, _pinned(
            'false \\" && # c\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "an escaped single quote": (1, _pinned(
            "false \\' && # c\nrun \"y\" \\\n  python3 %s --against-commit\n"
            % (_t,))),
        "a quoted escaped quote": (1, _pinned(
            'false "a \\" b" && # c\nrun "y" \\\n  python3 %s --against-commit\n'
            % (_t,))),
        "an escaped space, then # and &&": (1, _pinned(
            'false \\ #x &&\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "a comment ending in a backslash, then a blank line": (1, _pinned(
            'false && # note \\\n\nrun "y" \\\n  python3 %s --against-commit\n'
            % (_t,))),
        "a comment ending in a backslash, then a comment line": (1, _pinned(
            'false && # note \\\n# more\nrun "y" \\\n  python3 %s --against-commit\n'
            % (_t,))),
        "a trailing comment on the line above": (1, _pinned(
            "echo ok # a note\n  python3 %s --against-commit\n" % (_t,))),
        "a backslash before a comment": (1, _pinned(
            "echo done \\ # a note\n  python3 %s --against-commit\n" % (_t,))),
        "&&# in a run: | body": (2, _pinned(
            "      - run: |\n          false &&# c\n          python3 %s\n" % (_t,),
            yaml=True)),
        "a comment ending in a backslash in a run: | body": (2, _pinned(
            "      - run: |\n          false && # n \\\n\n          python3 %s\n"
            % (_t,), yaml=True)),
        "a form feed splits the call line": (2, _pinned(
            'run "y" \\\n: \x0c  python3 %s --against-commit\n' % (_t,))),
        "a carriage return splits the call line": (2, _pinned(
            'run "y" \\\n: \r  python3 %s --against-commit\n' % (_t,))),
        "a line separator splits the call line": (2, _pinned(
            'run "y" \\\n: \u2028  python3 %s --against-commit\n' % (_t,))),
        "a CRLF one-line run: in YAML": (1, _pinned(
            "      - run: python3 %s --against-commit\r\n" % (_t,), yaml=True)),
        "a CRLF call line": (1, _pinned(
            "python3 %s --against-commit\r\n" % (_t,))),
        "NBSP before `# n \\` above the wrapper": (1, _pinned(
            '\u00a0# n \\\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "FF before `# n \\` above the wrapper": (1, _pinned(
            '\x0c# n \\\nrun "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "NBSP before `# n \\` above the call": (1, _pinned(
            "\u00a0# n \\\n  python3 %s --against-commit\n" % (_t,))),
        "FF before `# n \\` above the call": (1, _pinned(
            "\x0c# n \\\n  python3 %s --against-commit\n" % (_t,))),
        "an NBSP-indented wrapper": (1, _pinned(
            '\u00a0run "y" \\\n  python3 %s --against-commit\n' % (_t,))),
        "FF before `# n \\` in a run: | body": (2, _pinned(
            "      - run: |\n          \x0c# n \\\n          python3 %s\n" % (_t,),
            yaml=True)),
        "false && in a run: | body": (2, _pinned(
            "      - run: |\n          false &&\n          python3 %s\n" % (_t,),
            yaml=True)),
    }
    _chain_read = dict((k, got) for k, (_n, got) in _chained.items()
                       if not (len(got) == 1 and isinstance(got[0], str)))
    _chain_unnamed = [k for k, (n, got) in _chained.items()
                      if ("line %d " % (n,)) not in str(got)]
    _read_anyway = dict((k, got) for k, got in _continued.items()
                        if not (len(got) == 1 and isinstance(got[0], str)))
    _both_named = [k for k in ("echo \\", ": \\")
                   if not ("line 1" in str(_continued[k]) and "line 2" in
                           str(_continued[k]))]
    check("ra29i the real call line is REFUSED when what runs is not it: a YAML "
          "`run: >`/`>-` or a plain `run:` continued onto a deeper line (the flag "
          "sits on the continuation), and a shell call continued from a line that "
          "is not the runner's `run \"<label>\" \\` wrapper, naming both lines: "
          "read anyway %r, both lines not named %r; and when the code line before "
          "the command - above the wrapper or the call - contains `&`, `|`, a "
          "backslash or `#` anywhere, naming that line: read anyway %r, line not "
          "named %r"
          % (_read_anyway, _both_named, _chain_read, _chain_unnamed),
          _read_anyway == {} and _both_named == []
          and _chain_read == {} and _chain_unnamed == [])


# --- no case asks git about this checkout, measured while the cases run --------
# The pre-commit sweep runs this suite, and a question put to this checkout's HEAD
# from inside it is the one this file stopped asking there. A rule over the SOURCE
# could only look for spellings - a call with no root - and `uncommitted(REPO)` or
# `head_text(REPO, ...)` got past it. So the seam every HEAD question goes through,
# `_git`, is swapped for a recorder while the cases run, and a call it saw against
# this checkout is a failing case naming the function and line that made it.
# WHAT IT CANNOT SEE: git run by something other than `_git`. This file does run
# git that way, but only against repositories it builds for a case - the fixture
# `_head_fixture` commits, and the staging in `_head_cases` - never against this
# checkout.
_GIT_SEAM = _git


def _case_caller():
    """"<function>:<line>" of the nearest selftest function on the stack."""
    frame = sys._getframe(2)
    while frame is not None:
        name = frame.f_code.co_name
        if name.endswith("_cases") or name.startswith("_planted"):
            return "%s:%d" % (name, frame.f_lineno)
        frame = frame.f_back
    return "outside any case"


def _recording_git(calls, root, real):
    """A `_git` that notes every call made against `root` or any directory under
    it - git answers those about the same repository - then makes it. Under means
    a path separator follows, so a sibling that only shares the name's prefix is
    not this checkout."""
    target = os.path.realpath(root)

    def recording(git_root, args):
        where = os.path.realpath(git_root)
        if where == target or where.startswith(target + os.sep):
            calls.append("%s git %s" % (_case_caller(), args[0] if args else ""))
        return real(git_root, args)
    return recording


def _planted_repo_call():
    """What ra30b plants: a HEAD question put to this checkout by name."""
    return uncommitted(REPO, subjects=[_HEAD_FX_REL])


def _planted_subdir_call():
    """...and the same question put to a directory INSIDE this checkout, which
    git answers about the same repository."""
    return head_unavailable(os.path.join(REPO, "tools"))


def _seam_cases(check):
    """The recorder itself: it catches a planted call, and not a fixture's."""
    inner = []
    outer = globals()["_git"]
    globals()["_git"] = _recording_git(inner, REPO, _GIT_SEAM)
    root = None
    try:
        _planted_repo_call()
        caught = list(inner)
        _planted_subdir_call()
        caught_sub = inner[len(caught):]
        caught = list(inner)
        root = _head_fixture("<html>fixture</html>\n")
        uncommitted(root, subjects=[_HEAD_FX_REL])
        after_fixture = list(inner)
    finally:
        globals()["_git"] = outer
        if root is not None:
            from _suite import remove_tree   # tools/_suite.py says why the import is here
            remove_tree(root)
    check("ra30b the recorder catches `uncommitted(REPO)` - a call that names a "
          "root and still asks this checkout - naming the function it came from, "
          "and records nothing for the same question put to a fixture repository: "
          "%r" % (after_fixture,),
          caught != []
          and all(c.startswith(("_planted_repo_call:", "_planted_subdir_call:"))
                  for c in caught)
          and after_fixture == caught)
    _sibling = []
    _probe = _recording_git(_sibling, REPO, lambda root, args: None)
    _probe(REPO + "-sibling", ["status"])
    check("ra30c a directory UNDER this checkout is this checkout - a question put "
          "to it is caught too - while a sibling whose name merely starts with the "
          "checkout's is not: %r / %r" % (caught_sub, _sibling),
          len(caught_sub) == 1
          and caught_sub[0].startswith("_planted_subdir_call:")
          and _sibling == [])


def _recorded_cases(check):
    """Every case, with the `_git` seam recording calls against this checkout."""
    calls = []
    seam = globals()["_git"]
    globals()["_git"] = _recording_git(calls, REPO, seam)
    try:
        _cases(check)
        _seam_cases(check)
    finally:
        globals()["_git"] = seam
    check("ra30 no case asked git about THIS checkout while the suite ran - the "
          "pre-commit sweep runs it, so a HEAD question here is the one this file "
          "moved out of it: %r" % (calls,), calls == [])


_READER_ROOTS = ("call_lines", "release_lines", "run_arms")
_READER_PATTERNS = ("_RELEASE_OPEN", "_YAML_ONE_LINE", "_YAML_LITERAL",
                    "_RUNNER_WRAPPER")


def _reader_blank_leaks(source=None):
    """["<function>:<line> <call>"] - a whitespace test the shell would not make,
    in any module-level function the runner reader reaches from `_READER_ROOTS`,
    plus any reader pattern that uses `\\s`."""
    if source is None:
        with io.open(os.path.abspath(__file__), encoding="utf-8") as fh:
            source = fh.read()
    tree = ast.parse(source)
    funcs = dict((node.name, node) for node in tree.body
                 if isinstance(node, ast.FunctionDef))
    reached, todo = set(), list(_READER_ROOTS)
    while todo:
        name = todo.pop()
        if name in reached or name not in funcs:
            continue
        reached.add(name)
        todo.extend(n.func.id for n in ast.walk(funcs[name])
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name))
    out = []
    for name in sorted(reached):
        for node in ast.walk(funcs[name]):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                continue
            attr = node.func.attr
            if (attr in ("strip", "lstrip", "rstrip", "split") and not node.args) \
                    or attr == "splitlines":
                out.append("%s:%d .%s()" % (name, node.lineno, attr))
        out.extend("%s:%d a pattern using \\s" % (name, node.lineno)
                   for node in ast.walk(funcs[name])
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and "\\s" in node.value)
    out.extend("%s uses \\s" % (name,) for name in _READER_PATTERNS
               if "\\s" in globals()[name].pattern)
    return out


def _pinned(text, yaml=False):
    """What the pin makes of `text`: one entry per line naming the tool."""
    return [c for _n, c in call_lines(text, yaml=yaml)]


def _refused_once(got):
    """Whether a reader's answer is exactly one refusal, naming line 2."""
    return (len(got) == 1 and isinstance(got[0], str) and "line 2" in got[0])


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_recorded_cases)


# --- cli ------------------------------------------------------------------------
def _tabled_artifacts():
    """Every artifact this tool compares, in the order it compares them."""
    return ([rel for rel, _m, _p, _r in ARTIFACTS]
            + [rel for rel, _b in GENERATED_ARTIFACTS])


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return _selftest()
    if "--how" in argv:
        for rel in _tabled_artifacts():
            sys.stdout.write("%s\n" % (rel,))
            for line in _recipe_lines(rel):
                sys.stdout.write(line + "\n")
        for copy_rel, source_rel, _sides in COPY_PROVEN:
            sys.stdout.write("%s (a byte copy, checked by cmp not by a render)\n"
                             % (copy_rel,))
            sys.stdout.write("      refresh %s FIRST, then\n" % (source_rel,))
            sys.stdout.write("      cp %s %s\n" % (source_rel, copy_rel))
        sys.stdout.write("\na run that asks %s - no flag, or `--against-commit` - "
                         "also compares every page above with what it tracks. A "
                         "refreshed page nobody committed is then reported "
                         "UNCOMMITTED and the repair is `git add` plus a commit, not "
                         "another render. `--before-commit` does not ask it.\n"
                         % (_HEAD,))
        return 0
    arms, problem = arms_for(argv)
    if problem is not None:
        sys.stderr.write("check-rendered-artifacts.py: %s\n" % (problem,))
        return 2
    # THE TWO ARMS, PRINTED APART. A page can be stale on disk, or current on disk
    # and absent from the commit, and the two are repaired by different acts - so
    # they are two blocks of output rather than one word.
    lines, code = arm_verdict(arms)
    for line in lines:
        sys.stdout.write(line + "\n")
    # The claim this tool makes about what it does NOT compare. Reported beside the
    # drift rather than in the docstring alone, because "docs/index.html is covered
    # by a cmp elsewhere" stops being true the moment that cmp goes, and a docstring
    # cannot notice.
    gaps = copy_check_missing()
    for copy_rel, side, problem in gaps:
        sys.stdout.write("UNCOVERED %s - %s %s\n" % (copy_rel, side, problem))
    if code or gaps:
        return 1
    sys.stdout.write("OK: every byte copy this tool defers on is still compared "
                     "where it says it is\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
