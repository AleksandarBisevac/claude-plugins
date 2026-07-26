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


def _composition_view(manifest):
    meta = manifest.get("meta") or {}
    phases_out, tasks_out = [], []
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        review = ph.get("review") if isinstance(ph.get("review"), dict) else {}
        phases_out.append({"id": ph.get("id"), "title": ph.get("title"),
                           "status": ph.get("status"), "reviewModel": review.get("model")})
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
 --radius:9px;--radius-lg:14px;--pill:999px;--shadow-sm:0 1px 2px rgba(15,23,42,.05),0 2px 8px rgba(15,23,42,.06);
 --shadow-md:0 10px 30px rgba(15,23,42,.14);--dur:.2s;--ease:cubic-bezier(.4,0,.2,1)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
 --bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;--muted:#93a4bd;
 --border:#1f2b40;--border-strong:#33425c;--accent:#2dd4bf;--accent-solid:#0f766e;
 --ring:rgba(45,212,191,.4);--ok:#34d399;--warn:#fbbf24;--err:#f87171;
 --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-md:0 12px 34px rgba(0,0,0,.5)}}
:root[data-theme=dark]{--bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;
 --muted:#93a4bd;--border:#1f2b40;--border-strong:#33425c;--accent:#2dd4bf;--accent-solid:#0f766e;
 --ring:rgba(45,212,191,.4);--ok:#34d399;--warn:#fbbf24;--err:#f87171;
 --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-md:0 12px 34px rgba(0,0,0,.5)}
*{box-sizing:border-box}html{background:var(--bg)}
body{font:15px/1.6 var(--sans);color:var(--text);background:var(--bg);margin:0;
 max-width:64rem;margin:0 auto;padding:1.6rem 1.3rem 4rem;-webkit-font-smoothing:antialiased}
h1{font-size:1.35rem;font-weight:680;letter-spacing:-.02em;margin:0}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
 font-weight:700;margin:1.6rem 0 .6rem}
.sub{color:var(--muted);font-family:var(--mono);font-size:.78rem;margin:.2rem 0 0;word-break:break-all}
.top{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.tabs{display:flex;gap:.4rem;margin:1.3rem 0 .3rem;flex-wrap:wrap}
.tab{cursor:pointer;font:inherit;font-size:.85rem;padding:.45rem .9rem;border-radius:var(--pill);
 border:1px solid var(--border);background:var(--surface);color:var(--text);transition:all var(--dur) var(--ease)}
.tab:hover{border-color:var(--border-strong)}
.tab.on{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);
 box-shadow:var(--shadow-sm);padding:1rem 1.15rem;margin:.7rem 0}
.row{display:flex;gap:.8rem;flex-wrap:wrap;align-items:center;margin:.55rem 0}
label.f{display:flex;flex-direction:column;gap:.25rem;flex:1 1 15rem;font-size:.82rem;color:var(--muted)}
input,textarea,select{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--border);
 border-radius:var(--radius);padding:.42rem .65rem;font-size:.9rem}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
textarea{font-family:var(--mono);font-size:.82rem;min-height:4.5rem;resize:vertical}
.mono{font-family:var(--mono)}
.btn{cursor:pointer;font:inherit;font-size:.85rem;padding:.45rem .9rem;border-radius:var(--pill);
 border:1px solid var(--border);background:var(--surface);color:var(--text);transition:all var(--dur) var(--ease)}
.btn:hover{border-color:var(--border-strong);transform:translateY(-1px);box-shadow:var(--shadow-sm)}
.btn:active{transform:none}.btn:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.btn.primary{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
.btn.small{font-size:.75rem;padding:.25rem .6rem}
.badge{font-size:.68rem;font-weight:700;padding:.1rem .5em;border-radius:var(--pill);
 background:var(--surface-2);color:var(--muted);border:1px solid var(--border)}
.badge.run{background:color-mix(in srgb,var(--ok) 16%,transparent);color:var(--ok);border-color:transparent}
.badge.claim{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warn);border-color:transparent}
.chip{display:inline-flex;align-items:center;gap:.3em;font-size:.76rem;padding:.12rem .5em;border-radius:var(--pill);
 background:var(--surface-2);border:1px solid var(--border);color:var(--text)}
.chip button{border:none;background:none;color:var(--muted);cursor:pointer;font-size:.9em;padding:0}
.tag{display:inline-block;font-size:.66rem;padding:.05rem .45em;border-radius:var(--pill);
 border:1px solid var(--border);color:var(--muted);margin-left:.35rem}
.listwrap{display:flex;flex-direction:column;gap:.35rem}
.pill-in{display:flex;gap:.3rem;flex-wrap:wrap;align-items:center;border:1px solid var(--border);
 border-radius:var(--radius);padding:.3rem .4rem;background:var(--bg)}
.pill-in input{border:none;background:none;box-shadow:none;flex:1 1 6rem;padding:.15rem .2rem}
.mut{color:var(--muted);font-size:.82rem}
.bar{height:.5rem;border-radius:var(--pill);background:var(--surface-2);overflow:hidden;flex:1 1 8rem;min-width:6rem}
.bar>i{display:block;height:100%;background:var(--accent)}
.grid{display:grid;grid-template-columns:1fr;gap:.5rem}
.tsk{border:1px solid var(--border);border-radius:var(--radius);padding:.6rem .75rem;background:var(--bg)}
.tsk .h{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap}
.dot{width:.6rem;height:.6rem;border-radius:50%;display:inline-block;background:var(--muted)}
.rule{display:grid;grid-template-columns:1fr 1fr 1.3fr auto;gap:.4rem;margin:.35rem 0}
@media(max-width:40rem){.rule{grid-template-columns:1fr}}
#toast{position:fixed;left:50%;bottom:1.3rem;transform:translateX(-50%);z-index:50;
 background:var(--surface);border:1px solid var(--border);box-shadow:var(--shadow-md);
 border-radius:var(--pill);padding:.5rem 1rem;font-size:.85rem;opacity:0;transition:opacity var(--dur);pointer-events:none}
#toast.show{opacity:1}#toast.err{border-color:var(--err);color:var(--err)}#toast.ok{border-color:var(--ok)}
.findings{margin:.5rem 0 0;padding:.5rem .7rem;border-radius:var(--radius);font-size:.82rem}
.findings.err{background:color-mix(in srgb,var(--err) 12%,transparent);color:var(--err)}
.findings.warn{background:color-mix(in srgb,var(--warn) 14%,transparent);color:var(--warn)}
.findings.ok{background:color-mix(in srgb,var(--ok) 12%,transparent);color:var(--ok)}
.src{font-size:.66rem}.hidden{display:none}
/* info hints on labels */
.lbl{display:inline-flex;align-items:center;gap:.35rem}
.hint{display:inline-flex;align-items:center;justify-content:center;width:1.02rem;height:1.02rem;border-radius:50%;
 border:1px solid var(--border-strong);color:var(--muted);font:italic 700 .62rem/1 var(--sans);cursor:help;
 position:relative;flex:0 0 auto;text-transform:none}
.hint:hover,.hint:focus{border-color:var(--accent);color:var(--accent);outline:none}
.hint::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + .4rem);z-index:60;width:17rem;max-width:72vw;
 background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:var(--radius);
 box-shadow:var(--shadow-md);padding:.5rem .6rem;font:400 .74rem/1.45 var(--sans);text-transform:none;letter-spacing:0;
 white-space:normal;opacity:0;visibility:hidden;transition:opacity var(--dur);pointer-events:none}
.hint:hover::after,.hint:focus::after{opacity:1;visibility:visible}
/* custom autocomplete combobox (replaces native datalist) */
.combo{position:relative;flex:1 1 18rem}
.combo>input{width:100%}
.combo-menu{position:absolute;left:0;right:0;top:calc(100% + .25rem);z-index:40;background:var(--surface);
 border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow-md);max-height:15rem;overflow:auto;padding:.25rem}
.combo-it{display:flex;align-items:center;gap:.5rem;padding:.4rem .55rem;border-radius:6px;cursor:pointer}
.combo-it:hover,.combo-it.active{background:var(--surface-2)}
.combo-n{font-size:.82rem;flex:0 0 auto}
.combo-d{color:var(--muted);font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1 1 auto}
.chipwrap{display:flex;flex-direction:column;gap:.4rem;flex:1 1 auto}
.chips{display:flex;gap:.3rem;flex-wrap:wrap}
/* discovered building-blocks: subtabs + one table */
.subtabs{display:flex;gap:.35rem;margin:.5rem 0 .6rem;flex-wrap:wrap}
.subtab{cursor:pointer;font:inherit;font-size:.78rem;padding:.3rem .75rem;border-radius:var(--pill);
 border:1px solid var(--border);background:var(--bg);color:var(--muted);transition:all var(--dur) var(--ease)}
.subtab:hover{border-color:var(--border-strong)}
.subtab.on{background:var(--surface-2);color:var(--text);border-color:var(--border-strong)}
.regtblwrap{max-height:22rem;overflow:auto;border:1px solid var(--border);border-radius:var(--radius)}
table.regtbl{width:100%;border-collapse:separate;border-spacing:0;font-size:.82rem}
table.regtbl th{position:sticky;top:0;z-index:1;background:var(--surface-2);color:var(--muted);text-align:left;
 font-size:.66rem;text-transform:uppercase;letter-spacing:.05em;padding:.45rem .65rem;border-bottom:1px solid var(--border)}
table.regtbl td{padding:.4rem .65rem;border-bottom:1px solid var(--border);vertical-align:top}
table.regtbl tbody tr:hover td{background:var(--surface-2)}
table.regtbl td.d{color:var(--muted)}
/* status -> --st (reuses the theme-aware ok/warn/err/muted tokens) */
[data-status="done"],[data-status="fixed"]{--st:var(--ok)}
[data-status="in_progress"],[data-status="triaged"]{--st:var(--warn)}
[data-status="blocked"],[data-status="open"]{--st:var(--err)}
[data-status="pending"],[data-status="wontfix"]{--st:var(--muted)}
.st{display:inline-block;font-size:.66rem;font-weight:600;padding:.05rem .5em;border-radius:var(--pill);
 background:color-mix(in srgb,var(--st,var(--muted)) 15%,transparent);color:var(--st,var(--muted));
 border:1px solid color-mix(in srgb,var(--st,var(--muted)) 32%,transparent);white-space:nowrap}
/* composition: filter toolbar + one compact collapsible table */
.comptools{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;margin:.3rem 0 .6rem}
.comptools input[type=search]{flex:1 1 13rem;min-width:9rem;padding:.35rem .7rem}
.filtlbl{font-size:.72rem;color:var(--muted)}
.filt{cursor:pointer;font:inherit;font-size:.75rem;padding:.26rem .68rem;border-radius:var(--pill);
 border:1px solid var(--border);background:var(--bg);color:var(--muted);transition:all var(--dur) var(--ease)}
.filt:hover{border-color:var(--border-strong)}
.filt.on{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
.count{font-size:.73rem;color:var(--muted);font-variant-numeric:tabular-nums}
.comptblwrap{border:1px solid var(--border);border-radius:var(--radius);overflow:visible}
table.comp{width:100%;border-collapse:separate;border-spacing:0;font-size:.85rem}
table.comp th,table.comp td{padding:.4rem .55rem;border-bottom:1px solid var(--border);text-align:left;vertical-align:middle}
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
td.tmodel input{width:6.5rem;padding:.22rem .45rem;font-size:.8rem}
td.tskills{min-width:15rem}
.comp-review{display:flex;align-items:center;gap:.3rem;margin-left:auto;font-weight:400;color:var(--muted);font-size:.72rem}
.comp-review input{width:8rem;padding:.2rem .45rem;font-size:.78rem}
.comp .chipwrap{flex-direction:row;flex-wrap:wrap;align-items:center;gap:.25rem}
.comp .chips{gap:.25rem}
.comp .combo{flex:1 1 8rem;min-width:7rem}
@media(max-width:48rem){.comptblwrap{overflow-x:auto}html,body{overflow-x:hidden}}
</style></head><body>
<div class=top>
 <div><h1>audit · control panel</h1><p class=sub id=proj></p></div>
 <button class="btn small" id=theme title="light/dark">☾</button>
</div>
<div class=tabs>
 <button class="tab on" data-t=guards>Guards &amp; paths</button>
 <button class="tab" data-t=comp>Composition</button>
 <button class="tab" data-t=over>Overview</button>
</div>
<div id=guards></div>
<div id=comp class=hidden></div>
<div id=over class=hidden></div>
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
 for(const id of['guards','comp','over'])$('#'+id).classList.toggle('hidden',id!==t.dataset.t);});
function toast(msg,kind){const t=$('#toast');t.textContent=msg;t.className='show '+(kind||'');
 setTimeout(()=>t.className=t.className.replace('show','').trim(),2600);}
function findingsBox(res){const box=el('div');
 if(res.findings&&res.findings.length)box.append(el('div',{class:'findings err'},'✗ '+res.findings.join(' · ')));
 if(res.warnings&&res.warnings.length)box.append(el('div',{class:'findings warn'},'! '+res.warnings.join(' · ')));
 if(res.ok&&!(res.warnings&&res.warnings.length))box.append(el('div',{class:'findings ok'},'✓ saved'));
 return box;}
async function boot(){STATE=await api('GET','/api/state');REG=await api('GET','/api/registry');
 renderGuards();renderComp();renderOver();}
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
  phaseEls.push({id:ph.id,title:ph.title||'',status:ph.status||'',tr:pr,tasks:taskEls});
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
   const pText=hit(P.id+' '+P.title,term);let anyT=false;
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
// ---------- Overview ----------
function renderOver(){const c=$('#over');c.textContent='';const r=STATE.rollup;const card=el('div',{class:'card'});
 if(!r){card.append(el('div',{class:'mut'},'No manifest at '+STATE.manifestPath+'. Run /audit:init.'));c.append(card);return;}
 const vstate=r.valid?el('div',{class:'findings ok'},'✓ manifest valid ('+r.warnings+' warnings)'):
   el('div',{class:'findings err'},'✗ '+r.findings+' finding(s): '+(STATE.manifestFindings||[]).join(' · '));
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
  card.append(el('div',{class:'row'},el('span',{class:'mono',style:'flex:0 0 3rem'},p.id),
   el('span',{style:'flex:1 1 10rem'},p.title||''),el('span',{class:'badge'},p.status||''),
   runBadge,
   el('span',{class:'bar'},el('i',{style:'width:'+pct+'%'})),el('span',{class:'mut'},p.done+'/'+p.total)));});
 const t=r.tasks,b=r.bugs;
 card.append(el('h2',{},'Totals'),el('div',{class:'row'},
   el('span',{class:'chip'},'tasks '+t.total),el('span',{class:'chip'},'bugs '+b.total),
   el('span',{class:'chip'},'open bugs '+b.open),el('span',{class:'chip'},'ready '+ (r.ready||[]).length)));
 c.append(card);}
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
