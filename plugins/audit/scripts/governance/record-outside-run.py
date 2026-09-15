#!/usr/bin/env python3
"""Record a test suite that ran where this plugin could not see it.

WHY THIS EXISTS. `run-test-gate.py` records the runs it MAKES, and for a long
time those were the only runs the ledger knew about. But a suite can run
somewhere else on the same machine and in the same minutes: a pre-push hook fires
one on `git push`, a developer starts one in a second terminal, a commit hook
runs one. Those runs take the same cores, the same ports and the same scratch
directories as a gate run, and until there was a word for them a red that a
concurrent outside suite had caused was recorded, rendered and read as the gate's
own verdict on the work.

RECORDING ONE DOES NOT MAKE THE RED GO AWAY, and nothing here can. What it buys
is the one thing that was missing: a named rival with its own row, so
`_evidence_io.attribution_of` can say the verdict is CONTESTED instead of the
gate claiming it alone. A question whose answer is "nobody could look" is a third
answer, and it is the honest one until somebody writes this row.

IT IS DECLARED AND NEVER SNIFFED. The plugin could try to guess an outside suite
from the spelling of a Bash command - does it say `playwright`, does it say
`push` - and that is the read-the-command's-spelling class this product keeps
being repaired for. It would be wrong in both directions on the first project
that wraps its own runner. So the row is written by whoever knows: the operator,
or the hook they wire it into.

THE ROW HAS NO SUBJECT, which is the bound that keeps it safe. A gate row carries
a `scope` and a task or phase id, and those are what `latest_by_subject` and
`reusable_run` key on. This row carries neither, so it can never be pointed at a
task, never stand in for a measurement the plugin owes, and never be repeated
instead of a gate. It is a fact about the MACHINE in a window, and the only
reader that wants it is the one asking who else was running.

AND IT CARRIES NO VERDICT UNLESS IT WAS GIVEN ONE. `--status` is optional and is
written through as the caller said it; absent means nobody told this command what
the outside suite answered, which is a true thing to record and better than a
word invented to fill the field.

Usage:
  record-outside-run.py <manifest> --label TEXT --started <ISO>
                        [--ended <ISO> | --duration-ms N]
                        [--status passed|failed] [--project DIR] [--json]

Exit codes:
  0  the row was written
  1  the row could not be written
  2  usage error - the manifest will not load, or the window will not parse

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_record_outside_run.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
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

import _evidence_io as _ev  # noqa: E402  (the ledger, the row shape and the runner words)
import _journal_io  # noqa: E402  (the config, and the session id a CLI writer files under)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)

E_OK, E_FAIL, E_USAGE = 0, 1, 2

PREFIX = "[record-outside-run]"

# The scope word this row wears. NOT "task" and NOT "phase": those are the two
# words `latest_by_subject` keys a pointer on and `reusable_run` compares, and a
# row wearing either of them with no id is a row those readers have to special-case.
# A word of its own says what the row is about - the machine, in a window - and
# leaves every subject reader answering exactly as it did before.
SCOPE_OUTSIDE = "outside"

# The verdicts a caller may pass through. Deliberately the two an outside runner
# can honestly report: it passed, or it did not. The words that describe HOW a
# gate failed to answer - timed out, ran no checks, mutated the tree - are
# observations `run-test-gate` takes for itself, and this command took none of
# them.
STATUS_WORDS = ("passed", "failed")

STAMP = "%Y-%m-%dT%H:%M:%SZ"


# --- the window ----------------------------------------------------------------
def parse_stamp(text):
    """`%Y-%m-%dT%H:%M:%SZ` as epoch seconds, or None when it is not that shape.

    IT IS THE LEDGER'S OWN READING AND NOT A SECOND ONE. `_evidence_io` is what
    turns a row's stamps back into a window, so a writer that parsed them its own
    way would be the module that decides what an instant is disagreeing with the
    module that decides whether two of them overlap - and the disagreement would
    be a time zone wide, which is a whole class of runs wrongly cleared or wrongly
    accused.

    None rather than a substitute: a stamp nothing can read is a row that cannot
    take part in an overlap question, and a zero would put it at the start of the
    epoch where it would overlap nothing and look like an answer.
    """
    return _ev._epoch(text)


def window(started, ended, duration_ms, now=None):
    """`(startedAt, ts, durationMs, why)` - the row's window, or a refusal.

    THREE WAYS TO AN END AND THEY ARE RANKED. An explicit `--ended` is the
    recorded one; a `--duration-ms` is the runner's own measurement added to the
    start; and with neither, the end is NOW, which is true for a row written the
    moment the suite finished and is the spelling a hook wrapper produces.

    A START THAT WILL NOT PARSE IS A REFUSAL AND NOT A GUESS. The whole value of
    this row is its window, so a row with no readable start would be a row that
    answers the one question it was written for with "not knowable" - which the
    ledger already says for free about every row that predates the key.

    AN END BEFORE THE START IS REFUSED TOO. Two stamps in that order describe no
    interval, and an overlap computed over a negative one is arithmetic nobody
    can read back.
    """
    start = parse_stamp(started)
    if start is None:
        return (None, None, None,
                "--started %r is not an instant this can read; the shape is "
                "%s, which is what every row in this ledger is stamped in"
                % (started, STAMP.replace("%", "")))
    if ended is not None:
        end = parse_stamp(ended)
        if end is None:
            return (None, None, None,
                    "--ended %r is not an instant this can read; the shape is "
                    "%s" % (ended, STAMP.replace("%", "")))
    elif duration_ms is not None:
        end = start + int(duration_ms // 1000)
    else:
        end = now if now is not None else int(time.time())
    if end < start:
        return (None, None, None,
                "the run ended before it started (%s then %s), which describes "
                "no interval for an overlap question to be asked over"
                % (started, ended))
    return (time.strftime(STAMP, time.gmtime(start)),
            time.strftime(STAMP, time.gmtime(end)),
            (end - start) * 1000, "")


# --- the row -------------------------------------------------------------------
def outside_row(project, label, started_at, ts, duration_ms, status=None,
                session_id=None):
    """The `result`/`identity` pair `_evidence_io.record` takes for one outside run.

    BUILT THROUGH `row_for` RATHER THAN HAND-ASSEMBLED, which is the point of
    returning a pair instead of a dict. That function is the one definition of
    what an evidence row may carry - an inventive caller cannot widen it - and a
    second row builder here would be a second shape wearing one file name.

    `runner` IS THE ONLY FIELD THAT MAKES THIS ROW WHAT IT IS. Absent means the
    gate, because every row written before the key existed was the wrapper's; so
    this is the one writer that has to set it, and a row that failed to would be
    filed as a run this plugin made.
    """
    # THE LABEL TRAVELS AS THE STEP'S `name` AND NOT AS ITS `command`. A
    # `command` is stored as a digest, a byte count and a program token unless the
    # manifest publishes it - which is right for a string this file has no claim
    # about, and useless here, because the label IS the identification a reader of
    # a contested verdict needs. `name` is the free-text half of a step and is
    # stored as given, the way every other operator sentence in this product is.
    result = {"status": status, "durationMs": duration_ms, "failed": [],
              "steps": [{"name": str(label)}]}
    identity = {"runId": _ev.new_run_id(), "via": "cli",
                "sessionId": session_id,
                _ev.RUNNER_KEY: _ev.RUNNER_OUTSIDE,
                _ev.STARTED_KEY: started_at, "ts": ts}
    return result, identity


def record_outside(project, manifest_path, label, started_at, ts, duration_ms,
                   status=None, config=None):
    """`(exitCode, answer)` - write the row and say what happened. Prints nothing.

    A PAIR RATHER THAN AN EXIT CODE, for `run-test-gate.run_gate`'s reason: a
    function that returned only a verdict could not be exercised without a
    terminal around it.
    """
    config = _journal_io.load_config(project) if config is None else config
    session_id = _journal_io.env_session_id()
    result, identity = outside_row(project, label, started_at, ts, duration_ms,
                                   status=status, session_id=session_id)
    try:
        written = _ev.record(project, result, SCOPE_OUTSIDE, {}, identity,
                             config=config)
    except Exception as exc:
        return E_FAIL, {"recorded": False, "runId": identity["runId"],
                        "refused": "the row could not be appended (%s)" % (exc,)}
    rows = []
    try:
        rows = _ev.read_rows(project, config=config)["rows"]
    except Exception:
        rows = []
    # WHO THIS ROW NOW CONTESTS, said on the run that writes it. The operator who
    # records an outside suite is the one person in a position to act on the
    # answer, and telling them later - on somebody else's gate run - is telling
    # the wrong reader.
    gate_runs, basis = _ev.overlapping_runs(rows, written["row"], _ev.RUNNER_GATE)
    return E_OK, {"recorded": True, "runId": written["row"]["runId"],
                  "path": written["path"], "journalled": bool(written["appended"]),
                  "contests": None if gate_runs is None
                  else [str(r.get("runId") or "?") for r in gate_runs],
                  "basis": basis, "refused": ""}


def render(answer, out=print):
    """Print what happened, in the order somebody reading a terminal needs it."""
    if answer.get("refused"):
        out("%s REFUSED: %s" % (PREFIX, answer["refused"]))
        return
    out("%s recorded %s" % (PREFIX, answer["runId"]))
    contests = answer.get("contests")
    if contests is None:
        out("  contests: not knowable - %s" % (answer.get("basis"),))
    elif contests:
        out("  contests: %d recorded gate run(s) share this window (%s). Their "
            "verdicts are no longer this gate's alone to claim, and a red among "
            "them may be the crowd rather than the work"
            % (len(contests), ", ".join(contests)))
    else:
        out("  contests: no recorded gate run shares this window, so nothing "
            "this plugin measured is put in doubt by it")
    if not answer.get("journalled"):
        out("  the ledger row was written and the trail row was not, so the run "
            "is recorded and nothing in the journal points at it")


# --- cli ------------------------------------------------------------------------
def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="record-outside-run.py", add_help=True, allow_abbrev=False,
        description="Record a test suite that ran where this plugin could not "
                    "see it, so a gate run in the same window is not credited "
                    "with its effects.")
    parser.add_argument("manifest")
    parser.add_argument("--project", default=".",
                        help="the directory holding .claude/ and the records "
                             "(default: the current directory)")
    parser.add_argument("--label", required=True,
                        help="what ran, in the words of whoever ran it")
    parser.add_argument("--started", required=True,
                        help="when it began, as %s" % (STAMP.replace("%", ""),))
    parser.add_argument("--ended", default=None,
                        help="when it finished; default is now")
    parser.add_argument("--duration-ms", dest="duration_ms", type=int,
                        default=None,
                        help="how long it took, if the end was not recorded")
    parser.add_argument("--status", choices=list(STATUS_WORDS), default=None,
                        help="what it answered; absent means nobody said")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv, out=print):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK

    if not str(args.label or "").strip():
        sys.stderr.write("ERROR: --label says what ran, and a blank one records "
                         "a rival nobody can identify\n")
        return E_USAGE
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n"
                         % (args.manifest, exc))
        return E_USAGE
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: manifest %s is not a JSON object\n"
                         % (args.manifest,))
        return E_USAGE

    started_at, ts, duration_ms, why = window(args.started, args.ended,
                                              args.duration_ms)
    if why:
        sys.stderr.write("ERROR: %s\n" % (why,))
        return E_USAGE

    project = os.path.abspath(args.project)
    code, answer = record_outside(project, args.manifest, args.label,
                                  started_at, ts, duration_ms,
                                  status=args.status)
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        render(answer, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("record-outside-run.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_record_outside_run.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
