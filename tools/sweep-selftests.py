#!/usr/bin/env python3
"""
Run every `--selftest` in the tree, in parallel, under the STRICTEST of the three
sweeps that used to exist.

    tools/sweep-selftests.py                     # the sweep, all cores but two
    tools/sweep-selftests.py --jobs 1            # serial, for a bisect
    tools/sweep-selftests.py --encoding cp1252   # the "can it print" pass
    tools/sweep-selftests.py --selftest          # this file's own cases

WHY THIS EXISTS. The sweep was written twice - once in `tools/verify.sh` and once
inlined in `.github/workflows/ci.yml` - and the two copies did not check the same
things. `verify.sh` asserted the EXIT CODE and nothing else. CI additionally
required the `N/M cases passed` contract, applied the `--covered` skip, and carried
the trap that a migrated file must NOT print the contract. So a file that exited 0
having asserted nothing at all was GREEN locally and RED in CI - the exact "passes
locally, fails in CI" class this repo keeps a whole skill about, living inside the
tool built to stop forgotten steps.

Two copies of a procedure is one copy and one lie. This is the one copy: both
callers run this file, so a rule added here is added to both at once.

AND IT IS PARALLEL, which is why replacing the loop beat tightening it. Measured
before this file existed: 181 files, 56.3s end to end, because `<python> <file>
--selftest` is a process start plus an import graph and the serial loop paid both
181 times while thirteen cores idled. The work is subprocess-bound, so THREADS are
the right pool - the GIL is released across `subprocess.run`, and a process pool
would only add a second layer of interpreter starts.

`sys.executable`, not `python3` or `python`. The two old copies disagreed about
that too: `verify.sh` said `python3` and CI said `python`, so on a machine where
those are different interpreters the local sweep and the CI sweep were not testing
the same thing. The child is whatever is running this file.

OUTPUT IS COLLECTED AND PRINTED SORTED, never interleaved. A parallel runner whose
log is in completion order is a log you cannot diff against yesterday's, and
"which file was it" is the first question a red sweep has to answer.
"""
import io
import os
import re
import subprocess
import sys
import tempfile
from concurrent import futures

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`.
# Same shape as `tools/where.py`, and for the same reason.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

_output.install_path()

# The directories a sweep covers. A tuple so nothing can append to it at runtime.
#
# `tools/` IS ONE OF THEM, and that was the fix for a class rather than a file.
# Three tools here carried no cases at all - they printed a sentence saying a tool
# under `tools/` needs none - and nothing noticed, because the sweep walked only the
# plugin. That is the same silence CI's globbed sweep was written to end for
# `scripts/`: adding a file and adding a line to a list are two acts, and only one of
# them was ever enforced. A tool without a suite now fails this sweep by name.
#
# It also means every tool suite runs HERE and nowhere else. `verify.sh` and `ci.yml`
# each carried a `--selftest` line per tool for a while; the sweep covers them on
# both sides, and one path to a check beats two.
SWEEP_DIRS = (
    os.path.join("plugins", "audit", "hooks"),
    os.path.join("plugins", "audit", "scripts"),
    os.path.join("plugins", "audit", "tests"),
    "tools",
)

# The contract every non-migrated suite must print. Kept as ONE pattern because the
# grader reads it twice with opposite expectations - present for a live suite,
# ABSENT for a migrated one - and two spellings of it would be two rules.
CONTRACT = re.compile(r"([0-9]+)/([0-9]+) cases passed")

# A file that has not finished by then is reported as a TIMEOUT rather than waited
# on forever. Neither old copy had one, so a hung selftest was indistinguishable
# from a slow machine and the sweep simply never returned.
DEFAULT_TIMEOUT = 300


# --- discovery ----------------------------------------------------------------
def sweep_files(repo=None):
    """Every `.py` under the swept directories, repo-relative, sorted.

    Delegates to `_output.py_files`, which is the same recursive walk the lints and
    `selftest_coverage()` use. A second implementation here is how CI's old flat
    glob came to disagree with the classifier about which files exist - a file in a
    subdirectory stopped being swept and nothing went red.
    """
    repo = repo or REPO
    out = []
    for rel_dir in SWEEP_DIRS:
        directory = os.path.join(repo, rel_dir)
        if not os.path.isdir(directory):
            continue
        for rel, _path in _output.py_files(directory):
            out.append("%s/%s" % (rel_dir.replace(os.sep, "/"), rel))
    return sorted(out)


def covered_paths():
    """The migrated set, from the classifier CI already asks - not a name transform.

    `covered_repo_paths()` is what `_output.py --covered` prints, so this runner and
    CI's old shell loop cannot disagree about which files are skipped. Returned as a
    set because the only question asked of it is membership.
    """
    return set(_output.covered_repo_paths())


# --- running (impure) and grading (pure) --------------------------------------
def run_one(rel_path, repo=None, encoding=None, timeout=DEFAULT_TIMEOUT):
    """Run one file's `--selftest` and report what happened. No verdict here.

    Split from `grade` on purpose: everything below this line is a decision about
    text and an exit code, and a decision that needs no subprocess is a decision a
    selftest can drive through every branch. That split is why this file can prove
    its own strictness instead of only being seen passing.

    stderr is folded into stdout (`2>&1`, as both old copies did) so a traceback
    lands in the same stream as the contract line, in order. Bytes are decoded with
    `replace`: under `--encoding cp1252` the child deliberately writes a legacy code
    page, and a runner that died decoding its output would be a runner that cannot
    run the pass it exists to run.
    """
    repo = repo or REPO
    env = dict(os.environ)
    if encoding:
        env["PYTHONIOENCODING"] = encoding
    argv = [sys.executable, rel_path, "--selftest"]
    try:
        done = subprocess.run(argv, cwd=repo, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"path": rel_path, "code": None,
                "output": "did not finish within %ds" % (timeout,)}
    except OSError as exc:
        return {"path": rel_path, "code": None,
                "output": "could not be started: %s" % (exc,)}
    return {"path": rel_path, "code": done.returncode,
            "output": done.stdout.decode("utf-8", "replace")}


def cases_in(output):
    """How many cases the contract claims, or None if it makes no claim.

    The LAST match, not the first: CI read `tail -1` and then grepped it, so a file
    printing a per-section line before its total would have had the total counted.
    Reading the last match keeps that answer and stops depending on the total being
    physically last.
    """
    found = CONTRACT.findall(output or "")
    if not found:
        return None
    return int(found[-1][0])


def grade(rel_path, code, output, covered, encoding_pass=False):
    """The verdict for one run, as a pure function of what the run produced.

    Three rules, and the strictest reading of each of the two old copies:

      * `encoding_pass` - a codec was forced, and the only claim is that the file
        can PRINT what it prints on a stream that cannot spell every character.
        Nothing is skipped and no contract is required, exactly as CI's second step
        had it: a migrated file's one-line pointer has to survive a legacy code page
        as much as a suite does.
      * a MIGRATED file (in `covered`) must exit 0 and must NOT print the contract.
        `selftest_coverage()` classifies by STRING LITERAL, so a file that assembles
        the line (`"0/0 cases " + "passed"`) reads as migrated while still printing
        it; this is the net under that blind spot.
      * every other file must exit 0 AND print the contract. This is the rule
        `verify.sh` did not have, and the reason a suite could be deleted from a
        file without anything going red locally.
    """
    def row(ok, why, cases=0, skipped=False):
        """One shape, built in one place, and it CARRIES the output it graded.

        Written as six dict literals first, and `render` then read an `output` key
        that only `sweep` bolted on afterwards - so a red row rendered through any
        other caller printed "(no output)" and hid the traceback. A row that leaves
        its evidence behind cannot develop that gap.
        """
        return {"path": rel_path, "ok": ok, "why": why, "cases": cases,
                "skipped": skipped, "output": output}

    if code is None:
        return row(False, output)
    if code != 0:
        return row(False, "exited %d" % (code,))
    if encoding_pass:
        return row(True, None)
    claimed = cases_in(output)
    if rel_path in covered:
        if claimed is not None:
            return row(False, "listed as migrated but still prints the suite "
                              "contract")
        return row(True, None, skipped=True)
    if claimed is None:
        return row(False, "no --selftest (every hook, script, test and tool must carry one)")
    return row(True, None, cases=claimed)


# --- the sweep ----------------------------------------------------------------
def default_jobs(cpus=None):
    """All cores but two, and never below one.

    Two are left for the machine that is also running an editor and a browser gate;
    below one is not a number of workers.
    """
    cpus = cpus if cpus is not None else (os.cpu_count() or 1)
    return max(1, cpus - 2)


def sweep(paths, covered, jobs=None, repo=None, encoding=None,
          timeout=DEFAULT_TIMEOUT):
    """Run every path and return one graded row per file, sorted by path.

    Sorted on the way out rather than printed on the way in: completion order is
    whatever the scheduler decided this run, and a log that reorders itself between
    two green runs cannot be diffed.
    """
    jobs = jobs or default_jobs()
    rows = []
    with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = [pool.submit(run_one, p, repo, encoding, timeout) for p in paths]
        for fut in futures.as_completed(pending):
            ran = fut.result()
            rows.append(grade(ran["path"], ran["code"], ran["output"], covered,
                              encoding_pass=bool(encoding)))
    return sorted(rows, key=lambda r: r["path"])


def render(rows, jobs, encoding=None, stream=None):
    """Print the table, then every failure IN FULL, then the summary. Returns exit.

    That order is not cosmetic: `verify.sh` shows `tail -12` of a failed step, so
    the last lines have to be the ones that say what broke. Full output goes above
    the summary because a step that hides its output in exactly the case you need it
    is worse than one that prints everything - CI's old comment says so, and this
    keeps that promise.
    """
    out = stream if stream is not None else sys.stdout
    bad = [r for r in rows if not r["ok"]]
    total_cases = sum(r["cases"] for r in rows)
    skipped = [r for r in rows if r["skipped"]]

    label = "encoding pass (%s)" % (encoding,) if encoding else "sweep"
    out.write("%s: %d files, %d workers\n" % (label, len(rows), jobs))
    for row in rows:
        if row["skipped"]:
            out.write("  ok      %-58s cases live in tests/\n" % (row["path"],))
        elif row["ok"]:
            out.write("  ok      %-58s %d cases\n" % (row["path"], row["cases"]))
        else:
            out.write("  FAILED  %-58s %s\n" % (row["path"], row["why"]))
    for row in bad:
        out.write("\n--- %s: %s ---\n" % (row["path"], row["why"]))
        out.write(row.get("output") or "(no output)")
        if not (row.get("output") or "").endswith("\n"):
            out.write("\n")
    out.write("\n")
    if bad:
        for row in bad:
            out.write("FAIL  %s: %s\n" % (row["path"], row["why"]))
    out.write("%d/%d files ok, %d migrated to tests/, %d cases\n"
              % (len(rows) - len(bad), len(rows), len(skipped), total_cases))
    return 1 if bad else 0


# --- entry point --------------------------------------------------------------
def _flag_value(argv, name, fallback):
    """`--name X` or `--name=X`, or the fallback. Two spellings, one reader."""
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return fallback


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    encoding = _flag_value(argv, "--encoding", None)
    timeout = int(_flag_value(argv, "--timeout", DEFAULT_TIMEOUT))
    jobs = int(_flag_value(argv, "--jobs", default_jobs()))

    paths = sweep_files()
    covered = covered_paths()
    if not paths:
        sys.stderr.write("sweep-selftests: found no .py under %s - refusing to "
                         "report a green sweep over nothing\n"
                         % (", ".join(SWEEP_DIRS),))
        return 2
    if not covered:
        sys.stderr.write("sweep-selftests: the migrated set is EMPTY, so the "
                         "migrated-file rules below would assert nothing. Run "
                         "`_output.py --covered` and find out why.\n")
        return 2
    rows = sweep(paths, covered, jobs=jobs, encoding=encoding, timeout=timeout)
    return render(rows, jobs, encoding=encoding)


# --- selftest -----------------------------------------------------------------
def _cases():
    """Every branch of `grade` plus the two refusals, driven without a subprocess."""
    out = []
    covered = set(["plugins/audit/scripts/_output.py"])
    live = "plugins/audit/tests/test__output.py"
    migrated = "plugins/audit/scripts/_output.py"

    g = grade(live, 0, "ALL PASS: 7/7 cases passed\n", covered)
    out.append(("g0", g["ok"] and g["cases"] == 7 and not g["skipped"],
                "a live suite that exits 0 and prints the contract is ok, and its "
                "case count is READ rather than assumed: %r" % (g,)))

    g = grade(live, 0, "ran some things\n", covered)
    out.append(("g1", (not g["ok"]) and "no --selftest" in g["why"],
                "THE RULE verify.sh DID NOT HAVE: exit 0 with no contract is a "
                "FAILURE, not a pass - this is the case that let a suite be "
                "deleted with nothing going red locally: %r" % (g,)))

    g = grade(migrated, 0, "cases moved to plugins/audit/tests/\n", covered)
    out.append(("g2", g["ok"] and g["skipped"] and g["cases"] == 0,
                "a migrated file exits 0, prints a pointer, contributes 0 cases "
                "and is NOT required to print the contract: %r" % (g,)))

    g = grade(migrated, 0, "ALL PASS: 0/0 cases passed\n", covered)
    out.append(("g3", (not g["ok"]) and "still prints" in g["why"],
                "the trap under selftest_coverage()'s string-literal blind spot: a "
                "file listed as migrated that STILL prints the contract is red: "
                "%r" % (g,)))

    g = grade(live, 1, "Traceback\n", covered)
    out.append(("g4", (not g["ok"]) and g["why"] == "exited 1",
                "a non-zero exit is red and the code is NAMED, so the summary line "
                "says what happened: %r" % (g,)))

    g = grade(migrated, 0, "ALL PASS: 3/3 cases passed\n", covered,
              encoding_pass=True)
    out.append(("g5", g["ok"] and g["cases"] == 0,
                "the encoding pass asserts ONLY that the file could print - the "
                "same file that is red at g3 is green here, which is what makes "
                "the two passes two different questions: %r" % (g,)))

    g = grade(live, None, "did not finish within 300s", covered)
    out.append(("g6", (not g["ok"]) and "did not finish" in g["why"],
                "a timeout is a NAMED failure, not a wait - neither old copy had "
                "one, so a hung suite and a slow machine printed the same nothing: "
                "%r" % (g,)))

    n = cases_in("part one: 2/2 cases passed\nALL PASS: 41/41 cases passed\n")
    out.append(("c0", n == 41,
                "the count comes from the LAST contract line, matching CI's "
                "`tail -1 | grep`: a per-section line before the total must not be "
                "what gets counted (got %r, and 2 would mean the first)" % (n,)))

    out.append(("c1", cases_in("nothing here") is None,
                "no contract reads as NO CLAIM (None), which is what g1 turns into "
                "a failure - if this returned 0 the two would be the same answer"))

    found = sweep_files()
    subdir = [p for p in found if p.count("/") > 3]
    out.append(("d0", len(found) > 100 and len(subdir) > 20,
                "discovery is RECURSIVE and reaches files in subdirectories - a "
                "flat glob is how CI's old loop silently stopped running a whole "
                "directory (%d files, %d of them nested)"
                % (len(found), len(subdir))))

    out.append(("d1", found == sorted(found) and len(found) == len(set(found)),
                "the list is sorted and carries no duplicate, so two green runs "
                "produce byte-identical logs and a path is swept once"))

    cov = covered_paths()
    out.append(("d2", len(cov) > 50 and all(p.startswith("plugins/audit/")
                                            for p in cov),
                "the migrated set is non-empty and repo-relative, in the SAME "
                "spelling discovery produces - a set that never matches would make "
                "g2 and g3 vacuous and the sweep would silently weaken to the old "
                "exit-code-only rule (%d paths)" % (len(cov),)))

    overlap = cov & set(found)
    out.append(("d3", len(overlap) == len(cov),
                "...and every migrated path IS one of the swept paths, which is "
                "the assertion that the two spellings agree rather than merely "
                "look alike (%d of %d matched)" % (len(overlap), len(cov))))

    out.append(("j0", default_jobs(14) == 12 and default_jobs(1) == 1
                and default_jobs(2) == 1,
                "worker count leaves two cores and never drops below one, so a "
                "single-core runner still runs"))

    v = _flag_value(["--jobs", "4"], "--jobs", 99)
    w = _flag_value(["--jobs=4"], "--jobs", 99)
    out.append(("f0", v == "4" and w == "4" and
                _flag_value([], "--jobs", 99) == 99,
                "both flag spellings read the same value and the fallback survives "
                "an empty argv"))

    buf = io.StringIO()
    code = render([grade(live, 0, "1/1 cases passed\n", covered),
                   grade("plugins/audit/scripts/_deps.py", 1, "boom\n", covered)], 4,
                  stream=buf)
    text = buf.getvalue()
    out.append(("r0", code == 1 and text.count("FAIL") == 2
                and "boom" in text and text.rstrip().endswith("1 cases"),
                "a red render exits 1, names the file twice (table and summary), "
                "reproduces the child's output IN FULL, and ends with the counts "
                "so `tail -12` of a failed step is the useful part"))

    buf = io.StringIO()
    code = render([grade(live, 0, "5/5 cases passed\n", covered)], 4, stream=buf)
    out.append(("r1", code == 0 and "FAIL" not in buf.getvalue()
                and "5 cases" in buf.getvalue(),
                "a green render exits 0, says FAIL nowhere, and still prints the "
                "count - so 'all ok' and 'nothing ran' cannot read the same"))

    buf = io.StringIO()
    render([grade(migrated, 0, "moved\n", covered)], 4, stream=buf)
    out.append(("r2", "cases live in tests/" in buf.getvalue(),
                "a migrated file is reported as SKIPPED with its reason rather "
                "than as a silent zero, which is the row CI printed by hand"))

    # A fixture, NOT this file: `run_one` appends `--selftest`, so pointing it at
    # this module would have it run its own suite, which runs this case, which
    # spawns it again. Written that way first; a hermetic child is both safe and a
    # sharper test, because the expected output is chosen rather than incidental.
    # NO `.py` SUFFIX on the fixture, deliberately. `_refs.tool_basename_drift()`
    # holds that every `.py` basename literal under `tools/` must name a file that
    # exists, and it scans prose and code alike with no exception list - a rule
    # worth keeping, because stale prose misleads a reader as far as a stale argv
    # misleads a process. A fixture this file CREATES is not a reference to a repo
    # script, and `sys.executable <path>` does not care about the extension, so the
    # honest fix is a name that makes no claim rather than an exemption.
    work = tempfile.mkdtemp()
    child = os.path.join(work, "fixture_child")
    io.open(child, "w", encoding="utf-8").write(
        "import sys\n"
        "sys.stdout.write('fixture: 4/4 cases passed\\n')\n")
    ran = run_one(child, timeout=30)
    out.append(("x0", ran["code"] == 0 and cases_in(ran["output"]) == 4,
                "run_one really starts a child and captures its stream, and the "
                "grader reads the child's OWN number back out - so the impure half "
                "is exercised and 4 could not have come from anywhere else "
                "(exit %r, read %r)" % (ran["code"], cases_in(ran["output"]))))

    io.open(child, "w", encoding="utf-8").write("import sys; sys.exit(3)\n")
    ran = run_one(child, timeout=30)
    out.append(("x0b", ran["code"] == 3,
                "...and the child's exit code is carried through unchanged rather "
                "than collapsed to 0/1, which is what makes g4's message name a "
                "real number (got %r)" % (ran["code"],)))

    missing = os.path.join(tempfile.gettempdir(), "sweep-no-such-file-xyz")
    ran = run_one(missing, timeout=5)
    out.append(("x1", ran["code"] != 0,
                "a file that cannot run reports a failure rather than an empty "
                "green row (code %r)" % (ran["code"],)))

    return out


def _selftest():
    rows = _cases()
    bad = [r for r in rows if not r[1]]
    for name, ok, why in rows:
        print("%s %s %s" % ("PASS" if ok else "FAIL", name, why))
    print("%s: %d/%d cases passed" % ("ALL PASS" if not bad else "FAILURES",
                                      len(rows) - len(bad), len(rows)))
    return 1 if bad else 0


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
