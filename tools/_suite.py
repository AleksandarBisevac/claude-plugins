#!/usr/bin/env python3
"""
The house helpers `tools/` may not copy, as reached from here - and the rules that
keep them here.

WHY A BRIDGE RATHER THAN A SECOND RUNNER. `tests/_harness.py` owns
`run()`: the `N/M cases passed` contract, the escape guard that turns a raised fixture
into a named failing case with every case already recorded still printed, and the
case-id uniqueness check. Every suite under `tests/` inherited all of it and every tool
under `tools/` inherited none, because each tool wrote its own printer - most of them
saying `FAILURES` where the house says `SELFTEST FAILED`, and one saying nothing at
all. `_harness`' own docstring records that spelling as a DEFECT rather than a variant:
a suite whose last line reads the same whether it passed or failed leaves the numbers
as its only sentinel. So the fix was documented, adopted, and had never reached these
files.

`run` is re-exported here, not reimplemented. A second copy of mutate-print-tally is
how the hand-rolled printers came to disagree in the first place - and `attempt` comes
with it, because a tool with a probe that must not abort the suite wants the same
answer `tests/` already has rather than a local `try` written a tenth way.

`remove_tree` is here for the same reason and it is the second thing this file carries.
Git writes its loose objects READ-ONLY. On POSIX that is invisible, because
unlinking a file needs a writable DIRECTORY and not a writable file; on windows the
attribute is read off the file itself, `os.unlink` raises, and `shutil.rmtree` leaves
`.git/objects/**` behind - SILENTLY, because every caller in this tree spells the call
`ignore_errors=True`. `_output.remove_tree()` in the scripts anchor is the answer and
its one home; `_harness.remove_tree` and the sweep runner's name are bound to it, and a
tool that needs the same answer gets it from here rather than becoming another copy.

WHY THE IMPORT IS DEFERRED, WHICH IS THE OBJECTION THIS FILE ANSWERS. `tools/` is
outside the plugin, and importing `_harness` puts `scripts/`, `hooks/` and every
subdirectory of `scripts/` on `sys.path` as a side effect of the import. A tool that
renders a report or counts pins should not pay for the test tree to run, and - more to
the point - should not stop working when it is missing. So a tool imports this module
INSIDE the code path that needs it - `_selftest()` for the runner, the `finally` that
disposes of a fixture for the removal - and the `sys.path` cost lands only on the modes
that ask for it. A tool whose FIXTURE is a git repository does reach the test tree on
its ordinary run, and that is a cost rather than a breakage: such a tool is a gate
driven from a checkout that has `tests/` in it, and `tools/` is development machinery in
the same sense `tests/` is.

That is also why `tools/` is not the `tests_import_violations()` rule's business.
That rule forbids `scripts/` and `hooks/` - the PRODUCT, the thing that ships - from
importing its own test tree. `tools/` ships with nothing; it is development machinery
in the same sense `tests/` is, and the marketplace payload is `plugins/audit/`.

AND THE RULES, BECAUSE AN EXEMPTION THAT EXISTS ONLY AS THE ABSENCE OF AN IMPORT IS
EASY TO LOSE TRACK OF. `hand_rolled_runners()` reads every tool's `_selftest` and reports one
that tallies its own cases instead of delegating here. `unsafe_removal_violations()`
reads every tool's removals - and, handed `tests/`, every suite's - and reports a bare
`shutil.rmtree(..., ignore_errors=True)` over a directory git wrote objects into: one
function and one reading, `removal_problem()`, for both trees. Both are derived from the tree, so the NEXT tool is
covered the day it is written rather than the day somebody remembers - which is the
same answer for the removal helper, whose call sites used to be enumerated by hand and
whose next one would not have been.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import builtins
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
TOOLS_DIR = _HERE
TESTS_DIR = os.path.join(REPO, "tests")

if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

# `_harness` puts `scripts/`, `hooks/` and every `.py`-bearing subdirectory of
# `scripts/` on `sys.path` as it is imported - which is why this import is the
# thing tools defer, and why `_output` below is reachable without a second bootstrap.
import _harness  # noqa: E402
import _output   # noqa: E402

# THE re-export, and the whole point of the file. Bound to the function object rather
# than wrapped: a wrapper here would be a second place for the tally to be spelled,
# and `s1` pins this identity for exactly that reason.
run = _harness.run
attempt = _harness.attempt

# THE SAME BINDING FOR THE SAME REASON, and the reason is sharper here: this fact has
# one home and a copy a check compares with it, so another spelling is not a style
# question but a rule broken. Bound, never wrapped - `s11` pins the identity, and
# `unsafe_removal_violations()` below quotes this name out of the object rather than
# out of a literal, so the rule cannot come to name a helper the bridge does not hand
# out.
remove_tree = _harness.remove_tree


# --- the marker a mutating gate sweep holds ------------------------------------
# `prove-gates.py` edits the working tree for minutes and restores it after each row.
# Nothing another process could see said so, so a concurrent sweep read a half-mutated
# tree and reported reds that were not real. The marker is a file under the git dir (not
# the working tree, which is what is being mutated, and not tracked), carrying the pid
# and the start time; the sweep refuses on a live one and `orchestrator-state.py`
# reports it. A marker whose pid is gone is stale - a killed run cannot release it - and
# is ignored aloud rather than wedging every later sweep.
MARKER_NAME = "prove-gates-live.json"


def git_dir_of(repo):
    """The absolute git dir of `repo`'s working tree, or None when git cannot say."""
    import subprocess
    try:
        got = subprocess.run(["git", "-C", repo, "rev-parse", "--absolute-git-dir"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    path = got.stdout.decode("utf-8", "replace").strip()
    return path if got.returncode == 0 and path else None


def pid_alive(pid):
    """Whether a process with this pid is running - the plugin's one probe, so a marker
    and a lock cannot disagree about who is gone. A pid it cannot judge reads as not
    alive here: the marker is advisory and a stale one is reported aloud."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    import _locks            # on sys.path through the `_harness` import above
    return _locks.pid_alive(pid) is True


def hold(git_dir, pid=None):
    """Write the marker for `pid` (this process by default); returns its path."""
    import json
    import time
    path = os.path.join(git_dir, MARKER_NAME)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(u"%s\n" % json.dumps({
            "pid": os.getpid() if pid is None else pid,
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    return path


def release(path):
    """Remove the marker; a marker already gone is not an error."""
    try:
        os.remove(path)
    except OSError:
        pass


def marker_state(git_dir):
    """What the marker says: {"state": none|live|stale|unreadable, "path", "pid",
    "started"}. An unreadable marker is its own state - reading it as `none` would let
    a sweep run over a tree somebody is mutating."""
    import json
    path = os.path.join(git_dir, MARKER_NAME)
    if not os.path.isfile(path):
        return {"state": "none", "path": path, "pid": None, "started": None}
    try:
        with io.open(path, encoding="utf-8") as fh:
            body = json.load(fh)
        pid, started = int(body["pid"]), str(body.get("started", "?"))
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "unreadable", "path": path, "pid": None, "started": None}
    return {"state": "live" if pid_alive(pid) else "stale", "path": path,
            "pid": pid, "started": started}


# --- the rule: no tool tallies its own cases ----------------------------------
def _selftest_body(tree):
    """The statements of a module-level `def _selftest`, or None if there is none."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_selftest":
            return node.body
    return None


def _is_runner_import(stmt):
    """True for an import out of this module - `from _suite import run`, or run and
    `attempt` together.

    The NAMES are not pinned, only where they come from: a rule that spelled the
    import list would refuse a tool importing the other half of the pair, and the
    delegation below is what actually carries the weight here.
    """
    return isinstance(stmt, ast.ImportFrom) and stmt.module == "_suite"


def _is_delegation(stmt):
    """True for `return run(<name>)` - the whole of a delegating `_selftest`."""
    if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.Call):
        return False
    call = stmt.value
    return (isinstance(call.func, ast.Name) and call.func.id == "run"
            and len(call.args) == 1 and isinstance(call.args[0], ast.Name)
            and not call.keywords)


def runner_problem(source):
    """Why `source`'s `_selftest` does not delegate to the house runner, or None.

    A PURE FUNCTION OVER TEXT, so both directions of the rule are driven from
    strings rather than from `.py` files written into a temp directory. That is
    not only cheaper: a `.py` basename literal written under `tools/` has to name
    a real file (`_refs.tool_basename_drift()`), so a fixture-file spelling of
    these cases would need a declared exemption to say what a string says for
    free.

    A module with no `_selftest` is NOT this rule's finding - the sweep already
    fails a tool that prints no contract, and reporting it twice under two
    different names is two bug reports for one defect.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return "does not parse, so nothing can be said about its runner: %s" % (exc,)
    body = _selftest_body(tree)
    if body is None:
        return None
    for stmt in body:
        if _is_runner_import(stmt) or _is_delegation(stmt):
            continue
        return ("its `_selftest` does its own work at line %d instead of handing "
                "`_cases` to the shared runner - which is how a tool comes to print "
                "its own tally, and every hand-rolled tally so far has printed the "
                "same last line on a pass and on a failure. The whole of a tool's "
                "`_selftest` is `from _suite import run` and `return run(_cases)`, "
                "with `_cases(check)` calling `check(label, cond, detail=\"\")` "
                "once per case" % (stmt.lineno,))
    if not any(_is_delegation(stmt) for stmt in body):
        return ("its `_selftest` never returns `run(_cases)`, so whatever it reports "
                "is not the house contract")
    return None


def hand_rolled_runners(tools_dir=None):
    """[(rel, problem)] for every tool that runs its own suite. Empty when clean.

    Walks with `_output.py_files()`, the same recursive walk the sweep uses to
    decide which files must carry a suite at all - a second walk here is how a
    file in a subdirectory comes to be swept by one rule and missed by another.
    """
    root = tools_dir if tools_dir is not None else TOOLS_DIR
    out = []
    for rel, path in _output.py_files(root):
        try:
            source = io.open(path, encoding="utf-8").read()
        except OSError as exc:
            out.append((rel, "could not be read: %s" % (exc,)))
            continue
        problem = runner_problem(source)
        if problem is not None:
            out.append((rel, problem))
    return out


# --- the rule: no tool removes a repository it built with a bare rmtree --------
# THE TWO SETS ARE THE MEASUREMENT, NOT A GUESS AT ONE. Run a bare repository
# initialisation into an empty directory and nothing under it lacks an owner-write
# bit; stage a single file and a read-only loose object appears immediately. So the
# marker for "this tool builds a tree windows cannot remove" is not the presence of
# a repository, it is the presence of a repository that has been WRITTEN to - and
# spelling it this way is what keeps the demo capture, whose fixture initialises a
# repository and never stages anything into it, out of the findings while convicting
# it on the day its fixture learns to stage or commit. An exemption row would have
# recorded the same premise in prose and gone on firing after it stopped being true.
REPO_MARKERS = ("git",)
OBJECT_MARKERS = ("add", "commit", "clone")

# The tests/ files the rule convicts and that are not repaired yet:
# `{file relative to tests/: why it stays}`. Empty while every conviction is repaired.
# A row naming a file the rule no longer convicts is itself a finding
# (`unsafe_removal_violations` reports it), so the table cannot outlive its premise.
# Adding the first row also owes `gate-parity.py` an `AUDITED_EXEMPTIONS` row for this
# table, naming `unsafe_removal_violations` as its auditor: `gate-parity.py` reports a
# reason-carrying table nothing audits, and reports that row as stale while this is empty.
REMOVAL_EXEMPT = {}


def _plain_constants(tree):
    """Every string constant in `tree` except the docstrings.

    THE NARROWING IS WHAT LETS THIS RULE LIVE IN A FILE THAT EXPLAINS IT. Several
    guards here read source as TEXT and cannot tell code from a comment about code,
    and the usual way to meet one is to describe it. Dropping docstrings is a
    distinction with a reason behind it rather than a hole cut to fit this file: a
    word a module only ever says about itself is not a word it passes to a
    subprocess. Comments are not constants at all, so they never arrive here.
    """
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            continue
        if not body or not isinstance(body[0], ast.Expr):
            continue
        first = body[0].value
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            docstrings.add(id(first))
    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            out.add(node.value)
    return out


def _bare_removal_lines(tree, helper):
    """The lines of every `<module>.rmtree(...)` call outside `def <helper>`.

    THE HELPER IS NOT ONE OF ITS OWN CALLERS. `remove_tree` is BUILT out of two
    ordinary removals - one that works everywhere and one behind a chmod pass - so
    a rule that counted them would convict the very answer it hands out, and the
    repair a reader reaches for when a rule convicts the arrangement it was written
    to police is to delete the rule. The copy under `tools/sweep-selftests.py` is
    the file this protects today.
    """
    return sorted(call.lineno for call in
                  _bare_removal_calls(tree, _helper_body_ids(tree, helper)))


def _bare_removal_calls(tree, inside):
    """Every `<module>.rmtree(...)` call whose node id is not in `inside`."""
    return [node for node in ast.walk(tree)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "rmtree" and id(node) not in inside)]


def _helper_body_ids(tree, helper):
    """Ids of every node inside `def <helper>`."""
    inside = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == helper:
            for child in ast.walk(node):
                inside.add(id(child))
    return inside


# --- which of a module's removals ran over a directory that was WRITTEN to -----
# The rule used to convict every bare removal in a module that built a written
# repository, which is right for a small tool and wrong for a suite: one file holds
# hundreds of fixtures and most are not repositories. So the module-level test above
# stays as the cheap first question, and each removal then answers for ITSELF: did
# the function that holds it hand git an object-writing verb for the directory it is
# removing, or for one that directory contains or was derived from?
_OBJECT_VERBS = frozenset(OBJECT_MARKERS)


def _non_variable_names(tree):
    """Names that are not fixture variables: builtins and everything imported."""
    names = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update((alias.asname or alias.name).split(".")[0]
                         for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _variables(node, ignore):
    return set(n.id for n in ast.walk(node)
               if isinstance(n, ast.Name) and n.id not in ignore)


def _constants_and_identifiers(nodes):
    """(lower-cased string constants, lower-cased names and attributes) under `nodes`."""
    consts, idents = set(), set()
    for root in nodes:
        for n in ast.walk(root):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                consts.add(n.value.lower())
            elif isinstance(n, ast.Name):
                idents.add(n.id.lower())
            elif isinstance(n, ast.Attribute):
                idents.add(n.attr.lower())
    return consts, idents


def _assignments(scope):
    """[(line, target names, value)] for every assignment or `for` binding under
    `scope`; a `for` binding's value is the iterable."""
    out = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            targets = set(n for t in node.targets for n in _bound_by(t))
            out.append((node.lineno, targets, node.value))
        elif isinstance(node, ast.For):
            # `for d in (a, b): rmtree(d)` - the loop variable is built from what it
            # iterates, which is how it joins the family of those directories.
            out.append((node.lineno, set(_bound_by(node.target)), node.iter))
    return out


def _bound_by(target):
    """The names an assignment target binds. `os.environ[k] = v` binds none: it
    changes an object, and walking into it would call `os` a fixture variable."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for elt in target.elts for name in _bound_by(elt)]
    if isinstance(target, ast.Starred):
        return _bound_by(target.value)
    return []


def _outermost_function(tree, line):
    """The top-level function holding `line`, or the module when none does."""
    best = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef) and node.lineno <= line <= node.end_lineno
                and (best is None or node.lineno < best.lineno)):
            best = node
    return best if best is not None else tree


def _directory_family(call, scope, assigns, ignore, defs):
    """(names the removed directory goes by, first line it can have been written
    from, module functions its latest assignment called) - or (None, None, [])
    when its history cannot be traced here.

    The removed expression's variables are followed BOTH ways inside `scope`, through
    path-building values only (`_is_path_expression`): up, into what the latest
    assignment to each was built from (`proj = join(tmp, ...)` makes `tmp` part of
    the family), and down, into later assignments built from a member. Only the
    LATEST assignment before the call counts, because a suite reuses one name for
    many fixtures and an earlier fixture's repository is not this one's. A fixture
    built by a function (`root = _repo()`) is answered by that function's body.
    Untraceable means no member was ever assigned in `scope`: a parameter, a global.
    """
    family = _variables(call.args[0], ignore) if call.args else set()
    if not family:
        return None, None, []
    latest = {}
    for line, targets, value in assigns:
        if line < call.lineno:
            for name in targets:
                if line >= latest.get(name, (0, None))[0]:
                    latest[name] = (line, value)
    if not any(name in latest for name in family):
        return None, None, []
    while True:
        known = [latest[n][0] for n in family if n in latest]
        start = min(known)
        grown = set(family)
        for name in family:
            if name in latest and _is_path_expression(latest[name][1]):
                grown |= _variables(latest[name][1], ignore)
        for line, targets, value in assigns:
            if (start <= line < call.lineno and _is_path_expression(value)
                    and _variables(value, ignore) & grown):
                grown |= targets
        if grown == family:
            built_by = [defs[n.func.id] for name in family if name in latest
                        for n in ast.walk(latest[name][1])
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in defs]
            return family, start, built_by
        family = grown


# The only calls that build one path out of another. A directory named by a value
# computed any other way - a parser, a helper, a `json.dumps` - is a different
# thing that merely mentions the first.
_PATH_CALLS = frozenset(("str", "os.path.join", "os.path.dirname", "os.path.abspath",
                         "os.path.realpath", "os.path.normpath", "os.fspath"))


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _is_path_expression(value):
    """True when every call inside `value` builds a path from other paths."""
    return all(_dotted(n.func) in _PATH_CALLS
               for n in ast.walk(value) if isinstance(n, ast.Call))


def _names_word(words, target):
    """True when some word in `words` contains `target` as a WHOLE word, words being
    split at every character that is not a letter or digit (`run_git`, `git-dir`,
    `git`). A substring match convicts `digits`, which is where this was wrong."""
    return any(target in "".join(c if c.isalnum() else " " for c in word).split()
               for word in words)


def _def_writes_objects(defn):
    """True when `defn`'s own body hands git an object-writing verb."""
    consts, idents = _constants_and_identifiers([defn])
    return (_names_word(consts | idents, "git")
            and (bool(consts & _OBJECT_VERBS)
                 or _names_word(idents, "commit")))


def _writes_objects(call, scope, family, start, defs, nested, assigns):
    """True when some call in `scope` from line `start` on hands git an object
    verb and names a member of `family`, directly or through a local helper - or
    through a variable the verb was bound to (`for argv in (["add"], ...)`)."""
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call) or not start <= node.lineno <= call.lineno:
            continue
        func = node.func
        callee = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        helper = defs.get(callee)
        names = _variables(node, set())
        # What a NON-directory argument was bound to: the directory's own binding
        # says how it was made, not which verb it was handed.
        bound = [value for line, targets, value in assigns
                 if line <= node.lineno and targets & (names - family)]
        # The call is judged on what IT hands over (and what its arguments were bound
        # to), never on the words in its callee's body: a helper that merely runs git
        # somewhere is not a call that writes an object, and `verb(proj, "add")` is
        # the plugin's own `add`. A helper counts only when its OWN body writes one.
        consts, idents = _constants_and_identifiers([node] + bound)
        git_ish = _names_word(consts | idents, "git")
        writes = (bool(consts & _OBJECT_VERBS)
                  or _names_word(idents, "commit"))
        through_helper = helper is not None and _def_writes_objects(helper)
        if helper is not None and id(helper) in nested:
            names |= _variables(helper, set())
        if ((git_ish and writes) or through_helper) and names & family:
            return True
    return False


def _ignores_errors(call):
    """True when the removal is spelled `ignore_errors=True`."""
    return any(kw.arg == "ignore_errors" and isinstance(kw.value, ast.Constant)
               and kw.value.value is True for kw in call.keywords)


def _written_removal_lines(tree, helper):
    """Lines of the bare removals that ran over a directory git wrote objects into,
    plus those whose directory has no traceable history (a parameter, a global): a
    module that writes objects cannot show the unseen caller did not."""
    ignore = _non_variable_names(tree)
    defs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            defs[node.name] = node
    lines = []
    for call in _bare_removal_calls(tree, _helper_body_ids(tree, helper)):
        if not _ignores_errors(call):
            continue        # a removal that raises is loud; only the silent one is the defect
        scope = _outermost_function(tree, call.lineno)
        # A suite defines `run_git` many times over; the one that counts is the one
        # nested in the function holding this removal.
        local = dict((n.name, n) for n in ast.walk(scope)
                     if isinstance(n, ast.FunctionDef))
        visible = dict(defs, **local)
        nested = set(id(n) for n in local.values())
        assigns = _assignments(scope)
        family, start, built_by = _directory_family(
            call, scope, assigns, ignore, visible)
        if (family is None or any(_def_writes_objects(d) for d in built_by)
                or _writes_objects(call, scope, family, start, visible, nested,
                                   assigns)):
            lines.append(call.lineno)
    return sorted(lines)


def removal_problem(source):
    """Why `source` cannot remove the repositories it builds, or None.

    A PURE FUNCTION OVER TEXT, like `runner_problem()` above and for the same two
    reasons: both directions of the rule are driven from strings rather than from
    files written into a temp directory, and a `.py` basename written under
    `tools/` has to name a file that exists (`_refs.tool_basename_drift()`), so a
    fixture spelled as a file would need a declared exemption to say what a string
    says for free.

    TWO QUESTIONS, ASKED IN THIS ORDER. The module is asked first: does it name git,
    an `init` and an object-writing verb at all? A module that does not cannot have
    built a tree with a read-only file in it, whatever it removes. Then each bare
    removal in a module that does is asked for itself (`_written_removal_lines`),
    because a suite holds many fixtures and most are not repositories: the removal is
    a finding when git was handed an object-writing verb for the directory it
    removes, or for one that directory contains or was derived from, and also when
    that directory arrives from outside the function so nothing here can say it was
    not. A fixture that is only initialised stays allowed.

    ONE READING FOR `tools/` AND `tests/`. Both directories go through this function,
    and a second reading for the larger tree is how the two come to disagree about
    the same call.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return "does not parse, so nothing can be said about its removals: %s" % (exc,)
    words = _plain_constants(tree)
    # A suite drives git through a wrapper (`_harness.git(root, "add")`), so the word
    # may be an identifier and never a string.
    _consts, idents = _constants_and_identifiers([tree])
    if not any(_names_word(words | idents, marker) for marker in REPO_MARKERS):
        return None
    if not any(marker in words for marker in OBJECT_MARKERS):
        return None
    lines = _written_removal_lines(tree, remove_tree.__name__)
    if not lines:
        return None
    return ("it builds a git repository and writes to it, then removes a tree with "
            "`shutil.rmtree` at line(s) %s. Git's loose objects are read-only, "
            "windows refuses to unlink a read-only file, and `ignore_errors=True` "
            "turns that refusal into silence - so the removal has never worked "
            "there and nothing said so. `from _suite import %s`, which is "
            "`_harness.%s` and retries behind a chmod pass"
            % (", ".join(str(line) for line in lines), remove_tree.__name__,
               remove_tree.__name__))


def unsafe_removal_violations(tools_dir=None, label="", exempt=None):
    """[(rel, problem)] for every file under the directory that cannot remove what it
    built. Empty when clean. The directory is `tools/` by default; `tests/` goes
    through the SAME function, as `unsafe_removal_violations(TESTS_DIR, "tests/",
    REMOVAL_EXEMPT)`, because a second function for the larger tree is how the two
    come to read one call two ways.

    Walks with `_output.py_files()`, the same recursive walk `hand_rolled_runners()`
    and the sweep use - a second walk here is how a file in a subdirectory comes to
    be covered by one rule and missed by another.

    `label` is put before each `rel`. `exempt` is `{rel: reason}`: a file named there
    is left out while the rule still convicts it, and a row for a file the rule no
    longer convicts is reported instead, so an exemption cannot outlive the removal
    it excused.
    """
    root = tools_dir if tools_dir is not None else TOOLS_DIR
    exempt = {} if exempt is None else exempt
    out = []
    convicted = set()
    for rel, path in _output.py_files(root):
        try:
            source = io.open(path, encoding="utf-8").read()
        except OSError as exc:
            out.append((label + rel, "could not be read: %s" % (exc,)))
            continue
        problem = removal_problem(source)
        if problem is None:
            continue
        convicted.add(rel)
        if rel not in exempt:
            out.append((label + rel, problem))
    out.extend((label + rel, "exempt, and the rule no longer convicts it: %s" % (why,))
               for rel, why in sorted(exempt.items()) if rel not in convicted)
    return out


# --- the rule: no relative path between a scratch directory and the checkout ---
# `rel_or_abs` is the same kind of binding as `remove_tree` above: the fact has one
# home in the harness, and a tool that needs it reaches it from here.
rel_or_abs = _harness.rel_or_abs

# THE TWO SETS ARE WHAT A READER CAN SEE WITHOUT RUNNING THE CODE. A scratch path is
# one that came out of a call that makes a directory; a checkout path is one built
# from the names the anchor and the tools give the repository's own directories. A
# call is convicted when one side is the first kind only and the other the second
# kind only: those are the two that can sit on different drives, and a pair under one
# scratch root or one checkout root cannot.
SCRATCH_MAKERS = frozenset(("mkdtemp", "mkstemp", "TemporaryDirectory",
                            "NamedTemporaryFile", "gettempdir", "fixture_root"))
CHECKOUT_NAMES = frozenset(("REPO", "REPO_ROOT", "SCRIPTS_DIR", "PLUGIN_ROOT",
                            "TESTS_DIR", "HOOKS_DIR", "LINTS_DIR", "TOOLS_DIR",
                            "UI_DIR", "__file__"))
RELATIVE_CALLS = frozenset(("relpath", "posix_rel"))


def _callee(call):
    """The bare name a call is made through: `f` for `f()` and `m.f()`."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _scratch_makers(tree):
    """`SCRATCH_MAKERS` plus every function in `tree` that calls one, to a fixed point.

    This is how `_mini_repo()` - a local function whose whole body is a call to the
    harness - is known to hand back a scratch path, and it was that function's result
    that took the suite down. It reads names, not return values, so a function that
    makes a directory and returns something else is also a maker: the cost is a
    possible false finding on a call that feeds such a result to a relative path,
    and nothing in this tree does.
    """
    makers = set(SCRATCH_MAKERS)
    defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    changed = True
    while changed:
        changed = False
        for fn in defs:
            if fn.name in makers:
                continue
            if any(isinstance(n, ast.Call) and _callee(n) in makers
                   for n in ast.walk(fn)):
                makers.add(fn.name)
                changed = True
    return makers


def _name_bindings(nodes):
    """`{name: [expression bound to it]}` over the statements in `nodes`, nested
    functions included. A tuple target binds every name in it to the whole right
    side, which over-approximates and never under-approximates."""
    out = {}
    for top in nodes:
        for node in ast.walk(top):
            pairs = []
            if isinstance(node, ast.Assign):
                pairs = [(t, node.value) for t in node.targets]
            elif isinstance(node, (ast.For, ast.comprehension)):
                pairs = [(node.target, node.iter)]
            elif isinstance(node, ast.With):
                pairs = [(i.optional_vars, i.context_expr) for i in node.items
                         if i.optional_vars is not None]
            for target, value in pairs:
                for name in ast.walk(target):
                    # A STORE only: `os.environ[k] = v` holds the name `os` in a
                    # target too, and binding it made every `os.path` after it
                    # read as the right-hand side.
                    if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                        out.setdefault(name.id, []).append(value)
    return out


def _path_kinds(expr, chain, makers, seen=frozenset()):
    """(scratch, checkout): whether `expr` can be a scratch path, a checkout path.

    A name is followed through the innermost scope that binds it, then outward, the
    way the interpreter would; a name nothing binds (a parameter) is unknown and
    contributes nothing, so a helper that is handed both sides is never convicted
    for what its callers pass.
    """
    scratch = checkout = False
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and _callee(node) in makers:
            scratch = True
        elif isinstance(node, ast.Attribute) and node.attr in CHECKOUT_NAMES:
            checkout = True
        elif isinstance(node, ast.Name):
            if node.id in CHECKOUT_NAMES:
                checkout = True
            elif node.id not in seen:
                for bindings in chain:
                    if node.id in bindings:
                        for value in bindings[node.id]:
                            s, c = _path_kinds(value, chain, makers,
                                               seen | {node.id})
                            scratch, checkout = scratch or s, checkout or c
                        break
    return scratch, checkout


def _enclosing_functions(tree):
    """`{id(call): [innermost function, ..., outermost function]}` for every call."""
    chains = {}

    def visit(node, stack):
        if isinstance(node, ast.FunctionDef):
            stack = [node] + stack
        if isinstance(node, ast.Call):
            chains[id(node)] = stack
        for child in ast.iter_child_nodes(node):
            visit(child, stack)

    visit(tree, [])
    return chains


def _relative_call_lines(tree):
    """The lines of every relative-path call whose sides can be on two drives."""
    makers = _scratch_makers(tree)
    chains = _enclosing_functions(tree)
    module_scope = _name_bindings(
        [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))])
    cache = {}
    lines = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _callee(node) in RELATIVE_CALLS):
            continue
        sides = list(node.args[:2])
        sides += [k.value for k in node.keywords if k.arg == "start"]
        if not sides:
            continue
        chain = []
        for fn in chains.get(id(node), []):
            if id(fn) not in cache:
                cache[id(fn)] = _name_bindings([fn])
            chain.append(cache[id(fn)])
        chain.append(module_scope)
        kinds = [_path_kinds(side, chain, makers) for side in sides]
        # Only the call's own relative-path callee counts, not a call it contains:
        # `walk` above visits the inner call on its own turn.
        first = ("scratch" if kinds[0][0] and not kinds[0][1]
                 else "checkout" if kinds[0][1] and not kinds[0][0] else "")
        if len(kinds) == 1:
            # `start` is the working directory, which is the checkout when a suite
            # is run by hand and a scratch directory only under the sweep.
            if first == "scratch":
                lines.add(node.lineno)
            continue
        second = ("scratch" if kinds[1][0] and not kinds[1][1]
                  else "checkout" if kinds[1][1] and not kinds[1][0] else "")
        if {first, second} == {"scratch", "checkout"}:
            lines.add(node.lineno)
    return sorted(lines)


def relpath_problem(source):
    """Why `source` can raise building a relative path across two drives, or None.

    A PURE FUNCTION OVER TEXT, for the reasons `removal_problem()` is: both
    directions are driven from strings, and a fixture spelled as a file would need
    a `.py` basename the tree does not contain.

    WHAT IT CANNOT SEE, SAID BECAUSE A GREEN RESULT IS NOT A PROOF. A side that
    arrives as a function PARAMETER is unknown, so a helper handed both paths is
    judged by none of its callers; a scratch path read back out of a data structure
    or a file is not followed; and a relative path built any other way than the
    two calls named in `RELATIVE_CALLS` (`pathlib`'s `relative_to`, which raises a
    different error) is not read at all.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return "does not parse, so nothing can be said about its relative paths: %s" % (exc,)
    lines = _relative_call_lines(tree)
    if not lines:
        return None
    return ("it makes a path relative between a scratch directory and a checkout "
            "path at line(s) %s. On windows those sit on different drives (the "
            "runner's temp directory on one, the checkout on another), `relpath` "
            "has no answer for two drives and raises ValueError, and it did so "
            "while a suite's cases were still being built, which ended the run "
            "with every later case unrun. `from _suite import %s`, which is "
            "`_harness.%s` and answers the absolute path instead of raising"
            % (", ".join(str(line) for line in lines), rel_or_abs.__name__,
               rel_or_abs.__name__))


def unsafe_relpath_violations(root=None, label=""):
    """[(rel, problem)] for every file under `root` that can raise building a
    relative path across drives. Empty when clean. `tools/` by default; `tests/`
    goes through the same function as `unsafe_relpath_violations(TESTS_DIR,
    "tests/")`, for the reason `unsafe_removal_violations()` gives. Walks with
    `_output.py_files()`, and `label` is put before each `rel`.
    """
    root = root if root is not None else TOOLS_DIR
    out = []
    for rel, path in _output.py_files(root):
        try:
            source = io.open(path, encoding="utf-8").read()
        except OSError as exc:
            out.append((label + rel, "could not be read: %s" % (exc,)))
            continue
        problem = relpath_problem(source)
        if problem is not None:
            out.append((label + rel, problem))
    return out


# --- selftest -----------------------------------------------------------------
def _cases(check):
    check("s1 `run` IS `_harness.run`, the same function object the suites under "
          "tests/ call - not a copy, not a wrapper. This is the case that fails "
          "the day somebody reimplements the tally here, which is the defect this "
          "file exists to stop rather than to relocate",
          run is _harness.run and attempt is _harness.attempt)
    check("s2 ...so the deferred import really did reach the test tree: %r"
          % (TESTS_DIR,),
          os.path.isfile(os.path.join(TESTS_DIR, "_harness.py"))
          and TESTS_DIR in sys.path)

    # The actual complaint, asserted rather than described: a suite that ends the
    # same way whether it passed or failed has the numbers as its only sentinel.
    # Both directions are needed - the failing line must be the house spelling AND
    # the passing line must not be it, or a runner that always said SELFTEST FAILED
    # would pass the first half.
    _held = sys.stdout
    sys.stdout = io.StringIO()
    try:
        green_code = run(lambda c: c("x1 a green case", True))
        green = sys.stdout.getvalue()
        sys.stdout = io.StringIO()
        red_code = run(lambda c: c("x2 a red case", False))
        red = sys.stdout.getvalue()
    finally:
        sys.stdout = _held
    check("s3 the last line differs between a pass and a failure, and the failing "
          "one carries the house spelling: %r vs %r"
          % (green.strip().splitlines()[-1:], red.strip().splitlines()[-1:]),
          green.strip().endswith("ALL PASS: 1/1 cases passed")
          and red.strip().endswith("SELFTEST FAILED: 0/1 cases passed"))
    check("s4 ...and the exit codes agree with the two sentinels, so a caller that "
          "reads the code and a reader who reads the line cannot disagree",
          (green_code, red_code) == (0, 1))

    # The rule, over the real tree. This is the case that goes red if a tool goes
    # back to printing its own tally.
    live = hand_rolled_runners()
    check("s5 every tool hands its cases to the shared runner: %r" % (live,),
          live == [])

    _delegating = ("def _cases(check):\n"
                   "    check('d1 a case', True)\n"
                   "\n"
                   "def _selftest():\n"
                   "    from _suite import run\n"
                   "    return run(_cases)\n")
    check("s6 ...and that is not the rule finding nothing findable: the shape it "
          "accepts is the shape the tools are written in, and it accepts the other "
          "half of the pair being imported beside the runner",
          runner_problem(_delegating) is None
          and runner_problem(_delegating.replace("import run",
                                                 "import attempt, run")) is None)
    # THE SECOND DIRECTION, and the fixture is the old hand-rolled body verbatim in
    # miniature - the seven-way copy, including the sentinel that read the same
    # on both paths. A rule that accepted this would have accepted the tree as it
    # stood, which is what made this worth enforcing rather than a preference.
    _hand_rolled = ("def _cases():\n"
                    "    return [('d1 a case', True, 'why')]\n"
                    "\n"
                    "def _selftest():\n"
                    "    rows = _cases()\n"
                    "    bad = [r for r in rows if not r[1]]\n"
                    "    print('%s: %d/%d cases passed' % ('ALL PASS', 1, 1))\n"
                    "    return 1 if bad else 0\n")
    _hand_problem = runner_problem(_hand_rolled)
    check("s7 a tool that runs its own suite is reported, and the report names the "
          "line rather than only the file: %r" % (_hand_problem,),
          _hand_problem is not None and "line 5" in _hand_problem)
    check("s8 a `_selftest` that is only an import and no delegation is reported "
          "too - the shape a half-finished migration leaves behind, which would "
          "otherwise return None from a body every statement of which was legal",
          runner_problem("def _selftest():\n"
                         "    from _suite import run\n") is not None)
    check("s9 a module with NO `_selftest` is not this rule's finding - the sweep "
          "already fails a tool that prints no contract, and one defect wants one "
          "name", runner_problem("x = 1\n") is None)
    check("s10 a file that will not parse is REPORTED, never skipped: a scan that "
          "quietly drops a file it could not read is a clean answer about a file "
          "nobody looked at",
          (runner_problem("def _selftest(:\n") or "").startswith("does not parse"))

    # --- the removal, and the rule that keeps it reachable from here -----
    check("s11 `remove_tree` IS `_harness.remove_tree` IS `_output.remove_tree`, "
          "the same function object the suites under tests/ call - not a copy. "
          "This fact has one home, `scripts/_output.py`, which the sweep runner "
          "binds as well. A binding here is how a tool gets the answer without "
          "becoming another copy",
          remove_tree is _harness.remove_tree
          and remove_tree is _output.remove_tree)

    # The fixture is BOTH directions of the helper exclusion in one body: a removal
    # inside `def remove_tree` (which is what the helper is BUILT of) and a removal
    # outside it (which is the defect). A version that skipped the exclusion reports
    # both lines, so the fixture tells the two implementations apart instead of
    # merely exercising one.
    _removing = ("import shutil\n"
                 "\n"
                 "def build(root):\n"
                 "    run(['git', '-C', root, 'init', '-q'])\n"
                 "    run(['git', '-C', root, 'commit', '-m', 'seed'])\n"
                 "\n"
                 "def remove_tree(path):\n"
                 "    shutil.rmtree(path, ignore_errors=True)\n"
                 "\n"
                 "def drop(root):\n"
                 "    shutil.rmtree(root, ignore_errors=True)\n")
    _removing_lines = _bare_removal_lines(ast.parse(_removing),
                                          remove_tree.__name__)
    check("s12 the helper's OWN body is not one of its callers - the careful "
          "removal is built out of ordinary ones, and a rule that counted them "
          "would convict the answer it hands out. Both removals are in this "
          "fixture and only the one outside the helper is reported: %r"
          % (_removing_lines,),
          _removing_lines == [11])
    _removing_problem = removal_problem(_removing)
    check("s13 a tool that stages or commits into a repository and then removes a "
          "tree with a bare `shutil.rmtree` is REPORTED, and the report names the "
          "line and the way out rather than only the file: %r"
          % (_removing_problem,),
          _removing_problem is not None
          and "line(s) 11" in _removing_problem
          and remove_tree.__name__ in _removing_problem)

    # THE PAIR, AND THE MUTATION IT EXISTS FOR: a rule that fired on any repository
    # at all rather than on a WRITTEN one. It reads as vacuous - it asserts that
    # something is not reported - and it is the only case that goes red when the
    # object-verb half of the marker test is removed. Measured rather than assumed:
    # a bare initialisation leaves nothing without an owner-write bit, and a single
    # staged file leaves a read-only loose object.
    _init_only = _removing.replace(
        "    run(['git', '-C', root, 'commit', '-m', 'seed'])\n", "")
    check("s14 ...while a tool that only INITIALISES a repository and never writes "
          "an object into it is not reported: there is no read-only object under a "
          "repository nothing was staged into, so a plain removal is the right one "
          "and a finding here would be a demand with no failure behind it",
          "commit" not in _init_only and removal_problem(_init_only) is None)
    check("s15 a file that will not parse is REPORTED by this rule too, never "
          "skipped",
          (removal_problem("def drop(:\n") or "").startswith("does not parse"))

    # The rule over the real tree. This is the case that goes red the day a tool
    # that builds a repository goes back to removing it with a bare call.
    _live_removals = unsafe_removal_violations()
    check("s16 every tool that builds a repository removes it the one way that "
          "works on both platforms: %r" % (_live_removals,),
          _live_removals == [])

    # --- the same rule over tests/, one removal at a time ----------------------
    # A suite holds many fixtures in one function and reuses one name for them, so
    # the module-level question is not enough: each removal is answered for the
    # directory it removes. Every fixture below is a string for the reason the first
    # ones are.
    _written = ("import shutil\n"
                "import tempfile\n"
                "import _harness\n"
                "\n"
                "def _cases(check):\n"
                "    d = tempfile.mkdtemp()\n"
                "    try:\n"
                "        _harness.git(d, 'init', '-q')\n"
                "        _harness.git(d, 'add', '-A')\n"
                "    finally:\n"
                "        shutil.rmtree(d, ignore_errors=True)\n")
    _written_problem = removal_problem(_written)
    check("s17 a suite-shaped fixture - a directory initialised, STAGED into with "
          "git reached through a wrapper, and removed with `ignore_errors=True` in "
          "one function - is reported at the removal's line: %r"
          % (_written_problem,),
          _written_problem is not None and "line(s) 11. " in _written_problem)

    # THE PAIR THAT TELLS A PER-REMOVAL READING FROM A PER-MODULE ONE: the same
    # function reuses `d` for a second fixture that is only initialised, and holds a
    # third directory git never touched. A reading that convicted the module would
    # list all three removals; one that forgot the rebinding would list the second.
    _mixed = ("import shutil\n"
              "import tempfile\n"
              "import _harness\n"
              "\n"
              "def _cases(check):\n"
              "    d = tempfile.mkdtemp()\n"
              "    try:\n"
              "        _harness.git(d, 'init', '-q')\n"
              "        _harness.git(d, 'add', '-A')\n"
              "    finally:\n"
              "        shutil.rmtree(d, ignore_errors=True)\n"
              "    d = tempfile.mkdtemp()\n"
              "    try:\n"
              "        _harness.git(d, 'init', '-q')\n"
              "    finally:\n"
              "        shutil.rmtree(d, ignore_errors=True)\n"
              "    e = tempfile.mkdtemp()\n"
              "    shutil.rmtree(e, ignore_errors=True)\n")
    _mixed_problem = removal_problem(_mixed)
    check("s18 ...while an init-only fixture that REUSES the name, and a directory "
          "git never touched, beside it in the same module are not: only the "
          "staged one is named, which is what fails a rule that reads the module, "
          "or one that forgets a name was rebound: %r" % (_mixed_problem,),
          _mixed_problem is not None and "line(s) 11. " in _mixed_problem)

    _closure = ("import shutil\n"
                "import subprocess\n"
                "import tempfile\n"
                "\n"
                "def _cases(check):\n"
                "    repo = tempfile.mkdtemp()\n"
                "    def run_git(*argv):\n"
                "        return subprocess.run(['git'] + list(argv), cwd=repo)\n"
                "    try:\n"
                "        run_git('init', '-q')\n"
                "        run_git('add', '-A')\n"
                "    finally:\n"
                "        shutil.rmtree(repo, ignore_errors=True)\n"
                "\n"
                "def _elsewhere():\n"
                "    def run_git(*argv):\n"
                "        return None\n")
    check("s19 a git runner CLOSED OVER the directory is read through the directory "
          "it closes over, and an unrelated function's own `run_git` defined later "
          "does not hide it: %r" % (removal_problem(_closure),),
          "line(s) 13. " in (removal_problem(_closure) or ""))

    _built = ("import shutil\n"
              "import tempfile\n"
              "import _harness\n"
              "\n"
              "def _repo():\n"
              "    d = tempfile.mkdtemp()\n"
              "    _harness.git(d, 'init', '-q')\n"
              "    _harness.git(d, 'add', '-A')\n"
              "    return d\n"
              "\n"
              "def _cases(check):\n"
              "    root = _repo()\n"
              "    try:\n"
              "        pass\n"
              "    finally:\n"
              "        shutil.rmtree(root, ignore_errors=True)\n")
    _looped = _written.replace("        _harness.git(d, 'init', '-q')\n"
                               "        _harness.git(d, 'add', '-A')\n",
                               "        for argv in (['init', '-q'], ['add', '-A']):\n"
                               "            _harness.git(d, *argv)\n")
    check("s20 a fixture BUILT by a function that stages into it is reported at "
          "the caller's removal, and so is one staged through a verb held in a "
          "loop variable: %r / %r"
          % (removal_problem(_built), removal_problem(_looped)),
          "line(s) 16. " in (removal_problem(_built) or "")
          and "line(s) 11. " in (removal_problem(_looped) or "")
          and "for argv" in _looped)
    check("s21 a removal that does not pass `ignore_errors=True` raises on windows "
          "instead of staying silent, so it is not this rule's finding even over "
          "a staged directory: a rule that demanded the helper there would be "
          "convicting a loud failure",
          removal_problem(_written.replace(", ignore_errors=True", "")) is None)

    _scratch = _harness.fixture_root("suite-removal-")
    try:
        # Fixture file names are built, not written: a `.py` basename spelled in this
        # directory has to name a file that exists.
        _ext = "." + "py"
        _planted, _clean = "planted" + _ext, "clean" + _ext
        for _name, _text in ((_planted, _written), (_clean, "x = 1\n")):
            with io.open(os.path.join(_scratch, _name), "w", encoding="utf-8") as _fh:
                _fh.write(_text)
        _bare = unsafe_removal_violations(_scratch, "tests/", {})
        _excused = unsafe_removal_violations(_scratch, "tests/", {_planted: "x"})
        _stale = unsafe_removal_violations(
            _scratch, "tests/", {_planted: "x", _clean: "was fixed"})
    finally:
        _harness.remove_tree(_scratch)
    check("s22 the tests/ walk names the file with the `tests/` prefix, an exemption "
          "row silences exactly the file it names, and a row for a file the rule no "
          "longer convicts is a finding of its own: %r / %r / %r"
          % ([r for r, _p in _bare], _excused, [r for r, _p in _stale]),
          [r for r, _p in _bare] == ["tests/" + _planted] and _excused == []
          and [r for r, _p in _stale] == ["tests/" + _clean])
    _verb = ("import shutil\n"
             "import subprocess\n"
             "import tempfile\n"
             "import _harness\n"
             "\n"
             "def verb(proj, *argv):\n"
             "    return subprocess.run(['git', 'rev-parse'], cwd=proj)\n"
             "\n"
             "def _cases(check):\n"
             "    proj = tempfile.mkdtemp()\n"
             "    try:\n"
             "        _harness.git(proj, 'init', '-q')\n"
             "        verb(proj, 'add', 'x')\n"
             "    finally:\n"
             "        shutil.rmtree(proj, ignore_errors=True)\n")
    check("s24 a helper that merely RUNS git somewhere, handed a word that happens "
          "to be an object verb in another tool's vocabulary, is not a write: "
          "reading a callee's body for the git half would convict every suite "
          "that drives the plugin's own `add`: %r" % (removal_problem(_verb),),
          removal_problem(_verb) is None)
    _digits = ("import shutil\n"
               "import tempfile\n"
               "import _harness\n"
               "\n"
               "def _write_fixture(d, name, mode):\n"
               "    return None\n"
               "\n"
               "def _cases(check):\n"
               "    d = tempfile.mkdtemp()\n"
               "    try:\n"
               "        _harness.git(d, 'init', '-q')\n"
               "        _write_fixture(d, 'digits', 'add')\n"
               "    finally:\n"
               "        shutil.rmtree(d, ignore_errors=True)\n")
    check("s25 an init-only fixture followed by a call that carries the word `digits` "
          "and an `add` mode is not a write: git is matched as a WHOLE word (`git`, "
          "`run_git`, `git-dir`), and a substring match convicts every name that "
          "happens to contain those three letters: %r" % (removal_problem(_digits),),
          removal_problem(_digits) is None
          and removal_problem(_digits.replace("'digits'", "'git'")) is not None)
    _live_tests = unsafe_removal_violations(TESTS_DIR, "tests/", REMOVAL_EXEMPT)
    _unexempted = unsafe_removal_violations(TESTS_DIR, "tests/", {})
    check("s23 the live tests/ tree has no unexcused bare removal of a staged "
          "fixture, and the exemption table lists exactly the files the rule "
          "still convicts - no more, which would be a premise that stopped being "
          "true, and no fewer: %r / %r"
          % (_live_tests, [r for r, _p in _unexempted]),
          _live_tests == []
          and [r for r, _p in _unexempted]
          == ["tests/%s" % name for name in sorted(REMOVAL_EXEMPT)])

    # --- the rule: no relpath between a scratch path and a checkout path ----------
    # The planted sources are strings, so the rule is driven from text exactly as
    # `removal_problem` is. Windows is emulated with `ntpath`, which raises on
    # posix the way `os.path` raises there: the scratch directory sits on one
    # drive and the checkout on another.
    import ntpath
    _across = ("import os\n"
               "import tempfile\n"
               "import _output\n"
               "\n"
               "def _cases(check):\n"
               "    scratch = tempfile.mkdtemp()\n"
               "    here = os.path.join(_output.SCRIPTS_DIR, 'x.txt')\n"
               "    rel = os.path.relpath(here, scratch)\n"
               "    check('r1', rel)\n")
    _across_problem = relpath_problem(_across)
    try:
        ntpath.relpath("C:\\scratch\\x", "D:\\checkout")
        _nt_raises = False
    except ValueError:
        _nt_raises = True
    _nt_cross = rel_or_abs("C:\\scratch\\x", "D:\\checkout", ntpath)
    _nt_same = rel_or_abs("D:\\checkout\\a\\b.txt", "D:\\checkout", ntpath)
    check("s26 a relpath between a mkdtemp-derived path and a checkout path is "
          "named, with its line: %r" % (_across_problem,),
          _across_problem is not None and "line(s) 8." in _across_problem
          and "rel_or_abs" in _across_problem)
    check("s27 THE WINDOWS FACT, AND THE HELPER'S ANSWER: `ntpath.relpath` across "
          "C: and D: raises (%s), and `rel_or_abs` answers the absolute path in "
          "`/` spelling instead of raising, while a same-drive pair still comes "
          "back relative: %r / %r" % (_nt_raises, _nt_cross, _nt_same),
          _nt_raises and _nt_cross == "C:/scratch/x"
          and _nt_same == "a/b.txt"
          and rel_or_abs(os.path.join(REPO, "tools", "_suite.py"), REPO)
          == "tools/_suite.py")
    check("s28 the same pair routed through the helper is not a finding: %r"
          % (relpath_problem(_across.replace("os.path.relpath(here, scratch)",
                                             "rel_or_abs(here, scratch)")),),
          relpath_problem(_across.replace("os.path.relpath(here, scratch)",
                                          "rel_or_abs(here, scratch)")) is None)
    # Each of these has to be quiet, and each is the mutation of one wrong
    # implementation: a rule that convicted every relpath in a file that mentions
    # a scratch directory, or every one with a repo name beside it.
    _same_root = _across.replace("here = os.path.join(_output.SCRIPTS_DIR, 'x.txt')",
                                 "here = os.path.join(scratch, 'x.txt')")
    _both_repo = ("import os\n"
                  "import tempfile\n"
                  "import _output\n"
                  "\n"
                  "def _cases(check):\n"
                  "    scratch = tempfile.mkdtemp()\n"
                  "    rel = os.path.relpath(_output.SCRIPTS_DIR, _output.REPO_ROOT)\n"
                  "    check('r1', rel, scratch)\n")
    _unknown = ("import os\n"
                "\n"
                "def inside(path, start):\n"
                "    return os.path.relpath(path, start)\n")
    check("s29 ALLOW CASES - a pair under ONE scratch root, a pair of checkout "
          "paths in a file that also makes a scratch directory, and a call whose "
          "sides arrive as parameters are not findings: %r / %r / %r"
          % (relpath_problem(_same_root), relpath_problem(_both_repo),
             relpath_problem(_unknown)),
          relpath_problem(_same_root) is None and relpath_problem(_both_repo) is None
          and relpath_problem(_unknown) is None)
    _posix_form = _across.replace("os.path.relpath(here, scratch)",
                                  "_output.posix_rel(scratch, here)")
    _one_arg = ("import os\n"
                "import tempfile\n"
                "\n"
                "def _cases(check):\n"
                "    d = tempfile.mkdtemp()\n"
                "    rel = os.path.relpath(os.path.join(d, 'm.json'))\n"
                "    check('r1', rel)\n")
    check("s30 the other spellings: `posix_rel`, which is `os.path.relpath` with "
          "the separators respelled and raises the same way, and the one-argument "
          "call, whose start is the working directory - the checkout when the "
          "suite is run by hand: %r / %r"
          % (relpath_problem(_posix_form), relpath_problem(_one_arg)),
          "line(s) 8." in (relpath_problem(_posix_form) or "")
          and "line(s) 6." in (relpath_problem(_one_arg) or ""))
    _via_helper_def = ("import os\n"
                       "import _harness\n"
                       "import _output\n"
                       "\n"
                       "def _mini_repo(prefix):\n"
                       "    return _harness.fixture_root(prefix)\n"
                       "\n"
                       "def _cases(check):\n"
                       "    own = os.path.join(_output.SCRIPTS_DIR, 'a.txt')\n"
                       "    repo = _mini_repo('p-')\n"
                       "    rel = os.path.relpath(os.path.realpath(own),\n"
                       "                          os.path.realpath(repo))\n"
                       "    check('r1', rel)\n")
    _unpacked = ("import os\n"
                 "import tempfile\n"
                 "import _output\n"
                 "\n"
                 "def _cases(check):\n"
                 "    def project():\n"
                 "        d = tempfile.mkdtemp()\n"
                 "        return d, os.path.join(d, 'm.json')\n"
                 "    d1, m1 = project()\n"
                 "    rel = os.path.relpath(m1, _output.REPO_ROOT)\n"
                 "    check('r1', rel)\n")
    check("s31 a scratch directory that arrives through a local function, the "
          "shape `_mini_repo()` has and the one that failed on windows, and one "
          "that arrives through a tuple unpacking, are followed: %r / %r"
          % (relpath_problem(_via_helper_def), relpath_problem(_unpacked)),
          "line(s) 11." in (relpath_problem(_via_helper_def) or "")
          and "line(s) 10." in (relpath_problem(_unpacked) or "")
          and (relpath_problem("def f(:\n") or "").startswith("does not parse"))
    _env_store = ("import os\n"
                  "import _harness\n"
                  "import _output\n"
                  "\n"
                  "def _cases(check):\n"
                  "    os.environ['ROOT'] = _output.REPO_ROOT\n"
                  "    scratch = _harness.fixture_root('p-')\n"
                  "    rel = os.path.relpath(_output.SCRIPTS_DIR, os.path.realpath(scratch))\n"
                  "    check('r1', rel)\n")
    check("s32 a subscript target (`os.environ[k] = ...`) holds the name `os` and "
          "binds nothing: read as a binding, it made every later `os.path` side a "
          "checkout path as well, a scratch side became mixed, and a call such as "
          "this one went unnamed: %r" % (relpath_problem(_env_store),),
          "line(s) 8." in (relpath_problem(_env_store) or ""))
    _live_relpaths = unsafe_relpath_violations()
    check("s33 no tool under tools/ makes a path relative between a scratch "
          "directory and the checkout: %r" % (_live_relpaths,),
          _live_relpaths == [])
    _live_suite_relpaths = unsafe_relpath_violations(TESTS_DIR, "tests/")
    check("s34 ...and no suite under tests/ does either - the half that "
          "convicted the gate suite's foreign-status block and a one-argument "
          "call whose start is the working directory: %r"
          % (_live_suite_relpaths,),
          _live_suite_relpaths == [])


def _selftest():
    return run(_cases)


if __name__ == "__main__":
    _output.safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _suite.py --selftest\n")
    raise SystemExit(2)
