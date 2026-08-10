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
import re
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
import _panel_ui             # noqa: E402  (UI_HTML's markup/CSS/JS, off disk as real files)
import _panel_settings       # noqa: E402  (settings-form schema + write allow-lists)
import _panel_discovery      # noqa: E402  (skills/agents/MCP registry scan)
import _panel_state          # noqa: E402  (the read-side payloads: state/areas/policy/journal/usage)
import _panel_write          # noqa: E402  (the write path: locks, change rows, journal, writers)

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
write_areas = _panel_write.write_areas
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


def _src_of_this_file():
    """This module's own source — for the selftests that must assert a server-side
    construct (a route, a call order) rather than a rendered string."""
    with open(__file__, encoding="utf-8") as fh:
        return fh.read()


# The stylesheet lints live in _ui_theme, beside the tokens they police, so the
# report and the panel are held to exactly the same rules by the same code.
_undeclared_css_vars = _theme.undeclared_css_vars
_theme_asymmetric_vars = _theme.theme_asymmetric_vars
_themes_missing_color_scheme = _theme.themes_missing_color_scheme
_mangled_css_escapes = _theme.mangled_css_escapes


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

    # c6's server half (the change rows a save echoes) and the journal call site
    # moved to _panel_write.py (P12.4). What stays below and further down is the
    # browser's half of the same contract, pinned against UI_HTML.

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
    check("the UI badges an abandoned lock differently from a running one",
          "no live run" in UI_HTML and ".badge.held" in UI_HTML)
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
    # Python by the SAME functions the rollup counts with — pinned in
    # _panel_state.py (P12.3). What stays here is the other half of that claim:
    # the browser being handed the verdicts rather than deriving its own.
    check("the browser is handed those verdicts rather than re-deriving them",
          "b.open&&b.high" in UI_HTML and "STATE.bugs" in UI_HTML
          and "severity" not in UI_HTML[UI_HTML.index("const rows=bugs.filter"):
                                        UI_HTML.index("const rows=bugs.filter") + 120])

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
    # from the project's own config, so there is nothing to traverse with. The
    # cases that RENDER a report moved to _panel_state.py (P12.3); what stays is
    # the route that reaches it and the button that opens it.
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

    # usage_state's own cases (facts, the roll-up cap, the declared rate basis)
    # moved to _panel_state.py (P12.3); everything above is the tab that reads it.

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
