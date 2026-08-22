#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Bash) — refuse a git command that would ORPHAN a
commit the manifest records.

`task.commit` holds the SHA of each task's commit and `bug.fixedIn` is derived
from it, which is why `reference/orchestrator.md` says "never rebase the phase
branch" and lists force-push among the invariants. Those are instructions to the
ORCHESTRATOR. A human at the same terminal is not the orchestrator, and the
damage is identical: `/audit:doctor` then reports "the manifest names a commit
git does not have" and the audit trail is a list of ghosts.

**THE GUARD BINDS TO THE EFFECT, NOT THE COMMAND NAME**, and that is the whole
design. `git reset --hard` is not one operation:

  git reset --hard                 discards uncommitted work, touches NO history.
                                   Legitimate and common - abandoning a botched
                                   task attempt is exactly this. ALLOWED.
  git reset --hard <ref>           allowed unless a recorded SHA stops being an
                                   ancestor of <ref>. That is a question git can
                                   answer: `git merge-base --is-ancestor`.
  git push --force / --orphan /    rewrite or discard published history
  filter-branch / filter-repo      wholesale. REFUSED while any SHA is recorded.

A guard that refused every `reset --hard` would fire on correct work, and a guard
that fires on correct work gets switched off - after which it protects nothing.
That failure mode is recorded in this project's own history (F-P-24, and the
`guard-secrets-read` read-vs-write class before it), so the ancestry check is not
an optimisation. It is the reason the guard is allowed to exist.

WHAT IT DOES NOT DO. It never inspects the working tree, never runs a write, and
never blocks a command it cannot decide: an unparseable command, an unreadable
manifest, or a git that will not answer all resolve to ALLOW. A manifest with no
recorded SHAs has nothing to orphan, so every command passes - the guard turns
itself on when there is a trail to protect, and says nothing until then.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 - the canonical
PreToolUse protocol. Unexpected input exits 0 (never break legitimate work).

This hook carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_guard_history_rewrite.py`.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402  (hooks resolve scripts/ by basename through here)

# Operations that rewrite or discard history wholesale. There is no ancestry
# question to ask about these: `--orphan` starts a branch with no history at all,
# `filter-branch` rewrites every SHA it touches, and a force-push replaces what
# other clones already have.
_ALWAYS = (
    (re.compile(r"\bgit\b[^|;&]*\bpush\b[^|;&]*(--force\b(?!-with-lease)|(?<![\w-])-f(?![\w-]))"),
     "force-push replaces history other clones already have"),
    (re.compile(r"\bgit\b[^|;&]*\bpush\b[^|;&]*--force-with-lease\b"),
     "force-push (--force-with-lease still replaces the remote's history)"),
    (re.compile(r"\bgit\b[^|;&]*\b(checkout|switch)\b[^|;&]*--orphan\b"),
     "an orphan branch starts with no history, so every recorded commit is "
     "unreachable from it"),
    (re.compile(r"\bgit\b[^|;&]*\bfilter-(branch|repo)\b"),
     "filter-branch/filter-repo rewrites every SHA it touches"),
    (re.compile(r"\bgit\b[^|;&]*\brebase\b(?![^|;&]*--abort)"),
     "rebasing rewrites the SHAs recorded in the manifest "
     "(reference/orchestrator.md states this as an invariant)"),
)

_RESET_HARD = re.compile(r"\bgit\b[^|;&]*\breset\b[^|;&]*--hard\b([^|;&]*)")
_AMEND = re.compile(r"\bgit\b[^|;&]*\bcommit\b[^|;&]*--amend\b")
_FLAGS = re.compile(r"(^|\s)-{1,2}[A-Za-z][\w-]*(=\S*)?")


def recorded_shas(root, cfg):
    """Every `task.commit` the manifest names, with the task that owns it.

    Reads the ASSEMBLED manifest: under the sharded layout the index stubs carry
    no tasks, so a raw read would find no SHAs and the guard would silently
    approve everything on exactly the repos most likely to have a long trail.
    """
    out = []
    try:
        rel = cfg.get("manifestPath") or "docs/audit/audit-plan.json"
        manifest = _config._load_manifest_assembled(os.path.join(root, rel))
        if not isinstance(manifest, dict):
            return out
        for phase in manifest.get("phases") or []:
            if not isinstance(phase, dict):
                continue
            for task in phase.get("tasks") or []:
                if isinstance(task, dict) and task.get("commit"):
                    out.append((str(task.get("id")), str(task.get("commit"))))
    except Exception:
        return []
    return out


def reset_target(command):
    """The ref a `git reset --hard` names, or "" when it names none.

    "" is the case the whole guard turns on: `git reset --hard` with no ref moves
    no branch pointer, so no commit can stop being reachable.
    """
    m = _RESET_HARD.search(command or "")
    if not m:
        return None
    rest = _FLAGS.sub(" ", m.group(1) or "")
    words = [w for w in rest.split() if w and not w.startswith("-")]
    # `--` separates refs from paths; a pathspec reset touches files, not history.
    return words[0] if words else ""


def orphaned_by(root, git_root, target, shas):
    """Which recorded SHAs would stop being ancestors of `target`.

    Returns [] when git cannot answer — an unresolvable ref is a command that is
    about to fail on its own, and guessing here would block work over a typo.
    """
    import subprocess
    lost = []
    for task_id, sha in shas:
        try:
            out = subprocess.run(
                ["git", "-C", git_root or root, "merge-base", "--is-ancestor",
                 sha, target],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            return []
        if out.returncode == 1:          # 1 = not an ancestor; >1 = git could not tell
            lost.append((task_id, sha))
        elif out.returncode > 1:
            return []
    return lost


def decide(data):
    """("deny", reason) or ("allow", "").

    `subprocess` is imported inside the two branches that shell out to git rather
    than at module scope. This hook runs on EVERY Bash tool call, and it returns
    "allow" before touching git for a non-Bash call, an empty command, a repo with
    no recorded task SHAs, and any command that matches none of the rewrite
    patterns - which is nearly all of them. `subprocess` brings about a dozen
    modules with it (threading, selectors, select, signal, locale, warnings, ...),
    and every one of them was being paid for on calls that never spawn anything.
    `tools/bench-hooks.py --gate` is what keeps it out.
    """
    if (data.get("tool_name") or "") != "Bash":
        return ("allow", "")
    command = ((data.get("tool_input") or {}).get("command") or "")
    if not command.strip():
        return ("allow", "")

    root = _config.repo_root(data)
    cfg = _config.load(root)
    shas = recorded_shas(root, cfg)
    if not shas:
        # Nothing to protect. Said here rather than left implicit: the guard is
        # inert on a repo with no trail, and that is an answer, not a miss.
        return ("allow", "")
    git_root = _config.git_root_dir(root, cfg)

    for pattern, why in _ALWAYS:
        if pattern.search(command):
            return ("deny",
                    "%s. The manifest records %d task commit SHA(s); "
                    "`/audit:doctor` reports a SHA that resolves nowhere as a "
                    "FINDING, and the trail cannot be rebuilt from the rewritten "
                    "history. If this is deliberate, run it outside the audit "
                    "checkout, or clear the affected `task.commit` values first "
                    "so the manifest stops claiming a commit that will not exist."
                    % (why, len(shas)))

    target = reset_target(command)
    if target is not None:
        if target == "":
            # The common, legitimate case, and the one this guard exists to keep
            # working: no ref means no branch pointer moves.
            return ("allow", "")
        lost = orphaned_by(root, git_root, target, shas)
        if lost:
            names = ", ".join("%s (%s)" % (t, s[:12]) for t, s in lost[:3])
            return ("deny",
                    "this reset would leave %d recorded commit(s) unreachable: "
                    "%s%s. Those SHAs are what `task.commit` names and what "
                    "`bug.fixedIn` is derived from. `git reset --hard` with NO "
                    "ref is not blocked - that discards uncommitted work and "
                    "touches no history."
                    % (len(lost), names, "" if len(lost) <= 3 else ", ..."))

    if _AMEND.search(command):
        import subprocess
        head = ""
        try:
            out = subprocess.run(["git", "-C", git_root or root, "rev-parse", "HEAD"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=10)
            if out.returncode == 0:
                head = out.stdout.decode("utf-8", "replace").strip()
        except Exception:
            return ("allow", "")
        for task_id, sha in shas:
            if head and sha.startswith(head[:12]) or (head and head.startswith(sha[:12])):
                return ("deny",
                        "amending would replace HEAD, which is the commit "
                        "`task.commit` records for %s (%s). "
                        "reference/orchestrator.md says the `task.commit` write "
                        "rides along with the NEXT commit for exactly this "
                        "reason - do NOT amend." % (task_id, sha[:12]))
    return ("allow", "")


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)
    try:
        verdict, reason = decide(data)
        if verdict == "deny":
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "[guard-history-rewrite] " + reason,
                }
            }))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print("guard-history-rewrite.py has no inline --selftest; its cases live "
              "in plugins/audit/tests/test_guard_history_rewrite.py - run that "
              "file instead.")
        sys.exit(0)
    main()
