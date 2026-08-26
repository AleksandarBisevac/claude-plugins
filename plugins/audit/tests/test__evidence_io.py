#!/usr/bin/env python3
"""
The cases for `governance/_evidence_io.py` - where the test-evidence record lives.

WHAT IS PROVEN HERE, and why each half has a partner. The directory is DERIVED
from `manifestPath` rather than hardcoded, so every case that asserts the default
is paired with one that moves the manifest and asserts the record moved with it -
a resolver that ignored its input would satisfy the first alone forever.

The membership test is a PREFIX comparison, and a prefix comparison written
without its separator admits every sibling whose name merely starts the same way.
So `ev6` is the boundary from the outside, and it is the case that fails when the
test is weakened rather than when it is broken.

The resolution is deliberately the JOURNAL's, one directory over: both answer
"where does this manifest keep its committed record", and two expressions of that
would separate the trail from the evidence the first time a repo set an unusual
`manifestPath`. `ev3` asserts the two agree on the same config rather than
asserting a literal, because a literal would keep agreeing after they diverged.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _evidence_io as M                           # noqa: E402
import _journal_io                                 # noqa: E402


def _project(root, config=None):
    """A project directory with a config, or with none at all."""
    os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
    if config is not None:
        with open(os.path.join(root, ".claude", "audit.config.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(config, fh)
    return root


def _cases(check):
    tmp = _harness.fixture_root("audit-evidence-")
    try:
        # --- where it lives ---------------------------------------------------
        plain = _project(os.path.join(tmp, "plain"), {})
        got = M.evidence_dir(plain)
        check("ev1 with no `evidence` block the record sits beside the manifest, "
              "under the default dirname - and the assertion is against the "
              "manifest's OWN directory rather than a spelled-out path, so it "
              "still holds if the default manifest moves: %r" % (got,),
              got == os.path.normpath(os.path.join(
                  plain, os.path.dirname(_journal_io.DEFAULT_MANIFEST),
                  M.DEFAULT_DIRNAME)))

        moved = _project(os.path.join(tmp, "moved"),
                         {"manifestPath": "plans/audit/plan.json"})
        got_moved = M.evidence_dir(moved)
        check("ev2 ...and the pair that proves it is DERIVED: move `manifestPath` "
              "and the record moves with it. A resolver that ignored its input "
              "would pass ev1 forever: %r" % (got_moved,),
              got_moved == os.path.normpath(
                  os.path.join(moved, "plans", "audit", M.DEFAULT_DIRNAME))
              and os.path.basename(os.path.dirname(got_moved)) == "audit")

        cfg = {"manifestPath": "plans/audit/plan.json"}
        check("ev3 the evidence directory and the journal directory are SIBLINGS "
              "under one manifest - asserted by comparing the two resolvers on "
              "the same config, not against a literal, because a literal keeps "
              "agreeing after they diverge: %r vs %r"
              % (M.evidence_dir(moved, cfg), _journal_io.journal_dir(moved, cfg)),
              os.path.dirname(M.evidence_dir(moved, cfg))
              == os.path.dirname(_journal_io.journal_dir(moved, cfg))
              and M.evidence_dir(moved, cfg)
              != _journal_io.journal_dir(moved, cfg))

        pinned = _project(os.path.join(tmp, "pinned"),
                          {"evidence": {"dir": "var/evidence"}})
        check("ev4 an explicit `evidence.dir` wins over the derivation, which is "
              "what makes the key worth reading at all: %r"
              % (M.evidence_dir(pinned),),
              M.evidence_dir(pinned)
              == os.path.normpath(os.path.join(pinned, "var", "evidence")))

        blank = _project(os.path.join(tmp, "blank"), {"evidence": {"dir": "   "}})
        check("ev5 ...and a blank one does NOT win - it falls back to the "
              "derivation rather than resolving to the project root, which is "
              "where a bare `os.path.join` would have put the whole record: %r"
              % (M.evidence_dir(blank),),
              M.evidence_dir(blank) == os.path.normpath(os.path.join(
                  blank, os.path.dirname(_journal_io.DEFAULT_MANIFEST),
                  M.DEFAULT_DIRNAME))
              and M.evidence_dir(blank) != os.path.normpath(blank))

        # --- membership -------------------------------------------------------
        home = M.evidence_dir(plain)
        os.makedirs(home, exist_ok=True)
        inside = os.path.join(home, "2026-08.w.jsonl")
        check("ev6 a file in the directory is inside it, and a SIBLING whose name "
              "merely starts the same way is not. The pair is the point: a prefix "
              "test written without its separator passes the first half and "
              "admits the second",
              M.in_evidence(plain, inside) is True
              and M.in_evidence(plain, home + "-notes/x.jsonl") is False)

        check("ev7 the directory itself counts as inside, and an unrelated path "
              "does not - the two ends of the same comparison",
              M.in_evidence(plain, home) is True
              and M.in_evidence(plain, os.path.join(plain, "src", "a.py")) is False)

        check("ev8 a project-relative path is resolved against the project, so a "
              "caller holding the spelling git prints does not have to make it "
              "absolute first",
              M.in_evidence(plain, os.path.relpath(inside, plain)) is True)

        check("ev9 a non-string path is False rather than an exception: this "
              "answers a guard's question, and a guard that raises on a payload "
              "it did not expect is a guard that is off",
              M.in_evidence(plain, None) is False
              and M.in_evidence(plain, 17) is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__evidence_io.py --selftest\n")
    raise SystemExit(2)
