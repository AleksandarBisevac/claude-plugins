#!/usr/bin/env python3
"""
The drift checks over the config vocabulary - development code, kept out of the
shipped plugin.

`_config_rules` is what `validate_config` and every reader of a config key ask: the
enumerations and the validators. The checks that compare those enumerations against
the three places that restate them (the schema's root keys, the defaults file, the
README's key table) judge the repository, not a user's configuration, so they leave
with the other development modules to `tools/lints/`, under a basename that collides
with nothing in `scripts/`.

`install_path()` never puts this directory on `sys.path`, so a development caller
(the harness, a tool) adds it itself.

This module carries no `--selftest`; its cases live in `tests/test__config_rules_lints.py`.
"""
import json
import os
import re
import sys
import _output
import _policy
import _loader

# The path bootstrap for a development module that lives OUTSIDE the plugin: it
# walks UP to the directory that holds `plugins/audit/scripts/_output.py` instead
# of counting `dirname()` calls, so it does not encode how deep this file sits.
# `install_path()` then adds `scripts/` and every subdirectory of it holding a
# `.py`, so every sibling below is reached by a bare basename.
_anchor_root = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_root, "plugins", "audit", "scripts",
                                      "_output.py")):
    _anchor_up = os.path.dirname(_anchor_root)
    if _anchor_up == _anchor_root:
        raise ImportError("audit lints: walked to the filesystem root from %s "
                          "without finding plugins/audit/scripts/_output.py - the "
                          "repository root is gone and no sibling can be imported"
                          % (__file__,))
    _anchor_root = _anchor_up
_anchor_dir = os.path.join(_anchor_root, "plugins", "audit", "scripts")
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)


_output.install_path()

from _config_rules import (  # noqa: E402
    KNOWN_ROOT)



# Not a fourth statement of the policy block's shape: `_policy` owns it, and every
# surface that needs the key set (this validator, the panel's Settings coverage
# check) reads THIS name, which is that module's.
KNOWN_POLICY = _policy.KNOWN_POLICY
KNOWN_POLICY_KIND = _policy.KNOWN_KIND
POLICY_KINDS = _policy.KINDS
ON_VIOLATION = _policy.ON_VIOLATION


# --- is the root vocabulary one vocabulary? -------------------------------------
# KNOWN_ROOT IS THE AUTHORITY FOR BOTH DIRECTIONS AND `DEFAULTS` IS NOT. Settling
# that came first, because the two do not agree: `policy` is in KNOWN_ROOT and
# deliberately absent from hooks/_config.py DEFAULTS (that module's `--- policy ---`
# note says why - `_policy.py` owns the block, and copying it back would put the
# scripts-side module on the hot path of every tool call). DEFAULTS is therefore a
# proper subset by design, and picking it as the authority would under-report by
# exactly the block with the most consequence.
#
# WHY HERE, WHEN `_help.schema_vocab_drift()` ALREADY DOES THIS FOR THE MANIFEST.
# That comparison had to leave `_manifest_vocab` because the vocabulary sits a
# layer below the tree's only `$ref`-resolving schema walk, so the alternative was
# a second walk. Neither half applies here: this module IS the config vocabulary,
# `_help` is its PEER in the same layer (so neither may import the other), and the
# config's root level is `schema["properties"]` - a dict access, not a walk.
# Mirroring the manifest's shape would mean moving this vocabulary down into a
# lower module - renaming what the panel's Settings form, the doctor and several
# suites read - to save that dict access.
_SCHEMA_REL = os.path.join("schema", "audit-config.schema.json")
_README_REL = "README.md"
# The table this reads, located by its own heading rather than by position.
README_TABLE_HEADING = "## Configuration (`.claude/audit.config.json`)"
# The first column, up to an UNESCAPED pipe - the discipline `command_flag_drift()`
# had to learn on this same file, where a lazy match to the first `|` truncated
# half the cells and reported keys that were written two characters further along.
_CFG_CELL = re.compile(r"^\|((?:\\\||[^|])*)\|")
_CFG_KEY = re.compile(r"`([A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9{},]+)*)`")
_CFG_SEP = re.compile(r"^[\s:|-]+$")

# Keys a surface may leave unpublished, with the reason it may. Read BOTH ways by
# `root_vocab_drift`: an exemption for a key the validator does not accept, or for
# one the surface has since published, is itself a finding. An exemption list with
# no live reasons is where a lint goes to die.
OFF_ROOT = {
    "hooks DEFAULTS": {
        "policy": "_policy.py owns the block's shape and its defaults; "
                  "hooks/_config.py stopped copying them so that consulting a "
                  "policy would not import the scripts-side module on every "
                  "tool call",
        "ci": "no hook reads it: only the step driver does, through "
              "ci_cadence_setting and carry_push_setting, which treat an absent "
              "key as landing only and as no push - so there is no shipped "
              "value for DEFAULTS to carry",
    },
}


def _cell_roots(cell):
    """The ROOT keys one Key cell of the Configuration table names.

    The table's compound cells are why this is a stated rule rather than a split on
    whitespace: a cell may name several roots (`stateDir` beside `logsDir`), and a
    cell whose first key is nested may name further LEAVES of that same key
    (`usage.currency` beside `pricingAsOf`). So a bare token following a nested one
    is a leaf, and one following a bare token is another root.
    """
    tokens = _CFG_KEY.findall(cell)
    if not tokens:
        return []
    nested_head = "." in tokens[0]
    roots = [tokens[0].split(".")[0]]
    for tok in tokens[1:]:
        if nested_head and "." not in tok:
            continue
        roots.append(tok.split(".")[0])
    return roots


def readme_root_keys(text):
    """(keys, problem) - the root keys the README's Configuration table documents.

    A MARKDOWN TABLE IS PROSE, so this reads the least of it that answers the
    question: the root segment of every backticked key path in the first column.
    Leaves are deliberately not compared - the map from a top-level key to the keys
    inside it is hand-kept wherever it exists at all (the panel's Settings form
    keeps one, and its own case says so), and a lint comparing against a hand-kept
    map agrees with a second copy rather than with the code.

    IT FAILS LOUDLY OR NOT AT ALL. A heading that is missing or doubled, a header
    row whose first column stopped saying `Key`, a missing separator, or a row that
    names no key each come back as a PROBLEM - because "I could not read this
    table" and "this table is complete" are different answers, and returning the
    empty finding list for both is how a formatting change turns a gate into
    decoration.
    """
    seen = text.count(README_TABLE_HEADING)
    if seen != 1:
        return None, ("carries the Configuration heading %d time(s), so the table "
                      "cannot be located" % (seen,))
    tail = text[text.find(README_TABLE_HEADING):].splitlines()[1:]
    rows, started = [], False
    for line in tail:
        if line.startswith("|"):
            rows.append(line)
            started = True
        elif started:
            break
    if len(rows) < 3:
        return None, ("the Configuration heading is followed by %d table row(s), "
                      "so the key table is not there to read" % (len(rows),))
    head = _CFG_CELL.match(rows[0])
    if head is None or head.group(1).strip() != "Key":
        return None, ("the Configuration table's header row does not open with a "
                      "`Key` column, so its shape has changed under this")
    if not _CFG_SEP.match(rows[1]):
        return None, ("the Configuration table's header is not followed by a "
                      "separator row, so its shape has changed under this")
    keys = set()
    for row in rows[2:]:
        cell = _CFG_CELL.match(row)
        if cell is None:
            return None, ("a Configuration table row has no first column: %r"
                          % (row[:60],))
        roots = _cell_roots(cell.group(1))
        if not roots:
            return None, ("a Configuration table row names no key in its first "
                          "column: %r" % (cell.group(1).strip(),))
        keys |= set(roots)
    return keys, None


def root_vocab_drift(surfaces, known, off_root):
    """[(surface, problem), ...] - every surface that has stopped agreeing with
    `known` about the config's root keys.

    Separate from `config_vocab_drift()` because that one reads every surface off a
    file on disk, and a lint you can only run against the real tree is a lint whose
    own failure modes are untested - the split `_help.vocab_drift()` is on, for the
    same reason. Every case that proves this goes red hands it a fixture here
    instead of mutating the shipped vocabulary.

    `surfaces` is `((name, keys or None, problem or None), ...)`, `known` the
    authority, and `off_root` the `{surface: {key: reason}}` table.
    """
    out = []
    named = set(name for name, _keys, _problem in surfaces)
    for name in sorted(set(off_root) - named):
        out.append((name, "OFF_ROOT excuses keys for a surface nothing reads"))
    for name, keys, problem in surfaces:
        if problem is not None:
            out.append((name, problem))
            continue
        published = set(keys or ())
        if not published:
            out.append((name, "publishes no root key at all - a comparison against "
                              "nothing passes for any vocabulary"))
            continue
        exempt = off_root.get(name) or {}
        for key in sorted(set(known) - published - set(exempt)):
            out.append((name, "does not publish %r, which the validator accepts - "
                              "publish it, or add it to OFF_ROOT with the reason "
                              "this surface leaves it out" % (key,)))
        for key in sorted(published - set(known)):
            out.append((name, "publishes %r, which the validator does not accept - "
                              "a config that sets it is warned about by the "
                              "plugin's own validator" % (key,)))
        for key in sorted(exempt):
            if key in published:
                out.append((name, "OFF_ROOT excuses %r, but this surface now "
                                  "publishes it - drop the exemption" % (key,)))
            elif key not in known:
                out.append((name, "OFF_ROOT excuses %r, which the validator does "
                                  "not accept - an exemption for a key nothing "
                                  "reads excuses nothing and hides the next one"
                            % (key,)))
            if not str(exempt[key]).strip():
                out.append((name, "OFF_ROOT excuses %r with no reason" % (key,)))
    return out


def _read_schema_roots(root):
    """(keys, problem) - the root property names the config schema publishes."""
    try:
        with open(os.path.join(root, _SCHEMA_REL), "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, "cannot be read: %s" % (exc,)
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        return None, "declares no root `properties` object to compare against"
    return set(schema["properties"]), None


def _read_readme_roots(root):
    """(keys, problem) - the root keys the plugin README's config table documents."""
    try:
        with open(os.path.join(root, _README_REL), "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return None, "cannot be read: %s" % (exc,)
    return readme_root_keys(text)


def _read_defaults_roots():
    """(keys, problem) - the root keys the hooks ship a default for.

    Through `_loader.load_hooks_config()` rather than by parsing the file: DEFAULTS
    is a dict literal of nested dicts, and a text scan of it would be a second and
    worse reader of something the loader already hands back. That call names no
    sibling and is why `_deps` leaves it out of the layer graph.

    Broad on purpose: a hooks module that cannot be loaded at all is exactly the
    case that must be SAID rather than passed over, and the value returned is a
    problem, not an empty key set that would read as agreement.
    """
    try:
        mod = _loader.load_hooks_config(modname="audit_config_vocab_defaults")
    except Exception as exc:                                    # noqa: BLE001
        return None, "cannot be loaded: %s" % (exc,)
    if not isinstance(getattr(mod, "DEFAULTS", None), dict):
        return None, "has no DEFAULTS dict to compare against"
    return set(mod.DEFAULTS), None


def config_vocab_drift(plugin_root=None):
    """[(surface, problem), ...] - every published statement of the config's root
    vocabulary that has stopped agreeing with `KNOWN_ROOT`.

    THE DIRECTION NOTHING HELD. The panel's Settings coverage case derives the
    form's controls FROM this validator, so "documented, therefore reachable" was
    already checked; "runs, therefore published" was not. `ui` spent its whole life
    read by `_ui_theme`, written by the panel, validated here, defaulted by the
    hooks - and absent from the schema, where `additionalProperties: true` meant no
    surface ever said so. The README table is the same rule one surface
    further: `priority.maxTier` had a panel control and no published row, so
    the only description of the lever was the row for the command that writes it.

    ROOT KEYS ONLY, which is the level at which three statements written for three
    different readers are comparable without inventing a fourth, hand-kept map
    between them.
    """
    root = plugin_root if plugin_root is not None else _output.PLUGIN_ROOT
    schema_keys, schema_bad = _read_schema_roots(root)
    readme_keys, readme_bad = _read_readme_roots(root)
    hooks_keys, hooks_bad = _read_defaults_roots()
    return root_vocab_drift((("schema", schema_keys, schema_bad),
                             ("README", readme_keys, readme_bad),
                             ("hooks DEFAULTS", hooks_keys, hooks_bad)),
                            KNOWN_ROOT, OFF_ROOT)
