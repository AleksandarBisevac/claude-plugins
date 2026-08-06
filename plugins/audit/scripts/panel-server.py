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
import importlib.util
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_REL = ".claude/audit.config.json"

sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)

# Fields the composition patch is allowed to touch — the security allow-list.
_META_KEYS = ("reviewSkill", "buildCommands")
_PHASE_KEYS = ("reviewModel",)
_TASK_KEYS = ("model", "skills")


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


def _manifest_path(project, config):
    mp = (config or {}).get("manifestPath") or _defaults()["manifestPath"]
    return os.path.normpath(os.path.join(project, mp))


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


def _areas_of(area):
    """A phase's `area` (string, list, or absent) -> a list of tag strings."""
    if isinstance(area, str):
        return [area] if area else []
    if isinstance(area, list):
        return [a for a in area if isinstance(a, str) and a]
    return []


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
                "skills": t.get("skills") if isinstance(t.get("skills"), list) else [],
            })
    return {
        "meta": {"reviewSkill": meta.get("reviewSkill"),
                 "buildCommands": meta.get("buildCommands")},
        "phases": phases_out, "tasks": tasks_out,
    }


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


def _lock_info(lockdir):
    """Read the shared audit-locks dir into {'index': info|None, 'phases': {pid: info}}.
    Each info is the lock file's `{hostname, startedAt, note}` (or {} if unreadable)."""
    out = {"index": None, "phases": {}}
    if not (lockdir and os.path.isdir(lockdir)):
        return out
    try:
        names = os.listdir(lockdir)
    except Exception:
        return out
    for name in names:
        if not name.endswith(".lock"):
            continue
        try:
            with open(os.path.join(lockdir, name), "r", encoding="utf-8") as fh:
                info = json.load(fh)
        except Exception:
            info = {}
        if not isinstance(info, dict):
            info = {}
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


def _undeclared_css_vars(css):
    """Custom properties referenced by var() but never declared anywhere.

    This check exists because the failure mode is SILENT and total: an undeclared
    `var(--x)` makes the whole declaration invalid at computed-value time, so the
    property falls back to its INITIAL value rather than to the stylesheet rule
    underneath it. An undeclared colour token therefore paints transparent — a bar
    chart with no bars — and logs nothing. That is exactly how `--bar-neutral`
    shipped invisible in light mode once."""
    declared = set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", css))
    # Only FALLBACK-LESS references are dangerous. `var(--x, something)` degrades
    # gracefully by design, and tokens set inline per element from Python (--w on a
    # progress fill, --sc on a sparkline) are always written that way for exactly
    # this reason.
    used = set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)", css))
    return sorted(used - declared)


def _theme_asymmetric_vars(css):
    """Colour tokens that exist in one theme but not the other - in EITHER direction.

    The light `:root` is the base token set; the dark blocks are overrides. There are
    two distinct silent failures here, and the first version of this check only
    caught one of them:

      * declared in light, missing from dark -> the token vanishes in dark mode
      * declared ONLY in a dark block        -> it vanishes in LIGHT mode, which is
        exactly how `--bar-neutral` shipped as invisible bars

    Both render transparent with nothing in the console, so both are checked."""
    light = re.search(r":root\s*\{([^}]*)\}", css)
    if not light:
        return []
    light_vars = set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", light.group(1)))
    dark_vars = set()
    for block in re.findall(
            r"(?:prefers-color-scheme\s*:\s*dark|data-theme=.?dark)[^{]*\{(.*?)\}\}?",
            css, re.S):
        dark_vars |= set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", block))
    if not dark_vars:
        return []
    # spacing / type / motion / font tokens are theme-independent by design and are
    # deliberately declared once, in the base only.
    neutral = ("--sp-", "--t-", "--dur", "--ease", "--radius", "--pill",
               "--sans", "--mono", "--shadow")

    def colourish(names):
        return {v for v in names if not any(v.startswith(n) for n in neutral)}

    return sorted("%s (light only)" % v
                  for v in colourish(light_vars) - dark_vars) + \
        sorted("%s (dark only)" % v for v in colourish(dark_vars) - light_vars)


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
             "pricingAsOf": ucfg.get("pricingAsOf"), "facts": [], "fields": [],
             # Every key the populated branch returns must appear here too: the
             # client reads this shape on a repo with no ledger yet, and a missing
             # key there is an `undefined` that only shows up on a fresh install.
             "phaseTitles": {}, "taskMeta": {},
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
    titles, task_meta = {}, {}
    mpath = _manifest_path(project, config)
    try:
        for ph in (_mio.load_manifest_safe(mpath).get("phases") or []):
            if not isinstance(ph, dict):
                continue
            if ph.get("id"):
                titles[ph["id"]] = ph.get("title") or ""
            for t in (ph.get("tasks") or []):
                if isinstance(t, dict) and t.get("id"):
                    task_meta[t["id"]] = {
                        "status": t.get("status"), "risk": t.get("risk") or "unrated",
                        "attempts": t.get("attempts") or 1,
                        "title": t.get("title") or ""}
    except Exception:
        titles, task_meta = {}, {}

    return {
        "enabled": bool(ucfg.get("enabled", True)),
        "ledgerDir": ledger_dir,
        "showCost": bool(ucfg.get("showCost", True)),
        "pricingAsOf": ucfg.get("pricingAsOf"),
        "fields": ["ts", "phase", "task", "model", "author", "agent", "attr",
                   "tokens", "cost", "msgs"],
        "facts": [list(k) + [v[0], round(v[1], 6), v[2]]
                  for k, v in sorted(facts.items())],
        "phaseTitles": titles,
        "taskMeta": task_meta,
        "counts": counts,
        "rolled": rolled,
        "totalRows": seen,
    }


def build_state(project):
    vm, vc, as_, _ = _cores()
    config = read_config(project)
    cfg_findings, cfg_warnings = vc.validate_config(config)
    mpath = _manifest_path(project, config)
    manifest, exists = None, os.path.isfile(mpath)
    rollup, m_findings = None, []
    composition = {"meta": {"reviewSkill": None, "buildCommands": None},
                   "phases": [], "tasks": []}
    if exists:
        try:
            manifest = _mio.load_manifest(mpath)   # dual-format: single-file OR index+shards
        except Exception as exc:
            m_findings = ["cannot parse manifest: %s" % exc]
        if isinstance(manifest, dict):
            m_findings, m_warn = vm.validate(manifest)
            rollup = as_.rollup(manifest, m_findings, m_warn)
            composition = _composition_view(manifest)
    return {
        "project": project,
        "manifestPath": os.path.relpath(mpath, project),
        "manifestExists": exists,
        "manifestLocked": _audit_lock_held(project, config),
        "config": config,
        "defaults": _defaults(),
        "configFindings": cfg_findings,
        "configWarnings": cfg_warnings,
        "manifestFindings": m_findings,
        "composition": composition,
        "rollup": rollup,
        "runStatus": _run_status(project, config, manifest),
    }


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
    _atomic_write_json(path, obj)
    return {"ok": True, "findings": [], "warnings": warnings,
            "path": os.path.relpath(path, project)}


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


def apply_composition(project, patch):
    """Load manifest, apply an allow-listed patch, validate, atomic-write."""
    vm, _, _, _ = _cores()
    if not isinstance(patch, dict):
        return {"ok": False, "findings": ["patch must be a JSON object"]}
    config = read_config(project)
    mpath = _manifest_path(project, config)
    if not _within(project, mpath):
        return {"ok": False, "findings": ["refused: manifest path escapes project"]}
    if not os.path.isfile(mpath):
        return {"ok": False, "findings": ["manifest not found: run /audit:init first"]}
    if _audit_lock_held(project, config):
        return {"ok": False, "locked": True,
                "findings": ["manifest is locked by a running /audit command; "
                             "try again once it finishes"]}
    try:
        manifest = _read_json(mpath)
    except Exception as exc:
        return {"ok": False, "findings": ["cannot parse manifest: %s" % exc]}
    if not isinstance(manifest, dict):
        return {"ok": False, "findings": ["manifest root is not an object"]}
    err = apply_composition_patch(manifest, patch)
    if err:
        return {"ok": False, "findings": ["refused: " + err]}
    findings, warnings = vm.validate(manifest)
    if findings:
        return {"ok": False, "findings": findings, "warnings": warnings}
    _atomic_write_json(mpath, manifest)
    return {"ok": True, "findings": [], "warnings": warnings,
            "path": os.path.relpath(mpath, project)}


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
            if path == "/api/registry":
                self._json(200, discover(project)); return
            if path == "/api/usage":
                self._json(200, usage_state(project)); return
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
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._guard():
                return
            if self.path.split("?", 1)[0] == "/api/validate":
                st = build_state(project)
                self._json(200, {"config": st["configFindings"],
                                 "manifest": st["manifestFindings"]}); return
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
        print("panel RUNNING: %s (PID %s)" % (info.get("url"), info.get("pid")))
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
        print("panel already running: %s (PID %s)"
              % (existing.get("url"), existing.get("pid")))
        print("stop it with:  --stop   (or /audit:panel stop)")
        return 0
    _rm_pidfile(project)  # clear any stale record

    token = secrets.token_urlsafe(18)
    port = port or _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(project, token))
    url = "http://127.0.0.1:%d/?t=%s" % (port, token)
    _write_pidfile(project, {"pid": os.getpid(), "port": port, "url": url})
    atexit.register(_rm_pidfile, project)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))  # --stop → clean exit
    print("audit control panel: %s" % url)
    print("project: %s" % project)
    print("(open the URL in a browser; press Ctrl-C — or `--stop` — to stop)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
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
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
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
:root{color-scheme:light dark;
 --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,system-ui,sans-serif;
 --mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,monospace;
 --bg:#f5f7fb;--surface:#fff;--surface-2:#eef2f7;--text:#0f172a;--muted:#64748b;
 --border:#e2e8f0;--border-strong:#cbd5e1;--accent:#0d9488;--accent-solid:#0d9488;
 --ring:rgba(13,148,136,.35);--ok:#15803d;--warn:#b45309;--err:#dc2626;
 --bar-neutral:#5c636d;
 /* Usage viz. Same validated categorical palette as the report, so a model
    keeps one identity across both surfaces. Slots are assigned by model NAME,
    never by rank, so filtering cannot repaint the survivors. */
 --viz-1:#2a78d6;--viz-2:#eb6834;--viz-3:#1baf7a;--viz-4:#eda100;
 --viz-5:#e87ba4;--viz-6:#008300;--viz-7:#4a3aa7;--viz-8:#e34948;
 --radius:9px;--radius-lg:14px;--pill:999px;--shadow-sm:0 1px 2px rgba(15,23,42,.05),0 2px 8px rgba(15,23,42,.06);
 --shadow-md:0 10px 30px rgba(15,23,42,.14);--dur:.2s;--ease:cubic-bezier(.4,0,.2,1);
 /* 8pt spacing scale + 3 text levels, matching the report so both surfaces
    share one rhythm. Spacing and type are theme-independent, so unlike the
    colour tokens these are declared ONCE, not repeated in the dark blocks. */
 --sp-0:.25rem;--sp-1:.5rem;--sp-2:.75rem;--sp-3:1rem;
 --sp-4:1.5rem;--sp-5:2rem;--sp-6:3rem;--sp-7:4rem;
 --t-1:1.7rem;--t-2:1.0625rem;--t-3:.875rem;--t-label:.68rem}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
 --bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;--muted:#93a4bd;
 --border:#1f2b40;--border-strong:#33425c;--accent:#2dd4bf;--accent-solid:#0f766e;
 --ring:rgba(45,212,191,.4);--ok:#34d399;--warn:#fbbf24;--err:#f87171;
 --viz-1:#3987e5;--viz-2:#d95926;--viz-3:#199e70;--viz-4:#c98500;
 --viz-5:#d55181;--viz-6:#008300;--viz-7:#9085e9;--viz-8:#e66767;
 --bar-neutral:#a6adb8;
 --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-md:0 12px 34px rgba(0,0,0,.5)}}
:root[data-theme=dark]{--bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;
 --muted:#93a4bd;--border:#1f2b40;--border-strong:#33425c;--accent:#2dd4bf;--accent-solid:#0f766e;
 --ring:rgba(45,212,191,.4);--ok:#34d399;--warn:#fbbf24;--err:#f87171;
 --viz-1:#3987e5;--viz-2:#d95926;--viz-3:#199e70;--viz-4:#c98500;
 --viz-5:#d55181;--viz-6:#008300;--viz-7:#9085e9;--viz-8:#e66767;
 --bar-neutral:#a6adb8;
 --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-md:0 12px 34px rgba(0,0,0,.5)}
*{box-sizing:border-box}html{background:var(--bg)}
body{font:15px/1.6 var(--sans);color:var(--text);background:var(--bg);margin:0;
 max-width:64rem;margin:0 auto;padding:1.5rem 1.5rem 4rem;-webkit-font-smoothing:antialiased}
h1{font-size:1.35rem;font-weight:680;letter-spacing:-.02em;margin:0}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
 font-weight:700;margin:1.5rem 0 .5rem}
.sub{color:var(--muted);font-family:var(--mono);font-size:.78rem;margin:.25rem 0 0;word-break:break-all}
.top{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.tabs{display:flex;gap:.5rem;margin:1.5rem 0 .25rem;flex-wrap:wrap}
.tab{cursor:pointer;font:inherit;font-size:.85rem;padding:.5rem 1rem;border-radius:var(--pill);
 border:1px solid var(--border);background:var(--surface);color:var(--text);transition:all var(--dur) var(--ease)}
.tab:hover{border-color:var(--border-strong)}
.tab.on{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
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
.ufil .combo{flex:1 1 11rem;min-width:9rem}
.ufil input,.ufil select{font:inherit;font-size:.78rem;width:100%;
 padding:var(--sp-0) var(--sp-1);border-radius:var(--radius);
 border:1px solid var(--border);background:var(--bg);color:var(--text)}
.ufil select{flex:0 0 auto;width:auto}
.ufil input:focus-visible,.ufil select:focus-visible{outline:2px solid var(--ring);
 outline-offset:1px}
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
.utiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(7.5rem,1fr));
 gap:var(--sp-1);margin:0 0 var(--sp-3)}
.utile{border:1px solid var(--border);border-radius:var(--radius);
 padding:var(--sp-1) var(--sp-2);background:var(--bg)}
.utile .k{font-size:var(--t-label);text-transform:uppercase;letter-spacing:.07em;
 color:var(--muted)}
.utile .v{font-size:1.25rem;font-weight:660;letter-spacing:-.02em;
 margin-top:var(--sp-0);display:flex;align-items:baseline;gap:var(--sp-0)}
.dl{font-size:.68rem;font-weight:600;padding:0 .3rem;border-radius:var(--pill);
 letter-spacing:0}
.dl.up{color:var(--ok);background:color-mix(in srgb,var(--ok) 14%,transparent)}
.dl.down{color:var(--muted);background:var(--surface-2)}
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
@media (max-width:34rem){
 dialog.browse{width:calc(100vw - 1rem)}
 .btblwrap{overflow-x:auto}
}
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
}
}
.tsk{border:1px solid var(--border);border-radius:var(--radius);padding:.5rem .75rem;background:var(--bg)}
.tsk .h{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap}
.dot{width:.6rem;height:.6rem;border-radius:50%;display:inline-block;background:var(--muted)}
.rule{display:grid;grid-template-columns:1fr 1fr 1.3fr auto;gap:.5rem;margin:.25rem 0}
@media(max-width:40rem){.rule{grid-template-columns:1fr}}
#toast{position:fixed;left:50%;bottom:1.3rem;transform:translateX(-50%);z-index:50;
 background:var(--surface);border:1px solid var(--border);box-shadow:var(--shadow-md);
 border-radius:var(--pill);padding:.5rem 1rem;font-size:.85rem;opacity:0;transition:opacity var(--dur);pointer-events:none}
#toast.show{opacity:1}#toast.err{border-color:var(--err);color:var(--err)}#toast.ok{border-color:var(--ok)}
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
 white-space:normal;opacity:0;visibility:hidden;transition:opacity var(--dur);pointer-events:none}
.hint:hover::after,.hint:focus::after{opacity:1;visibility:visible}
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
.count{font-size:.73rem;color:var(--muted);font-variant-numeric:tabular-nums}
.comptblwrap{border:1px solid var(--border);border-radius:var(--radius);overflow:visible}
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
.comp .combo{flex:1 1 8rem;min-width:7rem}
@media(max-width:48rem){.comptblwrap{overflow-x:auto}html,body{overflow-x:hidden}}
</style></head><body>
<div class=top>
 <div><h1>audit · control panel</h1><p class=sub id=proj></p></div>
 <div class=topbtns>
  <button class="btn small" id=theme title="light/dark">☾</button>
 </div>
</div>
<div class=tabs>
 <button class="tab on" data-t=guards>Guards &amp; paths</button>
 <button class="tab" data-t=comp>Composition</button>
 <button class="tab" data-t=over>Overview</button>
 <button class="tab" data-t=usage>Usage</button>
</div>
<div id=guards></div>
<div id=comp class=hidden></div>
<div id=over class=hidden></div>
<div id=usage class=hidden></div>
<div id=toast></div>
<script>
const TOKEN=__AUDIT_TOKEN__, PROJECT=__AUDIT_PROJECT__;
const $=(s,r=document)=>r.querySelector(s), el=(t,a={},...k)=>{const e=document.createElement(t);
 for(const[n,v]of Object.entries(a)){if(n==='class')e.className=v;else if(n==='html')e.innerHTML=v;
 else if(n.startsWith('on'))e.addEventListener(n.slice(2),v);else if(v!=null)e.setAttribute(n,v);}
 for(const c of k.flat()){if(c!=null)e.append(c.nodeType?c:document.createTextNode(c));}return e;};
const api=async(m,p,b)=>{const r=await fetch(p,{method:m,headers:{'X-Audit-Token':TOKEN,
 'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return r.json();};
let STATE=null, REG={skills:[],agents:[],mcp:[]};
$('#proj').textContent=PROJECT;
// theme
const root=document.documentElement, TK='audit-panel-theme';
try{const s=localStorage.getItem(TK);if(s)root.setAttribute('data-theme',s);}catch(e){}
const isDark=()=>{const t=root.getAttribute('data-theme');return t?t==='dark':matchMedia('(prefers-color-scheme:dark)').matches;};
const paint=()=>$('#theme').textContent=isDark()?'☀':'☾';paint();
$('#theme').onclick=()=>{const n=isDark()?'light':'dark';root.setAttribute('data-theme',n);
 try{localStorage.setItem(TK,n);}catch(e){}paint();};
// tabs
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
 document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));
 for(const id of['guards','comp','over','usage'])$('#'+id).classList.toggle('hidden',id!==t.dataset.t);});
function toast(msg,kind){const t=$('#toast');t.textContent=msg;t.className='show '+(kind||'');
 setTimeout(()=>t.className=t.className.replace('show','').trim(),2600);}
function findingsBox(res){const box=el('div');
 if(res.findings&&res.findings.length)box.append(el('div',{class:'findings err'},'✗ '+res.findings.join(' · ')));
 if(res.warnings&&res.warnings.length)box.append(el('div',{class:'findings warn'},'! '+res.warnings.join(' · ')));
 if(res.ok&&!(res.warnings&&res.warnings.length))box.append(el('div',{class:'findings ok'},'✓ saved'));
 return box;}
async function boot(){STATE=await api('GET','/api/state');REG=await api('GET','/api/registry');
 USAGE=await api('GET','/api/usage').catch(()=>null);
 renderGuards();renderComp();renderOver();renderUsage();}
// ---------- shared: info hints + autocomplete ----------
const DESC={
 manifestPath:"Path to the audit manifest JSON (project-relative). Default docs/audit/audit-plan.json.",
 gitRoot:"Path of the git repo root, where git + build/gate commands run. Default '.' (this dir).",
 stateDir:"Where the hooks keep transactional state files. Default .claude/state.",
 logsDir:"Where the hooks write logs. Default .claude/logs.",
 bypassKeyword:"Type this in a prompt to arm a one-off plan-first bypass for the next edit. Default #no-plan.",
 trivialLineThreshold:"First-touch edits at or under this many lines skip the plan-first gate. Default 80.",
 bashWriteCheck:"Warn when a Bash command creates new source files that weren't planned.",
 tddReminder:"Non-blocking nudge when you edit source without touching a test.",
 exemptGlobs:"Globs whose edits skip the plan-first / TDD / bash-write guards (docs, tests, .claude/**, the manifest).",
 tokenVars:"Identifier names that must never be logged — a console.log/print of any of these is blocked.",
 secretPatternsExtra:"Extra regexes that mark a file path as a secret; reading a matching file is blocked.",
 customRules:"Per-path banned patterns: block a regex in new content when the edited path starts with a prefix.",
 reviewSkill:"Skill the reviewer agent invokes at phase sign-off. Empty = tests are the only signer.",
 buildCommands:"Named shell commands (typecheck / test / lint …) the pipeline runs as gates.",
 phaseReviewModel:"Model used for this phase's sign-off review.",
 taskModel:"Model the executor uses to implement this task.",
 taskSkills:"Skills the executor loads (via the Skill tool) before writing code for this task."};
function hint(t){return t?el('span',{class:'hint',tabindex:'0','data-tip':t},'i'):null;}
function flabel(text,tip){return el('span',{class:'lbl'},text,hint(tip));}
function h2h(text,tip){return el('h2',{},text,hint(tip));}
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

// ---------- Guards & paths ----------
function listEditor(getArr,setArr,ph){const wrap=el('div',{class:'pill-in'});
 const draw=()=>{wrap.textContent='';(getArr()||[]).forEach((v,i)=>{
   wrap.append(el('span',{class:'chip'},v,el('button',{onclick:()=>{const a=getArr().slice();a.splice(i,1);setArr(a);draw();}},'×')));});
   const inp=el('input',{placeholder:ph||'add…'});inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&inp.value.trim()){const a=(getArr()||[]).slice();a.push(inp.value.trim());setArr(a);draw();}});
   wrap.append(inp);};draw();return wrap;}
function renderGuards(){const c=$('#guards');c.textContent='';const cfg=JSON.parse(JSON.stringify(STATE.config||{})),d=STATE.defaults;
 const g=(k)=>cfg[k]!==undefined?cfg[k]:d[k];
 const card=el('div',{class:'card'});
 const paths=el('div',{class:'row'});
 for(const k of['manifestPath','gitRoot','stateDir','logsDir','bypassKeyword']){
  const inp=el('input',{value:cfg[k]??'',placeholder:d[k]});inp.oninput=()=>{if(inp.value==='')delete cfg[k];else cfg[k]=inp.value;};
  paths.append(el('label',{class:'f'},flabel(k,DESC[k]),inp));}
 const thr=el('input',{type:'number',min:'1',value:cfg.trivialLineThreshold??'',placeholder:d.trivialLineThreshold});
 thr.oninput=()=>{if(thr.value==='')delete cfg.trivialLineThreshold;else cfg.trivialLineThreshold=parseInt(thr.value,10);};
 paths.append(el('label',{class:'f'},flabel('trivialLineThreshold',DESC.trivialLineThreshold),thr));
 card.append(el('h2',{},'Paths'),paths);
 // toggles
 const bw=cfg.bashWriteCheck?{...cfg.bashWriteCheck}:{};const td=cfg.tddReminder?{...cfg.tddReminder}:{};
 const tog=el('div',{class:'row'});
 const mk=(lbl,tip,val,fn)=>{const cb=el('input',{type:'checkbox'});cb.checked=val;cb.onchange=()=>fn(cb.checked);
  return el('label',{class:'f',style:'flex-direction:row;align-items:center;gap:.4rem;flex:0 0 auto'},cb,flabel(lbl,tip));};
 tog.append(mk('bashWriteCheck.enabled',DESC.bashWriteCheck,bw.enabled!==false,v=>{bw.enabled=v;cfg.bashWriteCheck=bw;}));
 tog.append(mk('tddReminder.enabled',DESC.tddReminder,td.enabled!==false,v=>{td.enabled=v;cfg.tddReminder=td;}));
 card.append(el('h2',{},'Guards'),tog);
 // lists
 card.append(h2h('exemptGlobs',DESC.exemptGlobs),listEditor(()=>cfg.exemptGlobs??d.exemptGlobs,a=>cfg.exemptGlobs=a,'glob…'));
 card.append(h2h('guardEdits.tokenVars (never logged)',DESC.tokenVars),
  listEditor(()=>{cfg.guardEdits=cfg.guardEdits||{};return cfg.guardEdits.tokenVars??d.guardEdits.tokenVars;},
   a=>{cfg.guardEdits=cfg.guardEdits||{};cfg.guardEdits.tokenVars=a;},'identifier…'));
 card.append(h2h('secretPatterns.extra (regex)',DESC.secretPatternsExtra),
  listEditor(()=>{cfg.secretPatterns=cfg.secretPatterns||{};return cfg.secretPatterns.extra??[];},
   a=>{cfg.secretPatterns=cfg.secretPatterns||{};cfg.secretPatterns.extra=a;},'regex…'));
 // custom rules
 card.append(h2h('guardEdits.customRules',DESC.customRules));
 const rulesWrap=el('div');const rules=()=>{cfg.guardEdits=cfg.guardEdits||{};cfg.guardEdits.customRules=cfg.guardEdits.customRules||[];return cfg.guardEdits.customRules;};
 const drawRules=()=>{rulesWrap.textContent='';rules().forEach((r,i)=>{
   const pp=el('input',{value:r.pathPrefix||'',placeholder:'pathPrefix'});pp.oninput=()=>r.pathPrefix=pp.value;
   const bp=el('input',{value:r.bannedPattern||'',placeholder:'bannedPattern (regex)'});bp.oninput=()=>r.bannedPattern=bp.value;
   const ms=el('input',{value:r.message||'',placeholder:'message'});ms.oninput=()=>r.message=ms.value;
   rulesWrap.append(el('div',{class:'rule'},pp,bp,ms,el('button',{class:'btn small',onclick:()=>{rules().splice(i,1);drawRules();}},'×')));});
   rulesWrap.append(el('button',{class:'btn small',onclick:()=>{rules().push({pathPrefix:'',bannedPattern:'',message:''});drawRules();}},'+ rule'));};
 drawRules();card.append(rulesWrap);
 const save=el('button',{class:'btn primary',onclick:async()=>{
   const res=await api('PUT','/api/config',cfg);const fb=findingsBox(res);
   c.querySelector('.findings-slot').replaceChildren(fb);
   toast(res.ok?'config saved':'config rejected',res.ok?'ok':'err');if(res.ok){STATE.config=cfg;}}},'Save config');
 card.append(el('div',{class:'row',style:'margin-top:.9rem'},save),el('div',{class:'findings-slot'}));
 c.append(card);}
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
function renderComp(){const c=$('#comp');c.textContent='';const comp=STATE.composition;
 const patch={meta:{},phases:{},tasks:{}};
 const meta=el('div',{class:'card'});meta.append(h2h('Phase sign-off review skill (meta.reviewSkill)',DESC.reviewSkill));
 meta.append(el('div',{class:'row'},skillPicker(comp.meta.reviewSkill,v=>patch.meta.reviewSkill=v)));
 meta.append(h2h('meta.buildCommands (JSON)',DESC.buildCommands));
 const bc=el('textarea',{});bc.value=comp.meta.buildCommands?JSON.stringify(comp.meta.buildCommands,null,2):'';
 bc.oninput=()=>{try{patch.meta.buildCommands=bc.value.trim()?JSON.parse(bc.value):null;bc.style.borderColor='';}
  catch(e){bc.style.borderColor='var(--err)';}};
 meta.append(bc);c.append(meta);
 // tasks: filter toolbar + ONE compact collapsible table (scales to 50x20)
 const tcard=el('div',{class:'card'});tcard.append(h2h('Composition — phases · tasks · skills',DESC.taskSkills));
 const q=el('input',{type:'search',placeholder:'filter phases & tasks…'});
 const statusBar=el('span',{class:'filtset',style:'display:inline-flex;gap:.3rem;flex-wrap:wrap'});
 const needsBtn=el('button',{class:'filt',type:'button',title:'only tasks with no skills yet'},'needs skills');
 const expandBtn=el('button',{class:'btn small',type:'button'},'expand all');
 const count=el('span',{class:'count',style:'margin-left:auto'});
 tcard.append(el('div',{class:'comptools'},q,el('span',{class:'filtlbl'},'phase:'),statusBar,needsBtn,expandBtn,count));
 const tbody=el('tbody');
 tcard.append(el('div',{class:'comptblwrap'},el('table',{class:'comp'},
   el('thead',{},el('tr',{},el('th',{},'id'),el('th',{},'title'),el('th',{},'status'),el('th',{},'model'),el('th',{},'skills'))),tbody)));

 const open={};let phaseFilter='',needsOnly=false;
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
    el('span',{class:'st','data-status':ph.status||''},ph.status||'—'),
    el('span',{class:'count'},tasks.length+(tasks.length===1?' task':' tasks')),
    el('span',{class:'comp-review'},flabel('review',DESC.phaseReviewModel),rev))));
  pr.onclick=()=>{open[ph.id]=!open[ph.id];refresh();};
  tbody.append(pr);
  const taskEls=[];
  tasks.forEach(t=>{
   const tp={};const model=el('input',{value:t.model??'',placeholder:'—'});
   model.oninput=()=>{tp.model=model.value.trim()||null;patch.tasks[t.id]=tp;};
   const getSkills=()=>tp.skills!==undefined?tp.skills:(t.skills||[]);
   const chips=skillChips(getSkills,a=>{tp.skills=a;patch.tasks[t.id]=tp;if(needsOnly)refresh();});
   const tr=el('tr',{class:'task','data-status':t.status||''});
   tr.append(el('td',{class:'tid'},t.id||''),el('td',{class:'ttitle',title:t.title||''},t.title||''),
     el('td',{},el('span',{class:'st','data-status':t.status||''},t.status||'—')),
     el('td',{class:'tmodel'},model),el('td',{class:'tskills'},chips));
   tbody.append(tr);
   taskEls.push({id:t.id||'',title:t.title||'',tr,getSkills});
  });
  phaseEls.push({id:ph.id,title:ph.title||'',status:ph.status||'',area:(ph.area||[]).join(' '),tr:pr,tasks:taskEls});
 });
 [...new Set(comp.phases.map(p=>p.status).filter(Boolean))].sort().forEach(s=>{
  const b=el('button',{class:'filt',type:'button','data-status':s},s);
  b.onclick=()=>{phaseFilter=phaseFilter===s?'':s;
   [...statusBar.children].forEach(x=>x.classList.toggle('on',x.getAttribute('data-status')===phaseFilter));refresh();};
  statusBar.append(b);});
 needsBtn.onclick=()=>{needsOnly=!needsOnly;needsBtn.classList.toggle('on',needsOnly);refresh();};
 expandBtn.onclick=()=>{const anyClosed=phaseEls.some(P=>!open[P.id]);phaseEls.forEach(P=>open[P.id]=anyClosed);refresh();};
 const hit=(s,term)=>!term||s.toLowerCase().includes(term);
 function refresh(){
  const term=q.value.trim().toLowerCase();const forced=(term!=='')||needsOnly;let visP=0,visT=0;
  phaseEls.forEach(P=>{
   const pText=hit(P.id+' '+P.title+' '+P.area,term);let anyT=false;
   P.tasks.forEach(T=>{const tHit=pText||hit(T.id+' '+T.title,term);
    const needHit=!needsOnly||((T.getSkills()||[]).length===0);T._m=tHit&&needHit;if(T._m)anyT=true;});
   const showP=(!phaseFilter||P.status===phaseFilter)&&(pText||anyT)&&(!needsOnly||anyT);
   P.tr.style.display=showP?'':'none';if(showP)visP++;
   const isOpen=showP&&(forced||!!open[P.id]);P.tr.classList.toggle('open',isOpen);
   P.tasks.forEach(T=>{const showT=showP&&isOpen&&T._m;T.tr.style.display=showT?'':'none';if(showT)visT++;});});
  count.textContent=(term||phaseFilter||needsOnly)?(visP+' / '+phaseEls.length+' phases · '+visT+' tasks')
    :(phaseEls.length+' phases · '+comp.tasks.length+' tasks');
  expandBtn.textContent=phaseEls.some(P=>!open[P.id])?'expand all':'collapse all';}
 q.addEventListener('input',refresh);refresh();

 const save=el('button',{class:'btn primary',onclick:async()=>{
   const clean={meta:{},phases:patch.phases,tasks:patch.tasks};
   for(const k of Object.keys(patch.meta))clean.meta[k]=patch.meta[k];
   const res=await api('PUT','/api/composition',clean);
   c.querySelector('.findings-slot').replaceChildren(findingsBox(res));
   toast(res.ok?'manifest saved':(res.locked?'manifest locked':'rejected'),res.ok?'ok':'err');
   if(res.ok){STATE=await api('GET','/api/state');}}},'Save composition');
 tcard.append(el('div',{class:'row',style:'margin-top:.9rem'},save),el('div',{class:'findings-slot'}));
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

// ---------- Overview ----------
function renderOver(){const c=$('#over');c.textContent='';const r=STATE.rollup;const card=el('div',{class:'card'});
 if(!r){card.append(el('div',{class:'mut'},'No manifest at '+STATE.manifestPath+'. Run /audit:init.'));c.append(card);return;}
 const vstate=r.valid?el('div',{class:'findings ok'},'✓ manifest valid ('+r.warnings+' warnings)')
   :manifestFindingsBox(r.findings,STATE.manifestFindings||[]);
 card.append(vstate);
 const rs=STATE.runStatus||{index:null,phases:{}};
 if(rs.index){const h=rs.index.hostname||'?';
  card.append(el('div',{class:'findings warn'},
   '⚙ index locked (structural op / id allocation)'+(h?' · '+h:'')+(rs.index.startedAt?' · since '+rs.index.startedAt:'')));}
 card.append(el('h2',{},'Phases'));
 r.phases.forEach(p=>{const pct=p.total?Math.round(100*p.done/p.total):0;
  const st=(rs.phases||{})[p.id]||{};let runBadge=null;
  if(st.lock){const h=st.lock.hostname||'?';
   runBadge=el('span',{class:'badge run',title:'phase lock held'+(st.lock.startedAt?' since '+st.lock.startedAt:'')},'● running'+(h?' · '+h:''));}
  else if(st.claim){const s=(st.claim.sessionId||'').slice(0,8);
   runBadge=el('span',{class:'badge claim',title:'claimed'+(st.claim.branch?' on '+st.claim.branch:'')},'◷ claimed'+(s?' · '+s:''));}
  const areaBadges=(p.area||[]).map(a=>el('span',{class:'badge area',title:'area'},a));
  card.append(el('div',{class:'row'},el('span',{class:'mono',style:'flex:0 0 3rem'},p.id),
   el('span',{style:'flex:1 1 10rem'},p.title||''),el('span',{class:'badge'},p.status||''),
   areaBadges,runBadge,
   el('span',{class:'bar'},el('i',{style:'width:'+pct+'%'})),el('span',{class:'mut'},p.done+'/'+p.total)));});
 const t=r.tasks,b=r.bugs;
 card.append(el('h2',{},'Totals'),el('div',{class:'row'},
   el('span',{class:'chip'},'tasks '+t.total),el('span',{class:'chip'},'bugs '+b.total),
   el('span',{class:'chip'},'open bugs '+b.open),el('span',{class:'chip'},'ready '+ (r.ready||[]).length)));
 c.append(card);}
// ---------- usage ----------
// ONE filter state. The chart's dimension is DERIVED from it, never stored
// separately -- an earlier version kept a parallel drill-down object and filtered
// author in two places, which let you select one author, click another's line, and
// land in a permanently empty view whose controls said nothing was filtered. With a
// single author slot that state cannot be represented at all.
let USAGE=null;
const UF={model:'',author:'',phase:'',task:'',day:'',range:'all'};
const DIMS=['model','author','phase','task','day'];
let UORDER=[];                 // dimensions in the order they were set (Esc pops)
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
const uPct=x=>x<1&&x>0?'<1%':x.toFixed(0)+'%';

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

function uFiltered(){if(!USAGE)return[];let out=USAGE.facts;
 if(UF.model)out=out.filter(f=>f[F.model]===UF.model);
 if(UF.author)out=out.filter(f=>f[F.author]===UF.author);
 if(UF.phase)out=out.filter(f=>f[F.phase]===UF.phase);
 if(UF.task)out=out.filter(f=>f[F.task]===UF.task);
 if(UF.day){const[a,b]=UF.day.split('..');
  out=b?out.filter(f=>{const d=f[F.ts].slice(0,10);return d>=a&&d<=b;})
       :out.filter(f=>f[F.ts].slice(0,10)===a);}
 if(UF.range!=='all'){const d=new Date(Date.now()-parseInt(UF.range,10)*864e5)
   .toISOString().slice(0,10);out=out.filter(f=>f[F.ts].slice(0,10)>=d);}
 return out;}
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

function uSeries(facts,dim){const per=new Map(),days=new Set();
 for(const f of facts){const d=f[F.ts].slice(0,10),k=f[F[dim]]||'--';
  days.add(d);const m=per.get(k)||new Map();
  m.set(d,(m.get(d)||0)+f[F.tokens]);per.set(k,m);}
 const ds=[...days].sort(),{size,bins}=uBin(ds);
 const at=d=>{const n=dnum(d);let lo=0,hi=bins.length-1;
  while(lo<hi){const mid=(lo+hi+1)>>1;dnum(bins[mid][0])<=n?lo=mid:hi=mid-1;}
  return lo;};
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

// --- metrics, all recomputed under the current filter --------------------------
function uCoverage(facts){const by={},tot=facts.reduce((a,f)=>a+f[F.tokens],0)||1;
 for(const f of facts)by[f[F.attr]]=(by[f[F.attr]]||0)+f[F.tokens];
 const un=by['unattributed']||0;
 return {attributed:100*(tot-un)/tot,task:100*(by['task']||0)/tot,by,tot};}
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
function uDelta(facts,days){
 if(UF.range==='all'||!days.length)return null;
 const span=parseInt(UF.range,10);
 const cut=new Date(Date.now()-span*864e5).toISOString().slice(0,10);
 const prevCut=new Date(Date.now()-2*span*864e5).toISOString().slice(0,10);
 const base=USAGE.facts.filter(f=>{const d=f[F.ts].slice(0,10);
  return d>=prevCut&&d<cut
   &&(!UF.model||f[F.model]===UF.model)&&(!UF.author||f[F.author]===UF.author)
   &&(!UF.phase||f[F.phase]===UF.phase)&&(!UF.task||f[F.task]===UF.task);});
 if(!base.length)return null;
 const sum=a=>a.reduce((x,f)=>[x[0]+f[F.tokens],x[1]+f[F.cost]],[0,0]);
 const now=sum(facts),was=sum(base);
 return {tokens:was[0]?100*(now[0]-was[0])/was[0]:null,
         cost:was[1]?100*(now[1]-was[1])/was[1]:null};}

// --- render --------------------------------------------------------------------
function uBars(facts,dim,title){
 const g=uAgg(facts,dim);if(!g.length)return[];
 const grand=g.reduce((a,x)=>a+x[1][0],0)||1;
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
    tipRow(null,'share',uPct(100*v[0]/grand)),
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

// --- browse dialog ---------------------------------------------------------------
// The ranked list is a summary: the top 8 by spend. Paging it eight at a time to
// reach P219 among 241 is 27 clicks and still gives you no way to re-rank by cost.
// This is the other half - search and sort over the whole dimension - and it reads
// from the SAME filtered facts the bars do, so it can never disagree with the page
// behind it. A native <dialog> brings the focus trap, the backdrop and Esc for free.
let BROWSE=null;
const BCOL={
 phase:[['id','id'],['title','title'],['tokens','tokens'],['share','share'],
        ['cost','cost'],['messages','msgs']],
 task:[['id','id'],['title','title'],['status','status'],['risk','risk'],
       ['tokens','tokens'],['share','share'],['cost','cost'],['messages','msgs']],
 model:[['model','id'],['tokens','tokens'],['share','share'],['cost','cost'],
        ['messages','msgs']],
 author:[['author','id'],['tokens','tokens'],['share','share'],['cost','cost'],
         ['messages','msgs']]};
const BNUM={tokens:1,share:1,cost:1,msgs:1};

function browseRows(dim,facts){
 const g=uAgg(facts,dim),grand=g.reduce((a,x)=>a+x[1][0],0)||1;
 return g.map(([k,v])=>{const m=(USAGE.taskMeta||{})[k]||{};
  return {id:k,
    title:dim==='phase'?(k==='--'?'unattributed':(USAGE.phaseTitles[k]||''))
      :dim==='task'?(k==='--'?'unattributed':(m.title||'')):'',
    status:m.status||'',risk:m.risk||'',
    tokens:v[0],share:100*v[0]/grand,cost:v[1],msgs:v[2]};});}

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
   ? el('div',{class:'mut small'},'within: '+UORDER.map(d=>d+' '+
       (d==='day'?UF.day.replace('..',' to '):UF[d])).join(' · '))
   : null;
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
  shown.sort((a,b)=>{const A=a[sort],B=b[sort];
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
      key==='tokens'?uTok(r.tokens,2)
      // NOT uPct here: across 241 phases every share is under 1%, and a column
      // where every cell reads "<1%" sorts fine and tells you nothing. This is
      // the precision surface, so it gets the digits.
      :key==='share'?(r.share<1?r.share.toFixed(2):r.share.toFixed(1))+'%'
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
 BROWSE.replaceChildren(...[head,within,
   el('div',{class:'comptools'},search,count),
   el('div',{class:'btblwrap'},el('table',{class:'btbl'},thead,tb)),
   el('div',{class:'mut small bfoot'},
     'click a header to sort · click a row to filter')].filter(Boolean));
 BROWSE.showModal();
 search.focus();}

function renderUsage(){const c=$('#usage');c.textContent='';tipHide();
 const card=el('div',{class:'card'});
 if(!USAGE||!USAGE.facts.length){
  card.append(el('div',{class:'mut'},USAGE&&!USAGE.enabled
   ?'Token metering is off (usage.enabled=false in .claude/audit.config.json).'
   :'No usage recorded yet. Metering runs on the Stop/SubagentStop hooks; '
    +'"/audit:usage --backfill" reads transcripts already on disk.'),
   el('div',{class:'mut',style:'margin-top:var(--sp-0)'},
     'ledger: '+((USAGE||{}).ledgerDir||'-')));
  c.append(card);return;}

 // context line: the shape of the ledger, at zero card weight
 const K=USAGE.counts||{};
 const bits=[K.phases+' phases',K.authors+' people',K.models+' models',
   K.sessions+' sessions'];
 if(K.from)bits.push(K.from+' to '+K.to);
 // What the FACTS are bucketed at, which is not what the chart draws at — the
 // chart names its own period in its heading, so this says "ledger" out loud
 // rather than leaving two different resolutions on screen unlabelled.
 bits.push(USAGE.rolled?'daily ledger (rolled up)':'hourly ledger');
 card.append(el('div',{class:'uctx'},bits.join(' - ')));

 // filters: typeahead for the high-cardinality dimensions, select for range
 const uniq=dim=>[...new Set(USAGE.facts.map(f=>f[F[dim]]).filter(Boolean))].sort();
 const totalsFor=dim=>{const m=new Map();
  for(const f of USAGE.facts)m.set(f[F[dim]],(m.get(f[F[dim]])||0)+f[F.tokens]);
  return m;};
 const filt=el('div',{class:'ufil'});
 ['model','author','phase'].forEach(dim=>{
  const all=uniq(dim),tot=totalsFor(dim);
  const inp=el('input',{type:'search',value:UF[dim],
    placeholder:'all '+dim+'s ('+all.length+')','aria-label':'filter by '+dim,
    onchange:e=>setF(dim,all.includes(e.target.value)?e.target.value:'')});
  filt.append(comboWrap(inp,()=>all.map(v=>({name:v,
    description:uTok(tot.get(v)||0)})),(name,close)=>{close();setF(dim,name);}));});
 filt.append(el('select',{'aria-label':'time range',
   onchange:e=>{UF.range=e.target.value;renderUsage();}},
  [['all','all time'],['7','last 7 days'],['30','last 30 days'],['90','last 90 days']]
   .map(([v,l])=>el('option',Object.assign({value:v},v===UF.range?{selected:'selected'}:{}),l))));
 card.append(filt);

 // active-filter chips: what is scoping the view, and a way out of each
 if(UORDER.length||UF.range!=='all'){
  const chips=el('div',{class:'uchips'});
  UORDER.forEach(d=>chips.append(el('button',{class:'uchip',title:'remove this filter',
    onclick:()=>setF(d,'')},el('span',{class:'ck'},d),
    d==='day'?UF.day.replace('..',' to '):UF[d],el('span',{class:'cx'},'x'))));
  chips.append(el('button',{class:'lnk',onclick:clearAll},'clear all'));
  card.append(chips);}

 const facts=uFiltered();
 const days=[...new Set(facts.map(f=>f[F.ts].slice(0,10)))].sort();
 const tot=facts.reduce((a,f)=>[a[0]+f[F.tokens],a[1]+f[F.cost],a[2]+f[F.msgs]],[0,0,0]);
 const cov=uCoverage(facts),unit=uUnit(facts),rt=uRetry(facts);
 const dl=uDelta(facts,days);
 const tile=(k,v,d)=>el('div',{class:'utile'},el('div',{class:'k'},k),
   el('div',{class:'v'},v,d==null?null:el('span',
     {class:'dl '+(d>=0?'up':'down')},(d>=0?'+':'')+d.toFixed(0)+'%')));
 const tiles=[tile('tokens',uTok(tot[0]),dl&&dl.tokens)];
 if(USAGE.showCost)tiles.push(tile('equivalent cost',uCost(tot[1]),dl&&dl.cost));
 tiles.push(tile('messages',tot[2].toLocaleString()));
 if(unit.perTask!=null)tiles.push(tile('cost per task',uCost(unit.perTask)));
 tiles.push(tile('attributed',cov.attributed.toFixed(0)+'%'));
 card.append(el('div',{class:'utiles'},tiles));

 if(!facts.length){
  card.append(el('div',{class:'mut'},'No rows match these filters.'),
   el('button',{class:'btn small',style:'margin-top:var(--sp-1)',onclick:clearAll},
     'Clear filters'));
  c.append(card);return;}

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

 c.append(card);}

// Esc pops the most recently applied filter -- the fastest way back out of a scope
// you clicked into by accident.
document.addEventListener('keydown',e=>{
 if(e.key!=='Escape'||$('#usage').classList.contains('hidden'))return;
 if(document.querySelector('.combo-menu:not(.hidden)'))return;
 // A dialog closes itself on Esc. Without this guard that same keypress would
 // ALSO drop a filter - one key, two effects, one of them invisible.
 if(document.querySelector('dialog[open]'))return;
 if(UORDER.length){setF(UORDER[UORDER.length-1],'');}
 else if(UF.range!=='all'){UF.range='all';renderUsage();}});
boot().catch(e=>toast('load failed: '+e,'err'));
</script></body></html>"""


# --- selftest -------------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

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

    # build_state shape
    st = build_state(proj)
    check("build_state has rollup + composition",
          st["rollup"] is not None and "reviewSkill" in st["composition"]["meta"])
    check("build_state reports manifestPath", bool(st["manifestPath"]))

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
    m2 = _read_json(mpath)
    m2["phases"][0]["claim"] = {"sessionId": "sess-abcd1234", "host": "h", "branch": "audit/p1"}
    _atomic_write_json(mpath, m2)
    st2 = build_state(proj)
    check("runStatus surfaces a phase claim from the manifest",
          ((st2["runStatus"]["phases"].get("P1") or {}).get("claim") or {}).get("sessionId")
          == "sess-abcd1234")
    check("runStatus phase lock is None when the git-dir lock isn't held (non-git tmp)",
          (st2["runStatus"]["phases"].get("P1") or {}).get("lock") is None)

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
    check("UI uses the custom combobox, not a native datalist",
          "function comboWrap(" in UI_HTML and "combo-menu" in UI_HTML
          and "<datalist" not in UI_HTML and "list:" not in UI_HTML)
    check("UI labels carry info hints", "function hint(" in UI_HTML and "data-tip" in UI_HTML)
    check("UI building blocks are a tabbed table", "regtbl" in UI_HTML and "subtab" in UI_HTML)
    check("composition is a compact collapsible filterable table",
          "comptools" in UI_HTML and "table.comp" in UI_HTML and "needs skills" in UI_HTML
          and "tr.phase" in UI_HTML and "class:'tsk'" not in UI_HTML)

    # --- usage tab ---------------------------------------------------------
    check("usage tab is registered and has a view container",
          "data-t=usage" in UI_HTML and "<div id=usage" in UI_HTML
          and "'usage'" in UI_HTML)
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
    sys.exit(main(sys.argv[1:]))
