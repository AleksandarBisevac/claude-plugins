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
it), and the cases in `plugins/audit/tests/test__help.py`, which are the reason
none of this is untested code while the drawer is still being built.

This module carries no `--selftest` of its own any more; its cases live in
that file, byte-identical labels and all - see `plugins/audit/tests/_harness.py`.
(That figure read 67 against a real 70 before the twelve `schema_vocab_drift`
cases landed, so it was already rotting; print it rather than trust it -
`python3 plugins/audit/tests/test__help.py --selftest | tail -1`.)
Three of them are CITATION cases: `source_drift()` and `agent_doc_drift()` read
this repository's own `README.md`, `SECURITY.md`, `PLUGIN-BUILD-GUIDE.md`,
`reference/*.md` and `agents/*.md` through `plugin_root()` - which is `_output`'s
one `PLUGIN_ROOT` anchor, so they keep resolving from `tests/` unchanged. Three of the
citations are plugin-relative paths into `scripts/` (`_areas.py`, `_policy.py`,
`audit-journal.py`); they are literals on purpose, and their going red when one of
those files moves is the feature.

ONE PATH RESOLVER, AND IT IS THIS ONE. A drawer holds a path into a DOCUMENT
(`usage.pricing.opus.in`); the table it looks that up in is keyed by SHAPES
(`usage.pricing.<name>.in`). `entry_for()` is what the panel asks, over HTTP, so
the browser never grows a second implementation of that normalisation — the same
reason the policy switchboard is handed verdicts rather than patterns to match.
"""
import ast
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
import _journal_io                               # noqa: E402  (the journal row shape, at layer 1)
import _manifest_vocab                           # noqa: E402  (the KNOWN_* sets schema_vocab_drift checks, at layer 1)

# The schemas ARE the field documentation; these are the only two there are.
SCHEMAS = {
    "config": os.path.join("schema", "audit-config.schema.json"),
    "manifest": os.path.join("schema", "audit-plan.schema.json"),
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
    "phaseReviewModel": "phases[].review.model",
    "phasePriority": "phases[].priority",
    "phaseAdoParent": "phases[].adoParent",
    # The question one step BEFORE the parent: whether this phase belongs on the
    # shared board at all. Its own lever, and therefore its own reference - the
    # two share a cell and a reader who opened the parent's page would find
    # nothing there about a phase that is deliberately off the board.
    "phaseAdoTracked": "phases[].adoTracked",
    # F187: three settings whose only path used to be a hand edit. The parent and
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
    out = {}
    defs = doc.get("$defs") if isinstance(doc.get("$defs"), dict) else {}

    def walk(node, prefix, seen, depth):
        if depth > max_depth:
            return
        node, seen = _deref(node, defs, seen)
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
    return out


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


def lookup(table, path):
    """The entry for `path`, exactly or through the shape it is an instance of."""
    if path in table:
        return table[path]
    norm = normalise_path(path)
    if norm in table:
        return table[norm]
    # An open map's concrete key: `usage.pricing.opus` -> `usage.pricing.<name>`.
    parts = norm.split(".")
    for i in range(len(parts) - 1, 0, -1):
        probe = ".".join(parts[:i] + ["<name>"] + parts[i + 1:])
        if probe in table:
            return table[probe]
    return None


# --- defaults --------------------------------------------------------------------
def _config_mod():
    """hooks/_config.py — hyphen-free, but a directory away."""
    return _loader.load_hooks_config(modname="audit__config_help")


def _journal_mod():
    """`_journal_io` — the row shape this topic shows the reader.

    A plain import at layer 1 now, not a `_loader.load_script("audit-journal.py")`:
    this module is layer 3 and that was a layer 7 entry point, one of the edges
    `_deps.KNOWN_LAYER_DEBT` recorded — a help topic reaching four layers UP to
    normalise one example row."""
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
        ("A manifest, nothing running", {}, {"exists": True},
         "Warns in-band: there is a plan and this edit is not in it."),
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
            "The secret guards are never graded. Logging an auth token is wrong "
            "whether or not a plan exists, and `guard-secrets-read` / `guard-edits` "
            "refuse at every tier.",
            "The shell-write half of the gate grades identically, so `sed -i` and "
            "the Edit tool agree about the same file.",
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
            "file": os.path.join("agents", name),
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
# Docs that ENUMERATE the shipped agents. Named explicitly, the same way
# `_areas._RULE_DOCS` is: `reference/orchestrator.md` names three agents because it
# spawns three, and requiring it to name a user-invoked one would be wrong.
_AGENT_DOCS = (
    "README.md",
    os.path.join("..", "..", "SECURITY.md"),
    os.path.join("..", "..", "PLUGIN-BUILD-GUIDE.md"),
)
_COUNT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten")


def agent_doc_drift(root=None):
    """[(file, problem), …] for every enumerating doc that has gone stale.

    Two ways it goes stale and both have happened here: an agent is added and a doc
    still lists the old set, or a doc says "three pinned-tool agents" while the
    directory holds four. A file that is not there is not drift — installed from a
    marketplace the plugin ships without the repository's own documents."""
    root = plugin_root(root)
    cards = agent_cards(root)
    names = [c["name"] for c in cards]
    out = []
    for rel in _AGENT_DOCS:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:
            out.append((rel, "unreadable: %s" % exc))
            continue
        for name in names:
            if name not in text:
                out.append((rel, "does not name the %s agent" % name))
        for word in re.findall(r"([A-Za-z]+) pinned-tool agents", text):
            if word.lower() not in _COUNT_WORDS or \
                    _COUNT_WORDS.index(word.lower()) != len(cards):
                out.append((rel, "says %r pinned-tool agents; the directory holds "
                                 "%d" % (word, len(cards))))
    return out


def _slug(heading):
    """A GitHub-style anchor for a markdown heading."""
    text = re.sub(r"[`*_]", "", heading).strip().lower()
    text = re.sub(r"[^a-z0-9 \-]", "", text)
    return re.sub(r"\s", "-", text)


def source_drift(root=None):
    """[(topic, source, problem), …] — every citation that does not resolve.

    A topic that points at `README.md#audit-trail` is making a checkable claim, and
    a renamed heading breaks it silently. Paths are plugin-relative, `../../` for
    the repository's own documents; a missing repo document is skipped for the same
    reason as above, but a missing ANCHOR in a file that IS there is drift."""
    root = plugin_root(root)
    out = []
    for topic in topics(root):
        for src in topic.get("sources") or []:
            rel, _, anchor = src.partition("#")
            path = os.path.join(root, rel) if not rel.startswith("..") \
                else os.path.join(root, rel)
            if not os.path.isfile(path):
                if rel.startswith(".."):
                    continue
                out.append((topic["id"], src, "no such file"))
                continue
            if not anchor:
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except Exception as exc:
                out.append((topic["id"], src, "unreadable: %s" % exc))
                continue
            slugs = {_slug(m) for m in re.findall(r"^#{1,6}\s+(.+)$", text, re.M)}
            if anchor not in slugs:
                out.append((topic["id"], src, "no heading with that anchor"))
    return out


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

    `anchors` defaults to `SCHEMA_ANCHORS`, the seven levels checked for coverage;
    `SUBSET_ANCHORS` is passed in for the containment check, which walks the same
    table and only asks a different question of it.
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
    `mv34` and `mv35` in `plugins/audit/tests/test__manifest_vocab.py` assert that
    and print the figures, because "reuse the other walk" is the obvious suggestion
    and acting on it drops a whole level in silence.

    AND WHY IT LIVES HERE AND NOT BESIDE THE SETS. The vocabulary is at layer 1;
    `fields()` is in this module at layer 2 and `gen-demo-manifest` is an entry point
    above it. Importing upward is what `_deps.layer_violations()` fails, and writing
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


def vocab_subsets(mod=None):
    """`{name: value}` for every `*_KEYS` attribute on the vocabulary module.

    Read off the module by its naming convention for the same reason `vocab_sets()`
    is: a subset added later must be compared whether or not anybody remembered this
    function existed. The other upper-case names there (`STATUS`, `BUG_STATUS`,
    `RISK`, `TESTS_MODE`, the two `*_RE` patterns) enumerate VALUES rather than keys,
    which is why the suffix and not "everything upper-case" is the filter.
    """
    mod = _manifest_vocab if mod is None else mod
    return dict((n, getattr(mod, n)) for n in dir(mod) if n.endswith("_KEYS"))


def subset_drift(levels, sets, anchors):
    """The containment comparison, on three plain arguments.

    ONE DIRECTION, AND THAT IS THE WHOLE POINT. Every key in the set must be a
    property the schema declares at the anchor; a property the schema declares and
    the set omits is CORRECT and is not reported. A recommended subset is a proper
    subset by design, so the coverage rule `vocab_drift()` applies would fail a set
    that is behaving perfectly — and a lint that fails the state it is asking for is
    one people learn to route around.

    Separate from `schema_subset_drift()` for the reason `vocab_drift()` is separate
    from `schema_vocab_drift()`: a lint that can only be run against the real tree is
    a lint whose own failure modes are untested. Every case proving this goes RED
    hands it a fixture here rather than mutating the shipped vocabulary.

    `levels` is `{set name: the properties the schema declares at its anchor}`,
    `sets` is `{set name: the keys the subset recommends}`, `anchors` the
    `(name, dotted path)` pairs.
    """
    anchored = dict(anchors)
    out = []

    for name in sorted(set(sets) - set(anchored)):
        out.append((name, "no SUBSET_ANCHORS entry: nothing says which schema "
                          "level this recommended subset is drawn from"))

    for name, anchor in anchors:
        where = anchor or "<root>"
        if name not in sets:
            out.append((name, "SUBSET_ANCHORS anchors it at %r, but the vocabulary "
                              "has no such set" % (where,)))
            continue
        recommended = list(sets[name])
        schema = set(levels.get(name) or ())
        # THE TWO EMPTY CASES ARE NOT SYMMETRIC, and saying so is the difference
        # between a guard and a ritual. An empty SET passes containment in silence
        # while the rule reading it asks for nothing — that one is pass-to-fail. An
        # empty LEVEL already fails, because every key in the set is then undeclared;
        # what this buys is the DIAGNOSIS, since without it a renamed `$def` reads as
        # three typos in the vocabulary rather than one move in the schema.
        if not schema:
            out.append((name, "the anchor %r declares no properties in "
                              "audit-plan.schema.json - a containment check against "
                              "nothing passes for any set" % (where,)))
            continue
        if not recommended:
            out.append((name, "the set is empty, so the rule reading it asks for "
                              "nothing and reports no key missing - indistinguishable "
                              "from every key being present"))
        for key in sorted(set(recommended) - schema):
            out.append((name, "%s.%s is recommended by this set and not declared by "
                              "the schema - a typo here does not warn, it stops the "
                              "key being asked for at all" % (where, key)))
    return out


def schema_subset_drift(root=None):
    """[(set-name, problem), …] — every `_manifest_vocab` recommended subset that
    has stopped being a subset of the schema level it is drawn from.

    Here rather than beside the sets for the reason `schema_vocab_drift()` is: the
    vocabulary is at layer 1 and `fields()` is at layer 2. `_manifest_vocab` keeps
    the claim it owns — `SUBSET_ANCHORS`, which level each subset is drawn from —
    and this is the comparison.

    WHAT IT CANNOT SEE, stated rather than implied, and every one of them
    UNDER-warns, which is the quiet direction:

      * whether the subset is the RIGHT subset. Containment is silent about
        omissions BY DESIGN — `CLAIM_KEYS` omitting `at` is the rule working — so a
        key that ought to be recommended and was dropped reads identically to one
        deliberately left out. Nothing here can tell those apart, and a check that
        tried would be the coverage check this one exists not to be.
      * a key that is a real property at the anchor but the wrong one for the rule
        (recommending `at`, which a claim writes rather than owes). Containment
        accepts it; the cost lands at runtime as a warning on correct manifests.
      * whether anything still READS the set. Delete the `CLAIM_KEYS` loop from
        `_manifest_phases._check_claim` and this stays green over a subset nobody
        consults — which is why `tests/test__manifest_vocab.py` drives that warning
        for real (mv27) instead of trusting the vocabulary to be consulted.
    """
    anchors = _manifest_vocab.SUBSET_ANCHORS
    return subset_drift(schema_level_keys(root, anchors), vocab_subsets(), anchors)


# --- the vocabularies that are literals at their call site ------------------------
def _called_name(node):
    """The bare function name of a call — `f()` and `mod.f()` alike, else None."""
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def _literal_str(node):
    """The value of a string literal node, or None if it is not one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_str_set(node):
    """The strings in a `{"a", "b"}` literal, or None if it is not one.

    None for `set(vocab)`, for a set holding a NAME rather than a constant, and for a
    comprehension. Declined rather than guessed at: the whole point is to read what a
    call actually passes, and anything needing a value the parser does not have would
    be a second implementation of the module being checked.
    """
    if not isinstance(node, ast.Set):
        return None
    out = set()
    for elt in node.elts:
        val = _literal_str(elt)
        if val is None:
            return None
        out.add(val)
    return out


def inline_vocabularies(sources):
    """The `_unknown_keys()` calls whose vocabulary is written into the call itself.

    `sources` is `{relative path: source text}`; the answer is
    `{"found": {dotted path: {"keys": …, "sites": [(where, sorted keys), …]}},
    "problems": [(relative path, why), …]}`, where `keys` is the union across sites.

    READ THE ARGUMENT, NOT A COPY OF IT. `meta.ado.onComplete` and its three
    neighbours have no named set anywhere — the vocabulary IS the literal in the
    call, so a check pointed at anything else would be checking a second spelling
    and reporting on the first. Sites that disagree with each other are reported
    rather than quietly merged, which is the only way a union can be safe.

    A call whose set or whose path is not a literal is SKIPPED IN SILENCE, because a
    named set is `schema_vocab_drift()`'s job and a computed one cannot be resolved
    without running the module. That is an under-count, and it is written out on
    `schema_inline_drift()` with the rest of what this cannot see.
    """
    found, problems = {}, []
    for rel in sorted(sources):
        try:
            tree = ast.parse(sources[rel])
        except SyntaxError as exc:
            # Named rather than skipped: a file the parser cannot read is not a file
            # with no inline vocabulary in it, and silence here would shrink the
            # scan's scope without shrinking the claim made about it.
            problems.append((rel, "does not parse, so any inline vocabulary in it "
                                  "is invisible to this check: %s" % (exc,)))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 3:
                continue
            if _called_name(node) != "_unknown_keys":
                continue
            keys = _literal_str_set(node.args[1])
            path = _literal_str(node.args[2])
            if keys is None or path is None:
                continue
            entry = found.setdefault(path, {"keys": set(), "sites": []})
            entry["keys"] |= keys
            entry["sites"].append(("%s:%d" % (rel, node.lineno),
                                   tuple(sorted(keys))))
    return {"found": found, "problems": problems}


def inline_drift(levels, found, anchors):
    """The comparison itself, on three plain arguments.

    `levels` is `{dotted path: the properties the schema declares there}`, `found` is
    `inline_vocabularies()`' `found` table, and `anchors` the dotted paths
    `INLINE_ANCHORS` declares. Separate from `schema_inline_drift()` for the reason
    `vocab_drift()` is separate from `schema_vocab_drift()`: a lint you can only run
    against the real tree is a lint whose own failure modes are untested.

    COVERAGE, BOTH DIRECTIONS, and the consumer is why. Each literal is the `known`
    argument of `_unknown_keys()`, so a schema property it omits becomes a warning
    about a real key, and a key it holds that the schema does not declare is a typo
    that took the warning for the real key with it. Neither is the RECOMMENDED-subset
    shape `subset_drift()` exists for, and asking coverage of one of those would fail
    a set that is behaving perfectly — which is why the two tables are separate.

    Everything it can say:

      * a declared path with no call site at all — the check has stopped covering
        that level rather than found it clean, and this is the direction that would
        otherwise pass in silence, since a comparison over nothing found reports
        nothing wrong;
      * a literal found at a path nothing declares, so a nested vocabulary added
        later cannot opt out of the check by being forgotten;
      * an anchor that resolves to NO schema properties, which is what a renamed or
        restructured level looks like from here;
      * two call sites passing different vocabularies for one level — one of them is
        already wrong, and a union alone would hide exactly that;
      * a property the schema declares and no call site names, and a key a call site
        passes that the schema does not declare.
    """
    declared = tuple(anchors)
    out = []

    for path in sorted(set(found) - set(declared)):
        out.append((path, "an inline vocabulary at %s that INLINE_ANCHORS does not "
                          "declare - a level nothing compares is where this whole "
                          "class of drift starts"
                    % (", ".join(site for site, _keys in found[path]["sites"]),)))

    for path in declared:
        entry = found.get(path)
        if not entry:
            out.append((path, "declared here, but no `_unknown_keys()` call under "
                              "scripts/ passes a literal set at this path - the "
                              "check has stopped covering the level, which is not "
                              "the same as finding it clean"))
            continue
        schema = set(levels.get(path) or ())
        keys = set(entry["keys"])
        if not schema:
            out.append((path, "the anchor declares no properties in "
                              "audit-plan.schema.json - a comparison against "
                              "nothing passes for any set"))
            continue
        spellings = sorted(set(k for _site, k in entry["sites"]))
        if len(spellings) > 1:
            out.append((path, "call sites pass different vocabularies for this "
                              "level, so one of them is already wrong: %s"
                        % (", ".join("%s %s" % (site, list(k))
                                     for site, k in sorted(entry["sites"])),)))
        for key in sorted(schema - keys):
            out.append((path, "%s.%s is in the schema and no call site names it - "
                              "add it, or the typo-catcher warns about a real key"
                        % (path, key)))
        for key in sorted(keys - schema):
            out.append((path, "%r is passed here and the schema does not declare it "
                              "at %s - add it to the schema, or the key it was meant "
                              "to be is the one going unwarned" % (key, path)))
    return out


def schema_inline_drift(root=None):
    """[(where, problem), …] — every nested level whose vocabulary is a set literal
    at its `_unknown_keys()` call and has stopped agreeing with
    `schema/audit-plan.schema.json`.

    Here rather than beside the anchors for the reason `schema_vocab_drift()` is: the
    vocabulary is at layer 1 and `fields()` is at layer 2. `_manifest_vocab` keeps the
    claim it owns — `INLINE_ANCHORS`, which levels are checked this way — and this is
    the comparison.

    `scripts/` ONLY, and the exclusions are load-bearing rather than incidental.
    `tests/` passes literal sets at a literal path to exercise `_unknown_keys` itself
    (`test__manifest_vocab.py`'s first few cases), and those are fixtures, not
    vocabulary: scanning them would fail a correct tree, which is how a lint gets
    routed around. `hooks/` cannot reach `_manifest_vocab` at all — hooks may not
    import `scripts/`.

    WHAT IT CANNOT SEE, stated rather than implied, and every one of them
    UNDER-warns, which is the quiet direction:

      * a vocabulary that is not a literal. `meta.ado.stateMap` is checked against
        `set(vocab)` and each block under it against `set(statuses)`, so neither is
        compared here — and the second one is not merely unchecked but genuinely
        divergent today: `_manifest_vocab.STATUS` carries `cancelled`, which the
        schema does not declare under `stateMap.task` or `stateMap.phase`. Closing
        that needs an exemption with a reason, not a wider scan.
      * a `_unknown_keys` reimplemented under another name, or reached through an
        alias the parser cannot resolve to that name.
      * whether the literal is the RIGHT vocabulary for its rule, as opposed to one
        the schema also declares.
      * whether the call is ever REACHED. The same limit `schema_subset_drift()`
        names: delete the branch around one of these calls and this stays green over
        a level nothing validates, which is why `test__manifest_vocab.py` drives the
        warnings through `_manifest_ado.check_ado_meta()` for real.
    """
    anchors = _manifest_vocab.INLINE_ANCHORS
    # `schema_level_keys()` keys its answer by SET NAME. These levels have no set
    # name — the path is the only name they have — so each is paired with itself,
    # which walks the same `fields()` output the other two tables do rather than
    # growing a third walk over the schema.
    pairs = tuple((path, path) for path in anchors)
    sources, problems = {}, []
    for rel, path in _output.py_files(_output.SCRIPTS_DIR):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                sources[rel] = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            # Named rather than skipped, for the reason `prose_number_claims()` names
            # its unreadable files: a file that cannot be read is not a clean one.
            problems.append((rel, "unreadable: %s" % (exc,)))
    scan = inline_vocabularies(sources)
    return (problems + scan["problems"]
            + inline_drift(schema_level_keys(root, pairs), scan["found"], anchors))


# --- the payload -----------------------------------------------------------------
DOCS = ("config", "manifest")


def tables(root=None):
    """`{"config": {…}, "manifest": {…}}` — every field, ready to serve.

    The enrichment (a config field's default, either field's concept page) lives
    here rather than inside `payload()` so a single-path lookup answers with
    exactly what the whole payload would have said about that path. Two builders
    would be two answers, and the drawer shows one right after the other."""
    root = plugin_root(root)
    cfg = config_fields(root)
    man = manifest_fields(root)
    defaults = config_defaults()
    for path, entry in cfg.items():
        if path in defaults:
            entry["default"] = defaults[path]
        topic = topic_of(path)
        if topic:
            entry["topic"] = topic
    for path, entry in man.items():
        topic = topic_of(path)
        if topic:
            entry["topic"] = topic
    return {"config": cfg, "manifest": man}


def entry_for(path, doc="config", root=None):
    """One field, resolved the way a reader ASKED for it.

    `{doc, path, key, entry}` — `path` as it was asked, `key` as the schema spells
    the shape that answered it, because "documented as `usage.pricing.<name>.in`"
    is the sentence that tells someone their second pricing row is not a second
    field. None when nothing documents it: a drawer that opens on an empty page is
    worse than one that says it has no entry for this."""
    if doc not in DOCS:
        return None
    table = tables(root)[doc]
    entry = lookup(table, path)
    if entry is None:
        return None
    # Identity, not equality: `lookup` hands back the table's own object, and two
    # different keys can carry word-for-word identical entries.
    key = next((k for k, v in table.items() if v is entry), None)
    return {"doc": doc, "path": path, "key": key, "entry": entry}


def payload(root=None):
    """Everything `GET /api/help` serves: the fields, the topics, the agent.

    Project-independent on purpose. This is documentation, not state — the live
    verdicts belong to `/api/policy`, the live trail to `/api/journal`, and a help
    drawer that quietly mixed the two would let a reader believe a worked example
    was their own repository."""
    root = plugin_root(root)
    tbl = tables(root)
    return {
        "fields": tbl,
        "composition": dict(COMPOSITION_PATHS),
        "topics": topics(root),
        "agent": guide_card(root),
        "schemas": dict(SCHEMAS),
    }


if __name__ == "__main__":
    import sys
    from _output import safe_stdio      # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_help.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__help.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
