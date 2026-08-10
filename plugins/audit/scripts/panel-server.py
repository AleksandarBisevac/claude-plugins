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
import importlib.util
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

# Fields the composition patch is allowed to touch — the security allow-list.
# `areas` is here so the registry can be written through the ONE write path that
# takes the lock, validates, journals and patches only the index (meta lives on the
# index; a registry save must never rewrite a phase shard). /api/areas is a thin
# front door onto it rather than a second writer.
_META_KEYS = ("reviewSkill", "buildCommands", "areas")
# ...of which these have no control on the Composition form: they are written by
# their own endpoint, so the confirm dialog's client-side change list must NOT
# enumerate them or it would compute a row for a field nobody can edit there. The
# selftest derives the client's list from this pair rather than trusting the two
# to be kept in step by hand.
_META_API_ONLY = ("areas",)
_META_FORM_KEYS = tuple(k for k in _META_KEYS if k not in _META_API_ONLY)
_PHASE_KEYS = ("reviewModel",)
_TASK_KEYS = ("model", "skills")


# --- the Settings form, described once, in Python --------------------------------
# WHY IN PYTHON. This used to be a `DESC = {...}` literal inside the UI string, and
# the form itself was hand-written field by field — so the set of settings the panel
# could edit was whatever someone had remembered to type. It had drifted: the whole
# `usage.*` block and four of the five `tddReminder.*` keys had no control at all,
# on the one surface whose entire job is making the config legible.
#
# Described here instead, the coverage question becomes mechanical. validate-config
# already knows every legal key (KNOWN_ROOT / KNOWN_SECRET / KNOWN_GUARD /
# KNOWN_BASHW / KNOWN_TDD / KNOWN_USAGE), so the selftest DERIVES the expected paths
# from the validator and compares — no hand-kept list on either side. A new config
# key without a control here fails the build rather than quietly not existing in the
# UI.
#
# `kind` drives a generic renderer for the ordinary shapes; `custom` hands the path
# to a bespoke renderer in the UI (lists of regexes, the rules table, the band pair,
# the pricing rows). Either way the path appears here, so it counts as covered.
FIELD_HELP = {
    "manifestPath":
        "Path to the audit manifest JSON, relative to this project. "
        "Default docs/audit/audit-plan.json.",
    "gitRoot":
        "Path of the git repo root, where git and the build/gate commands run. "
        "Default '.' — this directory IS the git root.",
    "stateDir":
        "Where the hooks keep their per-session state files. They are local scratch, "
        "garbage-collected after 7 days; gitignore them.",
    "logsDir": "Where the hooks write the bypass log. Local scratch; gitignore it.",
    "bypassKeyword":
        "Type this in a prompt to arm a ONE-OFF plan-first bypass for the next edit. "
        "It is consumed by that edit and logged.",
    "trivialLineThreshold":
        "The first file you touch in a session is free if the edit adds at most this "
        "many lines. Anything larger needs a plan.",
    "enforce":
        "Force the plan gate to DENY even with no manifest. Off by default, which "
        "grades it on evidence: observe (no manifest) -> warn (a manifest, nothing "
        "running) -> deny (a phase is in_progress). The secret guards are never "
        "graded — they deny either way.",
    "exemptGlobs":
        "Globs whose edits skip the plan-first, TDD and shell-write guards — docs, "
        "tests, .claude/** and the manifest. Globs, not regexes: each one is matched "
        "against the whole relative path AND against the bare file name, so "
        "**/*.test.* and *.test.* both work.",
    "secretPatterns.extra":
        "Extra file paths to treat as secrets, so reading one is refused. These are "
        "REGEXES, not globs, and they are matched case-insensitively anywhere in the "
        "path: '.env' means 'any character, then env' and matches secrets.envelope. "
        "Write \\.env$ if you mean the file. A pattern that does not compile is "
        "dropped in silence at runtime — this form refuses to save one instead.",
    "guardEdits.tokenVars":
        "Identifier names that must never be logged: a console.log or print of any "
        "of these is blocked. Your list REPLACES the three defaults rather than "
        "adding to them.",
    "guardEdits.customRules":
        "Your own banned patterns: block a regex in new content when a piece of text "
        "appears in the path being edited. The path test is a SUBSTRING match against "
        "the path the edit tool reported (usually absolute), so 'realtime/' covers "
        "every realtime/ directory in the repo. A rule missing either field, or whose "
        "pattern does not compile, is skipped in silence at runtime — this form "
        "refuses to save one instead.",
    "bashWriteCheck.enabled":
        "After a Bash command, diff git status and warn when it created source files "
        "that were not planned. A warning, never a block.",
    "tddReminder.enabled":
        "Nudge when you edit source without touching a test. Non-blocking: it prints "
        "a reminder and gets out of the way.",
    "tddReminder.sourceGlobs":
        "Globs that count as source, so editing one is a candidate for the nudge. "
        "This list also defines what 'source' means to the shell-write guard — the "
        "two read the same setting so they cannot disagree.",
    "tddReminder.testGlobs":
        "Globs that count as tests. Touching one in the same session silences the "
        "nudge.",
    "tddReminder.throttleMinutes":
        "Least time between two nudges in one session. 0 means nudge every time.",
    "tddReminder.inProgressPolicy":
        "What the nudge does while an audit task is in_progress. skip-gate-only "
        "(default) stays quiet for files the task already covers; skip-all goes quiet "
        "for the whole run; warn-always ignores the manifest entirely.",
    "usage.enabled":
        "Meter token usage on the Stop and SubagentStop hooks. The ledger records "
        "counts, model ids, timestamps, branch and author — never prompt content.",
    "usage.ledgerDir":
        "Where the monthly NDJSON ledger and its scan cursors are written. "
        "Deliberately outside stateDir, which is garbage-collected: a lost cursor "
        "would re-scan a transcript from the start and double-count.",
    "usage.authorMode":
        "How the spender is recorded: their git email, their git name, a short "
        "salt-free sha256 (pseudonymous but still groupable), or nobody at all.",
    "usage.showCost":
        "Show an equivalent API cost beside the tokens. Labelled 'equiv' because a "
        "subscription plan carries no per-token bill.",
    "usage.backfillOnFirstRun":
        "The first time a transcript is seen, read it from the start instead of "
        "metering only from now on. Bounded by the scan ceiling below.",
    "usage.maxScanBytes":
        "Ceiling in bytes for that first-sight backfill; above it the scan seeks to "
        "the end, so the 10-second hook timeout stays safe. "
        "'/audit:usage --backfill' has no ceiling.",
    "usage.currency": "Currency label printed beside the rates. Default USD.",
    "usage.pricingAsOf":
        "The date the rate table below was accurate. Surfaced in the report and the "
        "Usage tab so a stale rate is visible rather than assumed — until you set it, "
        "both say the rates are undated rather than showing you a date you never "
        "chose.",
    "usage.bands":
        "Absolute thresholds that sort each task's spend into typical / high / "
        "outlier. Leave both empty and the bands calibrate from this project's own "
        "completed tasks (median and p90), which needs no guess to mean something. "
        "Set both to band by a real budget instead.",
    "journal.enabled":
        "Record every write to the plan and to this config in an append-only, "
        "hash-chained journal: who, when, what changed, and the state it left "
        "behind. Panel saves and edit-tool writes are recorded; shell writes cannot "
        "be, and show up instead as a document that changed with no row to explain "
        "it. Tamper-EVIDENT, not tamper-proof - `audit-journal.py verify` names an "
        "edited, deleted or reordered row, but nothing here can stop someone "
        "rewriting the whole file.",
    "journal.dir":
        "Where the monthly per-writer .jsonl files live. Empty keeps them beside "
        "the manifest, which is what lets one commit carry both the change and the "
        "record of it. One file per writer, so two sessions in two worktrees never "
        "conflict.",
    "usage.pricing":
        "Rates in this project's currency per MILLION tokens. Lookup is exact match, "
        "then longest matching prefix — so a dated model id resolves to its family — "
        "then the _default row. Leave a cell empty to keep the shipped rate shown in "
        "it.",
}

# The manifest levers the Composition tab edits. A separate dict on purpose: these
# are not config paths, and the coverage selftest above would have to special-case
# them if they lived in the same namespace.
COMPOSITION_HELP = {
    "reviewSkill": "Skill the reviewer agent invokes at phase sign-off. Empty = tests"
                   " are the only signer.",
    "buildCommands": "Named shell commands (typecheck / test / lint …) the pipeline "
                     "runs as gates.",
    "phaseReviewModel": "Model used for this phase's sign-off review.",
    "taskModel": "Model the executor uses to implement this task.",
    "taskSkills": "Skills the executor loads (via the Skill tool) before writing code "
                  "for this task.",
}

SETTINGS_GROUPS = (
    {
        "id": "paths",
        "title": "Paths & gate",
        "blurb": "Where the plugin looks for things, and how hard the plan-first gate "
                 "pushes. Paths are relative to this project directory. Leave a field "
                 "empty to use the default shown inside it — nothing is written for a "
                 "setting you have not changed.",
        "fields": (
            {"path": "manifestPath", "label": "The plan", "kind": "text"},
            {"path": "gitRoot", "label": "Git root", "kind": "text"},
            {"path": "stateDir", "label": "Hook state", "kind": "text"},
            {"path": "logsDir", "label": "Hook logs", "kind": "text"},
            {"path": "bypassKeyword", "label": "Bypass keyword", "kind": "text"},
            {"path": "trivialLineThreshold", "label": "Free first touch, in lines",
             "kind": "int", "min": 1},
            {"path": "enforce", "label": "Always deny edits outside the plan",
             "kind": "bool"},
            {"path": "exemptGlobs", "label": "Paths the guards skip", "kind": "list",
             "placeholder": "glob…"},
        ),
    },
    {
        "id": "guards",
        "title": "Write guards",
        "blurb": "The rules that can REFUSE an edit rather than warn about it. Unlike "
                 "the plan gate these are never graded on evidence: logging an auth "
                 "token is wrong whether or not a plan exists.",
        "fields": (
            {"path": "bashWriteCheck.enabled",
             "label": "Warn on unplanned shell writes", "kind": "bool"},
            {"path": "guardEdits.tokenVars",
             "label": "Secrets never written to logs", "kind": "custom"},
            {"path": "secretPatterns.extra",
             "label": "Extra files treated as secrets", "kind": "custom"},
            {"path": "guardEdits.customRules", "label": "Your own banned patterns",
             "kind": "custom"},
        ),
    },
    {
        "id": "tdd",
        "title": "TDD reminder",
        "blurb": "A nudge, never a block. It prints one line when you change source "
                 "without touching a test, and then leaves you alone for the throttle "
                 "window.",
        "fields": (
            {"path": "tddReminder.enabled", "label": "Nudge when tests are untouched",
             "kind": "bool"},
            {"path": "tddReminder.throttleMinutes", "label": "Minutes between nudges",
             "kind": "number", "min": 0},
            {"path": "tddReminder.inProgressPolicy",
             "label": "While an audit task is running", "kind": "enum",
             "enum": "inProgressPolicy"},
            {"path": "tddReminder.sourceGlobs", "label": "What counts as source",
             "kind": "list", "placeholder": "glob…"},
            {"path": "tddReminder.testGlobs", "label": "What counts as a test",
             "kind": "list", "placeholder": "glob…"},
        ),
    },
    {
        "id": "usage",
        "title": "Usage & pricing",
        "blurb": "Token metering and the rate table every dollar in the Usage tab is "
                 "computed from. The ledger holds counts, model ids, timestamps, "
                 "branch and author — never prompt content.",
        "fields": (
            {"path": "usage.enabled", "label": "Meter token usage", "kind": "bool"},
            {"path": "usage.showCost", "label": "Show equivalent cost", "kind": "bool"},
            {"path": "usage.backfillOnFirstRun",
             "label": "Read transcripts already on disk", "kind": "bool"},
            {"path": "usage.ledgerDir", "label": "Ledger directory", "kind": "text"},
            {"path": "usage.authorMode", "label": "How the spender is recorded",
             "kind": "enum", "enum": "authorMode"},
            {"path": "usage.currency", "label": "Currency label", "kind": "text"},
            {"path": "usage.pricingAsOf", "label": "Rates accurate as of",
             "kind": "date"},
            {"path": "usage.maxScanBytes", "label": "Backfill ceiling, bytes",
             "kind": "int", "min": 0},
            {"path": "usage.bands", "label": "Cost bands", "kind": "custom"},
            {"path": "usage.pricing", "label": "Rates per million tokens",
             "kind": "custom"},
        ),
    },
    {
        "id": "journal",
        "title": "Audit trail",
        # No backticks in a blurb: it is rendered as text, not as markdown, and the
        # other four say their command names plainly for the same reason.
        "blurb": "An append-only, hash-chained record of every change to the plan "
                 "and to these settings. Tamper-EVIDENT, not tamper-proof: editing, "
                 "deleting or reordering a row breaks the chain and audit-journal.py "
                 "verify names it - but with no secret key to keep on your own "
                 "machine, nothing here can stop someone rewriting the whole file. "
                 "It is a smoke detector, not a vault.",
        "fields": (
            {"path": "journal.enabled", "label": "Record plan and config writes",
             "kind": "bool"},
            {"path": "journal.dir", "label": "Where the record is kept",
             "kind": "text", "placeholder": "beside the manifest"},
        ),
    },
)


def _src_of_this_file():
    """This module's own source — for the selftests that must assert a server-side
    construct (a route, a call order) rather than a rendered string."""
    with open(__file__, encoding="utf-8") as fh:
        return fh.read()


def _settings_paths():
    """Every config path the Settings form binds a control to."""
    return [f["path"] for g in SETTINGS_GROUPS for f in g["fields"]]


def _cfg_enums():
    """The enum choices, read off the validator that enforces them.

    Not a copy. `warn-always` was documented in four places, implemented in
    remind-tdd.py and rejected by validate-config, so following the documentation
    produced a config the panel refused to save; a hand-kept list of options in the
    UI is the same failure with one more place to forget."""
    _, vc, _, _ = _cores()
    return {"inProgressPolicy": list(vc.IN_PROGRESS_POLICY),
            "authorMode": list(vc.AUTHOR_MODES)}


# --- lazy import of the plugin's own pure cores (hyphenated filenames) ----------
def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_VM = _VC = _AS = _CFG = None


def _cores():
    """Load (once) validate-manifest, validate-config, audit-status, _config."""
    global _VM, _VC, _AS, _CFG
    if _VM is None:
        _VM = _load("audit_validate_manifest",
                    os.path.join(_HERE, "validate-manifest.py"))
        _VC = _load("audit_validate_config",
                    os.path.join(_HERE, "validate-config.py"))
        _AS = _load("audit_status", os.path.join(_HERE, "audit-status.py"))
        _CFG = _load("audit__config",
                     os.path.join(_HERE, "..", "hooks", "_config.py"))
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
            ul = _load("audit_usage_ledger", os.path.join(_HERE, "usage_ledger.py"))
            author = ul.resolve_author(project, mode)
        except Exception:
            author = None
        _VIEWER_CACHE[key] = {"author": author, "mode": mode}
    return _VIEWER_CACHE[key]


def _atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --- discovery / registry -------------------------------------------------------
def _front_matter(text):
    """Parse the leading '--- ... ---' block into a flat {key: value} dict.
    Stdlib only (no YAML dep); good enough for `name` / `description`."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            val = m.group(2).strip().strip("\"'")
            fm[m.group(1)] = val
    return fm


def _fm_of(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _front_matter(fh.read(4096))
    except Exception:
        return {}


def _entry(name, description, source, path):
    return {"name": name, "description": (description or "")[:280],
            "source": source, "path": path}


def _scan_skills(base, source, out, seen, cap=500):
    """Add every <base>/*/SKILL.md as a skill entry."""
    skills_dir = os.path.join(base, "skills")
    if not os.path.isdir(skills_dir):
        return
    for name in sorted(os.listdir(skills_dir)):
        if len(out) >= cap:
            return
        sk = os.path.join(skills_dir, name, "SKILL.md")
        if os.path.isfile(sk):
            fm = _fm_of(sk)
            key = (fm.get("name") or name)
            if key in seen:  # dedupe by name; project/user scanned before plugins win
                continue
            seen.add(key)
            out.append(_entry(key, fm.get("description"), source, sk))


def _scan_agents(base, source, out, seen, cap=500):
    agents_dir = os.path.join(base, "agents")
    if not os.path.isdir(agents_dir):
        return
    for name in sorted(os.listdir(agents_dir)):
        if len(out) >= cap:
            return
        if not name.endswith(".md"):
            continue
        ap = os.path.join(agents_dir, name)
        fm = _fm_of(ap)
        key = fm.get("name") or name[:-3]
        if key in seen:  # dedupe by name; project/user scanned before plugins win
            continue
        seen.add(key)
        out.append(_entry(key, fm.get("description"), source, ap))


def _plugin_bases(home, cap=200):
    """Directories that may hold skills/agents inside the plugins tree."""
    root = os.path.join(home, ".claude", "plugins")
    bases = []
    if not os.path.isdir(root):
        return bases
    for dirpath, dirnames, _files in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth > 5:
            dirnames[:] = []
            continue
        if os.path.basename(dirpath) in ("skills", "agents"):
            bases.append(os.path.dirname(dirpath))
        if len(bases) >= cap:
            break
    return sorted(set(bases))


def discover(project, home=None):
    """Return {skills, agents, mcp} available to this project (read-only scan)."""
    home = home or os.path.expanduser("~")
    skills, agents, s_seen, a_seen = [], [], set(), set()
    # project-local
    _scan_skills(os.path.join(project, ".claude"), "project", skills, s_seen)
    _scan_agents(os.path.join(project, ".claude"), "project", agents, a_seen)
    # user-global
    _scan_skills(os.path.join(home, ".claude"), "user", skills, s_seen)
    _scan_agents(os.path.join(home, ".claude"), "user", agents, a_seen)
    # installed plugins (parent-dir basename is often a version/cache name — noise,
    # so use a plain 'plugin' badge)
    for base in _plugin_bases(home):
        _scan_skills(base, "plugin", skills, s_seen)
        _scan_agents(base, "plugin", agents, a_seen)
    # this repo's own plugins (dev / local checkout — basename is the real name)
    for base in sorted(_local_plugin_bases(project)):
        label = "plugin:" + os.path.basename(base)
        _scan_skills(base, label, skills, s_seen)
        _scan_agents(base, label, agents, a_seen)
    # MCP servers (names only — never surface secrets/tokens)
    mcp = _mcp_names(home, project)
    return {"skills": skills, "agents": agents, "mcp": mcp}


def _local_plugin_bases(project):
    root = os.path.join(project, "plugins")
    out = []
    if os.path.isdir(root):
        for name in os.listdir(root):
            d = os.path.join(root, name)
            if os.path.isdir(os.path.join(d, "skills")) or \
               os.path.isdir(os.path.join(d, "agents")):
                out.append(d)
    return out


def _mcp_names(home, project):
    names = set()
    for path in (os.path.join(home, ".claude.json"),
                 os.path.join(project, ".mcp.json")):
        try:
            data = _read_json(path)
        except Exception:
            continue
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict):
            names.update(str(k) for k in servers.keys())
    return sorted(names)


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
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "audit_lock", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "audit-lock.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
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
                _JOURNAL["mod"] = _load("audit_journal", path)
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
UI_HTML = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>audit · control panel</title>
<style>
/*__THEME_TOKENS__*/
/* Panel-only roles. The shared tokens carry the product's colour; these three
   name jobs the report has no equivalent of — a validated field, a warning on a
   config value, a refused write — so they live here rather than pushing
   panel-shaped vocabulary into the shared layer. */
:root{--ok:#15803d;--warn:#b45309;--err:#dc2626}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
 --ok:#34d399;--warn:#fbbf24;--err:#f87171}}
:root[data-theme=dark]{--ok:#34d399;--warn:#fbbf24;--err:#f87171}
*{box-sizing:border-box}
/* Reserve the scrollbar always: Guards is short and Overview is long, and
   without this the whole centred shell jumps sideways between them. */
html{background:var(--bg);scrollbar-gutter:stable}
body{font:15px/1.6 var(--sans);color:var(--text);background:var(--bg);
 margin:0;padding:0;-webkit-font-smoothing:antialiased}

/* ---- app shell -----------------------------------------------------------
   Same split as the report — navigation at the side, actions on top — but the
   two are not the same kind of thing, and the nav reflects that. The report's
   sidebar points INTO one long document and marks where you are. This one
   switches between five exclusive views, so it is real navigation: `aria-current`
   on the active view, no scroll-spy, and the five remain five wherever they are
   drawn.

   Deliberately NOT collapsible to an icon rail. The rail pattern exists to stop a
   long nav competing with content for width; with five items it would add a
   control and a persisted preference to save 230px on screens that have it to
   spare, and five hand-drawn icons that mean less than the words they replace. */
.top{position:sticky;top:0;z-index:var(--z-topbar);display:flex;align-items:center;gap:.75rem 1rem;
 flex-wrap:nowrap;padding:.6rem 1.25rem;
 background:color-mix(in srgb,var(--surface) 88%,transparent);backdrop-filter:blur(10px);
 border-bottom:1px solid var(--border)}
.top>div:first-child{min-width:0;margin-right:auto;max-width:min(52%,34rem)}
.shell{display:grid;grid-template-columns:var(--nav-w) minmax(0,1fr);gap:var(--shell-gap);
 max-width:92rem;margin:0 auto;padding:1.25rem 1.25rem 4rem;align-items:start}
.view{min-width:0}
.tabs{position:sticky;top:calc(var(--topbar-h) + var(--sp-1))}
.tabs .navttl{font-size:var(--t-label);text-transform:uppercase;letter-spacing:.12em;
 color:var(--muted);font-weight:700;margin:0 0 .4rem .6rem}
@media(max-width:70rem){
 /* One information architecture, two presentations: the same five buttons become
    a horizontal strip. Never a second menu. */
 .shell{grid-template-columns:minmax(0,1fr);gap:.75rem;padding-top:.5rem}
 .tabs{position:sticky;top:var(--topbar-h);z-index:var(--z-strip);margin:0 -1.25rem;padding:.4rem 1.25rem;
  background:var(--bg);border-bottom:1px solid var(--border);
  overflow-x:auto;overflow-y:hidden}
 .tabs .navttl{display:none}
 /* Only when it really does not fit — see tabsOverflow(). A row that scrolls
    with no edge to say so reads as a row with four items in it, which is what a
    phone showed the day a fifth was added. The class is set from the measured
    width rather than from this breakpoint: whether five buttons fit depends on
    their words, not on the viewport this rule happens to start at. */
 .tabs.scrolls{mask-image:linear-gradient(to right,#000 calc(100% - 2.5rem),transparent);
  -webkit-mask-image:linear-gradient(to right,#000 calc(100% - 2.5rem),transparent)}
}
h1{font-size:1.35rem;font-weight:680;letter-spacing:-.02em;margin:0}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
 font-weight:700;margin:1.5rem 0 .5rem}
/* The JSON key beside a human heading. `text-transform:none` is the whole point:
   it sits inside an uppercased h2, and a config key is case-sensitive — uppercased
   it would be a string you cannot paste back into the file. */
.k2{font-family:var(--mono);font-size:.72rem;text-transform:none;letter-spacing:0;
 font-weight:500;color:var(--muted);opacity:.8;margin-left:.45rem;
 background:var(--surface-2);border:1px solid var(--border);border-radius:4px;padding:.02rem .3rem}
/* One line, middle-elided, full path in the tooltip. `word-break:break-all` wrapped
   a long project path across two lines and pushed the header controls down — and it
   broke at an arbitrary character, so neither the root nor the project name stayed
   readable. A path's two ends are the informative parts; the middle is what to drop. */
.sub{color:var(--muted);font-family:var(--mono);font-size:.78rem;margin:.25rem 0 0;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:min(56ch,100%)}
.tabs{display:flex;flex-direction:column;gap:.15rem;margin:0}
.tab{cursor:pointer;font:inherit;font-size:.87rem;text-align:left;padding:.42rem .65rem;
 border-radius:var(--radius);border:1px solid transparent;border-left:2px solid transparent;
 background:transparent;color:var(--muted);transition:all var(--dur) var(--ease)}
@media(max-width:70rem){
 .tabs{flex-direction:row;gap:.25rem;white-space:nowrap}
 .tab{border-left:none;border-bottom:2px solid transparent;
  border-radius:var(--radius) var(--radius) 0 0}
}
.tab:hover{border-color:var(--border-strong)}
.tab.on{background:var(--surface-2);color:var(--text);font-weight:600;
 border-left-color:var(--accent)}
@media(max-width:70rem){.tab.on{border-left-color:transparent;border-bottom-color:var(--accent)}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);
 box-shadow:var(--shadow-sm);padding:1rem 1rem;margin:.75rem 0}
.row{display:flex;gap:.75rem;flex-wrap:wrap;align-items:center;margin:.5rem 0}
label.f{display:flex;flex-direction:column;gap:.25rem;flex:1 1 15rem;font-size:.82rem;color:var(--muted)}
input,textarea,select{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--border);
 border-radius:var(--radius);padding:.5rem .75rem;font-size:.9rem}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
textarea{font-family:var(--mono);font-size:.82rem;min-height:4.5rem;resize:vertical}
.mono{font-family:var(--mono)}
.btn{cursor:pointer;font:inherit;font-size:.85rem;padding:.5rem 1rem;border-radius:var(--pill);
 border:1px solid var(--border);background:var(--surface);color:var(--text);transition:all var(--dur) var(--ease)}
.btn:hover{border-color:var(--border-strong);transform:translateY(-1px);box-shadow:var(--shadow-sm)}
.btn:active{transform:none}.btn:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.btn.primary{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
.btn.small{font-size:.75rem;padding:.25rem .5rem}
.badge{font-size:.68rem;font-weight:700;padding:.25rem .5em;border-radius:var(--pill);
 background:var(--surface-2);color:var(--muted);border:1px solid var(--border)}
.badge.run{background:color-mix(in srgb,var(--ok) 16%,transparent);color:var(--ok);border-color:transparent}
/* A lock whose holder is gone is not green: nothing is running, and nothing is
   wrong yet either — it is the state the human has to resolve. */
.badge.held{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warn);border-color:transparent}
.badge.claim{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warn);border-color:transparent}
.badge.area{background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent);border-color:transparent;text-transform:uppercase;letter-spacing:.03em}
.chip{display:inline-flex;align-items:center;gap:.3em;font-size:.76rem;padding:.25rem .5em;border-radius:var(--pill);
 background:var(--surface-2);border:1px solid var(--border);color:var(--text)}
.chip button{border:none;background:none;color:var(--muted);cursor:pointer;font-size:.9em;padding:0}
.tag{display:inline-block;font-size:.66rem;padding:.25rem .45em;border-radius:var(--pill);
 border:1px solid var(--border);color:var(--muted);margin-left:.25rem}
.listwrap{display:flex;flex-direction:column;gap:.25rem}
.pill-in{display:flex;gap:.25rem;flex-wrap:wrap;align-items:center;border:1px solid var(--border);
 border-radius:var(--radius);padding:.25rem .5rem;background:var(--bg)}
.pill-in input{border:none;background:none;box-shadow:none;flex:1 1 6rem;padding:.25rem .25rem}
.mut{color:var(--muted);font-size:.82rem}
.bar{height:.5rem;border-radius:var(--pill);background:var(--surface-2);overflow:hidden;flex:1 1 8rem;min-width:6rem}
.bar>i{display:block;height:100%;background:var(--accent)}
.grid{display:grid;grid-template-columns:1fr;gap:.5rem}
/* usage tab */
.uctx{font-size:.74rem;color:var(--muted);margin:0 0 var(--sp-2)}
.ufil{position:sticky;top:0;z-index:6;display:flex;flex-wrap:wrap;gap:var(--sp-1);
 align-items:center;margin:0 0 var(--sp-1);padding:var(--sp-1) 0;
 background:var(--surface);border-bottom:1px solid var(--border)}
/* Two rows, not one wrapping heap. Nine controls on one line wrap wherever the
   viewport happens to break, which puts "to" above its date input as often as
   beside it. The split is by JOB - who and what on top, when and how far down -
   so the pairs that read together cannot be separated by a reflow. */
.ufrow{display:flex;flex-wrap:wrap;gap:var(--sp-1);align-items:center;flex:1 1 100%}
.ufil .combo{flex:1 1 9rem;min-width:7.5rem}
.ufil input,.ufil select{font:inherit;font-size:.78rem;width:100%;
 padding:var(--sp-0) var(--sp-1);border-radius:var(--radius);
 border:1px solid var(--border);background:var(--bg);color:var(--text)}
.ufil select{flex:0 0 auto;width:auto}
.ufil .usearch{flex:2 1 12rem;min-width:9rem}
.ufil input[type=date]{flex:0 0 auto;width:auto}
/* The four of them are ONE control and wrap as one: a bare "from" stranded at the
   end of the row above its own input is a label for nothing. */
.udates{display:flex;align-items:center;gap:var(--sp-1);flex:0 1 auto}
.ufil input:focus-visible,.ufil select:focus-visible{outline:2px solid var(--ring);
 outline-offset:1px}
.ufil .filtlbl{font-size:.72rem;color:var(--muted)}
.ufil .push{margin-left:auto}
/* active filters: what is scoping the view, and a way out of each */
.uchips{display:flex;flex-wrap:wrap;gap:var(--sp-1);align-items:center;
 margin:0 0 var(--sp-2)}
.uchip{display:inline-flex;align-items:center;gap:var(--sp-0);font:inherit;
 font-size:.72rem;padding:var(--sp-0) var(--sp-1);border-radius:var(--pill);
 border:1px solid var(--border-strong);background:var(--surface-2);
 color:var(--text);cursor:pointer}
.uchip:hover{border-color:var(--accent)}
.uchip .ck{color:var(--muted)}
.uchip .cx{color:var(--muted);font-weight:600}
/* An empty view explains itself, and offers the narrowest way out beside the
   widest one. Two buttons rather than one: "clear filters" throws away the seven
   that were fine in order to lift the one that was not. */
.uempty{display:flex;flex-wrap:wrap;gap:var(--sp-1);align-items:center;
 margin-top:var(--sp-1)}
.utiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(7.5rem,1fr));
 gap:var(--sp-1);margin:0 0 var(--sp-3)}
.utile{border:1px solid var(--border);border-radius:var(--radius);
 padding:var(--sp-1) var(--sp-2);background:var(--bg)}
.utile .k{font-size:var(--t-label);text-transform:uppercase;letter-spacing:.07em;
 color:var(--muted)}
.utile .v{font-size:1.25rem;font-weight:660;letter-spacing:-.02em;
 margin-top:var(--sp-0);display:flex;align-items:baseline;gap:var(--sp-0)}
/* The sparkline sits under the number at its own intrinsic size, and the row keeps
   its height whether or not there is one to draw - so a tile without a daily series
   does not shorten its card and knock the grid out of line. */
.utrend{height:20px;margin-top:var(--sp-0);display:flex;align-items:center;
 color:var(--muted);font-size:.7rem}
.dl{font-size:.68rem;font-weight:600;padding:0 .3rem;border-radius:var(--pill);
 letter-spacing:0;font-variant-numeric:tabular-nums;
 color:var(--muted);background:var(--surface-2)}
/* Direction is stated by a glyph before it is stated by a hue: an arrow survives
   greyscale, forced-colours and paper, and the sign alone is easy to miss at
   .68rem. Colour is reserved for the ONE metric that has a direction worth
   judging - attribution coverage. Tokens and dollars going up is not good news or
   bad news, it is just news, and painting it green said otherwise for four
   releases. */
.dl.up::before{content:"\25b2\a0";font-size:.62em;vertical-align:.1em}
.dl.down::before{content:"\25bc\a0";font-size:.62em;vertical-align:.1em}
.dl.good{color:var(--ok);background:color-mix(in srgb,var(--ok) 14%,transparent)}
.dl.bad{color:var(--warn);background:color-mix(in srgb,var(--warn) 14%,transparent)}
/* A word-sized graphic: shape only, no axis and no labels. Everything it would
   need to be read precisely is in the chart directly below it. */
.uspark{display:block;overflow:visible}
.uspark .sa{fill:color-mix(in srgb,var(--accent-solid) 16%,transparent);stroke:none}
.uspark .sl{fill:none;stroke:var(--accent-solid);stroke-width:1.4;
 stroke-linejoin:round;stroke-linecap:round}
.uspark .sd{fill:var(--accent-solid)}
.ucrumb{font-size:.74rem;margin:0 0 var(--sp-1)}
.lnk{background:none;border:0;color:var(--accent);font:inherit;font-size:.76rem;
 cursor:pointer;padding:0}
.lnk:hover{text-decoration:underline}
/* The slot reserves the chart's height so the card does not jump between the first
   paint and the measured redraw one frame later. */
.chartslot{display:block;width:100%;height:190px;margin:var(--sp-0) 0 var(--sp-1)}
.uchart{width:100%;height:190px;display:block}
.uchart.pick{cursor:crosshair}
.uchart .g{stroke:var(--border);stroke-width:1;fill:none}
/* 10px, not 8px: the viewBox is now 1:1 with device pixels, so this is the real
   rendered size. The old 8px only looked bigger because it was being stretched. */
.uchart .ax{fill:var(--muted);font-size:10px;font-family:var(--sans)}
.uchart .ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;
 pointer-events:none}
.uchart .lnhit{fill:none;stroke:transparent;stroke-width:12;
 stroke-linejoin:round;stroke-linecap:round;cursor:pointer}
.uchart .dot{stroke:var(--surface);stroke-width:2}
.uchart .cross{stroke:var(--border-strong);stroke-width:1;stroke-dasharray:none}
.uchart .cross.hidden{display:none}
.ulegend{display:flex;flex-wrap:wrap;gap:var(--sp-1) var(--sp-3);font-size:.75rem;
 margin:0 0 var(--sp-2)}
.ulegend b{display:inline-flex;align-items:center;gap:var(--sp-0);font-weight:500}
.ulegend b.pick{cursor:pointer}
.ulegend b.pick:hover{text-decoration:underline}
.ulegend i{width:.6rem;height:.6rem;border-radius:3px;display:inline-block}
.urow{display:grid;grid-template-columns:minmax(8rem,20rem) minmax(4rem,1fr) auto;
 gap:var(--sp-2);align-items:center;margin:var(--sp-0) 0;font-size:.8rem;
 padding:var(--sp-0) var(--sp-1);border-radius:var(--radius);
 border:1px solid transparent}
.urow.pick{cursor:pointer}
.urow.pick:hover{background:var(--surface-2)}
.urow.on{border-color:var(--accent);background:var(--surface-2)}
.urow.tail .unm{font-style:italic}
.unm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.uamt{font-variant-numeric:tabular-nums;color:var(--muted);white-space:nowrap;
 font-size:.75rem}
.ufact{font-size:.82rem;margin:var(--sp-0) 0}
.small{font-size:.75rem}
.utbl{width:100%;border-collapse:collapse;font-size:.78rem;margin-top:var(--sp-1)}
.utbl th{text-align:left;font-size:var(--t-label);text-transform:uppercase;
 letter-spacing:.06em;color:var(--muted);font-weight:500;
 padding:var(--sp-0) var(--sp-1);border-bottom:1px solid var(--border)}
.utbl td{padding:var(--sp-0) var(--sp-1);border-bottom:1px solid var(--border)}
.utbl tr:last-child td{border-bottom:0}
/* The one recommendation in the tab — marked so it reads as advice, not as
   another measurement. */
.advice{border-left:3px solid var(--warn);background:var(--surface-2);
 border-radius:var(--radius);padding:var(--sp-1) var(--sp-2);margin:var(--sp-1) 0;
 font-size:.82rem}
.advice code{font-size:.95em}
/* Budget burn-down. Shares the ranked-row grid so the two read as one family. */
.bud{display:grid;grid-template-columns:minmax(8rem,20rem) minmax(4rem,1fr) 3rem auto;
 align-items:center;gap:var(--sp-1);margin:var(--sp-0) 0;font-size:.8rem}
.bud .bar{height:.5rem;background:var(--surface-2);border-radius:var(--pill);
 overflow:hidden}
.bud .bar i{display:block;height:100%;border-radius:var(--pill);background:var(--ok)}
.bud.over .bar i{background:var(--err)}
.bud .bpct{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.bud.over .bpct{color:var(--err);font-weight:640}
.bud.total{border-top:1px solid var(--border);padding-top:var(--sp-1);
 margin-top:var(--sp-1)}
/* The total has no bar; an empty track would paint a grey rail that reads as a
   phase sitting at zero, which is the one thing this block must never imply. */
.bud.total .bar{background:none}
@media (max-width:34rem){.bud{grid-template-columns:1fr auto}.bud .bar{display:none}}
/* Controls under each ranked list. Expanding costs one click; collapsing must too. */
.uctl{display:flex;align-items:center;gap:var(--sp-1);margin:var(--sp-0) 0 var(--sp-2);
 font-size:.76rem}
/* Browse dialog. Native <dialog>, so the focus trap, the backdrop and Esc are the
   platform's rather than ours. */
dialog.browse{width:min(56rem,calc(100vw - 2rem));max-height:calc(100vh - 4rem);
 padding:0;border:1px solid var(--border-strong);border-radius:var(--radius-lg);
 background:var(--surface);color:var(--text);box-shadow:var(--shadow-md);
 overflow:hidden}
dialog.browse::backdrop{background:rgb(0 0 0 / .45)}
dialog.browse>*{padding:0 var(--sp-3)}
.bhead{display:flex;align-items:baseline;justify-content:space-between;gap:var(--sp-2);
 padding-top:var(--sp-2)}
.bhead h2,.bhead h3{margin:0;font-size:1rem;font-weight:640}
.bx{border:none;background:none;color:var(--muted);cursor:pointer;font-size:1rem;
 line-height:1;padding:var(--sp-0)}
.bx:hover{color:var(--text)}
.btblwrap{max-height:min(60vh,28rem);overflow:auto;border-top:1px solid var(--border);
 padding:0}
table.btbl{width:100%;border-collapse:separate;border-spacing:0;font-size:.8rem}
table.btbl th{position:sticky;top:0;z-index:1;background:var(--surface-2);
 color:var(--muted);text-align:left;font-size:var(--t-label);text-transform:uppercase;
 letter-spacing:.05em;padding:var(--sp-1) var(--sp-2);white-space:nowrap;
 border-bottom:1px solid var(--border)}
table.btbl th.pick{cursor:pointer;user-select:none}
table.btbl th.pick:hover{color:var(--text)}
table.btbl th.on{color:var(--text)}
.sarrow{margin-left:.25em}
table.btbl td{padding:var(--sp-1) var(--sp-2);border-bottom:1px solid var(--border);
 vertical-align:middle}
/* A wrapping title turns a scannable table into a wall: one long task name pushes
   every other row four lines tall. Truncate, and keep the full text on hover. */
table.btbl td.t{max-width:20rem;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
table.btbl .n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
/* Model mix: a stack the eye reads for proportion, and the dominant model in text
   so identity never rests on colour alone. */
.mcell{display:inline-flex;align-items:center;gap:var(--sp-1);white-space:nowrap}
.mstack{display:inline-flex;width:3.4rem;height:.5rem;border-radius:var(--pill);
 overflow:hidden;flex:0 0 auto;background:var(--surface-2)}
.mstack i{display:block;height:100%}
.mstack i+i{box-shadow:-1px 0 0 var(--surface)}
.mdom{color:var(--muted);font-size:.92em}
/* Cost band. Status colours are reserved and never travel alone, so the pill
   carries the word — and the task's own status sits in the next column wearing
   the same palette, which makes the label load-bearing rather than decorative. */
.bandpill{display:inline-block;padding:.05rem .45rem;border-radius:var(--pill);
 font-size:.72rem;font-weight:600;white-space:nowrap;border:1px solid transparent}
.b-typical{color:var(--ok);background:color-mix(in srgb,var(--ok) 13%,transparent)}
.b-high{color:var(--warn);background:color-mix(in srgb,var(--warn) 16%,transparent)}
.b-outlier{color:var(--err);background:color-mix(in srgb,var(--err) 14%,transparent)}
table.btbl tbody tr.pick{cursor:pointer}
table.btbl tbody tr.pick:hover td{background:var(--surface-2)}
table.btbl tbody tr.on td{background:color-mix(in srgb,var(--accent-solid) 12%,transparent)}
.bfoot{padding-top:var(--sp-1);padding-bottom:var(--sp-2)}
@media (max-width:34rem){
 dialog.browse{width:calc(100vw - 1rem)}
 .btblwrap{overflow-x:auto}
}
/* Who the panel thinks you are. A pill rather than plain text: it is a fact about
   the session, not a heading, and it sits beside the two controls that act on the
   project. Elided rather than wrapped — an email address is long, and the topbar is
   nowrap, so an un-capped name would push the buttons off the edge. */
.who{display:inline-flex;align-items:center;gap:.35rem;font-size:.74rem;
 color:var(--muted);background:var(--surface-2);border:1px solid var(--border);
 border-radius:var(--pill);padding:.15rem .6rem;max-width:16rem;min-width:0}
.who b{font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
.who .wk{white-space:nowrap}
.who[hidden]{display:none}
@media(max-width:60rem){.who{max-width:10rem}.who .wk{display:none}}
@media(max-width:34rem){.who{display:none}}
/* Confirm-before-write. Same native <dialog> the browse table uses, for the same
   reasons — focus trap, backdrop and Esc are the platform's — and deliberately the
   same visual object, because both are "here is the data, decide". */
dialog.confirm{width:min(42rem,calc(100vw - 2rem));max-height:calc(100vh - 4rem);
 padding:0;border:1px solid var(--border-strong);border-radius:var(--radius-lg);
 background:var(--surface);color:var(--text);box-shadow:var(--shadow-md);
 overflow:hidden}
dialog.confirm::backdrop{background:rgb(0 0 0 / .45)}
dialog.confirm>*{padding:0 var(--sp-3)}
.cflist{max-height:min(50vh,22rem);overflow:auto;border-top:1px solid var(--border);
 padding:0}
table.cftbl{width:100%;border-collapse:separate;border-spacing:0;font-size:.8rem}
table.cftbl th{position:sticky;top:0;z-index:1;background:var(--surface-2);
 color:var(--muted);text-align:left;font-size:var(--t-label);text-transform:uppercase;
 letter-spacing:.05em;padding:var(--sp-1) var(--sp-2);white-space:nowrap;
 border-bottom:1px solid var(--border)}
table.cftbl td{padding:var(--sp-1) var(--sp-2);border-bottom:1px solid var(--border);
 vertical-align:top}
table.cftbl td.tgt{font-family:var(--mono);white-space:nowrap}
table.cftbl td.fld{color:var(--muted);white-space:nowrap}
/* Old on the left, new on the right, and the arrow between them is text — a glyph
   drawn in CSS would vanish in the copy of this dialog nobody can take. */
.cfv{font-family:var(--mono);font-size:.76rem;word-break:break-word}
.cfv.was{color:var(--muted);text-decoration:line-through;text-decoration-thickness:1px}
.cfv.unset{font-style:italic;text-decoration:none}
.cfarr{color:var(--muted);padding:0 .35rem}
.cffoot{display:flex;gap:var(--sp-1);align-items:center;flex-wrap:wrap;
 padding-top:var(--sp-2);padding-bottom:var(--sp-2)}
.cffoot .push{margin-left:auto}
/* A lock is a live fact about somebody else's run, so it is stated inside the
   dialog rather than only guessed at from the last page load. */
.cflock{margin:var(--sp-1) 0 0;font-size:.76rem}
@media (max-width:34rem){dialog.confirm{width:calc(100vw - 1rem)}
 .cflist{overflow-x:auto}}
/* one shared tooltip element, moved on hover */
.utip{position:fixed;z-index:60;pointer-events:none;background:var(--surface);
 border:1px solid var(--border-strong);border-radius:var(--radius);
 box-shadow:var(--shadow-md);padding:var(--sp-1) var(--sp-2);font-size:.74rem;
 max-width:18rem;color:var(--text)}
.utip.hidden{display:none}
.utip-h{font-weight:600;margin-bottom:var(--sp-0);word-break:break-word}
.utip-r{display:flex;align-items:center;gap:var(--sp-0);
 font-variant-numeric:tabular-nums;line-height:1.5}
.utip-r i{width:.55rem;height:.55rem;border-radius:2px;flex:0 0 auto}
.utip-k{color:var(--muted);flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
.utip-v{font-weight:600}
.utip-f{color:var(--muted);font-size:.68rem;margin-top:var(--sp-0);
 border-top:1px solid var(--border);padding-top:var(--sp-0)}
@media (max-width:34rem){
 .urow{grid-template-columns:1fr;gap:0}
 .urow .bar{display:none}
 .ufil .combo{flex:1 1 100%}
 /* A date input has an intrinsic width of about 9rem plus the picker glyph. Two of
    them, two labels and a select do not fit a 360px row, and `flex:0 0 auto` means
    they do not shrink either - so the pair takes a line of its own and each half
    takes half of it. Measured at 390px, which is where the report's own filter
    panel was found hanging off the left edge. */
 .udates{flex:1 1 100%}
 .ufil input[type=date]{flex:1 1 calc(50% - 3rem);min-width:0}
 .ufil .push{margin-left:0}
 /* And it stops pinning. Nine controls stacked at this width measure 311px, which
    on an 844px phone is a sticky bar owning 37% of the screen for the whole scroll
    - the same shape as the report's filter panel covering the table it filtered.
    Above the breakpoint the bar is two lines and worth pinning; here it is not. */
 .ufil{position:static}
}
/* ---- settings ------------------------------------------------------------
   Four cards over one file. The grouping is the whole point: the config is not a
   flat bag of keys, it is four decisions (where things are, what may be refused,
   how loud the nudge is, what a token costs), and a reader looking for one of
   them should not have to read the other three. */
.blurb{color:var(--muted);font-size:.8rem;margin:.15rem 0 .75rem;max-width:62ch}
/* Bottoms, not centres. A label that wraps to two lines is centred against
   single-line siblings and drags its input half a line down, so one long field name
   knocks a whole row out of alignment. */
#guards .row{align-items:end}
.sub2{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;
 color:var(--muted);font-weight:700;margin:1.25rem 0 .4rem}
.sub2 .lbl{gap:.35rem}
label.f.wide{flex:1 1 100%}
/* A checkbox and its words are one line, and the words are not a column header. */
label.f.cbf{flex-direction:row;align-items:center;gap:.4rem;flex:0 0 auto}
label.f.cbf input{margin:0}
/* Reachable from any of the four cards. A form this long with the Save at the
   bottom is a form people leave without saving. */
.savebar{position:sticky;bottom:0;z-index:var(--z-strip);display:flex;gap:.75rem;
 align-items:center;flex-wrap:wrap;margin:.75rem 0 0;padding:.75rem 1rem;
 background:color-mix(in srgb,var(--surface) 92%,transparent);
 backdrop-filter:blur(10px);border:1px solid var(--border);
 border-radius:var(--radius-lg);box-shadow:var(--shadow-sm)}
.savebar .findings-slot{flex:1 1 100%}
/* Defaults that are ACTIVE, drawn as what they are: real, and not yours yet. */
.ghost{display:flex;gap:.35rem;align-items:center;flex-wrap:wrap;margin-top:.4rem}
.chip.ghosted{border-style:dashed;color:var(--muted);background:transparent}
/* A value this browser's regex engine will not accept. Never green for the
   opposite case: Python's engine is the one that decides, on save. */
.chip.bad{border-color:var(--err);color:var(--err)}
input.bad{border-color:var(--err)}
.ferr{color:var(--err);font-size:.74rem;margin:-.1rem 0 .35rem}
.rule.rulehead{text-transform:uppercase;letter-spacing:.05em;font-size:.66rem;
 margin-bottom:.15rem}
@media(max-width:40rem){.rule.rulehead{display:none}}
.ptblwrap{border:1px solid var(--border);border-radius:var(--radius);
 overflow-x:auto;-webkit-overflow-scrolling:touch;max-height:24rem;overflow-y:auto}
table.ptbl{width:100%;border-collapse:separate;border-spacing:0;font-size:.8rem}
table.ptbl th{position:sticky;top:0;z-index:1;background:var(--surface-2);
 color:var(--muted);text-align:left;font-size:var(--t-label);text-transform:uppercase;
 letter-spacing:.05em;padding:.4rem .5rem;white-space:nowrap;
 border-bottom:1px solid var(--border)}
table.ptbl th.n,table.ptbl td.n{text-align:right}
table.ptbl td{padding:.25rem .5rem;border-bottom:1px solid var(--border);white-space:nowrap}
table.ptbl td input{width:6rem;padding:.2rem .4rem;font-size:.78rem;text-align:right;
 font-variant-numeric:tabular-nums}
table.ptbl tbody tr:last-child td{border-bottom:none}
/* Arriving from a link in another tab: say WHICH field you were sent to, briefly.
   Scrolling to it silently leaves the reader hunting for what changed. */
.flash{outline:2px solid var(--accent);outline-offset:3px;border-radius:var(--radius)}
@media (prefers-reduced-motion:no-preference){
 .flash{transition:outline-color var(--dur) var(--ease)}}
.tsk{border:1px solid var(--border);border-radius:var(--radius);padding:.5rem .75rem;background:var(--bg)}
.tsk .h{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap}
.dot{width:.6rem;height:.6rem;border-radius:50%;display:inline-block;background:var(--muted)}
.rule{display:grid;grid-template-columns:1fr 1fr 1.3fr auto;gap:.5rem;margin:.25rem 0}
@media(max-width:40rem){.rule{grid-template-columns:1fr}}
#toast{position:fixed;left:50%;bottom:1.3rem;transform:translateX(-50%);z-index:50;
 background:var(--surface);border:1px solid var(--border);box-shadow:var(--shadow-md);
 border-radius:var(--pill);padding:.5rem 1rem;font-size:.85rem;opacity:0;transition:opacity var(--dur);pointer-events:none}
#toast.show{opacity:1}#toast.err{border-color:var(--err);color:var(--err)}#toast.ok{border-color:var(--ok)}
#toast.warn{border-color:var(--warn);color:var(--warn)}
.findings{margin:.5rem 0 0;padding:.5rem .75rem;border-radius:var(--radius);font-size:.82rem}
.findings.err{background:color-mix(in srgb,var(--err) 12%,transparent);color:var(--err)}
.findings.warn{background:color-mix(in srgb,var(--warn) 14%,transparent);color:var(--warn)}
.findings.ok{background:color-mix(in srgb,var(--ok) 12%,transparent);color:var(--ok)}
/* Grouped findings. One manifest mistake repeated across 300 phases is ONE thing
   to fix, so it reads as one row with a count — not 300 rows of the same
   sentence. The raw list stays one click away. */
.fgrp{margin:var(--sp-1) 0 0;padding:0;list-style:none;display:grid;gap:var(--sp-0)}
.fgrp li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:var(--sp-1);
 align-items:baseline}
.fgrp .fn{font-variant-numeric:tabular-nums;font-weight:700;opacity:.85}
.fgrp .feg{opacity:.72;font-size:.94em;overflow-wrap:anywhere}
.fall{margin-top:var(--sp-1)}
.fall>summary{cursor:pointer;opacity:.8}
.fall ol{margin:var(--sp-1) 0 0;padding-left:1.4rem;max-height:16rem;overflow:auto;
 display:grid;gap:2px}
.src{font-size:.66rem}.hidden{display:none}
/* info hints on labels */
.lbl{display:inline-flex;align-items:center;gap:.25rem}
.hint{display:inline-flex;align-items:center;justify-content:center;width:1.02rem;height:1.02rem;border-radius:50%;
 border:1px solid var(--border-strong);color:var(--muted);font:italic 700 .62rem/1 var(--sans);cursor:help;
 position:relative;flex:0 0 auto;text-transform:none}
.hint:hover,.hint:focus{border-color:var(--accent);color:var(--accent);outline:none}
.hint::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + .4rem);z-index:60;width:17rem;max-width:72vw;
 background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:var(--radius);
 box-shadow:var(--shadow-md);padding:.5rem .5rem;font:400 .74rem/1.45 var(--sans);text-transform:none;letter-spacing:0;
 white-space:normal;display:none;pointer-events:none}
.hint:hover::after,.hint:focus::after{display:block}
/* Two fixes for one bug. A 17rem bubble anchored left overflows the viewport for
   any hint in the right half of a wide layout, and an absolutely-positioned box
   counts toward scrollable overflow even while hidden — so the page carried 34px
   of sideways scroll before anyone hovered anything. `visibility:hidden` was not
   enough for that; `display:none` is, at the cost of the fade, which is a fair
   trade for a tooltip that appears under the cursor anyway. And when it IS shown
   it flips to the right edge if it would not fit. The old guard
   (`overflow-x:hidden` under 48rem) hid the symptom, and only on phones. */
.hint.flip::after{left:auto;right:0}
/* custom autocomplete combobox (replaces native datalist) */
.combo{position:relative;flex:1 1 18rem}
.combo>input{width:100%}
.combo-menu{position:absolute;left:0;right:0;top:calc(100% + .25rem);z-index:40;background:var(--surface);
 border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow-md);max-height:15rem;overflow:auto;padding:.25rem}
.combo-it{display:flex;align-items:center;gap:.5rem;padding:.5rem .5rem;border-radius:6px;cursor:pointer}
.combo-it:hover,.combo-it.active{background:var(--surface-2)}
.combo-n{font-size:.82rem;flex:0 0 auto}
.combo-d{color:var(--muted);font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1 1 auto}
.chipwrap{display:flex;flex-direction:column;gap:.5rem;flex:1 1 auto}
.chips{display:flex;gap:.25rem;flex-wrap:wrap}
/* discovered building-blocks: subtabs + one table */
.subtabs{display:flex;gap:.25rem;margin:.5rem 0 .5rem;flex-wrap:wrap}
.subtab{cursor:pointer;font:inherit;font-size:.78rem;padding:.25rem .75rem;border-radius:var(--pill);
 border:1px solid var(--border);background:var(--bg);color:var(--muted);transition:all var(--dur) var(--ease)}
.subtab:hover{border-color:var(--border-strong)}
.subtab.on{background:var(--surface-2);color:var(--text);border-color:var(--border-strong)}
.regtblwrap{max-height:22rem;overflow:auto;border:1px solid var(--border);border-radius:var(--radius)}
table.regtbl{width:100%;border-collapse:separate;border-spacing:0;font-size:.82rem}
table.regtbl th{position:sticky;top:0;z-index:1;background:var(--surface-2);color:var(--muted);text-align:left;
 font-size:.66rem;text-transform:uppercase;letter-spacing:.05em;padding:.5rem .75rem;border-bottom:1px solid var(--border)}
table.regtbl td{padding:.5rem .75rem;border-bottom:1px solid var(--border);vertical-align:top}
table.regtbl tbody tr:hover td{background:var(--surface-2)}
table.regtbl td.d{color:var(--muted)}
/* status -> --st (reuses the theme-aware ok/warn/err/muted tokens) */
[data-status="done"],[data-status="fixed"]{--st:var(--ok)}
[data-status="in_progress"],[data-status="triaged"]{--st:var(--warn)}
[data-status="blocked"],[data-status="open"]{--st:var(--err)}
[data-status="pending"],[data-status="wontfix"]{--st:var(--muted)}
.st{display:inline-block;font-size:.66rem;font-weight:600;padding:.25rem .5em;border-radius:var(--pill);
 background:color-mix(in srgb,var(--st,var(--muted)) 15%,transparent);color:var(--st,var(--muted));
 border:1px solid color-mix(in srgb,var(--st,var(--muted)) 32%,transparent);white-space:nowrap}
/* composition: filter toolbar + one compact collapsible table */
.comptools{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin:.25rem 0 .5rem}
.comptools input[type=search]{flex:1 1 13rem;min-width:9rem;padding:.25rem .75rem}
.filtlbl{font-size:.72rem;color:var(--muted)}
.filt{cursor:pointer;font:inherit;font-size:.75rem;padding:.25rem .75rem;border-radius:var(--pill);
 border:1px solid var(--border);background:var(--bg);color:var(--muted);transition:all var(--dur) var(--ease)}
.filt:hover{border-color:var(--border-strong)}
.filt.on{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
/* State carried by more than hue, as in the report. */
.filt.on::before{content:"\2713\a0";font-weight:700}
.count{font-size:.73rem;color:var(--muted);font-variant-numeric:tabular-nums}
/* A wide data table scrolls inside its own box at EVERY width, not only on a
   phone. The old rule was scoped to 48rem because the page was a 64rem column
   that the table happened to fit; widening the shell exposed that the guard was
   tied to the viewport rather than to the table being wider than its container.
   Same rule the report follows: text wraps to the reader, data tables scroll. */
.comptblwrap{border:1px solid var(--border);border-radius:var(--radius);
 overflow-x:auto;-webkit-overflow-scrolling:touch}
table.comp{width:100%;border-collapse:separate;border-spacing:0;font-size:.85rem}
table.comp th,table.comp td{padding:.5rem .5rem;border-bottom:1px solid var(--border);text-align:left;vertical-align:middle}
table.comp thead th{position:sticky;top:0;z-index:1;background:var(--surface-2);color:var(--muted);
 font-size:.62rem;text-transform:uppercase;letter-spacing:.05em}
table.comp tbody tr:last-child td{border-bottom:none}
tr.phase{cursor:pointer}
tr.phase>td{background:var(--surface-2);border-top:1px solid var(--border-strong);
 border-left:3px solid var(--st,var(--muted))}
.phtd{display:flex;align-items:center;gap:.5rem}
tr.phase:hover>td{filter:brightness(1.05)}
.tri{display:inline-block;width:.9em;color:var(--muted);transition:transform var(--dur) var(--ease)}
.tri::before{content:"\25B6";font-size:.68em}
tr.phase.open .tri{transform:rotate(90deg)}
tr.task>td{background:var(--surface)}
tr.task:hover>td{background:var(--surface-2)}
tr.task>td.tid{font-family:var(--mono);color:var(--muted);font-size:.8em;padding-left:1.5rem;
 border-left:3px solid var(--st,var(--border))}
td.ttitle{max-width:22rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
td.tmodel input{width:6.5rem;padding:.25rem .5rem;font-size:.8rem}
td.tskills{min-width:15rem}
.comp-review{display:flex;align-items:center;gap:.25rem;margin-left:auto;font-weight:400;color:var(--muted);font-size:.72rem}
.comp-review input{width:8rem;padding:.25rem .5rem;font-size:.78rem}
.comp .chipwrap{flex-direction:row;flex-wrap:wrap;align-items:center;gap:.25rem}
.comp .chips{gap:.25rem}
.topbtns{display:flex;gap:var(--sp-1);align-items:center;flex-shrink:0}
.comp .combo{flex:1 1 8rem;min-width:7rem}
/* overview: summary strips, phase rows, ready-now
   The strips are a legend AND the filter — one row of pills that says how the work
   is distributed and scopes the list below when you press one. Two separate
   affordances for the same eight numbers is how a reader ends up believing the
   legend and the list disagree. */
.ovstrip{display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;margin:.35rem 0 .1rem}
.ovstrip .ovlbl{font-size:.72rem;color:var(--muted);flex:0 0 auto;min-width:3.2rem}
.ovpill{cursor:pointer;font:inherit;display:inline-flex;align-items:center;gap:.4em;
 font-size:.74rem;padding:.28rem .7em;border-radius:var(--pill);
 background:color-mix(in srgb,var(--st,var(--muted)) 12%,transparent);
 color:var(--st,var(--muted));
 border:1px solid color-mix(in srgb,var(--st,var(--muted)) 30%,transparent);
 transition:all var(--dur) var(--ease)}
.ovpill:hover{border-color:var(--st,var(--border-strong))}
.ovpill:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.ovpill[aria-pressed=true]{background:color-mix(in srgb,var(--st,var(--muted)) 26%,transparent);
 border-color:var(--st,var(--muted));font-weight:640}
/* Selected state carried by more than hue, as in the report and the composition
   filters — in greyscale, in forced-colours and on paper the fill says nothing. */
.ovpill[aria-pressed=true]::before{content:"\2713\a0";font-weight:700}
.ovpill b{font-variant-numeric:tabular-nums;font-weight:640}
/* a severity cut, not a status — it carries no data-status, so it sets --st itself */
.ovpill.hi{--st:var(--err)}
.ovtools{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin:.6rem 0 .4rem}
.ovtools input[type=search]{flex:1 1 13rem;min-width:9rem;padding:.25rem .75rem}
.ovtools select{font-size:.8rem;padding:.25rem .5rem}
.ovtools label.inl{display:inline-flex;align-items:center;gap:.35rem;font-size:.78rem;color:var(--muted)}
.ovgrp{display:flex;align-items:baseline;gap:.5rem;margin:.9rem 0 .1rem;
 padding-bottom:.25rem;border-bottom:1px solid var(--border)}
.ovgrp .gname{font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--accent)}
/* A row is one control: it opens this phase in Composition. A <button> rather than
   a div with a click handler, so it is reachable by keyboard and announced as
   something you can press without a hand-written role/tabindex/keydown trio. */
.ovrow{display:flex;gap:.75rem;flex-wrap:wrap;align-items:center;width:100%;text-align:left;
 font:inherit;color:var(--text);cursor:pointer;background:none;border:1px solid transparent;
 border-left:3px solid var(--st,var(--border));border-radius:var(--radius);
 padding:.4rem .5rem;margin:.15rem 0;transition:background var(--dur) var(--ease)}
.ovrow:hover{background:var(--surface-2)}
.ovrow:focus-visible{outline:2px solid var(--ring);outline-offset:1px}
.ovrow .pid{font-family:var(--mono);font-size:.8rem;color:var(--muted);flex:0 0 3rem}
.ovrow .ptitle{flex:1 1 12rem;min-width:8rem}
.ovout{flex:1 1 100%;font-size:.76rem;color:var(--muted);margin:.1rem 0 0 3.75rem;
 max-width:80ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ovmatch{font-size:.72rem;color:var(--muted);font-variant-numeric:tabular-nums}
.ovempty{color:var(--muted);font-size:.85rem;padding:.6rem .2rem}
/* ready-now: the one thing you can act on without reading anything else */
.rdy{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;padding:.35rem .2rem;
 border-bottom:1px solid var(--border)}
.rdy:last-child{border-bottom:none}
.rdy .rcmd{font-family:var(--mono);font-size:.78rem;background:var(--surface-2);
 border:1px solid var(--border);border-radius:var(--radius);padding:.15rem .45rem;
 white-space:nowrap}
.rdy .rt{flex:1 1 12rem;min-width:8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sev{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}
.sev.high{color:var(--err)}
@media(max-width:48rem){
 .ovout{margin-left:0}
 .ovrow .ptitle{flex:1 1 100%}
}

/* ---- policy switchboard ---------------------------------------------------
   A wide table by construction: one column per area, and an area can be added
   without asking this stylesheet. So it scrolls INSIDE its own frame — the
   document never scrolls sideways, which on a phone is the difference between a
   table you can read and a page that slides out from under you. */
.poltblwrap{border:1px solid var(--border);border-radius:var(--radius);
 overflow:auto;max-height:34rem;margin:.4rem 0}
table.poltbl{width:100%;border-collapse:separate;border-spacing:0;font-size:.8rem}
table.poltbl th{position:sticky;top:0;z-index:1;background:var(--surface-2);
 text-align:left;font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;
 color:var(--muted);font-weight:700;padding:.35rem .5rem;
 border-bottom:1px solid var(--border);white-space:nowrap}
table.poltbl th.ar{color:var(--accent)}
table.poltbl th.ar .mut{display:block;font-size:.62rem;letter-spacing:.02em;
 text-transform:none;font-weight:600}
table.poltbl th.ar.dormant{color:var(--muted)}
table.poltbl td{padding:.3rem .5rem;border-bottom:1px solid var(--border);
 vertical-align:top}
table.poltbl tbody tr:last-child td{border-bottom:none}
table.poltbl td.nm{font-family:var(--mono);font-size:.76rem;
 max-width:22rem;overflow-wrap:anywhere}
/* A NAME may break anywhere — some of them are long and this column has a width.
   A badge is a word, and `overflow-wrap:anywhere` inherits, so `required` was
   being drawn as "req" over "uired" beside audit's own row. */
table.poltbl td.nm .badge{white-space:nowrap;overflow-wrap:normal}
table.poltbl td.pend{background:color-mix(in srgb,var(--accent-solid) 10%,transparent)}
select.prule{font:inherit;font-size:.74rem;padding:.15rem .3rem;
 border:1px solid var(--border);border-radius:var(--radius);
 background:var(--surface);color:var(--text)}
select.prule:disabled{opacity:.55;cursor:not-allowed}
select.prule[data-set=deny]{border-color:var(--err);color:var(--err)}
select.prule[data-set=allow]{border-color:var(--ok);color:var(--ok)}
/* The verdict is a claim, and the basis under it is what makes the claim
   checkable — the same rule the report's routing advice and the lock verdict
   follow. It is never colour alone: the word says it too. */
.pv{display:inline-flex;align-items:center;gap:.3em;font-size:.72rem;font-weight:700;
 padding:.15rem .5em;border-radius:var(--pill);white-space:nowrap;
 background:color-mix(in srgb,var(--pvc) 14%,transparent);color:var(--pvc);
 border:1px solid color-mix(in srgb,var(--pvc) 30%,transparent)}
.pv.allow{--pvc:var(--ok)}
.pv.violation{--pvc:var(--err)}
.pbasis{display:block;color:var(--muted);font-size:.7rem;line-height:1.45;
 max-width:44ch;margin-top:.15rem}
.badge.req{background:color-mix(in srgb,var(--accent) 16%,transparent);
 color:var(--accent);border-color:transparent}
.badge.stand{background:color-mix(in srgb,var(--warn) 16%,transparent);
 color:var(--warn);border-color:transparent}
.badge.pend{background:color-mix(in srgb,var(--accent-solid) 18%,transparent);
 color:var(--accent);border-color:transparent}
table.polrules{width:100%;border-collapse:separate;border-spacing:0;font-size:.78rem}
table.polrules th{text-align:left;font-size:.66rem;text-transform:uppercase;
 letter-spacing:.06em;color:var(--muted);font-weight:700;padding:.3rem .5rem;
 border-bottom:1px solid var(--border)}
table.polrules td{padding:.28rem .5rem;border-bottom:1px solid var(--border)}
table.polrules tbody tr:last-child td{border-bottom:none}
table.polrules td.pat{font-family:var(--mono);font-size:.76rem}
table.polrules td.lst{font-weight:700;font-size:.7rem;text-transform:uppercase;
 letter-spacing:.04em}
table.polrules td.lst[data-list=deny]{color:var(--err)}
table.polrules td.lst[data-list=allow]{color:var(--ok)}
.poladd{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin:.5rem 0 0}
.poladd input{flex:1 1 14rem;min-width:8rem;padding:.25rem .5rem}
.poladd select{font-size:.8rem;padding:.25rem .5rem}
/* The four limits. Shut by default because they are read once and remembered,
   open-able because a switchboard that never states them is selling enforcement
   it does not have. */
.polhonest{margin:.6rem 0 0;font-size:.82rem}
.polhonest summary{cursor:pointer;color:var(--muted);font-size:.78rem}
.polhonest ol{margin:.5rem 0 0;padding-left:1.2rem;color:var(--muted);
 font-size:.78rem;line-height:1.55;max-width:76ch}
.polhonest b{color:var(--text)}
@media(max-width:48rem){
 .pbasis{max-width:none}
 .poltblwrap{max-height:none}
}

</style></head><body>
<div class=top>
 <div><h1>audit · control panel</h1><p class=sub id=proj></p></div>
 <div class=topbtns>
  <span class=who id=who hidden></span>
  <button class="btn small" id=report title="render the standalone HTML report (it carries Save-as-PDF)">Export report</button>
  <button class="btn small" id=theme title="light/dark">☾</button>
 </div>
</div>
<div class=shell>
<nav class=tabs aria-label="Panel sections">
 <p class=navttl>Sections</p>
 <button class="tab on" data-t=guards aria-current="true">Settings</button>
 <button class="tab" data-t=comp>Composition</button>
 <button class="tab" data-t=over>Overview</button>
 <button class="tab" data-t=usage>Usage</button>
 <button class="tab" data-t=policy>Policy</button>
</nav>
<main class=view>
<div id=guards></div>
<div id=comp class=hidden></div>
<div id=over class=hidden></div>
<div id=usage class=hidden></div>
<div id=policy class=hidden></div>
</main>
</div>
<div id=toast role=status aria-live=polite></div>
<script>
const TOKEN=__AUDIT_TOKEN__, PROJECT=__AUDIT_PROJECT__;
const $=(s,r=document)=>r.querySelector(s), el=(t,a={},...k)=>{const e=document.createElement(t);
 for(const[n,v]of Object.entries(a)){if(n==='class')e.className=v;else if(n==='html')e.innerHTML=v;
 else if(n.startsWith('on'))e.addEventListener(n.slice(2),v);else if(v!=null)e.setAttribute(n,v);}
 for(const c of k.flat()){if(c!=null)e.append(c.nodeType?c:document.createTextNode(c));}return e;};
const api=async(m,p,b)=>{const r=await fetch(p,{method:m,headers:{'X-Audit-Token':TOKEN,
 'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return r.json();};
// For navigations rather than fetches: window.open cannot set a header, so the
// token has to ride in the query string (the guard accepts either).
const url=p=>p+'?t='+encodeURIComponent(TOKEN);
let STATE=null, REG={skills:[],agents:[],mcp:[]};
// Middle ellipsis, not a tail cut: the head says which machine/checkout this is
// and the tail says which project, and a plain truncation throws away whichever
// end the CSS happens to reach first. The full path stays in the tooltip, so
// nothing is lost — it is just no longer allowed to set the header's height.
function midElide(s,max){if(!s||s.length<=max)return s||'';
 const keep=max-1,head=Math.ceil(keep*0.38);return s.slice(0,head)+'…'+s.slice(s.length-(keep-head));}
$('#proj').textContent=midElide(PROJECT,56);
$('#proj').title=PROJECT;
// theme
const root=document.documentElement, TK='audit-panel-theme';
try{const s=localStorage.getItem(TK);if(s)root.setAttribute('data-theme',s);}catch(e){}
const isDark=()=>{const t=root.getAttribute('data-theme');return t?t==='dark':matchMedia('(prefers-color-scheme:dark)').matches;};
const paint=()=>$('#theme').textContent=isDark()?'☀':'☾';paint();
$('#theme').onclick=()=>{const n=isDark()?'light':'dark';root.setAttribute('data-theme',n);
 try{localStorage.setItem(TK,n);}catch(e){}paint();};
// Render the standalone report and open it. Opened through THIS origin (/report):
// a browser will not follow a file:// link from an http:// page, so handing over a
// filesystem path would give you a button that silently does nothing. The report
// itself already carries Save-as-PDF and a Markdown twin, so there is no PDF
// machinery here.
$('#report').onclick=async e=>{const b=e.currentTarget;
 const was=b.textContent;b.disabled=true;b.textContent='Rendering…';
 // Opened NOW, inside the click, and navigated once the render returns. Called
 // after the await it is no longer a user gesture, and a render that takes a
 // second or two is exactly when a browser silently blocks the popup — the
 // button then reports success and nothing appears.
 let win=null; try{win=window.open('','_blank','noopener');}catch(_e){}
 try{const r=await api('POST','/api/report',{});
  if(!r.ok){if(win)win.close();toast((r.findings||['render failed'])[0],'err');return;}
  if(!r.exists){if(win)win.close();
   toast('rendered, but no HTML report was written — check /audit:report','err');return;}
  toast('wrote '+(r.files||[]).length+' file(s)','ok');
  if(win){win.location=url('/report');}
  else{
   // Blocked anyway: leave a link rather than a button that did nothing.
   const a=$('#replink')||el('a',{id:'replink',class:'lnk',target:'_blank',rel:'noopener'},'open report ↗');
   a.href=url('/report');if(!a.parentNode)b.parentNode.insertBefore(a,b.nextSibling);}
 }catch(err){if(win)win.close();toast('render failed: '+err,'err');}
 finally{b.disabled=false;b.textContent=was;}};
// tabs
// Views are addressable, and each remembers where you were in it. Every switch
// used to slam the page back to the top and the URL never changed: a 50-phase
// Composition table lost your place the moment you glanced at Usage, and there
// was no way to link anyone to a tab — a reload always landed on Guards.
// The manifest's vocabulary is machine-facing: `in_progress` sorts, compares and
// survives serialization. It is not a thing to show anyone, and it was leaking
// into every status pill, every filter button and every phase row. The machine
// value stays in data-status (the CSS themes off it, the filters compare it);
// only the text changes.
const LABELS=__LABELS__;
const label=v=>LABELS[v]||(v?String(v).replace(/[_-]+/g,' ').replace(/^./,c=>c.toUpperCase()):'—');
const TABS=['guards','comp','over','usage','policy'],SCROLL={};
let CURTAB=null;
function showTab(t,push){
 if(!TABS.includes(t))t='guards';
 if(CURTAB)SCROLL[CURTAB]=window.scrollY;
 CURTAB=t;
 document.querySelectorAll('.tab').forEach(x=>{const on=x.dataset.t===t;x.classList.toggle('on',on);
  // Colour alone does not say which view you are in — a screen reader gets nothing
  // from a background change, and these four are exclusive views, not filters.
  if(on)x.setAttribute('aria-current','true');else x.removeAttribute('aria-current');});
 for(const id of TABS)$('#'+id).classList.toggle('hidden',id!==t);
 if(push!==false){const h='#/'+t;if(location.hash!==h)history.replaceState(null,'',h);}
 try{localStorage.setItem('audit-panel-tab',t);}catch(e){}
 // After the browser has laid the view out, not before it.
 requestAnimationFrame(()=>window.scrollTo({top:SCROLL[t]||0,behavior:'auto'}));}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>showTab(t.dataset.t));
// Measured, not assumed. Below the shell breakpoint the five views become one
// horizontal strip, and on a phone the last of them is off the right-hand edge
// with nothing to suggest it exists.
function tabsOverflow(){const n=document.querySelector('.tabs');
 if(n)n.classList.toggle('scrolls',n.scrollWidth>n.clientWidth+1);}
addEventListener('resize',tabsOverflow);tabsOverflow();
addEventListener('hashchange',()=>{const t=(location.hash||'').replace(/^#\/?/,'');
 if(TABS.includes(t)&&t!==CURTAB)showTab(t,false);});
function initialTab(){const h=(location.hash||'').replace(/^#\/?/,'');
 if(TABS.includes(h))return h;
 try{const s=localStorage.getItem('audit-panel-tab');if(TABS.includes(s))return s;}catch(e){}
 return 'guards';}
function toast(msg,kind){const t=$('#toast');t.textContent=msg;t.className='show '+(kind||'');
 setTimeout(()=>t.className=t.className.replace('show','').trim(),2600);}
function findingsBox(res){const box=el('div');
 if(res.findings&&res.findings.length)box.append(el('div',{class:'findings err'},'✗ '+res.findings.join(' · ')));
 if(res.warnings&&res.warnings.length)box.append(el('div',{class:'findings warn'},'! '+res.warnings.join(' · ')));
 if(res.ok&&!(res.warnings&&res.warnings.length))box.append(el('div',{class:'findings ok'},'✓ saved'));
 return box;}
// ---------- who is writing, what exactly, and whether it was recorded ----------
// Three questions the panel could not answer until now, and they are one flow: a
// save wrote whatever the form happened to hold, said "manifest saved", and left
// no trace of who did it or what changed. So: the topbar names you, Save shows the
// exact rows before it writes anything, the server echoes back what it really
// applied, and the journal (when this install has one) keeps the record.

// The name comes from the server, resolved by usage_ledger.resolve_author — the
// same function and the same usage.authorMode that decide the `author` column in
// the token ledger. That is what makes the Usage tab's "my spend" chip able to
// filter on it: two ways of naming the same person would produce a filter that
// silently matches nothing.
function renderViewer(){
 const v=(STATE&&STATE.viewer)||{},w=$('#who');
 if(!w)return;
 w.hidden=false;w.textContent='';w.append(el('span',{class:'wk'},'viewing as'));
 if(v.author){
  w.append(el('b',{title:v.author},v.author));
  w.title='Resolved from git config in '+(v.mode||'email')+' mode (usage.authorMode). '
   +'This is the name written into the token ledger, so Usage → my spend filters on '
   +'exactly this string.';
  return;}
 // `none` is a decision this project made, not a failure to find you — and it is
 // the reason the ledger has no author column to filter on either. Anything else
 // means the resolver could not answer, which is worth the same link.
 w.append(settingsLink(v.mode==='none'?'not recorded':'unknown','usage.authorMode'));
 w.title=v.mode==='none'
  ?'usage.authorMode is "none": this project records no author, here or in the '
   +'token ledger.'
  :'Could not resolve a name from git config or the environment.';}

// A re-render replaces a view's children but never the view element itself, so a
// delegated listener added per render would stack up one more copy on every save.
// One controller per view, aborted at the top of that view's own wiring.
const VIEWAC={};
function onViewEdit(id,fn){
 if(VIEWAC[id])VIEWAC[id].abort();
 VIEWAC[id]=new AbortController();
 const opt={signal:VIEWAC[id].signal},run=()=>requestAnimationFrame(fn);
 ['input','change','click'].forEach(e=>$('#'+id).addEventListener(e,run,opt));
 fn();}

// Unsaved edits, registered per surface rather than tracked with a boolean. A
// boolean answers "is something dirty"; three callers need the ROWS — the confirm
// dialog lists them, Discard says how many are about to be lost, and beforeunload
// only earns the right to interrupt a close if there really are some.
const EDITS={guards:null,comp:null,policy:null};
function editRows(k){try{return (EDITS[k]?EDITS[k]():[])||[];}catch(e){return[];}}
function dirtyRows(){return Object.keys(EDITS).reduce((a,k)=>a.concat(editRows(k)),[]);}
addEventListener('beforeunload',ev=>{
 if(!dirtyRows().length)return;              // never interrupt a clean close
 ev.preventDefault();ev.returnValue='';return '';});

// --- change rows: {target, field, from, to} -------------------------------------
// The same shape the server echoes back as `applied`, computed here from the form
// and there from the file. Values are compared through JSON so a skills list is
// compared by content, and undefined and null are the one thing they mean here:
// "no value".
const cfNorm=v=>v===undefined?null:v;
const cfSame=(a,b)=>JSON.stringify(cfNorm(a))===JSON.stringify(cfNorm(b));
const cfRow=(target,field,from,to)=>({target,field,from:cfNorm(from),to:cfNorm(to)});
// Field order matches the server's (_META_FORM_KEYS, then phases, then tasks by
// _TASK_KEYS) so the dialog and the echo read as the same list, not two lists.
// FORM keys, not every writable meta key: `meta.areas` is writable through
// /api/areas and has no control here, so computing a row for it would be the
// dialog describing an edit this form cannot make.
function compChanges(patch){
 const comp=STATE.composition||{meta:{},phases:[],tasks:[]},rows=[];
 for(const k of ['reviewSkill','buildCommands'])
  if(patch.meta&&(k in patch.meta)&&!cfSame(comp.meta[k],patch.meta[k]))
   rows.push(cfRow('meta',k,comp.meta[k],patch.meta[k]));
 const byP={};(comp.phases||[]).forEach(p=>{byP[p.id]=p;});
 Object.keys(patch.phases||{}).sort().forEach(pid=>{
  const p=byP[pid],pv=patch.phases[pid]||{};
  if(!p||!('reviewModel' in pv))return;
  if(!cfSame(p.reviewModel,pv.reviewModel))
   rows.push(cfRow(pid,'review model',p.reviewModel,pv.reviewModel));});
 const byT={};(comp.tasks||[]).forEach(t=>{byT[t.id]=t;});
 Object.keys(patch.tasks||{}).sort().forEach(tid=>{
  const t=byT[tid],tv=patch.tasks[tid]||{};
  if(!t)return;
  ['model','skills'].forEach(k=>{if(!(k in tv))return;
   if(!cfSame(t[k],tv[k]))rows.push(cfRow(tid,k,t[k],tv[k]));});});
 return rows;}
// Dotted leaf paths, matching _flat_paths in this file: a non-empty object is a
// branch, everything else is a leaf. "usage.bands.highUSD changed" is a sentence
// somebody can check; "usage changed" is not.
function cfFlat(o,pre,out){out=out||{};
 if(o&&typeof o==='object'&&!Array.isArray(o))for(const k of Object.keys(o)){
  const p=pre?pre+'.'+k:k,v=o[k];
  if(v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length)cfFlat(v,p,out);
  else out[p]=v;}
 return out;}
function configChanges(cfg){
 const a=cfFlat(STATE.config||{}),b=cfFlat(cfg||{}),rows=[];
 [...new Set([...Object.keys(a),...Object.keys(b)])].sort().forEach(p=>{
  const ina=(p in a),inb=(p in b);
  // Presence as well as value: deleting a key is how "use the default" is
  // written, and a key whose value was already null would otherwise vanish.
  if(ina===inb&&cfSame(a[p],b[p]))return;
  rows.push(cfRow('config',p,ina?a[p]:null,inb?b[p]:null));});
 return rows;}

// --- the confirm dialog ---------------------------------------------------------
let CFDLG=null;
// Absent, empty-list and empty-string are three different values and the dialog
// says so. Collapsing them into one "not set" made a real change read as a no-op —
// "not set → not set" — which is precisely the row a reader would skim past.
function cfVal(v,cls){
 const none=v===null||v===undefined;
 const empty=none||v===''||(Array.isArray(v)&&!v.length);
 return el('span',{class:'cfv '+cls+(empty?' unset':'')},
   none?'not set'
    :(Array.isArray(v)&&!v.length?'(empty list)'
      :(v===''?'(empty text)'
        :(typeof v==='object'?JSON.stringify(v):String(v)))));}
// Which phases a change list touches, so the lock notice can be about the phases
// you are actually writing rather than about the manifest in general. A task id is
// mapped through the composition view rather than sliced out of the string: task
// ids are the plan's to shape, not this file's to parse.
function cfTouched(rows){
 const byT={};((STATE.composition||{}).tasks||[]).forEach(t=>{byT[t.id]=t.phaseId;});
 const s=new Set();
 rows.forEach(r=>{if(r.target==='meta'||r.target==='config')return;
  s.add(byT[r.target]||r.target);});
 return [...s];}
// Live, from the 5s poll — not from the page-load snapshot. A dialog that opens to
// say "nothing is running" because nothing was running when the tab loaded is
// exactly the reassurance this flow must not give.
function cfLock(rows,scope){
 const rs=RUNSTATUS||(STATE||{}).runStatus||{index:null,phases:{}};
 const idx=rs.index&&rs.index.live!==false;
 const livePhases=Object.keys(rs.phases||{}).filter(pid=>{
  const l=(rs.phases[pid]||{}).lock;return l&&l.live!==false;});
 if(idx)return{kind:'warn',text:'An /audit command holds the manifest lock right '
  +'now. This write will be refused while it does — nothing here is lost if it is.'};
 if(scope==='comp'){
  const hit=cfTouched(rows).filter(p=>livePhases.includes(p));
  if(hit.length)return{kind:'warn',text:'Running elsewhere right now: '+hit.join(', ')
   +'. A phase that is being worked cannot be edited here until that run finishes, '
   +'so this write will be refused.'};}
 if(livePhases.length)return{kind:'ok',text:'Running elsewhere: '+livePhases.join(', ')
  +' — none of them touched by these changes.'};
 return null;}
/**
 * Show the exact rows and wait for an answer. Resolves true only on the primary
 * button; Esc, the backdrop, the × and Cancel all resolve false, which is the
 * point of using a native <dialog> — the focus trap, the backdrop and Esc are the
 * platform's rather than three hand-written listeners that each forget one case.
 */
function confirmChanges(o){
 return new Promise(resolve=>{
  if(!CFDLG){CFDLG=el('dialog',{class:'confirm'});
   // Clicking the backdrop is the same intent as Esc. The dialog element fills the
   // viewport, so a click whose target IS the dialog landed outside the panel.
   CFDLG.addEventListener('click',ev=>{if(ev.target===CFDLG)CFDLG.close();});
   document.body.append(CFDLG);}
  const d=CFDLG;let done=false;
  const settle=v=>{if(done)return;done=true;resolve(v);};
  d.addEventListener('close',()=>settle(false),{once:true});
  d.textContent='';
  d.append(el('div',{class:'bhead'},el('h2',{},o.title),
    el('button',{class:'bx','aria-label':'close',type:'button',
      onclick:()=>d.close()},'×')));
  const tb=el('tbody');
  o.rows.forEach(r=>tb.append(el('tr',{'data-cfrow':r.target+' '+r.field},
    el('td',{class:'tgt'},r.target),el('td',{class:'fld'},r.field),
    el('td',{},cfVal(r.from,'was'),el('span',{class:'cfarr'},'→'),
      cfVal(r.to,'now')))));
  d.append(el('div',{class:'cflist'},el('table',{class:'cftbl'},
    el('thead',{},el('tr',{},el('th',{},'what'),el('th',{},'field'),
      el('th',{},'change'))),tb)));
  const lk=o.lock===false?null:cfLock(o.rows,o.scope);
  if(lk)d.append(el('div',{class:'cflock'},
    el('div',{class:'findings '+lk.kind},lk.text)));
  const cancel=el('button',{class:'btn small push',type:'button',
    'data-cfcancel':'1',onclick:()=>d.close()},'Cancel');
  const go=el('button',{class:'btn primary',type:'button','data-cfgo':'1',
    onclick:()=>{settle(true);d.close();}},o.verb);
  // The identity is repeated here, at the moment of the write, and not only in the
  // topbar: below 34rem the topbar pill is dropped for want of room, and "who is
  // this being recorded as" is a question that matters most on the screen where
  // there is least room to answer it. Not on the Discard dialog — nothing is
  // written there, so a name would be answering a question nobody asked.
  const who=((STATE||{}).viewer||{}).author;
  d.append(el('div',{class:'cffoot'},
    el('span',{class:'mut small','data-cfwho':who&&!o.danger?'1':null},
      (who&&!o.danger?'as '+who+' · ':'')+(o.note||'')),cancel,go));
  d.showModal();
  // A destructive primary must not be one Enter away from a keyboard that opened
  // the dialog by pressing Enter on a button.
  (o.danger?cancel:go).focus();});}

// --- what came back -------------------------------------------------------------
// The server recomputes the change list against the document it is about to write
// and echoes it as `applied`. Comparing it with what the dialog showed is the only
// way this flow tells "your save landed" apart from "your save landed on a
// manifest that is no longer the one you were reading" — a second tab, or an
// /audit run, having moved it in between. Without the comparison a confirm dialog
// makes that case WORSE: it adds a screenful of reassurance about stale values.
function appliedDiff(rows,res){
 if(!res||!res.ok||!Array.isArray(res.applied))return null;
 const key=r=>JSON.stringify([r.target,r.field,cfNorm(r.from),cfNorm(r.to)]);
 const mine=new Set(rows.map(key)),theirs=new Set(res.applied.map(key));
 const missing=[...mine].filter(k=>!theirs.has(k)).length;
 const extra=[...theirs].filter(k=>!mine.has(k)).length;
 return (missing||extra)?{missing,extra,shown:rows.length,
   applied:res.applied.length}:null;}
// One sentence for what happened to your changes: how many landed, and whether
// there is a record of it. "not logged" is said only when a journal exists and
// refused the row — on an install with no journal at all the clause is left off
// rather than reporting the absence of a feature as a failure of a save.
function saveOutcome(res,rows,what,slot){
 if(!res||!res.ok){
  toast(res&&res.locked?(what+' is locked — nothing was written')
    :('rejected — nothing was written'),'err');
  return null;}
 if(res.unchanged){toast('nothing to save — no values changed');return null;}
 const n=(res.applied||[]).length;
 const diff=appliedDiff(rows,res);
 const log=res.journaled?' · logged'
   :(res.journaledWhy==='failed'?' · NOT logged':'');
 toast('Saved · '+n+' change'+(n===1?'':'s')+log,diff?'warn':'ok');
 if(diff&&slot)slot.append(el('div',{class:'findings warn','data-cfdiff':'1'},
   'Saved, but not exactly what the dialog listed: '+diff.applied+' of the '
   +diff.shown+' change(s) shown were applied'
   +(diff.extra?(', and '+diff.extra+' other change(s) were'):'')
   +'. The file moved between opening this view and saving — reload the panel to '
   +'see what it holds now.'));
 return diff;}

async function boot(){STATE=await api('GET','/api/state');REG=await api('GET','/api/registry');
 USAGE=await api('GET','/api/usage').catch(()=>null);BANDS=null;
 POLICY=await api('GET','/api/policy').catch(()=>null);PDRAFT=pClone(POLICY&&POLICY.stored);
 renderViewer();renderSettings();renderComp();renderOver();renderUsage();renderPolicy();
 // Restored last, once every view has content to scroll to.
 showTab(initialTab());
 RUNSTATUS=STATE.runStatus||null;startRunPoll();}
// ---------- shared: info hints + autocomplete ----------
// The help text, the form's shape and the enum choices all arrive from Python —
// see FIELD_HELP / SETTINGS_GROUPS / _cfg_enums in this file. They used to be a JS
// literal here, which is how the form came to cover only part of the config while
// nothing said so. HELP is keyed by dotted config path; MDESC covers the manifest
// levers the Composition tab edits, which are not config paths.
const SETTINGS=__SETTINGS__, HELP=__FIELD_HELP__, MDESC=__COMP_HELP__, ENUMS=__CFG_ENUMS__;
function hint(t){if(!t)return null;
 const h=el('span',{class:'hint',tabindex:'0','data-tip':t},'i');
 // Measured at open time, not guessed from a breakpoint: whether the bubble fits
 // depends on where this particular hint sits, which CSS cannot ask.
 const place=()=>{const r=h.getBoundingClientRect();
  h.classList.toggle('flip',r.left+272>document.documentElement.clientWidth-8);};
 h.addEventListener('mouseenter',place);h.addEventListener('focus',place);
 return h;}
function flabel(text,tip){return el('span',{class:'lbl'},text,hint(tip));}
function h2h(text,tip){return el('h2',{},text,hint(tip));}
// Heading in the reader's words, with the JSON key beside it for whoever is
// editing .claude/audit.config.json by hand. Both audiences are real and they
// want different strings: "guardEdits.tokenVars" tells you nothing about what the
// setting DOES, and "Secrets never written to logs" cannot be typed into a file.
// The key keeps its own case on purpose — h2 is uppercased, and an uppercased
// camelCase key is not merely shouted, it is WRONG: config keys are
// case-sensitive, so copying it out of here would produce a setting that silently
// does nothing.
function klabel(text,key,tip){return el('span',{class:'lbl'},text,el('code',{class:'k2'},key),hint(tip));}
// A custom autocomplete: menu opens directly under the input, limited height,
// clear items (name + source + description), keyboard + click select.
function comboWrap(inp,itemsFn,onChoose,onEnterFree){
 const wrap=el('div',{class:'combo'}),menu=el('div',{class:'combo-menu hidden'});
 let active=-1,shown=[];
 const close=()=>{menu.classList.add('hidden');active=-1;};
 const render=()=>{const q=inp.value.trim().toLowerCase();
  shown=itemsFn().filter(it=>it.name.toLowerCase().includes(q)).slice(0,60);
  menu.textContent='';
  if(!shown.length){close();return;}
  shown.forEach((it,i)=>menu.append(el('div',{class:'combo-it'+(i===active?' active':''),
    onmousedown:e=>{e.preventDefault();onChoose(it.name,close);}},
    el('span',{class:'combo-n mono'},it.name),
    it.source?el('span',{class:'src badge'},it.source):null,
    it.description?el('span',{class:'combo-d'},it.description):null)));
  menu.classList.remove('hidden');
  const a=menu.querySelector('.combo-it.active');if(a)a.scrollIntoView({block:'nearest'});};
 inp.setAttribute('autocomplete','off');
 inp.addEventListener('focus',render);
 inp.addEventListener('input',()=>{active=-1;render();});
 inp.addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'){e.preventDefault();active=Math.min(active+1,shown.length-1);render();}
  else if(e.key==='ArrowUp'){e.preventDefault();active=Math.max(active-1,0);render();}
  else if(e.key==='Enter'){if(active>=0){e.preventDefault();onChoose(shown[active].name,close);}
   else if(onEnterFree&&inp.value.trim()){e.preventDefault();onEnterFree(inp.value.trim(),close);}}
  else if(e.key==='Escape'){close();}});
 inp.addEventListener('blur',()=>setTimeout(close,150));
 wrap.append(inp,menu);return wrap;}

// ---------- Settings ----------
// The view id stays `guards`: it is the hash route (#/guards), the screenshot name
// and what several selftests pin. An internal id is an address, not a description —
// renaming it would break every link anyone already has for the sake of a word only
// this file ever sees.
function listEditor(getArr,setArr,ph,validate){const wrap=el('div',{class:'pill-in'});
 const draw=()=>{wrap.textContent='';(getArr()||[]).forEach((v,i)=>{
   const bad=validate?validate(v):null;
   wrap.append(el('span',{class:'chip'+(bad?' bad':''),title:bad||null},v,
     el('button',{'aria-label':'remove '+v,
       onclick:()=>{const a=getArr().slice();a.splice(i,1);setArr(a);draw();}},'×')));});
   const inp=el('input',{placeholder:ph||'add…'});inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&inp.value.trim()){const a=(getArr()||[]).slice();a.push(inp.value.trim());setArr(a);draw();}});
   wrap.append(inp);};draw();return wrap;}
// Does the browser's engine accept this pattern? A first pass only — the config is
// compiled by Python's `re` on save, and the two dialects are not the same, so this
// says "your browser rejects it", never "this is valid".
function reErr(src){if(!src)return null;
 try{new RegExp(src);return null;}catch(e){return String(e.message||e);}}
// Read/write a dotted config path. The form is described by path in Python, so the
// only alternative would be a getter and a setter per field, hand-written.
function getPath(o,p){let cur=o;for(const k of p.split('.')){
  if(cur==null||typeof cur!=='object')return undefined;cur=cur[k];}return cur;}
function setPath(o,p,v){const ks=p.split('.');let cur=o;
 for(const k of ks.slice(0,-1)){if(typeof cur[k]!=='object'||cur[k]===null)cur[k]={};cur=cur[k];}
 cur[ks[ks.length-1]]=v;}
// An empty field means "use the default", which is written by REMOVING the key, not
// by storing an empty string — a config listing every default is a config nobody can
// read, and it also freezes today's defaults into the file.
function delPath(o,p){const ks=p.split('.');let cur=o;
 for(const k of ks.slice(0,-1)){if(cur==null||typeof cur[k]!=='object')return;cur=cur[k];}
 delete cur[ks[ks.length-1]];
 // Drop the container too if this emptied it, so removing the last usage override
 // does not leave `"usage": {}` behind.
 if(ks.length>1){const par=getPath(o,ks.slice(0,-1).join('.'));
  if(par&&typeof par==='object'&&!Object.keys(par).length)delPath(o,ks.slice(0,-1).join('.'));}}
const fieldId=p=>'set-'+p;
// Every "set X in audit.config.json" notice elsewhere in the panel comes here, to
// the field itself. A notice that names a setting and cannot reach it is a dead end
// on the one surface built to edit that setting.
function gotoSetting(path){showTab('guards');
 requestAnimationFrame(()=>{const t=document.getElementById(fieldId(path));
  if(!t)return;t.scrollIntoView({block:'center',behavior:'auto'});
  try{t.focus({preventScroll:true});}catch(e){}
  t.classList.add('flash');setTimeout(()=>t.classList.remove('flash'),1600);});}
function settingsLink(text,path){
 return el('button',{class:'lnk',type:'button',onclick:()=>gotoSetting(path)},text);}

function renderSettings(){const c=$('#guards');c.textContent='';
 const cfg=JSON.parse(JSON.stringify(STATE.config||{})),d=STATE.defaults;
 const findings=el('div',{class:'findings-slot'});
 // What this form would change, against the config the server last served. Read by
 // Save (to list it), by Discard (to say what is being thrown away) and by
 // beforeunload (to decide whether it may interrupt at all).
 EDITS.guards=()=>configChanges(cfg);
 // One `cfg`, one Save: the four cards are one FILE, and saving a quarter of a
 // document is not a thing this API can do.
 const save=el('button',{class:'btn primary',onclick:async()=>{
   const rows=configChanges(cfg);
   if(!rows.length){toast('nothing to save — no settings changed');return;}
   if(!await confirmChanges({title:'Save settings',rows,scope:'guards',
     verb:'Save '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'writes .claude/audit.config.json'}))return;
   const res=await api('PUT','/api/config',cfg);
   findings.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the config',findings);
   if(res.ok){STATE.config=JSON.parse(JSON.stringify(cfg));}}},'Save settings');
 // Enabled only when there is something to discard, and it says how much: a
 // control that throws work away must not be reachable by an idle click, and
 // "Discard" alone does not tell you whether pressing it costs you anything.
 const discard=el('button',{class:'btn small','data-discard':'guards',
   type:'button',onclick:async()=>{
   const rows=configChanges(cfg);
   if(!rows.length)return;
   if(!await confirmChanges({title:'Discard unsaved settings',rows,danger:1,
     lock:false,verb:'Discard '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'nothing is written; the form goes back to the saved file'}))return;
   renderSettings();toast('discarded — the form is back to the saved file');}},
   'Discard');
 // Every control in this form mutates `cfg` and none of them announces it, so the
 // counter is refreshed from the events that reach the view rather than from a
 // hook added to each of the twenty-odd field builders.
 onViewEdit('guards',()=>{const n=configChanges(cfg).length;
   discard.disabled=!n;
   discard.textContent=n?('Discard '+n+' change'+(n===1?'':'s')):'Discard';});
 const CUSTOM={
  'guardEdits.tokenVars':()=>tokenVarsField(cfg,d),
  'secretPatterns.extra':()=>secretPatternsField(cfg),
  'guardEdits.customRules':()=>customRulesField(cfg),
  'usage.bands':()=>bandsField(cfg),
  'usage.pricing':()=>pricingField(cfg,d)};
 for(const grp of SETTINGS){
  const card=el('div',{class:'card',id:'setgrp-'+grp.id});
  card.append(el('h2',{},grp.title));
  if(grp.blurb)card.append(el('p',{class:'blurb'},grp.blurb));
  // Ordinary fields flow into a shared row; a custom one gets its own heading and
  // closes the row before it. The row is APPENDED and replaced, never cloned —
  // cloneNode copies the elements and drops every listener on them, which would
  // leave a form that looks complete and edits nothing.
  let inline=el('div',{class:'row'}),was=null;
  const flush=()=>{if(inline.childNodes.length){card.append(inline);
    inline=el('div',{class:'row'});}};
  for(const f of grp.fields){
   const tip=HELP[f.path];
   if(f.kind==='custom'){
    flush();was=null;
    card.append(el('h3',{class:'sub2'},klabel(f.label,f.path,tip)),CUSTOM[f.path]());
    continue;}
   // Switches and boxes wrap differently — a checkbox is as wide as its words, a
   // text field claims 15rem — so mixing them in one flex row leaves a ragged edge
   // that reads as an accident. They get their own rows.
   const kind=f.kind==='bool'?'bool':'input';
   if(was&&kind!==was)flush();
   was=kind;
   inline.append(kind==='bool'?boolField(cfg,d,f,tip):scalarField(cfg,d,f,tip));}
  flush();
  c.append(card);}
 // Sticky, because the form is now four cards long and a Save you have to go
 // looking for is a Save people forget to press.
 c.append(el('div',{class:'savebar'},save,discard,
   el('span',{class:'mut small'},'writes .claude/audit.config.json'),findings));}

function boolField(cfg,d,f,tip){
 const cur=getPath(cfg,f.path),def=getPath(d,f.path)!==false;
 const cb=el('input',{type:'checkbox',id:fieldId(f.path)});
 cb.checked=cur===undefined?def:cur!==false;
 cb.onchange=()=>{if(cb.checked===def)delPath(cfg,f.path);else setPath(cfg,f.path,cb.checked);};
 return el('label',{class:'f cbf'},cb,klabel(f.label,f.path,tip));}

function scalarField(cfg,d,f,tip){
 const cur=getPath(cfg,f.path),def=getPath(d,f.path);
 let inp;
 if(f.kind==='enum'){
  // Options come from the validator's own tuple — see _cfg_enums.
  inp=el('select',{id:fieldId(f.path)},
    el('option',{value:''},'default'+(def?' ('+def+')':'')),
    (ENUMS[f.enum]||[]).map(v=>el('option',Object.assign({value:v},
      v===cur?{selected:'selected'}:{}),v)));}
 else if(f.kind==='list'){
  // The id lands on the editor, not the label: it is what gotoSetting() scrolls to
  // and focuses, and a label is neither focusable nor the thing you came to edit.
  const ed=listEditor(()=>getPath(cfg,f.path)??def??[],a=>setPath(cfg,f.path,a),
    f.placeholder||'add…');
  ed.id=fieldId(f.path);ed.tabIndex=-1;
  return el('label',{class:'f wide'},klabel(f.label,f.path,tip),ed);}
 else{const t=f.kind==='date'?'date':(f.kind==='int'||f.kind==='number')?'number':'text';
  // The placeholder is the DEFAULT, so an empty box says what leaving it empty
  // gets you. Some defaults are null and mean something anyway ("beside the
  // manifest"), and an empty box beside an empty placeholder says nothing at all —
  // so a field may supply that sentence itself.
  inp=el('input',Object.assign({type:t,id:fieldId(f.path),value:cur??'',
    placeholder:def==null?(f.placeholder||''):String(def)},
    f.min!=null?{min:String(f.min)}:{}));}
 inp.oninput=inp.onchange=()=>{const v=inp.value;
  if(v===''){delPath(cfg,f.path);return;}
  if(f.kind==='int')setPath(cfg,f.path,parseInt(v,10));
  else if(f.kind==='number')setPath(cfg,f.path,Number(v));
  else setPath(cfg,f.path,v);};
 return el('label',{class:'f'},klabel(f.label,f.path,tip),inp);}

// The three defaults are ACTIVE while this list is empty, and vanish the moment it
// is not — `_config.token_vars` returns the configured list only when it is
// non-empty. An empty box that silently means "accessToken, refreshToken, idToken"
// and a one-entry box that silently means "only that one" look identical, so both
// states say which they are.
function tokenVarsField(cfg,d){
 const defs=d.guardEdits.tokenVars;
 const box=el('div',{id:fieldId('guardEdits.tokenVars'),tabindex:'-1'});
 const note=el('div');
 const cur=()=>{const v=getPath(cfg,'guardEdits.tokenVars');return Array.isArray(v)?v:[];};
 // Only the notice is redrawn. Rebuilding the list editor would take the caret out
 // of the box you are typing in, every time you add a name.
 const draw=()=>{note.textContent='';
  const list=cur();
  if(!list.length){
   note.append(el('div',{class:'ghost'},
     el('span',{class:'mut small'},'defaults are active:'),
     defs.map(v=>el('span',{class:'chip ghosted'},v))));return;}
  const missing=defs.filter(v=>!list.includes(v));
  if(missing.length)note.append(el('div',{class:'findings warn'},
    'Your list REPLACES the defaults — it does not add to them. Not covered any '
    +'more: '+missing.join(', ')+'. ',
    el('button',{class:'lnk',type:'button',onclick:()=>{
      const merged=[...missing,...cur()];setPath(cfg,'guardEdits.tokenVars',merged);
      redraw(merged);}},'put them back')));};
 let redraw=()=>{};
 const list=listEditor(cur,a=>{if(a.length)setPath(cfg,'guardEdits.tokenVars',a);
   else delPath(cfg,'guardEdits.tokenVars');draw();},'identifier…');
 redraw=()=>{const fresh=listEditor(cur,a=>{
   if(a.length)setPath(cfg,'guardEdits.tokenVars',a);
   else delPath(cfg,'guardEdits.tokenVars');draw();},'identifier…');
  list.replaceWith(fresh);draw();};
 box.append(list,note);draw();return box;}

function secretPatternsField(cfg){
 const box=el('div',{id:fieldId('secretPatterns.extra'),tabindex:'-1'});
 const cur=()=>{const v=getPath(cfg,'secretPatterns.extra');return Array.isArray(v)?v:[];};
 box.append(listEditor(cur,a=>{if(a.length)setPath(cfg,'secretPatterns.extra',a);
   else delPath(cfg,'secretPatterns.extra');},'regex…  e.g.  \\.env$',reErr));
 box.append(el('p',{class:'blurb'},'Regexes, matched case-insensitively anywhere in '
  +'the path — so ".env" also matches secrets.envelope. Anchor it (\\.env$) when you '
  +'mean the file. A pattern your browser rejects is marked here; the save is '
  +'decided by Python’s engine, which is the one the hook uses.'));
 return box;}

function customRulesField(cfg){
 const wrap=el('div',{id:fieldId('guardEdits.customRules'),tabindex:'-1'});
 // The list is held here and written into `cfg` only when it has something in it.
 // It used to create `guardEdits.customRules: []` in the config the moment this
 // field RENDERED, so merely opening Settings on a project that had never set a
 // custom rule left an edit sitting in the form — invisible while a save wrote
 // whatever the form held, and, now that a save says what it is about to do, a
 // phantom row in the confirm dialog and a Discard button offering to throw away
 // a change nobody made.
 const cur=()=>{const v=getPath(cfg,'guardEdits.customRules');
  return Array.isArray(v)?v:[];};
 let arr=cur();
 const sync=()=>{if(arr.length)setPath(cfg,'guardEdits.customRules',arr);
  else delPath(cfg,'guardEdits.customRules');};
 const rules=()=>arr;
 const draw=()=>{wrap.textContent='';
  wrap.append(el('div',{class:'rule rulehead mut small'},
    el('span',{},'path contains'),el('span',{},'banned pattern (regex)'),
    el('span',{},'message shown when it fires'),el('span',{},'')));
  rules().forEach((r,i)=>{
   // `pathPrefix` is the key on disk and stays that, because configs in the field
   // already use it. The LABEL tells the truth about what it does: the hook tests
   // `prefix in path` against the path the tool reported, usually absolute.
   const pp=el('input',{value:r.pathPrefix||'',placeholder:'realtime/'});
   pp.oninput=()=>r.pathPrefix=pp.value;
   const bp=el('input',{value:r.bannedPattern||'',placeholder:'\\.removeAllListeners\\('});
   const err=el('div',{class:'ferr'});
   const lint=()=>{const e=reErr(bp.value);bp.classList.toggle('bad',!!e);
     err.textContent=e?'your browser rejects this pattern: '+e:'';};
   bp.oninput=()=>{r.bannedPattern=bp.value;lint();};lint();
   const ms=el('input',{value:r.message||'',placeholder:'why this is banned here'});
   ms.oninput=()=>r.message=ms.value;
   wrap.append(el('div',{class:'rule'},pp,bp,ms,
     el('button',{class:'btn small','aria-label':'remove rule '+(i+1),
       onclick:()=>{arr.splice(i,1);sync();draw();}},'×')),err);});
  wrap.append(el('button',{class:'btn small',onclick:()=>{
    arr.push({pathPrefix:'',bannedPattern:'',message:''});sync();draw();}},'+ rule'));
  wrap.append(el('p',{class:'blurb'},'The path test is a SUBSTRING match, not a '
   +'prefix — "realtime/" fires under src/realtime/ and packages/web/src/realtime/ '
   +'alike. A rule missing either field, or whose pattern will not compile, is '
   +'skipped in silence when the hook runs; saving here refuses it instead.'));};
 draw();return wrap;}

// The same predicate usage_ledger.cost_bands applies: 0 < high <= outlier, and
// anything else falls back to the relative basis. Said here, next to the pair,
// because the fallback is silent everywhere else.
function bandsField(cfg){
 const box=el('div',{id:fieldId('usage.bands'),tabindex:'-1'});
 const row=el('div',{class:'row'}),warn=el('div');
 const mk=(key,lbl)=>{const p='usage.bands.'+key;
  const inp=el('input',{type:'number',min:'0',step:'0.01',id:fieldId(p),
    value:getPath(cfg,p)??'',placeholder:'not set'});
  inp.oninput=()=>{if(inp.value==='')delPath(cfg,p);else setPath(cfg,p,Number(inp.value));lint();};
  return el('label',{class:'f'},klabel(lbl,p,null),inp);};
 const lint=()=>{const hi=getPath(cfg,'usage.bands.highUSD'),
   ou=getPath(cfg,'usage.bands.outlierUSD');
  warn.textContent='';
  if(hi==null&&ou==null){warn.append(el('div',{class:'findings ok'},
    'Both empty: bands calibrate from this project’s own completed tasks '
    +'(median and p90), once there are five of them.'));return;}
  if(hi==null||ou==null){warn.append(el('div',{class:'findings warn'},
    'Set BOTH or neither — one threshold alone is ignored and the bands fall back '
    +'to the project-relative basis.'));return;}
  if(!(hi>0&&hi<=ou))warn.append(el('div',{class:'findings warn'},
    'high must be above 0 and no greater than outlier. As written this pair is '
    +'ignored at runtime and the bands fall back to the project-relative basis — '
    +'silently, which is why it is said here.'));};
 row.append(mk('highUSD','high above'),mk('outlierUSD','outlier above'));
 box.append(row,warn);lint();
 return box;}

function pricingField(cfg,d){
 const wrap=el('div',{id:fieldId('usage.pricing'),tabindex:'-1'});
 const COLS=[['in','input'],['out','output'],['cacheW5m','cache w 5m'],
   ['cacheW1h','cache w 1h'],['cacheR','cache read']];
 const cur=()=>{const v=getPath(cfg,'usage.pricing');
  return (v&&typeof v==='object'&&!Array.isArray(v))?v:{};};
 const draw=()=>{wrap.textContent='';
  const over=cur(),models=[...new Set([...Object.keys(d.usage.pricing),...Object.keys(over)])].sort();
  const tbl=el('table',{class:'ptbl'},el('thead',{},el('tr',{},
    el('th',{},'model'),COLS.map(([,l])=>el('th',{class:'n'},l)),el('th',{}))));
  const tb=el('tbody');
  models.forEach(m=>{
   const def=(d.usage.pricing||{})[m]||{},row=over[m]||{};
   const tds=COLS.map(([k])=>{
    const inp=el('input',{type:'number',min:'0',step:'0.01',value:row[k]??'',
      placeholder:def[k]==null?'—':String(def[k]),'aria-label':m+' '+k});
    inp.oninput=()=>{const o=cur();
     if(inp.value===''){if(o[m])delete o[m][k];}
     else{o[m]=o[m]||{};o[m][k]=Number(inp.value);}
     if(o[m]&&!Object.keys(o[m]).length)delete o[m];
     if(Object.keys(o).length)setPath(cfg,'usage.pricing',o);
     else delPath(cfg,'usage.pricing');};
    return el('td',{class:'n'},inp);});
   tb.append(el('tr',{},el('td',{class:'mono'},m),tds,
     el('td',{},over[m]?el('button',{class:'btn small','aria-label':'reset '+m,
       title:'drop this override and use the shipped rate',
       onclick:()=>{const o=cur();delete o[m];
        if(Object.keys(o).length)setPath(cfg,'usage.pricing',o);
        else delPath(cfg,'usage.pricing');draw();}},'reset'):null)));});
  tbl.append(tb);wrap.append(el('div',{class:'ptblwrap'},tbl));
  const add=el('input',{placeholder:'add a model id…'});
  add.addEventListener('keydown',e=>{if(e.key!=='Enter'||!add.value.trim())return;
   const o=cur();o[add.value.trim()]=o[add.value.trim()]||{};
   setPath(cfg,'usage.pricing',o);add.value='';draw();});
  wrap.append(el('div',{class:'row'},add));
  wrap.append(el('p',{class:'blurb'},'Empty means the shipped rate shown in the box, '
   +'so only what you change is written. An unrecognised model id falls back to the '
   +'longest matching prefix and then to _default, which is priced at the top tier '
   +'on purpose: over-stating spend is the safer error for a cost display.'));};
 draw();return wrap;}
// ---------- Composition ----------
function skillPicker(current,onChange){
 const inp=el('input',{value:current??'',placeholder:'search a skill…  (empty = none)'});
 inp.addEventListener('input',()=>onChange(inp.value.trim()||null));
 return comboWrap(inp,()=>REG.skills,(name,close)=>{inp.value=name;onChange(name);close();});}
function skillChips(getArr,setArr){
 const box=el('div',{class:'chipwrap'}),chips=el('div',{class:'chips'});
 const inp=el('input',{placeholder:'search a skill to add…'});
 const draw=()=>{chips.textContent='';(getArr()||[]).forEach((v,i)=>chips.append(
   el('span',{class:'chip'},v,el('button',{onmousedown:e=>{e.preventDefault();const a=getArr().slice();a.splice(i,1);setArr(a);draw();}},'×'))));};
 const add=(name,close)=>{const n=(name||'').trim();
   if(n){const a=(getArr()||[]).slice();if(!a.includes(n)){a.push(n);setArr(a);draw();}}
   inp.value='';if(close)close();};
 const combo=comboWrap(inp,()=>REG.skills.filter(s=>!(getArr()||[]).includes(s.name)),add,add);
 draw();box.append(chips,combo);return box;}
// Composition's filter state lives OUT here, not in renderComp's closure. Two
// reasons, and the second is the one that made it necessary: a re-render (after a
// save, or a poll) used to drop you back to the unfiltered table, and Overview
// needs to hand this tab a phase to open. `apply` is published by renderComp so a
// caller can change the state without re-rendering — re-rendering would throw away
// whatever is half-typed in the composition form, which is the same mistake the
// run-status poll was fixed for.
const COMPF={q:'',status:'',needs:false,open:{},apply:null};
function openInComp(pid){COMPF.q=pid;COMPF.status='';COMPF.needs=false;COMPF.open[pid]=true;
 if(COMPF.apply)COMPF.apply();showTab('comp');}
function renderComp(){const c=$('#comp');c.textContent='';const comp=STATE.composition;
 const patch={meta:{},phases:{},tasks:{}};
 const meta=el('div',{class:'card'});meta.append(h2h('Phase sign-off review skill (meta.reviewSkill)',MDESC.reviewSkill));
 meta.append(el('div',{class:'row'},skillPicker(comp.meta.reviewSkill,v=>patch.meta.reviewSkill=v)));
 meta.append(h2h('meta.buildCommands (JSON)',MDESC.buildCommands));
 const bc=el('textarea',{});bc.value=comp.meta.buildCommands?JSON.stringify(comp.meta.buildCommands,null,2):'';
 let bcBad=false;
 bc.oninput=()=>{try{patch.meta.buildCommands=bc.value.trim()?JSON.parse(bc.value):null;
   bcBad=false;bc.style.borderColor='';}
  catch(e){bcBad=true;bc.style.borderColor='var(--err)';}};
 meta.append(bc);c.append(meta);
 // tasks: filter toolbar + ONE compact collapsible table (scales to 50x20)
 const tcard=el('div',{class:'card'});tcard.append(h2h('Composition — phases · tasks · skills',MDESC.taskSkills));
 const q=el('input',{type:'search',placeholder:'filter phases & tasks…',value:COMPF.q});
 const statusBar=el('span',{class:'filtset',style:'display:inline-flex;gap:.3rem;flex-wrap:wrap'});
 const needsBtn=el('button',{class:'filt',type:'button','aria-pressed':'false',title:'only tasks with no skills yet'},'needs skills');
 const expandBtn=el('button',{class:'btn small',type:'button'},'expand all');
 const count=el('span',{class:'count',style:'margin-left:auto'});
 tcard.append(el('div',{class:'comptools'},q,el('span',{class:'filtlbl'},'phase:'),statusBar,needsBtn,expandBtn,count));
 const tbody=el('tbody');
 tcard.append(el('div',{class:'comptblwrap'},el('table',{class:'comp'},
   el('thead',{},el('tr',{},el('th',{},'id'),el('th',{},'title'),el('th',{},'status'),el('th',{},'model'),el('th',{},'skills'))),tbody)));

 const open=COMPF.open;
 const phaseEls=[];const byPhase={};comp.tasks.forEach(t=>{(byPhase[t.phaseId]=byPhase[t.phaseId]||[]).push(t);});
 comp.phases.forEach(ph=>{
  const tasks=byPhase[ph.id]||[];
  const rev=el('input',{value:ph.reviewModel??'',placeholder:'review model'});
  rev.oninput=()=>{patch.phases[ph.id]={reviewModel:rev.value.trim()||null};};
  rev.onclick=e=>e.stopPropagation();
  const pr=el('tr',{class:'phase','data-status':ph.status||''});
  pr.append(el('td',{colspan:'5'},el('div',{class:'phtd'},
    el('span',{class:'tri'}),el('span',{class:'mono'},ph.id||''),el('strong',{},ph.title||''),
    (ph.area||[]).map(a=>el('span',{class:'badge area'},a)),
    el('span',{class:'st','data-status':ph.status||''},label(ph.status)),
    el('span',{class:'count'},tasks.length+(tasks.length===1?' task':' tasks')),
    el('span',{class:'comp-review'},flabel('review',MDESC.phaseReviewModel),rev))));
  pr.onclick=()=>{open[ph.id]=!open[ph.id];refresh();};
  tbody.append(pr);
  const taskEls=[];
  tasks.forEach(t=>{
   const tp={};const model=el('input',{value:t.model??'',placeholder:'—'});
   model.oninput=()=>{tp.model=model.value.trim()||null;patch.tasks[t.id]=tp;};
   const getSkills=()=>tp.skills!==undefined?tp.skills:(t.skills||[]);
   const chips=skillChips(getSkills,a=>{tp.skills=a;patch.tasks[t.id]=tp;if(COMPF.needs)refresh();});
   const tr=el('tr',{class:'task','data-status':t.status||''});
   tr.append(el('td',{class:'tid'},t.id||''),el('td',{class:'ttitle',title:t.title||''},t.title||''),
     el('td',{},el('span',{class:'st','data-status':t.status||''},label(t.status))),
     el('td',{class:'tmodel'},model),el('td',{class:'tskills'},chips));
   tbody.append(tr);
   taskEls.push({id:t.id||'',title:t.title||'',tr,getSkills});
  });
  phaseEls.push({id:ph.id,title:ph.title||'',status:ph.status||'',area:(ph.area||[]).join(' '),tr:pr,tasks:taskEls});
 });
 [...new Set(comp.phases.map(p=>p.status).filter(Boolean))].sort().forEach(s=>{
  const b=el('button',{class:'filt',type:'button','data-status':s,'aria-pressed':'false'},label(s));
  b.onclick=()=>{COMPF.status=COMPF.status===s?'':s;syncFilters();refresh();};
  statusBar.append(b);});
 // aria-pressed alongside the class: which filter is on was carried by the accent
 // fill alone, which a screen reader never sees. Driven from COMPF rather than
 // toggled in place, so a filter set from elsewhere (Overview) shows here too.
 function syncFilters(){
  [...statusBar.children].forEach(x=>{const on=x.getAttribute('data-status')===COMPF.status;
   x.classList.toggle('on',on);x.setAttribute('aria-pressed',on?'true':'false');});
  needsBtn.classList.toggle('on',COMPF.needs);
  needsBtn.setAttribute('aria-pressed',COMPF.needs?'true':'false');}
 needsBtn.onclick=()=>{COMPF.needs=!COMPF.needs;syncFilters();refresh();};
 expandBtn.onclick=()=>{const anyClosed=phaseEls.some(P=>!open[P.id]);phaseEls.forEach(P=>open[P.id]=anyClosed);refresh();};
 const hit=(s,term)=>!term||s.toLowerCase().includes(term);
 function refresh(){
  COMPF.q=q.value;
  const term=q.value.trim().toLowerCase();const forced=(term!=='')||COMPF.needs;let visP=0,visT=0;
  phaseEls.forEach(P=>{
   const pText=hit(P.id+' '+P.title+' '+P.area,term);let anyT=false;
   P.tasks.forEach(T=>{const tHit=pText||hit(T.id+' '+T.title,term);
    const needHit=!COMPF.needs||((T.getSkills()||[]).length===0);T._m=tHit&&needHit;if(T._m)anyT=true;});
   const showP=(!COMPF.status||P.status===COMPF.status)&&(pText||anyT)&&(!COMPF.needs||anyT);
   P.tr.style.display=showP?'':'none';if(showP)visP++;
   const isOpen=showP&&(forced||!!open[P.id]);P.tr.classList.toggle('open',isOpen);
   P.tasks.forEach(T=>{const showT=showP&&isOpen&&T._m;T.tr.style.display=showT?'':'none';if(showT)visT++;});});
  count.textContent=(term||COMPF.status||COMPF.needs)?(visP+' / '+phaseEls.length+' phases · '+visT+' tasks')
    :(phaseEls.length+' phases · '+comp.tasks.length+' tasks');
  expandBtn.textContent=phaseEls.some(P=>!open[P.id])?'expand all':'collapse all';}
 // Published for whoever wants to scope this tab without rebuilding it.
 COMPF.apply=()=>{q.value=COMPF.q;syncFilters();refresh();};
 syncFilters();q.addEventListener('input',refresh);refresh();

 EDITS.comp=()=>compChanges(patch);
 const save=el('button',{class:'btn primary',onclick:async()=>{
   // The textarea only writes into the patch when its contents PARSE, so an
   // unparseable box would confirm — and then save — the last value that did. A
   // dialog that shows something other than what the form holds is worse than no
   // dialog, so this is refused at the door and the field says which one it is.
   if(bcBad){toast('meta.buildCommands is not valid JSON — fix it or clear it '
     +'before saving','err');bc.focus();return;}
   const rows=compChanges(patch);
   if(!rows.length){toast('nothing to save — no values changed');return;}
   if(!await confirmChanges({title:'Save composition',rows,scope:'comp',
     verb:'Save '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'writes '+STATE.manifestPath}))return;
   const clean={meta:{},phases:patch.phases,tasks:patch.tasks};
   for(const k of Object.keys(patch.meta))clean.meta[k]=patch.meta[k];
   const res=await api('PUT','/api/composition',clean);
   if(!res.ok){c.querySelector('.findings-slot').replaceChildren(findingsBox(res));
    saveOutcome(res,rows,'the manifest',null);return;}
   // Re-render from the saved state. Without it the form kept showing the values
   // you typed rather than the values on disk — indistinguishable while they
   // agree, and silently wrong the moment the server normalised one or refused
   // part of a patch. COMPF is hoisted, so the filter, the search and which
   // phases were open all survive this.
   STATE=await api('GET','/api/state');renderComp();renderOver();
   const slot=$('#comp .findings-slot');
   if(slot)slot.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the manifest',slot);}},'Save composition');
 const discard=el('button',{class:'btn small','data-discard':'comp',type:'button',
   onclick:async()=>{
   const rows=compChanges(patch);
   if(!rows.length)return;
   if(!await confirmChanges({title:'Discard unsaved composition edits',rows,
     danger:1,lock:false,
     verb:'Discard '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'nothing is written; the table goes back to the saved manifest'}))return;
   renderComp();toast('discarded — the table is back to the saved manifest');}},
   'Discard');
 onViewEdit('comp',()=>{const n=compChanges(patch).length;
   discard.disabled=!n;
   discard.textContent=n?('Discard '+n+' change'+(n===1?'':'s')):'Discard';});
 tcard.append(el('div',{class:'row',style:'margin-top:.9rem'},save,discard),
   el('div',{class:'findings-slot'}));
 if(!STATE.manifestExists)tcard.append(el('div',{class:'findings warn'},'No manifest yet — run /audit:init first.'));
 if(STATE.manifestLocked)tcard.append(el('div',{class:'findings warn'},'Manifest is locked by a running /audit command.'));
 c.append(tcard);
 // building blocks — one table, sub-tabs switch context (skills / agents / mcp)
 const bb=el('div',{class:'card'});
 bb.append(h2h('Available building blocks (discovered)',
   'Skills & agents found in this project, your ~/.claude, and installed plugins — plus MCP servers in scope. Use these names in the pickers above.'));
 const datasets={skills:REG.skills,agents:REG.agents,
   mcp:(REG.mcp||[]).map(n=>({name:n,source:'mcp',description:''}))};
 const subtabs=el('div',{class:'subtabs'}),host=el('div',{class:'regtblwrap'});let cur='skills';
 const drawTbl=()=>{const items=datasets[cur]||[];const tb=el('tbody');
   if(!items.length)tb.append(el('tr',{},el('td',{colspan:'3',class:'mut'},'none found')));
   items.forEach(it=>tb.append(el('tr',{},el('td',{class:'mono'},it.name),
     el('td',{},it.source?el('span',{class:'src badge'},it.source):null),
     el('td',{class:'d'},it.description||''))));
   host.replaceChildren(el('table',{class:'regtbl'},
     el('thead',{},el('tr',{},el('th',{},'name'),el('th',{},'source'),el('th',{},'description'))),tb));};
 ['skills','agents','mcp'].forEach(k=>subtabs.append(el('button',{class:'subtab'+(k===cur?' on':''),
   onclick:e=>{cur=k;[...subtabs.children].forEach(x=>x.classList.toggle('on',x===e.currentTarget));drawTbl();}},
   k+' ('+(datasets[k]||[]).length+')')));
 drawTbl();bb.append(subtabs,host);c.append(bb);}
// One malformed manifest can emit a finding PER phase, per task and per indexed
// file: a 300-phase repo produced 1009 of them, joined into a single paragraph
// that filled the screen and told the reader nothing. But 1009 findings are not
// 1009 problems — they were four mistakes repeated. So group by shape, count each,
// show one real example, and keep the raw list one click away.
const FGROUP_MIN=6, FSHOW=6, FRAW=200;
function findingKind(s){
 const i=s.indexOf(': ');
 return (i>0?s.slice(i+2):s)
  .replace(/'[^']*'/g,"'*'").replace(/\[[^\]]*\]/g,'[*]').replace(/\d+/g,'#');}
// Named for the manifest specifically: findingsBox() already exists above for
// save-result feedback, and a second function of the same name would hoist over it
// and break every config save.
function manifestFindingsBox(n,list){
 const box=el('div',{class:'findings err'},
   el('b',{},'✗ '+n+' finding(s)'));
 if(list.length<FGROUP_MIN){
  box.append(' '+list.join(' · '));return box;}
 const by=new Map();
 for(const f of list){const k=findingKind(f);
  const g=by.get(k)||{n:0,eg:f};g.n++;by.set(k,g);}
 const groups=[...by.entries()].sort((a,b)=>b[1].n-a[1].n);
 const ul=el('ul',{class:'fgrp'});
 groups.slice(0,FSHOW).forEach(([k,g])=>ul.append(el('li',{},
   el('span',{class:'fn'},g.n+'×'),
   el('span',{},k,el('div',{class:'feg'},g.n>1?'e.g. '+g.eg:g.eg)))));
 box.append(el('div',{},groups.length===1?'one problem, repeated:'
   :groups.length+' distinct problems'
    +(groups.length>FSHOW?' ('+FSHOW+' most common shown)':'')+':'),ul);
 const ol=el('ol',{});
 list.slice(0,FRAW).forEach(f=>ol.append(el('li',{},f)));
 if(list.length>FRAW)ol.append(el('li',{},'… and '+(list.length-FRAW)+
   ' more — run /audit:validate for the complete list'));
 box.append(el('details',{class:'fall'},
   el('summary',{},'every finding, unfolded'),ol));
 return box;}

// ---------- live run status ----------
// Who is driving which phase changes WHILE you are looking at the panel — that is
// the whole point of the badges, and until now they were a snapshot taken at page
// load. A colleague taking a phase lock in another worktree appeared only if you
// happened to reload.
//
// It polls the narrow endpoint, never /api/state: re-rendering from full state
// would discard whatever is half-typed in the guards form, so "live" would have
// cost you your edits. And it only repaints Overview, which has no inputs.
//
// Stops while the tab is hidden. A backgrounded panel polling a colleague's laptop
// every few seconds forever is the kind of thing people notice in a battery graph
// and never forgive.
let RUNSTATUS=null, RUNPOLL=null;
function runStatusKey(rs){return JSON.stringify(rs&&{i:rs.index,p:rs.phases});}
async function pollRunStatus(){
 if(document.hidden)return;
 try{
  const next=await api('GET','/api/runstatus');
  if(runStatusKey(next)===runStatusKey(RUNSTATUS))return;   // no repaint on no change
  RUNSTATUS=next;
  if(!$('#over').classList.contains('hidden'))renderOver();
 }catch(e){/* a panel that dies because a poll failed is worse than a stale badge */}
}
function startRunPoll(){
 if(RUNPOLL)clearInterval(RUNPOLL);
 RUNPOLL=setInterval(pollRunStatus,5000);
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollRunStatus();});

// ---------- Overview ----------
// The rollup arrives with tasks.byStatus, bugs.byStatus, areas and ready[] already
// computed, and this view used to drop all four on the floor: four grey total chips
// and a flat list of every phase. So the numbers you steer by — what is in
// progress, what is blocked, which bugs are open, what can start right now — were
// the numbers the panel had and would not show.
//
// The filter state lives OUT here for the same reason COMPF does: the 5s run-status
// poll repaints this view, so a filter held in the render closure would be wiped by
// a badge update the reader never asked for, five seconds after they set it.
const OVF={q:'',ts:'',bs:'',byArea:false,sort:'plan'};
// Nothing-to-see-first: the statuses that need a human come before the ones that
// do not, in the strips and in the status sort. Plan order is still the default —
// a plan is written in an order and that order means something.
const OVORDER=['in_progress','blocked','pending','done'];
const OVBUGORDER=['open','triaged','in_progress','fixed','wontfix'];
const ovRank=(o,s)=>{const i=o.indexOf(s);return i<0?o.length:i;};
const ovAnyFilter=()=>!!(OVF.q.trim()||OVF.ts||OVF.bs);
function ovPill(status,n,text,on,onclick,tip,cls){
 return el('button',{class:'ovpill'+(cls?' '+cls:''),type:'button','data-status':status||'',
  'aria-pressed':on?'true':'false',title:tip||'',onclick:onclick},text,el('b',{},String(n)));}
// A copy button that fails silently is worse than no copy button: clipboard.write
// can be refused, and the reader is left believing they have the command.
function ovCopy(btn,text){
 const done=()=>{const was=btn.textContent;btn.textContent='Copied';
  setTimeout(()=>{btn.textContent=was;},1600);};
 const manual=()=>{const ta=el('textarea',{style:'position:fixed;top:-1000px;opacity:0'});
  ta.value=text;document.body.append(ta);ta.select();
  let ok=false;try{ok=document.execCommand('copy');}catch(e){ok=false;}
  ta.remove();if(ok)done();else toast('could not copy — the command is '+text,'err');};
 try{navigator.clipboard.writeText(text).then(done,manual);}catch(e){manual();}}
function renderOver(){const c=$('#over');const r=STATE.rollup;
 // The poll repaints this view under the reader's hands. Put the caret back where
 // it was, or typing a five-letter search while a colleague takes a phase lock
 // loses the last three letters and the focus with them.
 const act=document.activeElement,keepQ=!!(act&&act.id==='ovq'),
   caret=keepQ?act.selectionStart:0;
 c.textContent='';
 const card=el('div',{class:'card'});
 if(!r){card.append(el('div',{class:'mut'},'No manifest at '+STATE.manifestPath+'. Run /audit:init.'));c.append(card);return;}
 const vstate=r.valid?el('div',{class:'findings ok'},'✓ manifest valid ('+r.warnings+' warnings)')
   :manifestFindingsBox(r.findings,STATE.manifestFindings||[]);
 card.append(vstate);
 const rs=RUNSTATUS||STATE.runStatus||{index:null,phases:{}};
 if(rs.index){const h=rs.index.hostname||'?';const dead=rs.index.live===false;
  card.append(el('div',{class:'findings warn',title:rs.index.liveBasis||''},
   (dead?'⚠ index lock held by no live run':'⚙ index locked (structural op / id allocation)')
   +(h?' · '+h:'')+(rs.index.startedAt?' · since '+rs.index.startedAt:'')
   +(dead?' · '+(rs.index.liveBasis||''):'')));}

 // --- the two strips: legend and filter in one control ------------------------
 // Per-phase status counts come from the composition (the same manifest), because
 // the rollup carries done/total per phase and nothing finer — and "which phases
 // have work in progress" is the question the strip is for.
 const tasks=(STATE.composition||{}).tasks||[];
 const pStatus={};
 tasks.forEach(t=>{const m=pStatus[t.phaseId]=pStatus[t.phaseId]||{};
  const s=t.status||'';m[s]=(m[s]||0)+1;});
 const tBy=r.tasks.byStatus||{},bBy=r.bugs.byStatus||{};
 const tstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Tasks'),
   el('span',{class:'mut'},r.tasks.total+' total'));
 Object.keys(tBy).sort((a,b)=>ovRank(OVORDER,a)-ovRank(OVORDER,b)).forEach(s=>{
  tstrip.append(ovPill(s,tBy[s],label(s),OVF.ts===s,
    ()=>{OVF.ts=OVF.ts===s?'':s;renderOver();},
    'show only phases carrying '+label(s).toLowerCase()+' tasks'));});
 const bstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Bugs'),
   el('span',{class:'mut'},r.bugs.total+' total · '+r.bugs.open+' open'));
 Object.keys(bBy).sort((a,b)=>ovRank(OVBUGORDER,a)-ovRank(OVBUGORDER,b)).forEach(s=>{
  bstrip.append(ovPill(s,bBy[s],label(s),OVF.bs===s,
    ()=>{OVF.bs=OVF.bs===s?'':s;renderOver();},'show only '+label(s).toLowerCase()+' bugs'));});
 // Not a status — a severity cut across the open ones. It keeps its own class
 // rather than borrowing data-status="blocked" for the colour: the machine value
 // in data-status is what the CSS themes off AND what a reader inspecting the DOM
 // is told this pill means, and "blocked" would be a plain lie there.
 if(r.bugs.openHighSeverity)bstrip.append(ovPill('',r.bugs.openHighSeverity,
   'High severity, open',OVF.bs==='!high',()=>{OVF.bs=OVF.bs==='!high'?'':'!high';renderOver();},
   'open bugs filed high, critical, blocker, sev1 or p0','hi'));
 card.append(tstrip,bstrip);

 // --- tools: search, sort, group by area --------------------------------------
 const qIn=el('input',{type:'search',id:'ovq',value:OVF.q,
   placeholder:'search phases — id, title, area, outcome…','aria-label':'search phases'});
 qIn.addEventListener('input',()=>{OVF.q=qIn.value;renderOver();});
 const sortSel=el('select',{'aria-label':'sort phases',
   onchange:e=>{OVF.sort=e.target.value;renderOver();}});
 [['plan','plan order'],['progress','progress'],['status','status']].forEach(([v,t])=>{
  const o=el('option',{value:v},t);if(OVF.sort===v)o.selected=true;sortSel.append(o);});
 const tools=el('div',{class:'ovtools'},qIn,el('span',{class:'filtlbl'},'sort:'),sortSel);
 const areaTags=Object.keys(r.areas||{});
 if(areaTags.length){
  const cb=el('input',{type:'checkbox',id:'ovarea'});cb.checked=OVF.byArea;
  cb.onchange=()=>{OVF.byArea=cb.checked;renderOver();};
  tools.append(el('label',{class:'inl',for:'ovarea'},cb,'group by area'));}
 const count=el('span',{class:'count',style:'margin-left:auto'});
 tools.append(count);
 if(ovAnyFilter())tools.append(el('button',{class:'btn small',type:'button','data-ovclear':'1',
   onclick:()=>{OVF.q='';OVF.ts='';OVF.bs='';renderOver();}},'Clear filters'));
 card.append(el('h2',{},'Phases'),tools);

 // --- phases -------------------------------------------------------------------
 const term=OVF.q.trim().toLowerCase();
 const hitP=p=>(!term||((p.id+' '+(p.title||'')+' '+(p.area||[]).join(' ')+' '
     +(p.desiredOutcome||'')).toLowerCase().includes(term)))
   &&(!OVF.ts||!!((pStatus[p.id]||{})[OVF.ts]));
 const ordered=r.phases.filter(hitP);
 const pct=p=>p.total?100*p.done/p.total:0;
 if(OVF.sort==='progress')ordered.sort((a,b)=>pct(b)-pct(a));
 else if(OVF.sort==='status')ordered.sort((a,b)=>ovRank(OVORDER,a.status)-ovRank(OVORDER,b.status));
 function phaseRow(p){const w=Math.round(pct(p));
  const st=(rs.phases||{})[p.id]||{};let runBadge=null;
  if(st.lock){const h=st.lock.hostname||'?';const dead=st.lock.live===false;
   // "running" is a claim about a process. Say it only when the pid was probed
   // and answered; an abandoned lock says so, with the basis in the tooltip.
   runBadge=el('span',{class:'badge '+(dead?'held':'run'),
    title:(st.lock.liveBasis||'phase lock held')+(st.lock.startedAt?' · since '+st.lock.startedAt:'')},
    (dead?'○ lock, no live run':'● running')+(h?' · '+h:''));}
  else if(st.claim){const s=(st.claim.sessionId||'').slice(0,8);
   runBadge=el('span',{class:'badge claim',title:'claimed'+(st.claim.branch?' on '+st.claim.branch:'')},'◷ claimed'+(s?' · '+s:''));}
  const areaBadges=(p.area||[]).map(a=>el('span',{class:'badge area',title:'area'},a));
  // One control, not a row with a handler bolted on: keyboard reachable and
  // announced as pressable without a hand-written role/tabindex/keydown trio.
  return el('button',{class:'ovrow',type:'button','data-status':p.status||'','data-phase':p.id,
    title:'open '+p.id+' in Composition',onclick:()=>openInComp(p.id)},
   el('span',{class:'pid'},p.id),
   el('span',{class:'ptitle'},p.title||''),
   el('span',{class:'st','data-status':p.status||''},label(p.status)),
   areaBadges,runBadge,
   OVF.ts?el('span',{class:'ovmatch'},((pStatus[p.id]||{})[OVF.ts]||0)+' '+label(OVF.ts).toLowerCase()):null,
   el('span',{class:'bar'},el('i',{style:'width:'+w+'%'})),
   el('span',{class:'mut'},p.done+'/'+p.total),
   // The line the plan is actually about. It was in the rollup all along and the
   // panel showed the title, which says what the phase is called, not what it is for.
   p.desiredOutcome?el('span',{class:'ovout',title:p.desiredOutcome},p.desiredOutcome):null);}
 if(!ordered.length){
  card.append(el('div',{class:'ovempty'},'No phase matches this filter. ',
    el('button',{class:'btn small',type:'button','data-ovclear':'1',
      onclick:()=>{OVF.q='';OVF.ts='';OVF.bs='';renderOver();}},'Clear filters')));}
 else if(OVF.byArea){
  // A phase with two tags is listed under both — the same rule the rollup counts
  // by, so the group headings add up to more than the plan when tags overlap, and
  // saying so here is cheaper than a reader discovering it by arithmetic.
  areaTags.sort().forEach(tag=>{
   const inTag=ordered.filter(p=>(p.area||[]).includes(tag));
   if(!inTag.length)return;
   const g=r.areas[tag]||{};
   card.append(el('div',{class:'ovgrp'},el('span',{class:'gname'},tag),
     el('span',{class:'mut'},inTag.length+' of '+g.phases+' phases · '+g.done+'/'+g.total+' tasks')));
   inTag.forEach(p=>card.append(phaseRow(p)));});
  const untagged=ordered.filter(p=>!(p.area||[]).length);
  if(untagged.length){card.append(el('div',{class:'ovgrp'},el('span',{class:'gname'},'untagged'),
    el('span',{class:'mut'},untagged.length+' phases')));
   untagged.forEach(p=>card.append(phaseRow(p)));}}
 else ordered.forEach(p=>card.append(phaseRow(p)));
 count.textContent=ovAnyFilter()?(ordered.length+' / '+r.phases.length+' phases')
   :(r.phases.length+' phases · '+r.tasks.total+' tasks');
 c.append(card);

 // --- ready now ----------------------------------------------------------------
 const tById={};tasks.forEach(t=>{tById[t.id]=t;});
 // Deliberately NOT scoped by the strips: this is the do-something-now list, and a
 // filter set to look at what is blocked must not empty the one card that says
 // where to start.
 const ready=r.ready||[];
 const rcard=el('div',{class:'card'});
 rcard.append(h2h('Ready now',
   'Tasks whose blockers are all done and whose phase is not gated — the ones /audit:run '
   +'will accept right now. Copy the command rather than retyping an id.'));
 if(!ready.length)rcard.append(el('div',{class:'mut'},
   r.tasks.total?'Nothing is ready: every pending task is waiting on something, or there is nothing left to do.'
     :'No tasks yet.'));
 const RSHOW=8;
 ready.slice(0,RSHOW).forEach(id=>{const t=tById[id]||{};
  const cmd='/audit:run '+id;
  rcard.append(el('div',{class:'rdy'},el('code',{class:'rcmd'},cmd),
    el('span',{class:'rt',title:t.title||''},t.title||''),
    t.phaseId?el('span',{class:'mut'},t.phaseId):null,
    el('button',{class:'btn small',type:'button','data-copy':cmd,
      onclick:e=>ovCopy(e.currentTarget,cmd)},'Copy')));});
 if(ready.length>RSHOW)rcard.append(el('div',{class:'mut'},
   '+'+(ready.length-RSHOW)+' more ready — see Composition'));
 c.append(rcard);

 // --- bugs ---------------------------------------------------------------------
 const bugs=STATE.bugs||[];
 if(bugs.length){
  const bcard=el('div',{class:'card'});
  bcard.append(h2h('Bugs',
    'Status here is the EFFECTIVE status the totals above count: a bug materialized '
    +'into a task reads Fixed once that task is done, so the list and the pills can '
    +'never disagree.'));
  const rows=bugs.filter(b=>OVF.bs?(OVF.bs==='!high'?(b.open&&b.high):b.status===OVF.bs):true);
  if(!rows.length)bcard.append(el('div',{class:'ovempty'},'No bug matches this filter.'));
  rows.slice(0,20).forEach(b=>{
   bcard.append(el('div',{class:'rdy'},el('span',{class:'mono'},b.id||''),
     el('span',{class:'rt',title:b.title||''},b.title||''),
     b.severity?el('span',{class:'sev'+(b.high?' high':'')},b.severity):null,
     el('span',{class:'st','data-status':b.status||''},label(b.status)),
     // A bug whose status came from its task should say where it came from, or it
     // reads as something somebody typed into the manifest by hand.
     b.taskId?el('span',{class:'mut',title:'materialized as '+b.taskId
       +(b.reported&&b.reported!==b.status?' (reported '+label(b.reported).toLowerCase()+')':'')},
       '→ '+b.taskId):null));});
  if(rows.length>20)bcard.append(el('div',{class:'mut'},'+'+(rows.length-20)+' more'));
  c.append(bcard);}

 if(keepQ){const n=$('#ovq');if(n){n.focus();try{n.setSelectionRange(caret,caret);}catch(e){}}}}
// ---------- capability policy: the switchboard ----------
// `{"default":"deny","allow":["code-*"]}` is four words that decide the fate of
// every skill on the machine, and nobody can hold that cross-product in their
// head. This view IS the cross-product: one row per capability the project can
// actually reach, the verdict the guard would give it, and the reason.
//
// Two rules run through all of it.
//
// The verdicts are the SERVER's — computed by `_policy.resolve`, the function the
// hook itself calls — and are never recomputed here. A second matcher in the
// browser would eventually disagree with the guard, and disagreeing about a denial
// is the one thing a preview must not do. The consequence is that a verdict is
// true of the SAVED policy: an edited row is marked as pending rather than
// re-judged, and the verdicts are re-read from the server after every save.
//
// And the draft is the block AS WRITTEN (`stored`), never the merged one. PUT
// /api/policy replaces the block wholesale, so anything this form does not
// represent — a comment key, a pattern nobody clicked — would be destroyed by
// someone who came to flip one switch. Which is also why the raw rules are a table
// of their own further down: a rule the form cannot show is a rule it must not be
// trusted to save.
let POLICY=null;
// null means "no policy block on disk, and nothing typed yet". It is not {}: an
// empty object is a policy someone wrote, and writing one where there was none is
// a change this view must not make by rendering.
let PDRAFT=null;
const PKINDS=['skills','agents','mcp'];
const PKLABEL={skills:'Skills',agents:'Subagents',mcp:'MCP servers'};
const PF={kind:'skills',q:'',bad:false};
// The nodes the last save left behind — the ✓/✗ box and, if the file had moved
// under the reader, the mismatch warning. A save re-renders the whole view to pick
// up the server's fresh verdicts, which would otherwise throw away the one part of
// the page that says what just happened. Consumed once, so an edit made afterwards
// does not sit under a stale "saved".
let PNOTE=null;
const pClone=o=>(o==null?null:JSON.parse(JSON.stringify(o)));
// Every edit goes through here. It drops the last save's box — that box describes
// a file this form no longer matches — and redraws.
function pEdit(fn){PNOTE=null;fn();renderPolicy();}
function pBlock(){if(PDRAFT===null)PDRAFT={};return PDRAFT;}
const pKindCfg=(b,k)=>((b||{})[k]||{});
const pEnabled=()=>((PDRAFT||{}).enabled!==false);
const pOnViolation=()=>((PDRAFT||{}).onViolation||(POLICY&&POLICY.onViolation)||'deny');
const pDefault=k=>(pKindCfg(PDRAFT,k).default==='deny'?'deny':'allow');
// What a violation DOES, in the words the hook uses. Said next to the control that
// picks it, because "deny" and "warn" are not degrees of the same thing: one
// refuses the call and one lets it through with a sentence attached.
const PVIOL={deny:'refuse the call',ask:'ask for approval, per call',
 warn:'allow it and say so'};
// Where this row's rule is written, for one scope: '' (nothing), 'allow', 'deny'.
// EXACT names only, and deliberately so — a glob that happens to match is not this
// row's rule to move, and silently dropping `code-*` because somebody pressed
// Default on one skill it covers would change the verdict of every other one. A
// pattern is edited where it is written, in the rules table below.
function pRuleOf(block,kind,name,tag){
 const k=pKindCfg(block,kind);
 const src=tag?((k.areas||{})[tag]||{}):k;
 for(const l of ['deny','allow'])if((src[l]||[]).indexOf(name)>=0)return l;
 return '';}
function pSetRule(kind,name,tag,val){
 const b=pBlock(),k=b[kind]=b[kind]||{};
 let src=k;
 if(tag){const a=k.areas=k.areas||{};src=a[tag]=a[tag]||{};}
 ['allow','deny'].forEach(l=>{if(!Array.isArray(src[l]))return;
  const i=src[l].indexOf(name);if(i>=0)src[l].splice(i,1);});
 if(val){src[val]=src[val]||[];src[val].push(name);}
 pPrune();}
function pAddPattern(kind,list,tag,pattern){
 const b=pBlock(),k=b[kind]=b[kind]||{};
 let src=k;
 if(tag){const a=k.areas=k.areas||{};src=a[tag]=a[tag]||{};}
 src[list]=src[list]||[];
 if(src[list].indexOf(pattern)<0)src[list].push(pattern);}
function pDropPattern(kind,list,tag,pattern){
 const src=tag?((pKindCfg(PDRAFT,kind).areas||{})[tag]||{}):pKindCfg(PDRAFT,kind);
 const arr=src[list];if(!Array.isArray(arr))return;
 const i=arr.indexOf(pattern);if(i>=0)arr.splice(i,1);
 pPrune();}
// Emptying a list REMOVES it, and removing the last one removes its container —
// the same convention Settings writes with, for the same reason: a block listing
// every default is a block nobody can read, and `"areas":{"web":{"deny":[]}}` is
// a rule that looks like a rule and is not one.
function pPrune(){
 if(!PDRAFT)return;
 for(const kind of PKINDS){
  const k=PDRAFT[kind];if(!k||typeof k!=='object')continue;
  ['allow','deny'].forEach(l=>{if(Array.isArray(k[l])&&!k[l].length)delete k[l];});
  if(k.areas&&typeof k.areas==='object'){
   for(const tag of Object.keys(k.areas)){const r=k.areas[tag]||{};
    ['allow','deny'].forEach(l=>{if(Array.isArray(r[l])&&!r[l].length)delete r[l];});
    if(!Object.keys(r).length)delete k.areas[tag];}
   if(!Object.keys(k.areas).length)delete k.areas;}
  if(!Object.keys(k).length)delete PDRAFT[kind];}}
// The change rows, computed the same way Settings computes its own: this block is
// one key of the config, the server writes it through the one config writer, and
// the echo comes back as `config · policy.skills.deny · … -> …`. So the dialog is
// fed a whole config with this block swapped in, and cannot describe the save in a
// vocabulary the server does not answer in.
function policyChanges(){
 if(PDRAFT===null)return [];
 const cfg=JSON.parse(JSON.stringify(STATE.config||{}));
 cfg.policy=PDRAFT;
 return configChanges(cfg);}
// Every pattern in the draft, in the order `resolve` reads them: deny before
// allow, project before area. Annotated from the server's own matching where the
// server has seen the pattern — a rule typed a second ago has no match count and
// says so rather than borrowing the count of the one it replaced.
function pDraftRules(kind){
 const out=[],k=pKindCfg(PDRAFT,kind);
 const push=(scope,list)=>{const src=scope?((k.areas||{})[scope]||{}):k;
  (src[list]||[]).forEach(p=>out.push({scope:scope||null,list:list,pattern:p}));};
 push(null,'deny');push(null,'allow');
 Object.keys(k.areas||{}).sort().forEach(tag=>{push(tag,'deny');push(tag,'allow');});
 return out;}
const pRuleKey=r=>JSON.stringify([r.scope||null,r.list,r.pattern]);
function pServerRules(kind){const m={};
 ((POLICY.rules||{})[kind]||[]).forEach(r=>{m[pRuleKey(r)]=r;});return m;}

function renderPolicy(){
 const c=$('#policy');
 // The whole view redraws on every switch, so put back the two things a redraw
 // throws away: the caret in whichever box was being typed in, and how far down
 // the capability table the reader had scrolled.
 const act=document.activeElement,
   keepId=act&&act.id&&(act.id==='polq'||act.id==='poladdpat')?act.id:null,
   caret=keepId?act.selectionStart:0,
   scrolled=(()=>{const w=$('#poltbl');return w?w.scrollTop:0;})();
 c.textContent='';
 if(!POLICY){c.append(el('div',{class:'card'},el('div',{class:'findings warn'},
   'The capability policy could not be read from this project. Nothing here can be '
   +'edited until it can.')));return;}
 EDITS.policy=()=>policyChanges();
 const pending=policyChanges();
 const findings=el('div',{class:'findings-slot'});
 if(PNOTE){findings.append(...PNOTE);PNOTE=null;}

 // --- what is in force, and whether anything is enforcing it ------------------
 const head=el('div',{class:'card',id:'polhead'});
 head.append(h2h('Capability policy','Which skills, subagents and MCP tools may be '
   +'used in this project. Every verdict below is computed by _policy.resolve — the '
   +'same function guard-capabilities calls — and never by this page.'));
 const active=POLICY.active,en=pEnabled();
 if(!en)head.append(el('div',{class:'findings warn','data-pstate':'off'},
   'Turned off. policy.enabled is false, so nothing below is enforced — the rules '
   +'stay written down and decide nothing.'));
 else if(!active)head.append(el('div',{class:'findings ok','data-pstate':'inert'},
   'Inert — every kind defaults to allow and no deny list has an entry, so there is '
   +'nothing this policy can refuse. That is how it ships.'));
 else if(POLICY.enforcement&&POLICY.enforcement.seen)
  head.append(el('div',{class:'findings ok','data-pstate':'enforced'},
   'Active, and the guard has run in this project — last seen '
   +pAgo(POLICY.enforcement.ageDays)+'.'));
 else head.append(el('div',{class:'findings warn','data-pstate':'unproven'},
   'Active, but nothing here has ever seen the guard run in this project. On some '
   +'Claude Code versions Skill / Task / MCP calls are not dispatched to plugin '
   +'hooks at all, and inside a subagent they may not be inherited '
   +'(anthropics/claude-code#43772). Until the marker appears, treat these verdicts '
   +'as documentation rather than enforcement — /audit:doctor says the same.'));
 // The saved state above describes the FILE, not the form. Say so the moment the
 // two differ, or a reader edits a switch, reads "inert" underneath it and
 // concludes the switch did nothing.
 if(pending.length)head.append(el('div',{class:'findings warn','data-ppend':'1'},
   'Described above: the policy as SAVED. You have '+pending.length+' unsaved '
   +'change'+(pending.length===1?'':'s')+' — verdicts are re-read from the server '
   +'once they are written.'));
 (POLICY.findings||[]).forEach(f=>head.append(
   el('div',{class:'findings err','data-pfinding':'1'},'✗ '+f)));
 (POLICY.warnings||[]).forEach(w=>head.append(el('div',{class:'findings warn'},'! '+w)));
 const enb=el('input',{type:'checkbox',id:'polenabled'});enb.checked=en;
 enb.onchange=()=>pEdit(()=>{const b=pBlock();
   if(enb.checked)delete b.enabled;else b.enabled=false;pPrune();});
 const ovSel=el('select',{id:'polonviol','aria-label':'what a violation does'});
 (POLICY.onViolationChoices||['deny']).forEach(v=>{
   const o=el('option',{value:v},v+' — '+(PVIOL[v]||''));
   if(pOnViolation()===v)o.selected=true;ovSel.append(o);});
 // Back to the shipped default is written by REMOVING the key, unless the file
 // states it — a block that spells out every default is a block nobody can read,
 // and this one is meant to be read in a pull request.
 ovSel.onchange=()=>pEdit(()=>{const b=pBlock();
   if(ovSel.value===(POLICY.onViolation||'deny')&&!(POLICY.stored||{}).onViolation)
    delete b.onViolation;
   else b.onViolation=ovSel.value;
   pPrune();});
 head.append(el('div',{class:'row'},
   el('label',{class:'f cbf'},enb,flabel('Policy enabled',
     'Off writes policy.enabled:false, which is how you keep the rules and stop '
     +'applying them.')),
   el('label',{class:'f'},flabel('On a violation','What the hook does when a call '
     +'breaks a rule. warn is deliberately NOT a permission grant — it lets the '
     +'call through and says so.'),ovSel)));
 // Which area rules are deciding anything TODAY. An area rule applies only while
 // some phase in that area has work in progress, so a column of denials for a
 // dormant area is inert — and becomes live the moment that phase starts, which is
 // the surprise this line exists to remove.
 const live=(POLICY.activeAreas||[]),
   dormant=(POLICY.areaInfo||[]).filter(a=>!a.active).map(a=>a.tag);
 if(dormant.length||live.length)head.append(el('div',{class:'mut','data-pdormant':'1'},
   'Area rules apply only while that area has work in progress. Live now: '
   +(live.join(', ')||'none')
   +(dormant.length?(' · dormant: '+dormant.join(', ')):'')));
 head.append(pHonesty());
 c.append(head);

 // --- one kind at a time ------------------------------------------------------
 const card=el('div',{class:'card'});
 const kstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Kind'));
 PKINDS.forEach(k=>kstrip.append(el('button',{class:'ovpill',type:'button','data-pk':k,
   'aria-pressed':PF.kind===k?'true':'false',
   title:'the '+PKLABEL[k].toLowerCase()+' this project can reach',
   onclick:()=>{PF.kind=k;PF.q='';PNOTE=null;renderPolicy();}},
   PKLABEL[k],el('b',{},String(((POLICY.resolved||{})[k]||[]).length)))));
 card.append(kstrip);
 const kind=PF.kind,rows=((POLICY.resolved||{})[kind]||[]);
 const dstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Everything else'),
   ['allow','deny'].map(v=>el('button',{class:'ovpill'+(v==='deny'?' hi':''),
     type:'button','data-pdefault':v,'aria-pressed':pDefault(kind)===v?'true':'false',
     title:v==='deny'
       ?'nothing runs unless a rule allows it — including anything installed later'
       :'everything not denied is allowed',
     onclick:()=>pEdit(()=>{const b=pBlock(),k=b[kind]=b[kind]||{};
       if(v==='deny')k.default='deny';else delete k.default;pPrune();})},v)));
 card.append(dstrip);
 card.append(el('p',{class:'blurb'},pDefault(kind)==='deny'
   ?('Default deny for '+PKLABEL[kind].toLowerCase()+': nothing runs unless it is '
     +'allowed below, and anything installed after today starts refused.')
   :('Default allow for '+PKLABEL[kind].toLowerCase()+': a deny rule is the only '
     +'thing that can refuse anything. An allow rule here has no effect at all, '
     +'which is what the validator warns about.')));
 if(kind==='mcp')card.append(el('p',{class:'blurb'},'What is discoverable is a '
   +'SERVER; a policy matches whole tool names. Each row therefore stands in for '
   +'the server as mcp__<server>__* — a rule aimed at one tool of that server will '
   +'not move it, which is true and better said than quietly averaged.'));

 // --- the capability table ----------------------------------------------------
 const q=PF.q.trim().toLowerCase();
 const shown=rows.filter(r=>(!q||(r.name+' '+(r.source||'')).toLowerCase().includes(q))
   &&(!PF.bad||r.verdict==='violation'));
 const qIn=el('input',{type:'search',id:'polq',value:PF.q,
   placeholder:'search '+PKLABEL[kind].toLowerCase()+'…',
   'aria-label':'search '+PKLABEL[kind].toLowerCase()});
 qIn.addEventListener('input',()=>{PF.q=qIn.value;renderPolicy();});
 const bad=el('input',{type:'checkbox',id:'polbad'});bad.checked=PF.bad;
 bad.onchange=()=>{PF.bad=bad.checked;renderPolicy();};
 const tools=el('div',{class:'ovtools'},qIn,
   el('label',{class:'inl',for:'polbad'},bad,'violations only'),
   el('span',{class:'count',style:'margin-left:auto'},
     shown.length===rows.length?(rows.length+' discovered')
       :(shown.length+' / '+rows.length)));
 if(q||PF.bad)tools.append(el('button',{class:'btn small',type:'button',
   'data-polclear':'1',onclick:()=>{PF.q='';PF.bad=false;renderPolicy();}},
   'Clear filters'));
 card.append(tools);
 const cols=POLICY.areaInfo||[];
 const head2=el('tr',{},el('th',{},'capability'),el('th',{},'source'),
   el('th',{},'rule'),
   cols.map(a=>el('th',{class:'ar'+(a.active?'':' dormant'),
     title:a.active
       ?('area '+a.tag+' has work in progress, so its rules apply right now')
       :('no phase tagged '+a.tag+' has work in progress, so its rules decide '
         +'nothing until one does')},
     a.tag,el('span',{class:'mut'},a.active?'live':'dormant'))),
   el('th',{},'verdict, and why'));
 const tb=el('tbody');
 shown.forEach(r=>{
  const tr=el('tr',{'data-pcap':r.name,'data-verdict':r.verdict});
  tr.append(el('td',{class:'nm'},r.name,
    r.required?el('span',{class:'badge req',title:'shipped by audit itself — the '
      +'panel refuses to write a policy denying it, and the guard would allow it '
      +'anyway. Not unremovable: disabling the plugin removes it, visibly.'},
      'required'):null,
    r.standIn?el('span',{class:'badge stand',title:'stands in for every tool of '
      +'this server'},'server'):null));
  tr.append(el('td',{},r.source?el('span',{class:'src badge'},r.source):null));
  tr.append(pCell(kind,r,null));
  cols.forEach(a=>tr.append(pCell(kind,r,a.tag)));
  tr.append(el('td',{class:'vd'},
    el('span',{class:'pv '+r.verdict},r.verdict==='violation'?'Violation':'Allowed'),
    el('span',{class:'pbasis'},r.basis||'')));
  tb.append(tr);});
 if(!shown.length)card.append(el('div',{class:'ovempty','data-polempty':'1'},
   rows.length?'No '+PKLABEL[kind].toLowerCase()+' match this filter. '
     :'Nothing of this kind was discovered for this project. A rule can still be '
      +'written for it below — it will apply the day something matches it.',
   rows.length?el('button',{class:'btn small',type:'button','data-polclear':'1',
     onclick:()=>{PF.q='';PF.bad=false;renderPolicy();}},'Clear filters'):null));
 else card.append(el('div',{class:'poltblwrap',id:'poltbl'},
   el('table',{class:'poltbl'},el('thead',{},head2),tb)));

 // --- the block as written ----------------------------------------------------
 card.append(el('h3',{class:'sub2'},flabel('Rules as written',
   'The block for this kind, in the order the guard reads it: deny before allow, '
   +'project before area. The switches above write exact names here; a pattern can '
   +'only be written and removed here.')));
 const srv=pServerRules(kind),drafted=pDraftRules(kind);
 if(!drafted.length)card.append(el('div',{class:'mut','data-polnorules':'1'},
   'No rules for '+PKLABEL[kind].toLowerCase()+'. With the default at '
   +pDefault(kind)+', that means '
   +(pDefault(kind)==='deny'?'nothing of this kind may run.':'everything may run.')));
 else{
  const rtb=el('tbody');
  drafted.forEach(r=>{
   const hit=srv[pRuleKey(r)];
   rtb.append(el('tr',{'data-prule':(r.scope||'project')+' '+r.list+' '+r.pattern},
     el('td',{},r.scope
       ?el('span',{class:'badge area',title:'applies only while this area has work '
         +'in progress'},r.scope)
       :el('span',{class:'mut'},'project')),
     el('td',{class:'lst','data-list':r.list},r.list),
     el('td',{class:'pat'},r.pattern),
     el('td',{class:'mut',title:hit&&hit.matches&&hit.matches.length
       ?hit.matches.join(', ')+(hit.n>hit.matches.length
         ?(' +'+(hit.n-hit.matches.length)+' more'):''):''},
       hit?(hit.n?(hit.n+' installed'):'nothing installed matches it today')
         :'not saved yet'),
     el('td',{},el('button',{class:'btn small',type:'button',
       'aria-label':'remove '+r.list+' rule '+r.pattern,
       onclick:()=>pEdit(()=>pDropPattern(kind,r.list,r.scope,r.pattern))},'×'))));});
  card.append(el('table',{class:'polrules'},
    el('thead',{},el('tr',{},el('th',{},'scope'),el('th',{},'list'),
      el('th',{},'pattern'),el('th',{},'matches now'),el('th',{}))),rtb));}
 card.append(pAddRow(kind));
 c.append(card);

 // --- save --------------------------------------------------------------------
 const save=el('button',{class:'btn primary','data-psave':'1',onclick:async()=>{
   const chg=policyChanges();
   if(!chg.length){toast('nothing to save — the policy is unchanged');return;}
   if(!await confirmChanges({title:'Save capability policy',rows:chg,scope:'policy',
     verb:'Save '+chg.length+' change'+(chg.length===1?'':'s'),
     note:'writes .claude/audit.config.json'}))return;
   const res=await api('PUT','/api/policy',{policy:PDRAFT||{}});
   findings.replaceChildren(findingsBox(res));
   saveOutcome(res,chg,'the config',findings);
   if(!res.ok)return;
   const cfg=JSON.parse(JSON.stringify(STATE.config||{}));
   cfg.policy=PDRAFT||{};STATE.config=cfg;
   // Re-read rather than assume: every verdict on this page is the server's, and
   // the only way they become true of what was just written is to ask again. The
   // box that says what happened is carried across the redraw, not re-derived.
   POLICY=await api('GET','/api/policy').catch(()=>POLICY);
   PDRAFT=pClone(POLICY&&POLICY.stored);
   PNOTE=[...findings.childNodes];
   renderPolicy();
 }},'Save policy');
 const discard=el('button',{class:'btn small','data-discard':'policy',type:'button',
   onclick:async()=>{
   const chg=policyChanges();
   if(!chg.length)return;
   if(!await confirmChanges({title:'Discard unsaved policy changes',rows:chg,danger:1,
     lock:false,verb:'Discard '+chg.length+' change'+(chg.length===1?'':'s'),
     note:'nothing is written; the form goes back to the saved block'}))return;
   pEdit(()=>{PDRAFT=pClone(POLICY&&POLICY.stored);});
   toast('discarded — the form is back to the saved policy');}},
   pending.length?('Discard '+pending.length+' change'+(pending.length===1?'':'s'))
     :'Discard');
 discard.disabled=!pending.length;
 c.append(el('div',{class:'savebar'},save,discard,
   el('span',{class:'mut small'},'writes .claude/audit.config.json'),findings));

 if(keepId){const n=document.getElementById(keepId);
  if(n){n.focus();try{n.setSelectionRange(caret,caret);}catch(e){}}}
 if(scrolled){const w=$('#poltbl');if(w)w.scrollTop=scrolled;}}

// How long ago, in words. The panel never decides whether that is TOO long: how
// stale a marker may be is /audit:doctor's judgement, and a second threshold here
// is a threshold that can disagree with it.
function pAgo(days){
 if(days==null)return 'at an unknown time';
 if(days<1/24)return 'within the hour';
 if(days<1)return 'today';
 return Math.round(days)+' day(s) ago';}

// One switch, for one capability, in one scope.
function pCell(kind,r,tag){
 const cur=pRuleOf(PDRAFT,kind,r.name,tag),
   was=pRuleOf(POLICY.stored,kind,r.name,tag),
   moved=cur!==was;
 const sel=el('select',{class:'prule','data-set':cur||null,
   'data-prule':r.name+(tag?('@'+tag):''),
   'aria-label':(tag?('rule for area '+tag+', '):'project rule for ')+r.name});
 [['','—'],['allow','allow'],['deny','deny']].forEach(([v,t])=>{
  const o=el('option',{value:v},t);if(cur===v)o.selected=true;sel.append(o);});
 if(r.required){
  // The one promise this panel makes about its own components, kept mechanically:
  // the control cannot be moved at all. The server refuses such a policy too — the
  // validator calls it a FINDING — so this is the friendly half of a rule that is
  // enforced somewhere it cannot be edited around.
  sel.disabled=true;
  sel.title='required by audit — the panel refuses to write a policy denying it';}
 else sel.onchange=()=>pEdit(()=>pSetRule(kind,r.name,tag,sel.value));
 return el('td',{class:moved?'pend':null},sel,
   moved?el('span',{class:'badge pend',title:'unsaved: '
     +(was?('was '+was):'no rule')+' → '+(cur||'no rule')},'unsaved'):null);}

// Writing a pattern, which is the half the per-row switches cannot do.
function pAddRow(kind){
 const pat=el('input',{id:'poladdpat',placeholder:'pattern…  e.g.  code-*',
   'aria-label':'pattern to add'});
 const lst=el('select',{'aria-label':'which list'},
   el('option',{value:'deny'},'deny'),el('option',{value:'allow'},'allow'));
 const scope=el('select',{'aria-label':'scope'},el('option',{value:''},'project'),
   (POLICY.areaInfo||[]).map(a=>el('option',{value:a.tag},
     'area '+a.tag+(a.active?'':' (dormant)'))));
 const add=()=>{const p=pat.value.trim();if(!p)return;
   pEdit(()=>{pAddPattern(kind,lst.value,scope.value||null,p);pat.value='';});};
 pat.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();add();}});
 return el('div',{},
   el('div',{class:'poladd'},pat,lst,scope,
     el('button',{class:'btn small',type:'button','data-poladd':'1',onclick:add},
       'Add rule')),
   el('p',{class:'blurb'},'Shell-style globs, matched case-sensitively against the '
     +'whole name: code-* covers code-review and code-simplifier, and matches '
     +'nothing else. Deny beats allow, and one live area’s deny is enough. A '
     +'rule aimed at audit’s own components is refused when you save — with '
     +'the validator’s own words, because it would not take effect.'));}

// The four limits, from SECURITY.md, in the place someone is most likely to
// believe the opposite: a page full of verdicts looks like enforcement. Shut by
// default — read once, remembered — and never removed, because a switchboard that
// does not state them is selling something it cannot deliver.
function pHonesty(){
 const d=el('details',{class:'polhonest','data-polhonest':'1'});
 d.append(el('summary',{},'What this cannot hold — four limits'));
 d.append(el('ol',{},
  el('li',{},el('b',{},'Subagent hooks are not inherited on every version'),
    ' (anthropics/claude-code#43772). Inside a subagent the policy may never be '
    +'consulted. The only local evidence is the marker the guard leaves when it '
    +'runs, which is what the line above reports.'),
  el('li',{},el('b',{},'It denies the tool, not the knowledge.'),
    ' Denying a skill stops the Skill call. It does not unread a document the '
    +'model already has, and it does not stop the same work being done by hand.'),
  el('li',{},el('b',{},'Your own switch outranks it.'),
    ' Anyone can disable a plugin, and a disabled plugin’s hooks do not run — '
    +'which is why audit’s own components are not deniable here. The honest '
    +'claim is not "unremovable", it is "not removable quietly".'),
  el('li',{},el('b',{},'Hooks cannot gate hooks.'),
    ' Another plugin’s hooks run in the same session and nothing here can '
    +'refuse them. This panel inventories what is installed; it never claims to '
    +'enforce against it.')));
 return d;}
// ---------- usage ----------
// ONE filter state. The chart's dimension is DERIVED from it, never stored
// separately -- an earlier version kept a parallel drill-down object and filtered
// author in two places, which let you select one author, click another's line, and
// land in a permanently empty view whose controls said nothing was filtered. With a
// single author slot that state cannot be represented at all.
let USAGE=null;
const UF={model:'',author:'',phase:'',task:'',agent:'',attr:'',day:'',q:'',range:'all'};
const DIMS=['model','author','phase','task','agent','attr','day','q'];
// What a filter is CALLED where it is shown. The internal name is the fact-tuple
// field, which is the right name in the code and the wrong one on a chip: `attr` is
// not a word, and `q` is not a dimension anybody typed.
// `range` is not in DIMS and never wears a chip, but it is a filter a reader can
// be asked about by name, so it is named here with the rest rather than spelled
// out at the one place that asks.
const DLABEL={q:'text',attr:'attributed to',agent:'agent',day:'date',
 range:'time range'};
const fName=d=>DLABEL[d]||d;
const fVal=d=>d==='day'?UF.day.replace('..',' to ')
 :d==='range'?(UF.range==='all'?'all time':'last '+UF.range+' days'):UF[d];
let UORDER=[];                 // dimensions in the order they were set (Esc pops)
let UQT=null;                  // search debounce; the whole tab re-renders per change
const SHOWN={phase:8,model:8,author:8,task:8};   // ranked-list depth; 'other' pages
const F={ts:0,phase:1,task:2,model:3,author:4,agent:5,attr:6,tokens:7,cost:8,msgs:9};
const RISKS=['high','med','low','unrated'];
const TOP=8;
// Token counts are a MAGNITUDE and are always compact - '3.2M', never '3,230,000'.
// dp=2 is for hover: pointing at a bar buys '3.23M', more precision than the label
// without dumping the raw integer. Countables (messages, sessions) are not
// magnitudes and keep their separators - '47,625' is a number you can act on.
// Mirrors _fmt_tokens in render-report.py; the two must agree or one surface will
// quietly disagree with the other about the same number.
const uTok=(n,dp=1)=>{n=n||0;for(const[l,s]of[[1e9,'B'],[1e6,'M'],[1e3,'K']])
 if(Math.abs(n)>=l)return (n/l).toFixed(dp)+s;return String(Math.round(n));};
const uCost=x=>!x?'$0.00':(Math.abs(x)<0.01?'<$0.01':'$'+x.toFixed(2));
const uPct=x=>x==null?'—':x<1&&x>0?'<1%':x.toFixed(0)+'%';
// A share of nothing is not 0% and it is certainly not 100% — it is undefined, and
// the honest rendering of undefined is the same em dash a tile with no series
// already draws. EVERY printed percentage in this tab is computed here, because
// the idiom it replaces — `||1` on the denominator, written to dodge a divide by
// zero — answers a question that has no answer: `100*(1-0)/1` made the
// `attributed` tile read 100% over an empty selection, beside three honest zeros,
// on the one tile of the four that is coloured by polarity. A denominator may
// still carry `||1` where the quotient is a bar WIDTH or a sparkline's range —
// a scale is a drawing decision, not a claim — and nowhere else.
const uShare=(part,whole)=>whole?100*part/whole:null;

// Colour follows the entity, never its rank in the current view: a slot comes from
// the entity's spend rank across the WHOLE ledger, so filtering cannot repaint a
// series that already had a colour. Model colours live in their own map so a model
// keeps one identity whether the chart is showing authors or models.
//
// Past the 8 validated hues there is no stable map left to preserve — forty people
// cannot each keep a distinct colour. The earlier rule (sorted name, capped at 8)
// preserved the invariant by handing SEVEN of eight plotted authors the same red,
// which is the one failure a categorical palette cannot survive. So: whoever is in
// the global top 8 keeps their hue under every filter, and anyone else who reaches
// the chart takes a slot the current view leaves free. Survivors never repaint;
// newcomers gain a colour they did not have before.
//
// Models order by NAME, which is the rule render-report.py's _model_slots uses, so
// a model wears the same hue in the report and the panel. Authors order by spend,
// because there is no report chart to agree with and rank is the useful priority
// when only 8 of 40 can be coloured.
let USLOTS={}, MSLOTS={};
function uRanks(field,by){
 if(by==='name'){const o={};
  [...new Set(USAGE.facts.map(f=>f[field]))].sort().forEach((k,i)=>o[k]=i);
  return o;}
 const t={};
 for(const f of USAGE.facts)t[f[field]]=(t[f[field]]||0)+f[F.tokens];
 const o={};Object.keys(t).sort((a,b)=>t[b]-t[a]||(a<b?-1:1))
  .forEach((k,i)=>o[k]=i);return o;}
function uSlots(field,present,by){
 const rank=uRanks(field,by),used=new Set(),out={};
 const keys=[...new Set(present)].filter(k=>k&&k!=='other')
  .sort((a,b)=>(rank[a]==null?1e9:rank[a])-(rank[b]==null?1e9:rank[b]));
 for(const k of keys){const r=rank[k];
  if(r!=null&&r<8&&!used.has(r+1)){out[k]=r+1;used.add(r+1);}}
 let free=1;
 for(const k of keys){if(out[k])continue;
  while(free<=8&&used.has(free))free++;
  if(free<=8){out[k]=free;used.add(free);}}
 return out;}
function uCol(k){return USLOTS[k]?'var(--viz-'+USLOTS[k]+')':'var(--bar-neutral)';}
function uMCol(k){return MSLOTS[k]?'var(--viz-'+MSLOTS[k]+')':'var(--bar-neutral)';}

function setF(dim,val){
 UF[dim]=val||'';
 UORDER=UORDER.filter(d=>d!==dim);
 if(UF[dim])UORDER.push(dim);
 if(dim!=='day')SHOWN[dim]=TOP;      // a new scope starts from the top again
 renderUsage();}
function clearAll(){DIMS.forEach(d=>UF[d]='');UF.range='all';UORDER=[];
 DIMS.forEach(d=>{if(d in SHOWN)SHOWN[d]=TOP;});renderUsage();}

// Chart dimension is DERIVED: scoping to one author makes the interesting split
// their models. Nothing stores "which level am I on".
function chartDim(){return UF.author?'model':'author';}

// The text index behind the free-text box: everything about a row that a person
// could plausibly type, including the phase and task TITLES, which is what makes
// "checkout" find the work rather than only the id you would have to know already.
// Built once per fact and cached on the row, so the second keystroke rebuilds
// nothing across 20000 of them.
function uHay(f){
 if(f.h===undefined)f.h=[f[F.phase],f[F.task],f[F.model],f[F.author],f[F.agent],
   f[F.attr],(USAGE.phaseTitles||{})[f[F.phase]]||'',
   ((USAGE.taskMeta||{})[f[F.task]]||{}).title||''].join(' ').toLowerCase();
 return f.h;}

// Every filter EXCEPT the date window, in one place. uFiltered() applies it to the
// window on screen and uDelta() applies it to the window before, and a dimension
// that existed in only one of them would compare two different populations while
// the chip said "vs prior 30d". The delta used to re-list its dimensions inline,
// which is a copy that goes stale the moment a filter is added — as three were
// here.
function uMatch(f){
 return (!UF.model||f[F.model]===UF.model)
  &&(!UF.author||f[F.author]===UF.author)
  &&(!UF.phase||f[F.phase]===UF.phase)
  &&(!UF.task||f[F.task]===UF.task)
  &&(!UF.agent||f[F.agent]===UF.agent)
  &&(!UF.attr||f[F.attr]===UF.attr)
  &&(!UF.q||uHay(f).includes(UF.q.trim().toLowerCase()));}

function uFiltered(){if(!USAGE)return[];let out=USAGE.facts.filter(uMatch);
 if(UF.day){const[a,b]=UF.day.split('..');
  out=b?out.filter(f=>{const d=f[F.ts].slice(0,10);return d>=a&&d<=b;})
       :out.filter(f=>f[F.ts].slice(0,10)===a);}
 if(UF.range!=='all'){const d=new Date(Date.now()-parseInt(UF.range,10)*864e5)
   .toISOString().slice(0,10);out=out.filter(f=>f[F.ts].slice(0,10)>=d);}
 return out;}
const uAnyFilter=()=>UORDER.length>0||UF.range!=='all';

// Why the view is empty. "No rows match these filters" spread over eight controls
// is a puzzle, and one of the ways to empty this tab cannot be worked out from the
// screen at all: a range preset counts back from TODAY, so on a ledger whose last
// row is older than the window it selects nothing — which is the normal state of a
// FINISHED plan, and exactly when someone opens this tab to ask what it cost. That
// case is named outright, with both dates, because the reader's own conclusion
// would otherwise be that the metering never ran.
//
// The presets are deliberately NOT re-anchored on the data to make this go away: a
// control labelled "last 30 days" whose behaviour means "the last 30 days there
// happens to be data for" is a quieter defect than an empty result, and the label
// is what makes it one. (The report answers the neighbouring question differently
// and correctly — its presets measure back from the plan's own last day, and its
// labels say so.) An empty result that explains itself is the right answer here.
//
// Every count comes from uFiltered() with one slot temporarily blank — the same
// predicate the view itself runs. A second implementation of "what matches" is how
// an explanation ends up disagreeing with the thing it is explaining.
function uEmptyWhy(){
 const C=USAGE.counts||{};
 const toAll=()=>{UF.range='all';renderUsage();};
 if(UF.range!=='all'){
  const cut=new Date(Date.now()-parseInt(UF.range,10)*864e5)
    .toISOString().slice(0,10);
  if(C.to&&C.to<cut)return{why:'range-after-ledger',
   text:'The last '+UF.range+' days begin '+cut+', and the ledger ends '+C.to+
     ' — it stops before this window. Range presets count back from today, not '+
     'from the last day recorded.',
   fix:{key:'range',label:'Show all time',run:toAll}};}
 // Which single filter is doing it. Naming one and lifting one is the answer to a
 // question "clear filters" cannot answer: it throws away every filter that was
 // fine, so the reader learns nothing and has to rebuild the view to find out.
 for(const d of UORDER.concat(UF.range==='all'?[]:['range'])){
  const keep=UF[d];UF[d]=d==='range'?'all':'';
  const n=uFiltered().length;UF[d]=keep;
  if(!n)continue;
  return{why:d,
   text:'No rows match. It is the '+fName(d)+' filter ('+fVal(d)+') doing it: '+
     n+' row(s) match everything else.',
   fix:{key:d,label:d==='range'?'Show all time':'Remove the '+fName(d)+' filter',
     run:d==='range'?toAll:()=>setF(d,'')}};}
 return{why:'combination',
  text:'No rows match these filters, and no single one of them explains it — it '+
    'is the combination that selects nothing.'};}

// The from/to pair writes the SAME `UF.day` grammar the chart's click writes — one
// ISO day, or 'from..to' for a span — so a date typed here and a bin clicked there
// produce one filter, one chip and one way out. The pair also READS it, which is
// what keeps the two inputs showing the window a chart click just applied.
//
// Half a pair is completed from the LEDGER's own ends, never from today:
// "everything from 1 April" on a ledger that stopped in May means April to May, and
// completing it with the wall clock would silently widen the window past the data
// every day the project sits idle.
function uDayPair(){const[a,b]=(UF.day||'').split('..');return [a||'',b||a||''];}
function uSetDays(from,to){const C=USAGE.counts||{};
 const a=from||C.from||'',b=to||C.to||'';
 setF('day',(a||b)?(a===b?a:a+'..'+b):'');}

function uAgg(facts,key){const m=new Map();
 for(const f of facts){const k=f[F[key]]||'--';const s=m.get(k)||[0,0,0];
  s[0]+=f[F.tokens];s[1]+=f[F.cost];s[2]+=f[F.msgs];m.set(k,s);}
 return [...m.entries()].sort((a,b)=>b[1][0]-a[1][0]);}

// --- shared tooltip -------------------------------------------------------------
// One element, moved on hover. Compact by design: enough to stop you estimating
// against an axis, short enough to read without moving your eyes.
let TIP=null;
function tipEl(){if(!TIP){TIP=el('div',{class:'utip hidden'});document.body.append(TIP);}return TIP;}
function tipShow(ev,nodes){const t=tipEl();t.textContent='';
 (Array.isArray(nodes)?nodes:[nodes]).forEach(n=>t.append(n));
 t.classList.remove('hidden');tipMove(ev);}
function tipMove(ev){const t=tipEl(),pad=14,r=t.getBoundingClientRect();
 let x=ev.clientX+pad,y=ev.clientY+pad;
 if(x+r.width>innerWidth-8)x=ev.clientX-r.width-pad;
 if(y+r.height>innerHeight-8)y=ev.clientY-r.height-pad;
 t.style.left=Math.max(4,x)+'px';t.style.top=Math.max(4,y)+'px';}
function tipHide(){if(TIP)TIP.classList.add('hidden');}
function tipRow(colour,label,value){return el('div',{class:'utip-r'},
 colour?el('i',{style:'background:'+colour}):null,
 el('span',{class:'utip-k'},label),el('span',{class:'utip-v'},value));}
function bindTip(node,build){
 node.addEventListener('mouseenter',e=>tipShow(e,build()));
 node.addEventListener('mousemove',tipMove);
 node.addEventListener('mouseleave',tipHide);
 return node;}

// --- multi-line chart with crosshair --------------------------------------------
// Eight series over nine months of daily points is spaghetti: 250 marks across
// 680px is 2.7px per day, so what the eye gets is noise with a trend hidden in it.
// Past MAXPTS the days roll up into natural bins - week, four weeks, quarter -
// chosen as the smallest that fits, and the chart SAYS which one it used. Binning
// silently would be worse than the spaghetti: the reader would take a weekly total
// for a daily one.
const MAXPTS=60, LADDER=[1,7,28,91,364];
const BINNAME={1:'day',7:'week',28:'4 weeks',91:'quarter',364:'year'};
const dnum=d=>Date.UTC(+d.slice(0,4),+d.slice(5,7)-1,+d.slice(8,10))/864e5;
function uBin(days){
 if(days.length<2)return{size:1,bins:days.map(d=>[d,d])};
 const span=dnum(days[days.length-1])-dnum(days[0])+1;
 const size=LADDER.find(s=>Math.ceil(span/s)<=MAXPTS)||LADDER[LADDER.length-1];
 if(size===1)return{size:1,bins:days.map(d=>[d,d])};
 const start=dnum(days[0]),iso=n=>new Date(n*864e5).toISOString().slice(0,10);
 const bins=[];
 for(let a=0;a<span;a+=size)
  bins.push([iso(start+a),iso(start+Math.min(a+size,span)-1)]);
 return{size,bins};}
// Which bin a day falls in. Extracted because the sparklines bin the same days by
// the same ladder: two binary searches over one bin list is two chances for the
// chart and the tile above it to draw the same span at different resolutions.
function binAt(bins){return d=>{const n=dnum(d);let lo=0,hi=bins.length-1;
  while(lo<hi){const mid=(lo+hi+1)>>1;dnum(bins[mid][0])<=n?lo=mid:hi=mid-1;}
  return lo;};}

function uSeries(facts,dim){const per=new Map(),days=new Set();
 for(const f of facts){const d=f[F.ts].slice(0,10),k=f[F[dim]]||'--';
  days.add(d);const m=per.get(k)||new Map();
  m.set(d,(m.get(d)||0)+f[F.tokens]);per.set(k,m);}
 const ds=[...days].sort(),{size,bins}=uBin(ds);
 const at=binAt(bins);
 const idx=new Map(ds.map(d=>[d,at(d)]));
 const roll=m=>{const v=new Array(bins.length).fill(0);
  for(const[d,n]of m)v[idx.get(d)]+=n;return v;};
 let ent=[...per.entries()].map(([k,m])=>({key:k,
   total:[...m.values()].reduce((a,b)=>a+b,0),values:roll(m)}))
  .sort((a,b)=>b.total-a.total);
 if(ent.length>TOP){const tail=ent.slice(TOP);ent=ent.slice(0,TOP);
  ent.push({key:'other',total:tail.reduce((a,e)=>a+e.total,0),
    values:bins.map((_,i)=>tail.reduce((a,e)=>a+e.values[i],0))});}
 return {buckets:bins.map(b=>b[0]),bins:bins,binSize:size,entities:ent};}
// A bin is one filter value: an exact day, or "from..to" for a rolled-up range.
const binKey=b=>b[0]===b[1]?b[0]:b[0]+'..'+b[1];
const binLabel=b=>b[0]===b[1]?b[0]:b[0]+' to '+b[1];
const NS='http://www.w3.org/2000/svg';
const svgEl=(t,a)=>{const e=document.createElementNS(NS,t);
 for(const k in a)e.setAttribute(k,a[k]);return e;};
// W comes from measuring the container, and the viewBox is built at that exact
// pixel size, so the scale is 1:1 in both axes. It used to be a fixed 680 stretched
// to fit with preserveAspectRatio="none" - which scales the coordinate system
// non-uniformly and therefore scales the GLYPHS: at 942px the axis labels rendered
// 38% too wide, the 2px lines drew 2.8px on vertical runs and 2px on horizontal
// ones, and the end-of-series circles were ellipses. Rendering 1:1 fixes all four
// at once, which no amount of tuning inside a stretched space can.
function uChart(sr,dim,W){
 const H=190,PL=44,PB=20,PT=10;
 if(!sr.buckets.length)return el('div',{class:'mut'},'No data in this window.');
 const peak=Math.max(1,...sr.entities.flatMap(e=>e.values));
 const n=sr.buckets.length, iw=W-PL-6, ih=H-PB-PT;
 const X=i=>PL+(n<2?iw/2:iw*i/(n-1)), Y=v=>PT+ih-ih*v/peak;
 const svg=svgEl('svg',{class:'uchart',viewBox:'0 0 '+W+' '+H,role:'img',
   'aria-label':'Tokens per '+(sr.binSize===1?'day':BINNAME[sr.binSize])
     +', peak '+uTok(peak)+'. Click to filter to one.'});
 [0,0.5,1].forEach(fr=>{const y=PT+ih*fr;
  svg.appendChild(svgEl('line',{class:'g',x1:PL,y1:y,x2:W,y2:y}));
  const t=svgEl('text',{class:'ax',x:0,y:y+3});t.textContent=uTok(peak*(1-fr));
  svg.appendChild(t);});
 const cross=svgEl('line',{class:'cross hidden',y1:PT,y2:PT+ih});
 svg.appendChild(cross);
 sr.entities.forEach(e=>{
  const d=e.values.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)).join('');
  svg.appendChild(svgEl('path',{class:'ln',d:d,stroke:uCol(e.key)}));
  // A 2px line is a poor click target, and clicking a LINE (that series) has to stay
  // distinct from clicking the plot (that day). A wider transparent companion path
  // gives the series a comfortable hit area; the click stops there so it never also
  // registers as a day selection.
  if(e.key!=='other'){
   const hit=svgEl('path',{class:'lnhit',d:d});
   hit.addEventListener('click',ev=>{ev.stopPropagation();
     setF(dim,UF[dim]===e.key?'':e.key);});
   const ttl=svgEl('title',{});ttl.textContent='Click to scope to '+e.key;
   hit.appendChild(ttl);
   svg.appendChild(hit);}
  const li=e.values.length-1;
  svg.appendChild(svgEl('circle',{class:'dot',cx:X(li),cy:Y(e.values[li]),r:3.5,
    fill:uCol(e.key)}));});
 [0,n-1].forEach(i=>{if(n<2&&i)return;const t=svgEl('text',{class:'ax',x:X(i),y:H-4,
   'text-anchor':i?'end':'start'});t.textContent=sr.buckets[i].slice(5);
  svg.appendChild(t);});
 // Crosshair: nearest bucket to the cursor, one tooltip row per series.
 const idxAt=ev=>{const r=svg.getBoundingClientRect();
  const rel=(ev.clientX-r.left)/r.width*W;
  return Math.max(0,Math.min(n-1,Math.round((rel-PL)/(n<2?1:iw/(n-1)))));};
 svg.addEventListener('mousemove',ev=>{const i=idxAt(ev);
  cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));
  cross.classList.remove('hidden');
  const rows=[el('div',{class:'utip-h'},binLabel(sr.bins[i]))];
  sr.entities.filter(e=>e.values[i]).sort((a,b)=>b.values[i]-a.values[i])
   .forEach(e=>rows.push(tipRow(uCol(e.key),e.key,uTok(e.values[i]))));
  if(rows.length===1)rows.push(el('div',{class:'utip-r mut'},'no usage'));
  rows.push(el('div',{class:'utip-f'},'click to filter to this '
    +(sr.binSize===1?'day':BINNAME[sr.binSize])));
  tipShow(ev,rows);});
 svg.addEventListener('mouseleave',()=>{cross.classList.add('hidden');tipHide();});
 svg.addEventListener('click',ev=>setF('day',binKey(sr.bins[idxAt(ev)])));
 svg.classList.add('pick');
 return svg;}

// The chart is built at the container's true pixel width, and the container is not
// in the DOM while renderUsage() is assembling the card - so the first measurement
// can be 0. Draw once, measure again on the next frame, and re-draw on resize. The
// width guard makes every one of those a no-op unless the width actually moved.
function mountChart(sr,dim){
 const host=el('div',{class:'chartslot'});
 const draw=()=>{const w=Math.round(host.clientWidth);
  if(!w||w===host.__w)return;
  host.__w=w;host.replaceChildren(uChart(sr,dim,w));};
 requestAnimationFrame(()=>{draw();
  if(window.ResizeObserver&&!host.__ro){
   host.__ro=new ResizeObserver(()=>draw());host.__ro.observe(host);}});
 return host;}

// --- sparklines ------------------------------------------------------------------
// A KPI tile is one number, and one number cannot say whether it is the top of a
// climb or the bottom of one. The spark is that shape and nothing else: no axis, no
// labels, no interaction — everything needed to read it precisely is in the chart
// directly below, and a tile that tried to be a chart would be a worse one.
//
// Drawn at its intrinsic pixel size, NOT stretched to the tile, for the reason the
// main chart is drawn 1:1: a viewBox scaled non-uniformly scales the strokes with
// it, and at this size a 1.4px line becoming 2px on the verticals is the whole
// drawing. It bins by the same ladder the chart uses (via uBin/binAt), so the tile
// and the chart under it can never be showing two different resolutions, and the
// period it settled on is named in the tile's own tooltip rather than left implied.
const SPW=76,SPH=20;
function uDaily(facts){
 const per=new Map();
 for(const f of facts){const d=f[F.ts].slice(0,10);
  const s=per.get(d)||[0,0,0,0];      // tokens, cost, msgs, unattributed tokens
  s[0]+=f[F.tokens];s[1]+=f[F.cost];s[2]+=f[F.msgs];
  if(f[F.attr]==='unattributed')s[3]+=f[F.tokens];
  per.set(d,s);}
 const ds=[...per.keys()].sort();
 if(!ds.length)return{period:'day',series:{}};
 const{size,bins}=uBin(ds),at=binAt(bins);
 const acc=bins.map(()=>[0,0,0,0]);
 for(const[d,s]of per){const i=at(d);for(let k=0;k<4;k++)acc[i][k]+=s[k];}
 return{period:size===1?'day':BINNAME[size],
   series:{tokens:acc.map(v=>v[0]),cost:acc.map(v=>v[1]),msgs:acc.map(v=>v[2]),
     // A bucket with no tokens has no coverage to report; carrying 0% would draw a
     // cliff to the floor on a quiet day and call it a collapse in attribution.
     attributed:acc.map(v=>v[0]?100*(v[0]-v[3])/v[0]:null)}};}

// `zero` is not decoration, it is the claim the drawing makes. A magnitude is
// measured from nothing, so its baseline is 0 and the area under it means the
// quantity. A SHARE is not: attribution moving 96% -> 99% against a 0..100 axis is
// three pixels of a solid block, which is a sparkline that says nothing while
// looking like it says something. A share is therefore scaled to its own range and
// drawn as a line alone — no area, because there is no zero for the area to be
// measured from, and a filled shape would invite exactly that reading.
function uSpark(vals,label,zero){
 // Two points make a line; one makes a claim about a trend from a single sample.
 // Nulls are gaps (a bucket with no tokens has no share to report) and are dropped
 // rather than plotted as zero, which would draw a cliff on a quiet day.
 const v=(vals||[]).filter(x=>x!=null);
 if(v.length<2)return null;
 const hi=Math.max(...v),lo=zero?Math.min(0,Math.min(...v)):Math.min(...v);
 const rng=(hi-lo)||1;
 const X=i=>SPW*i/(v.length-1),Y=x=>1.5+(SPH-3)*(1-(x-lo)/rng);
 const d=v.map((x,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(x).toFixed(1)).join('');
 const svg=svgEl('svg',{class:'uspark',width:SPW,height:SPH,
   viewBox:'0 0 '+SPW+' '+SPH,role:'img','aria-label':label});
 if(zero)svg.appendChild(svgEl('path',{class:'sa',
   d:d+'L'+SPW.toFixed(1)+' '+SPH+'L0 '+SPH+'Z'}));
 svg.appendChild(svgEl('path',{class:'sl',d:d}));
 svg.appendChild(svgEl('circle',{class:'sd',cx:SPW,cy:Y(v[v.length-1]).toFixed(1),
   r:1.7}));
 return svg;}

// --- metrics, all recomputed under the current filter --------------------------
function uCoverage(facts){const by={},tot=facts.reduce((a,f)=>a+f[F.tokens],0);
 for(const f of facts)by[f[F.attr]]=(by[f[F.attr]]||0)+f[F.tokens];
 const un=by['unattributed']||0;
 return {attributed:uShare(tot-un,tot),task:uShare(by['task']||0,tot),by,tot};}
function uUnit(facts){const M=USAGE.taskMeta||{},cost={};
 for(const f of facts){const t=f[F.task];if(t&&t!=='--')cost[t]=(cost[t]||0)+f[F.cost];}
 const done=Object.keys(cost).filter(t=>(M[t]||{}).status==='done').map(t=>cost[t]);
 const remaining=Object.keys(M).filter(t=>['pending','in_progress','blocked']
   .includes((M[t]||{}).status)).length;
 const out={completed:done.length,remaining,gate:5,perTask:null,proj:null};
 if(done.length)out.perTask=done.reduce((a,b)=>a+b,0)/done.length;
 // Same gate as the report: a forecast off fewer than 5 samples is noise, so it is
 // suppressed rather than shown with false confidence.
 if(done.length>=5){const s=[...done].sort((a,b)=>a-b),q=p=>s[Math.max(0,
   Math.min(s.length-1,Math.round(p*(s.length-1))))];
  out.proj={low:q(.25)*remaining,high:q(.75)*remaining};}
 return out;}
function uRetry(facts){const M=USAGE.taskMeta||{};let tot=0,re=0,bl=0;
 const rs=new Set(),bs=new Set();
 for(const f of facts){tot+=f[F.cost];const t=M[f[F.task]];if(!t)continue;
  if((t.attempts||1)>1){re+=f[F.cost];rs.add(f[F.task]);}
  if(t.status==='blocked'){bl+=f[F.cost];bs.add(f[F.task]);}}
 return {tot,re,bl,rn:rs.size,bn:bs.size,
   overlap:[...rs].filter(x=>bs.has(x)).length};}
function uRouting(facts){const M=USAGE.taskMeta||{},acc={};
 for(const f of facts){const t=M[f[F.task]];if(!t)continue;
  const risk=t.risk||'unrated',model=f[F.model];
  acc[risk]=acc[risk]||{};
  const c=acc[risk][model]=acc[risk][model]||{cost:0,tasks:new Set(),att:[]};
  c.cost+=f[F.cost];
  if(!c.tasks.has(f[F.task])){c.tasks.add(f[F.task]);c.att.push(t.attempts||1);}}
 const rows=[];
 for(const risk in acc)for(const model in acc[risk]){const c=acc[risk][model];
  rows.push({risk,model,tasks:c.tasks.size,perTask:c.cost/c.tasks.size,
    att:c.att.reduce((a,b)=>a+b,0)/c.att.length});}
 rows.sort((a,b)=>RISKS.indexOf(a.risk)-RISKS.indexOf(b.risk)||
   a.model.localeCompare(b.model));
 return rows;}
// vs the window immediately before this one, same length. Null when there is no
// prior period -- a first-run dashboard must not invent a trend.
//
// "All time" has no window, so it gets one: the last 30 days of the LEDGER against
// the 30 before them, anchored on the last day that has data rather than on the
// wall clock. Anchoring on today would make the default view of a ledger that
// stopped two months ago compare an empty window with an empty window and show no
// trend at all, forever — which is exactly the state a project is in when someone
// opens the panel to ask what it cost.
//
// Both date ranges travel with the number in `basis`, because "+18%" against an
// unnamed period is not a measurement.
function uDelta(facts,days){
 if(!days.length)return null;
 const all=UF.range==='all',span=all?30:parseInt(UF.range,10);
 const iso=n=>new Date(n*864e5).toISOString().slice(0,10);
 const anchor=all?days[days.length-1]:iso(Math.floor(Date.now()/864e5));
 // One boundary convention: the window is [cut, anchor], the one before it is
 // [prevCut, cut). Under a range preset `cut` is the same cut uFiltered() applies,
 // so the "now" side is exactly the rows the tiles are counting and `facts` can be
 // used as-is; under "all time" `facts` is the whole ledger and has to be sliced.
 const cut=iso(dnum(anchor)-span+(all?1:0)),prevCut=iso(dnum(cut)-span);
 const day=f=>f[F.ts].slice(0,10);
 const now=all?facts.filter(f=>day(f)>=cut):facts;
 const base=USAGE.facts.filter(f=>{const d=day(f);
  return d>=prevCut&&d<cut&&uMatch(f);});
 if(!base.length||!now.length)return null;
 const sum=a=>{let t=0,c=0,m=0,un=0;
  for(const f of a){t+=f[F.tokens];c+=f[F.cost];m+=f[F.msgs];
   if(f[F.attr]==='unattributed')un+=f[F.tokens];}
  return{tokens:t,cost:c,msgs:m,attributed:t?100*(t-un)/t:null};};
 const A=sum(now),B=sum(base);
 const pc=(x,y)=>y?100*(x-y)/y:null;
 return {tokens:pc(A.tokens,B.tokens),cost:pc(A.cost,B.cost),
         msgs:pc(A.msgs,B.msgs),
         // A share compared with a share is a difference in POINTS. 90% to 95% is
         // five points, and calling it +5.6% would be a third number nobody asked
         // for and the one a reader would misread as the coverage itself.
         attributed:(A.attributed==null||B.attributed==null)
           ?null:A.attributed-B.attributed,
         label:'vs prior '+span+'d',
         basis:(all?'the ledger’s last '+span+' days':'the last '+span+' days')
           +' ('+cut+' to '+anchor+') against '+prevCut+' to '+iso(dnum(cut)-1)};}

// --- CSV export ------------------------------------------------------------------
// The rows behind the view, as a file, because the questions a spreadsheet is for
// are not the questions a dashboard is for. Numbers go out RAW — no thousands
// separators, no currency symbol, no locale — since the receiver parses them:
// '3,230,000' lands in Excel as text and every sum over the column is then wrong
// and silently so. (The panel's own selftest scans for toLocaleString on the screen
// side for the same reason, one surface up.)
function uCsvText(facts){
 const head=['ts','phase','task','model','author','agent','attr','tokens',
   'costUSD','msgs'];
 // RFC 4180: quote anything containing a comma, a quote or a newline, and double
 // the quotes inside. A task title with a comma in it is not exotic.
 const q=v=>{const s=v==null?'':String(v);
  return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;};
 const out=[head.join(',')];
 for(const f of facts)out.push([f[F.ts],f[F.phase],f[F.task],f[F.model],
   f[F.author],f[F.agent],f[F.attr],f[F.tokens],f[F.cost].toFixed(6),f[F.msgs]]
  .map(q).join(','));
 return out.join('\r\n')+'\r\n';}
function uExport(facts){
 if(!facts.length){toast('nothing to export — no rows match these filters','err');
  return;}
 // The name says what the file IS. These are aggregated buckets, not raw ledger
 // lines, and at 20000 rows the server rolls them from hourly to daily — a file
 // called usage.csv on someone's disk three weeks later cannot be trusted to be
 // either. Span, resolution and whether a filter was applied all go in the name.
 const C=USAGE.counts||{};
 const name='usage-'+(C.from||'start')+'_'+(C.to||'end')+'-'
   +(USAGE.rolled?'daily':'hourly')+(uAnyFilter()?'-filtered':'')+'.csv';
 try{
  // U+FEFF: without a byte-order mark Excel reads a UTF-8 CSV in the local 8-bit
  // codepage and turns every non-ASCII author name into mojibake on open. Written
  // as an escape, never as the character itself — an invisible literal in the
  // source is unreviewable and ungreppable.
  const url=URL.createObjectURL(new Blob(['\ufeff'+uCsvText(facts)],
    {type:'text/csv;charset=utf-8'}));
  const a=el('a',{href:url,download:name});
  document.body.append(a);a.click();a.remove();
  // Revoked late, not immediately: some browsers have not started reading the blob
  // by the time click() returns, and a revoked URL there is a download that fails
  // with no error anywhere.
  setTimeout(()=>URL.revokeObjectURL(url),4000);
  toast(facts.length+' row(s) exported to '+name);
 }catch(e){toast('export failed: '+e,'err');}}

// --- render --------------------------------------------------------------------
function uBars(facts,dim,title){
 const g=uAgg(facts,dim);if(!g.length)return[];
 const grand=g.reduce((a,x)=>a+x[1][0],0);
 const limit=SHOWN[dim]||TOP;
 const head=g.slice(0,limit),tail=g.slice(limit);
 const peak=Math.max(...head.map(x=>x[1][0]))||1;
 const out=[el('h2',{},title)];
 for(const[k,v]of head){
  const meta=USAGE.taskMeta[k]||{};
  const nm=dim==='phase'
    ?(k==='--'?'-- unattributed':(k+' '+(USAGE.phaseTitles[k]||'')).trim())
    :(dim==='task'&&meta.title?(k+' '+meta.title):k);
  const active=UF[dim]===k;
  const row=el('div',{class:'urow pick'+(active?' on':''),
    onclick:()=>setF(dim,active?'':k)},
   el('span',{class:'unm'},nm),
   // Floor the width: a row that spent 0.08% of the peak rounds to 0.0% and
   // paints an empty track, which reads as "no data" rather than "a little".
   el('span',{class:'bar'},el('i',{style:'width:'+
     Math.max(v[0]?0.8:0,100*v[0]/peak).toFixed(1)+'%;'+
     'background:'+(dim==='model'?uMCol(k):'var(--bar-neutral)')})),
   el('span',{class:'uamt'},uTok(v[0])+(USAGE.showCost?' - '+uCost(v[1]):'')));
  bindTip(row,()=>[el('div',{class:'utip-h'},nm),
    tipRow(dim==='model'?uMCol(k):null,'tokens',uTok(v[0],2)),
    tipRow(null,'share',uPct(uShare(v[0],grand))),
    USAGE.showCost?tipRow(null,'cost',uCost(v[1])):null,
    tipRow(null,'messages',v[2].toLocaleString()),
    el('div',{class:'utip-f'},active?'click to clear this filter':'click to filter')
   ].filter(Boolean));
  out.push(row);}
 if(tail.length){
  const more=tail.reduce((a,x)=>[a[0]+x[1][0],a[1]+x[1][1]],[0,0]);
  out.push(el('div',{class:'urow pick tail',
    onclick:()=>{SHOWN[dim]=limit+TOP;renderUsage();}},
   el('span',{class:'unm mut'},'other ('+tail.length+') - show '+
     Math.min(TOP,tail.length)+' more'),
   el('span',{class:'bar'},el('i',{style:'width:'+(100*more[0]/peak).toFixed(1)+
     '%;background:var(--bar-neutral);opacity:.45'})),
   el('span',{class:'uamt'},uTok(more[0])+(USAGE.showCost?' - '+uCost(more[1]):''))));}
 // Expanding costs one click, so collapsing must too. This used to be an `else if`
 // on the tail being empty, which meant the way back only appeared after paging
 // through the whole list - thirty clicks at 233 rows. And paging is the wrong tool
 // for finding one row among hundreds, which is what `browse all` is for.
 const ctl=[];
 if(limit>TOP)ctl.push(el('button',{class:'lnk',
   onclick:()=>{SHOWN[dim]=TOP;renderUsage();}},'show top '+TOP+' only'));
 if(g.length>TOP)ctl.push(el('button',{class:'lnk',
   onclick:()=>openBrowse(dim,title,facts)},'browse all '+g.length+' →'));
 if(ctl.length){
  const bar=el('div',{class:'uctl'});
  ctl.forEach((b,i)=>{if(i)bar.append(el('span',{class:'mut'},'·'));bar.append(b);});
  out.push(bar);}
 return out;}

// --- phase budgets ---------------------------------------------------------------
// Spend against the PLAN rather than the calendar. Rendered only when some phase
// declares a budgetUSD, so it costs nothing in the common case where nobody has.
//
// Unlike the bands, this DOES follow the filter: "what has P1 cost me" is a
// question about the rows you are looking at, and a budget row that ignored an
// author filter while the bar above it obeyed one would be two truths on one
// screen. The caption says which rows it counted.
function uBudgets(facts){
 const B=USAGE.phaseBudgets||{};
 const ids=Object.keys(B);
 if(!ids.length)return [];
 const spent={};
 for(const f of facts){const p=f[F.phase]||'--';
  spent[p]=(spent[p]||0)+f[F.cost];}
 const rows=ids.map(id=>{const used=spent[id]||0,budget=B[id];
   return {id,budget,used,pct:100*used/budget,over:used>budget};})
  .sort((a,b)=>b.pct-a.pct);
 const out=[el('h2',{},'Budget')];
 if(UORDER.length)out.push(el('div',{class:'ucrumb mut'},
   'Counting only the rows the filters above leave in view.'));
 for(const r of rows){
  const nm=(r.id+' '+(USAGE.phaseTitles[r.id]||'')).trim();
  out.push(el('div',{class:'bud'+(r.over?' over':'')},
   el('span',{class:'unm'},nm),
   // The fill stops at the track; the number beside it does not, so an overrun
   // is legible instead of being a bar that looks merely full.
   el('span',{class:'bar'},el('i',{style:'width:'+Math.min(100,r.pct).toFixed(1)+'%'})),
   el('span',{class:'bpct'},r.pct.toFixed(0)+'%'),
   el('span',{class:'uamt'},uCost(r.used)+' of '+uCost(r.budget)
     +(r.over?' · over':''))));}
 const tb=rows.reduce((a,r)=>a+r.budget,0),ts=rows.reduce((a,r)=>a+r.used,0);
 out.push(el('div',{class:'bud total'},
   el('span',{class:'unm mut'},'All budgeted phases'),
   el('span',{class:'bar'}),el('span',{class:'bpct'}),
   el('span',{class:'uamt'},uCost(ts)+' of '+uCost(tb))));
 const missing=Object.keys(USAGE.phaseTitles||{}).filter(p=>!(p in B)).length;
 if(missing)out.push(el('div',{class:'mut small'},
   missing+' phase(s) have no budgetUSD set and are not listed - they are not '
   +'phases at zero.'));
 return out;}

// --- cost bands ------------------------------------------------------------------
// Mirrors cost_bands() in usage_ledger.py; the two must agree or the panel and the
// report will put the same task in different bands. Same gate, same thresholds,
// same fallback when the configured pair is malformed.
//
// Computed from the WHOLE ledger, never from the filtered view: a task is an
// outlier relative to the project, not relative to whatever slice you are looking
// at. Recalibrating per filter would make one of any three tasks an "outlier".
const BAND_GATE=5, BAND_ORDER=['typical','high','outlier'];
let BANDS=null;
function uBandInfo(){
 if(BANDS)return BANDS;
 const cfg=USAGE.bands||{},M=USAGE.taskMeta||{},cost={};
 for(const f of USAGE.facts){const t=f[F.task];
  if(t&&t!=='--'&&M[t])cost[t]=(cost[t]||0)+f[F.cost];}
 let hi=Number(cfg.highUSD),ou=Number(cfg.outlierUSD),basis='absolute',sample=0;
 if(!(isFinite(hi)&&isFinite(ou)&&hi>0&&hi<=ou)){
  const done=Object.keys(cost).filter(t=>(M[t]||{}).status==='done')
    .map(t=>cost[t]).sort((a,b)=>a-b);
  sample=done.length;
  if(done.length<BAND_GATE)
   return (BANDS={basis:null,sufficient:false,byTask:{},sample,gate:BAND_GATE});
  const pct=p=>done[Math.max(0,Math.min(done.length-1,
    Math.round(p/100*(done.length-1))))];
  hi=pct(50);ou=pct(90);basis='relative';}
 const byTask={},counts={typical:0,high:0,outlier:0};
 for(const t in cost){const b=cost[t]>ou?'outlier':cost[t]>hi?'high':'typical';
  byTask[t]=b;counts[b]++;}
 return (BANDS={basis,sufficient:true,high:hi,outlier:ou,byTask,counts,sample,
   gate:BAND_GATE});}
function bandOf(id){const b=uBandInfo();
 return b.sufficient?(b.byTask[id]||null):null;}

// --- browse dialog ---------------------------------------------------------------
// The ranked list is a summary: the top 8 by spend. Paging it eight at a time to
// reach P219 among 241 is 27 clicks and still gives you no way to re-rank by cost.
// This is the other half - search and sort over the whole dimension - and it reads
// from the SAME filtered facts the bars do, so it can never disagree with the page
// behind it. A native <dialog> brings the focus trap, the backdrop and Esc for free.
let BROWSE=null;
// `models` is omitted for the model dimension, where it would restate the row.
const BCOL={
 phase:[['id','id'],['title','title'],['models','models'],['tokens','tokens'],
        ['share','share'],['cost','cost'],['messages','msgs']],
 // `cost` band only on tasks: the band is defined per task, and calling a phase
 // an outlier would be a different claim from the one that was computed.
 task:[['id','id'],['title','title'],['status','status'],['risk','risk'],
       ['models','models'],['cost band','band'],['tokens','tokens'],
       ['share','share'],['cost','cost'],['messages','msgs']],
 model:[['model','id'],['tokens','tokens'],['share','share'],['cost','cost'],
        ['messages','msgs']],
 author:[['author','id'],['models','models'],['tokens','tokens'],['share','share'],
         ['cost','cost'],['messages','msgs']]};
const BNUM={tokens:1,share:1,cost:1,msgs:1};

function browseRows(dim,facts){
 const g=uAgg(facts,dim),grand=g.reduce((a,x)=>a+x[1][0],0);
 // Which models did this phase/task/person actually use? The aggregate throws
 // that away, and it is the question the ranked bar cannot answer: two phases
 // costing the same can be one opus run and one long haiku grind.
 const mix={};
 for(const f of facts){const k=f[F[dim]]||'--',m=f[F.model]||'unknown';
  (mix[k]=mix[k]||{})[m]=(mix[k][m]||0)+f[F.tokens];}
 return g.map(([k,v])=>{const meta=(USAGE.taskMeta||{})[k]||{};
  // Slot order, not token order: the palette was validated on THAT adjacency, so
  // drawing segments in any other sequence puts unvalidated pairs side by side.
  const per=mix[k]||{};
  const models=Object.keys(per).sort((a,b)=>(MSLOTS[a]||99)-(MSLOTS[b]||99))
    .map(m=>({model:m,tokens:per[m],pct:uShare(per[m],v[0])}));
  const top=[...models].sort((a,b)=>b.tokens-a.tokens)[0];
  return {id:k,
    title:dim==='phase'?(k==='--'?'unattributed':(USAGE.phaseTitles[k]||''))
      :dim==='task'?(k==='--'?'unattributed':(meta.title||'')):'',
    status:meta.status||'',risk:meta.risk||'',
    band:(dim==='task'?bandOf(k):null)||'',
    models:models,dominant:top?top.model:'',
    tokens:v[0],share:uShare(v[0],grand),cost:v[1],msgs:v[2]};});}

// A mini stack plus the dominant model NAMED. Identity is never colour alone, and
// at this size the segments are far too small to carry inline labels.
function modelCell(r){
 if(!r.models.length)return el('span',{class:'mut'},'—');
 const bar=el('span',{class:'mstack'});
 r.models.forEach(m=>bar.append(el('i',{style:'flex:'+Math.max(1,m.tokens)+' 0 0;'
   +'background:'+uMCol(m.model)})));
 const cell=el('span',{class:'mcell'},bar,
   el('span',{class:'mdom'},r.dominant.replace(/^claude-/,'')));
 cell.title=r.models.map(m=>m.model+'  '+uPct(m.pct)+'  '+uTok(m.tokens,2))
   .join('\n');
 return cell;}

function openBrowse(dim,title,facts){
 if(!BROWSE){BROWSE=el('dialog',{class:'browse'});
  // Clicking the backdrop is the same intent as Esc. The dialog element itself
  // fills the viewport, so a click whose target IS the dialog landed outside the
  // panel it contains.
  BROWSE.addEventListener('click',ev=>{if(ev.target===BROWSE)BROWSE.close();});
  document.body.append(BROWSE);}
 const rows=browseRows(dim,facts),cols=BCOL[dim]||BCOL.model;
 let sort='tokens',desc=true,q='';
 const head=el('div',{class:'bhead'},
   el('h3',{},title+' — '+rows.length),
   el('button',{class:'bx',title:'close','aria-label':'close',
     onclick:()=>BROWSE.close()},'✕'));
 // "All phases" would be a lie while the page is scoped to one author.
 const within=UORDER.length
   ? el('div',{class:'mut small'},'within: '+UORDER.map(d=>fName(d)+' '+fVal(d))
       .join(' · '))
   : null;
 // State the thresholds, or state why there are none. Either way the reader can
 // check the classification rather than take it on faith.
 const bi=dim==='task'?uBandInfo():null;
 const bandNote=!bi?null:el('div',{class:'mut small'},bi.sufficient
   ? 'cost band: '+(bi.basis==='absolute'
       ? 'configured thresholds'
       : 'this project’s own completed tasks, median/p90')
     +' — typical ≤ '+uCost(bi.high)+' · high ≤ '+uCost(bi.outlier)
     +' · outlier above'
   : ['cost band: not shown — needs '+bi.gate+' completed tasks to calibrate, '
      +'there are '+bi.sample+'. ',
      settingsLink('Set absolute thresholds instead','usage.bands'),
      ' to band by a budget rather than by this project’s own history.']);
 const search=el('input',{type:'search',placeholder:'search '+dim+'…'});
 // An <input type=search> eats the FIRST Escape to clear itself, so the dialog
 // only closed on the second press - which reads as the key being broken. One
 // Escape, one effect: close.
 search.addEventListener('keydown',ev=>{
   if(ev.key==='Escape'){ev.preventDefault();BROWSE.close();}});
 const count=el('span',{class:'count'});
 const tb=el('tbody');
 const thead=el('thead');

 const draw=()=>{
  const needle=q.trim().toLowerCase();
  const shown=rows.filter(r=>!needle
    ||(r.id+' '+r.title).toLowerCase().includes(needle));
  // A mix has no natural order, so the models column sorts by its dominant model.
  shown.sort((a,b)=>{const k=sort==='models'?'dominant':sort;
    const A=a[k],B=b[k];
    const c=BNUM[sort]?A-B:String(A).localeCompare(String(B));
    return desc?-c:c;});
  count.textContent=shown.length+' of '+rows.length;
  thead.replaceChildren(el('tr',{},...cols.map(([lbl,key])=>
    el('th',{class:(BNUM[key]?'n ':'')+'pick'+(sort===key?' on':''),
      onclick:()=>{if(sort===key)desc=!desc;else{sort=key;desc=!!BNUM[key];}draw();}},
     lbl,sort===key?el('span',{class:'sarrow'},desc?'▼':'▲'):null))));
  tb.replaceChildren(...shown.map(r=>{
   const active=UF[dim]===r.id;
   return el('tr',{class:'pick'+(active?' on':''),
     title:active?'click to clear this filter':'click to filter to this '+dim,
     onclick:()=>{setF(dim,active?'':r.id);BROWSE.close();}},
    ...cols.map(([,key])=>el('td',
      {class:BNUM[key]?'n':(key==='title'?'t':''),
       title:key==='title'?String(r.title||''):null},
      key==='models'?modelCell(r)
      // A dot alone would be status-colour-as-meaning; the word carries it.
      :key==='band'?(r.band?el('span',{class:'bandpill b-'+r.band},r.band)
                           :el('span',{class:'mut'},'—'))
      :key==='tokens'?uTok(r.tokens,2)
      // NOT uPct here: across 241 phases every share is under 1%, and a column
      // where every cell reads "<1%" sorts fine and tells you nothing. This is
      // the precision surface, so it gets the digits.
      :key==='share'?(r.share==null?'—'
        :(r.share<1?r.share.toFixed(2):r.share.toFixed(1))+'%')
      :key==='cost'?uCost(r.cost)
      :key==='msgs'?r.msgs.toLocaleString()
      :String(r[key]||'—'))));}));
  if(!shown.length)tb.replaceChildren(el('tr',{},
    el('td',{colspan:String(cols.length),class:'mut'},
      'Nothing matches "'+q.trim()+'".')));};

 search.addEventListener('input',()=>{q=search.value;draw();});
 draw();
 // replaceChildren is the native DOM API, not el(): it STRINGIFIES anything that
 // is not a Node, so passing the null `within` painted the literal text "null"
 // above the dialog. Filter before handing it over.
 BROWSE.replaceChildren(...[head,within,bandNote,
   el('div',{class:'comptools'},search,count),
   el('div',{class:'btblwrap'},el('table',{class:'btbl'},thead,tb)),
   el('div',{class:'mut small bfoot'},
     'click a header to sort · click a row to filter')].filter(Boolean));
 BROWSE.showModal();
 search.focus();}

function renderUsage(){const c=$('#usage');
 // Every filter change repaints this whole tab — and a filter change is exactly
 // what typing in the search box IS. Without this, the third letter of a five
 // letter search goes into a box that no longer exists, and the caret with it.
 const act=document.activeElement,keepQ=!!(act&&act.id==='uq'),
   caret=keepQ?act.selectionStart:0;
 c.textContent='';tipHide();
 const card=el('div',{class:'card'});
 const done=()=>{c.append(card);
  if(keepQ){const n=$('#uq');if(n){n.focus();try{n.setSelectionRange(caret,caret);}catch(e){}}}};
 if(!USAGE||!USAGE.facts.length){
  card.append(USAGE&&!USAGE.enabled
   ?el('div',{class:'mut'},'Token metering is off — ',
     settingsLink('turn it back on in Settings','usage.enabled'),'.')
   :el('div',{class:'mut'},'No usage recorded yet. Metering runs on the '
     +'Stop/SubagentStop hooks; "/audit:usage --backfill" reads transcripts already '
     +'on disk.'),
   el('div',{class:'mut',style:'margin-top:var(--sp-0)'},
     'ledger: '+((USAGE||{}).ledgerDir||'-'),' · ',
     settingsLink('change where it is written','usage.ledgerDir')));
  done();return;}

 // context line: the shape of the ledger, at zero card weight
 const K=USAGE.counts||{};
 const bits=[K.phases+' phases',K.authors+' people',K.models+' models',
   K.sessions+' sessions'];
 if(K.from)bits.push(K.from+' to '+K.to);
 // What the FACTS are bucketed at, which is not what the chart draws at — the
 // chart names its own period in its heading, so this says "ledger" out loud
 // rather than leaving two different resolutions on screen unlabelled.
 bits.push(USAGE.rolled?'daily ledger (rolled up)':'hourly ledger');
 // The rate table behind every dollar in this tab. `pricingAsOf` is served from the
 // MERGED config, so it is set even when this project never chose it — printing it
 // unconditionally would present the default table's date as the project's own.
 // `pricingAsOfDeclared` is the server saying which of the two it is.
 if(USAGE.showCost&&USAGE.pricingAsOfDeclared)bits.push('rates as of '+USAGE.pricingAsOf);
 const ctx=el('div',{class:'uctx'},bits.join(' - '));
 // This used to end the sentence with "set usage.pricingAsOf" — an instruction to
 // go and edit a file, printed on the surface built to edit that file. Now it is
 // the way there.
 if(USAGE.showCost&&!USAGE.pricingAsOfDeclared)ctx.append(' - ',
   settingsLink('rates undated: date them in Settings','usage.pricingAsOf'));
 card.append(ctx);

 // filters, on two rows: WHO and WHAT above, WHEN and the way out below.
 // Typeahead for the dimensions with hundreds of values, a plain select for the
 // two that have three — a select states its whole domain at a glance, which a
 // typeahead hides behind a keystroke, and hiding a two-value domain is silly.
 const uniq=dim=>[...new Set(USAGE.facts.map(f=>f[F[dim]]).filter(Boolean))].sort();
 const totalsFor=dim=>{const m=new Map();
  for(const f of USAGE.facts)m.set(f[F[dim]],(m.get(f[F[dim]])||0)+f[F.tokens]);
  return m;};
 const filt=el('div',{class:'ufil'});
 const r1=el('div',{class:'ufrow'}),r2=el('div',{class:'ufrow'});
 // Free text is the way in when you do not yet know which dimension the word you
 // remember belongs to. Debounced, because every change repaints the tab.
 const qIn=el('input',{type:'search',id:'uq',class:'usearch',value:UF.q,
   placeholder:'search rows — id, title, model, person, agent…',
   'aria-label':'search usage rows'});
 qIn.addEventListener('input',()=>{clearTimeout(UQT);
   UQT=setTimeout(()=>{if(qIn.value!==UF.q)setF('q',qIn.value);},220);});
 r1.append(qIn);
 // `task` joins the typeaheads: it was filterable by clicking a bar or a browse
 // row and by nothing you could type, which on 1000 tasks means it was filterable
 // only by the ones already in the top 8.
 ['model','author','phase','task'].forEach(dim=>{
  const all=uniq(dim),tot=totalsFor(dim);
  const inp=el('input',{type:'search',value:UF[dim],
    placeholder:'all '+dim+'s ('+all.length+')','aria-label':'filter by '+dim,
    onchange:e=>setF(dim,all.includes(e.target.value)?e.target.value:'')});
  r1.append(comboWrap(inp,()=>all.map(v=>({name:v,
    description:uTok(tot.get(v)||0)})),(name,close)=>{close();setF(dim,name);}));});
 // "My spend" — the author filter, pre-loaded with the name in the topbar. It is
 // the SAME string on both ends by construction: the server resolves it with
 // usage_ledger.resolve_author, which is the function that wrote the author column
 // on every row here. A toggle, not a jump: pressing it twice puts you back.
 const me=((STATE||{}).viewer||{}).author;
 if(me){
  const mine=USAGE.facts.filter(f=>f[F.author]===me).length,on=UF.author===me;
  // Rendered even when the count is zero, and saying so, because that is a fact
  // worth having: `usage.authorMode` may name you differently here (hash mode, a
  // repo-local user.email) and a chip that quietly disappeared would leave that
  // unanswerable. Pressing it lands on the empty state, which names the author
  // filter as the cause and offers to lift it.
  r1.append(el('button',{class:'filt'+(on?' on':''),type:'button','data-umine':'1',
    'aria-pressed':on?'true':'false',
    title:mine?('Scope to the '+mine+' row(s) recorded for '+me)
      :('No rows are recorded for '+me+' in this ledger'),
    onclick:()=>setF('author',on?'':me)},'my spend'));}
 [['agent','all agents'],['attr','all attributions']].forEach(([dim,none])=>{
  const vals=uniq(dim);
  if(!vals.length)return;
  const sel=el('select',{'aria-label':'filter by '+fName(dim),'data-uf':dim,
    onchange:e=>setF(dim,e.target.value)});
  sel.append(el('option',{value:''},none+' ('+vals.length+')'));
  vals.forEach(v=>{const o=el('option',{value:v},v);
   if(UF[dim]===v)o.selected=true;sel.append(o);});
  r2.append(sel);});
 // An absolute window, in the same UF.day grammar the chart's click writes.
 const dp=uDayPair();
 const mkDate=(which,val)=>el('input',{type:'date',value:val,
   'data-uf':which,'aria-label':which+' date',
   // The pickers open on the ledger, not on this century. Both ends are also
   // cross-constrained so the picker cannot offer a `to` before the `from`.
   min:which==='to'?(dp[0]||K.from||''):(K.from||''),
   max:which==='from'?(dp[1]||K.to||''):(K.to||''),
   onchange:e=>{const[a,b]=uDayPair();
     if(which==='from')uSetDays(e.target.value,b);else uSetDays(a,e.target.value);}});
 r2.append(el('span',{class:'udates'},
   el('span',{class:'filtlbl'},'from'),mkDate('from',dp[0]),
   el('span',{class:'filtlbl'},'to'),mkDate('to',dp[1])));
 r2.append(el('select',{'aria-label':'time range','data-uf':'range',
   onchange:e=>{UF.range=e.target.value;renderUsage();}},
  [['all','all time'],['7','last 7 days'],['30','last 30 days'],['90','last 90 days']]
   .map(([v,l])=>el('option',Object.assign({value:v},v===UF.range?{selected:'selected'}:{}),l))));
 r2.append(el('button',{class:'btn small push',type:'button','data-ucsv':'1',
   title:'Download the rows behind this view as CSV — one row per bucket, phase, '
     +'task, model, person, agent and attribution, with the filters applied',
   onclick:()=>uExport(uFiltered())},'Export CSV'));
 filt.append(r1,r2);
 card.append(filt);

 // active-filter chips: what is scoping the view, and a way out of each
 if(uAnyFilter()){
  const chips=el('div',{class:'uchips'});
  UORDER.forEach(d=>chips.append(el('button',{class:'uchip',title:'remove this filter',
    'data-uchip':d,onclick:()=>setF(d,'')},el('span',{class:'ck'},fName(d)),
    fVal(d),el('span',{class:'cx'},'x'))));
  chips.append(el('button',{class:'lnk',onclick:clearAll},'clear all'));
  card.append(chips);}

 const facts=uFiltered();
 const days=[...new Set(facts.map(f=>f[F.ts].slice(0,10)))].sort();
 const tot=facts.reduce((a,f)=>[a[0]+f[F.tokens],a[1]+f[F.cost],a[2]+f[F.msgs]],[0,0,0]);
 const cov=uCoverage(facts),unit=uUnit(facts),rt=uRetry(facts);
 const dl=uDelta(facts,days);
 const sp=uDaily(facts);
 // A tile is three things: the number, how it moved against the window before, and
 // the shape it moved in. `pp` says the delta is a difference in percentage POINTS
 // rather than a percentage change; `pol` marks the one metric whose direction is
 // worth judging, so only that one is coloured.
 const tile=(k,v,o)=>{o=o||{};
  const d=o.delta==null?null:o.delta;
  const box=el('div',{class:'utile'},el('div',{class:'k'},k),
    el('div',{class:'v'},v,d==null?null:el('span',
      {class:'dl '+(d>=0?'up':'down')+(o.pol?(d>=0?' good':' bad'):''),
       'data-dl':o.key||'',title:dl.basis},
      (d>=0?'+':'')+d.toFixed(o.pp?1:0)+(o.pp?' pts':'%'))));
  const s=o.series?uSpark(o.series,k+' per '+sp.period+', oldest to newest',!o.pp)
    :null;
  box.append(s
    ? el('div',{class:'utrend',
        title:k+' per '+sp.period+(o.pp?', scaled to its own range — a share has no'
          +' zero to draw an area from':', from zero')},s)
    // Not a blank: a tile with no spark has a reason, and the reason is short
    // enough to carry. Dropping the row instead would also shorten the card and
    // pull the tile grid out of line.
    : el('div',{class:'utrend',title:o.why||'no daily series for this metric'},'—'));
  return box;};
 const tiles=[tile('tokens',uTok(tot[0]),
   {key:'tokens',delta:dl&&dl.tokens,series:sp.series.tokens})];
 if(USAGE.showCost)tiles.push(tile('equivalent cost',uCost(tot[1]),
   {key:'cost',delta:dl&&dl.cost,series:sp.series.cost}));
 tiles.push(tile('messages',tot[2].toLocaleString(),
   {key:'msgs',delta:dl&&dl.msgs,series:sp.series.msgs}));
 if(unit.perTask!=null)tiles.push(tile('cost per task',uCost(unit.perTask),
   {why:'no daily trend: a task’s cost accrues over every day it ran and is only '
     +'complete when the task is, so there is no per-day cost-per-task to plot'}));
 tiles.push(tile('attributed',uPct(cov.attributed),
   {key:'attributed',delta:dl&&dl.attributed,pp:true,pol:1,
    series:sp.series.attributed}));
 card.append(el('div',{class:'utiles'},tiles));
 // Said once, under the row, rather than five times on five chips — and the exact
 // pair of date ranges is on each chip's own tooltip.
 if(dl)card.append(el('div',{class:'ucrumb mut small'},
   'Trend is '+dl.label+': '+dl.basis+'.'));

 if(!facts.length){
  const why=uEmptyWhy();
  const acts=el('div',{class:'uempty'});
  if(why.fix)acts.append(el('button',{class:'btn small','data-ufix':why.fix.key,
    onclick:why.fix.run},why.fix.label));
  // Kept, and kept second: it is the way out when the diagnosis is "the
  // combination", and the one control a reader already knows from every other tab.
  acts.append(el('button',{class:'btn small','data-uclear':'1',
    onclick:clearAll},'Clear filters'));
  card.append(el('div',{class:'mut','data-uwhy':why.why},why.text),acts);
  done();return;}

 const dim=chartDim();
 // Slots are handed out to the entities actually drawn, so a hue is never shared.
 const sr=uSeries(facts,dim);
 const plotted=sr.entities.map(e=>e.key);
 MSLOTS=uSlots(F.model,dim==='model'?plotted
   :uAgg(facts,'model').slice(0,TOP).map(r=>r[0]),'name');
 USLOTS=dim==='model'?MSLOTS:uSlots(F.author,plotted,'spend');
 const per=sr.binSize===1?'day':BINNAME[sr.binSize];
 card.append(el('h2',{},'Tokens per '+per+' by '+dim));
 card.append(el('div',{class:'ucrumb mut'},(UF.author
   ?'Scoped to '+UF.author+' - lines are their models. Click a line to scope to one, or clear the author filter to compare people again.'
   :'Click a line to scope to that person, or anywhere else to scope to that '+per+'.')
   +(sr.binSize===1?'':' Days are rolled up into '+per+
     ' totals - '+sr.buckets.length+' points instead of '+
     'one per day, which at this span would draw noise.')));
 card.append(mountChart(sr,dim));
 card.append(el('div',{class:'ulegend'},sr.entities.map(e=>
   el('b',{class:e.key==='other'?'':'pick',
     onclick:()=>{if(e.key!=='other')setF(dim,UF[dim]===e.key?'':e.key);}},
    el('i',{style:'background:'+uCol(e.key)}),e.key))));

 card.append(...uBars(facts,'phase','By phase'));
 card.append(...uBudgets(facts));
 card.append(...uBars(facts,'model','By model'));
 card.append(...uBars(facts,'author','By author'));
 card.append(...uBars(facts,'task','By task'));

 // economics - the same honesty caveats the report carries
 card.append(el('h2',{},'Unit economics'));
 if(unit.proj)card.append(el('div',{class:'ufact'},'Remaining '+unit.remaining+
   ' task(s) project to '+uCost(unit.proj.low)+' to '+uCost(unit.proj.high)+
   ' at the p25-p75 per-task rate.'));
 else card.append(el('div',{class:'mut small'},'Projection needs '+unit.gate+
   ' completed tasks to mean anything; there are '+unit.completed+
   '. A forecast off a smaller sample would be noise.'));
 if(rt.tot)card.append(el('div',{class:'ufact'},uCost(rt.re)+' on tasks that needed '+
   'more than one attempt ('+rt.rn+' task(s)) - '+uCost(rt.bl)+
   ' on tasks that ended blocked ('+rt.bn+' task(s)).'),
  el('div',{class:'mut small'},'Retried spend is not wasted spend: the ledger '+
   'buckets by hour, not by attempt, so a task that retried and then landed did not '+
   'burn every attempt for nothing. Only the blocked figure is spend with no '+
   'outcome'+(rt.overlap?' (the same task is in both figures here)':'')+'.'));

 const rows=uRouting(facts);
 if(rows.length){card.append(el('h2',{},'Model cost within each risk band'),
  el('div',{class:'mut small'},'Compared inside a band on purpose: hard work is '+
   'routed to the stronger model deliberately, so a raw spend-per-task comparison '+
   'across bands would flag that working system as a fault.'));
  const tbl=el('table',{class:'utbl'},el('thead',{},el('tr',{},
    ['risk','model','tasks','cost/task','mean attempts'].map(h=>el('th',{},h)))));
  const tb=el('tbody',{});let last='';
  rows.forEach(r=>{tb.append(el('tr',{},el('td',{},r.risk===last?'':r.risk),
    el('td',{class:'mono'},r.model),el('td',{},String(r.tasks)),
    el('td',{},uCost(r.perTask)),el('td',{},r.att.toFixed(1))));last=r.risk;});
  tbl.append(tb);card.append(tbl);}

 // The one recommendation in the tab. Computed server-side over the whole ledger
 // (see routingAdvice in usage_state), so it is a statement about the project and
 // says so whenever a filter is narrowing everything else on screen.
 const adv=USAGE.routingAdvice||[];
 if(adv.length){
  card.append(el('h2',{},'What the evidence supports'));
  if(UORDER.length)card.append(el('div',{class:'ucrumb mut'},
    'Across the whole ledger - this one does not follow the filters above.'));
  adv.forEach(a=>card.append(el('div',{class:'advice'},
    el('div',{},el('b',{},a.risk),' work is running on ',
      el('code',{},a.from),' - '+a.tasks+' task(s) at '
      +(a.fromMeanAttempts||0).toFixed(1)+' mean attempts. Those same tokens cost '
      +uCost(a.atToRates)+' at ',el('code',{},a.to),' rates versus '
      +uCost(a.atFromRates)+', ',el('b',{},uCost(a.saving)+' less ('
      +a.savingPct.toFixed(0)+'%)'),'.'),
    el('div',{class:'mut small'},a.to+' has already run '+a.evidenceTasks
      +' task(s) in this band here, at '+(a.evidenceAttempts||0).toFixed(1)
      +' mean attempts.'))));
  card.append(el('div',{class:'mut small'},
    'An upper bound, not a forecast: this re-prices the tokens that were actually '
    +'spent at the other model’s rates, and a different model would not emit '
    +'the same tokens. Both sides use today’s price table.'));}

 done();}

// Esc pops the most recently applied filter -- the fastest way back out of a scope
// you clicked into by accident.
document.addEventListener('keydown',e=>{
 if(e.key!=='Escape'||$('#usage').classList.contains('hidden'))return;
 if(document.querySelector('.combo-menu:not(.hidden)'))return;
 // A dialog closes itself on Esc. Without this guard that same keypress would
 // ALSO drop a filter - one key, two effects, one of them invisible.
 if(document.querySelector('dialog[open]'))return;
 // An <input type=search> clears ITSELF on Escape, the same trap the browse
 // dialog hit. Left alone, one press would empty the box and pop an unrelated
 // filter; so from inside the box, Escape means "drop the search" and nothing
 // else, and the state follows the box rather than diverging from it.
 const a=document.activeElement;
 if(a&&a.id==='uq'){if(UF.q)setF('q','');return;}
 if(UORDER.length){setF(UORDER[UORDER.length-1],'');}
 else if(UF.range!=='all'){UF.range='all';renderUsage();}});
boot().catch(e=>toast('load failed: '+e,'err'));
</script></body></html>"""

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

    # front-matter parser
    fm = _front_matter("---\nname: my-skill\ndescription: \"Does X.\"\n---\nbody")
    check("front-matter name", fm.get("name") == "my-skill")
    check("front-matter desc unquoted", fm.get("description") == "Does X.")
    check("no front-matter -> {}", _front_matter("# just md") == {})

    tmp = tempfile.mkdtemp(prefix="panel-selftest-")
    proj = os.path.join(tmp, "proj")
    home = os.path.join(tmp, "home")
    # a project skill + agent
    os.makedirs(os.path.join(proj, ".claude", "skills", "proj-skill"))
    with open(os.path.join(proj, ".claude", "skills", "proj-skill", "SKILL.md"), "w") as fh:
        fh.write("---\nname: proj-skill\ndescription: Project skill.\n---\n")
    os.makedirs(os.path.join(proj, ".claude", "agents"))
    with open(os.path.join(proj, ".claude", "agents", "proj-agent.md"), "w") as fh:
        fh.write("---\nname: proj-agent\ndescription: Project agent.\n---\n")
    # a user-global skill
    os.makedirs(os.path.join(home, ".claude", "skills", "user-skill"))
    with open(os.path.join(home, ".claude", "skills", "user-skill", "SKILL.md"), "w") as fh:
        fh.write("---\nname: user-skill\n---\n")

    reg = discover(proj, home=home)
    names = {s["name"] for s in reg["skills"]}
    check("discovery finds project skill", "proj-skill" in names)
    check("discovery finds user skill", "user-skill" in names)
    check("discovery finds project agent",
          any(a["name"] == "proj-agent" for a in reg["agents"]))
    check("discovery labels source",
          any(s["source"] == "project" for s in reg["skills"]) and
          any(s["source"] == "user" for s in reg["skills"]))

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
    # The claim this tab makes is "here is the configuration". It was not true: the
    # form covered part of the config and nothing anywhere said which part, so the
    # `usage.*` block and four of five `tddReminder.*` keys were invisible on the one
    # surface built to make them legible.
    #
    # The expected set is DERIVED from validate-config's own key sets rather than
    # listed here. A hand-kept list would be a third place to forget a key — the
    # exact failure this chunk exists to fix, one level up.
    _vc = _cores()[1]
    _containers = {"secretPatterns": _vc.KNOWN_SECRET, "guardEdits": _vc.KNOWN_GUARD,
                   "bashWriteCheck": _vc.KNOWN_BASHW, "tddReminder": _vc.KNOWN_TDD,
                   "usage": _vc.KNOWN_USAGE, "journal": _vc.KNOWN_JOURNAL}
    # `policy` is a root key with no control on this form, on purpose — the one
    # exemption, and it is stated rather than silently subtracted. It is not a
    # setting with a value; it is a rule set whose meaning is the verdict it
    # produces for each installed capability, which is what /api/policy serves and
    # what the **Policy tab** renders, switch by switch. A generic text box over it
    # would be a JSON editor wearing a label. The exemption is pinned below: it must
    # name a key the validator actually knows, or it would silently excuse nothing.
    _settings_exempt = {"policy"}
    _expected = {k for k in _vc.KNOWN_ROOT
                 if k not in _containers and k not in _settings_exempt}
    for _parent, _keys in _containers.items():
        _expected |= {"%s.%s" % (_parent, k) for k in _keys}
    check("the Settings exemption names a real config key - an exemption for a key "
          "the validator has never heard of excuses nothing and hides the next one",
          _settings_exempt <= _vc.KNOWN_ROOT)
    check("...and the exempt key is served by its own endpoint instead, so it is "
          "not simply missing from the panel",
          all('if path == "/api/%s"' % k in _src_of_this_file()
              for k in _settings_exempt))
    # The container map above IS hand-kept — there is no machine link from a
    # top-level key to the set of keys inside it — so the one thing it can get
    # wrong is naming a container the validator has never heard of. Then the
    # derived set would keep expecting `journal.*` after `journal` was dropped from
    # KNOWN_ROOT, and this whole check would agree with itself about a key the
    # hooks ignore.
    check("every container the form groups is a real top-level key",
          set(_containers) <= _vc.KNOWN_ROOT)
    _bound = set(_settings_paths())
    check("Settings binds a control to EVERY key the validator accepts - the "
          "missing ones were the whole usage block and most of tddReminder",
          _bound == _expected,)
    if _bound != _expected:
        print("     missing: %s" % sorted(_expected - _bound))
        print("     unknown: %s" % sorted(_bound - _expected))
    check("every bound setting has help text, and no help text names a key the "
          "validator does not know",
          set(FIELD_HELP) == _bound)
    check("no path is bound twice (a duplicate would render two controls writing "
          "the same key)", len(_settings_paths()) == len(_bound))
    # Named by what they DO, with the key beside them. Every heading used to BE a
    # JSON path, uppercased by the h2 rule: "GUARDEDITS.TOKENVARS". That reads as a
    # config dump and assumes the schema the reader came here to learn.
    for _g in SETTINGS_GROUPS:
        for _f in _g["fields"]:
            check("%r is labelled %r rather than shown as a bare key"
                  % (_f["path"], _f["label"]),
                  bool(_f["label"]) and _f["label"] != _f["path"]
                  and not _f["label"][0].islower())
    check("the groups are the decisions the config makes, not one list",
          tuple(g["id"] for g in SETTINGS_GROUPS)
          == ("paths", "guards", "tdd", "usage", "journal")
          and all(g["blurb"] for g in SETTINGS_GROUPS))
    check("the audit trail's card states the limit of the claim, where someone "
          "deciding whether to rely on it will read it",
          "not tamper-proof" in dict(
              (g["id"], g["blurb"]) for g in SETTINGS_GROUPS)["journal"])
    check("no blurb writes markdown - they are rendered as text, so a backtick "
          "reaches the screen as a backtick",
          not any("`" in g["blurb"] or "**" in g["blurb"]
                  for g in SETTINGS_GROUPS))
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
