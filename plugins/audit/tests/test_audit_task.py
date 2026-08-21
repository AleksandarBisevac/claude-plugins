#!/usr/bin/env python3
"""
The cases for `audit-task.py`, moved out of it - an entry point.

`audit-task.py` is hyphenated, so it comes through `_loader.load_script` and the
test file substitutes underscores; see `test_migrate_manifest.py` for both halves
of that rule. `M` is the module under test. `_manifest_io` and `_panel_write` are
imported here the way `audit-task.py` imports them, because the fixtures write and
read through those modules' own objects (`_panel_write._atomic_write_json`,
`_mio.save_sharded`, `_panel_write._lockmod`) rather than through a second copy.

NOTHING IN THIS SUITE HAD TO CHANGE MEANING TO MOVE. The AST scan for the six
shapes the guide forbids carrying literally came back empty: no `globals()` and no
`vars()` (nothing is stubbed - the lock cases drive a real subprocess and the
journal cases read the real rows), no `__file__`, no path built off the suite's own
directory, and no `split(a)[1].split(b)[0]`. Every fixture lives under one
`tempfile.mkdtemp(prefix="audit-task-selftest-")` removed in a single `finally`,
including the two `git init` repositories the k-group needs. It loads no sibling
through `_loader`, so no `KNOWN_LAYER_DEBT` entry moved with it.

The `check(name, cond)` this file used was the 2-argument form, which the harness's
`check(label, cond, detail="")` is a superset of - the call sites are unchanged.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as audit-task imports it)
import _panel_write                                # noqa: E402  (as audit-task imports it)

M = _loader.load_script("audit-task.py", modname="audit_task")


# --- cases --------------------------------------------------------------------
# Letters taken in this file (NEW file -- fresh letter space): a (add + phase
# resolution), i (reserved/parked ids), t (template fields), s (skills
# three-state), x (fileIndex), r (validator rollback), k (lock), y (layout:
# sharded/single), j (--json + journal row), h (A4 heal at this write site),
# u (usage errors).
def _cases(check):
    import contextlib
    import shutil
    import subprocess

    def run(argv):
        lines = []
        code = M.main(argv, out=lines.append)
        return code, "\n".join(lines)

    def base_manifest():
        return {
            "meta": {"version": 2, "buildCommands": {"test": "true"}},
            "phases": [
                {"id": "P1", "title": "Shipped", "status": "done",
                 "testGate": ["test"],
                 "tasks": [{"id": "P1.1", "title": "old", "status": "done"}]},
                {"id": "P2", "title": "Live", "status": "in_progress",
                 "testGate": ["test"],
                 "tasks": [
                     {"id": "P2.1", "title": "a", "status": "done",
                      "files": ["src/a.ts"]},
                     {"id": "P2.3", "title": "b", "status": "pending"}]},
                {"id": "P3", "title": "Parked work", "status": "pending",
                 "testGate": [], "tasks": []},
            ],
            "fileIndex": {"src/a.ts": ["P2.1"]},
            "bugs": [],
        }

    tmp = tempfile.mkdtemp(prefix="audit-task-selftest-")

    def mk(name, manifest, sharded=False, git=False):
        proj = os.path.join(tmp, name)
        os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json"})
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        if sharded:
            _mio.save_sharded(mpath, manifest)
        else:
            _panel_write._atomic_write_json(mpath, manifest)
        if git:
            subprocess.run(["git", "init", "-q", proj], check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        return proj, mpath

    def task_in(mpath, tid):
        try:
            return _mio.tasks_by_id(_mio.load_manifest(mpath)).get(tid)
        except Exception:
            return None

    try:
        # ---- (a) add + phase resolution -----------------------------------
        proj, mpath = mk("a-single", base_manifest())
        code, txt = run(["add", "New guard", "--phase", "P2",
                         "--project-dir", proj])
        check("a1 explicit --phase add exits 0", code == 0)
        check("a2 gaps are history: P2.1 + P2.3 allocate P2.4, P2.2 is "
              "never re-minted", task_in(mpath, "P2.4") is not None)
        code, txt = run(["add", "Default phase", "--project-dir", proj])
        check("a3 --phase absent lands in the single in_progress phase",
              code == 0 and task_in(mpath, "P2.5") is not None)

        two = base_manifest()
        two["phases"][2]["status"] = "in_progress"
        proj2, _m2 = mk("a-two-inprog", two)
        code, txt = run(["add", "X", "--project-dir", proj2])
        check("a4 two in_progress phases -> exit 2, --phase required",
              code == 2)
        check("a4b ...naming BOTH choices", "P2" in txt and "P3" in txt)

        idle = base_manifest()
        idle["phases"][1]["status"] = "pending"
        proj3, _m3 = mk("a-idle", idle)
        code, txt = run(["add", "X", "--project-dir", proj3])
        check("a5 no in_progress phase -> exit 2 naming the open phases",
              code == 2 and "P2" in txt and "P3" in txt)

        code, txt = run(["add", "X", "--phase", "P1", "--project-dir", proj])
        check("a6 a done phase refuses -- immutable history",
              code == 2 and "immutable" in txt)
        check("a6b ...and nothing landed in it",
              len((_mio.load_manifest(mpath)["phases"][0].get("tasks"))) == 1)
        code, txt = run(["add", "X", "--phase", "P9", "--project-dir", proj])
        check("a7 unknown phase -> exit 2 listing what exists",
              code == 2 and "P2" in txt)
        empty_proj = os.path.join(tmp, "a-empty")
        os.makedirs(empty_proj, exist_ok=True)
        code, txt = run(["add", "X", "--project-dir", empty_proj])
        check("a8 missing manifest -> exit 2 pointing at /audit:init",
              code == 2 and "init" in txt)
        code, txt = run(["add", "   ", "--project-dir", proj])
        check("a9 an empty title is a usage error", code == 2)

        # ---- (i) reserved / parked ids ------------------------------------
        code, _txt = run(["add", "Third", "--phase", "P2",
                          "--project-dir", proj])
        check("i1 sequential adds keep counting (P2.6 after P2.5)",
              code == 0 and task_in(mpath, "P2.6") is not None)

        def prop(status):
            # `notes` only when dropped: the validator requires a justification on
            # a dropped proposal (an archive that cannot say why is a tombstone)
            # and refuses `droppedAt` on any other status, so a fixture that
            # carried the pair unconditionally would be invalid three ways.
            extra = ({"notes": "declined for this fixture",
                      "droppedAt": "2026-01-02T00:00:00Z"}
                     if status == "dropped" else {})
            return dict(extra, **{
                    "id": "PROP-1", "name": "Parked phase", "status": status,
                    "origin": "audit:init",
                    "createdISO": "2026-01-01T00:00:00Z",
                    "scope": "x", "benefit": "y", "openQuestions": [],
                    "materializedAs": None, "materializedAt": None,
                    "payload": {"phase": {
                        "id": "P4", "title": "Parked", "status": "pending",
                        "tasks": [{"id": "P4.1", "title": "t",
                                   "status": "pending"}]}}})

        resv = base_manifest()
        resv["proposals"] = [prop("proposed")]
        proj4, _m4 = mk("i-reserved", resv)
        code, txt = run(["add", "X", "--phase", "P4", "--project-dir", proj4])
        check("i2 a phase id RESERVED by a parked proposal refuses toward "
              "/audit:propose materialize",
              code == 2 and "PROP-1" in txt and "materialize" in txt)
        dropped = base_manifest()
        dropped["proposals"] = [prop("dropped")]
        proj5, _m5 = mk("i-dropped", dropped)
        code, txt = run(["add", "X", "--phase", "P4", "--project-dir", proj5])
        check("i3 a dropped proposal releases the id -- plain unknown-phase "
              "refusal, no proposal named",
              code == 2 and "PROP-1" not in txt)

        # ---- (t) the template ---------------------------------------------
        t = task_in(mpath, "P2.4") or {}
        check("t1 every template field initialized, each exactly once",
              set(t.keys()) == set(M._TEMPLATE_KEYS))
        check("t2 the conventions template values are the ones written",
              t.get("status") == "pending" and t.get("attempts") == 0
              and t.get("maxAttempts") == 3 and t.get("commit") is None
              and t.get("outcome") == {"technical": None, "descriptive": None}
              and t.get("startedAt") is None and t.get("completedAt") is None
              and t.get("verifiedBy") == [] and t.get("blockedBy") == []
              and t.get("dependsOn") == [])
        check("t3 tests default: gate-only, no red-first, gate from the "
              "phase's testGate",
              t.get("tests") == {"mode": "gate-only", "add": [],
                                 "expectRedFirst": False, "gate": ["test"]})
        check("t4 model floors at sonnet, risk defaults low",
              t.get("model") == "sonnet" and t.get("risk") == "low")

        code, _txt = run(["add", "Risky", "--phase", "P2",
                          "--project-dir", proj,
                          "--risk", "high", "--tests-mode", "tdd",
                          "--tests-add", "repro must fail first",
                          "--blocked-by", "P2.1", "--depends-on", "P2.3",
                          "--description", "why and how"])
        t = task_in(mpath, "P2.7") or {}
        check("t5 risk high without --model escalates to opus",
              code == 0 and t.get("model") == "opus"
              and t.get("risk") == "high")
        check("t6 tdd sets expectRedFirst true and carries the authored test",
              (t.get("tests") or {}).get("mode") == "tdd"
              and (t.get("tests") or {}).get("expectRedFirst") is True
              and (t.get("tests") or {}).get("add")
              == ["repro must fail first"])
        check("t7 blockedBy/dependsOn/description land as given",
              t.get("blockedBy") == ["P2.1"] and t.get("dependsOn") == ["P2.3"]
              and t.get("description") == "why and how")
        code, _txt = run(["add", "Explicit model", "--phase", "P2",
                          "--project-dir", proj, "--risk", "high",
                          "--model", "sonnet"])
        check("t8 an explicit --model wins over the risk escalation",
              code == 0 and (task_in(mpath, "P2.8") or {}).get("model")
              == "sonnet")

        # ---- (s) skills: the three states ---------------------------------
        check("s1 skills absent -> [] (unconsidered; area default in force)",
              (task_in(mpath, "P2.4") or {}).get("skills") == [])
        code, _txt = run(["add", "With skills", "--phase", "P2",
                          "--project-dir", proj,
                          "--skills", "clean-typescript,web-security"])
        check("s2 --skills a,b lands as the list",
              code == 0 and (task_in(mpath, "P2.9") or {}).get("skills")
              == ["clean-typescript", "web-security"])
        code, _txt = run(["add", "Opted out", "--phase", "P2",
                          "--project-dir", proj, "--skills", "null"])
        s3t = task_in(mpath, "P2.10") or {}
        check("s3 --skills null is the explicit opt-out: key present, "
              "value None", code == 0 and "skills" in s3t
              and s3t.get("skills") is None)
        with open(mpath, encoding="utf-8") as fh:
            raw = fh.read()
        check("s3b ...written as JSON null in the file, not flattened "
              "or dropped", '"skills": null' in raw)

        # ---- (x) fileIndex -------------------------------------------------
        code, txt = run(["add", "Indexed", "--phase", "P2",
                         "--project-dir", proj,
                         "--files", "src/a.ts,src/new.ts"])
        fidx = (_mio.load_manifest(mpath).get("fileIndex") or {})
        check("x1 an existing fileIndex entry is EXTENDED, other tasks kept",
              code == 0 and fidx.get("src/a.ts") == ["P2.1", "P2.11"])
        check("x1b a new file gets a fresh entry",
              fidx.get("src/new.ts") == ["P2.11"])
        check("x2 a file not on disk is noted (new-file paths stay allowed), "
              "never refused", code == 0 and "src/new.ts" in txt)

        # ---- (r) validator rollback ----------------------------------------
        before = open(mpath, "rb").read()
        code, txt = run(["add", "Bad ref", "--phase", "P2",
                         "--project-dir", proj, "--blocked-by", "P9.9"])
        check("r1 a reference the validator refuses -> exit 1 with the "
              "findings", code == 1 and "does not resolve" in txt)
        check("r2 ...and the manifest is rolled back byte-for-byte",
              open(mpath, "rb").read() == before)

        dup = base_manifest()
        dup["phases"][1]["tasks"].append({"id": "P2.1", "title": "dup",
                                          "status": "pending"})
        projd, mpathd = mk("r-preinvalid", dup)
        befored = open(mpathd, "rb").read()
        code, txt = run(["add", "X", "--phase", "P2", "--project-dir", projd])
        check("r3 an ALREADY-invalid manifest refuses before any write",
              code == 1 and "already" in txt.lower()
              and open(mpathd, "rb").read() == befored)

        # ---- (y) the sharded layout ----------------------------------------
        projs, mpaths = mk("y-sharded", base_manifest(), sharded=True)
        idx_raw = _mio.read_json(mpaths)
        check("y0 fixture really is sharded", _mio.is_sharded(idx_raw))
        sbase = os.path.dirname(mpaths)
        shard_of = {s.get("id"): os.path.join(sbase, s["shard"])
                    for s in idx_raw["phases"] if isinstance(s, dict)}
        p1_before = open(shard_of["P1"], "rb").read()
        idx_before = open(mpaths, "rb").read()
        code, _txt = run(["add", "Sharded add", "--phase", "P2",
                          "--project-dir", projs])
        check("y1 the task lands in the phase SHARD and survives a reload",
              code == 0 and (task_in(mpaths, "P2.4") or {}).get("title")
              == "Sharded add")
        check("y2 an untouched phase's shard is not rewritten",
              open(shard_of["P1"], "rb").read() == p1_before)
        check("y3 no --files -> the index itself is untouched",
              open(mpaths, "rb").read() == idx_before)
        code, _txt = run(["add", "Sharded indexed", "--phase", "P2",
                          "--project-dir", projs, "--files", "src/new.ts"])
        check("y4 --files updates the fileIndex ON THE INDEX",
              code == 0 and (_mio.load_manifest(mpaths).get("fileIndex")
                             or {}).get("src/new.ts") == ["P2.5"])
        check("y4b ...and the untouched shard is still byte-identical",
              open(shard_of["P1"], "rb").read() == p1_before)
        p2_before = open(shard_of["P2"], "rb").read()
        idx_before2 = open(mpaths, "rb").read()
        code, _txt = run(["add", "Bad", "--phase", "P2",
                          "--project-dir", projs, "--blocked-by", "NOPE",
                          "--files", "src/x.ts"])
        check("y5 sharded rollback restores shard AND index byte-for-byte",
              code == 1 and open(shard_of["P2"], "rb").read() == p2_before
              and open(mpaths, "rb").read() == idx_before2)

        # ---- (h) the A4 heal ------------------------------------------------
        healm = base_manifest()
        healm["phases"][2]["tasks"] = [{"id": "P3.1", "title": "hand-flipped",
                                        "status": "in_progress"}]
        projh, mpathh = mk("h-heal", healm)
        code, txt = run(["add", "Heal me", "--phase", "P3",
                         "--project-dir", projh])
        p3 = [p for p in _mio.load_manifest(mpathh)["phases"]
              if p.get("id") == "P3"][0]
        check("h1 a pending phase holding an in_progress task is healed in "
              "the same write (v0.37 A4, reused from _panel_write)",
              code == 0 and p3.get("status") == "in_progress")
        check("h2 ...and the heal is reported",
              "pending -> in_progress" in txt)

        # ---- (j) --json + the journal ---------------------------------------
        projj, _mj = mk("j-json", base_manifest())
        code, txt = run(["add", "Json add", "--phase", "P2",
                         "--project-dir", projj, "--json"])
        parsed = None
        try:
            parsed = json.loads(txt)
        except Exception:
            pass
        check("j1 --json emits one parseable object",
              code == 0 and isinstance(parsed, dict))
        check("j1b ...naming the id and the task it wrote",
              bool(parsed) and parsed.get("id") == "P2.4"
              and (parsed.get("task") or {}).get("status") == "pending")
        jm = _panel_write._journalmod()
        rows = jm.read_all(projj) if jm else []
        addrows = [r for r in rows if r.get("action") == "task.add"]
        check("j2 a task.add row is journaled through audit-journal's append",
              len(addrows) == 1)
        check("j2b ...with the allow-listed details a reader joins on",
              bool(addrows)
              and (addrows[0].get("details") or {}).get("taskId") == "P2.4"
              and (addrows[0].get("details") or {}).get("phaseId") == "P2")
        check("j2c ...and the result reports the journal outcome",
              bool(parsed) and parsed.get("journaled") is True)

        # ---- (k) the lock ----------------------------------------------------
        if not shutil.which("git"):
            print("SKIP k* (git not installed)")
        else:
            projk, mpathk = mk("k-lock", base_manifest(), git=True)
            # `audit-lock.py`, not `_panel_write._lockmod()`. This group ACQUIRES
            # and seizes a lock - it drives `main()` and `_write_lock`, which are
            # the command's half. `_lockmod()` is the panel's READ-side accessor
            # and returns `_locks` (layer 1) since the read side moved down there;
            # it never promised a `main`, and reaching a command through an
            # accessor named for reading is what made this case break when the
            # two were finally separated.
            lockmod = _loader.load_script("audit-lock.py", modname="audit_lock")
            check("k0 the lock library loads", lockmod is not None)
            if lockmod is not None:
                held = lockmod.main(
                    ["acquire", "index", "--project", projk,
                     "--note", "phase P2 run", "--session", "sess-A",
                     "--pid", str(os.getpid())], out=lambda *_a: None)
                check("k0b fixture lock taken", held == 0)
                kb = open(mpathk, "rb").read()
                code, txt = run(["add", "Locked out", "--phase", "P2",
                                 "--project-dir", projk])
                check("k1 a live holder refuses with exit 3", code == 3)
                check("k1b ...printing the lock's own standard shape",
                      "HELD by a live run" in txt and "sess-A" in txt)
                check("k1c ...and nothing was written",
                      open(mpathk, "rb").read() == kb)
                deadp = subprocess.Popen([sys.executable, "-c", "pass"])
                deadp.wait()
                lpath = os.path.join(lockmod.lock_dir(projk), "index.lock")
                info = lockmod.read_lock(lpath)
                info["pid"] = deadp.pid
                lockmod._write_lock(lpath, info)
                code, txt = run(["add", "Stale", "--phase", "P2",
                                 "--project-dir", projk])
                check("k2 an abandoned holder -> exit 4, offering --takeover",
                      code == 4 and "--takeover" in txt)
                check("k2b ...but nothing is seized or written yet",
                      open(mpathk, "rb").read() == kb)
                code, txt = run(["add", "Taken over", "--phase", "P2",
                                 "--project-dir", projk, "--takeover"])
                check("k3 --takeover seizes the abandoned lock and writes",
                      code == 0 and (task_in(mpathk, "P2.4") or {}).get("title")
                      == "Taken over")
                check("k4 the lock is released after the write",
                      not os.path.exists(lpath))
        projl, mpathl = mk("k-legacy", base_manifest())
        open(mpathl + ".lock", "w").close()
        code, txt = run(["add", "X", "--phase", "P2", "--project-dir", projl])
        check("k5 outside a git repo the working-tree lockfile still refuses",
              code == 3 and "locked" in txt)
        os.remove(mpathl + ".lock")

        # ---- (n) named-manifest project resolution (F-C-1) -------------------
        # Naming another project's manifest from this cwd must not journal (or
        # lock, or note file existence) into THIS repo -- the class
        # audit-usage's resolve_ledger already solved. cwd and
        # CLAUDE_PROJECT_DIR are both pinned to a "home" project that must
        # come out untouched.
        projn_home, _mnh = mk("n-home", base_manifest())
        projn_foreign, mpn = mk("n-foreign", base_manifest())
        oldcwd = os.getcwd()
        oldenv = os.environ.get("CLAUDE_PROJECT_DIR")

        def _pin(cwd, env):
            os.chdir(cwd)
            if env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = env

        def _unpin():
            os.chdir(oldcwd)
            if oldenv is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = oldenv

        try:
            _pin(projn_home, projn_home)
            code, txt = run(["add", "Foreign add", mpn, "--phase", "P2"])
        finally:
            _unpin()
        jm2 = _panel_write._journalmod()
        frows = [r for r in (jm2.read_all(projn_foreign) if jm2 else [])
                 if r.get("action") == "task.add"]
        check("n1 a NAMED manifest journals beside ITSELF, not into the "
              "cwd/env repo (F-C-1)", code == 0 and len(frows) == 1)
        check("n2 ...and the cwd/env repo's journal is untouched (no dir "
              "even exists)",
              not os.path.isdir(os.path.join(projn_home, "docs", "audit",
                                             "journal")))
        check("n3 ...and the row's target is manifest-relative, not a "
              "../../ crawl out of the wrong root",
              bool(frows)
              and frows[0].get("target") == "docs/audit/audit-plan.json")

        projn_f2, mpn2 = mk("n-foreign2", base_manifest())
        projn_h2, _mn2 = mk("n-home2", base_manifest())
        code, _txt = run(["add", "Explicit wins", mpn2, "--phase", "P2",
                          "--project-dir", projn_h2])
        h2rows = [r for r in (jm2.read_all(projn_h2) if jm2 else [])
                  if r.get("action") == "task.add"]
        check("n4 an explicit --project-dir wins over the named manifest's "
              "own root -- the human said so",
              code == 0 and len(h2rows) == 1)

        projn_sh, mpsh = mk("n-sharded-foreign", base_manifest(),
                            sharded=True)
        try:
            _pin(projn_home, projn_home)
            code, _txt = run(["add", "Sharded foreign", mpsh,
                              "--phase", "P2"])
        finally:
            _unpin()
        check("n5 a NAMED sharded manifest is writable from a foreign cwd "
              "-- the shard guard scopes to the manifest's OWN project",
              code == 0 and (task_in(mpsh, "P2.4") or {}).get("title")
              == "Sharded foreign")

        projn_env, mpe = mk("n-env", base_manifest())
        try:
            _pin(tmp, projn_env)
            code, _txt = run(["add", "Env project", "--phase", "P2"])
        finally:
            _unpin()
        check("n6 with nothing named, CLAUDE_PROJECT_DIR answers before the "
              "cwd (audit-usage's resolve_project order)",
              code == 0 and task_in(mpe, "P2.4") is not None)

        # F-C-2: MARKERLESS trees (no .claude, no .git anywhere above). The
        # fallback root must keep the journal in a sane place INSIDE the
        # manifest's tree -- never doubled, never outside.
        def mk_bare(name, manifest, rel="docs/audit/audit-plan.json"):
            proj = os.path.join(tmp, name)
            mp = os.path.join(proj, rel)
            os.makedirs(os.path.dirname(mp), exist_ok=True)
            _panel_write._atomic_write_json(mp, manifest)
            return proj, mp

        projb, mpb = mk_bare("n-markerless", base_manifest())
        try:
            _pin(projn_home, projn_home)
            code, _txt = run(["add", "Markerless", mpb, "--phase", "P2"])
        finally:
            _unpin()
        brows = [r for r in (jm2.read_all(projb) if jm2 else [])
                 if r.get("action") == "task.add"]
        check("n7 a markerless default-layout tree journals beside its "
              "manifest, where default readers find it (F-C-2)",
              code == 0 and len(brows) == 1)
        check("n7b ...and the layout is not doubled -- docs/audit/docs "
              "never appears",
              not os.path.exists(os.path.join(projb, "docs", "audit",
                                              "docs")))

        projb2, mpb2 = mk_bare("n-bare-layout", base_manifest(),
                               rel="plan.json")
        try:
            _pin(projn_home, projn_home)
            code, _txt = run(["add", "Bare layout", mpb2, "--phase", "P2"])
        finally:
            _unpin()
        jdir = os.path.join(projb2, "journal")
        jtext = ""
        if os.path.isdir(jdir):
            for fn in os.listdir(jdir):
                with open(os.path.join(jdir, fn), encoding="utf-8") as fh:
                    jtext += fh.read()
        check("n8 a bare non-default layout (x/plan.json) journals at "
              "x/journal, beside the manifest",
              code == 0 and '"task.add"' in jtext)
        check("n8b ...without conjuring docs/audit into the tree",
              not os.path.exists(os.path.join(projb2, "docs")))

        # ---- (c) cancel: finished, but not done ------------------------------
        # A phase can end without landing: the feature is dropped, part of the
        # work exists, the phase closes. Until now the only way to say so was
        # to hand-edit the manifest, so the reason lived in nobody's memory and
        # the trail had no row. The verb records all three: the status, the
        # reason, and the moment.
        projc, mpc = mk("cancel", base_manifest())
        code, txt = run(["cancel", "P2.3", mpc, "--reason",
                         "search feature dropped", "--project-dir", projc])
        mc = _mio.load_manifest(mpc)
        tc = [t for ph in mc["phases"] for t in ph["tasks"] if t["id"] == "P2.3"][0]
        check("c1 a task is cancelled, with the reason and the moment recorded",
              code == 0 and tc["status"] == "cancelled"
              and "search feature dropped" in (tc.get("outcome") or {}).get("descriptive", "")
              and tc.get("completedAt"))
        check("c2 the reason is REQUIRED - a status flipped with no why is the "
              "hand-edit this verb replaces",
              run(["cancel", "P2.1", mpc, "--project-dir", projc])[0] == 2
              and run(["cancel", "P2.1", mpc, "--reason", "  ",
                       "--project-dir", projc])[0] == 2)
        check("c3 already-terminal work is refused rather than silently "
              "rewritten - a done task is history",
              run(["cancel", "P2.1", mpc, "--reason", "no",
                   "--project-dir", projc])[0] == 2)
        code, txt = run(["cancel", "P2.3", mpc, "--reason", "again",
                         "--project-dir", projc])
        check("c4 ...and so is one already cancelled", code == 2)

        projd, mpd = mk("cancel-phase", base_manifest())
        code, txt = run(["cancel", "P3", mpd, "--reason", "area shelved",
                         "--project-dir", projd])
        md = _mio.load_manifest(mpd)
        pd = [ph for ph in md["phases"] if ph["id"] == "P3"][0]
        check("c5 a phase can be cancelled too, and says why in its summary",
              code == 0 and pd["status"] == "cancelled"
              and "area shelved" in (pd.get("summary") or ""))

        proje, mpe = mk("cancel-cascade", base_manifest())
        code, txt = run(["cancel", "P2", mpe, "--reason", "shelved",
                         "--project-dir", proje])
        me = _mio.load_manifest(mpe)
        pe = [ph for ph in me["phases"] if ph["id"] == "P2"][0]
        states = {t["id"]: t["status"] for t in pe["tasks"]}
        check("c6 cancelling a phase cancels the work still open inside it - a "
              "pending task under a dropped phase would still be offered by "
              "/audit:next",
              code == 0 and states["P2.3"] == "cancelled"
              # ...and leaves finished work exactly as it finished.
              and states["P2.1"] == "done")
        check("c7 the manifest stays valid after both writes",
              not _panel_write._cores()[0].validate(me)[0])
        jpath = os.path.join(proje, "docs", "audit", "journal")
        jtxt = ""
        for root, _dirs, files in os.walk(jpath):
            for f in files:
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    jtxt += fh.read()
        check("c8 the trail carries a row naming the reason - the point of the "
              "verb is that the why outlives the session",
              '"phase.cancel"' in jtxt and "shelved" in jtxt)
        code, jtext = run(["cancel", "P1", mpe, "--reason", "x",
                           "--project-dir", proje, "--json"])
        check("c9 a done PHASE is refused as well", code == 2)

        # ---- (w) the index _waiting_on resolves refs through -------------------
        # A phase with NO tasks still has a status and can still be the thing a
        # task is blocked by, and `_mio.iter_tasks` yields nothing at all for
        # such a phase -- so the phase half of that index is a separate walk.
        # These are the cases that go red if the two are ever folded into one.
        _wm = {"phases": [
            {"id": "P0", "title": "groundwork", "status": "done"},
            {"id": "P1", "title": "next", "status": "in_progress", "tasks": [
                {"id": "P1.1", "title": "t", "status": "pending"}]},
        ]}
        # DONE on purpose: a phase missing from the index reads back as None,
        # which is already "not done", so a PENDING blocker would let the folded
        # version and this one agree and prove nothing.
        check("w1 a ref to a task-less DONE phase counts as satisfied",
              M._waiting_on(_wm, {"blockedBy": ["P0"], "dependsOn": []}) == [])
        # The other direction, and it looks vacuous by design: it is the only
        # case that fails if `_waiting_on` ever becomes "nothing is ever waiting".
        check("w2 ...while a ref to a phase that is NOT done is still reported",
              M._waiting_on(_wm, {"blockedBy": ["P1"], "dependsOn": []}) == ["P1"])
        check("w3 a task ref resolves through the same index",
              M._waiting_on(_wm, {"dependsOn": ["P1.1"]}) == ["P1.1"])
        # w4: this call site tested `!= "done"` while audit-status' readiness
        # used ("done", "cancelled"), so a task blocked by a CANCELLED task was
        # ready to /audit:status and still waiting to /audit:task add - one
        # manifest, two answers. `cancelled` arrived as the second terminal state
        # and this line never followed. The rule now has one home.
        _wc = {"phases": [{"id": "P1", "title": "p", "status": "in_progress",
                           "tasks": [{"id": "P1.1", "title": "dropped",
                                      "status": "cancelled"}]}]}
        check("w4 a ref to a CANCELLED task counts as satisfied, exactly as "
              "/audit:status' readiness has always counted it: %r"
              % (M._waiting_on(_wc, {"blockedBy": ["P1.1"]}),),
              M._waiting_on(_wc, {"blockedBy": ["P1.1"]}) == [])
        # w5-w6: same unvalidated-input class audit-status carries. A
        # non-hashable ref used to raise inside the index lookup here too.
        try:
            _wbad = M._waiting_on(_wm, {"blockedBy": [None, 7, [1, 2]]})
        except Exception as _wexc:
            _wbad = "RAISED %s: %s" % (type(_wexc).__name__, _wexc)
        check("w5 a malformed ref does not raise here either - the same defect "
              "lived at this call site, not only in audit-status: %r" % (_wbad,),
              _wbad == ["None", "7", "[1, 2]"])
        check("w6 ...and _waiting_on returns only strings, so whatever joins "
              "them cannot die on the row: %r" % (_wbad,),
              isinstance(_wbad, list) and all(isinstance(x, str) for x in _wbad))

        # ---- (u) usage -------------------------------------------------------
        with open(os.devnull, "w") as _null, \
                contextlib.redirect_stderr(_null):
            code, _txt = run(["frobnicate", "X"])
            check("u1 an unknown subcommand is a usage error", code == 2)
            code, _txt = run([])
            check("u2 bare invocation is a usage error", code == 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_task.py --selftest\n")
    raise SystemExit(2)
