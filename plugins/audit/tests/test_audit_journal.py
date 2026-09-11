#!/usr/bin/env python3
"""
The cases for `audit-journal.py`, moved out of it - an entry point.

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
nothing at all. k6 is the case that fails loudly if the stub is ever not
installed (`_anchor_calls == [basename(gfile)]`), and both directions were
proven red.

AND THE SAME BUG HAPPENED A SECOND TIME, WHICH IS WHY THE PAIRING IS THE POINT.
The stub was moved to `M._git_anchor_finding` when the suite moved here - correct
at the time, because `M` defined `verify`. It stopped being correct when the trail
moved to `_journal_io.py` and `audit-journal.py` became a command over it: `M`'s
`_git_anchor_finding` is an alias, and `verify` still reads its own module's
global. k5 went green again; k6 went red again and named it. The stub is installed
on `_journal_io` now - the module that DEFINES the function, which is the rule the
next move should follow too.

`M` is `audit-journal.py`, and it re-exports the whole trail because these 112
cases are about the trail AS THE COMMAND SEES IT - the file a user runs. The cases
that are about the library's own boundary live in `test__journal_io.py`.

NOTHING ELSE ABOUT THIS SUITE DEPENDS ON WHERE IT SITS. It reads no source, names
no `__file__`, builds no path off its own directory, and takes no
`split(a)[1].split(b)[0]` slice. Its fixtures are real files, all of them under a
single `_harness.fixture_root()` removed in one `finally`
(`shutil.rmtree(..., ignore_errors=True)`) - the git repositories the k-group and
the l-group build are subdirectories of it, so nothing is left behind on a case
that fails part way. The root comes from the harness rather than from `tempfile`
because those repositories are exactly what a plain removal leaves behind on
windows; `remove_tree()` says why, and the `finally` above is still the fast path.
It loads no sibling through `_loader`, so no `KNOWN_LAYER_DEBT` entry moved with it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import hashlib
import json
import os
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402  (posix_rel: the one path spelling)
import _loader                                     # noqa: E402
import _journal_io                                 # noqa: E402  (k5-k8 patch target)

M = _loader.load_script("audit-journal.py", modname="audit_journal")


# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil
    import subprocess           # the k-group, the mg-group and mr1 all shell out

    def run(argv, project):
        lines = []
        code = M.main(argv + ["--project", project], out=lines.append)
        return code, "\n".join(lines)

    def parsed(txt, empty):
        """`txt` decoded, or `empty` when it is not JSON of that shape.

        A CASE THAT RAISES TAKES EVERY CASE AFTER IT OUT OF THE RUN AND NAMES
        NONE OF THEM, WHICH IS F330. `_sxj = json.loads(txt)` sat outside its
        `check()` and did exactly that: mutating `sessions --json` to print prose
        dropped sx2 through sx6, named none of them, and left the contract line
        under-reporting its own total -- so the one mutation those cases exist to
        catch was the one that stopped them being reported at all. Guarding on
        the exit code is not enough, because the shape this has to survive is a
        ZERO exit with prose on stdout.

        `empty` is the default AND the shape being asked for: a listing that came
        back as an object, or an object that came back as a list, is as broken a
        `--json` as prose is, and one falsy value of the right type keeps the
        case that reads it FAILING BY NAME instead of raising."""
        ok, val = _harness.attempt(json.loads, txt)
        if not ok or not isinstance(val, type(empty)):
            return empty
        return val

    def _cross_second():
        """Sleep just past the next whole second, and no further.

        A CASE ABOUT A SECOND-RESOLUTION TIMESTAMP HAS TO CHOOSE ITS SECOND
        (F342). `_merge_marker` stamps `max(last row, now)` to the second, so
        whether a re-run rebuilds the previous marker byte for byte is decided
        by which second the two runs happen to land in -- and a case that hopes
        for one of them asserts a different thing on a slow machine, which is
        the shape CI finds and a laptop does not. Waiting for the boundary
        rather than sleeping a flat second costs the remainder and nothing
        more, and it makes the harder branch the one that runs."""
        time.sleep(1.02 - (time.time() % 1.0))

    def _month_shift(n):
        """YYYY-MM for `n` months before the current month. Computed, never
        hardcoded -- a hardcoded date goes red the day the calendar catches
        up with it (the doctor's F-A1 lesson)."""
        t = time.gmtime()
        y, m = t.tm_year, t.tm_mon - n
        while m < 1:
            y, m = y - 1, m + 12
        return "%04d-%02d" % (y, m)

    tmp = _harness.fixture_root("audit-journal-")
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
        # It used to end `and bool(r0["actor"]["host"])`, and that field is gone:
        # it was written on every row and read by nothing, while naming the
        # machine of whoever ran the plugin in a file this plugin tells people to
        # commit. Rewritten rather than deleted, so the suite still says what the
        # actor is - and the negative arm is what would catch it coming back.
        check("b4 the actor keeps who and how, and no longer says WHERE - a "
              "machine name nobody read is a field to delete, not one to hash",
              r0["actor"]["author"] == "dev@example.com"
              and r0["actor"]["via"] == "panel"
              and r0["actor"]["sessionId"] == "s-one"
              and "host" not in r0["actor"], repr(sorted(r0["actor"])))
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
        # BOTH separators on BOTH platforms, built from `chr(92)` rather than
        # `os.sep`. Written with `os.sep` this asked about "/" here and about "\"
        # there, so a sanitiser that stripped one and not the other was green on
        # whichever platform it was written on. `_SAFE` is a whitelist and strips
        # both, which is what makes the pair assertable rather than aspirational.
        _bs = chr(92)
        check("e5 a writer id cannot escape the journal directory, and neither "
              "separator survives it on either platform",
              M.writer_id({"sessionId": "../../etc/passwd"}) == "etc-passwd"
              and M.writer_id({"sessionId": ".." + _bs + ".." + _bs + "etc"
                               + _bs + "passwd"}) == "etc-passwd"
              and "/" not in M.writer_id({"sessionId": "a/b"})
              and _bs not in M.writer_id({"sessionId": "a" + _bs + "b"})
              and M.writer_id({"sessionId": "a/b" + _bs + "c"}) == "a-b-c")
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
        _i5 = parsed(txt, [])
        check("i5 show --json is parseable and carries the chain fields",
              code == 0 and bool(_i5) and _i5[0].get("hash"), txt)
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
              code == 1 and parsed(txt, {}).get("ok") is False, txt)
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
        # AND SAYS SO. A value cut in silence left a short value and a cut one
        # identical in a committed row, inside the one block that already sets
        # `truncated` when it drops change entries. Read through the command's
        # OWN re-exports, which is this suite's whole subject: the trail as
        # `audit-journal.py` sees it.
        check("j7 a long value is truncated to %d chars and carries the marker "
              "that says it was" % M.MAX_VALUE_CHARS,
              M.read_all(jproj, jcfg)[-1].get("details", {}).get("from")
              == "x" * (M.MAX_VALUE_CHARS - len(M.VALUE_TRUNCATED))
              + M.VALUE_TRUNCATED)
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
        _j10 = parsed(txt, [])
        got = _j10[-1] if _j10 else {}
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
            _orig_anchor = _journal_io._git_anchor_finding
            _anchor_calls = []

            def _counting_anchor(path):
                _anchor_calls.append(os.path.basename(path))
                return _orig_anchor(path)

            # ON `_journal_io`, THE MODULE THAT DEFINES `verify`, never on `M` and
            # never `globals()[...]`. `verify()` reads this name as a global of ITS
            # OWN module, so a stub installed anywhere else leaves the real anchor
            # running and the counter at [] - and k5 asserts exactly `[]`, so it
            # passes while measuring nothing.
            #
            # THIS HAS NOW BEEN THE SAME BUG TWICE. First `globals()[...]` from
            # `tests/`, fixed by moving the patch to `M`; then `M` itself stopped
            # being the definer when the trail moved into `_journal_io.py` and
            # `audit-journal.py` became a command over it. k5 went green both
            # times and k6 - which asserts a NON-empty list - is what caught it
            # both times. The lesson is in the pairing, not in either case:
            # a monkeypatch case that asserts an empty list cannot tell "the stub
            # ran and saw nothing" from "the stub was never installed", so it must
            # be kept beside one that asserts the stub DID run. Restored on
            # `_journal_io` in the same `finally`.
            _journal_io._git_anchor_finding = _counting_anchor
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
                _journal_io._git_anchor_finding = _orig_anchor

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
              [_output.posix_rel(p, ldir)
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

        # --- mg: one writer, two branches, and the verb that resolves it ------
        # F306. The per-writer file split separates two WRITERS and not two
        # BRANCHES, so a paused phase landing produces one file with a shared
        # prefix and two tails. Nothing can resolve that by editing -- each
        # divergent row's hash covers a `prev` only its own side has -- and with
        # no verb the resolution keeps one tail and loses the other in a second
        # parent nobody reads again.
        #
        # DRIVEN THROUGH A REAL `git merge` ON A REAL REPOSITORY, not through a
        # hand-built pair of files: the two sides this verb reads come from the
        # INDEX (stages 2 and 3), which only a genuine conflict puts there, and a
        # fixture that skipped the conflict would have tested a path no operator
        # ever takes.
        if not shutil.which("git"):
            print("SKIP mg1-mg13 (git is not on PATH)")
        else:
            gm = os.path.join(tmp, "diverge")
            os.makedirs(os.path.join(gm, "docs", "audit"))
            gmcfg = {"manifestPath": "docs/audit/audit-plan.json"}

            def gmgit(*args):
                # `merge.conflictstyle` is PINNED and not inherited: it is the
                # operator's global setting, `zdiff3` moves what a conflicted
                # working copy contains, and mg3c reads that text as evidence.
                # A fixture whose shape comes from the machine's config asserts a
                # different thing on every machine.
                return subprocess.run(
                    ["git", "-C", gm, "-c", "user.email=t@t",
                     "-c", "user.name=t", "-c", "merge.conflictstyle=merge"]
                    + list(args),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=30)

            def gmput(summary, ts, action="manifest.edit"):
                return M.append(gm, {"action": action, "target": "",
                                     "summary": summary, "ts": ts,
                                     "actor": {"sessionId": "s-branch",
                                               "via": "hook"}}, config=gmcfg)

            gmgit("init", "-q")
            gmput("base-1", "2026-06-01T00:00:00Z")
            gmfile = M.journal_files(M.journal_dir(gm, gmcfg))[0]
            gmname = os.path.basename(gmfile)
            gmrel = _output.posix_rel(gmfile, gm)
            gmgit("add", "-A")
            gmgit("commit", "-q", "-m", "base")
            # The branch name is ASKED FOR rather than assumed: `master` and
            # `main` are both defaults in the wild, and a hardcoded one silently
            # leaves the checkout on the side branch and merges nothing.
            gmbase = ((gmgit("rev-parse", "--abbrev-ref", "HEAD").stdout
                       or b"").decode("utf-8", "replace").strip())
            gmgit("branch", "side")
            # `theirs` lands BETWEEN ours' two rows, which is the shape that
            # decides mg4: ours' second row keeps its content and gets a new
            # `prev`, so HEAD's bytes stop being a prefix of a resolution that
            # dropped nothing at all.
            gmput("ours-1", "2026-06-02T00:00:00Z", action="task.complete")
            gmput("ours-2", "2026-06-05T00:00:00Z", action="task.commit")
            gmgit("add", "-A")
            gmgit("commit", "-q", "-m", "ours")
            gmhead = (gmgit("show", "HEAD:./%s" % gmrel).stdout or b"")
            gmgit("checkout", "-q", "side")
            gmput("theirs-1", "2026-06-03T00:00:00Z", action="task.complete")
            gmgit("add", "-A")
            gmgit("commit", "-q", "-m", "theirs")
            gmgit("checkout", "-q", gmbase)
            gmconflict = gmgit("merge", "side")
            with open(gmfile, "r", encoding="utf-8") as fh:
                gmmarkers = fh.read()
            check("mg1 the fixture is a REAL conflict: git could not merge the "
                  "journal file, and what it left behind is not a chain at all "
                  "-- which is why `verify` alone cannot tell an operator "
                  "whether their resolution is sound",
                  gmconflict.returncode != 0
                  and "<<<<<<<" in gmmarkers
                  and not M.verify(gm, gmcfg)["ok"],
                  repr((gmconflict.returncode,
                        (gmconflict.stdout or b"")[:120])))
            code, txt = run(["merge", "--file", gmrel, "--dry-run"], gm)
            with open(gmfile, "r", encoding="utf-8") as fh:
                gmstill = fh.read()
            check("mg2 --dry-run reports the resolution and writes NOTHING -- "
                  "the conflicted file is still the conflicted file",
                  code == 0 and "left as it is" in txt
                  and gmstill == gmmarkers
                  and "1 shared" in txt and "2 only in ours" in txt
                  and "1 only in theirs" in txt, txt)
            code, txt = run(["merge", "--file", gmrel], gm)
            gmrows = M.read_file(gmfile)[0]
            check("mg3 merge takes the two sides from the INDEX and writes the "
                  "union in timestamp order, so neither branch's tail is lost "
                  "-- which is the whole finding: %r"
                  % ([r.get("summary") for r in gmrows],),
                  code == 0
                  and [r.get("summary") for r in gmrows][:4]
                  == ["base-1", "ours-1", "theirs-1", "ours-2"]
                  and gmrows[-1]["action"] == M.MERGE_ACTION, txt)
            check("mg3b ...and the auditability claim carries its basis: both "
                  "sides came from the INDEX here, so both really are in git "
                  "-- the same sentence over two files a caller extracted "
                  "itself would be a claim this command cannot support",
                  "came from the index" in txt
                  and "Nothing here can say" not in txt, txt)
            # THE PREMISE OF AN EXEMPTION, MEASURED. The F328 target check does
            # not run on this path, and the reason it must not is a property of
            # the conflicted working copy rather than a preference: git built
            # that file out of the two stages, so its parseable rows are the two
            # tails concatenated with markers between them - an order no chain
            # ever had. Asserting the verdict on it is NOT held is what makes the
            # exemption checkable; if git ever produced a conflicted file the
            # check would accept, this goes red and the exemption can be
            # narrowed on evidence instead of being believed.
            gmpremise = M.anchor_verdict(gmmarkers, M.merge_text(gmrows))
            check("mg3c the F328 target check is NOT asked about the index path, "
                  "and here is why it must not be: the conflicted working copy "
                  "this merge replaced does not itself hold the result in order "
                  "(held=%r, first row it cannot account for %r), so asking "
                  "would refuse every genuine conflict resolution -- while the "
                  "loss F328 is about cannot happen here at all, because both "
                  "sides ARE stages of this file"
                  % (gmpremise["held"], gmpremise["row"]),
                  code == 0 and "REFUSED" not in txt
                  and gmpremise["held"] is False, txt)
            # F342: A RE-RUN IS NOT A ROW SOMEBODY TYPED, AND THE VERDICT MAY
            # NOT DEPEND ON WHICH SECOND IT LANDS IN. Re-running the verb over
            # a file it has already resolved was refused with `_conflict_loss`'s
            # sentence -- "A row typed into a conflicted journal while resolving
            # it ... Append it again after the merge" -- about a row nobody
            # typed. Worse, WHETHER it was refused came down to the wall clock:
            # `_merge_marker` stamps `max(last row, now)` at second resolution,
            # so a re-run inside the same second rebuilds the previous marker
            # byte for byte and nothing is unaccounted for, while a re-run a
            # second later leaves it unaccounted and is refused.
            #
            # THIS ONE IS THE SAME-SECOND HALF, deliberately run with nothing
            # between it and the merge above: on the old code it exited 0 and
            # silently rewrote the file. mg3d below is the other half and
            # crosses a second boundary on purpose. Both must now give the same
            # answer, which is what "does not depend on the clock" means.
            with open(gmfile, "r", encoding="utf-8") as fh:
                gmresolved = fh.read()
            gmrcode, gmrtxt = run(["merge", "--file", gmrel], gm)
            with open(gmfile, "r", encoding="utf-8") as fh:
                gmrerun = fh.read()
            check("mg3f re-running the verb over a file it has ALREADY resolved "
                  "is refused, and the refusal names what is actually there -- "
                  "a `%s` row neither stage holds, which is the trail's only "
                  "record of the first resolution and would be dropped by a "
                  "fresh one. Nothing typed, nothing to append again"
                  % (M.MERGE_ACTION,),
                  gmrcode == 1 and "already holds a `%s` row" % (M.MERGE_ACTION,)
                  in gmrtxt and "already been resolved by this command" in gmrtxt
                  and "typed into a conflicted journal" not in gmrtxt
                  and gmrerun == gmresolved, gmrtxt)
            # ...AND THE HOLE THAT EXEMPTION USED TO LEAVE. A row typed INTO the
            # conflicted file is in neither stage, so no union of the two can
            # hold it and the order-aware check above is not the one that can
            # ask. `rows_unaccounted` is, and this drives it through `main`:
            # the index stages survive an uncommitted merge, so re-running after
            # appending a row exercises exactly that path.
            #
            # A SECOND BOUNDARY IS CROSSED FIRST, ON PURPOSE. mg3d and mg3e used
            # to depend on both runs landing in one wall-clock second: past it,
            # the previous marker row is unaccounted for too, it sits EARLIER in
            # the file than the typed row, and the single "first missing row"
            # the old refusal named was therefore the marker -- so mg3e's
            # `(task.note)` went red on any machine slow enough, which CI is.
            # The refusals are partitioned by what the row IS now, so the typed
            # row is named whichever second this lands in; the sleep is here to
            # make sure it is the harder one.
            _cross_second()
            # The file is RESTORED below before the block goes on: the cases
            # after this one grade this same resolution against git, and a row
            # left behind here turns three of them red for a reason that has
            # nothing to do with what they assert. Found by doing exactly that.
            try:
                with open(gmfile, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(
                        {"ts": "2026-08-09T00:00:00Z", "action": "task.note",
                         "target": "P1.9", "summary": "typed while resolving",
                         "prev": None, "hash": "0" * 12}) + "\n")
                with open(gmfile, "r", encoding="utf-8") as fh:
                    gmtyped = fh.read()
                gmtcode, gmttxt = run(["merge", "--file", gmrel], gm)
                with open(gmfile, "r", encoding="utf-8") as fh:
                    gmafter = fh.read()
            finally:
                with open(gmfile, "w", encoding="utf-8") as fh:
                    fh.write(gmresolved)
            check("mg3d a row somebody typed INTO the conflicted file is in no "
                  "stage, so the union cannot hold it -- REFUSED rather than "
                  "written, and the row is still there afterwards. This is the "
                  "one loss the index path could still take, and the check that "
                  "catches it asks about PRESENCE alone because mg3c's premise "
                  "is exactly why it cannot ask about order",
                  gmtcode == 1 and "in NEITHER side the index holds" in gmttxt
                  and "typed while resolving" in gmafter
                  and gmafter == gmtyped, gmttxt)
            check("mg3e ...and it names the row by its ACTION -- the typed one, "
                  "not the marker row that is also unaccounted for a second "
                  "later -- so the sentence reads like the other refusal's "
                  "rather than printing content into a terminal, and reads the "
                  "same in every second",
                  "(task.note)" in gmttxt and "typed while resolving" not in
                  gmttxt, gmttxt)
            check("mg3e2 ...and the two facts are reported APART: the file was "
                  "already resolved AND a row was typed into it, which are two "
                  "acts with two repairs. One list, one refusal each, and "
                  "neither sentence claiming the other's cause",
                  "already been resolved by this command" in gmttxt
                  and "in NEITHER side the index holds" in gmttxt
                  and gmttxt.count("REFUSED:") == 2, gmttxt)
            gmres = M.verify(gm, gmcfg)
            with open(gmfile, "rb") as fh:
                gmmerged = fh.read()
            check("mg4 THE HALF THAT MAKES THE VERB USABLE: `verify` calls the "
                  "resolution CLEAN even though HEAD's bytes are no longer a "
                  "prefix of it (%r) -- the old proxy reported every sound "
                  "resolution as broken, so the tool that was meant to grade a "
                  "resolution rejected its own output"
                  % (gmmerged.startswith(gmhead),),
                  gmres["ok"] and not gmres["findings"]
                  and not gmmerged.startswith(gmhead)
                  and len(gmhead) > 0, repr(gmres["findings"]))
            check("mg5 ...and it does not pass in SILENCE: the re-linking is a "
                  "WARNING that names what it was and where to check it, "
                  "because a row inserted between committed rows is what the "
                  "byte prefix used to forbid outright: %s"
                  % (_output.some_of(gmres["warnings"]),),
                  any("no row's content changed" in w
                      and "merge commit" in w for w in gmres["warnings"]),
                  repr(gmres["warnings"]))
            # `.get` rather than `[...]`: proving mg6 red means DELETING the
            # marker row, which makes the key absent - and a case that raises
            # takes every case after it out of the run while naming none.
            gmmarker = gmrows[-1] if gmrows else {}
            check("mg6 the file itself records that it was re-chained -- the "
                  "operation is auditable in the trail and not only in git",
                  (gmmarker.get("actor") or {}).get("via") == M.MERGE_VIA
                  and gmname in (gmmarker.get("summary") or "")
                  and "only `prev`/`hash` recomputed"
                  in (gmmarker.get("summary") or ""),
                  repr(gmmarker.get("summary")))
            gmgit("add", "-A")
            gmgit("commit", "-q", "-m", "merged")
            check("mg7 once the resolution is committed the fast path is back: "
                  "HEAD equals the working copy, so nothing is warned about and "
                  "nothing is parsed to say so",
                  M.verify(gm, gmcfg)["ok"]
                  and not M.verify(gm, gmcfg)["warnings"],
                  repr(M.verify(gm, gmcfg)["warnings"]))
            # SECOND DIRECTION, and the case this whole change has to survive: a
            # forger who rewrites a committed row's CONTENT and recomputes every
            # hash forward still has to get past the anchor.
            with open(gmfile, "rb") as fh:
                gmpristine = fh.read()
            gmforged, gmprev = [], M.genesis_prev(gmname)
            for r in M.read_file(gmfile)[0]:
                r = dict(r)
                if not gmforged:
                    r["summary"] = "nothing happened"
                r["prev"] = gmprev
                r["hash"] = M.row_hash({k: v for k, v in r.items()
                                        if k != "hash"})
                gmprev = r["hash"]
                gmforged.append(r)
            rewrite(gmfile, gmforged)
            gmbad = M.verify(gm, gmcfg)
            check("mg8 a committed row whose CONTENT was rewritten is STILL a "
                  "FINDING, and exactly one -- the anchor asks about rows now "
                  "instead of bytes, and a rule loosened to admit a merge would "
                  "have admitted this too: %s"
                  % (_output.some_of(gmbad["findings"]),),
                  not gmbad["ok"] and len(gmbad["findings"]) == 1
                  and "committed past changed" in gmbad["findings"][0]
                  and "content" in gmbad["findings"][0],
                  repr(gmbad["findings"]))
            with open(gmfile, "wb") as fh:
                fh.write(gmpristine)
            check("mg9 restored byte for byte, it verifies again",
                  M.verify(gm, gmcfg)["ok"],
                  repr(M.verify(gm, gmcfg)["findings"]))
            code, txt = run(["merge", "--file", gmrel], gm)
            check("mg10 with no conflict open there are no index stages to "
                  "read, and that is a usage error naming what to do instead -- "
                  "never a merge of the working copy with itself, which would "
                  "report the other side's rows as absent",
                  code == 2 and "could not read the ours side" in txt
                  and "--ours/--theirs" in txt, txt)
            code, txt = run(["merge"], gm)
            check("mg11 merge with no --file is a usage error that says the "
                  "basename is what seeds the chain",
                  code == 2 and "seeds the chain" in txt, txt)
            code, txt = run(["merge", "--file", gmrel, "--ours", gmfile], gm)
            check("mg12 --ours without --theirs is a usage error rather than a "
                  "merge of one side with a default",
                  code == 2 and "go together" in txt, txt)
            code, txt = run(["merge", "--file", "notes.txt"], gm)
            check("mg12b a --file that is not a .jsonl journal file is refused "
                  "before anything is read",
                  code == 2 and ".jsonl" in txt, txt)
            # Two whole files under one name, sharing no history: the refusal
            # this must never talk itself out of.
            gmalien = os.path.join(tmp, "alien.jsonl")
            with open(gmalien, "w", encoding="utf-8") as fh:
                fh.write("")
            code, txt = run(["merge", "--file", gmrel, "--ours", gmfile,
                             "--theirs", gmalien], gm)
            check("mg13 an empty side is refused and nothing is written: a side "
                  "with no rows is not a divergence, and treating it as one "
                  "would overwrite the file with one branch's tail",
                  code == 1 and "REFUSED" in txt
                  and "not a divergence" in txt, txt)

        # --- mh: the same verb over two files a caller extracted itself -------
        # No git here on purpose: the index is the DEFAULT source and not the
        # only one, because a conflict resolved days ago no longer has stages -
        # and this arm is where the auditability claim has no evidence, which is
        # the second direction for mg3b.
        mhcfg = {"journal": {"dir": "j"}}

        def mhput(root, summary, ts, action="manifest.edit"):
            return M.append(root, {"action": action, "target": "",
                                   "summary": summary, "ts": ts,
                                   "actor": {"sessionId": "s-hand",
                                             "via": "hook"}}, config=mhcfg)

        def diverged(tag):
            """One file name and two divergent copies of it, with the target
            INTACT: (project, live path, basename, ours path, theirs path).

            The shape a conflict resolved days ago leaves behind. `project`'s
            live file holds the shared row and `mine`; `ours` is a copy of that
            file taken as it stands, so it is a faithful side rather than a stale
            one; `theirs` is a sibling project's copy of the same name holding
            the shared row and `yours`.

            A BUILDER RATHER THAN A BLOCK OF SETUP, because the cases below
            differ only in what they ASK of one fixture and a second hand-built
            copy of it is how two of them would come to be asking about
            different things. The config is written ON DISK as well as passed:
            `run` goes through `main`, which loads the project's own."""
            root = os.path.join(tmp, tag)
            os.makedirs(os.path.join(root, ".claude"))
            with open(os.path.join(root, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                fh.write('{"journal": {"dir": "j"}}')
            mhput(root, "shared", "2026-08-01T00:00:00Z")
            live = M.journal_files(M.journal_dir(root, mhcfg))[0]
            side = os.path.join(tmp, tag + "-side")
            shutil.copytree(root, side)
            mhput(root, "mine", "2026-08-02T00:00:00Z", action="task.complete")
            ours = os.path.join(tmp, tag + "-ours.jsonl")
            shutil.copyfile(live, ours)
            mhput(side, "yours", "2026-08-03T00:00:00Z", action="task.commit")
            return (root, live, os.path.basename(live), ours,
                    M.journal_files(M.journal_dir(side, mhcfg))[0])

        mh, mhfile, mhname, mhours, mhtheirs = diverged("byhand")
        code, txt = run(["merge", "--file", "j/" + mhname, "--ours", mhours,
                         "--theirs", mhtheirs], mh)
        check("mh1 two files named explicitly merge the same way, so a conflict "
              "whose index stages are long gone is still resolvable: %r"
              % ([r.get("summary") for r in M.read_file(mhfile)[0]][:3],),
              code == 0
              and [r.get("summary") for r in M.read_file(mhfile)[0]][:3]
              == ["shared", "mine", "yours"]
              and M.verify(mh, mhcfg)["ok"], txt)
        check("mh2 SECOND DIRECTION for mg3b: over files it was handed, the "
              "command does NOT claim both inputs are in git -- it says it "
              "cannot know, because a claim whose basis is missing is the thing "
              "to say rather than the thing to assume",
              "Nothing here can say" in txt
              and "came from the index" not in txt, txt)
        # mh3 USED TO ASSERT THE F328 BUG AS CORRECT BEHAVIOUR. It merged this
        # two-row extract against itself over the LIVE file mh1 had just grown to
        # four rows, and the assertion it made - exit 0, no divergence, nothing
        # re-chained - was true of the two INPUTS while the file went from four
        # rows to two. Its stated subject was "re-running a resolution cannot
        # keep appending marker rows", which is not what that fixture does:
        # re-running the resolution means passing the same two sides again. What
        # the fixture actually asks about is `merge_rows`'s no-divergence branch,
        # so it now asks it over a target the result really does hold - the same
        # question with the data loss taken out of the setup.
        mh3, mh3file, mh3name, mh3ours, _mh3theirs = diverged("selfmerge")
        code, txt = run(["merge", "--file", "j/" + mh3name, "--ours", mh3ours,
                         "--theirs", mh3ours], mh3)
        mh3rows = M.read_file(mh3file)[0]
        check("mh3 a copy merged against ITSELF is no divergence and no error: "
              "the longer side already holds every row of the other, so nothing "
              "is re-chained and NO `%s` row is added -- the file comes out "
              "holding exactly what it held (%r)"
              % (M.MERGE_ACTION, [r.get("summary") for r in mh3rows]),
              code == 0 and "no divergence" in txt and "0 re-linked" in txt
              and [r.get("summary") for r in mh3rows] == ["shared", "mine"]
              and [r.get("action") for r in mh3rows].count(M.MERGE_ACTION) == 0
              and M.verify(mh3, mhcfg)["ok"], txt)
        # F328, AND IT IS THE REALISTIC MISTAKE RATHER THAN AN EXOTIC ONE.
        # `--ours/--theirs` exists for a conflict resolved days ago, so a side
        # that has fallen behind the live file is what a caller actually reaches
        # for - and `--file` names the TARGET, never a side, so its rows were
        # read by nothing. `mhours` is now exactly that: a two-row extract of a
        # file mh1 grew to four. The genesis refusal cannot see it, because a
        # stale extract of this file begins at the RIGHT genesis.
        with open(mhfile, "rb") as fh:
            mh4before = fh.read()
        code, txt = run(["merge", "--file", "j/" + mhname, "--ours", mhours,
                         "--theirs", mhours], mh)
        with open(mhfile, "rb") as fh:
            mh4after = fh.read()
        check("mh4 a side that is a STALE EXTRACT of the target is REFUSED, and "
              "the refusal names the row that would have gone: the result is "
              "graded against the file it would replace, because a merge may "
              "re-link and may not lose a row",
              code == 1 and "REFUSED" in txt and "STALE EXTRACT" in txt
              and "task.commit" in txt and "nothing written" in txt, txt)
        check("mh4b ...and NOTHING was written: byte for byte the file mh1 left, "
              "still chaining. This is the whole finding -- every sentence the "
              "old code printed was a claim about the two INPUTS and read as a "
              "claim about the FILE, `no row's content touched` included, so the "
              "loss was silent and `verify` called the survivor clean",
              mh4after == mh4before
              and len(M.read_file(mhfile)[0]) == 4
              and M.verify(mh, mhcfg)["ok"],
              repr([r.get("summary") for r in M.read_file(mhfile)[0]]))
        code, txt = run(["merge", "--file", "j/" + mhname, "--ours", mhours,
                         "--theirs", mhours, "--dry-run"], mh)
        check("mh5 --dry-run REVEALS it too, which is the point of a preview: it "
              "used to print the same input-side counts as the write, so the one "
              "flag a careful operator reaches for could not show the loss",
              code == 1 and "REFUSED" in txt and "STALE EXTRACT" in txt
              and "left as it is" not in txt, txt)
        code, txt = run(["merge", "--file", "j/" + mhname, "--ours", mhours,
                         "--theirs", mhours, "--json"], mh)
        _mh6 = parsed(txt, {})
        check("mh6 ...and so does --json, in the same verdict rather than a "
              "second opinion: refused, no rows and no text for a caller to "
              "write out by accident, and `written` false",
              code == 1 and _mh6.get("ok") is False
              and len(_mh6.get("refusals") or []) == 1
              and "STALE EXTRACT" in (_mh6.get("refusals") or [""])[0]
              and _mh6.get("rows") == [] and _mh6.get("text") == ""
              and _mh6.get("written") is False, txt)
        with open(mhfile, "rb") as fh:
            mh6after = fh.read()
        check("mh6b ...and the file is still byte for byte the one mh1 left: a "
              "refused `--json` merge writes nothing either, which is the half a "
              "payload can never be trusted to report about itself",
              mh6after == mh4before,
              repr([r.get("summary") for r in M.read_file(mhfile)[0]]))
        # THE TWO ANSWERS `_target_now` KEEPS APART, each with its own case,
        # because collapsing them is how this guard would go quiet: a target that
        # is not there holds no row and a target that cannot be read is a
        # question nobody could ask. Every `diverged()` fixture writes the SAME
        # basename (one month, one writer id), so `mhours`/`mhtheirs` are a valid
        # pair for any of these projects -- the chain seed is that name.
        #
        # A DIRECTORY is how "there and unreadable" is spelled portably: `open`
        # raises on it everywhere, while a permission bit does not (a mode of 000
        # is no obstacle to root, which is who CI containers usually are).
        mu = os.path.join(tmp, "unreadable")
        os.makedirs(os.path.join(mu, ".claude"))
        with open(os.path.join(mu, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"journal": {"dir": "j"}}')
        os.makedirs(os.path.join(mu, "j", mhname))
        code, txt = run(["merge", "--file", "j/" + mhname, "--ours", mhours,
                         "--theirs", mhtheirs], mu)
        check("mh7 a target that IS there and cannot be read is a REFUSAL, not a "
              "pass: this command replaces that file, so an empty read standing "
              "in for its contents would let the guard clear a merge of "
              "everything it could not see",
              code == 1 and "REFUSED" in txt and "could not be read" in txt
              and "nothing written" in txt, txt)
        # SECOND DIRECTION, and the one a guard like this gets wrong by
        # over-firing: the first write of a name is not a loss of anything.
        mn = os.path.join(tmp, "no-target-yet")
        os.makedirs(os.path.join(mn, ".claude"))
        with open(os.path.join(mn, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"journal": {"dir": "j"}}')
        os.makedirs(os.path.join(mn, "j"))
        code, txt = run(["merge", "--file", "j/" + mhname, "--ours", mhours,
                         "--theirs", mhtheirs], mn)
        mnrows = M.read_file(os.path.join(mn, "j", mhname))[0]
        check("mh8 a target that does not exist yet is NOT a refusal -- it holds "
              "no row, so there is nothing a merge could take from it, and the "
              "union is written under that name: %r"
              % ([r.get("summary") for r in mnrows],),
              code == 0 and "REFUSED" not in txt
              and [r.get("summary") for r in mnrows][:3]
              == ["shared", "mine", "yours"]
              and M.verify(mn, mhcfg)["ok"], txt)

        # --- F341: the TARGET's own bytes are graded too ----------------------
        # The F328 repair closed the door it was reported through and left the
        # room open. `_merge_input_faults` refuses a torn or unparseable SIDE
        # and says why -- those bytes are not a row, so a merge would drop them
        # and say nothing -- while nothing asked that of the file being
        # OVERWRITTEN. `anchor_verdict` cannot: it drops `_unparseable` rows
        # from the committed side before comparing, so such a row can never be
        # reported missing, and its docstring justifies that with "`verify`'s
        # own per-row pass is what reports one in the WORKING copy" -- true
        # where the git anchor calls it, false here, where the working copy
        # ceases to exist.
        #
        # THE ROW IS ONE NEITHER SIDE HOLDS, which is what makes the loss
        # visible: a torn row whose content the sides also carry would be
        # rebuilt by the merge and the fixture would pass on the broken code.
        mt, mtfile, mtname, mtours, mttheirs = diverged("torn-target")
        mhput(mt, "half-written-by-a-crash", "2026-08-09T00:00:00Z",
              action="task.note")
        with open(mtfile, "r", encoding="utf-8") as fh:
            mttext = fh.read()
        mtcut = mttext[:len(mttext) - 40]
        with open(mtfile, "w", encoding="utf-8") as fh:
            fh.write(mtcut)
        code, txt = run(["merge", "--file", "j/" + mtname, "--ours", mtours,
                         "--theirs", mttheirs], mt)
        with open(mtfile, "r", encoding="utf-8") as fh:
            mtafter = fh.read()
        check("mh9 a TARGET whose last line a crash left half-written is "
              "REFUSED: those bytes are not a row, nothing can say whether the "
              "merge still holds them, and this command replaces the file. It "
              "used to exit 0 saying `wrote %s` with them gone" % (mtname,),
              code == 1 and "REFUSED" in txt and "partial line" in txt
              and "nothing written" in txt and "wrote " not in txt, txt)
        check("mh9b ...and the bytes are still there afterwards, byte for "
              "byte, so a torn tail stays the operator's to truncate on "
              "purpose -- `verify` goes on warning about it rather than the "
              "warning being resolved by deletion",
              mtafter == mtcut
              and any("torn" in w or "partial" in w
                      for w in M.verify(mt, mhcfg)["warnings"]),
              repr(M.verify(mt, mhcfg)["warnings"]))
        # A CORRUPTED ROW MID-FILE IS THE SAME CLASS AND A DIFFERENT LINE:
        # `verify` grades it a FINDING rather than a warning, and the merge
        # took it away just as quietly.
        mc, mcfile, mcname, mcours, mctheirs = diverged("corrupt-target")
        with open(mcfile, "r", encoding="utf-8") as fh:
            mclines = fh.read().splitlines()
        mclines.insert(1, '{"ts": "2026-08-01T12:00:00Z", "action": "task.no')
        with open(mcfile, "w", encoding="utf-8") as fh:
            fh.write("\n".join(mclines) + "\n")
        mcbefore = "\n".join(mclines) + "\n"
        code, txt = run(["merge", "--file", "j/" + mcname, "--ours", mcours,
                         "--theirs", mctheirs], mc)
        with open(mcfile, "r", encoding="utf-8") as fh:
            mcafter = fh.read()
        check("mh10 a corrupted row that is NOT the last line is refused too, "
              "named by the line it is on -- `verify` calls that a finding, and "
              "a merge that overwrote it would have closed the finding by "
              "deleting the evidence for it",
              code == 1 and "REFUSED" in txt and "line 2 is not valid JSON" in
              txt and mcafter == mcbefore
              and not M.verify(mc, mhcfg)["ok"], txt)

        # --- F343: --file must name a file in the trail -----------------------
        # `in_journal` was already in the module and called by nobody. Only the
        # `.jsonl` suffix was checked, so `--file <basename>` -- exactly what an
        # operator copies out of git's conflict message -- resolved against the
        # project root, where a name holding no row cannot lose one, and the
        # merge was written there. The live journal was untouched, `verify`
        # passed, and `journal_files` cannot see the stray file, so every
        # surface agreed nothing had happened.
        ms, msfile, msname, msours, mstheirs = diverged("stray")
        with open(msfile, "rb") as fh:
            msbefore = fh.read()
        code, txt = run(["merge", "--file", msname, "--ours", msours,
                         "--theirs", mstheirs], ms)
        with open(msfile, "rb") as fh:
            msafter = fh.read()
        check("mh11 a --file that resolves OUTSIDE the journal directory is a "
              "usage error naming the directory it must be in, and nothing is "
              "written anywhere: the stray path is where the merge used to "
              "land, invisible to every reader of the trail",
              code == 2 and "inside the journal directory" in txt
              and not os.path.exists(os.path.join(ms, msname))
              and msafter == msbefore, txt)
        code, txt = run(["merge", "--file", os.path.join(tmp, "elsewhere.jsonl"),
                         "--ours", msours, "--theirs", mstheirs], ms)
        check("mh11b ...and an ABSOLUTE path outside it is refused by the same "
              "question rather than by the relative-path spelling, because the "
              "check is about where the file IS and not how it was written",
              code == 2 and "inside the journal directory" in txt
              and not os.path.exists(os.path.join(tmp, "elsewhere.jsonl")), txt)

        # --- F342 on the path that has no index ------------------------------
        # The same defect the mg block drives through a real conflict, on the
        # arm where the two sides are files the caller named: re-running over a
        # file this verb already resolved was refused with the STALE EXTRACT
        # sentence -- wrong cause, wrong advice -- or not refused at all, and
        # which of the two came down to the wall-clock second. The boundary is
        # crossed on purpose so this is the branch where the marker row no
        # longer matches, which is the one that used to print the wrong reason.
        mp, mpfile, mpname, mpours, mptheirs = diverged("rerun-byhand")
        code, txt = run(["merge", "--file", "j/" + mpname, "--ours", mpours,
                         "--theirs", mptheirs], mp)
        with open(mpfile, "rb") as fh:
            mpfirst = fh.read()
        _cross_second()
        code, txt = run(["merge", "--file", "j/" + mpname, "--ours", mpours,
                         "--theirs", mptheirs], mp)
        with open(mpfile, "rb") as fh:
            mpsecond = fh.read()
        check("mh12 re-running with the SAME two sides over a file already "
              "resolved is refused with the reason that is true of it -- a "
              "`%s` row neither side holds -- and not with the stale-extract "
              "sentence, whose advice is to re-extract sides that are not the "
              "problem" % (M.MERGE_ACTION,),
              code == 1 and "already been resolved by this command" in txt
              and "STALE EXTRACT" not in txt
              and mpsecond == mpfirst, txt)
        # SECOND DIRECTION, and the mutation this repair could have made
        # instead: answering "already resolved" to every merge over a file that
        # holds a marker row, which would stop naming the row actually at risk.
        # Same already-resolved target, but the sides are now the two-row
        # extract it has outgrown -- a real row is being lost, and THAT is the
        # news rather than the marker.
        code, txt = run(["merge", "--file", "j/" + mpname, "--ours", mpours,
                         "--theirs", mpours], mp)
        with open(mpfile, "rb") as fh:
            mpthird = fh.read()
        check("mh12b ...and a STALE side over that same resolved file still "
              "gets the stale-extract sentence naming the row that would go: a "
              "marker row in the target is not what makes a refusal fire, and "
              "a guard that answered `already resolved` to every merge over a "
              "merged file would have stopped naming the row at risk",
              code == 1 and "STALE EXTRACT" in txt and "task.commit" in txt
              and "already been resolved by this command" not in txt
              and mpthird == mpfirst, txt)

        # --- mj: `merge --json` renders the operation, it does not change it ---
        # F331. `--json` returned BEFORE the write, so it printed `"ok": true`
        # with a full row list over a file it had not touched -- and
        # `--json --dry-run` printed byte-identical output, which left a caller
        # no way at all to tell a write from a preview. Nothing covered
        # `merge --json` here at all, which is how it shipped that way.
        mj, mjfile, mjname, mjours, mjtheirs = diverged("json-writes")
        code, txt = run(["merge", "--file", "j/" + mjname, "--ours", mjours,
                         "--theirs", mjtheirs, "--json"], mj)
        _mj1 = parsed(txt, {})
        with open(mjfile, "r", encoding="utf-8") as fh:
            mjdisk = fh.read()
        check("mj1 `--json` WRITES and SAYS it wrote: the payload's `text` is "
              "byte for byte what is now on disk, so the claim carries the thing "
              "that makes it true rather than describing an intention",
              code == 0 and _mj1.get("ok") is True
              and _mj1.get("written") is True and _mj1.get("dryRun") is False
              and _mj1.get("text") == mjdisk
              and [r.get("summary") for r in M.read_file(mjfile)[0]][:3]
              == ["shared", "mine", "yours"]
              and M.verify(mj, mhcfg)["ok"], txt)
        # SECOND DIRECTION, and it is the mutation the repair could have made
        # instead: `--json` suppressing the write would satisfy mj1's shape only
        # if `written` were then a lie, and this is the case that fails when the
        # two flags stop being independent.
        mk, mkfile, mkname, mkours, mktheirs = diverged("json-dry")
        with open(mkfile, "rb") as fh:
            mkbefore = fh.read()
        code, txt = run(["merge", "--file", "j/" + mkname, "--ours", mkours,
                         "--theirs", mktheirs, "--json", "--dry-run"], mk)
        _mj2 = parsed(txt, {})
        with open(mkfile, "rb") as fh:
            mkafter = fh.read()
        check("mj2 `--json --dry-run` is the flag that withholds the write, and "
              "the payload is where the two are told apart: `dryRun` true, "
              "`written` false, the rows still rendered for a caller to read, "
              "and the file untouched. The two outputs used to be byte-identical",
              code == 0 and _mj2.get("ok") is True
              and _mj2.get("dryRun") is True and _mj2.get("written") is False
              and len(_mj2.get("rows") or []) == 4
              and mkafter == mkbefore, txt)
        # A WRITE THAT FAILED MUST NOT READ AS ONE THAT HAPPENED, in either
        # rendering. The write is now made BEFORE anything is printed, so this is
        # the path that shape has to get right - and the failure is arranged
        # through a `--file` under a directory that is not there, which is an
        # operator's typo rather than a fact about how `write_merged` names its
        # temporary file: a fixture resting on that internal would go red on a
        # rename that broke nothing.
        mw, _mwfile, mwname, mwours, mwtheirs = diverged("write-fails")
        mwmissing = "j/" + os.path.join("nowhere", mwname).replace(os.sep, "/")
        code, txt = run(["merge", "--file", mwmissing, "--ours", mwours,
                         "--theirs", mwtheirs], mw)
        check("mj3 a write that FAILED exits 1 and says so, after the summary "
              "rather than instead of it -- the counts describe a result that "
              "was computed, and the closing line is what says it did not land",
              code == 1 and "could not write" in txt
              and "wrote " not in txt
              and not os.path.exists(os.path.join(mw, "j", "nowhere")), txt)
        code, txt = run(["merge", "--file", mwmissing, "--ours", mwours,
                         "--theirs", mwtheirs, "--json"], mw)
        _mj4 = parsed(txt, {})
        check("mj4 ...and `--json` carries the same failure as DATA: `ok` stays "
              "true because the merge itself was sound, `written` is false, and "
              "`error` is the reason -- a payload with a full row list and no "
              "`written` key is exactly what F331 was",
              code == 1 and _mj4.get("ok") is True
              and _mj4.get("written") is False
              and _mj4.get("dryRun") is False
              and bool(_mj4.get("error")), txt)

        # --- mr: a REAL append racing the merge's write (F340) ----------------
        # The F328 repair graded the result against the target and then called
        # `write_merged`, which took the lock. So the read that graded happened
        # BEFORE the lock existed, and a row appended in between was graded by
        # nobody and deleted by `os.replace` -- exit 0, `wrote <name>`, and
        # `verify` reporting the survivors chain cleanly. That is F328's own
        # signature moved from "the target was never read" to "read too early".
        #
        # DRIVEN, NOT MOCKED. A separate `audit-journal.py append` PROCESS
        # appends a real row through the real code path and contends for the
        # real lock; `mv1` next door is the deterministic structural pin under
        # this and asserts the lock is held while the grader runs. The only
        # thing injected here is WHEN that process starts -- at the grading,
        # which is the window -- and the seam is `anchor_verdict`, the same
        # patch-the-module idiom k5-k8 use, restored in a `finally`.
        #
        # WHAT MAKES IT DETERMINISTIC rather than a hopeful sleep: the seam
        # WATCHES THE FILE. On the broken code nothing blocks the child, so its
        # row appears and the watch returns at once -- the row is provably on
        # disk before the grading reads a thing, which is the losing
        # interleaving, arranged rather than hoped for. With the lock held
        # across the grade the row cannot appear and the watch runs out. Either
        # way the case asserts one thing: a row the appender said it wrote is
        # still in the file afterwards.
        #
        # THE WATCH IS SHORTER THAN `LOCK_WAIT_SECONDS` AND DERIVED FROM IT.
        # The child gives up on the lock that long after it first tries, so a
        # watch that outlasted it would turn the fixed code's honest wait into
        # a refused append and prove nothing -- which is exactly what a flat
        # timeout longer than the product's own patience did on the first run
        # of this case.
        #
        # THE MONTH IS THE CURRENT ONE because the appender cannot be given a
        # timestamp -- `append` has no --ts -- so a fixture written in a fixed
        # month would put its row in a DIFFERENT file, and a race with no
        # shared file is not a race. The session id matches for the same
        # reason: the writer id is what names the file.
        mrmonth = time.strftime("%Y-%m", time.gmtime())
        mr = os.path.join(tmp, "raced")
        os.makedirs(os.path.join(mr, ".claude"))
        with open(os.path.join(mr, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"journal": {"dir": "j"}}')
        mhput(mr, "shared", mrmonth + "-01T00:00:00Z")
        mrfile = M.journal_files(M.journal_dir(mr, mhcfg))[0]
        mrname = os.path.basename(mrfile)
        mrside = os.path.join(tmp, "raced-side")
        shutil.copytree(mr, mrside)
        mhput(mr, "mine", mrmonth + "-01T00:00:01Z", action="task.complete")
        mrours = os.path.join(tmp, "raced-ours.jsonl")
        shutil.copyfile(mrfile, mrours)
        mhput(mrside, "yours", mrmonth + "-01T00:00:02Z", action="task.commit")
        mrtheirs = M.journal_files(M.journal_dir(mrside, mhcfg))[0]
        mrstate = {"child": None, "atgrade": "the grader never ran"}
        _mr_real = M.anchor_verdict

        def _mr_landed():
            try:
                with open(mrfile, "r", encoding="utf-8") as fh:
                    return "raced-append" in fh.read()
            except Exception:
                return False

        def _mr_seam(committed, working):
            if mrstate["child"] is None:
                mrstate["child"] = subprocess.Popen(
                    [sys.executable, _loader.script_path("audit-journal.py"),
                     "append", "--action", "task.note",
                     "--summary", "raced-append", "--session", "s-hand",
                     "--project", mr],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                mrstate["atgrade"] = "its row had not landed"
                deadline = time.time() + M.LOCK_WAIT_SECONDS * 0.6
                while time.time() < deadline:
                    if _mr_landed():
                        mrstate["atgrade"] = "its row was ALREADY on disk"
                        break
                    if mrstate["child"].poll() is not None:
                        mrstate["atgrade"] = ("gone, exit %d"
                                              % mrstate["child"].returncode)
                        break
                    time.sleep(0.02)
            return _mr_real(committed, working)

        try:
            M.anchor_verdict = _mr_seam
            code, txt = run(["merge", "--file", "j/" + mrname,
                             "--ours", mrours, "--theirs", mrtheirs], mr)
        finally:
            M.anchor_verdict = _mr_real
        mrout = ""
        if mrstate["child"] is not None:
            mrout = (mrstate["child"].communicate()[0]
                     or b"").decode("utf-8", "replace")
            mrstate["child"].wait()
        mrrows = M.read_file(mrfile)[0]
        mrsums = [r.get("summary") for r in mrrows]
        check("mr1 a row a SECOND PROCESS appended while the merge was grading "
              "its result is still in the file afterwards. The appender "
              "reported the write and the merge reported its own (exit %d); on "
              "the old code both were true and the row was gone, because the "
              "grading read the file before the lock existed: %r"
              % (code, mrsums),
              code == 0 and "raced-append" in mrsums
              and mrstate["child"].returncode == 0
              and "could not append" not in mrout
              and mrsums[:3] == ["shared", "mine", "yours"], txt)
        check("mr2 ...and the losing interleaving really was ATTEMPTED rather "
              "than having quietly not happened: when the grading ran, the "
              "appender's row %s. A run where the child had already landed it "
              "is the broken code; a run where the child never started would "
              "assert nothing at all, and both are named apart from this one"
              % (mrstate["atgrade"],),
              mrstate["atgrade"] == "its row had not landed"
              and mrstate["child"] is not None, repr(mrstate["atgrade"]))
        mrres = M.verify(mr, mhcfg)
        mrmarker = mrrows[-2] if len(mrrows) > 1 else {}
        check("mr3 ...and it landed AFTER the merge rather than beside it: the "
              "raced row's `prev` is the hash of the `%s` row, so the two "
              "writers were serialised by the lock and the chain the merge "
              "wrote is the one the append extended. A row chained onto a tail "
              "the merge had already replaced is the break that reads exactly "
              "like a deleted row" % (M.MERGE_ACTION,),
              mrres["ok"] and not mrres["findings"]
              and mrmarker.get("action") == M.MERGE_ACTION
              and mrrows[-1].get("prev") == mrmarker.get("hash"),
              repr((mrres["findings"], [r.get("action") for r in mrrows])))

        # --- sx: which session wrote which file (F309) -------------------------
        # The file NAME carries the writer id the row supplied, truncated to fit
        # a name, and for the hook that writes most rows that is not the id the
        # session reads from Bash. `sessions` is what maps one to the other.
        # THE ENVIRONMENT IS PINNED, not read: this suite runs both inside a
        # Claude Code session (where the variable is set to a real id) and in
        # CI (where it is not), and a case that read whatever the machine
        # exported would assert a different thing on each.
        _sx_held = os.environ.get(M.ENV_SESSION_VAR)
        try:
            os.environ[M.ENV_SESSION_VAR] = "env-side-id"
            sx = os.path.join(tmp, "sessions")
            os.makedirs(os.path.join(sx, ".claude"))
            sxcfg = {"journal": {"dir": "j"}}
            # On DISK as well as in hand: `sessions` is driven through `main`,
            # which loads the project's own config, so a fixture that only held
            # the dict would have the command reading an empty default directory
            # and reporting no journal at all.
            with open(os.path.join(sx, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                fh.write('{"journal": {"dir": "j"}}')
            M.append(sx, {"action": "manifest.edit", "target": "",
                          "summary": "written by a hook",
                          "ts": "2026-06-09T00:00:00Z",
                          "actor": {"sessionId": "payload-side-id",
                                    "via": "hook"}}, config=sxcfg)
            code, txt = run(["sessions"], sx)
            check("sx1 `sessions` reads a file's opaque name back to the id the "
                  "SESSION knows, which is the one thing a per-session file "
                  "name is for and the one thing this name cannot carry",
                  code == 0
                  and "payload-side-id" in txt and "env-side-id" in txt
                  and "writer id in the name   payload-side-id" in txt
                  and "<- this session" in txt, txt)
            code, txt = run(["sessions", "--json"], sx)
            # Through `parsed`, and every read of it is a `.get`: the mutation
            # this case exists for is a `--json` that prints prose, and the
            # unguarded form met it by RAISING - which took sx3 through sx6 out
            # of the run, named none of them, and under-reported the total
            # (F330).
            _sxj = parsed(txt, {})
            _sxf = (_sxj.get("files") or [{}])[0]
            check("sx2 ...and the same mapping is available as JSON, keyed by "
                  "the file, with each id carrying how many rows named it",
                  code == 0 and _sxj.get("env") == "env-side-id"
                  and _sxf.get("sessionIds") == [["payload-side-id", 1]]
                  and _sxf.get("envSessionIds") == [["env-side-id", 1]]
                  and _sxj.get("mine") == [_sxf.get("file")], txt)
            os.environ[M.ENV_SESSION_VAR] = "a-session-that-wrote-nothing"
            code, txt = run(["sessions"], sx)
            check("sx3 SECOND DIRECTION: an id that names no file is SAID to "
                  "name none. A command that printed the listing and stopped "
                  "would read as though the reader had found their rows",
                  code == 0 and "names none of the files above" in txt
                  and "<- this session" not in txt, txt)
            os.environ.pop(M.ENV_SESSION_VAR, None)
            _sx_old = os.path.join(tmp, "sessions-old")
            os.makedirs(os.path.join(_sx_old, ".claude"))
            with open(os.path.join(_sx_old, ".claude", "audit.config.json"),
                      "w", encoding="utf-8") as fh:
                fh.write('{"journal": {"dir": "j"}}')
            M.append(_sx_old, {"action": "manifest.edit", "target": "",
                               "summary": "no alias to record",
                               "ts": "2026-06-09T00:00:00Z",
                               "actor": {"sessionId": "solo-id",
                                         "via": "hook"}}, config=sxcfg)
            code, txt = run(["sessions"], _sx_old)
            check("sx4 a file with no alias row says the gap out loud: absence "
                  "means EITHER the two ids agreed OR the rows predate the "
                  "field, and nothing can tell those apart -- so it does not "
                  "print the reassuring one",
                  code == 0 and "no actor.envSessionId on any row" in txt
                  and "cannot tell those apart" in txt
                  and "is not set here" in txt, txt)
            check("sx5 the mapping never renames anything: the file keeps the "
                  "opaque name it was written under, because that name is the "
                  "chain's genesis seed and a rename would break `verify` on "
                  "every clone that already holds it",
                  os.path.basename(M.journal_files(M.journal_dir(sx, sxcfg))[0])
                  == "2026-06.payload-side-id.jsonl"
                  and M.verify(sx, sxcfg)["ok"],
                  repr(M.journal_files(M.journal_dir(sx, sxcfg))))
            _sx_empty = os.path.join(tmp, "sessions-empty")
            os.makedirs(_sx_empty)
            code, txt = run(["sessions"], _sx_empty)
            check("sx6 a project with no journal says so instead of printing an "
                  "empty listing that reads as 'no session wrote anything'",
                  code == 0 and "no journal yet" in txt, txt)
        finally:
            if _sx_held is None:
                os.environ.pop(M.ENV_SESSION_VAR, None)
            else:
                os.environ[M.ENV_SESSION_VAR] = _sx_held
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
