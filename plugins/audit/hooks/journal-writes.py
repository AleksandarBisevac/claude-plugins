#!/usr/bin/env python3
"""
PostToolUse recorder (matcher: Edit|Write|MultiEdit|NotebookEdit).

Appends one row to the tamper-evident journal for every edit-tool write to the
MANIFEST (index or phase shard) or to `.claude/audit.config.json`. Nothing else is
recorded: the journal is the audit trail of the plan and the rules, not a log of
the repository.

WHY A HOOK AND NOT A PROMPT. The orchestrator could be told to journal its writes,
and it would — most of the time. A model that forgets, or a session that never read
the instruction, produces a gap that looks exactly like a covered-up change; the
one thing an audit trail cannot afford is to be as reliable as compliance. This
runs mechanically, after the write, whatever wrote it and whatever it was told.

WHAT IT CANNOT SEE, stated here rather than discovered later:
  * shell writes (`sed -i`, `>`), which never reach a tool matcher. guard-bash-writes
    reports those separately, and `verify` sees the file move with no row to explain
    it (out-of-band drift).
  * a write while the plugin is disabled. Nothing in Claude Code can outlive the
    user's own switch, and SECURITY.md says so.

CONTRACT: PostToolUse, mode `open`, NO stdout. A recorder that talks turns every
manifest edit into a line of transcript nobody asked for, and additionalContext is
context the model then has to read. Failure is silent by design — a journal that
cannot be written must never break the write it was recording. ALWAYS exits 0.

Run `python3 journal-writes.py --selftest` to exercise the decision core.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts")


def _target_of(tool, ti):
    ti = ti if isinstance(ti, dict) else {}
    if tool == "NotebookEdit":
        return str(ti.get("notebook_path", "") or ti.get("file_path", ""))
    return str(ti.get("file_path", ""))


def _how(tool, ti):
    """The one detail worth keeping about the write itself. A MultiEdit is n edits
    in one call, and 'MultiEdit' alone would hide how much moved."""
    if tool == "MultiEdit":
        n = len((ti or {}).get("edits") or [])
        return "MultiEdit (%d edit%s)" % (n, "" if n == 1 else "s")
    return tool


def _author(root, cfg):
    """Who the ledger would call this person, under the project's own authorMode.

    The SAME function the usage ledger writes its author column with, so the
    journal's `who` and the ledger's `who` are one identity and `my spend` in the
    panel can line up with `my changes` here. Costs one `git config` read, and only
    on a manifest or config write — never on an ordinary edit."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "usage_ledger", os.path.join(_SCRIPTS, "usage_ledger.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mode = (_config.usage_cfg(cfg) or {}).get("authorMode") or "email"
        return mod.resolve_author(str(root), mode)
    except Exception:
        return None


def decide(data, *, cfg=None, root=None):
    """Pure decision core. Returns ("journal", entry) or ("skip", reason).

    `entry` is the row's news — action, target, summary, actor. Everything that
    makes it a CHAIN (v, ts, stateHash, prev, hash) belongs to audit-journal.py and
    is deliberately not invented here."""
    tool = data.get("tool_name", "")
    if tool not in _EDIT_TOOLS:
        return ("skip", "not an edit tool")
    root = root if root is not None else _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    if not _config.journal_enabled(cfg):
        return ("skip", "journal disabled")

    ti = data.get("tool_input", {}) or {}
    path = _target_of(tool, ti)
    if not path:
        return ("skip", "no path")
    rel = _config.rel_path(root, path)
    manifest_rel = cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]

    # The journal itself is never journalled. guard-edits refuses that write
    # anyway, so this only matters when the guards are off — and a recorder that
    # records the recording is a loop nobody wants to read.
    if _config.in_journal(root, cfg, rel):
        return ("skip", "the journal is not its own subject")

    if rel == manifest_rel or _config.governing_lock(manifest_rel, rel):
        action = "manifest.edit"
    elif rel == _config.CONFIG_REL:
        action = "config.edit"
    else:
        return ("skip", "not a manifest or config path")

    return ("journal", {
        "action": action,
        "target": rel,
        "summary": "%s wrote %s" % (_how(tool, ti), rel),
        "actor": {"author": _author(root, cfg),
                  "sessionId": str(data.get("session_id") or "") or None,
                  "via": "hook"},
    })


def _journal_lib():
    return _config._load_journal_lib()


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        verdict, payload = decide(data)
        if verdict == "journal":
            mod = _journal_lib()
            if mod is not None:
                mod.append(str(_config.repo_root(data)), payload)
    except Exception:
        pass
    sys.exit(0)


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import shutil
    import tempfile

    results = []

    def check(name, cond, detail=""):
        results.append(bool(cond))
        print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                           (" (%s)" % detail) if detail and not cond else ""))

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
            return decide(payload(tool, path, **kw), cfg=use_cfg or cfg, root=tmp)
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
              "(1 edit)" in decide(payload("MultiEdit", "docs/audit/audit-plan.json",
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
            v, e = decide(payload("Edit", "docs/audit/audit-plan.json",
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
        try:
            _bad = decide({"tool_name": "Edit", "tool_input": None}, cfg=cfg,
                          root=tmp)
            ok = _bad[0] == "skip"
        except Exception as exc:                       # pragma: no cover
            ok = False
            print("     raised: %s" % exc)
        results.append(ok)
        print("%s e1 a malformed payload is skipped, never raised"
              % ("PASS" if ok else "FAIL"))
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
                main()
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
    finally:
        if prev_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev_env
        shutil.rmtree(tmp, ignore_errors=True)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
