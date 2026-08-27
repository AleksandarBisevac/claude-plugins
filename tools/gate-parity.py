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

IT ALSO HOLDS THE RULES ABOUT THE RUNNERS THEMSELVES, because it is already the
thing that reads `verify.sh` for a living. Neither is a parity question; both are
properties of how the gates get run, and the alternative to keeping them here was a
second reader of the same files:

  * no runnable file under `tools/` may name a temp path a second concurrent run
    would share. `scratch_isolation()` has what went wrong when the paths were
    fixed, and why the scope is the directory rather than the runner alone.
  * every check the `--affected` selector NAMES must be one the runner can
    DISPATCH. `affected_dispatch()` asks that of the real pair, and it is the
    disagreement `parity()` cannot see: both files named the same gates while
    disagreeing about which of them run, so a step the runner had no arm for was
    dropped in silence and the summary went on calling the change covered.
"""
import ast
import io
import os
import re
import shutil
import subprocess
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
    # THE ONLY GATE HERE THAT LEAVES THE MACHINE, and the row says which side it is
    # absent from and why rather than leaving the absence to be read as an oversight.
    ("tools/check-release-published.py", ("ci.yml",),
     "it asks GitHub's API whether the newest published tag has a Release and "
     "whether Latest names it, and what that answers changes once per release. A "
     "workflow calling the API on every push would spend the repository's rate "
     "limit re-deriving a fact that cannot have moved, and would go red for a "
     "network it does not control on changes that have nothing to do with "
     "releasing. It belongs to the release set: verify.sh runs it under --release "
     "alone, and both documents name it in their Releasing sections. This row goes "
     "stale the day a workflow that runs at release time - a tag-triggered one - "
     "adopts it, which is the shape that would make it a CI gate honestly"),

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


# --- ...asked of every runnable file under `tools/` ----------------------------
# THE RULE WIDENS, AND THIS IS THE DECISION RATHER THAN A DESCRIPTION OF IT. It was
# written for `verify.sh` and read `verify.sh` alone, on the reasonable ground that
# the gate runner is where a crossed path turns into a green verdict for work nobody
# did. Two more tools had the same defect the day anybody looked: `prove-gates.py`
# read its verdict back through a fixed name in the system temp, and
# `check-rendered-artifacts.py` built one for a fixture. Neither is `verify.sh`, so a
# rule scoped to one file could not have said so - the scope WAS the defect, and
# fixing the two tools without widening it would leave the third to be found the same
# way. `tools/` is the boundary because that is where this repo keeps the machinery
# that several agents run at once against one checkout.
#
# WHAT DOES NOT WIDEN IS THE READER. The shell half matches TEXT, and `tools/` is
# full of legitimate temp-path STRINGS: a detector's fixture, an env value a case
# hands to a builder, a comment quoting the path that was repaired. A text reader
# over `.py` would convict every one of them, and a pattern loosened until they
# passed would stop catching the thing it exists for. So the Python half is an AST
# rule about an OPERATION - asking for the shared root and hanging a fixed name off
# it - and the strings are none of its business.

# Both spellings hand back a name in the shared system temp directory WITHOUT
# allocating it, so two runs on one machine get the same path.
# `mkdtemp`/`mkstemp`/`NamedTemporaryFile`/`TemporaryDirectory` each allocate a
# unique one, which is exactly why they are not here.
_TEMP_NAMERS = ("gettempdir", "mktemp")


def _called_name(node):
    """The attribute or bare name a `Call` invokes, or None for anything else."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _python_scratch_violations(source):
    """{"violations": [(where, problem)], "examined": n} for one module's source.

    `examined` counts the CALLS walked, for the reason the shell half counts
    runnable lines: a file that would not parse and a file with nothing to find must
    not produce the same answer. A parse failure is itself a finding here - a scan
    that quietly drops a file it could not read is a clean answer about a file
    nobody looked at.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return {"violations": [("<parse>", "does not parse, so nothing can be said "
                                           "about its scratch paths: %s" % (exc,))],
                "examined": 0}
    out = []
    walked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        walked += 1
        name = _called_name(node)
        if name in _TEMP_NAMERS:
            out.append(("line %d: %s()" % (node.lineno, name),
                        "names a path in the SHARED temp directory without "
                        "allocating it, so a second run on this machine gets the "
                        "same one - use mkdtemp/mkstemp, or take the directory "
                        "from a caller that already did"))
    return {"violations": out, "examined": walked}


# WHERE A FIXED PATH STAYS, WITH THE REASON AND THE REPAIR. (file, the exact
# spelling excused, why). A needle rather than a file, so a SECOND fixed path in an
# excused file is still reported - a file-wide exemption is how one recorded defect
# becomes cover for the next. Every row is checked in both directions below: a row
# whose spelling no longer violates anything is reported exactly as a violation is.
SCRATCH_EXEMPT = (
    ("tools/redfirst.sh", "${TMPDIR:-/tmp}/redfirst-gate.log",
     "the gate log, and the one fixed path here a repair cannot simply rename: "
     "`prove-gates.py` reads it back BY NAME after the script exits, so making it "
     "unique means the script emitting the path it chose - a contract change to "
     "the one file in this repo that mutates the working tree, and not a thing to "
     "do as a side effect of another change. What closes the crossing in the "
     "meantime is the CALLER: `prove-gates.py` points the temp root at a per-run "
     "directory before it shells out, so this spelling resolves somewhere "
     "different on every automated run and only two hand-runs started in the same "
     "second can still collide. Recorded rather than hidden, and it goes stale the "
     "day the script derives the path itself."),
)

_MIN_SCRATCH_REASON = 80   # a reason short enough to be a label is not a reason


def _sh_files(directory):
    """Sorted `(relname, path)` for every `.sh` under `directory`, recursively.

    Mirrors `_output.py_files()` deliberately: two walks that disagree about which
    files are in scope is how a file in a subdirectory comes to be checked by one
    rule and missed by another.
    """
    found = []
    for root, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for fname in filenames:
            if not fname.endswith(".sh"):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, directory).replace(os.sep, "/")
            found.append((rel, full))
    return sorted(found)


def _excused(rel, where):
    """The reason `rel`'s finding at `where` is declared, or None."""
    for path, needle, why in SCRATCH_EXEMPT:
        if path == rel and needle in where:
            return why
    return None


def scratch_isolation(repo=None):
    """The same question asked of `verify.sh` and of every tool beside it.

    Returns `{"violations", "excused", "dead_exemptions", "lines", "calls",
    "files"}`. THREE counters and not one, because the two readers narrow to
    nothing in different ways and a single number would let one of them fail
    behind the other: `lines` is what the shell reader saw, `calls` what the AST
    reader walked, `files` how many files were opened at all.
    """
    root = repo or REPO
    tools = os.path.join(root, "tools")
    out = []
    excused = []
    seen_where = []
    lines = calls = files = 0
    readers = ([(rel, path, _scratch_violations, "lines")
                for rel, path in _sh_files(tools)]
               + [(rel, path, _python_scratch_violations, "calls")
                  for rel, path in _output.py_files(tools)])
    for rel, path, reader, counter in readers:
        posix = "tools/" + rel
        try:
            with io.open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (IOError, OSError, UnicodeDecodeError) as exc:
            # Loud rather than empty: "I could not read this file" and "this file
            # is clean" are different answers, and returning nothing tells the
            # first as the second.
            out.append((posix, "could not be read: %s" % (exc,)))
            continue
        files += 1
        result = reader(text)
        if counter == "lines":
            lines += result["examined"]
        else:
            calls += result["examined"]
        for where, problem in result["violations"]:
            seen_where.append((posix, where))
            why = _excused(posix, where)
            if why is None:
                out.append((posix, "%s - %s" % (where, problem)))
            else:
                excused.append((posix, where, why))
    dead = [(p, needle) for p, needle, _why in SCRATCH_EXEMPT
            if not any(p == rel and needle in where for rel, where in seen_where)]
    return {"violations": out, "excused": excused, "dead_exemptions": sorted(dead),
            "lines": lines, "calls": calls, "files": files}


def reasonless_scratch_exemptions():
    """Rows whose reason is too short to be a decision anyone can disagree with."""
    return [(p, needle) for p, needle, why in SCRATCH_EXEMPT
            if not isinstance(why, str) or len(why.strip()) < _MIN_SCRATCH_REASON]


# --- does the runner run what the selector names? -----------------------------
# THE OTHER DISAGREEMENT BETWEEN TWO FILES THAT DESCRIBE ONE GATE SET, and the one
# `parity()` above cannot see: `--affected` narrows a local run to what the working
# tree needs, and `affected.py` chooses the checks while `verify.sh` dispatches
# them. The dispatcher matched three command prefixes; the selector emits a fourth
# for any change under `commands/`, `skills/` or `agents/`, so that step matched no
# arm, ran nothing, and the summary went on saying every selected check was green.
# A dropped gate and a passed gate spelled the same way, in the tool whose whole
# subject is what a narrowed run leaves out.
#
# So this asks the pair the only question that settles it: run the selector, and
# check the runner could dispatch every line it printed. Both halves are READ - the
# accepted prefixes off `verify.sh`, the commands off a real selector run - because
# a rule that restated either would go green while the file it describes moved.

# One probe per arm of the selector that appends a GATE. A suite selection emits
# `python3 <suite> --selftest`, which is the one shape nothing has ever got wrong;
# what has to be exercised here is every branch that appends something else.
AFFECTED_PROBES = (
    # The arm that was broken: plugin prose selects a validator that is neither
    # python nor node. Without this probe the check below is green over a command
    # set that never contained the failing shape.
    "plugins/audit/commands/status.md",
    # A report part: the JavaScript suites, the three report gates, the artifacts.
    "plugins/audit/scripts/ui/report/areas.js",
    # A panel part: the browser gate that runs a real server.
    "plugins/audit/scripts/ui/panel/boot.js",
    # A tool that is also a side of the gate set: its own cases, plus this check.
    "tools/gate-parity.py",
)

_ACCEPT_RE = re.compile(r"-e\s+'\^([^']+)'")


def dispatchable_prefixes(text):
    """The command prefixes `verify.sh`'s `--affected` runner will dispatch.

    READ OFF THE RUNNER, never listed here. A copy of that list is the same defect
    one file over: it would agree with the runner on the day it was written and
    stop agreeing without anybody being told.
    """
    for line in _shell_command_lines(text):
        if not line.startswith("grep -v "):
            continue
        found = _ACCEPT_RE.findall(line)
        if found:
            return found
    return []


def steps_in(output):
    """The command lines of a selector run - what the runner dispatches over.

    The selector prints its REASONS first and its commands after a `run:` line, and
    both halves are indented the same way, which is why a dispatcher reading the
    whole thing could not tell one from the other. The rule is the runner's: after
    `run:`, indented, and not the parenthesised sentence the selector uses to say it
    selected nothing.
    """
    out = []
    started = False
    for line in output.splitlines():
        if line.strip() == "run:":
            started = True
            continue
        if not started or not line.startswith("  ") or line.startswith("  ("):
            continue
        out.append(line[2:])
    return out


def affected_dispatch(repo=None):
    """{"undispatchable", "commands", "accepted", "problem"} for the real pair.

    `problem` is not None when the question could not be asked at all - the
    selector refusing to narrow, an unreadable runner, a run that printed no
    commands. Each of those produces an EMPTY undispatchable list, which is the
    exact shape of a clean answer, so the caller is told which one it got.
    """
    root = repo or REPO
    try:
        with io.open(os.path.join(root, VERIFY_REL), encoding="utf-8") as fh:
            accepted = dispatchable_prefixes(fh.read())
    except (IOError, OSError, UnicodeDecodeError) as exc:
        return {"undispatchable": [], "commands": [], "accepted": [],
                "problem": "the runner could not be read: %s" % (exc,)}
    if not accepted:
        return {"undispatchable": [], "commands": [], "accepted": [],
                "problem": "no accepted-prefix list could be read out of %s, so "
                           "nothing here knows what the runner dispatches"
                           % (VERIFY_REL,)}
    proc = subprocess.run(
        [sys.executable, os.path.join(root, "tools", "affected.py")]
        + list(AFFECTED_PROBES),
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        return {"undispatchable": [], "commands": [], "accepted": accepted,
                "problem": "the selector exited %d rather than narrowing, so it "
                           "named no checks to compare: %s"
                           % (proc.returncode, text.strip().splitlines()[:1])}
    commands = steps_in(text)
    if not commands:
        return {"undispatchable": [], "commands": [], "accepted": accepted,
                "problem": "the selector printed no commands for the probe set, "
                           "so an empty result here says nothing"}
    bad = [c for c in commands
           if not any(c.startswith(p) for p in accepted)]
    return {"undispatchable": bad, "commands": commands, "accepted": accepted,
            "problem": None}


# --- the sweep's isolation, and every document that describes it --------------
# THE THIRD RULE HERE THAT IS NOT A PARITY QUESTION, and it is in this file for the
# reason the two above are: this is already the thing that reads a RUNNER for a
# living, and what is being compared is a property of how the gates get run rather
# than of which gates exist. `tools/sweep-selftests.py` points a child's environment
# away from the machine it runs on, and three documents describe that surface -
# `CLAUDE.md`, `CONTRIBUTING.md`, and the docstring `_harness.fixture_root()` keeps
# beside the fixture helper it hands out. Nothing compared any of the three with the
# runner, so every correction was a hand edit that went stale the next time the
# surface grew - and it grew more than once, leaving each document behind by a
# different amount. A rule is worth more than a fourth correction.
#
# IT READS THE RUNNER'S CONSTANTS, AND THAT IS THE ONE THING THE REST OF THIS FILE
# DOES NOT DO. Everything above compares TEXT with TEXT. A family of environment
# variables is a tuple in a module, and a rule that re-spelled that tuple here would
# be a fourth description of the thing it is checking rather than a check on the
# other three.
#
# WHY THE GRAIN IS A FAMILY AND NOT A VARIABLE. The runner pins every name a lookup
# reads - `TMP` and `TEMP` beside `TMPDIR`, the `XDG_*` roots and the windows pair
# beside `HOME` - because a variable left unpinned is a lookup that finds the shared
# directory again. A document that spelled all of them would BE the module. What a
# document owes is not to leave a whole family out: naming one member names the
# family, and naming none of them is the drift this reports.
#
# AND THE RUNNER IS CHECKED AGAINST ITSELF, which is the half a prose rule cannot
# reach. The watched directories are zipped against their labels, so a directory
# added to the walk without a label beside it is DROPPED by `zip` - silently, and
# into exactly the shape this repo keeps finding: a check that grew and went on
# reporting a clean answer about the part nobody wired up. The sentinel plantings
# are counted for the same reason: a watched directory with no file planted in it
# can only ever report a stray, never a deletion.
SWEEP_REL = os.path.join("tools", "sweep-selftests.py")

# (label, path). The label is what a finding names, as in SIDES above.
ISOLATION_SIDES = (("CLAUDE.md", CLAUDE_REL),
                   ("CONTRIBUTING.md", DOC_REL),
                   ("tests/_harness.py",
                    os.path.join("plugins", "audit", "tests", "_harness.py")))


def _module_constants(tree):
    """{NAME: value} for every module-level `NAME = <literal>` that evaluates.

    Module level only, and literals only. A family of environment names is written
    as a tuple beside the code that spreads it, which is the whole reason this rule
    can read the runner instead of restating it.
    """
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            found[target.id] = ast.literal_eval(node.value)
        except (ValueError, SyntaxError, TypeError):
            continue
    return found


def _string_tuple(value):
    """`value` as a tuple of strings, or None when it is not a family of names."""
    if not isinstance(value, (tuple, list)) or not value:
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)


def _slice_expr(node):
    """The expression inside a subscript, in either spelling this floor allows.

    3.8 wraps it in an `Index` node and 3.9 dropped the wrapper. Read by class NAME
    rather than by `isinstance`, because the wrapper class is on its own deprecation
    path and a rule that imported it would be a version test in a lint.
    """
    inner = node.slice
    if inner.__class__.__name__ == "Index":
        return getattr(inner, "value", None)
    return inner


def _env_assign(node, env_name):
    """(key expression, value name) for `env[<key>] = <name>`, else (None, None)."""
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return None, None
    target, value = node.targets[0], node.value
    if not isinstance(target, ast.Subscript) or not isinstance(value, ast.Name):
        return None, None
    if not isinstance(target.value, ast.Name) or target.value.id != env_name:
        return None, None
    return _slice_expr(target), value.id


def _env_keys_of(node, consts):
    """Every environment name a helper writes into the mapping it builds.

    Two shapes, because the windows pair cannot be listed with the rest: the
    families the helper SPREADS arrive as module constants it reads by name, and the
    names it DERIVES arrive as literal keys it stores. Reading only the first would
    miss exactly the pair whose absence made `HOME` alone look sufficient.
    """
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            members = _string_tuple(consts.get(child.id))
            if members:
                names |= set(members)
        elif isinstance(child, ast.Subscript) and isinstance(child.ctx, ast.Store):
            key = _slice_expr(child)
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.add(key.value)
    return names


def pinned_env_groups(source, entry="run_one", env_name="env"):
    """({directory: (env names,)}, problem) for the runner - one of the two is empty.

    GROUPED BY THE DIRECTORY THE VARIABLE POINTS AT, and that grouping is what makes
    the rule about isolation rather than about environment variables. The child is
    handed an encoding as well, and an encoding is not a place; only a name set to a
    directory this runner ALLOCATED counts, which is a distinction read off the code
    rather than a list of names to skip.

    A source that will not parse, or that carries no `entry`, or that pins nothing,
    is REPORTED. Each of those produces an empty group map, which is the exact shape
    of a runner that isolates nothing, and a caller told the two apart is the whole
    difference between this rule and a green answer about a file nobody read.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return {}, "does not parse, so nothing can be compared: %s" % (exc,)
    consts = _module_constants(tree)
    fns = dict((n.name, n) for n in tree.body if isinstance(n, ast.FunctionDef))
    fn = fns.get(entry)
    if fn is None:
        return {}, "carries no module-level `def %s`, so what it pins per child " \
                   "cannot be read" % (entry,)
    dirs = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and _called_name(node.value) == "mkdtemp"):
            dirs |= set(t.id for t in node.targets if isinstance(t, ast.Name))
    if not dirs:
        return {}, "allocates no scratch directory in `%s`, so nothing there is " \
                   "pinned at one" % (entry,)
    groups = {}
    for node in ast.walk(fn):
        if (isinstance(node, ast.For) and isinstance(node.iter, ast.Name)
                and isinstance(node.target, ast.Name)):
            members = _string_tuple(consts.get(node.iter.id))
            if members is None:
                continue
            for child in ast.walk(node):
                key, held = _env_assign(child, env_name)
                if (held in dirs and isinstance(key, ast.Name)
                        and key.id == node.target.id):
                    groups.setdefault(held, set()).update(members)
            continue
        key, held = _env_assign(node, env_name)
        if (held in dirs and isinstance(key, ast.Constant)
                and isinstance(key.value, str)):
            groups.setdefault(held, set()).add(key.value)
            continue
        # `env.update(<helper>(<dir>))` - the family that cannot be a literal list,
        # because two of its names are derived from the path by splitting it.
        if (isinstance(node, ast.Call) and _called_name(node) == "update"
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == env_name and len(node.args) == 1
                and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Name)):
            inner = node.args[0]
            helper = fns.get(inner.func.id)
            held = [a.id for a in inner.args
                    if isinstance(a, ast.Name) and a.id in dirs]
            if helper is not None and held:
                groups.setdefault(held[0], set()).update(
                    _env_keys_of(helper, consts))
    if not groups:
        return {}, "sets no environment variable to a directory it allocated, so " \
                   "there is no isolation here for a document to describe"
    return dict((k, tuple(sorted(v))) for k, v in groups.items()), None


def watched_channels(source, entry="run_one", reader="child_debris"):
    """{"labels", "read", "planted", "problem"} - the runner against itself.

    `labels` is how many channels the finding vocabulary has, `read` how many
    directories the walk actually visits, `planted` how many get a file put in them
    before the run. All three are one number in a correct runner, and each pair
    fails differently: a directory with no label is dropped by `zip` and reported
    about by nothing, and a directory with no planted file can report a stray but
    never a deletion.
    """
    out = {"labels": None, "read": None, "planted": None, "problem": None}
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        out["problem"] = "does not parse, so nothing can be counted: %s" % (exc,)
        return out
    consts = _module_constants(tree)
    fns = dict((n.name, n) for n in tree.body if isinstance(n, ast.FunctionDef))
    walk = fns.get(reader)
    if walk is None:
        out["problem"] = "carries no module-level `def %s`" % (reader,)
        return out
    for node in ast.walk(walk):
        if not isinstance(node, ast.Call) or _called_name(node) != "zip":
            continue
        labelled = [a for a in node.args
                    if isinstance(a, ast.Name) and _string_tuple(consts.get(a.id))]
        roots = [a for a in node.args if isinstance(a, ast.Tuple)]
        if labelled and roots:
            out["labels"] = len(_string_tuple(consts[labelled[0].id]))
            out["read"] = len(roots[0].elts)
            break
    if out["labels"] is None:
        out["problem"] = ("`%s` no longer walks a label family against a tuple of "
                          "roots, so what it watches cannot be counted" % (reader,))
        return out
    run = fns.get(entry)
    if run is None:
        out["problem"] = "carries no module-level `def %s`" % (entry,)
        return out
    for node in ast.walk(run):
        if not isinstance(node, ast.For) or not isinstance(node.iter, ast.Tuple):
            continue
        if any(isinstance(c, ast.Call) and _called_name(c) == "open"
               for c in ast.walk(node)):
            out["planted"] = len(node.iter.elts)
            break
    if out["planted"] is None:
        out["problem"] = ("`%s` plants nothing before the run, so a directory a "
                          "suite DELETED from reads exactly like a clean one"
                          % (entry,))
    return out


def unnamed_groups(text, groups):
    """The families `text` names no member of, sorted.

    A PURE FUNCTION OVER ONE DOCUMENT AND THE DERIVED FAMILIES, so both directions
    of the prose rule are driven from strings rather than from documents written
    into a temp directory - and so the case that reads the real tree is one call
    rather than a fixture encoding the same assumption the rule does.
    """
    return [held for held in sorted(groups)
            if not any(name in text for name in groups[held])]


def isolation_drift(repo=None):
    """{"prose", "runner", "groups", "watched", "sides", "problem"} for the tree.

    `problem` is not None when the runner could not be read at all - which produces
    an empty finding list, the same shape a tree in perfect agreement produces, and
    the caller is told which of the two it got.
    """
    root = repo or REPO
    try:
        with io.open(os.path.join(root, SWEEP_REL), encoding="utf-8") as fh:
            source = fh.read()
    except (IOError, OSError, UnicodeDecodeError) as exc:
        return {"prose": [], "runner": [], "groups": {}, "watched": {}, "sides": 0,
                "problem": "%s could not be read: %s" % (SWEEP_REL, exc)}
    groups, problem = pinned_env_groups(source)
    if problem is not None:
        return {"prose": [], "runner": [], "groups": {}, "watched": {}, "sides": 0,
                "problem": "%s %s" % (SWEEP_REL, problem)}
    watched = watched_channels(source)
    runner = []
    if watched["problem"] is not None:
        runner.append((SWEEP_REL, "-", watched["problem"]))
    else:
        if watched["labels"] != watched["read"]:
            runner.append((SWEEP_REL, "-",
                           "walks %d watched directory/ies against %d channel "
                           "label(s), so `zip` drops the difference and nothing "
                           "reports what happened in it"
                           % (watched["read"], watched["labels"])))
        if watched["planted"] != watched["read"]:
            runner.append((SWEEP_REL, "-",
                           "walks %d watched directory/ies and plants a file in "
                           "%d of them, so the rest can report a stray but never "
                           "a deletion"
                           % (watched["read"], watched["planted"])))
    prose = []
    sides = 0
    for label, rel in ISOLATION_SIDES:
        try:
            with io.open(os.path.join(root, rel), encoding="utf-8") as fh:
                text = fh.read()
        except (IOError, OSError, UnicodeDecodeError) as exc:
            prose.append((label, "-", "could not be read: %s" % (exc,)))
            continue
        sides += 1
        for held in unnamed_groups(text, groups):
            names = groups[held]
            prose.append((label, held,
                          "the sweep points %s at a scratch directory of its "
                          "own per child, and this document names no member "
                          "of that family - so a reader of it cannot tell "
                          "the pin exists"
                          % (", ".join("`%s`" % (n,) for n in names),)))
    return {"prose": prose, "runner": runner, "groups": groups, "watched": watched,
            "sides": sides, "problem": None}


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
def _cases(check):
    real = parity()
    check("p0 THE LIVE CLAIM: every description of the gate set names the "
          "same gates and no exemption has gone stale (%s) - %r"
          % (", ".join("%s=%d" % (k, v)
                       for k, v in sorted(real["counts"].items())),
             real["missing"] + real["stale_exemptions"]),
          real["missing"] == [] and real["stale_exemptions"] == [])

    check("p1 ...and every side was really READ, so p0 is not a row of empty "
          "sets agreeing: every side clears a floor of %d, the larger of the "
          "absolute term and the largest side's share. It is also the case a "
          "floor set too HIGH fails - the sides legitimately differ in size, "
          "so a floor AT the largest count would report the smallest side as "
          "unread: %r / %r"
          % (read_floor(real["counts"]), real["counts"],
             underread_sides(real["counts"])),
          underread_sides(real["counts"]) == [])

    # THE FIXTURE VALUE IS THE OLD FLOOR'S BLIND SPOT (F69), which is the only
    # reason this case is worth anything: `p1` compared each count with a fixed
    # number that the rotted side below CLEARS. Both versions score this fixture,
    # and they disagree about it.
    rotted = dict((label, 14) for label, _r in SIDES)
    rotted["CLAUDE.md"] = 6
    check("p2 a document that rotted while the other sides stood IS reported, "
          "by name and with both numbers - the count it named and the floor "
          "the rest of the tree sets: %r" % (underread_sides(rotted),),
          underread_sides(rotted) == [("CLAUDE.md", 6, 7)])

    empty = dict((label, 0) for label, _r in SIDES)
    check("p3 ...and a run where NOTHING was read reports every side, at the "
          "ABSOLUTE floor. This is the direction the derived term cannot "
          "cover on its own - a fraction of nothing is nothing, and a floor "
          "of 0 would let the emptiest possible read pass: %r"
          % (underread_sides(empty),),
          underread_sides(empty)
          == [(label, 0, FLOOR_MINIMUM) for label, _r in SIDES])

    live = scratch_isolation()
    check("sc0 THE LIVE CLAIM, now over every runnable file under tools/ and not "
          "the runner alone: nothing names a temp path a second run would share, "
          "read across %d file(s), %d runnable shell line(s) and %d python "
          "call(s). THREE counters because there are two readers, and one number "
          "would let either of them narrow to nothing behind the other: %r"
          % (live["files"], live["lines"], live["calls"], live["violations"]),
          live["violations"] == [] and live["files"] > 0
          and live["lines"] > 0 and live["calls"] > 0)

    fixed = _scratch_violations("run() {\n  cmd >/tmp/verify-step.log 2>&1\n}\n")
    check("sc1 ...and a fixed path IS reported, which is what tells sc0 apart "
          "from a rule that cannot fire at all: %r" % (fixed["violations"],),
          len(fixed["violations"]) == 1)

    derived = _scratch_violations(
        'WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/verify-XXXXXX")\n')
    check("sc2 the ONE derivation may name the root - deriving it is what makes "
          "the path unique - and the line was READ rather than skipped, so "
          "this is an exemption and not a blind spot: %r" % (derived,),
          derived["violations"] == [] and derived["examined"] == 1)

    prose = _scratch_violations("# it used to write /tmp/verify-step.log\n")
    check("sc3 a comment naming the old path is history, not a command - and "
          "`examined` says 0 instead of letting the empty result read as "
          "clean, which is the half sc0 pairs with: %r" % (prose,),
          prose["violations"] == [] and prose["examined"] == 0)

    # --- the python half of the same rule, and the reason it is not the shell one
    # THE PAIR. Two fixtures differing only in whether the shared root is ASKED FOR
    # or ALLOCATED. Asserting the clean one alone would pass against a reader that
    # found nothing either way, and asserting the dirty one alone would pass
    # against a reader that convicted every call it walked.
    _py_fixed = _python_scratch_violations(
        "import tempfile, os\n"
        "log = os.path.join(tempfile.gettempdir(), 'probe-gate.log')\n")
    _py_unique = _python_scratch_violations(
        "import tempfile\n"
        "work = tempfile.mkdtemp(prefix='probe-')\n")
    check("sp0 asking for the SHARED temp root is the finding, and allocating a "
          "unique directory under it is not - the two fixtures differ in nothing "
          "else, so a reader that answered the same way to both would fail here "
          "in one direction or the other: %r vs %r"
          % (_py_fixed["violations"], _py_unique["violations"]),
          len(_py_fixed["violations"]) == 1
          and "line 2" in _py_fixed["violations"][0][0]
          and _py_unique["violations"] == []
          and _py_unique["examined"] > 0)
    # `mktemp` is the other half of the same operation - a NAME in the shared root,
    # handed back without being allocated - and a rule that knew only the first
    # spelling would let the next tool reach for it.
    _py_mktemp = _python_scratch_violations("import tempfile\n"
                                            "p = tempfile.mktemp()\n")
    check("sp1 ...and both spellings of it are known, so the rule is about the "
          "operation rather than about one function name: %r"
          % (_py_mktemp["violations"],),
          len(_py_mktemp["violations"]) == 1)
    # THE WIDENING'S OWN JUSTIFICATION, ASSERTED. The shell reader matches text, and
    # `tools/` is full of legitimate temp-path strings - a detector's fixture, an
    # env value handed to a builder. This is the case that fails if the python half
    # is ever "simplified" into the text one, which would convict every one of them.
    _py_strings = _python_scratch_violations(
        "FIXTURE = '/tmp/x'\n"
        "ENVS = {'TMPDIR': '/tmp/probe'}\n"
        "def fixture_env(home):\n    return dict(HOME=home)\n"
        "ENV = fixture_env('/tmp/x')\n")
    check("sp2 a temp path that is DATA - a fixture value, an env a case builds - "
          "is not an operation and is not reported. The shell reader would "
          "convict all three lines, which is why this half reads the AST: %r"
          % (_py_strings,),
          _py_strings["violations"] == [] and _py_strings["examined"] > 0)
    _py_broken = _python_scratch_violations("def _probe(:\n")
    check("sp3 a file that will not parse is REPORTED, never skipped: a scan that "
          "quietly drops a file it could not read is a clean answer about a file "
          "nobody looked at",
          len(_py_broken["violations"]) == 1
          and _py_broken["violations"][0][0] == "<parse>"
          and _py_broken["examined"] == 0)

    # --- the exemption table, both directions ---------------------------------
    check("se0 every declared exemption still names a real finding - a row whose "
          "spelling stopped violating anything is a sentence about a state that "
          "has passed, and it stays green forever under a check that only asks "
          "whether the rule fired: %r" % (live["dead_exemptions"],),
          live["dead_exemptions"] == [])
    check("se1 ...and the rows that ARE live are reported as excused rather than "
          "dropped, so a reader of a clean run can see what it did not cover "
          "(%d row(s)): %r"
          % (len(SCRATCH_EXEMPT), [(p, w) for p, w, _why in live["excused"]]),
          len(live["excused"]) > 0
          and all(_why.strip() for _p, _w, _why in live["excused"]))
    check("se2 ...and every row carries a reason a reader can disagree with, "
          "because an exemption without one is a decision nobody can argue "
          "against: %r" % (reasonless_scratch_exemptions(),),
          reasonless_scratch_exemptions() == [])
    # THE NEEDLE, NOT THE FILE. A row excuses one spelling; a second fixed path in
    # the same file is still reported. This is the case that fails if somebody
    # widens a row to a filename to get a new finding past se0.
    _one_excused = _excused("tools/redfirst.sh",
                            'log="${TMPDIR:-/tmp}/redfirst-gate.log"')
    _not_excused = _excused("tools/redfirst.sh",
                            'other="${TMPDIR:-/tmp}/redfirst-other.log"')
    check("se3 an exemption excuses one SPELLING and not a file, so a second "
          "fixed path in an excused file is still a finding: %r vs %r"
          % (_one_excused is not None, _not_excused),
          _one_excused is not None and _not_excused is None)

    # --- the runner really runs what the selector names -----------------------
    # F: `--affected` narrowed a run by dropping a gate it could not dispatch and
    # then reported every selected check green. `parity()` above cannot see it -
    # both files name the same gates; they disagree about which of them RUN.
    _ad = affected_dispatch()
    check("ad0 THE LIVE CLAIM: every command the selector prints for the probe "
          "set is one the runner can dispatch, over %d command(s) against %d "
          "accepted prefix(es) read off the runner itself - and a run that could "
          "not ask the question says so instead of coming back empty: %r / %r"
          % (len(_ad["commands"]), len(_ad["accepted"]), _ad["problem"],
             _ad["undispatchable"]),
          _ad["problem"] is None and _ad["undispatchable"] == [])
    # THE FIXTURE-VALUE CASE, and without it ad0 is green over a command set that
    # never contains the failing shape. `claude plugin validate` is what the
    # dispatcher dropped, and a probe set that stopped emitting it would leave ad0
    # asserting nothing while still passing.
    check("ad1 ...and the probe set really does reach the arm that broke: the "
          "command the dispatcher used to drop is among the ones it emitted, so "
          "ad0 is a claim about that shape rather than about python and node: %r"
          % (_ad["commands"],),
          any(c.startswith("claude plugin validate") for c in _ad["commands"]))
    check("ad2 the accepted prefixes are READ OFF the runner and there is more "
          "than one, so this cannot be a list that agreed on the day it was "
          "written: %r" % (_ad["accepted"],),
          len(_ad["accepted"]) >= 2
          and "python3 " in _ad["accepted"])
    # `ruff check ...` is a real gate of this repo that `--affected` never selects,
    # so it is a command the runner legitimately cannot dispatch - which makes it
    # the honest half of this pair rather than an invented string.
    _made_up = [c for c in ["node tools/x.mjs", "ruff check plugins/audit tools"]
                if not any(c.startswith(p) for p in _ad["accepted"])]
    check("ad3 ...and those prefixes DO refuse something: a command outside them "
          "is rejected while one inside is not, which is the pair that tells ad0 "
          "apart from a comparison nothing can fail: %r" % (_made_up,),
          _made_up == ["ruff check plugins/audit tools"])
    # THE INVENTED TOOL NAMES CARRY THE JAVASCRIPT MODULE EXTENSION, for the reason
    # the fixtures further up this file do: `_refs.tool_basename_drift()` holds that
    # a `.py` basename written anywhere under `tools/` must name a file that exists,
    # and a fixture nobody creates is exactly what a stale reference looks like.
    _steps = steps_in("affected: 1 changed path(s) against HEAD\n"
                      "  tools/x.mjs - a reason indented like a command\n"
                      "\nrun:\n"
                      "  node tools/x.mjs --check\n"
                      "  claude plugin validate plugins/audit\n")
    check("ad4 the step reader takes ONLY what follows `run:` - the selector's "
          "reasons are indented exactly like its commands, which is the "
          "ambiguity that made a catch-all arm impossible and the silent skip "
          "the only shape available: %r" % (_steps,),
          _steps == ["node tools/x.mjs --check",
                     "claude plugin validate plugins/audit"])
    check("ad5 ...and the sentence the selector prints when it selected NOTHING "
          "is not read as a command, while a run with no `run:` section at all "
          "yields nothing rather than the whole document",
          steps_in("run:\n  (nothing - no check covers what changed)\n") == []
          and steps_in("affected: FULL SET required\n"
                       "  x - UNRECOGNISED\n") == [])
    check("ad6 a runner nothing could read is a NAMED problem and not an empty "
          "undispatchable list - the two spell the same way otherwise, and one "
          "of them means the check did not run",
          affected_dispatch(os.path.join(REPO, "no-such-repo-dir"))["problem"]
          is not None)

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
    check("c0 a commented invocation is NOT an invocation, and a trailing "
          "comment is cut - all three files discuss their own gates at "
          "length, so without this every mention would register: %r" % (body,),
          body == ["ruff check x"])

    yml = _yaml_run_lines(
        "      - name: something about tools/ghost.mjs\n"
        "        shell: bash\n"
        "        run: node tools/real.mjs\n"
        "      - name: block form\n"
        "        run: |\n"
        "          # a comment about tools/commented-fixture\n"
        "          python tools/block-fixture\n"
        "      - name: after the block, tools/after.mjs\n")
    check("c1 a workflow is mostly KEYS: only `run:` values and their block "
          "scalars are commands, so renaming a step cannot change the gate "
          "set. Written as 'every non-comment line' first, and a step name "
          "mentioning verify.sh registered as an invocation of it: %r"
          % (yml,),
          yml == ["node tools/real.mjs", "python tools/block-fixture"])

    md = _markdown_fence_lines(
        DOC_REL,
        "Prose naming `node tools/ghost.mjs` at length.\n\n"
        "```bash\n# a comment about tools/commented-fixture\n"
        "node tools/real.mjs  # a trailing note about tools/trailing-fixture\n"
        "```\n\nMore prose about tools/after.mjs.\n")
    check("c2 a Markdown document is mostly PROSE, and this one argues about its "
          "own gates for pages: only fenced blocks are commands. The reader "
          "comes from `_refs`, which already owns 'the runnable region of a "
          "document' for the sweep-shape rule - a second definition of that is "
          "how two rules come to disagree about what a document says. The "
          "TRAILING note is cut as well, which it was not: an annotated command "
          "in a fence named a gate the identical annotation in verify.sh did "
          "not, and a list a reader is meant to annotate is what this side is: "
          "%r" % (md,),
          md == ["node tools/real.mjs"])

    tmp = _output.REPO_ROOT  # any real directory; the point is the missing file
    res = parity(os.path.join(tmp, "no-such-repo-dir"))
    check("m0 every unreadable side is a NAMED failure, not perfect parity - "
          "empty sets for all three would report three missing files as "
          "agreement: %r" % (res["stale_exemptions"],),
          len(res["stale_exemptions"]) == len(SIDES)
          and all("could not be read" in n
                  for _g, _s, n in res["stale_exemptions"]))

    seen = gates_in(os.path.join(REPO, VERIFY_REL))
    check("g0 the extractor finds an external gate, a linter and a repo script "
          "in the real verify.sh - three different shapes, so a pattern that "
          "silently stopped matching one of them fails here",
          "npx vitest" in seen and "ruff" in seen
          and "tools/sweep-selftests.py" in seen)

    fx = tempfile.mkdtemp(prefix="gate-parity-")
    commented = os.path.join(fx, "commented.sh")
    running = os.path.join(fx, "running.sh")
    io.open(commented, "w", encoding="utf-8").write(
        "# node tools/ghost.mjs is what we used to run\n")
    io.open(running, "w", encoding="utf-8").write("node tools/ghost.mjs\n")
    seen_c, seen_r = gates_in(commented), gates_in(running)
    shutil.rmtree(fx, ignore_errors=True)
    check("g1 THE PAIR: two fixtures differing ONLY in whether the mention is a "
          "comment give OPPOSITE answers, so the comment rule is doing work "
          "rather than the extractor finding nothing either way. Asserting "
          "the empty one alone would pass on a version that always returned "
          "an empty set (%r vs %r)" % (seen_c, seen_r),
          seen_c == set() and seen_r == set(["tools/ghost.mjs"]))

    labels = set(label for label, _r in SIDES)
    bad_side = [(g, s) for g, sides, _w in ABSENT_BY_DESIGN for s in sides
                if s not in labels]
    check("e0 every exemption names a side that EXISTS - a row pointing at a "
          "label nothing reads is a row that can never be wrong: %r"
          % (bad_side,),
          bad_side == [])

    dead = [(g, s) for g, s, n in real["stale_exemptions"]
            if "does nothing" in n or "any more" in n]
    check("e1 no exemption names a side that RUNS the gate, and none names a "
          "gate no side runs. The first stays green under a check that only "
          "asks about its own side; the second is a row that cannot be "
          "reported missing and therefore asserts nothing - the reason "
          "`prove-gates.py` had no row until a side named it: %r" % (dead,),
          dead == [])

    check("e2 and every row carries at least one side and a REASON, because an "
          "exemption without one is a decision nobody can disagree with "
          "(%d rows)" % (len(ABSENT_BY_DESIGN),),
          all(sides for _g, sides, _w in ABSENT_BY_DESIGN)
          and all(why.strip() for _g, _s, why in ABSENT_BY_DESIGN))

    buf = io.StringIO()
    code = render({"missing": [("tools/x.mjs", "ci.yml", "why")],
                   "stale_exemptions": [], "counts": {"verify.sh": 3}}, stream=buf)
    check("r0 a gap exits 1 and names the gate, the SIDE it is missing from, and "
          "what to do about it - two sides made 'missing' unambiguous and "
          "three do not",
          code == 1 and "tools/x.mjs" in buf.getvalue()
          and "ci.yml" in buf.getvalue() and "why" in buf.getvalue())

    buf = io.StringIO()
    code = render({"missing": [], "stale_exemptions": [],
                   "counts": dict((l, 9) for l, _r in SIDES)}, stream=buf)
    check("r1 and parity exits 0 saying so - 'nothing to report' must not read "
          "like 'nothing was compared'",
          code == 0 and "every side names" in buf.getvalue())

    # --- the fourth side ------------------------------------------------------
    # F61: CLAUDE.md's list said of itself that it was one of the sides being
    # compared, and it was the one side nothing read. These drive `compare()` with
    # fixture sets, because what has to be shown is that a named side is really
    # compared - and four real files would put the readers under test instead.
    agreed = dict((label, set(["tools/alpha.mjs", "tools/beta.mjs"])) for label, _r in SIDES)
    same = compare(agreed, table=())
    check("x0 THE SECOND DIRECTION, and it looks vacuous on purpose: sides that "
          "name the same gates report nothing. It is the only case that fails "
          "if the comparison starts firing unconditionally, which is the other "
          "way x1 could be green for a bad reason: %r" % (same,),
          same["missing"] == [] and same["stale_exemptions"] == [])

    short = dict(agreed)
    short["CLAUDE.md"] = set(["tools/alpha.mjs"])
    gap = compare(short, table=())
    check("x1 a gate the other sides name and CLAUDE.md does not is reported "
          "against CLAUDE.md BY NAME, and nothing else is reported. The whole "
          "of F61 is that this could not happen: the document telling readers "
          "it was compared was not in SIDES: %r" % (gap["missing"],),
          [(g, s) for g, s, _n in gap["missing"]]
          == [("tools/beta.mjs", "CLAUDE.md")])

    lone = dict((label, set()) for label, _r in SIDES)
    lone["CLAUDE.md"] = set(["tools/lone.mjs"])
    others = tuple(l for l, _r in SIDES if l != "CLAUDE.md")
    unrowed = compare(lone, table=())
    rowed = compare(lone, table=(("tools/lone.mjs", others, "a reason"),))
    check("x2 THE PAIR behind the two rows CLAUDE.md alone carries: a gate only "
          "it names is reported against every other side until a row says why, "
          "and the row then silences exactly those. Neither half was reachable "
          "before the fourth side, which is why `prove-gates.py` could not be "
          "given a row that asserted anything: %r vs %r"
          % (unrowed["missing"], rowed),
          sorted(s for _g, s, _n in unrowed["missing"])
          == sorted(others)
          and rowed["missing"] == [] and rowed["stale_exemptions"] == [])

    forgot = dict((label, set(["tools/alpha.mjs"])) for label, _r in SIDES)
    del forgot["CLAUDE.md"]
    unread = compare(forgot, table=())
    check("x3 a caller that read no gate set for a side gets a NAMED failure "
          "instead of a verdict over the sides it did remember - substituting "
          "an empty set would report the unread side as absent from nothing "
          "and disagreeing with everything: %r" % (unread,),
          unread["missing"] == []
          and [(g, s) for g, s, _n in unread["stale_exemptions"]]
          == [("CLAUDE.md", "-")])

    doc = gates_in(os.path.join(REPO, CLAUDE_REL))
    check("x4 REAL DOCUMENT, BOTH DIRECTIONS: CLAUDE.md's fences are read, and "
          "`tools/redfirst.sh` - which it names in PROSE and no side runs - is "
          "not. Several rows in the table rest on that scope, and a reader "
          "widened to the whole document would invent a gate every other side "
          "is missing: %r" % (sorted(doc or []),),
          doc is not None and "tools/sweep-selftests.py" in doc
          and "tools/redfirst.sh" not in doc)

    # THE ANNOTATION IS NOT PART OF THE GATE SET, and this says so about the REAL
    # document rather than about a fixture. `c2` proves the trailing note is cut
    # from a Markdown fence; what nobody could point at is that the annotation
    # beside CLAUDE.md's own sweep line is therefore free text - so a comment
    # that had gone out of date was left standing through a whole release on the
    # grounds that correcting it might move this check. It cannot. The comment is
    # cut before `_SCRIPT_RE` ever sees the line, exactly as `_shell_command_lines`
    # cuts verify.sh's, and a Markdown side that read its annotations would let a
    # gate be DECLARED by mentioning it - which is the opposite of comparing what
    # each side RUNS, and would make this the fourth description of the gate set
    # rather than a check on the other three.
    _cm_text = io.open(os.path.join(REPO, CLAUDE_REL), encoding="utf-8").read()
    _cm_run = [ln for ln in _cm_text.split("\n")
               if ln.startswith("python3 tools/sweep-selftests.py ") and " #" in ln]
    _cm_before = _markdown_fence_lines(CLAUDE_REL, _cm_text)
    _cm_after = _markdown_fence_lines(
        CLAUDE_REL,
        _cm_text.replace(_cm_run[0],
                         _cm_run[0].split(" #")[0] + "  # and tools/ghost-gate.mjs")
        if _cm_run else _cm_text)
    check("x5 the ANNOTATION beside a fenced command is not read: CLAUDE.md's "
          "sweep line carries one (%r), and rewriting it to name a tool no side "
          "runs leaves the runnable lines byte-identical (%d lines either way) "
          "with no ghost gate invented. This is what makes that comment safe to "
          "correct, which it was not known to be: %r"
          % (_cm_run, len(_cm_before),
             sorted(set(_cm_after) - set(_cm_before))),
          bool(_cm_run) and _cm_before == _cm_after
          and "python3 tools/sweep-selftests.py" in _cm_before
          and not any("ghost-gate" in ln for ln in _cm_after))

    buf = io.StringIO()
    listed = render_list({"verify.sh": set(["tools/alpha.mjs"]), "ci.yml": set(),
                          "CONTRIBUTING.md": None,
                          "CLAUDE.md": set(["tools/alpha.mjs"])}, stream=buf)
    shown = buf.getvalue()
    check("l0 --list heads a column per side, derived from SIDES. It was two "
          "hard-coded columns, so a side it did not know about was invisible "
          "in the one output that exists to show what each side invokes - and "
          "an unreadable side prints `?` rather than reading as a side that "
          "runs nothing: %r" % (shown,),
          listed == 1 and all(label in shown for label, _r in SIDES)
          and "x" in shown and "?" in shown)


    # --- the sweep's isolation against every document that describes it -------
    # F163: three documents describe what `sweep-selftests.py` points away from the
    # machine, the surface grew more than once, and each document was left behind by
    # a different amount because nothing compared any of them with the runner.
    _iso = isolation_drift()
    check("is0 THE LIVE CLAIM: every family the sweep pins is named by every "
          "document that describes the isolation, and the runner agrees with "
          "itself about what it watches - read over %d document(s) and the "
          "families %r, with a run that could not ask the question saying so "
          "instead of coming back empty: %r / %r / %r"
          % (_iso["sides"], sorted(_iso["groups"]), _iso["problem"],
             _iso["prose"], _iso["runner"]),
          _iso["problem"] is None and _iso["prose"] == []
          and _iso["runner"] == [] and _iso["sides"] == len(ISOLATION_SIDES))

    # A MINIATURE RUNNER, and every name in it is invented: what is being tested is
    # that the families are READ, so a fixture spelling the real ones would pass
    # against a rule that had them written in. `PROBE_ENCODING` is the fixture value
    # that tells two implementations apart - it is set from an argument rather than
    # from a directory this runner allocated, so a version that took every `env[...]
    # = ...` would report it as a family no document names.
    _mini = ('import os, tempfile\n'
             'FAM_A = ("PROBE_ONE", "PROBE_TWO")\n'
             'FAM_B = ("PROBE_HOME",)\n'
             'LABELS = ("first", "second")\n'
             'MARK = "probe-mark"\n'
             'def fam_b_env(home):\n'
             '    out = dict((n, home) for n in FAM_B)\n'
             '    out["PROBE_DRIVE"] = home\n'
             '    return out\n'
             'def child_debris(a, b):\n'
             '    return [(l, r) for l, r in zip(LABELS, (a, b))]\n'
             'def run_one(rel):\n'
             '    env = dict(os.environ)\n'
             '    work = tempfile.mkdtemp(prefix="a-")\n'
             '    home = tempfile.mkdtemp(prefix="b-")\n'
             '    cache = tempfile.mkdtemp(prefix="c-")\n'
             '    for name in FAM_A:\n'
             '        env[name] = work\n'
             '    env.update(fam_b_env(home))\n'
             '    env["PROBE_CACHE"] = cache\n'
             '    env["PROBE_ENCODING"] = rel\n'
             '    for root in (work, home):\n'
             '        open(os.path.join(root, MARK), "wb")\n'
             '    return env\n')
    _mini_groups, _mini_problem = pinned_env_groups(_mini)
    check("is1 the families are READ off the runner - the spread constant, the "
          "literal key, and the pair a helper DERIVES from the path rather than "
          "listing - and grouped by the directory each points at. A name set from "
          "an argument is not a place and is not a family: %r / %r"
          % (_mini_problem, _mini_groups),
          _mini_problem is None
          and _mini_groups == {"work": ("PROBE_ONE", "PROBE_TWO"),
                               "home": ("PROBE_DRIVE", "PROBE_HOME"),
                               "cache": ("PROBE_CACHE",)})
    # THE PAIR. Two documents differing ONLY in whether they name a member of every
    # family. Asserting the reported one alone would pass against a rule that
    # reported every family always; asserting the clean one alone would pass against
    # a rule that found nothing either way.
    _names_all = "it pins PROBE_TWO, PROBE_HOME and PROBE_CACHE per child"
    _names_some = "it pins PROBE_TWO and PROBE_HOME per child"
    check("is2 a document naming one member of a family names the family, and a "
          "document naming none of them is reported for exactly that family - "
          "the grain is a family because the runner pins every spelling a lookup "
          "reads and a document that listed all of them would be the module: "
          "%r vs %r"
          % (unnamed_groups(_names_all, _mini_groups),
             unnamed_groups(_names_some, _mini_groups)),
          unnamed_groups(_names_all, _mini_groups) == []
          and unnamed_groups(_names_some, _mini_groups) == ["cache"])
    # ...and the property that makes is0 worth anything about the REAL runner: the
    # families it derives are wider than the one name each document leads with, so a
    # rule that had read `TMPDIR` and `HOME` alone would be green on a document that
    # never mentioned the rest.
    _wide = sorted(held for held in _iso["groups"] if len(_iso["groups"][held]) > 1)
    check("is3 ...and the real runner's families are read whole rather than by "
          "their leading name: more than one of them carries more than a single "
          "variable, which is what a rule spelling one name per family could not "
          "say: %r" % (_wide,),
          len(_wide) > 1)

    _mini_watch = watched_channels(_mini)
    _mini_extra = watched_channels(_mini.replace("zip(LABELS, (a, b))",
                                                 "zip(LABELS, (a, b, a))"))
    _mini_unplanted = watched_channels(_mini.replace("for root in (work, home):",
                                                     "for root in (work,):"))
    check("is4 THE RUNNER AGAINST ITSELF, both directions: a watched directory "
          "with no label beside it is DROPPED by `zip` and reported about by "
          "nothing, and a watched directory with nothing planted in it can report "
          "a stray but never a deletion. The agreeing fixture reports neither, "
          "which is the case that fails if this starts firing unconditionally: "
          "%r / %r / %r" % (_mini_watch, _mini_extra, _mini_unplanted),
          (_mini_watch["problem"] is None
           and _mini_watch["labels"] == _mini_watch["read"] == _mini_watch["planted"]
           and _mini_extra["read"] != _mini_extra["labels"]
           and _mini_unplanted["planted"] != _mini_unplanted["read"]))

    _broken, _why_broken = pinned_env_groups("def run_one(:\n")
    _entryless, _why_entryless = pinned_env_groups("x = 1\n")
    _pinless, _why_pinless = pinned_env_groups(
        "import tempfile\n"
        "def run_one(rel):\n"
        "    env = {}\n"
        "    work = tempfile.mkdtemp(prefix='a-')\n"
        "    return env, work\n")
    check("is5 a runner that will not parse, one with no such function, and one "
          "that pins NOTHING are three NAMED problems and not one empty group "
          "map - all three produce the shape of a runner that isolates nothing, "
          "and a caller told which it got is the difference between this rule "
          "and a clean answer about a file nobody read: %r / %r / %r"
          % (_why_broken, _why_entryless, _why_pinless),
          _broken == _entryless == _pinless == {}
          and (_why_broken or "").startswith("does not parse")
          and "no module-level" in (_why_entryless or "")
          and "allocated" in (_why_pinless or ""))

    _no_repo = isolation_drift(os.path.join(REPO, "no-such-repo-dir"))
    check("is6 a tree with no runner in it is a NAMED problem rather than a "
          "document set that agrees with nothing - an empty finding list is what "
          "perfect agreement looks like, and one of the two means the rule never "
          "ran: %r" % (_no_repo["problem"],),
          _no_repo["problem"] is not None and _no_repo["prose"] == []
          and _no_repo["sides"] == 0)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
