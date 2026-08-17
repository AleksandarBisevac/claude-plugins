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

This module carries no `--selftest` of its own any more; its 67 cases live in
that file, byte-identical labels and all - see `plugins/audit/tests/_harness.py`.
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
    "phaseReviewModel": "phases[].review.model",
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
    return _loader.load_script("audit-journal.py", modname="audit_journal_help")


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
