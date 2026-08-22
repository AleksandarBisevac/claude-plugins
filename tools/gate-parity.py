#!/usr/bin/env python3
"""
The local gate set and the CI gate set must name the same gates.

    tools/gate-parity.py            # the check
    tools/gate-parity.py --list     # what each side invokes, side by side
    tools/gate-parity.py --selftest # this file's own cases

WHY. The gate set was described in three places by hand - `CLAUDE.md`,
`tools/verify.sh` and `.github/workflows/ci.yml` - and by the time anyone measured
it, the three had drifted IN BOTH DIRECTIONS at once:

  * the selftest sweep existed twice with different strictness, so a file that
    exited 0 having asserted nothing was green locally and red in CI;
  * `npx vitest run` - 28 files, 305 tests - ran only in CI, so a change under
    `scripts/ui/` could reach a push with none of its suites having run;
  * `vermin` covered three directories locally and two in CI, so a 3.9+ construct
    in a test file passed CI and failed locally.

Three copies of one list is how that happens, and fixing each instance by hand is
how it happens again. This makes the parity a CHECK: a gate added to one side and
not the other fails the build by name.

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

VERIFY_REL = os.path.join("tools", "verify.sh")
CI_REL = os.path.join(".github", "workflows", "ci.yml")

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

# CI runs it and `verify.sh` does not, on purpose. Each entry owes a reason a reader
# can disagree with.
CI_ONLY = (
    ("plugins/audit/scripts/demo/gen-demo-manifest.py",
     "builds a throwaway demo tree in /tmp to smoke the pipeline end to end; "
     "verify.sh checks the COMMITTED artifacts instead"),
    ("plugins/audit/scripts/demo/gen-demo-usage.py",
     "same throwaway demo tree"),
    ("plugins/audit/scripts/report/render-report.py",
     "rendered into /tmp as a smoke test; locally the equivalent claim is "
     "check-rendered-artifacts.py, which is stronger because it compares bytes"),
    ("plugins/audit/scripts/status/audit-doctor.py",
     "an end-to-end CLI smoke test over a fixture project"),
    ("plugins/audit/scripts/status/audit-status.py",
     "exercises --gate's exit codes, which need a fixture manifest per case"),
    ("plugins/audit/hooks/py-launch.sh",
     "the launcher is driven directly with fixture projects and with PATH unset, "
     "to prove the WIRING rather than decide(): the interpreter fallback, the stdin "
     "contract and the emitted JSON. Neither unsetting PATH nor feeding three "
     "fixture manifests is a thing to do to a developer's shell. The hooks it "
     "drives - require-plan.py, guard-edits.py, guard-secrets-read.py - are "
     "ARGUMENTS to it, not paths, so this one entry covers all of them"),
)

# `verify.sh` runs it and CI does not, on purpose.
# `verify.sh` runs it and CI does not, on purpose.
LOCAL_ONLY = (
    ("tools/affected.py",
     "a SELECTOR, not a gate: it narrows a local run and CI never narrows. Its own "
     "cases DO run on both sides - inside the sweep, which covers tools/ - so what "
     "is exempt here is the narrowing itself, not the checking of it"),
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
    reader = _yaml_run_lines if path.endswith((".yml", ".yaml")) else \
        _shell_command_lines
    body = "\n".join(reader(text))
    for match in _SCRIPT_RE.finditer(body):
        found.add(match.group(0))
    for label, pattern in _EXTERNAL:
        if pattern.search(body):
            found.add(label)
    return found


def parity(repo=None):
    """{"missing_local": [...], "missing_ci": [...], "stale_exemptions": [...],
    "local": n, "ci": n}.

    Every list is of `(gate, note)` pairs so a failure names the gate AND says which
    table would have to change to make it legal.
    """
    repo = repo or REPO
    local = gates_in(os.path.join(repo, VERIFY_REL))
    ci = gates_in(os.path.join(repo, CI_REL))
    if local is None or ci is None:
        missing = VERIFY_REL if local is None else CI_REL
        return {"missing_local": [], "missing_ci": [],
                "stale_exemptions": [(missing, "could not be read at all")],
                "local": 0, "ci": 0}
    ci_only = dict(CI_ONLY)
    local_only = dict(LOCAL_ONLY)

    missing_local = sorted((g, "in CI only; add it to %s or declare it in CI_ONLY"
                            % (VERIFY_REL,))
                           for g in ci - local if g not in ci_only)
    missing_ci = sorted((g, "local only; add it to %s or declare it in LOCAL_ONLY"
                         % (CI_REL,))
                        for g in local - ci if g not in local_only)
    # TWO WAYS AN EXEMPTION STOPS DESCRIBING THE SYSTEM, and the second is the one
    # a single-direction check cannot see: an entry naming a gate BOTH sides now run
    # is not an exemption at all, it is a sentence about a state that has passed. It
    # stays green forever under the first rule alone, and the table becomes a place
    # where dead reasons accumulate.
    stale = sorted([(g, "declared CI-only, but CI does not invoke it any more")
                    for g in ci_only if g not in ci]
                   + [(g, "declared local-only, but %s does not invoke it any more"
                       % (VERIFY_REL,)) for g in local_only if g not in local]
                   + [(g, "declared CI-only, but %s invokes it too - the exemption "
                          "does nothing" % (VERIFY_REL,))
                      for g in ci_only if g in ci and g in local]
                   + [(g, "declared local-only, but CI invokes it too - the "
                          "exemption does nothing")
                      for g in local_only if g in local and g in ci])
    return {"missing_local": missing_local, "missing_ci": missing_ci,
            "stale_exemptions": stale, "local": len(local), "ci": len(ci)}


def render(result, stream=None):
    """Print the verdict. Returns the exit code."""
    out = stream if stream is not None else sys.stdout
    bad = (result["missing_local"] + result["missing_ci"]
           + result["stale_exemptions"])
    out.write("gate parity: %d gate(s) in %s, %d in %s\n"
              % (result["local"], VERIFY_REL, result["ci"], CI_REL))
    for label, rows in (("missing from the LOCAL gate set", result["missing_local"]),
                        ("missing from the CI gate set", result["missing_ci"]),
                        ("stale exemption", result["stale_exemptions"])):
        for gate, note in rows:
            out.write("  %s: %s\n      %s\n" % (label, gate, note))
    if not bad:
        out.write("  the two sides name the same gates, and every declared "
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
    out.append(("p0", real["missing_local"] == [] and real["missing_ci"] == []
                and real["stale_exemptions"] == [],
                "THE LIVE CLAIM: this repo's two gate sets name the same gates and "
                "no exemption has gone stale (%d local, %d ci) - %r"
                % (real["local"], real["ci"],
                   real["missing_local"] + real["missing_ci"]
                   + real["stale_exemptions"])))

    out.append(("p1", real["local"] > 5 and real["ci"] > 5,
                "...and both sides were really READ, so p0 is not two empty sets "
                "agreeing: %d gates locally, %d in CI"
                % (real["local"], real["ci"])))

    body = _shell_command_lines(
        "# node tools/ghost.mjs\n  ruff check x  # ruff check y\n")
    out.append(("c0", body == ["ruff check x"],
                "a commented invocation is NOT an invocation, and a trailing "
                "comment is cut - both files discuss their own gates at length, so "
                "without this every mention would register as a gate: %r" % (body,)))

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

    tmp = _output.REPO_ROOT  # any real directory; the point is the missing file
    res = parity(os.path.join(tmp, "no-such-repo-dir"))
    out.append(("m0", len(res["stale_exemptions"]) == 1
                and "could not be read" in res["stale_exemptions"][0][1],
                "an unreadable gate file is a NAMED failure, not perfect parity - "
                "returning empty sets for both would report two missing files as "
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

    ci_seen = gates_in(os.path.join(REPO, CI_REL))
    for gate, _why in CI_ONLY:
        if gate not in ci_seen:
            out.append(("x-%s" % (gate,), False,
                        "CI_ONLY names %s but CI does not invoke it" % (gate,)))
    out.append(("e0", all(g in ci_seen for g, _w in CI_ONLY),
                "every CI_ONLY entry is a gate CI really runs (%d entries) - an "
                "exemption for something that no longer exists is how a table "
                "stops describing the system" % (len(CI_ONLY),)))

    both = parity()
    out.append(("e1", not any("does nothing" in note
                              for _g, note in both["stale_exemptions"]),
                "no declared exemption names a gate BOTH sides run. An entry that "
                "did would stay green under a check that only asks whether its own "
                "side still runs it, which is how a table of reasons turns into a "
                "table of history: %r" % (both["stale_exemptions"],)))

    buf = io.StringIO()
    code = render({"missing_local": [("tools/x.mjs", "why")], "missing_ci": [],
                   "stale_exemptions": [], "local": 3, "ci": 4}, stream=buf)
    out.append(("r0", code == 1 and "tools/x.mjs" in buf.getvalue()
                and "why" in buf.getvalue(),
                "a gap exits 1 and prints both the gate and what to do about it"))

    buf = io.StringIO()
    code = render({"missing_local": [], "missing_ci": [], "stale_exemptions": [],
                   "local": 9, "ci": 9}, stream=buf)
    out.append(("r1", code == 0 and "same gates" in buf.getvalue(),
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
