#!/usr/bin/env python3
"""Record the README demo GIF - a real Claude Code session meeting the plan gate - and
check, without a session, that the gate still says what the recording shows.

WHY THIS EXISTS. Every other artifact in this repo shows the product at rest - a
rendered report, a screenshot of the panel. The thing the product actually IS, an edit
being refused inside a session, cannot be shown by a still: the refusal is an event.

WHAT IS RECORDED. `tools/demo-gate.tape` drives VHS through a real `claude` session in
a demo project built fresh at a fixed neutral path (`FIXTURE_DIR`), with a copy of
this checkout's plugin loaded through --plugin-dir from a neutral path beside it
(`KIT_DIR`) - a path under a home directory would put a user name on screen. The user
types /audit:status, asks for an edit the plan covers and sees it go through, then
asks for an edit no task covers and sees Claude Code render the plan gate's deny.
Nothing on screen is drawn by this file.

    python3 tools/capture-demo-gif.py --record [--dry-run] [--out docs/screenshots/demo-gate.gif]
    python3 tools/capture-demo-gif.py --check  [--out docs/screenshots/demo-gate.gif]

--record needs `vhs` and a logged-in `claude`, and costs a short paid model session.
With CLAUDE_CODE_OAUTH_TOKEN set it hands the take a Claude Code config of its own
under the kit, removed afterwards; without it the take runs against the operator's
config, and the tool prints what it left there (`config_plan()`). It refuses to
start when `claude auth status --json` names no account or `claude plugin list
--json` gives no answer. It builds the fixture and the kit, runs the tape, and only
then decides whether the recording may ship: the operator's installed plugins must
be what they were, Claude must have tried to edit the out-of-plan file, the gate fed
that SAME payload again must refuse it, the refusal must be on screen at least as far
as its first line, and no frame of VHS's text output may carry the recording host's
user name, home path, machine name, git identity, the account's email or
organisation, or an email address. That text is what is scanned, not the GIF's
pixels; a take whose Wait failed is refused before the scan, on VHS's exit and the
screens its log keeps. Any failure writes nothing and keeps the evidence in a temp
directory it names. --dry-run builds everything, validates the tape, prints the
commands, and starts no session.

--check needs neither: CI runs it. It rebuilds the fixture, feeds `require-plan.py`
the out-of-plan payload the recording captured, and fails naming the GIF when the
refusal the gate prints now differs from the one recorded, when the committed GIF's
sha256 differs from the record, or when there is no record to compare. The pixels are
never compared, for the reason the screenshots' are not: rasterisation differs by host.

WHERE THE RECORD LIVES. `docs/screenshots/captured-at.json`, under its own top-level
key (`GIF_KEY`), beside the screenshots' records that `capture-screenshots.mjs` keeps
and carries through its own merge.
"""
import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, "plugins", "audit", "hooks")
SCRIPTS = os.path.join(REPO, "plugins", "audit", "scripts")
PLUGIN_SRC = os.path.join(REPO, "plugins", "audit")
TAPE = os.path.join(REPO, "tools", "demo-gate.tape")
PY = sys.executable

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import _loader  # noqa: E402  (reachable now that SCRIPTS is on the path)
import _output  # noqa: E402
_output.install_path()
import _manifest_rules  # noqa: E402  (the rules every manifest writer validates with)
import _manifest_vocab  # noqa: E402


def resolve_script(basename):
    """The absolute path of `basename` WHEREVER it sits under the scripts tree.

    NOT A COPY OF THE RESOLUTION RULE, AND THAT IS THE WHOLE POINT OF THE FUNCTION.
    `capture-screenshots.mjs` had to grow its own index because `.mjs` cannot import
    Python; this file is Python, so it asks the module that already owns the answer and
    inherits all three of `script_path()`'s refusals unchanged — nothing found (naming
    the basename and how many files were searched), two files claiming the name (naming
    both), a value carrying a directory separator (naming the value). A second Python
    walk here would be a fifth statement of one rule with nothing comparing it to the
    other four.

    IT IS STILL A NAMED FUNCTION rather than an inline call, so that this file has one
    place where "which script" is decided, exactly as the JavaScript tool does, and so a
    reader meeting either tool finds the same shape.

    WHY IT REPLACED A JOIN. Joining the SCRIPTS constant with a filename looks one
    directory too high the moment that script is filed under a domain folder, and the fix
    that suggests itself — inserting the folder's name into the join — hard-codes a label
    into a consumer. The folders under the scripts tree are labels, not namespaces. No
    such join is left in this file, and `test__refs.py` asserts that.

    The `require-plan.py` join below is deliberately left alone: the hooks tree is not
    being reorganised, it is flat by design and has to stay reachable from a launcher
    that knows only its directory, so a resolver there would buy nothing.
    """
    return _loader.script_path(basename)


# --- where the recording happens ------------------------------------------------
# Fixed, neutral and outside every home directory: Claude Code prints the project
# path in its header and the plugin path in every Bash line it runs, so whatever these
# are is what the GIF shows. The tape names the same three paths; `tape_problems()`
# holds the two files to each other.
FIXTURE_DIR = "/tmp/acme-store-demo"
KIT_DIR = "/tmp/acme-store-demo-kit"
KIT_PLUGIN = KIT_DIR + "/audit"
KIT_SETTINGS = KIT_DIR + "/settings.json"
TAP_NAME = "payloads.jsonl"
VHS_GIF = "demo-gate.gif"
VHS_TEXT = "demo-gate.txt"
MODEL = "sonnet"
OUT_OF_PLAN_REL = "src/billing.ts"
IN_PLAN_REL = "src/checkout.ts"
EDIT_TOOLS = ("Edit", "Write", "MultiEdit")

SIDECAR = "captured-at.json"
GIF_KEY = "gifs"
GIF_NAME = "demo-gate.gif"
_FIXTURE_TOKEN = "<demo-project>"
REPLAY_SESSION = "demo-replay"
# Where a user's plan lives when nothing says otherwise: the plugin's own default
# `manifestPath`. The demo keeps it there and writes no config, so the session sees
# the layout a user gets, and the commands find the plan the way they would there.
MANIFEST_REL = "docs/audit/audit-plan.json"


# --- the demo project, and what the gate says about it --------------------------
def build_fixture(d):
    """A minimal but honest plan: one phase running, one task covering one file.

    The gate's behaviour depends entirely on this shape — a phase `in_progress` is
    what makes it deny rather than warn — so the fixture is the demo's premise and
    is written out here rather than described in a caption. The plan sits at the
    default `MANIFEST_REL` and no config names it."""
    os.makedirs(os.path.dirname(os.path.join(d, MANIFEST_REL)), exist_ok=True)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    subprocess.run(["git", "-C", d, "init", "-q"], capture_output=True)
    manifest = {
        "meta": {"version": 2, "repo": "acme-store", "title": "ACME Store security audit"},
        "phases": [{
            "id": "P2", "title": "Input validation", "status": "in_progress",
            "desiredOutcome": "Every request payload is validated before it reaches "
                              "business logic.",
            "tasks": [
                {"id": "P2.1", "title": "Validate the checkout payload",
                 "status": "in_progress", "model": "sonnet", "risk": "med",
                 "files": [IN_PLAN_REL]},
                {"id": "P2.2", "title": "Sanitize the product-search query",
                 "status": "pending", "model": "opus", "risk": "high",
                 "files": ["src/search.ts"]}]}],
        "bugs": []}
    manifest["fileIndex"] = derived_file_index(manifest)
    with open(os.path.join(d, MANIFEST_REL), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    for name in ("checkout.ts", "billing.ts"):
        with open(os.path.join(d, "src", name), "w", encoding="utf-8") as fh:
            fh.write("export function %s() {}\n" % name[:-3])


def derived_file_index(manifest):
    """{path: [task id, ...]} - every file each task claims, under the key the
    validator and the plan gate match on (`_manifest_vocab._strip_line_suffix`).

    A plan without it is one every writer refuses: the first full validation - the
    one `audit-task add` runs after its write - reports each task file missing from
    the index, and a demo session that follows the gate's advice to add a task
    meets that refusal on camera."""
    out = {}
    for phase in manifest.get("phases") or []:
        for task in phase.get("tasks") or []:
            for entry in task.get("files") or []:
                ids = out.setdefault(_manifest_vocab._strip_line_suffix(entry), [])
                if task["id"] not in ids:
                    ids.append(task["id"])
    return dict((k, out[k]) for k in sorted(out))


def plan_findings(manifest):
    """(findings, warnings) of the validation a manifest writer runs before keeping
    a write: the rules with the published schema bound in, as `audit-task` does."""
    schema, unreadable = _manifest_rules.load_validation_schema()
    findings, warnings = _manifest_rules.validate(manifest, schema=schema)
    return list(unreadable) + findings, warnings


def fire_payload(d, tool_name, tool_input, session):
    """Feed require-plan.py one PreToolUse payload; the deny reason, or None.

    None is what an allow looks like from the outside: nothing at all."""
    payload = {"session_id": session, "cwd": d, "hook_event_name": "PreToolUse",
               "tool_name": tool_name, "tool_input": tool_input}
    out = subprocess.run([PY, os.path.join(HOOKS, "require-plan.py")],
                         input=json.dumps(payload), capture_output=True, text=True,
                         env=dict(os.environ, CLAUDE_PROJECT_DIR=d))
    if not out.stdout.strip():
        return None
    try:
        return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    except (ValueError, KeyError, TypeError):
        return out.stdout.strip()


def fire_in_plan(d):
    """The edit the plan covers, as a payload of the shape Claude Code sends."""
    return fire_payload(d, "Edit", {
        "file_path": os.path.join(d, IN_PLAN_REL),
        "old_string": "export function checkout() {}",
        "new_string": "export function checkout(payload: unknown) {\n"
                      "  assertCheckoutPayload(payload);\n}"}, "demo-in-plan")


def replay(stored, d):
    """The gate's answer to a stored payload, replayed against the fixture at `d`.

    Both the project and the payload's paths are given the RESOLVED spelling of `d`.
    Given the macOS temp symlink in one and the resolved path in the other, the gate
    names the file as a climb out of the project, and that text differs by host and
    by run. Whether the replay matches what the session showed is not assumed here:
    `verify_recording()` refuses a recording whose screen does not show the replayed
    refusal."""
    real = os.path.realpath(d)
    live = unscrub_value(stored, real)
    return fire_payload(real, live.get("tool_name"), live.get("tool_input"),
                        REPLAY_SESSION)


def fixture_roots(d):
    """Both spellings of the fixture path, longest first: on macOS the path asked for
    and the path the kernel resolves differ by a symlink, and either can reach a
    payload or a refusal."""
    return sorted(set([d, os.path.realpath(d)]), key=len, reverse=True)


def scrub_value(value, roots):
    """`value` with every fixture root in every string replaced by the token, so a
    record taken at one path compares with a replay at another."""
    if isinstance(value, str):
        for root in roots:
            value = value.replace(root, _FIXTURE_TOKEN)
        return value
    if isinstance(value, list):
        return [scrub_value(v, roots) for v in value]
    if isinstance(value, dict):
        return dict((k, scrub_value(v, roots)) for k, v in value.items())
    return value


def unscrub_value(value, d):
    """The inverse of `scrub_value` for a fixture rebuilt at `d`."""
    if isinstance(value, str):
        return value.replace(_FIXTURE_TOKEN, d)
    if isinstance(value, list):
        return [unscrub_value(v, d) for v in value]
    if isinstance(value, dict):
        return dict((k, unscrub_value(v, d)) for k, v in value.items())
    return value


# --- reading what the session did ----------------------------------------------
def parse_payloads(text):
    """Every JSON object in the tap file, in order; ([objects], [unparsed fragments]).

    The tap appends stdin as it arrives, so objects may or may not be separated by a
    newline. A fragment that does not parse is returned rather than dropped: a tap
    that read half a payload is a recording that cannot be replayed."""
    dec = json.JSONDecoder()
    objs, bad, i, n = [], [], 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            nl = text.find("\n", i)
            end = n if nl < 0 else nl
            bad.append(text[i:end])
            i = end
            continue
        if isinstance(obj, dict):
            objs.append(obj)
        i = end
    return objs, bad


def out_of_plan_payload(payloads, rel=OUT_OF_PLAN_REL):
    """{"tool_name", "tool_input"} of the first edit aimed at `rel`, or None.

    Only those two fields are kept: the rest of a PreToolUse payload carries the
    session id and a transcript path under the recording host's home directory, and
    none of it changes what the gate decides."""
    suffix = "/" + rel
    for p in payloads:
        tool = p.get("tool_name")
        ti = p.get("tool_input")
        if tool not in EDIT_TOOLS or not isinstance(ti, dict):
            continue
        path = str(ti.get("file_path") or "").replace("\\", "/")
        if path == rel or path.endswith(suffix):
            return {"tool_name": tool, "tool_input": ti}
    return None


# Characters Claude Code draws around a tool result. None can occur in the refusal,
# which is ASCII, so removing them from the screen cannot remove a word of it.
_DECORATION = set(u"⎿│⏺●─╭╮╰╯…")


def screen_frames(text):
    """VHS's text output split into frames.

    VHS separates frames with a line drawn of one box character, and Claude Code
    draws the same line around its input box, so a "frame" here may be part of one;
    the transcript a refusal sits in is never cut, because it lies between two such
    lines either way."""
    frames, cur = [], []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and set(stripped) == set(u"─"):
            frames.append("\n".join(cur))
            cur = []
            continue
        cur.append(line)
    frames.append("\n".join(cur))
    return [f for f in frames if f.strip()]


def _compact(text, drop):
    return "".join(ch for ch in text if not ch.isspace() and ch not in drop)


def shown_refusal(screen_text, refusal):
    """The longest leading part of `refusal` that one frame shows; "" when none does.

    Compared with every space and line break taken out on both sides, because the
    terminal re-wraps the refusal at its own width and may break a long token
    mid-word. The answer is cut from `refusal` itself, so it keeps the gate's own
    line breaks rather than the terminal's."""
    if not refusal:
        return ""
    idx = [i for i, ch in enumerate(refusal) if not ch.isspace()]
    target = "".join(refusal[i] for i in idx)
    best = 0
    for frame in screen_frames(screen_text):
        hay = _compact(frame, _DECORATION)
        lo, hi = best, len(target)
        if lo < hi and target[:lo + 1] not in hay:
            continue
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if target[:mid] in hay:
                lo = mid
            else:
                hi = mid - 1
        best = lo
    if best == 0:
        return ""
    return refusal[:idx[best - 1] + 1]


def first_line_shown(refusal, shown):
    """True when what the screen showed covers the refusal's whole first line - the
    line naming the gate, the reason and the file."""
    head = (refusal or "").split("\n")[0].rstrip()
    return bool(head) and len(shown.rstrip()) >= len(head)


# --- no personal data in any frame -------------------------------------------
# What the scan refuses is what the CLI's recording mode (IS_DEMO, documented as
# hiding the email and organisation name from the header and /status) promises to
# keep off screen, plus the host's own identity: so a take passing it is a take in
# which IS_DEMO did its job. The plan line beside the model is NOT refused - the
# recording mode keeps it on purpose, and the demo shows the header as a user sees
# it.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# A home directory of ANY user, not only the recording host's: macOS and Linux
# spellings, and the windows one.
HOME_PATH_RE = re.compile(r"(?<![\w.-])/(?:Users|home)/[A-Za-z0-9._-]+"
                          r"|\b[A-Za-z]:\\Users\\[^\\\s]+")
_MIN_MARKER = 3


def _git_identity(key):
    try:
        out = subprocess.run(["git", "config", "--global", key],
                             capture_output=True, text=True)
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def account_markers_from(status_json):
    """[(kind, value)] read from `claude auth status --json`'s answer; [] when it is
    not that answer. Only the email and organisation name are taken - the two fields
    the recording mode promises to hide."""
    try:
        body = json.loads(status_json or "")
    except ValueError:
        return []
    if not isinstance(body, dict):
        return []
    pairs = [("account email", body.get("email")),
             ("organisation name", body.get("orgName"))]
    return [(k, v) for k, v in pairs
            if isinstance(v, str) and len(v.strip()) >= _MIN_MARKER]


def account_markers(env, run=subprocess.run):
    """The logged-in account's email and organisation, asked of the CLI's own status
    command - which reads no secret into this process and starts no session - or []
    with the reason when it gives no answer. `env` is the take's own, so the account
    asked about is the one the session will show. `take_preconditions()` refuses a
    take on that reason: without the account's own values the scan could look only
    for the email pattern, and an organisation name has no pattern."""
    try:
        out = run(["claude", "auth", "status", "--json"],
                  capture_output=True, text=True, env=env)
    except OSError as exc:
        return [], "`claude auth status` could not run: %s" % (exc,)
    found = account_markers_from(out.stdout) if out.returncode == 0 else []
    if not found:
        return [], ("`claude auth status --json` named no account email or "
                    "organisation (exit %d)" % out.returncode)
    return found, None


def personal_markers():
    """[(kind, value)] - what would identify the recording host if it reached a frame.

    Read at record time from the host itself, never written down here: the values
    are the point, and a committed list of them would be the leak."""
    host = socket.gethostname() or ""
    pairs = [("user name", getpass.getuser()),
             ("home path", os.path.expanduser("~")),
             ("machine name", host),
             ("machine name", host.split(".")[0]),
             ("git user name", _git_identity("user.name")),
             ("git email", _git_identity("user.email")),
             ("this checkout's path", REPO)]
    return [(k, v) for k, v in pairs if v and len(v) >= _MIN_MARKER]


def pii_findings(text, markers):
    """Sorted kinds of personal data found in `text`; [] when none.

    The kind is reported and never the value: the finding is printed to a terminal
    and, in CI, to a public log."""
    low = (text or "").lower()
    kinds = set(k for k, v in markers if v.lower() in low)
    if EMAIL_RE.search(text or ""):
        kinds.add("an email address")
    if HOME_PATH_RE.search(text or ""):
        kinds.add("a home directory path")
    return sorted(kinds)


# --- the session's environment ------------------------------------------------
# Kept from the caller: the two variables that say WHICH login and config the CLI
# uses. Every other CLAUDE*/AUDIT_* variable is the recording host's own session
# leaking in - a child-session marker turns transcript saving off and says so in
# the footer, and a lock token would let the demo act as the caller.
_ENV_KEPT = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR")
_ENV_DROPPED_PREFIXES = ("CLAUDE", "AUDIT_")
# Added: IS_DEMO, documented in Claude Code's environment-variable reference as
# hiding the email and organisation name from the header and /status and skipping
# onboarding, "useful when streaming or recording a session"; and
# DISABLE_AUTOUPDATER, one of the two variables the CLI's updates-disabled check
# reads (read off the 2.1.292 binary), so no update notice reaches the footer. Only
# documented switches are shipped here: an undocumented one is a claim nothing backs.
_ENV_ADDED = (("IS_DEMO", "1"), ("DISABLE_AUTOUPDATER", "1"))


def session_env(environ, config_dir=None):
    """A new environment for the recording: `environ` without the caller's session
    markers, plus the demo's own switches. VHS hands it to the shell that launches
    `claude`, so the scrub is done once, before any process of the take starts.
    `config_dir`, when given, is the take's isolated config (`config_plan()`) and
    replaces whatever config dir the caller named."""
    out = dict((k, v) for k, v in environ.items()
               if k in _ENV_KEPT or not k.startswith(_ENV_DROPPED_PREFIXES))
    out.update(dict(_ENV_ADDED))
    if config_dir:
        out["CLAUDE_CONFIG_DIR"] = config_dir
    return out


# --- which Claude Code config the take writes into ------------------------------
# A session writes into its config: the folder-trust answer, its transcript, a
# plugin a recommendation dialog installed on a stray key. So the take gets a config
# of its own under the kit's scratch directory, removed with the kit, whenever it can
# authenticate there without an interactive login - which a CLAUDE_CODE_OAUTH_TOKEN
# in the environment provides. Claude Code's authentication page documents both
# halves (https://code.claude.com/docs/en/authentication): `claude setup-token`
# prints a token to set "as the `CLAUDE_CODE_OAUTH_TOKEN` environment variable
# wherever you want to authenticate", and with CLAUDE_CONFIG_DIR set "Each directory
# has its own settings, session history, and claude.ai login or API key" - the
# macOS Keychain entry included, keyed to that directory. Whether a session
# authenticated by the token alone writes a Keychain entry is not documented there.
# Without a token the take runs against the
# operator's own config, and `footprint_refusals()` and `leftover_lines()` say what
# it did there. Either way the operator's config is read before and after, so an
# isolation that leaked is a refusal rather than an assumption.
ISOLATED_CONFIG = KIT_DIR + "/claude-config"
_TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"


def config_plan(environ):
    """{"isolated", "configDir", "why"} - which config the take is handed."""
    if (environ.get(_TOKEN_VAR) or "").strip():
        return {"isolated": True, "configDir": ISOLATED_CONFIG,
                "why": "%s is set, so the take runs against its own config at %s, "
                       "removed afterwards" % (_TOKEN_VAR, ISOLATED_CONFIG)}
    return {"isolated": False, "configDir": None,
            "why": "%s is not set, so the take can authenticate only through your "
                   "own Claude Code config and runs against it; what it leaves "
                   "there is listed after the take" % (_TOKEN_VAR,)}


def seed_isolated_config(config_dir):
    """Create the take's config with onboarding marked complete, and nothing else.

    Without it the tape's first launch - the one that answers the trust question -
    meets the first-run onboarding instead and its Wait times out before any prompt
    is sent. `hasCompletedOnboarding` is not a documented key: it is the one the
    2.1.292 binary writes when onboarding finishes, and the one it seeds into the
    scratch configs it builds for itself. Trust is not seeded: the tape grants it
    through the CLI's own dialog, as a user would."""
    os.makedirs(config_dir)
    with open(os.path.join(config_dir, ".claude.json"), "w", encoding="utf-8") as fh:
        json.dump({"hasCompletedOnboarding": True}, fh)


def _row_key(row):
    return (row["id"], row["scope"], row.get("projectPath") or "")


def plugin_rows(list_json):
    """(rows, why) parsed from `claude plugin list --json`; rows None with the
    reason when the answer is not that list. Only what identifies an install and
    what a take could change are kept - id, scope, project, version, enabled."""
    try:
        body = json.loads(list_json or "")
    except ValueError as exc:
        return None, "`claude plugin list --json` did not answer JSON: %s" % (exc,)
    if not isinstance(body, list) or not all(
            isinstance(r, dict) and isinstance(r.get("id"), str)
            and isinstance(r.get("scope"), str) for r in body):
        return None, "`claude plugin list --json` did not answer a list of plugins"
    rows = [{"id": r["id"], "scope": r["scope"],
             "projectPath": r.get("projectPath") or "",
             "version": r.get("version"), "enabled": r.get("enabled")} for r in body]
    return sorted(rows, key=_row_key), None


def installed_plugins(env, run=subprocess.run):
    """(rows, why) - the plugins the config `env` names has installed."""
    try:
        out = run(["claude", "plugin", "list", "--json"],
                  capture_output=True, text=True, env=env)
    except OSError as exc:
        return None, "`claude plugin list --json` could not run: %s" % (exc,)
    if out.returncode != 0:
        return None, "`claude plugin list --json` exited %d" % out.returncode
    return plugin_rows(out.stdout)


def _where(row):
    place = "%s scope" % row["scope"]
    if row.get("projectPath"):
        place += " (project %s; run the undo there)" % row["projectPath"]
    return place


def plugin_changes(before, after):
    """[change, ...] between two `plugin_rows()` lists, each naming the plugin, its
    scope and the command that undoes it; [] when nothing changed."""
    old = dict((_row_key(r), r) for r in before)
    new = dict((_row_key(r), r) for r in after)
    out = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a is None:
            out.append("%s was installed at %s - undo: claude plugin uninstall %s "
                       "--scope %s" % (b["id"], _where(b), b["id"], b["scope"]))
        elif b is None:
            out.append("%s was uninstalled from %s - undo: claude plugin install %s "
                       "--scope %s" % (a["id"], _where(a), a["id"], a["scope"]))
        elif a["enabled"] != b["enabled"]:
            verb = "enable" if a["enabled"] else "disable"
            out.append("%s was %sd at %s - undo: claude plugin %s %s --scope %s"
                       % (b["id"], "disable" if a["enabled"] else "enable",
                          _where(b), verb, b["id"], b["scope"]))
        elif a["version"] != b["version"]:
            out.append("%s at %s moved from version %s to %s - no single command "
                       "puts a version back; reinstall the one you want"
                       % (b["id"], _where(b), a["version"], b["version"]))
    return out


def global_config_file(env):
    """The config file Claude Code keeps folder trust in: `.claude.json` in
    CLAUDE_CONFIG_DIR when set, else in the home directory (read off the 2.1.292
    binary's config-path function; the trust entry is keyed by the resolved path)."""
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(env.get("CLAUDE_CONFIG_DIR") or home, ".claude.json")


def trust_entries(config_text, roots):
    """(keys, why) - the `projects` entries in a global config naming a fixture root.
    An absent file is no entries; one that will not parse is a reason, never []."""
    if config_text is None:
        return [], None
    try:
        body = json.loads(config_text)
    except ValueError as exc:
        return [], "the config does not parse: %s" % (exc,)
    projects = body.get("projects") if isinstance(body, dict) else None
    if not isinstance(projects, dict):
        return [], None
    return sorted(k for k in projects if k in roots), None


def transcript_names(roots):
    """The transcript directory name of each fixture root: the path with every
    character outside letters and digits replaced by a dash - the shape every
    directory under the CLI's projects directory has."""
    return sorted(set(re.sub(r"[^A-Za-z0-9]", "-", r) for r in roots))


def _projects_dir(env, run):
    """(path, why) - the transcript root, as `claude auth status --json` reports it."""
    try:
        out = run(["claude", "auth", "status", "--json"],
                  capture_output=True, text=True, env=env)
    except OSError as exc:
        return None, "`claude auth status` could not run: %s" % (exc,)
    try:
        body = json.loads(out.stdout or "")
    except ValueError:
        body = None
    where = body.get("projectsDirectory") if isinstance(body, dict) else None
    if not isinstance(where, str) or not where:
        return None, ("`claude auth status --json` named no projectsDirectory "
                      "(exit %d)" % out.returncode)
    return where, None


def config_footprint(env, roots, run=subprocess.run):
    """What the config `env` names holds that a take could have put there: its
    installed plugins, its trust entries for the demo folder, and the demo folder's
    transcript directories. Every part that could not be read carries its reason."""
    plugins, plugins_why = installed_plugins(env, run)
    trust_file = global_config_file(env)
    trust, trust_why = trust_entries(_read_text(trust_file), roots)
    projects, projects_why = _projects_dir(env, run)
    transcripts = []
    if projects:
        transcripts = [os.path.join(projects, n) for n in transcript_names(roots)
                       if os.path.isdir(os.path.join(projects, n))]
    return {"plugins": plugins, "pluginsWhy": plugins_why,
            "trustFile": trust_file, "trust": trust, "trustWhy": trust_why,
            "transcripts": transcripts, "transcriptsWhy": projects_why}


def take_preconditions(account_why, plugins_why):
    """[refusal, ...] that stop a take before it starts; [] when it may run."""
    out = []
    if account_why:
        out.append("%s - the scan needs the account's own email and organisation "
                   "to look for, so the take is refused" % (account_why,))
    if plugins_why:
        out.append("%s - without the installed plugins before the take, nothing "
                   "could say afterwards whether it changed them" % (plugins_why,))
    return out


def footprint_refusals(plan, before, after):
    """[refusal, ...] about what a take did to the operator's config.

    A changed plugin list refuses the take in either mode - against the operator's
    config it is a stray dialog answer, against an isolated one a leak. A trust entry
    or transcript directory that appeared refuses an ISOLATED take only: against the
    operator's own config they are expected, and `leftover_lines()` names them."""
    out = []
    if after.get("plugins") is None:
        out.append("the installed plugins could not be read after the take (%s), so "
                   "whether it changed them is unknown" % (after.get("pluginsWhy"),))
    elif before.get("plugins") is not None:
        lead = ("the take ran against an isolated config, yet the operator's "
                "plugins changed: " if plan["isolated"] else
                "the take changed the operator's installed plugins: ")
        out.extend(lead + c for c in plugin_changes(before["plugins"], after["plugins"]))
    if not plan["isolated"]:
        return out
    for why in (after.get("trustWhy"), after.get("transcriptsWhy")):
        if why:
            out.append("the operator's config could not be read after the take "
                       "(%s), so whether the isolation held is unknown" % (why,))
    for key in sorted(set(after.get("trust") or []) - set(before.get("trust") or [])):
        out.append("the take ran against an isolated config, yet %s gained a trust "
                   "entry for %s" % (after["trustFile"], key))
    for path in sorted(set(after.get("transcripts") or [])
                       - set(before.get("transcripts") or [])):
        out.append("the take ran against an isolated config, yet a transcript "
                   "directory appeared in the operator's: %s" % (path,))
    return out


def leftover_lines(plan, before, after):
    """[line, ...] - what the take left in a config that outlives it, each with the
    step that removes it. An isolated take leaves nothing of its own behind."""
    if plan["isolated"]:
        return ["the take's own config at %s was removed with the kit; the operator's "
                "plugins, trust entries and transcripts were compared before and "
                "after" % (plan["configDir"],)]
    out = []
    if after.get("trustWhy"):
        out.append("%s could not be read (%s), so the trust entry for the demo folder "
                   "is unknown - look under \"projects\" there"
                   % (after["trustFile"], after["trustWhy"]))
    for key in after.get("trust") or []:
        was = " (it was there before this take)" if key in (before.get("trust") or []) \
            else ""
        out.append("trust entry %r in %s%s - to remove it, with no Claude Code "
                   "session open, delete that key under \"projects\" in the file"
                   % (key, after["trustFile"], was))
    if after.get("transcriptsWhy"):
        out.append("the transcript directory could not be located (%s)"
                   % (after["transcriptsWhy"],))
    for path in after.get("transcripts") or []:
        out.append("transcripts in %s - to remove them: rm -rf '%s'" % (path, path))
    if not out:
        out.append("no trust entry and no transcript directory for the demo folder "
                   "were found in %s" % (after.get("trustFile"),))
    return out


# --- the session's isolated settings -----------------------------------------
_SCRIPT_CALL_RE = re.compile(r'python3 "\$\{CLAUDE_PLUGIN_ROOT\}/(scripts/[A-Za-z0-9_./-]+)"')


def command_script_calls(commands_dir):
    """Sorted plugin-relative script paths the plugin's own commands tell Claude to run.

    Read off the command files rather than listed here, so a command that starts
    calling another script is covered by the next recording without anybody editing
    an allow list."""
    found = set()
    for name in sorted(os.listdir(commands_dir)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(commands_dir, name), encoding="utf-8") as fh:
            found.update(_SCRIPT_CALL_RE.findall(fh.read()))
    return sorted(found)


def demo_settings(plugin_root, script_calls, tap_path):
    """The one settings file the session loads.

    The allow list is the plugin's own script calls, rooted at the copy the session
    loads, plus edits under the demo's `src/`: the edit the plan covers must go
    through without a permission prompt, and the gate's deny is decided before any
    allow rule is read, so allowing the edit cannot let the refused one through.
    `Edit(...)` covers every file-editing tool; the CLI warns on a `Write(...)` rule
    and matches nothing with it. No mode is set - here, on the command line, or in
    the isolated config - so the footer shows Claude Code's own starting mode and
    not one this demo chose. For the recorded CLI that is auto mode, documented at
    https://code.claude.com/docs/en/permission-modes: "With Claude Code v2.1.283 or
    later, auto mode is the built-in starting permission mode for interactive
    terminal and VS Code sessions." The one hook is
    the tap: it appends each edit's PreToolUse payload to `tap_path` and prints
    nothing, which is how --check later replays exactly what Claude sent.

    Two documented switches keep Claude Code's own text out of the frames, so a take
    shows only what the user typed and what Claude answered, and two takes differ
    only by the model: `promptSuggestionEnabled` off, because a suggestion can land
    in the input box while the tape is typing; `spinnerTipsEnabled` off, because a
    tip is random text. Both are settings keys in Claude Code's settings reference
    (https://code.claude.com/docs/en/settings-reference.md)."""
    allow = ['Bash(python3 "%s/%s":*)' % (plugin_root, rel) for rel in script_calls]
    allow += ["Edit(./src/**)"]
    return {
        "promptSuggestionEnabled": False,
        "spinnerTipsEnabled": False,
        "permissions": {"allow": allow},
        "hooks": {"PreToolUse": [{
            "matcher": "|".join(EDIT_TOOLS),
            "hooks": [{"type": "command",
                       "command": "cat >> '%s'; echo >> '%s'" % (tap_path, tap_path)}]}]},
    }


TAPE_NEEDS = (
    ("Output %s" % VHS_GIF, "the GIF output this tool ships"),
    ("Output %s" % VHS_TEXT, "the text output the checks read"),
    ("cd %s" % FIXTURE_DIR, "the neutral fixture path"),
    ("--plugin-dir %s" % KIT_PLUGIN, "this checkout's plugin copy"),
    ("--settings %s" % KIT_SETTINGS, "the isolated settings"),
    ("--model %s" % MODEL, "the recorded model"),
    ("--strict-mcp-config", "no MCP server of the host's in the session"),
    ("--setting-sources project,local", "none of the user's own settings"),
    ("/audit:status", "the status command the demo opens on"),
    (IN_PLAN_REL, "the edit the plan covers"),
    (OUT_OF_PLAN_REL, "the edit no task covers"),
    ("Hide", "hiding the launch line and the banner"),
    ("Usage limit reached", "ending a take that hit the account's limit in seconds"),
    ("esc to interrupt", "proving each prompt was submitted"),
    ("env -u IS_DEMO claude", "a first launch that can be asked to trust the folder"),
    ("Quick safety check", "waiting for the folder-trust question"),
    ("Interrupted", "the end state the last Wait proves before the hold"),
    ("Show", "showing the session once the banner is cleared"),
)


def tape_problems(tape_text):
    """[problem, ...] - why the committed tape would not record what this tool reads.

    The two files share fixed paths and output names; each disagreement is a
    recording that runs, costs a session, and is then refused."""
    out = []
    for need, why in TAPE_NEEDS:
        if need not in tape_text:
            out.append("the tape does not carry %r (%s)" % (need, why))
    for banned in ("--dangerously-skip-permissions", "bypassPermissions",
                   "--permission-mode"):
        if banned in tape_text:
            out.append("the tape carries %r: the demo may not choose a permission "
                       "mode; the footer shows the CLI's own default" % (banned,))
    for prompt in tape_prompts(tape_text):
        if re.search(r"\d", prompt):
            out.append("the prompt %r carries a digit: typed while a numbered dialog "
                       "has the keys, a digit answers it" % (prompt[:40],))
    return out


def tape_prompts(tape_text):
    """[text, ...] - what the tape types into the recorded session, in order: every
    Type after the camera first comes on. The launch is typed before that, into
    the shell; a prompt typed off camera later is still the user's prompt."""
    out, started = [], False
    for on, line in tape_steps(tape_text):
        started = started or on
        if started and line.startswith('Type "') and line.endswith('"'):
            out.append(line[len('Type "'):-1].replace('\\"', '"'))
    return out


_TAPE_SKIP = ("#", "Output ", "Set ", "Require ")


def collapsed_steps(steps):
    """`steps` with each run of one repeated action folded into one row and a count,
    so the dry run's listing stays readable: [(on camera, line, times)]."""
    out = []
    for on, line in steps:
        if out and out[-1][0] == on and out[-1][1] == line:
            out[-1] = (on, line, out[-1][2] + 1)
        else:
            out.append((on, line, 1))
    return out


def tape_steps(tape_text):
    """[(on camera, line)] - the tape's actions in order, each marked by whether the
    recording shows it: lines between Hide and Show run off camera."""
    steps, shown = [], True
    for raw in tape_text.split("\n"):
        line = raw.strip()
        if not line or line.startswith(_TAPE_SKIP):
            continue
        if line == "Hide":
            shown = False
        elif line == "Show":
            shown = True
        steps.append((shown and line != "Show", line))
    return steps


# --- the record that ties the committed GIF to the refusal it shows ------------
def gif_record_entry(gif_bytes, refusal, shown, payload, cli_version, vhs_version):
    """What a recording writes about the file it just wrote."""
    return {"sha256": hashlib.sha256(gif_bytes).hexdigest(),
            "refusal": refusal,
            "refusalShown": shown,
            "payload": payload,
            "cliVersion": cli_version,
            "model": MODEL,
            "recordedWith": vhs_version,
            "tape": "tools/demo-gate.tape",
            "writtenBy": "tools/capture-demo-gif.py"}


def record_entry(body, name):
    """This GIF's entry in a parsed sidecar, or None."""
    if not isinstance(body, dict):
        return None
    table = body.get(GIF_KEY)
    entry = table.get(name) if isinstance(table, dict) else None
    return entry if isinstance(entry, dict) else None


def first_difference(recorded, now):
    """(line number, recorded line, current line) of the first line that differs."""
    a = (recorded or "").split("\n")
    b = (now or "").split("\n")
    for i in range(max(len(a), len(b))):
        la = a[i] if i < len(a) else "<no line>"
        lb = b[i] if i < len(b) else "<no line>"
        if la != lb:
            return i + 1, la, lb
    return 0, "", ""


def gif_record_problems(body, name, gif_bytes, refusal):
    """[problem, ...] - why the committed GIF does not match its record; [] when it does.

    `body` None means the sidecar was absent or would not parse, `gif_bytes` None that
    the GIF is not on disk, and `refusal` None that the gate printed no refusal for
    the recorded payload. Every missing basis is a finding naming the GIF: a record
    nobody wrote cannot settle the claim the picture makes."""
    if not isinstance(body, dict):
        return ["%s: %s is missing or unreadable, so nothing records which refusal "
                "the GIF shows - re-record it" % (name, SIDECAR)]
    entry = record_entry(body, name)
    if entry is None:
        return ["%s: %s holds no record for it under %r, so whether it still shows "
                "the gate's refusal is unknown rather than settled - re-record it"
                % (name, SIDECAR, GIF_KEY)]
    if gif_bytes is None:
        return ["%s: recorded, but the file is not on disk" % (name,)]
    out = []
    if entry.get("sha256") != hashlib.sha256(gif_bytes).hexdigest():
        out.append("%s: the committed bytes are not the ones recorded (sha256 "
                   "differs) - re-record it rather than editing the record" % (name,))
    recorded = entry.get("refusal")
    if not isinstance(recorded, str) or not recorded:
        out.append("%s: the record names no refusal, so what the GIF shows the gate "
                   "saying is unknown rather than settled - re-record it" % (name,))
    elif refusal is None:
        out.append("%s: the gate printed no refusal for the recorded payload, so the "
                   "GIF shows a refusal the plugin no longer makes" % (name,))
    elif refusal != recorded:
        line, was, now = first_difference(recorded, refusal)
        out.append("%s: the gate's refusal is no longer the one the recording "
                   "captured - line %d was %r and is now %r; re-record it"
                   % (name, line, was, now))
    return out


def merged_sidecar(body, name, entry):
    """A new sidecar body with this GIF's entry set; every other key as it was read.

    The screenshots' half belongs to `capture-screenshots.mjs`, which carries this
    key through its own merge the same way."""
    out = dict(body)
    table = dict(out.get(GIF_KEY) or {})
    table[name] = entry
    out[GIF_KEY] = dict((k, table[k]) for k in sorted(table))
    return out


def sidecar_text(body):
    """The bytes `JSON.stringify(body, null, 2)` plus a newline would write, so the
    two writers of one file never reformat each other's half."""
    return json.dumps(body, indent=2, ensure_ascii=False) + "\n"


def _read_bytes(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _read_text(path):
    raw = _read_bytes(path)
    return None if raw is None else raw.decode("utf-8", "replace")


def _read_sidecar(path):
    """(body, error) - body None with error None means the file is absent."""
    raw = _read_bytes(path)
    if raw is None:
        return None, None
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        return None, "%s does not parse: %s" % (path, exc)
    if not isinstance(body, dict):
        return None, "%s is not a JSON object" % (path,)
    return body, None


def _sidecar_path(out_path):
    return os.path.join(os.path.dirname(out_path), SIDECAR)


def recorded_gif_problems(out_path, refusal):
    """--check's comparison, against the files beside `out_path`."""
    body, _err = _read_sidecar(_sidecar_path(out_path))
    return gif_record_problems(body, os.path.basename(out_path),
                               _read_bytes(out_path), refusal)


def record_gif(out_path, entry):
    """Write this GIF's record into the sidecar beside it; None, or why it refused.

    An absent sidecar is created holding only this record. One that will not parse
    is REFUSED and left as it is: replacing it would drop every screenshot record it
    held, and those are not this tool's to rebuild."""
    side = _sidecar_path(out_path)
    body, err = _read_sidecar(side)
    if err:
        return err
    new = merged_sidecar(body or {}, os.path.basename(out_path), entry)
    with open(side, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(sidecar_text(new))
    return None


# --- --check -----------------------------------------------------------------
def _status_text(d):
    """The status render, run INSIDE the fixture: run from wherever the caller stood,
    it reported that checkout's own phase locks - process ids and the host's name."""
    return subprocess.run([PY, resolve_script("audit-status.py"),
                           os.path.join(d, MANIFEST_REL)],
                          capture_output=True, text=True, cwd=d,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=d)).stdout


def refusal_shape_problems(refusal):
    """What a refusal worth showing must still say."""
    if not refusal:
        return ["the out-of-plan edit was ALLOWED; there is no refusal to show"]
    out = []
    if OUT_OF_PLAN_REL not in refusal:
        out.append("the refusal does not name the file it refused")
    if "#no-plan" not in refusal:
        out.append("the refusal does not name a way out")
    return out


def run_check(out_path):
    name = os.path.basename(out_path)
    body, err = _read_sidecar(_sidecar_path(out_path))
    entry = record_entry(body, name)
    payload = entry.get("payload") if entry else None
    d = tempfile.mkdtemp(prefix="audit-demo-gif-")
    try:
        build_fixture(d)
        problems = [err] if err else []
        with open(os.path.join(d, MANIFEST_REL), encoding="utf-8") as fh:
            invalid, _warnings = plan_findings(json.load(fh))
        problems.extend("the demo plan is one a writer would refuse: %s" % f
                        for f in invalid)
        status = _status_text(d)
        if "P2.1" not in status or "READY NOW" not in status:
            problems.append("the status render is not the one the demo shows")
        if fire_in_plan(d) is not None:
            problems.append("the in-plan edit was DENIED; the demo shows it going through")
        refusal = None
        if entry is not None and (not isinstance(payload, dict)
                                  or not isinstance(payload.get("tool_input"), dict)):
            problems.append("%s: the record holds no out-of-plan payload to replay - "
                            "re-record it" % (name,))
        elif entry is not None:
            raw = replay(payload, d)
            problems.extend(refusal_shape_problems(raw))
            refusal = scrub_value(raw, fixture_roots(d)) if raw else None
        problems.extend(gif_record_problems(body, name, _read_bytes(out_path), refusal))
    finally:
        # THE ANSWER HERE IS THE PLAIN CALL. `build_fixture()` initialises a
        # repository and never writes an object into one: no `add`, no `commit`, and
        # the hooks this drives only read. A repository nothing was staged into holds
        # no read-only loose object, so there is nothing for windows to refuse to
        # unlink. THE PREMISE IS ENFORCED: `_suite.unsafe_removal_violations()` asks
        # for a staging or committing verb as well as an initialising one, so the day
        # `build_fixture()` learns to stage or commit, this file becomes a finding.
        shutil.rmtree(d, ignore_errors=True)
    for p in problems:
        sys.stderr.write("FAIL: %s\n" % p)
    if problems:
        return 1
    print("  gate allowed the in-plan edit (silently)")
    print("  gate refused the recorded out-of-plan edit with the refusal %s shows" % name)
    print("  %s is the recorded bytes" % name)
    print("\nOK: demo preconditions hold")
    return 0


# --- --record ------------------------------------------------------------------
def _tool_version(argv):
    try:
        out = subprocess.run(argv, capture_output=True, text=True)
    except OSError:
        return None
    text = (out.stdout or out.stderr or "").strip()
    return text.split("\n")[0] if out.returncode == 0 and text else None


def build_kit(kit_dir, plugin_src):
    """The plugin copy the session loads and the settings it loads, at `kit_dir`."""
    plugin = os.path.join(kit_dir, "audit")
    shutil.copytree(plugin_src, plugin,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
    calls = command_script_calls(os.path.join(plugin, "commands"))
    tap = os.path.join(kit_dir, TAP_NAME)
    with open(tap, "w", encoding="utf-8"):
        pass
    with open(os.path.join(kit_dir, "settings.json"), "w", encoding="utf-8") as fh:
        json.dump(demo_settings(plugin, calls, tap), fh, indent=2)
    return calls


USAGE_LIMIT_RE = re.compile(r"hit your session limit|Usage limit reached")


def usage_limit_problem(screen):
    """Why the take is void when the account ran out of usage, or None.

    Named on its own because every other finding of such a take - no edit, no
    refusal - is a consequence of it, and a re-record needs to wait for the reset
    rather than a fix."""
    if screen and USAGE_LIMIT_RE.search(screen):
        return ("the account hit its usage limit during the take - Claude Code "
                "showed its usage-limit screen; re-record after the limit resets")
    return None


_LAST_VALUE = "last value was:"
_LOG_SCREEN_END = "\nrecording failed"


def log_screens(log_text):
    """[screen, ...] - the terminal screens VHS printed into its log, and nothing else.

    The log also echoes every tape command, and the tape's own Wait patterns name the
    texts this tool looks for, so reading the whole log reads the question as its
    answer. A screen is only what follows a failed Wait's "last value was:" marker."""
    out, i = [], 0
    text = log_text or ""
    while True:
        i = text.find(_LAST_VALUE, i)
        if i < 0:
            return out
        start = i + len(_LAST_VALUE)
        end = text.find(_LOG_SCREEN_END, start)
        out.append(text[start:] if end < 0 else text[start:end])
        i = start


VHS_FRAME_BAR = u"\u2500" * 80
_HEADER_MARK = "Claude Code v"
_FOOTER_MARK = "shift+tab to cycle"


def vhs_frames(text_output):
    """VHS's text output split at its own frame separator - a bar of exactly the
    separator's width, which Claude Code's wider box borders never equal."""
    frames, cur = [], []
    for line in (text_output or "").split("\n"):
        if line.strip() == VHS_FRAME_BAR:
            frames.append("\n".join(cur))
            cur = []
        else:
            cur.append(line)
    frames.append("\n".join(cur))
    return [f for f in frames if f.strip()]


def outgrew_problem(screens):
    """Why the take cannot be read, when the session outgrew the terminal; or None.

    VHS reads a screen - for its Wait and for its text output alike - as the first
    rows of the terminal's buffer, as many as the window is tall, so once the session
    scrolls, the bottom of it is never read: not the step a Wait waits for, and not
    the refusal this tool must find. Claude Code draws its footer at the very bottom,
    and VHS pads a screen to the window's height, so a screen showing the header, no
    footer, and something on its last row is one whose bottom was cut. (An open
    command popup also hides the footer, but leaves the rows under it blank.)"""
    for scr in screens:
        bottom_filled = scr.split("\n")[-1].strip() != ""
        if _HEADER_MARK in scr and _FOOTER_MARK not in scr and bottom_filled:
            return ("the session outgrew the terminal: a screen shows Claude Code's "
                    "header but not its footer, so VHS read only its top rows and "
                    "could see neither the step a Wait was waiting for nor the "
                    "refusal - the whole take has to fit on one screen")
    return None


NARRATION_RE = re.compile(r"<manifestPath>|wasn't filled in|didn't fill in|"
                          r"was not filled in|did not fill in")


def narration_problem(screen):
    """Why the take may not ship when Claude narrates an unfilled command placeholder,
    or None. A user never sees that sentence when the command resolves its own
    arguments; a demo that shows it shows a defect. The fix is in the command."""
    if screen and NARRATION_RE.search(screen):
        return ("the session narrates an unfilled command placeholder "
                "(<manifestPath> / 'wasn't filled in'); a user should never see it - "
                "fix the command, then re-record")
    return None


def submitted_prompts(screen):
    """[text, ...] - the prompts the transcript shows as sent.

    Claude Code echoes a sent prompt at the left edge as the prompt mark and an
    ordinary space; the live input box uses a no-break space there, and a dialog's
    selected option and the command popup are indented - none of those is a send."""
    return [line[2:].rstrip() for line in (screen or "").split("\n")
            if line.startswith(u"\u276f ") and line[2:].strip()]


def stray_prompt_problem(screen, prompts):
    """Why the take shows a prompt the tape never typed, or None.

    A sent prompt that is not the start of one of the tape's own is a prompt
    something else wrote - a dialog that took half the keys, a suggestion accepted
    by an Enter - and the session that follows answers a question nobody asked."""
    expected = [p for p in (prompts or ()) if p]
    for shown in submitted_prompts(screen):
        if not any(p.startswith(shown) for p in expected):
            return ("the session shows a prompt the tape never typed (%r) - the keys "
                    "went somewhere else first; re-record" % (shown[:60],))
    return None


def screen_problems(text_output, log_text, prompts=()):
    """[problem, ...] read off what the terminal showed - the text output's frames
    and the screens in the log - never off the tape commands the log echoes. A
    usage limit comes first: every other finding of such a take follows from it.
    `prompts` are the tape's own (`tape_prompts()`); without them no sent prompt
    can be judged, and none is."""
    screens = vhs_frames(text_output) + log_screens(log_text)
    joined = "\n".join(screens)
    found = [usage_limit_problem(joined), outgrew_problem(screens),
             narration_problem(joined),
             stray_prompt_problem(joined, prompts) if prompts else None]
    return [p for p in found if p]


_EDIT_ON_SCREEN_RE = re.compile(r"(?:Update|Write)\((?:[^)]*/)?src/")


def hooks_problem(screen, payloads):
    """Why the take's edits went past every hook, or None.

    The tap is a PreToolUse hook like the plan gate. An edit Claude Code drew on
    screen that the tap never saw means no hook ran in that session - for a folder
    Claude Code has not been told to trust, it loads no plugin or settings hook - so
    there was no gate to refuse anything."""
    if not payloads and screen and _EDIT_ON_SCREEN_RE.search(screen):
        return ("the screen shows an edit but the tap recorded none, so no hook ran "
                "in the session - the plan gate included; the demo folder was most "
                "likely never trusted")
    return None


def verify_recording(screen, payloads_text, d, markers):
    """(problems, refusal, shown, payload) for one finished recording at fixture `d`."""
    problems = []
    payloads, bad = parse_payloads(payloads_text or "")
    if bad:
        problems.append("the tap holds a payload that does not parse")
    hooks = hooks_problem(screen, payloads)
    if hooks:
        return problems + [hooks], None, "", None
    payload = out_of_plan_payload(payloads)
    if payload is None:
        return (problems + ["Claude never tried to edit %s, so there is no refusal "
                            "in this recording" % OUT_OF_PLAN_REL], None, "", None)
    roots = fixture_roots(d)
    stored = scrub_value(payload, roots)
    raw = replay(stored, d)
    problems.extend(refusal_shape_problems(raw))
    if not raw:
        return problems, None, "", None
    shown = shown_refusal(screen, raw)
    if not first_line_shown(raw, shown):
        problems.append("the screen never shows the gate's refusal as far as its "
                        "first line, so the GIF does not show the refusal it records")
    refusal = scrub_value(raw, roots)
    for where, text in (("a recorded frame", screen),
                        ("the refusal", refusal),
                        ("the recorded payload", json.dumps(stored))):
        for kind in pii_findings(text, markers):
            problems.append("%s carries %s" % (where, kind))
    return problems, refusal, scrub_value(shown, roots), stored


def _keep_evidence(kit_dir):
    keep = tempfile.mkdtemp(prefix="audit-demo-failed-")
    for n in (VHS_GIF, VHS_TEXT, TAP_NAME, "vhs.log"):
        src = os.path.join(kit_dir, n)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(keep, n))
    return keep


def run_record(out_path, dry_run):
    for need in ("vhs",) if dry_run else ("vhs", "claude"):
        if shutil.which(need) is None:
            sys.stderr.write("COULD NOT RUN: %s is not on PATH\n" % need)
            return 2
    for path in (FIXTURE_DIR, KIT_DIR):
        if os.path.exists(path):
            sys.stderr.write("COULD NOT RUN: %s already exists - remove it; this tool "
                             "never writes into a directory it did not create\n" % path)
            return 2
    with open(TAPE, encoding="utf-8") as fh:
        tape_issues = tape_problems(fh.read())
    for p in tape_issues:
        sys.stderr.write("FAIL: %s\n" % p)
    if tape_issues:
        return 1
    kept = None
    try:
        os.makedirs(FIXTURE_DIR)
        os.makedirs(KIT_DIR)
        build_fixture(FIXTURE_DIR)
        calls = build_kit(KIT_DIR, PLUGIN_SRC)
        print("  fixture %s, plugin copy %s, %d script call(s) allowed"
              % (FIXTURE_DIR, KIT_PLUGIN, len(calls)))
        if dry_run:
            with open(TAPE, encoding="utf-8") as fh:
                order = tape_steps(fh.read())
            print("  the tape, in order (- off camera, + on camera):")
            for on, line, times in collapsed_steps(order):
                print("    %s %s%s" % ("+" if on else "-", line,
                                       "   (x%d)" % times if times > 1 else ""))
            check = subprocess.run(["vhs", "validate", TAPE], capture_output=True,
                                   text=True)
            sys.stdout.write(check.stdout + check.stderr)
            print("  would run: (cd %s && vhs %s)" % (KIT_DIR, TAPE))
            if check.returncode != 0:
                sys.stderr.write("FAIL: vhs validate exited %d\n" % check.returncode)
                return 1
            print("\nOK: dry run - no session started, nothing written")
            return 0
        cli = _tool_version(["claude", "--version"])
        plan = config_plan(os.environ)
        print("  config: %s" % plan["why"])
        if plan["isolated"]:
            seed_isolated_config(plan["configDir"])
        take_env = session_env(os.environ, plan["configDir"])
        # The operator's config as the operator's own shell names it, read on both
        # sides of the take whichever config the take was handed.
        operator_env = session_env(os.environ)
        roots = fixture_roots(FIXTURE_DIR)
        before = config_footprint(operator_env, roots)
        account, why = account_markers(take_env)
        blocked = take_preconditions(why, before["pluginsWhy"])
        for p in blocked:
            sys.stderr.write("COULD NOT RUN: %s\n" % p)
        if blocked:
            return 2
        vhs = _tool_version(["vhs", "--version"])
        with open(os.path.join(KIT_DIR, "vhs.log"), "w", encoding="utf-8") as log:
            ran = subprocess.run(["vhs", TAPE], cwd=KIT_DIR, stdout=log,
                                 stderr=subprocess.STDOUT, env=take_env)
        after = config_footprint(operator_env, roots)
        print("  what the take left in a Claude Code config:")
        for line in leftover_lines(plan, before, after):
            print("    %s" % line)
        problems = footprint_refusals(plan, before, after)
        if ran.returncode != 0:
            problems.append("vhs exited %d (its log is kept)" % ran.returncode)
        screen = _read_text(os.path.join(KIT_DIR, VHS_TEXT))
        gif = _read_bytes(os.path.join(KIT_DIR, VHS_GIF))
        if screen is None or gif is None:
            problems.append("vhs wrote no %s" % (VHS_TEXT if screen is None else VHS_GIF))
        refusal = shown = payload = None
        # VHS writes a text frame per command, so a screen that appears while a Wait
        # is polling can be missing from the text output; the log's failed-Wait
        # screen is where a take showed it. These findings are read first and, when
        # there are any, stand in for the replay: they say why the take is void.
        with open(TAPE, encoding="utf-8") as fh:
            typed = tape_prompts(fh.read())
        void = screen_problems(screen, _read_text(os.path.join(KIT_DIR, "vhs.log")),
                               typed)
        if void:
            problems = void + problems
        elif not problems:
            more, refusal, shown, payload = verify_recording(
                screen, _read_text(os.path.join(KIT_DIR, TAP_NAME)), FIXTURE_DIR,
                personal_markers() + account)
            problems.extend(more)
        if cli is None:
            problems.append("`claude --version` gave no answer to record")
        if problems:
            kept = _keep_evidence(KIT_DIR)
            for p in problems:
                sys.stderr.write("FAIL: %s\n" % p)
            sys.stderr.write("nothing was written; the recording is kept in %s\n" % kept)
            return 1
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(gif)
        err = record_gif(out_path, gif_record_entry(gif, refusal, shown, payload,
                                                    cli, vhs))
        if err:
            sys.stderr.write("FAIL: the GIF was written but its record was not: %s\n"
                             % err)
            return 1
        print("  wrote %s (%d KB) from %s, model %s"
              % (os.path.relpath(out_path, REPO), len(gif) // 1024, cli, MODEL))
        print("  recorded its sha256 and the refusal it shows in %s under %r"
              % (SIDECAR, GIF_KEY))
        print("\nOK: demo GIF recorded")
        return 0
    finally:
        # Same premise as `run_check`'s removal: the fixture is initialised and never
        # staged into, and the kit is plain files.
        shutil.rmtree(FIXTURE_DIR, ignore_errors=True)
        shutil.rmtree(KIT_DIR, ignore_errors=True)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "screenshots", GIF_NAME))
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="replay the recorded refusal and compare; no session, no write")
    mode.add_argument("--record", action="store_true",
                      help="record a real session with vhs and claude (paid)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --record: build and validate everything, start no session")
    args = ap.parse_args(argv)
    if args.dry_run and not args.record:
        ap.error("--dry-run goes with --record")
    if args.check:
        return run_check(args.out)
    return run_record(args.out, args.dry_run)


# --- selftest -----------------------------------------------------------------
# `--check` asserts the half that needs the hooks - it replays the recorded payload
# against the real gate. These cases hold the pure logic around it: the comparison,
# the screen reading, the personal-data scan and the files the session is given.
def _cases(check):
    real = resolve_script("audit-status.py")
    check("r0 a basename resolves to the file WHEREVER it sits under the scripts "
          "tree - a join against the scripts root would look one directory too "
          "high for anything under a domain folder: %s"
          % (os.path.relpath(real, REPO),),
          os.path.isfile(real)
          and os.path.join("scripts", "status") in real)

    try:
        resolve_script("no-such-script-in-this-tree.py")
        found = "returned a path"
    except ImportError as exc:
        found = "ImportError" if "no script named" in str(exc) else str(exc)[:40]
    except Exception as exc:
        found = type(exc).__name__
    check("r1 a basename that names nothing FAILS LOUD rather than resolving to "
          "something plausible - the three refusals are inherited from "
          "`_loader.script_path`, not restated here (got %s)" % (found,),
          found == "ImportError")

    try:
        resolve_script(os.path.join("status", "audit-status.py"))
        sep = "accepted a path"
    except ValueError as exc:
        sep = "ValueError" if "directory sep" in str(exc) else str(exc)[:40]
    except Exception as exc:
        sep = type(exc).__name__
    check("r2 ...and a value carrying a directory separator is refused too, "
          "because the folders under the scripts tree are labels and not "
          "namespaces (got %s)" % (sep,),
          sep == "ValueError")

    _refusal_record_cases(check)
    _sidecar_cases(check)
    _screen_cases(check)
    _payload_cases(check)
    _pii_cases(check)
    _session_file_cases(check)
    _env_cases(check)
    _fixture_cases(check)
    _screen_reading_cases(check)
    _prompt_cases(check)
    _limit_cases(check)
    _tape_step_cases(check)
    _config_isolation_cases(check)
    _plugin_change_cases(check)
    _account_query_cases(check)


def _refusal_record_cases(check):
    """--check against a record of the REFUSAL a recording captured.

    The record is written as literal dicts here rather than by the writer, so a
    writer that wrote the wrong field cannot also be the thing these cases trust."""
    gif = b"GIF89a-recorded-session"
    sha = hashlib.sha256(gif).hexdigest()
    refusal = ("[require-plan] Outside the running plan (change magnitude 120 "
               "(> 80)): src/billing.ts\n"
               "  2. This is genuinely a one-off -> the HUMAN types #no-plan")
    body = {"images": {"a.png": {"sha256": "aa"}},
            GIF_KEY: {GIF_NAME: {"sha256": sha, "refusal": refusal}}}

    agree = gif_record_problems(body, GIF_NAME, gif, refusal)
    check("rr0 THE ALLOW TWIN: the gate prints the refusal the recording captured "
          "and the GIF is the recorded bytes - no finding, so the cases below are "
          "not passing on a check that always fails: %r" % (agree,),
          agree == [])

    moved = refusal.replace("the HUMAN types", "type")
    drift = gif_record_problems(body, GIF_NAME, gif, moved)
    check("rr1 the gate's refusal no longer matches the text the recording "
          "captured: ONE finding, naming the GIF, saying it is the refusal, and "
          "quoting the first line that differs so the repair is readable from CI's "
          "log alone: %r" % (drift,),
          len(drift) == 1 and GIF_NAME in drift[0] and "refusal" in drift[0]
          and "the HUMAN types" in drift[0] and "-> type #no-plan" in drift[0])

    bytes_moved = gif_record_problems(body, GIF_NAME, gif + b"!", refusal)
    check("rr2 the committed GIF is not the bytes recorded: ONE finding naming the "
          "GIF and its sha256, and the agreeing refusal adds none: %r"
          % (bytes_moved,),
          len(bytes_moved) == 1 and GIF_NAME in bytes_moved[0]
          and "sha256" in bytes_moved[0])

    no_refusal = {GIF_KEY: {GIF_NAME: {"sha256": sha}}}
    got = gif_record_problems(no_refusal, GIF_NAME, gif, refusal)
    check("rr3 a record that names no refusal is a finding about the REFUSAL, "
          "never a pass - an absent basis settles nothing: %r" % (got,),
          len(got) == 1 and GIF_NAME in got[0] and "refusal" in got[0])

    for label, side in (("no gif table", {"images": {}}),
                        ("no entry for the GIF", {GIF_KEY: {}}),
                        ("no sidecar at all", None)):
        got = gif_record_problems(side, GIF_NAME, gif, refusal)
        check("rr4 a sidecar with %s is a finding naming the GIF: %r" % (label, got),
              len(got) == 1 and GIF_NAME in got[0])

    d = tempfile.mkdtemp(prefix="audit-demo-gif-selftest-")
    try:
        out = os.path.join(d, GIF_NAME)
        with open(out, "wb") as fh:
            fh.write(gif)
        with open(os.path.join(d, SIDECAR), "w", encoding="utf-8") as fh:
            fh.write(sidecar_text(body))
        on_disk = recorded_gif_problems(out, refusal)
        on_disk_moved = recorded_gif_problems(out, moved)
        check("rr5 the same comparison read off the files --check reads: green when "
              "they agree (%r), red naming the refusal when the gate moved (%r)"
              % (on_disk, on_disk_moved),
              on_disk == [] and len(on_disk_moved) == 1
              and "refusal" in on_disk_moved[0])
    finally:
        # Plain files only, no repository, so nothing read-only for the windows
        # runner to refuse.
        shutil.rmtree(d, ignore_errors=True)

    gone = gif_record_problems(body, GIF_NAME, gif, None)
    check("rr6 the gate printing NO refusal for the recorded payload is a finding "
          "of its own, not a comparison that happened to differ: %r" % (gone,),
          len(gone) == 1 and "no refusal for the recorded payload" in gone[0])
    missing = gif_record_problems(body, GIF_NAME, None, refusal)
    check("rr7 a GIF that is not on disk is a finding rather than a skipped "
          "comparison: %r" % (missing,),
          len(missing) == 1 and GIF_NAME in missing[0])


def _sidecar_cases(check):
    gif = b"GIF89a-the-committed-bytes"
    entry = gif_record_entry(gif, "R", "R", {"tool_name": "Write"}, "2.1.0", "vhs 1")
    check("m0 the entry a recording writes is one --check accepts: its own refusal "
          "and bytes compare clean (%r)"
          % (gif_record_problems({GIF_KEY: {GIF_NAME: entry}}, GIF_NAME, gif, "R"),),
          gif_record_problems({GIF_KEY: {GIF_NAME: entry}}, GIF_NAME, gif, "R") == []
          and entry["model"] == MODEL and entry["cliVersion"] == "2.1.0")

    # The sidecar exactly as capture-screenshots.mjs writes it: two-space JSON, a
    # trailing newline, keys in the order it chose. A recording may add its own key
    # and must leave every byte of the screenshots' half where it was - and of any
    # key neither tool owns today, which is what `elsewhere` is for.
    shots = {"note": "Written by capture-screenshots - é",
             "images": {"a.png": {"sha256": "aa", "version": "3.1.0"},
                        "b.png": {"sha256": "bb", "version": "3.1.0"}},
             "elsewhere": {"kept": True}}
    shots_text = json.dumps(shots, indent=2, ensure_ascii=False) + "\n"
    merged = merged_sidecar(json.loads(shots_text), GIF_NAME, entry)
    rest = dict((k, v) for k, v in merged.items() if k != GIF_KEY)
    check("m1 a recording writes its OWN key and leaves the screenshots' entries "
          "byte-identical once serialised",
          sidecar_text(rest) == shots_text
          and merged.get(GIF_KEY) == {GIF_NAME: entry})
    before = json.loads(shots_text)
    merged_sidecar(before, GIF_NAME, entry)
    check("m2 the merge returns a new body and leaves the one it was handed alone",
          before == shots)

    d = tempfile.mkdtemp(prefix="audit-demo-gif-selftest-")
    try:
        out = os.path.join(d, GIF_NAME)
        side = os.path.join(d, SIDECAR)
        with open(out, "wb") as fh:
            fh.write(gif)
        with open(side, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(shots_text)
        err = record_gif(out, entry)
        with open(side, encoding="utf-8") as fh:
            written = json.loads(fh.read())
        check("f0 a recording writes the record beside the GIF, and --check on "
              "the same tree finds nothing (got %r, then %r)"
              % (err, recorded_gif_problems(out, "R")),
              err is None and recorded_gif_problems(out, "R") == []
              and written.get("images") == shots["images"])
        with open(side, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        err = record_gif(out, entry)
        with open(side, encoding="utf-8") as fh:
            kept = fh.read()
        check("f1 a sidecar that will not parse is REFUSED rather than replaced - "
              "rewriting it would drop every screenshot record it held: %r" % (err,),
              err is not None and kept == "{ not json")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _screen_cases(check):
    refusal = ("[require-plan] Outside the running plan (change magnitude 120 "
               "(> 80)): src/billing.ts\nPhase P2 is in_progress, so edits are held "
               "to the plan.\n  2. the HUMAN types #no-plan in their own prompt")
    bar = u"─" * 40
    # The refusal as a terminal shows it: re-wrapped at its own width, a token split
    # mid-word, Claude Code's result marker in front, and frames between bars.
    wrapped = (u"  ⎿  Error: [require-plan] Outside the running plan (change\n"
               u"     magnitude 120 (> 80)): src/bil\n"
               u"     ling.ts\n     Phase P2 is in_progress, so edits are held to the\n"
               u"     plan.\n")
    full = wrapped + u"       2. the HUMAN types #no-plan in their own prompt\n"
    screen_full = "\n".join(["earlier frame", bar, full, bar, "> "])
    check("s0 a refusal re-wrapped by the terminal, split mid-token and drawn behind "
          "Claude Code's marker is still read as SHOWN, whole",
          shown_refusal(screen_full, refusal) == refusal)
    part = shown_refusal("\n".join([bar, wrapped, bar]), refusal)
    check("s1 a screen that shows the first lines and not the rest yields the shown "
          "part, cut on the gate's own text: %r" % (part,),
          refusal.startswith(part) and part.endswith("to the plan.")
          and first_line_shown(refusal, part))
    stub = shown_refusal(u"⎿  Error: [require-plan] Outside the", refusal)
    check("s2 THE PAIR: a screen showing less than the first line is NOT enough - "
          "the line naming the file is the refusal: %r" % (stub,),
          stub and not first_line_shown(refusal, stub))
    check("s3 a screen without the refusal shows none of it, and an empty refusal "
          "is never shown",
          shown_refusal("nothing here\n" + bar + "\nstill nothing", refusal) == ""
          and shown_refusal(screen_full, "") == "")
    split = "\n".join(["[require-plan] Outside the running", bar,
                       "plan (change magnitude 120"])
    check("s4 two frames are never read as one: half a line in each is not the line",
          not first_line_shown(refusal, shown_refusal(split, refusal)))
    check("s5 a frame is what lies between the bars, and blank frames are dropped",
          screen_frames("a\n%s\n\n%s\nb" % (bar, bar)) == ["a", "b"])


def _payload_cases(check):
    root = "/tmp/acme-store-demo"
    tap = ('{"session_id":"s","tool_name":"Edit","tool_input":{"file_path":"%s/src/'
           'checkout.ts","old_string":"a","new_string":"b"}}\n'
           '{"session_id":"s","transcript_path":"/home/x/t.jsonl","tool_name":'
           '"Write","tool_input":{"file_path":"%s/src/billing.ts","content":"x"}}'
           '{"tool_name":"Write","tool_input":{"file_path":"%s/src/billing.ts",'
           '"content":"second"}}\n' % (root, root, root))
    objs, bad = parse_payloads(tap)
    check("p0 the tap is read whole, newline-separated or not: %d object(s), %d bad"
          % (len(objs), len(bad)),
          len(objs) == 3 and bad == [])
    _objs, bad2 = parse_payloads(tap + '{"tool_name": "Wri')
    check("p1 a half-written payload is REPORTED, not dropped: %r" % (bad2,),
          len(bad2) == 1)
    picked = out_of_plan_payload(objs)
    check("p2 the replayed payload is the FIRST edit aimed at the out-of-plan file, "
          "and carries only the tool and its input - no session id, no transcript "
          "path under a home directory: %r" % (picked,),
          picked == {"tool_name": "Write",
                     "tool_input": {"file_path": root + "/src/billing.ts",
                                    "content": "x"}})
    check("p3 THE TWIN: a session that only edited the planned file has no "
          "out-of-plan payload",
          out_of_plan_payload(objs[:1]) is None)
    check("p4 a file whose name merely ENDS like the target is not the target",
          out_of_plan_payload([{"tool_name": "Edit", "tool_input": {
              "file_path": root + "/src/rebilling.ts"}}]) is None)
    roots = ["/private" + root, root]       # the order fixture_roots() returns
    stored = scrub_value(picked, roots)
    check("p5 a stored payload names no fixture path, and replays at any other path: "
          "%r" % (stored,),
          root not in json.dumps(stored)
          and unscrub_value(stored, "/var/x")["tool_input"]["file_path"]
          == "/var/x/src/billing.ts")
    check("p6 the resolved spelling of the fixture path is scrubbed too, longest "
          "root first so no half-replaced path is left",
          scrub_value("/private/tmp/acme-store-demo/a", roots) == _FIXTURE_TOKEN + "/a"
          and fixture_roots("/tmp")[0] == os.path.realpath("/tmp"))


def _pii_cases(check):
    markers = [("user name", "jdoe"), ("home path", "/Users/jdoe"),
               ("machine name", "jdoe-laptop")]
    clean = "/tmp/acme-store-demo  [require-plan] Outside the running plan"
    check("i0 THE ALLOW TWIN: a frame with only the neutral paths and the refusal "
          "carries nothing", pii_findings(clean, markers) == [])
    got = pii_findings("cwd: /Users/JDoe/work on jdoe-laptop", markers)
    check("i1 a home path and a machine name are found, case-insensitively, and "
          "reported by KIND: %r" % (got,),
          got == ["a home directory path", "home path", "machine name", "user name"])
    mail = pii_findings("Logged in as someone@example.org", markers)
    check("i2 an email address is found without being a known marker, and the "
          "finding never repeats it: %r" % (mail,),
          mail == ["an email address"] and "example" not in " ".join(mail))
    mine = personal_markers()
    header = (u" \u2590\u259b\u2588\u2588\u2588\u259b\u2588   Claude Code v2.1.292\n"
              u"\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u2588\u2580  Sonnet 5.5 \u00b7 "
              u"Claude Team\n   /private/tmp/acme-store-demo")
    check("i4 THE ALLOW TWIN of the account cases: the header as the recording mode "
          "leaves it - version, model, plan line and the neutral project path - is "
          "NOT refused: %r" % (pii_findings(header, markers),),
          pii_findings(header, markers) == [])
    acct = [("account email", "dev@acme.example"), ("organisation name", "Acme Widgets")]
    leaked = pii_findings(header + u"\n  Acme Widgets's Organization", acct)
    check("i5 a header still carrying the organisation name is refused by kind, "
          "never by value: %r" % (leaked,),
          leaked == ["organisation name"])
    homes = [pii_findings(t, []) for t in ("cwd /Users/someone/project",
                                           "cwd /home/someone/project",
                                           "cwd C:\\Users\\someone\\project")]
    check("i6 ANY user's home directory is refused, in all three spellings, without "
          "knowing the name: %r" % (homes,),
          homes == [["a home directory path"]] * 3)
    check("i7 THE TWIN: the neutral paths the demo uses, and a path that merely "
          "contains the word, are not a home directory",
          pii_findings("/private/tmp/acme-store-demo /tmp/acme-store-demo-kit/audit "
                       "src/home/users.ts", []) == [])
    status = json.dumps({"loggedIn": True, "email": "dev@acme.example",
                         "orgName": "Acme Widgets", "orgId": "x", "subscriptionType": "team"})
    check("i8 the account's email and organisation are read off `claude auth status "
          "--json` - and nothing else from it, and nothing from an answer that is "
          "not JSON: %r" % (account_markers_from(status),),
          account_markers_from(status) == acct
          and account_markers_from("Logged in as dev") == []
          and account_markers_from(json.dumps({"email": "", "orgName": None})) == [])
    check("i3 the host's own markers are read from the host, and none is shorter "
          "than a word can safely be matched: %r" % (sorted(set(k for k, _ in mine)),),
          any(k == "home path" for k, _ in mine)
          and all(len(v) >= _MIN_MARKER for _k, v in mine))


def _session_file_cases(check):
    calls = command_script_calls(os.path.join(PLUGIN_SRC, "commands"))
    check("e0 the allow list is read off the plugin's own commands and includes the "
          "status call the demo opens on: %d call(s)" % (len(calls),),
          "scripts/status/audit-status.py" in calls
          and all(c.startswith("scripts/") and c.endswith(".py") for c in calls))
    settings = demo_settings(KIT_PLUGIN, calls, KIT_DIR + "/" + TAP_NAME)
    allow = settings["permissions"]["allow"]
    check("e1 every allowed script call is rooted at the copy the session loads, "
          "and nothing grants a mode",
          all(a.startswith('Bash(python3 "%s/scripts/' % KIT_PLUGIN)
              for a in allow if a.startswith("Bash("))
          and "defaultMode" not in settings["permissions"]
          and "bypassPermissions" not in json.dumps(settings))
    check("e6 file edits are allowed by ONE Edit rule under the demo's src/ - a "
          "Write rule matches nothing and puts a warning on screen: %r"
          % ([a for a in allow if not a.startswith("Bash(")],),
          [a for a in allow if not a.startswith("Bash(")] == ["Edit(./src/**)"])
    check("e2 THE PAIR: no rule allows Bash beyond those calls - a bare Bash allow "
          "would let the session run anything without the prompt a reader expects",
          all(a.startswith('Bash(python3 "') for a in allow if a.startswith("Bash"))
          and "Bash" not in allow)
    with open(TAPE, encoding="utf-8") as fh:
        tape = fh.read()
    check("e3 the committed tape names the paths, outputs and model this tool "
          "reads: %r" % (tape_problems(tape),),
          tape_problems(tape) == [])
    bad = tape.replace("--model %s" % MODEL, "--model opus") \
        + "\nType \"--dangerously-skip-permissions --permission-mode bypassPermissions\"\n"
    check("e4 THE PAIR: a tape on another model, or showing any spelling of a "
          "permission mode, is refused once per spelling: %r" % (tape_problems(bad),),
          len(tape_problems(bad)) == 4)
    stripped = [need for need, _why in TAPE_NEEDS
                if not any(need in p for p in tape_problems(tape.replace(need, "")))]
    check("e7 every line the lint requires is one it actually checks: removing any "
          "of them from the committed tape is a finding naming it (unchecked: %r)"
          % (stripped,),
          stripped == [])
    check("e5 the fixture and the kit sit outside every home directory",
          not FIXTURE_DIR.startswith(os.path.expanduser("~"))
          and not KIT_DIR.startswith(os.path.expanduser("~"))
          and not FIXTURE_DIR.startswith(REPO))


def _tape_step_cases(check):
    steps = tape_steps("# c\nOutput a.gif\nSet Width 9\nHide\nType \"claude\"\n"
                       "Ctrl+L\nShow\nType \"/audit:status\"\nEnter\n")
    check("ts0 the dry run's order marks what runs between Hide and Show as off "
          "camera and the rest as on it, and leaves out comments and settings: %r"
          % (steps,),
          steps == [(False, "Hide"), (False, 'Type "claude"'), (False, "Ctrl+L"),
                    (False, "Show"), (True, 'Type "/audit:status"'), (True, "Enter")])
    with open(TAPE, encoding="utf-8") as fh:
        real = tape_steps(fh.read())
    first_show = [ln for _on, ln in real].index("Show")
    hidden = [ln for _on, ln in real[:first_show]]
    shown = [ln for _on, ln in real[first_show:]]
    check("ts1 THE PAIR, on the committed tape: the launch runs before the camera "
          "first comes on, the status command after it, and no /clear starts a "
          "second conversation that reprints the header",
          any("claude --model" in ln for ln in hidden)
          and not any("/clear" in ln for _on, ln in real)
          and 'Type "/audit:status"' in shown
          and not any("claude --model" in ln for ln in shown))


def _limit_cases(check):
    limit = usage_limit_problem(u"\u23bf  You've hit your session limit \u00b7 resets 2am")
    other = usage_limit_problem(u"\u23fa Usage limit reached \u00b7 continuing at 2am")
    check("ul0 both spellings of the usage-limit screen void the take, named as the "
          "limit: %r" % (limit,),
          limit is not None and other is not None and "usage limit" in limit)
    check("ul1 THE TWIN: an ordinary turn - including one that says the word "
          "'limit' - is not a usage limit",
          usage_limit_problem("Validate the payload; limit the items array to 100") is None
          and usage_limit_problem(None) is None)
    folded = collapsed_steps([(False, "Hide"), (False, "Ctrl+J"), (False, "Ctrl+J"),
                              (True, "Ctrl+J"), (True, "Enter")])
    check("ul2 the dry run folds a run of one key into one row with its count, and "
          "never across the camera boundary: %r" % (folded,),
          folded == [(False, "Hide", 1), (False, "Ctrl+J", 2), (True, "Ctrl+J", 1),
                     (True, "Enter", 1)])


def _fixture_cases(check):
    default = _loader.load(os.path.join(HOOKS, "_config.py")).DEFAULTS["manifestPath"]
    d = tempfile.mkdtemp(prefix="audit-demo-gif-selftest-")
    try:
        build_fixture(d)
        files = sorted(os.path.relpath(os.path.join(r, f), d).replace(os.sep, "/")
                       for r, _dirs, fs in os.walk(d) if ".git" not in r.split(os.sep)
                       for f in fs)
        with open(os.path.join(d, MANIFEST_REL), encoding="utf-8") as fh:
            meta = json.load(fh).get("meta", {})
    finally:
        # The fixture initialises a repository and stages nothing into it, so it
        # holds no read-only object for the windows runner to refuse.
        shutil.rmtree(d, ignore_errors=True)
    d2 = tempfile.mkdtemp(prefix="audit-demo-gif-selftest-")
    try:
        build_fixture(d2)
        with open(os.path.join(d2, MANIFEST_REL), encoding="utf-8") as fh:
            plan = json.load(fh)
    finally:
        shutil.rmtree(d2, ignore_errors=True)
    findings, _warn = plan_findings(plan)
    # What a writer leaves behind: its own new row in an index that holds none of
    # the tasks already there. An ABSENT index is not checked at all, so it would
    # not show the defect.
    stripped = dict(plan)
    stripped["fileIndex"] = {OUT_OF_PLAN_REL: ["P2.1"]}
    missing, _w = plan_findings(stripped)
    check("fx1 the demo plan passes the validation a writer runs before keeping a "
          "write - its FINDINGS, not an exit code: %r" % (findings,),
          findings == [] and plan.get("fileIndex")
          == {IN_PLAN_REL: ["P2.1"], "src/search.ts": ["P2.2"]})
    check("fx2 THE TWIN: the same plan with an index missing its tasks' rows is "
          "refused by that same "
          "validation, naming each task's file - the defect a session met on "
          "camera: %r" % ([f[:50] for f in missing],),
          len([f for f in missing if "missing from fileIndex" in f]) == 2
          and any(IN_PLAN_REL in f for f in missing)
          and any("src/search.ts" in f for f in missing))
    check("fx0 the demo plan sits where the plugin looks when nothing says otherwise "
          "(%s), and no config file names it: %r" % (default, files),
          MANIFEST_REL == default
          and files == sorted([default, IN_PLAN_REL, OUT_OF_PLAN_REL])
          and "manifestPath" not in meta)


def _screen_reading_cases(check):
    bar = VHS_FRAME_BAR
    # The shape of a real failed take's log: the tape command echoed with the limit
    # alternation in its pattern, then the failed Wait's screen.
    wait_echo = ("Wait Screen (?s)(Update|Write)\\([^)]*checkout\\.ts\\).*for \\d+s "
                 u"\u00b7 done|hit your session limit|Usage limit reached\n")
    head = u" \u2590\u259b\u2588\u2588\u2588\u259b\u2588   Claude Code v2.1.292\n"
    foot = u"\n  \u23f5\u23f5 auto mode on (shift+tab to cycle)\n"
    plain_screen = head + u"\u23fa Write(src/checkout.ts)\n  \u23bf  Added 10 lines" + foot
    log = (wait_echo + 'failed to execute command: timeout waiting for "Screen ..." '
           "to match ...; last value was: " + plain_screen + "\nrecording failed\n")
    check("sr0 a log whose echoed tape commands carry the limit pattern, and whose "
          "screen shows no limit, is NOT a usage limit: %r"
          % (screen_problems("", log),),
          screen_problems("", log) == [] and len(log_screens(log)) == 1
          and "Wait Screen" not in log_screens(log)[0]
          and "Added 10 lines" in log_screens(log)[0])
    limited = log.replace("Added 10 lines", u"You've hit your session limit")
    got = screen_problems("", limited)
    check("sr1 THE TWIN: the same log whose SCREEN shows the limit is one, named "
          "first: %r" % (got,),
          len(got) == 1 and "usage limit" in got[0])
    cut = log.replace(foot, "")             # the bottom row is the last content row
    outgrew = screen_problems("", cut)
    check("sr2 a screen showing Claude Code's header and not its footer is a take "
          "that outgrew the terminal - the bottom VHS cannot read: %r" % (outgrew,),
          len(outgrew) == 1 and "outgrew the terminal" in outgrew[0])
    boxed = plain_screen.replace(foot, "\n" + u"\u2500" * 121 + foot)   # Claude's own border
    frames = "\n".join([">", bar, boxed, bar, boxed])
    check("sr3 THE TWIN, over the text output: frames with header and footer both "
          "are fine, and the frames are split at VHS's own bar only: %r"
          % (len(vhs_frames(frames)),),
          screen_problems(frames, "") == [] and len(vhs_frames(frames)) == 3)
    narr = screen_problems(plain_screen.replace(
        "Added 10 lines", "The command didn't fill in <manifestPath>, so I used it"), "")
    check("sr4 a take narrating an unfilled command placeholder is refused: %r"
          % (narr,),
          len(narr) == 1 and "placeholder" in narr[0])
    popup = (head + u"\u276f /audit:status\n    /audit:status   (audit) print manifest "
             "status\n    /audit:task     (audit) add a task\n\n\n")
    check("sr6 THE TWIN of sr2: a command popup hides the footer too, but leaves the "
          "rows under it blank - that is not a cut screen",
          outgrew_problem([popup]) is None
          and outgrew_problem(log_screens(cut)) is not None)
    check("sr7 an edit drawn on screen that the tap never saw means no hook ran - "
          "named as such; with the edit tapped, or with no edit on screen, it is "
          "not this finding",
          hooks_problem(plain_screen, []) is not None
          and hooks_problem(plain_screen, [{"tool_name": "Write"}]) is None
          and hooks_problem(head + foot, []) is None)
    status = plain_screen.replace("Added 10 lines", "READY NOW  1 task(s)  "
                                  "docs/audit/audit-plan.json filled in by the plan")
    check("sr5 THE TWIN: an ordinary status answer - even one using the words "
          "'filled in' - is not that narration",
          screen_problems(status, "") == [])


def _prompt_cases(check):
    settings = demo_settings(KIT_PLUGIN, ["scripts/status/audit-status.py"],
                             KIT_DIR + "/" + TAP_NAME)
    check("pr0 the session's settings switch prompt suggestions and spinner tips off: "
          "%r" % (dict((k, settings.get(k)) for k in ("promptSuggestionEnabled",
                                                       "spinnerTipsEnabled")),),
          settings.get("promptSuggestionEnabled") is False
          and settings.get("spinnerTipsEnabled") is False)
    check("pr1 ...and nothing else changed shape: the same top-level keys as before "
          "plus those two, the allow list and the one tap hook: %r" % (sorted(settings),),
          sorted(settings) == ["hooks", "permissions", "promptSuggestionEnabled",
                               "spinnerTipsEnabled"]
          and sorted(settings["permissions"]) == ["allow"]
          and list(settings["hooks"]) == ["PreToolUse"]
          and len(settings["hooks"]["PreToolUse"]) == 1)
    with open(TAPE, encoding="utf-8") as fh:
        tape = fh.read()
    typed = tape_prompts(tape)
    check("pr2 the tape's own prompts are read off the tape, on camera only, and "
          "carry no digit: %r" % ([t[:24] for t in typed],),
          typed and typed[0] == "/audit:status"
          and any(IN_PLAN_REL in t for t in typed)
          and any(OUT_OF_PLAN_REL in t for t in typed)
          and not any("claude --model" in t for t in typed)
          and not any(re.search(r"\d", t) for t in typed))
    real = "\n".join([u"\u276f " + t for t in typed]
                     + [u"\u276f\u00a0Try \"how do I log an error?\"",
                        u"   \u276f 1. Yes, install",
                        u"  \u276f /audit:status      (audit) print manifest status"])
    check("pr3 THE ALLOW TWIN: the tape's real prompts as sent, plus the live input "
          "box, a dialog option and the command popup, are no finding: %r"
          % (stray_prompt_problem(real, typed),),
          stray_prompt_problem(real, typed) is None)
    mangled = real + u"\n\u276f 20 lines."
    got = stray_prompt_problem(mangled, typed)
    check("pr4 a sent prompt the tape never typed - the tail of one whose start a "
          "dialog took - is refused, quoting it: %r" % (got,),
          got is not None and "20 lines." in got
          and screen_problems(mangled, "", typed) == [got])
    wrapped = u"\u276f " + typed[-1][:50]
    check("pr5 a long prompt the terminal wrapped is still the tape's own: its first "
          "line is the start of a typed prompt",
          stray_prompt_problem(wrapped, typed) is None)
    empty_box = u"\u276f" + u" " * 60
    check("pr7 an EMPTY live box - the prompt mark and padding only - is not a sent "
          "prompt and not a stray one: %r" % (submitted_prompts(real + "\n" + empty_box),),
          submitted_prompts(empty_box) == []
          and stray_prompt_problem(real + "\n" + empty_box, typed) is None)
    box_waits = [ln for _on, ln in tape_steps(tape)
                 if ln.startswith("Wait") and u"\u276f" in ln]
    # Go's spelling of the no-break space, read as Python's, so the tape's own
    # pattern is what these cases run.
    pats = [re.compile(ln[ln.index("/") + 1:ln.rindex("/")].replace("\\x{00A0}", u"\u00a0"))
            for ln in box_waits]
    border = u"\u2500" * 120 + u"   "
    done = u"READY NOW  1 task(s)\n\u273b Cogitated for 10s \u00b7 done 2:59 AM\n"

    def screen(box_row):
        return done + border + "\n" + box_row + "\n" + border + "\n  footer"
    empty, holding = screen(empty_box), screen(u"\u276f\u00a0Now rewrite src/billing.ts")
    placeholder = screen(u"\u276f\u00a0Try \"how do I log an error?\"")
    dialog = done + border + (u"\n LSP plugin recommendation\n   \u276f 1. Yes, install\n"
                              u"     2. No, not now\n")
    # The mark alone on a row with no border round it is not the live box: the box
    # is drawn between its two border rows, and nothing else is.
    unboxed = done + empty_box + "\n  footer"
    check("pr8 the tape's input-box Wait matches the EMPTY live box, with or without "
          "the placeholder, and not a box holding text, an open dialog, or the mark "
          "outside the box's borders (%d such "
          "Wait(s) read off the tape)" % (len(pats),),
          len(pats) == len(box_waits) and len(pats) > 0
          and all(bool(p.search(scr)) for p in pats for scr in (empty, placeholder)
                  if "READY NOW" in p.pattern)
          and not any(p.search(scr) for p in pats
                      for scr in (holding, dialog, unboxed)))
    ends = [ln for _on, ln in tape_steps(tape)
            if ln.startswith("Wait") and "Interrupted" in ln]
    end_pats = [re.compile(ln[ln.index("/") + 1:ln.rindex("/")].replace(
        "\\x{00A0}", u"\u00a0")) for ln in ends]
    refused = (u"\u23fa Write(src/billing.ts)\n  \u23bf  Error: PreToolUse:Write hook "
               u"error: [require-plan] Outside the running plan (change magnitude "
               u"131 (> 80)): src/billing.ts\n\n\u23fa The plan gate blocked the "
               u"write.\n")
    box = border + "\n" + empty_box + "\n" + border + "\n  footer"
    interrupted = refused + u"  \u23bf  Interrupted \u00b7 What should Claude do instead?\n" + box
    finished = refused + u"\u273b Worked for 7s \u00b7 done 3:08 AM\n" + box
    # The last frame of the first take that got this far: a turn still running
    # under an input box that is empty because Claude, not the user, has the turn.
    running = refused + (u"\u23fa Bash(python3 \"/tmp/acme-store-demo-kit/audit/scripts/"
                         u"manifest/audit-task.py\" add ...)\n\u273b Jitterbugging\u2026 "
                         u"(30s \u00b7 thinking)\n") + box
    check("pr9 the tape's end Wait proves a finished end state - interrupted, or the "
          "turn done - with the box empty, and NOT a turn still running under an "
          "empty box (%d end Wait(s) read off the tape)" % (len(end_pats),),
          len(end_pats) == 1
          and bool(end_pats[0].search(interrupted)) and bool(end_pats[0].search(finished))
          and not end_pats[0].search(running)
          and not end_pats[0].search(done + box))
    digit = tape.replace("around a hundred and twenty lines", "about 120 lines")
    check("pr6 a tape prompt carrying a digit is refused by the tape lint: %r"
          % ([p for p in tape_problems(digit) if "digit" in p],),
          tape_problems(tape) == []
          and len([p for p in tape_problems(digit) if "digit" in p]) == 1)


def _env_cases(check):
    host = {"PATH": "/usr/bin", "HOME": "/h", "CLAUDECODE": "1",
            "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_CODE_ENTRYPOINT": "cli",
            "AUDIT_LOCK_TOKENS": "t", "CLAUDE_CODE_OAUTH_TOKEN": "o",
            "CLAUDE_CONFIG_DIR": "/c", "AUDITOR": "kept"}
    env = session_env(host)
    check("v0 the caller's session markers and lock tokens do not reach the take: %r"
          % (sorted(env),),
          not any(k in env for k in ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION",
                                     "CLAUDE_CODE_ENTRYPOINT", "AUDIT_LOCK_TOKENS")))
    check("v1 THE TWIN: the login and config the CLI needs survive, and so does a "
          "variable that only looks similar",
          env.get("CLAUDE_CODE_OAUTH_TOKEN") == "o" and env.get("CLAUDE_CONFIG_DIR") == "/c"
          and env.get("AUDITOR") == "kept" and env.get("PATH") == "/usr/bin")
    check("v2 the demo's own documented switches are set, an undocumented one is "
          "not, and the caller's dict is left alone",
          env.get("IS_DEMO") == "1" and env.get("DISABLE_AUTOUPDATER") == "1"
          and "CLAUDE_CODE_HIDE_ACCOUNT_INFO" not in env
          and "IS_DEMO" not in host and host.get("CLAUDECODE") == "1")


def _fake_cli(plugins_json, status_json, status_exit=0):
    """A stand-in for `subprocess.run` answering the two read-only queries a take
    asks of the CLI, so the cases never start the operator's own `claude`."""
    def run(argv, **_kw):
        if argv[1:3] == ["plugin", "list"]:
            return subprocess.CompletedProcess(argv, 0, plugins_json, "")
        if argv[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(argv, status_exit, status_json, "")
        return subprocess.CompletedProcess(argv, 1, "", "unexpected call %r" % (argv,))
    return run


def _tree_bytes(root):
    """{relative path: bytes} of every file under `root` - a whole-tree snapshot, so
    a write anywhere in it is a difference and not only a write to a named file."""
    out = {}
    for r, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(r, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = fh.read()
    return out


_LSP_ROW = {"id": "typescript-lsp@claude-plugins-official", "version": "1.0.0",
            "scope": "user", "enabled": True}
_KEPT_ROW = {"id": "audit@quality-gates", "version": "3.1.0", "scope": "project",
             "enabled": True, "projectPath": "/srv/work/shop"}


def _config_isolation_cases(check):
    host = {"PATH": "/usr/bin", "HOME": "/h", "CLAUDE_CONFIG_DIR": "/operator/cfg",
            "CLAUDE_CODE_OAUTH_TOKEN": "tok"}
    plan = config_plan(host)
    env = session_env(host, plan["configDir"])
    check("ci0 a token in the environment gives the take a config of its own under "
          "the kit's scratch directory, which replaces the caller's config dir in "
          "the take's environment: %r" % ((plan["isolated"], plan["configDir"],
                                           env.get("CLAUDE_CONFIG_DIR")),),
          plan["isolated"] is True
          and plan["configDir"].startswith(KIT_DIR + "/")
          and env.get("CLAUDE_CONFIG_DIR") == plan["configDir"]
          and env.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok")
    bare = dict(host)
    del bare["CLAUDE_CODE_OAUTH_TOKEN"]
    fallback = config_plan(bare)
    env2 = session_env(bare, fallback["configDir"])
    check("ci1 THE TWIN: with no token the take falls back to the operator's own "
          "config - the caller's config dir reaches it unchanged - and the plan says "
          "why, naming the variable: %r" % (fallback["why"],),
          fallback["isolated"] is False and fallback["configDir"] is None
          and env2.get("CLAUDE_CONFIG_DIR") == "/operator/cfg"
          and "CLAUDE_CODE_OAUTH_TOKEN" in fallback["why"])
    check("ci2 an empty token is no token: blank is not a credential",
          config_plan(dict(bare, CLAUDE_CODE_OAUTH_TOKEN="  "))["isolated"] is False)

    roots = ["/private/tmp/acme-store-demo", "/tmp/acme-store-demo"]
    d = tempfile.mkdtemp(prefix="audit-demo-gif-selftest-")
    try:
        operator = os.path.join(d, "operator")
        scratch = os.path.join(d, "kit", "claude-config")
        os.makedirs(os.path.join(operator, "projects", "-srv-work-shop"))
        with open(os.path.join(operator, ".claude.json"), "w", encoding="utf-8") as fh:
            json.dump({"projects": {"/srv/work/shop": {"hasTrustDialogAccepted": True}}},
                      fh)
        op_env = {"HOME": d, "CLAUDE_CONFIG_DIR": operator}
        status = json.dumps({"loggedIn": True,
                             "projectsDirectory": os.path.join(operator, "projects")})
        cli = _fake_cli(json.dumps([_KEPT_ROW]), status)
        before_bytes = _tree_bytes(operator)
        before = config_footprint(op_env, roots, run=cli)
        seed_isolated_config(scratch)
        take = session_env(dict(op_env, CLAUDE_CODE_OAUTH_TOKEN="tok"), scratch)
        # What a take does to the config it was handed: trust the folder, keep a
        # transcript, install the plugin a stray key accepted.
        cfg = take["CLAUDE_CONFIG_DIR"]
        with open(os.path.join(cfg, ".claude.json"), "w", encoding="utf-8") as fh:
            json.dump({"projects": {roots[0]: {"hasTrustDialogAccepted": True}}}, fh)
        os.makedirs(os.path.join(cfg, "projects", "-private-tmp-acme-store-demo"))
        after = config_footprint(op_env, roots, run=cli)
        isolated = {"isolated": True, "configDir": scratch, "why": ""}
        refused = footprint_refusals(isolated, before, after)
        check("ci3 a take run against an isolated config leaves the operator's config "
              "byte-identical - trust, transcripts and plugins all landed in the "
              "scratch config - and the comparison finds nothing: %r" % (refused,),
              _tree_bytes(operator) == before_bytes and refused == []
              and before["trust"] == [] and after["trust"] == []
              and after["transcripts"] == [])
        report = leftover_lines(isolated, before, after)
        check("ci4 ...and the report after such a take names the scratch config as "
              "removed and no path of the operator's: %r" % (report,),
              len(report) == 1 and scratch in report[0]
              and operator not in report[0])
        # The leak the comparison exists for: the same take, writing into the
        # operator's config after all.
        with open(os.path.join(operator, ".claude.json"), "w", encoding="utf-8") as fh:
            json.dump({"projects": {"/srv/work/shop": {"hasTrustDialogAccepted": True},
                                    roots[0]: {"hasTrustDialogAccepted": True}}}, fh)
        leaked = footprint_refusals(isolated, before,
                                    config_footprint(op_env, roots, run=cli))
        check("ci5 THE TWIN: an isolated take whose trust entry reached the "
              "operator's config anyway is REFUSED, naming the entry and the file: %r"
              % (leaked,),
              len(leaked) == 1 and roots[0] in leaked[0] and ".claude.json" in leaked[0])
        fallback_plan = {"isolated": False, "configDir": None, "why": ""}
        os.makedirs(os.path.join(operator, "projects", "-private-tmp-acme-store-demo"))
        now = config_footprint(op_env, roots, run=cli)
        left = leftover_lines(fallback_plan, before, now)
        check("ci6 a take against the operator's own config prints what it left there "
              "- the trust entry for the demo folder with the file it sits in, the "
              "transcript directory - each with the step that removes it: %r" % (left,),
              footprint_refusals(fallback_plan, before, now) == []
              and any(roots[0] in ln and ".claude.json" in ln and "delete" in ln
                      for ln in left)
              and any("-private-tmp-acme-store-demo" in ln and "rm -rf" in ln
                      for ln in left))
    finally:
        # Plain files only, no repository.
        shutil.rmtree(d, ignore_errors=True)

    found, why = trust_entries("{ not json", roots)
    check("ci7 a global config that will not parse is a reason, never an empty "
          "answer read as 'no trust entry': %r" % ((found, why),),
          found == [] and why is not None)
    check("ci8 the transcript directory name is the path with every character "
          "outside letters and digits turned into a dash, as the CLI names it",
          transcript_names(roots) == ["-private-tmp-acme-store-demo",
                                      "-tmp-acme-store-demo"])


def _plugin_change_cases(check):
    rows, why = plugin_rows(json.dumps([_KEPT_ROW, _LSP_ROW]))
    check("pc0 the installed plugins are read off `claude plugin list --json`: %r"
          % ((len(rows), why),),
          why is None and len(rows) == 2)
    bad, bad_why = plugin_rows("Plugins: none")
    check("pc1 an answer that is not that JSON is a reason, never an empty list "
          "that would compare equal to another empty list: %r" % (bad_why,),
          bad is None and bad_why is not None)
    before, _w = plugin_rows(json.dumps([_KEPT_ROW]))
    after, _w2 = plugin_rows(json.dumps([_KEPT_ROW, _LSP_ROW]))
    same = plugin_changes(before, before)
    check("pc2 THE ALLOW TWIN: an unchanged plugin list is no change: %r" % (same,),
          same == [])
    added = plugin_changes(before, after)
    check("pc3 a plugin a take installed is ONE change, naming the plugin, the scope "
          "it landed in and the command that undoes it: %r" % (added,),
          len(added) == 1 and "typescript-lsp@claude-plugins-official" in added[0]
          and "user" in added[0]
          and "claude plugin uninstall typescript-lsp@claude-plugins-official "
              "--scope user" in added[0])
    gone = plugin_changes(after, before)
    flipped_row = dict(_KEPT_ROW, enabled=False)
    flipped = plugin_changes(before, plugin_rows(json.dumps([flipped_row]))[0])
    check("pc4 each other kind of change names its own undo - an uninstall is put "
          "back by an install, a disable by an enable run in that project: %r"
          % (gone + flipped,),
          len(gone) == 1 and "claude plugin install typescript-lsp@claude-plugins-"
                             "official --scope user" in gone[0]
          and len(flipped) == 1
          and "claude plugin enable audit@quality-gates --scope project" in flipped[0]
          and "/srv/work/shop" in flipped[0])
    fallback = {"isolated": False, "configDir": None, "why": ""}
    snap = {"plugins": before, "pluginsWhy": None, "trust": [], "trustWhy": None,
            "trustFile": "/c/.claude.json", "transcripts": [], "transcriptsWhy": None}
    refused = footprint_refusals(fallback, snap, dict(snap, plugins=after))
    check("pc5 a take recorded against the operator's config whose installed plugins "
          "changed is REFUSED, naming the change and its undo: %r" % (refused,),
          len(refused) == 1 and "claude plugin uninstall" in refused[0]
          and "typescript-lsp" in refused[0])
    blind = footprint_refusals(fallback, snap, dict(snap, plugins=None,
                                                    pluginsWhy="exit 1"))
    check("pc6 a plugin list that could not be read after the take is a refusal of "
          "its own - an unreadable answer is never 'unchanged': %r" % (blind,),
          len(blind) == 1 and "exit 1" in blind[0])


def _account_query_cases(check):
    status = json.dumps({"loggedIn": True, "email": "dev@acme.example",
                         "orgName": "Acme Widgets"})
    found, why = account_markers({}, run=_fake_cli("[]", status))
    check("aq0 THE ALLOW TWIN: an account query that names the account gives its "
          "markers and no refusal: %r" % ((len(found), why),),
          len(found) == 2 and why is None
          and take_preconditions(why, None) == [])
    none, none_why = account_markers({}, run=_fake_cli("[]", "", status_exit=1))
    refused = take_preconditions(none_why, None)
    check("aq1 an account query that gives no answer REFUSES the take before it "
          "starts, rather than narrowing the scan to the email pattern: %r"
          % (refused,),
          none == [] and none_why is not None and len(refused) == 1
          and "auth status" in refused[0] and "narrow" not in refused[0])
    blind = take_preconditions(None, "`claude plugin list --json` exited 1")
    check("aq2 a plugin list that cannot be read BEFORE the take refuses it too: "
          "nothing could be compared afterwards: %r" % (blind,),
          len(blind) == 1 and "plugin list" in blind[0])


def _selftest():
    from _suite import run         # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    # `safe_stdio()` first, as every `.py` under scripts/ and hooks/ does - the AST
    # lint that enforces it does not scan tools/, and this file prints a deny message
    # captured from the product, which is exactly the kind of text a legacy code page
    # cannot spell.
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
