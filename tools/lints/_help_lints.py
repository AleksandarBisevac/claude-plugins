#!/usr/bin/env python3
"""
The drift checks over the help schema - development code, kept out of the shipped
plugin.

`_help` is what `/audit:help` and the panel read: the schema walk, the field help and
the concept topics. The checks that compare it against everything it describes (the
vocabulary sets the parsers advertise, the choices an argparse command offers, the
config and manifest fields the schema names) judge the repository, not a user's
question, so they leave with the other development modules to `tools/lints/`, under
a basename that collides with nothing in `scripts/`.

`install_path()` never puts this directory on `sys.path`, so a development caller
(the harness, a tool) adds it itself.

This module carries no `--selftest`; its cases live in `tests/test__help_lints.py`.
"""
import os
import re
import sys
import _output
import _loader
import _manifest_vocab

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

from _help import (  # noqa: E402
    READ_ONLY_TOOLS, _walk_schema, guide_card, load_schema, plugin_root)





def fields(doc, max_depth=12):
    """`{dotted path: {description, type, enum, …}}` for one schema document.

    Arrays are spelled `customRules[].message` and open maps `pricing.<name>.in`,
    which is how the panel's own paths read and how a reader would say them aloud.
    """
    return _walk_schema(doc, max_depth)["fields"]


def config_fields(root=None):
    return fields(load_schema("config", root))


def manifest_fields(root=None):
    return fields(load_schema("manifest", root))


def guide_is_read_only(root=None):
    """True iff the guide holds exactly the read-only tools — a fact about its tool
    list, not a promise in its prompt. A guide that could write would be an agent
    with no plan, no lock and no journal row editing a repository."""
    card = guide_card(root)
    return bool(card) and sorted(card["tools"]) == sorted(READ_ONLY_TOOLS)


# --- lints -----------------------------------------------------------------------


def _direct_children(table, anchor):
    """The property names one level under `anchor` in a `fields()` table.

    `meta.ado` -> {organization, project, types, …} and NOT `types.bug`, which is
    one level further down and belongs to a different question. `""` is the
    document root, so `bugs` and `$schema` come back and `fileIndex.<name>` does
    not. `<name>` itself is dropped: it is `fields()`' spelling for an open map's
    values, a SHAPE rather than a key anybody writes.
    """
    prefix = (anchor + ".") if anchor else ""
    out = set()
    for path in table:
        if not path.startswith(prefix):
            continue
        rest = path[len(prefix):]
        if not rest or "." in rest or "[]" in rest or rest == "<name>":
            continue
        out.add(rest)
    return out


def schema_level_keys(root=None, anchors=None):
    """`{set name: set of properties the plan schema declares there}`.

    Split out of `schema_vocab_drift()` so the SIZE of the comparison is askable.
    A set-difference against an empty set reports no problems, which reads exactly
    like agreement — so `tests/test__manifest_vocab.py` holds a floor under this
    total (mv19), and `schema_vocab_drift()` reports an anchor that resolves to
    nothing as drift rather than letting it pass quietly.

    `anchors` defaults to `SCHEMA_ANCHORS`, the levels checked for coverage; a
    caller with another table of `(name, dotted path)` pairs may pass it in.
    """
    table = manifest_fields(root)
    pairs = _manifest_vocab.SCHEMA_ANCHORS if anchors is None else anchors
    return dict((name, _direct_children(table, anchor)) for name, anchor in pairs)


def vocab_sets(mod=None):
    """`{name: value}` for every `KNOWN_*` attribute on the vocabulary module.

    Read off the module rather than listed, so a set added later is compared
    whether or not anybody remembered this function existed — an enumeration here
    would make "forgot to register it" look identical to "agrees with the schema".
    """
    mod = _manifest_vocab if mod is None else mod
    return dict((n, getattr(mod, n)) for n in dir(mod) if n.startswith("KNOWN_"))


def vocab_drift(levels, sets, anchors, off_schema):
    """The comparison itself, on four plain arguments.

    Separate from `schema_vocab_drift()` because that one reads three of these off
    a module and the fourth off a file on disk, and a lint you can only run against
    the real tree is a lint whose own failure modes are untested. Every case that
    proves this goes RED hands it a fixture here instead of mutating the shipped
    vocabulary in place.

    `levels` is `{set name: the properties the schema declares at its anchor}`,
    `sets` is `{set name: the keys the vocabulary holds}`, `anchors` is the
    `(name, dotted path)` pairs and `off_schema` the `{name: {key: reason}}` table.
    """
    anchored = dict(anchors)
    out = []

    for name in sorted(set(sets) - set(anchored)):
        out.append((name, "no SCHEMA_ANCHORS entry: nothing says where in "
                          "audit-plan.schema.json this set is defined"))
    for name in sorted(set(off_schema) - set(anchored)):
        out.append((name, "OFF_SCHEMA excuses keys for a set SCHEMA_ANCHORS does "
                          "not anchor"))

    for name, anchor in anchors:
        where = anchor or "<root>"
        if name not in sets:
            out.append((name, "SCHEMA_ANCHORS anchors it at %r, but the vocabulary "
                              "has no such set" % (where,)))
            continue
        vocab = set(sets[name])
        schema = set(levels.get(name) or ())
        if not schema:
            out.append((name, "the anchor %r declares no properties in "
                              "audit-plan.schema.json - a comparison against "
                              "nothing passes for any set" % (where,)))
            continue
        exempt = off_schema.get(name) or {}
        for key in sorted(schema - vocab):
            out.append((name, "%s.%s is in the schema and not in the set - add it, "
                              "or the typo-catcher warns about a real key"
                        % (where, key)))
        for key in sorted(vocab - schema - set(exempt)):
            out.append((name, "%r is in the set and not in the schema - add it to "
                              "the schema, or to OFF_SCHEMA with the reason it is "
                              "accepted anyway" % (key,)))
        for key in sorted(exempt):
            if key in schema:
                out.append((name, "OFF_SCHEMA excuses %r, but the schema now "
                                  "declares it - drop the exemption" % (key,)))
            elif key not in vocab:
                out.append((name, "OFF_SCHEMA excuses %r, which the set no longer "
                                  "holds - drop the exemption" % (key,)))
            if not str(exempt[key]).strip():
                out.append((name, "OFF_SCHEMA excuses %r with no reason" % (key,)))
    return out


def schema_vocab_drift(root=None):
    """[(set-name, problem), …] — every `_manifest_vocab.KNOWN_*` set that has
    stopped agreeing with `schema/audit-plan.schema.json`.

    WHY THIS WALK AND NOT THE OTHER ONE. `fields()` is not the tree's only schema
    walk, and the difference is not cosmetic: `gen-demo-manifest.schema_fields()`
    asks whether a FIXTURE exercises the schema, so it keys a field
    `<owner>.<field>` with the owner a `$def` NAME — and an object the schema spells
    out INLINE has no name to attribute a sub-key to. `meta.ado` is inline, which
    puts `KNOWN_ADO`, the level this check exists for, outside that walk's reach by
    construction rather than by accident. `fields()` keys by DOCUMENT PATH
    (`meta.ado.conventions`), which is the shape a per-LEVEL known-key set needs.
    `mv34` and `mv35` in `tests/test__manifest_vocab.py` assert that
    and print the figures, because "reuse the other walk" is the obvious suggestion
    and acting on it drops a whole level in silence.

    AND WHY IT LIVES HERE AND NOT BESIDE THE SETS. The vocabulary sits a layer
    below `fields()`, which is in this module, and `gen-demo-manifest` is an entry
    point above it. Importing upward is what `_deps.layer_violations()` fails, and writing
    another walk down there would move the duplication rather than remove it.
    `_manifest_vocab` keeps the two claims it is the right owner of — `SCHEMA_ANCHORS`
    (where each set lives in the document) and `OFF_SCHEMA` (which keys are wider
    than the schema on purpose, with a reason each) — and this is the comparison.

    Everything it can say, and each is a way this has gone wrong or could:

      * the schema declares a property the set does not hold — the failure that
        prompted this, where a field is added in one file and the typo-catcher
        starts warning about a real key;
      * the set holds a key the schema does not and `OFF_SCHEMA` does not excuse
        it — a typo in the vocabulary itself is otherwise invisible;
      * an anchor resolves to NO properties, which is what a renamed or
        restructured `$def` looks like from here, and which would otherwise turn
        that whole level into a comparison against nothing;
      * a `KNOWN_*` attribute with no `SCHEMA_ANCHORS` entry, so a set added later
        cannot opt out of the check by being forgotten;
      * an `OFF_SCHEMA` entry that has gone stale — the schema has since grown the
        key, or the set no longer holds it — or one whose reason is blank. An
        exemption list without live reasons is where a lint goes to die.
    """
    return vocab_drift(schema_level_keys(root), vocab_sets(),
                       _manifest_vocab.SCHEMA_ANCHORS, _manifest_vocab.OFF_SCHEMA)


# --- a documented flag's VALUES, against the parser that takes them ---------------
# THE DEFECT THIS CATCHES SHIPPED INSIDE THE VERY CHANGE THAT ADDED THE FLAG:
# `commands/status.md` advertised `--view active|pending|archived|all` while the
# parser took three, so a value copied straight out of the documentation exited 2.
# Every gate was green and every one of them was honest — `_refs.command_flag_drift`
# compares flag NAMES between the command doc and the README, two documents, and
# asks no parser anything. The value list inside an `argument-hint` was unread text.
#
# WHY IT ASKS ARGPARSE AND NOT THE AST. Measured across the plugin: of the five
# value lists a command doc advertises, a static reader resolves ONE. The rest
# spell `choices=list(_cli_fmt.MODES)` or `choices=sorted(_vocab.VIEW_SEGS)` —
# calls, not literals — so a source-reading version would have to re-implement
# enough of Python to evaluate them, and a lint that computes the wrong answer is
# worse than no lint. Constructing the parser is the whole trick, and it is why
# `audit-doctor.py` grew a `build_parser()`: the option surface has to be reachable
# without starting a process.
#
# AND WHY IT LIVES HERE RATHER THAN BESIDE `command_flag_drift` IN `_refs`. That
# module is a layer-mate of `_loader` — the one thing that can load a script as
# a library — so `_refs` may not import it. `schema_vocab_drift` above is at this
# layer for exactly the same reason: the walk that can SEE the thing does, a layer
# up from the thing itself.
_HINT_CHOICES = re.compile(r"(--[a-z][a-z0-9-]*)\s+([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)+)")
_DOC_SCRIPT = re.compile(r"scripts/[A-Za-z0-9_/-]+\.py")


def advertised_choices(hint):
    """{flag: [value, ...]} — every VALUE LIST a command's `argument-hint` shows.

    Only the pipe-separated form, because that is the only one that makes a
    claim this check can grade. `--phase <id>` and `--fail-on <c1,c2,...>` name a
    metavar rather than a set, and a rule that read those would be inventing a
    promise the document never made.
    """
    return dict((m.group(1), m.group(2).split("|"))
                for m in _HINT_CHOICES.finditer(hint or ""))


def parser_choices(parser):
    """{flag: set(choices)} — what an argparse parser really accepts.

    Read off `_actions` rather than re-derived: argparse is the thing the command
    runs on, so it is the only answer that cannot be a second opinion. Actions
    with no `choices` contribute nothing — an unconstrained flag has no value set
    to disagree about.
    """
    out = {}
    for action in getattr(parser, "_actions", ()):
        if not getattr(action, "choices", None):
            continue
        for flag in (action.option_strings or ()):
            if flag.startswith("--"):
                out[flag] = set(str(c) for c in action.choices)
    return out


def choice_drift(cmd, advertised, accepted, unreadable):
    """[(cmd, problem), ...] — where a command doc and its parsers disagree.

    BOTH DIRECTIONS, and they are different defects. A value the doc advertises
    and the parser refuses is a promise the product breaks for anyone who copies
    it — the shape the section comment above describes. A value the parser
    takes and the doc omits is a
    capability nobody can find, which is the defect `command_flag_drift` already
    exists for, one level down from the flag to its values.

    `unreadable` is `{script: why}` for a script the command names whose options
    could not be read, and it is CONTEXT ON A REAL FINDING rather than a finding
    of its own. That distinction was got wrong first: reporting a census hole
    whenever one existed convicted `doctor.md` for printing a `run-test-gate.py`
    invocation in its prose — a pointer to another tool, not a parser this command
    runs on. A guard that fires on a correct document is a guard somebody routes
    around, and the live case is what caught it.

    Hiding a parser still cannot buy silence, because the risk only exists when a
    flag goes unmatched — and that is already the finding below, which names the
    unreadable scripts as the reason it could not answer.
    """
    out = []
    for flag in sorted(advertised):
        want = list(advertised[flag])
        got = accepted.get(flag)
        if got is None:
            why = ", ".join("%s: %s" % (s, unreadable[s])
                            for s in sorted(unreadable)) or "no parser declares it"
            out.append((cmd, "%s: no parser named by this command declares it "
                              "(%s)" % (flag, why)))
            continue
        for value in want:
            if value not in got:
                out.append((cmd, "%s: the doc advertises %r, which the parser "
                                 "refuses (it takes %s)"
                                 % (flag, value, ", ".join(sorted(got)))))
        for value in sorted(got):
            if value not in want:
                out.append((cmd, "%s: the parser accepts %r, which the doc never "
                                 "advertises" % (flag, value)))
    return out


def command_choice_drift(root=None):
    """[(command, problem), ...] — the whole command surface, both directions.

    A command with no `argument-hint`, or one whose hint shows no value list, is
    not a finding: there is nothing there that claims a set. Silence is an answer
    when the document made no claim, and only then.
    """
    base = plugin_root(root)
    cmd_dir = os.path.join(base, "commands")
    out = []
    for name in sorted(os.listdir(cmd_dir) if os.path.isdir(cmd_dir) else []):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(cmd_dir, name), "r", encoding="utf-8") as fh:
                body = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            out.append((name, "unreadable: %s" % (exc,)))
            continue
        hint = re.search(r"^argument-hint:\s*(.+)$", body[:4096], re.MULTILINE)
        advertised = advertised_choices(hint.group(1) if hint else "")
        if not advertised:
            continue
        accepted, unreadable = {}, {}
        for rel in sorted(set(_DOC_SCRIPT.findall(body))):
            leaf = os.path.basename(rel)
            try:
                mod = _loader.load_script(leaf, modname="cc_" + leaf[:-3].replace("-", "_"))
            except Exception as exc:
                unreadable[leaf] = "will not load (%s)" % (exc,)
                continue
            build = getattr(mod, "build_parser", None)
            if not callable(build):
                unreadable[leaf] = "exposes no build_parser()"
                continue
            try:
                accepted.update(parser_choices(build()))
            except Exception as exc:
                unreadable[leaf] = "build_parser() raised (%s)" % (exc,)
        out += choice_drift(name, advertised, accepted, unreadable)
    return out
