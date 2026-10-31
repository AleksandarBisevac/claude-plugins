#!/usr/bin/env python3
"""
The workflow runs slices of the one runner, and every slice it names is real.

    tools/gate-parity.py            # the check
    tools/gate-parity.py --list     # each slice verify.sh lists, its tier, and the jobs running it
    tools/gate-parity.py --selftest # this file's own cases

WHY. The gate set used to be described four times by hand - `tools/verify.sh`,
`.github/workflows/ci.yml` and two documents - and the copies drifted IN BOTH
DIRECTIONS at once: the sweep existed twice with different strictness, vitest ran
only in CI, vermin covered a different directory list on each side. This file held
the copies together by reading each one's commands, the report checker's documents
and the sweep's legs, and every CI change cost four edits plus that reader's
fixtures.

ONE EXECUTABLE DESCRIPTION NOW. Every CI job is setup plus one
`tools/verify.sh --only <slices>` call, and the runner alone says what a slice
runs - so the copies are gone rather than compared. What is left to hold is what
the workflow says ABOUT the slices, and `slice_drift()` and `shard_matrix_drift()`
hold it against `verify.sh --list`, asked of the real runner:

  * every slice a job names is one the list prints;
  * every per-run slice is run by a job outside the release tier;
  * a sharded slice's matrix runs every part 1..N on every runner it runs on.

The documents point at `verify.sh --list` instead of listing commands, so there is
no document side left to compare.

IT ALSO HOLDS THE RULES THAT ARE NOT PARITY QUESTIONS, because it is already the
thing that reads a runner - and a hand-maintained description of a machine-readable
fact - for a living. None of them is a parity question; each is a property of how
the gates get run or of what a document claims, and the alternative to keeping them
here was a second reader of the same files:

  * every check the `--affected` selector NAMES must be one the runner can
    DISPATCH. `affected_dispatch()` asks that of the real pair, and it is a
    disagreement the slice rule cannot see: the two files once named the same
    gates while disagreeing about which of them run, so a step the runner had no
    arm for was dropped in silence and the summary went on calling the change
    covered.
  * every fail mode `SECURITY.md` documents must be the one `hooks.json` registers,
    and every wired hook-and-event pair must have a row. `failmode_table_drift()`
    says why that document's drift is a security claim rather than a stale
    paragraph, and why the second direction is what makes the first worth having.
  * every CI job carries a time bound, two to three times the longest run its
    `longest` line records (`untimed_jobs()`, `job_bound_evidence()`).
  * every CI job pins its runner image: no `runs-on`, and no value of a matrix it
    reads, is a floating `*-latest` label (`floating_runners()`).
  * ruff and vermin are pointed at the directories the code lives in: the suites
    at the repository root and the two lint modules under `tools/lints/`, never
    the directory the suites left (`lint_dir_findings()`, `lint_dir_verdict()`).
  * every reason-carrying exemption table names who audits it
    (`exemption_audit_drift()`).
"""
import ast
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile

_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

_output.install_path()

VERIFY_REL = os.path.join("tools", "verify.sh")
CI_REL = os.path.join(".github", "workflows", "ci.yml")

# --- reading a runner's commands ---------------------------------------------
def _shell_command_lines(text):
    """Every line of a shell script that could be a command.

    A comment naming a tool is not an invocation of it, and both gate files talk
    about their own gates at length - this file's own docstring would otherwise
    register as a gate set of its own.
    """
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(line.split(" #")[0].strip())
    return out


# --- does the runner run what the selector names? -----------------------------
# A DISAGREEMENT BETWEEN TWO FILES ABOUT ONE GATE SET that the slice rule cannot
# see, because it never runs the selector: `--affected` narrows a local run to what the working
# tree needs, and `affected.py` chooses the checks while `verify.sh` dispatches
# them. The dispatcher matched three command prefixes; the selector emits a fourth
# for any change under `commands/`, `skills/` or `agents/`, so that step matched no
# arm, ran nothing, and the summary went on saying every selected check was green.
# A dropped gate and a passed gate spelled the same way, in the tool whose whole
# subject is what a narrowed run leaves out.
#
# So this asks the pair the only question that settles it: run the selector, and
# check the runner could dispatch every line it printed. Both halves are READ - the
# accepted prefixes off `verify.sh`, the commands off a real selector run - because
# a rule that restated either would go green while the file it describes moved.

# One probe per arm of the selector that appends a GATE. A suite selection emits
# `python3 <suite> --selftest`, which is the one shape nothing has ever got wrong;
# what has to be exercised here is every branch that appends something else.
AFFECTED_PROBES = (
    # The arm that was broken: plugin prose selects a validator that is neither
    # python nor node. Without this probe the check below is green over a command
    # set that never contained the failing shape.
    "plugins/audit/commands/status.md",
    # A report part: the JavaScript suites, the report gates, the artifacts.
    "plugins/audit/scripts/ui/report/areas.js",
    # A panel part: the browser gate that runs a real server.
    "plugins/audit/scripts/ui/panel/boot.js",
    # A tool that is also a side of the gate set: its own cases, plus this check.
    "tools/gate-parity.py",
)

_ACCEPT_RE = re.compile(r"-e\s+'\^([^']+)'")


def dispatchable_prefixes(text):
    """The command prefixes `verify.sh`'s `--affected` runner will dispatch.

    READ OFF THE RUNNER, never listed here. A copy of that list is the same defect
    one file over: it would agree with the runner on the day it was written and
    stop agreeing without anybody being told.
    """
    for line in _shell_command_lines(text):
        if not line.startswith("grep -v "):
            continue
        found = _ACCEPT_RE.findall(line)
        if found:
            return found
    return []


def steps_in(output):
    """The command lines of a selector run - what the runner dispatches over.

    The selector prints its REASONS first and its commands after a `run:` line, and
    both halves are indented the same way, which is why a dispatcher reading the
    whole thing could not tell one from the other. The rule is the runner's: after
    `run:`, indented, and not the parenthesised sentence the selector uses to say it
    selected nothing.
    """
    out = []
    started = False
    for line in output.splitlines():
        if line.strip() == "run:":
            started = True
            continue
        if not started or not line.startswith("  ") or line.startswith("  ("):
            continue
        out.append(line[2:])
    return out


def affected_dispatch(repo=None):
    """{"undispatchable", "commands", "accepted", "problem"} for the real pair.

    `problem` is not None when the question could not be asked at all - the
    selector refusing to narrow, an unreadable runner, a run that printed no
    commands. Each of those produces an EMPTY undispatchable list, which is the
    exact shape of a clean answer, so the caller is told which one it got.
    """
    root = repo or REPO
    try:
        with io.open(os.path.join(root, VERIFY_REL), encoding="utf-8") as fh:
            accepted = dispatchable_prefixes(fh.read())
    except (IOError, OSError, UnicodeDecodeError) as exc:
        return {"undispatchable": [], "commands": [], "accepted": [],
                "problem": "the runner could not be read: %s" % (exc,)}
    if not accepted:
        return {"undispatchable": [], "commands": [], "accepted": [],
                "problem": "no accepted-prefix list could be read out of %s, so "
                           "nothing here knows what the runner dispatches"
                           % (VERIFY_REL,)}
    proc = subprocess.run(
        [sys.executable, os.path.join(root, "tools", "affected.py")]
        + list(AFFECTED_PROBES),
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        return {"undispatchable": [], "commands": [], "accepted": accepted,
                "problem": "the selector exited %d rather than narrowing, so it "
                           "named no checks to compare: %s"
                           % (proc.returncode, text.strip().splitlines()[:1])}
    commands = steps_in(text)
    if not commands:
        return {"undispatchable": [], "commands": [], "accepted": accepted,
                "problem": "the selector printed no commands for the probe set, "
                           "so an empty result here says nothing"}
    bad = [c for c in commands
           if not any(c.startswith(p) for p in accepted)]
    return {"undispatchable": bad, "commands": commands, "accepted": accepted,
            "problem": None}






# --- SECURITY.md's fail-mode table against the wiring it describes ------------
# ANOTHER RULE HERE THAT IS NOT A PARITY QUESTION, and it is in this file for the
# reason its neighbours above are: this is already the thing that compares a
# hand-maintained description with the machine-readable fact behind it, and what it
# reads is a document against a launcher rather than one document against another.
#
# WHAT THE TABLE PROMISES A READER. `SECURITY.md`'s "Fail modes (by design)" section
# says, per hook and per event, what happens when `hooks/py-launch.sh` can find no
# Python interpreter: a manual approval prompt saying the guards are NOT running, or
# nothing at all. That is decided nowhere near the document - it is the second
# argument of each registration in `hooks/hooks.json`, which the launcher reads as
# `mode`, and SECURITY.md names that file as the authority. Nothing compared them.
#
# WHY THAT MATTERS MORE THAN A STALE DOCUMENT USUALLY DOES. Drift here does not make
# a paragraph out of date; it makes SECURITY.md tell a reader that a BLOCKING guard
# fails silently, or that a silent hook will prompt, at the moment they are deciding
# whether to trust this plugin with their repository. The table was accurate when
# this was written, so the rule catches nothing today - which is the only cheap
# moment there is to start holding one.
#
# BOTH DIRECTIONS, AND THE SECOND IS WHAT MAKES THE FIRST WORTH ANYTHING. A row
# whose cell disagrees with its registration is the obvious half. The other half is
# a wired pair NO row describes: without it, DELETING a row makes the table agree
# with itself, and a description that shrinks quietly is the failure this repo keeps
# finding. A row describing a pair nothing wires any more is reported too, for the
# reason a dead exemption is - an account of a state that has passed stays green
# for ever.
#
# AND THE EVENT DECIDES WHETHER A LOUD FALLBACK IS EVEN POSSIBLE. The launcher's
# prompt is a `permissionDecision`, and the JSON it prints names the one event that
# carries such a channel. A loud mode registered on any other event would print
# JSON the host ignores - a hook the table calls blocking that blocks nothing - so
# the event is checked against the launcher's own payload rather than against a name
# written here.
#
# NOT `check-prohibitions.fail_mode_drift()`, WHICH READS THE SAME FILE AND ASKS
# SOMETHING ELSE. That one asks whether the wiring assigns the loud mode to
# precisely the hooks that can emit a permission decision, over `PreToolUse` and
# `Bash` alone, because that is the set it drives. This one asks whether SECURITY.md
# still describes the wiring, over every event and every hook. Neither subsumes the
# other: a table could be perfectly accurate about a wiring whose loud modes sit on
# the wrong hooks, and a wiring could be exactly right while the document has gone
# stale about it.
HOOKS_JSON_REL = os.path.join("plugins", "audit", "hooks", "hooks.json")
LAUNCHER_REL = os.path.join("plugins", "audit", "hooks", "py-launch.sh")
SECURITY_REL = "SECURITY.md"

# The columns this rule reads, BY HEADING rather than by position: a column inserted
# to the left of one of them would otherwise move every cell it reads one over,
# silently, and the rule would go on comparing something.
HOOK_COLUMN = "Hook"
EVENT_COLUMN = "Event"
FAILMODE_COLUMN = "No interpreter"

# The table's word for the launcher's quiet path. The LOUD word is deliberately NOT
# written here - it is read off `py-launch.sh`, which is the only thing that decides
# which token produces a prompt, and a copy of it here would be one more description
# of the very fact this rule exists to compare.
QUIET_CELL = "silent"

# What the launcher says about itself. `mode="${2:-open}"` is the default a
# registration gets by writing no token at all; the `[ "$mode" = ... ]` test is the
# token that produces a prompt; and the `hookEventName` in the payload it prints is
# the only event with a permission-decision channel to print into.
#
# A MODE IS A SHELL WORD, so the two mode patterns take one rather than letters
# alone - the token today is a bare word, and a reader that could not see a renamed
# one would report a launcher it cannot read instead of the wiring it describes. An
# event name is an identifier the host defines and needs no such room.
_LAUNCH_DEFAULT = re.compile(r'mode="\$\{2:-([A-Za-z0-9_-]+)\}"')
_LAUNCH_LOUD = re.compile(r'\[\s*"\$mode"\s*=\s*"([A-Za-z0-9_-]+)"\s*\]')
_LAUNCH_EVENT = re.compile(r'"hookEventName"\s*:\s*"([A-Za-z]+)"')

_LAUNCHER_BASENAME = os.path.basename(LAUNCHER_REL)


def launcher_contract(text):
    """({"loud", "default", "decision_event"}, problem) read off the launcher.

    A dict or a NAMED problem, never a usable-looking default: every comparison
    below is against one of these values, so a launcher this cannot read produces
    no verdict rather than a verdict taken against a guess.
    """
    default = _LAUNCH_DEFAULT.search(text)
    loud = _LAUNCH_LOUD.search(text)
    event = _LAUNCH_EVENT.search(text)
    if default is None:
        return None, ("names no default mode, so what a registration with no token "
                      "at all gets cannot be read")
    if loud is None:
        return None, ("tests `$mode` against nothing, so which token produces a "
                      "prompt cannot be read")
    if event is None:
        return None, ("prints no `hookEventName`, so the event whose permission "
                      "channel the prompt uses cannot be read")
    return ({"loud": loud.group(1), "default": default.group(1),
             "decision_event": event.group(1)}, None)


def _launched(command, default_mode):
    """`(hook, mode)` for a command that goes through the launcher, else None.

    The mode is positional because that is how the launcher reads it, and an absent
    one is the launcher's DEFAULT rather than nothing - a registration that writes
    no token still has a fail mode, and reading it as absent would let the quietest
    possible wiring go undescribed.
    """
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    for index, token in enumerate(parts):
        if os.path.basename(token) != _LAUNCHER_BASENAME:
            continue
        rest = parts[index + 1:]
        if not rest:
            return None
        hook = os.path.splitext(os.path.basename(rest[0]))[0]
        return (hook, rest[1] if len(rest) > 1 else default_mode)
    return None


def hook_registrations(text, default_mode):
    """{"wired", "unlaunched", "events", "problem"} from `hooks.json`'s own text.

    `events` is the event vocabulary the table's Event column is then read against,
    taken from the registration file rather than listed here: a document may only
    be credited with naming an event the wiring actually uses.

    `unlaunched` is a registration that does not go through the launcher at all.
    Its no-interpreter behaviour is whatever its own command does, which is not
    what this table describes - so it is reported rather than skipped.
    """
    blank = {"wired": [], "unlaunched": [], "events": ()}
    try:
        data = json.loads(text)
    except ValueError as exc:
        blank["problem"] = "does not parse as JSON: %s" % (exc,)
        return blank
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict) \
            or not data["hooks"]:
        blank["problem"] = "carries no `hooks` object, so it registers nothing"
        return blank
    blocks = data["hooks"]
    wired = []
    unlaunched = []
    try:
        for event in blocks:
            for block in blocks[event]:
                for entry in block["hooks"]:
                    got = _launched(entry.get("command", ""), default_mode)
                    if got is None:
                        unlaunched.append((event, entry.get("command", "")))
                        continue
                    wired.append((got[0], event, got[1]))
    except (AttributeError, KeyError, TypeError) as exc:
        blank["problem"] = ("is not shaped like a registration file, so the wiring "
                            "cannot be read: %s" % (exc,))
        return blank
    return {"wired": sorted(set(wired)), "unlaunched": sorted(unlaunched),
            "events": tuple(sorted(blocks)), "problem": None}


def _plain(cell):
    """One table cell with markdown emphasis and code ticks taken off."""
    return cell.replace("**", "").replace("`", "").strip()


def _row_cells(line):
    """The cells of one markdown table row, or None when the line is not one."""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


_RULE_CELL = re.compile(r"^:?-{2,}:?$")


def failmode_rows(text, events):
    """([(lineno, hook, events, cell)], problem) for the fail-mode table.

    THE PARSING TRAPS ARE THE POINT OF THIS FUNCTION, and both are shapes the real
    document already wears:

      * one cell words SEVERAL events (`PreToolUse ..., PostToolUse ...`), so a
        reader that took the first event of a cell would leave the rest of that
        row's pairs described by nothing - and would then agree with a wiring it
        had never looked at;
      * one script appears twice, disambiguated by a parenthetical name, because
        its events fail differently and SECURITY.md says that is what the split is
        for. A reader keying by script name alone would collapse them and score
        one of the pair against the other's cell.

    So a row is a hook plus EVERY event its cell names, and the parenthetical is
    dropped from the hook rather than read as part of its name.
    """
    lines = text.splitlines()
    wanted = ((HOOK_COLUMN, "hook"), (EVENT_COLUMN, "event"),
              (FAILMODE_COLUMN, "mode"))
    start = None
    columns = None
    for lineno, line in enumerate(lines, 1):
        cells = _row_cells(line)
        if cells is None:
            continue
        heads = [_plain(cell).lower() for cell in cells]
        if all(head.lower() in heads for head, _key in wanted):
            columns = dict((key, heads.index(head.lower()))
                           for head, key in wanted)
            start = lineno
            break
    if start is None:
        return [], ("holds no table headed %s, so the fail modes it documents "
                    "cannot be read"
                    % (", ".join("`%s`" % (head,) for head, _key in wanted),))
    rows = []
    for lineno, line in enumerate(lines[start:], start + 1):
        cells = _row_cells(line)
        if cells is None:
            break
        if all(_RULE_CELL.match(cell) for cell in cells if cell):
            continue
        if len(cells) <= max(columns.values()):
            return [], ("has a fail-mode row at line %d with fewer cells than the "
                        "headings above it, so no column can be read off it"
                        % (lineno,))
        hook = re.sub(r"\([^)]*\)", "", _plain(cells[columns["hook"]])).strip()
        named = tuple(event for event in events
                      if re.search(r"\b%s\b" % (re.escape(event),),
                                   cells[columns["event"]]))
        cell = _plain(cells[columns["mode"]]).split("(")[0].strip()
        rows.append((lineno, hook, named, cell))
    if not rows:
        return [], "holds the fail-mode headings with no rows under them"
    return rows, None


def failmode_findings(rows, wired, contract):
    """[(subject, note)] for every disagreement between a table and a wiring.

    Pure over the PARSED pair, so a case can hand it a table and a wiring that
    differ in exactly one place rather than a repo path. Building two real trees
    to move one cell would be a case about the readers wearing a case about the
    rule.
    """
    loud = contract["loud"]
    decision = contract["decision_event"]
    by_pair = {}
    for hook, event, mode in wired:
        by_pair.setdefault((hook, event), set()).add(mode)
    described = {}
    out = []
    for lineno, hook, named, cell in rows:
        if not named:
            out.append(("SECURITY.md line %d" % (lineno,),
                        "names no event any registration uses, so whatever it "
                        "says about `%s` is scored against nothing" % (hook,)))
            continue
        if cell != loud and cell != QUIET_CELL:
            out.append(("SECURITY.md line %d" % (lineno,),
                        "states the fail mode as %r, which is neither `%s` (the "
                        "token the launcher answers with a prompt) nor `%s`"
                        % (cell, loud, QUIET_CELL)))
            continue
        for event in named:
            described.setdefault((hook, event), set()).add(cell)
    conflicted = set()
    for pair in sorted(described):
        hook, event = pair
        cells = described[pair]
        if len(cells) > 1:
            conflicted.add(pair)
            out.append(("%s / %s" % (hook, event),
                        "is described by rows that disagree (%s), and the table's "
                        "grain is one answer per hook and event"
                        % (", ".join(sorted(cells)),)))
            continue
        if pair not in by_pair:
            out.append(("%s / %s" % (hook, event),
                        "has a row stating `%s`, and nothing registers that hook "
                        "on that event any more - the row describes a state that "
                        "has passed" % (sorted(cells)[0],)))
    for pair in sorted(by_pair):
        hook, event = pair
        modes = by_pair[pair]
        if len(set(mode == loud for mode in modes)) > 1:
            out.append(("%s / %s" % (hook, event),
                        "is registered both loudly and silently on one event (%s), "
                        "which the table's grain cannot express at all"
                        % (", ".join(sorted(modes)),)))
        if loud in modes and event != decision:
            out.append(("%s / %s" % (hook, event),
                        "asks the launcher for a `%s` prompt on an event with no "
                        "permission-decision channel - the payload names `%s`, so "
                        "that JSON is printed and ignored and a guard the table "
                        "calls loud blocks nothing" % (loud, decision)))
        if pair in conflicted:
            continue
        if pair not in described:
            out.append(("%s / %s" % (hook, event),
                        "is wired (%s) and no row of the table describes it, so "
                        "deleting a row would leave the table agreeing with itself"
                        % (", ".join(sorted(modes)),)))
            continue
        documented = sorted(described[pair])[0]
        if (documented == loud) != (loud in modes):
            out.append(("%s / %s" % (hook, event),
                        "is documented as `%s` and registered as %s, so the "
                        "document promises %s where the wiring does the opposite"
                        % (documented, ", ".join(sorted(modes)),
                           "a prompt" if documented == loud else "silence")))
    return sorted(out)


def _failmode_answer(problem, findings=(), rows=(), wired=(), contract=None):
    """One shape for every way this rule can answer, so no arm can omit a key.

    A caller reads `problem` FIRST: an empty finding list is what perfect agreement
    looks like and also what a file nobody could read produces, and spelling those
    two the same way is the defect this rule exists to catch one document up.
    """
    return {"problem": problem, "findings": sorted(findings), "rows": list(rows),
            "wired": list(wired), "contract": contract,
            "described": sorted((hook, event, cell)
                                for _lineno, hook, named, cell in rows
                                for event in named)}


def failmode_table_drift(repo=None):
    """{"problem", "findings", "rows", "described", "wired", "contract"}."""
    root = repo or REPO
    texts = {}
    for rel in (LAUNCHER_REL, HOOKS_JSON_REL, SECURITY_REL):
        try:
            with io.open(os.path.join(root, rel), encoding="utf-8") as fh:
                texts[rel] = fh.read()
        except (IOError, OSError, UnicodeDecodeError) as exc:
            return _failmode_answer("%s could not be read: %s" % (rel, exc))
    contract, problem = launcher_contract(texts[LAUNCHER_REL])
    if problem is not None:
        return _failmode_answer("%s %s" % (LAUNCHER_REL, problem))
    reg = hook_registrations(texts[HOOKS_JSON_REL], contract["default"])
    if reg["problem"] is not None:
        return _failmode_answer("%s %s" % (HOOKS_JSON_REL, reg["problem"]),
                                contract=contract)
    rows, problem = failmode_rows(texts[SECURITY_REL], reg["events"])
    if problem is not None:
        return _failmode_answer("%s %s" % (SECURITY_REL, problem),
                                wired=reg["wired"], contract=contract)
    findings = failmode_findings(rows, reg["wired"], contract)
    findings += [("%s / %s" % (HOOKS_JSON_REL, event),
                  "does not go through `%s`, so its no-interpreter behaviour is "
                  "not the one the fail-mode table describes: %s"
                  % (_LAUNCHER_BASENAME, command))
                 for event, command in reg["unlaunched"]]
    return _failmode_answer(None, findings=findings, rows=rows,
                            wired=reg["wired"], contract=contract)


# --- the slices ci.yml runs, against the slices verify.sh lists ----------------
# ONE EXECUTABLE DESCRIPTION. ci.yml used to carry the gate set as inline shell, and
# this file held hand-maintained copies of it together - the runner, the workflow and
# two documents - by reading each one's commands, the report checker's documents and
# the sweep's legs. Every CI job is now setup plus one `verify.sh --only` call, so the
# workflow names SLICES and the runner alone says what a slice runs. What is left to
# hold is what the workflow says about the slices:
#
#   * every slice a job names is one `verify.sh --list` prints - a misspelt or
#     retired name is otherwise refused by the runner on the day the job runs;
#   * every per-run slice is run by some job outside the release tier, so no gate
#     the runner defines is one an ordinary CI run never reaches;
#   * a sharded slice's matrix runs every part 1..N, on every runner it runs on.
#
# `--list` is ASKED of the real runner rather than parsed out of its text, because
# the list is what a run executes - `run` prints instead of running under it - and
# a second reading of the file would be a second description of it.
VERIFY_LIST_TIMEOUT = 60
_SLICE_LINE = re.compile(r"^  ([a-z0-9][a-z0-9-]*) \((per-run|release)\)$")
_STEP_LINE = re.compile(r"^    (\S.*)$")
_COMMAND_LINE = re.compile(r"^        (\S.*)$")
# The terms a job's `if:` may be made of and still be PROVED to run on every run: the
# two the workflow puts on its jobs (not cancelled, and no earlier run verified the
# commit) and, for the release-tier job, the tier input. They are compared as whole
# terms of an `&&` chain with the spaces removed, so a condition that merely MENTIONS
# one of them (`... || false`, a `github.event_name` test beside it) is not one.
_GUARD_TERMS = frozenset(["!cancelled()", "needs.verified.outputs.run==''"])
_RELEASE_TERM = "inputs.tier=='release'"
_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
_MATRIX_WORD = re.compile(r"\$\{\{matrix\.([A-Za-z0-9_-]+)\}\}")
_VERIFY_CALL = re.compile(r"(?:^|[\s;&|(])(?:\./)?tools/verify\.sh(?=\s|$)(.*)$",
                          re.M)
_CALL_END = re.compile(r"\s(?:;|&&|\|\||\||#|>|<)")


def _output_tail(text, lines=6):
    return "\n".join(text.strip().splitlines()[-lines:])


def parse_verify_list(text):
    """{"order", "tiers", "steps", "commands"} read off `verify.sh --list`, or
    None when the text holds no slice: a list that printed nothing must not read
    as a runner with no slices to hold a workflow to. `steps` are each slice's
    step labels, `commands` the command printed under each label."""
    order, tiers, steps, commands = [], {}, {}, {}
    current = None
    for line in text.splitlines():
        got = _SLICE_LINE.match(line)
        if got:
            current = got.group(1)
            order.append(current)
            tiers[current] = got.group(2)
            steps[current] = []
            commands[current] = []
            continue
        if current is None:
            continue
        step = _STEP_LINE.match(line)
        if step:
            steps[current].append(step.group(1))
            continue
        command = _COMMAND_LINE.match(line)
        if command:
            commands[current].append(command.group(1))
    if not order:
        return None
    return {"order": order, "tiers": tiers, "steps": steps, "commands": commands}


def verify_list(repo=None):
    """(parsed `--list`, problem) for the runner itself; exactly one is None."""
    root = repo or REPO
    path = os.path.join(root, VERIFY_REL)
    if not os.path.isfile(path):
        return None, "%s is not there, so its slices cannot be listed" % (
            VERIFY_REL,)
    shell = shutil.which("sh")
    if shell is None:
        return None, "no `sh` on PATH, so `%s --list` cannot be asked" % (
            VERIFY_REL,)
    try:
        done = subprocess.run([shell, path, "--list"], cwd=root,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=VERIFY_LIST_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "`%s --list` could not be run: %s" % (VERIFY_REL, exc)
    text = done.stdout.decode("utf-8", "replace")
    if done.returncode != 0:
        return None, "`%s --list` exited %d: %s" % (VERIFY_REL, done.returncode,
                                                   _output_tail(text, 3))
    parsed = parse_verify_list(text)
    if parsed is None:
        return None, "`%s --list` printed no slice" % (VERIFY_REL,)
    return parsed, None


def _workflow_jobs(text):
    """[(job id, [the job's lines])] under the top-level `jobs:`, read by
    indentation the way `untimed_jobs` reads it; [] when there is no such block."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"jobs:\s*(#.*)?$", line):
            start = i + 1
            break
    if start is None:
        return []
    jobs = []
    depth = None
    for line in lines[start:]:
        if line.strip() and not line.startswith((" ", "\t", "#")):
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if depth is None:
            depth = indent
        if indent == depth:
            jobs.append((stripped.split(":", 1)[0].strip(), []))
        elif jobs and indent > depth:
            jobs[-1][1].append(line)
    return jobs


def _job_keys(lines):
    """{key: value} for a job's own keys - the first depth under its id."""
    keys = {}
    depth = None
    for line in lines:
        got = _key_line(line)
        if got is None:
            continue
        indent, key, value = got
        if depth is None:
            depth = indent
        if indent == depth:
            keys[key] = value
    return keys


def _matrix_cells(lines):
    """{"cells": [dict], "problem": str or None} for one job's `matrix:`.

    Axes (`key: [a, b]`) are crossed, `exclude` entries remove the cells they
    match, `include` entries are added as cells. A job with no matrix is ONE cell
    with no keys. Only the shapes this repo writes are read; anything else is a
    `problem`, never an empty cell list, because no cells would read as "nothing
    is wrong".
    """
    body = [re.sub(r"\s+#.*$", "", ln.rstrip()) for ln in lines
            if ln.strip() and not ln.strip().startswith("#")]
    heads = [i for i, ln in enumerate(body) if ln.strip() == "matrix:"]
    if not heads:
        return {"cells": [{}], "problem": None}
    if len(heads) != 1:
        return {"cells": [], "problem": "the job has %d `matrix:` blocks, so "
                "which cells run cannot be read" % len(heads)}
    base = len(body[heads[0]]) - len(body[heads[0]].lstrip())
    block = []
    for ln in body[heads[0] + 1:]:
        if len(ln) - len(ln.lstrip()) <= base:
            break
        block.append(ln)
    if not block:
        return {"cells": [], "problem": "the `matrix:` block is empty"}
    top = len(block[0]) - len(block[0].lstrip())
    axes, groups, current = {}, {"include": [], "exclude": []}, None
    for ln in block:
        indent = len(ln) - len(ln.lstrip())
        text = ln.strip()
        if indent == top:
            key, _sep, rest = text.partition(":")
            rest = rest.strip()
            current = None
            if key in groups and not rest:
                current = key
            elif rest.startswith("[") and rest.endswith("]"):
                axes[key] = [v.strip().strip("'\"") for v in rest[1:-1].split(",")
                             if v.strip()]
            else:
                return {"cells": [], "problem": "matrix key `%s` is in a form "
                        "this reader cannot resolve" % key}
        elif current is not None:
            if text.startswith("- "):
                groups[current].append({})
                text = text[2:]
            key, _sep, val = text.partition(":")
            if not groups[current]:
                return {"cells": [], "problem": "an `%s` entry is not a list item"
                        % current}
            groups[current][-1][key.strip()] = val.strip().strip("'\"")
    cells = [{}]
    for name in sorted(axes):
        cells = [dict(c, **{name: v}) for c in cells for v in axes[name]]
    cells = [c for c in cells
             if not any(all(c.get(k) == v for k, v in ex.items())
                        for ex in groups["exclude"])]
    # `include` AS GITHUB READS IT: an entry is added to every combination it can join
    # without overwriting a value the matrix lists (a value an earlier entry added may
    # be overwritten), and becomes a combination of its own only when it joins none.
    extra = []
    for entry in groups["include"]:
        joined = [c for c in cells
                  if all(c.get(k) == v for k, v in entry.items() if k in axes)]
        for cell in joined:
            cell.update(entry)
        if not joined:
            extra.append(dict(entry))
    return {"cells": cells + extra, "problem": None}


def _job_runs(lines):
    """Every `run:` a job's steps carry, one string each: a `|` block's lines
    joined as the shell reads them, a `>` block's folded with spaces."""
    out = []
    i = 0
    while i < len(lines):
        got = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", lines[i])
        if not got:
            i += 1
            continue
        indent = len(got.group(1))
        rest = got.group(2).strip()
        i += 1
        if rest and rest[0] not in "|>":
            out.append(rest)
            continue
        body = []
        while i < len(lines) and (not lines[i].strip()
                                  or len(lines[i]) - len(lines[i].lstrip())
                                  > indent):
            body.append(lines[i].strip())
            i += 1
        out.append(("\n" if rest.startswith("|") else " ")
                   .join(b for b in body if b))
    return out


def _collapse(text):
    """`${{ x }}` spelled without its spaces, so one expression is one word."""
    return _EXPR.sub(lambda m: "${{%s}}" % (m.group(1).replace(" ", ""),), text)


def _verify_args(run):
    """[[word, ...]] for each `tools/verify.sh` call in one `run:` value."""
    calls = []
    for match in _VERIFY_CALL.finditer(_collapse(run)):
        rest = match.group(1)
        cut = _CALL_END.search(rest)
        calls.append((rest[:cut.start()] if cut else rest).split())
    return calls


def _flag(words, name):
    """The value `words` gives `name` (`--x V` or `--x=V`), or None."""
    for i, word in enumerate(words):
        if word == name and i + 1 < len(words):
            return words[i + 1]
        if word.startswith(name + "="):
            return word.split("=", 1)[1]
    return None


def _resolve(word, cell):
    """`word` with each `${{matrix.K}}` replaced by the cell's value; a key the
    cell lacks is left in place, so the caller can see it was not resolved."""
    return _MATRIX_WORD.sub(lambda m: cell.get(m.group(1), m.group(0)), word)


def _if_tier(condition):
    """`(tier, why)` for a job's `if:` value - exactly one is None.

    No condition, or one made only of the guard terms, is `per-run`; with the
    release-tier term it is `release`. Any other term is a `why`, because a job
    that may be skipped on an ordinary run (`false`, a push-only test) runs its
    slices on no run the caller can name.
    """
    expr = condition.strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2]
    terms = [t for t in "".join(expr.split()).split("&&") if t]
    other = [t for t in terms if t not in _GUARD_TERMS and t != _RELEASE_TERM]
    if other:
        return None, ("its condition %r cannot be proved to run on every run "
                      "(unproved: %s), so its slices are not counted as run "
                      "by an ordinary CI run" % (condition.strip(),
                                                  ", ".join(other)))
    return ("release" if _RELEASE_TERM in terms else "per-run"), None


def job_slices(text):
    """{"jobs": [...], "problems": [...], "problem": str or None} for a workflow.

    One entry per job: its id, its tier (`release` when its `if:` carries
    `inputs.tier == 'release'`, `per-run` when it carries only the guard terms or
    nothing, and `unproved` when a job that calls verify.sh has any other
    condition - which is also a `problems` row), and one run per verify.sh call
    per matrix cell - the slices it names (None for a call with no `--only`,
    which runs every per-run slice), its `--shard` and the matrix keys that
    produced it. A value a cell cannot resolve is a `problems` row naming the
    job, never a silently dropped run.
    """
    jobs = _workflow_jobs(text)
    if not jobs:
        return {"jobs": [], "problems": [],
                "problem": "no top-level `jobs:` block, so no job could be read"}
    out, problems = [], []
    for job, lines in jobs:
        calls = [args for run in _job_runs(lines) for args in _verify_args(run)]
        tier, why = _if_tier(_job_keys(lines).get("if", ""))
        entry = {"job": job, "tier": tier or "unproved", "runs": []}
        out.append(entry)
        if not calls:
            continue            # a guard job carries no slice, so no condition to prove
        if why is not None:
            problems.append((job, why))
        matrix = _matrix_cells(lines)
        if matrix["problem"] is not None:
            problems.append((job, matrix["problem"]))
            continue
        for words in calls:
            only, shard = _flag(words, "--only"), _flag(words, "--shard")
            for cell in matrix["cells"]:
                values = [_resolve(w, cell) for w in (only, shard) if w is not None]
                if any("${{" in v for v in values):
                    problems.append((job, "a verify.sh argument the matrix cell "
                                     "%r cannot resolve: %r" % (cell, values)))
                    continue
                entry["runs"].append({
                    "cell": cell,
                    "slices": (None if only is None
                               else [s for s in _resolve(only, cell).split(",")
                                     if s]),
                    "shard": None if shard is None else _resolve(shard, cell),
                    "shard_keys": (set(_MATRIX_WORD.findall(shard))
                                   if shard is not None else set())})
    return {"jobs": out, "problems": problems, "problem": None}


def slice_drift(text, listed):
    """[(slice, why)] for a slice the workflow and the runner disagree about.

    `listed` is `{slice: tier}` as `verify.sh --list` prints it, or None when
    the list could not be read - which is one finding rather than a check of
    the workflow against nothing.
    """
    if listed is None:
        return [("verify.sh --list", "could not be read, so which slices exist "
                 "is unknown and no job can be held to them")]
    got = job_slices(text)
    if got["problem"] is not None:
        return [("ci.yml", got["problem"])]
    per_run = sorted(name for name, tier in listed.items() if tier == "per-run")
    named = {}
    for job in got["jobs"]:
        for run in job["runs"]:
            for name in (per_run if run["slices"] is None else run["slices"]):
                named.setdefault(name, set()).add((job["job"], job["tier"]))
    findings = []
    for name in sorted(named):
        if name not in listed:
            findings.append((name, "job(s) %s run it and `verify.sh --list` does "
                             "not print it, so the runner refuses it the day the "
                             "job runs" % (", ".join(sorted(j for j, _t
                                                            in named[name])),)))
    for name in per_run:
        tiers = set(t for _j, t in named.get(name, ()))
        if "per-run" in tiers:
            continue
        findings.append((name, "a per-run slice no job outside the release tier "
                         "runs, so an ordinary CI run never runs it%s"
                         % "".join(
                             ["; only the release tier does"
                              if "release" in tiers else "",
                              "; a job whose condition cannot be proved runs it "
                              "(see that job's own finding)"
                              if "unproved" in tiers else ""])))
    return findings + [("%s (job)" % (job,), why) for job, why in got["problems"]]


def shard_matrix_drift(text):
    """[(subject, why)] for a sharded slice whose parts are not all run.

    A sweep slice may be split into `--shard I/N` cells only because the cells
    together still run every file - which holds only if, for each slice on each
    runner, the cells cover exactly 1..N. Cells are grouped by everything but
    the keys the shard is read from, so an `exclude` that drops one part on one
    runner is found even though every list still carries every value.
    """
    got = job_slices(text)
    if got["problem"] is not None:
        return [("ci.yml", got["problem"])]
    findings = []
    for job in got["jobs"]:
        groups = {}
        for run in job["runs"]:
            if run["shard"] is None:
                continue
            rest = tuple(sorted((k, v) for k, v in run["cell"].items()
                                if k not in run["shard_keys"]))
            subject = "%s (%s)" % (job["job"], ", ".join(
                ["%s=%s" % kv for kv in rest]
                + ["--only %s" % (",".join(run["slices"] or ["<per-run>"]),)]))
            spec = re.match(r"^([0-9]+)/([0-9]+)$", run["shard"])
            if spec is None:
                findings.append((subject, "a `--shard` of %r, a form this reader "
                                 "cannot resolve, so whether every part runs is "
                                 "unknown" % (run["shard"],)))
                continue
            groups.setdefault(subject, set()).add((int(spec.group(1)),
                                                   int(spec.group(2))))
        for subject, parts in sorted(groups.items()):
            totals = sorted(set(n for _i, n in parts))
            if len(totals) != 1:
                findings.append((subject, "its cells split it into different "
                                 "totals %r, so no one part list covers it"
                                 % (totals,)))
                continue
            total = totals[0]
            have = set(i for i, _n in parts)
            want = set(range(1, total + 1))
            if have - want:
                findings.append((subject, "asks for part(s) %s of %d, which do "
                                 "not exist" % (sorted(have - want), total)))
            if want - have:
                findings.append((subject, "runs parts %s of %d, so part(s) %s "
                                 "never run" % (sorted(have), total,
                                                sorted(want - have))))
    return findings


# THE MANIFEST-VALIDATION WORK, each piece found by a word its command or label
# carries in `verify.sh --list` rather than by a slice's name, so moving a piece
# into a slice of its own changes what is read and not whether it is read. A
# piece the runner's list no longer carries maps to no slice, which the case
# reading this reports rather than passing over.
MANIFEST_WORK = (("validator", "validate-manifest.py"),
                 ("sharded layout", "sharded_layout_intact"),
                 ("doctor", "audit-doctor.py"),
                 ("report smoke", "status_gate_and_render"),
                 ("rendered artifacts", "check-rendered-artifacts.py"))


def manifest_work_slices(listed):
    """[(piece, [slice, ...])] in MANIFEST_WORK's order - the slices of a parsed
    `verify.sh --list` whose printed commands run each piece; [] for a piece
    no slice runs."""
    return [(piece, [name for name in listed["order"]
                     if any(word in c for c in listed["commands"][name])])
            for piece, word in MANIFEST_WORK]


def per_run_named(text, listed_tiers):
    """{slice: [job, ...]} for every slice a per-run job of the workflow runs -
    a call with no `--only` runs every per-run slice `listed_tiers` holds - or
    None when the workflow's jobs could not be read."""
    got = job_slices(text)
    if got["problem"] is not None:
        return None
    every = sorted(n for n, t in listed_tiers.items() if t == "per-run")
    named = {}
    for job in got["jobs"]:
        if job["tier"] != "per-run":
            continue
        for run in job["runs"]:
            for name in (every if run["slices"] is None else run["slices"]):
                named.setdefault(name, set()).add(job["job"])
    return dict((n, sorted(j)) for n, j in named.items())


def family_shard_parts(text, family):
    """{slice: sorted [(part, total)]} for the sharded runs of the matrix cells
    whose `os` starts with `family`, or None when the workflow's jobs could not
    be read. A cell with no `os` belongs to no family."""
    got = job_slices(text)
    if got["problem"] is not None:
        return None
    parts = {}
    for job in got["jobs"]:
        for run in job["runs"]:
            if run["shard"] is None or not str(run["cell"].get("os", "")
                                               ).startswith(family):
                continue
            spec = re.match(r"^([0-9]+)/([0-9]+)$", run["shard"])
            key = (int(spec.group(1)), int(spec.group(2))) if spec else run["shard"]
            for name in (run["slices"] or ["<per-run>"]):
                parts.setdefault(name, set()).add(key)
    return dict((n, sorted(p, key=str)) for n, p in parts.items())


def render_slices(listed, text, stream=None):
    """`--list`: each slice the runner lists, its tier, and the jobs that run it.
    Returns the number of slices printed."""
    out = stream if stream is not None else sys.stdout
    got = job_slices(text)
    runs = {}
    for job in got["jobs"]:
        for run in job["runs"]:
            for name in (run["slices"] or []):
                runs.setdefault(name, set()).add(job["job"])
    for name in listed["order"]:
        out.write("  %-18s %-8s %s\n" % (name, listed["tiers"][name],
                                         ", ".join(sorted(runs.get(name, ())))
                                         or "(no job)"))
    return len(listed["order"])


# --- who audits an exemption's REASON ------------------------------------------
# Asked for the tree rather than for one table: every exemption carrying a reason
# must name the instrument that reads it, or say why it can have none.
#
# THE DERIVATION IS BY SHAPE, and the shape cannot tell an exemption from a help
# table - `FIELD_HELP`, `PRESETS` and `VERDICT_HELP` are all `{subject: sentence}`
# and excuse nothing. That is the same first-filter problem `prove-gates` has with
# lint names, and this is its answer: derive everything the shape reaches, and let
# a table declare itself out in a row that is itself checked. A classification made
# once by hand and then enforced is worth more than a cleverer rule that is wrong
# about the next table somebody adds.
_EXEMPTION_ROOTS = ("plugins/audit/scripts", "plugins/audit/hooks", "tools")

# WHO AUDITS EACH TABLE, and the value NAMES A FUNCTION this tree defines - checked,
# so a row cannot outlive the instrument it points at. That check is what stops this
# becoming the thing `NOT_A_GATE`'s own rule forbids: a row that silences something
# and can never be wrong.
#
# TWO STRENGTHS, SPELLED APART, because collapsing them would make this table assert
# more than it can show:
#
#   `reason` — the SENTENCE is compared against the world, and each such instrument
#     cost a defect to build: `prohibition_drift`, for one, asks the document
#     whether the rule an excuse stands against is still stated.
#   `live`  — the SUBJECT is checked to still be there, so a row that excuses nothing
#     is reported. Weaker, and it is the half both earlier fixes ultimately needed:
#     a row survives its subject long before its sentence stops being true.
#
# A table with neither is a finding, which is the whole point of deriving them.
AUDITED_EXEMPTIONS = {
    # `schema_coverage()` reports an exemption naming a field the schema dropped; it
    # does not read the sentence, so this is the weaker of the two strengths.
    "SCHEMA_EXEMPTIONS": ("live", "schema_coverage"),
    "NOT_A_GATE": ("live", "coverage"),
    "PLUGIN_OWNED_IN_CLAUDE": ("live", "tests/test_commit_task_work.py ctw-at9"),
    "ALLOW_EXEMPT": ("live", "prove"),
    "PROSE_SCAN_EXEMPT": ("live", "prose_number_claims"),
    "CITATION_SCAN_EXEMPT": ("live", "register_citation_violations"),
    "PLAIN_READ_EXEMPT": ("live", "plain_read_violations"),
    # The prohibitions this repo states and does NOT enforce. `check-prohibitions`
    # reads each row's reason for length and asks the document whether the rule it
    # excuses is still stated - so the table cannot go stale quietly, and a rule
    # that gains a hook has to leave it.
    "ADVISORY": ("reason", "prohibition_drift"),
    # The sections of `orchestrator.md` that carry no anchor, each with why. The
    # document was once measured at one anchored sentence in fourteen sections, so
    # what this table has to stop is the honest subset quietly becoming the whole file
    # again: a section that GAINS an anchor must leave here, and a reason a reader
    # cannot disagree with is not a reason.
    "UNANCHORED_SECTIONS": ("reason", "claim_drift"),
    "CONTRAST_EXEMPTIONS": ("live", "contrast_exemption_problems"),
    "BASELINE": ("live", "dead_baseline"),
    "KNOWN_CONFIG_MIRRORS": ("reason", "config_read_violations"),
    "TOOL_FIXTURE_BASENAMES": ("live", "tool_basename_drift"),
    # The hook scopes that read the project's plan on purpose. The lint that
    # reads the table reports a row naming no finding as stale, and a row with
    # no reason excuses nothing.
    "HOOK_TREE_EXEMPT": ("live", "hook_tree_violations"),
    # The sites allowed to replace a state file themselves. The lint that reads
    # the table reports a row whose function no longer replaces anything, and a
    # row whose reason is short enough to be a label; it does not judge whether
    # the sentence is true, so this is the weaker of the two strengths.
    "STATE_WRITERS": ("live", "state_write_violations"),
    # The sites allowed to write JSON without the machine-path scrub. The lint
    # reports a reach of the raw writer from a site no row names, and a row whose
    # site no longer reaches it; whether its reason is true it does not judge.
    "RAW_JSON_WRITERS": ("live", "raw_json_writer_violations"),
    # `git_path_base_violations` reports a git listing site that neither routes
    # through the path pair nor has a row here, a row whose function no longer makes
    # a listing call, and a row with a blank reason; whether a reason is true it does
    # not judge.
    "GIT_PATH_BASE_EXEMPT": ("live", "git_path_base_violations"),
    # ...and the two whose instrument is a CASE rather than a function. This tree's
    # suites lint other files' source, so an auditor living in one is not a lesser
    # auditor - `r2` is the strongest row in this table, refusing a NEW debt and a
    # RETIRED one alike so the list may only shrink and only deliberately.
    "KNOWN_LAYER_DEBT": ("reason", "tests/test__deps.py r2"),
    # What the sweep leaves out of the checkout's own `.claude/` it watches. `cw5`
    # builds a `.claude/` holding every kind of entry and asks which survive the
    # snapshot, naming the left-out ones, so a row whose subject stopped being
    # left out is reported; whether its sentence is still true of a live session
    # it does not judge, so this is the weaker of the two strengths.
    "CLAUDE_UNWATCHED": ("live", "tools/sweep-selftests.py cw5"),
    # ...and what it leaves out of `state/` by name. `cw10` drives every row with
    # the example it carries - skipped - and the same name with a character put
    # in at its head or on its tail - not skipped - so a dead row, and a row
    # loosened at its anchor or its ending, are both reported; a row loosened
    # only in its middle is not. `cw10b` formats each writer's constant and asks
    # the table to skip it, but whether a row's sentence is true of a live
    # session neither judges, so this is the weaker strength too.
    "CLAUDE_LIVE_WRITES": ("live", "tools/sweep-selftests.py cw10"),
    "EXCLUDED": ("live", "tests/test__refs.py t2"),
}

# ...and the tables the shape reaches that excuse nothing. `{subject: sentence}` is
# how this tree writes help text, remedies and message fragments too, and no rule
# that reads only the shape can tell those from an excuse - which is why the
# classification is made once by hand and then enforced, rather than guessed at
# every run. Each row says WHY, because a row that silences nothing can never be
# wrong and would sit here for ever.
NOT_AN_EXEMPTION = {
    "COMPOSITION_HELP": "panel help text: what each composition lever means, shown "
                        "in the drawer beside the control it describes",
    "FIELD_HELP": "panel help text for the config fields, same drawer",
    "FIELD_LIMIT": "what each identity field of a tree stamp can and cannot "
                   "establish, printed beside the field on the way in and on the "
                   "way out - the opposite of an exemption: every row NARROWS "
                   "what the stamp is allowed to claim rather than excusing "
                   "anything from a rule",
    "PRESETS": "theme presets - a named palette per preset, not an excuse",
    "VERDICT_HELP": "what each invariant verdict means, printed beside it",
    "_SH_SELF_DIR_SHAPES": "a RULE table, and the opposite of an exemption: each "
                           "row is a way a shell script may NOT read its own "
                           "directory, with the sentence the lint prints to "
                           "say why - a row adds a refusal rather than "
                           "excusing anything",
    "_EVAL_SHAPE":"the two spellings of an inline eval, used to name the form the "
                   "operator actually typed in a refusal",
    "_UNENCODED": "a RULE table, and the opposite of an exemption: each row is a "
                  "shape of text I/O that may NOT leave its encoding unnamed, "
                  "with the sentence `text_encoding_violations` prints to say "
                  "what to pass instead - a row adds a refusal rather than "
                  "excusing a site",
    "_FILE_REFUSALS": "a RULE table, and the opposite of an exemption: each row is "
                      "a prefix a `--files` entry may NOT open with, and the "
                      "sentence beside it is the clause the refusal prints to say "
                      "why that string is not a repository-relative path - so a row "
                      "adds a string the verb rejects rather than excusing one from "
                      "a check",
    "_TEV_WHY": "the report's explanation of a testEvidence state, rendered to a "
                "reader rather than excusing anything",
    "_TEV_GAP_WHY": "the same, for the states where a pointer resolves to nothing - "
                    "read by a person looking at a report, excusing no rule",
    "SYNTHETIC": "the wordings a synthetic PII verdict is printed with, so an empty "
                 "run cannot read as a clean one",
    "FINDINGS": "what each release-publication finding means, printed with it",
    "REFUSALS": "what each question a release check could not put means, printed "
                "with it so a refusal cannot read as a clean run",
    "_ALWAYS": "a RULE table, and the opposite of an exemption: every row is a "
               "history rewrite this hook always refuses, with the why it prints",
    "LIST_ANCHORS": "a RULE table too, and the opposite of an exemption twice over: "
                    "each row DERIVES a vocabulary from the enum that owns it and "
                    "requires a section of `orchestrator.md` to name every member, "
                    "in both directions - so a row adds a thing the document must "
                    "do rather than excusing it from one, and the reason on each "
                    "row says which enum is the authority",
    "PROJECT_BASES": "a RULE table, and the opposite of an exemption twice over: "
                     "the rows ARE the order a manifest writer resolves its "
                     "project root in, and each sentence is the clause the "
                     "command PRINTS to say which row won - so a row obliges a "
                     "verb to explain itself rather than excusing it from a "
                     "check, and a row nothing can resolve to is a red case "
                     "rather than a quiet excuse",
    "_EMPTY_RECORDS": "the append-only records the gates leave behind, each with "
                      "the sentence the doctor prints when one holds nothing - the "
                      "opposite of an exemption: a row makes the command say WHICH "
                      "of two facts an empty file is, where the row's absence "
                      "would leave the silence reading as good news",
    "_PANEL_FILES": "the panel's own local files, with the remedy the doctor prints "
                    "when one is tracked - subjects of a check, not excuses from it",
    "CLAUDE_IGNORE_LINES": "every line the plugin writes into `.claude/.gitignore`, "
                           "each with the writer that owns it and the comment that "
                           "explains it in the file - the rows the ignore file's "
                           "commit check recognises, not an excuse from any rule",
    "OWED_REASON": "what the tests.add migration prints about an entry it will "
                   "NOT rewrite, one sentence per reason it refused - the "
                   "opposite of an exemption: a row is why a repair was declined "
                   "and what the human has to decide, so a verdict with no row "
                   "would say less rather than escape a rule",
    "_JOURNAL_WARNING_CLASSES": "the repair text the doctor prints for each class "
                                "of journal warning, and the opposite of an "
                                "exemption: a class with no row gets a POINTER and "
                                "no cause rather than borrowing another class's "
                                "sentence, which is a defect this repairs - so a "
                                "row makes the check say more, never less",
    "CLASS_MEANING": "what each content class of a recorded session's cost means, "
                     "printed beside the class's figures - a legend for a reader, "
                     "excusing nothing from any rule",
}

# The reason has to be a SENTENCE. A one-word value is a label - `{"P1": "done"}` -
# and a table of labels is data rather than a set of excuses somebody has to stand
# behind. Measured against the real tables: the shortest live reason is well over
# this, and the shortest help-table value is too, so this separates data from prose
# and NOT exemptions from help.
_REASON_MIN = 30


def _module_sentences(tree):
    """`{name: text}` for every module-level `NAME = "a long enough sentence"`.

    A REASON MAY BE SHARED, and until `guard-history-rewrite.py`'s rework nothing
    here could see one that was. It names its refusal sentences once and
    reads each from TWO places - the regex fallback table and the tokenized arm -
    so duplicating the text would be the defect this repository names most often.
    The cost was silent: `_reason_table_names` matched only literal values, so the
    day those sentences moved into constants `_ALWAYS` stopped being a reason table
    and dropped out of the exemption audit with nothing to say so. A blind spot that
    swallows a table is worse than a table that fails loudly, which is why this
    resolves the name rather than asking the hook to repeat itself.
    """
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found[target.id] = value.value
    return found


def _sentence_text(node, shared):
    """The string a table's sentence slot holds, or None when it is not one.

    A literal, or a module constant resolved through `shared`. None rather than ""
    on purpose: an empty string and "this slot is not a sentence" are different
    answers, and a caller comparing against `_REASON_MIN` would fold them together.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return shared.get(node.id)
    return None


def _reason_table_names(source):
    """Every module constant in `source` shaped `{subject: sentence}`.

    Both spellings the tree uses: a dict, and a tuple/list of pairs whose LAST
    element is the sentence. Read from the AST, so a name assembled at runtime or
    mentioned in a comment is not one. A sentence may also be a module constant
    rather than a literal - see `_module_sentences` for why that had to be read.
    """
    out = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    shared = _module_sentences(tree)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        name = target.id
        if not (name.isupper() or name.lstrip("_").isupper()):
            continue
        value = node.value
        sentences = []
        if isinstance(value, ast.Dict) and value.values:
            sentences = list(value.values)
        elif isinstance(value, (ast.Tuple, ast.List)) and value.elts \
                and all(isinstance(e, (ast.Tuple, ast.List)) and e.elts
                        for e in value.elts):
            sentences = [e.elts[-1] for e in value.elts]
        if not sentences:
            continue
        texts = [_sentence_text(s, shared) for s in sentences]
        if all(t is not None and len(t) >= _REASON_MIN for t in texts):
            out.append(name)
    return out


def exemption_tables(repo=None):
    """`{name: path}` — every reason-carrying table this tree declares."""
    root = repo or REPO
    found = {}
    for sub in _EXEMPTION_ROOTS:
        base = os.path.join(root, sub.replace("/", os.sep))
        for dirpath, _dirs, files in os.walk(base):
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fname)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        text = fh.read()
                except (OSError, UnicodeDecodeError):
                    continue
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                for name in _reason_table_names(text):
                    found.setdefault(name, rel)
    return found


def _instrument_missing(repo, who):
    """"" when the named auditor is really there, else why it is not.

    Two spellings, both falsifiable by renaming the thing they name: a bare word is
    a function and must be defined somewhere under the walked roots; `<path> <case>`
    is a suite case and the file must exist and carry that case id.
    """
    root = repo or REPO
    who = who.strip()
    if not who:
        return ("names no instrument, so the row asserts an audit nobody performs")
    if " " in who:
        rel, case = who.rsplit(" ", 1)
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            return ("names a case in %s and that file cannot be read, so the audit "
                    "it claims cannot be happening" % (rel,))
        if ('"%s ' % (case,)) not in text and ("'%s " % (case,)) not in text:
            return ("names case %r in %s and no case by that id is there any more"
                    % (case, rel))
        return ""
    needle = "def %s(" % (who,)
    for sub in _EXEMPTION_ROOTS + ("tests",):
        base = os.path.join(root, sub.replace("/", os.sep))
        for dirpath, _dirs, files in os.walk(base):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                try:
                    with open(os.path.join(dirpath, fname), "r",
                              encoding="utf-8") as fh:
                        if needle in fh.read():
                            return ""
                except (OSError, UnicodeDecodeError):
                    continue
    return ("names %r as its auditor and nothing under the walked roots defines a "
            "function by that name - the row outlived its instrument" % (who,))


def exemption_audit_drift(repo=None, audited=None, not_exemptions=None):
    """[(name, problem)] — a reason-carrying table nobody audits, or a dead row.

    THE SAME PROBLEM, ASKED OF EVERY TABLE. Two defects were recorded before this
    existed and both had the same shape: a row whose SENTENCE had stopped being true
    while the row stayed
    green — `gen-demo-usage.py` behind "same throwaway demo tree" while CI diffed a
    committed ledger, and `meta.branch` behind "REVISIT when the panel grows a card"
    for releases after the panel grew one. Each was fixed with its own instrument.
    What was missing is the rule that every such table HAS one.

    BOTH DIRECTIONS, for `NOT_A_GATE`'s reason: a table added later must not opt out
    by being forgotten, and a row must not outlive the table it classifies. A row
    that silences nothing can never be wrong, which is the shape this refuses.
    """
    audited = AUDITED_EXEMPTIONS if audited is None else audited
    not_exemptions = (NOT_AN_EXEMPTION if not_exemptions is None
                      else not_exemptions)
    found = exemption_tables(repo)
    # THE CLASSIFICATION IS NOT ITSELF CLASSIFIED, and saying so is cheaper than the
    # regress. Both tables below are `{subject: sentence}` and the derivation reaches
    # them, so without this the rule would demand a row about itself - and the row
    # about the row after that. They are audited by THIS function, which checks every
    # subject is still derived and every reason is a sentence; a classification whose
    # own rows rot is what `exemption_audit_drift` reports on its next run.
    for own in ("AUDITED_EXEMPTIONS", "NOT_AN_EXEMPTION"):
        found.pop(own, None)
    out = []
    for name in sorted(found):
        if name in audited and name in not_exemptions:
            out.append((name, "is classified twice - it cannot both carry excuses "
                              "somebody audits and excuse nothing"))
        elif name not in audited and name not in not_exemptions:
            out.append((name, "carries a reason per entry and nothing says who "
                              "reads it: add it to AUDITED_EXEMPTIONS naming the "
                              "instrument, or to NOT_AN_EXEMPTION saying why it "
                              "excuses nothing (found in %s)" % (found[name],)))
    for name in sorted(set(audited) | set(not_exemptions)):
        if name not in found:
            out.append((name, "is classified here and no reason-carrying table by "
                              "that name exists any more - the row outlived its "
                              "subject"))
    # ...and the instrument each row names must EXIST. Without this the table would
    # be the shape `NOT_A_GATE` forbids: a row that silences a finding and can never
    # itself be wrong. Two spellings, because an auditor here legitimately lives in
    # either place - a function, or a case in a suite that lints another file's
    # source, which is how half this tree's rules are written.
    for name, row in sorted(audited.items()):
        if name not in found:
            continue
        strength, who = (row if isinstance(row, tuple) else ("live", row))
        if strength not in ("reason", "live"):
            out.append((name, "claims an unknown strength %r - a row says whether "
                              "the SENTENCE is audited or only the subject's "
                              "liveness, and those are different promises"
                        % (strength,)))
        gone = _instrument_missing(repo, str(who))
        if gone:
            out.append((name, gone))
    for name, why in sorted(not_exemptions.items()):
        if name in found and len(str(why).strip()) < _REASON_MIN:
            out.append((name, "is excused from the rule with a label rather than a "
                              "reason a reader can disagree with"))
    return out


def failmode_table_verdict(repo=None):
    """`failmode_table_drift()` as a finding list, with an unreadable tree AS a finding.

    `parity()` renders one verdict, and a rule whose "could not ask" arm arrived
    there as an empty list would be the exact shape the rest of this file exists to
    refuse. So the problem is raised to a finding HERE rather than inside the rule,
    where a case still needs the two told apart.
    """
    got = failmode_table_drift(repo)
    if got["problem"] is not None:
        return [("fail-mode wiring", got["problem"])]
    return got["findings"]


# --- every CI job carries a time bound -------------------------------------------
# A job with no `timeout-minutes` gets GitHub's default of six hours, and a gate
# that hangs spends all of it: the run ends "cancelled", naming no step, and the
# head it was testing waits that long for any verdict at all. A bound is a key on
# the job, so whether one is there is a fact this file can read off the workflow
# rather than a habit a reviewer has to remember. Only the JOB-level key counts: a
# step-level `timeout-minutes` bounds that one step and leaves the rest of the job
# at the default.
_JOB_TIMEOUT_KEY = "timeout-minutes"


def _key_line(line):
    """(indent, key, value) for a `key: value` line, or None for anything else -
    a blank, a comment, a list item, or a line inside a block scalar that does not
    read as a key."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("-"):
        return None
    match = re.match(r"(\s*)([A-Za-z0-9_-]+):(?:\s+(.*?))?\s*$", line)
    if not match:
        return None
    value = (match.group(3) or "").split(" #")[0].strip()
    return len(match.group(1)), match.group(2), value


def untimed_jobs(text):
    """{"findings": [(job, why)], "jobs": n, "problem": str|None} for a workflow.

    A finding is a job under the top-level `jobs:` whose own keys carry no
    `timeout-minutes`, or carry one that is not a positive whole number of
    minutes (an expression is reported too: what it resolves to is not
    readable here). `jobs` counts the jobs read, so an empty finding list over
    zero jobs cannot pass for a clean workflow; a text with no `jobs:` block at
    all is a `problem`, not an empty verdict.

    Indentation is read, not assumed: the first job sets the depth of a job id,
    and each job's first key sets the depth of that job's own keys, so a key
    nested deeper - a step's `timeout-minutes` among them - is never taken for
    the job's.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"jobs:\s*(#.*)?$", line):
            start = i + 1
            break
    if start is None:
        return {"findings": [], "jobs": 0, "bounds": {}, "names": [],
                "problem": "no top-level `jobs:` block, so no job could be read"}
    jobs = []          # [(job id, {key: value} at that job's own depth)]
    job_depth = None
    key_depth = None
    for line in lines[start:]:
        if line.strip() and not line.startswith((" ", "\t", "#")):
            break                                   # the next top-level key
        got = _key_line(line)
        if got is None:
            continue
        indent, key, value = got
        if job_depth is None:
            job_depth = indent
        if indent == job_depth:
            jobs.append((key, {}))
            key_depth = None
            continue
        if not jobs or indent < job_depth:
            continue
        if key_depth is None:
            key_depth = indent
        if indent == key_depth:
            jobs[-1][1][key] = value
    findings = []
    bounds = {}
    for job, keys in jobs:
        if _JOB_TIMEOUT_KEY not in keys:
            findings.append((job, "no job-level %s, so a hang runs to GitHub's "
                                  "six-hour default" % _JOB_TIMEOUT_KEY))
            continue
        value = keys[_JOB_TIMEOUT_KEY]
        if not re.match(r"[0-9]+$", value) or int(value) <= 0:
            findings.append((job, "%s is %r, not a positive whole number of "
                                  "minutes this check can read"
                                  % (_JOB_TIMEOUT_KEY, value)))
            continue
        bounds[job] = int(value)
    if not jobs:
        return {"findings": [], "jobs": 0, "bounds": {}, "names": [],
                "problem": "the `jobs:` block names no job"}
    return {"findings": findings, "jobs": len(jobs), "bounds": bounds,
            "names": [job for job, _keys in jobs], "problem": None}


# --- ...and every bound is two to three times the longest run it was measured against
# A bound set by feel is either too tight - a slow runner fails a green job - or
# so loose it is the six hours again under another number. So the workflow
# carries, as comment lines, the longest finished run of each job over the runs
# its comment names, and each bound must be at least twice that and at most
# three times it. A job whose three times is under `BOUND_FLOOR_MINUTES` may
# sit at that floor: a sub-minute measurement samples none of the runner
# provisioning and package-install variance a bound still has to cover. The figures are
# written by whoever measured them (`gh run view` prints them; nothing here can
# ask GitHub, and a selftest that did would fail offline); what this holds is
# that the bound and the measurement written beside it agree, which is the claim
# the comment makes and the one that was once false by half.
_LONGEST_LINE = re.compile(
    r"^\s*#\s+longest\s+([A-Za-z0-9_-]+):\s+([0-9]+)m([0-9]{2})s\b", re.M)
BOUND_FACTOR = 2
BOUND_CEILING_FACTOR = 3
BOUND_FLOOR_MINUTES = 5


def job_bound_evidence(text):
    """[(job, why)] for every job whose bound is not backed by a `longest` line.

    A job with a readable bound needs exactly one `# longest <job>: <m>m<ss>s`
    line, and `timeout-minutes` must be at least BOUND_FACTOR times it and at
    most BOUND_CEILING_FACTOR times it, or `BOUND_FLOOR_MINUTES` when that is
    more. A line
    naming a job the workflow does not have is reported too: it is a
    measurement of nothing, and it would let a renamed job keep a figure that
    no longer describes it. Jobs with no readable bound are `untimed_jobs`'
    findings and are not repeated here.
    """
    got = untimed_jobs(text)
    if got["problem"] is not None:
        return []
    longest = {}
    findings = []
    for match in _LONGEST_LINE.finditer(text):
        job = match.group(1)
        secs = int(match.group(2)) * 60 + int(match.group(3))
        if job in longest:
            findings.append((job, "two `longest` lines, so which measurement the "
                                  "bound answers to cannot be read"))
        longest[job] = secs
    for job in sorted(set(longest) - set(got["names"])):
        findings.append((job, "a `longest` line names a job this workflow "
                              "does not have"))
    for job, minutes in sorted(got["bounds"].items()):
        if job not in longest:
            findings.append((job, "%s is %d with no `# longest %s: <m>m<ss>s` "
                                  "line, so nothing says what it was measured "
                                  "against" % (_JOB_TIMEOUT_KEY, minutes, job)))
            continue
        need = BOUND_FACTOR * longest[job]
        if minutes * 60 < need:
            findings.append((job, "%s is %d, under %d times its longest recorded "
                                  "run of %dm%02ds (%dm%02ds needed)"
                                  % (_JOB_TIMEOUT_KEY, minutes, BOUND_FACTOR,
                                     longest[job] // 60, longest[job] % 60,
                                     need // 60, need % 60)))
        allowed = max(BOUND_CEILING_FACTOR * longest[job],
                      BOUND_FLOOR_MINUTES * 60)
        if minutes * 60 > allowed:
            findings.append((job, "%s is %d, over %d times its longest recorded "
                                  "run of %dm%02ds and over the %d-minute floor "
                                  "(%dm%02ds allowed) - a hung job holds its "
                                  "runner until the bound"
                                  % (_JOB_TIMEOUT_KEY, minutes,
                                     BOUND_CEILING_FACTOR,
                                     longest[job] // 60, longest[job] % 60,
                                     BOUND_FLOOR_MINUTES,
                                     allowed // 60, allowed % 60)))
    return findings


def job_timeout_verdict(repo=None):
    """`untimed_jobs()` over ci.yml as [(job, why)], with an unreadable workflow
    or one with no jobs in it AS a finding - a question nobody could ask must not
    reach `render()` as an empty list."""
    path = os.path.join(repo or REPO, CI_REL)
    try:
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (IOError, OSError) as exc:
        return [("ci.yml", "could not be read: %s" % (exc,))]
    got = untimed_jobs(text)
    if got["problem"] is not None:
        return [("ci.yml", got["problem"])]
    return got["findings"] + job_bound_evidence(text)


# --- every CI job pins its runner image -------------------------------------------
# A `*-latest` label is a pointer GitHub moves: `ubuntu-latest` went from ubuntu-24.04
# to ubuntu-26.04 between two runs of the same commit, and the new image could not
# install the browser the lockfile pins nor offered the interpreter the lint job asks
# for. Nothing in the repository changed, so no diff explains the red. An explicit
# image changes when this file does. The label is read where it is WRITTEN: a job's
# `runs-on`, and - when that is `${{ matrix.K }}` - every value the job's matrix
# gives K, in its axes and in its `include` and `exclude` rows, because an
# `exclude` left on the old label matches no cell once the axis is pinned and
# silently stops excluding.
_FLOATING_LABEL = re.compile(r"^[A-Za-z0-9._-]*-latest$", re.IGNORECASE)
_RUNS_ON_MATRIX = re.compile(r"^\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}$")


def _block_items(body, start, key_indent):
    """The scalar items of the block sequence that follows `body[start - 1]`, as
    ([item], index after the last one). An item is a `- value` line at or below
    the key's own indent; the first line that is not one ends the block."""
    items = []
    i = start
    while i < len(body):
        ln = body[i]
        got = re.match(r"^(\s*)-\s+(\S.*)$", ln)
        if not got or len(got.group(1)) < key_indent or ":" in got.group(2):
            break
        items.append(got.group(2).strip())
        i += 1
    return items, i


def _matrix_key_values(lines, key):
    """{"values": [...], "unread": [...]} for the job's `matrix:` block, or None
    when it has no such block. `values` is every label the block writes for `key`
    - the axis as an inline list, a scalar or a block sequence, and each `include`
    / `exclude` row's entry; `unread` holds each place the key is written in a form
    this cannot resolve to labels (an expression, a list spread over lines, a key
    with nothing under it), so a value nobody read is reported and not dropped.

    Read from the lines rather than from `_matrix_cells()`, which resolves the
    cells that RUN and so no longer shows an `exclude` value that matches none."""
    body = [re.sub(r"\s+#.*$", "", ln.rstrip()) for ln in lines
            if ln.strip() and not ln.strip().startswith("#")]
    heads = [i for i, ln in enumerate(body) if ln.strip() == "matrix:"]
    if len(heads) != 1:
        return None
    base = len(body[heads[0]]) - len(body[heads[0]].lstrip())
    values, unread = [], []
    i = heads[0] + 1
    while i < len(body):
        ln = body[i]
        i += 1
        if len(ln) - len(ln.lstrip()) <= base:
            break
        got = re.match(r"^(\s*)(?:-\s+)?%s:\s*(.*)$" % re.escape(key), ln)
        if not got:
            continue
        rest = got.group(2).strip()
        if not rest:
            # The key's own column: after a `- ` it is two columns past the dash.
            key_col = ln.index(key + ":")
            rest_items, i = _block_items(body, i, key_col)
            if not rest_items:
                unread.append(ln.strip())
            texts = rest_items
        elif rest.startswith("[") and rest.endswith("]"):
            texts = [v for v in rest[1:-1].split(",") if v.strip()]
        elif rest.startswith("["):
            unread.append(ln.strip())
            continue
        else:
            texts = [rest]
        for text in texts:
            text = text.strip().strip("'\"")
            if "${{" in text:
                unread.append(ln.strip())
            else:
                values.append(text)
    return {"values": values, "unread": unread}


# A runner image written the way GitHub labels one: `ubuntu-24.04`, `windows-2025`,
# `macos-latest`. In a job's display name it ties the check's name to the image, so
# the next image move renames the check a branch-protection rule may be waiting on.
_IMAGE_LABEL = re.compile(r"\b(?:ubuntu|windows|macos)-(?:latest|[0-9][0-9A-Za-z.]*)",
                          re.IGNORECASE)


def image_in_job_names(text):
    """[(job, why)] for each job whose `name:` carries a runner image - a label
    written out, or `${{ matrix.K }}` where `runs-on` reads that K. A name built
    from the family (`startsWith(matrix.os, 'windows')`) is not the image."""
    findings = []
    for job, lines in _workflow_jobs(text):
        keys = _job_keys(lines)
        name = keys.get("name")
        if name is None:
            continue
        ref = _RUNS_ON_MATRIX.match((keys.get("runs-on") or "").strip())
        via_key = ref is not None and re.search(
            r"\$\{\{\s*matrix\.%s\s*\}\}" % re.escape(ref.group(1)), name)
        if via_key or _IMAGE_LABEL.search(name):
            findings.append((job, "display name %r carries the runner image, so "
                                  "the next image move renames the check; name "
                                  "the family (windows, linux) instead" % name))
    return findings


def floating_runners(text):
    """{"findings": [(job, why)], "jobs": n, "problem": str|None} for a workflow.

    A finding is a job whose runner image is a floating `*-latest` label - written
    as its `runs-on`, or as a value its matrix gives the key `runs-on` reads - or
    whose label this cannot read: none at all, an expression other than a
    `matrix.` reference, or a reference to a key its matrix never lists. An
    unreadable label is reported rather than passed, because a label nobody could
    read is not a label somebody pinned. `jobs` counts the jobs read, so an empty
    finding list over zero jobs cannot pass for a clean workflow; a text with no
    `jobs:` block is a `problem`.
    """
    jobs = _workflow_jobs(text)
    if not jobs:
        return {"findings": [], "jobs": 0,
                "problem": "no top-level `jobs:` block naming a job, so no "
                           "runner image could be read"}
    findings = []
    for job, lines in jobs:
        label = _job_keys(lines).get("runs-on")
        if label is None:
            findings.append((job, "no `runs-on`, so which image runs it cannot "
                                  "be read"))
            continue
        label = label.strip().strip("'\"")
        ref = _RUNS_ON_MATRIX.match(label)
        if ref:
            got = _matrix_key_values(lines, ref.group(1))
            labels = got["values"] if got else []
            if got and got["unread"]:
                findings.append((job, "`runs-on` reads matrix key `%s`, written "
                                      "as %r, which this check cannot read into "
                                      "labels" % (ref.group(1), got["unread"][0])))
            elif not labels:
                findings.append((job, "`runs-on` reads matrix key `%s`, which "
                                      "the job's matrix does not list"
                                 % ref.group(1)))
                continue
        elif "${{" in label or not label:
            findings.append((job, "`runs-on` is %r, a form this check cannot "
                                  "resolve to an image" % label))
            continue
        else:
            labels = [v.strip().strip("'\"")
                      for v in label.strip("[]").split(",") if v.strip()]
        findings += [(job, "runner image %r floats: GitHub moves a `-latest` "
                           "label, so pin the image it points at today" % one)
                     for one in labels if _FLOATING_LABEL.match(one)]
    findings += image_in_job_names(text)
    return {"findings": findings, "jobs": len(jobs), "problem": None}


def runner_image_verdict(repo=None):
    """`floating_runners()` over ci.yml as [(job, why)], with an unreadable
    workflow or one with no jobs in it AS a finding."""
    path = os.path.join(repo or REPO, CI_REL)
    try:
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (IOError, OSError, UnicodeDecodeError) as exc:
        return [("ci.yml", "could not be read: %s" % (exc,))]
    got = floating_runners(text)
    if got["problem"] is not None:
        return [("ci.yml", got["problem"])]
    return got["findings"]


# --- the directories ruff and vermin are pointed at -----------------------------
# THE DIRECTORY LISTS LIVE IN ONE PLACE, `verify.sh`, and what that place says is a
# claim about where the code is. The suites and the two lint modules left the
# plugin, so a list still naming the old suite directory lints a directory that is
# gone and silently stops linting the suites that moved - the cheap failure being
# a `ruff` or `vermin` that exits 0 over fewer files than it did.
#
# `required` is by COVERAGE, not spelling: `tools` covers `tools/lints`, which is
# why ruff's list does not have to name it. `retired` is a spelling that must not
# come back, matched as a prefix so a subdirectory of it does not slip through.
LINT_DIR_RULES = (
    ("ruff", ("ruff", "check"), ("plugins/audit", "tools", "tests")),
    ("vermin", ("vermin",), ("plugins/audit/scripts", "plugins/audit/hooks",
                             "tests", "tools/lints")),
)
RETIRED_LINT_DIRS = ("plugins/audit/tests",)


def _joined_commands(text):
    """The command lines of a shell script with each `\\` continuation joined, so
    an invocation spread over two lines is one string to read."""
    out, pending = [], ""
    for line in _shell_command_lines(text):
        pending = (pending + " " + line).strip() if pending else line
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        out.append(pending)
        pending = ""
    if pending:
        out.append(pending)
    return out


def _covers(listed, wanted):
    """True when `wanted` is one of `listed` or sits under one of them."""
    return any(wanted == one or wanted.startswith(one.rstrip("/") + "/")
               for one in listed)


def lint_dir_findings(text):
    """{"findings": [(tool, why)], "read": [tool, ...]} for a `verify.sh` text.

    Each rule in `LINT_DIR_RULES` names a tool whose command line must be found
    and must cover every directory the rule requires; a command that is not there
    is a finding rather than a pass, because a list nobody could read is not a
    list somebody checked. A directory in `RETIRED_LINT_DIRS` named by any of the
    commands is a finding, whatever else is listed beside it.
    """
    commands = _joined_commands(text)
    findings, read = [], []
    for tool, words, required in LINT_DIR_RULES:
        found = None
        for command in commands:
            tokens = command.split()
            for i in range(len(tokens) - len(words) + 1):
                if tuple(tokens[i:i + len(words)]) == words:
                    found = tokens[i + len(words):]
                    break
            if found is not None:
                break
        if found is None:
            findings.append((tool, "verify.sh has no `%s` command, so the "
                                   "directories it lints cannot be read"
                             % " ".join(words)))
            continue
        read.append(tool)
        listed = [w.strip("'\"") for w in found
                  if not w.startswith("-") and w not in ("&&", "||", ";")]
        for want in required:
            if not _covers(listed, want):
                findings.append((tool, "its directory list %r does not cover `%s`"
                                 % (listed, want)))
        for old in RETIRED_LINT_DIRS:
            if any(_covers([old], one) for one in listed):
                findings.append((tool, "its directory list still names `%s`, "
                                       "a directory the suites left" % old))
    return {"findings": findings, "read": read}


def lint_dir_verdict(repo=None):
    """`lint_dir_findings()` over the tree's `verify.sh` as [(tool, why)], an
    unreadable runner AS a finding."""
    path = os.path.join(repo or REPO, VERIFY_REL)
    try:
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (IOError, OSError, UnicodeDecodeError) as exc:
        return [("verify.sh", "could not be read: %s" % (exc,))]
    return lint_dir_findings(text)["findings"]


def slice_verdict(repo=None):
    """`(slice findings, the parsed list or None, job count)` for the tree.

    A list that could not be had and a workflow that could not be read are each
    a finding, so neither silence reaches `render()` as an empty list.
    """
    root = repo or REPO
    listed, problem = verify_list(root)
    try:
        with io.open(os.path.join(root, CI_REL), encoding="utf-8") as fh:
            text = fh.read()
    except (IOError, OSError, UnicodeDecodeError) as exc:
        return [("ci.yml", "could not be read: %s" % (exc,))], listed, 0
    findings = ([("verify.sh --list", problem)] if listed is None
                else slice_drift(text, listed["tiers"]))
    return (findings + shard_matrix_drift(text), listed,
            len(_workflow_jobs(text)))


def parity(repo=None):
    """{"slices", "failmodes", "job_timeouts", "runner_images", "lint_dirs",
    "stale_exemptions", "counts"}.

    The rules that are not slice questions ride here because this command is
    already the one that reads a runner and the documents describing it, and a
    second place to run them from would be a second reader of the same files.
    """
    slices, listed, jobs = slice_verdict(repo)
    return {"slices": slices,
            "failmodes": failmode_table_verdict(repo),
            "job_timeouts": job_timeout_verdict(repo),
            "runner_images": runner_image_verdict(repo),
            "lint_dirs": lint_dir_verdict(repo),
            "stale_exemptions": exemption_audit_drift(repo),
            "counts": {"slices": len(listed["order"]) if listed else 0,
                       "jobs": jobs}}


def render(result, stream=None):
    """Print the verdict. Returns the exit code."""
    out = stream if stream is not None else sys.stdout
    bad = (result["slices"] + result["failmodes"] + result["job_timeouts"]
           + result["runner_images"] + result["lint_dirs"]
           + result["stale_exemptions"])
    out.write("gate parity: %d slice(s) listed by verify.sh --list, %d job(s) in "
              "ci.yml\n" % (result["counts"].get("slices", 0),
                            result["counts"].get("jobs", 0)))
    for subject, note in result["slices"]:
        out.write("  slice drift (%s): %s\n" % (subject, note))
    for subject, note in result["failmodes"]:
        out.write("  fail-mode drift (%s): %s\n" % (subject, note))
    for job, note in result["job_timeouts"]:
        out.write("  CI job bound (%s): %s\n" % (job, note))
    for job, note in result["runner_images"]:
        out.write("  CI runner image (%s): %s\n" % (job, note))
    for tool, note in result["lint_dirs"]:
        out.write("  lint directories (%s): %s\n" % (tool, note))
    for name, note in result["stale_exemptions"]:
        out.write("  exemption table (%s): %s\n" % (name, note))
    if not bad:
        out.write("  every slice ci.yml names is one verify.sh lists, every "
                  "per-run slice has a job, every sharded slice runs all its "
                  "parts, SECURITY.md's fail modes are the ones hooks.json "
                  "registers, every CI job carries a time bound two to three "
                  "times its longest recorded run (or the floor for a "
                  "sub-minute job), every CI job pins its runner image "
                  "instead of a floating `-latest` label, ruff and vermin are "
                  "pointed at the directories the code now lives in, and every "
                  "exemption table names who audits it\n")
    return 1 if bad else 0


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    result = parity()
    if "--list" in argv:
        listed, problem = verify_list()
        if listed is None:
            sys.stdout.write("  (no list: %s)\n" % (problem,))
        else:
            with io.open(os.path.join(REPO, CI_REL), encoding="utf-8") as fh:
                render_slices(listed, fh.read())
    return render(result)


# --- verify.sh removes its scratch directories under a strict POSIX sh ----------
# `trap '...' RETURN` is spelled correctly and does nothing in any POSIX sh that is
# not bash, so `verify.sh` (which asks for `/bin/sh`) left a `verify-ledger-*`
# directory under `$TMPDIR` on every run where `sh` is dash. Only a process can say
# whether a directory is still there afterwards, so these cases run the functions
# the script defines - cut out of the shipped file - in a shell, against a `python3`
# shim standing for the demo generator in one of three shapes (it reproduces the
# committed ledger, it writes a different one, it fails). The shell is `dash` when
# the machine has one and `sh` otherwise, and each label names the one that ran.
_VERIFY_CLAUSE = "the case named in the description"
_LEDGER_FUNCS = ("ledger_compare", "ledger_reproducible")
_GENERATOR_STUB = """#!/bin/sh
case "$STUB_MODE" in
  fail) exit 1 ;;
  same) cp examples/acme-store/.claude/usage/a.jsonl "$4/a.jsonl" ;;
  differ) printf 'other\\n' >"$4/a.jsonl" ;;
  term) printf 'partial\\n' >"$4/a.jsonl"; kill -TERM $PPID ;;
  int) printf 'partial\\n' >"$4/a.jsonl"; kill -INT $PPID ;;
esac
exit 0
"""
# The removed spelling, so the cases can show this shell is one that would keep it.
_RETURN_TRAP_FUNC = (
    "old() {\n  regen=$(mktemp -d \"${TMPDIR:-/tmp}/verify-ledger-XXXXXX\")\n"
    "  trap 'rm -rf \"$regen\"' RETURN\n  return 0\n}\nold\n")


def shell_function_text(source, name):
    """The shell function `name` as written in `source`, or None."""
    found = re.search(r"^%s\(\) \{\n.*?^\}\n" % (re.escape(name),), source,
                      re.S | re.M)
    return found.group(0) if found else None


def _default_sigint():
    """Runs in the child before exec: SIGINT back to its default action.

    A caller that is a background job passes SIGINT down as ignored, and a
    POSIX shell keeps an inherited-ignored signal ignored, so verify.sh's INT
    trap would never be reachable and the cases would grade the caller instead
    of the script. Windows has no preexec_fn, and its shell cases do not send
    signals through it."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def run_in_scratch_shell(sh, root, script, mode=None):
    """(exit code, output, what is left in the TMPDIR it was given).

    The child's SIGINT is reset to its default, whatever this process holds."""
    scratch = os.path.join(root, "tmp")
    if os.path.isdir(scratch):
        shutil.rmtree(scratch)
    os.makedirs(scratch)
    env = {"PATH": os.path.join(root, "bin") + os.pathsep + "/usr/bin"
           + os.pathsep + "/bin", "TMPDIR": scratch, "HOME": root}
    if mode is not None:
        env["STUB_MODE"] = mode
    done = subprocess.run([sh, "-c", script], cwd=root, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          preexec_fn=_default_sigint if os.name == "posix" else None)
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            sorted(os.listdir(scratch)))


def return_trap_probe(shell, argv_prefix=()):
    """(honoured, reason): whether `shell` runs a function-scoped RETURN trap.

    `argv_prefix` is put in front of the shell's own argv, so a stand-in that is
    a Python program can be run through the interpreter on every OS instead of
    through a shebang Windows cannot read. The shell is asked directly, one
    line, and it answers True only by printing the trap's word. A program the
    OS refuses to start is an answer too, not an escape: it is False with the
    reason named, so one unrunnable shell can fail its case without ending the
    suite body that asked. `reason` is None whenever the probe actually ran."""
    argv = list(argv_prefix) + [shell, "-c",
                                "f() { trap 'echo honoured' RETURN; return 0; }; f"]
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        return False, "OSError starting %r: %s" % (shell, exc)
    return b"honoured" in done.stdout, None


def return_trap_honoured(shell, argv_prefix=()):
    """True when `shell` runs a function-scoped RETURN trap, asked directly.

    The skip for a missing control has to rest on what the shell IS, so it is
    probed here with a one-line function rather than inferred from how many
    directories the control left. A shell that rejects the signal name (dash
    prints `bad trap`), runs nothing, or cannot be started answers False; the
    reason for the last is `return_trap_probe`'s."""
    return return_trap_probe(shell, argv_prefix)[0]


def return_trap_verdict(dash_present, left_count, honoured):
    """'control', 'skip' or 'fail' for the RETURN-trap control.

    Only a machine with no dash may skip, and only when the shell it fell back
    on provably honours the trap and left nothing behind. Dash on PATH never
    skips: a dash that no longer leaves its directory is a control that stopped
    working, and it must turn the suite red."""
    if left_count == 1:
        return "control"
    if not dash_present and left_count == 0 and honoured:
        return "skip"
    return "fail"


def _verify_cleanup_cases(check):
    from _suite import remove_tree
    dash = shutil.which("dash")
    shell = dash or shutil.which("sh")
    if shell is None:
        check("vsh0 no POSIX shell on PATH, so verify.sh's cleanup cannot be run",
              False)
        return
    ran = os.path.basename(shell)
    with io.open(os.path.join(REPO, VERIFY_REL), encoding="utf-8") as fh:
        source = fh.read()
    funcs = [shell_function_text(source, name) for name in _LEDGER_FUNCS]
    check("vsh1 %s - both functions that make and compare the regenerated ledger "
          "are found in the shipped script, so the cases below run its text and "
          "not a copy: %r" % (_VERIFY_CLAUSE, [f is not None for f in funcs]),
          all(f is not None for f in funcs))
    if not all(f is not None for f in funcs):
        return
    # The functions run under the script's own scratch-directory preamble (its
    # WORKDIR and traps, cut out of the shipped file), because the regenerated
    # directory is made under that workdir and only its exit trap can remove it on a
    # signal. The second printf reports what the workdir still holds at the moment
    # the function has returned, so an explicit early release is seen as well as the
    # trap's final one.
    head = source.split("WORKDIR=$(mktemp", 1)[1].split("\n\n", 1)[0]
    trapped = "WORKDIR=$(mktemp" + head + "\n"
    run_ledger = (trapped + "".join(funcs) + "ledger_reproducible\n"
                  "ledger_rc=$?\nprintf 'status=%s\\n' $ledger_rc\n"
                  "printf 'workdir_left=[%s]\\n' \"$(ls -A \"$WORKDIR\")\"\n")

    root = tempfile.mkdtemp(prefix="verify-sh-selftest-")
    try:
        os.makedirs(os.path.join(root, "bin"))
        stub = os.path.join(root, "bin", "python3")
        with io.open(stub, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_GENERATOR_STUB)
        os.chmod(stub, 0o755)
        usage = os.path.join(root, "examples", "acme-store", ".claude", "usage")
        os.makedirs(usage)
        with io.open(os.path.join(usage, "a.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("committed\n")

        _, out, left = run_in_scratch_shell(shell, root, run_ledger, mode="same")
        check("vsh2 %s - a regenerated ledger identical to the committed one is "
              "reported reproducible (status 0) and the scratch directory is gone "
              "afterwards, under %s: out=%r left=%r"
              % (_VERIFY_CLAUSE, ran, out, left),
              "status=0" in out and "workdir_left=[]" in out and left == [])

        _, out, left = run_in_scratch_shell(shell, root, run_ledger, mode="differ")
        check("vsh3 %s - a regenerated ledger that differs is refused (status 1), "
              "named, and the scratch directory is gone afterwards, under %s: "
              "out=%r left=%r" % (_VERIFY_CLAUSE, ran, out, left),
              "status=1" in out and "no longer matches" in out
              and "workdir_left=[]" in out and left == [])

        _, out, left = run_in_scratch_shell(shell, root, run_ledger, mode="fail")
        check("vsh4 %s - a generator that fails is refused (status 1) and the "
              "scratch directory is gone afterwards, under %s: out=%r left=%r"
              % (_VERIFY_CLAUSE, ran, out, left),
              "status=1" in out and "workdir_left=[]" in out and left == [])

        # A signal that arrives WHILE the generator runs ends the run through the
        # script's exit trap; the regenerated directory must go with it. This is the
        # case that is red when that directory is made under the system temp
        # directory instead of the workdir, which only the explicit removal after
        # the comparison would then reach.
        for sig, want in (("TERM", 143), ("INT", 130)):
            code, out, left = run_in_scratch_shell(
                shell, root, run_ledger, mode=sig.lower())
            check("vsh9 %s - a %s arriving while the generator runs ends the run "
                  "with status %d, never reports a ledger verdict, and leaves no "
                  "regenerated directory behind, under %s: code=%r out=%r left=%r"
                  % (_VERIFY_CLAUSE, sig, want, ran, code, out, left),
                  code == want and "status=" not in out and left == [])

        # The control. If the shell in use ran a RETURN trap, the cases above
        # could not have seen the defect and their green would say nothing. Three
        # outcomes, decided by return_trap_verdict(): the directory is left behind
        # (a real control); the shell is not dash, honours the trap when asked
        # directly, and left nothing (a skip the run SAYS it took, through the
        # house helper); or anything else, which is red - above all a dash that
        # stopped leaving its directory, because that is the vacuous state this
        # control exists to catch and "install dash" would tell the reader to
        # install the shell already running.
        _, _, left = run_in_scratch_shell(shell, root, _RETURN_TRAP_FUNC,
                                          mode="same")
        honoured = return_trap_honoured(shell)
        verdict = return_trap_verdict(dash is not None, len(left), honoured)
        if verdict == "control":
            check("vsh5 the cases can see the defect they guard - the removed "
                  "`trap ... RETURN` spelling leaves its directory behind under "
                  "%s: left=%r" % (ran, left), True)
        elif verdict == "skip":
            from _harness import skip
            skip(check, "vsh5",
                 "under %s (no dash on PATH) a function-scoped `trap ... RETURN` "
                 "runs when probed directly and the removed spelling left no "
                 "directory behind, so vsh2-vsh4 and vsh9 above could not have "
                 "seen the defect it guards; install dash to run the control: "
                 "left=%r" % (ran, left), honoured and len(left) == 0)
        else:
            check("vsh5 the cases can see the defect they guard - under %s the "
                  "removed `trap ... RETURN` spelling left %d directories "
                  "(dash on PATH: %s, RETURN trap honoured when probed: %s), so "
                  "vsh2-vsh4 and vsh9 cannot see the defect: left=%r"
                  % (ran, len(left), dash is not None, honoured, left), False)

        # The signal half: TERM and INT must END the run with the directory
        # removed, not remove it and let the script carry on.
        for sig, want in (("TERM", 143), ("INT", 130)):
            code, out, left = run_in_scratch_shell(
                shell, root,
                trapped + "kill -%s $$\nprintf 'resumed\\n'\n" % (sig,))
            check("vsh6 %s - a %s ends the run with status %d and removes the "
                  "workdir instead of resuming, under %s: code=%r out=%r left=%r"
                  % (_VERIFY_CLAUSE, sig, want, ran, code, out, left),
                  code == want and "resumed" not in out and left == [])

        # A background job (nohup, `&`, a harness runner) hands its children SIGINT
        # as ignored, and a POSIX shell keeps an inherited-ignored signal ignored,
        # so a trap on it never fires. This process ignores it here, as such a
        # caller would, and the INT legs must still end at 130: the cases measure
        # verify.sh's trap, not the caller's disposition. The two legs are the
        # ones vsh6 and vsh9 run; they are red without the reset in
        # run_in_scratch_shell.
        was = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            code_a, out_a, left_a = run_in_scratch_shell(
                shell, root, trapped + "kill -INT $$\nprintf 'resumed\\n'\n")
            code_b, out_b, left_b = run_in_scratch_shell(
                shell, root, run_ledger, mode="int")
        finally:
            signal.signal(signal.SIGINT, was)
        check("vsh13 the INT leg exits 130 even when this process ignores SIGINT, "
              "under %s: kill=%r/%r/%r generator=%r/%r/%r"
              % (ran, code_a, out_a, left_a, code_b, out_b, left_b),
              code_a == 130 and "resumed" not in out_a and left_a == []
              and code_b == 130 and "status=" not in out_b and left_b == [])

        code, out, left = run_in_scratch_shell(shell, root, trapped + "exit 3\n")
        check("vsh7 %s - a plain exit still removes the workdir and keeps its "
              "status, under %s: code=%r left=%r"
              % (_VERIFY_CLAUSE, ran, code, left),
              code == 3 and left == [])
    finally:
        remove_tree(root)

    check("vsh8 %s - the script names RETURN as a trap signal nowhere outside a "
          "comment" % (_VERIFY_CLAUSE,),
          not re.search(r"^[^#\n]*\btrap\b[^\n]*\bRETURN\b", source, re.M))


# --- the slices ci.yml runs against the slices verify.sh lists: the cases ------
_SLICE_CLAUSE = ("a slice ci.yml names that verify.sh --list does not print is "
                 "red, a per-run slice no job runs is red, and shards that do not "
                 "cover 1..N are red")
_SLICE_RUN_CLAUSE = ("verify.sh --only lint under dash leaves no verify-* "
                     "directory in TMPDIR, and --list prints exactly the slices "
                     "the run calls execute")

# A workflow of the shape ci.yml has: a guard job, a sharded sweep job whose
# slice and shard come from its matrix, plain jobs naming their slices, and a
# job only the release tier runs.
_SLICE_CI = """\
on:
  workflow_dispatch:
    inputs:
      tier:
        default: per-run
jobs:
  verified:
    timeout-minutes: 5
    steps:
      - run: python tools/ci-verified.py --sha "$GITHUB_SHA"
  selftests:
    timeout-minutes: 26
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
        slice: [selftests, selftests-stress]
        shard: [1, 2, 3]
        exclude:
          - os: windows-latest
            slice: selftests-stress
    steps:
      - uses: actions/checkout@v5
      - run: sh tools/verify.sh --only ${{ matrix.slice }} --shard ${{ matrix.shard }}/3
  lint:
    timeout-minutes: 5
    steps:
      - run: sh tools/verify.sh --only lint,runner
  resample:
    if: ${{ !cancelled() && inputs.tier == 'release' }}
    timeout-minutes: 40
    steps:
      - run: sh tools/verify.sh --only resample
"""
_SLICE_LISTED = {"selftests": "per-run", "selftests-stress": "per-run",
                 "lint": "per-run", "runner": "per-run",
                 "release": "release", "resample": "release"}


def _slice_cases(check):
    clean = slice_drift(_SLICE_CI, _SLICE_LISTED) + shard_matrix_drift(_SLICE_CI)
    check("sv0 %s (THE ALLOW CASE: a workflow running every per-run slice, with "
          "a full shard matrix and a release-only slice no job runs, is clean: "
          "%r)" % (_SLICE_CLAUSE, clean), clean == [])

    unknown = slice_drift(_SLICE_CI.replace("--only lint,runner",
                                            "--only lint,runner,lnt"),
                          _SLICE_LISTED)
    check("sv1 %s (a job naming a slice the list does not print is named: %r)"
          % (_SLICE_CLAUSE, unknown),
          [s for s, _why in unknown] == ["lnt"])

    listed = dict(_SLICE_LISTED, js="per-run")
    unrun = slice_drift(_SLICE_CI, listed)
    check("sv2 %s (a per-run slice no job runs is named: %r)"
          % (_SLICE_CLAUSE, unrun), [s for s, _why in unrun] == ["js"])

    # A per-run slice that only the release-tier job runs is unrun on every
    # ordinary run, which is the same gap as no job at all.
    release_only = slice_drift(
        _SLICE_CI.replace("--only lint,runner", "--only lint"),
        _SLICE_LISTED.copy())
    tiered = slice_drift(
        _SLICE_CI.replace("--only lint,runner", "--only lint")
                 .replace("--only resample", "--only resample,runner"),
        _SLICE_LISTED)
    check("sv3 %s (a per-run slice dropped from its job, and one left only to "
          "the release-tier job, are both named: %r / %r)"
          % (_SLICE_CLAUSE, release_only, tiered),
          [s for s, _why in release_only] == ["runner"]
          and [s for s, _why in tiered] == ["runner"])

    short = shard_matrix_drift(_SLICE_CI.replace("shard: [1, 2, 3]",
                                                 "shard: [1, 2]"))
    over = shard_matrix_drift(_SLICE_CI.replace("shard: [1, 2, 3]",
                                                "shard: [1, 2, 3, 4]"))
    check("sv4 %s (a matrix missing part 3 of 3, and one listing a part 4 of 3, "
          "are both named: %r / %r)" % (_SLICE_CLAUSE, short, over),
          len(short) >= 1 and any("3" in why for _s, why in short)
          and len(over) >= 1 and any("4" in why for _s, why in over))

    # Read as GitHub reads the matrix: an exclude that drops one part of one
    # slice leaves that slice short on that runner, though every list still
    # carries all three values.
    holed = shard_matrix_drift(_SLICE_CI.replace(
        "        exclude:\n",
        "        exclude:\n          - os: windows-latest\n"
        "            shard: 2\n"))
    check("sv5 %s (an exclude removing part 2 on one runner leaves that "
          "runner's slice short, and it is named: %r)" % (_SLICE_CLAUSE, holed),
          len(holed) >= 1 and any("windows-latest" in s or "windows-latest" in why
                                  for s, why in holed))

    # The shape ci.yml really has: cells named by a `leg` axis, and `include` rows
    # that add the slice to every cell of a leg because they overwrite no listed
    # value. Read as plain extra cells - the old reading - the slices would ride on
    # three cells with no os and no shard, and the real cells would resolve no slice.
    by_leg = _SLICE_CI.replace(
        "        slice: [selftests, selftests-stress]\n",
        "        leg: [plain, stress]\n").replace(
        "            slice: selftests-stress\n",
        "            leg: stress\n")
    by_leg = by_leg.replace(
        "          - os: windows-latest\n            leg: stress\n",
        "          - os: windows-latest\n            leg: stress\n"
        "        include:\n          - leg: plain\n            slice: selftests\n"
        "          - leg: stress\n            slice: selftests-stress\n")
    legged = job_slices(by_leg)
    cells = [(r["cell"].get("leg"), r["cell"].get("slice"), r["shard"])
             for j in legged["jobs"] if j["job"] == "selftests" for r in j["runs"]]
    alone = _matrix_cells(["        matrix:", "          os: [a, b]",
                           "          include:", "            - os: c",
                           "              extra: x"])
    check("sv11 %s (an `include` row joins every cell it overwrites nothing in, so "
          "each leg's cells carry its slice and the workflow is clean; one naming a "
          "value the matrix does not list is a cell of its own: %r / %r / %r)"
          % (_SLICE_CLAUSE, sorted(set(cells)), legged["problems"], alone),
          len(cells) == 9 and legged["problems"] == []
          and set((leg, sl) for leg, sl, _s in cells)
          == set([("plain", "selftests"), ("stress", "selftests-stress")])
          and slice_drift(by_leg, _SLICE_LISTED) == []
          and shard_matrix_drift(by_leg) == []
          and alone["cells"] == [{"os": "a"}, {"os": "b"}, {"os": "c", "extra": "x"}])

    # A PART COUNT PER RUNNER FAMILY, the shape ci.yml has once the two families
    # stop sharing one: the total is a matrix value an `include` row keyed by `os`
    # adds, and an `exclude` drops the parts the smaller family does not have. Each
    # family is still held to every part of ITS total - a reader taking one total
    # for the whole job would call the smaller family short, and a forgotten
    # exclude, or a family's total raised with no part added, must each be named.
    per_family = _SLICE_CI.replace(
        "          - os: windows-latest\n            slice: selftests-stress\n",
        "          - os: windows-latest\n            slice: selftests-stress\n"
        "          - os: ubuntu-latest\n            shard: 3\n"
        "        include:\n          - os: ubuntu-latest\n            parts: 2\n"
        "          - os: windows-latest\n            parts: 3\n").replace(
        "${{ matrix.shard }}/3", "${{ matrix.shard }}/${{ matrix.parts }}")
    no_exclude = per_family.replace(
        "          - os: ubuntu-latest\n            shard: 3\n", "")
    raised = per_family.replace("            parts: 3\n", "            parts: 4\n")
    unset = per_family.replace(
        "          - os: windows-latest\n            parts: 3\n", "")
    fam_clean = slice_drift(per_family, _SLICE_LISTED) + shard_matrix_drift(
        per_family)
    fam_parts = (family_shard_parts(per_family, "ubuntu"),
                 family_shard_parts(per_family, "windows"))
    fam_over, fam_short = (shard_matrix_drift(no_exclude),
                           shard_matrix_drift(raised))
    fam_unset = slice_drift(unset, _SLICE_LISTED)
    check("sv16 %s (a part count per runner family - two on one, three on the "
          "other - is clean and each family runs every part of its own total; a "
          "missing exclude asks the smaller family for a part it does not have, a "
          "raised total leaves a part unrun, and a family with no total is a "
          "named job problem: %r / %r / %r / %r / %r)"
          % (_SLICE_CLAUSE, fam_clean, fam_parts, fam_over, fam_short, fam_unset),
          per_family.count("matrix.parts") == 1 and no_exclude != per_family
          and raised != per_family and unset != per_family
          and fam_clean == []
          and fam_parts == ({"selftests": [(1, 2), (2, 2)],
                             "selftests-stress": [(1, 2), (2, 2)]},
                            {"selftests": [(1, 3), (2, 3), (3, 3)]})
          and sorted(s for s, _w in fam_over)
          == ["selftests (os=ubuntu-latest, slice=selftests, --only selftests)",
              "selftests (os=ubuntu-latest, slice=selftests-stress, "
              "--only selftests-stress)"]
          and all("part(s) [3] of 2" in w for _s, w in fam_over)
          and [s for s, _w in fam_short]
          == ["selftests (os=windows-latest, slice=selftests, --only selftests)"]
          and "part(s) [4] never run" in fam_short[0][1]
          and len(fam_unset) == 3
          and set(s for s, _w in fam_unset) == set(["selftests (job)"]))

    # A job's `if:` is held to what it reduces to, not to whether it mentions the
    # release tier: a condition that is false, or true on a push only, leaves its
    # slices unrun on an ordinary run while the job still reads as per-run.
    def with_if(cond):
        text = _SLICE_CI.replace("  lint:\n    timeout-minutes: 5\n",
                                 "  lint:\n    if: %s\n    timeout-minutes: 5\n"
                                 % (cond,))
        assert text != _SLICE_CI, "the lint job's header moved in the fixture"
        return text

    guard = "${{ !cancelled() && needs.verified.outputs.run == '' }}"
    tiered_guard = ("${{ !cancelled() && needs.verified.outputs.run == '' && "
                    "inputs.tier == 'release' }}")
    release_job = _SLICE_CI.replace("${{ !cancelled() && inputs.tier == 'release' }}",
                                    tiered_guard)
    assert release_job != _SLICE_CI, "the resample job's condition moved"
    never = slice_drift(with_if("${{ false }}"), _SLICE_LISTED)
    push_only = slice_drift(with_if("${{ github.event_name == 'push' }}"),
                            _SLICE_LISTED)
    guarded = slice_drift(with_if(guard), _SLICE_LISTED)
    released = slice_drift(release_job, _SLICE_LISTED)
    check("sv12 a per-run job carrying `if: ${{ false }}` and one carrying a "
          "push-only condition are each reported by slice_drift naming the job, "
          "while the verified-run guard alone and with the release-tier term "
          "report nothing (%r / %r / %r / %r)" % (never, push_only, guarded,
                                                  released),
          [(s, w) for s, w in never if s == "lint (job)"]
          and all("cannot be proved" in w for s, w in never if s == "lint (job)")
          and [s for s, _w in push_only if s.endswith("(job)")] == ["lint (job)"]
          and guarded == [] and released == [])

    unread = slice_drift(_SLICE_CI, None)
    check("sv6 %s (a list that could not be read is a named problem, never an "
          "empty verdict: %r)" % (_SLICE_CLAUSE, unread), len(unread) == 1)

    real = parity()
    check("sv7 %s (THE LIVE CLAIM: ci.yml against the real `verify.sh --list` - "
          "%d slice(s) listed, %d job(s) read, and the counts are what keep an "
          "unread list or workflow from passing: %r)"
          % (_SLICE_CLAUSE, real["counts"]["slices"], real["counts"]["jobs"],
             real["slices"]),
          real["slices"] == [] and real["counts"]["slices"] > 0
          and real["counts"]["jobs"] > 0)

    absent = parity(os.path.join(REPO, "no-such-repo-dir"))
    check("sv8 %s (a tree with no runner and no workflow is a NAMED failure, not "
          "a clean verdict over nothing: %r)" % (_SLICE_CLAUSE, absent["slices"]),
          len(absent["slices"]) >= 1
          and any("could not be read" in why or "not there" in why
                  for _s, why in absent["slices"]))

    clean = {"slices": [], "failmodes": [], "job_timeouts": [],
             "runner_images": [], "lint_dirs": [],
             "stale_exemptions": [], "counts": {"slices": 3, "jobs": 2}}
    for key, row, needle in (("slices", ("js", "no job runs it"), "js"),
                             ("failmodes", ("guard-edits / PreToolUse", "why"),
                              "guard-edits / PreToolUse"),
                             ("job_timeouts", ("lint", "no bound"), "lint"),
                             ("runner_images", ("e2e", "floats"), "e2e"),
                             ("lint_dirs", ("vermin", "no tests"), "vermin"),
                             ("stale_exemptions", ("GONE", "outlived"), "GONE")):
        buf = io.StringIO()
        code = render(dict(clean, **{key: [row]}), stream=buf)
        check("sv9 %s (a %s finding alone exits 1 and names its subject, so no "
              "kind of finding can hide behind the others being clean: %r)"
              % (_SLICE_CLAUSE, key, buf.getvalue()[-160:]),
              code == 1 and needle in buf.getvalue()
              and "every slice ci.yml names" not in buf.getvalue())
    buf = io.StringIO()
    code = render(clean, stream=buf)
    check("sv10 %s (and a clean verdict exits 0 saying what was checked - "
          "'nothing to report' must not read like 'nothing was compared': %r)"
          % (_SLICE_CLAUSE, buf.getvalue()),
          code == 0 and "every slice ci.yml names" in buf.getvalue()
          and "3 slice(s)" in buf.getvalue())


# THE WINDOWS PART COUNT, pinned rather than read, because the windows sweep cells
# are the run's critical path and the count is what its wall clock rests on: a
# matrix narrowed back to fewer parts is still complete, so shard_matrix_drift
# accepts it, and only this pin names it. The linux legs' count is not pinned -
# shard_matrix_drift holds each family to every part of its own total either way.
WINDOWS_SHARDS = 5
_CI_SHAPE_CLAUSE = ("every slice a per-run job of ci.yml runs is one `verify.sh "
                    "--list` prints, each piece of the manifest-validation work is "
                    "run by one of them, and the Windows sweep cells run parts "
                    "1..%d of %d of each slice" % (WINDOWS_SHARDS, WINDOWS_SHARDS))


def _ci_shape_findings(text, listed):
    """[(subject, why)] for the live claim the ci-shape cases make, over a
    workflow `text` and a parsed `verify.sh --list`."""
    named = per_run_named(text, listed["tiers"])
    windows = family_shard_parts(text, "windows")
    if named is None or windows is None:
        return [("ci.yml", "its jobs could not be read")]
    out = [(name, "a per-run job (%s) runs it and `verify.sh --list` does not "
            "print it" % (", ".join(jobs),))
           for name, jobs in sorted(named.items()) if name not in listed["tiers"]]
    for piece, slices in manifest_work_slices(listed):
        if not slices:
            out.append((piece, "no slice `verify.sh --list` prints runs it"))
        elif not [s for s in slices if s in named]:
            out.append((piece, "run only by slice(s) %s, which no per-run job "
                        "runs" % (", ".join(slices),)))
    want = set((i, WINDOWS_SHARDS) for i in range(1, WINDOWS_SHARDS + 1))
    if not windows:
        out.append(("windows", "no sharded sweep cell runs on a windows runner"))
    for name, parts in sorted(windows.items()):
        if set(parts) != want:
            out.append(("windows %s" % (name,), "its cells run parts %r, not "
                        "1..%d of %d" % (parts, WINDOWS_SHARDS, WINDOWS_SHARDS)))
    return out


def _ci_shape_cases(check):
    listed, problem = verify_list()
    try:
        with io.open(os.path.join(REPO, CI_REL), encoding="utf-8") as fh:
            text = fh.read()
    except (IOError, OSError, UnicodeDecodeError) as exc:
        text, problem = None, problem or "ci.yml could not be read: %s" % (exc,)
    if listed is None or text is None:
        check("sv13 %s (the runner's list or the workflow could not be read, so "
              "nothing was compared: %r)" % (_CI_SHAPE_CLAUSE, problem), False)
        return
    work = manifest_work_slices(listed)
    windows = family_shard_parts(text, "windows")
    live = _ci_shape_findings(text, listed)
    check("sv13 %s (THE LIVE CLAIM, over the real ci.yml and `verify.sh --list`: "
          "the work is run by %r, the windows cells run %r, and the findings "
          "are %r)" % (_CI_SHAPE_CLAUSE, work, windows, live),
          live == [] and all(slices for _p, slices in work)
          and len(work) == len(MANIFEST_WORK) and bool(windows)
          and "selftests" in windows)

    # A per-run job naming a manifest slice the runner does not list, and a
    # workflow from which the manifest job's slice has gone: the first is named
    # by its slice, the second by every piece of the work it carried.
    calls = re.findall(r"--only (\S*manifests\S*)", text)
    unlisted = _ci_shape_findings(
        text.replace(calls[0], calls[0].replace("manifests",
                                                "manifests,manifests-doctor"), 1)
        if calls else text, listed)
    without = (text.replace(calls[0], calls[0].replace("manifests,", "").replace(
        ",manifests", ""), 1) if calls else text)
    dropped = _ci_shape_findings(without, listed)
    # ...and moved to the release-tier job alone, which an ordinary run skips.
    moved = without.replace("--only resample", "--only resample,manifests", 1)
    released = _ci_shape_findings(moved, listed)
    check("sv14 %s (a per-run job naming `manifests-doctor`, which the list does "
          "not print, is named; and the manifest job's slice dropped from it, or "
          "left only to the release-tier job, leaves every piece of the work "
          "named as unrun: %r / %r / %r)"
          % (_CI_SHAPE_CLAUSE, unlisted, dropped, released),
          len(calls) == 1 and moved != without
          and [s for s, _w in unlisted] == ["manifests-doctor"]
          and sorted(s for s, _w in dropped)
          == sorted(p for p, _w in MANIFEST_WORK)
          and sorted(s for s, _w in released)
          == sorted(p for p, _w in MANIFEST_WORK))

    # The windows cells held to their pinned part count: the windows family
    # narrowed to one part fewer, complete in itself, and an exclude dropping the
    # last part on windows alone, are each named by the windows slice they leave
    # short - shard_matrix_drift accepts the first, since N-1 of N-1 is complete.
    # Built off the live text, so the windows `parts` row must be there to edit.
    last = WINDOWS_SHARDS
    row = "          - os: windows-2025\n            parts: %d\n" % (last,)
    drop_last = ("        exclude:\n          - os: windows-2025\n"
                 "            shard: %d\n" % (last,))
    fewer = text.replace(row, row.replace("parts: %d" % (last,),
                                          "parts: %d" % (last - 1,)), 1)
    fewer = fewer.replace("        exclude:\n", drop_last, 1)
    holed = text.replace("        exclude:\n", drop_last, 1)
    narrowed, excluded = (_ci_shape_findings(fewer, listed),
                          _ci_shape_findings(holed, listed))
    check("sv15 %s (the windows family narrowed to %d parts of %d, and an "
          "exclude dropping part %d on windows, are each named by a windows "
          "slice: %r / %r)" % (_CI_SHAPE_CLAUSE, last - 1, last - 1, last,
                               narrowed, excluded),
          text.count(row) == 1 and fewer != text and holed != text
          and shard_matrix_drift(fewer) == []
          and shard_matrix_drift(holed) != []
          and narrowed and all(s.startswith("windows ") for s, _w in narrowed)
          and "windows selftests" in [s for s, _w in narrowed]
          and "windows selftests" in [s for s, _w in excluded])


def _verify_stub_bin(root):
    """A bin directory whose interpreters and tools answer at once and record
    nothing, so verify.sh's own control flow is what runs: every slice, every
    trap, every label. `0.0.0` is what each stub prints, so a step whose label
    is built from a stub's output reads the same in `--list` and in a run."""
    bin_dir = os.path.join(root, "bin")
    os.makedirs(bin_dir)
    for name in ("python3", "python", "ruff", "vermin", "node", "npx", "claude"):
        path = os.path.join(bin_dir, name)
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("#!/bin/sh\necho 0.0.0\nexit 0\n")
        os.chmod(path, 0o755)
    return bin_dir


def run_verify(shell, root, args):
    """(exit code, output, what is left in the TMPDIR it was given) for the
    shipped verify.sh run under `shell` with the stubs `root/bin` holds."""
    scratch = os.path.join(root, "tmp")
    if os.path.isdir(scratch):
        shutil.rmtree(scratch)
    os.makedirs(scratch)
    env = {"PATH": os.path.join(root, "bin") + os.pathsep + "/usr/bin"
           + os.pathsep + "/bin", "TMPDIR": scratch, "HOME": root}
    done = subprocess.run([shell, os.path.join(REPO, VERIFY_REL)] + list(args),
                          cwd=root, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            sorted(os.listdir(scratch)))


def summary_labels(output):
    """The labels a run's summary table names, in order, without their status."""
    tail = output.split("verify: summary", 1)
    if len(tail) < 2:
        return None
    labels = []
    for line in tail[1].splitlines():
        got = re.match(r"^  (?:ok|FAIL|skip)  +(.*?)(?: \(--fast\))?$", line)
        if got:
            labels.append(got.group(1))
    return labels


def _verify_slice_run_cases(check):
    from _suite import remove_tree
    shell = shutil.which("dash") or shutil.which("sh")
    if shell is None:
        check("svr0 %s (no POSIX shell on PATH, so verify.sh cannot be run)"
              % (_SLICE_RUN_CLAUSE,), False)
        return
    ran = os.path.basename(shell)
    root = tempfile.mkdtemp(prefix="verify-slices-selftest-")
    try:
        _verify_stub_bin(root)
        code, out, left = run_verify(shell, root, ["--only", "lint"])
        check("svr1 %s (under %s, `--only lint` ran its steps, exited %r and left "
              "%r in TMPDIR: %r)" % (_SLICE_RUN_CLAUSE, ran, code, left,
                                     _output_tail(out)),
              code == 0 and left == [] and bool(summary_labels(out)))

        code, out, left = run_verify(shell, root, ["--list"])
        listed = parse_verify_list(out)
        check("svr2 %s (under %s, `--list` exited %r, printed slices %r and "
              "left %r in TMPDIR)" % (_SLICE_RUN_CLAUSE, ran, code,
                                      sorted((listed or {}).get("tiers", {})),
                                      left),
              code == 0 and left == [] and listed is not None
              and "lint" in listed["tiers"]
              and "per-run" in listed["tiers"].values()
              and "release" in listed["tiers"].values())
        if listed is None:
            return
        unpaired = [(name, len(listed["steps"][name]), len(listed["commands"][name]))
                    for name in listed["order"]
                    if len(listed["commands"][name]) != len(listed["steps"][name])]
        check("svr2b `--list` prints one command under each step label, and the "
              "parse reads it apart from the label - the sweep's own command is "
              "what says a slice runs it unscoped (slices whose counts differ: %r; "
              "the selftests slice reads %r)"
              % (unpaired, listed["commands"].get("selftests")),
              unpaired == []
              and listed["commands"].get("selftests") == [
                  "python3 tools/sweep-selftests.py"])
        drift = []
        for name in listed["order"]:
            code, out, left = run_verify(shell, root, ["--only", name])
            ran_labels = summary_labels(out)
            if ran_labels != listed["steps"][name] or left:
                drift.append((name, listed["steps"][name], ran_labels, left,
                              _output_tail(out)))
        check("svr3 %s (every slice `--list` prints is one `--only` runs, step "
              "for step, and none leaves a directory behind: %r)"
              % (_SLICE_RUN_CLAUSE, drift), drift == [])

        per_run = [label for name in listed["order"]
                   if listed["tiers"][name] == "per-run"
                   for label in listed["steps"][name]]
        code, out, left = run_verify(shell, root, [])
        check("svr4 %s (a run with no flag executes exactly the per-run slices' "
              "steps, in the order `--list` prints them: %r vs %r, left %r)"
              % (_SLICE_RUN_CLAUSE, summary_labels(out), per_run, left),
              summary_labels(out) == per_run and left == [])

        code, out, left = run_verify(shell, root, ["--only", "lnt"])
        code2, out2, left2 = run_verify(shell, root, ["--only", "lint",
                                                      "--shard", "1/3"])
        check("svr5 %s (a slice the list does not print, and a shard of a slice "
              "that is not a sweep, are refused with exit 2 having run nothing: "
              "%r %r / %r %r)" % (_SLICE_RUN_CLAUSE, code, _output_tail(out),
                                  code2, _output_tail(out2)),
              code == 2 and code2 == 2 and summary_labels(out) is None
              and summary_labels(out2) is None and left == [] and left2 == [])
    finally:
        remove_tree(root)


# --- every CI job pins its runner image: the cases ---------------------------------
_RI_CLAUSE = ("a workflow job whose runs-on is a floating *-latest label is reported "
              "by name, while an explicit image (ubuntu-24.04, windows-2025) is not")
_RI_PLAIN = ("name: ci\njobs:\n"
             "  floats:\n    runs-on: ubuntu-latest\n    steps:\n      - run: x\n"
             "  pinned:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: x\n"
             "  win-pinned:\n    runs-on: windows-2025\n    steps:\n      - run: x\n"
             "  win-floats:\n    runs-on: windows-latest\n    steps:\n      - run: x\n")
_RI_BLOCK = ("name: ci\njobs:\n  cells:\n    strategy:\n      matrix:\n"
             "        os:\n          - ubuntu-24.04\n          - %s\n"
             "        leg: [a, b]\n        include:\n          - os: %s\n"
             "            leg: c\n"
             "    runs-on: ${{ matrix.os }}\n    steps:\n      - run: x\n")
_RI_BLOCK_RAW = ("name: ci\njobs:\n  cells:\n    strategy:\n      matrix:\n"
                 "        os:\n%s"
                 "        leg: [a, b]\n"
                 "    runs-on: ${{ matrix.os }}\n    steps:\n      - run: x\n")
_RI_NAMED = ("name: ci\njobs:\n  cells:\n    name: %s\n    strategy:\n"
             "      matrix:\n        os: [ubuntu-24.04, windows-2025]\n"
             "    runs-on: ${{ matrix.os }}\n    steps:\n      - run: x\n")
_RI_MATRIX = ("name: ci\njobs:\n  cells:\n    strategy:\n      matrix:\n"
              "        os: [ubuntu-24.04, windows-2025]\n        leg: [a, b]\n"
              "%s"
              "    runs-on: ${{ matrix.os }}\n    steps:\n      - run: x\n")


def _runner_image_cases(check):
    plain = floating_runners(_RI_PLAIN)
    check("ri1 %s (the plain `runs-on:` label: %r)" % (_RI_CLAUSE, plain),
          plain["problem"] is None and plain["jobs"] == 4
          and [job for job, _why in plain["findings"]] == ["floats", "win-floats"]
          and all("-latest" in why for _job, why in plain["findings"]))

    # The over-fire direction: a check that reported every job, or every label that
    # carries a hyphen, fails this one, which names no floating label at all.
    pinned = floating_runners(_RI_PLAIN.replace("ubuntu-latest", "ubuntu-24.04")
                              .replace("windows-latest", "windows-2025"))
    check("ri2 ...and the same workflow with every label an explicit image is "
          "clean, over all four jobs read: %r" % (pinned,),
          (pinned["findings"], pinned["jobs"], pinned["problem"]) == ([], 4, None))

    axis = floating_runners(_RI_MATRIX % "").get("findings")
    floated = floating_runners(
        (_RI_MATRIX % "").replace("windows-2025]", "windows-latest]"))
    check("ri3 ...a `runs-on: ${{ matrix.os }}` job is judged by the values its "
          "matrix lists for `os`: pinned values are clean and one floating value "
          "is reported, naming the job and the value: %r / %r" % (axis, floated),
          axis == [] and [j for j, _w in floated["findings"]] == ["cells"]
          and "windows-latest" in floated["findings"][0][1])

    # An `exclude` or `include` row is a value the matrix names too: left on the old
    # label after the axis was pinned, an exclude matches no cell and silently stops
    # excluding, which is a wrong CI that no job's runs-on shows.
    stale = floating_runners(_RI_MATRIX % (
        "        exclude:\n          - os: windows-latest\n            leg: a\n"))
    added = floating_runners(_RI_MATRIX % (
        "        include:\n          - os: ubuntu-latest\n            leg: c\n"))
    check("ri4 ...and so are the values in a matrix's `exclude` and `include` "
          "rows: %r / %r" % (stale["findings"], added["findings"]),
          [j for j, _w in stale["findings"]] == ["cells"]
          and "windows-latest" in stale["findings"][0][1]
          and [j for j, _w in added["findings"]] == ["cells"]
          and "ubuntu-latest" in added["findings"][0][1])

    unreadable = (
        floating_runners("name: ci\njobs:\n  a:\n    steps:\n      - run: x\n"),
        floating_runners("name: ci\njobs:\n  a:\n"
                         "    runs-on: ${{ inputs.runner }}\n    steps:\n"
                         "      - run: x\n"),
        floating_runners("name: ci\njobs:\n  a:\n    runs-on: ${{ matrix.os }}\n"
                         "    steps:\n      - run: x\n"),
        floating_runners("name: ci\non:\n  push:\n"))
    check("ri5 ...a job with no runs-on, one whose label is an expression this "
          "cannot resolve, a matrix reference to a key the matrix does not list, "
          "and a workflow with no `jobs:` block are each NAMED, never an empty "
          "list over a question nobody could ask: %r" % (unreadable,),
          [j for j, _w in unreadable[0]["findings"]] == ["a"]
          and [j for j, _w in unreadable[1]["findings"]] == ["a"]
          and [j for j, _w in unreadable[2]["findings"]] == ["a"]
          and unreadable[3]["problem"] is not None
          and unreadable[3]["jobs"] == 0)

    with io.open(os.path.join(REPO, CI_REL), encoding="utf-8") as fh:
        live = floating_runners(fh.read())
    check("ri6 THE LIVE CLAIM: no job in ci.yml and no value of a matrix it "
          "crosses is a floating label, over %d job(s) read - the count keeps a "
          "workflow nobody parsed from reading as clean: %r"
          % (live["jobs"], live),
          live["problem"] is None and live["findings"] == [] and live["jobs"] > 0
          and runner_image_verdict() == [] and parity()["runner_images"] == [])

    absent = runner_image_verdict(os.path.join(REPO, "no-such-repo-dir"))
    check("ri7 a tree with no workflow in it is a NAMED finding, so the verdict "
          "`parity()` renders cannot come back clean over a file nobody read: %r"
          % (absent,),
          len(absent) == 1 and "could not be read" in absent[0][1])

    # The axis written as a BLOCK sequence. Read as nothing, its floating value was
    # invisible and the `include` row naming the same key made the list non-empty,
    # so the job passed over a label no diff would have caught moving.
    block = floating_runners(_RI_BLOCK % ("windows-latest", "ubuntu-24.04"))
    block_ok = floating_runners(_RI_BLOCK % ("windows-2025", "ubuntu-24.04"))
    block_inc = floating_runners(_RI_BLOCK % ("windows-2025", "ubuntu-latest"))
    check("ri8 ...a matrix axis written as a block sequence is read as the inline "
          "list is: a floating value in it is reported beside an `include` row "
          "naming the same key, the same workflow pinned is clean (the over-fire "
          "direction), and a floating `include` value is still reported: "
          "%r / %r / %r" % (block["findings"], block_ok["findings"],
                            block_inc["findings"]),
          [j for j, _w in block["findings"]] == ["cells"]
          and "windows-latest" in block["findings"][0][1]
          and block_ok["findings"] == []
          and [j for j, _w in block_inc["findings"]] == ["cells"]
          and "ubuntu-latest" in block_inc["findings"][0][1])

    unread = (
        floating_runners(_RI_BLOCK_RAW % "          - ${{ fromJSON(inputs.os) }}\n"),
        floating_runners(_RI_BLOCK_RAW % ""),
        floating_runners(
            _RI_BLOCK_RAW % "          - windows-2025\n          - ubuntu-24.04\n"
            ).get("findings"))
    check("ri9 ...a matrix value this cannot read - an expression, a key with no "
          "value under it - is NAMED for its job, never dropped; a readable block "
          "is not reported: %r" % (unread,),
          [j for j, _w in unread[0]["findings"]] == ["cells"]
          and "cannot read" in unread[0]["findings"][0][1]
          and [j for j, _w in unread[1]["findings"]] == ["cells"]
          and "cannot read" in unread[1]["findings"][0][1]
          and unread[2] == [])

    named = floating_runners(_RI_NAMED % "selftests (${{ matrix.os }}, a)")
    named_lit = floating_runners(_RI_NAMED % "e2e (windows-2025)")
    named_clean = floating_runners(
        _RI_NAMED % "selftests (${{ startsWith(matrix.os, 'windows') && "
                    "'windows' || 'linux' }}, a)")
    check("ri10 ...and a job's display name carries no runner image: the matrix "
          "key `runs-on` reads, or a literal label, in `name:` is reported; a name "
          "derived from the family is not: %r / %r / %r"
          % (named["findings"], named_lit["findings"], named_clean["findings"]),
          [j for j, _w in named["findings"]] == ["cells"]
          and "display name" in named["findings"][0][1]
          and [j for j, _w in named_lit["findings"]] == ["cells"]
          and "display name" in named_lit["findings"][0][1]
          and named_clean["findings"] == [])

    with io.open(os.path.join(REPO, CI_REL), encoding="utf-8") as fh:
        live_names = image_in_job_names(fh.read())
    check("ri11 THE LIVE CLAIM, names: no job in ci.yml names its runner image in "
          "its display name, so the next image move renames no check: %r"
          % (live_names,), live_names == [])


# A `verify.sh` fragment in the two shapes the real one has: `ruff` on one line and
# `vermin` spread over two with a `\\` continuation, between comment lines that name
# both tools and so must not be read as an invocation.
_LD_GOOD = (
    "# ruff check is run below, and vermin -t=3.8- after it\n"
    "slice_lint() {\n"
    "  run \"ruff\" ruff check plugins/audit tools tests\n"
    "  run \"vermin (3.8 floor)\" vermin -t=3.8- --no-tips --violations \\\n"
    "    plugins/audit/scripts plugins/audit/hooks tests tools/lints\n"
    "}\n")
_LD_OLD = _LD_GOOD.replace("tests tools/lints", "plugins/audit/tests")


def _lint_dir_cases(check):
    good = lint_dir_findings(_LD_GOOD)
    check("ld1 the two directory lists name the suites at the repository root and "
          "the lint modules under tools/lints, and a `\\` continuation is read as "
          "part of its command: %r" % (good,),
          good == {"findings": [], "read": ["ruff", "vermin"]})

    old = lint_dir_findings(_LD_OLD)
    check("ld2 the lists as they stood before the move - vermin naming the "
          "suite directory inside the plugin and no tools/lints - are findings "
          "that name the tool and the directory, one for what is missing and "
          "one for the spelling that must not come back: %r" % (old,),
          [tool for tool, _why in old["findings"]] == ["vermin", "vermin", "vermin"]
          and any("tests" in why and "does not cover" in why
                  for _tool, why in old["findings"])
          and any("tools/lints" in why and "does not cover" in why
                  for _tool, why in old["findings"])
          and any("the suites left" in why for _tool, why in old["findings"]))

    # The over-fire direction: a check that demanded every directory be SPELLED,
    # or that flagged the repository root's `tests` for sharing a word with the
    # retired path, goes red on this text and on nothing else here.
    covered = lint_dir_findings(_LD_GOOD.replace("tests tools/lints", "tests tools"))
    check("ld3 `tools` covers `tools/lints`, and `tests` is not the retired "
          "`plugins/audit/tests`: a list that names the parent directory is "
          "clean for vermin, and this names no finding: %r" % (covered,),
          covered["findings"] == [])

    missing = lint_dir_findings(_LD_GOOD.replace("run \"ruff\" ruff check", "run \"ruff\" echo"))
    absent = lint_dir_findings("slice_lint() {\n  run x true\n}\n")
    check("ld4 a runner with no `ruff check` command, or with neither tool, is a "
          "NAMED finding per tool and the tool is not in `read` - an empty list "
          "over a command nobody found would read as a clean one: %r / %r"
          % (missing, absent),
          [t for t, _w in missing["findings"]] == ["ruff"]
          and missing["read"] == ["vermin"]
          and [t for t, _w in absent["findings"]] == ["ruff", "vermin"]
          and absent["read"] == [])

    ruff_old = lint_dir_findings(_LD_GOOD.replace("plugins/audit tools tests",
                                                  "plugins/audit tools"))
    check("ld5 ruff's list without `tests` is a finding of its own, so the check "
          "is not satisfied by vermin's list alone: %r" % (ruff_old,),
          [t for t, _w in ruff_old["findings"]] == ["ruff"]
          and "`tests`" in ruff_old["findings"][0][1])

    check("ld6 THE LIVE CLAIM: this repository's verify.sh points ruff and vermin "
          "at the directories the code lives in, and `parity()` renders that "
          "verdict instead of omitting it: %r" % (lint_dir_verdict(),),
          lint_dir_verdict() == [] and parity()["lint_dirs"] == []
          and lint_dir_findings(io.open(os.path.join(REPO, VERIFY_REL),
                                        encoding="utf-8").read())["read"]
          == ["ruff", "vermin"])

    gone = lint_dir_verdict(os.path.join(REPO, "no-such-repo-dir"))
    check("ld7 a tree with no verify.sh is a NAMED finding, so the verdict "
          "`parity()` renders cannot come back clean over a file nobody read: %r"
          % (gone,),
          len(gone) == 1 and "could not be read" in gone[0][1])


# --- selftest -----------------------------------------------------------------
def _cases(check):
    # --- the runner really runs what the selector names -----------------------
    # F: `--affected` narrowed a run by dropping a gate it could not dispatch and
    # then reported every selected check green. The slice rule cannot see it - the
    # two files disagree about which checks RUN, not about which slices exist.
    _ad = affected_dispatch()
    check("ad0 THE LIVE CLAIM: every command the selector prints for the probe "
          "set is one the runner can dispatch, over %d command(s) against %d "
          "accepted prefix(es) read off the runner itself - and a run that could "
          "not ask the question says so instead of coming back empty: %r / %r"
          % (len(_ad["commands"]), len(_ad["accepted"]), _ad["problem"],
             _ad["undispatchable"]),
          _ad["problem"] is None and _ad["undispatchable"] == [])
    # THE FIXTURE-VALUE CASE, and without it ad0 is green over a command set that
    # never contains the failing shape. `claude plugin validate` is what the
    # dispatcher dropped, and a probe set that stopped emitting it would leave ad0
    # asserting nothing while still passing.
    check("ad1 ...and the probe set really does reach the arm that broke: the "
          "command the dispatcher used to drop is among the ones it emitted, so "
          "ad0 is a claim about that shape rather than about python and node: %r"
          % (_ad["commands"],),
          any(c.startswith("claude plugin validate") for c in _ad["commands"]))
    check("ad2 the accepted prefixes are READ OFF the runner and there is more "
          "than one, so this cannot be a list that agreed on the day it was "
          "written: %r" % (_ad["accepted"],),
          len(_ad["accepted"]) >= 2
          and "python3 " in _ad["accepted"])
    # `ruff check ...` is a real gate of this repo that `--affected` never selects,
    # so it is a command the runner legitimately cannot dispatch - which makes it
    # the honest half of this pair rather than an invented string.
    _made_up = [c for c in ["node tools/x.mjs", "ruff check plugins/audit tools"]
                if not any(c.startswith(p) for p in _ad["accepted"])]
    check("ad3 ...and those prefixes DO refuse something: a command outside them "
          "is rejected while one inside is not, which is the pair that tells ad0 "
          "apart from a comparison nothing can fail: %r" % (_made_up,),
          _made_up == ["ruff check plugins/audit tools"])
    # THE INVENTED TOOL NAMES CARRY THE JAVASCRIPT MODULE EXTENSION, for the reason
    # the fixtures further up this file do: `_refs.tool_basename_drift()` holds that
    # a `.py` basename written anywhere under `tools/` must name a file that exists,
    # and a fixture nobody creates is exactly what a stale reference looks like.
    _steps = steps_in("affected: 1 changed path(s) against HEAD\n"
                      "  tools/x.mjs - a reason indented like a command\n"
                      "\nrun:\n"
                      "  node tools/x.mjs --check\n"
                      "  claude plugin validate plugins/audit\n")
    check("ad4 the step reader takes ONLY what follows `run:` - the selector's "
          "reasons are indented exactly like its commands, which is the "
          "ambiguity that made a catch-all arm impossible and the silent skip "
          "the only shape available: %r" % (_steps,),
          _steps == ["node tools/x.mjs --check",
                     "claude plugin validate plugins/audit"])
    check("ad5 ...and the sentence the selector prints when it selected NOTHING "
          "is not read as a command, while a run with no `run:` section at all "
          "yields nothing rather than the whole document",
          steps_in("run:\n  (nothing - no check covers what changed)\n") == []
          and steps_in("affected: FULL SET required\n"
                       "  x - UNRECOGNISED\n") == [])
    check("ad6 a runner nothing could read is a NAMED problem and not an empty "
          "undispatchable list - the two spell the same way otherwise, and one "
          "of them means the check did not run",
          affected_dispatch(os.path.join(REPO, "no-such-repo-dir"))["problem"]
          is not None)

    # THE INVENTED GATE NAMES BELOW CARRY THE JAVASCRIPT MODULE EXTENSION, and it is
    # not decoration: `_refs.tool_basename_drift()` holds that a `.py` basename
    # written anywhere under `tools/` must name a file that exists, prose included,
    # and a fixture nobody creates is exactly what a stale reference looks like. That
    # rule's docstring is where the spellings live. Do not "fix" them to the Python
    # extension - the lint will stop the commit, and the thing it is protecting is
    # the rule rather than these names.
    body = _shell_command_lines(
        "# node tools/ghost.mjs\n  ruff check x  # ruff check y\n")
    check("c0 a commented invocation is NOT an invocation, and a trailing "
          "comment is cut - the runner discusses its own commands at length, so "
          "without this the scratch-path and dispatch readers would read every "
          "mention as a command: %r" % (body,),
          body == ["ruff check x"])

    # --- THE GENERAL RULE: every exemption names who audits its reason ---------
    # Two defects were recorded before this existed and both had one shape - a row
    # whose sentence had stopped being true while the row stayed green. Each was
    # fixed with its own instrument; what was missing is the rule that every such
    # table HAS one, so a third instance is a finding rather than a discovery.
    _ea_live = exemption_audit_drift()
    check("ea1 THE LIVE CLAIM: every reason-carrying table in this tree is "
          "classified, and every instrument a row names really exists: %r"
          % (_ea_live,),
          _ea_live == [])
    _ea_tables = exemption_tables()
    check("ea2 ...over a derivation that reached a REAL set, not an empty one - "
          "an empty walk classifies nothing and clears everything, which is the "
          "silence this whole rule exists to refuse. %d tables found, and the "
          "two the classification is made OF are excluded by name because "
          "classifying the classification is a regress"
          % (len(_ea_tables),),
          len(_ea_tables) >= 20
          and "PROSE_SCAN_EXEMPT" in _ea_tables
          and "FIELD_HELP" in _ea_tables,
          repr(sorted(_ea_tables)[:6]))
    # ea2b. A REASON MAY BE SHARED, and this is the case that stops the derivation
    # losing a table the day it is. `_ALWAYS` names its refusal sentences as module
    # constants because the tokenized arm and the regex fallback must give the SAME
    # reason - duplicating the text would be the defect this repo names most often.
    # The literal-only reader dropped it silently, so `ea1` went on reporting a
    # clean classification over a set one table smaller. A fixture proves the
    # resolution rather than the real file alone, because the real file is free to
    # stop sharing and this rule is about the SHAPE.
    _ea_shared = _reason_table_names(
        'WHY_ONE = "a sentence long enough to be a reason and not a label"\n'
        'WHY_TWO = "a second sentence, equally long, equally not a label"\n'
        "SHARED_REASONS = ((1, WHY_ONE), (2, WHY_TWO))\n")
    _ea_unresolvable = _reason_table_names(
        "SHARED_REASONS = ((1, WHY_MISSING), (2, WHY_ALSO_MISSING))\n")
    check("ea2b ...and a table whose sentences are module CONSTANTS rather than "
          "literals is still one, because a reason two readers share may not be "
          "written twice - while a name that resolves to nothing is NOT a reason "
          "table, so the resolution cannot become a way in for any tuple: %r / %r"
          % (_ea_shared, _ea_unresolvable),
          _ea_shared == ["SHARED_REASONS"] and _ea_unresolvable == []
          and "_ALWAYS" in _ea_tables)
    _ea_expect = sorted(set(_ea_tables) - {"AUDITED_EXEMPTIONS",
                                           "NOT_AN_EXEMPTION"})
    check("ea3 a table in NEITHER classification is reported, which is how one "
          "added later cannot opt out by being forgotten - EVERY derived table "
          "except the two the classification is made of",
          [n for n, _w in exemption_audit_drift(
              audited={}, not_exemptions={})] == _ea_expect,
          repr([n for n, _w in exemption_audit_drift(
              audited={}, not_exemptions={})][:4]))
    _ea_ghost = exemption_audit_drift(
        audited=dict(AUDITED_EXEMPTIONS, GONE_TABLE=("live", "x")),
        not_exemptions=NOT_AN_EXEMPTION)
    check("ea4 ...and a row for a table that no longer exists is reported too - "
          "the other direction, without which the table becomes the place a "
          "retired excuse goes to keep being green: %r"
          % ([n for n, _w in _ea_ghost],),
          [n for n, _w in _ea_ghost] == ["GONE_TABLE"])
    _ea_noinst = exemption_audit_drift(
        audited=dict(AUDITED_EXEMPTIONS,
                     CONTRAST_EXEMPTIONS=("live", "no_such_auditor_anywhere")),
        not_exemptions=NOT_AN_EXEMPTION)
    check("ea5 ...and an instrument that does not exist is reported, which is "
          "what stops this table being the shape NOT_A_GATE forbids: a row that "
          "silences a finding and can never itself be wrong: %r"
          % ([n for n, _w in _ea_noinst],),
          [n for n, _w in _ea_noinst] == ["CONTRAST_EXEMPTIONS"])
    _ea_case = exemption_audit_drift(
        audited=dict(AUDITED_EXEMPTIONS,
                     KNOWN_LAYER_DEBT=("reason",
                                       "tests/test__deps.py zz9")),
        not_exemptions=NOT_AN_EXEMPTION)
    check("ea6 ...and the same for an auditor named as a CASE, because half this "
          "tree's rules are cases in suites that lint another file's source - a "
          "spelling that could not be checked would be the loophole: %r"
          % ([n for n, _w in _ea_case],),
          [n for n, _w in _ea_case] == ["KNOWN_LAYER_DEBT"])
    _ea_label = exemption_audit_drift(
        audited=AUDITED_EXEMPTIONS,
        not_exemptions=dict(NOT_AN_EXEMPTION, FIELD_HELP="help"))
    check("ea7 ...and a table excused with a LABEL rather than a reason is "
          "reported, for `NOT_A_GATE`'s reason one register over: an excuse "
          "nobody can disagree with is not one: %r" % ([n for n, _w in _ea_label],),
          [n for n, _w in _ea_label] == ["FIELD_HELP"])

    # --- SECURITY.md's fail modes against the wiring that decides them --------
    # The table says, per hook and per event, whether a missing interpreter
    # PROMPTS or passes in silence, and nothing in this tree compared it with the
    # second argument of each registration - the thing that actually decides. It
    # was accurate when this arrived, so these cases start no repair; what they
    # start is the only cheap moment there is to begin holding one.
    _fm = failmode_table_drift()
    check("fm0 THE LIVE CLAIM: every fail mode SECURITY.md documents is the one "
          "`hooks.json` registers, every wired hook+event pair has a row, no row "
          "describes a pair nothing wires any more, and a run that could not ask "
          "the question says so instead of coming back empty - read over %d "
          "row(s), %d documented pair(s) and %d registration(s) against the "
          "launcher's own %r: %r / %r"
          % (len(_fm["rows"]), len(_fm["described"]), len(_fm["wired"]),
             _fm["contract"], _fm["problem"], _fm["findings"]),
          _fm["problem"] is None and _fm["findings"] == []
          and _fm["rows"] != [] and _fm["described"] != [] and _fm["wired"] != [])

    # ...and the property that makes fm0 worth anything about the REAL document.
    # Both shapes below are ones a careless reader loses IN SILENCE, and losing
    # either leaves fm0 green over pairs it never compared.
    _fm_wide = sorted(hook for _l, hook, named, _c in _fm["rows"] if len(named) > 1)
    _fm_cells = {}
    for _hook, _event, _cell in _fm["described"]:
        _fm_cells.setdefault(_hook, set()).add(_cell)
    _fm_split = sorted(h for h in _fm_cells if len(_fm_cells[h]) > 1)
    check("fm1 the document really wears both shapes the parser is built for: a "
          "row whose ONE cell words several events %r, and a script appearing "
          "twice under a parenthetical name with DIFFERENT fail modes %r. A "
          "reader taking the first event of a cell would leave the rest of that "
          "row's pairs described by nothing; one keying by script name alone "
          "would score one of the pair against the other's cell"
          % (_fm_wide, _fm_split),
          _fm_wide != [] and _fm_split != [])

    # A MINIATURE TABLE AND A MINIATURE WIRING, and every name in both is
    # invented: what is under test is that the launcher's tokens are READ, so a
    # fixture spelling the real ones would pass against a rule that had them
    # written in. The hook files borrow the JavaScript extension because the rule
    # strips whatever extension it is handed and cannot tell them apart - a
    # `.py` basename invented under `tools/` is a finding of its own
    # (`_refs.tool_basename_drift()`), and this is the spelling that rule names
    # for a fixture the scanner under test does not open.
    _fmc = {"loud": "PROBE_LOUD", "default": "PROBE_QUIET",
            "decision_event": "ProbeDecide"}
    _fm_events = ("ProbeDecide", "ProbeAfter")
    _fm_table = (
        "| Hook | Event | No interpreter | On internal error |\n"
        "|---|---|---|---|\n"
        "| `probe-one` | ProbeDecide reads | **PROBE_LOUD** (loud) | allow |\n"
        "| `probe-one` (state commit) | ProbeAfter reads | silent | no-op |\n"
        "| `probe-two` | ProbeDecide reads **+ writes**, ProbeAfter writes "
        "| silent | no-op |\n")
    _fm_wiring = (("probe-one", "ProbeDecide", "PROBE_LOUD"),
                  ("probe-one", "ProbeAfter", "PROBE_QUIET"),
                  ("probe-two", "ProbeDecide", "PROBE_QUIET"),
                  ("probe-two", "ProbeAfter", "PROBE_QUIET"))
    _fm_parsed, _fm_parse_why = failmode_rows(_fm_table, _fm_events)
    check("fm2 the parser drops the parenthetical from a hook name and reads "
          "EVERY event a cell words - so one script may carry two fail modes and "
          "one row may cover two pairs: %r / %r"
          % (_fm_parse_why, _fm_parsed),
          _fm_parse_why is None
          and [(hook, named, cell) for _l, hook, named, cell in _fm_parsed]
          == [("probe-one", ("ProbeDecide",), "PROBE_LOUD"),
              ("probe-one", ("ProbeAfter",), "silent"),
              ("probe-two", ("ProbeDecide", "ProbeAfter"), "silent")])

    # THE PAIR. A table and a wiring differing in nothing but one cell's mode.
    # Asserting the flipped one alone would pass against a rule that reported
    # every pair always; asserting the agreeing one alone would pass against a
    # rule that found nothing either way.
    _fm_agree = failmode_findings(_fm_parsed, _fm_wiring, _fmc)
    _fm_flip = failmode_findings(
        failmode_rows(_fm_table.replace("**PROBE_LOUD** (loud)", "silent"),
                      _fm_events)[0], _fm_wiring, _fmc)
    check("fm3 a cell that disagrees with its registration is reported by pair, "
          "with both sides of the disagreement in the note - and the agreeing "
          "table reports nothing, which is the direction that fails if this "
          "starts firing unconditionally: %r vs %r"
          % (_fm_agree, _fm_flip),
          _fm_agree == [] and len(_fm_flip) == 1
          and _fm_flip[0][0] == "probe-one / ProbeDecide"
          and "silent" in _fm_flip[0][1] and "PROBE_LOUD" in _fm_flip[0][1])

    _fm_shrunk = failmode_findings(
        failmode_rows(_fm_table.replace(", ProbeAfter writes", ""),
                      _fm_events)[0], _fm_wiring, _fmc)
    _fm_dead = failmode_findings(_fm_parsed, _fm_wiring[:3], _fmc)
    check("fm4 THE SECOND DIRECTION, which is what makes the first worth "
          "anything: a wired pair NO row describes is reported %r, so deleting a "
          "row cannot make the table agree with itself - and a row describing a "
          "pair nothing wires any more is reported too %r, because an account of "
          "a state that has passed stays green for ever"
          % (_fm_shrunk, _fm_dead),
          [s for s, _n in _fm_shrunk] == ["probe-two / ProbeAfter"]
          and "no row of the table describes it" in _fm_shrunk[0][1]
          and [s for s, _n in _fm_dead] == ["probe-two / ProbeAfter"]
          and "has passed" in _fm_dead[0][1])

    _fm_loud_late = failmode_findings(
        _fm_parsed, (("probe-one", "ProbeDecide", "PROBE_LOUD"),
                     ("probe-one", "ProbeAfter", "PROBE_LOUD"),
                     ("probe-two", "ProbeDecide", "PROBE_QUIET"),
                     ("probe-two", "ProbeAfter", "PROBE_QUIET")), _fmc)
    check("fm5 a loud mode asked for on an event with no permission-decision "
          "channel is a finding on its own terms - the launcher's payload names "
          "the one event that has one, so the JSON is printed and ignored and a "
          "guard the table calls blocking blocks nothing. The agreeing wiring "
          "says none of it, which is the same pair the other way: %r / %r"
          % ([n for _s, n in _fm_loud_late if "permission-decision" in n],
             _fm_agree),
          any("permission-decision channel" in n for _s, n in _fm_loud_late)
          and not any("permission-decision" in n for _s, n in _fm_agree))

    _fm_launcher = ('mode="${2:-PROBE_QUIET}"\n'
                    'if [ "$mode" = "PROBE_LOUD" ]; then\n'
                    '  printf \'{"hookSpecificOutput":{"hookEventName":'
                    '"ProbeDecide"}}\'\n'
                    'fi\n'
                    'exit 0\n')
    _fm_read, _fm_read_why = launcher_contract(_fm_launcher)
    _fm_no_default = launcher_contract(
        _fm_launcher.replace('mode="${2:-PROBE_QUIET}"', 'mode="$2"'))[1]
    _fm_no_loud = launcher_contract(
        _fm_launcher.replace('"$mode" = "PROBE_LOUD"', '"$mode" = "$3"'))[1]
    _fm_no_event = launcher_contract(
        _fm_launcher.replace("hookEventName", "hookEventNamed"))[1]
    check("fm6 the tokens every comparison above turns on are READ off the "
          "launcher - the default a registration gets by writing none, the one "
          "that produces a prompt, and the event whose channel that prompt uses "
          "- and a launcher missing any of them is a NAMED problem rather than a "
          "usable-looking default: %r / %r / %r / %r"
          % (_fm_read, _fm_no_default, _fm_no_loud, _fm_no_event),
          _fm_read_why is None
          and _fm_read == {"loud": "PROBE_LOUD", "default": "PROBE_QUIET",
                           "decision_event": "ProbeDecide"}
          and "default mode" in (_fm_no_default or "")
          and "produces a prompt" in (_fm_no_loud or "")
          and "hookEventName" in (_fm_no_event or ""))

    _fm_json = ('{"hooks": {"ProbeDecide": [{"matcher": "X", "hooks": ['
                '{"type": "command", "command":'
                ' "sh \\"${R}/hooks/py-launch.sh\\" probe-one.mjs PROBE_LOUD"},'
                '{"type": "command", "command":'
                ' "sh \\"${R}/hooks/py-launch.sh\\" probe-two.mjs"},'
                '{"type": "command", "command": "node probe-three.mjs"}]}]}}')
    _fm_reg = hook_registrations(_fm_json, "PROBE_QUIET")
    _fm_bad_json = hook_registrations("{not json", "PROBE_QUIET")["problem"]
    _fm_no_hooks = hook_registrations('{"other": {}}', "PROBE_QUIET")["problem"]
    check("fm7 a registration that writes NO mode token gets the launcher's "
          "DEFAULT rather than none - a hook with no token still has a fail mode "
          "- the event vocabulary comes off the registration file rather than a "
          "list written here, and a command that never reaches the launcher is "
          "reported rather than skipped, as is a file that cannot be read as a "
          "registration at all: %r / %r / %r"
          % (_fm_reg, _fm_bad_json, _fm_no_hooks),
          _fm_reg["problem"] is None
          and _fm_reg["wired"] == [("probe-one", "ProbeDecide", "PROBE_LOUD"),
                                   ("probe-two", "ProbeDecide", "PROBE_QUIET")]
          and [e for e, _c in _fm_reg["unlaunched"]] == ["ProbeDecide"]
          and _fm_reg["events"] == ("ProbeDecide",)
          and "does not parse as JSON" in (_fm_bad_json or "")
          and "registers nothing" in (_fm_no_hooks or ""))

    _fm_absent = failmode_table_drift(os.path.join(REPO, "no-such-repo-dir"))
    _fm_absent_verdict = failmode_table_verdict(os.path.join(REPO, "no-such-repo-dir"))
    _fm_tableless = failmode_rows("nothing here is a table\n", _fm_events)[1]
    check("fm8 a tree with none of those files in it, and a document with no "
          "such table in it, are NAMED problems rather than a comparison that "
          "agrees with nothing - and `parity()` raises the problem TO a finding, "
          "so the verdict cannot come back clean over a question nobody could "
          "ask: %r / %r / %r"
          % (_fm_absent["problem"], _fm_tableless, _fm_absent_verdict),
          _fm_absent["problem"] is not None and _fm_absent["findings"] == []
          and _fm_tableless is not None
          and len(_fm_absent_verdict) == 1
          and _fm_absent_verdict[0][1] == _fm_absent["problem"])

    with io.open(os.path.join(REPO, CI_REL), encoding="utf-8") as fh:
        _jt_live = untimed_jobs(fh.read())
    check("jt0 THE LIVE CLAIM: every job in ci.yml carries a job-level time "
          "bound, over %d job(s) read - the count is what keeps an empty finding "
          "list over a workflow nobody parsed from reading as clean: %r"
          % (_jt_live["jobs"], _jt_live),
          _jt_live["problem"] is None and _jt_live["findings"] == []
          and _jt_live["jobs"] > 0 and job_timeout_verdict() == [])

    # The fixture's bound sits on a STEP of the untimed job: a reader that took
    # any `timeout-minutes` inside a job's block for the job's own passes it.
    _jt_wf = ("name: ci\non:\n  push:\njobs:\n"
              "  timed:\n    name: timed\n    timeout-minutes: 30\n"
              "    runs-on: ubuntu-latest\n    steps:\n      - run: |\n"
              "          echo hi\n"
              "  untimed:\n    name: untimed\n    runs-on: ubuntu-latest\n"
              "    steps:\n      - name: one step\n        timeout-minutes: 5\n"
              "        run: echo hi\n")
    _jt_red = untimed_jobs(_jt_wf)
    check("jt1 a job with no job-level bound IS reported, by name, and a bound on "
          "one of its STEPS does not count for the job, while its timed sibling "
          "is not reported: %r" % (_jt_red,),
          _jt_red["problem"] is None and _jt_red["jobs"] == 2
          and [job for job, _why in _jt_red["findings"]] == ["untimed"])

    # The over-fire direction: a reader that reported every job, or that read
    # the first job's key depth as every job's, fails this one.
    _jt_ok = untimed_jobs(_jt_wf.replace(
        "  untimed:\n    name: untimed\n",
        "  untimed:\n    name: untimed\n    timeout-minutes: 10\n"))
    check("jt2 ...and the same workflow with that job bounded is clean, over both "
          "jobs: %r" % (_jt_ok,),
          (_jt_ok["findings"], _jt_ok["jobs"], _jt_ok["problem"]) == ([], 2, None)
          and _jt_ok["bounds"] == {"timed": 30, "untimed": 10})

    _jt_zero = untimed_jobs(_jt_wf.replace("timeout-minutes: 30",
                                           "timeout-minutes: 0"))
    _jt_expr = untimed_jobs(_jt_wf.replace(
        "timeout-minutes: 30", "timeout-minutes: ${{ inputs.minutes }}"))
    check("jt3 a bound of zero, or one written as an expression this cannot "
          "resolve, is reported rather than taken on trust: %r / %r"
          % (_jt_zero["findings"], _jt_expr["findings"]),
          [job for job, _w in _jt_zero["findings"]] == ["timed", "untimed"]
          and [job for job, _w in _jt_expr["findings"]] == ["timed", "untimed"])

    with io.open(os.path.join(REPO, CI_REL), encoding="utf-8") as fh:
        _jb_live_text = fh.read()
    _jb_live = job_bound_evidence(_jb_live_text)
    _jb_lines = _LONGEST_LINE.findall(_jb_live_text)
    check("jb0 THE LIVE CLAIM: every bounded job in ci.yml carries one `longest` "
          "line and a bound at least %d and at most %d times it (or the floor), "
          "over %d such line(s) read: %r"
          % (BOUND_FACTOR, BOUND_CEILING_FACTOR, len(_jb_lines), _jb_live),
          _jb_live == [] and len(_jb_lines) == _jt_live["jobs"])

    # A fixture whose bound is just under, at, and just over twice its figure:
    # 49m58s needed for 24m59s, so 49 is red and 50 is green - a factor read as
    # 1, or a comparison against minutes instead of seconds, moves the line.
    _jb_wf = ("name: ci\njobs:\n"
              "  one:\n    timeout-minutes: %s\n    runs-on: x\n"
              "  two:\n    timeout-minutes: 5\n    runs-on: x\n")
    _jb_rows = "# measured\n#   longest one: 24m59s (run 1)\n#   longest two: 1m12s (run 1)\n"
    _jb_under = job_bound_evidence(_jb_rows + _jb_wf % "49")
    _jb_over = job_bound_evidence(_jb_rows + _jb_wf % "50")
    check("jb1 a bound under twice its recorded longest run IS reported, naming "
          "the job and the minutes it needed, and the same job one minute over "
          "is clean - the direction a check firing on every bound fails: %r / %r"
          % (_jb_under, _jb_over),
          [job for job, _w in _jb_under] == ["one"]
          and "49m58s needed" in _jb_under[0][1] and _jb_over == [])

    _jb_bare = job_bound_evidence(_jb_wf % "50")
    _jb_ghost = job_bound_evidence(_jb_rows + "#   longest gone: 1m00s (run 1)\n"
                                   + _jb_wf % "50")
    _jb_twice = job_bound_evidence(_jb_rows + "#   longest one: 24m59s (run 2)\n"
                                   + _jb_wf % "50")
    check("jb2 a bound with no `longest` line is reported (a figure set by feel "
          "is the defect), as is a line for a job the workflow does not have and "
          "a job measured twice: %r / %r / %r" % (_jb_bare, _jb_ghost, _jb_twice),
          [job for job, _w in _jb_bare] == ["one", "two"]
          and [job for job, _w in _jb_ghost] == ["gone"]
          and [job for job, _w in _jb_twice] == ["one"])

    _jb_tree = tempfile.mkdtemp(prefix="gate-parity-jb-")
    try:
        os.makedirs(os.path.dirname(os.path.join(_jb_tree, CI_REL)))
        with io.open(os.path.join(_jb_tree, CI_REL), "w", encoding="utf-8") as fh:
            fh.write(_jb_rows + _jb_wf % "49")
        _jb_verdict = job_timeout_verdict(_jb_tree)
    finally:
        shutil.rmtree(_jb_tree, ignore_errors=True)
    check("jb3 ...and the verdict `parity()` renders carries that finding, so an "
          "under-twice bound fails the command and not only this function: %r"
          % (_jb_verdict,),
          [job for job, _w in _jb_verdict] == ["one"])

    # The other direction: 74m57s is three times 24m59s, so 74 is clean and 75
    # is over; a sub-minute job may sit at the five-minute floor and not past it.
    _jb_cap = [job_bound_evidence(_jb_rows + (_jb_wf % m).replace(
        "timeout-minutes: 5\n", "timeout-minutes: %s\n" % (t,)))
        for m, t in (("74", "5"), ("75", "5"), ("74", "6"))]
    check("jb4 a bound MORE than three times its longest run - or, for a job "
          "whose three times is under five minutes, past five minutes - is "
          "reported too, since a hung job holds its runner until the bound: "
          "%r" % (_jb_cap,),
          _jb_cap[0] == []
          and [job for job, _w in _jb_cap[1]] == ["one"]
          and "74m57s allowed" in _jb_cap[1][0][1]
          and [job for job, _w in _jb_cap[2]] == ["two"]
          and "5m00s allowed" in _jb_cap[2][0][1])

    _jt_none = untimed_jobs("name: ci\non:\n  push:\n")
    _jt_absent = job_timeout_verdict(os.path.join(REPO, "no-such-repo-dir"))
    _jt_tree = tempfile.mkdtemp(prefix="gate-parity-jt-")
    try:
        os.makedirs(os.path.dirname(os.path.join(_jt_tree, CI_REL)))
        with io.open(os.path.join(_jt_tree, CI_REL), "w", encoding="utf-8") as fh:
            fh.write("name: ci\non:\n  push:\n")
        _jt_jobless = job_timeout_verdict(_jt_tree)
    finally:
        shutil.rmtree(_jt_tree, ignore_errors=True)
    check("jt4 a workflow with no `jobs:` block, and a tree with no workflow at "
          "all, are NAMED problems - and the verdict raises each to a finding, "
          "so `parity()` cannot come back clean over a file nobody read: "
          "%r / %r / %r" % (_jt_none, _jt_jobless, _jt_absent),
          _jt_none["problem"] is not None and _jt_none["jobs"] == 0
          and _jt_jobless == [("ci.yml", _jt_none["problem"])]
          and len(_jt_absent) == 1 and "could not be read" in _jt_absent[0][1])

    _verify_cleanup_cases(check)
    _slice_cases(check)
    _ci_shape_cases(check)
    _verify_slice_run_cases(check)
    _runner_image_cases(check)
    _lint_dir_cases(check)

    # The verdict behind vsh5, in all its corners. The dash rows are the ones
    # that must stay red: a dash that left nothing is a control that stopped
    # working, not a machine without one. The no-dash row that skips is the
    # over-fire direction - a verdict that always failed would pass every row but it.
    _rt = [(d, n, h, return_trap_verdict(d, n, h))
           for d in (True, False) for n in (0, 1, 2) for h in (True, False)]
    _rt_want = {(d, n, h): ("control" if n == 1 else
                            "skip" if (not d and n == 0 and h) else "fail")
                for d in (True, False) for n in (0, 1, 2) for h in (True, False)}
    check("vsh10 the RETURN-trap control skips only with no dash on PATH, a shell "
          "that honours the trap when probed and no directory left; dash with "
          "nothing left, a shell with nothing left that does not honour the trap, "
          "and two directories all fail: %r"
          % ([r for r in _rt if _rt_want[r[:3]] != r[3]],),
          all(_rt_want[r[:3]] == r[3] for r in _rt)
          and return_trap_verdict(True, 0, True) == "fail"
          and return_trap_verdict(False, 0, True) == "skip")
    # The probe reads what the shell PRINTS, so two stub "shells" separate its
    # verdicts on any machine: one that prints the word, one that prints nothing.
    # The stubs are Python programs handed to the interpreter running this suite,
    # because a file starting with a shell shebang is not a program Windows can
    # start at all.
    _rt_root = tempfile.mkdtemp(prefix="return-trap-probe-")
    try:
        _rt_stubs = {}
        for _name, _body in (("says", "print('honoured')\n"),
                             ("silent", "pass\n")):
            _rt_stubs[_name] = os.path.join(_rt_root, _name + ".py")
            with io.open(_rt_stubs[_name], "w", encoding="utf-8", newline="\n") as fh:
                fh.write(_body)
        _rt_run = (sys.executable,)
        _rt_says = return_trap_honoured(_rt_stubs["says"], _rt_run)
        _rt_silent = return_trap_honoured(_rt_stubs["silent"], _rt_run)
        # A file the OS cannot start as a program: a plain text file with no
        # execute bit raises an OSError on posix, and starting an extensionless
        # path raises an OSError on Windows too, so the probe's OSError path is
        # reachable on both. Which error it is differs and the case does not read it.
        _rt_dead = os.path.join(_rt_root, "not-a-program")
        with io.open(_rt_dead, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("echo honoured\n")
        os.chmod(_rt_dead, 0o644)
        _rt_ok = return_trap_probe(_rt_stubs["says"], _rt_run)
        try:
            _rt_gone = return_trap_probe(_rt_dead)
            _rt_gone_bool = return_trap_honoured(_rt_dead)
            _rt_raised = None
        except OSError as exc:
            _rt_gone = _rt_gone_bool = None
            _rt_raised = exc
    finally:
        from _suite import remove_tree
        remove_tree(_rt_root)
    check("vsh11 the direct probe reads the shell's own answer: a shell that prints "
          "the trap's word is honoured and one that prints nothing is not: %r / %r"
          % (_rt_says, _rt_silent), _rt_says is True and _rt_silent is False)
    check("vsh14 (inline --selftest) return_trap_honoured over stubs that are not "
          "shell scripts runs on every OS - the stub is a Python program run "
          "through the interpreter, so no shebang is needed and the probe ran "
          "(reason None): %r" % (_rt_ok,),
          _rt_ok == (True, None) and _rt_says is True and _rt_silent is False)
    check("vsh15 (inline --selftest) an OSError from the program is recorded as a "
          "failed case instead of ending the selftest body - the probe answers "
          "False with the reason named, return_trap_honoured stays a plain False, "
          "and this case itself ran: raised=%r probe=%r bool=%r"
          % (_rt_raised, _rt_gone, _rt_gone_bool),
          _rt_raised is None and _rt_gone is not None
          and _rt_gone[0] is False and "OSError" in (_rt_gone[1] or "")
          and _rt_gone_bool is False)
    _rt_dash = shutil.which("dash")
    if _rt_dash is None:
        from _harness import skip
        skip(check, "vsh12", "no dash on PATH, so dash's own refusal of the RETURN "
             "trap is not probed", _rt_dash is None)
    else:
        # The probe's own answer, not the boolean: a dash that cannot be started is
        # also False, and that would satisfy the boolean without the shell ever
        # having been asked. A reason of None is the probe having run.
        _rt_dash_probe = return_trap_probe(_rt_dash)
        check("vsh12 dash rejects the RETURN trap when probed directly, so no dash "
              "machine can reach the skip - the probe ran (reason None) and the "
              "shell refused the trap: %r on %r" % (_rt_dash_probe, _rt_dash),
              _rt_dash_probe == (False, None))


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
