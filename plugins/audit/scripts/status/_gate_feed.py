#!/usr/bin/env python3
"""
The plan-gate events feed as something that can be CLEANED, not only appended to.

`hooks/_config.append_gate_event` writes `<logsDir>/plan-gate-events.jsonl` and the
panel's Plan gate card reads the tail of it. Nothing in between could ever remove a
row, so a user who wanted rows naming a scratch directory outside their repository
gone had to hand-write Python against a file this plugin both produces and displays.
That is the gap this module closes, and `audit-logs.py` and the panel are the two
doors onto it.

WHAT "NO LONGER BELONGS" MEANS HERE, and each class is decided by evidence rather
than by preference:

  * outsideRepo  the row's `file` resolves outside the consuming repository. The
                 plugin manages and references only that repository, so such a row
                 is not this feed's to keep - and it can no longer be produced
                 either (4e81429 made the gates allow out-of-scope paths before
                 they are recorded), so what is left is history to clear.
  * unreadable   the line is not a JSON object. The reader in `_panel_runstate`
                 already drops these silently, so they occupy the file while
                 showing up nowhere.
  * agedOut      OPT-IN ONLY, and off unless a caller names a threshold. There is
                 no default number here and that is the decision, not an omission:
                 the feed already self-trims by SIZE in `append_gate_event`, so age
                 has no growth problem left to solve, and "old" is not the same
                 claim as "does not belong" - a deny from last quarter is still a
                 true record of this repository. A default would be a number with
                 no basis, which is the one thing this repo's output rules refuse.

A row is counted in the FIRST class it falls into, so the class counts sum to the
removed total and a reader can add them up. `classify()` returns every class,
including the ones at zero: a count that appears only when it is non-zero cannot be
told from a count nobody computed.

CONTAINMENT IS ASKED ONCE, of `hooks/_config.within_root` - the same function
require-plan, remind-tdd and guard-secrets-read ask, so "inside this repository"
has one answer across the plugin. Note what that does NOT cover: the file-safety
question below is an EQUALITY, not a containment test, because the two questions
have opposite failure directions. `within_root` answers *inside* when it cannot
resolve a path, which is right for a gate (a wrong guess leaves a gate where it
already was) and wrong for a writer (a wrong guess writes). So the writer's
boundary is spelled as "this exact file in this exact directory" and fails closed.

Layer 2: it reaches `_loader` and `_usage_core`, both layer 1, and nothing else.
`parse_ts` comes from `_usage_core` for the reason `_ado_drift` states about the
same call - the alternative was this tree's next ISO parser.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__gate_feed.py` - see `plugins/audit/tests/_harness.py`.
"""
import json
import os
import sys
import time
from pathlib import Path

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

import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _usage_core  # noqa: E402  (parse_ts: this tree's ONE ISO-8601 reader)

# The removal classes, and the tuple is what makes "every class, including the ones
# at zero" a property of the code rather than a habit at each call site.
CLASS_OUTSIDE = "outsideRepo"
CLASS_UNREADABLE = "unreadable"
CLASS_AGED = "agedOut"
CLASSES = (CLASS_OUTSIDE, CLASS_UNREADABLE, CLASS_AGED)

_SECONDS_PER_DAY = 86400.0


def hooks_config():
    """`hooks/_config` - `within_root`, `logs_dir`, `GATE_EVENTS_FILE`,
    `atomic_write_text`.

    Through `_loader`, which caches by realpath, so this is the SAME module
    object `_panel_paths.hooks_config()` hands the panel: one memo, one answer to
    "what does this project's config say", and no module state of its own here.
    """
    return _loader.load_hooks_config(modname="audit__config")


# --- where this module may write ------------------------------------------------
def feed_path(project, config=None):
    """`(path, refusal)` - the ONE file this module may rewrite, or why it may not.

    The blast radius is not checked after the fact, it is CONSTRUCTED: the path is
    `hooks/_config.logs_dir()` joined with `hooks/_config.GATE_EVENTS_FILE`, the
    same two facts the writer uses, so this module cannot name a second file even
    by accident. Where `logsDir` points is therefore not this function's business -
    wherever the gate appends is where the prune reads, and the two staying equal
    is the whole property.

    The one refusal is a feed that is a SYMLINK out of its own directory. That
    case has to be caught rather than followed: `append_gate_event` opens the path
    in append mode and so writes THROUGH the link, while `atomic_write_text` ends
    in `os.replace`, which would replace the link itself with a regular file - the
    prune would silently redirect the feed to somewhere the gate no longer writes.
    Refusing is fail-CLOSED, which is why this is an equality between resolved
    directories and not `within_root`: that one answers *inside* when it cannot
    resolve, and a writer must not proceed on a tie.

    The refusal names `logsDir` and never the resolved destination. A path outside
    the repository is the thing being removed, and printing it in the reason would
    put it straight back into the transcript.
    """
    mod = hooks_config()
    cfg = config if isinstance(config, dict) else mod.load(Path(project))
    logs = mod.logs_dir(Path(project), cfg)
    target = os.path.join(str(logs), mod.GATE_EVENTS_FILE)
    try:
        real_logs = os.path.realpath(str(logs))
        real_target = os.path.realpath(target)
    except (OSError, ValueError) as exc:
        return (None, "could not resolve %s inside %s: %s"
                % (mod.GATE_EVENTS_FILE, logs, exc))
    if os.path.dirname(real_target) != real_logs:
        return (None,
                "%s in %s resolves outside that directory (a symlink). Refusing: "
                "the gate appends THROUGH the link, and rewriting the file would "
                "replace the link and send the feed somewhere the gate does not "
                "write. Remove the link, or point logsDir at the directory you "
                "actually want." % (mod.GATE_EVENTS_FILE, logs))
    return (target, None)


# --- what still belongs ---------------------------------------------------------
def classify(project, lines, older_than_days=None, now=None):
    """Split raw feed lines into what stays and what goes.

    Returns `{"keep": [line...], "kept": n, "removed": n, "classes": {name: n}}`
    with every name in `CLASSES` present. `keep` holds the lines verbatim (minus
    their newline), so a row this module does not understand survives a prune
    byte-for-byte rather than being re-serialised into whatever shape today's
    writer happens to use.

    A `file` that is not a path is the normal case, not an edge: `guard-secrets-read`
    puts a glob or even a whole shell command in that field. Those are relative
    spellings, so they resolve inside the project and are KEPT - the question asked
    is "does this name somewhere outside the repository", and a command line does
    not.

    An unparseable `ts` is never aged out. Age is a claim about when a row was
    written, and without a readable stamp there is no basis for it; keeping the row
    is the side of the tie that loses nothing.
    """
    mod = hooks_config()
    counts = dict((name, 0) for name in CLASSES)
    cutoff = None
    if older_than_days is not None:
        base = time.time() if now is None else float(now)
        cutoff = base - (float(older_than_days) * _SECONDS_PER_DAY)

    keep = []
    for raw in lines:
        line = raw.rstrip("\n")
        text = line.strip()
        if not text:
            counts[CLASS_UNREADABLE] += 1
            continue
        try:
            row = json.loads(text)
        except ValueError:
            row = None
        if not isinstance(row, dict):
            counts[CLASS_UNREADABLE] += 1
            continue
        named = row.get("file")
        if isinstance(named, str) and named.strip() \
                and not mod.within_root(project, named.strip()):
            counts[CLASS_OUTSIDE] += 1
            continue
        if cutoff is not None:
            when = _usage_core.parse_ts(row.get("ts"))
            if when is not None and when < cutoff:
                counts[CLASS_AGED] += 1
                continue
        keep.append(line)

    removed = sum(counts[name] for name in CLASSES)
    return {"keep": keep, "kept": len(keep), "removed": removed,
            "classes": counts}


# --- the action -----------------------------------------------------------------
def prune(project, config=None, older_than_days=None, dry_run=False, now=None):
    """Read the feed, drop what no longer belongs, rewrite it. The whole action.

    Returns the shape both doors render, and every field is present on every
    outcome - a refusal carries `kept`/`removed` at zero exactly as a clean run
    carries them, because a caller must never have to tell "nothing was removed"
    apart from "the counts were not computed" by which keys exist:

        {"ok", "findings", "path", "exists", "kept", "removed", "classes",
         "olderThanDays", "dryRun", "wrote"}

    `exists` is the one that separates a feed nobody has written yet from a feed
    that is empty. Both report zero and zero; only one of them means the gate has
    never had anything to say here.

    `wrote` is False when nothing was removed, and that is deliberate rather than
    an optimisation: a prune that changes nothing leaves the mtime alone, so it
    cannot be mistaken for a gate event by anything watching the file, and it
    never races the hooks for a rewrite that would produce identical bytes.

    THE RACE THAT REMAINS, stated rather than papered over: a hook appending
    between the read and the replace loses its row. That is the same window
    `append_gate_event`'s own size-trim has always had, on the same file, for the
    same reason - this feed is telemetry and not the tamper-evident journal, and
    buying a lock for it would mean the gate taking one on every tool call.
    """
    out = {"ok": True, "findings": [], "path": None, "exists": False,
           "kept": 0, "removed": 0,
           "classes": dict((name, 0) for name in CLASSES),
           "olderThanDays": older_than_days, "dryRun": bool(dry_run),
           "wrote": False}

    path, refusal = feed_path(project, config)
    if refusal:
        out["ok"] = False
        out["findings"].append(refusal)
        return out
    out["path"] = path

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return out                      # no feed yet: `exists` stays False
    except OSError as exc:
        out["ok"] = False
        out["findings"].append("could not read %s: %s" % (path, exc))
        return out
    out["exists"] = True

    verdict = classify(project, lines, older_than_days=older_than_days, now=now)
    out["kept"] = verdict["kept"]
    out["removed"] = verdict["removed"]
    out["classes"] = verdict["classes"]
    if out["dryRun"] or not verdict["removed"]:
        return out

    # "".join over a generator rather than "\n".join: an empty keep list must
    # produce an EMPTY file, and "\n".join([]) + "\n" is a blank line the next
    # prune would count as unreadable.
    text = "".join(line + "\n" for line in verdict["keep"])
    try:
        hooks_config().atomic_write_text(path, text)
    except OSError as exc:
        out["ok"] = False
        out["findings"].append("could not rewrite %s: %s" % (path, exc))
        return out
    out["wrote"] = True
    return out


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answered rather than falling through to the library notice below: CI
        # runs `--selftest` over every file here. It deliberately does NOT print
        # the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_gate_feed.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__gate_feed.py - run that file instead.")
        raise SystemExit(0)
    print("This is a library module; run with --selftest to exercise it.")
