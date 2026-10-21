#!/usr/bin/env python3
"""
The cases for `repair-tests-add.py` — the DOOR of the `tests.add` migration.

`test__manifest_phases.py` tests what a repairable entry MEANS — which token may
be read out of a sentence, and which may not. This tests the command: exit codes,
what it writes, what it refuses to touch, and where the record lands.

THE EXIT CODE ANSWERS ONE QUESTION IN BOTH MODES — *does every graded entry name
a file now?* — which is why a successful `--apply` that leaves entries needing a
human still exits non-zero. A migration that reported success over a plan it had
only half repaired would be read as "done", and the half that cannot be done
mechanically is the half somebody has to be told about.

WHAT THE WRITE MUST NOT TOUCH IS ASSERTED, not assumed: `files`, the `fileIndex`
and a settled task's entries are all read back after `--apply`. The first two
belong to `/audit:task scope`, which re-derives them; the third describes work
already judged.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("repair-tests-add.py")

# The entry shapes, named once. LOOSE spells its path inside a sentence and is
# the only one a migration may touch; PROSE names no file at all and is what has
# to be handed back; NAMED is already in the documented shape.
LOOSE = "a case in tests/cart.spec.ts for two stacked percentage discounts"
FIXED = "tests/cart.spec.ts: " + LOOSE
PROSE = "the cart total is right with two stacked percentage discounts"
NAMED = "src/cart/total.ts: two stacked percentage discounts"


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _plan(tasks):
    return {"meta": {"version": 2},
            "fileIndex": {"src/cart/total.ts": ["P0.1"]},
            "phases": [{"id": "P0", "title": "t", "status": "in_progress",
                        "tasks": tasks}]}


def _task(tid, status, add, mode="tdd", files=None):
    return {"id": tid, "title": tid, "status": status,
            "files": list(files or []),
            "tests": {"mode": mode, "add": list(add),
                      "expectRedFirst": mode == "tdd", "gate": []}}


def _repo(tmp, name, manifest):
    """A real git repo holding `manifest` where the plugin expects to find one."""
    repo = os.path.join(tmp, name)
    os.makedirs(os.path.join(repo, "docs", "audit"))
    subprocess.run(["git", "init", "-q", repo], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test User")
    mpath = os.path.join(repo, "docs", "audit", "audit-plan.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return repo, mpath


def _read(mpath):
    with open(mpath, encoding="utf-8") as fh:
        return json.load(fh)


def _raw(mpath):
    with open(mpath, encoding="utf-8") as fh:
        return fh.read()


def _adds(mpath, tid):
    for phase in _read(mpath)["phases"]:
        for task in phase["tasks"]:
            if task["id"] == tid:
                return task["tests"]["add"]
    return None


def _journal_rows(repo):
    rows = []
    jdir = os.path.join(repo, "docs", "audit", "journal")
    for name in sorted(os.listdir(jdir)) if os.path.isdir(jdir) else []:
        with open(os.path.join(jdir, name), encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    return rows


# --- cases --------------------------------------------------------------------
def _cases(check):
    check("rt0 no arguments is a usage error, not an accidental clean report",
          M.main([]) == 2)
    check("rt1 an unreadable manifest is 2 - never a fall-through to 'every "
          "entry names a file', which is what a clean exit would claim",
          M.main(["/no/such/manifest.json"]) == 2)

    tmp = _harness.fixture_root("qg-repair-tests-add-")
    try:
        repo, mpath = _repo(tmp, "mixed", _plan([
            _task("P0.1", "pending", [LOOSE, PROSE, NAMED],
                  files=["src/cart/total.ts"]),
            # SETTLED, carrying the same unrepairable entry: the exemption is
            # part of the rule rather than a carve-out, because a settled task's
            # entries describe work already judged.
            _task("P0.2", "done", [LOOSE, PROSE]),
            # A behaviour-preserving task, where the field is free prose and
            # always was.
            _task("P0.3", "pending", [PROSE], mode="regression")]))
        before = _raw(mpath)

        out, code = _harness._capture(M.main, [mpath])
        check("rt2 report mode exits 1 when anything is owed, and writes "
              "NOTHING - the default has to be safe to run anywhere, including "
              "against a plan somebody else is mid-run on",
              code == 1 and _raw(mpath) == before, repr(code))
        check("rt3 ...and the report tells the two apart: the rewritable entry "
              "is shown as was/now so the operator reads the change before "
              "approving it, and the one naming no file is handed back with the "
              "reason it cannot be done mechanically. One remedy printed for "
              "both classes would be the wrong advice for one of them",
              "REWRITABLE:" in out and "was: " + LOOSE in out
              and "now: " + FIXED in out
              and "FOR A HUMAN:" in out and "names no file at all" in out,
              out[:200])
        check("rt3b ...and the settled task is in NEITHER list, so a migration "
              "cannot rewrite the description of work that has already been "
              "graded: %r" % ([l for l in out.splitlines() if "P0.2" in l],),
              "P0.2" not in out and "P0.3" not in out)

        _applied_out, code = _harness._capture(M.main, [mpath, "--apply"])
        check("rt4 --apply rewrites ONLY the entry that already spelled its "
              "path, in place, leaving its neighbours byte-identical - the "
              "unrepairable one and the one already in the shape both stay "
              "exactly as they were: %r" % (_adds(mpath, "P0.1"),),
              _adds(mpath, "P0.1") == [FIXED, PROSE, NAMED])
        check("rt4b ...and the run that WROTE says so in the past tense, while "
              "report mode says REWRITABLE. A row that did not move must never "
              "be printed as one that did, and the same render serves both "
              "modes: %r"
              % ([l for l in _applied_out.splitlines() if "P0.1" in l],),
              "REWROTE  P0.1" in _applied_out
              and "REWRITABLE:" not in _applied_out)
        check("rt5 SECOND-DIRECTION CASE: the DONE task's entries are untouched "
              "by the same run, including the one that WAS repairable - the "
              "exemption is the validator's own filter, asked rather than "
              "restated, so the migration cannot reach an entry nothing "
              "complained about: %r" % (_adds(mpath, "P0.2"),),
              _adds(mpath, "P0.2") == [LOOSE, PROSE])
        check("rt5b ...and so is the regression task's, for the same reason one "
              "layer over: the shape is required of a tdd task because the "
              "`files` union promises commit-scope a path there, and free prose "
              "is what most entries of the other modes are: %r"
              % (_adds(mpath, "P0.3"),),
              _adds(mpath, "P0.3") == [PROSE])
        check("rt6 ...and the run still exits 1, because an entry naming no "
              "file is left: the exit code answers the same question in both "
              "modes - does every graded entry name a file NOW - and a "
              "migration reporting success over a plan it half repaired reads "
              "as done", code == 1, repr(code))
        idx = _read(mpath)
        check("rt7 `files` and the fileIndex are NOT touched by the write. They "
              "are re-derived by `/audit:task scope`, which is their one "
              "writer, and a second writer of the index is how two writers come "
              "to disagree about it: %r"
              % ((idx["fileIndex"], idx["phases"][0]["tasks"][0]["files"]),),
              idx["fileIndex"] == {"src/cart/total.ts": ["P0.1"]}
              and idx["phases"][0]["tasks"][0]["files"] == ["src/cart/total.ts"])

        rows = _journal_rows(repo)
        det = (rows[0].get("details") or {}) if rows else {}
        check("rt8 the journal row lands in <repo>/docs/audit/journal and "
              "CARRIES the entry on both sides. Asserting 'it journaled' passes "
              "over a row whose details block was dropped as unknown keys, "
              "which is a write that succeeded and recorded nothing: %r"
              % (det,),
              len(rows) == 1 and rows[0].get("action") == "scope.repair"
              and [(c.get("id"), c.get("field")) for c in det.get("changes") or []]
              == [("P0.1", "tests.add")])
        check("rt8b ...and the row's summary names the task, so the trail is "
              "readable without opening the manifest it describes: %r"
              % (rows[0].get("summary") if rows else None,),
              rows and "P0.1" in (rows[0].get("summary") or ""))

        again = _harness._capture(M.main, [mpath, "--apply"])[1]
        check("rt9 a second --apply changes nothing: the rewritten entry now "
              "opens with a path, so the rule reads it as done rather than "
              "prefixing it again - a migration that is not idempotent cannot "
              "be run over a plan whose state nobody is sure of: %r"
              % (_adds(mpath, "P0.1"),),
              again == 1 and _adds(mpath, "P0.1") == [FIXED, PROSE, NAMED])

        _clean_repo, clean = _repo(tmp, "clean", _plan([
            _task("P0.1", "pending", [NAMED], files=["src/cart/total.ts"])]))
        out, code = _harness._capture(M.main, [clean])
        check("rt10 a plan whose graded entries all name a file exits 0 and "
              "says so - a rule that fires on the shape it is asking for is a "
              "rule somebody routes around",
              code == 0 and out.startswith("OK:"), out[:120])

        _quiet_repo, quiet = _repo(tmp, "quiet", _plan([
            _task("P0.1", "pending", [PROSE], mode="regression")]))
        out, code = _harness._capture(M.main, [quiet])
        check("rt11 ...and a plan the rule REACHED NOTHING IN says that "
              "instead. A body of behaviour-preserving work has no graded entry "
              "at all, and a reader who cannot tell that from 'they all name a "
              "file' has read an unasked question as a good answer",
              code == 0 and out.startswith("NOTHING GRADED:"), out[:120])

        # --- the two refusals, which must not be one sentence ---
        _broken = _plan([_task("P0.1", "pending", [LOOSE], files=["src/x.ts"])])
        _broken_repo, bpath = _repo(tmp, "broken", _broken)
        _bbefore = _raw(bpath)
        out, code = _harness._capture(M.main, [bpath, "--apply"])
        check("rt13 a plan that was ALREADY invalid is refused before anything "
              "is touched, and the message says the repair is not what broke "
              "it. 'the result would be invalid' over a plan that arrived that "
              "way sends the operator hunting for a bug in the migration: %r"
              % (out.strip()[:120],),
              code == 1 and _raw(bpath) == _bbefore
              and "already has validator finding" in out
              and "src/x.ts" in out)

        _fresh_repo, fpath = _repo(tmp, "fresh", _plan([
            _task("P0.1", "pending", [LOOSE], files=["src/cart/total.ts"])]))
        _fbefore = _raw(fpath)
        _real_rewrite = M.rewrite

        def _corrupt(manifest, rows):
            # The guard's own subject, since nothing this command legitimately
            # writes can invalidate a plan: it puts a STRING into a free-prose
            # array. A check that can only ever be seen passing is asserting
            # nothing, so the rewriter is replaced with one that breaks the
            # document and the refusal is read off the result.
            manifest["phases"][0]["tasks"][0]["status"] = "nonsense"
            return _real_rewrite(manifest, rows)

        try:
            M.rewrite = _corrupt
            out, code = _harness._capture(M.main, [fpath, "--apply"])
        finally:
            M.rewrite = _real_rewrite
        check("rt14 ...and a rewrite that WOULD break the plan is refused after "
              "the mutation and before the save, with the other sentence - the "
              "manifest on disk is byte-identical, so a refusal never leaves a "
              "half-repaired plan behind: %r" % (out.strip()[:120],),
              code == 1 and _raw(fpath) == _fbefore
              and "would have made the plan invalid" in out)
        check("rt14b ...and with the rewriter put back, the same plan is "
              "repaired - which is what proves the case above failed on the "
              "guard rather than on a fixture that could never be written",
              _harness._capture(M.main, [fpath, "--apply"])[1] == 0
              and _adds(fpath, "P0.1") == [FIXED])

        _moved = _plan([_task("P0.1", "pending", [PROSE, LOOSE])])
        _stale = [{"taskId": "P0.1", "index": 0,
                   "verdict": M._rules.REPAIR_REWRITE,
                   "entry": LOOSE, "replacement": FIXED}]
        _landed = M.rewrite(_moved, _stale)
        check("rt15 a row whose entry is no longer at the index it names writes "
              "NOTHING. The rows are read off the same document, so the index "
              "is right - but it is right only while nothing has moved, and a "
              "write that trusted it would replace a different entry with this "
              "one's text: %r"
              % (_moved["phases"][0]["tasks"][0]["tests"]["add"],),
              _landed == []
              and _moved["phases"][0]["tasks"][0]["tests"]["add"]
              == [PROSE, LOOSE])

        out, code = _harness._capture(M.main, [mpath, "--json"])
        payload = json.loads(out)
        check("rt12 --json is available in report mode, does not change the "
              "verdict, and carries the two classes under their own keys - a "
              "machine reader that had to parse the prose above would break on "
              "the first rewording: %r" % (sorted(payload),),
              code == 1 and payload["applied"] is False
              and payload["rewrite"] == []
              and [r["taskId"] for r in payload["owed"]] == ["P0.1"]
              and payload["graded"] == 3)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_repair_tests_add.py --selftest\n")
    raise SystemExit(2)
