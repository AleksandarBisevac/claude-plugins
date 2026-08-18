#!/usr/bin/env python3
"""
The two things every doctor check needs: somewhere to put a result, and a way
to reach a sibling module.

Split out of `audit-doctor.py` (1,456 lines) along with its six check modules.
This is the piece all six sit on, and it is deliberately the only one that
holds no check at all: `Report` knows nothing about what is being diagnosed
and `_load` knows nothing about what is being loaded, which is why they can sit
at layer 2 under checks that reach as high as layer 5.

`Report` is a class, and that is one of the handful in this tree with a reason
you can say out loud: it is an accumulator with an invariant (every row carries
a level, a check name and a detail) whose whole point is that the checks write
into ONE of it. Rendering is not here — `audit-doctor.render()` owns that, so a
second output format never has to touch this file.

`LAUNCHER_INTERPRETERS` and `RECENT_DAYS` live here because two check modules
read each of them and a constant copied into two files is two constants that
disagree the first time one is edited.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__doctor_report.py` - see
`plugins/audit/tests/_harness.py`.
"""
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

_HOOKS = _output.HOOKS_DIR
sys.path.insert(0, _HOOKS)
import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)

# The interpreters py-launch.sh tries, in its order. Kept in sync deliberately:
# what matters is the interpreter the HOOKS will find, not the one running this.
LAUNCHER_INTERPRETERS = ("python3", "python", "py")

# A hook has "recently run" if state or ledger files were touched inside this many
# days. Matches detect-plan-skip's 7-day GC, so a quiet week is not read as broken.
RECENT_DAYS = 7


# --- loader ---------------------------------------------------------------------
# Decision (P14.3 loader tidy): kept, not inlined. Over _loader.load() alone this
# adds two things every one of the ~15 call sites below would otherwise repeat:
# (1) a `directory` switch (most callers reach scripts/, three reach ../hooks/,
# via _HOOKS) instead of each call site building its own os.path.join, and
# (2) a fixed cache=False — every check re-reads its target fresh, which matters
# here specifically because `tests/test_audit_doctor.py` runs diagnose() repeatedly
# against ONE fixture project it mutates between calls, in ONE process, and a stale
# cached module would be indistinguishable from a real regression (which is also
# why that suite moved WHOLE). It does NOT shape errors: a load
# failure still propagates uncaught to the caller, same as _loader.load().
def _load(name, filename, directory=None):
    """Load a sibling module by path (the filenames are hyphenated).

    With no `directory` this goes through `_loader.load_script`, which resolves a
    scripts/ file by BASENAME wherever it sits; the three hooks/ callers pass
    `_HOOKS` and keep the explicit join, because `hooks/` is not on that walk."""
    if directory is None:
        return _loader.load_script(filename, modname=name, cache=False)
    return _loader.load(os.path.join(directory, filename), modname=name, cache=False)


# --- report ---------------------------------------------------------------------
class Report(object):
    """Collects results; knows nothing about how they are rendered."""

    def __init__(self):
        self.rows = []

    def add(self, level, check, detail, fix=None):
        self.rows.append({"level": level, "check": check, "detail": detail,
                          "fix": fix})

    def ok(self, check, detail):
        self.add("OK", check, detail)

    def warn(self, check, detail, fix=None):
        self.add("WARNING", check, detail, fix)

    def finding(self, check, detail, fix=None):
        self.add("FINDING", check, detail, fix)

    def counts(self):
        out = {"OK": 0, "WARNING": 0, "FINDING": 0}
        for r in self.rows:
            out[r["level"]] = out.get(r["level"], 0) + 1
        return out

    def exit_code(self):
        return 1 if self.counts()["FINDING"] else 0


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_doctor_report.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__doctor_report.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
