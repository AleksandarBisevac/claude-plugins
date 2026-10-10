#!/usr/bin/env python3
"""
The cases for `_runner_collects.py` - does the test runner collect this path.

The danuvia shape is the reason the module exists: a `vitest.config.ts` whose
`test.include` names one directory, and a task whose `tests.add` names a file
outside it. The cases are grouped by the question each answers: the three-way
answer for that fixture, the refusals to guess (an unknown runner, an include
that is computed), the glob semantics (each pattern was also given to a real
`vitest list` when the cases were written), the list-mode-first order, and the
jest and pytest readings.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _runner_collects as M                       # noqa: E402

# Shaped like the real config: a comment and a nested `include` that are NOT the
# test's, so a reader that takes the first `include` in the text answers wrongly.
DANUVIA = """\
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// include: ["everything/**"]   <- a comment, not the config
export default defineConfig({
  plugins: [react()],
  test: {
    coverage: { include: ["lib/**"] },
    environment: "jsdom",
    include: ['tests/unit/**/*.test.ts'],
    globals: false,
  },
});
"""


def _write(root, rel, text=""):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


def _project(root, files):
    for rel, text in files.items():
        _write(root, rel, text)
    return root


def _answer(root, path, runner, lister=None):
    return M.collects(path, runner, root, lister=lister)["answer"]


def _never(runner, project):
    raise AssertionError("list mode was asked and should not have been")


def _lists(*paths):
    return lambda runner, project: list(paths)


def _vitest(check, tmp):
    root = _project(os.path.join(tmp, "dan"), {"vitest.config.ts": DANUVIA})
    for label, path, want in (
            ("rc1 the danuvia fixture: lib/store.test.ts is not collected",
             "lib/store.test.ts", M.NOT_COLLECTED),
            ("rc2 the danuvia fixture: components/x.test.tsx is not collected",
             "components/x.test.tsx", M.NOT_COLLECTED),
            ("rc3 tests/unit/a.test.ts is collected",
             "tests/unit/a.test.ts", M.COLLECTED),
            ("rc4 a deeper path under the include is collected",
             "tests/unit/deep/er/b.test.ts", M.COLLECTED),
            ("rc5 the suffix is part of the pattern: a .tsx under tests/unit is not",
             "tests/unit/c.test.tsx", M.NOT_COLLECTED)):
        got = M.collects(path, "vitest", root, lister=_lists())
        check(label + " (%s)" % got["answer"], got["answer"] == want)
    got = M.collects("lib/store.test.ts", "vitest", root, lister=_lists())
    check("rc6 a definite answer names the include it read: %r" % got["basis"],
          "tests/unit/**/*.test.ts" in got["basis"] and got["via"] == "config")

    # The second direction: an `exclude` the module does not read turns a
    # "collected" into "could not tell", while a mismatch stays definite.
    ex = _project(os.path.join(tmp, "ex"), {"vitest.config.ts":
        "export default { test: { include: ['a/**/*.test.ts'], exclude: ['a/x/**'] } }"})
    check("rc7 an exclude in the config: a match is only 'could not tell'",
          _answer(ex, "a/x/y.test.ts", "vitest", _lists()) == M.COULD_NOT_TELL)
    check("rc8 an exclude in the config: a mismatch is still definite",
          _answer(ex, "b/y.test.ts", "vitest", _lists()) == M.NOT_COLLECTED)

    none = _project(os.path.join(tmp, "none"), {"package.json": "{}"})
    check("rc9 vitest with no config reads the documented default include",
          _answer(none, "lib/store.test.ts", "vitest", _lists()) == M.COLLECTED
          and _answer(none, "lib/store.ts", "vitest", _lists()) == M.NOT_COLLECTED)
    vite = _project(os.path.join(tmp, "vite"), {"vite.config.ts":
        "export default { test: { include: ['t/**/*.spec.ts'] } }"})
    check("rc10 vite.config.ts is read when there is no vitest.config",
          _answer(vite, "t/a.spec.ts", "vitest", _lists()) == M.COLLECTED
          and _answer(vite, "lib/a.spec.ts", "vitest", _lists()) == M.NOT_COLLECTED)


def _refusals(check, tmp):
    root = _project(os.path.join(tmp, "unk"), {"vitest.config.ts": DANUVIA})
    for runner in ("mocha", "ava", "", None, "Vitest "):
        got = M.collects("tests/unit/a.test.ts", runner, root, lister=_never)
        check("rc11 runner %r is unknown: could not tell, not collected" % (runner,),
              got["answer"] == M.COULD_NOT_TELL and "basis" in got and got["basis"])
    cases = (
        ("rc12 a variable include", "const INC = ['x/**'];\n"
         "export default { test: { include: INC } }"),
        ("rc13 a spread inside the include array",
         "export default { test: { include: [...base, 'x/**/*.test.ts'] } }"),
        ("rc14 a spread inside the test object",
         "export default { test: { ...shared, include: ['x/**/*.test.ts'] } }"),
        ("rc15 a template with an expression",
         "export default { test: { include: [`${dir}/**/*.test.ts`] } }"),
        ("rc16 a call as the include",
         "export default { test: { include: glob('x') } }"),
        ("rc17 mergeConfig, whose base may carry the include",
         "export default mergeConfig(base, { test: { include: ['x/**/*.test.ts'] } })"),
        ("rc18 projects, each with an include of its own",
         "export default { test: { projects: ['a'], include: ['x/**/*.test.ts'] } }"),
        ("rc19 a root that moves what 'relative' means",
         "export default { test: { root: './src', include: ['x/**/*.test.ts'] } }"))
    for label, text in cases:
        proj = _project(os.path.join(tmp, label.split()[0]), {"vitest.config.ts": text})
        for path in ("x/a.test.ts", "lib/store.test.ts"):
            got = M.collects(path, "vitest", proj, lister=_lists())
            check("%s: %s is 'could not tell' (%s)" % (label, path, got["answer"]),
                  got["answer"] == M.COULD_NOT_TELL and got["basis"])


def _glob(check):
    # Every row with a boolean was put to a real `vitest list` as an include.
    rows = (
        ("g1", "tests/unit/**/*.test.ts", "tests/unit/a.test.ts", True),
        ("g2", "tests/unit/**/*.test.ts", "tests/unit/x/y/a.test.ts", True),
        ("g3", "tests/unit/**/*.test.ts", "tests/e2e/a.test.ts", False),
        ("g4", "tests/unit/**", "tests/unit/a.test.ts", True),
        ("g5", "**/*.test.ts", "a.test.ts", True),
        ("g6", "**/*.test.ts", "x/y/a.test.ts", True),
        ("g7", "*.test.ts", "x/a.test.ts", False),
        ("g8", "lib/*.test.ts", "lib/a/b.test.ts", False),
        ("g9", "tests/unit/**/*.test.{ts,tsx}", "tests/unit/a.test.tsx", True),
        ("g10", "tests/unit/**/*.test.{ts,tsx}", "tests/unit/a.test.js", False),
        ("g11", "**/*.?(c|m)[jt]s?(x)", "a/b.mts", True),
        ("g12", "**/*.?(c|m)[jt]s?(x)", "a/b.tsx", True),
        ("g13", "**/*.?(c|m)[jt]s?(x)", "a/b.py", False),
        ("g14", "src/a?.test.ts", "src/ab.test.ts", True),
        ("g15", "src/a?.test.ts", "src/abc.test.ts", False),
        ("g16", "src/**/*.test.ts", "src/a.test.ts", True),
        ("g17", "./tests/**/*.ts", "tests/a.ts", True),
        ("g18", "+(a|b)/x.ts", "ab/x.ts", True),
        ("g19", "@(a|b)/x.ts", "ab/x.ts", False),
        # Not understood: None, which the caller reads as 'could not tell'.
        ("g20", "!(a)/x.ts", "b/x.ts", None),
        ("g21", "!tests/**", "lib/a.ts", None),
        ("g22", "{1..3}/x.ts", "1/x.ts", None),
        ("g23", "tests/**/*.ts", ".hidden/a.ts", None),
        ("g24", "../x/**", "x/a.ts", None),
        ("g25", "a[b/x.ts", "ab/x.ts", None))
    for cid, pattern, path, want in rows:
        got = M.match_glob(pattern, path)
        check("%s %r vs %r -> %r (got %r)" % (cid, pattern, path, want, got),
              got is want)


def _list_mode(check, tmp):
    root = _project(os.path.join(tmp, "lm"), {
        "vitest.config.ts": "export default { test: { include: ['only/**/*.test.ts'] } }",
        "lib/a.test.ts": "", "lib/b.test.ts": "", "only/c.test.ts": ""})
    both = _lists("lib/a.test.ts", "lib/b.test.ts")
    got = M.collects("lib/a.test.ts", "vitest", root, lister=both)
    check("lm1 the runner's own listing wins over the config: collected, via list",
          got["answer"] == M.COLLECTED and got["via"] == "list")
    got = M.collects("only/c.test.ts", "vitest", root, lister=both)
    check("lm2 an existing file the listing omits is not collected, via list "
          "(the config alone would say collected)",
          got["answer"] == M.NOT_COLLECTED and got["via"] == "list")
    got = M.collects("lib/new.test.ts", "vitest", root, lister=both)
    check("lm3 a path not yet on disk takes its same-suffix siblings' verdict: "
          "collected", got["answer"] == M.COLLECTED and got["via"] == "list")
    got = M.collects("only/new.test.ts", "vitest", root, lister=both)
    check("lm4 ... and not collected when the siblings were left out of the listing",
          got["answer"] == M.NOT_COLLECTED and got["via"] == "list")
    got = M.collects("only/new.test.tsx", "vitest", root, lister=both)
    check("lm5 a new path with no sibling of its suffix falls back to the config "
          "(%s)" % got["via"], got["via"] == "config")
    for label, lister in (("an empty listing", _lists()),
                          ("a runner that failed", lambda r, p: None)):
        got = M.collects("only/c.test.ts", "vitest", root, lister=lister)
        check("lm6 %s is not an answer; the config is read: %s/%s"
              % (label, got["answer"], got["via"]),
              got["answer"] == M.COLLECTED and got["via"] == "config")
    check("lm7 an unknown runner is never handed to any lister (an AssertionError "
          "from `_never` would end the suite)",
          _answer(root, "a.test.js", "mocha", _never) == M.COULD_NOT_TELL)
    lone = _project(os.path.join(tmp, "lm2"), {"package.json": "{}", "x/a.test.ts": ""})
    got = M.collects("x/a.test.ts", "vitest", lone, lister=_lists("x/a.test.ts"))
    check("lm8 a listing alone answers even where no config exists",
          got["answer"] == M.COLLECTED and got["via"] == "list")
    # The real lister, with no vitest installed under the project: it is
    # unavailable, which is None - never an empty list and never a guess.
    check("lm9 no local vitest binary: the lister answers None",
          M.vitest_list("vitest", lone) is None
          and M.jest_list("jest", lone) is None and M.pytest_list("pytest", lone) is None)


def _fake_binary(root, rel, printed):
    """An executable at `rel` that prints `printed` and exits 0 - the lister's
    reader exercised end to end without the real runner installed."""
    _write(root, rel, "#!/bin/sh\ncat <<'EOF'\n%s\nEOF\n" % printed)
    os.chmod(os.path.join(root, *rel.split("/")), 0o755)


def _listers(check, tmp):
    jroot = _project(os.path.join(tmp, "jl"), {
        "jest.config.js": "module.exports = { testMatch: ['**/in/**/*.js'] }",
        "in/a.js": "", "out/b.test.js": ""})
    got = M.collects("out/b.test.js", "jest", jroot, lister=_lists("in/a.js"))
    check("jl1 a jest listing omitting an existing file refutes it, via list "
          "(the testMatch alone would say not collected for a different reason)",
          got["answer"] == M.NOT_COLLECTED and got["via"] == "list"
          and "jest --listTests" in got["basis"])
    got = M.collects("out/b.test.js", "jest", jroot, lister=_lists("out/b.test.js"))
    check("jl2 a jest listing naming the file wins over a testMatch that omits it",
          got["answer"] == M.COLLECTED and got["via"] == "list")
    proot = _project(os.path.join(tmp, "pl"), {"tests/test_a.py": "", "tests/helpers.py": ""})
    got = M.collects("tests/helpers.py", "pytest", proot, lister=_lists("tests/helpers.py"))
    check("pl1 a pytest listing naming a file proves it collected whatever its name",
          got["answer"] == M.COLLECTED and got["via"] == "list")
    got = M.collects("tests/helpers.py", "pytest", proot, lister=_lists("tests/test_a.py"))
    check("pl2 ... but its silence refutes nothing (a file with no test is absent): "
          "the config reading answers instead (%s)" % got["via"],
          got["answer"] == M.NOT_COLLECTED and got["via"] == "default")
    if os.name != "posix":
        return
    froot = _project(os.path.join(tmp, "fb"), {"a/x.test.js": "", "a/y.js": ""})
    _fake_binary(froot, "node_modules/.bin/jest", os.path.realpath(froot) + "/a/x.test.js\n/elsewhere/z.js")
    check("jl3 the real jest reader turns absolute paths into project-relative ones "
          "and drops those outside the project / not on disk: %r" % (M.jest_list("jest", froot),),
          M.jest_list("jest", froot) == ["a/x.test.js"])
    _fake_binary(froot, ".venv/bin/pytest", "a/x.test.js::test_one\na/x.test.js::test_two\n\n2 tests collected in 0.01s")
    check("pl3 the real pytest reader keeps the file part of each node id, once: %r"
          % (M.pytest_list("pytest", froot),), M.pytest_list("pytest", froot) == ["a/x.test.js"])
    _fake_binary(froot, "node_modules/.bin/vitest", "")
    check("jl4 a lister printing no file is no answer (None, not an empty list)",
          M.vitest_list("vitest", froot) is None)


def _jest(check, tmp):
    cfg = ("module.exports = {\n  // testMatch: ['**/nope/**']\n"
           "  roots: ['<rootDir>/src'],\n"
           "  testMatch: ['<rootDir>/src/**/*.spec.ts', '**/__tests__/**/*.ts'],\n};\n")
    root = _project(os.path.join(tmp, "j1"), {"jest.config.js": cfg})
    check("j1 under roots and matching testMatch: collected",
          _answer(root, "src/a/b.spec.ts", "jest") == M.COLLECTED)
    check("j2 outside roots: not collected",
          _answer(root, "lib/b.spec.ts", "jest") == M.NOT_COLLECTED)
    check("j3 inside roots but matching no pattern: not collected",
          _answer(root, "src/a/b.test.ts", "jest") == M.NOT_COLLECTED)
    pkg = _project(os.path.join(tmp, "j2"), {"package.json":
        '{"name": "x", "jest": {"testMatch": ["**/*.check.js"]}}'})
    check("j4 the package.json jest key is read",
          _answer(pkg, "a/b.check.js", "jest") == M.COLLECTED
          and _answer(pkg, "a/b.test.js", "jest") == M.NOT_COLLECTED)
    dflt = _project(os.path.join(tmp, "j3"), {"package.json": "{}"})
    check("j5 jest's documented default testMatch with no config",
          _answer(dflt, "src/a.test.ts", "jest") == M.COLLECTED
          and _answer(dflt, "src/__tests__/h.ts", "jest") == M.COLLECTED
          and _answer(dflt, "src/a.ts", "jest") == M.NOT_COLLECTED)
    check("j5b the default extension set differs between jest versions: .mjs and .cts "
          "under the default testMatch are could-not-tell, .js keeps its answer",
          _answer(dflt, "src/a.test.mjs", "jest") == M.COULD_NOT_TELL
          and _answer(dflt, "src/a.test.cts", "jest") == M.COULD_NOT_TELL
          and _answer(dflt, "src/a.test.js", "jest") == M.COLLECTED)
    for n, (label, text) in enumerate((
            ("testRegex instead of testMatch", "module.exports = { testRegex: '.*\\\\.t$' }"),
            ("projects", "module.exports = { projects: ['<rootDir>/a'], testMatch: ['**/*.t.js'] }"),
            ("a preset that may bring its own testMatch",
             "module.exports = { preset: 'react-native' }"),
            ("a computed testMatch", "module.exports = { testMatch: MATCH }"),
            ("a testMatch relative to nothing",
             "module.exports = { testMatch: ['src/**/*.test.ts'] }"),
            ("a spread", "module.exports = { ...base, testMatch: ['**/*.t.js'] }"))):
        proj = _project(os.path.join(tmp, "jx%d" % n), {"jest.config.js": text})
        check("j6 %s: could not tell" % label,
              _answer(proj, "src/a.t.js", "jest") == M.COULD_NOT_TELL)


def _pytest(check, tmp):
    root = _project(os.path.join(tmp, "p1"), {"pyproject.toml": "[project]\nname='x'\n"})
    check("p1 test_*.py is collected by the defaults",
          _answer(root, "tests/test_a.py", "pytest") == M.COLLECTED)
    check("p2 *_test.py is collected by the defaults",
          _answer(root, "tests/a_test.py", "pytest") == M.COLLECTED)
    check("p3 helpers.py is not collected by the defaults",
          _answer(root, "tests/helpers.py", "pytest") == M.NOT_COLLECTED)
    check("p4 test_a.txt is not collected: the suffix is .py",
          _answer(root, "tests/test_a.txt", "pytest") == M.NOT_COLLECTED)
    for rel, text in (("pytest.ini", "[pytest]\npython_files = check_*.py\n"),
                      ("pyproject.toml", "[tool.pytest.ini_options]\npython_files = ['check_*.py']\n"),
                      ("setup.cfg", "[tool:pytest]\ntestpaths = spec\n"),
                      ("tox.ini", "[pytest]\nnorecursedirs = tests\n")):
        proj = _project(os.path.join(tmp, "p-" + rel.replace(".", "-")), {rel: text})
        check("p5 %s overrides a default: could not tell" % rel,
              _answer(proj, "tests/test_a.py", "pytest") == M.COULD_NOT_TELL
              and _answer(proj, "tests/helpers.py", "pytest") == M.COULD_NOT_TELL)
    quiet = _project(os.path.join(tmp, "p6"), {"pytest.ini": "[pytest]\naddopts = -q\n"})
    check("p6 a pytest config that overrides none of the three keys keeps the defaults",
          _answer(quiet, "tests/test_a.py", "pytest") == M.COLLECTED
          and _answer(quiet, "tests/helpers.py", "pytest") == M.NOT_COLLECTED)


def _cases(check):
    tmp = _harness.fixture_root("runner-collects-")   # removed at exit
    _vitest(check, tmp)
    _refusals(check, tmp)
    _glob(check)
    _list_mode(check, tmp)
    _jest(check, tmp)
    _pytest(check, tmp)
    _listers(check, tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__runner_collects.py --selftest\n")
    raise SystemExit(2)
