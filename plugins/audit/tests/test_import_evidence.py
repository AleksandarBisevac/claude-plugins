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

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import shutil
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
