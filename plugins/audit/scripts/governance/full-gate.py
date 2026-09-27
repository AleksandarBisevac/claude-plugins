#!/usr/bin/env python3
"""The one command of the third place: a pre-push hook's whole obligation.

WHY IT EXISTS. `run-test-gate.py --full --record` is the one measurement
`meta.fullGate` deserves - the whole product, not one phase's or one task's
claim - but a pre-push hook or a CI step should not have to spell that
sentence out itself, refuse a phase argument beside `--full`, or decide what
a plan with no third place declared means. This file is that decision, made
once: run the real command as a SUBPROCESS (an entry point may not import
another entry point - `_deps.KNOWN_LAYER_DEBT` is the list of the rare
exceptions and this is not one), stream what it prints, and exit with its
code.

THE ONE BRANCH THIS FILE DECIDES FOR ITSELF. With no `meta.fullGate`
declared, `run-test-gate.py --full` refuses (exit 2 - a phase-scope caller
asking for a run with nothing to run is a usage error). A pre-push hook is
not that caller: a plan that never declared a third place must not block
every push from every contributor, forever, over a gate nobody asked for.
So THIS file reads `meta.fullGate` itself, before invoking anything, and
answers with the sentence and exit 0 rather than letting the runner's own
usage refusal reach an operator's shell as a blocked push. Read directly
off the manifest dict rather than through `_evidence_io.resolved_commands`:
that function also resolves aliases and couplings, which is a question
about WHAT the third place runs, and this file only asks whether one is
declared at all - the identical presence check `run-test-gate.py`'s own
`_run_full` makes one line above calling `resolved_commands` in the first
place.

THE RED BRANCH LEARNS, AND STILL BLOCKS. After the runner exits non-zero,
this file reads the row it recorded (`_evidence_io.row_by_run`, with the run
id off the runner's own `evidence: recorded` line) and files what the run
taught through `audit-task.py`, as subprocesses: a `couple` and a `bug-add`
for each `selectionMiss` entry, and a `couple --caught` for each suite the
plan already coupled that the runner named failing and the row does not list
as a miss of its own. Each verb's own output
is printed and its exit code named. The exit stays the runner's: a learned
miss is still a red run, and the push it was guarding is still refused.

WHAT IT NEVER ACTS ON. A green run (the runner's exit is the verdict, not
whatever a row says). A run the runner said it did NOT record - a row the
ledger holds for that head is some other run's. A failure the runner did not
NAME: every miss is re-checked against `_evidence_io.named_failing_suites`,
the one reading of "named", so a suite read off a tail of output is reported
as not learned rather than coupled. A miss whose `sources` the row CUT
(`sourcesDropped`): coupling a suite to a prefix of what it depends on is a
narrowing nobody would see, so the bug is filed saying so and pointing at the
plan, where the full list is the tasks' own files. And a miss an OPEN bug
already tracks, or a coupling that already covers every source named - a
push retried on the same red would otherwise file the same bug each time.

A RUN RECORDED ELSEWHERE IS LEARNED FROM AFTER IT IS IMPORTED. A CI build
records into its own shard and learning there would write into a checkout the
build throws away, so `--learn-from <runId>` runs NOTHING: it reads that row
from this checkout's ledger (`_evidence_io.row_by_run`) and hands it to
`learn_from_row`, the same function the red branch calls - the rules above are
stated once. It refuses a run id the ledger does not hold (naming any ledger
file it could not read in full), a row that is not full scope, and a green
row. `import-evidence.py` prints this command for each red full row it brings
in.

Usage:
  full-gate.py <manifest> [--writer NAME] [--project-dir DIR]
  full-gate.py <manifest> --learn-from RUNID [--project-dir DIR]

Exit codes:
  0  no meta.fullGate declared (nothing to run), or the full run was green;
     with --learn-from, the learning ran - even when it filed nothing
  1  the full run was red - whether or not a miss was learned from it; with
     --learn-from, the row was refused, the ledger could not be read, a
     learning verb failed, or the learning raised
  2  usage error (--learn-from beside --writer), or the manifest will not load

A verb that fails while learning from a run this file made is printed with its
exit code and does not change this file's own: the runner's verdict is the
only one it reports. With --learn-from there is no runner's verdict, so a
failed verb is the answer.

This module carries no `--selftest` of its own; its cases live in
plugins/audit/tests/test_full_gate.py.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import os
import sys
import time

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

import _loader  # noqa: E402  (script_path: resolves run-test-gate.py and
#                              audit-task.py by basename, never loads either -
#                              the subprocess boundary below is exactly why
#                              those edges are not counted by `_deps`)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _evidence_io as _ev  # noqa: E402  (row_by_run, named_failing_suites)
import _status_facts  # noqa: E402  (CLOSED_BUG: the one reading of "not open")

# --- delegating the run -----------------------------------------------------------
E_OK, E_FAIL, E_USAGE = 0, 1, 2

PREFIX = "[full-gate]"

NO_THIRD_PLACE = (
    "%s no meta.fullGate declared - this plan names no third place, so "
    "nothing here blocks the push" % (PREFIX,))


def declares_full_gate(manifest):
    """True when `meta.fullGate` names at least one entry.

    THE SAME PRESENCE CHECK `run-test-gate.py`'s own `_run_full` makes
    (`entries = (meta.get("fullGate") or [])`), read here rather than through
    `_evidence_io.resolved_commands` - that function also resolves aliases and
    couplings, a question about WHAT the third place runs, while this file
    only asks whether one is declared before deciding whether to invoke the
    runner at all.
    """
    entries = ((manifest.get("meta") or {}).get("fullGate") or [])
    return bool(entries)


def _stream_subprocess(cmd, out):
    """Run `cmd`, printing every line of its combined output as it arrives,
    and return its exit code.

    THE SEAM. A test replaces this function rather than the subprocess module
    itself, so a fixture can hand back canned lines and an exit code without
    a real child process - the same shape `derive-phase-gate.py`'s `_spawn`
    is replaced by in its own tests. Combined stdout+stderr, unbuffered line
    by line, because the point of streaming at all is that an operator
    watching a pre-push hook sees the runner's own progress rather than a
    silence followed by one final verdict.
    """
    import subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        for line in proc.stdout:
            out(line.rstrip("\n"))
    finally:
        proc.stdout.close()
    return proc.wait()


def _run_full_gate(manifest_path, writer, project_dir, out):
    """Build and run the one delegated command, returning its exit code.

    NEVER RE-IMPLEMENTS THE RUN. Every flag here is `run-test-gate.py`'s own:
    `--full --record` is the measurement this file exists to make easy to
    reach, and `--writer`/`--project-dir` pass through unchanged rather than
    being re-parsed and re-validated a second time by a second parser that
    could drift from the first.
    """
    cmd = [sys.executable, _loader.script_path("run-test-gate.py"),
          manifest_path, "--full", "--record"]
    if writer:
        cmd += ["--writer", writer]
    if project_dir:
        cmd += ["--project-dir", project_dir]
    return _stream_subprocess(cmd, out)


# --- learning from a red run ----------------------------------------------------
# The runner prints exactly one of these for a `--record` run, and the run id
# after the first is the only pointer to the row this run wrote.
RECORDED_MARK = "evidence: recorded "
NOT_RECORDED_MARK = "evidence: NOT recorded"


def bug_title(test):
    """The title of the bug a selection miss files - the runner's own remedy
    spells the same one, pinned by a case, so a bug pasted from that line and
    one filed here read as the same bug."""
    return "SELECTION MISS: %s" % (test,)


def bug_description(miss, run_id, head):
    """The sentence the runner's remedy files as the bug's description."""
    return ("full run %s at %s failed %s, and no derived sign-off gate in %s "
            "listed it" % (run_id, head, miss.get("test"),
                           ", ".join(miss.get("phases") or [])))


def recorded_run(lines):
    """`(state, value)` read off the runner's printed lines: `("recorded",
    runId)`, `("not-recorded", the runner's line)`, or `(None, None)` when
    neither line was printed."""
    for line in lines:
        text = line.strip()
        if text.startswith(RECORDED_MARK):
            return "recorded", text[len(RECORDED_MARK):].strip()
        if text.startswith(NOT_RECORDED_MARK):
            return "not-recorded", text
    return None, None


def start_moment(now=None):
    """The moment a run starts, in epoch seconds FLOORED TO THE WHOLE SECOND:
    the runner stamps a row's `ts` at whole-second precision, so an unfloored
    start taken later within the same second would read this run's own row
    as earlier than the run."""
    return float(int(time.time() if now is None else now))


def _moment_text(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _newest_full_since(rows, started):
    """The newest full row stamped at or after `started` (epoch seconds) -
    this run's, when the runner printed no evidence line at all.

    BOUNDED BY THE MOMENT rather than by the head: an earlier full run at the
    same head would otherwise be read as this one and its miss filed a second
    time. COMPARED AS MOMENTS, never as text, through `_evidence_io`'s own
    `stamp_moment` and `newest_row` - the one moment read and the one order
    the ledger's readers share - because a fractional second or an offset
    spelling sorts differently as a string than it falls in time. A `ts` that
    names no moment is not since anything."""
    since = [r for r in rows or [] if isinstance(r, dict)
             and r.get("scope") == _ev.FULL_SCOPE
             and _stamped_since(r, started)]
    return _ev.newest_row(since)


def _stamped_since(row, started):
    moment = _ev.stamp_moment(row.get("ts"))
    return moment is not None and moment >= started


def find_row(rows, lines, started):
    """`(row, why)` - the row this run recorded, or None and the sentence
    saying why nothing can be acted on."""
    state, value = recorded_run(lines)
    if state == "not-recorded":
        return None, ("the runner printed %r, so there is no row of this run "
                      "to learn from; a row the ledger holds is some other "
                      "run's" % (value,))
    if state == "recorded":
        row = _ev.row_by_run(rows, value)
        if row is None:
            return None, ("the runner printed that it recorded %s, and the "
                          "evidence ledger holds no row with that id" % (value,))
        return row, None
    row = _newest_full_since(rows, started)
    if row is None:
        return None, ("the runner printed no evidence line, and the ledger "
                      "holds no full row stamped since %s"
                      % (_moment_text(started),))
    return row, None


def _couple_skip(miss, run_id, head, coupled):
    """Why a miss is not coupled, or None when it should be."""
    test, sources = miss.get("test"), list(miss.get("sources") or [])
    phases = ", ".join(miss.get("phases") or []) or "no named phase"
    if miss.get("sourcesDropped"):
        return ("no couple for %s: run %s's selectionMiss keeps only the "
                "first %d of its sources (sourcesDropped: %s), and coupling "
                "the suite to that prefix would narrow it silently; the full "
                "list is the files of the tasks of %s in the plan"
                % (test, run_id, len(sources), miss.get("sourcesDropped"),
                   phases))
    if not sources:
        return ("no couple for %s: the tasks of %s declare no files to "
                "couple it to (run %s)" % (test, phases, run_id))
    if not head:
        return ("no couple for %s: run %s records no head, and a coupling "
                "names the head that taught it" % (test, run_id))
    held = coupled.get(test)
    if held is not None and all(s in held for s in sources):
        return ("no couple for %s: meta.coupling already couples it to "
                "every source run %s names" % (test, run_id))
    return None


def _described(miss, run_id, head):
    """The bug's description: the runner's sentence, plus what the row cut."""
    text = bug_description(miss, run_id, head)
    if miss.get("sourcesDropped"):
        text += (". Not coupled: the row keeps only the first %d sources "
                 "(sourcesDropped: %s); the full list is the files of the "
                 "tasks of those phases in the plan"
                 % (len(miss.get("sources") or []), miss["sourcesDropped"]))
    if miss.get("phasesDropped"):
        text += (". The row keeps only the phases named (phasesDropped: %s)"
                 % (miss["phasesDropped"],))
    return text


def learning_plan(row, coupled, open_titles):
    """What a red row teaches: `{"verbs": [(label, test, argv)], "notes":
    [line]}`.

    `coupled` maps each test the plan already couples to its sources, read
    BEFORE anything here writes - so a suite coupled by this run is not also
    credited with a catch by it. `open_titles` maps an open bug's title to
    its id. Pure: nothing is run and nothing is read.

    EVERY MISS IS RE-ASKED, never trusted off the row: a suite counts only
    when a step whose runner NAMED its failing suites names it
    (`_evidence_io.named_failing_suites`), so a failure read off a tail of
    output is a note, never a verb."""
    run_id = str(row.get("runId") or "")
    head = (row.get("testedState") or {}).get("head")
    steps = row.get("steps") or []
    named = _ev.named_failing_suites(steps)
    verbs, notes = [], []
    notes.extend("not learned from run %s: the runner did not name the "
                 "failing suites (basis: %s)" % (run_id, basis)
                 for basis in _ev.unnamed_failure_bases(steps))
    misses = [m for m in row.get("selectionMiss") or [] if isinstance(m, dict)]
    if row.get("selectionMissDropped"):
        notes.append("not learned from run %s: its selectionMiss keeps the "
                     "first %d misses (selectionMissDropped: %s), and the "
                     "rest are named nowhere this file can read"
                     % (run_id, len(misses), row["selectionMissDropped"]))
    for miss in misses:
        test = miss.get("test")
        if not test or not _ev.listed_by(test, named):
            notes.append("not learned from run %s: it records a miss for %s, "
                         "and no step whose runner named its failing suites "
                         "names it" % (run_id, test))
            continue
        skip = _couple_skip(miss, run_id, head, coupled)
        if skip:
            notes.append(skip)
        else:
            verbs.append(("couple", test, [
                "couple", "--test", test,
                "--sources", ",".join(miss["sources"]),
                "--basis-run", run_id, "--basis-head", head,
                "--phases", ",".join(miss.get("phases") or [])]))
        title = bug_title(test)
        if title in open_titles:
            notes.append("no bug for %s: %s is already open under the title "
                         "%r" % (test, open_titles[title], title))
            continue
        verbs.append(("bug-add", test, [
            "bug-add", title, "--severity", "med",
            "--description",
            _described(miss, run_id, head or "an unrecorded head"),
            "--files", test]))
    # EACH NAMED SUITE IS PINNED TO ONE COUPLED KEY OR TO NONE
    # (`_evidence_io.resolve_named`): a runner may print a suite relative to
    # its own directory, and a name that fits several coupled suites cannot
    # say which one failed - crediting any of them would reset the age of a
    # coupling that caught nothing, so that name credits none.
    #
    # A SUITE THIS ROW LISTS AS ITS OWN MISS IS NEVER ITS CATCH: the row says
    # no derived gate ran it, so no coupling did the work a catch credits -
    # whichever run taught the coupling, in whatever order imported rows are
    # learned from, and whether this row's `couple` created it or widened it.
    # Matched on the exact spelling or the coupled key, never a suffix, so a
    # miss spelled one way cannot withhold a catch from a different suite.
    missed = [m.get("test") for m in misses if m.get("test")]
    caught, own = [], []
    for spelling in named:
        key, why = _ev.resolve_named(spelling, list(coupled))
        if key is not None and (key in missed or spelling in missed):
            if key not in own:
                own.append(key)
                notes.append("no catch credited for %s in run %s: its own "
                             "selectionMiss lists that suite, so no derived "
                             "gate ran it and no coupling caught anything"
                             % (key, run_id))
        elif key is not None:
            if key not in caught:
                caught.append(key)
        elif _ev.listed_by(spelling, list(coupled)):
            notes.append("no catch credited for %s in run %s: %s"
                         % (spelling, run_id, why))
    verbs.extend(("couple --caught", key, ["couple", "--test", key,
                                           "--caught", run_id])
                 for key in caught)
    return {"verbs": verbs, "notes": notes}


def _plan_state(manifest):
    """`(coupled, open_titles)` off the plan as it stands - `learning_plan`'s
    two inputs. Open means not in `_status_facts.CLOSED_BUG` by the bug's
    EFFECTIVE status, so a bug whose fix task is done is not open."""
    meta = manifest.get("meta") or {}
    coupled = dict((e.get("test"), list(e.get("sources") or []))
                   for e in meta.get("coupling") or []
                   if isinstance(e, dict) and e.get("test"))
    by_id = _mio.tasks_by_id(manifest)
    open_titles = dict((b.get("title"), b.get("id"))
                       for b in manifest.get("bugs") or []
                       if isinstance(b, dict) and b.get("title")
                       and _mio.effective_bug_status(b, by_id)
                       not in _status_facts.CLOSED_BUG)
    return coupled, open_titles


def _run_verb(label, test, argv, manifest_path, project, out):
    """Run one `audit-task.py` verb, printing what it is and what it said.
    Returns its exit code."""
    cmd = ([sys.executable, _loader.script_path("audit-task.py")] + argv
           + [manifest_path, "--project-dir", project])
    out("%s learning: audit-task.py %s for %s" % (PREFIX, label, test))
    code = _stream_subprocess(cmd, out)
    out("%s audit-task.py %s for %s exited %d%s"
        % (PREFIX, label, test, code,
           "" if code == 0 else " - its own lines above say what it refused"))
    return code


def learn_from_row(row, manifest_path, project, out):
    """Act on one red full row: `{"verbs": ran, "failed": failed, "error":
    sentence or None}`.

    THE ONE PLACE THE LEARNING HAPPENS, for both doors into it - the red
    branch of a run this file made, and `--learn-from` over a row some other
    machine recorded. Neither door re-states a rule: which misses count,
    which catches are credited, what is skipped as already filed, is all
    `learning_plan`'s, read against the plan as it stands now.

    Every refusal to act is printed with its reason - a red run that taught
    nothing says so, rather than looking like one that was never asked."""
    try:
        manifest = _mio.load_manifest(manifest_path)
    except Exception as exc:
        why = "the plan could not be re-read (%s)" % (exc,)
        out("%s learned nothing from run %s: %s"
            % (PREFIX, row.get("runId"), why))
        return {"verbs": 0, "failed": 0, "error": why}
    coupled, open_titles = _plan_state(manifest)
    plan = learning_plan(row, coupled, open_titles)
    for note in plan["notes"]:
        out("%s %s" % (PREFIX, note))
    if not plan["verbs"]:
        why = ("each line above says why" if plan["notes"] else
               "it names no selection miss and no coupled suite as failing, "
               "and the runner's own lines above say whether the question "
               "could be asked")
        out("%s learned nothing from run %s: %s"
            % (PREFIX, row.get("runId"), why))
        return {"verbs": 0, "failed": 0, "error": None}
    failed = [label for label, test, argv in plan["verbs"]
              if _run_verb(label, test, argv, manifest_path, project,
                           out) != 0]
    return {"verbs": len(plan["verbs"]), "failed": len(failed), "error": None}


def learn(manifest_path, project, lines, started, out):
    """Act on the row a red run recorded; return how many verbs failed."""
    try:
        rows = _ev.read_rows(project)["rows"]
    except Exception as exc:
        out("%s learned nothing: the evidence ledger could not be read (%s)"
            % (PREFIX, exc))
        return 0
    row, why = find_row(rows, lines, started)
    if row is None:
        out("%s learned nothing: %s" % (PREFIX, why))
        return 0
    return learn_from_row(row, manifest_path, project, out)["failed"]


# --- learning from a run recorded elsewhere ---------------------------------------
# A CI build records its full run into its own shard, and learning there would
# write into a checkout the build throws away. So the build records, the shard
# is imported (`import-evidence.py` prints the command below for each red full
# row it brought in), and the learning happens here, in the checkout that keeps
# it - running nothing, reading the one row the id names.
def row_refusal(row, run_id):
    """Why the ledger's row for `run_id` cannot be learned from, or None.
    Red is `_evidence_io.row_is_red`, the runner's own reading, and a run
    that exited red is the one the red branch learns from."""
    scope = row.get("scope")
    if scope != _ev.FULL_SCOPE:
        return ("run %s is a run of scope %r, not %r - a selection miss is "
                "asked only of the third place's run"
                % (run_id, scope, _ev.FULL_SCOPE))
    if not _ev.row_is_red(row):
        return ("run %s passed - a green run has nothing to teach"
                % (run_id,))
    return None


def _missing_row(ledger, run_id, project):
    """The refusal for a run id the readable rows do not hold - naming each
    ledger file that could not be read in full, because the run may sit on
    the line that read lost, and 'no such run' would then be a false answer."""
    lost = [_output.posix_rel(p, project) if os.path.isabs(p) else p
            for p in ledger.get("unreadableFiles") or []]
    if lost:
        return ("no run %s is among the readable rows of the evidence "
                "ledger, and %s could not be read in full - the run may be "
                "on a line that read lost; repair it before asking again"
                % (run_id, ", ".join(lost)))
    return ("no run %s is in the evidence ledger - import the shard that "
            "recorded it first (import-evidence.py)" % (run_id,))


def learn_from(manifest_path, project, run_id, out):
    """`--learn-from`: learn from the ledger's row for `run_id`, running no
    gate. Returns the exit code.

    EXIT 1 WHEN THE LEARNING DID NOT HAPPEN OR DID NOT FINISH - a refused
    row, an unreadable ledger, a verb that failed, a raise. Unlike the red
    branch there is no runner's verdict to preserve here: the learning IS
    the command, so its failure is the answer. Exit 0 once it ran, including
    when it filed nothing, and the lines above the summary say why."""
    try:
        ledger = _ev.read_rows(project)
    except Exception as exc:
        out("%s cannot learn from run %s: the evidence ledger could not be "
            "read (%s)" % (PREFIX, run_id, exc))
        return E_FAIL
    row = _ev.row_by_run(ledger.get("rows") or [], run_id)
    why = (_missing_row(ledger, run_id, project) if row is None
           else row_refusal(row, run_id))
    if why:
        out("%s cannot learn from run %s: %s" % (PREFIX, run_id, why))
        return E_FAIL
    try:
        done = learn_from_row(row, manifest_path, project, out)
    except Exception as exc:
        out("%s learned nothing from run %s: learning raised %s: %s"
            % (PREFIX, run_id, type(exc).__name__, exc))
        return E_FAIL
    if done["error"]:
        return E_FAIL
    if done["failed"]:
        out("%s learning from run %s ran %d verb(s); %d failed, printed above"
            % (PREFIX, run_id, done["verbs"], done["failed"]))
        return E_FAIL
    if done["verbs"]:
        out("%s learned from run %s: %d verb(s) ran, none failed"
            % (PREFIX, run_id, done["verbs"]))
    return E_OK


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="full-gate.py", add_help=True)
    p.add_argument("manifest")
    p.add_argument("--writer", dest="writer", default=None)
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--learn-from", dest="learn_from", default=None,
                   metavar="RUNID")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK
    if args.learn_from is not None and args.writer:
        out("%s --learn-from runs no gate and records no row, so --writer "
            "names no file to write; pass one of them" % (PREFIX,))
        return E_USAGE
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        out("%s cannot read the manifest: %s" % (PREFIX, exc))
        return E_USAGE
    # THE RUNNER'S OWN DERIVATION of the project a manifest belongs to, so
    # the ledger read here is the one the run was recorded into.
    project = args.project_dir or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(args.manifest))))
    if args.learn_from is not None:
        return learn_from(args.manifest, project, args.learn_from, out)
    if not declares_full_gate(manifest):
        out(NO_THIRD_PLACE)
        return E_OK
    printed = []

    def tee(line):
        printed.append(line)
        out(line)

    started = start_moment()
    code = _run_full_gate(args.manifest, args.writer, args.project_dir, tee)
    if code == E_OK:
        return code
    # LEARNING IS ADVISORY, THE VERDICT IS NOT: a row this file cannot read
    # must not turn the runner's red into a traceback with no verdict line.
    try:
        failed = learn(args.manifest, project, printed, started, out)
    except Exception as exc:
        out("%s learned nothing: learning from the run raised %s: %s"
            % (PREFIX, type(exc).__name__, exc))
        failed = 0
    out("%s the run is still red - exit %d from run-test-gate.py blocks the "
        "push, whatever was learned%s"
        % (PREFIX, code, "" if not failed
           else "; %d learning verb(s) failed, printed above" % (failed,)))
    return code


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("full-gate.py: cases live in "
              "plugins/audit/tests/test_full_gate.py")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
