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

IT COMPARES THREE SIDES, and the third was itself a finding. `verify.sh` and `ci.yml`
were compared for a while and `CONTRIBUTING.md` was not - while saying of itself
"the individual commands stay documented below, because they are the definition and
the script is only a caller". A document that claims to be the definition owes every
gate; it carried seven of thirteen when it was finally read.

WHAT IT COMPARES, AND WHY THAT GRAIN. The set of REPO SCRIPTS and NAMED EXTERNAL
GATES each side invokes - not the full command lines. Arguments legitimately differ
(CI renders into a throwaway `/tmp` tree; `verify.sh` checks the committed
artifacts) and comparing them would produce noise that trains a reader to ignore
this. What may never differ is WHICH checks exist.

EXEMPTIONS ARE DECLARED, WITH A REASON, AND ARE THEMSELVES CHECKED. An entry in
either table below that names a gate neither side invokes any more is reported too -
otherwise the tables become a place where dead exemptions accumulate and the check
quietly stops covering what it claims.
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

# (label, path). The label is what a finding names and what a table row exempts, so
# it is short on purpose - a reader should not have to know the path to read the
# reason.
SIDES = (("verify.sh", VERIFY_REL), ("ci.yml", CI_REL),
         ("CONTRIBUTING.md", DOC_REL))

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

# THREE SIDES, and one table that can express all of them. `CI_ONLY` and
# `LOCAL_ONLY` were two tables for two sides, and adding CONTRIBUTING.md as a third
# would have needed a third - with a gate absent from two sides needing an entry in
# each. One row per gate, listing the sides it is legitimately absent FROM, and a
# reason a reader can disagree with.
#
# CONTRIBUTING.md is here because it says of itself: "The individual commands stay
# documented below, because they are the definition and the script is only a
# caller." A document that claims to be the definition owes every gate, and it
# carried seven of thirteen when somebody finally compared it.
# `tools/prove-gates.py` is deliberately NOT a row here, and the staleness rule is
# what said so: a gate no side names can never be reported missing, so a row
# declaring it absent from all three asserts nothing. It is minutes rather than
# seconds and mutates the tree while it runs; CLAUDE.md carries the command, and its
# own cases run in the sweep like every other tool's.
ABSENT_BY_DESIGN = (
    ("plugins/audit/scripts/demo/gen-demo-manifest.py", ("verify.sh", "CONTRIBUTING.md"),
     "builds a throwaway demo tree in /tmp to smoke the pipeline end to end; the "
     "local set checks the COMMITTED artifacts instead"),
    ("plugins/audit/scripts/demo/gen-demo-usage.py", ("verify.sh", "CONTRIBUTING.md"),
     "same throwaway demo tree"),
    ("plugins/audit/scripts/report/render-report.py", ("verify.sh", "CONTRIBUTING.md"),
     "rendered into /tmp as a smoke test; locally the equivalent claim is "
     "check-rendered-artifacts.py, which is stronger because it compares bytes"),
    ("plugins/audit/scripts/status/audit-doctor.py", ("verify.sh", "CONTRIBUTING.md"),
     "an end-to-end CLI smoke test over a fixture project"),
    ("plugins/audit/scripts/status/audit-status.py", ("verify.sh", "CONTRIBUTING.md"),
     "exercises --gate's exit codes, which need a fixture manifest per case"),
    ("plugins/audit/hooks/py-launch.sh", ("verify.sh", "CONTRIBUTING.md"),
     "the launcher is driven directly with fixture projects and with PATH unset, to "
     "prove the WIRING rather than decide(): the interpreter fallback, the stdin "
     "contract and the emitted JSON. Neither unsetting PATH nor feeding three "
     "fixture manifests is a thing to do to a developer's shell. The hooks it drives "
     "are ARGUMENTS to it, not paths, so this one entry covers all of them"),
    ("tools/affected.py", ("ci.yml", "CONTRIBUTING.md"),
     "a SELECTOR, not a gate: it narrows a local run and CI never narrows. Its own "
     "cases DO run on every side - inside the sweep, which covers tools/ - so what "
     "is exempt is the narrowing, not the checking of it"),
    ("tools/verify.sh", ("verify.sh", "ci.yml"),
     "the caller. CONTRIBUTING.md names it as the one command to run; it does not "
     "invoke itself, and CI runs the gates rather than the wrapper"),
)


# --- reading the two gate sets ------------------------------------------------
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


def _markdown_fence_lines(text):
    """The fenced blocks of a Markdown document - what it tells a reader to RUN.

    `_refs._runnable_text` already owns this question for the sweep-shape rule, and
    a second definition of "the runnable region of a document" is how two rules come
    to disagree about what a document says. Borrowed, not rewritten.
    """
    runnable, problem = _refs._runnable_text(DOC_REL, text)
    if problem is not None or runnable is None:
        return []
    return [ln for ln in runnable.split("\n")
            if ln.strip() and not ln.strip().startswith("#")]


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
        reader = _yaml_run_lines
    elif path.endswith(".md"):
        reader = _markdown_fence_lines
    else:
        reader = _shell_command_lines
    body = "\n".join(reader(text))
    for match in _SCRIPT_RE.finditer(body):
        found.add(match.group(0))
    for label, pattern in _EXTERNAL:
        if pattern.search(body):
            found.add(label)
    return found


def parity(repo=None):
    """{"missing": [(gate, side, note)], "stale_exemptions": [...], "counts": {}}.

    A gate must be named by EVERY side unless a row in `ABSENT_BY_DESIGN` says which
    sides it is legitimately absent from and why. Two tables for two sides became one
    table for three, because a gate absent from two sides would otherwise need an
    entry in each and the two could disagree.
    """
    repo = repo or REPO
    read = {}
    unreadable = []
    for label, rel in SIDES:
        got = gates_in(os.path.join(repo, rel))
        if got is None:
            unreadable.append((rel, label, "could not be read at all"))
        read[label] = got if got is not None else set()
    if unreadable:
        # NOT an empty verdict. A side nothing could read is not a side that agrees.
        return {"missing": [], "stale_exemptions": unreadable,
                "counts": dict((k, len(v)) for k, v in read.items())}

    exempt = {}
    for gate, sides, _why in ABSENT_BY_DESIGN:
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
    for gate, sides, _why in ABSENT_BY_DESIGN:
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
    return {"missing": sorted(missing), "stale_exemptions": sorted(stale),
            "counts": dict((k, len(v)) for k, v in read.items())}


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
        out.write("  all three sides name the same gates, and every declared "
                  "exemption is still real\n")
    return 1 if bad else 0


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    result = parity()
    if "--list" in argv:
        local = gates_in(os.path.join(REPO, VERIFY_REL)) or set()
        ci = gates_in(os.path.join(REPO, CI_REL)) or set()
        for gate in sorted(local | ci):
            sys.stdout.write("  %-3s %-3s %s\n"
                             % ("L" if gate in local else "-",
                                "C" if gate in ci else "-", gate))
    return render(result)


# --- selftest -----------------------------------------------------------------
def _cases():
    out = []
    real = parity()
    out.append(("p0", real["missing"] == [] and real["stale_exemptions"] == [],
                "THE LIVE CLAIM: all three descriptions of the gate set name the "
                "same gates and no exemption has gone stale (%s) - %r"
                % (", ".join("%s=%d" % (k, v)
                             for k, v in sorted(real["counts"].items())),
                   real["missing"] + real["stale_exemptions"])))

    out.append(("p1", all(real["counts"].get(label, 0) > 5 for label, _r in SIDES),
                "...and every side was really READ, so p0 is not three empty sets "
                "agreeing: %r" % (real["counts"],)))

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
        "Prose naming `node tools/ghost.mjs` at length.\n\n"
        "```bash\n# a comment about tools/commented-fixture\n"
        "node tools/real.mjs\n```\n\nMore prose about tools/after.mjs.\n")
    out.append(("c2", md == ["node tools/real.mjs"],
                "a Markdown document is mostly PROSE, and this one argues about its "
                "own gates for pages: only fenced blocks are commands. The reader "
                "comes from `_refs`, which already owns 'the runnable region of a "
                "document' for the sweep-shape rule - a second definition of that is "
                "how two rules come to disagree about what a document says: %r"
                % (md,)))

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
                "reported missing and therefore asserts nothing - which is why "
                "`prove-gates.py` is deliberately not a row: %r" % (dead,)))

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
    out.append(("r1", code == 0 and "all three sides" in buf.getvalue(),
                "and parity exits 0 saying so - 'nothing to report' must not read "
                "like 'nothing was compared'"))
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
