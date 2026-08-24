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
Exit 0 when every artifact is current and the copy check is still in place, 1 naming
each artifact that is stale and each declared copy check that has gone, 2 on a usage
error. Nothing is written to the repo -- it renders into a temporary directory.
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
        return 0
    bad = drifted()
    for rel, detail in bad:
        sys.stdout.write("STALE %s - %s\n" % (rel, detail))
        _write_recipe(rel)
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
    if bad or gaps:
        return 1
    sys.stdout.write("OK: %d committed artifact(s) match a fresh render, and every "
                     "byte copy this tool defers on is still compared where it says "
                     "it is\n" % (len(ARTIFACTS) + len(GENERATED_ARTIFACTS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
