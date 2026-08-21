#!/usr/bin/env python3
"""
The cases for `resolve-branch.py` — the DOOR, not the rule behind it.

`test__branch.py` tests what a branch name and a parent branch MEAN; this file
tests the command: arguments, exit codes, and the printed answer, which is half
the contract because the orchestrator reads it rather than importing anything.

WHAT IS PINNED, and why each one is here rather than trusted:

- **Exit 1 is reserved for a name git would reject**, and nothing else reaches
  it. A type outside `meta.branch.types` and a phase merging into a story branch
  are both REPORTED at exit 0 — this is `SECURITY.md`'s advisory/gate split, and
  an advisory that exits non-zero would stop runs it has no business stopping.
- **The story-branch NOTE is printed, not merely computed.** `parentIsDevelopment`
  being False in the JSON is worth nothing if the human-readable mode stays
  quiet: the sign-off report is written from this output, and silence there reads
  as "the work landed on main".
- **A usage error is 2 and never a lucky 0.** An unreadable manifest, a missing
  `--phase`, and a phase id that is not in the plan are three different mistakes
  and all three must refuse rather than resolve something plausible.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import io
import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (entry points load by name)

M = _loader.load_script("resolve-branch.py")

PHASE = {"id": "P0", "title": "Chart export", "status": "pending", "tasks": []}


def _manifest(meta=None, phase=None):
    return {"meta": dict({"version": 2, "developmentBranch": "main"}, **(meta or {})),
            "phases": [dict(PHASE, **(phase or {}))]}


def _write(tmp, name, obj):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def _run(argv):
    """(exit code, stdout) — the printed answer is half this command's contract."""
    buf, real = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = M.main(argv)
    finally:
        sys.stdout = real
    return code, buf.getvalue()


def _cases(check):
    check("rb0 no arguments is a usage error, not an accidental pass",
          M.main([]) == 2)
    tmp = tempfile.mkdtemp(prefix="qg-resolvebranch-")
    try:
        legacy = _write(tmp, "legacy.json", _manifest({"branchPrefix": "audit"}))
        modern = _write(tmp, "modern.json", _manifest(
            {"branch": {"template": "{type}/{initials}/{phase}-{slug}"}}))
        story = _write(tmp, "story.json", _manifest(
            {"branch": {"template": "{type}/{phase}-{slug}"}},
            {"parentBranch": "feature/jd/p9-story"}))
        illegal = _write(tmp, "illegal.json", _manifest(
            {"branch": {"template": "{type}//{phase}"}}))
        odd_type = _write(tmp, "oddtype.json", _manifest(
            {"branch": {"template": "{type}/{phase}"}}, {"branchType": "wip"}))

        # --- usage errors, three different mistakes -------------------------
        check("rb1 an unreadable manifest is 2 - never a fall-through to a "
              "plausible-looking default branch name",
              M.main(["/no/such/manifest.json", "--phase", "P0"]) == 2)
        check("rb2 a manifest with no --phase and no --globs is 2: the command "
              "has nothing to resolve and must say so rather than pick a phase",
              M.main([legacy]) == 2)
        check("rb3 a phase id that is not in the plan is 2, not a name composed "
              "from an empty phase - a branch for a phase that does not exist "
              "is the shape that gets created and then orphaned",
              M.main([legacy, "--phase", "P9"]) == 2)

        # --- the resolved answer ---------------------------------------------
        code, out = _run([legacy, "--phase", "P0"])
        check("rb4 a legacy manifest resolves at exit 0 and names "
              "meta.branchPrefix as what decided the convention",
              code == 0 and "audit/p0-chart-export" in out
              and "meta.branchPrefix" in out, repr(out))
        code, out = _run([modern, "--phase", "P0"])
        check("rb5 a meta.branch manifest resolves at exit 0 and says so",
              code == 0 and "meta.branch" in out and "p0-chart-export" in out,
              repr(out))

        # --- the note that sign-off is written from ---------------------------
        code, out = _run([story, "--phase", "P0"])
        check("rb6 a phase merging into a story branch PRINTS the note, at exit "
              "0. Computing parentIsDevelopment and staying quiet would be "
              "worthless: the sign-off report is written from this text, and "
              "silence about the real merge target reads as 'landed on main'",
              code == 0 and "NOT into the development branch" in out
              and "feature/jd/p9-story" in out, repr(out))
        code, out = _run([modern, "--phase", "P0"])
        check("rb7 ...and a phase that DOES target the development branch prints "
              "no such note - the mutation-in-the-other-direction case, without "
              "which rb6 would pass on a version that printed it always",
              "NOT into the development branch" not in out, repr(out))

        # --- exit 1 is reserved -----------------------------------------------
        code, out = _run([illegal, "--phase", "P0"])
        check("rb8 a composed name git would reject is exit 1, and says which "
              "rule it breaks - `git switch -c` fails anyway, and this is the "
              "version that says why",
              code == 1 and "not a legal git ref" in out, repr((code, out)))
        code, out = _run([odd_type, "--phase", "P0"])
        check("rb9 a type outside meta.branch.types WARNS at exit 0, because the "
              "branch is legal and the run works - what it costs is the "
              "pre-approved glob. An advisory that exited non-zero would stop "
              "runs it has no business stopping (SECURITY.md's split)",
              code == 0 and "pre-approved globs" in out, repr((code, out)))

        # --- globs and json ---------------------------------------------------
        code, out = _run([legacy, "--globs"])
        check("rb10 --globs prints the legacy prefix glob and nothing wider - "
              "the permission surface must not widen just because the code "
              "learned about types",
              code == 0 and out.strip() == "audit/*", repr(out))
        code, out = _run([modern, "--globs"])
        check("rb11 ...and a meta.branch manifest prints one glob per type",
              code == 0 and "feature/*" in out and "bugfix/*" in out, repr(out))
        code, out = _run([story, "--phase", "P0", "--json"])
        ok, parsed = _harness.attempt(json.loads, out)
        check("rb12 --json carries the same answer as an object, including the "
              "flag the note is printed from, so a caller can branch on it "
              "without parsing prose",
              ok and parsed.get("parentIsDevelopment") is False
              and parsed.get("parent") == "feature/jd/p9-story", repr(out))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_resolve_branch.py --selftest\n")
    raise SystemExit(2)
