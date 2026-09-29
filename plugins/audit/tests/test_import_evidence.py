#!/usr/bin/env python3
"""
The cases for `import-evidence.py` - a CI build's evidence ledger file brought
into this checkout WHOLE, after its own chain verifies.

`import-evidence.py` is hyphenated, so it comes through `_loader.load_script`;
`test_record_outside_run.py` is the precedent for that shape and for the
one-`tempfile.mkdtemp()`-removed-in-`finally` fixture.

WHAT IS PINNED, and why each one is here rather than trusted:

- **A VALID SHARD IS COPIED BYTE FOR BYTE**, and `_evidence_io.read_rows` reads
  its rows back afterwards - proving the import is really the same product
  every other reader of this directory already trusts, not a parallel copy
  path with its own idea of what a row is.
- **A CHAIN THAT DOES NOT HOLD IS REFUSED**, over a shard whose second row's
  own `hash` was altered after the fact - the same finding
  `_evidence_io.verify_rows` already reports for an edited row, asked here
  through the CLI door instead of the library one, and NOTHING is written when
  it fires.
- **A NAME COLLISION WITH DIFFERENT BYTES IS REFUSED.** The chain's genesis is
  seeded from the basename alone, so two different files sharing one name
  would read as one chain with two genesis rows - and the file already on
  disk must survive that refusal untouched.
- **THE ALLOW CASE: RE-IMPORTING THE IDENTICAL FILE EXITS 0.** A byte-for-byte
  repeat of an import already done is not an error - it is the same shard
  arriving twice - and this is the case a version that always refused a name
  already on disk would fail.
- **A RUN THE LEDGER ALREADY HOLDS IS REFUSED UNDER ANY OTHER NAME**, naming
  each duplicated id and the file that holds it, with nothing written - and
  its two allow cases beside it (new ids import into a non-empty ledger; the
  identical re-import still reads as already imported). A shard repeating a
  runId among its own rows is refused the same way, naming itself. The holder
  is named from the ledger reader's own read, so a file carrying a non-UTF-8
  byte is still named. A ledger that cannot be read in full refuses too,
  saying the check could not be made and giving the step that clears a torn
  tail, because an unread row is a row that might be the duplicate.
- **THE PROJECT IS THE MANIFEST'S, NOT THE CURRENT DIRECTORY'S.** Typed from
  elsewhere with no `--project-dir`, the shard lands in the manifest's project
  and the printed command names it; a `--project-dir` the manifest does not
  sit under is refused, exit 2; and typed from inside the project the import
  is unchanged.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _evidence_io as _ev                         # noqa: E402
import _journal_io                                 # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("import-evidence.py", modname="import_evidence")


def _manifest():
    return {"meta": {"version": 2},
            "phases": [{"id": "P1", "title": "One", "status": "in_progress",
                        "tasks": [{"id": "P1.1", "title": "a",
                                   "status": "in_progress"}]}]}


def _shard_bytes(basename, rows):
    """A valid, chained ledger file's bytes - the `chain_file` a real writer
    (`_evidence_io.append_row`, `run-test-gate.py --record`) would have
    produced for exactly these rows under this name."""
    chained = _ev.chain_file(rows, basename)
    return ("\n".join(_journal_io.canonical(r) for r in chained) + "\n").encode(
        "utf-8"), chained


def _cases(check):
    root = tempfile.mkdtemp(prefix="import-evidence-selftest-")

    def project():
        d = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(d, ".claude"))
        os.makedirs(os.path.join(d, "docs", "audit"))
        with io.open(os.path.join(d, ".claude", "audit.config.json"),
                     "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"manifestPath": "docs/audit/audit-plan.json"}))
        mpath = os.path.join(d, "docs", "audit", "audit-plan.json")
        with io.open(mpath, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_manifest(), indent=2))
        return d, mpath

    def write_shard(name, data):
        path = os.path.join(root, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def run(argv):
        lines = []
        held = sys.stderr
        sys.stderr = io.StringIO()
        try:
            code = M.main(argv, out=lines.append)
        finally:
            sys.stderr = held
        return code, "\n".join(lines)

    try:
        # --- a valid shard, copied whole -----------------------------------
        d1, mp1 = project()
        basename = "2026-01.ci-w1.jsonl"
        rows1 = [{"runId": "run-a1", "v": 1, "status": "passed"},
                 {"runId": "run-a2", "v": 1, "status": "passed"}]
        data1, chained1 = _shard_bytes(basename, rows1)
        src1 = write_shard(basename, data1)

        code, out = run([mp1, src1, "--project-dir", d1])
        check("i1 a valid shard is copied whole, exit 0: %r (%s)" % (code, out),
              code == 0)

        dest1 = os.path.join(_ev.evidence_dir(d1), basename)
        with open(dest1, "rb") as fh:
            landed = fh.read()
        check("i2 ...and the bytes on disk are IDENTICAL to the source, not a "
              "reserialisation of it - a re-encode is how a byte-for-byte copy "
              "quietly turns into something a chain check would still call "
              "valid but a git diff would not call unchanged",
              landed == data1)

        read_back = _ev.read_rows(d1)["rows"]
        check("i3 read_rows() finds both rows through the SAME reader every "
              "other consumer of this directory uses, with their runIds intact: "
              "%r" % ([r.get("runId") for r in read_back],),
              sorted(r.get("runId") for r in read_back) == ["run-a1", "run-a2"])

        # --- a broken chain is refused, and nothing is written --------------
        d2, mp2 = project()
        basename2 = "2026-01.ci-w2.jsonl"
        rows2 = [{"runId": "run-b1", "v": 1, "status": "passed"},
                 {"runId": "run-b2", "v": 1, "status": "passed"}]
        data2, chained2 = _shard_bytes(basename2, rows2)
        tampered = list(chained2)
        tampered[1] = dict(tampered[1])
        tampered[1]["hash"] = "0" * 64             # the row's own hash, altered
        bad_data = ("\n".join(_journal_io.canonical(r) for r in tampered)
                   + "\n").encode("utf-8")
        src2 = write_shard(basename2, bad_data)

        code, out = run([mp2, src2, "--project-dir", d2])
        check("i4 a shard whose second row's own hash was altered is refused, "
              "exit 1: %r (%s)" % (code, out), code == 1)
        check("i5 ...and nothing was written - a refused import leaves the "
              "evidence directory exactly as it found it: %r"
              % (os.path.isdir(_ev.evidence_dir(d2)),),
              not os.path.isdir(_ev.evidence_dir(d2))
              or not os.listdir(_ev.evidence_dir(d2)))

        # --- a same-name collision with different bytes is refused ----------
        d3, mp3 = project()
        basename3 = "2026-01.ci-w3.jsonl"
        rows3a = [{"runId": "run-c1", "v": 1, "status": "passed"}]
        data3a, _ = _shard_bytes(basename3, rows3a)
        src3a = write_shard(basename3 + ".first", data3a)
        # rename to the real basename the importer reads off the path
        real_src3a = os.path.join(root, basename3)
        shutil.copy(src3a, real_src3a)
        code, out = run([mp3, real_src3a, "--project-dir", d3])
        check("i6 setup: the first shard under this name imports cleanly: %r"
              % (code,), code == 0)

        rows3b = [{"runId": "run-d1", "v": 1, "status": "failed"}]
        data3b, _ = _shard_bytes(basename3, rows3b)
        assert data3b != data3a
        src3b_dir = tempfile.mkdtemp(dir=root)
        src3b = os.path.join(src3b_dir, basename3)
        with open(src3b, "wb") as fh:
            fh.write(data3b)

        code, out = run([mp3, src3b, "--project-dir", d3])
        check("i7 a second, DIFFERENT file arriving under the SAME basename is "
              "refused - the chain's genesis is seeded from the name alone, so "
              "two different chains sharing one name is exactly the "
              "substitution the seed exists to catch: %r (%s)" % (code, out),
              code == 1)

        dest3 = os.path.join(_ev.evidence_dir(d3), basename3)
        with open(dest3, "rb") as fh:
            still_there = fh.read()
        check("i8 ...and the file already on disk was not overwritten by the "
              "refused import: %r" % (still_there == data3a,),
              still_there == data3a)

        # --- the allow case: re-importing the identical file exits 0 -------
        code, out = run([mp1, src1, "--project-dir", d1])
        check("i9 importing the exact same bytes a second time is not an error "
              "- it is the same shard arriving twice - and exits 0: %r (%s)"
              % (code, out), code == 0)
        with open(dest1, "rb") as fh:
            landed_again = fh.read()
        check("i10 ...and the file on disk is unchanged by the repeat: %r"
              % (landed_again == data1,), landed_again == data1)

        # --- the report names the runIds and the authentication caveat -----
        d4, mp4 = project()
        basename4 = "2026-01.ci-w4.jsonl"
        rows4 = [{"runId": "run-e1", "v": 1, "status": "passed"}]
        data4, _ = _shard_bytes(basename4, rows4)
        src4 = write_shard(basename4, data4)
        code, out = run([mp4, src4, "--project-dir", d4])
        check("i11 the report names the run it brought and says a ledger is "
              "evidence, not authentication: %r" % (out,),
              code == 0 and "run-e1" in out and "not authentication" in out)

        # --- a run already in the ledger, arriving under another name -------
        d5, mp5 = project()
        held_name = "2026-01.ci-w5.jsonl"
        held_data, _ = _shard_bytes(
            held_name, [{"runId": "run-f1", "v": 1, "status": "passed"},
                        {"runId": "run-f2", "v": 1, "status": "passed"}])
        held_src = write_shard(held_name, held_data)
        code, out = run([mp5, held_src, "--project-dir", d5])
        check("i12 setup: the first shard of this project imports: %r (%s)"
              % (code, out), code == 0)

        dup_name = "2026-01.ci-w6.jsonl"
        dup_data, _ = _shard_bytes(
            dup_name, [{"runId": "run-f2", "v": 1, "status": "passed"},
                       {"runId": "run-g1", "v": 1, "status": "passed"}])
        dup_src = write_shard(dup_name, dup_data)
        code, out = run([mp5, dup_src, "--project-dir", d5])
        check("i13 a shard under a NEW name carrying a runId the ledger already "
              "holds is refused, exit 1 - imported, the same run would be "
              "counted twice: %r (%s)" % (code, out), code == 1)
        refusal_lines = [ln for ln in out.splitlines() if "run-f2" in ln]
        check("i14 ...the refusal names the duplicated id AND the file already "
              "holding it, and does not name the id that was new: %r" % (out,),
              len(refusal_lines) == 1 and held_name in refusal_lines[0]
              and "run-g1" not in out)
        ev5 = _ev.evidence_dir(d5)
        check("i15 ...and nothing was written - the directory holds the first "
              "file alone, no copy and no stray temp file: %r"
              % (sorted(os.listdir(ev5)),),
              sorted(os.listdir(ev5)) == [held_name])
        _json_out = run([mp5, dup_src, "--project-dir", d5, "--json"])[1]
        dups = json.loads(_json_out).get("duplicates")
        check("i16 --json carries each duplicate as a runId and the file that "
              "holds it: %r" % (dups,),
              dups == [{"runId": "run-f2", "file": held_name}])

        # allow direction: the check must not fire on runs the ledger lacks,
        # nor on the byte-identical re-import of a file already held - a
        # version that refused every import into a non-empty ledger fails here
        new_name = "2026-01.ci-w7.jsonl"
        new_data, _ = _shard_bytes(
            new_name, [{"runId": "run-h1", "v": 1, "status": "passed"}])
        new_src = write_shard(new_name, new_data)
        code, out = run([mp5, new_src, "--project-dir", d5])
        check("i17 ALLOW: a shard of run ids the ledger does not hold imports "
              "into a non-empty ledger, exit 0: %r (%s)" % (code, out),
              code == 0 and os.path.isfile(os.path.join(ev5, new_name)))
        code, out = run([mp5, held_src, "--project-dir", d5])
        check("i18 ALLOW: re-importing the identical file still reads 'already "
              "imported', exit 0, even though every one of its runIds is in the "
              "ledger: %r (%s)" % (code, out),
              code == 0 and "already imported" in out)

        # --- a ledger that cannot be read in full: the check cannot be made -
        d6, mp6 = project()
        ev6 = _ev.evidence_dir(d6)
        os.makedirs(ev6)
        broken_name = "2026-01.ci-w8.jsonl"
        with open(os.path.join(ev6, broken_name), "wb") as fh:
            fh.write(b'{"runId": "run-k1", "v": 1')        # a torn last line
        fresh_name = "2026-01.ci-w9.jsonl"
        fresh_data, _ = _shard_bytes(
            fresh_name, [{"runId": "run-m1", "v": 1, "status": "passed"}])
        fresh_src = write_shard(fresh_name, fresh_data)
        code, out = run([mp6, fresh_src, "--project-dir", d6])
        check("i19 an existing ledger file that cannot be read in full refuses "
              "the import, exit 1 - read as empty, the run it lost could be "
              "the very one arriving again: %r (%s)" % (code, out), code == 1)
        check("i20 ...the refusal says the duplicate check could not be made, "
              "names the file by its full path, says a partial last line is an "
              "interrupted write, and gives the step that clears it - a "
              "refusal with no next step leaves every later import blocked: %r"
              % (out,),
              "could not be made" in out
              and os.path.join(ev6, broken_name) in out
              and "a writer was interrupted there" in out
              and "Truncate the partial line on purpose and re-run the import"
              in out)
        # One clause per cause `read_rows` folds into its unreadable list,
        # plus the pointer to the command that tells them apart - each is
        # pinned alone, so dropping any one of them goes red by name.
        clauses = [
            "`audit-journal.py verify` names the cause for each file",
            "could not be opened at all",
            "is cleared by making it readable and re-running the import",
            "Any other line that is not valid JSON is a corrupted row",
            "restore the file from its committed copy, or remove that line on "
            "purpose once you have read it, and re-run the import"]
        check("i20b ...and it gives a way out for EVERY cause it cannot tell "
              "apart - a file that would not open, a torn tail, a corrupted "
              "line before the end - and names the command that tells them "
              "apart; missing: %r" % ([c for c in clauses if c not in out],),
              all(c in out for c in clauses))
        check("i21 ...and nothing was written: %r" % (sorted(os.listdir(ev6)),),
              sorted(os.listdir(ev6)) == [broken_name])

        # --- a shard repeating a runId among its own rows --------------------
        d7, mp7 = project()
        twice_name = "2026-01.ci-w10.jsonl"
        twice_data, _ = _shard_bytes(
            twice_name, [{"runId": "run-n1", "v": 1, "status": "passed"},
                         {"runId": "run-n2", "v": 1, "status": "passed"},
                         {"runId": "run-n1", "v": 1, "status": "failed"}])
        twice_src = write_shard(twice_name, twice_data)
        code, out = run([mp7, twice_src, "--project-dir", d7, "--json"])
        answer7 = json.loads(out)
        check("i22 a shard whose OWN rows repeat a runId is refused, exit 1 - "
              "the same run twice is counted twice whether the second copy "
              "sits in another file or in this one: %r (%s)" % (code, out),
              code == 1)
        check("i23 ...naming the repeated id once, with the shard itself as "
              "the file holding it, and not the id that appears once: %r"
              % (answer7.get("duplicates"),),
              answer7.get("duplicates") == [{"runId": "run-n1",
                                             "file": twice_name}])
        ev7 = _ev.evidence_dir(d7)
        check("i24 ...and nothing was written: %r"
              % (os.path.isdir(ev7) and sorted(os.listdir(ev7)),),
              not os.path.isdir(ev7) or not os.listdir(ev7))

        # --- a ledger file whose bytes are not UTF-8 is unreadable ---------
        # Every ledger reader decodes through one strict function, so a stray
        # byte inside a field loses the whole file rather than yielding a row
        # whose value the byte silently changed. The import cannot know what
        # that file held, so it is refused through the unreadable-ledger path,
        # naming the file - never answered as "no duplicate".
        d8, mp8 = project()
        ev8 = _ev.evidence_dir(d8)
        os.makedirs(ev8)
        odd_name = "2026-01.ci-w11.jsonl"
        odd_data, _ = _shard_bytes(
            odd_name, [{"runId": "run-p1", "v": 1, "status": "passed",
                        "note": "BYTE"}])
        odd_data = odd_data.replace(b"BYTE", b"B\xffTE")
        with open(os.path.join(ev8, odd_name), "wb") as fh:
            fh.write(odd_data)
        again_name = "2026-01.ci-w12.jsonl"
        again_data, _ = _shard_bytes(
            again_name, [{"runId": "run-p1", "v": 1, "status": "passed"}])
        again_src = write_shard(again_name, again_data)
        code, out = run([mp8, again_src, "--project-dir", d8, "--json"])
        answer8 = json.loads(out)
        refused8 = answer8.get("refused") or ""
        check("i25 a ledger file carrying a non-UTF-8 byte is UNREADABLE, so "
              "the import is refused through the unreadable-ledger path - "
              "naming that file by its full path, pointing at the command that "
              "names the cause, and giving THIS cause its own step - a byte "
              "is not a permission, so the could-not-open clause is the wrong "
              "fix - and no duplicate is claimed from bytes nothing could "
              "decode: %r (%r)" % (code, answer8),
              code == 1 and answer8.get("duplicates") == []
              and answer8.get("imported") is False
              and "could not be made" in refused8
              and os.path.join(ev8, odd_name) in refused8
              and "`audit-journal.py verify` names the cause for each file"
              in refused8
              and "A file holding a byte that is not UTF-8 text is lost whole"
              in refused8
              and "counted in bytes from the start of the file, not a line"
              in refused8
              and "cleared by restoring the file from its committed copy, or "
              "by removing that byte on purpose" in refused8)

        # THE SHARD IS DECODED BY THE LEDGER'S ONE DECODER, not a second one
        # written here: the decoder is swapped for one that refuses, and the
        # import must say so - a private decode would import the shard anyway.
        d9, mp9 = project()
        dec_name = "2026-01.ci-w14.jsonl"
        dec_data, _ = _shard_bytes(
            dec_name, [{"runId": "run-d1", "v": 1, "status": "passed"}])
        dec_src = write_shard(dec_name, dec_data)
        real_decode = _ev.ledger_decode

        def refusing_decode(raw):
            raise ValueError("the decoder under test refused these bytes")
        _ev.ledger_decode = refusing_decode
        try:
            code9, out9 = run([mp9, dec_src, "--project-dir", d9, "--json"])
        finally:
            _ev.ledger_decode = real_decode
        answer9 = json.loads(out9)
        check("i25b RED-FIRST: the shard's bytes go through "
              "`_evidence_io.ledger_decode` - swap it for a refusing one and "
              "the import refuses, quoting it: %r (%r)"
              % (code9, answer9.get("refused")),
              code9 == 1 and answer9.get("imported") is False
              and "the decoder under test refused these bytes"
              in (answer9.get("refused") or ""))

        # --- a ledger-held run carried twice by the shard: named once -------
        twice_held_name = "2026-01.ci-w13.jsonl"
        twice_held_data, _ = _shard_bytes(
            twice_held_name,
            [{"runId": "run-f1", "v": 1, "status": "passed"},
             {"runId": "run-q1", "v": 1, "status": "passed"},
             {"runId": "run-f1", "v": 1, "status": "failed"}])
        twice_held_src = write_shard(twice_held_name, twice_held_data)
        code, out = run([mp5, twice_held_src, "--project-dir", d5, "--json"])
        answer9 = json.loads(out)
        check("i26 a runId the ledger holds, carried TWICE by the shard, is "
              "reported once and against the LEDGER file that holds it - not "
              "once per row, and not against the shard: %r (%s)"
              % (code, answer9.get("duplicates")),
              code == 1 and answer9.get("duplicates")
              == [{"runId": "run-f1", "file": held_name}])

        # --- a red full row prints the command that learns from it ----------
        # THE SHARD MIXES every row the rule must tell apart - a red full run,
        # a green full run and a red run of phase scope - so a version that
        # printed for every row, or for every red one, names more than one id.
        d10, mp10 = project()
        red_name = "2026-01.ci-w15.jsonl"
        red_data, _ = _shard_bytes(red_name, [
            {"runId": "run-r1", "v": 1, "scope": "full", "status": "failed"},
            {"runId": "run-r2", "v": 1, "scope": "full", "status": "passed"},
            {"runId": "run-r3", "v": 1, "scope": "phase",
             "status": "failed"}])
        red_src = write_shard(red_name, red_data)
        code, out = run([mp10, red_src, "--project-dir", d10])
        told = [ln for ln in out.splitlines() if "--learn-from" in ln]
        want = ("python3 %s %s --learn-from run-r1 --project-dir %s"
                % (shlex.quote(_loader.script_path("full-gate.py")),
                   shlex.quote(os.path.abspath(mp10)),
                   shlex.quote(os.path.abspath(d10))))
        check("i27 RED-FIRST: a red full row among the imported ones prints "
              "exactly one line, ending in the python3 <full-gate.py> "
              "--learn-from command for that run, over the manifest this "
              "import was given: %r (%s)" % (told, code),
              code == 0 and len(told) == 1 and told[0].endswith(want))
        code, out = run([mp10, red_src, "--project-dir", d10, "--json"])
        check("i28 --json carries the same command, once, beside the rest of "
              "the answer: %r" % (json.loads(out).get("learnFrom"),),
              code == 0 and json.loads(out).get("learnFrom") == [want])
        # THE PRINTED STRING IS RUN AS A SHELL WOULD RUN IT, from a directory
        # that is not the project: a bare script name is 'command not found'
        # there, and a path relative to the import's cwd names nothing.
        printed = (json.loads(out).get("learnFrom") or [""])[0]
        away = tempfile.mkdtemp(dir=root)
        proc = subprocess.run(["/bin/sh", "-c", printed], cwd=away,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True)
        check("i30 RED-FIRST: the printed command runs as printed under "
              "/bin/sh -c from another directory, exit 0, and it is "
              "full-gate.py learning from run-r1: %r (%s)"
              % (proc.returncode, proc.stdout[-300:]),
              proc.returncode == 0
              and "[full-gate] learned nothing from run run-r1" in proc.stdout)

        # A RELATIVE MANIFEST is printed absolute, so the command does not
        # depend on the directory it is pasted into.
        rel = os.path.relpath(mp10)
        code, out = run([rel, red_src, "--project-dir", d10, "--json"])
        words = shlex.split((json.loads(out).get("learnFrom") or [""])[0])
        check("i31 RED-FIRST: an import given a relative manifest (%s) prints "
              "it absolute: %r" % (rel, words[2:3]),
              code == 0 and len(words) > 2 and os.path.isabs(words[2])
              and os.path.samefile(words[2], mp10))

        # ALLOW DIRECTION: a green import prints no --learn-from at all, so
        # the mutation 'print it for every full row' goes red here.
        d11, mp11 = project()
        green_name = "2026-01.ci-w16.jsonl"
        green_data, _ = _shard_bytes(green_name, [
            {"runId": "run-s1", "v": 1, "scope": "full", "status": "passed"}])
        green_src = write_shard(green_name, green_data)
        code, out = run([mp11, green_src, "--project-dir", d11])
        check("i29 a green full row imports with no --learn-from line: %r (%s)"
              % (code, out),
              code == 0 and "run-s1" in out and "--learn-from" not in out)

        # --- the project comes from the manifest, not the current directory -
        # Typed from a directory that is not the project, with no
        # --project-dir: the shard must land in the MANIFEST's project and the
        # printed command must name that project. A version reading the cwd
        # writes under <cwd>/docs/audit/evidence and prints the cwd.
        d12, mp12 = project()
        away12 = tempfile.mkdtemp(dir=root)
        away_name = "2026-01.ci-w17.jsonl"
        away_data, _ = _shard_bytes(away_name, [
            {"runId": "run-t1", "v": 1, "scope": "full", "status": "failed"}])
        away_src = write_shard(away_name, away_data)
        held_cwd = os.getcwd()
        os.chdir(away12)
        try:
            code, out = run([mp12, away_src, "--json"])
        finally:
            os.chdir(held_cwd)
        answer12 = json.loads(out)
        want12 = ("python3 %s %s --learn-from run-t1 --project-dir %s"
                  % (shlex.quote(_loader.script_path("full-gate.py")),
                     shlex.quote(os.path.abspath(mp12)),
                     shlex.quote(os.path.abspath(d12))))
        check("i32 RED-FIRST: an import typed from another directory with no "
              "--project-dir lands under the manifest's project, and nothing "
              "lands under the directory it was typed in: %r (%r, %r)"
              % (code, answer12.get("path"), sorted(os.listdir(away12))),
              code == 0 and os.path.isfile(
                  os.path.join(_ev.evidence_dir(d12), away_name))
              and os.listdir(away12) == [])
        check("i33 RED-FIRST: ...and the printed --learn-from command names "
              "the manifest's project, not that directory: %r"
              % (answer12.get("learnFrom"),),
              answer12.get("learnFrom") == [want12])

        # A --project-dir the manifest does not sit under is refused, exit 2,
        # with a reason, and nothing is written in either project.
        d13, mp13 = project()
        d14, _mp14 = project()
        mis_name = "2026-01.ci-w18.jsonl"
        mis_data, _ = _shard_bytes(mis_name, [
            {"runId": "run-u1", "v": 1, "scope": "full", "status": "failed"}])
        mis_src = write_shard(mis_name, mis_data)
        err = io.StringIO()
        held_err = sys.stderr
        sys.stderr = err
        mis_lines = []
        try:
            code = M.main([mp13, mis_src, "--project-dir", d14],
                          out=mis_lines.append)
        finally:
            sys.stderr = held_err
        check("i34 RED-FIRST: a --project-dir the manifest is not under is "
              "refused, exit 2, saying the manifest is not under it, and "
              "neither project's ledger gains a file: %r (%r)"
              % (code, err.getvalue()),
              code == 2 and "is not under --project-dir" in err.getvalue()
              and not os.path.isdir(_ev.evidence_dir(d13))
              and not os.path.isdir(_ev.evidence_dir(d14)) and not mis_lines)

        # ALLOW DIRECTION: typed from inside the project with no --project-dir,
        # the import is exactly what it was - a version refusing whenever the
        # flag is absent, or deriving some other directory, goes red here.
        d15, mp15 = project()
        in_name = "2026-01.ci-w19.jsonl"
        in_data, _ = _shard_bytes(in_name, [
            {"runId": "run-v1", "v": 1, "scope": "full", "status": "failed"}])
        in_src = write_shard(in_name, in_data)
        os.chdir(d15)
        try:
            code, out = run(["docs/audit/audit-plan.json", in_src, "--json"])
        finally:
            os.chdir(held_cwd)
        answer15 = json.loads(out)
        want15 = ("python3 %s %s --learn-from run-v1 --project-dir %s"
                  % (shlex.quote(_loader.script_path("full-gate.py")),
                     shlex.quote(os.path.join(os.path.realpath(d15), "docs",
                                              "audit", "audit-plan.json")),
                     shlex.quote(os.path.realpath(d15))))
        check("i35 ALLOW: an import typed from inside the project with no "
              "--project-dir lands in that project and prints its command: "
              "%r (%r)" % (code, answer15.get("learnFrom")),
              code == 0 and os.path.isfile(
                  os.path.join(_ev.evidence_dir(d15), in_name))
              and answer15.get("learnFrom") == [want15])

        # --- the project is the plugin's one answer for a named manifest ----
        # `_panel_write.project_of_manifest`: the first ancestor holding
        # `.claude/` or `.git`, else `<T>` for `<T>/docs/audit/<file>`, else
        # the manifest's own directory. A rule counting three directories up
        # is right for the default layout alone.
        def import_away(mpath, name, run_id):
            data, _ = _shard_bytes(name, [
                {"runId": run_id, "v": 1, "scope": "full",
                 "status": "failed"}])
            src = write_shard(name, data)
            away = tempfile.mkdtemp(dir=root)
            os.chdir(away)
            try:
                code, out = run([mpath, src, "--json"])
            finally:
                os.chdir(held_cwd)
            try:
                answer = json.loads(out)
            except ValueError:
                answer = {"unparsed": out}
            return code, answer

        def lands_in(project_dir, name, answer, run_id, mpath):
            want = ("python3 %s %s --learn-from %s --project-dir %s"
                    % (shlex.quote(_loader.script_path("full-gate.py")),
                       shlex.quote(os.path.abspath(mpath)), run_id,
                       shlex.quote(project_dir)))
            return (os.path.isfile(os.path.join(_ev.evidence_dir(project_dir),
                                                name))
                    and answer.get("learnFrom") == [want])

        # A plan outside the default layout, in a project marked by `.git`.
        t16 = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(t16, ".git"))
        os.makedirs(os.path.join(t16, "plan"))
        mp16 = os.path.join(t16, "plan", "audit-plan.json")
        with io.open(mp16, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_manifest(), indent=2))
        code, answer16 = import_away(mp16, "2026-01.ci-w20.jsonl", "run-w1")
        check("i36 RED-FIRST: a plan at <T>/plan/audit-plan.json in a project "
              "marked by <T>/.git imports into <T> - the marker names the "
              "project, not a count of directories - and the command names "
              "<T>: %r (%r)" % (code, answer16),
              code == 0 and lands_in(t16, "2026-01.ci-w20.jsonl", answer16,
                                     "run-w1", mp16))

        # A plan nested with no marker above it: the manifest's own
        # directory, the helper's documented fallback. The precondition is
        # asserted rather than assumed - a marker somewhere above the scratch
        # directory would make this case test a different branch.
        t17 = tempfile.mkdtemp(dir=root)
        nest17 = os.path.join(t17, "a", "b")
        os.makedirs(nest17)
        mp17 = os.path.join(nest17, "audit-plan.json")
        with io.open(mp17, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_manifest(), indent=2))
        marked = []
        cur = os.path.abspath(nest17)
        while True:
            if (os.path.isdir(os.path.join(cur, ".claude"))
                    or os.path.exists(os.path.join(cur, ".git"))):
                marked.append(cur)
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        code, answer17 = import_away(mp17, "2026-01.ci-w21.jsonl", "run-w2")
        check("i37 RED-FIRST: a plan nested at <N>/a/b/audit-plan.json with "
              "no marker above it imports into <N>/a/b, the manifest's own "
              "directory (markers above: %r): %r (%r)"
              % (marked, code, answer17),
              not marked and code == 0
              and lands_in(nest17, "2026-01.ci-w21.jsonl", answer17,
                           "run-w2", mp17))

        # ALLOW DIRECTION: the default layout with no marker at all is still
        # <T> - the case every earlier import in this file already relied on,
        # now without the `.claude/` that let the helper stop early.
        t18 = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(t18, "docs", "audit"))
        mp18 = os.path.join(t18, "docs", "audit", "audit-plan.json")
        with io.open(mp18, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_manifest(), indent=2))
        code, answer18 = import_away(mp18, "2026-01.ci-w22.jsonl", "run-w3")
        check("i38 ALLOW: the default layout <T>/docs/audit/audit-plan.json "
              "with no marker still imports into <T>: %r (%r)"
              % (code, answer18),
              code == 0 and lands_in(t18, "2026-01.ci-w22.jsonl", answer18,
                                     "run-w3", mp18))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_import_evidence.py --selftest\n")
    raise SystemExit(2)
