#!/usr/bin/env python3
"""
Migrate an audit manifest from the legacy single-file layout to the SHARDED layout
(index + per-phase shards) — dependency-free (stdlib only).

The sharded layout keeps the shared, rarely-churned data (meta, bugs, fileIndex) in the
index and each phase's body in `phases/<phaseId>.json`, so a phase command loads only its
own phase (fewer tokens) and two parallel phase branches edit different files (no manifest
merge conflict). Reading is transparent — every script + hook already loads both layouts
via _manifest_io — so migration is opt-in and reversible (a backup is written).

Usage:
  migrate-manifest.py <manifest> [--dry-run] [--force] [--renumber]
  migrate-manifest.py --selftest

Safe by default:
  - ALREADY sharded  -> nothing to do (exit 0)
  - validates the SOURCE first; refuses to migrate a manifest with findings (exit 1)
    (--renumber first repairs duplicate BUG- ids — the common cross-machine collision)
  - refuses if any phase is `in_progress` (a mid-run migration corrupts the run);
    override with --force
  - backs up the original to <manifest>.bak-<UTC> before writing
  - validates the RESULT; on any failure it RESTORES the backup and exits non-zero

Exit codes: 0 ok / already-sharded · 1 refused or validation failure · 2 usage/unreadable.
"""
import datetime
import os
import re
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402


def _load_validator():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "validate_manifest", os.path.join(_HERE, "validate-manifest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _utc_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _in_progress_phases(manifest):
    return [p.get("id") for p in manifest.get("phases", [])
            if isinstance(p, dict) and p.get("status") == "in_progress"]


def renumber_duplicate_bugs(manifest):
    """Repair duplicate BUG- ids (the common cross-machine collision) by renaming the
    later duplicate to the next free number and fixing its reciprocal task.bugId link.
    Returns [(old, new), ...]. Other duplicate-id classes (phase/task) are left for
    manual repair — auto-renumbering them would have to rewrite dependsOn/blockedBy/
    fileIndex and is too risky to automate blindly."""
    bugs = manifest.get("bugs") or []
    mx = 0
    for b in bugs:
        m = re.match(r"^BUG-(\d+)$", str(b.get("id", "")))
        if m:
            mx = max(mx, int(m.group(1)))
    task_by_id = {}
    for ph in manifest.get("phases", []):
        for t in (ph.get("tasks") or []) if isinstance(ph, dict) else []:
            if isinstance(t, dict) and t.get("id"):
                task_by_id[t["id"]] = t
    seen, changed = set(), []
    for b in bugs:
        bid = b.get("id")
        if bid in seen:
            mx += 1
            new = "BUG-%d" % mx
            tid = b.get("taskId")
            if tid in task_by_id and task_by_id[tid].get("bugId") == bid:
                task_by_id[tid]["bugId"] = new
            b["id"] = new
            changed.append((bid, new))
        else:
            seen.add(bid)
    return changed


def migrate(path, *, dry_run=False, force=False, renumber=False, out=None):
    """Do the migration. Returns (exit_code, message)."""
    # detect already-sharded from the RAW index (before assembly)
    try:
        raw = _mio._read_json(path)
    except Exception as exc:
        return 2, "cannot read/parse %s: %s" % (path, exc)
    if _mio.is_sharded(raw):
        return 0, "already sharded: %s (nothing to do)" % path
    try:
        manifest = _mio.load_manifest(path)
    except Exception as exc:
        return 2, "cannot load %s: %s" % (path, exc)
    if not isinstance(manifest, dict):
        return 2, "%s is not a JSON object" % path

    vm = _load_validator()
    if renumber:
        changed = renumber_duplicate_bugs(manifest)
        if changed:
            sys.stderr.write("renumbered duplicate bug ids: %s\n"
                             % ", ".join("%s->%s" % c for c in changed))
    findings, _ = vm.validate(manifest)
    if findings:
        return 1, ("source manifest has %d finding(s); fix them before migrating"
                   "%s:\n  - %s" % (len(findings),
                   " (or pass --renumber for duplicate BUG- ids)"
                   if any("duplicate" in f.lower() and "BUG-" in f for f in findings) else "",
                   "\n  - ".join(findings[:8])))

    blocked = _in_progress_phases(manifest)
    if blocked and not force:
        return 1, ("refusing: phase(s) %s are in_progress — migrating mid-run corrupts the "
                   "run. Finish/pause them, or pass --force." % ", ".join(str(b) for b in blocked))

    index, shards = _mio.split_manifest(manifest)
    if dry_run:
        return 0, ("DRY RUN: would write index %s + %d shard(s): %s"
                   % (out or path, len(shards),
                      ", ".join("phases/%s.json" % _mio._shard_name(p) for p in shards)))

    target = out or path
    backup = None
    if out is None:                     # in-place: back up the original first
        backup = "%s.bak-%s" % (path, _utc_stamp())
        shutil.copy2(path, backup)
    try:
        written = _mio.save_sharded(target, manifest)
        # validate the RESULT by reloading through the loader
        result = _mio.load_manifest(target)
        rfindings, _ = vm.validate(result)
        if rfindings:
            raise RuntimeError("post-migration validation failed: %s" % "; ".join(rfindings[:4]))
    except Exception as exc:
        if backup and os.path.exists(backup):
            shutil.copy2(backup, path)   # restore
        return 1, "migration failed (restored backup): %s" % exc

    msg = "migrated %s -> index + %d shard(s)" % (target, len(shards))
    if backup:
        msg += "\n  backup: %s" % backup
    msg += "\n  " + "\n  ".join(written)
    return 0, msg


def main(argv):
    if "--selftest" in argv:
        return _selftest()
    args = [a for a in argv if not a.startswith("--")]
    flags = set(a for a in argv if a.startswith("--"))
    out = None
    for a in argv:
        if a.startswith("--out="):
            out = a.split("=", 1)[1]
    if len(args) != 1:
        sys.stderr.write("usage: migrate-manifest.py <manifest> "
                         "[--dry-run] [--force] [--renumber] [--out=<index>]\n")
        return 2
    code, msg = migrate(args[0], dry_run="--dry-run" in flags,
                        force="--force" in flags, renumber="--renumber" in flags, out=out)
    (sys.stderr if code else sys.stdout).write(msg + "\n")
    return code


# --- selftest -------------------------------------------------------------------
def _selftest():
    import json
    import tempfile

    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    def legacy():
        return {
            "meta": {"version": 2, "repo": "demo"},
            "phases": [
                {"id": "P1", "title": "One", "status": "done",
                 "tasks": [{"id": "P1.1", "title": "a", "status": "done", "files": ["src/a.ts"]}]},
                {"id": "P2", "title": "Two", "status": "pending",
                 "tasks": [{"id": "P2.1", "title": "b", "status": "pending",
                            "dependsOn": ["P1.1"], "files": ["src/b.ts"], "bugId": "BUG-1"}]},
            ],
            "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["P2.1"]},
            "bugs": [{"id": "BUG-1", "title": "bug", "status": "in_progress", "taskId": "P2.1",
                      "severity": "high"}],
        }

    tmp = tempfile.mkdtemp(prefix="migrate-selftest-")
    try:
        # 1. lossless in-place migration + backup + result validates
        p = os.path.join(tmp, "c1", "audit-plan.json")
        os.makedirs(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(legacy(), fh)
        code, msg = migrate(p)
        check("migrate exit 0", code == 0)
        check("index still at manifest path", os.path.isfile(p))
        check("shards written", os.path.isfile(os.path.join(tmp, "c1", "phases", "P1.json"))
              and os.path.isfile(os.path.join(tmp, "c1", "phases", "P2.json")))
        check("backup written", any(n.startswith("audit-plan.json.bak-")
              for n in os.listdir(os.path.join(tmp, "c1"))))
        reloaded = _mio.load_manifest(p)
        expect = legacy()
        expect["meta"]["version"] = 3
        check("reload == source (modulo meta.version)", reloaded == expect)

        # 2. already-sharded is a no-op
        code2, msg2 = migrate(p)
        check("second migrate: already-sharded exit 0", code2 == 0 and "already sharded" in msg2)

        # 3. refuses on in_progress phase (unless --force)
        p3 = os.path.join(tmp, "c3", "audit-plan.json")
        os.makedirs(os.path.dirname(p3))
        m3 = legacy()
        m3["phases"][1]["status"] = "in_progress"
        m3["phases"][1]["tasks"][0]["status"] = "in_progress"
        with open(p3, "w", encoding="utf-8") as fh:
            json.dump(m3, fh)
        code3, msg3 = migrate(p3)
        check("in_progress -> refused (exit 1)", code3 == 1 and "in_progress" in msg3)
        code3f, _ = migrate(p3, force=True)
        check("in_progress + --force -> migrates", code3f == 0)

        # 4. dry-run writes nothing
        p4 = os.path.join(tmp, "c4", "audit-plan.json")
        os.makedirs(os.path.dirname(p4))
        with open(p4, "w", encoding="utf-8") as fh:
            json.dump(legacy(), fh)
        code4, msg4 = migrate(p4, dry_run=True)
        check("dry-run exit 0 + no phases dir", code4 == 0
              and not os.path.isdir(os.path.join(tmp, "c4", "phases")))

        # 5. --renumber repairs duplicate BUG- ids and fixes reciprocal links
        m5 = legacy()
        m5["bugs"].append({"id": "BUG-1", "title": "dup", "status": "open",
                           "taskId": "P1.1", "severity": "low"})
        m5["phases"][0]["tasks"][0]["bugId"] = "BUG-1"
        changed = renumber_duplicate_bugs(m5)
        ids = [b["id"] for b in m5["bugs"]]
        check("renumber: duplicate BUG-1 -> distinct ids", len(set(ids)) == len(ids)
              and changed and changed[0][0] == "BUG-1")
        check("renumber: reciprocal task.bugId updated",
              m5["phases"][0]["tasks"][0]["bugId"] == changed[0][1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
