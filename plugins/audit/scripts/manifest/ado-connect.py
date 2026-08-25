#!/usr/bin/env python3
"""
The ladder `/audit:sync connect` climbs before anything is written.

WHY IT EXISTS. The connector is the first thing a new person on a team touches
and was the only part with no guided path: install the extension,
authenticate, work out which auth path is in effect, hand-write `meta.ado` -
and only then find out whether any of it worked, because the first thing that
PROVED access was a `push`, which is also the first thing that can CREATE
items on somebody's real board. Every rung below is read-only. The write is
step 5, it goes to the manifest and nowhere else, and the orchestrator does it
behind an AskUserQuestion.

IT NEVER HANDLES CREDENTIALS. Auth belongs to `az` / the MCP server: after
`az devops login` the credential already lives in the CLI's own store and every
process on the machine uses it, so there is nothing here to capture. The three
observations below are a PATH lookup, a JSON listing of extension names, and a
file of organization URLs - no token is read, echoed, copied or stored, and
this plugin's own `guard-secrets-read` hook exists to block the other move.

THE RULE IS NOT HERE. `_ado_connect` owns every decision and takes its
observations as arguments; this file is the door, and it is a real command
rather than a `python3 -c` one-liner for the reason `check-ado-item` is: a
one-liner naming a source path is exactly the shape `guard-secrets-read`
refuses, so the check would be blocked on the machines that most need it.

THE BOARD CALL IS THE CALLER'S. `az` is not run against a board here, because
the session may be holding MCP tools this file could never call - so rung 3
grades an ENVELOPE the caller writes after making the call it chose:

  {"exitCode": 0, "stderr": "", "rows": [ ...`az boards query` output... ]}

Usage:
  ado-connect.py <manifest>                        # rungs 1-2, then the query
  ado-connect.py <manifest> --probe <probe.json>   # rungs 1-4 + the plan
  ado-connect.py <manifest> --probe -              # envelope on stdin
  ado-connect.py <manifest> --transport mcp        # the session has MCP tools
  ado-connect.py <manifest> --probe p.json --json

Exit codes: 0 = ready (with `--probe`: a proposal to confirm) - 1 = a rung
stopped the run - 2 = usage error or unreadable input.
"""
import json
import os
import shutil
import subprocess
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

import _ado_connect as _conn  # noqa: E402  (every decision this door reports)

USAGE = ("usage: ado-connect.py <manifest> [--transport auto|mcp|az] "
         "[--probe <file.json|->] [--json]\n")

# Where `az devops login` records WHICH organizations it holds a PAT for. The
# file is a list of organization URLs; the tokens live in the OS keyring and
# nothing here opens it. Read because it is the only observation that binds a
# credential to ONE organization, which is the question rung 2 asks.
STORED_ORGS_FILE = os.path.join("~", ".azure", "azuredevops", "organization_list")


def iso_now():
    """Wall clock, isolated so nothing above reaches for one.

    `now(timezone.utc)` rather than `utcnow()`: that spelling is deprecated and
    warns on every call, while `datetime.UTC` needs 3.11 and this tree holds a
    3.8 floor. Same body as `_proposals.iso_now()` and deliberately not shared:
    that module is L4 and this is the door, so importing it to reach two lines
    would be an upward edge the layer lint refuses.
    """
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# --- observations: the only part that touches this machine ----------------------
def extension_reading(has_az, completed, error):
    """`{names, saw}` from ONE `az extension list` attempt. Takes no I/O.

    `names` is None whenever the list did not answer - a distinct value on
    purpose, since `transport_verdict` stops on it rather than reading it as
    "the extension is missing" OR as "present". `saw` is the half this door used
    to throw away: `az extension list did not answer` is true of a tool that is
    absent, of a sandbox that refused it, and of output that was not JSON, and
    those are three different places to go next. The operator had to re-run the
    command by hand to find out which - so the exit code and the stderr, which
    are the only evidence this process has, are carried instead of summarised.

    Pure so that both causes are reachable from a case on a machine with no `az`
    at all, which is why the split exists rather than an inline `except`.
    """
    if not has_az:
        return {"names": None, "saw": "az is not on PATH"}
    if error is not None:
        return {"names": None,
                "saw": "`az extension list` could not be run: %s: %s"
                       % (type(error).__name__, error)}
    code = getattr(completed, "returncode", None)
    stderr = (getattr(completed, "stderr", "") or "").strip()
    if code != 0:
        return {"names": None,
                "saw": "`az extension list` exited %s: %s"
                       % (code, stderr or "(nothing on stderr)")}
    stdout = getattr(completed, "stdout", "") or ""
    try:
        parsed = json.loads(stdout or "null")
    except Exception as exc:
        return {"names": None,
                "saw": "`az extension list` exited 0 and its output is not JSON "
                       "(%s): %r" % (exc, stdout[:120])}
    if not isinstance(parsed, list):
        return {"names": None,
                "saw": "`az extension list` exited 0 and returned %s, not the "
                       "list of extensions" % (type(parsed).__name__,)}
    names = [e.get("name") for e in parsed if isinstance(e, dict)]
    return {"names": names,
            "saw": "`az extension list` named %d extension(s)" % (len(names),)}


def az_extensions():
    """`extension_reading` over a real attempt. The I/O edge, and nothing else."""
    if not shutil.which("az"):
        return extension_reading(False, None, None)
    try:
        out = subprocess.run(["az", "extension", "list", "--output", "json"],
                             capture_output=True, text=True, timeout=20)
    except Exception as exc:
        return extension_reading(True, None, exc)
    return extension_reading(True, out, None)


def azure_signin():
    """The Azure sign-in `az account show` reports, or None.

    The USER NAME only. `az account show` prints no credential, and nothing
    here reaches for one that does.
    """
    if not shutil.which("az"):
        return None
    try:
        out = subprocess.run(["az", "account", "show", "--output", "json"],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    try:
        parsed = json.loads(out.stdout or "null")
    except Exception:
        return None
    user = parsed.get("user") if isinstance(parsed, dict) else None
    name = user.get("name") if isinstance(user, dict) else None
    return name if isinstance(name, str) and name else None


def stored_org_listing():
    """The text of `az devops login`'s organization list, or None if there is none."""
    path = os.path.expanduser(STORED_ORGS_FILE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def observe(transport_hint):
    """Everything the rules need from this machine, in one dict.

    Separated from `report()` so the decision path is reachable from a test
    with no `az`, no network and no credential - which is the only way the
    stopping rungs below ever get exercised.
    """
    has_mcp = transport_hint == "mcp"
    has_az = bool(shutil.which("az"))
    # Not consulted when MCP carries the session: the extension list is slow, and
    # az is not the transport then. SAID rather than left blank - "we did not
    # look" and "we looked and saw nothing" are different answers, and this is
    # the field that has to keep them apart.
    reading = ({"names": None,
                "saw": "not consulted - the session carries the azure-devops "
                       "MCP tools, so az is not the transport"}
               if has_mcp else az_extensions())
    return {"hasMcp": has_mcp,
            "hasAz": has_az,
            "extensions": reading["names"],
            "extensionsSaw": reading["saw"],
            "signedInAs": None if has_mcp else azure_signin(),
            # MEMBERSHIP, never the value. This is the whole of what this
            # command knows about that variable.
            "patEnvSet": _conn.PAT_ENV_VAR in os.environ,
            "storedOrgs": _conn.stored_pat_orgs(stored_org_listing())}


# --- the report -----------------------------------------------------------------
def ado_of(manifest):
    """`meta.ado`, or None. Tolerant on the way down: a wrong-typed `meta` is
    `check_ado_meta`'s finding to report, not this command's to crash on."""
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    ado = meta.get("ado") if isinstance(meta, dict) else None
    return ado if isinstance(ado, dict) else None


def _target(ado, argv):
    """(organization, project) - from `--org`/`--project`, else the manifest."""
    org = _flag(argv, "--org") or (ado or {}).get("organization")
    project = _flag(argv, "--project") or (ado or {}).get("project")
    return org, project


def _flag(argv, name):
    if name in argv:
        i = argv.index(name)
        if len(argv) > i + 1 and not argv[i + 1].startswith("-"):
            return argv[i + 1]
    return None


def report(manifest, facts, envelope, organization, project, now):
    """The whole ladder, as lines plus a machine-readable answer.

    Returns `{"lines": [...], "code": int, "data": {...}}`. `envelope` is None
    when the caller has not made the board call yet - rungs 1 and 2 still run,
    because they are what says whether making it is worth the round trip.
    """
    lines = []
    data = {"transport": None, "auth": None, "probe": None, "process": None,
            "plan": None, "connection": None}

    # --- rung 1: transport ---
    t = _conn.transport_verdict(facts.get("hasAz"), facts.get("extensions"),
                                facts.get("hasMcp"))
    data["transport"] = t
    # The RULE's basis, then WHAT WAS SEEN, then the remedy. The rule can only say
    # that the list did not answer; the observation is the thing that separates a
    # missing extension from a sandbox refusing the call, and a reader who has
    # both goes to the right place in one step instead of re-running by hand.
    # Absent when the caller made no such observation, because a report that
    # invented one would be the same defect one layer along.
    if t["stop"]:
        lines.append("STOP (transport): %s" % (t["stop"],))
        lines.append("  basis: %s" % (t["basis"],))
        if facts.get("extensionsSaw"):
            lines.append("  saw:   %s" % (facts["extensionsSaw"],))
        lines.append("  fix:   %s" % (t["remedy"],))
        return {"lines": lines, "code": 1, "data": data}
    lines.append("transport: %s - %s" % (t["transport"], t["basis"]))
    if facts.get("extensionsSaw"):
        lines.append("  saw: %s" % (facts["extensionsSaw"],))

    if not organization or not project:
        lines.append("STOP (target): no organization/project to connect to - "
                     "pass --org and --project, or set meta.ado.organization "
                     "and meta.ado.project.")
        return {"lines": lines, "code": 1, "data": data}

    # --- rung 2: which auth path is in effect ---
    if t["transport"] == _conn.TRANSPORT_MCP:
        # Said rather than skipped. A rung that prints nothing cannot be told
        # from a rung that found nothing, and the MCP server's identity is
        # genuinely outside this command's reach.
        auth = {"paths": [], "absent": [], "inEffect": None,
                "ambiguous": False, "stop": None, "remedy": None,
                "note": "identity: the MCP server holds it, and this command "
                        "cannot see which account it authenticated as."}
        lines.append("identity: %s" % (auth["note"],))
    else:
        auth = _conn.auth_path_report(organization, facts.get("patEnvSet"),
                                      facts.get("signedInAs"),
                                      facts.get("storedOrgs"))
        if auth["stop"]:
            lines.append("STOP (identity): %s" % (auth["stop"],))
            for line in auth["absent"]:
                lines.append("  - %s" % (line,))
            lines.append("  fix: %s" % (auth["remedy"],))
            data["auth"] = auth
            return {"lines": lines, "code": 1, "data": data}
        lines.append("identity, for organization %r:" % (organization,))
        for entry in auth["paths"]:
            lines.append("  IN PLAY: %s" % (entry["line"],))
        for line in auth["absent"]:
            lines.append("  absent:  %s" % (line,))
        lines.append("  %s" % (auth["note"],))
    data["auth"] = auth
    lines.append("PAT scope this connector needs, and nothing else: %s"
                 % (_conn.REQUIRED_SCOPE,))
    lines.append(_conn.expiry_note(auth))

    # --- rung 3: the read-only probe ---
    if envelope is None:
        lines.append("")
        lines.append("NEXT: make the read-only probe, then re-run with "
                     "--probe. It is one Work Items query and it is the same "
                     "one rung 4 reads:")
        lines.append("  az boards query --organization "
                     "https://dev.azure.com/%s --project %s --wiql \"%s\" "
                     "--output json" % (organization, project,
                                        _conn.probe_wiql(project)))
        lines.append("  ...then write {\"exitCode\": <code>, \"stderr\": "
                     "\"<stderr>\", \"rows\": <that JSON>} and pass it to "
                     "--probe.")
        return {"lines": lines, "code": 0, "data": data}

    probe = _conn.probe_verdict(envelope)
    data["probe"] = probe
    if not probe["ok"]:
        lines.append("STOP (probe): %s" % (probe["detail"],))
        if probe["remedy"]:
            lines.append("  fix: %s" % (probe["remedy"],))
        lines.append("  NOTHING WAS WRITTEN - the manifest is untouched, and "
                     "no work item was created or read beyond the query above.")
        return {"lines": lines, "code": 1, "data": data}
    lines.append("probe: %s" % (probe["detail"],))

    # --- rung 4: process detection ---
    detected = _conn.detect_process(probe["rows"])
    data["process"] = detected
    if detected["process"] is None:
        lines.append("process: NOT DETECTED (%s) - %s"
                     % (detected["unknown"], detected["basis"]))
    else:
        lines.append("process: %s - %s"
                     % (detected["process"], detected["basis"]))
        lines.append("  types.pbi  -> %r" % (detected["types"]["pbi"],))
        lines.append("  types.bug  -> %r" % (detected["types"]["bug"],))
        lines.append("  types.task -> %r" % (detected["types"]["task"],))
    for line in _conn.state_map_advice(detected):
        lines.append(line)

    # --- rung 5: what would be written, over what is already there ---
    existing = ado_of(manifest)
    proposal = {"organization": organization, "project": project,
                "enabled": True}
    if detected["types"]:
        proposal["types"] = detected["types"]
    plan = _conn.connect_plan(existing, proposal)
    data["plan"] = plan
    data["connection"] = _conn.connection_evidence(organization, project,
                                                   detected, auth, now)
    lines.append("")
    lines.append("PLAN - %s: %d to set, %d to change, %d already right."
                 % ("this manifest already configures meta.ado"
                    if plan["configured"] else "meta.ado is not configured yet",
                    plan["counts"][_conn.ACTION_SET],
                    plan["counts"][_conn.ACTION_CHANGE],
                    plan["counts"][_conn.ACTION_KEEP]))
    for row in plan["rows"]:
        if row["action"] == _conn.ACTION_KEEP:
            lines.append("  keep   meta.ado.%s = %r" % (row["key"],
                                                        row["current"]))
        elif row["action"] == _conn.ACTION_SET:
            lines.append("  set    meta.ado.%s = %r" % (row["key"],
                                                        row["proposed"]))
        else:
            lines.append("  CHANGE meta.ado.%s: %r -> %r (offered, never "
                         "applied without your answer)"
                         % (row["key"], row["current"], row["proposed"]))
    # OUTSIDE the counts above, and said so rather than left to be noticed: the
    # evidence block is re-stamped on every run BY DEFINITION - a fresh
    # `fetchedAt` is what re-probing produces - so counting it would make the
    # "already right" figure permanently one short, and printing it inside a
    # plan that says "0 to set" would be a line contradicting the line above it.
    # F184. TWO CLAIMS, AND EACH ONE CARRIES THE BASIS THAT MAKES IT TRUE. This
    # line said "replaces the last run's" unconditionally, so a FIRST connect
    # announced it was overwriting evidence that had never been recorded - and
    # that reading is what a confirm's decline option is composed from, which is
    # how it went on to promise an older moment of proven access that does not
    # exist. `plan["evidence"]` is the prior block itself or None: the claim about
    # replacing is made only when there is something to replace, and it names
    # WHEN, because that is the whole value of the field.
    prior = plan.get("evidence")
    prior_at = (prior or {}).get("fetchedAt")
    if prior_at:
        lines.append("  restamp (not counted above) meta.ado.connection = "
                     "<process, pbiType, stateMapNeeded, authPath, fetchedAt, "
                     "basis> - this run's evidence replaces the evidence stamped "
                     "%s, because a moment that is not now is the wrong moment"
                     % (prior_at,))
    else:
        lines.append("  stamp (not counted above) meta.ado.connection = "
                     "<process, pbiType, stateMapNeeded, authPath, fetchedAt, "
                     "basis> - the FIRST evidence for this connection; nothing "
                     "here is being replaced, because nothing was recorded")
    # THE DECLINE CONSEQUENCE IS PRINTED, NOT COMPOSED. `commands/sync.md` sends
    # the plan block into a confirm, and the option that declines needs a sentence
    # too - which was being written from the restamp line above and inherited its
    # false premise. A reader deciding not to write is owed the same standard of
    # claim as one deciding to.
    if prior_at:
        lines.append("  decline - nothing is written and meta.ado.connection "
                     "keeps the evidence stamped %s, which is then the last "
                     "moment access was proven" % (prior_at,))
    else:
        lines.append("  decline - nothing is written and there is no earlier "
                     "evidence to fall back on: this connection stays unproven "
                     "until a run of this command is applied")
    lines.append("")
    lines.append("This command wrote nothing. Confirm the plan, apply it to "
                 "the manifest, revalidate with validate-manifest.py, then "
                 "run /audit:sync status.")
    return {"lines": lines, "code": 0, "data": data}


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write(USAGE)
        return 2
    manifest_path = argv[0]
    transport_hint = _flag(argv, "--transport") or "auto"
    if transport_hint not in ("auto", "mcp", "az"):
        sys.stderr.write(USAGE)
        return 2
    probe_path = _flag(argv, "--probe")
    if "--probe" in argv and not probe_path:
        sys.stderr.write(USAGE)
        return 2

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n"
                         % (manifest_path, exc))
        return 2

    envelope = None
    if probe_path:
        try:
            if probe_path == "-":
                envelope = json.load(sys.stdin)
            else:
                with open(probe_path, "r", encoding="utf-8") as fh:
                    envelope = json.load(fh)
        except Exception as exc:
            sys.stderr.write("ERROR: cannot read/parse probe envelope %s: %s\n"
                             % (probe_path, exc))
            return 2

    ado = ado_of(manifest)
    organization, project = _target(ado, argv)
    facts = observe(transport_hint)
    answer = report(manifest, facts, envelope, organization, project,
                    iso_now())

    if "--json" in argv:
        print(json.dumps(answer["data"], indent=2, sort_keys=True))
        return answer["code"]
    for line in answer["lines"]:
        print(line)
    return answer["code"]


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("ado-connect.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_ado_connect.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
