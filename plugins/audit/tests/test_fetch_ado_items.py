#!/usr/bin/env python3
"""
The cases for `fetch-ado-items.py` — the door, not the rule.

`test__ado_fetch.py` proves the chunking, the ceiling and the named outcomes. What
is left for the door is everything a caller can get wrong and everything the exit
code promises:

- **Exit 1 means the payload is PARTIAL.** This one is a gate, unlike
  `explain-ado-drift.py`: "somebody else moved this card" is the normal state of a
  shared board, but "the board did not answer" is a failure, and a payload missing
  the chunk that timed out reads downstream as a clean board for exactly those
  items.
- **A bound is not a hang, and that is asserted with a clock.** The case runs the
  real subprocess path against a process that outlives its bound and requires the
  call to come back — a timeout case that only ever checks the message would pass
  against a `timeout=` that was never wired through, because nothing would ever
  reach it.
- **A sharded manifest plans for its phase-held links.** The command reads through
  `_manifest_io.load_manifest` for the same reason `explain-ado-drift.py` does; a
  raw read would plan a fetch for the index's bugs alone and call it complete.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _ado_fetch as F                             # noqa: E402  (the seam patched below)
import _manifest_io as MIO                         # noqa: E402  (the sharded WRITER)

M = _loader.load_script("fetch-ado-items.py", modname="fetch_ado_items")

ADO = {"organization": "acme", "project": "store"}

# Links in all three places, and one task with none, so a plan that lost a whole
# kind is visible as a missing id rather than only as a smaller total.
SOURCE = {
    "meta": {"version": 2, "ado": ADO},
    "phases": [{"id": "P1", "title": "one",
                "ado": {"id": 4001},
                "tasks": [{"id": "T1.1", "ado": {"id": 5120}},
                          {"id": "T1.2"}]},
               {"id": "P2", "title": "two",
                "ado": {"id": 4002},
                "tasks": [{"id": "T2.1", "ado": {"id": 5121}}]}],
    "bugs": [{"id": "BUG-7", "ado": {"id": 4890}}],
}


class _Done(object):
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _row(i):
    return ('{"id": %d, "fields": {"System.Id": %d, "System.State": "Active",'
            ' "System.ChangedDate": "2026-08-22T10:51:38.37Z"}}' % (i, i))


def _answering(_argv, _timeout):
    """A board that answers with a row for every id the query names."""
    wiql = _argv[_argv.index("--wiql") + 1]
    ids = [int(x) for x in
           wiql.split("IN (")[1].rstrip(")").split(",") if x.strip()]
    return _Done(0, "[%s]" % (",".join(_row(i) for i in ids),))


def _timing_out(argv, timeout):
    raise subprocess.TimeoutExpired(argv, timeout)


def _run(argv):
    """(exit code, stdout, stderr) — the printed answer is half the contract."""
    out, err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = M.main(argv)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    return code, out.getvalue(), err.getvalue()


def _write(tmp, name, payload):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _cases(check):
    tmp = tempfile.mkdtemp(prefix="fai-")
    real_runner = F._run_subprocess
    try:
        single = _write(tmp, "audit-plan.json", SOURCE)

        # --- usage and unreadable input ---------------------------------------
        for label, argv in (("no arguments at all", []),
                            ("a flag where the manifest goes", ["--json"])):
            code, out, _err = _run(argv)
            check("fa1 usage error is exit 2 and prints nothing (%s): %r"
                  % (label, code), code == 2 and out == "")

        code, _out, err = _run([os.path.join(tmp, "nope.json")])
        check("fa2 a manifest that cannot be read is exit 2 and says so",
              code == 2 and err.startswith("ERROR: cannot read/parse manifest"))

        noado = _write(tmp, "noado.json", {"meta": {"version": 2},
                                           "phases": [], "bugs": []})
        code, out, err = _run([noado])
        check("fa3 a manifest with no meta.ado is exit 2 pointing at `connect` - "
              "not an empty fetch, which would read as a board with nothing on "
              "it: %r" % (err.strip()[:60],),
              code == 2 and out == "" and "meta.ado" in err
              and "connect" in err)

        for raw in ("later", "0", "-3"):
            code, out, err = _run([single, "--chunk", raw])
            check("fa4 --chunk %r is refused rather than silently defaulted - a "
                  "limit nobody chose is a limit nobody can check" % (raw,),
                  code == 2 and out == "" and err.startswith("ERROR: --chunk"))
        code, out, err = _run([single, "--timeout", "0"])
        check("fa5 ...and the same for --timeout: a bound of zero is a bound "
              "nobody meant", code == 2 and err.startswith("ERROR: --timeout"))

        # --- the plan, without spending a call --------------------------------
        F._run_subprocess = _timing_out          # would FAIL if anything called it
        code, out, _err = _run([single, "--dry-run"])
        check("fa6 --dry-run prints the plan and exits 0 having called NOTHING - "
              "the runner installed here raises on any call, so a query that was "
              "actually sent would surface as a failure line: %r"
              % (out.splitlines()[:1],),
              code == 0 and "ADO TIMED OUT" not in out
              and "5 of 6 manifest item(s) carry an ado link" in out)
        check("fa7 ...and it says how many QUERIES, not just how many ids - the "
              "number of calls is the thing that was wrong, so it is the thing "
              "the plan has to state",
              "5 id(s) in 1 query (chunk limit 200, bound 60s per query)" in out)

        code, out, _err = _run([single, "--dry-run", "--chunk", "5"])
        check("fa8 THE CHUNK BOUNDARY AT THE SIZE: five ids at a chunk of five "
              "is ONE query, not two. A chunker tested only below its limit "
              "passes with the limit ignored, so this sits exactly on it",
              code == 0 and "5 id(s) in 1 query" in out)
        code, out, _err = _run([single, "--dry-run", "--chunk", "4"])
        check("fa9 ...and one past it is TWO queries. The pair is what proves "
              "the size is read: fa8 alone passes for a chunker that never "
              "splits, fa9 alone for one that always does",
              code == 0 and "5 id(s) in 2 queries" in out)

        # --- the sharded layout ------------------------------------------------
        sdir = os.path.join(tmp, "sharded")
        os.makedirs(sdir)
        sharded = os.path.join(sdir, "audit-plan.json")
        MIO.save_sharded(sharded, SOURCE)
        code, out, _err = _run([sharded, "--dry-run"])
        check("fa10 a SHARDED manifest plans for its phase-held links too: the "
              "phase's own `ado` and every task's live in a shard file the index "
              "only points at, so a raw read would plan for the index's one bug "
              "and call it complete",
              code == 0 and "5 of 6 manifest item(s) carry an ado link" in out)

        code, out, _err = _run([sharded, "--dry-run", "--json"])
        sharded_ids = json.loads(out)["plan"]["ids"]
        code, out, _err = _run([single, "--dry-run", "--json"])
        check("fa11 ...and the two layouts plan the SAME fetch, id for id and in "
              "the same order. Storage is a choice about files; it does not get "
              "to change which board items get read: %r" % (sharded_ids,),
              sharded_ids == json.loads(out)["plan"]["ids"]
              # link_inventory's documented order: every phase, then every task,
              # then every bug. Pinned rather than sorted, because the order the
              # plan is made in is the order the table comes back in.
              and sharded_ids == [4001, 4002, 5120, 5121, 4890])

        # --- a board that answers ----------------------------------------------
        F._run_subprocess = _answering
        payload = os.path.join(tmp, "fetched.json")
        code, out, _err = _run([single, "--out", payload])
        check("fa12 every chunk answering is exit 0, and the count says how many "
              "OF how many were asked for: %r"
              % ([ln for ln in out.splitlines() if ln.startswith("fetched")],),
              code == 0 and "fetched 5 of 5 linked item(s)" in out)
        check("fa13 THE PAIR for fa16: a run where nothing failed prints NO "
              "partial-payload warning and no timeout line. This is the case "
              "that goes red if the warning became unconditional",
              "THE PAYLOAD IS PARTIAL" not in out and "ADO TIMED OUT" not in out
              and "NO ROW:" not in out)

        with open(payload, "r", encoding="utf-8") as fh:
            written = json.load(fh)
        check("fa14 --out writes exactly the `{id, fields}` payload "
              "explain-ado-drift.py --items reads - one entry per id, each "
              "carrying the fields the board returned: %d entr(y/ies)"
              % (len(written),),
              len(written) == 5
              and sorted(e["id"] for e in written)
              == [4001, 4002, 4890, 5120, 5121]
              and all("System.State" in e["fields"] for e in written))
        check("fa15 ...and it does NOT invent `mapped`: that is the stateMap "
              "translation sync.md owns, and a second copy here would be a "
              "second answer", not any("mapped" in e for e in written))

        # --- a board that does not answer --------------------------------------
        F._run_subprocess = _timing_out
        code, out, _err = _run([single, "--timeout", "3"])
        check("fa16 A CHUNK THAT DID NOT ANSWER IS EXIT 1 with a NAMED outcome, "
              "not exit 0 with a short table: the status is named, the bound is "
              "stated, and every id it has no news about is listed: %r"
              % ([ln for ln in out.splitlines() if ln.startswith("ADO ")],),
              code == 1 and "ADO TIMED OUT" in out and "within 3s" in out
              and "no news about: #4001" in out
              and "THE PAYLOAD IS PARTIAL" in out)
        check("fa17 ...and it does NOT claim to have fetched anything - `fetched "
              "0 of 5` is the honest line, and it is printed rather than left "
              "out, because a count that appears only on success cannot be told "
              "from a count nobody computed",
              "fetched 0 of 5 linked item(s)" in out)

        # A board that answers for one chunk and stalls on the next. The partial
        # case is the one that matters: a table built from half a board reads as a
        # whole board unless the missing half is named.
        calls = []

        def _half(argv, timeout):
            calls.append(argv)
            if len(calls) == 1:
                return _answering(argv, timeout)
            raise subprocess.TimeoutExpired(argv, timeout)

        F._run_subprocess = _half
        code, out, _err = _run([single, "--chunk", "3", "--timeout", "3"])
        check("fa18 one chunk answering and the next stalling is STILL exit 1, "
              "and the answer says both halves - what it has and what it has no "
              "news about. A partial payload that printed like a whole one is "
              "the defect this exit code exists for: %r"
              % ([ln for ln in out.splitlines() if ln.startswith(("fetched",
                                                                 "  no news"))],),
              code == 1 and "fetched 3 of 5 linked item(s)" in out
              and "no news about: #5121, #4890" in out)

        # --- rows that never came back -----------------------------------------
        F._run_subprocess = lambda a, t: _Done(0, "[%s]" % (_row(4001),))
        code, out, _err = _run([single, "--chunk", "200"])
        check("fa19 an id asked for that no row came back for is NAMED and the "
              "run still exits 0 - a work item deleted or moved out of the "
              "project is information, not a failure, and dropping it would "
              "leave a shorter table looking complete",
              code == 0 and out.count("NO ROW: #") == 4
              and "NO ROW: #5120" in out)

        # --- the bound is real, measured on the REAL subprocess path -----------
        F._run_subprocess = real_runner
        started = time.time()
        try:
            real_runner([sys.executable, "-c", "import time; time.sleep(30)"], 2)
            raised = None
        except subprocess.TimeoutExpired:
            raised = "timeout"
        except Exception as exc:
            raised = type(exc).__name__
        elapsed = time.time() - started
        check("fa20 THE BOUND IS NOT A HANG, and a clock is what says so: the "
              "real runner against a process outliving its bound came back in "
              "%.1fs raising %r. A timeout case that only checks the MESSAGE "
              "passes against a `timeout=` that was never wired through, because "
              "nothing would ever reach the message" % (elapsed, raised),
              raised == "timeout" and elapsed < 15)

        done = real_runner([sys.executable, "-c",
                            "import sys; sys.stdout.write(repr(sys.stdin.read()))"],
                           30)
        check("fa21 ...and stdin is CLOSED on every call, so a prompt for a "
              "credential becomes an immediate end-of-input rather than a wait "
              "nobody can see: the child read %r" % (done.stdout,),
              done.returncode == 0 and done.stdout == "''")
    finally:
        F._run_subprocess = real_runner
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_fetch_ado_items.py --selftest\n")
    raise SystemExit(2)
