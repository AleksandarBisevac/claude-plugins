#!/usr/bin/env python3
"""
What a hook costs on the critical path of every tool call — and the one part of it
that can be gated without flaking.

    python3 tools/bench-hooks.py             # the measurement, for a human
    python3 tools/bench-hooks.py --json      # the same, machine-readable
    python3 tools/bench-hooks.py --gate      # the deterministic check CI runs
    python3 tools/bench-hooks.py --gate --python /usr/bin/python3.9
                                             # ...and on one you name as well

WHY THE WALL CLOCK IS NOT THE GATE. A hook is unlike every other cost in this repo:
it is not the sweep's wall clock and not CI's CPU, it is latency added to EVERY
matching tool call, several times over — `hooks.json` puts three PreToolUse and four
PostToolUse hooks on one edit. So it looks like the obvious thing to put a ceiling
on. It is not. Measured on an idle-ish laptop, the ratio of one hook's wall clock to
a bare interpreter start swings by double-digit percent between repeats of the same
command, while the regressions worth catching — an eagerly imported module — are
worth a fraction of a baseline each. A ceiling loose enough not to flake cannot see
them; one tight enough to see them fires on a busy runner. Re-derive both figures
before disagreeing:

    python3 tools/bench-hooks.py --json      # ratio, per lane, this machine
    python3 tools/bench-hooks.py --json      # ...and again, for the spread

WHAT IS GATED INSTEAD. The import graph, which is exact. Every hook pays for its
module-level imports on every invocation, and that set is decidable: load the hook
in a fresh interpreter and diff `sys.modules`. `SHARED_FLOOR` is what a hook cannot
avoid (it imports `_config`, which reaches the config, the globs and the locks);
`EXTRA_ALLOWED` is what one named hook may add and why. Anything else fails BY NAME.
That catches the whole class the measurement was reaching for, with no timing in it.

AND IT IS ASKED OF EVERY INTERPRETER THIS MACHINE CAN OFFER, not of the one that
typed the command. The import graph moves between versions - a C accelerator that
exists on 3.9 and has merged away by 3.13 is enough - and this plugin publishes
support for a RANGE (`vermin -t=3.8-` is a gate). A verdict taken at one point in
that range is still worth having, and it now arrives with the point named and with
the versions nobody could reach listed as unreached. Both halves matter: a gate
that says which interpreter it ran on can be argued with, and one that says which
it did not is not mistaken for a gate that ran on all of them.

The two regressions that motivated this are worth naming, because both were invisible
to every gate the repo had:

  * `hooks/_config.py` loaded the scripts-side policy engine at module scope purely
    to copy its defaults, dragging `_output` and `ast` — a BUILD-TIME dependency of
    the house-style lints — into all ten hooks. One hook consults a policy.
  * `guard-bash-writes` and `guard-history-rewrite` imported `subprocess` at module
    scope for branches that run on a small minority of calls; `subprocess` brings a
    dozen modules with it.

Exit codes: 0 ok — 1 a budget violation (with --gate) or a failed selftest — 2 usage.
"""
import ast
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

_output.install_path()

HOOKS_DIR = os.path.join(REPO, "plugins", "audit", "hooks")

# Fixture names are ASSEMBLED, never written out. `_refs.tools_py_refs()` reads every
# python-module basename appearing anywhere under tools/ and requires it to name a
# file that exists - a real rule, and the invented names a selftest needs would each
# be a violation of it. tools/affected.py and tools/prove-gates.py compose theirs the
# same way. Rewording, not widening: loosening that lint to admit a fixture would
# stop it catching the stale reference it exists for.
_EXT = "." + "py"
_FIX_SRC = "a" + _EXT                    # the throwaway source file a payload names
_FIX_ABSENT = "no-such-hook-at-all" + _EXT
_FIX_GREEDY = "greedy-hook" + _EXT
_FIX_LEAN = "lean-hook" + _EXT
_FIX_BROKEN = "broken-hook" + _EXT
# An interpreter name that resolves to nothing, for the cases about a probe that
# cannot run. Deliberately not one of the names above: "a hook that is not there"
# and "an interpreter that is not there" are two different questions, and sharing
# one fixture between them is how a case comes to pass for the other one's reason.
_FIX_NO_PYTHON = "no-such-interpreter-anywhere"

# --- the import budget --------------------------------------------------------
# THE FLOOR IS DERIVED, and it used to be a frozen list. That list was measured on
# one interpreter and compared on every other, and the stdlib import graph is not
# stable across versions: measured here, `_config` pulls `warnings` on 3.13 and does
# not on 3.14, and pulls `fcntl` and `io` on 3.14 and does not on 3.13. CI runs
# 3.12, so six hooks were "1 module beyond budget: warnings" there while the same
# command on the same commit said "within budget" locally. Three green certifications
# of a red tree came out of that.
#
# The comment this replaces carried TWO definitions and only noticed one. The cause
# it named — "every hook imports `_config`, and `_config` reaches the config file,
# the exempt globs and the lock files" — is exact and measurable. The method it then
# described, "the intersection of what all the hooks pull", is a different claim that
# happened to agree, and it is the one that can RISE: if every hook grew heavier at
# once the intersection would grow with them and the gate would pass through the very
# regression it exists for.
#
# So the cause is what is measured, in the SAME interpreter that will judge the
# hooks. `_config` is added back by name because the probe loads it under its own
# module name, so it never appears in its own result — but it does appear in every
# hook's, which imports it.
_FLOOR_MODULE = "_config.py"


def shared_floor(hooks_dir=None, python=None):
    """The modules a hook cannot avoid, on THIS interpreter, or None if unmeasurable.

    None rather than an empty set on failure, and every caller reports it: an empty
    floor would fail every hook for the wrong reason, which is the shape a probe that
    stopped working takes.
    """
    pulled = modules_pulled(_FLOOR_MODULE, hooks_dir=hooks_dir, python=python)
    if pulled is None:
        return None
    return frozenset(pulled | {"_config"})


# THE DERIVED FLOOR ANSWERS ONE QUESTION AND A SECOND ONE HAS TO BE ASKED SEPARATELY.
# "What is unavoidable on this interpreter" is what the derivation measures. "And is
# that still what we agreed to pay" is a different question, and the frozen list was
# answering both — badly at the first and by accident at the second.
#
# It matters most here of anywhere: `_config.py` is excluded from the hook
# measurement because it is not invoked, it is what they all import, so nothing
# bounded it at all. An eager import added there is paid by every hook on every
# matching call — seven times over on one edit, per `hooks.json`. A floor derived
# from `_config` would simply absorb it and report every hook `within budget`,
# turning the loudest regression this tool can catch into silence.
#
# So the second question is asked of the SOURCE, not of the runtime graph:
# `_config.py`'s module-scope imports, read from the AST. That is version-independent
# by construction — it is what the file says, not what an interpreter happens to drag
# behind it — and unlike a list of names somebody thought expensive, it catches an
# addition whether or not anyone would have called it expensive. `warnings`, the
# module that made CI red, is on no expensive list anywhere.
CONFIG_IMPORTS = frozenset((
    "copy", "fnmatch", "json", "os", "pathlib", "re", "sys", "time",
))


def _module_scope_imports(path):
    """Top-level import names in one file, or None if it cannot be read or parsed."""
    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (IOError, OSError, UnicodeDecodeError, SyntaxError):
        return None
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module.split(".")[0])
    return names


def floor_regressions(hooks_dir=None):
    """[(module, why)] — what the shared helper imports beyond what was agreed.

    Reported in BOTH directions. An addition is the regression; a removal means the
    declaration outlived the code, and a declaration nobody trimmed is how this list
    would come to permit an import that is no longer there.
    """
    here = hooks_dir or HOOKS_DIR
    got = _module_scope_imports(os.path.join(here, _FLOOR_MODULE))
    if got is None:
        return [(None, "_config.py could not be read or parsed, so what every hook "
                       "pays for cannot be established - reported rather than passed")]
    out = [(m, "imported by _config at module scope, so EVERY hook pays for it on "
               "EVERY matching call") for m in sorted(got - CONFIG_IMPORTS)]
    out += [(m, "declared here but no longer imported by _config - trim it, or this "
                "list starts permitting what is not there") 
            for m in sorted(CONFIG_IMPORTS - got)]
    return out

# What one named hook may add, and the reason it may. A reason is required by the
# selftest, not by convention: an allowance nobody can explain is an allowance that
# outlives the need for it.
#
# `modules` IS THE ALLOWANCE A HUMAN AGREED TO. `derive` is what that allowance
# costs, measured on the interpreter doing the judging rather than written out —
# the same move `shared_floor()` already made, for the same reason and one layer
# down. The entry below read `("hashlib", "_hashlib", "_blake2")`, which is exactly
# what `import hashlib` drags on 3.13 and 3.14; on 3.9 it drags `_sha3` as well, so
# the gate was green on the interpreter that wrote the list and red on a version
# `vermin -t=3.8-` and COMPATIBILITY.md both promise support for. A C accelerator
# appearing or merging away is a version fact, and a version fact belongs in a
# measurement.
#
# It does not widen the rule. The allowance still buys exactly one named module's
# own graph: a hook that started importing `subprocess` would be reported, because
# `hashlib` does not drag it.
EXTRA_ALLOWED = {
    "journal-writes.py": {
        "modules": ("hashlib",),
        "derive": ("hashlib",),
        "why": "the journal is a hash chain - each row commits to its predecessor, "
               "so this hook cannot defer hashing into a branch",
    },
}

# `subprocess` is called out because it is the expensive one and because it has now
# been deferred out of two hooks. It brings roughly a dozen modules behind it
# (threading, selectors, select, signal, locale, warnings, ...), so a hook that
# imports it at module scope pays for all of them on calls that never spawn
# anything. Both hooks that needed git now import it inside the branch that runs it.
NOTABLE = ("subprocess", "ast", "_ast", "_output", "tempfile", "difflib",
           "argparse", "datetime", "socket", "urllib", "unicodedata")

_PROBE = (
    "import sys, json\n"
    "sys.path.insert(0, %r)\n"
    "_base = set(sys.modules)\n"
    "import importlib.util as _iu\n"
    "_spec = _iu.spec_from_file_location('bench_probe', %r)\n"
    "_mod = _iu.module_from_spec(_spec)\n"
    "_spec.loader.exec_module(_mod)\n"
    "print(json.dumps(sorted(m for m in set(sys.modules) - _base "
    "if '.' not in m)))\n"
)

# The same question asked of a NAMED module rather than of a file, which is what an
# allowance's `derive` needs: not "what does this hook pull" but "what does the one
# thing it is allowed to import cost here".
_IMPORT_PROBE = (
    "import sys, json\n"
    "_base = set(sys.modules)\n"
    "for _name in %r:\n"
    "    __import__(_name)\n"
    "print(json.dumps(sorted(m for m in set(sys.modules) - _base "
    "if '.' not in m)))\n"
)

# The version this plugin promises to run on, held by `vermin -t=3.8-` in CI and
# published in COMPATIBILITY.md. It is here because the budget is a claim about that
# whole RANGE, and a verdict from one point in it has to say which point.
SUPPORTED_MINOR_MIN = 8


def hook_files(hooks_dir=None):
    """The hooks whose import weight is gated: entry points, not the shared helper.

    `_config.py` is excluded because it is not invoked — it is what they all import,
    and its own weight is asserted by `plugins/audit/tests/test__config.py`.
    """
    d = hooks_dir or HOOKS_DIR
    try:
        names = os.listdir(d)
    except Exception:
        return []
    return sorted(n for n in names
                  if n.endswith(".py") and n != "_config.py"
                  and not n.startswith("."))


def modules_pulled(hook, hooks_dir=None, python=None):
    """Top-level modules a fresh interpreter gains from loading `hook`, or None.

    None is a distinct answer from an empty set: the probe failing to run at all
    must never read as "this hook imports nothing", which is the shape that would
    turn this whole gate green by breaking it.
    """
    d = hooks_dir or HOOKS_DIR
    out = subprocess.run(
        [python or sys.executable, "-c",
         _PROBE % (os.path.abspath(d), os.path.join(os.path.abspath(d), hook))],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if out.returncode != 0:
        return None
    try:
        return set(json.loads(out.stdout.decode("utf-8", "replace")))
    except Exception:
        return None


def modules_pulled_by_import(names, python=None):
    """Top-level modules a fresh interpreter gains from importing `names`, or None.

    None on any failure, for the reason `modules_pulled` gives: a probe that would
    not run must never be spelled the way "this costs nothing" is spelled. Here it
    matters twice over, because an empty allowance would then report a hook over
    budget for something it was granted.
    """
    try:
        out = subprocess.run(
            [python or sys.executable, "-c", _IMPORT_PROBE % (list(names),)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    try:
        return set(json.loads(out.stdout.decode("utf-8", "replace")))
    except Exception:
        return None


def allowance_for(hook, python=None, table=None):
    """`(modules, problem)` — what one hook may add beyond the floor, on `python`.

    Exactly one of the two is None. A `derive` the probe could not run yields the
    problem, never a narrower allowance: silently falling back to the declared names
    alone is how a measured allowance would decay back into the hand-written list
    this replaced, and it would do it on the machine least able to notice.

    `table` is a parameter for the reason `compare()` in `tools/gate-parity.py` has
    one: the live table's declared names happen to EQUAL what its `derive` measures
    on most interpreters, so a case asked over the real entry cannot tell a derived
    allowance from a frozen one except on the one version where they diverge. A
    fixture whose declared set is deliberately smaller can, on every version.
    """
    spec = (EXTRA_ALLOWED if table is None else table).get(hook)
    if not spec:
        return frozenset(), None
    out = set(spec.get("modules") or ())
    derive = tuple(spec.get("derive") or ())
    if derive:
        pulled = modules_pulled_by_import(derive, python=python)
        if pulled is None:
            return None, ("its allowance derives from %s and that probe would not "
                          "run, so what this hook may add cannot be established"
                          % ", ".join(derive))
        out |= pulled
    return frozenset(out), None


# --- which interpreters the verdict covers ------------------------------------
# THE FLOOR BEING DERIVED WAS READ AS THE WHOLE REPAIR, AND IT IS HALF OF ONE.
# Deriving it stopped the SHARED floor disagreeing with itself between versions.
# It left the hooks' own graphs, and every allowance, measured on exactly one
# interpreter — whichever one typed the command — while the line that comes out
# says `10 hook(s) within budget` and names no condition at all.
#
# `journal-writes.py` is the proof rather than the hypothesis: its allowance was
# three module names, correct on 3.13 and 3.14, one short on 3.9. The gate was
# green on every interpreter anyone had run it on and red on a version this plugin
# publishes support for, and nothing in the output could have told you which of
# those you were reading.
#
# So the verdict now carries its basis: which interpreters it was taken on, and
# which supported versions it did NOT reach. A machine that offers one interpreter
# still gets a useful answer — it is the answer it can have — but it gets it with
# the condition attached instead of as a property of the system.
def interpreter_version(python):
    """`"3.12.4"` for `python`, or None when it will not run or will not say."""
    try:
        out = subprocess.run(
            [python, "-c",
             "import sys;print('%d.%d.%d' % sys.version_info[:3])"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    text = out.stdout.decode("utf-8", "replace").strip()
    return text or None


def candidate_names():
    """The interpreter names to look for on PATH.

    DERIVED from `sys.version_info` rather than written out. A frozen top rots the
    day a newer release ships and nobody notices, because the tool goes on happily
    measuring the versions it was told about; the running interpreter's own minor is
    by definition the newest this machine knows of.
    """
    top = max(sys.version_info[1], SUPPORTED_MINOR_MIN)
    names = ["python3.%d" % m
             for m in range(SUPPORTED_MINOR_MIN, top + 1)]
    # `python3` and `python` are here because a machine's newest interpreter is not
    # always reachable under a versioned name - a system Python often is not - and
    # a name that resolves to one already found is dropped below by real path.
    return names + ["python3", "python"]


def discover_interpreters(extra=None):
    """`{"found": [(path, version)], "unusable": [(name, why)]}`.

    `sys.executable` first: it is the one interpreter that is certainly there, so a
    machine with nothing else still gets a measured answer rather than none.

    An `extra` (from `--python`) that will not run is REPORTED. "You named an
    interpreter and it is not one" and "you named none" are different answers, and
    a tool that dropped the first would measure fewer versions than it was asked to
    and say the same thing either way.
    """
    found, unusable, seen = [], [], set()

    def consider(name, loud):
        path = name if os.path.isabs(name) else shutil.which(name)
        if not path:
            if loud:
                unusable.append((name, "no such interpreter on PATH"))
            return
        key = os.path.realpath(path)
        if key in seen:
            return
        version = interpreter_version(path)
        if version is None:
            if loud:
                unusable.append((name, "would not run, or would not report a "
                                       "version"))
            return
        seen.add(key)
        found.append((path, version))

    consider(sys.executable, True)
    for name in candidate_names():
        consider(name, False)
    for name in (extra or ()):
        consider(name, True)
    return {"found": found, "unusable": unusable}


def unmeasured_minors(found):
    """The supported 3.x minors no discovered interpreter covers, as sorted ints.

    The ceiling is the highest minor anything here knows about - the running
    interpreter or a discovered one - so this never invents versions that do not
    exist yet, and never quietly stops at a number somebody typed once.
    """
    covered = set()
    for _path, version in found:
        bits = str(version).split(".")
        if len(bits) >= 2 and bits[0] == "3" and bits[1].isdigit():
            covered.add(int(bits[1]))
    top = max([sys.version_info[1], SUPPORTED_MINOR_MIN] + sorted(covered))
    return [m for m in range(SUPPORTED_MINOR_MIN, top + 1) if m not in covered]


def budget_violations(hooks_dir=None, python=None):
    """[(hook, sorted-unbudgeted-modules, notable-among-them)] — empty when clean.

    A hook the probe could not load is reported too, as `None` modules, because a
    gate that silently skips what it cannot measure is not a gate.
    """
    out = []
    # Measured once, with the interpreter that will judge the hooks. Taking it from
    # a constant is what made this gate disagree with itself across versions.
    floor = shared_floor(hooks_dir=hooks_dir, python=python)
    if floor is None:
        return [(_FLOOR_MODULE, None, ())]
    # One probe per allowance, not one per hook: the allowances are keyed by hook
    # and there is at most a handful of them, but the derivation is a subprocess and
    # this runs once per interpreter now.
    allowances = {}
    for hook in EXTRA_ALLOWED:
        allowances[hook] = allowance_for(hook, python=python)
    for hook in hook_files(hooks_dir):
        granted, problem = allowances.get(hook, (frozenset(), None))
        if problem is not None:
            # Reported as its own row rather than folded into "over budget": the
            # hook may be perfectly lean, and accusing it of the modules it was
            # granted would be a finding about the probe wearing the hook's name.
            out.append((hook, None, ()))
            continue
        pulled = modules_pulled(hook, hooks_dir=hooks_dir, python=python)
        if pulled is None:
            out.append((hook, None, ()))
            continue
        allowed = set(floor) | set(granted)
        extra = sorted(pulled - allowed)
        if extra:
            out.append((hook, extra, tuple(m for m in extra if m in NOTABLE)))
    return out


# --- the measurement ----------------------------------------------------------
# Named lanes rather than one number per hook: `guard-bash-writes` runs on both the
# Edit and the Bash matcher and the two branches cost very different amounts, which
# is the fact that made deferring its `subprocess` import worth doing.
LANES = (
    ("guard-edits.py", "ask", "edit"),
    ("require-plan.py", "ask", "edit"),
    ("journal-writes.py", "open", "edit"),
    ("remind-tdd.py", "open", "edit"),
    ("guard-bash-writes.py", "open", "edit"),
    ("guard-bash-writes.py", "open", "bash"),
    ("guard-secrets-read.py", "ask", "read"),
    ("guard-secrets-read.py", "ask", "bash"),
    ("guard-history-rewrite.py", "ask", "bash"),
    ("guard-capabilities.py", "ask", "skill"),
)


def _payloads(root):
    """One hook payload per lane kind, rooted at a throwaway directory."""
    src = os.path.join(root, "src", _FIX_SRC)
    return {
        "edit": {"tool_name": "Edit", "tool_input": {
            "file_path": src, "old_string": "x=1", "new_string": "x=2"}},
        "bash": {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        "read": {"tool_name": "Read", "tool_input": {"file_path": src}},
        "skill": {"tool_name": "Skill", "tool_input": {"skill": "some-skill"}},
    }


def _median_ms(argv, payload=None, repeats=9):
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        subprocess.run(argv, input=payload,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        times.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(times)


def measure(repeats=9, hooks_dir=None):
    """{"baseline": ms, "lanes": [{...}]} — wall clock, and the ratio to a bare start.

    The ratio is reported instead of the delta because machine speed scales both
    terms; the delta alone is meaningless off the machine that produced it. Neither
    is gated — see the module docstring for the spread that decided that.
    """
    d = hooks_dir or HOOKS_DIR
    launcher = os.path.join(d, "py-launch.sh")
    root = tempfile.mkdtemp(prefix="bench-hooks-")
    try:
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        with io.open(os.path.join(root, "src", _FIX_SRC), "w",
                     encoding="utf-8") as fh:
            fh.write("x=1\n")
        bodies = _payloads(root)
        baseline = _median_ms([sys.executable, "-c", "pass"], repeats=repeats)
        lanes = []
        for hook, mode, kind in LANES:
            body = dict(bodies[kind])
            body["session_id"] = "bench-hooks"
            body["cwd"] = root
            blob = json.dumps(body).encode("utf-8")
            ms = _median_ms(["sh", launcher, hook, mode], payload=blob,
                            repeats=repeats)
            lanes.append({"hook": hook, "lane": kind, "ms": round(ms, 2),
                          "ratio": round(ms / baseline, 3) if baseline else None})
        return {"baseline_ms": round(baseline, 2), "repeats": repeats,
                "lanes": lanes}
    finally:
        # F156. What stood here was a call to `_output.rmtree_quiet()` behind a
        # `hasattr` for it - and no such helper has ever existed, in `_output` or
        # anywhere else, so the condition was false on every run and the statement
        # was a no-op wearing a defensive coat. The `isdir` guard below it existed
        # only to avoid removing twice after a call that never happened, and
        # `ignore_errors=True` already tolerates a directory that is not there.
        #
        # A PLAIN REMOVAL IS THE RIGHT ONE HERE, which is the other half of the
        # judgement and is recorded rather than left to the next reader (F155).
        # This fixture is a `src/` directory of text; nothing under it is a git
        # repository, so there are no read-only loose objects for windows to
        # refuse to unlink. The tree that DOES need the careful removal reaches it
        # through `_harness.remove_tree()`, re-exported by `tools/_suite.py`.
        shutil.rmtree(root, ignore_errors=True)


# --- rendering ----------------------------------------------------------------
def render_report(data):
    out = ["hook latency - wall clock per invocation, median of %d"
           % data["repeats"],
           "  bare interpreter start: %.2f ms  (the floor nothing can remove)"
           % data["baseline_ms"], ""]
    out.append("  %-26s %-6s %9s %8s" % ("hook", "lane", "ms", "xbase"))
    for row in data["lanes"]:
        out.append("  %-26s %-6s %9.2f %8s"
                   % (row["hook"], row["lane"], row["ms"],
                      "-" if row["ratio"] is None else "%.2f" % row["ratio"]))
    out.append("")
    out.append("  NOT a gate: this swings between repeats by more than a deferred "
               "import is worth.")
    out.append("  The gated part is the import budget: "
               "python3 tools/bench-hooks.py --gate")
    return "\n".join(out)


def render_violations(violations):
    if not violations:
        hooks = hook_files()
        return ("hook import budget: %d hook(s) within budget - none reaches "
                "beyond the shared floor except where EXTRA_ALLOWED says why"
                % len(hooks))
    out = ["hook import budget: %d hook(s) over budget" % len(violations)]
    for hook, extra, notable in violations:
        if extra is None:
            out.append("  %s: could NOT be loaded by the probe - unmeasured, "
                       "which this gate treats as a failure rather than a skip"
                       % hook)
            continue
        out.append("  %s: %d module(s) beyond budget: %s"
                   % (hook, len(extra), ", ".join(extra)))
        if notable:
            out.append("      the expensive one(s): %s - import inside the branch "
                       "that needs it, or add an EXTRA_ALLOWED entry saying why "
                       "every invocation should pay" % ", ".join(notable))
    return "\n".join(out)


def render_gate(report):
    """The whole verdict, with the condition that makes it true. Returns text.

    THE CONDITION IS NOT AN APPENDIX. `10 hook(s) within budget` with no interpreter
    named is the sentence F87 is about: it was read as a property of the system and
    it was a property of one machine. So the versions come first, the per-version
    verdicts follow, and the versions nobody could measure are named LAST and out
    loud - a gap said plainly is the difference between a narrow answer and a wrong
    one.
    """
    out = []
    if report["problem"]:
        return "hook import budget: NOT MEASURED - %s" % report["problem"]
    drift = report["drift"]
    if drift:
        out.append("shared floor: %d change(s) to what EVERY hook pays for"
                   % len(drift))
        for mod, why in drift:
            out.append("  %-14s %s" % (mod if mod else "-", why))
    versions = ", ".join(row["version"] for row in report["measured"])
    out.append("hook import budget, measured on %d interpreter(s): %s"
               % (len(report["measured"]), versions))
    for row in report["measured"]:
        head = render_violations(row["violations"]).splitlines()
        out.append("  %-9s %s" % (row["version"], head[0].split(": ", 1)[-1]))
        for line in head[1:]:
            out.append("  " + line)
    for name, why in report["unusable"]:
        out.append("  %s: named but not usable - %s" % (name, why))
    gaps = report["unmeasured"]
    if gaps:
        # Never "everything is fine": this verdict covers the versions above and
        # says so. `vermin -t=3.8-` promises the rest, and a budget that quietly
        # spoke for versions it never ran on is what made this line necessary.
        out.append("  NOT MEASURED: %s - no interpreter for %s was found here, so "
                   "this covers the version(s) above and not the whole supported "
                   "range. Name one with --python <path>."
                   % (", ".join("3.%d" % m for m in gaps),
                      "them" if len(gaps) > 1 else "it"))
    return "\n".join(out)


# --- selftest -----------------------------------------------------------------
def _cases(check):
    hooks = hook_files()
    check("h1 the hook list is the entry points, and excludes the shared helper",
          len(hooks) >= 8 and "_config.py" not in hooks
          and "guard-edits.py" in hooks)

    # The gate's own fail-open. `modules_pulled` returning None on a probe it could
    # not run is the only thing standing between "unmeasurable" and "imports
    # nothing", and the second reads as a pass. Asked with a name that is not there.
    check("h2 a hook that cannot be probed reads as None, never as an empty set",
          modules_pulled(_FIX_ABSENT) is None)

    _floor = shared_floor()
    pulled = modules_pulled("guard-edits.py")
    check("h3 the probe really observes imports - a known hook pulls the floor "
          "measured on THIS interpreter. Asserting a frozen list here is what made "
          "this case pass locally and fail on CI: the floor differs by version, and "
          "the constant was a snapshot of whichever one measured it",
          _floor is not None and pulled is not None and _floor.issubset(pulled))

    check("h4 every hook still pulls the whole floor - an entry no hook needs is an "
          "allowance nobody asked for, and deriving the floor does not excuse that: "
          "it is derived from `_config`, not from the hooks, so it can still name "
          "something none of them reach",
          bool(_floor) and all(_floor.issubset(v) for v in
                               (modules_pulled(h) or _floor for h in hooks)))

    # The half a derived floor CANNOT answer, and the reason it is asked of the
    # source rather than of the runtime graph.
    check("h4b `_config` imports exactly what was agreed - the derived floor absorbs "
          "anything added there and would report every hook `within budget`, which "
          "turns the costliest regression this tool can catch into silence: %r"
          % (floor_regressions(),),
          floor_regressions() == [])

    # h4c: the removal direction. `CONFIG_IMPORTS` is a declaration, and a declaration
    # nobody trims starts permitting what is no longer there - so a name it keeps that
    # `_config` has stopped importing is a finding too, not a tidy-up.
    _fl = tempfile.mkdtemp(prefix="bench-hooks-floor-")
    try:
        with io.open(os.path.join(_fl, _FLOOR_MODULE), "w", encoding="utf-8") as fh:
            fh.write("import os\n")
        _drift = floor_regressions(hooks_dir=_fl)
        _added = [m for m, _w in _drift if m and m not in CONFIG_IMPORTS]
        _gone = [m for m, _w in _drift if m in CONFIG_IMPORTS]
        check("h4c a declared import `_config` no longer makes IS reported - the "
              "list would otherwise go on allowing what is not there, and only the "
              "addition half was pinned until a mutation that removed this reporting "
              "coloured nothing: added=%r gone=%r" % (_added, _gone),
              not _added and sorted(_gone) == sorted(CONFIG_IMPORTS - {"os"}))
        # ...and the file being unreadable is its own answer, never an empty one.
        with io.open(os.path.join(_fl, _FLOOR_MODULE), "w", encoding="utf-8") as fh:
            fh.write("this is not python(\n")
        _bad = floor_regressions(hooks_dir=_fl)
        check("h4d an unparseable `_config` is REPORTED - 'I cannot establish what "
              "every hook pays for' must not be spelled like 'it pays for what was "
              "agreed': %r" % (_bad,),
              len(_bad) == 1 and _bad[0][0] is None)
    finally:
        import shutil as _sh3
        _sh3.rmtree(_fl, ignore_errors=True)

    # h4e: and both halves reach the DECISION. Removing the floor half from the gate
    # turned nothing red until this existed - the check was computed, rendered, and
    # consulted by nothing that could fail.
    # Asked over a fixture that HAS drift, never over the clean tree. Comparing
    # `gate_findings()[0]` with `floor_regressions()` on a healthy repo compares two
    # empty lists: it passes just as happily when the wiring is cut, which is exactly
    # what a mutation severing it proved - it coloured nothing.
    _w = tempfile.mkdtemp(prefix="bench-hooks-wired-")
    try:
        with io.open(os.path.join(_w, _FLOOR_MODULE), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport urllib\n")
        _g = gate_findings(hooks_dir=_w)
        _floor_half = [m for m, _w2 in _g[0]]
        check("h4e `--gate` decides on BOTH halves - a floor change reaches the "
              "decision rather than only the printout. A check that is rendered and "
              "consulted by nothing that can fail is not a gate: %r" % (_floor_half,),
              isinstance(_g, tuple) and len(_g) == 2 and "urllib" in _floor_half)
    finally:
        import shutil as _sh4
        _sh4.rmtree(_w, ignore_errors=True)

    check("h5 every EXTRA_ALLOWED entry names a hook that exists and carries a "
          "reason - an allowance nobody can explain outlives its need",
          all(h in hooks and str(v.get("why", "")).strip()
              and v.get("modules")
              for h, v in EXTRA_ALLOWED.items()))

    # THE CASE THAT MATTERS: the gate must be able to go red. A fabricated hook
    # directory holding one file that imports something expensive, asked through
    # the real `budget_violations`.
    tmp = tempfile.mkdtemp(prefix="bench-hooks-selftest-")
    try:
        # A hooks directory without `_config.py` is not one: the floor is what
        # that file drags in, so the fixture carries a minimal stand-in rather
        # than asking the real tree for it. `os` alone, so a fixture hook that
        # imports only `os` is genuinely on the floor and `h7` still means what
        # its label says.
        with io.open(os.path.join(tmp, _FLOOR_MODULE), "w",
                     encoding="utf-8") as fh:
            fh.write("import os\n")
        with io.open(os.path.join(tmp, _FIX_GREEDY), "w",
                     encoding="utf-8") as fh:
            fh.write("import subprocess\nimport ast\n")
        with io.open(os.path.join(tmp, _FIX_LEAN), "w",
                     encoding="utf-8") as fh:
            fh.write("import os\n")
        bad = budget_violations(hooks_dir=tmp)
        named = dict((h, tuple(e or ())) for h, e, _n in bad)
        check("h6 a hook importing subprocess and ast is reported, and both are "
              "named",
              _FIX_GREEDY in named
              and "subprocess" in named[_FIX_GREEDY]
              and "ast" in named[_FIX_GREEDY], repr(named))
        # The second direction. Without it, a gate that flagged EVERY hook would
        # pass h6 - and `os` is not on the floor, so this also pins that the floor
        # is not being used as a catch-all.
        check("h7 ...while a hook importing only a floor member is NOT reported - "
              "the second-direction case for h6",
              _FIX_LEAN not in named, repr(named))
        # A hook the probe cannot execute must be REPORTED, not quietly dropped:
        # "I could not measure this" and "this is within budget" are the two
        # answers a gate must never merge. A syntax error is the cheapest way to
        # be unloadable while still being a `.py` the lister returns.
        broken = tempfile.mkdtemp(prefix="bench-hooks-broken-")
        try:
            # A hooks directory without `_config.py` is not one: the floor is what
            # that file drags in, so the fixture carries a minimal stand-in rather
            # than asking the real tree for it. `os` alone, so a fixture hook that
            # imports only `os` is genuinely on the floor and `h7` still means what
            # its label says.
            with io.open(os.path.join(broken, _FLOOR_MODULE), "w",
                             encoding="utf-8") as fh:
                fh.write("import os\n")
            with io.open(os.path.join(broken, _FIX_BROKEN), "w",
                         encoding="utf-8") as fh:
                fh.write("import os\nthis is not python(\n")
            bad_b = budget_violations(hooks_dir=broken)
            check("h8 an unloadable hook is reported with None modules, not "
                  "skipped as if it were clean",
                  [(h, e) for h, e, _n in bad_b] == [(_FIX_BROKEN, None)],
                  repr(bad_b))
            check("h8b ...and it renders as unmeasured rather than as a module "
                  "list",
                  "could NOT be loaded" in render_violations(bad_b))
        finally:
            import shutil as _sh2
            _sh2.rmtree(broken, ignore_errors=True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # Rendering, both ways round: the clean line must not read like a failure and
    # the failure line must name the hook.
    check("h9 the clean report says what was checked rather than staying silent",
          "within budget" in render_violations([]))
    check("h10 the failure report names the hook and the module",
          _FIX_GREEDY in render_violations(
              [(_FIX_GREEDY, ["subprocess"], ("subprocess",))])
          and "subprocess" in render_violations(
              [(_FIX_GREEDY, ["subprocess"], ("subprocess",))]))

    # --- the condition the verdict is true under (F87) -------------------------
    _found = discover_interpreters()
    check("h11 the running interpreter is always among the discovered ones, and "
          "each carries the version it actually reports - a gate that named no "
          "interpreter is the sentence F87 is about: %r"
          % ([v for _p, v in _found["found"]],),
          any(os.path.realpath(p) == os.path.realpath(sys.executable)
              for p, _v in _found["found"])
          and all(str(v)[:2] == "3." for _p, v in _found["found"]))

    # The second direction, and the one a discovery function gets wrong: an
    # interpreter somebody NAMED and that is not one must be reported. Dropping it
    # measures fewer versions than were asked for and prints the same line either
    # way.
    _named = discover_interpreters([_FIX_NO_PYTHON])
    check("h12 an interpreter named with --python that will not run is REPORTED, "
          "not dropped - 'you named one and it is not one' must not be spelled "
          "like 'you named none': %r" % (_named["unusable"],),
          [n for n, _w in _named["unusable"]] == [_FIX_NO_PYTHON]
          and _named["found"] == _found["found"])

    # THE F87 REGRESSION CASE. The allowance was written out as three module names
    # and `hashlib` drags a fourth on 3.9, so `journal-writes.py` was over budget on
    # a version this plugin promises while every interpreter anyone had run it on
    # said `within budget`.
    #
    # ASKED OVER A FIXTURE, and that is the whole reason the fixture exists. The live
    # entry declares `hashlib` and derives from `hashlib`, so on any interpreter
    # where the old hand-written list was already correct the two spellings produce
    # the SAME set - the case would pass identically against the frozen list, which
    # is a case that cannot fail on most machines. The fixture declares NOTHING and
    # derives from `hashlib`, so the entire grant is the measurement: a build that
    # stopped deriving hands back an empty allowance here, on every version.
    _fixture_table = {_FIX_LEAN: {"modules": (), "derive": ("hashlib",),
                                  "why": "a fixture, not a real allowance"}}
    _granted, _why_not = allowance_for(_FIX_LEAN, table=_fixture_table)
    _bare = modules_pulled_by_import(("hashlib",))
    check("h13 an allowance is MEASURED, not listed: an entry that declares no "
          "module and derives from one is granted exactly what importing that "
          "module costs on this interpreter, which is what the hand-written list "
          "was one short of on 3.9: %r" % (sorted(_granted or ()),),
          _why_not is None and _bare is not None and _granted == frozenset(_bare)
          and "hashlib" in _granted and len(_granted) > 1)

    # ...and the mechanism is WIRED to the real allowance rather than only available
    # to it. h4e's lesson: a derivation nothing consults is a derivation that can be
    # deleted without colouring anything.
    _live = EXTRA_ALLOWED["journal-writes.py"]
    _live_granted, _live_why = allowance_for("journal-writes.py")
    check("h13b ...and the live entry really derives - it names `derive` and its "
          "grant carries what that module drags here, so the hook that carries "
          "'auditable' is judged against a measurement and not against a snapshot: "
          "%r" % (sorted(_live_granted or ()),),
          bool(_live.get("derive")) and _live_why is None
          and _bare is not None and _bare.issubset(_live_granted))
    _dead_grant, _dead_why = allowance_for("journal-writes.py",
                                           python=_FIX_NO_PYTHON)
    check("h14 ...and a `derive` the probe cannot run is a PROBLEM, never a "
          "narrower allowance - falling back to the declared names alone is how a "
          "measured allowance decays into the list it replaced, silently and on "
          "the machine least able to notice: %r" % (_dead_why,),
          _dead_grant is None and _dead_why is not None
          and "hashlib" in _dead_why)
    # ...and a hook with no entry gets an EMPTY allowance and no problem, which is
    # the direction that fails if the two are ever merged into one falsy answer.
    check("h15 a hook with no allowance is granted nothing, and that is not a "
          "problem - the case that goes red if 'no entry' and 'the probe died' "
          "ever come back as the same value",
          allowance_for("guard-edits.py") == (frozenset(), None))

    # h16: one red interpreter fails the whole gate. Without it, a loop that
    # measured four and read only the last would pass every case above.
    _one_red = {"drift": [], "unusable": [], "unmeasured": [], "problem": None,
                "measured": [{"python": "a", "version": "3.9.6",
                              "violations": []},
                             {"python": "b", "version": "3.14.0",
                              "violations": [(_FIX_GREEDY, ["subprocess"],
                                              ("subprocess",))]}]}
    _all_green = dict(_one_red,
                      measured=[dict(_one_red["measured"][0]),
                                dict(_one_red["measured"][1], violations=[])])
    check("h16 a violation on ONE interpreter fails the gate, and an all-green set "
          "does not - the second half is the case that fails if the verdict is "
          "ever taken from the last row measured",
          gate_failed(_one_red) is True and gate_failed(_all_green) is False)
    check("h17 ...and a report that measured NOTHING fails too: zero measurements "
          "and zero violations are spelled identically by any `any()` over an "
          "empty list, and one of them is a broken probe",
          gate_failed({"drift": [], "measured": [], "unusable": [],
                       "unmeasured": [], "problem": "the probe died"}) is True)

    # The rendering, both directions. A version nobody could measure must not read
    # like a version that passed, and the versions that DID pass must be named.
    _text = render_gate(_all_green)
    _gapped = render_gate(dict(_all_green, unmeasured=[8, 10]))
    check("h18 the verdict names the interpreters it covers, and an unmeasured "
          "version is named as unmeasured rather than omitted - omission is what "
          "let one machine's answer read as a property of the system: %r"
          % (_gapped.splitlines()[-1:],),
          "3.9.6" in _text and "3.14.0" in _text
          and "NOT MEASURED" not in _text
          and "NOT MEASURED" in _gapped and "3.8" in _gapped
          and "3.10" in _gapped)

    check("h19 the supported range starts where the published floor does, and the "
          "list of names to look for is derived from it rather than written out",
          SUPPORTED_MINOR_MIN == 8
          and candidate_names()[0] == "python3.8"
          and ("python3.%d" % sys.version_info[1]) in candidate_names())


def gate_findings(hooks_dir=None, python=None):
    """`(floor_drift, budget_violations)` — everything `--gate` decides on.

    A function rather than a block inside `main()` so a case can assert that BOTH
    halves reach the decision. They did not, at first: the source half was computed
    and rendered, and removing it from the gate turned nothing red - a check that
    exists without deciding anything, which is the shape this repo keeps finding.

    The floor half is returned first because it is reported first, and that ordering
    is the point rather than presentation: if `_config` has grown, every hook is
    "within budget" only because the floor grew with it, so printing the hooks above
    the reason would put a reassurance over the fact that voids it.
    """
    return (floor_regressions(hooks_dir=hooks_dir),
            budget_violations(hooks_dir=hooks_dir, python=python))


def gate_report(hooks_dir=None, extra_pythons=None):
    """`--gate`'s whole answer, per interpreter, plus what it could not reach.

    {"drift": [...], "measured": [{"python", "version", "violations"}],
     "unusable": [(name, why)], "unmeasured": [minor], "problem": None|str}

    `drift` is asked ONCE and not per interpreter, and that is a fact about the
    question rather than a saving: `floor_regressions()` reads `_config.py`'s AST,
    which is what the file SAYS. Running it under four interpreters would be four
    copies of one answer, and copies of one answer are how a reader comes to
    believe a version-independent check is version-dependent.

    `problem` is set only when nothing could be measured at all. That cannot happen
    from `sys.executable` alone, so it is the shape of a broken probe rather than of
    a bare machine - and a gate that reported zero measurements as zero violations
    would be exactly the silent pass this file's own `h2` exists for.
    """
    found = discover_interpreters(extra_pythons)
    measured = []
    for path, version in found["found"]:
        measured.append({"python": path, "version": version,
                         "violations": budget_violations(hooks_dir=hooks_dir,
                                                         python=path)})
    problem = None
    if not measured:
        problem = ("no interpreter could be probed at all, so nothing was "
                   "checked - this is a broken probe, not a clean tree")
    return {"drift": floor_regressions(hooks_dir=hooks_dir),
            "measured": measured, "unusable": found["unusable"],
            "unmeasured": unmeasured_minors(found["found"]),
            "problem": problem}


def gate_failed(report):
    """Does this report fail the build? A separate function because the answer has
    three sources and a `--gate` branch that spelled them inline would be the place
    one of them quietly stops being read - which is the defect `h4e` records."""
    if report["problem"]:
        return True
    if report["drift"]:
        return True
    return any(row["violations"] for row in report["measured"])


def _extra_pythons(argv):
    """Every `--python <path>` in `argv`, in order. A flag with no value is dropped
    here and refused by the usage guard in `__main__`, so it can never silently
    become "measure nothing extra"."""
    out = []
    for i, arg in enumerate(argv):
        if arg == "--python" and i + 1 < len(argv):
            out.append(argv[i + 1])
    return out


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


# --- main ---------------------------------------------------------------------
def main(argv):
    if "--selftest" in argv:
        return _selftest()
    if "--gate" in argv:
        report = gate_report(extra_pythons=_extra_pythons(argv))
        print(render_gate(report))
        return 1 if gate_failed(report) else 0
    data = measure()
    if "--json" in argv:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(render_report(data))
    return 0


if __name__ == "__main__":
    _output.safe_stdio()
    args = sys.argv[1:]
    _expect_value = False
    for _a in args:
        if _expect_value:
            _expect_value = False
            continue
        if _a == "--python":
            _expect_value = True
            continue
        if _a not in ("--selftest", "--gate", "--json"):
            sys.stderr.write("usage: bench-hooks.py [--gate | --json | "
                             "--selftest] [--python PATH ...]\n")
            raise SystemExit(2)
    if _expect_value:
        sys.stderr.write("bench-hooks.py: --python needs an interpreter path\n")
        raise SystemExit(2)
    raise SystemExit(main(args))
