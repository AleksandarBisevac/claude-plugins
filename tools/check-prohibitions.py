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
force-push"**, and of that pair only force-push was refused by a hook. `git push`
and `git stash` were both ALLOWED by every guard in the plugin. The most
emphatic rule in the file was half-enforced, and nothing could say so.

`git stash` is enforced now (F281) - it is the one git verb that removes work
without naming what it removed, and a compound command carrying one took a whole
session's uncommitted edits out of an audit checkout. `git push` deliberately is
not, and the ADVISORY row below is where that decision is recorded rather than
left to be re-derived.

WHAT IT CHECKS, in both directions:

  * every prohibition in the document appears in `ENFORCED` or `ADVISORY`;
  * every hook named in `ENFORCED` really refuses the command it claims to -
    DRIVEN, not asserted, because a table naming a hook that stopped refusing
    reads exactly like one that still does;
  * every `ADVISORY` row carries a reason long enough to be one, and its rule
    still appears in the document - a table that only grows stops describing
    the system;
  * every `ADVISORY` row that names a command is DRIVEN as well, against every
    hook `hooks.json` puts on `PreToolUse`/`Bash` in a deciding mode. A row
    saying "nothing stops this" is a claim about the hooks, and the flattering
    direction of this file's own defect is a row still claiming a gap that has
    since been closed.

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

# --- what the document states -------------------------------------------------
# A prohibition is a bolded NEVER naming a command. The narrowing is deliberate:
# `never goes out of date` is prose about a manifest, not a rule about an action,
# and a census that swept those in would be a census nobody reads. The cost of the
# narrowing is stated rather than hidden - a prohibition written without the bold,
# or one writing `Never` rather than `NEVER`, is invisible here. THIS COMMENT USED
# TO NAME AN `unbolded_prohibitions()` THAT REPORTS IT; there is no such function
# and there never was, so the blind spot was silent while the comment said it was
# not. The consequence is live and is declared per row below: the `rebase` and
# `filter-branch` rows carry no document phrase to check, because the sentences
# stating those rules are not ones this scan can see.
_BOLD_NEVER = re.compile(r"\*\*[^*]*\bNEVER\b[^*]*\*\*")
_COMMAND = re.compile(r"`([a-z][a-z0-9 _.-]{2,40})`")

# rule token -> (the hook that refuses it, the commands it must refuse, the phrase
#                a prohibition in the document must still carry, or None)
#
# THE COMMANDS ARE A TUPLE AND THE COMPOUND SPELLING IS IN IT ON PURPOSE. The
# stash row is justified by an incident that happened inside a COMPOUND command,
# and it was probed with a single-line one - so a tokenizer that read only the
# first command in a line would have passed this gate while the incident's own
# shape went unenforced. That is not hypothetical: F284 was exactly that bug for
# the newline spelling, and this probe would not have caught it.
#
# THE THIRD ELEMENT IS THE HALF THAT KEEPS THE DOCUMENT HONEST, and it is optional
# for the reason the `_BOLD_NEVER` comment above records rather than for
# convenience: only a rule this scan can SEE can be asked whether it is still
# stated. Where it is None the row checks enforcement alone - the document could
# drop that sentence and nothing here would say so. That is the harmless direction
# (enforced but undocumented, not documented but unenforced), and it is written
# down instead of being a property of the tuple's length.
ENFORCED = {
    # "NEVER `git push` or force-push." - the token is not a substring of the
    # sentence, so the phrase is the half of the pair that IS spelled there.
    "git push --force": ("guard-history-rewrite.py",
                         ("git push --force origin main",
                          "git status && git push --force origin main",
                          "git status\ngit push --force origin main"),
                         "force-push"),
    # Stated as "**Never rebase**" and "a rebase this document forbids" - neither
    # is an upper-case NEVER, so `_BOLD_NEVER` never sees them.
    "rebase": ("guard-history-rewrite.py",
               ("git rebase -i main", 'sh -c "git rebase -i main"'), None),
    # Named only inside this hook's own docstring and in prose that is not a
    # bolded prohibition.
    "filter-branch": ("guard-history-rewrite.py",
                      ("git filter-branch -f",), None),
    # F281. `git stash` moved here from ADVISORY, and the pairing below is the
    # whole point of the move: the destructive verb is refused and the two READ
    # verbs are not. A hook refusing `git stash list` would be switched off, and
    # then the destructive half would be unguarded too - which is the argument
    # the push row makes for staying advisory. It keeps the document check it had
    # as an advisory row: moving a row between tables must not quietly drop the
    # question the other table was asking.
    "git stash": ("guard-history-rewrite.py",
                  ("git stash push --keep-index",
                   "git stash list && git stash drop",
                   "git stash list\ngit stash drop"),
                  "git stash"),
}

# ...and the READS each ENFORCED rule must NOT refuse, driven on an ORDINARY run
# rather than only under `--selftest`. `SECURITY.md` says this file drives both
# halves of that pair on every run, and it did not: the refusal half was a gate
# and the reads-stay-allowed half was a case, so a hook that started refusing
# `git stash list` would have shipped green through `verify.sh`. A guard that
# fires on a read is a guard people route around, and then the refusal half is
# protecting nothing - which makes this half of the pair a gate too.
MUST_STAY_ALLOWED = {
    "git stash": ("git stash list", "git stash show", "git stash --help"),
    "rebase": ("git rebase --abort", "git rebase --help"),
}

# rule token -> why no hook refuses it. A reason, not a label: it has to say what
# would have to be true for the rule to be enforceable, so a reader can tell a
# decision from an omission.
#
# THE SHAPE IS `{subject: reason}` AND IT HAS TO STAY THAT, which is why the probe
# command lives in its own table below rather than in a tuple beside the reason.
# `gate-parity.exemption_audit_drift` finds every reason-carrying table in this
# tree by shape and refuses one nobody audits; this row is declared there by name,
# and pairing the reason with anything makes the table invisible to that rule -
# measured, by making exactly that change and watching the audit report ADVISORY
# as a subject that no longer exists.
ADVISORY = {
    "git push": (
        "DELIBERATELY UNENFORCED, and this is the row that records the decision. "
        "The force-push half is refused (see ENFORCED above); a plain `git push` "
        "is not, and a hook that refused it would stop the human operator on "
        "every release. CLAUDE.md makes exactly this argument about the release "
        "guard - a guard that fires on correct work is routed around inside a "
        "day, after which it protects nothing, including the half that mattered. "
        "So the prohibition rests on the model reading the sentence, the probe "
        "beside this reason proves no hook refuses it, and re-opening this needs "
        "a way to tell an orchestrator's push from an operator's."),
    "task.complete": (
        "ADVISORY BY CONSTRUCTION rather than by omission. The rule is that "
        "completion rows are hook-derived and must not be appended by hand, and "
        "the hook that derives them cannot also refuse a hand-written one: it "
        "fires on the write that WOULD produce the row, so a person appending "
        "the row directly is doing the thing it is downstream of. Enforcing this "
        "belongs to the journal's own hash chain, which already reports a row "
        "nothing wrote - `/audit:logs verify` is where it surfaces."),
}

# ADVISORY rule token -> a command that must stay ALLOWED, for the rows where one
# exists. This half is F281's other direction: a row saying "nothing stops this"
# is a claim about the HOOKS, and the flattering direction of this file's own
# defect is a row still claiming a gap that has since been closed. A rule with no
# entry here is unmeasurable rather than measured - `task.complete` is a rule about
# a journal ROW, not about a command, so there is nothing to hand a Bash guard.
ADVISORY_PROBE = {
    "git push": "git push origin main",
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


# --- asking the hooks ---------------------------------------------------------
def deciding_bash_hooks(hooks_json=None):
    """Every hook `hooks.json` registers on PreToolUse for Bash that can DECIDE.

    Read rather than listed, because a table of hook names here would be a second
    copy of a fact `hooks.json` already owns - and an ADVISORY row claiming "no
    hook refuses this" is only as good as the set of hooks it asked.

    Filtered to the `ask` registrations, and that filter is load-bearing in two
    directions. A hook launched in `open` mode cannot return a permission
    decision, so asking it could only ever produce a false finding; and
    `journal-writes.py` is registered on this very event in `open` mode and
    WRITES the audit trail when it runs, so driving it would make a read-only
    check mutate the repository it is checking.
    """
    path = hooks_json or os.path.join(HOOKS, "hooks.json")
    with io.open(path, encoding="utf-8") as fh:
        wiring = json.load(fh)
    out = []
    for block in ((wiring.get("hooks") or {}).get("PreToolUse") or []):
        if "Bash" not in (block.get("matcher") or ""):
            continue
        for hook in block.get("hooks") or []:
            parts = (hook.get("command") or "").split()
            if len(parts) >= 2 and parts[-1] == "ask":
                name = parts[-2].split("/")[-1]
                if name not in out:
                    out.append(name)
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


# --- the verdict --------------------------------------------------------------
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
    stated = " || ".join(s for s, _c in prohibitions(body))
    for token, (hook, commands, phrase) in sorted(ENFORCED.items()):
        for command in commands:
            denied, why = refuses(hook, command)
            if denied is None:
                out.append((token, "%s %s" % (hook, why)))
            elif not denied:
                out.append((token,
                            "declared enforced by %s, which ALLOWED %r when "
                            "asked" % (hook, command)))
        for command in MUST_STAY_ALLOWED.get(token) or ():
            denied, why = refuses(hook, command)
            if denied is None:
                out.append((token, "%s %s" % (hook, why)))
            elif denied:
                out.append((token,
                            "%s REFUSED %r, which is a READ - a guard that "
                            "fires on a read is one people route around, after "
                            "which the refusal half protects nothing"
                            % (hook, command)))
        if phrase and phrase not in stated:
            out.append((token, "declared enforced, but no prohibition in the "
                               "document carries %r any more - a rule enforced "
                               "by a hook and stated nowhere is a rule the next "
                               "reader will not know to keep" % (phrase,)))
    # A STALE ROW - in EITHER table; `stated` above is shared - IS ASKED OF THE
    # PROHIBITIONS AND NOT OF THE WHOLE DOCUMENT, and
    # that distinction was found by a red-first probe rather than reasoned: the
    # first version tested `token not in body`, which stayed GREEN when the
    # prohibition was deleted, because `git push` still appeared in ordinary prose
    # elsewhere in the file. A staleness check that any mention satisfies is a
    # check that cannot go stale.
    for token, reason in sorted(ADVISORY.items()):
        allowed = ADVISORY_PROBE.get(token)
        if token not in stated:
            out.append((token, "declared advisory, but no prohibition in the "
                               "document states this any more - delete the row"))
        if len(reason) < _REASON_MIN:
            out.append((token, "its advisory reason is %d characters; a reason "
                               "shorter than %d is a label"
                        % (len(reason), _REASON_MIN)))
        # THE ADVISORY ROWS ARE DRIVEN TOO, and this half is F281's other
        # direction. `git stash` sat here saying "MEASURED UNENFORCED" while it
        # was being enforced would have been the same defect as an ENFORCED row
        # naming a hook that stopped refusing - a table describing the system
        # wrongly, just in the flattering direction. Nothing asked, so nothing
        # could have said so.
        if not allowed:
            continue
        for hook in deciding_bash_hooks():
            denied, why = refuses(hook, allowed)
            if denied is None:
                out.append((token, "%s %s" % (hook, why)))
            elif denied:
                out.append((token,
                            "declared advisory, but %s REFUSED %r when asked - "
                            "the row is now wrong in the other direction; move "
                            "it to ENFORCED" % (hook, allowed)))
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
    # F281. The stash half, pinned as a PAIR. Either line alone is a rule that is
    # useless (refuse nothing) or harmful (refuse the reads too, and get switched
    # off) - and the pair is what makes ENFORCED the honest table for it.
    verb = "git " + "stash"
    denied, _w = refuses("guard-history-rewrite.py", verb + " push --keep-index")
    read_l, _w = refuses("guard-history-rewrite.py", verb + " list")
    read_s, _w = refuses("guard-history-rewrite.py", verb + " show")
    # ...and the NEWLINE spelling, which is the shape F284 allowed while the
    # single-line probe passed. It is asked here as well as in ENFORCED because
    # a probe list is only as good as the spellings somebody thought of.
    compound, _w = refuses("guard-history-rewrite.py",
                           verb + " list\n" + verb + " drop")
    check("pr5b the compound spellings the incident actually took are refused, "
          "newline as well as `&&`. The row's justification is a COMPOUND "
          "command and its probe was a single-line one, which is how a "
          "tokenizer that read only the first command passed this gate",
          compound is True, repr(compound))
    check("pr5 the stash prohibition is enforced in the direction that matters "
          "and NOT in the other: the destructive verb is refused, `list` and "
          "`show` are reads and stay allowed. A hook refusing all three would be "
          "routed around, which is the reason the push half is a decision",
          denied is True and read_l is False and read_s is False,
          repr((denied, read_l, read_s)))
    # ...and the hooks that were asked are the ones the wiring names, not a list
    # written here. An empty set would make pr5's siblings vacuous.
    asked = deciding_bash_hooks()
    check("pr6 the ADVISORY probes are driven against the hooks `hooks.json` "
          "actually registers on PreToolUse/Bash in a deciding mode - %r. An "
          "empty set would make every advisory row agree with itself, and an "
          "`open`-mode hook in it would make this file write the audit trail "
          "it is checking" % (asked,),
          bool(asked) and "guard-history-rewrite.py" in asked
          and "journal-writes.py" not in asked)
    # Both directions of the advisory probe, on a fixture: a row whose command a
    # hook DOES refuse is a finding, and the row that is genuinely unenforced is
    # not. The first is the direction nothing asked before F281.
    saved = ADVISORY_PROBE.get("git push")
    try:
        ADVISORY_PROBE["git push"] = "git rebase -i main"
        check("pr7 an ADVISORY row whose command a hook REFUSES is a finding - "
              "the table wrong in the flattering direction, which is the one "
              "this file could not previously see",
              any("wrong in the other direction" in p
                  for _s, p in prohibition_drift()))
    finally:
        ADVISORY_PROBE["git push"] = saved
    check("pr8 ...and the real row is not a finding, which is the second-"
          "direction case: a probe that reported every command refused would "
          "turn pr7 into a check that cannot fail",
          not any("wrong in the other direction" in p
                  for _s, p in prohibition_drift()))
    # An ENFORCED row is asked whether the DOCUMENT still states its rule, not
    # only whether the hook still refuses it. Found by a red-first probe: moving
    # `git stash` out of ADVISORY silently dropped the staleness question that
    # table was asking, so deleting the sentence went unnoticed while the hook
    # went on enforcing it.
    only_push = "**NEVER `git push` or force-push.**"
    check("pr9 an ENFORCED row whose rule the document no longer states is a "
          "finding - a rule a hook enforces and no document states is one the "
          "next reader will not know to keep",
          any("document carries 'git stash'" in p
              for _s, p in prohibition_drift(only_push)))
    check("pr10 ...and a row that declares NO document phrase is not dragged "
          "into that check. `rebase` is stated as `Never rebase`, which the "
          "upper-case scan cannot see, so its row asks about enforcement only "
          "- the blind spot is declared per row rather than being a property "
          "of the tuple's shape",
          ENFORCED["rebase"][2] is None
          and not any(subject == "rebase" and "document carries" in problem
                      for subject, problem in prohibition_drift(only_push)))


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
