#!/usr/bin/env python3
"""
The one walk over every phase and every task, and the checks it makes on the way.

Split out of `_manifest_rules.py`. This is the half of that file's
`# --- validate: one walk ---` seam that PRODUCES the index rather than reading
it: `_walk_phases` visits each phase and each task once, checks the per-object
rules a phase carries (its parallel-run claim, its area tag, its budget, its
sign-off consistency) and returns five named accumulators the checks in
`_manifest_crossrefs` then read.

THE WALK STAYS ONE PASS ON PURPOSE, and that is the whole reason the index is a
return value rather than five separate walks: splitting it per-question would
visit every task four times and would let two of them disagree about which
objects were skipped as malformed.

`_check_claim`, `_check_area_tag` and `_check_areas` live here because the walk
is their only caller and a phase is their only subject. `_check_areas` is the
odd one - it is called by `validate()` directly rather than from inside the
loop, because two of its three questions are about the REGISTRY (`meta.areas`)
rather than about any one phase.

The `tests_add_*` group lives here for a DIFFERENT reason, and it is what a
caller outside validation reads: `audit-task.py` asks `tests_add_path` which
path a `tests.add` entry puts into a task's `files`, the walk asks it to
require one of a `tdd` task that can still be committed against (F294, beside
F254's rule about the same field), and `repair-tests-add.py` asks
`tests_add_repair` what a one-shot migration may do to an entry written before
that rule existed. They are here because those rules are what a reader has to
compare - the first draft put the walk's one in `_manifest_rules` with a walk
of its own, which was a third pass over the tasks and a second copy of
`mode == "tdd" and status not in TERMINAL` that had already drifted from
F254's on `expectRedFirst`. That filter is now `tests_add_graded`, so the walk
and the migration cannot disagree about which entries the rule reaches.
`_manifest_rules` re-exports the group, so no call site knows where it sits.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__manifest_phases.py` - see
`plugins/audit/tests/_harness.py`.
"""
import json
import os
import re
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

import _manifest_io as _mio  # noqa: E402  (TERMINAL: what 'finished' means everywhere)
import _areas  # noqa: E402  (meta.areas registry + the resolution every surface shares)
import _manifest_vocab as _vocab  # noqa: E402  (the words, and the shared shape checks)
import _ado_parent as _parent  # noqa: E402  (what an `adoParent` declaration may say)
import _ado_tracked as _tracked  # noqa: E402  (and what an `adoTracked` one may say)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_manifest_rules.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
CLAIM_KEYS = _vocab.CLAIM_KEYS
KNOWN_PHASE = _vocab.KNOWN_PHASE
KNOWN_TASK = _vocab.KNOWN_TASK
RISK = _vocab.RISK
STATUS = _vocab.STATUS
TESTS_MODE = _vocab.TESTS_MODE
TERMINAL = _mio.TERMINAL
_check_ado = _vocab._check_ado
_require_fields = _vocab._require_fields
_safe_list = _vocab._safe_list
_unknown_keys = _vocab._unknown_keys


# --- what a phase carries --------------------------------------------------------
def _check_claim(phase, pwhere, findings, warnings):
    """Validate an optional parallel-run `claim` on a phase (v0.15 sharded layout).

    A claim records which session/host/branch is running a phase so concurrent work
    across machines is coordinated (and a same-phase double-claim shows up as a shard
    merge conflict). Shape errors are findings; a claim missing recommended keys, or one
    left on a finished phase (stale — should be released), is a warning."""
    if "claim" not in phase:
        return
    claim = phase.get("claim")
    if claim is None:
        return
    if not isinstance(claim, dict):
        findings.append("%s: claim must be an object {sessionId, host, branch, at}, got %s"
                        % (pwhere, type(claim).__name__))
        return
    missing = [k for k in CLAIM_KEYS if not claim.get(k)]
    if missing:
        warnings.append("%s: claim is missing %s — a claim should identify the "
                        "session/host/branch holding the phase" % (pwhere, ", ".join(missing)))
    if phase.get("status") in ("done", "cancelled", "blocked"):
        warnings.append("%s: has a claim but status is %r — a finished/blocked phase should "
                        "release its claim (stale claim)" % (pwhere, phase.get("status")))


# --- what a review recorded -------------------------------------------------------
# THE FINDING'S SHAPE, AND THE WORDS ITS SEVERITY MAY TAKE. Both are written down
# here because until they were, nobody wrote them down in a place anything read: the
# reviewer agent's return format states one shape, the orchestrator's sign-off step
# asks for a record of it, and the schema declared five optional properties with no
# rule attached. So every phase recorded findings in whatever shape that run's
# reviewer happened to return -- most of them plain strings -- and a finding that
# names no file and no resolution is one no later run, report or panel can act on.
#
# The vocabulary is the one the reviewer is already asked for, rather than a new one:
# a validator that invented a fourth word would be grading returns against something
# no agent was ever told.
FINDING_FIELDS = ("id", "severity", "file", "issue", "resolution")
FINDING_SEVERITY = ("low", "med", "high")
# Both lists the review block holds findings in. The second is not read by the
# orchestrator, but it is the SAME record shape and a reader that could parse one
# and not the other would be two readers.
REVIEW_FINDING_LISTS = ("findings", "preExistingNotCharged")


def _check_review(phase, pwhere, warnings):
    """A phase's recorded review findings, held to the shape the schema names.

    WARNINGS, NEVER FINDINGS, and that is the rule rather than a soft start. Every
    plan written before this shape carries free-text findings, and a validator that
    refused them would be refusing documents the product itself wrote -- which is
    how a validator stops being run at all. The manifest stays valid; the line says
    what cannot be read back.

    ONE WARNING PER PROBLEM PER PHASE, not one per finding. The bodies are then
    byte-identical across phases, so `_warning_groups.collapse` folds a whole plan's
    worth into one line; a per-item rule that cannot fold is exactly what buries the
    warning standing next to it.
    """
    review = phase.get("review")
    if not isinstance(review, dict):
        return
    for key in REVIEW_FINDING_LISTS:
        entries = review.get(key)
        if not isinstance(entries, list):
            continue
        shapeless = False
        missing = set()
        outside = set()
        for entry in entries:
            if not isinstance(entry, dict):
                shapeless = True
                continue
            for field in FINDING_FIELDS:
                value = entry.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing.add(field)
            sev = entry.get("severity")
            if isinstance(sev, str) and sev.strip() and sev not in FINDING_SEVERITY:
                outside.add(sev)
        if shapeless:
            warnings.append(
                "%s: review.%s holds an entry that is not a finding object - a "
                "plain string records no file, no severity and no resolution, so "
                "nothing downstream can turn it into a fix task. The shape is "
                "{%s}" % (pwhere, key, ", ".join(FINDING_FIELDS)))
        if missing:
            warnings.append(
                "%s: a review.%s finding is missing %s - the shape is {%s}, and a "
                "finding missing one of them cannot be read back"
                % (pwhere, key, ", ".join(sorted(missing)),
                   ", ".join(FINDING_FIELDS)))
        if outside:
            warnings.append(
                "%s: a review.%s finding carries severity %s - the vocabulary is "
                "%s, which is what the reviewer is asked to return"
                % (pwhere, key, ", ".join(repr(s) for s in sorted(outside)),
                   ", ".join(FINDING_SEVERITY)))


def _gate_entries(value):
    """A `testGate` / `tests.gate` value as the entries that will actually run.

    ONE NORMALISATION FOR BOTH SIDES, because the only question asked of it is
    whether two gates are the same gate. A non-list is [], a non-string entry is
    dropped (nothing resolves it and nothing runs it), and a blank string is
    dropped too — `["lint", ""]` and `["lint"]` order the same commands, so a
    comparison that told them apart would be reading whitespace rather than
    scope. Order is KEPT: gate entries run in the order they are written, and
    two lists holding the same commands in a different order are two different
    runs.
    """
    return [e for e in _safe_list(value) if isinstance(e, str) and e.strip()]


def _check_area_tag(phase, pwhere, findings):
    """A phase's `area` must be a tag or a list of them (v0.16 shape, v0.28 meaning).

    Shape only — WHICH tags are legal is not this function's business and is not
    anybody's: free text stays legal forever. But `area: 3` and `area: {...}`
    normalise to NO tags at all, so the phase silently leaves every grouping and
    resolves against no area. Silence is the reason this is worth a finding."""
    if "area" not in phase:
        return
    area = phase.get("area")
    if area is None or isinstance(area, str):
        return
    if not isinstance(area, list):
        findings.append("%s: area must be a tag or a list of tags, got %s"
                        % (pwhere, type(area).__name__))
        return
    bad = [a for a in area if not isinstance(a, str) or not a.strip()]
    if bad:
        findings.append("%s: every area tag must be a non-empty string (%d bad: %s)"
                        % (pwhere, len(bad),
                           _output.some_of(bad, render=repr)))


def _check_areas(manifest):
    """The `meta.areas` registry, and the phases that name it (v0.28).

    Returns (findings, warnings). It used to take both lists and write into
    them; every direct child of `validate()` returns its own pair now, so no
    caller can depend on the order two of them happen to run in, and a piece
    can be exercised from a case without being handed two lists to inspect
    afterwards.

    Three questions, and only the first can invalidate a manifest:

      * is the registry SHAPED like a registry — findings, same as any other
        wrong type in this file;
      * does every tag a phase carries have an entry — warnings, and ONLY when
        the manifest registers areas at all. A project that tags freely and
        registers nothing is using the v0.16 feature exactly as designed, and
        warning it would be this validator nagging about a feature not in use.
        A project that DOES register is one where an unregistered tag is nearly
        always a typo of a registered one — and a typo'd tag quietly resolves to
        no area, so the reviewer and the skills the author expected never happen;
      * do a phase's areas AGREE about its reviewer — a warning naming the
        winner, because written order decides and a silent tie-break is a
        reviewer nobody can explain.
    """
    findings, warnings = [], []
    meta = manifest.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    if "areas" in meta:
        f, w = _areas.validate_registry(meta.get("areas"))
        findings.extend(f)
        warnings.extend(w)
    for pid, tag in _areas.unregistered_tags(manifest):
        warnings.append("phase %s: area tag %r has no entry in meta.areas — it "
                        "groups and filters, but resolves to no root, no default "
                        "reviewer and no default skills (typo? free-text tags are "
                        "legal)" % (pid, tag))
    for phase in manifest.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        clash = _areas.review_skill_conflicts(manifest, phase)
        if clash:
            # json.dumps, not %r: the values came out of a JSON file and go back to
            # someone editing one, and `None` is not something they can type there.
            # A null IS one of the disagreeing answers here — an area saying "tests
            # sign this off" disagrees with an area naming a reviewer.
            warnings.append(
                "phase %s: areas %s each set a different reviewSkill — written "
                "order decides, so %s (from area %s) is the one that runs"
                % (phase.get("id") or "?",
                   ", ".join("%s=%s" % (t, json.dumps(s)) for t, s in clash),
                   json.dumps(clash[0][1]), clash[0][0]))
    return (findings, warnings)


def _add_parent(obj, where, findings, warnings):
    """Fold `_ado_parent`'s shape check into the walk's two accumulators.

    A three-line adapter rather than a call at each of the two sites, because
    the walk writes into lists and `_ado_parent` returns a pair - and the day
    that mismatch is spelled out twice is the day one of the two forgets the
    warnings half. `_ado_parent` is at layer 1 beside `_manifest_vocab`, so
    this module reaches it downward like any other word it borrows.
    """
    pf, pw = _parent.declaration_findings(obj, where)
    findings.extend(pf)
    warnings.extend(pw)


def _add_tracked(obj, where, findings, warnings):
    """The same adapter for `_ado_tracked`, and separate because the SCOPE differs.

    `adoParent` is declared on a phase AND on a task; `adoTracked` is a phase's
    alone, because a task inherits. Folding the two into one adapter would have
    made the task call site carry a check that must never fire there, and the way
    that goes wrong is silent: a task growing a declaration nothing reads.
    """
    tf, tw = _tracked.declaration_findings(obj, where)
    findings.extend(tf)
    warnings.extend(tw)


# --- what a `tests.add` entry NAMES ----------------------------------------------
# F294. The schema documents `tests.add` as free prose, and `audit-task.py`'s `files`
# union treated every entry as a path on F258's premise that a tdd task "creates the
# file it names in `tests.add` by definition". True of the tasks that name one, false
# of the field: the scope filled up with assertions and `fileIndex` grew keys no path
# can ever match. The SHARP half was never the pollution -- the union exists so
# `_invariants.commit_scope` will allow the file the task says it will create, and
# when the entry is a sentence the thing added to `files` is not that path, so the
# permission was never granted.
#
# IT LIVES BESIDE THE WALK, and beside F254's rule about the same field, because
# those two are what a reader has to compare. The first draft put it in
# `_manifest_rules` (L3) with a walk of its own, which was a THIRD pass over the
# tasks and a second expression of `mode == "tdd" and status not in TERMINAL` -- and
# the two had already drifted apart on `expectRedFirst` before anybody read them
# together. `_manifest_rules` re-exports both names, so every caller and the L7 ->
# L3 edge from `audit-task.py` are unchanged.
_TESTS_ADD_LEAD = re.compile(r"\A\s*([^\s:]+)\s*(?::|\Z)")
# A FILENAME, not merely something with a separator in it. `_PATHISH_EXT` wants a
# dot followed by a letter-initial extension, and `_DOTFILE` covers the other real
# shape - `.gitignore` and `.gitattributes` are both live `files` entries in this
# repository's own plan and neither carries an extension.
_PATHISH_EXT = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}\Z")
_DOTFILE = re.compile(r"\A\.[A-Za-z][A-Za-z0-9_.-]+\Z")


def tests_add_path(entry):
    """The path a `tests.add` entry NAMES, or None when it names none.

    THREE QUESTIONS, ASKED IN ORDER, and all three have to hold.

    POSITION. The documented shape is `"<path>: <what it asserts>"`, so the
    candidate is the whole entry or everything before a colon -- never a token
    pulled out of the middle of a sentence, because a path nobody typed is the
    same defect one word narrower. `require-plan selftests a4-a6: custom-path
    manifest...` fails here: its leading token is followed by a word, not a
    colon.

    SEGMENTS. Every separator-delimited piece must be non-empty, which is what
    refuses a bare `/` and a trailing-slash directory. An entry naming a
    directory names no file, which is precisely what this is asked.

    FILENAME. The LAST segment has to look like one - an extension, or a
    dotfile. This is the bound the first draft did not have, and F294's own
    defect one shape narrower is what its absence produced: `--tests-add "n/a"`
    put `n/a` into `files` and into `fileIndex`, a key no path can ever match.
    Measured over every `files` entry in the plans this repository ships, the
    only extensionless paths are the two dotfiles, which is why that arm exists
    and why a bare `docs/audit` does not qualify.

    NONE IS AN ANSWER AND NOT A FAILURE. A caller is expected to say the entry
    named no file rather than fall back to a default.
    """
    if not isinstance(entry, str) or not entry.strip():
        return None
    found = _TESTS_ADD_LEAD.match(entry)
    if not found:
        return None
    token = found.group(1)
    segments = re.split(r"[\\/]", token)
    if not all(segments):
        return None
    leaf = segments[-1]
    if _PATHISH_EXT.search(leaf) or _DOTFILE.match(leaf):
        return token
    return None


def tests_add_graded(task):
    """Whether the `"<path>: <what it asserts>"` rule reaches this task's entries.

    ONE FILTER, TWO CALLERS. The walk below warns about the entries this
    accepts and `repair-tests-add.py` offers to rewrite exactly those, so a
    second expression of it would be a migration repairing entries the
    validator never complained about, or leaving ones it did. The neighbouring
    rule about the same field was born as a second copy of this same filter and
    had drifted before anybody read the two together, which is the argument for
    naming it rather than repeating it.

    TERMINAL IS EXEMPT, which is what the migration inherits for free: a
    settled task's `tests.add` is a record of work already judged, and rewriting
    one would edit the description of a commit that has already been graded.
    """
    if not isinstance(task, dict):
        return False
    tests = task.get("tests")
    if not isinstance(tests, dict) or tests.get("mode") != "tdd":
        return False
    return task.get("status") not in TERMINAL


# --- what a one-shot repair may do to an entry -----------------------------------
# The rule above announces a refusal that arrives at a major, and an announcement
# with no migration behind it strands every plan written before it. So this is the
# other half: what can be repaired mechanically, and what has to be handed back.
#
# NOTHING HERE INVENTS A PATH. The only path a repair may write is one the entry
# ITSELF already spells - moving an author's own token to the front is reading the
# entry, while deriving one from the task's `files` or from a naming convention
# would be writing a path nobody typed into the field that grants commit scope. A
# sentence is visibly not a path; a wrong path is not, which is why the wrong one
# is the worse of the two to leave behind.
#
# THE MENTION BOUND IS STRICTER THAN THE LEAD BOUND, and the asymmetry is the
# whole design. The lead position is a DECLARATION, so a filename is enough there;
# a token inside a sentence is a MENTION, and ordinary prose is full of tokens that
# pass a filename test - `e.g.` is a dot followed by a letter and would read as an
# extension. Requiring a separator refuses those, and refuses `Node.js` with them.
# What it costs is a repo-root dotfile named mid-sentence, which is then handed to
# a human rather than guessed at - the direction this errs in on purpose.
_MENTION_WRAP = "`'\"()[]{}<>,.;:!?"

# The verdicts, as words rather than as a tuple position, because three of the four
# mean "leave this entry alone" for three different reasons and a caller that
# collapsed them would print one remedy for all three.
REPAIR_NAMED = "named"            # already opens with a path; nothing to do
REPAIR_REWRITE = "rewrite"        # the entry names one path; move it to the front
REPAIR_UNNAMED = "unnamed"        # nothing in it parses as a path
REPAIR_AMBIGUOUS = "ambiguous"    # it names more than one, so which is the case?


def tests_add_mentions(entry):
    """Every DISTINCT path an entry MENTIONS, in the order it mentions them.

    A token counts when it carries a separator AND would be the whole answer if
    it stood at the lead - `tests_add_path` decides the filename half, so this
    cannot disagree with the rule it is repairing about what a path looks like.
    Wrapping punctuation is stripped because prose quotes, brackets and ends
    sentences; a token carrying a line suffix (`a/b.py:12`) is NOT the whole
    answer and falls out here, left for a human rather than truncated.
    """
    if not isinstance(entry, str):
        return []
    found = []
    for token in entry.split():
        bare = token.strip(_MENTION_WRAP)
        if "/" not in bare and "\\" not in bare:
            continue
        if tests_add_path(bare) != bare:
            continue
        if bare not in found:
            found.append(bare)
    return found


def tests_add_repair(entry):
    """`(verdict, replacement)` - what a one-shot repair may do to this entry.

    THE REWRITE ONLY EVER PREPENDS. The entry arrives back as the tail of its
    own replacement, so no claim its author made is lost and the result can be
    trusted by looking at it rather than by re-reading the sentence. That is
    also what makes the rewrite safe on a task that has already run: what
    append-only protects is a backwards grading, `_invariants.commit_scope`
    grades against `files`, and a prefix can only ADD to the paths an entry
    names.

    AMBIGUITY IS A REFUSAL AND NOT A RANKING. An entry naming a test file and
    the source file it drives names both in prose, and picking the first would
    be a convention this field has never had. The author knows which one holds
    the case; this does not.
    """
    if tests_add_path(entry) is not None:
        return (REPAIR_NAMED, None)
    mentioned = tests_add_mentions(entry)
    if not mentioned:
        return (REPAIR_UNNAMED, None)
    if len(mentioned) > 1:
        return (REPAIR_AMBIGUOUS, None)
    return (REPAIR_REWRITE, "%s: %s" % (mentioned[0], entry.strip()))


# --- the walk --------------------------------------------------------------------
def _walk_phases(phases):
    """One pass over every phase and every task: (index, findings, warnings).

    THE INDEX IS WHY THIS WAS NEVER CUT OUT BEFORE. Five accumulating locals
    ride this single walk and each is read by a DIFFERENT check further down,
    which is exactly the coupling that kept `validate()` in one 354-line piece.
    Naming them turns the coupling into an argument:

      phase_ids     every phase id, document order   -> unique ids, proposals
      task_ids      every task id, document order    -> unique ids, refs,
                                                        fileIndex, bugs
      task_by_id    id -> the task object            -> bug reciprocity
      task_files    id -> its non-empty `files` list -> fileIndex, both ways
      bug_links     (twhere, task id, bugId) per link-> bug reciprocity

    `task_files` holds only tasks whose `files` is a non-empty list, because
    that is the question `_check_file_index` asks of it; a task with no files
    is absent rather than mapped to [], and the fileIndex check reads it with
    `.items()` only.

    The walk stays ONE pass on purpose. Splitting it per-question would visit
    every task four times to build four dicts, and would let two of them
    disagree about which objects were skipped as malformed.
    """
    f, w = [], []
    phase_ids, task_ids = [], []
    task_bug_links = []       # (twhere, task_id, bugId)
    task_by_id = {}
    task_files = {}           # task_id -> files list

    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            f.append("phases[%d]: not an object" % pi)
            continue
        pid = phase.get("id")
        pwhere = "phase %s" % (pid or ("phases[%d]" % pi))
        _require_fields(phase, pwhere, f)
        _unknown_keys(phase, KNOWN_PHASE, pwhere, w)
        # connector v2: phaseWorkItems writes a phase-level adoLink
        _check_ado(phase, pwhere, f)
        # U-PARENT: the AUTHORED half beside it. Shape only here - where the
        # parent resolves to and whether that place can be true are questions
        # about the whole plan, and `_manifest_crossrefs` asks them.
        _add_parent(phase, pwhere, f, w)
        # U-BOARD: the other AUTHORED ado field, and PHASE-ONLY on purpose - a
        # task inherits its phase's answer and never declares one, so checking it
        # on the task walk below would invite a declaration the resolver ignores.
        _add_tracked(phase, pwhere, f, w)
        if pid:
            phase_ids.append(pid)
        if phase.get("status") not in STATUS:
            f.append("%s: status %r not in %s" % (pwhere, phase.get("status"), list(STATUS)))
        _check_claim(phase, pwhere, f, w)
        _check_review(phase, pwhere, w)
        _check_area_tag(phase, pwhere, f)
        # A budget of 0 or a negative one is not a budget, and a string is a typo
        # that would silently render as "no budget". Both are worth saying out loud.
        if "budgetUSD" in phase:
            budget = phase.get("budgetUSD")
            if isinstance(budget, bool) or not isinstance(budget, (int, float)):
                f.append("%s: budgetUSD must be a number, got %s"
                         % (pwhere, type(budget).__name__))
            elif budget <= 0:
                f.append("%s: budgetUSD must be greater than 0 (got %s) — omit the "
                         "key entirely for 'no budget'" % (pwhere, budget))

        tasks_val = phase.get("tasks")
        if "tasks" not in phase:
            w.append("%s: no 'tasks' key — the schema requires one (an empty "
                     "phase should carry an empty list)" % pwhere)
        elif not isinstance(tasks_val, list):
            f.append("%s: tasks must be an array, got %s"
                     % (pwhere, type(tasks_val).__name__))
        # A phase is 'done' only after sign-off, which requires every task done.
        # A done phase with a non-done task is a stale-status slip the schema
        # can't express (e.g. a hand-regenerated roadmap that flipped the phase
        # but not its tasks).
        if phase.get("status") == "done":
            # FINISHED, not done: a task the team cancelled is settled, and a
            # phase that signed off around it is not a slip. Only genuinely
            # unfinished work (pending / in_progress / blocked) contradicts it.
            not_done = [t.get("id") or "?" for t in _safe_list(tasks_val)
                        if isinstance(t, dict) and t.get("status") not in TERMINAL]
            if not_done:
                f.append("%s: status 'done' but %d task(s) are not finished (%s) "
                         "— a phase is done only after ALL its tasks are done "
                         "or cancelled (sign-off)"
                         % (pwhere, len(not_done),
                            _output.some_of(not_done)))
        for ti, task in enumerate(_safe_list(tasks_val)):
            if not isinstance(task, dict):
                f.append("%s tasks[%d]: not an object" % (pwhere, ti))
                continue
            tid = task.get("id")
            twhere = "task %s" % (tid or ("%s.tasks[%d]" % (pwhere, ti)))
            _require_fields(task, twhere, f)
            _unknown_keys(task, KNOWN_TASK, twhere, w)
            if tid:
                task_ids.append(tid)
                task_by_id[tid] = task
                files = task.get("files")
                if isinstance(files, list) and files:
                    task_files[tid] = files
            if task.get("status") not in STATUS:
                f.append("%s: status %r not in %s" % (twhere, task.get("status"), list(STATUS)))
            if (phase.get("status") == "pending"
                    and task.get("status") == "in_progress"):
                w.append("%s is in_progress but its %s is still 'pending' — "
                         "pre-0.3 manifest? /audit:resume expects the phase to "
                         "be 'in_progress' too" % (twhere, pwhere))
            tests = task.get("tests")
            if "tests" in task and tests is not None and not isinstance(tests, dict):
                f.append("%s: tests must be an object with a 'mode', got %s"
                         % (twhere, type(tests).__name__))
            if isinstance(tests, dict) and tests.get("mode") not in TESTS_MODE:
                f.append("%s: tests.mode %r not in %s" % (twhere, tests.get("mode"), list(TESTS_MODE)))
            # F254. `tdd` + `expectRedFirst` + nothing named is an instruction to
            # prove a red first with no case to prove it with, and nothing said so:
            # a live run met exactly this on the largest security change of a phase,
            # generated by `/audit:init`, and only noticed later. A WARNING and not
            # a finding, because the repair is to name the case and an existing plan
            # must not go red over a field it was written without.
            #
            # UNFINISHED TASKS ONLY, and that narrowing is the difference between a
            # rule and noise. A red-first case named after the task is done is not a
            # red-first case - the opportunity it describes is gone - so warning
            # about a `done` one tells the reader about something they cannot act
            # on, which is how a warning that fires across most of a mature plan
            # teaches people to skip the whole class. Measured on this repository's
            # own manifest the moment the rule landed: 25 tasks, and every finished
            # one of them already carries its cases in `verifiedBy`.
            if isinstance(tests, dict) and tests.get("mode") == "tdd" \
                    and tests.get("expectRedFirst") \
                    and task.get("status") not in TERMINAL \
                    and not (tests.get("add") or []):
                w.append("%s: tests.mode is 'tdd' with expectRedFirst and no "
                         "tests.add - a red-first task naming no case cannot be "
                         "shown to have gone red. Name it with `/audit:task scope "
                         "%s --tests-add \"<case>\"`, or use mode 'regression' or "
                         "'gate-only' if no new test is owed" % (twhere, tid))
            # F294, THE RULE ABOUT THE SAME FIELD ONE QUESTION OVER, and the two
            # sit together so a reader can see where they differ and why.
            #
            # F254 above asks whether a red-first task named a case AT ALL; this
            # asks whether the case it named can be found on disk. So this one
            # does NOT require `expectRedFirst`, and the difference is deliberate
            # rather than drift: `expectRedFirst` is a DERIVED field
            # (`audit-task._build_task` writes `mode == "tdd"`), it is what
            # declares the red-first intent F254 is about, and the `files` union
            # this rule exists for does not read it at all. Requiring it here
            # would let a hand-edited `expectRedFirst: false` opt a task out of a
            # rule about a field it has no bearing on.
            #
            # TERMINAL IS EXEMPT, on F254's reasoning read one step further: a
            # settled task's `tests.add` is a RECORD of work already judged, and
            # F283 leaves its scope append-only through the verb, so a line about
            # one names nothing anybody can act on.
            #
            # A WARNING THROUGH THE 2.x LINE. `COMPATIBILITY.md` promises that a
            # manifest which validates keeps validating, and this shape was legal
            # for a field the schema documents as prose - so the rule warns, its
            # text names the release the refusal arrives in, and 3.0.0 is where it
            # becomes a finding. The order is announce, then enforce.
            if tests_add_graded(task):
                add_val = tests.get("add")
                if add_val is not None and not isinstance(add_val, list):
                    # A FINDING, and a TYPE one, which is its neighbours' shape
                    # (`tasks must be an array`, `tests must be an object`) and
                    # not a deprecation: the schema has always declared this an
                    # array, so a string here never validated against it. Said
                    # ONCE - iterating a string yields one warning per character,
                    # which is the warning class people learn to skip.
                    f.append("%s: tests.add must be an array, got %s"
                             % (twhere, type(add_val).__name__))
                for entry in _safe_list(add_val):
                    if tests_add_path(entry) is not None:
                        continue
                    w.append("%s: this tests.add entry names no file, so the "
                             "`files` union has no path to carry and "
                             "commit-scope will refuse the case this task says "
                             "it will create. Write it as \"<path>: <what it "
                             "asserts>\" - THIS BECOMES A FINDING AT 3.0.0 "
                             "(COMPATIBILITY.md -> Validation stays additive). "
                             "For a plan written before the rule, "
                             "`scripts/manifest/repair-tests-add.py <manifest>` "
                             "reports every entry like this one and rewrites "
                             "the ones that already spell their path: "
                             "%r" % (twhere, entry))
            # THE DERIVED GATE, READ BACK. `/audit:init` step 5.3 narrows a
            # task's `tests.gate` to the paths that task names and reaches the
            # phase's wide gate only as its last arm, with a reason in the
            # description; nothing here had ever looked at the result, so a plan
            # that took the last arm on task after task validated in silence. A
            # task carrying the phase gate re-asks the PHASE's question - is the
            # repository still whole - inside the executor's retry loop, on every
            # attempt, per task, per phase running in parallel, which is the cost
            # the derivation exists to avoid.
            #
            # A WARNING, NEVER A FINDING, for two independent reasons: the wide
            # gate is the RIGHT answer for a runner with no path-scoped spelling,
            # and a validator that refused a plan written before this line
            # existed is a validator people stop running.
            #
            # TERMINAL IS EXEMPT, on the reasoning the red-first rule above uses:
            # the gate of a settled task has already run, so a line about it
            # names nothing anybody can still act on, and the settled tasks are
            # the bulk of a mature plan - which is the difference between a line
            # an operator reads and a class they learn to skip. Re-derive the
            # split on any plan with `validate-manifest.py <plan> --verbose`.
            #
            # AN EMPTY PHASE GATE RAISES NOTHING. A phase that grades itself with
            # no command has no wide gate for a task to have copied, and a task
            # with an empty gate is a designed state `audit-task.py` reports on
            # its own terms; neither is this rule's subject.
            phase_gate = _gate_entries(phase.get("testGate"))
            task_gate = _gate_entries(tests.get("gate")
                                      if isinstance(tests, dict) else None)
            if phase_gate and task_gate == phase_gate \
                    and task.get("status") not in TERMINAL:
                w.append("%s: tests.gate is its phase's testGate verbatim - the "
                         "wide gate, re-run on every attempt of this task "
                         "instead of once at sign-off. Narrow it to the paths "
                         "this task names (`/audit:task scope <id> --gate "
                         "\"<command>\"`), or say in the task's description why "
                         "the wide gate is the answer here - /audit:init step "
                         "5.3 writes that reason when it cannot derive a "
                         "narrower one" % (twhere,))
            if "risk" in task and task.get("risk") not in RISK:
                f.append("%s: risk %r not in %s" % (twhere, task.get("risk"), ["low", "med", "high", None]))
            _check_ado(task, twhere, f)
            _add_parent(task, twhere, f, w)
            # The id-prefix rule (workstream B) -- the hand-move detector.
            # /audit:task move renumbers a task into its target phase, so an id
            # that does not match `<phaseId>.<int>` means the object was dragged
            # by hand. A WARNING only: legacy manifests with free-form ids must
            # never go red over bookkeeping.
            if tid and pid and not re.match(
                    r"^%s\.\d+$" % re.escape(str(pid)), str(tid)):
                w.append("%s: id does not follow its phase's prefix (%s.<n>) "
                         "-- moved by hand? /audit:task move renumbers, "
                         "rewrites references and records a task.move row. "
                         "Informational; legacy ids stay legal" % (twhere, pid))
            if "movedFrom" in task:
                mf = task.get("movedFrom")
                if mf is not None and not isinstance(mf, dict):
                    w.append("%s: movedFrom should be an object "
                             "{id, phase, at}, got %s"
                             % (twhere, type(mf).__name__))
                elif isinstance(mf, dict):
                    lacking = [k for k in ("id", "phase", "at")
                               if not mf.get(k)]
                    if lacking:
                        w.append("%s: movedFrom is missing %s -- /audit:task "
                                 "move writes all three"
                                 % (twhere, ", ".join(lacking)))
            if task.get("bugId"):
                task_bug_links.append((twhere, tid, task["bugId"]))

    return ({"phase_ids": phase_ids, "task_ids": task_ids,
             "task_by_id": task_by_id, "task_files": task_files,
             "bug_links": task_bug_links}, f, w)

# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_manifest_phases.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__manifest_phases.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
