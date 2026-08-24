#!/usr/bin/env python3
"""
Nineteen warnings that differ only in the task they name, rendered as one line.

WHY THIS IS NOT INSIDE THE RULE THAT PRODUCED THEM. On a real manifest the
unresolved-skills advisory printed one line per task -- nineteen of them, every
mutating command, every run -- and the cost was never the verbosity. It was what
those lines buried: a priority warning naming a phase that waits on a task
nobody has done sat inside the block, and the operator had already learned to
scroll past it. The rule was right and its three remedies were the right three;
only the SHAPE was wrong, and a shape is the reporter's job. `validate()` has no
notion of a repeated finding at all, so EVERY per-item rule has this defect
latent -- the skills one is simply the first to meet a manifest big enough.
Repairing it where the lines are rendered covers the next one for free.

WHAT COUNTS AS ONE FINDING, AND WHY NOTHING HAD TO CHANGE TO DECIDE IT. A
warning is already `"<kind> <ident>: <body>"` wherever it names one item -- a
locator of exactly two tokens, then the whole self-contained message. So two
warnings are the same finding when their bodies are EQUAL BYTE FOR BYTE, and
that test needs no new field, no id and no structured record: `_locator()`
round-trips, so a group of one re-renders its original line exactly.

Equality is the conservative reading on purpose. It never merges two lines whose
text differs, so a warning whose parenthetical BASIS differs ("phase has no area
tag" vs "area(s) core declare none") stays its own line even though the remedy
after it is identical -- the basis is half of what the reader acts on, and a
group that averaged two bases would be claiming something neither warning said.

WHAT IT COULD NOT DECIDE FROM THE STRING: WHICH PHASE. Nineteen task ids are not
actionable and four phase ids are, but `P0.1` implies `P0` only by a convention
the validator itself merely WARNS about (`_manifest_phases` flags an id that
does not follow its phase's prefix, and the manifest stays valid). Deriving the
owner by splitting the id would therefore be unsound on exactly the documents
this tolerates. The owner comes from `_manifest_io.iter_tasks` instead -- the
document, not the id -- which is why `collapse()` takes the manifest and why a
caller that has not got one degrades to naming items rather than to guessing.

FINDINGS ARE DELIBERATELY NOT COLLAPSED. A finding stops the command; it is read
one item at a time and every one of them has to be fixed, so being told there are
nineteen helps nobody and hides which to open first. The count already has a
home that prints it -- `INVALID: %d finding(s)` -- and a second, partial count in
front of it would be the repo's own defect about numbers in prose, in output.
`tests/test__warning_groups.py` pins the refusal, because a later tidy would
otherwise read the generality here as an invitation.

ORDER IS THE FIRST OCCURRENCE'S. A group renders where its first member stood
and its ids stay in document order, so `validate()`'s "findings and warnings each
keep the order they were produced in" survives, and two runs over one file print
the same bytes. Nothing here sorts by count: a tie would break arbitrarily and a
manifest edit would reshuffle lines it did not touch.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__warning_groups.py` - see `plugins/audit/tests/_harness.py`.
"""
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

import _fmt  # noqa: E402  (`plural` - the one place a noun agrees with its count)
import _manifest_io as _mio  # noqa: E402  (iter_tasks: the only sound task -> phase map)

# The nouns a locator may open with. A closed set rather than "the first token,
# whatever it is": `meta.ado.conventions: unknown key(s) ...` also splits on a
# colon, and reading `meta.ado.conventions` as an ITEM would let two unrelated
# config lines group the day their tails happened to match. Everything outside
# this set falls through untouched, which is the safe direction.
ITEM_KINDS = ("task", "phase", "bug", "proposal")

# Who owns an item, for the kinds where the question has an answer. A phase owns
# nothing above it, so a group of phase warnings names the phases themselves.
OWNER_KIND = {"task": "phase"}

# How many ids a collapsed line names before it stops naming them.
#
# BELOW IT the id list IS the complete answer: nothing is hidden, `--verbose`
# buys the reader nothing, and eliding would take away ids the un-collapsed
# output gave for free. ABOVE it the list is something a reader scans rather than
# reads, and for a per-item warning the owner is the unit the remedy applies to
# anyway -- "tag the phase" is one action for seven tasks.
#
# Six rather than the three `audit-status.budget_line` elides at, because that
# one truncates a RANKED list where the tail is by definition the least
# interesting entry, and here every item is implicated equally. Six rather than
# something roomier because a phase in a real plan routinely holds five or seven
# tasks, so a larger cap would reprint the block this module exists to replace.
NAMED_MAX = 6

# Where the ids went. Named as a COMMAND rather than as a bare flag because it is
# read from four other commands' output too, and "--verbose" alone would name a
# flag those commands do not have. `validate-manifest.py` passes its own spelling.
HINT = "validate-manifest.py --verbose"


# --- reading one line -------------------------------------------------------------
def locator(line):
    """`(kind, ident, body)` when the line opens with an item locator, else None.

    The round trip is the contract: `"%s %s: %s" % locator(line) == line` for
    every line this accepts, which is what lets a group of one re-render its
    original bytes and what makes byte-equality of `body` a sound test for "the
    same finding". A case asserts it over real validator output rather than over
    a hand-written line, because a fixture written beside the parser encodes the
    parser's assumption twice.

    Two tokens exactly. `phase P1 and P2 both hold priority 3 ...` opens with the
    right noun and is NOT a locator: its second token is followed by a word, not
    by the separator, so it falls through and prints as it always did.
    """
    if not isinstance(line, str):
        return None
    head, sep, body = line.partition(": ")
    if not sep:
        return None
    parts = head.split(" ")
    if len(parts) != 2 or parts[0] not in ITEM_KINDS or not parts[1]:
        return None
    return (parts[0], parts[1], body)


def task_owners(manifest):
    """`{task id: phase id}` - read from the document, never from the id.

    `iter_tasks` is the one walk that yields the pair, so this cannot disagree
    with the rest of the tree about which phase holds a task. A task whose id
    does not follow its phase's prefix is a WARNING and not a finding, so a
    manifest where the two readings disagree is a manifest this validator
    accepts - which is the whole reason the split-the-id shortcut is refused.
    """
    owners = {}
    for phase, task in _mio.iter_tasks(manifest):
        tid, pid = task.get("id"), phase.get("id")
        if isinstance(tid, str) and tid and isinstance(pid, str) and pid:
            owners.setdefault(tid, pid)
    return owners


# --- grouping ---------------------------------------------------------------------
def group(lines, manifest=None):
    """`[{kind, body, lines, items, owners, unowned}, ...]`, first-occurrence order.

    A line with no locator becomes its own group carrying `kind: None` — it is
    passed through rather than dropped, so the pipeline cannot lose a warning it
    did not understand.

    `unowned` counts the items whose phase the manifest does not name. It exists
    so the renderer can refuse to say "in 4 phases" over a set it could only
    place part of; a partial attribution is the shape that reads as complete and
    is not.
    """
    owners = task_owners(manifest) if isinstance(manifest, dict) else {}
    groups = []
    by_key = {}
    for line in lines:
        loc = locator(line)
        if loc is None:
            groups.append({"kind": None, "body": None, "lines": [line],
                           "items": [], "owners": [], "unowned": 0})
            continue
        kind, ident, body = loc
        key = (kind, body)
        grp = by_key.get(key)
        if grp is None:
            grp = {"kind": kind, "body": body, "lines": [], "items": [],
                   "owners": [], "unowned": 0}
            by_key[key] = grp
            groups.append(grp)
        grp["lines"].append(line)
        if ident not in grp["items"]:
            grp["items"].append(ident)
        owner = owners.get(ident) if kind in OWNER_KIND else None
        if owner is None:
            grp["unowned"] += 1
        elif owner not in grp["owners"]:
            grp["owners"].append(owner)
    return groups


# --- rendering --------------------------------------------------------------------
def _named(ids, limit):
    """`'a, b, c'`, or the first `limit` and how many were left out."""
    if len(ids) <= limit:
        return ", ".join(ids)
    return "%s, +%d more" % (", ".join(ids[:limit]), len(ids) - limit)


def render(grp, hint=None):
    """One line for one group — the original line, unchanged, when it holds one.

    THE ONE-MEMBER CASE IS RETURNED VERBATIM AND NOT REBUILT. A rebuilt line
    would read `1 task (P0.1): ...` and announce a group where a reader used to
    see a plain warning, which is a change of output every manifest small enough
    to have one occurrence would pay for nothing.
    """
    hint = HINT if hint is None else hint
    lines = grp["lines"]
    if len(lines) < 2:
        return lines[0]
    count = _fmt.plural(len(lines), grp["kind"])
    if len(grp["items"]) <= NAMED_MAX:
        return "%s (%s): %s" % (count, ", ".join(grp["items"]), grp["body"])
    if grp["owners"] and not grp["unowned"]:
        where = "%s in %s (%s" % (count,
                                  _fmt.plural(len(grp["owners"]),
                                              OWNER_KIND[grp["kind"]]),
                                  _named(grp["owners"], NAMED_MAX))
    else:
        where = "%s (%s" % (count, _named(grp["items"], NAMED_MAX))
    return "%s; %s names each): %s" % (where, hint, grp["body"])


def collapse(lines, manifest=None, verbose=False, hint=None):
    """The warnings a human should read: one line per distinct finding.

    `verbose=True` returns them unchanged, which is the escape hatch every
    elided line names. It is a separate argument rather than "pass no manifest"
    because those two mean different things: no manifest still collapses, it
    just cannot say which phases.
    """
    if verbose:
        return list(lines)
    return [render(grp, hint) for grp in group(lines, manifest)]


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_warning_groups.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__warning_groups.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
