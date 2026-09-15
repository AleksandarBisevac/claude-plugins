#!/usr/bin/env python3
"""What is actually happening right now, read rather than remembered.

WHY THIS EXISTS. An orchestrator running several agents against one repository holds a
model of the world that drifts from the world: agents finish, branches move, the tree gets
dirty, a task is created and never spawned. Three times in one run this project's
orchestrator wrote a verb in the first person - "I started it", "I am committing it" -
before executing the action, and the sentence became the artifact instead of the action.
Each time the rule against it was already written down and already known, which is why a
rule is not the repair.

So this is not a reminder. It is the read the report is written FROM: run it as the last
thing in a turn, and say only what it printed. If it shows an idle slot, fill the slot
before writing a word - a report composed while nothing is building is the failure this
exists to catch.

It answers four questions and nothing else:
  - what is running, and how far along (the worktree, never the transcript, which does
    not grow while an agent works);
  - what is finished and waiting to be taken;
  - what is uncommitted here;
  - what is ready to start.

IT NEVER SAYS WHETHER AN AGENT IS ALIVE. This process cannot see the agent list. The
worktree is the evidence it has, and a worktree that is clean and whose HEAD has not moved
means one of two things - nothing has been written yet, or nothing was ever spawned. It
prints both, because telling them apart needs the agent list and saying only one of them
would be the guess this tool exists to refuse.
"""
import io
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(args, cwd=None):
    try:
        p = subprocess.run(["git"] + args, cwd=cwd or REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=20)
        return p.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def worktrees():
    """(path, branch, head) for every linked worktree on a working branch."""
    out, rows, cur = _git(["worktree", "list", "--porcelain"]), [], {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if cur:
                rows.append(cur)
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):][:7]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "")
    if cur:
        rows.append(cur)
    return [r for r in rows
            if os.path.abspath(r.get("path", "")) != os.path.abspath(REPO)
            and (r.get("branch") or "").startswith(("audit/", "p3", "p4"))]


def _running(phase):
    """Whether this phase is executing: its own status, OR a task under it that is.

    THE SECOND ARM IS NOT A COURTESY. The plan gate resolves the same question the same
    way and says why in its own words -- a manifest whose phase status was never written
    is still a repo executing its plan, and refusing to notice would report an idle plan
    while work is running. The status is the weaker signal here because nothing on the
    command line writes it: there is a verb that promotes a task and none that promotes a
    phase, so the field is maintained only by the control surface's heal on save. Keying
    on it alone printed `nothing is ready` over a plan of forty-odd unblocked tasks.

    Reading only the task arm would be the opposite error: a phase whose tasks are all
    finished still reads `in_progress` until it is signed off, and its remaining pending
    tasks -- there are none by then, but a plan mid-edit can have them -- belong to a
    phase somebody entered deliberately."""
    if phase.get("status") == "in_progress":
        return True
    return any(t.get("status") == "in_progress" for t in (phase.get("tasks") or []))


def ready_tasks(manifest):
    """Task ids a RUNNING phase holds that nothing unfinished is waiting on.

    None, not [], when the manifest cannot be read: "nothing is ready" and "nothing
    could be read" are two different reports, and collapsing them is how an orchestrator
    reads an unreadable plan as a finished one."""
    try:
        plan = json.load(io.open(os.path.join(REPO, manifest), encoding="utf-8"))
    except Exception:
        return None
    out = []
    for entry in plan.get("phases", []):
        node = entry
        if entry.get("shard"):
            try:
                node = json.load(io.open(
                    os.path.join(REPO, "docs/audit", entry["shard"]), encoding="utf-8"))
            except Exception:
                continue
        if not _running(node):
            continue
        done = set(t["id"] for t in node.get("tasks", []) if t.get("status") == "done")
        for task in node.get("tasks", []):
            if task.get("status") != "pending":
                continue
            if not [d for d in (task.get("dependsOn") or []) if d not in done]:
                out.append(task["id"])
    return out


def main():
    head = _git(["rev-parse", "--short", "HEAD"])
    print("HEAD %s" % head)

    rows = worktrees()
    if rows:
        print("\nWORKTREES  (the live signal is the tree; a transcript does not grow)")
    for row in rows:
        dirty = [x for x in _git(["status", "--short"], cwd=row["path"]).splitlines()
                 if x.strip()]
        if dirty:
            state = "WRITING    %d file(s) changed" % len(dirty)
        elif row.get("head", "") != head:
            state = "COMMITTED  in its own tree - diff against ITS head, not a branch"
        else:
            state = "NOTHING YET - it has not written, OR it was never spawned"
        print("  %-32s %-12s %s" % (os.path.basename(row["path"]),
                                    row.get("branch", "?"), state))

    dirty = [l for l in _git(["status", "--short"]).splitlines() if l.strip()]
    print("\nUNCOMMITTED HERE: %d path(s)" % len(dirty))
    for line in dirty[:12]:
        print("  " + line)
    if len(dirty) > 12:
        print("  ... and %d more" % (len(dirty) - 12))

    # WHAT THE NEXT COMMIT WOULD TAKE, which is not what you last named. Staging
    # by path is this checkout's rule because a second session shares the tree,
    # and that rule silently assumes the index was empty to begin with. A
    # three-way patch application stages everything it merges and says nothing,
    # so the next commit-by-path took a body of unrelated work under a
    # bookkeeping message. `git commit` takes the INDEX, never the paths just
    # added, and this line is the only place that difference is visible before
    # the commit rather than after it.
    staged = [l for l in _git(["diff", "--cached", "--name-only"]).splitlines()
              if l.strip()]
    print("\nSTAGED HERE: %s" % (
        "nothing - the next commit would take only what you add"
        if not staged else
        "%d path(s) ALREADY IN THE INDEX - `git commit` takes these too" % len(staged)))
    for line in staged[:12]:
        print("  " + line)
    if len(staged) > 12:
        print("  ... and %d more" % (len(staged) - 12))

    ready = ready_tasks("docs/audit/audit-plan.json")
    print("\nREADY NOW: %s" % ("the manifest could not be read" if ready is None
                               else (", ".join(ready) if ready else "nothing")))
    return 0


# --- selftest -------------------------------------------------------------------
def _cases(check):
    """The readiness rule, driven on a fixture manifest.

    `check` is the house runner's, and this file hands its cases over rather than keeping
    a tally: a hand-rolled one prints the same last line on a pass and on a failure, which
    is exactly what `_suite.runner_problem()` reports and what it caught here."""
    import shutil
    import tempfile

    box = tempfile.mkdtemp(prefix="orchstate-")
    json.dump({"phases": [
        {"id": "P1", "title": "t", "status": "in_progress", "tasks": [
            {"id": "P1.1", "status": "pending", "dependsOn": []},
            {"id": "P1.2", "status": "pending", "dependsOn": ["P1.1"]},
            {"id": "P1.3", "status": "done", "dependsOn": []},
            {"id": "P1.4", "status": "pending", "dependsOn": ["P1.3"]}]},
        {"id": "P0", "title": "t", "status": "done", "tasks": [
            {"id": "P0.1", "status": "pending", "dependsOn": []}]},
        {"id": "P2", "title": "t", "status": "pending", "tasks": [
            {"id": "P2.1", "status": "in_progress", "dependsOn": []},
            {"id": "P2.2", "status": "pending", "dependsOn": []}]},
        {"id": "P3", "title": "t", "status": "pending", "tasks": [
            {"id": "P3.1", "status": "pending", "dependsOn": []}]}]},
        io.open(os.path.join(box, "audit-plan.json"), "w"))

    global REPO
    keep = REPO
    try:
        REPO = box
        got = ready_tasks("audit-plan.json")
        check("s1 a pending task nothing unfinished waits on is ready",
              "P1.1" in (got or []), got)
        check("s2 ...one waiting on an UNFINISHED task is not",
              "P1.2" not in (got or []), got)
        check("s3 ...one waiting on a FINISHED task is",
              "P1.4" in (got or []), got)
        check("s4 a task in a phase that is not running is never ready",
              "P0.1" not in (got or []), got)
        check("s6 a phase reading 'pending' that HOLDS a running task is running, so its "
              "other pending tasks are ready -- the plan gate's own rule, because no "
              "command-line verb writes a phase's status and a reader that keys on it "
              "alone sees an executing plan as an idle one",
              "P2.2" in (got or []), got)
        check("s7 ...and a pending phase holding NO running task is still not running, "
              "which is the allow case that reddens if s6 is widened to any pending phase",
              "P3.1" not in (got or []), got)
        REPO = os.path.join(box, "does-not-exist")
        check("s5 an unreadable manifest answers None rather than an empty list, so "
              "'nothing is ready' cannot be read off 'nothing could be read'",
              ready_tasks("audit-plan.json") is None)
    finally:
        REPO = keep
        shutil.rmtree(box, ignore_errors=True)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
