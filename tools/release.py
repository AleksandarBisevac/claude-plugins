#!/usr/bin/env python3
"""Cut a release end to end, stopping at the first red step and resuming from it.

WHY THIS EXISTS. `CONTRIBUTING.md` and `tools/verify.sh --release`'s `#R` block
already name every step a release needs, in the order it needs them, but typing
them by hand is how a release goes out with a step skipped or run twice (the
screenshots-before-the-bump mistake `verify.sh` itself records). This runs the
whole sequence, writing each finished step into a state file so a run that dies
partway - a real CI failure, a laptop closing - RESUMES at the step that failed
rather than redoing the bump or re-pushing a branch that already went up.

THE STEPS, IN ORDER, each skipped on a later run once its state file entry
reads "done":

  preflight            the open-bug / provisional-phase question
                        `release_permitted` asks - built only from this
                        repository's own release-guard hook's predicates
                        (under `.claude/hooks/`), read rather than restated -
                        plus the tag being free, BEFORE any file is touched
  bump-version          plugins/audit/.claude-plugin/plugin.json
  finalize-changelog    CHANGELOG.md's `## [Unreleased]` becomes the version
  followers             `tools/verify.sh --release`'s `#R` list, in its order:
                        README pins, the pinned examples under docs/examples/
                        (the set `tools/check-example-pins.py` reads), the
                        rendered example (+ docs/index.html), the scale demo,
                        the screenshots
  commit                the release commit
  verify-release        `sh tools/verify.sh --release`, AFTER the commit:
                        its last arm asks whether HEAD carries the pages
                        the followers re-rendered, which is red for as long
                        as one is uncommitted - so before the commit it
                        could never pass. A red here leaves a local commit
                        only; amend it and resume, nothing has gone out
  push-ci-branch        push `ci/v<version>`, dispatch `ci.yml` on it with
                        `-f tier=release` (the per-run jobs plus the Windows
                        re-sample), and
                        record the commit pushed (HEAD at that moment) -
                        the push creates no local `ci/...` branch, so that
                        bare name resolves to nothing afterwards
  wait-ci               wait for THAT exact commit's run to complete
  tag                   the annotated `v<version>` tag
  push-main-tag         push `main`, then the tag
  gh-release            `gh release create` with the CHANGELOG section
  check-published       `tools/check-release-published.py`

NOTHING IS PUSHED WITHOUT AN EXPLICIT `--push`, which is `CLAUDE.md`'s own
rule restated as code: permission to commit is not permission to push. Every
remote step is recorded "skipped" - never "done" - when `--push` was not
given, and nothing is run for it. A skipped step is still pending: a later
run WITH `--push` over the same state file runs it, so the documented
prepare-then-publish sequence publishes on its second run instead of finding
every remote step already "done" and printing a success over nothing. A run
that skipped any remote step ends saying it published nothing, not COMPLETE.

EVERY REMOTE STEP IS NAMED BEFORE IT RUNS: the step's own name is printed as
it starts, so a run watched live names what is about to touch a remote before
it does.

A CANCELLED CI RUN IS NOT A FAILED ONE. `wait-ci` reads the run's
`conclusion` rather than treating "not success" as one undifferentiated red,
and says which it saw.

THE OPEN-BUG / HELD-PHASE QUESTION IS ASKED AGAIN BEFORE EVERY STEP THAT
TOUCHES A REMOTE - `push-ci-branch`, `tag`, `push-main-tag`, `gh-release` -
not only at `preflight`. Time passes between the two (a CI wait can run for
an hour), and a bug filed in that gap must stop the next push rather than
let a preflight answer from before the bug existed keep authorising one.
`release_permitted` is what each of those calls, and `#release-with-bugs`
governs it exactly as it governs the hook: an armed, unexpired bypass slot
for the running session (`CLAUDE_CODE_SESSION_ID`) lets it through, read
rather than restated from the hook's own `bypass_armed`.

`release.py ci <ref>` runs the CI step ALONE: a landed phase that wants CI
run the same way this release's `wait-ci` step runs it does not need a
version or a release in flight to ask for it. It dispatches with no input,
so the workflow's default - the per-run tier - is what runs.

Exit codes: 0 the whole pipeline (or the lone `ci` step) went green -
1 a step failed, named, with the resume command printed - 2 usage error.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)

PLUGIN_JSON_REL = os.path.join("plugins", "audit", ".claude-plugin",
                                "plugin.json")
CHANGELOG_REL = "CHANGELOG.md"
README_REL = os.path.join("plugins", "audit", "README.md")
DEFAULT_STATE_REL = os.path.join(".claude", "state", "release-run.json")

STEPS = ("preflight", "bump-version", "finalize-changelog", "followers",
         "commit", "verify-release", "push-ci-branch", "wait-ci", "tag",
         "push-main-tag", "gh-release", "check-published")
# The steps that touch a remote at all, and so are recorded "skipped" (nothing
# run, still pending for a later `--push` run) when `--push` was not given.
REMOTE_STEPS = ("push-ci-branch", "wait-ci", "push-main-tag", "gh-release",
                "check-published")

USAGE = ("usage: release.py run --version X.Y.Z [--push] [--state PATH]\n"
         "       release.py ci <ref>\n"
         "       release.py --selftest\n")

DEFAULT_CI_TIMEOUT = 60 * 60
DEFAULT_POLL_INTERVAL = 15


# --- loading the files this script reads rather than restates -----------------
def _load_module(name, path):
    """A module loaded by file path - the same pattern `tools/sweep-selftests.py`
    uses to drive `tests/_harness.py` without putting it on
    `sys.path` for every caller."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_guard_release(repo=None):
    """This repository's own release-guard hook, loaded by path.

    THE PREFLIGHT STEP IMPORTS THIS RATHER THAN RESTATING ITS RULE, for the
    reason that hook's own docstring gives about its vocabulary: a second
    reading of "what holds a release" invented here could disagree with the
    first the day either one changed.
    """
    repo = repo or REPO
    path = os.path.join(repo, ".claude", "hooks", "guard-release.py")
    return _load_module("release_guard_release", path)


def release_permitted(ctx):
    """`(True, None)` once the plan carries no open bug and no held phase, or
    a bypass was armed for the running session; `(False, refusal)` otherwise.

    Built ONLY from the guard hook's own functions, loaded by path - `read_bugs`,
    `read_held_phases`, `bypass_armed` and `refusal` - never a second copy of the
    rule here. Asked at `preflight` and again immediately before every step that
    touches a remote: time passes between the two (a CI wait can run for an
    hour), and a bug filed in that gap must stop the next push rather than let
    a preflight answer from before the bug existed keep authorising one.

    The session the bypass is armed for is read from `CLAUDE_CODE_SESSION_ID` -
    absent, no bypass is possible, matching the guard hook's own single-session
    scope for the slot.
    """
    gr = load_guard_release()
    bugs, bug_problem = gr.read_bugs(ctx.repo)
    held, phase_problem = gr.read_held_phases(ctx.repo)
    if bug_problem or phase_problem:
        return False, ("could not read the release status: %s"
                       % ("; ".join(p for p in (bug_problem, phase_problem) if p)))
    if not (bugs or held):
        return True, None
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if gr.bypass_armed(ctx.repo, session_id):
        return True, None
    return False, gr.refusal("cuts a release", bugs, bug_problem, held,
                             phase_problem)


def load_rendered_artifacts(repo=None):
    """`tools/check-rendered-artifacts.py`, loaded by path - the one place the
    scale-demo and example refresh commands are written down (`refresh_for`,
    `demo_refresh_command`), so this file does not keep a second copy that
    could name different flags."""
    repo = repo or REPO
    path = os.path.join(repo, "tools", "check-rendered-artifacts.py")
    return _load_module("release_rendered_artifacts", path)


def load_example_pins(repo=None):
    """`tools/check-example-pins.py`, loaded by path: the reader that decides
    which examples pin a tag. `step_followers` repins and `step_commit` stages
    what its `pinned_examples` names, so a pinned example added under
    `docs/examples/` is followed with no edit here and the two steps cannot
    disagree with the check that fails the release over a stale pin."""
    repo = repo or REPO
    path = os.path.join(repo, "tools", "check-example-pins.py")
    return _load_module("release_example_pins", path)


def excerpt(text, limit=600):
    """A failing command's output, short enough for one line of a refusal."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + (" [... %d more chars ...]" % (len(text) - limit,))


# --- the state file -------------------------------------------------------------
def default_state_path(repo):
    return os.path.join(repo, DEFAULT_STATE_REL)


def load_state(path):
    try:
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"steps": {}}
    if not isinstance(data, dict):
        return {"steps": {}}
    data.setdefault("steps", {})
    return data


def save_state(path, state):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(state, indent=2, sort_keys=True))
        fh.write("\n")


def step_done(state, name):
    return (state.get("steps", {}).get(name) or {}).get("status") == "done"


def mark(state, name, status, detail):
    state.setdefault("steps", {})[name] = {
        "status": status, "detail": str(detail),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


# --- running a command, through one seam a test can replace --------------------
def default_runner(args, cwd=None):
    """`(returncode, combined output)` - a real subprocess. `args` a list runs
    directly; a string runs through the shell, which is what a multi-line
    recipe (`demo_refresh_command()`) needs."""
    try:
        proc = subprocess.run(args, cwd=cwd, shell=isinstance(args, str),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        return 1, "could not run %r: %s" % (args, exc)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


class Context(object):
    """Everything a step needs, including the one seam the selftest replaces:
    `runner`. `state` is the whole state dict; a step reads and writes it
    directly (`ctx.state["oldVersion"]`) rather than through a second object,
    because the state file IS the one place a step's own history is kept."""

    def __init__(self, repo, version, push, runner=None, state=None,
                 state_path=None, ci_timeout=None, poll_interval=None):
        self.repo = repo
        self.version = version
        self.push = push
        self.runner = runner or default_runner
        self.state = state if state is not None else {"steps": {}}
        self.state_path = state_path or default_state_path(repo)
        self.ci_timeout = ci_timeout if ci_timeout is not None else DEFAULT_CI_TIMEOUT
        self.poll_interval = (poll_interval if poll_interval is not None
                              else DEFAULT_POLL_INTERVAL)

    def run(self, args, cwd=None):
        return self.runner(args, cwd=cwd or self.repo)

    def path(self, rel):
        return os.path.join(self.repo, rel)


# --- the steps ------------------------------------------------------------------
def step_preflight(ctx):
    """Refuses before a single file is written: the open-bug / provisional-
    phase question `release_permitted` asks, and that the tag is free.
    Captures the PRE-BUMP version into the state, because `followers` needs
    it after `bump-version` has already overwritten `plugin.json` on a later
    run."""
    allowed, refusal = release_permitted(ctx)
    if not allowed:
        return False, refusal
    rc, out = ctx.run(["git", "rev-parse", "v%s" % (ctx.version,)])
    if rc == 0:
        return False, ("tag v%s already exists - a pushed tag is never moved "
                       "here" % (ctx.version,))
    with io.open(os.path.join(ctx.repo, PLUGIN_JSON_REL),
                encoding="utf-8") as fh:
        ctx.state["oldVersion"] = json.load(fh).get("version")
    return True, "no open bug, no held phase, tag v%s is free" % (ctx.version,)


def step_bump_version(ctx):
    path = os.path.join(ctx.repo, PLUGIN_JSON_REL)
    with io.open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["version"] = ctx.version
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, indent=2))
        fh.write("\n")
    return True, "plugin.json version set to %s" % (ctx.version,)


def changelog_section(repo, version):
    """The `## [version]` section's text, or None when there is no such
    heading."""
    path = os.path.join(repo, CHANGELOG_REL)
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    marker = "## [%s]" % (version,)
    index = text.find(marker)
    if index < 0:
        return None
    rest = text[index:]
    nxt = rest.find("\n## [", 1)
    section = rest if nxt < 0 else rest[:nxt]
    return section.strip() + "\n"


def step_finalize_changelog(ctx):
    if changelog_section(ctx.repo, ctx.version) is not None:
        return True, "CHANGELOG.md already carries ## [%s]" % (ctx.version,)
    path = os.path.join(ctx.repo, CHANGELOG_REL)
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    marker = "## [Unreleased]"
    if marker not in text:
        return False, ("CHANGELOG.md has neither a ## [%s] section nor a "
                       "## [Unreleased] one to finalize" % (ctx.version,))
    text = text.replace(marker, "## [%s]" % (ctx.version,), 1)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return True, "## [Unreleased] renamed to ## [%s]" % (ctx.version,)


def _rewrite_readme_pins(ctx):
    old_version = ctx.state.get("oldVersion")
    if not old_version:
        return True, "no prior version recorded - nothing to rewrite"
    path = os.path.join(ctx.repo, README_REL)
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    old_pin = "claude-plugins/v%s/" % (old_version,)
    new_pin = "claude-plugins/v%s/" % (ctx.version,)
    if old_pin not in text:
        return True, "README carries no v%s pin to rewrite" % (old_version,)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text.replace(old_pin, new_pin))
    return True, "README pins rewritten %s -> %s" % (old_pin, new_pin)


def step_followers(ctx):
    """`tools/verify.sh --release`'s `#R` list, in its order. Each recipe is
    READ off `check-rendered-artifacts.py` rather than kept a second time here
    - that is the file the gate itself derives from, so a flag change there
    cannot leave this script producing bytes the gate then rejects."""
    notes = []
    ok, note = _rewrite_readme_pins(ctx)
    if not ok:
        return False, note
    notes.append(note)

    repinned = load_example_pins().repin_examples(ctx.repo,
                                                  "v%s" % (ctx.version,))
    notes.append("example pins repinned to v%s: %s"
                 % (ctx.version, ", ".join(repinned) or "none needed"))

    crt = load_rendered_artifacts()
    for rel in ("examples/acme-store/acme-store-audit.html",
                "examples/acme-store/acme-store-audit.md"):
        recipe = crt.refresh_for(rel)
        rc, out = ctx.run(recipe)
        if rc != 0:
            return False, "refreshing %s failed: %s" % (rel, excerpt(out))
    notes.append("examples/report.sh regenerated the example report")

    rc, out = ctx.run("cp examples/acme-store/acme-store-audit.html "
                      "docs/index.html")
    if rc != 0:
        return False, "docs/index.html copy failed: %s" % (excerpt(out),)
    notes.append("docs/index.html copied")

    recipe = crt.refresh_for("docs/demo-large.html")
    rc, out = ctx.run(recipe)
    if rc != 0:
        return False, "docs/demo-large.html refresh failed: %s" % (excerpt(out),)
    notes.append("docs/demo-large.html regenerated")

    rc, out = ctx.run(["node", "tools/capture-screenshots.mjs"])
    if rc != 0:
        return False, "capture-screenshots.mjs failed: %s" % (excerpt(out),)
    notes.append("screenshots recaptured")
    return True, "; ".join(notes)


def step_verify_release(ctx):
    rc, out = ctx.run(["sh", "tools/verify.sh", "--release"])
    if rc != 0:
        return False, "tools/verify.sh --release failed: %s" % (excerpt(out),)
    return True, "tools/verify.sh --release is green"


def step_commit(ctx):
    paths = [PLUGIN_JSON_REL, CHANGELOG_REL, README_REL,
             "examples/acme-store/acme-store-audit.html",
             "examples/acme-store/acme-store-audit.md",
             "docs/index.html", "docs/demo-large.html",
             "docs/screenshots"]
    paths += load_example_pins().pinned_examples(ctx.repo)
    rc, out = ctx.run(["git", "add"] + paths)
    if rc != 0:
        return False, "git add failed: %s" % (excerpt(out),)
    rc, out = ctx.run(["git", "commit", "-m", "release: v%s" % (ctx.version,)])
    if rc != 0:
        return False, "git commit failed: %s" % (excerpt(out),)
    return True, "committed release v%s" % (ctx.version,)


def _skip_remote(name, ctx):
    return name in REMOTE_STEPS and not ctx.push


def _ci_branch(version):
    return "ci/v%s" % (version,)


def dispatch_ci(ctx, ref, tier=None):
    """Dispatch ci.yml on `ref`. With no `tier` the workflow's own default runs,
    which is the per-run tier; a release candidate passes `tier="release"`, which
    adds the Windows re-sample job to every per-run job."""
    argv = ["gh", "workflow", "run", "ci.yml", "--ref", ref]
    if tier is not None:
        argv += ["-f", "tier=%s" % (tier,)]
    rc, out = ctx.run(argv)
    if rc != 0:
        return False, "%s failed: %s" % (" ".join(argv), excerpt(out))
    return True, "dispatched ci.yml on %s%s" % (
        ref, "" if tier is None else " (tier %s)" % (tier,))


def wait_ci(ctx, ref, sha=None):
    """Waits for the run matching `ref`'s EXACT commit to complete, and reads
    `conclusion` rather than reducing every non-success to one failure - a
    cancelled run is named as cancelled, not reported as if it had failed.

    `sha` is the commit when the caller already knows it - the release's own
    push records it - and `ref` is resolved locally only when it is not
    given, which is right for `ci <ref>` on a local branch."""
    if sha is None:
        rc, out = ctx.run(["git", "rev-parse", ref])
        if rc != 0:
            return False, "could not resolve %s to a commit: %s" % (
                ref, excerpt(out))
        sha = out.strip()
    deadline = time.time() + ctx.ci_timeout
    while True:
        rc, out = ctx.run(["gh", "run", "list", "--branch", ref,
                           "--workflow", "ci.yml", "--limit", "10",
                           "--json", "databaseId,headSha,status,conclusion"])
        if rc != 0:
            return False, "gh run list failed: %s" % (excerpt(out),)
        try:
            runs = json.loads(out or "[]")
        except ValueError:
            return False, "gh run list did not print JSON: %s" % (excerpt(out),)
        matching = [row for row in runs if row.get("headSha") == sha]
        if matching:
            found = matching[0]
            if found.get("status") == "completed":
                conclusion = found.get("conclusion")
                run_id = found.get("databaseId")
                if conclusion == "success":
                    return True, "ci.yml run %s on %s succeeded" % (run_id, sha)
                if conclusion == "cancelled":
                    return False, ("ci.yml run %s on %s was CANCELLED, not "
                                  "failed - re-dispatch and resume" % (run_id, sha))
                return False, ("ci.yml run %s on %s FAILED (conclusion: %s)"
                              % (run_id, sha, conclusion))
        if time.time() >= deadline:
            return False, ("no completed ci.yml run for %s appeared within "
                           "%ss" % (sha, ctx.ci_timeout))
        time.sleep(ctx.poll_interval)


def step_push_ci_branch(ctx):
    """Records the commit it pushes, read from HEAD BEFORE the push: the push
    names a remote ref only, so no local `ci/...` branch exists afterwards
    for `wait-ci` to resolve."""
    allowed, refusal = release_permitted(ctx)
    if not allowed:
        return False, refusal
    branch = _ci_branch(ctx.version)
    rc, out = ctx.run(["git", "rev-parse", "HEAD"])
    if rc != 0 or not out.strip():
        return False, "could not read HEAD before the push: %s" % (excerpt(out),)
    sha = out.strip()
    rc, out = ctx.run(["git", "push", "origin",
                       "HEAD:refs/heads/%s" % (branch,)])
    if rc != 0:
        return False, "push to %s failed: %s" % (branch, excerpt(out))
    ctx.state["ciBranch"] = branch
    ctx.state["ciSha"] = sha
    ok, detail = dispatch_ci(ctx, branch, tier="release")
    if not ok:
        return False, detail
    return True, "pushed %s (%s) and %s" % (branch, sha, detail)


def step_wait_ci(ctx):
    """Waits on the commit `push-ci-branch` recorded. A state file written
    before that was recorded falls back to the remote-tracking ref the push
    left, never the bare branch name."""
    branch = ctx.state.get("ciBranch") or _ci_branch(ctx.version)
    sha = ctx.state.get("ciSha")
    if not sha:
        rc, out = ctx.run(["git", "rev-parse", "origin/%s" % (branch,)])
        if rc != 0 or not out.strip():
            return False, ("no pushed commit is recorded and origin/%s does "
                           "not resolve: %s" % (branch, excerpt(out)))
        sha = out.strip()
    return wait_ci(ctx, branch, sha=sha)


def step_tag(ctx):
    allowed, refusal = release_permitted(ctx)
    if not allowed:
        return False, refusal
    message = changelog_section(ctx.repo, ctx.version) or (
        "release v%s" % (ctx.version,))
    rc, out = ctx.run(["git", "tag", "-a", "v%s" % (ctx.version,),
                       "-m", message])
    if rc != 0:
        return False, "git tag failed: %s" % (excerpt(out),)
    return True, "tagged v%s" % (ctx.version,)


def step_push_main_tag(ctx):
    allowed, refusal = release_permitted(ctx)
    if not allowed:
        return False, refusal
    rc, out = ctx.run(["git", "push", "origin", "main"])
    if rc != 0:
        return False, "push main failed: %s" % (excerpt(out),)
    rc, out = ctx.run(["git", "push", "origin", "v%s" % (ctx.version,)])
    if rc != 0:
        return False, "push v%s failed: %s" % (ctx.version, excerpt(out))
    return True, "pushed main and v%s" % (ctx.version,)


def step_gh_release(ctx):
    allowed, refusal = release_permitted(ctx)
    if not allowed:
        return False, refusal
    notes = changelog_section(ctx.repo, ctx.version) or ""
    fd, notes_path = tempfile.mkstemp(prefix="release-notes-", suffix=".md")
    try:
        with io.open(fd, "w", encoding="utf-8") as fh:
            fh.write(notes)
        rc, out = ctx.run(["gh", "release", "create", "v%s" % (ctx.version,),
                           "--title", "v%s" % (ctx.version,),
                           "--notes-file", notes_path])
    finally:
        try:
            os.remove(notes_path)
        except OSError:
            pass
    if rc != 0:
        return False, "gh release create failed: %s" % (excerpt(out),)
    return True, "created the GitHub Release for v%s" % (ctx.version,)


def step_check_published(ctx):
    rc, out = ctx.run(["python3", "tools/check-release-published.py"])
    if rc != 0:
        return False, "check-release-published.py: %s" % (excerpt(out),)
    return True, excerpt(out)


STEP_FUNCS = {
    "preflight": step_preflight,
    "bump-version": step_bump_version,
    "finalize-changelog": step_finalize_changelog,
    "followers": step_followers,
    "verify-release": step_verify_release,
    "commit": step_commit,
    "push-ci-branch": step_push_ci_branch,
    "wait-ci": step_wait_ci,
    "tag": step_tag,
    "push-main-tag": step_push_main_tag,
    "gh-release": step_gh_release,
    "check-published": step_check_published,
}


def resume_command(ctx):
    words = ["python3", "tools/release.py", "run", "--version", ctx.version,
             "--state", ctx.state_path]
    if ctx.push:
        words.append("--push")
    return " ".join(words)


def run_pipeline(ctx, out=None):
    """Runs every step not already `done` in `ctx.state`, in order. Returns
    `(exit_code, last_detail)`. Writes `ctx.state` to `ctx.state_path` after
    EVERY step, so a process killed mid-pipeline leaves a state file that
    names exactly what finished.

    The one place a remote step is skipped without `--push`: recorded
    `skipped`, which `step_done` does not count, so the same step runs on a
    later `--push` run over this state file."""
    out = out if out is not None else sys.stdout
    ctx.state.setdefault("version", ctx.version)
    if ctx.state.get("version") != ctx.version:
        detail = ("the state file at %s already tracks a release for %s, not "
                  "%s - use --state to start a fresh one, or finish that "
                  "release first" % (ctx.state_path, ctx.state.get("version"),
                                     ctx.version))
        out.write(detail + "\n")
        return 2, detail
    skipped = []
    for name in STEPS:
        if step_done(ctx.state, name):
            out.write("== %-16s skipped (already done)\n" % (name,))
            continue
        if _skip_remote(name, ctx):
            mark(ctx.state, name, "skipped", "no --push given; nothing run")
            save_state(ctx.state_path, ctx.state)
            out.write("== %-16s skipped (no --push given)\n" % (name,))
            skipped.append(name)
            continue
        out.write("-> %s\n" % (name,))
        func = STEP_FUNCS[name]
        try:
            ok, detail = func(ctx)
        except Exception as exc:                                  # noqa: BLE001
            ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
        mark(ctx.state, name, "done" if ok else "failed", detail)
        save_state(ctx.state_path, ctx.state)
        if not ok:
            out.write("\nRELEASE STOPPED at %r:\n  %s\n\n" % (name, detail))
            out.write("Resume with:\n  %s\n" % (resume_command(ctx),))
            return 1, detail
        out.write("   ok: %s\n" % (detail,))
    if skipped:
        detail = ("release v%s prepared locally and nothing was published: "
                  "%s skipped (no --push given)" % (ctx.version,
                                                    ", ".join(skipped)))
        out.write("\n%s.\nPublish with:\n  %s --push\n"
                  % (detail, resume_command(ctx)))
        return 0, detail
    out.write("\nRELEASE v%s COMPLETE.\n" % (ctx.version,))
    return 0, "complete"


# --- command line ----------------------------------------------------------------
def parse_run_argv(argv):
    """`{"push", "version", "state"}` or None on a bad argument list."""
    push = False
    version = None
    state = None
    i = 0
    while i < len(argv):
        word = argv[i]
        if word == "--push":
            push = True
        elif word == "--version":
            i += 1
            if i >= len(argv):
                return None
            version = argv[i]
        elif word == "--state":
            i += 1
            if i >= len(argv):
                return None
            state = argv[i]
        else:
            return None
        i += 1
    return {"push": push, "version": version, "state": state}


def cmd_run(argv, repo=None, runner=None, out=None):
    repo = repo or REPO
    parsed = parse_run_argv(argv)
    if parsed is None:
        sys.stderr.write(USAGE)
        return 2
    state_path = parsed["state"] or default_state_path(repo)
    state = load_state(state_path)
    version = parsed["version"] or state.get("version")
    if not version:
        sys.stderr.write("release.py: --version is required for a first "
                         "run (none is recorded at %s)\n" % (state_path,))
        return 2
    ctx = Context(repo, version, parsed["push"], runner=runner, state=state,
                 state_path=state_path)
    code, _detail = run_pipeline(ctx, out=out)
    return 0 if code == 0 else 1


def cmd_ci(argv, repo=None, runner=None, out=None):
    repo = repo or REPO
    out = out if out is not None else sys.stdout
    if len(argv) != 1:
        sys.stderr.write(USAGE)
        return 2
    ref = argv[0]
    ctx = Context(repo, version=None, push=True, runner=runner)
    ok, detail = dispatch_ci(ctx, ref)
    if ok:
        out.write(detail + "\n")
        ok, detail = wait_ci(ctx, ref)
    out.write(detail + "\n")
    return 0 if ok else 1


def route_subcommand(argv):
    """`(subcommand, rest)` - `run` is implicit, so `release.py --push` reads
    exactly as `release.py run --push` does. Both forms run the same `cmd_run`,
    which asks `release_permitted` the same question regardless of which
    spelling a reader typed."""
    if argv and argv[0] in ("run", "ci"):
        return argv[0], argv[1:]
    return "run", argv


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return _selftest()
    sub, rest = route_subcommand(argv)
    if sub == "ci":
        return cmd_ci(rest)
    return cmd_run(rest)


# --- selftest ---------------------------------------------------------------
class FakeRunner(object):
    """A scripted `runner`: `responses` is `[(predicate, (rc, out)), ...]`,
    checked in order against the command rendered as one string, so a case
    can fail exactly one step by matching a substring of it. A result may be
    a callable taking that string, for an answer that depends on what ran
    before it (`_faithful_responses`). Records every call so a case can
    assert what did, or did not, run."""

    def __init__(self, responses=None, default=(0, ""), call_limit=200):
        self.calls = []
        self.call_limit = call_limit
        self.responses = list(responses or [])
        self.default = default

    def __call__(self, args, cwd=None):
        text = args if isinstance(args, str) else " ".join(str(a) for a in args)
        self.calls.append(text)
        if len(self.calls) > self.call_limit:
            # A loop that polls (`wait_ci`) ends here instead of at its
            # timeout, and the recorded list stays small enough to print.
            return 1, "fake runner: more than %d calls" % (self.call_limit,)
        for predicate, result in self.responses:
            if predicate(text):
                return result(text) if callable(result) else result
        return self.default


def _new_world():
    """What a faithful fake remembers across runners - one release attempt
    and its resume share it, because the repository and the remote outlive
    the process that touched them."""
    return {"head": "0ldhead0", "committed": False, "tagged": False,
            "pushedSha": None}


def _faithful_responses(world, version="9.9.9"):
    """The answers git, `verify.sh` and `gh` actually give, as the steps reach
    them, so a case cannot pass on an order or a ref the real tools refuse.

    - `git push origin HEAD:refs/heads/ci/v...` creates NO local branch, so
      `git rev-parse ci/v...` fails exactly as it does in a real clone after
      that push; only `origin/ci/v...` resolves, and only once pushed.
    - `verify.sh --release` ends by asking whether HEAD carries the pages the
      followers re-rendered, so it is red until a commit has been recorded.
    - `gh run list` reports a green run for the commit that was pushed."""
    sha = "c0mm1tted"
    tag = "v%s" % (version,)
    branch = "ci/v%s" % (version,)

    def commit(_text):
        world["committed"] = True
        world["head"] = sha
        return 0, "[main %s] release: %s" % (sha, tag)

    def tag_it(_text):
        world["tagged"] = True
        return 0, ""

    def rev_parse_tag(_text):
        if world["tagged"]:
            return 0, "7a9000\n"
        return 128, "fatal: ambiguous argument '%s': unknown revision" % (tag,)

    def rev_parse_remote(_text):
        if world["pushedSha"]:
            return 0, world["pushedSha"] + "\n"
        return 128, "fatal: ambiguous argument 'origin/%s'" % (branch,)

    def push_ci(_text):
        world["pushedSha"] = world["head"]
        return 0, ""

    def verify(_text):
        if world["committed"]:
            return 0, "verify: every gate green"
        return 1, ("FAIL HEAD carries the published pages: a re-rendered "
                   "page is uncommitted")

    def run_list(_text):
        if not world["pushedSha"]:
            return 0, "[]"
        return 0, json.dumps([{"headSha": world["pushedSha"],
                               "status": "completed", "conclusion": "success",
                               "databaseId": 7}])

    return [
        (lambda c: c == "git rev-parse %s" % (tag,), rev_parse_tag),
        (lambda c: c.startswith("git rev-parse ci/"),
         (128, "fatal: ambiguous argument '%s': unknown revision" % (branch,))),
        (lambda c: c.startswith("git rev-parse origin/ci/"), rev_parse_remote),
        (lambda c: c == "git rev-parse HEAD",
         lambda _t: (0, world["head"] + "\n")),
        (lambda c: c.startswith("git commit"), commit),
        (lambda c: c.startswith("git tag -a"), tag_it),
        (lambda c: c.startswith("git push origin HEAD:refs/heads/ci/"),
         push_ci),
        (lambda c: c == "sh tools/verify.sh --release", verify),
        (lambda c: c.startswith("gh run list"), run_list),
    ]


def _call_list(runner):
    """Every case that prints a fake runner's call list prints it clipped."""
    return excerpt(repr(runner.calls))


_TIER_CLAUSE = ("the release dispatch passes -f tier=release, and a dispatch "
                "with no input runs the per-run tier")


def _workflow_tier_input(text):
    """`{"default", "options"}` of the `tier` input under `workflow_dispatch:`,
    or None when the workflow declares no such input. Read by indentation, the
    way GitHub nests it: `workflow_dispatch:` > `inputs:` > `tier:` > its keys,
    with `options:` as a block list one level under its key."""
    lines = text.splitlines()
    path = ("workflow_dispatch", "inputs", "tier")
    depth = []                       # indents of the path keys matched so far
    found = None
    keys = {}
    options = []
    in_options = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if found is not None:
            if indent <= found:
                break
            if in_options is not None and indent > in_options \
                    and stripped.startswith("- "):
                options.append(stripped[2:].strip().strip("'\""))
                continue
            in_options = None
            key, _sep, value = stripped.partition(":")
            if key == "options" and not value.strip():
                in_options = indent
            else:
                keys[key] = value.strip().strip("'\"")
            continue
        while depth and indent <= depth[-1]:
            depth.pop()
        if len(depth) < len(path) and stripped == path[len(depth)] + ":":
            depth.append(indent)
            if len(depth) == len(path):
                found = indent
    if found is None:
        return None
    return {"default": keys.get("default"), "options": options}


def _fixture_repo(bugs=None):
    """A scratch tree carrying just what the steps under test read: the plan
    (for `preflight`), `plugin.json` (for `bump-version`), `CHANGELOG.md` and
    the README. Never touches the real repository and is removed by the
    caller."""
    root = tempfile.mkdtemp(prefix="release-fixture-")
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, os.path.dirname(PLUGIN_JSON_REL)),
               exist_ok=True)
    os.makedirs(os.path.join(root, os.path.dirname(README_REL)), exist_ok=True)
    with io.open(os.path.join(root, "docs", "audit", "audit-plan.json"),
                "w", encoding="utf-8") as fh:
        json.dump({"meta": {"version": 2}, "phases": [],
                   "bugs": bugs or []}, fh)
    with io.open(os.path.join(root, PLUGIN_JSON_REL), "w",
                encoding="utf-8") as fh:
        json.dump({"name": "audit", "version": "1.0.0"}, fh)
    with io.open(os.path.join(root, CHANGELOG_REL), "w",
                encoding="utf-8") as fh:
        fh.write("# Changelog\n\n## [Unreleased]\n\n- a change\n")
    with io.open(os.path.join(root, README_REL), "w", encoding="utf-8") as fh:
        fh.write("curl -fsSL https://.../claude-plugins/v1.0.0/x.sh\n")
    return root


def _cases(check):
    from _suite import remove_tree          # tools/_suite.py says why here

    # --- a pinned example is repinned and staged with no edit to this file -----
    tmp = _fixture_repo()
    try:
        folder = os.path.join(tmp, "docs", "examples")
        os.makedirs(folder)
        pinned = {"zz-new-pipeline.yml": "run: git clone --branch v1.0.0 u s\n",
                  "zz-other.yaml": "run: curl https://x/claude-plugins/v1.0.0/a\n"}
        unpinned = {"zz-plain.yml": "# --branch v1.0.0\nrun: echo hi\n"}
        for name, body in dict(pinned, **unpinned).items():
            with io.open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                fh.write(body)
        runner = FakeRunner(default=(0, ""))
        ctx = Context(tmp, "9.9.9", push=False, runner=runner,
                     state={"steps": {}, "version": "9.9.9"},
                     state_path=os.path.join(tmp, "state.json"))
        ok_f, detail_f = step_followers(ctx)
        ok_c, detail_c = step_commit(ctx)
        texts = {n: io.open(os.path.join(folder, n), encoding="utf-8").read()
                 for n in list(pinned) + list(unpinned)}
        adds = [c for c in runner.calls if c.startswith("git add")]
        staged = adds[0].split(" ") if adds else []
        check("rl16 a pinned example dropped under docs/examples/ is repinned "
              "to the release tag by the followers step and staged by the "
              "commit step, with no edit to release.py; an unpinned one is "
              "neither: %r / %r / %r" % (detail_f, texts, adds),
              ok_f and ok_c and len(adds) == 1
              and all("v9.9.9" in texts[n] and "v1.0.0" not in texts[n]
                      for n in pinned)
              and texts["zz-plain.yml"] == unpinned["zz-plain.yml"]
              and all("docs/examples/%s" % n in staged for n in pinned)
              and "docs/examples/zz-plain.yml" not in staged
              and "zz-new-pipeline.yml" in detail_f)
    finally:
        remove_tree(tmp)

    # --- preflight refuses before any file is written -------------------------
    tmp = _fixture_repo(bugs=[{"id": "BUG-1", "status": "open",
                              "severity": "high", "title": "a real one"}])
    try:
        runner = FakeRunner(default=(1, "no such tag"))
        ctx = Context(tmp, "9.9.9", push=False, runner=runner,
                     state_path=os.path.join(tmp, "state.json"))
        code, detail = run_pipeline(ctx, out=io.StringIO())
        with io.open(os.path.join(tmp, PLUGIN_JSON_REL), encoding="utf-8") as fh:
            version_after = json.load(fh).get("version")
        check("rl1 with an open bug in the plan, the preflight refuses "
              "before any file is written: %r" % (detail,),
              code == 1 and "BUG-1" in detail and version_after == "1.0.0")
        check("rl1b ...and only the tag-freshness check ran - bump-version "
              "was never reached, so no write happened to miss",
              step_done(ctx.state, "preflight") is False
              and "bump-version" not in ctx.state.get("steps", {}))
    finally:
        remove_tree(tmp)

    # --- without --push, no publishing command is ever issued ------------------
    tmp = _fixture_repo()
    try:
        world = _new_world()
        state_path = os.path.join(tmp, "state.json")
        runner = FakeRunner(_faithful_responses(world))
        ctx = Context(tmp, "9.9.9", push=False, runner=runner,
                     state_path=state_path)
        printed = io.StringIO()
        code, _detail = run_pipeline(ctx, out=printed)
        publishing = [c for c in runner.calls
                     if ("git push" in c or "gh release create" in c
                         or "gh workflow run" in c)]
        check("rl2 a full run with no --push reaches the end green and "
              "issues no push, no `gh workflow run` and no `gh release "
              "create`: %s" % (_call_list(runner),),
              code == 0 and not publishing)
        statuses = [(ctx.state["steps"].get(name) or {}).get("status")
                    for name in REMOTE_STEPS]
        check("rl2b ...and every remote step is recorded `skipped`, never "
              "`done` - a `done` would let a later --push run skip it and "
              "publish nothing: %r" % (statuses,),
              statuses == ["skipped"] * len(REMOTE_STEPS))
        check("rl2d ...and the run does not claim a COMPLETE release, saying "
              "instead that nothing was published: %r"
              % (excerpt(printed.getvalue()[-300:]),),
              "COMPLETE" not in printed.getvalue()
              and "nothing was published" in printed.getvalue())

        runner2 = FakeRunner(_faithful_responses(world))
        ctx2 = Context(tmp, "9.9.9", push=True, runner=runner2,
                      state=load_state(state_path), state_path=state_path,
                      poll_interval=0, ci_timeout=2)
        printed2 = io.StringIO()
        code2, detail2 = run_pipeline(ctx2, out=printed2)
        published = [c for c in runner2.calls
                     if c.startswith("git push origin")
                     or c.startswith("gh release create")]
        check("rl2c the same state file run again WITH --push publishes - "
              "the ci branch, main, the tag and the GitHub Release are all "
              "pushed - and only then prints COMPLETE: %r / %s"
              % (detail2, _call_list(runner2)),
              code2 == 0 and "COMPLETE" in printed2.getvalue()
              and [c.split(" ")[3] if c.startswith("git push") else "release"
                   for c in published]
              == ["HEAD:refs/heads/ci/v9.9.9", "main", "v9.9.9", "release"]
              and all(step_done(ctx2.state, name) for name in REMOTE_STEPS))
        check("rl2e ...and the local steps that already ran are not run a "
              "second time by that --push run: %s" % (_call_list(runner2),),
              not any(c.startswith("git commit") or c.startswith("git tag -a")
                      or "verify.sh" in c for c in runner2.calls))
    finally:
        remove_tree(tmp)

    # --- the order and the refs a REAL run meets --------------------------------
    tmp = _fixture_repo()
    try:
        world = _new_world()
        runner = FakeRunner(_faithful_responses(world))
        ctx = Context(tmp, "9.9.9", push=True, runner=runner,
                     state_path=os.path.join(tmp, "state.json"),
                     poll_interval=0, ci_timeout=2)
        code, detail = run_pipeline(ctx, out=io.StringIO())
        commit_at = [i for i, c in enumerate(runner.calls)
                     if c.startswith("git commit")]
        verify_at = [i for i, c in enumerate(runner.calls)
                     if c == "sh tools/verify.sh --release"]
        check("rl12 `verify.sh --release` runs once, AFTER the release "
              "commit - its HEAD-carries-the-pages arm is red before one, so "
              "a full --push run over a faithful fake goes green: %r / %s"
              % (detail, _call_list(runner)),
              code == 0 and len(commit_at) == 1 and len(verify_at) == 1
              and commit_at[0] < verify_at[0])
        check("rl13 wait-ci never asks git for the bare `ci/v...` name the "
              "push does not create, and waits on the commit that was "
              "pushed: %r / %s" % (ctx.state.get("ciSha"), _call_list(runner)),
              not any(c.startswith("git rev-parse ci/") for c in runner.calls)
              and ctx.state.get("ciSha") == "c0mm1tted"
              and "c0mm1tted" in (ctx.state["steps"].get("wait-ci")
                                  or {}).get("detail", ""))
        released = [c for c in runner.calls if c.startswith("gh workflow run")]
        check("rt1 %s (the release pipeline's dispatch: %r)"
              % (_TIER_CLAUSE, released),
              released == ["gh workflow run ci.yml --ref ci/v9.9.9 "
                           "-f tier=release"])
    finally:
        remove_tree(tmp)

    # --- a phase's CI dispatch passes no input, and the workflow reads that ----
    # as the per-run tier: the drive's cadence and `release.py ci` both dispatch
    # with `--ref` alone, so the default IS what every non-release run gets.
    phase_runner = FakeRunner(_faithful_responses(_new_world()))
    cmd_ci(["ci/p999"], repo=REPO, runner=phase_runner, out=io.StringIO())
    phase_dispatch = [c for c in phase_runner.calls
                      if c.startswith("gh workflow run")]
    with io.open(os.path.join(REPO, ".github", "workflows", "ci.yml"),
                 encoding="utf-8") as fh:
        workflow = fh.read()
    tier_input = _workflow_tier_input(workflow)
    check("rt2 %s (a phase dispatch %r; the workflow's tier input %r)"
          % (_TIER_CLAUSE, phase_dispatch, tier_input),
          phase_dispatch == ["gh workflow run ci.yml --ref ci/p999"]
          and tier_input == {"default": "per-run",
                             "options": ["per-run", "release"]})
    # The second direction: a workflow defaulting to the release tier, or with
    # no tier input at all, must not read as one that runs the per-run tier.
    as_release = _workflow_tier_input(
        workflow.replace("default: per-run", "default: release"))
    no_input = _workflow_tier_input("on:\n  workflow_dispatch:\njobs:\n")
    check("rt3 %s (a workflow defaulting to release reads %r, one with no "
          "tier input reads %r)" % (_TIER_CLAUSE, as_release, no_input),
          (as_release or {}).get("default") == "release" and no_input is None)

    # --- a red at the CI step stops there, and resume starts there -------------
    tmp = _fixture_repo()
    try:
        state_path = os.path.join(tmp, "state.json")
        world = _new_world()
        red_run = (lambda c: c.startswith("gh run list"),
                   lambda _t: (0, json.dumps([{
                       "headSha": world["pushedSha"], "status": "completed",
                       "conclusion": "failure", "databaseId": 1}])))
        runner = FakeRunner([red_run] + _faithful_responses(world))
        ctx = Context(tmp, "9.9.9", push=True, runner=runner,
                     state_path=state_path, poll_interval=0, ci_timeout=2)
        code, detail = run_pipeline(ctx, out=io.StringIO())
        check("rl3 a fake run that goes red at the CI step stops there, "
              "naming the step and the conclusion: %r" % (detail,),
              code == 1 and "FAILED" in detail
              and step_done(ctx.state, "wait-ci") is False)
        check("rl3b ...and the steps before it - preflight through "
              "push-ci-branch - are recorded done, so a resume does not "
              "redo the bump",
              all(step_done(ctx.state, name) for name in
                  ("preflight", "bump-version", "finalize-changelog",
                   "followers", "verify-release", "commit",
                   "push-ci-branch")))
        check("rl3c the resume command this run prints names the version "
              "and the state file, with --push carried through",
              resume_command(ctx) == (
                  "python3 tools/release.py run --version 9.9.9 --state %s "
                  "--push" % (state_path,)))

        with io.open(os.path.join(tmp, PLUGIN_JSON_REL), encoding="utf-8") as fh:
            version_after_red = json.load(fh).get("version")
        check("rl3d bump-version actually ran on the first attempt (it is "
              "the earlier step, not the failing one): %r" % (version_after_red,),
              version_after_red == "9.9.9")

        # Resume: the CI run now succeeds.
        bumps_before_resume = len(
            [c for c in runner.calls if c.startswith("git tag")])
        resumed_state = load_state(state_path)
        runner2 = FakeRunner(_faithful_responses(world))
        ctx2 = Context(tmp, "9.9.9", push=True, runner=runner2,
                      state=resumed_state, state_path=state_path,
                      poll_interval=0, ci_timeout=2)
        code2, detail2 = run_pipeline(ctx2, out=io.StringIO())
        check("rl4 resuming starts at the CI step and finishes green: %r"
              % (detail2,), code2 == 0)
        check("rl4b ...and the earlier steps did not run again on resume - "
              "no second push of the ci branch and no second `examples/"
              "report.sh` (both already recorded done): %s"
              % (_call_list(runner2),),
              bumps_before_resume == 0
              and not any(c.startswith("git push origin HEAD:refs/heads/")
                         for c in runner2.calls)
              and not any("report.sh" in c for c in runner2.calls))
        check("rl4c ...and `gh workflow run` was not issued a second time - "
              "the already-pushed branch is not re-dispatched on resume",
              not any("gh workflow run" in c for c in runner2.calls))
    finally:
        remove_tree(tmp)

    # --- a stop at EVERY step resumes there, and only there ---------------------
    # One row per step: how to make that step (and only it) red on the first
    # run, and how to repair the fixture before the resume. The second run's
    # runner carries no fault, so what it calls is what the resume re-ran.
    signature = {
        "preflight": "git rev-parse v9.9.9",
        "followers": "capture-screenshots.mjs",
        "commit": "git commit",
        "verify-release": "sh tools/verify.sh --release",
        "push-ci-branch": "git push origin HEAD:refs/heads/",
        "wait-ci": "gh run list",
        "tag": "git tag -a",
        "push-main-tag": "git push origin main",
        "gh-release": "gh release create",
        "check-published": "check-release-published.py",
    }

    def _failing(needle, result):
        return [(lambda c: needle in c, result)]

    def _write(root, rel, text):
        with io.open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
            fh.write(text)

    good_changelog = "# Changelog\n\n## [Unreleased]\n\n- a change\n"
    good_plugin = json.dumps({"name": "audit", "version": "1.0.0"})
    rows = {
        "preflight": {"faults": _failing("git rev-parse v9.9.9",
                                         (0, "an existing tag\n"))},
        "bump-version": {
            # Nothing a fake can answer makes bump-version red while letting
            # preflight (which reads the same file) through, so this row
            # starts with preflight already recorded and an unparseable file.
            "seed": ("preflight",),
            "break": lambda root: _write(root, PLUGIN_JSON_REL, "{not json"),
            "repair": lambda root: _write(root, PLUGIN_JSON_REL, good_plugin)},
        "finalize-changelog": {
            "break": lambda root: _write(root, CHANGELOG_REL, "# Changelog\n"),
            "repair": lambda root: _write(root, CHANGELOG_REL, good_changelog)},
        "followers": {"faults": _failing("capture-screenshots.mjs",
                                         (1, "no browser"))},
        "commit": {"faults": _failing("git commit", (1, "hook refused"))},
        "verify-release": {"faults": _failing("tools/verify.sh",
                                              (1, "a gate is red"))},
        "push-ci-branch": {"faults": _failing("git push origin HEAD:",
                                              (1, "rejected"))},
        "wait-ci": {"faults": None},
        "tag": {"faults": _failing("git tag -a", (1, "tag refused"))},
        "push-main-tag": {"faults": _failing("git push origin main",
                                             (1, "rejected"))},
        "gh-release": {"faults": _failing("gh release create",
                                          (1, "HTTP 502"))},
        "check-published": {"faults": _failing("check-release-published.py",
                                               (1, "Latest names v1.0.0"))},
    }
    check("rl15 the resume table has exactly one row per step, in STEPS "
          "order: %r" % (sorted(set(STEPS) ^ set(rows)),),
          sorted(rows) == sorted(STEPS))
    for index, name in enumerate(STEPS):
        row = rows.get(name) or {}
        earlier = STEPS[:index]
        tmp = _fixture_repo()
        try:
            world = _new_world()
            state_path = os.path.join(tmp, "state.json")
            state = {"steps": {}, "version": "9.9.9"}
            for seeded in row.get("seed", ()):
                mark(state, seeded, "done", "fixture: pre-seeded done")
                state["oldVersion"] = "1.0.0"
            if row.get("break"):
                row["break"](tmp)
            faults = row.get("faults") or []
            if name == "wait-ci":
                faults = [(lambda c: c.startswith("gh run list"),
                           lambda _t: (0, json.dumps([{
                               "headSha": world["pushedSha"],
                               "status": "completed", "conclusion": "failure",
                               "databaseId": 3}])))]
            runner = FakeRunner(faults + _faithful_responses(world))
            ctx = Context(tmp, "9.9.9", push=True, runner=runner, state=state,
                         state_path=state_path, poll_interval=0, ci_timeout=2)
            code1, detail1 = run_pipeline(ctx, out=io.StringIO())
            first_ok = (code1 == 1
                        and (ctx.state["steps"].get(name) or {}).get("status")
                        == "failed"
                        and all(step_done(ctx.state, e) for e in earlier))
            if row.get("repair"):
                row["repair"](tmp)
            runner2 = FakeRunner(_faithful_responses(world))
            ctx2 = Context(tmp, "9.9.9", push=True, runner=runner2,
                          state=load_state(state_path), state_path=state_path,
                          poll_interval=0, ci_timeout=2)
            printed2 = io.StringIO()
            code2, detail2 = run_pipeline(ctx2, out=printed2)
            text2 = printed2.getvalue()
            reran = [e for e in earlier
                     if "== %-16s skipped (already done)" % (e,) not in text2
                     or (e in signature
                         and any(signature[e] in c for c in runner2.calls))]
            own = signature.get(name)
            check("rl14 %s: a first run red at %s stops there with every "
                  "earlier step done, and the resume re-runs %s and no "
                  "earlier step, then finishes: first %r / resume %r / "
                  "re-ran %r / %s"
                  % (name, name, name, excerpt(detail1, 160),
                     excerpt(detail2, 160), reran, _call_list(runner2)),
                  first_ok and code2 == 0 and not reran
                  and ("-> %s\n" % (name,)) in text2
                  and (own is None or any(own in c for c in runner2.calls)))
        finally:
            remove_tree(tmp)

    # --- release_permitted: asked again before every remote step, not only -----
    # at preflight, because a bug can be filed in the gap a CI wait leaves open.
    _pre_remote = ("preflight", "bump-version", "finalize-changelog",
                  "followers", "verify-release", "commit")

    tmp = _fixture_repo()
    try:
        state_path = os.path.join(tmp, "state.json")
        state = {"steps": {}, "version": "9.9.9", "oldVersion": "1.0.0"}
        for name in _pre_remote:
            mark(state, name, "done", "fixture: pre-seeded done")
        plan_path = os.path.join(tmp, "docs", "audit", "audit-plan.json")
        with io.open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
        plan["bugs"] = [{"id": "BUG-9", "status": "open", "severity": "high",
                         "title": "filed mid-release"}]
        with io.open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        runner = FakeRunner(default=(0, ""))
        ctx = Context(tmp, "9.9.9", push=True, runner=runner, state=state,
                     state_path=state_path, poll_interval=0, ci_timeout=2)
        code, detail = run_pipeline(ctx, out=io.StringIO())
        check("rl8 a bug filed in the plan after preflight ran stops the run "
              "at the next remote step, naming the bug, with no push issued: "
              "%r / %s" % (detail, _call_list(runner)),
              code == 1 and "BUG-9" in detail
              and step_done(ctx.state, "push-ci-branch") is False
              and not runner.calls)
    finally:
        remove_tree(tmp)

    # A run that never appears: the fake ends the poll, not the 60s timeout,
    # and the failure text built from its call list stays short.
    runner = FakeRunner(default=(0, "[]"), call_limit=50)
    tmp = _fixture_repo()
    try:
        ctx = Context(tmp, "9.9.9", push=False, runner=runner,
                     poll_interval=0, ci_timeout=60)
        began = time.time()
        ok, detail = wait_ci(ctx, "audit/some-branch")
        waited = time.time() - began
    finally:
        remove_tree(tmp)
    message = "%r / %s" % (detail, excerpt(repr(runner.calls)))
    check("rl8b wait_ci over a fake that never shows a run returns once the "
          "fake's call limit ends the poll, not at its 60s timeout, and the "
          "message naming the call list is bounded (a few KB at most): "
          "%.2fs, %d calls, %d chars"
          % (waited, len(runner.calls), len(message)),
          ok is False and waited < 10 and len(runner.calls) == 51
          and len(message) < 2048 and "[... " in message)

    tmp = _fixture_repo(bugs=[{"id": "BUG-2", "status": "open",
                              "severity": "high", "title": "still open"}])
    try:
        session_id = "release-selftest-session"
        prior = os.environ.get("CLAUDE_CODE_SESSION_ID")
        os.environ["CLAUDE_CODE_SESSION_ID"] = session_id
        try:
            ctx = Context(tmp, "9.9.9", push=False,
                         runner=FakeRunner(default=(1, "no such tag")),
                         state_path=os.path.join(tmp, "state.json"))
            bypass_dir = os.path.join(tmp, ".claude", "state")
            os.makedirs(bypass_dir, exist_ok=True)
            bypass_path = os.path.join(
                bypass_dir, "release-bypass-%s.json" % (session_id,))
            with io.open(bypass_path, "w", encoding="utf-8") as fh:
                json.dump({"armedAtEpoch": time.time(), "ttlSeconds": 3600}, fh)
            allowed, refusal = release_permitted(ctx)
            check("rl9 an armed, unexpired bypass slot for the running "
                  "session lets a plan with an open bug through: %r"
                  % (refusal,), allowed is True and refusal is None)

            with io.open(bypass_path, "w", encoding="utf-8") as fh:
                json.dump({"armedAtEpoch": time.time() - 7200,
                          "ttlSeconds": 3600}, fh)
            allowed2, refusal2 = release_permitted(ctx)
            check("rl10 an expired bypass slot does not let the same bug "
                  "through: %r" % (refusal2,),
                  allowed2 is False and "BUG-2" in (refusal2 or ""))
        finally:
            if prior is None:
                os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            else:
                os.environ["CLAUDE_CODE_SESSION_ID"] = prior
    finally:
        remove_tree(tmp)

    tmp = _fixture_repo(bugs=[{"id": "BUG-3", "status": "open",
                              "severity": "high", "title": "no session"}])
    try:
        prior = os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        try:
            ctx = Context(tmp, "9.9.9", push=False,
                         runner=FakeRunner(default=(1, "no such tag")),
                         state_path=os.path.join(tmp, "state.json"))
            allowed, refusal = release_permitted(ctx)
            check("rl11 a bug in the plan with no session id set at all is "
                  "refused - no bypass slot can be looked up for a session "
                  "that does not exist: %r" % (refusal,),
                  allowed is False and "BUG-3" in (refusal or ""))
        finally:
            if prior is not None:
                os.environ["CLAUDE_CODE_SESSION_ID"] = prior
    finally:
        remove_tree(tmp)

    # --- the `ci` step runs alone ------------------------------------------------
    calls = []

    def ci_runner(args, cwd=None):
        text = args if isinstance(args, str) else " ".join(str(a) for a in args)
        calls.append(text)
        if "gh workflow run" in text:
            return 0, "ok"
        if text.startswith("git rev-parse"):
            return 0, "cafef00d\n"
        if "gh run list" in text:
            return 0, json.dumps([{"headSha": "cafef00d", "status": "completed",
                                   "conclusion": "success", "databaseId": 9}])
        return 0, ""

    ctx = Context(REPO, version=None, push=True, runner=ci_runner,
                 poll_interval=0, ci_timeout=2)
    ok, detail = dispatch_ci(ctx, "audit/some-branch")
    ok2, detail2 = ok and wait_ci(ctx, "audit/some-branch")
    check("rl5 `ci <ref>` dispatches ci.yml on the ref and waits for THAT "
          "commit's run, succeeding on a success conclusion: %r / %r"
          % (detail, detail2), ok and ok2 and "succeeded" in detail2)
    check("rl5b a cancelled run is reported as cancelled, never as failed",
          "CANCELLED" in (wait_ci(
              Context(REPO, None, True,
                     runner=lambda a, cwd=None: (
                         (0, json.dumps([{"headSha": "cafef00d",
                                         "status": "completed",
                                         "conclusion": "cancelled",
                                         "databaseId": 10}]))
                         if (a if isinstance(a, str) else " ".join(a)).find(
                             "gh run list") >= 0
                         else (0, "cafef00d\n")),
                     poll_interval=0, ci_timeout=2),
              "audit/some-branch")[1]))

    # --- parsing --------------------------------------------------------------
    check("rl6 `run` needs --version on a first invocation",
          parse_run_argv(["--push"]) == {"push": True, "version": None,
                                        "state": None}
          and parse_run_argv(["--version", "1.2.3"])
          == {"push": False, "version": "1.2.3", "state": None})
    check("rl6b an unknown argument refuses rather than being ignored",
          parse_run_argv(["--wat"]) is None
          and parse_run_argv(["--version"]) is None)
    check("rl7 the bare form `release.py --push` routes exactly as "
          "`release.py run --push` does - a reader typing the short form "
          "must still answer to `release_permitted`: %r"
          % ([route_subcommand(["--push"]), route_subcommand(["run", "--push"]),
             route_subcommand(["ci", "audit/x"])],),
          route_subcommand(["--push"]) == ("run", ["--push"])
          and route_subcommand(["run", "--push"]) == ("run", ["--push"])
          and route_subcommand(["ci", "audit/x"]) == ("ci", ["audit/x"]))


def _selftest():
    from _suite import run           # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    raise SystemExit(main())
