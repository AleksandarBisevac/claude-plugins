#!/usr/bin/env python3
"""
The one spelling of "this moment" every stamped time in a plan, a shard, an
evidence row and a worktree record is written in - stdlib only.

WHY THIS IS A MODULE AND NOT A FUNCTION IN EACH WRITER. Writers across
`scripts/` spelled the same ISO-8601 UTC instant each in its own helper, in two idioms
(`time.strftime(..., time.gmtime())` and `datetime.now(timezone.utc).strftime`),
and the module docstrings that explained why one could not borrow another's were
the sign: each writer sat on a different layer, and none could import a sibling's
two lines without an edge the layer lint refuses. The clock lives below all of
them instead, in a layer that reaches nothing but `_output`.

THE GMTIME IDIOM, not `datetime.utcnow()` (deprecated from 3.12, warns onto the
stderr of every run) and not `datetime.UTC` (3.11+, above this tree's 3.8 floor).
It needs no inline import and takes an explicit epoch, so a case can pin the
spelling to a known instant instead of racing the wall clock.

THE HOOKS DO NOT USE THIS. A hook may not import `scripts/`, so its stamp lives in
`hooks/_config.py` under a name that says what it is (`local_stamp`: local time
with its offset, a different spelling on purpose). A format that is not this one
- the compact `%Y%m%dT%H%M%SZ` a migration backup is named with - keeps its own
helper and its own name for the same reason.

The cases for this file live in `tests/test__utc_stamp.py`.
"""
import os
import sys
import time

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

STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_stamp(epoch=None):
    """`epoch` (seconds since the Unix epoch; now when None) as `STAMP_FORMAT` in UTC.

    `epoch=0` is the instant 1970-01-01T00:00:00Z and not "now": the test is
    `is None`, because a falsy zero is a real moment.
    """
    # Argument-less gmtime() when no epoch is given: that call is the seam a test
    # pins a child's clock through, and `gmtime(time.time())` would route around it.
    return time.strftime(STAMP_FORMAT,
                         time.gmtime() if epoch is None else time.gmtime(epoch))


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
