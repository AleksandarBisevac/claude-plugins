#!/usr/bin/env python3
"""
The half of this plugin that writes to a repository, driven against a REAL one.

    tools/check-git-pipeline.py             # the gate
    tools/check-git-pipeline.py --keep      # ...and leave the fixture, path printed
    tools/check-git-pipeline.py --json      # machine-readable
    tools/check-git-pipeline.py --selftest  # this file's own cases

WHY THIS EXISTS. Nothing in the gate set ever created a git repository. `verify.sh`
and `ci.yml` between them ran the renderer, the validators, `--gate`, the usage views
and four hooks through the launcher - all of it against a manifest, a transcript or a
synthetic project directory, and none of it against a codebase with history. The
worked example under `examples/` is manifest data and rendered output: no source, no
commits, nothing to fork.

So an entire column of this product had never been executed by a gate. The commit
trail, the branch resolution, `guard-history-rewrite`'s ancestry question, the
journal's git anchor, the ledger's author - every one of them reads git, and every
one of them FAILS OPEN when git cannot be asked. That is the correct behaviour and it
is also why their absence was invisible: on a fixture with no `.git`, a check that
cannot run and a check that found nothing print the same thing.

`repair-commits.py` carries the receipt in its own source: `project_of` walks upward
for `.git` "instead of the manifest's own directory - which is what this did until it
was run against a real repo". That bug was found by a human driving the pipeline by
hand. This is that hand, in the gate set.

IT IS ALSO WHERE THE REMAINING HOOKS ARE WIRED. `ci.yml` drove four hooks through
`py-launch.sh` and said exactly why that is not optional - the selftests call
`decide()` directly and cannot prove the launcher, the stdin contract or the emitted
JSON. The hooks left out were `journal-writes`, `meter-usage`, `guard-history-rewrite`,
`guard-bash-writes` and `detect-plan-skip`, and the first two are the ones the
product's own adjectives rest on: "auditable" and "measurable". All five run here,
and three of them are here rather than beside the other four because their evidence
IS a repository - a ledger author from `git config`, a dirty set from
`git status --porcelain`, an ancestry question from `merge-base --is-ancestor`.
`remind-tdd.py` is wired in `ci.yml` beside the other launcher steps rather than
here, and belongs there because it needs NO repository: its evidence is its own
state file, keyed by session id. Every hook `hooks.json` registers is therefore
driven through the launcher by one side or the other, and none is a remainder.

WHAT THIS DOES NOT COVER, AND IT IS SAID HERE RATHER THAN IMPLIED. The pipeline has
two halves. The deterministic half is commands and hooks, and it is what runs below.
The other half is Claude - the explorer, the executor, the reviewer - and no gate can
drive it: there is no fixture that makes a model's output reproducible, and a check
that pretended otherwise would be asserting the shape of a prompt. A green run here
says the machinery around the model works on a real repository. It says nothing about
the model.

THE FIXTURE IS ISOLATED FROM THE MACHINE'S GIT, deliberately and by more than one
variable. `git config user.name` falls back to `~/.gitconfig`, so a fixture that only
sets a repo-local identity still answers with whoever is running the gate - measured
here, `resolve-branch` composed a branch carrying the developer's initials and the
case would have passed for the wrong reason, then failed on a runner with no identity
at all. Every lookup that could reach outside the fixture is pinned: the global and
system config files, `HOME` and its Windows spellings, and the session id the journal
puts in its own filenames.

Exit codes: 0 every check passed - 1 a check failed, or the fixture could not be
built, or nothing ran - 2 usage error.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`.
# Same shape as `tools/bench-hooks.py`, and for the same reason.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

_output.install_path()

HOOKS_DIR = os.path.join(REPO, "plugins", "audit", "hooks")
SCRIPTS_DIR = _scripts
def _sh_arg(path):
    """A path as a POSIX shell is handed one: "/" separators, on every platform.

    `py-launch.sh` finds its own directory by splitting `$0` on "/" - the only
    separator a POSIX shell has. `hooks.json` always spells the launcher with one,
    because it interpolates `${CLAUDE_PLUGIN_ROOT}/hooks/py-launch.sh`. A native
    Windows path has none, so the launcher would fall back to `.` and resolve every
    hook against the CALLER's directory instead of its own - which is the fixture
    root here, where no hook exists. The failure is silent in the sense that
    matters: each hook exits nonzero without deciding, and a runner reading
    "no decision" as "the guard allowed it" would call the whole pipeline green.

    Backslashes are replaced UNCONDITIONALLY rather than only `os.sep`. With
    `os.sep` this function is the identity on POSIX, so the case below could not
    ask it anything and would be green here whatever the body did - which is the
    shape of a check that only ever fails on the platform nobody runs locally.
    The same trade every `_config.slashed()` call in `hooks/` already takes.
    """
    return path.replace("\\", "/")


LAUNCHER = _sh_arg(os.path.join(HOOKS_DIR, "py-launch.sh"))

# The fixture's identity. A name whose initials are unambiguous, and a domain that
# can never resolve: `.invalid` is reserved for exactly this by RFC 2606, so no
# machine anywhere can be tricked into contacting it.
FIXTURE_NAME = "Ada Lovelace"
FIXTURE_EMAIL = "ada@example.invalid"
FIXTURE_INITIALS = "al"
FIXTURE_BRANCH = "main"

# The one source file the fixture's task names. Not a `.py`: every python-module
# basename written under `tools/` has to name a file that exists
# (`_refs.tool_basename_drift()`), and a fixture's invented name would be a
# violation of it. A `.ts` is also what the starter manifest's example task uses.
FIXTURE_SRC = "src/cart.ts"

MANIFEST_REL = "docs/audit/audit-plan.json"

# A SHA that is 40 legal hex characters and names nothing. Assembled rather than
# written so it cannot be mistaken for a real commit anybody could look up.
ABSENT_SHA = "0" * 40


# --- the fixture --------------------------------------------------------------
def fixture_env(root):
    """The environment every subprocess in this run gets.

    PINNED, NOT INHERITED, and the list is the argument. `git config user.name`
    reads the repo, then `~/.gitconfig`, then `/etc/gitconfig`; the journal names
    its files after `$CLAUDE_CODE_SESSION_ID` when that is set. Leave any of them
    ambient and a case passes on the machine that wrote it because of a value that
    machine happened to have - which is not a passing case, it is an unasked
    question with a tick beside it.

    `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` point at a path inside the fixture that
    is never created: git reads a missing config file as an empty one. `HOME` and
    the two Windows spellings are set as well, because those variables are what an
    older git consults and this runs on both CI platforms.
    """
    env = dict(os.environ)
    nowhere = os.path.join(root, "no-such-gitconfig")
    env.update({
        "HOME": root,
        "USERPROFILE": root,
        "GIT_CONFIG_GLOBAL": nowhere,
        "GIT_CONFIG_SYSTEM": nowhere,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": FIXTURE_NAME,
        "GIT_AUTHOR_EMAIL": FIXTURE_EMAIL,
        "GIT_COMMITTER_NAME": FIXTURE_NAME,
        "GIT_COMMITTER_EMAIL": FIXTURE_EMAIL,
        "CLAUDE_PROJECT_DIR": root,
    })
    # Not set to a fixture value - REMOVED. The journal embeds this id in its own
    # filenames, and a run that inherited the developer's would produce a different
    # tree from a run on CI.
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    return env


def run(argv, cwd, env, stdin=None):
    """`(returncode, output)` for one subprocess. stdout and stderr, in order.

    Output is kept on a NON-ZERO exit, which is the whole reason this is a helper:
    every command driven here - the validators, `--gate`, `repair-commits` in report
    mode - exits non-zero BY DESIGN and writes its answer to stdout. A runner that
    returned stderr alone on failure would throw away the thing being asserted.
    """
    try:
        out = subprocess.run(argv, cwd=cwd, env=env,
                             input=stdin.encode("utf-8") if stdin else None,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=120)
    except Exception as exc:
        return None, "could not be run: %s" % (exc,)
    return out.returncode, out.stdout.decode("utf-8", "replace")


def git(fx, *args):
    """`(returncode, output)` for one git command inside the fixture."""
    return run([fx["git"]] + list(args), fx["root"], fx["env"])


def script(fx, name, *args):
    """Run one of the plugin's commands, resolved by basename under `scripts/`."""
    path = _resolve_script(name)
    if path is None:
        return None, "no script named %r under scripts/" % (name,)
    return run([sys.executable, path] + list(args), fx["root"], fx["env"])


def _resolve_script(name):
    """Full path of a `scripts/` command by basename, or None.

    By basename because the folders under `scripts/` are labels and not namespaces -
    the same resolution `_loader` and `hooks/_config.find_script()` use, so a command
    moved into another domain directory does not break this file.
    """
    for rel, path in _output.py_files(SCRIPTS_DIR):
        if os.path.basename(rel) == name:
            return path
    return None


def hook(fx, name, mode, payload):
    """Drive one hook THROUGH `py-launch.sh`, exactly as `hooks.json` does.

    Not `python3 hooks/<name>`: the launcher, the stdin contract and the emitted
    JSON shape are precisely what a selftest calling `decide()` cannot prove, which
    is what the four existing wiring steps in `ci.yml` say about themselves.
    """
    return run([fx["sh"], LAUNCHER, name, mode], fx["root"], fx["env"],
               stdin=json.dumps(payload))


def manifest_body(commit=None, task_status="in_progress"):
    """The fixture's manifest. Small, and valid against `_manifest_rules`.

    A template with a `{initials}` placeholder on purpose: the legacy
    `meta.branchPrefix` shape has nowhere for an identity to land, so a fixture
    using it could not tell a branch composed from the repo's git identity from one
    composed without it.
    """
    return {
        "meta": {
            "version": 2, "repo": "git-fixture",
            "title": "a real repository, for the gate set",
            "developmentBranch": FIXTURE_BRANCH,
            "branch": {"template": "{type}/{initials}/{phase}-{slug}",
                       "defaultType": "feature", "types": ["feature", "fix"]},
            "buildCommands": {},
        },
        "phases": [{
            "id": "P1", "title": "phase", "status": "in_progress",
            "blockedBy": [], "testGate": [],
            "tasks": [{
                "id": "P1.1", "title": "task", "status": task_status,
                "files": [FIXTURE_SRC], "blockedBy": [], "dependsOn": [],
                "commit": commit, "attempts": 1, "maxAttempts": 3,
            }],
        }],
        "fileIndex": {FIXTURE_SRC: ["P1.1"]},
        "bugs": [], "proposals": [],
    }


def write_manifest(fx, body):
    path = os.path.join(fx["root"], MANIFEST_REL)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(body, indent=1, sort_keys=True))


def read_manifest(fx):
    path = os.path.join(fx["root"], MANIFEST_REL)
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def build_fixture(root):
    """A real git repository with source, a commit and a branch.

    `{"root", "head", "git", "sh", "env", "problem"}` - and `problem` is set instead
    of raising, because a half-built fixture must never be handed to the checks. A
    check run against a repository whose first commit failed would report the
    plugin as broken, and the finding would name the wrong thing entirely.

    Every git call's exit code is read. `git init` followed by
    `symbolic-ref HEAD` rather than `init -b`: the flag arrived in git 2.28 and the
    branch name is asserted below, so buying it with a version floor would be a
    version floor bought for a fixture.
    """
    git_bin = shutil.which("git")
    sh_bin = shutil.which("sh")
    if not git_bin:
        return {"problem": "git is not on PATH, so the half of the pipeline that "
                           "writes to a repository cannot be exercised at all - "
                           "reported rather than skipped"}
    if not sh_bin:
        return {"problem": "no POSIX sh on PATH, so `py-launch.sh` cannot be "
                           "driven - the hook wiring is what this proves, and "
                           "unproven is not the same answer as proven"}
    fx = {"root": root, "git": git_bin, "sh": sh_bin, "env": fixture_env(root),
          "head": None, "problem": None}

    for rel in ("src", "docs/audit"):
        os.makedirs(os.path.join(root, rel.replace("/", os.sep)))
    with io.open(os.path.join(root, FIXTURE_SRC.replace("/", os.sep)), "w",
                 encoding="utf-8") as fh:
        fh.write("export const cart = 1;\n")
    write_manifest(fx, manifest_body())

    steps = (
        ("init", ("init", "-q")),
        # The default branch, without depending on `init -b`.
        ("branch", ("symbolic-ref", "HEAD", "refs/heads/" + FIXTURE_BRANCH)),
        # Line endings pinned: on Windows an autocrlf checkout commits LF while the
        # working file is CRLF, and the journal's git anchor compares BYTES.
        ("autocrlf", ("config", "core.autocrlf", "false")),
        ("name", ("config", "user.name", FIXTURE_NAME)),
        ("email", ("config", "user.email", FIXTURE_EMAIL)),
        ("add", ("add", "-A")),
        ("commit", ("commit", "-q", "-m", "seed the fixture")),
    )
    for label, args in steps:
        code, out = git(fx, *args)
        if code != 0:
            return {"problem": "building the fixture failed at `git %s`: %s"
                               % (label, (out or "").strip()[:300])}
    code, out = git(fx, "rev-parse", "HEAD")
    if code != 0 or not out.strip():
        return {"problem": "the fixture has no HEAD after its first commit, so "
                           "there is no history to fork: %s" % (out or "").strip()}
    fx["head"] = out.strip()
    return fx


# --- the checks ---------------------------------------------------------------
# Each takes the fixture and returns `(ok, detail)`. `detail` is printed on a
# failure AND recorded on a pass, so a green run still shows what it saw - a check
# whose evidence is invisible on success is a check nobody can audit later.
def check_branch_identity(fx):
    """`resolve-branch.py` reads the repository's git identity."""
    code, out = script(fx, "resolve-branch.py", MANIFEST_REL, "--phase", "P1",
                       "--json")
    if code != 0:
        return False, "exit %r: %s" % (code, out.strip()[:300])
    try:
        ans = json.loads(out)
    except Exception as exc:
        return False, "output is not JSON (%s): %s" % (exc, out.strip()[:200])
    want = "feature/%s/p1-phase" % FIXTURE_INITIALS
    ok = (ans.get("initialsSource") == "git user.name"
          and ans.get("branch") == want
          and ans.get("parent") == FIXTURE_BRANCH)
    return ok, ("initialsSource=%r branch=%r parent=%r (wanted branch %r)"
                % (ans.get("initialsSource"), ans.get("branch"),
                   ans.get("parent"), want))


def check_trail_resolves(fx):
    """A recorded commit that really exists is reported as resolving."""
    write_manifest(fx, manifest_body(commit=fx["head"]))
    code, out = script(fx, "repair-commits.py", MANIFEST_REL, "--json")
    if code != 0:
        return False, "exit %r: %s" % (code, out.strip()[:300])
    try:
        ans = json.loads(out)
    except Exception as exc:
        return False, "output is not JSON (%s): %s" % (exc, out.strip()[:200])
    ok = (ans.get("recorded") == 1 and ans.get("lost") == []
          and ans.get("unchecked") == [])
    return ok, ("recorded=%r lost=%r unchecked=%r"
                % (ans.get("recorded"), ans.get("lost"), ans.get("unchecked")))


def check_trail_missing(fx):
    """A fabricated SHA is `missing` and not `unchecked`.

    THE DISTINCTION IS THE POINT. `unchecked` is what a shallow clone produces -
    git was asked and could not answer past the graft boundary - and folding the
    two together is the F88 class: the doctor's remedy for `missing` NULLS the
    recorded SHAs, so a clone that could not answer would have destroyed a trail
    that was intact. A repository this gate creates itself is never shallow, so
    `missing` is the answer that proves the accusation path is reachable at all.
    """
    write_manifest(fx, manifest_body(commit=ABSENT_SHA))
    code, out = script(fx, "repair-commits.py", MANIFEST_REL, "--json")
    if code != 1:
        return False, "expected exit 1 in report mode, got %r: %s" % (
            code, out.strip()[:300])
    try:
        ans = json.loads(out)
    except Exception as exc:
        return False, "output is not JSON (%s): %s" % (exc, out.strip()[:200])
    missing = [r.get("taskId") for r in ans.get("missing") or []]
    ok = (missing == ["P1.1"] and ans.get("unchecked") == []
          and ans.get("unreachable") == [])
    return ok, ("missing=%r unreachable=%r unchecked=%r"
                % (missing, ans.get("unreachable"), ans.get("unchecked")))


def check_trail_repair(fx):
    """`--apply` clears the SHA and leaves a journal row saying what was lost."""
    code, out = script(fx, "repair-commits.py", MANIFEST_REL, "--apply")
    if code != 0:
        return False, "exit %r: %s" % (code, out.strip()[:300])
    body = read_manifest(fx)
    cleared = body and body["phases"][0]["tasks"][0].get("commit") is None
    rows = journal_rows(fx)
    repaired = [r for r in rows if r.get("action") == "trail.repair"]
    was = [c.get("from") for r in repaired
           for c in ((r.get("details") or {}).get("changes") or [])]
    ok = bool(cleared) and len(repaired) == 1 and was == [ABSENT_SHA]
    return ok, ("commit cleared=%r trail.repair rows=%d, recording from=%r"
                % (cleared, len(repaired), was))


def check_rewrite_allows_plain_reset(fx):
    """`git reset --hard` with NO ref is allowed while a SHA is recorded.

    THE SECOND-DIRECTION CASE, and the one that decides whether this guard survives
    contact with a human. A guard that refused every `reset --hard` would fire on
    abandoning a botched task attempt - correct work - and a guard that fires on
    correct work gets switched off, after which it protects nothing. The guard's own
    docstring says so; nothing ran it against a repository to find out.
    """
    write_manifest(fx, manifest_body(commit=fx["head"]))
    code, out = hook(fx, "guard-history-rewrite.py", "ask", bash_payload(
        fx, "git reset --hard"))
    ok = code == 0 and out.strip() == ""
    return ok, "exit %r, output %r" % (code, out.strip()[:200])


def check_rewrite_denies_orphaning_reset(fx):
    """A reset that orphans the recorded tip is refused, naming the task.

    Needs TWO commits and a real ancestry question - `merge-base --is-ancestor` -
    which is precisely what no fixture in the gate set could ask.
    """
    code, _out = git(fx, "commit", "-q", "--allow-empty", "-m", "a second commit")
    if code != 0:
        return False, "the fixture could not take a second commit"
    code, out = git(fx, "rev-parse", "HEAD")
    if code != 0:
        return False, "the fixture has no new HEAD"
    write_manifest(fx, manifest_body(commit=out.strip()))
    code, out = hook(fx, "guard-history-rewrite.py", "ask", bash_payload(
        fx, "git reset --hard HEAD~1"))
    decision, reason = decision_of(out)
    ok = code == 0 and decision == "deny" and "P1.1" in (reason or "")
    return ok, "exit %r decision=%r reason=%r" % (code, decision,
                                                  (reason or "")[:160])


def check_rewrite_denies_force_push(fx):
    """A force-push is refused while any SHA is recorded."""
    code, out = hook(fx, "guard-history-rewrite.py", "ask", bash_payload(
        fx, "git push --force origin " + FIXTURE_BRANCH))
    decision, reason = decision_of(out)
    ok = code == 0 and decision == "deny"
    return ok, "exit %r decision=%r reason=%r" % (code, decision,
                                                  (reason or "")[:160])


def check_journal_wiring(fx):
    """`journal-writes.py` through the launcher: both passes, and the chained rows.

    F53. Two hooks carry the product's own adjectives - this one is "auditable" -
    and neither was driven through `py-launch.sh` by anything. The Pre pass caches
    the manifest's bytes and the Post pass diffs them, so a hook whose wiring was
    broken in either direction would simply write nothing, which is what a hook that
    is not registered also does.
    """
    reset_journal(fx)
    write_manifest(fx, manifest_body(task_status="in_progress"))
    target = os.path.join(fx["root"], MANIFEST_REL.replace("/", os.sep))
    code, out = hook(fx, "journal-writes.py", "open",
                     edit_payload(fx, target, "PreToolUse"))
    if code != 0:
        return False, "the Pre pass exited %r: %s" % (code, out.strip()[:200])
    # The edit the two passes bracket. This is the orchestrator's job in a real
    # run, and the row's content is a diff of before and after - so the fixture has
    # to actually change the file between them.
    write_manifest(fx, manifest_body(commit=fx["head"], task_status="done"))
    code, out = hook(fx, "journal-writes.py", "open",
                     edit_payload(fx, target, "PostToolUse"))
    if code != 0:
        return False, "the Post pass exited %r: %s" % (code, out.strip()[:200])
    rows = journal_rows(fx)
    actions = [r.get("action") for r in rows]
    recorded = [r.get("summary") for r in rows if r.get("action") == "task.commit"]
    ok = (actions == ["manifest.edit", "task.complete", "task.commit"]
          and len(recorded) == 1 and fx["head"][:12] in (recorded[0] or ""))
    return ok, "actions=%r task.commit summary=%r" % (actions, recorded)


def check_journal_anchor_holds(fx):
    """Committing the journal does not itself produce a finding.

    THE SECOND-DIRECTION CASE FOR `check_journal_anchor_fires`, and it is narrower
    than it first looks - said here because a label that overclaims is worse than a
    check that is narrow. `verify()` runs ONE porcelain over the journal directory
    and pays the per-file anchor only for files that are tracked AND dirty; a clean
    committed file is byte-identical to HEAD, so the prefix holds trivially and
    `_git_anchor_finding` is never reached. What this proves is that the batching
    keeps a clean committed journal green - which is the failure a guard that fired
    on every commit would have, and the one that gets a check switched off.
    """
    for args in (("add", "-A"), ("commit", "-q", "-m", "commit the journal")):
        code, out = git(fx, *args)
        if code != 0:
            return False, "could not commit the journal: %s" % (out or "")[:200]
    code, out = script(fx, "audit-journal.py", "verify", "--project", ".")
    ok = code == 0 and "chain cleanly" in out
    return ok, "exit %r: %s" % (code, out.strip()[:200])


def check_journal_anchor_fires(fx):
    """Removing a COMMITTED row is caught by the git anchor, and only by it.

    The forgery this anchor exists for is "rewrite the file and recompute every
    hash", which the chain alone cannot see. Truncating a committed row is the
    cheapest way to break the anchor WITHOUT breaking the chain: the rows that
    remain still hash to their predecessors, so exactly one finding should come
    back and it should be the anchor. Counting them is the assertion - a mutation
    that broke both would pass a check that only looked for the word.

    Unreachable outside a real repository: `_git_anchor_finding` fails open on "not
    a repository" and on "untracked", so on every fixture the gate set had before
    this one it returned None and the check was invisible.
    """
    path = journal_files(fx)[:1]
    if not path:
        return False, "the fixture has no journal file to tamper with"
    lines = io.open(path[0], encoding="utf-8").read().splitlines()
    if len(lines) < 2:
        return False, "the journal has too few rows to truncate one meaningfully"
    try:
        with io.open(path[0], "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines[:-1]) + "\n")
        code, out = script(fx, "audit-journal.py", "verify", "--project", ".")
    finally:
        # Put it back whatever happened. This is the only check that damages the
        # fixture on purpose, and the ones after it read the same tree - a raise
        # between the two writes would hand them a journal this check broke and
        # they would report the plugin for it.
        with io.open(path[0], "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    findings = [ln for ln in out.splitlines() if ln.startswith("FINDING:")]
    anchored = [ln for ln in findings if "committed past changed" in ln]
    ok = code == 1 and len(findings) == 1 and len(anchored) == 1
    return ok, ("exit %r, %d finding(s): %s"
                % (code, len(findings),
                   _output.some_of(findings, render=repr)))


def check_meter_wiring(fx):
    """`meter-usage.py` through the launcher, and the ledger's author is git's.

    F53's other half - this hook is what "measurable" rests on. The author is the
    assertion that needs the repository: `resolve_author` asks
    `git config --get user.email` and falls back to `$USER`, so on a fixture with
    no `.git` the row carries whoever ran the gate and the check would be green for
    a reason that has nothing to do with the code.
    """
    path = write_transcript(fx, "meter-1")
    code, out = hook(fx, "meter-usage.py", "open", {
        "hook_event_name": "SessionEnd", "session_id": "meter-1",
        "cwd": fx["root"], "transcript_path": path})
    if code != 0:
        return False, "exit %r: %s" % (code, out.strip()[:200])
    rows = ledger_rows(fx)
    said = ""
    try:
        said = (json.loads(out) or {}).get("systemMessage") or ""
    except Exception:
        said = ""
    ok = (len(rows) == 1 and rows[0].get("author") == FIXTURE_EMAIL
          and rows[0].get("in") == 300 and rows[0].get("out") == 130
          and "this session" in said)
    return ok, ("rows=%d author=%r in/out=%r/%r said=%r"
                % (len(rows), rows[0].get("author") if rows else None,
                   rows[0].get("in") if rows else None,
                   rows[0].get("out") if rows else None, said[:80]))


def check_meter_does_not_double_count(fx):
    """A second Stop over the same transcript adds nothing.

    The cursor is a FILE OFFSET under the ledger directory, and a lost cursor
    re-scans from zero. Counted rather than looked for: "a row exists" is true
    whether the ledger holds one or two.
    """
    before = ledger_rows(fx)
    path = os.path.join(fx["root"], "transcripts", "meter-1.jsonl")
    code, out = hook(fx, "meter-usage.py", "open", {
        "hook_event_name": "Stop", "session_id": "meter-1",
        "cwd": fx["root"], "transcript_path": path})
    after = ledger_rows(fx)
    ok = code == 0 and len(after) == len(before) and len(after) == 1
    return ok, ("rows before=%d after=%d, exit %r, output %r"
                % (len(before), len(after), code, out.strip()[:120]))


def check_bash_writes_wiring(fx):
    """`guard-bash-writes.py` notices a shell write by diffing real `git status`.

    THE HOOK WHOSE EVIDENCE IS `git status` ITSELF. It snapshots the dirty set on
    one call and compares it on the next, so a fixture with no repository gives it
    nothing to diff and it stays silent - the same silence a hook that is not wired
    at all produces. Two calls are needed for the same reason: the first has no
    baseline to be new against.

    The warning is an `additionalContext` injection and never a decision, which is
    also asserted: a PostToolUse hook cannot undo a write, and one that emitted a
    permission decision here would be claiming a power it does not have.
    """
    baseline = {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                "session_id": "bash-writes", "cwd": fx["root"],
                "tool_input": {"command": "ls -la"}}
    code, _out = hook(fx, "guard-bash-writes.py", "open", baseline)
    if code != 0:
        return False, "the baseline call exited %r" % (code,)
    # A shell write the plan gate never saw: not through Edit, not exempt, and
    # inside a task's own file list.
    with io.open(os.path.join(fx["root"], FIXTURE_SRC.replace("/", os.sep)), "a",
                 encoding="utf-8") as fh:
        fh.write("export const sneaked = 2;\n")
    code, out = hook(fx, "guard-bash-writes.py", "open", dict(
        baseline, tool_input={"command": "printf x >> " + FIXTURE_SRC}))
    said = ""
    try:
        block = (json.loads(out) or {}).get("hookSpecificOutput") or {}
        said = block.get("additionalContext") or ""
    except Exception:
        said = ""
    decision, _reason = decision_of(out)
    ok = (code == 0 and os.path.basename(FIXTURE_SRC) in said
          and decision is None)
    return ok, ("exit %r decision=%r additionalContext=%r"
                % (code, decision, said[:160]))


def check_prompt_hook_wiring(fx):
    """`detect-plan-skip.py` arms the bypass through the launcher.

    The UserPromptSubmit lane, which nothing in the gate set drove. It is the one
    hook that writes state on a PROMPT rather than on a tool call, so a wiring
    break here is invisible in every other check: the bypass simply never arms and
    the plan gate goes on denying, which looks like the gate working.
    """
    state = os.path.join(fx["root"], ".claude", "state")
    before = set(os.listdir(state)) if os.path.isdir(state) else set()
    code, out = hook(fx, "detect-plan-skip.py", "open", {
        "hook_event_name": "UserPromptSubmit", "session_id": "prompt-1",
        "cwd": fx["root"], "prompt": "tidy this up #no-plan"})
    after = set(os.listdir(state)) if os.path.isdir(state) else set()
    armed = sorted(n for n in (after - before) if n.startswith("plan-bypass-"))
    said = ""
    try:
        said = (json.loads(out) or {}).get("systemMessage") or ""
    except Exception:
        said = ""
    ok = code == 0 and len(armed) == 1 and "bypass" in said.lower()
    return ok, "exit %r armed=%r said=%r" % (code, armed, said[:120])


def check_invariants_have_a_basis(fx):
    """`verify-invariants.py` EXAMINES commit scope rather than reporting no basis.

    Every verdict this command prints carries the evidence it rests on, and on a
    project with no history the honest answer to most of them is `no-basis`. That
    is exactly why running it there proves nothing: the command would print a clean
    page whether or not the check underneath it worked. `commit-scope` reads
    `git show --name-only` against a recorded SHA, so it has a subject here.
    """
    write_manifest(fx, manifest_body(commit=fx["head"], task_status="done"))
    code, out = script(fx, "verify-invariants.py", MANIFEST_REL, "--all",
                       "--project", ".")
    scope = [ln.strip() for ln in out.splitlines()
             if ln.strip().startswith("commit-scope")]
    ok = (code == 0 and len(scope) == 1 and "no-basis" not in scope[0]
          and "examined" in scope[0])
    return ok, "exit %r, commit-scope line %r" % (code, scope[:1])


# ONE FIXTURE, IN ORDER, and that is a decision rather than an accident. Building a
# repository per check would be honest and slower, and the order carries real
# meaning: `g6` needs a SECOND commit for there to be an ancestry question at all,
# `g9` needs the journal `g8` wrote, and `g10` needs `g9`'s commit to have happened.
# What the order costs is that a reordering breaks checks silently, so each one
# above says what it needs and what it leaves behind, and the only check that
# damages the tree puts it back under `finally`.
CHECKS = (
    ("g1  branch resolution reads the repository's git identity",
     check_branch_identity),
    ("g2  a recorded commit that exists is reported as resolving",
     check_trail_resolves),
    ("g3  a fabricated SHA is `missing`, not `unchecked`", check_trail_missing),
    ("g4  --apply clears it and journals what was lost", check_trail_repair),
    ("g5  `git reset --hard` with no ref is ALLOWED",
     check_rewrite_allows_plain_reset),
    ("g6  a reset that orphans the recorded tip is refused",
     check_rewrite_denies_orphaning_reset),
    ("g7  a force-push is refused while a SHA is recorded",
     check_rewrite_denies_force_push),
    ("g8  journal-writes is WIRED: both passes, three chained rows",
     check_journal_wiring),
    ("g9  committing the journal is not itself a finding",
     check_journal_anchor_holds),
    ("g10 removing a committed row fires the git anchor, and only it",
     check_journal_anchor_fires),
    ("g11 meter-usage is WIRED: a ledger row, authored by git's identity",
     check_meter_wiring),
    ("g12 ...and a second pass over one transcript adds nothing",
     check_meter_does_not_double_count),
    ("g13 guard-bash-writes is WIRED: a shell write is seen in `git status`",
     check_bash_writes_wiring),
    ("g14 detect-plan-skip is WIRED: a prompt arms the bypass",
     check_prompt_hook_wiring),
    ("g15 the invariants have a basis to examine, not `no-basis`",
     check_invariants_have_a_basis),
)


# --- reading what the run produced --------------------------------------------
def journal_files(fx):
    root = os.path.join(fx["root"], "docs", "audit", "journal")
    out = []
    for base, _dirs, names in os.walk(root):
        for name in sorted(names):
            if name.endswith(".jsonl"):
                out.append(os.path.join(base, name))
    return sorted(out)


def _read_jsonl(paths):
    """Every row across `paths`, in file then line order. A line that will not parse
    is DROPPED and the drop is visible in the count, which every caller asserts on -
    a silent skip inside a reader is how a check comes to assert about half a file."""
    rows = []
    for path in paths:
        try:
            text = io.open(path, encoding="utf-8").read()
        except OSError:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def journal_rows(fx):
    return _read_jsonl(journal_files(fx))


def reset_journal(fx):
    """Empty the journal directory so a check counts only its own rows.

    THE CAREFUL REMOVAL EVEN THOUGH THIS TREE HOLDS NO OBJECTS (F155). What is
    under here is the journal's own text, and a plain removal would take it on
    either platform. The rule this file now answers to is per MODULE and not per
    directory, and that is the point of it: "which of these trees has a `.git` in
    it" is the judgement F155 asked at every site and it came back wrong more than
    once. On a tree with no read-only file the helper's second half never runs, so
    uniformity inside a repository-building tool costs nothing and removes the
    judgement.
    """
    from _suite import remove_tree   # tools/_suite.py says why the import is here
    remove_tree(os.path.join(fx["root"], "docs", "audit", "journal"))


def ledger_rows(fx):
    root = os.path.join(fx["root"], ".claude", "usage")
    paths = []
    for name in sorted(os.listdir(root) if os.path.isdir(root) else []):
        if name.endswith(".jsonl"):
            paths.append(os.path.join(root, name))
    return _read_jsonl(paths)


def write_transcript(fx, session):
    """A transcript with two priced assistant turns. Returns its path.

    The counts are chosen so the two turns cannot be confused with one: a scan that
    read only the first, or read the file twice, produces a different total either
    way.
    """
    root = os.path.join(fx["root"], "transcripts")
    if not os.path.isdir(root):
        os.makedirs(root)
    path = os.path.join(root, session + ".jsonl")
    turns = [
        {"type": "assistant", "timestamp": "2026-08-24T10:00:00Z",
         "gitBranch": FIXTURE_BRANCH,
         "message": {"id": "m1", "model": "claude-opus-5",
                     "usage": {"input_tokens": 100, "output_tokens": 50,
                               "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 0}}},
        {"type": "assistant", "timestamp": "2026-08-24T10:05:00Z",
         "gitBranch": FIXTURE_BRANCH,
         "message": {"id": "m2", "model": "claude-opus-5",
                     "usage": {"input_tokens": 200, "output_tokens": 80,
                               "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 0}}},
    ]
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(t) for t in turns) + "\n")
    return path


def bash_payload(fx, command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash",
            "session_id": "git-fixture", "cwd": fx["root"],
            "tool_input": {"command": command}}


def edit_payload(fx, target, event):
    return {"hook_event_name": event, "tool_name": "Edit",
            "session_id": "git-fixture", "cwd": fx["root"],
            "tool_input": {"file_path": target,
                           "old_string": "in_progress", "new_string": "done"}}


def decision_of(text):
    """`(permissionDecision, reason)` from a hook's stdout, or `(None, None)`.

    Silence is `(None, None)` and so is unparseable output, which the callers tell
    apart by also reading the raw text: a guard that started printing a traceback
    would otherwise look exactly like a guard that allowed the call.
    """
    try:
        block = (json.loads(text) or {}).get("hookSpecificOutput") or {}
    except Exception:
        return None, None
    return block.get("permissionDecision"), block.get("permissionDecisionReason")


# --- running ------------------------------------------------------------------
def run_checks(fx, checks=None):
    """`[{"name", "ok", "detail"}]` for every check, in order.

    A check that RAISES becomes a failing row rather than aborting the run: the
    remaining checks are independent, and a runner that stopped at the first
    exception would report one defect where there were four. The exception text is
    the detail, so nothing is swallowed.
    """
    out = []
    for name, fn in (checks if checks is not None else CHECKS):
        try:
            ok, detail = fn(fx)
        except Exception as exc:
            ok, detail = False, "raised %s: %s" % (type(exc).__name__, exc)
        out.append({"name": name, "ok": bool(ok), "detail": detail})
    return out


def render(result, stream=None):
    """Print the verdict. Returns the exit code."""
    out = stream if stream is not None else sys.stdout
    if result.get("problem"):
        out.write("git pipeline: NOT CHECKED - %s\n" % result["problem"])
        return 1
    rows = result["checks"]
    failed = [r for r in rows if not r["ok"]]
    out.write("git pipeline: %d check(s) against a real repository at %s\n"
              % (len(rows), result["root"]))
    for row in rows:
        out.write("  %-4s %s\n" % ("ok" if row["ok"] else "FAIL", row["name"]))
        if not row["ok"]:
            out.write("       %s\n" % (row["detail"],))
    if not rows:
        # A filter that narrowed to nothing must not read as a clean run. This is
        # unreachable from `CHECKS` and reachable from a caller passing its own.
        out.write("  NOTHING RAN, which is not the same answer as nothing wrong\n")
        return 1
    if failed:
        out.write("BROKEN: %d of %d check(s) failed\n" % (len(failed), len(rows)))
        return 1
    out.write("OK: the deterministic half of the pipeline works on a real "
              "repository.\n")
    out.write("    The Claude-driven half - explorer, executor, reviewer - is not "
              "gateable and is not claimed here.\n")
    return 0


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    keep = "--keep" in argv
    root = tempfile.mkdtemp(prefix="audit-git-fixture-")
    try:
        fx = build_fixture(root)
        if fx.get("problem"):
            result = {"problem": fx["problem"], "root": root, "checks": []}
        else:
            result = {"problem": None, "root": root, "checks": run_checks(fx)}
        if "--json" in argv:
            print(json.dumps(result, indent=1, sort_keys=True))
            return 1 if (result["problem"]
                         or not result["checks"]
                         or any(not r["ok"] for r in result["checks"])) else 0
        code = render(result)
        if keep:
            print("fixture kept at %s" % root)
        return code
    finally:
        if not keep:
            # F155. `root` IS a git repository with commits in it, so its loose
            # objects are read-only and `shutil.rmtree` cannot unlink them on
            # windows - with `ignore_errors=True` it would leave `.git/objects/**`
            # in the system temp and say nothing at all.
            from _suite import remove_tree   # tools/_suite.py says why here
            remove_tree(root)


# --- selftest -----------------------------------------------------------------
def _cases(check):
    # The detail is what FAILED, not what the function is for: a red case whose
    # detail is a docstring tells the reader nothing they did not already have.
    check("k1 THE LIVE CLAIM: the deterministic half of the pipeline runs against "
          "a real git repository. Every check below is about this runner; this one "
          "is about the product, and it is the reason the file exists",
          _live_run()["ok"], _live_run()["text"])

    # The runner's own fail-loud paths. Each of these is a way for this gate to
    # report nothing while looking healthy, which is the only way a gate can lie.
    text = io.StringIO()
    code = render({"problem": None, "root": "/nowhere", "checks": []}, text)
    check("k2 a run with NO checks is a FAILURE, not a clean sheet - a filter that "
          "narrowed to nothing must never be spelled the way 'nothing wrong' is: "
          "%r" % (text.getvalue().strip()[-60:],),
          code == 1 and "NOTHING RAN" in text.getvalue())

    text = io.StringIO()
    code = render({"problem": "git is not on PATH", "root": "/nowhere",
                   "checks": []}, text)
    check("k3 a fixture that could not be BUILT is reported as not checked, and "
          "fails - 'the repository could not be made' and 'the pipeline is fine' "
          "are the two answers this must never merge",
          code == 1 and "NOT CHECKED" in text.getvalue())

    # A check that raises must become one failing row, not an aborted run. Driven
    # with a fabricated check list, so the real ones are not disturbed.
    def _boom(_fx):
        raise ValueError("a probe blew up")

    def _fine(_fx):
        return True, "nothing to say"

    rows = run_checks({}, (("x1 explodes", _boom), ("x2 is fine", _fine)))
    check("k4 a check that RAISES becomes one failing row and the rest still run - "
          "a runner that stopped at the first exception would report one defect "
          "where there were four: %r" % ([(r["name"], r["ok"]) for r in rows],),
          [r["ok"] for r in rows] == [False, True]
          and "a probe blew up" in rows[0]["detail"])

    text = io.StringIO()
    code = render({"problem": None, "root": "/nowhere", "checks": rows}, text)
    check("k5 ...and the verdict names the failing check and carries its detail, "
          "rather than a count somebody has to go looking for",
          code == 1 and "x1 explodes" in text.getvalue()
          and "a probe blew up" in text.getvalue())

    # The second direction for k2/k3/k5: an all-green run must NOT print any of
    # those sentinels. Without this, a renderer that always said BROKEN would pass
    # every case above.
    text = io.StringIO()
    code = render({"problem": None, "root": "/nowhere",
                   "checks": [{"name": "x3", "ok": True, "detail": "d"}]}, text)
    check("k6 an all-green run exits 0, says the limit it does NOT cover, and "
          "carries none of the failure sentinels - the case a renderer that always "
          "failed would break: %r" % (text.getvalue().strip()[-70:],),
          code == 0 and "not gateable" in text.getvalue()
          and "BROKEN" not in text.getvalue()
          and "NOTHING RAN" not in text.getvalue())

    # The isolation, asserted rather than assumed. This is the variable that made a
    # case pass for the wrong reason on the machine that wrote it.
    env = fixture_env("/tmp/x")
    _pinned = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
               "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
               "GIT_COMMITTER_EMAIL", "HOME", "USERPROFILE")
    # The detail lists the keys THIS case pins, not everything with GIT in its
    # name: the inherited environment carries a token variable, and printing the
    # whole family into a CI log to describe four of them is a bad trade.
    check("k7 the fixture environment pins every lookup that could reach the "
          "machine's own git or session, and REMOVES the session id rather than "
          "setting it: %r" % ([k for k in _pinned if k in env],),
          env["HOME"] == "/tmp/x" and env["USERPROFILE"] == "/tmp/x"
          and env["GIT_CONFIG_GLOBAL"].startswith("/tmp/x")
          and env["GIT_CONFIG_SYSTEM"].startswith("/tmp/x")
          and env["GIT_AUTHOR_EMAIL"] == FIXTURE_EMAIL
          and "CLAUDE_CODE_SESSION_ID" not in env)

    check("k8 ...and the pinned config paths name a file the fixture never "
          "creates, which git reads as empty - pointing them at a file that "
          "exists would substitute one ambient config for another",
          not os.path.exists(fixture_env("/tmp/x")["GIT_CONFIG_GLOBAL"]))

    check("k9 every check in the table has a distinct id and a callable, so the "
          "table cannot silently lose one to a copied line",
          len(set(n.split()[0] for n, _f in CHECKS)) == len(CHECKS)
          and all(callable(f) for _n, f in CHECKS))

    check("k10 every command this drives resolves to a file that exists - a "
          "renamed script would otherwise fail every check at once and name none "
          "of them",
          all(_resolve_script(n) is not None
              for n in ("resolve-branch.py", "repair-commits.py",
                        "audit-journal.py", "verify-invariants.py"))
          and os.path.isfile(LAUNCHER))

    # The Windows spelling is built from a literal backslash, NOT from `os.sep`,
    # so this case asks the same question on both platforms. The second half is
    # the reason the first one matters: it reads the separator out of `hooks.json`
    # instead of restating it, so the tool keeps driving the launcher the way the
    # product does even if that command line is ever rewritten.
    _bs = chr(92)
    _win = "C:" + _bs + "plug" + _bs + "hooks" + _bs + "py-launch.sh"
    _hooks_json = io.open(os.path.join(HOOKS_DIR, "hooks.json"),
                          encoding="utf-8").read()
    check("k12 the launcher is handed to `sh` spelled the way `hooks.json` "
          "spells it - `py-launch.sh` splits $0 on \"/\" to find its own "
          "directory, so a native Windows path sends it looking for every hook "
          "in the CALLER's directory and every guard exits without deciding: %r"
          % (_sh_arg(_win),),
          _sh_arg(_win) == "C:/plug/hooks/py-launch.sh"
          and _bs not in _sh_arg(_win)
          and "/hooks/py-launch.sh" in _hooks_json
          and LAUNCHER.endswith("/hooks/py-launch.sh"))

    check("k11 a hook's silence and a hook's decision are told apart, and so is "
          "output that is not JSON at all - a guard printing a traceback must not "
          "read as a guard that allowed the call",
          decision_of("") == (None, None)
          and decision_of("Traceback (most recent call last):") == (None, None)
          and decision_of(json.dumps({"hookSpecificOutput": {
              "permissionDecision": "deny",
              "permissionDecisionReason": "because"}})) == ("deny", "because"))


# THE LIVE RUN, memoised. Every case above is about the runner and costs nothing;
# k1 builds a real repository and drives the whole pipeline through it, and calling
# it twice would double the wall clock of this suite for one label.
_LIVE = {}


def _live_run():
    """{"ok": bool, "text": str} - the whole gate, run once, against a real repo."""
    if not _LIVE:
        root = tempfile.mkdtemp(prefix="audit-git-fixture-selftest-")
        try:
            fx = build_fixture(root)
            if fx.get("problem"):
                _LIVE.update({"ok": False, "text": fx["problem"]})
            else:
                rows = run_checks(fx)
                bad = [(r["name"], r["detail"]) for r in rows if not r["ok"]]
                _LIVE.update({"ok": not bad and bool(rows), "text": repr(bad)})
        finally:
            # F155, AND THIS IS THE SITE THAT WAS LIVE RATHER THAN THEORETICAL:
            # the windows leg of CI runs the whole sweep, the sweep runs this
            # file's `--selftest` with the temp roots pinned at a scratch
            # directory, and it refuses a file that left anything in it. A
            # repository removed by a call that cannot unlink a read-only object
            # is exactly that debris.
            from _suite import remove_tree   # tools/_suite.py says why here
            remove_tree(root)
    return _LIVE


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    _output.safe_stdio()
    args = sys.argv[1:]
    for _a in args:
        if _a not in ("--selftest", "--json", "--keep", "-h", "--help"):
            sys.stderr.write("usage: check-git-pipeline.py [--json | --keep | "
                             "--selftest]\n")
            raise SystemExit(2)
    if "--selftest" in args:
        raise SystemExit(_selftest())
    raise SystemExit(main(args))
