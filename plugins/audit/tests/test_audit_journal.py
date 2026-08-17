#!/usr/bin/env python3
"""
The cases for `scripts/audit-journal.py`, moved out of it - an entry point.

`audit-journal.py` is hyphenated, so it comes through `_loader.load_script` and
the test file substitutes underscores; see `test_migrate_manifest.py` for both
halves of that rule. `M` is the module under test.

ONE EXPRESSION COULD NOT MOVE LITERALLY, AND IT IS THE DANGEROUS SHAPE.
`globals()["_git_anchor_finding"] = _counting_anchor` (k5-k8) swaps the
git-anchor check for a counting stub so the batched-porcelain claim can be
MEASURED - "tracked-and-clean files never pay the single-file check" is a claim
about how many times a function ran. From `tests/` the bare form binds a name
nothing reads: `verify()` looks the anchor up as a global of ITS OWN module, the
real one would go on running, and `_anchor_calls` would stay `[]` - which is
precisely what k5 asserts, so the case would have gone green while measuring
nothing at all. It is `M._git_anchor_finding`, restored on `M` in the same
`finally`. k6 is the case that fails loudly if the stub is ever not installed
(`_anchor_calls == [basename(gfile)]`), and both directions were proven red.

NOTHING ELSE ABOUT THIS SUITE DEPENDS ON WHERE IT SITS. It reads no source, names
no `__file__`, builds no path off its own directory, and takes no
`split(a)[1].split(b)[0]` slice. Its fixtures are real files, all of them under a
single `tempfile.mkdtemp(prefix="audit-journal-")` removed in one `finally`
(`shutil.rmtree(..., ignore_errors=True)`) - the git repositories the k-group and
the l-group build are subdirectories of it, so nothing is left behind on a case
that fails part way. It loads no sibling through `_loader`, so no
`KNOWN_LAYER_DEBT` entry moved with it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import hashlib
import json
import os
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("audit-journal.py", modname="audit_journal")


# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil
    import tempfile

    def run(argv, project):
        lines = []
        code = M.main(argv + ["--project", project], out=lines.append)
        return code, "\n".join(lines)

    def _month_shift(n):
        """YYYY-MM for `n` months before the current month. Computed, never
        hardcoded -- a hardcoded date goes red the day the calendar catches
        up with it (the doctor's F-A1 lesson)."""
        t = time.gmtime()
        y, m = t.tm_year, t.tm_mon - n
        while m < 1:
            y, m = y - 1, m + 12
        return "%04d-%02d" % (y, m)

    tmp = tempfile.mkdtemp(prefix="audit-journal-")
    try:
        proj = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(proj, "docs", "audit"))
        cfg = {"manifestPath": "docs/audit/audit-plan.json"}

        # --- a1: where it lands, without being told ---------------------------
        # Derived from manifestPath rather than hardcoded: a repo that moved its
        # plan must not end up with the record of it somewhere else.
        check("a1 the journal sits beside the manifest by default",
              M.journal_dir(proj, cfg)
              == os.path.join(proj, "docs/audit".replace("/", os.sep), "journal"))
        check("a2 journal.dir overrides it",
              M.journal_dir(proj, {"journal": {"dir": "audit-trail"}})
              == os.path.join(proj, "audit-trail"))
        check("a2b a root-level manifestPath does not leave a `./` segment in the "
              "returned path (BUG-2: mixed separators on Windows, `proj/./journal` "
              "on POSIX)",
              M.journal_dir(proj, {"manifestPath": "audit.json"})
              == os.path.normpath(os.path.join(proj, M.DEFAULT_DIRNAME)))
        check("a2c the default-manifest shape is normalized too",
              M.journal_dir(proj, cfg)
              == os.path.normpath(os.path.join(proj, "docs", "audit", "journal")))
        check("a3 enabled by default, and an explicit false is honoured",
              M.enabled({}) is True and M.enabled({"journal": {"enabled": False}}) is False)
        check("a4 a non-bool `enabled` is ignored rather than trusted "
              "(the rule `enforce` already follows)",
              M.enabled({"journal": {"enabled": "false"}}) is True)

        # --- b: one row, and what is in it ------------------------------------
        ok = M.append(proj, {"action": "config.write", "target": "cfg.json",
                           "summary": "1 change(s): x", "actor": {
                               "author": "dev@example.com", "sessionId": "s-one",
                               "via": "panel"}}, config=cfg)
        d = M.journal_dir(proj, cfg)
        files = M.journal_files(d)
        # F-F3: success is the PATH of the file the row landed in, not a bare
        # True -- the journal-writes hook records that path in its sidecar so
        # guard-bash-writes can tell the plugin's own append from a shell write.
        # Truthiness is unchanged, so every caller that boolean-tests survives.
        check("b1 append() reports success as the path it wrote, and writes "
              "exactly one file",
              isinstance(ok, str) and ok == files[0] and len(files) == 1,
              repr((ok, files)))
        check("b2 the file is <month>.<writer>.jsonl",
              os.path.basename(files[0]).endswith(".s-one.jsonl")
              and os.path.basename(files[0])[:7] == time.strftime("%Y-%m",
                                                                  time.gmtime()))
        rows, torn = M.read_file(files[0])
        r0 = rows[0]
        check("b3 the row carries the contract's fields and nothing invented",
              set(r0) == {"v", "ts", "actor", "action", "target", "summary",
                          "stateHash", "prev", "hash"}, repr(sorted(r0)))
        check("b4 the actor keeps who, how and where",
              r0["actor"]["author"] == "dev@example.com"
              and r0["actor"]["via"] == "panel"
              and r0["actor"]["sessionId"] == "s-one"
              and bool(r0["actor"]["host"]))
        check("b5 the first row's prev is derived from the FILE NAME, so a file "
              "cannot be renamed into another writer's slot and still verify",
              r0["prev"] == M.genesis_prev(os.path.basename(files[0])))
        check("b6 the row hashes to its own contents", r0["hash"] == M.row_hash(r0)
              and not torn)
        check("b7 a target that does not exist leaves stateHash null, rather than "
              "a hash of nothing", r0["stateHash"] is None)

        # --- c: the chain -----------------------------------------------------
        M.append(proj, {"action": "composition.write", "target": "m.json",
                      "summary": "two", "actor": {"sessionId": "s-one",
                                                  "via": "panel"}}, config=cfg)
        rows, _ = M.read_file(files[0])
        check("c1 the second row chains to the first",
              len(rows) == 2 and rows[1]["prev"] == rows[0]["hash"])
        res = M.verify(proj, cfg)
        check("c2 a clean chain verifies with no findings",
              res["ok"] and res["rows"] == 2 and not res["findings"],
              repr(res["findings"]))

        def rewrite(path, rows_):
            with open(path, "w", encoding="utf-8") as fh:
                for r in rows_:
                    fh.write(M.canonical(r) + "\n")

        # An edited row: the summary says something else and the hash no longer
        # covers it. This is the case the whole file exists for.
        edited = [dict(rows[0]), dict(rows[1])]
        edited[0]["summary"] = "nothing happened"
        rewrite(files[0], edited)
        res = M.verify(proj, cfg)
        check("c3 an edited row is a FINDING that names the row and the reason",
              not res["ok"] and any("edited after it was written" in f
                                    for f in res["findings"]), repr(res["findings"]))
        # And the forger who fixes the hash of the row they edited is caught by
        # the NEXT row's prev -- which is the entire point of chaining.
        edited[0]["hash"] = M.row_hash(edited[0])
        rewrite(files[0], edited)
        res = M.verify(proj, cfg)
        check("c4 ...and re-hashing that row alone still breaks the chain at the "
              "row after it",
              not res["ok"] and any("does not follow the row before it" in f
                                    for f in res["findings"]), repr(res["findings"]))

        rewrite(files[0], rows)                       # back to the honest pair
        check("c5 restored, it verifies again", M.verify(proj, cfg)["ok"])

        rewrite(files[0], [rows[1]])                  # first row deleted
        res = M.verify(proj, cfg)
        check("c6 a deleted row is a FINDING (the survivor's prev names a row that "
              "is not there)", not res["ok"])
        rewrite(files[0], [rows[1], rows[0]])         # reordered
        res = M.verify(proj, cfg)
        check("c7 a reordered pair is a FINDING", not res["ok"])
        rewrite(files[0], rows)

        # A torn tail is a crash, not a cover-up: warn, do not accuse.
        with open(files[0], "a", encoding="utf-8") as fh:
            fh.write('{"v":1,"action":"half-writ')
        res = M.verify(proj, cfg)
        check("c8 a torn last line is a WARNING, and the rows before it still "
              "verify", res["ok"] and res["rows"] == 2
              and any("partial line" in w for w in res["warnings"]),
              repr(res))
        rewrite(files[0], rows)

        # A file copied into another writer's name: every prev still matches its
        # predecessor, so ONLY the genesis binding catches this.
        twin = os.path.join(d, os.path.basename(files[0]).replace("s-one", "s-two"))
        shutil.copyfile(files[0], twin)
        res = M.verify(proj, cfg)
        check("c9 a file copied under another writer's name is caught by the "
              "genesis binding, which is the only thing that can see it",
              not res["ok"] and any("renamed" in f for f in res["findings"]),
              repr(res["findings"]))
        os.unlink(twin)
        check("c10 and removing the copy makes it clean again", M.verify(proj, cfg)["ok"])

        # --- d: out-of-band drift --------------------------------------------
        tgt = os.path.join(proj, "docs", "audit", "audit-plan.json")
        with open(tgt, "w", encoding="utf-8") as fh:
            fh.write('{"meta":{"version":3}}')
        M.append(proj, {"action": "manifest.edit",
                      "target": "docs/audit/audit-plan.json",
                      "summary": "wrote it", "actor": {"sessionId": "s-one",
                                                       "via": "hook"}}, config=cfg)
        res = M.verify(proj, cfg)
        check("d1 a target recorded and untouched raises nothing",
              res["ok"] and not res["warnings"], repr(res["warnings"]))
        with open(tgt, "w", encoding="utf-8") as fh:
            fh.write('{"meta":{"version":3},"phases":[]}')
        res = M.verify(proj, cfg)
        check("d2 a target changed with no row to explain it is a WARNING, not a "
              "finding - an out-of-band write is not proof of a cover-up",
              res["ok"] and any("never saw" in w for w in res["warnings"]),
              repr(res["warnings"]))
        os.unlink(tgt)
        check("d3 a target that has been deleted says so",
              any("no longer exists" in w for w in M.verify(proj, cfg)["warnings"]))

        # --- e: fail-soft, and the safety of a caller-supplied id -------------
        # Every one of these goes through `_soft`, because "never raises" is the
        # contract and an exception escaping here would kill this suite with a
        # traceback instead of failing the case that is about it — red for the
        # wrong reason proves nothing.
        def _soft(entry, config=cfg, project=proj):
            try:
                return M.append(project, entry, config=config)
            except Exception as exc:                   # pragma: no cover
                return "it raised: %s" % exc

        check("e1 a row with no action is refused rather than written blank",
              _soft({"summary": "x"}) is False)
        check("e2 a disabled journal writes nothing and says False, so a caller "
              "reports `not logged` rather than a failed save",
              _soft({"action": "x"}, config={"journal": {"enabled": False}}) is False)
        check("e3 garbage in, False out - never an exception into the writer",
              _soft(None) is False and _soft("not a dict") is False)
        check("e4 an unwritable journal dir is False, not a crash",
              _soft({"action": "x"}, config={"journal": {"dir": "\0bad"}},
                    project=os.path.join(tmp, "no-such-project")) is False)
        # A session id is supplied by the caller and lands in a PATH.
        check("e5 a writer id cannot escape the journal directory",
              M.writer_id({"sessionId": "../../etc/passwd"}) == "etc-passwd"
              and "/" not in M.writer_id({"sessionId": "a/b"})
              and os.sep not in M.writer_id({"sessionId": "a" + os.sep + "b"}))
        check("e6 a writer with no session id still gets a stable file name",
              bool(M.writer_id({})) and M.writer_id({}) == M.writer_id({}))
        check("e7 a long session id is truncated (a file name is not unbounded)",
              len(M.writer_id({"sessionId": "x" * 200})) == 24)
        # F-F2: the truncation itself can END on `-` or `.`. A real UUID is
        # 8-4-4-4-12, so its 24-char slice ends exactly on the fourth dash --
        # every real session got a writer id with a trailing `-`, and a rename
        # of that file (or a hand copy that drops the dash) reads as another
        # writer's slot. Strip AFTER the slice too; the first strip still
        # handles leading rubbish before the slice spends its budget on it.
        check("e8 a real UUID's writer id does not end on a dash",
              M.writer_id({"sessionId": "abcd1234-ef56-7890-abcd-123456789012"})
              == "abcd1234-ef56-7890-abcd",
              repr(M.writer_id({"sessionId":
                              "abcd1234-ef56-7890-abcd-123456789012"})))
        check("e8b the boundary id whose 24th char is the dash is trimmed, "
              "not kept",
              M.writer_id({"sessionId": "a" * 23 + "-" + "b" * 10}) == "a" * 23,
              repr(M.writer_id({"sessionId": "a" * 23 + "-" + "b" * 10})))
        check("e8c a pathological id of nothing but separators still gets a "
              "stable name",
              M.writer_id({"sessionId": "." * 40}) == "writer"
              and M.writer_id({"sessionId": "-.-.-.-" * 10}) == "writer")

        # --- f: two writers, two files, one clean journal ---------------------
        two = os.path.join(tmp, "two")
        os.makedirs(two)
        for sid in ("alpha", "beta"):
            for i in range(2):
                M.append(two, {"action": "config.write", "summary": "%s-%d" % (sid, i),
                             "actor": {"sessionId": sid, "via": "panel"}},
                       config={"journal": {"dir": "j"}})
        res = M.verify(two, {"journal": {"dir": "j"}})
        check("f1 two writers write two files - one shared file would conflict on "
              "every worktree merge",
              len(res["files"]) == 2 and res["rows"] == 4 and res["ok"],
              repr(res))
        check("f2 read_all returns every row, oldest first, tagged with its file",
              len(M.read_all(two, {"journal": {"dir": "j"}})) == 4
              and all(r.get("_file") for r in
                      M.read_all(two, {"journal": {"dir": "j"}})))

        # --- g: the lock ------------------------------------------------------
        gproj = os.path.join(tmp, "lockrepo")
        os.makedirs(gproj)
        gcfg = {"journal": {"dir": "j"}}
        M.append(gproj, {"action": "a", "actor": {"sessionId": "s"}}, config=gcfg)
        gpath = M.journal_files(M.journal_dir(gproj, gcfg))[0]
        held = gpath + ".lock"
        with open(held, "w", encoding="utf-8") as fh:
            fh.write("")
        t0 = time.time()
        check("g1 a held lock declines the append rather than racing it - a torn "
              "chain reads as tampering, which is worse than a missing row",
              M.append(gproj, {"action": "b", "actor": {"sessionId": "s"}},
                     config=gcfg) is False)
        check("g2 ...and it gives up in bounded time", time.time() - t0 < 10)
        os.utime(held, (time.time() - 600, time.time() - 600))
        check("g3 a lock left behind by a dead writer is stolen, not waited on "
              "forever (and success is the written path)",
              isinstance(M.append(gproj, {"action": "c",
                                        "actor": {"sessionId": "s"}},
                                config=gcfg), str))
        check("g4 the stolen-lock append still chains cleanly",
              M.verify(gproj, gcfg)["ok"])
        check("g5 the lock file is not left lying in the journal directory",
              not os.path.exists(held))

        # --- h: canonical form ------------------------------------------------
        check("h1 canonical JSON is stable regardless of key order",
              M.canonical({"b": 1, "a": [1, {"d": 2, "c": 3}]})
              == M.canonical({"a": [1, {"c": 3, "d": 2}], "b": 1}))
        check("h2 the hash ignores the `hash` field itself (or nothing could ever "
              "verify)",
              M.row_hash({"a": 1, "hash": "x"}) == M.row_hash({"a": 1, "hash": "y"}))
        check("h3 canonical output is pure ASCII, so a cp1252 stream cannot kill "
              "a writer", M.canonical({"a": "café"}).isascii())

        # --- i: the CLI -------------------------------------------------------
        cproj = os.path.join(tmp, "cli")
        os.makedirs(os.path.join(cproj, "docs", "audit"))
        code, txt = run(["verify"], cproj)
        check("i1 verify with no journal at all is 0 and says so, not an error",
              code == 0 and "no journal yet" in txt, txt)
        code, txt = run(["append", "--action", "config.write", "--summary", "hi"],
                        cproj)
        check("i2 append prints the row it wrote", code == 0 and "config.write" in txt)
        code, txt = run(["verify"], cproj)
        check("i3 verify is 0 on a clean chain and counts the rows",
              code == 0 and "OK: 1 row(s)" in txt, txt)
        code, txt = run(["show"], cproj)
        check("i4 show prints the row", code == 0 and "config.write" in txt)
        code, txt = run(["show", "--json"], cproj)
        check("i5 show --json is parseable and carries the chain fields",
              code == 0 and json.loads(txt)[0]["hash"])
        code, txt = run(["append"], cproj)
        check("i6 append with no action is a usage error (2), not a blank row",
              code == 2, txt)
        _lines = []
        check("i7 a missing project is a usage error",
              M.main(["verify", "--project",
                    os.path.join(tmp, "not-a-directory")],
                   out=_lines.append) == 2, "\n".join(_lines))
        # Break it, and prove the CLI's exit code moves with the verdict: this is
        # the code CI and the doctor act on.
        jf = M.journal_files(M.journal_dir(cproj))[0]
        rows, _ = M.read_file(jf)
        rows[0]["summary"] = "tampered"
        rewrite(jf, rows)
        code, txt = run(["verify"], cproj)
        check("i8 verify EXITS 1 on a broken chain (grepping the text is how three "
              "false pass reports happened)", code == 1 and "FINDING" in txt, txt)
        code, txt = run(["verify", "--json"], cproj)
        check("i9 verify --json keeps the exit code and reports ok:false",
              code == 1 and json.loads(txt)["ok"] is False)
        code, txt = run(["nonsense"], cproj)
        check("i10 an unknown command is a usage error", code == 2)

        # --- j: row v2 -- the optional `details` block ------------------------
        # The hash covers whatever fields are present, so a v1 row and a v2 row
        # share a file with no migration; everything here pins that claim.
        jproj = os.path.join(tmp, "v2")
        os.makedirs(jproj)
        jcfg = {"journal": {"dir": "j"}}
        ok = M.append(jproj, {"action": "manifest.edit", "target": "plan.json",
                            "summary": "P1.1: status in_progress->done",
                            "details": {"taskId": "P1.1", "phaseId": "P1",
                                        "from": "in_progress", "to": "done"},
                            "actor": {"sessionId": "s-v2", "via": "hook"}},
                    config=jcfg)
        jrows = M.read_all(jproj, jcfg)
        jrow = jrows[-1] if jrows else {}
        check("j1 a row can carry details, and the allow-listed keys survive the "
              "round trip",
              isinstance(ok, str) and jrow.get("details") == {
                  "taskId": "P1.1", "phaseId": "P1",
                  "from": "in_progress", "to": "done"},
              repr(jrow.get("details")))
        jclean = {k: v for k, v in jrow.items() if k != "_file"}
        check("j2 a details row is v2, hashes to its own contents, and verifies",
              jrow.get("v") == 2 and jclean.get("hash") == M.row_hash(jclean)
              and M.verify(jproj, jcfg)["ok"], repr(jrow))
        M.append(jproj, {"action": "manifest.edit", "target": "plan.json",
                       "summary": "plain", "actor": {"sessionId": "s-v2",
                                                     "via": "hook"}}, config=jcfg)
        jrows = M.read_all(jproj, jcfg)
        check("j3 a row without details stays v1 with the v1 key set - the new "
              "shape is opt-in per row, not a migration",
              jrows[-1].get("v") == 1 and "details" not in jrows[-1]
              and set(jrows[-1]) - {"_file"} == {
                  "v", "ts", "actor", "action", "target", "summary",
                  "stateHash", "prev", "hash"}, repr(sorted(jrows[-1])))
        check("j3b ...and the mixed file still chains cleanly",
              M.verify(jproj, jcfg)["ok"] and M.verify(jproj, jcfg)["rows"] == 2)

        # A file an OLDER plugin wrote -- hand-built v1 rows -- then a v2 row
        # appended by THIS code, chaining onto the old tail.
        fixdir = os.path.join(tmp, "v1fixture")
        os.makedirs(os.path.join(fixdir, "j"))
        fpath = os.path.join(fixdir, "j", "%s.s-old.jsonl"
                             % time.strftime("%Y-%m", time.gmtime()))
        prev_h = M.genesis_prev(os.path.basename(fpath))
        hand = []
        for i in range(2):
            r = {"v": 1, "ts": "2020-01-01T00:00:0%dZ" % i,
                 "actor": {"author": None, "sessionId": "s-old", "via": "hook",
                           "host": "h"},
                 "action": "manifest.edit", "target": "", "summary": "old %d" % i,
                 "stateHash": None, "prev": prev_h}
            r["hash"] = M.row_hash(r)
            prev_h = r["hash"]
            hand.append(r)
        rewrite(fpath, hand)
        fixcfg = {"journal": {"dir": "j"}}
        check("j4 a pre-v2 fixture file verifies untouched",
              M.verify(fixdir, fixcfg)["ok"]
              and M.verify(fixdir, fixcfg)["rows"] == 2,
              repr(M.verify(fixdir, fixcfg)))
        M.append(fixdir, {"action": "manifest.edit", "target": "",
                        "summary": "new", "details": {"taskId": "P9.1"},
                        "actor": {"sessionId": "s-old", "via": "hook"}},
               config=fixcfg)
        resv = M.verify(fixdir, fixcfg)
        vrows, _ = M.read_file(fpath)
        check("j5 a v2 row appended after v1 rows chains onto the old tail in "
              "the SAME file",
              resv["ok"] and resv["rows"] == 3 and len(resv["files"]) == 1
              and vrows[-1].get("v") == 2
              and vrows[-1].get("prev") == hand[-1]["hash"], repr(resv))

        # The allow-list, the bounds, and the cap.
        M.append(jproj, {"action": "x", "summary": "s",
                       "details": {"taskId": "T", "invented": "nope"},
                       "actor": {"sessionId": "s-v2"}}, config=jcfg)
        check("j6 an unknown details key is dropped, not chained in",
              M.read_all(jproj, jcfg)[-1].get("details") == {"taskId": "T"},
              repr(M.read_all(jproj, jcfg)[-1].get("details")))
        check("j6b a details dict with ONLY unknown keys leaves a plain v1 row",
              M.normalise_details({"invented": 1}) is None
              and M.normalise_details("not a dict") is None
              and M.normalise_details(None) is None)
        M.append(jproj, {"action": "x", "summary": "s",
                       "details": {"from": "x" * 500},
                       "actor": {"sessionId": "s-v2"}}, config=jcfg)
        check("j7 a long value is truncated to %d chars" % M.MAX_VALUE_CHARS,
              M.read_all(jproj, jcfg)[-1].get("details", {}).get("from") == "x" * 120)
        many = [{"id": "P1.%d" % i, "field": "status", "from": "a", "to": "b"}
                for i in range(20)]
        det = M.normalise_details({"changes": many})
        check("j8 a change list is capped at %d and says it was truncated"
              % M.MAX_CHANGES,
              isinstance(det, dict) and len(det.get("changes") or []) == 12
              and det.get("truncated") is True, repr(det))
        huge = {"changes": [{"id": "P1.%d" % i, "field": "outcome",
                             "from": "a" * 120, "to": "b" * 120}
                            for i in range(12)],
                "taskId": "t" * 120, "phaseId": "p" * 120, "commit": "c" * 120,
                "completedAt": "d" * 120, "fromId": "e" * 120, "toId": "f" * 120,
                "fromPhase": "g" * 120, "toPhase": "h" * 120}
        det = M.normalise_details(huge)
        check("j9 a details block over %d bytes collapses to a truncation marker "
              "that still says how many changes there were" % M.MAX_DETAILS_BYTES,
              det == {"truncated": True, "changes": 12}, repr(det))
        check("j9b the marker itself is under the cap",
              len(M.canonical({"truncated": True, "changes": 12})
                  .encode("utf-8")) < M.MAX_DETAILS_BYTES)

        # The CLI.
        c2proj = os.path.join(tmp, "cli2")
        os.makedirs(c2proj)
        code, txt = run(["append", "--action", "task.move",
                         "--details", '{"fromId":"P1.1","toId":"P2.4"}'], c2proj)
        check("j10 append --details writes the row (exit 0)", code == 0, txt)
        code, txt = run(["show", "--json"], c2proj)
        got = json.loads(txt)[-1] if code == 0 else {}
        check("j10b ...and show --json carries it back out",
              got.get("details") == {"fromId": "P1.1", "toId": "P2.4"}
              and got.get("v") == 2, repr(got))
        code, txt = run(["append", "--action", "x", "--details", "{not json"],
                        c2proj)
        check("j11 malformed --details is a usage error (2), not a silent plain "
              "row", code == 2, txt)
        code, txt = run(["append", "--action", "x", "--details", '["a list"]'],
                        c2proj)
        check("j11b a non-object --details is a usage error too", code == 2, txt)
        check("j11c neither wrote anything",
              M.verify(c2proj)["rows"] == 1, repr(M.verify(c2proj)))
        M.append(c2proj, {"action": "x", "summary": "s", "details": "a string",
                        "actor": {"sessionId": "s"}})
        check("j12 a non-dict details via the API is ignored, the row stays v1",
              M.read_all(c2proj)[-1].get("v") == 1
              and "details" not in M.read_all(c2proj)[-1])

        # --- k: the git anchor -------------------------------------------------
        # A forger who rewrites the whole file and recomputes every hash forward
        # produces a chain that verifies -- the module docstring admits it. What
        # they cannot rewrite from here is git history: once the journal is
        # committed, `git show HEAD:<file>` must be a byte-prefix of the working
        # copy (append-only across commits).
        import subprocess
        if not shutil.which("git"):
            print("SKIP k1-k4 (git is not on PATH)")
        else:
            gdir = os.path.join(tmp, "gitrepo")
            os.makedirs(os.path.join(gdir, "docs", "audit"))

            def git(*args):
                return subprocess.run(
                    ["git", "-C", gdir, "-c", "user.email=t@t",
                     "-c", "user.name=t"] + list(args),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30)

            git("init", "-q")
            gcfg = {"manifestPath": "docs/audit/audit-plan.json"}
            M.append(gdir, {"action": "manifest.edit", "target": "",
                          "summary": "one",
                          "actor": {"sessionId": "s-git", "via": "hook"}},
                   config=gcfg)
            gfile = M.journal_files(M.journal_dir(gdir, gcfg))[0]
            resk = M.verify(gdir, gcfg)
            check("k1 an untracked journal is silent - no finding, no warning "
                  "(fail-open: no git anchor is not evidence of anything)",
                  resk["ok"] and not resk["warnings"], repr(resk))
            git("add", ".")
            git("commit", "-q", "-m", "journal")
            M.append(gdir, {"action": "manifest.edit", "target": "",
                          "summary": "two",
                          "actor": {"sessionId": "s-git", "via": "hook"}},
                   config=gcfg)
            check("k2 the committed copy is a byte-prefix of the working file, "
                  "so appending after a commit stays clean",
                  M.verify(gdir, gcfg)["ok"], repr(M.verify(gdir, gcfg)))
            with open(gfile, "rb") as fh:
                pristine = fh.read()
            grows, _ = M.read_file(gfile)
            forged, prev_f = [], M.genesis_prev(os.path.basename(gfile))
            for r in grows:
                r = dict(r)
                if not forged:
                    r["summary"] = "nothing happened"
                r["prev"] = prev_f
                r["hash"] = M.row_hash({k: v for k, v in r.items()
                                      if k != "hash"})
                prev_f = r["hash"]
                forged.append(r)
            rewrite(gfile, forged)
            resk = M.verify(gdir, gcfg)
            check("k3 a full rewrite with recomputed hashes chains cleanly and "
                  "is STILL a FINDING - the committed past changed",
                  not resk["ok"]
                  and any("committed past changed" in f
                          for f in resk["findings"]), repr(resk["findings"]))
            with open(gfile, "wb") as fh:
                fh.write(pristine)
            check("k4 restored byte-for-byte, it verifies again",
                  M.verify(gdir, gcfg)["ok"], repr(M.verify(gdir, gcfg)))

            # k5-k8 (F-B3): the anchor is BATCHED - one porcelain per
            # directory decides who pays the single-file check. Fixture: two
            # committed-clean writer files + one committed-then-appended one.
            M.append(gdir, {"action": "manifest.edit", "target": "",
                          "summary": "w2", "actor": {"sessionId": "s-git-2",
                                                     "via": "hook"}},
                   config=gcfg)
            M.append(gdir, {"action": "manifest.edit", "target": "",
                          "summary": "w3", "actor": {"sessionId": "s-git-3",
                                                     "via": "hook"}},
                   config=gcfg)
            git("add", ".")
            git("commit", "-q", "-m", "all writers committed")
            _orig_anchor = M._git_anchor_finding
            _anchor_calls = []

            def _counting_anchor(path):
                _anchor_calls.append(os.path.basename(path))
                return _orig_anchor(path)

            # `M._git_anchor_finding`, never `globals()[...]`: from `tests/` the
            # bare form binds a name nothing calls. `verify()` reads this as a
            # global of ITS module, so the real anchor would keep running, the
            # counter would stay [] - and k5 asserts exactly `[]`, so it would
            # have passed while measuring nothing. Restored on `M` in the same
            # `finally`.
            M._git_anchor_finding = _counting_anchor
            try:
                resk = M.verify(gdir, gcfg)
                check("k5 tracked-and-clean files never pay the single-file "
                      "check - committed equals working, the prefix holds "
                      "trivially",
                      resk["ok"] and _anchor_calls == [],
                      repr((_anchor_calls, resk["findings"])))
                M.append(gdir, {"action": "manifest.edit", "target": "",
                              "summary": "three",
                              "actor": {"sessionId": "s-git", "via": "hook"}},
                       config=gcfg)
                _anchor_calls.clear()
                resk = M.verify(gdir, gcfg)
                check("k6 a committed-then-appended file is the ONLY one that "
                      "pays git show, and it still verifies - O(1+dirty)",
                      resk["ok"]
                      and _anchor_calls == [os.path.basename(gfile)],
                      repr((_anchor_calls, resk["findings"])))
                with open(gfile, "rb") as fh:
                    pristine2 = fh.read()
                grows2, _ = M.read_file(gfile)
                forged2, prev_f2 = [], M.genesis_prev(os.path.basename(gfile))
                for r in grows2:
                    r = dict(r)
                    if not forged2:
                        r["summary"] = "nothing happened here either"
                    r["prev"] = prev_f2
                    r["hash"] = M.row_hash({k: v for k, v in r.items()
                                          if k != "hash"})
                    prev_f2 = r["hash"]
                    forged2.append(r)
                rewrite(gfile, forged2)
                resk = M.verify(gdir, gcfg)
                check("k7 a rewritten committed row is STILL a FINDING through "
                      "the batched path - batching skips the clean, never the "
                      "guilty",
                      not resk["ok"]
                      and any("committed past changed" in f
                              for f in resk["findings"]),
                      repr(resk["findings"]))
                with open(gfile, "wb") as fh:
                    fh.write(pristine2)
                check("k8 restored byte-for-byte, the batched pass is green "
                      "again", M.verify(gdir, gcfg)["ok"],
                      repr(M.verify(gdir, gcfg)["findings"]))
            finally:
                M._git_anchor_finding = _orig_anchor

            # k9-k10 (F-D-1): status keys are JOURNAL-RELATIVE PATHS, not
            # basenames. The journal dir here sits three levels deep
            # (docs/audit/journal), so these go red if porcelain's
            # repo-root-relative paths are ever mapped onto the directory
            # wrongly: an archived file the batch cannot see never pays the
            # anchor, and a forged archive twin would sail through.
            jdir9 = M.journal_dir(gdir, gcfg)
            aname9 = os.path.basename(gfile)
            apath9 = os.path.join(jdir9, "archive", aname9)
            os.makedirs(os.path.join(jdir9, "archive"))
            shutil.copyfile(gfile, apath9)
            git("add", ".")
            git("commit", "-q", "-m", "archive twin committed")
            with open(apath9, "rb") as fh:
                pristine9 = fh.read()
            arows9, _ = M.read_file(apath9)
            forged9, prev9 = [], M.genesis_prev(aname9)
            for r in arows9:
                r = dict(r)
                if not forged9:
                    r["summary"] = "nothing happened"
                r["prev"] = prev9
                r["hash"] = M.row_hash({k: v for k, v in r.items()
                                      if k != "hash"})
                prev9 = r["hash"]
                forged9.append(r)
            rewrite(apath9, forged9)
            resk = M.verify(gdir, gcfg)
            aent9 = [e for e in resk["files"]
                     if e["file"] == "archive/" + aname9]
            check("k9 a forged ARCHIVED twin of a live basename is caught "
                  "through the batched path - the twin answers for ITSELF, "
                  "its live namesake cannot answer for it (F-D-1)",
                  not resk["ok"] and aent9
                  and any("committed past changed" in f
                          for f in aent9[0]["findings"]),
                  repr(resk["findings"]))
            with open(apath9, "wb") as fh:
                fh.write(pristine9)
            resk = M.verify(gdir, gcfg)
            check("k10 restored byte-for-byte the batch is green again, and "
                  "only the duplicate-basename WARNING remains (the "
                  "collision state itself, already named by verify)",
                  resk["ok"] and not resk["findings"]
                  and any("double-count" in w for w in resk["warnings"]),
                  repr((resk["findings"], resk["warnings"])))

        # --- l: the archive/ subdirectory -------------------------------------
        # journal_files sees `<journal>/archive/` -- EXACTLY one level, never a
        # walk. The chain seed is the file's BASENAME (genesis_prev), so a file
        # MOVED into archive/ byte-for-byte verifies exactly as it did live:
        # that is the entire design of the git-mv archive (untouched bytes,
        # same name, different directory).
        lproj = os.path.join(tmp, "arch")
        os.makedirs(lproj)
        lcfg = {"journal": {"dir": "j"}}
        old_month = _month_shift(2)
        for i, summ in enumerate(("old-1", "old-2")):
            M.append(lproj, {"action": "manifest.edit", "target": "",
                           "summary": summ,
                           "ts": "%s-01T00:00:0%dZ" % (old_month, i),
                           "actor": {"sessionId": "s-old", "via": "hook"}},
                   config=lcfg)
        M.append(lproj, {"action": "manifest.edit", "target": "",
                       "summary": "live",
                       "actor": {"sessionId": "s-new", "via": "hook"}},
               config=lcfg)
        ldir = M.journal_dir(lproj, lcfg)
        pre = M.verify(lproj, lcfg)
        check("l1 the fixture verifies green BEFORE archiving",
              pre["ok"] and pre["rows"] == 3, repr(pre))
        lold = os.path.join(ldir, "%s.s-old.jsonl" % old_month)
        lnew_name = "%s.s-new.jsonl" % time.strftime("%Y-%m", time.gmtime())
        with open(lold, "rb") as fh:
            lbytes = fh.read()
        os.makedirs(os.path.join(ldir, "archive"))
        lapath = os.path.join(ldir, "archive", os.path.basename(lold))
        os.rename(lold, lapath)
        check("l2 journal_files sees the archive/ subdirectory, live files "
              "first",
              [os.path.relpath(p, ldir).replace(os.sep, "/")
               for p in M.journal_files(ldir)]
              == [lnew_name, "archive/%s.s-old.jsonl" % old_month],
              repr(M.journal_files(ldir)))
        deepdir = os.path.join(ldir, "archive", "deep")
        os.makedirs(deepdir)
        with open(os.path.join(deepdir, "0000-01.x.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write("{}\n")
        check("l3 exactly ONE level: a file nested below archive/ is not a "
              "journal file (minimal scope, not a tree walk)",
              all(os.sep + "deep" + os.sep not in p
                  for p in M.journal_files(ldir)), repr(M.journal_files(ldir)))
        res = M.verify(lproj, lcfg)
        check("l4 the chain verifies green AFTER the move -- untouched bytes "
              "under the same basename seed the same genesis",
              res["ok"] and res["rows"] == 3, repr(res))
        check("l5 verify reports the archived file AS archive/<name>, so a "
              "live and an archived month cannot read as one another",
              any(e["file"] == "archive/%s.s-old.jsonl" % old_month
                  for e in res["files"])
              and any(e["file"] == lnew_name for e in res["files"]),
              repr([e["file"] for e in res["files"]]))
        arows, _ = M.read_file(lapath)
        arows2 = [dict(r) for r in arows]
        arows2[0]["summary"] = "nothing happened"
        rewrite(lapath, arows2)
        res = M.verify(lproj, lcfg)
        check("l6 a broken chain INSIDE archive/ is still a FINDING, and it "
              "names the archive/ path",
              not res["ok"] and any("archive/" in f and "edited after" in f
                                    for f in res["findings"]),
              repr(res["findings"]))
        with open(lapath, "wb") as fh:
            fh.write(lbytes)
        check("l7 restored byte-for-byte, the archived file is green again",
              M.verify(lproj, lcfg)["ok"],
              repr(M.verify(lproj, lcfg)["findings"]))
        shutil.copyfile(lapath, lold)
        res = M.verify(lproj, lcfg)
        check("l8 the same basename live AND archived is a WARNING naming the "
              "duplication (its rows double-count)",
              res["ok"] and any("archive/" in w and "double-count" in w
                                for w in res["warnings"]),
              repr(res["warnings"]))
        os.unlink(lold)
        check("l9 read_all includes archived rows, tagged with the BASENAME "
              "(_file feeds the doctor's deep check, which greps commit trees "
              "where the file was still live)",
              len(M.read_all(lproj, lcfg)) == 3
              and any(r.get("_file") == os.path.basename(lold)
                      for r in M.read_all(lproj, lcfg)),
              repr([r.get("_file") for r in M.read_all(lproj, lcfg)]))

        # --- m: the `archive` subcommand ---------------------------------------
        # `git mv`, never a rewrite: the hash chain survives only untouched
        # bytes, and git carries the file's committed history across the move
        # so the git anchor keeps holding.
        m0 = os.path.join(tmp, "norepo")
        os.makedirs(os.path.join(m0, ".claude"))
        with open(os.path.join(m0, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"journal": {"dir": "j"}}')
        M.append(m0, {"action": "manifest.edit", "target": "",
                    "summary": "old", "ts": old_month + "-01T00:00:00Z",
                    "actor": {"sessionId": "s-m", "via": "hook"}},
               config={"journal": {"dir": "j"}})
        code, txt = run(["archive"], m0)
        check("m1 outside a git repository archive REFUSES (usage error 2) "
              "and says why: git mv is the mechanism, no repo means no "
              "history to carry",
              code == 2 and "git mv" in txt and "git init" in txt, txt)
        check("m1b ...and nothing moved",
              os.path.isfile(os.path.join(m0, "j", "%s.s-m.jsonl" % old_month))
              and not os.path.isdir(os.path.join(m0, "j", "archive")),
              repr(os.listdir(os.path.join(m0, "j"))))
        if not shutil.which("git"):
            print("SKIP m2-m10 (git is not on PATH)")
        else:
            mdir = os.path.join(tmp, "archrepo")
            os.makedirs(os.path.join(mdir, ".claude"))
            with open(os.path.join(mdir, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                fh.write('{"journal": {"dir": "j"}}')

            def mgit(*a):
                return subprocess.run(
                    ["git", "-C", mdir, "-c", "user.email=t@t",
                     "-c", "user.name=t"] + list(a),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=30)

            mgit("init", "-q")
            mcfg = {"journal": {"dir": "j"}}
            for i in range(2):
                M.append(mdir, {"action": "manifest.edit", "target": "",
                              "summary": "old %d" % i,
                              "ts": "%s-01T00:00:0%dZ" % (old_month, i),
                              "actor": {"sessionId": "s-arch", "via": "hook"}},
                       config=mcfg)
            M.append(mdir, {"action": "manifest.edit", "target": "",
                          "summary": "live",
                          "actor": {"sessionId": "s-arch", "via": "hook"}},
                   config=mcfg)
            mgit("add", ".")
            mgit("commit", "-q", "-m", "journal committed")
            mold = os.path.join(mdir, "j", "%s.s-arch.jsonl" % old_month)
            mlive = os.path.join(mdir, "j", "%s.s-arch.jsonl"
                                 % time.strftime("%Y-%m", time.gmtime()))
            with open(mold, "rb") as fh:
                mbytes = fh.read()
            msha = hashlib.sha256(mbytes).hexdigest()
            pre = M.verify(mdir, mcfg)
            code, txt = run(["archive"], mdir)
            march = os.path.join(mdir, "j", "archive",
                                 "%s.s-arch.jsonl" % old_month)
            same_bytes = False
            if os.path.isfile(march):
                with open(march, "rb") as fh:
                    same_bytes = (hashlib.sha256(fh.read()).hexdigest()
                                  == msha)
            check("m2 archive moves the past month into archive/ and leaves "
                  "the bytes untouched (sha256-identical)",
                  code == 0 and same_bytes and not os.path.exists(mold), txt)
            check("m2b the current month stays live -- still being written, "
                  "never archived", os.path.isfile(mlive),
                  repr(M.journal_files(os.path.join(mdir, "j"))))
            check("m2c the output says what moved and why mv-not-rewrite "
                  "matters (the chain survives only untouched bytes)",
                  "git mv" in txt and "untouched bytes" in txt, txt)
            st = mgit("status", "--porcelain").stdout.decode("utf-8",
                                                             "replace")
            check("m3 the move is a STAGED RENAME -- git followed it, nothing "
                  "was deleted-and-recreated",
                  any(line.startswith("R ") for line in st.splitlines()), st)
            post = M.verify(mdir, mcfg)
            check("m4 chain verify is green before AND after: same rows, no "
                  "findings",
                  pre["ok"] and post["ok"]
                  and pre["rows"] == post["rows"] == 3,
                  repr((pre["rows"], post["rows"], post["findings"])))
            code, txt = run(["archive"], mdir)
            check("m5 a second run is idempotent: exit 0 and a calm "
                  "nothing-to-archive line",
                  code == 0 and "nothing to archive" in txt, txt)
            # The staged-rename window: HEAD has no copy at the NEW path yet,
            # so a whole-file rewrite here would slip past a naive anchor. The
            # committed past sits one level up, at the pre-archive path, and
            # the anchor must follow it there.
            frows, _ = M.read_file(march)
            forged, fprev = [], M.genesis_prev(os.path.basename(march))
            for r in frows:
                r = dict(r)
                if not forged:
                    r["summary"] = "nothing happened"
                r["prev"] = fprev
                r["hash"] = M.row_hash({k: v for k, v in r.items()
                                      if k != "hash"})
                fprev = r["hash"]
                forged.append(r)
            rewrite(march, forged)
            res = M.verify(mdir, mcfg)
            check("m6 a full rewrite of the archived file DURING the "
                  "staged-rename window is STILL a FINDING -- the anchor "
                  "follows the move back to the pre-archive path",
                  not res["ok"] and any("committed past changed" in f
                                        for f in res["findings"]),
                  repr(res["findings"]))
            with open(march, "wb") as fh:
                fh.write(mbytes)
            check("m6b restored byte-for-byte, green again",
                  M.verify(mdir, mcfg)["ok"],
                  repr(M.verify(mdir, mcfg)["findings"]))
            mgit("add", "-A")
            mgit("commit", "-q", "-m", "the archive commit")
            check("m7 after the archive commit the moved file anchors at its "
                  "NEW path and still verifies", M.verify(mdir, mcfg)["ok"],
                  repr(M.verify(mdir, mcfg)["findings"]))
            # Untracked files and --before. DECISION (pinned): an untracked
            # file is MOVED with os.rename rather than refused -- git mv fails
            # on untracked files, and the reason git mv is the mechanism
            # (carrying COMMITTED history across the move) does not exist for
            # a file with no committed past; a plain rename loses nothing.
            old3, old1 = _month_shift(3), _month_shift(1)
            for mo in (old3, old1):
                M.append(mdir, {"action": "manifest.edit", "target": "",
                              "summary": "untracked " + mo,
                              "ts": mo + "-01T00:00:00Z",
                              "actor": {"sessionId": "s-un", "via": "hook"}},
                       config=mcfg)
            code, txt = run(["archive", "--before", old1], mdir)
            check("m8 --before archives strictly OLDER months only: %s "
                  "moves, %s stays" % (old3, old1),
                  code == 0
                  and os.path.isfile(os.path.join(
                      mdir, "j", "archive", "%s.s-un.jsonl" % old3))
                  and os.path.isfile(os.path.join(
                      mdir, "j", "%s.s-un.jsonl" % old1)), txt)
            check("m8b an untracked file is MOVED (renamed), and the output "
                  "says there was no git history to carry",
                  "renamed" in txt and "no git history" in txt, txt)
            check("m8c ...and the untracked move still verifies green",
                  M.verify(mdir, mcfg)["ok"],
                  repr(M.verify(mdir, mcfg)["findings"]))
            code, txt = run(["archive", "--before", "not-a-month"], mdir)
            check("m9 a malformed --before is a usage error (2) naming the "
                  "shape", code == 2 and "YYYY-MM" in txt, txt)
            future = "%04d-01" % (time.gmtime().tm_year + 1)
            code, txt = run(["archive", "--before", future], mdir)
            check("m9b a future --before is clamped out loud -- the current "
                  "month and anything newer is never archived",
                  code == 0 and "never archived" in txt
                  and os.path.isfile(mlive), txt)
            # A live file re-created for an archived month (a late append):
            # never overwritten -- the refusal is printed, verify warns.
            M.append(mdir, {"action": "manifest.edit", "target": "",
                          "summary": "late row for an archived month",
                          "ts": old_month + "-15T00:00:00Z",
                          "actor": {"sessionId": "s-arch", "via": "hook"}},
                   config=mcfg)
            res = M.verify(mdir, mcfg)
            check("m10 a re-created live file for an archived month is the "
                  "duplicate WARNING, not a silent double count",
                  res["ok"] and any("double-count" in w
                                    for w in res["warnings"]),
                  repr(res["warnings"]))
            code, txt = run(["archive"], mdir)
            check("m10b archive refuses to overwrite an existing archive "
                  "file -- the live one is kept and the refusal printed",
                  code == 0 and "refusing to overwrite" in txt
                  and os.path.isfile(mold), txt)
            os.unlink(mold)
            check("m10c with the duplicate gone the journal reads clean "
                  "again",
                  M.verify(mdir, mcfg)["ok"]
                  and not M.verify(mdir, mcfg)["warnings"],
                  repr(M.verify(mdir, mcfg)["warnings"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_journal.py --selftest\n")
    raise SystemExit(2)
