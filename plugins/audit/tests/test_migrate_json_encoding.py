#!/usr/bin/env python3
"""
The cases for `migrate-json-encoding.py` — one manifest's files brought to the one
escaping, or nothing written at all.

`migrate-json-encoding.py` is hyphenated, so it comes through `_loader.load_script`
and this file substitutes underscores; `test_set_priority.py` is the precedent for
both halves of that rule. Every fixture lives under one `tempfile.mkdtemp()` removed
in a single `finally`.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The escaped file is rewritten and the character survives.** Both halves are
  asserted, because they fail apart: a writer that dropped the character would
  satisfy "no escape sequence is left" on its own.
- **A file already in the encoding is not rewritten, and is REPORTED.** "There was
  nothing to do" and "it never looked" are different answers, and a report that
  printed only what it changed would spell them the same way.
- **One unreadable file refuses the WHOLE pass**, with the readable siblings left
  byte for byte as they were. A half-migrated manifest is worse than an
  un-migrated one, and the case asserts the sibling's bytes rather than its exit
  code, because a command that wrote the sibling and then reported a refusal would
  pass an exit-code-only check.
- **A manifest with findings is refused BEFORE the save.** This command changes no
  value, so re-spelling a broken document only makes the break harder to read.
- **A `shard` value pointing outside the index's own directory is refused by name
  and the file it names is untouched.** The manifest is a document a project may
  have hand-edited; following a path out of it would turn this into a writer of
  somebody else's files.
- **`--dry-run` writes nothing** and still names every class.

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

M = _loader.load_script("migrate-json-encoding.py",
                        modname="migrate_json_encoding")

# The two characters the incident was about: an em dash in a title, and a curly
# apostrophe. Both are outside ASCII, so the two families spell them differently
# and a case can tell which one wrote the file.
DASH = u"—"
QUOTE = u"’"


def _base_manifest():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P1", "title": "One " + DASH + " the first",
             "status": "pending",
             "tasks": [{"id": "P1.1", "title": "a", "status": "pending"}]},
            {"id": "P2", "title": "Two" + QUOTE + "s turn", "status": "pending",
             "tasks": [{"id": "P2.1", "title": "b", "status": "pending"}]},
        ],
    }


def _write_escaped(path, obj):
    """The OTHER family, written the way the tree found it: escaped ASCII, the
    same indent and the same trailing newline, so the only difference between a
    migrated file and this one is the escaping."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, indent=2, ensure_ascii=True) + "\n")


# --- cases --------------------------------------------------------------------
# Letters taken in this file (NEW file -- fresh letter space): m (the migration),
# n (nothing to do), r (refusals), b (bounds: what this command will not follow),
# d (--dry-run and --json).
def _cases(check):
    root = tempfile.mkdtemp(prefix="migrate-json-encoding-selftest-")

    def project(manifest=None, escaped=True):
        """A sharded project whose files are in the OTHER family by default."""
        d = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(d, ".claude"))
        os.makedirs(os.path.join(d, "docs", "audit"))
        mpath = os.path.join(d, "docs", "audit", "audit-plan.json")
        data = manifest if manifest is not None else _base_manifest()
        written = _mio.save_sharded(mpath, data)
        if escaped:
            for path in written:
                _write_escaped(path, _mio.read_json(path))
        return d, mpath, written

    def run(argv):
        lines = []
        code = M.main(argv, out=lines.append)
        return code, "\n".join(lines)

    def text(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    try:
        # --- the migration ----------------------------------------------------
        _d, mp, written = project()
        shard = [p for p in written if p.endswith("P1.json")][0]
        check("m1 the file starts in the OTHER family - without this the rest of "
              "the block would pass against a fixture that needed no migration",
              "\\u2014" in text(shard), text(shard)[:120])
        code, out = run([mp])
        check("m2 the pass reports done and NAMES the file it rewrote",
              code == 0 and "rewrote" in out and "P1.json" in out,
              "%r %r" % (code, out))
        check("m3 ...the escape sequence is gone AND the character is there. Two "
              "halves because they fail apart: a writer that dropped the "
              "character would satisfy the first on its own",
              "\\u2014" not in text(shard) and DASH in text(shard),
              text(shard)[:200])
        check("m4 ...and the manifest still reads back with the same values - a "
              "re-encoding that changed a value would be a data migration, which "
              "this is not",
              _mio.load_manifest(mp)["phases"][0]["title"]
              == "One " + DASH + " the first",
              repr(_mio.load_manifest(mp)["phases"][0]["title"]))
        check("m5 ...and a second run has nothing to do, which is what makes the "
              "pass safe to re-run rather than a thing to do once",
              run([mp])[1].count("rewrote") == 0, run([mp])[1])

        # --- nothing to do ----------------------------------------------------
        _d, mp, written = project(escaped=False)
        code, out = run([mp])
        check("n1 a tree already in the encoding exits 0, writes nothing, and "
              "REPORTS every file as already there - a report that printed only "
              "changes would spell 'nothing to do' and 'it never looked' the same",
              code == 0 and "rewrote" not in out
              and len([ln for ln in out.splitlines()
                       if ln.startswith("  already in the encoding:")])
              == len(written),
              "%r %r" % (code, out))

        # --- refusals ---------------------------------------------------------
        _d, mp, written = project()
        victim = [p for p in written if p.endswith("P2.json")][0]
        survivor = [p for p in written if p.endswith("P1.json")][0]
        before = text(survivor)
        with open(victim, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        code, out = run([mp])
        check("r1 one unreadable file refuses the WHOLE pass and names it",
              code == 1 and "REFUSED" in out and "P2.json" in out,
              "%r %r" % (code, out))
        check("r2 ...and its readable sibling is byte-for-byte untouched. "
              "Asserted on the BYTES and not on the exit code: a version that "
              "rewrote the siblings and then reported the refusal would pass an "
              "exit-code check and leave a half-migrated manifest behind",
              text(survivor) == before, text(survivor)[:120])

        broken = _base_manifest()
        broken["phases"][1]["id"] = "P1"          # duplicate id: a finding
        _d, mp, written = project(manifest=broken)
        escaped_before = dict((p, text(p)) for p in written)
        inode_before = dict((p, os.stat(p).st_ino) for p in written)
        code, out = run([mp])
        check("r3 a manifest with findings is refused, and the findings are "
              "printed rather than summarised away",
              code == 1 and "FINDING:" in out, "%r %r" % (code, out))
        check("r4 ...and nothing is KEPT, so the repair diff is the repair and "
              "not the repair plus a re-spelling of every line",
              all(text(p) == escaped_before[p] for p in written))

        # THE BYTES CANNOT TELL THE TWO REFUSALS APART, AND THAT IS WHY THIS CASE
        # EXISTS. There are two: one before the save, and one after it that rolls
        # every file back. Remove the first and the second still catches this
        # manifest, still exits 1, still prints `FINDING:`, and still leaves every
        # file byte-for-byte as it was -- so r3 and r4 both pass over a command
        # that wrote the whole manifest and took it back. What separates them is
        # WHICH refusal ran: its own line, and the files never having been
        # replaced at all. `atomic_write_json` and the rollback both land through
        # `os.replace`, so an inode that has not moved is a file nothing wrote.
        _r5_probe = os.path.join(root, "inode-probe.json")
        _mio.atomic_write_json(_r5_probe, {"n": 1}, indent=2)
        _r5_ino = os.stat(_r5_probe).st_ino
        _mio.atomic_write_json(_r5_probe, {"n": 2}, indent=2)
        _r5_moves = os.stat(_r5_probe).st_ino != _r5_ino
        check("r5 ...and the refusal that ran is the one BEFORE the save: its "
              "own line, no rollback line, and not one owned file replaced. The "
              "inode half carries its own floor - a filesystem that cannot tell "
              "a replace apart makes this case red rather than vacuously green: "
              "%r / %r" % (_r5_moves, out[:160]),
              _r5_moves
              and "the manifest has findings, and nothing was written" in out
              and "does not validate" not in out
              and all(os.stat(p).st_ino == inode_before[p] for p in written))

        # --- what it will not follow ------------------------------------------
        _d, mp, written = project()
        outsider = os.path.join(_d, "not-mine.json")
        # A VALID phase body, so the assembled manifest still validates and this
        # case is about the bound alone. A body that made the manifest invalid
        # would be caught by the findings refusal above and prove nothing here.
        _write_escaped(outsider, {"id": "P1", "title": "Outside " + DASH,
                                  "status": "pending",
                                  "tasks": [{"id": "P1.1", "title": "a",
                                             "status": "pending"}]})
        index = _mio.read_json(mp)
        index["phases"][0]["shard"] = "../../not-mine.json"
        _write_escaped(mp, index)
        outsider_before = text(outsider)
        code, out = run([mp])
        check("b1 a shard path climbing out of the index's own directory is "
              "REFUSED by name rather than followed",
              code == 0 and "not mine" in out and "../../not-mine.json" in out,
              "%r %r" % (code, out))
        check("b2 ...and the file it named is untouched. This is the case that "
              "separates 'migrate the manifest I was pointed at' from 'rewrite "
              "whatever a handed-in path resolves to'",
              text(outsider) == outsider_before, text(outsider)[:120])

        # --- dry run ----------------------------------------------------------
        _d, mp, written = project()
        before = dict((p, text(p)) for p in written)
        code, out = run([mp, "--dry-run"])
        check("d1 --dry-run reports what it WOULD rewrite",
              code == 0 and "would rewrite" in out, "%r %r" % (code, out))
        check("d2 ...and writes nothing at all",
              all(text(p) == before[p] for p in written))
        code, out = run([mp, "--dry-run", "--json"])
        payload = json.loads(out[out.index("{"):])
        check("d3 the --json payload carries the SAME four lists the human "
              "report renders, so the two cannot disagree about what happened: %r"
              % (sorted(payload.get("view", {}).keys()),),
              payload["applied"] is False and payload["dryRun"] is True
              and sorted(payload["view"].keys())
              == ["already", "refused", "rewrite", "unreadable"],
              out)

        # --- usage ------------------------------------------------------------
        code, out = run([os.path.join(root, "no-such-manifest.json")])
        check("d4 a manifest that is not there is a usage error, not a refusal - "
              "the two exit codes route differently for a caller",
              code == 2 and "not found" in out, "%r %r" % (code, out))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_migrate_json_encoding.py --selftest\n")
    raise SystemExit(2)
