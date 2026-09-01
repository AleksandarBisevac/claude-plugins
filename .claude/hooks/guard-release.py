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

THE WAY PAST IT is `arm-release-bypass.py`: the maintainer types the keyword and a
single-use slot appears. Nothing the model writes can arm it. That is why the
switch is on the prompt and not on this command - a guard the caller can satisfy
by writing the right words is not a guard.

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
import sys
import time

STATE_REL = os.path.join(".claude", "state")
MANIFEST_REL = os.path.join("docs", "audit", "audit-plan.json")
CLOSED = ("fixed", "wontfix")
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


def refusal(why, bugs, problem):
    """The sentence a refused release reads, naming what to do about it."""
    if problem:
        return ("this command %s, and whether the plan carries open bugs is "
                "UNKNOWN: %s. A pushed tag is never moved here, so this refuses "
                "rather than guessing. Fix the file, or type %s to release "
                "anyway." % (why, problem, KEYWORD))
    listed = "; ".join("%s (%s) %s" % (b[0], b[1], b[2][:70]) for b in bugs)
    return ("this command %s while %d bug(s) are open in the plan: %s. Close "
            "them, or type %s in your own message to release over them - the "
            "keyword only counts from you, which is why it is read off the "
            "prompt and not off this command."
            % (why, len(bugs), listed, KEYWORD))


def decide(command, project, session_id, now=None):
    """`reason` when the call must be denied, else None. The whole rule, in one
    pure-ish function so its cases need no hook payload."""
    why = publishing(command)
    if not why:
        return None
    bugs, problem = read_bugs(project)
    if not bugs and not problem:
        return None
    if bypass_armed(project, session_id, now):
        return None
    return refusal(why, bugs, problem)


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
                    str(payload.get("session_id") or ""))
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

    print("")
    print("%s: %d/%d cases passed"
          % ("ALL PASS" if not failed else "SELFTEST FAILED",
             len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
