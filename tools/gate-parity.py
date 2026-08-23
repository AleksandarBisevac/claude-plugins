#!/usr/bin/env python3
"""
Every description of the gate set must name the same gates.

    tools/gate-parity.py            # the check
    tools/gate-parity.py --list     # what each side invokes, side by side
    tools/gate-parity.py --selftest # this file's own cases

WHY. The gate set is described in more than one place by hand, and by the time
anyone measured it the copies had drifted IN BOTH DIRECTIONS at once:

  * the selftest sweep existed twice with different strictness, so a file that
    exited 0 having asserted nothing was green locally and red in CI;
  * `npx vitest run` - 28 files, 305 tests - ran only in CI, so a change under
    `scripts/ui/` could reach a push with none of its suites having run;
  * `vermin` covered three directories locally and two in CI, so a 3.9+ construct
    in a test file passed CI and failed locally.

Copies of one list are how that happens, and fixing each instance by hand is how it
happens again. This makes the parity a CHECK: a gate named by one side and not by
another fails the build, naming both.

IT COMPARES FOUR SIDES, and every document among them was added because nothing had
ever compared it. `verify.sh` and `ci.yml` were compared for a while and
`CONTRIBUTING.md` was not - while saying of itself "the individual commands stay
documented below, because they are the definition and the script is only a caller".
A document that claims to be the definition owes every gate; it carried seven of
thirteen when it was finally read.

`CLAUDE.md` was that shape one file over, and it said so of ITSELF: its list carried
the comment "this list, verify.sh and ci.yml, compared" while being the one side
nothing here read. It named the sweep, this check, vitest, ruff and vermin; of the
rest of the local set it named the two browser gates in prose only, and the hook
import budget, the artifact comparison and the demo gate not anywhere in the
document. The manifest and plugin-structure half it leaves out ON PURPOSE and says
so - that split is rows in the table below now instead of one sentence covering an
unmeasured remainder, and the remainder is exactly where it had rotted.

WHAT IT COMPARES, AND WHY THAT GRAIN. The set of REPO SCRIPTS and NAMED EXTERNAL
GATES each side invokes - not the full command lines. Arguments legitimately differ
(CI renders into a throwaway `/tmp` tree; `verify.sh` checks the committed
artifacts) and comparing them would produce noise that trains a reader to ignore
this. What may never differ is WHICH checks exist.

EXEMPTIONS ARE DECLARED, WITH A REASON, AND ARE THEMSELVES CHECKED. An entry in
either table below that names a gate neither side invokes any more is reported too -
otherwise the tables become a place where dead exemptions accumulate and the check
quietly stops covering what it claims.

IT ALSO HOLDS ONE RULE ABOUT THE RUNNER ITSELF, because it is already the thing
that reads `verify.sh` for a living: no runnable line may name a temp path that a
second concurrent run would share. That is not a parity question, but it is a
property of the gate runner, and the alternative was a second reader of the same
file. See `scratch_isolation()` for what went wrong when the paths were fixed.
"""
import io
import os
import re
import shutil
import sys
import tempfile

_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

_output.install_path()

import _refs  # noqa: E402  (it owns "the runnable region of a document")

VERIFY_REL = os.path.join("tools", "verify.sh")
CI_REL = os.path.join(".github", "workflows", "ci.yml")
DOC_REL = "CONTRIBUTING.md"
CLAUDE_REL = "CLAUDE.md"

# (label, path). The label is what a finding names and what a table row exempts, so
# it is short on purpose - a reader should not have to know the path to read the
# reason.
SIDES = (("verify.sh", VERIFY_REL), ("ci.yml", CI_REL),
         ("CONTRIBUTING.md", DOC_REL), ("CLAUDE.md", CLAUDE_REL))

# A repo script invoked as a command. Anchored on the two directories that hold
# them, so a bare basename in prose is not mistaken for an invocation.
_SCRIPT_RE = re.compile(
    r"(?:tools|plugins/audit/(?:scripts|hooks))/[A-Za-z0-9_./-]+\.(?:py|mjs|sh)")

# Gates that are not a file in this repo. Each is a fixed label rather than a
# command, because their spellings legitimately differ (`npx --yes ajv-cli` here,
# a pinned install there) while the gate is the same gate.
_EXTERNAL = (
    ("npx vitest", re.compile(r"\bvitest run\b")),
    ("ruff", re.compile(r"\bruff check\b")),
    ("vermin", re.compile(r"\bvermin -t=")),
    ("ajv-cli", re.compile(r"\bajv-cli validate\b")),
    ("claude plugin validate", re.compile(r"\bclaude plugin validate\b")),
)

# FOUR SIDES, and one table that can express all of them. `CI_ONLY` and `LOCAL_ONLY`
# were two tables for two sides, and adding CONTRIBUTING.md as a third would have
# needed a third - with a gate absent from two sides needing an entry in each. One
# row per gate, listing the sides it is legitimately absent FROM, and a reason a
# reader can disagree with. The fourth side then cost this table ROWS and not a
# shape, which is the argument for the shape.
#
# Both documents are here because each claims to be the definition. CONTRIBUTING.md
# says of itself: "The individual commands stay documented below, because they are
# the definition and the script is only a caller." CLAUDE.md's list says "which
# remain the definition". A document that claims that owes every gate it does not
# hand to another document IN WRITING - and the writing is what the rows below are.

# THE SIDES A ROW USUALLY NAMES, named once. A CI-only smoke test is absent from
# every description of the LOCAL set for one reason, and spelling the labels into
# each such row is how one of them gets forgotten the next time a side is added -
# which is most of how CLAUDE.md came to be uncompared in the first place.
DOC_SIDES = ("CONTRIBUTING.md", "CLAUDE.md")
LOCAL_SIDES = ("verify.sh",) + DOC_SIDES

ABSENT_BY_DESIGN = (
    ("plugins/audit/scripts/demo/gen-demo-manifest.py", LOCAL_SIDES,
     "builds a throwaway demo tree in /tmp to smoke the pipeline end to end; the "
     "local set checks the COMMITTED artifacts instead"),
    ("plugins/audit/scripts/demo/gen-demo-usage.py", LOCAL_SIDES,
     "same throwaway demo tree"),
    ("plugins/audit/scripts/report/render-report.py", LOCAL_SIDES,
     "rendered into /tmp as a smoke test; locally the equivalent claim is "
     "check-rendered-artifacts.py, which is stronger because it compares bytes"),
    ("plugins/audit/scripts/status/audit-doctor.py", LOCAL_SIDES,
     "an end-to-end CLI smoke test over a fixture project"),
    ("plugins/audit/scripts/status/audit-status.py", LOCAL_SIDES,
     "exercises --gate's exit codes, which need a fixture manifest per case"),
    ("plugins/audit/hooks/py-launch.sh", LOCAL_SIDES,
     "the launcher is driven directly with fixture projects and with PATH unset, to "
     "prove the WIRING rather than decide(): the interpreter fallback, the stdin "
     "contract and the emitted JSON. Neither unsetting PATH nor feeding three "
     "fixture manifests is a thing to do to a developer's shell. The hooks it drives "
     "are ARGUMENTS to it, not paths, so this one entry covers all of them"),
    ("tools/affected.py", ("ci.yml",) + DOC_SIDES,
     "a SELECTOR, not a gate: it narrows a local run and CI never narrows. Its own "
     "cases DO run on every side - inside the sweep, which covers tools/ - so what "
     "is exempt is the narrowing, not the checking of it"),
    ("tools/verify.sh", ("verify.sh", "ci.yml", "CLAUDE.md"),
     "the caller. CONTRIBUTING.md names it as the one command to run; it does not "
     "invoke itself, and CI runs the gates rather than the wrapper. CLAUDE.md names "
     "it in the prose ABOVE its list, and the list is by construction the commands "
     "it calls"),

    # THE SPLIT BETWEEN THE TWO DOCUMENTS, per gate instead of per sentence.
    # CLAUDE.md's Tests section says CONTRIBUTING.md "has the manifest and
    # plugin-structure checks that complete the pre-PR set", and CLAUDE.md's own
    # preamble says it "deliberately restates no procedure, because two copies of a
    # procedure is one copy and one lie". That sentence is a real division of labour
    # and these rows are it, said gate by gate - because as one sentence it also
    # covered an unmeasured remainder, and the remainder had rotted: the hook import
    # budget, the artifact comparison and the demo gate were in neither half.
    ("plugins/audit/scripts/manifest/validate-manifest.py", ("CLAUDE.md",),
     "a manifest check, and CLAUDE.md hands the manifest half to CONTRIBUTING.md, "
     "whose list carries both invocations with the reasoning. CLAUDE.md's hard rules "
     "do name this script - as the thing every mutating command must call, which is "
     "the rule and not the gate"),
    ("ajv-cli", ("CLAUDE.md",),
     "the manifest's JSON Schema: same half, handed to the same document"),
    ("claude plugin validate", ("CLAUDE.md",),
     "the plugin and marketplace structure: same half, same document"),

    # NAMED BY CLAUDE.md ALONE, AND NEITHER IS A GATE. Both print and exit 0, so
    # there is nothing for a runner to fail on. They need rows because a side that
    # names them makes them reportable - which is the whole difference the fourth
    # side made to this table.
    ("tools/count-ui-pins.py", ("verify.sh", "ci.yml", "CONTRIBUTING.md"),
     "a REPORT, not a gate - its own usage says `Exit codes: 0 always`. It prints "
     "the change budget for an edit under scripts/ui/, which is a thing to read "
     "before starting and not a thing to fail. Its own cases run in the sweep, "
     "which covers tools/"),
    ("tools/prove-gates.py", ("verify.sh", "ci.yml", "CONTRIBUTING.md"),
     "minutes rather than seconds, and it MUTATES the tree while it runs, so it is "
     "not a per-commit gate. This was once the argument for no row at all: a gate no "
     "side named could never be reported missing, so the row would have asserted "
     "nothing. That premise died with the fourth side - CLAUDE.md carries the "
     "command, so this row now goes stale the day one of the other three adopts it"),
)


# --- reading each side's gate set --------------------------------------------
def _shell_command_lines(text):
    """Every line of a shell script that could be a command.

    A comment naming a tool is not an invocation of it, and both gate files talk
    about their own gates at length - this file's own docstring would otherwise
    register as a gate set of its own.
    """
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(line.split(" #")[0].strip())
    return out


def _yaml_run_lines(text):
    """Only what a workflow actually RUNS: `run:` values and their block scalars.

    NOT every non-comment line, which is what this did first - and a step whose
    `name:` mentioned a tool registered as an invocation of it, so renaming a step
    changed the gate set. A workflow is mostly keys; the commands live in exactly
    one of them.

    An inline `run: cmd` contributes its remainder; a block form (`run: |`)
    contributes every following line indented deeper than the `run:` key itself,
    which is what ends the block in YAML.
    """
    out = []
    depth = None
    for line in text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if depth is not None:
            if stripped and indent <= depth:
                depth = None
            elif not stripped or not stripped.startswith("#"):
                out.append(line.split(" #")[0].strip())
                continue
        if stripped.startswith("#"):
            continue
        match = re.match(r"(\s*)run:\s*(.*)$", line)
        if match:
            depth = len(match.group(1))
            rest = match.group(2).strip()
            if rest and rest not in ("|", ">", "|-", ">-", "|+", ">+"):
                out.append(rest)
    return out


def _markdown_fence_lines(rel, text):
    """The fenced blocks of a Markdown document - what it tells a reader to RUN.

    `_refs._runnable_text` already owns this question for the sweep-shape rule, and
    a second definition of "the runnable region of a document" is how two rules come
    to disagree about what a document says. Borrowed, not rewritten.

    `rel` is a parameter and not `DOC_REL` because it was `DOC_REL`: hard-coding the
    one Markdown side made a second one unaddable, which is a small reason a document
    claiming to be the definition went uncompared for as long as it did. Only the
    extension is read from it.
    """
    runnable, problem = _refs._runnable_text(rel, text)
    if problem is not None or runnable is None:
        return []
    out = []
    for line in runnable.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Cut the TRAILING comment too, exactly as `_shell_command_lines` does. It did
        # not, so a fenced command annotated `# see tools/foo.mjs` named a gate on this
        # side while the identical annotation in verify.sh did not - and a list a
        # reader is meant to annotate is precisely what this side is.
        out.append(line.split(" #")[0].strip())
    return out


# --- one scratch root per run, and one place that derives it ------------------
# `verify.sh` kept every step log AND every parallel leg's exit code at a FIXED
# /tmp path, so two runs on one machine shared them. A crossed log is a nuisance;
# `.rc` is not a log. The leg WRITES its exit code there and the reader turns it
# into the verdict, and both runs number their legs from zero - so one could read
# the other's success and print `ok` for work it never did. `affected.txt` is the
# LIST OF STEPS, so a crossed read runs somebody else's gates and skips its own,
# which the summary spells exactly like a pass.
#
# What that repair leaves behind is small enough to check by rule: a runnable line
# may name a temp root ONLY where `mktemp` derives the per-run directory; everything
# else goes through the variable holding it. Read over the RUNNABLE region, so the
# comment above the fix - which has to name the old paths to explain itself - stays
# legal. Same scoping `_refs.sweep_glob_drift()` uses, for the same reason.
_TEMP_ROOT = re.compile(r"/tmp/|\$\{?TMPDIR")


def _scratch_violations(text):
    """{"violations": [(line, problem)], "examined": n} for one shell script.

    `examined` sits beside the list because a filter that narrowed to nothing must
    not be spelled the same way as a script that is clean. An unreadable file or a
    splitter that stopped working yields no runnable lines at all, and "no
    violations" over zero lines is the silent pass this repo keeps re-finding.
    """
    lines = _shell_command_lines(text)
    out = []
    for line in lines:
        if not _TEMP_ROOT.search(line):
            continue
        # The one derivation is allowed to name the root; it is what makes the
        # path unique. Exempting `mktemp` rather than a spelling keeps this about
        # WHO derives the directory instead of about how the line looks.
        if "mktemp" in line:
            continue
        out.append((line, "names a temp path directly, so a second run on this "
                          "machine shares it - route it through the per-run "
                          "scratch directory"))
    return {"violations": out, "examined": len(lines)}


def scratch_isolation(repo=None):
    """The same question asked of the real `verify.sh`."""
    path = os.path.join(repo or REPO, VERIFY_REL)
    try:
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (IOError, OSError, UnicodeDecodeError) as exc:
        # Loud rather than empty: "I could not read the runner" and "the runner is
        # clean" are different answers, and returning [] would tell the first as
        # the second.
        return {"violations": [(VERIFY_REL, "could not be read: %s" % exc)],
                "examined": 0}
    return _scratch_violations(text)


def gates_in(path):
    """The set of gate labels a file invokes, or None if it cannot be read.

    None rather than an empty set: "this file is not there" and "this file runs no
    gates" are different answers, and a check that spells them the same way reports
    a missing workflow as perfect parity.
    """
    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError:
        return None
    found = set()
    if path.endswith((".yml", ".yaml")):
        lines = _yaml_run_lines(text)
    elif path.endswith(".md"):
        lines = _markdown_fence_lines(path, text)
    else:
        lines = _shell_command_lines(text)
    body = "\n".join(lines)
    for match in _SCRIPT_RE.finditer(body):
        found.add(match.group(0))
    for label, pattern in _EXTERNAL:
        if pattern.search(body):
            found.add(label)
    return found


def compare(read, table=None):
    """{"missing": [(gate, side, note)], "stale_exemptions": [...]} from READ sets.

    A gate must be named by EVERY side unless a row in the table says which sides it
    is legitimately absent from and why. Two tables for two sides became one table
    for four, because a gate absent from three sides would otherwise need an entry in
    each and the three could disagree.

    Takes the gate sets rather than a repo path so a case can hand it four sets that
    differ in one place. Proving that a particular side is really compared needs a
    gate withheld from that side alone, and building four real files to do it would
    be a case about the readers wearing a case about the rule.
    """
    table = ABSENT_BY_DESIGN if table is None else table
    absent = [label for label, _rel in SIDES if label not in read]
    if absent:
        # Loud, and NOT a verdict over the sides the caller did remember: a side with
        # no gate set read for it would otherwise be an empty set, and an empty set
        # agrees with every exemption and disagrees with every gate.
        return {"missing": [],
                "stale_exemptions": [(", ".join(sorted(absent)), "-",
                                      "no gate set was read for this side")]}

    exempt = {}
    for gate, sides, _why in table:
        exempt[gate] = set(sides)
    every = set()
    for names in read.values():
        every |= names

    missing = []
    for gate in sorted(every):
        for label, _rel in SIDES:
            if gate in read[label]:
                continue
            if label in exempt.get(gate, ()):
                continue
            missing.append((gate, label,
                            "named by another side and not by this one; add it or "
                            "give it a row in ABSENT_BY_DESIGN"))

    # THREE WAYS AN EXEMPTION STOPS DESCRIBING THE SYSTEM. The third is the one a
    # single-direction check cannot see, and it is why this is checked at all: a row
    # naming a side that DOES run the gate is not an exemption, it is a sentence
    # about a state that has passed, and it stays green forever under the first two.
    stale = []
    for gate, sides, _why in table:
        if gate not in every:
            stale.append((gate, "-", "declared absent by design, but no side "
                                     "invokes it any more"))
            continue
        for label in sides:
            if label not in dict(SIDES):
                stale.append((gate, label, "names a side that does not exist"))
            elif gate in read[label]:
                stale.append((gate, label, "declared absent from this side, which "
                                           "invokes it - the row does nothing"))
    return {"missing": sorted(missing), "stale_exemptions": sorted(stale)}


def read_sides(repo=None):
    """{label: gate set or None} for every side, read once.

    None survives to the caller on purpose - `gates_in` earns the distinction and
    flattening it here would spend it.
    """
    repo = repo or REPO
    return dict((label, gates_in(os.path.join(repo, rel)))
                for label, rel in SIDES)


def parity(repo=None):
    """{"missing": [...], "stale_exemptions": [...], "counts": {}} for the tree."""
    raw = read_sides(repo)
    read = {}
    unreadable = []
    for label, rel in SIDES:
        got = raw[label]
        if got is None:
            unreadable.append((rel, label, "could not be read at all"))
        read[label] = got if got is not None else set()
    counts = dict((k, len(v)) for k, v in read.items())
    if unreadable:
        # NOT an empty verdict. A side nothing could read is not a side that agrees.
        return {"missing": [], "stale_exemptions": unreadable, "counts": counts}
    result = compare(read)
    result["counts"] = counts
    return result


# --- was each side really READ? -----------------------------------------------
# `compare()` answers "do the sides agree", and agreement is worth nothing from a
# side nobody read: an empty set agrees with every other side and with every row in
# the table. So the suite carries a floor, and the floor is what F69 was about - it
# was one ABSOLUTE term, which catches a reader that returned nothing and cannot
# catch a document that rotted while the others stood. It sat below the smallest
# side, so that side could have shed half its gates and still cleared it.
#
# TWO TERMS NOW. The absolute one is unchanged - it is the answer to "did this read
# return anything at all", and nothing about it was wrong. The derived one measures
# a side against the largest count anyone read, which is the best available evidence
# of how big the gate set really is.
#
# WHAT THE DERIVED TERM GIVES UP, SAID RATHER THAN IMPLIED. It COUPLES the sides: if
# every side shrinks together the floor shrinks with them and this stays green, and
# no floor derived from the thing it measures can do otherwise. That case is covered
# elsewhere and not here - `compare()`'s stale-exemption half reports every row in
# ABSENT_BY_DESIGN whose gate no side invokes any more, so a gate set that collapsed
# across all four sides comes back as a table full of dead rows rather than as a
# quiet pass. It also leaves the LARGEST side judged by the absolute term alone,
# which is arithmetic rather than a choice: a count is never below its own fraction.
FLOOR_MINIMUM = 6
FLOOR_DIVISOR = 2


def read_floor(counts):
    """The fewest gates a side may name before its set stops being evidence of a read.

    Derived from the largest count rather than per-side from the largest OTHER count,
    which was written first and is the same function: the two can only differ for the
    largest side itself, and there the fraction is of a number that cannot fall below
    it. One number is also what a message can print.
    """
    largest = max(counts.values(), default=0)
    return max(FLOOR_MINIMUM, (largest + FLOOR_DIVISOR - 1) // FLOOR_DIVISOR)


def underread_sides(counts):
    """[(label, gates, floor)] for every side that named fewer gates than the floor.

    A list rather than a bool so the finding names the side and both numbers - which
    side rotted and by how far is the whole content of this check, and `False` is a
    thing nobody can act on.

    Iterates SIDES rather than `counts`, and reads a missing label as none named: a
    side absent from the counts is the strongest version of "not read", and
    `.get(label, 0)` sends it through the same floor as a side that read short.
    """
    floor = read_floor(counts)
    return [(label, counts.get(label, 0), floor)
            for label, _rel in SIDES if counts.get(label, 0) < floor]


def render(result, stream=None):
    """Print the verdict. Returns the exit code."""
    out = stream if stream is not None else sys.stdout
    bad = result["missing"] + result["stale_exemptions"]
    out.write("gate parity: %s\n"
              % (", ".join("%d in %s" % (result["counts"].get(label, 0), label)
                           for label, _rel in SIDES),))
    for gate, side, note in result["missing"]:
        out.write("  MISSING from %s: %s\n      %s\n" % (side, gate, note))
    for gate, side, note in result["stale_exemptions"]:
        out.write("  stale exemption (%s / %s): %s\n" % (gate, side, note))
    if not bad:
        out.write("  every side names the same gates, and every declared "
                  "exemption is still real\n")
    return 1 if bad else 0


def render_list(raw, stream=None):
    """One column per side, headed by its label. Returns the number of gates listed.

    Derived from SIDES, because it was two hard-coded columns spelled `L` and `C`:
    `CONTRIBUTING.md` was invisible here for as long as it had been a side, in the
    one output whose whole job is to show what each side invokes. That is the drift
    this file reports, inside the file that reports it.

    An unreadable side prints `?` rather than an empty column - a side nothing could
    read must not look like a side that runs nothing.
    """
    out = stream if stream is not None else sys.stdout
    every = set()
    for names in raw.values():
        every |= (names or set())
    out.write("  %s  gate\n" % "  ".join(label for label, _rel in SIDES))
    for gate in sorted(every):
        cells = []
        for label, _rel in SIDES:
            names = raw.get(label)
            mark = "?" if names is None else ("x" if gate in names else "-")
            cells.append("%-*s" % (len(label), mark))
        out.write("  %s  %s\n" % ("  ".join(cells), gate))
    return len(every)


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    result = parity()
    if "--list" in argv:
        render_list(read_sides())
    return render(result)


# --- selftest -----------------------------------------------------------------
def _cases():
    out = []
    real = parity()
    out.append(("p0", real["missing"] == [] and real["stale_exemptions"] == [],
                "THE LIVE CLAIM: every description of the gate set names the "
                "same gates and no exemption has gone stale (%s) - %r"
                % (", ".join("%s=%d" % (k, v)
                             for k, v in sorted(real["counts"].items())),
                   real["missing"] + real["stale_exemptions"])))

    out.append(("p1", underread_sides(real["counts"]) == [],
                "...and every side was really READ, so p0 is not a row of empty "
                "sets agreeing: every side clears a floor of %d, the larger of the "
                "absolute term and the largest side's share. It is also the case a "
                "floor set too HIGH fails - the sides legitimately differ in size, "
                "so a floor AT the largest count would report the smallest side as "
                "unread: %r / %r"
                % (read_floor(real["counts"]), real["counts"],
                   underread_sides(real["counts"]))))

    # THE FIXTURE VALUE IS THE OLD FLOOR'S BLIND SPOT (F69), which is the only
    # reason this case is worth anything: `p1` compared each count with a fixed
    # number that the rotted side below CLEARS. Both versions score this fixture,
    # and they disagree about it.
    rotted = dict((label, 14) for label, _r in SIDES)
    rotted["CLAUDE.md"] = 6
    out.append(("p2", underread_sides(rotted) == [("CLAUDE.md", 6, 7)],
                "a document that rotted while the other sides stood IS reported, "
                "by name and with both numbers - the count it named and the floor "
                "the rest of the tree sets: %r" % (underread_sides(rotted),)))

    empty = dict((label, 0) for label, _r in SIDES)
    out.append(("p3", underread_sides(empty)
                == [(label, 0, FLOOR_MINIMUM) for label, _r in SIDES],
                "...and a run where NOTHING was read reports every side, at the "
                "ABSOLUTE floor. This is the direction the derived term cannot "
                "cover on its own - a fraction of nothing is nothing, and a floor "
                "of 0 would let the emptiest possible read pass: %r"
                % (underread_sides(empty),)))

    live = scratch_isolation()
    out.append(("sc0", live["violations"] == [] and live["examined"] > 0,
                "THE LIVE CLAIM: no runnable line in verify.sh names a temp path a "
                "second run would share, over %d runnable line(s) - the count is "
                "here so this cannot be an empty read agreeing with itself: %r"
                % (live["examined"], live["violations"])))

    fixed = _scratch_violations("run() {\n  cmd >/tmp/verify-step.log 2>&1\n}\n")
    out.append(("sc1", len(fixed["violations"]) == 1,
                "...and a fixed path IS reported, which is what tells sc0 apart "
                "from a rule that cannot fire at all: %r" % (fixed["violations"],)))

    derived = _scratch_violations(
        'WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/verify-XXXXXX")\n')
    out.append(("sc2", derived["violations"] == [] and derived["examined"] == 1,
                "the ONE derivation may name the root - deriving it is what makes "
                "the path unique - and the line was READ rather than skipped, so "
                "this is an exemption and not a blind spot: %r" % (derived,)))

    prose = _scratch_violations("# it used to write /tmp/verify-step.log\n")
    out.append(("sc3", prose["violations"] == [] and prose["examined"] == 0,
                "a comment naming the old path is history, not a command - and "
                "`examined` says 0 instead of letting the empty result read as "
                "clean, which is the half sc0 pairs with: %r" % (prose,)))

    # THE INVENTED GATE NAMES BELOW CARRY THE JAVASCRIPT MODULE EXTENSION, and it is
    # not decoration: `_refs.tool_basename_drift()` holds that a `.py` basename
    # written anywhere under `tools/` must name a file that exists, prose included,
    # and a fixture nobody creates is exactly what a stale reference looks like. That
    # rule's docstring is where the spellings live; `_SCRIPT_RE` above accepts every
    # extension it may see, so these fixtures are faithful and not evasions. Do not
    # "fix" them to the Python extension - the lint will stop the commit, and the
    # thing it is protecting is the rule rather than these names.
    body = _shell_command_lines(
        "# node tools/ghost.mjs\n  ruff check x  # ruff check y\n")
    out.append(("c0", body == ["ruff check x"],
                "a commented invocation is NOT an invocation, and a trailing "
                "comment is cut - all three files discuss their own gates at "
                "length, so without this every mention would register: %r" % (body,)))

    yml = _yaml_run_lines(
        "      - name: something about tools/ghost.mjs\n"
        "        shell: bash\n"
        "        run: node tools/real.mjs\n"
        "      - name: block form\n"
        "        run: |\n"
        "          # a comment about tools/commented-fixture\n"
        "          python tools/block-fixture\n"
        "      - name: after the block, tools/after.mjs\n")
    out.append(("c1", yml == ["node tools/real.mjs", "python tools/block-fixture"],
                "a workflow is mostly KEYS: only `run:` values and their block "
                "scalars are commands, so renaming a step cannot change the gate "
                "set. Written as 'every non-comment line' first, and a step name "
                "mentioning verify.sh registered as an invocation of it: %r"
                % (yml,)))

    md = _markdown_fence_lines(
        DOC_REL,
        "Prose naming `node tools/ghost.mjs` at length.\n\n"
        "```bash\n# a comment about tools/commented-fixture\n"
        "node tools/real.mjs  # a trailing note about tools/trailing-fixture\n"
        "```\n\nMore prose about tools/after.mjs.\n")
    out.append(("c2", md == ["node tools/real.mjs"],
                "a Markdown document is mostly PROSE, and this one argues about its "
                "own gates for pages: only fenced blocks are commands. The reader "
                "comes from `_refs`, which already owns 'the runnable region of a "
                "document' for the sweep-shape rule - a second definition of that is "
                "how two rules come to disagree about what a document says. The "
                "TRAILING note is cut as well, which it was not: an annotated command "
                "in a fence named a gate the identical annotation in verify.sh did "
                "not, and a list a reader is meant to annotate is what this side is: "
                "%r" % (md,)))

    tmp = _output.REPO_ROOT  # any real directory; the point is the missing file
    res = parity(os.path.join(tmp, "no-such-repo-dir"))
    out.append(("m0", len(res["stale_exemptions"]) == len(SIDES)
                and all("could not be read" in n
                        for _g, _s, n in res["stale_exemptions"]),
                "every unreadable side is a NAMED failure, not perfect parity - "
                "empty sets for all three would report three missing files as "
                "agreement: %r" % (res["stale_exemptions"],)))

    seen = gates_in(os.path.join(REPO, VERIFY_REL))
    out.append(("g0", "npx vitest" in seen and "ruff" in seen
                and "tools/sweep-selftests.py" in seen,
                "the extractor finds an external gate, a linter and a repo script "
                "in the real verify.sh - three different shapes, so a pattern that "
                "silently stopped matching one of them fails here"))

    fx = tempfile.mkdtemp(prefix="gate-parity-")
    commented = os.path.join(fx, "commented.sh")
    running = os.path.join(fx, "running.sh")
    io.open(commented, "w", encoding="utf-8").write(
        "# node tools/ghost.mjs is what we used to run\n")
    io.open(running, "w", encoding="utf-8").write("node tools/ghost.mjs\n")
    seen_c, seen_r = gates_in(commented), gates_in(running)
    shutil.rmtree(fx, ignore_errors=True)
    out.append(("g1", seen_c == set() and seen_r == set(["tools/ghost.mjs"]),
                "THE PAIR: two fixtures differing ONLY in whether the mention is a "
                "comment give OPPOSITE answers, so the comment rule is doing work "
                "rather than the extractor finding nothing either way. Asserting "
                "the empty one alone would pass on a version that always returned "
                "an empty set (%r vs %r)" % (seen_c, seen_r)))

    labels = set(label for label, _r in SIDES)
    bad_side = [(g, s) for g, sides, _w in ABSENT_BY_DESIGN for s in sides
                if s not in labels]
    out.append(("e0", bad_side == [],
                "every exemption names a side that EXISTS - a row pointing at a "
                "label nothing reads is a row that can never be wrong: %r"
                % (bad_side,)))

    dead = [(g, s) for g, s, n in real["stale_exemptions"]
            if "does nothing" in n or "any more" in n]
    out.append(("e1", dead == [],
                "no exemption names a side that RUNS the gate, and none names a "
                "gate no side runs. The first stays green under a check that only "
                "asks about its own side; the second is a row that cannot be "
                "reported missing and therefore asserts nothing - the reason "
                "`prove-gates.py` had no row until a side named it: %r" % (dead,)))

    out.append(("e2", all(sides for _g, sides, _w in ABSENT_BY_DESIGN)
                and all(why.strip() for _g, _s, why in ABSENT_BY_DESIGN),
                "and every row carries at least one side and a REASON, because an "
                "exemption without one is a decision nobody can disagree with "
                "(%d rows)" % (len(ABSENT_BY_DESIGN),)))

    buf = io.StringIO()
    code = render({"missing": [("tools/x.mjs", "ci.yml", "why")],
                   "stale_exemptions": [], "counts": {"verify.sh": 3}}, stream=buf)
    out.append(("r0", code == 1 and "tools/x.mjs" in buf.getvalue()
                and "ci.yml" in buf.getvalue() and "why" in buf.getvalue(),
                "a gap exits 1 and names the gate, the SIDE it is missing from, and "
                "what to do about it - two sides made 'missing' unambiguous and "
                "three do not"))

    buf = io.StringIO()
    code = render({"missing": [], "stale_exemptions": [],
                   "counts": dict((l, 9) for l, _r in SIDES)}, stream=buf)
    out.append(("r1", code == 0 and "every side names" in buf.getvalue(),
                "and parity exits 0 saying so - 'nothing to report' must not read "
                "like 'nothing was compared'"))

    # --- the fourth side ------------------------------------------------------
    # F61: CLAUDE.md's list said of itself that it was one of the sides being
    # compared, and it was the one side nothing read. These drive `compare()` with
    # fixture sets, because what has to be shown is that a named side is really
    # compared - and four real files would put the readers under test instead.
    agreed = dict((label, set(["tools/alpha.mjs", "tools/beta.mjs"])) for label, _r in SIDES)
    same = compare(agreed, table=())
    out.append(("x0", same["missing"] == [] and same["stale_exemptions"] == [],
                "THE SECOND DIRECTION, and it looks vacuous on purpose: sides that "
                "name the same gates report nothing. It is the only case that fails "
                "if the comparison starts firing unconditionally, which is the other "
                "way x1 could be green for a bad reason: %r" % (same,)))

    short = dict(agreed)
    short["CLAUDE.md"] = set(["tools/alpha.mjs"])
    gap = compare(short, table=())
    out.append(("x1", [(g, s) for g, s, _n in gap["missing"]]
                == [("tools/beta.mjs", "CLAUDE.md")],
                "a gate the other sides name and CLAUDE.md does not is reported "
                "against CLAUDE.md BY NAME, and nothing else is reported. The whole "
                "of F61 is that this could not happen: the document telling readers "
                "it was compared was not in SIDES: %r" % (gap["missing"],)))

    lone = dict((label, set()) for label, _r in SIDES)
    lone["CLAUDE.md"] = set(["tools/lone.mjs"])
    others = tuple(l for l, _r in SIDES if l != "CLAUDE.md")
    unrowed = compare(lone, table=())
    rowed = compare(lone, table=(("tools/lone.mjs", others, "a reason"),))
    out.append(("x2", sorted(s for _g, s, _n in unrowed["missing"])
                == sorted(others)
                and rowed["missing"] == [] and rowed["stale_exemptions"] == [],
                "THE PAIR behind the two rows CLAUDE.md alone carries: a gate only "
                "it names is reported against every other side until a row says why, "
                "and the row then silences exactly those. Neither half was reachable "
                "before the fourth side, which is why `prove-gates.py` could not be "
                "given a row that asserted anything: %r vs %r"
                % (unrowed["missing"], rowed)))

    forgot = dict((label, set(["tools/alpha.mjs"])) for label, _r in SIDES)
    del forgot["CLAUDE.md"]
    unread = compare(forgot, table=())
    out.append(("x3", unread["missing"] == []
                and [(g, s) for g, s, _n in unread["stale_exemptions"]]
                == [("CLAUDE.md", "-")],
                "a caller that read no gate set for a side gets a NAMED failure "
                "instead of a verdict over the sides it did remember - substituting "
                "an empty set would report the unread side as absent from nothing "
                "and disagreeing with everything: %r" % (unread,)))

    doc = gates_in(os.path.join(REPO, CLAUDE_REL))
    out.append(("x4", doc is not None and "tools/sweep-selftests.py" in doc
                and "tools/redfirst.sh" not in doc,
                "REAL DOCUMENT, BOTH DIRECTIONS: CLAUDE.md's fences are read, and "
                "`tools/redfirst.sh` - which it names in PROSE and no side runs - is "
                "not. Several rows in the table rest on that scope, and a reader "
                "widened to the whole document would invent a gate every other side "
                "is missing: %r" % (sorted(doc or []),)))

    buf = io.StringIO()
    listed = render_list({"verify.sh": set(["tools/alpha.mjs"]), "ci.yml": set(),
                          "CONTRIBUTING.md": None,
                          "CLAUDE.md": set(["tools/alpha.mjs"])}, stream=buf)
    shown = buf.getvalue()
    out.append(("l0", listed == 1 and all(label in shown for label, _r in SIDES)
                and "x" in shown and "?" in shown,
                "--list heads a column per side, derived from SIDES. It was two "
                "hard-coded columns, so a side it did not know about was invisible "
                "in the one output that exists to show what each side invokes - and "
                "an unreadable side prints `?` rather than reading as a side that "
                "runs nothing: %r" % (shown,)))
    return out


def _selftest():
    rows = _cases()
    bad = [r for r in rows if not r[1]]
    for name, ok, why in rows:
        print("%s %s %s" % ("PASS" if ok else "FAIL", name, why))
    print("%s: %d/%d cases passed" % ("ALL PASS" if not bad else "FAILURES",
                                      len(rows) - len(bad), len(rows)))
    return 1 if bad else 0


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
