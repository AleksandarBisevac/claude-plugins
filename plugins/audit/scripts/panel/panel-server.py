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

Exit: Ctrl-C stops the server. --selftest reports where its cases went.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_panel_server.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. Three of them slice THIS file's source at the
handler's own method boundaries and at the first top-level def after the class, to
tell a read route from a write one. Those boundaries are a contract, and
`_harness.between()` raises rather than widening a slice when one moves. The
boundary names are deliberately NOT spelled out in this docstring: a marker
written here would be found HERE, above the code, and the slices would run over
prose instead of over routes - which is exactly the self-matching bug (F-P-8) that
made one of those cases find its own assertion line.
"""
import argparse
import atexit
import json
import os
import secrets
import signal
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _ui_theme as _theme   # noqa: E402  (tokens + labels shared with the report)
import _panel_settings       # noqa: E402  (settings-form schema + write allow-lists)
import _panel_discovery      # noqa: E402  (skills/agents/MCP registry scan)
import _panel_state          # noqa: E402  (the read-side payloads: state/areas/policy/journal/usage)
import _panel_write          # noqa: E402  (the write path: locks, change rows, journal, writers)
import _panel_page           # noqa: E402  (the assembled page: UI_HTML + UI_TEMPLATE)

# The settings-form schema and the write-path allow-lists are settings-shape
# knowledge, not server plumbing — they live in _panel_settings.py (P12.1).
# Aliased here so every downstream reference in this file (the substitution
# chain below, `_composition_changes`, `_reject_unknown`, the cases in tests/)
# keeps working unchanged.
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
# call, the fixture-dir cases in tests/) keeps working unchanged.
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
# the cases in tests/) keeps working unchanged. See that module's docstring for why
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
# (P12.4). Aliased here so the PUT routes, the fixtures the cases in tests/ still
# build, and anything that spelled these names in this file keep working
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
# into what the browser gets -- and the cases in tests/ that assert about the
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
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("panel-server.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_panel_server.py - run that file instead.")
        return 0
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



if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    sys.exit(main(sys.argv[1:]))
