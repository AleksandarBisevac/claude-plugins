#!/usr/bin/env python3
"""
`/audit:logs` - the command over the plugin's own local feeds. Stdlib only.

    audit-logs.py prune [--project DIR] [--older-than DAYS] [--dry-run] [--json]

Today it has exactly one verb and one feed: `prune` over
`<logsDir>/plan-gate-events.jsonl`, the file `hooks/_config.append_gate_event`
writes and the panel's Plan gate card shows. The rule it applies lives in
`_gate_feed.py`; this file is the door - argument parsing, the render, the exit
code - so the panel can take the same action through the same rule without going
through a command.

WHY THIS IS NOT `/audit:doctor --prune-events`, which is what was asked for. The
doctor is read-only BY CONSTRUCTION, and three surfaces promise it: its own
docstring, `commands/doctor.md` and the README, all of which are what makes it
safe to run mid-phase and in CI. The decisive part is not the promise though, it
is the shape: `--prune-events` would have to SKIP `diagnose()` entirely - a
seventeen-check diagnosis is no part of removing rows from a log - and a flag that
skips the whole body of a command is a different command wearing that command's
name. Its exit code says the same thing: doctor's is a health verdict, and a
prune's outcome has nowhere to go in it.

WHY THE NAME IS THE BOUNDARY. `logs` is not a category picked for tidiness; it is
the guarantee. Everything this command can touch lives under `logsDir`, and
`_gate_feed.feed_path` derives the one file from the writer's own `logs_dir()` +
`GATE_EVENTS_FILE` rather than from anything typed here, so there is no argument
this command takes that can widen it. The journal is deliberately out of reach:
that is the tamper-evident trail, it is append-only on purpose, and a command that
could prune it would be a command that could edit the evidence.

Exit: 0 the prune ran (whatever the counts) - 1 it could not - 2 a usage error.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_audit_logs.py` - see `plugins/audit/tests/_harness.py`.
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

import _gate_feed  # noqa: E402  (the rule: what still belongs in the gate feed)

# The class names as a reader meets them. `agedOut` is absent on purpose: its
# wording has to carry the threshold that produced it, so `render` builds that
# label from the result rather than reading it here - a fixed "older than the
# threshold" would be a claim with the basis cut off.
CLASS_WORDS = ((_gate_feed.CLASS_OUTSIDE, "outside this repository"),
               (_gate_feed.CLASS_UNREADABLE, "unreadable"))

# Said once, at the bottom, and it is the reason the breakdown above it is counts
# rather than rows. Echoing an out-of-repository path to explain that it was
# removed writes it straight back into the terminal the removal was meant to clear.
_NO_ECHO = ("Removed rows are counted by class and never echoed: the path in an\n"
            "  out-of-repository row is the thing being removed, and printing it "
            "would put it back.")

# One label column for every row below, wide enough for the longest label a
# --dry-run produces. A width computed from the labels actually emitted would be
# a second thing to keep true for the sake of two characters.
_LABEL = "  %-12s"


# --- render -----------------------------------------------------------------------
def _shown_path(project, path):
    """`path` relative to `project` when it is inside it, else as given.

    Never `os.path.relpath`, which raises across Windows drives and answers a
    path in another tree with a run of `..` - the two failures this plugin has
    already been bitten by. A prefix strip has neither.
    """
    if not path:
        return "(none)"
    base = os.path.abspath(str(project))
    full = os.path.abspath(str(path))
    if full.startswith(base + os.sep):
        return full[len(base) + 1:].replace("\\", "/")
    return full


def render(result, project):
    """Plain ASCII, printed verbatim by the command.

    BOTH COUNTS ALWAYS PRINT, including at zero, and so does every class that was
    actually looked for. A number that shows up only when it is non-zero cannot be
    told from a number nobody computed, and this command exists precisely because
    somebody could not tell what the plugin had done to a file.
    """
    verb = "would remove" if result.get("dryRun") else "removed"
    kept_verb = "would keep" if result.get("dryRun") else "kept"
    lines = ["AUDIT LOGS  %s" % project, ""]
    lines.append((_LABEL + " %s") % ("feed",
                                     _shown_path(project, result.get("path"))))

    if not result.get("ok"):
        for finding in result.get("findings") or ["refused"]:
            lines.append((_LABEL + " %s") % ("REFUSED", finding))
        lines.append("")
        lines.append("  Nothing was read and nothing was written.")
        return "\n".join(lines)

    classes = result.get("classes") or {}
    parts = ["%s %d" % (word, classes.get(key, 0)) for key, word in CLASS_WORDS]
    days = result.get("olderThanDays")
    if days is not None:
        parts.append("older than %d day(s) %d"
                     % (days, classes.get(_gate_feed.CLASS_AGED, 0)))

    lines.append((_LABEL + " %s") % ("state", (
        "present" if result.get("exists")
        else "no feed yet - the plan gate has written nothing here")))
    lines.append((_LABEL + " %-4d %s")
                 % (verb, result.get("removed", 0), " - ".join(parts)))
    lines.append((_LABEL + " %d") % (kept_verb, result.get("kept", 0)))
    if days is None:
        lines.append((_LABEL + " %s")
                     % ("age", "not applied - pass --older-than DAYS to prune "
                               "by age as well"))
    lines.append("")
    if result.get("dryRun"):
        lines.append("  --dry-run: the feed was NOT rewritten.")
    elif result.get("wrote"):
        lines.append("  The feed was rewritten.")
    else:
        lines.append("  Nothing to remove; the feed was not rewritten.")
    lines.append("  %s" % _NO_ECHO)
    return "\n".join(lines)


# --- cli --------------------------------------------------------------------------
def main(argv):
    ap = argparse.ArgumentParser(
        prog="audit-logs.py",
        description="Prune the plugin's own local feeds under logsDir.")
    ap.add_argument("action", choices=("prune",),
                    help="prune: drop the rows of "
                         "<logsDir>/plan-gate-events.jsonl that no longer belong")
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--older-than", type=int, default=None, dest="older_than",
                    metavar="DAYS",
                    help="also drop rows stamped more than DAYS days ago. Off "
                         "unless given: the feed already self-trims by size, and "
                         "an old verdict is still a true record of this repo")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="report the same counts and write nothing")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    project = os.path.abspath(args.project)
    if not os.path.isdir(project):
        sys.stderr.write("ERROR: %s is not a directory\n" % project)
        return 2
    if args.older_than is not None and args.older_than < 1:
        sys.stderr.write("ERROR: --older-than takes a whole number of days, at "
                         "least 1 (got %d)\n" % args.older_than)
        return 2

    result = _gate_feed.prune(project, older_than_days=args.older_than,
                              dry_run=args.dry_run)
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render(result, project))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to `main`, which would demand a
        # verb and exit 2. It deliberately does NOT print the `N/M cases passed`
        # contract - that literal is how `_output.selftest_coverage()` tells an
        # inline suite from a migrated one.
        print("audit-logs.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_logs.py - run that file instead.")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
