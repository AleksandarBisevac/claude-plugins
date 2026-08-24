#!/usr/bin/env python3
"""
The cases for `_ado_connect` — every decision `/audit:sync connect` makes.

THE FIXTURES ARE MEASURED, NOT IMAGINED. `AGILE_ROWS` and `SCRUM_ROWS` are the
shapes two live boards returned to the one query rung 4 makes
(`test-audit-lab/audit-gate-agile` and `.../audit-gate-scrum`), reduced to the
two fields the rule reads. That matters for one case in particular: the Agile
board had NO item sitting in `Active` or `Resolved`, so its observed Task
states were `New` and `Closed` alone — which is exactly why the discriminator
here is the phase-level TYPE and not the states, and why a fixture invented
from the process documentation would have hidden the problem rather than
pinned it.

AND THE TWO BOARDS ARE A MATCHED PAIR. Agile's observed Task states contain
`Closed` and Scrum's do not, so `state_map_advice` runs both of its evidence
branches off real data — a positive and a negative that no always-true rule
can satisfy at once.

WHAT IS PINNED BY COUNT RATHER THAN BY PRESENCE. Every rung has its own stop,
and "each rung stops with its own message" is a claim about DISTINCTNESS: two
rungs sharing one sentence would leave a user reading the wrong remedy while
every presence assertion stayed green. So the stops are collected and counted.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ado_connect as M                           # noqa: E402


def _row(wit, state):
    return {"id": 1, "fields": {"System.WorkItemType": wit,
                                "System.State": state}}


# Measured 2026-08-24 against test-audit-lab/audit-gate-agile: 8 items.
AGILE_ROWS = [_row("Epic", "New"),
              _row("User Story", "New"), _row("User Story", "Closed"),
              _row("Task", "New"), _row("Task", "Closed")]
# Measured the same day against test-audit-lab/audit-gate-scrum: 30 items.
SCRUM_ROWS = [_row("Bug", "New"), _row("Epic", "New"),
              _row("Product Backlog Item", "New"),
              _row("Product Backlog Item", "Committed"),
              _row("Product Backlog Item", "Done"),
              _row("Task", "To Do"), _row("Task", "In Progress"),
              _row("Task", "Done"), _row("Task", "Removed")]


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- rung 1: transport ---
    mcp = M.transport_verdict(False, None, True)
    check("t1 MCP tools carry the session even with no az at all - the az "
          "rungs are not preconditions for a transport that is not az",
          mcp["transport"] == M.TRANSPORT_MCP and mcp["stop"] is None)
    no_az = M.transport_verdict(False, None, False)
    check("t2 no az and no MCP stops, and names installing azure-cli",
          no_az["transport"] is None and no_az["stop"] is not None
          and "azure-cli" in no_az["remedy"])
    unknown = M.transport_verdict(True, None, False)
    check("t3 an extension list that did NOT answer stops on its own rung: "
          "unknown is not installed, and reading it as installed would send "
          "the run to a board call whose failure names the wrong cause",
          unknown["transport"] is None and unknown["stop"] is not None)
    missing = M.transport_verdict(True, ["front-door", "log-analytics"], False)
    check("t4 az present, extension absent -> the add command, and NOT the "
          "install-azure-cli remedy t2 gives",
          missing["transport"] is None
          and missing["remedy"] == "az extension add --name azure-devops"
          and missing["remedy"] != no_az["remedy"])
    ok = M.transport_verdict(True, ["azure-devops", "front-door"], False)
    check("t5 ...and the same list WITH the extension is the az transport "
          "with no stop - the negative half, so t4 cannot pass on a rule that "
          "always refuses",
          ok["transport"] == M.TRANSPORT_AZ and ok["stop"] is None)
    stops = [v["stop"] for v in (no_az, unknown, missing) if v["stop"]]
    check("t6 three rungs stop and each says something DIFFERENT - counted, "
          "because two rungs sharing one sentence leaves a reader following "
          "the wrong remedy while every presence check stays green: %d/%d"
          % (len(set(stops)), len(stops)),
          len(stops) == 3 and len(set(stops)) == 3)

    # --- rung 2: which auth path ---
    check("a0 an organization reaches the stored list as a bare key whether "
          "it arrived as a name or as a URL, and case is dropped as the CLI "
          "drops it",
          M.org_key("https://dev.azure.com/Test-Audit-Lab")
          == M.org_key("test-audit-lab") == "test-audit-lab")
    check("a0b ...and nothing usable is None rather than an empty key that "
          "would then MATCH an empty entry in the stored list",
          M.org_key("") is None and M.org_key(None) is None
          and M.org_key(7) is None)
    # The real file's shape: `azdevops-cli:https://dev.azure.com/<org>`.
    stored = M.stored_pat_orgs("azdevops-cli:https://dev.azure.com/uptimize\n")
    check("a0c the stored-org list is parsed from the CLI's own line shape "
          "(%r) - it names ORGANIZATIONS and holds no token" % (stored,),
          stored == ["uptimize"])
    check("a0d ...and no file at all is an empty list, not a crash and not a "
          "wildcard that would report every organization as stored",
          M.stored_pat_orgs(None) == [] and M.stored_pat_orgs(12) == [])

    env_on = M.auth_path_report("acme", True, None, [])
    check("a1 the PAT environment variable being SET is reported by NAME, and "
          "the report says out loud that only its existence was read - a "
          "connector that touched the value would be the thing this plugin's "
          "own secret guard blocks",
          env_on["inEffect"] == M.PATH_ENV_PAT
          and sum(1 for p in env_on["paths"]
                  if M.PAT_ENV_VAR in p["line"]) == 1
          and "never its value" in env_on["paths"][0]["line"])
    signin = M.auth_path_report("acme", False, "dev@example.com", [])
    check("a2 ...and with it unset, the Azure sign-in is the path, the "
          "variable is named in the ABSENT list instead, and it appears in "
          "NEITHER an in-play line - the paired negative a1 needs",
          signin["inEffect"] == M.PATH_AZURE_SIGNIN
          and sum(1 for p in signin["paths"]
                  if M.PAT_ENV_VAR in p["line"]) == 0
          and sum(1 for line in signin["absent"]
                  if M.PAT_ENV_VAR in line) == 1)
    per_org = M.auth_path_report("uptimize", False, None, ["uptimize"])
    other_org = M.auth_path_report("test-audit-lab", False, None, ["uptimize"])
    check("a3 a stored PAT is PER-ORGANIZATION: the same stored list makes one "
          "organization's path 'stored' and another's nothing at all. This is "
          "the fact measured on the machine this was written on, where two "
          "organizations resolved by different paths at the same moment",
          per_org["inEffect"] == M.PATH_STORED_PAT
          and other_org["inEffect"] is None
          and other_org["stop"] is not None)
    check("a4 no path anywhere is a STOP with a remedy naming both ways in, "
          "rather than a run that goes on to fail at the board",
          other_org["stop"] is not None
          and "az login" in other_org["remedy"]
          and M.REQUIRED_SCOPE in other_org["remedy"])
    both = M.auth_path_report("uptimize", True, "dev@example.com", ["uptimize"])
    check("a5 THREE paths present at once is reported as ambiguous and picks "
          "NONE - nothing observable from outside says which one az answered "
          "with, and a precedence rule this command cannot verify would be a "
          "confident wrong answer: %d paths" % (len(both["paths"]),),
          both["ambiguous"] is True and both["inEffect"] is None
          and len(both["paths"]) == 3)
    check("a6 ...and the sentence that holds either way is the one the rung "
          "exists for: a working board command proves the ORGANIZATION is "
          "reachable, never which identity reached it",
          "reachable" in both["note"] and "identity" in both["note"]
          and both["note"] != signin["note"])
    check("a7 the absences are printed even when a path WAS found, so a rung "
          "that ran can be told from a rung that did not: %d absent line(s) "
          "beside %d path(s)" % (len(signin["absent"]), len(signin["paths"])),
          len(signin["absent"]) == 2 and len(signin["paths"]) == 1
          and len(both["absent"]) == 0)

    # --- rung 3: the probe ---
    good = M.probe_verdict({"exitCode": 0, "stderr": "", "rows": AGILE_ROWS})
    check("p1 exit 0 is access proven, and the rows come back for rung 4: %s"
          % (good["detail"],),
          good["verdict"] == M.PROBE_OK and good["ok"] is True
          and len(good["rows"]) == len(AGILE_ROWS))
    # Measured verbatim: this is what a project name with a typo in it says.
    no_proj = M.probe_verdict({"exitCode": 1, "rows": [],
                               "stderr": "ERROR: The project specified is not "
                                         "found in hierarchy. The error is "
                                         "caused by «'nope'»."})
    check("p2 'not found in hierarchy' is the PROJECT being wrong, and the "
          "verdict says the credential worked - blaming auth here is how a "
          "typo costs an afternoon",
          no_proj["verdict"] == M.PROBE_NO_PROJECT and no_proj["ok"] is False
          and "credential works" in no_proj["detail"])
    # Measured verbatim: an organization that does not exist says THIS.
    login = M.probe_verdict({"exitCode": 1, "rows": [],
                             "stderr": "ERROR: Before you can run Azure DevOps "
                                       "commands, you need to run the login "
                                       "command(az login if using AAD/MSA "
                                       "identity else az devops login if using "
                                       "PAT token) to setup credentials."})
    check("p3 the 'you need to run the login command' text is graded as ONE "
          "verdict naming BOTH readings, because a nonexistent organization "
          "produces it identically - measured, not supposed",
          login["verdict"] == M.PROBE_AUTH_OR_ORG
          and "organization name is wrong" in login["detail"]
          and "does not say which" in login["detail"])
    check("p3b ...and it is a DIFFERENT verdict from p2's, so the two are not "
          "collapsed into one 'it failed'",
          login["verdict"] != no_proj["verdict"]
          and login["detail"] != no_proj["detail"])
    weird = M.probe_verdict({"exitCode": 7, "rows": [], "stderr": "boom"})
    check("p4 an unrecognised failure is its own verdict carrying the message "
          "verbatim, never a fall-through to ok - a probe nobody understood "
          "is not a probe that passed",
          weird["verdict"] == M.PROBE_OTHER and weird["ok"] is False
          and "boom" in weird["detail"])
    check("p5 a non-object envelope is refused rather than read as exit 0 - "
          "`{}.get('exitCode')` is None, and None == 0 is False, but the "
          "shape check is what says so out loud",
          M.probe_verdict(None)["ok"] is False
          and M.probe_verdict([])["ok"] is False)
    check("p6 an exit-0 envelope with NO rows is still ok - an empty project "
          "proves access exactly as a full one does, and refusing it would "
          "make connect unusable on a board nobody has filed anything on",
          M.probe_verdict({"exitCode": 0, "stderr": "", "rows": []})["ok"]
          is True)

    # --- rung 4: process detection ---
    agile = M.detect_process(AGILE_ROWS)
    scrum = M.detect_process(SCRUM_ROWS)
    check("d1 the Agile board proposes 'User Story' for types.pbi, off the "
          "type name - which is the whole reason the type is the "
          "discriminator: this board's observed Task states are %r, and "
          "neither Active nor Resolved is among them"
          % (agile["observed"]["Task"],),
          agile["process"] == "Agile"
          and agile["types"]["pbi"] == "User Story")
    check("d2 the Scrum board proposes 'Product Backlog Item' - the paired "
          "negative, so d1 cannot be passing on a rule that always answers "
          "Agile",
          scrum["process"] == "Scrum"
          and scrum["types"]["pbi"] == "Product Backlog Item"
          and scrum["types"]["pbi"] != agile["types"]["pbi"])
    check("d3 stateMap is REQUIRED on Scrum and NOT on Agile, because the "
          "built-in defaults name %s states - both directions, since a rule "
          "that always warned would satisfy the Scrum half alone"
          % (M.DEFAULT_STATE_PROCESS,),
          scrum["stateMapNeeded"] is True
          and agile["stateMapNeeded"] is False)
    s_advice = M.state_map_advice(scrum)
    a_advice = M.state_map_advice(agile)
    check("d4 the Scrum advice says REQUIRED once and carries the observed "
          "Task states as the SECOND, weaker basis - marked as evidence and "
          "not proof, because a state with no item in it does not appear in a "
          "query over items: %r" % (s_advice[-1][:60],),
          sum(1 for line in s_advice if "REQUIRED" in line) == 1
          and "not proof" in s_advice[-1]
          and "In Progress" in s_advice[-1])
    check("d5 ...and the Agile advice says REQUIRED zero times and reports "
          "%r as observed, which is the corroborating half going the other "
          "way" % (M.DEFAULT_TASK_DONE_STATE,),
          sum(1 for line in a_advice if "REQUIRED" in line) == 0
          and sum(1 for line in a_advice
                  if "somewhere to land" in line) == 1)
    check("d6 Basic proposes 'Issue' for the BUG type too - a process fact "
          "rather than an observation, and the one place it matters: Basic "
          "has no Bug type at all, so a proposal built from 'Bug unless we "
          "saw otherwise' would configure a connector that cannot file one",
          M.detect_process([_row("Issue", "To Do"),
                            _row("Task", "Doing")])["types"]["bug"] == "Issue"
          and scrum["types"]["bug"] == "Bug")

    empty = M.detect_process([])
    no_pbi = M.detect_process([_row("Task", "New"), _row("Bug", "New")])
    check("d7 an EMPTY project detects nothing and says access is proven "
          "anyway - it is not a failure and not a reason to stop",
          empty["process"] is None
          and empty["unknown"] == M.DETECT_UNKNOWN_EMPTY
          and "empty" in empty["basis"])
    check("d8 ...and rows with no phase-level type among them is a DIFFERENT "
          "unknown from an empty project, counted rather than merged: two "
          "reasons nobody can tell apart is one reason nobody can act on",
          no_pbi["process"] is None
          and no_pbi["unknown"] == M.DETECT_UNKNOWN_NO_PBI
          and no_pbi["unknown"] != empty["unknown"]
          and no_pbi["basis"] != empty["basis"])
    two = M.detect_process([_row("User Story", "New"),
                            _row("Product Backlog Item", "New")])
    check("d9 a board carrying TWO phase-level types picks neither and says "
          "the process was customised - and names both candidates, because "
          "the pick is the operator's: %r" % (two["candidates"],),
          two["process"] is None and two["unknown"] == M.DETECT_AMBIGUOUS
          and sorted(two["candidates"]) == ["Agile", "Scrum"])
    check("d10 an undetected process makes the stateMap advice UNDECIDABLE "
          "rather than 'not needed' - the defaults are still Agile's, and "
          "silence would read as a board that needs no map",
          sum(1 for line in M.state_map_advice(empty)
              if "undecidable" in line) == 1
          and sum(1 for line in M.state_map_advice(empty)
                  if "not needed" in line) == 0)
    check("d11 a row with no readable fields is skipped rather than counted "
          "as a type - junk in the query output must not invent a process",
          M.observed_shape([{"fields": None}, {"nope": 1}, "junk",
                            _row("Task", "New")]) == {"Task": ["New"]})
    check("d12 ...and a row with a type but NO state contributes the type "
          "with an empty state list, since the type is what rung 4 reads",
          M.observed_shape([{"fields": {"System.WorkItemType": "Task"}}])
          == {"Task": []})

    # --- rung 5: idempotence over an already-configured manifest ---
    proposal = {"organization": "test-audit-lab", "project": "audit-gate-scrum",
                "enabled": True, "types": scrum["types"]}
    fresh = M.connect_plan(None, proposal)
    check("i1 an unconfigured manifest is four sets, no changes and no keeps",
          fresh["configured"] is False
          and fresh["counts"][M.ACTION_SET] == 4
          and fresh["counts"][M.ACTION_CHANGE] == 0
          and fresh["counts"][M.ACTION_KEEP] == 0)
    same = M.connect_plan(dict(proposal), proposal)
    check("i2 re-running against the manifest it already wrote changes "
          "NOTHING - four keeps, zero writes. Idempotence is the claim, and "
          "the writes figure is what a caller gates on",
          same["counts"][M.ACTION_KEEP] == 4 and same["writes"] == 0
          and same["configured"] is True)
    drifted = M.connect_plan({"organization": "test-audit-lab",
                              "project": "audit-gate-scrum",
                              "enabled": False,
                              "types": {"bug": "Bug", "task": "Task",
                                        "pbi": "User Story"}},
                             proposal)
    changes = [r for r in drifted["rows"] if r["action"] == M.ACTION_CHANGE]
    check("i3 a manifest configured DIFFERENTLY produces change rows carrying "
          "BOTH values - offered, never applied: the value in the file may be "
          "the one a person chose against this command's advice. %d change(s)"
          % (len(changes),),
          len(changes) == 2
          and sorted(r["key"] for r in changes) == ["enabled", "types"]
          and changes[0]["current"] is False
          and changes[0]["proposed"] is True)
    check("i4 ...and the two keys that DO agree are keeps in the same plan, "
          "so i3 is not passing on a rule that reports everything as changed",
          drifted["counts"][M.ACTION_KEEP] == 2
          and drifted["counts"][M.ACTION_SET] == 0)
    partial = M.connect_plan({"organization": "test-audit-lab"},
                             {"organization": "test-audit-lab",
                              "project": "p", "enabled": True})
    check("i5 a proposal missing `types` (an undetected process) plans the "
          "three keys it has and does not invent the fourth - a types.pbi "
          "guessed from nothing is the first-push failure this feature "
          "exists to remove",
          len(partial["rows"]) == 3
          and sum(1 for r in partial["rows"] if r["key"] == "types") == 0)

    # --- the evidence block, and why it carries no expiry date ---
    ev = M.connection_evidence("test-audit-lab", "audit-gate-scrum", scrum,
                               {"inEffect": M.PATH_STORED_PAT},
                               "2026-08-24T09:00:00Z")
    check("e1 meta.ado.connection is the same EVIDENCE shape the other two "
          "meta.ado caches use - a fetchedAt and a basis - so it can be aged "
          "and checked rather than trusted: %r" % (sorted(ev),),
          ev["fetchedAt"] == "2026-08-24T09:00:00Z"
          and isinstance(ev["basis"], str) and ev["basis"]
          and "audit-gate-scrum" in ev["basis"])
    check("e2 it records WHICH auth path was in effect, which is the whole of "
          "what makes a later 401 readable: a stored PAT that worked on a "
          "named day and stops is an expired token, not a broken config",
          ev["authPath"] == M.PATH_STORED_PAT
          and ev["process"] == "Scrum"
          and ev["pbiType"] == "Product Backlog Item"
          and ev["stateMapNeeded"] is True)
    check("e3 an UNDETECTED process still produces the block, with nulls "
          "rather than a guessed process - the stamp of when access was "
          "proven is worth keeping on its own",
          M.connection_evidence("o", "p", empty, {"inEffect": None},
                                "T")["process"] is None)
    pat_note = M.expiry_note({"inEffect": M.PATH_STORED_PAT})
    aad_note = M.expiry_note({"inEffect": M.PATH_AZURE_SIGNIN})
    check("e4 expiry is reported as NOT DISCOVERABLE for a PAT and says why, "
          "instead of a field holding a date nothing can supply - every "
          "surface would print that null and every reader would take it for "
          "'does not expire'",
          "not discoverable" in pat_note and "organization-admin" in pat_note)
    check("e5 ...and the Azure sign-in gets a DIFFERENT note, because what "
          "expires there renews itself hourly and printing that as "
          "'credential expiry' would be worse than printing nothing",
          aad_note != pat_note and "renews" in aad_note
          and M.expiry_note({"inEffect": None}) not in (pat_note, aad_note))

    # The probe query, which both rung 3 and rung 4 read.
    wiql = M.probe_wiql("audit-gate-scrum")
    check("w1 the probe is a Work Items query naming the project, and reaches "
          "for no other scope - a `project list` probe needs a different "
          "scope and would report a false failure on a PAT scoped exactly "
          "right for this connector",
          wiql.count("audit-gate-scrum") == 1
          and "System.WorkItemType" in wiql and "System.State" in wiql
          and "Work Items" in M.REQUIRED_SCOPE)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ado_connect.py --selftest\n")
    raise SystemExit(2)
