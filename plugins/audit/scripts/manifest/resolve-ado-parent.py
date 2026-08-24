#!/usr/bin/env python3
"""
Where each audit item would hang on the board, and whether that place can be true.

`_ado_parent` holds the rules; this is the door the orchestrator knocks on before
it creates anything. A real command rather than a `python3 -c` one-liner for the
reason `check-ado-item.py` gives and which is not style: a one-liner naming a
source path is exactly the shape `guard-secrets-read` refuses (F20/F22), so the
check would be blocked on the machines that most need it.

  resolve-ado-parent.py <manifest> [--all | --phase P3 | --task P3.1] [--json]
  resolve-ado-parent.py <manifest> --hierarchy-from <backlogconfig.json|->

`--all` is the default, because the push plan needs the whole picture and a
command whose default answers about nothing is a command people forget to scope.

`--hierarchy-from` IS THE SECOND HALF OF THE SAME DOOR, and it exists because
prose was doing the job. `/audit:sync parents` asks the project for its backlog
configuration and then had to BUILD `meta.ado.hierarchy` out of the answer, so
the rule for placing the bug rung was written out in three documents - and the
rule moved under them (F143/F157). The rank comes from `bugsBehavior`; the NAME
comes from `meta.ado.types.bug`, which is why the manifest is still the first
argument here. A document telling a reader to file that rank under `Bug` files
it under a name no work item carries on a board that renamed the type, while
the `basis` line goes on claiming the whole ladder came from the project's own
configuration. So this mode prints the block to write, whole: the reader copies
an answer instead of following a recipe, and `levels_from_backlog_config` stays
the one place the ladder is derived.

IT WALKS BUGS TOO, and they are reported apart from the plan. `status` fetches a
linked bug's `System.Parent` like any other item's and had nothing on the
manifest side to compare it with, so a linked bug got no `parent?` verdict and
nothing said why (F101). A bug's row is what the manifest RECORDS about where it
hangs - usually written by a pull, off the board - and never a plan for a write:
a push creates no bug parent link, so the bug rows stay out of the plan block's
counts and out of the hierarchy check, and one line names them instead. The
scopes are unchanged; `--all` is the only one that reaches a bug.

THE HIERARCHY IS ALWAYS COMPUTED OVER THE WHOLE PLAN, even when the scope is one
phase. A loop is a property of the graph and not of the item you happened to ask
about, so narrowing the walk would let `--phase P3` report clean while P3's
parent hangs under P3 through P4. What the scope narrows is the VERDICT: refusals
outside it are counted and printed rather than silently dropped, and they do not
change the exit code, because this run was asked about P3.

Exit codes, and the third one is the load-bearing one:
  0  resolved - INCLUDING "no parent anywhere". Uncategorised work is an answer
     and a create, not an error; `conventions.requireParent` is the board saying
     otherwise and it is graded where the whole plan can be seen.
  1  a hierarchy violation in scope - do NOT create these links.
  2  unreadable input, an unknown flag, or a scope naming nothing. NEVER 1:
     saying "this does not belong" about something we could not read is the
     confident wrong answer this door exists to avoid.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_resolve_ado_parent.py`.
"""
import json
import os
import sys
import time

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

import _ado_parent as _parent  # noqa: E402  (the rules this command is a door onto)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)

USAGE = ("usage: resolve-ado-parent.py <manifest> "
         "[--all | --phase <id> | --task <id>] [--json]\n"
         "       resolve-ado-parent.py <manifest> "
         "--hierarchy-from <backlogconfig.json|->\n")


# --- arguments, and the scope they name -----------------------------------------
def parse_args(argv):
    """(options, error). `error` is a sentence, and then nothing else is read.

    Parsed into a dict rather than a tuple of four so that adding a flag is not
    an edit at every unpacking site, and returned WITH its error rather than
    raising, because a usage error is exit 2 and never an exception the caller
    has to translate.
    """
    opts = {"manifest": None, "scope": "all", "target": None, "json": False,
            "hierarchyFrom": None}
    rest = list(argv)
    if not rest or rest[0].startswith("-"):
        return (opts, "a manifest path is the first argument")
    opts["manifest"] = rest.pop(0)
    # Every flag that shapes the ITEM report, remembered as it is seen. The
    # ladder mode answers about the PROJECT and has one output shape, so each of
    # these would be accepted and then do nothing there - and a flag that is
    # silently ignored leaves the caller believing it applied.
    about_items = []
    while rest:
        flag = rest.pop(0)
        if flag == "--json":
            opts["json"] = True
            about_items.append(flag)
        elif flag == "--all":
            opts["scope"] = "all"
            about_items.append(flag)
        elif flag in ("--phase", "--task"):
            if not rest:
                return (opts, "%s needs an id" % (flag,))
            opts["scope"] = flag[2:]
            opts["target"] = rest.pop(0)
            about_items.append(flag)
        elif flag == "--hierarchy-from":
            if not rest:
                return (opts, "%s needs the backlogconfiguration payload - a "
                              "path, or - to read it from stdin" % (flag,))
            opts["hierarchyFrom"] = rest.pop(0)
        else:
            return (opts, "unknown flag %r" % (flag,))
    if opts["hierarchyFrom"] is not None and about_items:
        return (opts, "--hierarchy-from asks this PROJECT what its ladder is, "
                      "not where an item hangs, and it always prints the block "
                      "to write - so %s answers nothing here"
                      % (", ".join(sorted(set(about_items))),))
    return (opts, None)


def in_scope(row, opts):
    """Is this inventory row what the caller asked about?

    A `--phase` covers the phase AND the tasks under it, because "where does P3
    hang" and "where does P3's work hang" are the same question at a confirm
    gate — a phase whose own parent is fine and whose tasks close a loop is
    exactly the state that must not read as clean.
    """
    if opts["scope"] == "all":
        return True
    target = opts["target"]
    if opts["scope"] == "task":
        return row["kind"] == "task" and row["id"] == target
    # A bug is not a phase and is under none: the id prefix rule below is about
    # `P3` covering `P3.1`, and without the kind guard `--phase BUG-3` would
    # answer about a bug in a sentence that names a phase.
    return row["kind"] != "bug" and (
        row["id"] == target
        or str(row["id"] or "").startswith("%s." % (target,)))


# --- the manifest side: which settings there are to resolve against -------------
def _ado_of(manifest):
    """`meta.ado`, or {} — tolerant on the way down, like `conventions_of`.

    A manifest whose `meta` or `ado` is the wrong type is the validator's
    finding to report, not this command's to crash on. Here the only question is
    what settings there are to resolve against.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    ado = meta.get("ado") if isinstance(meta, dict) else None
    return ado if isinstance(ado, dict) else {}


def levels_of(ado):
    """The cached type ranks, or None when nobody has fetched them.

    `None` reaches `hierarchy_violations` unchanged and every link reports `not
    verified`, which is the honest answer: `meta.ado.hierarchy` is EVIDENCE with
    a `fetchedAt` and a basis, and an absent cache is a missing basis rather
    than a project that ranks nothing.
    """
    block = ado.get("hierarchy")
    levels = block.get("levels") if isinstance(block, dict) else None
    return levels if isinstance(levels, dict) else None


# --- the ladder itself: building the cache the rest of this file reads ----------
def iso_now():
    """Wall clock, isolated so nothing above reaches for one.

    `time.gmtime()` rather than `datetime`, the same spelling
    `repair-commits.py` uses in this directory: it needs no inline import and no
    note about which `utcnow` is deprecated, and the format is the one every
    stamped moment in this manifest already carries. Not borrowed from
    `_proposals.iso_now()` either - that module owns parked proposals, and an
    import edge into it to reach two lines would say this door depends on
    proposals when it does not.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_backlog_payload(path):
    """(payload, error) — the `backlogconfiguration` response, off a file or
    stdin.

    Returned WITH its error for `parse_args`' reason: an unreadable payload is
    exit 2, and never an exception a caller has to translate into one. `-` reads
    stdin so the fetch can be piped straight in, the way `ado-connect.py
    --probe -` takes the envelope it grades.
    """
    try:
        if path == "-":
            return (json.load(sys.stdin), None)
        with open(path, "r", encoding="utf-8") as fh:
            return (json.load(fh), None)
    except Exception as exc:
        return (None, "cannot read/parse the backlogconfiguration payload %s: "
                      "%s" % (path, exc))


def hierarchy_block(payload, ado, now):
    """(block, error) — `meta.ado.hierarchy` exactly as it should be written.

    THE BLOCK IS THE ANSWER, so it is emitted whole and copied verbatim rather
    than described. `levels` and `basis` come from `levels_from_backlog_config`,
    which is the ONE derivation of the ladder; `fetchedAt` is added here because
    a cache with no moment cannot be aged, and the moment a payload was parsed
    is the moment the fetch that produced it can be dated from.

    A `None` FROM THE RULES IS AN ERROR AND NEVER AN EMPTY LADDER. A response
    nobody could parse, cached as `{}`, reads as "this project ranks nothing" -
    a basis-shaped object that switches the type check off while looking like
    evidence. So nothing is printed and the caller writes nothing.

    A new dict rather than the one the rules returned: `basis` is the sentence
    that has to survive into the cache unchanged, and a function that edits its
    caller's value and also returns it is two contracts.
    """
    levels = _parent.levels_from_backlog_config(payload, ado)
    if levels is None:
        return (None, "that payload ranks no backlog level - no taskBacklog, "
                      "requirementBacklog or portfolioBacklogs[] entry in it "
                      "carries both a rank and a workItemTypes list. "
                      "Nothing was written: an empty ladder cached as evidence "
                      "reads as a project that ranks nothing, which is the "
                      "shape that turns the type check off")
    block = dict(levels)
    block["fetchedAt"] = now
    return (block, None)


# --- the report: the whole-graph verdict, narrowed to what was asked ------------
def scope_result(result, scoped, scoped_ids):
    """The whole-graph verdict, narrowed to the rows the caller asked about.

    NARROWED AND NEVER RECOMPUTED. Running the check a second time over the
    scoped rows alone would build a smaller graph and quietly lose every loop
    that leaves the scope — which is precisely the state `--phase` is most often
    used in. Two computations here would also be two verdicts: the printed
    refusals and the exit code came from different walks until this function
    existed, so `--phase P1` could exit 1 while printing a clean plan.
    """
    return {"refusals": [e for e in result["refusals"] if e["id"] in scoped_ids],
            "findings": [e for e in result["findings"] if e["id"] in scoped_ids],
            "warnings": [e for e in result["warnings"] if e["id"] in scoped_ids],
            "unverified": [e for e in result["unverified"]
                           if e["id"] in scoped_ids],
            # A bug's declared parent is NOT a checked link, for the reason
            # `hierarchy_violations` skips it: nothing here would create it. A
            # count that included one would say the hierarchy check looked at a
            # link it refuses to have an opinion about, which is the "nothing
            # was wrong" that means "nothing was looked at".
            "checked": len([r for r in scoped if r["parent"] is not None
                            and r["kind"] != "bug"])}


def bug_line(rows):
    """The one sentence about bugs — printed ALWAYS, including at zero.

    THIS COMMAND ALWAYS ASKS ABOUT BUGS, which is why the line can be
    unconditional here and could not be inside `plan_lines`: a count taken
    there cannot tell a manifest with no bugs from a caller that passed none,
    and those are the two answers this whole feature is about keeping apart.

    It says how many were RESOLVED and how many of them are LINKED, because the
    linked ones are the rows `status` has a board side for. It does not appear
    in the plan block above: a push creates no bug parent link, so a bug
    counted among the plan's uncategorised items would report the ordinary
    state of every bug as a gap.
    """
    bugs = [r for r in rows if r.get("kind") == "bug"]
    linked = [r for r in bugs if r.get("workItemId") is not None]
    return ("  bugs: %d resolved, %d linked - reported so `status` has a "
            "manifest side for a linked bug's parent, and counted apart "
            "because a push neither creates nor changes a bug's parent link"
            % (len(bugs), len(linked)))


def report(rows, scoped, scoped_result, result, ado):
    """Every line this command prints, so `main()` decides only the exit code."""
    lines = list(_parent.plan_lines(scoped, scoped_result))
    block = ado.get("hierarchy")
    basis = block.get("basis") if isinstance(block, dict) else None
    lines.append("  basis: %s" % (basis if basis else
                                  "meta.ado.hierarchy is not cached - run "
                                  "/audit:sync parents to fetch this project's "
                                  "own backlog ranks"))
    # The refusals the SCOPE excluded, counted and named. Dropping them silently
    # would let `--phase P3` read as a clean board while the plan around it is
    # unbuildable; changing the exit code over them would answer a question this
    # run was not asked.
    scoped_ids = set(r["id"] for r in scoped)
    elsewhere = [e for e in result["refusals"] if e["id"] not in scoped_ids]
    lines.append("  outside this scope: %d refusal(s) over %d item(s) not asked "
                 "about%s" % (len(elsewhere), len(rows) - len(scoped),
                              (" (%s)" % ", ".join(
                                  str(e["id"]) for e in elsewhere))
                              if elsewhere else ""))
    # OVER THE WHOLE INVENTORY, never the scope: a `--phase P3` run that
    # printed "0 bugs" would be answering about P3 in a sentence that reads as
    # a fact about the manifest. It sits beside the scope line for that reason.
    lines.append(bug_line(rows))
    return lines


# --- cli ------------------------------------------------------------------------
def main(argv):
    opts, error = parse_args(argv)
    if error:
        sys.stderr.write("ERROR: %s\n%s" % (error, USAGE))
        return 2

    try:
        manifest = _mio.load_manifest(opts["manifest"])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n"
                         % (opts["manifest"], exc))
        return 2

    ado = _ado_of(manifest)

    if opts["hierarchyFrom"] is not None:
        # The ladder mode returns before any of the item walk below: it answers
        # about the project, it creates no link and refuses none, so exit 1 -
        # "do NOT create these" - is not one of its answers.
        payload, error = read_backlog_payload(opts["hierarchyFrom"])
        block = None
        if error is None:
            block, error = hierarchy_block(payload, ado, iso_now())
        if error:
            sys.stderr.write("ERROR: %s\n" % (error,))
            return 2
        print(json.dumps(block, indent=2, sort_keys=True))
        return 0

    # BUGS ARE ASKED ABOUT HERE AND NOWHERE ELSE. `status` fetches a linked
    # bug's `System.Parent` exactly as it does a phase's, and until this list
    # was passed there was no manifest side to compare it with - so a linked bug
    # got no `parent?` verdict at all and nothing said that was why (F101). The
    # list is passed even when it is empty, because `inventory` reads None as
    # "not asked" and this command always asks.
    inv = _parent.inventory(manifest.get("phases"), ado,
                            manifest.get("bugs") or [])
    rows = inv["rows"]
    # The WHOLE graph, always - a loop is a property of the plan and not of the
    # item asked about. See the module docstring.
    result = _parent.hierarchy_violations(rows, levels_of(ado))
    scoped = [r for r in rows if in_scope(r, opts)]
    if opts["scope"] != "all" and not scoped:
        # Exit 2, never 0. "Resolved: nothing" about an id that does not exist
        # is the same confident wrong answer as refusing something unreadable.
        sys.stderr.write("ERROR: no %s named %r in %s\n"
                         % (opts["scope"], opts["target"], opts["manifest"]))
        return 2

    scoped_ids = set(r["id"] for r in scoped)
    scoped_result = scope_result(result, scoped, scoped_ids)
    refused = scoped_result["refusals"]

    if opts["json"]:
        print(json.dumps({"scope": opts["scope"], "target": opts["target"],
                          "rows": scoped, "refusals": refused,
                          "refusalsOutsideScope":
                              [e for e in result["refusals"]
                               if e["id"] not in scoped_ids],
                          "findings": scoped_result["findings"],
                          "warnings": scoped_result["warnings"],
                          "unverified": scoped_result["unverified"],
                          "checked": scoped_result["checked"],
                          "resolveWarnings": inv["warnings"]},
                         indent=2, sort_keys=True))
        return 1 if refused else 0

    for line in report(rows, scoped, scoped_result, result, ado):
        print(line)
    for line in inv["warnings"]:
        print("WARNING: " + line)
    if refused:
        print("\nREFUSED: %d hierarchy violation(s) in scope - do NOT create "
              "these parent links." % (len(refused),))
        return 1
    print("\nOK: every in-scope item has a place, or is deliberately "
          "uncategorised.")
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("resolve-ado-parent.py has no inline --selftest; its cases live "
              "in plugins/audit/tests/test_resolve_ado_parent.py - run that "
              "file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
