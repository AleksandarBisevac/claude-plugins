#!/usr/bin/env python3
"""The one command of the third place: a pre-push hook's whole obligation.

WHY IT EXISTS. `run-test-gate.py --full --record` is the one measurement
`meta.fullGate` deserves - the whole product, not one phase's or one task's
claim - but a pre-push hook or a CI step should not have to spell that
sentence out itself, refuse a phase argument beside `--full`, or decide what
a plan with no third place declared means. This file is that decision, made
once: run the real command as a SUBPROCESS (an entry point may not import
another entry point - `_deps.KNOWN_LAYER_DEBT` is the list of the rare
exceptions and this is not one), stream what it prints, and exit with its
code.

THE ONE BRANCH THIS FILE DECIDES FOR ITSELF. With no `meta.fullGate`
declared, `run-test-gate.py --full` refuses (exit 2 - a phase-scope caller
asking for a run with nothing to run is a usage error). A pre-push hook is
not that caller: a plan that never declared a third place must not block
every push from every contributor, forever, over a gate nobody asked for.
So THIS file reads `meta.fullGate` itself, before invoking anything, and
answers with the sentence and exit 0 rather than letting the runner's own
usage refusal reach an operator's shell as a blocked push. Read directly
off the manifest dict rather than through `_evidence_io.resolved_commands`:
that function also resolves aliases and couplings, which is a question
about WHAT the third place runs, and this file only asks whether one is
declared at all - the identical presence check `run-test-gate.py`'s own
`_run_full` makes one line above calling `resolved_commands` in the first
place.

THE OTHER BRANCH DOES NOT LEARN. This phase's script does not read the
evidence ledger, does not compare a selection-miss against what actually
broke, and does not open a bug on a red run - that pass belongs to whatever
phase comes after this one. What this file owes is delegation: the runner's
exit code, unchanged, is this file's exit code.

Usage:
  full-gate.py <manifest> [--writer NAME] [--project-dir DIR]

Exit codes:
  0  no meta.fullGate declared (nothing to run), or the full run was green
  1  the full run was red
  2  usage error, or the manifest will not load

This module carries no `--selftest` of its own; its cases live in
plugins/audit/tests/test_full_gate.py.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import os
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _loader  # noqa: E402  (script_path: resolves run-test-gate.py by basename,
#                              never loads it - the subprocess boundary below is
#                              exactly why that edge is not counted by `_deps`)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)

E_OK, E_FAIL, E_USAGE = 0, 1, 2

PREFIX = "[full-gate]"

NO_THIRD_PLACE = (
    "%s no meta.fullGate declared - this plan names no third place, so "
    "nothing here blocks the push" % (PREFIX,))


def declares_full_gate(manifest):
    """True when `meta.fullGate` names at least one entry.

    THE SAME PRESENCE CHECK `run-test-gate.py`'s own `_run_full` makes
    (`entries = (meta.get("fullGate") or [])`), read here rather than through
    `_evidence_io.resolved_commands` - that function also resolves aliases and
    couplings, a question about WHAT the third place runs, while this file
    only asks whether one is declared before deciding whether to invoke the
    runner at all.
    """
    entries = ((manifest.get("meta") or {}).get("fullGate") or [])
    return bool(entries)


def _stream_subprocess(cmd, out):
    """Run `cmd`, printing every line of its combined output as it arrives,
    and return its exit code.

    THE SEAM. A test replaces this function rather than the subprocess module
    itself, so a fixture can hand back canned lines and an exit code without
    a real child process - the same shape `derive-phase-gate.py`'s `_spawn`
    is replaced by in its own tests. Combined stdout+stderr, unbuffered line
    by line, because the point of streaming at all is that an operator
    watching a pre-push hook sees the runner's own progress rather than a
    silence followed by one final verdict.
    """
    import subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        for line in proc.stdout:
            out(line.rstrip("\n"))
    finally:
        proc.stdout.close()
    return proc.wait()


def _run_full_gate(manifest_path, writer, project_dir, out):
    """Build and run the one delegated command, returning its exit code.

    NEVER RE-IMPLEMENTS THE RUN. Every flag here is `run-test-gate.py`'s own:
    `--full --record` is the measurement this file exists to make easy to
    reach, and `--writer`/`--project-dir` pass through unchanged rather than
    being re-parsed and re-validated a second time by a second parser that
    could drift from the first.
    """
    cmd = [sys.executable, _loader.script_path("run-test-gate.py"),
          manifest_path, "--full", "--record"]
    if writer:
        cmd += ["--writer", writer]
    if project_dir:
        cmd += ["--project-dir", project_dir]
    return _stream_subprocess(cmd, out)


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="full-gate.py", add_help=True)
    p.add_argument("manifest")
    p.add_argument("--writer", dest="writer", default=None)
    p.add_argument("--project-dir", dest="project_dir", default=None)
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        out("%s cannot read the manifest: %s" % (PREFIX, exc))
        return E_USAGE
    if not declares_full_gate(manifest):
        out(NO_THIRD_PLACE)
        return E_OK
    return _run_full_gate(args.manifest, args.writer, args.project_dir, out)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("full-gate.py: cases live in "
              "plugins/audit/tests/test_full_gate.py")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
