#!/usr/bin/env python3
"""
What the plugin can tell you about itself, without spending a token — stdlib only.

Two questions get asked of a panel: *what is this field?* and *how does this
actually work?* Both had the same answer here until v0.31 — read the README, or
ask a model and pay for it. This module is the zero-token half of the answer, and
`/api/help` is a thin front door onto it.

FIELD DESCRIPTIONS ARE EXTRACTED, NEVER RESTATED. `schema/audit-config.schema.json`
and `schema/audit-plan.schema.json` already describe every key, they are shipped
for editors and validated in CI, and they are the document a reader is told to
trust. So `fields()` walks a schema and hands back `{dotted path: what the schema
says}` at request time. A second copy of that prose would be a second thing to
keep true, and this repository has already shipped that bug (`exemptGlobs` and
`tddReminder.testGlobs`, two lists disagreeing about what a test file is).

TOPICS ARE DERIVED WHERE A RULE IS EXECUTABLE, AND POINTERS WHERE IT IS NOT. A
concept page that re-types a rule the code decides is drift waiting to happen, so:

  - the plan gate's tiers come from `_config.plan_gate_mode` — the function the
    hook calls, asked the same three questions the hook asks it;
  - the area resolution IS `_areas.REVIEW_RULE` / `SKILLS_RULE`, the pinned
    sentences every doc is already linted against;
  - the policy precedence is a WORKED EXAMPLE run through `_policy.resolve`, so
    each verdict and its basis are the guard's own words;
  - the journal's row shape is whatever `audit-journal._normalise` produces.

Where the product states something authoritatively in prose — the four limits of
the capability policy, "tamper-evident, not tamper-proof" — a topic NAMES it and
cites where it is stated. It does not restate it. That is the same reason the two
skills are thin: two copies of a claim is one copy and one lie.

THE GUIDE AGENT'S CARD IS READ OFF THE AGENT. `agents/guide.md` is a file
with frontmatter; `guide_card()` parses it, so a drawer offering "Ask audit:guide"
cannot advertise tools the agent does not have — and `guide_is_read_only()` fails
the build if that agent ever gains one that writes.

Consumers: `panel-server.py` (`GET /api/help`, and the help drawer that consumes
it), and the cases in `tests/test__help.py`, which are the reason
none of this is untested code while the drawer is still being built.

This module carries no `--selftest` of its own any more; its cases live in
that file, byte-identical labels and all - see `tests/_harness.py`.
(That figure read 67 against a real 70 before the twelve `schema_vocab_drift`
cases landed, so it was already rotting; print it rather than trust it -
`python3 tests/test__help.py --selftest | tail -1`.)
Nothing checks that a topic's citation still resolves to a heading, or that a
document enumerating the agents names them all: the two checks that did were
retired, so the sources in `topics()` and the agents a document lists are kept true
by whoever edits them.

ONE PATH RESOLVER, AND IT IS THIS ONE. A drawer holds a path into a DOCUMENT
(`usage.pricing.opus.in`); the table it looks that up in is keyed by SHAPES
(`usage.pricing.<name>.in`). `entry_for()` is what the panel asks, over HTTP, so
the browser never grows a second implementation of that normalisation — the same
reason the policy switchboard is handed verdicts rather than patterns to match.
"""
import json
import os
import re
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

import _areas                                    # noqa: E402  (the areas rule)
import _policy                                   # noqa: E402  (the policy verdicts)
import _loader                                   # noqa: E402  (the one path-importlib loader)
import _journal_io                               # noqa: E402  (the journal row shape)
import _manifest_vocab                           # noqa: E402  (the KNOWN_* sets schema_vocab_drift checks)

# The schemas ARE the field documentation; these are the only two there are.
# Spelled with '/', which both platforms open and which serialises the same
# everywhere - an os.path.join here would put a backslash in the served payload.
SCHEMAS = {
    "config": "schema/audit-config.schema.json",
    "manifest": "schema/audit-plan.schema.json",
}

# The panel's Composition tab edits manifest levers under names of its own
# (`taskModel`), because a form control is not a JSON path. This is the map from
# one to the other, and the selftest requires every target to resolve in the
# schema — so a lever whose schema key is renamed fails the build rather than
# quietly losing its help text.
COMPOSITION_PATHS = {
    "reviewSkill": "meta.reviewSkill",
    "buildCommands": "meta.buildCommands",
    # The branch-naming card (a Composition FORM key, saved with the form):
    "branchConvention": "meta.branch",
    "branchTemplate": "meta.branch.template",
    "branchDefaultType": "meta.branch.defaultType",
    "branchTypes": "meta.branch.types",
    "branchInitials": "meta.branch.initials",
    "branchSlugMax": "meta.branch.slugMaxLength",
    # Where a phase lands, and what happens once it has. Same card, same form save,
    # and the same shape as the three ADO settings below: the merge TARGET was
    # reachable only by hand-editing the manifest, and it is the key every reader of
    # a sign-off report depends on.
    "developmentBranch": "meta.developmentBranch",
    "mergePolicy": "meta.merge",
    "mergeAuto": "meta.merge.auto",
    "mergeRemoveWorktree": "meta.merge.removeWorktree",
    "mergeDeleteBranch": "meta.merge.deleteBranch",
    # The worktree table has no manifest key of its own: it describes git. It
    # points at the policy that governs what may be swept, which is the page a
    # reader who clicked it actually wants.
    "worktreeTable": "meta.merge",
    "phaseParentBranch": "phases[].parentBranch",
    "phaseReviewModel": "phases[].review.model",
    "phasePriority": "phases[].priority",
    "phaseAdoParent": "phases[].adoParent",
    # The question one step BEFORE the parent: whether this phase belongs on the
    # shared board at all. Its own lever, and therefore its own reference - the
    # two share a cell and a reader who opened the parent's page would find
    # nothing there about a phase that is deliberately off the board.
    "phaseAdoTracked": "phases[].adoTracked",
    # Three settings whose only path used to be a hand edit. The parent and
    # the gate that needs it sit at the top of `meta.ado`; the tag vocabulary is
    # inside `conventions`, which is where the board's own rules live.
    "adoParentWorkItem": "meta.ado.parentWorkItem",
    "adoRequireParent": "meta.ado.conventions.requireParent",
    "adoTagVocabulary": "meta.ado.conventions.tagVocabulary",
    "taskModel": "phases[].tasks[].model",
    "taskSkills": "phases[].tasks[].skills",
    # The ADO connector card (PUT /api/ado):
    "adoConnector": "meta.ado",
    "adoEnabled": "meta.ado.enabled",
    "adoEcho": "meta.ado.echo",
    "adoPhaseWorkItems": "meta.ado.phaseWorkItems",
    "adoTypes": "meta.ado.types",
    "adoTag": "meta.ado.tag",
    "adoStateMap": "meta.ado.stateMap",
    "adoRemainingWork": "meta.ado.onComplete.remainingWork",
    "adoComments": "meta.ado.comments",
    "adoSprint": "meta.ado.sprint",
    "adoPull": "meta.ado.pull",
    "adoIdentityMap": "meta.ado.identityMap",
    "adoFields": "meta.ado.fields",
}

# Which concept page a field belongs to, by path prefix. Longest prefix wins, so a
# more specific rule can override a broader one.
_FIELD_TOPICS = (
    ("policy", "policy"),
    ("journal", "journal"),
    ("meta.areas", "areas"),
    ("phases[].area", "areas"),
    ("enforce", "gate-tiers"),
    ("planGate", "gate-tiers"),
    ("exemptGlobs", "gate-tiers"),
    ("trivialLineThreshold", "gate-tiers"),
    ("bypassKeyword", "gate-tiers"),
)

# A default is shown beside a field so an empty box means something. Long ones are
# not: `usage.pricing` is a rate table, and its rows carry their own defaults.
_MAX_DEFAULT_ITEMS = 12

# Tools an agent may hold and still be READ-ONLY as a fact rather than as a
# request. The guide answers questions about a repository it must not touch.
READ_ONLY_TOOLS = ("Glob", "Grep", "Read")


def plugin_root(root=None):
    return root or _output.PLUGIN_ROOT


# --- schema extraction -----------------------------------------------------------
def load_schema(which, root=None):
    """One of the two shipped schemas, parsed. Raises if it is unreadable — a help
    endpoint that silently serves nothing is worse than one that says why."""
    rel = SCHEMAS[which]
    with open(os.path.join(plugin_root(root), rel), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _deref(node, defs, seen):
    """Follow `$ref` to the node that carries the description.

    A referring node may describe its own use of a shared shape (`phase.model` is
    "the tier for this phase") while the `$def` describes the shape itself, so the
    caller keeps the referrer's description when there is one and takes the
    target's when there is not. `seen` stops a self-referential schema walking
    forever; it is per branch, so one `$def` used twice in different places is
    still expanded twice."""
    while isinstance(node, dict) and "$ref" in node:
        name = str(node["$ref"]).rsplit("/", 1)[-1]
        if name in seen or name not in defs:
            return None, seen
        seen = seen + (name,)
        node = defs[name]
    return (node if isinstance(node, dict) else None), seen


def _entry(node, defs, seen):
    """What the drawer shows for one key: the words, and the shape they describe."""
    target, _ = _deref(node, defs, seen)
    target = target if isinstance(target, dict) else {}
    desc = node.get("description") if isinstance(node, dict) else None
    out = {"description": desc or target.get("description") or ""}
    for key in ("type", "enum", "format", "minimum", "maximum", "pattern"):
        val = node.get(key) if isinstance(node, dict) else None
        if val is None:
            val = target.get(key)
        if val is not None:
            out[key] = val
    return out


def fields(doc, max_depth=12):
    """`{dotted path: {description, type, enum, …}}` for one schema document.

    Arrays are spelled `customRules[].message` and open maps `pricing.<name>.in`,
    which is how the panel's own paths read and how a reader would say them aloud.
    """
    return _walk_schema(doc, max_depth)["fields"]


def _walk_schema(doc, max_depth=12):
    """`{"fields": …, "sites": [(def name, path), …]}` — the table, and every path
    at which a `$def`'s body was expanded, in walk order.

    The sites are what `fold_repeats` needs: one `$def` reached from two places is
    expanded twice, and the second expansion is a byte-for-byte copy of the first
    under a different prefix."""
    out = {}
    sites = []
    defs = doc.get("$defs") if isinstance(doc.get("$defs"), dict) else {}

    def walk(node, prefix, seen, depth):
        if depth > max_depth:
            return
        node, reached = _deref(node, defs, seen)
        if len(reached) > len(seen):
            sites.append((reached[-1], prefix))
        seen = reached
        if not isinstance(node, dict):
            return
        props = node.get("properties")
        if isinstance(props, dict):
            for key, sub in props.items():
                path = ("%s.%s" % (prefix, key)) if prefix else key
                out[path] = _entry(sub, defs, seen)
                walk(sub, path, seen, depth + 1)
        extra = node.get("additionalProperties")
        if isinstance(extra, dict):
            path = ("%s.<name>" % prefix) if prefix else "<name>"
            out[path] = _entry(extra, defs, seen)
            walk(extra, path, seen, depth + 1)
        items = node.get("items")
        if isinstance(items, dict):
            walk(items, prefix + "[]", seen, depth + 1)

    walk(doc, "", (), 0)
    return {"fields": out, "sites": sites}


def _under(path, prefix):
    return path.startswith(prefix + ".") or path.startswith(prefix + "[")


def _subtree(table, prefix, ignore=()):
    """The entries below `prefix`, keyed by what follows it — so two expansions of
    one shape compare equal whatever they are mounted under."""
    return {k[len(prefix):]: {f: v for f, v in e.items() if f not in ignore}
            for k, e in table.items() if _under(k, prefix)}


def fold_repeats(table, sites, ignore=("topic",)):
    """`{"fields": folded table, "aliases": {copy prefix: canonical prefix}}`.

    A `$def` mounted at several paths is the same documentation at each of them,
    and served expanded it is paid for once per mount: the plan's `phase` shape
    reappears whole under every proposal. The first expansion stays; a later one
    is dropped below its own entry, which is kept because it carries the
    referrer's description of its use, and an alias says where its children are
    documented.

    A copy folds only when its subtree is EQUAL to the first one, so a mount the
    depth bound or the recursion guard cut short stays expanded, and so does a
    config path whose default differs from its twin's - a default is the fallback
    for that exact path. `topic` is ignored in the comparison: it is attached by
    path prefix, and a shared shape is the same concept wherever a reader meets
    it, so a folded path answers with the canonical path's page."""
    first = {}
    aliases = {}
    out = dict(table)
    for name, prefix in sites:
        if any(prefix == a or _under(prefix, a) for a in aliases):
            continue
        if name not in first:
            first[name] = prefix
            continue
        canon = first[name]
        copy = _subtree(table, prefix, ignore)
        if not copy or copy != _subtree(table, canon, ignore):
            continue
        out = {k: e for k, e in out.items() if not _under(k, prefix)}
        aliases[prefix] = canon
    return {"fields": out, "aliases": aliases}


def unalias(path, aliases):
    """`path` rewritten through the aliases whose prefixes it sits under, or as is.

    Repeated, because one rewrite can land under another alias: a proposal's
    phase maps onto `phases[]`, whose tasks' `ado` maps onto the phase's own.
    The passes are bounded by the number of aliases, so no alias map can hang a
    lookup."""
    order = sorted(aliases or {}, key=len, reverse=True)
    for _ in range(len(order)):
        hit = next((p for p in order if _under(path, p)), None)
        if hit is None:
            break
        path = aliases[hit] + path[len(hit):]
    return path


def config_fields(root=None):
    return fields(load_schema("config", root))


def manifest_fields(root=None):
    return fields(load_schema("manifest", root))


def unquote_scalar(val):
    """A quoted frontmatter value, with the quoting undone — including the escape.

    Shared with `panel-server._front_matter` rather than written twice: both read
    the same `---` blocks off the same files, and the panel discovered this the
    expensive way. Stripping the quotes and stopping there renders the guide
    agent's own description as *"the plugin''s own README"* on the one surface
    built to explain the plugin — YAML escapes a quote inside a quoted scalar by
    doubling it (`\\"` in a double-quoted one), and a stripper that does not know
    that publishes the escape.

    Balanced quotes only. `don't` is a value, not a mis-quoted one, and the old
    `strip("\\"'")` ate the apostrophe off `'sup` for the same reason it kept
    `''`."""
    val = str(val)
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
        quote, val = val[0], val[1:-1]
        val = val.replace(quote * 2, quote) if quote == "'" \
            else val.replace("\\" + quote, quote)
    return val


def normalise_path(path):
    """`usage.pricing.opus.in` -> `usage.pricing.<name>.in`, `files.0` -> `files[]`.

    A caller holds a path into a DOCUMENT; the schema describes a SHAPE. Without
    this the drawer would find help for `guardEdits.customRules[].message` and none
    at all for the second rule the user is actually looking at."""
    parts = re.split(r"\.", str(path or ""))
    out = []
    for part in parts:
        if re.fullmatch(r"\d+", part):
            if out:
                out[-1] = out[-1] + "[]"
            continue
        out.append(part)
    return ".".join(out)


def lookup(table, path, aliases=None):
    """The entry for `path`, exactly or through the shape it is an instance of —
    and, over a folded table, through the alias that says where a repeated
    shape's children are documented."""
    norm = normalise_path(path)
    parts = norm.split(".")
    # An open map's concrete key: `usage.pricing.opus` -> `usage.pricing.<name>`.
    probes = [path, norm] + [".".join(parts[:i] + ["<name>"] + parts[i + 1:])
                             for i in range(len(parts) - 1, 0, -1)]
    for probe in probes:
        for key in (probe, unalias(probe, aliases)):
            if key in table:
                return table[key]
    return None


# --- defaults --------------------------------------------------------------------
def _config_mod():
    """hooks/_config.py — hyphen-free, but a directory away."""
    return _loader.load_hooks_config(modname="audit__config_help")


def _journal_mod():
    """`_journal_io` — the row shape this topic shows the reader.

    A plain downward import now, not a `_loader.load_script("audit-journal.py")`:
    that was an entry point, one of the edges `_deps.KNOWN_LAYER_DEBT` recorded —
    a help topic reaching several layers UP to normalise one example row."""
    return _journal_io


def _showable(value):
    """Is this default worth printing beside a field?

    Scalars always; a short list of scalars yes, because "the eight globs you get
    for free" is the answer to "what happens if I leave this empty". A dict never:
    its children each carry their own default, and a rate table pasted into a
    tooltip is a wall."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list) and len(value) <= _MAX_DEFAULT_ITEMS:
        return all(v is None or isinstance(v, (str, int, float, bool)) for v in value)
    return False


def config_defaults(defaults=None):
    """`{dotted path: default}` flattened out of `_config.DEFAULTS` — the values the
    hooks actually fall back to, not a second list of them."""
    src = defaults if isinstance(defaults, dict) else _config_mod().DEFAULTS
    out = {}

    def walk(node, prefix):
        for key, val in node.items():
            path = ("%s.%s" % (prefix, key)) if prefix else key
            if isinstance(val, dict):
                walk(val, path)
                continue
            if _showable(val):
                out[path] = val

    walk(src, "")
    return out


def topic_of(path):
    """The concept page a field belongs to, or None. Longest prefix wins."""
    best = None
    for prefix, topic in _FIELD_TOPICS:
        if path == prefix or path.startswith(prefix + ".") or \
                path.startswith(prefix + "["):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, topic)
    return best[1] if best else None


# --- concept topics --------------------------------------------------------------
def _gate_topic():
    """The plan gate, tabulated by asking the function that decides it."""
    cfg_mod = _config_mod()
    import _ui_theme as theme
    rows = []
    for evidence, cfg, state, effect in (
        ("No manifest in this repo", {}, {"exists": False},
         "Records that the edit would have needed a plan, and reports once per "
         "session. Never blocks."),
        ("A manifest holding no phase", {}, {"exists": True},
         "Warns in-band: there is a plan and this edit is not in it."),
        ("Phases, none running", {}, {"exists": True, "hasPhases": True},
         "The free file stays; the next edit is refused until a phase runs "
         "(/audit:phase add, then run it)."),
        ("A manifest and a phase in progress", {}, {"exists": True,
                                                    "phaseRunning": True},
         "Refuses the edit unless the file is in the running task, exempt, or a "
         "single-use bypass was armed."),
        ('planGate: "ask", whatever the evidence', {"planGate": "ask"},
         {"exists": False},
         "Each out-of-plan edit waits for the human's approval, once per edit. "
         "Any tier can be pinned this way; observe is the only one that lowers "
         "the gate below its evidence, and the doctor warns about it."),
        ("enforce: true, whatever the evidence", {"enforce": True},
         {"exists": False},
         "Always-on deny, as a decision someone made rather than a default that "
         "surprises a stranger. Legacy: planGate: \"deny\" says the same thing."),
    ):
        mode = cfg_mod.plan_gate_mode(cfg, state)
        rows.append([evidence, theme.label(mode, theme.GATE_TIER), effect])
    return {
        "id": "gate-tiers",
        "title": "The plan gate is graded on evidence",
        "summary": "How hard the gate pushes depends on what the repo can prove — "
                   "and it never denies on the weakest evidence it has.",
        "paragraphs": [
            "Plan-first only means something where there is a plan. In a repo with "
            "no manifest a denial does not enforce anything; it rate-limits edits, "
            "which is a different and worse product sharing one code path. So the "
            "gate grades itself, and every tier below is read from the same "
            "function the hook calls.",
            "The secret RULES are never graded. Logging an auth token is wrong "
            "whether or not a plan exists, so reading a secret file, sourcing or "
            "copying one, dumping the environment and echoing a token are refused "
            "at every tier by `guard-secrets-read` / `guard-edits` - including "
            "the tier a repo with no manifest at all is on. What is graded is "
            "plan COVERAGE, which is the one claim that needs a plan to mean "
            "anything, and `guard-secrets-read` reads a tier in exactly one "
            "function (`_plan_gate_write_verdict`) that no secret rule calls.",
            "Every Bash WRITE form grades identically, so `sed -i`, a `>` "
            "redirect, `python3 -c` and the Edit tool agree about the same file.",
            "`planGate` pins one tier by hand - observe, warn, ask or deny - "
            "instead of grading on evidence, and it beats the legacy `enforce` "
            "flag when both are set. A typo fails open to the graded ladder, "
            "never to deny; the validator flags it.",
        ],
        "table": {
            "caption": "What the repo has, and what the gate does about it",
            "columns": ["Evidence", "Tier", "What happens"],
            "rows": rows,
        },
        "sources": ["README.md#configuration-claudeauditconfigjson",
                    "hooks/_config.py"],
    }


def _areas_topic():
    """Monorepo areas: the pinned sentence, plus what it answers for a real phase."""
    manifest = {
        "meta": {"reviewSkill": "house-review",
                 "areas": {"api": {"root": "services/api",
                                   "reviewSkill": "backend-review",
                                   "skills": ["python-conventions"]},
                           "web": {"root": "apps/web", "skills": ["ts-conventions"]}}},
    }
    rows = []
    for phase, task, note in (
        ({"id": "P1", "area": "api"}, {"skills": ["sql-review"]},
         "The area answers; nothing on the phase overrides it."),
        ({"id": "P2", "area": "web"}, {},
         "The area declares no reviewer, so the project's own is used."),
        ({"id": "P3", "area": "api", "reviewSkill": None}, {},
         "Set to null ON the phase — an answer, not a miss."),
    ):
        skill, basis = _areas.resolve_review_skill(manifest, phase)
        rows.append([phase["id"] + " (" + str(phase.get("area")) + ")",
                     skill or "— none —", basis or "nothing declares one",
                     ", ".join(_areas.resolve_skills(manifest, phase, task)) or "—",
                     note])
    return {
        "id": "areas",
        "title": "Monorepo areas — how a tag becomes a reviewer",
        "summary": "`meta.areas` turns the free-text `phase.area` tag into "
                   "something with a root, a reviewer and default skills.",
        "paragraphs": [
            "Registration is optional in both directions: a tag with no entry is "
            "still legal (the validator warns, nothing refuses), and an entry no "
            "phase uses is legal too. Write nothing and you get the v0.16 "
            "behaviour, so no existing manifest changes meaning by upgrading.",
            "The reviewer for a phase is `%s`." % _areas.REVIEW_RULE,
            "The executor's skills are the area's, %s — so a project convention "
            "loads before a task-specific one." % _areas.SKILLS_RULE,
            "Several tags on one phase are tried in WRITTEN ORDER. Any tie-break "
            "is arbitrary; what matters is that it is stated and visible, which is "
            "why the validator warns when two areas both declare a reviewer.",
        ],
        "table": {
            "caption": "Resolved against a two-area registry (house-review is the "
                       "project default)",
            "columns": ["Phase", "Reviewer", "Chosen by", "Executor skills",
                        "Why"],
            "rows": rows,
        },
        "sources": ["README.md#monorepo-areas--metaareas",
                    "reference/manifest-conventions.md", "scripts/manifest/_areas.py"],
    }


def _policy_topic():
    """Capability policy: the order, demonstrated by the resolver itself."""
    policy = _policy.policy_cfg({"policy": {
        "skills": {"default": "deny", "allow": ["code-*"], "deny": ["code-danger"],
                   "areas": {"api": {"allow": ["sql-review"]}}}}})
    rows = []
    for name, note in (("audit:next", "audit's own"),
                       ("code-danger", "denied by name"),
                       ("code-review", "allowed by `code-*`"),
                       ("sql-review", "allowed by the active area"),
                       ("some-other-skill", "nothing matched")):
        verdict = _policy.resolve(policy, "skills", name, active_tags=("api",))
        rows.append([name, "Allowed" if verdict["verdict"] == "allow" else "Refused",
                     verdict["basis"]])
    return {
        "id": "policy",
        "title": "Capability policy — what decides a verdict",
        "summary": "Which skills, subagents and MCP tools may be used in this "
                   "repository, resolved in one fixed order.",
        "paragraphs": [
            "Required first: audit's own commands, skills and agents are allowed "
            "whatever the policy says, and the set is READ OFF the plugin's own "
            "directory rather than typed out. Denying one is a validator finding, "
            "not a line that is silently ignored.",
            "Then deny, then allow, then the kind's `default`. Deny beats allow. "
            "Patterns are shell globs matched case-sensitively against the name as "
            "the tool call spells it.",
            "An `areas` rule is in force only while a phase carrying that tag has "
            "work `in_progress` — a hook sees a tool name, not a directory, so "
            "\"in this area\" can only mean \"while this area is being worked on\". "
            "Several active areas union their allow lists; any one's deny wins.",
            "Four limits bound what this can hold — subagent hooks are not "
            "inherited on every version, it denies the tool and not the knowledge, "
            "your own switch outranks it, and hooks cannot gate hooks. They are "
            "stated in full in SECURITY.md and repeated on the Policy tab under "
            "\"What this cannot hold\"; they are named here rather than restated so "
            "there is one wording to keep true.",
        ],
        "table": {
            "caption": "A worked example: skills default to deny, `code-*` is "
                       "allowed, `code-danger` denied, and area `api` is running",
            "columns": ["Capability", "Verdict", "Basis the guard would print"],
            "rows": rows,
        },
        "sources": ["README.md#capability-policy--policy",
                    "../../SECURITY.md", "scripts/governance/_policy.py"],
    }


def _journal_topic():
    """The audit trail: the row shape as the writer produces it."""
    row = _journal_mod()._normalise({"action": "config.write", "target": ".claude/"
                                     "audit.config.json", "ts": "2026-01-01T00:00:00Z"})
    shape = sorted(row) + ["stateHash", "prev", "hash"]
    return {
        "id": "journal",
        "title": "The audit trail — what a row is, and what verify can see",
        "summary": "An append-only, hash-chained record of every write to the plan "
                   "and to the config. Tamper-evident, not tamper-proof.",
        "paragraphs": [
            "Each row carries: %s. `hash` covers the canonical JSON of the row "
            "without it, `prev` is the row before, and the first row's `prev` is "
            "derived from the file's own base name — so a file cannot be renamed "
            "into another writer's slot and still verify."
            % ", ".join("`%s`" % k for k in shape),
            "`stateHash` is the target as it stood immediately after the write, "
            "which is what lets `verify` notice a document that changed with no "
            "row to explain it.",
            "An edited, deleted or reordered row is a FINDING. A torn tail — a row "
            "half-written by a process that died — and out-of-band drift are "
            "WARNINGS, because a `git checkout` produces the second and nobody's "
            "tampering does.",
            "One file per writer per month, beside the manifest, so the same commit "
            "carries both the change and the record of it and two worktrees never "
            "conflict.",
            "The limit is stated wherever the feature is: nothing here stops "
            "someone rewriting the whole file, because there is nowhere on your own "
            "machine to keep a key you cannot read. It is a smoke detector, not a "
            "vault.",
        ],
        "table": None,
        "sources": ["README.md#audit-trail", "../../SECURITY.md",
                    "scripts/governance/audit-journal.py"],
    }


def topics(root=None):
    """The concept pages, built fresh so every derived claim is current."""
    return [_gate_topic(), _areas_topic(), _policy_topic(), _journal_topic()]


# --- the guide agent -------------------------------------------------------------
# Renamed from "audit-guide" in 0.35: the plugin prefix made the qualified
# name stutter (audit:audit-guide), and this is the one agent humans invoke
# by name. Policy configs naming the old id get a validator warning.
GUIDE = "guide"


def front_matter(text):
    """Parse the leading `---\\n ... \\n---\\n` block into a flat {key: value}
    dict, or {}. The one frontmatter parser in the plugin -- it replaces what
    used to be two hand-rolled parsers (this module's old `_frontmatter` and
    `panel-server._front_matter`) that quietly disagreed at the edges. The
    merge, and what it does at each edge the two disagreed on:

    - CRLF: the fence and the lines inside it may end in `\\r\\n` or `\\n`;
      both parse the same.
    - Indented continuation lines (a wrapped value, or YAML block style) are
      skipped rather than mis-read as a new `key: value` pair -- this is the
      more correct approximation of the two prior parsers, so it won.
    - Quoted scalars go through `unquote_scalar`, which undoes a doubled `''`
      or an escaped `\\"` rather than stripping bare quote characters (see
      that function's docstring for why the naive strip was wrong).
    - The block is parsed in full no matter how long it is -- this function
      takes the whole text; a caller that wants a read-size cap (scanning
      many files cheaply) applies it before calling and falls back to a full
      read when the cap would cut through the block itself.
    - No closing `---` fence, or no leading `---` line at all: returns {}
      rather than a guess.

    Deliberately not a YAML parser: the frontmatter this repository writes is
    flat scalars and one comma list, and a hand-rolled parser that quietly
    mis-reads something more elaborate would be worse than one that reads
    exactly what is there."""
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not match:
        return {}
    out = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip() != line:
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        out[key.strip()] = unquote_scalar(val.strip())
    return out


def _frontmatter(path):
    """Thin wrapper: read the file (utf-8, best-effort) and delegate to the
    one frontmatter parser, `front_matter`. See that docstring for the
    merged edge-case behavior."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return {}
    return front_matter(text)


def agent_cards(root=None):
    """Every agent the plugin ships, as its own file describes it."""
    directory = os.path.join(plugin_root(root), "agents")
    out = []
    try:
        names = sorted(os.listdir(directory))
    except Exception:
        return out
    for name in names:
        if not name.endswith(".md") or name.startswith("."):
            continue
        front = _frontmatter(os.path.join(directory, name))
        if not front:
            continue
        tools = [t.strip() for t in (front.get("tools") or "").split(",")
                 if t.strip()]
        out.append({
            "name": front.get("name") or name[:-3],
            "qualified": "audit:%s" % (front.get("name") or name[:-3]),
            "description": front.get("description") or "",
            "tools": tools,
            "model": front.get("model"),
            "effort": front.get("effort"),
            # Plugin-relative and "/"-separated on every platform, like the
            # topics' `sources`: it is shown to a reader, never opened, and an
            # os.sep join made the served payload a byte larger on Windows.
            "file": "agents/" + name,
        })
    return out


def guide_card(root=None):
    """The card the drawer's "Ask audit:guide" hint is built from, or None.

    None rather than a stub when the agent is absent: a hint offering an agent
    this install does not ship is a dead end, and the drawer can simply not draw
    it."""
    for card in agent_cards(root):
        if card["name"] == GUIDE:
            card = dict(card)
            card["invoke"] = "Ask for the `audit:guide` subagent by name."
            card["readOnly"] = sorted(card["tools"]) == sorted(READ_ONLY_TOOLS)
            return card
    return None


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


# --- the payload -----------------------------------------------------------------
DOCS = ("config", "manifest")


def _enriched(which, root, defaults):
    """One schema's table with each entry's default and concept page attached,
    folded so a repeated shape is served once."""
    walked = _walk_schema(load_schema(which, root))
    table = {}
    for path, entry in walked["fields"].items():
        entry = dict(entry)
        if path in defaults:
            entry["default"] = defaults[path]
        topic = topic_of(path)
        if topic:
            entry["topic"] = topic
        table[path] = entry
    return fold_repeats(table, walked["sites"])


def tables(root=None):
    """`{"fields": {"config": {…}, "manifest": {…}}, "aliases": {…same keys…}}` —
    every field, ready to serve, and where each folded copy's children live.

    The enrichment (a config field's default, either field's concept page) lives
    here rather than in `entry_for()` so every reader of the tables sees one
    build: two assemblies would be two answers about one field. The fold lives here
    for the same reason: `entry_for` resolves through the very aliases built
    alongside the table."""
    root = plugin_root(root)
    defaults = {"config": config_defaults(), "manifest": {}}
    built = {which: _enriched(which, root, defaults[which]) for which in DOCS}
    return {"fields": {which: built[which]["fields"] for which in DOCS},
            "aliases": {which: built[which]["aliases"] for which in DOCS}}


def entry_for(path, doc="config", root=None):
    """One field, resolved the way a reader ASKED for it.

    `{doc, path, key, entry}` — `path` as it was asked, `key` as the schema spells
    the shape that answered it, because "documented as `usage.pricing.<name>.in`"
    is the sentence that tells someone their second pricing row is not a second
    field. None when nothing documents it: a drawer that opens on an empty page is
    worse than one that says it has no entry for this."""
    if doc not in DOCS:
        return None
    built = tables(root)
    table = built["fields"][doc]
    entry = lookup(table, path, built["aliases"][doc])
    if entry is None:
        return None
    # Identity, not equality: `lookup` hands back the table's own object, and two
    # different keys can carry word-for-word identical entries.
    key = next((k for k, v in table.items() if v is entry), None)
    return {"doc": doc, "path": path, "key": key, "entry": entry}


def payload(root=None):
    """Everything `GET /api/help` serves: the topics, the agent card and
    the two small maps the drawer reads.

    Project-independent on purpose. This is documentation, not state — the live
    verdicts belong to `/api/policy`, the live trail to `/api/journal`, and a help
    drawer that quietly mixed the two would let a reader believe a worked example
    was their own repository.

    There is no field table here, and that is the point of this shape: the drawer
    opens one field at a time and asks `entry_for` for it over
    `GET /api/help?path=`, which resolves a path through the fold and the aliases
    on the server. A whole-table copy in this payload was read by nothing in the
    product, so a caller that wants the tables calls `tables()` or `entry_for()`
    rather than looking for a key of this dict. `test__help.py` is what holds the
    payload's keys to the ones `help-drawer.js` reads."""
    root = plugin_root(root)
    return {
        "composition": dict(COMPOSITION_PATHS),
        "topics": topics(root),
        "agent": guide_card(root),
        "schemas": dict(SCHEMAS),
    }


if __name__ == "__main__":
    import sys
    from _output import safe_stdio, selftest_requested      # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_help.py has no inline --selftest; its cases moved to "
              "tests/test__help.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
