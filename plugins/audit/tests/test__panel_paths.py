#!/usr/bin/env python3
"""
The cases for `_panel_paths.py` - where a project's files are, and the three
modules the panel reads them through.

Written at U3.1, when this module was cut out of `_panel_state.py`. `M` is the
module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

WHAT THESE CASES ARE ACTUALLY GUARDING. This module exists because `_cores()` was
a positional 4-tuple bundling `_manifest_rules` (layer 3) with three modules that
have nothing to do with it, and a shared base holding that tuple could only sit at
layer 4 - leaving no layer for the five modules that read it. The cases below pin
the two halves of the repair: the accessors hand back the RIGHT modules, and
`_panel_state._cores()` still assembles the same tuple in the same order for
`_panel_write` and `audit-task`, which read it positionally.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as the module imports it)
import _config_rules                               # noqa: E402  (what config_rules() must be)
import _deps                                       # noqa: E402  (the import graph, read from the AST)
import _manifest_rules                             # noqa: E402  (what _cores()[0] must be)
import _status_facts                               # noqa: E402  (what status_facts() must be)
import _panel_paths as M                           # noqa: E402
import _panel_state as _state                      # noqa: E402  (the tuple's one assembler)


# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="panel-paths-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)

    # --- the three accessors, by identity ---------------------------------------
    # `is`, not a name or a duck-type: the whole point of the split is that these
    # hand back the SAME module objects the old tuple carried, so a caller that
    # moved from `_cores()[1]` to `config_rules()` cannot have quietly changed
    # which rules it validates against.
    check("pp1 config_rules() IS `_config_rules`, the module the old tuple's "
          "index 1 carried", M.config_rules() is _config_rules)
    check("pp2 status_facts() IS `_status_facts`, the old index 2",
          M.status_facts() is _status_facts)
    check("pp3 hooks_config() reaches hooks/_config - the one accessor here that "
          "LOADS anything, and the reason this module keeps a memo at all",
          hasattr(M.hooks_config(), "DEFAULTS")
          and hasattr(M.hooks_config(), "usage_cfg"))
    # The memo, by identity rather than by timing: two loads would be two module
    # objects, and a case that patched one would be testing a config the other
    # side never sees - the split state the old `_cores()` docstring warned about.
    check("pp4 hooks_config() memoizes - the second call is the SAME object, so "
          "a case that patches it patches what every reader sees",
          M.hooks_config() is M.hooks_config())

    # --- and the tuple `_panel_write`/`audit-task` still read positionally ------
    # Both of those spell `_cores()[0]`, and two suites spell `[1]`. The order is
    # the contract, so it is pinned here by identity and by length rather than
    # left to whoever next edits the assembler.
    _t = _state._cores()
    check("pp5 `_panel_state._cores()` is still a 4-tuple in the original order - "
          "`_panel_write` and `audit-task` read index 0 out of it and two suites "
          "read index 1, so the shape is a contract, not an implementation detail",
          len(_t) == 4 and _t[0] is _manifest_rules
          and _t[1] is _config_rules and _t[2] is _status_facts
          and _t[3] is M.hooks_config())
    # THE SECOND DIRECTION, and the one that decides whether the split was worth
    # anything: `_manifest_rules` must NOT be reachable from here. If it were, this
    # module would be at layer 4 and the five modules that read it would have
    # nowhere to sit - which is the eighth layer this cut exists to not add.
    # Asked of `_deps`, which reads the AST, rather than of the source text. The
    # first version of this case searched the file for `import _manifest_rules`
    # and went red on its own DOCSTRING, which names the module four times while
    # explaining why it is absent - the same trap the viewer's `--name-only` slice
    # sprang the same afternoon. A prose mention is not an edge, and only the
    # module that owns the import graph can tell the two apart.
    _edges, _broken = _deps.import_graph()
    check("pp6 ...and nothing here REACHES `_manifest_rules` - it is the one piece "
          "that could not come down, and a later edit that 'helpfully' imports it "
          "puts the whole split back on layer 4: %r"
          % ([d for s, d in _edges if s == "_panel_paths"],),
          not _broken
          and ("_panel_paths", "_manifest_rules") not in _edges
          and not hasattr(M, "_manifest_rules"))
    # The other end of the same claim, so this pair cannot both pass while the
    # edge simply moved: `_panel_state` DOES reach it, which is what makes
    # `_cores()[0]` legal there and illegal here.
    check("pp6b ...while `_panel_state` at layer 5 does reach it, which is what "
          "makes the same tuple legal one layer up",
          ("_panel_state", "_manifest_rules") in _edges)

    # --- path safety -------------------------------------------------------------
    check("pp7 _within accepts the project itself and a path inside it, and "
          "refuses a parent and a sibling",
          M._within(proj, proj) is True
          and M._within(proj, os.path.join(proj, "a", "b")) is True
          and M._within(proj, tmp) is False
          and M._within(proj, os.path.join(tmp, "other")) is False)
    check("pp8 _config_path is the project's own .claude/audit.config.json",
          M._config_path(proj) == os.path.join(proj, M.CONFIG_REL.replace("/", os.sep))
          or M._config_path(proj) == os.path.join(proj, M.CONFIG_REL))
    check("pp9 _manifest_path normalizes, so an escaping manifestPath resolves to "
          "a path `_within` can then refuse rather than to a literal with `..` in "
          "the middle that string checks would miss",
          ".." not in M._manifest_path(proj, {"manifestPath": "a/../../out.json"})
          and M._within(proj,
                        M._manifest_path(proj, {"manifestPath": "a/../../out.json"}))
          is False)
    check("pp10 _manifest_path falls back to the hooks config's own default rather "
          "than to a path spelled a second time here",
          M._manifest_path(proj, {})
          == os.path.normpath(os.path.join(proj, M._defaults()["manifestPath"])))

    # --- what the config declares, and what merely defaults ---------------------
    # `usage_cfg()` merges a default `pricingAsOf`, so the merged value is almost
    # never absent; rendering it as the rate basis would present a date the project
    # never chose as though it had. Only the RAW config can tell the two apart.
    check("pp11 _declared_as_of separates a project's own value from the default",
          M._declared_as_of({"usage": {"pricingAsOf": "2026-01-02"}}) is True
          and M._declared_as_of({"usage": {"showCost": True}}) is False
          and M._declared_as_of({}) is False
          and M._declared_as_of({"usage": {"pricingAsOf": "   "}}) is False
          and M._declared_as_of({"usage": {"pricingAsOf": 20260102}}) is False)

    # --- reading the config ------------------------------------------------------
    check("pp12 read_config on a project with no config file is {} rather than a "
          "raise - a fresh install is a state the panel renders",
          M.read_config(proj) == {})
    _mio.atomic_write_json(M._config_path(proj), {"planGate": "warn"},
                           ensure_ascii=False, indent=2)
    check("pp13 ...and it reads one that is there", M.read_config(proj)
          == {"planGate": "warn"})
    with open(M._config_path(proj), "w", encoding="utf-8") as fh:
        fh.write("[1, 2, 3]")
    check("pp14 a config that parses but is not an OBJECT reads as {} - `[1,2,3]"
          "`.get would raise on the first knob any caller asked for",
          M.read_config(proj) == {})
    with open(M._config_path(proj), "w", encoding="utf-8") as fh:
        fh.write("{ not json")
    check("pp15 ...and one that does not parse at all reads as {} too",
          M.read_config(proj) == {})
    check("pp16 _read_json delegates to the plugin's ONE json reader rather than "
          "opening the file itself",
          "_mio.read_json(path)" in _harness.module_source(M))

    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_paths.py --selftest\n")
    raise SystemExit(2)
