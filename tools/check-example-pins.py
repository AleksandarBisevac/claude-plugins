#!/usr/bin/env python3
"""Every plugin script an example invokes must exist at the tag the example pins.

WHY THIS EXISTS. `docs/examples/azure-pipelines.yml` told a reader to clone the
plugin at an early tag and then called scripts, with options, that the tag did not
have. Nothing was wrong with the pipeline's logic; the pin simply named a release
that predates the files the steps call, so a user copying the example got a red
build on its first run. A pin is a claim about what a tag contains, and the only
thing that can keep that claim true is asking the tag.

WHAT IT ASKS. For each example under `docs/examples/`: which tags does it pin
(`--branch vX.Y.Z`, or a `claude-plugins/vX.Y.Z/` URL), which
script paths under `plugins/audit/scripts/` does it invoke (comment lines are not
invocations), and does `git ls-tree` at each pinned tag list each path. It asks the
tag's tree, not the working tree, because the working tree is exactly the thing the
pin is not about.

IT IS ALSO ASKED WHETHER THE PIN LAGS. A pin that names a tag older than the newest
tag this repository has is what a version bump leaves behind, and it would still
pass the first question for as long as the old tag happened to hold the files. The
bump followers list in `tools/verify.sh` names this check, so the next bump cannot
pass over the example.

"COULD NOT ASK" IS NOT "CLEAN". A pinned tag that is not available locally (a
shallow clone, a clone without tags) is a REFUSAL with a non-zero exit and a closing
line saying nothing was checked; so is a repository with no tags at all. A run that
cleared nothing must not print what a run that found nothing prints.

IT IS A RELEASE-SET GATE. `tools/verify.sh --release` runs it; `ci.yml` does not,
because a CI checkout does not promise to carry tags.

Exit codes: 0 clean - 1 a finding or a refusal - 2 usage error.
"""

import io
import os
import re
import subprocess
import sys
import tempfile

_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)

EXAMPLES_DIR = os.path.join("docs", "examples")
EXAMPLE_SUFFIXES = (".yml", ".yaml")
SCRIPTS_PREFIX = "plugins/audit/scripts/"

TAG_PATTERNS = (
    re.compile(r"--branch\s+(v\d+\.\d+\.\d+)\b"),
    re.compile(r"claude-plugins/(v\d+\.\d+\.\d+)/"),
)
SCRIPT_PATTERN = re.compile(r"plugins/audit/scripts/[A-Za-z0-9_./-]+\.py")

USAGE = "usage: check-example-pins.py [--repo <path>] [--selftest]\n"

FINDINGS = {
    "script-missing-at-tag": ("the example invokes a plugin script the pinned "
                              "tag does not contain, so a user copying it gets "
                              "a failing build"),
    "pin-behind-newest-tag": ("the example pins a tag older than the newest tag "
                              "this repository has, which is what a version "
                              "bump leaves behind"),
    "no-pin": ("the example invokes plugin scripts and pins no tag, so nothing "
               "says which release holds them"),
}

REFUSALS = {
    "git-unavailable": "`git` could not be run, so no tag was ever asked",
    "no-tags": ("this repository has no version tag locally, so there is nothing "
                "to hold a pin against. Fetch tags (`git fetch --tags`)"),
    "tag-unavailable": ("the pinned tag is not available locally, so its tree "
                        "was never read. Fetch tags (`git fetch --tags`)"),
}


def is_refusal(name):
    return name in REFUSALS


# --- reading an example -------------------------------------------------------
def _code_text(text):
    """The example with its comment lines removed: a comment names, it never calls."""
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#"))


def read_pins(text):
    """The sorted distinct tags an example pins. PURE."""
    code = _code_text(text)
    found = set()
    for pattern in TAG_PATTERNS:
        found.update(pattern.findall(code))
    return sorted(found)


def read_scripts(text):
    """The sorted distinct plugin script paths an example invokes. PURE."""
    return sorted(set(SCRIPT_PATTERN.findall(_code_text(text))))


def version_key(tag):
    return tuple(int(part) for part in tag[1:].split("."))


def newest_tag(tags):
    """The highest `vX.Y.Z` of `tags`, or None. NUMERIC, never lexical."""
    versions = [t for t in tags if re.match(r"^v\d+\.\d+\.\d+$", t)]
    return max(versions, key=version_key) if versions else None


# --- asking git ---------------------------------------------------------------
def git_reader(root):
    """A `git` reader: `read(args) -> (stdout, exit code)`, never raising."""
    def read(args):
        try:
            proc = subprocess.run(["git", "-C", root or REPO] + list(args),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True)
        except OSError:
            return "", 127
        return proc.stdout, proc.returncode
    return read


def example_files(root):
    folder = os.path.join(root or REPO, EXAMPLES_DIR)
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
            if n.endswith(EXAMPLE_SUFFIXES)]


def check_example(name, text, git, tags):
    """The `(finding or refusal, detail)` rows for one example's text."""
    rows = []
    pins, scripts = read_pins(text), read_scripts(text)
    if scripts and not pins:
        return [("no-pin", name)]
    newest = newest_tag(tags)
    for tag in pins:
        out, code = git(["ls-tree", "-r", "--name-only", tag, "--",
                         SCRIPTS_PREFIX.rstrip("/")])
        if code != 0:
            rows.append(("tag-unavailable", "%s pins %s" % (name, tag)))
            continue
        held = set(out.split())
        for path in scripts:
            if path not in held:
                rows.append(("script-missing-at-tag",
                             "%s: %s is not in %s" % (name, path, tag)))
        if newest and version_key(tag) < version_key(newest):
            rows.append(("pin-behind-newest-tag",
                         "%s pins %s, newest tag is %s" % (name, tag, newest)))
    return rows


def check(root=None, git=None, files=None):
    """`{"examples": [...], "rows": [(name, detail)]}` for the whole directory."""
    git = git_reader(root) if git is None else git
    run = {"examples": [], "rows": []}
    out, code = git(["tag", "--list", "v*"])
    if code != 0:
        run["rows"].append(("git-unavailable", "git tag --list"))
        return run
    tags = out.split()
    if newest_tag(tags) is None:
        run["rows"].append(("no-tags", root or REPO))
        return run
    for path in (example_files(root) if files is None else files):
        name = os.path.basename(path)
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        run["examples"].append(name)
        run["rows"].extend(check_example(name, text, git, tags))
    return run


def report(run):
    """`(exit code, [lines])` for one `check()` result. PURE."""
    lines = []
    for name, detail in run["rows"]:
        label = "REFUSED" if is_refusal(name) else "FOUND"
        lines.append("%s %s: %s (%s)"
                     % (label, name, FINDINGS.get(name) or REFUSALS[name],
                        detail))
    if any(is_refusal(n) for n, _d in run["rows"]):
        lines.append("")
        lines.append("NOTHING WAS CHECKED. This run did not clear the examples; "
                     "it failed to ask. Re-run where the tags are available "
                     "before reading anything into a green release.")
        return 1, lines
    if run["rows"]:
        lines.append("")
        lines.append("Repin the example to the newest release tag, and make sure "
                     "every script it calls exists there.")
        return 1, lines
    if not run["examples"]:
        return 1, ["FOUND no-examples: no example file was read, so no pin was "
                   "checked"]
    return 0, ["OK: every plugin script invoked by %s exists at the tag it pins"
               % (", ".join(run["examples"]),)]


# --- command line -------------------------------------------------------------
def parse_argv(argv):
    """`(root, problem)` -- exactly one of the two is None."""
    rest = list(argv)
    root = None
    if "--repo" in rest:
        index = rest.index("--repo")
        if index + 1 >= len(rest):
            return None, "--repo needs a path"
        root = rest[index + 1]
        del rest[index:index + 2]
        if not os.path.isdir(root):
            return None, "--repo %r is not a directory" % (root,)
    if rest:
        return None, "unknown argument(s): %s" % (" ".join(rest),)
    return root, None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return _selftest()
    root, problem = parse_argv(argv)
    if problem is not None:
        sys.stderr.write("check-example-pins.py: %s\n" % (problem,))
        sys.stderr.write(USAGE)
        return 2
    code, lines = report(check(root))
    for line in lines:
        sys.stdout.write(line + "\n")
    return code


# --- selftest -----------------------------------------------------------------
_GATE = SCRIPTS_PREFIX + "governance/run-test-gate.py"
_FLAT = SCRIPTS_PREFIX + "validate-manifest.py"
_OLD_EXAMPLE = """\
# comment naming %s
steps:
  - script: |
      git clone --depth 1 --branch v0.5.0 https://example/claude-plugins.git src
      python src/%s m --full
""" % (SCRIPTS_PREFIX + "status/audit-status.py", _GATE)
_NEW_EXAMPLE = _OLD_EXAMPLE.replace("v0.5.0", "v3.2.0")


def _fake_git(trees, tags=None, tag_code=0):
    """A git reader answering from `{tag: [paths]}`; an unknown tag exits 128."""
    def read(args):
        if args[:1] == ["tag"]:
            return "\n".join(sorted(trees) if tags is None else tags), tag_code
        if args[:1] == ["ls-tree"]:
            held = trees.get(args[3])
            if held is None:
                return "", 128
            return "\n".join(held), 0
        return "", 1
    return read


def _rows(text, trees, tags=None):
    git = _fake_git(trees, tags)
    return check_example("x.yml", text, git, sorted(trees) if tags is None else tags)


def _quietly(argv):
    held, sys.stderr = sys.stderr, io.StringIO()
    try:
        return main(argv)
    finally:
        sys.stderr = held


def _cases(check_case):
    old_trees = {"v0.5.0": [_FLAT],
                 "v3.2.0": [_GATE]}

    check_case("r1 the example's pins and calls are read from code lines only: a "
               "comment naming a script is not a call: %r"
               % ([read_pins(_OLD_EXAMPLE), read_scripts(_OLD_EXAMPLE)],),
               read_pins(_OLD_EXAMPLE) == ["v0.5.0"]
               and read_scripts(_OLD_EXAMPLE) == [_GATE])

    check_case("r2 the newest tag is chosen numerically, so v3.10.0 beats v3.9.0: "
               "%r" % (newest_tag(["v3.9.0", "v3.10.0", "v3.2.0", "junk"]),),
               newest_tag(["v3.9.0", "v3.10.0", "v3.2.0", "junk"]) == "v3.10.0"
               and newest_tag([]) is None)

    rows = _rows(_OLD_EXAMPLE, old_trees)
    check_case("c1 an example pinning a tag that lacks the script it calls is "
               "refused by name: %r" % (rows,),
               [n for n, _d in rows] == ["script-missing-at-tag",
                                         "pin-behind-newest-tag"]
               and "v0.5.0" in rows[0][1])

    rows = _rows(_NEW_EXAMPLE, old_trees)
    check_case("c2 the repinned example, at a tag holding the script and the "
               "newest tag, passes with no row: %r" % (rows,), rows == [])

    rows = _rows(_NEW_EXAMPLE, {"v3.2.0": [_GATE], "v3.3.0": [_GATE]})
    check_case("c3 a pin that holds the files but trails the newest tag is still "
               "a finding - the bump follower: %r" % (rows,),
               [n for n, _d in rows] == ["pin-behind-newest-tag"])

    rows = _rows(_NEW_EXAMPLE, {"v3.2.0": [_GATE]}, tags=["v3.2.0"])
    git = _fake_git({}, tags=["v3.2.0"])
    missing = check_example("x.yml", _NEW_EXAMPLE, git, ["v3.2.0"])
    check_case("c4 a pinned tag that is not available locally REFUSES rather than "
               "passing: %r" % (missing,),
               rows == [] and [n for n, _d in missing] == ["tag-unavailable"]
               and is_refusal("tag-unavailable"))

    code, lines = report({"examples": ["x.yml"], "rows": missing})
    check_case("c5 a refusal exits non-zero and says nothing was checked: %r"
               % (lines,),
               code == 1 and any("NOTHING WAS CHECKED" in l for l in lines))

    no_pin = "steps:\n  - script: python %s m\n" % (_GATE,)
    rows = _rows(no_pin, old_trees)
    check_case("c6 calling plugin scripts without pinning any tag is a finding: "
               "%r" % (rows,), [n for n, _d in rows] == ["no-pin"])

    code, lines = report({"examples": [], "rows": []})
    check_case("c7 a run that read no example is not a clean run: %r" % (lines,),
               code == 1)

    no_tags = check(git=_fake_git({}, tags=[]), files=[])
    check_case("c8 a repository with no version tag refuses: %r"
               % (no_tags["rows"],),
               [n for n, _d in no_tags["rows"]] == ["no-tags"])

    check_case("i1 a wrong command line is a usage error and not a verdict: %r"
               % ([parse_argv(["--repo"])[1], parse_argv(["--wat"])[1]],),
               parse_argv([]) == (None, None)
               and parse_argv(["--repo"])[1] is not None
               and parse_argv(["--wat"])[1] is not None
               and _quietly(["--wat"]) == 2)

    live = check()
    check_case("l1 THE LIVE CLAIM: the committed examples, asked of this "
               "repository's own tags, carry no finding. A checkout without the "
               "tags answers with a refusal, which is the honest answer there and "
               "not a clean one: %r" % (live["rows"],),
               bool(live["examples"] or live["rows"])
               and all(is_refusal(n) for n, _d in live["rows"]))

    # The real reader against a real repository: a file path in a tag's tree.
    from _suite import remove_tree
    scratch = tempfile.mkdtemp()
    try:
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1")
        ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                 "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
        target = os.path.join(scratch, "plugins", "audit", "scripts",
                              "governance")
        os.makedirs(target)
        with io.open(os.path.join(target, "run-test-gate.py"), "w") as handle:
            handle.write("x\n")
        os.makedirs(os.path.join(scratch, "docs", "examples"))
        with io.open(os.path.join(scratch, "docs", "examples", "e.yml"), "w") as h:
            h.write(_NEW_EXAMPLE)
        for step in (["init", "-q"], ["add", "-A"],
                     ident + ["commit", "-q", "-m", "x"],
                     ident + ["tag", "v3.2.0"]):
            subprocess.run(["git", "-C", scratch] + step, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        run = check(scratch)
        check_case("g1 the REAL git reader, against a real repository whose tag "
                   "holds the script: clean: %r" % (run,),
                   run["rows"] == [] and run["examples"] == ["e.yml"])
        with io.open(os.path.join(scratch, "docs", "examples", "e.yml"), "w") as h:
            h.write(_OLD_EXAMPLE)
        run = check(scratch)
        check_case("g2 the same repository with the example pinned to a tag that "
                   "does not exist: refused, not passed: %r" % (run["rows"],),
                   [n for n, _d in run["rows"]] == ["tag-unavailable"])
    finally:
        remove_tree(scratch)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    raise SystemExit(main())
