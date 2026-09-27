#!/usr/bin/env python3
"""
UserPromptSubmit hook — arm the release-with-open-bugs bypass. THIS REPO'S OWN
CONFIGURATION, not the audit plugin's product.

WHY IT EXISTS. Two releases went out over four open bugs and nothing said a word.
`v2.0.0` and `v2.0.1` were both cut while those bugs sat `open` in
`docs/audit/audit-plan.json`, and a bug reported DURING the second one was written
into a scratch plan file no gate reads. Every one of the twenty-one gates was
green and truthfully so: not one of them asked whether the plan still carried
open bugs. A rule nobody can forget is worth more than the intention to remember.

So `guard-release.py` refuses a tag, a tag push or a `gh release create` while any
bug is open or any merged phase is provisional or unanswerable — and THIS file is
the only way past it. The maintainer types the
keyword; nothing the model writes can arm it, which is the whole point of putting
the switch on the prompt rather than on the command.

THE SHAPE IS BORROWED, deliberately, from `detect-plan-skip.py` one directory over:
a keyword in a submitted prompt arms a single-use, TTL'd slot in a state file, and
a PreToolUse guard observes it. That mechanism is already proven here, and a second
design for the same job would be a second set of edge cases.

WHAT THE ARMING MESSAGE SAYS, and why it is not a bare acknowledgement. The
maintainer chose one blanket phrase over naming each bug, so the friction that
would have kept them aware is gone; the message NAMES the open bugs and the held
phases instead. The
cost of a blanket phrase is that it becomes reflex, and the mitigation that
survives that is being told, at the moment of arming, exactly what is being
shipped over.

Single-use and time-limited for the same reason the plan bypass is: an
acknowledgement left armed is an acknowledgement that has stopped being about
this release.

Never blocks a prompt. Emits {"systemMessage": ...} on stdout and exits 0.

Exit codes: 0 always - a hook that fails a prompt over its own bug is worse than
one that says nothing.
"""
import json
import os
import re
import sys
import time

# The phrase the maintainer types. Not configurable through
# `.claude/audit.config.json`: that file is the PLUGIN's, and this is one
# repository's release discipline, so its switch lives with it.
KEYWORD = "#release-with-bugs"
# Long enough to finish a release, short enough that yesterday's acknowledgement
# cannot authorise today's. The plan bypass uses thirty minutes for the narrower
# job of one edit; a release is a longer errand.
TTL_SECONDS = 3600
STATE_REL = os.path.join(".claude", "state")
MANIFEST_REL = os.path.join("docs", "audit", "audit-plan.json")
CLOSED = ("fixed", "wontfix")


def project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _load_guard():
    """`guard-release.py`, loaded BY PATH - its name is hyphenated and
    `import` cannot spell it, the same reason the plugin's own hook tests
    load their subjects this way. Shared by `open_bugs` and
    `held_phases`: both ask the guard's own reading rather than
    rebuilding it, so this file cannot come to disagree with the guard it
    is arming a bypass for."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "audit_repo_guard_release", os.path.join(here, "guard-release.py"))
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        return guard
    except Exception:
        return None


GUARD_UNLOADED = ("the release guard could not be loaded from "
                  ".claude/hooks/guard-release.py, so this list cannot be read "
                  "here")


def open_bugs(project):
    """`([(id, severity, title)], problem)` - every bug the plan still calls
    open, or why that list could not be read.

    THE GUARD'S OWN READING, borrowed rather than rebuilt. Naming a different set
    of bugs in the arming message than the guard refuses over would be two
    answers to one question, and this file would be the one lying. It also
    inherits both defects the guard's first draft had and fixed: the status is
    the EFFECTIVE one, and the manifest is the ASSEMBLED one - a raw read of this
    repository's sharded plan reports five open bugs where one is.

    THE PROBLEM TRAVELS WITH THE LIST. A list the guard could not read is one
    it refuses over as UNKNOWN, and the armed slot releases over that refusal
    too - so reducing it to an empty list here would tell the maintainer the
    slot authorises nothing at the moment it authorises exactly that.
    """
    guard = _load_guard()
    if guard is None:
        return ([], GUARD_UNLOADED)
    return guard.read_bugs(project)


def held_phases(project):
    """`([(phaseId, kind, basis, headRecorded)], problem)` - every merged phase the guard's
    own `read_held_phases` says holds a release, provisional or unanswerable,
    or why that list could not be read: the SAME reading `guard-release.py`
    refuses releases over, problem included, for the reason `open_bugs`
    gives."""
    guard = _load_guard()
    if guard is None:
        return ([], GUARD_UNLOADED)
    return guard.read_held_phases(project)


def arm(project, session_id):
    """Write the single-use slot. Returns the path, or None when it could not."""
    state = os.path.join(project, STATE_REL)
    try:
        if not os.path.isdir(state):
            os.makedirs(state)
        path = os.path.join(state, "release-bypass-%s.json" % (session_id or "none",))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"armedAtEpoch": time.time(),
                       "ttlSeconds": TTL_SECONDS}, fh)
        return path
    except Exception:
        return None


def message(bug_read, held_read, armed):
    """What the maintainer is told at the moment they authorise this - the
    open bugs, the provisional phases and the unanswerable phases each named
    on its own, never folded into one count, because each is settled a
    different way: a bug is closed, a provisional phase needs a full run, and
    an unanswerable one needs its merge record repaired before a run can
    settle it. `kind` is the guard's own word for each phase.

    `bug_read` and `held_read` are the `(list, problem)` pairs `open_bugs` and
    `held_phases` return. A list with a problem is named UNKNOWN, with the
    reason, as something the slot releases over - never counted as empty."""
    bugs, bug_problem = bug_read
    held, phase_problem = held_read
    if GUARD_UNLOADED in (bug_problem, phase_problem):
        # Not an unknown list: the guard being off. A PreToolUse hook that
        # cannot load refuses nothing, so the slot is the least of it.
        return ("release bypass %s, but the release guard itself could not "
                "be loaded from .claude/hooks/guard-release.py. If it cannot "
                "load as a hook either, it is refusing nothing at all - with "
                "or without this bypass - so fix the guard file before "
                "releasing." % ("armed" if armed else "could NOT be armed",))
    if not armed:
        return ("release bypass could NOT be armed - the state directory is not "
                "writable, so the release guard will still refuse. Fix the "
                "directory rather than working around the guard.")
    if not (bugs or held or bug_problem or phase_problem):
        return ("release bypass armed, and the plan currently carries no open "
                "bug and no provisional or unanswerable phase - so it "
                "authorises nothing. It expires unused.")
    parts = []
    if bug_problem:
        parts.append("a bug list that is UNKNOWN (%s)" % (bug_problem,))
    if phase_problem:
        parts.append("a merged-phase list that is UNKNOWN (%s)"
                     % (phase_problem,))
    if bugs:
        listed = "; ".join("%s (%s) %s" % (b[0], b[1], b[2][:60]) for b in bugs)
        parts.append("%d open bug(s): %s" % (len(bugs), listed))
    # The guard's own cap on a basis, so the two surfaces cut a reason at the
    # same place; no cut at all if the guard cannot say.
    cap = getattr(_load_guard(), "BASIS_CAP", None) if held else None
    # Grouped by the guard's own word, in the order it first appears, so no
    # second copy of that vocabulary lives in this file.
    kinds = []
    for h in held:
        if h[1] not in kinds:
            kinds.append(h[1])
    for kind in kinds:
        picked = [h for h in held if h[1] == kind]
        if picked:
            listed = "; ".join("%s (%s)" % (h[0], h[2][:cap]) for h in picked)
            parts.append("%d %s phase(s): %s" % (len(picked), kind, listed))
    return ("release bypass armed for this session, single use. You are "
            "releasing over %s. It expires unused in %d minutes."
            % ("; and ".join(parts), TTL_SECONDS // 60))


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = str(payload.get("prompt") or "")
    # Case-insensitive and whole-word, so `#release-with-bugs-later` in a
    # sentence about the keyword does not arm anything.
    if not re.search(r"(?i)(?:^|\s)" + re.escape(KEYWORD) + r"(?:\s|$|[.,!])",
                     prompt):
        return 0
    project = project_dir()
    bug_read = open_bugs(project)
    held_read = held_phases(project)
    armed = arm(project, str(payload.get("session_id") or ""))
    sys.stdout.write(json.dumps(
        {"systemMessage": message(bug_read, held_read, armed)}))
    return 0


def _selftest():
    """Cases: plugins/audit/tests/ is the PLUGIN's suite and this is not the
    plugin, so the cases live beside the file they test."""
    import shutil
    import tempfile
    cases, failed = [], []

    def check(label, cond, detail=""):
        cases.append(label)
        if not cond:
            failed.append("%s (%s)" % (label, detail))
        print(("PASS " if cond else "FAIL ") + label)

    pat = r"(?i)(?:^|\s)" + re.escape(KEYWORD) + r"(?:\s|$|[.,!])"
    check("rb1 the keyword arms on its own line",
          bool(re.search(pat, "#release-with-bugs")))
    check("rb2 ...and inside a sentence",
          bool(re.search(pat, "go ahead, #release-with-bugs please")))
    # THE SECOND DIRECTION. A substring test passes rb1 and rb2 and fails these,
    # and it would arm on a prompt that is talking ABOUT the keyword rather than
    # typing it - which is exactly what this docstring does.
    check("rb3 a longer word carrying it does NOT arm",
          not re.search(pat, "use #release-with-bugs-later for that"))
    check("rb4 an ordinary prompt does not arm",
          not re.search(pat, "please fix the panel detail row"))

    tmp = tempfile.mkdtemp(prefix="release-bypass-")
    try:
        os.makedirs(os.path.join(tmp, "docs", "audit"))
        mpath = os.path.join(tmp, MANIFEST_REL)
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump({"bugs": [
                {"id": "BUG-1", "status": "fixed", "severity": "high", "title": "a"},
                {"id": "BUG-2", "status": "open", "severity": "med", "title": "b"},
                {"id": "BUG-3", "status": "wontfix", "severity": "low", "title": "c"},
            ]}, fh)
        got = open_bugs(tmp)
        check("rb5 only the OPEN bug is counted - fixed and wontfix are closed "
              "states and a guard that counted them would never let anything "
              "ship: %r" % (got,),
              [b[0] for b in got[0]] == ["BUG-2"] and got[1] is None)
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        got = open_bugs(tmp)
        check("rb6 an unreadable manifest yields no bugs AND the reason the "
              "list is unknown - the guard refuses over exactly that, so an "
              "empty list alone would understate what the slot releases "
              "over: %r" % (got,),
              got[0] == [] and bool(got[1]))
        shutil.rmtree(os.path.join(tmp, "docs"))
        got = open_bugs(tmp)
        check("rb7 ...and a project with no manifest at all carries its "
              "reason the same way: %r" % (got,),
              got[0] == [] and bool(got[1]))
        path = arm(tmp, "s1")
        check("rb8 arming writes a slot carrying WHEN it was armed, which is "
              "what lets the guard expire it",
              bool(path) and os.path.isfile(path)
              and "armedAtEpoch" in json.load(open(path, encoding="utf-8")))
        msg = message(([("BUG-2", "med", "a thing that is wrong")], None),
                      ([], None), path)
        check("rb9 the arming message NAMES the bugs being shipped over - the "
              "blanket phrase costs the friction that kept a reader aware, and "
              "being told at the moment of arming is what replaces it: %r" % (msg,),
              "BUG-2" in msg and "1 open bug" in msg)
        clean = message(([], None), ([], None), path)
        check("rb10 ...and with nothing open or provisional it says the "
              "bypass authorises nothing, rather than congratulating anyone: "
              "%r" % (clean,),
              "authorises nothing" in clean)
        broken = message(([("BUG-2", "med", "x")], None), ([], None), None)
        check("rb11 a bypass that could NOT be armed says so instead of "
              "reporting success - a reader who thinks it is armed will be "
              "refused later with no idea why: %r" % (broken,),
              "could NOT be armed" in broken)

        # --- the SECOND list, beside the bugs, through the guard's OWN reading -
        got_p = held_phases(tmp)
        check("rb12 with no manifest at all, held_phases names no phase and "
              "carries the reason, as open_bugs does: %r" % (got_p,),
              got_p[0] == [] and bool(got_p[1]))
        os.makedirs(os.path.join(tmp, "docs", "audit"))
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"fullGate": ["full"],
                               "buildCommands": {"full": "echo full"}},
                      "phases": [{"id": "P9", "title": "p", "status": "done",
                                 "mergedAt": "2026-01-01T00:00:00Z",
                                 "mergedHead": "b" * 40, "tasks": []}],
                      "bugs": []}, fh)
        got_p = held_phases(tmp)
        check("rb13 RED-FIRST: a merged phase this ledger has recorded no "
              "full run for is named by held_phases, driven through "
              "the GUARD's own `read_held_phases` rather than a second rule "
              "invented here: %r" % (got_p,),
              [p[0] for p in got_p[0]] == ["P9"] and got_p[1] is None)
        msg_p = message(([], None), got_p, path)
        check("rb14 the arming message names the PROVISIONAL phase beside "
              "the (empty) bugs list, through the same reading: %r" % (msg_p,),
              "P9" in msg_p and "provisional phase" in msg_p)

        # A merged phase the evidence cannot answer for holds a release as
        # surely as a provisional one, so the maintainer arming past it is
        # told so - by name, with the guard's basis, and apart from the
        # provisional phases because it is settled a different way.
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"fullGate": ["full"],
                               "buildCommands": {"full": "echo full"}},
                      "phases": [{"id": "P8", "title": "p", "status": "done",
                                 "mergedAt": "2026-01-01T00:00:00Z",
                                 "tasks": []}],
                      "bugs": []}, fh)
        msg_u = message(([], None), held_phases(tmp), path)
        check("rb15 RED-FIRST: a merged phase with no mergedHead is named in "
              "the arming message with the guard's basis, as unanswerable "
              "rather than provisional: %r" % (msg_u,),
              "P8" in msg_u and "records no mergedHead" in msg_u
              and "unanswerable" in msg_u and "provisional phase" not in msg_u)

        # THE HOOK AS A PROCESS, over a plan nobody can parse. The guard
        # refuses that release UNKNOWN and the armed slot lets it through, so
        # a message saying the slot "authorises nothing" is false - it
        # authorises exactly the release the maintainer cannot see into.
        import subprocess
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = tmp
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__)],
            input=json.dumps({"prompt": KEYWORD, "session_id": "s9"}),
            capture_output=True, text=True, cwd=tmp, env=env, timeout=120)
        try:
            said = json.loads(proc.stdout).get("systemMessage") or ""
        except Exception:
            said = "unparsable hook output: %r" % (proc.stdout,)
        check("rb16 RED-FIRST: over an unparsable plan the arming message "
              "names the lists UNKNOWN and says the slot authorises a release "
              "over them, never that it authorises nothing: %r" % (said,),
              "UNKNOWN" in said and "authorises nothing" not in said)

        # THE GUARD ITSELF UNLOADABLE. If this file cannot load it, the hook
        # runner probably cannot either - and a PreToolUse hook that fails to
        # load refuses nothing. That is not an unknown list; it is the guard
        # being off, and the message must say so in those words.
        own = globals()
        saved = own["_load_guard"]
        own["_load_guard"] = lambda: None
        try:
            msg_g = message(open_bugs(tmp), held_phases(tmp), path)
        finally:
            own["_load_guard"] = saved
        check("rb17 RED-FIRST: with the release guard unloadable, the arming "
              "message says the guard itself could not be loaded, that it "
              "may be refusing nothing, and that the guard file needs "
              "fixing: %r" % (msg_g,),
              "guard itself could not be loaded" in msg_g
              and "refusing nothing" in msg_g and "fix" in msg_g)

        # ONE CAP ON A BASIS FOR BOTH SURFACES. A recorded-but-unresolvable
        # head's basis names two commit ids before it says why git could not
        # answer, so a cap narrower than the guard's cuts exactly the reason.
        basis = ("whether %s is contained in run run-x's head could not be "
                 "established: git said the object is missing" % ("c" * 40,))
        msg_b = message(([], None),
                        ([("P3", "unanswerable", basis, True)], None), path)
        check("rb18 RED-FIRST: the arming message keeps a recorded-but-"
              "unresolvable head's reason, on the guard's own cap: %r"
              % (msg_b,),
              "could not be established" in msg_b)

        # THE FULL LIST IN THE ARMING MESSAGE, even where the guard's refusal
        # summarises its tail: this is the moment the maintainer authorises
        # shipping over every one of them.
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"fullGate": ["full"],
                               "buildCommands": {"full": "echo full"}},
                      "phases": [{"id": "Q%02d" % (i,), "title": "m",
                                 "status": "done",
                                 "mergedAt": "2026-01-01T00:00:00Z",
                                 "tasks": []} for i in range(1, 13)],
                      "bugs": []}, fh)
        msg_all = message(([], None), held_phases(tmp), path)
        check("rb19 the arming message names EVERY held phase, never a "
              "summarised tail: %r" % (msg_all,),
              all(("Q%02d" % (i,)) in msg_all for i in range(1, 13))
              and "more -" not in msg_all)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    print("%s: %d/%d cases passed"
          % ("ALL PASS" if not failed else "SELFTEST FAILED",
             len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
