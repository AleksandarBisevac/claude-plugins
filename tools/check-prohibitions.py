#!/usr/bin/env python3
"""Every absolute prohibition the orchestrator states is enforced, or says it is not.

WHY THIS EXISTS, and it is a measurement rather than a worry. `reference/
orchestrator.md` governs every run, and a prose mutation sweep over it found that
**deleting any one of its `##` sections is noticed by nothing** - not by the
selftest sweep, not by gate-parity. Exactly one sentence in the whole document is
anchored by a gate, and it survives a section deletion only because it appears
twice. So the document is, mechanically, unchecked. Re-derive the figures rather
than trusting a copy of them here:

    python3 tools/check-prohibitions.py --json

That is tolerable for prose that EXPLAINS. It is not tolerable for prose that
PROHIBITS, because a prohibition nothing enforces is a rule that holds until a
session forgets - which is the argument `journal-writes.py` already makes against
putting a rule in a prompt, in its own docstring.

Measured before this existed: the document says **"NEVER `git push` or
force-push"**, and of that pair only force-push is refused by a hook. `git push`
and `git stash` were both ALLOWED by every guard in the plugin. The most
emphatic rule in the file was half-enforced, and nothing could say so.

WHAT IT CHECKS, in both directions:

  * every prohibition in the document appears in `ENFORCED` or `ADVISORY`;
  * every hook named in `ENFORCED` really refuses the command it claims to -
    DRIVEN, not asserted, because a table naming a hook that stopped refusing
    reads exactly like one that still does;
  * every `ADVISORY` row carries a reason long enough to be one, and its rule
    still appears in the document - a table that only grows stops describing
    the system.

THIS IS A TOOL AND NOT A LINT because it spawns hook processes: a per-commit
gate that starts subprocesses is a gate somebody disables. It belongs beside
`check-git-pipeline.py`, which builds a real repository for the same reason.

Exit codes: 0 every prohibition accounted for - 1 findings - 2 usage error.
"""
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "plugins", "audit", "scripts"))

import _output  # noqa: E402  (the anchor: install_path, safe_stdio)

_output.install_path()

E_OK, E_FAIL, E_USAGE = 0, 1, 2

DOC = os.path.join(REPO, "plugins", "audit", "reference", "orchestrator.md")
HOOKS = os.path.join(REPO, "plugins", "audit", "hooks")

# A prohibition is a bolded NEVER naming a command. The narrowing is deliberate:
# `never goes out of date` is prose about a manifest, not a rule about an action,
# and a census that swept those in would be a census nobody reads. The cost of the
# narrowing is stated rather than hidden - a prohibition written without the bold
# is invisible here, and `unbolded_prohibitions()` below reports that separately
# so the blind spot is visible rather than silent.
_BOLD_NEVER = re.compile(r"\*\*[^*]*\bNEVER\b[^*]*\*\*")
_COMMAND = re.compile(r"`([a-z][a-z0-9 _.-]{2,40})`")

# rule token -> (the hook that refuses it, a command it must refuse)
ENFORCED = {
    "git push --force": ("guard-history-rewrite.py", "git push --force origin main"),
    "rebase": ("guard-history-rewrite.py", "git rebase -i main"),
    "filter-branch": ("guard-history-rewrite.py", "git filter-branch -f"),
}

# rule token -> why no hook refuses it. A reason, not a label: it has to say what
# would have to be true for the rule to be enforceable, so a reader can tell a
# decision from an omission.
ADVISORY = {
    "git push": (
        "MEASURED UNENFORCED, and recorded rather than quietly accepted: every "
        "guard in the plugin allows `git push origin main` today, so this "
        "prohibition rests entirely on the model reading the sentence. A hook "
        "would be cheap; what it costs is that a human running the same session "
        "cannot push either, which is why it is a decision and not an oversight."),
    "git stash": (
        "MEASURED UNENFORCED for the same reason as `git push` above. Stash is "
        "harder to guard than it looks: the danger is a stash that is never "
        "popped, which is a state rather than a command, and a hook refusing the "
        "verb outright would block the legitimate rescue use."),
    "task.complete": (
        "ADVISORY BY CONSTRUCTION rather than by omission. The rule is that "
        "completion rows are hook-derived and must not be appended by hand, and "
        "the hook that derives them cannot also refuse a hand-written one: it "
        "fires on the write that WOULD produce the row, so a person appending "
        "the row directly is doing the thing it is downstream of. Enforcing this "
        "belongs to the journal's own hash chain, which already reports a row "
        "nothing wrote - `/audit:logs verify` is where it surfaces."),
}

_REASON_MIN = 80


def prohibitions(text=None):
    """Every bolded NEVER in the document, as (sentence, [commands it names])."""
    body = text if text is not None else io.open(DOC, encoding="utf-8").read()
    out = []
    for m in _BOLD_NEVER.finditer(body):
        sentence = " ".join(m.group(0).split())
        out.append((sentence, _COMMAND.findall(m.group(0))))
    return out


def refuses(hook, command):
    """Does this hook refuse this command? DRIVEN, the way Claude Code drives it.

    A table that named a hook and never asked it would go on passing after the
    hook stopped refusing - which is the failure this whole file is about, one
    level down.
    """
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                          "tool_input": {"command": command}, "cwd": REPO})
    try:
        done = subprocess.run([sys.executable, os.path.join(HOOKS, hook)],
                              input=payload.encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              cwd=REPO, timeout=60)
    except Exception as exc:
        return None, "could not be run (%s)" % (exc,)
    blob = ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8", "replace")
    denied = "deny" in blob.lower() or done.returncode == 2
    return denied, blob.strip()[:120]


def prohibition_drift(text=None):
    """[(subject, problem)] - every prohibition nothing accounts for, both ways."""
    out = []
    body = text if text is not None else io.open(DOC, encoding="utf-8").read()
    known = dict(ENFORCED)
    seen = set()
    for sentence, cmds in prohibitions(body):
        matched = False
        for token in list(known) + list(ADVISORY):
            if token in sentence:
                matched = True
                seen.add(token)
        if not matched:
            out.append((sentence[:70],
                        "an absolute prohibition in neither ENFORCED nor "
                        "ADVISORY, so nothing says whether anything stops it"))
    # the tables are checked against reality, not trusted
    for token, (hook, command) in sorted(ENFORCED.items()):
        denied, why = refuses(hook, command)
        if denied is None:
            out.append((token, "%s %s" % (hook, why)))
        elif not denied:
            out.append((token,
                        "declared enforced by %s, which ALLOWED %r when asked"
                        % (hook, command)))
    # A STALE ROW IS ASKED OF THE PROHIBITIONS, NOT OF THE WHOLE DOCUMENT, and
    # that distinction was found by a red-first probe rather than reasoned: the
    # first version tested `token not in body`, which stayed GREEN when the
    # prohibition was deleted, because `git push` still appeared in ordinary prose
    # elsewhere in the file. A staleness check that any mention satisfies is a
    # check that cannot go stale.
    stated = " || ".join(s for s, _c in prohibitions(body))
    for token, reason in sorted(ADVISORY.items()):
        if token not in stated:
            out.append((token, "declared advisory, but no prohibition in the "
                               "document states this any more - delete the row"))
        if len(reason) < _REASON_MIN:
            out.append((token, "its advisory reason is %d characters; a reason "
                               "shorter than %d is a label"
                        % (len(reason), _REASON_MIN)))
    return out


def main(argv):
    if argv and argv[0] not in ("--json",):
        sys.stderr.write("usage: check-prohibitions.py [--json]\n")
        return E_USAGE
    found = prohibition_drift()
    if "--json" in argv:
        print(json.dumps({"findings": found}, indent=2))
    else:
        for subject, problem in found:
            print("  %s\n      %s" % (subject, problem))
        counted = len(prohibitions())
        if found:
            print("FINDINGS: %d of %d prohibition(s) unaccounted for"
                  % (len(found), counted))
        else:
            print("OK: every prohibition the orchestrator states is enforced by a "
                  "hook that was asked, or declared advisory with a reason "
                  "(%d examined)" % (counted,))
    return E_FAIL if found else E_OK


def _cases(check):
    live = prohibition_drift()
    check("pr0 THE LIVE CLAIM: every absolute prohibition the orchestrator "
          "states is either enforced by a hook that was ASKED, or declared "
          "advisory with a reason - %r" % (live,),
          live == [])
    # ...and the floor beneath it, because a scan that found no prohibitions
    # reports exactly what a fully-accounted document reports.
    found = prohibitions()
    check("pr1 ...and the document really was read: %d prohibition(s) found, "
          "each naming at least one command. A regex that stopped matching "
          "would make pr0 an empty set agreeing with itself"
          % (len(found),),
          len(found) > 0 and all(cmds for _s, cmds in found))
    # The hook probe is the half that cannot be asserted from a table: it drives
    # the guard. If the driver itself broke, every ENFORCED row would report as
    # unenforced, so prove the driver answers BOTH ways on one hook.
    denied, _why = refuses("guard-history-rewrite.py", "git rebase -i main")
    allowed, _why2 = refuses("guard-history-rewrite.py", "git status")
    check("pr2 the hook driver answers both ways - it refuses a real rewrite "
          "and allows an ordinary read. A driver stuck on one answer would make "
          "this whole file either vacuous or a wall of false findings",
          denied is True and allowed is False)
    # Both directions of the ADVISORY table, on fixtures rather than on the tree,
    # so the cases keep working when the real document changes.
    fake = "**NEVER `git frobnicate` a phase branch.**"
    check("pr3 a prohibition in neither table is a finding",
          any("neither ENFORCED nor ADVISORY" in p
              for _s, p in prohibition_drift(fake)))
    check("pr4 ...and a prohibition the document no longer states makes its "
          "ADVISORY row a finding, so the table shrinks by being deleted rather "
          "than by going quiet",
          any("no prohibition in the document states this" in p
              for _s, p in prohibition_drift(fake)))


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
