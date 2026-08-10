#!/usr/bin/env python3
"""
The `policy` config block and everything that resolves against it — stdlib only.

A project can say which skills, subagents and MCP tools may be used inside it:

    "policy": {
      "enabled": true,
      "onViolation": "deny",
      "skills": {"default": "allow", "deny": ["dangerous-skill"]},
      "agents": {"default": "deny",  "allow": ["audit:*", "code-reviewer"],
                 "areas": {"api": {"allow": ["backend-review"]}}},
      "mcp":    {"default": "allow", "deny": ["mcp__prod-db__*"]}
    }

Shipped INERT: every kind defaults to `allow` with empty lists, which is a policy
that cannot refuse anything (`is_active()` says so, and the guard hook exits on it
without reading the manifest). A repo that writes nothing behaves exactly as it did
before v0.30.

**The resolution, once, here** — `hooks/guard-capabilities.py` enforces it, the
panel previews it, the doctor and the validator check it, and none of them owns a
second opinion about what a policy means:

    1. REQUIRED    audit's own skills, commands and agents are allowed whatever the
                   policy says. See `required_names` — the set is READ OFF the
                   plugin's own directory, not typed out, so it cannot drift from
                   what ships.
    2. DENY        a match in `deny`, or in any ACTIVE area's `deny`, is a
                   violation. Deny beats allow, and one area's deny is enough.
    3. ALLOW       a match in `allow`, or in any ACTIVE area's `allow`, passes.
                   Several active areas UNION their allow lists — documented
                   fail-open: a repo working in two areas at once gets the more
                   permissive answer rather than the intersection nobody wrote.
    4. DEFAULT     `default: "deny"` refuses everything else; `"allow"` permits it.

"ACTIVE areas" are the `meta.areas` tags of phases with in_progress work
(`_config.active_area_tags`). An area rule is therefore scoped to *while that part
of the monorepo is being worked on*, which is the only reading that means anything
for a tool call — a hook sees a tool name, not a directory.

Every verdict carries the `basis` that produced it — the rule text and the list it
came from — because a refusal a reader cannot explain is a refusal they will turn
off.

Patterns are `fnmatch` globs matched CASE-SENSITIVELY against the name as the tool
call spells it (`fnmatchcase`, not `fnmatch`, which normalises case on macOS and
Windows and would make one policy mean two things on two machines):

    skills   the Skill tool's `skill` argument      e.g. `audit:next`, `dataviz`
    agents   the Task/Agent tool's `subagent_type`  e.g. `audit:audit-executor`
    mcp      the whole tool name                    e.g. `mcp__github__get_issue`,
             so `mcp__github__*` is how a server is named

**What this cannot do**, stated here because the panel and SECURITY.md both quote
it: it governs the TOOL, not the knowledge — denying a skill stops the tool call,
not a model that already read the same document; it only holds while the plugin is
enabled, because a user's own switch outranks it; subagents do not inherit parent
hooks on every Claude Code version (anthropics/claude-code#43772), so a policy may
be advisory inside a subagent; and hooks cannot gate hooks, so other plugins'
hooks are inventoried, never enforced.
"""
import fnmatch
import os

# --- constants + defaults -----------------------------------------------------
KINDS = ("skills", "agents", "mcp")
KNOWN_POLICY = {"enabled", "onViolation"} | set(KINDS)
KNOWN_KIND = {"default", "allow", "deny", "areas"}
KNOWN_AREA_RULE = {"allow", "deny"}
ON_VIOLATION = ("deny", "ask", "warn")
DEFAULT_MODES = ("allow", "deny")

# The shipped block. Inert by construction: `is_active` is false for it, so the
# guard hook returns before it reads a manifest, and `resolve` allows everything.
DEFAULTS = {
    "enabled": True,
    "onViolation": "deny",
    "skills": {"default": "allow", "allow": [], "deny": [], "areas": {}},
    "agents": {"default": "allow", "allow": [], "deny": [], "areas": {}},
    "mcp": {"default": "allow", "allow": [], "deny": [], "areas": {}},
}

# The plugin's own namespace. Kept as a pattern as well as the concrete names
# below, so a command added after this release is required from the day it ships.
NAMESPACE = "audit:*"

_REQUIRED_CACHE = {}


# --- required set -------------------------------------------------------------
def _plugin_root(plugin_root=None):
    return plugin_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _stems(directory, suffix=".md", dirs=False):
    try:
        names = os.listdir(directory)
    except Exception:
        return []
    out = []
    for name in sorted(names):
        if dirs:
            if os.path.isdir(os.path.join(directory, name)) and not name.startswith("."):
                out.append(name)
        elif name.endswith(suffix) and not name.startswith("."):
            out.append(name[: -len(suffix)])
    return out


def required_names(plugin_root=None):
    """{kind: [name, ...]} — audit's own capabilities, READ OFF ITS OWN DIRECTORY.

    Commands, skills and agents are files; a list of them typed into this module
    would be a second statement of what the plugin ships, and the first thing it
    would do is go stale the next time a command is added. So `commands/*.md`,
    `skills/*/` and `agents/*.md` ARE the list.

    Both spellings are included — `audit:bug` as the Skill tool spells it, and the
    bare `bug` — because a policy written by hand may use either and a required
    capability that is required under only one of its names is not required.

    `mcp` is deliberately EMPTY. The plugin uses no MCP server of its own;
    `/audit:sync` drives whatever Azure DevOps server the project configured, and
    force-allowing a third-party server on the plugin's behalf would be this module
    deciding something that belongs to the project. Deny it and sync stops working
    — that is a legitimate choice, made in the open.
    """
    root = _plugin_root(plugin_root)
    if root in _REQUIRED_CACHE:
        return _REQUIRED_CACHE[root]
    skills = _stems(os.path.join(root, "commands")) + \
        _stems(os.path.join(root, "skills"), dirs=True)
    agents = _stems(os.path.join(root, "agents"))
    out = {
        "skills": sorted({"audit:%s" % s for s in skills} | set(skills)),
        "agents": sorted({"audit:%s" % a for a in agents} | set(agents)),
        "mcp": [],
    }
    _REQUIRED_CACHE[root] = out
    return out


# --- pattern matching ---------------------------------------------------------
def required_patterns(kind, plugin_root=None):
    """What counts as "audit's own" for `kind`: the namespace glob + the concrete
    names. The glob covers a command that shipped after this release; the concrete
    names cover the bare spellings, which no glob can."""
    if kind not in KINDS:
        return []
    names = required_names(plugin_root).get(kind) or []
    return ([NAMESPACE] if names else []) + list(names)


def matches(name, patterns):
    """The first pattern that matches `name`, or None. Case-sensitive by design."""
    if not isinstance(name, str) or not name:
        return None
    for pat in patterns or []:
        if not isinstance(pat, str) or not pat.strip():
            continue
        pat = pat.strip()
        if pat == name or fnmatch.fnmatchcase(name, pat):
            return pat
    return None


def _merge_kind(base, over):
    out = dict(base)
    if isinstance(over, dict):
        for k, v in over.items():
            out[k] = v
    return out


# --- policy config ------------------------------------------------------------
def policy_cfg(config):
    """The merged `policy` block, defaults filled in per kind. Never raises.

    Per kind rather than per key, the same shape as `_config.usage_cfg`: a project
    that writes `{"agents": {"default": "deny"}}` must still get `allow`, `deny` and
    `areas` — a missing list read as absent would be a KeyError in the hot path of a
    blocking guard.
    """
    try:
        out = {"enabled": DEFAULTS["enabled"], "onViolation": DEFAULTS["onViolation"]}
        block = (config or {}).get("policy")
        block = block if isinstance(block, dict) else {}
        if isinstance(block.get("enabled"), bool):
            out["enabled"] = block["enabled"]
        if block.get("onViolation") in ON_VIOLATION:
            out["onViolation"] = block["onViolation"]
        for kind in KINDS:
            merged = _merge_kind(DEFAULTS[kind], block.get(kind))
            if merged.get("default") not in DEFAULT_MODES:
                merged["default"] = DEFAULTS[kind]["default"]
            for key in ("allow", "deny"):
                if not isinstance(merged.get(key), list):
                    merged[key] = []
            if not isinstance(merged.get("areas"), dict):
                merged["areas"] = {}
            out[kind] = merged
        return out
    except Exception:
        return {k: (dict(v) if isinstance(v, dict) else v)
                for k, v in DEFAULTS.items()}


def _area_rules(kind_cfg, key, active_tags):
    """[(tag, pattern-list)] for the active areas that state `key`."""
    out = []
    for tag in active_tags or []:
        rule = (kind_cfg.get("areas") or {}).get(tag)
        if isinstance(rule, dict) and isinstance(rule.get(key), list):
            out.append((tag, rule[key]))
    return out


def is_active(policy):
    """Can this policy refuse anything at all?

    False for the shipped block, and for any policy that only ever says "allow" —
    allow lists cannot deny, so a policy with every `default: allow` and no `deny`
    entry anywhere has no verdict to make. The guard hook returns on this before
    reading a manifest, which is what keeps an inert policy free.
    """
    try:
        pol = policy if isinstance(policy, dict) else {}
        if pol.get("enabled") is False:
            return False
        for kind in KINDS:
            k = pol.get(kind) or {}
            if k.get("default") == "deny":
                return True
            if k.get("deny"):
                return True
            for rule in (k.get("areas") or {}).values():
                if isinstance(rule, dict) and rule.get("deny"):
                    return True
        return False
    except Exception:
        return False


# --- resolution ---------------------------------------------------------------
def resolve(policy, kind, name, active_tags=(), plugin_root=None):
    """The verdict for one capability.

    Returns {"verdict": "allow"|"violation", "kind", "name", "basis", "rule",
    "area"}. Never raises: on any internal error it allows, because a guard that
    crashes into a denial refuses work for a reason nobody can read.
    """
    out = {"verdict": "allow", "kind": kind, "name": name, "basis": "",
           "rule": None, "area": None}
    try:
        if kind not in KINDS or not name:
            out["basis"] = "not a governed capability"
            return out
        pol = policy if isinstance(policy, dict) else {}
        if pol.get("enabled") is False:
            out["basis"] = "policy.enabled is false"
            return out
        kcfg = pol.get(kind) if isinstance(pol.get(kind), dict) else {}

        # 1. audit's own components, whatever the policy says.
        hit = matches(name, required_patterns(kind, plugin_root))
        if hit:
            out["basis"] = ("required by audit (matches %r) - the panel refuses to "
                            "write a policy denying it" % hit)
            out["rule"] = hit
            return out

        # 2. deny beats allow, and one active area's deny is enough.
        hit = matches(name, kcfg.get("deny"))
        if hit:
            out.update(verdict="violation", rule=hit,
                       basis="policy.%s.deny lists %r" % (kind, hit))
            return out
        for tag, patterns in _area_rules(kcfg, "deny", active_tags):
            hit = matches(name, patterns)
            if hit:
                out.update(verdict="violation", rule=hit, area=tag,
                           basis="policy.%s.areas.%s.deny lists %r, and area %r has "
                                 "work in progress" % (kind, tag, hit, tag))
                return out

        # 3. an explicit allow, from the project or from any active area (union).
        hit = matches(name, kcfg.get("allow"))
        if hit:
            out.update(rule=hit, basis="policy.%s.allow lists %r" % (kind, hit))
            return out
        for tag, patterns in _area_rules(kcfg, "allow", active_tags):
            hit = matches(name, patterns)
            if hit:
                out.update(rule=hit, area=tag,
                           basis="policy.%s.areas.%s.allow lists %r, and area %r has "
                                 "work in progress" % (kind, tag, hit, tag))
                return out

        # 4. whatever the kind says about everything else.
        if kcfg.get("default") == "deny":
            out.update(verdict="violation",
                       basis="policy.%s.default is deny and nothing allows %r"
                             % (kind, name))
            return out
        out["basis"] = "policy.%s.default is allow" % kind
        return out
    except Exception as exc:                      # pragma: no cover - defensive
        out["basis"] = "policy could not be read (%s); allowing" % type(exc).__name__
        return out


def required_denials(policy, plugin_root=None):
    """[(kind, pattern, name), ...] — every rule that would refuse audit its own.

    The hook allows those anyway (step 1), so this is not a live hazard; it is a
    policy that does not mean what it says, and saying so is cheaper than letting
    someone believe they turned the orchestrator off through its own config. The
    honest version of "you cannot remove this quietly" is a message, not a silence.
    """
    out = []
    try:
        pol = policy if isinstance(policy, dict) else {}
        names = required_names(plugin_root)
        for kind in KINDS:
            kcfg = pol.get(kind) if isinstance(pol.get(kind), dict) else {}
            lists = [(None, kcfg.get("deny"))]
            for tag, rule in (kcfg.get("areas") or {}).items():
                if isinstance(rule, dict):
                    lists.append((tag, rule.get("deny")))
            for tag, patterns in lists:
                for pat in patterns or []:
                    for name in names.get(kind) or []:
                        if matches(name, [pat]):
                            where = kind if tag is None else "%s.areas.%s" % (kind, tag)
                            out.append((where, pat, name))
                            break
    except Exception:
        return out
    return out


# --- validation ---------------------------------------------------------------
def validate_policy(policy, where="policy"):
    """(findings, warnings) for a `policy` value. Never raises.

    FINDINGS are shapes that would be MISREAD — a kind that is not an object, a
    `default` outside the enum, an allow list that is not a list. Those are the
    typos with silent consequences: `"default": "denied"` falls back to allow, and a
    policy that silently allows is the opposite of what was written.

    WARNINGS are policies that are legal and do nothing: an allow list under
    `default: allow` (it can only repeat what is already true), and a deny rule
    aimed at audit's own components (step 1 overrides it).
    """
    findings, warnings = [], []
    if policy is None:
        return findings, warnings
    if not isinstance(policy, dict):
        findings.append("%s: must be an object {enabled, onViolation, skills, "
                        "agents, mcp}, got %s" % (where, type(policy).__name__))
        return findings, warnings
    for key in policy:
        ks = str(key)
        if ks not in KNOWN_POLICY and not ks.startswith(("_", "//")):
            warnings.append("%s: unknown key %r (known: %s)"
                            % (where, ks, ", ".join(sorted(KNOWN_POLICY))))
    if "enabled" in policy and not isinstance(policy["enabled"], bool):
        findings.append("%s.enabled: must be true or false (a bool, not a string)"
                        % where)
    if "onViolation" in policy and policy["onViolation"] not in ON_VIOLATION:
        findings.append("%s.onViolation: must be one of %s, got %r"
                        % (where, ", ".join(ON_VIOLATION), policy["onViolation"]))
    for kind in KINDS:
        if kind not in policy:
            continue
        kcfg = policy[kind]
        kwhere = "%s.%s" % (where, kind)
        if not isinstance(kcfg, dict):
            findings.append("%s: must be an object {default, allow, deny, areas}, "
                            "got %s" % (kwhere, type(kcfg).__name__))
            continue
        for key in kcfg:
            ks = str(key)
            if ks not in KNOWN_KIND and not ks.startswith(("_", "//")):
                warnings.append("%s: unknown key %r (known: %s)"
                                % (kwhere, ks, ", ".join(sorted(KNOWN_KIND))))
        if "default" in kcfg and kcfg["default"] not in DEFAULT_MODES:
            findings.append("%s.default: must be 'allow' or 'deny', got %r"
                            % (kwhere, kcfg["default"]))
        for key in ("allow", "deny"):
            _check_list(kcfg.get(key), "%s.%s" % (kwhere, key), key in kcfg,
                        findings)
        if kcfg.get("default", "allow") == "allow" and kcfg.get("allow"):
            warnings.append("%s.allow: has no effect while %s.default is 'allow' - "
                            "everything not denied is already allowed"
                            % (kwhere, kwhere))
        areas = kcfg.get("areas")
        if "areas" in kcfg and not isinstance(areas, dict):
            findings.append("%s.areas: must be an object {tag: {allow, deny}}, got %s"
                            % (kwhere, type(areas).__name__))
        elif isinstance(areas, dict):
            for tag, rule in areas.items():
                awhere = "%s.areas.%s" % (kwhere, tag)
                if not isinstance(tag, str) or not tag.strip():
                    findings.append("%s.areas: an area tag must be a non-empty name"
                                    % kwhere)
                    continue
                if not isinstance(rule, dict):
                    findings.append("%s: must be an object {allow, deny}, got %s"
                                    % (awhere, type(rule).__name__))
                    continue
                for key in rule:
                    ks = str(key)
                    if ks not in KNOWN_AREA_RULE and not ks.startswith(("_", "//")):
                        warnings.append("%s: unknown key %r (known: allow, deny)"
                                        % (awhere, ks))
                for key in ("allow", "deny"):
                    _check_list(rule.get(key), "%s.%s" % (awhere, key), key in rule,
                                findings)
    # A FINDING rather than a warning, and the grading is the point. This
    # validator reserves FINDING for a config that would be MISREAD, and that is
    # exactly what this is: the rule does not take effect (step 1 of `resolve`
    # overrules it), so whoever wrote it believes they turned the orchestrator's
    # own components off and did not. Refusing the file — which is what a finding
    # does, in the panel and at /audit preflight — says so once, loudly, instead of
    # leaving a line that reads like an enforcement nobody is getting.
    for where_kind, pat, name in required_denials(policy):
        findings.append("%s.%s.deny: %r matches %r, one of audit's own "
                        "capabilities, and would NOT take effect - the plugin's "
                        "components are not deniable through its own policy. "
                        "Remove the pattern, or disable the plugin if you want "
                        "them gone." % (where, where_kind, pat, name))
    return findings, warnings


def _check_list(value, where, present, findings):
    if not present:
        return
    if not isinstance(value, list):
        findings.append("%s: must be an array of name patterns, got %s"
                        % (where, type(value).__name__))
        return
    bad = [v for v in value if not isinstance(v, str) or not v.strip()]
    if bad:
        findings.append("%s: every entry must be a non-empty name pattern "
                        "(%d bad: %r)" % (where, len(bad), bad[:3]))


# --- tool -> capability mapping -----------------------------------------------
def capability_of(tool_name, tool_input):
    """(kind, name) for a tool call, or (None, "") when nothing here governs it.

    An `Agent`/`Task` call with no `subagent_type` is the general-purpose agent —
    that is what the tool does when the field is omitted, so naming it here is
    reading the contract rather than inventing a name. Left blank it would be the
    one subagent a `default: deny` policy could never catch.
    """
    tool = str(tool_name or "")
    ti = tool_input if isinstance(tool_input, dict) else {}
    if tool == "Skill":
        return ("skills", str(ti.get("skill") or "").strip())
    if tool in ("Task", "Agent"):
        return ("agents", str(ti.get("subagent_type") or "general-purpose").strip())
    if tool.startswith("mcp__"):
        return ("mcp", tool)
    return (None, "")


# --- selftest -----------------------------------------------------------------
def _selftest():
    ok = bad = 0

    def check(name, cond, detail=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("PASS %s" % name)
        else:
            bad += 1
            print("FAIL %s%s" % (name, (" :: %s" % detail) if detail else ""))

    # --- the shipped default is a policy that cannot refuse -----------------------
    inert = policy_cfg({})
    check("a1 the shipped block is inert - nothing about it can produce a violation",
          not is_active(inert))
    for _kind, _name in (("skills", "anything"), ("agents", "general-purpose"),
                         ("mcp", "mcp__whatever__do")):
        check("a2 %s/%s is allowed under the shipped default" % (_kind, _name),
              resolve(inert, _kind, _name)["verdict"] == "allow")
    check("a3 an absent policy block reads as the shipped one",
          policy_cfg(None) == policy_cfg({}) == policy_cfg({"policy": None}))
    check("a4 a partial kind still carries every list - a blocking guard must not "
          "meet a missing key in its hot path",
          policy_cfg({"policy": {"agents": {"default": "deny"}}})["agents"]
          == {"default": "deny", "allow": [], "deny": [], "areas": {}})
    check("a5 an unmergeable block degrades to the shipped one rather than raising",
          policy_cfg({"policy": "off"})["skills"]["default"] == "allow"
          and policy_cfg({"policy": {"skills": 3}})["skills"]["deny"] == [])
    check("a6 a nonsense `default` falls back to allow rather than being trusted",
          policy_cfg({"policy": {"mcp": {"default": "denied"}}})["mcp"]["default"]
          == "allow")
    check("a6b ...and a nonsense `onViolation` falls back to deny, which is the "
          "written intent: the file says refuse, and only the WORD for how is "
          "unreadable (the validator calls it a finding either way)",
          policy_cfg({"policy": {"onViolation": "block"}})["onViolation"] == "deny")
    check("a6c a list that is not a list becomes one, so the blocking guard's hot "
          "path never meets a string where it iterates patterns",
          policy_cfg({"policy": {"skills": {"allow": "just-this-one",
                                            "deny": 7}}})["skills"]
          == {"default": "allow", "allow": [], "deny": [], "areas": {}})
    check("a7 enabled:false is off, not inert-by-accident",
          is_active(policy_cfg({"policy": {"enabled": False,
                                           "skills": {"deny": ["x"]}}})) is False)
    check("a8 an allow list alone is still inert - an allow cannot refuse",
          not is_active(policy_cfg({"policy": {"skills": {"allow": ["only-this"]}}})))
    check("a9 ...but a deny list, or a deny default, is not",
          is_active(policy_cfg({"policy": {"skills": {"deny": ["x"]}}}))
          and is_active(policy_cfg({"policy": {"mcp": {"default": "deny"}}}))
          and is_active(policy_cfg({"policy": {"agents": {"areas": {
              "api": {"deny": ["x"]}}}}})))

    # --- matching ----------------------------------------------------------------
    check("m1 an exact name matches", matches("dataviz", ["dataviz"]) == "dataviz")
    check("m2 a glob matches, and reports which one",
          matches("mcp__github__get_issue", ["mcp__gitlab__*", "mcp__github__*"])
          == "mcp__github__*")
    check("m3 matching is CASE-SENSITIVE",
          matches("DataViz", ["dataviz"]) is None
          and matches("dataviz", ["Data*"]) is None)
    # m3 alone cannot fail on Linux or macOS: `fnmatch.fnmatch` normalises case
    # through `os.path.normcase`, which is the identity everywhere except Windows.
    # So the wrong function passes m3 on the machine most people run this on and
    # reddens only the Windows CI leg — a check whose failure mode is "somebody
    # else's build". This pins the function itself, which is decidable anywhere.
    with open(os.path.abspath(__file__), encoding="utf-8") as _fh:
        _self_src = _fh.read()
    # The forbidden call is ASSEMBLED at runtime, or this very line would contain
    # it and the check would fail against a correct file — the same trick
    # guard-edits.py uses to name a token it must not write literally.
    _case_folding_call = "fnmatch." + "fnmatch(name"
    check("m3b ...and the case-preserving matcher is the one actually called, "
          "which is the half a posix machine cannot observe: the other one would "
          "make one policy mean two things on two operating systems",
          "fnmatch.fnmatchcase(name, pat)" in _self_src
          and _case_folding_call not in _self_src)
    check("m4 junk entries are skipped, not crashed on",
          matches("x", [None, 3, "  ", "x"]) == "x" and matches("", ["*"]) is None
          and matches("x", None) is None)

    # --- required: read off the plugin's own directory ---------------------------
    req = required_names()
    check("r1 the required set is READ from the plugin tree, not typed out - "
          "commands, skills and agents are all there",
          "audit:next" in req["skills"] and "audit:bug" in req["skills"]
          and "audit:audit-codebase" in req["skills"]
          and "audit:audit-executor" in req["agents"]
          and "audit:audit-explorer" in req["agents"], repr(req))
    check("r2 both spellings, since a hand-written policy may use either",
          "next" in req["skills"] and "audit-reviewer" in req["agents"])
    check("r3 mcp is deliberately empty - the plugin owns no server, and "
          "force-allowing someone else's would be this module deciding for the "
          "project", req["mcp"] == [])
    check("r4 a directory with no plugin in it yields nothing rather than raising",
          required_names(os.path.join(os.path.dirname(__file__), "_nope"))
          == {"skills": [], "agents": [], "mcp": []})

    hard = {"enabled": True, "onViolation": "deny",
            "skills": {"default": "deny", "allow": [], "deny": [], "areas": {}},
            "agents": {"default": "deny", "allow": [], "deny": [], "areas": {}},
            "mcp": {"default": "deny", "allow": [], "deny": [], "areas": {}}}
    v = resolve(hard, "skills", "audit:next")
    check("r5 audit's own skill survives a default-deny policy, and says why",
          v["verdict"] == "allow" and "required by audit" in v["basis"], repr(v))
    v = resolve({"skills": {"default": "allow", "deny": ["audit:*"]}},
                "skills", "audit:status")
    check("r6 ...and an explicit deny of it does not take effect either",
          v["verdict"] == "allow" and "required by audit" in v["basis"], repr(v))
    v = resolve(hard, "agents", "audit:audit-executor")
    check("r7 the same for its agents", v["verdict"] == "allow", repr(v))
    v = resolve(hard, "mcp", "mcp__azure-devops__wit_query")
    check("r8 but NOT for the ADO server /audit:sync drives - denying it is a "
          "legitimate choice this module must not overrule",
          v["verdict"] == "violation", repr(v))

    # --- order: deny beats allow, default decides the rest -----------------------
    pol = policy_cfg({"policy": {"skills": {"default": "allow",
                                            "allow": ["risky"], "deny": ["risky"]}}})
    v = resolve(pol, "skills", "risky")
    check("o1 a name in BOTH lists is denied - deny beats allow",
          v["verdict"] == "violation" and "deny" in v["basis"], repr(v))
    pol = policy_cfg({"policy": {"agents": {"default": "deny",
                                            "allow": ["code-*"]}}})
    check("o2 default deny + an allow list is the 'deny all, then permit' shape",
          resolve(pol, "agents", "code-reviewer")["verdict"] == "allow"
          and resolve(pol, "agents", "random-agent")["verdict"] == "violation")
    v = resolve(pol, "agents", "random-agent")
    check("o3 the default's refusal names the default rather than a rule",
          "default is deny" in v["basis"] and v["rule"] is None, repr(v))
    check("o4 an unknown kind or an empty name is not a governed capability",
          resolve(pol, "tools", "x")["verdict"] == "allow"
          and resolve(pol, "agents", "")["verdict"] == "allow")
    check("o5 enabled:false allows even what the lists deny",
          resolve(policy_cfg({"policy": {"enabled": False,
                                         "skills": {"deny": ["x"]}}}),
                  "skills", "x")["verdict"] == "allow")

    # --- areas: scoped to the part of the repo actually being worked on ----------
    area_pol = policy_cfg({"policy": {"skills": {
        "default": "allow",
        "areas": {"api": {"deny": ["deploy-*"]},
                  "web": {"allow": ["storybook"]}}}}})
    check("e1 an area rule is silent while that area has no work in progress",
          resolve(area_pol, "skills", "deploy-prod")["verdict"] == "allow")
    v = resolve(area_pol, "skills", "deploy-prod", active_tags=["api"])
    check("e2 ...and refuses once it has, naming the area and why it counts",
          v["verdict"] == "violation" and v["area"] == "api"
          and "work in progress" in v["basis"], repr(v))
    deny_default = policy_cfg({"policy": {"skills": {
        "default": "deny",
        "areas": {"api": {"allow": ["python-conv"]},
                  "web": {"allow": ["ts-conv"]}}}}})
    check("e3 several active areas UNION their allow lists - the documented "
          "fail-open, so a repo working in two places at once is not caught "
          "between two policies neither of which was written for it",
          resolve(deny_default, "skills", "python-conv",
                  active_tags=["api", "web"])["verdict"] == "allow"
          and resolve(deny_default, "skills", "ts-conv",
                      active_tags=["api", "web"])["verdict"] == "allow"
          and resolve(deny_default, "skills", "python-conv",
                      active_tags=["web"])["verdict"] == "violation")
    both = policy_cfg({"policy": {"skills": {
        "default": "allow", "allow": ["shared"],
        "areas": {"api": {"deny": ["shared"]}}}}})
    check("e4 one area's deny outranks a project-wide allow - the intersection "
          "rule is the other way round from the allow union, on purpose",
          resolve(both, "skills", "shared", active_tags=["api"])["verdict"]
          == "violation"
          and resolve(both, "skills", "shared", active_tags=["web"])["verdict"]
          == "allow")

    # --- capability_of -----------------------------------------------------------
    check("c1 the Skill tool names a skill",
          capability_of("Skill", {"skill": " audit:next "}) == ("skills", "audit:next"))
    check("c2 Task and Agent both name a subagent",
          capability_of("Task", {"subagent_type": "explorer"}) == ("agents", "explorer")
          and capability_of("Agent", {"subagent_type": "explorer"})
          == ("agents", "explorer"))
    check("c3 an Agent call with no subagent_type IS the general-purpose agent - "
          "left blank it would be the one subagent a default-deny policy could "
          "never catch",
          capability_of("Agent", {}) == ("agents", "general-purpose"))
    check("c4 an MCP tool is governed by its whole name, so mcp__srv__* names a "
          "server", capability_of("mcp__github__get_issue", {})
          == ("mcp", "mcp__github__get_issue"))
    check("c5 anything else is not this hook's business",
          capability_of("Edit", {"file_path": "a"}) == (None, "")
          and capability_of(None, None) == (None, ""))

    # --- required_denials --------------------------------------------------------
    rd = required_denials({"skills": {"deny": ["audit:*"]}})
    check("d1 a deny aimed at audit's own namespace is reported once per rule",
          len(rd) == 1 and rd[0][0] == "skills" and rd[0][1] == "audit:*", repr(rd))
    rd = required_denials({"agents": {"areas": {"api": {"deny": ["*"]}}}})
    check("d2 ...including inside an area, named as such",
          len(rd) == 1 and rd[0][0] == "agents.areas.api", repr(rd))
    check("d3 a deny that touches nothing of audit's is not reported",
          required_denials({"skills": {"deny": ["dataviz", "mcp__x__*"]}}) == [])
    check("d4 hostile shapes report nothing rather than raising",
          required_denials(None) == [] and required_denials({"skills": 3}) == [])

    # --- validation --------------------------------------------------------------
    f, w = validate_policy(None)
    check("v1 an absent policy is silent", (f, w) == ([], []))
    f, w = validate_policy({"enabled": True, "onViolation": "ask",
                            "skills": {"default": "deny", "allow": ["a"],
                                       "deny": ["b"],
                                       "areas": {"api": {"allow": ["c"]}}}})
    check("v2 a good policy has no findings and no warnings", not f and not w,
          repr((f, w)))
    f, _ = validate_policy([])
    check("v3 a non-object policy is a finding", len(f) == 1)
    f, _ = validate_policy({"onViolation": "block"})
    check("v4 an onViolation outside the enum is a finding, not a silent deny",
          any("onViolation" in x for x in f), repr(f))
    f, _ = validate_policy({"enabled": "true"})
    check("v5 a string `enabled` is a finding (the `enforce` rule)",
          any("enabled" in x for x in f))
    f, _ = validate_policy({"skills": {"default": "denied"}})
    check("v6 a misspelled default is a finding - it would silently ALLOW, which "
          "is the opposite of what was written", any("default" in x for x in f))
    f, _ = validate_policy({"skills": {"deny": "one-name"}})
    check("v7 a bare string where the list goes is a finding",
          any("deny" in x for x in f))
    f, _ = validate_policy({"skills": {"allow": ["ok", ""]}})
    check("v8 an empty pattern in a list is a finding", any("allow" in x for x in f))
    f, _ = validate_policy({"agents": "deny-everything"})
    check("v9 a kind that is not an object is a finding", any("agents" in x for x in f))
    f, _ = validate_policy({"mcp": {"areas": []}})
    check("v10 a non-object areas map is a finding", any("areas" in x for x in f))
    f, _ = validate_policy({"mcp": {"areas": {"api": ["x"]}}})
    check("v11 ...and so is an area rule that is not an object", len(f) == 1, repr(f))
    _, w = validate_policy({"skills": {"typo": 1}})
    check("v12 an unknown key warns rather than failing", any("unknown" in x for x in w))
    _, w = validate_policy({"skills": {"default": "allow", "allow": ["x"]}})
    check("v13 an allow list under default:allow is legal and does NOTHING - "
          "saying so is the difference between a policy and a decoration",
          any("no effect" in x for x in w), repr(w))
    f, w = validate_policy({"skills": {"deny": ["audit:*"]}})
    check("v14 denying audit's own components is a FINDING, not a warning - the "
          "line does not take effect, so the file says something that is not true, "
          "and a saveable config that lies is worse than a refused one",
          any("not deniable" in x for x in f) and not any(
              "not deniable" in x for x in w), repr((f, w)))
    f, _ = validate_policy({"agents": {"areas": {"api": {"deny": ["audit-*"]}}}})
    check("v14b ...including inside an area rule, where it is easiest to miss",
          any("agents.areas.api.deny" in x for x in f), repr(f))
    _, w = validate_policy({"//comment": "why", "_note": 1})
    check("v15 the `//` comment convention this repo's template uses is not an "
          "unknown key", not w, repr(w))

    print(("ALL PASS: %d/%d cases passed" if not bad else
           "SELFTEST FAILED: %d/%d cases passed") % (ok, ok + bad))
    return 1 if bad else 0


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__.strip())
