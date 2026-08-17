#!/usr/bin/env python3
"""
The cases for `migrate-manifest.py`, moved out of it - the entry-point shape.

The pilot that proves the naming rule has to exist. `migrate-manifest.py` is hyphenated,
which is this repo's mark of a thing something INVOKES rather than imports, and a hyphen
is not legal in a Python identifier: `import migrate-manifest` is a syntax error, and so
would be a test file called `test_migrate-manifest.py`. So the file name substitutes
underscores for hyphens (`test_migrate_manifest.py`) and the module itself comes through
`_loader.load_script`, which is the ONE way `scripts/` loads a sibling script as a library
and the only way anything in this tree reaches a hyphenated file at all.

`M` is the module under test - see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. Here it is not a preference: `load_script` hands back a module
object, so there is nothing else to spell.

`_manifest_io` is imported under its own name rather than reached as `M._mio`. The rule
across all of these: the module UNDER TEST is `M`, and every other production module a
case needs is imported the way production imports it, so a reader can tell at a glance
which names are the subject and which are the scenery.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402

M = _loader.load_script("migrate-manifest.py", modname="migrate_manifest")


# --- fixtures -----------------------------------------------------------------
def _legacy():
    """A minimal single-file manifest: two phases, a dependency across them, a
    fileIndex and one bug with a reciprocal `task.bugId`. Every field the migration
    has to carry through is present exactly once, so a lossy split shows up as an
    inequality rather than as a subtly smaller document."""
    return {
        "meta": {"version": 2, "repo": "demo"},
        "phases": [
            {"id": "P1", "title": "One", "status": "done",
             "tasks": [{"id": "P1.1", "title": "a", "status": "done", "files": ["src/a.ts"]}]},
            {"id": "P2", "title": "Two", "status": "pending",
             "tasks": [{"id": "P2.1", "title": "b", "status": "pending",
                        "dependsOn": ["P1.1"], "files": ["src/b.ts"], "bugId": "BUG-1"}]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["P2.1"]},
        "bugs": [{"id": "BUG-1", "title": "bug", "status": "in_progress", "taskId": "P2.1",
                  "severity": "high"}],
    }


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = tempfile.mkdtemp(prefix="migrate-selftest-")
    try:
        # 1. lossless in-place migration + backup + result validates
        p = os.path.join(tmp, "c1", "audit-plan.json")
        os.makedirs(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(_legacy(), fh)
        code, msg = M.migrate(p)
        check("migrate exit 0", code == 0, msg)
        check("index still at manifest path", os.path.isfile(p))
        check("shards written", os.path.isfile(os.path.join(tmp, "c1", "phases", "P1.json"))
              and os.path.isfile(os.path.join(tmp, "c1", "phases", "P2.json")))
        check("backup written", any(n.startswith("audit-plan.json.bak-")
              for n in os.listdir(os.path.join(tmp, "c1"))))
        reloaded = _mio.load_manifest(p)
        expect = _legacy()
        expect["meta"]["version"] = 3
        check("reload == source (modulo meta.version)", reloaded == expect)

        # 2. already-sharded is a no-op
        code2, msg2 = M.migrate(p)
        check("second migrate: already-sharded exit 0", code2 == 0 and "already sharded" in msg2)

        # 3. refuses on in_progress phase (unless --force)
        p3 = os.path.join(tmp, "c3", "audit-plan.json")
        os.makedirs(os.path.dirname(p3))
        m3 = _legacy()
        m3["phases"][1]["status"] = "in_progress"
        m3["phases"][1]["tasks"][0]["status"] = "in_progress"
        with open(p3, "w", encoding="utf-8") as fh:
            json.dump(m3, fh)
        code3, msg3 = M.migrate(p3)
        check("in_progress -> refused (exit 1)", code3 == 1 and "in_progress" in msg3)
        code3f, _ = M.migrate(p3, force=True)
        check("in_progress + --force -> migrates", code3f == 0)

        # 4. dry-run writes nothing
        p4 = os.path.join(tmp, "c4", "audit-plan.json")
        os.makedirs(os.path.dirname(p4))
        with open(p4, "w", encoding="utf-8") as fh:
            json.dump(_legacy(), fh)
        code4, msg4 = M.migrate(p4, dry_run=True)
        check("dry-run exit 0 + no phases dir", code4 == 0
              and not os.path.isdir(os.path.join(tmp, "c4", "phases")), msg4)

        # 5. --renumber repairs duplicate BUG- ids and fixes reciprocal links
        m5 = _legacy()
        m5["bugs"].append({"id": "BUG-1", "title": "dup", "status": "open",
                           "taskId": "P1.1", "severity": "low"})
        m5["phases"][0]["tasks"][0]["bugId"] = "BUG-1"
        changed = M.renumber_duplicate_bugs(m5)
        ids = [b["id"] for b in m5["bugs"]]
        check("renumber: duplicate BUG-1 -> distinct ids", len(set(ids)) == len(ids)
              and changed and changed[0][0] == "BUG-1")
        check("renumber: reciprocal task.bugId updated",
              m5["phases"][0]["tasks"][0]["bugId"] == changed[0][1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_migrate_manifest.py --selftest\n")
    raise SystemExit(2)
