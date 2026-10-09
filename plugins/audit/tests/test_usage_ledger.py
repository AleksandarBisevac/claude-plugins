#!/usr/bin/env python3
"""
The cases for `usage_ledger.py`, moved out of it - a module loaded BY PATH.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. Here the prefix is more than a convention: nothing imports
`usage_ledger` by name - `hooks/meter-usage.py`, `_report_usage` and `audit-usage`
all reach it through `_loader.load_script("usage_ledger.py", ...)` and read
attributes off the module object. `M.` is exactly the shape those call sites use.

THREE `globals()` REBINDS HAD TO BECOME ATTRIBUTE WORK ON `M`, and they fail in two
different ways if carried literally:

  * `_home` - the `discover:` cases swap it for a lambda pointing at a fixture home
    so the ledger walk cannot escape upward. From here `globals()["_home"] = ...`
    patches a name nothing calls, `find_ledger_dir` keeps calling the real `_home()`,
    and the three cases would walk into the DEVELOPER'S OWN `~/.claude/usage` - a
    directory that exists on nearly every machine that ever ran Claude Code, which
    is the exact failure those cases exist to prevent. Silent: they would still pass
    on a machine with no such directory.
  * `rx1`/`rx2` - "is this public name served by usage_ledger?" was `n in globals()`
    because the suite WAS that namespace. It is `hasattr(M, n)` / `getattr(M, n)`
    here. This half fails loudly (every name reported missing) rather than
    quietly, and is written out anyway so the next reader does not have to
    rediscover which of the two shapes was which.

`aggregate`, `totals` and `parse_ts` are spelled `M.aggregate` and so on rather than
imported from `_usage_core`: they are re-exports, and `rx2` is the case that pins
them to being the SAME object. Reaching for `_usage_core` directly here would test
the wrong module.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import usage_ledger as M                           # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil
    import tempfile

    # --- usage normalization ----------------------------------------------
    counts = M._usage_counts({
        "input_tokens": 2, "output_tokens": 264,
        "cache_creation_input_tokens": 24813,
        "cache_creation": {"ephemeral_1h_input_tokens": 24813,
                           "ephemeral_5m_input_tokens": 0},
        "cache_read_input_tokens": 22494})
    check("usage: cache tiers split from the breakdown",
          counts["cacheW1h"] == 24813 and counts["cacheW5m"] == 0)
    fallback = M._usage_counts({"cache_creation_input_tokens": 900})
    check("usage: missing breakdown bills the whole write at the 5m rate",
          fallback["cacheW5m"] == 900 and fallback["cacheW1h"] == 0)
    # Observed in real transcripts: total 0 but the breakdown still reports a 1h
    # figure. Trusting the breakdown there inflated cache-write spend by 2,494
    # tokens across one session, so the total must clamp it.
    stale = M._usage_counts({"cache_creation_input_tokens": 0,
                           "cache_creation": {"ephemeral_1h_input_tokens": 145,
                                              "ephemeral_5m_input_tokens": 0}})
    check("usage: breakdown exceeding the total is clamped to the total",
          stale["cacheW5m"] + stale["cacheW1h"] == 0)
    partial = M._usage_counts({"cache_creation_input_tokens": 100,
                             "cache_creation": {"ephemeral_1h_input_tokens": 400,
                                                "ephemeral_5m_input_tokens": 0}})
    check("usage: over-reported 1h tier clamps without going negative",
          partial["cacheW1h"] == 100 and partial["cacheW5m"] == 0)
    check("usage: negative / garbage counts clamp to 0",
          M._usage_counts({"input_tokens": -5, "output_tokens": "x"})["in"] == 0)

    # --- attribution -------------------------------------------------------
    manifest = {"phases": [
        {"id": "P3", "title": "Sharding",
         "claim": {"sessionId": "sess-1"},
         "tasks": [
             {"id": "P3.1", "status": "done",
              "startedAt": "2026-08-06T07:00:00Z",
              "completedAt": "2026-08-06T07:30:00Z"},
             {"id": "P3.2", "status": "in_progress",
              "startedAt": "2026-08-06T07:10:00Z"},
         ]},
        {"id": "P4", "title": "Panel", "tasks": [{"id": "P4.1", "status": "pending"}]},
    ]}
    att = M.Attributor(manifest, "sess-1")
    check("attr: claimed phase found via claim.sessionId",
          att.claimed_phase is not None and att.claimed_phase["id"] == "P3")
    check("attr: subagent description yields an exact task id",
          att.attribute({"description": "P3.2 shard writer"}, None)
          == ("P3", "P3.2", "task"))
    check("attr: a task id from another phase still resolves",
          att.attribute({"description": "P4.1 panel tab"}, None)
          == ("P4", "P4.1", "task"))
    sided = {"meta": {"version": 2}, "phases": [
        {"id": "P4", "title": "Panel", "tasks": [{"id": "P4.1", "status": "pending"},
                                                 {"id": "P4.2-k7m", "status": "pending"}]}]}
    att_s = M.Attributor(sided, "sess-1")
    check("attr: a task id carrying a branch suffix is read whole - `P4.2-k7m: ...` "
          "attributes to P4.2-k7m, not to nothing",
          att_s.attribute({"description": "P4.2-k7m wire the tab"}, None)
          == ("P4", "P4.2-k7m", "task"),
          att_s.attribute({"description": "P4.2-k7m wire the tab"}, None))
    check("attr: ...and a hyphenated WORD after an unsuffixed id is not swallowed "
          "into it - `P4.1-fix the tab` is P4.1, because P4.1-fix is no task",
          att_s.attribute({"description": "P4.1-fix the tab"}, None)
          == ("P4", "P4.1", "task"),
          att_s.attribute({"description": "P4.1-fix the tab"}, None))
    check("attr: description naming no known task is ignored",
          att.attribute({"description": "Z9.9 nonsense"},
                        M.parse_ts("2026-08-06T06:00:00Z"))[2] == "phase")
    check("attr: main session outside every window -> phase",
          att.attribute({}, M.parse_ts("2026-08-06T06:00:00Z")) == ("P3", None, "phase"))
    check("attr: single matching window -> window attribution",
          att.attribute({}, M.parse_ts("2026-08-06T07:05:00Z"))
          == ("P3", "P3.1", "window"))
    check("attr: overlapping parallel windows collapse to the phase",
          att.attribute({}, M.parse_ts("2026-08-06T07:20:00Z"))
          == ("P3", None, "phase"))
    # The session that claimed a phase writes `claim.sessionId` from Bash under
    # $CLAUDE_CODE_SESSION_ID, while meter-usage identifies the session by its HOOK
    # PAYLOAD id. Those are different values in a live session, so matching only the
    # payload id can never fire — and it fails silently, as spend that stays
    # `unattributed`. Aliases exist so the reader accepts either name.
    aliased = M.Attributor(manifest, "hook-payload-id",
                         session_aliases=["sess-1"])
    check("attr: a claim written under the session's OTHER name still matches",
          aliased.claimed_phase is not None
          and aliased.claimed_phase.get("id") == manifest["phases"][0]["id"])
    check("attr: an alias never matches somebody else's claim",
          M.Attributor(manifest, "hook-payload-id",
                     session_aliases=["sess-nope"]).claimed_phase is None)
    check("attr: aliases are optional and None is not an alias",
          M.Attributor(manifest, "sess-1", session_aliases=[None, ""]).claimed_phase
          is not None)

    unclaimed = M.Attributor(manifest, "sess-other")
    check("attr: unclaimed session -> unattributed, never dropped",
          unclaimed.attribute({}, M.parse_ts("2026-08-06T07:20:00Z"))
          == (None, None, "unattributed"))
    check("attr: subagent label still works for an unclaimed session",
          unclaimed.attribute({"description": "P3.2 x"}, None)
          == ("P3", "P3.2", "task"))

    # --- author ------------------------------------------------------------
    # A FIXTURE REPOSITORY, NOT `"."`. These cases passed the PROCESS CWD as
    # the project root, so the identity they hashed was whatever the directory the
    # suite happened to be launched from carried: the developer's own address from
    # inside a checkout, and `$USER` through `resolve_author`'s fallback from
    # anywhere else. Both spellings satisfy "starts with anon- and is stable", so
    # the pair asserted the prefix and the determinism of sha256 - never that the
    # repository was read at all. Pinning `user.email` in a fixture makes the
    # expected digest a value no ambient identity can produce.
    import hashlib
    import subprocess
    authroot = _harness.fixture_root("usage-ledger-author-")
    _author_email = "fixture-author@example.invalid"
    subprocess.run(["git", "init", "-q", authroot], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=30)
    subprocess.run(["git", "-C", authroot, "config", "user.email",
                    _author_email], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=30)
    _want = "anon-" + hashlib.sha256(
        _author_email.encode("utf-8")).hexdigest()[:12]
    check("author: none mode returns None",
          M.resolve_author(authroot, "none") is None)
    h = M.resolve_author(authroot, "hash")
    check("author: hash mode is the pseudonym of the REPOSITORY's identity, "
          "and stable - the digest is the one that address produces and no "
          "other, so a lookup that read the ambient identity instead cannot "
          "match it (got %r, wanted %r)" % (h, _want),
          h == _want and h == M.resolve_author(authroot, "hash"))
    check("author: ...and email mode hands back that same address unhashed, "
          "which is what makes the digest above a claim about the repository "
          "rather than about sha256",
          M.resolve_author(authroot, "email") == _author_email)

    tmp = tempfile.mkdtemp(prefix="usage-ledger-selftest-")
    try:
        # --- scanning: the dedup trap -------------------------------------
        proj = os.path.join(tmp, "projects")
        os.makedirs(proj)
        main = os.path.join(proj, "sess-1.jsonl")

        def entry(mid, ts, out_tokens, model="claude-opus-5"):
            return json.dumps({
                "type": "assistant", "timestamp": ts, "gitBranch": "audit/p3",
                "message": {"id": mid, "model": model, "usage": {
                    "input_tokens": 1, "output_tokens": out_tokens,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 10}}})

        with open(main, "w", encoding="utf-8") as fh:
            # msg-A repeated 3x (the real-world shape), msg-B once
            for _ in range(3):
                fh.write(entry("msg-A", "2026-08-06T07:20:10.266Z", 100) + "\n")
            fh.write(entry("msg-B", "2026-08-06T07:25:00Z", 50) + "\n")
            fh.write("{ this line is not json\n")
            fh.write(json.dumps({"type": "user", "message": {}}) + "\n")

        opts = {"repo": "demo", "backfillOnFirstRun": True}
        rows, cur = M.scan_transcripts(main, "sess-1", {}, manifest, opts)
        agg = M.totals(rows)
        check("scan: repeated message.id counted ONCE (out == 150, not 350)",
              agg["out"] == 150, "got %s" % agg["out"])
        check("scan: msgs counts unique messages", agg["msgs"] == 2)
        check("scan: malformed line tolerated, scan continues", agg["in"] == 2)
        check("scan: non-assistant entries ignored", agg["tokens"] == 2 + 150 + 20)

        # --- scanning: cursor resume --------------------------------------
        rows2, cur2 = M.scan_transcripts(main, "sess-1", cur, manifest, opts)
        check("scan: re-scan with cursor yields nothing new", rows2 == [])
        with open(main, "a", encoding="utf-8") as fh:
            fh.write(entry("msg-C", "2026-08-06T08:05:00Z", 7) + "\n")
        rows3, cur3 = M.scan_transcripts(main, "sess-1", cur2, manifest, opts)
        check("scan: appended entry picked up incrementally",
              M.totals(rows3)["out"] == 7)
        check("scan: new hour lands in its own bucket",
              rows3 and rows3[0]["ts"] == "2026-08-06T08")

        # --- scanning: duplicate split across a chunk boundary -------------
        split_path = os.path.join(proj, "sess-split.jsonl")
        with open(split_path, "w", encoding="utf-8") as fh:
            fh.write(entry("msg-D", "2026-08-06T07:00:00Z", 11) + "\n")
        r_a, c_a = M.scan_transcripts(split_path, "sess-1", {}, manifest, opts)
        with open(split_path, "a", encoding="utf-8") as fh:
            fh.write(entry("msg-D", "2026-08-06T07:00:00Z", 11) + "\n")
        r_b, _ = M.scan_transcripts(split_path, "sess-1", c_a, manifest, opts)
        check("scan: duplicate spanning two scans is caught by the recent ring",
              M.totals(r_a + r_b)["out"] == 11,
              "got %s" % M.totals(r_a + r_b)["out"])

        # --- scanning: partial trailing line -------------------------------
        partial = os.path.join(proj, "sess-partial.jsonl")
        with open(partial, "w", encoding="utf-8") as fh:
            fh.write(entry("msg-E", "2026-08-06T07:00:00Z", 5) + "\n")
            fh.write(entry("msg-F", "2026-08-06T07:00:00Z", 5)[:20])  # torn
        r_p, c_p = M.scan_transcripts(partial, "sess-1", {}, manifest, opts)
        check("scan: torn trailing line is not consumed",
              M.totals(r_p)["out"] == 5)
        with open(partial, "a", encoding="utf-8") as fh:
            fh.write(entry("msg-F", "2026-08-06T07:00:00Z", 5)[20:] + "\n")
        r_p2, _ = M.scan_transcripts(partial, "sess-1", c_p, manifest, opts)
        check("scan: completed line is picked up on the next pass",
              M.totals(r_p2)["out"] == 5)

        # --- scanning: a streaming partial, then the final entry -----------
        # The shape a real subagent transcript wrote: one message id twice, first
        # with stop_reason null and the output count of the first streamed
        # tokens, then with the stop reason and the real count. Input and cache
        # fields are the same on both entries, so a fix that counted both would
        # show up as a doubled `in`.
        def streamed(mid, out_tokens, stop):
            return json.dumps({
                "type": "assistant", "timestamp": "2026-08-06T07:30:00Z",
                "gitBranch": "audit/p3",
                "message": {"id": mid, "model": "claude-haiku-4-5",
                            "stop_reason": stop, "usage": {
                                "input_tokens": 2306, "output_tokens": out_tokens,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 0}}})

        one_scan = os.path.join(proj, "sess-stream.jsonl")
        with open(one_scan, "w", encoding="utf-8") as fh:
            fh.write(streamed("msg-S", 3, None) + "\n")
            fh.write(streamed("msg-S", 164, "tool_use") + "\n")
        r_s, _ = M.scan_transcripts(one_scan, "sess-1", {}, manifest, opts)
        t_s = M.totals(r_s)
        check("sf1 a streaming partial followed by its final entry is counted "
              "once, at the final entry's output tokens (164, not the partial's 3)",
              (t_s["out"], t_s["in"], t_s["msgs"]) == (164, 2306, 1),
              (t_s["out"], t_s["in"], t_s["msgs"]))

        two_scans = os.path.join(proj, "sess-stream-split.jsonl")
        with open(two_scans, "w", encoding="utf-8") as fh:
            fh.write(streamed("msg-T", 1, None) + "\n")
        r_t1, c_t1 = M.scan_transcripts(two_scans, "sess-1", {}, manifest, opts)
        with open(two_scans, "a", encoding="utf-8") as fh:
            fh.write(streamed("msg-T", 125, "end_turn") + "\n")
        r_t2, c_t2 = M.scan_transcripts(two_scans, "sess-1", c_t1, manifest, opts)
        t_t = M.totals(r_t1 + r_t2)
        check("sf2 a scan that ends after the partial and a later scan that reads "
              "the final entry together count the message once, at the final "
              "entry's tokens (125 out, 2306 in, one message)",
              (t_t["out"], t_t["in"], t_t["msgs"]) == (125, 2306, 1),
              (t_t["out"], t_t["in"], t_t["msgs"]))
        r_t3, _ = M.scan_transcripts(two_scans, "sess-1", c_t2, manifest, opts)
        with open(two_scans, "a", encoding="utf-8") as fh:
            fh.write(streamed("msg-T", 125, "end_turn") + "\n")
        r_t4, _ = M.scan_transcripts(two_scans, "sess-1", c_t2, manifest, opts)
        check("sf3 ...and once the final is counted, a re-scan and a repeat of the "
              "final entry add nothing",
              r_t3 == [] and M.totals(r_t4)["tokens"] == 0,
              (r_t3, M.totals(r_t4)))
        pend = (c_t2.get("files") or {}).get(two_scans, {}).get("pending")
        check("sf4 ...and the cursor stops carrying a message as provisional once "
              "its final entry is counted",
              not pend, pend)

        # Allow twin, for the mutation that counts final entries only: a message
        # whose stream was cut off never gets a final entry, and its partial is
        # the only record that tokens were spent at all.
        cut_off = os.path.join(proj, "sess-stream-cut.jsonl")
        with open(cut_off, "w", encoding="utf-8") as fh:
            fh.write(streamed("msg-U", 7, None) + "\n")
        r_u, _ = M.scan_transcripts(cut_off, "sess-1", {}, manifest, opts)
        t_u = M.totals(r_u)
        check("sf5 a partial that never gets a final entry is still counted, "
              "rather than dropped",
              (t_u["out"], t_u["in"], t_u["msgs"]) == (7, 2306, 1),
              (t_u["out"], t_u["in"], t_u["msgs"]))

        # --- scanning: subagents + parallel attribution --------------------
        sub = os.path.join(proj, "sess-1", "subagents")
        os.makedirs(sub)
        for aid, task, out_tokens in (("a1", "P3.1", 1000), ("a2", "P3.2", 2000)):
            with open(os.path.join(sub, "agent-%s.jsonl" % aid), "w",
                      encoding="utf-8") as fh:
                fh.write(entry("m-%s" % aid, "2026-08-06T07:20:00Z",
                               out_tokens, "claude-haiku-4-5") + "\n")
            with open(os.path.join(sub, "agent-%s.meta.json" % aid), "w",
                      encoding="utf-8") as fh:
                json.dump({"agentType": "audit-executor",
                           "description": "%s do the thing" % task,
                           "toolUseId": "toolu_x", "spawnDepth": 1}, fh)
        rows4, _ = M.scan_transcripts(main, "sess-1", cur3, manifest, opts)
        by_task = M.aggregate(rows4, "task")
        check("scan: parallel subagents attributed to distinct tasks",
              by_task.get("P3.1", {}).get("out") == 1000
              and by_task.get("P3.2", {}).get("out") == 2000)
        check("scan: subagent agentType recorded",
              all(r["agentType"] == "audit-executor" for r in rows4))
        check("scan: subagent model priced separately from the orchestrator",
              M.aggregate(rows4, "model").get("claude-haiku-4-5", {}).get("msgs") == 2)

        # --- a continued agent's next task --------------------------------
        # THE MEASUREMENT THE ORCHESTRATOR'S OWN PREFERENCE RESTS ON. It is told
        # to continue a running executor rather than spawn a replacement, and a
        # continued agent keeps the `.meta.json` it was spawned with - so without
        # a second label its whole second task reads as free and the first task
        # reads as having cost both. The label is the first line of the message
        # that hands it the next task, which is the spawn description's own
        # convention one message later.
        #
        # THE ENVELOPE IS THE HARNESS'S, not the sender's: a message handed to a
        # running agent arrives with a lead line ahead of the text somebody
        # typed, so "first line" has to mean the sender's first line or the
        # convention is unwritable. The literals here are the ones live
        # transcripts carry, which is why they are fixtures and not paraphrases.
        def handoff(text, kind="coordinator",
                    lead=M.CONTINUATION_LEADS[0]):
            return json.dumps({
                "type": "user", "origin": {"kind": kind},
                "timestamp": "2026-08-06T09:00:00Z", "isSidechain": True,
                "message": {"role": "user", "content": lead + "\n" + text}})

        def tool_result(text):
            """A `user` entry that is a TOOL RESULT - no `origin`, like the spawn
            prompt and an injected skill. All three are `type: "user"`, and a
            reader that took any of them for a hand-off would move a task's spend
            onto whatever id appeared in a tool's output."""
            return json.dumps({
                "type": "user", "timestamp": "2026-08-06T09:00:00Z",
                "toolUseResult": {"stdout": text},
                "message": {"role": "user", "content": text}})

        def continued(aid, lines):
            """One subagent transcript spawned for P3.1, written in order."""
            with open(os.path.join(cont_sub, "agent-%s.jsonl" % aid), "w",
                      encoding="utf-8") as fh:
                for line in lines:
                    fh.write(line + "\n")
            with open(os.path.join(cont_sub, "agent-%s.meta.json" % aid), "w",
                      encoding="utf-8") as fh:
                json.dump({"agentType": "audit-executor",
                           "description": "P3.1 the task it was spawned for",
                           "toolUseId": "toolu_c", "spawnDepth": 1}, fh)

        cont_main = os.path.join(proj, "sess-cont.jsonl")
        with open(cont_main, "w", encoding="utf-8") as fh:
            fh.write("")
        cont_sub = os.path.join(proj, "sess-cont", "subagents")
        os.makedirs(cont_sub)
        continued("c1", [entry("m-c1a", "2026-08-06T09:00:00Z", 100),
                         handoff("P3.2 carry on - the scope is widened"),
                         entry("m-c1b", "2026-08-06T09:10:00Z", 400)])
        # AN UNCLAIMED SESSION, so nothing here can be attributed by a window and
        # the only two answers available are the description and the hand-off.
        cont_rows, cont_cur = M.scan_transcripts(cont_main, "sess-cont", {},
                                                 manifest, opts)
        by_task = M.aggregate(cont_rows, "task")
        check("ho1 a continued agent's spend after a message naming the next "
              "task lands on THAT task, and what it spent before it stays on the "
              "task it was spawned for - the pair, because either half alone "
              "also passes for a reader that moved everything: %r"
              % ({k: v.get("out") for k, v in by_task.items()},),
              by_task.get("P3.1", {}).get("out") == 100
              and by_task.get("P3.2", {}).get("out") == 400)
        check("ho2 ...and the moved spend is `task` attribution with the phase "
              "that owns the named task, not a phase average: %r"
              % ([(r.get("taskId"), r.get("phaseId"), r.get("attr"))
                  for r in cont_rows],),
              sorted((r.get("taskId"), r.get("phaseId"), r.get("attr"))
                     for r in cont_rows)
              == [("P3.1", "P3", "task"), ("P3.2", "P3", "task")])

        # THE CURSOR CARRIES IT, because a scan reads only the new bytes: the
        # message that moved attribution is in a chunk already consumed by the
        # time the rest of the second task's spend is written.
        with open(os.path.join(cont_sub, "agent-c1.jsonl"), "a",
                  encoding="utf-8") as fh:
            fh.write(entry("m-c1c", "2026-08-06T10:00:00Z", 7) + "\n")
        cont_rows2, _ = M.scan_transcripts(cont_main, "sess-cont", cont_cur,
                                           manifest, opts)
        check("ho3 ...and a LATER scan, which never sees that message again, "
              "still attributes to the task it named - a hand-off forgotten "
              "between scans puts the rest of the second task back on the "
              "first: %r" % ([(r.get("taskId"), r.get("out")) for r in cont_rows2],),
              [(r.get("taskId"), r.get("out")) for r in cont_rows2]
              == [("P3.2", 7)])

        # --- what must NOT move it ----------------------------------------
        quiet_main = os.path.join(proj, "sess-quiet.jsonl")
        with open(quiet_main, "w", encoding="utf-8") as fh:
            fh.write("")
        cont_sub = os.path.join(proj, "sess-quiet", "subagents")
        os.makedirs(cont_sub)
        continued("c2", [handoff("carry on, the gate is green"),
                         entry("m-c2a", "2026-08-06T09:00:00Z", 50)])
        continued("c3", [handoff("keep going with what you have\n\nthe review "
                                 "for P3.2 is somebody else's job"),
                         entry("m-c3a", "2026-08-06T09:00:00Z", 60)])
        continued("c4", [tool_result("P3.2 appears in this tool's output"),
                         entry("m-c4a", "2026-08-06T09:00:00Z", 70)])
        quiet_rows, _ = M.scan_transcripts(quiet_main, "sess-quiet", {},
                                           manifest, opts)
        quiet_tasks = M.aggregate(quiet_rows, "task")
        check("ho4 a message naming no task changes nothing - the spawn "
              "description still answers, because a known attribution being "
              "coarse is better than an invented one being precise: %r"
              % ({k: v.get("out") for k, v in quiet_tasks.items()},),
              quiet_tasks.get("P3.1", {}).get("out") == 50 + 60 + 70
              and "P3.2" not in quiet_tasks)
        check("ho5 ...and that holds when a task id appears further down the "
              "message and when one appears in a TOOL RESULT: the convention "
              "names the first line the sender wrote, so an id mentioned in "
              "passing cannot re-bill an agent's work: %r"
              % (sorted(set(r.get("taskId") for r in quiet_rows)),),
              sorted(set(r.get("taskId") for r in quiet_rows)) == ["P3.1"])

        # THE MAIN TRANSCRIPT IS NOT A CONTINUED AGENT. A message there is
        # addressed to the orchestrator, which hands nobody a second task, and
        # its spend is answered by the phase claim and the task windows.
        orch_main = os.path.join(proj, "sess-orch.jsonl")
        with open(orch_main, "w", encoding="utf-8") as fh:
            fh.write(handoff("P3.2 please", kind="human") + "\n")
            fh.write(entry("m-o1", "2026-08-06T06:00:00Z", 9) + "\n")
        orch_rows, _ = M.scan_transcripts(orch_main, "sess-1", {}, manifest, opts)
        check("ho6 ...and a message in the MAIN transcript moves nothing: the "
              "orchestrator's own spend is answered by the claim and the "
              "windows, and there is no spawn description there to correct: %r"
              % ([(r.get("phaseId"), r.get("taskId"), r.get("attr"))
                  for r in orch_rows],),
              [(r.get("phaseId"), r.get("taskId"), r.get("attr"))
               for r in orch_rows] == [("P3", None, "phase")])

        # --- backfill sizing guard ----------------------------------------
        rows5, _ = M.scan_transcripts(
            main, "sess-1", {}, manifest,
            {"repo": "demo", "backfillOnFirstRun": True, "maxScanBytes": 10})
        check("scan: oversized transcript on first sight skips history",
              rows5 == [])
        rows6, _ = M.scan_transcripts(
            main, "sess-1", {}, manifest,
            {"repo": "demo", "backfillOnFirstRun": False})
        check("scan: backfillOnFirstRun=False starts at EOF", rows6 == [])

        # --- ledger I/O ----------------------------------------------------
        ledger = os.path.join(tmp, "usage")
        all_rows, _ = M.scan_transcripts(main, "sess-1", {}, manifest, opts)
        n = M.append_rows(ledger, all_rows)
        check("ledger: append writes one line per row", n == len(all_rows))
        check("ledger: monthly file named after the bucket",
              os.path.isfile(os.path.join(ledger, "2026-08.jsonl")))
        back = M.read_ledger(ledger)
        check("ledger: round-trips", M.totals(back) == M.totals(all_rows))
        check("ledger: --since filters by date",
              M.totals(M.read_ledger(ledger, since="2026-08-06"))["msgs"]
              == M.totals(back)["msgs"])
        check("ledger: --since in the future returns nothing",
              M.read_ledger(ledger, since="2099-01-01") == [])
        check("ledger: --until in the past returns nothing",
              M.read_ledger(ledger, until="1999-01-01") == [])
        with open(os.path.join(ledger, "2026-08.jsonl"), "a",
                  encoding="utf-8") as fh:
            fh.write("{ torn line\n")
        check("ledger: torn line tolerated on read",
              M.totals(M.read_ledger(ledger)) == M.totals(all_rows))

        # --- cursor persistence -------------------------------------------
        M.save_cursor(ledger, "sess-1", {"author": "a@b.c", "files": {}})
        check("cursor: round-trips",
              M.load_cursor(ledger, "sess-1").get("author") == "a@b.c")
        check("cursor: missing cursor -> {}",
              M.load_cursor(ledger, "nope") == {})
        # Ledger discovery must never GUESS. The fixed-depth version of this
        # resolved examples/acme-store/audit-plan.json to the enclosing repo and
        # rendered that project's spend under the example's name.
        deep = os.path.join(tmp, "proj", "docs", "audit")
        os.makedirs(os.path.join(tmp, "proj", ".claude", "usage"), exist_ok=True)
        os.makedirs(deep, exist_ok=True)
        flat = os.path.join(tmp, "proj", "sub")
        os.makedirs(os.path.join(flat, ".claude", "usage"), exist_ok=True)
        check("discover: docs/audit/<m>.json finds the repo-root ledger",
              M.find_ledger_dir(os.path.join(deep, "m.json"), ".claude/usage")
              == os.path.join(tmp, "proj", ".claude", "usage"))
        check("discover: a manifest beside its own ledger prefers THAT one",
              M.find_ledger_dir(os.path.join(flat, "m.json"), ".claude/usage")
              == os.path.join(flat, ".claude", "usage"))
        check("discover: no ledger anywhere -> None, never a guessed ancestor",
              M.find_ledger_dir(os.path.join(tmp, "elsewhere", "m.json"),
                              ".claude/nonexistent") is None)
        check("discover: an explicit project dir always wins",
              M.find_ledger_dir(os.path.join(flat, "m.json"), ".claude/usage",
                              os.path.join(tmp, "proj"))
              == os.path.join(tmp, "proj", ".claude", "usage"))
        # The three cases above pass `.claude/usage` — the shipped default, written
        # with a forward slash because it is authored in JSON — and compare against
        # os.path.join. That is not incidental: it is the assertion. On Windows the
        # unnormalised join returns `C:\proj\.claude/usage`, which opens fine and so
        # goes unnoticed until the string is compared or printed, and audit-status.py
        # puts it straight into the JSON the panel reads. These two state the rule
        # outright so it cannot be optimised away as redundant.
        for label, got in (
                ("upward search",
                 M.find_ledger_dir(os.path.join(deep, "m.json"), ".claude/usage")),
                ("explicit project dir",
                 M.find_ledger_dir(os.path.join(flat, "m.json"), ".claude/usage",
                                 os.path.join(tmp, "proj")))):
            check("discover: %s returns a path in this platform's own separator"
                  % label, got == os.path.normpath(got))

        # The walk is bounded by the repo itself. Unbounded, a manifest
        # inside a repo with no ledger walked PAST the repo root, found
        # ~/.claude/usage -- the user's global Claude state, which exists on
        # nearly every machine that ever ran Claude Code -- and rendered every
        # project's spend under this one manifest's name.
        fake_home = os.path.join(tmp, "home")
        os.makedirs(os.path.join(fake_home, ".claude", "usage"), exist_ok=True)
        with open(os.path.join(fake_home, ".claude", "usage", "2026-08.jsonl"),
                  "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"v": 1, "tokens": 7}) + "\n")
        repo = os.path.join(fake_home, "repo")
        os.makedirs(os.path.join(repo, ".git"), exist_ok=True)  # a real clone
        os.makedirs(os.path.join(repo, "docs", "audit"), exist_ok=True)
        # `M._home`, not `globals()["_home"]`. Inline this rebound the global
        # `find_ledger_dir` actually reads; from here `globals()` is this file's
        # namespace, `find_ledger_dir` would keep calling the real `_home()`,
        # the walk would reach the REAL `~/.claude/usage` on this machine and
        # the three cases below would be measuring the developer's home
        # directory rather than the fixture. Restored on `M` in the same
        # `finally` - a leaked patch would silently re-route every later case.
        _real_home = getattr(M, "_home", None)
        M._home = lambda: fake_home
        try:
            check("discover: the walk stops at the repo root (.git dir) and "
                  "never finds the HOME ledger above it",
                  M.find_ledger_dir(os.path.join(repo, "docs", "audit", "m.json"),
                                  ".claude/usage") is None)
            # Worktrees and submodules mark the boundary with a FILE named
            # .git; the ledger above such a checkout belongs to someone else.
            parent = os.path.join(tmp, "parent")
            os.makedirs(os.path.join(parent, ".claude", "usage"), exist_ok=True)
            wt = os.path.join(parent, "wt")
            os.makedirs(os.path.join(wt, "docs"), exist_ok=True)
            with open(os.path.join(wt, ".git"), "w", encoding="utf-8") as fh:
                fh.write("gitdir: /somewhere/else\n")
            check("discover: a worktree's .git FILE is the same boundary",
                  M.find_ledger_dir(os.path.join(wt, "docs", "m.json"),
                                  ".claude/usage") is None)
            # No .git anywhere on the way up: the home guard alone must
            # refuse ~/.claude before the walk runs out of ancestors.
            check("discover: outside any repo the walk still never answers "
                  "with the user's own ~/.claude",
                  M.find_ledger_dir(os.path.join(fake_home, "notes", "m.json"),
                                  ".claude/usage") is None)
        finally:
            if _real_home is None:
                del M._home
            else:
                M._home = _real_home
        # The boundary must not shadow the repo's OWN ledger: the candidate
        # is tested before the .git stop, so a root holding both still answers.
        os.makedirs(os.path.join(tmp, "proj", ".git"), exist_ok=True)
        check("discover: a repo root holding both .git and the ledger still "
              "answers with the ledger",
              M.find_ledger_dir(os.path.join(deep, "m.json"), ".claude/usage")
              == os.path.join(tmp, "proj", ".claude", "usage"))

        check("cursor: lives outside stateDir, next to the ledger",
              os.path.isfile(os.path.join(ledger, ".cursors", "sess-1.json")))

        # --- backfill idempotency ------------------------------------------
        month_rows = M.read_ledger(ledger)
        before = M.totals(month_rows)
        fresh, _ = M.scan_transcripts(main, "sess-1", {}, manifest, opts)
        kept = [r for r in month_rows if r.get("sessionId") != "sess-1"]
        M.rewrite_month(ledger, "2026-08", kept + fresh)
        check("backfill: rebuild is idempotent (totals unchanged)",
              M.totals(M.read_ledger(ledger)) == before)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- context: read once vs re-read, and the peak a single turn reached --
    # WHY a task got expensive has two causes with OPPOSITE repairs - a lot of
    # NEW work (narrow the task) or a long-lived run re-paying for context it
    # already read (hand the rest to a fresh agent) - and a single cost total
    # cannot tell them apart. `_context_of` and `context_shape` are that split.
    check("ctx1 _context_of counts every billed field except `out` - a "
          "generated token is not context a later turn has to carry forward",
          M._context_of({"in": 3, "out": 999, "cacheW5m": 2, "cacheW1h": 1,
                         "cacheR": 5}) == 11)

    ctx_manifest = {"phases": [{"id": "PC", "tasks": [
        {"id": "PC.1", "status": "done"}, {"id": "PC.2", "status": "done"}]}]}

    # PC.1: one big new-read turn, one small re-read turn.
    pc1_rows = [
        {"taskId": "PC.1", "in": 100, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 5,
         "maxContext": 100},
        {"taskId": "PC.1", "in": 1, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 200,
         "maxContext": 201},
    ]
    shape = M.context_shape(ctx_manifest, pc1_rows)
    check("ctx2 newTokens/reReadTokens sum the raw fields every row has "
          "always carried, across every row naming this task: %r"
          % (shape.get("PC.1"),),
          shape["PC.1"]["newTokens"] == 101 and shape["PC.1"]["reReadTokens"] == 205)
    check("ctx3 maxContext is the PEAK single turn (201), never the sum of "
          "the rows it comes from (101 + 205 = 306)",
          shape["PC.1"]["maxContext"] == 201
          and shape["PC.1"]["contextBasis"] == "measured")

    # PC.2: one row predates the field entirely - the peak has to say so
    # rather than reporting the max of what it COULD see, which would
    # silently understate the truth whenever the missing row was the bigger
    # one of the two.
    pc2_rows = [
        {"taskId": "PC.2", "in": 5, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0,
         "maxContext": 5},
        {"taskId": "PC.2", "in": 5, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0},
    ]
    shape2 = M.context_shape(ctx_manifest, pc2_rows)
    check("ctx4 a task with even one row that predates maxContext tracking "
          "reports None and says why, never a zero and never the partial "
          "max of the rows that do carry it: %r" % (shape2.get("PC.2"),),
          shape2["PC.2"]["maxContext"] is None
          and shape2["PC.2"]["contextBasis"] == "predates-tracking")
    check("ctx5 ...but newTokens/reReadTokens still answer - that split has "
          "no missing-basis case, because every row this ledger has ever "
          "written carries the raw fields it is built from",
          shape2["PC.2"]["newTokens"] == 10 and shape2["PC.2"]["reReadTokens"] == 0)

    check("ctx6 a row naming a task the manifest does not have is excluded, "
          "never folded into a bucket nobody asked for - the same "
          "`task_index` filter cost_bands/unit_economics already apply",
          "GHOST" not in M.context_shape(
              ctx_manifest, [{"taskId": "GHOST", "in": 1, "maxContext": 1}]))

    # --- context: the SCANNER tracks the peak, never the sum -----------------
    ctx_tmp = tempfile.mkdtemp(prefix="usage-ledger-context-")
    try:
        ctx_proj = os.path.join(ctx_tmp, "projects")
        os.makedirs(ctx_proj)
        ctx_main = os.path.join(ctx_proj, "sess-ctx.jsonl")

        def usage_entry(mid, ts, in_tokens, cache_read):
            return json.dumps({
                "type": "assistant", "timestamp": ts, "gitBranch": "audit/ctx",
                "message": {"id": mid, "model": "claude-opus-5", "usage": {
                    "input_tokens": in_tokens, "output_tokens": 1,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": cache_read}}})

        with open(ctx_main, "w", encoding="utf-8") as fh:
            # context 50, then context 10 - both in the same hour bucket, so
            # they fold into ONE row and the row must keep the larger figure.
            fh.write(usage_entry("ctx-A", "2026-08-06T07:00:00Z", 40, 10) + "\n")
            fh.write(usage_entry("ctx-B", "2026-08-06T07:05:00Z", 5, 5) + "\n")
        ctx_rows, _ = M.scan_transcripts(ctx_main, "sess-ctx", {}, {},
                                         {"backfillOnFirstRun": True})
        check("ctx7 one bucket folding two turns carries the LARGER turn's "
              "context (50), never their sum (60) and never the other one "
              "(10): %r" % (ctx_rows,),
              len(ctx_rows) == 1 and ctx_rows[0]["maxContext"] == 50)
    finally:
        shutil.rmtree(ctx_tmp, ignore_errors=True)

    # --- ig: the ledger dir is self-ignoring --------------------------------
    # It holds person identities and per-machine cursors; a `*` .gitignore
    # written by every dir-creating writer keeps `git add .claude` from
    # publishing either. An existing marker is the user's file - preserved.
    _ig_tmp = tempfile.mkdtemp(prefix="ledger-ignore-")
    try:
        _ig = os.path.join(_ig_tmp, "ledger")
        M.append_rows(_ig, [{"ts": "2026-08-01T09", "out": 5}])
        check("ig1 append_rows drops a `*` .gitignore beside the monthly file",
              os.path.exists(os.path.join(_ig, ".gitignore")))
        _ig2 = os.path.join(_ig_tmp, "ledger2")
        M.save_cursor(_ig2, "s-ig", {"pos": 1})
        check("ig2 save_cursor marks the LEDGER ROOT self-ignoring, covering "
              ".cursors beneath it",
              os.path.exists(os.path.join(_ig2, ".gitignore")))
        with open(os.path.join(_ig, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("custom\n")
        M.rewrite_month(_ig, "2026-08", [{"ts": "2026-08-01T09", "out": 5}])
        check("ig3 an existing marker is preserved by every writer",
              open(os.path.join(_ig, ".gitignore"),
                   encoding="utf-8").read() == "custom\n")
    finally:
        shutil.rmtree(_ig_tmp, ignore_errors=True)

    # --- tw: a replace's temp file is this writer's own --------------------
    # A temp name derived from the target alone is shared by every writer of
    # that target: a second writer's half-written temp is truncated, or moved
    # into place as if it were this one's. Each writer takes a name nobody else
    # can hold, so a file planted under the derived name is left as it was.
    _tw_tmp = tempfile.mkdtemp(prefix="ledger-temp-")
    try:
        _tw = os.path.join(_tw_tmp, "ledger")
        os.makedirs(os.path.join(_tw, ".cursors"))
        _tw_month_foreign = os.path.join(_tw, "2026-08.jsonl.tmp")
        _tw_cursor_foreign = M.cursor_path(_tw, "s-tw") + ".tmp"
        for _p in (_tw_month_foreign, _tw_cursor_foreign):
            with open(_p, "w", encoding="utf-8") as fh:
                fh.write("FOREIGN WRITER IN FLIGHT\n")
        _tw_row = {"ts": "2026-08-01T09", "out": 5}
        _tw_ok_month = M.rewrite_month(_tw, "2026-08", [_tw_row])
        _tw_ok_cursor = M.save_cursor(_tw, "s-tw", {"pos": 7})

        def _tw_read(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    return fh.read()
            except OSError:
                return None
        check("tw1 rewrite_month neither overwrites nor consumes a foreign "
              "`<month>.jsonl.tmp` beside the ledger: it is still there, byte "
              "for byte",
              _tw_read(_tw_month_foreign) == "FOREIGN WRITER IN FLIGHT\n",
              "got %r" % (_tw_read(_tw_month_foreign),))
        check("tw2 ...and save_cursor leaves a foreign cursor temp file the "
              "same way",
              _tw_read(_tw_cursor_foreign) == "FOREIGN WRITER IN FLIGHT\n",
              "got %r" % (_tw_read(_tw_cursor_foreign),))
        # The allow twin: a writer that kept its hands off the foreign file by
        # not writing at all would pass both cases above.
        _tw_month_text = _tw_read(os.path.join(_tw, "2026-08.jsonl"))
        _tw_cursor_text = _tw_read(M.cursor_path(_tw, "s-tw"))
        check("tw3 ...while both writes still land: the month holds exactly the "
              "row handed over, the cursor reads back, and both writers say so",
              _tw_ok_month is True and _tw_ok_cursor is True
              and _tw_month_text is not None
              and [json.loads(x) for x in _tw_month_text.splitlines()] == [_tw_row]
              and M.load_cursor(_tw, "s-tw") == {"pos": 7},
              "month=%r cursor=%r ok=%r/%r" % (_tw_month_text, _tw_cursor_text,
                                               _tw_ok_month, _tw_ok_cursor))
        _tw_left = sorted(os.listdir(_tw)) + sorted(
            os.listdir(os.path.join(_tw, ".cursors")))
        check("tw4 ...and leave no temp file of their own behind - only the "
              "planted pair, the two targets, the month's lock file and the "
              "ignore marker: %r" % (_tw_left,),
              _tw_left == sorted([".cursors", ".gitignore", "2026-08.jsonl",
                                  "2026-08.jsonl.lock", "2026-08.jsonl.tmp"])
              + sorted(["s-tw.json", "s-tw.json.tmp"]))
    finally:
        shutil.rmtree(_tw_tmp, ignore_errors=True)

    # --- nm: a month with no file is held like every other month ------------
    # A writer that does not take the month's lock - a copy of this file from
    # before it had one - can still create the month file while the backfill
    # is rebuilding that month, writing into a file the replace then retires;
    # so the rewrite must hold a descriptor on the file it would otherwise
    # never have seen. `append_rows` itself waits for the lock (lk1), so the
    # writer here appends directly.
    _nm_tmp = tempfile.mkdtemp(prefix="ledger-new-month-")
    try:
        _nm = os.path.join(_nm_tmp, "ledger")
        os.makedirs(_nm)
        _nm_rebuilt = {"ts": "2026-09-01T09", "sessionId": "S-BF", "out": 3}
        _nm_hook = {"ts": "2026-09-01T10", "sessionId": "S-HOOK", "out": 5}
        _nm_keep, _nm_tail = M.open_month(_nm, "2026-09", {"S-BF"})
        _nm_real = M._replace_rows
        _nm_fired = []

        def _nm_replace(path, rows):
            # The hook's append lands after the rewrite looked for the file and
            # before the replace: it creates the file, or appends to the one
            # the rewrite created.
            if not _nm_fired:
                with open(os.path.join(_nm, "2026-09.jsonl"), "a",
                          encoding="utf-8") as fh:
                    fh.write(M._row_line(_nm_hook))
                _nm_fired.append(1)
            return _nm_real(path, rows)
        M._replace_rows = _nm_replace
        try:
            _nm_ok = M.rewrite_month(_nm, "2026-09", _nm_keep + [_nm_rebuilt],
                                     tail=_nm_tail)
        finally:
            M._replace_rows = _nm_real
        _nm_rows = M.read_ledger(_nm)
        check("nm1 a row a writer appends to a month file created during a "
              "backfill of a month that had no file survives the rewrite: "
              "ok=%r fired=%r rows=%r" % (_nm_ok, _nm_fired, _nm_rows),
              _nm_ok is True and _nm_fired == [1]
              and _nm_rows.count(_nm_hook) == 1
              and _nm_rows.count(_nm_rebuilt) == 1 and len(_nm_rows) == 2)
        # ALLOW TWIN: with no writer in the window, the created month holds
        # exactly the rows handed over - the mutation it catches is a carry
        # that re-reads the rebuilt file and doubles its own rows.
        _nm2 = os.path.join(_nm_tmp, "ledger2")
        os.makedirs(_nm2)
        _nm2_keep, _nm2_tail = M.open_month(_nm2, "2026-09", {"S-BF"})
        _nm2_ok = M.rewrite_month(_nm2, "2026-09", _nm2_keep + [_nm_rebuilt],
                                  tail=_nm2_tail)
        check("nm2 ...and a missing month rebuilt with no writer holds exactly "
              "the rows handed over: ok=%r rows=%r"
              % (_nm2_ok, M.read_ledger(_nm2)),
              _nm2_ok is True and M.read_ledger(_nm2) == [_nm_rebuilt]
              and os.path.isfile(os.path.join(_nm2, "2026-09.jsonl")))
    finally:
        shutil.rmtree(_nm_tmp, ignore_errors=True)

    # --- lk: an append waits for the month's lock, and never for ever -------
    # A rewrite holds the month's lock across its replace; an append made then
    # must land after the swap, not in the file the swap erases. Threads stand
    # in for processes: the lock is per open file, so two in one process
    # exclude each other as two processes do.
    import threading
    _lk_tmp = tempfile.mkdtemp(prefix="ledger-lock-")
    _lk_wait = M.MONTH_LOCK_WAIT_S
    try:
        _lk_path = os.path.join(_lk_tmp, "2026-09.jsonl")
        _lk_row = {"ts": "2026-09-01T09", "out": 3, "probeId": "lk"}

        def _lk_count():
            try:
                with open(_lk_path, encoding="utf-8") as fh:
                    return sum(1 for line in fh if '"lk"' in line)
            except OSError:
                return 0

        _lk_res = []
        _lk_held = M.lock_month(_lk_path)
        _lk_thread = threading.Thread(
            target=lambda: _lk_res.append(M.append_rows(_lk_tmp, [_lk_row])))
        _lk_thread.start()
        _lk_thread.join(0.3)
        _lk_during = (_lk_thread.is_alive(), _lk_count())
        M.unlock_month(_lk_held)
        _lk_thread.join(30)
        check("lk1 an append made while the month's lock is held waits for it, "
              "then writes its row once: held=%r after=%d result=%r"
              % (_lk_during, _lk_count(), _lk_res),
              _lk_held is not None and _lk_during == (True, 0)
              and _lk_count() == 1 and _lk_res == [1])

        # The other direction: a wait that ends in a dropped row trades a row
        # at risk for a row certainly lost. The lock is never released here.
        M.MONTH_LOCK_WAIT_S = 0.05
        _lk_held = M.lock_month(_lk_path, wait_s=0)
        _lk_n = M.append_rows(_lk_tmp, [_lk_row])
        M.unlock_month(_lk_held)
        check("lk2 ...and an append whose lock is not had within the wait "
              "writes its row anyway: written=%r rows=%d" % (_lk_n, _lk_count()),
              _lk_held is not None and _lk_n == 1 and _lk_count() == 2)
        M.MONTH_LOCK_WAIT_S = _lk_wait

        # An append that kept its lock would stall every later one for the
        # whole wait; the lock must be free the moment it returns.
        _lk_after = M.lock_month(_lk_path, wait_s=0)
        M.unlock_month(_lk_after)
        check("lk3 ...and the lock is free again once append_rows returns",
              _lk_after is not None)
    finally:
        M.MONTH_LOCK_WAIT_S = _lk_wait
        shutil.rmtree(_lk_tmp, ignore_errors=True)

    # --- rx: the re-export this module exists to keep serving ---------------
    # Nothing imports `usage_ledger` by name: every consumer loads it BY PATH and
    # reads attributes off the module object. A name that quietly stopped being
    # served would therefore fail at a call site in another file, at runtime, in
    # whichever surface happened to ask for it first. Counted against what the two
    # modules below actually define, not against a hand-copied list, so adding a
    # public name down there and forgetting it up here goes red HERE.
    import _usage_core as _core_mod
    import _usage_coverage
    import _usage_economics
    import _usage_routing
    import _usage_spend

    # The four modules `_usage_analytics` was cut into. `_usage_bench` is
    # NOT here and that is not an omission: every name it defines starts with an
    # underscore, so it contributes nothing to re-export, and the passes it holds
    # are the four below's, counted there.
    _analytics_mods = (_usage_spend, _usage_economics, _usage_routing,
                       _usage_coverage)

    def _public_names(mod):
        """What `mod` DEFINES for others: no underscore names, and no modules it
        merely imported (`re`, `time`) - those are not part of anyone's API."""
        return sorted(n for n, v in vars(mod).items()
                      if not n.startswith("_")
                      and not isinstance(v, type(_core_mod)))

    _core_public = _public_names(_core_mod)
    # Each analytics module imports names from `_usage_core`, so they are ITS
    # attributes too. They belong to core and are counted there, once.
    _analytics_public = sorted(set(
        n for mod in _analytics_mods for n in _public_names(mod)
        if n not in _core_public))
    # `M` rather than `globals()`, and this is the pair that would have failed
    # LOUDLY rather than quietly - which is why it is worth naming. Inline,
    # "is this name served?" was "is it in my own namespace?", because the suite
    # WAS the module. Here it has to ask the module: `hasattr(M, n)` and
    # `getattr(M, n, None)`. Carried literally, `_missing` would list every
    # name and rx1 would go red on a re-export that is perfectly intact.
    _missing = [n for n in _core_public + _analytics_public
                if not hasattr(M, n)]
    check("rx1 every public name _usage_core and the four analytics modules define "
          "is served by usage_ledger too - the re-export is what lets a six-way "
          "split change no call site",
          _missing == [], "missing: %r" % (_missing,))

    def _definer(name):
        """The module that DEFINES `name`, for the identity check below. Read
        rather than assumed: since the split a name can come from any of five files,
        and asking the wrong one would compare an object against itself."""
        for mod in (_core_mod,) + _analytics_mods:
            if name in _public_names(mod) and (
                    mod is _core_mod or name not in _core_public):
                return mod
        return None

    check("rx2 ...and each one IS the object the defining module holds, not a "
          "same-named copy that could drift",
          all(getattr(M, n, None) is getattr(_definer(n), n, object())
              for n in _core_public + _analytics_public))
    # The second direction, and it is the one that looks vacuous: rx1 passes by
    # construction if `_public_names` narrows to NOTHING (a filter that narrows
    # to empty must never read as 'all clear'). The yardstick is read off
    # usage_ledger.py's own import statements by AST rather than written here
    # as a count, so it is a second source that cannot be gutted along with the
    # filter, and a name added below and re-exported above moves both sides at
    # once instead of turning a literal stale.
    import ast

    def _reexported_by_source():
        """{defining module: sorted names} that usage_ledger.py's own
        `from _usage_* import (...)` statements list."""
        with open(M.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 0 and (
                    node.module or "").startswith("_usage_"):
                found.setdefault(node.module, []).extend(
                    a.name for a in node.names)
        return dict((mod, sorted(names)) for mod, names in found.items())

    _rx_src = _reexported_by_source()
    _rx_core_src = _rx_src.get("_usage_core", [])
    _rx_analytics_src = sorted(set(
        n for mod in _analytics_mods for n in _rx_src.get(mod.__name__, [])))
    check("rx3 ...and the names counted are exactly the ones usage_ledger.py's "
          "import statements re-export, none of them empty, so rx1 cannot be "
          "green over a filter that narrowed to nothing",
          bool(_rx_core_src) and bool(_rx_analytics_src)
          and _core_public == _rx_core_src
          and _analytics_public == _rx_analytics_src,
          "core %r vs source %r; analytics %r vs source %r"
          % (_core_public, _rx_core_src, _analytics_public, _rx_analytics_src))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_usage_ledger.py --selftest\n")
    raise SystemExit(2)
