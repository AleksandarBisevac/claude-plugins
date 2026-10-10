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

        home = "/Users/someone/work/secret/run.py"
        row = {"steps": [{"command": "python3 " + home, "note": "ran " + home}]}
        kept = M.scrubbed_values(repo, row, keep=frozenset(["command"]))
        plain = M.scrubbed_values(repo, row)
        check("mp8 a field NAMED in `keep` is the one value a reader compares "
              "back and passes through byte for byte at any depth, while a "
              "sibling free-text field is still scrubbed, and with nothing "
              "kept both are scrubbed: %r" % ((kept, plain),),
              kept["steps"][0]["command"] == row["steps"][0]["command"]
              and home not in kept["steps"][0]["note"]
              and home not in json.dumps(plain)
              and row["steps"][0]["note"].endswith(home))

        check("mp7 the journal re-exports the SAME objects, so the detector "
              "tool and every old caller judge by one pattern set",
              _journal_io.MACHINE_PATH_SHAPES is M.MACHINE_PATH_SHAPES
              and _journal_io.machine_path_shape is M.machine_path_shape
              and _journal_io.redacted_free_text is M.redacted_free_text
              and _journal_io.OUTSIDE_TOKEN == M.OUTSIDE_TOKEN
              and _journal_io.canonical is M.canonical)
    finally:
        _harness.remove_tree(proj)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__machine_paths.py --selftest\n")
    raise SystemExit(2)
