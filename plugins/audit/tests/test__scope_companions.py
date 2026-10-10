#!/usr/bin/env python3
"""
The cases for `_scope_companions.py` - the files a task's change cannot avoid.

The danuvia shape is the reason the module exists: P1.2 added a dependency and
widened onto `package.json` and `pnpm-lock.yaml`, P1.3 put a test outside
`vitest.config.ts`'s include, P1.5 added strings and widened onto both locale
files. Each group below is one companion kind. Every group carries the allow
case beside the add case - a derivation that adds a lockfile nobody has, or a
config for a test the runner does collect, is the over-firing mutation, and only
a case that expects NOTHING catches it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _scope_companions as M                      # noqa: E402

VITEST_NARROW = """\
export default defineConfig({
  test: { include: ['tests/unit/**/*.test.ts'] },
});
"""


def _write(root, rel, text=""):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


def _repo(tmp, name, files):
    root = os.path.join(tmp, name)
    os.makedirs(root)
    for rel in files:
        _write(root, rel, VITEST_NARROW if rel.startswith("vitest.config") else "{}")
    return root


def _paths(result):
    return [c["path"] for c in result["companions"]]


def _no_list(runner, project):
    return None


def _dependency(check, tmp):
    p12 = _repo(tmp, "p12", ["package.json", "pnpm-lock.yaml", "next.config.ts", "proxy.ts"])
    got = M.derive({"dependencies": ["next-intl"], "files": ["next.config.ts", "proxy.ts"]}, p12)
    check("dep1 P1.2: package.json and the pnpm lockfile on disk are the companions, in that order",
          _paths(got) == ["package.json", "pnpm-lock.yaml"], _paths(got))
    check("dep2 P1.2: package-lock.json is not added - it is not on disk",
          "package-lock.json" not in _paths(got), _paths(got))
    check("dep3 every companion carries a basis that names its path",
          all(c["path"] in c["basis"] for c in got["companions"]) and len(got["companions"]) == 2,
          got["companions"])

    bare = _repo(tmp, "nolock", ["package.json"])
    got = M.derive({"dependencies": ["next-intl"]}, bare)
    check("dep4 no lockfile: only the manifest is added", _paths(got) == ["package.json"], _paths(got))
    check("dep5 no lockfile: a basis line says so rather than staying silent",
          sum("no lockfile" in n for n in got["notes"]) == 1, got["notes"])

    npm = _repo(tmp, "npm", ["package.json", "package-lock.json"])
    check("dep6 package-lock.json IS added when it is the one on disk (the other direction)",
          _paths(M.derive({"dependencies": ["x"]}, npm)) == ["package.json", "package-lock.json"])

    both = _repo(tmp, "both", ["package.json", "pnpm-lock.yaml", "yarn.lock"])
    got = M.derive({"dependencies": ["x"]}, both)
    check("dep7 two lockfiles on disk: both added and the note says there were two",
          _paths(got) == ["package.json", "pnpm-lock.yaml", "yarn.lock"]
          and any("more than one" in n for n in got["notes"]), got)

    mono = _repo(tmp, "mono", ["apps/web/package.json", "pnpm-lock.yaml", "apps/web/page.tsx"])
    got = M.derive({"dependencies": ["x"], "files": ["apps/web/page.tsx"]}, mono)
    check("dep8 a nested package: its own manifest, and the workspace lockfile above it",
          _paths(got) == ["apps/web/package.json", "pnpm-lock.yaml"], _paths(got))

    py = _repo(tmp, "py", ["pyproject.toml", "uv.lock"])
    check("dep9 python: pyproject.toml and uv.lock",
          _paths(M.derive({"dependencies": ["httpx"]}, py)) == ["pyproject.toml", "uv.lock"])
    poetry = _repo(tmp, "poetry", ["pyproject.toml", "poetry.lock"])
    check("dep10 python: poetry.lock when that is the one",
          _paths(M.derive({"dependencies": ["httpx"]}, poetry)) == ["pyproject.toml", "poetry.lock"])

    none = _repo(tmp, "nomanifest", ["README.md"])
    got = M.derive({"dependencies": ["x"]}, none)
    check("dep11 no manifest at all: nothing added and the note says no manifest was found",
          _paths(got) == [] and any("no dependency manifest" in n for n in got["notes"]), got)

    both_eco = _repo(tmp, "eco", ["package.json", "pyproject.toml", "uv.lock", "pnpm-lock.yaml"])
    got = M.derive({"dependencies": ["x"]}, both_eco)
    check("dep12 two ecosystems in one directory: nothing guessed, the note names the ambiguity",
          _paths(got) == [] and any("ambiguous" in n for n in got["notes"]), got)
    got = M.derive({"dependencies": ["x"], "ecosystem": "python"}, both_eco)
    check("dep13 ...and the caller naming the ecosystem resolves it",
          _paths(got) == ["pyproject.toml", "uv.lock"], _paths(got))

    got = M.derive({"dependencies": ["x"], "files": ["package.json", "pnpm-lock.yaml"]}, p12)
    check("dep14 a companion already declared is not added twice",
          _paths(got) == [], _paths(got))

    check("dep15 no dependency in the intent: no manifest, no note (the allow case)",
          M.derive({"files": ["proxy.ts"]}, p12) == {"companions": [], "notes": []})


def _strings(check, tmp):
    p15 = _repo(tmp, "p15", ["messages/en.json", "messages/sr.json", "messages/README.md",
                              "app/globals.css"])
    got = M.derive({"userStrings": True}, p15)
    check("loc1 P1.5: both locale files, and not the readme beside them",
          _paths(got) == ["messages/en.json", "messages/sr.json"], _paths(got))
    check("loc2 each locale companion carries a basis naming its directory",
          all("messages" in c["basis"] for c in got["companions"]), got["companions"])

    nested = _repo(tmp, "nested", ["locales/en/common.json", "locales/sr/common.json",
                                    "locales/sr/errors.json"])
    check("loc3 locales/<lang>/... : every file under every language directory",
          _paths(M.derive({"userStrings": True}, nested))
          == ["locales/en/common.json", "locales/sr/common.json", "locales/sr/errors.json"])

    plain = _repo(tmp, "plain", ["data/en.json", "data/sr.json"])
    got = M.derive({"userStrings": True}, plain)
    check("loc4 a directory not named like a locale directory is never guessed at",
          _paths(got) == [] and any("no locale directory" in n for n in got["notes"]), got)

    two = _repo(tmp, "two", ["messages/en.json", "locales/en.json"])
    got = M.derive({"userStrings": True}, two)
    check("loc5 two candidate locale directories: nothing added, both named in the note",
          _paths(got) == [] and any("messages" in n and "locales" in n for n in got["notes"]), got)

    check("loc6 userStrings off: the locale files are not added (the allow case)",
          _paths(M.derive({"userStrings": False}, p15)) == [])


def _runner(check, tmp):
    repo = _repo(tmp, "runner", ["vitest.config.ts", "package.json"])
    got = M.derive({"tests": ["lib/store.test.ts"], "runner": "vitest"}, repo, lister=_no_list)
    check("run1 a test outside the include glob brings vitest.config.ts",
          _paths(got) == ["vitest.config.ts"], got)
    check("run2 ...with the runner's own basis", any("tests/unit" in c["basis"] for c in got["companions"]),
          got["companions"])

    got = M.derive({"tests": ["tests/unit/store.test.ts"], "runner": "vitest"}, repo, lister=_no_list)
    check("run3 a test the include does collect adds nothing (the allow case)",
          _paths(got) == [], got)
    check("run4 ...and a note says the runner collects it", len(got["notes"]) == 1 and "collects" in got["notes"][0],
          got["notes"])

    got = M.derive({"tests": ["lib/store.test.ts"], "runner": "mocha"}, repo, lister=_no_list)
    check("run5 COULD_NOT_TELL adds nothing", _paths(got) == [], got)
    check("run6 ...and says it could not tell, with the reason",
          len(got["notes"]) == 1 and "could not tell" in got["notes"][0] and "mocha" in got["notes"][0],
          got["notes"])

    got = M.derive({"tests": ["lib/a.test.ts", "lib/b.test.ts"], "runner": "vitest"}, repo, lister=_no_list)
    check("run7 two uncollected tests name the config once", _paths(got) == ["vitest.config.ts"], got)

    bare = _repo(tmp, "bareconf", ["package.json"])
    got = M.derive({"tests": ["tests/x.ts"], "runner": "vitest"}, bare, lister=_no_list)
    check("run8 not collected by a default and no config file on disk: nothing to widen, note says so",
          _paths(got) == [] and any("no config file" in n for n in got["notes"]), got)

    check("run9 no tests in the intent: the lister is never asked (the allow case)",
          M.derive({"runner": "vitest"}, repo, lister=_never) == {"companions": [], "notes": []})


def _never(runner, project):
    raise AssertionError("the runner was asked with no test in the intent")


def _cases(check):
    tmp = _harness.fixture_root("scope-companions-")   # removed at exit
    _dependency(check, tmp)
    _strings(check, tmp)
    _runner(check, tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__scope_companions.py --selftest\n")
    raise SystemExit(2)
