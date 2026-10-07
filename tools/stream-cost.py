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
    a command's output, an agent's hand-back, the session's own start), what writing
    it cost and what carrying it through every later request cost, totalled by the
    stage the content came from and by class - fixed per run, per task, per file.

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
    stream. It is rebuilt from the result event: per model, `modelUsage` minus every
    request the stream shows. With one dispatch on a model that residual IS the missing
    request; the prefix identity predicts its cache read independently, and the two are
    printed side by side. With several dispatches on one model each cache read comes
    from the identity and the residual cache write is split by the bytes that entered
    after each dispatch's last visible request - an estimate, and labelled as one.
  * Output counts in the stream are emit-time and undercount. The measured ones are the
    main loop's (`result.usage`, which the stream's own input-side sums are checked
    against) and each model's (`modelUsage`). Within such a pool, output is apportioned
    to requests by the bytes each emitted - an estimate, labelled.
  * A cache write that held content from more than one source is split across them by
    bytes - an estimate; how many writes needed it is printed.

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
    """The session as this tool reads it: requests (deduplicated by message id),
    the agent dispatches, every tool result's size, a timeline and the result event.

    An assistant event without a message id cannot be joined to a request; it is
    counted in `unjoined` rather than dropped silently.
    """
    init = next((e for e in events if e.get("type") == "system"
                 and e.get("subtype") == "init"), {})
    roots = sorted(set(p.get("path") for p in init.get("plugins") or []
                       if isinstance(p, dict) and isinstance(p.get("path"), str)
                       and os.path.isabs(p.get("path"))))
    requests, order, agents, results, calls = {}, [], {}, {}, {}
    timeline, seen, unjoined, result = [], set(), 0, None
    for event in events:
        uid = event.get("uuid")
        if uid is not None:
            if uid in seen:
                continue
            seen.add(uid)
        kind = event.get("type")
        stamp = _ts(event.get("timestamp"))
        if kind == "result":
            result = event
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
                       "emitFile": 0, "emitOther": 0, "reconstructed": False}
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
                    if tool["name"] in AGENT_TOOLS:
                        agents[tool["id"]] = {
                            "type": tool["input"].get("subagent_type") or "?",
                            "request": mid, "context": req["context"],
                            "briefBytes": _text_bytes(tool["input"].get("prompt"))}
                    if tool["name"] in WRITE_TOOLS:
                        req["emitFile"] += size
                        continue
                req["emitOther"] += size
            timeline.append((stamp, "request", mid))
        elif kind == "user":
            parent = event.get("parent_tool_use_id")
            got = False
            for block in _blocks(event):
                if block.get("type") == "tool_result":
                    got = True
                    tid = block.get("tool_use_id")
                    results[tid] = {"bytes": _text_bytes(block.get("content")),
                                    "error": bool(block.get("is_error"))}
                    timeline.append((stamp, "result", tid))
            if parent and not got:
                timeline.append((stamp, "brief", parent))
    return {"roots": roots, "cwd": init.get("cwd") or "", "init": init,
            "requests": [requests[m] for m in order], "agents": agents,
            "results": results, "calls": calls, "timeline": timeline,
            "result": result, "unjoined": unjoined}


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


def _tail_bytes(req, results):
    """Bytes that entered a context after `req`: its own output and its tools' results."""
    return (req["emitFile"] + req["emitOther"]
            + sum((results.get(t["id"]) or {}).get("bytes", 0) for t in req["tools"]))


def _pseudo(rid, context, model, counts, why):
    req = {"id": rid, "context": context, "model": model, "tools": [], "emitFile": 0,
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
    usage_main = result.get("usage") or {}
    main_reqs = [r for r in reqs if r["context"] == MAIN]
    seen_main = _input_side(main_reqs)
    told_main = {"in": int(usage_main.get("input_tokens") or 0),
                 "cw": int(usage_main.get("cache_creation_input_tokens") or 0),
                 "cr": int(usage_main.get("cache_read_input_tokens") or 0)}
    main_gap = dict((k, told_main[k] - seen_main[k]) for k in told_main)
    if any(main_gap.values()):
        notes.append("main loop: result.usage and the stream's own requests DISAGREE "
                     "by in=%(in)d cacheW=%(cw)d cacheR=%(cr)d; the gap is a request of "
                     "its own, stage unattributed" % main_gap)
        model = main_reqs[-1]["model"] if main_reqs else "?"
        extra.append(_pseudo("residual:main", MAIN, model,
                             {"in": main_gap["in"], "cw5": 0, "cw1": main_gap["cw"],
                              "cr": main_gap["cr"]}, "main-loop gap"))
    else:
        notes.append("main loop: result.usage agrees with the stream's own requests "
                     "(in, cacheW, cacheR)")
    usage = result.get("modelUsage") or {}
    by_model = {}
    for aid, dispatch in sorted(session["agents"].items()):
        mine = [r for r in reqs if r["context"] == aid]
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

    Pools are measured; the split inside a pool is by emitted bytes [estimate]."""
    result = session["result"]
    if result is None:
        return None, ["output not measured: no result event"]
    main = [r for r in reqs if r["context"] == MAIN and not r["id"].startswith("residual:")]
    main_out = int((result.get("usage") or {}).get("output_tokens") or 0)
    notes = ["output pool, measured: main loop %d tokens (result.usage)" % main_out]
    out = _split(main, main_out)
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
    weights = [r["emitFile"] + r["emitOther"] for r in members]
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
    out = [(stage, "file", "output: code written", prev["emitFile"]),
           (stage, own, "output: text and calls", prev["emitOther"])]
    for tool in prev["tools"]:
        size = (results.get(tool["id"]) or {}).get("bytes", 0)
        origin = agent_stage(agents[tool["id"]]["type"]) if tool["id"] in agents else stage
        out.append((origin, classify(tool, in_main, roots),
                    describe(tool, agents, redact), size))
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
    """{class: share} of what a request emitted: code written is per file, the rest is
    the stage's own work."""
    own = "run" if stage == "orient" else "task"
    emitted = req["emitFile"] + req["emitOther"]
    code = req["emitFile"] / float(emitted) if emitted else 0.0
    return {"file": code, own: 1.0 - code} if own != "file" else {"file": 1.0}


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
        rest = req["emitFile"] + req["emitOther"] - sum(
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
    if session["result"] is not None:
        lines.append("[measured] result event: total_cost_usd=%s duration_ms=%s num_turns=%s"
                     % (result.get("total_cost_usd"), result.get("duration_ms"),
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
    lines.append("  %swall_s partitions the first-to-last stream timestamp: %.1fs%s"
                 % ("* holds a rebuilt request. " if rebuilt else "", reading["wall"]["span"],
                    "" if not result.get("duration_ms") else
                    "; duration_ms adds %.1fs before the first one"
                    % (result["duration_ms"] / 1000.0 - reading["wall"]["span"])))
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
    lines.append("  %-10s %4s %6s %8s %8s %9s %9s %9s %10s"
                 % ("context", "req", "breaks", "start_cR", "start_cW", "run", "task", "file",
                    "$/request"))
    for context, info in sorted(filled["contexts"].items(), key=lambda kv: kv[0] != MAIN):
        name = MAIN if context == MAIN else agent_stage(
            session["agents"].get(context, {}).get("type"))
        held = info["heldByClass"]
        lines.append("  %-10s %4d %6d %8d %8d %9d %9d %9d %10.4f"
                     % (name, info["requests"], info["identityBreaks"], info["startRead"],
                        info["startWrite"], round(held["run"]), round(held["task"]),
                        round(held["file"]), sum(held.values()) * info["readRate"]))
    return "\n".join(lines)


def as_json(reading):
    redact = redactor(reading["session"]["roots"], reading["session"]["cwd"])
    rows, total = reconciliation(reading)
    return {"stages": stage_table(reading), "classes": class_table(reading),
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


def _fx_result(main=None, exe=None, rev=None):
    main = dict(_FX_MAIN, **(main or {}))
    exe = dict(_FX_EXE, **(exe or {}))
    rev = dict(_FX_REV, **(rev or {}))
    opus_5m, opus_1h = exe["cw"], main["cw"]

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
    stream carries; `duplicate` replays one event under its own uuid."""
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
            _kind, tid, size, parent = step
            events.append({"type": "user", "uuid": "u-res-" + tid, "timestamp": stamp(),
                           "parent_tool_use_id": parent,
                           "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                                    "content": "y" * size}]}})
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
    if result:
        events.append(_fx_result())
    return events


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
    ]
    wrong = [(tool["input"], in_main, want, classify(tool, in_main, roots))
             for tool, in_main, want in shapes if classify(tool, in_main, roots) != want]
    check("sc12 content classes: a command that only looks at project files is a file read, "
          "one that also runs anything is task work, plan state is task work, and plugin "
          "prose is fixed per run in the main loop only: %r" % (wrong,), not wrong)

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


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
