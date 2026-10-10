#!/usr/bin/env python3
"""
The cases for `_wave.py` - which ready tasks may run together, and what an
overlap between two of them is.

Every case is pure data in, data out: no repository, no temp directory. Fixtures
are chosen so the wrong implementation disagrees with the right one - `w4` uses a
sibling that shares only a name prefix (`src` vs `src-old/`), which a
`startswith` without the separator would call an overlap, and `w6` is the
quiet-tree direction for the lockfile class (an ordinary overlap must NOT be
non-mergeable).

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _wave as M                                  # noqa: E402


def _t(tid, *files):
    return {"id": tid, "files": list(files)}


def _select_cases(check):
    two = [_t("P1.1", "src/a.py"), _t("P1.2", "src/b.py")]
    got = M.select(two, 2)
    check("w1 two disjoint ready tasks at width 2 are ONE wave of two: %r"
          % (got,), got["wave"] == ["P1.1", "P1.2"] and got["deferred"] == [])

    one = M.select(two, 1)
    check("w2 width 1 is today's path - the first task in order, alone, the "
          "other deferred and named as waiting on width: %r" % (one,),
          one["wave"] == ["P1.1"]
          and [d["id"] for d in one["deferred"]] == ["P1.2"]
          and one["deferred"][0]["reason"] == "width")

    lone = M.select([_t("P1.1"), _t("P1.2", "src/b.py")], 3)
    check("w3 a task with empty `files` runs ALONE even when width allows more, "
          "because it cannot be proved disjoint: %r" % (lone,),
          lone["wave"] == ["P1.1"]
          and lone["deferred"][0]["reason"] == "undeclared")

    after = M.select([_t("P1.1", "src/a.py"), _t("P1.2"),
                      _t("P1.3", "src/c.py")], 3)
    check("w3b an empty-files task met AFTER a chosen one is deferred, and a "
          "later disjoint task still joins - skipping is not stopping: %r"
          % (after,),
          after["wave"] == ["P1.1", "P1.3"]
          and after["deferred"][0]["id"] == "P1.2")

    nest = M.select([_t("P1.1", "src"), _t("P1.2", "src/deep/x.py:10-20"),
                     _t("P1.3", "src-old/y.py")], 3)
    check("w4 a directory entry covers its subpath (a `:line` suffix is "
          "dropped) and a sibling sharing only a name prefix does not: %r"
          % (nest,),
          nest["wave"] == ["P1.1", "P1.3"]
          and nest["deferred"][0]["id"] == "P1.2"
          and nest["deferred"][0]["with"] == "P1.1"
          and nest["deferred"][0]["reason"] == "overlap")

    check("w4b nothing ready is an EMPTY wave that says so, not a wave of "
          "nobody: %r" % (M.select([], 2),),
          M.select([], 2) == {"wave": [], "deferred": []})

    refused = []
    for bad in (0, -1, None, "auto", True):
        try:
            M.select(two, bad)
            refused.append(False)
        except ValueError:
            refused.append(True)
    check("w4c a width that is not an integer of at least 1 is refused loudly - "
          "'auto' is resolved by the caller, and a 0 must not read as 'run "
          "nothing, successfully': %r" % (refused,), all(refused))


def _overlap_cases(check):
    a, b = _t("P1.1", "src/app.py"), _t("P1.2", "src", "docs/x.md")
    hit = M.overlap(a, b)
    check("w5 an overlap NAMES BOTH TASKS and the path both reach (the more "
          "specific of the two entries): %r" % (hit,),
          hit is not None and hit["tasks"] == ["P1.1", "P1.2"]
          and hit["paths"] == ["src/app.py"])

    check("w5b ...and order of arguments changes neither the pair's id order "
          "nor the paths: %r" % (M.overlap(b, a),),
          M.overlap(b, a) == hit)

    check("w5c disjoint tasks overlap in nothing - None, not an empty record: "
          "%r" % (M.overlap(_t("P1.1", "a.py"), _t("P1.2", "b.py")),),
          M.overlap(_t("P1.1", "a.py"), _t("P1.2", "b.py")) is None)

    plain = M.overlap(_t("P1.1", "src/app.py"), _t("P1.2", "src/app.py"))
    check("w6 an ordinary shared file is mergeable (the quiet direction for "
          "the lockfile class): %r" % (plain,),
          plain is not None and plain["mergeable"] is True)

    lock = M.overlap(_t("P1.1", "web/pnpm-lock.yaml", "a.py"),
                     _t("P1.2", "web/pnpm-lock.yaml"))
    check("w7 a lockfile overlap is NON-MERGEABLE and still names both "
          "tasks: %r" % (lock,),
          lock is not None and lock["mergeable"] is False
          and lock["tasks"] == ["P1.1", "P1.2"]
          and lock["nonMergeable"] == ["web/pnpm-lock.yaml"])

    mixed = M.overlap(_t("P1.1", "a.py", "Cargo.lock"),
                      _t("P1.2", "a.py", "Cargo.lock"))
    check("w7b one lockfile among ordinary shared paths makes the whole "
          "overlap non-mergeable, and says which path did: %r" % (mixed,),
          mixed["mergeable"] is False
          and mixed["paths"] == ["Cargo.lock", "a.py"]
          and mixed["nonMergeable"] == ["Cargo.lock"])

    check("w7c a task with no declared files overlaps nothing it can name - "
          "None here, because `select` is what keeps it alone: %r"
          % (M.overlap(_t("P1.1"), _t("P1.2", "a.py")),),
          M.overlap(_t("P1.1"), _t("P1.2", "a.py")) is None)


def _cases(check):
    _harness.stage(check, "ws", _select_cases)
    _harness.stage(check, "wo", _overlap_cases)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__wave.py --selftest\n")
    raise SystemExit(2)
