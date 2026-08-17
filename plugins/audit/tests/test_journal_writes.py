#!/usr/bin/env python3
"""
The cases for `hooks/journal-writes.py`, moved out of it - a hook, hyphenated.

The module comes through `_loader.load` by path out of `_harness.HOOKS_DIR`;
`_config` is imported directly, the way the hook imports it, because the fixtures
build configs with `_config._deep_merge(_config.DEFAULTS, ...)` and the `d` group
loads the journal module the hook's own way, through `_config._load_journal_lib()`.

ONE CASE WOULD HAVE PASSED SILENTLY IF MOVED LITERALLY. `j4` read
`getattr(sys.modules[__name__], "record_plugin_write", lambda *a: None)(...)` - the
INTROSPECTION form the guide lists, and the half that fails green. `sys.modules[__name__]`
meant "this module" while the case sat inside the hook; from `tests/` it is the TEST
module, which has no `record_plugin_write`, so `getattr`'s default hands back a lambda
that returns None and the case passes without ever calling the hook. Measured: with
the literal form restored, `j4` is still PASS with the production function DELETED.
It now names the subject, `M.record_plugin_write(...)`, and drops the swallowing
default so a vanished function raises and `_harness.run` reports it by name.

The other five shapes came back empty: no `vars()`, no bare `__file__`, no path built
off the suite's own directory, no `split(a)[1].split(b)[0]`, and no `globals()` REBIND -
`c8` swaps `_config._LEDGER_LIB`, which is an attribute on a module BOTH sides import,
restored in a `finally`, and therefore works from here unchanged.

`e1` gave up its hand-rolled `results.append(ok)` + `print("%s e1 ...")` pair for
`check()` through `_harness.attempt`; the label is unchanged and the raise text is now
a detail, printed only on failure.

The hook's own `_journal_lib()` and `record_plugin_write()` both have production call
sites in `main()`, so no import edge retired with this suite.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _config                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "journal-writes.py"),
                 modname="journal_writes")


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = tempfile.mkdtemp(prefix="journal-writes-selftest-")
    prev_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = tmp
    cfg = _config._deep_merge(_config.DEFAULTS, {})

    def payload(tool, path, *, sid="sess-1", edits=None):
        if tool == "NotebookEdit":
            ti = {"notebook_path": path, "new_source": "x"}
        elif tool == "MultiEdit":
            ti = {"file_path": path, "edits": edits or [{}, {}]}
        else:
            ti = {"file_path": path, "content": "x"}
        return {"tool_name": tool, "tool_input": ti, "session_id": sid,
                "cwd": tmp}

    def verdict(tool, path, *, use_cfg=None, **kw):
        try:
            return M.decide(payload(tool, path, **kw), cfg=use_cfg or cfg,
                            root=tmp)
        except Exception as exc:                       # pragma: no cover
            return ("EXC", str(exc))

    try:
        # --- what is recorded -------------------------------------------------
        v, e = verdict("Edit", "docs/audit/audit-plan.json")
        check("a1 an edit to the manifest index is journalled",
              v == "journal" and e["action"] == "manifest.edit"
              and e["target"] == "docs/audit/audit-plan.json", repr((v, e)))
        v, e = verdict("Write", "docs/audit/phases/P3.json")
        check("a2 a phase shard is the manifest too - under the sharded layout "
              "almost every write IS a shard, and only the index has that name",
              v == "journal" and e["action"] == "manifest.edit"
              and e["target"] == "docs/audit/phases/P3.json", repr((v, e)))
        v, e = verdict("Edit", ".claude/audit.config.json")
        check("a3 the config is journalled under its own action - the rules "
              "changing is a different event from the plan changing",
              v == "journal" and e["action"] == "config.edit", repr((v, e)))
        v, e = verdict("Edit", os.path.join(tmp, "docs", "audit", "audit-plan.json"))
        check("a4 an ABSOLUTE path is recognised and recorded repo-relative "
              "(the tool reports absolute paths)",
              v == "journal" and e["target"] == "docs/audit/audit-plan.json",
              repr((v, e)))
        v, e = verdict("NotebookEdit", "docs/audit/audit-plan.json")
        check("a5 a notebook edit reads its own path key", v == "journal")

        # --- what is not ------------------------------------------------------
        for path, why in ((".claude/audit.config.json.bak", "a backup is not the config"),
                          ("src/app.py", "ordinary source"),
                          ("docs/audit/notes.md", "a sibling of the manifest"),
                          ("docs/audit/phases/notes.txt", "not a shard"),
                          ("docs/audit/audit-plan.json.lock", "the lock file")):
            v, _ = verdict("Write", path)
            check("b %s is not journalled (%s)" % (path, why), v == "skip")
        v, _ = verdict("Bash", "docs/audit/audit-plan.json")
        check("b6 a non-edit tool is not this hook's business", v == "skip")
        v, _ = verdict("Edit", "")
        check("b7 a payload with no path is skipped, not guessed at", v == "skip")
        v, r = verdict("Edit", "docs/audit/journal/2026-08.a.jsonl")
        check("b8 the journal is never its own subject", v == "skip"
              and "not its own subject" in r)
        v, _ = verdict("Edit", "docs/audit/audit-plan.json", use_cfg=_config._deep_merge(
            cfg, {"journal": {"enabled": False}}))
        check("b9 a disabled journal records nothing", v == "skip")
        # A moved manifest takes its shards and its journal with it.
        moved = _config._deep_merge(cfg, {"manifestPath": "plan/audit.json"})
        v, e = verdict("Edit", "plan/phases/P1.json", use_cfg=moved)
        check("b10 a shard of a MOVED manifest is still the manifest",
              v == "journal" and e["action"] == "manifest.edit")
        v, _ = verdict("Edit", "docs/audit/audit-plan.json", use_cfg=moved)
        check("b11 ...and the old location stops being special", v == "skip")

        # --- what the row says ------------------------------------------------
        v, e = verdict("MultiEdit", "docs/audit/audit-plan.json",
                       edits=[{}, {}, {}])
        check("c1 a MultiEdit says how many edits it was - 'MultiEdit' alone hides "
              "how much moved", "MultiEdit (3 edits)" in e["summary"], e["summary"])
        check("c2 one edit is not pluralised",
              "(1 edit)" in M.decide(
                  payload("MultiEdit", "docs/audit/audit-plan.json",
                          edits=[{}]), cfg=cfg, root=tmp)[1]["summary"])
        check("c3 the row carries only the news, never the chain fields that "
              "audit-journal.py owns",
              set(e) == {"action", "target", "summary", "actor"}, repr(sorted(e)))
        check("c4 the actor names the session and how the write arrived",
              e["actor"]["sessionId"] == "sess-1" and e["actor"]["via"] == "hook")
        v, e = verdict("Edit", "docs/audit/audit-plan.json", sid="")
        check("c5 a payload with no session id still produces a row",
              v == "journal" and e["actor"]["sessionId"] is None)
        _none = _config._deep_merge(cfg, {"usage": {"authorMode": "none"}})
        v, e = verdict("Edit", "docs/audit/audit-plan.json", use_cfg=_none)
        check("c6 authorMode none is honoured here too - a project that refuses to "
              "record who spends must not have it recorded here instead",
              v == "journal" and e["actor"]["author"] is None, repr(e["actor"]))
        # F-B2: the ledger module behind _author loads through _config's cache.
        # Honest accounting: production calls _author once per hook process, so
        # the cache is a selftest/parity win (suites drive it dozens of times,
        # each uncached call re-executing a ~1800-line module) - plus the same
        # single-module identity _journal_lib and _areas_lib already have.
        _llib_fn = getattr(_config, "_ledger_lib", None)
        _llib = _llib_fn() if _llib_fn else None
        check("c7 _config caches the ledger module - the same object across "
              "two calls, and _author's answer is resolve_author's answer",
              _llib is not None and _llib is _llib_fn()
              and M._author(tmp, cfg) == _llib.resolve_author(str(tmp), "email"))
        _saved_lib = dict(getattr(_config, "_LEDGER_LIB", None) or {})

        class _StubLedger:
            @staticmethod
            def resolve_author(_root, mode):
                return "stub-author:" + mode

        try:
            if hasattr(_config, "_LEDGER_LIB"):
                _config._LEDGER_LIB.update({"tried": True, "mod": _StubLedger})
            check("c8 _author reads THROUGH the cache - swap the cached module "
                  "and the answer follows it",
                  M._author(tmp, cfg) == "stub-author:email")
        finally:
            if hasattr(_config, "_LEDGER_LIB"):
                _config._LEDGER_LIB.clear()
                _config._LEDGER_LIB.update(_saved_lib)

        # --- end to end: the hook actually writes a verifiable chain -----------
        # decide() alone proves the decision, not the wiring. Two writes go all the
        # way through the real module, and the chain is then verified.
        proj = os.path.join(tmp, "e2e")
        os.makedirs(os.path.join(proj, "docs", "audit"))
        with open(os.path.join(proj, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"meta":{"version":3}}')
        jmod = _config._load_journal_lib()
        check("d0 the journal module loads from the hooks side at all",
              jmod is not None)
        for i in range(2):
            v, e = M.decide(payload("Edit", "docs/audit/audit-plan.json",
                                    sid="e2e-%d" % i), cfg=cfg, root=proj)
            if v == "journal":
                jmod.append(proj, e)
        res = jmod.verify(proj)
        check("d1 two writes leave two rows, in two files - one per session, which "
              "is what keeps parallel worktrees conflict-free",
              res["rows"] == 2 and len(res["files"]) == 2, repr(res))
        check("d2 and the chain verifies", res["ok"] and not res["findings"],
              repr(res["findings"]))
        rows = jmod.read_all(proj)
        check("d3 the row records the manifest as it stood after the write, so a "
              "later change with no row to explain it is visible",
              all(r.get("stateHash") for r in rows), repr(rows))
        with open(os.path.join(proj, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"meta":{"version":3},"phases":[]}')
        check("d4 ...and it is: an out-of-band edit warns, without accusing",
              jmod.verify(proj)["ok"]
              and any("never saw" in w for w in jmod.verify(proj)["warnings"]))

        # --- failure is silent, always ---------------------------------------
        # A recorder that raises into a PostToolUse hook is a recorder that breaks
        # the write it was recording.
        _e1_ok, _bad = _harness.attempt(
            M.decide, {"tool_name": "Edit", "tool_input": None}, cfg=cfg,
            root=tmp)
        check("e1 a malformed payload is skipped, never raised",
              _e1_ok and _bad[0] == "skip", "" if _e1_ok else _bad)
        # Driven through main() rather than read off the source: this is the whole
        # stdin-to-exit contract, and the one thing it must not do is speak.
        import io
        _stdin, _stdout = sys.stdin, sys.stdout
        _cap = io.StringIO()
        _code = None
        try:
            sys.stdin = io.StringIO(json.dumps(
                {"tool_name": "Edit", "session_id": "e2",
                 "tool_input": {"file_path": "docs/audit/audit-plan.json",
                                "new_string": "x"},
                 "cwd": proj}))
            sys.stdout = _cap
            os.environ["CLAUDE_PROJECT_DIR"] = proj
            try:
                M.main()
            except SystemExit as exc:
                _code = exc.code
        finally:
            sys.stdin, sys.stdout = _stdin, _stdout
            os.environ["CLAUDE_PROJECT_DIR"] = tmp
        check("e2 the hook exits 0 and prints NOTHING - a recorder that talks "
              "turns every manifest edit into a line of transcript nobody asked "
              "for", _code in (0, None) and _cap.getvalue() == "",
              repr((_code, _cap.getvalue()[:120])))
        check("e3 ...and it really did record that write - a hook that stays quiet "
              "by doing nothing would pass the case above",
              jmod.verify(proj)["rows"] == 3, repr(jmod.verify(proj)))

        # --- g: the Pre pass caches the pre-image ------------------------------
        # Edit fragments are not parseable JSON, so the only way to diff is to
        # remember the file as it stood BEFORE the write.
        pproj = os.path.join(tmp, "prepost")
        os.makedirs(os.path.join(pproj, "docs", "audit"))
        man_rel = "docs/audit/audit-plan.json"
        man_abs = os.path.join(pproj, man_rel)

        def write_manifest(obj):
            with open(man_abs, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        def manifest_doc(status="in_progress", commit=None, completed=None,
                         phase_status="in_progress", merged=None):
            return {"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "p", "status": phase_status,
                 "mergedAt": merged,
                 "tasks": [{"id": "P1.1", "title": "t", "status": status,
                            "commit": commit, "completedAt": completed}]}]}

        write_manifest(manifest_doc())
        slot = M.pre_cache(payload("Edit", man_rel, sid="pp-1"), cfg=cfg,
                           root=pproj)
        check("g1 the Pre pass caches a manifest target and returns the slot",
              slot is not None and os.path.exists(slot), repr(slot))
        with open(slot, encoding="utf-8") as fh:
            slot_obj = json.load(fh)
        check("g2 the slot holds the path, a hash and the bytes themselves",
              slot_obj.get("path") == man_rel
              and str(slot_obj.get("sha256") or "").startswith("sha256:")
              and json.loads(slot_obj["content"])["phases"][0]["id"] == "P1",
              repr(slot_obj)[:200])
        check("g3 an ordinary source file leaves no slot",
              M.pre_cache(payload("Edit", "src/app.py", sid="pp-1"), cfg=cfg,
                          root=pproj) is None)
        check("g4 a disabled journal caches nothing (the Pre pass reads the "
              "pre-image config: on Pre, disk IS the pre-image)",
              M.pre_cache(payload("Edit", man_rel, sid="pp-1"),
                          cfg=_config._deep_merge(cfg, {"journal":
                                                        {"enabled": False}}),
                          root=pproj) is None)
        write_manifest(manifest_doc(status="pending"))
        M.pre_cache(payload("Edit", man_rel, sid="pp-1"), cfg=cfg, root=pproj)
        with open(slot, encoding="utf-8") as fh:
            slot_obj2 = json.load(fh)
        check("g5 a second Pre OVERWRITES the stale slot - a denied tool call "
              "self-heals on the next attempt",
              json.loads(slot_obj2["content"])
              ["phases"][0]["tasks"][0]["status"] == "pending")
        os.makedirs(os.path.join(pproj, "docs", "audit", "phases"),
                    exist_ok=True)
        big_rel = "docs/audit/phases/P9.json"
        with open(os.path.join(pproj, big_rel), "w", encoding="utf-8") as fh:
            fh.write('{"id":"P9","tasks":[],"pad":"'
                     + "x" * (5 * 1024 * 1024) + '"}')
        slot_big = M.pre_cache(payload("Edit", big_rel, sid="pp-1"), cfg=cfg,
                               root=pproj)
        with open(slot_big, encoding="utf-8") as fh:
            check("g6 a pre-image over the 5 MB cap is not cached whole - the "
                  "slot records the miss and the Post pass falls back",
                  json.load(fh).get("content") is None)

        # --- h: the Post pass diffs, summarises, and derives events ------------
        write_manifest(manifest_doc(status="in_progress"))
        M.pre_cache(payload("Edit", man_rel, sid="pp-2"), cfg=cfg, root=pproj)
        write_manifest(manifest_doc(status="done",
                                    completed="2026-08-11T00:00:00Z"))
        entries = M.post_entries(payload("Edit", man_rel, sid="pp-2"), cfg=cfg,
                                 root=pproj)
        check("h1 a status flip yields a semantic summary, not 'Edit wrote ...'",
              len(entries) >= 1
              and "P1.1: status in_progress->done" in entries[0]["summary"]
              and "completedAt set" in entries[0]["summary"],
              repr([e.get("summary") for e in entries]))
        check("h2 ...with the structured changes in details",
              {"id": "P1.1", "field": "status", "from": "in_progress",
               "to": "done"} in (entries[0].get("details") or {})
              .get("changes", []), repr(entries[0].get("details")))
        comp = [e for e in entries if e.get("action") == "task.complete"]
        check("h3 ...and a task.complete row derived from the same diff - the "
              "HOOK is the only writer of these",
              len(comp) == 1 and comp[0]["details"] == {
                  "taskId": "P1.1", "phaseId": "P1", "from": "in_progress",
                  "to": "done", "completedAt": "2026-08-11T00:00:00Z"},
              repr(comp))
        check("h4 the Post pass consumed and deleted the slot",
              not os.path.exists(M._slot_path(pproj, cfg,
                                              {"session_id": "pp-2"}, man_rel)))

        write_manifest(manifest_doc(status="done", completed="X"))
        M.pre_cache(payload("Write", man_rel, sid="pp-3"), cfg=cfg, root=pproj)
        write_manifest(manifest_doc(status="done", completed="X",
                                    commit="a" * 40))
        entries = M.post_entries(payload("Write", man_rel, sid="pp-3"), cfg=cfg,
                                 root=pproj)
        commit_rows = [e for e in entries if e.get("action") == "task.commit"]
        check("h5 a Write is diffed by full content: commit null->SHA yields a "
              "task.commit row",
              len(commit_rows) == 1
              and commit_rows[0]["details"]["commit"] == "a" * 40
              and commit_rows[0]["details"]["taskId"] == "P1.1", repr(entries))
        check("h5b ...and no task.complete - the status did not move this time",
              not [e for e in entries if e.get("action") == "task.complete"])

        write_manifest(manifest_doc(status="done", completed="X",
                                    commit="a" * 40))
        M.pre_cache(payload("Edit", man_rel, sid="pp-4"), cfg=cfg, root=pproj)
        write_manifest(manifest_doc(status="done", completed="X",
                                    commit="a" * 40, phase_status="done",
                                    merged="2026-08-11T01:00:00Z"))
        entries = M.post_entries(payload("Edit", man_rel, sid="pp-4"), cfg=cfg,
                                 root=pproj)
        sign = [e for e in entries if e.get("action") == "phase.signoff"]
        check("h6 a phase flipped to done yields a phase.signoff row carrying "
              "mergedAt",
              len(sign) == 1 and sign[0]["details"] == {
                  "phaseId": "P1", "from": "in_progress", "to": "done",
                  "mergedAt": "2026-08-11T01:00:00Z"}, repr(sign))

        # --- i: connector v2 events (task.blocked + ado.link) ------------------
        # Derived from the same diff as everything else, tested on the core
        # directly. D-1 rule: `ado` is NOT in TASK_FIELDS - only the id is
        # compared, so an echo's lastSyncedAt bump writes no row at all.
        i_base = manifest_doc(status="in_progress")
        i_blocked = manifest_doc(status="blocked")
        i_blocked["phases"][0]["tasks"][0]["attempts"] = 3
        d_i1 = M.semantic_diff(i_base, i_blocked)
        blk = [e for e in (d_i1 or {}).get("events", [])
               if e.get("action") == "task.blocked"]
        check("i1 a task entering blocked yields a task.blocked row - "
              "symmetric with task.complete",
              len(blk) == 1 and blk[0]["details"] == {
                  "taskId": "P1.1", "phaseId": "P1",
                  "from": "in_progress", "attempts": 3},
              repr(d_i1 and d_i1.get("events")))
        d_i2 = M.semantic_diff(i_blocked, i_base)
        check("i2 LEAVING blocked is a change row only, never a task.blocked "
              "event",
              d_i2 is not None and not [e for e in d_i2.get("events", [])
                                        if e.get("action") == "task.blocked"])
        i_linked = manifest_doc(status="in_progress")
        i_linked["phases"][0]["tasks"][0]["ado"] = {
            "id": 7, "url": "u", "lastSyncedAt": "t1"}
        d_i3 = M.semantic_diff(i_base, i_linked)
        link_rows = [e for e in (d_i3 or {}).get("events", [])
                     if e.get("action") == "ado.link"]
        check("i3 a task link (ado.id None->int) yields an ado.link row and "
              "an ado.id change row",
              len(link_rows) == 1 and link_rows[0]["details"] == {
                  "taskId": "P1.1", "phaseId": "P1", "adoId": 7}
              and any(c.get("field") == "ado.id" for c in d_i3["changes"]),
              repr(d_i3))
        i_bumped = json.loads(json.dumps(i_linked))
        i_bumped["phases"][0]["tasks"][0]["ado"]["lastSyncedAt"] = "t2"
        check("i4 a lastSyncedAt-only bump is NO row at all - the plan did "
              "not move, and the echo must not spam the journal",
              M.semantic_diff(i_linked, i_bumped) is None)
        i_ph = manifest_doc(status="in_progress")
        i_ph["phases"][0]["ado"] = {"id": 9, "url": "u", "lastSyncedAt": "t"}
        d_i5 = M.semantic_diff(i_base, i_ph)
        ph_rows = [e for e in (d_i5 or {}).get("events", [])
                   if e.get("action") == "ado.link"]
        check("i5 a phase PBI link yields an ado.link row too",
              len(ph_rows) == 1 and ph_rows[0]["details"] == {
                  "phaseId": "P1", "adoId": 9}, repr(d_i5))
        i_garbage = manifest_doc(status="in_progress")
        i_garbage["phases"][0]["tasks"][0]["ado"] = "WI-7"
        check("i6 a non-dict ado never crashes the diff and never links",
              M.semantic_diff(i_base, i_garbage) is None)

        write_manifest(manifest_doc())
        entries = M.post_entries(payload("Edit", man_rel, sid="pp-5"), cfg=cfg,
                                 root=pproj)
        check("h7 a cache miss falls back to the generic summary, no details, "
              "no events",
              len(entries) == 1
              and entries[0]["summary"].startswith("Edit wrote ")
              and "details" not in entries[0], repr(entries))
        slot2 = M.pre_cache(payload("Edit", man_rel, sid="pp-6"), cfg=cfg,
                            root=pproj)
        with open(slot2, "w", encoding="utf-8") as fh:
            json.dump({"path": man_rel, "ts": "t", "sha256": "sha256:x",
                       "content": "{not json"}, fh)
        entries = M.post_entries(payload("Edit", man_rel, sid="pp-6"), cfg=cfg,
                                 root=pproj)
        check("h8 an unparseable pre-image falls back to the generic summary",
              len(entries) == 1
              and entries[0]["summary"].startswith("Edit wrote "))
        slot3 = M.pre_cache(payload("Edit", man_rel, sid="pp-7"), cfg=cfg,
                            root=pproj)
        with open(slot3, "w", encoding="utf-8") as fh:
            json.dump({"path": man_rel, "ts": "t", "sha256": None,
                       "content": None}, fh)
        entries = M.post_entries(payload("Edit", man_rel, sid="pp-7"), cfg=cfg,
                                 root=pproj)
        check("h9 an over-the-cap pre-image falls back too",
              len(entries) == 1
              and entries[0]["summary"].startswith("Edit wrote "))

        # --- k: the disable loophole, closed -----------------------------------
        # journal.enabled is judged against the PRE-IMAGE when the config itself
        # is the target, so the flip that would have silenced its own record is
        # written down as a final row - the last will.
        cfg_rel = _config.CONFIG_REL
        cfg_abs = os.path.join(pproj, cfg_rel)
        os.makedirs(os.path.dirname(cfg_abs), exist_ok=True)

        def write_cfg_file(obj):
            with open(cfg_abs, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        write_cfg_file({"journal": {"enabled": True}})
        M.pre_cache(payload("Edit", cfg_rel, sid="pp-9"), cfg=cfg, root=pproj)
        write_cfg_file({"journal": {"enabled": False}})
        post_cfg = _config._deep_merge(cfg, {"journal": {"enabled": False}})
        entries = M.post_entries(payload("Edit", cfg_rel, sid="pp-9"),
                                 cfg=post_cfg, root=pproj)
        check("k1 flipping journal.enabled true->false IS journalled, with the "
              "flip in details",
              len(entries) == 1 and entries[0]["action"] == "config.edit"
              and (entries[0].get("details") or {}).get("changes") ==
              [{"field": "journal.enabled", "from": True, "to": False}]
              and "journal.enabled" in entries[0]["summary"], repr(entries))
        write_cfg_file({"journal": {"enabled": False}})
        check("k2 a config edit while the journal was already off records "
              "nothing - the user's switch is honoured",
              M.pre_cache(payload("Edit", cfg_rel, sid="pp-10"), cfg=post_cfg,
                          root=pproj) is None
              and M.post_entries(payload("Edit", cfg_rel, sid="pp-10"),
                                 cfg=post_cfg, root=pproj) == [])
        write_cfg_file({"journal": {"enabled": True}})
        entries = M.post_entries(payload("Edit", cfg_rel, sid="pp-11"), cfg=cfg,
                                 root=pproj)
        check("k3 flipping it back ON is recorded (generically - there was no "
              "pre-image while it was off)",
              len(entries) == 1 and entries[0]["action"] == "config.edit")

        # --- w: the wiring - main() routes by hook_event_name ------------------
        wproj = os.path.join(tmp, "wire")
        os.makedirs(os.path.join(wproj, "docs", "audit"))
        wman = os.path.join(wproj, "docs", "audit", "audit-plan.json")

        def wwrite(status):
            with open(wman, "w", encoding="utf-8") as fh:
                json.dump({"meta": {"version": 2}, "phases": [
                    {"id": "P1", "title": "p", "status": "in_progress",
                     "tasks": [{"id": "P1.1", "title": "t", "status": status,
                                "commit": None,
                                "completedAt": "2026-08-11T02:00:00Z"
                                if status == "done" else None}]}]}, fh)

        def drive(event):
            import io
            _stdin, _stdout = sys.stdin, sys.stdout
            cap = io.StringIO()
            code = None
            try:
                sys.stdin = io.StringIO(json.dumps(
                    {"tool_name": "Edit", "session_id": "wire-1",
                     "hook_event_name": event,
                     "tool_input": {"file_path": "docs/audit/audit-plan.json",
                                    "new_string": "x"},
                     "cwd": wproj}))
                sys.stdout = cap
                os.environ["CLAUDE_PROJECT_DIR"] = wproj
                try:
                    M.main()
                except SystemExit as exc:
                    code = exc.code
            finally:
                sys.stdin, sys.stdout = _stdin, _stdout
                os.environ["CLAUDE_PROJECT_DIR"] = tmp
            return code, cap.getvalue()

        wwrite("in_progress")
        code, spoke = drive("PreToolUse")
        wslots = [f for f in os.listdir(os.path.join(wproj, ".claude", "state"))
                  if f.startswith("journal-preimage-")] if os.path.isdir(
                      os.path.join(wproj, ".claude", "state")) else []
        check("w1 the Pre pass through main() exits 0, prints nothing, and "
              "leaves a slot",
              code in (0, None) and spoke == "" and len(wslots) == 1,
              repr((code, spoke[:80], wslots)))
        wwrite("done")
        code, spoke = drive("PostToolUse")
        wres = jmod.verify(wproj)
        wrows = jmod.read_all(wproj)
        check("w2 the Post pass through main() appends the semantic row AND the "
              "task.complete row, and the chain verifies",
              code in (0, None) and spoke == "" and wres["ok"]
              and [r.get("action") for r in wrows] ==
              ["manifest.edit", "task.complete"]
              and wrows[1].get("details", {}).get("taskId") == "P1.1",
              repr((wres, [r.get("action") for r in wrows])))

        # --- j: the F-F3 sidecar -----------------------------------------------
        # The append above put the journal file into git status, and
        # guard-bash-writes' next Bash pass used to blame the shell command for
        # it. After every successful append, main() records the written file's
        # rel path in <stateDir>/bash-writes-plugin-<sid>.json -- ONE writer
        # (this hook), because hooks on the same event run in parallel and a
        # shared state file would race. guard-bash-writes reads it and skips
        # exactly those rels; its k group drives THIS writer, so the two sides
        # cannot drift about where the sidecar lives.
        _wsd = os.path.join(wproj, ".claude", "state")
        _wsides = ([f for f in os.listdir(_wsd)
                    if f.startswith("bash-writes-plugin-")]
                   if os.path.isdir(_wsd) else [])
        _wjfiles = jmod.journal_files(jmod.journal_dir(wproj, cfg))
        _wjrels = [os.path.relpath(p, wproj).replace(os.sep, "/")
                   for p in _wjfiles]
        _wslot = (os.path.join(_wsd, _wsides[0]) if _wsides else None)
        try:
            with open(_wslot, "r", encoding="utf-8") as fh:
                _wobj = json.load(fh)
        except Exception:
            _wobj = {}
        check("j1 the Post pass leaves a sidecar naming the journal file the "
              "append landed in",
              len(_wsides) == 1
              and sorted(_wobj.get("pluginWrote") or []) == sorted(_wjrels),
              repr((_wsides, _wobj, _wjrels)))
        check("j2 the sidecar name carries the bash-writes- prefix, so the "
              "existing state GC sweeps it",
              bool(_wsides) and _wsides[0].startswith("bash-writes-")
              and ("wire-1" in _wsides[0]))
        wwrite("in_progress")
        drive("PreToolUse")
        wwrite("done")
        drive("PostToolUse")
        try:
            with open(_wslot, "r", encoding="utf-8") as fh:
                _wobj2 = json.load(fh)
        except Exception:
            _wobj2 = {}
        check("j3 a second append to the same file does not duplicate the "
              "entry",
              sorted(_wobj2.get("pluginWrote") or []) == sorted(_wjrels),
              repr(_wobj2))
        # `sys.modules[__name__]` was this module when the case lived inside the
        # hook. Carried literally it names the TEST module, whose `getattr`
        # default hands back `lambda *a: None` - which returns None, so the case
        # passes while asking the hook nothing at all. Named on the subject, and
        # without the swallowing default: a vanished function is an AttributeError
        # `_harness.run` reports as a failing case, which is what it should be.
        check("j4 record_plugin_write never raises on garbage - it guards a "
              "PostToolUse hook",
              M.record_plugin_write(None, None, None, None) is None)
        # A disabled journal appends nothing, so there is nothing to record.
        _joff = os.path.join(tmp, "joff")
        os.makedirs(os.path.join(_joff, "docs", "audit"), exist_ok=True)
        _joffcfg = _config._deep_merge(cfg, {"journal": {"enabled": False}})
        check("j5 a disabled journal leaves no sidecar (nothing was appended)",
              M.post_entries(payload("Edit", "docs/audit/audit-plan.json",
                                     sid="j5"), cfg=_joffcfg, root=_joff) == []
              and not os.path.isdir(os.path.join(_joff, ".claude", "state")))
    finally:
        if prev_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev_env
        shutil.rmtree(tmp, ignore_errors=True)

    # (i) the sidecar's state dir is self-ignoring
    tmp_i = tempfile.mkdtemp(prefix="jw-ignore-")
    try:
        _cfg_i = dict(_config.DEFAULTS)
        M.record_plugin_write(tmp_i, _cfg_i, {"session_id": "s-i"},
                              os.path.join(tmp_i, "docs", "audit", "journal",
                                           "j.jsonl"))
        check("i1 record_plugin_write's state dir carries a `*` .gitignore",
              os.path.exists(os.path.join(
                  tmp_i, str(_cfg_i["stateDir"]), ".gitignore")))
    finally:
        shutil.rmtree(tmp_i, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_journal_writes.py --selftest\n")
    raise SystemExit(2)
