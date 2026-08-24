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

import contextlib
import io
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

        # --- the flag surface: it must FAIL CLOSED --------------------------
        # `parse_args` needs no manifest on disk, which is why it is a function; the
        # `cli*` cases below then drive the same refusals through `main()` against a
        # real tree, because "exit non-zero" and "wrote nothing" are two claims.
        check("flg1 no --to means sharded, so every invocation written before the "
              "reverse existed still means what it meant",
              M.parse_args(["m.json"])[0]["to"] == "sharded")
        check("flg2 --to takes its value with an = sign, the one spelling `--out` "
              "already used and the one the command docs invoke",
              M.parse_args(["m.json", "--to=single-file"])[0]
              == {"path": "m.json", "to": "single-file", "dry_run": False,
                  "force": False, "renumber": False, "out": None})
        check("flg3 a SPACE-separated value is refused by name, not absorbed - a "
              "parser consuming the next argv entry turns `--to <plan>` into an "
              "argument about a missing positional instead of about the flag",
              M.parse_args(["m.json", "--to", "single-file"])[0] is None
              and "= sign" in M.parse_args(["m.json", "--to", "single-file"])[1])
        check("flg4 a misspelled LAYOUT is refused, never defaulted - defaulting "
              "would convert the manifest the opposite way from the one asked for",
              M.parse_args(["m.json", "--to=shraded"])[0] is None
              and "shraded" in M.parse_args(["m.json", "--to=shraded"])[1])
        check("flg5 an unknown FLAG is refused too. THE ORIGINAL DEFECT: the old "
              "parser collected a set and looked only for the three it knew, so "
              "`--dryrun` was dropped and the run MIGRATED FOR REAL and said so",
              M.parse_args(["m.json", "--dryrun"])[0] is None
              and M.parse_args(["m.json", "--single-file"])[0] is None)
        check("flg6 ...and every refusal lists what IS accepted, so the message is "
              "a repair and not just a rejection",
              all("--dry-run" in M.parse_args(["m.json", a])[1]
                  and "--to=" in M.parse_args(["m.json", a])[1]
                  for a in ("--dryrun", "--to", "--dry-run=no")))
        check("flg7 a bare flag given a value is an error - `--dry-run=no` reads "
              "as 'off' and would otherwise turn the run ON",
              M.parse_args(["m.json", "--dry-run=no"])[0] is None)
        check("flg8 the other three flags keep their meaning in both directions",
              M.parse_args(["m.json", "--to=single-file", "--dry-run", "--force",
                            "--renumber", "--out=/x/y.json"])[0]
              == {"path": "m.json", "to": "single-file", "dry_run": True,
                  "force": True, "renumber": True, "out": "/x/y.json"})
        check("flg9 exactly one positional, and the count is REPORTED - two paths "
              "silently taking the first is how the wrong file gets converted",
              M.parse_args([])[0] is None and M.parse_args(["a", "b"])[0] is None)
        check("flg10 the layout names come off `_manifest_io.LAYOUT_VERSION`, so a "
              "layout added to the writer cannot be missing from the flag",
              M.layout_names() == sorted(_mio.LAYOUT_VERSION))
        check("flg11 migrate() itself refuses an unknown layout with a usage code, "
              "not a crash - it is callable from a test and from a command",
              M.migrate(os.path.join(tmp, "nope.json"), to="bogus")[0] == 2)

        # --- and the refusal writes NOTHING, in either direction ---------------
        # Through `main()`, against a real tree, because an exit code says the run
        # stopped and only the tree says it stopped BEFORE writing. Both fixtures are
        # built from the real assembled shape rather than reused: a manifest that is
        # already in the requested layout is a no-op and would hide this entirely.
        def _tree(root):
            """{relative path: bytes} for a fixture directory, backups INCLUDED - a
            `.bak-<UTC>` appearing is itself proof that a refusal wrote."""
            out = {}
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    with open(full, "rb") as fh:
                        out[os.path.relpath(full, root)] = fh.read()
            return out

        def _refuses_untouched(where, root, path, argv):
            """Drive `main()` and return the tree afterwards. The two ids are the
            helper's own, one call site each, so a mutation is credited to the claim
            it broke rather than to whichever loop iteration ran first."""
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = M.main([path] + argv)
            check("cli3 %s source, %s: usage exit, not a run"
                  % (where, " ".join(argv)), code == 2,
                  "%s / %s" % (code, err.getvalue().strip()))
            check("cli4 %s source, %s: the message names the offending argument AND "
                  "the accepted set, so it is a repair and not just a rejection"
                  % (where, " ".join(argv)),
                  "accepted:" in err.getvalue()
                  and argv[-1].lstrip("-").split("=")[-1] in err.getvalue(),
                  err.getvalue().strip())
            return _tree(root)

        _clidir = os.path.join(tmp, "cli-single")
        os.makedirs(_clidir)
        _clip = os.path.join(_clidir, "audit-plan.json")
        with open(_clip, "w", encoding="utf-8") as fh:
            json.dump(_legacy(), fh)
        _clibefore = _tree(_clidir)
        for _argv in (["--dryrun"], ["--to=singlefile"], ["--to", "sharded"]):
            check("cli1 SINGLE-FILE source: %s leaves the tree byte-identical - no "
                  "phases/, no .bak-, no rewrite" % " ".join(_argv),
                  _refuses_untouched("single-file", _clidir, _clip, _argv)
                  == _clibefore, repr(sorted(_tree(_clidir))))

        _clidir2 = os.path.join(tmp, "cli-sharded")
        os.makedirs(_clidir2)
        _clip2 = os.path.join(_clidir2, "audit-plan.json")
        with open(_clip2, "w", encoding="utf-8") as fh:
            json.dump(_legacy(), fh)
        assert M.migrate(_clip2)[0] == 0
        _clibefore2 = _tree(_clidir2)
        for _argv in (["--to=single-file", "--dryrun"], ["--to=singlefile"],
                      ["--to", "single-file"]):
            check("cli2 SHARDED source: %s leaves the tree byte-identical - the "
                  "shards stay put and nothing is parked" % " ".join(_argv),
                  _refuses_untouched("sharded", _clidir2, _clip2, _argv)
                  == _clibefore2, repr(sorted(_tree(_clidir2))))
        check("cli5 SECOND-DIRECTION CASE: the same fixtures DO convert when the "
              "flags are spelled right, so cli1/cli2 are comparing a tree something "
              "is able to change rather than one nothing ever touches",
              M.main([_clip2, "--to=single-file"]) == 0
              and _tree(_clidir2) != _clibefore2)

        # --- sharded -> single-file, the reverse ------------------------------
        _rp = os.path.join(tmp, "rev", "audit-plan.json")
        os.makedirs(os.path.dirname(_rp))
        with open(_rp, "w", encoding="utf-8") as fh:
            json.dump(_legacy(), fh)
        check("rev1 forward first, so the reverse has a real sharded tree to read",
              M.migrate(_rp)[0] == 0)
        _rcode, _rmsg = M.migrate(_rp, to="single-file")
        check("rev2 reverse exit 0", _rcode == 0, _rmsg)
        _rraw = _mio.read_json(_rp)
        check("rev3 the result IS the single-file layout by the structural reading",
              _mio.layout_of(_rraw) == "single-file", repr(_rraw.get("phases")))
        check("rev4 ...and meta.version came back DOWN to name it. THE TWO READINGS "
              "AGREE: `is_sharded()` reads the stubs and /audit:doctor reads the "
              "version, and a file they disagree about has no layout at all",
              _mio.declared_layout(_rraw) == _mio.layout_of(_rraw),
              repr(_rraw.get("meta")))
        check("rev5 the round trip loses nothing AS DATA - single-file -> sharded -> "
              "single-file is the source manifest again, meta.version included",
              _rraw == _legacy(), json.dumps(_rraw, sort_keys=True))
        _rparked = [n for n in os.listdir(os.path.join(tmp, "rev"))
                    if n.startswith("phases.bak-")]
        check("rev6 the emptied shard directory is MOVED ASIDE, not deleted and not "
              "left looking live", len(_rparked) == 1
              and not os.path.isdir(os.path.join(tmp, "rev", "phases")),
              repr(sorted(os.listdir(os.path.join(tmp, "rev")))))
        # `_rparked` is guarded rather than indexed: with the version fix mutated out
        # the directory is never parked, and an IndexError here would take the whole
        # body down instead of letting rev6 and rev7 report separately.
        check("rev7 ...and every shard file is still in it - a rename cannot "
              "half-apply, which a delete-then-write can",
              bool(_rparked) and sorted(os.listdir(
                  os.path.join(tmp, "rev", _rparked[0]))) == ["P1.json", "P2.json"])
        check("rev8 a second reverse is a no-op, the same way a second forward is",
              M.migrate(_rp, to="single-file")[0] == 0
              and "already single-file" in M.migrate(_rp, to="single-file")[1])

        # --- the refusals, in the reverse direction too ----------------------
        _ip = os.path.join(tmp, "rev-inprogress", "audit-plan.json")
        os.makedirs(os.path.dirname(_ip))
        _im = _legacy()
        _im["phases"][1]["status"] = "in_progress"
        _im["phases"][1]["tasks"][0]["status"] = "in_progress"
        with open(_ip, "w", encoding="utf-8") as fh:
            json.dump(_im, fh)
        M.migrate(_ip, force=True)
        _icode, _imsg = M.migrate(_ip, to="single-file")
        check("ref1 in_progress refuses the REVERSE as well - a mid-run layout "
              "change corrupts the run whichever way it goes",
              _icode == 1 and "in_progress" in _imsg, _imsg)
        check("ref2 ...and --force overrides it in the reverse too",
              M.migrate(_ip, to="single-file", force=True)[0] == 0)
        _ep = os.path.join(tmp, "no-phases", "audit-plan.json")
        os.makedirs(os.path.dirname(_ep))
        with open(_ep, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": []}, fh)
        _ecode, _emsg = M.migrate(_ep)
        check("ref3 a manifest with no phase to shard is REFUSED, not stamped: a "
              "split with nothing to point at writes the sharded version onto a "
              "file every consumer reads as single-file",
              _ecode == 1 and "nothing to" in _emsg, _emsg)
        check("ref4 ...and the file was not touched by the refusal",
              _mio.declared_layout(_mio.read_json(_ep)) == "single-file")
        # ref5-ref8: two phase ids that sanitise to one shard FILENAME. This is
        # data loss, not an odd name - the second body overwrites the first and
        # `load_manifest` then returns the surviving phase twice, so the count of
        # phases is unchanged and nothing looks wrong. `P/9` and `P_9` differ in
        # exactly the character `_manifest_io._shard_name` collapses, so a fix
        # that trimmed or lowercased instead would still fail here.
        _cp = os.path.join(tmp, "shard-collision", "audit-plan.json")
        os.makedirs(os.path.dirname(_cp))
        _cman = _legacy()
        _cman["phases"][0]["id"] = "P/9"
        _cman["phases"][0]["tasks"][0]["id"] = "P/9.1"
        _cman["phases"][1]["id"] = "P_9"
        _cman["phases"][1]["tasks"][0]["id"] = "P_9.1"
        _cman["phases"][1]["tasks"][0]["dependsOn"] = ["P/9.1"]
        _cman["fileIndex"] = {"src/a.ts": ["P/9.1"], "src/b.ts": ["P_9.1"]}
        _cman["bugs"][0]["taskId"] = "P_9.1"
        with open(_cp, "w", encoding="utf-8") as fh:
            json.dump(_cman, fh)
        _ccode, _cmsg = M.migrate(_cp)
        check("ref5 the forward direction REFUSES the pair, naming both ids and "
              "the one file they would share",
              _ccode == 1 and "P/9" in _cmsg and "P_9" in _cmsg
              and "phases/P_9.json" in _cmsg, _cmsg)
        check("ref6 ...and wrote nothing: no shard directory, and the source is "
              "still the single file it was",
              not os.path.exists(os.path.join(os.path.dirname(_cp), "phases"))
              and _mio.layout_of(_mio.read_json(_cp)) == "single-file",
              repr(sorted(os.listdir(os.path.dirname(_cp)))))
        _dcode, _dmsg = M.migrate(_cp, dry_run=True)
        check("ref7 --dry-run refuses it too. A preview that listed the shard "
              "files and said nothing about two of them being one file would "
              "send the reader into the real run to discover it",
              _dcode == 1 and "P/9" in _dmsg, _dmsg)
        _ncp = os.path.join(tmp, "no-collision", "audit-plan.json")
        os.makedirs(os.path.dirname(_ncp))
        with open(_ncp, "w", encoding="utf-8") as fh:
            json.dump(_legacy(), fh)     # the SAME shape, ids left alone
        _nccode, _ncmsg = M.migrate(_ncp)
        check("ref8 SECOND-DIRECTION CASE: the same manifest with the ids left "
              "alone migrates. A refusal that fired on every sharded write would "
              "pass ref5-ref7 and stop the command working at all",
              _nccode == 0 and _mio.layout_of(_mio.read_json(_ncp)) == "sharded",
              _ncmsg)

        # --- --out leaves the source alone, in both directions ---------------
        _op = os.path.join(tmp, "out", "audit-plan.json")
        os.makedirs(os.path.dirname(_op))
        with open(_op, "w", encoding="utf-8") as fh:
            json.dump(_legacy(), fh)
        M.migrate(_op)
        _obytes = open(_op, "rb").read()
        _oelse = os.path.join(tmp, "out", "elsewhere.json")
        _ocode, _omsg = M.migrate(_op, to="single-file", out=_oelse)
        check("out1 --out writes the single file elsewhere and exits 0",
              _ocode == 0 and os.path.isfile(_oelse), _omsg)
        check("out2 ...leaving the source index byte-for-byte as it was",
              open(_op, "rb").read() == _obytes)
        check("out3 ...and its shards live, because nothing restores a source that "
              "was never written to - the message has to SAY so",
              os.path.isdir(os.path.join(tmp, "out", "phases"))
              and "still live" in _omsg, _omsg)

        # --- --renumber, in the reverse direction ----------------------------
        # Meaningful in BOTH directions, which is why it is not refused in one: the
        # source is assembled and validated either way, and the repair rides out with
        # the rest of the manifest. The fixture is a SHARDED manifest carrying the
        # duplicate, written by the writer rather than by a migration, so the reverse
        # is the first thing to see it.
        _np = os.path.join(tmp, "renumber-rev", "audit-plan.json")
        os.makedirs(os.path.dirname(_np))
        _nm = _legacy()
        _nm["bugs"].append({"id": "BUG-1", "title": "dup", "status": "open",
                            "taskId": "P1.1", "severity": "low"})
        _nm["phases"][0]["tasks"][0]["bugId"] = "BUG-1"
        _mio.save_sharded(_np, _nm)
        _ncode, _nmsg = M.migrate(_np, to="single-file")
        check("num1 the duplicate BUG- id is a FINDING, so the reverse refuses it "
              "and NAMES --renumber - the fixture really is broken",
              _ncode == 1 and "--renumber" in _nmsg, _nmsg)
        check("num2 ...and the refusal wrote nothing: the source is still sharded",
              _mio.layout_of(_mio.read_json(_np)) == "sharded")
        _ncode2, _nmsg2 = M.migrate(_np, to="single-file", renumber=True)
        check("num3 --renumber gets the REVERSE through too", _ncode2 == 0, _nmsg2)
        _nids = [b["id"] for b in _mio.read_json(_np)["bugs"]]
        check("num4 ...and the repaired ids really landed in the single file, which "
              "is the half a repair made only in memory would fail",
              len(set(_nids)) == len(_nids) == 2, repr(_nids))
        # Read through `.get`, not by indexing: if the reverse write ever stops
        # landing, this file is still the sharded INDEX whose stubs carry no `tasks`,
        # and a KeyError here would take the body down instead of failing this case.
        _ntask = (_mio.read_json(_np)["phases"][0].get("tasks") or [{}])[0]
        check("num5 ...along with the reciprocal task.bugId the repair rewrote",
              _ntask.get("bugId") == "BUG-2", repr(_ntask))

        # --- --dry-run writes nothing, in the reverse direction --------------
        _dp = os.path.join(tmp, "dry-rev", "audit-plan.json")
        os.makedirs(os.path.dirname(_dp))
        with open(_dp, "w", encoding="utf-8") as fh:
            json.dump(_legacy(), fh)
        M.migrate(_dp)
        _dbytes = open(_dp, "rb").read()
        _dcode, _dmsg = M.migrate(_dp, to="single-file", dry_run=True)
        check("dry1 the reverse dry run names the file it would write AND the "
              "directory it would move aside - a preview that showed only the "
              "write would leave the one alarming step unmentioned",
              _dcode == 0 and "DRY RUN" in _dmsg and "aside" in _dmsg, _dmsg)
        check("dry2 ...and it wrote nothing: the index is unchanged and the shards "
              "are still where they were",
              open(_dp, "rb").read() == _dbytes
              and os.path.isdir(os.path.join(tmp, "dry-rev", "phases")))

        # --- THE RESTORE PATH -------------------------------------------------
        # The case that matters most. A layout change that half-applies and then
        # reports failure has still corrupted the user's plan, so each injection below
        # breaks a different step of the reverse and every one of them has to leave
        # BYTE-IDENTICAL originals behind: the index as it was, every shard where it
        # was, and no parked directory.
        #
        # Each fixture is its own directory and each snapshot is taken from disk right
        # before the failing call, so a case cannot pass by comparing a value with
        # itself.
        def _snapshot(root):
            """{relative path: bytes} for a whole fixture tree, backups excluded.

            Bytes and not parsed JSON: "the original came back" is a claim about the
            file, and re-serializing would let a writer that reordered keys or changed
            the indent pass as a restore.
            """
            out = {}
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, root)
                    if ".bak-" in rel:
                        continue
                    with open(full, "rb") as fh:
                        out[rel] = fh.read()
            return out

        def _sharded_fixture(name):
            """A migrated, valid, sharded manifest in its own directory."""
            root = os.path.join(tmp, name)
            os.makedirs(root)
            path = os.path.join(root, "audit-plan.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(_legacy(), fh)
            code, msg = M.migrate(path)
            assert code == 0, msg
            return root, path

        class _FailsOnTheResult(object):
            """A validator that passes the SOURCE and fails the RESULT.

            The one failure the restore path exists for, and the only way to reach it:
            the corruption has to happen AFTER the write, which nothing outside the
            process can arrange. `calls` is asserted on, so a stub that was never
            reached cannot be mistaken for a stub that found nothing.
            """

            def __init__(self):
                self.calls = 0

            def validate(self, _manifest):
                self.calls += 1
                if self.calls == 1:
                    return [], []
                return ["injected: the result does not validate"], []

        _orig_validator = M._load_validator
        _orig_join = _mio.join_manifest
        _orig_retire = M._retire_shard_dir
        try:
            # r1. the result fails validation
            _r1root, _r1p = _sharded_fixture("restore-validate")
            _r1before = _snapshot(_r1root)
            _stub = _FailsOnTheResult()
            M._load_validator = lambda: _stub
            _r1code, _r1msg = M.migrate(_r1p, to="single-file")
            M._load_validator = _orig_validator
            check("rst1 a result that does not validate exits NON-ZERO - a failure "
                  "reported as success is the whole defect class",
                  _r1code == 1, "%s / %s" % (_r1code, _r1msg))
            check("rst2 ...and says it restored the backup, naming it",
                  "restored" in _r1msg and ".bak-" in _r1msg, _r1msg)
            check("rst3 ...and the injection really fired: the stub validated the "
                  "source AND the result, so rst1 is not passing for another reason",
                  _stub.calls == 2, repr(_stub.calls))
            check("rst4 THE ORIGINAL IS BACK BYTE-FOR-BYTE - index and every shard, "
                  "compared as bytes rather than as re-serialized data",
                  _snapshot(_r1root) == _r1before,
                  repr(sorted(_snapshot(_r1root))))
            check("rst5 ...so the manifest still reads as the layout it started in, "
                  "by BOTH readings of the layout",
                  _mio.layout_of(_mio.read_json(_r1p)) == "sharded"
                  and _mio.declared_layout(_mio.read_json(_r1p)) == "sharded")
            check("rst6 ...and the shard directory was never moved: a failure must "
                  "not leave the shard state half-changed",
                  os.path.isdir(os.path.join(_r1root, "phases"))
                  and not [n for n in os.listdir(_r1root)
                           if n.startswith("phases.bak-")],
                  repr(sorted(os.listdir(_r1root))))

            # r2. THE TRAP: the reverse write leaves `meta.version` naming the
            #     sharded layout. `is_sharded()` then reads single-file and
            #     /audit:doctor reads sharded, and nothing else in the pipeline
            #     would notice. This is the pre-fix reverse, put back on purpose.
            _r2root, _r2p = _sharded_fixture("restore-two-readings")
            _r2before = _snapshot(_r2root)

            def _join_leaving_the_version(manifest):
                out = _orig_join(manifest)
                out["meta"] = dict(out["meta"])
                out["meta"]["version"] = _mio.LAYOUT_VERSION["sharded"]
                return out

            _mio.join_manifest = _join_leaving_the_version
            _r2code, _r2msg = M.migrate(_r2p, to="single-file")
            _mio.join_manifest = _orig_join
            check("rst7 a write whose meta.version names the OTHER layout is caught "
                  "and refused, even though the document validates perfectly - the "
                  "validator is layout-blind by design",
                  _r2code == 1, "%s / %s" % (_r2code, _r2msg))
            check("rst8 ...and the message names WHICH reading disagreed, so the "
                  "failure is diagnosable rather than just red",
                  "meta.version" in _r2msg, _r2msg)
            check("rst9 ...and the original came back byte-for-byte here too",
                  _snapshot(_r2root) == _r2before)

            # r3. the shard-parking step fails. It is the LAST mutation and the only
            #     one the backup does not cover, so it has to be inside the try.
            _r3root, _r3p = _sharded_fixture("restore-retire")
            _r3before = _snapshot(_r3root)

            def _retire_that_fails(_raw_index, _index_path, _stamp):
                raise OSError("injected: cannot move the shard directory aside")

            M._retire_shard_dir = _retire_that_fails
            try:
                _r3code, _r3msg = M.migrate(_r3p, to="single-file")
            except Exception as _escaped:                          # noqa: BLE001
                # Not a passing outcome dressed as an error: with the parking moved
                # out of the try the exception escapes `migrate` entirely, and a
                # sentinel no case accepts is what makes rst10 report that rather
                # than the harness reporting "the body raised".
                _r3code, _r3msg = -1, "migrate() let it escape: %s" % (_escaped,)
            M._retire_shard_dir = _orig_retire
            check("rst10 a failure in the LAST step restores as well - the parking "
                  "runs inside the try, not after it",
                  _r3code == 1 and "restored" in _r3msg, "%s / %s" % (_r3code, _r3msg))
            check("rst11 ...and the shards are untouched, which is the state a "
                  "restored index has to point at",
                  _snapshot(_r3root) == _r3before
                  and os.path.isdir(os.path.join(_r3root, "phases")))

            # r4b. a failure under `--out`: there is nothing to restore, and saying
            #      "restored" there would be a claim about a file the run never wrote.
            _r4bp = os.path.join(tmp, "restore-out", "audit-plan.json")
            os.makedirs(os.path.dirname(_r4bp))
            with open(_r4bp, "w", encoding="utf-8") as fh:
                json.dump(_legacy(), fh)
            M.migrate(_r4bp)
            _r4bbytes = open(_r4bp, "rb").read()
            _stub_out = _FailsOnTheResult()
            M._load_validator = lambda: _stub_out
            _r4bcode, _r4bmsg = M.migrate(
                _r4bp, to="single-file",
                out=os.path.join(tmp, "restore-out", "elsewhere.json"))
            M._load_validator = _orig_validator
            check("rst14 a failed --out run exits non-zero and does NOT claim a "
                  "restore - the source was never written to",
                  _r4bcode == 1 and "restored" not in _r4bmsg, _r4bmsg)
            check("rst15 ...it says the output may be an incomplete write instead, "
                  "which is the thing a reader would otherwise have to find out",
                  "incomplete write" in _r4bmsg, _r4bmsg)
            check("rst16 ...and the source index really is untouched, byte for byte",
                  open(_r4bp, "rb").read() == _r4bbytes)

            # r4. SECOND-DIRECTION CASE. Every case above breaks something; this one
            #     breaks nothing, and it is the only one that fails if the restore
            #     ever becomes unconditional. It reads vacuous on purpose.
            _r4root, _r4p = _sharded_fixture("restore-not-taken")
            _r4before = _snapshot(_r4root)
            _r4code, _r4msg = M.migrate(_r4p, to="single-file")
            check("rst12 SECOND-DIRECTION CASE: a run with nothing injected does NOT "
                  "restore - it exits 0 and the manifest is the new single file",
                  _r4code == 0 and _mio.layout_of(_mio.read_json(_r4p)) == "single-file",
                  "%s / %s" % (_r4code, _r4msg))
            check("rst13 ...so the tree really changed, and rst4/rst9/rst11 are "
                  "comparing something a failed run puts back rather than something "
                  "no run ever moves",
                  _snapshot(_r4root) != _r4before)
        finally:
            M._load_validator = _orig_validator
            _mio.join_manifest = _orig_join
            M._retire_shard_dir = _orig_retire
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
