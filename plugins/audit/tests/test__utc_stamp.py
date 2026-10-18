#!/usr/bin/env python3
"""
The cases for `_utc_stamp.py` - the one spelling of "this moment" the writers share.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The spelling, at a known instant.** The expected text is a literal, so a
  helper that formatted local time, dropped the `Z`, or used a space for the `T`
  each fails.
- **Zero is a moment, not "now".** `epoch=0` is the guard against `epoch or now`.
- **No epoch means the clock**, bracketed by two readings of the clock itself.
- **The same text the writers wrote before they shared one**, checked against the
  two idioms they used (gmtime and the aware datetime) at the same instant.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import datetime
import re
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _utc_stamp as M                             # noqa: E402


def _cases(check):
    check("us1 a fixed epoch gives the plan's one UTC spelling, read off a "
          "literal: %r" % (M.utc_stamp(1700000000),),
          M.utc_stamp(1700000000) == "2023-11-14T22:13:20Z")

    check("us2 epoch zero is the Unix epoch and not 'now' - the guard against "
          "`epoch or time.time()`, whose falsy zero would read the clock: %r"
          % (M.utc_stamp(0),),
          M.utc_stamp(0) == "1970-01-01T00:00:00Z")

    before = int(time.time())
    got = M.utc_stamp()
    after = int(time.time())
    shaped = re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", got) is not None
    check("us3 no epoch reads the clock: the stamp lies between two readings of "
          "it, and has the shape: %r" % (got,),
          shaped and M.utc_stamp(before) <= got <= M.utc_stamp(after))

    instant = 1234567890
    aware = (datetime.datetime.fromtimestamp(instant, datetime.timezone.utc)
             .strftime("%Y-%m-%dT%H:%M:%SZ"))
    check("us4 the same text the datetime idiom wrote before the writers shared "
          "one, so moving to this helper changes no stamp already on disk: %r"
          % (aware,),
          M.utc_stamp(instant) == aware == "2009-02-13T23:31:30Z")


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__utc_stamp.py --selftest\n")
    raise SystemExit(2)
