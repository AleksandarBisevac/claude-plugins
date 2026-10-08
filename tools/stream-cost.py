#!/usr/bin/env python3
"""Attribute a recorded Claude Code session's tokens, price and time to pipeline
stages, and to the content that filled its context.

WHY THIS EXISTS. A pipeline run's cost had been published per stage, and the figures
could say WHERE money went but not WHY: a stage that re-reads a large prefix on every
request and a stage that writes a large file once look alike in a total. Prompt
caching makes the difference decisive. Every request re-reads its whole context at
the cache-read rate, so content that enters early is paid for once as a cache write
and again on every later request of the same context. Attributing a session therefore
needs two views, and this prints both:

  * BY STAGE, AS BILLED - every token of a request in the stage of that request,
    which is what each step of the pipeline was charged;
  * BY CONTENT - what put the tokens there: each cache write, its source (a file read,
    a command's output, an agent's hand-back, an injected command body, the session's
    own start), what writing
    it cost and what carrying it through every later request cost, totalled by the
    stage the content came from and by class - fixed per run, per task, per file.
    The bytes an Edit or a Write emits take the class of the path it writes, by the
    rule its tool result is classed by: an edit of the plan is task work, not a file
    the work touches, though both are typed as a file write.

The two views disagree on purpose. Prose the main loop reads in its first requests is
billed to the NEXT request, the one whose context it entered, and from then on to every
request that re-reads it; the content view hands all of that back to the reading.

THE IDENTITY THE CONTENT VIEW RESTS ON, CHECKED RATHER THAN ASSUMED. Within one context
(the main loop, or one subagent dispatch) request k reads from cache exactly what the
first request read plus everything written since:

    cacheRead[k] = cacheRead[1] + sum(cacheWrite[i] for i < k)

So a cache write at request j is read again by every later request of its context, and
its carrying cost is a COUNT of reads, not an estimate. Where a recorded stream breaks
the identity - a cache that expired, a prefix that changed - the difference is printed
as reads the identity does not explain, never folded into a neighbour.

STAGES. A main-loop request is placed by where the main loop is:

  orient    before its first tool call that does anything but read the plugin's own
            files outside its `scripts/` (reading the command's prose, sizing it)
  plan      from there up to and including the request that dispatches an executor:
            preflight, the manifest, the lock, the task start, the brief
  gate      after an executor's hand-back, up to and including the reviewer dispatch
  close     after a reviewer's hand-back (commit, done, lock release, final message)
  main      every main-loop request after orient, in a session that dispatches no
            executor - a plain session reads as one stage, which is what it is

A subagent request belongs to its dispatch: `executor`, `reviewer`, or `agent:<type>`.
A plugin root is read off the stream's `init` event; a session with none has no orient
stage. On a run of several tasks, the plan work for the next task, before its dispatch
request, is counted in the previous task's close - the recordings this was built on are
single-task runs, where that case does not arise.

WHAT THE STREAM DOES NOT CARRY, AND WHAT IS DONE ABOUT IT.

  * A subagent's last request - the one that writes its hand-back - is absent from the
    stream. It is rebuilt from the result events: per model, `modelUsage` minus every
    request the stream shows. With one dispatch on a model that residual IS the missing
    request; the prefix identity predicts its cache read independently, and the two are
    printed side by side. With several dispatches on one model each cache read comes
    from the identity and the residual cache write is split by the bytes that entered
    after each dispatch's last visible request - an estimate, and labelled as one.
    A dispatch whose tool result is the background-launch notice is the exception: its
    report is its own last request, which the stream shows, so nothing is rebuilt for
    it. Rebuilding one there counts that request twice and leaves a negative residual.
  * A command body a `Skill` call injects arrives as a user text block, not a tool
    result. Each such block is sized and is a source of its own, `command body:
    <skill>`, fixed per run in the main loop as a Read of the same file would be;
    any other user text block of the main loop is `user text`.
  * Output counts in the stream are emit-time and undercount. The measured ones are the
    main loop's (each stretch's `usage`, which the stream's own input-side sums are
    checked against) and each model's (`modelUsage`). Within such a pool, output is
    apportioned to requests by the bytes each emitted - an estimate, labelled.
  * A cache write that held content from more than one source is split across them by
    bytes - an estimate; how many writes needed it is printed.

A RE-INVOKED SESSION RUNS IN STRETCHES. When a background task's notification wakes a
headless session, the session runs again under the same id: each stretch opens with an
`init` event of its own and closes with a result event of its own, and the recorded
streams hold every result at their end, so a stretch is told by its `init` and never by
where its result sits. The result events do not all carry the same kind of figure:

  * `usage` is the stretch's own main loop. The results' `usage` blocks are summed, the
    main loop is checked stretch by stretch against its own result, and each stretch's
    output is a measured pool of its own;
  * `modelUsage` and `total_cost_usd` are the whole session's, repeated in every result,
    so they are read once, from the last. Summed, every subagent would be counted once
    per stretch. Results that disagree on them are reported, never reconciled.

A stream whose `init` events do not pair one to one with its results is checked on the
summed `usage` alone, and the reconstruction says so.

SPANS read a session by what its main loop did rather than by stage, from the verbs it
called through the plugin's task script and their operands - never from the text around
them, so `done --help` closes nothing and a script path held in a shell variable or a
`for` loop over task ids is followed (`script_calls`):

  planning  from the first request before the cycle that plans - a `Skill` call to
            `audit:phase` or `audit:task` whose args begin with `add`, or the `add` or
            `add-phase` verb - to the last one before the cycle that calls one of those
            verbs, or the request that opened it when none does
  cycle     from the first request that starts a task to the last that closes one
            before any request inside it plans; the tasks it holds are the operands of
            its `done` calls. A request that runs the step driver (`drive-phase.py`)
            starts and closes the tasks its printed result says it started and
            closed, because the driver calls `start` and `done` in subprocesses the
            stream does not show. A session with no start has no cycle, and one with
            no close after its start has a cycle that never closed: each says so
  after it  a fix task from each planning verb to the next close; the close from the
            lock release or the request after the landing, whichever comes first; and
            sign-off, the rest

An agent's requests are in the span of the main-loop request that dispatched it. The
cycle is then priced by class with its agents, its content counted for the request that
added it; the main loop's context is split by origin; and each dispatch's start, read
and written, is printed with how it was launched.

PRICES come from the plugin's own shipped table (`_usage_core.DEFAULT_PRICING`), with
the five-minute and one-hour write rates applied to the split the stream records. The
priced total is compared, per model, with the session's own `costUSD` and the
disagreement printed rather than reconciled.

No path from the stream is printed as recorded: the plugin root reads `<plugin>`, the
session's working directory `<repo>`, and any other home or temp path `<abs>`.

Usage:  python3 tools/stream-cost.py <stream.jsonl> [--top N] [--json]
        python3 tools/stream-cost.py --selftest
Exit codes: 0 report printed - 1 selftest failed - 2 unreadable input or usage error.
"""
import argparse
import json
import os
import re
import shlex
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(REPO, "plugins", "audit", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import _output  # noqa: E402  (the anchor: install_path, safe_stdio)

_output.install_path()

import _usage_core  # noqa: E402  (the shipped price table and its resolver)
import _loader  # noqa: E402  (load_script: the step driver's own did-line reader)

# The step driver starts and closes a task in its own subprocesses, which the stream
# never shows; what it shows is the driver's print, and the driver's own reader of
# that print is the one place the words it uses are kept.
_DRIVE = _loader.load_script("drive-phase.py", "stream_cost_drive_phase")

MAIN = "main"
STAGE_ORDER = ("orient", "plan", "main", "executor", "gate", "reviewer", "close")
CLASSES = ("run", "task", "file")
CLASS_MEANING = {
    "run": "fixed per run: the main loop's start and the plugin prose read into it",
    "task": "per task: agent starts, briefs, hand-backs, plan and gate output, "
            "the model's own text and calls",
    "file": "per file the work touches: project files read, and code written",
}
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
READ_TOOLS = ("Read", "Glob", "Grep", "NotebookRead")
AGENT_TOOLS = ("Agent", "Task")
# A shell segment whose command word is one of these only LOOKS at files. A command
# all of whose segments look is a file read; anything else a command does (a test run,
# a plugin script, git plumbing) is task work.
VIEW_WORDS = frozenset(("cat", "head", "tail", "sed", "nl", "less", "more", "ls",
                        "grep", "rg", "find", "tree", "wc", "diff", "awk", "file"))
VIEW_GIT = frozenset(("diff", "show"))
PLAN_STATE_NAMES = ("audit-plan.json", "audit.config.json")
# The label of the bytes a write tool emitted, by the class of the path it wrote.
# "file" keeps the label earlier readings printed for code, so a reading of one
# session taken before this split and after it compares row for row.
WRITE_LABEL = {"file": "output: code written",
               "task": "output: plan state or plugin files written",
               "run": "output: plugin files written"}
_ABS_RE = re.compile(r"(?<![\w.<>$])/(?:Users|home|private|tmp|var|opt|mnt|Volumes)"
                     r"/[^\s'\"`;|&)]*")
_WIN_ABS_RE = re.compile(r"[A-Za-z]:\\(?:Users|Temp)\\[^\s'\"`;|&)]*")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")


# --- reading the stream --------------------------------------------------------
def load_events(path):
    """Every JSON line of `path`. A line that is not JSON is an error that names it:
    a stream with a torn line is a stream whose totals cannot be trusted."""
    events = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except ValueError as exc:
                raise ValueError("%s line %d is not JSON (%s)"
                                 % (os.path.basename(path), lineno, exc))
    return events


def _ts(stamp):
    """Seconds since the epoch for an ISO stamp, or None for a missing one."""
    if not isinstance(stamp, str) or len(stamp) < 19:
        return None
    body = stamp.rstrip("Z")
    for shape in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            moment = datetime.strptime(body[:26], shape)
        except ValueError:
            continue
        return (moment - datetime(1970, 1, 1)).total_seconds()
    return None


def _blocks(event):
    content = (event.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def _text_bytes(value):
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, list):
        return sum(len((part.get("text") or "").encode("utf-8"))
                   for part in value if isinstance(part, dict))
    return 0


def _text_of(value):
    """A content value's text: a string as it is, a list's text parts joined."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(part.get("text") or "") for part in value
                         if isinstance(part, dict))
    return ""


def _emitted_bytes(block):
    """Bytes a content block puts on the wire as model output."""
    kind = block.get("type")
    if kind == "text":
        return _text_bytes(block.get("text"))
    if kind == "thinking":
        return _text_bytes(block.get("thinking"))
    if kind == "tool_use":
        return len(json.dumps(block.get("input") or {}, sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return 0


def _usage_counts(usage):
    """The input side of one usage block, with the write split by TTL.

    `ttlKnown` is False when the block carries no split: the write is then priced at
    the five-minute rate, the lower of the two, and the report says how many writes
    that touched.
    """
    usage = usage if isinstance(usage, dict) else {}
    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else None
    write = int(usage.get("cache_creation_input_tokens") or 0)
    if split is not None:
        w5 = int(split.get("ephemeral_5m_input_tokens") or 0)
        w1 = int(split.get("ephemeral_1h_input_tokens") or 0)
    else:
        w5, w1 = write, 0
    return {"in": int(usage.get("input_tokens") or 0), "cw5": w5, "cw1": w1,
            "cr": int(usage.get("cache_read_input_tokens") or 0),
            "outEmit": int(usage.get("output_tokens") or 0),
            "ttlKnown": split is not None or write == 0}


def parse(events):
    """The session as this tool reads it: requests (deduplicated by message id, each
    with the stretch it ran in), the agent dispatches, every tool result's size, a
    timeline, every result event (`ends`) and the session's reading of them
    (`result`, from `session_result`).

    An assistant event without a message id cannot be joined to a request; it is
    counted in `unjoined` rather than dropped silently.
    """
    init = next((e for e in events if e.get("type") == "system"
                 and e.get("subtype") == "init"), {})
    roots = sorted(set(p.get("path") for p in init.get("plugins") or []
                       if isinstance(p, dict) and isinstance(p.get("path"), str)
                       and os.path.isabs(p.get("path"))))
    requests, order, agents, results, calls = {}, [], {}, {}, {}
    # Bash calls that run the step driver: their results' text is kept, because
    # the tasks the driver started and closed are named there and nowhere else.
    driven = set()
    timeline, seen, unjoined, ends, inits = [], set(), 0, [], 0
    last_main, before_any = None, 0
    for event in events:
        uid = event.get("uuid")
        if uid is not None:
            if uid in seen:
                continue
            seen.add(uid)
        kind = event.get("type")
        stamp = _ts(event.get("timestamp"))
        if kind == "system" and event.get("subtype") == "init":
            inits += 1
        elif kind == "result":
            ends.append(event)
        elif kind == "assistant":
            message = event.get("message") or {}
            mid = message.get("id")
            if not mid:
                unjoined += 1
                continue
            req = requests.get(mid)
            if req is None:
                req = {"id": mid, "context": event.get("parent_tool_use_id") or MAIN,
                       "model": message.get("model") or "?", "tools": [],
                       "emitWrite": {}, "emitOther": 0, "reconstructed": False,
                       "stretch": max(inits - 1, 0), "at": stamp, "injected": []}
                req.update(_usage_counts(message.get("usage")))
                requests[mid] = req
                order.append(mid)
            else:
                again = _usage_counts(message.get("usage"))
                for key in ("in", "cw5", "cw1", "cr", "outEmit"):
                    req[key] = max(req[key], again[key])
                req["ttlKnown"] = req["ttlKnown"] and again["ttlKnown"]
            for block in _blocks(event):
                size = _emitted_bytes(block)
                if block.get("type") == "tool_use":
                    tool = {"id": block.get("id"), "name": block.get("name") or "?",
                            "input": block.get("input") or {}}
                    req["tools"].append(tool)
                    calls[tool["id"]] = mid
                    if tool["name"] == "Bash" and any(
                            script == DRIVER_SCRIPT for script, _v, _o in
                            script_calls(str(tool["input"].get("command") or ""))):
                        driven.add(tool["id"])
                    if tool["name"] in AGENT_TOOLS:
                        agents[tool["id"]] = {
                            "type": tool["input"].get("subagent_type") or "?",
                            "request": mid, "context": req["context"],
                            "briefBytes": _text_bytes(tool["input"].get("prompt"))}
                    if tool["name"] in WRITE_TOOLS:
                        kind = classify(tool, req["context"] == MAIN, roots)
                        req["emitWrite"][kind] = req["emitWrite"].get(kind, 0) + size
                        continue
                req["emitOther"] += size
            if req["context"] == MAIN:
                last_main = mid
            timeline.append((stamp, "request", mid))
        elif kind == "user":
            parent = event.get("parent_tool_use_id")
            got = False
            for block in _blocks(event):
                if block.get("type") == "tool_result":
                    got = True
                    tid = block.get("tool_use_id")
                    results[tid] = {"bytes": _text_bytes(block.get("content")),
                                    "error": bool(block.get("is_error")),
                                    "launched": _launch_notice(block.get("content"))}
                    if tid in driven:
                        results[tid]["text"] = _text_of(block.get("content"))
                    timeline.append((stamp, "result", tid))
                elif block.get("type") == "text" and not parent:
                    if last_main is None:
                        before_any += 1
                        continue
                    host = requests[last_main]
                    host["injected"].append({"label": _injected_label(host),
                                             "bytes": _text_bytes(block.get("text"))})
            if parent and not got:
                timeline.append((stamp, "brief", parent))
    return {"roots": roots, "cwd": init.get("cwd") or "", "init": init,
            "requests": [requests[m] for m in order], "agents": agents,
            "results": results, "calls": calls, "timeline": timeline,
            "result": session_result(ends), "ends": ends, "inits": inits,
            "unjoined": unjoined, "textBeforeAny": before_any}


# The tool result an `Agent` call gets back when the agent was launched in the
# background, whatever its `run_in_background` said: the recorded sessions launched
# two that way with the key absent. Such an agent's report is its own last request,
# which the stream shows.
LAUNCH_NOTICE = "Async agent launched successfully."


def _launch_notice(content):
    text = content if isinstance(content, str) else "".join(
        (part.get("text") or "") for part in content or [] if isinstance(part, dict))
    return text.lstrip().startswith(LAUNCH_NOTICE)


def _injected_label(req):
    """The source name of a user text block the main loop received after `req`: a
    `Skill` call's command body is named by its skill, anything else is user text."""
    skills = [str((t.get("input") or {}).get("skill") or "?") for t in req["tools"]
              if t["name"] == "Skill"]
    return "command body: %s" % skills[-1] if skills else "user text"


# A result's `usage` holds its own stretch's main loop, so these are summed across
# results. The tool reads no other key of a result's usage, so no other is summed.
_STRETCH_USAGE = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                  "output_tokens")
# Per stretch as well: they differ from result to result, smallest in the stretch with
# the fewest requests.
_STRETCH_COUNTS = ("duration_ms", "num_turns")
# The whole session's, repeated in every result: read once, from the last.
_SESSION_TOTALS = ("modelUsage", "total_cost_usd")


def session_result(ends):
    """The session as its result events report it, or None when it has none.

    One result stands as it is. Several are one per stretch: `usage` and the
    per-stretch counts are summed, and every other field - the session's totals
    among them - is the last result's."""
    if not ends:
        return None
    if len(ends) == 1:
        return ends[0]
    merged = dict(ends[-1])
    merged["usage"] = dict((key, sum(int((e.get("usage") or {}).get(key) or 0) for e in ends))
                           for key in _STRETCH_USAGE)
    for key in _STRETCH_COUNTS:
        values = [e.get(key) for e in ends]
        merged[key] = None if None in values else sum(values)
    return merged


def _same_totals(ends):
    """True when every result carries the last one's session totals."""
    def shape(event, key):
        return json.dumps(event.get(key), sort_keys=True)
    return all(shape(e, key) == shape(ends[-1], key) for e in ends for key in _SESSION_TOTALS)


def main_stretches(session):
    """([(number, usage, requests)], why): the main loop's requests grouped by the
    result whose `usage` must account for them. `number` counts stretches from one,
    and is None for the single group a session gets when it has one result, or when
    its `init` events do not pair one to one with its results; `why` names that
    second case and is None otherwise."""
    main = [r for r in session["requests"] if r["context"] == MAIN]
    ends = session["ends"]
    whole = [(None, (session["result"] or {}).get("usage") or {}, main)]
    if len(ends) < 2:
        return whole, None
    if session["inits"] != len(ends):
        return whole, ("main loop: result events %d, init events %d - no request can be "
                       "placed in its stretch, so it is checked against the summed usage "
                       "alone" % (len(ends), session["inits"]))
    return [(k + 1, end.get("usage") or {}, [r for r in main if r["stretch"] == k])
            for k, end in enumerate(ends)], None


# --- stages --------------------------------------------------------------------
def agent_stage(subagent_type):
    kind = subagent_type or "?"
    if kind.endswith("executor"):
        return "executor"
    if kind.endswith("reviewer"):
        return "reviewer"
    return "agent:%s" % kind


def _under(path, roots):
    return bool(path) and any(path == r or path.startswith(r.rstrip("/\\") + "/")
                              for r in roots)


def _reads_plugin_only(tool, roots):
    """True for a call that reads the plugin's own files and touches nothing else.

    A shell command counts when it names a plugin root and no `/scripts/` path at all:
    a command that reaches the plugin's scripts, to run one or to read one, is plan
    work, whatever else it does."""
    if not roots:
        return False
    data = tool.get("input") or {}
    if tool["name"] in READ_TOOLS:
        return _under(data.get("file_path") or data.get("path") or "", roots)
    if tool["name"] == "Bash":
        command = data.get("command") or ""
        return any(r in command for r in roots) and "/scripts/" not in command
    return False


def assign_stages(session):
    """{request id: stage}. See the module docstring for the rule."""
    agents = session["agents"]
    roots = session["roots"]
    has_executor = any(a["context"] == MAIN and agent_stage(a["type"]) == "executor"
                       for a in agents.values())
    after_orient = "plan" if has_executor else "main"
    state = "orient" if roots else after_orient
    stages = {}
    for req in session["requests"]:
        if req["context"] != MAIN:
            dispatch = agents.get(req["context"])
            stages[req["id"]] = agent_stage(dispatch["type"]) if dispatch else "agent:?"
            continue
        if state == "orient" and any(not _reads_plugin_only(t, roots) for t in req["tools"]):
            state = after_orient
        sent = [agent_stage(agents[t["id"]]["type"]) for t in req["tools"] if t["id"] in agents]
        if "executor" in sent:
            stages[req["id"]] = "plan"
            state = "gate"
        elif "reviewer" in sent:
            stages[req["id"]] = state
            state = "close"
        else:
            stages[req["id"]] = state
    return stages


# --- what the stream leaves out --------------------------------------------------
def _sum(reqs, key):
    return sum(r[key] for r in reqs)


def _input_side(reqs):
    return {"in": _sum(reqs, "in"), "cw": _sum(reqs, "cw5") + _sum(reqs, "cw1"),
            "cr": _sum(reqs, "cr")}


def _emitted(req):
    """Every byte a request put on the wire as output, whatever class it went to."""
    return sum(req["emitWrite"].values()) + req["emitOther"]


def _tail_bytes(req, results):
    """Bytes that entered a context after `req`: its own output and its tools' results."""
    return (_emitted(req)
            + sum((results.get(t["id"]) or {}).get("bytes", 0) for t in req["tools"])
            + sum(i["bytes"] for i in req.get("injected") or []))


def _pseudo(rid, context, model, counts, why):
    req = {"id": rid, "context": context, "model": model, "tools": [], "emitWrite": {},
           "emitOther": 0, "reconstructed": True, "outEmit": 0, "ttlKnown": True,
           "why": why}
    req.update(counts)
    return req


def reconstruct(session):
    """(extra requests, notes): each dispatch's missing final request, and any
    residual the stream cannot place, as requests of their own so every token the
    result event reports is attributed somewhere visible."""
    result = session["result"]
    if result is None:
        return [], ["no result event: missing final requests cannot be rebuilt and output "
                    "is not measured, so output is not priced"]
    reqs = session["requests"]
    notes, extra = [], []
    ends = session["ends"]
    if len(ends) > 1:
        notes.append(("%d result events, one per stretch: their usage is summed, and "
                      "modelUsage and total_cost_usd, the same in every one, are read once"
                      if _same_totals(ends) else
                      "%d result events DISAGREE on modelUsage or total_cost_usd: both are "
                      "read from the last, which is the session's whole only if the CLI "
                      "reports them cumulatively") % len(ends))
    groups, why = main_stretches(session)
    if why:
        notes.append(why)
    fallback = next((r["model"] for r in reversed(reqs) if r["context"] == MAIN), "?")
    for number, told_usage, members in groups:
        note, gap = _main_gap(number, len(groups), told_usage, members, fallback)
        notes.append(note)
        if gap is not None:
            extra.append(gap)
    usage = result.get("modelUsage") or {}
    by_model = {}
    for aid, dispatch in sorted(session["agents"].items()):
        mine = [r for r in reqs if r["context"] == aid]
        if (session["results"].get(aid) or {}).get("launched"):
            notes.append("dispatch %s (%s) was launched in the background: its tool result "
                         "is the launch notice and its last visible request is its final, "
                         "so nothing is rebuilt for it" % (aid[-6:], dispatch["type"]))
            continue
        if aid not in session["results"]:
            notes.append("dispatch %s (%s) has no hand-back: nothing rebuilt for it"
                         % (aid[-6:], dispatch["type"]))
            continue
        if not mine:
            notes.append("dispatch %s (%s) shows no request: its tokens stay in the "
                         "model residual" % (aid[-6:], dispatch["type"]))
            continue
        by_model.setdefault(mine[-1]["model"], []).append((aid, mine))
    models = sorted(set(list(usage) + list(by_model) + [r["model"] for r in reqs]))
    for model in models:
        row = usage.get(model)
        if row is None:
            if any(_input_side([r for r in reqs if r["model"] == model]).values()):
                notes.append("%s: no modelUsage row, so nothing is rebuilt for it" % model)
            continue
        seen = _input_side([r for r in reqs + extra if r["model"] == model])
        resid = {"in": int(row.get("inputTokens") or 0) - seen["in"],
                 "cw": int(row.get("cacheCreationInputTokens") or 0) - seen["cw"],
                 "cr": int(row.get("cacheReadInputTokens") or 0) - seen["cr"]}
        if any(v < 0 for v in resid.values()):
            notes.append("%s: the stream holds MORE than modelUsage (%r); nothing rebuilt"
                         % (model, resid))
            continue
        members = by_model.get(model, [])
        built = _rebuild_finals(model, members, resid, session["results"], notes)
        extra.extend(built)
        left = dict((k, resid[k] - sum(b[k] for b in built)) for k in ("in", "cr"))
        left["cw"] = resid["cw"] - sum(b["cw5"] + b["cw1"] for b in built)
        if any(left.values()):
            notes.append("%s: in=%d cacheW=%d cacheR=%d in modelUsage belong to no "
                         "request the stream shows; kept as an unattributed request"
                         % (model, left["in"], left["cw"], left["cr"]))
            extra.append(_pseudo("residual:%s" % model, "residual:%s" % model, model,
                                 {"in": left["in"], "cw5": left["cw"], "cw1": 0,
                                  "cr": left["cr"]}, "model residual"))
    return extra, notes


def _main_gap(number, count, told_usage, members, fallback):
    """(note, residual request or None): one group of main-loop requests against the
    usage that must account for them. A gap is a request of its own, so every token
    the result reports stays attributed somewhere visible."""
    where = "main loop" if number is None else "main loop, stretch %d of %d" % (number, count)
    seen = _input_side(members)
    told = {"in": int(told_usage.get("input_tokens") or 0),
            "cw": int(told_usage.get("cache_creation_input_tokens") or 0),
            "cr": int(told_usage.get("cache_read_input_tokens") or 0)}
    gap = dict((k, told[k] - seen[k]) for k in told)
    if not any(gap.values()):
        return ("%s: result.usage agrees with the stream's own requests (in, cacheW, cacheR)"
                % where), None
    note = ("%s: result.usage and the stream's own requests DISAGREE by in=%d cacheW=%d "
            "cacheR=%d; the gap is a request of its own, stage unattributed"
            % (where, gap["in"], gap["cw"], gap["cr"]))
    rid = "residual:main" if number is None else "residual:main:%d" % number
    model = members[-1]["model"] if members else fallback
    return note, _pseudo(rid, MAIN, model, {"in": gap["in"], "cw5": 0, "cw1": gap["cw"],
                                            "cr": gap["cr"]}, "main-loop gap")


def _rebuild_finals(model, members, resid, results, notes):
    if not members:
        return []
    out = []
    tails = [max(_tail_bytes(mine[-1], results), 0) for _aid, mine in members]
    whole = float(sum(tails)) or float(len(tails))
    budget_cw, budget_in = resid["cw"], resid["in"]
    for index, (aid, mine) in enumerate(members):
        last = mine[-1]
        predicted = last["cr"] + last["cw5"] + last["cw1"]
        one_hour = _sum(mine, "cw1") > _sum(mine, "cw5")
        if len(members) == 1:
            cr, cw, inn = resid["cr"], resid["cw"], resid["in"]
            verdict = ("agrees" if cr == predicted
                       else "DIFFERS by %d" % (cr - predicted))
            basis = ("the whole %s residual; the prefix identity predicts cacheR=%d (%s)"
                     % (model, predicted, verdict))
        else:
            share = (tails[index] if sum(tails) else 1) / whole
            cr = predicted
            last_one = index == len(members) - 1
            cw = budget_cw if last_one else int(round(resid["cw"] * share))
            inn = budget_in if last_one else resid["in"] // len(members)
            budget_cw -= cw
            budget_in -= inn
            basis = ("cacheR from the prefix identity; the %s residual write split "
                     "by bytes entering after the last visible request [estimate]" % model)
        req = _pseudo("final:%s" % aid, aid, model,
                      {"in": inn, "cw5": 0 if one_hour else cw, "cw1": cw if one_hour else 0,
                       "cr": cr}, "final request")
        req["emitOther"] = (results.get(aid) or {}).get("bytes", 0)
        req["after"] = last["id"]
        out.append(req)
        notes.append("dispatch %s: final request rebuilt in=%d cacheW=%d (%s) cacheR=%d - %s"
                      % (aid[-6:], inn, cw, "1h" if one_hour else "5m", cr, basis))
    return out


def apportion_output(session, reqs):
    """{request id: output tokens}, or None when no result event measured any.

    Pools are measured - the main loop's one per stretch - and the split inside a pool
    is by emitted bytes [estimate]."""
    result = session["result"]
    if result is None:
        return None, ["output not measured: no result event"]
    main = [r for r in reqs if r["context"] == MAIN and not r["id"].startswith("residual:")]
    main_out = int((result.get("usage") or {}).get("output_tokens") or 0)
    groups, _why = main_stretches(session)
    notes = ["output pool, measured: main loop %d tokens (result.usage%s)"
             % (main_out, "" if len(groups) == 1 else
                ", over %d stretches, each split within its own" % len(groups))]
    out = {}
    for number, told_usage, members in groups:
        pool = int(told_usage.get("output_tokens") or 0)
        if pool and not members:
            notes.append("main loop%s: %d output tokens belong to no request the stream "
                         "shows" % ("" if number is None else ", stretch %d" % number, pool))
        out.update(_split(members, pool))
    usage = result.get("modelUsage") or {}
    for model in sorted(usage):
        pool = int(usage[model].get("outputTokens") or 0)
        pool -= sum(out[r["id"]] for r in main if r["model"] == model)
        members = [r for r in reqs if r["context"] != MAIN and r["model"] == model]
        if pool < 0:
            notes.append("%s: the main loop's output exceeds the model's; subagent output "
                         "on it is not apportioned" % model)
            pool = 0
        if pool and not members:
            notes.append("%s: %d output tokens belong to no request the stream shows"
                         % (model, pool))
        elif members:
            notes.append("output pool, measured: %s subagents %d tokens (modelUsage less "
                         "the main loop's)" % (model, pool))
        out.update(_split(members, pool))
    return out, notes


def _split(members, pool):
    weights = [_emitted(r) for r in members]
    whole = float(sum(weights))
    if not members:
        return {}
    if not whole:
        return dict((r["id"], pool / float(len(members))) for r in members)
    return dict((r["id"], pool * w / whole) for r, w in zip(members, weights))


# --- pricing ---------------------------------------------------------------------
def _rate(model, key):
    """USD per token for one of the shipped table's keys."""
    return _usage_core.price({key: 1000000}, model) / 1000000.0


def request_cost(req, out_tokens):
    """{in, cw, cr, out, total} in USD; `out` is None when output is unmeasured."""
    cost = {"in": req["in"] * _rate(req["model"], "in"),
            "cw": (req["cw5"] * _rate(req["model"], "cacheW5m")
                   + req["cw1"] * _rate(req["model"], "cacheW1h")),
            "cr": req["cr"] * _rate(req["model"], "cacheR"),
            "out": None if out_tokens is None else out_tokens * _rate(req["model"], "out")}
    cost["total"] = cost["in"] + cost["cw"] + cost["cr"] + (cost["out"] or 0.0)
    return cost


# --- content: what put the tokens there ------------------------------------------
def _segments(command):
    """A shell command split on ; && || | and newline outside quotes."""
    out, cur, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            cur.append(ch)
            quote = None if ch == quote else quote
            i += 1
            continue
        if ch == "\\" and command[i + 1:i + 2] == "\n":
            cur.append(" ")
            i += 2
            continue
        if ch in "'\"":
            quote = ch
        if command[i:i + 2] in ("&&", "||"):
            out.append("".join(cur))
            cur, i = [], i + 2
            continue
        if ch in ";|\n":
            out.append("".join(cur))
            cur, i = [], i + 1
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def _only_views(command):
    words_seen = False
    for segment in _segments(command):
        words = [w for w in segment.split() if not _ASSIGN_RE.match(w)]
        if not words:
            continue
        words_seen = True
        head = os.path.basename(words[0])
        if head == "git" and len(words) > 1 and words[1] in VIEW_GIT:
            continue
        if head not in VIEW_WORDS:
            return False
    return words_seen


def _is_plan_state(text):
    spot = "/" + text.replace("\\", "/")
    return "/docs/audit/" in spot or any(n in spot for n in PLAN_STATE_NAMES)


def classify(tool, in_main, roots):
    """`run`, `task` or `file` for the content a tool call returned."""
    name, data = tool["name"], tool.get("input") or {}
    if name in AGENT_TOOLS:
        return "task"
    if _reads_plugin_only(tool, roots) or (name in READ_TOOLS + WRITE_TOOLS and _under(
            data.get("file_path") or data.get("path") or "", roots)):
        return "run" if in_main else "task"
    if name in READ_TOOLS + WRITE_TOOLS:
        path = data.get("file_path") or data.get("notebook_path") or data.get("path") or ""
        return "task" if _is_plan_state(path) else "file"
    if name == "Bash":
        command = data.get("command") or ""
        return "file" if _only_views(command) and not _is_plan_state(command) else "task"
    return "task"


def redactor(roots, cwd):
    pairs = sorted([(r, "<plugin>") for r in roots] + ([(cwd, "<repo>")] if cwd else []),
                   key=lambda pair: -len(pair[0]))

    def redact(text):
        for old, new in pairs:
            text = text.replace(old, new)
        return _WIN_ABS_RE.sub("<abs>", _ABS_RE.sub("<abs>", text))
    return redact


def describe(tool, agents, redact):
    name, data = tool["name"], tool.get("input") or {}
    if name in AGENT_TOOLS:
        return "hand-back of %s" % (agents.get(tool["id"], {}).get("type") or "?")
    if name in READ_TOOLS + WRITE_TOOLS:
        target = data.get("file_path") or data.get("notebook_path") or data.get("path") \
            or data.get("pattern") or ""
        return "%s %s" % (name, redact(target))
    if name == "Bash":
        line = " ".join((data.get("command") or "").split())
        return "Bash %s" % redact(line)[:72]
    return name


def _contexts(reqs):
    out = {}
    for req in reqs:
        out.setdefault(req["context"], []).append(req)
    return out


def _ordered(context_reqs):
    """A context's requests in order, each rebuilt final after the request it follows."""
    visible = [r for r in context_reqs if not r["reconstructed"]]
    finals = [r for r in context_reqs if r["reconstructed"] and r.get("after")]
    loose = [r for r in context_reqs if r["reconstructed"] and not r.get("after")]
    out = []
    for req in visible:
        out.append(req)
        out.extend(f for f in finals if f["after"] == req["id"])
    return out + loose


def content(session, reqs, stages, costs):
    """Every piece of content that entered a context, with what writing it cost and
    what every later read of it cost; and the prefix identity checked per context.

    Returns {"items": [...], "contexts": {...}, "mixed": n, "writes": n}."""
    results, agents = session["results"], session["agents"]
    redact = redactor(session["roots"], session["cwd"])
    items, contexts, mixed, writes = [], {}, 0, 0
    for context, members in _contexts(reqs).items():
        chain = _ordered(members)
        in_main = context == MAIN
        reads_after = []
        for k in range(len(chain)):
            reads_after.append(sum(_rate(r["model"], "cacheR") for r in chain[k + 1:]))
        # `held` is what the identity predicts this request reads. It is never reset
        # to the recorded value: after a cache break every item written before it is
        # still counted as carried, so the gap must stay counted on every later
        # request too, or the carry and the gap would double-count the same reads.
        held, broken, unexplained = 0, 0, 0.0
        for j, req in enumerate(chain):
            stage = stages[req["id"]]
            if j == 0:
                held = req["cr"]
            elif req["cr"] != held:
                broken += 1
                unexplained += (req["cr"] - held) * _rate(req["model"], "cacheR")
            cw = req["cw5"] + req["cw1"]
            per_token = costs[req["id"]]["cw"] / cw if cw else 0.0
            if j == 0:
                kind = "run" if in_main else "task"
                if req["cr"]:
                    base = _item(stage, kind, req["cr"], 0, 0.0,
                                 req["cr"] * _rate(req["model"], "cacheR")
                                 + req["cr"] * reads_after[0],
                                 len(chain), "cached before this context began", req)
                    base["base"] = True
                    items.append(base)
                if cw:
                    writes += 1
                    items.append(_item(stage, kind, cw, 0, cw * per_token,
                                       cw * reads_after[0], len(chain) - 1,
                                       _start_label(context, agents), req))
                held += cw
                continue
            held += cw
            if not cw:
                continue
            writes += 1
            sources = _sources(chain[j - 1], stages, agents, results, in_main,
                               session["roots"], redact)
            total = float(sum(s[3] for s in sources))
            if len(set((s[0], s[1]) for s in sources if s[3])) > 1:
                mixed += 1
            if not total:
                sources = [(stage, "task", "unseen content (system reminders, hook "
                            "context)", 1)]
                total = 1.0
            for origin, kind, label, size in sources:
                if not size:
                    continue
                tokens = cw * size / total
                items.append(_item(origin, kind, tokens, size, tokens * per_token,
                                   tokens * reads_after[j], len(chain) - 1 - j, label, req))
        held_by = dict((k, 0.0) for k in CLASSES)
        mine = set(r["id"] for r in chain)
        for item in items:
            if item["request"] in mine:
                held_by[item["class"]] += item["tokens"]
        contexts[context] = {"requests": len(chain), "identityBreaks": broken,
                             "unexplainedReadUSD": unexplained, "heldByClass": held_by,
                             "readRate": _rate(chain[-1]["model"], "cacheR"),
                             "startRead": chain[0]["cr"],
                             "startWrite": chain[0]["cw5"] + chain[0]["cw1"]}
    return {"items": items, "contexts": contexts, "mixed": mixed, "writes": writes}


def _item(origin, kind, tokens, size, write_usd, carry_usd, reads, label, req):
    return {"stage": origin, "class": kind, "tokens": tokens, "bytes": size,
            "writeUSD": write_usd, "carryUSD": carry_usd, "reads": reads,
            "source": label, "request": req["id"], "base": False}


def _start_label(context, agents):
    if context == MAIN:
        return "session start"
    if context in agents:
        return "agent start: %s" % (agents[context].get("type") or "?")
    return "tokens no visible request holds"


def _sources(prev, stages, agents, results, in_main, roots, redact):
    """(origin stage, class, label, bytes) for everything `prev` added to its context."""
    stage = stages[prev["id"]]
    own = "run" if stage == "orient" else "task"
    out = [(stage, kind, WRITE_LABEL[kind], prev["emitWrite"][kind])
           for kind in CLASSES if kind in prev["emitWrite"]]
    out.append((stage, own, "output: text and calls", prev["emitOther"]))
    for tool in prev["tools"]:
        size = (results.get(tool["id"]) or {}).get("bytes", 0)
        origin = agent_stage(agents[tool["id"]]["type"]) if tool["id"] in agents else stage
        out.append((origin, classify(tool, in_main, roots),
                    describe(tool, agents, redact), size))
    # A command body is plugin prose the host typed into the context: fixed per run in
    # the main loop, as a Read of the same file would be.
    for block in prev.get("injected") or []:
        kind = "run" if in_main and block["label"].startswith("command body") else "task"
        out.append((stage, kind, block["label"], block["bytes"]))
    return out


# --- time ------------------------------------------------------------------------
def wall_clock(session, stages):
    """{stage: seconds}: each gap between timestamped events goes to the stage of the
    later event - a tool result to the stage that called it, a hand-back to the agent
    that produced it. The stages partition the first-to-last span."""
    agents, calls = session["agents"], session["calls"]

    def stage_of(kind, key):
        if kind == "request":
            return stages.get(key, "?")
        if kind == "brief" or key in agents:
            return agent_stage(agents.get(key, {}).get("type"))
        return stages.get(calls.get(key), "?")
    stamped = [(t, kind, key) for t, kind, key in session["timeline"] if t is not None]
    spent, backwards = {}, 0
    for (t0, _k0, _key0), (t1, kind, key) in zip(stamped, stamped[1:]):
        gap = t1 - t0
        if gap < 0:
            backwards += 1
            gap = 0.0
        stage = stage_of(kind, key)
        spent[stage] = spent.get(stage, 0.0) + gap
    span = stamped[-1][0] - stamped[0][0] if len(stamped) > 1 else 0.0
    return {"byStage": spent, "span": span, "backwards": backwards}


# --- spans: planning, the task cycle, and what follows it --------------------------
# The task verbs a span bound is read off. A verb is the word after the script's own
# path and its operand the word after that, so `done --help` names no task and closes
# nothing, and a path held in a shell variable is followed to the script it names.
TASK_SCRIPT = "audit-task.py"
PLAN_VERBS = ("add", "add-phase")
PLAN_SKILLS = ("audit:phase", "audit:task")
LANDING_SCRIPT = "close-phase.py"
DRIVER_SCRIPT = "drive-phase.py"
LOCK_SCRIPT = "audit-lock.py"
_VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
# A shell assignment as a word after quote removal: its value may hold spaces.
_NAME_SET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _words(segment):
    """A shell segment's words, quotes removed; an unbalanced quote falls back to a
    split on whitespace rather than dropping the segment."""
    try:
        return shlex.split(segment, comments=False, posix=True)
    except ValueError:
        return segment.split()


def _expand(word, names):
    """Every value `word` takes under the shell variables `names` holds, each a list
    because a `for` loop binds one name to several words. An unknown name stays as
    written, so `$t` outside a loop is an operand nobody can read."""
    found = _VAR_RE.search(word)
    if not found or found.group(1) not in names:
        return [word]
    out = []
    for value in names[found.group(1)]:
        out.extend(_expand(word[:found.start()] + value + word[found.end():], names))
    return out


def script_calls(command):
    """[(script, verb, operand)] for every Python script a shell command runs, in order.
    `verb` is the first word after the script, `operand` the next one when it is not a
    flag; either is None when absent."""
    names, calls = {}, []
    for segment in _segments(command):
        words = _words(segment)
        while words and words[0] in ("do", "then", "else", "{", "(", "!"):
            words = words[1:]
        if len(words) >= 3 and words[0] == "for" and words[2] == "in":
            names[words[1]] = [w for w in words[3:] if w not in ("do", ";")]
            continue
        held = []
        for word in words:
            if not _NAME_SET_RE.match(word):
                break
            held.append(word)
        for word in held:
            name, value = word.split("=", 1)
            names[name] = _expand(value, names)
        # One command line per value a loop variable takes, so `start $t` over two
        # ids is two starts. Only a variable's value is split again, as the shell
        # splits an unquoted expansion; a quoted literal stays one word.
        lines = [[]]
        for word in words[len(held):]:
            values = _expand(word, names)
            parts = [[word]] if values == [word] else [_words(v) for v in values]
            lines = [line + part for line in lines for part in parts]
        for flat in lines:
            calls.extend(_calls_in(flat))
    return calls


def _calls_in(flat):
    """[(script, verb, operand)] for each word of one expanded command line that names
    a Python script."""
    calls = []
    for i, word in enumerate(flat):
        script = os.path.basename(word.replace("\\", "/"))
        if not script.endswith(".py"):
            continue
        verb = flat[i + 1] if i + 1 < len(flat) else None
        operand = flat[i + 2] if verb is not None and i + 2 < len(flat) else None
        if verb is not None and verb.startswith("-"):
            verb, operand = None, None
        if operand is not None and (operand.startswith("-") or "$" in operand):
            operand = None
        calls.append((script, verb, operand))
    return calls


def request_marks(req, results=None):
    """What one main-loop request did that a span bound reads: whether it planned, the
    tasks it started and closed, whether it called a planning verb, landed the phase or
    released the lock. A step driver's call does what its result's did-lines say it
    did, read from `results` (tool id -> the parsed result): the tasks it started and
    closed, a fix task it added - a planning verb run in its subprocess - and the
    landing and lock release its final step made."""
    marks = {"plans": False, "adds": False, "starts": [], "dones": [], "lands": False,
             "releases": False}
    for tool in req["tools"]:
        data = tool.get("input") or {}
        if tool["name"] == "Skill":
            args = str(data.get("args") or "").split()
            if data.get("skill") in PLAN_SKILLS and args[:1] == ["add"]:
                marks["plans"] = True
            continue
        if tool["name"] != "Bash":
            continue
        for script, verb, operand in script_calls(data.get("command") or ""):
            if script == DRIVER_SCRIPT:
                did = _DRIVE.did_events(((results or {}).get(tool.get("id")) or {})
                                        .get("text"))
                marks["starts"].extend(did[_DRIVE.STARTED])
                marks["dones"].extend(did[_DRIVE.CLOSED])
                if did["added"]:
                    marks["plans"] = marks["adds"] = True
                marks["lands"] = marks["lands"] or did["landed"]
                marks["releases"] = marks["releases"] or did["released"]
            elif script == TASK_SCRIPT and verb in PLAN_VERBS:
                marks["plans"] = marks["adds"] = True
            elif script == TASK_SCRIPT and verb in ("start", "done") and operand:
                marks["starts" if verb == "start" else "dones"].append(operand)
            elif script == LANDING_SCRIPT:
                marks["lands"] = True
            elif script == LOCK_SCRIPT and verb == "release":
                marks["releases"] = True
    return marks


def find_spans(main, results=None):
    """The span of every visible main-loop request, by index, and what bounds them.

    The cycle opens at the first request that starts a task and closes at the last
    request that closes one before any request inside it plans. Planning opens at the
    first request before the cycle that plans and closes at the last one before the
    cycle that calls a planning verb, or where it opened when none does. After the
    cycle: a fix task runs from each planning verb to the next request that closes a
    task, the close starts at the lock release or after the landing, whichever comes
    first, and sign-off is the rest."""
    marks = [request_marks(r, results) for r in main]
    count = len(main)
    lo = next((i for i, m in enumerate(marks) if m["starts"]), None)
    found = {"marks": marks, "lo": lo, "hi": None, "why": None, "tasks": [],
             "doneAfter": [], "unclosedFix": []}
    if lo is None:
        found["why"] = "no request starts a task, so this session has no task cycle"
        before = count
    else:
        stop = next((i for i in range(lo + 1, count) if marks[i]["plans"]), count)
        closes = [i for i in range(lo, stop) if marks[i]["dones"]]
        if not closes:
            found["why"] = ("request %d starts a task and no request after it closes one "
                            "before any plans: the cycle never closed" % (lo + 1))
        else:
            found["hi"] = closes[-1]
            found["tasks"] = sorted(set(t for i in closes for t in marks[i]["dones"]))
        before = lo
    span = [None] * count
    planners = [i for i in range(before) if marks[i]["plans"]]
    if planners:
        verbs = [i for i in range(before) if marks[i]["adds"]]
        last = verbs[-1] if verbs else planners[0]
        for i in range(planners[0], max(last, planners[0]) + 1):
            span[i] = "planning"
    other = "before the cycle" if lo is not None else "outside any cycle"
    for i in range(before):
        span[i] = span[i] or other
    if lo is not None and found["hi"] is None:
        for i in range(lo, count):
            span[i] = "unclosed cycle"
        return span, found
    if lo is None:
        return span, found
    hi = found["hi"]
    for i in range(lo, hi + 1):
        span[i] = "cycle"
    after = range(hi + 1, count)
    found["doneAfter"] = [(i, t) for i in after for t in marks[i]["dones"]]
    landed = [i for i in after if marks[i]["lands"]]
    released = [i for i in after if marks[i]["releases"]]
    starts = [released[0]] if released else []
    if landed:
        starts.append(landed[-1] + 1)
    close = min(starts) if starts else count
    for i in range(close, count):
        span[i] = "close"
    for i in [j for j in after if j < close and marks[j]["adds"]]:
        end = next((j for j in range(i, close) if marks[j]["dones"]), None)
        if end is None:
            found["unclosedFix"].append(i)
            end = close - 1
        for j in range(i, end + 1):
            span[j] = "fix task"
    for i in after:
        span[i] = span[i] or "sign-off"
    return span, found


SPAN_ORDER = ("planning", "before the cycle", "outside any cycle", "cycle",
              "unclosed cycle", "sign-off", "fix task", "close", "unattributed")


def _ranges(numbers):
    """`1-3, 7` for [1, 2, 3, 7]."""
    out, run = [], []
    for n in sorted(numbers):
        if run and n != run[-1] + 1:
            out.append(run)
            run = []
        run.append(n)
    if run:
        out.append(run)
    return ", ".join("%d" % r[0] if len(r) == 1 else "%d-%d" % (r[0], r[-1]) for r in out)


def spans(reading):
    """The span reading: every visible main-loop request's span, each request's span
    (an agent's is that of the main-loop request that dispatched it), and the bounds."""
    session = reading["session"]
    main = [r for r in reading["requests"] if r["context"] == MAIN and not r["reconstructed"]]
    span, found = find_spans(main, session.get("results"))
    of_main = dict((r["id"], span[i]) for i, r in enumerate(main))
    agents = session["agents"]
    by_id = dict((r["id"], r) for r in reading["requests"])

    def owner(req, depth=0):
        if req["id"] in of_main:
            return of_main[req["id"]]
        dispatch = agents.get(req["context"])
        if dispatch is None or depth > len(agents):
            return "unattributed"
        parent = by_id.get(dispatch["request"])
        return owner(parent, depth + 1) if parent else "unattributed"
    of_request = dict((r["id"], owner(r)) for r in reading["requests"])
    return {"main": main, "span": span, "found": found, "ofRequest": of_request,
            "position": dict((r["id"], i) for i, r in enumerate(main))}


def span_table(reading, spread):
    """{span: {requests, numbers, mainUSD, agentsUSD, read, written, output}}: every
    request in the span of the main-loop request it belongs to, priced as billed."""
    rows = {}
    out = reading["output"] or {}
    for req in reading["requests"]:
        name = spread["ofRequest"][req["id"]]
        row = rows.setdefault(name, {"requests": 0, "numbers": [], "mainUSD": 0.0,
                                     "agentsUSD": 0.0, "read": 0, "written": 0,
                                     "output": 0.0})
        cost = reading["costs"][req["id"]]["total"]
        if req["context"] == MAIN and req["id"] in spread["position"]:
            row["mainUSD"] += cost
            row["requests"] += 1
            row["numbers"].append(spread["position"][req["id"]] + 1)
            row["read"] += req["cr"]
            row["written"] += req["cw5"] + req["cw1"]
            row["output"] += out.get(req["id"], 0.0)
        else:
            row["agentsUSD"] += cost
    return rows


def _made_by(main):
    """{request id: the main-loop request before it}: a main-loop cache write holds
    what the request before it added, so content is counted for that request."""
    return dict((main[i]["id"], main[i - 1]["id"]) for i in range(1, len(main)))


def cycle_reading(reading, spread, top=4):
    """The task cycle's own figures, or None when the session has none: its requests,
    their output, the task-class tokens they put into the main loop, its cost by class
    with the agents its requests dispatched, and its largest outputs."""
    found = spread["found"]
    if found["hi"] is None:
        return None
    main = spread["main"]
    cycle = set(r["id"] for r in main[found["lo"]:found["hi"] + 1])
    made = _made_by(main)
    sent = set(aid for aid, a in reading["session"]["agents"].items()
               if spread["ofRequest"].get(a["request"]) == "cycle")
    usd = dict((k, 0.0) for k in CLASSES)
    tokens = dict((k, 0.0) for k in CLASSES)
    context = dict((r["id"], r["context"]) for r in reading["requests"])
    for item in reading["content"]["items"]:
        where = context[item["request"]]
        if (where == MAIN and made.get(item["request"]) in cycle) or where in sent:
            usd[item["class"]] += item["writeUSD"] + item["carryUSD"]
            if where == MAIN:
                tokens[item["class"]] += item["tokens"]
    members = [r for r in reading["requests"] if r["id"] in cycle or r["context"] in sent]
    for req in members:
        cost, stage = reading["costs"][req["id"]], reading["stages"][req["id"]]
        usd["run" if stage == "orient" else "task"] += cost["in"]
        for kind, share in _output_class(req, stage).items():
            usd[kind] += (cost["out"] or 0.0) * share
    out = reading["output"] or {}
    loud = [row for row in largest_outputs(reading, len(reading["requests"]))
            if row["request"] in set(r["id"] for r in members)][:top]
    return {"first": found["lo"] + 1, "last": found["hi"] + 1, "requests": len(cycle),
            "tasks": found["tasks"], "output": sum(out.get(i, 0.0) for i in cycle),
            "tokens": tokens, "usd": usd, "agents": len(sent), "largest": loud,
            "outputMeasured": reading["output"] is not None}


def origin_of(item):
    """Where a piece of main-loop content came from, by its source."""
    source = item["source"]
    if item.get("base"):
        return "cached before"
    if source == "session start":
        return source
    if source.startswith("Read <plugin>/reference/"):
        return "reference prose"
    if (source.startswith("command body") or source.startswith("Read <plugin>/commands/")
            or source == "Skill"):
        return "command bodies"
    if source.startswith("hand-back"):
        return "hand-backs"
    if source.startswith("output:"):
        return "main-loop output"
    if item["class"] == "file":
        return "file reads"
    if source.startswith("Bash") and ("<plugin>" in source or "/scripts/" in source):
        return "plugin script output"
    return "other tool output"


def origins(reading, spread):
    """{origin: {atStart, inCycle, sessionUSD}} for the main loop: the tokens of the
    prefix the cycle's first request read, the tokens the cycle's requests read, and
    each origin's write and carry over the session. With no cycle the first two are
    None."""
    found = spread["found"]
    lo, hi = found["lo"], found["hi"]
    pos = spread["position"]
    count = len(spread["main"])
    rows = {}
    for item in reading["content"]["items"]:
        if item["request"] not in pos:
            continue
        row = rows.setdefault(origin_of(item), {"atStart": 0.0, "inCycle": 0.0,
                                                "sessionUSD": 0.0})
        row["sessionUSD"] += item["writeUSD"] + item["carryUSD"]
        if hi is None:
            continue
        j = pos[item["request"]]
        if j <= lo - 1 or (item.get("base") and j <= lo):
            row["atStart"] += item["tokens"]
        first = j if item.get("base") else j + 1
        row["inCycle"] += item["tokens"] * sum(1 for k in range(first, count) if lo <= k <= hi)
    if hi is None:
        for row in rows.values():
            row["atStart"] = row["inCycle"] = None
    return rows


def reference_reads(reading, spread):
    """{span: [reads, tokens]}: every `Read` of a plugin reference file the main loop
    made, by the span of the request that made it."""
    made = _made_by(spread["main"])
    out = {}
    for item in reading["content"]["items"]:
        if origin_of(item) != "reference prose" or item["request"] not in made:
            continue
        name = spread["ofRequest"][made[item["request"]]]
        slot = out.setdefault(name, [0, 0.0])
        slot[0] += 1
        slot[1] += item["tokens"]
    return out


def injections(session):
    """[(main-loop request number, label, bytes)] for each user text block the main
    loop received, in stream order."""
    main = [r for r in session["requests"] if r["context"] == MAIN]
    return [(n + 1, block["label"], block["bytes"])
            for n, req in enumerate(main) for block in req.get("injected") or []]


def context_gaps(session):
    """{context: (seconds, after request number) or None}: the longest wait between
    two consecutive requests of a context, each timed at its first event. None when
    the context has fewer than two timed requests."""
    out = {}
    for context, members in _contexts([r for r in session["requests"]]).items():
        timed = [(n + 1, r["at"]) for n, r in enumerate(members) if r.get("at") is not None]
        gaps = [(b[1] - a[1], a[0]) for a, b in zip(timed, timed[1:])]
        out[context] = max(gaps) if gaps else None
    return out


def dispatches(reading, spread):
    """One row per dispatch the main loop made: where, of what type, on which model,
    whether it was launched in the background, its requests, its start read and
    written, and what it cost - a rebuilt final included."""
    session = reading["session"]
    rows = []
    for aid, dispatch in session["agents"].items():
        mine = [r for r in reading["requests"] if r["context"] == aid]
        seen = [r for r in mine if not r["reconstructed"]]
        if dispatch["context"] != MAIN or not seen:
            continue
        first = seen[0]
        rows.append({"id": aid, "at": spread["position"].get(dispatch["request"], -1) + 1,
                     "span": spread["ofRequest"].get(dispatch["request"], "unattributed"),
                     "type": dispatch["type"], "model": first["model"],
                     "background": bool((session["results"].get(aid) or {}).get("launched")),
                     "requests": len(mine), "rebuilt": len(mine) - len(seen),
                     "startRead": first["cr"], "startWritten": first["cw5"] + first["cw1"],
                     "usd": sum(reading["costs"][r["id"]]["total"] for r in mine)})
    return sorted(rows, key=lambda r: (r["at"], r["id"]))


# --- the whole reading -------------------------------------------------------------
def analyse(events):
    session = parse(events)
    extra, notes = reconstruct(session)
    reqs = session["requests"] + extra
    stages = assign_stages(session)
    for req in extra:
        if req["context"] == MAIN:
            stages[req["id"]] = "unattributed"
        elif req["context"] in session["agents"]:
            stages[req["id"]] = agent_stage(session["agents"][req["context"]]["type"])
        else:
            stages[req["id"]] = "unattributed"
    out, out_notes = apportion_output(session, reqs)
    costs = dict((r["id"], request_cost(r, None if out is None else out.get(r["id"], 0.0)))
                 for r in reqs)
    filled = content(session, reqs, stages, costs)
    return {"session": session, "requests": reqs, "stages": stages, "output": out,
            "costs": costs, "content": filled, "notes": notes + out_notes,
            "wall": wall_clock(session, stages)}


def stage_table(reading):
    """{stage: totals} - the BILLING view: every token of a request counts in that
    request's stage, exactly as the request was billed. Only output is apportioned."""
    rows = {}
    out = reading["output"]
    for req in reading["requests"]:
        r = rows.setdefault(reading["stages"][req["id"]],
                            {"requests": 0, "rebuilt": 0, "in": 0, "cw5": 0, "cw1": 0,
                             "cr": 0, "out": 0.0, "usdIn": 0.0, "usdCw": 0.0,
                             "usdCr": 0.0, "usdOut": 0.0})
        cost = reading["costs"][req["id"]]
        r["requests"] += 1
        r["rebuilt"] += 1 if req["reconstructed"] else 0
        for key in ("in", "cw5", "cw1", "cr"):
            r[key] += req[key]
        r["out"] += 0.0 if out is None else out.get(req["id"], 0.0)
        r["usdIn"] += cost["in"]
        r["usdCw"] += cost["cw"]
        r["usdCr"] += cost["cr"]
        r["usdOut"] += cost["out"] or 0.0
    for r in rows.values():
        r["usd"] = r["usdIn"] + r["usdCw"] + r["usdCr"] + r["usdOut"]
    return rows


def _output_class(req, stage):
    """{class: share} of what a request emitted: what it wrote to a path goes to that
    path's class, the rest is the stage's own work."""
    own = "run" if stage == "orient" else "task"
    emitted = float(_emitted(req))
    if not emitted:
        return {own: 1.0}
    shares = {own: req["emitOther"] / emitted}
    for kind, size in req["emitWrite"].items():
        shares[kind] = shares.get(kind, 0.0) + size / emitted
    return shares


def origin_matrix(reading):
    """{stage: {class: USD}} - the CONTENT view: what each stage put into a context,
    priced as written plus every later read of it, plus the stage's own input and
    output. Rows and columns both sum to the billed total; sizes inside a write that
    held several sources are split by bytes [estimate]."""
    rows = {}
    for item in reading["content"]["items"]:
        row = rows.setdefault(item["stage"], dict((k, 0.0) for k in CLASSES))
        row[item["class"]] += item["writeUSD"] + item["carryUSD"]
    for req in reading["requests"]:
        stage = reading["stages"][req["id"]]
        cost = reading["costs"][req["id"]]
        row = rows.setdefault(stage, dict((k, 0.0) for k in CLASSES))
        row["run" if stage == "orient" else "task"] += cost["in"]
        for kind, share in _output_class(req, stage).items():
            row[kind] += (cost["out"] or 0.0) * share
    return rows


def largest_outputs(reading, top):
    """The requests that emitted the most output, with what they emitted - an
    output token's price is the dearest in the table, and a stage's output is only
    visible in aggregate in the billing view."""
    out = reading["output"] or {}
    agents = reading["session"]["agents"]
    redact = redactor(reading["session"]["roots"], reading["session"]["cwd"])
    ranked = sorted(reading["requests"], key=lambda r: (-out.get(r["id"], 0.0), r["id"]))
    rows = []
    for req in ranked[:top]:
        parts = []
        for tool in req["tools"]:
            size = _emitted_bytes({"type": "tool_use", "input": tool.get("input")})
            if tool["name"] in AGENT_TOOLS:
                what = "brief for %s" % (agents.get(tool["id"], {}).get("type") or "?")
            else:
                what = describe(tool, agents, redact)
            parts.append("%s (%d B)" % (what[:60], size))
        rest = _emitted(req) - sum(
            _emitted_bytes({"type": "tool_use", "input": t.get("input")}) for t in req["tools"])
        if req["reconstructed"]:
            parts.append("hand-back text (%d B)" % req["emitOther"])
        elif rest > 0:
            parts.append("text and thinking (%d B)" % rest)
        rows.append({"request": req["id"], "stage": reading["stages"][req["id"]],
                     "tokens": out.get(req["id"], 0.0),
                     "usd": reading["costs"][req["id"]]["out"] or 0.0, "emitted": parts})
    return rows


def class_table(reading):
    """{class: {write, carry, out, in, total}} in USD - the per-run / per-task / per-file
    answer. Output and input go to the class of the request that paid them."""
    rows = dict((k, {"write": 0.0, "carry": 0.0, "out": 0.0, "in": 0.0}) for k in CLASSES)
    for item in reading["content"]["items"]:
        rows[item["class"]]["write"] += item["writeUSD"]
        rows[item["class"]]["carry"] += item["carryUSD"]
    for req in reading["requests"]:
        cost = reading["costs"][req["id"]]
        stage = reading["stages"][req["id"]]
        rows["run" if stage == "orient" else "task"]["in"] += cost["in"]
        for kind, share in _output_class(req, stage).items():
            rows[kind]["out"] += (cost["out"] or 0.0) * share
    for r in rows.values():
        r["total"] = r["write"] + r["carry"] + r["out"] + r["in"]
    return rows


def cache_economics(reading):
    """What the cache saved and what it could not: the session priced as billed,
    against the same tokens with every input-side token at the base input rate."""
    billed = sum(c["total"] for c in reading["costs"].values())
    uncached = 0.0
    reads = premium = 0.0
    for req in reading["requests"]:
        base = _rate(req["model"], "in")
        cost = reading["costs"][req["id"]]
        uncached += (req["in"] + req["cw5"] + req["cw1"] + req["cr"]) * base + (cost["out"] or 0.0)
        reads += cost["cr"]
        premium += cost["cw"] - (req["cw5"] + req["cw1"]) * base
    never = sum(i["writeUSD"] for i in reading["content"]["items"] if i["reads"] == 0)
    output = sum(c["out"] or 0.0 for c in reading["costs"].values())
    return {"billed": billed, "uncached": uncached, "saved": uncached - billed,
            "readsPaid": reads, "writePremium": premium, "neverReadWrites": never,
            "output": output}


def reconciliation(reading):
    """Per model: priced by the shipped table against the session's own costUSD."""
    result = reading["session"]["result"] or {}
    usage = result.get("modelUsage") or {}
    priced = {}
    for req in reading["requests"]:
        priced[req["model"]] = priced.get(req["model"], 0.0) + reading["costs"][req["id"]]["total"]
    rows = []
    for model in sorted(set(list(priced) + list(usage))):
        told = (usage.get(model) or {}).get("costUSD")
        rows.append((model, priced.get(model, 0.0), told))
    return rows, result.get("total_cost_usd")


# --- rendering -------------------------------------------------------------------
def _stage_key(stage):
    return (STAGE_ORDER.index(stage) if stage in STAGE_ORDER else len(STAGE_ORDER), stage)


def render(reading, top=10):
    session = reading["session"]
    result = session["result"] or {}
    init = session["init"]
    lines = ["stream-cost: claude_code %s, main model %s"
             % (init.get("claude_code_version") or "?", init.get("model") or "?")]
    stretched = len(session["ends"]) > 1
    if session["result"] is not None:
        lines.append("[measured] %s: total_cost_usd=%s duration_ms=%s num_turns=%s"
                     % ("result event" if not stretched else
                        "%d result events, one per stretch, duration_ms and num_turns summed"
                        % len(session["ends"]),
                        result.get("total_cost_usd"), result.get("duration_ms"),
                        result.get("num_turns")))
    lines.append("reconstruction:")
    lines.extend("  " + n for n in reading["notes"])
    if session["unjoined"]:
        lines.append("  %d assistant events carried no message id and were not joined"
                     % session["unjoined"])
    untimed = sum(1 for r in reading["requests"] if not r["ttlKnown"])
    if untimed:
        lines.append("  %d requests carried no write TTL split; priced at the 5m rate "
                     "(the lower bound)" % untimed)
    rows, total = reconciliation(reading)
    lines.append("pricing: the shipped table (_usage_core, as of %s) against the "
                 "session's own costUSD:" % _usage_core.PRICING_AS_OF)
    for model, priced, told in rows:
        verdict = ("not reported" if told is None else
                   "agree" if abs(priced - told) < 5e-7 else "DIFFER by %+.6f" % (priced - told))
        lines.append("  %-20s priced=%.6f costUSD=%s  %s"
                     % (model, priced, "-" if told is None else "%.6f" % told, verdict))
    billed = sum(c["total"] for c in reading["costs"].values())
    lines.append("  all models          priced=%.6f total_cost_usd=%s" % (billed, total))
    table = stage_table(reading)
    lines.append("")
    lines.append("per stage, as billed [every token in the stage of the request that "
                 "paid it, measured; out apportioned by emitted bytes within its measured "
                 "pool, estimate]")
    lines.append("  %-10s %4s %5s %8s %8s %9s %7s  %8s %8s %8s %8s %8s %6s %7s"
                 % ("stage", "req", "in", "cacheW5m", "cacheW1h", "cacheR", "out",
                    "$in", "$cacheW", "$cacheR", "$out", "$total", "share", "wall_s"))
    wall = reading["wall"]["byStage"]
    for stage in sorted(table, key=_stage_key):
        r = table[stage]
        lines.append("  %-10s %4s %5d %8d %8d %9d %7d  %8.4f %8.4f %8.4f %8.4f %8.4f %5.1f%% %7.1f"
                     % (stage, "%d%s" % (r["requests"], "*" if r["rebuilt"] else ""),
                        r["in"], round(r["cw5"]), round(r["cw1"]), r["cr"], round(r["out"]),
                        r["usdIn"], r["usdCw"], r["usdCr"], r["usdOut"], r["usd"],
                        100.0 * r["usd"] / billed if billed else 0.0, wall.get(stage, 0.0)))
    rebuilt = any(r["rebuilt"] for r in table.values())
    duration = result.get("duration_ms")
    if not duration:
        timed = ""
    elif stretched:
        # The span less the summed duration_ms is not time before the first event here:
        # in the recorded streams a stretch's stamped extent differs from its own
        # duration_ms, in both directions.
        timed = "; duration_ms summed over the stretches is %.1fs" % (duration / 1000.0)
    else:
        timed = ("; duration_ms adds %.1fs before the first one"
                 % (duration / 1000.0 - reading["wall"]["span"]))
    lines.append("  %swall_s partitions the first-to-last stream timestamp: %.1fs%s"
                 % ("* holds a rebuilt request. " if rebuilt else "", reading["wall"]["span"],
                    timed))
    filled = reading["content"]
    matrix = origin_matrix(reading)
    lines.append("")
    lines.append("per stage, by what it put there [a write and every later read of it in "
                 "the stage the content came from; sizes split by bytes where a write held "
                 "several sources: %d of %d writes, estimate]" % (filled["mixed"], filled["writes"]))
    lines.append("  %-10s %8s %8s %8s %8s %6s" % ("stage", "$run", "$task", "$file", "$total",
                                                "share"))
    for stage in sorted(matrix, key=_stage_key):
        row = matrix[stage]
        whole = sum(row.values())
        lines.append("  %-10s %8.4f %8.4f %8.4f %8.4f %5.1f%%"
                     % (stage, row["run"], row["task"], row["file"], whole,
                        100.0 * whole / billed if billed else 0.0))
    classes = class_table(reading)
    lines.append("")
    lines.append("by content class [write and carry: exact read counts on sizes split "
                 "by bytes where a write held several sources]")
    lines.append("  %-6s %8s %8s %8s %8s %8s %6s  %s"
                 % ("class", "$write", "$carry", "$out", "$in", "$total", "share", "meaning"))
    for kind in CLASSES:
        r = classes[kind]
        lines.append("  %-6s %8.4f %8.4f %8.4f %8.4f %8.4f %5.1f%%  %s"
                     % (kind, r["write"], r["carry"], r["out"], r["in"], r["total"],
                        100.0 * r["total"] / billed if billed else 0.0, CLASS_MEANING[kind]))
    unexplained = sum(c["unexplainedReadUSD"] for c in filled["contexts"].values())
    breaks = sum(c["identityBreaks"] for c in filled["contexts"].values())
    lines.append("  reads the prefix identity does not explain: $%.4f over %d request(s)"
                 % (unexplained, breaks))
    econ = cache_economics(reading)
    lines.append("")
    lines.append("cache [same tokens, every input-side token at the base input rate]:")
    lines.append("  without the cache $%.4f   as billed $%.4f   saved $%.4f"
                 % (econ["uncached"], econ["billed"], econ["saved"]))
    lines.append("  reads still paid $%.4f   write premium over base input $%.4f "
                 "(on writes never read again $%.4f)   output $%.4f"
                 % (econ["readsPaid"], econ["writePremium"], econ["neverReadWrites"],
                    econ["output"]))
    lines.append("")
    lines.append("largest cache writes [tokens split by bytes within a write: estimate]")
    lines.append("  %-9s %-5s %7s %7s %6s %5s %8s %8s %8s  %s"
                 % ("stage", "class", "tokens", "bytes", "B/tok", "reads", "$write",
                    "$carry", "$total", "source"))
    ranked = sorted(filled["items"], key=lambda i: (-i["tokens"], i["source"]))
    for item in [i for i in ranked if not i["base"]][:top]:
        ratio = item["bytes"] / item["tokens"] if item["bytes"] and item["tokens"] else 0.0
        lines.append("  %-9s %-5s %7d %7d %6s %5d %8.4f %8.4f %8.4f  %s"
                     % (item["stage"], item["class"], round(item["tokens"]), item["bytes"],
                        "%.2f" % ratio if ratio else "-", item["reads"], item["writeUSD"],
                        item["carryUSD"], item["writeUSD"] + item["carryUSD"], item["source"]))
    lines.append("")
    lines.append("largest outputs [output tokens apportioned by emitted bytes: estimate]")
    for row in largest_outputs(reading, min(top, 6)):
        lines.append("  %-9s %7d %8.4f  %s" % (row["stage"], round(row["tokens"]), row["usd"],
                                               "; ".join(row["emitted"]) or "-"))
    lines.append("")
    lines.append("contexts: requests, identity breaks, what the first request found cached "
                 "and wrote [measured], and the prefix a further request would read, by "
                 "class [tokens; sizes split by bytes: estimate], priced at the cache-read rate")
    lines.append("  %-10s %4s %6s %8s %8s %9s %9s %9s %10s %7s"
                 % ("context", "req", "breaks", "start_cR", "start_cW", "run", "task", "file",
                    "$/request", "gap_s"))
    gaps = context_gaps(session)
    for context, info in sorted(filled["contexts"].items(), key=lambda kv: kv[0] != MAIN):
        name = MAIN if context == MAIN else agent_stage(
            session["agents"].get(context, {}).get("type"))
        held = info["heldByClass"]
        gap = gaps.get(context)
        lines.append("  %-10s %4d %6d %8d %8d %9d %9d %9d %10.4f %7s"
                     % (name, info["requests"], info["identityBreaks"], info["startRead"],
                        info["startWrite"], round(held["run"]), round(held["task"]),
                        round(held["file"]), sum(held.values()) * info["readRate"],
                        "-" if gap is None else "%.0f" % gap[0]))
    main_gap = gaps.get(MAIN)
    lines.append("  gap_s: the longest wait between two consecutive requests of the context, "
                 "each timed at its first event; - where fewer than two are timed")
    if main_gap is not None:
        lines.append("  longest main-loop gap: %.0fs, after main-loop request %d"
                     % (main_gap[0], main_gap[1]))
    lines.extend(render_spans(reading, top))
    return "\n".join(lines)


def render_spans(reading, top=10):
    """The span view: planning, the task cycle and what follows it, with the main
    loop's context by origin, the plugin prose it took in, and every dispatch."""
    session = reading["session"]
    spread = spans(reading)
    found = spread["found"]
    lines = ["", "spans [main-loop requests numbered in stream order; bounds read off "
             "the task verbs and their operands; an agent in the span of the request "
             "that dispatched it]"]
    if found["why"]:
        lines.append("  %s" % found["why"])
    else:
        lines.append("  task cycle: requests %d-%d, tasks %s"
                     % (found["lo"] + 1, found["hi"] + 1, " ".join(found["tasks"])))
    for index, task in found["doneAfter"]:
        lines.append("  done after the cycle: %s at request %d" % (task, index + 1))
    for index in found["unclosedFix"]:
        lines.append("  a fix task added at request %d is never closed before the close"
                     % (index + 1))
    table = span_table(reading, spread)
    if "planning" not in table:
        lines.append("  planning: empty - no request before the cycle plans")
    lines.append("  %-17s %-14s %8s %8s %8s %4s %9s %8s %7s"
                 % ("span", "requests", "$main", "$agents", "$total", "req", "read", "written",
                    "output"))
    for name in sorted(table, key=lambda n: SPAN_ORDER.index(n) if n in SPAN_ORDER else 99):
        row = table[name]
        lines.append("  %-17s %-14s %8.4f %8.4f %8.4f %4d %9d %8d %7.0f"
                     % (name, _ranges(row["numbers"]) or "-", row["mainUSD"],
                        row["agentsUSD"], row["mainUSD"] + row["agentsUSD"], row["requests"],
                        row["read"], row["written"], row["output"]))
    cycle = cycle_reading(reading, spread, min(top, 4))
    if cycle is not None:
        tasks = len(cycle["tasks"]) or 1
        whole = sum(cycle["usd"].values())
        lines.append("")
        lines.append("task cycle [its requests and every request of the agents they "
                     "dispatched; content counted for the request that added it; output "
                     "apportioned by emitted bytes, estimate]")
        lines.append("  requests %d-%d: %d main-loop requests, %d dispatches, holding %s"
                     % (cycle["first"], cycle["last"], cycle["requests"], cycle["agents"],
                        " ".join(cycle["tasks"])))
        lines.append("  main-loop output %s tokens; task-class tokens put into the main "
                     "loop %d (run %d, file %d)"
                     % ("%.0f" % cycle["output"] if cycle["outputMeasured"] else
                        "not measured", round(cycle["tokens"]["task"]),
                        round(cycle["tokens"]["run"]), round(cycle["tokens"]["file"])))
        lines.append("  by class: run %.6f  task %.6f  file %.6f  total %.6f; per task "
                     "(%d) %.6f" % (cycle["usd"]["run"], cycle["usd"]["task"],
                                    cycle["usd"]["file"], whole, tasks, whole / tasks))
        for row in cycle["largest"]:
            lines.append("  largest output: %-9s %7d %8.4f  %s"
                         % (row["stage"], round(row["tokens"]), row["usd"],
                            "; ".join(row["emitted"]) or "-"))
    rows = origins(reading, spread)
    lines.append("")
    lines.append("main loop by origin [tokens; sizes split by bytes within a write: "
                 "estimate]")
    lines.append("  %-22s %14s %16s %12s" % ("origin", "cycle's prefix", "read in cycle",
                                              "$session"))
    for name in sorted(rows, key=lambda k: (-rows[k]["sessionUSD"], k)):
        row = rows[name]
        lines.append("  %-22s %14s %16s %12.4f"
                     % (name, "-" if row["atStart"] is None else "%.0f" % row["atStart"],
                        "-" if row["inCycle"] is None else "%.0f" % row["inCycle"],
                        row["sessionUSD"]))
    lines.append("  cycle's prefix: what its first request read; read in cycle: summed over "
                 "its requests; $session: write and carry over the session")
    told = injections(session)
    lines.append("")
    lines.append("injected text [user text blocks of the main loop, sized as sources of "
                 "their own]: %d" % len(told))
    for number, label, size in told:
        lines.append("  after request %-4d %-28s %7d B" % (number, label, size))
    if session.get("textBeforeAny"):
        lines.append("  %d before the first request, inside the session start's write"
                     % session["textBeforeAny"])
    reads = reference_reads(reading, spread)
    lines.append("reference reads [Read <plugin>/reference/..., by the span of the request "
                 "that read them]: %d" % sum(v[0] for v in reads.values()))
    for name in sorted(reads, key=lambda n: SPAN_ORDER.index(n) if n in SPAN_ORDER else 99):
        lines.append("  %-17s %3d reads %9.0f tokens" % (name, reads[name][0], reads[name][1]))
    rows = dispatches(reading, spread)
    lines.append("")
    lines.append("dispatches [start read and written: the first visible request; $ holds a "
                 "rebuilt final where marked *]")
    for row in rows:
        lines.append("  at %-3d %-17s %-22s %-18s %-10s %3d%s req  start_cR %6d  start_cW "
                     "%6d  %.4f"
                     % (row["at"], row["span"], row["type"][:22], row["model"][:18],
                        "background" if row["background"] else "foreground",
                        row["requests"], "*" if row["rebuilt"] else " ", row["startRead"],
                        row["startWritten"], row["usd"]))
    return lines


def as_json(reading):
    redact = redactor(reading["session"]["roots"], reading["session"]["cwd"])
    rows, total = reconciliation(reading)
    spread = spans(reading)
    found = spread["found"]
    return {"spans": {"cycle": None if found["hi"] is None else
                      {"first": found["lo"] + 1, "last": found["hi"] + 1,
                       "tasks": found["tasks"]},
                      "why": found["why"],
                      "doneAfter": [{"request": i + 1, "task": t} for i, t in found["doneAfter"]],
                      "table": span_table(reading, spread),
                      "byRequest": [spread["span"][i] for i in range(len(spread["main"]))]},
            "taskCycle": cycle_reading(reading, spread),
            "origins": origins(reading, spread),
            "injected": [{"request": n, "label": l, "bytes": b}
                         for n, l, b in injections(reading["session"])],
            "referenceReads": reference_reads(reading, spread),
            "dispatches": dispatches(reading, spread),
            "gaps": dict((k, v) for k, v in context_gaps(reading["session"]).items()),
            "stages": stage_table(reading), "classes": class_table(reading),
            "byOrigin": origin_matrix(reading),
            "largestOutputs": largest_outputs(reading, 10),
            "cache": cache_economics(reading),
            "reconciliation": {"perModel": [{"model": m, "priced": p, "costUSD": t}
                                            for m, p, t in rows], "totalCostUSD": total},
            "notes": [redact(n) for n in reading["notes"]],
            "wall": reading["wall"],
            "items": sorted(reading["content"]["items"], key=lambda i: -i["tokens"]),
            "requests": [{"id": r["id"], "stage": reading["stages"][r["id"]],
                          "model": r["model"], "in": r["in"], "cw5": r["cw5"],
                          "cw1": r["cw1"], "cr": r["cr"],
                          "out": None if reading["output"] is None
                          else reading["output"].get(r["id"]),
                          "rebuilt": r["reconstructed"]} for r in reading["requests"]]}


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stream", help="a stream-json session record (.jsonl)")
    ap.add_argument("--top", type=int, default=10, help="largest cache writes to list")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    try:
        events = load_events(args.stream)
    except (OSError, ValueError) as exc:
        print("stream-cost: cannot read the stream: %s" % exc, file=sys.stderr)
        return 2
    if not any(e.get("type") == "assistant" for e in events):
        print("stream-cost: the stream holds no assistant event, so there is no request "
              "to attribute", file=sys.stderr)
        return 2
    reading = analyse(events)
    if args.as_json:
        print(json.dumps(as_json(reading), indent=2, sort_keys=True))
    else:
        print(render(reading, args.top))
    return 0


# --- selftest ------------------------------------------------------------------
# Every fixture below is built in the shape the recorded streams carry - the same
# keys, the same nesting, a message's usage repeated on every event that carries one
# of its blocks - because a parser and a fixture written by one author encode one
# assumption twice unless the fixture is copied from the source's shape.
# Assembled rather than written, so no scanner for machine paths reads a fixture as one.
_FX_HOME = "/" + "/".join(("Users", "someone"))
_FX_PLUGIN = _FX_HOME + "/cache/audit/plug"
_FX_REPO = _FX_HOME + "/work/proj"
_FX_OPUS = "claude-opus-5-5"
_FX_SONNET = "claude-sonnet-5-5"


def _fx_usage(cr, cw, ttl="1h", inp=2, out=8):
    return {"input_tokens": inp, "cache_creation_input_tokens": cw,
            "cache_read_input_tokens": cr, "output_tokens": out,
            "cache_creation": {"ephemeral_5m_input_tokens": cw if ttl == "5m" else 0,
                               "ephemeral_1h_input_tokens": cw if ttl == "1h" else 0}}


def _fx_input(fields, total):
    """`fields` with a `prompt` padded so the input serializes to exactly `total`
    bytes - the byte count a mixed cache write is split by."""
    bare = dict(fields, prompt="")
    room = total - len(json.dumps(bare, sort_keys=True, separators=(",", ":")))
    return dict(fields, prompt="x" * room)


def _fx_session():
    """The known-answer session. Each request is (id, context, model, cr, cw, ttl,
    blocks); each result is (tool id, bytes, parent). The answer per stage is in
    `_FX_EXPECTED`, worked out by hand from these numbers, not by this tool."""
    exe = _fx_input({"description": "d", "subagent_type": "audit:audit-executor"}, 698)
    rev = _fx_input({"description": "r", "subagent_type": "audit:audit-reviewer"}, 300)
    t = lambda tid, name, data: {"type": "tool_use", "id": tid, "name": name, "input": data}  # noqa: E731
    flow = [
        ("req", "m1", None, _FX_OPUS, 100, 50, "1h",
         [t("t1", "Bash", {"command": "wc -l %s/reference/a.md" % _FX_PLUGIN})]),
        ("res", "t1", 40, None),
        ("req", "m2", None, _FX_OPUS, 150, 10, "1h",
         [{"type": "text", "text": "reading"},
          t("t2", "Read", {"file_path": _FX_PLUGIN + "/reference/a.md"})]),
        ("res", "t2", 4000, None),
        ("req", "m3", None, _FX_OPUS, 160, 1000, "1h",
         [t("t3", "Read", {"file_path": _FX_REPO + "/docs/audit/audit-plan.json"})]),
        ("res", "t3", 400, None),
        ("req", "m4", None, _FX_OPUS, 1160, 100, "1h",
         [{"type": "text", "text": "go"}, t("t4", "Agent", exe)]),
        ("brief", "t4"),
        ("req", "e1", "t4", _FX_OPUS, 0, 500, "5m",
         [t("t5", "Read", {"file_path": _FX_REPO + "/src/a.rb"})]),
        ("res", "t5", 2000, "t4"),
        ("req", "e2", "t4", _FX_OPUS, 500, 600, "5m",
         [t("t6", "Edit", {"file_path": _FX_REPO + "/src/a.rb", "old_string": "a",
                           "new_string": "b"})]),
        ("res", "t6", 100, "t4"),
        ("res", "t4", 300, None),
        ("req", "m5", None, _FX_OPUS, 1260, 200, "1h",
         [t("t7", "Bash", {"command": 'python3 "%s/scripts/governance/run-test-gate.py" x'
                                      % _FX_PLUGIN})]),
        ("res", "t7", 200, None),
        ("req", "m6", None, _FX_OPUS, 1460, 80, "1h", [t("t8", "Agent", rev)]),
        ("brief", "t8"),
        ("req", "r1", "t8", _FX_SONNET, 0, 400, "5m", [t("t9", "Bash", {"command": "git diff"})]),
        ("res", "t9", 500, "t8"),
        ("res", "t8", 200, None),
        ("req", "m7", None, _FX_OPUS, 1540, 150, "1h",
         [t("t10", "Bash", {"command": 'python3 "%s/scripts/manifest/audit-task.py" done'
                                       % _FX_PLUGIN})]),
        ("res", "t10", 50, None),
        ("req", "m8", None, _FX_OPUS, 1690, 20, "1h", [{"type": "text", "text": "done"}]),
    ]
    return flow


# The hidden final requests the result event implies: the executor's (in=2, cacheW=50,
# cacheR=1100) and the reviewer's (in=2, cacheW=60, cacheR=400) - each cacheR is what
# the prefix identity predicts, so a reconstruction that ignored either would miss it.
_FX_MAIN = {"in": 16, "cw": 1610, "cr": 7520, "out": 900}
_FX_EXE = {"in": 6, "cw": 1150, "cr": 1600, "out": 300}
_FX_REV = {"in": 4, "cw": 460, "cr": 400, "out": 100}
# As billed: every token in the stage of the request that paid it.
_FX_EXPECTED = {
    "orient": {"requests": 2, "in": 4, "cw": 60, "cr": 250},
    "plan": {"requests": 2, "in": 4, "cw": 1100, "cr": 1320},
    "executor": {"requests": 3, "in": 6, "cw": 1150, "cr": 1600},
    "gate": {"requests": 2, "in": 4, "cw": 280, "cr": 2720},
    "reviewer": {"requests": 2, "in": 4, "cw": 460, "cr": 400},
    "close": {"requests": 2, "in": 4, "cw": 170, "cr": 3230},
}
# Cache writes by the stage the content came from. The prose orient read is billed to
# plan's first request and comes back to orient here. Two writes held two stages'
# content: m5's (the brief, 700 bytes, from plan; the executor's hand-back, 300 bytes)
# and m7's (the reviewer brief, 300 bytes, from gate; the reviewer's hand-back, 200).
_FX_ORIGIN = {"orient": 1060, "plan": 240, "executor": 1210, "gate": 170, "reviewer": 520,
              "close": 20}


def _fx_result(main=None, exe=None, rev=None, exe_ttl="5m"):
    """The result event. `exe_ttl` is the rate the executor's writes are priced at in
    `costUSD`; modelUsage itself carries one write total per model, with no split."""
    main = dict(_FX_MAIN, **(main or {}))
    exe = dict(_FX_EXE, **(exe or {}))
    rev = dict(_FX_REV, **(rev or {}))
    opus_5m = exe["cw"] if exe_ttl == "5m" else 0
    opus_1h = main["cw"] + (exe["cw"] if exe_ttl == "1h" else 0)

    def cost(model, inn, w5, w1, cr, out):
        return _usage_core.price({"in": inn, "cacheW5m": w5, "cacheW1h": w1, "cacheR": cr,
                                  "out": out}, model)
    return {"type": "result", "subtype": "success", "uuid": "u-result",
            "total_cost_usd": 0.0, "duration_ms": 23500, "num_turns": 8,
            "usage": {"input_tokens": main["in"], "cache_creation_input_tokens": main["cw"],
                      "cache_read_input_tokens": main["cr"], "output_tokens": main["out"]},
            "modelUsage": {
                _FX_OPUS: {"inputTokens": main["in"] + exe["in"],
                           "cacheCreationInputTokens": opus_5m + opus_1h,
                           "cacheReadInputTokens": main["cr"] + exe["cr"],
                           "outputTokens": main["out"] + exe["out"],
                           "costUSD": cost(_FX_OPUS, main["in"] + exe["in"], opus_5m, opus_1h,
                                           main["cr"] + exe["cr"], main["out"] + exe["out"])},
                _FX_SONNET: {"inputTokens": rev["in"], "cacheCreationInputTokens": rev["cw"],
                             "cacheReadInputTokens": rev["cr"], "outputTokens": rev["out"],
                             "costUSD": cost(_FX_SONNET, rev["in"], rev["cw"], 0, rev["cr"],
                                             rev["out"])}}}


def _fx_events(flow, split=False, noise=False, duplicate=False, result=True, roots=True):
    """The stream for `flow`. `split` emits one event per content block with the usage
    repeated on each, as Claude Code does; `noise` interleaves the system events a real
    stream carries; `duplicate` replays one event under its own uuid. An `("init",)`
    step opens a stretch with an `init` event of its own. `result` is True for the
    known-answer result event, False for none, a result event, or a list of them -
    every one written at the end, where the recorded streams hold them."""
    init = {"type": "system", "subtype": "init", "uuid": "u-init", "cwd": _FX_REPO,
            "model": _FX_OPUS, "claude_code_version": "0.0.0",
            "plugins": ([{"name": "audit", "path": _FX_PLUGIN}] if roots else [])
            + [{"name": "builtin-thing", "path": "builtin"}]}
    events = [init]
    clock = [0]

    def stamp():
        clock[0] += 1
        return "2026-10-07T09:00:%02d.000Z" % clock[0]

    def chatter(n):
        if noise:
            events.append({"type": "system", "subtype": "hook_started", "uuid": "u-h%d" % n})
            events.append({"type": "system", "subtype": "thinking_tokens",
                           "estimated_tokens": 50, "uuid": "u-k%d" % n})
            events.append({"type": "rate_limit_event", "uuid": "u-r%d" % n})
    for n, step in enumerate(flow):
        chatter(n)
        if step[0] == "req":
            _kind, mid, parent, model, cr, cw, ttl, blocks = step
            when = stamp()
            parts = [[b] for b in blocks] if split else [blocks]
            for i, part in enumerate(parts):
                events.append({"type": "assistant", "uuid": "u-%s-%d" % (mid, i),
                               "timestamp": when, "parent_tool_use_id": parent,
                               "message": {"id": "msg_" + mid, "model": model,
                                           "usage": _fx_usage(cr, cw, ttl),
                                           "content": part}})
        elif step[0] == "res":
            # A size is a body of that many bytes; a string is the body itself.
            _kind, tid, size, parent = step
            body = size if isinstance(size, str) else "y" * size
            events.append({"type": "user", "uuid": "u-res-" + tid, "timestamp": stamp(),
                           "parent_tool_use_id": parent,
                           "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                                    "content": body}]}})
        elif step[0] == "text":
            # A user text block of the main loop, as the host injects a command body.
            events.append({"type": "user", "uuid": "u-text-%d" % n, "timestamp": stamp(),
                           "parent_tool_use_id": None, "isSynthetic": True,
                           "message": {"content": [{"type": "text", "text": step[1]}]}})
        elif step[0] == "init":
            events.append(dict(init, uuid="u-init-%d" % n))
        else:
            events.append({"type": "user", "uuid": "u-brief-" + step[1], "timestamp": stamp(),
                           "parent_tool_use_id": step[1],
                           "message": {"content": [{"type": "text", "text": "brief"}]}})
    if duplicate:
        # The replay is the dispatch's own block: kept, it would list the Agent call
        # twice and double the bytes the next cache write is split by.
        replay = [e for e in events if e.get("type") == "assistant"
                  and e["message"]["id"] == "msg_m4"
                  and any(b.get("name") == "Agent" for b in e["message"]["content"])]
        events.append(json.loads(json.dumps(replay[-1])))
    if isinstance(result, list):
        events.extend(result)
    elif result:
        events.append(result if isinstance(result, dict) else _fx_result())
    return events


# The known-answer session as a re-invoked one: a second `init` opens a stretch at the
# main loop's fifth request, after the executor's hand-back. Each stretch's main loop,
# worked out by hand from `_fx_session` - requests m1-m4, then m5-m8 - sums to
# `_FX_MAIN`. The output split between them is chosen, not derived: a split by bytes
# across the whole main loop puts a different share in each.
_FX_STRETCHES = ({"in": 8, "cw": 1160, "cr": 1570, "out": 500},
                 {"in": 8, "cw": 450, "cr": 5950, "out": 400})


def _fx_stretched(flow):
    """`flow` with a second stretch opened before the main loop's request m5."""
    at = next(i for i, step in enumerate(flow) if step[0] == "req" and step[1] == "m5")
    return list(flow[:at]) + [("init",)] + list(flow[at:])


def _fx_ends(stretches):
    """One result event per stretch: its own `usage`, and the known-answer session's
    `modelUsage` and `total_cost_usd` repeated in each, as the recorded CLI writes them."""
    ends = []
    for k, part in enumerate(stretches):
        end = _fx_result()
        end["total_cost_usd"] = sum(row["costUSD"] for row in end["modelUsage"].values())
        end.update({"uuid": "u-result-%d" % k, "result_index": k, "duration_ms": 1000 * (k + 2),
                    "usage": {"input_tokens": part["in"],
                              "cache_creation_input_tokens": part["cw"],
                              "cache_read_input_tokens": part["cr"],
                              "output_tokens": part["out"]}})
        ends.append(end)
    return ends


def _fx_main_out(reading, ids):
    """Output tokens the reading gives to the main-loop requests `ids`."""
    return sum(reading["output"]["msg_" + i] for i in ids)


def _fx_stage_totals(reading):
    table = stage_table(reading)
    return dict((stage, {"requests": r["requests"], "in": r["in"],
                         "cw": int(round(r["cw5"] + r["cw1"])), "cr": r["cr"]})
                for stage, r in table.items())


def _close(a, b):
    return abs(a - b) < 1e-9


def _cases(check):
    flow = _fx_session()
    reading = analyse(_fx_events(flow))
    got = _fx_stage_totals(reading)
    check("sc1 the known-answer session, as billed, lands every token in the stage worked "
          "out by hand for the request that paid it: %r" % (got,), got == _FX_EXPECTED)

    origin = {}
    for item in reading["content"]["items"]:
        if not item["base"]:
            origin[item["stage"]] = origin.get(item["stage"], 0.0) + item["tokens"]
    origin = dict((k, int(round(v))) for k, v in origin.items())
    check("sc19 by content, each cache write returns to the stage its content came from - "
          "the prose orient read, billed to plan, comes back to orient, and a hand-back "
          "goes to the agent that wrote it: %r" % (origin,), origin == _FX_ORIGIN)

    twin = analyse(_fx_events(flow, split=True, noise=True, duplicate=True))
    same = all(_close(stage_table(twin)[s][k], stage_table(reading)[s][k])
               for s in stage_table(reading) for k in stage_table(reading)[s])
    check("sc2 THE TWIN: the same session as Claude Code emits it - one event per content "
          "block with the usage repeated on each, hook and rate-limit events between them, "
          "one event replayed - moves not one token or cent between stages. Summing usage "
          "per event instead of per message, or keeping the replay, would: %r"
          % (_fx_stage_totals(twin),),
          set(stage_table(twin)) == set(stage_table(reading)) and same
          and class_table(twin) == class_table(reading))

    rebuilt = [r for r in reading["requests"] if r["reconstructed"]]
    check("sc3 each dispatch's missing final request is rebuilt from the result event, and "
          "the prefix identity's prediction of its cache read agrees: %r"
          % ([(r["id"], r["in"], r["cw5"] + r["cw1"], r["cr"]) for r in rebuilt],),
          sorted((r["context"], r["cw5"], r["cr"]) for r in rebuilt)
          == [("t4", 50, 1100), ("t8", 60, 400)]
          and sum(1 for n in reading["notes"] if "(agrees)" in n) == 2)

    out = reading["output"]
    by_stage = {}
    for req in reading["requests"]:
        stage = reading["stages"][req["id"]]
        by_stage[stage] = by_stage.get(stage, 0.0) + out[req["id"]]
    main_out = sum(v for k, v in by_stage.items() if k not in ("executor", "reviewer"))
    pools = [n for n in reading["notes"] if n.startswith("output pool, measured")]
    check("sc4 output pools are the measured ones - the main loop's from result.usage, each "
          "subagent's from its model's modelUsage less the main loop's share - and only the "
          "split inside a pool is apportioned; each pool is printed: %r" % ((by_stage, pools),),
          _close(main_out, 900) and _close(by_stage["executor"], 300)
          and _close(by_stage["reviewer"], 100)
          and pools == ["output pool, measured: main loop 900 tokens (result.usage)",
                        "output pool, measured: %s subagents 300 tokens (modelUsage less "
                        "the main loop's)" % _FX_OPUS,
                        "output pool, measured: %s subagents 100 tokens (modelUsage less "
                        "the main loop's)" % _FX_SONNET])

    rows, _total = reconciliation(reading)
    check("sc5 priced by the shipped table with each write at its own TTL rate, the session "
          "agrees with every model's costUSD: %r" % (rows,),
          rows and all(told is not None and abs(priced - told) < 1e-9
                       for _m, priced, told in rows))

    flat = analyse(_fx_events(flow))
    for req in flat["requests"]:
        req["cw5"], req["cw1"] = req["cw5"] + req["cw1"], 0
    flat["costs"] = dict((r["id"], request_cost(r, flat["output"].get(r["id"], 0.0)))
                         for r in flat["requests"])
    rows_flat, _t = reconciliation(flat)
    check("sc6 ...and the same tokens with the one-hour writes priced at the five-minute "
          "rate DISAGREE with costUSD, so sc5 is reading the TTL split rather than passing "
          "on any price: %r" % (rows_flat,),
          any(abs(p - t) > 1e-6 for _m, p, t in rows_flat if t is not None))

    billed = sum(c["total"] for c in reading["costs"].values())
    classes = class_table(reading)
    stages = stage_table(reading)
    matrix = origin_matrix(reading)
    check("sc7 nothing is lost or counted twice: the stages as billed, the classes, and the "
          "content view's rows and columns each sum to the priced total (%.9f)" % billed,
          _close(sum(r["usd"] for r in stages.values()), billed)
          and _close(sum(r["total"] for r in classes.values()), billed)
          and _close(sum(sum(r.values()) for r in matrix.values()), billed)
          and all(_close(sum(r[k] for r in matrix.values()), classes[k]["total"])
                  for k in CLASSES))

    code_out = reading["costs"]["msg_e2"]["out"]
    check("sc21 output that WRITES code is per file and the rest is the stage's own work: "
          "the one request that edits a file is the whole of the file class's output "
          "(%.9f), and its text is not" % code_out,
          code_out > 0 and _close(classes["file"]["out"], code_out)
          and _close(classes["task"]["out"] + classes["run"]["out"] + code_out,
                     sum(c["out"] for c in reading["costs"].values())))

    loud = largest_outputs(reading, 2)
    check("sc20 the largest output is named by what was emitted - here the executor brief, "
          "the biggest thing the main loop typed - and ranked first: %r"
          % ([(r["stage"], r["emitted"]) for r in loud],),
          loud and loud[0]["stage"] == "plan"
          and any("brief for audit:audit-executor" in e for e in loud[0]["emitted"]))

    reads_paid = sum(c["cr"] for c in reading["costs"].values())
    carried = sum(i["carryUSD"] for i in reading["content"]["items"])
    starts = dict((k, (c["startRead"], c["startWrite"]))
                  for k, c in reading["content"]["contexts"].items())
    check("sc8 every cache read is a carry of some written content: the carries sum to the "
          "read cost exactly, with nothing left unexplained, when the identity holds - and "
          "each context's start is reported as recorded, what it found cached and what it "
          "wrote: %r" % (starts,),
          _close(carried, reads_paid)
          and all(c["identityBreaks"] == 0 for c in reading["content"]["contexts"].values())
          and starts == {MAIN: (100, 50), "t4": (0, 500), "t8": (0, 400)})

    broken = [list(step) for step in flow]
    for step in broken:
        if step[0] == "req" and step[1] == "m6":
            step[4] = 1400
    torn = analyse(_fx_events([tuple(s) for s in broken], result=False))
    carried = sum(i["carryUSD"] for i in torn["content"]["items"])
    gap = sum(c["unexplainedReadUSD"] for c in torn["content"]["contexts"].values())
    paid = sum(c["cr"] for c in torn["costs"].values())
    check("sc9 a context whose reads break the identity is REPORTED as breaks and an "
          "unexplained amount, and carry plus that amount still equals what was paid - "
          "a reset of the running prediction would double-count every later read",
          sum(c["identityBreaks"] for c in torn["content"]["contexts"].values()) >= 1
          and gap < 0 and _close(carried + gap, paid))

    check("sc10 with no result event, output is NOT priced and the report says so, rather "
          "than pricing the stream's emit-time counts as if they were measured",
          torn["output"] is None
          and all(c["out"] is None for c in torn["costs"].values())
          and "not measured" in render(torn))

    text = render(reading)
    check("sc11 no recorded path leaves the tool: the plugin root reads <plugin>, the "
          "working directory <repo>, any other home path <abs>",
          _FX_HOME not in text and "<plugin>" in text and "<repo>" in text
          and _FX_HOME not in json.dumps(as_json(reading)))

    roots = [_FX_PLUGIN]
    shapes = [
        ({"name": "Bash", "input": {"command": "cat src/a.rb"}}, True, "file"),
        ({"name": "Bash", "input": {"command": "git diff -- src && head -3 src/b.rb"}}, True,
         "file"),
        ({"name": "Bash", "input": {"command": "cat docs/audit/audit-plan.json"}}, True, "task"),
        ({"name": "Bash", "input": {"command": "cat src/a.rb && python3 -m unittest"}}, True,
         "task"),
        ({"name": "Read", "input": {"file_path": _FX_PLUGIN + "/reference/a.md"}}, True, "run"),
        ({"name": "Read", "input": {"file_path": _FX_PLUGIN + "/reference/a.md"}}, False,
         "task"),
        ({"name": "Read", "input": {"file_path": _FX_REPO + "/src/a.rb"}}, False, "file"),
        # Plan state reached by the file tools rather than by a shell command: these
        # are what an orchestrator does to the plan, and the tool name alone says file.
        ({"name": "Read", "input": {"file_path": _FX_REPO + "/docs/audit/audit-plan.json"}},
         True, "task"),
        ({"name": "Edit", "input": {"file_path": _FX_REPO + "/docs/audit/audit-plan.json",
                                    "old_string": "a", "new_string": "b"}}, True, "task"),
        ({"name": "Read", "input": {"file_path": _FX_REPO + "/docs/audit/phases/first.json"}},
         False, "task"),
        # ...and the twin that keeps the plan-state rule from swallowing every edit.
        ({"name": "Edit", "input": {"file_path": _FX_REPO + "/src/a.rb", "old_string": "a",
                                    "new_string": "b"}}, False, "file"),
    ]
    wrong = [(tool["input"], in_main, want, classify(tool, in_main, roots))
             for tool, in_main, want in shapes if classify(tool, in_main, roots) != want]
    check("sc12 content classes: a command that only looks at project files is a file read, "
          "one that also runs anything is task work, plan state is task work whether a "
          "command, a Read or an Edit reaches it, and plugin prose is fixed per run in the "
          "main loop only: %r" % (wrong,), not wrong)

    wall = reading["wall"]
    check("sc13 wall clock partitions the span, a tool result's wait goes to the stage that "
          "called it and a hand-back's to its agent: %r" % (wall["byStage"],),
          _close(sum(wall["byStage"].values()), wall["span"])
          and wall["byStage"] == {"orient": 3.0, "plan": 3.0, "executor": 6.0, "gate": 3.0,
                                  "reviewer": 4.0, "close": 3.0})

    plain = [s for s in flow if not (s[0] == "req" and s[2])]
    plain = [s for s in plain if not (s[0] in ("res", "brief") and s[1] in ("t4", "t8"))
             and not (s[0] == "res" and s[3])]
    plain = [s if s[0] != "req" else s[:7] + ([b for b in s[7] if b.get("name") != "Agent"],)
             for s in plain]
    alone = analyse(_fx_events(plain, roots=False, result=False))
    check("sc14 a session with no plugin and no dispatch reads as one stage, `main` - "
          "not as orient or plan, which would describe a pipeline it never ran: %r"
          % (sorted(set(alone["stages"].values())),),
          set(alone["stages"].values()) == {"main"})

    scripted = [list(s) for s in flow]
    scripted[0][7] = [{"type": "tool_use", "id": "t1", "name": "Bash",
                       "input": {"command": 'python3 "%s/scripts/status/audit-status.py"' % _FX_PLUGIN}}]
    early = analyse(_fx_events([tuple(s) for s in scripted]))
    check("sc15 THE OVER-FIRE TWIN of orient: a first call that RUNS a plugin script is plan "
          "work, so orient ends before it rather than swallowing it: %r"
          % (early["stages"]["msg_m1"],), early["stages"]["msg_m1"] == "plan")

    import tempfile
    from _suite import remove_tree
    scratch = tempfile.mkdtemp(prefix="stream-cost-")
    try:
        path = os.path.join(scratch, "stream.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "system"}) + "\n{not json\n")
        try:
            load_events(path)
            raised = None
        except ValueError as exc:
            raised = str(exc)
        import io
        said, real = io.StringIO(), sys.stderr
        sys.stderr = said
        try:
            code = main([path])
        finally:
            sys.stderr = real
        check("sc16 a torn line is an error naming the line, and the command exits 2 saying "
              "so on stderr - a stream with a line missing is a stream whose totals cannot "
              "be trusted: %r" % (raised,),
              raised is not None and "line 2" in raised and code == 2
              and "line 2" in said.getvalue())
    finally:
        remove_tree(scratch)

    two = [list(s) for s in flow]
    for step in two:
        if step[0] == "req" and step[2] == "t4":
            step[3] = _FX_SONNET
    shared = analyse(_fx_events([tuple(s) for s in two], result=False))
    shared["session"]["result"] = _fx_result()
    usage = shared["session"]["result"]["modelUsage"]
    usage[_FX_SONNET] = {"inputTokens": _FX_EXE["in"] + _FX_REV["in"],
                         "cacheCreationInputTokens": _FX_EXE["cw"] + _FX_REV["cw"],
                         "cacheReadInputTokens": _FX_EXE["cr"] + _FX_REV["cr"],
                         "outputTokens": _FX_EXE["out"] + _FX_REV["out"], "costUSD": 0.0}
    for key, value in (("inputTokens", _FX_MAIN["in"]),
                       ("cacheCreationInputTokens", _FX_MAIN["cw"]),
                       ("cacheReadInputTokens", _FX_MAIN["cr"]),
                       ("outputTokens", _FX_MAIN["out"])):
        usage[_FX_OPUS][key] = value
    extra, notes = reconstruct(shared["session"])
    finals = dict((r["context"], r) for r in extra if r["id"].startswith("final:"))
    # The bytes each dispatch received after its last visible request, counted here from
    # the fixture's own inputs: the executor's edit and its result, the reviewer's diff
    # command and its result. An equal split would give each half of the residual.
    tail_exe = len(json.dumps({"file_path": _FX_REPO + "/src/a.rb", "old_string": "a",
                               "new_string": "b"}, sort_keys=True, separators=(",", ":"))) + 100
    tail_rev = len(json.dumps({"command": "git diff"}, separators=(",", ":"))) + 500
    want_exe = int(round(110 * tail_exe / float(tail_exe + tail_rev)))
    check("sc17 two dispatches on one model: each final's cache read comes from its own "
          "prefix, the residual write is shared out whole in proportion to the bytes each "
          "received after its last visible request (%d for the executor), and the split "
          "is labelled an estimate: %r"
          % (want_exe, [(k, v["cr"], v["cw5"]) for k, v in sorted(finals.items())]),
          finals.get("t4", {}).get("cr") == 1100 and finals.get("t8", {}).get("cr") == 400
          and finals.get("t4", {}).get("cw5") == want_exe
          and sum(r["cw5"] + r["cw1"] for r in finals.values()) == 110
          and not [r for r in extra if r["id"].startswith("residual:")]
          and sum(1 for n in notes if "[estimate]" in n) == 2)

    exe2 = _fx_input({"description": "d2", "subagent_type": "audit:audit-executor"}, 300)
    second = list(flow) + [
        ("req", "m9", None, _FX_OPUS, 1710, 20, "1h",
         [{"type": "tool_use", "id": "t11", "name": "Agent", "input": exe2}]),
        ("brief", "t11"),
        ("req", "e9", "t11", _FX_OPUS, 0, 400, "5m", [{"type": "text", "text": "ok"}]),
        ("res", "t11", 100, None),
        ("req", "m10", None, _FX_OPUS, 1730, 30, "1h", [{"type": "text", "text": "done"}]),
    ]
    again = analyse(_fx_events(second, result=False))
    got = (again["stages"]["msg_m8"], again["stages"]["msg_m9"], again["stages"]["msg_e9"],
           again["stages"]["msg_m10"])
    check("sc18 a second task's dispatch, made from close, is plan work, and the main loop "
          "is back in gate once that executor hands back - the stage machine does not "
          "stop at the first task: %r" % (got,),
          got == ("close", "plan", "executor", "gate"))

    # A residual that is NOT what the prefix identity predicts. The amount is one no
    # other figure in the fixture carries, so a verdict that printed some other
    # difference could not pass by coincidence.
    skew = 37
    off = analyse(_fx_events(flow, result=_fx_result(rev={"cr": _FX_REV["cr"] + skew})))
    rev_notes = [n for n in off["notes"] if n.startswith("dispatch t8: final request")]
    rev_final = [r for r in off["requests"] if r["id"] == "final:t8"]
    rev_ctx = off["content"]["contexts"]["t8"]
    check("sc22 a rebuilt final request whose modelUsage read is off from the prefix "
          "identity by %d prints DIFFERS by that amount and never the agrees verdict, keeps "
          "the residual it was billed rather than the prediction, and the content view "
          "carries the same %d as an identity break: %r"
          % (skew, skew, (rev_notes, [r["cr"] for r in rev_final], rev_ctx["identityBreaks"])),
          len(rev_notes) == 1 and "(DIFFERS by %d)" % skew in rev_notes[0]
          and "agrees" not in rev_notes[0]
          and sum(1 for n in off["notes"] if "(agrees)" in n) == 1
          and [r["cr"] for r in rev_final] == [_FX_REV["cr"] + skew]
          and rev_ctx["identityBreaks"] == 1
          and _close(rev_ctx["unexplainedReadUSD"], skew * _rate(_FX_SONNET, "cacheR")))

    hour = [list(s) for s in flow]
    for step in hour:
        if step[0] == "req" and step[2] == "t4":
            step[6] = "1h"
    held = analyse(_fx_events([tuple(s) for s in hour], result=_fx_result(exe_ttl="1h")))
    exe_final = [(r["cw1"], r["cw5"]) for r in held["requests"] if r["id"] == "final:t4"]
    exe_notes = [n for n in held["notes"] if n.startswith("dispatch t4: final request")]
    rows_hour, _t = reconciliation(held)
    check("sc23 a subagent that writes at the one-hour rate has its rebuilt final request "
          "written at that rate too - modelUsage carries one write total and no split, so "
          "the rebuild takes the dispatch's own - and the session still prices to every "
          "model's costUSD: %r" % ((exe_final, exe_notes, rows_hour),),
          exe_final == [(50, 0)] and len(exe_notes) == 1
          and "(1h)" in exe_notes[0]
          and all(told is not None and abs(priced - told) < 1e-9
                  for _m, priced, told in rows_hour))

    edited = [list(s) for s in flow]
    for step in edited:
        if step[0] == "req" and step[1] == "m3":
            step[7] = [{"type": "tool_use", "id": "t3", "name": "Edit",
                        "input": {"file_path": _FX_REPO + "/docs/audit/audit-plan.json",
                                  "old_string": "pending", "new_string": "in_progress"}}]
    planned = analyse(_fx_events([tuple(s) for s in edited]))
    from_edit = [(i["class"], i["source"]) for i in planned["content"]["items"]
                 if i["request"] == "msg_m4"]
    plan_classes = class_table(planned)
    check("sc24 the bytes the main loop emits editing the plan are task work, in the content "
          "view and in the output split, as the plan read they replace is - not file work "
          "because the tool that typed them writes a file; the executor's code edit stays "
          "the whole of the file class's output: %r" % (from_edit,),
          from_edit and all(kind == "task" for kind, _src in from_edit)
          and sum(1 for _k, src in from_edit if src == WRITE_LABEL["task"]) == 1
          and planned["content"]["contexts"][MAIN]["heldByClass"]["file"] == 0
          and planned["costs"]["msg_e2"]["out"] > 0
          and _close(plan_classes["file"]["out"], planned["costs"]["msg_e2"]["out"]))

    stretched = _fx_stretched(flow)
    two = analyse(_fx_events(stretched, result=_fx_ends(_FX_STRETCHES)))
    one = analyse(_fx_events(flow, result=_fx_ends((_FX_MAIN,))))
    rows_two, total_two = reconciliation(two)
    shares = (_fx_main_out(two, ("m1", "m2", "m3", "m4")),
              _fx_main_out(two, ("m5", "m6", "m7", "m8")))
    whole_share = _fx_main_out(one, ("m1", "m2", "m3", "m4"))
    agreed = ["main loop, stretch %d of 2: result.usage agrees with the stream's own "
              "requests (in, cacheW, cacheR)" % k for k in (1, 2)]
    text = render(two)
    check("sc25 a session re-invoked once - two stretches, each with its own init and its own "
          "result, both results at the end - reads as the hand-worked answer: every token in "
          "the stage of the request that paid it and none unattributed, each stretch's main "
          "loop agreeing with its own result, each stretch's output its own measured pool "
          "(500 and 400, where one pool split by bytes gives the first %.1f), every model "
          "priced to its costUSD, and the header saying two results were read. Keeping the "
          "last result alone reads the first stretch as a gap of negative tokens: %r"
          % (whole_share, (_fx_stage_totals(two), shares)),
          _fx_stage_totals(two) == _FX_EXPECTED
          and two["session"]["result"]["usage"] == {
              "input_tokens": _FX_MAIN["in"], "cache_creation_input_tokens": _FX_MAIN["cw"],
              "cache_read_input_tokens": _FX_MAIN["cr"], "output_tokens": _FX_MAIN["out"]}
          and not [r for r in two["requests"] if r["id"].startswith("residual:")]
          and [n for n in two["notes"] if n.startswith("main loop")] == agreed
          and _close(shares[0], 500) and _close(shares[1], 400)
          and not _close(whole_share, 500)
          and len(rows_two) == 2
          and all(told is not None and abs(priced - told) < 1e-9 for _m, priced, told in rows_two)
          and "2 result events, one per stretch, duration_ms and num_turns summed" in text
          and "duration_ms summed over the stretches is 5.0s" in text
          and "before the first one" not in text)

    def rebuilt_of(r):
        return sorted((q["id"], q["in"], q["cw5"], q["cw1"], q["cr"])
                      for q in r["requests"] if q["reconstructed"])
    rows_one, total_one = reconciliation(one)
    check("sc26 THE SINGLE-RESULT TWIN: the same session with ONE result carrying the same "
          "totals reads the same wherever the output split does not reach - every stage's "
          "tokens, every rebuilt final request, every model's price and costUSD, the total "
          "cost and the total output. Summing modelUsage or total_cost_usd, which every "
          "result repeats, would count each subagent once per stretch: %r"
          % ((rebuilt_of(two), rows_two, total_two),),
          _fx_stage_totals(two) == _fx_stage_totals(one) == _FX_EXPECTED
          and rebuilt_of(two) == rebuilt_of(one) and len(rebuilt_of(one)) == 2
          and [(m, t) for m, _p, t in rows_two] == [(m, t) for m, _p, t in rows_one]
          and all(_close(a[1], b[1]) for a, b in zip(rows_two, rows_one))
          and total_one and total_two == total_one
          and _close(sum(two["output"].values()), sum(one["output"].values())))

    skew = 37
    traded = (dict(_FX_STRETCHES[0], cr=_FX_STRETCHES[0]["cr"] - skew),
              dict(_FX_STRETCHES[1], cr=_FX_STRETCHES[1]["cr"] + skew))
    off = analyse(_fx_events(stretched, result=_fx_ends(traded)))
    gaps = sorted((r["id"], r["cr"]) for r in off["requests"] if r["id"].startswith("residual:"))
    told_off = [n for n in off["notes"] if n.startswith("main loop, stretch ")
                and "DISAGREE by in=0 cacheW=0 cacheR=" in n]
    check("sc27 each stretch's main loop is held to its own result: two results that trade "
          "%d cache-read tokens, their sum still the main loop's, print a gap in each "
          "stretch, -%d and +%d, where a check of the sum alone passes: %r"
          % (skew, skew, skew, (gaps, told_off)),
          gaps == [("residual:main:1", -skew), ("residual:main:2", skew)]
          and len(told_off) == 2)

    unpaired = analyse(_fx_events(flow, result=_fx_ends(_FX_STRETCHES)))
    why = [n for n in unpaired["notes"] if "result events 2, init events 1 - " in n]
    check("sc28 two results with one init cannot be placed stretch by stretch, and the "
          "reconstruction SAYS so; the main loop is held to the summed usage, which it meets, "
          "and its output is one pool, as with one result. The paired session of sc25 says "
          "nothing of the kind: %r" % (why,),
          len(why) == 1
          and not [r for r in unpaired["requests"] if r["id"].startswith("residual:")]
          and [n for n in unpaired["notes"] if n.startswith("main loop: result.usage")]
          == ["main loop: result.usage agrees with the stream's own requests (in, cacheW, "
              "cacheR)"]
          and all(_close(unpaired["output"][k], one["output"][k]) for k in one["output"])
          and not [n for n in two["notes"] if "init events" in n])

    drifted = _fx_ends(_FX_STRETCHES)
    drifted[0]["modelUsage"][_FX_OPUS]["inputTokens"] -= 1
    odd = analyse(_fx_events(stretched, result=drifted))
    loud = [n for n in odd["notes"] if "DISAGREE on modelUsage or total_cost_usd" in n]
    same = [n for n in two["notes"] if "the same in every one, are read once" in n]
    check("sc29 results that disagree on the session totals they repeat are REPORTED, and "
          "the last is the one read; results that agree say so, and never the first: %r"
          % ((loud, same),),
          len(loud) == 1 and _fx_stage_totals(odd) == _FX_EXPECTED
          and len(same) == 1
          and not [n for n in two["notes"] if "DISAGREE on modelUsage" in n])
    _span_cases(check)


# --- selftest: spans, injected bodies and background agents ------------------------
_FX_TASK = 'python3 "%s/scripts/manifest/audit-task.py"' % _FX_PLUGIN


def _fx_bash(command):
    return ("Bash", {"command": command})


def _fx_verb(text):
    return _fx_bash("%s %s" % (_FX_TASK, text))


_FX_PLAN = ("Skill", {"skill": "audit:phase", "args": "add"})
_FX_RUN = ("Skill", {"skill": "audit:phase", "args": "P1"})
_FX_PREFLIGHT = _fx_bash('python3 "%s/scripts/status/audit-status.py" docs/audit/audit-plan.json'
                         % _FX_PLUGIN)
_FX_LAND = _fx_bash('python3 "%s/scripts/git/close-phase.py" docs/audit/audit-plan.json P1'
                    % _FX_PLUGIN)
_FX_RELEASE = _fx_bash('python3 "%s/scripts/governance/audit-lock.py" release phase-P1'
                       % _FX_PLUGIN)


def _fx_main_only(steps):
    """A main-loop-only flow: one request per entry of `steps`, each a list of
    (tool name, input) calls, every call answered with a small result."""
    flow, cr = [], 100
    for n, calls in enumerate(steps):
        blocks = [{"type": "tool_use", "id": "c%d_%d" % (n, k), "name": name, "input": data}
                  for k, (name, data) in enumerate(calls)]
        flow.append(("req", "s%d" % n, None, _FX_OPUS, cr, 10, "1h",
                     blocks or [{"type": "text", "text": "ok"}]))
        flow.extend(("res", "c%d_%d" % (n, k), 20, None) for k in range(len(calls)))
        cr += 10
    return flow


def _fx_spans(steps):
    reading = analyse(_fx_events(_fx_main_only(steps), result=False))
    spread = spans(reading)
    return reading, spread


def _fx_numbers(spread, name):
    return [i + 1 for i, s in enumerate(spread["span"]) if s == name]


def _fx_launch(background, handback):
    """The twin pair for a background launch: one executor and one reviewer, both on
    the same model, so a rebuild that predicted a final for the executor would take its
    read from the prefix identity rather than from the model's residual. The executor's
    final request is in the stream only when it ran in the background, and its
    hand-back then is the launch notice; the result event is the same in both."""
    exe = {"description": "d", "subagent_type": "audit:audit-executor"}
    rev = {"description": "r", "subagent_type": "audit:audit-reviewer"}
    t = lambda tid, name, data: {"type": "tool_use", "id": tid, "name": name, "input": data}  # noqa: E731
    look = {"command": "git diff"}
    flow = [("req", "m1", None, _FX_OPUS, 100, 50, "1h", [t("tX", "Agent", exe)]),
            ("brief", "tX"),
            ("req", "x1", "tX", _FX_SONNET, 0, 500, "5m", [t("x1t", "Bash", look)]),
            ("res", "x1t", 300, "tX"),
            ("req", "x2", "tX", _FX_SONNET, 500, 100, "5m", [t("x2t", "Bash", look)]),
            ("res", "x2t", 300, "tX")]
    if background:
        flow.append(("req", "x3", "tX", _FX_SONNET, 600, 60, "5m",
                     [{"type": "text", "text": "z" * len(handback)}]))
    flow += [("res", "tX", (LAUNCH_NOTICE + " agentId: a1") if background else handback, None),
             ("req", "m2", None, _FX_OPUS, 150, 40, "1h", [t("tR", "Agent", rev)]),
             ("brief", "tR"),
             ("req", "r1", "tR", _FX_SONNET, 0, 400, "5m", [t("r1t", "Bash", look)]),
             ("res", "r1t", 300, "tR"),
             ("res", "tR", "w" * len(handback), None),
             ("req", "m3", None, _FX_OPUS, 190, 20, "1h", [{"type": "text", "text": "done"}])]
    main = {"in": 6, "cw": 110, "cr": 440, "out": 300}
    sonnet = {"in": 10, "cw": 1120, "cr": 1500, "out": 200}

    def cost(model, row, w5, w1):
        return _usage_core.price({"in": row["in"], "cacheW5m": w5, "cacheW1h": w1,
                                  "cacheR": row["cr"], "out": row["out"]}, model)
    end = {"type": "result", "subtype": "success", "uuid": "u-result", "duration_ms": 9000,
           "num_turns": 3,
           "usage": {"input_tokens": main["in"], "cache_creation_input_tokens": main["cw"],
                     "cache_read_input_tokens": main["cr"], "output_tokens": main["out"]},
           "modelUsage": {
               _FX_OPUS: {"inputTokens": main["in"], "cacheCreationInputTokens": main["cw"],
                          "cacheReadInputTokens": main["cr"], "outputTokens": main["out"],
                          "costUSD": cost(_FX_OPUS, main, 0, main["cw"])},
               _FX_SONNET: {"inputTokens": sonnet["in"],
                            "cacheCreationInputTokens": sonnet["cw"],
                            "cacheReadInputTokens": sonnet["cr"],
                            "outputTokens": sonnet["out"],
                            "costUSD": cost(_FX_SONNET, sonnet, sonnet["cw"], 0)}}}
    end["total_cost_usd"] = sum(r["costUSD"] for r in end["modelUsage"].values())
    return analyse(_fx_events(flow, result=end))


def _fx_context_usd(reading, context):
    return sum(reading["costs"][r["id"]]["total"] for r in reading["requests"]
               if r["context"] == context)


def _span_cases(check):
    calls = script_calls('S=/p/scripts/manifest/audit-task.py; python3 $S done P1.1 --commit c'
                         '\nT="python3 /p/scripts/manifest/audit-task.py"\n$T add "a b" --phase P1'
                         '\nfor t in P1.2 P1.3; do python3 "${PL}/x/audit-task.py" start $t; done'
                         '\npython3 /p/audit-task.py done --help; python3 /p/audit-task.py start $u')
    check("sp1 a verb and its operand are read off the words after the script, through a path "
          "held in a variable, a variable holding the whole command, and a loop over task "
          "ids; a flag or an unreadable variable is no operand: %r" % (calls,),
          calls == [("audit-task.py", "done", "P1.1"), ("audit-task.py", "add", "a b"),
                    ("audit-task.py", "start", "P1.2"), ("audit-task.py", "start", "P1.3"),
                    ("audit-task.py", "done", None), ("audit-task.py", "start", None)])
    quoted = script_calls("echo 'audit-task.py done P1.1' && grep -n done audit-task.md")
    check("sp2 THE OVER-FIRE TWIN: the verb's name inside a quoted string or a grep pattern "
          "is not a call - only a word naming the script is: %r" % (quoted,), quoted == [])

    # The reference read is in planning's last request, so the write that holds it falls
    # at the first request after planning: a reading by the holding request's span
    # would put it outside planning.
    shared = [[_FX_PLAN], [_fx_verb('add-phase "x" --outcome y')],
              [_fx_verb('add "one" --phase P1')],
              [_fx_verb('add "two" --phase P1'),
               ("Read", {"file_path": _FX_PLUGIN + "/reference/a.md"})]]
    tail = [[_fx_verb("start P1.1")], [_fx_verb("done P1.1 --commit c")], [_FX_RELEASE]]
    gap, spread_gap = _fx_spans(shared + [[_FX_RUN], [_FX_PREFLIGHT]] + tail)
    flat, spread_flat = _fx_spans(shared + tail)
    got = (_fx_numbers(spread_gap, "planning"), _fx_numbers(spread_flat, "planning"),
           _fx_numbers(spread_gap, "before the cycle"))
    check("sp3 THE PLANNING TWIN: a run whose second Skill call and preflight sit between the "
          "last add and the first start, and one whose start follows the last add, hold the "
          "same planning row; the requests between fall in neither span. A rule that closed "
          "planning at the start would put them in the first: %r" % (got,),
          got == ([1, 2, 3, 4], [1, 2, 3, 4], [5, 6]))
    reads = reference_reads(gap, spread_gap)
    check("sp4 a reference read is summed in the span of the request that made it, not the "
          "one whose cache write held it: %r" % (reads,),
          dict((k, v[0]) for k, v in reads.items()) == {"planning": 1})

    work = [[_fx_verb("start P1.1")], [_fx_verb("done P1.1 --commit c")],
            [_fx_verb("start P1.2")], [_fx_verb("done P1.2 --commit c")]]
    # A request between the landing and the lock release, so a close read from the
    # release alone starts one request later than the close read from the landing.
    close = [[_fx_verb("signoff P1 --verdict passed")], [_FX_LAND], [_fx_bash("git log -1")],
             [_FX_RELEASE]]
    fixed, spread_fixed = _fx_spans(work + [[_fx_verb('add "fix" --phase P1')],
                                            [_fx_verb("start P1.3-fcb")],
                                            [_fx_verb("done P1.3-fcb --commit c")]] + close)
    plain, spread_plain = _fx_spans(work + close)
    got = [(s["found"]["lo"], s["found"]["hi"], s["found"]["tasks"])
           for s in (spread_fixed, spread_plain)]
    parts = [(_fx_numbers(s, "fix task"), _fx_numbers(s, "sign-off"), _fx_numbers(s, "close"))
             for s in (spread_fixed, spread_plain)]
    check("sp5 THE SIGN-OFF TWIN: a phase whose sign-off adds and runs a fix task after the "
          "last task's done, and one that adds none, hold the same cycle and tasks; what "
          "follows is sign-off, the fix task and the close, the close from the request after "
          "the landing. A rule that closed the cycle at the last done would swallow the fix "
          "task: %r" % ((got, parts, spread_fixed["found"]["doneAfter"]),),
          got == [(0, 3, ["P1.1", "P1.2"]), (0, 3, ["P1.1", "P1.2"])]
          and parts == [([5, 6, 7], [8, 9], [10, 11]), ([], [5, 6], [7, 8])]
          and spread_fixed["found"]["doneAfter"] == [(6, "P1.3-fcb")])

    helped, spread_help = _fx_spans([[_fx_verb("start P1.1")], [_fx_verb("done --help")]])
    closed, spread_closed = _fx_spans([[_fx_verb("start P1.1")], [_fx_verb("done --help")],
                                       [_fx_verb("done P1.1")]])
    text = "\n".join(render_spans(helped))
    check("sp6 `done --help` names no task, so it closes nothing: a cycle with only that after "
          "its start prints that it never closed, and the twin with a real done after it "
          "closes there: %r" % ((spread_help["found"]["why"], spread_closed["found"]["hi"]),),
          spread_help["found"]["hi"] is None and "never closed" in text
          and _fx_numbers(spread_help, "unclosed cycle") == [1, 2]
          and spread_closed["found"]["hi"] == 2
          and spread_closed["found"]["tasks"] == ["P1.1"])

    denied, spread_denied = _fx_spans([[_FX_PLAN], [_fx_bash("ls")], [_fx_bash("cat src/a.rb")]])
    text = "\n".join(render_spans(denied))
    check("sp7 a session whose only planning is one Skill call and which starts nothing has a "
          "planning row of that one request and no task cycle, said in words - a rule that "
          "closed planning only at a start would read every request as planning: %r"
          % (_fx_numbers(spread_denied, "planning"),),
          _fx_numbers(spread_denied, "planning") == [1]
          and _fx_numbers(spread_denied, "outside any cycle") == [2, 3]
          and "no task cycle" in text and cycle_reading(denied, spread_denied) is None
          and "task cycle [" not in text)

    plain_twin = analyse(_fx_events(_fx_session()))
    cyc_none = spans(plain_twin)["found"]["why"]
    check("sp8 the known-answer session calls no start through the task script, so it has no "
          "cycle, rather than a cycle of nothing: %r" % (cyc_none,),
          cyc_none is not None and "no task cycle" in cyc_none)

    handback = "h" * 640
    fore = _fx_launch(False, handback)
    back = _fx_launch(True, handback)
    prices = [(_fx_context_usd(r, "tX"), _fx_context_usd(r, "tR")) for r in (fore, back)]
    phantom = [r["id"] for r in back["requests"] if r["id"].startswith(("final:tX", "residual:"))]
    rows = [(d["type"], d["background"], d["rebuilt"]) for d in dispatches(back, spans(back))]
    check("sp9 THE LAUNCH TWIN: an agent launched in the background, whose last request the "
          "stream shows and whose tool result is the launch notice, is priced as the same "
          "agent run in the foreground with its final rebuilt - no phantom final, no "
          "unattributed row, and the dispatch says how it was launched: %r"
          % ((prices, phantom, rows),),
          _close(prices[0][0], prices[1][0]) and _close(prices[0][1], prices[1][1])
          and not phantom
          and not [r for r in fore["requests"] if r["id"].startswith("residual:")]
          and rows == [("audit:audit-executor", True, 0), ("audit:audit-reviewer", False, 1)]
          and _close(sum(c["total"] for c in fore["costs"].values()),
                     sum(c["total"] for c in back["costs"].values())))

    body = "B" * 4000
    flow = [("req", "m1", None, _FX_OPUS, 100, 50, "1h",
             [{"type": "tool_use", "id": "k1", "name": "Skill",
               "input": {"skill": "audit:phase", "args": "add"}}]),
            ("res", "k1", "Launching skill: audit:phase", None), ("text", body),
            ("req", "m2", None, _FX_OPUS, 150, 1500, "1h",
             [{"type": "tool_use", "id": "k2", "name": "Bash", "input": {"command": "ls"}}]),
            ("res", "k2", 30, None), ("text", "u" * 300),
            ("req", "m3", None, _FX_OPUS, 1650, 120, "1h", [{"type": "text", "text": "ok"}])]
    sized = analyse(_fx_events(flow, result=False))
    rows = sorted((i["source"], i["class"], i["bytes"]) for i in sized["content"]["items"]
                  if i["source"] in ("command body: audit:phase", "user text"))
    held = sum(i["tokens"] for i in sized["content"]["items"] if i["request"] == "msg_m2")
    check("sp10 a command body a Skill call injects is a source of its own, sized by its bytes "
          "and fixed per run, and a user text block after any other call is user text; the "
          "write that held it still sums to what was billed (%.1f of 1500): %r" % (held, rows),
          rows == [("command body: audit:phase", "run", 4000), ("user text", "task", 300)]
          and _close(held, 1500)
          and [n for n, _l, _b in injections(sized["session"])] == [1, 2])

    session = {"requests": [{"context": MAIN, "at": 10.0}, {"context": MAIN, "at": 15.0},
                            {"context": MAIN, "at": 27.0}, {"context": "a", "at": 12.0},
                            {"context": "a", "at": 13.5}, {"context": "b", "at": 14.0}]}
    gaps = context_gaps(session)
    check("sp11 the longest gap is read per context between its own consecutive requests, "
          "with the request it followed, and a context of one request has none: %r" % (gaps,),
          gaps == {MAIN: (12.0, 2), "a": (1.5, 1), "b": None})
    _driver_span_cases(check)


_FX_DRIVE = 'python3 "%s/scripts/governance/drive-phase.py" next P1' % _FX_PLUGIN


def _fx_driven(steps):
    """A main-loop-only flow of Bash calls, each `(command, its printed result)`."""
    flow, cr = [], 100
    for n, (command, said) in enumerate(steps):
        flow.append(("req", "d%d" % n, None, _FX_OPUS, cr, 10, "1h",
                     [{"type": "tool_use", "id": "dc%d" % n, "name": "Bash",
                       "input": {"command": command}}]))
        flow.append(("res", "dc%d" % n, said, None))
        cr += 10
    reading = analyse(_fx_events(flow, result=False))
    return reading, spans(reading)


def _driver_span_cases(check):
    # The prints are the driver's own shape: a did-line, then the instruction.
    drive = [(_FX_DRIVE, "[drive-phase] P1: started P1.1\n"
                         "dispatch audit:audit-executor P1.1 model=sonnet brief=/b/1"),
             ("ls", "x"),
             (_FX_DRIVE, "[drive-phase] P1: gate P1.1 green; stamp current\n"
                         "dispatch audit:audit-reviewer P1.1 model=sonnet brief=/b/2"),
             ("ls", "x"),
             (_FX_DRIVE, "[drive-phase] P1: closed P1.1 at abc1234; started P1.2\n"
                         "dispatch audit:audit-executor P1.2 model=sonnet brief=/b/3"),
             (_FX_DRIVE, "[drive-phase] P1: closed P1.2 at def5678\n"
                         "done P1: every task is closed; sign-off is next")]
    _r, spread = _fx_driven(drive)
    found = spread["found"]
    check("sp12 a session that drives its tasks through the step driver, calling no "
          "start or done itself, has a task cycle: from the request whose print says it "
          "started a task to the last whose print says it closed one, holding the tasks "
          "closed: %r" % ((found["lo"], found["hi"], found["tasks"]),),
          (found["lo"], found["hi"], found["tasks"]) == (0, 5, ["P1.1", "P1.2"])
          and _fx_numbers(spread, "cycle") == [1, 2, 3, 4, 5, 6])
    echoed = [("echo '[drive-phase] P1: started P1.1'",
               "[drive-phase] P1: started P1.1"),
              ("cat notes.txt", "[drive-phase] P1: closed P1.1 at abc1234"),
              (_FX_DRIVE, "decide gate-red P1.1: its recorded gate is red (GATE RED: x)")]
    _r, spread_echo = _fx_driven(echoed)
    check("sp13 THE OVER-FIRE TWIN: the driver's words in the result of a command that "
          "does not run the driver start nothing, and a driver print with no did-line "
          "starts nothing either - so no cycle: %r" % (spread_echo["found"]["why"],),
          spread_echo["found"]["lo"] is None
          and "no task cycle" in (spread_echo["found"]["why"] or ""))

    # A driven sign-off with a fix task: the review's dispatch, the triage, the fix
    # task added and started inside the driver, its close beside the triage again,
    # and the final step that signs off, lands and releases the lock.
    signed = [(_FX_DRIVE, "[drive-phase] P1: started P1.1\n"
                          "dispatch audit:audit-executor P1.1 model=sonnet brief=/b/1"),
              (_FX_DRIVE, "[drive-phase] P1: gate P1.1 green; stamp current; closed "
                          "P1.1 at abc1234\n"
                          "dispatch audit:audit-reviewer P1 model=sonnet brief=/b/2"),
              (_FX_DRIVE, "[drive-phase] P1: 1 finding(s) of the phase review filed\n"
                          "decide triage P1: the phase review returned `findings`"),
              (_FX_DRIVE, "[drive-phase] P1: fix task P1.2-fcb added for P1-R1; "
                          "started P1.2-fcb\n"
                          "dispatch audit:audit-executor P1.2-fcb model=sonnet brief=/b/3"),
              (_FX_DRIVE, "[drive-phase] P1: gate P1.2-fcb green; stamp current; "
                          "closed P1.2-fcb at def5678\n"
                          "decide triage P1: the phase review returned `findings`"),
              (_FX_DRIVE, "[drive-phase] P1: phase gate green; invariants clean; "
                          "signed off; committed 1234567; landed (audit/p1 -> main); "
                          "lock released\ndone P1: signed off (passed)")]
    _r, spread_signed = _fx_driven(signed)
    found = spread_signed["found"]
    parts = (_fx_numbers(spread_signed, "cycle"), _fx_numbers(spread_signed, "sign-off"),
             _fx_numbers(spread_signed, "fix task"), _fx_numbers(spread_signed, "close"))
    check("sp14 a driven sign-off with a fix task reads as the driver's did-words say: "
          "the cycle holds the phase's own task, the fix task runs from the request that "
          "added it to the one that closed it, the triage is sign-off, and the request "
          "that landed and released the lock is the close: %r"
          % ((found["tasks"], parts),),
          found["tasks"] == ["P1.1"]
          and parts == ([1, 2], [3], [4, 5], [6]))


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
