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
import json
import os
import secrets
import signal
import socket
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_REL = ".claude/audit.config.json"

sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _ui_theme as _theme   # noqa: E402  (tokens + labels shared with the report)
import _help                # noqa: E402  (schema-sourced field help + concept topics)
import _panel_settings       # noqa: E402  (settings-form schema + write allow-lists)
import _panel_discovery      # noqa: E402  (skills/agents/MCP registry scan)
import _panel_state          # noqa: E402  (the read-side payloads: state/areas/policy/journal/usage)
import _panel_write          # noqa: E402  (the write path: locks, change rows, journal, writers)
import _panel_page           # noqa: E402  (the assembled page: UI_HTML + UI_TEMPLATE)

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

# The panel's READ side -- every payload `GET /api/*` answers with, plus the path
# safety, viewer identity, core-module loading and lock detection those payloads
# rest on -- lives in _panel_state.py (P12.3). Aliased here so every downstream
# reference in this file (the GET routes, the write path's own use of `_cores`,
# `_within`, `read_config`, `_manifest_path`, `_read_json` and `_journalmod`, and
# the selftest below) keeps working unchanged. See that module's docstring for why
# each shared name moved rather than being duplicated.
_load = _panel_state._load
_cores = _panel_state._cores
_defaults = _panel_state._defaults
_within = _panel_state._within
_config_path = _panel_state._config_path
_declared_as_of = _panel_state._declared_as_of
_manifest_path = _panel_state._manifest_path
_viewer = _panel_state._viewer
_read_json = _panel_state._read_json
read_config = _panel_state.read_config
_areas_of = _panel_state._areas_of
_bugs_view = _panel_state._bugs_view
_skills_of = _panel_state._skills_of
_composition_view = _panel_state._composition_view
areas_state = _panel_state.areas_state
_JOURNAL = _panel_state._JOURNAL
_journalmod = _panel_state._journalmod
JOURNAL_PAGE = _panel_state.JOURNAL_PAGE
journal_state = _panel_state.journal_state
help_state = _panel_state.help_state
help_field = _panel_state.help_field
_policy_rules = _panel_state._policy_rules
_policy_enforcement = _panel_state._policy_enforcement
_policy_areas_view = _panel_state._policy_areas_view
policy_state = _panel_state.policy_state
_active_area_tags = _panel_state._active_area_tags
_audit_lock_dir = _panel_state._audit_lock_dir
_audit_lock_held = _panel_state._audit_lock_held
_lockmod = _panel_state._lockmod
_lock_info = _panel_state._lock_info
_run_status = _panel_state._run_status
usage_state = _panel_state.usage_state
report_paths = _panel_state.report_paths
render_report = _panel_state.render_report
build_state = _panel_state.build_state

# The panel's WRITE side -- the lock a save takes, the change rows it echoes, the
# journal row it leaves and the four writers themselves -- lives in _panel_write.py
# (P12.4). Aliased here so the PUT routes, the fixtures the selftest below still
# builds, and anything that spelled these names in this file keep working
# unchanged. `_atomic_write_json` moved with them: it is the one write the read
# side never makes, and the wrapper (not `_mio.atomic_write_json` at each call
# site) is what keeps this panel's byte shape stated once.
_atomic_write_json = _panel_write._atomic_write_json
write_policy = _panel_write.write_policy
# th (F-P-6): the Appearance tab's two calls.
theme_state = _panel_write.theme_state
write_theme = _panel_write.write_theme
write_areas = _panel_write.write_areas
write_ado = _panel_write.write_ado
_panel_session = _panel_write._panel_session
_acquire_write_lock = _panel_write._acquire_write_lock
_release_write_lock = _panel_write._release_write_lock
_flat_paths = _panel_write._flat_paths
_config_changes = _panel_write._config_changes
_composition_changes = _panel_write._composition_changes
_fmt_change = _panel_write._fmt_change
_journal = _panel_write._journal
write_config = _panel_write.write_config
_reject_unknown = _panel_write._reject_unknown
apply_composition_patch = _panel_write.apply_composition_patch
_touched_phase_ids = _panel_write._touched_phase_ids
_write_back = _panel_write._write_back
apply_composition = _panel_write.apply_composition


# --- the assembled page ---------------------------------------------------------
# The page itself -- the eight-substitution chain that turns _panel_ui.raw_template()
# into what the browser gets -- and the ~283 selftest cases that assert about the
# CSS and JS in it live in _panel_page.py. They are claims about ui/panel.css and
# ui/panel.js, not about this HTTP server, and they were three quarters of this
# file. Aliased here so `do_GET` and the cases that mix a page claim with a server
# call keep spelling the same two names.
#
# UI_TEMPLATE still carries the `/*__THEME_TOKENS__*/` marker, on purpose: do_GET
# substitutes THIS project's theme into it per request. UI_HTML is the same
# finished page wearing the default. See _panel_page.py's docstring for why the
# order that produces the pair is load-bearing, and `pg1` there for the case that
# goes red if the snapshot point moves.
UI_HTML = _panel_page.UI_HTML
UI_TEMPLATE = _panel_page.UI_TEMPLATE


def _src_of_this_file():
    """This module's own source — for the selftests that must assert a server-side
    construct (a route, a call order) rather than a rendered string."""
    with open(__file__, encoding="utf-8") as fh:
        return fh.read()


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
                # th (F-P-6): the token block is swapped per REQUEST, not at
                # import: a theme is a file on disk, and the reader who just
                # saved one reloads to see it. The default costs one string
                # compare (resolve_theme finds nothing and hands back TOKEN_CSS
                # itself), so the ordinary case pays nothing for the feature.
                css, _tinfo = _theme.token_css_for(
                    project, _panel_write.read_config(project))
                html = UI_TEMPLATE.replace("/*__THEME_TOKENS__*/", css).replace(
                    "__AUDIT_TOKEN__", _js(token)).replace(
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
            if path == "/api/theme":
                self._json(200, theme_state(project)); return
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
            if path == "/api/ado":
                self._json(200, write_ado(project, body)); return
            if path == "/api/policy":
                self._json(200, write_policy(project, body)); return
            if path == "/api/theme":
                self._json(200, write_theme(project, body)); return
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

    The token is a live credential for a localhost server, and this plugin
    treats it as one: the pidfile holding it gets its ignore rule written by
    _ensure_pidfile_ignored (claimed-but-never-written until 0.35 - found on
    a real repo by `git check-ignore`). Printing it to a terminal that Claude
    Code transcribes was the same leak by a different route.

    Matches `t=` at the start of the string as well as after `?`/`&`. A redactor that
    passes its input through unchanged when the shape is unexpected is worse than no
    redactor at all, so the pattern is deliberately looser than the one URL this is
    called with today."""
    try:
        import re as _re
        return _re.sub(r"((?:^|[?&])t=)[^&\s]*", r"\1<hidden>", str(url))
    except Exception:
        return "http://127.0.0.1/?t=<hidden>"


def _ensure_pidfile_ignored(project):
    """Write the ignore rule the status line used to merely CLAIM existed.

    The pidfile carries a live session token, and "it is gitignored; keep it
    that way" shipped for versions while nothing anywhere wrote the rule —
    `git check-ignore` on a real repo came back empty, one `git add .claude`
    from putting the token in history. The rule is a single targeted line in
    `.claude/.gitignore`; never a blanket ignore, because audit.config.json
    and settings.json beside it are exactly what a team SHOULD commit (the
    file itself is committable and shares the hygiene). Returns True when the
    rule is in place, False when it could not be ensured — callers must warn
    then, not claim."""
    try:
        path = _pidfile(project)
        base = os.path.basename(path)
        gi = os.path.join(os.path.dirname(path), ".gitignore")
        try:
            with open(gi, "r", encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            content = None
        if content is not None \
                and base in [ln.strip() for ln in content.splitlines()]:
            return True
        with open(gi, "a", encoding="utf-8") as fh:
            if content is None:
                fh.write("# audit plugin: the panel pidfile holds a live "
                         "session token\n")
            elif content and not content.endswith("\n"):
                fh.write("\n")
            fh.write(base + "\n")
        return True
    except Exception:
        return False


def _write_pidfile(project, info):
    path = _pidfile(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _ensure_pidfile_ignored(project)
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
        if _ensure_pidfile_ignored(project):
            print("the full URL (with its session token) is in "
                  ".claude/audit-panel.json — it is gitignored; keep it that way")
        else:
            print("the full URL (with its session token) is in "
                  ".claude/audit-panel.json — WARNING: could not write the "
                  "ignore rule; add `audit-panel.json` to .claude/.gitignore "
                  "before anything commits it")
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
    # scrollback and in the Claude transcript — the same value whose pidfile gets
    # its ignore rule written by _ensure_pidfile_ignored. So it is printed only
    # when the caller has to open the URL by hand (--no-open); in the default flow
    # the browser is handed the URL directly and the terminal shows a redacted form.
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



# --- selftest -------------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

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

    # The write path's own cases -- the config and composition writers, the sharded
    # write-back, the lock refusal, the areas and policy PUTs, the change rows and
    # the journal -- moved to _panel_write.py's selftest (P12.4), with their labels.
    # The FIXTURE they built stays here: build_state, the viewer, runStatus and the
    # composition view below all read this project, and they are claims about what
    # the server serves rather than about what a save writes.
    write_config(proj, {"trivialLineThreshold": 40})
    mpath = _manifest_path(proj, read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T",
                               "status": "pending"}]}]})
    apply_composition(proj, {"meta": {"reviewSkill": "user-skill"},
                             "tasks": {"P1.1": {"skills": ["user-skill"],
                                                "model": "opus"}}})

    # --- v0.31: the help endpoint ------------------------------------------------
    # The drawer that consumes this lands with panel c8; the endpoint ships now, and
    # is exercised here rather than left as untested code until it has a caller —
    # the one thing v0.29's journal call site taught, in the other direction.
    _help_pay = help_state()
    # Read the handler's own source, sliced at the method boundaries: counting the
    # string over the whole file would count this check as a route. THIS FILE, not
    # _panel_page.py — do_GET/do_PUT/do_POST stayed here when the page moved, so the
    # slices still read the code they are about.
    #
    # WARNING, DEFINITION ORDER: `_write_src` runs from `def do_PUT` to
    # `def _free_port`, i.e. it deliberately spans do_PUT AND do_POST — every route
    # that WRITES — and it ends there only because `_free_port` happens to be the
    # next top-level def after the handler class. Move `_free_port` (it reads like
    # lifecycle code and would look at home beside the pidfile) and this slice
    # silently swallows do_POST, the whole rest of the file, and the checks below;
    # the "…not in _write_src" halves then pass by being vacuously true rather than
    # by being right. If you move it, re-point the boundary at whatever ends the
    # class, and prove the case still goes red by putting `/api/help` in do_PUT.
    _hsrc = _src_of_this_file()
    _get_src = _hsrc.split("def do_GET")[1].split("def do_PUT")[0]
    _write_src = _hsrc.split("def do_PUT")[1].split("def _free_port")[0]
    check("GET /api/help is a route, and only a GET: help is a document, and a "
          "drawer that could write one would be a second config writer",
          'if path == "/api/help"' in _get_src and "/api/help" not in _write_src)
    check("PUT /api/ado is a write route, and only a write - the connector card "
          "saves through it, mirroring /api/areas; its read side rides "
          "composition.adoStatus in /api/state",
          'if path == "/api/ado"' in _write_src and "/api/ado" not in _get_src)
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
          "so an 'Ask audit:guide' hint cannot offer a capability it does not have",
          (_help_pay["agent"] or {}).get("name") == "guide"
          and (_help_pay["agent"] or {}).get("readOnly") is True
          and (_help_pay["agent"] or {}).get("model") == "haiku")
    check("the payload is documentation, not state: it names no path on this "
          "machine, so it cannot be read as a report about this project",
          _HERE not in json.dumps(_help_pay)
          and os.path.dirname(_HERE) not in json.dumps(_help_pay))

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
    # _lock_info's own cases (what a lock file says, and whether the run behind it
    # is alive) moved to _panel_state.py (P12.3).
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

    check("UI token injected as a quoted JS string",
          'const TOKEN="abc123"' in UI_HTML.replace("__AUDIT_TOKEN__", _js("abc123")))
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
    check("gt: the server block behind that card is _run_status's, with the "
          "tier computed by the hooks' own functions",
          isinstance((_run_status(proj, read_config(proj), {})
                      .get("gate") or {}).get("mode"), str)
          and "plan_gate_mode" in
          open(os.path.join(_HERE, "_panel_state.py"),
               encoding="utf-8").read().split("def _gate_block")[1]
                                       .split("def _run_status")[0])
    check("usage.bands is a legitimate key now, so the pair the README documents "
          "no longer warns from the plugin's own validator",
          "bands" in _vc.KNOWN_USAGE
          and _vc.validate_config(
              {"usage": {"bands": {"highUSD": 4, "outlierUSD": 12}}}) == ([], []))

    check("th-p2 the page is dressed in THIS project's theme per request, and "
          "the template keeps the marker so it can be",
          '"/*__THEME_TOKENS__*/"' in _hsrc
          and "UI_TEMPLATE.replace(" in _hsrc
          and "/*__THEME_TOKENS__*/" in UI_TEMPLATE
          and "/*__THEME_TOKENS__*/" not in UI_HTML)
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

    # --- report export ------------------------------------------------------------
    # There is deliberately no path parameter on /report: the location is derived
    # from the project's own config, so there is nothing to traverse with. The
    # cases that RENDER a report moved to _panel_state.py (P12.3); what stays is
    # the route that reaches it and the button that opens it.
    #
    # F-P-8: this searched the WHOLE of this file's own source, so each literal
    # found the assertion line spelling it — the check matched itself, and renaming
    # the route in do_POST left the suite green while the routes it claims to guard
    # went unguarded. It reads the handler slices instead, which end at
    # `def _free_port` well before this line. That makes the DEFINITION ORDER
    # warning above this case's business too, and in the harder direction: a slice
    # that swallowed the rest of the file would swallow these literals as well, and
    # the check would go back to finding itself.
    check("the export route derives its path and takes no parameter — POST "
          "/api/report renders, GET /report serves what was written",
          'if path == "/api/report"' in _write_src
          and 'if path == "/report"' in _get_src
          and "paths = report_paths(project)" in _get_src)

    # --- v0.34 C5 (lv): live data - polling + fingerprint -----------------------
    # The fingerprint's own cases (stability, what moves it) live in
    # _panel_state.py; the out-of-band-write round trip is driven in
    # capture-screenshots.mjs --check. These pin the client wiring.
    check("lv: the fingerprint rides the runstatus PAYLOAD and stays OUT of "
          "runStatusKey - the D9 claim (the poll never has to refetch full "
          "state) stays literally true of the poll itself. gt: the GATE block "
          "is IN the key ({i,p,g}), so a fresh gate event repaints the card "
          "from the same payload",
          "function runStatusKey(rs){return JSON.stringify(rs&&{i:rs.index,"
          "p:rs.phases,g:rs.gate});}" in UI_HTML
          and isinstance(_run_status(proj, read_config(proj), {})
                         .get("fingerprint"), str))

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

    # --- (i) the pidfile ignore rule is WRITTEN, not just claimed ---------------
    # The status line has said "it is gitignored; keep it that way" since the
    # panel learned to redact the URL - but nothing ever wrote the rule, and on
    # a real repo `git check-ignore` proved the token file one `git add .claude`
    # away from history. The plugin now ensures the rule itself.
    _gi = os.path.join(proj, ".claude", ".gitignore")
    try:
        os.remove(_gi)
    except OSError:
        pass
    _write_pidfile(proj, {"pid": 1, "port": 1, "url": "http://x"})
    _gi_lines = []
    try:
        with open(_gi, encoding="utf-8") as fh:
            _gi_lines = [ln.strip() for ln in fh.read().splitlines()]
    except OSError:
        pass
    check("i1 writing the pidfile ensures a targeted .claude/.gitignore rule",
          "audit-panel.json" in _gi_lines)
    check("i2 the rule is targeted - nothing else in .claude is ignored",
          not any("*" == ln or "audit.config.json" in ln or "settings" in ln
                  for ln in _gi_lines))
    with open(_gi, "w", encoding="utf-8") as fh:
        fh.write("node_modules")            # pre-existing, NO trailing newline
    check("i3 appending to a newline-less .gitignore does not glue lines",
          _ensure_pidfile_ignored(proj)
          and open(_gi, encoding="utf-8").read().splitlines()[0] == "node_modules")
    _n_before = open(_gi, encoding="utf-8").read().count("audit-panel.json")
    _ensure_pidfile_ignored(proj)
    check("i4 re-ensuring is idempotent - no duplicate lines",
          open(_gi, encoding="utf-8").read().count("audit-panel.json")
          == _n_before == 1)
    _proj_bad = os.path.join(tmp, "badproj")
    os.makedirs(_proj_bad, exist_ok=True)
    with open(os.path.join(_proj_bad, ".claude"), "w", encoding="utf-8") as fh:
        fh.write("")                        # .claude is a FILE: rule unwritable
    check("i5 an unwritable rule reports False so callers warn instead of "
          "claiming", _ensure_pidfile_ignored(_proj_bad) is False)

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
