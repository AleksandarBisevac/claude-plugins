#!/usr/bin/env python3
"""
Which audit items belong on the shared board at all, and why each one does not.

`_ado_tracked` holds the rules; this is the door the orchestrator knocks on
before it pushes anything, and the door `/audit:sync status` asks before it
calls a phase `unlinked`. A real command rather than a `python3 -c` one-liner
for `check-ado-item.py`'s reason, which is not style: a one-liner naming a
source path is exactly the shape `guard-secrets-read` refuses (F20/F22), so the
check would be blocked on the machines that most need it.

  resolve-ado-tracked.py <manifest> [--all | --phase P3 | --task P3.1] [--json]

`--all` is the default, because the push plan needs the whole picture and a
command whose default answers about nothing is a command people forget to scope.

IT LOADS THE MANIFEST THROUGH `_manifest_io`, AND THAT IS THE HALF THE RULES
CANNOT DO. `_ado_tracked` sits at layer 1 so every consumer can reach it, which
puts `_manifest_io` out of its reach as a layer-mate - so the assembly happens
here. It is not a formality: in the sharded layout the file at `manifestPath`
is an INDEX whose phases are stubs, and `adoTracked` lives in the shard body
with the tasks. A door that opened the file itself would see no declaration on
any phase and no task at all, and would report a whole plan TRACKED by default.
The rules refuse an un-assembled stub rather than trusting this door to be
right, and a case pins both halves.

Exit codes, and the missing one is the load-bearing one:
  0  answered - INCLUDING "nothing is tracked". A plan every phase of which is
     deliberately off the board is a plan, not a fault; and a command that
     exited non-zero over a declared, intended state would be switched off
     inside a day, taking the real answers with it.
  2  unreadable input, an unknown flag, or a scope naming nothing. NEVER read as
     a pass: "tracked: nothing" about an id that does not exist looks exactly
     like a plan that is deliberately internal.
  THERE IS NO EXIT 1. `resolve-ado-parent.py` has one because a hierarchy
  violation is a link nothing can build - a real refusal. "This phase is not on
  the board" is a normal state that somebody authored on purpose, and inventing
  a refusal for it would put this command in the way of the exact intent it was
  written to record.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_resolve_ado_tracked.py`.
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

import _ado_tracked as _tracked  # noqa: E402  (the rules this command is a door onto)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)

USAGE = ("usage: resolve-ado-tracked.py <manifest> "
         "[--all | --phase <id> | --task <id>] [--json]\n")


# --- arguments, and the scope they name -----------------------------------------
def parse_args(argv):
    """(options, error). `error` is a sentence, and then nothing else is read.

    Parsed into a dict rather than a tuple of four so that adding a flag is not
    an edit at every unpacking site, and returned WITH its error rather than
    raising, because a usage error is exit 2 and never an exception the caller
    has to translate.
    """
    opts = {"manifest": None, "scope": "all", "target": None, "json": False}
    rest = list(argv)
    if not rest or rest[0].startswith("-"):
        return (opts, "a manifest path is the first argument")
    opts["manifest"] = rest.pop(0)
    while rest:
        flag = rest.pop(0)
        if flag == "--json":
            opts["json"] = True
        elif flag == "--all":
            opts["scope"] = "all"
        elif flag in ("--phase", "--task"):
            if not rest:
                return (opts, "%s needs an id" % (flag,))
            opts["scope"] = flag[2:]
            opts["target"] = rest.pop(0)
        else:
            return (opts, "unknown flag %r" % (flag,))
    return (opts, None)


# --- the report -----------------------------------------------------------------
def outside_line(rows, scoped):
    """The items this run was NOT asked about, counted and graded.

    PRINTED EVEN WHEN THE SCOPE IS EVERYTHING, where it reads as zero. A scoped
    run's counts are facts about the scope, and a reader with no line telling
    them how much of the file was left out will read them as facts about the
    file - which is the same confusion between "nothing found" and "nothing
    looked at" that the counts above it exist to prevent.

    It does not change the exit code. Nothing outside the scope was asked about,
    and this command answers the question it was asked.
    """
    seen = set((r.get("kind"), r.get("id")) for r in scoped)
    rest = [r for r in rows if (r.get("kind"), r.get("id")) not in seen]
    tally = _tracked.counts(rest)
    return ("  outside this scope: %d item(s) not asked about, %d of them "
            "deliberately untracked, %d not answered"
            % (tally["items"], tally["untracked"], tally["unanswered"]))


def report(rows, scoped):
    """Every line this command prints, so `main()` decides only the exit code."""
    lines = list(_tracked.plan_lines(scoped))
    lines.append(outside_line(rows, scoped))
    # OVER THE WHOLE INVENTORY, never the scope: a `--phase P3` run printing
    # "0 bugs" would be answering about P3 in a sentence that reads as a fact
    # about the manifest. It sits beside the scope line for that reason.
    lines.append(_tracked.bug_line(rows))
    return lines


def verdict_line(scoped):
    """The closing sentence, and it is never a refusal.

    "NOTHING IS TRACKED" GETS ITS OWN WORDS rather than the ordinary OK line.
    An operator who has just pushed nothing needs to read why, and a command
    whose success sentence is identical whether it planned every phase or none
    is the shape that gets believed on the wrong day. It is still exit 0: the
    state was declared on purpose and this command records intent.
    """
    tally = _tracked.counts(scoped)
    if tally["items"] and not tally["tracked"]:
        return ("\nOK: NOTHING in scope belongs on the board - %d item(s), "
                "every one of them deliberately untracked or unanswered. That "
                "is an answer and not a fault; a push creates nothing here."
                % (tally["items"],))
    return ("\nOK: every in-scope item has an answer - %d on the board, %d "
            "deliberately untracked, %d not answered."
            % (tally["tracked"], tally["untracked"], tally["unanswered"]))


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

    inv = _tracked.inventory(manifest)
    rows = inv["rows"]
    scoped = _tracked.scope_rows(rows, opts["scope"], opts["target"])
    if opts["scope"] != "all" and not scoped:
        # Exit 2, never 0. "Tracked: nothing" about an id that does not exist
        # reads exactly like a plan somebody deliberately keeps internal, and
        # those are the two answers this whole feature is about keeping apart.
        sys.stderr.write("ERROR: no %s named %r in %s\n"
                         % (opts["scope"], opts["target"], opts["manifest"]))
        return 2

    if opts["json"]:
        # `counts` twice, over two row sets, because one of them is the answer
        # to what was ASKED and the other is the answer about the FILE. A
        # consumer given only the first cannot tell a manifest that tracks
        # nothing from a scope that happens to contain nothing tracked.
        print(json.dumps({"scope": opts["scope"], "target": opts["target"],
                          "rows": scoped,
                          "counts": _tracked.counts(scoped),
                          "manifestCounts": _tracked.counts(rows),
                          "warnings": inv["warnings"]},
                         indent=2, sort_keys=True))
        return 0

    for line in report(rows, scoped):
        print(line)
    for line in inv["warnings"]:
        print("WARNING: " + line)
    print(verdict_line(scoped))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("resolve-ado-tracked.py has no inline --selftest; its cases live "
              "in plugins/audit/tests/test_resolve_ado_tracked.py - run that "
              "file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
