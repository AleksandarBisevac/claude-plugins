#!/usr/bin/env python3
"""
The cases for `_output_lints.py` - the dialect lints, the preamble check, the
prose-number scan and the selftest coverage classifier that used to be the second
half of `_output.py`.

`L` is the module under test and `M` is `_output`, which some cases use for the
anchors and the file walks the lints are built on. Several cases are assertions about
the REAL tree (`f1`, `g10`, `rc7`, `sc7`), and the real tree contains this file: `f2`
requires `tests/` to be non-empty and every entry point in it to install the guard, a
rule this file is subject to and satisfies.

The cases for what stayed in `_output.py` are in `tests/test__output.py`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output as M                                # noqa: E402
import _output_lints as L                          # noqa: E402



# --- cases --------------------------------------------------------------------
def _cases(check):
    import subprocess
    import tempfile
    import shutil
    import io

    # ------------------------------------------------------------------ the crash
    # Proven by reproduction, not by reasoning: the same one-line program, run twice,
    # differing only in whether the guard is installed. If the unguarded child ever
    # stops dying, this whole module is answering a question nobody is asking any more
    # and these cases are the ones that should say so.
    tmp = tempfile.mkdtemp(prefix="audit-output-")
    try:
        naked = os.path.join(tmp, "naked.py")
        with open(naked, "w", encoding="utf-8") as fh:
            fh.write('print("tick \\u2713 done")\n')

        guarded = os.path.join(tmp, "guarded.py")
        with open(guarded, "w", encoding="utf-8") as fh:
            fh.write(
                "import sys\n"
                "sys.path.insert(0, %r)\n"
                "from _output import safe_stdio\n"
                "safe_stdio()\n"
                'print("tick \\u2713 done")\n' % M.SCRIPTS_DIR)

        def run(path, io_encoding):
            env = dict(os.environ, PYTHONIOENCODING=io_encoding)
            return subprocess.run([sys.executable, path], env=env,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")

        bare = run(naked, "cp1252")
        check("a1 an unguarded print of a non-cp1252 glyph DIES on a cp1252 stream - "
              "this is the Windows CI failure, reproduced on any platform",
              bare.returncode != 0)
        check("a2 ...and it dies with UnicodeEncodeError, not some other error that "
              "would mean this module is fixing the wrong thing",
              "UnicodeEncodeError" in bare.stderr)
        check("a3 ...losing the whole line, not just the glyph: nothing is printed",
              "done" not in bare.stdout)

        safe = run(guarded, "cp1252")
        check("b1 the guarded child survives the same stream", safe.returncode == 0)
        check("b2 ...and still says everything it had to say", "done" in safe.stdout)

        utf8 = run(guarded, "utf-8")
        check("c1 a UTF-8 consumer gets the REAL character, not the degraded one - "
              "'replace' is the floor, not the behaviour", "✓" in utf8.stdout)

        # ------------------------------------------------------- the guard's own edges
        held = sys.stdout, sys.stderr
        try:
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            M.safe_stdio()  # a StringIO has no reconfigure at all
            failed = False
        except Exception:
            failed = True
        finally:
            sys.stdout, sys.stderr = held
        check("d1 a captured stream (StringIO, which every capturing selftest installs) "
              "is not a reason to take the process down", not failed)

        # -------------------------------------------------------------- adoption lint
        fake = os.path.join(tmp, "fake")
        os.makedirs(fake)
        with open(os.path.join(fake, "importable.py"), "w", encoding="utf-8") as fh:
            fh.write('def f():\n    print("hi")\n')  # no __main__: not an entry point
        with open(os.path.join(fake, "forgot.py"), "w", encoding="utf-8") as fh:
            fh.write('if __name__ == "__main__":\n    print("hi")\n')
        with open(os.path.join(fake, "late.py"), "w", encoding="utf-8") as fh:
            fh.write('print("early")\n'
                     'if __name__ == "__main__":\n'
                     '    safe_stdio()\n')
        with open(os.path.join(fake, "ok.py"), "w", encoding="utf-8") as fh:
            fh.write('if __name__ == "__main__":\n'
                     '    safe_stdio()\n'
                     '    print("hi")\n')
        # The shape every real script in this directory has, and the one a textual lint
        # gets wrong: printing functions defined FIRST, the guard installed in the entry
        # block. Nothing here prints before the guard, because none of it runs before it.
        with open(os.path.join(fake, "defs.py"), "w", encoding="utf-8") as fh:
            fh.write('def render():\n'
                     '    print("output")\n'
                     'if __name__ == "__main__":\n'
                     '    safe_stdio()\n'
                     '    render()\n')
        with open(os.path.join(fake, "broken.py"), "w", encoding="utf-8") as fh:
            fh.write('if __name__ == "__main__"\n    safe_stdio(\n')
        found = L.entries_missing_guard((fake,))
        check("e1 the lint names an entry point that never installs the guard",
              "forgot.py" in found)
        check("e2 ...and one that installs it AFTER printing, which crashes on the "
              "line the guard was added to protect", "late.py" in found)
        check("e3 an imported module with no __main__ is not an entry point and is "
              "not named", "importable.py" not in found)
        check("e4 a print inside a def is a plan to print, not printing - the shape "
              "every script here has, and the one a textual check misreads",
              "defs.py" not in found)
        check("e5 a file that will not parse is reported, not silently skipped - "
              "the lint must not be the thing that hides a syntax error",
              "broken.py" in found)
        check("e6 nothing else is named: %r" % (found,),
              found == ["broken.py", "forgot.py", "late.py"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The gate this module exists for. Every command under scripts/ AND tests/ is
    # covered, and a new one that forgets fails HERE - in a suite CI already runs -
    # rather than on a Windows runner, in one leg of a matrix, weeks later.
    real = L.entries_missing_guard()
    check("f1 every entry point under scripts/ installs the guard before it prints: %r"
          % (real,), not real)
    check("f2 ...and the default scope now reaches tests/ too, which is the half a "
          "sibling directory added: %r"
          % (sorted(n for n, _p in M.py_files(M.TESTS_DIR)),),
          L.entries_missing_guard() == sorted(L.entries_missing_guard((M.SCRIPTS_DIR,))
                                              + L.entries_missing_guard((M.TESTS_DIR,)))
          and M.py_files(M.TESTS_DIR) != [])

    # ------------------------------------------------------------ the usage hook
    # Every parser an entry point builds hands itself to the one shared usage hook,
    # so a usage error from an older copy names the newer one. The fixtures carry the
    # shapes the real tree uses - a parser hooked beside its construction, one wrapped
    # at construction, a builder returning the hooked parser, a `parents=` template
    # that never parses argv - and the shapes that would leave a parser bare.
    hook = tempfile.mkdtemp(prefix="audit-usage-hook-")
    try:
        os.makedirs(os.path.join(hook, "sub"))
        fixtures = {
            os.path.join("sub", "bare.py"):
                'import argparse\n'
                'if __name__ == "__main__":\n'
                '    p = argparse.ArgumentParser(prog="bare")\n'
                '    p.parse_args()\n',
            "hooked.py":
                'import argparse\nimport _claude_home\n'
                'if __name__ == "__main__":\n'
                '    p = argparse.ArgumentParser(prog="hooked")\n'
                '    p.add_argument("verb")\n'
                '    _claude_home.attach_usage_hint(p)\n'
                '    p.parse_args()\n',
            "wrapped.py":
                'import argparse\nimport _claude_home\n'
                'def main():\n'
                '    p = _claude_home.attach_usage_hint(\n'
                '        argparse.ArgumentParser(prog="wrapped"))\n'
                '    return p.parse_args()\n',
            "builder.py":
                'import argparse\nimport _claude_home\n'
                'def build():\n'
                '    parser = argparse.ArgumentParser(prog="builder")\n'
                '    return _claude_home.attach_usage_hint(parser)\n',
            "parent.py":
                'import argparse\nimport _claude_home\n'
                'def build():\n'
                '    common = argparse.ArgumentParser(add_help=False)\n'
                '    p = argparse.ArgumentParser(parents=[common])\n'
                '    return _claude_home.attach_usage_hint(p)\n',
            # The hook attached only after argv was parsed decorates nothing: the
            # usage error has already been raised by the time it is installed.
            "late.py":
                'import argparse\nimport _claude_home\n'
                'def main():\n'
                '    p = argparse.ArgumentParser(prog="late")\n'
                '    args = p.parse_args()\n'
                '    _claude_home.attach_usage_hint(p)\n'
                '    return args\n',
            # The same NAME hooked in a different function is a different parser.
            "elsewhere.py":
                'import argparse\nimport _claude_home\n'
                'def build():\n'
                '    p = argparse.ArgumentParser(prog="elsewhere")\n'
                '    return p\n'
                'def other(p):\n'
                '    return _claude_home.attach_usage_hint(p)\n',
            # A parser no name holds cannot be handed to anything afterwards.
            "unnamed.py":
                'import argparse\n'
                'def main():\n'
                '    return argparse.ArgumentParser(prog="unnamed").parse_args()\n',
            # Naming the constructor in prose or comparing against its name is not
            # building one - the shape of the lint that reads other files' parsers
            # and of the hook's own docstring.
            "prose.py":
                '"""Every ArgumentParser(...) here is read, never built."""\n'
                'def built(fn):\n'
                '    return fn == "ArgumentParser"\n',
            "broken.py":
                'p = argparse.ArgumentParser(\n',
        }
        for rel, text in fixtures.items():
            with open(os.path.join(hook, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        found = L.usage_hint_violations((hook,))
        where = sorted((rel, line) for rel, line, _why in found)
        check("uh1 an entry point that builds a parser and never hands it to the "
              "usage hook is named by file and line: %r" % (where,),
              ("sub/bare.py", 3) in where)
        check("uh2 ...and so is one that hands it over only AFTER parsing argv, "
              "since the usage error has already been raised by then: %r"
              % (where,), ("late.py", 4) in where)
        check("uh3 ...and a parser hooked under the same name in ANOTHER function "
              "is still bare where it was built: %r" % (where,),
              ("elsewhere.py", 4) in where)
        check("uh4 ...and a parser no name holds, and a file that will not parse "
              "(reported, never skipped): %r" % (where,),
              ("unnamed.py", 3) in where and ("broken.py", 0) in where)
        # The over-fire twin: a lint that named every parser it saw would pass
        # uh1-uh4 and fail here, on the hooked, wrapped, builder, parents= and
        # prose fixtures that must stay quiet.
        check("uh5 nothing else is named - a hooked, wrapped, built-and-returned "
              "or parents= parser, and a file that only NAMES the constructor, all "
              "stay quiet: %r" % (where,),
              where == [("broken.py", 0), ("elsewhere.py", 4), ("late.py", 4),
                        ("sub/bare.py", 3), ("unnamed.py", 3)])
        check("uh6 every finding says why, in words: %r" % (found,),
              all(why and isinstance(why, str) for _r, _l, why in found))
    finally:
        shutil.rmtree(hook, ignore_errors=True)

    real_hook = L.usage_hint_violations()
    check("uh7 no entry point under scripts/ builds a parser it never hands to the "
          "usage hook: %r" % (real_hook,), real_hook == [])
    # The allow case on the real tree, and the one that keeps uh7 from being green
    # over an empty scan: every file that spells the constructor followed by an
    # open parenthesis must be one the AST reads a parser in, except the one that
    # only NAMES it - `_claude_home.py`'s docstring describes the seam. It builds
    # no parser, so it owes no hook and is not exempted.
    spelled = set()
    for rel, path in M.lint_py_files(M.SCRIPTS_DIR):
        with open(path, encoding="utf-8") as fh:
            if "ArgumentParser" + "(" in fh.read():
                spelled.add(rel)
    sites = set(rel for rel, _line, _why in
                L.parser_sites(M.lint_py_files(M.SCRIPTS_DIR)))
    mentions = set(["status/_claude_home.py"])
    check("uh8 the scan reads a parser in every file that spells one being built, "
          "and not in the file that only names the constructor: sites "
          "missing %r, unexpected %r"
          % (sorted(spelled - mentions - sites), sorted(sites - (spelled - mentions))),
          mentions <= spelled and sites == spelled - mentions and bool(sites))

    # ----------------------------------------------- the hand-parsed dispatcher shape
    # The other half of the same check: a dispatcher that reads its verb by hand
    # (`if verb not in (...)`) builds no parser, so `parser_sites()` cannot see it -
    # `materialize-proposal.py` was exactly this before it called the hint
    # directly in the branch that refuses an unrecognised verb. Two signals are
    # both required (see the module comment above `verb_dispatch_sites`), each
    # proven necessary by its own twin below: a fixture that has one signal but
    # not the other must stay as quiet as a plain validator.
    vd = tempfile.mkdtemp(prefix="audit-verb-dispatch-")
    try:
        vd_fixtures = {
            # The deny case: the shape the review found - a name dispatched on
            # elsewhere (`verb == "list"`) whose unknown-verb branch prints the
            # usage block and nothing else.
            "bare.py":
                'import sys\n'
                'USAGE = "usage: bare.py <verb>\\n"\n'
                'def main(argv):\n'
                '    verb = argv[0]\n'
                '    if verb not in ("list", "plan", "drop"):\n'
                '        sys.stderr.write(USAGE)\n'
                '        return 2\n'
                '    if verb == "list":\n'
                '        return 0\n'
                '    return 1\n',
            # The allow twin: structurally identical, differing only in the one
            # call this check is about - proving the lint reads the call and not
            # merely the shape of the `if`.
            "hinted.py":
                'import sys\n'
                'import _claude_home\n'
                'USAGE = "usage: hinted.py <verb>\\n"\n'
                'def main(argv):\n'
                '    verb = argv[0]\n'
                '    if verb not in ("list", "plan", "drop"):\n'
                '        sys.stderr.write(USAGE)\n'
                '        hint = _claude_home.usage_hint(None, None, None, None)\n'
                '        sys.stderr.write("\\n".join(hint))\n'
                '        return 2\n'
                '    if verb == "list":\n'
                '        return 0\n'
                '    return 1\n',
            # Dispatched on, but the refusal is an ordinary sentence, never the
            # shared usage block - `materialize-proposal.py`'s OWN `--all applies
            # to plan and materialize only` branch is exactly this shape, and
            # owes the hint no more than any other one-line refusal does.
            "ordinary_refusal.py":
                'import sys\n'
                'def main(argv):\n'
                '    verb = argv[0]\n'
                '    if verb not in ("plan", "materialize"):\n'
                '        sys.stderr.write("--all applies to plan and '
                'materialize only\\n")\n'
                '        return 2\n'
                '    if verb == "plan":\n'
                '        return 0\n'
                '    return 1\n',
            # Prints the usage block, but the name is never dispatched on again -
            # a validated flag, not a verb - `ado-connect.py`'s `--transport`
            # check is exactly this shape.
            "validated_flag.py":
                'import sys\n'
                'USAGE = "usage: validated_flag.py --transport auto|mcp|az\\n"\n'
                'def main(argv):\n'
                '    transport_hint = argv[0]\n'
                '    if transport_hint not in ("auto", "mcp", "az"):\n'
                '        sys.stderr.write(USAGE)\n'
                '        return 2\n'
                '    return 0\n',
            # A single flag check is not a verb dispatch, and a membership test
            # against one literal is not "unknown among several" - neither owes
            # the hint, and a lint that fired on either would be unusable on this
            # tree's many `"--flag" in argv` checks.
            "flag_only.py":
                'def main(argv):\n'
                '    if "--json" not in argv:\n'
                '        return 1\n'
                '    return 0\n',
            "single_literal.py":
                'import sys\n'
                'def main(argv):\n'
                '    if argv[0] not in ("list",):\n'
                '        sys.stderr.write("usage\\n")\n'
                '        return 2\n'
                '    return 0\n',
            # The usage block written inside a FORMAT EXPRESSION, one level
            # below the call argument itself - the shape this tree's own
            # migrate-manifest.py and resolve-ado-parent.py write
            # (`"%s\\n%s\\n" % (err, _USAGE)`), which a check that only read a
            # bare `ast.Name` argument would miss.
            "format_bare.py":
                'import sys\n'
                '_USAGE = "usage: format_bare.py <verb>\\n"\n'
                'def main(argv):\n'
                '    verb = argv[0]\n'
                '    err = "bad verb"\n'
                '    if verb not in ("list", "plan", "drop"):\n'
                '        sys.stderr.write("%s\\n%s\\n" % (err, _USAGE))\n'
                '        return 2\n'
                '    if verb == "list":\n'
                '        return 0\n'
                '    return 1\n',
            # The allow twin for the format-expression shape - same format
            # expression, the hint called in the branch.
            "format_hinted.py":
                'import sys\n'
                'import _claude_home\n'
                '_USAGE = "usage: format_hinted.py <verb>\\n"\n'
                'def main(argv):\n'
                '    verb = argv[0]\n'
                '    err = "bad verb"\n'
                '    if verb not in ("list", "plan", "drop"):\n'
                '        sys.stderr.write("%s\\n%s\\n" % (err, _USAGE))\n'
                '        hint = _claude_home.usage_hint(None, None, None, None)\n'
                '        sys.stderr.write("\\n".join(hint))\n'
                '        return 2\n'
                '    if verb == "list":\n'
                '        return 0\n'
                '    return 1\n',
        }
        for rel, text in vd_fixtures.items():
            with open(os.path.join(vd, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        vd_found = L.usage_hint_violations((vd,))
        vd_where = sorted((rel, line) for rel, line, _why in vd_found)
        check("vd1 a hand-parsed unknown-verb branch that never calls "
              "_claude_home.usage_hint is named by file and line: %r" % (vd_where,),
              ("bare.py", 5) in vd_where)
        check("vd2 ...its why says what is missing: %r" % (vd_found,),
              any(rel == "bare.py" and why and "usage_hint" in why
                  for rel, _line, why in vd_found))
        check("vd3 the allow twin - same shape, the hint called in the branch - "
              "stays quiet, and so do a dispatched-but-ordinary refusal, a "
              "usage-printing but never-dispatched flag, a single-flag check "
              "and a one-literal membership test: %r" % (vd_where,),
              vd_where == [("bare.py", 5), ("format_bare.py", 6)])
        check("vd5 the usage block written inside a FORMAT EXPRESSION - "
              "`\"%%s\\n%%s\\n\" %% (err, _USAGE)` - is read the same as a bare "
              "name argument, and is named by file and line: %r" % (vd_where,),
              ("format_bare.py", 6) in vd_where)
        check("vd6 ...and its allow twin - the identical format expression, the "
              "hint called in the branch - stays quiet: %r" % (vd_where,),
              ("format_hinted.py", 6) not in vd_where)
    finally:
        shutil.rmtree(vd, ignore_errors=True)

    real_verb_dispatch = L.verb_dispatch_sites(M.lint_py_files(M.SCRIPTS_DIR))
    check("vd4 no hand-parsed dispatcher under scripts/ refuses an unknown verb "
          "without calling the usage hint: %r"
          % ([r for r in real_verb_dispatch if r[2]],),
          all(why is None for _rel, _line, why in real_verb_dispatch))

    # --------------------------------------------------------- house-style AST bans
    # Same shape as the adoption-lint block above: a fixture directory per case, each
    # proving the checker actually reads the construct rather than merely never having
    # seen one. A ban whose case never turns red before the implementation exists is a
    # decoration, not a check.
    style = tempfile.mkdtemp(prefix="audit-style-")
    try:
        with open(os.path.join(style, "walrus.py"), "w", encoding="utf-8") as fh:
            fh.write("if (n := 3) > 0:\n    print(n)\n")
        with open(os.path.join(style, "future.py"), "w", encoding="utf-8") as fh:
            fh.write("from __future__ import annotations\n")
        with open(os.path.join(style, "typing_import.py"), "w", encoding="utf-8") as fh:
            fh.write("import typing\n")
        with open(os.path.join(style, "typing_from.py"), "w", encoding="utf-8") as fh:
            fh.write("from typing import Optional\n")
        with open(os.path.join(style, "dataclasses_import.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("import dataclasses\n")
        with open(os.path.join(style, "dataclasses_from.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("from dataclasses import dataclass\n")
        with open(os.path.join(style, "ann_param.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def f(value: str):\n    return value\n")
        with open(os.path.join(style, "ann_return.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def f(value) -> str:\n    return value\n")
        with open(os.path.join(style, "ann_assign.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("count: int = 0\n")
        with open(os.path.join(style, "ann_star.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def f(*rest: str, **kw: int):\n    return rest, kw\n")
        with open(os.path.join(style, "clean.py"), "w", encoding="utf-8") as fh:
            fh.write('def f(n, m=1):\n    return n + m\n')
        with open(os.path.join(style, "broken.py"), "w", encoding="utf-8") as fh:
            fh.write("def f(:\n")

        hits = L.house_style_violations((style,))
        by_file = {}
        for fname, line, what in hits:
            by_file.setdefault(fname, []).append(what)

        check("g1 the walrus operator is named as its own construct, not lumped in "
              "with everything else", any("walrus" in w for w in
              by_file.get("walrus.py", [])))
        check("g2 `from __future__ import ...` is caught even though it is legal "
              "3.8 syntax a version gate would wave through", any(
              "__future__" in w for w in by_file.get("future.py", [])))
        check("g3 `import typing` is caught", any(
              w == "import typing" for w in by_file.get("typing_import.py", [])))
        check("g4 `from typing import ...` is caught", any(
              "typing" in w for w in by_file.get("typing_from.py", [])))
        check("g5 `import dataclasses` is caught", any(
              w == "import dataclasses" for w in
              by_file.get("dataclasses_import.py", [])))
        check("g6 `from dataclasses import ...` is caught", any(
              "dataclasses" in w for w in by_file.get("dataclasses_from.py", [])))
        check("g7 a clean file with none of the four constructs is not named",
              "clean.py" not in by_file)
        check("g8 a file that will not parse is reported, not silently skipped - "
              "same rule entries_missing_guard already follows",
              "broken.py" in by_file)
        # ---- annotations: the half the rule claimed and nothing enforced -------
        # `CLAUDE.md` named this function as the enforcer of "no annotations" the
        # whole time and it read only walrus and two import shapes. The tree had
        # 113 of them, all in hooks/, and the check stayed green under a mutation
        # that added one. All THREE shapes are asserted separately, because a rule
        # written as "no annotations" that reads one of three is the same defect
        # one step smaller.
        check("ga1 an annotated PARAMETER is caught, and named with the parameter "
              "so a reader can find it: %r" % (by_file.get("ann_param.py"),),
              any("annotated parameter" in w and "value" in w
                  for w in by_file.get("ann_param.py", [])))
        check("ga2 a RETURN annotation is caught, and named with the function: %r"
              % (by_file.get("ann_return.py"),),
              any("return annotation" in w and "f" in w
                  for w in by_file.get("ann_return.py", [])))
        check("ga3 an annotated ASSIGNMENT is caught - the shape with no function "
              "around it at all: %r" % (by_file.get("ann_assign.py"),),
              any("annotated assignment" in w
                  for w in by_file.get("ann_assign.py", [])))
        check("ga4 `*args` and `**kw` annotations are caught TOO, and that is what "
              "one branch over `ast.arg` buys: a version walking each FunctionDef's "
              "arg lists by hand looks complete and misses exactly these two: %r"
              % (by_file.get("ann_star.py"),),
              len([w for w in by_file.get("ann_star.py", [])
                   if "annotated parameter" in w]) == 2)
        check("ga5 ...while a clean signature WITH A DEFAULT is not named - the "
              "rule is the annotation, not the `=`, and stripping 113 of them left "
              "defaults behind everywhere",
              "clean.py" not in by_file)
        check("g9 every violation names a line number, so a failure can point at "
              "its offender rather than just its file",
              all(isinstance(line, int) and line > 0 for _, line, _ in hits
                  if _ != "broken.py"))
    finally:
        shutil.rmtree(style, ignore_errors=True)

    # The gate this half of the module exists for: scripts/, hooks/ and tests/, as
    # they stand, carry none of the bans - INCLUDING annotations, which is new and is
    # why 113 of them came out of hooks/ in the same change that added the rule.
    real_style = L.house_style_violations()
    check("g10 no scanned directory carries any house-style ban, annotations "
          "included: %r" % (real_style,), not real_style)

    # ------------------------------------------------- the lints reach a subdirectory
    # The rule these replace said `.py` must stay one directory deep BECAUSE the
    # scanners were flat - a file in a subdirectory silently stopped being checked.
    # A fixture tree proves the recursion rather than the docstring claiming it: one
    # clean file at the top, one banned import a level down, one entry point a level
    # down with no guard.
    rec = tempfile.mkdtemp(prefix="audit-output-rec-")
    try:
        with open(os.path.join(rec, "flat_ok.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        os.makedirs(os.path.join(rec, "usage"))
        with open(os.path.join(rec, "usage", "banned.py"), "w", encoding="utf-8") as fh:
            fh.write("import typing\nx = 1\n")
        with open(os.path.join(rec, "usage", "unguarded.py"), "w", encoding="utf-8") as fh:
            fh.write('import sys\nif __name__ == "__main__":\n    print("hi")\n')
        with open(os.path.join(rec, "usage", "clean_entry.py"), "w", encoding="utf-8") as fh:
            fh.write('import sys\nif __name__ == "__main__":\n    safe_stdio()\n'
                     '    print("hi")\n')

        found = M.py_files(rec)
        names = [n for n, _ in found]
        check("r1 py_files walks into a subdirectory and names the file by its "
              "RELATIVE path, so `usage/banned.py` cannot be mistaken for a "
              "top-level `banned.py` once folders exist: %r" % (names,),
              names == ["flat_ok.py", "usage/banned.py", "usage/clean_entry.py",
                        "usage/unguarded.py"])

        hs = L.house_style_violations([rec])
        check("r2 a banned import one directory down IS reported - the flat scan "
              "this replaced returned [] for exactly this tree: %r" % (hs,),
              any(n == "usage/banned.py" for n, _l, _w in hs))
        check("r3 ...and the clean files beside it are NOT reported. Reads vacuous, "
              "and is the only case that fails if the walk starts flagging "
              "everything it can now see: %r" % (hs,),
              not any(n in ("flat_ok.py", "usage/clean_entry.py")
                      for n, _l, _w in hs))

        missing = L.entries_missing_guard((rec,))
        check("r4 an entry point one directory down with no safe_stdio() guard is "
              "named: %r" % (missing,),
              "usage/unguarded.py" in missing)
        check("r5 ...and a guarded one a level down is not - the second direction "
              "for the guard check too: %r" % (missing,),
              "usage/clean_entry.py" not in missing)
    finally:
        shutil.rmtree(rec, ignore_errors=True)

    # ---------------------------------------- a count whose evidence was truncated
    # THE MOTIVATING CASE: the doctor told a live client repo that four tasks were
    # marked done with no completion record and then named three. The renderer
    # first, then the lint that keeps the shape from coming back.
    fits = M.some_of(["P12.2", "P12.3", "P12.10", "P12.14"])
    check("te1 a list inside the budget is rendered whole, with NO tail. THE "
          "SECOND-DIRECTION CASE for the whole family, and it is meant to read "
          "as vacuous: it is the only one that fails if the tail becomes "
          "unconditional, and the last id is the one the doctor used to drop: %r"
          % (fits,),
          fits == "P12.2, P12.3, P12.10, P12.14" and "more" not in fits)

    long_ids = ["P205.%09d" % (n,) for n in range(12)]
    over = M.some_of(long_ids)
    head, _sep, tail = over.rpartition(" and ")
    shown = [x for x in head.split(", ") if x]
    # A SLICE AND NEVER AN INDEX, because the input this reads is the thing under
    # test: a renderer that stopped emitting a tail - or emitted an empty string -
    # has to be THIS case going red, with the rendering quoted back. Indexing the
    # first token raises instead, and a raise here takes every case after it down
    # while naming none of them, which a mutation harness reads as a whole column
    # of checks catching one change when it was one crash.
    _te_tail = tail.split()[:1]
    hidden = int(_te_tail[0]) if _te_tail and _te_tail[0].isdigit() else -1
    check("te2 ...and one that does NOT fit says how many it left out, exactly. "
          "Read back off the rendering rather than compared with a number spelled "
          "here: shown plus hidden has to be the whole set, which is the property "
          "the motivating case broke and a hard-coded expectation would only "
          "restate: %r -> "
          "%d shown + %d hidden of %d"
          % (over, len(shown), hidden, len(long_ids)),
          hidden > 0 and len(shown) + hidden == len(long_ids)
          and all(i in over for i in shown))

    huge = M.some_of(["z" * (M.EVIDENCE_BUDGET * 2), "b", "c"])
    check("te3 the FIRST element is shown however long it is, and the rest are "
          "counted - a budget that can drop everything turns a finding into a "
          "bare number, which is the same defect one step further along: %r"
          % (huge[-24:],),
          huge.startswith("z" * 10) and huge.endswith(" and 2 more"))

    check("te4 `render=repr` reproduces each item's repr, so the sites that used "
          "to hand a bounded list to `%%r` lost nothing but the brackets - and an "
          "empty set renders empty rather than as a lone tail: %r / %r"
          % (M.some_of(["a", ""], render=repr), M.some_of([])),
          M.some_of(["a", ""], render=repr) == "'a', ''" and M.some_of([]) == "")

    tev = tempfile.mkdtemp(prefix="audit-output-tev-")
    try:
        def _wt(rel, text):
            with open(os.path.join(tev, rel), "w", encoding="utf-8") as fh:
                fh.write(text)

        # THE DEFECT: the count is the whole set, the slice is a prefix, and the
        # sentence says nothing about the difference.
        _wt("defect.py", 'def r(a):\n'
                         '    return "%d thing(s): %s" % (len(a), ", ".join(a[:3]))\n')
        # A bounded slice with NO count beside it. Still a truncation, and still
        # not this defect: nothing in the line is untrue.
        _wt("nocount.py", 'def r(a):\n'
                          '    return "thing(s): %s" % (", ".join(a[:3]),)\n')
        # A count beside a slice of something ELSE - an abbreviated SHA, which can
        # legitimately sit right next to the truncated-evidence shape in the same
        # file.
        _wt("other.py", 'def r(a, sha):\n'
                        '    return "%d thing(s): %s" % (len(a), sha[:12])\n')
        # The remainder stated, literal cap: `hooks/meter-usage.py`'s spelling,
        # written before `some_of()` existed and correct without it.
        _wt("says.py", 'def r(a):\n'
                       '    return "%d thing(s): %s%s" % (\n'
                       '        len(a), ", ".join(a[:3]),\n'
                       '        " +%d" % (len(a) - 3) if len(a) > 3 else "")\n')
        # ...and with a cap held in a VARIABLE: `_warning_groups`'s spelling.
        _wt("varcap.py", 'def r(a, limit):\n'
                         '    return "%s, +%d more" % (", ".join(a[:limit]),\n'
                         '                             len(a) - limit)\n')
        # The same variable cap with the remainder NOT stated.
        _wt("varsilent.py", 'def r(a, limit):\n'
                            '    return "%d thing(s): %s" % (len(a),\n'
                            '                                ", ".join(a[:limit]))\n')
        # The slice applied to a WRAPPED collection - `sorted(a)[:3]` beside
        # `len(a)` - a shape this tree's own truncating helpers really use, not
        # merely a hypothetical one.
        _wt("inner.py", 'def r(a):\n'
                        '    return "%d thing(s): %r" % (len(a), sorted(a)[:3])\n')

        hits = L.truncated_evidence_violations((tev,))
        named = dict((n, l) for n, l, _w3 in hits)
        check("te5 the defect is reported, by file and by the line the SLICE is "
              "on - the count is usually a line or two above it, and the slice is "
              "the half that needs changing: %r" % (sorted(named.items()),),
              named.get("defect.py") == 2)
        check("te6 a bounded slice with NO count beside it is silent. Nothing in "
              "that line is untrue, and a rule firing on it would fire on most "
              "of the truncations in this tree",
              "nocount.py" not in named)
        check("te7 a count beside a slice of a DIFFERENT thing is silent - an "
              "abbreviated SHA is width, not evidence dropped from the set being "
              "counted, and the two shapes can legitimately sit in adjacent lines "
              "of the same file", "other.py" not in named)
        check("te8 the remainder STATED is silent, in both spellings - a literal "
              "cap and one held in a variable. Read structurally: the tail phrase "
              "differs at those two sites, so a rule looking for the words would "
              "convict one of them for complying: %r"
              % (sorted(named),),
              "says.py" not in named and "varcap.py" not in named)
        check("te9 ...while the SAME variable cap with no remainder IS reported, "
              "which is what makes te8 a claim about the remainder rather than "
              "about literal caps: %r" % (named.get("varsilent.py"),),
              "varsilent.py" in named)
        check("te10 a slice of a WRAPPED collection is still a slice of it - "
              "`sorted(a)[:3]` beside `len(a)`. A key built from the outermost "
              "expression alone walks past this, and it is a shape this tree's "
              "own helpers are really spelled in", "inner.py" in named)
    finally:
        shutil.rmtree(tev, ignore_errors=True)

    check("te11 ...and the real tree carries none of the shape. This is the case "
          "that goes red the next time somebody prints a count over evidence they "
          "cut: %r" % (L.truncated_evidence_violations(),),
          L.truncated_evidence_violations() == [])

    # --------------------------------- a tool's output, cut at one end
    bc = tempfile.mkdtemp(prefix="audit-barecut-")
    try:
        def _bc(name, text):
            with open(os.path.join(bc, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        _bc("bare.py", 'def f(run_git):\n'
                       '    code, out, err = run_git(["status"])\n'
                       '    return (err or out).strip()[:200]\n')
        _bc("stream.py", 'def f(done):\n'
                         '    return done.stderr.decode("utf-8").strip()[:160]\n')
        _bc("getattr.py", 'def f(done):\n'
                          '    text = getattr(done, "stdout", "") or ""\n'
                          '    return text[:120]\n')
        _bc("sha.py", 'def f(run_git):\n'
                      '    code, out, err = run_git(["rev-parse", "HEAD"])\n'
                      '    return out.strip()[:12]\n')
        _bc("title.py", 'def f(title):\n'
                        '    return title.strip()[:200]\n')
        _bc("routed.py", 'def f(run_git, _excerpt):\n'
                         '    code, out, err = run_git(["status"])\n'
                         '    return _excerpt.reason_of(err, out)\n')
        _bc("tail.py", 'def f(run_git):\n'
                       '    code, out, err = run_git(["status"])\n'
                       '    return out.strip()[-200:]\n')
        got = dict((n, l) for n, l, _w in L.bare_output_cut_violations((bc,), ()))
        check("bc1 a head-only cut of a runner's output is reported by file and "
              "line, whether the name was bound from a runner, read off "
              "`.stderr` or fetched with getattr: %r" % (sorted(got.items()),),
              got.get("bare.py") == 3 and got.get("stream.py") == 2
              and got.get("getattr.py") == 3)
        check("bc2 ...and the allow cases are silent - an abbreviated SHA, a cut "
              "title, the helper's own call and a TAIL slice - each the one a "
              "widened rule would convict first: %r" % (sorted(got),),
              not ({"sha.py", "title.py", "routed.py", "tail.py"} & set(got)))
        held = L.bare_output_cut_violations((bc,), ("bare.py", "title.py"))
        check("bc3 a pending row silences its file, and a row naming a file with "
              "no such cut is itself reported, so the table cannot outlive its "
              "sites: %r" % (held,),
              not [h for h in held if h[0] == "bare.py"]
              and [h for h in held if h[0] == "title.py" and h[1] == 0])
    finally:
        shutil.rmtree(bc, ignore_errors=True)
    check("bc4 ...and the pending table is empty while the real tree still "
          "carries no head-only cut of output: %r pending, %r found"
          % (L.BARE_CUT_PENDING, L.bare_output_cut_violations()),
          L.BARE_CUT_PENDING == () and L.bare_output_cut_violations() == [])

    # ------------------------------------ text-mode writes name their newline
    nw = tempfile.mkdtemp(prefix="audit-newline-")
    try:
        def _nw(name, text):
            with open(os.path.join(nw, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        _nw("bare.py", 'def f(p):\n'
                       '    with open(p, "w", encoding="utf-8") as fh:\n'
                       '        fh.write("x")\n')
        _nw("fd.py", 'import os\n'
                     'def f(fd):\n'
                     '    return os.fdopen(fd, "w", encoding="utf-8")\n')
        _nw("kw.py", 'def f(p):\n'
                     '    return open(p, mode="a", encoding="utf-8")\n')
        _nw("plus.py", 'import io\n'
                       'def f(p):\n'
                       '    return io.open(p, "r+")\n')
        _nw("named.py", 'import os\n'
                        'def f(p, fd):\n'
                        '    a = open(p, "w", encoding="utf-8", newline="\\n")\n'
                        '    b = os.fdopen(fd, "w", encoding="utf-8", newline="")\n'
                        '    return a, b\n')
        _nw("binary.py", 'def f(p):\n'
                         '    return open(p, "wb")\n')
        _nw("read.py", 'def f(p):\n'
                       '    return open(p, "r", encoding="utf-8")\n')
        _nw("dynamic.py", 'def f(p, m):\n'
                          '    return open(p, m)\n')
        nw_got = dict((n, l) for n, l, _w in
                      L.text_write_newline_violations((nw,), ()))
        check("nw1 a text-mode open for writing with no newline is reported by "
              "file and line, whether it is open, os.fdopen, a keyword mode or "
              "an update mode: %r" % (sorted(nw_got.items()),),
              nw_got.get("bare.py") == 2 and nw_got.get("fd.py") == 3
              and nw_got.get("kw.py") == 2 and nw_got.get("plus.py") == 3)
        check("nw2 ...and the allow cases are silent - a newline named by "
              "keyword on either opener, a binary handle, a read, and a mode "
              "the lint cannot read; each is the one an over-wide rule "
              "convicts first: %r" % (sorted(nw_got),),
              not ({"named.py", "binary.py", "read.py", "dynamic.py"}
                   & set(nw_got)))
        nw_held = L.text_write_newline_violations(
            (nw,), ("bare.py", "read.py"))
        check("nw3 a pending row silences its file, and a row naming a file "
              "that holds no such write is itself reported, so the table can "
              "only shrink: %r" % (nw_held,),
              not [h for h in nw_held if h[0] == "bare.py"]
              and [h for h in nw_held if h[0] == "read.py" and h[1] == 0])
        # a hooks/-shaped directory: the same open convicts there too
        nw_hooks = os.path.join(nw, "hooks")
        os.mkdir(nw_hooks)
        with open(os.path.join(nw_hooks, "hook.py"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write('def f(p):\n    return open(p, "w", encoding="utf-8")\n')
        nw_hk = L.text_write_newline_violations((nw_hooks,), ())
        check("nw5 a bare text-mode write open in a hooks/ file is reported, "
              "and the default walk reaches the hooks directory: %r"
              % (nw_hk,),
              [h[:2] for h in nw_hk] == [("hook.py", 2)]
              and M.HOOKS_DIR in L.NEWLINE_DIRS
              and M.SCRIPTS_DIR in L.NEWLINE_DIRS)
        # a .claude/hooks-shaped directory: the same open convicts there too
        nw_proj = os.path.join(nw, ".claude", "hooks")
        os.makedirs(nw_proj)
        with open(os.path.join(nw_proj, "guard.py"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write('def f(p):\n    return open(p, "w", encoding="utf-8")\n')
        nw_pj = L.text_write_newline_violations((nw_proj,), ())
        nw_real = os.path.join(M.REPO_ROOT, ".claude", "hooks")
        check("nw6 a bare text-mode write in a .claude/hooks-shaped directory is "
              "reported, and the default walk reaches the repository's own "
              "project hooks whenever that directory exists: %r"
              % (nw_pj,),
              [h[:2] for h in nw_pj] == [("guard.py", 2)]
              and (nw_real in L.NEWLINE_DIRS) == os.path.isdir(nw_real))
    finally:
        shutil.rmtree(nw, ignore_errors=True)
    check("nw4...and the pending table holds no row and the real tree "
          "(scripts and hooks) opens no text handle for writing without a "
          "newline: %r pending, %r found"
          % (L.NEWLINE_PENDING, L.text_write_newline_violations()),
          not L.NEWLINE_PENDING and L.text_write_newline_violations() == [])

    # --------------------------- a shell script finds its dir on any $0
    sd = tempfile.mkdtemp(prefix="audit-shself-")
    try:
        def _sd(name, text):
            with open(os.path.join(sd, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        _sd("case.sh", '#!/bin/sh\ncase "$0" in\n  */*) here=${0%/*} ;;\nesac\n')
        _sd("dirname.sh", '#!/bin/sh\nhere=$(dirname "$0")\n')
        _sd("cut.sh", '#!/bin/sh\nhere=${0%/*}\n')
        _sd("good.sh", '#!/bin/sh\nself=$0\ncase "$self" in\n  */*) h=${self%/*} ;;\nesac\n')
        _sd("comment.sh", '#!/bin/sh\n# case "$0" in */*) and dirname "$0"\nx=1\n')
        _sd("notsh.txt", 'dirname "$0"\n')
        sd_got = L.sh_self_dir_violations(sd)
        sd_files = sorted(set(v[0] for v in sd_got))
        check("sd1 a shell script that works out its directory from a raw $0 "
              "is reported - by a case, by dirname and by a pattern cut, "
              "naming the line: %r" % (sd_got,),
              any(v[0] == "case.sh" and v[1] == 2 for v in sd_got)
              and "dirname.sh" in sd_files and "cut.sh" in sd_files)
        check("sd2 ...and the allow cases are silent - the normalised copy, a "
              "comment that names the pattern, and a file that is not a "
              "script: %r" % (sd_files,),
              not ({"good.sh", "comment.sh", "notsh.txt"} & set(sd_files)))
    finally:
        shutil.rmtree(sd, ignore_errors=True)
    check("sd3 ...and no tracked script in the real tree reads its own "
          "directory from a raw $0: %r" % (L.sh_self_dir_violations(),),
          L.sh_self_dir_violations() == [])

    # ------------------------------------------- the raw JSON writer, by name
    rw = tempfile.mkdtemp(prefix="audit-rawjson-")
    try:
        def _rw(rel, text):
            full = os.path.join(rw, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)

        _rw("manifest/_manifest_io.py",
            "def raw_atomic_write_json(path, obj, indent=2):\n    return None\n"
            "def atomic_write_json(path, obj, indent=2):\n"
            "    raw_atomic_write_json(path, obj)\n")
        _rw("called.py", "import _manifest_io as _mio\n"
                         "def save(p, o):\n"
                         "    _mio.raw_atomic_write_json(p, o)\n")
        _rw("aliased.py", "import _manifest_io as _mio\n"
                          "w = _mio.raw_atomic_write_json\n")
        _rw("listed.py", "import _manifest_io as _mio\n"
                         "def restore(p, o):\n"
                         "    _mio.raw_atomic_write_json(p, o, indent=2)\n"
                         "def other(p, o):\n"
                         "    _mio.atomic_write_json(p, o)\n")
        rw_table = (("scripts/listed.py", "restore", "byte-exact restore"),
                    ("scripts/gone.py", "vanished", "a site deleted since"))
        rw_hits = L.raw_json_writer_violations(rw, "", table=rw_table)
        rw_files = sorted(set(f for f, _w in rw_hits))
        check("rj1 a reach of the raw writer from a site the table does not "
              "name is reported - a call inside a function, and an alias bound "
              "at module level, which a call-only scan would read past: %r"
              % (rw_hits,),
              "scripts/called.py" in rw_files and "scripts/aliased.py" in rw_files
              and any("(save)" in w for f, w in rw_hits
                      if f == "scripts/called.py"))
        check("rj2 ALLOW: the site the table names is silent, and so is the "
              "scrubbing writer beside it in the same file, and the home module "
              "that defines and calls the raw writer - a lint that ignored the "
              "table, or read `atomic_write_json` as the raw name, fails here: %r"
              % (rw_hits,),
              "scripts/listed.py" not in rw_files
              and "scripts/manifest/_manifest_io.py" not in rw_files)
        check("rj3 a table row whose site no longer reaches the raw writer is "
              "reported, so the table cannot carry permission for a site nobody "
              "wrote: %r" % (rw_hits,),
              any(f == "scripts/gone.py" and "vanished" in w for f, w in rw_hits))
        os.remove(os.path.join(rw, "manifest", "_manifest_io.py"))
        rw_blind = L.raw_json_writer_violations(rw, "", table=())
        check("rj4 a tree whose home module defines no raw writer is reported "
              "BLIND, never clean: %r" % (rw_blind,),
              any(f == "<tree>" and "blind" in w for f, w in rw_blind))
    finally:
        shutil.rmtree(rw, ignore_errors=True)

    check("rj5 ...and the real tree reaches the raw writer only from the sites "
          "RAW_JSON_WRITERS names, each of which still does: %r"
          % (L.raw_json_writer_violations(),),
          L.raw_json_writer_violations() == [])

    # ------------------------------------------------ the returns writer
    rt = tempfile.mkdtemp(prefix="returns-writer-")
    try:
        def _rt(rel, text):
            full = os.path.join(rt, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)

        home = ("def scrubbed_return_text(p, t):\n    return t\n"
                "def file_once(path, text):\n"
                "    text = scrubbed_return_text(path, text)\n"
                "    open(path, 'x').write(text)\n"
                "def return_path(e, t, r):\n    return e\n")
        _rt("manifest/_filed_returns.py", home)
        _rt("bypass.py", "import _filed_returns as _fr\n"
                         "def file(e, t, text):\n"
                         "    path = _fr.return_path(e, t, 'executor')\n"
                         "    with open(path, 'w') as fh:\n"
                         "        fh.write(text)\n")
        _rt("reads.py", "import _filed_returns as _fr\n"
                        "def read(e, t):\n"
                        "    path = _fr.return_path(e, t, 'executor')\n"
                        "    with open(path, 'r') as fh:\n"
                        "        return fh.read()\n"
                        "def other(p, text):\n"
                        "    with open(p, 'w') as fh:\n"
                        "        fh.write(text)\n")
        rt_hits = L.returns_writer_violations(rt)
        rt_files = sorted(set(f for f, _w in rt_hits))
        check("rw1 a function that builds a filed return's path and writes the "
              "file itself is reported, naming the function: %r" % (rt_hits,),
              rt_files == ["scripts/bypass.py"]
              and any("(file)" in w for _f, w in rt_hits))
        check("rw2 ALLOW: a reader that builds the same path, a writer that "
              "builds no return path, and the home module that does both are "
              "silent - a lint keyed on either half alone fails here: %r"
              % (rt_hits,),
              "scripts/reads.py" not in rt_files
              and "scripts/manifest/_filed_returns.py" not in rt_files)
        _rt("manifest/_filed_returns.py",
            home.replace("    text = scrubbed_return_text(path, text)\n", ""))
        rt_unscrubbed = L.returns_writer_violations(rt)
        check("rw3 a home writer that no longer calls the scrub is reported: %r"
              % (rt_unscrubbed,),
              any(f == "scripts/manifest/_filed_returns.py" and "scrub" in w
                  for f, w in rt_unscrubbed))
        os.remove(os.path.join(rt, "manifest", "_filed_returns.py"))
        check("rw4 a tree without the home module is BLIND, never clean: %r"
              % (L.returns_writer_violations(rt),),
              any(f == "<tree>" and "blind" in w
                  for f, w in L.returns_writer_violations(rt)))
    finally:
        shutil.rmtree(rt, ignore_errors=True)
    check("rw5 ...and the real tree files a return only through the scrubbing "
          "writer: %r" % (L.returns_writer_violations(),),
          L.returns_writer_violations() == [])

    # ------------------------------------------------------------ selftest coverage
    # Every case builds its own tree: the classifier is asked about a FIXTURE through
    # its keyword arguments, so the real tree's answer cannot leak into it and a case
    # cannot be green because the real tree happens to be clean.
    sc_root = tempfile.mkdtemp(prefix="audit-coverage-")
    try:
        def _sc_tree(shipped, hooks, tests):
            """A `scripts/`, `hooks/` and `tests/` under `sc_root`, each holding the
            named files (empty bodies: the classifier reads names, not source)."""
            for sub, names in (("scripts", shipped), ("hooks", hooks), ("tests", tests)):
                d = os.path.join(sc_root, sub)
                if os.path.isdir(d):
                    shutil.rmtree(d)
                os.makedirs(d)
                for name in names:
                    with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                        fh.write("\n")
            return dict(script_dir=os.path.join(sc_root, "scripts"),
                        hooks_dir=os.path.join(sc_root, "hooks"),
                        tests_dir=os.path.join(sc_root, "tests"))

        _kw = _sc_tree(["_a.py", "b-c.py", "tested.py"], ["h.py"],
                       ["test__a.py", "test_b_c.py", "test_tested.py", "test_h.py"])
        _c = L.selftest_coverage(**_kw)
        check("sc1 a module with its tests/test_<name>.py is covered, a hyphen reads as "
              "an underscore, and a clean tree has no defects and says how many it "
              "looked at - so an empty walk cannot print the same way",
              _c["covered"] == ["hooks/h.py", "scripts/_a.py", "scripts/b-c.py",
                                "scripts/tested.py"]
              and _c["defects"] == [] and _c["total"] == 4, repr(_c))
        _kw = _sc_tree(["_a.py", "lonely.py"], [], ["test__a.py"])
        _c = L.selftest_coverage(**_kw)
        check("sc2 a shipped module with NEITHER a test file NOR a named exemption is "
              "uncovered, and that is a defect that names the file - the case the "
              "retired either/or rule let through",
              _c["uncovered"] == ["scripts/lonely.py"]
              and _c["defects"] == ["uncovered scripts/lonely.py"], repr(_c))
        _c = L.selftest_coverage(exempt={"scripts/lonely.py": "no logic of its own"}, **_kw)
        check("sc3 ...a NAMED exemption takes it out of the defects and into `exempt`, "
              "where a review can read the debt",
              _c["uncovered"] == [] and _c["exempt"] == ["scripts/lonely.py"]
              and _c["defects"] == [], repr(_c))
        _c = L.selftest_coverage(exempt={"scripts/_a.py": "x", "scripts/gone.py": "y"}, **_kw)
        check("sc4 ...and an exemption that names a module that is gone, or one that has "
              "a test file after all, is itself a defect, so the table cannot outlive "
              "its premise",
              sorted(_c["stale_exempt"]) == ["scripts/_a.py (has a test file)",
                                             "scripts/gone.py (no such module)"]
              and all(d.startswith("stale_exempt") or d.startswith("uncovered")
                      for d in _c["defects"]), repr(_c))
        _kw = _sc_tree(["a-b.py", "a_b.py"], [], ["test_a_b.py", "test_nobody.py"])
        _c = L.selftest_coverage(**_kw)
        check("sc5 two modules mapping to one test name are a collision, and a test "
              "file naming no module is an orphan - and `_harness.py` is neither",
              len(_c["collisions"]) == 1 and "a-b.py" in _c["collisions"][0]
              and _c["orphans"] == ["tests/test_nobody.py"], repr(_c))
        _kw = _sc_tree(["_a.py"], [], ["test__a.py", "_harness.py"])
        check("sc6 the helper every suite imports is not a test file, so it is not an "
              "orphan candidate",
              L.selftest_coverage(**_kw)["orphans"] == [])
    finally:
        _harness.remove_tree(sc_root)
    _real = L.selftest_coverage()
    check("sc7 the real tree: every shipped module and every development module whose "
          "cases live in tests/ has a suite or a named exemption, and the walk "
          "classified more than a handful, so a clean answer is not an empty one: %s"
          % (_real["defects"],),
          _real["defects"] == [] and _real["total"] > 100)
    check("sc8 NO FILE IS CLASSIFIED MIGRATED any more - the classes are covered, "
          "exempt and the four defects, and the helpers that spoke the old vocabulary "
          "are gone, so nothing can read a file as listed-and-skipped",
          sorted(_real) == sorted(["covered", "exempt", "uncovered", "stale_exempt",
                                   "orphans", "collisions", "defects", "total"])
          and not hasattr(L, "covered_repo_paths")
          and not hasattr(L, "_carries_inline_selftest"), repr(sorted(_real)))
    _else = L.suite_elsewhere_paths()
    check("sc9 the development modules the sweep must not run are named, they exist, "
          "and none of them is a shipped file: %r" % (_else[:3],),
          _else and all(os.path.isfile(os.path.join(M.REPO_ROOT, p)) for p in _else)
          and not any(p.startswith("plugins/") for p in _else)
          and "tools/bench-report.py" in _else and "tools/lints/_deps.py" in _else
          and "tools/demo/gen-demo-usage.py" in _else)

    # ------------- the two lint modules are still read by the dialect rules (`ln*`)
    # They were `scripts/` files, so every default-scope lint covered them; after the
    # move each of those defaults has to NAME the directory or the rule quietly checks
    # fewer files. A fixture directory stands in for `LINTS_DIR` - the functions read
    # the module global at CALL time, so rebinding it is how a violation is planted
    # where only the new scope would look - and each lint is run twice, once over a
    # clean file and once over a planted one, so a lint that fires on any file in the
    # directory (or on none) fails one of the two.
    ln_dir = tempfile.mkdtemp(prefix="audit-lints-scope-")
    ln_real = L.LINTS_DIR
    try:
        with open(os.path.join(ln_dir, "clean_lint.py"), "w", encoding="utf-8") as fh:
            fh.write('"""A lint module with nothing wrong."""\n'
                     "from _output import safe_stdio\n\n\n"
                     'if __name__ == "__main__":\n    safe_stdio()\n')
        L.LINTS_DIR = ln_dir
        ln_clean = (L.house_style_violations(), L.entries_missing_guard(),
                    L.truncated_evidence_violations(),
                    L.usage_hint_violations(), L.bare_output_cut_violations())
        with open(os.path.join(ln_dir, "planted_lint.py"), "w", encoding="utf-8") as fh:
            fh.write("def f(x: int):\n    return x\n\n\n"
                     'if __name__ == "__main__":\n    print("no guard first")\n')
        ln_planted = (L.house_style_violations(), L.entries_missing_guard())
    finally:
        L.LINTS_DIR = ln_real
        shutil.rmtree(ln_dir, ignore_errors=True)
    check("ln1 a clean module in the lints directory is reported by NONE of the "
          "default-scope dialect and hygiene rules - the allow direction: %r"
          % (ln_clean,), all(r == [] for r in ln_clean))
    check("ln2 ...and a module there that carries an annotation and prints before "
          "`safe_stdio()` is reported by the dialect rule AND the guard rule, by "
          "name - so the directory is in their default scope, not just on disk: %r"
          % (ln_planted,),
          any(name.endswith("planted_lint.py") for name, _l, _w in ln_planted[0])
          and "planted_lint.py" in ln_planted[1])
    check("ln3 the newline and encoding rules read the directory too, through the "
          "tuples they walk: %r" % ((L.NEWLINE_DIRS, L.ENCODING_DIRS),),
          M.LINTS_DIR in L.NEWLINE_DIRS and M.LINTS_DIR in L.ENCODING_DIRS)

    # ------------------------------------------------- the pinned path preamble
    check("pp1 the real tree carries the preamble exactly once in every `.py` "
          "under scripts/, above every sibling import: %r"
          % (L.path_preamble_violations(),),
          L.path_preamble_violations() == [])
    check("pp2 ...and `_output.py` is exempt BY NAME rather than by passing: it IS the "
          "anchor the preamble walks up to, so it carries the text zero times and a "
          "count-based rule that exempted nothing would name it - the case that says "
          "the exemption is deliberate, not a coincidence",
          L._PREAMBLE_EXEMPT == "_output.py"
          and open(M.__file__, encoding="utf-8").read().count(L.PATH_PREAMBLE) == 0)
    check("pp3 the preamble is depth-INDEPENDENT by construction: it walks up "
          "looking for the marker file and spells no `dirname(dirname(`, no `..` "
          "and no count of levels",
          "_output.py" in L.PATH_PREAMBLE
          and "while not os.path.isfile" in L.PATH_PREAMBLE
          and "dirname(os.path.dirname" not in L.PATH_PREAMBLE
          and '".."' not in L.PATH_PREAMBLE)
    check("pp4 it terminates at the filesystem root with a NAMED ImportError "
          "rather than looping - the failure a bootstrap must not have",
          "raise ImportError" in L.PATH_PREAMBLE
          and "_anchor_up == _anchor_dir" in L.PATH_PREAMBLE)
    check("pp5 it carries no `# --- name ---` banner. `_deps._NAV_HEADER_RE` "
          "matches those at column 0, so a banner in every file would let a "
          "2,000-line module satisfy navigability_violations() on boilerplate",
          not any(re.match(r"^# --- (.+?) -+\s*$", ln)
                  for ln in L.PATH_PREAMBLE.split("\n")))
    _entries = [(r, open(p, encoding="utf-8").read()) for r, p in M.script_files()
                if os.path.basename(r) != L._PREAMBLE_EXEMPT]
    _entries = [(r, t) for r, t in _entries if '__name__ == "__main__"' in t]
    check("pp6 the __main__ blocks were NOT rewritten: all %d of them still spell "
          "`from _output import safe_stdio`, and NOTHING in scripts/ calls it as "
          "`_output.safe_stdio()`. That would be an ast.Attribute call, which "
          "`_call_lines` does not recognise, and entries_missing_guard() would "
          "then name every entry point in the tree" % (len(_entries),),
          len(_entries) > 30
          and all("from _output import safe_stdio" in t for _r, t in _entries)
          and not any("_output.safe_stdio" in t for _r, t in _entries))

    # The three ways the lint has to go red, each built as a file rather than
    # reasoned about. A lint only ever seen returning [] is a lint that might be
    # returning [] because it looks at nothing.
    pre = tempfile.mkdtemp(prefix="audit-preamble-")
    try:
        _good = ("import os\nimport sys\n\n" + L.PATH_PREAMBLE
                 + "\nimport _sibling  # noqa: E402\n")
        with open(os.path.join(pre, "_output.py"), "w", encoding="utf-8") as fh:
            fh.write("SCRIPTS_DIR = 1\n")
        # The sibling carries the preamble too: it is a `.py` under the fixture
        # `scripts/` and the rule applies to it, so leaving it bare would put a
        # fourth name in the expected list for a reason unrelated to any case.
        with open(os.path.join(pre, "_sibling.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + L.PATH_PREAMBLE + "\nx = 1\n")
        with open(os.path.join(pre, "ok.py"), "w", encoding="utf-8") as fh:
            fh.write(_good)
        with open(os.path.join(pre, "missing.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\nimport _sibling\n")
        with open(os.path.join(pre, "doubled.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + L.PATH_PREAMBLE + "\n"
                     + L.PATH_PREAMBLE + "\nimport _sibling  # noqa: E402\n")
        with open(os.path.join(pre, "too_late.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\nimport _sibling  # noqa: E402\n\n"
                     + L.PATH_PREAMBLE)
        # The shape a whole-block count CANNOT see: one correct preamble
        # followed by a repeat of its last two statements. The files under
        # `panel/` carried exactly this while the lint returned nothing for them.
        # The tail is SLICED off `PATH_PREAMBLE` rather than typed out - a fixture
        # spelling it again is a second copy of the bytes the rule is about.
        # `.find` and never `.index`, for the reason te2 slices rather than
        # indexes: a pinned preamble that no longer carries this statement is
        # pp14 going red, not a ValueError that takes pp7-pp13 and every case
        # after them down without naming one of them.
        _tail_at = L.PATH_PREAMBLE.find("\nimport _output")
        check("pp14 the statement the partial fixture is SLICED at is still in "
              "the pinned preamble - the fixture repeats the preamble's own tail "
              "rather than spelling those bytes a second time, so an anchor that "
              "moved would leave pp11 and pp12 grading a file nobody meant to "
              "write: %r" % (L.PATH_PREAMBLE[-60:],),
              _tail_at >= 0)
        _tail = L.PATH_PREAMBLE[_tail_at:] if _tail_at >= 0 else L.PATH_PREAMBLE
        with open(os.path.join(pre, "partial.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + L.PATH_PREAMBLE + _tail
                     + "\nimport _sibling  # noqa: E402\n")
        # ...and the file that must NOT be named: it MENTIONS a preamble line
        # inside a longer line, once in a docstring and once in a commented
        # one-liner. `_loader.py` and `panel-server.py` do exactly that in the
        # live tree, which is why the repeat check is whole-line equality.
        with open(os.path.join(pre, "prose.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + L.PATH_PREAMBLE
                     + '\ndef _why():\n'
                       '    """Folders are labels: _output.install_path() adds '
                       'each one."""\n'
                       '    return None\n\n'
                       '#   import _output;_output.install_path();import _x as u\n')
        hits = {}
        for name, why in L.path_preamble_violations(pre):
            hits.setdefault(name, []).append(why)
        check("pp7 a file with NO preamble is named, and the message says how many "
              "it has rather than only that something is wrong: %r"
              % (hits.get("missing.py"),),
              any("0 times" in w for w in hits.get("missing.py", []))
              and any("never calls _output.install_path()" in w
                      for w in hits.get("missing.py", [])))
        check("pp8 a DOUBLED preamble is named too - counted, not tested for "
              "membership, because `in` cannot tell one occurrence from two and "
              "two is a second walk-up and a second install: %r"
              % (hits.get("doubled.py"),),
              any("2 times" in w for w in hits.get("doubled.py", [])))
        check("pp9 a preamble placed BELOW the sibling import it exists to enable "
              "is named. It is exactly once, so the count says nothing; only the "
              "AST ordering check fires: %r" % (hits.get("too_late.py"),),
              any("above the _output.install_path()" in w
                  for w in hits.get("too_late.py", []))
              and not any("times" in w for w in hits.get("too_late.py", [])))
        check("pp10 ...and the correct file is NOT named. Reads vacuous beside the "
              "three above and is the only case that fails if the lint starts "
              "reporting everything: %r" % (sorted(hits),),
              "ok.py" not in hits and sorted(hits) == ["doubled.py", "missing.py",
                                                       "partial.py",
                                                       "too_late.py"])
        check("pp11 a file carrying ONE preamble and then repeating its TAIL "
              "is named. The whole-block count finds one occurrence and says "
              "nothing, so only the line check fires - the same division of "
              "labour pp9 pins the other way round: %r" % (hits.get("partial.py"),),
              any("repeats a line of the pinned path preamble" in w
                  for w in hits.get("partial.py", []))
              and not any("times" in w for w in hits.get("partial.py", [])))
        _partial = open(os.path.join(pre, "partial.py"), encoding="utf-8").read()
        _repeated = L._preamble_line_repeats(_partial)
        _tail_lines = [ln for ln in _tail.splitlines() if ln.strip()]
        _both = [n for n, ln in enumerate(_partial.splitlines(), 1)
                 if ln in _tail_lines]
        check("pp12 ...and the lines it names are the LATER occurrences, never "
              "the first. Each tail statement is in that file twice and exactly "
              "the second half comes back, which is what tells a reader which "
              "lines to delete rather than only that something is doubled: "
              "%r out of %r" % (_repeated, _both),
              len(_both) == 2 * len(_tail_lines)
              and _repeated == _both[len(_tail_lines):])
        check("pp13 ...and a file MENTIONING a preamble line inside a LONGER line "
              "is not named. `_loader.py` and `panel-server.py` each do that in "
              "the live tree, so a repeat counted with `in` instead of by "
              "whole-line equality convicts two correct files - and this is the "
              "only case that fails if the check widens to a substring: %r"
              % (hits.get("prose.py"),),
              "prose.py" not in hits)
    finally:
        shutil.rmtree(pre, ignore_errors=True)

    # ------------------------------------------------ the self-location lint
    check("ds1 no `.py` under scripts/ reads `__file__` outside the pinned "
          "preamble any more - the seventeen sites are gone and this is what "
          "stops the eighteenth: %r" % (L.depth_sensitive_paths(),),
          L.depth_sensitive_paths() == [])
    dsl = tempfile.mkdtemp(prefix="audit-depth-")
    try:
        with open(os.path.join(dsl, "clean.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + L.PATH_PREAMBLE + "\nx = 1\n")
        # The TWO-STEP shape, which is how sixteen of the seventeen were actually
        # written. A lint looking for `dirname(dirname(` nested in one expression
        # passes this file, which is why the rule is "no __file__ at all".
        with open(os.path.join(dsl, "two_step.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + L.PATH_PREAMBLE
                     + '\n_HERE = os.path.dirname(os.path.abspath(__file__))\n'
                       'HOOKS = os.path.join(os.path.dirname(_HERE), "hooks")\n')
        with open(os.path.join(dsl, "nested.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + L.PATH_PREAMBLE
                     + '\nR = os.path.dirname(os.path.dirname(os.path.abspath'
                       '(__file__)))\n')
        with open(os.path.join(dsl, "own_name.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + L.PATH_PREAMBLE
                     + '\nUSAGE = "usage: %s" % os.path.basename(__file__)\n')
        found = {}
        for name, line, _why in L.depth_sensitive_paths(dsl):
            found.setdefault(name, []).append(line)
        check("ds2 the TWO-STEP form is caught - `_HERE = dirname(abspath(...))` "
              "on one line and `dirname(_HERE)` on the next was how sixteen of the "
              "seventeen sites were written, and a nesting-only rule passes it: %r"
              % (found.get("two_step.py"),), "two_step.py" in found)
        check("ds3 the nested form is caught too", "nested.py" in found)
        check("ds4 `os.path.basename(__file__)` is NOT caught - it yields a NAME, "
              "not a location, and panel-server.py prints its own filename in a "
              "usage line", "own_name.py" not in found)
        check("ds5 a file carrying only the pinned preamble is NOT caught, though "
              "the preamble itself spells `dirname(abspath(__file__))`. The block "
              "is cut out before the scan; without that every file in the tree "
              "would be a violation and the lint would be uninstallable",
              "clean.py" not in found and sorted(found) == ["nested.py",
                                                            "two_step.py"])
    finally:
        shutil.rmtree(dsl, ignore_errors=True)

    # --- tk: the tokenizer is memoised, and the memo is honest -----------------
    # Profiled with cProfile, `_tokenize` was the hottest function in this suite,
    # entered several times per line: as the line itself, again inside
    # `_historical_sentences`, and again as its neighbours' `preceding` and
    # `following`. A bounded LRU catches the repeats. Two cases, because a cache
    # on an impure function is a wrong answer that arrives fast - and tk1 is
    # guarded so that REMOVING the memo fails one case by name instead of raising
    # on `cache_info` and taking the rest of this suite down with it.
    _tk_line = "Its 3 cases stayed at 17; see tools/x.py. Then 2 more."
    _tk_memo = hasattr(L._tokenize, "cache_info")
    if _tk_memo:
        L._tokenize.cache_clear()
    _tk_a = L._tokenize(_tk_line)
    _tk_h0 = L._tokenize.cache_info().hits if _tk_memo else None
    _tk_b = L._tokenize(_tk_line)
    _tk_h1 = L._tokenize.cache_info().hits if _tk_memo else None
    check("tk0 the memo does not LIE: a cleared cache and a served one give the "
          "same tokens and the same sentence ordinals (%r)"
          % (_tk_a["words"][:4],),
          _tk_a == _tk_b and bool(_tk_a["words"])
          and len(_tk_a["words"]) == len(_tk_a["sentence"]))
    check("tk1 ...and it is IN USE: the second call on the same line is a hit and "
          "not a second walk (hits %r -> %r)" % (_tk_h0, _tk_h1),
          _tk_memo and _tk_h1 == _tk_h0 + 1)

    # --- pn: numbers written into prose (the rot this repo keeps meeting) -----
    _pn_live = L.prose_number_claims()
    check("pn0 no `.py` this repo keeps writes a present-tense number into its "
          "prose - every one of these has a live source one command away, so a "
          "copy in a docstring has no reader and nothing comparing it: %r"
          % (_pn_live[:6],),
          _pn_live == [])
    # Vacuity FIRST, because "no claims" and "read no files" print identically.
    #
    # TWO TERMS - one absolute, one derived - and the second one is not derived
    # from the thing it measures. `scan_floor()` holds the scanned set against
    # the CANDIDATE count the same walk produced, which catches an exemption row
    # that grew to swallow a directory but cannot catch the walk itself collapsing
    # - both fall together. So the other half of this case is a PLAIN recursive
    # walk of the three directories that have to exist, which needs no
    # `.gitignore` and so cannot fail the way the derivation can: if the pruning
    # ever starts eating the plugin, the derived set drops below a walk that
    # knows nothing about it.
    _pn_scan = L.prose_scan_set((".py",))
    _pn_plain = (len(M.py_files(M.SCRIPTS_DIR)) + len(M.py_files(M.HOOKS_DIR))
                 + len(M.py_files(M.TESTS_DIR)))
    check("pn1 the walk that produced pn0 read the tree, by two measures that "
          "fail differently - %d file(s) scanned of %d candidate(s), floor %d, "
          "against %d found by a plain walk that reads no `.gitignore`"
          % (len(_pn_scan["paths"]), _pn_scan["candidates"],
             L.scan_floor(_pn_scan["candidates"]), _pn_plain),
          _pn_scan["problem"] is None
          and len(_pn_scan["paths"]) >= L.scan_floor(_pn_scan["candidates"])
          and _pn_scan["candidates"] >= _pn_plain)
    check("pn2 CARDINALITY is caught, in each of the four shapes",
          L._prose_number_claim("its 124 cases live in `tests/test_x.py`")
              == "its 124 cases"
          and L._prose_number_claim("11 cases live in the suite")
              == "11 cases live in"
          and L._prose_number_claim("Config `x`. `--selftest` (26 cases).")
              == "--selftest (26 cases)"
          and L._prose_number_claim("the migration finished, all 64 of them")
              == "all 64 of them")
    check("pn3 the REPAIR is not itself a finding - dropping the number is the "
          "fix for all three families, so every fixed line must read clean or "
          "the lint would forbid its own remedy",
          L._prose_number_claim("its cases live in `tests/test_x.py`") is None
          and L._prose_number_claim("`--selftest`.") is None
          and L._prose_number_claim("the migration finished, all of them") is None
          and L._prose_number_claim("`KNOWN_LAYER_DEBT` did not change and the "
                                    "map did not move") is None
          and L._prose_number_claim("`KNOWN_LAYER_DEBT` is unchanged") is None
          and L._prose_number_claim("Every one of them has moved") is None)
    check("pn4 HISTORY stays writable - the past tense is how a decision record "
          "explains itself, and a lint that forbade it would push the rot into "
          "vaguer wording instead of removing it. `was still` and `stood at` "
          "are anchored to a past moment; `stayed at` with no anchor is not, "
          "which is why one is a finding and the other is not",
          L._prose_number_claim("ONE entry, down from the seventeen") is None
          and L._prose_number_claim("it stood at 70 cases that day, and was wrong")
              is None
          and L._prose_number_claim("`KNOWN_LAYER_DEBT` was still 17 that day")
              is None
          and L._prose_number_claim("all 48 files carried their own copy") is None)
    check("pn5 a number that carries its own re-derivation is NOT a finding - "
          "the house rule is that a claim carries the basis that makes it true",
          L._prose_number_claim("its 82 cases live in x - re-derive with "
                                "`python3 tests/test_x.py --selftest`") is None)
    check("pn6 ...and the basis counts when it lands on the FOLLOWING line, "
          "because every document here is hard-wrapped. Judging the claim by "
          "its own line alone would report a line that has already satisfied "
          "the house rule, and the repair for THAT would be to delete the basis",
          L._prose_number_claim("into `tests/`, all 83 of them (`73042a1` - "
                                "print it with", "`python3 -c \"...\"`); a "
                                "migrated file still exits 0") is None
          and L._prose_number_claim("into `tests/`, all 83 of them (`73042a1` - "
                                    "print it with", "and then read it off.")
              == "all 83 of them")
    check("pn7 the word 'cases' without a count is untouched, so ordinary prose "
          "about edge cases does not become a violation",
          L._prose_number_claim("the edge cases this guard cannot see") is None
          and L._prose_number_claim("in most cases the answer is no") is None)
    check("pn8 PERSISTENCE is caught - the same defect recurring in this shape "
          "more than once. A claim that a number has not changed is the purest "
          "form of the rot, because the sentence's whole job is to be checked "
          "against the present",
          L._prose_number_claim("`KNOWN_LAYER_DEBT` stayed at 17 and the map "
                                "did not move") == "stayed at 17"
          and L._prose_number_claim("`KNOWN_LAYER_DEBT` is still 17 and "
                                    "`--render` is byte-identical")
              == "is still 17"
          and L._prose_number_claim("`LAYERS` remains at 8") == "remains at 8"
          and L._prose_number_claim("`KNOWN_LAYER_DEBT` remains 17")
              == "remains 17")
    check("pn9 ...and it fires ONLY where the line names code in backticks. The "
          "measured line this protects is `hooks/_config.py`'s counterfactual "
          "about a format string's width: it is correct, removing its number "
          "would destroy the sentence, and it names no code. The two fixtures "
          "differ in exactly that, so a gate that stopped working turns this red",
          L._prose_number_claim("the `Z` is a literal so it is still 17 wide")
              == "is still 17"
          and L._prose_number_claim("the result is still 20 characters, and "
                                    "strptime parses it") is None)
    check("pn10 COMPLETENESS is caught when it carries a present-tense "
          "auxiliary within three tokens, and the window is what separates a "
          "claim about now from a count followed by an unrelated relative "
          "clause seven tokens later",
          L._prose_number_claim("All 48 files have moved, so the OR is empty")
              == "all 48 ... have"
          and L._prose_number_claim("**All 48 have moved**, `sc10` asserts it")
              == "all 48 ... have"
          and L._prose_number_claim("pins all 17 alias lines this module's "
                                    "names are re-exported through") is None
          and L._prose_number_claim("against all 8 viz slots on this surface")
              is None)


    check("pn10b the BARE count is caught however it is introduced - the three "
          "narrow shapes above all needed an introducer ('its', 'live in', "
          "'--selftest'), and eight sites said it plainly instead: 'the N cases "
          "in tests/', 'across N cases', 'the ~N cases below'. SEVEN of the "
          "eight were already wrong, and the eighth was one added case from "
          "joining them",
          L._prose_number_claim("and the 285 cases in `tests/` that read the page")
              == "285 cases"
          and L._prose_number_claim("asks for them by hand across 112 cases")
              == "112 cases"
          and L._prose_number_claim("It also keeps the ~230 cases, and that is")
              == "230 cases"
          and L._prose_number_claim("holds the ~283 selftest cases that assert")
              == "283 cases")
    check("pn11 ...and this is the family wide enough to swallow RECOLLECTION, "
          "so it is the one that has to ask whether the line means THEN - "
          "without that, a decision record cannot say what a number used to be",
          L._prose_number_claim("it stood at 70 cases that day, and was wrong")
              is None
          and L._prose_number_claim("the suite was 285 cases before the split")
              is None
          and L._prose_number_claim("down from 48 cases once the migration ran")
              is None)
    check("pn12 the REPAIR of the bare shape reads clean, or the lint forbids "
          "its own remedy and everyone deletes the pointer too",
          L._prose_number_claim("and the cases in `tests/` that read the page")
              is None
          and L._prose_number_claim("asks for them by hand, case by case")
              is None
          and L._prose_number_claim("holds the selftest cases that assert")
              is None)
    check("pn13 a count spelled as a WORD is the same claim in a different "
          "spelling - one that sat in a comment block every gate reads because "
          "no lint was looking at that spelling. One numeral reader serves every "
          "shape, so the word form cannot reach one family and miss another",
          L._prose_number_claim("its thirteen cases live in `tests/test_x.py`")
              == "its thirteen cases"
          and L._prose_number_claim("eleven cases live in the suite")
              == "eleven cases live in"
          and L._prose_number_claim("Config `x`. `--selftest` (nineteen cases).")
              == "--selftest (nineteen cases)"
          and L._prose_number_claim("the migration finished, all fifteen of them")
              == "all fifteen of them"
          and L._prose_number_claim("All fifteen files have moved, so the OR is "
                                    "empty") == "all fifteen ... have"
          and L._prose_number_claim("`KNOWN_LAYER_DEBT` stayed at seventeen and "
                                    "the map did not move")
              == "stayed at seventeen"
          and L._prose_number_claim("and the ten cases in `tests/` that read it")
              == "ten cases")
    # SECOND DIRECTION, and the only case in this family that fails if the numeral
    # table GROWS. It looks vacuous - none of these lines is a finding before the
    # word spelling was read either - and it is the whole reason the table stops
    # where it does. Every line is real prose from this tree, and not one of them
    # is a count: a rate, a uniqueness claim whose sentence dies if the word goes,
    # an anaphor pointing at an enumeration the reader can see in the same breath,
    # and an auxiliary that belongs to the NEXT sentence. Admitting the small words
    # - the obvious "make it see more" mutation - turns every one of them into a
    # finding, and the repair reached for next would be loosening a shape, which is
    # how a pattern stops catching the thing it exists for.
    check("pn14 ...and a number-word in ordinary prose is NOT a claim, which is "
          "what the table's omissions buy. These are measured lines from this "
          "tree, not invented ones, and admitting the words below `ten` makes "
          "every one of them a violation",
          L._prose_number_claim("a caller can still report one case per asset")
              is None
          and L._prose_number_claim("It is the ONE case that brings the section")
              is None
          and L._prose_number_claim("and all three are honest about what a "
                                    "violation does") is None
          and L._prose_number_claim("belongs below all four of them, not beside "
                                    "one") is None
          and L._prose_number_claim("read 'fixed'. Pinned below by two cases.")
              is None
          and L._prose_number_claim("because `diagnose()` calls all six. They "
                                    "are modules now, cut where the") is None)
    check("pn15 a tens word and its tail are ONE numeral, because the hyphen is "
          "punctuation the tokenizer has already dropped - without that a "
          "written-out compound reads as a number followed by an unrelated word "
          "and slips every shape. The tail words are not numerals on their own, "
          "which is what keeps pn14 true, and a tens word with no tail keeps its "
          "own shape, which is what fails if the span over-consumes",
          L._prose_number_claim("forty-four cases assert the join") == "forty-four cases"
          and L._prose_number_claim("its twenty-one cases live in `tests/x.py`")
              == "its twenty-one cases"
          and L._prose_number_claim("twenty cases live in the suite")
              == "twenty cases live in"
          and L._prose_number_claim("four cases assert the join") is None
          and L._prose_number_claim("carrying twenty-one upward runtime edges")
              is None)
    check("pn16 the word spelling inherits BOTH escape hatches, or the extension "
          "would make the decision record unwritable and forbid its own remedy - "
          "the two things every family here is pinned against",
          L._prose_number_claim("the suite was eleven cases before the split")
              is None
          and L._prose_number_claim("it stood at seventy cases that day") is None
          and L._prose_number_claim("its thirteen cases live in x - re-derive "
                                    "with `python3 tests/test_x.py --selftest`")
              is None
          and L._prose_number_claim("its cases live in `tests/test_x.py`") is None)
    _pn_isdigit = [ln for ln in open(L.__file__, encoding="utf-8").read().split("\n")
                   if "isdigit" in ln]
    check("pn17 every shape reads its number through the ONE span reader - a "
          "family added later that asked a token whether it is a digit itself "
          "would see digits and miss words, which is the same word-spelling gap "
          "wearing a new shape. COUNTED over the source rather than asserted "
          "present, because the defect is a second reader existing at all. TWO "
          "occurrences, not one, "
          "and the pair is spelled out rather than tallied: one asks whether a "
          "TOKEN is a numeral, the other whether a CHARACTER is a digit, which "
          "is the tokenizer's separator rule and runs before any shape sees "
          "anything. A third would be the defect this counts: %r" % (_pn_isdigit,),
          sorted(ln.strip() for ln in _pn_isdigit)
              == ["if tok.isdigit():", "return ch.isdigit()"]
          and L._numeral_span(["ten"], 0) == ("ten", 1)
          and L._numeral_span(["17"], 0) == ("17", 1)
          and L._numeral_span(["four"], 0) is None)

    # --- pn18-pn23: WHERE the scan looks, which is C4's location axis ---------
    # The set used to be a hand-written pair and the claims had moved to what it
    # left out. Each directory below held a real one: a suite size in a `tests/`
    # docstring, a file count in the prover, a part count per assembled surface.
    _pn_reach = dict(
        (_d, len([r for r in _pn_scan["paths"] if r.startswith(_d)]))
        for _d in ("tools/", "tests/", "plugins/audit/hooks/",
                   "plugins/audit/scripts/"))
    check("pn18 the scanned set is DERIVED from the tree, so it reaches the "
          "directories no hand-written list held - `tools/`, which holds the "
          "sweep runner and the mutation table, and `tests/`, which is where the "
          "suite sizes are written down: %r" % (_pn_reach,),
          _pn_scan["problem"] is None and all(_pn_reach.values()))
    # THE PREMISE OF EACH ROW, CHECKED, not just its presence. A row for a path
    # nothing holds any more is a sentence about a state that has passed, and it
    # stays green forever under a presence check alone - gate-parity's
    # stale-exemption half is the same reading. The generated report is the one
    # row whose file is legitimately absent from a fresh checkout, and it is
    # absent for a reason this can verify: `.gitignore` names it.
    _pn_ign = [_l.strip() for _l in
               io.open(os.path.join(M.REPO_ROOT, ".gitignore"),
                       encoding="utf-8").read().splitlines()]
    _pn_rows = L.PROSE_SCAN_EXEMPT
    _pn_bad = [_p for _p, _w in _pn_rows if not _w.strip()]
    _pn_dead = [_p for _p, _w in _pn_rows
                if not os.path.exists(
                    os.path.join(M.REPO_ROOT, _p.replace("/", os.sep)))
                and _p not in _pn_ign]
    check("pn19 every exemption carries a reason and describes a file that is "
          "really there - or one `.gitignore` names, which is how a generated "
          "document earns a row. The matcher is asked about that row's path "
          "directly, because it is the one row whose effect this tree never "
          "shows: the file is absent until somebody renders a report, and a row "
          "that matched nothing would look identical from here: %r"
          % (_pn_bad + _pn_dead,),
          not _pn_bad and not _pn_dead
          and len(_pn_rows) == len(set(_p for _p, _w in _pn_rows))
          and L.prose_scan_exemption("docs/audit/audit-report.md") is not None
          and L.prose_scan_exemption("docs/design/anything.md") is not None
          and L.prose_scan_exemption("plugins/audit/README.md") is None)
    _pn_tmp = tempfile.mkdtemp(prefix="pn-scan-")
    try:
        def _pn_write(rel, text):
            _full = os.path.join(_pn_tmp, rel.replace("/", os.sep))
            _dir = os.path.dirname(_full)
            if _dir and not os.path.isdir(_dir):
                os.makedirs(_dir)
            with io.open(_full, "w", encoding="utf-8") as _fh:
                _fh.write(text)
        _pn_write(".gitignore", "# fixture\nnotkept/\n")
        # Every line here is honest prose of a kind this tree really writes: a
        # recollection, a claim carrying its own basis, a noun with no count, and
        # a tally. None of them is a finding.
        _pn_write("clean.py",
                  '"""It stood at 70 cases that day, and the cases live in\n'
                  "`tests/`. Re-derive with `python3 x.py --selftest`.\n"
                  'ALL PASS: 7/7 cases passed."""\n')
        _pn_write("notes.md", "# Notes\n\nThe parts are joined in the order the\n"
                              "module lists them.\n")
        # The pruned half: a REAL claim, in a directory `.gitignore` names. If it
        # were reported, the finding count would depend on which agent worktrees
        # happened to be lying around rather than on anything in the commit.
        _pn_write("notkept/rot.py", '"""its 12 cases live in `tests/x.py`."""\n')
        _pn_honest = L.prose_number_claims(_pn_tmp)
        _pn_honest_set = L.prose_scan_set((".py",), _pn_tmp)
        # SECOND DIRECTION, and the only case here that fails if the widened scan
        # fires unconditionally: a tree whose prose is all correct reports
        # nothing WHILE HAVING READ IT. It looks vacuous, which is why the count
        # is in the message - "clean" and "read nothing" print the same otherwise.
        check("pn20 a tree whose claims are all honest reports nothing, over %d "
              "file(s) really read - this is the case that goes red if the scan "
              "ever fires unconditionally, and the one that goes red if the "
              "`.gitignore` pruning stops working: %r"
              % (len(_pn_honest_set["paths"]), _pn_honest),
              _pn_honest == [] and _pn_honest_set["paths"] == ["clean.py"])
        # ...and the same fixture WITH a claim, so pn20 is not a scan that cannot
        # fire. One line changed, one finding, naming the file and the line.
        _pn_write("clean.py", '"""its 12 cases live in `tests/x.py`."""\n')
        _pn_dirty = L.prose_number_claims(_pn_tmp)
        check("pn21 ...and the same tree with ONE claim added reports exactly it, "
              "by path and line - which is what tells pn20 apart from a walk "
              "that reads nothing: %r" % (_pn_dirty,),
              _pn_dirty == [("clean.py", 1, "its 12 cases")])
        os.remove(os.path.join(_pn_tmp, ".gitignore"))
        _pn_blind = L.prose_number_claims(_pn_tmp)
        check("pn22 a tree whose `.gitignore` cannot be read reports THAT and "
              "stops - the derivation is what prunes the agent worktrees, so "
              "falling back to 'nothing is ignored' would be a wrong answer "
              "wearing the shape of a right one, and returning [] would be "
              "'could not look' printed as 'clean': %r" % (_pn_blind,),
              len(_pn_blind) == 1 and _pn_blind[0][0] == ".gitignore"
              and "unreadable" in _pn_blind[0][2])
    finally:
        shutil.rmtree(_pn_tmp, ignore_errors=True)
    check("pn23 a numeral with an interior separator is a TALLY or a "
          "MEASUREMENT, not a count of things - the narrowing the widened scan "
          "needed, because the contract every suite prints appears outside "
          "`scripts/` as a fixture, a regex and an asserted literal. The bare "
          "count on the same noun still fires, which is what fails if the rule "
          "is ever widened from 'inside a number' to 'anywhere on the line'",
          L._prose_number_claim("ALL PASS: 7/7 cases passed") is None
          and L._prose_number_claim("suppresses even the <$0.01 case") is None
          and L._prose_number_claim("so the 4/1000 case goes red") is None
          and L._prose_number_claim("7 cases live in the suite")
              == "7 cases live in"
          and L._prose_number_claim("its 124 cases live in `tests/x.py`")
              == "its 124 cases"
          # THE TWO DIRECTIONS A NARROWING CAN BE WRONG IN, and neither is the
          # one above. Widened to the LINE, a real claim on a line that also
          # carries a tally would stop being read - and lines like that are
          # ordinary here. Widened to the TOKEN, a separator next to a letter
          # would be kept and every path in the tree would become one word.
          and L._prose_number_claim("7 cases live in it, in 1/2 the time")
              == "7 cases live in"
          and L._words("tests/x.py has 7 cases") == ["tests", "x", "py",
                                                     "has", "7", "cases"]
          # A thousands comma is NOT one of the separators: a grouped number is
          # still a count, so it stays dropped and the second numeral keeps its
          # noun. Asserted on the tokens, because the claim above it is reported
          # either way and so cannot tell the two versions apart.
          and L._prose_number_claim("1,254 lines, 148 cases, and 53 of them")
              == "148 cases"
          and L._words("1,254 lines") == ["1", "254", "lines"]
          and L._words("7/7 and 0.01") == ["7/7", "and", "0.01"])

    # --- pn24-pn28: the SENTENCE a number sits in, and two families refused ---
    # THE MOTIVATING CASE: the tense escape read the physical line, and a line is
    # neither the unit a tense belongs to nor the unit prose arrives in. The
    # first line below is the real one it was found on: a stale count sat unread
    # behind a past marker two clauses earlier, about something else entirely.
    check("pn24 the tense escape reads the SENTENCE the numeral sits in, not the "
          "physical line - a marker in an earlier sentence on the same line used "
          "to excuse a live count (a false negative, on the line it was found "
          "on). The second half is what fails if the scope narrows past a "
          "sentence to a clause: a marker inside the number's OWN sentence still "
          "excuses it, which is what keeps the decision record writable",
          L._prose_number_claim("THIS SUITE ALREADY HAD ITS OWN `check`. 102 of "
                                "the 131 cases go") == "131 cases"
          and L._prose_number_claim("the split was measured. 131 cases go "
                                    "through the wrapper") == "131 cases"
          and L._prose_number_claim("it had 131 cases then") is None)
    check("pn25 ...and the sentence is JOINED across the wrap, one line each way "
          "- the window `_carries_basis()` already reads, for the same reason: "
          "prose wraps, so a marker and its number land on different lines. Both "
          "directions of the join are here, and so is the half that fails if the "
          "join stops asking where a sentence ENDS - a marker in a sentence that "
          "finished before the wrap must not reach across it",
          L._prose_number_claim("146 cases stayed green afterwards", "",
                                "nothing pinned it, so the count was replaced by "
                                "a constant and all") is None
          and L._prose_number_claim("146 cases stayed green afterwards", "",
                                    "nothing pinned it, so the count was "
                                    "replaced by a constant.") == "146 cases"
          and L._prose_number_claim("the suite keeps all 146 cases",
                                    "before the split") is None
          and L._prose_number_claim("the suite keeps all 146 cases.",
                                    "It was different before.") == "146 cases"
          # A markdown sentence ends after its emphasis, not before it. Without
          # that the bolded line below would read as unfinished and hand its past
          # tense down to the next line, which is a document-shaped hole: `.md` is
          # half of what these shapes now read.
          and L._prose_number_claim("146 cases go through the wrapper", "",
                                    "**it was measured then.**") == "146 cases"
          # Called with no neighbours at all - one string, read as one whole
          # sentence. Every case above this section hands over exactly that.
          and L._prose_number_claim("the suite keeps all 146 cases") == "146 cases")
    # SECOND DIRECTION, and it is the only case here that fails when the boundary
    # rule gets GREEDY. It looks vacuous - both lines are ordinary recollection
    # and neither was a finding before this rule closed the sentence-boundary gap
    # either - and it is the whole reason the rule asks what follows a stop.
    # Each half names its own mutation: read every
    # stop as a boundary and a dotted filename cuts the sentence in two, leaving
    # the tense behind in the first half; read a run of stops as boundaries and an
    # elided tag pair cuts one sentence into four, which is how a docstring's own
    # history was reported as a claim while this was being written.
    check("pn26 a stop INSIDE a name, and a run of stops standing for elided "
          "markup, are not sentence ends - a fragmenting boundary rule throws "
          "away the tense the sentence opened with and reports recollection as a "
          "claim. The third line is the same shape with the marker removed, so "
          "this fails if the joining stops firing at all rather than reading as "
          "two silent lines",
          L._prose_number_claim("it was rewritten in `x.py` and has 7 cases")
              is None
          and L._prose_number_claim("used to hold `<style>...</style>` and 7 "
                                    "cases") is None
          and L._prose_number_claim("it holds `x.py` and 7 cases") == "7 cases")
    # TWO FAMILIES MEASURED AND REFUSED, recorded as cases because a docstring
    # saying "cannot see" is not checkable and the next author will reach for
    # exactly these shapes.
    #
    # A MEASUREMENT - a duration, a byte count, a line count - is invisible here,
    # and the units family that would read it was surveyed over this whole tree
    # before being declined. Every hit was read: on the widest unit vocabulary
    # honest prose outran real claims by better than two to one, and on the
    # narrowest defensible cut (size units, on a line naming code, the gate the
    # persistence family uses) it still outran them. The lines below are the
    # reason and they are real ones from this tree: a THRESHOLD, a configured
    # constant and a hypothetical are numbers that must stay, and they are the
    # shape a units family cannot tell from a claim.
    # THE BOUND matters as much as the rule: an underscore glues a token only
    # where WORD CHARACTERS flank it, so a trailing one still ends the token and
    # the numeral after it keeps whatever noun follows. The second half is the
    # direction that fails if this is ever applied to any underscore at all.
    _f77_line = '    x = y[1] == case_id(z)'
    check("pn29 an identifier is ONE word, so a numeric index in front of a name "
          "whose first piece is a case noun is not a claim - and the rule stops "
          "at a word boundary, so a trailing separator still leaves the numeral "
          "its noun: %r / %r"
          % (L._words(_f77_line), L._words("count_ 5 cases")),
          L._prose_number_claim(_f77_line) is None
          and "case_id" in L._words(_f77_line)
          and L._words("count_ 5 cases") == ["count", "5", "cases"]
          and L._prose_number_claim("count_ 5 cases") is not None
          # ...and a LEADING separator is dropped too, so an underscore-prefixed
          # noun still keeps the numeral in front of it. This is the direction
          # that fails if the rule stops asking for left context.
          and L._words("its 1 _cases") == ["its", "1", "cases"]
          and L._prose_number_claim("its 1 _cases") is not None)
    check("pn27 a MEASUREMENT is not read - the units family was surveyed over "
          "this tree and refused, because a size or a duration here is usually a "
          "threshold, a budget or a hypothetical, and those numbers are the point "
          "of their sentences. This is the case that goes red if one is adopted "
          "without measuring again",
          L._prose_number_claim("Files of 400+ lines need at least two markers")
              is None
          and L._prose_number_claim("Events are the newest ~20 lines of")
              is None
          and L._prose_number_claim("a banner would let a 2,000-line module pass")
              is None
          # WHAT THE REFUSAL GIVES UP, in the same case so it cannot be read as
          # an accident: a real measurement of this tree is not read either.
          and L._prose_number_claim("front-matter reads, 159 ms cold and 31 ms "
                                    "warm - and it runs on a POLL") is None
          and L._prose_number_claim("the 46,220-byte `audit-plan.schema.json`")
              is None)
    check("pn28 ...and a BEFORE/AFTER sentence is not read either, for a "
          "different reason: its first number is history and legal for ever, its "
          "second is a live claim, and the tense that makes the first one legal "
          "sits in the same sentence as the second. The `is N` shape that would "
          "reach it was surveyed too and refused - real claims were a quarter of "
          "its hits, the rest arithmetic, format shapes and external facts. The "
          "repair is the prose, and the repaired form reads clean",
          L._prose_number_claim("It was 1,456 lines and is 242, because the "
                                "checks shared one file") is None
          and L._prose_number_claim("`E_USAGE` is 2 and the reason is arithmetic")
              is None
          and L._prose_number_claim("It was one file and is six, because the "
                                    "checks shared it for one reason") is None)

    # THE RATIO FAMILY, and every case below is about ONE distinction: a
    # count quoted from what a command prints is legal when the command is named
    # and is a copy with no basis when it is not. That is the question
    # `_carries_basis()` already decides for a bare cardinality, which is why
    # this is a third answer to it rather than a fourth shape.
    #
    # The reported spelling is `13 of 14 sections`, quoting `_areas.py
    # --coverage`. Both numbers rot, and the `of M` is what made it read as a
    # quotation: a ratio shows its own whole, so it looks self-verifying, and a
    # denominator is not a basis because nothing re-derives it either.
    check("pn30 a RATIO with no command beside it is a finding, in BOTH "
          "spellings and mixed - no shape may read a digit and a word by "
          "different rules, and a family added after this one must read them "
          "through `_numeral_span()` rather than growing its own reader",
          L._prose_number_claim("anchored 13 of 14 sections")
              == "13 of 14 sections"
          and L._prose_number_claim("anchored thirteen of fourteen sections")
              == "thirteen of fourteen sections"
          and L._prose_number_claim("anchored 13 of fourteen sections")
              == "13 of fourteen sections"
          and L._prose_number_claim("anchored five of nine sections")
              == "five of nine sections")
    # THE THREE LEGAL SPELLINGS, QUOTED FROM `CONTRIBUTING.md`'s "Writing a
    # count that is allowed" RATHER THAN INVENTED. They are the three shapes a
    # ratio is most easily confused with, because all three read as quotation -
    # and a lint that convicted the number carrying its own command would be
    # routed around inside a day, with the repair being to delete the basis.
    _pn_wrapped = ("it anchored 13 of 14 sections - print it with",
                   "`python3 plugins/audit/scripts/manifest/_areas.py "
                   "--coverage`")
    check("pn30b ...and the three spellings this repo keeps LEGAL stay silent, "
          "including the one whose basis lands on the NEXT line because prose "
          "wraps. The last pair is the second direction: the same claim with "
          "the command taken away, so this case fails if the basis gate stops "
          "being consulted at all rather than passing two silent lines",
          L._prose_number_claim("The largest file is `_deps.py`; `python3 "
                                "tools/count-ui-pins.py` reports the split by "
                                "directory.") is None
          and L._prose_number_claim("Roughly a third of the suites reach the "
                                    "browser gates:",
                                    "`grep -rln capture-screenshots "
                                    "tests | wc -l`") is None
          and L._prose_number_claim("Two consecutive captures agreed on every "
                                    "image the day this shipped.") is None
          and L._prose_number_claim("it anchored the sections `_areas.py "
                                    "--coverage` names") is None
          and L._prose_number_claim(_pn_wrapped[0], _pn_wrapped[1]) is None
          and L._prose_number_claim(_pn_wrapped[0], "and read the split off it.")
              == "13 of 14 sections")
    # ...and the REFUSAL, which is the other half of the ratio family and is
    # refused rather than missing. `five claims deep` is `the N <noun>` with an
    # ordinary noun - the same shape a word-spelled numeral wears when nothing
    # bounds its noun; the noun is unbounded, so reading it means reading every
    # count in every sentence. The small-word reading exists
    # for a shape that supplies its own bound and is OFF everywhere else - both
    # halves are pinned here, because a widening in either would turn this tree
    # red on prose that is doing its job.
    check("pn31 an ordinary `the N <noun>` is NOT read, in either spelling, and "
          "a small number-word is not a numeral to the families that read a "
          "bare noun - the second direction of `_numeral_span`'s `small` flag, "
          "which the ratio case above is the first direction of",
          L._prose_number_claim("the argument runs five claims deep") is None
          and L._prose_number_claim("the argument runs 5 claims deep") is None
          and L._prose_number_claim("the argument runs fourteen claims deep")
              is None
          and L._prose_number_claim("all three are honest about what they are:")
              is None
          and L._prose_number_claim("an id naming two cases defeats that") is None
          and L._numeral_span(["five", "cases"], 0) is None
          and L._numeral_span(["five", "cases"], 0, True) == ("five", 1)
          and L._numeral_span(["twenty", "five"], 0) == ("twenty-five", 2)
          and L._numeral_span(["twenty", "five"], 0, True) == ("twenty-five", 2))
    # EACH NARROWING WITH THE CLASS OF LINE THAT BOUGHT IT, all four measured
    # over this tree rather than guessed. The fixtures are real lines from it,
    # shortened only where the whole line would not fit.
    #
    # THE ARTICLE LINE IS REFUSED TWICE, so it is the one fixture here that no
    # single mutation turns red: the loop wants the whole to follow `of`
    # directly, and the verbatim rule refuses the spelling again because the run
    # built from the tokens has no article in it. Both were removed separately
    # and together to establish that, and the pair is the reason this comment
    # exists - green after one mutation is not evidence of a dead rule.
    check("pn32 the four narrowings, each on the class of line it was bought "
          "by: an ARTICLE no formatter emits, a QUOTED span where the tally is "
          "a byte, a token after the whole that cannot be a noun, and a run "
          "the text never actually spelled that way",
          L._prose_number_claim("17 of the 18 detail-carrying files print it")
              is None
          and L._prose_number_claim('and "5 of 6 manifest item(s) carry an ado '
                                    'link" in out') is None
          and L._prose_number_claim("for example *\"Audit of acme-store: 3 of "
                                    "5 phases signed off, 2") is None
          and L._prose_number_claim("`wave 2 of 8 - 16 of 20 tasks still "
                                    "ready` reads as progress") is None
          and L._prose_number_claim("only 8 of 40 can be coloured") is None
          and L._prose_number_claim("it fails at 17 of 353 with the feature off")
              is None
          and L._prose_number_claim('index["phases"][1]["claim"] = {}') is None
          and L._prose_number_claim("a phase that was 1-of-1 done reading 2/2")
              is None
          and L._prose_number_claim("45% of this tree (22,363 of 49,393 lines) "
                                    "moved") is None
          and L._prose_number_claim("this is one of four classes, and the "
                                    "sentence dies if the word goes") is None)
    # An UNPARTNERED delimiter opens a span to the end of the line, because both
    # prose and source wrap here and the closing one is on neither line. Counted
    # rather than asserted present: the first fixture has one span and the second
    # two, so a rule that stopped pairing at all still separates them.
    _pn_odd = L._quoted_spans('    "0 of 5` is the honest line, and printed')
    _pn_even = L._quoted_spans('reading `x` is worse than `y` here')
    check("pn33 a quoted span is read by COLUMNS, an unpartnered delimiter runs "
          "to the end of the line, and overlap is enough - a run leaning out "
          "past a closing delimiter is still that tally: %r / %r"
          % (_pn_odd, _pn_even),
          len(_pn_even) == 2
          and len(_pn_odd) == 2
          and L._in_quoted_span("a `b 3 of 4 x` c", 3, 13)
          and L._in_quoted_span("a `b 3 of 4 x` c", 3, 16)
          and not L._in_quoted_span("a `b` 3 of 4 x", 6, 14))
    # The REPAIR reads clean, or the lint forbids its own remedy and the next
    # author deletes the pointer with the number. And the history escape's new
    # markers must not excuse a sentence that does not carry one - without the
    # second half this passes on a `_looks_historical` that returns True always.
    check("pn34 the repair of a ratio reads clean, and the past-tense markers "
          "the ratio family added to `_PAST` excuse only the sentences that "
          "carry them",
          L._prose_number_claim("anchored every section but one - print the "
                                "split with `python3 x.py --coverage`") is None
          and L._prose_number_claim("measured that day: 13 of 14 sections were "
                                    "anchored") is None
          and L._prose_number_claim("one saw 9 of 12 tasks reported that way")
              is None
          and L._prose_number_claim("today it anchors 13 of 14 sections")
              == "13 of 14 sections"
          and "measured" in L._PAST and "saw" in L._PAST)
    # THE EXTENT OF THE UNPARTNERED-DELIMITER SPAN, both ends of it. pn33 pins
    # that the span exists and is read by columns; this pins how far it reaches,
    # because a blind spot whose size nothing holds is free to grow into the
    # families it was never adopted for. The claim is the same claim in every
    # fixture, so what separates them is only where the delimiter sits.
    _pn_before = "today it anchors 13 of 14 sections and `x"
    _pn_afterTick = "and `x is open while today it anchors 13 of 14 sections"
    _pn_afterQuote = 'a "quotation opens while today it anchors 13 of 14 sections'
    _pn_evenTick = 'a `b` and "c today it anchors 13 of 14 sections'
    _pn_closed = "a `3 of 4 x` and today it anchors 13 of 14 sections"
    check("pn35 the blind span OPENS at the unpartnered delimiter and CLOSES at "
          "the end of its line: a claim in front of one is still read, a claim "
          "after a partnered pair is still read, the next line is read normally, "
          "and the two delimiters are counted apart - so balanced backticks do "
          "not rescue a line whose double quotes are odd: %r"
          % ((L._prose_number_claim(_pn_before),
              L._prose_number_claim(_pn_afterTick)),),
          L._prose_number_claim(_pn_before) == "13 of 14 sections"
          and L._prose_number_claim(_pn_closed) == "13 of 14 sections"
          and L._prose_number_claim("today it anchors 13 of 14 sections",
                                    None, _pn_afterTick) == "13 of 14 sections"
          and L._prose_number_claim(_pn_afterTick) is None
          and L._prose_number_claim(_pn_afterQuote) is None
          and L._prose_number_claim(_pn_evenTick) is None)
    # THE FOURTH NARROWING, ISOLATED. Every other fixture for it is refused twice
    # over - a grouped `22,363 of 49,393` fails the verbatim rule as well, so
    # removing this one leaves the line quiet and proves nothing about it. A
    # numeral standing in the NOUN slot is the shape only this narrowing sees,
    # and the pair below is the specification: the same sentence with a word
    # there is a finding, and with a numeral there it is not.
    check("pn36 a ratio whose noun position holds another NUMERAL is not read - "
          "the narrowing that stops a thousands-grouped tally, which tokenizes "
          "into two numbers with the second one standing where the noun would. "
          "What it gives up is a tally whose noun really is a numeral, which is "
          "an under-count and is the direction these shapes are documented as "
          "being wrong in",
          L._prose_number_claim("today it anchors 13 of 14 2026") is None
          and L._prose_number_claim("today it anchors 13 of 14 sections")
              == "13 of 14 sections"
          and L._prose_number_claim("45% of this tree (22,363 of 49,393 lines) "
                                    "moved") is None)

    # --- how an acquire result may be read ---------------------------------------
    # `_locks.acquire` returns an INT on every path. Two callers once named it
    # `handle` and tested `isinstance(handle, dict)` - never true of an int - so
    # their release never ran and their status was never read: every write leaked
    # the index lock, and a REFUSED acquire fell straight into the write and
    # changed the manifest with no lock held. One misreading, two defects, and a
    # `try/finally` that made the first look handled.
    #
    # Read as SOURCE because the shape is the fault. A behavioural case per caller
    # is worth having and some exist, but they cannot stop the NEXT caller
    # inventing the same reading; `isinstance(x, dict)` on an int raises nothing
    # and returns a value, so nothing fails until a lock is contended.
    #
    # THE MEMBERSHIP IS A WALK, NOT A TABLE. A hand-kept list of callers is
    # exactly how a new one goes unwatched: nothing re-reads the tree to notice
    # one, so a caller added under a directory the list's author was not
    # thinking about opts itself out by being forgotten. `M.py_files` is the
    # same recursive walk every other source-reading case in this module already
    # shares (see `px2` above); finding "which file spells `_locks.acquire(`" out
    # of it costs nothing this suite does not already spend.
    _lk_callers = []
    _lk_src_of = {}
    _lk_bad = {}
    for _lk_rel, _lk_path in M.py_files(M.SCRIPTS_DIR):
        # A FILE THE WALK NAMES AND CANNOT READ IS A FINDING, not a traceback -
        # the same posture `px2` takes for the same reason: whether THIS file
        # calls `_locks.acquire(` could not be checked, and that has to show up
        # as a row rather than as an exception that takes every later case down
        # while naming none of them.
        try:
            _lk_src = io.open(_lk_path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            _lk_bad[_lk_rel] = ("cannot be read - whether it calls "
                                "_locks.acquire( could not be checked")
            continue
        _lk_calls_it = False
        for _lk_line in _lk_src.splitlines():
            _lk_st = _lk_line.strip()
            if _lk_st.startswith("#"):
                continue
            if "_locks.acquire(" in _lk_st:
                _lk_calls_it = True
                break
        if _lk_calls_it:
            _lk_callers.append(_lk_rel)
            _lk_src_of[_lk_rel] = _lk_src
    for _rel in _lk_callers:
        for _line in _lk_src_of[_rel].splitlines():
            _st = _line.strip()
            if _st.startswith("#"):
                continue
            if "isinstance(" in _st and ("handle" in _st or "code" in _st):
                _lk_bad[_rel] = _st[:70]
    # THE FLOOR, NOT A COUNT. What follows is not today's tally - run the walk
    # to see that - it is the least this case accepts before treating itself as
    # having stopped matching the source, rather than the tree having actually
    # shed that much at once. Both manifest repairs, the phase-proposal writer
    # and the panel's write path each take this lock by name below, and none of
    # them can disappear without a change large enough to carry its own review -
    # so a walk that lands under this floor is far more likely to have broken
    # than to be reporting a tree that has genuinely lost that much.
    _lk_floor = 4
    check("lk4 no caller reads an acquire result as anything but the integer it "
          "is - the release and the refusal both hang off that value, and a "
          "`dict` reading disables both while raising nothing: %r" % (_lk_bad,),
          not _lk_bad and len(_lk_callers) >= _lk_floor)



def _ts_order_cases(check):
    """`ts_order_violations`: an order or a comparison taken on a `ts` field's
    TEXT is reported, and one taken through a moment reader is not."""
    import shutil
    import tempfile
    to = tempfile.mkdtemp(prefix="audit-ts-order-")
    try:
        def _to(rel, text):
            full = os.path.join(to, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)

        _to("planted.py", "def newest(rows):\n"
                          "    return max(r['ts'] for r in rows)\n")
        _to("keyed.py", "def order(rows):\n"
                        "    rows.sort(key=lambda r: str(r.get('ts') or ''))\n"
                        "    return sorted(rows, key=lambda r: r['ts'])\n")
        _to("compared.py", "def later(a, b):\n"
                           "    return a.get('ts') >= b.get('ts')\n")
        # The helpers' own shapes: every `ts` read sits inside a moment reader.
        _to("governance/_evidence_io.py",
            "def _ts_moment(row):\n"
            "    return stamp_moment(row.get('ts'))\n"
            "def oldest_first(rows):\n"
            "    keyed = [(_ts_moment(r), r) for r in rows]\n"
            "    return sorted(keyed, key=lambda pair: pair[0])\n"
            "def newer(a, b):\n"
            "    return stamp_moment(a.get('ts')) > stamp_moment(b['ts'])\n"
            "def row_ts(row):\n"
            "    return min(_usage_core.parse_ts(r.get('ts')) for r in row)\n")
        # Equality and a ts read outside any ordering are not orders.
        _to("equal.py", "def same(a, b):\n"
                        "    return a.get('ts') == b.get('ts')\n"
                        "def label(r):\n"
                        "    return 'at %s' % (r.get('ts'),)\n")
        _to("listed.py", "def legacy(rows):\n"
                         "    return max(r['ts'] for r in rows)\n")
        table = (("scripts/listed.py", "legacy", "a planted exception"),
                 ("scripts/gone.py", "vanished", "a site deleted since"))
        hits = L.ts_order_violations(to, "", table=table)
        files = sorted(set(f for f, _w in hits))
        check("to1 a planted max(r['ts']) is reported, and so are a sort and a "
              "sorted keyed on a ts field's text and a >= between two ts "
              "values: %r" % (hits,),
              {"scripts/planted.py", "scripts/keyed.py",
               "scripts/compared.py"} <= set(files)
              and len([h for h in hits if h[0] == "scripts/keyed.py"]) == 2)
        check("to2 ALLOW: _evidence_io's helpers - every ts read inside a "
              "moment reader - are quiet, and so is an equality and a ts read "
              "that orders nothing; a lint that convicted any of these would be "
              "a lint that convicts the fix: %r" % (files,),
              "scripts/governance/_evidence_io.py" not in files
              and "scripts/equal.py" not in files)
        check("to3 a table row silences its site, and a row whose site no "
              "longer orders on ts text is itself reported: %r" % (hits,),
              "scripts/listed.py" not in files
              and any(f == "scripts/gone.py" and "vanished" in w
                      for f, w in hits))
    finally:
        shutil.rmtree(to, ignore_errors=True)
    real = L.ts_order_violations()
    check("to4 ...and the real tree orders no ts by its text outside the "
          "sites TS_ORDER_SITES names: %r" % (real,),
          real == [])
    check("to5 ...the real _evidence_io, whose helpers ARE the moment order, "
          "is quiet by construction and not by a table row: %r"
          % ([r for r in L.TS_ORDER_SITES if "_evidence_io" in r[0]],),
          not [r for r in L.TS_ORDER_SITES if "_evidence_io" in r[0]]
          and not [h for h in real if "_evidence_io" in h[0]])


_ENCODING_REPORTED = (
    "import io, os, subprocess\n"
    "a = open(p, 'w')\n"
    "b = open(p)\n"
    "c = io.open(p, mode='r')\n"
    "d = os.fdopen(fd, 'w')\n"
    "e = path.read_text()\n"
    "f = path.write_text(s)\n"
    "g = subprocess.run(cmd, capture_output=True, text=True)\n"
    "h = subprocess.Popen(cmd, stdout=PIPE, universal_newlines=True)\n"
    "i = subprocess.check_output(cmd, errors='replace')\n"
    "j = subprocess.run(cmd, capture_output=True).stdout.decode()\n"
    "k = open(p, m)\n"
    "q = subprocess.run(cmd, text=flag)\n")
# Every line here names its encoding: a lint reporting any of them convicts
# the fix itself.
_ENCODING_NAMED = (
    "import io, os, subprocess\n"
    "a = open(p, 'w', encoding='utf-8')\n"
    "b = open(p, 'r', -1, 'utf-8')\n"
    "c = io.open(p, mode='r', encoding='utf-8', errors='replace')\n"
    "d = os.fdopen(fd, 'w', encoding='utf-8')\n"
    "e = path.read_text('utf-8')\n"
    "f = path.write_text(s, encoding='utf-8')\n"
    "g = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',\n"
    "                   errors='replace')\n"
    "h = subprocess.Popen(cmd, stdout=PIPE, encoding='utf-8')\n"
    "i = subprocess.run(cmd, capture_output=True).stdout.decode('utf-8', 'replace')\n")
# ...and nothing here is text at all, or the lint cannot read what it forwards.
_ENCODING_BINARY = (
    "import os, subprocess\n"
    "a = open(p, 'rb')\n"
    "b = os.open(p, os.O_RDONLY)\n"
    "c = subprocess.run(cmd, capture_output=True)\n"
    "d = subprocess.run(cmd, text=False)\n"
    "e = open(p, **kw)\n"
    "f = subprocess.run(cmd, **kw)\n"
    "g = os.fdopen(fd, 'rb')\n")


def _encoding_cases(check):
    """`text_encoding_violations`: a text-mode open or subprocess call that
    names no encoding is reported by file and line, and one that names it, or
    is not text, is not."""
    import shutil
    import tempfile
    en = tempfile.mkdtemp(prefix="audit-encoding-")
    try:
        scripts = os.path.join(en, "scripts")
        hooks = os.path.join(en, "hooks")
        for d, name, text in ((scripts, "sub/report.py", _ENCODING_REPORTED),
                              (scripts, "named.py", _ENCODING_NAMED),
                              (scripts, "binary.py", _ENCODING_BINARY),
                              (hooks, "hook.py", "x = open(p, 'a')\n"
                                                 "y = open(p, 'a', encoding='utf-8')\n")):
            full = os.path.join(d, *name.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        found = L.text_encoding_violations((scripts, hooks), ())
        by_file = {}
        for name, line, _what in found:
            by_file.setdefault(name, []).append(line)
        check("tests/test__output.py: a text-mode open or a "
              "text-mode subprocess call with no encoding anywhere under "
              "scripts/ or hooks/ is reported by file and line, and one that "
              "names its encoding is not (open, io.open, os.fdopen, "
              "read_text, write_text, text=, universal_newlines=, errors= and "
              "a bare .decode() each reported once at its own line; every "
              "encoding-naming twin silent): %r" % (by_file,),
              by_file == {"scripts/sub/report.py": list(range(2, 14)),
                          "hooks/hook.py": [1]})
        check("en2 ALLOW: a handle or a capture that is not text - a binary "
              "mode, os.open, a bytes capture, text=False - and a **kwargs "
              "forward the lint cannot read are silent; a rule convicting any "
              "of them teaches an author to name an encoding on bytes: %r"
              % (sorted(by_file),),
              "scripts/binary.py" not in by_file
              and "scripts/named.py" not in by_file)
        held = L.text_encoding_violations((scripts,), ("scripts/sub/report.py",
                                                       "scripts/named.py"))
        check("en3 a pending row silences its file, and a row naming a file "
              "that holds no unencoded text I/O is itself reported, so the "
              "table can only shrink: %r" % (held,),
              [h[:2] for h in held] == [("scripts/named.py", 0)])
        per_source = L.unencoded_text_io(_ENCODING_REPORTED)
        check("en4 the per-source walker is the one the tree-wide lint uses: "
              "the same lines, each with what it is: %r" % (per_source,),
              [line for line, _what in per_source] == by_file.get(
                  "scripts/sub/report.py")
              and all(what for _line, what in per_source))
    finally:
        shutil.rmtree(en, ignore_errors=True)
    real = L.text_encoding_violations()
    project_hooks = os.path.join(M.REPO_ROOT, ".claude", "hooks")
    check("en5 ...and the pending table holds no row, the default walk is the "
          "plugin's scripts/ and hooks/ plus the project's .claude/hooks "
          "whenever that directory exists, and the real tree opens no text "
          "handle and decodes no subprocess output without naming its "
          "encoding: %r pending, %r found" % (L.ENCODING_PENDING, real),
          not L.ENCODING_PENDING and real == []
          and L.ENCODING_DIRS[:2] == (M.SCRIPTS_DIR, M.HOOKS_DIR)
          and (project_hooks in L.ENCODING_DIRS) == os.path.isdir(project_hooks))


def _selftest():
    def body(check):
        _cases(check)
        _ts_order_cases(check)
        _encoding_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__output_lints.py --selftest\n")
    raise SystemExit(2)
