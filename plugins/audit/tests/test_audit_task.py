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
# n (named-manifest project resolution), c (cancel), p (add-phase: the F58
# verb, both layouts), w (the _waiting_on index), u (usage errors).
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

        # The three verbs' rows are built by ONE function, and this is the pair
        # that says so from the OUTPUT rather than from the source. `cancel`
        # used to build its own and passed the whole `_viewer()` DICT as
        # `actor.author`; `_journal_io` normalises a non-string author to None
        # and defaults an absent `via` to "unknown", so every cancel row went
        # in with no author and the wrong channel and nothing on the row said
        # so. Comparing the two rows FROM ONE RUN is what makes this
        # environment-independent - whether an author resolves at all depends
        # on the machine, whether the two agree does not.
        projac, mpac = mk("c-actor", base_manifest())
        run(["add", "Actor probe", "--phase", "P2", "--project-dir", projac])
        run(["cancel", "P3", mpac, "--reason", "shelved",
             "--project-dir", projac])
        jmac = _panel_write._journalmod()
        rows_ac = jmac.read_all(projac) if jmac else []
        add_ac = [r for r in rows_ac if r.get("action") == "task.add"]
        can_ac = [r for r in rows_ac if r.get("action") == "phase.cancel"]
        check("c10 both rows were written (1 add, 1 cancel): %d/%d"
              % (len(add_ac), len(can_ac)),
              len(add_ac) == 1 and len(can_ac) == 1)
        check("c11 ...and the cancel row's actor is the add row's actor, "
              "field for field - via=cli and an author of the same type, "
              "which is what a per-verb row builder had already lost: %r vs %r"
              % ((can_ac[0].get("actor") if can_ac else None),
                 (add_ac[0].get("actor") if add_ac else None)),
              bool(add_ac) and bool(can_ac)
              and can_ac[0].get("actor") == add_ac[0].get("actor")
              and (can_ac[0].get("actor") or {}).get("via") == "cli")

        # WHAT WENT WITH THE PHASE, in the row rather than only in the prose.
        # The cascaded ids were handed over as `details.cascaded`, which is not
        # on `_journal_io.DETAILS_KEYS`: written, dropped in silence, and
        # believed. They ride `changes` now -- the shape the allow-list already
        # bounds and clips -- and the statuses below are deliberately all
        # different, so a builder that stamped a constant `from`, or read the
        # status AFTER `_cancel_task` had overwritten it, emits rows that are
        # identical to each other and cannot pass this.
        cascade_fx = base_manifest()
        cascade_fx["phases"][1]["tasks"] = [
            {"id": "P2.1", "title": "a", "status": "done", "files": ["src/a.ts"]},
            {"id": "P2.2", "title": "b", "status": "pending"},
            {"id": "P2.3", "title": "c", "status": "blocked"},
            {"id": "P2.4", "title": "d", "status": "in_progress"},
        ]
        projcc, mpcc = mk("c-cascade-row", cascade_fx)
        code, txt = run(["cancel", "P2", mpcc, "--reason", "shelved",
                         "--project-dir", projcc])
        jmcc = _panel_write._journalmod()
        rows_cc = [r for r in (jmcc.read_all(projcc) if jmcc else [])
                   if r.get("action") == "phase.cancel"]
        det_cc = (rows_cc[0].get("details") or {}) if rows_cc else {}
        check("c12 the cascade survives INTO the row: every task the phase took "
              "with it is a `changes` entry naming the status it held, and the "
              "already-done one is not among them. Compared whole rather than "
              "probed for one id, because a writer that emitted only the first "
              "would pass a presence check for ever: %r"
              % (det_cc.get("changes"),),
              code == 0 and len(rows_cc) == 1
              and det_cc.get("changes") == [
                  {"id": "P2.2", "field": "status", "from": "pending",
                   "to": "cancelled"},
                  {"id": "P2.3", "field": "status", "from": "blocked",
                   "to": "cancelled"},
                  {"id": "P2.4", "field": "status", "from": "in_progress",
                   "to": "cancelled"}])
        check("c12b ...and the details block is EXACTLY the keys the writer "
              "means. No `cancelledId`: it was handed over and dropped while "
              "`phaseId` already carried the same string, so restoring it to "
              "the allow-list would have grown a committed row for nothing: %r"
              % (sorted(det_cc),),
              sorted(det_cc) == ["changes", "phaseId", "reason"]
              and det_cc.get("phaseId") == "P2"
              and det_cc.get("reason") == "shelved")

        projct, mpct = mk("c-cascade-none", base_manifest())
        run(["cancel", "P2.3", mpct, "--reason", "dropped",
             "--project-dir", projct])
        jmct = _panel_write._journalmod()
        rows_ct = [r for r in (jmct.read_all(projct) if jmct else [])
                   if r.get("action") == "task.cancel"]
        det_ct = (rows_ct[0].get("details") or {}) if rows_ct else {}
        check("c13 SECOND-DIRECTION CASE: a TASK cancel takes nothing with it, "
              "so its row carries no `changes` key at all. This passes on the "
              "pre-change code by construction and is the only case here that "
              "goes red if the cascade is written unconditionally: %r"
              % (det_ct,),
              len(rows_ct) == 1
              and sorted(det_ct) == ["phaseId", "reason", "taskId"]
              and det_ct.get("taskId") == "P2.3")

        projcj, mpcj = mk("c-cascade-json", cascade_fx)
        code, txt_cj = run(["cancel", "P2", mpcj, "--reason", "shelved",
                            "--project-dir", projcj, "--json"])
        parsed_cj = {}
        try:
            parsed_cj = json.loads(txt_cj)
        except Exception:
            pass
        check("c14 the --json block still names the cascade as bare ids: the "
              "ROW's shape moved, the command's output is a separate contract "
              "and did not: %r" % (parsed_cj.get("cascaded"),),
              code == 0
              and parsed_cj.get("cascaded") == ["P2.2", "P2.3", "P2.4"])

        # THE BOUND, DRIVEN THROUGH THE VERB rather than trusted from the
        # constant. A details block over MAX_DETAILS_BYTES does not lose its
        # tail, it collapses to a truncation marker and a count -- taking
        # `reason` with it, which is the one thing this row exists to preserve.
        # A phase far past the change cap is what proves the cascade is bounded
        # before it can get there, and it goes red the day a per-entry field is
        # added that is fat enough to reach the byte cap.
        wide = base_manifest()
        _jmod = _panel_write._journalmod()
        wide["phases"][1]["tasks"] = [
            {"id": "P2.%d" % n, "title": "t", "status": "pending"}
            for n in range(1, 2 * _jmod.MAX_CHANGES + 1)]
        projcw, mpcw = mk("c-cascade-wide", wide)
        code, txt = run(["cancel", "P2", mpcw, "--reason", "whole area shelved",
                         "--project-dir", projcw])
        rows_cw = [r for r in (_jmod.read_all(projcw) if _jmod else [])
                   if r.get("action") == "phase.cancel"]
        det_cw = (rows_cw[0].get("details") or {}) if rows_cw else {}
        check("c15 a cascade wider than the change cap is CUT and says so, and "
              "the reason and the phase id survive the cut - the why is what "
              "the row exists for, and the collapse a byte-cap overflow forces "
              "would take it: kept %d, truncated %r"
              % (len(det_cw.get("changes") or []), det_cw.get("truncated")),
              code == 0 and len(rows_cw) == 1
              and len(det_cw.get("changes") or []) == _jmod.MAX_CHANGES
              and det_cw.get("truncated") is True
              and det_cw.get("reason") == "whole area shelved"
              and det_cw.get("phaseId") == "P2")

        # ---- (p) add-phase: one more phase in a plan that already exists ------
        # F58. Nothing appended to `phases[]` except the ADO pull: init writes a
        # whole plan, materialize MOVES one that was already written, and `add`
        # needs the phase to be there. Every case below is about the half a hand
        # edit forgets.
        def phase_fixture():
            """P0 done, P1 live, and P2 RESERVED by a parked proposal.

            The reservation is the point: allocation that counted only LIVE ids
            would hand out P2 and collide with the payload materialization is
            holding it for, and every other value in this fixture is chosen so
            that mistake shows up as a different id rather than as a pass."""
            return {
                "meta": {"version": 2,
                         "buildCommands": {"unit": "pytest -q",
                                           "lint": "ruff check"}},
                "phases": [
                    {"id": "P0", "title": "Shipped", "status": "done",
                     "testGate": ["unit"],
                     "tasks": [{"id": "P0.1", "title": "old",
                                "status": "done"}]},
                    {"id": "P1", "title": "Live", "status": "in_progress",
                     "testGate": ["unit"], "tasks": []},
                ],
                "fileIndex": {}, "bugs": [],
                "proposals": [{
                    "id": "PROP-9", "name": "Parked phase",
                    "status": "proposed", "origin": "audit:init",
                    "createdISO": "2026-01-01T00:00:00Z",
                    "scope": "x", "benefit": "y", "openQuestions": [],
                    "materializedAs": None, "materializedAt": None,
                    "payload": {"phase": {
                        "id": "P2", "title": "Parked", "status": "pending",
                        "tasks": [{"id": "P2.1", "title": "t",
                                   "status": "pending"}]}}}]}

        def phase_in(mpath, pid):
            try:
                return [ph for ph in _mio.load_manifest(mpath).get("phases") or []
                        if ph.get("id") == pid][0]
            except Exception:
                return None

        projp, mpp = mk("p-single", phase_fixture())
        code, txt = run(["add-phase", "Search hardening", "--project-dir", projp,
                         "--outcome", "no injection path reaches the index"])
        check("p1 add-phase exits 0 and the phase lands pending",
              code == 0 and (phase_in(mpp, "P3") or {}).get("status")
              == "pending")
        check("p2 the id counts LIVE and PARKED ids alike - P2 is reserved by "
              "PROP-9's payload, so the new phase is P3 and not the id "
              "materialization is holding: %r"
              % ([ph.get("id") for ph in _mio.load_manifest(mpp)["phases"]],),
              phase_in(mpp, "P3") is not None)
        check("p3 ...and it is APPENDED - the written order is the plan's order",
              [ph.get("id") for ph in _mio.load_manifest(mpp)["phases"]]
              == ["P0", "P1", "P3"])
        newp = phase_in(mpp, "P3") or {}
        check("p4 every new-phase template field initialized, each exactly once",
              set(newp.keys()) == set(M._PHASE_TEMPLATE_KEYS))
        check("p5 the conventions template VALUES are the ones written",
              newp.get("baseRef") is None and newp.get("branch") is None
              and newp.get("mergedAt") is None and newp.get("summary") is None
              and newp.get("tasks") == [] and newp.get("blockedBy") == []
              and newp.get("review") == {"tool": None, "model": "sonnet",
                                         "status": "pending", "findings": []})
        check("p6 testGate comes from meta.buildCommands when --gate is absent, "
              "and the line carries the BASIS rather than only the value",
              newp.get("testGate") == ["unit", "lint"]
              and "from meta.buildCommands" in txt)
        check("p7 --outcome is REQUIRED - a phase whose success cannot be "
              "stated in a line is a phase sign-off cannot address, and the "
              "refusal happens before any write",
              run(["add-phase", "No outcome", "--project-dir", projp])[0] == 2
              and run(["add-phase", "Blank", "--outcome", "   ",
                       "--project-dir", projp])[0] == 2
              and phase_in(mpp, "P4") is None)

        # An EMPTY gate is an answer, and the one that must not read as a
        # clean result: the phase is signed off on review alone, so the line
        # says which of the two reasons produced it.
        nogate = phase_fixture()
        nogate["meta"].pop("buildCommands")
        projg, mpg = mk("p-nogate", nogate)
        code, txt = run(["add-phase", "Gateless", "--project-dir", projg,
                         "--outcome", "o"])
        check("p8 a phase with no gate SAYS so, with the reason: %r"
              % (txt.splitlines()[2] if len(txt.splitlines()) > 2 else txt,),
              code == 0 and (phase_in(mpg, "P3") or {}).get("testGate") == []
              and "gate: none" in txt
              and "declares no meta.buildCommands" in txt)
        code, txt = run(["add-phase", "Explicit gate", "--project-dir", projg,
                         "--outcome", "o", "--gate", "make check",
                         "--gate", "npm test"])
        check("p9 --gate wins over the manifest, and says that it did",
              code == 0
              and (phase_in(mpg, "P4") or {}).get("testGate")
              == ["make check", "npm test"]
              and "from --gate" in txt)

        # `area` is a STRING for one tag and a LIST for several - the shape
        # every hand-written manifest and /audit:init phase already uses. A
        # one-element list would validate and still be the odd one out in
        # every diff, which is why the two are separate cases.
        proj_area, mpa = mk("p-area", phase_fixture())
        run(["add-phase", "One tag", "--project-dir", proj_area, "--outcome", "o",
             "--area", "backend"])
        run(["add-phase", "Two tags", "--project-dir", proj_area, "--outcome", "o",
             "--area", "backend,security", "--review-skill", "code-review"])
        check("p10 one --area tag is written as a bare string",
              (phase_in(mpa, "P3") or {}).get("area") == "backend")
        check("p11 ...and several as a list, in the order given",
              (phase_in(mpa, "P4") or {}).get("area")
              == ["backend", "security"])
        check("p12 an untagged phase carries NO area key at all - the "
              "conventions default it to absent, and `area: null` would claim "
              "the question was considered",
              "area" not in (phase_in(mpp, "P3") or {})
              and (phase_in(mpa, "P4") or {}).get("reviewSkill")
              == "code-review")

        # Every refusal, and every one of them before a byte is written.
        projr2, mpr2 = mk("p-refuse", phase_fixture())
        before_r2 = open(mpr2, "rb").read()
        code, txt = run(["add-phase", "Dup", "--id", "P1", "--outcome", "o",
                         "--project-dir", projr2])
        check("p13 an --id that is already a live phase is refused, and the "
              "alternative offered is one the next command would accept",
              code == 2 and "already exists" in txt
              and "/audit:task add --phase P1" in txt)
        code, txt = run(["add-phase", "Dup", "--id", "P0", "--outcome", "o",
                         "--project-dir", projr2])
        check("p14 ...and for a DONE phase the offer is dropped rather than "
              "pointing at a command that refuses done phases",
              code == 2 and "/audit:task add --phase P0" not in txt)
        code, txt = run(["add-phase", "Reserved", "--id", "P2", "--outcome",
                         "o", "--project-dir", projr2])
        check("p15 an --id RESERVED by a parked payload refuses toward "
              "/audit:propose materialize, naming the proposal",
              code == 2 and "PROP-9" in txt and "materialize" in txt)
        code, txt = run(["add-phase", "Taskish", "--id", "P0.1", "--outcome",
                         "o", "--project-dir", projr2])
        check("p16 an --id that is already a TASK id is refused too",
              code == 2 and "TASK id" in txt)
        code, txt = run(["add-phase", "Blank id", "--id", "  ", "--outcome",
                         "o", "--project-dir", projr2])
        check("p17 ...and a blank --id, rather than falling back to the "
              "allocator as if it had not been passed", code == 2)
        check("p18 not one of those refusals wrote a byte",
              open(mpr2, "rb").read() == before_r2)

        # THE SHARDED HALF, which is where a hand edit goes wrong: a new phase
        # needs a shard that does not exist AND an index stub pointing at it.
        projs2, mps2 = mk("p-sharded", phase_fixture(), sharded=True)
        idx2 = _mio.read_json(mps2)
        check("p19 fixture really is sharded", _mio.is_sharded(idx2))
        sbase2 = os.path.dirname(mps2)
        p0_before = open(os.path.join(sbase2, "phases", "P0.json"), "rb").read()
        code, txt = run(["add-phase", "Sharded phase", "--project-dir", projs2,
                         "--outcome", "o"])
        shard_p3 = os.path.join(sbase2, "phases", "P3.json")
        stubs = {s.get("id"): s.get("shard")
                 for s in _mio.read_json(mps2).get("phases") or []}
        check("p20 the shard FILE is created", code == 0
              and os.path.isfile(shard_p3))
        check("p21 ...and the index carries a stub pointing at it - without "
              "both halves the phase exists only in the dict the writer was "
              "handed, and the command reports a success that wrote no phase: "
              "%r" % (stubs,),
              stubs.get("P3") == "phases/P3.json")
        check("p22 ...and it reads back as one assembled phase",
              (phase_in(mps2, "P3") or {}).get("title") == "Sharded phase")
        check("p23 an untouched phase's shard is not rewritten",
              open(os.path.join(sbase2, "phases", "P0.json"), "rb").read()
              == p0_before)
        check("p24 the report names both files it wrote",
              "phases/P3.json" in txt and "audit-plan.json" in txt)

        idx_before3 = open(mps2, "rb").read()
        code, txt = run(["add-phase", "Bad", "--project-dir", projs2,
                         "--outcome", "o", "--blocked-by", "NOPE"])
        check("p25 a phase that would leave the manifest invalid is rolled "
              "back and the index is byte-identical",
              code == 1 and open(mps2, "rb").read() == idx_before3)
        check("p26 ...and the orphan SHARD is gone rather than left behind - a "
              "phase body the restored index no longer points at is a file the "
              "next reader cannot explain",
              not os.path.isfile(os.path.join(sbase2, "phases", "P4.json")))

        projv, mpv = mk("p-single-rb", phase_fixture())
        before_v = open(mpv, "rb").read()
        code, txt = run(["add-phase", "Bad", "--project-dir", projv,
                         "--outcome", "o", "--blocked-by", "NOPE"])
        check("p27 the single-file layout rolls back byte-for-byte too",
              code == 1 and open(mpv, "rb").read() == before_v)

        # Two ids the shard FILENAME cannot tell apart would land on one file
        # and the second write would overwrite the first phase's body.
        projz, mpz = mk("p-collide", phase_fixture(), sharded=True)
        code, _txt = run(["add-phase", "Slashy", "--id", "P/9", "--outcome",
                          "o", "--project-dir", projz])
        code2, txt2 = run(["add-phase", "Twin", "--id", "P_9", "--outcome",
                           "o", "--project-dir", projz])
        check("p28 the sanitised twin of an existing shard name is refused, "
              "naming the phase that already occupies the file",
              code == 0 and code2 == 2 and "P/9" in txt2
              and "overwrite" in txt2)

        projj2, mpj2 = mk("p-journal", phase_fixture())
        code, txt = run(["add-phase", "Journalled", "--project-dir", projj2,
                         "--outcome", "the search path is proven safe",
                         "--json"])
        parsed_p = None
        try:
            parsed_p = json.loads(txt)
        except Exception:
            pass
        check("p29 --json emits one parseable object naming the phase it wrote",
              code == 0 and isinstance(parsed_p, dict)
              and parsed_p.get("id") == "P3"
              and (parsed_p.get("phase") or {}).get("status") == "pending"
              and parsed_p.get("testGateBasis") == "from meta.buildCommands")
        jm3 = _panel_write._journalmod()
        rows3 = jm3.read_all(projj2) if jm3 else []
        addp = [r for r in rows3 if r.get("action") == "phase.add"]
        check("p30 exactly one phase.add row is journaled - counted rather "
              "than found, because a writer that appended twice would look "
              "the same to a presence check: %d" % (len(addp),),
              len(addp) == 1)
        check("p31 ...carrying the desiredOutcome in the SUMMARY, which is "
              "where it survives: _journal_io.DETAILS_KEYS is an allow-list "
              "and drops an unlisted details key in silence",
              bool(addp)
              and "the search path is proven safe" in (addp[0].get("summary") or "")
              and (addp[0].get("details") or {}) == {"phaseId": "P3"})
        check("p32 ...and the actor is the one the add row writes: the author "
              "STRING and via=cli, not a nested viewer dict",
              bool(addp)
              and (addp[0].get("actor") or {}).get("via") == "cli"
              and not isinstance((addp[0].get("actor") or {}).get("author"),
                                 dict))

        projq, mpq = mk("p-invalid", phase_fixture())
        bad_q = phase_fixture()
        bad_q["phases"][0]["status"] = "nonsense"
        _panel_write._atomic_write_json(mpq, bad_q)
        before_q = open(mpq, "rb").read()
        code, txt = run(["add-phase", "X", "--outcome", "o",
                         "--project-dir", projq])
        check("p33 a manifest that was ALREADY invalid is refused with nothing "
              "written - which is what tells 'your phase broke it' apart from "
              "'it was broken when you arrived'",
              code == 1 and "already invalid" in txt
              and open(mpq, "rb").read() == before_q)

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

        # ---- (sc) F189: `scope`, the verb the importer's own instruction needed
        # `pull sprint` writes `files: []` and tells the reader to scope before
        # running. Nothing could: `add` creates, `cancel` closes, `move`
        # relocates, and the panel reaches `skills`/`model` but not `files`. The
        # cost was not tidiness - `files` builds `fileIndex`, and `fileIndex` is
        # what the plan gate matches an edit against, so an unscoped phase ran
        # with its central guard inert rather than failing.
        sc_proj, sc_mp = mk("p-scope", base_manifest())
        os.makedirs(os.path.join(sc_proj, "src"), exist_ok=True)
        for _f in ("b.ts", "c.ts"):
            with open(os.path.join(sc_proj, "src", _f), "w") as _fh:
                _fh.write("x\n")
        code, txt = run(["scope", "P2.3", "--files", "src/b.ts,src/c.ts",
                         "--tests-mode", "tdd", "--project-dir", sc_proj])
        _sct = task_in(sc_mp, "P2.3")
        _idx = (_mio.load_manifest(sc_mp).get("fileIndex") or {})
        check("sc1 scope writes the files AND puts them in fileIndex - the index "
              "is the whole point, because the plan gate matches an edit against "
              "it and an empty one makes the gate inert rather than loud: %r"
              % (_idx,),
              code == 0 and _sct.get("files") == ["src/b.ts", "src/c.ts"]
              and _idx.get("src/b.ts") == ["P2.3"]
              and _idx.get("src/c.ts") == ["P2.3"])
        check("sc2 ...and the tests block moves with it, with expectRedFirst "
              "DERIVED the way `_build_task` derives it - two writers of one "
              "field must not disagree about what tdd means: %r"
              % (_sct.get("tests"),),
              (_sct.get("tests") or {}).get("mode") == "tdd"
              and (_sct.get("tests") or {}).get("expectRedFirst") is True)
        # THE SUBTRACTION, which an append-only index would fail.
        code, txt = run(["scope", "P2.3", "--files", "src/b.ts",
                         "--project-dir", sc_proj])
        _idx2 = (_mio.load_manifest(sc_mp).get("fileIndex") or {})
        check("sc3 re-scoping RELEASES the files the task no longer claims - an "
              "index that only ever grew would keep the gate matching edits to a "
              "scope that is gone, and leaves other tasks' rows alone: %r"
              % (_idx2,),
              code == 0 and _idx2.get("src/b.ts") == ["P2.3"]
              and "src/c.ts" not in _idx2
              and _idx2.get("src/a.ts") == ["P2.1"])
        code, txt = run(["scope", "P2.1", "--files", "src/b.ts",
                         "--project-dir", sc_proj])
        check("sc4 a task that is not pending is REFUSED, and the refusal says "
              "why: its scope is what its attempts were judged against: %r"
              % (txt[:90],),
              code == 2 and "only rewrites a PENDING task" in txt)
        code, txt = run(["scope", "P2", "--files", "src/b.ts",
                         "--project-dir", sc_proj])
        check("sc5 a PHASE id is refused by name - a phase silently scoping its "
              "first task is the kind of guess this verb removes: %r"
              % (txt[:80],),
              code == 2 and "takes a TASK id" in txt and "is a phase" in txt)
        code, txt = run(["scope", "P2.3", "--project-dir", sc_proj])
        check("sc6 a call that would change nothing is refused rather than "
              "taking the index lock for it: %r" % (txt[:80],),
              code == 2 and "scope needs --files" in txt)
        with open(sc_mp, "rb") as _fh:
            _sc_before = _fh.read()
        code, txt = run(["scope", "P9.9", "--files", "src/b.ts",
                         "--project-dir", sc_proj])
        with open(sc_mp, "rb") as _fh:
            _sc_after = _fh.read()
        check("sc7 an unknown id writes nothing - the manifest is byte identical, "
              "which is the assertion rather than the exit code",
              code == 2 and _sc_after == _sc_before)

        # ---- (rt) F190: a plan can be CORRECTED, not only created ------------
        # `init` and `pull sprint` synthesize a phase and choose its `testGate`;
        # until `retarget` that choice was unreachable, and one wrong choice made
        # the phase unable to pass its own sign-off. `--gate` APPENDS, so the
        # empty gate - which `_phase_gate` documents as a designed state, sign-off
        # on review alone - had no spelling at all after import.
        rt_proj, rt_mp = mk("p-retarget", base_manifest())
        code, txt = run(["retarget", "P3", "--gate", "test",
                         "--project-dir", rt_proj])
        _rtp = _mio.load_manifest(rt_mp)["phases"][2]
        check("rt1 retarget replaces the gate an import chose: %r"
              % (_rtp.get("testGate"),),
              code == 0 and _rtp.get("testGate") == ["test"])
        code, txt = run(["retarget", "P3", "--gate-clear",
                         "--project-dir", rt_proj])
        _rtp = _mio.load_manifest(rt_mp)["phases"][2]
        check("rt2 ...and --gate-clear reaches the EMPTY gate, which `--gate` "
              "cannot because it appends - the designed state a guessed gate "
              "took away, and the report SAYS what it means rather than leaving "
              "silence to read as breakage: %r" % (txt[-90:],),
              code == 0 and _rtp.get("testGate") == []
              and "review alone" in txt)
        code, txt = run(["retarget", "P3", "--gate", "test", "--gate-clear",
                         "--project-dir", rt_proj])
        check("rt3 --gate with --gate-clear is refused - two answers about one "
              "field, and guessing which was meant is the fault this closes: %r"
              % (txt[:80],),
              code == 2 and "opposite things" in txt)
        code, txt = run(["retarget", "P3", "--area", "api,api,web",
                         "--outcome", "shipped", "--project-dir", rt_proj])
        _rtp = _mio.load_manifest(rt_mp)["phases"][2]
        check("rt4 area goes through the SAME `_areas.areas_of` every surface "
              "shares (deduped, one tag stays a string) and the outcome moves "
              "with it: %r" % ((_rtp.get("area"), _rtp.get("desiredOutcome")),),
              code == 0 and _rtp.get("area") == ["api", "web"]
              and _rtp.get("desiredOutcome") == "shipped")
        code, txt = run(["retarget", "P3", "--area", "",
                         "--project-dir", rt_proj])
        _rtp = _mio.load_manifest(rt_mp)["phases"][2]
        check("rt5 ...and an emptied --area REMOVES the key rather than writing "
              "null - the conventions default it to absent, and a null would "
              "make an untagged phase claim to have considered the question",
              code == 0 and "area" not in _rtp)
        code, txt = run(["retarget", "P1", "--gate-clear",
                         "--project-dir", rt_proj])
        check("rt6 a DONE phase is refused: its sign-off was given against the "
              "gate it had, and moving that rewrites what was attested: %r"
              % (txt[:90],),
              code == 2 and "was given against the gate it had" in txt)
        code, txt = run(["retarget", "P2.3", "--gate-clear",
                         "--project-dir", rt_proj])
        check("rt7 a TASK id is refused by name - `retarget` takes a phase, and "
              "the sibling verb for a task is `scope`: %r" % (txt[:80],),
              code == 2 and "takes a PHASE id" in txt and "is a task" in txt)
        code, txt = run(["retarget", "P3", "--project-dir", rt_proj])
        check("rt8 a call that changes nothing is refused rather than taking the "
              "index lock for it: %r" % (txt[:70],),
              code == 2 and "retarget needs one of" in txt)
        # F190's OTHER half of the pending rule: an attempted task keeps an
        # outcome describing work judged under the scope it had.
        at_proj, at_mp = mk("p-attempted", base_manifest())
        _am = _mio.load_manifest(at_mp)
        _am["phases"][1]["tasks"][1]["attempts"] = 1
        _panel_write._atomic_write_json(at_mp, _am)
        code, txt = run(["scope", "P2.3", "--files", "src/a.ts",
                         "--project-dir", at_proj])
        check("rt9 scope refuses a PENDING task that has already been attempted "
              "- status alone is not the test, because a task put back to pending "
              "still carries an outcome judged under its old scope: %r"
              % (txt[:90],),
              code == 2 and "already been attempted" in txt)

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
