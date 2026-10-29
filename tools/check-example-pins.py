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
because a CI checkout does not promise to carry tags. The release run passes
`--pending v<version>`: a pin naming the tag the release is about to create is read
against HEAD's tree (what the tag will point at) instead of being refused as
unavailable, so the example can be repinned in the release commit itself. The
selftest's live case asks with the lag question off, since "the pin trails the
newest tag" is true of a release moment and not of every later commit.

THE SAME READER NAMES WHAT A RELEASE MUST REPIN. `pinned_examples()` is the set of
example files this checker reads that pin a tag, and `repin_examples()` rewrites
them; `tools/release.py` repins and stages from those two, so a pinned example
added under `docs/examples/` is followed by the release with no edit to the
release script. `--list` prints that set, one path per line, for a person or a
script that wants the same answer.

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

USAGE = ("usage: check-example-pins.py [--repo <path>] [--pending <vX.Y.Z>] "
         "[--list] [--selftest]\n")

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


def repin_text(text, tag):
    """`text` with every pin on a code line rewritten to `tag`. PURE.

    The pins are the ones `read_pins` reads - the same patterns, code lines only -
    so a comment that mentions an old tag is left as written."""
    def rewrite(line):
        if line.strip().startswith("#"):
            return line
        for pattern in TAG_PATTERNS:
            line = pattern.sub(
                lambda m: m.group(0).replace(m.group(1), tag), line)
        return line
    return "".join(rewrite(line) for line in text.splitlines(True))


def _read_text(path):
    with io.open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def pinned_examples(root=None):
    """The repo-relative, `/`-separated paths of the examples that pin a tag.

    The files are the ones `check()` reads (`example_files`), narrowed by the
    reader `check_example` asks (`read_pins`), so the set a release repins and
    stages cannot differ from the set this checker holds to a tag."""
    return sorted(
        "/".join(EXAMPLES_DIR.split(os.sep) + [os.path.basename(path)])
        for path in example_files(root)
        if read_pins(_read_text(path)))


def repin_examples(root, tag):
    """Rewrites every pinned example under `root` to `tag`; the paths that
    changed, in `pinned_examples` order. A file already on `tag` is not
    rewritten and is not named."""
    changed = []
    for rel in pinned_examples(root):
        path = os.path.join(root or REPO, *rel.split("/"))
        text = _read_text(path)
        updated = repin_text(text, tag)
        if updated == text:
            continue
        with io.open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
        changed.append(rel)
    return changed


def check_example(name, text, git, tags, pending=None, lag=True):
    """The `(finding or refusal, detail)` rows for one example's text.

    `pending` is the tag the release being cut will create. A pin naming it while
    it does not exist yet is read against HEAD's tree, which is what the tag will
    point at. `lag=False` leaves out the question whether the pin trails the newest
    tag: that is a claim about the moment of a release, not about every commit.
    """
    rows = []
    pins, scripts = read_pins(text), read_scripts(text)
    if scripts and not pins:
        return [("no-pin", name)]
    newest = newest_tag(list(tags) + ([pending] if pending else []))
    for tag in pins:
        ref = "HEAD" if tag == pending and tag not in tags else tag
        out, code = git(["ls-tree", "-r", "--name-only", ref, "--",
                         SCRIPTS_PREFIX.rstrip("/")])
        if code != 0:
            rows.append(("tag-unavailable", "%s pins %s" % (name, tag)))
            continue
        held = set(out.split())
        for path in scripts:
            if path not in held:
                rows.append(("script-missing-at-tag",
                             "%s: %s is not in %s" % (name, path, tag)))
        if lag and newest and version_key(tag) < version_key(newest):
            rows.append(("pin-behind-newest-tag",
                         "%s pins %s, newest tag is %s" % (name, tag, newest)))
    return rows


def check(root=None, git=None, files=None, pending=None, lag=True):
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
        run["rows"].extend(check_example(name, text, git, tags, pending, lag))
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
    """`(root, pending, problem)` -- `problem` is None exactly when the rest is usable."""
    rest = list(argv)
    root = None
    pending = None
    if "--repo" in rest:
        index = rest.index("--repo")
        if index + 1 >= len(rest):
            return None, None, "--repo needs a path"
        root = rest[index + 1]
        del rest[index:index + 2]
        if not os.path.isdir(root):
            return None, None, "--repo %r is not a directory" % (root,)
    if "--pending" in rest:
        index = rest.index("--pending")
        if index + 1 >= len(rest) or not re.match(r"^v\d+\.\d+\.\d+$",
                                                  rest[index + 1]):
            return None, None, "--pending needs a tag like v1.2.3"
        pending = rest[index + 1]
        del rest[index:index + 2]
    if rest:
        return None, None, "unknown argument(s): %s" % (" ".join(rest),)
    return root, pending, None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return _selftest()
    listing = "--list" in argv
    root, pending, problem = parse_argv([a for a in argv if a != "--list"])
    if problem is not None:
        sys.stderr.write("check-example-pins.py: %s\n" % (problem,))
        sys.stderr.write(USAGE)
        return 2
    if listing:
        found = pinned_examples(root)
        for rel in found:
            sys.stdout.write(rel + "\n")
        if not found:
            sys.stderr.write("check-example-pins.py: no example pins a tag, "
                             "so there is nothing to list\n")
        return 0 if found else 1
    code, lines = report(check(root, pending=pending))
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
               % ([parse_argv(["--repo"])[2], parse_argv(["--wat"])[2]],),
               parse_argv([]) == (None, None, None)
               and parse_argv(["--repo"])[2] is not None
               and parse_argv(["--wat"])[2] is not None
               and parse_argv(["--pending", "3.3"])[2] is not None
               and parse_argv(["--pending", "v3.3.0"]) == (None, "v3.3.0", None)
               and _quietly(["--wat"]) == 2)

    head_trees = {"v3.2.0": [_GATE], "HEAD": [_GATE]}
    git = _fake_git(head_trees, tags=["v3.2.0"])
    pinned_new = _NEW_EXAMPLE.replace("v3.2.0", "v3.3.0")
    rows = check_example("x.yml", pinned_new, git, ["v3.2.0"], pending="v3.3.0")
    check_case("p1 a pin naming the tag this release is about to create is read "
               "against HEAD and passes, not refused: %r" % (rows,), rows == [])

    rows = check_example("x.yml", pinned_new, git, ["v3.2.0"])
    check_case("p2 the same pin without a pending release still refuses: %r"
               % (rows,), [n for n, _d in rows] == ["tag-unavailable"])

    rows = check_example("x.yml", _NEW_EXAMPLE, git, ["v3.2.0"], pending="v3.3.0")
    check_case("p3 leaving the example on the previous tag during a release is "
               "still the lag finding: %r" % (rows,),
               [n for n, _d in rows] == ["pin-behind-newest-tag"])

    git = _fake_git({"v3.2.0": [_GATE], "v3.3.0": [_GATE]})
    rows = check_example("x.yml", _NEW_EXAMPLE, git, ["v3.2.0", "v3.3.0"],
                         lag=False)
    check_case("p4 with the lag question off an older pin that holds the script "
               "is clean: %r" % (rows,), rows == [])

    # --- the pinned set release.py repins and stages -------------------------
    from _suite import remove_tree
    pin_root = tempfile.mkdtemp()
    try:
        folder = os.path.join(pin_root, "docs", "examples")
        os.makedirs(folder)
        bodies = {
            "a-branch.yml": _OLD_EXAMPLE,
            "b-url.yaml": "run: curl https://x/claude-plugins/v0.5.0/s.sh\n",
            "c-nopin.yml": "steps:\n  - script: echo hi\n",
            "d-comment-only.yml": "# git clone --branch v0.5.0 somewhere\nx: 1\n",
            "e-notes.md": "git clone --branch v0.5.0 x\n",
        }
        for name, body in bodies.items():
            with io.open(os.path.join(folder, name), "w", encoding="utf-8") as h:
                h.write(body)
        found = pinned_examples(pin_root)
        seen = check(pin_root, git=_fake_git({"v0.5.0": [_GATE]}))["examples"]
        checked_and_pinned = []
        for name in seen:
            with io.open(os.path.join(folder, name), encoding="utf-8") as h:
                if read_pins(h.read()):
                    checked_and_pinned.append("docs/examples/" + name)
        check_case("x1 pinned_examples names exactly the examples the checker "
                   "reads that pin a tag - the .yml and the .yaml, never the "
                   "unpinned one, the comment-only one or the .md - and the two "
                   "sets are compared: %r vs %r" % (found, checked_and_pinned),
                   found == ["docs/examples/a-branch.yml",
                             "docs/examples/b-url.yaml"]
                   and found == sorted(checked_and_pinned))
        live_pinned = pinned_examples()
        live_seen = [os.path.join(EXAMPLES_DIR, n).replace(os.sep, "/")
                     for n in (os.path.basename(f) for f in example_files(None))
                     if read_pins(_read_text(os.path.join(REPO, EXAMPLES_DIR, n)))]
        # The two sides above share their ingredients (the same files, the same
        # filter), so they agree however the filter reads. The named example is
        # the side that does not: it clones the plugin at a tag on a code line,
        # so a filter that stopped reading that pin drops it from both sides.
        check_case("x2 THE LIVE SET: this repository's own pinned examples, as "
                   "the function release.py reads returns them, are the ones "
                   "the checker's own listing finds, and they hold the Azure "
                   "Pipelines example by name: %r vs %r"
                   % (live_pinned, live_seen),
                   live_pinned == sorted(live_seen)
                   and "docs/examples/azure-pipelines.yml" in live_pinned)
        listed = io.StringIO()
        held, sys.stdout = sys.stdout, listed
        try:
            list_code = main(["--repo", pin_root, "--list"])
        finally:
            sys.stdout = held
        check_case("x5 `--list` prints the pinned set one path per line and "
                   "exits 0: %r" % (listed.getvalue(),),
                   list_code == 0
                   and listed.getvalue().split() == found)
        bare = tempfile.mkdtemp()
        try:
            check_case("x6 `--list` over a repository whose examples pin "
                       "nothing is a refusal (exit 1), never an empty "
                       "all-clear",
                       _quietly(["--repo", bare, "--list"]) == 1)
        finally:
            remove_tree(bare)
        retext = repin_text(_OLD_EXAMPLE + "# --branch v0.5.0 in a comment\n",
                            "v4.0.0")
        check_case("x3 repin_text rewrites every code-line pin and leaves a "
                   "comment line alone: %r" % (retext,),
                   read_pins(retext) == ["v4.0.0"]
                   and "# --branch v0.5.0 in a comment" in retext
                   and retext.count("v4.0.0") == 1
                   and read_pins(repin_text(bodies["b-url.yaml"], "v4.0.0"))
                   == ["v4.0.0"])
        changed = repin_examples(pin_root, "v4.0.0")
        after = {}
        for name in bodies:
            # Newlines translated, as `bodies` were written: on Windows the
            # write above put CRLF on disk, and the comparison is of the text.
            with io.open(os.path.join(folder, name), encoding="utf-8") as h:
                after[name] = h.read()
        check_case("x4 repin_examples rewrites the pinned examples on disk, "
                   "returns exactly those paths, and leaves every other file "
                   "byte for byte as it was: %r" % (changed,),
                   changed == found
                   and read_pins(after["a-branch.yml"]) == ["v4.0.0"]
                   and read_pins(after["b-url.yaml"]) == ["v4.0.0"]
                   and all(after[n] == bodies[n] for n in
                           ("c-nopin.yml", "d-comment-only.yml", "e-notes.md"))
                   and repin_examples(pin_root, "v4.0.0") == [])
    finally:
        remove_tree(pin_root)

    live = check(lag=False)
    check_case("l1 THE LIVE CLAIM: the committed examples, asked of this "
               "repository's own tags, name no missing script. A checkout without "
               "the tags answers with a refusal, which is the honest answer there "
               "and not a clean one: %r" % (live["rows"],),
               bool(live["examples"] or live["rows"])
               and all(is_refusal(n) for n, _d in live["rows"]))

    # The real reader against a real repository: a file path in a tag's tree.
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
