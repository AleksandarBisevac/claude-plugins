#!/usr/bin/env python3
"""
The cases for `_warning_groups.py` - the shape a repeated warning prints in.

Two kinds of fixture on purpose. The rendering rules are exercised on HAND-WRITTEN
lines, because they are a pure list -> list transform and a temp directory would
only slow them down; the two claims ABOUT the corpus - that a warning already
carries everything needed to decide whether two of them are the same finding, and
that the collapsed block really does replace the block a real plan produced - are
exercised on the output of `_manifest_rules.validate()` over a built manifest.
That split is the point of `no-silent-pass`'s rule about fixtures: a parser tested
only against lines its author wrote encodes one assumption twice.

EVERY POSITIVE HERE HAS ITS NEGATIVE. The collapse is a conditional, so it has two
wrong implementations - it never fires (the defect) and it always fires. `wg3` is
the second one: it asserts a single occurrence prints EXACTLY the bytes it printed
before this module existed, which is vacuous against the old code and is the only
case that goes red if a group of one starts announcing itself as a group.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio, some_of            # noqa: E402
import _warning_groups as M                        # noqa: E402
import _manifest_rules                             # noqa: E402

# The line the defect was measured on, with its item stripped off. Written once
# here so the fixture and the expected rendering cannot drift apart.
SKILLS_BODY = ("no skills resolve (task skills []; phase has no area tag) -- set "
               "task.skills, register default skills on an area in meta.areas, or "
               "write \"skills\": null to say 'none applies'")

# The plan the defect was measured on: six areas declared, one phase tagged, four
# untagged holding 7 + 5 + 1 + 6 tasks. The untagged counts are what produced
# nineteen identical lines, and `BF1` sits third so a renderer that sorted its
# phase ids instead of keeping document order would be visible.
MEASURED = (("P0", 7), ("P1", 5), ("BF1", 1), ("P8", 6))


# --- fixtures -------------------------------------------------------------------
def _plan(counts, prefix=None):
    """A manifest whose untagged phases hold tasks that resolve no skills.

    The leading TAGGED phase is not decoration: `_check_skills` is gated on
    `_skills_in_use`, so without a phase that really does resolve a skill the
    rule stays silent and every case below would pass over an empty list.

    `prefix` overrides the task-id stem so a case can build the document the
    id convention does NOT describe - the one where splitting `Q9.4` names a
    phase that is not in the manifest.
    """
    phases = [{"id": "PT", "title": "Tagged", "status": "pending", "area": "core",
               "tasks": [{"id": "PT.1", "title": "t", "status": "pending"}]}]
    n = 0
    for pid, count in counts:
        tasks = []
        for _i in range(count):
            n += 1
            tasks.append({"id": "%s.%d" % (prefix or pid, n if prefix else _i + 1),
                          "title": "t", "status": "pending", "skills": []})
        phases.append({"id": pid, "title": pid, "status": "pending", "tasks": tasks})
    return {"meta": {"version": 2,
                     "areas": {"core": {"root": "src", "skills": ["writing-python"]}}},
            "phases": phases}


def _owned(counts):
    """A manifest holding exactly the ids a hand-written line names."""
    return {"meta": {"version": 2},
            "phases": [{"id": pid, "title": pid, "status": "pending",
                        "tasks": [{"id": "%s.%d" % (pid, i + 1)}
                                  for i in range(count)]}
                       for pid, count in counts]}


def _ids(counts):
    return ["%s.%d" % (pid, i + 1) for pid, count in counts for i in range(count)]


def _lines(ids, body="b"):
    return ["task %s: %s" % (tid, body) for tid in ids]


def _skills_warnings(manifest):
    """Only the unresolved-skills lines - the rule the defect was measured on."""
    _findings, warnings = _manifest_rules.validate(manifest)
    return [w for w in warnings if ": no skills resolve" in w]


# --- cases ----------------------------------------------------------------------
def _cases(check):
    # --- the measured defect ---------------------------------------------------
    plan = _plan(MEASURED)
    raw = _skills_warnings(plan)
    check("wg1 the plan the defect was measured on still produces one warning per "
          "task, so the case below is collapsing a real block and not an empty "
          "list: %d" % (len(raw),),
          len(raw) == 19)
    got = M.collapse(raw, plan)
    want = ("19 tasks in 4 phases (P0, P1, BF1, P8; %s names each): %s"
            % (M.HINT, SKILLS_BODY))
    check("wg2 ...and they render as ONE line naming the count and the four "
          "phases in document order - counted, not looked for, because a "
          "renderer that emitted the group AND the members would satisfy a "
          "presence assertion: %d line(s), %s"
          % (len(got), some_of(got, render=repr)),
          len(got) == 1 and got[0] == want)

    # THE SECOND DIRECTION, and it is meant to read as vacuous. A collapse that
    # fires unconditionally renders `1 task (P0.1): ...` here, which is a new
    # output shape for every manifest small enough to have one occurrence.
    one = _plan((("P0", 1),))
    raw_one = _skills_warnings(one)
    check("wg3 a SINGLE occurrence prints the bytes it printed before this module "
          "existed - the compatibility case, and the only one that fails if a "
          "group of one starts announcing itself: %r" % (raw_one,),
          len(raw_one) == 1
          and M.collapse(raw_one, one) == raw_one
          and M.collapse(raw_one, one)[0].startswith("task P0.1: "))

    # --- what counts as the same finding ---------------------------------------
    mixed = M.collapse(_lines(["P0.1", "P0.2"], "remedy A")
                       + _lines(["P0.3"], "remedy B"), None)
    check("wg4 two warnings that differ in their REMEDY stay two lines while the "
          "pair that differs only in the item becomes one - three warnings in, "
          "two lines out: %r" % (mixed,),
          len(mixed) == 2
          and mixed[0] == "2 tasks (P0.1, P0.2): remedy A"
          and mixed[1] == "task P0.3: remedy B")

    # Same rule, same remedy, different BASIS. Kept apart deliberately: the basis
    # is half of what the reader acts on, and a group spanning two of them would
    # be claiming something neither warning said.
    two_bases = _plan((("P0", 2),))
    two_bases["phases"][1]["area"] = "empty"
    two_bases["meta"]["areas"]["empty"] = {"root": "src"}
    two_bases["phases"].append(
        {"id": "P1", "title": "P1", "status": "pending",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending", "skills": []},
                   {"id": "P1.2", "title": "t", "status": "pending", "skills": []}]})
    split = M.collapse(_skills_warnings(two_bases), two_bases)
    check("wg5 same rule and same remedy, two different bases - four warnings "
          "become TWO lines and not one, because equality of the whole message "
          "is the test: %r" % (split,),
          len(split) == 2
          and all(line.startswith("2 tasks (") for line in split)
          and len(set(split)) == 2)

    # --- nothing is dropped ----------------------------------------------------
    passthru = ["meta.ado.fields is empty, so it supplies nothing",
                "task P0.1: alone",
                "phase P1 and P2 both hold priority 3, which is one tier"]
    check("wg6 a line this cannot parse is passed through unchanged and none is "
          "lost - a reporter that dropped what it did not understand would look "
          "identical on the fixtures above",
          M.collapse(passthru, None) == passthru)

    # --- the threshold, exercised AT the boundary ------------------------------
    below = _owned((("P0", 5),))
    at = _owned((("P0", 6),))
    above = _owned((("P0", 4), ("P1", 3)))
    r_below = M.collapse(_lines(_ids((("P0", 5),))), below)
    r_at = M.collapse(_lines(_ids((("P0", 6),))), at)
    r_above = M.collapse(_lines(_ids((("P0", 4),)) + _ids((("P1", 3),))), above)
    check("wg7 one under the cap names every id and offers no escape hatch, "
          "because there is nothing left to escape to: %r" % (r_below,),
          len(r_below) == 1
          and r_below[0] == "5 tasks (P0.1, P0.2, P0.3, P0.4, P0.5): b")
    check("wg8 AT the cap the ids are still all named - the boundary itself, not "
          "either side of it: %r" % (r_at,),
          len(r_at) == 1
          and r_at[0] == ("6 tasks (P0.1, P0.2, P0.3, P0.4, P0.5, P0.6): b")
          and M.HINT not in r_at[0])
    check("wg9 one over the cap the line names the OWNING phases and the command "
          "that names every id, and no task id survives in it: %r" % (r_above,),
          len(r_above) == 1
          and r_above[0] == ("7 tasks in 2 phases (P0, P1; %s names each): b"
                             % (M.HINT,))
          and "P0.1" not in r_above[0])

    # --- the owner is read from the document, never from the id ----------------
    # `Q9.4` sits in `P0` and `Q9.5` in `P1`. Splitting the id would name one
    # phase called `Q9`, which is in no manifest at all - and the validator only
    # WARNS about an id that does not follow its phase's prefix, so this document
    # is one it accepts.
    crooked = _plan((("P0", 4), ("P1", 3)), prefix="Q9")
    r_crooked = M.collapse(_skills_warnings(crooked), crooked)
    check("wg10 a task whose id does not follow its phase prefix is still credited "
          "to the phase that HOLDS it - the naive split would print a phase this "
          "manifest does not contain: %r" % (r_crooked,),
          len(r_crooked) == 1
          and r_crooked[0].startswith("7 tasks in 2 phases (P0, P1; ")
          and "Q9" not in r_crooked[0])

    # ...and the refusal that goes with it: a set the manifest can only place
    # PART of is never described as "in N phases", because a partial attribution
    # reads as a complete one.
    partial = M.collapse(_lines(_ids((("P0", 6),)) + ["X1"]), _owned((("P0", 6),)))
    check("wg11 an item the manifest does not place stops the phase claim for the "
          "whole group and the line falls back to naming items: %r" % (partial,),
          len(partial) == 1
          and " in 1 phase" not in partial[0]
          and partial[0].startswith("7 tasks (P0.1, P0.2, P0.3, P0.4, P0.5, "
                                    "P0.6, +1 more; "))

    # --- no manifest ------------------------------------------------------------
    check("wg12 with no manifest the line still collapses but never claims a "
          "phase - `verbose` and `manifest=None` are different questions and a "
          "caller with neither must not get a guess",
          M.collapse(_lines(_ids((("P0", 7),))), None)
          == ["7 tasks (P0.1, P0.2, P0.3, P0.4, P0.5, P0.6, +1 more; %s names "
              "each): b" % (M.HINT,)])

    # --- verbose ----------------------------------------------------------------
    check("wg13 `verbose=True` returns every line unchanged - the escape hatch the "
          "elided line names has to exist, or the pointer is a lie",
          M.collapse(raw, plan, verbose=True) == raw and len(raw) == 19)

    # --- the decidability claim, over real validator output ---------------------
    # The module's claim is that NOTHING had to change about a warning to decide
    # whether two of them are the same finding. This is that claim, put to the
    # corpus: every line either has no locator or round-trips byte for byte.
    corpus = _manifest_rules.validate(_locator_corpus())[1]
    parsed = [M.locator(w) for w in corpus]
    trips = [w for w, loc in zip(corpus, parsed)
             if loc is not None and "%s %s: %s" % loc == w]
    check("wg14 every warning the validator produces either carries no locator or "
          "reconstructs from one EXACTLY - the proof that the message needed no "
          "new field, and both classes are non-empty so it cannot pass vacuously: "
          "%d parsed of %d" % (len(trips), len(corpus)),
          len(corpus) > 4
          and len(trips) == len([p for p in parsed if p is not None])
          and len(trips) > 0
          and len([p for p in parsed if p is None]) > 0)

    # --- order ------------------------------------------------------------------
    interleaved = ["task P0.1: zeta", "task P0.2: alpha", "task P0.3: zeta",
                   "task P0.4: alpha"]
    ordered = M.collapse(interleaved, None)
    check("wg15 a group renders where its FIRST member stood, so the output keeps "
          "the order the rules produced and does not sort - `zeta` before "
          "`alpha` is the observable half: %r" % (ordered,),
          ordered == ["2 tasks (P0.1, P0.3): zeta", "2 tasks (P0.2, P0.4): alpha"])
    check("wg16 two runs over one fixture print the same bytes - the determinism "
          "the repo's output rules ask for, compared across two separate "
          "`validate()` calls rather than two calls on one list",
          M.collapse(_skills_warnings(_plan(MEASURED)), _plan(MEASURED))
          == M.collapse(_skills_warnings(_plan(MEASURED)), _plan(MEASURED)))


def _locator_corpus():
    """A manifest that trips several unrelated rules at once.

    Deliberately mixed: `wg14` is only worth anything if the corpus contains both
    a warning that parses as a locator and one that does not, and a fixture built
    to please the parser would contain neither by accident.
    """
    return {
        "meta": {"version": 2,
                 "areas": {"core": {"root": "src", "skills": ["writing-python"]}},
                 "branch": {"template": "{who}/{nope}"},
                 "nosuchkey": 1},
        "phases": [
            {"id": "PT", "title": "T", "status": "pending", "area": "core",
             "tasks": [{"id": "PT.1", "title": "t", "status": "pending"}]},
            {"id": "P0", "title": "P0", "status": "pending", "priority": "high",
             "tasks": [{"id": "P0.1", "title": "t", "status": "pending",
                        "skills": []},
                       {"id": "P0.2", "title": "t", "status": "pending",
                        "skills": "writing-python"}]},
        ],
    }


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__warning_groups.py --selftest\n")
    raise SystemExit(2)
