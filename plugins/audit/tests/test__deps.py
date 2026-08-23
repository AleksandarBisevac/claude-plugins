#!/usr/bin/env python3
"""
The cases for `_deps.py`, moved out of it - the import-graph lint, scanning a
tree that now holds this file too.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

NOT ONE OF THE UNMOVABLE SHAPES IS PRESENT HERE, and that was measured rather than
hoped: an AST pass over the block before it moved found no `globals()`/`vars()`, no
`__file__`, no `sys.modules[__name__]`, no three-argument `getattr`, and no
`src.split(a)[1].split(b)[0]`. What it has instead is the hazard this batch is named
for - most of its cases are assertions about the REAL tree, and the real tree now
contains the suite making them. Three of those are worth knowing by name:

  * `tb7` / `tb8` - the `tests/` boundary. `tb7` requires that nothing under
    `scripts/` or `hooks/` reaches into `tests/`, and this file's arrival cannot
    change that: `tests_import_violations()` reads the PRODUCT and never the test
    tree. `tb8` intersects `LAYERS` with every `tests/**.py` BASENAME, so it now reads
    `test__deps` among them - and `test__deps` is not a layer name, which is exactly
    what it asserts.
  * `e1` and `n1` - `guide_enumeration()` and `navigability_violations()` are scoped
    to `scripts/` + `hooks/` and stay so. `tests/` owes the guide ONE section, not one
    per file, and a widened scope would demand forty-eight.

THE SUBJECT'S OWN ANCHORS RATHER THAN `_harness.SCRIPTS_DIR` AND ITS SIBLINGS. They
are the same three directories, and the choice is not cosmetic: these cases ask what
the lint scans BY DEFAULT (`r5` reads the module list `layer_violations()` would read
with no argument; `f4` hands it the real `scripts/` while swapping the hooks half for a
fixture). Respelling them off the harness would quietly turn a claim about the subject's
own default into a claim about two paths that happen to agree today. They used to be
`_deps`' own `_HERE` / `_HOOKS_DIR` / `_TESTS_DIR`, three constants it derived from its
own `__file__`; the module now reads them off the single anchor in `_output`, and
reaching them THROUGH the subject keeps each case pointed at what the subject actually
resolves rather than at a second copy of the same walk.

ONE ODDITY IS PRESERVED RATHER THAN TIDIED. `m2` passes `hooks_dir=tmp`, and `tmp` at
that point names the fixtures directory the block above already removed in its
`finally`. It is harmless - a hooks directory that does not exist contributes no
violations, and `m2` asks only whether the upward edge is still caught - but it is not
what a reader would guess. The label and the behaviour are unchanged; the observation
is recorded here rather than fixed inside a migration.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402  (as _deps imports it)
import _deps as M                                  # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil
    import tempfile

    # ------------------------------------------------------------- real tree, green cases
    real_edges, real_broken = M.import_graph()
    real_violations = M.layer_violations()
    by_what = lambda needle: [v for v in real_violations if needle in v[1]]  # noqa: E731

    check("r1 the real scripts/ tree is acyclic: %r" % (real_violations,),
          not by_what("import cycle"))
    _downward = tuple(sorted(by_what("not strictly downward")))
    _new = [v for v in _downward if v not in M.KNOWN_LAYER_DEBT]
    _gone = [v for v in M.KNOWN_LAYER_DEBT if v not in _downward]
    check("r2 the not-strictly-downward edges are EXACTLY the %d recorded in "
          "KNOWN_LAYER_DEBT. A new one fails here; RETIRING one fails here too, "
          "until its entry is deleted on purpose - the list may only shrink, and "
          "only deliberately. new=%r retired=%r"
          % (len(M.KNOWN_LAYER_DEBT), _new, _gone),
          not _new and not _gone)
    check("r3 every real scripts/*.py file is assigned a layer, and LAYERS carries no "
          "stale entry: %r" % (real_violations,),
          not by_what("not assigned a layer") and not by_what("stale table entry"))
    check("r4 every real scripts/*.py file parses: %r" % (real_broken,), not real_broken)

    # Read the RAW hooks scan directly as well as through layer_violations(). The raw list
    # is what NAMES an offender; the filtered one is what a build reads. They were two
    # different facts while an allow-list sat between them, and the point of removing it is
    # that they are now one - so both are asserted, and a suppression reintroduced anywhere
    # in between makes exactly one of them fail.
    real_modules, real_collisions = M._module_files(M._output.SCRIPTS_DIR)
    real_on_disk = set(real_modules)
    real_hooks_raw = [(f, m) for f, m in M._hooks_scripts_imports(M._output.HOOKS_DIR,
                                                                 real_on_disk)
                      if m is not None]
    check("r5 hooks/ statically imports nothing from scripts/ AT ALL - no allow-list, no "
          "documented exception, because the one there was is fixed (F11): a hook runs on "
          "every tool call from a process that may not have scripts/ on its path, so every "
          "scripts/-owned feature is loaded by path and treated as optional: %r"
          % (real_hooks_raw,),
          real_hooks_raw == [])
    check("r5b ...and layer_violations() says the same thing rather than filtering it - the "
          "raw scan and the reported one are one fact now, not two",
          not by_what("imports scripts module"))

    check("r6 real edge count is positive - a checker that finds zero edges on a tree "
          "this size is reading the wrong directory, not a clean graph: %d"
          % len(real_edges), len(real_edges) > 0)

    real_static, real_runtime, _rb = M._scan_edges()
    check("r7 the `_loader` runtime edges are actually being READ, and they are edges "
          "the import walk does not already have (%d runtime, %d static, %d runtime-only): "
          "every entry point in this tree is hyphenated and therefore cannot be reached "
          "by an `import` statement at all, so a scan that finds none of them here is "
          "reading static imports only - the state in which r2 certified this tree while "
          "seeing a fraction of it"
          % (len(real_runtime), len(real_static), len(real_runtime - real_static)),
          real_runtime and (real_runtime - real_static))

    real_hook_modules = {}
    real_hook_collisions = []
    if os.path.isdir(M._output.HOOKS_DIR):
        real_hook_modules, real_hook_collisions = M._module_files(M._output.HOOKS_DIR)
    real_hook_names = set(real_hook_modules)
    check("r8 no hooks/**.py basename collides with a scripts/**.py one. The runtime-load "
          "rule reads a literal's BASENAME and ignores its directory (audit-doctor loads "
          "`../hooks/_config.py` and `../hooks/guard-capabilities.py` by path), so the "
          "day both directories carry the same filename a hooks load would be recorded "
          "as a scripts edge. That precondition is asserted here rather than assumed in "
          "a comment: %r" % (sorted(real_hook_names & real_on_disk),),
          not (real_hook_names & real_on_disk))
    check("r8b ...and no basename collides WITHIN either directory either. Both scans "
          "are recursive now, so `usage/core.py` beside `panel/core.py` is a shape the "
          "tree can take - and it would be one node in the graph wearing two files' "
          "edges, and one ambiguous name for `guide_enumeration` to match on. scripts=%r "
          "hooks=%r" % (real_collisions, real_hook_collisions),
          not real_collisions and not real_hook_collisions)

    # -------------------------------------------------------- render: format + determinism
    render_a = M.render()
    render_b = M.render()
    check("d1 --render is deterministic: two calls on the same tree are byte-identical",
          render_a == render_b)
    check("d2 the rendered map names every layer this module defines",
          all(("L%d:" % i) in render_a for i in range(len(M.LAYERS))))
    check("d3 the rendered map ends with a trailing newline (clean CLI output)",
          render_a.endswith("\n") and not render_a.endswith("\n\n"))

    # ----------------------------------------------------- fixtures: each violation named
    tmp = tempfile.mkdtemp(prefix="audit-deps-")
    try:
        # a cycle: two files that import each other.
        cyc = os.path.join(tmp, "cycle")
        os.makedirs(cyc)
        with open(os.path.join(cyc, "a.py"), "w", encoding="utf-8") as fh:
            fh.write("import b\n")
        with open(os.path.join(cyc, "b.py"), "w", encoding="utf-8") as fh:
            fh.write("import a\n")
        cyc_layers = (("a",), ("b",))  # a table that would (wrongly) call this acyclic
        hits = M.layer_violations(cyc, hooks_dir=tmp, layers=cyc_layers)
        cyc_hits = [v for v in hits if v[1].startswith("import cycle")]
        check("f1 a real import cycle is named as a cycle, with the path in the message",
              len(cyc_hits) == 1 and "a" in cyc_hits[0][1] and "b" in cyc_hits[0][1])

        # an upward import: the lower layer imports the higher one.
        up = os.path.join(tmp, "upward")
        os.makedirs(up)
        with open(os.path.join(up, "low.py"), "w", encoding="utf-8") as fh:
            fh.write("import high\n")
        with open(os.path.join(up, "high.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        up_layers = (("low",), ("high",))  # low is BELOW high; low importing high is up
        up_hits = M.layer_violations(up, hooks_dir=tmp, layers=up_layers)
        up_named = [v for v in up_hits if v[0] == "low.py"
                    and "not strictly downward" in v[1]]
        check("f2 an upward import (a lower layer importing a higher one) is named, "
              "with both layer numbers in the message: %r" % (up_hits,),
              len(up_named) == 1 and "layer 0" in up_named[0][1]
              and "layer 1" in up_named[0][1])

        # an unassigned file: on disk, absent from LAYERS.
        unassigned = os.path.join(tmp, "unassigned")
        os.makedirs(unassigned)
        with open(os.path.join(unassigned, "known.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        with open(os.path.join(unassigned, "orphan.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        orphan_layers = (("known",),)
        orphan_hits = M.layer_violations(unassigned, hooks_dir=tmp, layers=orphan_layers)
        check("f3 a file on disk with no LAYERS entry is named as unassigned: %r"
              % (orphan_hits,),
              any(v == ("orphan.py", "on disk but not assigned a layer in LAYERS")
                  for v in orphan_hits))
        stale_layers = (("known",), ("ghost",))
        stale_hits = M.layer_violations(unassigned, hooks_dir=tmp, layers=stale_layers)
        check("f3b a LAYERS entry with no file on disk is named as stale, the other "
              "direction of the same drift: %r" % (stale_hits,),
              any(v[0] == "ghost.py" and "stale table entry" in v[1]
                  for v in stale_hits))

        # hooks importing a scripts module: the banned direction.
        hooksfix = os.path.join(tmp, "hooksfix")
        os.makedirs(hooksfix)
        with open(os.path.join(hooksfix, "sneaky.py"), "w", encoding="utf-8") as fh:
            fh.write("import _fmt\n")  # _fmt is a real scripts/ module name
        with open(os.path.join(hooksfix, "_config.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")  # a hook's own sibling, never flagged
        hook_hits = M.layer_violations(script_dir=M._output.SCRIPTS_DIR, hooks_dir=hooksfix)
        check("f4 hooks/*.py importing a real scripts/ module name is named, with the "
              "hook file and the module both in the message: %r" % (hook_hits,),
              any(v == ("sneaky.py", "imports scripts module _fmt - hooks must not "
                        "depend on scripts") for v in hook_hits))
        check("f5 a hook importing its OWN sibling (_config) is not flagged - only a "
              "real scripts/ module name is banned",
              not any(v[0] == "_config.py" and "imports scripts module" in v[1]
                      for v in hook_hits))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------- runtime loads: the `_loader` call shapes
    # The edges the graph could not see AT ALL until now. Every shape below was read off
    # the real tree first (`_loader.load_script("x.py")`, the `_ldr` alias in
    # validate-config.py's selftest, the three `_load(...)` wrappers, and the one call
    # whose target is bound to a name before the call) - a fixture invented from the same
    # head that wrote the parser proves only that the head is self-consistent.
    rt = tempfile.mkdtemp(prefix="audit-deps-runtime-")
    try:
        rt_hooks = os.path.join(rt, "hooks")  # empty; the hooks pass is not under test
        os.makedirs(rt_hooks)
        rt_src = os.path.join(rt, "scripts")
        os.makedirs(rt_src)

        def _rt_write(name, body):
            with open(os.path.join(rt_src, name), "w", encoding="utf-8") as fh:
                fh.write(body)

        # No _loader.py in the fixture, on purpose: if `_loader` were a sibling here,
        # `import _loader` would ALSO be a static edge and these cases could pass on the
        # import walk alone, proving nothing about the call walk.
        _rt_write("high.py", "pass\n")
        _rt_write("bottom.py", "pass\n")
        _rt_write("low.py",
                  "import _loader\n"
                  "def go():\n"
                  "    return _loader.load_script('high.py', modname='high')\n")
        _rt_write("aliased.py",
                  "import _loader as _ldr\n"
                  "def go():\n"
                  "    return _ldr.load(os.path.join(_HERE, 'high.py'), modname='high')\n")
        _rt_write("wrapped.py",
                  "import _loader\n"
                  "def _load(name, filename):\n"
                  "    return _loader.load_script(filename, modname=name)\n"
                  "def go():\n"
                  "    return _load('high', 'high.py')\n")
        _rt_write("computed.py",
                  "import _loader\n"
                  "TARGET = 'high.py'\n"
                  "def go():\n"
                  "    return _loader.load_script(TARGET)\n")
        _rt_write("top.py",
                  "import _loader\n"
                  "def go():\n"
                  "    return _loader.load_script('bottom.py', modname='bottom')\n")
        # low/aliased/wrapped/computed sit BELOW high; top sits ABOVE bottom. One table
        # carries both directions so a single call has to get both of them right.
        rt_layers = (("aliased", "bottom", "computed", "low", "wrapped"),
                     ("high", "top"))
        rt_hits = M.layer_violations(rt_src, hooks_dir=rt_hooks, layers=rt_layers)
        rt_by_file = lambda name: [v for v in rt_hits if v[0] == name]  # noqa: E731

        check("rt1 a runtime `_loader.load_script('high.py')` from a LOWER layer is named "
              "as an upward edge - the whole class of edge the import-only walk could not "
              "see - and the message says runtime-loads, not imports, because there is no "
              "import line for the reader to go and find: %r" % (rt_hits,),
              len([v for v in rt_by_file("low.py")
                   if "runtime-loads high (layer 1) from layer 0" in v[1]]) == 1)

        check("rt2 the alias form (`import _loader as _ldr`, which validate-config.py's "
              "selftest really uses) is seen, and so is a literal nested inside an "
              "`os.path.join(...)` argument - the shape `_panel_state` and `audit-doctor` "
              "spell most of their loads with: %r" % (rt_hits,),
              len([v for v in rt_by_file("aliased.py")
                   if "runtime-loads high" in v[1]]) == 1)

        check("rt3 a local wrapper that forwards a caller-chosen filename is followed to "
              "its CALL SITE, where the filename is actually spelled - without this the "
              "~12 `_load(...)` sites across the doctor's six check modules are "
              "invisible: %r" % (rt_hits,),
              len([v for v in rt_by_file("wrapped.py")
                   if "runtime-loads high" in v[1]]) == 1)

        check("rt4 a target that is not a literal IN the call (bound to a name first) is "
              "NOT guessed at. The documented limitation, asserted so it stays a decision "
              "on record; it is also the OTHER-direction case, going red the day detection "
              "is widened to 'any .py literal anywhere in the file', which would invent "
              "edges out of error messages and docstrings: %r" % (rt_hits,),
              rt_by_file("computed.py") == [])

        check("rt5 control: a LEGAL downward runtime load (top -> bottom) is left alone. "
              "The rule fires on DIRECTION, not on the presence of a load, and this is "
              "the only case that goes red if it ever becomes unconditional - which would "
              "flag every one of the ~13 correct downward loads in the real tree: %r"
              % (rt_hits,), rt_by_file("top.py") == [])

        # ---- mutation proof: the pre-change graph must MISS these same fixtures ----
        # The graph as it stood before the runtime pass existed: edges from `ast.Import` /
        # `ast.ImportFrom` only. Everything else is today's code - including the recursive
        # `_module_files` walk - so exactly ONE variable is removed and a red rt6 can only
        # be about that one. It reports nothing at all here, which is precisely how it
        # reported nothing on a real tree carrying twenty-one bad edges.
        def _static_only_layer_violations(script_dir, layers):
            names, _dupes = M._module_files(script_dir)
            found = []
            for mod in sorted(names):
                rel, path = names[mod][0]
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=rel)
                for imported in M._imported_sibling_names(tree, set(names), mod):
                    li = M._layer_of(mod, layers)
                    lj = M._layer_of(imported, layers)
                    if li is not None and lj is not None and not (li > lj):
                        found.append((mod + ".py", "imports %s - not strictly downward"
                                      % imported))
            return found

        weak_rt_hits = _static_only_layer_violations(rt_src, rt_layers)
        check("rt6 mutation proof: with the runtime pass removed (the static-import walk "
              "this change replaced, and nothing else changed with it), the SAME three "
              "fixtures rt1-rt3 catch are "
              "missed ENTIRELY - red here proves those three cases test something real "
              "rather than passing however the check were written: %r" % (weak_rt_hits,),
              weak_rt_hits == [])

        rt_again = M.layer_violations(rt_src, hooks_dir=rt_hooks, layers=rt_layers)
        check("rt7 mutation proof: the real, unweakened check still catches all THREE - "
              "counted, not merely found, so a version that spots one upward load and "
              "drops the other two cannot pass this; nothing was left mutated behind: %r"
              % (rt_again,),
              len([v for v in rt_again if "runtime-loads" in v[1]]) == 3)
    finally:
        shutil.rmtree(rt, ignore_errors=True)

    # ---------------------------------------------- a wrapper shared across files
    # `_doctor_report._load` is defined in one module and CALLED from six, so the
    # `_loader` import and the `.py` literal live in different files. Reading one
    # tree at a time sees neither half as an edge, which is the shape a lint can be
    # "configured, green and structurally blind" in.
    bw = tempfile.mkdtemp(prefix="deps-borrow-")
    try:
        bw_src = os.path.join(bw, "scripts")
        bw_hooks = os.path.join(bw, "hooks")
        os.makedirs(bw_src)
        os.makedirs(bw_hooks)

        def _bw_write(name, body):
            with open(os.path.join(bw_src, name), "w", encoding="utf-8") as fh:
                fh.write(body)

        _bw_write("high.py", "pass\n")
        _bw_write("bottom.py", "pass\n")
        # The wrapper's own file names nothing: it has the `_loader` import and no
        # `.py` literal at all, so it must contribute NO edge of its own.
        _bw_write("basemod.py",
                  "import _loader\n"
                  "def _load(name, filename):\n"
                  "    return _loader.load_script(filename, modname=name)\n")
        # ...and three ways to reach it, all of which the real tree spells.
        _bw_write("aliaser.py",
                  "import basemod\n"
                  "_load = basemod._load\n"
                  "def go():\n"
                  "    return _load('high', 'high.py')\n")
        _bw_write("fromer.py",
                  "from basemod import _load\n"
                  "def go():\n"
                  "    return _load('high', 'high.py')\n")
        _bw_write("attrer.py",
                  "import basemod as _b\n"
                  "def go():\n"
                  "    return _b._load('high', 'high.py')\n")
        # The control: the same alias, calling it with a literal that names NO
        # sibling. A rule that fired on the wrapper rather than on its argument
        # would invent an edge here.
        _bw_write("innocent.py",
                  "import basemod\n"
                  "_load = basemod._load\n"
                  "def go():\n"
                  "    return _load('cfg', '../hooks/_config.py')\n")
        # THREE layers, not two: the wrapper's home has to sit BELOW its
        # borrowers or the plain `import basemod` is itself a same-layer
        # violation and the fixture reports noise beside the edge it is about.
        bw_layers = (("basemod", "bottom"),
                     ("aliaser", "attrer", "fromer", "innocent"), ("high",))
        bw_hits = M.layer_violations(bw_src, hooks_dir=bw_hooks,
                                     layers=bw_layers)
        bw_by = lambda name: [v for v in bw_hits if v[0] == name]  # noqa: E731

        for spelling, name in (("`_load = basemod._load`", "aliaser.py"),
                               ("`from basemod import _load`", "fromer.py"),
                               ("`basemod._load(...)`", "attrer.py")):
            check("bw1-%s a wrapper borrowed as %s is followed to the call site in "
                  "the BORROWING file, where the `.py` literal is: %r"
                  % (name[0], spelling, bw_hits),
                  len([v for v in bw_by(name)
                       if "runtime-loads high (layer 2) from layer 1" in v[1]]) == 1)

        check("bw2 the file that DEFINES the wrapper contributes no edge - it "
              "names no target, and attributing its callers' loads to it would "
              "put every one of them on the wrong module: %r" % (bw_hits,),
              bw_by("basemod.py") == [])

        check("bw3 a borrowed wrapper handed a hooks/ filename is NOT an edge. "
              "The rule fires on what the literal NAMES, not on the wrapper: the "
              "doctor really does load `../hooks/_config.py` through this "
              "wrapper, and reading that as a scripts/ sibling would invent an "
              "edge: %r" % (bw_hits,), bw_by("innocent.py") == [])

        # ---- mutation proof: the pre-change scan must MISS all three ----
        bw_modules, _bw_dupes = M._module_files(bw_src)
        bw_names = set(bw_modules)
        blind = []
        for mod in sorted(bw_modules):
            rel, path = bw_modules[mod][0]
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            # `wrapper_map` omitted: exactly the call the scan made before this
            # change, and nothing else varied.
            blind.extend((mod, t) for t in
                         M._runtime_loaded_sibling_names(tree, bw_names, mod))
        check("bw4 mutation proof: with the wrapper map withheld - the scan as it "
              "stood, one tree at a time - the same three fixtures are missed "
              "ENTIRELY. Red here is what proves bw1 tests something real: %r"
              % (blind,), blind == [])

        seeing = []
        bw_trees = {}
        for mod in sorted(bw_modules):
            rel, path = bw_modules[mod][0]
            with open(path, "r", encoding="utf-8") as fh:
                bw_trees[mod] = ast.parse(fh.read(), filename=rel)
        bw_map = M._wrapper_map(bw_trees)
        for mod in sorted(bw_trees):
            seeing.extend((mod, t) for t in M._runtime_loaded_sibling_names(
                bw_trees[mod], bw_names, mod, bw_map))
        check("bw5 ...and the real, unweakened scan catches all THREE - counted, "
              "so a version that follows one spelling and drops the other two "
              "cannot pass; nothing was left mutated behind: %r" % (seeing,),
              sorted(seeing) == [("aliaser", "high"), ("attrer", "high"),
                                 ("fromer", "high")])

        check("bw6 the map itself says which names each module can be called "
              "through, and it grows to a FIXPOINT: `aliaser` borrowed `_load` "
              "and therefore IS a place a fourth module could borrow it from, "
              "which a two-pass version would not record: %r" % (bw_map,),
              bw_map["basemod"] == set(["_load"])
              and bw_map["aliaser"] == set(["_load"])
              and bw_map["high"] == set())
    finally:
        shutil.rmtree(bw, ignore_errors=True)

    # ------------------------------------------------------- the guide's location
    # `_guide_path()` counted three `..` segments off this module's own directory,
    # which was `_deps.py`'s depth written into a constant. It reads
    # `_output.REPO_ROOT` now, and on a flat tree the two must name the same file:
    # compared by normpath, because the old spelling carried its `..` segments
    # right through into the string.
    _old_guide = os.path.join(M._output.SCRIPTS_DIR, "..", "..", "..",
                              "PLUGIN-BUILD-GUIDE.md")
    check("gp1 _guide_path() resolves to the file the old three-deep `..` walk "
          "resolved to, and it is really there: %r" % (M._guide_path(),),
          M._guide_path() == os.path.normpath(_old_guide)
          and os.path.isfile(M._guide_path()))
    check("gp2 ...and an explicit argument still wins, so every map_drift case "
          "below can point the lint at a fixture",
          M._guide_path("/nowhere/x.md") == "/nowhere/x.md")

    # --------------------------------------------------- map_drift: guide vs --render output
    check("g1 the shipped guide's module map fence matches `_deps.py --render` "
          "byte-for-byte right now - the house 'a doc block must match the code's own "
          "statement' pattern `_areas.rule_drift()` uses, applied to this generated "
          "block: %r" % (M.map_drift(),), not M.map_drift())

    # ---------------------------------------------- hooks_rule_drift: guide vs the rule
    # The generated map has a byte lint; the SENTENCE beside it had nothing, and that is
    # how the guide went on naming an exception (`hooks/_config.py`'s guarded
    # `import _manifest_io`) that no longer exists. Both halves are asserted against
    # fixtures below, because a lint that only requires the sentence is green for a
    # document that states the rule and then takes it back in the next clause.
    check("g0 the shipped guide states the hooks rule and claims no exception to it: %r"
          % (M.hooks_rule_drift(),), not M.hooks_rule_drift())

    rule_tmp = tempfile.mkdtemp(prefix="audit-deps-rule-")
    try:
        silent_path = os.path.join(rule_tmp, "no-rule.md")
        with open(silent_path, "w", encoding="utf-8") as fh:
            fh.write("# guide\n\nhooks are lovely and nothing is said about imports.\n")
        silent_hits = M.hooks_rule_drift(silent_path)
        check("g0a a guide that never states the rule is drift: %r" % (silent_hits,),
              len(silent_hits) == 1 and "does not state" in silent_hits[0][1])

        excuse_path = os.path.join(rule_tmp, "excused.md")
        with open(excuse_path, "w", encoding="utf-8") as fh:
            fh.write("# guide\n\n...and " + M._GUIDE_HOOKS_RULE + ". One known "
                     "pre-existing exception (`hooks/_config.py`'s guarded "
                     "`import _manifest_io`) is named rather than papered over.\n")
        excuse_hits = M.hooks_rule_drift(excuse_path)
        check("g0b ...and so is a guide that states it and then carves an allowance out "
              "of it - which is exactly what shipped until F11, with the sentence above "
              "it correct the whole time: %r" % (excuse_hits,),
              len(excuse_hits) == 1 and "still describes an exception" in excuse_hits[0][1])

        missing_rule_path = os.path.join(rule_tmp, "gone.md")
        check("g0c an unreadable guide is reported, not treated as a clean one",
              [p for _, p in M.hooks_rule_drift(missing_rule_path) if "unreadable" in p])
    finally:
        shutil.rmtree(rule_tmp, ignore_errors=True)

    guide_tmp = tempfile.mkdtemp(prefix="audit-deps-guide-")
    try:
        real_render = M.render()

        stale_path = os.path.join(guide_tmp, "stale.md")
        with open(stale_path, "w", encoding="utf-8") as fh:
            fh.write("intro\n\n" + M._GUIDE_HEADING + "\n\nsome text\n\n```\n"
                     + real_render[:-2] + "X\n```\n\nmore text\n")  # one byte changed
        stale_hits = M.map_drift(stale_path)
        check("g2 a fenced block one byte off from the real `render()` output is named "
              "as stale, not silently accepted: %r" % (stale_hits,),
              len(stale_hits) == 1 and stale_hits[0][0] == stale_path
              and "does not match" in stale_hits[0][1])

        no_heading_path = os.path.join(guide_tmp, "no_heading.md")
        with open(no_heading_path, "w", encoding="utf-8") as fh:
            fh.write("intro\n\n## something else entirely\n\n```\n" + real_render + "```\n")
        no_heading_hits = M.map_drift(no_heading_path)
        check("g3 a guide missing the module-map heading entirely is named, not "
              "mistaken for a match: %r" % (no_heading_hits,),
              len(no_heading_hits) == 1
              and "heading" in no_heading_hits[0][1]
              and "not found" in no_heading_hits[0][1])

        no_fence_path = os.path.join(guide_tmp, "no_fence.md")
        with open(no_fence_path, "w", encoding="utf-8") as fh:
            fh.write("intro\n\n" + M._GUIDE_HEADING + "\n\nno fence follows this heading "
                     "at all, just prose.\n")
        no_fence_hits = M.map_drift(no_fence_path)
        check("g4 a guide with the heading but no fenced block after it is named as "
              "missing the fence, distinctly from a stale-content mismatch: %r"
              % (no_fence_hits,),
              len(no_fence_hits) == 1
              and "no fenced code block" in no_fence_hits[0][1])

        missing_path = os.path.join(guide_tmp, "does_not_exist.md")
        missing_hits = M.map_drift(missing_path)
        check("g5 an unreadable guide path is named as unreadable, not crashed on: %r"
              % (missing_hits,),
              len(missing_hits) == 1 and "unreadable" in missing_hits[0][1])

        # ---- mutation proof: a weakened comparison must MISS the g2 stale fixture ----
        # Same idea as m1/m2 below: a version of the comparison that only checks the
        # block is non-empty (instead of comparing it to `render()`) would let g2's
        # one-byte-off fixture through clean - proving g2 is testing something real.
        def _weakened_map_drift(guide_path):
            path = M._guide_path(guide_path)
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            if M._GUIDE_HEADING not in text:
                return [(path, "heading not found")]
            block = M._fenced_block_after(text, M._GUIDE_HEADING)
            if block is None:
                return [(path, "no fenced code block")]
            return [] if block else [(path, "empty block")]  # never compares to render()

        weak_stale_hits = _weakened_map_drift(stale_path)
        check("g6 mutation proof: with the byte-for-byte comparison to `render()` "
              "removed, the SAME one-byte-stale fixture g2 catches is missed entirely "
              "(red proves g2 is testing something real): %r" % (weak_stale_hits,),
              not weak_stale_hits)
        real_stale_hits = M.map_drift(stale_path)
        check("g7 mutation proof: the real, unweakened map_drift() still catches it - "
              "nothing was left mutated behind",
              real_stale_hits and "does not match" in real_stale_hits[0][1])
    finally:
        shutil.rmtree(guide_tmp, ignore_errors=True)

    # ------------------------------------------------------- mutation proof: upward edge
    # Same idea _fmt.py's own selftest proves with a hand-mutated formatter: a weakened
    # version of the check (here, one that simply never looks at layer numbers) must MISS
    # the fixture the real function catches - proving f2 above is testing something real,
    # not a case that would pass however the check were (mis)written.
    mut_dir = tempfile.mkdtemp(prefix="audit-deps-mutant-")
    try:
        with open(os.path.join(mut_dir, "low.py"), "w", encoding="utf-8") as fh:
            fh.write("import high\n")
        with open(os.path.join(mut_dir, "high.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        mut_layers = (("low",), ("high",))

        def _weakened_layer_violations(script_dir, layers):
            # The upward-edge pass, deliberately dropped - everything else kept, so the
            # only thing this proves red is the check f2 depends on.
            edges, _broken = M.import_graph(script_dir)
            found = []
            cycle = M._find_cycle(edges)
            if cycle:
                found.append((cycle[0] + ".py", "import cycle: " + " -> ".join(cycle)))
            return found

        weak_hits = _weakened_layer_violations(mut_dir, mut_layers)
        check("m1 mutation proof: with the upward-edge check removed, the SAME fixture "
              "that f2 catches is missed entirely (red proves the case can fail): %r"
              % (weak_hits,), not weak_hits)
        real_hits = M.layer_violations(mut_dir, hooks_dir=tmp, layers=mut_layers)
        check("m2 mutation proof: the real, unweakened check still catches it - nothing "
              "was left mutated behind",
              any("not strictly downward" in v[1] for v in real_hits))
    finally:
        shutil.rmtree(mut_dir, ignore_errors=True)

    # ------------------------------------------ guide_enumeration: real guide + fixtures
    check("e1 the real, shipped guide names no scripts/hooks .py file missing from "
          "either the directory tree or a section-2 heading right now: %r"
          % (M.guide_enumeration(),), not M.guide_enumeration())

    enum_tmp = tempfile.mkdtemp(prefix="audit-deps-enum-")
    try:
        hk_dir = os.path.join(enum_tmp, "hooks")  # empty; no hooks fixtures needed here
        os.makedirs(hk_dir)

        src_a = os.path.join(enum_tmp, "scripts_a")
        os.makedirs(src_a)
        with open(os.path.join(src_a, "present.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        with open(os.path.join(src_a, "no_section.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")

        complete_guide = os.path.join(enum_tmp, "complete.md")
        with open(complete_guide, "w", encoding="utf-8") as fh:
            fh.write(
                "intro\n\n" + M._TREE_HEADING + "\n\n```\n"
                "  present.py    # a file\n"
                "  no_section.py # another file\n"
                "```\n\n" + M._SECTION2_HEADING + "\n\n"
                "### `present.py`\nprose.\n\n"
                "## 3. Next section\nnot part of section 2.\n"
            )
        complete_hits = M.guide_enumeration(complete_guide, script_dir=src_a,
                                            hooks_dir=hk_dir)
        check("e2 a file present in the tree but absent from every section-2 heading "
              "is named as missing its section, and ONLY that: %r" % (complete_hits,),
              complete_hits == [("no_section.py",
                                 "no '### ' heading in '%s' mentions it"
                                 % M._SECTION2_HEADING)])

        src_b = os.path.join(enum_tmp, "scripts_b")
        os.makedirs(src_b)
        with open(os.path.join(src_b, "present.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        with open(os.path.join(src_b, "no_tree.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")

        no_tree_guide = os.path.join(enum_tmp, "no_tree.md")
        with open(no_tree_guide, "w", encoding="utf-8") as fh:
            fh.write(
                "intro\n\n" + M._TREE_HEADING + "\n\n```\n"
                "  present.py    # a file\n"
                "```\n\n" + M._SECTION2_HEADING + "\n\n"
                "### `present.py`\nprose.\n\n"
                "### `no_tree.py`\nprose.\n\n"
                "## 3. Next section\nnot part of section 2.\n"
            )
        no_tree_hits = M.guide_enumeration(no_tree_guide, script_dir=src_b,
                                           hooks_dir=hk_dir)
        check("e3 a file present in every section-2 heading but absent from the tree "
              "is named as missing from the tree, and ONLY that: %r" % (no_tree_hits,),
              no_tree_hits == [("no_tree.py",
                                "missing from the '%s' tree" % M._TREE_HEADING)])

        # ---- mutation proof: a weakened check must MISS the e3 tree-only fixture ----
        def _weakened_guide_enumeration(guide_path):
            with open(guide_path, "r", encoding="utf-8") as fh:
                text = fh.read()
            section2 = M._section_text(text, M._SECTION2_HEADING)
            headings = (re.findall(r"^### .*$", section2, re.M)
                        if section2 is not None else [])
            found = []
            for rel, _kind, _path in M._real_source_files(src_b, hk_dir):
                base = os.path.basename(rel)
                if not any(base in h for h in headings):  # tree check dropped entirely
                    found.append((rel, "no section heading"))
            return found

        weak_hits = _weakened_guide_enumeration(no_tree_guide)
        check("e4 mutation proof: with the tree-coverage check removed, the SAME "
              "tree-missing fixture e3 catches is missed entirely (red proves e3 is "
              "testing something real): %r" % (weak_hits,),
              not any(f == "no_tree.py" for f, _ in weak_hits))
        real_hits_again = M.guide_enumeration(no_tree_guide, script_dir=src_b,
                                              hooks_dir=hk_dir)
        check("e5 mutation proof: the real, unweakened guide_enumeration() still "
              "catches it - nothing was left mutated behind",
              any(f == "no_tree.py" for f, _ in real_hits_again))
    finally:
        shutil.rmtree(enum_tmp, ignore_errors=True)

    # --------------------------------------------------- navigability_violations
    check("n1 the real tree's long files (>= %d lines) all carry at least 2 "
          "non-selftest section headers - navigability is enforced, not just "
          "declared, with no exceptions left on record: %r"
          % (M._NAV_MIN_LINES, M.navigability_violations()),
          not M.navigability_violations())

    nav_tmp = tempfile.mkdtemp(prefix="audit-deps-nav-")
    try:
        nav_hooks = os.path.join(nav_tmp, "hooks")  # empty; no hooks fixture needed
        os.makedirs(nav_hooks)
        long_path = os.path.join(nav_tmp, "long_file.py")
        with open(long_path, "w", encoding="utf-8") as fh:
            fh.write("pass\n" * (M._NAV_MIN_LINES + 10))
        nav_hits = M.navigability_violations(nav_tmp, hooks_dir=nav_hooks)
        check("n2 a long file with no section headers at all is named as a "
              "navigability violation: %r" % (nav_hits,),
              any(f == "long_file.py" for f, _ in nav_hits))

        # ---- mutation proof: a weakened check must MISS the n2 fixture ----
        def _weakened_navigability_violations(script_dir, hooks_dir):
            return []  # the header-count check removed entirely

        weak_nav_hits = _weakened_navigability_violations(nav_tmp, nav_hooks)
        check("n3 mutation proof: with the header-count check removed, the SAME "
              "headerless-file fixture n2 catches is missed entirely (red proves "
              "n2 is testing something real): %r" % (weak_nav_hits,),
              not any(f == "long_file.py" for f, _ in weak_nav_hits))
        real_nav_hits_again = M.navigability_violations(nav_tmp, hooks_dir=nav_hooks)
        check("n4 mutation proof: the real, unweakened navigability_violations() "
              "still catches it - nothing was left mutated behind",
              any(f == "long_file.py" for f, _ in real_nav_hits_again))

        # ---- a docstring QUOTING the house style is not a section header ----
        # The two files differ in exactly one thing: where the marker lines sit. Same
        # characters, same column, same count - one inside a string, one in real
        # comments - so a check that passes both is reading text and a check that
        # separates them is reading tokens.
        _marker_lines = "# --- reading ---\n# --- writing ---\n"
        _prose_only = ('"""\nWhy this file exists.\n\nHouse style for a long module '
                       'is two top-level markers, spelled\n%s\nso a reader scanning '
                       'the left margin has landmarks.\n"""\n'
                       % _marker_lines) + "pass\n" * M._NAV_MIN_LINES
        _real_markers = _marker_lines + "pass\n" * M._NAV_MIN_LINES
        with open(os.path.join(nav_tmp, "prose_only.py"), "w",
                  encoding="utf-8") as fh:
            fh.write(_prose_only)
        with open(os.path.join(nav_tmp, "real_markers.py"), "w",
                  encoding="utf-8") as fh:
            fh.write(_real_markers)
        nav_prose = M.navigability_violations(nav_tmp, hooks_dir=nav_hooks)
        check("n5 a long file whose only `# --- name ---` lines sit INSIDE its module "
              "docstring carries zero section headers and is named - a docstring "
              "showing the house style is a mention, not a landmark: %r" % (nav_prose,),
              [w for f, w in nav_prose if f == "prose_only.py"]
              == ["%d lines but only 0 non-selftest section header(s) "
                  "(# --- name ---); needs >= 2 to be navigable"
                  % (_prose_only.count("\n"),)])
        check("n6 ...while the file carrying the SAME two marker lines as real "
              "comments is not reported, which is what tells n5 apart from a rule "
              "that stopped counting headers altogether",
              not any(f == "real_markers.py" for f, _ in nav_prose))

        # ---- mutation proof: the line scan this replaced cannot separate them ----
        def _line_scanned_navigability(text):
            return len([1 for line in text.splitlines(True)
                        if M._NAV_HEADER_RE.match(line)
                        and M._NAV_HEADER_RE.match(line).group(1).strip()
                        != "selftest"])

        check("n7 mutation proof: the line-matching form this replaced counts the "
              "docstring's two markers as two headers and reads the prose_only "
              "fixture as navigable - red proves n5 tests the tokens, not the text",
              _line_scanned_navigability(_prose_only) == 2
              and _line_scanned_navigability(_real_markers) == 2)
        check("n8 mutation proof: the real, token-reading form separates the two - "
              "nothing was left mutated behind: %r"
              % (M._section_header_names(_prose_only),),
              M._section_header_names(_prose_only) == []
              and M._section_header_names(_real_markers) == ["reading", "writing"])

        # ---- a file that will not tokenize is named, never skipped ----
        with open(os.path.join(nav_tmp, "broken.py"), "w", encoding="utf-8") as fh:
            fh.write("def (\n" + "pass\n" * M._NAV_MIN_LINES)
        nav_broken = M.navigability_violations(nav_tmp, hooks_dir=nav_hooks)
        check("n9 a long file that will not tokenize is reported as such rather than "
              "skipped - a scan that passes over a file it could not read is claiming "
              "a clean answer about it: %r" % (nav_broken,),
              any(f == "broken.py" and "does not tokenize" in w
                  for f, w in nav_broken)
              and M._section_header_names("def (\n") is None)

        # ---- F44: and a file that will not OPEN is named on the same argument ----
        # The tokenize branch has reported its file since F21; the READ branch was
        # a bare `continue` beside it, so this function disagreed with its own
        # docstring and an unreadable file came back looking navigable. The
        # fixture is a real mis-encoded asset rather than a chmod, because the
        # windows CI leg cannot make a file unreadable by permission.
        with open(os.path.join(nav_tmp, "mojibake.py"), "wb") as fh:
            fh.write(b"# \xff\xfe not utf-8\n" + b"pass\n" * M._NAV_MIN_LINES)
        nav_unread = M.navigability_violations(nav_tmp, hooks_dir=nav_hooks)
        check("n10 a .py that will not DECODE is named, not skipped (F44) - the "
              "sibling ui rule swallowed exactly this and so did this branch, "
              "which made 'could not read it' print identically to 'nothing "
              "wrong with it': %r"
              % ([w for f, w in nav_unread if f == "mojibake.py"],),
              any(f == "mojibake.py" and "unreadable" in w
                  for f, w in nav_unread))
        check("n11 ...and the clean fixtures beside it are still not named, so "
              "n10 is not passing because the scan started reporting everything",
              not any(f == "real_markers.py" for f, _ in nav_unread))
    finally:
        shutil.rmtree(nav_tmp, ignore_errors=True)

    # ------------------------------------------------ ui_navigability_violations
    check("u1 the real scripts/ui/ assets (>= %d lines) all carry one section "
          "marker per %d lines - the four files that hold the entire report and "
          "panel UI were unchecked by anything until now: %r"
          % (M._NAV_MIN_LINES, M._NAV_MIN_LINES, M.ui_navigability_violations()),
          not M.ui_navigability_violations())

    ui_tmp = tempfile.mkdtemp(prefix="audit-deps-uinav-")
    try:
        def _write(name, body):
            with open(os.path.join(ui_tmp, name), "w", encoding="utf-8") as fh:
                fh.write(body)

        _JS_MARK = "// --- one -------------------------------------------------\n"
        _CSS_MARK = "/* ---- one ---------------------------------------------- */\n"

        _write("bare.js", "x();\n" * (M._NAV_MIN_LINES + 10))
        ui_hits = M.ui_navigability_violations(ui_tmp)
        check("u2 a long .js with no section markers at all is named as a ui "
              "navigability violation: %r" % (ui_hits,),
              any(f == "bare.js" for f, _ in ui_hits))

        # ---- mutation proof: a weakened check must MISS the u2 fixture ----
        def _weakened_ui_navigability_violations(ui_dir):
            return []  # the marker-count check removed entirely

        weak_ui_hits = _weakened_ui_navigability_violations(ui_tmp)
        check("u3 mutation proof: with the marker-count check removed, the SAME "
              "markerless-file fixture u2 catches is missed entirely (red proves "
              "u2 is testing something real): %r" % (weak_ui_hits,),
              not any(f == "bare.js" for f, _ in weak_ui_hits))
        check("u4 mutation proof: the real, unweakened ui_navigability_violations() "
              "still catches it - nothing was left mutated behind",
              any(f == "bare.js" for f, _ in M.ui_navigability_violations(ui_tmp)))

        # ---- the density is what does the work, not the floor of 2 ----
        _write("thin.css", _CSS_MARK * 2 + ("a{b:c}\n" * (M._NAV_MIN_LINES * 2 + 50)))
        thin_hits = M.ui_navigability_violations(ui_tmp)
        check("u5 a 900-line asset carrying exactly 2 markers is still named - a "
              "flat 'at least 2' rule (what the .py lint asks) would pass it, so "
              "this is the case that proves the DENSITY is doing the work: %r"
              % (thin_hits,),
              any(f == "thin.css" for f, _ in thin_hits))

        # ---- the other direction: the rule must not fire on a well-marked file.
        # Looks vacuous and is the only case that goes red if the density is ever
        # tightened into something no real asset can satisfy.
        _write("ok.css", _CSS_MARK * 2 + ("a{b:c}\n" * (M._NAV_MIN_LINES - 100)))
        _write("short.js", "x();\n" * 100)
        ok_hits = M.ui_navigability_violations(ui_tmp)
        check("u6 control: a long asset with enough markers, and a short one with "
              "none, are both left alone - the rule fires on too few markers for "
              "the length, not on length or on markers alone: %r" % (ok_hits,),
              not any(f in ("ok.css", "short.js") for f, _ in ok_hits))

        _write("panel.html", "<div>\n" * (M._NAV_MIN_LINES + 10))
        check("u7 an extension with no marker syntax on record (.html) is skipped "
              "rather than guessed at",
              not any(f == "panel.html" for f, _ in M.ui_navigability_violations(ui_tmp)))

        # ---- the hole this rule keeps, pinned as a decision (F37) ----
        # A marker is a matched LINE, so a marker-shaped line inside a template
        # literal counts as a section marker. `tokenize` is what closed the same
        # hole in the .py rule (F21) and there is no stdlib tokenizer for CSS or
        # JavaScript; the argument, and the cheap tightening that was measured
        # and rejected, are above `_UI_MARKER_RES`.
        #
        # The two fixtures differ by NOTHING except those two lines inside the
        # backticks, which is what stops this from asserting "a file passes":
        # the same body without them IS reported, so the pass is caused by the
        # fake markers and by nothing else.
        #
        # IF THIS CASE GOES RED, THE HOLE WAS CLOSED. Delete the case on purpose
        # - do not weaken it back into green.
        _stringy_body = "x();\n" * (M._NAV_MIN_LINES + 10)
        _write("stringy.js", "const doc = `\n" + _JS_MARK + _JS_MARK + "`;\n"
               + _stringy_body)
        _write("nostring.js", _stringy_body)
        hole_hits = M.ui_navigability_violations(ui_tmp)
        check("u8 KNOWN BLINDNESS, pinned rather than fixed: two marker-shaped "
              "lines inside a template literal are counted as section markers, so "
              "stringy.js passes while nostring.js - the identical body without "
              "them - is named. A regex cannot tell a comment from a string and "
              "neither language has a stdlib tokenizer (F37): %r" % (hole_hits,),
              not any(f == "stringy.js" for f, _ in hole_hits)
              and any(f == "nostring.js" for f, _ in hole_hits))
    finally:
        shutil.rmtree(ui_tmp, ignore_errors=True)

    # ---- why the column-0 tightening was rejected, measured on the real asset ----
    # Why the marker rule allows up to two leading spaces. The report's script
    # body is wrapped, so every line in it is indented and so is every section
    # marker; a column-0 rule would count none of them. Measured from the shipped
    # regex against the shipped parts rather than from a literal, so the day the
    # body stops being wrapped this reports it.
    _js_marker_re = dict(M._UI_MARKER_RES)[".js"]
    _report_dir = os.path.join(M._UI_DIR, "report")
    _report_parts = sorted(n for n in os.listdir(_report_dir)
                           if n.endswith(".js"))
    _report_lines = []
    for _n in _report_parts:
        with open(os.path.join(_report_dir, _n), "r", encoding="utf-8") as fh:
            _report_lines.extend(fh.readlines())
    _marked = [ln for ln in _report_lines if _js_marker_re.match(ln)]
    _at_col0 = [ln for ln in _marked if not ln.startswith(" ")]
    check("u9 the report's script body indents every section marker, because the "
          "whole body runs inside one wrapper: %d line(s) across %d part(s), %d "
          "marker(s), %d of them at column 0. A column-0 rule would therefore "
          "count none of them and fail the best-marked source in the directory, "
          "which is why the leading-space allowance exists. If the body is ever "
          "unwrapped and its markers reach column 0, this goes red and the "
          "stricter rule becomes available"
          % (len(_report_lines), len(_report_parts), len(_marked), len(_at_col0)),
          len(_report_parts) >= 2 and len(_marked) >= 2 and not _at_col0)

    # ---- F44: the two quiet answers this function used to give ------------------
    # The marker hole u8 pins is a DECISION - closing it costs a hand-rolled lexer
    # for two languages. These two were never a decision: an asset nothing could
    # read came back as an asset with nothing wrong, and a missing scripts/ui/ -
    # the whole report and panel UI gone - printed exactly what a clean tree
    # prints. Both are the direction F21 named as the one that hurts.
    f44_tmp = tempfile.mkdtemp(prefix="audit-deps-f44-")
    try:
        with open(os.path.join(f44_tmp, "mojibake.js"), "wb") as fh:
            fh.write(b"// \xff\xfe not utf-8\n" + b"x();\n" * M._NAV_MIN_LINES)
        with open(os.path.join(f44_tmp, "fine.js"), "w", encoding="utf-8") as fh:
            fh.write("x();\n" * 10)
        f44_hits = M.ui_navigability_violations(f44_tmp)
        check("u10 an asset that will not DECODE is named, never swallowed (F44): %r"
              % (f44_hits,),
              any(f == "mojibake.js" and "unreadable" in w for f, w in f44_hits))
        check("u11 ...and the readable asset beside it is not named, which is what "
              "tells u10 apart from a rule that started reporting every file",
              not any(f == "fine.js" for f, _ in f44_hits))
    finally:
        shutil.rmtree(f44_tmp, ignore_errors=True)

    _f44_gone = M.ui_navigability_violations(os.path.join(f44_tmp, "vanished"))
    check("u12 a ui_dir that cannot be LISTED returns a NAMED finding, not the "
          "empty list a clean directory returns (F44). `return []` there meant "
          "'scripts/ui/ is missing' and 'every asset is navigable' printed the "
          "same way, and the missing directory is the whole report and panel "
          "UI: %r" % (_f44_gone,),
          len(_f44_gone) == 1 and "unlistable" in _f44_gone[0][1])
    check("u13 ...and the real directory still returns [] - the case that goes "
          "red if u12's repair turned into 'always report something'",
          M.ui_navigability_violations() == [])

    # --------------------------------------------------- one concern, one home
    _sc = M.shared_concern_violations()
    check("sc1 no registered shared concern has spread past its allowance: %r"
          % (_sc,), _sc == [])
    # The check on the check. Every row's live count is computed here so an empty
    # violation list cannot mean "the needles stopped matching". A row whose live
    # count is 0 AND whose home is None would be a needle that found nothing
    # anywhere, which is the shape a typo takes.
    _live = [(c, sum(n for _f, n in M._concern_hits(M._UI_DIR, home, needle)), allowed)
             for c, home, needle, allowed, _w in M.SHARED_CONCERNS]
    _dead = [(c, n, a) for c, n, a in _live if a > 0 and n == 0]
    check("sc2 ...and that verdict is over needles that still match - %r; a row "
          "allowing copies while finding none is a needle that has stopped "
          "working, and it would read exactly like a clean tree (dead: %r)"
          % (_live, _dead), not _dead)
    # A HOME used to imply an allowance of zero, and that held while every homed
    # row was fully extracted. The table-header row broke it honestly: fourteen of
    # fifteen sites reach the helper, and the fifteenth builds an empty <thead>
    # and fills it on every redraw - a different job, which forcing through the
    # helper for this lint's sake would be the tail wagging the dog. So a residual
    # is allowed and must be DECLARED here, which is what stops "extracted, with
    # an exception" from quietly becoming "extracted, with several".
    _RESIDUAL = {"table header construction", "select option loop"}
    _homed = [(c, a) for c, home, _n, a, _w in M.SHARED_CONCERNS if home is not None]
    _undeclared = sorted(c for c, a in _homed if a > 0 and c not in _RESIDUAL)
    _stale = sorted(c for c, a in _homed if a == 0 and c in _RESIDUAL)
    check("sc3 an EXTRACTED concern allows nothing outside its home, unless its "
          "residual is declared here - undeclared %r, and %r declared a residual "
          "it no longer has" % (_undeclared, _stale),
          not _undeclared and not _stale
          and any(home is not None for _c, home, _n, _a, _w in M.SHARED_CONCERNS))
    check("sc4 every row carries a reason, because a bare number in this table "
          "is a number nobody can re-derive the intent of",
          all(isinstance(why, str) and len(why) > 40
              for _c, _h, _n, _a, why in M.SHARED_CONCERNS))
    # sc2 can only vouch for a row that still ALLOWS copies: it calls a live count
    # of 0 a dead needle, which is right for an unextracted row and wrong for an
    # extracted one, where 0 is the goal. So an extracted row whose needle stopped
    # matching reads exactly like a clean tree - the failure this whole registry
    # exists to prevent, one level up.
    #
    # Each needle is therefore pointed at a sample that MUST match and one that
    # must not. Hand-kept, and a row with no sample fails rather than being
    # skipped, because a skipped row is the same silence.
    _SAMPLES = {
        "blob download": ("const u=URL.createObjectURL(b);", "revokeObjectURL(u)"),
        "web storage": ("localStorage.setItem(k,v)", "storageSet(k,v)"),
        "pluralisation": ("' change'+(n===1?'':'s')", "plural(n,'change')"),
        # The four that made this needle a regex: a space follows the paren in
        # `dParse(s) + 6 * DAY` too, so only what comes NEXT tells them apart.
        "literal (s) pluralisation": ("' row(s) match everything'",
                                      "dIso(dParse(s) + 6 * DAY)"),
        "clipboard copy": ("navigator.clipboard.writeText(t)", "copyText(t)"),
        "table header construction": ("el('thead',{},el('tr',{}))",
                                      "tableHead(['a','b'])"),
        "day <-> milliseconds": ("const d=ms/864e5;", "const d=ms/DAY_MS;"),
        "save confirmation": ("toast('nothing to save - x')", "confirmSave({})"),
        "theme token walk": ("const now=tVal(name,mode),was=b(name,mode);",
                             "TMODES.forEach(mode=>{ drawCell(mode); });"),
        "select option loop": ("if(cur===v)o.selected=true;",
                               "fillOptions(sel, pairs, cur)"),
        "heatmap calendar": ("function startOf(g, d) { return d; }",
                             "periodStart(g, d)"),
        # The miss sample is a CALL, because every surface still calls heatRows -
        # a needle that fired on the call would report the two readers this row
        # exists to permit.
        "heatmap row shapes": ("function weekdayRows(lo, hi) { return []; }",
                               "heatRows(g, win, days, hoursOf)"),
        "caret restore": ("n.setSelectionRange(caret,caret)",
                          "restoreCaret(n,caret,back)"),
        # The miss sample carries BOTH halves this needle had to separate: the
        # repaired sort, which reads a rank the server computed, AND the innocent
        # lookalike it must not fire on - a form control whose value for an
        # absent tier is an empty string, which decides no order at all.
        "phase execution order": (
            "ordered.sort((a,b)=>(a.priority==null?1:0)-(b.priority==null?1:0))",
            "prio.value=ph.priority==null?'':String(ph.priority);"
            "ordered.sort((a,b)=>a.porder-b.porder)"),
    }
    _missing = [c for c, _h, _n, _a, _w in M.SHARED_CONCERNS if c not in _SAMPLES]
    check("sc12 every row has a sample its needle is checked against - a row "
          "without one would be a needle nothing proves can fire: %r" % (_missing,),
          not _missing and len(_SAMPLES) == len(M.SHARED_CONCERNS))
    _blind, _noisy = [], []
    for _c, _h, _needle, _a, _w in M.SHARED_CONCERNS:
        _hit, _miss = _SAMPLES.get(_c, ("", ""))
        _count = M._needle_counter(_needle)
        if _count(_hit) < 1:
            _blind.append((_c, _needle, _hit))
        if _count(_miss) > 0:
            _noisy.append((_c, _needle, _miss))
    check("sc13 ...and each needle FIRES on the convention it names (blind: %r)"
          % (_blind,), not _blind)
    check("sc14 ...and does NOT fire on the repaired form, or on the calls that "
          "merely look like it (noisy: %r)" % (_noisy,), not _noisy)
    # It is a CAP, not an equality, and that is the entire difference between this
    # registry and the three save/discard counts retired in 9f73b22: those
    # required the duplication to stay, so removing a copy turned them red.
    _slack_fixture = tempfile.mkdtemp(prefix="audit-deps-sc-")
    try:
        os.makedirs(os.path.join(_slack_fixture, "shared"))
        with open(os.path.join(_slack_fixture, "shared", "x.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("// nothing here\n")
        _empty = M.shared_concern_violations(_slack_fixture)
        check("sc5 a tree with NO copies of anything is not a violation - removing "
              "a duplicate must never fail this lint, or it forbids its own "
              "remedy exactly as the retired counts did (%r)" % (_empty,),
              _empty == [])
        _slack = M.shared_concern_slack(_slack_fixture)
        check("sc6 ...and the freed allowance is REPORTED instead, so the table "
              "cannot quietly become a column of numbers nobody re-derived: %r"
              % (_slack,),
              sorted(c for c, _n, _a in _slack)
              == sorted(c for c, _h, _n, a, _w in M.SHARED_CONCERNS if a > 0))
        # A comment is not an implementation. This is the false positive that
        # would make the lint hostile: the paragraph explaining a concern would be
        # reported as a second copy of it.
        with open(os.path.join(_slack_fixture, "shared", "y.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("// localStorage.getItem is what this file does NOT do\n"
                     "/* URL.createObjectURL, also only in prose */\n"
                     "const ok = 1;\n")
        check("sc7 a comment naming a concern is not a copy of it - three checks "
              "in this repo have already been tripped by prose, and a registry "
              "that counted comments would punish documenting the rule (%r)"
              % (M.shared_concern_violations(_slack_fixture),),
              M.shared_concern_violations(_slack_fixture) == [])
        # ...and the same text in CODE is caught, which is what stops sc7 from
        # being "the lint sees nothing".
        with open(os.path.join(_slack_fixture, "shared", "z.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("const u = URL.createObjectURL(b);\n")
        _caught = M.shared_concern_violations(_slack_fixture)
        check("sc8 mutation proof: the SAME text as real code IS caught, and "
              "named with the file and the count - %r" % (_caught,),
              len(_caught) == 1 and _caught[0][0] == "blob download"
              and "z.js" in _caught[0][4])
    finally:
        shutil.rmtree(_slack_fixture, ignore_errors=True)

    # The comment scanner, pinned on the three constructs that actually appear in
    # `ui/` and that broke the two-regex version. Each is a real line from the
    # tree, reduced: a `//` comment containing `/*`, a string containing `//`, and
    # a regex literal containing a quote. The direction of every failure here is
    # UNDER-counting, which reads as "no duplication".
    _co = [
        ("// a note about .claude/themes/*.json\nreal();\n", "real();",
         "a /* inside a LINE comment must not open a block comment - it did, and "
         "swallowed 150 lines of appearance-view.js including a real occurrence"),
        ("const NS='http://www.w3.org/2000/svg';\nkeep();\n", "keep();",
         "a // inside a STRING must not start a comment - which is why stripping "
         "line comments first is not the fix either"),
        ("const q=/[\",\\r\\n]/;\nkeep2();\n", "keep2();",
         "a quote inside a REGEX literal must not open a string; three of these "
         "ship in ui/ as CSV quoters"),
        ("/* block\n * spanning\n */ after();\n", "after();",
         "and a real block comment is still removed"),
    ]
    for _src, _want, _why in _co:
        check("sc9 comment scanner: %s" % (_why,), _want in M._code_only(_src))
    check("sc10 ...and the scanner keeps line numbers, so a scout reporting a hit "
          "sends a reader to the right line: a three-line block comment leaves "
          "three newlines behind",
          M._code_only("/* a\n b\n */x;\n").count("\n") == 3)
    # The other direction: it must still REMOVE comments, or sc7 passes for the
    # wrong reason.
    check("sc11 a needle that appears ONLY in a comment is not counted, and the "
          "same needle in code is - the pair is what makes sc7 mean anything",
          "URL.createObjectURL" not in M._code_only("// URL.createObjectURL\n")
          and "URL.createObjectURL" in M._code_only("x=URL.createObjectURL(b);\n"))

    # ------------------------------------------- the scanners reach a subdirectory
    # A recursive walk that is never handed a subdirectory proves nothing, so this
    # builds one. Every scanner in this module used a flat `os.listdir`, which is
    # why `CONTRIBUTING.md` had to forbid a `.py` below scripts/ or hooks/: the file
    # did not fail anything, it stopped being scanned and said so nowhere. The
    # fixture puts the offence one level down in each direction - an upward edge in
    # `scripts/usage/`, a banned hooks->scripts import in `hooks/nested/` - and the
    # clean second direction beside each of them.
    rec = tempfile.mkdtemp(prefix="audit-deps-rec-")
    try:
        rec_scripts = os.path.join(rec, "scripts")
        rec_hooks = os.path.join(rec, "hooks")
        for _d in (rec_scripts, rec_hooks,
                   os.path.join(rec_scripts, "usage"),
                   os.path.join(rec_scripts, "panel"),
                   os.path.join(rec_hooks, "nested")):
            os.makedirs(_d)

        def _rec_write(*parts):
            body = parts[-1]
            with open(os.path.join(rec, *parts[:-1]), "w", encoding="utf-8") as fh:
                fh.write(body)

        _rec_write("scripts", "flat_low.py", "pass\n")
        _rec_write("scripts", "high.py", "pass\n")
        # One directory down and UPWARD: L0 reaching L1. The offence.
        _rec_write("scripts", "usage", "core.py", "import high\n")
        # One directory down and DOWNWARD: L1 reaching L0. Legal, and must stay legal.
        _rec_write("scripts", "panel", "clean.py", "import flat_low\n")
        # A hook one directory down importing a scripts module that is ITSELF only
        # findable one directory down - both walks have to work for this to be named.
        _rec_write("hooks", "nested", "sneaky.py", "import core\n")
        _rec_write("hooks", "nested", "fine.py", "import os\n")
        rec_layers = (("core", "flat_low"), ("clean", "high"))

        rec_modules, rec_collisions = M._module_files(rec_scripts)
        rec_map = dict((name, [rel for rel, _p in entries])
                       for name, entries in rec_modules.items())
        check("w1 the scripts walk descends into subdirectories, keys each file by its "
              "BASENAME (the only name `import` or `_loader` can spell) and remembers the "
              "relative path to report it by: %r" % (rec_map,),
              rec_map == {"clean": ["panel/clean.py"], "core": ["usage/core.py"],
                          "flat_low": ["flat_low.py"], "high": ["high.py"]})

        rec_hits = sorted(M.layer_violations(rec_scripts, hooks_dir=rec_hooks,
                                             layers=rec_layers))
        check("w2 the whole violation list is EXACTLY the two offences, one from a "
              "scripts file one directory down and one from a hooks file one directory "
              "down, each NAMED BY ITS RELATIVE PATH rather than by a bare basename the "
              "reader would have to go hunting for. Counted as a whole list, not found "
              "one at a time, so a walk that sees one of the two cannot pass: %r"
              % (rec_hits,),
              rec_hits == [
                  ("nested/sneaky.py",
                   "imports scripts module core - hooks must not depend on scripts"),
                  ("usage/core.py",
                   "imports high (layer 1) from layer 0 - not strictly downward")])
        check("w3 ...and the second direction, which w2's exact list already carries and "
              "this states out loud: a LEGAL downward import from `panel/clean.py`, and a "
              "hook one level down importing only stdlib, are both left alone. Living in "
              "a folder is not the offence - it never was: %r" % (rec_hits,),
              not any(f in ("panel/clean.py", "nested/fine.py") for f, _w in rec_hits))

        rec_edges, rec_broken = M.import_graph(rec_scripts)
        check("w4 a file one directory down is the node `core`, not `usage/core` - the "
              "name every real edge in this tree is spelled with. Pinned because the "
              "alternative silently matches nothing: %r %r" % (rec_edges, rec_broken),
              rec_edges == [("clean", "flat_low"), ("core", "high")] and not rec_broken)

        # ---- mutation proof: the flat scan this replaced misses both offences ----
        def _flat_relnames(directory):
            """The `os.listdir` these scanners used to call: one level, no walk."""
            return sorted(f for f in os.listdir(directory) if f.endswith(".py"))

        def _flat_layer_violations(script_dir, hooks_dir, layers):
            # `layer_violations()` with ONE thing swapped back - the recursive walk
            # returns to the flat listing. The edge walk, the layer comparison and the
            # hooks rule are all the real ones, so an empty result here is about file
            # discovery and nothing else.
            names = dict((f[:-3], os.path.join(script_dir, f))
                         for f in _flat_relnames(script_dir))
            found = []
            for mod in sorted(names):
                with open(names[mod], "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=mod)
                for imported in M._imported_sibling_names(tree, set(names), mod):
                    li = M._layer_of(mod, layers)
                    lj = M._layer_of(imported, layers)
                    if li is not None and lj is not None and not (li > lj):
                        found.append((mod + ".py",
                                      "imports %s (layer %d) from layer %d - not "
                                      "strictly downward" % (imported, lj, li)))
            for fname in _flat_relnames(hooks_dir):
                with open(os.path.join(hooks_dir, fname), "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=fname)
                for imported in M._imported_sibling_names(tree, set(names), None):
                    found.append((fname, "imports scripts module %s - hooks must not "
                                  "depend on scripts" % imported))
            return found

        weak_rec_hits = _flat_layer_violations(rec_scripts, rec_hooks, rec_layers)
        check("w5 mutation proof: with the walk swapped back for the flat `os.listdir` "
              "it replaced, BOTH offences w2 catches are missed entirely - the scan "
              "returns %r and %r and reports a clean tree. That is the exact failure "
              "`CONTRIBUTING.md`'s old flat-files rule existed to avoid: %r"
              % (_flat_relnames(rec_scripts), _flat_relnames(rec_hooks), weak_rec_hits),
              weak_rec_hits == [])
        rec_again = M.layer_violations(rec_scripts, hooks_dir=rec_hooks, layers=rec_layers)
        check("w6 mutation proof: the real, unweakened check still names both - each "
              "KIND counted separately, so a version that finds the scripts one and "
              "drops the hooks one cannot pass here. Counting the list length alone "
              "would not do it: a flat scan turns those same two files into two "
              "'stale table entry' violations and lands on 2 as well, which is the "
              "shape of a fixture that cannot tell the two implementations apart: %r"
              % (rec_again,),
              len([v for v in rec_again if "not strictly downward" in v[1]]) == 1
              and len([v for v in rec_again if "imports scripts module" in v[1]]) == 1
              and len(rec_again) == 2)

        # ---- guide_enumeration: matched by basename, reported by relative path ----
        rec_guide = os.path.join(rec, "guide.md")
        with open(rec_guide, "w", encoding="utf-8") as fh:
            fh.write(
                "intro\n\n" + M._TREE_HEADING + "\n\n```\n"
                "  flat_low.py\n  high.py\n  usage/\n    core.py\n```\n\n"
                + M._SECTION2_HEADING + "\n\n"
                "### `flat_low.py`\nprose.\n\n"
                "### `high.py`\nprose.\n\n"
                "### `core.py`\nprose.\n\n"
                "## 3. Next section\nnot part of section 2.\n"
            )
        rec_enum_hooks = os.path.join(rec, "empty_hooks")
        os.makedirs(rec_enum_hooks)
        rec_enum = M.guide_enumeration(rec_guide, script_dir=rec_scripts,
                                       hooks_dir=rec_enum_hooks)
        check("w7 a file one directory down that the guide never mentions is named, by "
              "its relative path - and `usage/core.py`, which the tree draws as an "
              "indented `core.py` under a `usage/` line, is NOT, because the match is on "
              "the BASENAME. Both directions in one exact list, which is also what fails "
              "if the rule is ever tightened to demand the literal `usage/core.py` a "
              "correctly drawn tree does not contain: %r" % (rec_enum,),
              rec_enum == [
                  ("panel/clean.py", "missing from the '%s' tree" % M._TREE_HEADING),
                  ("panel/clean.py", "no '### ' heading in '%s' mentions it"
                   % M._SECTION2_HEADING)])

        # ---- navigability: a long file one directory down is still judged ----
        nav_scripts = os.path.join(rec, "nav", "scripts", "deep")
        os.makedirs(nav_scripts)
        nav_hooks_dir = os.path.join(rec, "nav", "hooks")
        os.makedirs(nav_hooks_dir)
        with open(os.path.join(nav_scripts, "long_file.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("pass\n" * (M._NAV_MIN_LINES + 10))
        nav_deep = M.navigability_violations(os.path.join(rec, "nav", "scripts"),
                                             hooks_dir=nav_hooks_dir)
        check("w8 a long, headerless file one directory down is a navigability "
              "violation like any other, named `deep/long_file.py`: %r" % (nav_deep,),
              [f for f, _w in nav_deep] == ["deep/long_file.py"])

        # ---- the price of naming nodes by basename, charged rather than assumed ----
        coll = os.path.join(rec, "collide")
        os.makedirs(os.path.join(coll, "usage"))
        os.makedirs(os.path.join(coll, "panel"))
        for _sub in ("usage", "panel"):
            with open(os.path.join(coll, _sub, "core.py"), "w",
                      encoding="utf-8") as fh:
                fh.write("pass\n")
        coll_hits = M.layer_violations(coll, hooks_dir=rec_enum_hooks,
                                       layers=(("core",),))
        check("w9 two files claiming one module name is a violation IN ITS OWN WORDS, "
              "naming both paths - not a silently kept last-one-wins. They would be a "
              "single node in the graph, each wearing the other's edges, and every "
              "later judgement would be about a tree that is not there: %r" % (coll_hits,),
              len(coll_hits) == 1 and coll_hits[0][0] == "panel/core.py"
              and "claimed by 2 files" in coll_hits[0][1]
              and "usage/core.py" in coll_hits[0][1])
        check("w10 ...and the second direction: two DIFFERENT basenames in two different "
              "subdirectories are not a collision. Reads vacuous, and is the only case "
              "that fails if uniqueness is ever implemented as 'more than one directory' "
              "rather than 'more than one file per name' - which would make the whole "
              "recursion unusable: %r" % (rec_collisions,),
              rec_collisions == [])
    finally:
        shutil.rmtree(rec, ignore_errors=True)

    # ---- the tests/ boundary: the product may not depend on its own test tree ----
    # Fixtures, because the real tree is (and must stay) clean, and a rule only ever
    # seen returning [] is a rule that might be returning [] for the wrong reason.
    tb_s = tempfile.mkdtemp(prefix="deps-testboundary-s-")
    tb_h = tempfile.mkdtemp(prefix="deps-testboundary-h-")
    tb_t = tempfile.mkdtemp(prefix="deps-testboundary-t-")
    try:
        def _wtb(root, name, text):
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write(text)

        _wtb(tb_t, "_harness.py", "def run(body):\n    return 0\n")
        _wtb(tb_t, "test_thing.py", "x = 1\n")
        _wtb(tb_s, "reaches_in.py", "import _harness\nx = 1\n")
        _wtb(tb_s, "reaches_in_from.py", "from _harness import run\nx = 1\n")
        _wtb(tb_s, "loads_it.py",
             'import _loader\n\n\ndef f():\n'
             '    return _loader.load_script("test_thing.py")\n')
        # The shape the three migrated files actually have: a test file named in
        # PROSE, so a reader knows where the cases went. Not an edge, and the only
        # case that fails if this lint is ever widened to "any .py literal".
        #
        # The anchor is BUILT, never spelled beside the filename: this file is one of
        # `_refs`' anchored surfaces, so an anchor written immediately in front of a
        # tests/ filename here would be a real reference to a fixture that exists for
        # four milliseconds, and `_refs.missing_references()` reports it. Learned by
        # doing it twice - the second time inside the comment saying not to.
        _anchor = "plugins/audit/"
        _wtb(tb_s, "only_points_at_it.py",
             '"""Its cases live in %stests/test_thing.py."""\n'
             'import _loader\n\n\ndef f():\n'
             '    print("moved to %stests/test_thing.py")\n'
             '    return _loader\n' % (_anchor, _anchor))
        _wtb(tb_h, "hook_reaches_in.py", "import _harness\nx = 1\n")
        _wtb(tb_h, "hook_clean.py", "import json\nx = 1\n")

        tb = M.tests_import_violations(tb_s, tb_h, tb_t)
        named_tb = sorted(n for n, _w in tb)
        check("tb1 a scripts/ file that imports the harness is reported, and so is "
              "the `from ... import` form - one rule, both spellings: %r" % (named_tb,),
              "scripts/reaches_in.py" in named_tb
              and "scripts/reaches_in_from.py" in named_tb)
        check("tb2 a HOOK that reaches into tests/ is reported too. hooks/ may not "
              "import scripts/ either, and both rules exist so the thing that runs on "
              "every tool call stays loadable from a launcher: %r" % (named_tb,),
              "hooks/hook_reaches_in.py" in named_tb)
        check("tb3 a `_loader` call naming a tests/ file is an edge as much as an "
              "import is - most of this tree's real edges are loader calls: %r"
              % (named_tb,), "scripts/loads_it.py" in named_tb)
        check("tb4 a file that merely NAMES a test file in a docstring and a print is "
              "NOT reported. Reads vacuous, and is the only case that fails if this "
              "widens to any `.py` literal - which would report all three migrated "
              "files, whose pointer messages say exactly that: %r" % (named_tb,),
              "scripts/only_points_at_it.py" not in named_tb
              and "hooks/hook_clean.py" not in named_tb)
        check("tb5 the message names the kind of edge, so the reader knows whether to "
              "look for an `import` or a loader call: %r" % ([w for _n, w in tb],),
              any("imports _harness from tests/" in w for _n, w in tb)
              and any("runtime-loads test_thing from tests/" in w for _n, w in tb))
        check("tb6 an empty (or absent) tests/ yields no violations, and is not "
              "confused with a clean scan of a populated one",
              M.tests_import_violations(tb_s, tb_h,
                                        os.path.join(tb_t, "no-such-dir")) == [])
    finally:
        shutil.rmtree(tb_s, ignore_errors=True)
        shutil.rmtree(tb_h, ignore_errors=True)
        shutil.rmtree(tb_t, ignore_errors=True)

    check("tb7 ...and the REAL tree carries none. This is the case that goes red the "
          "day a script imports the harness: %r" % (M.tests_import_violations(),),
          M.tests_import_violations() == [])
    check("tb8 tests/ is deliberately absent from LAYERS - a test file has no position "
          "in the product's import order, and tb7 is the rule that replaces one: %r"
          % (sorted(set(M._all_names()) & set(os.path.basename(r)[:-3]
                                              for r, _p in _output.py_files(
                                                  M._output.TESTS_DIR))),),
          not (set(M._all_names()) & set(os.path.basename(r)[:-3]
                                         for r, _p in _output.py_files(M._output.TESTS_DIR))))

    # --- dpn: the prose docs accumulate one stale number per module -----------
    _dpn = M.doc_prose_numbers()
    check("dpn0 no prose doc writes a present-tense number - they carry a line "
          "per module, so they accrue one stale number per module; two of the "
          "five case counts were already wrong when the first family landed "
          "(_policy 60 vs 71, _refs 32 vs 80), and all three of the persistence "
          "and completeness claims were wrong when these two did (F43): %r"
          % (_dpn[:6],),
          _dpn == [])
    # Vacuity FIRST: "no claims" and "read nothing" print identically otherwise,
    # and this scan now spans three files, so a per-file count is what says the
    # walk reached all of them rather than stopping after the first.
    _dpn_lines = []
    for _dname in M._PROSE_DOCS:
        try:
            with open(os.path.join(M._output.REPO_ROOT, _dname),
                      "r", encoding="utf-8") as _dfh:
                _dpn_lines.append((_dname, len(_dfh.read().split("\n"))))
        except (OSError, UnicodeDecodeError):
            _dpn_lines.append((_dname, 0))
    check("dpn1 dpn0 read all %d documents rather than an empty string - %r"
          % (len(M._PROSE_DOCS), _dpn_lines),
          len(_dpn_lines) == 3
          and all(n > 100 for _d, n in _dpn_lines)
          and max(n for _d, n in _dpn_lines) > 500)
    check("dpn2 an unreadable document returns a NAMED finding, not the same "
          "empty list a clean one returns - F21's rule, and the reason a clean "
          "dpn0 means 'looked and found nothing' rather than 'could not look'",
          M.doc_prose_numbers(["/nonexistent/GUIDE.md"])
              == [("GUIDE.md", 0, "<unreadable: GUIDE.md>")])
    check("dpn3 the shape is defined ONCE - doc_prose_numbers delegates to "
          "_output._prose_number_claim, because a second copy of the pattern "
          "would be exactly the defect both functions exist to catch",
          M.doc_prose_numbers.__doc__ is not None
          and "_output._prose_number_claim" in M.doc_prose_numbers.__doc__
          and not [l for l in open(M.__file__, encoding="utf-8").read().split("\n")
                   if l.startswith("def _prose_number_claim")
                   or l.startswith("def _case_claim")])
    # POSITIVE CONTROL. dpn0 asserts an empty list, which is also what a scanner
    # that reads nothing returns; dpn1 proves the bytes arrived and this proves
    # the predicate is still wired to them. The fixture is F43's own sentence,
    # the wrap that carries a basis, and a historical line - so it fails if the
    # scan dies, if the basis stops being read across the wrap, or if history
    # stops being writable.
    _dpn_tmp = tempfile.mkdtemp(prefix="audit-deps-dpn-")
    try:
        _dpn_doc = os.path.join(_dpn_tmp, "FIXTURE.md")
        with open(_dpn_doc, "w", encoding="utf-8") as fh:
            fh.write("`KNOWN_LAYER_DEBT` stayed at 17 and the map did not move.\n"
                     "It stood at 70 that day, and was wrong by the next commit.\n"
                     "all 83 of them (`73042a1` - print it with\n"
                     "`python3 -c \"...\"`); a migrated file still exits 0.\n")
        _dpn_hits = M.doc_prose_numbers([_dpn_doc])
        check("dpn4 POSITIVE CONTROL: F43's own sentence IS reported, with its "
              "line number, while the historical line and the wrapped line whose "
              "basis lands on the next one are both left alone. dpn0 is an empty "
              "list, and an empty list is also what a broken scanner returns: %r"
              % (_dpn_hits,),
              _dpn_hits == [("FIXTURE.md", 1, "stayed at 17")])
    finally:
        shutil.rmtree(_dpn_tmp, ignore_errors=True)


    # --- the ONE recorded layer debt, and whether its REASON still holds ----------
    # KNOWN_LAYER_DEBT carries a written justification, and a written justification
    # is the half of an allow-list that rots without anything noticing: `r2` pins
    # the EDGE and would stay green for as long as the edge existed, whatever the
    # comment above it had come to claim. These two recompute the claim instead.
    #
    # The claim: `_panel_state` runtime-loads `render-report` because what it wants
    # is the whole report pipeline ending in files on disk, that pipeline bottoms
    # out at `_report_page`, and `_report_page` is NOT strictly below
    # `_panel_state` - so no module `_panel_state` may import from can hold it.
    # Retiring the entry therefore means moving one of those two, and that is
    # exactly what these cases watch for.
    _ld_static, _ld_runtime, _ld_broken = M._scan_edges()
    _ld_all = _ld_static | _ld_runtime
    _ld_chain = ("_report_html", "_usage_viz", "_usage_markdown", "_report_md",
                 "_report_page")
    _ld_links = [(_ld_chain[i + 1], _ld_chain[i]) for i in range(len(_ld_chain) - 1)]
    _ld_missing = [lk for lk in _ld_links if lk not in _ld_all]
    _ld_layers = [M._layer_of(n) for n in _ld_chain]
    check("ld0 the report document stack is a REAL chain in the scanned tree, not "
          "a picture: every link of %r is an edge (%d links, %d missing: %r) and "
          "its layers rise strictly (%r). Read off %d scanned edges, so an empty "
          "scan cannot pass this"
          % (_ld_chain, len(_ld_links), len(_ld_missing), _ld_missing, _ld_layers,
             len(_ld_all)),
          len(_ld_all) > 0 and not _ld_missing and None not in _ld_layers
          and all(_ld_layers[i] < _ld_layers[i + 1]
                  for i in range(len(_ld_layers) - 1)))

    def _debt_reason_holds(layers):
        """True while no layer under `_panel_state` can hold the report writer.

        The entry's justification, as arithmetic: the deepest module the whole-
        document pipeline needs (`_report_page`) is at or above the module that
        wants it, so there is no legal home below the consumer.
        """
        consumer = M._layer_of("_panel_state", layers)
        deepest = M._layer_of("_report_page", layers)
        if consumer is None or deepest is None:
            return None
        return deepest >= consumer

    _ld_consumer = M._layer_of("_panel_state")
    _ld_deepest = M._layer_of("_report_page")
    check("ld1 the justification written above KNOWN_LAYER_DEBT is still ARITHMETIC "
          "and not history: `_report_page` (layer %r) is not strictly below "
          "`_panel_state` (layer %r), so the report writer has no home this module "
          "may import from and the edge cannot be retired by moving code. If this "
          "goes red the entry has become retirable - rewrite or delete it, do not "
          "re-green this case"
          % (_ld_deepest, _ld_consumer),
          _debt_reason_holds(M.LAYERS) is True)

    # POSITIVE CONTROL for ld1. `ld1` asserts a condition that is true of the tree
    # as it stands, so on its own it cannot distinguish "the reason holds" from
    # "the predicate answers True to everything". This lifts `_panel_state` above
    # the report stack - the FIRST of the two fixes the entry names - and requires
    # the answer to flip. The mutation is asserted to have applied before it is
    # judged, because a table that silently failed to change would make this pass.
    _ld_mut = tuple(tuple(n for n in members if n != "_panel_state")
                    for members in M.LAYERS) + (("_panel_state",),)
    _ld_mut_layer = M._layer_of("_panel_state", _ld_mut)
    check("ld2 POSITIVE CONTROL: the mutation APPLIED - `_panel_state` moved from "
          "layer %r to layer %r and appears exactly once in the mutated table (%d "
          "occurrences), which is what makes ld2b's answer mean anything"
          % (_ld_consumer, _ld_mut_layer,
             sum(1 for ms in _ld_mut for n in ms if n == "_panel_state")),
          _ld_mut_layer is not None and _ld_mut_layer > _ld_consumer
          and sum(1 for ms in _ld_mut for n in ms if n == "_panel_state") == 1)
    check("ld2b ...and with `_panel_state` above `_report_page` the justification "
          "STOPS holding - so ld1 is reading the table rather than answering True "
          "unconditionally, and the entry really would be retirable if anyone made "
          "that move",
          _debt_reason_holds(_ld_mut) is False)

    # The entry is a pair (file, what), and `r2` already pins it against the real
    # violations. What r2 cannot see is WHICH file the reason is written about: a
    # justification naming `_panel_state` while the recorded edge belonged to some
    # other module would be an allow-list entry with a reason for a different
    # thing. Cheap to state, and it is the join between ld1's arithmetic and r2's
    # equality.
    _ld_files = sorted(set(f for f, _w in M.KNOWN_LAYER_DEBT))
    check("ld3 the arithmetic in ld1 is about the file the table actually records: "
          "every debt entry names a `_panel_state` path (%r)"
          % (_ld_files,),
          _ld_files and all(os.path.basename(f) == "_panel_state.py"
                            for f in _ld_files))


    # --- the navigability walk must descend into feature directories ----------
    import _ui_theme as _uith
    _theme_assets = _uith.UI_ASSETS
    _u_tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(_u_tmp, "feature"))
        _long = "".join("  var x%d = %d;\n" % (_i, _i) for _i in range(900))
        with open(os.path.join(_u_tmp, "feature", "big.js"), "w") as _fh:
            _fh.write(_long)
        _nested = M.ui_navigability_violations(_u_tmp)
        check("u14 a long asset inside a feature directory is CHECKED - a flat "
              "listing would grade the directory clean without ever opening it, "
              "which is the shape that hides a whole surface (got %r)"
              % (_nested,),
              [n for n, _p in _nested] == ["feature/big.js"])
        # Not "a declared name contains a slash" - that is a fact about a Python
        # literal and stays true with the directory deleted. This asks the
        # SHIPPED walk whether it visits the subdirectory, by comparing what it
        # reaches against a deliberately flat listing of the same root.
        _flat = [_f for _f in os.listdir(M._UI_DIR)
                 if os.path.isfile(os.path.join(M._UI_DIR, _f))]
        _seen = M.ui_asset_names(M._UI_DIR)
        check("u15 the shipped walk reaches more than a flat listing of the same "
              "directory - %d file(s) walked against %d at the top level, so it "
              "is descending rather than agreeing by accident"
              % (len(_seen), len(_flat)),
              len(_seen) > len(_flat))
    finally:
        shutil.rmtree(_u_tmp, ignore_errors=True)

    # --- tools/ is under the marker rule now, and it was under nothing -----------
    # The largest file in this repository was a browser gate of 8451 lines, and the
    # marker rule reached scripts/ui/, scripts/ and hooks/ but never the directory
    # holding the machinery that proves all three. Two extensions had to join the
    # table for that to mean anything - `.mjs`, which nothing here used, and `.py`,
    # whose absence would have made the walk SKIP every tool silently.
    _tn = M.tool_navigability_violations()
    _tn_names = M.ui_asset_names(M._TOOLS_DIR)
    _tn_graded = [n for n in _tn_names
                  if any(n.endswith(e) for e, _r in M._UI_MARKER_RES)]
    _tn_long = [n for n in _tn_graded
                if sum(1 for _l in open(os.path.join(M._TOOLS_DIR, n),
                                        encoding="utf-8", errors="replace"))
                >= M._NAV_MIN_LINES]
    check("tn0 every long file under tools/ carries its section markers: %r"
          % (_tn,), _tn == [])
    check("tn1 ...and that verdict is over real observations - %d file(s) walked, "
          "%d gradable by extension, %d long enough to be checked. A clean list "
          "means one thing at those numbers and something else entirely at zero, "
          "which is what a table missing an extension would have produced"
          % (len(_tn_names), len(_tn_graded), len(_tn_long)),
          len(_tn_long) >= 4 and len(_tn_graded) >= 20)

    _tn_tmp = tempfile.mkdtemp(prefix="audit-deps-tools-")
    try:
        _long_js = "".join("  const x%d = %d;\n" % (_i, _i) for _i in range(900))
        _long_py = "".join("x%d = %d\n" % (_i, _i) for _i in range(900))
        with open(os.path.join(_tn_tmp, "thin.mjs"), "w", encoding="utf-8") as _fh:
            _fh.write("// --- only one -------------------------------------\n"
                      + _long_js)
        with open(os.path.join(_tn_tmp, "thin.py"), "w", encoding="utf-8") as _fh:
            _fh.write("# --- only one -------------------------------------\n"
                      + _long_py)
        _hits = dict((n, p) for n, p in M.tool_navigability_violations(_tn_tmp))
        check("tn2 a long `.mjs` with one marker is REPORTED - the extension the "
              "table gained for this, and the one every tool in the split is "
              "written in: %r" % (_hits.get("thin.mjs"),),
              "thin.mjs" in _hits and "section marker" in _hits["thin.mjs"])
        check("tn3 ...and a long `.py` too, which is the half that would have been "
              "SKIPPED rather than failed: an extension with no entry in the table "
              "is passed over, so the docstring claimed a coverage the table did "
              "not give: %r" % (_hits.get("thin.py"),),
              "thin.py" in _hits and "section marker" in _hits["thin.py"])
        with open(os.path.join(_tn_tmp, "thin.mjs"), "w", encoding="utf-8") as _fh:
            _fh.write("// --- one ------------------------------------------\n"
                      + _long_js
                      + "// --- two ------------------------------------------\n"
                      + "// --- three ----------------------------------------\n")
        _after = dict(M.tool_navigability_violations(_tn_tmp))
        check("tn4 THE PAIR: the same file with enough markers is not reported, "
              "while its `.py` neighbour still is - so tn2 is reading the count "
              "rather than the extension: %r" % (sorted(_after),),
              "thin.mjs" not in _after and "thin.py" in _after)
    finally:
        shutil.rmtree(_tn_tmp, ignore_errors=True)

    check("tn5 widening the table did not change scripts/ui/, which holds neither "
          "extension: %r" % (M.ui_navigability_violations(),),
          M.ui_navigability_violations() == [])

    # --- the scan memo: it must be USED, must not LIE, and must not be POISONED ---
    # A scan parses every `.py` under `scripts/` and grows the wrapper map to a
    # fixpoint, and the lints each ask for the whole graph because each judges the
    # whole graph - profiled, one run of this file entered `_scan_edges` 25 times
    # and spent most of its wall clock there recomputing one answer. The memo is
    # what removed that, and these five cases are what keep it honest: a cache is
    # the one optimisation that can be WRONG rather than merely slow.
    _fresh = M._scan_edges_once(_output.SCRIPTS_DIR)
    _cached = M._scan_edges()
    check("mm0 the memo does not LIE: the cached answer is the same answer an "
          "uncached scan of the same tree produces, edge for edge (%d static, "
          "%d runtime, %d broken)"
          % (len(_cached[0]), len(_cached[1]), len(_cached[2])),
          _cached[0] == _fresh[0] and _cached[1] == _fresh[1]
          and _cached[2] == _fresh[2] and len(_cached[0]) > 100)

    _a, _b = M._scan_edges(), M._scan_edges()
    _a[0].add(("poison-importer", "poison-imported"))
    _a[2].append("poison.relname")
    _after = M._scan_edges()
    check("mm1 ...and each caller gets its OWN containers, proven by MUTATING one "
          "and reading another: a shared set would make one lint's `.add()` the "
          "next lint's input, which is the module state the house style bans "
          "(%d edges after the poison against %d before)"
          % (len(_after[0]), len(_b[0])),
          _a[0] is not _b[0] and _after[0] == _b[0]
          and "poison.relname" not in _after[2])

    _calls = []
    _real_once = M._scan_edges_once

    def _counting_once(script_dir=None):
        _calls.append(script_dir)
        return _real_once(script_dir)

    _mem_tmp = tempfile.mkdtemp(prefix="audit-deps-memo-")
    try:
        M._scan_edges_once = _counting_once
        M._EDGES.clear()
        M._scan_edges()
        M._scan_edges()
        M._scan_edges()
        check("mm2 the memo is actually IN USE - three default-tree calls after a "
              "cleared cache reach the real scan exactly ONCE (%d call(s)). Without "
              "this case a memo whose key never matched would pass every other "
              "case here and the speedup would be unattributable" % (len(_calls),),
              len(_calls) == 1)

        os.makedirs(os.path.join(_mem_tmp, "tree"))
        for _n, _src in (("p.py", "import q\n"), ("q.py", "pass\n")):
            with open(os.path.join(_mem_tmp, "tree", _n), "w",
                      encoding="utf-8") as _fh:
                _fh.write(_src)
        _own = M._scan_edges(os.path.join(_mem_tmp, "tree"))
        check("mm3 a caller that hands over its OWN tree is NOT served the cache - "
              "it gets the fixture's single edge, not the real tree's hundreds. "
              "This is the case that fails if the memo ignores `script_dir`, and "
              "every fixture-tree case above silently becomes a claim about "
              "scripts/ instead: %r" % (sorted(_own[0]),),
              sorted(_own[0]) == [("p", "q")])

        _still = M._scan_edges()
        check("mm4 ...and that fixture call did not POISON the cache either: the "
              "default tree still answers with its own edges afterwards (%d), so "
              "the isolation holds in both directions" % (len(_still[0]),),
              _still[0] == _fresh[0])
    finally:
        M._scan_edges_once = _real_once
        M._EDGES.clear()
        shutil.rmtree(_mem_tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__deps.py --selftest\n")
    raise SystemExit(2)
