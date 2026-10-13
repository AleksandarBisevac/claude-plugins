#!/usr/bin/env python3
"""
The cases for `_machine_paths.py` - what counts as machine identity in a string,
and how the plugin's own text is scrubbed of it before a committed file keeps it.

WHAT IS PINNED, and why each one is here rather than trusted:

- **Every shape, both directions.** Each machine-path shape is named by the
  detector and removed by the redaction, and each has an ALLOW twin that a
  widened pattern would wrongly rewrite. A scrub only ever seen redacting may
  be redacting everything.
- **The pre-reject drops nothing real.** `may_hold_path` skips the regexes for a
  string with none of the characters a machine path needs. The case runs the
  full redaction twice over one corpus - once through the shipped pre-reject,
  once with it replaced by a match-all - and demands identical output, so a
  pre-reject narrowed past a shape fails by naming the string.
- **The old door still opens.** `_journal_io` re-exports these names as the SAME
  objects, so `tools/check-committed-pii.py` and every caller keep judging by
  the one pattern set.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _machine_paths as M                         # noqa: E402
import _journal_io                                 # noqa: E402


def _samples():
    """One machine-path string per shape, each built so this file never spells
    one whole, and each paired with an allow twin."""
    return (
        ("posix-home", "/".join(("", "Users", "someone", "x")),
         "docs/users/x.md"),
        ("windows-user-path", "C:\\" + "\\".join(("Users", "someone", "x")) + "\\f",
         "C:docs"),
        ("session-slug", "/x/" + "-".join(("", "Users", "someone", "Desktop")) + "/s",
         "see docs/users-guide.md"),
        ("escaped-path", "%2F".join(("q=", "Users", "someone", "x")),
         "q=%2Fdocs%2Fx"),
        ("tempdir-session", "/".join(("", "private", "tmp", "claude-501", "p")),
         "src/tmp/claude-7.ts"),
        ("tempdir-session", "/".join(("", "var", "folders", "ab", "cdef", "T",
                                      "audit-red-1", "npmrc")),
         "docs/var/folders/ab/T/x.md"),
        ("unexpanded-home", "cwd=" + "~" + "/probe/notes.md",
         "costs ~5% more, see src/~/x"),
    )


def _bare_slugs():
    """Machine-path strings with NO separator and no percent sign: the only
    shapes the pre-reject's dash literals exist for, so a mutation that drops
    either literal cannot hide behind a sample that carries a `/`."""
    return ("-".join(("", "Users", "someone", "Desktop")),
            "-".join(("", "home", "someone", "work")),
            "-".join(("", "private", "tmp", "claude", "probe")))


def _corpus():
    """Every sample, plus every string of the shipped example plan and its shards."""
    strings = list(_bare_slugs())
    for _name, raw, allow in _samples():
        strings += [raw, allow, "probe at %s here" % (raw,)]
    here = os.path.join(_output.REPO_ROOT, "examples", "acme-store")
    found = []

    def walk(value):
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    if here:
        for dirpath, _dirs, files in os.walk(here):
            for name in files:
                if name.endswith(".json"):
                    with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                        walk(json.load(fh))
    return strings, found


def _cases(check):
    proj = _harness.fixture_root("machine-paths-")
    try:
        repo = os.path.join(proj, "repo")
        os.makedirs(os.path.join(repo, "src"))
        got = []
        for name, raw, allow in _samples():
            said = "probe at %s here" % (raw,)
            red = M.redacted_free_text(repo, said)
            got.append((name, M.machine_path_shape(said) == name,
                        raw not in red and M.machine_path_shape(red) is None,
                        M.machine_path_shape(allow) is None
                        and M.redacted_free_text(repo, allow) == allow))
        check("mp1 each shape is named by the detector and removed by the "
              "redaction, and its allow twin is left byte for byte: %r" % (got,),
              all(g[1] and g[2] and g[3] for g in got))

        inside = os.path.join(repo, "src", "a.py")
        out = M.redacted_free_text(repo, "wrote %s and %s" % (inside, os.path.join(
            repo, "..", "elsewhere", "b.txt")))
        check("mp2 an in-repo absolute path becomes repo-relative and an "
              "outside one the outside token, the sentence around both kept: %r"
              % (out,),
              out == "wrote src/a.py and %s" % (M.OUTSIDE_TOKEN,))

        # THE PRE-REJECT, both directions. First: it must accept every shape.
        check("mp3 the pre-reject lets every shape sample through, and every "
              "bare dash-joined slug that carries no separator at all, and "
              "the detector really names those slugs: %r"
              % ([n for n, raw, _a in _samples() if not M.may_hold_path(raw)]
                 + [x for x in _bare_slugs() if not M.may_hold_path(x)],),
              all(M.may_hold_path(raw) for _n, raw, _a in _samples())
              and all(M.may_hold_path(x) and M.machine_path_shape(x) is not None
                      for x in _bare_slugs()))
        samples, real = _corpus()
        corpus = samples + real
        shipped = M._MAY_HOLD_PATH
        fast = [M.redacted_free_text(repo, s) for s in corpus]
        M._MAY_HOLD_PATH = re.compile("")
        try:
            slow = [M.redacted_free_text(repo, s) for s in corpus]
        finally:
            M._MAY_HOLD_PATH = shipped
        differ = [s[:60] for s, a, b in zip(corpus, fast, slow) if a != b]
        check("mp4 the shipped pre-reject and a match-all give the same output "
              "over %d strings (%d from the shipped example plan): differ=%r"
              % (len(corpus), len(real), differ),
              not differ and len(real) > 50)
        # SECOND DIRECTION: a pre-reject that accepts everything would pass mp4
        # by construction, so the share it skips is counted.
        skipped = sum(1 for s in real if not M.may_hold_path(s))
        check("mp5 the pre-reject actually skips strings (%d of the example "
              "plan's %d): a match-all would pass mp4 and save nothing"
              % (skipped, len(real)), skipped > len(real) // 2)

        tree = {"a": ["x %s y" % (_samples()[0][1],), {"k": 3, "ok": "plain words"}],
                "n": None, "b": True}
        keep = json.dumps(tree, sort_keys=True)
        scrubbed = M.scrubbed_values(repo, tree)
        check("mp6 scrubbed_values returns a NEW structure with every string "
              "scrubbed, keys and scalars untouched, the argument unchanged: %r"
              % (scrubbed,),
              json.dumps(tree, sort_keys=True) == keep
              and scrubbed["a"][1] == {"k": 3, "ok": "plain words"}
              and scrubbed["n"] is None and scrubbed["b"] is True
              and M.machine_path_shape(json.dumps(scrubbed)) is None
              and scrubbed["a"][0].startswith("x ")
              and scrubbed["a"][0].endswith(" y"))

        home = "/".join(("", "Users", "someone", "work", "secret", "run.py"))
        row = {"steps": [{"command": "python3 " + home, "note": "ran " + home},
                         {"command": "python3 " + home}],
               "other": {"command": "python3 " + home}}
        kept = M.scrubbed_values(repo, row,
                                 exempt=M.exempt_positions(["/steps/*/command"]))
        plain = M.scrubbed_values(repo, row)
        check("mp8 a value at an EXEMPT POSITION passes through byte for byte, "
              "every index the wildcard covers included, while a sibling "
              "free-text field AND a field of the same NAME at another "
              "position are still scrubbed - the exemption is where a value "
              "sits, never what its key is called: %r" % ((kept, plain),),
              [s["command"] for s in kept["steps"]]
              == [s["command"] for s in row["steps"]]
              and home not in kept["steps"][0]["note"]
              and home not in kept["other"]["command"]
              and home not in json.dumps(plain)
              and row["steps"][0]["note"].endswith(home))
        whole = M.scrubbed_values(repo, row, exempt=M.exempt_positions(["/steps"]))
        check("mp9 an exempt position covers the whole subtree under it, and "
              "nothing outside it: %r" % (whole,),
              whole["steps"] == row["steps"]
              and home not in whole["other"]["command"])

        said = M.executed_value_refusal(repo, "meta.buildCommands.test",
                                        "python3 " + home)
        inner = M.executed_value_refusal(
            repo, "testGate", "sh " + os.path.join(repo, "tools", "gate.sh"))
        check("mp10 a machine path in an executed value is refused naming the "
              "field, the shape and the remedy a command can take - a "
              "repo-relative or PATH-resolved spelling, never a placeholder "
              "that would stop it running - and never the value; an in-repo "
              "absolute path is refused as the checkout root: %r"
              % ((said, inner),),
              said and "meta.buildCommands.test" in said and "posix-home" in said
              and "PATH" in said and "repo-relative" in said
              and "someone" not in said and "<home>" not in said
              and inner and "checkout-root" in inner and repo not in inner)
        check("mp11 ALLOW twin: a repo-relative command and a PATH-resolved "
              "one are no refusal - a door that refused every command would "
              "pass mp10: %r"
              % ([M.executed_value_refusal(repo, "testGate", v)
                  for v in ("python3 tools/gate.py", "npx vitest run",
                            ["test", "lint"])],),
              all(M.executed_value_refusal(repo, "testGate", v) is None
                  for v in ("python3 tools/gate.py", "npx vitest run",
                            ["test", "lint"])))

        # THE ONE PREDICATE `tools/check-committed-pii.py` now reads too
        # (`shape_fires`): a home directory deep enough still fires with its
        # leading separator cut, and a sentence's words joined by slashes do
        # not pick up a separator from standing nowhere near one.
        _pattern = dict(M.MACHINE_PATH_SHAPES)["posix-home"]
        _cut = "among them: Users/someone/p/x.js"
        _prose = "callers pass home/cwd/project directories"
        check("mp16 shape_fires still finds a cut home path (no leading "
              "separator, but deep enough) and leaves alone a prose phrase "
              "slashes merely join (shallower, no separator either): cut=%r "
              "prose=%r"
              % ([m.group(0) for m in _pattern.finditer(_cut)
                  if M.shape_fires("posix-home", m)],
                 [m.group(0) for m in _pattern.finditer(_prose)
                  if M.shape_fires("posix-home", m)]),
              any(M.shape_fires("posix-home", m)
                  for m in _pattern.finditer(_cut))
              and not any(M.shape_fires("posix-home", m)
                         for m in _pattern.finditer(_prose)))

        _spaced_root_cases(check, proj)

        check("mp7 the journal re-exports the SAME objects, so the detector "
              "tool and every old caller judge by one pattern set",
              _journal_io.MACHINE_PATH_SHAPES is M.MACHINE_PATH_SHAPES
              and _journal_io.machine_path_shape is M.machine_path_shape
              and _journal_io.redacted_free_text is M.redacted_free_text
              and _journal_io.OUTSIDE_TOKEN == M.OUTSIDE_TOKEN
              and _journal_io.canonical is M.canonical)
    finally:
        _harness.remove_tree(proj)


def _spaced_root_cases(check, proj):
    """A machine root holding a space - a home directory, the checkout's own
    root - is one path to the scrub, not two words.

    The fixture builds both under a directory named with a space and points
    HOME at it for the length of the block, so the run does not depend on the
    temp directory the sweep happened to hand this suite. Every fragment of
    the home spelling is asked for in the output, because a scrub that stops
    at the space leaves the tail of the user's path beside the token."""
    home = os.path.join(proj, "Some One")
    repo = os.path.join(home, "My Projects", "repo")
    os.makedirs(os.path.join(repo, "src"))
    os.makedirs(os.path.join(home, ".config"))
    os.makedirs(os.path.join(home, "My Projects", "other"))
    said = "read %s and %s and %s then %s" % (
        os.path.join(home, ".config", "tool"),
        os.path.join(repo, "src", "a.py"),
        os.path.join(home, "My Projects", "other", "b.txt"),
        os.path.join(home, "My Docs", "c.md"))
    want = "read %s and src/a.py and %s then %s" % (
        M.OUTSIDE_TOKEN, M.OUTSIDE_TOKEN, M.OUTSIDE_TOKEN)
    held = dict((k, os.environ.get(k)) for k in ("HOME", "USERPROFILE"))
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    try:
        free = M.redacted_free_text(repo, said)
        output = M.redacted_paths(repo, said)
        bare = M.redacted_free_text(repo, "home is %s" % (home,))
    finally:
        for key, value in held.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    fragments = ("One", "Projects", ".config", "other", "b.txt", "Docs", "c.md")
    check("mp12 a home root and a checkout root that HOLD A SPACE are each "
          "replaced whole - no fragment of the user's path survives beside "
          "the token - and a path inside the spaced checkout stays "
          "repo-relative, in free text and in program output alike: %r"
          % ((free, output, bare),),
          free == want and output == want
          and bare == "home is %s" % (M.OUTSIDE_TOKEN,)
          and not [f for f in fragments if f in free + output + bare])
    plain = "see docs/My Projects.md and src/a b/c.py"
    check("mp13 ALLOW twin for mp12: a repo-relative path holding a space is "
          "no machine root and is kept byte for byte: %r"
          % (M.redacted_free_text(repo, plain),),
          M.redacted_free_text(repo, plain) == plain)

    # The Windows shape, built on every OS: the home is named with a drive
    # and backslashes, and a posix-spelled home is named drive-less - the
    # spelling `abspath` rewrites with the current drive on Windows.
    for label, home, line in (
            ("backslash", "C:\\Users\\Some One",
             "read C:\\Users\\Some One\\My Projects\\proj\\notes.md ok"),
            ("drive-less", "/Users/Some One",
             "read /Users/Some One/My Projects/proj/notes.md ok")):
        known = M._known_roots(None, environ={"HOME": home})
        got = M.redacted_free_text(None, line, known=known)
        check("mp14 a home holding a space, spelled the Windows way (%s), is "
              "replaced whole: %r" % (label, got),
              got == "read %s ok" % (M.OUTSIDE_TOKEN,))

    # A relative spelling is no machine root: it would otherwise scrub that
    # substring out of ordinary repository text.
    ordinary = "see proj/sub/notes.md and rel dir/x.md"
    for rel in ("proj/sub", "rel dir", "proj\\sub"):
        known = M._known_roots(None, environ={"HOME": rel})
        kept = M.redacted_free_text(None, ordinary, known=known)
        check("mp15 a RELATIVE home spelling (%r) adds no known root and "
              "leaves ordinary text alone: %r" % (rel, kept),
              kept == ordinary
              and not [r for r in known if r[0] in ("proj/sub", "rel dir")])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__machine_paths.py --selftest\n")
    raise SystemExit(2)
