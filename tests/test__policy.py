#!/usr/bin/env python3
"""
The cases for `_policy.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

TWO EXPRESSIONS NAMED THE FILE THEY LIVED IN, and a test file lives one directory
over, so each was re-pointed at the thing it actually meant rather than carried:

  * `m3b` reads the module's OWN SOURCE to pin which `fnmatch` function is called -
    the half a posix machine cannot observe by behaviour. Inline that was
    `os.path.abspath(__file__)`; here it is `os.path.abspath(M.__file__)`, which is
    the same file. Read literally it would have inspected this test instead, and
    the case would have passed while asserting nothing about `_policy.py`.
  * `r4` points `required_names` at a directory holding no plugin. Inline that was
    `scripts/_nope`; it is spelled off `_harness.SCRIPTS_DIR` here so the input is
    the same non-existent directory rather than "a non-existent directory beside
    whichever file this is".

`r1`/`r2`/`r3` call `M.required_names()` with NO argument, and its default plugin
root is computed inside `_policy.py` from its own location - so those genuinely
read the real `commands/`, `skills/` and `agents/` directories, and are unaffected
by where this file sits.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _policy as M                                # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the shipped default is a policy that cannot refuse -----------------------
    inert = M.policy_cfg({})
    check("a1 the shipped block is inert - nothing about it can produce a violation",
          not M.is_active(inert))
    for _kind, _name in (("skills", "anything"), ("agents", "general-purpose"),
                         ("mcp", "mcp__whatever__do")):
        check("a2 %s/%s is allowed under the shipped default" % (_kind, _name),
              M.resolve(inert, _kind, _name)["verdict"] == "allow")
    check("a3 an absent policy block reads as the shipped one",
          M.policy_cfg(None) == M.policy_cfg({}) == M.policy_cfg({"policy": None}))
    check("a4 a partial kind still carries every list - a blocking guard must not "
          "meet a missing key in its hot path",
          M.policy_cfg({"policy": {"agents": {"default": "deny"}}})["agents"]
          == {"default": "deny", "allow": [], "deny": [], "areas": {}})
    check("a5 an unmergeable block degrades to the shipped one rather than raising",
          M.policy_cfg({"policy": "off"})["skills"]["default"] == "allow"
          and M.policy_cfg({"policy": {"skills": 3}})["skills"]["deny"] == [])
    check("a6 a nonsense `default` falls back to allow rather than being trusted",
          M.policy_cfg({"policy": {"mcp": {"default": "denied"}}})["mcp"]["default"]
          == "allow")

    check("a6b ...and a nonsense `onViolation` falls back to deny, which is the "
          "written intent: the file says refuse, and only the WORD for how is "
          "unreadable (the validator calls it a finding either way)",
          M.policy_cfg({"policy": {"onViolation": "block"}})["onViolation"] == "deny")
    check("a6c a list that is not a list becomes one, so the blocking guard's hot "
          "path never meets a string where it iterates patterns",
          M.policy_cfg({"policy": {"skills": {"allow": "just-this-one",
                                              "deny": 7}}})["skills"]
          == {"default": "allow", "allow": [], "deny": [], "areas": {}})

    # a6d/a6e: `_merge_kind` copied the shipped block with `dict(base)`, so every
    # resolved policy handed out the SAME `allow`/`deny` lists that live in
    # DEFAULTS. One caller appending to its own result poisoned the engine for the
    # whole process - the panel and the doctor both resolve more than once. It
    # survived because the only aliasing case in the tree asked the question of
    # `_config.load()`, which deep-copied on the way out and hid this.
    #
    # A sentinel that could never be a real capability name, appended to the list a
    # DENY consults: if the copy is shallow again, a6e's independent call refuses it.
    _al = M.policy_cfg({})
    _al["skills"]["deny"].append("ALIAS-PROBE-*")
    _al["skills"]["areas"]["probe"] = {"deny": ["ALIAS-PROBE-*"]}
    check("a6d mutating a resolved policy does not reach the engine's defaults",
          "ALIAS-PROBE-*" not in M.DEFAULTS["skills"]["deny"]
          and "probe" not in M.DEFAULTS["skills"]["areas"])
    check("a6e ...nor the next call, which is the one a long-lived panel makes",
          M.policy_cfg({})["skills"]["deny"] == []
          and M.policy_cfg({})["skills"]["areas"] == {}
          and M.resolve(M.policy_cfg({}), "skills",
                        "ALIAS-PROBE-x")["verdict"] != "violation")
    check("a7 enabled:false is off, not inert-by-accident",
          M.is_active(M.policy_cfg({"policy": {"enabled": False,
                                               "skills": {"deny": ["x"]}}})) is False)
    check("a8 an allow list alone is still inert - an allow cannot refuse",
          not M.is_active(M.policy_cfg({"policy": {"skills": {"allow": ["only-this"]}}})))
    check("a9 ...but a deny list, or a deny default, is not",
          M.is_active(M.policy_cfg({"policy": {"skills": {"deny": ["x"]}}}))
          and M.is_active(M.policy_cfg({"policy": {"mcp": {"default": "deny"}}}))
          and M.is_active(M.policy_cfg({"policy": {"agents": {"areas": {
              "api": {"deny": ["x"]}}}}})))

    # --- matching ----------------------------------------------------------------
    check("m1 an exact name matches", M.matches("dataviz", ["dataviz"]) == "dataviz")
    check("m2 a glob matches, and reports which one",
          M.matches("mcp__github__get_issue", ["mcp__gitlab__*", "mcp__github__*"])
          == "mcp__github__*")
    check("m3 matching is CASE-SENSITIVE",
          M.matches("DataViz", ["dataviz"]) is None
          and M.matches("dataviz", ["Data*"]) is None)
    # m3 alone cannot fail on Linux or macOS: `fnmatch.fnmatch` normalises case
    # through `os.path.normcase`, which is the identity everywhere except Windows.
    # So the wrong function passes m3 on the machine most people run this on and
    # reddens only the Windows CI leg — a check whose failure mode is "somebody
    # else's build". This pins the function itself, which is decidable anywhere.
    with open(os.path.abspath(M.__file__), encoding="utf-8") as _fh:
        _self_src = _fh.read()
    # The forbidden call is ASSEMBLED rather than written out. That was once
    # load-bearing — the line lived in the very file being read — and is kept now
    # that the read is of `_policy.py` from here, because the alternative is a
    # literal that would break the case again the day anything reads this file.
    _case_folding_call = "fnmatch." + "fnmatch(name"
    check("m3b ...and the case-preserving matcher is the one actually called, "
          "which is the half a posix machine cannot observe: the other one would "
          "make one policy mean two things on two operating systems",
          "fnmatch.fnmatchcase(name, pat)" in _self_src
          and _case_folding_call not in _self_src)
    check("m4 junk entries are skipped, not crashed on",
          M.matches("x", [None, 3, "  ", "x"]) == "x" and M.matches("", ["*"]) is None
          and M.matches("x", None) is None)

    # --- required: read off the plugin's own directory ---------------------------
    req = M.required_names()
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
          M.required_names(os.path.join(_harness.SCRIPTS_DIR, "_nope"))
          == {"skills": [], "agents": [], "mcp": []})

    hard = {"enabled": True, "onViolation": "deny",
            "skills": {"default": "deny", "allow": [], "deny": [], "areas": {}},
            "agents": {"default": "deny", "allow": [], "deny": [], "areas": {}},
            "mcp": {"default": "deny", "allow": [], "deny": [], "areas": {}}}
    v = M.resolve(hard, "skills", "audit:next")
    check("r5 audit's own skill survives a default-deny policy, and says why",
          v["verdict"] == "allow" and "required by audit" in v["basis"], repr(v))
    v = M.resolve({"skills": {"default": "allow", "deny": ["audit:*"]}},
                  "skills", "audit:status")
    check("r6 ...and an explicit deny of it does not take effect either",
          v["verdict"] == "allow" and "required by audit" in v["basis"], repr(v))
    v = M.resolve(hard, "agents", "audit:audit-executor")
    check("r7 the same for its agents", v["verdict"] == "allow", repr(v))
    v = M.resolve(hard, "mcp", "mcp__azure-devops__wit_query")
    check("r8 but NOT for the ADO server /audit:sync drives - denying it is a "
          "legitimate choice this module must not overrule",
          v["verdict"] == "violation", repr(v))

    # --- order: deny beats allow, default decides the rest -----------------------
    pol = M.policy_cfg({"policy": {"skills": {"default": "allow",
                                              "allow": ["risky"],
                                              "deny": ["risky"]}}})
    v = M.resolve(pol, "skills", "risky")
    check("o1 a name in BOTH lists is denied - deny beats allow",
          v["verdict"] == "violation" and "deny" in v["basis"], repr(v))
    pol = M.policy_cfg({"policy": {"agents": {"default": "deny",
                                              "allow": ["code-*"]}}})
    check("o2 default deny + an allow list is the 'deny all, then permit' shape",
          M.resolve(pol, "agents", "code-reviewer")["verdict"] == "allow"
          and M.resolve(pol, "agents", "random-agent")["verdict"] == "violation")
    v = M.resolve(pol, "agents", "random-agent")
    check("o3 the default's refusal names the default rather than a rule",
          "default is deny" in v["basis"] and v["rule"] is None, repr(v))
    check("o4 an unknown kind or an empty name is not a governed capability",
          M.resolve(pol, "tools", "x")["verdict"] == "allow"
          and M.resolve(pol, "agents", "")["verdict"] == "allow")
    check("o5 enabled:false allows even what the lists deny",
          M.resolve(M.policy_cfg({"policy": {"enabled": False,
                                             "skills": {"deny": ["x"]}}}),
                    "skills", "x")["verdict"] == "allow")

    # --- areas: scoped to the part of the repo actually being worked on ----------
    area_pol = M.policy_cfg({"policy": {"skills": {
        "default": "allow",
        "areas": {"api": {"deny": ["deploy-*"]},
                  "web": {"allow": ["storybook"]}}}}})
    check("e1 an area rule is silent while that area has no work in progress",
          M.resolve(area_pol, "skills", "deploy-prod")["verdict"] == "allow")
    v = M.resolve(area_pol, "skills", "deploy-prod", active_tags=["api"])
    check("e2 ...and refuses once it has, naming the area and why it counts",
          v["verdict"] == "violation" and v["area"] == "api"
          and "work in progress" in v["basis"], repr(v))
    deny_default = M.policy_cfg({"policy": {"skills": {
        "default": "deny",
        "areas": {"api": {"allow": ["python-conv"]},
                  "web": {"allow": ["ts-conv"]}}}}})
    check("e3 several active areas UNION their allow lists - the documented "
          "fail-open, so a repo working in two places at once is not caught "
          "between two policies neither of which was written for it",
          M.resolve(deny_default, "skills", "python-conv",
                    active_tags=["api", "web"])["verdict"] == "allow"
          and M.resolve(deny_default, "skills", "ts-conv",
                        active_tags=["api", "web"])["verdict"] == "allow"
          and M.resolve(deny_default, "skills", "python-conv",
                        active_tags=["web"])["verdict"] == "violation")
    both = M.policy_cfg({"policy": {"skills": {
        "default": "allow", "allow": ["shared"],
        "areas": {"api": {"deny": ["shared"]}}}}})
    check("e4 one area's deny outranks a project-wide allow - the intersection "
          "rule is the other way round from the allow union, on purpose",
          M.resolve(both, "skills", "shared", active_tags=["api"])["verdict"]
          == "violation"
          and M.resolve(both, "skills", "shared", active_tags=["web"])["verdict"]
          == "allow")

    # --- capability_of -----------------------------------------------------------
    check("c1 the Skill tool names a skill",
          M.capability_of("Skill", {"skill": " audit:next "})
          == ("skills", "audit:next"))
    check("c2 Task and Agent both name a subagent",
          M.capability_of("Task", {"subagent_type": "explorer"})
          == ("agents", "explorer")
          and M.capability_of("Agent", {"subagent_type": "explorer"})
          == ("agents", "explorer"))
    check("c3 an Agent call with no subagent_type IS the general-purpose agent - "
          "left blank it would be the one subagent a default-deny policy could "
          "never catch",
          M.capability_of("Agent", {}) == ("agents", "general-purpose"))
    check("c4 an MCP tool is governed by its whole name, so mcp__srv__* names a "
          "server", M.capability_of("mcp__github__get_issue", {})
          == ("mcp", "mcp__github__get_issue"))
    check("c5 anything else is not this hook's business",
          M.capability_of("Edit", {"file_path": "a"}) == (None, "")
          and M.capability_of(None, None) == (None, ""))

    # --- required_denials --------------------------------------------------------
    rd = M.required_denials({"skills": {"deny": ["audit:*"]}})
    check("d1 a deny aimed at audit's own namespace is reported once per rule",
          len(rd) == 1 and rd[0][0] == "skills" and rd[0][1] == "audit:*", repr(rd))
    rd = M.required_denials({"agents": {"areas": {"api": {"deny": ["*"]}}}})
    check("d2 ...including inside an area, named as such",
          len(rd) == 1 and rd[0][0] == "agents.areas.api", repr(rd))
    check("d3 a deny that touches nothing of audit's is not reported",
          M.required_denials({"skills": {"deny": ["dataviz", "mcp__x__*"]}}) == [])
    check("d4 hostile shapes report nothing rather than raising",
          M.required_denials(None) == [] and M.required_denials({"skills": 3}) == [])

    # --- dead patterns: a rule that names nothing installed (v0.38) --------------
    dp = M.dead_patterns({"skills": {"deny": ["zzz-*"]}}, "skills", ["real-skill"])
    check("i1 a pattern matching nothing in the inventory and nothing of audit's "
          "own is dead, reported with its list",
          dp == [(None, "deny", "zzz-*")], repr(dp))
    check("i2 a pattern the inventory satisfies is not dead",
          M.dead_patterns({"skills": {"deny": ["real-*"]}}, "skills",
                          ["real-skill"]) == [])
    check("i3 a pattern that names only audit's own components is not dead - the "
          "plugin ships them, so they are always installed; for deny that is "
          "already the required-denial finding, for allow a legal no-op, and "
          "either way this check is about the INVENTORY",
          M.dead_patterns({"skills": {"deny": ["audit:*"],
                                      "allow": ["audit:next"]}}, "skills", []) == [])
    dp = M.dead_patterns({"agents": {"areas": {"api": {"deny": ["ghost-*"]}}}},
                         "agents", ["real-agent"])
    check("i4 an area rule's dead pattern carries its area tag",
          dp == [("api", "deny", "ghost-*")], repr(dp))
    check("i5 allow lists are walked too - a dead allow is as quiet a no-op as a "
          "dead deny, whatever the default says",
          M.dead_patterns({"skills": {"allow": ["ghost-*"]}}, "skills",
                          ["real-skill"]) == [(None, "allow", "ghost-*")])
    check("i6 mcp is matched BOTH ways against the server stand-ins: a rule for "
          "one tool of an installed server is alive, a rule for an absent server "
          "is dead",
          M.dead_patterns({"mcp": {"deny": ["mcp__srv__one_tool"]}}, "mcp",
                          ["mcp__srv__*"]) == []
          and M.dead_patterns({"mcp": {"deny": ["mcp__gone__*"]}}, "mcp",
                              ["mcp__srv__*"])
          == [(None, "deny", "mcp__gone__*")])
    check("i7 deny before allow, project before area - resolve's own reading "
          "order, so a report renders top-down as the block is read",
          M.dead_patterns({"skills": {"allow": ["g2-*"], "deny": ["g1-*"],
                                      "areas": {"b": {"deny": ["g4-*"]},
                                                "a": {"allow": ["g3-*"]}}}},
                          "skills", ["real-skill"])
          == [(None, "deny", "g1-*"), (None, "allow", "g2-*"),
              ("a", "allow", "g3-*"), ("b", "deny", "g4-*")])
    check("i8 hostile shapes report nothing rather than raising, and junk "
          "entries are skipped, not judged",
          M.dead_patterns(None, "skills", ["x"]) == []
          and M.dead_patterns({"skills": 3}, "skills", ["x"]) == []
          and M.dead_patterns({"skills": {"deny": [7, "  "]}}, "skills", ["x"]) == []
          and M.dead_patterns({"tools": {"deny": ["a"]}}, "tools", ["x"]) == [])

    # --- validation --------------------------------------------------------------
    f, w = M.validate_policy(None)
    check("v1 an absent policy is silent", (f, w) == ([], []))
    f, w = M.validate_policy({"enabled": True, "onViolation": "ask",
                              "skills": {"default": "deny", "allow": ["a"],
                                         "deny": ["b"],
                                         "areas": {"api": {"allow": ["c"]}}}})
    check("v2 a good policy has no findings and no warnings", not f and not w,
          repr((f, w)))
    f, _ = M.validate_policy([])
    check("v3 a non-object policy is a finding", len(f) == 1)
    f, _ = M.validate_policy({"onViolation": "block"})
    check("v4 an onViolation outside the enum is a finding, not a silent deny",
          any("onViolation" in x for x in f), repr(f))
    f, _ = M.validate_policy({"enabled": "true"})
    check("v5 a string `enabled` is a finding (the `enforce` rule)",
          any("enabled" in x for x in f))
    f, _ = M.validate_policy({"skills": {"default": "denied"}})
    check("v6 a misspelled default is a finding - it would silently ALLOW, which "
          "is the opposite of what was written", any("default" in x for x in f))
    f, _ = M.validate_policy({"skills": {"deny": "one-name"}})
    check("v7 a bare string where the list goes is a finding",
          any("deny" in x for x in f))
    f, _ = M.validate_policy({"skills": {"allow": ["ok", ""]}})
    check("v8 an empty pattern in a list is a finding", any("allow" in x for x in f))
    f, _ = M.validate_policy({"agents": "deny-everything"})
    check("v9 a kind that is not an object is a finding",
          any("agents" in x for x in f))
    f, _ = M.validate_policy({"mcp": {"areas": []}})
    check("v10 a non-object areas map is a finding", any("areas" in x for x in f))
    f, _ = M.validate_policy({"mcp": {"areas": {"api": ["x"]}}})
    check("v11 ...and so is an area rule that is not an object", len(f) == 1, repr(f))
    _, w = M.validate_policy({"skills": {"typo": 1}})
    check("v12 an unknown key warns rather than failing",
          any("unknown" in x for x in w))
    _, w = M.validate_policy({"skills": {"default": "allow", "allow": ["x"]}})
    check("v13 an allow list under default:allow is legal and does NOTHING - "
          "saying so is the difference between a policy and a decoration",
          any("no effect" in x for x in w), repr(w))
    f, w = M.validate_policy({"skills": {"deny": ["audit:*"]}})
    check("v14 denying audit's own components is a FINDING, not a warning - the "
          "line does not take effect, so the file says something that is not true, "
          "and a saveable config that lies is worse than a refused one",
          any("not deniable" in x for x in f) and not any(
              "not deniable" in x for x in w), repr((f, w)))
    f, _ = M.validate_policy({"agents": {"areas": {"api": {"deny": ["audit-*"]}}}})
    check("v14b ...including inside an area rule, where it is easiest to miss",
          any("agents.areas.api.deny" in x for x in f), repr(f))
    _, w = M.validate_policy({"//comment": "why", "_note": 1})
    check("v15 the `//` comment convention this repo's template uses is not an "
          "unknown key", not w, repr(w))

    # (g) the 0.35 guide rename: a pattern for the old id is legal and matches
    # nothing - the quiet no-op this validator exists to name.
    _, w = M.validate_policy({"agents": {"allow": ["audit:audit-guide"]}})
    check("g1 a pattern naming the pre-0.35 guide id gets a rename warning",
          any("audit:guide" in x and "audit-guide" in x for x in w), repr(w))
    _, w = M.validate_policy({"agents": {"areas": {"api": {
        "deny": ["*audit-guide*"]}}}})
    check("g2 ...including inside an area rule, glob variants too",
          any("areas.api" in x and "audit:guide" in x for x in w), repr(w))
    _, w = M.validate_policy({"agents": {"allow": ["audit:guide", "myteam-*"]}})
    check("g3 the NEW id and unrelated patterns stay silent",
          not any("audit-guide" in x for x in w), repr(w))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__policy.py --selftest\n")
    raise SystemExit(2)
