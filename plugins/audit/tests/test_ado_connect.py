#!/usr/bin/env python3
"""
The cases for `ado-connect.py` — the door `/audit:sync connect` knocks on.

The DECISIONS live in `_ado_connect` and have their own suite. What is pinned
HERE is the ladder: that each rung stops the run rather than reporting and
carrying on, that the rungs stop IN ORDER, and — the case this whole feature
exists for — that a failed probe leaves the plan and the evidence block
UNBUILT rather than merely unwritten.

WHY THAT LAST ONE IS ABOUT ABSENCE AND NOT ABOUT A MESSAGE. "It stops before
any write" is easy to satisfy with a printed sentence and easy to break with a
refactor that computes the plan first and prints it later. So the assertion is
that `data["plan"]` and `data["connection"]` are None on every stopping rung —
a shape a later edit cannot pass by accident.

`observe()` IS NOT EXERCISED HERE, AND THAT IS THE SPLIT WORKING. It is the
only function that touches this machine (a PATH lookup, an extension list, a
sign-in read, a file of organization URLs), and every rung below takes those
observations as arguments — which is the only reason the stopping rungs are
reachable at all from a test with no `az`, no network and no credential.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("ado-connect.py", modname="ado_connect")

# az on PATH, the extension installed, one auth path, nothing ambiguous.
READY = {"hasMcp": False, "hasAz": True, "extensions": ["azure-devops"],
         "signedInAs": "dev@example.com", "patEnvSet": False,
         "storedOrgs": []}
NOW = "2026-08-24T09:00:00Z"


def _row(wit, state):
    return {"id": 1, "fields": {"System.WorkItemType": wit,
                                "System.State": state}}


SCRUM_ROWS = [_row("Product Backlog Item", "New"), _row("Task", "To Do"),
              _row("Task", "Done")]
AGILE_ROWS = [_row("User Story", "New"), _row("Task", "Closed")]
OK_SCRUM = {"exitCode": 0, "stderr": "", "rows": SCRUM_ROWS}
OK_AGILE = {"exitCode": 0, "stderr": "", "rows": AGILE_ROWS}
DENIED = {"exitCode": 1, "rows": [],
          "stderr": "ERROR: Before you can run Azure DevOps commands, you need "
                    "to run the login command(az login ...) to setup "
                    "credentials."}


def _run(manifest, facts, envelope, org="test-audit-lab",
         project="audit-gate-scrum"):
    return M.report(manifest, facts, envelope, org, project, NOW)


def _write(tmp, name, obj):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def _main(argv):
    """(exit code, stdout) — the printed answer is half this command's contract."""
    buf, real = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = M.main(argv)
    finally:
        sys.stdout = real
    return code, buf.getvalue()


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the ladder stops, rung by rung, and each stop is its own ---
    no_transport = _run({}, dict(READY, hasAz=False, extensions=None), OK_SCRUM)
    check("r1 rung 1 stops the whole run when there is no transport, and does "
          "NOT go on to report an identity it could not have observed",
          no_transport["code"] == 1
          and sum(1 for line in no_transport["lines"]
                  if line.startswith("STOP (transport)")) == 1
          and sum(1 for line in no_transport["lines"]
                  if line.startswith("identity")) == 0)
    no_auth = _run({}, dict(READY, signedInAs=None), OK_SCRUM)
    check("r2 rung 2 stops when no auth path exists at all - AFTER rung 1 "
          "reported its transport, so the two rungs are visibly ordered "
          "rather than one combined verdict",
          no_auth["code"] == 1
          and sum(1 for line in no_auth["lines"]
                  if line.startswith("transport:")) == 1
          and sum(1 for line in no_auth["lines"]
                  if line.startswith("STOP (identity)")) == 1)
    no_target = _run({}, READY, None, org=None, project=None)
    check("r3 no organization/project is its own stop, named separately from "
          "the two above - it is a manifest problem, not a machine one",
          no_target["code"] == 1
          and sum(1 for line in no_target["lines"]
                  if line.startswith("STOP (target)")) == 1)
    denied = _run({}, READY, DENIED)
    check("r4 rung 3 stops on a probe the board refused",
          denied["code"] == 1
          and sum(1 for line in denied["lines"]
                  if line.startswith("STOP (probe)")) == 1)
    stops = []
    for res in (no_transport, no_auth, no_target, denied):
        stops += [line for line in res["lines"] if line.startswith("STOP")]
    check("r5 four rungs stop and each prints a DIFFERENT sentence - counted, "
          "because two rungs sharing one message send a reader to the wrong "
          "remedy while every presence check stays green: %d/%d distinct"
          % (len(set(stops)), len(stops)),
          len(stops) == 4 and len(set(stops)) == 4)

    # --- THE case: a failed probe leaves nothing built, not merely unwritten ---
    check("r6 a refused probe builds NO plan and NO evidence block - asserted "
          "as absence rather than as a printed promise, because a message is "
          "easy to keep true while a refactor computes the plan anyway",
          denied["data"]["plan"] is None
          and denied["data"]["connection"] is None
          and denied["data"]["process"] is None)
    check("r7 ...and it says so where a person reads it, exactly once",
          sum(1 for line in denied["lines"]
              if "NOTHING WAS WRITTEN" in line) == 1)
    ok = _run({}, READY, OK_SCRUM)
    check("r8 the paired positive: a probe that ANSWERED does build both, so "
          "r6 cannot be passing on a rule that never builds a plan",
          ok["code"] == 0 and ok["data"]["plan"] is not None
          and ok["data"]["connection"] is not None
          and ok["data"]["process"]["process"] == "Scrum")
    for res, name in ((no_transport, "transport"), (no_auth, "identity"),
                      (no_target, "target")):
        check("r9-%s the earlier rungs leave the plan unbuilt too - every "
              "stop is before the write, not just the probe's" % (name,),
              res["data"]["plan"] is None
              and res["data"]["connection"] is None)

    # --- rung 2's report, both directions ---
    env_facts = dict(READY, patEnvSet=True, signedInAs=None)
    with_env = _run({}, env_facts, None)
    without_env = _run({}, READY, None)
    check("r10 with the PAT variable set, the report names the VARIABLE in an "
          "in-play line exactly once and the sign-in nowhere",
          sum(1 for line in with_env["lines"]
              if "IN PLAY" in line and "AZURE_DEVOPS_EXT_PAT" in line) == 1
          and sum(1 for line in with_env["lines"]
                  if "IN PLAY" in line and "az account show" in line) == 0)
    check("r11 ...and with it unset the sign-in is the in-play line while the "
          "variable moves to `absent` - the paired negative, so neither line "
          "can be coming from a report that prints both regardless",
          sum(1 for line in without_env["lines"]
              if "IN PLAY" in line and "az account show" in line) == 1
          and sum(1 for line in without_env["lines"]
                  if "IN PLAY" in line and "AZURE_DEVOPS_EXT_PAT" in line) == 0
          and sum(1 for line in without_env["lines"]
                  if line.strip().startswith("absent:")
                  and "AZURE_DEVOPS_EXT_PAT" in line) == 1)
    check("r12 the required PAT scope is stated once, and it is the Work "
          "Items one - the only scope this connector needs",
          sum(1 for line in without_env["lines"]
              if "Work Items -> Read & write" in line) == 1)

    # --- MCP is a transport with no identity this command can see ---
    mcp = _run({}, {"hasMcp": True, "hasAz": False, "extensions": None,
                    "signedInAs": None, "patEnvSet": False, "storedOrgs": []},
               OK_AGILE)
    check("r13 an MCP session runs the ladder with no az at all, and says out "
          "loud that the identity is the server's - said rather than skipped, "
          "since a rung printing nothing cannot be told from one that found "
          "nothing",
          mcp["code"] == 0
          and sum(1 for line in mcp["lines"]
                  if "cannot see which account" in line) == 1
          and mcp["data"]["process"]["process"] == "Agile")

    # --- rung 3 not yet made: the ladder stops usefully, not with a failure ---
    pending = _run({}, READY, None)
    check("r14 with no probe yet the run EXITS 0 and hands over the exact "
          "query to make - the local rungs are what say whether the round "
          "trip is worth making, so 'not yet probed' is not a failure",
          pending["code"] == 0
          and sum(1 for line in pending["lines"]
                  if "az boards query" in line) == 1
          and pending["data"]["probe"] is None
          and pending["data"]["plan"] is None)
    check("r15 the handed-over query names the project it was asked about, "
          "rather than a placeholder somebody has to substitute",
          sum(1 for line in pending["lines"]
              if "audit-gate-scrum" in line) >= 1
          and sum(1 for line in pending["lines"] if "<project>" in line) == 0)

    # --- rung 4 and 5 in the report, Scrum vs Agile ---
    agile = _run({}, READY, OK_AGILE)
    check("r16 the Scrum report proposes Product Backlog Item and prints the "
          "stateMap requirement; the Agile one proposes User Story and does "
          "not - both directions off one report path",
          sum(1 for line in ok["lines"]
              if "types.pbi" in line and "Product Backlog Item" in line) == 1
          and sum(1 for line in ok["lines"] if "REQUIRED" in line) == 1
          and sum(1 for line in agile["lines"]
                  if "types.pbi" in line and "User Story" in line) == 1
          and sum(1 for line in agile["lines"] if "REQUIRED" in line) == 0)

    # --- idempotence, through the door ---
    configured = {"meta": {"ado": {"organization": "test-audit-lab",
                                   "project": "audit-gate-scrum",
                                   "enabled": True,
                                   "types": {"bug": "Bug", "task": "Task",
                                             "pbi": "Product Backlog Item"}}}}
    again = _run(configured, READY, OK_SCRUM)
    check("r17 run against the manifest it already wrote, the plan is four "
          "keeps and zero writes - and it says the connector is already "
          "configured rather than reporting a fresh setup",
          again["code"] == 0 and again["data"]["plan"]["writes"] == 0
          and sum(1 for line in again["lines"]
                  if "already configures meta.ado" in line) == 1
          and sum(1 for line in again["lines"]
                  if line.strip().startswith("keep ")) == 4)
    check("r18 ...and the same probe against an EMPTY meta.ado plans four "
          "sets and zero keeps, which is the negative r17 needs",
          ok["data"]["plan"]["writes"] == 4
          and sum(1 for line in ok["lines"]
                  if line.strip().startswith("set    meta.ado.")) == 4
          and sum(1 for line in ok["lines"]
                  if line.strip().startswith("keep ")) == 0)
    # Found by running the real command against the live Scrum board: the head
    # line read `0 to set` and a `set meta.ado.connection` row followed it. The
    # evidence block is re-stamped on EVERY run by definition, so it belongs
    # outside the counts and has to say so - a plan whose rows contradict its
    # own head line is exactly the arithmetic nobody re-checks.
    check("r18b the evidence block is a RESTAMP outside the counts, and the "
          "line says so - on the already-configured run the head line reads "
          "zero to set and no row under it claims a set",
          sum(1 for line in again["lines"]
              if line.strip().startswith("restamp (not counted above)")) == 1
          and sum(1 for line in again["lines"]
                  if line.strip().startswith("set    meta.ado.")) == 0
          and sum(1 for line in again["lines"]
                  if "0 to set" in line) == 1)
    check("r18c ...and it is restamped on the FRESH run too, so the block is "
          "never left holding an older run's moment: the paired positive, "
          "since a line that only appeared when configured would be a "
          "different bug wearing the same shape",
          sum(1 for line in ok["lines"]
              if line.strip().startswith("restamp (not counted above)")) == 1
          and ok["data"]["connection"]["fetchedAt"] == NOW)
    drift = {"meta": {"ado": {"organization": "test-audit-lab",
                              "project": "audit-gate-scrum",
                              "enabled": False,
                              "types": {"bug": "Bug", "task": "Task",
                                        "pbi": "User Story"}}}}
    offered = _run(drift, READY, OK_SCRUM)
    check("r19 a manifest configured differently gets CHANGE rows saying "
          "'offered, never applied' - a connect that clobbered somebody's "
          "deliberate value would be worse than one that refused to run",
          sum(1 for line in offered["lines"]
              if line.strip().startswith("CHANGE meta.ado.")) == 2
          and sum(1 for line in offered["lines"]
                  if "never applied without your answer" in line) == 2)
    check("r20 and no rung of this command writes: every path above returned "
          "lines and data only, and the closing line says the manifest is "
          "still the caller's to edit",
          sum(1 for line in offered["lines"]
              if "This command wrote nothing" in line) == 1
          and sum(1 for line in again["lines"]
                  if "This command wrote nothing" in line) == 1)

    # --- the door itself: exit codes and unreadable input ---
    #
    # `observe()` IS PINNED TO A FIXTURE FOR EVERY `main()` CASE BELOW, and the
    # reason is not convenience: it is the one function that reads this
    # machine, so a `main()` case left to run it would pass on a laptop with
    # `az` installed and fail in CI without it - a suite that is green in the
    # one place it is least needed. `c8` asserts the seam itself, so pinning it
    # cannot become a way of testing a path production does not take.
    check("c0 no arguments is a usage error, not an accidental pass",
          M.main([]) == 2)
    tmp = tempfile.mkdtemp(prefix="qg-adoconnect-")
    _real_observe = M.observe
    _seen_hints = []

    def _fake_observe(hint):
        _seen_hints.append(hint)
        return dict(READY)

    try:
        M.observe = _fake_observe
        m_ok = _write(tmp, "m.json", configured)
        probe_ok = _write(tmp, "p.json", OK_SCRUM)
        check("c1 an unreadable MANIFEST is 2, never a fall-through to a run "
              "that reports a connector it never read",
              M.main(["/no/such/manifest.json"]) == 2)
        broken = os.path.join(tmp, "broken.json")
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("c1b ...and unparseable counts as unreadable, since a manifest "
              "that cannot be read carries no meta.ado to plan against",
              M.main([broken]) == 2)
        check("c2 --probe naming a file that does not exist is 2 and NOT 1: a "
              "1 says a rung refused this board, and saying that about an "
              "envelope we could not read is the confident wrong answer",
              M.main([m_ok, "--probe", os.path.join(tmp, "nope.json")]) == 2)
        check("c3 an unknown --transport is a usage error rather than a "
              "silent fall back to `auto`, which would run the az rungs on a "
              "session that meant to say MCP",
              M.main([m_ok, "--transport", "banana"]) == 2)
        code, out = _main([m_ok, "--probe", probe_ok, "--json"])
        parsed = json.loads(out)
        check("c4 --json carries the machine-readable answer and the same "
              "exit code, so a caller can gate on `plan.writes` rather than "
              "grepping prose: %r" % (sorted(parsed),),
              code == 0 and parsed["plan"]["writes"] == 0
              and parsed["process"]["process"] == "Scrum"
              and parsed["connection"]["authPath"] is not None)
        code, out = _main([m_ok, "--probe", probe_ok])
        check("c5 ...and without --json the same run prints the ladder and "
              "not JSON - the two renderings are of one answer",
              code == 0 and "transport:" in out
              and out.lstrip()[:1] != "{")
        m_bare = _write(tmp, "bare.json", {})
        check("c6 a manifest with no meta.ado at all and no --org is the "
              "target stop, not a crash - the common first-run shape",
              M.main([m_bare]) == 1)
        code, out = _main([m_bare, "--org", "acme", "--project", "web"])
        check("c7 ...and --org/--project supply what the manifest lacks, "
              "which is how the very first connect is run: the query handed "
              "over names them",
              sum(1 for line in out.splitlines()
                  if "acme" in line and "web" in line) >= 1)
        _seen_hints[:] = []
        M.main([m_ok, "--transport", "mcp"])
        M.main([m_ok])
        check("c8 `main()` really does route through `observe()`, and hands "
              "it the transport hint verbatim - without this, pinning the "
              "stub above would quietly be testing a path production never "
              "takes: %r" % (_seen_hints,),
              _seen_hints == ["mcp", "auto"])
    finally:
        M.observe = _real_observe
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_ado_connect.py --selftest\n")
    raise SystemExit(2)
