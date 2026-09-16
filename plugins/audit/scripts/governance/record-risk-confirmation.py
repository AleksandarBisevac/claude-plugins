#!/usr/bin/env python3
"""
record-risk-confirmation.py -- the human's answer to the high-risk gate, given BEFORE
the run instead of during it, bounded to the tasks it can honestly cover and written
into the hash-chained trail in the operator's own words.

WHY THIS EXISTS. `reference/orchestrator.md` step 4a says a `risk: "high"` task stops
and asks the human before its commit, always. An operator running the pipeline
unattended has high-risk tasks and nobody at the keyboard: asking parks the run until
somebody comes back, so the run instruction itself gets treated as the confirmation and
the report says so afterwards. That is a safety rule being overridden quietly, which is
worse than either a stall or a documented exception -- and it was reported from a live
run, not imagined here.

The third option is to let the answer be given EARLY and RECORDED. `always ask` is
still true; the asking simply happened before the run, and the trail says who answered
and in what words.

WHAT MAKES IT SAFE RATHER THAN MERELY CONVENIENT, and this is the whole design:

  * IT COVERS A NAMED LIST OF TASK IDS, NEVER A CONDITION. The covered set is computed
    HERE, from the manifest as it stands at the moment of the answer, and written into
    the row by id. A confirmation phrased as "any high-risk task in this phase" would go
    on answering for work that did not exist when it was given -- which is not an answer,
    it is the rule deleted and a flag left behind where the rule used to be.

  * ONE PHASE, AND THE PHASE THE OPERATOR NAMED. A run is invoked per phase, so the
    phase is the unit the operator is actually looking at when they answer; the plan is
    not. Widening to the plan would let one answer given about three tasks discharge the
    gate for every high-risk task anywhere, including phases the operator never opened.

  * OPEN WORK ONLY. A task already `done` or `cancelled` has no commit left to confirm,
    so listing it would inflate what the answer appears to cover without covering
    anything.

  * IT REFUSES WHEN THERE IS NOTHING TO CONFIRM. A phase with no open high-risk task
    gets exit 2, not an empty row. An empty confirmation is a standing permission with
    no subject -- exactly the shape that survives into the next phase and answers for
    work nobody has read.

  * IT FAILS LOUD. The row IS the deliverable, so an append that does not land is exit 1
    and says the confirmation was NOT recorded. `journal.enabled: false` is refused for
    the same reason one step earlier: a pre-given answer with no trail is an override
    with nothing to check it against, and the run must go back to asking per task.

WHAT IT DOES NOT DO, said here because a reader will otherwise assume it. It writes no
manifest field and gates no commit. Nothing in this plugin refuses a commit of a
high-risk task that is missing from the list -- the orchestrator obeying step 4a is what
does that. This command bounds what may be CLAIMED and leaves a row a reader can hold
the claim against afterwards; `audit-journal.py show --target <phaseId>` is where they
find it.

THE WORDS GO IN UNCHANGED -- `reference/manifest-conventions.md` -> *The operator's
words go in unchanged*, the same rule `/audit:phase cancel --reason` follows, and for
the same reason: the chain guarantees whatever sentence it is handed, so a paraphrase
makes it guarantee a sentence its subject never wrote. The value is echoed back in this
command's own output and carried in the row, which is also this command's answer to a
shell that ate a clause: the operator reads their own sentence back before the run
proceeds, rather than finding it in a file a week later.

Usage:
  record-risk-confirmation.py <manifestPath> <phaseId>
                              --confirm-high-risk "<the operator's own words>"
                              [--project DIR] [--json]

Exit codes:
  0  recorded -- the row landed, and the covered ids are in the output
  1  NOT recorded: the journal is disabled, or the append did not land. The run has no
     pre-given answer and must ask per task
  2  usage: the manifest will not load, no such phase, blank words, or the phase has no
     open high-risk task for an answer to be about

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_record_risk_confirmation.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
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

import _journal_io                                                   # noqa: E402
import _manifest_io as _mio                                          # noqa: E402

E_OK, E_FAIL, E_USAGE = 0, 1, 2

# The journal action. A name of its own rather than a reuse of `task.cancel`'s: the
# trail is read by people asking "who authorised this commit", and a row borrowed from
# another verb answers a different question under a familiar word.
ACTION_RISK_CONFIRMED = "risk.confirmed"

# The one spelling of the risk level this gate is about. `task.risk` is
# `low|med|high|null` in the schema, so the comparison is against this and never
# against "not low" -- a null risk is an unanswered question, not a high one.
HIGH = "high"


# --- the covered set ------------------------------------------------------------
def covered_tasks(manifest, phase_id):
    """[taskId, ...] -- exactly the tasks this answer is allowed to cover.

    THREE NARROWINGS, AND EACH ONE IS THE FEATURE. The phase the operator named, so
    an answer about one phase cannot discharge the gate in another; `risk == "high"`,
    so the answer covers the question that was actually asked; and open work only,
    because a terminal task has no commit left to confirm and listing it would make
    the answer look wider than it is.

    DERIVED AT THE MOMENT OF THE ANSWER, which is what makes the row a record rather
    than a rule. A task that becomes high-risk afterwards -- retargeted, or added
    mid-run -- is absent from this list and is therefore unanswered; step 4a stops
    and asks for it.
    """
    out = []
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        if str(phase.get("id")) != str(phase_id):
            continue
        for task in (phase.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            if str(task.get("risk") or "").strip().lower() != HIGH:
                continue
            if str(task.get("status") or "") in _mio.TERMINAL:
                continue
            out.append(str(task.get("id")))
    return out


def nothing_to_confirm(phase_id):
    """The refusal for a phase with no open high-risk task.

    It has to say what an answer would have been ABOUT, because the caller's next
    move depends on which of two things is true: the phase genuinely carries no
    high-risk work (nothing to do, run it), or the risk is not on the tasks yet
    (`/audit:task add --risk high` / `retarget`, then answer).
    """
    return ("[risk-confirmation] %s has no OPEN task with risk \"high\", so there is "
            "nothing for a confirmation to be about -- and a confirmation with no "
            "subject is a standing permission that answers for whatever appears "
            "next. Nothing was recorded. If the phase really does carry high-risk "
            "work, the risk is not on the tasks: set it, then answer."
            % (phase_id,))


# --- the row --------------------------------------------------------------------
def record(project, phase_id, covered, words, config=None):
    """The path the row landed in, or False. FAIL-LOUD, and the opposite of
    `close-phase.record_row`'s contract on purpose.

    There the merge had already happened and the row was its record, so a failed
    append must not report a merge as not having happened. Here the row IS the whole
    deliverable -- nothing else changes -- so an append that did not land leaves the
    run with no pre-given answer at all, and the only safe report of that is failure.

    THE IDS GO IN THE SUMMARY AND THE WORDS IN `details.reason`, which is
    `task.cancel`'s shape one verb over rather than a second one invented. Both are
    bounded by `_journal_io` -- a long sentence is clipped and SAYS it was clipped --
    and that bound is a bound, not a paraphrase: the rule this follows forbids
    rewriting the operator, and a marked clip leaves the reader knowing there is more
    rather than believing they have all of it.

    THE ENTRY IS BUILT AT THE CALL SITE, which is every journal writer's shape here
    (`close-phase.record_row` is the nearest one) and not a style choice. Returning it
    from a helper makes this the one statically resolvable producer of `_normalise`'s
    `entry` in the tree, and `_deps.dict_key_contracts()` then grades that parameter
    against this single caller -- reporting `ts` as a key nothing writes, while the
    writer that does supply it reaches `_normalise` through a runtime module load the
    scan cannot follow. The row shape is asserted against the APPENDED row instead,
    which is the stronger read anyway: it is what a reader of the trail will find.
    """
    config = _journal_io.load_config(project) if config is None else config
    return _journal_io.append_from_cli(project, {
        "action": ACTION_RISK_CONFIRMED,
        "actor": {"via": "record-risk-confirmation"},
        "target": str(phase_id),
        "summary": "%s: high-risk commits confirmed in advance for %s"
                   % (phase_id, ", ".join(covered)),
        "details": {"phaseId": str(phase_id), "reason": words},
    }, config=config)


# --- the command ----------------------------------------------------------------
def _parser():
    p = argparse.ArgumentParser(
        prog="record-risk-confirmation.py",
        description="Record a human's confirmation of a phase's high-risk commits, "
                    "given before the run, bounded to the task ids it can cover.")
    p.add_argument("manifest", help="path to the audit manifest (index or single file)")
    p.add_argument("phase", help="the phase the answer is about")
    p.add_argument("--confirm-high-risk", dest="words", required=True,
                   help="the operator's OWN words, passed through unchanged")
    p.add_argument("--project", dest="project", default=None,
                   help="the directory holding .claude/ and the journal "
                        "(default: derived from the manifest path)")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="print the answer as JSON instead of as a block")
    return p


def _project_of(args, mpath):
    """Which root owns the journal and the config: --project when given, else the
    directory the manifest's `docs/audit/` sits under, walked up from the file."""
    if args.project:
        return os.path.abspath(args.project)
    here = os.path.dirname(os.path.abspath(mpath))
    while True:
        if os.path.isdir(os.path.join(here, ".claude")):
            return here
        up = os.path.dirname(here)
        if up == here:
            return os.path.dirname(os.path.abspath(mpath))
        here = up


def render(answer, out=print):
    """One block, read top to bottom: what was answered, for which ids, in whose
    words, where the row is -- and what is still unanswered, because the last line is
    the one that keeps this from reading as a blanket permission."""
    out("[risk-confirmation] %s -- the high-risk gate answered before the run"
        % (answer["phaseId"],))
    out("  covered: %s" % (", ".join(answer["covered"]),))
    out("  words: %s" % (answer["confirmation"],))
    out("  row: %s" % (answer["row"],))
    out("  NOT covered: every other task in this phase, and any task whose risk "
        "becomes \"high\" after this row. Those still stop and ask.")


def main(argv, out=print):
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK

    words = args.words if isinstance(args.words, str) else ""
    if not words.strip():
        out("[risk-confirmation] --confirm-high-risk was blank. The value is the "
            "operator's answer and it goes into the trail unchanged, so there is "
            "nothing here to record. Nothing was written.")
        return E_USAGE

    mpath = os.path.abspath(args.manifest)
    # `load_manifest`, not `load_manifest_safe`: the safe reader answers {} for an
    # unreadable file, and {} here would reach the "no high-risk task" refusal and
    # tell the operator their phase is clear when the truth is that nothing was read.
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[risk-confirmation] cannot read/parse %s: %s" % (mpath, exc))
        return E_USAGE

    # Through the shared resolver, so `2`, `p2` and `P2` name one phase here
    # and everywhere else rather than three answers per script.
    phase_id, perr = _mio.resolve_phase_id(manifest, args.phase)
    if phase_id is None:
        out("[risk-confirmation] %s" % (perr,))
        return E_USAGE

    covered = covered_tasks(manifest, phase_id)
    if not covered:
        out(nothing_to_confirm(phase_id))
        return E_USAGE

    project = _project_of(args, mpath)
    config = _journal_io.load_config(project)
    if not _journal_io.enabled(config):
        out("[risk-confirmation] journal.enabled is false for %s, so this answer "
            "would leave no record. A pre-given confirmation with nothing to check "
            "it against is an override, not an answer -- refused. Turn the journal "
            "on, or let the run ask per task." % (project,))
        return E_FAIL

    path = record(project, phase_id, covered, words, config=config)
    if not path:
        out("[risk-confirmation] the row could NOT be appended, so nothing was "
            "recorded and this run has no pre-given answer. Every high-risk task "
            "in %s still stops and asks." % (phase_id,))
        return E_FAIL

    answer = {"phaseId": phase_id, "covered": covered, "confirmation": words,
              "row": path, "action": ACTION_RISK_CONFIRMED}
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        render(answer, out=out)
    return E_OK


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("record-risk-confirmation.py has no inline --selftest; its cases live "
              "in plugins/audit/tests/test_record_risk_confirmation.py - run that "
              "file instead.")
        sys.exit(0)
    raise SystemExit(main(sys.argv[1:]))
