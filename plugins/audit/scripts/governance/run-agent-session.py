#!/usr/bin/env python3
"""
Run one role - the writer or the reviewer - as a headless top-level Claude Code
session in a task's tree, and print what that session cost, read from the session's
own result.

WHY A TOP-LEVEL SESSION AND NOT A SUBAGENT. A task's writer had been a subagent the
main loop dispatched, so its spend arrived folded into the main loop's and its price
was an apportionment rather than a figure. A `claude -p` session is priced by its
own `result` event's `total_cost_usd`, and that is the number printed here - beside
nothing, averaged with nothing - so a caller that re-prices the transcript can put
the two side by side and see a difference rather than lose it.

WHAT THE ARGV CARRIES, AND WHY EACH ONE:

  * `--model` as a FULL id, refused when it is an alias (`ALIAS_SHAPE`): an alias
    names whatever is newest on the day, so two runs under one plan could be two
    models and their costs would not compare;
  * `--effort`, `--permission-mode auto` and `--max-budget-usd` from the caller -
    the budget is the per-session ceiling, enforced by the CLI itself;
  * `--output-format stream-json` with `--verbose`: claude 2.1.305 refuses the
    pair in print mode without it (probed 2026-10-21: "When using --print,
    --output-format=stream-json requires --verbose");
  * `--plugin-dir` naming the plugin this file belongs to, so its hooks act on
    the session the same way they act on an interactive one;
  * the reviewer alone gets `--agents <file>` built from `agents/audit-reviewer.md`
    and `--agent audit-reviewer`; the writer is a plain session and gets no agent
    flag and no agent body. The definition goes in a FILE, which the CLI's help
    documents for print mode, rather than as an argv string: the body is several
    kilobytes of prose that a batch-file launcher would re-quote;
  * `--skill NAME`, repeatable, puts the named skills in the session's system prompt
    from its first turn: each SKILL.md is found the way a session in that tree
    finds a skill (`_skill_places.resolve_skill`) and the bodies, each wrapped with its name, are
    written to ONE file under the scratch and passed as
    `--append-system-prompt-file`; `claude --help` does not list that flag, though
    the CLI accepts it, and a probe (claude 2.1.307, 2026-10-23: `--agents <file>
    --agent <name> --append-system-prompt-file <file>` on a print-mode session)
    had the reviewer quote a token only the appended skill held, so the reviewer
    path delivers it as the writer's does. A subagent definition's `skills` field
    was probed (claude 2.1.307, 2026-10-23) and the session did not see the skill,
    which is why this appends instead; the prompt on stdin is untouched by it. The
    order a name is searched in is the user's skills, the project's, then the
    plugin's own (see `_skill_places`), and each skill is headed by its base
    directory, as the Skill tool does. A name that
    resolves nowhere refuses to start, naming every place looked in, because a
    skill the plan declares and the session never loads is a defect the cost of
    which nobody sees. `--record` carries each skill's name, path and sha256, so a
    reader can tell which skills a session had without a Skill call;
  * `--resume <session id>` continues a recorded session and changes nothing else;
    an id that is not a UUID is refused (`SESSION_ID`), so no flag rides in as one.
  * the budget must be a finite positive number - `float()` also reads `inf` and
    `nan`, and an infinite ceiling is none.

THE PROMPT GOES ON STDIN, NEVER IN ARGV. A sibling session cleaning up with
`pkill -f` matches command lines, so a prompt in argv makes every session whose
prompt happens to contain the pattern a target. This file reads its own prompt off
stdin or `--prompt-file` for the same reason.

THE CHILD RUNS IN A PROCESS GROUP OF ITS OWN (`_proc_group.group_kwargs`) with a
TMPDIR of its own, so a stop reaches everything it started and nothing it wrote to
a temp directory lands in a sibling's. That directory is made under the PARENT's temp
directory (`tempfile.gettempdir()`, so a caller's TMPDIR is honoured) and not under
the task's scratch: the drive keeps the scratch inside the project, and a TMPDIR below
it put every fixture a session's suites built inside the real checkout. A parent temp
directory with a `.git` above it is refused, naming it, and nothing else is tried.
The scratch keeps a record of where the TMPDIR was (`<its name>.tmpdir`, holding the
path), since it never lies beneath it. THE TMPDIR IS REMOVED WHEN THE RUN ENDS
(`_run`'s `finally`, through `_output.remove_tree`), on success, on a failing or
missing result, on a budget stop and on SIGINT or SIGTERM, which are armed from
before the directory is made until the outcome is printed - a TMPDIR per session that
nobody removes is one more directory per session in the machine's temp, forever.
Nothing a caller is told to read lives in it, so nothing is copied out first: the
stream, its stderr and the agents file are under the state dir, the skills file and
the record under the scratch. A removal that fails is named on stderr and leaves the
exit code as the session made it. What still leaves it: a SIGKILL, after which
nothing in this process runs.

THE CHILD STARTS WITHOUT THE PARENT'S CLAUDE SESSION VARIABLES (`PARENT_SESSION_VARS`),
as a top-level session does: copied through, `CLAUDECODE` and the session id would
make the writer start as a child of the orchestrator's session, and a measured
pipeline would not be the thing a plain session is compared against. A few names are
dropped (`PARENT_SESSION_VARS`) and so is every name under `CLAUDE_CODE_`
(`PARENT_SESSION_PREFIXES`), except the provider and credential switches a plain
session inherits (`KEEP_SESSION_VARS`, `KEEP_SESSION_PREFIXES`). Everything else in
the environment (PATH, HOME, credentials, provider switches) is passed on.

THE STREAM IS SAVED under `<state-dir>/sessions/`, one file per run (a resumed
session is a second stream, which is how a transcript re-price reads a session),
with the CLI's stderr beside it.

WHAT IT PRINTS: one line, `session=<id> subtype=<subtype> is_error=<is_error>
total_cost_usd=<cost> exit=<claude's exit> stream=<path>`, the path last because it
may hold spaces; a subtype or is_error the result does not carry prints `absent`.
The cost is the LAST result event's: a resumed session's results each carry the
whole session's figure so far. A stream that ends with no result event, or whose
result lacks a session id or a numeric cost, is `could-not-run` naming the stream -
never a zero cost. A directory or file the run needs that cannot be made or read
prints `io-error:` naming the path, before claude is started.

`--record <path>` ALSO APPENDS THAT OUTCOME TO A FILE, one JSON line `{"line",
"exit"}` per run: the line printed (a usage refusal's message prefixed `usage:`)
and this script's exit code. It is how the step driver learns which session ran and what it cost without
the main loop retyping the line: the driver names the path in the command it
prints and reads each line once at its next steps, taking a last line that
does not parse as not written yet. A record that cannot be written is reported on stderr and
changes no exit code.

Exit codes (`exit_for`): 0 a result with `is_error: false` and claude exited 0 -
1 any other result - 2 usage error - 3 could-not-run - 4 a budget stop (result
subtype `error_max_budget_usd`, whatever claude exited with) - 5 io-error.
"""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

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

import _claude_home  # noqa: E402  (attach_usage_hint: a usage error names the install; claude_home: the user's skills)
import _help         # noqa: E402  (front_matter: the one frontmatter parser)
import _manifest_io  # noqa: E402  (checkout_of: is a directory inside a git checkout)
import _proc_group   # noqa: E402  (group_kwargs, tear_down, the interrupt pair)
import _skill_places  # noqa: E402  (resolve_skill, plugin_name: where a named skill lives, shared with doctor)

E_OK, E_SESSION, E_USAGE, E_COULD_NOT_RUN, E_BUDGET, E_IO = 0, 1, 2, 3, 4, 5

# The result subtype a session stopped by `--max-budget-usd` ends with. The
# spelling was reported by a review of this file and has not been probed here: a
# probe means spending past a budget on purpose.
BUDGET_STOP = "error_max_budget_usd"

# A recorded session id: the CLI writes a UUID into every event's `session_id`.
# Anything else is refused, so a value beginning with `--` cannot reach the argv
# as a flag of its own.
SESSION_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# What a parent Claude session exports to its children, and so what a top-level
# session never has: the marker that a Claude process is the parent (CLAUDECODE),
# its pid and effort (CLAUDE_PID, CLAUDE_EFFORT), its project directory
# (CLAUDE_PROJECT_DIR), the plugin's lock tokens (AUDIT_LOCK_TOKENS), and the
# session's own state under CLAUDE_CODE_ - session id, entrypoint, executable,
# messaging socket and token, SSE port, child-session marker. Passed on, each makes
# the child a child of the orchestrator's session, so the rule is: the names
# outside CLAUDE_CODE_ are dropped by name (`PARENT_SESSION_VARS`), and everything
# in that namespace is dropped by prefix (`PARENT_SESSION_PREFIXES`), which also
# takes a session variable a later CLI release exports without this file being told
# its name. The prefix would take what a top-level session does start with - the
# provider and credential switches - so those are kept by name
# (`KEEP_SESSION_VARS`) or by prefix (`KEEP_SESSION_PREFIXES`:
# CLAUDE_CODE_USE_BEDROCK, CLAUDE_CODE_USE_VERTEX and the like). This runner sets
# no CLAUDE_* variable of its own.
PARENT_SESSION_VARS = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "AUDIT_LOCK_TOKENS",
                       "CLAUDE_PROJECT_DIR")
PARENT_SESSION_PREFIXES = ("CLAUDE_CODE_",)
KEEP_SESSION_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_API_KEY_HELPER_TTL_MS",
                     "CLAUDE_CODE_SKIP_BEDROCK_AUTH", "CLAUDE_CODE_SKIP_VERTEX_AUTH",
                     "CLAUDE_CODE_SKIP_FOUNDRY_AUTH")
KEEP_SESSION_PREFIXES = ("CLAUDE_CODE_USE_",)

ROLES = ("writer", "reviewer")
REVIEWER = "audit-reviewer"
# The effort levels `claude --help` lists (2.1.305, read 2026-10-21).
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# A full model id is `claude-<family...>` with a version digit in it. Anything
# else - `opus`, `sonnet`, `fable`, `default`, `opusplan` - is an alias the CLI
# resolves to whatever is current, which is the drift this refuses.
FULL_MODEL_ID = re.compile(r"^claude-[a-z][a-z0-9-]*[0-9][a-z0-9-]*$")

# The fence `_help.front_matter` reads; the body is what follows it. Kept to the
# same pattern so the two cannot disagree on where the frontmatter ends.
_FENCE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)


# --- the argv ------------------------------------------------------------------
def is_full_model_id(model):
    return bool(FULL_MODEL_ID.match(model or ""))


def session_argv(model, effort, budget, plugin_dir, agents_file=None, resume=None,
                 skills_file=None):
    """The arguments after the `claude` executable, for one role.

    `agents_file` is the reviewer's: with it come `--agents <file>` and `--agent
    audit-reviewer`, and without it neither. `skills_file` adds
    `--append-system-prompt-file <file>` and nothing else; without it the flag is
    absent. `resume` appends the recorded id and touches nothing before it, so a
    resumed argv is the plain one plus one pair.
    """
    argv = ["-p", "--model", model, "--effort", effort,
            "--permission-mode", "auto",
            "--output-format", "stream-json", "--verbose",
            "--max-budget-usd", budget, "--plugin-dir", plugin_dir]
    if skills_file is not None:
        argv += ["--append-system-prompt-file", skills_file]
    if agents_file is not None:
        argv += ["--agents", agents_file, "--agent", REVIEWER]
    if resume is not None:
        argv += ["--resume", resume]
    return argv


def agent_definition(text):
    """`{"audit-reviewer": {...}}` from an agent file's text, or None when it has no
    frontmatter. The body below the fence is the prompt; description and tools are
    the frontmatter's."""
    match = _FENCE.match(text)
    front = _help.front_matter(text)
    if not match or not front:
        return None
    tools = [t.strip() for t in (front.get("tools") or "").split(",") if t.strip()]
    return {front.get("name") or REVIEWER: {
        "description": front.get("description") or "",
        "prompt": text[match.end():],
        "tools": tools,
    }}


# --- the skills ----------------------------------------------------------------
def find_skills(names, tree, user_home, plugin_root, running):
    """`{"found": [{"name", "path"}], "problem": str-or-None}`: the first existing
    place of each name, in the order the names came, a repeated name once. A name
    with none stops the search with a problem naming it and every place looked.
    Where a name lives is `_skill_places.resolve_skill`'s answer, the one doctor asks
    too - personal, then project, then the running plugin's own `skills/` (Claude
    Code's documented "personal over project", code.claude.com/docs/en/skills,
    "Resolve skills that share a name") - and no inventory is passed, so only a
    SKILL.md this launcher can read counts."""
    found, seen = [], set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        hit = _skill_places.resolve_skill(name, tree, user_home, plugin_root, running)
        if hit["problem"]:
            return {"found": found, "problem": hit["problem"]}
        if not hit["found"]:
            places = hit["places"]
            where = ("looked in, in this order: %s (only these places are searched: "
                     "the user's skills, the tree's .claude/skills and the running "
                     "plugin's skills/)" % ", ".join(places)) if places else (
                "a plugin-qualified name is read only from that plugin's own skills/, "
                "and this is plugin %s" % (running or "(its name could not be read)"))
            return {"found": found,
                    "problem": "the skill %s is not found - %s" % (name, where)}
        found.append({"name": name, "path": hit["path"]})
    return {"found": found, "problem": None}


def load_skills(found):
    """Each found skill with its text and the sha256 of the file's bytes. Raises
    PreparationError, naming the path, for a file that cannot be read or is not
    UTF-8 - a skill that is there and unreadable is not a missing one."""
    loaded = []
    for skill in found:
        try:
            with open(skill["path"], "rb") as fh:
                raw = fh.read()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PreparationError("could not read the skill %s from %s: %s"
                                   % (skill["name"], skill["path"], exc))
        loaded.append(dict(skill, text=text, sha256=hashlib.sha256(raw).hexdigest()))
    return loaded


def skills_prompt(loaded):
    """The text appended to the system prompt: each skill's file, whole, wrapped in a
    `<skill name="...">` element so a reader of the prompt can tell where one ends.
    The element opens with `Base directory for this skill: <dir>`, the line the Skill
    tool puts above a skill it loads, so a file the skill names under `references/`
    resolves against the skill's own directory."""
    return "\n".join('<skill name="%s">\nBase directory for this skill: %s\n\n%s\n</skill>\n'
                     % (s["name"], os.path.dirname(s["path"]), s["text"].rstrip("\n"))
                     for s in loaded)


def skills_record(loaded):
    """What `--record` keeps of the skills: name, path and digest, never the text."""
    return [{"name": s["name"], "path": s["path"], "sha256": s["sha256"]} for s in loaded]


# --- reading the stream --------------------------------------------------------
def read_stream(path):
    """`{"result": event-or-None, "unparsed": n, "problem": str-or-None}` for the
    saved stream. The result is the LAST `result` event; a result missing its
    session id or a numeric cost is a problem, not a zero."""
    last, unparsed = None, 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    unparsed += 1
                    continue
                if isinstance(event, dict) and event.get("type") == "result":
                    last = event
    except OSError as exc:
        return {"result": None, "unparsed": unparsed,
                "problem": "the stream could not be read: %s" % exc}
    if last is None:
        return {"result": None, "unparsed": unparsed,
                "problem": "the stream ended with no result event"}
    cost = last.get("total_cost_usd")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return {"result": None, "unparsed": unparsed,
                "problem": "the last result event carries no numeric total_cost_usd"}
    if not isinstance(last.get("session_id"), str) or not last["session_id"]:
        return {"result": None, "unparsed": unparsed,
                "problem": "the last result event carries no session_id"}
    return {"result": last, "unparsed": unparsed, "problem": None}


def _word(result, key):
    """A result field as printed: JSON's spelling, or `absent` when the result
    does not carry it - never a default standing in for a value nobody sent."""
    if key not in result:
        return "absent"
    value = result[key]
    return value if isinstance(value, str) and value and " " not in value \
        else json.dumps(value)


def result_line(result, exit_code, stream):
    return "session=%s subtype=%s is_error=%s total_cost_usd=%s exit=%d stream=%s" % (
        result["session_id"], _word(result, "subtype"), _word(result, "is_error"),
        json.dumps(result["total_cost_usd"]), exit_code, stream)


def exit_for(result, exit_code):
    """E_BUDGET for a budget stop, whatever claude exited with; E_OK only for a
    result that says `is_error: false` from a claude that exited 0; else E_SESSION."""
    if result.get("subtype") == BUDGET_STOP:
        return E_BUDGET
    if exit_code == 0 and result.get("is_error") is False:
        return E_OK
    return E_SESSION


def could_not_run_line(problem, stream, stderr_path, exit_code, unparsed):
    tail = (" (%d line(s) of it were not JSON)" % unparsed) if unparsed else ""
    return ("could-not-run: %s%s - stream %s, stderr %s, claude exit %s"
            % (problem, tail, stream, stderr_path, exit_code))


# --- running it ----------------------------------------------------------------
def _stream_path(state_dir, task, role):
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    base = "%s.%s.%s.%d" % (re.sub(r"[^A-Za-z0-9._-]", "_", task), role, stamp,
                            os.getpid())
    return os.path.join(os.path.abspath(state_dir), "sessions", base + ".jsonl")


def _is_parent_session_var(name):
    """True when `name` is session state a top-level session starts without: a
    listed name or anything under a dropped prefix, unless it is on the keep list."""
    if name in KEEP_SESSION_VARS or name.startswith(KEEP_SESSION_PREFIXES):
        return False
    return name in PARENT_SESSION_VARS or name.startswith(PARENT_SESSION_PREFIXES)


def _session_env(tmpdir):
    """The child's environment: the parent's, less its Claude session variables
    (`_is_parent_session_var`), with the session's own TMPDIR."""
    env = dict((k, v) for k, v in os.environ.items() if not _is_parent_session_var(k))
    for name in ("TMPDIR", "TEMP", "TMP"):
        env[name] = tmpdir
    return env


def run_session(claude, argv, prompt, tree, env, stream, stderr_path):
    """Run claude once with the prompt on stdin and its stdout saved to `stream`.
    Returns `(exit code, interrupted-by-or-None)`."""
    previous = _proc_group.arm_interrupt()
    proc = None
    try:
        with open(stream, "wb") as out, open(stderr_path, "wb") as err:
            proc = subprocess.Popen([claude] + argv, cwd=tree, env=env,
                                    stdin=subprocess.PIPE, stdout=out, stderr=err,
                                    **_proc_group.group_kwargs())
            proc.communicate(input=prompt.encode("utf-8"))
        return proc.returncode, None
    except KeyboardInterrupt as exc:
        if proc is not None:
            _proc_group.tear_down(proc)
        return (proc.returncode if proc is not None else None), str(exc) or "SIGINT"
    finally:
        _proc_group.disarm_interrupt(previous)


class PreparationError(Exception):
    """A file or directory the run needs could not be made or read; the message
    names the path. An exception of its own so `main` can tell it from a defect."""


def _io(what, path, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except OSError as exc:
        raise PreparationError("could not %s %s: %s" % (what, path, exc))


def _read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _write_json(path, value):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=1)


def _parent_tmp():
    """The temp directory this runner was handed (`tempfile.gettempdir()`, so a
    caller's TMPDIR is honoured), when it has no `.git` above it.

    The session's TMPDIR is made here and not under the scratch, because the drive
    keeps the scratch inside the project: a TMPDIR below it put every
    `tempfile.mkdtemp()` fixture a session's suites build inside the real checkout,
    where `_manifest_io.checkout_of` found the project's own `.git`. A temp
    directory that is itself inside a checkout is refused, naming it - falling back
    to another place would be a TMPDIR the caller did not choose. The path is
    resolved first, so a symlinked temp root is judged by where it lies."""
    parent = _io("find the temp directory", "(tempfile.gettempdir)", tempfile.gettempdir)
    inside = _manifest_io.checkout_of(os.path.join(os.path.realpath(parent), "x"))
    if inside is not None:
        raise PreparationError(
            "the temp directory %s lies inside the git checkout %s, so a session's "
            "TMPDIR made there would put every fixture its suites build inside a "
            "checkout; point TMPDIR at a directory with no .git above it"
            % (parent, inside))
    return parent


def _prepare(args, stream, loaded=()):
    """Make what the session needs before claude starts: the stream's directory,
    the scratch, the skills file when `loaded` holds skills, the reviewer's agents
    file and the session's TMPDIR. Returns `{"agents_file", "skills_file", "tmpdir",
    "problem"}`; raises PreparationError on I/O.

    The parent temp directory is judged first, so a refusal leaves nothing made."""
    parent_tmp = _parent_tmp()
    sessions = os.path.dirname(stream)
    _io("create the stream directory", sessions, os.makedirs, sessions, exist_ok=True)
    _io("create the scratch directory", args.scratch, os.makedirs, args.scratch,
        exist_ok=True)
    skills_file = None
    if loaded:
        skills_file = os.path.join(os.path.abspath(args.scratch),
                                   os.path.basename(stream)[:-len(".jsonl")]
                                   + ".skills.md")
        _io("write the skills file", skills_file, _write_text, skills_file,
            skills_prompt(loaded))
    agents_file = None
    if args.role == "reviewer":
        source = os.path.join(_output.PLUGIN_ROOT, "agents", REVIEWER + ".md")
        definition = agent_definition(_io("read the agent file", source, _read_text,
                                          source))
        if definition is None:
            return {"agents_file": None, "skills_file": None, "tmpdir": None,
                    "problem": "%s has no frontmatter to build --agents from" % source}
        agents_file = stream[:-len(".jsonl")] + ".agents.json"
        _io("write the agents file", agents_file, _write_json, agents_file, definition)
    tmpdir = _io("create the session TMPDIR under", parent_tmp, tempfile.mkdtemp,
                 prefix="session-%s-" % args.role, dir=parent_tmp)
    # Until this returns the caller holds no path to remove, so a failure (or a stop
    # signal) between the directory's making and the return removes it here.
    handed = False
    try:
        record = os.path.join(args.scratch, os.path.basename(tmpdir) + ".tmpdir")
        _io("write the TMPDIR record", record, _write_text, record, tmpdir + "\n")
        handed = True
        return {"agents_file": agents_file, "skills_file": skills_file, "tmpdir": tmpdir,
                "problem": None}
    finally:
        if not handed:
            _output.remove_tree(tmpdir)


def drop_session_tmp(tmpdir):
    """Remove the session's TMPDIR whole. None when it is gone or none was made;
    otherwise the sentence naming the directory that is still there."""
    if tmpdir is None or _output.remove_tree(tmpdir):
        return None
    return "the session TMPDIR %s could not be removed; it is left in place" % tmpdir


def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="run-agent-session.py", add_help=True, allow_abbrev=False,
        description="Run a writer or a reviewer as a headless Claude Code session "
                    "under a per-session budget, and print its cost from the "
                    "session's own result. The prompt is read from stdin or "
                    "--prompt-file, never from argv.")
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--task", required=True, help="the task id, naming the stream")
    parser.add_argument("--tree", required=True, help="the task's tree; the session's cwd")
    parser.add_argument("--scratch", required=True,
                        help="the task's scratch; it keeps the session's records, "
                             "including where its TMPDIR is (that lies under the "
                             "parent's temp directory, not under this)")
    parser.add_argument("--state-dir", dest="state_dir", required=True,
                        help="where the stream is saved, under sessions/")
    parser.add_argument("--model", required=True, help="a full model id, never an alias")
    parser.add_argument("--effort", choices=EFFORTS, required=True)
    parser.add_argument("--budget-usd", dest="budget", required=True,
                        help="the session's ceiling, passed as --max-budget-usd")
    parser.add_argument("--resume", default=None, help="a recorded session id to continue")
    parser.add_argument("--prompt-file", dest="prompt_file", default=None,
                        help="read the prompt from this file instead of stdin")
    parser.add_argument("--skill", dest="skills", action="append", default=None,
                        metavar="NAME",
                        help="a skill the session starts with, repeatable; found in the "
                             "tree's .claude/skills, the user's, then this plugin's "
                             "(plugin:skill only from that plugin), and a name found "
                             "nowhere refuses to start")
    parser.add_argument("--record", default=None,
                        help="also append the printed outcome and the exit code "
                             "to this file, one JSON line per run")
    return _claude_home.attach_usage_hint(parser)


def _usage(message):
    sys.stderr.write("ERROR: %s\n" % message)
    return E_USAGE


def _budget_ok(text):
    """A finite positive amount. `float()` reads `inf`, `Infinity` and `nan`, and
    an infinite ceiling is no ceiling."""
    try:
        value = float(text)
    except ValueError:
        return False
    return math.isfinite(value) and value > 0


def _read_prompt(args, stdin):
    if args.prompt_file:
        with open(args.prompt_file, encoding="utf-8") as fh:
            return fh.read()
    return stdin.buffer.read().decode("utf-8") if hasattr(stdin, "buffer") else stdin.read()


def write_record(path, line, code, skills=None):
    """Append `{"line", "exit"}` to `path` as one JSON line, making its
    directory, with a `"skills"` key beside them when the session was started with
    skills (`skills_record`) and no such key when it was not. None, or why it could
    not be written. Appended, so the same command run twice keeps both outcomes; the
    one reader takes a last line that does not parse as one not written yet."""
    body = {"line": line, "exit": code}
    if skills:
        body["skills"] = skills
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(body, ensure_ascii=False) + "\n")
    except OSError as exc:
        return "the record %s could not be written: %s" % (path, exc)
    return None


def main(argv, stdin=None, out=print):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK
    said = []

    def tell(line):
        said.append(line)
        out(line)

    def refuse(message):
        said.append("usage: %s" % message)
        return _usage(message)
    ran = {}
    code = _run(args, stdin, tell, refuse, ran)
    if args.record:
        problem = write_record(args.record, said[-1] if said else "", code,
                               ran.get("skills"))
        if problem:
            sys.stderr.write("ERROR: %s\n" % problem)
    return code


def _run(args, stdin, out, refuse, ran):
    """The run itself, once the arguments parsed: every outcome is one `out`
    line, or one `refuse` - a usage refusal, which goes to stderr. `ran` is the
    caller's dict for what the run learned that its printed line does not carry:
    `ran["skills"]` is `skills_record` of the skills the session was started with,
    set as soon as they are read so every later outcome is recorded with them."""
    if not is_full_model_id(args.model):
        return refuse("--model %r is not a full model id (claude-<family>-<version>); "
                      "an alias resolves to whatever is newest on the day" % args.model)
    if not _budget_ok(args.budget):
        return refuse("--budget-usd %r is not a finite positive amount" % args.budget)
    if not os.path.isdir(args.tree):
        return refuse("--tree %s is not a directory" % args.tree)
    if args.resume is not None and not SESSION_ID.match(args.resume):
        return refuse("--resume %r is not a recorded session id (a UUID, as the "
                      "stream's session_id is)" % args.resume)
    try:
        prompt = _read_prompt(args, stdin if stdin is not None else sys.stdin)
    except (OSError, UnicodeDecodeError) as exc:
        return refuse("the prompt could not be read: %s" % exc)
    if not prompt.strip():
        return refuse("the prompt is empty - it is read from stdin or --prompt-file")
    searched = find_skills(args.skills or [], args.tree,
                           _claude_home.claude_home(), _output.PLUGIN_ROOT,
                           _skill_places.plugin_name(_output.PLUGIN_ROOT))
    if searched["problem"]:
        return refuse(searched["problem"])
    try:
        loaded = load_skills(searched["found"])
    except PreparationError as exc:
        out("io-error: %s" % exc)
        return E_IO
    ran["skills"] = skills_record(loaded)

    claude = shutil.which("claude")
    stream = _stream_path(args.state_dir, args.task, args.role)
    stderr_path = stream[:-len(".jsonl")] + ".stderr"
    if claude is None:
        out(could_not_run_line("no `claude` on PATH", stream, stderr_path, None, 0))
        return E_COULD_NOT_RUN
    # Armed from before the TMPDIR is made until the outcome is printed, so a stop
    # outside the child's own run (which `run_session` answers itself) still
    # reaches the `finally` instead of ending the interpreter there. Disarmed
    # before the removal: a second stop during it acts as it would on a script
    # with no handler, rather than raising out of the `finally`.
    previous = _proc_group.arm_interrupt()
    prepared = {}
    try:
        prepared = _prepare(args, stream, loaded)
        return _in_session(args, prompt, claude, stream, stderr_path, prepared, out)
    except PreparationError as exc:
        out("io-error: %s" % exc)
        return E_IO
    except KeyboardInterrupt as exc:
        out(could_not_run_line("interrupted by %s outside the session's own run"
                               % (str(exc) or "SIGINT"), stream, stderr_path, None, 0))
        return E_COULD_NOT_RUN
    finally:
        _proc_group.disarm_interrupt(previous)
        problem = drop_session_tmp(prepared.get("tmpdir"))
        if problem:
            sys.stderr.write("ERROR: %s\n" % problem)


def _in_session(args, prompt, claude, stream, stderr_path, prepared, out):
    """The session itself, once `_prepare` made what it needs: start claude, read
    its stream, print the one line. The caller removes the TMPDIR."""
    if prepared.get("problem"):
        out(could_not_run_line(prepared["problem"], stream, stderr_path, None, 0))
        return E_COULD_NOT_RUN
    session = session_argv(args.model, args.effort, args.budget, _output.PLUGIN_ROOT,
                           agents_file=prepared["agents_file"], resume=args.resume,
                           skills_file=prepared["skills_file"])
    try:
        code, interrupted = run_session(claude, session, prompt, args.tree,
                                        _session_env(prepared["tmpdir"]), stream,
                                        stderr_path)
    except OSError as exc:
        out("io-error: could not start the session writing %s: %s" % (stream, exc))
        return E_IO
    if interrupted:
        out(could_not_run_line("interrupted by %s; the session group was torn down"
                               % interrupted, stream, stderr_path, code, 0))
        return E_COULD_NOT_RUN
    reading = read_stream(stream)
    if reading["problem"]:
        out(could_not_run_line(reading["problem"], stream, stderr_path, code,
                               reading["unparsed"]))
        return E_COULD_NOT_RUN
    out(result_line(reading["result"], code, stream))
    return exit_for(reading["result"], code)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    sys.exit(main(sys.argv[1:]))
