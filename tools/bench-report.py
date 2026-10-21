#!/usr/bin/env python3
"""
Time a full report render at two plan sizes, phase by phase.

    tools/bench-report.py

It left `render-report.py --bench`: a benchmark is something the repository's
maintainers run, and the shipped entry point carried it into every install. It
prints numbers a human can run twice and compare and never fails - the section
comment below carries the argument for each choice (phases timed separately,
best-of-N, no CI threshold).

Its fixture is built by RUNNING the two demo generators under `tools/demo/`, and
its best-of-N timer is `_usage_bench._time_best`, the one definition the ledger
benchmark shares.

This file carries no `--selftest` of its own; its cases live in
`tests/test_bench_report.py`. Exit codes: 0 every scale ran - 1 a scale failed -
2 usage error.
"""
import os
import sys

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`
# (the same shape as `tools/where.py`). `tools/` goes on the path too, because
# `_usage_bench` sits beside this file.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
for _p in (_scripts, _here):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _output  # noqa: E402  (the anchor: install_path, safe_stdio)

_output.install_path()

import _loader  # noqa: E402  (loads render-report.py, a hyphenated entry point, as a library)
import _manifest_io  # noqa: E402  (the manifest loader the render reads through)
import _usage_bench  # noqa: E402  (the one best-of-N timer both benches share)

DEMO_DIR = os.path.join(_here, "demo")
R = _loader.load_script("render-report.py", modname="render_report")


# --- bench ----------------------------------------------------------------------
# WHY, AND WHY IT IS NOT A GATE. Until this landed there was not one `perf_counter`
# or benchmark in the repository, while several comments stated measured costs that
# nobody — including their author — could produce again. This prints numbers a human
# can run twice and compare; it is deliberately NOT a CI threshold, because a shared
# runner's noise floor is wider than the regressions worth catching and a gate that
# flaps teaches people to ignore it.
#
# PHASES SEPARATELY, NEVER ONE TOTAL. Earlier profiling claimed the ledger analytics
# dominate the HTML build several times over. Whether that is still true is exactly
# what a single total would hide — and the two grow with DIFFERENT things: the ledger
# pass with rows, everything else with the plan. So each phase is timed on its own
# and printed against the denominator that makes it comparable across scales.
#
# BEST-OF-N, NOT THE MEAN, and the definition of that has ONE home:
# `_usage_bench._time_best`.
_BENCH_SCALES = ((10, 5), (50, 20))
_BENCH_REPEATS = 3

# Which denominator makes each phase comparable across scales. The ledger pass grows
# with ROWS; everything else grows with the PLAN. `bn5` pins that this table covers
# exactly the phases `_bench_phases` returns, so a phase added later without a
# denominator fails by name instead of printing a bare millisecond figure.
_BENCH_PER = {"validate": "task", "rollup": "task", "usage load": "row",
              "html": "task", "markdown": "task"}


def _bench_fixture(out_dir, phases, tasks):
    """Build the demo manifest AND a matching ledger in `out_dir`, by RUNNING the
    two generators. Returns {manifestPath, tasks, rows, ledgerDir}.

    `gen-demo-manifest.py` and `gen-demo-usage.py` already produce exactly this
    fixture, deterministically - hand-rolling a third one here would be a fixture
    that nothing else validates. They are run as COMMANDS, the same way ci.yml and
    tools/capture-screenshots.mjs build the demo: out of process, the fixture build
    cannot contaminate what it is a fixture for - its imports, its loader cache and
    its garbage stay out of the very process whose timings this reports.

    A generator that fails raises with its stderr attached rather than leaving the
    caller to time an empty directory and report a suspiciously fast render.
    """
    import subprocess
    # Resolved by BASENAME under `tools/demo/`: a miss raises here, naming the file
    # and how many were searched, instead of handing `subprocess` a path nothing
    # put a file at.
    gen_manifest = _loader.script_path("gen-demo-manifest.py", root=DEMO_DIR)
    gen_usage = _loader.script_path("gen-demo-usage.py", root=DEMO_DIR)
    manifest_path = os.path.join(out_dir, "audit-plan.json")
    # The generators do not read it, but the bench must never be one environment
    # variable away from resolving a ledger somewhere else on this machine.
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    for cmd in ([sys.executable, gen_manifest, out_dir,
                 "--phases", str(phases), "--tasks", str(tasks)],
                [sys.executable, gen_usage, manifest_path]):
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                "%s exited %d: %s" % (os.path.basename(cmd[1]), proc.returncode,
                                      (proc.stderr or b"").decode("utf-8",
                                                                  "replace").strip()))
    ledger_dir = os.path.join(out_dir, ".claude", "usage")
    rows = 0
    for name in sorted(os.listdir(ledger_dir)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(ledger_dir, name), "r", encoding="utf-8") as fh:
            rows += sum(1 for line in fh if line.strip())
    return {"manifestPath": manifest_path, "ledgerDir": ledger_dir,
            "tasks": phases * tasks, "rows": rows}


def _bench_phases(manifest, manifest_path, project_dir):
    """`(label, thunk)` for the five phases of a render, in the order `main()`
    runs them.

    Each thunk hands its output to the next through one dict, because that is what
    `main()` does: the summary is rollup's output and both writers need it. Timing
    them separately is the whole point — see the section note above.

    `load_usage` is handed `project_dir` EXPLICITLY. Left to itself it falls back to
    `CLAUDE_PROJECT_DIR`, which every Claude Code session sets to the real
    repository — the bench would then load, time and report THIS repo's own live
    ledger instead of the fixture's, and the number would look perfectly reasonable.
    """
    lib = R._load_status_lib()
    vm = R._manifest_rules
    out = {}

    def _validate():
        out["findings"], out["warnings"] = vm.validate(manifest)
        return out["findings"]

    def _rollup():
        out["summary"] = lib.rollup(manifest, out.get("findings") or [],
                                    out.get("warnings") or [])
        return out["summary"]

    def _usage():
        out["usage"] = R.load_usage(manifest, manifest_path,
                                  project_dir=project_dir)
        return out["usage"]

    def _html():
        return R.render_html(manifest, out["summary"], "bench", out["usage"])

    def _markdown():
        return R.render_md(manifest, out["summary"], out["usage"])

    return (("validate", _validate), ("rollup", _rollup), ("usage load", _usage),
            ("html", _html), ("markdown", _markdown))


def _bench(scales=None, repeats=None):
    """Time a full render at each scale. 0 when every scale ran, 1 if one failed.

    The fixture is built in a temp directory and DELETED before this returns, at
    every scale, including the failing ones — a bench that leaves a fixture behind
    is a bench whose next run measures something else.
    """
    import shutil
    import tempfile
    # ONE definition of best-of-N, in `_usage_bench`, beside the note that
    # argues for the minimum over the mean. A second copy here is how two benches
    # start disagreeing about what "the time" means.
    analytics = _usage_bench
    scales = scales if scales is not None else _BENCH_SCALES
    repeats = repeats if repeats is not None else _BENCH_REPEATS
    print("bench-report  (python %s on %s)"
          % (sys.version.split()[0], sys.platform))
    print("fixture:  gen-demo-manifest.py + gen-demo-usage.py, run as commands "
          "into a temp dir that is deleted before this exits")
    print("timing:   best of %d runs per phase - the MINIMUM, not the mean, "
          "because other load can only make a call slower" % repeats)
    rc = 0
    for phases, tasks in scales:
        tmp = tempfile.mkdtemp(prefix="report-bench-")
        try:
            fx = _bench_fixture(tmp, phases, tasks)
            manifest = _manifest_io.load_manifest(fx["manifestPath"])
            print("")
            print("%d phases x %d tasks (%s tasks, %s ledger rows)"
                  % (phases, tasks, "{:,}".format(fx["tasks"]),
                     "{:,}".format(fx["rows"])))
            seen = {}
            for label, thunk in _bench_phases(manifest, fx["manifestPath"], tmp):
                seconds, _ = analytics._time_best(thunk, repeats)
                seen[label] = seconds
                per = fx["rows"] if _BENCH_PER[label] == "row" else fx["tasks"]
                print("  %-11s %8.2f ms  (%7.2f us/%s)"
                      % (label, seconds * 1e3, seconds * 1e6 / max(1, per),
                         _BENCH_PER[label]))
            total = sum(seen.values())
            # A SUM of minima, not a measured whole-render time - said so rather
            # than printed as if one run had been observed taking it.
            print("  %-11s %8.2f ms  (%7.2f us/task)"
                  % ("sum of min", total * 1e3,
                     total * 1e6 / max(1, fx["tasks"])))
            if seen.get("html"):
                print("  the ledger pass is %.1fx the HTML build"
                      % (seen["usage load"] / seen["html"]))
        except Exception as exc:             # a failed scale must not read as fast
            sys.stderr.write("ERROR: bench failed at %d x %d: %s\n"
                             % (phases, tasks, exc))
            rc = 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return rc


if __name__ == "__main__":
    _output.safe_stdio()
    if len(sys.argv) > 1:
        sys.stderr.write("usage: bench-report.py\n")
        raise SystemExit(2)
    raise SystemExit(_bench())
