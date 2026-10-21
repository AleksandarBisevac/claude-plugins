#!/usr/bin/env python3
"""
The cases for `_help_lints.py` - the drift checks between the help schema and the
vocabularies, argparse choices and fields it describes, which were the second half of
`_help.py` before the lints left the plugin.

`L` is the module under test and `M` is `_help`. The cases for what stayed are in
`tests/test__help.py`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402  (as _help imports it)
import _help as M                                  # noqa: E402
import _help_lints as L                          # noqa: E402


# --- the payload under another platform's conventions --------------------------
# `GET /api/help` is fetched once per drawer session and parsed whole, and the
# tables behind its per-path form are built from the same sources, so the size of
# all of it is a serving cost that has a ceiling. The ceiling stays fixed; HEADROOM is the
# margin that has to stay free under it at all times. It is larger than the whole
# config table, so no single schema addition can be the byte that crosses the
# line: crossing it has to be a decision to spend the margin, made in this file,
# not a paragraph that happened to land last.
PAYLOAD_CAP = 200000
PAYLOAD_HEADROOM = 40000


def _payload_bytes(root=None):
    """Every byte `/api/help` can serve: the payload and the per-path tables that
    `entry_for` answers from. The tables left the payload, but the field text is the
    part a CRLF checkout or a backslash separator changes, so measuring the payload
    alone would stop watching the one thing the cap and the platform cases exist for."""
    return len(json.dumps([M.payload(root), M.tables(root)]))


def _crlf_root():
    """A plugin root whose schemas and agent files end every line in CRLF - the
    sources `payload()` reads, as a checkout that ignored `.gitattributes` would
    write them."""
    import shutil
    root = _harness.fixture_root("help-crlf-")
    src = M.plugin_root()
    for sub in ("schema", "agents"):
        shutil.copytree(os.path.join(src, sub), os.path.join(root, sub))
        for dirpath, _dirs, names in os.walk(os.path.join(root, sub)):
            for name in names:
                path = os.path.join(dirpath, name)
                with open(path, "rb") as fh:
                    data = fh.read().replace(b"\r\n", b"\n")
                with open(path, "wb") as fh:
                    fh.write(data.replace(b"\n", b"\r\n"))
    return root


def _backslash_payload_bytes():
    """The payload as built where `os.sep` is a backslash and `os.path.join`
    is Windows' own. Only the module under test sees the swap - its `os` and its
    `open` are replaced for the call and put back - and every real file access is
    handed a forward-slash path, which both platforms open, so the fixture
    changes how a path is SPELLED and never which file is read."""
    import ntpath
    import types
    real_os = M.os

    def fwd(path):
        return path.replace("\\", "/") if isinstance(path, str) else path

    shim_path = types.ModuleType("shim_path")
    shim_path.__dict__.update(real_os.path.__dict__)
    shim_path.join = ntpath.join
    shim_path.sep = "\\"
    for name in ("isfile", "isdir", "exists", "lexists"):
        shim_path.__dict__[name] = (lambda f: lambda p: f(fwd(p)))(
            getattr(real_os.path, name))
    shim_os = types.ModuleType("shim_os")
    shim_os.__dict__.update(real_os.__dict__)
    shim_os.path = shim_path
    shim_os.sep = "\\"
    shim_os.listdir = lambda p=".": real_os.listdir(fwd(p))
    M.os = shim_os
    M.open = lambda p, *a, **k: open(fwd(p), *a, **k)
    try:
        return _payload_bytes()
    finally:
        M.os = real_os
        del M.open


def _backslash_paths(node):
    """Every served string that spells a file path with a backslash between two
    path words. Walks the payload object itself, so the backslash is one
    character, not the doubled form `json.dumps` writes."""
    pat = re.compile(r"[\w.-]+\\[\w.-]+\.(?:json|md|py)\b")
    if isinstance(node, str):
        return [node] if pat.search(node) else []
    if isinstance(node, dict):
        return [h for v in node.values() for h in _backslash_paths(v)]
    if isinstance(node, (list, tuple)):
        return [h for v in node for h in _backslash_paths(v)]
    return []


def _run_with_nt_join(fn):
    """Run `fn()` while `os.path.join` spells every relative join Windows-style.
    The Windows join is bound BEFORE the swap: where `os.path` is `ntpath`,
    `ntpath.join` is the very attribute being replaced, so a lambda that looked it
    up at call time would call itself."""
    import ntpath
    _nt_join = ntpath.join
    _real_join = os.path.join
    os.path.join = lambda first, *rest: (
        _real_join(first, *rest) if os.path.isabs(first)
        else _nt_join(first, *rest))
    try:
        return fn()
    finally:
        os.path.join = _real_join


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- extraction ---------------------------------------------------------------
    cfg = L.config_fields()
    man = L.manifest_fields()
    check("s1 the config schema yields dotted paths with their own words",
          cfg["usage.pricingAsOf"]["description"].startswith("Date the pricing")
          or "pricing" in cfg["usage.pricingAsOf"]["description"],
          repr(cfg.get("usage.pricingAsOf")))

    # --- the manifest vocabulary against the schema -------------------------------
    # `_manifest_vocab`'s KNOWN_* sets restate vocabulary this schema owns, and the
    # comparison lives here because the walk does: the vocabulary is at layer 1 and
    # `fields()` is at layer 2, so it could not reach up for it. The cases that
    # assert the SHIPPED sets agree are in `test__manifest_vocab.py`, beside the
    # thing a reader is editing; these prove the comparison itself can fail, which
    # a green-only lint never does.
    check("v1 an anchor yields the properties ONE level under it - `types` and "
          "not `types.bug`, which belongs to a different question",
          L._direct_children(man, "meta.ado") >= {"organization", "types",
                                                  "stateMap"}
          and "types.bug" not in L._direct_children(man, "meta.ado")
          and "bug" not in L._direct_children(man, "meta.ado"),
          repr(sorted(L._direct_children(man, "meta.ado"))))
    check("v2 ...the document root is the empty anchor, and `<name>` is a SHAPE "
          "rather than a key anybody writes, so it is dropped",
          L._direct_children(man, "") == {"$schema", "meta", "phases", "bugs",
                                          "decisions", "deferred", "fileIndex",
                                          "proposals"}
          and "<name>" not in L._direct_children(man, "fileIndex"),
          repr(sorted(L._direct_children(man, ""))))
    # Nine fixtures, one per thing the lint can say. Fixtures rather than the real
    # module: mutating the shipped vocabulary to prove a lint would leave the tree
    # one exception away from shipping the mutation.
    _anch = (("KNOWN_X", "meta"),)

    def _probe(levels, sets, off):
        """Just the problems, against one anchor — the set name is `KNOWN_X` in
        every fixture, so carrying it into each expected list is noise."""
        return [p for _, p in L.vocab_drift(levels, sets, _anch, off)]

    check("v3 a property the schema declares and the set does not is named, with "
          "its anchor - the failure that prompted this whole check",
          _probe({"KNOWN_X": {"a", "b"}}, {"KNOWN_X": {"a"}}, {}) ==
          ["meta.b is in the schema and not in the set - add it, or the "
           "typo-catcher warns about a real key"])
    check("v11 ...and an agreeing table says nothing at all - the case that fails "
          "if any of v3-v10 is firing on everything",
          L.vocab_drift({"KNOWN_X": {"a"}}, {"KNOWN_X": {"a"}}, _anch, {}) == [])
    check("v12 `vocab_sets()` reads the sets OFF the module rather than listing "
          "them, so v9 has something to catch",
          L.vocab_sets(_vocab) == dict((n, getattr(_vocab, n)) for n in
                                       ("KNOWN_ROOT", "KNOWN_META", "KNOWN_ADO",
                                        "KNOWN_BRANCH", "KNOWN_MERGE",
                                        "KNOWN_PHASE", "KNOWN_TASK", "KNOWN_BUG",
                                        "KNOWN_DECISION", "KNOWN_PROPOSAL")),
          repr(sorted(L.vocab_sets(_vocab))))
    guide = M.guide_card()
    check("g3 the guide is mechanically read-only - an answering agent with an "
          "edit tool would be a writer with no plan, no lock and no journal row",
          L.guide_is_read_only() and (guide or {}).get("readOnly") is True)

    # --- (ch) a documented flag's VALUES against the parser that takes them -----
    # `/audit:status --view pending` was advertised by the command doc and
    # refused by the parser, and the whole gate set was green: `command_flag_drift`
    # compares flag NAMES between two documents and asks no parser anything. These
    # cases are the instrument, and they are pure so the failure modes can be
    # driven without a repository.
    check("ch1 the hint is read for VALUE LISTS, not for flags: `--view a|b|c` "
          "yields its three, and a flag with a free-form metavar yields nothing "
          "because there is nothing to compare",
          L.advertised_choices(
              "'[--gate] [--phase <id>] [--view active|archived|all] "
              "[--color auto|always|never]'")
          == {"--view": ["active", "archived", "all"],
              "--color": ["auto", "always", "never"]})
    check("ch2 THE DEFECT THAT SHIPPED: a value the doc advertises and the "
          "parser refuses is a finding that names both sides",
          [p for _s, p in L.choice_drift(
              "status.md", {"--view": ["active", "pending", "archived", "all"]},
              {"--view": set(("active", "archived", "all"))}, {})]
          == ["--view: the doc advertises 'pending', which the parser refuses "
              "(it takes active, all, archived)"])
    check("ch3 ...and the SAME FAULT FACING THE OTHER WAY is reported too - a "
          "value the parser takes that the doc never mentions is a capability "
          "nobody can find, which is this repo's oldest defect",
          [p for _s, p in L.choice_drift(
              "status.md", {"--view": ["active", "all"]},
              {"--view": set(("active", "archived", "all"))}, {})]
          == ["--view: the parser accepts 'archived', which the doc never "
              "advertises"])
    check("ch4 agreement is silence - a rule that fired on a correct pair would "
          "be routed around by the first person who read it",
          L.choice_drift("status.md", {"--view": ["active", "archived", "all"]},
                         {"--view": set(("active", "archived", "all"))}, {}) == [])
    check("ch5 A FLAG NO PARSER OWNS IS A FINDING, NOT A SKIP: a doc could "
          "otherwise opt out of this check by advertising a flag nothing "
          "implements, and silence would read exactly like agreement",
          [p for _s, p in L.choice_drift(
              "status.md", {"--view": ["active"]}, {},
              {"audit-status.py": "exposes no build_parser()"})]
          == ["--view: no parser named by this command declares it "
              "(audit-status.py: exposes no build_parser())"])
    check("ch6 ...but an unreadable script is CONTEXT, not a finding of its own: "
          "with the flag matched, a doc that merely PRINTS another tool's command "
          "in its prose is silent. This was got wrong first and convicted "
          "`doctor.md` for showing a `run-test-gate.py` invocation - a guard that "
          "fires on a correct document is one somebody routes around",
          L.choice_drift("status.md", {"--view": ["active"]},
                         {"--view": set(("active",))},
                         {"helper.py": "exposes no build_parser()"}) == [])
    # THE LIVE ONE. Everything above is a fixture; this is the tree, and it is
    # what makes the rule shippable rather than an argument written on the day it
    # landed.
    _ch_live = L.command_choice_drift()
    check("ch7 ...and the real command surface agrees with its own parsers "
          "right now, in both directions: %r" % (_ch_live,),
          _ch_live == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__help_lints.py --selftest\n")
    raise SystemExit(2)
