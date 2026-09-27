#!/usr/bin/env python3
"""
PreToolUse hook (matcher: Bash) — refuse to publish a release while the plan
carries an open bug. THIS REPO'S OWN CONFIGURATION, not the audit plugin's product.

WHAT IT IS FOR. `v2.0.0` and `v2.0.1` were both released while BUG-2 through BUG-5
sat `open` in the manifest, and a bug reported during the second one went into a
scratch plan file no gate reads. Twenty-one gates were green and every one of them
was honest: not one asked whether the plan still carried an open bug. This is that
question, asked at the only moment it cannot be skipped - the command that
publishes.

WHAT COUNTS AS PUBLISHING, and the line is drawn where the consequence is. A tag
that has been pushed is never moved here and a Release is a page the world lands
on, so those are refused. `git push origin main` is NOT: pushing code is not
releasing it, and a guard that blocked ordinary work would be routed around within
a day - which is the failure mode `guard-false-positive-class` is about. Creating
a tag LOCALLY is refused too, because a local tag is what the push then publishes
and refusing only the push leaves a trap already loaded.

A SECOND LIST HOLDS THE SAME RELEASE, BESIDE THE BUGS: a merged phase the
plan's own evidence ledger reads PROVISIONAL - no green, measured, clean,
verbatim full run yet recorded whose head contains what that phase merged
into - refuses exactly the same commands, for the reason the manifest's
"third place" exists at all: a merge is not the same claim as a full suite
having actually run against it. `read_provisional` asks the plugin's own
`full_status` this question rather than restating it, the way `read_bugs`
already asks `effective_bug_status` rather than reading a stored field. A
plan naming no third place (`meta.fullGate` absent) has nothing provisional
by definition, so this guard then behaves exactly as it did before this
existed.

THE WAY PAST IT is `arm-release-bypass.py`: the maintainer types the keyword and a
single-use slot appears. Nothing the model writes can arm it. That is why the
switch is on the prompt and not on this command - a guard the caller can satisfy
by writing the right words is not a guard. The message it prints names the
provisional phases beside the bugs, through this file's own `read_provisional`,
so what is being shipped over is never understated.

FAIL-LOUD, NOT FAIL-OPEN, AND THAT IS THE OPPOSITE OF THIS REPO'S OTHER HOOKS.
`SECURITY.md`'s table puts advisory paths on fail-open: a guard that crashes must
not stop legitimate work. This one inverts it for one reason - the thing it
protects is irreversible. A pushed tag cannot be taken back, so a guard that
cannot read the manifest must refuse rather than wave a release through on its own
malfunction. It says which of the two happened.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 - the canonical PreToolUse
protocol.

Exit codes: 0 always (the decision travels in the payload, never in the code).
"""
import json
import os
import re
import subprocess
import sys
import time

STATE_REL = os.path.join(".claude", "state")
MANIFEST_REL = os.path.join("docs", "audit", "audit-plan.json")
# The words that mean a bug will not hold a release. `fixed` is what the plugin's
# derivation produces; the rest are the verdicts a person wrote, and a bug closed
# with one this tuple has not learned would hold every release until somebody
# rewrote its status to a word that is less true. A hook may not import the
# plugin, so this restates rather than reads — and `gr` cases below drive the
# plugin's own vocabulary against it so the two cannot come apart in silence.
CLOSED = ("fixed", "wontfix", "not_a_bug")
KEYWORD = "#release-with-bugs"

# What publishes. Each is anchored at a command boundary (start of line, `&&`,
# `;`, `|`) so a word appearing inside a filename or a commit message cannot
# trip it, and each carries WHY it is on this list.
PUBLISHERS = (
    # A tag is the release object. Creating one locally is refused with the push,
    # because a created tag is a loaded trap and refusing only the push leaves it.
    (r"git\s+tag\b(?!.*\s-(?:d|-delete|l|-list)\b)", "creates a git tag"),
    # `git push … v1.2.3`, `--tags`, or an explicit refs/tags spec.
    (r"git\s+push\b.*(?:--tags\b|--follow-tags\b|\brefs/tags/|\sv\d+\.\d+)",
     "pushes a tag"),
    (r"gh\s+release\s+create\b", "publishes a GitHub Release"),
)
_BOUNDARY = r"(?:^|[;&|]\s*|\s&&\s*|\s\|\|\s*)\s*"


def project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def publishing(command):
    """`reason` when `command` would publish a release, else None.

    Read over the WHOLE command string rather than the first word: a release is
    routinely typed as `git tag -a v1 -m … && git push origin v1`, and a guard
    that only inspected the head of the line would wave the second half through.
    """
    text = str(command or "")
    for pattern, why in PUBLISHERS:
        if re.search(_BOUNDARY + pattern, text):
            return why
    return None


def _effective(project):
    """The plugin's own `effective_bug_status`, or None when it cannot be reached.

    IMPORTED, NOT REIMPLEMENTED, and the first draft of this file got it wrong:
    it read the raw `status` field and reported five open bugs where
    `/audit:status` reported one. A bug materialized into a task reads `fixed`
    once that task is done - the orchestrator never writes `bugs[]` during a run
    - so the stored field lags on purpose, and a second reading of it is a second
    answer that had already disagreed before this comment was written.

    The plugin's own hooks may not import `scripts/`; this one is not a plugin
    hook. It is this repository's configuration, and this repository always has
    `plugins/audit/scripts/` sitting next to it.

    LAZILY, from inside the one branch that needs it: this hook runs on every
    Bash call, and `publishing()` has already said no by the time most of them
    get here. The import cost belongs to a release, not to every `ls`.

    Resolved from THIS FILE's own repository rather than from `project`, because
    those are two different things: `project` is where the manifest is, and the
    plugin's code is wherever this hook was checked out. The fallback keeps a
    caller that hands over a different project working when its own tree carries
    the plugin.
    """
    here = os.path.dirname(os.path.abspath(__file__))       # .claude/hooks
    repo = os.path.dirname(os.path.dirname(here))
    for root in (repo, project):
        scripts = os.path.join(root, "plugins", "audit", "scripts")
        if not os.path.isdir(scripts):
            continue
        for entry in (scripts, os.path.join(scripts, "manifest")):
            if entry not in sys.path:
                sys.path.insert(0, entry)
        try:
            import _manifest_io
            return _manifest_io
        except Exception:
            continue
    return None


def _evidence_modules(project):
    """`(_evidence_io, _worktrees, _manifest_vocab)`, or None when they cannot
    be reached - the lazy load `read_provisional` needs, patterned on
    `_effective`'s load of `_manifest_io` for the same reason: most Bash calls
    never reach the publishing branch, so the cost of reaching
    `scripts/governance`, `scripts/git` and `scripts/manifest` belongs to a
    release alone, not to every command this hook is asked about.
    """
    here = os.path.dirname(os.path.abspath(__file__))       # .claude/hooks
    repo = os.path.dirname(os.path.dirname(here))
    for root in (repo, project):
        scripts = os.path.join(root, "plugins", "audit", "scripts")
        if not os.path.isdir(scripts):
            continue
        for entry in (scripts, os.path.join(scripts, "governance"),
                      os.path.join(scripts, "git"),
                      os.path.join(scripts, "manifest")):
            if entry not in sys.path:
                sys.path.insert(0, entry)
        try:
            import _evidence_io
            import _worktrees
            import _manifest_vocab
            return (_evidence_io, _worktrees, _manifest_vocab)
        except Exception:
            continue
    return None


def _hooks_config(project):
    """The plugin's own `plugins/audit/hooks/_config`, loaded lazily and by
    the same two-root search `_effective` and `_evidence_modules` use.

    THIS FILE IS NOT A PLUGIN HOOK - its own docstring says so - but the tree
    a release command targets is exactly the question `_config.tree_for`
    already answers for every hook that does count as one (P72), and a second
    answer to that question invented here could disagree with the first the
    day a linked worktree entered the picture.
    """
    here = os.path.dirname(os.path.abspath(__file__))       # .claude/hooks
    repo = os.path.dirname(os.path.dirname(here))
    for root in (repo, project):
        hooks = os.path.join(root, "plugins", "audit", "hooks")
        if not os.path.isfile(os.path.join(hooks, "_config.py")):
            continue
        if hooks not in sys.path:
            sys.path.insert(0, hooks)
        try:
            import _config
            return _config
        except Exception:
            continue
    return None


def resolved_tree(payload, project):
    """The tree whose PLAN a release command answers to.

    `_config.tree_for`, asked about THIS COMMAND's own effective working
    directory - never `CLAUDE_PROJECT_DIR` alone. A release typed from a
    linked worktree publishes over THAT worktree's plan, which may carry a
    provisional phase the project's own copy does not, so judging it against
    the project unconditionally would be asking the wrong tree the question
    this file exists to ask (P72).

    Falls back to `project` (today's reading, unconditionally) when `_config`
    cannot be reached or answers nothing usable - never a THIRD guess at a
    tree neither `project` nor `_config` named.
    """
    cfg_mod = _hooks_config(project)
    if cfg_mod is None:
        return project
    data = payload if isinstance(payload, dict) else {}
    command = (data.get("tool_input") or {}).get("command", "")
    try:
        target = cfg_mod.effective_cwd(command, data.get("cwd"))
        placed = cfg_mod.tree_for(data, target, project=project)
    except Exception:
        return project
    root = placed.get("root")
    return str(root) if root else project


def read_bugs(project):
    """`(open_bugs, problem)` — the plan's open bugs, or why they are unknown.

    The two are returned apart because they are different answers. `([], None)`
    is a plan with nothing open; `(_, "…")` is a plan nobody could read, and
    reporting that as "nothing open" would let a release through on the strength
    of a broken file.

    "Open" is the EFFECTIVE status, which is the plugin's rule and not one of
    this file's own - see `_effective`.
    """
    mio = _effective(project)
    if mio is None:
        return ([], "the plugin's own bug rule could not be loaded from "
                    "plugins/audit/scripts, so `open` cannot be decided here")
    path = os.path.join(project, MANIFEST_REL)
    try:
        # THE ASSEMBLED manifest, not the raw index. This repository's own plan is
        # SHARDED: `json.load` returns phases that are stubs carrying no tasks, so
        # every bug's linked task went missing and five bugs read open where
        # `/audit:status` reported one. `_panel_write` carries the same scar in
        # its own docstring - it read the raw index too, and every per-task edit
        # was refused for a task the panel had just listed.
        data = mio.load_manifest_safe(path)
    except Exception as exc:
        return ([], "%s could not be read (%s)" % (MANIFEST_REL, exc))
    if not isinstance(data, dict):
        return ([], "%s did not parse as a manifest object" % (MANIFEST_REL,))
    bugs = data.get("bugs")
    if not isinstance(bugs, list):
        return ([], "%s carries no `bugs` list" % (MANIFEST_REL,))
    try:
        by_id = mio.tasks_by_id(data)
    except Exception as exc:
        return ([], "the plan's tasks could not be indexed (%s), so a bug's "
                    "effective status is unknown" % (exc,))
    out = []
    for bug in bugs:
        if not isinstance(bug, dict):
            continue
        try:
            status = mio.effective_bug_status(bug, by_id)
        except Exception:
            status = bug.get("status")
        if str(status or "").lower() not in CLOSED:
            out.append((bug.get("id") or "?", bug.get("severity") or "?",
                        bug.get("title") or ""))
    return (out, None)


def read_provisional(project):
    """`(provisional, problem)` - every merged phase this plan's own evidence
    ledger reads PROVISIONAL, each named with `full_status`'s own basis, or
    why that cannot be decided at all.

    THE SECOND LIST BESIDE THE OPEN BUGS, on the plugin's own vocabulary
    rather than a rule invented here: `full_status` (P80.3) already answers
    whole, provisional, unknown or not-declared from the ledger alone, and a
    second reading of that question in this file would be the same defect
    `read_bugs`'s docstring already warns about - two answers to one
    question, with this file at risk of being the one that lies.

    UNREADABLE IS A REFUSAL, NEVER "NOTHING PROVISIONAL" - this file's own
    fail-loud rule, extended to the second list it now reads. A manifest that
    will not parse or a ledger carrying a file that could not be read or
    verified means the caller cannot know whether some phase is provisional,
    so it must say so rather than let a release through on the strength of a
    file nobody could actually read.

    No `meta.fullGate` at all means nothing is provisional and this returns
    `([], None)` - the guard's behaviour is then exactly what it was before
    this function existed.
    """
    mio = _effective(project)
    if mio is None:
        return ([], "the plugin's own evidence rule could not be loaded from "
                    "plugins/audit/scripts, so provisional phases cannot be "
                    "decided here")
    modules = _evidence_modules(project)
    if modules is None:
        return ([], "the plugin's own evidence reader could not be loaded "
                    "from plugins/audit/scripts, so provisional phases "
                    "cannot be decided here")
    evidence_io, _worktrees, vocab = modules
    path = os.path.join(project, MANIFEST_REL)
    try:
        data = mio.load_manifest_safe(path)
    except Exception as exc:
        return ([], "%s could not be read (%s)" % (MANIFEST_REL, exc))
    if not isinstance(data, dict):
        return ([], "%s did not parse as a manifest object" % (MANIFEST_REL,))
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    full_gate = meta.get("fullGate")
    if not full_gate:
        return ([], None)
    full_commands = [c for _name, c in
                     evidence_io.resolved_commands(data, full_gate)]
    ledger = evidence_io.read_rows(project)
    if ledger.get("unreadable"):
        return ([], "the evidence ledger carries file(s) that could not be "
                    "read or verified: %s"
                    % (", ".join(ledger.get("unreadableFiles") or []),))
    rows = ledger.get("rows") or []
    phases = data.get("phases")
    phases = phases if isinstance(phases, list) else []
    out = []
    for phase in phases:
        if not isinstance(phase, dict) or not phase.get("mergedAt"):
            continue
        status = evidence_io.full_status(rows, phase, project, full_commands)
        if status.get("answer") == vocab.FULL_STATUS_PROVISIONAL:
            out.append((phase.get("id") or "?", status.get("basis") or ""))
    return (out, None)


def bypass_armed(project, session_id, now=None):
    """True iff the maintainer armed a bypass that has not expired.

    Read here and CONSUMED nowhere: PreToolUse may run more than once for one
    intention, and a slot deleted on the first read would refuse the second half
    of `git tag … && git push …`. It expires on its own TTL instead, which is
    what makes it single-use in the sense that matters - it cannot authorise a
    later release.
    """
    now = time.time() if now is None else now
    path = os.path.join(project, STATE_REL,
                        "release-bypass-%s.json" % (session_id or "none",))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            slot = json.load(fh)
    except Exception:
        return False
    armed = slot.get("armedAtEpoch")
    ttl = slot.get("ttlSeconds")
    if not isinstance(armed, (int, float)) or not isinstance(ttl, (int, float)):
        return False
    return (now - armed) <= ttl


def refusal(why, bugs, provisional, problem):
    """The sentence a refused release reads, naming what to do about it - the
    open bugs and the provisional phases named as two lists, because they are
    settled two different ways."""
    if problem:
        return ("this command %s, and whether the plan carries open bugs or "
                "a provisional phase is UNKNOWN: %s. A pushed tag is never "
                "moved here, so this refuses rather than guessing. Fix the "
                "file, or type %s to release anyway."
                % (why, problem, KEYWORD))
    parts = []
    if bugs:
        listed = "; ".join("%s (%s) %s" % (b[0], b[1], b[2][:70]) for b in bugs)
        parts.append("%d bug(s) are open in the plan: %s" % (len(bugs), listed))
    if provisional:
        listed = "; ".join("%s (%s)" % (p[0], p[1][:90]) for p in provisional)
        parts.append("%d phase(s) are provisional - no green full run yet "
                     "measured on a head containing what they merged into: %s"
                     % (len(provisional), listed))
    return ("this command %s while %s. Close the bugs, record the full run "
            "that settles a provisional phase (/audit:review <phase> --full, "
            "or the pre-push/CI step), or type %s in your own message to "
            "release over them - the keyword only counts from you, which is "
            "why it is read off the prompt and not off this command."
            % (why, "; and ".join(parts), KEYWORD))


def decide(command, project, session_id, now=None, payload=None):
    """`reason` when the call must be denied, else None. The whole rule, in one
    pure-ish function so its cases need no hook payload.

    `payload` is OPTIONAL and used for exactly one thing: resolving which
    TREE this release answers to, through `resolved_tree`. Every case in this
    file that predates that question passes no `payload` and keeps reading
    `project` as the tree directly, which is the same answer it always got."""
    why = publishing(command)
    if not why:
        return None
    tree = resolved_tree(payload, project) if payload else project
    bugs, bug_problem = read_bugs(tree)
    provisional, prov_problem = read_provisional(tree)
    problem = bug_problem or prov_problem
    if not bugs and not provisional and not problem:
        return None
    if bypass_armed(project, session_id, now):
        return None
    return refusal(why, bugs, provisional, problem)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Nothing to judge. This is the one fail-open branch: a payload this hook
        # cannot parse is not evidence about a release.
        return 0
    tool = payload.get("tool_name") or payload.get("toolName") or ""
    if tool != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "")
    reason = decide(command, project_dir(),
                    str(payload.get("session_id") or ""),
                    payload=payload)
    if reason:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[guard-release] " + reason}}))
    return 0


def _selftest():
    import shutil
    import tempfile
    cases, failed = [], []

    def check(label, cond, detail=""):
        cases.append(label)
        if not cond:
            failed.append("%s (%s)" % (label, detail))
        print(("PASS " if cond else "FAIL ") + label)

    # --- what counts as publishing -------------------------------------------
    check("gr1 creating an annotated tag is publishing",
          publishing('git tag -a v2.0.2 -m "notes"'))
    check("gr2 pushing a tag by name is publishing",
          publishing("git push origin v2.0.2"))
    check("gr3 --tags is publishing", publishing("git push --tags"))
    check("gr4 a GitHub Release is publishing",
          publishing("gh release create v2.0.2 --verify-tag"))
    check("gr5 a release typed as ONE line is caught in its second half - this "
          "is how a release is actually typed, and a guard reading only the "
          "head of the line would wave it through",
          publishing('git tag -a v1 -m x && git push origin v1'))
    # THE SECOND DIRECTION, and the cases that keep this guard from being routed
    # around: ordinary work must not trip it. A guard that fires on a read gets
    # disabled, which is the class `guard-false-positive-class` records.
    check("gr6 pushing a BRANCH is not publishing - pushing code is not "
          "releasing it", not publishing("git push origin main"))
    check("gr7 setting upstream on a branch is not publishing",
          not publishing("git push -u origin audit/some-branch"))
    check("gr8 LISTING or DELETING tags is not publishing",
          not publishing("git tag -l") and not publishing("git tag -d v1"))
    check("gr9 reading releases is not publishing",
          not publishing("gh release view v2.0.1")
          and not publishing("gh release list"))
    check("gr10 the words inside a commit message do not trip it",
          not publishing('git commit -m "prepare gh release create notes"'))

    # --- the rule, end to end -------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="guard-release-")
    try:
        os.makedirs(os.path.join(tmp, "docs", "audit"))
        os.makedirs(os.path.join(tmp, STATE_REL))
        mpath = os.path.join(tmp, MANIFEST_REL)

        def write_bugs(bugs, phases=None):
            with open(mpath, "w", encoding="utf-8") as fh:
                json.dump({"meta": {"version": 2}, "phases": phases or [],
                           "bugs": bugs}, fh)

        # THE DEFECT THIS FILE SHIPPED IN ITS FIRST DRAFT, as a case: a bug whose
        # fix task is `done` reads FIXED even though its stored status still says
        # open, because the orchestrator does not write `bugs[]` during a run.
        # Reading the raw field reported five open bugs where `/audit:status`
        # reported one, and this is the fixture that tells the two apart.
        write_bugs([{"id": "BUG-9", "status": "open", "severity": "med",
                     "title": "materialized and finished", "taskId": "P1.1"}],
                   phases=[{"id": "P1", "title": "p", "status": "done",
                            "tasks": [{"id": "P1.1", "title": "t",
                                       "status": "done", "bugId": "BUG-9"}]}])
        check("gr10b a bug whose fix task is done is CLOSED, on the plugin's own "
              "rule rather than on this file's reading of a stored field",
              decide("git push origin v2.0.2", tmp, "s1") is None)

        write_bugs([{"id": "BUG-2", "status": "open", "severity": "med",
                     "title": "a real one"}])
        got = decide("git push origin v2.0.2", tmp, "s1")
        check("gr11 a release with an open bug is REFUSED, and the refusal names "
              "the bug and the way past it: %r" % (got,),
              got and "BUG-2" in got and KEYWORD in got)
        # THE SECOND-DIRECTION CASE, and the one that looks vacuous: with the plan
        # clean, the same command must go through untouched. A guard that refused
        # unconditionally would pass gr11 and fail here, and it would be the last
        # release this repository ever cut.
        write_bugs([{"id": "BUG-1", "status": "fixed", "severity": "high",
                     "title": "closed"}])
        check("gr12 ...and with every bug closed the same command is allowed",
              decide("git push origin v2.0.2", tmp, "s1") is None)
        write_bugs([{"id": "BUG-2", "status": "open", "severity": "med",
                     "title": "a real one"}])
        check("gr13 ordinary work is allowed even with bugs open - only the "
              "publishing commands are judged",
              decide("git push origin main", tmp, "s1") is None)

        # --- the vocabulary this file RESTATES, driven against its owner -------
        # A hook may not import the plugin, so `CLOSED` above is a copy - and a
        # copy nothing compares is a copy that goes stale silently. The failure
        # is one-directional and expensive: the plugin learns a word that closes
        # a bug, this file does not, and every release afterwards is held by a
        # bug the tracker considers settled. So the source is READ rather than
        # imported, and a file that cannot be read is a FAILURE here rather than
        # a case that quietly passes.
        import ast

        # `<repo>/.claude/hooks/<this file>` - three levels, resolved off
        # `__file__` rather than off the cwd, because the selftest sweep runs
        # every child in a scratch directory it must leave alone.
        repo = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))

        def literal(rel, name):
            """The value assigned to `name` at the top level of `rel`, or None."""
            try:
                with open(os.path.join(repo, rel), "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
            except Exception:
                return None
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        try:
                            return ast.literal_eval(node.value)
                        except Exception:
                            return None
            return None

        vocab = literal(os.path.join("plugins", "audit", "scripts", "manifest",
                                     "_manifest_vocab.py"), "BUG_STATUS")
        human = literal(os.path.join("plugins", "audit", "scripts", "manifest",
                                     "_manifest_io.py"), "HUMAN_BUG_VERDICT")
        check("gr13b the plugin's own bug vocabulary was READ, so the two cases "
              "below are comparisons rather than two Nones agreeing: %r / %r"
              % (vocab, human),
              bool(vocab) and bool(human))
        check("gr13c every word this file treats as closed is a word the plugin "
              "defines - a status invented here would silently stop holding "
              "releases for a bug nothing can be in: %r"
              % (sorted(set(CLOSED) - set(vocab or ())),),
              bool(vocab) and set(CLOSED) <= set(vocab))
        check("gr13d ...and the set is EXACTLY the plugin's own: `fixed`, which "
              "its derivation produces, plus every human verdict it names. An "
              "inclusion alone would pass on a copy that had missed a word, "
              "which is the direction that costs a release: %r vs %r"
              % (sorted(CLOSED), sorted({"fixed"} | set(human or ()))),
              bool(human) and set(CLOSED) == ({"fixed"} | set(human)))
        # AND THE OTHER DIRECTION, so the tuple cannot be widened until it closes
        # everything: at least one word of the vocabulary must still hold a
        # release, or this guard has been turned off by a rewrite of one line.
        check("gr13e SECOND-DIRECTION CASE: some bug status is still OPEN as far "
              "as this guard is concerned - a `CLOSED` widened to the whole "
              "vocabulary would pass every case above and refuse nothing ever "
              "again: %r" % (sorted(set(vocab or ()) - set(CLOSED)),),
              bool(vocab) and bool(set(vocab) - set(CLOSED)))
        # ...and driven end to end on the word that was added, rather than
        # asserted about the tuple alone: a set comparison cannot see a `decide`
        # that reads a different constant.
        write_bugs([{"id": "BUG-7", "status": "not_a_bug", "severity": "high",
                     "title": "investigated; the behaviour is correct"}])
        check("gr13f a bug closed as a verified negative does not hold a "
              "release, driven through `decide` rather than inferred from the "
              "tuple",
              decide("git push origin v2.0.2", tmp, "s1") is None)
        write_bugs([{"id": "BUG-2", "status": "open", "severity": "med",
                     "title": "a real one"}])

        # --- the bypass, both directions -------------------------------------
        slot = os.path.join(tmp, STATE_REL, "release-bypass-s1.json")
        with open(slot, "w", encoding="utf-8") as fh:
            json.dump({"armedAtEpoch": time.time(), "ttlSeconds": 3600}, fh)
        check("gr14 an armed bypass lets the release through",
              decide("git push origin v2.0.2", tmp, "s1") is None)
        check("gr15 ...and it is scoped to the SESSION that armed it - another "
              "session's release is still refused",
              decide("git push origin v2.0.2", tmp, "s2") is not None)
        # An acknowledgement that never expires is an acknowledgement about some
        # other release. Driven by passing the clock rather than by sleeping.
        check("gr16 an EXPIRED bypass does not authorise anything",
              decide("git push origin v2.0.2", tmp, "s1",
                     now=time.time() + 7200) is not None)
        with open(slot, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("gr17 an unreadable slot is not an armed one",
              decide("git push origin v2.0.2", tmp, "s1") is not None)
        os.remove(slot)

        # --- fail LOUD, which is this hook's inversion of the house rule ------
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        got = decide("git push origin v2.0.2", tmp, "s1")
        check("gr18 a manifest that cannot be READ refuses the release and says "
              "so - a pushed tag cannot be taken back, so this is the one guard "
              "here that must not fail open: %r" % (got,),
              got and "UNKNOWN" in got)
        os.remove(mpath)
        check("gr19 ...and a MISSING manifest refuses on the same grounds",
              decide("git push origin v2.0.2", tmp, "s1") is not None)
        check("gr20 but an unreadable manifest still does not block ordinary "
              "work - the failure is scoped to what it protects",
              decide("git push origin main", tmp, "s1") is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # THE REAL PLAN, and it is the only fixture that could have caught the second
    # defect: this repository's manifest is SHARDED, so a raw `json.load` sees
    # phases that are stubs with no tasks and every materialized bug reads open.
    # A hand-built single-file fixture agrees with both readings and proves
    # nothing, which is why this case asks the plugin the same question and
    # demands the two answers match.
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    if os.path.isfile(os.path.join(repo, MANIFEST_REL)):
        mine = read_bugs(repo)[0]
        mio = _effective(repo)
        theirs = None
        try:
            data = mio.load_manifest_safe(os.path.join(repo, MANIFEST_REL))
            by_id = mio.tasks_by_id(data)
            theirs = [b.get("id") for b in (data.get("bugs") or [])
                      if str(mio.effective_bug_status(b, by_id)).lower()
                      not in CLOSED]
        except Exception as exc:
            theirs = "could not ask: %s" % (exc,)
        check("gr21 over the REAL sharded plan this guard counts exactly what "
              "the plugin's own rule counts - mine=%r theirs=%r"
              % ([b[0] for b in mine], theirs),
              [b[0] for b in mine] == theirs)

    # --- provisional phases hold a release too, asked of the plugin's own
    # `full_status` rather than a second rule invented here. A FRESH fixture,
    # never this repository's real plan: BUG-12 sits open in it right now, so
    # only a fixture plan can isolate "no open bug, one provisional phase".
    tmp2 = tempfile.mkdtemp(prefix="guard-release-full-")
    try:
        os.makedirs(os.path.join(tmp2, "docs", "audit"))
        os.makedirs(os.path.join(tmp2, STATE_REL))
        mpath2 = os.path.join(tmp2, MANIFEST_REL)

        def write_plan(meta_extra, phases, bugs=None):
            meta = {"version": 2}
            meta.update(meta_extra or {})
            with open(mpath2, "w", encoding="utf-8") as fh:
                json.dump({"meta": meta, "phases": phases or [],
                           "bugs": bugs or []}, fh)

        modules = _evidence_modules(tmp2)
        check("gr22 the evidence and ancestry modules load from this "
              "repository's own scripts/ - what read_provisional needs to "
              "ask full_status anything at all",
              modules is not None)

        # RED-FIRST: a merged phase with a declared fullGate and NO recorded
        # full run at all reads PROVISIONAL (full_status's own "no full-scope
        # run has ever been recorded" answer) - and that alone must hold a
        # release exactly like an open bug does.
        write_plan({"fullGate": ["full"],
                   "buildCommands": {"full": "echo full"}},
                  [{"id": "P1", "title": "p", "status": "done",
                    "mergedAt": "2026-01-01T00:00:00Z",
                    "mergedHead": "a" * 40, "tasks": []}])
        provisional, problem = read_provisional(tmp2)
        check("gr23 RED-FIRST: a merged phase this ledger has never recorded "
              "a full run for reads PROVISIONAL, with no problem to report: "
              "%r / %r" % (provisional, problem),
              problem is None and [p[0] for p in provisional] == ["P1"])
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr24 RED-FIRST (dg13): no open bug and one provisional phase "
              "still REFUSES `git tag v1` - the mutation this guards is "
              "`decide` reading only the bugs: %r" % (got,),
              got and "P1" in got and "provisional" in got)

        # ALLOW (dg13): the SAME plan with no meta.fullGate at all has
        # nothing provisional to ask about, and behaves exactly as it did
        # before this function existed.
        write_plan({}, [{"id": "P1", "title": "p", "status": "done",
                        "mergedAt": "2026-01-01T00:00:00Z",
                        "mergedHead": "a" * 40, "tasks": []}])
        check("gr25 ALLOW: no meta.fullGate at all means nothing is "
              "provisional, and the release goes through",
              decide("git tag -a v1 -m x", tmp2, "s1") is None)

        # ALLOW (dg13): ordinary work is never refused by a provisional
        # phase either - only the publishing commands are judged.
        write_plan({"fullGate": ["full"],
                   "buildCommands": {"full": "echo full"}},
                  [{"id": "P1", "title": "p", "status": "done",
                    "mergedAt": "2026-01-01T00:00:00Z",
                    "mergedHead": "a" * 40, "tasks": []}])
        check("gr26 ALLOW: `git push origin main` is not refused by a "
              "provisional phase - it is not a publishing command",
              decide("git push origin main", tmp2, "s1") is None)

        # RED-FIRST: an unreadable ledger is a PROBLEM, never "nothing
        # provisional" - fail-loud extended to this second list.
        edir = os.path.join(tmp2, "docs", "audit", "evidence")
        os.makedirs(edir, exist_ok=True)
        with open(os.path.join(edir, "2026-01.broken.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"not": "chained"}\n{also not valid json\n')
        provisional, problem = read_provisional(tmp2)
        check("gr27 RED-FIRST: a ledger carrying a torn line is a PROBLEM, "
              "not an empty provisional list: %r / %r"
              % (provisional, problem),
              provisional == [] and bool(problem))
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr28 ...and `decide` refuses over that problem, naming it "
              "UNKNOWN exactly like an unreadable manifest does: %r" % (got,),
              got and "UNKNOWN" in got)
        os.remove(os.path.join(edir, "2026-01.broken.jsonl"))

        # ALLOW: the same phase made WHOLE by a real recorded full run whose
        # head really does contain mergedHead - a REAL repo, never two
        # strings compared for equality, for the reason `test__evidence_io`'s
        # own fixture states: a mutation comparing `head == mergedHead` would
        # still pass against two equal fixture strings.
        evidence_io = modules[0]
        git = ["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
              "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]

        def sh(*args):
            subprocess.run(git + list(args), cwd=tmp2, check=True,
                          capture_output=True, timeout=30)

        def rev():
            out = subprocess.run(git + ["rev-parse", "HEAD"], cwd=tmp2,
                                 check=True, capture_output=True, timeout=30)
            return out.stdout.decode("utf-8").strip()

        sh("init", "-q")
        with open(os.path.join(tmp2, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("1\n")
        sh("add", "-A")
        sh("commit", "-qm", "one")
        merged_head = rev()
        with open(os.path.join(tmp2, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("2\n")
        sh("add", "-A")
        sh("commit", "-qm", "two")
        full_head = rev()

        write_plan({"fullGate": ["full"], "nodePreamble": "export X=1",
                   "buildCommands": {"full": "echo full"}},
                  [{"id": "P1", "title": "p", "status": "done",
                    "mergedAt": "2026-01-01T00:00:00Z",
                    "mergedHead": merged_head, "tasks": []}])
        with open(mpath2, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
        full_commands = [c for _n, c in
                        evidence_io.resolved_commands(plan, ["full"])]
        row = {
            "v": evidence_io.ROW_VERSION, "runId": "run-whole",
            "ts": "2026-01-02T00:00:00Z", "scope": evidence_io.FULL_SCOPE,
            "status": "passed",
            "steps": [{"name": "gate", "command": c, "exit": 0,
                      "durationMs": 1000} for c in full_commands],
            "testedState": {"head": full_head},
            "observations": {"ranTotal": 1, "countsBasis": "1 check",
                             "dirtyOutside": []},
        }
        evidence_io.append_row(tmp2, row, writer="selftest")
        provisional, problem = read_provisional(tmp2)
        check("gr29 ALLOW: a real recorded full run whose head really "
              "contains mergedHead reads WHOLE, not provisional: %r / %r"
              % (provisional, problem),
              problem is None and provisional == [])
        check("gr30 ALLOW (dg13): ...and the release goes through",
              decide("git tag -a v1 -m x", tmp2, "s1") is None)

        # THE MUTATION THIS PROVES AGAINST, DRIVEN RATHER THAN ASSERTED: the
        # SAME row read against the bare `meta.fullGate` entries - no
        # `resolved_commands`, no preamble - does not match this run's
        # published commands, so a `read_provisional` that skipped the
        # resolution would disqualify a run that really did measure the
        # declared gate and hold this release open forever.
        bare = evidence_io.full_status(
            evidence_io.read_rows(tmp2).get("rows") or [],
            {"id": "P1", "mergedHead": merged_head}, tmp2, ["full"])
        vocab = modules[2]
        check("gr31 the bare fullGate entry (no preamble, no buildCommands "
              "resolution) does NOT read WHOLE against this run's published "
              "commands - the shape a preamble-skipping mutation would "
              "break: %r" % (bare,),
              bare["answer"] != vocab.FULL_STATUS_WHOLE)

        # --- P72: the tree a release is judged against comes from
        # `_config.tree_for`, never `CLAUDE_PROJECT_DIR` read a second time --
        check("gr32 resolved_tree with NO payload leaves the tree exactly as "
              "`project` - the reading every call above this point made, "
              "unconditionally",
              resolved_tree(None, tmp2) == tmp2)
        payload_here = {"cwd": tmp2,
                        "tool_input": {"command": "git tag -a v1 -m x"}}
        check("gr33 resolved_tree asked about a command whose shell never "
              "leaves the session's own directory answers with that SAME "
              "directory - `tree_for` reached and agreeing, not a second "
              "tree invented for the ordinary call",
              resolved_tree(payload_here, tmp2) == tmp2)
        wt = tempfile.mkdtemp(prefix="guard-release-wt-")
        shutil.rmtree(wt)
        subprocess.run(git + ["worktree", "add", "-b", "gr34-side", wt],
                      cwd=tmp2, check=True, capture_output=True, timeout=30)
        try:
            payload_elsewhere = {"cwd": tmp2, "tool_input": {
                "command": "cd %s && git tag -a v1 -m x" % (wt,)}}
            moved = resolved_tree(payload_elsewhere, tmp2)
            check("gr34 ...and a command that `cd`s into a LINKED WORKTREE "
                  "before tagging is judged against THAT worktree's own "
                  "plan, never `project`'s - a release typed there must "
                  "answer for what IT carries, not for wherever "
                  "CLAUDE_PROJECT_DIR happened to point (P72): %r"
                  % (moved,),
                  os.path.realpath(moved) == os.path.realpath(wt))
        finally:
            subprocess.run(git + ["worktree", "remove", "--force", wt],
                          cwd=tmp2, check=True, capture_output=True,
                          timeout=30)
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    print("")
    print("%s: %d/%d cases passed"
          % ("ALL PASS" if not failed else "SELFTEST FAILED",
             len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
