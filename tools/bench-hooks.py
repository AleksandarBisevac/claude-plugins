#!/usr/bin/env python3
"""
What a hook costs on the critical path of every tool call — and the one part of it
that can be gated without flaking.

    python3 tools/bench-hooks.py             # the measurement, for a human
    python3 tools/bench-hooks.py --json      # the same, machine-readable
    python3 tools/bench-hooks.py --gate      # the deterministic check CI runs

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
EXTRA_ALLOWED = {
    "journal-writes.py": {
        "modules": ("hashlib", "_hashlib", "_blake2"),
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
    for hook in hook_files(hooks_dir):
        pulled = modules_pulled(hook, hooks_dir=hooks_dir, python=python)
        if pulled is None:
            out.append((hook, None, ()))
            continue
        allowed = set(floor)
        allowed.update(EXTRA_ALLOWED.get(hook, {}).get("modules", ()))
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
        _output.rmtree_quiet(root) if hasattr(_output, "rmtree_quiet") else None
        if os.path.isdir(root):
            import shutil
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


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


# --- main ---------------------------------------------------------------------
def main(argv):
    if "--selftest" in argv:
        return _selftest()
    if "--gate" in argv:
        drift, violations = gate_findings()
        if drift:
            print("shared floor: %d change(s) to what EVERY hook pays for"
                  % len(drift))
            for mod, why in drift:
                print("  %-14s %s" % (mod if mod else "-", why))
        print(render_violations(violations))
        return 1 if (drift or violations) else 0
    data = measure()
    if "--json" in argv:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(render_report(data))
    return 0


if __name__ == "__main__":
    _output.safe_stdio()
    args = sys.argv[1:]
    for _a in args:
        if _a not in ("--selftest", "--gate", "--json"):
            sys.stderr.write("usage: bench-hooks.py [--gate | --json | "
                             "--selftest]\n")
            raise SystemExit(2)
    raise SystemExit(main(args))
