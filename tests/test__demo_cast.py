#!/usr/bin/env python3
"""
The cases for `_demo_cast.py` — three identities two generators must agree on.

The module is one tuple, and the cases are not about the tuple's contents. They
are about the AGREEMENT: `gen-demo-usage.py` stamps these authors on every
synthetic ledger row and `gen-demo-manifest.py` hands the same ones out as
`meta.areas[*].owner`, precisely so the shipped demo shows `/audit:doctor`'s
owner-versus-ledger join succeeding. If the two ever disagreed, the demo would
render that warning about itself — a fixture failing the check it exists to
demonstrate.

That is why a three-line module earns a test file: the risk here was never that
the tuple is wrong, it is that a second copy appears and nothing compares them.
`gen-demo-manifest.py` used to read the tuple off `gen-demo-usage.py` through
`_loader`, which is one entry point loading another for one name — the last of
the seventeen `KNOWN_LAYER_DEBT` edges.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _demo_cast as M                             # noqa: E402

_USAGE = _loader.load_script("gen-demo-usage.py", modname="gen_demo_usage_cast")
_MANIFEST = _loader.load_script("gen-demo-manifest.py",
                                modname="gen_demo_manifest_cast")


# --- cases --------------------------------------------------------------------
def _cases(check):
    check("c1 the cast is a non-empty tuple of strings",
          isinstance(M.DEFAULT_AUTHORS, tuple) and M.DEFAULT_AUTHORS
          and all(isinstance(a, str) and a for a in M.DEFAULT_AUTHORS),
          repr(M.DEFAULT_AUTHORS))
    # RFC 2606 reserves `.example` so a fixture can carry an address that can
    # never route to a real person. Asserted rather than trusted, because the one
    # way this fixture could do harm is by shipping someone's real mailbox.
    _bad = [a for a in M.DEFAULT_AUTHORS if not a.endswith(".example")]
    check("c2 every identity is under the reserved `.example` TLD, so no demo "
          "fixture can name a mailbox that exists: %r" % (_bad,), _bad == [])

    check("c3 gen-demo-usage.py's DEFAULT_AUTHORS IS this tuple, not a copy - "
          "identity, so a pasted-back literal fails here rather than drifting",
          _USAGE.DEFAULT_AUTHORS is M.DEFAULT_AUTHORS)

    # The claim that makes the module exist: the manifest generator hands out
    # exactly these owners. Checked against the GENERATED fixture rather than
    # against the source, because what matters is what the demo ships.
    _areas = _MANIFEST._demo_areas()
    _owners = set(e["owner"] for e in _areas.values() if "owner" in e)
    _unknown = sorted(_owners - set(M.DEFAULT_AUTHORS))
    check("c4 every area owner in the generated demo manifest is one of the "
          "cast - which is the join /audit:doctor checks, so the fixture "
          "demonstrates a pass instead of warning about itself: %r" % (_unknown,),
          _owners and _unknown == [])
    # The second direction, and it reads vacuous beside c4: c4 also passes if the
    # generator stopped assigning owners at all (empty set minus anything is
    # empty). This is the case that fails on that mutation.
    check("c5 ...and owners are actually assigned - c4 would pass over a "
          "manifest that had stopped setting `owner` entirely",
          len(_owners) >= 2, sorted(_owners))
    # `infra` is deliberately ownerless: the no-owner case has to render too.
    check("c6 `infra` stays ownerless on purpose, so the demo carries the "
          "no-owner case as well as the matched one",
          "owner" not in (_areas.get("infra") or {}))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__demo_cast.py --selftest\n")
    raise SystemExit(2)
