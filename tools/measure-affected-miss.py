#!/usr/bin/env python3
"""
How often the affected-test selection leaves out a suite that was going to go red.

    tools/measure-affected-miss.py                      # the last task commits, then CI
    tools/measure-affected-miss.py --commits 8          # fewer, when the clock matters
    tools/measure-affected-miss.py --budget-minutes 90  # stop starting commits past this
    tools/measure-affected-miss.py --no-ci              # the mutation half alone
    tools/measure-affected-miss.py --ci-only --ci-since 2026-10-01   # the CI half alone
    tools/measure-affected-miss.py --json               # machine-readable
    tools/measure-affected-miss.py --selftest           # this file's own cases

WHY IT EXISTS. `tools/affected.py` decides which suites a change owes, and a narrowed
run is trusted exactly as far as that decision is. Nothing had ever asked it how
often it is wrong - its own cases check the rules it has, which cannot show a rule it
lacks. So this asks the history: for a commit, which suites WOULD have gone red under
a plausible fault in the files it changed, and did the selection name them?

THE MUTATION HALF. For each of the last task commits, in a scratch worktree at that
commit, every `.py` the commit changed is mutated in two ways - an import-time
`raise`, and a house-style violation (an annotation) that the tree lints read - one
mutation at a time, and the sweep is run over the whole tree. A suite that went red
and that `tools/affected.py --base <parent>` did not select is a MISS; every miss is
named with the commit, the mutation and the suite.

A RED THE SELECTION DID NOT NAME IS CHECKED TWICE BEFORE IT IS COUNTED. It is run
again alone under the same mutation (a timeout under load is not a miss), and then
alone on the commit with nothing mutated (a suite already red there is not a miss
either, and is listed as such). Only a suite red under the mutation, red again, and
green without it is counted.

THE CI HALF. Each failed CI run since the oldest examined commit is read through
`gh run view --log-failed`, the suites its log names as failing are taken, and each
is checked against the selection for that run's own commit. A run whose log names no
suite (a lint job, a browser gate) is counted apart: the selection does not pick
those. When `gh` cannot be asked - missing, not signed in, no network - the half
prints `could-not-ask` with the reason, which is a different statement from "no
failing run was missed" and is never rendered as a zero. A run whose commit this
clone does not hold, or whose log could not be fetched, is named as unread rather than
dropped.

WHAT IT DOES NOT SAY.
  - The selection measured is the one each commit CARRIED (that commit's own
    `tools/affected.py`), run from inside the scratch worktree, because the selector
    reads its repository from where it lives. `--affected-cmd` replaces it.
  - A mutation that turns nothing red is reported as `inert`. Zero misses over an
    inert mutation is zero evidence, and the output says so instead of counting it.
  - A commit that changed no Python has nothing to mutate; it is named and left out
    of the commits count. A commit whose selection was the full set cannot have a
    miss by construction; it is counted, and named as full.
  - A commit that could not be measured (the worktree, the selector or the sweep
    failed) is named with the reason and is not counted as a zero.
  - A CI miss is a failing suite its commit's selection did not name, whatever made it
    fail. A suite already red before the commit, a platform-only red and a flaky one
    are all counted, so the CI figure is an UPPER bound on the misses the diff itself
    caused; the mutation half is the one that attributes a red to a change.
  - The two mutations are two plausible faults, not the set of all faults. A miss rate
    from them is a floor on the true rate for the faults they model and says nothing
    about the rest.

IT NEVER EDITS THE CHECKOUT. Every mutation happens in a scratch worktree made under
the temp directory and removed in `finally`; the checkout is only asked questions
(`git log`, `git diff`, `git rev-parse`) and told to add and drop that worktree. A
scratch directory that would sit inside the checkout is refused before it is made.

Exit codes: 0 a measurement was taken - 1 no commit could be measured (with
--ci-only: gh could not be asked) - 2 usage.
"""
import argparse
import calendar
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

# A task commit names a phase task in its subject; the plan-state and merge commits
# between them change no code a task owns.
TASK_SUBJECT = re.compile(r"^[a-z]+\(P\d+\.\d+[^)]*\):")

# Both a sweep's output and a CI log carry the verdict as `FAIL  <what>: <why>` lines
# directly above the `N/M files ok` summary - and ALSO carry, higher up, the full
# output of every failing suite, which can contain FAIL lines and summaries of its
# own (the sweep's suite drives a sweep of fixtures). Only the block above the final
# summary is the verdict; a line is searched for, not anchored, because CI puts a job
# and step prefix in front of it.
FAIL_LINE = re.compile(r"(?:^|\s)FAIL  (\S+): ")
EXEMPT_LINE = re.compile(r"(?:^|\s)EXEMPT ")
SUMMARY_LINE = re.compile(r"\b\d+/\d+ files ok\b")
CI_PREFIX = re.compile(r"^(.*?)\d{4}-\d\d-\d\dT[\d:.]+Z ?")
SELFTEST_GATE = re.compile(r"\bpython3? (\S+) --selftest\b")
PY_SUFFIX = "." + "py"
CODING_COMMENT = re.compile(rb"^#.*coding[:=]")

MUTATIONS = ("raise", "style")
RAISE_LINE = b'raise RuntimeError("measure-affected-miss: import-time probe")\n'
STYLE_TAIL = b"\n\ndef _measure_probe(value: int) -> int:\n    return value\n"

SCRATCH_PREFIX = "measure-affected-miss-"
# What an option set holds; a key outside it is a typo, refused by name.
DEFAULTS = {
    "rev": "HEAD", "commits": 20, "scan": 400, "pattern": TASK_SUBJECT,
    "sweep_cmd": None, "affected_cmd": None, "timeout": 3600, "env": None,
    "mutation": True, "ci": True, "ci_since": None, "ci_limit": 200, "gh_cmd": ["gh"],
    "budget_minutes": None, "scratch_dir": None,
}


# --- running things -------------------------------------------------------------
def run_cmd(argv, cwd, env=None, timeout=300):
    """`(returncode, text)` - stdout and stderr in order, kept on a non-zero exit.

    `(None, reason)` when the command could not be run at all, so a missing binary
    and a command that ran and failed are different answers to the caller."""
    try:
        out = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timed out after %ss: %s" % (timeout, " ".join(argv[:3]))
    except OSError as exc:
        return None, "could not run %s: %s" % (argv[0] if argv else "?", exc)
    return out.returncode, out.stdout.decode("utf-8", "replace")


def git(args, cwd, env=None, timeout=300):
    """`run_cmd` for git, with the path quoting pinned so names arrive raw."""
    return run_cmd(["git", "-c", "core.quotePath=false"] + list(args), cwd, env,
                   timeout)


def tail(text, limit=240):
    """The last of `text`, one line, for a reason that must fit in a report line."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else "..." + flat[-limit:]


# --- reading what the tools print -------------------------------------------------
def _block_above(lines, at):
    """The `FAIL  <what>: ` lines directly above `lines[at]`, `EXEMPT` lines between
    them and the summary stepped over."""
    found = []
    for line in reversed(lines[:at]):
        got = FAIL_LINE.search(line)
        if got:
            found.append(got.group(1).replace("\\", "/"))
        elif not EXEMPT_LINE.search(line):
            break
    return found


def _failures(text, summaries):
    """`(suites, others)` from the verdict blocks above the summaries at `summaries`:
    a path ending in the Python suffix is a suite, anything else (`coverage`) is a red
    that names no file."""
    lines = (text or "").splitlines()
    suites, others = set(), set()
    for at in summaries:
        for what in _block_above(lines, at):
            (suites if what.endswith(PY_SUFFIX) else others).add(what)
    return sorted(suites), sorted(others)


def _summary_lines(text):
    return [i for i, line in enumerate((text or "").splitlines())
            if SUMMARY_LINE.search(line)]


def parse_sweep(text):
    """What a sweep printed: the suites that went red, the reds that name no file,
    and whether the run reached its summary line.

    Only the FINAL summary's block is read. A failing suite's own output sits above
    it in full, and a suite that itself runs a sweep over fixtures puts FAIL lines and
    a summary of its own there - reading those named suites that were never part of
    this run, and a path the sweep then refuses by name.

    `complete` is the sentinel. A sweep that crashed, timed out or printed nothing
    has no summary line and an empty red list, and an empty red list read alone would
    be a clean sweep."""
    summaries = _summary_lines(text)
    red, other = _failures(text, summaries[-1:])
    if summaries:
        # The coverage verdict is printed AFTER the summary, as a FAIL line too.
        late = set(other)
        for line in (text or "").splitlines()[summaries[-1] + 1:]:
            got = FAIL_LINE.search(line)
            if got and not got.group(1).endswith(PY_SUFFIX):
                late.add(got.group(1))
        other = sorted(late)
    return {"complete": bool(summaries), "red": red, "other": other}


def parse_ci_log(text):
    """The failing suites a `gh run view --log-failed` log names, once each.

    A CI log interleaves several jobs and holds, per job, the nested verdicts of any
    failing suite that runs a sweep of its own. The verdict is the LAST summary a
    job's lines print, so lines are grouped by the `job<TAB>step<TAB>` prefix CI puts
    in front of them and each group's final summary is the one whose block is read.
    A log with no summary line names no suite - and the caller sets such a run
    apart as naming no suite, rather than reading anything else as a verdict."""
    lines = (text or "").splitlines()
    last = {}
    for at, line in enumerate(lines):
        if SUMMARY_LINE.search(line):
            got = CI_PREFIX.match(line)
            last[got.group(1) if got else ""] = at
    return _failures(text, sorted(last.values()))[0]


def read_selection(rc, text):
    """The selection `tools/affected.py --json` printed, or why it is unreadable.

    The exit code is not consulted: the selector exits non-zero for the full set
    ON PURPOSE and prints the JSON all the same. An answer that is not that JSON is
    `readable` False with the head of what it said - never an empty selection,
    which would make every red a miss."""
    try:
        body = json.loads(text)
    except ValueError:
        body = None
    if not isinstance(body, dict) or "full" not in body:
        return {"readable": False, "full": False, "suites": [], "paths": [],
                "why": "selector exit %s said: %s" % (rc, tail(text))}
    if body["full"]:
        return {"readable": True, "full": True, "suites": [], "paths": [], "why": ""}
    suites = sorted(set(body.get("suites") or []))
    paths = set()
    for gate in body.get("gates") or []:
        found = SELFTEST_GATE.search(gate)
        if found:
            paths.add(found.group(1).replace("\\", "/"))
    return {"readable": True, "full": False, "suites": suites,
            "paths": sorted(paths), "why": ""}


def is_selected(sel, path):
    """Whether the selection covers this red suite: every suite in a `tests`
    directory is named by basename, every other one only by a gate that asks for its
    selftest.

    A `tests` directory at ANY depth, because the suites lived under the plugin
    before they moved to the repository root, and a CI run on a commit from before the
    move names them by the old path; matching only the root one read every such suite
    as unselected."""
    if sel["full"]:
        return True
    path = path.replace("\\", "/")
    if path.startswith("tests/") or "/tests/" in path:
        return path.rsplit("/", 1)[-1] in sel["suites"]
    return path in sel["paths"]


def parse_task_log(text, pattern=None):
    """The `sha<TAB>subject` lines whose subject names a phase task, in order."""
    pattern = pattern or TASK_SUBJECT
    found = []
    for line in (text or "").splitlines():
        sha, _tab, subject = line.partition("\t")
        if sha and subject and pattern.match(subject):
            found.append({"sha": sha, "subject": subject})
    return found


# --- the mutations ----------------------------------------------------------------
def _is_preamble(line, index):
    return (index == 0 and line.startswith(b"#!")) or (
        index < 2 and bool(CODING_COMMENT.match(line)))


def mutate(kind, data):
    """`data` (bytes) with one fault planted.

    `raise` goes after the shebang and coding lines and BEFORE the module's own
    statements, so importing the file fails however the rest of it is written.
    `style` is appended - an annotated function, which the AST lint reads and no
    interpreter minds."""
    if kind == "raise":
        lines = data.splitlines(True)
        at = 0
        while at < len(lines) and _is_preamble(lines[at], at):
            at += 1
        return b"".join(lines[:at]) + RAISE_LINE + b"".join(lines[at:])
    if kind == "style":
        body = data if (not data or data.endswith(b"\n")) else data + b"\n"
        return body + STYLE_TAIL
    raise ValueError("unknown mutation %r" % (kind,))


# --- the options ------------------------------------------------------------------
def make_options(repo, **overrides):
    """One option set, defaults filled in; an unknown key is an error."""
    unknown = sorted(set(overrides) - set(DEFAULTS))
    if unknown:
        raise ValueError("unknown option(s): %s" % ", ".join(unknown))
    opts = dict(DEFAULTS)
    opts["gh_cmd"] = list(DEFAULTS["gh_cmd"])
    opts.update(overrides)
    opts["repo"] = os.path.abspath(repo)
    if opts["sweep_cmd"] is None:
        opts["sweep_cmd"] = [sys.executable, os.path.join("tools", "sweep-selftests.py"),
                             "--quiet"]
    if opts["affected_cmd"] is None:
        opts["affected_cmd"] = [sys.executable, os.path.join("tools", "affected.py"),
                                "--json", "--base", "{base}"]
    return opts


def affected_argv(opts, base):
    return [part.replace("{base}", base) for part in opts["affected_cmd"]]


# --- the scratch worktree ----------------------------------------------------------
def inside(path, parent):
    """True when `path` is `parent` or below it, after resolving links."""
    path, parent = os.path.realpath(path), os.path.realpath(parent)
    return path == parent or path.startswith(parent + os.sep)


def add_worktree(repo, sha, tree, env):
    """A detached worktree of `sha` at `tree`. Hooks are pointed at nothing, so a
    post-checkout hook of the checkout cannot run against the scratch tree."""
    return git(["-c", "core.hooksPath=" + os.devnull, "worktree", "add", "--detach",
                "-q", tree, sha], repo, env)


def drop_worktree(repo, tree, root, env):
    """Remove the worktree, then its directory. A failed `worktree remove` leaves a
    registration behind in the checkout's git dir, so only then is `prune` asked."""
    rc, _text = git(["worktree", "remove", "--force", tree], repo, env)
    _output.remove_tree(root)
    if rc != 0:
        git(["worktree", "prune"], repo, env)


def changed_python(repo, parent, sha, env):
    """The `.py` files `sha` added or modified against `parent`, or None."""
    rc, text = git(["diff", "--name-only", "--diff-filter=AM", parent, sha], repo, env)
    if rc != 0:
        return None
    return sorted(line.strip() for line in text.splitlines()
                  if line.strip().endswith(PY_SUFFIX))


# --- measuring one commit ----------------------------------------------------------
def _sweep(opts, tree, paths):
    rc, text = run_cmd(opts["sweep_cmd"] + list(paths), tree, opts["env"],
                       opts["timeout"])
    got = parse_sweep(text)
    got["why"] = "" if got["complete"] else "sweep exit %s said: %s" % (rc, tail(text))
    return got


def _restore(tree, originals):
    for rel, data in originals.items():
        with open(os.path.join(tree, rel), "wb") as fh:
            fh.write(data)


def run_mutation(opts, tree, kind, originals, sel):
    """One mutation, one full sweep, and the reds the selection did not name.

    The tree is restored from the bytes read before any mutation - in `finally`,
    and before the baseline check, which must see the commit as it was."""
    rec = {"kind": kind, "status": "ran", "why": "", "red": 0, "unselected": 0,
           "inert": False, "missed": [], "baseline_red": [], "flaky": [],
           "other": []}
    try:
        for rel, data in sorted(originals.items()):
            with open(os.path.join(tree, rel), "wb") as fh:
                fh.write(mutate(kind, data))
        first = _sweep(opts, tree, [])
        if not first["complete"]:
            rec.update(status="sweep-unreadable", why=first["why"])
            return rec
        rec["red"], rec["other"] = len(first["red"]), first["other"]
        rec["inert"] = not first["red"] and not first["other"]
        unselected = [p for p in first["red"] if not is_selected(sel, p)]
        rec["unselected"] = len(unselected)
        if not unselected:
            return rec
        again = _sweep(opts, tree, unselected)
        if not again["complete"]:
            rec.update(status="sweep-unreadable", why=again["why"])
            return rec
        still = [p for p in unselected if p in again["red"]]
        rec["flaky"] = [p for p in unselected if p not in still]
        _restore(tree, originals)
        if still:
            base = _sweep(opts, tree, still)
            if not base["complete"]:
                rec.update(status="sweep-unreadable", why=base["why"])
                return rec
            rec["baseline_red"] = [p for p in still if p in base["red"]]
            rec["missed"] = [p for p in still if p not in base["red"]]
        return rec
    finally:
        _restore(tree, originals)


def select_in_tree(opts, tree, parent):
    rc, text = run_cmd(affected_argv(opts, parent), tree, opts["env"], opts["timeout"])
    return read_selection(rc, text)


def measure_in_tree(opts, tree, parent, changed):
    """The mutation records for one commit's tree, or why it could not be measured."""
    sel = select_in_tree(opts, tree, parent)
    if not sel["readable"]:
        return {"status": "could-not-measure", "why": sel["why"], "full": False,
                "mutations": []}
    if sel["full"]:
        return {"status": "measured", "why": "", "full": True, "mutations": []}
    originals = {}
    for rel in changed:
        with open(os.path.join(tree, rel), "rb") as fh:
            originals[rel] = fh.read()
    mutations = [run_mutation(opts, tree, kind, originals, sel) for kind in MUTATIONS]
    bad = [m for m in mutations if m["status"] != "ran"]
    if bad:
        return {"status": "could-not-measure", "full": False, "mutations": mutations,
                "why": "%s: %s" % (bad[0]["kind"], bad[0]["why"])}
    return {"status": "measured", "why": "", "full": False, "mutations": mutations}


def measure_commit(opts, commit):
    """One commit's record. Whatever goes wrong is a stated status, not a raise: a
    run that takes hours must not lose its other commits to one bad worktree."""
    rec = {"sha": commit["sha"], "subject": commit["subject"], "status": "",
           "why": "", "full": False, "changed": [], "mutations": []}
    repo, env = opts["repo"], opts["env"]
    scratch = opts["scratch_dir"] or tempfile.gettempdir()
    if inside(scratch, repo):
        rec.update(status="could-not-measure",
                   why="the scratch directory %s is inside the checkout" % (scratch,))
        return rec
    rc, parent = git(["rev-parse", commit["sha"] + "^"], repo, env)
    parent = parent.strip()
    if rc != 0:
        rec.update(status="could-not-measure", why="no parent: " + tail(parent))
        return rec
    changed = changed_python(repo, parent, commit["sha"], env)
    if changed is None:
        rec.update(status="could-not-measure", why="git diff could not read the commit")
        return rec
    rec["changed"] = changed
    if not changed:
        rec["status"] = "no-python"
        return rec
    root = tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=scratch)
    tree = os.path.join(root, "tree")
    try:
        added, text = add_worktree(repo, commit["sha"], tree, env)
        if added != 0:
            rec.update(status="could-not-measure", why="worktree: " + tail(text))
        else:
            rec.update(measure_in_tree(opts, tree, parent, changed))
    except Exception as exc:                                   # noqa: BLE001
        rec.update(status="could-not-measure",
                   why="%s: %s" % (type(exc).__name__, exc))
    finally:
        drop_worktree(repo, tree, root, env)
    return rec


def recent_task_commits(opts):
    """`(commits, problem)` - the newest task commits first, up to the count."""
    rc, text = git(["log", "--format=%H%x09%s", "-n", str(opts["scan"]), opts["rev"]],
                   opts["repo"], opts["env"])
    if rc != 0:
        return [], "git log could not read %s: %s" % (opts["rev"], tail(text))
    return parse_task_log(text, opts["pattern"])[:opts["commits"]], ""


# --- the CI half --------------------------------------------------------------------
def _epoch(text):
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return calendar.timegm(time.strptime(text, fmt))
        except (ValueError, TypeError):
            continue
    return None


def selection_for_sha(opts, sha, cache):
    """The selection for `sha`'s own diff, from a scratch worktree at it; a dict
    like `read_selection`'s, `readable` False when it could not be produced."""
    if sha in cache:
        return cache[sha]
    repo, env = opts["repo"], opts["env"]
    got = {"readable": False, "why": "commit %s is not in this clone" % sha[:9]}
    rc, _text = git(["rev-parse", "--verify", "--quiet", sha + "^{commit}"], repo, env)
    if rc == 0:
        rc, parent = git(["rev-parse", sha + "^"], repo, env)
        got = {"readable": False, "why": "no parent for %s" % sha[:9]}
        scratch = opts["scratch_dir"] or tempfile.gettempdir()
        if rc == 0 and not inside(scratch, repo):
            root = tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=scratch)
            tree = os.path.join(root, "tree")
            try:
                added, text = add_worktree(repo, sha, tree, env)
                got = (select_in_tree(opts, tree, parent.strip()) if added == 0 else
                       {"readable": False, "why": "worktree: " + tail(text)})
            finally:
                drop_worktree(repo, tree, root, env)
    cache[sha] = got
    return got


def window_start(opts, shas):
    """The oldest commit time among `shas` as epoch seconds, or None."""
    times = []
    for sha in shas:
        rc, text = git(["log", "-1", "--format=%ct", sha], opts["repo"], opts["env"])
        if rc == 0 and text.strip().isdigit():
            times.append(int(text.strip()))
    return min(times) if times else None


def ci_half(opts, shas):
    """`{"asked": False, "why"}` when gh could not be asked, else the runs read.

    The window opens at the oldest of `shas` (or at `--ci-since`) and runs to now;
    gh is looked up FIRST, so a machine without it answers before any git is run."""
    gh = opts["gh_cmd"]
    if shutil.which(gh[0]) is None:
        return {"asked": False, "why": "%s is not on PATH" % (gh[0],)}
    repo, env = opts["repo"], opts["env"]
    since = _epoch(opts["ci_since"]) if opts["ci_since"] else window_start(opts, shas)
    if since is None:
        return {"asked": False, "why": "no window: no commit time and no --ci-since"}
    rc, text = run_cmd(gh + ["run", "list", "--status", "failure", "--limit",
                             str(opts["ci_limit"]), "--json",
                             "databaseId,headSha,createdAt,workflowName"],
                       repo, env, 120)
    try:
        listed = json.loads(text) if rc == 0 else None
    except ValueError:
        listed = None
    if not isinstance(listed, list):
        return {"asked": False, "why": "gh run list: " + tail(text)}
    runs, cache = [], {}
    for item in listed:
        made = _epoch(item.get("createdAt") or "")
        if made is not None and made < since:
            continue
        rec = {"id": item.get("databaseId"), "sha": item.get("headSha") or "",
               "workflow": item.get("workflowName") or "", "status": "", "why": "",
               "failing": [], "missed": []}
        rc, log = run_cmd(gh + ["run", "view", str(rec["id"]), "--log-failed"],
                          repo, env, 300)
        if rc != 0:
            rec.update(status="unread", why="gh run view: " + tail(log))
        else:
            rec["failing"] = parse_ci_log(log)
            if not rec["failing"]:
                rec["status"] = "no-suite"
            else:
                sel = selection_for_sha(opts, rec["sha"], cache)
                if not sel["readable"]:
                    rec.update(status="unread", why=sel["why"])
                else:
                    rec["missed"] = [p for p in rec["failing"]
                                     if not is_selected(sel, p)]
                    rec["status"] = "read"
        runs.append(rec)
    return {"asked": True, "why": "", "runs": runs}


# --- the whole measurement -----------------------------------------------------------
def describe(rec):
    """One line for a commit: what happened to it and what each mutation found."""
    head = "%s %s" % (rec["sha"][:9], rec["subject"][:60])
    if rec["status"] == "no-python":
        return "%s: no Python changed, nothing to mutate" % (head,)
    if rec["status"] == "could-not-measure":
        return "%s: NOT MEASURED - %s" % (head, rec["why"])
    if rec["full"]:
        return "%s: the selection was the full set, so no suite can be missed" % (head,)
    parts = []
    for m in rec["mutations"]:
        if m["inert"]:
            parts.append("%s: inert, nothing went red" % m["kind"])
        else:
            parts.append("%s: red %d, unselected %d, missed %d"
                         % (m["kind"], m["red"], m["unselected"], len(m["missed"])))
    return "%s: %s" % (head, "; ".join(parts))


def measure(opts, say=None):
    """The mutation half over the recent task commits, then the CI half."""
    say = say or (lambda line: None)
    started = time.time()
    commits, problem = recent_task_commits(opts) if opts["mutation"] else ([], "")
    result = {"requested": opts["commits"], "problem": problem, "commits": [],
              "measured": 0, "stopped": None, "ci": None, "range": None,
              "mutation": opts["mutation"]}
    if problem:
        return result
    for index, commit in enumerate(commits):
        spent = (time.time() - started) / 60.0
        if opts["budget_minutes"] is not None and spent >= opts["budget_minutes"]:
            result["stopped"] = {"examined": index, "of": len(commits)}
            break
        rec = measure_commit(opts, commit)
        result["commits"].append(rec)
        say("[%d/%d] %s" % (index + 1, len(commits), describe(rec)))
    result["measured"] = sum(1 for r in result["commits"] if r["status"] == "measured")
    if result["commits"]:
        result["range"] = [result["commits"][-1]["sha"], result["commits"][0]["sha"]]
    if opts["ci"]:
        result["ci"] = ci_half(opts, [r["sha"] for r in result["commits"]])
    return result


def commit_misses(rec):
    return [(m["kind"], path) for m in rec["mutations"] for path in m["missed"]]


def render(result):
    """The report as lines; the headline is the last one."""
    if result["problem"]:
        return ["measure-affected-miss: " + result["problem"]]
    lines = []
    if not result.get("mutation", True):
        pass
    elif result["range"]:
        fulls = sum(1 for r in result["commits"]
                    if r["status"] == "measured" and r["full"])
        lines.append("window: %d task commit(s), %s..%s, %d measured (%d of them the "
                     "full set, which cannot miss)"
                     % (len(result["commits"]), result["range"][0][:9],
                        result["range"][1][:9], result["measured"], fulls))
    else:
        lines.append("window: no task commit found")
    for rec in result["commits"]:
        lines.append("  " + describe(rec))
    if result["stopped"]:
        lines.append("STOPPED by the time budget after %d of %d commits; the rest "
                     "were not examined" % (result["stopped"]["examined"],
                                            result["stopped"]["of"]))
    measured = [r for r in result["commits"] if r["status"] == "measured"]
    for rec in result["commits"]:
        for kind, path in commit_misses(rec):
            lines.append("MISS  %s  %s  %s  (changed: %s)"
                         % (rec["sha"][:9], kind, path, ", ".join(rec["changed"])))
        for m in rec["mutations"]:
            for path in m["baseline_red"]:
                lines.append("not a miss  %s  %s  %s  (already red unmutated)"
                             % (rec["sha"][:9], m["kind"], path))
            for path in m["flaky"]:
                lines.append("not a miss  %s  %s  %s  (green on the second run)"
                             % (rec["sha"][:9], m["kind"], path))
            for what in m["other"]:
                lines.append("unattributed red  %s  %s  %s  (no suite file named)"
                             % (rec["sha"][:9], m["kind"], what))
    ci = result["ci"]
    if ci and ci["asked"]:
        for run in ci["runs"]:
            tag = "CI run %s (%s %s)" % (run["id"], run["workflow"], run["sha"][:9])
            for path in run["missed"]:
                lines.append("MISS  %s  %s" % (tag, path))
            if run["status"] == "unread":
                lines.append("CI unread  %s  %s" % (tag, run["why"]))
    if not result.get("mutation", True):
        head = "mutation half not run (--ci-only)"
    elif measured:
        with_miss = sum(1 for r in measured if commit_misses(r))
        head = "misses %d of %d commits (mutation)" % (with_miss, len(measured))
    else:
        head = "misses unknown (no commit could be measured)"
    if ci is None:
        tail_text = "CI not asked (--no-ci)"
    elif not ci["asked"]:
        tail_text = "CI could-not-ask (%s)" % (ci["why"],)
    else:
        read = [r for r in ci["runs"] if r["status"] == "read"]
        tail_text = "%d of %d runs (CI)" % (
            sum(1 for r in read if r["missed"]), len(read))
        if not ci["runs"]:
            tail_text += " - gh answered, and no failed run falls in the window"
        apart = [r for r in ci["runs"] if r["status"] != "read"]
        if apart:
            tail_text += ", %d run(s) set apart (%d named no suite, %d unread)" % (
                len(apart), sum(1 for r in apart if r["status"] == "no-suite"),
                sum(1 for r in apart if r["status"] == "unread"))
    lines.append("%s; %s" % (head, tail_text))
    return lines


# --- the command line -----------------------------------------------------------------
def main(argv, out=None):
    out = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser(
        prog="measure-affected-miss.py",
        description="How often tools/affected.py leaves out a suite that went red.")
    parser.add_argument("--commits", type=int, default=DEFAULTS["commits"])
    parser.add_argument("--rev", default=DEFAULTS["rev"])
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--sweep-cmd", default=None,
                        help="the sweep, run in each scratch worktree")
    parser.add_argument("--affected-cmd", default=None,
                        help="the selector; {base} is the parent commit")
    parser.add_argument("--timeout", type=int, default=DEFAULTS["timeout"])
    parser.add_argument("--budget-minutes", type=float, default=None)
    parser.add_argument("--no-ci", action="store_true")
    parser.add_argument("--ci-only", action="store_true",
                        help="skip the mutation half; needs --ci-since")
    parser.add_argument("--ci-since", default=None)
    parser.add_argument("--ci-limit", type=int, default=DEFAULTS["ci_limit"])
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if args.commits < 1:
        sys.stderr.write("measure-affected-miss: --commits must be at least 1\n")
        return 2
    if args.ci_only and (args.no_ci or not args.ci_since):
        sys.stderr.write("measure-affected-miss: --ci-only needs --ci-since and "
                         "cannot be combined with --no-ci\n")
        return 2
    overrides = {"commits": args.commits, "rev": args.rev, "timeout": args.timeout,
                 "budget_minutes": args.budget_minutes, "ci": not args.no_ci,
                 "mutation": not args.ci_only,
                 "ci_since": args.ci_since, "ci_limit": args.ci_limit}
    if args.sweep_cmd:
        overrides["sweep_cmd"] = shlex.split(args.sweep_cmd)
    if args.affected_cmd:
        overrides["affected_cmd"] = shlex.split(args.affected_cmd)
    opts = make_options(args.repo, **overrides)
    rc, _text = git(["rev-parse", "--show-toplevel"], opts["repo"], opts["env"])
    if rc != 0:
        sys.stderr.write("measure-affected-miss: %s is not a git checkout\n"
                         % (opts["repo"],))
        return 2

    def say(line):
        out.write(line + "\n")
        out.flush()

    result = measure(opts, None if args.json else say)
    if args.json:
        out.write(json.dumps(result, indent=1, sort_keys=True) + "\n")
    else:
        out.write("\n".join(render(result)) + "\n")
    if args.ci_only:
        return 0 if result["ci"] and result["ci"]["asked"] else 1
    return 0 if result["measured"] else 1


# --- selftest -----------------------------------------------------------------
# A fixture repository stands in for this one. Its sweep and its selector are two
# small scripts committed INTO it, so every scratch worktree the tool makes carries
# them - which is what lets the tool's own default commands (the real sweep, the
# real selector) stay out of the cases: those are measured by running the tool on
# this repository, not by a suite that would take minutes.
def _py(stem):
    # A module name assembled rather than written, because `_refs` reads every
    # `.py` basename literal under `tools/` and requires it to exist.
    return stem + "." + "py"


FAKE_SWEEP = """\
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
args = [a for a in sys.argv[1:] if not a.startswith("-")]
if not args:
    tdir = os.path.join(root, "tests")
    args = ["tests/" + n for n in sorted(os.listdir(tdir))
            if n.startswith("test_") and n.endswith("py")]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
bad = []
for rel in args:
    rc = subprocess.run([sys.executable, os.path.join(root, rel)], cwd=root,
                        env=env, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT).returncode
    if rc:
        bad.append(rel)
for rel in bad:
    print("FAIL  %s: exited 1" % rel)
print("%d/%d files ok, 0 cases" % (len(args) - len(bad), len(args)))
sys.exit(1 if bad else 0)
"""

FAKE_AFFECTED = """\
import json, os, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, "selection.txt")) as fh:
    names = [ln.strip() for ln in fh if ln.strip()]
if names == ["FULL"]:
    print(json.dumps({"full": True, "reasons": ["fixture"]}))
    sys.exit(2)
print(json.dumps({"full": False, "suites": names, "gates": [], "reasons": [],
                  "changed": []}))
"""

TEST_USES_MOD = """\
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mod_a
"""


def _write(path, text):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _fixture_env(root):
    env = dict(os.environ)
    nowhere = os.path.join(root, "no-such-gitconfig")
    env.update({"HOME": root, "USERPROFILE": root, "GIT_CONFIG_GLOBAL": nowhere,
                "GIT_CONFIG_SYSTEM": nowhere, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "f@example.invalid",
                "GIT_COMMITTER_NAME": "Fixture",
                "GIT_COMMITTER_EMAIL": "f@example.invalid"})
    env.pop("GIT_INDEX_FILE", None)
    return env


def build_repo(root, selection, broken=False, flaky=False):
    """A repository of two task commits over a base: one changes a module, one
    only a text file. `{"problem": str}` when git could not build it."""
    env = _fixture_env(root)
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    _write(os.path.join(repo, _py("mod_a")), "VALUE = 1\n")
    _write(os.path.join(repo, "tests", _py("test_a")), TEST_USES_MOD)
    _write(os.path.join(repo, "tests", _py("test_b")), TEST_USES_MOD)
    _write(os.path.join(repo, "tests", _py("test_c")), "print('independent')\n")
    if broken:
        _write(os.path.join(repo, "tests", _py("test_d")), "raise SystemExit(1)\n")
    if flaky:
        # Red the first time anything runs it, green after: the marker lives outside
        # the repository, so every scratch worktree of it shares the one memory.
        _write(os.path.join(repo, "tests", _py("test_e")),
               "import os, sys\nmarker = %r\nif not os.path.exists(marker):\n"
               "    open(marker, 'w').close()\n    sys.exit(1)\n"
               % os.path.join(root, "flaky-marker"))
    _write(os.path.join(repo, "tools", _py("fake_sweep")), FAKE_SWEEP)
    _write(os.path.join(repo, "tools", _py("fake_affected")), FAKE_AFFECTED)
    _write(os.path.join(repo, "selection.txt"), "".join(s + "\n" for s in selection))
    _write(os.path.join(repo, "notes.txt"), "one\n")
    steps = [(["init", "-q", "--initial-branch=main", "."], None),
             (["add", "-A"], None), (["commit", "-qm", "chore: fixture base"], None)]
    shas = {}
    for args, _ in steps:
        rc, text = git(args, repo, env)
        if rc != 0:
            return {"problem": "git %s: %s" % (args[0], text.strip())}
    _write(os.path.join(repo, _py("mod_a")), "VALUE = 2\n")
    for args in (["add", "-A"], ["commit", "-qm", "feat(P9.1): change the module"]):
        rc, text = git(args, repo, env)
        if rc != 0:
            return {"problem": "git %s: %s" % (args[0], text.strip())}
    rc, shas["module"] = git(["rev-parse", "HEAD"], repo, env)
    _write(os.path.join(repo, "notes.txt"), "one\ntwo\n")
    for args in (["add", "-A"], ["commit", "-qm", "docs(P9.2): a note"]):
        rc, text = git(args, repo, env)
        if rc != 0:
            return {"problem": "git %s: %s" % (args[0], text.strip())}
    rc, shas["note"] = git(["rev-parse", "HEAD"], repo, env)
    return {"repo": repo, "env": env, "shas": {k: v.strip() for k, v in shas.items()}}


def _fixture_opts(fx, **overrides):
    base = dict(
        sweep_cmd=[sys.executable, os.path.join("tools", _py("fake_sweep"))],
        affected_cmd=[sys.executable, os.path.join("tools", _py("fake_affected")),
                      "--json", "--base", "{base}"],
        env=fx["env"], ci=False)
    base.update(overrides)
    return make_options(fx["repo"], **base)


def _t(stem):
    return "tests/" + _py(stem)


def _cases(check):
    from _suite import remove_tree     # tools/_suite.py says why this is deferred

    # --- the readers, pure -----------------------------------------------------
    zed = "tools/" + _py("z")
    pad = _t("test_pad")
    sweep_red = ("sweep: 4 files, 2 workers\n\n"
                 "--- %s: exited 1 ---\nFAIL  %s: nested fixture\n"
                 "1/2 files ok, 3 cases\n\n"
                 "FAIL  %s: exited 1\n"
                 "FAIL  %s: timed out\n"
                 "EXEMPT a/b: not run here\n"
                 "2/4 files ok, 9 cases\n"
                 "FAIL  coverage: a module has no suite\n"
                 % (_t("test_b"), pad, _t("test_b"), zed))
    got = parse_sweep(sweep_red)
    check("m1 the sweep's own output is read into the suites that went red; a "
          "red that names no file is kept apart, and a run with no summary line "
          "is INCOMPLETE rather than clean",
          got["complete"] and got["red"] == [_t("test_b"), zed]
          and got["other"] == ["coverage"] and pad not in got["red"]
          and not parse_sweep("Traceback (most recent call last):\n")["complete"]
          and parse_sweep("")["red"] == [] and not parse_sweep("")["complete"])

    pre = "selftests (ubuntu)\tverify slice\t2026-10-20T15:55:33.9Z "
    win = "selftests (windows)\tverify slice\t2026-10-20T15:59:11.9Z "
    gate = "tools/" + _py("gate-parity")
    ci_log = (pre + "  FAILED  %s   exited 1  [49.2s]\n" % gate
              + pre + "FAIL  %s: nested fixture\n" % _t("test_pad")
              + pre + "1/2 files ok, 3 cases\n"
              + pre + "SELFTEST FAILED: 69/70 cases passed\n"
              + pre + "FAIL  %s: exited 1\n" % gate
              + pre + "107/108 files ok, 53 migrated to tests/, 4661 cases\n"
              + pre + "== selftests: FAILED (exit 1)\n"
              + win + "FAIL  %s: exited 1\n" % gate.replace("/", "\\")
              + win + "107/108 files ok, 4661 cases\n"
              + win + "\n"
              + win + "== selftests: FAILED (exit 1)\n"
              + "browser (panel)\tstep\t2026-10-20T15:59:11.9Z FAIL  panel gate\n")
    check("m2 a CI log's failing suites are read out of the prefixed lines above "
          "each job's final summary, once each across the jobs that repeat "
          "them, a backslash spelling folded to the posix one, and the nested "
          "block a failing suite's own output carries is not a verdict",
          parse_ci_log(ci_log) == [gate]
          and parse_ci_log("nothing here\n") == [])

    src = b"#!/usr/bin/env python3\n\"\"\"Doc.\"\"\"\nimport os\nVALUE = 1\n"
    boomed = mutate("raise", src)
    styled = mutate("style", src)
    import ast
    annotated = [a for n in ast.walk(ast.parse(styled.decode("utf-8")))
                 if isinstance(n, ast.FunctionDef)
                 for a in n.args.args if a.annotation is not None]
    check("m3 the import-time raise lands after the shebang and BEFORE the "
          "module's own statements, the style violation is an annotation the "
          "AST lint reads, and both leave the original bytes otherwise intact",
          boomed.startswith(b"#!/usr/bin/env python3\n")
          and b"raise" in boomed and boomed.index(b"raise") < boomed.index(b"import os")
          and boomed.endswith(src.split(b"\n", 1)[1])
          and styled.startswith(src) and len(annotated) == 1
          and mutate("raise", b"x = 1") != b"x = 1")

    sel = read_selection(0, json.dumps({
        "full": False, "suites": [_py("test_a")],
        "gates": ["python3 tools/where.py --selftest", "python3 tools/gate-parity.py"],
        "reasons": [], "changed": []}))
    full = read_selection(2, json.dumps({"full": True, "reasons": ["x"]}))
    bad = read_selection(1, "Traceback: boom")
    check("m4 a selection names its suites under tests/ and the tools whose OWN "
          "selftest it asked for - a gate that merely runs a tool is not its "
          "suite - the full set selects everything, and an unreadable answer is "
          "unreadable rather than empty",
          sel["readable"] and is_selected(sel, _t("test_a"))
          and is_selected(sel, "tools/where.py")
          and not is_selected(sel, "tools/gate-parity.py")
          and not is_selected(sel, _t("test_b"))
          and is_selected(sel, "plugins/audit/" + _t("test_a"))
          and not is_selected(sel, "plugins/audit/" + _t("test_b"))
          and full["readable"] and is_selected(full, _t("anything"))
          and not bad["readable"] and "boom" in bad["why"])

    log = ("aaa\tfeat(P12.3-x): a task\nbbb\tchore(audit-state): P12 - index\n"
           "ccc\tfix(P7.1): another\nddd\tMerge branch 'x'\n")
    tasks = parse_task_log(log)
    check("m5 a task commit is one whose subject names a phase task; the "
          "plan-state and merge commits between them are not",
          [t["sha"] for t in tasks] == ["aaa", "ccc"])

    # --- the measurement, against a fixture repository -------------------------
    roots = []

    def fixture(selection, broken=False, flaky=False):
        root = tempfile.mkdtemp(prefix="measure-affected-miss-selftest-")
        roots.append(root)
        return build_repo(root, selection, broken, flaky)

    def mutations_of(result, kind):
        return [m for r in result["commits"] for m in r["mutations"]
                if m["kind"] == kind]

    def tmp_scratch():
        return sorted(n for n in os.listdir(tempfile.gettempdir())
                      if n.startswith(SCRATCH_PREFIX))

    try:
        fx = fixture([_py("test_a")])
        if fx.get("problem"):
            check("m6 the fixture repository was built: %s" % (fx["problem"],), False)
            return
        snap = (git(["status", "--porcelain"], fx["repo"], fx["env"]),
                git(["worktree", "list"], fx["repo"], fx["env"]),
                git(["rev-parse", "HEAD"], fx["repo"], fx["env"]),
                tmp_scratch())
        result = measure(_fixture_opts(fx))
        text = "\n".join(render(result))
        raised = mutations_of(result, "raise")
        check("m6 on a fixture where a suite depends on the changed module and "
              "the selection omits it, the miss is counted AND named, under the "
              "mutation that exposes it",
              len(raised) == 1 and raised[0]["missed"] == [_t("test_b")]
              and raised[0]["red"] == 2
              and "misses 1 of 1 commits (mutation)" in text
              and "MISS  " in text and _t("test_b") in text)

        style = mutations_of(result, "style")
        check("m9 a mutation that turned NOTHING red is reported as inert rather "
              "than as a clean pass - the fixture's sweep reads no style lint, so "
              "this is the case that goes red if inert reads as zero misses",
              len(style) == 1 and style[0]["red"] == 0 and style[0]["inert"]
              and style[0]["missed"] == [] and "inert" in text)

        left = [r for r in result["commits"] if r["status"] == "no-python"]
        check("m6b a task commit that changed no Python is named and left out of "
              "the commits count, not measured as zero",
              len(left) == 1 and "no Python changed" in text
              and result["measured"] == 1)

        check("m13 the checkout is untouched by a run: same status, same HEAD, "
              "one worktree, no scratch tree left behind",
              (git(["status", "--porcelain"], fx["repo"], fx["env"]),
               git(["worktree", "list"], fx["repo"], fx["env"]),
               git(["rev-parse", "HEAD"], fx["repo"], fx["env"]),
               tmp_scratch()) == snap)

        inner = _fixture_opts(fx, scratch_dir=os.path.join(fx["repo"], "scratch"))
        os.makedirs(inner["scratch_dir"])
        refused = measure(inner)
        check("m14 a scratch directory inside the checkout is refused before a "
              "tree is made there: the commit is named as not measured and the "
              "directory stays empty",
              refused["measured"] == 0 and os.listdir(inner["scratch_dir"]) == []
              and any("inside the checkout" in r["why"] for r in refused["commits"]
                      if r["status"] == "could-not-measure"))

        # the selection holds every suite that goes red
        both = fixture([_py("test_a"), _py("test_b")])
        every = measure(_fixture_opts(both))
        every_text = "\n".join(render(every))
        every_raise = mutations_of(every, "raise")
        check("m8 a selection that includes every red suite counts zero misses - "
              "and the raise mutation DID turn suites red, so the zero is a "
              "measurement and not an inert run",
              every_raise[0]["red"] == 2 and every_raise[0]["unselected"] == 0
              and every_raise[0]["missed"] == [] and not every_raise[0]["inert"]
              and "misses 0 of 1 commits (mutation)" in every_text)

        fullset = measure(_fixture_opts(fixture(["FULL"])))
        check("m8b a full-set selection cannot miss: it is counted, named as the "
              "full set, and no sweep was run for it",
              fullset["measured"] == 1
              and [r["full"] for r in fullset["commits"]
                   if r["status"] == "measured"] == [True]
              and [r["mutations"] for r in fullset["commits"]
                   if r["status"] == "measured"] == [[]]
              and "full set" in "\n".join(render(fullset)))

        # a suite already red before any mutation is not a miss
        brk = fixture([_py("test_a")], broken=True)
        baseline = measure(_fixture_opts(brk))
        base_raise = mutations_of(baseline, "raise")[0]
        check("m7 a suite red on the commit with nothing mutated is not a miss: "
              "it is listed apart, and only the suite the mutation turned red "
              "is counted",
              base_raise["missed"] == [_t("test_b")]
              and base_raise["baseline_red"] == [_t("test_d")]
              and "already red unmutated" in "\n".join(render(baseline)))

        # a red that is gone on the second run is not a miss
        unsteady = measure(_fixture_opts(fixture([_py("test_a")], flaky=True)))
        steady_raise = mutations_of(unsteady, "raise")[0]
        check("m16 a suite that went red once and was green when run again is "
              "listed apart as a second-run green and not counted, so a timeout "
              "under load cannot become a miss; the suite the mutation really "
              "broke is still counted",
              steady_raise["flaky"] == [_t("test_e")]
              and steady_raise["missed"] == [_t("test_b")]
              and "green on the second run" in "\n".join(render(unsteady)))

        # a sweep that cannot be read is not a clean sweep
        broken_sweep = measure(_fixture_opts(
            fx, sweep_cmd=[sys.executable, os.path.join("tools", _py("absent"))]))
        broken_text = "\n".join(render(broken_sweep))
        check("m12 a sweep that printed no summary leaves the commit NOT "
              "MEASURED with the reason, and the headline says the rate is "
              "unknown rather than zero",
              broken_sweep["measured"] == 0
              and "NOT MEASURED" in broken_text
              and "misses unknown" in broken_text
              and "misses 0 of" not in broken_text)

        # the CI half
        saved_path = os.environ.get("PATH")
        empty = tempfile.mkdtemp(prefix="measure-affected-miss-nopath-")
        roots.append(empty)
        os.environ["PATH"] = empty
        try:
            nogh = ci_half(_fixture_opts(fx, ci=True), [fx["shas"]["module"]])
        finally:
            if saved_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = saved_path
        shown = "\n".join(render({
            "problem": "", "commits": result["commits"], "measured": 1,
            "stopped": None, "ci": nogh, "range": result["range"]}))
        check("m10 with no gh on PATH the CI half prints could-not-ask with the "
              "reason, and no count of runs that could read as zero",
              nogh["asked"] is False and "gh" in nogh["why"]
              and "could-not-ask" in shown and "runs (CI)" not in shown)

        stub_dir = tempfile.mkdtemp(prefix="measure-affected-miss-gh-")
        roots.append(stub_dir)
        module = fx["shas"]["module"]
        stamp = "2026-10-20T10:00:00Z"
        _write(os.path.join(stub_dir, "runs.json"), json.dumps([
            {"databaseId": 1, "headSha": module, "createdAt": stamp,
             "workflowName": "ci"},
            {"databaseId": 2, "headSha": module, "createdAt": stamp,
             "workflowName": "ci"},
            {"databaseId": 3, "headSha": "f" * 40, "createdAt": stamp,
             "workflowName": "ci"},
            {"databaseId": 4, "headSha": module, "createdAt": stamp,
             "workflowName": "ci"},
            {"databaseId": 5, "headSha": module, "createdAt": "1999-01-01T00:00:00Z",
             "workflowName": "ci"}]))
        _write(os.path.join(stub_dir, "log-1.txt"),
               "selftests\tverify\t2026 FAIL  %s: exited 1\n" % _t("test_b")
               + "selftests\tverify\t2026 1/2 files ok, 3 cases\n== selftests: FAILED\n")
        _write(os.path.join(stub_dir, "log-2.txt"),
               "selftests\tverify\t2026 FAIL  %s: exited 1\n" % _t("test_a")
               + "selftests\tverify\t2026 1/2 files ok, 3 cases\n== selftests: FAILED\n")
        _write(os.path.join(stub_dir, "log-3.txt"),
               "selftests\tverify\t2026 FAIL  %s: exited 1\n" % _t("test_a")
               + "selftests\tverify\t2026 1/2 files ok, 3 cases\n== selftests: FAILED\n")
        _write(os.path.join(stub_dir, "log-4.txt"), "Error: the lint job failed\n")
        _write(os.path.join(stub_dir, _py("gh_stub")),
               "import os, sys\n"
               "d = os.path.dirname(os.path.abspath(__file__))\n"
               "a = sys.argv[1:]\n"
               "if a[:2] == ['run', 'list']:\n"
               "    sys.stdout.write(open(os.path.join(d, 'runs.json')).read())\n"
               "elif a[:2] == ['run', 'view']:\n"
               "    sys.stdout.write(open(os.path.join(d, 'log-%s.txt' % a[2])).read())\n"
               "else:\n"
               "    sys.exit(3)\n")
        asked = ci_half(_fixture_opts(
            fx, ci=True, ci_since="2020-01-01",
            gh_cmd=[sys.executable, os.path.join(stub_dir, _py("gh_stub"))]), [])
        by_id = {r["id"]: r for r in asked["runs"]}
        shown_ci = "\n".join(render({
            "problem": "", "commits": result["commits"], "measured": 1,
            "stopped": None, "ci": asked, "range": result["range"]}))
        check("m11 the CI half reads each failed run's log against the selection "
              "for that run's own commit: the run whose failing suite the "
              "selection omits is a miss and is named, the run whose failing "
              "suite it holds is not, a run naming no suite and a run on a "
              "commit this clone lacks are set apart and named, and a run older "
              "than the window is not read",
              asked["asked"] and sorted(by_id) == [1, 2, 3, 4]
              and by_id[1]["missed"] == [_t("test_b")]
              and by_id[2]["status"] == "read" and by_id[2]["missed"] == []
              and by_id[3]["status"] == "unread" and "not in this clone" in by_id[3]["why"]
              and by_id[4]["status"] == "no-suite"
              and "1 of 2 runs (CI)" in shown_ci
              and "MISS  CI run 1" in shown_ci and "CI unread  CI run 3" in shown_ci)

        only = measure(_fixture_opts(
            fx, mutation=False, ci=True, ci_since="2020-01-01",
            gh_cmd=[sys.executable, os.path.join(stub_dir, _py("gh_stub"))]))
        only_text = "\n".join(render(only))
        check("m17 the CI half runs alone when asked to: no commit is mutated or "
              "swept, the headline says the mutation half was not run rather "
              "than reporting zero misses, and the CI count is still there",
              only["commits"] == [] and only["measured"] == 0
              and "mutation half not run" in only_text
              and "misses 0 of" not in only_text and "1 of 2 runs (CI)" in only_text
              and main(["--ci-only"], io.StringIO()) == 2)

        quiet = "\n".join(render({
            "problem": "", "commits": result["commits"], "measured": 1,
            "stopped": None, "range": result["range"],
            "ci": {"asked": True, "why": "", "runs": []}}))
        check("m18 a CI half that WAS answered and found no failed run in the "
              "window says so, in words, instead of a bare zero of zero",
              "0 of 0 runs (CI) - gh answered" in quiet)

        def _line(*argv):
            # The tool splits these two options with `shlex.split` (POSIX rules),
            # which eats the backslashes of a Windows path and breaks a path
            # holding a space; quoting each word is what survives that split.
            return " ".join(shlex.quote(a) for a in argv)

        out = io.StringIO()
        code = main(["--repo", fx["repo"], "--no-ci", "--sweep-cmd",
                     _line(sys.executable, os.path.join("tools", _py("fake_sweep"))),
                     "--affected-cmd",
                     _line(sys.executable, os.path.join("tools", _py("fake_affected")))
                     + " --json --base {base}"],
                    out)
        check("m15 the command line runs the same measurement and exits zero when "
              "a commit was measured, nonzero when none was, and two on a usage "
              "error",
              code == 0 and "misses 1 of 1 commits (mutation); CI not asked"
              in out.getvalue()
              and main(["--repo", fx["repo"], "--no-ci", "--sweep-cmd",
                        _line(sys.executable) + " -c pass"], io.StringIO()) == 1
              and main(["--commits", "0"], io.StringIO()) == 2
              and main(["--repo", tempfile.gettempdir(), "--no-ci"],
                       io.StringIO()) == 2)

        # The words a command line must survive: a Windows interpreter path and
        # one holding a space, round-tripped through the split the tool applies.
        # The second clause is the other direction: joined WITHOUT quoting, the
        # same words do not survive, so the first clause cannot pass vacuously.
        _hard = ["C:\\Python 3\\python.exe", "tools\\fake sweep.txt", "plain"]
        check("m15b a command line built with _line() survives the tool's own "
              "split word for word, backslashes and spaces included: %r"
              % (shlex.split(_line(*_hard)),),
              shlex.split(_line(*_hard)) == _hard
              and shlex.split(" ".join(_hard)) != _hard)
    finally:
        for r in roots:
            remove_tree(r)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    _output.safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
