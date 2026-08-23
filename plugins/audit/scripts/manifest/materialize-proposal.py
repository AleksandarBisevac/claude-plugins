#!/usr/bin/env python3
"""
The command door onto the proposal lifecycle.

    materialize-proposal.py <manifest> list [all] [--json]
    materialize-proposal.py <manifest> plan <PROP-id>|--all [--json]
    materialize-proposal.py <manifest> materialize <PROP-id>|--all
                            [--with-deps|--drop-edges] [--json]
    materialize-proposal.py <manifest> drop <PROP-id> --reason <text> [--json]
    materialize-proposal.py <manifest> revive <PROP-id> [--json]

`list` IS HERE FOR THE SAME REASON THE OTHERS ARE (F91). It was the one
subcommand `commands/propose.md` both specified AND rendered - a table described
in prose, printed from prose, checked by nothing - and what a user got was an
accurate summary with no table in it. The rows come from `_proposals.list_view`,
which is what the panel's Proposals tab reads too; what is spelled below is only
the shape of the columns.

THE RULE IS `_proposals.py`, NOT THIS FILE. `commands/propose.md` specified the
lifecycle and executed it by reading itself, which was fine while it was the only
caller; the panel can materialize and drop now, and two readings of one rule are
two answers the first time either is edited. What is left here is a door: argument
parsing, printing, and the exit code. The same split `check-ado-item.py` has over
`_ado_conventions.py`, and made for the same reason the layer lint gives - the
panel's write path sits BELOW the entry points, so it must import the rule
downward rather than reach up to a command.

PLAN, THEN EXECUTE. `plan` writes nothing and reports exactly what would happen,
including the dependency closure, and that output is what `/audit:propose`'s
confirm and the panel's dialog both render. So a human sees what a materialization
pulls in BEFORE anything is written, and the dependency decision arrives as a FLAG
rather than as a question asked inside a rule an HTTP endpoint has to call.

Exit codes: 0 = done (or a clean plan) - 1 = refused, with the reason - 2 = usage
error or unreadable input.

This file carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_materialize_proposal.py`.
"""
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

import _fmt  # noqa: E402  (plural(): `1 task` / `2 tasks`, one implementation)
import _manifest_io as _mio  # noqa: E402  (to resolve --all before the rule runs)
import _proposals  # noqa: E402  (the rule this command is a front end for)

USAGE = (
    "usage:\n"
    "  materialize-proposal.py <manifest> list [all] [--json]\n"
    "  materialize-proposal.py <manifest> plan <PROP-id>|--all [--json]\n"
    "  materialize-proposal.py <manifest> materialize <PROP-id>|--all "
    "[--with-deps|--drop-edges] [--json]\n"
    "  materialize-proposal.py <manifest> drop <PROP-id> --reason <text> [--json]\n"
    "  materialize-proposal.py <manifest> revive <PROP-id> [--json]\n")


def _opt(argv, name):
    if name in argv:
        i = argv.index(name)
        if len(argv) > i + 1:
            return argv[i + 1]
    return None


def _all_parked(manifest):
    """Every still-parked id, in dependency order. `--all`'s meaning."""
    ordered = []
    for prop in (manifest.get("proposals") or []):
        if not isinstance(prop, dict) or prop.get("status") != "proposed":
            continue
        if not prop.get("id"):
            continue
        for step in _proposals.closure(manifest, prop["id"]):
            if step not in ordered:
                ordered.append(step)
    return ordered


# The columns `commands/propose.md` specifies, in its order. A tuple rather than a
# format string so the header and the rows are measured against one list and
# cannot drift apart by a column.
LIST_COLUMNS = ("id", "status", "reserved phase (task count)", "name",
                "openQuestions")


def _reserved_cell(row):
    """The payload column: the phase this proposal reserves, and how big it is.

    `-` when there is no payload. A legacy free-form entry reserves nothing, and
    printing a phase id for it would invent one - `hasPayload` is the basis, not
    whether `phaseId` happens to be truthy.
    """
    if not row["hasPayload"]:
        return "-"
    return "%s (%s)" % (row["phaseId"], _fmt.plural(row["taskCount"], "task"))


def _list_row(row):
    """One proposal as its cells, in `LIST_COLUMNS` order."""
    return [row["id"] or "?", row["status"] or "?", _reserved_cell(row),
            row["name"] or "-", "; ".join(row["openQuestions"]) or "-"]


def _empty_list_lines(view):
    """Empty is a RESULT, and which empty it is decides what to do next.

    Two independent facts, so two independent lines: whether the default filter
    hid history, and whether there is a plan at all. A single sentence covering
    both would have to pick one, and the reader needs the other one.
    """
    out = []
    if view["hidden"]:
        out.append("no open proposals - %d materialized/dropped record(s) are "
                   "history; `list all` reads them too" % (view["hidden"],))
    else:
        out.append("no proposals in this manifest")
    if not view["phaseCount"]:
        out.append("...and no phases either: /audit:init synthesizes a plan and "
                   "parks what you decline, rather than discarding it")
    return out


def _list_lines(view):
    """The table, as a person reads it. `--json` prints the structure instead.

    Widths are measured across every row and the header once, which is what makes
    the columns columns - the same reason `audit-status.py` measures its task
    table before printing any of it.
    """
    if not view["rows"]:
        return _empty_list_lines(view)
    rows = [_list_row(r) for r in view["rows"]]
    widths = [len(c) for c in LIST_COLUMNS]
    for cells in rows:
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "  ".join("%-*s" % (widths[i], cells[i])
                         for i in range(len(LIST_COLUMNS))).rstrip()

    out = [fmt_row(list(LIST_COLUMNS))]
    out += [fmt_row(cells) for cells in rows]
    if view["hidden"]:
        out.append("")
        out.append("%d materialized/dropped record(s) not shown - `list all` "
                   "reads them too" % (view["hidden"],))
    return out


def _list(mpath, rest, as_json):
    """`list` end to end: read, filter, print. It never locks and never writes."""
    extra = [a for a in rest if a not in ("all", "--all", "--json")]
    if extra:
        # Not a silent default listing: `list proposed` or a mistyped `all` would
        # otherwise print the default and read as if the argument had applied.
        sys.stderr.write("list takes `all` or nothing, not %r\n" % (extra[0],))
        return 2
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read %s: %s\n" % (mpath, exc))
        return 2
    view = _proposals.list_view(manifest,
                                include_all=bool({"all", "--all"} & set(rest)))
    if as_json:
        print(json.dumps(view, indent=2, sort_keys=True))
    else:
        for line in _list_lines(view):
            print(line)
    return 0


def _print_plan(plan):
    """The plan as a person reads it. `--json` prints the structure instead."""
    for bad in plan["refused"]:
        print("REFUSED %s: %s" % (bad["id"], bad["reason"]))
    for step in plan["steps"]:
        print("%s -> %s (%d task(s))%s"
              % (step["id"], step["phaseId"], step["taskCount"],
                 "" if not step["renamedFrom"]
                 else " [renamed from %s]" % (step["renamedFrom"],)))
        for ref in step["parkedDeps"]:
            print("    waits on %s, still parked" % (ref,))
        for ref in step["danglingRefs"]:
            print("    edge to %s resolves to nothing" % (ref,))
    if plan["needsDecision"]:
        print("\nthis pulls in %s - re-run with --with-deps to materialize them "
              "too, or --drop-edges to cut the edges"
              % (", ".join(plan["pulledIn"]),))


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(USAGE)
        return 2
    mpath, verb = argv[0], argv[1]
    rest = argv[2:]
    as_json = "--json" in rest
    if verb not in ("list", "plan", "materialize", "drop", "revive"):
        sys.stderr.write(USAGE)
        return 2

    # Before `--all` is resolved: `list` has no id to name and no closure to walk,
    # and routing it through `run()` would hand the read side an index lock and a
    # revalidation it has no use for.
    if verb == "list":
        return _list(mpath, rest, as_json)

    if "--all" in rest:
        if verb not in ("plan", "materialize"):
            sys.stderr.write("--all applies to plan and materialize only\n")
            return 2
        try:
            pids = _all_parked(_mio.load_manifest(mpath))
        except Exception as exc:
            sys.stderr.write("ERROR: cannot read %s: %s\n" % (mpath, exc))
            return 2
        policy = "with-deps"
    else:
        named = [a for a in rest if not a.startswith("-")]
        if not named:
            sys.stderr.write(USAGE)
            return 2
        pids = [named[0]]
        policy = ("with-deps" if "--with-deps" in rest
                  else "drop-edges" if "--drop-edges" in rest else None)

    ok, payload = _proposals.run(mpath, verb, pids, policy=policy,
                                 reason=_opt(rest, "--reason"),
                                 now=os.environ.get("AUDIT_NOW"))
    if not ok:
        if as_json:
            print(json.dumps({"ok": False,
                              "findings": payload.get("findings") or []},
                             indent=2))
        else:
            for line in (payload.get("findings") or []):
                sys.stderr.write("REFUSED: %s\n" % (line,))
        return 1

    if verb == "plan":
        plan = payload["plan"]
        if as_json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            _print_plan(plan)
        # The SAME code in both spellings: a `--json` plan that always exited 0
        # would let `plan && materialize` sail past a refusal, and one exit code
        # cannot mean two things depending on a flag.
        return 1 if plan["refused"] and not plan["steps"] else 0

    message = payload.get("message")
    lines = message if isinstance(message, list) else [message]
    if as_json:
        print(json.dumps({"ok": True, "message": lines,
                          "warnings": payload.get("warnings") or []}, indent=2))
    else:
        for line in lines:
            print(line)
        for line in (payload.get("warnings") or []):
            print("WARNING: %s" % (line,))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("materialize-proposal.py has no inline --selftest; its cases live "
              "in plugins/audit/tests/test_materialize_proposal.py - run that "
              "file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
