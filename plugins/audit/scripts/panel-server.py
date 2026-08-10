#!/usr/bin/env python3
"""
/audit:panel — an ephemeral, on-demand local control panel for the audit plugin.

Launched by the /audit:panel command; NOT a persistent service. It serves a
self-contained themeable UI on 127.0.0.1 and exposes a tiny JSON API that:
  - reads/writes .claude/audit.config.json (validated against validate-config.py),
  - reads the manifest and writes back ONLY the composition levers
    (meta.reviewSkill / meta.buildCommands, phase.review.model, task.model/skills)
    — never structural CRUD — validated via validate-manifest.py before write,
  - discovers the skills & agents actually available (project + user + plugins)
    so you pick from real building blocks instead of typing names blindly.

Dependency-free (stdlib only). Reuses the plugin's own pure cores by importlib
(validate-manifest.validate, audit-status.rollup) — no logic is duplicated.

Safety: localhost bind + Host-header check + a random per-launch token required on
every /api call; writes are refused if the resolved path escapes the project dir;
manifest writes are refused while <manifestPath>.lock is held; all writes are
atomic (temp + os.replace).

Usage:
  python3 panel-server.py --project <dir> [--port N] [--no-open]
  python3 panel-server.py --selftest

Exit: Ctrl-C stops the server. --selftest returns 0/1.
"""
import argparse
import atexit
import contextlib
import io
import json
import os
import pathlib
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_REL = ".claude/audit.config.json"

sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _ui_theme as _theme   # noqa: E402  (tokens + labels shared with the report)
import _areas               # noqa: E402  (meta.areas registry + shared resolution)
import _policy              # noqa: E402  (the capability policy + its resolution)
import _help                # noqa: E402  (schema-sourced field help + concept topics)
import _loader               # noqa: E402  (the one path-importlib loader for scripts/)
import _panel_ui             # noqa: E402  (UI_HTML's markup/CSS/JS, off disk as real files)
import _panel_settings       # noqa: E402  (settings-form schema + write allow-lists)
import _panel_discovery      # noqa: E402  (skills/agents/MCP registry scan)

# The settings-form schema and the write-path allow-lists are settings-shape
# knowledge, not server plumbing — they live in _panel_settings.py (P12.1).
# Aliased here so every downstream reference in this file (the substitution
# chain below, `_composition_changes`, `_reject_unknown`, the selftest) keeps
# working unchanged.
_META_KEYS = _panel_settings._META_KEYS
_META_API_ONLY = _panel_settings._META_API_ONLY
_META_FORM_KEYS = _panel_settings._META_FORM_KEYS
_PHASE_KEYS = _panel_settings._PHASE_KEYS
_TASK_KEYS = _panel_settings._TASK_KEYS
FIELD_HELP = _panel_settings.FIELD_HELP
COMPOSITION_HELP = _panel_settings.COMPOSITION_HELP
SETTINGS_GROUPS = _panel_settings.SETTINGS_GROUPS
_settings_paths = _panel_settings._settings_paths
_cfg_enums = _panel_settings._cfg_enums

# The skills/agents/MCP registry scan is a read-only filesystem walk, not server
# plumbing — it lives in _panel_discovery.py (P12.2). Aliased here so every
# downstream reference (the /api/registry route, `policy_state`'s own preview
# call, the selftest's fixture-dir cases) keeps working unchanged.
_front_matter = _panel_discovery._front_matter
_fm_of = _panel_discovery._fm_of
_entry = _panel_discovery._entry
_scan_skills = _panel_discovery._scan_skills
_scan_agents = _panel_discovery._scan_agents
_plugin_bases = _panel_discovery._plugin_bases
discover = _panel_discovery.discover
_local_plugin_bases = _panel_discovery._local_plugin_bases
_mcp_names = _panel_discovery._mcp_names


def _src_of_this_file():
    """This module's own source — for the selftests that must assert a server-side
    construct (a route, a call order) rather than a rendered string."""
    with open(__file__, encoding="utf-8") as fh:
        return fh.read()


# --- lazy import of the plugin's own pure cores (hyphenated filenames) ----------
def _load(modname, path):
    """Thin per-call wrapper: callers here pass an explicit modname (the file is
    hyphenated and not otherwise importable). Delegates to `_loader`, the one
    shared path-importlib loader — see its docstring for the caching policy."""
    return _loader.load(path, modname=modname)


_VM = _VC = _AS = _CFG = None


def _cores():
    """Load (once) validate-manifest, validate-config, audit-status, _config."""
    global _VM, _VC, _AS, _CFG
    if _VM is None:
        _VM = _loader.load_script("validate-manifest.py",
                                   modname="audit_validate_manifest")
        _VC = _loader.load_script("validate-config.py",
                                   modname="audit_validate_config")
        _AS = _loader.load_script("audit-status.py", modname="audit_status")
        _CFG = _loader.load_hooks_config(modname="audit__config")
    return _VM, _VC, _AS, _CFG


def _defaults():
    return _cores()[3].DEFAULTS


# --- path safety ----------------------------------------------------------------
def _within(project, path):
    """True iff `path` resolves inside `project` (no ../ escape, no symlink out)."""
    proj = os.path.realpath(project)
    tgt = os.path.realpath(path)
    return tgt == proj or tgt.startswith(proj + os.sep)


def _config_path(project):
    return os.path.join(project, CONFIG_REL)


def _declared_as_of(config):
    """Did the PROJECT set `usage.pricingAsOf`, or is the effective value a default?

    `usage_cfg()` merges `DEFAULTS`, so `ucfg["pricingAsOf"]` is almost never absent
    — it falls back to the default table's date. Rendering that as the rate basis
    would present a date this project never chose as though it had, which is the
    manufactured basis `render-report._usage_context` refuses for the same reason.
    The panel needs the raw config to tell the two apart, so it reports the fact
    separately rather than making the client guess from a value that is always set.
    """
    block = (config or {}).get("usage")
    return isinstance(block, dict) and isinstance(block.get("pricingAsOf"), str) \
        and bool(block["pricingAsOf"].strip())


def _manifest_path(project, config):
    mp = (config or {}).get("manifestPath") or _defaults()["manifestPath"]
    return os.path.normpath(os.path.join(project, mp))


# --- who is looking at this panel -------------------------------------------------
_VIEWER_CACHE = {}


def _viewer(project, config):
    """Who is driving the panel: `{author, mode}`.

    Resolved by `usage_ledger.resolve_author` — the SAME function, reading the same
    `usage.authorMode` — rather than by asking git here. The two names have to be
    one string: the Usage tab offers a "my spend" filter that compares this value
    with the `author` column the ledger writes, and a second implementation would
    produce a filter that matches nothing on any project where the two disagreed
    (mode `hash`, say, or a repo-local `user.email`).

    `mode: none` is a real answer, not a failure: it means this project chose not
    to record who spent what, and the panel says so rather than inventing a name.

    Cached per (project, mode) because resolve_author shells out to git and
    build_state runs on every /api/state.
    """
    _, _, _, cfg_mod = _cores()
    mode = str((cfg_mod.usage_cfg(config) or {}).get("authorMode") or "email")
    key = (os.path.realpath(project), mode)
    if key not in _VIEWER_CACHE:
        author = None
        try:
            ul = _loader.load_script("usage_ledger.py", modname="audit_usage_ledger")
            author = ul.resolve_author(project, mode)
        except Exception:
            author = None
        _VIEWER_CACHE[key] = {"author": author, "mode": mode}
    return _VIEWER_CACHE[key]


def _atomic_write_json(path, obj):
    """Thin delegation to the plugin's ONE atomic-JSON-write implementation
    (_manifest_io.atomic_write_json) — ensure_ascii=False keeps this module's
    existing byte shape unchanged."""
    _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)


def _read_json(path):
    """Thin delegation to the plugin's ONE JSON reader (_manifest_io.read_json)."""
    return _mio.read_json(path)


# --- state (read) ---------------------------------------------------------------
def read_config(project):
    try:
        obj = _read_json(_config_path(project))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


# A phase's `area` -> its tags. One implementation, in `_areas`, shared with
# audit-status: this file and that one each had their own copy of the same six
# lines, and the day one of them learned something (trimming, de-duplication, the
# registry lookup) the panel and the terminal would have disagreed about which
# phases are in an area.
_areas_of = _areas.areas_of


def _bugs_view(manifest):
    """The bug rows the Overview lists, one per bug, already resolved.

    `status` here is the EFFECTIVE status — the same value `rollup()` counts in
    `bugs.byStatus`, computed by the same function — so a reader who clicks the
    "Fixed 2" pill gets exactly two rows. Deriving it a second time in JavaScript
    would be a second implementation of the bug<->task rule (a bug materialized
    into a task reads `fixed` once that task is done), and two implementations
    that can disagree is precisely how the panel's counts and its lists drift.
    `reported` keeps what the manifest actually stores, so a bug whose status is
    inherited from its task can say so instead of looking hand-edited."""
    _, _, as_, _ = _cores()
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    task_by_id = {t["id"]: t for p in phases for t in (p.get("tasks") or [])
                  if isinstance(t, dict) and t.get("id")}
    task_phase = {t["id"]: p.get("id") for p in phases for t in (p.get("tasks") or [])
                  if isinstance(t, dict) and t.get("id")}
    out = []
    for b in (manifest.get("bugs") or []):
        if not isinstance(b, dict):
            continue
        eff = as_.effective_bug_status(b, task_by_id)
        out.append({
            "id": b.get("id"), "title": b.get("title"),
            "status": eff,
            "reported": b.get("status"),
            "severity": b.get("severity"),
            # `open` and `high` are decided HERE, by the same two rules the rollup's
            # `open` / `openHighSeverity` counts use — CLOSED_BUG and the
            # high-or-worse severity set, which knows that critical, blocker, sev1
            # and p0 all mean high. A regex in the browser would be a third opinion
            # on the same question, and the "High severity, open" pill would
            # eventually count a different set than the list it filters to.
            "open": eff not in as_.CLOSED_BUG,
            "high": as_._is_high_severity(b.get("severity")),
            "taskId": b.get("taskId"),
            "phaseId": task_phase.get(b.get("taskId")),
            "reportedAt": b.get("reportedAt"),
        })
    return out


def _skills_of(task):
    """A task's skills as the panel SHOWS them: a list, always.

    Absent and `null` both render as an empty chip row, so this is the value the
    reader is looking at — which is what a change row has to be written against.
    Reading the raw `None` here instead would be a truer reading of the file and a
    false mismatch against the form: adding one skill would make the client say
    `[] -> [a]` and the server `null -> [a]`, and the panel would warn about a
    disagreement that is only a normalisation.
    """
    v = (task or {}).get("skills")
    return v if isinstance(v, list) else []


def _composition_view(manifest):
    meta = manifest.get("meta") or {}
    phases_out, tasks_out = [], []
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        review = ph.get("review") if isinstance(ph.get("review"), dict) else {}
        phases_out.append({"id": ph.get("id"), "title": ph.get("title"),
                           "status": ph.get("status"), "reviewModel": review.get("model"),
                           "area": _areas_of(ph.get("area")), "reviewSkill": ph.get("reviewSkill")})
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            tasks_out.append({
                "id": t.get("id"), "title": t.get("title"),
                "phaseId": ph.get("id"), "status": t.get("status"),
                "model": t.get("model"),
                "skills": _skills_of(t),
            })
    return {
        "meta": {"reviewSkill": meta.get("reviewSkill"),
                 "buildCommands": meta.get("buildCommands")},
        "phases": phases_out, "tasks": tasks_out,
    }


def areas_state(project):
    """`GET /api/areas` — the registry, and every tag the phases actually use.

    Both halves, because the two disagree in both directions and each disagreement
    is worth seeing: a tag no entry covers resolves to no reviewer and no skills
    (usually a typo), and a registered area no phase uses is either a plan that has
    not been written yet or a rename that only got done on one side.

    Every verdict here comes from `_areas` — the same module the validator, the
    doctor and the status renderer resolve through — so this endpoint cannot
    develop its own opinion about what is registered.
    """
    config = read_config(project)
    mpath = _manifest_path(project, config)
    out = {"path": os.path.relpath(mpath, project) if _within(project, mpath)
           else None,
           "areas": {}, "tags": [], "findings": [], "warnings": []}
    if not _within(project, mpath):
        out["findings"] = ["refused: manifest path escapes project"]
        return out
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:
        out["findings"] = ["cannot read manifest: %s" % exc]
        return out
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    stored = meta.get("areas")
    out["areas"] = stored if isinstance(stored, dict) else {}
    f, w = _areas.validate_registry(stored)
    out["findings"], out["warnings"] = f, w
    reg = _areas.registry(manifest)
    used = {}
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for tag in _areas.areas_of(ph.get("area")):
            used.setdefault(tag, []).append(ph.get("id"))
    for tag in sorted(set(reg) | set(used)):
        entry = reg.get(tag) or {}
        root = _areas.root_of(entry)
        out["tags"].append({
            "tag": tag,
            "registered": tag in reg,
            "phases": used.get(tag, []),
            "root": root or None,
            # Resolved here rather than in the browser: the panel already learned
            # once (c6) that a value it SHOWS and a value the server computes have
            # to come from one function or the two eventually disagree.
            "rootExists": bool(root) and os.path.isdir(os.path.join(project, root)),
            "description": entry.get("description"),
            "reviewSkill": entry.get("reviewSkill"),
            "skills": entry.get("skills") if isinstance(entry.get("skills"), list)
            else [],
        })
    return out


JOURNAL_PAGE = 200


def journal_state(project, limit=JOURNAL_PAGE):
    """`GET /api/journal` — the recent rows, and whether the chain still holds.

    Both halves in one response, because either alone misleads. A list of rows with
    no verdict invites the reader to trust it; a verdict with no rows is a claim
    about something they cannot see. The verdict comes from `audit-journal.verify`
    — the same function the doctor and the CLI call — so the panel cannot develop
    its own opinion about what counts as intact.

    Read-only, and it stays that way: the journal is written by the writers it
    records, never by a request for it.
    """
    out = {"enabled": True, "dir": None, "rows": [], "verify": None,
           "available": False}
    mod = _journalmod()
    if mod is None:
        # This install has no journal module at all (pre-0.29). Reported rather
        # than 404'd: "there is no journal here" is an answer.
        return out
    config = read_config(project)
    out["enabled"] = bool(mod.enabled(config))
    try:
        res = mod.verify(project, config)
        out["available"] = True
        out["verify"] = {k: res[k] for k in
                         ("ok", "exists", "rows", "findings", "warnings")}
        out["dir"] = (os.path.relpath(res["dir"], project)
                      if _within(project, res["dir"]) else None)
        rows = mod.read_all(project, config)
        out["rows"] = list(reversed(rows[-limit:]))     # newest first
        out["truncated"] = len(rows) > limit
    except Exception as exc:
        out["verify"] = {"ok": False, "exists": False, "rows": 0,
                         "findings": ["could not read the journal: %s" % exc],
                         "warnings": []}
    return out


def help_state():
    """`GET /api/help` — what every field means, and how the four concepts work.

    Costs nothing to ask and nothing to answer: the field text is EXTRACTED from
    the two shipped schemas at request time, so the drawer cannot drift from the
    document a reader is told to trust, and the concept pages derive every
    executable rule from the code that executes it (`_help` states which). The
    conversational half — the `audit-guide` agent — is a card in this payload
    rather than something the panel spawns: a question a static page already
    answers should not silently bill for a model.

    Project-independent, and deliberately so. It takes no `project` argument
    because there is nothing here to scope: the live verdicts are `/api/policy`,
    the live trail is `/api/journal`, and mixing documentation with state would let
    a reader take a worked example for their own repository.
    """
    return _help.payload()


def help_field(path, doc):
    """`GET /api/help?path=usage.pricing.opus.in&doc=config` — one field.

    The drawer holds a path into a DOCUMENT and the help table is keyed by SHAPES,
    and exactly one thing in this product knows how to get from one to the other:
    `_help.entry_for`. Asking it over HTTP costs a localhost round trip and buys
    the guarantee the policy tab already has — the browser is handed an answer, not
    the machinery to compute one, so a second implementation cannot drift into
    disagreeing with the first.

    `found:false` rather than a 404: "nothing documents this path" is an answer the
    drawer can render, and a 404 would be indistinguishable from a panel talking to
    an install with no help endpoint at all.
    """
    res = _help.entry_for(path, doc)
    if res is None:
        return {"found": False, "path": path, "doc": doc}
    out = dict(res)
    out["found"] = True
    return out


def _policy_rules(policy, kind, names):
    """Every pattern the block states for `kind`, with what it matches TODAY.

    The switchboard's per-capability switches can only ever write EXACT names, and
    a policy is not obliged to be written that way: `code-*` is one rule deciding
    ten rows, and a rule aimed at something nobody has installed decides none. Both
    are invisible in a table of capabilities, and a form that cannot show a rule
    cannot be trusted to save one — the PUT replaces the block wholesale, so a rule
    this UI does not represent is a rule it would quietly destroy.

    Matched by `_policy.matches`, the function the guard itself matches with, so
    "this pattern covers these three" is the same claim the verdict column makes.

    Deny before allow, and project before area, because that is the order `resolve`
    reads them in — a list in resolution order can be read top-down as the reason.
    """
    out = []
    kcfg = policy.get(kind) if isinstance(policy.get(kind), dict) else {}

    def add(scope, listname, patterns):
        # A LIST, not merely something iterable. `"deny": "nope"` is a shape the
        # validator calls a finding and a hand-edited file can still hold, and
        # iterating it yields four one-letter rules — a form inventing four rules
        # the file does not contain, each with its own remove button.
        if not isinstance(patterns, list):
            return
        for pat in patterns:
            if not isinstance(pat, str) or not pat.strip():
                continue
            hits = [n for n in names if _policy.matches(n, [pat])]
            out.append({"scope": scope, "list": listname, "pattern": pat,
                        "matches": hits[:6], "n": len(hits)})

    add(None, "deny", kcfg.get("deny"))
    add(None, "allow", kcfg.get("allow"))
    areas = kcfg.get("areas") if isinstance(kcfg.get("areas"), dict) else {}
    for tag in sorted(areas):
        rule = areas.get(tag)
        if isinstance(rule, dict):
            add(tag, "deny", rule.get("deny"))
            add(tag, "allow", rule.get("allow"))
    return out


def _policy_enforcement(project, config):
    """Has the guard hook ever actually run here?

    The one question a switchboard full of `deny` verdicts must not leave
    unanswered. Subagents do not inherit parent hooks on every Claude Code version
    (anthropics/claude-code#43772), and where that is true the policy is advisory —
    a page that draws a denial next to a capability while nothing is dispatching
    the matchers would be claiming enforcement nobody has.

    The evidence is the marker `guard-capabilities.py` writes when it runs with a
    live policy, read here exactly as `/audit:doctor` reads it: the hook's own
    `SEEN_FILE` constant and the config's own `state_dir`, never a path spelled out
    a second time in this file. The age is reported and the judgement is not — how
    stale is too stale is the doctor's call, and a threshold restated here is a
    threshold that can disagree with it.
    """
    out = {"seen": False, "ageDays": None}
    try:
        cfg_mod = _cores()[3]
        gc_mod = _load("audit_guard_capabilities",
                       os.path.join(_HERE, "..", "hooks", "guard-capabilities.py"))
        import pathlib
        marker = os.path.join(
            str(cfg_mod.state_dir(pathlib.Path(project), config)), gc_mod.SEEN_FILE)
        age = (time.time() - os.path.getmtime(marker)) / 86400.0
        out["seen"] = True
        out["ageDays"] = round(age, 2)
    except Exception:
        pass
    return out


def _policy_areas_view(reg, active, tags):
    """The area columns: every tag a rule could be aimed at, and whether it is LIVE.

    An area rule only applies while some phase in that area has work in progress
    (`_config.active_area_tags`, and `_active_area_tags` here) — so a column of
    denials for a dormant area decides nothing today and will decide everything the
    moment that phase starts. That is the fact this view exists to carry: the tag,
    whether it is active, and where the tag came from, since a rule may legitimately
    be written for a free-text tag the registry never registered.
    """
    out = []
    for tag in tags:
        entry = reg.get(tag) if isinstance(reg, dict) else None
        out.append({"tag": tag, "active": tag in (active or []),
                    "registered": isinstance(entry, dict),
                    "description": (entry or {}).get("description")
                    if isinstance(entry, dict) else None})
    return out


def policy_state(project):
    """`GET /api/policy` — the block, and what it RESOLVES TO for what is installed.

    The block alone is unreadable as governance: `{"default": "deny", "allow":
    ["code-*"]}` is four words that decide the fate of every skill on the machine,
    and nobody can hold the cross-product in their head. So the verdict for each
    discovered capability is computed here, by `_policy.resolve` — the same function
    the guard hook calls — and shipped alongside. A preview that ran its own
    matching would eventually disagree with the guard, and disagreeing about a
    denial is the one place a panel must not be creative.

    Every verdict carries its `basis` for the same reason the hook's refusal does.

    MCP is the one kind whose rows are STAND-INS: what is discoverable is a server
    name, while a policy matches whole tool names, so the row for server `github` is
    evaluated as `mcp__github__*` and says so via `standIn`. A rule aimed at one
    tool of that server therefore does not move the server's row — which is true,
    and better said than quietly averaged.
    """
    config = read_config(project)
    policy = _policy.policy_cfg(config)
    findings, warnings = _policy.validate_policy(config.get("policy"))
    mpath = _manifest_path(project, config)
    try:
        manifest = _mio.load_manifest_safe(mpath)
    except Exception:
        manifest = {}
    active = _active_area_tags(manifest)
    reg = _areas.registry(manifest)
    found = discover(project)
    out = {
        "policy": policy,
        "stored": config.get("policy") if isinstance(config.get("policy"), dict)
        else None,
        "active": _policy.is_active(policy),
        "onViolation": policy.get("onViolation"),
        "activeAreas": active,
        # Registered, used, or live — the same union `areas_state` reports, because
        # a rule can legitimately be written for a tag the registry does not carry
        # (free-text tagging is still legal) and a switchboard that offered only
        # registered areas would silently hide the rules aimed at the others.
        "areas": sorted(set(reg) | set(_areas.used_tags(manifest)) | set(active)),
        "required": _policy.required_names(),
        "kinds": list(_policy.KINDS),
        "onViolationChoices": list(_policy.ON_VIOLATION),
        "findings": findings, "warnings": warnings,
        # Whether anything is enforcing this at all. Served with the verdicts and
        # not on a separate endpoint, because it is a qualifier ON the verdicts.
        "enforcement": _policy_enforcement(project, config),
        "resolved": {}, "rules": {},
    }
    out["areaInfo"] = _policy_areas_view(reg, active, out["areas"])
    for kind in _policy.KINDS:
        rows = []
        if kind == "mcp":
            names = [("mcp__%s__*" % s, s, True) for s in (found.get("mcp") or [])]
        else:
            names = [(e.get("name"), e.get("source"), False)
                     for e in (found.get(kind) or []) if e.get("name")]
        for name, source, stand_in in names:
            v = _policy.resolve(policy, kind, name, active_tags=active)
            rows.append({"name": name, "source": source, "standIn": stand_in,
                         "verdict": v["verdict"], "basis": v["basis"],
                         "rule": v["rule"], "area": v["area"],
                         "required": bool(_policy.matches(
                             name, _policy.required_patterns(kind)))})
        out["resolved"][kind] = rows
        out["rules"][kind] = _policy_rules(policy, kind,
                                           [r["name"] for r in rows])
    return out


def _active_area_tags(manifest):
    """The area tags of phases with work in progress — what scopes an area rule.

    The same question `_config.active_area_tags` answers for the hook, asked of a
    manifest already in hand rather than re-read from disk. Both walk the ASSEMBLED
    document and both use `_areas.areas_of`, so the panel's preview and the guard's
    decision cannot disagree about which areas are live.
    """
    tags = []
    for phase in (manifest or {}).get("phases") or []:
        if not isinstance(phase, dict):
            continue
        running = phase.get("status") == "in_progress" or any(
            isinstance(t, dict) and t.get("status") == "in_progress"
            for t in (phase.get("tasks") or []))
        if not running:
            continue
        for tag in _areas.areas_of(phase.get("area")):
            if tag not in tags:
                tags.append(tag)
    return tags


def write_policy(project, body):
    """`PUT /api/policy` — replace the `policy` block wholesale.

    Wholesale for the same reason the registry is: a policy is a set of rules, and
    removing one is as ordinary an edit as adding one.

    Checked HERE before anything is written, so the caller gets
    `policy.skills.default: must be 'allow' or 'deny'` rather than the same fact
    restated across a whole-config validation. The write itself then goes through
    `write_config` — the one config writer — which validates the WHOLE file again,
    takes the lock, writes atomically and journals the change rows. That is also
    what makes the refusal below mechanical rather than a second rule living here:
    a policy denying audit's own components is a validator FINDING, so the write
    path already refuses it, and this check exists to say so in the policy's own
    words before the file is even assembled.
    """
    if not isinstance(body, dict):
        return {"ok": False, "findings": ["body must be a JSON object"]}
    policy = body.get("policy") if "policy" in body else body
    if policy is None:
        policy = {}
    findings, warnings = _policy.validate_policy(policy)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    config = read_config(project)
    updated = dict(config)
    updated["policy"] = policy
    res = write_config(project, updated)
    if res.get("ok"):
        res["warnings"] = list(res.get("warnings") or []) + warnings
    return res


def write_areas(project, body):
    """`PUT /api/areas` — replace `meta.areas` wholesale.

    Wholesale because a registry is a set: dropping an area is as ordinary an edit
    as adding one, and a merge-shaped API gives no way to say "this tag is gone".

    The shape is checked HERE, before anything is written, so the caller gets
    `meta.areas.api.root: must be a non-empty…` instead of the same fact restated
    as a manifest validator finding after a lock has been taken. The write itself
    then goes through `apply_composition`, which is the only writer: it takes the
    lock, re-validates the assembled document, patches the INDEX alone (meta lives
    there — a registry save must not touch a phase shard and manufacture a conflict
    on a branch nobody is on), echoes the change rows and journals them.
    """
    if not isinstance(body, dict):
        return {"ok": False, "findings": ["body must be a JSON object"]}
    # Accept either {"areas": {...}} or the bare registry, since both readings of
    # "PUT the areas" are reasonable and guessing wrong costs a confusing 400.
    areas = body.get("areas") if "areas" in body else body
    if areas is None:
        areas = {}
    findings, warnings = _areas.validate_registry(areas)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    res = apply_composition(project, {"meta": {"areas": areas}})
    if res.get("ok"):
        res["warnings"] = list(res.get("warnings") or []) + warnings
    return res


# The stylesheet lints live in _ui_theme, beside the tokens they police, so the
# report and the panel are held to exactly the same rules by the same code.
_undeclared_css_vars = _theme.undeclared_css_vars
_theme_asymmetric_vars = _theme.theme_asymmetric_vars
_themes_missing_color_scheme = _theme.themes_missing_color_scheme
_mangled_css_escapes = _theme.mangled_css_escapes


# --- concurrency-lock detection (locks live in the shared git dir, not the tree) --
_LOCKDIR_CACHE = {}


def _audit_lock_dir(project, config):
    """The shared audit-locks dir: $(git -C <gitRoot> rev-parse --git-common-dir)/audit-locks
    — where the orchestrator now keeps its index + per-phase locks (out of the working tree,
    shared across worktrees). None when this isn't a git repo (caller falls back to the legacy
    working-tree lock). Cached per git-root: build_state runs per request; the git dir never moves."""
    git_root = os.path.realpath(os.path.join(project, (config or {}).get("gitRoot") or "."))
    if git_root in _LOCKDIR_CACHE:
        return _LOCKDIR_CACHE[git_root]
    lockdir = None
    try:
        out = subprocess.run(["git", "-C", git_root, "rev-parse", "--git-common-dir"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            gd = out.stdout.strip()
            if not os.path.isabs(gd):
                gd = os.path.join(git_root, gd)
            lockdir = os.path.join(os.path.realpath(gd), "audit-locks")
    except Exception:
        lockdir = None
    _LOCKDIR_CACHE[git_root] = lockdir
    return lockdir


def _audit_lock_held(project, config):
    """True iff any /audit run holds a lock — the index lock OR any per-phase-shard lock.
    Checks the shared git-dir lock dir, falling back to the legacy working-tree lock, so the
    panel's 'locked' signal (and its composition-write refusal) keeps working in both layouts."""
    lockdir = _audit_lock_dir(project, config)
    if lockdir and os.path.isdir(lockdir):
        try:
            for name in os.listdir(lockdir):
                if name == "index.lock" or (name.startswith("phase-") and name.endswith(".lock")):
                    return True
        except Exception:
            pass
    return os.path.exists(_manifest_path(project, config) + ".lock")   # legacy fallback


def _lockmod():
    """audit-lock.py, loaded by path. None if it cannot be loaded — the panel
    then shows the lock without a liveness verdict rather than showing nothing."""
    try:
        return _loader.load_script("audit-lock.py", modname="audit_lock")
    except Exception:
        return None


def _lock_info(lockdir):
    """Read the shared audit-locks dir into {'index': info|None, 'phases': {pid: info}}.

    Each info is the lock file's `{hostname, startedAt, note}` (or {} if unreadable),
    plus `live` and `liveBasis` from audit-lock.py. The panel used to badge every
    lock file "running", which is a claim about a process it had not checked — an
    abandoned lock and a working one looked identical, and the badge was most
    confident exactly when it was most likely wrong.
    """
    out = {"index": None, "phases": {}}
    if not (lockdir and os.path.isdir(lockdir)):
        return out
    try:
        names = os.listdir(lockdir)
    except Exception:
        return out
    lock = _lockmod()
    for name in names:
        if not name.endswith(".lock"):
            continue
        path = os.path.join(lockdir, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                info = json.load(fh)
        except Exception:
            info = {}
        if not isinstance(info, dict):
            info = {}
        if lock is not None:
            try:
                info["live"], info["liveBasis"] = lock.judge(info, path)
            except Exception:
                pass
        if name == "index.lock":
            out["index"] = info
        elif name.startswith("phase-"):
            out["phases"][name[len("phase-"):-len(".lock")]] = info
    return out


def _run_status(project, config, manifest):
    """Per-phase live run status for the panel ('who's running what'): which phase is
    locked (and by whom) and which carries an optimistic claim. Combines the shared
    git-dir phase locks with each phase's `claim` from the manifest."""
    locks = _lock_info(_audit_lock_dir(project, config))
    phases = {}
    if isinstance(manifest, dict):
        for p in manifest.get("phases", []) or []:
            if isinstance(p, dict) and p.get("id"):
                claim = p.get("claim")
                phases[p["id"]] = {
                    "lock": locks["phases"].get(p["id"]),
                    "claim": claim if isinstance(claim, dict) else None}
    for pid, info in locks["phases"].items():          # locks for phases not in the manifest
        phases.setdefault(pid, {"lock": info, "claim": None})
    return {"index": locks["index"], "phases": phases}


_MAX_FACTS = 20000


def usage_state(project):
    """Payload for the Usage tab.

    Ships FACTS rather than finished tables — compact positional arrays the browser
    re-aggregates on every filter change, so switching model/author/phase/range is
    instant and never round-trips. Beyond _MAX_FACTS hourly rows the facts are rolled
    up to daily first, which keeps the payload bounded on a long-lived ledger; the
    response says so via `rolled` rather than silently truncating.

    Read-only: no lock, no writes, nothing that can collide with a running phase."""
    _, _, _, cfg_mod = _cores()
    config = read_config(project)
    ucfg = cfg_mod.usage_cfg(config)
    ledger_dir = str(cfg_mod.ledger_dir(project, config))
    empty = {"enabled": bool(ucfg.get("enabled", True)), "ledgerDir": ledger_dir,
             "showCost": bool(ucfg.get("showCost", True)),
             "pricingAsOf": ucfg.get("pricingAsOf"),
             "pricingAsOfDeclared": _declared_as_of(config),
             "facts": [], "fields": [],
             # Every key the populated branch returns must appear here too: the
             # client reads this shape on a repo with no ledger yet, and a missing
             # key there is an `undefined` that only shows up on a fresh install.
             "phaseTitles": {}, "taskMeta": {}, "phaseBudgets": {},
             "routingAdvice": [], "bands": ucfg.get("bands") or {},
             "counts": {"phases": 0, "tasks": 0, "models": 0, "authors": 0,
                        "sessions": 0, "days": 0, "from": None, "to": None},
             "rolled": False, "totalRows": 0}
    try:
        ul = _load("audit_usage_ledger", os.path.join(_HERE, "usage_ledger.py"))
        rows = ul.read_ledger(ledger_dir)
    except Exception:
        return empty
    if not rows:
        return empty

    # Orientation counts for the context line. Computed over the WHOLE ledger on
    # purpose — they describe the shape of the data you are looking at, not the
    # current filter — and `sessionId` deliberately never enters `facts`, where it
    # would multiply row cardinality for a number shown once.
    days = sorted({(r.get("ts") or "")[:10] for r in rows} - {""})
    counts = {
        "phases": len({r.get("phaseId") for r in rows if r.get("phaseId")}),
        "tasks": len({r.get("taskId") for r in rows if r.get("taskId")}),
        "models": len({r.get("model") for r in rows if r.get("model")}),
        "authors": len({r.get("author") for r in rows if r.get("author")}),
        "sessions": len({r.get("sessionId") for r in rows if r.get("sessionId")}),
        "days": len(days),
        "from": days[0] if days else None,
        "to": days[-1] if days else None,
    }

    rolled = len(rows) > _MAX_FACTS
    facts, seen = {}, 0
    for r in rows:
        seen += 1
        ts = r.get("ts") or ""
        key = (ts[:10] if rolled else ts, r.get("phaseId") or "--",
               r.get("taskId") or "--", r.get("model") or "unknown",
               r.get("author") or "unknown", r.get("agentType") or "orchestrator",
               r.get("attr") or "unattributed")
        slot = facts.get(key)
        if slot is None:
            slot = facts[key] = [0, 0.0, 0]
        slot[0] += sum(int(r.get(k) or 0) for k in ul.TOKEN_KEYS)
        slot[1] += float(r.get("costUSD") or 0.0)
        slot[2] += int(r.get("msgs") or 0)

    # Ship the small slice of manifest the analytics need — task status, risk and
    # attempts — so EVERY panel recomputes client-side under the current filter. The
    # alternative (server-computed metrics) would leave half the tab silently
    # ignoring the filter bar, which is worse than a slightly larger payload.
    titles, task_meta, budgets = {}, {}, {}
    mpath = _manifest_path(project, config)
    try:
        for ph in (_mio.load_manifest_safe(mpath).get("phases") or []):
            if not isinstance(ph, dict):
                continue
            if ph.get("id"):
                titles[ph["id"]] = ph.get("title") or ""
                # Same rule the validator enforces: 0, negative, boolean and
                # non-numeric all mean "no budget", never a budget of zero.
                b = ph.get("budgetUSD")
                if isinstance(b, (int, float)) and not isinstance(b, bool) and b > 0:
                    budgets[ph["id"]] = float(b)
            for t in (ph.get("tasks") or []):
                if isinstance(t, dict) and t.get("id"):
                    task_meta[t["id"]] = {
                        "status": t.get("status"), "risk": t.get("risk") or "unrated",
                        "attempts": t.get("attempts") or 1,
                        "title": t.get("title") or ""}
    except Exception:
        titles, task_meta, budgets = {}, {}, {}

    # Needs the assembled manifest and the per-tier counts, so it cannot be done
    # on the client. Fail-soft: no advice is the normal outcome anyway.
    try:
        advice = ul.routing(_mio.load_manifest_safe(mpath), rows,
                            ucfg.get("pricing")).get("advice") or []
    except Exception:
        advice = []

    return {
        "enabled": bool(ucfg.get("enabled", True)),
        "ledgerDir": ledger_dir,
        "showCost": bool(ucfg.get("showCost", True)),
        "pricingAsOf": ucfg.get("pricingAsOf"),
        "pricingAsOfDeclared": _declared_as_of(config),
        "fields": ["ts", "phase", "task", "model", "author", "agent", "attr",
                   "tokens", "cost", "msgs"],
        "facts": [list(k) + [v[0], round(v[1], 6), v[2]]
                  for k, v in sorted(facts.items())],
        "phaseTitles": titles,
        "taskMeta": task_meta,
        "phaseBudgets": budgets,
        # Server-computed, unlike every other metric here: the counterfactual
        # re-prices the per-tier token counts, and `facts` are already aggregated
        # to [tokens, cost, msgs]. Shipping the breakdown to do it client-side
        # would multiply the payload to serve one paragraph. So this is a
        # statement about the PROJECT, and the panel labels it as such.
        "routingAdvice": advice,
        "bands": ucfg.get("bands") or {},
        "counts": counts,
        "rolled": rolled,
        "totalRows": seen,
    }


def report_paths(project):
    """(manifest, out_dir, html_path) for this project's report, or None.

    The output location is DERIVED, never taken from the request: there is no path
    parameter to traverse with. Both ends are re-checked against the project root
    anyway, because a manifestPath in config could point outside it."""
    config = read_config(project)
    mpath = _manifest_path(project, config)
    if not (os.path.isfile(mpath) and _within(project, mpath)):
        return None
    out_dir = os.path.dirname(os.path.abspath(mpath))
    if not _within(project, out_dir):
        return None
    try:
        rr = _load("audit_render_report", os.path.join(_HERE, "render-report.py"))
        manifest = _mio.load_manifest_safe(mpath)
        # `_report_basename` takes META, not the manifest — it reads
        # `reportBasename` off the mapping it is handed. Passed the whole manifest
        # it found no such key and always answered "audit-report", so on every
        # project that sets meta.reportBasename (the shipped example does) the
        # panel rendered the report correctly and then looked for it under the
        # wrong name: "wrote 2 files" followed by a 404.
        base = rr._report_basename(manifest.get("meta"), None)
    except Exception:
        base = "audit-report"
    return mpath, out_dir, os.path.join(out_dir, base + ".html")


def render_report(project):
    """Write the standalone HTML report (and its Markdown twin) for this project.

    Calls render-report.py's own `main` rather than shelling out: same code path
    the CLI takes, no interpreter discovery, and it works the same on Windows."""
    paths = report_paths(project)
    if not paths:
        return {"ok": False,
                "findings": ["no manifest to report on (or its path escapes the "
                             "project) — run /audit:init first"]}
    mpath, out_dir, html_path = paths
    try:
        rr = _load("audit_render_report", os.path.join(_HERE, "render-report.py"))
    except Exception as exc:
        return {"ok": False, "findings": ["cannot load the renderer: %s" % exc]}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = rr.main([mpath, "--out-dir", out_dir, "--format", "both"])
    except Exception as exc:
        return {"ok": False, "findings": ["render failed: %s" % exc]}
    if code != 0:
        return {"ok": False,
                "findings": ["renderer exited %s — run /audit:report for detail"
                             % code]}
    written = [ln[len("wrote "):] for ln in buf.getvalue().splitlines()
               if ln.startswith("wrote ")]
    return {"ok": True, "files": written,
            # Served back through this origin: a browser will not follow a file://
            # link from an http:// page, so handing over a filesystem path would
            # produce a button that silently does nothing.
            "href": "/report", "exists": os.path.isfile(html_path)}


def build_state(project):
    vm, vc, as_, _ = _cores()
    config = read_config(project)
    cfg_findings, cfg_warnings = vc.validate_config(config)
    mpath = _manifest_path(project, config)
    manifest, exists = None, os.path.isfile(mpath)
    rollup, m_findings = None, []
    composition = {"meta": {"reviewSkill": None, "buildCommands": None},
                   "phases": [], "tasks": []}
    bugs = []
    if exists:
        try:
            manifest = _mio.load_manifest(mpath)   # dual-format: single-file OR index+shards
        except Exception as exc:
            m_findings = ["cannot parse manifest: %s" % exc]
        if isinstance(manifest, dict):
            m_findings, m_warn = vm.validate(manifest)
            rollup = as_.rollup(manifest, m_findings, m_warn)
            composition = _composition_view(manifest)
            bugs = _bugs_view(manifest)
    return {
        "project": project,
        "manifestPath": os.path.relpath(mpath, project),
        "manifestExists": exists,
        "manifestLocked": _audit_lock_held(project, config),
        "viewer": _viewer(project, config),
        "config": config,
        "defaults": _defaults(),
        "configFindings": cfg_findings,
        "configWarnings": cfg_warnings,
        "manifestFindings": m_findings,
        "composition": composition,
        "bugs": bugs,
        "rollup": rollup,
        "runStatus": _run_status(project, config, manifest),
    }


# --- write locking ---------------------------------------------------------------
def _panel_session():
    """This panel's lock identity. A pid the OS can vouch for is what lets a
    crashed panel's lock be judged dead rather than waited out for an hour."""
    return "panel-%d" % os.getpid()


def _acquire_write_lock(project, config, touched_phases=None):
    """Take the index lock for the duration of a write.

    Returns {"blocked": False, ...} when the caller may proceed, or
    {"blocked": True, "response": <dict to return to the client>}.

    `touched_phases` matters only in the sharded layout: a phase running in
    another worktree owns its own shard, and editing a DIFFERENT phase's shard
    cannot conflict with it. Passing None (single file) means any phase lock
    contends, because there is only one file.
    """
    lockmod = _lockmod()
    mpath = _manifest_path(project, config)
    if lockmod is None:
        # No lock library: fall back to the old check-only behaviour rather than
        # writing unguarded or refusing everything.
        if _audit_lock_held(project, config):
            return {"blocked": True, "response": {
                "ok": False, "locked": True,
                "findings": ["manifest is locked by a running /audit command; "
                             "try again once it finishes"]}}
        return {"blocked": False, "held": False}

    # A phase lock on a shard this write does not touch is not our business: that
    # phase owns its own file, and editing a different one cannot collide with it.
    # An abandoned lock does not block either — that is what `live` is for.
    info = _lock_info(_audit_lock_dir(project, config)) or {}
    blocking = [pid for pid, ph in (info.get("phases") or {}).items()
                if (ph or {}).get("live", True)
                and (touched_phases is None or pid in touched_phases)]
    if blocking:
        host = ((info.get("phases") or {}).get(blocking[0]) or {}).get("hostname")
        return {"blocked": True, "response": {
            "ok": False, "locked": True, "lockedPhases": sorted(blocking),
            "findings": ["phase %s is running elsewhere (%s); it cannot be edited "
                         "until that run finishes"
                         % (", ".join(sorted(blocking)), host or "unknown host")]}}

    git_root = os.path.join(project, (config or {}).get("gitRoot") or ".")
    out = []
    try:
        code = lockmod.main(["acquire", "index", "--project", git_root,
                             "--note", "panel write", "--session", _panel_session(),
                             "--pid", str(os.getpid())], out=out.append)
    except Exception:
        code = None
    if code == 0:
        return {"blocked": False, "held": True, "project": git_root, "mod": lockmod}
    if code == getattr(lockmod, "E_LIVE", 3):
        return {"blocked": True, "response": {
            "ok": False, "locked": True,
            "findings": [" ".join(out).strip()
                         or "the manifest is locked by a running /audit command; "
                            "try again once it finishes"]}}
    if code == getattr(lockmod, "E_STALE", 4):
        # Never taken over silently: a lock whose holder died is a decision for
        # the person who knows what that run was doing.
        return {"blocked": True, "response": {
            "ok": False, "locked": True, "lockStale": True,
            "findings": [(" ".join(out).strip() + " ") if out else "" +
                         "Release it with: audit-lock.py release index --project ."]}}
    # Not a git repo (or the lock library refused for a reason of its own): keep
    # the legacy working-tree lock as the guard rather than writing unguarded.
    legacy = mpath + ".lock"
    try:
        fd = os.open(legacy, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        return {"blocked": False, "held": True, "legacy": legacy}
    except FileExistsError:
        return {"blocked": True, "response": {
            "ok": False, "locked": True,
            "findings": ["manifest is locked by a running /audit command; "
                         "try again once it finishes"]}}
    except OSError:
        return {"blocked": False, "held": False}


def _release_write_lock(lock):
    """Give the lock back. Never raises: a write that succeeded must not be
    reported as failed because the release did."""
    if not lock or not lock.get("held"):
        return
    try:
        if lock.get("legacy"):
            os.unlink(lock["legacy"])
            return
        mod = lock.get("mod")
        if mod is not None:
            mod.main(["release", "index", "--project", lock.get("project") or ".",
                      "--session", _panel_session(), "--pid", str(os.getpid())],
                     out=lambda *_a, **_k: None)
    except Exception:
        pass


# --- what a save would change, and the record of it -------------------------------
# One row shape for both writers and for the journal: {target, field, from, to}.
# The panel renders it as "P1.2 · model · sonnet -> opus" before you confirm, the
# server recomputes it from the document on disk and echoes it back as `applied`,
# and the client compares the two. That comparison is the point: it is what turns
# "the save went through" into "the save changed exactly what I was shown", and it
# catches the case a confirm dialog otherwise makes WORSE — a second tab, or an
# /audit run, having moved the manifest under you between render and save.
def _flat_paths(obj, prefix=""):
    """Dotted leaf paths of a JSON object. Lists and empty dicts are leaves.

    A leaf per path rather than per block so `usage.bands.highUSD` reads as one
    change instead of "usage changed" — which is not a sentence anyone can check.
    """
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k) if prefix else str(k)
            if isinstance(v, dict) and v:
                out.update(_flat_paths(v, p))
            else:
                out[p] = v
    return out


def _config_changes(before, after):
    """Rows for a config save: one per dotted leaf path that actually differs."""
    a, b = _flat_paths(before or {}), _flat_paths(after or {})
    rows = []
    for p in sorted(set(a) | set(b)):
        # Presence as well as value: removing a key whose value was null is a real
        # change — deleting the key is how "use the default" is written — and
        # comparing two `.get()` results alone would call that a no-op.
        if (p in a) == (p in b) and a.get(p) == b.get(p):
            continue
        rows.append({"target": "config", "field": p,
                     "from": a.get(p), "to": b.get(p)})
    return rows


def _composition_changes(manifest, patch):
    """Rows for a composition save, computed BEFORE the patch is applied.

    Read off the ASSEMBLED manifest — the same document the panel rendered its form
    from — so the client's list and this one are two readings of one pair of values.

    A field set back to the value it already had is dropped here, and the client
    drops it too. That symmetry is what makes the mismatch check mean something: a
    row on one side only is news, not a difference of opinion about what counts.

    Unknown ids are skipped rather than reported: `apply_composition_patch` refuses
    them a moment later, with the message that names them.
    """
    rows = []
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    for k in _META_KEYS:
        if k in (patch.get("meta") or {}):
            was, now = meta.get(k), patch["meta"][k]
            if was != now:
                rows.append({"target": "meta", "field": k, "from": was, "to": now})
    by_pid = {p.get("id"): p for p in (manifest.get("phases") or [])
              if isinstance(p, dict)}
    for pid, pv in sorted((patch.get("phases") or {}).items()):
        ph = by_pid.get(pid)
        if ph is None or "reviewModel" not in (pv or {}):
            continue
        rev = ph.get("review") if isinstance(ph.get("review"), dict) else {}
        was, now = rev.get("model"), pv["reviewModel"]
        if was != now:
            rows.append({"target": pid, "field": "review model",
                         "from": was, "to": now})
    by_tid = {t.get("id"): t for p in (manifest.get("phases") or [])
              if isinstance(p, dict)
              for t in (p.get("tasks") or []) if isinstance(t, dict)}
    for tid, tv in sorted((patch.get("tasks") or {}).items()):
        t = by_tid.get(tid)
        if t is None:
            continue
        for k in _TASK_KEYS:
            if k in (tv or {}):
                # `skills` through the same normaliser the view uses — see
                # _skills_of for why the raw value would be the wrong `from`.
                was = _skills_of(t) if k == "skills" else t.get(k)
                now = tv[k]
                if was != now:
                    rows.append({"target": tid, "field": k,
                                 "from": was, "to": now})
    return rows


def _fmt_change(row):
    """One row as the panel prints it, for the journal's one-line summary.

    Every value except a plain string is JSON-spelled, which matters for exactly
    one type and was wrong for it until the journal made it visible: `str(True)` is
    `True`, and the dialog beside it says `true`. Whoever reads this line is
    holding a JSON file, where `True` is not something they can type — the same
    reason the areas validator spells its values in JSON rather than in Python.
    Strings stay bare, because quoting every model name would be noise.
    """
    def side(v):
        if v is None:
            return "(unset)"
        if isinstance(v, str):
            return v
        return json.dumps(v, sort_keys=True)
    return "%s %s: %s -> %s" % (row.get("target"), row.get("field"),
                                side(row.get("from")), side(row.get("to")))


_JOURNAL = {"tried": False, "mod": None}


def _journalmod():
    """`audit-journal.py`, loaded by path — or None, which is the normal answer
    today: the module ships with v0.29 and this call site ships before it, on
    purpose, so that the release which adds the journal does not also have to reach
    back into every writer. Loaded once; a missing file is not retried per save."""
    if not _JOURNAL["tried"]:
        _JOURNAL["tried"] = True
        path = os.path.join(_HERE, "audit-journal.py")
        if os.path.isfile(path):
            try:
                _JOURNAL["mod"] = _loader.load(path, modname="audit_journal")
            except Exception:
                _JOURNAL["mod"] = None
    return _JOURNAL["mod"]


def _journal(project, config, action, target, rows):
    """Append one row to the tamper-evident journal. Response fields, not a bool.

    FAIL-SOFT BY CONTRACT, and the contract is the interesting part: a write that
    SUCCEEDED must never be reported as failed because the journal was absent,
    unwritable or broken. Nothing here can raise into a writer.

    Returns `{"journaled": True}`, or False plus a `journaledWhy` that the panel
    needs in order not to lie in either direction:

      "unavailable" — this install has no journal (the module ships with v0.29,
        this call site ships now). The toast then says nothing about logging at
        all: "not logged" would advertise a feature that is not here and make every
        ordinary save read like a failure.
      "failed"      — the journal exists and would not take the row. That one IS
        worth saying out loud, in the same breath as the save: an unlogged change
        and a broken audit trail are not the same news.

    The changes go into `summary` rather than a field of their own: the journal row
    is a fixed shape ({v, ts, actor, action, target, summary, stateHash, prev,
    hash}) and inventing a key here would be this file deciding a format that file
    owns.
    """
    mod = _journalmod()
    if mod is None or not hasattr(mod, "append"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    try:
        ok = bool(mod.append(project, {
            "action": action,
            "target": target,
            "summary": "%d change(s): %s" % (
                len(rows), "; ".join(_fmt_change(r) for r in rows)),
            "actor": {"author": _viewer(project, config).get("author"),
                      "sessionId": _panel_session(), "via": "panel"}}))
    except Exception:
        ok = False
    return {"journaled": True} if ok else {"journaled": False,
                                           "journaledWhy": "failed"}


# --- writes ---------------------------------------------------------------------
def write_config(project, obj):
    """Validate then atomically write .claude/audit.config.json. Returns dict."""
    _, vc, _, _ = _cores()
    if not isinstance(obj, dict):
        return {"ok": False, "findings": ["config must be a JSON object"]}
    findings, warnings = vc.validate_config(obj)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    path = _config_path(project)
    if not _within(project, path):
        return {"ok": False, "findings": ["refused: path escapes project"]}
    current = read_config(project)
    applied = _config_changes(current, obj)
    if not applied:
        # Nothing to write. Not an error and not a lie either: the response says
        # `unchanged`, so the panel can say "no changes" rather than "saved" —
        # and no file is touched, so a save with nothing in it cannot rewrite a
        # config someone else edited in the meantime.
        return {"ok": True, "findings": [], "warnings": warnings, "applied": [],
                "unchanged": True, "journaled": False,
                "journaledWhy": "unchanged",
                "path": os.path.relpath(path, project)}
    # The config decides where the manifest is and which guards run; writing it
    # under a running phase is the same class of surprise as writing the manifest.
    lock = _acquire_write_lock(project, current, None)
    if lock.get("blocked"):
        return lock["response"]
    try:
        _atomic_write_json(path, obj)
    finally:
        _release_write_lock(lock)
    out = {"ok": True, "findings": [], "warnings": warnings, "applied": applied,
           "path": os.path.relpath(path, project)}
    # `current`, not the config just written: the actor is resolved under the mode
    # that was in force when they made the change, not one this same save may have
    # altered.
    out.update(_journal(project, current, "config.write", out["path"], applied))
    return out


def _reject_unknown(patch):
    for top in patch:
        if top not in ("meta", "phases", "tasks"):
            return "unknown patch section %r" % top
    for k in (patch.get("meta") or {}):
        if k not in _META_KEYS:
            return "meta.%s is not editable here" % k
    for _pid, pv in (patch.get("phases") or {}).items():
        for k in (pv or {}):
            if k not in _PHASE_KEYS:
                return "phase.%s is not editable here" % k
    for _tid, tv in (patch.get("tasks") or {}).items():
        for k in (tv or {}):
            if k not in _TASK_KEYS:
                return "task.%s is not editable here" % k
    return None


def apply_composition_patch(manifest, patch):
    """Apply an allow-listed composition patch to `manifest` in place.
    Returns None on success or an error string. Never touches structure."""
    err = _reject_unknown(patch)
    if err:
        return err
    meta = manifest.setdefault("meta", {})
    for k in _META_KEYS:
        if k in (patch.get("meta") or {}):
            meta[k] = patch["meta"][k]
    by_pid = {p.get("id"): p for p in (manifest.get("phases") or [])
              if isinstance(p, dict)}
    for pid, pv in (patch.get("phases") or {}).items():
        ph = by_pid.get(pid)
        if ph is None:
            return "unknown phase %r" % pid
        if "reviewModel" in (pv or {}):
            rev = ph.get("review")
            if not isinstance(rev, dict):
                rev = ph["review"] = {}
            rev["model"] = pv["reviewModel"]
    by_tid = {t.get("id"): t for p in (manifest.get("phases") or [])
              if isinstance(p, dict)
              for t in (p.get("tasks") or []) if isinstance(t, dict)}
    for tid, tv in (patch.get("tasks") or {}).items():
        t = by_tid.get(tid)
        if t is None:
            return "unknown task %r" % tid
        if "model" in (tv or {}):
            t["model"] = tv["model"]
        if "skills" in (tv or {}):
            sk = tv["skills"]
            if not (isinstance(sk, list) and all(isinstance(x, str) for x in sk)):
                return "task %s skills must be an array of strings" % tid
            t["skills"] = sk
    return None


def _touched_phase_ids(manifest, patch):
    """Which phases a patch actually changes — named directly, or owning a task."""
    touched = set((patch.get("phases") or {}).keys())
    want = set((patch.get("tasks") or {}).keys())
    if want:
        for ph in (manifest.get("phases") or []):
            if not isinstance(ph, dict):
                continue
            for t in (ph.get("tasks") or []):
                if isinstance(t, dict) and t.get("id") in want:
                    touched.add(ph.get("id"))
    return touched


def _write_back(project, mpath, raw_index, assembled, patch, touched):
    """Persist a patched manifest into whichever layout it is stored in.

    SINGLE FILE: write the assembled dict; it IS the file.

    SHARDED: write only what the patch touched — the body of each touched phase's
    shard, and the index only if `meta` changed. Two reasons this is targeted
    rather than a wholesale `save_sharded`:

      * The index stub is deliberately {id, title, shard} with no body mirror, and
        `_merge_phase` treats the shard as the source of truth. Writing a phase's
        `review.model` into the stub — which is what this used to do — put it
        somewhere the next load discards.
      * Rewriting untouched shards would renormalize files no one edited and
        manufacture merge conflicts against the parallel phase branches the
        sharded layout exists to keep conflict-free.

    Returns the list of written paths, project-relative.
    """
    if not _mio.is_sharded(raw_index):
        _atomic_write_json(mpath, assembled)
        return [os.path.relpath(mpath, project)]

    base = os.path.dirname(os.path.abspath(mpath))
    by_pid = {p.get("id"): p for p in (assembled.get("phases") or [])
              if isinstance(p, dict)}
    written = []
    for stub in (raw_index.get("phases") or []):
        if not isinstance(stub, dict) or stub.get("id") not in touched:
            continue
        patched = by_pid.get(stub.get("id"))
        if patched is None:
            continue
        if "shard" not in stub:
            continue          # inline phase in a sharded index: falls to the index write
        spath = os.path.abspath(os.path.join(base, stub["shard"]))
        if not _within(project, spath):
            raise ValueError("refused: shard path escapes project: %s" % stub["shard"])
        body = dict(patched)
        # The stub owns identity; the shard body never carries its own pointer.
        body.pop("shard", None)
        _atomic_write_json(spath, body)
        written.append(os.path.relpath(spath, project))

    if patch.get("meta"):
        idx = dict(raw_index)
        idx["meta"] = assembled.get("meta") or {}
        _atomic_write_json(mpath, idx)
        written.append(os.path.relpath(mpath, project))
    return written


def apply_composition(project, patch):
    """Load manifest, apply an allow-listed patch, validate, write it back.

    Reads through the dual-format loader and patches the ASSEMBLED manifest. It
    used to read the raw index instead, which on a sharded manifest — this repo's
    own, and the shipped example's — meant the phases were stubs with no tasks in
    them: every per-task edit was refused as "unknown task" for a task the panel
    had just listed, phase edits landed in a stub the next load throws away, and
    even a meta-only save failed on a wall of validator findings about stubs
    missing fields they are not supposed to have.
    """
    vm, _, _, _ = _cores()
    if not isinstance(patch, dict):
        return {"ok": False, "findings": ["patch must be a JSON object"]}
    config = read_config(project)
    mpath = _manifest_path(project, config)
    if not _within(project, mpath):
        return {"ok": False, "findings": ["refused: manifest path escapes project"]}
    if not os.path.isfile(mpath):
        return {"ok": False, "findings": ["manifest not found: run /audit:init first"]}
    try:
        raw_index = _read_json(mpath)
    except Exception as exc:
        return {"ok": False, "findings": ["cannot parse manifest: %s" % exc]}
    if not isinstance(raw_index, dict):
        return {"ok": False, "findings": ["manifest root is not an object"]}
    try:
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        return {"ok": False, "findings": ["cannot assemble manifest: %s" % exc]}
    if not isinstance(assembled, dict):
        return {"ok": False, "findings": ["manifest root is not an object"]}

    # Computed against the manifest as it is NOW, before the patch touches it: the
    # `from` half of every row has to be the value on disk, not the value the patch
    # is about to put there.
    applied = _composition_changes(assembled, patch)
    err = apply_composition_patch(assembled, patch)
    if err:
        return {"ok": False, "findings": ["refused: " + err]}
    findings, warnings = vm.validate(assembled)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    if not applied:
        # A patch whose every field already holds the value it asks for. Writing it
        # would rewrite shards nobody edited — the exact renormalisation the
        # targeted write-back exists to avoid — to record no change at all.
        return {"ok": True, "findings": [], "warnings": warnings, "applied": [],
                "unchanged": True, "journaled": False,
                "journaledWhy": "unchanged", "written": [],
                "path": os.path.relpath(mpath, project),
                "layout": "sharded" if _mio.is_sharded(raw_index) else "single"}

    touched = _touched_phase_ids(assembled, patch)
    sharded = _mio.is_sharded(raw_index)
    # Hold the lock across read-patch-write. Checking it and then writing left a
    # window an /audit run could start in; acquiring it closes that window with
    # the same O_EXCL primitive the CLI uses.
    lock = _acquire_write_lock(project, config,
                               touched if sharded else None)
    if lock.get("blocked"):
        return lock["response"]
    try:
        written = _write_back(project, mpath, raw_index, assembled, patch, touched)
    except ValueError as exc:
        return {"ok": False, "findings": [str(exc)]}
    finally:
        _release_write_lock(lock)
    out = {"ok": True, "findings": [], "warnings": warnings, "applied": applied,
           "path": os.path.relpath(mpath, project),
           "layout": "sharded" if sharded else "single",
           "written": written}
    out.update(_journal(project, config, "composition.write",
                        out["path"], applied))
    return out


# --- HTTP server ----------------------------------------------------------------
def _make_handler(project, token):
    _local = {"127.0.0.1", "localhost", "[::1]"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "AuditPanel/1.0"

        def log_message(self, *a):  # keep the console quiet
            pass

        def _host_ok(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in _local or host == ""

        def _tok_ok(self):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            supplied = self.headers.get("X-Audit-Token") or (q.get("t") or [""])[0]
            return secrets.compare_digest(supplied, token)

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj), "application/json")

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw or b"{}")

        def _guard(self):
            if not self._host_ok():
                self._json(403, {"error": "bad host"}); return False
            if not self._tok_ok():
                self._json(403, {"error": "bad or missing token"}); return False
            return True

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/favicon.ico":
                self._send(204, b"", "image/x-icon"); return
            if path == "/":
                if not self._host_ok():
                    self._send(403, "forbidden", "text/plain"); return
                html = UI_HTML.replace("__AUDIT_TOKEN__", _js(token)).replace(
                    "__AUDIT_PROJECT__", _js(project))
                self._send(200, html, "text/html"); return
            if not self._guard():
                return
            if path == "/api/state":
                self._json(200, build_state(project)); return
            if path == "/api/runstatus":
                # Deliberately NOT `/api/state` on a timer. Two reasons, and the
                # second is correctness rather than cost: build_state computes the
                # rollup, the composition and up to 20000 usage facts, and the
                # client would have to re-render from it — blowing away whatever
                # the human had half-typed into the guards form. This endpoint
                # reads the lock dir and the phases' claims and nothing else, so
                # the poll can update the badges without touching the editors.
                cfg = read_config(project)
                try:
                    man = _mio.load_manifest_safe(_manifest_path(project, cfg))
                except Exception:
                    man = {}
                self._json(200, _run_status(project, cfg, man)); return
            if path == "/api/registry":
                self._json(200, discover(project)); return
            if path == "/api/areas":
                self._json(200, areas_state(project)); return
            if path == "/api/usage":
                self._json(200, usage_state(project)); return
            if path == "/api/journal":
                self._json(200, journal_state(project)); return
            if path == "/api/policy":
                self._json(200, policy_state(project)); return
            if path == "/api/help":
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                want = (q.get("path") or [""])[0]
                if want:
                    self._json(200, help_field(
                        want, (q.get("doc") or ["config"])[0])); return
                self._json(200, help_state()); return
            if path == "/report":
                # No path parameter: the location is derived from the project's
                # own config, so there is nothing here to traverse with.
                paths = report_paths(project)
                if not paths or not os.path.isfile(paths[2]):
                    self._send(404, "<h1>No report yet</h1><p>Use "
                               "<b>Export report</b> in the panel, or run "
                               "<code>/audit:report</code>.</p>", "text/html")
                    return
                try:
                    with open(paths[2], "rb") as fh:
                        self._send(200, fh.read(), "text/html")
                except Exception:
                    self._send(500, "<h1>Could not read the report</h1>",
                               "text/html")
                return
            self._json(404, {"error": "not found"})

        def do_PUT(self):
            if not self._guard():
                return
            path = self.path.split("?", 1)[0]
            try:
                body = self._body()
            except Exception as exc:
                self._json(400, {"ok": False, "findings": ["bad JSON: %s" % exc]}); return
            if path == "/api/config":
                self._json(200, write_config(project, body)); return
            if path == "/api/composition":
                self._json(200, apply_composition(project, body)); return
            if path == "/api/areas":
                self._json(200, write_areas(project, body)); return
            if path == "/api/policy":
                self._json(200, write_policy(project, body)); return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._guard():
                return
            path = self.path.split("?", 1)[0]
            if path == "/api/validate":
                st = build_state(project)
                self._json(200, {"config": st["configFindings"],
                                 "manifest": st["manifestFindings"]}); return
            if path == "/api/report":
                self._json(200, render_report(project)); return
            self._json(404, {"error": "not found"})

    return Handler


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- lifecycle: a pidfile so a running panel is always discoverable + stoppable -
def _pidfile(project):
    return os.path.join(project, ".claude", "audit-panel.json")


def _read_pidfile(project):
    try:
        with open(_pidfile(project), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _redact_token(url):
    """Same URL with the `t=` value replaced, for anything that gets kept.

    The token is a live credential for a localhost server, and this plugin already
    treats it as one: the pidfile holding it is gitignored with the note "Never
    history". Printing it to a terminal that Claude Code transcribes was the same
    leak by a different route.

    Matches `t=` at the start of the string as well as after `?`/`&`. A redactor that
    passes its input through unchanged when the shape is unexpected is worse than no
    redactor at all, so the pattern is deliberately looser than the one URL this is
    called with today."""
    try:
        import re as _re
        return _re.sub(r"((?:^|[?&])t=)[^&\s]*", r"\1<hidden>", str(url))
    except Exception:
        return "http://127.0.0.1/?t=<hidden>"


def _write_pidfile(project, info):
    path = _pidfile(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2)


def _rm_pidfile(project):
    try:
        os.remove(_pidfile(project))
    except OSError:
        pass


def _pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, owned by someone else
    except OSError:
        return False          # best-effort (e.g. Windows quirks)
    return True


def status_panel(project):
    info = _read_pidfile(project)
    if info and _pid_alive(info.get("pid")):
        # --status answers "is it running", which needs the port but not the token.
        print("panel RUNNING: %s (PID %s)"
              % (_redact_token(info.get("url")), info.get("pid")))
        print("the full URL (with its session token) is in "
              ".claude/audit-panel.json — it is gitignored; keep it that way")
        return 0
    _rm_pidfile(project)   # stale/none
    print("panel not running (project: %s)" % project)
    return 0


def stop_panel(project):
    info = _read_pidfile(project)
    if not info or not _pid_alive(info.get("pid")):
        _rm_pidfile(project)
        print("no panel running (project: %s)" % project)
        return 0
    pid = info["pid"]
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        print("could not stop panel (PID %s): %s" % (pid, exc))
        return 1
    _rm_pidfile(project)
    print("stopped panel (PID %s — was %s)" % (pid, info.get("url")))
    return 0


def serve(project, port=0, open_browser=True):
    # One panel per project: if one is already up, point at it instead of spawning
    # a second (and never leave an untracked process behind).
    existing = _read_pidfile(project)
    if existing and _pid_alive(existing.get("pid")):
        # The caller asked to OPEN the panel, so honour that against the one that is
        # already up rather than printing a URL and stopping. Refusing with a link
        # made the common case ("I want the panel") a two-step manual dance.
        print("panel already running: %s  (token hidden)"
              % _redact_token(existing.get("url")))
        if open_browser and existing.get("url"):
            print("opening the running one in your browser")
            try:
                webbrowser.open(existing["url"])
            except Exception:
                print("could not open a browser; the full URL is in "
                      ".claude/audit-panel.json")
        print("stop it with:  --stop   (or /audit:panel stop)")
        return 0
    _rm_pidfile(project)  # clear any stale record

    token = secrets.token_urlsafe(18)
    port = port or _free_port()
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port),
                                    _make_handler(project, token))
    except OSError as exc:
        # A taken port is the ordinary case, not an exceptional one: --port was
        # given explicitly, or _free_port lost the race between probing and
        # binding. Either way a Python traceback is the wrong answer.
        sys.stderr.write(
            "ERROR: cannot listen on 127.0.0.1:%d — %s\n" % (port, exc))
        sys.stderr.write(
            "  another panel or process may already hold that port. Try:\n"
            "    python3 %s --project %s --status    # is a panel already running?\n"
            "    python3 %s --project %s --stop      # stop the one that is\n"
            "  or omit --port to let the OS pick a free one.\n"
            % (os.path.basename(__file__), project,
               os.path.basename(__file__), project))
        return 2
    url = "http://127.0.0.1:%d/?t=%s" % (port, token)
    _write_pidfile(project, {"pid": os.getpid(), "port": port, "url": url})
    atexit.register(_rm_pidfile, project)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))  # --stop → clean exit
    # The URL carries a live session token. Printing it put that token in terminal
    # scrollback and in the Claude transcript — the same value whose pidfile is
    # gitignored with the note "Never history". So it is printed only when the
    # caller has to open the URL by hand (--no-open); in the default flow the
    # browser is handed the URL directly and the terminal shows a redacted form.
    if open_browser:
        print("audit control panel: %s  (token hidden)" % _redact_token(url))
        print("project: %s" % project)
        print("(opening your browser; press Ctrl-C — or `--stop` — to stop)")
        print("need the URL? run with --status, or read .claude/audit-panel.json")
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    else:
        print("audit control panel: %s" % url)
        print("project: %s" % project)
        print("(open the URL in a browser; press Ctrl-C — or `--stop` — to stop)")
        print("NOTE: that URL contains a live session token — avoid pasting it "
              "anywhere it will be kept.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
        _rm_pidfile(project)
    return 0


def _js(s):
    """JSON-escape a string for safe embedding inside a <script> literal."""
    return json.dumps(str(s))


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--stop", action="store_true", help="stop a running panel for --project")
    ap.add_argument("--status", action="store_true", help="report whether a panel is running")
    ap.add_argument("--selftest", action="store_true")
    # Read by tools/capture-screenshots.mjs, which then asserts the live page has a
    # control for each one. The list is derived from SETTINGS_GROUPS rather than
    # restated in the checker, so the browser check cannot go stale against it.
    ap.add_argument("--settings-paths", action="store_true",
                    help="print the config paths the Settings form binds, as JSON")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.settings_paths:
        print(json.dumps(_settings_paths()))
        return 0
    project = os.path.realpath(args.project)
    if not os.path.isdir(project):
        sys.stderr.write("ERROR: --project %s is not a directory\n" % project)
        return 2
    if args.stop:
        return stop_panel(project)
    if args.status:
        return status_panel(project)
    return serve(project, args.port, not args.no_open)


# --- the UI (self-contained; talks only to its own localhost API) ---------------
UI_HTML = _panel_ui.raw_template()

# Assembled once, at import: the shared token layer and the words both surfaces
# render. One substitution rather than a template engine, so every selftest that
# asks `... in UI_HTML` still sees the whole finished stylesheet.
UI_HTML = UI_HTML.replace("/*__THEME_TOKENS__*/", _theme.TOKEN_CSS)
UI_HTML = UI_HTML.replace("__LABELS__", json.dumps(_theme.LABELS, sort_keys=True))
# `ensure_ascii=False` because the page is served as UTF-8 and this prose contains
# em dashes and curly apostrophes like the rest of it. \uXXXX escapes would render
# identically but leave the copy unreadable in the source and ungreppable by the
# selftests, which is how a sentence gets edited in one place and pinned in another.
_JS_JSON = dict(sort_keys=True, ensure_ascii=False)
UI_HTML = UI_HTML.replace("__SETTINGS__", json.dumps(SETTINGS_GROUPS, **_JS_JSON))
UI_HTML = UI_HTML.replace("__FIELD_HELP__", json.dumps(FIELD_HELP, **_JS_JSON))
UI_HTML = UI_HTML.replace("__COMP_HELP__", json.dumps(COMPOSITION_HELP, **_JS_JSON))
# Loads validate-config, so it runs at import rather than in the string above. The
# enums are the validator's own tuples — see _cfg_enums.
UI_HTML = UI_HTML.replace("__CFG_ENUMS__", json.dumps(_cfg_enums(), sort_keys=True))


# --- selftest -------------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    # --- stylesheet integrity ---------------------------------------------------
    # The existing CSS checks look at custom properties; nothing checked structure,
    # and an unbalanced brace had been shipping. A stray `}` at top level is merely
    # discarded, but the same slip one nesting level deeper silently terminates a
    # block and drops every rule after it, with nothing in the console.
    _css = re.search(r"<style>([\s\S]*?)</style>", UI_HTML)
    check("panel stylesheet is present", _css is not None)
    if _css:
        _sheet = _css.group(1)
        _depth, _stray = 0, []
        for _i, _line in enumerate(_sheet.split("\n"), 1):
            for _ch in _line:
                if _ch == "{":
                    _depth += 1
                elif _ch == "}":
                    _depth -= 1
                    if _depth < 0:
                        _stray.append(_i)
                        _depth = 0
        check("panel stylesheet has no stray '}' (%r)" % (_stray[:3],), not _stray)
        check("panel stylesheet closes every block (depth %d)" % _depth, _depth == 0)

    # the session token must never reach a terminal by accident
    check("token is redacted for anything that gets kept",
          _redact_token("http://127.0.0.1:8791/?t=SECRETVALUE")
          == "http://127.0.0.1:8791/?t=<hidden>")
    check("redaction survives extra query params",
          "SECRET" not in _redact_token("http://127.0.0.1:1/?t=SECRET&x=1"))
    check("redaction of a malformed url still hides a token",
          "SECRET" not in _redact_token(None) + _redact_token("t=SECRET"))

    # discovery (_scan_skills/_scan_agents/discover, the front-matter parser and
    # their fixture-dir cases) moved to _panel_discovery.py's own selftest (P12.2);
    # `discover` itself is still exercised indirectly below via `apply_composition`
    # writing a reviewSkill/skills value the same way the panel's picker would.
    tmp = tempfile.mkdtemp(prefix="panel-selftest-")
    proj = os.path.join(tmp, "proj")

    # path safety
    check("within: inside ok", _within(proj, os.path.join(proj, ".claude/x")))
    check("within: escape refused", not _within(proj, os.path.join(proj, "..", "evil")))

    # config write: valid then invalid
    res = write_config(proj, {"trivialLineThreshold": 40})
    check("write valid config ok", res["ok"] and os.path.isfile(_config_path(proj)))
    check("config on disk matches", read_config(proj).get("trivialLineThreshold") == 40)
    res = write_config(proj, {"trivialLineThreshold": 0})
    check("write invalid config rejected (not written)",
          not res["ok"] and read_config(proj).get("trivialLineThreshold") == 40)

    # manifest + composition patch
    mpath = _manifest_path(proj, read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    manifest = {"meta": {"version": 2, "reviewSkill": None},
                "phases": [{"id": "P1", "title": "P", "status": "pending",
                            "review": {"model": "sonnet"},
                            "tasks": [{"id": "P1.1", "title": "T",
                                       "status": "pending"}]}]}
    _atomic_write_json(mpath, manifest)

    res = apply_composition(proj, {"meta": {"reviewSkill": "user-skill"},
                                   "tasks": {"P1.1": {"skills": ["user-skill"], "model": "opus"}}})
    check("composition patch applied", res["ok"])
    saved = _read_json(mpath)
    check("reviewSkill written", saved["meta"]["reviewSkill"] == "user-skill")
    check("task skills written", saved["phases"][0]["tasks"][0]["skills"] == ["user-skill"])
    check("task model written", saved["phases"][0]["tasks"][0]["model"] == "opus")
    check("non-composition data preserved",
          saved["phases"][0]["title"] == "P" and saved["meta"]["version"] == 2)

    # structural edits refused
    res = apply_composition(proj, {"phases": {"P1": {"title": "HACKED"}}})
    check("structural phase edit refused", not res["ok"] and
          _read_json(mpath)["phases"][0]["title"] == "P")
    res = apply_composition(proj, {"bugs": []})
    check("unknown patch section refused", not res["ok"])
    res = apply_composition(proj, {"tasks": {"P9.9": {"model": "x"}}})
    check("unknown task id refused", not res["ok"])

    # a patch that would make the manifest invalid is rejected + not written
    res = apply_composition(proj, {"tasks": {"P1.1": {"skills": "notalist"}}})
    check("bad skills type refused", not res["ok"])

    # lock respected
    open(mpath + ".lock", "w").close()
    res = apply_composition(proj, {"meta": {"reviewSkill": "x"}})
    check("write refused while locked", not res["ok"] and res.get("locked"))
    os.remove(mpath + ".lock")

    # --- the SHARDED layout ---------------------------------------------------
    # Everything above ran on a single-file manifest, and that is exactly why this
    # was broken in the field for so long: this repo's own manifest and the shipped
    # example are both sharded, and there the writer read the raw INDEX. Its phases
    # are stubs with no tasks in them, so every task edit was refused as "unknown
    # task" for a task the panel had just listed, phase edits went into a stub the
    # next load discards, and a meta-only save died on validator findings about
    # stubs missing fields stubs are not supposed to have.
    import shutil as _shutil
    _sproj = tempfile.mkdtemp(prefix="panel-sharded-")
    try:
        _atomic_write_json(_config_path(_sproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _sm = _manifest_path(_sproj, read_config(_sproj))
        os.makedirs(os.path.dirname(_sm), exist_ok=True)
        _full = {"meta": {"version": 3, "reviewSkill": None},
                 "phases": [
                     {"id": "P1", "title": "One", "status": "pending",
                      "review": {"model": "sonnet"},
                      "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                     {"id": "P2", "title": "Two", "status": "pending",
                      "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]}
        _mio.save_sharded(_sm, _full)
        _idx = _read_json(_sm)
        check("sharded fixture really is sharded", _mio.is_sharded(_idx))
        _p2shard = os.path.join(os.path.dirname(_sm), _idx["phases"][1]["shard"])
        _p2_before = open(_p2shard, "rb").read()

        res = apply_composition(_sproj, {
            "meta": {"reviewSkill": "sk"},
            "phases": {"P1": {"reviewModel": "opus"}},
            "tasks": {"P1.1": {"model": "haiku", "skills": ["a"]}}})
        check("sharded: a task the panel listed can actually be edited", res["ok"])
        check("sharded: the response names the layout it wrote",
              res.get("layout") == "sharded")
        _re = _mio.load_manifest(_sm)
        _p1 = [p for p in _re["phases"] if p["id"] == "P1"][0]
        check("sharded: task model + skills survive a reload",
              _p1["tasks"][0].get("model") == "haiku"
              and _p1["tasks"][0].get("skills") == ["a"])
        check("sharded: per-phase review model lands in the shard, not the stub "
              "that _merge_phase throws away",
              _p1.get("review", {}).get("model") == "opus")
        check("sharded: meta lands on the index", _re["meta"]["reviewSkill"] == "sk")
        # The whole point of shards is that two phase branches never touch the same
        # file. A writer that rewrites every shard would renormalize files nobody
        # edited and manufacture exactly the conflicts the layout exists to avoid.
        check("sharded: an untouched phase's shard is not rewritten at all",
              open(_p2shard, "rb").read() == _p2_before)
        check("sharded: only the touched files are reported written",
              sorted(res.get("written") or []) == sorted(
                  [os.path.relpath(os.path.join(os.path.dirname(_sm),
                                                _idx["phases"][0]["shard"]), _sproj),
                   os.path.relpath(_sm, _sproj)]))
        # A meta-only save used to fail with ~22 findings about phase stubs.
        res = apply_composition(_sproj, {"meta": {"reviewSkill": "sk2"}})
        check("sharded: a meta-only save is not blocked by findings about stubs",
              res["ok"] and not res.get("findings"))
        check("sharded: unknown task still refused", not apply_composition(
            _sproj, {"tasks": {"P9.9": {"model": "x"}}})["ok"])
    finally:
        _shutil.rmtree(_sproj, ignore_errors=True)

    # --- v0.28: the areas registry over HTTP ------------------------------------
    # `meta` lives on the INDEX in a sharded manifest, so a registry save must
    # touch the index and nothing else. That is the whole reason this goes through
    # apply_composition rather than writing the file itself: a second writer here
    # would be a second implementation of the targeted write-back, and the way it
    # would fail is by rewriting shards on a branch nobody is on.
    _aproj = tempfile.mkdtemp(prefix="panel-areas-")
    try:
        _atomic_write_json(_config_path(_aproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _am = _manifest_path(_aproj, read_config(_aproj))
        os.makedirs(os.path.dirname(_am), exist_ok=True)
        os.makedirs(os.path.join(_aproj, "services", "api"), exist_ok=True)
        _mio.save_sharded(_am, {
            "meta": {"version": 3,
                     "areas": {"api": {"root": "services/api", "description": "d",
                                       "reviewSkill": "backend-review"},
                               "unused": {"root": "services/api"}}},
            "phases": [
                {"id": "P1", "title": "One", "status": "pending", "area": "api",
                 "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                {"id": "P2", "title": "Two", "status": "pending", "area": "apu",
                 "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]})
        _aidx = _read_json(_am)
        _ashard = os.path.join(os.path.dirname(_am), _aidx["phases"][0]["shard"])
        _ashard_before = open(_ashard, "rb").read()

        _st = areas_state(_aproj)
        # `.get` and not `[...]`: a missing tag is exactly what a broken version of
        # this endpoint returns, and a KeyError exits 1 without naming which check
        # noticed — indistinguishable from a suite that crashed for another reason.
        _bytag = {t["tag"]: t for t in _st["tags"]}
        _tag = lambda name: _bytag.get(name) or {}          # noqa: E731
        check("areas GET returns the registry as stored",
              set(_st["areas"]) == {"api", "unused"})
        check("areas GET lists a registered tag with the phases using it",
              _tag("api").get("registered") and _tag("api").get("phases") == ["P1"])
        check("areas GET says a root that exists exists",
              _tag("api").get("rootExists") is True)
        check("areas GET lists a tag no entry covers - the typo case, which "
              "resolves to no reviewer and no skills",
              _tag("apu").get("registered") is False
              and _tag("apu").get("phases") == ["P2"])
        check("areas GET also lists a registered area no phase uses - a rename "
              "done on one side only looks exactly like this",
              _tag("unused").get("registered")
              and _tag("unused").get("phases") == [])
        check("areas GET carries the resolved reviewer of a registered area",
              _tag("api").get("reviewSkill") == "backend-review")

        _bad = write_areas(_aproj, {"areas": {"api": "services/api"}})
        check("areas PUT refuses a malformed registry, naming the entry",
              not _bad["ok"] and any("must be an object" in f
                                     for f in _bad["findings"]))
        check("...and a refused PUT wrote nothing",
              _read_json(_am)["meta"]["areas"].get("api") == {
                  "root": "services/api", "description": "d",
                  "reviewSkill": "backend-review"})
        # The shape is checked BEFORE the manifest is opened, and this is the case
        # that proves it rather than merely restating the validator: with a
        # manifest that cannot be parsed at all, the writer can only report the
        # parse error — so a caller who sent a bad body would be told nothing about
        # it, fix the manifest, and hit the same wall a second time.
        _saved = open(_am, "rb").read()
        with open(_am, "wb") as _fh:
            _fh.write(b"{ this is not json")
        _both = write_areas(_aproj, {"areas": {"api": "services/api"}})
        check("a malformed registry is named even when the manifest itself cannot "
              "be read - one round trip, both problems",
              not _both["ok"] and any("must be an object" in f
                                      for f in _both["findings"]))
        check("...while a WELL-formed registry over an unreadable manifest reports "
              "the manifest, so the two failures are never confused",
              any("cannot parse manifest" in f for f in
                  write_areas(_aproj, {"areas": {"api": {"root": "x"}}})["findings"]))
        with open(_am, "wb") as _fh:
            _fh.write(_saved)

        _res = write_areas(_aproj, {"areas": {"api": {"root": "services/api"},
                                              "web": {"root": "services/api"}}})
        check("areas PUT writes through the one composition writer", _res["ok"])
        check("areas PUT echoes the change as a row the confirm flow can print",
              [r["field"] for r in _res.get("applied") or []] == ["areas"])
        check("areas PUT touches the INDEX only - meta lives there, and rewriting "
              "a phase shard would manufacture a conflict on a branch nobody is on",
              _res.get("written") == [os.path.relpath(_am, _aproj)]
              and open(_ashard, "rb").read() == _ashard_before)
        _after = _read_json(_am)["meta"]["areas"]
        check("areas PUT replaces the registry wholesale, so dropping an area is "
              "an ordinary edit rather than something the API cannot express",
              set(_after) == {"api", "web"})
        check("...and the dropped area's phase tag now reads unregistered",
              {t["tag"]: t["registered"] for t in areas_state(_aproj)["tags"]}
              == {"api": True, "apu": False, "web": True})
        check("areas PUT accepts the bare registry as well as {areas: ...} - both "
              "readings of 'PUT the areas' are reasonable",
              write_areas(_aproj, {"api": {"root": "services/api"}})["ok"])
        _res = write_areas(_aproj, {"areas": {}})
        check("areas PUT can empty the registry", _res["ok"]
              and _read_json(_am)["meta"]["areas"] == {})
        check("a save that changes nothing still writes nothing",
              write_areas(_aproj, {"areas": {}}).get("unchanged") is True)
        _st2 = areas_state(_aproj)
        check("with no registry the tags list is still the truth about the phases",
              [t["tag"] for t in _st2["tags"]] == ["api", "apu"]
              and not any(t["registered"] for t in _st2["tags"]))
        _res = write_areas(_aproj, {"areas": {"api": {"root": "services/gone"}}})
        check("a root that is not on disk is written and WARNED about, not "
              "refused - the doctor reports it; the panel does not veto it",
              _res["ok"] and not areas_state(_aproj)["tags"][0]["rootExists"])
    finally:
        _shutil.rmtree(_aproj, ignore_errors=True)

    # --- v0.30: the capability policy ------------------------------------------
    # The resolution lives in _policy and is exercised there. What is checked here
    # is that this endpoint SHOWS what the guard hook will DO — same function, same
    # active areas — and that the one writer refuses what the validator refuses.
    _pproj = tempfile.mkdtemp(prefix="panel-policy-")
    try:
        os.makedirs(os.path.join(_pproj, ".claude"), exist_ok=True)
        # The capabilities this fixture resolves verdicts for are CREATED here,
        # project-local, rather than whatever `discover` happens to find on the
        # machine. A check that names `code-reviewer` because this laptop has one
        # installed is a check about the laptop: green here, absent on CI, and
        # silently vacuous either way.
        os.makedirs(os.path.join(_pproj, ".claude", "agents"), exist_ok=True)
        for _name in ("code-reviewer", "random-agent", "audit-executor"):
            with open(os.path.join(_pproj, ".claude", "agents", _name + ".md"),
                      "w", encoding="utf-8") as _fh:
                _fh.write("---\nname: %s\ndescription: fixture\n---\n" % _name)
        _atomic_write_json(os.path.join(_pproj, ".mcp.json"),
                           {"mcpServers": {"prod-db": {"command": "x"}}})
        _atomic_write_json(_config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _pm = _manifest_path(_pproj, read_config(_pproj))
        os.makedirs(os.path.dirname(_pm), exist_ok=True)
        _atomic_write_json(_pm, {
            "meta": {"version": 2, "areas": {"api": {"root": "."}}},
            "phases": [
                {"id": "P1", "title": "One", "status": "in_progress", "area": "api",
                 "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                {"id": "P2", "title": "Two", "status": "pending", "area": "web",
                 "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]})

        _ps = policy_state(_pproj)
        check("policy GET reports the shipped block as inert, so a repo that never "
              "opted in is not shown a governance surface that governs nothing",
              _ps["active"] is False and _ps["stored"] is None
              and _ps["policy"]["skills"]["default"] == "allow")
        check("policy GET resolves a verdict for every kind, even inert",
              set(_ps["resolved"]) == set(_policy.KINDS))
        check("policy GET reports the ACTIVE areas, which is what scopes an area "
              "rule - and only the phases with work in progress count",
              _ps["activeAreas"] == ["api"] and "web" in _ps["areas"])

        _bad = write_policy(_pproj, {"skills": {"default": "denied"}})
        check("policy PUT refuses a misspelled default in the policy's own words",
              not _bad["ok"] and any("policy.skills.default" in f
                                     for f in _bad["findings"]))
        check("...and a refused PUT wrote nothing",
              read_config(_pproj).get("policy") is None)
        # The policy is checked BEFORE the config is assembled, and this is the case
        # that proves it rather than restating the validator: with an unrelated
        # finding already in the file, a writer that only validated the assembled
        # config would answer with both — and the caller, who sent a policy, would
        # be told about a threshold they did not touch.
        _atomic_write_json(_config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json",
                            "trivialLineThreshold": 0})
        _only = write_policy(_pproj, {"skills": {"default": "denied"}})
        check("a bad policy is reported ALONE, even when the config it would join "
              "already has a finding of its own",
              not _only["ok"]
              and all(f.startswith("policy.") for f in _only["findings"]),
              )
        _atomic_write_json(_config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _req = write_policy(_pproj, {"agents": {"deny": ["audit:*"]}})
        check("policy PUT refuses a policy denying audit's own components - the "
              "line would not take effect, so saving it would leave a file that "
              "says something untrue",
              not _req["ok"] and any("not deniable" in f for f in _req["findings"]))
        check("...and that refusal is the VALIDATOR's, so the panel and the CLI "
              "cannot disagree about what is saveable",
              any("not deniable" in f for f in
                  _cores()[1].validate_config({"policy": {"agents": {
                      "deny": ["audit:*"]}}})[0]))

        _res = write_policy(_pproj, {"skills": {"default": "deny",
                                                "allow": ["dataviz"]}})
        check("policy PUT writes through the one config writer", _res["ok"])
        check("...which echoes the change as rows the confirm flow can print",
              any(r["field"].startswith("policy.")
                  for r in _res.get("applied") or []),
              )
        check("...and reports the journal outcome like every other save",
              "journaled" in _res)
        check("the block landed in the config file itself",
              read_config(_pproj)["policy"]["skills"]["default"] == "deny")
        check("a save that changes nothing writes nothing",
              write_policy(_pproj, {"skills": {"default": "deny",
                                               "allow": ["dataviz"]}}
                           ).get("unchanged") is True)
        check("policy PUT accepts {policy: ...} as well as the bare block",
              write_policy(_pproj, {"policy": {"skills": {"default": "allow"}}})["ok"])
        check("policy PUT can empty the block back to inert",
              write_policy(_pproj, {})["ok"]
              and policy_state(_pproj)["active"] is False)

        # The preview IS the guard's answer. Asserted against _policy.resolve rather
        # than against a second expectation written here: a check whose oracle is a
        # copy of the thing under test proves only that two copies agree.
        # `deny: ["*"]` would be refused by the writer — it matches audit's own
        # names — so the deny-everything shape is written the way the validator
        # accepts it: a default of deny, which `resolve` reaches only after the
        # required check has already let audit's own through.
        write_policy(_pproj, {"skills": {"default": "deny", "allow": ["dataviz"]},
                              "agents": {"default": "deny",
                                         "areas": {"api": {"allow": ["code-*"]},
                                                   "web": {"allow": ["never-*"]}}}})
        _ps = policy_state(_pproj)
        _pol = _policy.policy_cfg(read_config(_pproj))
        _rows = _ps["resolved"]["agents"]
        # `.get`, not `[...]`: a row that is missing is exactly what a broken
        # endpoint returns, and a KeyError exits 1 without naming which check
        # noticed — indistinguishable from a suite that crashed for another reason.
        _by_pre = lambda rows: {r["name"]: r for r in rows}       # noqa: E731
        check("every resolved row is exactly what the guard hook would decide, "
              "including the basis it would print",
              bool(_rows) and all(
                  r["verdict"] == _policy.resolve(
                      _pol, "agents", r["name"], active_tags=["api"])["verdict"]
                  and r["basis"] == _policy.resolve(
                      _pol, "agents", r["name"], active_tags=["api"])["basis"]
                  for r in _rows))
        check("audit's own agent is marked required and allowed through a policy "
              "that denies everything - and it is the FIXTURE's copy, not one this "
              "machine happens to have installed",
              (_by_pre(_rows).get("audit-executor") or {}).get("required") is True
              and (_by_pre(_rows).get("audit-executor") or {}).get("verdict")
              == "allow")
        check("somebody else's agent under the same policy resolves to a violation",
              (_by_pre(_rows).get("random-agent") or {}).get("verdict")
              == "violation")
        # The preview must apply the ACTIVE areas, not merely the project-wide
        # rules: `api` has a phase in progress and `web` does not, so one area's
        # allow list is in force and the other's is not. Resolved with no active
        # areas at all, every one of these rows would read "violation".
        _by = _by_pre(_rows)
        check("an area's allow list is applied because that area has work in "
              "progress, and the row says which area answered",
              (_by.get("code-reviewer") or {}).get("verdict") == "allow"
              and (_by.get("code-reviewer") or {}).get("area") == "api",
              )
        check("...while an area with nothing running grants nothing",
              all(r["area"] != "web" for r in _rows))
        check("an MCP row is a STAND-IN for the whole server and says so, since "
              "what is discoverable is a server name and a policy matches tool "
              "names - and there IS a row, so this is not vacuously true",
              "mcp__prod-db__*" in [r["name"] for r in _ps["resolved"]["mcp"]]
              and all(r["standIn"] and r["name"].startswith("mcp__")
                      and r["name"].endswith("__*")
                      for r in _ps["resolved"]["mcp"]))

        # --- panel c7: what the switchboard needs beyond the verdicts ----------
        # The switches on that form can only write EXACT names. Everything else a
        # policy may legally contain — a glob, a rule for something nobody has
        # installed, a rule for a dormant area — is invisible to them, and the PUT
        # replaces the block WHOLESALE. A rule the form cannot show is therefore a
        # rule it would silently destroy, which is why the raw block travels too.
        _rules = _ps["rules"]["agents"]
        check("every pattern in the block is reported, in the order resolve reads "
              "them: deny before allow, project before area",
              [(r["scope"], r["list"], r["pattern"]) for r in _rules]
              == [("api", "allow", "code-*"), ("web", "allow", "never-*")])
        # Counted against `_policy.matches` over the rows this endpoint served, not
        # against a number written here: the machine running this has its own agents
        # installed, and "code-* matches exactly one" would be a claim about the
        # laptop — true here, false on CI, and vacuous either way.
        _codes = [r["name"] for r in _rows if _policy.matches(r["name"], ["code-*"])]
        check("...and each says what it matches TODAY, through the same matcher the "
              "guard matches with",
              "code-reviewer" in _codes
              and [r["n"] for r in _rules if r["pattern"] == "code-*"]
              == [len(_codes)])
        check("deny is listed before allow within a scope, because that is the "
              "order the verdict is decided in",
              [(r["list"], r["pattern"]) for r in _policy_rules(
                  {"skills": {"allow": ["a"], "deny": ["d"]}}, "skills", [])]
              == [("deny", "d"), ("allow", "a")])
        # A rule that matches nothing is the one a table of capabilities cannot
        # show at all, and the one most likely to be a typo. Dropping it here would
        # be the form quietly deleting it on the next save.
        check("a pattern matching nothing installed is still listed, and says it "
              "matches nothing rather than being left out",
              [r["n"] for r in _rules if r["pattern"] == "never-*"] == [0])
        _many = _policy_rules({"skills": {"deny": ["a*"]}}, "skills",
                              ["a%d" % i for i in range(9)])
        check("a pattern covering more names than fit is capped for display while "
              "the count stays true - a truncated list read as the total would "
              "understate what one rule decides",
              _many[0]["n"] == 9 and len(_many[0]["matches"]) == 6)
        check("a blank or non-string pattern is skipped rather than rendered as an "
              "empty rule nobody can remove",
              _policy_rules({"skills": {"deny": ["  ", "", 7, "real"]}},
                            "skills", []) == [
                  {"scope": None, "list": "deny", "pattern": "real",
                   "matches": [], "n": 0}])
        # Called through a wrapper so the failure is a named FAIL and not a
        # traceback: this endpoint feeds a form, a form's job is to survive a file
        # somebody hand-edited, and an assertion that dies while proving that
        # reports the wrong thing twice over — nothing about the defect, and a
        # crash that looks like one.
        def _rules_safe(pol, kind, names):
            try:
                return _policy_rules(pol, kind, names)
            except Exception as exc:                 # noqa: BLE001 - that is the check
                return "raised %s" % type(exc).__name__
        check("a malformed kind block yields no rules instead of raising",
              _rules_safe({"skills": "nonsense"}, "skills", ["x"]) == []
              and _rules_safe({}, "skills", ["x"]) == []
              and _rules_safe({"skills": {"deny": "nope"}}, "skills", ["x"]) == [])

        # Every area a rule can be aimed at, and whether it decides anything today.
        _ainfo = {a["tag"]: a for a in _ps["areaInfo"]}
        check("the area columns cover every tag a rule could name, and mark which "
              "are live - an area rule is inert until that area has work in "
              "progress, and a column that does not say so is a trap",
              sorted(_ainfo) == _ps["areas"]
              and _ainfo["api"]["active"] is True
              and _ainfo["web"]["active"] is False)
        check("...and say which of them the registry actually knows, since a rule "
              "may legitimately be written for a free-text tag",
              _ainfo["api"]["registered"] is True
              and _ainfo["web"]["registered"] is False)

        # Whether anything is enforcing any of this. A page full of `deny` verdicts
        # that cannot say whether the hook has ever run would be claiming
        # enforcement nobody has - the doctor's warning, on the surface that shows
        # the denials.
        check("with no marker, enforcement is reported as never seen rather than "
              "assumed",
              _ps["enforcement"] == {"seen": False, "ageDays": None})
        _sd = str(_cores()[3].state_dir(pathlib.Path(_pproj), read_config(_pproj)))
        os.makedirs(_sd, exist_ok=True)
        _gc = _load("audit_guard_capabilities_t",
                    os.path.join(_HERE, "..", "hooks", "guard-capabilities.py"))
        with open(os.path.join(_sd, _gc.SEEN_FILE), "w", encoding="utf-8") as _fh:
            _fh.write("{}")
        _pe = _policy_enforcement(_pproj, read_config(_pproj))
        check("with the guard's own marker present it is reported as seen, with an "
              "age and no verdict about whether that age is too old - how stale is "
              "too stale is /audit:doctor's judgement, and a second threshold here "
              "is one that can disagree with it",
              _pe["seen"] is True and _pe["ageDays"] is not None
              and _pe["ageDays"] < 1 and set(_pe) == {"seen", "ageDays"})
        check("...and it is found at the path the hook writes: the config's own "
              "state_dir and the hook's own SEEN_FILE, neither spelled out twice",
              os.path.isfile(os.path.join(_sd, _gc.SEEN_FILE))
              and _gc.SEEN_FILE == "capability-guard.json")
        check("an unreadable project reports never-seen rather than raising",
              _policy_enforcement(os.path.join(_pproj, "nope"), {})["seen"] is False)
    finally:
        _shutil.rmtree(_pproj, ignore_errors=True)

    # --- v0.31: the help endpoint ------------------------------------------------
    # The drawer that consumes this lands with panel c8; the endpoint ships now, and
    # is exercised here rather than left as untested code until it has a caller —
    # the one thing v0.29's journal call site taught, in the other direction.
    _help_pay = help_state()
    # Read the handler's own source, sliced at the method boundaries: counting the
    # string over the whole file would count this check as a route.
    _hsrc = _src_of_this_file()
    _get_src = _hsrc.split("def do_GET")[1].split("def do_PUT")[0]
    _write_src = _hsrc.split("def do_PUT")[1].split("def _free_port")[0]
    check("GET /api/help is a route, and only a GET: help is a document, and a "
          "drawer that could write one would be a second config writer",
          'if path == "/api/help"' in _get_src and "/api/help" not in _write_src)
    check("...and it serves _help.payload() rather than a second assembly of the "
          "same thing", _help_pay == _help.payload())
    _hcfg = _help_pay["fields"]["config"]
    _unexplained = [p for p in _settings_paths()
                    if not (_help.lookup(_hcfg, p) or {}).get("description")]
    check("every control the Settings form renders can be explained from the "
          "SCHEMA - the drawer's whole contract, and the reason none of this text "
          "is retyped here: %r" % (_unexplained,), not _unexplained)
    _hman = _help_pay["fields"]["manifest"]
    _uncomp = [k for k, p in _help_pay["composition"].items()
               if not (_help.lookup(_hman, p) or {}).get("description")]
    check("...and so can every composition lever, under the panel's own name for "
          "it: %r" % (_uncomp,), not _uncomp)
    check("the four concept pages arrive whole, so the drawer has topics and not "
          "just tooltips",
          sorted(t["id"] for t in _help_pay["topics"])
          == ["areas", "gate-tiers", "journal", "policy"]
          and all(t["title"] and t["paragraphs"] for t in _help_pay["topics"]))
    check("the guide agent's card rides along with the tools its own file grants, "
          "so an 'Ask audit-guide' hint cannot offer a capability it does not have",
          (_help_pay["agent"] or {}).get("name") == "audit-guide"
          and (_help_pay["agent"] or {}).get("readOnly") is True
          and (_help_pay["agent"] or {}).get("model") == "haiku")
    check("the payload is documentation, not state: it names no path on this "
          "machine, so it cannot be read as a report about this project",
          _HERE not in json.dumps(_help_pay)
          and os.path.dirname(_HERE) not in json.dumps(_help_pay))

    check("meta.areas is on the composition allow-list, so it goes through the "
          "writer that locks, validates and journals", "areas" in _META_KEYS
          and _reject_unknown({"meta": {"areas": {}}}) is None)
    check("...and nothing else was let in with it",
          _reject_unknown({"meta": {"phases": {}}}) is not None)
    # The confirm dialog computes its rows in the browser and the server recomputes
    # them from the file; a key on one list and not the other is a mismatch warning
    # about nothing. Derived, so adding a meta key cannot leave the two out of step.
    check("the dialog's meta fields are exactly the ones the FORM can edit",
          "for(const k of %s)" % json.dumps(list(_META_FORM_KEYS)).replace(
              '"', "'").replace(", ", ",") in UI_HTML,
          )
    check("an API-only meta key is deliberately absent from that list - the "
          "dialog must not describe an edit this form cannot make",
          all("'%s'" % k not in UI_HTML.split("function compChanges")[1][:400]
              for k in _META_API_ONLY))

    # --- c6: what a save would change, who is making it, and the record of it ---
    # The rows the confirm dialog lists ARE the rows the server echoes as
    # `applied`; the client compares the two. Everything below is about those two
    # lists being computable from the same pair of values.
    check("a leaf path per row, not a block per row",
          _flat_paths({"usage": {"bands": {"highUSD": 1}}, "enforce": True})
          == {"usage.bands.highUSD": 1, "enforce": True})
    check("an empty object is a leaf, so emptying a block is still a change",
          _flat_paths({"usage": {}}) == {"usage": {}})
    check("a list is a leaf: a changed list is one row, not one row per element",
          _flat_paths({"secretPatterns": {"extra": ["a", "b"]}})
          == {"secretPatterns.extra": ["a", "b"]})
    # The WHOLE path, not the leaf's own name: `highUSD` alone would not say which
    # of the settings called that had moved.
    check("config diff names the dotted path and both sides",
          _config_changes({"usage": {"bands": {"highUSD": 1}}},
                          {"usage": {"bands": {"highUSD": 2}}})
          == [{"target": "config", "field": "usage.bands.highUSD",
               "from": 1, "to": 2}])
    check("config diff: an untouched key is not a change",
          _config_changes({"a": 1, "b": 2}, {"a": 1, "b": 3})
          == [{"target": "config", "field": "b", "from": 2, "to": 3}])
    # Deleting a key is how "use the default" is written, and a key whose value was
    # already null would vanish from a diff that only compared .get() results.
    check("config diff: removing a null key is still a change",
          [r["field"] for r in _config_changes({"x": None}, {})] == ["x"])

    _cm = _mio.load_manifest(mpath)
    check("composition diff reads `from` off the manifest, not off the patch",
          _composition_changes(_cm, {"tasks": {"P1.1": {"model": "haiku"}}})
          == [{"target": "P1.1", "field": "model",
               "from": "opus", "to": "haiku"}])
    check("composition diff drops a field set back to what it already held",
          _composition_changes(_cm, {"tasks": {"P1.1": {"model": "opus"}}}) == [])
    check("composition diff covers meta and the per-phase review model",
          [(r["target"], r["field"]) for r in _composition_changes(_cm, {
              "meta": {"reviewSkill": "other"},
              "phases": {"P1": {"reviewModel": "haiku"}}})]
          == [("meta", "reviewSkill"), ("P1", "review model")])
    check("composition diff skips an unknown id (the patch refuses it a line later)",
          _composition_changes(_cm, {"tasks": {"P9.9": {"model": "x"}}}) == [])
    # The `from` side has to be the value the FORM shows. _composition_view turns a
    # missing skills key into [], so reading the raw None here would make adding a
    # skill read as `null -> [a]` on the server and `[] -> [a]` in the browser, and
    # the panel would warn about a disagreement that is only a normalisation.
    _nos = {"meta": {}, "phases": [{"id": "PX", "tasks": [{"id": "PX.1"}]}]}
    check("composition diff normalises skills exactly as the view does",
          _composition_changes(_nos, {"tasks": {"PX.1": {"skills": ["a"]}}})
          == [{"target": "PX.1", "field": "skills", "from": [], "to": ["a"]}]
          and _composition_view(_nos)["tasks"][0]["skills"] == [])
    check("composition diff: an empty skills list set to empty is not a change",
          _composition_changes(_nos, {"tasks": {"PX.1": {"skills": []}}}) == [])

    # The response the client compares against.
    res = apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("a composition save echoes exactly what it applied",
          res["ok"] and res["applied"] == [{"target": "P1.1", "field": "model",
                                            "from": "opus", "to": "sonnet"}])
    _mtime = os.path.getmtime(mpath)
    res = apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("a save that changes nothing writes nothing and says so",
          res["ok"] and res.get("unchanged") is True and res["applied"] == []
          and res.get("written") == [] and os.path.getmtime(mpath) == _mtime)
    _cfg_now = read_config(proj)
    res = write_config(proj, dict(_cfg_now))
    check("the same rule for the config: nothing changed, nothing written",
          res["ok"] and res.get("unchanged") is True and res["applied"] == [])
    res = write_config(proj, dict(_cfg_now, trivialLineThreshold=41))
    check("a config save echoes the dotted path it changed",
          res["ok"] and res["applied"] == [
              {"target": "config", "field": "trivialLineThreshold",
               "from": 40, "to": 41}])

    # --- the journal call site ---------------------------------------------------
    # This call site shipped in v0.28, one release BEFORE audit-journal.py, and was
    # exercised against the stubs below so it would not be untested code in the
    # meantime. The module is here now, so the last case in this block is the real
    # thing end to end — but the stubs stay: they are the only way to reach the two
    # fail-soft branches, and "the journal is absent" is still what an older
    # install looks like.
    _saved_j0 = dict(_JOURNAL)
    try:
        _JOURNAL.update({"tried": True, "mod": None})
        check("no journal on this install -> journaled false, and it says WHY",
              _journal(proj, read_config(proj), "config.write", "x", [])
              == {"journaled": False, "journaledWhy": "unavailable"})
    finally:
        _JOURNAL.clear()
        _JOURNAL.update(_saved_j0)
    check("...and on THIS install there is one, so the load resolves to the "
          "module rather than to None (the case above is a simulation now)",
          _journalmod() is not None and hasattr(_journalmod(), "append"))

    class _JStub(object):
        rows = []

        @staticmethod
        def append(project, entry):
            _JStub.rows.append((project, entry))
            return True

    class _JBroken(object):
        @staticmethod
        def append(project, entry):
            raise RuntimeError("disk on fire")

    _saved_j = dict(_JOURNAL)
    try:
        _JOURNAL.update({"tried": True, "mod": _JStub})
        _rows = [{"target": "P1.1", "field": "model",
                  "from": "opus", "to": "sonnet"}]
        out = _journal(proj, read_config(proj), "composition.write", "m.json", _rows)
        _ent = _JStub.rows[-1][1] if _JStub.rows else {}
        check("with a journal present the row is appended and reported",
              out == {"journaled": True} and len(_JStub.rows) == 1)
        check("the journal row carries the contract's fields, not this file's",
              _ent.get("action") == "composition.write"
              and _ent.get("target") == "m.json"
              and set(_ent) == {"action", "target", "summary", "actor"})
        check("the actor is the viewer, tagged with how the write arrived",
              (_ent.get("actor") or {}).get("via") == "panel"
              and (_ent.get("actor") or {}).get("sessionId") == _panel_session())
        check("the changes travel in the summary the row does have room for",
              "P1.1 model: opus -> sonnet" in (_ent.get("summary") or "")
              and (_ent.get("summary") or "").startswith("1 change(s)"))
        _JOURNAL.update({"tried": True, "mod": _JBroken})
        # Caught HERE as well: "fail-soft" means the exception does not leave
        # _journal, so a version that let it through would take this suite down
        # with a traceback instead of failing the one case that is about it.
        try:
            _fs = _journal(proj, read_config(proj), "x", "y", [])
        except Exception as exc:                                # pragma: no cover
            _fs = "it raised: %s" % exc
        check("a journal that throws never breaks the write it is recording",
              _fs == {"journaled": False, "journaledWhy": "failed"})
        _JOURNAL.update({"tried": True, "mod": _JStub})
        _JStub.rows = []
        res = apply_composition(proj, {"tasks": {"P1.1": {"model": "opus"}}})
        check("a real save appends one row and reports journaled",
              res["ok"] and res.get("journaled") is True and len(_JStub.rows) == 1)
    finally:
        _JOURNAL.clear()
        _JOURNAL.update(_saved_j)

    # --- ...and the same path with the REAL module behind it (v0.29) ------------
    # The stubs above prove the call site. They cannot prove that a save produces a
    # row anyone can verify, which is the only claim this feature actually makes —
    # so this drives the panel's own writer, then asks audit-journal.py, not the
    # panel, whether the chain holds.
    _jmod = _journalmod()
    _before = len(_jmod.read_all(proj, read_config(proj)))
    res = apply_composition(proj, {"tasks": {"P1.1": {"model": "haiku"}}})
    _after = _jmod.read_all(proj, read_config(proj))
    check("a real composition save appends a real row and says it was logged",
          res.get("journaled") is True and len(_after) == _before + 1)
    _row = _after[-1] if _after else {}
    check("the row names the change in the same words the dialog showed",
          "P1.1 model:" in (_row.get("summary") or "")
          and "haiku" in (_row.get("summary") or ""))
    check("...and it names the panel as the writer, with the viewer as the author",
          (_row.get("actor") or {}).get("via") == "panel"
          and (_row.get("actor") or {}).get("author")
          == _viewer(proj, read_config(proj)).get("author"))
    check("the row records the manifest as it stood after the write - which is "
          "what makes a later change with no row to explain it visible",
          bool(_row.get("stateHash")))
    _jv = _jmod.verify(proj, read_config(proj))
    check("the chain the panel wrote verifies",
          _jv["ok"] and not _jv["findings"])
    _jst = journal_state(proj)
    check("GET /api/journal reports the rows newest first, with the verdict beside "
          "them - a list with no verdict invites trust, a verdict with no list is "
          "a claim about something you cannot see",
          _jst["available"] and _jst["verify"]["ok"]
          and _jst["rows"] and _jst["rows"][0].get("hash") == _row.get("hash"))
    check("...and the verdict counts the rows the reader actually sees - a "
          "hardcoded `ok` beside a list nobody checked is the failure this "
          "endpoint exists to avoid",
          _jst["verify"]["rows"] == len(_after) and _jst["verify"]["exists"])
    check("...and it says where the journal is, relative to the project",
          isinstance(_jst["dir"], str) and not os.path.isabs(_jst["dir"]))
    _saved_j2 = dict(_JOURNAL)
    try:
        _JOURNAL.update({"tried": True, "mod": None})
        _jst0 = journal_state(proj)
        check("an install with no journal module answers `not available` rather "
              "than 404 - there being no journal here is an answer",
              _jst0["available"] is False and _jst0["rows"] == []
              and _jst0["verify"] is None)
    finally:
        _JOURNAL.clear()
        _JOURNAL.update(_saved_j2)
    # A config save is journalled too, under its own action.
    _cfg_j = read_config(proj)
    write_config(proj, dict(_cfg_j, trivialLineThreshold=43))
    _acts = [r.get("action") for r in _jmod.read_all(proj, read_config(proj))]
    check("a config save is recorded under its own action - the rules changing is "
          "not the same event as the plan changing",
          "config.write" in _acts and "composition.write" in _acts)
    # Off means off, on both surfaces.
    write_config(proj, dict(read_config(proj), journal={"enabled": False}))
    _n_off = len(_jmod.read_all(proj, read_config(proj)))
    res = apply_composition(proj, {"tasks": {"P1.1": {"model": "sonnet"}}})
    check("with journal.enabled false a save still succeeds, writes no row, and "
          "does NOT claim to have been logged",
          res["ok"] and res.get("journaled") is False
          and len(_jmod.read_all(proj, read_config(proj))) == _n_off)
    write_config(proj, dict(read_config(proj), journal={"enabled": True}))

    check("a change renders the same way for the journal as for the dialog",
          _fmt_change({"target": "P1.2", "field": "model",
                       "from": None, "to": "opus"}) == "P1.2 model: (unset) -> opus"
          and _fmt_change({"target": "P1.2", "field": "skills",
                           "from": [], "to": ["a"]}) == 'P1.2 skills: [] -> ["a"]')
    check("...including a boolean, which the browser spells `true` and str() "
          "spells `True` - a value nobody can type into the JSON file they are "
          "being told about",
          _fmt_change({"target": "config", "field": "enforce",
                       "from": False, "to": True})
          == "config enforce: false -> true")
    check("a number is not quoted and a string is not JSON-escaped - the line is "
          "prose about a JSON file, not JSON",
          _fmt_change({"target": "config", "field": "trivialLineThreshold",
                       "from": 40, "to": 41})
          == "config trivialLineThreshold: 40 -> 41"
          and "\"opus\"" not in _fmt_change({"target": "t", "field": "model",
                                             "from": "a", "to": "opus"}))

    # --- who is looking --------------------------------------------------------
    _vw = _viewer(proj, read_config(proj))
    check("the panel knows who is driving it, and in which mode",
          isinstance(_vw, dict) and set(_vw) == {"author", "mode"}
          and isinstance(_vw["mode"], str))
    check("viewer travels with the state, so the topbar can name the writer",
          isinstance(build_state(proj).get("viewer"), dict))
    _vprev = open(_config_path(proj), encoding="utf-8").read()
    try:
        with open(_config_path(proj), "w", encoding="utf-8") as fh:
            json.dump({"usage": {"authorMode": "none"}}, fh)
        _vn = _viewer(proj, read_config(proj))
        # .get(), not [] — a viewer missing a key is the case the check above is
        # about, and a KeyError here would take the suite down before it printed.
        check("authorMode none means no name — a decision, not a failure",
              _vn.get("mode") == "none" and _vn.get("author") is None)
    finally:
        with open(_config_path(proj), "w", encoding="utf-8") as fh:
            fh.write(_vprev)

    # build_state shape
    st = build_state(proj)
    check("build_state has rollup + composition",
          st["rollup"] is not None and "reviewSkill" in st["composition"]["meta"])
    check("build_state reports manifestPath", bool(st["manifestPath"]))
    check("build_state carries the bug rows the Overview lists",
          isinstance(st.get("bugs"), list)
          and build_state(tmp)["bugs"] == [])   # no manifest -> empty, never absent

    # D9 — runStatus ("who's running what"): per-phase lock + claim
    check("build_state has runStatus",
          isinstance(st.get("runStatus"), dict) and "phases" in st["runStatus"])
    ld = os.path.join(tmp, "audit-locks")
    os.makedirs(ld)
    _atomic_write_json(os.path.join(ld, "index.lock"), {"hostname": "hi", "startedAt": "t"})
    _atomic_write_json(os.path.join(ld, "phase-P1.lock"), {"hostname": "hp", "startedAt": "t2"})
    li = _lock_info(ld)
    check("_lock_info reads the index lock", (li["index"] or {}).get("hostname") == "hi")
    check("_lock_info reads a phase lock", (li["phases"].get("P1") or {}).get("hostname") == "hp")

    # C1 — the badge says "running", which is a claim about a live process.
    import platform as _pf
    import subprocess as _sp
    import time as _t
    _here = _pf.node()
    _old = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() - 95 * 60))
    _atomic_write_json(os.path.join(ld, "phase-P2.lock"),
                       {"hostname": _here, "pid": os.getpid(), "startedAt": _old})
    _d = _sp.Popen([sys.executable, "-c", "pass"]); _d.wait()
    _atomic_write_json(os.path.join(ld, "phase-P3.lock"),
                       {"hostname": _here, "pid": _d.pid,
                        "startedAt": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())})
    li = _lock_info(ld)
    check("lock verdict: a 95-min-old run with a live pid is live",
          li["phases"]["P2"].get("live") is True)
    check("lock verdict: a 1-min-old run whose pid is gone is not",
          li["phases"]["P3"].get("live") is False)
    check("lock verdict: each carries the basis behind it",
          bool(li["phases"]["P2"].get("liveBasis"))
          and bool(li["phases"]["P3"].get("liveBasis")))
    check("lock verdict: a pid-less lock gets one too (age fallback)",
          li["phases"]["P1"].get("live") is not None)
    check("the UI badges an abandoned lock differently from a running one",
          "no live run" in UI_HTML and ".badge.held" in UI_HTML)
    os.remove(os.path.join(ld, "phase-P2.lock"))
    os.remove(os.path.join(ld, "phase-P3.lock"))
    m2 = _read_json(mpath)
    m2["phases"][0]["claim"] = {"sessionId": "sess-abcd1234", "host": "h", "branch": "audit/p1"}
    _atomic_write_json(mpath, m2)
    st2 = build_state(proj)
    check("runStatus surfaces a phase claim from the manifest",
          ((st2["runStatus"]["phases"].get("P1") or {}).get("claim") or {}).get("sessionId")
          == "sess-abcd1234")
    check("runStatus phase lock is None when the git-dir lock isn't held (non-git tmp)",
          (st2["runStatus"]["phases"].get("P1") or {}).get("lock") is None)
    # D9, second half: the badges were a snapshot taken at page load, so a colleague
    # taking a phase lock in another worktree showed up only if you reloaded.
    check("D9: run status is served on its own endpoint, so the poll never has to "
          "refetch full state",
          "/api/runstatus" in UI_HTML
          and _run_status(tmp, {}, {}) is not None)
    check("D9: and the poll repaints ONLY Overview - re-rendering from full state "
          "would discard whatever is half-typed in the settings form",
          "if(!$('#over').classList.contains('hidden'))renderOver();" in UI_HTML
          and "renderSettings()" not in UI_HTML[UI_HTML.index("async function pollRunStatus"):
                                                UI_HTML.index("// ---------- Overview")])
    check("D9: it skips identical payloads rather than repainting on a timer",
          "runStatusKey(next)===runStatusKey(RUNSTATUS)" in UI_HTML)
    check("D9: it stops while the tab is hidden, and catches up on return",
          "if(document.hidden)return;" in UI_HTML
          and "visibilitychange" in UI_HTML)
    check("D9: a failed poll leaves a stale badge rather than killing the panel",
          "catch(e){/* a panel that dies because a poll failed" in UI_HTML)

    # v0.16 — composition view surfaces per-phase area (list) + reviewSkill;
    # a phase can carry cross-cutting tags (['backend','security'])
    m3 = _read_json(mpath)
    m3["phases"][0].update(area=["backend", "security"], reviewSkill="backend-review")
    _atomic_write_json(mpath, m3)
    cv = _composition_view(_mio.load_manifest(mpath))
    check("composition view carries area list + reviewSkill",
          cv["phases"][0].get("area") == ["backend", "security"]
          and cv["phases"][0].get("reviewSkill") == "backend-review")
    st3 = build_state(proj)
    check("rollup normalizes area to a list + groups under each tag",
          st3["rollup"]["phases"][0].get("area") == ["backend", "security"]
          and "backend" in (st3["rollup"].get("areas") or {})
          and "security" in (st3["rollup"].get("areas") or {}))
    check("_areas_of normalizes string/list/absent",
          _areas_of("x") == ["x"] and _areas_of(["a", "b"]) == ["a", "b"]
          and _areas_of(None) == [])
    check("UI renders area badges (per tag) + area-searchable composition",
          ".badge.area" in UI_HTML and "P.area" in UI_HTML
          and "(p.area||[]).map" in UI_HTML)

    # UI template integrity (token/project placeholders present, no stray %)
    check("UI has token placeholder", "__AUDIT_TOKEN__" in UI_HTML)
    check("UI has project placeholder", "__AUDIT_PROJECT__" in UI_HTML)
    check("UI token injected as a quoted JS string",
          'const TOKEN="abc123"' in UI_HTML.replace("__AUDIT_TOKEN__", _js("abc123")))
    # `list:` alone was the spelling here, and it is not a datalist — it matched
    # `{scope, list: 'deny', pattern}` in the policy view, which is a field name.
    # A native datalist needs the ATTRIBUTE, which in this file's `el()` calls is
    # always `list:'…'`, and the element it points at.
    check("UI uses the custom combobox, not a native datalist",
          "function comboWrap(" in UI_HTML and "combo-menu" in UI_HTML
          and "<datalist" not in UI_HTML and "list:'" not in UI_HTML)
    check("UI labels carry info hints", "function hint(" in UI_HTML and "data-tip" in UI_HTML)
    # --- Settings: the whole config, named by what it does ---------------------
    # The coverage checks (SETTINGS_GROUPS/FIELD_HELP derived against
    # validate-config's own key sets) moved to _panel_settings.py's own selftest
    # (P12.1) — they need no UI_HTML and no server source. What stays here needs
    # one or the other.
    _vc = _cores()[1]
    # `policy` is a root key with no control on this form, on purpose — the one
    # exemption, and it is stated rather than silently subtracted. It is not a
    # setting with a value; it is a rule set whose meaning is the verdict it
    # produces for each installed capability, which is what /api/policy serves and
    # what the **Policy tab** renders, switch by switch. A generic text box over it
    # would be a JSON editor wearing a label.
    _settings_exempt = {"policy"}
    check("the exempt key is served by its own endpoint instead of simply being "
          "missing from the panel",
          all('if path == "/api/%s"' % k in _src_of_this_file()
              for k in _settings_exempt))
    check("a field whose default is null can still say what empty means - an "
          "empty box beside an empty placeholder says nothing at all",
          "placeholder:def==null?(f.placeholder||''):String(def)" in UI_HTML
          and "beside the manifest" in UI_HTML)
    check("the form's shape, its help and its enums are injected from Python - "
          "the JS literal they replaced is what let the two drift",
          "const DESC={" not in UI_HTML
          and "const SETTINGS=" in UI_HTML and "__SETTINGS__" not in UI_HTML
          and "__FIELD_HELP__" not in UI_HTML and "__CFG_ENUMS__" not in UI_HTML
          and FIELD_HELP["usage.pricingAsOf"] in UI_HTML)
    # `warn-always` was documented in four places, implemented, and rejected by the
    # validator — so following the docs produced a config the panel refused to save.
    # A hand-kept <option> list is that failure with one more place to forget.
    check("the enum choices ARE the validator's tuples, not a copy of them",
          json.dumps(_cfg_enums(), sort_keys=True) in UI_HTML
          and set(_cfg_enums()["inProgressPolicy"]) == set(_vc.IN_PROGRESS_POLICY)
          and set(_cfg_enums()["authorMode"]) == set(_vc.AUTHOR_MODES))
    check("an empty field REMOVES the key rather than writing an empty string - a "
          "config listing every default is unreadable and freezes today's defaults",
          "function delPath(" in UI_HTML and "delPath(cfg,f.path)" in UI_HTML)
    check("and it drops the container it emptied, so no \"usage\": {} is left behind",
          "if(par&&typeof par==='object'&&!Object.keys(par).length)" in UI_HTML)
    check("Settings keeps the route, the screenshot name and the pinned id it "
          "already had - an internal id is an address, not a description",
          "data-t=guards aria-current=\"true\">Settings<" in UI_HTML
          and "$('#guards')" in UI_HTML)
    check("one Save for four cards, and it is reachable from all of them",
          UI_HTML.count("'/api/config'") == 1 and ".savebar{position:sticky" in UI_HTML)
    # --- the three facts the form has to state out loud ------------------------
    check("tokenVars: an empty box means the three defaults are ACTIVE, and says so "
          "rather than looking like nothing is protected",
          "'defaults are active:'" in UI_HTML and "chip ghosted" in UI_HTML)
    check("tokenVars: and a non-empty one warns that the list REPLACES them, "
          "naming what stopped being covered",
          "Your list REPLACES the defaults" in UI_HTML
          and "'put them back'" in UI_HTML)
    check("secret patterns say regex-not-glob, with the anchor a reader needs",
          "matched case-insensitively anywhere in " in UI_HTML
          and "\\\\.env$" in UI_HTML)
    check("custom rules are labelled 'path contains' and say SUBSTRING, because "
          "four documents said 'starts with' while the hook tested `prefix in path`",
          "'path contains'" in UI_HTML
          and "The path test is a SUBSTRING match, not a '" in UI_HTML
          and "starts with" not in UI_HTML)
    check("both guard fields state the silent skip - a malformed rule is dropped "
          "without a word at runtime, and saving here refuses it instead",
          UI_HTML.count("skipped in silence") >= 1
          and "dropped in silence at runtime" in FIELD_HELP["secretPatterns.extra"])
    check("a regex the browser rejects is marked, and the microcopy does NOT claim "
          "the reverse - Python's engine is the one that decides on save",
          "function reErr(" in UI_HTML
          and "your browser rejects this pattern: " in UI_HTML
          and "decided by Python’s engine" in UI_HTML)
    check("the band pair is linted against the SAME predicate cost_bands applies, "
          "and names the fallback that is otherwise silent",
          "if(!(hi>0&&hi<=ou))" in UI_HTML
          and "fall back to the project-relative basis" in UI_HTML)
    check("usage.bands is a legitimate key now, so the pair the README documents "
          "no longer warns from the plugin's own validator",
          "bands" in _vc.KNOWN_USAGE
          and _vc.validate_config(
              {"usage": {"bands": {"highUSD": 4, "outlierUSD": 12}}}) == ([], []))
    check("pricing rows write only what you change - an empty cell keeps the "
          "shipped rate rather than storing a copy of it",
          "if(inp.value===''){if(o[m])delete o[m][k];}" in UI_HTML
          and "delPath(cfg,'usage.pricing')" in UI_HTML)
    check("the key beside a heading keeps its own case - h2 is uppercased and a "
          "config key is case-sensitive, so an uppercased one cannot be pasted back",
          ".k2{" in UI_HTML and "text-transform:none" in UI_HTML[
              UI_HTML.index(".k2{"):UI_HTML.index(".k2{") + 200])
    # --- the project path is one line -----------------------------------------
    # The RULE, not the string: the comment above it names `word-break:break-all`
    # to say what was removed and why, and a substring test over the whole document
    # cannot tell the fix from the note explaining it.
    _sub = UI_HTML[UI_HTML.index(".sub{"):]
    _sub = _sub[:_sub.index("}")]
    check("the project path is middle-elided rather than wrapped across the header",
          "function midElide(" in UI_HTML and "midElide(PROJECT" in UI_HTML
          and "word-break" not in _sub and "text-overflow:ellipsis" in _sub)
    check("and the full path survives in the tooltip, so nothing is lost",
          "$('#proj').title=PROJECT" in UI_HTML)

    # --- app shell -------------------------------------------------------------
    check("shell: navigation at the side, actions on top",
          '<div class=shell>' in UI_HTML and '<nav class=tabs' in UI_HTML
          and '<main class=view>' in UI_HTML)
    check("shell: the four sections are ONE list that changes presentation, not "
          "two menus - a column above 70rem, a strip below it",
          ".tabs{display:flex;flex-direction:column" in UI_HTML
          and "@media(max-width:70rem){\n .tabs{flex-direction:row" in UI_HTML)
    check("shell: the active view is announced, not only coloured - these are "
          "exclusive views and a background change tells a screen reader nothing",
          'aria-current="true"' in UI_HTML and "x.setAttribute('aria-current'" in UI_HTML
          and "x.removeAttribute('aria-current')" in UI_HTML)
    # A view still never inherits ANOTHER view's scroll position — but it keeps its
    # own. Slamming to the top meant a glance at Usage cost you your place in a
    # 50-phase Composition table, every time.
    check("shell: each view remembers where you were in it, and never inherits "
          "another view's position",
          "SCROLL[CURTAB]=window.scrollY" in UI_HTML
          and "SCROLL[t]||0" in UI_HTML
          and "requestAnimationFrame(()=>window.scrollTo" in UI_HTML)
    check("shell: views are addressable, so a tab can be linked and a reload does "
          "not always land on Guards",
          "history.replaceState(null,''" in UI_HTML and "'#/'+t" in UI_HTML
          and "addEventListener('hashchange'" in UI_HTML
          and "function initialTab()" in UI_HTML)
    check("shell: the scrollbar's width is reserved, so a short view and a long "
          "one do not centre the shell at two different offsets",
          "scrollbar-gutter:stable" in UI_HTML)
    # Verbatim containment, so the two surfaces cannot drift to 14.5rem and
    # 13.5rem again without this failing; and declared ONCE, so the copy this
    # replaced cannot quietly come back alongside it.
    check("shell: the panel renders the shared token layer, not a hand-kept copy",
          _theme.TOKEN_CSS in UI_HTML
          and UI_HTML.count("--nav-w:") == 1
          and UI_HTML.count("--bg:#f5f7fb") == 1)
    check("shell: a saved-or-refused result is announced, not only shown",
          "id=toast role=status aria-live=polite" in UI_HTML)
    # `in_progress` was reaching people in the status pill, the phase row and the
    # filter buttons — the three places you look to find out how the work is going.
    check("labels: statuses read as words, with the machine value kept in "
          "data-status so theming and filtering still compare keys",
          "const LABELS=" in UI_HTML and '"in_progress": "In progress"' in UI_HTML
          and "label(ph.status)" in UI_HTML and "label(t.status)" in UI_HTML
          and "label(p.status)" in UI_HTML
          and "},ph.status||'—')" not in UI_HTML)
    check("labels: Overview colours its status the same way Composition does - "
          "same data, one treatment",
          "el('span',{class:'badge'},p.status" not in UI_HTML)
    check("labels: a status filter announces whether it is on",
          "'aria-pressed':'false'},label(s))" in UI_HTML)
    # Both of these were exposed by widening the shell, and both were guards tied
    # to the viewport rather than to the thing overflowing.
    check("shell: a wide data table scrolls inside its own box at every width, "
          "not only under 48rem",
          ".comptblwrap{border:1px solid var(--border);border-radius:var(--radius);\n"
          " overflow-x:auto" in UI_HTML
          and "@media(max-width:48rem){.comptblwrap{overflow-x:auto}}" not in UI_HTML)
    check("shell: a closed hint occupies no layout, so it cannot push the page "
          "sideways before anyone hovers it",
          "white-space:normal;display:none;pointer-events:none}" in UI_HTML)
    check("shell: and an open one flips at the right edge, measured rather than "
          "guessed from a breakpoint",
          ".hint.flip::after{left:auto;right:0}" in UI_HTML
          and "h.classList.toggle('flip'" in UI_HTML)
    # F8. Both halves of one rule: a settings row is allowed to shrink, and the
    # words inside it are allowed to wrap. Either one alone leaves the row exactly
    # as wide as its content, which on a 390px screen was 447px of DOCUMENT.
    check("shell: a checkbox row may shrink, so a long setting name cannot set the "
          "page's width",
          "label.f.cbf{flex-direction:row;align-items:baseline;gap:.4rem;"
          "flex:0 1 auto;min-width:0}" in UI_HTML)
    check("shell: and the label inside it wraps, which is the only reason "
          "shrinking has anywhere to go",
          ".lbl{display:inline-flex;align-items:center;gap:.25rem;"
          "flex-wrap:wrap;min-width:0}" in UI_HTML)
    check("UI building blocks are a tabbed table", "regtbl" in UI_HTML and "subtab" in UI_HTML)
    check("composition is a compact collapsible filterable table",
          "comptools" in UI_HTML and "table.comp" in UI_HTML and "needs skills" in UI_HTML
          and "tr.phase" in UI_HTML and "class:'tsk'" not in UI_HTML)

    # --- overview (panel c4) ------------------------------------------------
    # The rollup already carried tasks.byStatus, bugs.byStatus, areas and ready[];
    # the tab showed four grey total chips and threw the rest away.
    check("overview: the status strips are the legend AND the filter, one control "
          "for one set of numbers",
          "function ovPill" in UI_HTML and ".ovpill{" in UI_HTML
          and "OVF.ts=OVF.ts===s?'':s" in UI_HTML
          and "OVF.bs=OVF.bs===s?'':s" in UI_HTML
          # the four grey totals the strips replace
          and "'ready '+ (r.ready||[]).length" not in UI_HTML)
    check("overview: a selected pill is not selected by colour alone",
          '.ovpill[aria-pressed=true]::before{content:"\\2713\\a0"' in UI_HTML
          and "'aria-pressed':on?'true':'false'" in UI_HTML)
    check("overview: high-severity is a severity cut, not a status - it never "
          "borrows another status's machine value for its colour",
          "'High severity, open'" in UI_HTML
          and ".ovpill.hi{--st:var(--err)}" in UI_HTML
          and "ovPill('blocked'" not in UI_HTML)
    # A filter held in the render closure is wiped by the 5s run-status poll five
    # seconds after it is set — the same repaint D9 deliberately kept narrow.
    check("overview: the filter state is hoisted out of the render, so the poll "
          "cannot wipe it",
          "const OVF={q:'',ts:'',bs:'',byArea:false,sort:'plan'};" in UI_HTML
          and UI_HTML.index("const OVF=") < UI_HTML.index("function renderOver"))
    check("overview: and the caret survives a repaint mid-search",
          "act.id==='ovq'" in UI_HTML and "n.setSelectionRange(caret,caret)" in UI_HTML)
    check("overview: a phase row is a real button - keyboard reachable without a "
          "hand-written role/tabindex/keydown trio",
          "el('button',{class:'ovrow',type:'button'" in UI_HTML
          and "role:'button'" not in UI_HTML)
    check("overview: it opens that phase in Composition, pre-filtered, without "
          "re-rendering the form someone may be typing in",
          "function openInComp(pid){COMPF.q=pid;" in UI_HTML
          and "if(COMPF.apply)COMPF.apply();showTab('comp');" in UI_HTML
          and "onclick:()=>openInComp(p.id)" in UI_HTML)
    check("composition's filter state is hoisted too, so it survives a re-render",
          "const COMPF={q:'',status:'',needs:false,open:{},apply:null};" in UI_HTML
          and "const open=COMPF.open;" in UI_HTML
          and "COMPF.apply=()=>{q.value=COMPF.q;syncFilters();refresh();};" in UI_HTML)
    # --- c6: confirm before write, and who is writing --------------------------
    # These are string pins, and string pins cannot tell a working panel from a
    # dead one — the whole inline script is one <script>, so a missing paren kills
    # every view while every `'…' in UI_HTML` here still passes. The behaviour is
    # driven for real in tools/capture-screenshots.mjs (assertConfirmFlowWorks,
    # assertViewerIdentity); these guard the constructs those checks depend on.
    check("the topbar names the identity a write will be recorded under",
          "<span class=who id=who hidden></span>" in UI_HTML
          and "function renderViewer()" in UI_HTML
          and "renderViewer();renderSettings();" in UI_HTML)
    check("the write dialog names the identity too — the topbar pill is dropped "
          "below 34rem, which is where the question is least easy to answer",
          "'data-cfwho':who&&!o.danger?'1':null" in UI_HTML
          and "(who&&!o.danger?'as '+who+' · ':'')" in UI_HTML
          and "@media(max-width:34rem){.who{display:none}}" in UI_HTML)
    check("no author resolved -> a way to the setting that decides it, not a blank",
          "settingsLink(v.mode==='none'?'not recorded':'unknown','usage.authorMode')"
          in UI_HTML)
    check("unsaved work is registered per surface, and every writable surface "
          "registers — a surface that forgets is one beforeunload cannot protect",
          "const EDITS={guards:null,comp:null,policy:null};" in UI_HTML
          and "EDITS.comp=()=>compChanges(patch);" in UI_HTML
          and "EDITS.guards=()=>configChanges(cfg);" in UI_HTML
          and "EDITS.policy=()=>policyChanges();" in UI_HTML)
    check("beforeunload interrupts a close only when there is something to lose",
          "addEventListener('beforeunload',ev=>{" in UI_HTML
          and "if(!dirtyRows().length)return;" in UI_HTML)
    check("a re-render does not stack up one more delegated listener per save",
          "if(VIEWAC[id])VIEWAC[id].abort();" in UI_HTML
          and UI_HTML.count("onViewEdit('") == 2)
    check("the dialog is the platform's here too — focus trap, backdrop, Esc",
          "el('dialog',{class:'confirm'})" in UI_HTML
          and "d.showModal()" in UI_HTML
          and "if(ev.target===CFDLG)CFDLG.close()" in UI_HTML
          and "dialog.confirm::backdrop" in UI_HTML)
    check("a destructive primary is not one Enter away from the button that opened "
          "the dialog",
          "(o.danger?cancel:go).focus();" in UI_HTML)
    check("absent, empty list and empty text are three values, and the dialog says "
          "which — collapsing them made a real change read as 'not set -> not set'",
          "?'(empty list)'" in UI_HTML and "?'(empty text)'" in UI_HTML
          and "none?'not set'" in UI_HTML)
    check("the change rows the dialog lists are the shape the server echoes",
          "const cfRow=(target,field,from,to)=>({target,field,"
          "from:cfNorm(from),to:cfNorm(to)});" in UI_HTML
          and "function compChanges(patch)" in UI_HTML
          and "function configChanges(cfg)" in UI_HTML)
    check("what came back is compared with what was shown, not merely trusted",
          "function appliedDiff(rows,res)" in UI_HTML
          and "res.applied.map(key)" in UI_HTML
          and "'data-cfdiff':'1'" in UI_HTML)
    check("the save toast says how many landed and whether it was recorded",
          "'Saved · '+n+' change'+(n===1?'':'s')+log" in UI_HTML
          # "not logged" only when a journal exists and refused: reporting the
          # absence of a feature as a failed save would cry wolf on every write.
          and "res.journaledWhy==='failed'?' · NOT logged':''" in UI_HTML)
    check("a save re-reads from disk afterwards, and the filter survives it",
          "STATE=await api('GET','/api/state');renderComp();renderOver();" in UI_HTML)
    check("an unparseable buildCommands box cannot be confirmed as something else",
          "if(bcBad){toast('meta.buildCommands is not valid JSON" in UI_HTML)
    check("Discard exists on every writable surface, counts what it would throw "
          "away, and is dead while there is nothing to throw",
          UI_HTML.count("'data-discard':'") == 3
          and UI_HTML.count("discard.disabled=!n;") == 2
          and "discard.disabled=!pending.length;" in UI_HTML)
    check("Usage: my-spend filters on the very string the topbar shows",
          "const me=((STATE||{}).viewer||{}).author;" in UI_HTML
          and "onclick:()=>setF('author',on?'':me)},'my spend')" in UI_HTML
          and "'data-umine':'1'" in UI_HTML)
    check("a field must not write into the form merely by rendering — that is an "
          "unsaved change nobody made",
          "const cur=()=>{const v=getPath(cfg,'guardEdits.customRules');" in UI_HTML
          and "setPath(cfg,'guardEdits.customRules',[])" not in UI_HTML)

    check("overview: the phase row says what the phase is FOR, not only what it "
          "is called",
          "p.desiredOutcome?el('span',{class:'ovout'" in UI_HTML
          and ".ovout{" in UI_HTML)
    check("overview: sort and group-by-area consume the rollup's own areas registry",
          "['plan','plan order'],['progress','progress'],['status','status']" in UI_HTML
          and "OVF.byArea=cb.checked" in UI_HTML and "r.areas[tag]" in UI_HTML)
    check("overview: an empty result says so and offers the way back",
          "No phase matches this filter." in UI_HTML
          and "'data-ovclear':'1'" in UI_HTML)
    check("overview: ready-now hands over the command, with a fallback when the "
          "clipboard refuses",
          "const cmd='/audit:run '+id;" in UI_HTML and "function ovCopy" in UI_HTML
          and "document.execCommand('copy')" in UI_HTML
          and "could not copy — the command is " in UI_HTML)

    # _bugs_view: the bug rows behind the strip. Every derived field is decided in
    # Python by the SAME functions the rollup counts with.
    bm = {"phases": [{"id": "P1", "title": "One", "status": "in_progress", "tasks": [
              {"id": "P1.1", "title": "fix it", "status": "done", "bugId": "BUG-1"},
              {"id": "P1.2", "title": "later", "status": "pending", "bugId": "BUG-2"}]}],
          "bugs": [
              {"id": "BUG-1", "title": "a", "status": "open", "severity": "high",
               "taskId": "P1.1"},
              {"id": "BUG-2", "title": "b", "status": "open", "severity": "critical",
               "taskId": "P1.2"},
              {"id": "BUG-3", "title": "c", "status": "wontfix", "severity": "high"}]}
    bv = _bugs_view(bm)
    by_id = {b["id"]: b for b in bv}
    check("_bugs_view resolves a bug through its task: fixed when the task is done, "
          "with the stored value kept so it does not read as hand-edited",
          by_id["BUG-1"]["status"] == "fixed" and by_id["BUG-1"]["reported"] == "open"
          and by_id["BUG-2"]["status"] == "open")
    check("_bugs_view names the phase behind the linked task",
          by_id["BUG-1"]["phaseId"] == "P1")
    # A regex in the browser would be a third opinion on 'is this high?' — and the
    # first spelling it would miss is `critical`, which is the one that matters.
    _rup = _cores()[2].rollup(bm, [], [])
    check("_bugs_view's open/high agree with the rollup's counts, by construction",
          sum(1 for b in bv if b["open"]) == _rup["bugs"]["open"]
          and sum(1 for b in bv if b["open"] and b["high"])
          == _rup["bugs"]["openHighSeverity"] == 1
          and by_id["BUG-2"]["high"] is True)
    check("the browser is handed those verdicts rather than re-deriving them",
          "b.open&&b.high" in UI_HTML and "STATE.bugs" in UI_HTML
          and "severity" not in UI_HTML[UI_HTML.index("const rows=bugs.filter"):
                                        UI_HTML.index("const rows=bugs.filter") + 120])
    check("_bugs_view on a manifest with no bugs is an empty list, not an error",
          _bugs_view({"phases": []}) == [])

    # --- usage tab ---------------------------------------------------------
    check("usage tab is registered and has a view container",
          "data-t=usage" in UI_HTML and "<div id=usage" in UI_HTML
          and "'usage'" in UI_HTML)
    # The rate basis behind every dollar in this tab. It reads the DECLARED flag,
    # never `pricingAsOf` alone: usage_cfg() merges defaults, so that value is set
    # even for a project that never chose it, and printing it unconditionally would
    # present the default table's date as the project's own.
    check("the usage tab names the rate table behind its costs",
          "rates as of '+USAGE.pricingAsOf" in UI_HTML
          and "'rates undated: date them in Settings','usage.pricingAsOf'" in UI_HTML)
    check("and it decides on pricingAsOfDeclared, not on the merged value, so a "
          "default date is never shown as the project's own",
          "USAGE.pricingAsOfDeclared" in UI_HTML)
    check("withheld with the dollars when showCost is off",
          "if(USAGE.showCost&&USAGE.pricingAsOfDeclared)bits.push" in UI_HTML
          and "if(USAGE.showCost&&!USAGE.pricingAsOfDeclared)ctx.append" in UI_HTML)
    # Every one of these used to end with an instruction to go and edit a JSON file
    # by hand - printed on the surface whose whole job is editing that file.
    check("no notice in Usage tells you to set a config value without taking you "
          "to it",
          "function gotoSetting(" in UI_HTML
          and "function settingsLink(" in UI_HTML
          and UI_HTML.count("settingsLink(") >= 5
          and ".claude/audit.config.json)" not in UI_HTML
          and "Set usage.bands.highUSD/outlierUSD" not in UI_HTML)
    check("and arriving there says which field you were sent to, rather than "
          "scrolling somewhere silently",
          "t.classList.add('flash')" in UI_HTML and ".flash{outline:" in UI_HTML)

    # --- c7: the policy switchboard ------------------------------------------
    # String pins, and they cannot tell a working panel from a dead one — the
    # inline script is one <script>, so a missing paren kills every view while
    # every `'…' in UI_HTML` here still passes. The behaviour is driven for real
    # in tools/capture-screenshots.mjs (assertPolicyWorks), against a fixture with
    # its own HOME; these guard the constructs those checks depend on.
    check("the policy tab is registered, routable and has a view container",
          "data-t=policy>Policy<" in UI_HTML and "<div id=policy" in UI_HTML
          and "const TABS=['guards','comp','over','usage','policy']" in UI_HTML)
    check("the verdicts shown are the SERVER's — the browser is handed them and "
          "never matches a pattern itself, because two matchers eventually "
          "disagree about a denial",
          "POLICY.resolved" in UI_HTML and "r.verdict" in UI_HTML
          and "fnmatch" not in UI_HTML
          and "function pResolve" not in UI_HTML)
    check("...so an edited row is marked pending rather than re-judged, and the "
          "verdicts are re-read from the server after a save",
          "moved?el('span',{class:'badge pend'" in UI_HTML
          and "POLICY=await api('GET','/api/policy')" in UI_HTML)
    # EVERY assignment, not one of them. The first version of this pin asked
    # whether the string appeared at all — and it appears three times (boot, save,
    # discard), so a mutation that pointed one of them at the merged block left it
    # green. A wholesale PUT built from defaults would write every default into the
    # file the first time anyone pressed Save.
    _pdraft = re.findall(r"PDRAFT=pClone\(([^)]*)\)", UI_HTML)
    check("the draft is the block AS WRITTEN, not the merged one - and that is "
          "true of every place the draft is set, not merely somewhere",
          _pdraft == ["POLICY&&POLICY.stored"] * 3
          and "pRuleOf(POLICY.stored,kind,r.name,tag)" in UI_HTML)
    check("a switch moves an EXACT name only, so a glob covering ten rows is not "
          "silently dropped by pressing Default on one of them",
          "for(const l of ['deny','allow'])if((src[l]||[]).indexOf(name)>=0)"
          in UI_HTML
          and "function pDraftRules(" in UI_HTML and "'data-prule'" in UI_HTML)
    check("...and every pattern in the block is therefore listed and removable, "
          "with what the server says it matches today",
          "'not saved yet'" in UI_HTML and "'nothing installed matches it today'"
          in UI_HTML and "'data-poladd':'1'" in UI_HTML)
    check("audit's own components cannot be denied from here, and the row says why",
          "sel.disabled=true;" in UI_HTML
          and "required by audit — the panel refuses to write a policy denying it"
          in UI_HTML)
    check("every verdict carries the basis that makes it true, as the report's "
          "routing advice and the lock verdict do",
          "el('span',{class:'pbasis'},r.basis||'')" in UI_HTML
          and ".pbasis{" in UI_HTML)
    check("the page says whether anything is ENFORCING this, in four states, and "
          "never implies enforcement from a policy alone",
          UI_HTML.count("'data-pstate':'") == 4
          and "anthropics/claude-code#43772" in UI_HTML
          and "'data-pstate':'unproven'" in UI_HTML)
    check("the four limits are on the surface that most invites believing the "
          "opposite, and they are the ones SECURITY.md states",
          "What this cannot hold — four limits" in UI_HTML
          and "It denies the tool, not the knowledge." in UI_HTML
          and "Hooks cannot gate hooks." in UI_HTML
          and "not removable quietly" in UI_HTML)
    check("area columns come from the server's own view of them and say which are "
          "deciding anything today",
          "POLICY.areaInfo" in UI_HTML and "a.active?'live':'dormant'" in UI_HTML)
    check("emptying a list removes it, and the container with it - the same "
          "convention Settings writes the config with",
          "function pPrune(" in UI_HTML
          and "if(Array.isArray(k[l])&&!k[l].length)delete k[l];" in UI_HTML
          and "if(!Object.keys(k.areas).length)delete k.areas;" in UI_HTML)
    check("a save goes through the one confirm flow, writes through the one policy "
          "endpoint, and describes itself in the vocabulary the server echoes",
          "confirmChanges({title:'Save capability policy'" in UI_HTML
          and UI_HTML.count("'/api/policy'") == 3
          and "function policyChanges(){" in UI_HTML
          and "return configChanges(cfg);}" in UI_HTML)
    check("the box saying what a save did survives the redraw that follows it, "
          "instead of being wiped by the re-read it triggers",
          "PNOTE=[...findings.childNodes];" in UI_HTML
          and "if(PNOTE){findings.append(...PNOTE);PNOTE=null;}" in UI_HTML)
    check("the widest table this UI draws scrolls inside its own frame",
          ".poltblwrap{" in UI_HTML and "overflow:auto" in UI_HTML)
    # --- c8: the help drawer --------------------------------------------------
    # Same warning as c7's block, one release later: these are string pins over a
    # single inline script, and they cannot tell a working drawer from a dead
    # page. The drawer is DRIVEN in tools/capture-screenshots.mjs
    # (assertHelpDrawerWorks), every oracle computed from the /api/help payload
    # rather than from the drawer's own output; these guard the constructs those
    # checks stand on, and the server side they talk to.
    check("the drawer is a native <dialog>, for the focus trap, Esc, the backdrop "
          "and - the one that matters here - handing focus back to the field",
          "el('dialog',{class:'drawer'" in UI_HTML
          and "dialog.drawer{" in UI_HTML
          and "d.showModal()" in UI_HTML)
    check("the ⓘ that opens it is a real BUTTON. A focusable span inside a <label> "
          "is not interactive content, so pressing it also toggled the checkbox "
          "it was explaining, and a screen reader announced it as text",
          "el(ref?'button':'span',{class:'hint'" in UI_HTML
          and "h.type='button'" in UI_HTML)
    check("...and every Settings control gets one from the key it is already "
          "labelled with, rather than from a second list of which fields have help",
          "hint(tip,{path:key,doc:'config',label:text})" in UI_HTML)
    check("no path is resolved in the browser: `usage.pricing.opus.in` is a path "
          "into a DOCUMENT and the table is keyed by shapes, and exactly one thing "
          "knows the difference",
          "'/api/help?doc='" in UI_HTML
          and "normalise_path" not in UI_HTML
          and "'.<name>.'" not in UI_HTML
          and "function hNormalise" not in UI_HTML)
    check("...which the endpoint answers with the shape that resolved it, so the "
          "drawer can say a second pricing row is not a second field",
          _help.entry_for("usage.pricing.opus.in", "config")["key"]
          == "usage.pricing.<name>.in")
    check("a path nothing documents is found:false rather than a 404 - 'nothing "
          "describes this' is an answer, a 404 is indistinguishable from an "
          "install with no help endpoint at all",
          help_field("nothing.like.this", "config") ==
          {"found": False, "path": "nothing.like.this", "doc": "config"}
          and help_field("enforce", "config").get("found") is True)
    check("...and the document is one of the two shipped schemas, never a path "
          "someone put in a query string",
          help_field("enforce", "../../../etc/passwd").get("found") is False)
    # `.get`, not `[...]`: a response that stopped carrying the key is exactly what
    # these two are about, and a check that dies subscripting it exits 1 with a
    # traceback instead of a named failure — which is how a mutation goes red for
    # the wrong reason and proves nothing (F3, one level down).
    # The point of extracting rather than restating, asserted where it would
    # actually be broken: not one word of a concept page is in this file. A
    # sentence copied here would render identically and be a second thing to keep
    # true — which is the bug `_help` exists to avoid, reappearing in its consumer.
    _typed = [t["id"] for t in _help.topics()
              if t["title"] in UI_HTML or t["summary"] in UI_HTML
              or any(p in UI_HTML for p in t["paragraphs"])]
    check("no concept page is retyped into the UI - the drawer renders what the "
          "payload serves, and there is nowhere else for it to come from: %r"
          % _typed, not _typed)
    check("a field's concept page is the one the PAYLOAD links it to",
          "e.topic" in UI_HTML and "x.id===e.topic" in UI_HTML)
    check("the guide card is drawn from the payload's agent and not at all when "
          "there is none - a hint offering an agent this install does not ship is "
          "a dead end", "const a=doc&&doc.agent;if(!a)return null;" in UI_HTML
          and "(a.tools||[]).join(' · ')" in UI_HTML)
    check("...and it names the agent rather than offering to spend one: the whole "
          "point of the zero-token half is that it is the default",
          "This panel will not start it for you" in UI_HTML
          and "'/api/task'" not in UI_HTML and "spawnAgent" not in UI_HTML)
    check("the index is reachable from the topbar, not only from a field",
          "id=helpbtn" in UI_HTML and "$('#helpbtn').onclick=()=>openHelpIndex()"
          in UI_HTML)
    check("a group heading that has a concept page opens it; the three that have "
          "none draw no hint at all",
          "grp.topic?{topic:grp.topic}:null" in UI_HTML
          and [g["id"] for g in SETTINGS_GROUPS if g.get("topic")]
          == ["paths", "journal"]
          and {g["topic"] for g in SETTINGS_GROUPS if g.get("topic")}
          <= {t["id"] for t in _help.topics()})
    check("the composition levers are explained through _help's own map from the "
          "panel's name for a lever to the manifest path that documents it",
          not [k for k in ("reviewSkill", "buildCommands", "taskModel",
                           "taskSkills", "phaseReviewModel")
               if ("{comp:'%s'" % k) not in UI_HTML]
          and "(doc.composition||{})[ref.comp]" in UI_HTML
          and set(COMPOSITION_HELP) == set(_help.COMPOSITION_PATHS))
    check("backticks are the topics' only markup, and an unbalanced pair renders "
          "verbatim rather than guessing which half was code",
          "if(parts.length%2===0)return [String(s)];" in UI_HTML)
    # The drawer prints these one after the other under two headings. Byte-equal
    # is not two voices, it is the same sentence twice — and it is the shape of
    # the duplication this whole endpoint exists to avoid.
    _cfgfields = _help.config_fields()
    _dupe = [p for p, t in FIELD_HELP.items()
             if (_help.lookup(_cfgfields, p) or {}).get("description") == t]
    check("no panel note is word-for-word the schema's own sentence: %r" % _dupe,
          not _dupe)
    _undoc = [p for p in FIELD_HELP
              if not (_help.lookup(_cfgfields, p) or {}).get("description")]
    check("...and every note is beside a field the schema describes, so the "
          "drawer never opens on a note with nothing to cite: %r" % _undoc,
          not _undoc)
    check("a quoted frontmatter value is unquoted by the one function that knows "
          "how, so the panel does not publish the escape either",
          _front_matter("---\nname: x\ndescription: 'the plugin''s own README'\n"
                        "---\n")["description"] == "the plugin's own README"
          and _front_matter("---\nname: don't\n---\n")["name"] == "don't")

    check("_declared_as_of separates a project's own value from the default",
          _declared_as_of({"usage": {"pricingAsOf": "2026-01-02"}}) is True
          and _declared_as_of({"usage": {"showCost": True}}) is False
          and _declared_as_of({}) is False
          and _declared_as_of({"usage": {"pricingAsOf": "   "}}) is False
          and _declared_as_of({"usage": {"pricingAsOf": 20260102}}) is False)
    # UI_HTML carries the stylesheet AND the JS that writes inline styles, which
    # is where an undeclared token actually hides.
    _css = UI_HTML[UI_HTML.index("<style>"):UI_HTML.index("</style>")]
    _missing = _undeclared_css_vars(UI_HTML)
    check("every var(--token) in the panel CSS is declared "
          "(an undeclared one paints transparent and logs nothing): %r" % _missing,
          _missing == [])
    _asym = _theme_asymmetric_vars(_css)
    check("no colour token exists in only one theme (either direction): %r"
          % _asym, _asym == [])
    # Settings alone ships a <select>, an <input type=date> and four number
    # inputs; all six are painted by the UA from `color-scheme`, which no custom
    # property can reach. A theme that does not restate it renders our dark cards
    # with the OS's light spinners and menu.
    _nocs = _themes_missing_color_scheme(_css)
    check("every explicit data-theme restates color-scheme, so the toggle moves "
          "the selects, spinners, date picker and scrollbars too: %r" % _nocs,
          _nocs == [])
    # This sheet is a non-raw Python string too. The report's copy of the filter
    # chip's tick shipped as `¹3<BEL>0` for want of a doubled backslash; this one
    # was written correctly, and neither suite could see that they differed.
    _esc = _mangled_css_escapes(_css)
    check("no CSS escape was eaten by Python before the browser saw it: %r" % _esc,
          _esc == [])
    check("usage colours come from the same validated palette as the report",
          "--viz-1:#2a78d6" in UI_HTML and "--viz-1:#3987e5" in UI_HTML)
    # Two series in the same hue is the one failure a categorical palette cannot
    # survive, and it only appears past 8 entities — which is exactly where nobody
    # looks. `Math.min(i+1,8)` gave 40 authors ONE red between 33 of them. The
    # invariant (every drawn series a distinct slot) is asserted in-browser against
    # a 40-author fixture; these pin the construct that guarantees it.
    check("hues are never shared: slots go to the entities actually drawn, and "
          "the capped-index rule that collided is gone",
          "Math.min(i+1,8)" not in UI_HTML
          and "function uRanks" in UI_HTML
          and "while(free<=8&&used.has(free))free++;" in UI_HTML
          and "uSlots(F.author,plotted,'spend')" in UI_HTML)
    check("slot order is global spend rank, so a filter never repaints a survivor",
          "for(const f of USAGE.facts)t[f[field]]" in UI_HTML
          and "sort((a,b)=>t[b]-t[a]" in UI_HTML)
    # A model must wear one hue across BOTH surfaces, so the panel orders models by
    # the same key render-report.py's _model_slots does. Authors have no report
    # chart to agree with, so they order by spend — the useful priority when only
    # 8 of 40 can be coloured.
    check("models slot by name (matching the report), authors by spend",
          "uSlots(F.model,dim==='model'?plotted" in UI_HTML
          and "'name')" in UI_HTML
          and "uSlots(F.author,plotted,'spend')" in UI_HTML
          and "if(by==='name')" in UI_HTML)
    check("a tiny non-zero bar still paints (0.0% reads as no data)",
          "Math.max(v[0]?0.8:0,100*v[0]/peak)" in UI_HTML)
    # One number format, and it is easy to break one call site at a time: the label
    # reads 3.2M while the tooltip opening over it reads 3,230,000. Every raw
    # thousands-separated number in the panel must be a COUNTABLE — in the fact
    # tuple that is index 2 (msgs) — never a token magnitude at index 0.
    # The fact tuple is [ts,phase,task,model,author,agent,attr,tokens,cost,msgs],
    # and the aggregate tuple is [tokens,cost,msgs] — so a countable receiver ends
    # in `[2]` or names msgs outright. Anything else is a magnitude and must be
    # compact.
    _loc = re.findall(r"([\w.\[\]]+)\.toLocaleString\(\)", UI_HTML)
    _badloc = [x for x in _loc if not (x.endswith("[2]") or x.endswith("msgs"))]
    check("no token value is rendered with thousand separators "
          "(counts may be; magnitudes may not): %r"
          % (_badloc or "ok, %d countables" % len(_loc)),
          _badloc == [] and bool(_loc))
    check("tokens are compact at one decimal, two on hover, matching the report",
          "const uTok=(n,dp=1)=>" in UI_HTML and "(n/l).toFixed(dp)+s" in UI_HTML
          and "uTok(v[0],2)" in UI_HTML)

    # --- reversible tail + browse dialog -----------------------------------------
    # The collapse used to hang off `else if(limit>TOP)` — it only appeared once
    # you had paged to the end of the tail, which at 233 rows is thirty clicks
    # before the way back exists.
    check("the collapse is unconditional, not gated on the tail being exhausted",
          "else if(limit>TOP)" not in UI_HTML
          and "if(limit>TOP)ctl.push(" in UI_HTML
          and "'show top '+TOP+' only'" in UI_HTML)
    check("browse-all appears whenever the list folds, and states the full count",
          "if(g.length>TOP)ctl.push(" in UI_HTML
          and "'browse all '+g.length" in UI_HTML)
    check("the dialog is the platform's, so focus trap/backdrop/Esc are not ours",
          "el('dialog',{class:'browse'})" in UI_HTML
          and "BROWSE.showModal()" in UI_HTML
          and "dialog.browse::backdrop" in UI_HTML
          and "ev.target===BROWSE" in UI_HTML)
    check("Esc closes the dialog without also dropping a filter",
          "if(document.querySelector('dialog[open]'))return;" in UI_HTML)
    check("the dialog reads the same filtered facts as the bars, and says so "
          "when the page is scoped",
          "openBrowse(dim,title,facts)" in UI_HTML
          and "'within: '+UORDER.map(" in UI_HTML)
    check("search reports what it hid; sort toggles direction on re-click",
          "shown.length+' of '+rows.length" in UI_HTML
          and "if(sort===key)desc=!desc;else{sort=key;desc=!!BNUM[key];}" in UI_HTML
          and "desc?'▼':'▲'" in UI_HTML)
    check("a dialog row applies the filter and closes; an active row clears it",
          "setF(dim,active?'':r.id);BROWSE.close();" in UI_HTML)
    # <input type=search> consumes the first Escape to clear itself, so the dialog
    # only closed on the second press and the key read as broken.
    check("one Escape closes the dialog even from inside the search field",
          "if(ev.key==='Escape'){ev.preventDefault();BROWSE.close();}" in UI_HTML)
    # Across 241 phases every share is below 1%, and uPct floors those to "<1%" —
    # a column of identical cells that sorts correctly and says nothing.
    check("the share column keeps digits instead of flooring to <1%",
          "r.share<1?r.share.toFixed(2):r.share.toFixed(1)" in UI_HTML)
    # replaceChildren() stringifies non-Nodes, so an absent optional child painted
    # the literal word "null" into the dialog. el() tolerates nulls; this does not.
    check("optional dialog children are filtered, never stringified",
          "].filter(Boolean));" in UI_HTML
          and "BROWSE.replaceChildren(...[head,within," in UI_HTML)
    check("columns follow the dimension: only tasks carry status and risk",
          "task:[['id','id'],['title','title'],['status','status'],['risk','risk']"
          in UI_HTML and "author:[['author','id']" in UI_HTML)
    # Two phases costing the same can be one opus run and one long haiku grind —
    # the aggregate cannot say which, so the mix is carried alongside it.
    check("phase/task/author rows carry a model mix; the model dimension does not",
          "['models','models']" in UI_HTML
          and UI_HTML.count("['models','models']") == 3
          and "model:[['model','id'],['tokens','tokens']" in UI_HTML)
    check("mix segments are emitted in slot order (validated adjacency), and the "
          "dominant model is named rather than left to colour",
          "(MSLOTS[a]||99)-(MSLOTS[b]||99)" in UI_HTML
          and "el('span',{class:'mdom'},r.dominant" in UI_HTML
          and "cell.title=r.models.map(" in UI_HTML)
    check("a mix has no natural order, so that column sorts by dominant model",
          "const k=sort==='models'?'dominant':sort;" in UI_HTML)

    # --- phase budgets ------------------------------------------------------------
    # The client has no manifest, so budgets come off usage_state(); assert the
    # server side by exercising it rather than by grepping this file's own source.
    import shutil as _sh
    _bproj = tempfile.mkdtemp(prefix="panel-budget-")
    try:
        os.makedirs(os.path.join(_bproj, "docs", "audit"), exist_ok=True)
        with open(os.path.join(_bproj, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "A", "status": "done", "budgetUSD": 40,
                 "tasks": []},
                {"id": "P2", "title": "B", "status": "done", "budgetUSD": 0,
                 "tasks": []},
                {"id": "P3", "title": "C", "status": "done", "budgetUSD": True,
                 "tasks": []},
                {"id": "P4", "title": "D", "status": "done", "budgetUSD": "40",
                 "tasks": []},
                {"id": "P5", "title": "E", "status": "done", "tasks": []}]}, fh)
        # Seed a ledger so this exercises the POPULATED branch, not the stub.
        _bled = os.path.join(_bproj, ".claude", "usage")
        os.makedirs(_bled, exist_ok=True)
        with open(os.path.join(_bled, "2026-08.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": "2026-08-01T10", "sessionId": "s", "phaseId": "P1",
                "taskId": None, "attr": "phase", "model": "claude-opus-5",
                "author": "a@x", "msgs": 1, "in": 1, "out": 1, "cacheW5m": 0,
                "cacheW1h": 0, "cacheR": 0, "costUSD": 1.0}) + "\n")
        _bs = usage_state(_bproj)
        check("budgets ship from the server, and 0 / boolean / string / missing "
              "all mean NO budget — exactly as the validator treats them: %s"
              % repr(_bs.get("phaseBudgets")),
              _bs["phaseBudgets"] == {"P1": 40.0})
    finally:
        _sh.rmtree(_bproj, ignore_errors=True)
    # The no-ledger stub must carry every key the populated branch does, or a
    # fresh install hands the client `undefined` for half the tab.
    _eproj = tempfile.mkdtemp(prefix="panel-empty-")
    try:
        _es = usage_state(_eproj)
        check("the no-ledger stub has the same shape as a populated state",
              {"phaseBudgets", "bands", "taskMeta", "phaseTitles", "counts"}
              <= set(_es))
    finally:
        _sh.rmtree(_eproj, ignore_errors=True)
    check("no budget anywhere renders nothing at all",
          "if(!ids.length)return [];" in UI_HTML)
    check("the burn-down follows the filter, and says which rows it counted",
          "for(const f of facts){const p=f[F.phase]" in UI_HTML
          and "Counting only the rows the filters above leave in view." in UI_HTML)
    check("the fill caps at the track while the number does not",
          "Math.min(100,r.pct).toFixed(1)" in UI_HTML
          and "r.pct.toFixed(0)+'%'" in UI_HTML)
    check("unbudgeted phases are counted, never drawn as a phase at zero",
          "are not listed - they are not " in UI_HTML
          and "phases at zero." in UI_HTML)

    # This module's own source, for the handful of checks that must assert a
    # server-side construct rather than a rendered string.
    _src = _src_of_this_file()

    # --- report export ------------------------------------------------------------
    # There is deliberately no path parameter on /report: the location is derived
    # from the project's own config, so there is nothing to traverse with.
    _rp = tempfile.mkdtemp(prefix="panel-report-")
    try:
        os.makedirs(os.path.join(_rp, "docs", "audit"), exist_ok=True)
        with open(os.path.join(_rp, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2, "repo": "x"}, "phases": [
                {"id": "P1", "title": "A", "status": "done", "tasks": [
                    {"id": "P1.1", "title": "t", "status": "done"}]}]}, fh)
        check("no report exists before it is rendered",
              os.path.isfile(report_paths(_rp)[2]) is False)
        _res = render_report(_rp)
        check("export writes the html and its markdown twin, and reports both",
              _res["ok"] and len(_res["files"]) == 2
              and any(f.endswith(".html") for f in _res["files"])
              and any(f.endswith(".md") for f in _res["files"]))
        check("everything it writes stays inside the project",
              all(_within(_rp, f) for f in _res["files"]))
        check("it hands back an in-origin href, not a filesystem path — a browser "
              "will not follow file:// from an http:// page",
              _res["href"] == "/report" and _res["exists"] is True)
    finally:
        _sh.rmtree(_rp, ignore_errors=True)
    _np = tempfile.mkdtemp(prefix="panel-noreport-")
    try:
        check("a project with no manifest refuses instead of raising",
              report_paths(_np) is None
              and render_report(_np)["ok"] is False)
    finally:
        _sh.rmtree(_np, ignore_errors=True)
    check("the export route derives its path and takes no parameter",
          'if path == "/api/report"' in _src and 'if path == "/report"' in _src
          and "paths = report_paths(project)" in _src)
    check("the button opens through this origin with the token in the query "
          "string (window.open cannot set a header)",
          "const url=p=>p+'?t='+encodeURIComponent(TOKEN)" in UI_HTML
          and "win.location=url('/report')" in UI_HTML)
    # Opened during the click, navigated after the render returns. The other order
    # is a popup opened outside a user gesture, which Safari and a strict Firefox
    # block silently — leaving a button that reports success and does nothing.
    _rep = UI_HTML[UI_HTML.index("$('#report').onclick"):]
    _rep = _rep[:_rep.index("// tabs")]
    check("the window is opened inside the gesture, before the await, and a "
          "blocked popup still leaves a link",
          _rep.index("window.open('','_blank'") < _rep.index("await api('POST','/api/report'")
          and "id:'replink'" in _rep)
    check("a render that wrote no HTML says so instead of opening a 404",
          "if(!r.exists)" in _rep)

    # --- routing advice -----------------------------------------------------------
    # The only server-computed metric in the tab: the counterfactual re-prices the
    # per-tier token counts, which `facts` no longer carry.
    check("routing advice is shipped from the server and fails soft",
          '"routingAdvice": advice' in _src
          and "ul.routing(_mio.load_manifest_safe(mpath), rows," in _src
          and "advice = []" in _src)
    check("advice says it does NOT follow the filters, unlike everything else",
          "does not follow the filters above." in UI_HTML
          and "const adv=USAGE.routingAdvice||[];" in UI_HTML)
    check("the caveat travels with the number, not just in the docs",
          "An upper bound, not a forecast" in UI_HTML
          and "would not emit " in UI_HTML)
    check("no advice renders nothing at all",
          "if(adv.length){" in UI_HTML)

    # --- cost bands ---------------------------------------------------------------
    # The JS reimplements cost_bands(); the two agreeing is a standing obligation,
    # so the source says which Python function it shadows and pins the same gate.
    _ulmod = _load("audit_usage_ledger_check",
                   os.path.join(_HERE, "usage_ledger.py"))
    check("bands mirror the Python implementation and pin the SAME gate "
          "(a drift here puts one task in two different bands)",
          "const BAND_GATE=5" in UI_HTML
          and "Mirrors cost_bands() in usage_ledger.py" in UI_HTML
          and "const BAND_GATE=%d" % _ulmod.MIN_TASKS_FOR_PROJECTION in UI_HTML
          and list(_ulmod.BAND_ORDER) == ["typical", "high", "outlier"])
    # A task is an outlier relative to the PROJECT. Recalibrating per filter would
    # make one of any three tasks an outlier the moment you scoped to three.
    check("bands are computed from the whole ledger, never the filtered view",
          "for(const f of USAGE.facts){const t=f[F.task];" in UI_HTML
          and "uBandInfo()" in UI_HTML and "BANDS=null;" in UI_HTML)
    check("a malformed threshold pair falls back to the relative basis",
          "if(!(isFinite(hi)&&isFinite(ou)&&hi>0&&hi<=ou))" in UI_HTML)
    check("below the gate nothing is banded, and the dialog says what is missing",
          "return (BANDS={basis:null,sufficient:false,byTask:{},sample,gate:BAND_GATE})"
          in UI_HTML
          and "needs '+bi.gate+' completed tasks to calibrate" in UI_HTML)
    check("the thresholds themselves are printed, so the reader can check them",
          "typical ≤ '+uCost(bi.high)" in UI_HTML
          and "high ≤ '+uCost(bi.outlier)" in UI_HTML)
    check("the band is a labelled pill, never a bare status colour",
          "el('span',{class:'bandpill b-'+r.band},r.band)" in UI_HTML
          and ".bandpill{" in UI_HTML)
    check("only tasks carry a band — a phase is not the thing that was measured",
          "['cost band','band']" in UI_HTML
          and UI_HTML.count("['cost band','band']") == 1
          and "band:(dim==='task'?bandOf(k):null)" in UI_HTML)
    # A malformed 300-phase manifest emits a finding per phase, per task and per
    # indexed file — 1009 of them, previously joined into one paragraph that
    # filled the screen. They were four mistakes repeated, so the banner groups.
    check("findings group by shape with counts instead of one endless join",
          "function manifestFindingsBox" in UI_HTML
          and "function findingKind" in UI_HTML
          # a second findingsBox() would hoist over the save-result one
          and UI_HTML.count("function findingsBox") == 1
          and "el('span',{class:'fn'},g.n+'\\u00d7')" not in UI_HTML
          and "g.n+'×'" in UI_HTML
          and "'✗ '+r.findings+' finding(s): '" not in UI_HTML)
    check("a short finding list is still listed plainly, not force-grouped",
          "if(list.length<FGROUP_MIN)" in UI_HTML and "FGROUP_MIN=6" in UI_HTML)
    check("the raw list stays reachable and its own cap is stated",
          "every finding, unfolded" in UI_HTML
          and "' more — run /audit:validate for the complete list'" in UI_HTML)
    check("usage filtering is client-side (no round-trip per change)",
          "function uFiltered" in UI_HTML and "renderUsage()" in UI_HTML)
    # 250 daily points across 680px is 2.7px per mark: eight series of that is
    # noise. Rolling up is only honest if the chart says it rolled up, so the
    # heading, the crumb, the tooltip footer and the aria-label all name the bin.
    check("a long span rolls up into natural bins instead of drawing spaghetti",
          "const MAXPTS=60, LADDER=[1,7,28,91,364]" in UI_HTML
          and "function uBin" in UI_HTML
          and "LADDER.find(s=>Math.ceil(span/s)<=MAXPTS)" in UI_HTML)
    check("the roll-up is stated everywhere the period is named, never silent",
          "'Tokens per '+per+' by '+dim" in UI_HTML
          and "Days are rolled up into " in UI_HTML
          and "'click to filter to this '" in UI_HTML
          and "BINNAME[sr.binSize]" in UI_HTML)
    check("a rolled-up bin is still one clickable filter (from..to), and the "
          "chip spells the range out",
          "const binKey=b=>b[0]===b[1]?b[0]:b[0]+'..'+b[1]" in UI_HTML
          and "const[a,b]=UF.day.split('..')" in UI_HTML
          and "UF.day.replace('..',' to ')" in UI_HTML)

    # --- usage c5: filters, trends, export ---------------------------------
    # Derived, not enumerated. A filter added to UF and forgotten in DIMS is a
    # filter `clear all` cannot clear and Esc cannot pop — it stays on for the rest
    # of the session with a chip beside it that does nothing. The two lists must be
    # the same set, so the test compares them rather than restating either.
    _uf_keys = set(re.findall(r"(\w+):''", re.search(
        r"const UF=\{(.*?)\};", UI_HTML, re.S).group(1)))
    _dims = set(re.findall(r"'(\w+)'", re.search(
        r"const DIMS=\[(.*?)\];", UI_HTML, re.S).group(1)))
    check("every filter in UF is in DIMS, so clear-all and Esc reach all of them "
          "(UF-only: %r, DIMS-only: %r)"
          % (sorted(_uf_keys - _dims), sorted(_dims - _uf_keys)),
          _uf_keys == _dims and len(_dims) >= 8)
    # The delta used to re-list model/author/phase/task inline. Adding agent, attr
    # and free text to uFiltered alone would have left the trend comparing the
    # whole prior month against a filtered current one, and labelling it "vs prior
    # 30d" while doing it.
    _dl = UI_HTML[UI_HTML.index("function uDelta("):
                  UI_HTML.index("// --- CSV export")]
    check("one predicate scopes both windows: uFiltered and uDelta share uMatch, "
          "and the delta re-lists no dimension of its own",
          "function uMatch(f){" in UI_HTML
          and "USAGE.facts.filter(uMatch)" in UI_HTML
          and "&&uMatch(f);" in _dl
          and "UF.model" not in _dl and "UF.author" not in _dl)
    check("free text reads titles, not only ids, so a word from the plan finds "
          "the work",
          "function uHay(f)" in UI_HTML
          and "(USAGE.phaseTitles||{})[f[F.phase]]" in UI_HTML
          and "((USAGE.taskMeta||{})[f[F.task]]||{}).title" in UI_HTML)
    # A ledger's last day, never today's: the panel's own demo ledger ends in May,
    # and a wall-clock anchor makes the default view of it compare two empty
    # windows and show no trend at all, forever.
    check("all-time still gets a trend, anchored on the ledger's last day",
          "const all=UF.range==='all',span=all?30:parseInt(UF.range,10)" in UI_HTML
          and "const anchor=all?days[days.length-1]" in UI_HTML
          and "label:'vs prior '+span+'d'" in UI_HTML)
    check("and it carries both date ranges, because a percentage against an "
          "unnamed period is not a measurement",
          "basis:(all?'the ledger" in UI_HTML
          and "') against '+prevCut+' to '+iso(dnum(cut)-1)" in UI_HTML
          and "'Trend is '+dl.label+': '+dl.basis" in UI_HTML)
    check("a share moves in POINTS, a magnitude in per cent",
          "attributed:(A.attributed==null||B.attributed==null)" in _dl
          and "?null:A.attributed-B.attributed" in _dl
          and "(o.pp?' pts':'%')" in UI_HTML)
    # Colour said "spending more is good" for four releases, on the one chip whose
    # job is to report a direction.
    check("direction is a glyph before it is a hue, and only the metric with a "
          "polarity is coloured",
          '.dl.up::before{content:"\\25b2\\a0"' in UI_HTML
          and '.dl.down::before{content:"\\25bc\\a0"' in UI_HTML
          and "(o.pol?(d>=0?' good':' bad'):'')" in UI_HTML
          and ".dl{" in UI_HTML
          and "color:var(--muted);background:var(--surface-2)}" in UI_HTML)
    check("a magnitude spark is drawn from zero with an area, a share is scaled "
          "to its own range with none",
          "function uSpark(vals,label,zero)" in UI_HTML
          and "zero?Math.min(0,Math.min(...v)):Math.min(...v)" in UI_HTML
          and "if(zero)svg.appendChild(svgEl('path',{class:'sa'" in UI_HTML
          and "uSpark(o.series,k+' per '+sp.period+', oldest to newest',!o.pp)"
          in UI_HTML)
    _spk = UI_HTML[UI_HTML.index("function uSpark("):
                   UI_HTML.index("// --- metrics,")]
    check("the spark is drawn 1:1 like the chart, not stretched to the tile "
          "(a scaled viewBox scales the strokes with it)",
          "const SPW=76,SPH=20" in UI_HTML
          and "width:SPW,height:SPH" in _spk
          and "preserveAspectRatio" not in _spk)
    check("a tile with no daily series says why instead of drawing a flat line",
          "no daily trend: a task" in UI_HTML
          and "title:o.why||'no daily series for this metric'" in UI_HTML)
    # A quiet day has no share to report. Plotting it as 0% draws a cliff to the
    # floor and calls it a collapse in attribution.
    check("an empty bucket is a gap in a share series, never a zero",
          "attributed:acc.map(v=>v[0]?100*(v[0]-v[3])/v[0]:null)" in UI_HTML
          and "const v=(vals||[]).filter(x=>x!=null);" in UI_HTML)
    # The from/to pair and a click on the chart write ONE filter, in one grammar,
    # with one chip and one way out.
    check("the date pair reads and writes the same UF.day grammar the chart does",
          "function uDayPair(){const[a,b]=(UF.day||'').split('..')" in UI_HTML
          and "setF('day',(a||b)?(a===b?a:a+'..'+b):'')" in UI_HTML)
    check("half a pair is completed from the ledger's own ends, not from today",
          "const a=from||C.from||'',b=to||C.to||''" in UI_HTML
          and "Date.now" not in UI_HTML[UI_HTML.index("function uSetDays"):
                                        UI_HTML.index("function uAgg")])
    _csv = UI_HTML[UI_HTML.index("function uCsvText("):
                   UI_HTML.index("// --- render ---")]
    check("the CSV ships raw numbers: a separator makes every sum over the "
          "column wrong, and silently",
          "toLocaleString" not in _csv
          and "f[F.cost].toFixed(6)" in _csv and "f[F.tokens]," in _csv)
    check("and quotes per RFC 4180, so a comma in a title does not shift a column",
          '/[",\\r\\n]/.test(s)' in _csv
          and "'\"'+s.replace(/\"/g,'\"\"')+'\"'" in _csv
          and "out.join('\\r\\n')" in _csv)
    check("the file names what it is — span, resolution and whether a filter was "
          "on — so it can still be trusted three weeks later",
          "'usage-'+(C.from||'start')+'_'+(C.to||'end')+'-'" in _csv
          and "(USAGE.rolled?'daily':'hourly')" in _csv
          and "(uAnyFilter()?'-filtered':'')+'.csv'" in _csv)
    check("the blob URL outlives the click, and an export that cannot run says so "
          "rather than being a button that does nothing",
          "setTimeout(()=>URL.revokeObjectURL(url),4000)" in _csv
          and "toast('export failed: '+e,'err')" in _csv
          and "nothing to export" in _csv)
    check("the BOM is an escape, not an invisible character in the source",
          "['\\ufeff'+uCsvText(facts)]" in _csv
          and "﻿" not in UI_HTML)
    # <input type=search> clears itself on Escape - the trap the browse dialog
    # already hit once. One key, one effect.
    check("Escape inside the search box drops the search and nothing else",
          "if(a&&a.id==='uq'){if(UF.q)setF('q','');return;}" in UI_HTML)
    check("and the box keeps focus and caret when the filter repaints the tab",
          "keepQ=!!(act&&act.id==='uq')" in UI_HTML
          and "if(keepQ){const n=$('#uq');" in UI_HTML
          and "n.setSelectionRange(caret,caret)" in UI_HTML)

    # --- F5: an empty usage view explains itself ---------------------------
    # The range presets count back from the wall clock, so on a ledger that
    # stopped in May every preset but 90 selects nothing. That is the normal end
    # state of a finished plan, and precisely when someone opens this tab to ask
    # what it cost — and "No rows match these filters" left them with metering
    # never ran as the only conclusion on offer.
    _emp = UI_HTML[UI_HTML.index("function uEmptyWhy()"):
                   UI_HTML.index("function uDayPair()")]
    check("an empty usage view names its reason in an attribute, not only in "
          "prose a reader (or a check) has to parse",
          "const why=uEmptyWhy();" in UI_HTML
          and "'data-uwhy':why.why" in UI_HTML)
    check("a preset window beginning after the ledger's last day says so, with "
          "both dates",
          "why:'range-after-ledger'" in _emp
          and "if(C.to&&C.to<cut)" in _emp
          and "'The last '+UF.range+' days begin '+cut+', and the ledger ends '"
          "+C.to" in _emp)
    check("and offers the view that does hold the data, beside the bare "
          "clear-filters rather than instead of it",
          "label:'Show all time',run:toAll" in _emp
          and "'data-ufix':why.fix.key" in UI_HTML
          and "'data-uclear':'1'" in UI_HTML)
    # Re-anchoring the presets on the ledger would empty nothing and lie instead:
    # a control whose label says "today" and whose behaviour means "whenever the
    # data stopped". The empty state is the fix; the arithmetic was never wrong.
    check("the presets still measure back from today — the explanation is the "
          "fix, not a silently re-anchored window",
          "if(UF.range!=='all'){const d=new Date(Date.now()-parseInt(UF.range,10)"
          "*864e5)" in UI_HTML)
    # An explanation computed by a second copy of "what matches" is an explanation
    # that can contradict the view it is explaining.
    check("the diagnosis re-runs uFiltered with one slot blanked instead of "
          "re-implementing the match",
          "const keep=UF[d];UF[d]=d==='range'?'all':'';" in _emp
          and "const n=uFiltered().length;UF[d]=keep;" in _emp
          and "for(const d of UORDER.concat(" in _emp)
    check("one filter doing the emptying is named, counted and liftable on its "
          "own — clear-all throws away the ones that were fine",
          "n+' row(s) match everything else.'" in _emp
          and "'Remove the '+fName(d)+' filter'" in _emp)
    check("and where no single filter explains it, the page says so rather than "
          "blaming one at random",
          "why:'combination'" in _emp
          and "is the combination that selects nothing." in _emp)
    check("`range` carries a human name and a human value like every other "
          "filter, so it can be named where it is blamed",
          "range:'time range'" in UI_HTML
          and ":d==='range'?(UF.range==='all'?'all time':'last '+UF.range+' days')"
          in UI_HTML)

    # --- F6: a share of nothing is undefined, not 100% ---------------------
    # `uCoverage` divided by `tot||1` — the `||1` written to dodge a divide by
    # zero — so an empty selection returned 100*(1-0)/1 and the `attributed` tile
    # reported PERFECT coverage of no rows at all, beside three honest zeros, on
    # the one tile of the four that is coloured by polarity. It was also a second
    # implementation of `usage_ledger.coverage()`, which has always returned a
    # sentinel for an empty ledger rather than a number — two copies of one
    # calculation disagreeing at the boundary neither was tested on.
    #
    # The guard is the rule, not the patch: `||1` on a denominator is legitimate
    # for a bar's WIDTH and a sparkline's RANGE (a scale is a drawing decision,
    # not a claim) and for `attempts`, where one attempt is the true default. In
    # any other position it manufactures an answer to a question that has none.
    _or1 = [l.strip() for l in UI_HTML.splitlines()
            if "||1" in l and not l.lstrip().startswith("//")
            and not re.search(r"peak|\(hi-lo\)|attempts", l)]
    check("no percentage divides by a `||1` denominator — offenders: %r" % _or1,
          not _or1)
    check("every printed share goes through one helper that returns null when "
          "there is nothing to take a share of",
          "const uShare=(part,whole)=>whole?100*part/whole:null;" in UI_HTML
          and "return {attributed:uShare(tot-un,tot),task:uShare(by['task']||0,tot)"
          in UI_HTML
          and "tipRow(null,'share',uPct(uShare(v[0],grand)))" in UI_HTML
          and "share:uShare(v[0],grand)" in UI_HTML
          and "pct:uShare(per[m],v[0])" in UI_HTML)
    check("and null prints as the same em dash a tile with no series draws, "
          "rather than as a number",
          "const uPct=x=>x==null?'—':" in UI_HTML
          and "tile('attributed',uPct(cov.attributed)" in UI_HTML)
    # A null reaching .toFixed throws, and in the browse dialog that is the whole
    # table gone — the share column and the model tooltip are its two readers.
    check("both readers of a share that can now be null say so instead of "
          "throwing on .toFixed",
          "key==='share'?(r.share==null?'—'" in UI_HTML
          and "m.model+'  '+uPct(m.pct)+'  '+uTok(m.tokens,2)" in UI_HTML)
    # The other direction of the same rule: a scale is not a claim, and nulling
    # one would blank every bar and every sparkline in the tab.
    check("a bar's width and a sparkline's range still floor their denominator, "
          "because a scale is a drawing decision and not a measurement",
          "const peak=Math.max(...head.map(x=>x[1][0]))||1;" in UI_HTML
          and "const rng=(hi-lo)||1;" in UI_HTML)

    u = usage_state(proj)
    check("usage_state on a project with no ledger is empty, not an error",
          u["facts"] == [] and u["totalRows"] == 0 and "ledgerDir" in u)
    led = os.path.join(proj, ".claude", "usage")
    os.makedirs(led, exist_ok=True)
    with open(os.path.join(led, "2026-08.jsonl"), "w", encoding="utf-8") as fh:
        for i, (model, author) in enumerate(
                (("claude-opus-5", "a@x.io"), ("claude-haiku-4-5", "b@x.io"))):
            fh.write(json.dumps({
                "ts": "2026-08-0%dT1%d" % (i + 1, i), "sessionId": "s%d" % i,
                "phaseId": "P1", "taskId": "P1.%d" % (i + 1), "attr": "task",
                "model": model, "author": author, "agentType": "audit-executor",
                "msgs": 2, "in": 5, "out": 100, "cacheW5m": 0, "cacheW1h": 0,
                "cacheR": 50, "costUSD": 0.25}) + "\n")
        fh.write("{ torn line\n")
    u = usage_state(proj)
    check("usage_state reads the ledger into positional facts",
          len(u["facts"]) == 2 and u["fields"][0] == "ts"
          and len(u["facts"][0]) == len(u["fields"]))
    check("usage_state tolerates a torn ledger line", u["totalRows"] == 2)
    check("usage_state carries phase titles for labelling",
          isinstance(u["phaseTitles"], dict))
    check("usage_state does not roll up a small ledger", u["rolled"] is False)
    check("usage facts carry no prompt content — only dimensions and counts",
          all(len(f) == 10 for f in u["facts"]))
    _saved = globals()["_MAX_FACTS"]
    try:
        globals()["_MAX_FACTS"] = 1
        ru = usage_state(proj)
        check("oversized ledger rolls hourly facts up to daily, and says so",
              ru["rolled"] is True and all(len(f[0]) == 10 for f in ru["facts"]))
    finally:
        globals()["_MAX_FACTS"] = _saved
    _cfg_path = os.path.join(proj, ".claude", "audit.config.json")
    _prev_cfg = (open(_cfg_path, encoding="utf-8").read()
                 if os.path.isfile(_cfg_path) else None)
    try:
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"enabled": False, "showCost": False}}, fh)
        du = usage_state(proj)
        check("usage_state reports metering off so the tab can explain itself",
              du["enabled"] is False and du["showCost"] is False)
        # The empty branch's own comment requires it: every key the populated
        # branch returns must appear here too, or a fresh install reads undefined.
        check("the no-ledger shape carries pricingAsOfDeclared as well, so a "
              "fresh install does not read undefined",
              "pricingAsOfDeclared" in du and du["pricingAsOfDeclared"] is False)
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"pricingAsOf": "2026-01-02"}}, fh)
        check("a declared date is reported as declared, and travels with it",
              usage_state(proj)["pricingAsOfDeclared"] is True
              and usage_state(proj)["pricingAsOf"] == "2026-01-02")
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"showCost": True}}, fh)
        _dd = usage_state(proj)
        check("an undeclared one still carries the merged default as the VALUE, "
              "flagged as undeclared - the client decides, the server does not lie",
              _dd["pricingAsOfDeclared"] is False and _dd["pricingAsOf"])
    finally:
        if _prev_cfg is None:
            os.remove(_cfg_path)
        else:
            with open(_cfg_path, "w", encoding="utf-8") as fh:
                fh.write(_prev_cfg)

    # lifecycle: pidfile + stop/status (no socket needed)
    check("_pid_alive on this process is True", _pid_alive(os.getpid()))
    check("_pid_alive on a bogus pid is False", not _pid_alive(2147483000))
    _write_pidfile(proj, {"pid": os.getpid(), "port": 1, "url": "http://x"})
    check("pidfile round-trips", (_read_pidfile(proj) or {}).get("pid") == os.getpid())
    _rm_pidfile(proj)
    check("status with no pidfile -> 0", status_panel(proj) == 0)
    check("stop with no pidfile -> 0", stop_panel(proj) == 0)
    # a stale pidfile (dead pid) is cleaned up, not treated as running
    _write_pidfile(proj, {"pid": 2147483000, "port": 1, "url": "http://x"})
    check("stop clears a stale pidfile", stop_panel(proj) == 0
          and _read_pidfile(proj) is None)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    sys.exit(main(sys.argv[1:]))
