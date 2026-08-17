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
    here. This half fails loudly (all 40 names reported missing) rather than
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
    check("author: none mode returns None", M.resolve_author(".", "none") is None)
    h = M.resolve_author(".", "hash")
    check("author: hash mode is pseudonymous and stable",
          isinstance(h, str) and h.startswith("anon-")
          and h == M.resolve_author(".", "hash"))

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

        # The walk is bounded by the repo itself (F-E1). Unbounded, a manifest
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

    # --- rx: the re-export this module exists to keep serving ---------------
    # Nothing imports `usage_ledger` by name: every consumer loads it BY PATH and
    # reads attributes off the module object. A name that quietly stopped being
    # served would therefore fail at a call site in another file, at runtime, in
    # whichever surface happened to ask for it first. Counted against what the two
    # modules below actually define, not against a hand-copied list, so adding a
    # public name down there and forgetting it up here goes red HERE.
    import _usage_core as _core_mod
    import _usage_analytics as _analytics_mod

    def _public_names(mod):
        """What `mod` DEFINES for others: no underscore names, and no modules it
        merely imported (`re`, `time`) - those are not part of anyone's API."""
        return sorted(n for n, v in vars(mod).items()
                      if not n.startswith("_")
                      and not isinstance(v, type(_core_mod)))

    _core_public = _public_names(_core_mod)
    # `_usage_analytics` imports 8 names from `_usage_core`, so they are ITS
    # attributes too. They belong to core and are counted there, once.
    _analytics_public = [n for n in _public_names(_analytics_mod)
                         if n not in _core_public]
    # `M` rather than `globals()`, and this is the pair that would have failed
    # LOUDLY rather than quietly - which is why it is worth naming. Inline,
    # "is this name served?" was "is it in my own namespace?", because the suite
    # WAS the module. Here it has to ask the module: `hasattr(M, n)` and
    # `getattr(M, n, None)`. Carried literally, `_missing` would list all 40
    # names and rx1 would go red on a re-export that is perfectly intact.
    _missing = [n for n in _core_public + _analytics_public
                if not hasattr(M, n)]
    check("rx1 every public name _usage_core and _usage_analytics define is served "
          "by usage_ledger too - the re-export is what lets a three-way split "
          "change no call site",
          _missing == [], "missing: %r" % (_missing,))
    check("rx2 ...and each one IS the object the defining module holds, not a "
          "same-named copy that could drift",
          all(getattr(M, n, None) is getattr(_core_mod, n) for n in _core_public)
          and all(getattr(M, n, None) is getattr(_analytics_mod, n)
                  for n in _analytics_public))
    # The second direction, and it is the one that looks vacuous: rx1 passes by
    # construction if the two modules define NOTHING (a filter that narrows to
    # empty must never read as 'all clear'). Only a literal count fails then.
    check("rx3 ...and there are 17 + 23 of them, so rx1 cannot be green over an "
          "empty or gutted module",
          len(_core_public) == 17 and len(_analytics_public) == 23,
          "got %d + %d" % (len(_core_public), len(_analytics_public)))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_usage_ledger.py --selftest\n")
    raise SystemExit(2)
