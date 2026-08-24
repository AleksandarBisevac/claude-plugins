#!/usr/bin/env python3
"""
What `/audit:sync connect` decides, separated from what it observes.

The connector is the first thing a new person on a team touches and the only
part with no guided path: install the extension, authenticate, work out which
auth path is actually in effect, hand-write `meta.ado`, and only then discover
whether any of it worked - because the first thing that PROVES access is a
`push`, which is also the first thing that can CREATE items on somebody's real
board. `connect` is the read-only ladder that answers those questions before
anything is written, and this module is the half of it that can be tested
without a board: every rung takes its observations as ARGUMENTS.

FOUR RUNGS, EACH WITH ITS OWN STOP.

  1 transport      `transport_verdict`  - MCP tools, else az + the extension.
  2 identity       `auth_path_report`   - which auth path is in effect for
                                          THIS organization.
  3 probe          `probe_verdict`      - what a read-only board call proved.
  4 process        `detect_process`     - Agile or Scrum, and what that costs.

WHY THE BOARD CALL IS NOT MADE HERE. `check-ado-item` and `explain-ado-drift`
already split this way and for the same two reasons: the orchestrator may be
holding MCP tools this module could never call, and a rule that needs
credentials to test is a rule nobody tests. So rung 3 grades an envelope the
caller writes - `{exitCode, stderr, rows}` - and rungs 1 and 2 read only the
local machine.

CREDENTIALS ARE NEVER READ, ONLY COUNTED. Rung 2 answers "which path" from
three things that are not secrets: whether an environment variable is SET
(never its value), the Azure sign-in `az account show` prints, and the list of
organizations `az devops login` has stored a PAT for - a file of org URLs with
no token in it. This plugin's own `guard-secrets-read` hook exists to block the
other move, and a connector that captured a token would be the thing it guards
against.

AND WHERE IT CANNOT TELL, IT SAYS SO. Two auth paths can be present at once -
measured on the machine this was written on, where one organization resolves
through a stored PAT and another through the Azure sign-in, at the same time -
and nothing observable from outside says which one answered. So more than one
present path is reported as ambiguous BY NAME rather than resolved by a
precedence rule this module cannot verify. The fact that matters is true
either way and is the trap this rung exists for: a board command that succeeds
proves the ORGANIZATION is reachable, never which identity reached it.

Layer 1: it reaches nothing but `_output`. Everything - `meta.ado`, the
environment, the probe - arrives as an argument, which is what lets the entry
point be the only part that touches a machine.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__ado_connect.py` - see
`plugins/audit/tests/_harness.py`.
"""
import os
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()


# --- rung 1: transport ----------------------------------------------------------
# The name of the environment variable, never its value. Named as a constant so
# the one place that could ever read a token is the one place that provably does
# not: every caller below takes a BOOLEAN saying whether it is set.
PAT_ENV_VAR = "AZURE_DEVOPS_EXT_PAT"

TRANSPORT_MCP = "mcp"
TRANSPORT_AZ = "az"

# The scope this connector needs, and the reason it is the only one asked for.
# `az devops project list` would need a different scope, so probing with it
# would report a false failure on a PAT scoped exactly right - which is why
# rung 3's probe is a work-item query.
REQUIRED_SCOPE = "Work Items -> Read & write"


def transport_verdict(has_az, extensions, has_mcp):
    """Which transport `connect` may use, or the rung that stops it.

    `extensions` is the installed `az` extension NAMES, or None when the list
    could not be taken. None is its own stop and not a pass: an extension list
    that did not answer says nothing about whether `azure-devops` is there, and
    reading it as present would send the run on to a board call whose failure
    names the wrong cause.
    """
    if has_mcp:
        return {"transport": TRANSPORT_MCP, "stop": None, "remedy": None,
                "basis": "the session carries the azure-devops MCP tools"}
    if not has_az:
        return {"transport": None, "stop": "az is not on PATH and this session "
                "carries no azure-devops MCP tools - there is no transport to "
                "reach a board with",
                "remedy": "install azure-cli, then: az extension add --name "
                          "azure-devops",
                "basis": "shutil.which('az') found nothing"}
    if extensions is None:
        return {"transport": None, "stop": "az is on PATH but `az extension "
                "list` did not answer, so whether the azure-devops extension "
                "is installed is unknown - which is not the same as installed",
                # F98 CARRIED THE EVIDENCE AND THIS SENTENCE HAD NOT NOTICED.
                # It used to send the operator off to run `az extension list`
                # by hand and read its error - which was the only way to tell a
                # missing tool from a sandbox refusal until the reading grew a
                # `saw` half. The report prints that observation between this
                # rung's basis and this remedy, so the answer is already on
                # screen and re-running is work with a known result. Point at
                # it instead: a remedy naming the line beats one asking for a
                # second run of the command that produced it.
                "remedy": "read the `saw:` line above - it carries that call's "
                          "exit code and its stderr, which is what separates a "
                          "sandbox refusing the call from a tool that is not "
                          "there; if the extension is simply missing: az "
                          "extension add --name azure-devops",
                "basis": "`az extension list` failed or returned no JSON"}
    if "azure-devops" not in extensions:
        return {"transport": None, "stop": "az is on PATH but the azure-devops "
                "extension is not installed - `az boards` does not exist "
                "without it",
                "remedy": "az extension add --name azure-devops",
                "basis": "`az extension list` named %d extension(s), none of "
                         "them azure-devops" % (len(extensions),)}
    return {"transport": TRANSPORT_AZ, "stop": None, "remedy": None,
            "basis": "az is on PATH and the azure-devops extension is installed"}


# --- rung 2: which auth path is in effect ---------------------------------------
PATH_ENV_PAT = "env"
PATH_STORED_PAT = "stored"
PATH_AZURE_SIGNIN = "signin"


def org_key(organization):
    """The organization as `az devops login`'s stored-credential list spells it.

    An organization reaches this plugin as a bare name or as a URL, and the
    stored list holds a normalised URL - so the two are compared here once
    rather than at each call site. Case is dropped because the CLI drops it.
    """
    if not isinstance(organization, str) or not organization.strip():
        return None
    text = organization.strip().rstrip("/")
    tail = text.rsplit("/", 1)[-1] if "/" in text else text
    return tail.lower() or None


def stored_pat_orgs(listing):
    """The organizations `az devops login` has stored a PAT for, as org keys.

    `listing` is the text of `~/.azure/azuredevops/organization_list`, or None
    when there is no such file. That file names ORGANIZATIONS and holds no
    token - the tokens live in the OS keyring, which nothing here opens.
    """
    if not isinstance(listing, str):
        return []
    out = []
    for line in listing.splitlines():
        key = org_key(line.strip().split(":", 1)[-1] if ":" in line else line)
        if key and key not in out:
            out.append(key)
    return out


def auth_path_report(organization, pat_env_set, signed_in_as, stored_orgs):
    """Which auth path `az devops` will use for THIS organization.

    `signed_in_as` is what `az account show` reported (a user name), or None
    when it reported nothing. `stored_orgs` is `stored_pat_orgs()`'s answer.

    THE VERDICT IS NOT A PRECEDENCE RULE. When more than one path is present
    the honest answer is that nothing observable from outside says which one
    `az` used, so this returns `ambiguous` and names them all. The fact the
    caller actually needs holds either way, and is the reason this rung exists:
    a board command that succeeds proves the organization is REACHABLE, not
    which identity reached it.
    """
    want = org_key(organization)
    paths = []
    if pat_env_set:
        paths.append({"path": PATH_ENV_PAT,
                      "line": "the %s environment variable is SET (this "
                              "command reads whether it exists, never its "
                              "value)" % (PAT_ENV_VAR,)})
    if want and want in (stored_orgs or []):
        paths.append({"path": PATH_STORED_PAT,
                      "line": "`az devops login` has stored a PAT for "
                              "organization %r - stored credentials are "
                              "PER-ORGANIZATION, which is why this line names "
                              "one" % (organization,)})
    if signed_in_as:
        paths.append({"path": PATH_AZURE_SIGNIN,
                      "line": "`az account show` reports Azure sign-in %r"
                              % (signed_in_as,)})

    # The absences are printed too. A rung that speaks only when it finds
    # something cannot be told apart from a rung that did not run, and the
    # absence is what makes the remaining path an answer rather than a guess.
    absent = []
    if not pat_env_set:
        absent.append("the %s environment variable is not set" % (PAT_ENV_VAR,))
    if want and want not in (stored_orgs or []):
        absent.append("`az devops login` has stored no PAT for organization %r "
                      "(%d other organization(s) stored)"
                      % (organization, len(stored_orgs or [])))
    if not signed_in_as:
        absent.append("`az account show` reports no Azure sign-in")

    if not paths:
        return {"paths": [], "absent": absent, "inEffect": None,
                "ambiguous": False,
                "stop": "no auth path at all: no %s, no stored PAT for %r, and "
                        "no Azure sign-in - `az devops` has nothing to "
                        "authenticate with"
                        % (PAT_ENV_VAR, organization),
                "remedy": "az login (Azure identity), or az devops login "
                          "--organization https://dev.azure.com/%s (PAT, scope "
                          "%s)" % (organization, REQUIRED_SCOPE),
                "note": None}
    if len(paths) == 1:
        return {"paths": paths, "absent": absent, "inEffect": paths[0]["path"],
                "ambiguous": False, "stop": None, "remedy": None,
                "note": "one path is present, so it is the one the commands "
                        "will use."}
    return {"paths": paths, "absent": absent, "inEffect": None,
            "ambiguous": True, "stop": None, "remedy": None,
            "note": "%d auth paths are present at once and nothing observable "
                    "from outside says which one `az` answered with - so this "
                    "command does not pick one. What holds either way is the "
                    "part that matters: a board command that succeeds proves "
                    "the ORGANIZATION is reachable, never which identity "
                    "reached it." % (len(paths),)}


# --- rung 3: what the probe proved -----------------------------------------------
PROBE_OK = "ok"
PROBE_AUTH_OR_ORG = "auth-or-org"
PROBE_NO_PROJECT = "no-project"
PROBE_OTHER = "other"


def probe_verdict(envelope):
    """Grade the read-only board call the caller made. Returns a verdict dict.

    `envelope` is `{"exitCode": int, "stderr": str, "rows": [...]}` - one shape
    for success and failure both, so the failure branch is reachable from a
    test without a board.

    THE `login` MESSAGE DOES NOT MEAN "NOT LOGGED IN", and that is a measured
    fact rather than a caution: `az boards query` against an organization that
    does not exist answers "Before you can run Azure DevOps commands, you need
    to run the login command", identically to a genuine credential failure. So
    that text is graded as ONE verdict naming both readings. Telling a user to
    log in again when the organization name has a typo in it is the kind of
    wrong answer that costs an afternoon.
    """
    if not isinstance(envelope, dict):
        return {"verdict": PROBE_OTHER, "ok": False, "rows": [],
                "detail": "the probe envelope is %s, not an object "
                          "{exitCode, stderr, rows}"
                          % (type(envelope).__name__,),
                "remedy": None}
    code = envelope.get("exitCode")
    stderr = envelope.get("stderr")
    stderr = stderr if isinstance(stderr, str) else ""
    rows = envelope.get("rows")
    rows = rows if isinstance(rows, list) else []
    low = stderr.lower()

    if code == 0:
        return {"verdict": PROBE_OK, "ok": True, "rows": rows,
                "detail": "the work-item query answered: %d item(s) readable "
                          "in this project" % (len(rows),),
                "remedy": None}
    if "not found in hierarchy" in low or "project specified is not found" in low:
        return {"verdict": PROBE_NO_PROJECT, "ok": False, "rows": [],
                "detail": "the organization answered, but it has no such "
                          "project - so the credential works and the project "
                          "name is what is wrong",
                "remedy": "check the project name; `az devops project list "
                          "--organization <org>` lists them (a different "
                          "scope, so it may itself be refused)"}
    if "you need to run the login command" in low or "tf400813" in low:
        return {"verdict": PROBE_AUTH_OR_ORG, "ok": False, "rows": [],
                "detail": "az could not authenticate to this ORGANIZATION. "
                          "The message is the same one an organization that "
                          "does not exist produces, so it says either the "
                          "identity cannot reach this organization or the "
                          "organization name is wrong - it does not say which",
                "remedy": "confirm the organization name, then: az login, or "
                          "az devops login --organization "
                          "https://dev.azure.com/<org> (PAT scope %s)"
                          % (REQUIRED_SCOPE,)}
    return {"verdict": PROBE_OTHER, "ok": False, "rows": [],
            "detail": "the probe failed with exit %r and a message this "
                      "command does not recognise: %s"
                      % (code, stderr.strip()[:200] or "(no stderr)"),
            "remedy": None}


def probe_wiql(project):
    """The read-only query rung 3 and rung 4 share. One call, two readings.

    Work Items scope and nothing else, deliberately: it is the only scope this
    connector needs and the only one a careful person will have granted, so a
    probe that reached for `project list` would report a false failure on a PAT
    scoped exactly right.
    """
    return ("SELECT [System.Id], [System.WorkItemType], [System.State] "
            "FROM WorkItems WHERE [System.TeamProject] = '%s'" % (project,))


# --- rung 4: which process this board runs ---------------------------------------
# Per process: the phase-level type, the work item types `meta.ado.types` should
# name, and the Task states the process defines. ORDERED as tracker-sync.md's
# auto-detect is (Product Backlog Item -> User Story -> Requirement -> Issue),
# because a board carrying two of these types has been customised and the first
# match is the documented pick.
#
# `types` is a PROCESS fact, not an observation. Basic is why that distinction
# earns its place: Basic has no Bug type at all, so a proposal built from
# "Bug unless we saw otherwise" would configure a connector that cannot file a
# bug on the one process where that is knowable in advance.
PROCESSES = (
    {"name": "Scrum", "pbi": "Product Backlog Item",
     "types": {"bug": "Bug", "task": "Task", "pbi": "Product Backlog Item"},
     "taskStates": ("To Do", "In Progress", "Done", "Removed")},
    {"name": "Agile", "pbi": "User Story",
     "types": {"bug": "Bug", "task": "Task", "pbi": "User Story"},
     "taskStates": ("New", "Active", "Closed", "Removed")},
    {"name": "CMMI", "pbi": "Requirement",
     "types": {"bug": "Bug", "task": "Task", "pbi": "Requirement"},
     "taskStates": ("Proposed", "Active", "Resolved", "Closed")},
    {"name": "Basic", "pbi": "Issue",
     "types": {"bug": "Issue", "task": "Task", "pbi": "Issue"},
     "taskStates": ("To Do", "Doing", "Done")},
)

# The process the shipped `stateMap` defaults name. Everything else needs a map,
# and that is the single most likely first-push failure this rung removes.
DEFAULT_STATE_PROCESS = "Agile"
# The state the built-in default sends a done task to. Held here rather than
# spelled into a message twice, because the two would drift apart the first time
# the default changed and only one of them would be read.
DEFAULT_TASK_DONE_STATE = "Closed"

DETECT_UNKNOWN_EMPTY = "empty"
DETECT_UNKNOWN_NO_PBI = "no-pbi-type"
DETECT_AMBIGUOUS = "ambiguous"


def observed_shape(rows):
    """{work item type: sorted states seen} from the probe's rows.

    OBSERVED, not defined - the states are the ones items happen to be sitting
    in, so an absent state is evidence and never proof. Every caller below is
    written to that limit.
    """
    shape = {}
    for row in rows or []:
        fields = row.get("fields") if isinstance(row, dict) else None
        if not isinstance(fields, dict):
            continue
        wit = fields.get("System.WorkItemType")
        state = fields.get("System.State")
        if not isinstance(wit, str) or not wit:
            continue
        seen = shape.setdefault(wit, set())
        if isinstance(state, str) and state:
            seen.add(state)
    return dict((k, sorted(v)) for k, v in shape.items())


def detect_process(rows):
    """Which process template this board runs, and what that costs `meta.ado`.

    The DISCRIMINATOR IS THE PHASE-LEVEL TYPE, not the states. Measured on two
    live boards: the Agile one carried `User Story` with only New and Closed in
    use, because no item was sitting in Active or Resolved - so a states-first
    reading would have had to guess where a type name was already decisive.

    Three ways this answers nothing, and they are different answers:
      * no rows at all - the project is empty, so access is proven and there is
        nothing to detect from;
      * rows, but no phase-level type among them - only Tasks and Bugs exist yet;
      * two phase-level types - the process has been customised and the pick is
        the operator's, not this function's.
    """
    shape = observed_shape(rows)
    types_seen = sorted(shape.keys())
    matched = [p for p in PROCESSES if p["pbi"] in shape]

    if not types_seen:
        return {"process": None, "unknown": DETECT_UNKNOWN_EMPTY,
                "types": None, "stateMapNeeded": None, "candidates": [],
                "observed": shape,
                "basis": "the query answered and returned no work items, so "
                         "access is proven and this project is empty - which "
                         "is not the same as undetectable, and not a failure"}
    if not matched:
        return {"process": None, "unknown": DETECT_UNKNOWN_NO_PBI,
                "types": None, "stateMapNeeded": None, "candidates": [],
                "observed": shape,
                "basis": "the query returned %d type(s) (%s) and none of them "
                         "is a phase-level type (%s), so nothing on this board "
                         "says which process it runs yet"
                         % (len(types_seen), ", ".join(types_seen),
                            ", ".join(p["pbi"] for p in PROCESSES))}
    if len(matched) > 1:
        return {"process": None, "unknown": DETECT_AMBIGUOUS,
                "types": None, "stateMapNeeded": None,
                "candidates": [p["name"] for p in matched], "observed": shape,
                "basis": "this board carries %d phase-level types at once (%s), "
                         "which means the process was customised - the pick is "
                         "yours, not this command's"
                         % (len(matched),
                            ", ".join(p["pbi"] for p in matched))}

    proc = matched[0]
    needed = proc["name"] != DEFAULT_STATE_PROCESS
    return {"process": proc["name"], "unknown": None,
            "types": dict(proc["types"]), "stateMapNeeded": needed,
            "candidates": [proc["name"]], "observed": shape,
            "basis": "the board carries %r, which only the %s process defines"
                     % (proc["pbi"], proc["name"])}


def state_map_advice(detected):
    """What `detect_process`'s answer means for `meta.ado.stateMap`. Lines.

    Two bases, and they are not equally strong, so they are printed as two
    lines rather than merged into a verdict: the PROCESS name is the reason a
    map is needed, and the observed Task states are corroboration that can only
    ever be evidence, because an unobserved state may simply have no item in
    it right now.
    """
    if detected.get("process") is None:
        return ["stateMap: undecidable - the process is not known, and the "
                "built-in defaults name %s states. Set the map by hand, or "
                "re-run once the board has a phase-level item on it."
                % (DEFAULT_STATE_PROCESS,)]
    lines = []
    if not detected.get("stateMapNeeded"):
        lines.append("stateMap: not needed - the built-in defaults name %s "
                     "states and this board runs %s."
                     % (DEFAULT_STATE_PROCESS, detected["process"]))
    else:
        lines.append("stateMap: REQUIRED - the built-in defaults name %s "
                     "states (a done task goes to %r) and this board runs %s, "
                     "which does not define them."
                     % (DEFAULT_STATE_PROCESS, DEFAULT_TASK_DONE_STATE,
                        detected["process"]))
    task_states = (detected.get("observed") or {}).get("Task")
    if not task_states:
        lines.append("  no Task is on this board yet, so there is no observed "
                     "evidence either way - the line above rests on the "
                     "process name alone.")
    elif DEFAULT_TASK_DONE_STATE in task_states:
        lines.append("  observed Task states: %s - %r is among them, so the "
                     "built-in default has somewhere to land."
                     % (", ".join(task_states), DEFAULT_TASK_DONE_STATE))
    else:
        lines.append("  observed Task states: %s - %r is not among them. "
                     "Evidence, not proof: a state with no item in it does "
                     "not appear in a query over items."
                     % (", ".join(task_states), DEFAULT_TASK_DONE_STATE))
    return lines


# --- rung 5: what would be written, over what is already there -------------------
# The keys `connect` proposes, in the order the report prints them. `types` is
# last because it is the one the process rung supplies, so a reader following
# the report top to bottom meets it after the evidence for it.
PROPOSED_KEYS = ("organization", "project", "enabled", "types")

ACTION_SET = "set"
ACTION_KEEP = "keep"
ACTION_CHANGE = "change"


def connect_plan(existing_ado, proposal):
    """Per key: what is there, what is proposed, and which of the three it is.

    IDEMPOTENCE IS THE WHOLE POINT OF THE `change` ROW. Running `connect`
    against a manifest somebody already configured must report what is there
    and OFFER the difference - never duplicate it and never overwrite it
    quietly, because the value already in the file may be the one a person
    chose against this command's advice.
    """
    have = existing_ado if isinstance(existing_ado, dict) else {}
    rows = []
    for key in PROPOSED_KEYS:
        if key not in proposal:
            continue
        want = proposal[key]
        if key not in have:
            rows.append({"key": key, "current": None, "proposed": want,
                         "action": ACTION_SET})
        elif have[key] == want:
            rows.append({"key": key, "current": have[key], "proposed": want,
                         "action": ACTION_KEEP})
        else:
            rows.append({"key": key, "current": have[key], "proposed": want,
                         "action": ACTION_CHANGE})
    counts = {ACTION_SET: 0, ACTION_KEEP: 0, ACTION_CHANGE: 0}
    for row in rows:
        counts[row["action"]] += 1
    return {"rows": rows, "counts": counts,
            "configured": bool(have),
            "writes": counts[ACTION_SET] + counts[ACTION_CHANGE]}


def connection_evidence(organization, project, detected, auth, now):
    """`meta.ado.connection` - what this run PROVED, stamped with when.

    The third cache in `meta.ado` and deliberately the same shape as the two
    `/audit:sync parents` writes: a `fetchedAt` and a `basis`, because evidence
    with no moment cannot be aged and evidence with no basis has to be trusted
    rather than checked.

    IT CARRIES THE AUTH PATH BECAUSE EXPIRY CANNOT BE CARRIED. Neither
    transport can be asked when a credential expires - a PAT's expiry needs
    either the token itself or an organization-admin scope, and the Azure
    sign-in's access token expires hourly and renews itself, so printing that
    as "credential expiry" would be worse than printing nothing. What IS
    knowable is which path was in effect the last time access was proven, and
    that is what gives a later 401 a class: a stored PAT that worked on a named
    day and stops is an expired PAT, not a broken configuration.
    """
    return {"process": detected.get("process"),
            "pbiType": (detected.get("types") or {}).get("pbi"),
            "stateMapNeeded": detected.get("stateMapNeeded"),
            "authPath": (auth or {}).get("inEffect"),
            "fetchedAt": now,
            "basis": "read-only work-item query over %s/%s proved access; %s"
                     % (organization, project, detected.get("basis"))}


def expiry_note(auth):
    """Why no expiry date is recorded, in the terms of the path in effect.

    A field invented to hold a date nothing can supply is worse than the
    absence: every surface would print `null` and every reader would take it
    for "does not expire".
    """
    in_effect = (auth or {}).get("inEffect")
    if in_effect == PATH_STORED_PAT or in_effect == PATH_ENV_PAT:
        return ("expiry: not discoverable - a PAT's expiry date is readable "
                "only from the token itself or through an organization-admin "
                "scope this connector does not ask for. `meta.ado.connection` "
                "records WHEN access was last proven and by WHICH path "
                "instead, so a later 401 reads as an expired token rather "
                "than a broken configuration.")
    if in_effect == PATH_AZURE_SIGNIN:
        return ("expiry: not applicable in the form that bites - the Azure "
                "sign-in's access token expires hourly and `az` renews it. "
                "What expires here is the sign-in itself, which `az account "
                "show` reports as an error rather than as a date.")
    return ("expiry: not recorded - with the auth path itself undecided there "
            "is nothing to say about when it lapses, and a date nobody can "
            "supply is worse than its absence.")
