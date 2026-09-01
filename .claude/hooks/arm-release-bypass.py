#!/usr/bin/env python3
"""
UserPromptSubmit hook — arm the release-with-open-bugs bypass. THIS REPO'S OWN
CONFIGURATION, not the audit plugin's product.

WHY IT EXISTS. Two releases went out over four open bugs and nothing said a word.
`v2.0.0` and `v2.0.1` were both cut while BUG-2 through BUG-5 sat `open` in
`docs/audit/audit-plan.json`, and a bug reported DURING the second one was written
into a scratch plan file no gate reads. Every one of the twenty-one gates was
green and truthfully so: not one of them asked whether the plan still carried
open bugs. A rule nobody can forget is worth more than the intention to remember.

So `guard-release.py` refuses a tag, a tag push or a `gh release create` while any
bug is open — and THIS file is the only way past it. The maintainer types the
keyword; nothing the model writes can arm it, which is the whole point of putting
the switch on the prompt rather than on the command.

THE SHAPE IS BORROWED, deliberately, from `detect-plan-skip.py` one directory over:
a keyword in a submitted prompt arms a single-use, TTL'd slot in a state file, and
a PreToolUse guard observes it. That mechanism is already proven here, and a second
design for the same job would be a second set of edge cases.

WHAT THE ARMING MESSAGE SAYS, and why it is not a bare acknowledgement. The
maintainer chose one blanket phrase over naming each bug, so the friction that
would have kept them aware is gone; the message NAMES the open bugs instead. The
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


def open_bugs(project):
    """`[(id, severity, title)]` for every bug the plan still calls open.

    THE GUARD'S OWN READING, borrowed rather than rebuilt. Naming a different set
    of bugs in the arming message than the guard refuses over would be two
    answers to one question, and this file would be the one lying. It also
    inherits both defects the guard's first draft had and fixed: the status is
    the EFFECTIVE one, and the manifest is the ASSEMBLED one - a raw read of this
    repository's sharded plan reports five open bugs where one is.

    A manifest that cannot be read returns an empty list here and the guard
    reports the failure itself: two hooks blaming each other for one unreadable
    file is how a reader learns nothing.
    """
    # By PATH, because the sibling's name is hyphenated and `import` cannot spell
    # it - the same reason the plugin's own hook tests load their subjects this way.
    here = os.path.dirname(os.path.abspath(__file__))
    guard = None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "audit_repo_guard_release", os.path.join(here, "guard-release.py"))
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
    except Exception:
        guard = None
    if guard is None:
        # The sibling could not be loaded. Say nothing about bugs rather than
        # inventing a second rule for them; the guard still decides the release.
        return []
    return guard.read_bugs(project)[0]


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


def message(bugs, armed):
    """What the maintainer is told at the moment they authorise this."""
    if not armed:
        return ("release bypass could NOT be armed - the state directory is not "
                "writable, so the release guard will still refuse. Fix the "
                "directory rather than working around the guard.")
    if not bugs:
        return ("release bypass armed, and the plan currently carries no open "
                "bug - so it authorises nothing. It expires unused.")
    listed = "; ".join("%s (%s) %s" % (b[0], b[1], b[2][:60]) for b in bugs)
    return ("release bypass armed for this session, single use. You are "
            "releasing over %d open bug(s): %s. It expires unused in %d "
            "minutes." % (len(bugs), listed, TTL_SECONDS // 60))


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
    bugs = open_bugs(project)
    armed = arm(project, str(payload.get("session_id") or ""))
    sys.stdout.write(json.dumps({"systemMessage": message(bugs, armed)}))
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
              [b[0] for b in got] == ["BUG-2"])
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("rb6 an unreadable manifest yields no bugs HERE - the guard is "
              "what reports that failure, so the two hooks cannot blame each "
              "other for one broken file",
              open_bugs(tmp) == [])
        shutil.rmtree(os.path.join(tmp, "docs"))
        check("rb7 a project with no manifest at all is not an error either",
              open_bugs(tmp) == [])
        path = arm(tmp, "s1")
        check("rb8 arming writes a slot carrying WHEN it was armed, which is "
              "what lets the guard expire it",
              bool(path) and os.path.isfile(path)
              and "armedAtEpoch" in json.load(open(path, encoding="utf-8")))
        msg = message([("BUG-2", "med", "a thing that is wrong")], path)
        check("rb9 the arming message NAMES the bugs being shipped over - the "
              "blanket phrase costs the friction that kept a reader aware, and "
              "being told at the moment of arming is what replaces it: %r" % (msg,),
              "BUG-2" in msg and "1 open bug" in msg)
        clean = message([], path)
        check("rb10 ...and with nothing open it says the bypass authorises "
              "nothing, rather than congratulating anyone: %r" % (clean,),
              "authorises nothing" in clean)
        broken = message([("BUG-2", "med", "x")], None)
        check("rb11 a bypass that could NOT be armed says so instead of "
              "reporting success - a reader who thinks it is armed will be "
              "refused later with no idea why: %r" % (broken,),
              "could NOT be armed" in broken)
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
