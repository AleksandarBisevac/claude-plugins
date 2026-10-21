#!/usr/bin/env python3
"""
The cases for `_config_rules_lints.py` - the drift checks between the config
vocabulary and the three places that restate it (the schema, the defaults file and
the README's key table), which were the second half of `_config_rules.py` before the
lints left the plugin.

`L` is the module under test and `M` is `_config_rules`. The cases for what stayed are
in `tests/test__config_rules.py`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (load_hooks_config only)
import _policy                                     # noqa: E402
import _config_rules as M                          # noqa: E402
import _config_rules_lints as L                          # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    _hcfg = _loader.load_hooks_config(modname="audit__config_vc_selftest")
    check("the key sets ARE _policy's, not a copy - a fourth statement of this "
          "shape is the drift the delegation exists to prevent",
          L.KNOWN_POLICY is _policy.KNOWN_POLICY
          and L.KNOWN_POLICY_KIND is _policy.KNOWN_KIND
          and L.POLICY_KINDS is _policy.KINDS)

    # --- the root vocabulary is one vocabulary -----------------------------
    # cv1 is the case that would have caught the gap it was written for: `ui` was
    # read by `_ui_theme`, written by the panel, validated here and defaulted by
    # the hooks, and absent from the schema - where `additionalProperties: true`
    # meant no surface ever said so. It reads the real tree on purpose; the
    # fixture-driven cases below are what make its own failure modes testable,
    # which is the split `_help.vocab_drift()` is on.
    check("cv1 every published statement of the config's root vocabulary agrees "
          "with KNOWN_ROOT - the schema, the README's table and the hooks' "
          "DEFAULTS",
          L.config_vocab_drift() == [],
          "; ".join("%s: %s" % (s, p) for s, p in L.config_vocab_drift()))
    # cv2 states the disagreement between the two candidate authorities instead of
    # letting one of them win quietly. KNOWN_ROOT is the authority because it is
    # the only COMPLETE list: DEFAULTS is a proper subset by design, and the
    # difference is exactly what OFF_ROOT excuses with a reason. Put `policy` back
    # into DEFAULTS, or add a key to one list only, and this goes red.
    _hooks_root = set(_hcfg.DEFAULTS)
    check("cv2 KNOWN_ROOT is a proper superset of the hooks' DEFAULTS and the "
          "difference is exactly what OFF_ROOT excuses - so the narrower list is "
          "never quietly the authority",
          set(M.KNOWN_ROOT) - _hooks_root == set(L.OFF_ROOT["hooks DEFAULTS"])
          and not _hooks_root - set(M.KNOWN_ROOT),
          "extra in KNOWN_ROOT: %s | extra in DEFAULTS: %s"
          % (sorted(set(M.KNOWN_ROOT) - _hooks_root),
             sorted(_hooks_root - set(M.KNOWN_ROOT))))

    _known = {"alpha", "beta"}
    _clean = (("s", set(["alpha", "beta"]), None),)
    # cv3 looks vacuous and is the second-direction case: it is the only one that
    # fails if the comparison ever becomes unconditional. Keep it.
    check("cv3 a surface publishing exactly the vocabulary is silent",
          L.root_vocab_drift(_clean, _known, {}) == [])
    check("cv4 a key the validator accepts and a surface does not publish is "
          "named - the direction nothing held before",
          [p for _s, p in L.root_vocab_drift((("s", set(["alpha"]), None),),
                                             _known, {})
           if "'beta'" in p and "does not publish" in p])
    check("cv5 a key a surface publishes and the validator does not accept is "
          "named - a typo in a published list is otherwise invisible",
          [p for _s, p in L.root_vocab_drift(
              (("s", set(["alpha", "beta", "gama"]), None),), _known, {})
           if "'gama'" in p and "publishes" in p])
    check("cv6 a surface that publishes NOTHING is reported as empty rather than "
          "as agreement - a reader that quietly stopped matching would otherwise "
          "clear the whole vocabulary in one pass",
          [p for _s, p in L.root_vocab_drift((("s", set(), None),), _known, {})
           if "no root key at all" in p])
    check("cv7 a surface that could not be read reports its problem and is "
          "compared against nothing",
          L.root_vocab_drift((("s", None, "cannot be read: boom"),), _known, {})
          == [("s", "cannot be read: boom")])

    _off = {"s": {"beta": "a reason"}}
    check("cv8 OFF_ROOT excuses a key a surface leaves out on purpose",
          L.root_vocab_drift((("s", set(["alpha"]), None),), _known, _off) == [])
    check("cv9 ...and that exemption goes stale LOUDLY the moment the surface "
          "publishes the key - an exemption outliving its reason hides the next gap",
          [p for _s, p in L.root_vocab_drift(
              (("s", set(["alpha", "beta"]), None),), _known, _off)
           if "drop the exemption" in p])
    check("cv10 an exemption for a key the validator does not accept excuses "
          "nothing, and is named rather than believed",
          [p for _s, p in L.root_vocab_drift(
              (("s", set(["alpha", "beta"]), None),), _known,
              {"s": {"zeta": "why"}}) if "'zeta'" in p])
    check("cv11 an exemption with a blank reason is named",
          [p for _s, p in L.root_vocab_drift(
              (("s", set(["alpha"]), None),), _known, {"s": {"beta": "   "}})
           if "no reason" in p])
    check("cv12 OFF_ROOT naming a surface nothing reads is named - it would "
          "otherwise excuse a key on a surface that is no longer compared at all",
          [p for _s, p in L.root_vocab_drift(_clean, _known,
                                             {"gone": {"beta": "r"}})
           if "nothing reads" in p])

    # The README reader, on a fixture rather than on the shipped table: a case
    # that can only be run against the real README is a case whose own failure
    # modes are untested. The fixture carries both compound shapes the real table
    # has, and the values are chosen so the rule and its absence DISAGREE - drop
    # the leaf rule and `two` appears as a root; drop the root-segment rule and
    # `beta.one` does.
    _tbl = ("## Configuration (`.claude/audit.config.json`)\n"
            "\n"
            "| Key | Purpose | Default |\n"
            "|---|---|---|\n"
            "| `alpha` | one | `x` |\n"
            "| `beta.one` / `two` | a leaf spelled short | `y` |\n"
            "| `gamma` / `delta` | two roots in one cell | `z` |\n"
            "\n"
            "prose after the table\n")
    check("cv13 the README reader takes the ROOT of every key path in the first "
          "column, and reads a bare token after a NESTED one as a leaf rather "
          "than as another root",
          L.readme_root_keys(_tbl)
          == (set(["alpha", "beta", "gamma", "delta"]), None))
    check("cv14 a missing Configuration heading is a PROBLEM, never an empty "
          "vocabulary - returning the clean answer for an unreadable table is "
          "how a formatting change turns this gate into decoration",
          L.readme_root_keys("no heading here")[0] is None
          and "cannot be located" in L.readme_root_keys("no heading here")[1])
    check("cv15 a DOUBLED heading is a problem too - silently taking the first "
          "would read whichever table happened to come first",
          L.readme_root_keys(_tbl + _tbl)[0] is None)
    check("cv16 a header row that stopped opening with `Key` is a problem: the "
          "table's shape changed under the reader",
          L.readme_root_keys(_tbl.replace("| Key |", "| Setting |"))[0] is None)
    check("cv17 a header with no separator row under it is a problem",
          L.readme_root_keys(_tbl.replace("|---|---|---|\n", ""))[0] is None)
    check("cv18 a row whose first column names no key is a problem, never a "
          "silently skipped row",
          L.readme_root_keys(_tbl.replace("| `alpha` |", "| alpha |"))[0] is None)
    check("cv19 an escaped pipe inside a Key cell does not truncate it - the "
          "mistake command_flag_drift() had to make on this very file first, "
          "where a lazy match reported six commands as missing a flag that was "
          "written two characters further along",
          L.readme_root_keys(
              _tbl.replace("| `alpha` |", "| `alpha` \\| `zeta` |"))[0]
          == set(["alpha", "zeta", "beta", "gamma", "delta"]))

    # The two exit-code cases used to sit here. They are about
    # `validate-config.py`'s `main()`, not about a rule, and they went to
    # `test_validate_config.py` when the rules moved out from under it.


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__config_rules_lints.py --selftest\n")
    raise SystemExit(2)
