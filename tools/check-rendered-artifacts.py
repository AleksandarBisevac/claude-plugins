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

Run it:   python3 tools/check-rendered-artifacts.py
          python3 tools/check-rendered-artifacts.py --selftest
Exit 0 when every artifact is current, 1 naming each that is stale, 2 on a usage
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STAMP = re.compile(r"generated (\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}) UTC")

# (committed artifact, manifest, project dir). The project dir is what
# CLAUDE_PROJECT_DIR must be for the render to find the ledger beside the plan.
ARTIFACTS = [
    ("examples/acme-store/acme-store-audit.html",
     "examples/acme-store/audit-plan.json", "examples/acme-store"),
    ("examples/acme-store/acme-store-audit.md",
     "examples/acme-store/audit-plan.json", "examples/acme-store"),
]

# Rendered from a fixture this tool generates rather than from a committed
# manifest, so it carries its own entry: (artifact, rendered basename).
GENERATED_ARTIFACTS = [
    ("docs/demo-large.html", "demo-large.html"),
]


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
        [sys.executable, os.path.join(scripts, "demo", "gen-demo-manifest.py"),
         project, "--phases", "40", "--tasks", "5"],
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


def drifted(artifacts=None):
    """[(path, detail), ...] -- committed artifacts a fresh render disagrees with."""
    out = []
    work = tempfile.mkdtemp(prefix="audit-fresh-")
    try:
        rendered = {}
        for rel, manifest, project in (artifacts or ARTIFACTS):
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
        for rel, basename in GENERATED_ARTIFACTS:
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
            project = _build_demo_fixture(os.path.join(work, "gen"))
            if project is None:
                out.append((rel, "the fixture generator exited non-zero, so this "
                                 "artifact could not be compared at all"))
                continue
            sub = os.path.join(work, "genout")
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
    _fx = os.path.join(tempfile.gettempdir(), "audit-fresh-probe")
    _ra_manifest, _ra_project = render_args(_fx)
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
              for rel, _m, _p in ARTIFACTS)
          and all(os.path.exists(os.path.join(REPO, rel))
                  for rel, _b in GENERATED_ARTIFACTS))
    # The live one, and it is deliberately last for the reader rather than for the
    # stream: the shared runner prints nothing until every case has run, so a slow
    # render delays the whole report and the ordering buys no early news. What it
    # does buy is a report whose expensive case is the last line before the tally.
    _live = drifted()
    check("ra5 every committed rendered artifact matches what its source renders "
          "today - %r" % (_live,), _live == [])


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


def main():
    if "--selftest" in sys.argv[1:]:
        return _selftest()
    bad = drifted()
    for rel, detail in bad:
        sys.stdout.write("STALE %s - %s\n" % (rel, detail))
    if bad:
        sys.stdout.write("\n%d committed artifact(s) no longer match their source. "
                         "Re-render and commit them.\n" % len(bad))
        return 1
    sys.stdout.write("OK: %d committed artifact(s) match a fresh render\n"
                     % (len(ARTIFACTS) + len(GENERATED_ARTIFACTS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
