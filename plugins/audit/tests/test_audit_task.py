#!/usr/bin/env python3
"""
The cases for `audit-task.py`, moved out of it - an entry point.

`audit-task.py` is hyphenated, so it comes through `_loader.load_script` and the
test file substitutes underscores; see `test_migrate_manifest.py` for both halves
of that rule. `M` is the module under test. `_manifest_io` and `_panel_write` are
imported here the way `audit-task.py` imports them, because the fixtures write and
read through those modules' own objects (`_panel_write._atomic_write_json`,
`_mio.save_sharded`, `_panel_write.acquire_index_lock`) rather than through a
second copy.

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
import pathlib
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (SCRIPTS_DIR, to read a sibling's source)
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as audit-task imports it)
import _manifest_rules as _rules                   # noqa: E402  (the validator, to ask what a written plan warns about)
import _manifest_vocab as _vocab                   # noqa: E402  (the gate-basis words the validator grades against)
import _manifest_phases as _phases                 # noqa: E402  (the identity pin below: an alias, not a second body)
import _gate_derive                                # noqa: E402  (the identity pin below: an alias, not a second body)
import _panel_write                                # noqa: E402  (as audit-task imports it)
import _locks as _lock_lib                         # noqa: E402  (its claim writer, which the command no longer re-exports)
import _filed_returns as _fr                       # noqa: E402  (the word only a close writes)

M = _loader.load_script("audit-task.py", modname="audit_task")


# --- cases --------------------------------------------------------------------
# Letters taken in this file (NEW file -- fresh letter space): a (add + phase
# resolution), i (reserved/parked ids), t (template fields), s (skills
# three-state), x (fileIndex), r (validator rollback), k (lock), y (layout:
# sharded/single), j (--json + journal row), h (A4 heal at this write site),
# n (named-manifest project resolution), c (cancel), p (add-phase, both
# layouts), w (the _waiting_on index), u (usage errors), sc (scope), rt
# (retarget, extended by rt10-rt18 for --gate-drop/--gate-set),
# gc (the empty gate a task could not reach), jf (the prior state
# the trail attests), ag (the empty gate at CREATION), fn (the files row for a
# change that did not happen), sf (the three task fields `scope` did not
# reach), sn (the task with no `tests` object), qg (add-phase's empty gate),
# wd (the widening `scope` refused on the very task it exists for), pb (the
# owning phase's blockedBy, the readiness term this file's own copy never
# carried), eb (the brief a shell had already eaten, and the stdin route out),
# fg (the `tests.gate` a STARTED task could not change, and the two refusals
# beside it that must stay), pr (the `start` verb: the promotion the plan gate
# reads), pc (the phase claim `start` takes on the sharded layout),
# pd (the `done` verb: the close, and the SHA that makes it a record),
# tw (the tree the caller stands in against the tree the verb writes),
# sd (seed: the smallest honest plan, written where none was),
# gm (the marker inside the gap window, and a cause the check tested
# for rather than one it did not), bn (a shard write naming the
# phase's own branch against the one the caller stands on), ix (the
# index left dirty beside a shard, and the tool that lands it),
# dg (a gate-only task's `files` arm narrows only to a suite path, and
# a new phase's gate puts `meta.phaseGate.always` first and drops only what
# `meta.phaseGate.exclude` names), pg (the same phase-gate derivation,
# driven through `add-phase` itself), ff (`add --failing-from <runId>`
# gates a fix task on the suites a red sign-off run's own steps NAMED as
# failing).
def _cases(check):
    import contextlib
    import io
    import shutil
    import subprocess

    def run(argv):
        lines = []
        code = M.main(argv, out=lines.append)
        return code, "\n".join(lines)

    def run_on_stdin(argv, text):
        """`run`, with a real stream where stdin is -- the eb group's route.

        `sys.stdin` is SWAPPED rather than the module stubbed: `read_brief` reads
        whatever stream it is handed, so this hands it one, which is input and not
        a fake of the code under test. `test_check_ado_item.py` drives the same
        `-` dialect the same way, and the restore is unconditional because a
        selftest that left `sys.stdin` a StringIO would break every case after it.
        """
        real = sys.stdin
        sys.stdin = io.StringIO(text)
        try:
            return run(argv)
        finally:
            sys.stdin = real

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
        # `always`: these cases are about the verbs' mechanics under a reviewer
        # per task, which is what every close here was written against. The
        # shipped `phase` reading has its own cases, the `hd` block.
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json",
             "review": {"perTask": "always"}})
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        if sharded:
            _mio.save_sharded(mpath, manifest)
        else:
            _panel_write._atomic_write_json(mpath, manifest)
        if git:
            # The branch is named, not inherited: an unnamed `init` takes
            # whatever `init.defaultBranch` the machine's gitconfig carries, so
            # a verb that checks "forks from main" read a different fixture on
            # a runner whose git falls back to its built-in default.
            subprocess.run(["git", "init", "-q", "-b", "main", proj],
                           check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        return proj, mpath

    def mk_empty(name):
        """`(proj, mpath)` for a project `seed` can write INTO -- `mk()` minus
        the manifest write. Every other verb in this file needs one already
        there; `seed` is the one verb that refuses when it finds one, so its
        own second-direction case needs a project none of `mk()`'s callers
        would otherwise leave behind."""
        proj = os.path.join(tmp, name)
        os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json"})
        return proj, os.path.join(proj, "docs", "audit", "audit-plan.json")

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

        # a merged phase is never the default target, whatever its `status`
        # still says: `close-phase.py` stamps `mergedAt` and never touches
        # `status`, so a phase left at in_progress by a merge that outran its
        # own sign-off write must not silently take a new task.
        merged_stale = base_manifest()
        merged_stale["phases"][1]["mergedAt"] = "2026-01-01T00:00:00Z"
        proj4, _m4 = mk("a-merged-stale", merged_stale)
        code, txt = run(["add", "X", "--project-dir", proj4])
        check("a5b a merged-but-stale in_progress phase is not the default "
              "target -- exit 2, same as no in_progress phase at all",
              code == 2 and "P2" in txt and "P3" in txt)

        # CONTROL: a genuinely running phase beside a merged-but-stale one
        # resolves uniquely to the running one, not to "two in_progress
        # phases, --phase required".
        two_one_stale = base_manifest()
        two_one_stale["phases"][2]["status"] = "in_progress"
        two_one_stale["phases"][2]["mergedAt"] = "2026-01-01T00:00:00Z"
        proj5, m5 = mk("a-two-one-stale", two_one_stale)
        code, txt = run(["add", "Y", "--project-dir", proj5])
        check("a5c CONTROL a genuinely running phase beside a merged-and-"
              "stale one is still found and used as the default target",
              code == 0 and task_in(m5, "P2.4") is not None)

        code, txt = run(["add", "X", "--phase", "P1", "--project-dir", proj])
        check("a6 a done phase refuses -- immutable history",
              code == 2 and "immutable" in txt)
        check("a6b ...and nothing landed in it",
              len((_mio.load_manifest(mpath)["phases"][0].get("tasks"))) == 1)
        # A phase's done is DERIVED: every task finished plus a recorded verdict
        # (and a merge, for a phase with a branch). The signoff verb never writes
        # `status`, so a reader of the stored field alone sees in_progress.
        def _p3(mp):
            return _mio.load_manifest(mp)["phases"][2]

        def signed_p3(**extra):
            m = base_manifest()
            m["phases"][2].update(status="in_progress", review={"status": "passed"},
                                  tasks=[{"id": "P3.1", "title": "s",
                                          "status": "done"}], **extra)
            return m
        proj_ds, m_ds = mk("a-derived-done", signed_p3())
        code, txt = run(["add", "X", "--phase", "P3", "--project-dir", proj_ds])
        check("a6s a phase DONE BY DERIVATION refuses a new task like a stored done "
              "one - a task added now would reopen finished history: %r" % (txt,),
              code == 2 and "immutable" in txt
              and len(_p3(m_ds)["tasks"]) == 1)
        proj_sm, m_sm = mk("a-signed-unmerged", signed_p3(branch="audit/p3"))
        code, txt = run(["add", "X", "--phase", "P3", "--project-dir", proj_sm])
        check("a6t ...and so does one SIGNED OFF and awaiting its merge: the verdict "
              "on record reviewed a task set this would change: %r" % (txt,),
              code == 2 and "signed off" in txt
              and len(_p3(m_sm)["tasks"]) == 1)
        due = base_manifest()
        due["phases"][2].update(status="in_progress",
                                tasks=[{"id": "P3.1", "title": "s", "status": "done"}])
        proj_du, m_du = mk("a-due-beside-running", due)
        code, txt = run(["add", "Y", "--project-dir", proj_du])
        check("a5s the default target is the RUNNING phase: a phase only awaiting "
              "sign-off beside it is in_progress on the page and has no work left, "
              "so it does not make the default ambiguous: %r" % (txt[-120:],),
              code == 0 and task_in(m_du, "P2.4") is not None)
        due["phases"][1]["tasks"][1]["status"] = "done"
        proj_dn, _m_dn = mk("a-due-only", due)
        code, txt = run(["add", "Y", "--project-dir", proj_dn])
        check("a5t with nothing running there is no default, and the open phases it "
              "lists say which only await sign-off: %r" % (txt,),
              code == 2 and "no running phase" in txt
              and "P2 (in_progress, sign-off due)" in txt
              and "P3 (in_progress, sign-off due)" in txt)
        proj_rt, _m_rt = mk("a-retarget-signed", signed_p3(branch="audit/p3"))
        code, txt = run(["retarget", "P3", "--gate", "test", "--project-dir", proj_rt])
        check("a6u retarget refuses a SIGNED-OFF phase: its sign-off was given against "
              "the gate it had: %r" % (txt,),
              code == 2 and "sign-off" in txt)
        proj_ap, _m_ap = mk("a-addphase-signed", signed_p3())
        code, txt = run(["add-phase", "Dup", "--id", "P3", "--outcome", "o",
                         "--project-dir", proj_ap])
        check("a6v add-phase --id over a phase done by derivation offers no "
              "`add --phase` the next command would refuse: %r" % (txt,),
              code == 2 and "already exists (done)" in txt
              and "/audit:task add --phase P3" not in txt)
        proj_cx, m_cx = mk("a-cancel-signed", signed_p3())
        code, txt = run(["cancel", "P3", "--reason", "x", "--project-dir", proj_cx])
        check("a6w cancel refuses a phase done by derivation - terminal is terminal, "
              "and cancelling it would rewrite a sign-off: %r" % (txt,),
              code == 2 and "already done" in txt
              and _p3(m_cx)["status"] == "in_progress")
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
              "phase's testGate - and `gateBasis` records WHICH arm produced "
              "that list, because the arm is the thing a rule needs and the "
              "sentence the report prints is thrown away: %r" % (t.get("tests"),),
              t.get("tests") == {"mode": "gate-only", "add": [],
                                 "expectRedFirst": False, "gate": ["test"],
                                 "gateBasis": "phase-no-spelling"})
        check("t4 model floors at sonnet, risk defaults low",
              t.get("model") == "sonnet" and t.get("risk") == "low")

        code, _txt = run(["add", "Risky", "--phase", "P2",
                          "--project-dir", proj,
                          "--risk", "high", "--tests-mode", "tdd",
                          # The DOCUMENTED shape, `<path>: <what it asserts>`.
                          # It used to be a bare sentence here, and the
                          # suite agreed with the writer that a sentence is a
                          # path -- both were the same assumption, which is what
                          # a fixture written by the author of the parser costs.
                          "--tests-add",
                          "tests/repro.test.ts: it must fail first",
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
              == ["tests/repro.test.ts: it must fail first"])
        # The case named in `tests.add` is a file this task CREATES, so a
        # scope that excludes it fails the task's own commit through commit-scope.
        # One operator hand-fixed 13 tasks over exactly this, and reported that
        # there is no case where the divergence is wanted.
        # Its OWN project, because the ids in `proj` are positional and a task
        # added mid-suite renumbers every case after it.
        _tdd_proj, _tdd_mp = mk("a-tdd-note", base_manifest())
        code, _txt_tdd = run(["add", "No case named", "--phase", "P2",
                              "--project-dir", _tdd_proj, "--tests-mode", "tdd"])
        check("t5b a tdd task created with no --tests-add is NOTED at creation, "
              "not only at the next validate. A live run made two of these and "
              "the operator noticed later, by which point the work was already "
              "with an executor told to prove a red first with nothing to prove "
              "it with: %r" % (_txt_tdd[-260:],),
              code == 0 and "tests.add is empty" in _txt_tdd
              and "--tests-add" in _txt_tdd)
        check("t5c ...and a tdd task that DID name one is not noted, so the line "
              "means something when it appears",
              "tests.add is empty" not in _txt, repr(_txt[-160:]))
        check("t6b ...and the PATH the entry names is in `files`, unioned rather "
              "than left for the operator to type twice - the path and not the "
              "sentence around it: %r" % (t.get("files"),),
              "tests/repro.test.ts" in (t.get("files") or [])
              and not any(" " in f for f in (t.get("files") or [])))
        # The ordering rule asked of the helper that owns it, rather than by
        # creating a task here: the ids in this fixture are positional and a task
        # added mid-suite renumbers every case after it.
        check("t6c ...and the DECLARED order is kept with the derived case after "
              "it, duplicates dropped. `sorted(set(...))` would give the same "
              "scope and a different document on every edit, which is a diff "
              "nobody can review",
              M._union_paths(["src/a.ts", "src/b.ts"],
                             ["src/a.test.ts", "src/a.ts"])
              == ["src/a.ts", "src/b.ts", "src/a.test.ts"],
              repr(M._union_paths(["src/a.ts", "src/b.ts"],
                                  ["src/a.test.ts", "src/a.ts"])))
        check("t6d ...and a blank or non-string entry is not a path, so a stray "
              "comma in `--tests-add` cannot put an empty name into the scope",
              M._union_paths(["src/a.ts"], ["", "   ", None, "src/b.ts"])
              == ["src/a.ts", "src/b.ts"],
              repr(M._union_paths(["src/a.ts"], ["", "   ", None, "src/b.ts"])))

        # ---- (tp) the files union takes the PATH, or nothing ------------------
        # THE FIXTURES ARE THIS REPOSITORY'S OWN `tests.add` STRINGS, both
        # shapes, because the premise wrote down ("a tdd task creates the
        # file it names in `tests.add` BY DEFINITION") is true of the tasks that
        # name one and false of the FIELD, which the schema documents as
        # "Assertions/tests to author". Every regression task in this plan
        # carries the second shape.
        # THE NUMERAL IS BUILT AND NOT WRITTEN, which is `no-silent-pass`'
        # rule about a lint that reads text: `_output.prose_number_claims()`
        # scans every `.py` this repo keeps, this file included, and the plan
        # string below really does open with a case count. Rewording it would
        # make the fixture something somebody invented; building the literal
        # keeps the corpus string exactly as the plan carries it.
        _TP_NAMED = ("test_audit_task.py: the files union takes the leading "
                     "path of a tests.add entry")
        _TP_PROSE = ("%d selftest cases incl. exit-code matrix and readiness "
                     "rule" % (14,))
        _tp_proj, _tp_mp = mk("a-tests-add-path", base_manifest())
        # `regression` MODE, and the mode is load-bearing in this fixture rather
        # than incidental. `_manifest_rules._check_tests_add_shape` REQUIRES the
        # path shape of a `tdd` task that can still be committed against, so the
        # mixed pair below is only writable at a mode where the field is
        # best-effort - which is most of this plan's own entries. The tdd half of
        # the pair is `tp8`, where the same call is refused by the validator.
        code, _tp_txt = run(["add", "Named and unnamed", "--phase", "P2",
                             "--project-dir", _tp_proj,
                             "--tests-mode", "regression",
                             "--tests-add", _TP_NAMED,
                             "--tests-add", _TP_PROSE])
        _tp_task = task_in(_tp_mp, "P2.4") or {}
        check("tp1 the files union takes the leading path of a tests.add entry, "
              "and nothing at all from one that names no file - the SHARP half "
              "is the permission and not the pollution: the union exists so "
              "`commit_scope` will allow the file the task says it will create, "
              "and a sentence copied in is not that path, so the permission was "
              "never granted: %r" % (_tp_task.get("files"),),
              code == 0
              and _tp_task.get("files") == ["test_audit_task.py"])
        check("tp2 ...and the entry that named none is SAID, where it happened - "
              "a claim carries the basis that makes it true, and when the basis "
              "is missing that is the thing to say. Silence here tells the "
              "operator their case file is in scope when it is not: %r"
              % (_tp_txt[-320:],),
              "name no file" in _tp_txt and _TP_PROSE in _tp_txt
              and "<path>: <what it asserts>" in _tp_txt)
        check("tp3 ...and `fileIndex` gains the path and NOT the sentence, which "
              "is what the plan gate matches an edit against - a key no path can "
              "ever match is a row that will never fire: %r"
              % (sorted(_mio.load_manifest(_tp_mp).get("fileIndex") or {}),),
              sorted((_mio.load_manifest(_tp_mp).get("fileIndex") or {}).keys())
              == ["src/a.ts", "test_audit_task.py"])
        # SECOND-DIRECTION CASE, and it is the one that decides whether this can
        # ship: the note must not fire on a task whose every entry names a file,
        # or the operator learns to skip it.
        code, _tp_clean = run(["add", "All named", "--phase", "P2",
                               "--project-dir", _tp_proj,
                               "--tests-mode", "tdd",
                               "--tests-add", "tests/a.test.ts: one",
                               "--tests-add", "tests/b.test.ts: two"])
        check("tp4 SECOND-DIRECTION CASE: a task whose entries ALL name a file "
              "draws no note at all, and both paths reach `files` - a note on a "
              "correct call is a note somebody learns to skip: %r"
              % ((task_in(_tp_mp, "P2.5") or {}).get("files"),),
              code == 0 and "name no file" not in _tp_clean
              and (task_in(_tp_mp, "P2.5") or {}).get("files")
              == ["tests/a.test.ts", "tests/b.test.ts"])
        # THE PARSE ITSELF is graded in `test__manifest_rules.py`'s `ta` group,
        # where the parser lives: `tests_add_path` moved down beside the rule
        # that REQUIRES the shape, because the verb writing `files` and the rule
        # grading it have to ask one question. What stays here is what this verb
        # DOES with the answer.
        #
        # THE VALIDATOR IS THE OTHER HALF OF THE SAME REPAIR, and this is where
        # the two meet: a `tdd` task that can still be committed against owes
        # the path shape, and the walk's rule about `tests.add` says so.
        #
        # REFUSED AND ROLLED BACK FROM 3.0.0. `COMPATIBILITY.md` promised a
        # manifest that validates keeps validating through the 2.x line and
        # named 3.0.0 as where the shape stops being merely advised - so this
        # add, whose only defect is a `tdd` task's tests.add entry naming no
        # file, is refused by the same revalidate-after-write every other
        # invariant here goes through, and nothing it attempted is kept.
        with open(_tp_mp, "rb") as _fh:
            _tp_before = _fh.read()
        code, _tp_tdd = run(["add", "Tdd with prose", "--phase", "P2",
                             "--project-dir", _tp_proj,
                             "--tests-mode", "tdd",
                             "--tests-add", _TP_PROSE])
        with open(_tp_mp, "rb") as _fh:
            _tp_after = _fh.read()
        _tp_written = task_in(_tp_mp, "P2.6") or {}
        check("tp8 the SAME entry at `tdd` mode is REFUSED and rolled back: "
              "the manifest is byte-identical to before the call, and the "
              "finding names the entry and the shape it owes - a `tdd` task "
              "that can still be committed against has owed this shape since "
              "3.0.0 enforced what 2.3.0 only announced: %r"
              % (_tp_tdd[-300:],),
              code == M.E_INVALID and _tp_after == _tp_before
              and "names no file" in _tp_tdd
              and "<path>: <what it asserts>" in _tp_tdd
              and _TP_PROSE in _tp_tdd)
        check("tp8b ...and the rollback is COMPLETE: the task the call "
              "attempted never lands at all, not merely with an incomplete "
              "`files` union - a refused add that still left a task behind "
              "would be the half-write this verb exists to refuse: %r"
              % (_tp_written,),
              _tp_written == {})
        # `scope` is the OTHER two write sites, and the same file-union defect
        # reached all three. The verb an operator reaches for when reality
        # differed from the plan is the last place that should hand back a
        # scope it knows to be short.
        #
        # `regression` AGAIN, and for `tp1`'s reason one step on: a PENDING tdd
        # task carrying this entry is a manifest the validator refuses, so
        # `scope` would refuse the call before reading it ("already invalid") and
        # the case would be about the wrong thing.
        _tp_scope = base_manifest()
        _tp_scope["phases"][1]["tasks"].append(
            {"id": "P2.9", "title": "imported", "status": "pending",
             "files": [], "tests": {"mode": "regression", "add": [_TP_PROSE],
                                    "expectRedFirst": False, "gate": []}})
        _tps_proj, _tps_mp = mk("sc-tests-add-path", _tp_scope)
        code, _tps_txt = run(["scope", "P2.9", "--project-dir", _tps_proj,
                              "--files", "src/q.ts"])
        check("tp6 `scope --files` unions the paths the task's EXISTING "
              "tests.add names, so an entry that names none leaves `files` with "
              "exactly what the operator typed - and the call says so rather "
              "than reporting a scope it knows to be short: %r"
              % ((task_in(_tps_mp, "P2.9") or {}).get("files"),),
              code == 0
              and (task_in(_tps_mp, "P2.9") or {}).get("files") == ["src/q.ts"]
              and "name no file" in _tps_txt)
        code, _tps_txt2 = run(["scope", "P2.9", "--project-dir", _tps_proj,
                               "--tests-add",
                               "tests/q.test.ts: it caps the length"])
        check("tp7 ...and `scope --tests-add` unions the path the NEW entry "
              "names, appending it to the files already there: %r"
              % ((task_in(_tps_mp, "P2.9") or {}).get("files"),),
              code == 0
              and (task_in(_tps_mp, "P2.9") or {}).get("files")
              == ["src/q.ts", "tests/q.test.ts"]
              and "name no file" not in _tps_txt2)
        # A RE-SCOPE CONSULTS THE SAME ENTRY TWICE - once as the task's current
        # `tests.add` (because `--files` unions it back in) and once as the new
        # `--tests-add` - and the note lists the STRINGS so the reader knows
        # which line to go and fix. Naming one line twice makes them count
        # instead of read. COUNTED, not merely found: presence passes either way.
        _tpd_scope = base_manifest()
        _tpd_scope["phases"][1]["tasks"].append(
            {"id": "P2.9", "title": "imported", "status": "pending",
             "files": [], "tests": {"mode": "regression", "add": [_TP_PROSE],
                                    "expectRedFirst": False, "gate": []}})
        _tpd_proj, _tpd_mp = mk("sc-tests-add-dupe", _tpd_scope)
        code, _tpd_txt = run(["scope", "P2.9", "--project-dir", _tpd_proj,
                              "--files", "src/q.ts",
                              "--tests-add", _TP_PROSE])
        check("tp9 an entry the task ALREADY carries and the call passes again "
              "is named ONCE in the note, not twice - both lists are consulted "
              "and the entries they share are one line in the file: %r"
              % (_tpd_txt.count(_TP_PROSE),),
              code == 0 and _tpd_txt.count(_TP_PROSE) == 1
              and "name no file" in _tpd_txt)
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
        check("x2b ...and the note names BOTH readings of that silence instead "
              "of guessing the harmless one. It used to end `(new files?)`, "
              "which is the answer an operator who resolved their scope "
              "against the wrong root least needs to be handed: %r"
              % ([ln for ln in txt.split("\n")
                  if "nothing on disk answers for" in ln],),
              "will author them" in txt
              and "not the root these paths are relative to" in txt
              and proj in txt)

        # ---- (x3/x4) P59.6: a `:line-range` suffix must not defeat the stat -
        # The schema allows one on a `files` entry, and this verb used to pass
        # the raw entry to `os.path.exists`. A schema-legal `src/real.ts:5-9`
        # names a file that EXISTS, so reporting it as nothing on disk would be
        # wrong inside the one advisory an operator is asked to trust.
        os.makedirs(os.path.join(proj, "src"), exist_ok=True)
        with open(os.path.join(proj, "src", "real.ts"), "w") as _fh:
            _fh.write("x\n")
        code, txt = run(["add", "Suffixed and real", "--phase", "P2",
                         "--project-dir", proj, "--json",
                         "--files", "src/real.ts:5-9,src/still-missing.ts"])
        _x34 = json.loads(txt)
        check("x3 a suffixed entry naming a file that EXISTS does not join "
              "`filesNotOnDisk` under either spelling: %r"
              % (_x34.get("filesNotOnDisk"),),
              code == 0 and "src/real.ts:5-9" not in
              (_x34.get("filesNotOnDisk") or [])
              and "src/real.ts" not in (_x34.get("filesNotOnDisk") or []))
        check("x4 SECOND-DIRECTION CASE: an UNSUFFIXED entry in the SAME call "
              "that really is missing is still caught - the repair strips a "
              "suffix, it does not widen what counts as `on disk`: %r"
              % (_x34.get("filesNotOnDisk"),),
              "src/still-missing.ts" in (_x34.get("filesNotOnDisk") or []))

        # ---- (xp) a `--files` entry that cannot be a path -------------------
        # MEASURED: the incremental spelling every neighbouring tool offers went
        # into `files` as part of the filenames, into `fileIndex`, into a journal
        # row, and the only output was the note x2 is about. So the one shape
        # that is certainly a mistake read exactly like the one shape that is
        # certainly fine.
        _xp_before = open(mpath, "rb").read()
        _xp_code, _xp_txt = run(["add", "Delta spelling", "--phase", "P2",
                                 "--project-dir", proj,
                                 "--files", "+src/keep.ts,-src/drop.ts"])
        check("xp1 `--files` refuses an operator as a filename, before any "
              "write: the verb takes the REPLACEMENT list, and a string "
              "opening with a delta prefix is not a repository-relative path "
              "at all: %r" % (_xp_txt[:200],),
              _xp_code == 2 and "REPLACEMENT list" in _xp_txt
              and "'+src/keep.ts'" in _xp_txt and "'-src/drop.ts'" in _xp_txt
              and open(mpath, "rb").read() == _xp_before)
        check("xp2 ...and ONE message covers every bad entry in the call, "
              "because a caller who typed the delta spelling typed it on both "
              "sides and two refusals for one mistake is a class people learn "
              "to skip: %r" % (_xp_txt.count("--files takes the REPLACEMENT"),),
              _xp_txt.count("--files takes the REPLACEMENT") == 1)
        check("xp3 the other three shapes that are not repository-relative "
              "paths are refused by NAME, each with the reason it is not one - "
              "an absolute path, a home path, and a segment that climbs out of "
              "the tree: %r"
              % ([M._files_refusal([v]) is not None
                  for v in ("/etc/passwd", "~/notes.md", "src/../../x.ts")],),
              all(M._files_refusal([v]) is not None
                  for v in ("/etc/passwd", "~/notes.md", "src/../../x.ts")))
        check("xp4 SECOND-DIRECTION CASE, and it is the one an over-wide "
              "refusal breaks: declaring a file before it exists stays legal "
              "and stays QUIET, because the red-first workflow depends on it - "
              "and `..` inside a NAME is an ordinary filename, which a "
              "substring test would have refused: %r"
              % ([M._files_refusal([v]) for v in
                  ("src/not-yet.ts", "tests/a..b.py", "a-b/c-d.ts",
                   "src/x.ts")],),
              M._files_refusal(["src/not-yet.ts", "tests/a..b.py",
                                "a-b/c-d.ts", "src/x.ts"]) is None
              and M._files_refusal([]) is None)
        _xp_code2, _xp_txt2 = run(["scope", "P2.3", "--project-dir", proj,
                                   "--files", "+src/keep.ts"])
        check("xp5 ...and the refusal belongs to the FLAG rather than to the "
              "verb the defect was measured on: `scope` writes the same field "
              "into the same index off the same flag, so both doors ask: %r"
              % (_xp_txt2[:120],),
              _xp_code2 == 2 and "REPLACEMENT list" in _xp_txt2)

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

        # ---- (ix) the index left dirty beside a shard, and the tool that lands it
        # Reported from a live project: `/audit:task add` (and `add-phase`,
        # `scope`, `retarget`, `cancel`, `start`, `done` whenever a mirrored
        # stub key or `fileIndex` moves) can write the phase's shard AND the
        # shared index in ONE call, and nothing said the index was now sitting
        # uncommitted -- `commit-task-work.py` refuses to stage it (on
        # purpose, so two phases merge without a conflict there), so the only
        # way to land it is a SEPARATE tool this write never named.
        ixp, ixmp = mk("ix-sharded", base_manifest(), sharded=True)
        # `add-phase` is the row this class can be relied on to hit every
        # time: `_write_add`'s `index_dirty` is unconditional for a brand-new
        # stub, so there is no flag combination that skips it.
        code, ix_txt = run(["add-phase", "Second wave", "--outcome", "ships",
                            "--project-dir", ixp])
        check("ix1 a brand-new phase writes BOTH its shard and the index in "
              "one call, and the write says the index is now dirty and names "
              "the tool that lands it -- before now that tool's name reached "
              "a human only in the refusal that follows the mistake: %r"
              % (ix_txt[-320:],),
              code == 0 and "commit-manifest-index.py" in ix_txt
              and "DIRTY" in ix_txt)
        check("ix1b ...and it gives the ORDER: the shard it names is committed "
              "first, the index after - the other order records a plan that does "
              "not validate, and commit-manifest-index refuses it: %r"
              % (ix_txt[-320:],),
              "AFTER the shard" in ix_txt and "before or beside" not in ix_txt)
        ix_phase = [p for p in _mio.load_manifest(ixmp)["phases"]
                    if p.get("title") == "Second wave"][0]
        check("ix2 ...and the invocation it prints names THIS write's phase "
              "id, not a stale one left over from an earlier call in the "
              "same process: %r" % (ix_txt[-200:],),
              ix_phase["id"] in ix_txt.rsplit("commit-manifest-index.py", 1)[-1])
        code, ix_json_txt = run(["add-phase", "Third wave", "--outcome",
                                 "ships", "--project-dir", ixp, "--json"])
        ix_json = json.loads(ix_json_txt)
        check("ix3 the SAME note travels in --json as its own key, the "
              "`stdinNotes` shape: present with the sentence when there is "
              "one to make, so a machine caller can act on it without "
              "scraping human prose: %r" % (ix_json.get("indexDirtyNote"),),
              code == 0 and bool(ix_json.get("indexDirtyNote"))
              and "commit-manifest-index.py" in ix_json["indexDirtyNote"])
        # SECOND-DIRECTION CASE, and the one that decides whether this can
        # ship: an ordinary write that touches only the shard must say
        # NOTHING about the index, or the note becomes a line every plain
        # `add` prints and nobody reads.
        code, ix_quiet_txt = run(["add", "Quiet add", "--phase", "P2",
                                  "--project-dir", ixp])
        check("ix4 SECOND-DIRECTION CASE: a write that dirties only the "
              "shard names no tool and no index, because there is nothing "
              "to land: %r" % (ix_quiet_txt[-200:],),
              code == 0 and "commit-manifest-index.py" not in ix_quiet_txt
              and "DIRTY" not in ix_quiet_txt)
        code, ix_quiet_json_txt = run(["add", "Quiet add json", "--phase",
                                       "P2", "--project-dir", ixp, "--json"])
        ix_quiet_json = json.loads(ix_quiet_json_txt)
        check("ix5 ...and the JSON key is ABSENT rather than null or empty, "
              "the same 'nothing to say' shape `stdinNotes`/`projectBasis` "
              "already use, so a reader can tell 'nothing dirty' from 'this "
              "release carries no such key': %r"
              % (sorted(ix_quiet_json.keys()),),
              code == 0 and "indexDirtyNote" not in ix_quiet_json)
        # THE OTHER LAYOUT, where there is no separate index to leave dirty
        # at all -- the manifest IS the index, so the class this note exists
        # for cannot occur there.
        ixf_proj, ixf_mp = mk("ix-single", base_manifest())
        code, ixf_txt = run(["add-phase", "Single file wave", "--outcome",
                             "ships", "--project-dir", ixf_proj])
        check("ix6 the SINGLE-FILE layout never carries this note: there is "
              "one file and not two, so nothing was left dirty BESIDE "
              "anything: %r" % (ixf_txt[-160:],),
              code == 0 and "commit-manifest-index.py" not in ixf_txt)

        # ---- (bn) a write naming another phase's shard says which branch ------
        # The sharded layout promises a phase RUN touches only its own shard,
        # which is why two phase branches merge cleanly -- true of `run`, never
        # of these verbs, which take an id from wherever the caller happens to
        # be standing. Reproduced live: same tree, two branches, one shard, a
        # real merge conflict in the file the layout exists to keep
        # conflict-free.
        def bn_repo(name, phase_branch, checkout_branch):
            """A sharded, git-backed project with P2 recorded on
            `phase_branch` (or carrying none at all when `phase_branch` is
            None), currently checked out on `checkout_branch`."""
            m = base_manifest()
            if phase_branch:
                m["phases"][1]["branch"] = phase_branch
            proj, mpath = mk(name, m, sharded=True, git=True)
            subprocess.run(["git", "-C", proj, "checkout", "-q", "-b",
                            checkout_branch],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for argv in (["config", "user.email", "t@example.com"],
                        ["config", "user.name", "Test User"],
                        ["add", "-A"], ["commit", "-qm", "seed"]):
                subprocess.run(["git", "-C", proj] + argv,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            return proj, mpath

        bn1_proj, bn1_mp = bn_repo("bn-mismatch", "audit/p2-original",
                                    "mainline")
        code, bn1_txt = run(["cancel", "P2", "--reason", "dropped",
                             "--project-dir", bn1_proj])
        check("bn1 a write into P2's shard from branch `mainline`, while P2 "
              "is recorded on `audit/p2-original`, prints a WARNING naming "
              "BOTH branches and the phase -- naming it is the whole fix, "
              "because the writer then knows to expect a merge: %r"
              % (bn1_txt[-320:],),
              code == 0 and "WARNING: phase P2" in bn1_txt
              and "audit/p2-original" in bn1_txt and "mainline" in bn1_txt
              and "merge conflict" in bn1_txt)
        bn1_json = run(["cancel", "P2", "--reason", "dropped", "--json",
                        "--project-dir",
                        bn_repo("bn-mismatch-json", "audit/p2-json",
                               "mainline")[0]])
        bn1_parsed = json.loads(bn1_json[1])
        check("bn1b ...and the SAME fact travels in --json as its own key: %r"
              % (bn1_parsed.get("branchNote"),),
              bn1_json[0] == 0 and bool(bn1_parsed.get("branchNote"))
              and "audit/p2-json" in bn1_parsed["branchNote"])
        bn2_proj, bn2_mp = bn_repo("bn-match", "audit/p2-original",
                                   "audit/p2-original")
        code, bn2_txt = run(["cancel", "P2", "--reason", "dropped",
                             "--project-dir", bn2_proj])
        check("bn2 SECOND-DIRECTION CASE: standing on the SAME branch the "
              "phase records draws no warning at all -- the ordinary "
              "`/audit:phase run` flow, which must stay quiet or the note "
              "becomes a line every phase commit prints: %r"
              % (bn2_txt[-200:],),
              code == 0 and "WARNING: phase" not in bn2_txt)
        bn3_proj, bn3_mp = bn_repo("bn-nobranch", None, "mainline")
        code, bn3_txt = run(["cancel", "P2", "--reason", "dropped",
                             "--project-dir", bn3_proj])
        check("bn3 SECOND-DIRECTION CASE, AND THE ONE THAT DECIDES WHETHER "
              "THIS SHIPS: a phase recording NO branch at all draws no "
              "warning either, whatever branch the caller stands on -- "
              "measured over this project's own manifest, fewer than a "
              "fifth of its phases carry a branch and every phase running "
              "as this was written carries none, so a check keyed only on a "
              "populated branch is silent across this repository's own "
              "dogfood run. That silence is the stated condition, not a "
              "gap: %r" % (bn3_txt[-200:],),
              code == 0 and "WARNING: phase" not in bn3_txt)
        bn3_json = run(["cancel", "P3", "--reason", "dropped", "--json",
                        "--project-dir",
                        bn_repo("bn-nobranch-json", None, "mainline")[0]])
        bn3_parsed = json.loads(bn3_json[1])
        check("bn3b ...and the JSON key is ABSENT rather than null, the same "
              "shape `indexDirtyNote` already uses: %r"
              % (sorted(bn3_parsed.keys()),),
              bn3_json[0] == 0 and "branchNote" not in bn3_parsed)
        bn4_m = base_manifest()
        bn4_m["phases"][1]["branch"] = "audit/p2-original"
        bn4_proj, bn4_mp = mk("bn-nogit", bn4_m, sharded=True)
        code, bn4_txt = run(["cancel", "P2", "--reason", "dropped",
                             "--project-dir", bn4_proj])
        check("bn4 SECOND-DIRECTION CASE: with no git repository at all to "
              "ask, a recorded branch still draws no warning -- a claim "
              "with no way to verify it is refused the same way "
              "`standing_elsewhere` refuses one door over, never guessed: "
              "%r" % (bn4_txt[-200:],),
              code == 0 and "WARNING: phase" not in bn4_txt)
        with open(os.path.join(_output.PLUGIN_ROOT, "reference",
                               "orchestrator.md"), "r",
                  encoding="utf-8") as _bn_fh:
            _bn_orc_src = _bn_fh.read()
        check("bn5 `reference/orchestrator.md` gains the boundary the verbs "
              "cross -- the promise it states is `run`'s, and this document "
              "used to state it unhedged",
              "touches\n  **only its own shard**" in _bn_orc_src
              and "belongs to `run`, not to this verb" in
              _bn_orc_src.replace("\n", " "))

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

        # THE SAME HEAL IN THE SHARDED LAYOUT, WHERE THE PHASE HAS TWO HOMES.
        # `reference/orchestrator.md` lists the phase status-mirror write among
        # the index-lock writes and `reference/manifest-conventions.md` rests
        # `priority`'s index-only rule on the stub carrying `status` -- while the
        # writer copied identity alone, so every reader of the index alone was
        # told a running phase was pending, and the ordering argument the layout
        # is built on rested on a key nothing wrote.
        healsh = base_manifest()
        healsh["phases"][2]["tasks"] = [{"id": "P3.1", "title": "hand-flipped",
                                         "status": "in_progress"}]
        projhs, mpathhs = mk("h-heal-sharded", healsh, sharded=True)
        codehs, _txths = run(["add", "Heal me", "--phase", "P3",
                              "--project-dir", projhs])
        hs_idx = _mio.read_json(mpathhs)
        hs_stub = [s for s in hs_idx["phases"]
                   if isinstance(s, dict) and s.get("id") == "P3"][0]
        hs_body = [p for p in _mio.load_manifest(mpathhs)["phases"]
                   if p.get("id") == "P3"][0]
        check("h3 ...and in the SHARDED layout the index stub is moved with the "
              "shard, so a reader of the index alone is not told a running "
              "phase is pending: %r" % (hs_stub,),
              codehs == 0 and _mio.is_sharded(hs_idx)
              and hs_stub.get("status") == "in_progress"
              and hs_body.get("status") == "in_progress")
        # SECOND DIRECTION, and the one a mirror gets wrong by being written
        # unconditionally: the index is dirtied only when a mirrored key MOVED,
        # which is what keeps a phase's WORK out of the shared file.
        hs_before = open(mpathhs, "rb").read()
        codehs2, _txths2 = run(["add", "Second task", "--phase", "P3",
                                "--project-dir", projhs])
        check("h4 ...and a second write that moves no mirrored key leaves the "
              "index byte-identical - the mirror is refreshed on a phase's own "
              "transition, never on the work inside it, or two phase branches "
              "would collide on the index they no longer have to touch",
              codehs2 == 0 and open(mpathhs, "rb").read() == hs_before)

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
            # `audit-lock.py`, and nothing that reads a lock. This group
            # ACQUIRES and seizes one - it drives `main()`, the command's half,
            # and plants a claim through the library's writer. The panel used to publish a
            # READ-side accessor that answered with the library, and the write
            # path reached it for a command entry point the library never
            # promised; the accessor is out of that path now, and a taker says
            # which module it means in an import.
            lockmod = _loader.load_script("audit-lock.py", modname="audit_lock")
            check("k0 the lock library loads", lockmod is not None)
            # THE CALLER IS A STRANGER, AND THAT IS PINNED RATHER THAN FOUND.
            # A claim is re-entered by a process carrying its token, or by the
            # session or pid it was taken for - so the fixture lock is taken
            # in a CHILD, whose token dies with it, and every name this run
            # could go by is unset for the group. Taken in-process, the token
            # travels in this process's environment and the verb reads the
            # lock as its own; that only stayed hidden where the runner
            # happened to name a different session.
            _k_names = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PID",
                        "AUDIT_LOCK_TOKENS")
            _k_saved = dict((n, os.environ.get(n)) for n in _k_names)
            for n in _k_names:
                os.environ.pop(n, None)
            try:
                if lockmod is not None:
                    held = subprocess.run(
                        [sys.executable,
                         os.path.join(_output.SCRIPTS_DIR, "governance",
                                      "audit-lock.py"),
                         "acquire", "index", "--project", projk,
                         "--note", "phase P2 run", "--session", "sess-A",
                         "--pid", str(os.getpid())],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        universal_newlines=True)
                    check("k0b fixture lock taken, by a child",
                          held.returncode == 0, held.stdout)
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
                    _lock_lib._write_lock(lpath, info)
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
            finally:
                for n, v in _k_saved.items():
                    if v is None:
                        os.environ.pop(n, None)
                    else:
                        os.environ[n] = v
        projl, mpathl = mk("k-legacy", base_manifest())
        open(mpathl + ".lock", "w").close()
        code, txt = run(["add", "X", "--phase", "P2", "--project-dir", projl])
        check("k5 outside a git repo the working-tree lockfile still refuses",
              code == 3 and "locked" in txt)
        os.remove(mpathl + ".lock")

        # ---- (n) named-manifest project resolution ----------------------------
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
              "cwd/env repo", code == 0 and len(frows) == 1)
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

        # MARKERLESS trees (no .claude, no .git anywhere above). The
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
              "manifest, where default readers find it",
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
        # Nothing appended to `phases[]` except the ADO pull: init writes a
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
        # Tested END TO END, and the fixture above cannot reach it: `P0`, `P1`
        # live and `P2` parked is a plan with NO GAP, so the lowest-free rule
        # and the highest-plus-one rule both answer `P3` there and every case
        # from p1 down passes under either. This fixture has the gap the live
        # plan had. Driven through the VERB rather than the allocator, because
        # `_allocate_phase_id` was already sharing the taken set correctly and
        # what went wrong was the rule it applied to it.
        gap = phase_fixture()
        gap["proposals"] = []
        gap["phases"] = [
            {"id": "P0", "title": "Shipped", "status": "done",
             "testGate": ["unit"], "tasks": []},
            {"id": "P1", "title": "Also shipped", "status": "done",
             "testGate": ["unit"], "tasks": []},
            {"id": "P3", "title": "Live", "status": "in_progress",
             "testGate": ["unit"], "tasks": []},
        ]
        projgap, mpgap = mk("p-gap", gap)
        code, txt = run(["add-phase", "After the gap", "--project-dir", projgap,
                         "--outcome", "the next body of work is tracked"])
        _gap_ids = [ph.get("id")
                    for ph in _mio.load_manifest(mpgap)["phases"]]
        check("p3b the id is the HIGHEST plus one, so a gap in the plan "
              "is never re-minted - `P2` here is a phase that HAPPENED and "
              "`meta.branch` derives the branch name from the id, so handing "
              "it back names branches and merges that already exist. Measured "
              "live on this repository's plan: P0, then P30, then P32: %r"
              % (_gap_ids,),
              code == 0 and _gap_ids == ["P0", "P1", "P3", "P4"])
        emptyish = phase_fixture()
        emptyish["proposals"] = []
        emptyish["phases"] = []
        projzero, mpzero = mk("p-zero", emptyish)
        code, txt = run(["add-phase", "First", "--project-dir", projzero,
                         "--outcome", "there is a plan"])
        # ...and the OTHER half of that rule, which had no case at all: the
        # claim that an explicit `--id P0` stays ACCEPTED lived in three
        # docstrings and `ap3b`'s prose, and the only `--id P0` case asserted a
        # duplicate refusal. `examples/acme-store` ships a real P0 phase and
        # `templates/audit-plan.starter.json` opens with one, so a future
        # refusal-of-zero would break both - and nothing would have caught it.
        zero = phase_fixture()
        zero["proposals"] = []
        zero["phases"] = [{"id": "P4", "title": "Later", "status": "pending",
                           "testGate": ["unit"], "tasks": []}]
        projp0, mpp0 = mk("p-id-zero", zero)
        code, txt = run(["add-phase", "Groundwork", "--id", "P0",
                         "--outcome", "the base is in place",
                         "--project-dir", projp0])
        check("p3d an explicit `--id P0` is ACCEPTED - only ALLOCATION refuses "
              "zero, and it refuses it by SHAPE (highest-plus-one from a floor "
              "of zero) rather than by a rule about the id. The starter "
              "template opens with a P0 and the shipped example carries one, so "
              "a caller naming it is naming a legal id: %r"
              % ([ph.get("id")
                  for ph in _mio.load_manifest(mpp0)["phases"]],),
              code == 0
              and [ph.get("id")
                   for ph in _mio.load_manifest(mpp0)["phases"]]
              == ["P4", "P0"])
        check("p3c ...and it never allocates `P0`, even with nothing taken at "
              "all: an append happens in a plan that already exists, so a zero "
              "there would be an id minted from the absence of evidence. An "
              "`--id P0` the CALLER names stays legal - the starter template "
              "opens with one: %r"
              % ([ph.get("id")
                  for ph in _mio.load_manifest(mpzero)["phases"]],),
              code == 0
              and [ph.get("id")
                   for ph in _mio.load_manifest(mpzero)["phases"]] == ["P1"])
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
        #
        # THEY PASS A NODE THAT IS IN THE MANIFEST, found by id, because that is
        # what the three call sites pass now, in place of a synthetic dict
        # handed in from outside that answers about no task at all - and it
        # was exactly that shape, a task dict with no phase attached to it,
        # which hid the fourth readiness term here for as long as it did.
        _wm = {"phases": [
            {"id": "P0", "title": "groundwork", "status": "done"},
            {"id": "P1", "title": "next", "status": "in_progress", "tasks": [
                {"id": "P1.1", "title": "t", "status": "pending"},
                {"id": "P1.2", "title": "behind a done phase", "status": "pending",
                 "blockedBy": ["P0"], "dependsOn": []},
                {"id": "P1.3", "title": "behind a live phase", "status": "pending",
                 "blockedBy": ["P1"], "dependsOn": []},
                {"id": "P1.4", "title": "behind a sibling", "status": "pending",
                 "blockedBy": [], "dependsOn": ["P1.1"]},
                {"id": "P1.5", "title": "malformed refs", "status": "pending",
                 "blockedBy": [None, 7, [1, 2]], "dependsOn": []}]},
        ]}

        def wnode(manifest, nid):
            """The node `nid` names, taken OUT of the manifest - which is what
            every call site passes and what the id lookup has to resolve."""
            for _ph in (manifest.get("phases") or []):
                if _ph.get("id") == nid:
                    return _ph
                for _t in (_ph.get("tasks") or []):
                    if _t.get("id") == nid:
                        return _t
            return {}

        # DONE on purpose: a phase missing from the index reads back as None,
        # which is already "not done", so a PENDING blocker would let the folded
        # version and this one agree and prove nothing.
        check("w1 a ref to a task-less DONE phase counts as satisfied: %r"
              % (M._waiting_on(_wm, wnode(_wm, "P1.2")),),
              M._waiting_on(_wm, wnode(_wm, "P1.2")) == [])
        # The other direction, and it looks vacuous by design: it is the only
        # case that fails if `_waiting_on` ever becomes "nothing is ever waiting".
        check("w2 ...while a ref to a phase that is NOT done is still reported: "
              "%r" % (M._waiting_on(_wm, wnode(_wm, "P1.3")),),
              M._waiting_on(_wm, wnode(_wm, "P1.3")) == ["P1"])
        check("w3 a task ref resolves through the same index: %r"
              % (M._waiting_on(_wm, wnode(_wm, "P1.4")),),
              M._waiting_on(_wm, wnode(_wm, "P1.4")) == ["P1.1"])
        # w4: this call site tested `!= "done"` while audit-status' readiness
        # used ("done", "cancelled"), so a task blocked by a CANCELLED task was
        # ready to /audit:status and still waiting to /audit:task add - one
        # manifest, two answers. `cancelled` arrived as the second terminal state
        # and this line never followed. The rule now has one home.
        _wc = {"phases": [{"id": "P1", "title": "p", "status": "in_progress",
                           "tasks": [{"id": "P1.1", "title": "dropped",
                                      "status": "cancelled"},
                                     {"id": "P1.2", "title": "waiter",
                                      "status": "pending",
                                      "blockedBy": ["P1.1"],
                                      "dependsOn": []}]}]}
        check("w4 a ref to a CANCELLED task counts as satisfied, exactly as "
              "/audit:status' readiness has always counted it: %r"
              % (M._waiting_on(_wc, wnode(_wc, "P1.2")),),
              M._waiting_on(_wc, wnode(_wc, "P1.2")) == [])
        # w5-w6: same unvalidated-input class audit-status carries. A
        # non-hashable ref used to raise inside the index lookup here too.
        try:
            _wbad = M._waiting_on(_wm, wnode(_wm, "P1.5"))
        except Exception as _wexc:
            _wbad = "RAISED %s: %s" % (type(_wexc).__name__, _wexc)
        check("w5 a malformed ref does not raise here either - the same defect "
              "lived at this call site, not only in audit-status: %r" % (_wbad,),
              _wbad == ["None", "7", "[1, 2]"])
        check("w6 ...and _waiting_on returns only strings, so whatever joins "
              "them cannot die on the row: %r" % (_wbad,),
              isinstance(_wbad, list) and all(isinstance(x, str) for x in _wbad))
        # w7-w8: the fourth term of the readiness rule. `reference/
        # orchestrator.md` lists four and this function carried two, so a task
        # whose PHASE was parked read as ready - and `/audit:status`, reading
        # `_status_facts`, said the opposite about the same manifest. The suffix
        # is what makes the answer usable: a bare `P0` here would send a reader
        # looking for a task by that name.
        _wp = {"phases": [
            {"id": "P0", "title": "environment", "status": "pending"},
            {"id": "P1", "title": "the work", "status": "pending",
             "blockedBy": ["P0"], "tasks": [
                 {"id": "P1.1", "title": "t", "status": "pending",
                  "blockedBy": [], "dependsOn": []}]}]}
        check("w7 a task whose own refs are all clear is STILL waiting when its "
              "PHASE is blocked, and the ref says which term it came from: %r"
              % (M._waiting_on(_wp, wnode(_wp, "P1.1")),),
              M._waiting_on(_wp, wnode(_wp, "P1.1")) == ["P0 (phase)"])
        # THE PAIRED NEGATIVE. A version that appended the phase's `blockedBy`
        # without asking whether it was satisfied would pass w7 forever while
        # reporting every task in every phase as waiting.
        _wp2 = json.loads(json.dumps(_wp))
        _wp2["phases"][0]["status"] = "done"
        check("w8 SECOND-DIRECTION CASE: ...and when that phase blocker is DONE "
              "the task is ready again, so the term is evaluated rather than "
              "merely appended: %r" % (M._waiting_on(_wp2, wnode(_wp2, "P1.1")),),
              M._waiting_on(_wp2, wnode(_wp2, "P1.1")) == [])

        # ---- (sc) `scope`, the verb the importer's own instruction needed
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
        # This refusal has been narrowed once and split once since, and neither
        # removed it. The call above REPLACES `src/a.ts` with `src/b.ts`, so it
        # is a NARROWING - and a narrowing is refused on a done task for the one
        # reason that is true of a done task: its commit was graded against the
        # list it holds, so dropping an entry moves a judgement already made.
        # (The other shape, a WIDENING, settles the index rather than
        # re-judging anything - the st group holds it.)
        check("sc4 a NARROWING on a task whose commit was already graded is "
              "refused, and the refusal names the grading rather than the "
              "status alone - `done` is not `running` and must not borrow the "
              "started sentence: %r" % (txt[:120],),
              code == 2 and "is done" in txt
              and "graded against the files it names" in txt
              and "a judgement that has already been made" in txt
              and "it is running against the scope" not in txt)
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

        # ---- (sc8/sc9) P59.6: the SAME repair, on `scope`'s own stat --------
        # `add` and `scope` build `missing` the same way and used to pass the
        # raw entry to `os.path.exists` the same way; `src/b.ts` is on disk
        # from the setup above, so a suffixed re-declaration of it must not
        # start reading as absent.
        code, txt = run(["scope", "P2.3", "--files",
                         "src/b.ts:1-2,src/missing.ts",
                         "--project-dir", sc_proj, "--json"])
        _sc89 = json.loads(txt)
        check("sc8 a suffixed entry naming a file that EXISTS does not join "
              "`filesNotOnDisk`: %r" % (_sc89.get("filesNotOnDisk"),),
              code == 0 and "src/b.ts:1-2" not in
              (_sc89.get("filesNotOnDisk") or [])
              and "src/b.ts" not in (_sc89.get("filesNotOnDisk") or []))
        check("sc9 SECOND-DIRECTION CASE: the UNSUFFIXED entry in the SAME "
              "call that really is missing is still caught: %r"
              % (_sc89.get("filesNotOnDisk"),),
              "src/missing.ts" in (_sc89.get("filesNotOnDisk") or []))

        # ---- (sn) the verb was unusable on the task it exists for ------------
        # `tests` used to be materialized unconditionally, so `scope --files`
        # alone left `tests: {}` behind - and an ABSENT `tests` is legal while
        # one present without a `mode` is not (`_manifest_phases.py`). The
        # rollback held, so nothing was ever corrupted; the verb simply could
        # not run. Measured live on the scope-import case above: an imported
        # task whose description says "scope files/tests before running" has
        # no `tests` key, and the refusal read `tests.mode None not in [...]`,
        # which describes the manifest for a defect in the writer.
        sn_proj, sn_mp = mk("p-scope-notests", base_manifest())
        os.makedirs(os.path.join(sn_proj, "src"), exist_ok=True)
        with open(os.path.join(sn_proj, "src", "b.ts"), "w") as _fh:
            _fh.write("x\n")
        _snm = _mio.read_json(sn_mp)
        for _snp in _snm["phases"]:
            for _snt in _snp["tasks"]:
                if _snt["id"] == "P2.3":
                    _snt.pop("tests", None)
        with open(sn_mp, "w") as _fh:
            json.dump(_snm, _fh, indent=2)
        code, txt = run(["scope", "P2.3", "--files", "src/b.ts",
                         "--project-dir", sn_proj])
        _snt = task_in(sn_mp, "P2.3")
        check("sn1 scope succeeds on a task with NO tests key, and leaves it "
              "without one - the field is not this call's business and an empty "
              "object is the one shape the schema refuses: %r"
              % ((code, _snt.get("files"), "tests" in _snt),),
              code == 0 and _snt.get("files") == ["src/b.ts"]
              and "tests" not in _snt)
        code, txt = run(["scope", "P2.3", "--files", "src/b.ts", "--gate",
                         "lint", "--project-dir", sn_proj])
        check("sn2 ...while --gate ALONE on such a task is refused BEFORE the "
              "write, naming the flag that resolves it - writing would build a "
              "`tests` without a `mode`, and defaulting one would have this verb "
              "invent a grading nobody chose: %r" % (txt[:110],),
              code == 2 and "has no `tests` object" in txt
              and "--tests-mode" in txt
              and "tests" not in task_in(sn_mp, "P2.3"))
        code, txt = run(["scope", "P2.3", "--files", "src/b.ts", "--tests-mode",
                         "gate-only", "--gate", "lint", "--project-dir",
                         sn_proj])
        _snt = task_in(sn_mp, "P2.3")
        check("sn3 ...and the two together DO write, which is the paired "
              "positive: a refusal that also blocked the spelling it recommends "
              "would just be the old bug behind a better sentence: %r"
              % (_snt.get("tests"),),
              code == 0 and (_snt.get("tests") or {}).get("mode") == "gate-only"
              and (_snt.get("tests") or {}).get("gate") == ["lint"])
        code, txt = run(["scope", "P2.3", "--files", "src/b.ts", "--gate",
                         "true", "--project-dir", sn_proj])
        check("sn4 ...after which --gate alone is accepted, because the object "
              "now exists - the refusal is about the MISSING object and not "
              "about the flag: %r" % (txt[:80],),
              code == 0
              and (task_in(sn_mp, "P2.3").get("tests") or {}).get("gate")
              == ["true"])

        # ---- (rt) a plan can be CORRECTED, not only created ------------------
        # `init` and `pull sprint` synthesize a phase and choose its `testGate`;
        # until `retarget` that choice was unreachable, and one wrong choice made
        # the phase unable to pass its own sign-off. `--gate` REPLACES, so the
        # empty gate - which `_phase_gate` documents as a designed state, sign-off
        # on review alone - had no spelling at all after import: no VALUE of
        # `--gate` means "none".
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
        check("rt2 ...and --gate-clear reaches the EMPTY gate, which no `--gate` "
              "VALUE can spell - the designed state a guessed gate "
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
        # ---- (rn) a phase can be renamed, and a rename is not a label --------
        # Reported from a live run: a phase whose scope widened kept a title
        # describing half of it, and nothing could change it - `phase.title` is
        # written at creation and never again, the panel does not touch it, and
        # `retarget` had no flag for it.
        #
        # THE GUARD IS THE INTERESTING HALF, and it comes from a divergence
        # measured in the tree rather than from caution: `_branch.slugify` turns
        # the title into the branch's `{slug}`, `close-phase.py` and
        # `manage-worktrees.py` both prefer a recorded `phase.branch`, and
        # `resolve-branch.py` composes from the title UNCONDITIONALLY. So renaming
        # a phase that is already on a branch leaves three readers with two
        # answers. Before entry there is nothing to disagree with, and that is
        # when a widened scope is usually noticed.
        _rn = base_manifest()
        _rn["phases"][2].update({"status": "pending", "branch": None,
                                 "title": "Residual type-safety debt"})
        rn_proj, rn_mp = mk("rn-rename", _rn)
        code, txt = run(["retarget", "P3", "--rename", "Type safety and the "
                         "assertion debt behind it", "--project-dir", rn_proj])
        _rnp = _mio.load_manifest(rn_mp)["phases"][2]
        check("rn1 a phase that has not entered can be renamed, and the write "
              "moves the title the branch slug is composed from: %r"
              % (_rnp.get("title"),),
              code == 0
              and _rnp.get("title") == "Type safety and the assertion debt "
                                       "behind it")
        _rnb = base_manifest()
        _rnb["phases"][2].update({"status": "in_progress",
                                  "branch": "audit/p3-already-cut",
                                  "title": "already cut"})
        rnb_proj, rnb_mp = mk("rn-oncut", _rnb)
        code, txt = run(["retarget", "P3", "--rename", "something else",
                         "--project-dir", rnb_proj])
        check("rn2 SECOND DIRECTION: a phase already ON a branch is refused, and "
              "the refusal names the three readers rather than saying 'no' - a "
              "rename there gives the phase two names and no reader agreeing on "
              "which: %r" % (txt[:120],),
              code == 2 and "already on branch" in txt
              and "resolve-branch.py" in txt
              and _mio.load_manifest(rnb_mp)["phases"][2].get("title")
              == "already cut")
        # THE SHARDED LAYOUT IS WHERE A RENAME CAN HALF-LAND, and it did until
        # this case: `title` is one of `_mio._STUB_KEYS`, so the index carries a
        # COPY of it, and `_write_add` rewrites the index only when the fileIndex
        # moved. The shard took the new title and the stub kept the old one - a
        # reader of the index alone, which is the entire point of a stub, got the
        # name the phase was created with. Read off the RAW index rather than the
        # assembled manifest, because assembly merges the stub with the body and
        # the body wins: the very read that hides this.
        _rns = base_manifest()
        _rns["phases"][2].update({"status": "pending", "branch": None,
                                  "title": "Residual type-safety debt"})
        rns_proj, rns_mp = mk("rn-sharded", _rns, sharded=True)
        code, txt = run(["retarget", "P3", "--rename", "Type safety and the "
                         "assertion debt behind it", "--project-dir", rns_proj])
        _rns_idx = _mio.read_json(rns_mp)
        _rns_stub = [s for s in _rns_idx["phases"]
                     if isinstance(s, dict) and s.get("id") == "P3"][0]
        _rns_body = _mio.load_manifest(rns_mp)["phases"][2]
        check("rn3 ...and in the SHARDED layout the rename reaches the index "
              "STUB too, not only the shard body - a stub is what a reader of "
              "the index alone is answered from, so a stale copy there is the "
              "phase having two names: stub=%r body=%r"
              % (_rns_stub.get("title"), _rns_body.get("title")),
              code == 0 and _mio.is_sharded(_rns_idx)
              and _rns_stub.get("title") == "Type safety and the assertion "
                                            "debt behind it"
              and _rns_stub.get("title") == _rns_body.get("title"))
        # THE OTHER DIRECTION, and it needs its own reader. `y3` asks whether the
        # index file is byte-identical, which a refresh that rewrites the same
        # values passes -- so it cannot see a stub refresh that fires when nothing
        # moved. The written-paths list can: the stub design exists so a phase RUN
        # touches only its shard, and a write that names the index has given that
        # up whether or not the bytes came out the same.
        code, txt = run(["add", "Sharded add, no stub key moved", "--phase",
                         "P2", "--project-dir", rns_proj, "--json"])
        _rns_written = []
        try:
            _rns_written = (json.loads(txt) or {}).get("written") or []
        except Exception:
            pass
        check("rn5 ...and a write that moves NO stub key still leaves the index "
              "alone: only the shard is written, which is what lets two phase "
              "branches merge without a manifest conflict: %r" % (_rns_written,),
              code == 0 and _rns_written
              and not [p for p in _rns_written if p.endswith("audit-plan.json")])
        # DRIVEN, not introspected, and it stays driven now that there IS a
        # `build_parser()` to ask (built for this file, the same shape P26.1
        # extracted for `audit-doctor.py`). The parser is what would answer
        # "is `--title` declared"; only a run answers "and what happens when
        # somebody passes it", which is argparse refusing an unknown option on
        # STDERR and is the thing this case is about.
        _rn_code, _rn_txt = run(["retarget", "P3", "--title", "shadowed",
                                 "--project-dir", rnb_proj])
        check("rn4 ...and the flag is `--rename` rather than `--title`: this "
              "verb's POSITIONAL slot is called `title` and carries the phase "
              "id, so `--title` would shadow the id and read as the one thing it "
              "is not. argparse refuses it as unknown - on STDERR, which this "
              "helper does not collect, so the exit code is the assertion: "
              "code=%r out=%r" % (_rn_code, _rn_txt[:60]),
              _rn_code == 2
              and _mio.load_manifest(rnb_mp)["phases"][2].get("title")
              == "already cut")

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

        # ---- (rt10-18) retarget --gate-drop and --gate-set, one write each ---
        # `--gate-set` is `--gate`'s own REPLACE operation under a name that
        # takes several values under one flag instead of one value per repeat;
        # `--gate-drop` is the other operation, narrowing the CURRENT gate by
        # name. Both go through `_locked_retarget`, one lock, one
        # revalidate-or-roll-back, one `phase.retarget` journal row.
        def _gs_manifest():
            m = base_manifest()
            m["phases"][2]["testGate"] = ["test", "coverage"]
            return m
        gs_proj, gs_mp = mk("p-gate-drop-set", _gs_manifest())
        import _journal_io

        def gs_gate():
            return _mio.load_manifest(gs_mp)["phases"][2].get("testGate")

        code, txt = run(["retarget", "P3", "--gate-drop", "coverage",
                         "--project-dir", gs_proj])
        _gs_rows = [r for r in _journal_io.read_all(gs_proj)
                   if r.get("action") == "phase.retarget"]
        check("rt10 RED-FIRST: --gate-drop coverage on a phase gated "
              "[test, coverage] writes [test] with ONE phase.retarget journal "
              "row - today's parser does not declare the flag at all, so "
              "argparse refuses the call outright instead of writing anything: "
              "%r" % ((code, gs_gate(), len(_gs_rows)),),
              code == 0 and gs_gate() == ["test"] and len(_gs_rows) == 1)
        code, txt = run(["retarget", "P3", "--gate-drop", "test",
                         "--project-dir", gs_proj])
        check("rt11 dropping the ONLY remaining entry is refused with the "
              "empty-gate sentence rather than silently emptied - that state is "
              "reached through --gate-clear alone, which SAYS it is choosing "
              "it: %r" % (txt[:90],),
              code == 2 and "an empty gate is --gate-clear" in txt
              and gs_gate() == ["test"])
        code, txt = run(["retarget", "P3", "--gate-drop", "nope",
                         "--project-dir", gs_proj])
        check("rt12 --gate-drop naming an entry NOT in the phase's testGate is "
              "refused, naming the missing entry and the gate as it stands - a "
              "typo is not silently a no-op: %r" % (txt[:130],),
              code == 2 and "nope" in txt and '["test"]' in txt
              and gs_gate() == ["test"])
        code, txt = run(["retarget", "P3", "--gate-set",
                         "--project-dir", gs_proj])
        check("rt13 RED-FIRST: --gate-set with NO value is refused with the "
              "SAME empty-gate sentence, not argparse's own usage error for a "
              "starved flag: %r" % (txt[:90],),
              code == 2 and "an empty gate is --gate-clear" in txt
              and gs_gate() == ["test"])
        code, txt = run(["retarget", "P3", "--gate-set", "", "  ",
                         "--project-dir", gs_proj])
        check("rt14 SECOND DIRECTION: --gate-set of all-BLANK values is refused "
              "the same way as no values at all - a caller who typed nothing "
              "but blanks almost always meant the empty gate: %r" % (txt[:90],),
              code == 2 and "an empty gate is --gate-clear" in txt
              and gs_gate() == ["test"])
        code, txt = run(["retarget", "P3", "--gate-set", "lint",
                         "--project-dir", gs_proj])
        check("rt15 ALLOW CASE: --gate-set lint REPLACES the gate outright, "
              "the same operation --gate performs under a name that takes "
              "several values at once - declared, not narrowed or guessed: %r"
              % (gs_gate(),),
              code == 0 and gs_gate() == ["lint"])
        code, txt = run(["retarget", "P3", "--gate-set", "typecheck", "test",
                         "--project-dir", gs_proj])
        check("rt16 --gate-set takes SEVERAL values under one flag, unlike "
              "--gate's repeated spelling of the same operation: %r"
              % (gs_gate(),),
              code == 0 and gs_gate() == ["typecheck", "test"])
        code, txt = run(["retarget", "P3", "--gate-drop", "test", "--gate-set",
                         "lint", "--project-dir", gs_proj])
        check("rt17 --gate-drop with --gate-set is refused exactly as --gate "
              "with --gate-clear is - two answers to one question, and "
              "guessing which was meant is the fault this closes: %r"
              % (txt[:90],),
              code == 2 and "opposite things" in txt
              and gs_gate() == ["typecheck", "test"])
        code, txt = run(["retarget", "P1", "--gate-drop", "test",
                         "--project-dir", gs_proj])
        check("rt18 a DONE phase refuses --gate-drop too, by the SAME "
              "past-sign-off rule --gate-clear already uses, unchanged: %r"
              % (txt[:90],),
              code == 2 and "was given against the gate it had" in txt)

        # THE OTHER half of the pending rule: an attempted task keeps an
        # outcome describing work judged under the scope it had.
        #
        # THE CALL CHANGED AND THE CLAIM DID NOT. This used to pass
        # `--files src/a.ts` at a task holding none, which is a WIDENING and is
        # now accepted (the wd group drives that). `--description` is the field
        # the entry's own reason is sharpest about: the outcome answers the
        # description, so rewriting it is precisely what would make the record
        # describe something else.
        at_proj, at_mp = mk("p-attempted", base_manifest())
        _am = _mio.load_manifest(at_mp)
        _am["phases"][1]["tasks"][1]["attempts"] = 1
        _panel_write._atomic_write_json(at_mp, _am)
        code, txt = run(["scope", "P2.3", "--description", "a different job",
                         "--project-dir", at_proj])
        check("rt9 scope refuses a change that is NOT a widening on a PENDING "
              "task that has already been attempted - status alone is not the "
              "test, because a task put back to pending still carries an outcome "
              "judged under its old scope: %r" % (txt[:90],),
              code == 2 and "already been attempted" in txt
              and (task_in(at_mp, "P2.3") or {}).get("description")
              != "a different job")

        # ---- (gc) the empty gate a task could not reach -----------------------
        # `/audit:phase retarget` took `--gate-clear` in the release that gave
        # `scope` its `--gate`, and `scope` did not take the clear - so a phase
        # could say "nothing here can prove this" and a task could not. THE
        # REASON DIFFERS FROM `retarget`'s, which is why the same flag needed its
        # own justification: that verb REPLACES `testGate` too, so the
        # replacement is what left the empty gate unspellable, and this one
        # REPLACES `tests.gate` outright as well. The gap here is in the
        # values - no `--gate` VALUE says "none". Measured live: a phase
        # retargeted to `testGate: []`
        # left its pending tasks holding the `["lint"]` inherited at creation,
        # and the only routes to the phase's own new state were a rescope mid-run
        # or the hand edit `commands/task.md` forbids.
        gcm = base_manifest()
        # THE FIXTURE VALUES ARE THE CASE, here and in the (jf) group below. A
        # gate and an add list that are both non-empty AND different from what
        # these calls write are what tells three implementations apart: the
        # literal `None` the rows used to carry, a `from` read back AFTER the
        # write (which equals `to`), and the true prior value.
        gcm["phases"][1]["tasks"][1]["tests"] = {
            "mode": "gate-only", "expectRedFirst": False,
            "add": ["the case the import came with"], "gate": ["lint"]}
        gc_proj, gc_mp = mk("gc-gate", gcm)

        def gc_gate():
            return ((task_in(gc_mp, "P2.3") or {}).get("tests") or {}).get("gate")

        code, txt = run(["scope", "P2.3", "--gate", "pytest -q", "--gate-clear",
                         "--project-dir", gc_proj])
        check("gc1 --gate with --gate-clear is refused and the gate is untouched "
              "- two answers about one field, and guessing which was meant is how "
              "a task ends up gated on a command nobody asked for: %r"
              % ((code, gc_gate()),),
              code == 2 and "opposite things" in txt and gc_gate() == ["lint"])
        code, txt = run(["scope", "P2.3", "--project-dir", gc_proj])
        check("gc2 ...and the refusal for a call with no flags NAMES "
              "--gate-clear among what scope takes - the flag is only worth "
              "having if it is reachable, and a caller told \"needs --files\" "
              "learns nothing about it: %r" % (txt[:120],),
              code == 2 and "--gate-clear" in txt)
        # THE PAIRED NEGATIVE for gc1. A guard that refused on EITHER flag rather
        # than on both would make the ordinary call unusable, and no case above
        # would notice, because both of them pass the pair.
        code, txt = run(["scope", "P2.3", "--gate", "pytest -q",
                         "--project-dir", gc_proj])
        check("gc3 --gate alone still replaces the gate and says nothing about an "
              "empty one - the refusal is about the PAIR, not about either flag: "
              "%r" % ((code, gc_gate()),),
              code == 0 and gc_gate() == ["pytest -q"] and "now EMPTY" not in txt)
        code, txt = run(["scope", "P2.3", "--gate-clear",
                         "--project-dir", gc_proj])
        check("gc4 --gate-clear alone reaches the EMPTY gate - the state a phase "
              "could reach and a task could not - and the report SAYS what it "
              "means, because silence over a designed state reads as breakage: %r"
              % ((gc_gate(), txt[-100:]),),
              code == 0 and gc_gate() == [] and "now EMPTY" in txt)
        with open(gc_mp, "rb") as _fh:
            _gc_before = _fh.read()
        code, txt = run(["scope", "P2.3", "--gate-clear",
                         "--project-dir", gc_proj])
        with open(gc_mp, "rb") as _fh:
            _gc_after = _fh.read()
        check("gc5 clearing an already-empty gate writes nothing and says so - "
              "byte identity is the assertion rather than the exit code, because "
              "a writer that recorded the row anyway would journal a change from "
              "[] to []: %r" % (txt[:80],),
              code == 0 and "already reads that way" in txt
              and _gc_after == _gc_before)
        # THE SECOND DIRECTION for gc4's line: it reports a CHANGE, not a state,
        # so a scope that does not touch the gate must not announce it. A note
        # printed off the state alone would fire on every call after the clear.
        code, txt = run(["scope", "P2.3", "--files", "src/gc.ts",
                         "--project-dir", gc_proj])
        check("gc6 ...and a scope that leaves the gate alone does not announce "
              "the empty one, however empty it is: %r" % (txt[:100],),
              code == 0 and "now EMPTY" not in txt)
        code, txt = run(["scope", "P2.3", "--gate", "",
                         "--project-dir", gc_proj])
        check("gc7 `--gate \"\"` writes a gate holding an empty COMMAND, not the "
              "absence of one - the fixture that says why the clear had to be a "
              "flag rather than a value of the flag it clears: %r" % (gc_gate(),),
              code == 0 and gc_gate() == [""])

        # ---- (jf) what the trail says the prior state was ---------------------
        # `_locked_scope` builds the journal's `changes` list. Three fields read
        # the value they replace; `tests.add` and `tests.gate` wrote a literal
        # `None`. Measured live: a row said the gate went from nothing to a
        # command when it went from `["lint"]`. The chain verifies, the row is
        # genuine, and it is wrong about the prior state - so the surface built to
        # answer "what was this gated on before, and who changed it" gave a
        # false answer: the write is auditable end to end, but what it
        # attests is not true.
        jfm = base_manifest()
        # Both entries carry the documented `<path>: <what it asserts>` shape -
        # the union carries the PATH and not the sentence, so a fixture whose
        # entries name no file would leave `files` unmoved and take the row
        # this group is about out of the journal.
        jfm["phases"][1]["tasks"][1]["tests"] = {
            "mode": "gate-only", "expectRedFirst": False,
            "add": ["tests/import.test.ts: the case the import came with"],
            "gate": ["lint"]}
        jf_proj, jf_mp = mk("jf-from", jfm)
        code, txt = run(["scope", "P2.3", "--gate", "pytest -q",
                         "--tests-add",
                         "tests/fix.test.ts: the case the fix owes",
                         "--project-dir", jf_proj])
        jfmod = _panel_write._journalmod()
        jf_rows = [r for r in (jfmod.read_all(jf_proj) if jfmod else [])
                   if r.get("action") == "task.scope"]
        jf_changes = ((jf_rows[0].get("details") or {}).get("changes")
                      if jf_rows else [])
        jf_from = dict((r.get("field"), r.get("from")) for r in jf_changes)

        def jf_val(raw):
            """One stored `from`/`to`, DECODED rather than compared as text.
            `_journal_io._clip` spells a structured value canonically, so the row
            holds JSON text and restating that spelling here would pin the
            journal's separators instead of the claim. The literal this fault
            wrote was a bare `None`, which is not text at all - hence the
            TypeError arm rather than a `json.loads` on faith."""
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return raw

        check("jf1 the journaled row's `from` for tests.gate decodes to what the "
              "manifest HELD - this field IS the answer a reader gets when they "
              "ask what the task was gated on before, so a literal there is a "
              "false answer from the surface built to give the true one: %r"
              % (jf_from,),
              code == 0 and len(jf_rows) == 1
              and jf_val(jf_from.get("tests.gate")) == ["lint"])
        check("jf2 ...and tests.add likewise, read off the row ON DISK rather "
              "than the --json echo, because the trail is what the fault was "
              "about: %r" % (jf_changes,),
              jf_val(jf_from.get("tests.add"))
              == ["tests/import.test.ts: the case the import came with"])
        check("jf3 no row in the trail has `from` equal to `to` - the OTHER wrong "
              "fix is to read the field inside the branch, which reads back the "
              "value just written; asserted over every row, so a third field "
              "acquiring the shape is caught here rather than in a later live "
              "run: %r" % (jf_changes,),
              jf_changes != []
              and [r for r in jf_changes if r.get("from") == r.get("to")] == [])
        # THE PAIRED NEGATIVE for jf3, which is vacuously true over no rows at
        # all: the comparison this fix adds could suppress every row instead of
        # only the unchanged ones.
        check("jf4 ...and every field the call moved IS in it, counted rather "
              "than found. `files` joins the pair because `tests.add` is unioned "
              "into it: a case the task creates is a file it owns, and a "
              "scope that named one without the other was the shape that cost a "
              "real run 13 hand-fixes: %r" % (sorted(jf_from),),
              sorted(jf_from)
              == ["files", "tests.add", "tests.gate", "tests.gateBasis"])
        os.makedirs(os.path.join(jf_proj, "src"), exist_ok=True)
        for _jff in ("d.ts", "e.ts"):
            with open(os.path.join(jf_proj, "src", _jff), "w") as _fh:
                _fh.write("x\n")
        code, txt = run(["scope", "P2.3", "--files", "src/d.ts",
                         "--project-dir", jf_proj])
        # The invariant asserted on its own rather than as a side effect of
        # jf4's row count: `files` must contain everything `tests.add` names, from
        # whichever writer touched the task last.
        _jf_node = [t for p in _mio.load_manifest(jf_mp).get("phases") or []
                    for t in (p.get("tasks") or []) if t.get("id") == "P2.3"]
        # The claim here: `files` carries the PATH each entry names, not the
        # entry. Asked through the same parser the writer
        # uses, because a second reading of "which path did that entry name"
        # here would be the second opinion the parse exists to prevent - and an
        # entry naming none contributes none, which is `tp1`.
        _jf_named = [M._rules.tests_add_path(a)
                     for a in ((_jf_node[0].get("tests") or {}).get("add") or [])
                     ] if _jf_node else []
        check("jf4b files contains the path every tests.add entry NAMES, after a "
              "scope that moved tests.add - a task that names a file there "
              "creates it, so a scope that excludes it fails the task's own "
              "commit",
              _jf_node and _jf_named != [] and all(_jf_named)
              and all(p in (_jf_node[0].get("files") or [])
                      for p in _jf_named),
              repr((_jf_node[0].get("files"), _jf_named) if _jf_node else None))
        check("jf5 a scope that only ADDS files says so instead of claiming a "
              "release - the line names the direction the derivation actually "
              "went: %r" % (txt[:140],),
              code == 0 and "now claimed by this task: src/d.ts" in txt
              and "released by this task" not in txt)
        code, txt = run(["scope", "P2.3", "--tests-mode", "regression",
                         "--project-dir", jf_proj])
        check("jf6 ...and a call that never passed --files prints no fileIndex "
              "line at all: unconditional, it told the reader that files this "
              "task no longer claims had been released when the list had not "
              "moved: %r" % (txt[:140],),
              code == 0 and "fileIndex re-derived" not in txt)
        code, txt = run(["scope", "P2.3", "--files", "src/e.ts",
                         "--project-dir", jf_proj])
        _jf_idx = (_mio.load_manifest(jf_mp).get("fileIndex") or {})
        check("jf7 ...and a real release NAMES the path let go, which is the "
              "claim the old line made on every call, with the index agreeing: "
              "%r" % ((txt[:140], _jf_idx),),
              code == 0 and "released by this task: src/d.ts" in txt
              and "src/d.ts" not in _jf_idx
              and _jf_idx.get("src/e.ts") == ["P2.3"])

        # ---- (ag) the empty gate at CREATION ----------------------------------
        # The same shape as the gc group's, one verb over. `--gate-clear` is
        # defined GLOBALLY on the parser, so argparse accepted
        # `add --gate-clear`, `_build_task` never
        # read it, and the new task inherited the phase's `testGate`. A flag
        # accepted and ignored tells the operator the call succeeded while the
        # value they asked for is not there - and creation is where the COPY of the
        # phase gate is made, so it is the one place a task could not be GIVEN the
        # empty gate rather than rescoped into it a moment later.
        agm = base_manifest()
        # A real `tests` block on the pending task, so ag8's `scope --gate-clear`
        # has a gate to empty rather than a `tests` object to invent.
        agm["phases"][1]["tasks"][1]["tests"] = {
            "mode": "gate-only", "expectRedFirst": False,
            "add": [], "gate": ["test"]}
        ag_proj, ag_mp = mk("ag-add-gate", agm)
        code, txt = run(["add", "Markdown only", "--phase", "P2", "--gate-clear",
                         "--project-dir", ag_proj])
        ag_state_txt = txt
        _ag = task_in(ag_mp, "P2.4") or {}
        check("ag1 `add --gate-clear` writes the EMPTY gate instead of the phase's "
              "testGate - the fixture phase is gated on `test`, so inheriting and "
              "clearing produce DIFFERENT values and a flag that is read cannot "
              "pass as a flag that is ignored: %r"
              % ((code, (_ag.get("tests") or {}).get("gate")),),
              code == 0 and (_ag.get("tests") or {}).get("gate") == [])
        check("ag2 ...and the report SAYS the gate is empty, because a designed "
              "state met in silence reads as breakage - `scope` and `retarget` "
              "both say it and this was the third write site: %r" % (txt[:200],),
              "the gate is EMPTY" in txt
              and "phase's testGate at sign-off" in txt)
        # THE PAIRED NEGATIVE for ag1, and it is the one that fails if the fix
        # became unconditional: a gate resolved to `[]` for every add would satisfy
        # ag1 forever while deleting the inheritance the template is built on.
        code, txt = run(["add", "Ordinary work", "--phase", "P2",
                         "--project-dir", ag_proj])
        _agi = task_in(ag_mp, "P2.5") or {}
        check("ag3 SECOND-DIRECTION CASE: an add with NO gate flag still inherits "
              "the phase's testGate, and says nothing about an empty gate - the "
              "wrong fix is a clear that fires on every add: %r"
              % ((_agi.get("tests") or {}).get("gate"),),
              code == 0 and (_agi.get("tests") or {}).get("gate") == ["test"]
              and "the gate is EMPTY" not in txt)
        code, txt = run(["add", "Explicit gate", "--phase", "P2",
                         "--gate", "pytest -q", "--project-dir", ag_proj])
        _agg = task_in(ag_mp, "P2.6") or {}
        # NOT about the branch ORDER, which was this case's first claim and was
        # untestable: `_gate_contradiction` refuses the pair, so `--gate` and
        # `--gate-clear` can never both be set and no ordering of the two arms is
        # reachable. Reordering them left the whole suite green, which is what the
        # mutation said and reading did not. What it pins is that the VALUE arm
        # still exists at all - remove it and a named gate silently becomes the
        # phase's.
        check("ag4 an explicit --gate still wins over the phase's testGate - the "
              "new arm was added beside it, and a caller who names a gate must "
              "not get the inherited one: %r"
              % ((_agg.get("tests") or {}).get("gate"),),
              code == 0 and (_agg.get("tests") or {}).get("gate") == ["pytest -q"])
        with open(ag_mp, "rb") as _fh:
            _ag_before = _fh.read()
        code, ag_add_txt = run(["add", "Contradiction", "--phase", "P2",
                                "--gate", "pytest -q", "--gate-clear",
                                "--project-dir", ag_proj])
        with open(ag_mp, "rb") as _fh:
            _ag_after = _fh.read()
        check("ag5 --gate with --gate-clear is refused on `add` too, and NO id was "
              "minted - byte identity is the assertion rather than the exit code, "
              "because an allocated id is history even when the write is refused: "
              "%r" % (ag_add_txt[:80],),
              code == 2 and "opposite things" in ag_add_txt
              and _ag_after == _ag_before)
        code, ag_scope_txt = run(["scope", "P2.3", "--gate", "x", "--gate-clear",
                                  "--project-dir", ag_proj])
        code, ag_rt_txt = run(["retarget", "P3", "--gate", "x", "--gate-clear",
                               "--project-dir", ag_proj])
        check("ag6 ...and the three verbs print the SAME refusal, compared as text "
              "from three live runs rather than trusted: it is one rule about one "
              "field, `add` needed the third copy, and three copies is how one of "
              "them stops matching the others: %r"
              % (sorted(set([ag_add_txt, ag_scope_txt, ag_rt_txt])),),
              ag_add_txt != "" and ag_add_txt == ag_scope_txt == ag_rt_txt)
        code, txt = run(["add", "Into an ungated phase", "--phase", "P3",
                         "--project-dir", ag_proj])
        _agp = task_in(ag_mp, "P3.1") or {}
        check("ag7 the line is printed off the STATE, so a task inheriting an "
              "already-empty phase gate says it too - a creation has no prior "
              "value to have moved from, and a reader cares which state the task "
              "is in rather than which route reached it: %r"
              % ((_agp.get("tests") or {}).get("gate"),),
              code == 0 and (_agp.get("tests") or {}).get("gate") == []
              and "the gate is EMPTY" in txt)
        code, ag_moved_txt = run(["scope", "P2.3", "--gate-clear",
                                  "--project-dir", ag_proj])

        def ag_gate_note(text):
            """The EMPTY line with the tense removed - what the two verbs share."""
            for line in text.splitlines():
                if "EMPTY" in line:
                    return line.replace("is now EMPTY", "is EMPTY")
            return ""

        check("ag8 ...and the EXPLANATION after the marker is the same in both "
              "verbs, compared across two live runs with the tense masked - the "
              "tense is the only thing that differs (`add` reports a state, "
              "`scope` a change) and what an empty task gate MEANS is one fact: "
              "%r" % ((ag_gate_note(ag_state_txt),
                       ag_gate_note(ag_moved_txt)),),
              code == 0 and ag_gate_note(ag_state_txt) != ""
              and ag_gate_note(ag_state_txt) == ag_gate_note(ag_moved_txt))

        # ---- (fn) a row for a change that did not happen -----------------------
        # The same class as the jf group's, one field over and not named by
        # that entry: the `files` row went in under a bare `if files:`, so
        # re-scoping to the list the task already held printed and journaled
        # `files: [...] -> [...]`. Milder than that one (the `from` is true,
        # so nobody is misled about the prior state) and still a
        # hash-chained row attesting a change that never occurred, which is
        # exactly what a reader counting "who changed this task's scope, and
        # when" counts. The three sibling fields already compared.
        fnm = base_manifest()
        # A real `tests` block, because a `--files`-only scope over a task that has
        # none writes `tests: {}` and the validator refuses that - a different
        # question from the one this group asks.
        fnm["phases"][1]["tasks"][1]["tests"] = {
            "mode": "gate-only", "expectRedFirst": False,
            "add": [], "gate": ["test"]}
        fn_proj, fn_mp = mk("fn-noop", fnm)
        os.makedirs(os.path.join(fn_proj, "src"), exist_ok=True)
        for _fnf in ("f.ts", "g.ts"):
            with open(os.path.join(fn_proj, "src", _fnf), "w") as _fh:
                _fh.write("x\n")
        fnmod = _panel_write._journalmod()

        def fn_rows():
            """Every `task.scope` row in the trail - COUNTED, because the fault was
            a row existing rather than a value being wrong."""
            return [r for r in (fnmod.read_all(fn_proj) if fnmod else [])
                    if r.get("action") == "task.scope"]

        code, txt = run(["scope", "P2.3", "--files", "src/f.ts",
                         "--project-dir", fn_proj])
        _fn_scoped = len(fn_rows())
        with open(fn_mp, "rb") as _fh:
            _fn_before = _fh.read()
        code, txt = run(["scope", "P2.3", "--files", "src/f.ts",
                         "--project-dir", fn_proj])
        with open(fn_mp, "rb") as _fh:
            _fn_after = _fh.read()
        check("fn1 re-scoping to the list the task ALREADY holds journals no row "
              "and writes no byte - the trail is the assertion, because the fault "
              "was a verifying, genuine row attesting a change that never "
              "happened: %r" % ((code, len(fn_rows()), txt[:70]),),
              code == 0 and len(fn_rows()) == _fn_scoped
              and _fn_after == _fn_before
              and "already reads that way" in txt)
        # THE PAIRED NEGATIVE. The comparison could have been written to drop the
        # files row ALTOGETHER, which fn1 cannot tell from the fix.
        code, txt = run(["scope", "P2.3", "--files", "src/g.ts",
                         "--project-dir", fn_proj])
        _fn_moved = [r for r in fn_rows()
                     if any(c.get("field") == "files"
                            for c in ((r.get("details") or {}).get("changes") or []))]
        check("fn2 SECOND-DIRECTION CASE: a files list that REALLY moved still "
              "journals its row, carrying the list it replaced - the wrong fix is "
              "to stop recording `files` at all, which fn1 alone would call green: "
              "%r" % (len(_fn_moved),),
              code == 0 and len(_fn_moved) == 2)
        # THE SHARPEST ONE: `files` unchanged while another field moves. A fix that
        # returned early on an unchanged files list would lose the other field.
        code, txt = run(["scope", "P2.3", "--files", "src/g.ts",
                         "--tests-mode", "tdd", "--project-dir", fn_proj])
        _fn_last = ((fn_rows()[-1].get("details") or {}).get("changes")
                    if fn_rows() else [])
        check("fn3 an unchanged --files alongside a field that DID move writes the "
              "mover and only the mover - the fields are compared one at a time, "
              "not the call skipped: %r"
              % (sorted(c.get("field") for c in _fn_last),),
              code == 0 and sorted(c.get("field") for c in _fn_last)
              == ["tests.mode"])
        check("fn4 ...and the task really did take that field, so the row is not "
              "the only evidence: %r"
              % ((task_in(fn_mp, "P2.3") or {}).get("tests"),),
              ((task_in(fn_mp, "P2.3") or {}).get("tests") or {}).get("mode")
              == "tdd")

        # ---- (sf) the three fields `scope` did not reach -----------------------
        # `_build_task` initializes eleven fields. `scope` reached five, the panel's
        # composition card reaches `model` and `skills`, and `risk`, `blockedBy` and
        # `dependsOn` were reachable by NOTHING once set. Measured live: a task filed
        # `--depends-on P0.3,P0.4` against tasks parked behind an environment nobody
        # had created, where shipping its describable half meant removing one id -
        # and the only route was `cancel` plus a fresh `add`, losing the id, the
        # journal continuity and the description somebody wrote.
        sfm = base_manifest()
        # THE FIXTURE VALUES ARE THE CASE. `risk` and `model` are spelled out rather
        # than left absent, because `low`/`sonnet` is what the model note has to be
        # able to compare against - a task with no model at all cannot tell "stayed
        # where it was" from "was never set".
        sfm["phases"][1]["tasks"][1].update({
            "description": "imported", "files": [],
            "tests": {"mode": "gate-only", "expectRedFirst": False,
                      "add": [], "gate": ["test"]},
            "model": "sonnet", "skills": [], "risk": "low",
            "blockedBy": [], "dependsOn": ["P2.2"], "attempts": 0})
        # A PENDING sibling to wait on: the validator resolves `dependsOn` against
        # TASKS, so a phase id there is a finding rather than a dependency.
        sfm["phases"][1]["tasks"].insert(1, {"id": "P2.2", "title": "blocker",
                                             "status": "pending"})
        sf_proj, sf_mp = mk("sf-fields", sfm)
        code, txt = run(["scope", "P2.3", "--project-dir", sf_proj])
        check("sf1 the refusal for a call with no flags NAMES all three - a field "
              "reachable only by reading the source is the fault this closes, so "
              "the message a caller actually meets has to carry them: %r"
              % (txt[:200],),
              code == 2 and "--risk" in txt and "--blocked-by" in txt
              and "--depends-on" in txt)
        code, txt = run(["scope", "P2.3", "--risk", "high",
                         "--project-dir", sf_proj])
        _sft = task_in(sf_mp, "P2.3") or {}
        check("sf2 --risk moves the field that feeds the executor's model floor "
              "and the commit confirmation - the one field here where being wrong "
              "has a consequence at RUN time, and it is judged before the work was "
              "looked at: %r" % ((code, _sft.get("risk")),),
              code == 0 and _sft.get("risk") == "high")
        check("sf3 ...and the model is NOT re-derived, with the report saying so "
              "and naming what creation WOULD have derived - silence would let an "
              "operator who raised risk believe the executor was escalated with "
              "it, and rewriting `model` here would overrule /audit:panel: %r"
              % (txt[-190:],),
              _sft.get("model") == "sonnet"
              and "the model stays sonnet" in txt and "would derive opus" in txt)
        # THE SECOND DIRECTION for sf3: the note is printed off a DISAGREEMENT, so a
        # risk change whose implied model is already on the task must stay silent. A
        # note printed on every risk change would satisfy sf3 forever.
        code, txt = run(["scope", "P2.3", "--risk", "med",
                         "--project-dir", sf_proj])
        check("sf4 SECOND-DIRECTION CASE: a risk change whose derived model is the "
              "one the task already carries says nothing about the model at all: "
              "%r" % (txt[:120],),
              code == 0 and "the model stays" not in txt)
        code, txt = run(["scope", "P2.3", "--risk", "med",
                         "--project-dir", sf_proj])
        check("sf5 re-passing the risk the task already holds writes nothing and "
              "says so - the fn group's no-op comparison, extended to this field, "
              "so the fix did not arrive carrying the bug it was fixing: %r" % (txt[:70],),
              code == 0 and "already reads that way" in txt)
        code, txt = run(["scope", "P2.3", "--depends-on", "",
                         "--project-dir", sf_proj])
        _sft = task_in(sf_mp, "P2.3") or {}
        check("sf6 an EMPTY --depends-on empties the field - the spelling that "
              "makes a `--depends-on-clear` unnecessary, because a comma list of "
              "IDS has no value that reads as content the way `--gate \"\"` "
              "reads as an empty COMMAND: %r"
              % ((code, _sft.get("dependsOn")),),
              code == 0 and _sft.get("dependsOn") == [])
        check("sf7 ...and the call reports that the task can run NOW, which is the "
              "question a caller removing a blocking id is asking: %r"
              % (txt[-70:],),
              "ready now -- /audit:run P2.3" in txt)
        code, txt = run(["scope", "P2.3", "--depends-on", "P2.2",
                         "--project-dir", sf_proj])
        _sfrows = [r for r in (fnmod.read_all(sf_proj) if fnmod else [])
                   if r.get("action") == "task.scope"]
        _sffrom = dict((c.get("field"), c.get("from"))
                       for c in ((_sfrows[-1].get("details") or {}).get("changes")
                                 if _sfrows else []))
        # `jf_val` (the jf group's decoder) rather than a bare `json.loads`: the
        # stored `from` is canonical JSON TEXT, and a mutation that stops writing
        # the row leaves `None` there - which must fail this case, not kill the
        # body before the cases below it run.
        check("sf8 --depends-on replaces the list and the row carries the list it "
              "replaced, decoded rather than compared as text - the trail's `from` "
              "is what the jf group's fix was about and a new field must not arrive with a "
              "literal in it: %r" % (_sffrom,),
              code == 0 and jf_val(_sffrom.get("dependsOn")) == []
              and "waiting on: P2.2" in txt)
        code, txt = run(["scope", "P2.3", "--blocked-by", "P2.1",
                         "--project-dir", sf_proj])
        _sft = task_in(sf_mp, "P2.3") or {}
        check("sf9 --blocked-by lands the same way through the same loop - the two "
              "ref lists are one field twice over, and two blocks of it is how the "
              "pair comes to disagree about what an empty value means: %r"
              % (_sft.get("blockedBy"),),
              code == 0 and _sft.get("blockedBy") == ["P2.1"])
        with open(sf_mp, "rb") as _fh:
            _sf_before = _fh.read()
        code, txt = run(["scope", "P2.3", "--blocked-by", "NOPE.9",
                         "--project-dir", sf_proj])
        with open(sf_mp, "rb") as _fh:
            _sf_after = _fh.read()
        check("sf10 a ref that resolves to nothing is refused by the VALIDATOR and "
              "every written file rolled back - the guard is the revalidate this "
              "verb already ran, not a second copy of ref resolution here: %r"
              % ((code, txt[-90:]),),
              code == M.E_INVALID and _sf_after == _sf_before
              and "does not resolve" in txt)
        # THE SECOND DIRECTION for sf7: readiness is printed only when a REF field
        # moved, so a call that touched neither must not claim anything about it. A
        # line printed off the state alone would fire on every scope.
        code, txt = run(["scope", "P2.3", "--tests-mode", "regression",
                         "--project-dir", sf_proj])
        check("sf11 SECOND-DIRECTION CASE: a scope that moved neither ref field "
              "prints no readiness line - it is an answer about the two fields "
              "this call did not look at: %r" % (txt[:120],),
              code == 0 and "ready now" not in txt and "waiting on" not in txt)
        code, txt = run(["scope", "P2.3", "--risk", "low", "--json",
                         "--project-dir", sf_proj])
        try:
            _sfj = json.loads(txt)
        except ValueError:
            # A MUTATION MUST MAKE THE CASE FAIL, NOT THE SUITE RAISE. A refused
            # call prints a sentence rather than a JSON block, and letting that
            # reach `json.loads` bare stopped the body dead - every case after
            # this point then reported nothing at all, which is the failure mode
            # that looks like coverage. Found by mutating, not by reading.
            _sfj = {}
        check("sf12 --json carries the readiness even on a call the human report "
              "stays quiet about - this one moved only `risk`, so the report says "
              "nothing about the ref fields while the machine surface, which does "
              "not read, keeps the answer: %r"
              % ((_sfj.get("ready"), _sfj.get("waitingOn")),),
              _sfj.get("ready") is False and _sfj.get("waitingOn") == ["P2.2"]
              and [r["field"] for r in _sfj.get("changes") or []] == ["risk"])
        # THE GUARD IS PER-CHANGE NOW, AND THIS COMMENT USED TO SAY THE OPPOSITE.
        # It read "THE PENDING GUARD IS THE WHOLE CALL, not a per-field rule" -
        # now a started task takes a WIDENING of `files` or `tests.add`,
        # because that is the one change `_invariants.commit_scope` cannot
        # re-judge an already-recorded commit over. What is unchanged is
        # this case's own claim - `risk` REPLACES a value the attempt ran
        # under, so the same attempted-task rule still covers it exactly as
        # it covers the other two fields this group added, and the sentence
        # the caller meets is still the same one.
        sfa_proj, sfa_mp = mk("sf-attempted", sfm)
        _sfa = _mio.load_manifest(sfa_mp)
        _sfa["phases"][1]["tasks"][2]["attempts"] = 2
        _panel_write._atomic_write_json(sfa_mp, _sfa)
        code, txt = run(["scope", "P2.3", "--risk", "high",
                         "--project-dir", sfa_proj])
        check("sf13 the never-attempted guard covers the new fields too - the "
              "reason it exists (an outcome judged under the old scope) is the "
              "same reason for risk and the ref lists: %r" % (txt[:90],),
              code == 2 and "already been attempted" in txt)
        # ONE SENTENCE, TWO VERBS. The `/audit:run` handoff is a spelling a reader
        # COPIES, and comparing it across two live runs is what goes red if either
        # call site re-spells it.
        code, sf_add_txt = run(["add", "Ready at birth", "--phase", "P2",
                                "--project-dir", sf_proj])

        def sf_handoff(text, tid):
            for line in text.splitlines():
                if "/audit:run" in line:
                    return line.replace(tid, "<id>")
            return ""

        code, sf_scope_txt = run(["scope", "P2.3", "--depends-on", "",
                                  "--project-dir", sf_proj])
        check("sf14 the readiness sentence `scope` prints is the one `add` prints, "
              "compared across two live runs with the id masked - one home for a "
              "handoff a reader copies: %r"
              % ((sf_handoff(sf_add_txt, "P2.4"),
                  sf_handoff(sf_scope_txt, "P2.3")),),
              sf_handoff(sf_add_txt, "P2.4") != ""
              and sf_handoff(sf_add_txt, "P2.4")
              == sf_handoff(sf_scope_txt, "P2.3"))

        # ---- (wd) `scope` refused the case it exists for -----------------------
        # `reference/orchestrator.md` prescribes `/audit:task scope` for the
        # moment the plan gate refuses a file a RUNNING task genuinely needs -
        # and a task in that moment is `in_progress` with an attempt on it, the
        # two states the pending-and-never-attempted guard excluded. So the
        # documented remedy was unreachable in exactly its own scenario.
        # Measured live: hit three times in one phase, and the only escape each
        # time was hand-editing the shard and the index under the lock, which is
        # the operation this verb exists to replace.
        #
        # THESE CASES TEST THE DIRECTION, NOT THE FIELD, because direction is
        # what the permission is about. `_invariants.commit_scope` grades a
        # RECORDED commit against the task's CURRENT `files`, so growing that
        # list can only turn a breach into a pass; shrinking it can turn a commit
        # that was clean when it was made into a breach, which is a verdict
        # changed after the fact on work nobody can go back and redo.
        wdm = base_manifest()
        # The state orchestrator step 2 leaves a task in: `in_progress` AND
        # `attempts` incremented, in one step. Both signals are set here on
        # purpose - wd9 is the fixture that separates them.
        wdm["phases"][1]["tasks"][1].update({
            "status": "in_progress", "attempts": 1, "maxAttempts": 3,
            "description": "the running task", "risk": "low", "model": "sonnet",
            "skills": [], "blockedBy": [], "dependsOn": [],
            "files": ["src/known.ts", "src/known.test.ts"],
            "tests": {"mode": "tdd", "expectRedFirst": True,
                      "add": ["src/known.test.ts"], "gate": ["test"]}})
        wdm["fileIndex"]["src/known.ts"] = ["P2.3"]
        wdm["fileIndex"]["src/known.test.ts"] = ["P2.3"]
        wd_proj, wd_mp = mk("wd-widen", wdm)
        os.makedirs(os.path.join(wd_proj, "src"), exist_ok=True)
        for _wdf in ("known.ts", "known.test.ts", "needed.ts", "extra.ts"):
            with open(os.path.join(wd_proj, "src", _wdf), "w") as _fh:
                _fh.write("x\n")
        code, txt = run(["scope", "P2.3", "--files",
                         "src/known.ts,src/known.test.ts,src/needed.ts",
                         "--project-dir", wd_proj])
        _wdt = task_in(wd_mp, "P2.3") or {}
        _wdi = (_mio.load_manifest(wd_mp).get("fileIndex") or {})
        check("wd1 an in_progress task WITH an attempt on it takes a widening of "
              "`files`, and the fileIndex the plan gate reads gains the path - "
              "which is the whole errand, since the gate is what refused the "
              "file in the first place: %r"
              % ((code, _wdt.get("files"), _wdi.get("src/needed.ts")),),
              code == 0
              and _wdt.get("files") == ["src/known.ts", "src/known.test.ts",
                                        "src/needed.ts"]
              and _wdi.get("src/needed.ts") == ["P2.3"])
        check("wd2 ...and the report DATES it: which attempt the scope grew "
              "during, and what it gained. A widening that read like an ordinary "
              "scope would leave every record already carrying this task's id to "
              "be read as though the list had always been this one: %r"
              % (txt[-260:],),
              "WIDENED during attempt 1, while the task is in_progress" in txt
              and "files +src/needed.ts" in txt)
        code, txt = run(["scope", "P2.3", "--files",
                         "src/known.ts,src/known.test.ts,src/needed.ts,"
                         "src/extra.ts", "--json", "--project-dir", wd_proj])
        try:
            _wdj = json.loads(txt)
        except ValueError:
            # sf12's lesson: a refused call prints a sentence, and letting that
            # reach `json.loads` bare stops the body dead instead of failing one
            # case.
            _wdj = {}
        check("wd3 --json carries the same two facts as data, and `attempt` is "
              "the number rather than a flag - a machine surface must not be the "
              "one place `recorded_attempt`'s three answers collapse into two: %r"
              % ((_wdj.get("widened"), _wdj.get("attempt")),),
              _wdj.get("widened") is True and _wdj.get("attempt") == 1)
        with open(wd_mp, "rb") as _fh:
            _wd_before = _fh.read()
        code, txt = run(["scope", "P2.3", "--files", "src/needed.ts",
                         "--project-dir", wd_proj])
        with open(wd_mp, "rb") as _fh:
            _wd_after = _fh.read()
        check("wd4 SECOND-DIRECTION CASE: a NARROWING of that same field on that "
              "same task is still refused and writes no byte - append-only is "
              "the whole permission, and a guard reading 'files was passed' "
              "rather than 'files only grew' would let a commit that was clean "
              "when it was made become a breach: %r" % (txt[:230],),
              code == 2 and _wd_after == _wd_before
              and "`files` would drop src/known.ts, src/extra.ts" in txt)
        code, txt = run(["scope", "P2.3", "--risk", "high",
                         "--project-dir", wd_proj])
        check("wd5 ...and a field with no safe direction is refused whichever way "
              "it moves, naming the field and the move rather than only the task: "
              "`risk` REPLACES a value the attempt ran under, so the same "
              "attempted-task sentence is still the one the caller meets: %r" % (txt[:240],),
              code == 2 and "already been attempted (1)" in txt
              and '`risk` would move from "low" to "high"' in txt)
        code, txt = run(["scope", "P2.3", "--tests-add", "src/known.test.ts",
                         "--tests-add", "src/needed.test.ts",
                         "--project-dir", wd_proj])
        _wdt = task_in(wd_mp, "P2.3") or {}
        check("wd6 `tests.add` widens on the same terms, and the case it names "
              "lands in `files` with it - a task that CREATES a test file "
              "owns it, so a widening naming one without the other hands back a "
              "scope the task's own commit fails: %r"
              % ((code, (_wdt.get("tests") or {}).get("add")),),
              code == 0
              and (_wdt.get("tests") or {}).get("add") == ["src/known.test.ts",
                                                           "src/needed.test.ts"]
              and "src/needed.test.ts" in (_wdt.get("files") or []))
        code, txt = run(["scope", "P2.3", "--tests-add", "src/needed.test.ts",
                         "--project-dir", wd_proj])
        check("wd7 SECOND-DIRECTION CASE: ...and dropping a case from "
              "`tests.add` is refused for `files`' reason - the two are one "
              "permission, so a guard that listed only `files` would leak the "
              "narrowing through the field beside it: %r" % (txt[:230],),
              code == 2
              and "`tests.add` would drop src/known.test.ts" in txt)
        _wd_rows = [r for r in (fnmod.read_all(wd_proj) if fnmod else [])
                    if r.get("action") == "task.scope"]
        _wd_last = _wd_rows[-1] if _wd_rows else {}
        check("wd8 the trail records the ATTEMPT the widening landed under, and "
              "says WIDENED in the summary `audit-journal list` prints - the "
              "`attempt` key had to join `_journal_io.DETAILS_KEYS` for the "
              "first half, an allow-list that drops an unlisted key in silence, "
              "and a row reading like every other scope would need `details` "
              "opened for the second: %r"
              % ((_wd_last.get("summary"),
                  (_wd_last.get("details") or {}).get("attempt")),),
              (_wd_last.get("details") or {}).get("attempt") == 1
              and "WIDENED" in (_wd_last.get("summary") or "")
              and "during attempt 1" in (_wd_last.get("summary") or ""))
        wd0 = base_manifest()
        # THE TWO SIGNALS PULLED APART. A task moved to `in_progress` whose
        # attempt has not been written down yet is mid-flight with nothing to
        # count, and it is the fixture that says the refusal's basis is read
        # rather than assumed.
        wd0["phases"][1]["tasks"][1].update({
            "status": "in_progress", "attempts": 0, "risk": "low",
            "files": ["src/known.ts"],
            "tests": {"mode": "gate-only", "expectRedFirst": False,
                      "add": [], "gate": ["test"]}})
        wd0["fileIndex"]["src/known.ts"] = ["P2.3"]
        wd0_proj, wd0_mp = mk("wd-noattempt", wd0)
        code, txt = run(["scope", "P2.3", "--risk", "high",
                         "--project-dir", wd0_proj])
        check("wd9 the refusal carries the basis that is TRUE of the task in "
              "hand: one with no attempt recorded cannot be told it 'has already "
              "been attempted (0)', so the head names the status and what has "
              "been matching its edits instead: %r" % (txt[:210],),
              code == 2 and "P2.3 is in_progress" in txt
              and "already been attempted" not in txt
              and "matching its edits to that list" in txt)
        wdc = base_manifest()
        wdc["phases"][1]["tasks"][1].update({
            "status": "cancelled", "attempts": 1, "files": ["src/known.ts"]})
        wdc["fileIndex"]["src/known.ts"] = ["P2.3"]
        wdc_proj, wdc_mp = mk("wd-cancelled", wdc)
        code, txt = run(["scope", "P2.3", "--files", "src/known.ts,src/more.ts",
                         "--project-dir", wdc_proj])
        check("wd10 a CANCELLED task is refused outright, widening and all - and "
              "the split between the two statuses is exactly here: `done` "
              "takes a widening because there is an index to settle, "
              "`cancelled` does not because nothing "
              "will ever be committed against it. A guard written around either "
              "word alone gets one of the two wrong: %r" % (txt[:140],),
              code == 2 and "is cancelled" in txt
              and "its scope cannot grow" in txt
              and "no pairing here to settle" in txt
              and (task_in(wdc_mp, "P2.3") or {}).get("files")
              == ["src/known.ts"])
        wdp_proj, wdp_mp = mk("wd-pending", base_manifest())
        code, txt = run(["scope", "P2.3", "--files", "src/fresh.ts",
                         "--project-dir", wdp_proj])
        check("wd11 SECOND-DIRECTION CASE: an ordinary PENDING, never-attempted "
              "scope keeps its full freedom and says nothing about widening - a "
              "line printed off the state alone would fire on every call, and a "
              "guard that fired on every call would leave the verb narrower than "
              "it was before this entry: %r" % (txt[:160],),
              code == 0 and "WIDENED" not in txt and "append-only" not in txt)

        # THE DOCUMENT JOIN, and the half this group left open. The wd group
        # repaired the verb and the cases above pin the behaviour, but nothing
        # tied either of them to the document that PRESCRIBES this recovery --
        # so the `in_progress` arm was repaired without being named, and a gate
        # tightened back would meet no case that reads the flow it breaks.
        # `reference/execute-task.md` writes the state in its Execute step
        # (`task.status = "in_progress"` and `task.attempts += 1`, in one step,
        # BEFORE the executor is spawned) and then names the remedy for the
        # moment the plan gate refuses a file that task genuinely needs: widen
        # `task.files` through this verb and tell the RUNNING executor to carry
        # on, rather than spawning a fresh one. Released 2.2.0 wrote that state
        # and refused that remedy, so the route the document sells as the cheap
        # one was the route an operator could not take -- reported from a live
        # phase run. `## Execute the task` moved out of `reference/orchestrator.md`
        # into its own file, split off so a command that never runs a task does
        # not have to read it.
        #
        # READ OUT OF THE DOCUMENT, st5's rule: a reworded prescription, or a
        # state whose write moves, has to come past this case instead of
        # drifting away from the verb it names. READ, NOT CAUGHT -- a suite that
        # cannot open the document it is comparing must fail rather than assert
        # on an empty string.
        with open(os.path.join(_output.PLUGIN_ROOT, "reference",
                               "execute-task.md"), "r",
                  encoding="utf-8") as _fh:
            _orc_src = _fh.read()
        _orc_starts = ('task.status = "in_progress"' in _orc_src
                       and "task.attempts += 1" in _orc_src)
        _orc_widens = ("A widened scope CONTINUES the executor" in _orc_src
                       and "widen `task.files` (`/audit:task scope`)"
                       in _orc_src)
        wdd = base_manifest()
        # The state that Execute step leaves behind, and nothing more. `tests.add`
        # is EMPTY on purpose: `--files` unions the task's own cases back in,
        # so a case file sitting there would re-add itself in the narrowing
        # below and hide the drop that call exists to show.
        wdd["phases"][1]["tasks"][1].update({
            "status": "in_progress", "attempts": 1, "maxAttempts": 3,
            "description": "the executor is running", "risk": "low",
            "model": "sonnet", "skills": [], "blockedBy": [], "dependsOn": [],
            "files": ["src/documented.ts"],
            "tests": {"mode": "gate-only", "expectRedFirst": False,
                      "add": [], "gate": ["test"]}})
        wdd["fileIndex"]["src/documented.ts"] = ["P2.3"]
        wdd_proj, wdd_mp = mk("wd-documented", wdd)
        os.makedirs(os.path.join(wdd_proj, "src"), exist_ok=True)
        for _wddf in ("documented.ts", "refused.ts", "another.ts"):
            with open(os.path.join(wdd_proj, "src", _wddf), "w") as _fh:
                _fh.write("x\n")
        code, txt = run(["scope", "P2.3", "--files",
                         "src/documented.ts,src/refused.ts",
                         "--project-dir", wdd_proj])
        _wddt = task_in(wdd_mp, "P2.3") or {}
        _wddi = (_mio.load_manifest(wdd_mp).get("fileIndex") or {})
        check("wd12 THE DOCUMENTED RECOVERY, DRIVEN: `execute-task.md` sets "
              "`in_progress` and increments `attempts` before it spawns, and "
              "prescribes a widening through this verb plus a message to the "
              "RUNNING executor for the moment the plan gate refuses a file the "
              "task needs. So the state that document writes has to be a state "
              "this verb takes a widening on, and the index the gate reads has "
              "to gain the path. Released 2.2.0 wrote the state and refused the "
              "remedy, which left the route the document sells as the cheap one "
              "the one nobody could take: prescribes=%r accepts=%r"
              % ((_orc_starts, _orc_widens), (code, _wddt.get("files"))),
              _orc_starts and _orc_widens and code == 0
              and _wddt.get("files") == ["src/documented.ts", "src/refused.ts"]
              and _wddi.get("src/refused.ts") == ["P2.3"])
        with open(wdd_mp, "rb") as _fh:
            _wdd_before = _fh.read()
        code, txt = run(["scope", "P2.3", "--files",
                         "src/refused.ts,src/another.ts",
                         "--project-dir", wdd_proj])
        with open(wdd_mp, "rb") as _fh:
            _wdd_after = _fh.read()
        check("wd13 SECOND-DIRECTION CASE, on the task the document just "
              "widened: a call that GAINS a path and LOSES one is still "
              "refused, names the path it would drop, and writes no byte. That "
              "is the silent move this guard protects against -- an operator retyping "
              "the list from memory -- and it is the shape that separates a "
              "guard grading the DIRECTION of the change from one that merely "
              "notices something was added: %r" % (txt[:200],),
              code == 2 and _wdd_after == _wdd_before
              and "`files` would drop src/documented.ts" in txt
              and (task_in(wdd_mp, "P2.3") or {}).get("files")
              == ["src/documented.ts", "src/refused.ts"])

        # ---- (st) `done` settles the RECORD, not the INDEX ---------------------
        # The product prescribed a remedy and refused it in the same breath. At
        # sign-off `_invariants.manifest_revalidated` prints, as its own repair,
        # "run `/audit:task scope <id> --files ...` to re-derive the index" - and
        # sign-off runs only when every task is `done`, which this verb refused.
        # A live run spent 172,417 tokens on three fix-run subagents before that
        # surfaced. The fix widened the STARTED rule five hours earlier and left the
        # SETTLED one, so `done` was exactly the half that bites where it hurts.
        #
        # What licenses opening it was checked in the code rather than argued:
        # `_invariants.commit_scope` reads `task.files` LIVE, so growing the list
        # can only move a staged path INTO `allowed`. The pair st1/st4 is the
        # point - a guard written around "terminal" alone lets neither through,
        # and one written around "done" alone lets the wrong one through.
        stm = base_manifest()
        stm["phases"][1]["tasks"][0].update({
            "status": "done", "attempts": 1, "files": ["src/known.ts"],
            "commit": "a" * 40,
            "outcome": {"technical": "graded against src/known.ts",
                        "descriptive": None}})
        stm["fileIndex"]["src/known.ts"] = ["P2.1"]
        st_proj, st_mp = mk("st-done", stm)
        code, txt = run(["scope", "P2.1", "--files", "src/known.ts,src/late.ts",
                         "--project-dir", st_proj])
        _st_task = task_in(st_mp, "P2.1") or {}
        _st_idx = (_mio.load_manifest(st_mp).get("fileIndex") or {})
        check("st1 a DONE task takes an append-only widening, and the index is "
              "re-derived with it - which is the settlement sign-off asks for "
              "and the whole reason the refusal was split: %r" % (txt[:120],),
              code == 0
              and _st_task.get("files") == ["src/known.ts", "src/late.ts"]
              and _st_idx.get("src/late.ts") == ["P2.1"])
        check("st2 ...and the report says WHAT it settled and what it did not: a "
              "line that read like the mid-flight one would claim the plan gate "
              "now matches paths nobody is editing, and silence would let a "
              "reader take this for a record of new work: %r" % (txt[:200],),
              "already done will take it" in txt
              and "does NOT record new work" in txt
              and "Follow-up work is a new task" in txt
              and "the plan gate now matches" not in txt)
        _stmod = _panel_write._journalmod()
        _pr_rows = [r for r in (_stmod.read_all(st_proj) if _stmod else [])
                    if r.get("action") == "task.scope"]
        check("st3 ...and the row DATES it, because a settlement written into a "
              "finished task's record is exactly the thing a reader will later "
              "ask when happened: %r" % (_pr_rows[-1:],),
              len(_pr_rows) == 1
              and "WIDENED" in (_pr_rows[0].get("summary") or "")
              and "done" in (_pr_rows[0].get("summary") or "")
              and (_pr_rows[0].get("details") or {}).get("attempt") == 1)
        stn_proj, stn_mp = mk("st-done-narrow", stm)
        code, txt = run(["scope", "P2.1", "--files", "src/other.ts",
                         "--project-dir", stn_proj])
        check("st4 SECOND DIRECTION: a NARROWING on the same done task is still "
              "refused, so opening the settled rule bought a settlement and not "
              "a licence to rewrite what was graded - and the refusal names the "
              "grading, which is the one thing true of a task that is finished "
              "rather than running: %r" % (txt[:140],),
              code == 2 and "is done" in txt
              and "graded against the files it names" in txt
              and (task_in(stn_mp, "P2.1") or {}).get("files") == ["src/known.ts"])

        # THE LIVE CLAIM, and the case that would have caught the original
        # contradiction: the remedy `_invariants` PRINTS at sign-off has to be a
        # command this verb accepts. Read out of the invariant's own text rather
        # than restated here, so a reworded breach cannot drift away from the
        # verb it names.
        # READ, NOT CAUGHT. An earlier draft wrapped this in `except Exception:
        # pass`, and a missing import made it swallow a NameError and assert on
        # an empty string - the case reported PASS on nothing. A suite that
        # cannot read the file it is comparing must fail, not shrug.
        with open(os.path.join(_output.SCRIPTS_DIR, "governance",
                               "_invariants.py"), "r", encoding="utf-8") as _fh:
            _inv_src = _fh.read()
        _names_scope = "/audit:task scope" in _inv_src \
            and "re-derive the index" in _inv_src
        # ...and the verb really takes it. `st1` proved the widening lands; this
        # asserts the JOIN - that the command the invariant prints is the command
        # this verb accepts on the status the invariant will be looking at.
        sti_proj, sti_mp = mk("st-remedy", stm)
        code, txt = run(["scope", "P2.1", "--files", "src/known.ts,src/paired.ts",
                         "--project-dir", sti_proj])
        check("st5 the repair `manifest_revalidated` PRINTS at sign-off names "
              "`/audit:task scope … to re-derive the index`, and every id it can "
              "name is `done` by then - so this verb has to accept it on a done "
              "task. The two were written apart and contradicted each other in "
              "production for five weeks: prints=%r accepts=%r"
              % (_names_scope, code),
              _names_scope and code == 0
              and (_mio.load_manifest(sti_mp).get("fileIndex") or {})
              .get("src/paired.ts") == ["P2.1"])

        # ---- (fg) the gate a STARTED task could not change -------------------
        # THE COST, measured live: `tests.gate` was hand-edited inside a phase
        # shard with a Python one-liner, three separate times, because the verb
        # refused - and that hand edit is the operation this verb exists to
        # replace.
        #
        # THE REFUSAL WAS RIGHT FOR `files` AND WRONG FOR THIS FIELD, which is
        # why these cases pin the FIELD's reading direction rather than the
        # call. Everything `_narrowings` blocks is read BACKWARDS against work
        # already recorded: `_invariants.commit_scope` grades a recorded commit
        # against the CURRENT `files`, so dropping a path moves a judgement
        # already made. A gate has no backwards reading at all - `run-test-gate`
        # builds the NEXT run's steps from it, `_evidence_io.row_for` writes the
        # commands that ACTUALLY ran onto the evidence row, and
        # `_evidence_io.pointer_for` caches identity, verdict and time.
        #
        # THE FIXTURE CARRIES A GREEN POINTER ON PURPOSE. The narrower spelling
        # on offer was "a started task with no recorded green run", and this is
        # the task that spelling would refuse: a green verdict over a gate too
        # wide to be worth re-running is the one nobody re-scopes, and it is the
        # one that costs the most. The pointer is asserted UNCHANGED below, which
        # is the claim about it stated as something a case can read.
        fgm = base_manifest()
        fgm["phases"][1]["tasks"][1].update({
            "status": "in_progress", "attempts": 2, "maxAttempts": 3,
            "description": "the running task", "risk": "low", "model": "sonnet",
            "skills": [], "blockedBy": [], "dependsOn": [],
            "files": ["src/known.ts"],
            "testEvidence": {"runId": "run-opaque-1", "status": "passed",
                             "at": "2026-01-01T00:00:00Z"},
            "tests": {"mode": "tdd", "expectRedFirst": True,
                      "add": [], "gate": ["test", "typecheck"]}})
        fgm["fileIndex"]["src/known.ts"] = ["P2.3"]
        fg_proj, fg_mp = mk("fg-gate", fgm)
        os.makedirs(os.path.join(fg_proj, "src"), exist_ok=True)
        for _fgf in ("known.ts", "added.ts"):
            with open(os.path.join(fg_proj, "src", _fgf), "w") as _fh:
                _fh.write("x\n")
        _fg_green = dict(fgm["phases"][1]["tasks"][1]["testEvidence"])
        code, txt = run(["scope", "P2.3", "--gate",
                         "npm test -- src/known.test.ts",
                         "--project-dir", fg_proj])
        _fgt = task_in(fg_mp, "P2.3") or {}
        check("fg1 a STARTED task takes a new `tests.gate`, and the green "
              "verdict already cached on it is untouched - that pair IS the "
              "permission: the gate is what the next run will measure, and the "
              "pointer holds a run's id, verdict and time, so the write moves "
              "nothing that was already recorded: %r"
              % ((code, (_fgt.get("tests") or {}).get("gate"),
                  _fgt.get("testEvidence")),),
              code == 0
              and (_fgt.get("tests") or {}).get("gate")
              == ["npm test -- src/known.test.ts"]
              and _fgt.get("testEvidence") == _fg_green)
        check("fg2 ...and the report DATES it and says on what basis, without "
              "claiming a widening: nothing grew, so a line reading WIDENED "
              "would name a growth this call did not make - the two acceptances "
              "have two reasons and the operator meets them here: %r"
              % (txt[-400:],),
              "GATE CHANGED during attempt 2, while the task is in_progress"
              in txt
              and "the measurement the NEXT run will make" in txt
              and "WIDENED" not in txt)
        code, txt = run(["scope", "P2.3", "--files",
                         "src/known.ts,src/added.ts", "--gate",
                         "npm test -- src/known.test.ts --run",
                         "--project-dir", fg_proj])
        _fg_rows = [r for r in (_stmod.read_all(fg_proj) if _stmod else [])
                    if r.get("action") == "task.scope"]
        _fg_sum = [r.get("summary") or "" for r in _fg_rows]
        _fg_flds = [sorted(set(c.get("field") for c
                               in ((r.get("details") or {}).get("changes")
                                   or [])))
                    for r in _fg_rows]
        check("fg3 the gate change is its OWN journal row, in the widening "
              "row's shape rather than a second invention - same action, same "
              "allow-listed details, same attempt dating, one event word "
              "swapped. A call that both widens and re-gates writes BOTH, "
              "because `audit-journal list` prints the summary alone and one "
              "summary carries one event: %r" % (list(zip(_fg_sum, _fg_flds)),),
              code == 0 and len(_fg_rows) == 3
              and _fg_flds == [["tests.gate", "tests.gateBasis"], ["files"],
                               ["tests.gate"]]
              and "GATE CHANGED" in _fg_sum[0] and "WIDENED" in _fg_sum[1]
              and "GATE CHANGED" in _fg_sum[2]
              and all("during attempt 2" in s for s in _fg_sum)
              and all((r.get("details") or {}).get("attempt") == 2
                      for r in _fg_rows))
        code, txt = run(["scope", "P2.3", "--gate-clear", "--json",
                         "--project-dir", fg_proj])
        try:
            _fgj = json.loads(txt)
        except ValueError:
            # sf12's lesson: a refused call prints a sentence, and letting that
            # reach `json.loads` bare stops the body dead instead of failing one
            # case.
            _fgj = {}
        check("fg4 the machine surface carries the two events APART, and this "
              "is the call that separates them: `widened` read off 'the task "
              "has started' alone would say true here, on a call that dropped "
              "the gate to empty and grew nothing at all: %r"
              % ((_fgj.get("widened"), _fgj.get("gateChanged"),
                  _fgj.get("attempt")),),
              _fgj.get("widened") is False and _fgj.get("gateChanged") is True
              and _fgj.get("attempt") == 2
              and (task_in(fg_mp, "P2.3") or {}).get("tests", {})
              .get("gate") == [])
        check("fg5 ...which is `--gate-clear` reaching the EMPTY gate on a "
              "RUNNING task - the direction that is not growth in any reading, "
              "so a permission written as 'append-only, now with a third field' "
              "would refuse it: %r" % (_fgj.get("changes"),),
              any(c.get("field") == "tests.gate" and c.get("to") == []
                  for c in (_fgj.get("changes") or [])))
        with open(fg_mp, "rb") as _fh:
            _fg_before = _fh.read()
        code, txt = run(["scope", "P2.3", "--tests-mode", "regression",
                         "--project-dir", fg_proj])
        with open(fg_mp, "rb") as _fh:
            _fg_after = _fh.read()
        check("fg6 OVER-FIRE CASE, on the nearest neighbour there is: "
              "`tests.mode` is still refused on that same started task and "
              "writes no byte. The mode is what an attempt was GRADED under - "
              "the gate is only the commands the next run shells out to - so a "
              "permission widened from the field to its parent object would "
              "let this through: %r" % (txt[:250],),
              code == 2 and _fg_after == _fg_before
              and "already been attempted (2)" in txt
              and '`tests.mode` would move from "tdd" to "regression"' in txt)
        code, txt = run(["scope", "P2.3", "--risk", "high",
                         "--project-dir", fg_proj])
        with open(fg_mp, "rb") as _fh:
            _fg_after = _fh.read()
        check("fg7 OVER-FIRE CASE, the second field that REPLACES a value the "
              "attempt ran under: `risk` feeds the executor's model floor and "
              "whether a commit needs confirming, and it is still refused here "
              "whichever way it moves: %r" % (txt[:250],),
              code == 2 and _fg_after == _fg_before
              and '`risk` would move from "low" to "high"' in txt)
        # THE DOCUMENT JOIN, read out of `commands/task.md` rather than restated
        # here: that file listed `--gate` among the flags keeping the old
        # refusal, and a document describing a refusal the verb no longer makes
        # sends an operator back to the hand edit it forbids. READ, NOT CAUGHT -
        # a suite that cannot open the document it compares must fail rather
        # than assert on an empty string.
        with open(os.path.join(_output.PLUGIN_ROOT, "commands", "task.md"),
                  "r", encoding="utf-8") as _fh:
            _fg_doc = _fh.read()
        # Why the gate crosses the line on a started task is the verb's
        # explanation, which moved with the rest of it out of the command body
        # into `reference/verbs-in-full.md`, which the plugin ships.
        with open(os.path.join(_output.PLUGIN_ROOT, "reference", "verbs-in-full.md"),
                  "r", encoding="utf-8") as _fh:
            _fg_guide = _fh.read()
        _fg_at = _fg_doc.find("all keep the old refusal")
        # The flag list is the RUN-UP to that clause, so the window ends where
        # the clause begins - a window reaching past it would pick up the
        # paragraph that licenses `--gate` and read the removal as still done.
        _fg_sent = _fg_doc[max(0, _fg_at - 260):_fg_at] if _fg_at >= 0 else ""
        check("fg8 `commands/task.md` no longer counts `--gate` among the flags "
              "that keep the old refusal, and says which reading licenses it - "
              "the verb and its own document have to describe one refusal, or "
              "the reader is sent back to the hand edit this file forbids: %r"
              % (_fg_sent[-200:],),
              _fg_at >= 0 and "`--gate`" not in _fg_sent
              and "`--tests-mode`" in _fg_sent
              and "`--risk`" in _fg_sent
              and "`tests.gate` may be replaced outright" in _fg_doc
              and "narrowed to a started task with no green run recorded"
              in _fg_guide)

        # ---- (pb) readiness ignored the owning phase's blockedBy ---------------
        # `reference/orchestrator.md`'s readiness rule has FOUR terms and the
        # fourth is the task's PHASE's `blockedBy`. `_waiting_on` carried two, so
        # `add` and `scope` printed a copyable `ready now -- /audit:run <id>` for
        # a task whose phase was parked - while `/audit:status`, reading
        # `_status_facts`, said the opposite about the same manifest. Reported
        # from a live run. The w group tests the lookup; these two drive the
        # verbs, because the handoff sentence is what an operator acts on.
        pbm = base_manifest()
        pbm["phases"][2]["blockedBy"] = ["P2"]
        pbm["phases"][2]["tasks"] = [
            {"id": "P3.1", "title": "parked behind its phase", "status": "pending",
             "description": "imported", "files": [],
             "tests": {"mode": "gate-only", "expectRedFirst": False,
                       "add": [], "gate": []},
             "model": "sonnet", "skills": [], "risk": "low",
             # A SATISFIED task-level ref, deliberately: removing it moves a ref
             # field (which is what makes `scope` print readiness at all) and
             # leaves the task with nothing of its OWN to wait on, so the only
             # thing that can still hold it is the term this entry is about.
             "blockedBy": [], "dependsOn": ["P2.1"], "attempts": 0}]
        pb_proj, pb_mp = mk("pb-phaseblocked", pbm)
        code, txt = run(["scope", "P3.1", "--depends-on", "",
                         "--project-dir", pb_proj])
        check("pb1 `scope` does not hand back a runnable command for a task "
              "whose PHASE is blocked - it names the blocker and says which term "
              "it came from, because a bare id there sends the reader looking "
              "for a task by that name: %r" % (txt[-120:],),
              code == 0 and "waiting on: P2 (phase)" in txt
              and "ready now" not in txt)
        code, txt = run(["add", "More of the same", "--phase", "P3",
                         "--project-dir", pb_proj])
        check("pb2 ...and neither does `add`, which reaches the same answer "
              "through the same lookup - both call sites held the owning phase "
              "already and neither was asking it: %r" % (txt[-120:],),
              code == 0 and "waiting on: P2 (phase)" in txt
              and "ready now" not in txt)
        # P2.3 is PENDING, so this leaves the task with an unmet ref of its OWN
        # as well as an unmet phase: the only shape that shows the two terms side
        # by side, and one a single-term answer cannot produce.
        code, txt = run(["scope", "P3.1", "--depends-on", "P2.3", "--json",
                         "--project-dir", pb_proj])
        try:
            _pbj = json.loads(txt)
        except ValueError:
            _pbj = {}
        check("pb3 ...and the machine surface carries both terms, in the order a "
              "reader meets them - own refs first, then the phase's, suffixed: %r"
              % ((_pbj.get("ready"), _pbj.get("waitingOn")),),
              _pbj.get("ready") is False
              and _pbj.get("waitingOn") == ["P2.3", "P2 (phase)"])
        # THE PAIRED NEGATIVE. A term appended without being evaluated would pass
        # pb1-pb3 forever while reporting every task in every blocked-by-anything
        # phase as waiting - including the ones whose blocker has landed.
        pbm2 = base_manifest()
        pbm2["phases"][2]["blockedBy"] = ["P1"]
        pb2_proj, pb2_mp = mk("pb-phaseclear", pbm2)
        code, txt = run(["add", "Ready under a satisfied phase", "--phase", "P3",
                         "--project-dir", pb2_proj])
        check("pb4 SECOND-DIRECTION CASE: a phase whose OWN blockedBy is done "
              "holds nothing back, so the handoff is printed - the term is "
              "evaluated rather than merely appended: %r" % (txt[-90:],),
              code == 0 and "ready now -- /audit:run P3.1" in txt)

        # ---- (qg) add-phase reaches the EMPTY gate -----------------------------
        # The THIRD verb of one shape. `--gate-clear` sits on the shared parser, so
        # argparse accepted it here while `_phase_gate` never looked - the new
        # phase inherited `meta.buildCommands` and the caller was told the call
        # worked. `scope` was the gc group's bug and `add` was the ag group's;
        # the check that exists because of those two did not cover the verb
        # where it happened again,
        # which is why `_AT_WRITERS` gained a row with the fix.
        qg_proj, qg_mp = mk("p-phasegate", base_manifest())
        code, txt = run(["add-phase", "Docs only", "--outcome", "shipped",
                         "--gate-clear", "--project-dir", qg_proj])
        _qgp = [p for p in _mio.load_manifest(qg_mp)["phases"]
                if p.get("title") == "Docs only"]
        check("qg1 --gate-clear reaches the EMPTY gate on a NEW phase, so a plan "
              "whose remaining work nothing here can grade does not inherit a "
              "gate it cannot pass: %r" % ([p.get("testGate") for p in _qgp],),
              code == 0 and len(_qgp) == 1 and _qgp[0].get("testGate") == [])
        check("qg2 ...and the report names the FLAG as the basis, not a sentence "
              "about the manifest - 'nothing here can prove it' and 'the caller "
              "said not to' are different answers and only one of them is a "
              "choice: %r" % (txt[-90:],),
              "--gate-clear" in txt)
        # THE PAIRED NEGATIVE. A resolver that simply stopped reading
        # `meta.buildCommands` would pass qg1 exactly as the repair does.
        code, txt = run(["add-phase", "Inherits", "--outcome", "o",
                         "--project-dir", qg_proj])
        _qgi = [p for p in _mio.load_manifest(qg_mp)["phases"]
                if p.get("title") == "Inherits"]
        check("qg3 a phase with NEITHER flag still inherits meta.buildCommands - "
              "the clear is a choice a caller makes, not a new default: %r"
              % ([p.get("testGate") for p in _qgi],),
              code == 0 and _qgi and _qgi[0].get("testGate") == ["test"])
        _qg_before = _mio.load_manifest(qg_mp)
        code, txt = run(["add-phase", "Both", "--outcome", "o",
                         "--gate", "test", "--gate-clear",
                         "--project-dir", qg_proj])
        check("qg4 --gate with --gate-clear is REFUSED and writes nothing - the "
              "worse half, since before the fix it exited 0 and wrote the gate. "
              "The refusal is the same sentence the other three verbs spend, so "
              "four copies of one rule cannot drift apart: %r" % (txt[:80],),
              code == 2 and "opposite things" in txt
              and len(_mio.load_manifest(qg_mp)["phases"])
              == len(_qg_before["phases"]))

        # ---- (eb) the brief the shell had already eaten ------------------------
        # Reported from a live project. `--description "... `<the condition>`,
        # returning the response untouched otherwise."` -- the backticks are
        # COMMAND SUBSTITUTION inside double quotes, so the shell ran the
        # condition as a command and put its output (nothing) in its place. What
        # reached argparse had a hole in it exactly where the clause the author
        # had marked as the point used to be, and this script wrote it. The whole
        # treatment was `default=""`.
        #
        # THE FIXTURE IS THE DAMAGED STRING ITSELF, byte for byte as it was
        # stored, because a check written against a shape somebody invented is a
        # check that happens to agree with the incident rather than one that
        # catches it.
        _EATEN = ("transformErrorResponse gating on , returning the response "
                  "untouched otherwise.")
        _WHOLE = ("transformErrorResponse gating on `if (response.status "
                  "!== 409) return response`, returning the response untouched "
                  "otherwise.")
        eb_proj, eb_mp = mk("eb-brief", base_manifest())
        with open(eb_mp, "rb") as _fh:
            _eb_before = _fh.read()
        code, txt = run(["add", "Gate the error path", "--phase", "P2",
                         "--description", _EATEN, "--project-dir", eb_proj])
        with open(eb_mp, "rb") as _fh:
            _eb_after = _fh.read()
        check("eb1 the brief the shell ate is REFUSED off argv and the manifest "
              "is byte identical - the fault was that it was accepted and "
              "written, so the exit code alone is not the assertion: %r"
              % (txt[:90],),
              code == 2 and _eb_after == _eb_before)
        check("eb2 ...and the refusal says WHAT IT SAW and WHERE TO PUT IT. A "
              "reader told only that their input is malformed retypes the same "
              "command and the same shell eats the same clause again, so the "
              "message carries the offending span and the `-` route: %r"
              % (txt[:200],),
              "gating on , returning" in txt
              and "--description -" in txt
              and "BRIEF" in txt)
        # THE ORDER IS THE MESSAGE, and this is the case that holds it. Every
        # fact above is still here; what changed is that the command the reader
        # retypes is printed before the argument for it, because a refusal is
        # read in the order it arrives and this one wraps to most of a screen.
        _eb_lines = txt.splitlines()
        _eb_at = dict((_marker, [i for i, _l in enumerate(_eb_lines)
                                 if _marker in _l])
                      for _marker in ("<<'BRIEF'", "Seen at:",
                                      "COMMAND SUBSTITUTION"))
        check("eb2b ...and it says it in THAT order: the heredoc the reader "
              "retypes first, then the marked span, then one line of cause. "
              "Before this the same facts arrived with two paragraphs of "
              "argument in front of the three lines that are the repair: %r"
              % (_eb_at,),
              all(_hits for _hits in _eb_at.values())
              and _eb_at["<<'BRIEF'"][0] < _eb_at["Seen at:"][0]
              < _eb_at["COMMAND SUBSTITUTION"][0])
        # SECOND-DIRECTION CASE, and the one that decides whether this can ship:
        # an ordinary sentence with a comma in it is most of the corpus.
        code, txt = run(["add", "Ordinary brief", "--phase", "P2",
                         "--description",
                         "gating on the status, returning it untouched "
                         "otherwise.", "--project-dir", eb_proj])
        _eb_ok = [t for t in (_mio.tasks_by_id(_mio.load_manifest(eb_mp))
                              or {}).values()
                  if t.get("title") == "Ordinary brief"]
        check("eb3 SECOND-DIRECTION CASE: a description carrying an ordinary "
              "comma is written unchanged - a guard that fires on correct input "
              "is a guard somebody routes around within the day: %r"
              % ([t.get("description") for t in _eb_ok],),
              code == 0 and len(_eb_ok) == 1
              and _eb_ok[0].get("description")
              == "gating on the status, returning it untouched otherwise.")
        # The repair itself. `-` is the dialect five ADO scripts here already
        # speak; a brief that comes this way never meets a shell at all.
        code, txt = run_on_stdin(["add", "From stdin", "--phase", "P2",
                                  "--description", "-",
                                  "--project-dir", eb_proj], _WHOLE + "\n")
        _eb_in = [t for t in (_mio.tasks_by_id(_mio.load_manifest(eb_mp))
                              or {}).values()
                  if t.get("title") == "From stdin"]
        check("eb4 `--description -` reads the brief off STDIN and stores it "
              "VERBATIM, backticks and the condition included - the trailing "
              "newline a heredoc always adds is the only thing dropped: %r"
              % ([t.get("description") for t in _eb_in],),
              code == 0 and len(_eb_in) == 1
              and _eb_in[0].get("description") == _WHOLE)
        # THE DOOR, and it is what makes refusing defensible rather than a trap.
        code, txt = run_on_stdin(["add", "Gap on purpose", "--phase", "P2",
                                  "--description", "-",
                                  "--project-dir", eb_proj], _EATEN + "\n")
        _eb_gap = [t for t in (_mio.tasks_by_id(_mio.load_manifest(eb_mp))
                               or {}).values()
                   if t.get("title") == "Gap on purpose"]
        check("eb5 ...and the SAME text on that route is written rather than "
              "refused: the check's evidence is that a shell handled the value, "
              "which is untrue here, and a guard whose only escape is to mangle "
              "your own prose has no escape: %r"
              % ([t.get("description") for t in _eb_gap],),
              code == 0 and len(_eb_gap) == 1
              and _eb_gap[0].get("description") == _EATEN)
        _eb_verbs = {}
        for _v, _argv in (("scope", ["scope", "P2.3"]),
                          ("add-phase", ["add-phase", "Later work",
                                         "--outcome", "shipped"]),
                          ("retarget", ["retarget", "P2"])):
            _eb_verbs[_v] = run(_argv + ["--description", _EATEN,
                                         "--project-dir", eb_proj])[0]
        check("eb6 EVERY verb that writes a description refuses it, not just "
              "`add`: four of them take the flag off one global parser and each "
              "writes the value straight into the manifest, so a check living "
              "inside one of them is a check the other three do not have: %r"
              % (_eb_verbs,),
              sorted(_eb_verbs.values()) == [2, 2, 2])
        with open(eb_mp, "rb") as _fh:
            _eb_pre_empty = _fh.read()
        code, txt = run_on_stdin(["add", "Nothing on stdin", "--phase", "P2",
                                  "--description", "-",
                                  "--project-dir", eb_proj], "   \n")
        with open(eb_mp, "rb") as _fh:
            _eb_post_empty = _fh.read()
        check("eb7 `-` with nothing on stdin is a usage error naming the "
              "heredoc, not a task written with an empty brief - that is the "
              "same silent loss one step further on, and it is the shape a "
              "whole backticked description collapses to: %r" % (txt[:120],),
              code == 2 and _eb_post_empty == _eb_pre_empty
              and "BRIEF" in txt)
        check("eb8 the gap is read at every POSITION an eaten span can leave "
              "one, because the reported damage happened to sit before a comma "
              "and the next one will not: %r"
              % ([M.shell_eaten_gap(s) and M.shell_eaten_gap(s)[0]
                  for s in ("the  flag is read", "it is set by .",
                            "wrap ( ) around it")],),
              M.shell_eaten_gap("the  flag is read")
              and M.shell_eaten_gap("it is set by .")
              and M.shell_eaten_gap("wrap ( ) around it"))
        check("eb9 SECOND-DIRECTION CASE: the shapes ordinary technical prose "
              "really produces are NOT gaps - two spaces after a full stop is a "
              "typing convention, an indented continuation line is a line, and a "
              "bare `.` in a quoted command is a PATH (the one false positive "
              "the whole plan produced, before the full stop had to end a "
              "sentence): %r"
              % ([M.shell_eaten_gap(s)
                  for s in ("It ends here.  And starts again.",
                            "a line\n   indented on",
                            "run git fetch . b:p here")],),
              not M.shell_eaten_gap("It ends here.  And starts again.")
              and not M.shell_eaten_gap("a line\n   indented on")
              and not M.shell_eaten_gap("run git fetch . b:p here"))

        # ---- (gm) the refusal marks what it matched ----------------------------
        # Reported live: a nested ternary -- `foo() ? (a ? 280 : 70) : 0` --
        # passed through a LIST-FORM call with NO SHELL ANYWHERE tripped the
        # same whitespace-adjacency check the `eb` group above drives with a
        # real shell-eaten backtick, and the refusal explained itself in terms
        # of a backtick span being eaten. There were no backticks: the check
        # tests `_GAP_SHAPES` and none of them is one.
        gm_brief = "foo() ? (a ? 280 : 70) : 0"
        # A MISS IS A FAILED CASE, not a raise: unpacking None would stop the
        # suite here and every case after this line would go unrun.
        gm_what, gm_excerpt, gm_rs, gm_re = (M.shell_eaten_gap(gm_brief)
                                             or (None, "", 0, 0))
        check("gm0 fixture check: the ternary matches the space-before-a-mark "
              "shape on exactly the space+colon after `280`, and the excerpt "
              "is the whole short brief -- so the assertions below are "
              "checking a real match and not an empty one: %r"
              % ((gm_what, gm_excerpt, gm_excerpt[gm_rs:gm_re]),),
              gm_what == "whitespace before a mark that hugs the word in "
                         "front of it"
              and gm_excerpt == gm_brief and gm_excerpt[gm_rs:gm_re] == " :")
        gm_proj, gm_mp = mk("gm-ternary", base_manifest())
        code, gm_txt = run(["add", "Ternary brief", "--phase", "P2",
                            "--description", gm_brief,
                            "--project-dir", gm_proj])
        check("gm1 the ternary trips the SAME refusal an eaten backtick does, "
              "off a call this harness makes with `M.main(argv, ...)` -- an "
              "argv list, never a shell: %r" % (gm_txt[:160],),
              code == 2 and "hugs the word in front of it" in gm_txt)
        # INDEPENDENTLY COMPUTED, NOT TAKEN FROM `M._marked_excerpt` -- calling
        # the function under test to build the expectation it is then checked
        # against is the shortcut `no-silent-pass` warns about: a bug INSIDE
        # `_marked_excerpt` would move the expectation and the check together
        # and neither could ever fail. `gm0` already proved `gm_rs`/`gm_re`/
        # `gm_excerpt` are right against fixed literals, so the caret line
        # is rebuilt here from those primitives alone.
        gm_expect_marks = "".join("^" if gm_rs <= i < gm_re else " "
                                  for i in range(len(gm_excerpt)))
        gm_seen_line = M.SEEN_PREFIX + "'" + gm_excerpt + "'"
        gm_mark_line = (" " * len(M.SEEN_PREFIX)) + " " + gm_expect_marks
        check("gm2 a MARKER sits inside the printed window, aligned under the "
              "exact characters that matched -- the excerpt line and an "
              "INDEPENDENTLY built caret line both appear, in that order, so "
              "a reader is pointed at the characters that matched rather "
              "than left to count spaces across the whole excerpt: %r"
              % ((gm_seen_line, gm_mark_line),),
              gm_seen_line in gm_txt and gm_mark_line in gm_txt
              and gm_txt.index(gm_seen_line) < gm_txt.index(gm_mark_line))
        check("gm3 the message never claims the untested cause as fact: it "
              "says COMMAND SUBSTITUTION is ONE way this shape appears and "
              "that the check cannot tell that apart from code quoted "
              "straight into the brief -- which is what actually happened "
              "here, with no shell and no backtick anywhere in the call: %r"
              % (gm_txt[-460:],),
              "COMMAND SUBSTITUTION" in gm_txt
              and "cannot tell COMMAND SUBSTITUTION of a backtick span from "
                  "code quoted straight into the brief" in gm_txt
              and "`" not in gm_brief)
        # SECOND-DIRECTION CASE, and the one that decides whether this reads
        # as a repair rather than a rewording: the OLD sentence asserted the
        # cause as fact, and it must be gone rather than merely joined by a
        # hedge.
        check("gm4 SECOND-DIRECTION CASE: the retired sentence -- which "
              "asserted a deleted clause as fact rather than a shape that is "
              "consistent with one -- does not survive beside the new one: "
              "%r" % (gm_txt[-460:],),
              "is missing exactly the clause its author thought worth "
              "quoting" not in gm_txt)
        check("gm5 the STDIN escape works for text with no backticks at all "
              "-- it is the fix for the SHAPE, not only for backtick damage: "
              "%r" % (gm_brief,),
              run_on_stdin(["add", "Ternary via stdin", "--phase", "P2",
                            "--description", "-",
                            "--project-dir", gm_proj], gm_brief + "\n")[0] == 0)
        gm_help = M.build_parser().format_help()
        check("gm6 `--help` on the flag itself now says something -- before "
              "this it printed the bare flag name and the stdin escape was "
              "undiscoverable to a caller who had not yet been refused, and "
              "whose text has no backtick to go looking for: %r"
              % (gm_help[gm_help.index("--description"):
                         gm_help.index("--description") + 160],),
              "stdin" in gm_help and "whitespace-adjacency" in gm_help)

        # ---- (pf) the CLASS `--description` was one member of -------------------
        # The eb group fixed one flag. Two more carry the operator's own prose
        # into the manifest AND into the hash-chained journal through the same
        # shell: `--reason`, which is a VERBATIM field precisely so nobody would
        # paraphrase it - so a clause deleted out of one is silent by design -
        # and `--outcome`, which is the phase's `desiredOutcome` and the thing
        # sign-off has to address. `--rename` is here for the same reason one
        # step further: a phase title is what `_branch.slugify` composes a
        # branch name from.
        pf_proj, pf_mp = mk("pf-prose", base_manifest())
        with open(pf_mp, "rb") as _fh:
            _pf_before = _fh.read()
        _pf_refused = {}
        for _pfargv, _pfwhat in (
                (["cancel", "P2.3", "--reason", _EATEN], "cancel/--reason"),
                (["add-phase", "Later", "--outcome", _EATEN],
                 "add-phase/--outcome"),
                (["retarget", "P3", "--outcome", _EATEN],
                 "retarget/--outcome"),
                (["retarget", "P3", "--rename", _EATEN],
                 "retarget/--rename")):
            _pf_refused[_pfwhat] = run(_pfargv + ["--project-dir", pf_proj])
        with open(pf_mp, "rb") as _fh:
            _pf_after = _fh.read()
        check("pf1 --reason and --outcome refuse a shell-eaten value, and so "
              "does --rename: the manifest is byte identical, which is the "
              "assertion, because the fault was that each of these was accepted "
              "and written. `--reason` is the sharpest - it is a VERBATIM field "
              "precisely so nobody would paraphrase it, so a hole in one is silent by "
              "design: %r"
              % (dict((k, v[0]) for k, v in _pf_refused.items()),),
              sorted(v[0] for v in _pf_refused.values()) == [2, 2, 2, 2]
              and _pf_after == _pf_before)
        check("pf2 ...and every refusal names the FLAG the caller typed, not "
              "`--description`: one route serves them all now, and a message "
              "naming the wrong argument sends the reader to the wrong part of "
              "their own command line: %r"
              % (dict((k, v[1][:60]) for k, v in _pf_refused.items()),),
              all(_pf_refused[k][1].startswith("[audit-task] " + f)
                  for k, f in (("cancel/--reason", "--reason"),
                               ("add-phase/--outcome", "--outcome"),
                               ("retarget/--outcome", "--outcome"),
                               ("retarget/--rename", "--rename"))))
        _pf_stdin = {}
        _pf_stdin["reason"] = run_on_stdin(
            ["cancel", "P2.3", "--reason", "-", "--project-dir", pf_proj],
            _WHOLE + "\n")
        _pf_task = task_in(pf_mp, "P2.3") or {}
        check("pf3 ...and each has the STDIN route out, which is the repair "
              "rather than the check: `--reason -` writes the operator's words "
              "verbatim, backticks and the condition included, into the field "
              "the report reads: %r"
              % ((_pf_stdin["reason"][0],
                  (_pf_task.get("outcome") or {}).get("descriptive")),),
              _pf_stdin["reason"][0] == 0
              and (_pf_task.get("outcome") or {}).get("descriptive")
              == "Cancelled: " + _WHOLE)
        _pf_out = run_on_stdin(["add-phase", "From stdin", "--outcome", "-",
                                "--project-dir", pf_proj], _WHOLE + "\n")
        _pf_phase = [ph for ph in _mio.load_manifest(pf_mp)["phases"]
                     if ph.get("title") == "From stdin"]
        check("pf4 ...and `--outcome -` likewise, on the verb that REQUIRES it: "
              "a phase whose success cannot be stated is a phase sign-off "
              "cannot address, so the one field the verb insists on was the one "
              "with no shell-proof way in: %r"
              % ([p.get("desiredOutcome") for p in _pf_phase],),
              _pf_out[0] == 0 and len(_pf_phase) == 1
              and _pf_phase[0].get("desiredOutcome") == _WHOLE)
        # THE DESIGN QUESTION, ANSWERED IN THE CODE. stdin is ONE stream and
        # `add-phase` takes two prose flags (`retarget` takes three), so `-` is
        # a request at most one of them per call can be granted. Resolving it by
        # reading would put one operator's brief into the other's field.
        _pf_two = run_on_stdin(["add-phase", "Two claims", "--outcome", "-",
                                "--description", "-",
                                "--project-dir", pf_proj], _WHOLE + "\n")
        _pf_three = run_on_stdin(["retarget", "P3", "--outcome", "-",
                                  "--rename", "-", "--description", "-",
                                  "--project-dir", pf_proj], _WHOLE + "\n")
        check("pf5 ...and two flags claiming stdin in one call is REFUSED, "
              "naming which two are competing - stdin is one stream, so "
              "whichever was read first would take all of it and the other "
              "would get nothing, written verbatim into the wrong field with a "
              "journal row attesting it: %r"
              % ((_pf_two[0], _pf_two[1][:150]),),
              _pf_two[0] == 2 and "each claim stdin" in _pf_two[1]
              and "--description" in _pf_two[1] and "--outcome" in _pf_two[1]
              # THREE claimants on `retarget`, so the message is built from the
              # flags in the call rather than from a hard-coded pair.
              and _pf_three[0] == 2 and "--rename" in _pf_three[1])
        # SECOND-DIRECTION CASE. A refusal that fires on ONE claimant would make
        # the route unusable, and it is the only case that catches that.
        _pf_one = run_on_stdin(["add-phase", "One claim only", "--outcome", "-",
                                "--description", "written on the line",
                                "--project-dir", pf_proj], "shipped\n")
        _pf_one_phase = [ph for ph in _mio.load_manifest(pf_mp)["phases"]
                         if ph.get("title") == "One claim only"]
        check("pf6 SECOND-DIRECTION CASE: ONE flag claiming stdin alongside "
              "another prose flag given on the command line is accepted, and "
              "each field gets its own text - an arbitration that fired on a "
              "single claimant would close the route it exists to protect: %r"
              % ([(p.get("desiredOutcome"), p.get("description"))
                  for p in _pf_one_phase],),
              _pf_one[0] == 0 and len(_pf_one_phase) == 1
              and _pf_one_phase[0].get("desiredOutcome") == "shipped"
              and _pf_one_phase[0].get("description") == "written on the line")
        # THE MEASURED RESIDUAL, and the decision about it. An UNQUOTED heredoc
        # word expands its body exactly as double quotes do, so the shell eats
        # the clause BEFORE stdin is read and the route advertised as the repair
        # delivers damaged text with exit 0. Refusing stdin would close the door
        # a false positive escapes through - the guard-with-no-door shape this
        # repository has three fault entries about - so the run continues and
        # the reader is TOLD, with both readings side by side.
        _pf_note = run_on_stdin(["add-phase", "Eaten on stdin", "--outcome", "-",
                                 "--project-dir", pf_proj], _EATEN + "\n")
        _pf_note_phase = [ph for ph in _mio.load_manifest(pf_mp)["phases"]
                          if ph.get("title") == "Eaten on stdin"]
        check("pf7 a gap that arrives on STDIN is written verbatim AND said out "
              "loud: an unquoted `<<BRIEF` expands its body exactly as double "
              "quotes do, so the one route advertised as shell-proof is not - "
              "and silence there left that case indistinguishable from prose "
              "somebody meant: %r" % (_pf_note[1][:200],),
              _pf_note[0] == 0 and len(_pf_note_phase) == 1
              and _pf_note_phase[0].get("desiredOutcome") == _EATEN
              and "note:" in _pf_note[1]
              and "<<'BRIEF'" in _pf_note[1]
              and "VERBATIM" in _pf_note[1])
        # SECOND-DIRECTION CASE for pf7: the note must not fire on stdin text
        # that reads whole, or it becomes a line every heredoc prints.
        check("pf8 SECOND-DIRECTION CASE: stdin text with no gap in it draws no "
              "note at all - a note on every heredoc is a note nobody reads, "
              "and pf4's own run is the corpus that says so: %r"
              % (_pf_out[1][:120],),
              "note: the text on stdin" not in _pf_out[1]
              and "note: the text on stdin" not in _pf_stdin["reason"][1])
        # A REGRESSION IN THAT SAME FIX, reported from a live run and the
        # reason an advisory printed before dispatch is a defect rather than a style
        # choice: this note went to `out` from `resolve_briefs`, which runs
        # BEFORE the verb, so `--json` came back as three human lines followed
        # by the object and `json.load` raised on line 1 column 2 - at exit 0,
        # so a machine consumer saw success and an unparseable payload.
        _pf_json = run_on_stdin(["add-phase", "Titled", "--outcome", "-",
                                 "--json", "--project-dir", pf_proj],
                                _EATEN + "\n")
        _pf_parsed = None
        try:
            _pf_parsed = json.loads(_pf_json[1])
        except Exception as _exc:
            _pf_parsed = "UNPARSEABLE: %s" % (_exc,)
        check("pf11 `--json` stays ONE parseable object when a stdin value "
              "draws the note, and the note is a KEY - every other advisory in "
              "these verbs is data in JSON mode (`filesNotOnDisk`, "
              "`testsAddNamingNoFile`) and this was the one that printed prose "
              "into the same stream at exit 0: %r"
              % (_pf_parsed if isinstance(_pf_parsed, str)
                 else sorted(_pf_parsed),),
              _pf_json[0] == 0 and isinstance(_pf_parsed, dict)
              and _pf_parsed.get("ok") is True
              and len(_pf_parsed.get("stdinNotes") or []) == 1
              and "<<'BRIEF'" in (_pf_parsed.get("stdinNotes") or [""])[0])
        check("pf12 SECOND-DIRECTION CASE: the key is ABSENT when there is no "
              "note, so a reader can tell 'nothing to say' from a release that "
              "does not carry them - and the HUMAN branch still prints it, "
              "which is the half a suppression would have quietly dropped: %r"
              % ((_pf_out[1][-70:],),),
              "stdinNotes" not in json.loads(
                  run_on_stdin(["add-phase", "Clean json", "--outcome", "-",
                                "--json", "--project-dir", pf_proj],
                               "shipped\n")[1])
              and "note: the text on stdin" in run_on_stdin(
                  ["add-phase", "Human note", "--outcome", "-",
                   "--project-dir", pf_proj], _EATEN + "\n")[1])
        # The pf group closed the class for FLAGS and left the TITLE, which put
        # the guard on the CORRECTION path and not on the path where a title
        # first reaches the manifest: `retarget --rename "$T"` refused a run of spaces
        # while `add-phase "$T"` and `add "$T"` wrote the same string verbatim.
        # `_branch.slugify` derives the branch name from a phase title, which is
        # the argument for checking `--rename` read one door earlier.
        with open(pf_mp, "rb") as _fh:
            _pf_t_before = _fh.read()
        _pf_titles = {}
        for _pfargv, _pfwhat in (
                (["add-phase", _EATEN, "--outcome", "ok"], "add-phase"),
                (["add", _EATEN, "--phase", "P2"], "add")):
            _pf_titles[_pfwhat] = run(_pfargv + ["--project-dir", pf_proj])
        with open(pf_mp, "rb") as _fh:
            _pf_t_after = _fh.read()
        check("pf13 the TITLE positional is in the class too: `add` and "
              "`add-phase` refuse a shell-eaten title and write nothing, where "
              "before they took the same string `retarget --rename` was already "
              "refusing. The message names `the <title> argument` and not a "
              "`--title` flag, which argparse refuses and `rn4` pins: %r"
              % (dict((k, (v[0], v[1][:40])) for k, v in _pf_titles.items()),),
              sorted(v[0] for v in _pf_titles.values()) == [2, 2]
              and _pf_t_after == _pf_t_before
              and all("the <title> argument carries" in v[1]
                      for v in _pf_titles.values()))
        _pf_t_stdin = run_on_stdin(["add-phase", "-", "--outcome", "shipped",
                                    "--project-dir", pf_proj],
                                   "A title with `backticks` in it\n")
        _pf_t_named = [ph.get("title")
                       for ph in _mio.load_manifest(pf_mp)["phases"]
                       if "backticks" in (ph.get("title") or "")]
        check("pf14 ...and it has the same STDIN route, so the guard has a "
              "door: a title whose backticks matter comes through verbatim: %r"
              % (_pf_t_named,),
              _pf_t_stdin[0] == 0
              and _pf_t_named == ["A title with `backticks` in it"])
        # SECOND-DIRECTION CASE, and the one that decides whether this can
        # ship: the same positional is the ID on three verbs, and an id is not
        # prose. Checking it there would put a prose guard on `P2.3`.
        # ITS OWN PROJECT. `pf_proj` has been cancelled, scoped and retargeted
        # by the cases above, so an exit 2 there could be the accumulated state
        # rather than the positional - which is exactly what it was on the first
        # run of this case, and a green reading of it would have been luck.
        _pfid_proj, _pfid_mp = mk("pf-ids", base_manifest())
        _pf_ids = {}
        for _pfargv, _pfwhat in (
                (["scope", "P2.3", "--files", "src/a.ts"], "scope"),
                (["retarget", "P3", "--outcome", "restated"], "retarget"),
                (["cancel", "P2.3", "--reason", "dropped"], "cancel")):
            _pf_ids[_pfwhat] = run(_pfargv + ["--project-dir", _pfid_proj])[0]
        check("pf15 SECOND-DIRECTION CASE: the same positional is the ID for "
              "`scope`, `retarget` and `cancel`, and those are untouched - the "
              "door and the check follow the VERB, because an id is not prose "
              "and `-` in an id slot would mean reading an id off stdin: %r"
              % (_pf_ids,),
              sorted(_pf_ids.values()) == [0, 0, 0]
              and "title" not in M.PROSE_POSITIONAL.get("scope", "")
              and sorted(M.PROSE_POSITIONAL) == ["add", "add-phase", "bug-add"])
        check("pf9 the class is a TABLE and not four call sites, and what is "
              "OUTSIDE it was measured rather than assumed: `--gate` carries a "
              "COMMAND (`make check ; true` trips the gap shapes and is exactly "
              "right), and the id lists leave an empty element `_split_csv` "
              "already drops. `--descriptive` and `--technical` joined it with "
              "`done`, and they are the same argument as `--reason`: both halves "
              "of a task's `outcome` are the operator's own sentence, one "
              "rendered by every report surface and one quoted back to the next "
              "executor. `--intent-basis` and a note's `--text` are the same "
              "again, and so are a finding's `--issue` and `--resolution` and "
              "a bug's `--repro`, `--expected` and `--actual`, and the why of "
              "a close over its verdict, `--override-verdict`; "
              "`move --to`, `--fix-task` and `--severity` are an id and a word, "
              "and a mute's `--owner`, `--until` and `--bug` a name, a day and "
              "an id, which is why they are not: %r"
              % (sorted(M.PROSE_FLAGS),),
              sorted(M.PROSE_FLAGS)
              == ["actual", "description", "descriptive", "expected",
                  "intent_basis", "issue", "no_evidence_reason", "outcome",
                  "override_verdict", "reason", "rename", "repro", "resolution",
                  "review_outcome", "summary", "technical", "text"]
              and "owner" not in M.PROSE_FLAGS
              and "until" not in M.PROSE_FLAGS
              and "bug" not in M.PROSE_FLAGS
              and "to" not in M.PROSE_FLAGS
              and "fix_task" not in M.PROSE_FLAGS
              and "severity" not in M.PROSE_FLAGS
              and "gate" not in M.PROSE_FLAGS
              and "commit" not in M.PROSE_FLAGS
              and "verified_by" not in M.PROSE_FLAGS
              and M.shell_eaten_gap("make check ; true"))
        _pf_gate = run(["retarget", "P3", "--gate", "make check ; true",
                        "--project-dir", pf_proj])
        check("pf10 ...and that is not theoretical: the same `--gate` value the "
              "gap shapes convict is accepted and written, because a command is "
              "not prose - a table that swept every string flag in would have "
              "refused it: %r"
              % ((_pf_gate[0],
                  [ph.get("testGate")
                   for ph in _mio.load_manifest(pf_mp)["phases"]
                   if ph.get("id") == "P3"]),),
              _pf_gate[0] == 0
              and [ph.get("testGate")
                   for ph in _mio.load_manifest(pf_mp)["phases"]
                   if ph.get("id") == "P3"] == [["make check ; true"]])

        # ---- (vf) a flag a verb does not read is a usage error -----------------
        # ONE PARSER SERVES EVERY VERB. Driven across the grid before the fix,
        # half the (verb, flag) pairs were ACCEPTED, wrote nothing and reported
        # success with exit 0 - `scope --outcome`, `retarget --files`,
        # `add --id`, `add-phase --risk`, `add-phase --files` among them. The
        # gc, ag and qg groups above each fixed one cell of that grid;
        # `--rename` was born ignored by four verbs, which is what makes it a
        # class rather than three incidents.
        import ast
        import re
        # ONE RUNNING TASK IN THE FIXTURE, because `done` is the only verb here
        # whose base call needs a target it can legally close. Without it every
        # `done` row of the grid below would exit 2 for a reason of its own and
        # the stray-flag refusal would be riding on another refusal - which is a
        # row that asserts nothing while looking green.
        _vf_fx = base_manifest()
        _vf_fx["phases"][1]["tasks"].append(
            {"id": "P2.9", "title": "running", "status": "in_progress",
             "attempts": 1, "maxAttempts": 3, "commit": None,
             "startedAt": "2026-01-01T00:00:00Z", "completedAt": None,
             "outcome": {"technical": None, "descriptive": None},
             "verifiedBy": []})
        _VF_SHA = "0123456789abcdef0123456789abcdef01234567"
        vf_proj, vf_mp = mk("vf-flags", _vf_fx)
        # `couple`'s own second-direction row needs a run its own project's
        # evidence ledger actually holds - `_evidence_io.row_by_run`'s answer,
        # never a string the call merely types.
        import _evidence_io as _vf_ev
        _vf_ev.append_row(vf_proj, {
            "v": 1, "runId": "RUN-VF", "ts": "2026-09-01T00:00:00Z",
            "scope": "phase", "phaseId": "P2", "status": "failed", "steps": []})
        with open(vf_mp, "rb") as _fh:
            _vf_before = _fh.read()
        code, txt = run(["add-phase", "Later work", "--outcome", "shipped",
                         "--risk", "high", "--project-dir", vf_proj])
        with open(vf_mp, "rb") as _fh:
            _vf_after = _fh.read()
        check("vf1 a flag passed to a verb that does not read it exits 2 naming "
              "the verb that does - and the manifest is byte identical, which "
              "is the assertion, because the fault was that the call SUCCEEDED "
              "and wrote a phase with no risk on it: %r" % (txt[:200],),
              code == 2 and _vf_after == _vf_before
              and "does not read --risk" in txt
              and "read by: `add`, `scope`" in txt)
        _vf_cells = {}
        for _vfargv, _vfwhat in (
                (["scope", "P2.3", "--outcome", "o"], "scope/--outcome"),
                (["retarget", "P2", "--files", "src/a.ts"],
                 "retarget/--files"),
                (["add", "T", "--phase", "P2", "--id", "P7"], "add/--id"),
                (["add", "T", "--phase", "P2", "--rename", "X"],
                 "add/--rename"),
                (["add-phase", "T", "--outcome", "o", "--files", "src/a.ts"],
                 "add-phase/--files"),
                (["cancel", "P2.3", "--reason", "r", "--gate", "true"],
                 "cancel/--gate")):
            _vf_cells[_vfwhat] = run(_vfargv + ["--project-dir", vf_proj])[0]
        with open(vf_mp, "rb") as _fh:
            _vf_after2 = _fh.read()
        check("vf2 ...and every cell the live sweep found is refused, not only "
              "the one that got reported: each of these exited 0 having written "
              "nothing for the flag, which is indistinguishable from success: %r"
              % (_vf_cells,),
              sorted(_vf_cells.values()) == [2] * 6
              and _vf_after2 == _vf_before)
        # THE WHOLE GRID, counted rather than sampled: a fix driven off six
        # reported cells is a fix for six cells.
        _vf_parser = M.build_parser()
        _vf_opts = M.option_dests(_vf_parser)
        _vf_switch = set(a.dest for a in _vf_parser._actions
                         if a.option_strings and a.nargs == 0)
        _vf_pos = {"add": ["add", "T", "--phase", "P2"],
                   # `signoff` refuses P2's open task, so every stray flag must
                   # bounce BEFORE that refusal - which is what the grid asks.
                   "signoff": ["signoff", "P2", "--verdict", "passed", "--summary", "s"],
                   # `next-id` writes nothing and reads no flag of its own, so its
                   # row is the bare call and every flag must bounce.
                   "next-id": ["next-id", "bug"],
                   "add-phase": ["add-phase", "T", "--outcome", "o"],
                   "cancel": ["cancel", "P2.3", "--reason", "r"],
                   "scope": ["scope", "P2.3", "--files", "src/a.ts"],
                   "retarget": ["retarget", "P2", "--gate", "true"],
                   # `start` reads only `--force` and `--reason`, so its row
                   # here is the bare call and `vf3` drives every other option
                   # against it.
                   "start": ["start", "P2.3"],
                   # ...and `done` on the running task the fixture carries, with
                   # the one flag it requires: a base call that could not close
                   # anything would refuse every row for its own reason.
                   "done": ["done", "P2.9", "--commit", _VF_SHA] + _NOT_ASKED,
                   # `seed` refuses whenever a manifest is already there, which
                   # `vf_proj` is -- but that refusal is `cmd_seed`'s own, and it
                   # fires AFTER the misplaced-flag check this grid drives, so
                   # running it against the shared fixture still proves the
                   # thing vf3 asks about (a title placeholder is all it needs).
                   "seed": ["seed", "T"],
                   # `settle` takes no id and no flag of its own, so its row is
                   # the bare call and every flag must bounce.
                   "settle": ["settle"],
                   # `reopen` on the done task the fixture carries, in its open
                   # phase, with the one flag it requires.
                   "reopen": ["reopen", "P2.1", "--reason", "r"],
                   # `move`, `block` and `note` each on the pending task the
                   # fixture carries, with the one flag each requires.
                   "move": ["move", "P2.3", "--to", "P3"],
                   "block": ["block", "P2.3", "--reason", "r"],
                   "unblock": ["unblock", "P2.3", "--reason", "r"],
                   "note": ["note", "P2.3", "--text", "t"],
                   # `couple`/`uncouple` take no id at all - the misplaced-flag
                   # check this grid drives fires BEFORE either verb's own
                   # body runs, so a bare `--test` is enough to reach it.
                   "couple": ["couple", "--test", "src/a.ts"],
                   "uncouple": ["uncouple", "--test", "src/a.ts"],
                   # The three review verbs each with the flags their door
                   # requires, so a stray flag is what the call bounces on.
                   "finding": ["finding", "P2", "--severity", "low",
                               "--file", "src/a.ts", "--issue", "i",
                               "--resolution", "r"],
                   "resolve-finding": ["resolve-finding", "P2-R1",
                                       "--fix-task", "P2.1"],
                   "correct": ["correct", "P2", "--summary", "s"],
                   # `bug-add` with the answers its door requires; `mute` and
                   # `unmute` take no id, so `--test` alone reaches the
                   # misplaced-flag check, which fires before either body.
                   "bug-add": ["bug-add", "T", "--severity", "low",
                               "--description", "d"],
                   "mute": ["mute", "--test", "tests/test_vf.py"],
                   "unmute": ["unmute", "--test", "tests/test_vf.py"],
                   # `file-return` with its one flag; the misplaced-flag check
                   # fires before the door reads stdin.
                   "file-return": ["file-return", "P2.9", "--role",
                                   "executor"]}
        _vf_leaks = []
        for _vfv in sorted(M.VERB_FLAGS):
            _vfknown = set(M.VERB_FLAGS[_vfv]) | set(M.UNIVERSAL_FLAGS)
            for _vfd in sorted(_vf_opts):
                if _vfd in _vfknown:
                    continue
                _vfargv = list(_vf_pos[_vfv]) + [_vf_opts[_vfd]]
                if _vfd not in _vf_switch:
                    _vfargv.append("x")
                if run(_vfargv + ["--project-dir", vf_proj])[0] != 2:
                    _vf_leaks.append((_vfv, _vf_opts[_vfd]))
        with open(vf_mp, "rb") as _fh:
            _vf_after3 = _fh.read()
        check("vf3 ...and the WHOLE grid: every flag no verb of this parser "
              "reads exits 2 on that verb, and not one of those calls wrote a "
              "byte. "
              "Counted over the parser's own option list, so a flag added "
              "tomorrow is inside this case by existing - which is the half "
              "that makes `--rename`'s birth defect impossible to repeat: %r"
              % (_vf_leaks,),
              _vf_leaks == [] and _vf_after3 == _vf_before)
        # SECOND-DIRECTION CASES. A refusal that fires on a flag the verb DOES
        # read is a refusal somebody routes around inside a day, and the
        # universal flags are the ones every verb has to keep taking.
        #
        # `seed` needs its OWN project for this half, and not `vf_proj`: every
        # other verb's row below relies on a manifest already being there, and
        # `seed` refuses for exactly that reason. Its actual work -- writing
        # where nothing exists yet -- can only be shown on a project none of
        # the other rows has touched.
        _vf_seed_proj, _vf_seed_mp = mk_empty("vf-seed")
        _vf_ok = {}
        for _vfargv, _vfwhat in (
                (["add", "Files ok", "--phase", "P2", "--files", "src/a.ts"],
                 "add/--files"),
                (["add-phase", "Gate ok", "--outcome", "o", "--gate", "true"],
                 "add-phase/--gate"),
                (["retarget", "P3", "--outcome", "restated"],
                 "retarget/--outcome"),
                (["scope", "P2.3", "--files", "src/a.ts", "--json"],
                 "scope/--json"),
                # `start` on a ready task with a universal flag: the flags it
                # reads are driven by the `pr` group, which owns their door.
                (["start", "P2.3", "--json"], "start/--json"),
                # `done` reads four flags of its own AND the universal ones, and
                # this is the call that proves the refusal above did not widen
                # onto them: the close really happens, which the grid's byte
                # compare could never show.
                (["done", "P2.9", "--commit", _VF_SHA,
                  "--descriptive", "impact", "--technical", "what was done",
                  "--verified-by", "t_one,t_two", "--json"] + _NOT_ASKED,
                 "done/--commit"),
                (["cancel", "P3", "--reason", "dropped", "--json"],
                 "cancel/--json"),
                (["next-id", "bug", "--json"], "next-id/--json"),
                (["couple", "--test", "tests/test_vf.py",
                  "--sources", "src/a.ts", "--basis-run", "RUN-VF",
                  "--basis-head", "deadbeef", "--json"],
                 "couple/--sources"),
                (["uncouple", "--test", "tests/test_vf.py",
                  "--json"], "uncouple/--test")):
            _vf_ok[_vfwhat] = run(_vfargv + ["--project-dir", vf_proj])[0]
        # `signoff` against a project whose P2 is finished, because on `vf_proj`
        # P2 still has open work and the verb rightly refuses it.
        _vf_sign = base_manifest()
        _vf_sign["phases"][1]["tasks"][1]["status"] = "done"
        _vf_sign_proj, _vf_sign_mp = mk("vf-sign", _vf_sign)
        _vf_ok["signoff/--verdict"] = run(
            ["signoff", "P2", "--verdict", "passed", "--summary", "s",
             "--review-outcome", "r", "--no-evidence-reason", "fixture",
             "--json", "--project-dir", _vf_sign_proj])[0]
        # `seed` alone, against its own empty project rather than `vf_proj`
        # every row above shares -- see `_vf_seed_proj`'s comment.
        _vf_ok["seed/--gate"] = run(
            ["seed", "Bootstrap ok", "--gate", "true",
             "--project-dir", _vf_seed_proj])[0]
        # `settle` against its own project, because it writes whatever the plan
        # carries stale and `vf_proj` is shared by every row above.
        _vf_settle_proj, _vf_settle_mp = mk("vf-settle", base_manifest())
        _vf_ok["settle/--json"] = run(
            ["settle", "--json", "--project-dir", _vf_settle_proj])[0]
        _vf_reopen_proj, _vf_reopen_mp = mk("vf-reopen", base_manifest())
        _vf_ok["reopen/--reason"] = run(
            ["reopen", "P2.1", "--reason", "r", "--json",
             "--project-dir", _vf_reopen_proj])[0]
        # `move`, `block` and `note` each against a project of their own, since
        # each changes the task the next would act on.
        for _vfargv, _vfwhat in (
                (["move", "P2.3", "--to", "P3", "--json"], "move/--to"),
                (["block", "P2.3", "--reason", "r", "--json"], "block/--reason"),
                (["note", "P2.3", "--text", "t", "--json"], "note/--text")):
            _vf_own_proj, _vf_own_mp = mk("vf-%s" % _vfargv[0], base_manifest())
            _vf_ok[_vfwhat] = run(_vfargv + ["--project-dir", _vf_own_proj])[0]
        # The review verbs against a phase in sign-off: `finding` appends, then
        # `resolve-finding` settles it with the commit P2.1 is given here, and
        # `correct` rewrites the text once `signoff` has recorded a verdict.
        _vf_rv = base_manifest()
        _vf_rv["phases"][1]["tasks"][1]["status"] = "done"
        _vf_rv_proj, _vf_rv_mp = mk("vf-review", _vf_rv)
        _vf_ok["finding/--severity"] = run(
            ["finding", "P2", "--severity", "med", "--file", "src/a.ts",
             "--issue", "i", "--resolution", "r", "--json",
             "--project-dir", _vf_rv_proj])[0]
        _vf_ok["resolve-finding/--fix-task"] = run(
            ["resolve-finding", "P2-R1", "--fix-task", "P2.1",
             "--commit", _VF_SHA, "--json", "--project-dir", _vf_rv_proj])[0]
        run(["signoff", "P2", "--verdict", "skipped", "--summary", "s",
             "--project-dir", _vf_rv_proj])
        _vf_ok["correct/--summary"] = run(
            ["correct", "P2", "--summary", "restated", "--review-outcome", "o",
             "--json", "--project-dir", _vf_rv_proj])[0]
        # `done`'s no-change close reads `--no-change` and `--reason`, the half of
        # its row the close with a commit above does not reach.
        _vf_nc = base_manifest()
        _vf_nc["phases"][1]["tasks"][1].update(status="in_progress", attempts=1)
        _vf_nc_proj, _vf_nc_mp = mk("vf-nochange", _vf_nc)
        _vf_ok["done/--no-change"] = run(
            ["done", "P2.3", "--no-change", "--reason", "nothing to change",
             "--intent", "not-asked", "--intent-basis", "no diff to review",
             "--json", "--project-dir", _vf_nc_proj])[0]
        # `file-return` on a started task of its own project, its return on
        # stdin - the one input it takes that is not a flag.
        _vf_fr = base_manifest()
        _vf_fr["phases"][1]["tasks"][1].update(
            status="in_progress", attempts=1, startedAt="2026-01-01T00:00:00Z")
        _vf_fr_proj, _vf_fr_mp = mk("vf-file-return", _vf_fr)
        _vf_ok["file-return/--role"] = run_on_stdin(
            ["file-return", "P2.3", "--role", "executor", "--json",
             "--project-dir", _vf_fr_proj], _fr_executor())[0]
        # `bug-add`, `mute` and `unmute` in that order on one project: the
        # bug the first files is the one the mute names, and the unmute lifts
        # that mute. Every flag each row declares is passed.
        _vf_mu_proj, _vf_mu_mp = mk("vf-mute", base_manifest())
        _vf_ok["bug-add/--repro"] = run(
            ["bug-add", "T", "--severity", "low", "--description", "d",
             "--files", "src/a.ts", "--repro", "r", "--expected", "e",
             "--actual", "a", "--json", "--project-dir", _vf_mu_proj])[0]
        _vf_ok["mute/--bug"] = run(
            ["mute", "--test", "tests/test_vf.py", "--reason", "r",
             "--owner", "o", "--until", "2998-01-01", "--bug", "BUG-1",
             "--json", "--project-dir", _vf_mu_proj])[0]
        _vf_ok["unmute/--test"] = run(
            ["unmute", "--test", "tests/test_vf.py", "--json",
             "--project-dir", _vf_mu_proj])[0]
        # `unblock` reads `--reason`, on a task whose attempts are spent.
        _vf_ub = base_manifest()
        _vf_ub["phases"][1]["tasks"][1].update(status="blocked", attempts=3,
                                              maxAttempts=3)
        _vf_ub_proj, _vf_ub_mp = mk("vf-unblock", _vf_ub)
        _vf_ok["unblock/--reason"] = run(
            ["unblock", "P2.3", "--reason", "the human says again", "--json",
             "--project-dir", _vf_ub_proj])[0]
        check("vf4 SECOND-DIRECTION CASE: every flag a verb DOES read still "
              "works, and `--json` / `--project-dir` reach every verb - a guard "
              "that fires on a correct call is a guard somebody routes around "
              "inside the day - and the verbs covered are DERIVED off the table, "
              "so a verb added with no second-direction case is red rather than "
              "silently uncovered: %r" % (_vf_ok,),
              _vf_ok != {} and sorted(set(_vf_ok.values())) == [0]
              and sorted(set(w.split("/")[0] for w in _vf_ok))
              == sorted(M.VERB_FLAGS))
        _vf_empty = run(["cancel", "P2.3", "--reason", "r", "--description",
                         "", "--project-dir", vf_proj])[0]
        check("vf5 ...and the census reads ARGV rather than the namespace: "
              "`--description \"\"` holds the parser's own default, so a check "
              "comparing values could not tell it from a flag nobody passed - "
              "which is the half of a flag that is ignored MOST quietly: %r"
              % (_vf_empty,), _vf_empty == 2)
        # THE TABLE, GRADED AGAINST THE REAL DISPATCH. A hand-written table
        # nothing compares to the code is the same defect one level up: the qg
        # group's entry says a row added to `test__refs.py`'s writer table
        # stayed green with the flag's read DELETED, which is a check
        # asserting nothing.
        with open(os.path.join(_output.SCRIPTS_DIR, "manifest",
                               "audit-task.py"), "r", encoding="utf-8") as _fh:
            _vf_src = _fh.read()
        _vf_tree = ast.parse(_vf_src)
        _vf_defs = dict((n.name, n) for n in _vf_tree.body
                        if isinstance(n, ast.FunctionDef))

        def vf_doors(tree):
            """{verb: door function} off `main`'s own `doors` map.

            DERIVED AND NOT LISTED. The roots of the walk below are the
            functions the dispatch actually reaches, and a list of them kept
            here would be one more description of the verb set - which is the
            failure `test__refs.py`'s `_AT_WRITERS` records paying for.
            """
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign) \
                        or not isinstance(node.value, ast.Dict):
                    continue
                if "doors" not in [t.id for t in node.targets
                                   if isinstance(t, ast.Name)]:
                    continue
                return dict(
                    (k.value, v.id)
                    for k, v in zip(node.value.keys, node.value.values)
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Name))
            return {}

        def vf_reads(node):
            """The `args.<attr>` a function reads, dotted or through `getattr`.

            Off the AST and never a text search: `test__refs.py`'s `pf1` was a
            grep once, and the comment explaining that very repair contained
            the dest it looked for - so with the read deleted the check stayed
            green on the comment alone.
            """
            found = set()
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Attribute)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "args"):
                    found.add(sub.attr)
                elif (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name)
                        and sub.func.id == "getattr"
                        and len(sub.args) >= 2
                        and isinstance(sub.args[0], ast.Name)
                        and sub.args[0].id == "args"
                        and isinstance(sub.args[1], ast.Constant)
                        and isinstance(sub.args[1].value, str)):
                    found.add(sub.args[1].value)
            return found

        def vf_closure(root):
            """(dests, functions) reachable from `root` through this module.

            THE CLOSURE IS THE POINT. A verb's flags are read across its door,
            the body under the lock, and the payload builders - and the lambda
            `_under_lock` is handed sits INSIDE the door, so walking the door's
            whole subtree finds the `_locked_*` call without the walk having to
            know that `_under_lock` calls its argument.
            """
            seen, todo, dests = set(), [root], set()
            while todo:
                name = todo.pop()
                if name in seen or name not in _vf_defs:
                    continue
                seen.add(name)
                dests |= vf_reads(_vf_defs[name])
                todo.extend(sub.func.id for sub in ast.walk(_vf_defs[name])
                            if isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Name)
                            and sub.func.id in _vf_defs)
            return dests, seen

        _vf_map = vf_doors(_vf_tree)
        _vf_derived = dict((v, vf_closure(d)[0] & set(_vf_opts))
                           for v, d in _vf_map.items())
        _vf_declared = dict((v, set(M.VERB_FLAGS.get(v) or ())
                             | set(M.UNIVERSAL_FLAGS)) for v in _vf_map)
        _vf_off = dict((v, (sorted(_vf_declared[v] - _vf_derived[v]),
                            sorted(_vf_derived[v] - _vf_declared[v])))
                       for v in _vf_map
                       if _vf_declared[v] != _vf_derived[v])
        check("vf6 `VERB_FLAGS` is the set each verb's dispatch REALLY reads, "
              "derived by walking this file's own call graph from `main`'s "
              "`doors` map - equality and not a subset, because a table that "
              "over-claims refuses a working call and one that under-claims is "
              "the very defect this group exists to catch, back: %r" % (_vf_off,), _vf_off == {})
        # THE VACUITY GUARD, and it is the half that matters: an empty door map,
        # a renamed function or an option list that failed to resolve all leave
        # vf6 green over nothing at all.
        _vf_choices = sorted(a.choices or [] for a in _vf_parser._actions
                             if a.dest == "command")
        _vf_unresolved = sorted(d for d in _vf_map.values()
                                if d not in _vf_defs)
        check("vf7 ...over a door map, a call graph and an option list that all "
              "actually resolved: the parser's own verb list, every door found "
              "in the AST, and "
              "each derived set non-empty. `add` reaching `_build_task` and "
              "`retarget` reaching `--rename` are named because those are the "
              "two edges the closure exists for: %r"
              % ((sorted(_vf_map), _vf_unresolved,
                  sorted(_vf_derived.get("retarget") or [])),),
              sorted(_vf_map) == sorted(M.VERB_FLAGS)
              and _vf_choices and sorted(_vf_choices[0]) == sorted(M.VERB_FLAGS)
              and _vf_unresolved == []
              and all(_vf_derived[v] for v in _vf_derived)
              and "_build_task" in vf_closure(_vf_map["add"])[1]
              and "rename" in _vf_derived["retarget"])
        check("vf7b ...and `readers_of` answers for a UNIVERSAL flag as well as "
              "a per-verb one - the branch a misplaced flag can never reach, "
              "because a universal one is never stray, and therefore the branch "
              "nothing else here would run: %r"
              % ((M.readers_of("as_json"), M.readers_of("outcome"),
                  M.readers_of("nonesuch")),),
              M.readers_of("as_json") == sorted(M.VERB_FLAGS)
              and M.readers_of("outcome") == ["add-phase", "retarget"]
              and M.readers_of("nonesuch") == [])
        # THE DEFENSIVE BRANCH, driven through its only door. `main` cannot
        # reach it: the probe re-parses an argv the real parser has already
        # accepted, so the one shape it rejects is one `main`'s own parse
        # (`parse_intermixed_args`) rejects
        # first and `main` returns before calling this. Called directly it is
        # reachable, and what it must NOT do is return an empty set - which
        # reads as "no flags were passed" and lets every misplaced flag through.
        with open(os.devnull, "w") as _vf_null, \
                contextlib.redirect_stderr(_vf_null):
            _vf_none = M.supplied_flags(["add", "T", "--gate", "--json"])
            _vf_some = M.supplied_flags(["add", "T", "--json"])
        check("vf9 `supplied_flags` answers None - never an empty set - on an "
              "argv it cannot parse, and the distinction is the whole point: "
              "empty would read as 'nothing was passed', which is exactly the "
              "answer that lets a misplaced flag through. `main` refuses on it "
              "rather than writing on an unchecked call: %r"
              % ((_vf_none, sorted(_vf_some or [])),),
              _vf_none is None and _vf_some == set(["as_json"]))
        # THE DOCS' OWN EXAMPLES, GRADED AGAINST THE TABLE. `commands/phase.md`
        # said "a pair like `add --risk` ... exits 2 now", and driven,
        # `/audit:task add --risk high` exits 0 and writes `risk: high` - the
        # refused pair is `/audit:phase add --risk`. Correcting the sentence buys
        # one green day; what stops the next one is reading the pairs out of the
        # prose and asking the table.
        #
        # SENTENCE-SCOPED, because the trigger word is what marks a pair as
        # claimed-refused: the same two docs also cite pairs that are CORRECT
        # (`/audit:task add --risk high`), and a check that graded every pair it
        # found would demand they be refused.
        _vf_trigger = re.compile(r"refus|exit 2|does not read")
        _vf_pair = re.compile(r"`(/audit:(?:task|phase) )?([a-z][a-z-]*) "
                              r"(--[a-z][a-z-]*)")
        # `add` NAMES TWO DIFFERENT VERBS, and that ambiguity IS the bug: the
        # script's `add-phase` is spelled `add` under `/audit:phase` and its
        # `add` is spelled `add` under `/audit:task`. So a bare `add --flag` in
        # a refusing sentence is REPORTED as needing qualification rather than
        # resolved by a per-document guess - a guess is what read the wrong
        # verb in the first place, and a default nothing exercises is a branch
        # this suite cannot prove either way.
        _vf_docs = ("commands/phase.md", "commands/task.md")
        _vf_claimed, _vf_wrong, _vf_vague = [], [], []
        for _vfrel in _vf_docs:
            with open(os.path.join(_output.PLUGIN_ROOT, *_vfrel.split("/")),
                      "r", encoding="utf-8") as _fh:
                _vfbody = _fh.read()
            for _vfsent in re.split(r"(?<=[.;])\s", _vfbody):
                if not _vf_trigger.search(_vfsent):
                    continue
                for _vfq, _vfverb, _vfflag in _vf_pair.findall(_vfsent):
                    _vfd = [d for d, f in _vf_opts.items() if f == _vfflag]
                    if not _vfd:
                        continue
                    if _vfverb == "add" and not _vfq:
                        _vf_vague.append((_vfrel, _vfverb, _vfflag))
                        continue
                    if _vfq and "phase" in _vfq and _vfverb == "add":
                        _vfverb = "add-phase"
                    if _vfverb not in M.VERB_FLAGS:
                        continue
                    _vf_claimed.append((_vfrel, _vfverb, _vfflag))
                    if _vfd[0] in (set(M.VERB_FLAGS[_vfverb])
                                   | set(M.UNIVERSAL_FLAGS)):
                        _vf_wrong.append((_vfrel, _vfverb, _vfflag))
        check("vf10 every (verb, flag) pair the two command docs cite in a "
              "sentence about REFUSING is one the verb really does not read - "
              "`phase.md` claimed `add --risk` exits 2 while `/audit:task add "
              "--risk high` exits 0 and writes it, which is a false and "
              "testable claim in a user-facing doc: %r" % (_vf_wrong,),
              _vf_wrong == [])
        check("vf10b ...over pairs it actually FOUND, which is the half that "
              "matters: an empty set of citations satisfies vf10 while checking "
              "nothing, and `/audit:phase add --risk` is named because that is "
              "the pair the false sentence got backwards: %r"
              % (sorted(_vf_claimed),),
              len(_vf_claimed) >= 2
              and ("commands/phase.md", "add-phase", "--risk") in _vf_claimed)
        check("vf10c ...and a BARE `add --flag` in such a sentence is reported "
              "rather than resolved: `add` names `/audit:phase add` in one doc "
              "and `/audit:task add` in the other, so guessing which is what "
              "read the wrong verb to begin with. Both docs qualify it today, "
              "which is why this is empty: %r" % (_vf_vague,),
              _vf_vague == [])
        _vf_common = set.intersection(*[_vf_derived[v] for v in _vf_derived])
        check("vf8 ...and `UNIVERSAL_FLAGS` is EXACTLY the intersection of the "
              "derived sets, so a flag that becomes universal cannot stay "
              "listed per verb and one that stops being universal cannot stay "
              "here - the table's own vocabulary is derived too: %r"
              % (sorted(_vf_common),),
              _vf_common == set(M.UNIVERSAL_FLAGS))

        # ---- (pr) `start`: the promotion the plan gate reads ------------------
        # THE DEFECT, driven: `add` writes `status: "pending"`, and
        # `hooks/_config.in_progress_task_map` - what `require-plan.py` resolves
        # an allowed path through - skips every task that is not `in_progress`,
        # its `fileIndex` arm included (that arm only re-adds paths for ids
        # already in the filtered set). So a task added to a phase that is
        # ALREADY RUNNING is born with its own declared files denied on the
        # first Edit, and the only promotions were `/audit:run`, which promotes
        # AND spawns, and a hand edit. A field report measured two executors
        # returning zero edits, each having spent a subagent's budget, both
        # refused on a path their task's `files` declared.
        #
        # THE MAP IS ASKED HERE RATHER THAN ASSERTED ABOUT. Reading the task
        # back out of the manifest proves the three fields were written; it
        # proves nothing about the hook, and the hook is the reason the verb
        # exists. So this group imports the gate's own resolver and asks it the
        # question the denial asks - before, and after.
        import _config as _pr_cfg
        _PR_REL = "docs/audit/audit-plan.json"

        def pr_map(proj):
            return _pr_cfg.in_progress_task_map(proj, _PR_REL)

        def pr_fixture():
            fx = base_manifest()
            # P2.3 IS GIVEN A FILE ON PURPOSE. It is the OTHER pending task in
            # the same running phase, and without a path of its own `pr3` could
            # not tell the per-task promotion from the rejected widening: a map
            # taught to read `pending` opens whatever the pending tasks declare,
            # and a task declaring nothing exposes nothing either way.
            fx["phases"][1]["tasks"][1]["files"] = ["src/pending.ts"]
            fx["fileIndex"]["src/pending.ts"] = ["P2.3"]
            fx["phases"][1]["tasks"].append(
                {"id": "P2.4", "title": "fresh", "status": "pending",
                 "description": "", "files": ["src/fresh.ts"],
                 "tests": {"mode": "gate-only", "add": [], "expectRedFirst": False,
                           "gate": ["test"]},
                 "model": "sonnet", "skills": [], "risk": "low",
                 "blockedBy": [], "dependsOn": [], "attempts": 0,
                 "maxAttempts": 3, "commit": None,
                 "outcome": {"technical": None, "descriptive": None},
                 "startedAt": None, "completedAt": None, "verifiedBy": []})
            fx["fileIndex"]["src/fresh.ts"] = ["P2.4"]
            return fx

        projpr, mppr = mk("st-start", pr_fixture())
        _pr_before_map = pr_map(projpr)
        code, txt = run(["start", "P2.4", "--project-dir", projpr])
        _pr_after_map = pr_map(projpr)
        tpr = task_in(mppr, "P2.4")
        check("pr1 a pending task in a RUNNING phase is promoted: the fields "
              "are `reference/orchestrator.md` step 2's, and nothing else on "
              "the task moved - %r"
              % ((code, tpr.get("status"), tpr.get("attempts"),
                  bool(tpr.get("startedAt"))),),
              code == 0 and tpr.get("status") == "in_progress"
              and tpr.get("attempts") == 1
              and isinstance(tpr.get("startedAt"), str)
              and tpr.get("startedAt").endswith("Z")
              and tpr.get("completedAt") is None
              and tpr.get("files") == ["src/fresh.ts"])
        check("pr2 THE DEFECT, asked of the gate's own resolver rather than of "
              "the manifest: `src/fresh.ts` is a path the task DECLARES, and "
              "`in_progress_task_map` did not resolve it before the promotion "
              "and does after. This is what the two zero-edit executors were "
              "denied on: before=%r after=%r"
              % (_pr_before_map.get("src/fresh.ts"),
                 _pr_after_map.get("src/fresh.ts")),
              "src/fresh.ts" not in _pr_before_map
              and _pr_after_map.get("src/fresh.ts")
              == [{"taskId": "P2.4", "testsMode": "gate-only"}])
        check("pr3 SECOND-DIRECTION CASE: the promotion is PER TASK, which is "
              "the whole reason `in_progress_task_map` was not widened to read "
              "`pending` instead. P2.3 declares `src/pending.ts` and is pending "
              "in the same running phase, and that path is STILL unresolved "
              "after this call - a map that had been widened would have opened "
              "it in the same move: %r" % (sorted(_pr_after_map),),
              sorted(_pr_after_map) == ["src/fresh.ts"])

        check("pr3b SECOND-DIRECTION CASE: a phase that is ALREADY running is "
              "not re-promoted and not re-stamped - `healed` comes back empty, "
              "so the report and the trail say nothing about a transition that "
              "did not happen: %r"
              % (("phase " in txt,
                  [p for p in _mio.load_manifest(mppr)["phases"]
                   if p["id"] == "P2"][0].get("startedAt")),),
              "phase P2 status" not in txt
              and "startedAt" not in [p for p in
                                      _mio.load_manifest(mppr)["phases"]
                                      if p["id"] == "P2"][0])

        # THE PHASE HAS A VERB NOW. Until this, the control surface's save was
        # the ONLY site in the tree that moved a phase out of `pending`, so an
        # orchestrator driving a plan from the command line left every phase
        # pending for its whole life -- and a phase carried no start time at
        # all. The fixture puts the task in the PENDING phase, which is what the
        # blocks above never do.
        _pr_pend = pr_fixture()
        _pr_pend["phases"][2]["tasks"] = [
            {"id": "P3.1", "title": "first", "status": "pending",
             "description": "", "files": ["src/parked.ts"],
             "tests": {"mode": "gate-only", "add": [], "expectRedFirst": False,
                       "gate": []},
             "model": "sonnet", "skills": [], "risk": "low",
             "blockedBy": [], "dependsOn": [], "attempts": 0,
             "maxAttempts": 3, "commit": None,
             "outcome": {"technical": None, "descriptive": None},
             "startedAt": None, "completedAt": None, "verifiedBy": []}]
        _pr_pend["fileIndex"]["src/parked.ts"] = ["P3.1"]
        projph, mpph = mk("st-phase-start", _pr_pend)
        _pr_ph_code, _pr_ph_txt = run(["start", "P3.1",
                                       "--project-dir", projph])
        _pr_phase = [p for p in _mio.load_manifest(mpph)["phases"]
                     if p["id"] == "P3"][0]
        check("pr3c a start inside a PENDING phase promotes the phase in the "
              "same write and STAMPS it: the record a command-line run was "
              "losing is the moment the phase began, which had no field to sit "
              "in and no writer to put one there: %r"
              % ((_pr_ph_code, _pr_phase.get("status"),
                  _pr_phase.get("startedAt")),),
              _pr_ph_code == 0 and _pr_phase.get("status") == "in_progress"
              and isinstance(_pr_phase.get("startedAt"), str)
              and _pr_phase["startedAt"].endswith("Z"))
        check("pr3d ...from the SAME instant as the task it started for, "
              "rather than from a second clock reading: two records of one "
              "promotion that disagree by a second are two records nobody can "
              "line up: %r" % ((_pr_phase.get("startedAt"),
                                (task_in(mpph, "P3.1") or {}).get(
                                    "startedAt")),),
              _pr_phase.get("startedAt")
              == (task_in(mpph, "P3.1") or {}).get("startedAt"))
        check("pr3e ...and both surfaces report it: the terminal names the "
              "field that moved rather than announcing a promotion, since two "
              "fields move and only one of them is a status: %r"
              % (_pr_ph_txt[-260:],),
              "phase P3 status: pending -> in_progress" in _pr_ph_txt
              and "phase P3 startedAt" in _pr_ph_txt)
        _pr_ph_json = json.loads(run(["start", "P3.1", "--project-dir", projph,
                                      "--json"])[1])
        check("pr3f ...and the machine surface carries the rows APART from "
              "`changes`, which is this task's fields - folding them together "
              "would make a consumer join a phase's row on a task id. This "
              "call re-starts an already-running phase, so the list is empty "
              "and the key is still there: %r" % (_pr_ph_json.get("healed"),),
              _pr_ph_json.get("healed") == []
              and all(r["id"] == "P3.1" for r in _pr_ph_json["changes"]))
        _pr_ph_jm = _panel_write._journalmod()
        _pr_ph_rows = [r for r in (_pr_ph_jm.read_all(projph) if _pr_ph_jm
                                   else [])
                       if r.get("action") == "task.start"]
        check("pr3g ...and the trail's summary names the phase the write moved: "
              "a row naming only the task would leave the phase's own start "
              "recorded in the manifest and nowhere in the journal: %r"
              % ([r.get("summary") for r in _pr_ph_rows],),
              any("P3 status: pending -> in_progress"
                  in (r.get("summary") or "") for r in _pr_ph_rows)
              and any("P3 startedAt" in (r.get("summary") or "")
                      for r in _pr_ph_rows))

        # NOT IDEMPOTENT, AND THAT IS THE DECISION. `attempts` counts SPAWNS:
        # step 4 of the orchestrator leaves a task `in_progress` when its gates
        # run red and sends it back through step 2, so a second call IS that
        # retry. A verb that returned 0 having written nothing would freeze the
        # count `blocked` is derived from, and a run could retry for ever while
        # the plan said it had been attempted once.
        code2, txt2 = run(["start", "P2.4", "--project-dir", projpr])
        tpr2 = task_in(mppr, "P2.4")
        check("pr4 a start on a task that is ALREADY in_progress spends an "
              "attempt rather than returning success having written nothing - "
              "and says RE-STARTED, so a double call is visible: %r"
              % ((code2, tpr2.get("attempts"), "RE-STARTED" in txt2),),
              code2 == 0 and tpr2.get("attempts") == 2
              and tpr2.get("status") == "in_progress"
              and "RE-STARTED" in txt2)

        # THE CEILING. Step 2 pairs the increment with "if `task.attempts >
        # (task.maxAttempts or 3)`, do NOT spawn" - a verb writing the increment
        # and dropping that half hands back exit 0 on a task the caller must not
        # spawn. It refuses rather than writing `blocked`, which owes an ADO
        # echo and a human.
        projmx, mpmx = mk("st-ceiling", pr_fixture())
        _pr_climb = [run(["start", "P2.4", "--project-dir", projmx])[0]
                     for _prn in range(3)]
        with open(mpmx, "rb") as _fh:
            _pr_at_ceiling = _fh.read()
        code3, txt3 = run(["start", "P2.4", "--project-dir", projmx])
        with open(mpmx, "rb") as _fh:
            _pr_after_ceiling = _fh.read()
        check("pr5 a start that would take `attempts` PAST `maxAttempts` is "
              "refused, the manifest is byte identical, and the message names "
              "the count, the ceiling and whose move `blocked` is: %r"
              % (txt3[:160],),
              code3 == 2 and _pr_after_ceiling == _pr_at_ceiling
              and "maxAttempts" in txt3 and "blocked" in txt3
              and (task_in(mpmx, "P2.4") or {}).get("attempts") == 3)
        check("pr5b ALLOW CASE, and it is the direction an over-wide guard "
              "breaks: every attempt UP TO the ceiling goes through, so a "
              "comparison off by one would refuse the last retry the plan is "
              "entitled to. The exit codes are kept rather than inferred from "
              "the count, because a refused call and a written one both leave "
              "`attempts` short: %r" % ((_pr_climb,
                                         (task_in(mpmx, "P2.4") or {}).get(
                                             "attempts")),),
              _pr_climb == [0, 0, 0]
              and (task_in(mpmx, "P2.4") or {}).get("attempts") == 3
              and (task_in(mpmx, "P2.4") or {}).get("status") == "in_progress")

        # A ceiling nobody set is not a reason to refuse every start: the
        # template default answers, the way `recorded_attempt` refuses to invent
        # a count but this field has a documented default to fall back on.
        _pr_junk = pr_fixture()
        _pr_junk["phases"][1]["tasks"][-1]["maxAttempts"] = True
        projjk, mpjk = mk("st-ceiling-junk", _pr_junk)
        check("pr6 `maxAttempts: true` is not a ceiling of one - `bool` is an "
              "`int` in Python, and the template default answers for a value "
              "nobody set: %r" % ((M._attempt_ceiling({"maxAttempts": True}),
                                   M._attempt_ceiling({"maxAttempts": 0}),
                                   M._attempt_ceiling({}),
                                   M._attempt_ceiling({"maxAttempts": 7})),),
              run(["start", "P2.4", "--project-dir", projjk])[0] == 0
              and M._attempt_ceiling({"maxAttempts": True}) == 3
              and M._attempt_ceiling({"maxAttempts": 0}) == 3
              and M._attempt_ceiling({}) == 3
              and M._attempt_ceiling({"maxAttempts": 7}) == 7)

        # TERMINAL IS TERMINAL, `_locked_cancel`'s rule one verb over: flipping
        # a finished status back would rewrite history with no record of what it
        # said before, and a `done` task carries a commit graded against the
        # scope it holds.
        projtm, mptm = mk("st-terminal", pr_fixture())
        run(["cancel", "P2.3", "--reason", "dropped", "--project-dir", projtm])
        with open(mptm, "rb") as _fh:
            _pr_tm_before = _fh.read()
        _pr_term = {}
        for _prtid in ("P2.1", "P2.3"):
            _pr_term[_prtid] = run(["start", _prtid, "--project-dir", projtm])
        with open(mptm, "rb") as _fh:
            _pr_tm_after = _fh.read()
        check("pr7 a `done` task and a `cancelled` one are each refused BY "
              "NAME, and neither call wrote a byte: %r"
              % (dict((k, (v[0], v[1][:70])) for k, v in _pr_term.items()),),
              _pr_term["P2.1"][0] == 2 and _pr_term["P2.3"][0] == 2
              and "already done" in _pr_term["P2.1"][1]
              and "already cancelled" in _pr_term["P2.3"][1]
              and _pr_tm_after == _pr_tm_before)
        check("pr8 a PHASE id is refused rather than promoted, and an id that "
              "resolves to nothing says so - the two look alike enough that a "
              "verb guessing between them guesses wrong: %r"
              % ((run(["start", "P2", "--project-dir", projtm])[1][:80],
                  run(["start", "P9.9", "--project-dir", projtm])[1][:60]),),
              run(["start", "P2", "--project-dir", projtm])[0] == 2
              and "PHASE" in run(["start", "P2", "--project-dir", projtm])[1]
              and run(["start", "P9.9", "--project-dir", projtm])[0] == 2
              and run(["start", "", "--project-dir", projtm])[0] == 2)

        # THE ROW. `changes` and `attempt` are keys `_journal_io.DETAILS_KEYS`
        # already carries; a `startedAt` key invented for this writer would be
        # dropped in silence and believed, which is `_journal_phase_add`'s note.
        projjr, mpjr = mk("st-journal", pr_fixture())
        run(["start", "P2.4", "--project-dir", projjr])
        _prjm = _panel_write._journalmod()
        _pr_rows = [r for r in (_prjm.read_all(projjr) if _prjm else [])
                    if r.get("action") == "task.start"]
        _pr_det = (_pr_rows[0].get("details") or {}) if _pr_rows else {}
        check("pr9 the trail carries ONE `task.start` row whose details are "
              "exactly the allow-listed keys the writer means, with the status "
              "it moved FROM - read before the write, because afterwards every "
              "one of them says in_progress: %r" % ((sorted(_pr_det),
                                                     _pr_det.get("changes")),),
              len(_pr_rows) == 1
              and sorted(_pr_det) == ["attempt", "changes", "phaseId", "taskId"]
              and _pr_det.get("attempt") == 1
              and _pr_det.get("taskId") == "P2.4"
              and [c for c in _pr_det["changes"] if c["field"] == "status"]
              == [{"id": "P2.4", "field": "status", "from": "pending",
                   "to": "in_progress"}]
              and [c["field"] for c in _pr_det["changes"]]
              == ["status", "startedAt", "attempts"])
        # THE HANDOVER, NOT THE ROW, and the two are different questions:
        # `_journal_io` drops an unlisted key in SILENCE, so a row read back is
        # identical whether the writer handed over an allow-listed block or one
        # carrying an invented key beside it. `pr9` above cannot see that, and a
        # key written, dropped and believed is the exact failure
        # `_journal_phase_add` records - so the block the writer BUILDS is
        # compared against the allow-list `_journal_io` really holds.
        import _journal_io as _pr_jio
        _pr_hand = M._start_details(
            "P2.4", "P2", {"status": "pending", "attempts": 0,
                           "startedAt": None},
            {"attempts": 1, "status": "in_progress", "startedAt": "Z"})
        check("pr9c ...and every key the WRITER hands over is on "
              "`_journal_io.DETAILS_KEYS`, asked of that module rather than of "
              "the row it produced - an unlisted key is dropped without a word, "
              "so no assertion about the written row can see one: %r"
              % (sorted(_pr_hand),),
              sorted(_pr_hand) == ["attempt", "changes", "phaseId", "taskId"]
              and set(_pr_hand) <= set(_pr_jio.DETAILS_KEYS)
              and all(set(c) <= set(_pr_jio.CHANGE_KEYS) | set(["id"])
                      for c in _pr_hand["changes"]))
        run(["start", "P2.4", "--project-dir", projjr])
        _pr_rows2 = [r for r in (_prjm.read_all(projjr) if _prjm else [])
                     if r.get("action") == "task.start"]
        check("pr9b ...and a RE-START says so in the SUMMARY, because "
              "`audit-journal list` prints the summary and nothing else - a "
              "retry that read like a first start would have to be told apart "
              "by opening `details`: %r"
              % ([r.get("summary") for r in _pr_rows2],),
              len(_pr_rows2) == 2
              and "RE-STARTED" in (_pr_rows2[1].get("summary") or "")
              and "RE-STARTED" not in (_pr_rows2[0].get("summary") or ""))

        # READINESS IS REFUSED, AND `--force --reason` IS THE RECORDED
        # EXCEPTION. A start that only REPORTED what a task waited on made
        # readiness a rule the model followed or did not, and nothing in the plan
        # could tell which. The refusal reads `_status_facts.unmet_refs` and not a
        # second copy of the rule, so the expected lists below are asked of that
        # function AND written out by hand: the hand list is what keeps a case
        # from going vacuous if the function ever answered `[]` for everything.
        def pr_rows(proj):
            jm = _panel_write._journalmod()
            return [r for r in (jm.read_all(proj) if jm else [])
                    if r.get("action") == "task.start"]

        def pr_unmet(mp, tid):
            return M._status_facts.unmet_refs(_mio.load_manifest(mp)).get(tid)

        # Two fixtures, one per place a reference can sit: the task's OWN
        # `blockedBy` and `dependsOn` (P2.4 waits on a pending phase and a pending
        # task), and the owning PHASE's `blockedBy` (P3 waits on the running P2,
        # so its task inherits the wait and `unmet_refs` spells it `(phase)`).
        _pr_own = pr_fixture()
        _pr_own["phases"][1]["tasks"][-1]["blockedBy"] = ["P3"]
        _pr_own["phases"][1]["tasks"][-1]["dependsOn"] = ["P2.3"]
        _pr_phb = pr_fixture()
        _pr_phb["phases"][2]["blockedBy"] = ["P2"]
        _pr_phb["phases"][2]["tasks"] = [dict(_pr_pend["phases"][2]["tasks"][0])]
        _pr_phb["fileIndex"]["src/parked.ts"] = ["P3.1"]
        _pr_waits = (("own", _pr_own, "P2.4", ["P3", "P2.3"]),
                     ("phase", _pr_phb, "P3.1", ["P2 (phase)"]))
        _pr_refused = {}
        for _prk, _prfx, _prtid, _prwant in _pr_waits:
            _prproj, _prmp = mk("st-unready-" + _prk, _prfx)
            with open(_prmp, "rb") as _fh:
                _prb = _fh.read()
            _prc, _prt = run(["start", _prtid, "--project-dir", _prproj])
            with open(_prmp, "rb") as _fh:
                _pra = _fh.read()
            _pr_refused[_prk] = (_prc, _prt, pr_unmet(_prmp, _prtid), _prwant,
                                 _pra == _prb, len(pr_rows(_prproj)))
        check("pr10 a start on a pending task whose own `blockedBy`/`dependsOn` "
              "or whose phase's `blockedBy` is unmet is REFUSED: exit 2, the "
              "manifest byte identical, no `task.start` row, and the message "
              "names every unmet reference exactly as `unmet_refs` spells it: %r"
              % (dict((k, (v[0], v[2], v[1][:140])) for k, v in
                      _pr_refused.items()),),
              all(v[0] == 2 and v[4] and v[5] == 0
                  and sorted(v[2] or []) == sorted(v[3])
                  and all(ref in v[1] for ref in v[3])
                  and "--force" in v[1]
                  for v in _pr_refused.values()))
        _prjproj, _prjmp = mk("st-unready-json", _pr_own)
        _prjc, _prjt = run(["start", "P2.4", "--project-dir", _prjproj, "--json"])
        _prjo = {}
        try:
            _prjo = json.loads(_prjt)
        except ValueError:
            pass
        check("pr10b ...and under --json the refusal is one object a caller can "
              "parse, still naming what the task waits on: %r" % (_prjo,),
              _prjc == 2 and _prjo.get("ok") is False
              and "P2.3" in (_prjo.get("refused") or "")
              and (task_in(_prjmp, "P2.4") or {}).get("status") == "pending")
        # THE DOOR'S OTHER HALF: `--force` with no reason is an exception nobody
        # can read back, so it is refused before anything is written, and a
        # `--reason` with no `--force` is a why with nothing it explains.
        _prdproj, _prdmp = mk("st-unready-door", _pr_own)
        with open(_prdmp, "rb") as _fh:
            _prdb = _fh.read()
        _prd = [run(["start", "P2.4", "--force", "--project-dir", _prdproj]),
                run(["start", "P2.4", "--reason", "why",
                     "--project-dir", _prdproj])]
        with open(_prdmp, "rb") as _fh:
            _prda = _fh.read()
        check("pr10c `--force` alone and `--reason` alone are each refused with "
              "exit 2 and no byte written, so a forced start always carries the "
              "reason its row records: %r" % ([(c, t[:100]) for c, t in _prd],),
              [c for c, _t in _prd] == [2, 2] and _prda == _prdb
              and pr_rows(_prdproj) == []
              and "--reason" in _prd[0][1] and "--force" in _prd[1][1])

        _pr_forced = {}
        for _prk, _prfx, _prtid, _prwant in _pr_waits:
            _prproj, _prmp = mk("st-forced-" + _prk, _prfx)
            _prc, _prt = run(["start", _prtid, "--force", "--reason",
                              "hand start for the plan gate",
                              "--project-dir", _prproj])
            _prr = pr_rows(_prproj)
            _prdet = (_prr[0].get("details") or {}) if _prr else {}
            _pr_forced[_prk] = (_prc, (task_in(_prmp, _prtid) or {}).get("status"),
                                len(_prr), _prdet, _prwant,
                                (_prr[0].get("summary") or "") if _prr else "", _prt)
        check("pr11 `--force --reason` on the same tasks starts them, and the "
              "one `task.start` row records the exception: `mode: forced`, the "
              "reason verbatim, and every unmet reference in its basis and its "
              "summary: %r"
              % (dict((k, (v[0], v[1], v[3].get("mode"), v[3].get("reason"),
                           v[3].get("basis"))) for k, v in _pr_forced.items()),),
              all(v[0] == 0 and v[1] == "in_progress" and v[2] == 1
                  and v[3].get("mode") == "forced"
                  and v[3].get("reason") == "hand start for the plan gate"
                  and all(ref in (v[3].get("basis") or "") for ref in v[4])
                  and "FORCED" in v[5] and all(ref in v[5] for ref in v[4])
                  and "FORCED" in v[6]
                  for v in _pr_forced.values()))
        _prfproj, _prfmp = mk("st-forced-json", _pr_own)
        _prfc, _prft = run(["start", "P2.4", "--force", "--reason", "r",
                            "--project-dir", _prfproj, "--json"])
        _prfo = {}
        try:
            _prfo = json.loads(_prft)
        except ValueError:
            pass
        check("pr11b ...and the --json block carries the same facts as DATA: "
              "`forced` true, the reason, and the references it was forced past: "
              "%r" % (dict((k, _prfo.get(k)) for k in
                           ("ok", "forced", "forcedReason", "waitingOn",
                            "ready")),),
              _prfc == 0 and _prfo.get("ok") is True
              and _prfo.get("forced") is True
              and _prfo.get("forcedReason") == "r"
              and sorted(_prfo.get("waitingOn") or []) == ["P2.3", "P3"]
              and _prfo.get("ready") is False)

        # ALLOW TWINS. A ready task starts as it always did, with no `mode` on
        # its row - the case that goes red if the exception were recorded on
        # every start - and a task already in_progress is the RETRY of
        # `reference/orchestrator.md` step 4, which must not need `--force`
        # even while its references are unmet, or the retry path would be lost.
        _prrproj, _prrmp = mk("st-ready-allow", pr_fixture())
        _prrc, _prrt = run(["start", "P2.4", "--project-dir", _prrproj])
        _prrr = pr_rows(_prrproj)
        _prre = json.loads(json.dumps(_pr_own))
        _prre["phases"][1]["tasks"][-1]["status"] = "in_progress"
        _prre["phases"][1]["tasks"][-1]["attempts"] = 1
        _prreproj, _prremp = mk("st-retry-allow", _prre)
        _prrec, _prret = run(["start", "P2.4", "--project-dir", _prreproj])
        check("pr11c ALLOW CASES: a ready task starts with exit 0 and a row "
              "carrying no `mode`, and a re-start of an in_progress task whose "
              "references are unmet is still the retry - exit 0, RE-STARTED, "
              "attempt 2, no --force asked for: %r"
              % ((_prrc, [sorted((r.get("details") or {})) for r in _prrr],
                  _prrec, (task_in(_prremp, "P2.4") or {}).get("attempts"),
                  _prret[:120]),),
              _prrc == 0 and len(_prrr) == 1
              and "mode" not in (_prrr[0].get("details") or {})
              and _prrec == 0 and "RE-STARTED" in _prret
              and (task_in(_prremp, "P2.4") or {}).get("attempts") == 2
              and (task_in(_prremp, "P2.4") or {}).get("status") == "in_progress")

        # THE SHARDED LAYOUT, because a promotion writes a TASK and a task lives
        # in its phase's shard: a writer that reached for the index would leave
        # a manifest whose assembled task still said `pending`.
        projsh, mpsh = mk("st-sharded", pr_fixture(), sharded=True)
        _sh_idx = _mio.read_json(mpsh)
        _sh_base = os.path.dirname(mpsh)
        _sh_of = dict((s.get("id"), os.path.join(_sh_base, s["shard"]))
                      for s in _sh_idx["phases"] if isinstance(s, dict))
        with open(_sh_of["P1"], "rb") as _fh:
            _sh_p1 = _fh.read()
        with open(mpsh, "rb") as _fh:
            _sh_index = _fh.read()
        codesh, _txtsh = run(["start", "P2.4", "--project-dir", projsh])
        check("pr12 the sharded layout promotes in the phase's SHARD, leaves "
              "an untouched phase's shard and the index byte-identical, and the "
              "gate's resolver reads the assembled result: %r"
              % ((codesh, (task_in(mpsh, "P2.4") or {}).get("status")),),
              codesh == 0 and _mio.is_sharded(_sh_idx)
              and (task_in(mpsh, "P2.4") or {}).get("status") == "in_progress"
              and open(_sh_of["P1"], "rb").read() == _sh_p1
              and open(mpsh, "rb").read() == _sh_index
              and pr_map(projsh).get("src/fresh.ts")
              == [{"taskId": "P2.4", "testsMode": "gate-only"}])

        # AN ALREADY-INVALID MANIFEST REFUSES BEFORE ANY WRITE, the `r3` rule
        # for this verb: a promotion written onto findings nobody has fixed is
        # a second problem on top of the first.
        _pr_bad = pr_fixture()
        _pr_bad["phases"][1]["tasks"][-1]["blockedBy"] = ["NOPE"]
        projbd, mpbd = mk("st-invalid", _pr_bad)
        with open(mpbd, "rb") as _fh:
            _pr_bd_before = _fh.read()
        codebd, txtbd = run(["start", "P2.4", "--project-dir", projbd])
        check("pr13 an already-invalid manifest refuses BEFORE the write, and "
              "the two arms are told apart by their own words rather than by "
              "the exit code: dropping the pre-check leaves the byte compare "
              "green, because the post-write arm catches the same findings and "
              "rolls back to the same bytes with the same exit 1. `nothing "
              "written` is the pre-check; `rolled back` is the other one: %r"
              % (txtbd[:100],),
              codebd == 1
              and "already invalid -- nothing written" in txtbd
              and "rolled back" not in txtbd
              and open(mpbd, "rb").read() == _pr_bd_before)

        # ---- (pc) the phase claim `start` takes on the sharded layout ----------
        # The claim used to be a step the orchestrator hand-wrote into the shard
        # after promoting the phase, so a run that skipped it left a running
        # phase no other machine could see was taken. Every case pins the
        # session id it runs under: the sweep drops every `CLAUDE_` variable, a
        # session running the suite carries its own, and a case that inherited
        # either would be asserting about whichever one it happened to get.
        _pc_env_was = os.environ.get("CLAUDE_CODE_SESSION_ID")

        def pc_repo(name, claim=None, sharded=True, git=True):
            """A git-backed project whose P3 holds one ready pending task and
            records `audit/p3`, which is checked out - so the start is an
            `on-branch` entry and nothing about the claim rides on a cut."""
            m = base_manifest()
            m["phases"][2]["branch"] = "audit/p3"
            m["phases"][2]["tasks"] = [
                {"id": "P3.1", "title": "claimable", "status": "pending",
                 "description": "", "files": ["src/claim.ts"],
                 "tests": {"mode": "gate-only", "add": [],
                           "expectRedFirst": False, "gate": ["test"]},
                 "model": "sonnet", "skills": [], "risk": "low",
                 "blockedBy": [], "dependsOn": [], "attempts": 0,
                 "maxAttempts": 3, "commit": None,
                 "outcome": {"technical": None, "descriptive": None},
                 "startedAt": None, "completedAt": None, "verifiedBy": []}]
            m["fileIndex"]["src/claim.ts"] = ["P3.1"]
            if claim is not None:
                m["phases"][2]["claim"] = claim
            if not git:
                m["phases"][2].pop("branch", None)
                return mk(name, m, sharded=sharded)
            proj, mpath = mk(name, m, sharded=sharded, git=True)
            for argv in (["checkout", "-q", "-b", "audit/p3"],
                         ["config", "user.email", "t@example.com"],
                         ["config", "user.name", "Test User"],
                         ["add", "-A"], ["commit", "-qm", "seed"]):
                subprocess.run(["git", "-C", proj] + argv,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            return proj, mpath

        def pc_shard_path(mpath, pid):
            """The path of `pid`'s shard file, or None on a single-file plan."""
            idx = _mio.read_json(mpath)
            for stub in (idx.get("phases") or []):
                if isinstance(stub, dict) and stub.get("id") == pid \
                        and "shard" in stub:
                    return os.path.join(os.path.dirname(mpath), stub["shard"])
            return None

        def pc_shard(mpath, pid):
            """The phase body exactly as its SHARD file holds it, or None."""
            path = pc_shard_path(mpath, pid)
            return _mio.read_json(path) if path else None

        def pc_phase(mpath, pid):
            for ph in (_mio.load_manifest(mpath).get("phases") or []):
                if ph.get("id") == pid:
                    return ph
            return {}

        import platform
        import _locks

        def pc_lock(proj, pid, session="s-other-session"):
            """Plant the `phase-P3` lock a phase run holds, as `audit-lock.py
            acquire` by hand records it: on this host, so `_locks.judge` probes
            `pid` rather than falling back to the lock's age."""
            ld = _locks.lock_dir(proj)
            os.makedirs(ld, exist_ok=True)
            _panel_write._atomic_write_json(
                os.path.join(ld, "phase-P3.lock"),
                {"sessionId": session, "pid": pid, "hostname": platform.node(),
                 "startedAt": "2026-01-01T00:00:00Z", "handedOff": True,
                 "note": "phase run"})

        def pc_gone_pid():
            """A pid no process holds: a child that has already been reaped."""
            child = subprocess.Popen([sys.executable, "-c", "pass"])
            child.wait()
            return child.pid

        def pc_json(txt):
            try:
                return json.loads(txt)
            except ValueError:
                return {}

        _PC_OTHER = {"sessionId": "s-other-session",
                     "branch": "audit/p3", "at": "2026-01-01T00:00:00Z"}
        _pc_pid_was = os.environ.pop("CLAUDE_PID", None)
        try:
            os.environ["CLAUDE_CODE_SESSION_ID"] = "s-mine-session"
            pc1_proj, pc1_mp = pc_repo("pc-first")
            pc1_code, pc1_txt = run(["start", "P3.1", "--project-dir", pc1_proj])
            pc1_body = pc_shard(pc1_mp, "P3") or {}
            pc1_claim = pc1_body.get("claim") or {}
            pc1_task = task_in(pc1_mp, "P3.1") or {}
            pc1_rows = pr_rows(pc1_proj)
            pc1_det = (pc1_rows[0].get("details") or {}) if pc1_rows else {}
            pc1_crow = dict((c.get("field"), c) for c in
                            (pc1_det.get("changes") or [])
                            if c.get("id") == "P3")
            check("pc1 the start of a sharded plan's first task in a phase "
                  "writes phase.claim into the SHARD - sessionId from "
                  "$CLAUDE_CODE_SESSION_ID, the phase's branch and "
                  "the start's own instant - in the same write that set the "
                  "phase in_progress: %r"
                  % ((pc1_code, pc1_body.get("status"), pc1_claim,
                      pc1_body.get("startedAt"), pc1_txt[-200:]),),
                  pc1_code == 0 and pc1_body.get("status") == "in_progress"
                  and pc1_claim.get("sessionId") == "s-mine-session"
                  and pc1_claim.get("branch") == "audit/p3"
                  and pc1_claim.get("at") == pc1_body.get("startedAt")
                  == pc1_task.get("startedAt")
                  and "claim" not in (
                      [s for s in _mio.read_json(pc1_mp)["phases"]
                       if s.get("id") == "P3"][0]))
            # THE SHARD IS COMMITTED, so the claim carries no machine name: the
            # journal drops `actor.host` for the same reason, and
            # `tools/check-committed-pii.py` reports one under a claim.
            check("pc7 the claim a start writes carries NO `host` key - only "
                  "sessionId, branch and at: %r" % (sorted(pc1_claim),),
                  pc1_code == 0
                  and sorted(pc1_claim) == ["at", "branch", "sessionId"])
            # THE CLAIM THE VERB WRITES IS ONE THE VALIDATOR ACCEPTS WHOLE: a
            # warning on every start would teach a reader to skip the warnings.
            # The twin keeps the recommendation alive - a claim with no branch
            # still warns, so an emptied key set cannot pass for this case.
            _pc_vm = M._validator()
            _pc_f, _pc_w = _pc_vm.validate(_mio.load_manifest(pc1_mp))
            _pc_nb = json.loads(json.dumps(_mio.load_manifest(pc1_mp)))
            for _ph in _pc_nb["phases"]:
                if _ph.get("id") == "P3":
                    _ph["claim"].pop("branch", None)
            _pc_nbf, _pc_nbw = _pc_vm.validate(_pc_nb)
            check("pc8 the started sharded plan revalidates with NO claim "
                  "warning, while the same claim with its branch removed still "
                  "warns that it is missing branch: %r"
                  % (([w for w in _pc_w if "claim" in w],
                      [w for w in _pc_nbw if "claim" in w]),),
                  pc1_code == 0 and _pc_f == [] and _pc_nbf == []
                  and [w for w in _pc_w if "claim" in w] == []
                  and len([w for w in _pc_nbw
                           if "claim is missing branch" in w]) == 1)
            check("pc2 ...and the one task.start row records the claim it took, "
                  "as phase-keyed `changes` rows beside the task's own, from "
                  "nothing to this session and branch: %r"
                  % ((len(pc1_rows), sorted(pc1_crow),
                      (pc1_rows[0].get("summary") if pc1_rows else None)),),
                  len(pc1_rows) == 1
                  and (pc1_crow.get("claim.sessionId") or {}).get("from") is None
                  and (pc1_crow.get("claim.sessionId") or {}).get("to")
                  == "s-mine-session"
                  and (pc1_crow.get("claim.branch") or {}).get("to") == "audit/p3"
                  and (pc1_crow.get("claim.at") or {}).get("to")
                  == pc1_claim.get("at")
                  and "claim" in (pc1_rows[0].get("summary") or ""))

            # ALLOW CASES. A single-file plan has no shard for the claim to
            # conflict in, so it gets none; and a re-start by the session that
            # already holds the claim leaves it byte for byte - `at` included,
            # which is why the fixture's claim carries a moment no start writes.
            pc3_proj, pc3_mp = pc_repo("pc-single", sharded=False)
            pc3_code, _pc3_txt = run(["start", "P3.1", "--project-dir", pc3_proj])
            pc3_ph = pc_phase(pc3_mp, "P3")
            _pc_mine = dict(_PC_OTHER, sessionId="s-mine-session")
            pc4_proj, pc4_mp = pc_repo("pc-mine", claim=_pc_mine)
            pc4_code, _pc4_txt = run(["start", "P3.1", "--project-dir", pc4_proj])
            pc4_claim = (pc_shard(pc4_mp, "P3") or {}).get("claim")
            pc4_rows = pr_rows(pc4_proj)
            check("pc3 ALLOW CASES: a single-file plan starts and writes no "
                  "claim, and a start by the session that already holds the "
                  "claim leaves it exactly as it was and records no claim row: "
                  "%r" % ((pc3_code, pc3_ph.get("status"), pc3_ph.get("claim"),
                           pc4_code, pc4_claim),),
                  pc3_code == 0 and pc3_ph.get("status") == "in_progress"
                  and "claim" not in pc3_ph
                  and pc4_code == 0 and pc4_claim == _pc_mine
                  and len(pc4_rows) == 1
                  and not [c for c in ((pc4_rows[0].get("details") or {})
                                       .get("changes") or [])
                           if c.get("id") == "P3"])

            # ANOTHER SESSION'S CLAIM REFUSES WHILE ITS HOLDER IS LIVE, naming
            # it; `--force --reason` is the one way past, and the row keeps the
            # claim it replaced. The live holder is a `phase-P3` lock on a pid
            # that is running - this suite's own.
            pc5_proj, pc5_mp = pc_repo("pc-other", claim=_PC_OTHER)
            pc_lock(pc5_proj, os.getpid())
            with open(pc_shard_path(pc5_mp, "P3"), "rb") as _fh:
                pc5_before = _fh.read()
            pc5_code, pc5_txt = run(["start", "P3.1", "--project-dir", pc5_proj])
            with open(pc_shard_path(pc5_mp, "P3"), "rb") as _fh:
                pc5_after = _fh.read()
            check("pc4 a start on a phase another session has claimed is "
                  "REFUSED: exit 2, the shard byte identical, no task.start "
                  "row, and the message names the claim (session, branch, "
                  "moment) and --force: %r" % ((pc5_code, pc5_txt[:240]),),
                  pc5_code == 2 and pc5_after == pc5_before
                  and pr_rows(pc5_proj) == []
                  and "s-other-session" in pc5_txt
                  and "audit/p3" in pc5_txt
                  and _PC_OTHER["at"] in pc5_txt
                  and "--force" in pc5_txt
                  and (task_in(pc5_mp, "P3.1") or {}).get("status") == "pending")
            pc6_code, pc6_txt = run(["start", "P3.1", "--force", "--reason",
                                     "the other session died",
                                     "--project-dir", pc5_proj])
            pc6_claim = (pc_shard(pc5_mp, "P3") or {}).get("claim") or {}
            pc6_rows = pr_rows(pc5_proj)
            pc6_det = (pc6_rows[0].get("details") or {}) if pc6_rows else {}
            pc6_crow = dict((c.get("field"), c) for c in
                            (pc6_det.get("changes") or [])
                            if c.get("id") == "P3")
            check("pc5 ...and `--force --reason` replaces it with this "
                  "session's claim, and the task.start row journals the claim "
                  "it replaced: forced, the reason, the old session as `from`, "
                  "and the summary naming it: %r"
                  % ((pc6_code, pc6_claim, pc6_det.get("mode"),
                      pc6_det.get("reason"), pc6_crow.get("claim.sessionId"),
                      (pc6_rows[0].get("summary") if pc6_rows else None)),),
                  pc6_code == 0
                  and pc6_claim.get("sessionId") == "s-mine-session"
                  and pc6_claim.get("at") != _PC_OTHER["at"]
                  and len(pc6_rows) == 1
                  and pc6_det.get("mode") == "forced"
                  and pc6_det.get("reason") == "the other session died"
                  and "s-other-session" in (pc6_det.get("basis") or "")
                  and (pc6_crow.get("claim.sessionId") or {}).get("from")
                  == "s-other-session"
                  and (pc6_crow.get("claim.sessionId") or {}).get("to")
                  == "s-mine-session"
                  and "s-other-session" in (pc6_rows[0].get("summary") or ""))

            # NO SESSION ID, NO CLAIM: one naming nobody could never be told
            # apart from somebody else's, so the start runs, writes none, and
            # says why - rather than a claim with an empty `sessionId`.
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            pc7_proj, pc7_mp = pc_repo("pc-nosession")
            pc7_code, pc7_txt = run(["start", "P3.1", "--project-dir", pc7_proj])
            pc7_body = pc_shard(pc7_mp, "P3") or {}
            check("pc6 with $CLAUDE_CODE_SESSION_ID unset the start still runs, "
                  "writes no claim, and the output says none was taken and why: "
                  "%r" % ((pc7_code, pc7_body.get("status"),
                           pc7_body.get("claim"), pc7_txt[-220:]),),
                  pc7_code == 0 and pc7_body.get("status") == "in_progress"
                  and "claim" not in pc7_body
                  and "claim: none taken" in pc7_txt
                  and "CLAUDE_CODE_SESSION_ID is unset" in pc7_txt)

            # ---- (tk) a claim yields when its holder holds no live run -------
            # The claim alone has no liveness, so a refusal on it alone refused
            # every SEQUENTIAL session - the next /audit:next, any resume - and
            # made --force the routine path. Liveness is asked of the
            # `phase-<id>` lock through `_locks`, the reader `audit-lock.py
            # status` answers from.
            os.environ["CLAUDE_CODE_SESSION_ID"] = "s-mine-session"

            def tk_start(name, claim, lock_pid=None, lock_session=None,
                         extra=()):
                proj, mp = pc_repo(name, claim=claim)
                if lock_pid is not None:
                    pc_lock(proj, lock_pid, lock_session or "s-other-session")
                path = pc_shard_path(mp, "P3")
                with open(path, "rb") as fh:
                    before = fh.read()
                code, txt = run(["start", "P3.1", "--json", "--project-dir", proj]
                                + list(extra))
                with open(path, "rb") as fh:
                    after = fh.read()
                rows = pr_rows(proj)
                det = (rows[0].get("details") or {}) if rows else {}
                crow = dict((c.get("field"), c) for c in (det.get("changes") or [])
                            if c.get("id") == "P3")
                return {"code": code, "txt": txt, "json": pc_json(txt),
                        "claim": (pc_shard(mp, "P3") or {}).get("claim"),
                        "same": before == after, "rows": rows, "det": det,
                        "crow": crow, "mp": mp}

            # A CLAIM WITH NO LOCK BEHIND IT IS NOT EVIDENCE OF A FINISHED RUN:
            # it may have been pulled from another clone, whose lock directory
            # this clone cannot read, or written before a start took a lock. So
            # it refuses, and says the basis rather than a verdict on the holder.
            tk1 = tk_start("tk-nolock", dict(_PC_OTHER))
            check("tk1 another session's claim with NO phase lock in this clone "
                  "is REFUSED - exit 2, the shard byte identical, no row - and "
                  "the refusal says liveness could not be asked because no "
                  "phase-P3 lock is held here: %r"
                  % ((tk1["code"], tk1["txt"][:400]),),
                  tk1["code"] == 2 and tk1["same"] and tk1["rows"] == []
                  and "could not be asked" in tk1["txt"]
                  and "no phase-P3 lock" in tk1["txt"]
                  and "in this clone" in tk1["txt"])
            tk2 = tk_start("tk-deadlock", dict(_PC_OTHER),
                           lock_pid=pc_gone_pid())
            check("tk2 a sequential second session whose predecessor's phase "
                  "lock is still on disk but names a pid that is gone takes the "
                  "claim over without --force, and the task.start row records "
                  "the takeover: the replaced session as `from`, this one as "
                  "`to`, and a claim.takeover row carrying `_locks.judge`'s own "
                  "basis behind the clone-scoped wording: %r"
                  % ((tk2["code"], tk2["claim"], tk2["crow"],
                      tk2["json"].get("claimAction")),),
                  tk2["code"] == 0
                  and (tk2["claim"] or {}).get("sessionId") == "s-mine-session"
                  and tk2["json"].get("claimAction") == "takeover"
                  and tk2["json"].get("forced") is False
                  and len(tk2["rows"]) == 1
                  and tk2["det"].get("mode") is None
                  and (tk2["crow"].get("claim.sessionId") or {}).get("from")
                  == "s-other-session"
                  and (tk2["crow"].get("claim.takeover") or {}).get("from")
                  == "s-other-session"
                  and "no live phase-P3 lock in this clone"
                  in ((tk2["crow"].get("claim.takeover") or {}).get("to") or "")
                  and "is gone on this host"
                  in ((tk2["crow"].get("claim.takeover") or {}).get("to") or "")
                  and "taken over" in (tk2["rows"][0].get("summary") or ""))
            tk3 = tk_start("tk-livelock", dict(_PC_OTHER), lock_pid=os.getpid())
            _tk3_op = tk3["txt"].find("operator")
            check("tk3 SECOND DIRECTION: the same start with a LIVE phase lock "
                  "held by another session is refused - exit 2, the shard byte "
                  "identical, no row - and the refusal names the decision as "
                  "the operator's before it names --force: %r"
                  % ((tk3["code"], tk3["txt"][:300]),),
                  tk3["code"] == 2 and tk3["same"] and tk3["rows"] == []
                  and "is running on this host" in tk3["txt"]
                  and _tk3_op != -1
                  and _tk3_op < tk3["txt"].find("--force"))
            tk4 = tk_start("tk-ourlock", dict(_PC_OTHER), lock_pid=os.getpid(),
                           lock_session="s-mine-session")
            check("tk4 ALLOW: a live phase lock THIS session holds is the run "
                  "the orchestrator took before starting, not the claim's "
                  "holder, so the claim is taken over: %r"
                  % ((tk4["code"], tk4["claim"], tk4["txt"][:200]),),
                  tk4["code"] == 0
                  and (tk4["claim"] or {}).get("sessionId") == "s-mine-session"
                  and tk4["json"].get("claimAction") == "takeover")
            # LIVENESS THAT CANNOT BE ASKED REFUSES: a sharded plan outside any
            # git repository has no lock directory to read.
            tk5_proj, _tk5_mp = pc_repo("tk-nogit", claim=dict(_PC_OTHER),
                                        git=False)
            tk5_code, tk5_txt = run(["start", "P3.1", "--project-dir", tk5_proj])
            check("tk5 a start whose holder's liveness CANNOT be asked (no git "
                  "repository, so no lock directory) is refused like a live "
                  "one, and says liveness could not be asked: %r"
                  % ((tk5_code, tk5_txt[:300]),),
                  tk5_code == 2 and "could not be asked" in tk5_txt
                  and tk5_txt.find("operator") < tk5_txt.find("--force"))

            # NO SESSION ID UNDER A HELD CLAIM: a forced start has nothing to
            # replace the claim with, so it keeps it and reports it as KEPT.
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            tk6 = tk_start("tk-force-nosession", dict(_PC_OTHER),
                           lock_pid=os.getpid(),
                           extra=["--force", "--reason", "operator says go"])
            check("tk6 a forced start with no session id keeps the held claim "
                  "and reports claimReplaced None and the claim as kept - never "
                  "as replaced: %r" % ((tk6["code"], tk6["claim"],
                                        tk6["json"].get("claimReplaced"),
                                        tk6["json"].get("claimKept"),
                                        tk6["det"].get("basis")),),
                  tk6["code"] == 0 and tk6["claim"] == _PC_OTHER
                  and tk6["json"].get("claimReplaced") is None
                  and tk6["json"].get("claimKept") == _PC_OTHER
                  and "kept" in (tk6["det"].get("basis") or "")
                  and not tk6["crow"])
            tk7 = tk_start("tk-dead-nosession", dict(_PC_OTHER),
                           lock_pid=pc_gone_pid())
            check("tk7 ...and with no live holder an unforced start runs, "
                  "keeping the claim it cannot replace: %r"
                  % ((tk7["code"], tk7["claim"], tk7["json"].get("claimKept")),),
                  tk7["code"] == 0 and tk7["claim"] == _PC_OTHER
                  and tk7["json"].get("claimReplaced") is None
                  and tk7["json"].get("claimKept") == _PC_OTHER)

            # AN UNSAFE SESSION ID IS WRITTEN BOUNDED, through the one function
            # that bounds the value a committed row carries.
            os.environ["CLAUDE_CODE_SESSION_ID"] = "s mine/../" + "x" * 200
            import _journal_io as _tk_jio
            _tk8_want = _tk_jio.env_session_id()
            tk8 = tk_start("tk-unsafe", None)
            tk8_sid = (tk8["claim"] or {}).get("sessionId") or ""
            check("tk8 an over-long, unsafe session id lands in the claim "
                  "sanitised and bounded - the value `env_session_id` answers, "
                  "no path separator, no space: %r" % (tk8_sid,),
                  tk8["code"] == 0 and tk8_sid == _tk8_want
                  and 0 < len(tk8_sid) <= _tk_jio.MAX_SESSION_ID_CHARS
                  and "/" not in tk8_sid and " " not in tk8_sid)
            tk9 = tk_start("tk-unsafe-mine", {"sessionId": _tk8_want,
                                              "branch": "audit/p3",
                                              "at": "2026-01-01T00:00:00Z"},
                           # The lock is the one this session's own start writes:
                           # `_locks` records the session id as the environment
                           # spells it, the claim the bounded value.
                           lock_pid=os.getpid(),
                           lock_session=os.environ["CLAUDE_CODE_SESSION_ID"])
            check("tk9 ...and the holder comparison reads the same bounded "
                  "value, so that session's own claim is kept, not contested: %r"
                  % ((tk9["code"], tk9["json"].get("claimAction")),),
                  tk9["code"] == 0 and tk9["json"].get("claimAction") == "keep")

            # A LEGACY CLAIM ON THE INDEX STUB IS DROPPED BY SIGN-OFF AND
            # CANCEL. `_merge_phase` falls back to a stub claim when the body
            # has none, so popping the body's alone let it reappear.
            os.environ["CLAUDE_CODE_SESSION_ID"] = "s-mine-session"
            for _tk_case, _tk_verb in (("tk10", "signoff"), ("tk11", "cancel")):
                _tk_m = base_manifest()
                _tk_m["phases"][1]["tasks"][1]["status"] = "done"
                _tk_p, _tk_mp = mk("tk-stub-" + _tk_verb, _tk_m, sharded=True,
                                   git=True)
                _tk_idx = _mio.read_json(_tk_mp)
                for _stub in _tk_idx["phases"]:
                    if _stub.get("id") in ("P2", "P3"):
                        _stub["claim"] = dict(_PC_OTHER)
                _panel_write._atomic_write_json(_tk_mp, _tk_idx)
                if _tk_verb == "signoff":
                    _tk_code, _tk_txt = run(
                        ["signoff", "P2", "--verdict", "passed", "--summary",
                         "s", "--no-evidence-reason", "fixture",
                         "--project-dir", _tk_p])
                else:
                    _tk_code, _tk_txt = run(
                        ["cancel", "P2", "--reason", "fixture",
                         "--project-dir", _tk_p])
                _tk_after = _mio.read_json(_tk_mp)
                _tk_stub = dict((s.get("id"), s) for s in _tk_after["phases"])
                check("%s %s drops a legacy claim on the phase's INDEX STUB, "
                      "so it cannot reappear in the assembled phase, and "
                      "leaves another phase's stub alone: %r"
                      % (_tk_case, _tk_verb, (_tk_code, _tk_stub.get("P2"),
                                    pc_phase(_tk_mp, "P2").get("claim"),
                                    _tk_txt[-200:]),),
                      _tk_code == 0
                      and "claim" not in _tk_stub.get("P2", {})
                      and "claim" not in pc_phase(_tk_mp, "P2")
                      and _tk_stub.get("P3", {}).get("claim") == _PC_OTHER)

            # ---- (hl) the hand-off lock a hand-typed start takes ----------------
            # A start nobody orchestrated used to write a claim and no lock, so the
            # next session read "no lock" as "no live run" and took the phase over
            # from a session that was still working it. The start now takes the
            # `phase-<id>` lock `audit-lock.py acquire` takes, through the same
            # `_locks.acquire`, recording $CLAUDE_PID as the holder.
            def hl_lock_path(proj):
                return os.path.join(_locks.lock_dir(proj), "phase-P3.lock")

            def hl_plant(proj, info):
                ld = _locks.lock_dir(proj)
                os.makedirs(ld, exist_ok=True)
                _panel_write._atomic_write_json(hl_lock_path(proj), info)

            def hl_start(proj, session, pid, extra=()):
                os.environ["CLAUDE_CODE_SESSION_ID"] = session
                os.environ["CLAUDE_PID"] = str(pid)
                path = pc_shard_path(pc_repo_mp[proj], "P3")
                with open(path, "rb") as fh:
                    before = fh.read()
                code, txt = run(["start", "P3.1", "--json", "--project-dir", proj]
                                + list(extra))
                with open(path, "rb") as fh:
                    after = fh.read()
                return {"code": code, "txt": txt, "json": pc_json(txt),
                        "same": before == after,
                        "claim": (pc_shard(pc_repo_mp[proj], "P3") or {})
                        .get("claim")}

            pc_repo_mp = {}
            _hl_tokens_was = os.environ.get(_locks.TOKEN_ENV)
            _hl_child = subprocess.Popen([sys.executable, "-c",
                                          "import time; time.sleep(120)"])
            try:
                hl_proj, hl_mp = pc_repo("hl-hand")
                pc_repo_mp[hl_proj] = hl_mp
                hl_a = hl_start(hl_proj, "s-hand-a", _hl_child.pid)
                hl_info = _locks.read_lock(hl_lock_path(hl_proj))
                check("hl1 a hand-typed start by session A with a live $CLAUDE_PID "
                      "and no prior lock takes the phase-P3 lock in "
                      "`_locks.acquire`'s own format - handed off, A's session, "
                      "A's pid, this host, a token, and yielding to a longer "
                      "hold of A's own: %r"
                      % ((hl_a["code"], sorted(hl_info),
                          hl_info.get("sessionId"), hl_info.get("pid")),),
                      hl_a["code"] == 0
                      and (hl_a["claim"] or {}).get("sessionId") == "s-hand-a"
                      and hl_info.get("sessionId") == "s-hand-a"
                      and hl_info.get("pid") == _hl_child.pid
                      and hl_info.get("handedOff") is True
                      and hl_info.get("hostname") == platform.node()
                      and bool(hl_info.get("token"))
                      and sorted(hl_info) == ["handedOff", "hostname", "note",
                                              "pid", "sessionId", "startedAt",
                                              "token", "yields"])
                hl_b = hl_start(hl_proj, "s-hand-b", os.getpid())
                check("hl2 ...so session B's start, while A's pid runs, is "
                      "REFUSED: exit 2, the shard byte identical, A's lock "
                      "untouched, and the refusal names A's live pid: %r"
                      % ((hl_b["code"], hl_b["txt"][:300]),),
                      hl_b["code"] == 2 and hl_b["same"]
                      and _locks.read_lock(hl_lock_path(hl_proj)) == hl_info
                      and "is running on this host" in hl_b["txt"])
                _hl_child.kill()
                _hl_child.wait()
                hl_c = hl_start(hl_proj, "s-hand-b", os.getpid())
                hl_cinfo = _locks.read_lock(hl_lock_path(hl_proj))
                check("hl3 ...and once A's pid is gone the same start by B takes "
                      "the claim over without --force, takes the lock over too "
                      "(B's session and pid on it now), and its line states the "
                      "basis rather than a verdict on A: %r"
                      % ((hl_c["code"], hl_c["json"].get("claimAction"),
                          hl_cinfo.get("sessionId"), hl_cinfo.get("pid")),),
                      hl_c["code"] == 0
                      and hl_c["json"].get("claimAction") == "takeover"
                      and (hl_c["claim"] or {}).get("sessionId") == "s-hand-b"
                      and hl_cinfo.get("sessionId") == "s-hand-b"
                      and hl_cinfo.get("pid") == os.getpid()
                      and "no live phase-P3 lock in this clone"
                      in (hl_c["json"].get("claimTakeoverBasis") or "")
                      and (hl_c["json"].get("phaseLock") or {}).get("state")
                      == "took")
                # The text line, in the plain (non-JSON) output.
                hl_tp, hl_tmp = pc_repo("hl-text", claim=dict(_PC_OTHER))
                pc_lock(hl_tp, pc_gone_pid())
                os.environ["CLAUDE_CODE_SESSION_ID"] = "s-hand-b"
                hl_tcode, hl_ttxt = run(["start", "P3.1", "--project-dir", hl_tp])
                check("hl4 the takeover line says `no live phase-P3 lock in this "
                      "clone` and never that the holder holds no live run: %r"
                      % ((hl_tcode, [ln for ln in hl_ttxt.splitlines()
                                     if "claim:" in ln]),),
                      hl_tcode == 0
                      and "no live phase-P3 lock in this clone" in hl_ttxt
                      and "holds no live run" not in hl_ttxt)

                # AGE ALONE IS NOT DEATH: a lock with no pid, or one from another
                # host, past the age limit says nothing about whether its run still
                # holds the phase, so it refuses like a live one.
                hl_cases = (("hl5", "hl-nopid",
                             {"sessionId": "s-other-session",
                              "hostname": platform.node(),
                              "startedAt": "2026-01-01T00:00:00Z",
                              "handedOff": True, "note": "phase run"}),
                            ("hl6", "hl-otherhost",
                             {"sessionId": "s-other-session", "pid": os.getpid(),
                              "hostname": "not-" + platform.node(),
                              "startedAt": "2026-01-01T00:00:00Z",
                              "handedOff": True, "note": "phase run"}))
                for _hl_id, _hl_name, _hl_lock in hl_cases:
                    _hp, _hmp = pc_repo(_hl_name, claim=dict(_PC_OTHER))
                    pc_repo_mp[_hp] = _hmp
                    hl_plant(_hp, _hl_lock)
                    _hr = hl_start(_hp, "s-hand-b", os.getpid())
                    check("%s a %s lock past the age limit under another "
                          "session's claim is REFUSED as unaskable, not taken "
                          "over as dead, and the lock is left as it was: %r"
                          % (_hl_id, _hl_name, (_hr["code"], _hr["txt"][:300]),),
                          _hr["code"] == 2 and _hr["same"]
                          and "could not be asked" in _hr["txt"]
                          and "threshold" in _hr["txt"]
                          and _locks.read_lock(hl_lock_path(_hp)) == _hl_lock)

                # THE ORCHESTRATOR'S OWN LOCK IS REUSED, NEVER DOUBLED: the claim is
                # taken over and the lock file is the orchestrator's, byte for byte.
                hl_op, hl_omp = pc_repo("hl-orch", claim=dict(_PC_OTHER))
                pc_repo_mp[hl_op] = hl_omp
                pc_lock(hl_op, os.getpid(), "s-hand-b")
                with open(hl_lock_path(hl_op), "rb") as _fh:
                    _hl_obefore = _fh.read()
                hl_o = hl_start(hl_op, "s-hand-b", os.getpid())
                with open(hl_lock_path(hl_op), "rb") as _fh:
                    _hl_oafter = _fh.read()
                check("hl7 ALLOW: with the orchestrator's own phase lock held the "
                      "start takes the claim over without --force and leaves that "
                      "lock byte for byte - reused, not doubled or replaced: %r"
                      % ((hl_o["code"], hl_o["json"].get("claimAction"),
                          hl_o["json"].get("phaseLock")),),
                      hl_o["code"] == 0
                      and hl_o["json"].get("claimAction") == "takeover"
                      and _hl_oafter == _hl_obefore
                      and (hl_o["json"].get("phaseLock") or {}).get("state")
                      == "ours")

                # WHERE THE HAND-OFF LOCK GOES BACK: sign-off and a phase cancel
                # release the lock a start took, and leave anybody else's.
                for _hl_id, _hl_verb in (("hl8", "signoff"), ("hl9", "cancel")):
                    _hp, _hmp = pc_repo("hl-rel-" + _hl_verb)
                    pc_repo_mp[_hp] = _hmp
                    _hs = hl_start(_hp, "s-hand-a", os.getpid())
                    _had = os.path.exists(hl_lock_path(_hp))
                    if _hl_verb == "signoff":
                        run(["cancel", "P3.1", "--reason", "fixture",
                             "--project-dir", _hp])
                        _hc, _ht = run(["signoff", "P3", "--verdict", "passed",
                                        "--summary", "s", "--no-evidence-reason",
                                        "fixture", "--project-dir", _hp])
                    else:
                        _hc, _ht = run(["cancel", "P3", "--reason", "fixture",
                                        "--project-dir", _hp])
                    check("%s %s releases the phase lock the hand start took, and "
                          "says so: %r" % (_hl_id, _hl_verb,
                                           (_hs["code"], _had, _hc, _ht[-300:]),),
                          _hs["code"] == 0 and _had and _hc == 0
                          and not os.path.exists(hl_lock_path(_hp))
                          and "released phase-P3" in _ht)
                for _hl_id, _hl_verb in (("hl10", "signoff"), ("hl11", "cancel")):
                    _hp, _hmp = pc_repo("hl-keep-" + _hl_verb)
                    pc_repo_mp[_hp] = _hmp
                    pc_lock(_hp, os.getpid(), "s-hand-a")
                    with open(hl_lock_path(_hp), "rb") as _fh:
                        _hb = _fh.read()
                    _hs = hl_start(_hp, "s-hand-a", os.getpid())
                    if _hl_verb == "signoff":
                        run(["cancel", "P3.1", "--reason", "fixture",
                             "--project-dir", _hp])
                        _hc, _ht = run(["signoff", "P3", "--verdict", "passed",
                                        "--summary", "s", "--no-evidence-reason",
                                        "fixture", "--project-dir", _hp])
                    else:
                        _hc, _ht = run(["cancel", "P3", "--reason", "fixture",
                                        "--project-dir", _hp])
                    _ha = b""
                    if os.path.exists(hl_lock_path(_hp)):
                        with open(hl_lock_path(_hp), "rb") as _fh:
                            _ha = _fh.read()
                    check("%s ALLOW: %s leaves a phase lock the start did NOT "
                          "take - the orchestrator's, which it releases after "
                          "the merge - byte for byte: %r"
                          % (_hl_id, _hl_verb, (_hs["code"], _hc, _ht[-200:]),),
                          _hs["code"] == 0 and _hc == 0 and _ha == _hb)
            finally:
                if _hl_child.poll() is None:
                    _hl_child.kill()
                    _hl_child.wait()
                if _hl_tokens_was is None:
                    os.environ.pop(_locks.TOKEN_ENV, None)
                else:
                    os.environ[_locks.TOKEN_ENV] = _hl_tokens_was
                os.environ.pop("CLAUDE_PID", None)
        finally:
            if _pc_pid_was is not None:
                os.environ["CLAUDE_PID"] = _pc_pid_was
            if _pc_env_was is None:
                os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            else:
                os.environ["CLAUDE_CODE_SESSION_ID"] = _pc_env_was

        # ---- (lv) a held phase lock names a live process -----------------------
        # Every step is its own process with its own session id and $CLAUDE_PID,
        # the way two sessions and a restarted run really meet: in one process the
        # token a take carries in the environment would let every later call back
        # in, and the cases would be about that instead. The pids are sleepers this
        # suite starts and kills, so "the holder died" is an observed exit.
        _lv_task_py = os.path.join(_output.SCRIPTS_DIR, "manifest", "audit-task.py")
        _lv_lock_py = os.path.join(_output.SCRIPTS_DIR, "governance",
                                   "audit-lock.py")

        def lv_env(session, pid):
            # None leaves the variable unset: a run with no session id, or one
            # started where nothing exported $CLAUDE_PID.
            env = dict((k, v) for k, v in os.environ.items()
                       if not k.startswith("CLAUDE_") and k != _locks.TOKEN_ENV)
            if session is not None:
                env["CLAUDE_CODE_SESSION_ID"] = session
            if pid is not None:
                env["CLAUDE_PID"] = str(pid)
            return env

        def lv_call(script, proj, argv, session, pid):
            # `--verbose`, because what these cases read is the phase lock's
            # sentence in the long form a success prints; run as a command, a
            # success is otherwise one line (`sl` below), which these cases are
            # not about.
            done = subprocess.run([sys.executable, script] + argv + ["--verbose"],
                                  env=lv_env(session, pid), cwd=proj,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            return done.returncode, done.stdout.decode("utf-8", "replace")

        def lv_start(proj, session, pid):
            code, txt = lv_call(_lv_task_py, proj, ["start", "P3.1", "--json",
                                                    "--project-dir", proj],
                                session, pid)
            return {"code": code, "txt": txt, "json": pc_json(txt)}

        def lv_lock(proj, argv, session, pid):
            return lv_call(_lv_lock_py, proj, argv + ["--project", proj, "--wait",
                                                      "0"], session, pid)

        def lv_signoff(proj, session, pid):
            lv_call(_lv_task_py, proj, ["cancel", "P3.1", "--reason", "fixture",
                                        "--project-dir", proj], session, pid)
            return lv_call(_lv_task_py, proj,
                           ["signoff", "P3", "--verdict", "passed", "--summary",
                            "s", "--no-evidence-reason", "fixture",
                            "--project-dir", proj], session, pid)

        def lv_path(proj):
            return os.path.join(_locks.lock_dir(proj), "phase-P3.lock")

        def lv_shard_bytes(proj, mp):
            with open(pc_shard_path(mp, "P3"), "rb") as fh:
                return fh.read()

        def lv_sleeper():
            return subprocess.Popen([sys.executable, "-c",
                                     "import time; time.sleep(300)"])

        def lv_kill(proc):
            if proc.poll() is None:
                proc.kill()
            proc.wait()

        _lv_procs = []
        try:
            _lv_procs.extend(lv_sleeper() for _n in range(4))
            _lv_p1, _lv_p2, _lv_pb, _lv_pa = _lv_procs

            # A RESUMED SESSION RUNS UNDER A NEW PROCESS. Its keep start must move
            # the lock onto that process, or the lock still names the dead one and
            # the next session reads the phase as abandoned.
            lv1_proj, lv1_mp = pc_repo("lv-resume")
            lv1_a1 = lv_start(lv1_proj, "s-lv-a", _lv_p1.pid)
            lv_kill(_lv_p1)
            lv1_a2 = lv_start(lv1_proj, "s-lv-a", _lv_p2.pid)
            lv1_info = _locks.read_lock(lv_path(lv1_proj))
            lv1_before = lv_shard_bytes(lv1_proj, lv1_mp)
            lv1_b = lv_start(lv1_proj, "s-lv-b", _lv_pb.pid)
            check("lv1 a same-session start under a NEW process after the old one "
                  "died re-records the phase lock under the live process, so "
                  "another session's start is then REFUSED - exit 2, the shard "
                  "byte identical: %r"
                  % ((lv1_a1["code"], lv1_a2["code"],
                      lv1_a2["json"].get("claimAction"), lv1_info.get("pid"),
                      _lv_p2.pid, lv1_b["code"], lv1_b["txt"][:200]),),
                  lv1_a1["code"] == 0 and lv1_a2["code"] == 0
                  and lv1_a2["json"].get("claimAction") == "keep"
                  and lv1_info.get("pid") == _lv_p2.pid
                  and lv1_info.get("sessionId") == "s-lv-a"
                  and lv1_b["code"] == 2
                  and lv_shard_bytes(lv1_proj, lv1_mp) == lv1_before)
            # The allow twin: the refresh does not make a lock immortal. Once the
            # process it names is gone too, the next session takes the phase.
            lv_kill(_lv_p2)
            lv2_b = lv_start(lv1_proj, "s-lv-b", _lv_pb.pid)
            check("lv2 ALLOW: once the re-recorded process is gone as well, the "
                  "other session's start takes the claim over without --force: %r"
                  % ((lv2_b["code"], lv2_b["json"].get("claimAction")),),
                  lv2_b["code"] == 0
                  and lv2_b["json"].get("claimAction") == "takeover")

            # A KEEP START ASKS THE LOCK TOO. A session that kept its claim but
            # gave its lock back must not start again under another run's live
            # lock just because the claim is its own.
            lv3_proj, lv3_mp = pc_repo("lv-keep-foreign")
            lv3_a1 = lv_start(lv3_proj, "s-lv-a", _lv_pa.pid)
            lv3_rel = lv_lock(lv3_proj, ["release", "phase-P3"], "s-lv-a",
                              _lv_pa.pid)
            lv3_acq = lv_lock(lv3_proj, ["acquire", "phase-P3", "--note",
                                         "phase run"], "s-lv-b", _lv_pb.pid)
            lv3_lock = _locks.read_lock(lv_path(lv3_proj))
            lv3_before = lv_shard_bytes(lv3_proj, lv3_mp)
            lv3_a2 = lv_start(lv3_proj, "s-lv-a", _lv_pa.pid)
            check("lv3 a keep start while ANOTHER session's live phase lock is "
                  "held is REFUSED - exit 2, the shard byte identical, the other "
                  "session's lock untouched: %r"
                  % ((lv3_a1["code"], lv3_rel[0], lv3_acq[0], lv3_a2["code"],
                      lv3_a2["json"].get("phaseLock"), lv3_a2["txt"][:200]),),
                  lv3_a1["code"] == 0 and lv3_rel[0] == 0 and lv3_acq[0] == 0
                  and lv3_a2["code"] == 2
                  and lv_shard_bytes(lv3_proj, lv3_mp) == lv3_before
                  and _locks.read_lock(lv_path(lv3_proj)) == lv3_lock
                  and lv3_lock.get("sessionId") == "s-lv-b")
            lv4_proj, _lv4_mp = pc_repo("lv-keep-dead")
            lv4_a1 = lv_start(lv4_proj, "s-lv-a", _lv_pa.pid)
            lv_lock(lv4_proj, ["release", "phase-P3"], "s-lv-a", _lv_pa.pid)
            lv_lock(lv4_proj, ["acquire", "phase-P3", "--note", "phase run"],
                    "s-lv-b", pc_gone_pid())
            lv4_a2 = lv_start(lv4_proj, "s-lv-a", _lv_pa.pid)
            lv4_lock = _locks.read_lock(lv_path(lv4_proj))
            check("lv4 ALLOW: the same keep start over a lock whose process is "
                  "gone runs, and the lock is this session's afterwards: %r"
                  % ((lv4_a1["code"], lv4_a2["code"],
                      lv4_a2["json"].get("claimAction"), lv4_lock.get("sessionId"),
                      lv4_lock.get("pid")),),
                  lv4_a1["code"] == 0 and lv4_a2["code"] == 0
                  and lv4_a2["json"].get("claimAction") == "keep"
                  and lv4_lock.get("sessionId") == "s-lv-a"
                  and lv4_lock.get("pid") == _lv_pa.pid)

            # THE MERGE RUNS UNDER A HELD LOCK. The orchestrator's acquire over the
            # lock its own hand start took must leave a lock sign-off does not
            # give back - sign-off releases only the start's.
            lv5_proj, _lv5_mp = pc_repo("lv-merge")
            lv5_a = lv_start(lv5_proj, "s-lv-a", _lv_pa.pid)
            lv5_acq = lv_lock(lv5_proj, ["acquire", "phase-P3", "--note",
                                         "phase run"], "s-lv-a", _lv_pa.pid)
            lv5_so = lv_signoff(lv5_proj, "s-lv-a", _lv_pa.pid)
            lv5_lock = _locks.read_lock(lv_path(lv5_proj))
            check("lv5 hand start, then the orchestrator's acquire, then sign-off: "
                  "the phase lock is STILL HELD, under the orchestrator's note: %r"
                  % ((lv5_a["code"], lv5_acq, lv5_so[0], lv5_lock),),
                  lv5_a["code"] == 0 and lv5_acq[0] == 0 and lv5_so[0] == 0
                  and os.path.exists(lv_path(lv5_proj))
                  and lv5_lock.get("note") == "phase run"
                  and lv5_lock.get("sessionId") == "s-lv-a")
            lv6_proj, _lv6_mp = pc_repo("lv-merge-none")
            lv6_a = lv_start(lv6_proj, "s-lv-a", _lv_pa.pid)
            lv6_so = lv_signoff(lv6_proj, "s-lv-a", _lv_pa.pid)
            check("lv6 ALLOW: with no orchestrator acquire in between, sign-off "
                  "gives back the lock the start took: %r"
                  % ((lv6_a["code"], lv6_so[0], lv6_so[1][-200:]),),
                  lv6_a["code"] == 0 and lv6_so[0] == 0
                  and not os.path.exists(lv_path(lv6_proj))
                  and "released phase-P3" in lv6_so[1])

            # A SIGN-OFF BY A SESSION THAT NEVER HELD THE LOCK was not taken over,
            # and must not be told it was.
            lv7_proj, _lv7_mp = pc_repo("lv-nonholder")
            lv7_a = lv_start(lv7_proj, "s-lv-a", _lv_pa.pid)
            lv7_so = lv_signoff(lv7_proj, "s-lv-b", _lv_pb.pid)
            check("lv7 a sign-off by a non-holder while the holder is live says "
                  "the lock was LEFT IN PLACE and names the live holder - never "
                  "that this run was taken over: %r"
                  % ((lv7_a["code"], lv7_so[0],
                      [ln for ln in lv7_so[1].splitlines() if "phase lock" in ln]),),
                  lv7_a["code"] == 0 and lv7_so[0] == 0
                  and os.path.exists(lv_path(lv7_proj))
                  and "left in place" in lv7_so[1]
                  and "s-lv-a" in lv7_so[1]
                  and "took it over" not in lv7_so[1])
            lv8_proj, _lv8_mp = pc_repo("lv-takenover")
            lv8_a = lv_start(lv8_proj, "s-lv-a", _lv_pa.pid)
            lv8_tk = lv_lock(lv8_proj, ["acquire", "phase-P3", "--takeover",
                                        "--note", M._START_LOCK_NOTE],
                             "s-lv-b", _lv_pb.pid)
            lv8_so = lv_signoff(lv8_proj, "s-lv-a", _lv_pa.pid)
            check("lv8 ALLOW: a sign-off by the run whose lock WAS taken over "
                  "keeps the takeover wording: %r"
                  % ((lv8_a["code"], lv8_tk[0], lv8_so[0],
                      [ln for ln in lv8_so[1].splitlines() if "phase lock" in ln]),),
                  lv8_a["code"] == 0 and lv8_tk[0] == 0 and lv8_so[0] == 0
                  and "took it over" in lv8_so[1]
                  and "left in place" not in lv8_so[1])

            def lv_lock_lines(text):
                return [ln for ln in text.splitlines() if "phase lock" in ln]

            def lv_rewrite(proj, changes):
                info = _locks.read_lock(lv_path(proj))
                info.update(changes)
                _panel_write._atomic_write_json(lv_path(proj), info)
                return info

            # NOT TAKEN OVER IS DECIDED BY THE LOCK'S OWN RECORD, not by whether
            # its holder reads live: a start lock judged by its age, or one from
            # another host, is still somebody else's that this session never held.
            lv13_proj, _lv13_mp = pc_repo("lv-aged")
            lv13_a = lv_start(lv13_proj, "s-lv-a", None)
            lv13_lock = lv_rewrite(lv13_proj, {"startedAt": "2020-01-01T00:00:00Z"})
            lv13_so = lv_signoff(lv13_proj, "s-lv-b", _lv_pb.pid)
            check("lv13 a sign-off by a non-holder over a start lock with no pid "
                  "and past the age limit says the lock was LEFT IN PLACE, names "
                  "the holder and the age basis, never that it was taken over: %r"
                  % ((lv13_a["code"], lv13_lock.get("pid"), lv13_so[0],
                      lv_lock_lines(lv13_so[1])),),
                  lv13_a["code"] == 0 and "pid" not in lv13_lock
                  and lv13_so[0] == 0 and os.path.exists(lv_path(lv13_proj))
                  and "left in place" in lv13_so[1]
                  and "s-lv-a" in "".join(lv_lock_lines(lv13_so[1]))
                  and "threshold" in "".join(lv_lock_lines(lv13_so[1]))
                  and "took it over" not in lv13_so[1])
            lv14_proj, _lv14_mp = pc_repo("lv-foreign")
            lv14_a = lv_start(lv14_proj, "s-lv-a", _lv_pa.pid)
            lv_rewrite(lv14_proj, {"hostname": "elsewhere",
                                   "startedAt": "2020-01-01T00:00:00Z"})
            lv14_so = lv_signoff(lv14_proj, "s-lv-b", _lv_pb.pid)
            check("lv14 the same for an old start lock recorded on another host: "
                  "LEFT IN PLACE, with the foreign-host basis: %r"
                  % ((lv14_a["code"], lv14_so[0], lv_lock_lines(lv14_so[1])),),
                  lv14_a["code"] == 0 and lv14_so[0] == 0
                  and os.path.exists(lv_path(lv14_proj))
                  and "left in place" in lv14_so[1]
                  and "not this host" in "".join(lv_lock_lines(lv14_so[1]))
                  and "took it over" not in lv14_so[1])
            # The twin: the same foreign lock recording that it took over FROM the
            # signing session keeps the takeover sentence.
            lv15_proj, _lv15_mp = pc_repo("lv-foreign-taken")
            lv15_a = lv_start(lv15_proj, "s-lv-a", _lv_pa.pid)
            lv_rewrite(lv15_proj, {"hostname": "elsewhere",
                                   "startedAt": "2020-01-01T00:00:00Z",
                                   "takenOverFrom": {"sessionId": "s-lv-b"}})
            lv15_so = lv_signoff(lv15_proj, "s-lv-b", _lv_pb.pid)
            check("lv15 ALLOW: the same foreign-host lock recording a takeover "
                  "from the signing session keeps the takeover wording: %r"
                  % ((lv15_a["code"], lv15_so[0], lv_lock_lines(lv15_so[1])),),
                  lv15_a["code"] == 0 and lv15_so[0] == 0
                  and "took it over" in lv15_so[1]
                  and "left in place" not in lv15_so[1])

            # A RESUMED RUN GIVES BACK THE LOCK IT RE-RECORDED. The orchestrator
            # releases at the end only what its acquire said was this call's, so
            # an acquire that re-records its own session's lock from a dead pid
            # must say it holds it now - or the lock outlives the run.
            _lv_r1, _lv_r2 = lv_sleeper(), lv_sleeper()
            _lv_procs.extend([_lv_r1, _lv_r2])
            lv16_proj, _lv16_mp = pc_repo("lv-resumed")
            lv16_acq1 = lv_lock(lv16_proj, ["acquire", "phase-P3", "--note",
                                            "phase run"], "s-lv-a", _lv_r1.pid)
            lv16_st1 = lv_start(lv16_proj, "s-lv-a", _lv_r1.pid)
            lv_kill(_lv_r1)
            lv16_acq2 = lv_lock(lv16_proj, ["acquire", "phase-P3", "--note",
                                            "phase run"], "s-lv-a", _lv_r2.pid)
            lv16_acq3 = lv_lock(lv16_proj, ["acquire", "phase-P3", "--note",
                                            "phase run"], "s-lv-a", _lv_r2.pid)
            lv16_st2 = lv_start(lv16_proj, "s-lv-a", _lv_r2.pid)
            lv16_so = lv_signoff(lv16_proj, "s-lv-a", _lv_r2.pid)
            lv16_held = _locks.read_lock(lv_path(lv16_proj))
            lv16_rel = lv_lock(lv16_proj, ["release", "phase-P3"], "s-lv-a",
                               _lv_r2.pid)
            check("lv16 a resumed run's acquire over its own lock naming a dead "
                  "pid says the lock was re-recorded and is this call's - not "
                  "'already yours' - so its release at the end leaves no lock: %r"
                  % ((lv16_acq1[0], lv16_st1["code"], lv16_acq2,
                      lv16_st2["code"], lv16_so[0], lv16_held.get("pid"),
                      lv16_rel),),
                  lv16_acq1[0] == 0 and lv16_st1["code"] == 0
                  and lv16_acq2[0] == 0
                  and "re-recorded" in lv16_acq2[1]
                  and "already yours" not in lv16_acq2[1]
                  and "not this call's" not in lv16_acq2[1]
                  and lv16_st2["code"] == 0 and lv16_so[0] == 0
                  and lv16_held.get("pid") == _lv_r2.pid
                  and lv16_rel[0] == 0
                  and not os.path.exists(lv_path(lv16_proj)))
            check("lv17 ALLOW: a second acquire in the same resumed run, its "
                  "holder now live, is still 'already yours' and not this "
                  "call's to give back: %r" % (lv16_acq3,),
                  lv16_acq3[0] == 0 and "already yours" in lv16_acq3[1]
                  and "not yours to give back" in lv16_acq3[1])

            # A LIVE RECORDED HOLDER IS NOT RE-RECORDED. A start of the same
            # session under another live process leaves the lock naming the
            # process that took it, so that process's release still works. lv1 is
            # the twin: a dead recorded holder IS re-recorded.
            _lv_ra, _lv_rb = lv_sleeper(), lv_sleeper()
            _lv_procs.extend([_lv_ra, _lv_rb])
            lv18_proj, _lv18_mp = pc_repo("lv-live-refresh")
            lv18_acq = lv_lock(lv18_proj, ["acquire", "phase-P3", "--note",
                                           "phase run"], "s-lv-a", _lv_ra.pid)
            lv18_st = lv_start(lv18_proj, "s-lv-a", _lv_rb.pid)
            lv18_lock = _locks.read_lock(lv_path(lv18_proj))
            lv18_rel = lv_lock(lv18_proj, ["release", "phase-P3"], "s-lv-a",
                               _lv_ra.pid)
            check("lv18 a same-session start under a second LIVE process leaves "
                  "the lock naming the live process that took it, and that "
                  "process's release gives it back: %r"
                  % ((lv18_acq[0], lv18_st["code"], lv18_lock.get("pid"),
                      _lv_ra.pid, lv18_rel),),
                  lv18_acq[0] == 0 and lv18_st["code"] == 0
                  and lv18_lock.get("pid") == _lv_ra.pid
                  and lv18_rel[0] == 0 and "taken over" not in lv18_rel[1]
                  and not os.path.exists(lv_path(lv18_proj)))

            # A CALLER THAT IS NOT KNOWN TO BE THE HOLDER'S SESSION does not
            # re-take a yielding start lock or a claim. lv5 is the twin: the same
            # session's acquire re-takes the yielding lock.
            lv19_proj, _lv19_mp = pc_repo("lv-sessionless")
            lv19_a = lv_start(lv19_proj, "s-lv-a", _lv_pa.pid)
            with open(lv_path(lv19_proj), "rb") as _fh:
                lv19_before = _fh.read()
            lv19_acq = lv_lock(lv19_proj, ["acquire", "phase-P3", "--note",
                                           "phase run"], None, _lv_pa.pid)
            with open(lv_path(lv19_proj), "rb") as _fh:
                lv19_after = _fh.read()
            check("lv19 a hand-off acquire with no session id and the holder's "
                  "$CLAUDE_PID leaves the start's yielding lock byte for byte: %r"
                  % ((lv19_a["code"], lv19_acq),),
                  lv19_a["code"] == 0 and lv19_after == lv19_before
                  and "from this session's own yielding claim" not in lv19_acq[1])
            lv20_proj, lv20_mp = pc_repo("lv-shared-pid")
            lv20_a = lv_start(lv20_proj, "s-lv-a", _lv_pa.pid)
            lv20_lock = _locks.read_lock(lv_path(lv20_proj))
            lv20_before = lv_shard_bytes(lv20_proj, lv20_mp)
            lv20_b = lv_start(lv20_proj, "s-lv-b", _lv_pa.pid)
            check("lv20 another session sharing the holder's $CLAUDE_PID is not "
                  "the holder: its start is REFUSED, the shard byte identical and "
                  "the lock untouched: %r"
                  % ((lv20_a["code"], lv20_b["code"],
                      lv20_b["json"].get("claimAction"), lv20_b["txt"][:200]),),
                  lv20_a["code"] == 0 and lv20_b["code"] == 2
                  and lv_shard_bytes(lv20_proj, lv20_mp) == lv20_before
                  and _locks.read_lock(lv_path(lv20_proj)) == lv20_lock)

            # A START REPORTS A LOCK AS ITS OWN TAKE ONLY WHEN IT IS THE START'S.
            # A resumed session's start re-records its own lock from a dead pid
            # onto the live one; when that lock is the orchestrator's, sign-off
            # leaves it (it releases only the start's note), so the start's line
            # must not promise sign-off gives it back. The twin runs the same
            # flow over a lock the start itself took.
            def lv_resumed_flow(name, orchestrated):
                p0, p1 = lv_sleeper(), lv_sleeper()
                _lv_procs.extend([p0, p1])
                proj, _mp = pc_repo(name)
                acq = (lv_lock(proj, ["acquire", "phase-P3", "--note",
                                      "phase run"], "s-lv-a", p0.pid)
                       if orchestrated else (0, ""))
                first = lv_start(proj, "s-lv-a", p0.pid)
                lv_kill(p0)
                again = lv_call(_lv_task_py, proj,
                                ["start", "P3.1", "--project-dir", proj],
                                "s-lv-a", p1.pid)
                so = lv_signoff(proj, "s-lv-a", p1.pid)
                held = (_locks.read_lock(lv_path(proj))
                        if os.path.exists(lv_path(proj)) else None)
                return {"acq": acq[0], "first": first["code"],
                        "again": again[0], "line": lv_lock_lines(again[1]),
                        "so": so[0], "soLines": lv_lock_lines(so[1]),
                        "held": held, "p0": p0.pid, "p1": p1.pid}

            lv23 = lv_resumed_flow("lv-resumed-orch", True)
            lv23_line = "".join(lv23["line"])
            lv23_held = lv23["held"] or {}
            check("lv23 a resumed hand start over the orchestrator's 'phase run' "
                  "lock whose pid died does NOT call it its own take: its line "
                  "says the lock was re-recorded and keeps its hold's note, and "
                  "after sign-off the lock file agrees - still held, note "
                  "'phase run', pid of the live run, refreshedFrom the dead one: %r"
                  % (lv23,),
                  lv23["acq"] == 0 and lv23["first"] == 0 and lv23["again"] == 0
                  and len(lv23["line"]) == 1
                  and "re-recorded" in lv23_line and "phase run" in lv23_line
                  and "gives it back" not in lv23_line
                  and "taken for this session" not in lv23_line
                  and lv23["so"] == 0 and not lv23["soLines"]
                  and lv23_held.get("note") == "phase run"
                  and lv23_held.get("pid") == lv23["p1"]
                  and lv23_held.get("refreshedFrom") == lv23["p0"])
            lv24 = lv_resumed_flow("lv-resumed-start", False)
            lv24_line = "".join(lv24["line"])
            check("lv24 ALLOW: the same flow over a lock the start itself took "
                  "is the start's take - its line says sign-off gives it back, "
                  "and sign-off does release it: %r" % (lv24,),
                  lv24["first"] == 0 and lv24["again"] == 0
                  and len(lv24["line"]) == 1
                  and "taken for this session" in lv24_line
                  and "gives it back" in lv24_line
                  and lv24["so"] == 0
                  and any("released phase-P3" in ln for ln in lv24["soLines"])
                  and lv24["held"] is None)
        finally:
            for _lv_proc in _lv_procs:
                lv_kill(_lv_proc)

        # AN EXCEPTION BETWEEN THE LOCK TAKE AND THE VALIDATED WRITE gives the
        # lock back. Driven in process, because the injection is a replaced
        # function; the token the take carries is restored with the environment.
        _lv_env_was = dict((k, os.environ.get(k)) for k in
                           ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PID",
                            _locks.TOKEN_ENV))
        _lv_start_task = M._start_task

        def lv_boom(*_a, **_k):
            raise RuntimeError("injected between the lock take and the write")
        try:
            os.environ["CLAUDE_CODE_SESSION_ID"] = "s-lv-x"
            os.environ["CLAUDE_PID"] = str(os.getpid())
            lv9_proj, lv9_mp = pc_repo("lv-raise")
            lv9_before = lv_shard_bytes(lv9_proj, lv9_mp)
            M._start_task = lv_boom
            try:
                lv9_code, lv9_txt = run(["start", "P3.1", "--project-dir", lv9_proj])
            finally:
                M._start_task = _lv_start_task
            check("lv9 an exception injected between the lock take and the write "
                  "leaves NO phase lock and the shard as it was: %r"
                  % ((lv9_code, lv9_txt[-200:],
                      os.path.exists(lv_path(lv9_proj))),),
                  lv9_code != 0 and "injected" in lv9_txt
                  and not os.path.exists(lv_path(lv9_proj))
                  and lv_shard_bytes(lv9_proj, lv9_mp) == lv9_before)
            lv10_proj, _lv10_mp = pc_repo("lv-raise-ours")
            pc_lock(lv10_proj, os.getpid(), "s-lv-x")
            with open(lv_path(lv10_proj), "rb") as _fh:
                lv10_before = _fh.read()
            M._start_task = lv_boom
            try:
                lv10_code, _lv10_txt = run(["start", "P3.1", "--project-dir",
                                            lv10_proj])
            finally:
                M._start_task = _lv_start_task
            lv10_after = b""
            if os.path.exists(lv_path(lv10_proj)):
                with open(lv_path(lv10_proj), "rb") as _fh:
                    lv10_after = _fh.read()
            # The other direction: the rollback gives back only a lock this start
            # took. An unconditional release would take the orchestrator's.
            check("lv10 ALLOW: the same exception under a phase lock this start "
                  "did NOT take leaves that lock byte for byte: %r" % (lv10_code,),
                  lv10_code != 0 and lv10_after == lv10_before)
            lv11_proj, _lv11_mp = pc_repo("lv-noraise")
            lv11_code, _lv11_txt = run(["start", "P3.1", "--project-dir",
                                        lv11_proj])
            check("lv11 ALLOW: with nothing injected the same start keeps the lock "
                  "it took: %r" % (lv11_code,),
                  lv11_code == 0 and os.path.exists(lv_path(lv11_proj)))

            # A FAILED START GIVES BACK ONLY A LOCK THAT IS THE START'S. This
            # session's lock naming a dead pid is re-recorded under the run
            # asking either way; the orchestrator's stays for its run to release,
            # and the start's own is given back with the rolled-back write.
            def lv_failed_resume(name, note):
                proj, _mp = pc_repo(name)
                ld = _locks.lock_dir(proj)
                os.makedirs(ld, exist_ok=True)
                _panel_write._atomic_write_json(
                    lv_path(proj),
                    {"sessionId": "s-lv-x", "pid": pc_gone_pid(),
                     "hostname": platform.node(), "handedOff": True,
                     "startedAt": "2026-01-01T00:00:00Z", "note": note})
                M._start_task = lv_boom
                try:
                    code, _txt = run(["start", "P3.1", "--project-dir", proj])
                finally:
                    M._start_task = _lv_start_task
                return {"code": code,
                        "lock": (_locks.read_lock(lv_path(proj))
                                 if os.path.exists(lv_path(proj)) else None)}

            lv25 = lv_failed_resume("lv-raise-orch", "phase run")
            check("lv25 a failed start over this session's 'phase run' lock "
                  "naming a dead pid leaves that lock in place, re-recorded "
                  "under the live run with its note kept: %r" % (lv25,),
                  lv25["code"] != 0 and lv25["lock"] is not None
                  and lv25["lock"].get("note") == "phase run"
                  and lv25["lock"].get("pid") == os.getpid())
            lv26 = lv_failed_resume("lv-raise-startnote", M._START_LOCK_NOTE)
            check("lv26 ALLOW: the same failed start over the start's own lock "
                  "naming a dead pid gives that lock back: %r" % (lv26,),
                  lv26["code"] != 0 and lv26["lock"] is None)

            # A RAISE AFTER THE WRITE LANDED restores the claim WITH the lock:
            # giving back only the lock left a claim no lock stood behind. The
            # injection is the branch cut, the one step that runs after the
            # validated write, made to raise rather than refuse.
            _lv_entry = M._phase_entry
            _lv_run = subprocess.run

            def lv_cut_entry(git_root, meta, phase):
                head = _lv_run(["git", "-C", git_root, "rev-parse", "HEAD"],
                               stdout=subprocess.PIPE).stdout.decode().strip()
                return {"state": "cut", "refusal": None, "branch": "audit/p3-cut",
                        "parent": "audit/p3", "baseRef": head}

            def lv_cut_raises(argv, *a, **k):
                if isinstance(argv, list) and "switch" in argv:
                    raise RuntimeError("injected after the write landed")
                return _lv_run(argv, *a, **k)

            def lv_cut_start(name, boom):
                proj, mp = pc_repo(name)
                before = lv_shard_bytes(proj, mp)
                M._phase_entry = lv_cut_entry
                if boom:
                    subprocess.run = lv_cut_raises
                try:
                    code, txt = run(["start", "P3.1", "--project-dir", proj])
                finally:
                    M._phase_entry = _lv_entry
                    subprocess.run = _lv_run
                return {"code": code, "txt": txt,
                        "same": lv_shard_bytes(proj, mp) == before,
                        "claim": (pc_shard(mp, "P3") or {}).get("claim"),
                        "lock": os.path.exists(lv_path(proj))}

            lv21 = lv_cut_start("lv-raise-after", True)
            check("lv21 a raise after the write landed restores the shard - no "
                  "claim left - and gives the lock back with it: %r"
                  % ((lv21["code"], lv21["same"], lv21["claim"], lv21["lock"],
                      lv21["txt"][-200:]),),
                  lv21["code"] != 0 and "injected" in lv21["txt"]
                  and lv21["same"] and lv21["claim"] is None
                  and not lv21["lock"])
            lv22 = lv_cut_start("lv-noraise-after", False)
            check("lv22 ALLOW: the same cut with nothing raised keeps the claim "
                  "and the lock together: %r"
                  % ((lv22["code"], lv22["claim"], lv22["lock"],
                      lv22["txt"][-200:]),),
                  lv22["code"] == 0 and not lv22["same"]
                  and (lv22["claim"] or {}).get("sessionId") == "s-lv-x"
                  and lv22["lock"])

            # ONE PREDICATE FOR "THE HOLDER IS GONE": `_phase_holder` reads it
            # from `_locks`, so a change to it changes this reading too.
            # No $CLAUDE_PID here: the planted lock records this suite's pid, and
            # with the variable naming it too the lock would read as this run's.
            os.environ.pop("CLAUDE_PID", None)
            lv12_proj, _lv12_mp = pc_repo("lv-gone")
            pc_lock(lv12_proj, os.getpid(), "s-lv-other")
            _lv_had = hasattr(_locks, "holder_gone")
            _lv_gone_was = getattr(_locks, "holder_gone", None)
            _locks.holder_gone = lambda *_a, **_k: True
            try:
                lv12 = M._phase_holder(lv12_proj, "P3")
            finally:
                if _lv_had:
                    _locks.holder_gone = _lv_gone_was
                else:
                    del _locks.holder_gone
            lv12b = M._phase_holder(lv12_proj, "P3")
            check("lv12 `_phase_holder` decides a lock's holder is gone through "
                  "`_locks.holder_gone`: forced true it reads a live lock dead, "
                  "and left alone the same lock reads live: %r" % ((lv12, lv12b),),
                  lv12.get("state") == "dead" and lv12b.get("state") == "live")
        finally:
            M._start_task = _lv_start_task
            for _k, _v in _lv_env_was.items():
                if _v is None:
                    os.environ.pop(_k, None)
                else:
                    os.environ[_k] = _v

        # ---- (pd) `done`: the close, and the SHA that makes it a record -------
        # THE LOSS, from this repository and not from a scenario. With no verb
        # for the close, the orchestrator hand-wrote a task's completion into the
        # phase shard AND the manifest index; a later `git reset --hard` reverted
        # the index, the shard turned out never to have carried the marks at all,
        # and the record of three finished tasks survived only in their commit
        # subjects - rebuilt afterwards out of `git log`. `start` gave the
        # promotion a verb (the `pr` group above) and left the close a hand edit,
        # which is the half that still has to be true a month later.
        _PD_SHA = "0123456789abcdef0123456789abcdef01234567"

        def pd_fixture(last=False):
            fx = base_manifest()
            if last:
                # ...so the task closed below is the LAST open one in P2, which
                # is the phase question this verb had to settle.
                fx["phases"][1]["tasks"][1]["status"] = "done"
            fx["phases"][1]["tasks"].append(
                {"id": "P2.4", "title": "running", "status": "in_progress",
                 "description": "", "files": ["src/fresh.ts"],
                 "tests": {"mode": "gate-only", "add": [],
                           "expectRedFirst": False, "gate": ["test"]},
                 "model": "sonnet", "skills": [], "risk": "low",
                 "blockedBy": [], "dependsOn": [], "attempts": 1,
                 "maxAttempts": 3, "commit": None,
                 # A HALF THAT IS ALREADY WRITTEN, on purpose: step 4's
                 # test-failure arm puts the last red gate's reason here and the
                 # retry brief quotes it back, so `pd2` can ask whether a close
                 # that mentions neither half leaves it standing.
                 "outcome": {"technical": "attempt 1: gate red on t_checkout",
                             "descriptive": None},
                 "startedAt": "2026-01-01T00:00:00Z", "completedAt": None,
                 "verifiedBy": []})
            fx["fileIndex"]["src/fresh.ts"] = ["P2.4"]
            return fx

        def pd_repo(name, manifest):
            """A fixture whose project really IS a git repository with a commit.

            A REAL REPO RATHER THAN A STUB, for `test__commit_trail.py`'s reason
            one module over: the question this verb asks is whether git resolves
            a SHA, and a fake answer to it would be the suite agreeing with the
            code about a third party neither of them asked.
            """
            proj, mpath = mk(name, manifest, git=True)
            for argv in (["config", "user.email", "t@example.com"],
                         ["config", "user.name", "Test User"],
                         ["add", "-A"], ["commit", "-qm", "seed"]):
                subprocess.run(["git", "-C", proj] + argv,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            head = subprocess.run(["git", "-C", proj, "rev-parse", "HEAD"],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
            return proj, mpath, head.stdout.decode("utf-8", "replace").strip()

        projpd, mppd = mk("dn-close", pd_fixture())
        codepd, txtpd = run(["done", "P2.4", "--project-dir", projpd,
                             "--commit", _PD_SHA,
                             "--descriptive", "checkout no longer double-charges",
                             "--verified-by", "t_double_charge, t_refund"]
                            + _NOT_ASKED)
        tpd = task_in(mppd, "P2.4")
        check("pd1 a started task closes with `reference/orchestrator.md` step "
              "4's OWN fields and nothing besides - 4b's status and stamp, 4c's "
              "SHA - and the fields it was not told about are untouched: %r"
              % ((codepd, tpd.get("status"), tpd.get("commit"),
                  tpd.get("verifiedBy")),),
              codepd == 0 and tpd.get("status") == "done"
              and tpd.get("commit") == _PD_SHA
              and isinstance(tpd.get("completedAt"), str)
              and tpd.get("completedAt").endswith("Z")
              and tpd.get("verifiedBy") == ["t_double_charge", "t_refund"]
              and tpd.get("attempts") == 1
              and tpd.get("startedAt") == "2026-01-01T00:00:00Z"
              and tpd.get("files") == ["src/fresh.ts"])
        check("pd2 THE OUTCOME HALVES MOVE ONLY WHEN THE CALLER NAMES THEM, and "
              "the half nobody named still says what the failed attempt left "
              "there. A close that wrote the whole object would delete the last "
              "red gate's own words - the sentence the retry brief quotes - on "
              "its way to recording that the work arrived: %r"
              % (tpd.get("outcome"),),
              (tpd.get("outcome") or {}).get("descriptive")
              == "checkout no longer double-charges"
              and (tpd.get("outcome") or {}).get("technical")
              == "attempt 1: gate red on t_checkout")

        # THE SHA IS THE VERB. Three refusals guard it and they fail for three
        # different reasons, so they are driven apart: no flag at all, a value
        # that is not an object id, and an id this clone can answer for and does
        # not have.
        projns, mpns = mk("dn-nosha", pd_fixture())
        with open(mpns, "rb") as _fh:
            _pd_ns_before = _fh.read()
        _pd_nosha = run(["done", "P2.4", "--project-dir", projns])
        _pd_head = run(["done", "P2.4", "--project-dir", projns,
                        "--commit", "HEAD"])
        _pd_branch = run(["done", "P2.4", "--project-dir", projns,
                          "--commit", "main"])
        with open(mpns, "rb") as _fh:
            _pd_ns_after = _fh.read()
        check("pd3 a close with NO --commit is refused, and the manifest is byte "
              "identical: a done task carrying no SHA is the state /audit:doctor "
              "already reports, and `done` is terminal here so nothing in this "
              "file could correct it afterwards: %r" % (_pd_nosha[1][:120],),
              _pd_nosha[0] == 2 and "needs --commit" in _pd_nosha[1]
              and _pd_ns_after == _pd_ns_before)
        check("pd4 ...and a NAME is refused before git is asked at all. `HEAD` "
              "and a branch both RESOLVE, so a check that only asked git would "
              "write one into a field the schema calls a SHA, where it goes on "
              "meaning whatever it points at later - and this is the arm that "
              "still fires on a machine with no git: %r"
              % ((_pd_head[0], _pd_branch[0], _pd_head[1][:90]),),
              _pd_head[0] == 2 and _pd_branch[0] == 2
              and "SHA" in _pd_head[1] and "SHA" in _pd_branch[1]
              and _pd_ns_after == _pd_ns_before)

        projgt, mpgt, _pd_head_sha = pd_repo("dn-git", pd_fixture())
        with open(mpgt, "rb") as _fh:
            _pd_gt_before = _fh.read()
        _pd_bogus = run(["done", "P2.4", "--project-dir", projgt,
                         "--commit", "0" * 40])
        with open(mpgt, "rb") as _fh:
            _pd_gt_after = _fh.read()
        check("pd5 a SHA git CAN be asked about and does not have is refused, "
              "nothing written: writing one would put /audit:doctor's "
              "'fabricated or collected SHA' finding into the manifest "
              "deliberately, and its remedy nulls the trail: %r"
              % (_pd_bogus[1][:120],),
              _pd_bogus[0] == 2 and _pd_gt_after == _pd_gt_before
              and "0" * 12 in _pd_bogus[1]
              and _pd_head_sha != "" and len(_pd_head_sha) == 40)
        _pd_real = run(["done", "P2.4", "--project-dir", projgt, "--json",
                        "--commit", _pd_head_sha] + _NOT_ASKED)
        _pd_real_json = {}
        try:
            _pd_real_json = json.loads(_pd_real[1])
        except Exception:
            pass
        check("pd5b ALLOW CASE, and it is the direction the refusal above breaks "
              "in: the repository's REAL head closes the task and the report "
              "says the SHA was verified. A guard widened until it convicted "
              "every SHA would be routed around inside the day: %r"
              % ((_pd_real[0], _pd_real_json.get("commitVerified")),),
              _pd_real[0] == 0 and _pd_real_json.get("commitVerified") is True
              and (task_in(mpgt, "P2.4") or {}).get("commit") == _pd_head_sha)
        # THE UNASKED QUESTION, which is `_commit_trail.is_shallow`'s rule read
        # forward: with no repository to ask, `rev-parse` failing says the
        # question was never put. Refusing here would refuse honest closes on
        # CI's default (shallow) checkout and then send the operator to
        # `repair-commits.py --apply`, which NULLS an intact trail.
        _pd_unv = run(["done", "P2.4", "--project-dir", projns, "--json",
                       "--commit", "0" * 40] + _NOT_ASKED)
        _pd_unv_json = {}
        try:
            _pd_unv_json = json.loads(_pd_unv[1])
        except Exception:
            pass
        # ITS OWN PROJECT for the human line: `projns` has just closed P2.4, and
        # a second call there would answer `already done` - an exit-2 sentence
        # that carries no NOT VERIFIED and would make this read as green for the
        # wrong reason.
        projuh, _mpuh = mk("dn-unverified-human", pd_fixture())
        _pd_unv_human = run(["done", "P2.4", "--project-dir", projuh,
                             "--commit", "0" * 40] + _NOT_ASKED)
        check("pd5c ...and where git cannot be asked the same SHA is WRITTEN and "
              "SAID to be unverified, never refused: a project that is not a "
              "repository answers nothing, and a claim with no basis is reported "
              "as missing rather than guessed. The human line carries the word: "
              "%r" % ((_pd_unv[0], _pd_unv_json.get("commitVerified")),),
              _pd_unv[0] == 0
              and _pd_unv_json.get("commitVerified") is False
              and (task_in(mpns, "P2.4") or {}).get("commit") == "0" * 40
              and "NOT VERIFIED" in _pd_unv_human[1])

        # TERMINAL IS TERMINAL, `_locked_start`'s and `_locked_cancel`'s rule:
        # re-closing a finished task would rewrite history with no record of what
        # it said before, and a done task already carries a commit graded against
        # the scope it holds.
        projtd, mptd = mk("dn-terminal", pd_fixture())
        run(["cancel", "P2.3", "--reason", "dropped", "--project-dir", projtd])
        with open(mptd, "rb") as _fh:
            _pd_td_before = _fh.read()
        _pd_term = {}
        for _pdtid in ("P2.1", "P2.3"):
            _pd_term[_pdtid] = run(["done", _pdtid, "--project-dir", projtd,
                                    "--commit", _PD_SHA])
        with open(mptd, "rb") as _fh:
            _pd_td_after = _fh.read()
        check("pd6 a `done` task and a `cancelled` one are each refused BY NAME, "
              "and neither call wrote a byte: %r"
              % (dict((k, (v[0], v[1][:60])) for k, v in _pd_term.items()),),
              _pd_term["P2.1"][0] == 2 and _pd_term["P2.3"][0] == 2
              and "already done" in _pd_term["P2.1"][1]
              and "already cancelled" in _pd_term["P2.3"][1]
              and _pd_td_after == _pd_td_before)

        # NEVER STARTED IS A REFUSAL, NOT A WARNING, and the predicate is the one
        # this file already has: `_started` reads TWO independent signals, so a
        # task put back to `pending` carrying its count is not mistaken for one
        # that was never spawned. Both directions are driven, because the wrong
        # narrowing (status alone) is green on the first and red on the second.
        projus, mpus = mk("dn-unstarted", pd_fixture())
        with open(mpus, "rb") as _fh:
            _pd_us_before = _fh.read()
        _pd_never = run(["done", "P2.3", "--project-dir", projus,
                         "--commit", _PD_SHA])
        with open(mpus, "rb") as _fh:
            _pd_us_after = _fh.read()
        check("pd7 a task that was never started is refused: `pending` with no "
              "attempt means no spawn was ever written down, so the close would "
              "lay a TERMINAL state over a hole this file then refuses to "
              "re-decide - and it is the shape /audit:doctor grades as positive "
              "evidence of an edit outside the pipeline, so writing it would "
              "manufacture that finding. The refusal names the remedy: %r"
              % (_pd_never[1][-90:],),
              _pd_never[0] == 2 and _pd_us_after == _pd_us_before
              and "start P2.3" in _pd_never[1]
              and M._started({"status": "pending", "attempts": 0}) is False)
        _pd_back = pd_fixture()
        # THE SAME SHAPE AS ABOVE: a task that ran, failed and was put back to
        # `pending` carries the count with no status left to show for it.
        _pd_back["phases"][1]["tasks"][1]["attempts"] = 2
        projbk, mpbk = mk("dn-back-to-pending", _pd_back)
        _pd_ran = run(["done", "P2.3", "--project-dir", projbk,
                       "--commit", _PD_SHA] + _NOT_ASKED)
        check("pd7b SECOND DIRECTION, and it is the one a narrower predicate "
              "breaks: the SAME `pending` status with an attempt recorded DOES "
              "close, because the trail has the spawn in it. A guard reading "
              "`status` alone would refuse a legitimate close and be routed "
              "around: %r" % ((_pd_ran[0],
                               M._started({"status": "pending",
                                           "attempts": 2})),),
              _pd_ran[0] == 0
              and (task_in(mpbk, "P2.3") or {}).get("status") == "done"
              and M._started({"status": "pending", "attempts": 2}) is True)

        check("pd8 a PHASE id is refused rather than closed - a phase reaches "
              "done through SIGN-OFF, which writes a review verdict and a merge "
              "stamp beside the status - and an id resolving to nothing, or to "
              "no id at all, says so: %r"
              % ((run(["done", "P2", "--project-dir", projus,
                       "--commit", _PD_SHA])[1][:80],),),
              run(["done", "P2", "--project-dir", projus,
                   "--commit", _PD_SHA])[0] == 2
              and "PHASE" in run(["done", "P2", "--project-dir", projus,
                                  "--commit", _PD_SHA])[1]
              and run(["done", "P9.9", "--project-dir", projus,
                       "--commit", _PD_SHA])[0] == 2
              and run(["done", "", "--project-dir", projus,
                       "--commit", _PD_SHA])[0] == 2)

        # THE ROW. `task.complete` and `task.commit` are DERIVED by
        # `hooks/journal-writes.py` from the write itself and step 4c forbids
        # appending them by hand, so this verb's row is `task.done` - named after
        # the verb, the way `task.start` and `task.cancel` are.
        projjd, mpjd = mk("dn-journal", pd_fixture())
        run(["done", "P2.4", "--project-dir", projjd, "--commit", _PD_SHA,
             "--technical", "one module rewritten, cases added beside it"]
            + _NOT_ASKED)
        _pdjm = _panel_write._journalmod()
        _pd_all = _pdjm.read_all(projjd) if _pdjm else []
        _pd_rows = [r for r in _pd_all if r.get("action") == "task.done"]
        _pd_det = (_pd_rows[0].get("details") or {}) if _pd_rows else {}
        check("pd9 the trail carries ONE `task.done` row whose details are the "
              "allow-listed keys the writer means, with the status and the SHA "
              "it moved FROM - and NOT a `task.complete`, which "
              "`hooks/journal-writes.py` derives from this very write: two "
              "writers of one action means duplicate rows and a doctor whose "
              "completion count is no longer a count: %r"
              % ((sorted(_pd_det), [r.get("action") for r in _pd_all]),),
              len(_pd_rows) == 1
              and [r for r in _pd_all if r.get("action") == "task.complete"] == []
              and sorted(_pd_det) == ["changes", "commit", "completedAt",
                                      "phaseId", "taskId"]
              and _pd_det.get("commit") == _PD_SHA
              and _pd_det.get("taskId") == "P2.4"
              and [c for c in _pd_det["changes"] if c["field"] == "status"]
              == [{"id": "P2.4", "field": "status", "from": "in_progress",
                   "to": "done"}]
              and _PD_SHA[:12] in (_pd_rows[0].get("summary") or ""))
        # THE HANDOVER, NOT THE ROW, which is `pr9c`'s distinction one verb over:
        # `_journal_io` drops an unlisted key in SILENCE, so a row read back is
        # identical whether the writer handed over an allow-listed block or one
        # carrying an invented key beside it.
        import _journal_io as _pd_jio
        _pd_closed = {"status": "done", "completedAt": "Z", "commit": _PD_SHA,
                      "outcome": {"descriptive": "d", "technical": "t"},
                      "verifiedBy": ["t_one"]}
        _pd_hand = M._done_details(
            "P2.4", "P2", {"status": "in_progress", "completedAt": None,
                           "commit": None, "descriptive": None,
                           "technical": None, "verifiedBy": [],
                           "intentCheck": None},
            _pd_closed)
        check("pd9b ...and every key the WRITER hands over is on "
              "`_journal_io.DETAILS_KEYS`, asked of that module rather than of "
              "the row it produced - `commit` and `completedAt` are already "
              "there because the hook's own derived rows put them there, so this "
              "row invents no vocabulary: %r" % (sorted(_pd_hand),),
              set(_pd_hand) <= set(_pd_jio.DETAILS_KEYS)
              and all(set(c) <= set(_pd_jio.CHANGE_KEYS)
                      for c in _pd_hand["changes"])
              and len(_pd_hand["changes"]) <= _pd_jio.MAX_CHANGES)
        check("pd9c the `changes` list is the fields the call WROTE and no "
              "others: `status`, `completedAt` and `commit` every time, the "
              "outcome halves and `verifiedBy` only when the caller passed them, "
              "and `intentCheck` for the answer a close against a commit now "
              "always records. A row for an untouched field would claim a write "
              "that did not happen, which is the one thing a trail must never "
              "do: %r"
              % ([c["field"] for c in _pd_det["changes"]],),
              [c["field"] for c in _pd_det["changes"]]
              == ["status", "completedAt", "commit", "outcome.technical",
                  "intentCheck"])

        # THE PHASE QUESTION, SETTLED AND CHECKABLE IN BOTH DIRECTIONS.
        projls, mpls = mk("dn-last", pd_fixture(last=True))
        codels, txtls = run(["done", "P2.4", "--project-dir", projls, "--json",
                             "--commit", _PD_SHA] + _NOT_ASKED)
        _pd_last = {}
        try:
            _pd_last = json.loads(txtls)
        except Exception:
            pass
        _pd_phase = [p for p in (_mio.load_manifest(mpls).get("phases") or [])
                     if p.get("id") == "P2"]
        # `projpd` closed P2.4 at `pd1` and P2.3 was left pending, so it is
        # STARTED here before it is closed: the never-started refusal is `pd7`'s
        # subject and would otherwise answer this case instead.
        run(["start", "P2.3", "--project-dir", projpd])
        codelh, txtlh = run(["done", "P2.3", "--project-dir", projpd,
                             "--commit", _PD_SHA] + _NOT_ASKED)
        check("pd10 closing the LAST open task does NOT flip the phase, and the "
              "report says whose move that is. A phase reads done only once a "
              "verdict is recorded (`/audit:phase signoff`) and any branch has "
              "merged - so a verb flipping it here would be asserting a review "
              "and a merge it never saw: %r"
              % ((codels, _pd_last.get("phaseComplete"),
                  _pd_last.get("phaseStatus")),),
              codels == 0 and _pd_last.get("phaseComplete") is True
              and _pd_last.get("phaseOpenTasks") == []
              and _pd_last.get("phaseStatus") == "in_progress"
              and _pd_phase != [] and _pd_phase[0].get("status") == "in_progress"
              and "sign-off" in txtlh.lower()
              and "/audit:phase signoff P2" in txtlh)
        check("pd11 SECOND DIRECTION: a close that leaves work open reports the "
              "ids rather than the sign-off line, so the sentence above is a "
              "statement about this phase and not one the verb prints either "
              "way. `P2.3` was the last one here, and the earlier close in this "
              "same project named it as still open: %r"
              % ((codelh, txtlh.splitlines()[-2:]),),
              codelh == 0
              and "still has open work: P2.3" in txtpd
              and "no open task left" not in txtpd
              and "no open task left" in txtlh)

        # THE SHARDED LAYOUT, because a close writes a TASK and a task lives in
        # its phase's shard: a writer reaching for the index would leave a
        # manifest whose assembled task still said `in_progress` - which is the
        # exact half the hand edit got wrong when it wrote BOTH.
        projsd, mpsd = mk("dn-sharded", pd_fixture(), sharded=True)
        _sd_idx = _mio.read_json(mpsd)
        _sd_base = os.path.dirname(mpsd)
        _sd_of = dict((s.get("id"), os.path.join(_sd_base, s["shard"]))
                      for s in _sd_idx["phases"] if isinstance(s, dict))
        with open(_sd_of["P1"], "rb") as _fh:
            _sd_p1 = _fh.read()
        with open(mpsd, "rb") as _fh:
            _sd_index = _fh.read()
        codesd, _txtsd = run(["done", "P2.4", "--project-dir", projsd,
                              "--commit", _PD_SHA] + _NOT_ASKED)
        check("pd12 the sharded layout closes in the phase's SHARD, leaves an "
              "untouched phase's shard and the INDEX byte-identical, and the "
              "assembled manifest agrees with the shard - one place for one "
              "fact, which is the whole of the loss this verb answers: %r"
              % ((codesd, (task_in(mpsd, "P2.4") or {}).get("status")),),
              codesd == 0 and _mio.is_sharded(_sd_idx)
              and (task_in(mpsd, "P2.4") or {}).get("status") == "done"
              and (task_in(mpsd, "P2.4") or {}).get("commit") == _PD_SHA
              and open(_sd_of["P1"], "rb").read() == _sd_p1
              and open(mpsd, "rb").read() == _sd_index)

        # AN ALREADY-INVALID MANIFEST REFUSES BEFORE ANY WRITE, `pr13`'s rule for
        # this verb, and the two arms are told apart by their own words: dropping
        # the pre-check leaves the byte compare green, because the post-write arm
        # catches the same findings and rolls back to the same bytes.
        _pd_bad = pd_fixture()
        _pd_bad["phases"][1]["tasks"][-1]["blockedBy"] = ["NOPE"]
        projbd2, mpbd2 = mk("dn-invalid", _pd_bad)
        with open(mpbd2, "rb") as _fh:
            _pd_bd_before = _fh.read()
        codebd2, txtbd2 = run(["done", "P2.4", "--project-dir", projbd2,
                               "--commit", _PD_SHA])
        check("pd13 an already-invalid manifest refuses BEFORE the write: "
              "`nothing written` is the pre-check and `rolled back` is the other "
              "arm, and the exit code cannot tell them apart: %r"
              % (txtbd2[:90],),
              codebd2 == 1
              and "already invalid -- nothing written" in txtbd2
              and "rolled back" not in txtbd2
              and open(mpbd2, "rb").read() == _pd_bd_before)

        # ---- (rd) a close does not stand over a verdict that no longer holds ----
        # THE PROBE SEQUENCE: a gate run recorded red for the task, then `done`.
        # The commit verb refuses to commit over that verdict, and the close used
        # to write `done` over it anyway, so the record said finished while its
        # own newest measurement said failed. The rows are written by hand, as in
        # `test__verdict_binding.py`, so each arm is reached by exactly the row
        # that should reach it.
        import _evidence_io as _rd_ev
        import _journal_io as _rd_jio
        import _tree_stamp as _rd_ts
        # The trail's action name, spelled out: it is what a reader greps the
        # journal for, so the suite pins the literal rather than the constant.
        _RD_ACTION = "audit.verdict.close-overridden"

        def rd_ledger(proj, statuses, files=("src/fresh.ts",)):
            """P2.4's rows, oldest first and an hour apart, as `rd-0`, `rd-1`...
            A `passed` row carries the declared work's digest as it stands, so
            the allow case is BOUND rather than merely not refused."""
            ev = _rd_ev.evidence_dir(proj)
            os.makedirs(ev, exist_ok=True)
            digest = _rd_ts.scope_digest(proj, list(files))[0]
            with open(os.path.join(ev, "2026-09.rd.jsonl"), "w") as fh:
                for i, status in enumerate(statuses):
                    fh.write(json.dumps({
                        "runId": "rd-%d" % i,
                        "ts": "2026-09-01T0%d:00:00Z" % i, "scope": "task",
                        "taskId": "P2.4", "phaseId": "P2", "status": status,
                        "gateSource": "task", "steps": [{"name": "test"}],
                        "testedState": {"scopeDigest": digest}}) + "\n")

        def rd_rows(proj):
            return [r for r in _rd_jio.read_all(proj)
                    if r.get("action") == _RD_ACTION]

        projrd1, mprd1 = mk("dn-over-red", pd_fixture())
        rd_ledger(projrd1, ["passed", "failed"])
        coderd1, txtrd1 = run(["done", "P2.4", "--project-dir", projrd1,
                               "--commit", _PD_SHA] + _NOT_ASKED)
        check("rd1 RED-FIRST: done --commit over a task whose newest recorded "
              "gate verdict is red refuses, names the row, and writes nothing: "
              "exit %r, status %r, %r"
              % (coderd1, (task_in(mprd1, "P2.4") or {}).get("status"),
                 txtrd1[:300]),
              coderd1 == 2 and "rd-1" in txtrd1 and "`failed`" in txtrd1
              and "--override-verdict" in txtrd1
              and (task_in(mprd1, "P2.4") or {}).get("status") == "in_progress")
        coderd2, txtrd2 = run(["done", "P2.4", "--project-dir", projrd1,
                               "--commit", _PD_SHA, "--override-verdict",
                               "the red was a runner outage, re-run is green"]
                              + _NOT_ASKED)
        _rd2 = rd_rows(projrd1)
        check("rd2 RED-FIRST: an explicit --override-verdict closes it and "
              "journals the exception - ONE row naming the task, the red run "
              "and the reason: exit %r, rows %r, %r"
              % (coderd2, _rd2, txtrd2[-300:]),
              coderd2 == 0
              and (task_in(mprd1, "P2.4") or {}).get("status") == "done"
              and len(_rd2) == 1
              and (_rd2[0].get("details") or {}).get("runId") == "rd-1"
              and (_rd2[0].get("details") or {}).get("taskId") == "P2.4"
              and (_rd2[0].get("details") or {}).get("reason")
              == "the red was a runner outage, re-run is green")

        projrd3, mprd3 = mk("dn-green-newest", pd_fixture())
        rd_ledger(projrd3, ["failed", "passed"])
        coderd3, txtrd3 = run(["done", "P2.4", "--project-dir", projrd3,
                               "--commit", _PD_SHA] + _NOT_ASKED)
        check("rd3 ALLOW: a red retired by a later green closes with no flag, "
              "says which run it is bound to, and journals no exception: exit "
              "%r, %r" % (coderd3, txtrd3[-300:]),
              coderd3 == 0 and "gate: bound to run rd-1" in txtrd3
              and not rd_rows(projrd3))

        _rd_free = pd_fixture()
        _rd_free["phases"][1]["testGate"] = []
        _rd_free["phases"][1]["tasks"][-1]["tests"]["gate"] = []
        projrd4, mprd4 = mk("dn-no-gate", _rd_free)
        coderd4, txtrd4 = run(["done", "P2.4", "--project-dir", projrd4,
                               "--commit", _PD_SHA] + _NOT_ASKED)
        check("rd4 ALLOW: a task no gate measures closes and says so in the "
              "no-gate arm's own sentence: exit %r, %r"
              % (coderd4, txtrd4[-300:]),
              coderd4 == 0 and "gate: P2.4 declares no gate" in txtrd4
              and not rd_rows(projrd4))

        projrd5, mprd5 = mk("dn-nochange-red", pd_fixture())
        rd_ledger(projrd5, ["failed"])
        coderd5, txtrd5 = run(["done", "P2.4", "--project-dir", projrd5,
                               "--no-change", "--reason", "already correct"])
        check("rd5 a NO-CHANGE close asks the same question: its claim is that "
              "the code as it stands needed nothing, and the newest measurement "
              "of that code is red: exit %r, %r" % (coderd5, txtrd5[:300]),
              coderd5 == 2 and "rd-0" in txtrd5
              and (task_in(mprd5, "P2.4") or {}).get("status") == "in_progress")

        projrd6, mprd6 = mk("dn-over-red-unneeded", pd_fixture())
        rd_ledger(projrd6, ["passed"])
        coderd6, txtrd6 = run(["done", "P2.4", "--project-dir", projrd6,
                               "--commit", _PD_SHA, "--override-verdict", "x"]
                              + _NOT_ASKED)
        check("rd6 SECOND DIRECTION: --override-verdict with nothing to go over "
              "closes, says the reason was not needed, and journals NO "
              "exception - an override row with nothing overridden would "
              "count a gate removal that never happened: exit %r, %r"
              % (coderd6, txtrd6[-300:]),
              coderd6 == 0 and "not needed" in txtrd6 and not rd_rows(projrd6))

        # A GREEN OVER BYTES IT NEVER MEASURED: the declared file is written
        # after the passed run recorded its digest, so the close would vouch for
        # a measurement of other bytes.
        projrd7, mprd7 = mk("dn-digest-moved", pd_fixture())
        rd_ledger(projrd7, ["passed"])
        os.makedirs(os.path.join(projrd7, "src"), exist_ok=True)
        with open(os.path.join(projrd7, "src", "fresh.ts"), "w") as _fh:
            _fh.write("changed after the gate\n")
        coderd7, txtrd7 = run(["done", "P2.4", "--project-dir", projrd7,
                               "--commit", _PD_SHA] + _NOT_ASKED)
        check("rd7 RED-FIRST: done over a green whose declared files changed "
              "after the run refuses, names the run, and writes nothing: exit "
              "%r, %r" % (coderd7, txtrd7[:300]),
              coderd7 == 2 and "rd-0" in txtrd7
              and "have changed since it was measured" in txtrd7
              and (task_in(mprd7, "P2.4") or {}).get("status") == "in_progress")

        projrd8, mprd8 = mk("dn-no-run", pd_fixture())
        coderd8, txtrd8 = run(["done", "P2.4", "--project-dir", projrd8,
                               "--commit", _PD_SHA] + _NOT_ASKED)
        check("rd8 SECOND DIRECTION: a gate with no run recorded at all closes "
              "and says so - there is no measurement to vouch for: exit %r, %r"
              % (coderd8, txtrd8[-300:]),
              coderd8 == 0 and "no measurement to vouch for" in txtrd8
              and not rd_rows(projrd8))

        projrd9, mprd9 = mk("dn-journal-off", pd_fixture())
        _panel_write._atomic_write_json(
            os.path.join(projrd9, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json",
             "review": {"perTask": "always"},
             "journal": {"enabled": False}})
        rd_ledger(projrd9, ["failed"])
        with open(mprd9, "rb") as _fh:
            _rd9_before = _fh.read()
        coderd9, txtrd9 = run(["done", "P2.4", "--project-dir", projrd9,
                               "--commit", _PD_SHA, "--override-verdict", "x"]
                              + _NOT_ASKED)
        check("rd9 RED-FIRST: --override-verdict with journal.enabled false "
              "refuses BEFORE writing and names journal.enabled - an override "
              "recorded nowhere is a gate quietly removed: exit %r, %r"
              % (coderd9, txtrd9[:300]),
              coderd9 == 2 and "journal.enabled" in txtrd9
              and open(mprd9, "rb").read() == _rd9_before)

        # ---- (ic) a close records the intent answer, or that it received none ---
        # THE FAILURE MODE THIS IS WRITTEN AGAINST: an answer that is yes by
        # default. A close with no `--intent` must not read as one that agreed,
        # and a close that DID get an answer must name the diff (the commit) it
        # was given rather than a bare word.
        # The reviewer's answer reaches the close through its FILED return, which
        # is the only way a reviewer word closes a task against a commit.
        def ic_review(proj, answer):
            return run_on_stdin(["file-return", "P2.4", "--role", "reviewer",
                                 "--project-dir", proj], _fr_reviewer(answer))

        projic1, mpic1 = mk("dn-intent-matches", pd_fixture())
        ic_review(projic1, "matches")
        codeic1, txtic1 = run(["done", "P2.4", "--project-dir", projic1,
                               "--commit", _PD_SHA, "--intent", "matches"])
        ticm = task_in(mpic1, "P2.4")
        check("ic1 a close given `--intent matches` records the answer beside "
              "the SAME commit the close itself carried - the answer NAMES the "
              "diff it was given rather than floating free of it: %r"
              % (ticm.get("intentCheck"),),
              codeic1 == 0
              and ticm.get("intentCheck", {}).get("answer") == "matches"
              and ticm.get("intentCheck", {}).get("commit") == _PD_SHA
              and isinstance(ticm.get("intentCheck", {}).get("at"), str)
              and "matches" in txtic1)

        # A close against a commit can no longer record NO answer, so the absent
        # half is driven on the one close that still can: no change, no diff.
        projic2, mpic2 = mk("dn-intent-none", pd_fixture())
        codeic2, txtic2 = run(["done", "P2.4", "--project-dir", projic2,
                               "--no-change", "--reason", "already right"])
        ticn = task_in(mpic2, "P2.4")
        check("ic2 a close given NO --intent leaves `intentCheck` ABSENT - not a "
              "default word, and not a `None` answer field either: %r"
              % (ticn.get("intentCheck"),),
              codeic2 == 0 and "intentCheck" not in ticn
              and "NO ANSWER RECORDED" in txtic2)

        projic3, mpic3 = mk("dn-intent-diverges", pd_fixture())
        ic_review(projic3, "diverges")
        codeic3, _txtic3 = run(["done", "P2.4", "--project-dir", projic3,
                               "--commit", _PD_SHA])
        ticd = task_in(mpic3, "P2.4")
        check("ic3 NO ANSWER and a NEGATIVE answer are opposite facts and read "
              "as such: absent here, a real word there - a shared 'nothing to "
              "say' sentence would flatten them into one: %r"
              % ((ticn.get("intentCheck"), ticd.get("intentCheck")),),
              ticn.get("intentCheck") is None
              and ticd.get("intentCheck", {}).get("answer") == "diverges"
              and ticn.get("intentCheck") != ticd.get("intentCheck"))

        with open(mpic1, "rb") as _fh:
            _ic_before = _fh.read()
        # argparse's own usage error writes to the REAL stderr (`main` swallows
        # its SystemExit into a bare exit code and no text of its own), so this
        # is driven with stderr suppressed rather than read back - the same
        # pattern vf9 uses for the same reason.
        with open(os.devnull, "w") as _ic_null, \
                contextlib.redirect_stderr(_ic_null):
            codeic4, _txtic4 = run(["done", "P2.1", "--project-dir", projic1,
                                   "--commit", _PD_SHA, "--intent", "sideways"])
        with open(mpic1, "rb") as _fh:
            _ic_after = _fh.read()
        check("ic4 a word this flag does not recognise is refused before "
              "anything is written - argparse's own enum, so a typo cannot "
              "invent a fourth answer this schema was never told about: %r"
              % (codeic4,),
              codeic4 == 2 and _ic_after == _ic_before)

        _ic_jio = _panel_write._journalmod()
        _ic_rows = _ic_jio.read_all(projic1) if _ic_jio else []
        _ic_done = [r for r in _ic_rows if r.get("action") == "task.done"
                    and r.get("details", {}).get("taskId") == "P2.4"]
        _ic_changes = (_ic_done[0].get("details") or {}).get("changes") \
            if _ic_done else []
        _ic_field = [c for c in _ic_changes if c.get("field") == "intentCheck"]
        check("ic5 the close that DID carry an answer leaves a `changes` row "
              "naming the field, so the trail shows the write happened rather "
              "than leaving a reader to infer it from the task alone - the "
              "journal spells a structured value canonically, so `to` is the "
              "block's JSON text and not the from-nothing shape: %r"
              % (_ic_field,),
              len(_ic_field) == 1
              and _ic_field[0]["from"] is None
              and "\"answer\":\"matches\"" in _ic_field[0]["to"])

        # THE ORCHESTRATION DOCUMENT ITSELF NAMES THE FLAG, so the wiring above
        # is not a capability nothing tells an operator to use. `## Execute the
        # task` - where the per-task reviewer spawn and its close live - moved
        # into `reference/execute-task.md`, split off so a command that never
        # runs a task does not have to read it.
        with open(os.path.join(_output.PLUGIN_ROOT, "reference",
                               "execute-task.md"), "r", encoding="utf-8") as _ic_fh:
            _ic_orch = " ".join(_ic_fh.read().split())
        # The reviewer files through `drive-phase.py submit`, its last act, which
        # hands the return to `file-return` - the one write a filing makes.
        check("ic6 `reference/execute-task.md` tells the orchestrator that the "
              "reviewer's answer reaches the SAME close that carries `--commit` "
              "through the filed return, for whichever word it was, and names "
              "the one typed word a close may still carry - `not-asked` with "
              "its basis",
              "drive-phase.py submit <taskId> --role reviewer" in _ic_orch
              and "`audit-task.py file-return`" in _ic_orch
              and "--commit <sha> --from-return" in _ic_orch
              and "of the three words it was" in _ic_orch
              and "--intent not-asked --intent-basis" in _ic_orch)

        # ---- (tg) P45.1: the gate `add` DERIVES, and the basis it reports -----
        # A generated plan handed every task the phase's whole gate, so a phase of
        # nine tasks ran the full suite nine times to prove what the one sign-off
        # run proves; the operator who reported it retargeted them by hand and
        # then had to hand-edit `tests.gate` inside a shard three separate times,
        # which is the edit `commands/task.md` forbids. Both field reports said
        # the same thing. The input was already in hand: `--tests-add` was parsed
        # one line BELOW the copy of `phase.testGate`, and thrown away.
        #
        # THE BASIS IS ASSERTED IN EVERY CASE BELOW, including the ones where the
        # derived entries and the phase's happen to be equal. A gate that is right
        # for the wrong reason prints identically, and the third default (the wide
        # one) is reached both when it is correct and when the derivation quietly
        # failed - the sentence is the only thing that tells those apart.
        def gate_manifest():
            def seeded(tid, gate, files):
                return {"id": tid, "title": "seed", "status": "done",
                        "files": files,
                        "tests": {"mode": "gate-only", "add": [],
                                  "expectRedFirst": False, "gate": gate}}
            return {
                "meta": {"version": 2,
                         "buildCommands": {"lint": "npm run lint",
                                           "test": "npm test",
                                           "typecheck": "npm run typecheck",
                                           # A KEY THAT LOOKS LIKE A PATH. `tg7`
                                           # is the only case that can tell a
                                           # check reading the declaration from
                                           # one reading the punctuation.
                                           "web.spec": "npm test -- web"}},
                "phases": [
                    # P1: the spelling recorded IN the plan (commands/init.md
                    # step 5.3 - nothing else persists it).
                    {"id": "P1", "title": "Path-scoped", "status": "in_progress",
                     "testGate": ["lint", "test", "typecheck"],
                     "tasks": [seeded(
                         "P1.1",
                         ["lint", "npm test -- src/search/query.test.ts"],
                         ["src/search/query.ts"])]},
                    # P2: every sibling on the wide KEY. The phase gate carries
                    # one entry the sibling's does not, so a derivation that
                    # wrongly read P2.1 as a spelling would change the VALUE here
                    # and not only the sentence.
                    {"id": "P2", "title": "Wide keys", "status": "pending",
                     "testGate": ["lint", "test", "typecheck"],
                     "tasks": [seeded("P2.1", ["lint", "test"],
                                      ["src/cart/total.ts"])]},
                    # P3: a wide LITERAL - no key, no path. The arm that a
                    # loosened filename bound breaks.
                    {"id": "P3", "title": "Wide literal", "status": "pending",
                     "testGate": ["lint", "test"],
                     "tasks": [seeded("P3.1", ["npm test"],
                                      ["src/cart/stepper.ts"])]},
                    {"id": "P4", "title": "Keyed like a path",
                     "status": "pending", "testGate": ["lint"],
                     "tasks": [seeded("P4.1", ["web.spec"],
                                      ["src/web/app.ts"])]},
                    # P5: the same path-shaped KEY, this time riding alongside a
                    # real path-scoped entry. The only arrangement in which the
                    # copy-through arm of `_repointed` can be wrong.
                    {"id": "P5", "title": "Both at once", "status": "pending",
                     "testGate": ["lint", "test"],
                     "tasks": [seeded(
                         "P5.1",
                         ["web.spec", "npm test -- src/web/home.test.ts"],
                         ["src/web/home.ts"])]},
                ],
                "fileIndex": {"src/search/query.ts": ["P1.1"],
                              "src/cart/total.ts": ["P2.1"],
                              "src/cart/stepper.ts": ["P3.1"],
                              "src/web/app.ts": ["P4.1"],
                              "src/web/home.ts": ["P5.1"]},
                "bugs": [],
            }

        tg_proj, tg_mp = mk("tg-derive", gate_manifest())

        def tg_gate(tid):
            return ((task_in(tg_mp, tid) or {}).get("tests") or {}).get("gate")

        codetg, txttg = run(
            ["add", "Sanitize the sort parameter", "--phase", "P1",
             "--project-dir", tg_proj, "--tests-mode", "tdd",
             "--tests-add", "src/search/sort.test.ts: rejects an unknown key"])
        check("tg1 DEFAULT ONE: the task's own `tests.add` paths, in the "
              "sibling's spelling - the case the task promises to author is what "
              "its gate runs, and the report names which default it took: %r"
              % ((tg_gate("P1.2"), [ln for ln in txttg.split("\n")
                                    if ln.startswith("  gate:")]),),
              codetg == 0
              and tg_gate("P1.2") == ["lint",
                                      "npm test -- src/search/sort.test.ts"]
              and "narrowed to this task's tests.add paths, in P1.1's spelling" \
                  in txttg)
        check("tg1b ...and the shared key rides THROUGH untouched while only the "
              "path-scoped entry moves - `lint` has one scope for every task in "
              "the phase, so substituting into it would narrow nothing and lose "
              "the step: %r" % (tg_gate("P1.2"),),
              (tg_gate("P1.2") or [None])[0] == "lint")

        codetg, txttg = run(
            ["add", "Cache the facet counts", "--phase", "P1",
             "--project-dir", tg_proj, "--files",
             "src/search/facets.test.ts"])
        check("tg2 DEFAULT TWO: no case named, so the task's `files` go in "
              "instead - same spelling, same sibling, and the basis says which "
              "of the two it was. A SUITE PATH, deliberately: a gate-only task "
              "narrows only to a file `is_suite_path` accepts, so this fixture "
              "has to stay one for `tg2` to keep testing this arm rather than "
              "the gate-only-no-suite one `dg` below covers: %r"
              % ((tg_gate("P1.3"), codetg),),
              codetg == 0
              and tg_gate("P1.3") == [
                  "lint", "npm test -- src/search/facets.test.ts"]
              and "narrowed to this task's files, in P1.1's spelling" in txttg)

        codetg, txttg = run(
            ["add", "Two cases at once", "--phase", "P1",
             "--project-dir", tg_proj, "--tests-mode", "tdd",
             "--tests-add", "src/search/a.test.ts: one",
             "--tests-add", "src/search/b.test.ts: two"])
        check("tg3 every path goes in where the FIRST of the sibling's stood, so "
              "the flags around them survive a substitution nothing parsed - a "
              "gate that ran only the first case would be a green bought on half "
              "the work: %r" % (tg_gate("P1.4"),),
              codetg == 0
              and tg_gate("P1.4") == [
                  "lint",
                  "npm test -- src/search/a.test.ts src/search/b.test.ts"])

        # ---- THE ALLOW CASES: a wide gate the project CHOSE stays wide --------
        # This is the direction that decides whether the change is honest. A
        # derivation that silently narrows a deliberately wide gate is worse than
        # the cost it saves: a gate that stops selecting the tests it was meant to
        # is a green that means less than it did. All three phases below have to
        # come back with the phase's own entries AND with a basis that says the
        # wide one was taken and why.
        codetg, txttg = run(
            ["add", "Debounce the stepper", "--phase", "P2",
             "--project-dir", tg_proj, "--tests-mode", "tdd",
             "--tests-add", "src/cart/stepper.test.ts: coalesces two clicks"])
        check("tg4 ALLOW CASE: every sibling carries the wide KEY, so the plan "
              "records no spelling to read one off - the phase's testGate, with "
              "the reason. Its third entry is the one a wrongly-narrowed gate "
              "would drop: %r" % ((tg_gate("P2.2"), codetg),),
              codetg == 0
              and tg_gate("P2.2") == ["lint", "test", "typecheck"]
              and "the phase's testGate, wide" in txttg
              and "no sibling task in P2 declares a path-scoped gate entry" \
                  in txttg)

        codetg, txttg = run(
            ["add", "Trim the banner", "--phase", "P3",
             "--project-dir", tg_proj, "--tests-mode", "tdd",
             "--tests-add", "src/cart/banner.test.ts: hides on an empty cart"])
        check("tg5 ALLOW CASE, and the one a loosened filename bound breaks: a "
              "wide LITERAL (`npm test`) names no file, so it is not a spelling "
              "either - a token has to carry an extension or be a dotfile to "
              "count as a path: %r" % ((tg_gate("P3.2"), codetg),),
              codetg == 0 and tg_gate("P3.2") == ["lint", "test"]
              and "the phase's testGate, wide" in txttg)

        codetg, txttg = run(
            ["add", "Nothing named at all", "--phase", "P1",
             "--project-dir", tg_proj])
        check("tg6 ALLOW CASE at the other end: the sibling IS path-scoped and "
              "this task names no file, so there is nothing to point a gate at - "
              "the wide entry, and a DIFFERENT reason, because `no spelling` and "
              "`no paths` are two states an operator repairs differently: %r"
              % ((tg_gate("P1.5"), codetg),),
              codetg == 0
              and tg_gate("P1.5") == ["lint", "test", "typecheck"]
              and "P1.1 is path-scoped but this task names no file" in txttg)

        codetg, txttg = run(
            ["add", "Keyed like a path", "--phase", "P4",
             "--project-dir", tg_proj, "--tests-mode", "tdd",
             "--tests-add", "src/web/app.test.ts: renders the shell"])
        check("tg7 ALLOW CASE, reading the DECLARATION and not the punctuation: "
              "`web.spec` is a `meta.buildCommands` key whose name happens to "
              "look like a file, and a key is wide by declaration however it is "
              "spelled - only a check that asked the manifest can tell: %r"
              % ((tg_gate("P4.2"), codetg),),
              codetg == 0 and tg_gate("P4.2") == ["lint"]
              and "the phase's testGate, wide" in txttg)

        # ---- the two flags still win, and still say so ------------------------
        codetg, txttg = run(
            ["add", "Explicit", "--phase", "P1", "--project-dir", tg_proj,
             "--gate", "npx vitest run src/x.test.ts"])
        check("tg8 `--gate` is not a default and is not derived from: what the "
              "caller typed, reported as theirs: %r"
              % ((tg_gate("P1.6"), "from --gate" in txttg),),
              codetg == 0
              and tg_gate("P1.6") == ["npx vitest run src/x.test.ts"]
              and "from --gate" in txttg)
        codetg, txttg = run(
            ["add", "Ungradeable", "--phase", "P1", "--project-dir", tg_proj,
             "--gate-clear"])
        check("tg9 `--gate-clear` still reaches the EMPTY gate - the "
              "derivation runs after both flags, never instead of them: %r"
              % ((tg_gate("P1.7"), codetg),),
              codetg == 0 and tg_gate("P1.7") == []
              and "gate: none (from --gate-clear)" in txttg)

        codetg, txttg = run(
            ["add", "As data", "--phase", "P1", "--project-dir", tg_proj,
             "--json", "--tests-add", "src/search/c.test.ts: three"])
        _tg_json = json.loads(txttg)
        check("tg10 the machine surface carries the basis under the key "
              "`add-phase` already spells it with, so a reader comparing a "
              "phase's answer with a task's is comparing one kind of answer: %r"
              % (_tg_json.get("testGateBasis"),),
              codetg == 0
              and _tg_json.get("testGateBasis")
              == "narrowed to this task's tests.add paths, in P1.1's spelling"
              and (_tg_json.get("task") or {}).get("tests", {}).get("gate")
              == ["lint", "npm test -- src/search/c.test.ts"])

        codetg, txttg = run(
            ["add", "Rework the nav", "--phase", "P5",
             "--project-dir", tg_proj, "--tests-mode", "tdd",
             "--tests-add", "src/web/nav.test.ts: collapses under 640px"])
        check("tg12 a path-shaped KEY riding beside a real path-scoped entry is "
              "carried through while only the entry beside it moves - the one "
              "arrangement where copying a shared key through and repointing it "
              "produce different gates: %r" % ((tg_gate("P5.2"), codetg),),
              codetg == 0
              and tg_gate("P5.2") == ["web.spec",
                                      "npm test -- src/web/nav.test.ts"])

        # THE UNIT-LEVEL BOUND, driven at the function rather than through a
        # manifest: these are the tokens a path detector has to refuse, and a
        # manifest case can only reach them one at a time.
        check("tg11 `_gate_entry_paths` reads a runner's flags, selectors and "
              "shard fractions as what they are and not as paths, and finds the "
              "suite between them: %r"
              % ([M._gate_entry_paths(e) for e in
                  ("yarn test --selectProjects web", "yarn test --shard 1/4",
                   "npm test -- src/a.test.ts", "npm test", "lint",
                   "pytest tests/.coveragerc")],),
              M._gate_entry_paths("yarn test --selectProjects web") == []
              and M._gate_entry_paths("yarn test --shard 1/4") == []
              and M._gate_entry_paths("npm test -- src/a.test.ts") \
                  == ["src/a.test.ts"]
              and M._gate_entry_paths("npm test") == []
              and M._gate_entry_paths("lint") == []
              and M._gate_entry_paths("pytest tests/.coveragerc") \
                  == ["tests/.coveragerc"])
        check("tg13 `_gate_entry_paths` is an ALIAS of `_manifest_phases."
              "gate_entry_paths`, not a second body - `is`, not merely "
              "behaviour equal, because a re-pasted copy would pass tg11 "
              "and still be the copy an entry point cannot import out of "
              "run-test-gate.py",
              getattr(M, "_gate_entry_paths", None)
              is getattr(_phases, "gate_entry_paths", object()))
        check("tg14 `_is_shared_key`/`_path_scoped_sibling`/`_repointed` are "
              "ALIASES of `_gate_derive`'s own bodies, not copies re-pasted "
              "here - `is`, not merely behaviour-equal, for tg13's exact "
              "reason: a phase-level derivation and this task-level one must "
              "share one body or risk drifting the moment either changes",
              getattr(M, "_is_shared_key", None)
              is getattr(_gate_derive, "is_shared_key", object())
              and getattr(M, "_path_scoped_sibling", None)
              is getattr(_gate_derive, "path_scoped_sibling", object())
              and getattr(M, "_repointed", None)
              is getattr(_gate_derive, "repointed", object()))

        # ---- (gb) the derivation's arm, recorded where a rule can read it -----
        # The basis above is a SENTENCE: printed once, then gone. So a narrow
        # gate and a wide one read the same way in the manifest afterwards, and
        # the validator's line about a task carrying its phase's gate verbatim
        # could not tell the two wide arms apart - a project with no path-scoped
        # spelling, which has nothing to narrow with, from a task that named no
        # file, which does. It asked for prose in the `description` instead,
        # which nothing reads.
        def tg_basis(tid):
            return (((task_in(tg_mp, tid) or {}).get("tests") or {})
                    .get("gateBasis"))

        check("gb1 every arm writes its own word, and the two WIDE arms write "
              "DIFFERENT words - which is the whole question, since one says "
              "the project cannot narrow and the other says this task did not: "
              "%r" % ([tg_basis(t) for t in
                       ("P1.2", "P1.3", "P2.2", "P1.5", "P1.6", "P1.7")],),
              [tg_basis(t) for t in ("P1.2", "P1.3", "P2.2", "P1.5",
                                     "P1.6", "P1.7")]
              == ["tests.add", "files", "phase-no-spelling", "phase-no-paths",
                  "declared", "cleared"])
        check("gb2 ...and every one of those words is in the vocabulary the "
              "validator reads, asked of that module rather than of this list - "
              "a word written here and absent there is a basis nothing can "
              "grade: %r" % (sorted(_vocab.GATE_BASIS),),
              set(tg_basis(t) for t in ("P1.2", "P1.3", "P2.2", "P1.5",
                                        "P1.6", "P1.7"))
              <= set(_vocab.GATE_BASIS)
              and set(_vocab.GATE_BASIS_ANSWERED) <= set(_vocab.GATE_BASIS))
        _gb_w = _rules.validate(_mio.load_manifest(tg_mp))[1]
        _gb_wide = [x for x in _gb_w if "testGate verbatim" in x]
        check("gb3 so the validator is SILENT on the task whose phase records "
              "no spelling and NAMES the one whose sibling does - the same "
              "manifest, the same wide gate, two answers, because the "
              "distinction is whether the project can narrow: %r"
              % (_gb_wide,),
              not any("P2.2" in x for x in _gb_wide)
              and any("P1.5" in x for x in _gb_wide))
        # THE ROUTE THAT ANSWERS THE LINE, and it has to be a WRITE: declaring
        # the wide gate outright leaves `tests.gate` byte-identical, so a verb
        # comparing lists alone would say "already reads that way" and leave the
        # operator with prose nothing reads.
        _gb_code, _gb_txt = run(["scope", "P1.5", "--project-dir", tg_proj,
                                 "--gate", "lint", "--gate", "test",
                                 "--gate", "typecheck"])
        _gb_w2 = _rules.validate(_mio.load_manifest(tg_mp))[1]
        check("gb4 declaring the wide gate through `/audit:task scope --gate` "
              "records WHO chose it and takes the line down, even though the "
              "list itself did not move a byte: %r"
              % ((_gb_code, tg_basis("P1.5"), tg_gate("P1.5")),),
              _gb_code == 0 and tg_basis("P1.5") == "declared"
              and tg_gate("P1.5") == ["lint", "test", "typecheck"]
              and not any("P1.5" in x for x in _gb_w2
                          if "testGate verbatim" in x))
        check("gb5 ...and that call is reported as a gate change rather than "
              "swallowed, so the operator sees the write they made: %r"
              % (_gb_txt[:200],),
              "tests.gateBasis" in _gb_txt and "scoped in" in _gb_txt)

        # ---- (tw) the tree you stand in vs the tree you write -----------------
        # DRIVEN, AND THE FIXTURE IS THE INCIDENT: a checkout holding the plan,
        # a linked worktree added from it on another branch, the project
        # variable naming the checkout and no manifest argument. `scope --files`
        # exited 0 with a note, and afterwards the CHECKOUT had a modified plan
        # and a new journal while the worktree was clean. The one line that
        # named a tree was a note about a file "not on disk", and it did not say
        # which tree it had looked in.
        #
        # A REAL `git worktree add`, never a directory dressed as one: the
        # divergence is decided by asking git where the caller is standing, so a
        # fixture git would call an ordinary checkout proves nothing about the
        # case that matters.
        def _git_q(cwd, argv):
            return subprocess.run(
                ["git", "-C", cwd, "-c", "user.email=selftest@example.invalid",
                 "-c", "user.name=Selftest"] + list(argv),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL).returncode

        def mk_pair(name, manifest=None):
            """(project, manifestPath, linkedWorktreePath) -- a real pair."""
            proj, mp = mk(name, manifest or base_manifest(), git=True)
            _git_q(proj, ["add", "-A"])
            _git_q(proj, ["commit", "-qm", "fixture"])
            tree = os.path.join(tmp, name + "-wt")
            _git_q(proj, ["worktree", "add", "-q", "-b",
                          name + "-branch", tree])
            return proj, mp, tree

        def mk_pair_empty(name):
            """`mk_pair()` minus the manifest -- a git repo with a first
            commit and a linked worktree, but nothing at manifestPath yet.
            `seed`'s own row in the tw-group needs this: every other verb's
            row relies on a manifest already being at the project, and `seed`
            refuses for exactly that reason."""
            proj, mp = mk_empty(name)
            # Named branch, for the reason `mk()` gives.
            subprocess.run(["git", "init", "-q", "-b", "main", proj],
                           check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            _git_q(proj, ["add", "-A"])
            _git_q(proj, ["commit", "-qm", "fixture"])
            tree = os.path.join(tmp, name + "-wt")
            _git_q(proj, ["worktree", "add", "-q", "-b",
                          name + "-branch", tree])
            return proj, mp, tree

        # The clauses, read off the table rather than retyped here: a case that
        # spelled the sentence a second time would go green on a note that had
        # stopped matching the rule the resolver follows, which is the whole
        # thing this pair exists to prevent.
        _tw_why = dict(_panel_write.PROJECT_BASES)

        def _tw_posix(p):
            """`p`, resolved and forward-slash - `standing_elsewhere` names the
            tree with git's own `rev-parse --show-toplevel`, which prints POSIX
            separators on every platform (`_worktrees.within_tree`'s docstring
            carries the same fact for the same reason). `os.path.realpath`
            answers with native separators on windows, so comparing it against
            the verb's text unconverted failed there for a directory the two
            sides named identically - a spelling mismatch, not a wrong tree."""
            return os.path.realpath(p).replace("\\", "/")
        tw_proj, tw_mp, tw_tree = mk_pair("tw")
        _tw_before = open(tw_mp, "rb").read()
        _tw_twin = os.path.join(tw_tree, "docs", "audit", "audit-plan.json")
        try:
            _pin(tw_tree, tw_proj)
            code, txt = run(["scope", "P2.3", "--files", "src/a.ts,src/new.ts"])
        finally:
            _unpin()
        check("tw1 standing in a linked worktree with the project variable "
              "naming the OTHER checkout, the verb names both roots and why "
              "this one won -- the silence that let the incident happen: %r"
              % (txt[:160],),
              code == 0 and "WARNING" in txt
              and _tw_posix(tw_tree) in txt and tw_proj in txt
              and _tw_why["$CLAUDE_PROJECT_DIR"] in txt)
        check("tw2 ...and the warning is about a real divergence: the plan and "
              "the journal moved in the CHECKOUT, the worktree's own copy of "
              "the same file did not, and no journal appeared beside it",
              open(tw_mp, "rb").read() != _tw_before
              and open(_tw_twin, "rb").read() == _tw_before
              and os.path.isdir(os.path.join(tw_proj, "docs", "audit",
                                             "journal"))
              and not os.path.isdir(os.path.join(tw_tree, "docs", "audit",
                                                 "journal")))
        _tw_disk = [ln for ln in txt.split("\n")
                    if "nothing on disk answers for" in ln]
        check("tw3 the `not on disk` note carries the directory it searched, "
              "ONCE for the whole list -- the report asked for the directory, "
              "and an advisory that repeats a constant per file is the shape "
              "people stop reading: %r" % (_tw_disk,),
              len(_tw_disk) == 1 and tw_proj in _tw_disk[0]
              and "src/a.ts" in _tw_disk[0] and "src/new.ts" in _tw_disk[0])

        try:
            _pin(tw_proj, tw_proj)
            code, txt_same = run(["scope", "P2.3", "--files",
                                  "src/a.ts,src/new.ts,src/more.ts"])
        finally:
            _unpin()
        check("tw4 THE ALLOW CASE: an ordinary call from the checkout, where "
              "the tree and the project agree, says nothing new -- a verb that "
              "grew a paragraph on every invocation is one nobody reads: %r"
              % (txt_same[:160],),
              code == 0 and "standing in" not in txt_same
              and _tw_why["$CLAUDE_PROJECT_DIR"] not in txt_same
              and _tw_posix(tw_proj) not in txt_same.replace(
                  tw_proj, ""))

        # EVERY VERB, because the fault is the writing and not the verb: the
        # list is the parser's own, so a verb added past the shared door goes
        # red here rather than shipping silent.
        tw_all, tw_all_mp, tw_all_tree = mk_pair("tw-verbs")
        _tw_head = subprocess.run(["git", "-C", tw_all, "rev-parse", "HEAD"],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
        _tw_sha = _tw_head.stdout.decode("utf-8", "replace").strip()
        # `couple`'s row needs a run its OWN project's evidence ledger holds.
        import _evidence_io as _tw_ev
        _tw_ev.append_row(tw_all, {
            "v": 1, "runId": "RUN-TW", "ts": "2026-09-01T00:00:00Z",
            "scope": "phase", "phaseId": "P2", "status": "failed", "steps": []})
        # `seed` gets its OWN pair: every row below relies on a manifest
        # already being at `tw_all`, and `seed` refuses for exactly that
        # reason -- its row has to stand in a tree that diverges from a
        # PROJECT that is still empty.
        tw_seed_proj, _tw_seed_mp, tw_seed_tree = mk_pair_empty("tw-seed")
        # The review verbs get a pair of their own, whose P2 already carries a
        # verdict: `correct` needs one, and the fix commit `resolve-finding`
        # names has to be one this pair's git can resolve.
        _tw_rv = base_manifest()
        _tw_rv["phases"][1]["tasks"][1]["status"] = "done"
        _tw_rv["phases"][1]["review"] = {"status": "skipped"}
        _tw_rv["phases"][1]["summary"] = "s"
        tw_rv_proj, _tw_rv_mp, tw_rv_tree = mk_pair("tw-review", _tw_rv)
        _tw_rv_sha = subprocess.run(
            ["git", "-C", tw_rv_proj, "rev-parse", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        ).stdout.decode("utf-8", "replace").strip()
        # The fixtures' branch is the fixture's own, never the machine's: an
        # unnamed `git init` inherits `init.defaultBranch`, and the rows below
        # read a phase that forks from main.
        _tw_heads = [subprocess.run(
            ["git", "-C", p, "symbolic-ref", "--short", "-q", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        ).stdout.decode("utf-8", "replace").strip()
            for p in (tw_seed_proj, tw_rv_proj)]
        check("tw0 both git fixtures start on main whatever the runner's "
              "gitconfig names as the default branch: %r" % (_tw_heads,),
              _tw_heads == ["main", "main"])
        _tw_argv = (
            ("add", ["add", "Fresh", "--phase", "P2"]),
            ("add-phase", ["add-phase", "Later", "--outcome", "it ships"]),
            ("scope", ["scope", "P2.3", "--files", "src/a.ts"]),
            ("start", ["start", "P2.3"]),
            # `file-return` writes no plan, and still names the tree whose
            # evidence directory took the return.
            ("file-return", ["file-return", "P2.3", "--role", "executor"]),
            ("done", ["done", "P2.3", "--commit", _tw_sha] + _NOT_ASKED),
            ("retarget", ["retarget", "P3", "--outcome", "changed its mind"]),
            ("cancel", ["cancel", "P3", "--reason", "dropped"]),
            ("seed", ["seed", "Fresh plan"]),
            # `next-id` writes nothing, and it still names the tree it READ: the
            # id it prints is only true of that tree's plan and branch.
            ("next-id", ["next-id", "bug"]),
            ("signoff", ["signoff", "P2", "--verdict", "passed", "--summary", "s",
                         "--no-evidence-reason", "fixture"]),
            # `settle` writes nothing on a plan already settled, and still names
            # the tree it read: "nothing to settle" is only true of that plan.
            ("settle", ["settle"]),
            # `reopen` on the task `done` above just closed, in its open phase.
            ("reopen", ["reopen", "P2.3", "--reason", "r"]),
            # ...then a note on it, a block of it, and a move of the blocked task
            # into the phase `add-phase` above created - P3 is cancelled by now.
            ("note", ["note", "P2.3", "--text", "t"]),
            ("block", ["block", "P2.3", "--reason", "r"]),
            ("move", ["move", "P2.3", "--to", "P4"]),
            ("couple", ["couple", "--test", "tests/test_tw.py",
                        "--sources", "src/a.ts", "--basis-run", "RUN-TW",
                        "--basis-head", _tw_sha]),
            ("uncouple", ["uncouple", "--test",
                          "tests/test_tw.py"]),
            ("finding", ["finding", "P2", "--severity", "low", "--file",
                         "src/a.ts", "--issue", "i", "--resolution", "r"]),
            ("resolve-finding", ["resolve-finding", "P2-R1", "--fix-task", "P2.1",
                                 "--commit", _tw_rv_sha]),
            ("correct", ["correct", "P2", "--summary", "restated"]),
            ("bug-add", ["bug-add", "Flaky", "--severity", "low",
                         "--description", "d"]),
            # ...and `unmute` lifts the mute `mute` wrote, on their own pair.
            ("mute", ["mute", "--test", "tests/test_tw.py", "--reason", "r",
                      "--owner", "o", "--until", "2998-01-01",
                      "--bug", "BUG-3"]),
            ("unmute", ["unmute", "--test", "tests/test_tw.py"]),
            # ...and `unblock`, on a pair whose task has spent its attempts.
            ("unblock", ["unblock", "P2.3", "--reason", "try again"]),
        )
        # `signoff` gets its own pair too: by its row every other row has left P2
        # with open work, which it rightly refuses.
        _tw_sign = base_manifest()
        _tw_sign["phases"][1]["tasks"][1]["status"] = "done"
        tw_sign_proj, _tw_sign_mp, tw_sign_tree = mk_pair("tw-sign", _tw_sign)
        # `mute` and `unmute` get a pair whose plan already holds the bug the
        # mute names: on `tw_all` the bug `bug-add` files carries the linked
        # worktree's branch suffix, which a literal here could not spell.
        _tw_mu = base_manifest()
        _tw_mu["bugs"] = [{"id": "BUG-3", "title": "flaky", "status": "open"}]
        tw_mu_proj, _tw_mu_mp, tw_mu_tree = mk_pair("tw-mute", _tw_mu)
        _tw_ub = base_manifest()
        _tw_ub["phases"][1]["tasks"][1].update(status="blocked", attempts=3,
                                              maxAttempts=3)
        tw_ub_proj, _tw_ub_mp, tw_ub_tree = mk_pair("tw-unblock", _tw_ub)
        _tw_pairs = {"unblock": (tw_ub_tree, tw_ub_proj),
                     "mute": (tw_mu_tree, tw_mu_proj),
                     "unmute": (tw_mu_tree, tw_mu_proj),
                     "seed": (tw_seed_tree, tw_seed_proj),
                     "signoff": (tw_sign_tree, tw_sign_proj),
                     "finding": (tw_rv_tree, tw_rv_proj),
                     "resolve-finding": (tw_rv_tree, tw_rv_proj),
                     "correct": (tw_rv_tree, tw_rv_proj)}
        _tw_silent = []
        for _label, _argv in _tw_argv:
            _tw_tree, _tw_proj = _tw_pairs.get(_label, (tw_all_tree, tw_all))
            try:
                _pin(_tw_tree, _tw_proj)
                _codev, _txtv = (run_on_stdin(_argv, _fr_executor())
                                 if _label == "file-return" else run(_argv))
            finally:
                _unpin()
            if _codev != 0 or "standing in" not in _txtv \
                    or _tw_posix(_tw_tree) not in _txtv:
                _tw_silent.append((_label, _codev, _txtv[:140]))
        check("tw5 every manifest-writing verb says which tree it wrote, and "
              "the verbs are the PARSER's list rather than one typed here: %r"
              % (_tw_silent,),
              not _tw_silent
              and sorted(lbl for lbl, _a in _tw_argv) == sorted(M.VERB_FLAGS))

        tw_j, tw_j_mp, tw_j_tree = mk_pair("tw-json")
        try:
            _pin(tw_j_tree, tw_j)
            codej, txtj = run(["start", "P2.3", "--json"])
        finally:
            _unpin()
        # `.get` on both, so a payload that DROPPED the key fails this case
        # rather than raising out of the suite and leaving every case after it
        # unrun - an abort is red, but it is red about the wrong thing.
        _tw_pb = json.loads(txtj).get("projectBasis") or {}
        check("tw6 under `--json` the fact travels as DATA in the one object a "
              "caller parses, never as lines printed beside it: %r" % (_tw_pb,),
              codej == 0
              and _tw_pb.get("diverged") is True
              and _tw_pb.get("root") == tw_j
              and _tw_pb.get("standingIn") == _tw_posix(tw_j_tree)
              and _tw_pb.get("why") == _tw_why["$CLAUDE_PROJECT_DIR"])
        try:
            _pin(tw_j, tw_j)
            codej2, txtj2 = run(["scope", "P2.3", "--files", "src/a.ts",
                                 "--json"])
        finally:
            _unpin()
        _tw_pb2 = json.loads(txtj2).get("projectBasis") or {}
        check("tw7 ...and it travels on the SAME-tree call too, where the human "
              "render is silent: a machine that only ever saw the key on a "
              "divergence could not tell agreement from a release that does "
              "not answer this: %r" % (_tw_pb2,),
              codej2 == 0
              and _tw_pb2.get("diverged") is False
              and _tw_pb2.get("standingIn") == _tw_posix(tw_j))

        # NO GIT, NO GUESS. `tmp` is a scratch directory in no repository, which
        # is what a machine without git looks like to this code: the question
        # comes back unanswered and the verb stays quiet, because a divergence
        # nobody can verify is the advisory people learn to scroll past.
        import _worktrees as _tw_wt
        _tw_none = _tw_wt.tree_root(tmp)
        tw_q, tw_q_mp = mk("tw-quiet", base_manifest())
        try:
            _pin(tmp, tw_q)
            codeq, txtq = run(["scope", "P2.3", "--files", "src/a.ts"])
        finally:
            _unpin()
        check("tw8 a caller standing outside any working tree gets silence "
              "rather than a guessed divergence, and the unanswered question "
              "says so in its own basis: %r" % (_tw_none,),
              _tw_none["root"] is None and "could not be asked" in
              _tw_none["basis"]
              and codeq == 0 and "standing in" not in txtq)

        tw_here, tw_here_mp = mk("tw-on-disk", base_manifest())
        code, txt_disk = run(["scope", "P2.3", "--files",
                              ".claude/audit.config.json",
                              "--project-dir", tw_here])
        check("tw10 ALLOW CASE for the other half: every declared path IS under "
              "the root, so the note does not appear at all -- a line that "
              "printed an empty list would name a directory to say nothing "
              "about it: %r" % (txt_disk[:120],),
              code == 0 and "nothing on disk answers for" not in txt_disk)

        _tw_parser = M.build_parser()
        _tw_rows = []
        try:
            _pin(tw_proj, tw_proj)
            for _a in (["add", "T", "--project-dir", tw_proj],
                       ["add", "T", tw_mp], ["add", "T"]):
                _tw_rows.append(M.resolve_basis(
                    _tw_parser.parse_intermixed_args(_a)))
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            _tw_rows.append(M.resolve_basis(
                _tw_parser.parse_intermixed_args(["add", "T"])))
        finally:
            _unpin()
        check("tw9 every route names the table row that chose it and quotes "
              "that row's clause, and between them the four routes reach every "
              "row -- a row the resolver cannot produce, or a clause written "
              "beside the table instead of in it, goes red here: %r"
              % ([r["basis"] for r in _tw_rows],),
              [r["basis"] for r in _tw_rows]
              == ["--project-dir", "manifest argument", "$CLAUDE_PROJECT_DIR",
                  "the working directory"]
              and all(r["why"] == _tw_why[r["basis"]] for r in _tw_rows)
              and sorted(r["basis"] for r in _tw_rows)
              == sorted(k for k, _w in _panel_write.PROJECT_BASES))

        # ---- (sd) seed: the smallest honest plan, written where none was ----
        sd_proj, sd_mp = mk_empty("sd-fresh")
        code, txt = run(["seed", "--project-dir", sd_proj])
        sd_written = _mio.load_manifest(sd_mp) if os.path.isfile(sd_mp) else None
        check("sd1 seed writes a manifest that validates, where none existed "
              "a moment before: %r" % (code,),
              code == 0 and sd_written is not None
              and _rules.validate(sd_written)[0] == [])
        check("sd2 OVER-FIRE CASE: the plan carries exactly ONE phase and that "
              "phase exactly ONE task -- a generator that invented a second "
              "phase or a second task nobody asked for would still validate, "
              "so only a COUNT and not a validity check can catch it: %r"
              % ([len(sd_written.get("phases") or []) if sd_written else None,
                  len(sd_written["phases"][0].get("tasks") or [])
                  if sd_written else None],),
              sd_written is not None
              and len(sd_written.get("phases") or []) == 1
              and len(sd_written["phases"][0].get("tasks") or []) == 1)
        check("sd3 ...and nothing in it was guessed: the phase's testGate and "
              "the one task's tests.gate are both empty, with a basis word a "
              "reader (and the validator) can act on rather than a "
              "plausible-looking command nobody ran: %r"
              % (sd_written["phases"][0]["tasks"][0]["tests"]["gateBasis"],),
              sd_written["phases"][0]["testGate"] == []
              and sd_written["phases"][0]["tasks"][0]["tests"]["gate"] == []
              and sd_written["phases"][0]["tasks"][0]["tests"]["gateBasis"]
              in _vocab.GATE_BASIS)
        import _config as _sd_config
        sd_state = _sd_config.manifest_state(sd_proj,
                                             "docs/audit/audit-plan.json")
        sd_mode = _sd_config.plan_gate_mode(dict(_sd_config.DEFAULTS),
                                           sd_state)
        check("sd4 the plan gate is INERT (observe) with no manifest at all "
              "and LIVE (warn -- advisory, nothing running yet) the moment "
              "this writes one: %r" % (sd_mode,), sd_mode == "warn")
        sd2_proj, sd2_mp = mk("sd-exists", base_manifest())
        _sd2_before = open(sd2_mp, "rb").read()
        code2, _txt2 = run(["seed", "--project-dir", sd2_proj])
        check("sd5 SECOND-DIRECTION CASE: seed REFUSES rather than overwriting "
              "a manifest that is already there, and writes not one byte -- "
              "the one door here that checks the OPPOSITE of every other "
              "verb's precondition: %r" % (code2,),
              code2 == 2 and open(sd2_mp, "rb").read() == _sd2_before)
        sd3_proj, sd3_mp = mk_empty("sd-gate")
        code3, _txt3 = run(["seed", "Named", "--gate", "pytest -q",
                            "--project-dir", sd3_proj])
        sd3_written = _mio.load_manifest(sd3_mp)
        check("sd6 --gate reaches BOTH the phase's testGate and the one "
              "task's tests.gate in a single call -- what add-phase followed "
              "by add would need two calls to do -- and a title override "
              "lands on the phase rather than the default: %r"
              % (sd3_written["phases"][0]["title"],),
              code3 == 0
              and sd3_written["phases"][0]["title"] == "Named"
              and sd3_written["phases"][0]["testGate"] == ["pytest -q"]
              and sd3_written["phases"][0]["tasks"][0]["tests"]["gate"]
              == ["pytest -q"])

        # ---- (u) usage -------------------------------------------------------
        with open(os.devnull, "w") as _null, \
                contextlib.redirect_stderr(_null):
            code, _txt = run(["frobnicate", "X"])
            check("u1 an unknown subcommand is a usage error", code == 2)
            code, _txt = run([])
            check("u2 bare invocation is a usage error", code == 2)
        # ---- (so) sign-off recorded by a verb; the status derived from it ------
        import _journal_io
        signable = base_manifest()
        signable["phases"][1]["tasks"][1]["status"] = "done"   # P2: every task done
        signable["phases"][1]["claim"] = {"sessionId": "s", "at": "t"}
        projs, mpaths = mk("so-sign", signable, git=True)
        code, txt = run(["signoff", "P3", "--verdict", "passed", "--summary", "x",
                         "--project-dir", projs])
        check("so1 a phase with no finished task cannot be signed off: %s" % (txt,),
              code == 2 and "P3" in txt)
        unsigned = base_manifest()
        projo, _mo = mk("so-open", unsigned)
        code, txt = run(["signoff", "P2", "--verdict", "passed", "--summary", "x",
                         "--project-dir", projo])
        check("so2 ...nor one with an open task, and the refusal names it: %s" % (txt,),
              code == 2 and "P2.3" in txt)
        code, txt = run(["signoff", "P2", "--verdict", "passed",
                         "--summary", "Search sanitised end to end.",
                         "--review-outcome", "no findings",
                         "--no-evidence-reason", "fixture: no gate is run here",
                         "--project-dir", projs])
        ph2 = [p for p in _mio.load_manifest(mpaths)["phases"] if p["id"] == "P2"][0]
        check("so3 every task terminal: sign-off records the verdict, the outcome and the "
              "summary, clears the claim - and STORES the status the derivation now "
              "answers, so a reader of the field alone reads done: %s" % (txt,),
              code == 0 and ph2["review"]["status"] == "passed"
              and ph2["review"]["outcome"] == "no findings"
              and ph2["summary"] == "Search sanitised end to end."
              and "claim" not in ph2 and ph2["status"] == "done")
        check("so4 ...and the phase now reads done, which the output says",
              _mio.effective_phase_status(ph2) == "done" and "done" in txt, txt)
        rows = [r for r in _journal_io.read_all(projs) if r.get("action") == "phase.verdict"]
        check("so5 ...with a phase.verdict journal row naming the phase and the verdict",
              len(rows) == 1 and (rows[0].get("details") or {}).get("phaseId") == "P2"
              and "passed" in (rows[0].get("summary") or ""), rows)
        check("so5b ...and NOT a phase.signoff row: that one is DERIVED by the "
              "journal-writes hook from the write itself, and a verb writing it too "
              "would leave two rows for one sign-off",
              not [r for r in _journal_io.read_all(projs)
                   if r.get("action") == "phase.signoff"])
        code, txt = run(["signoff", "P2", "--verdict", "skipped", "--summary", "y",
                         "--project-dir", projs])
        check("so6 a second sign-off is refused - the verdict on record is not "
              "re-decided by this verb: %s" % (txt,), code == 2 and "already" in txt)
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "y",
                         "--project-dir", projs])
        check("so7 a phase already done is refused", code == 2, txt)
        code, txt = run(["signoff", "P2", "--summary", "y", "--project-dir", projs])
        check("so8 --verdict is required: which verdict is the reviewer's call",
              code == 2 and "--verdict" in txt, txt)
        branched = base_manifest()
        branched["phases"][1]["tasks"][1]["status"] = "done"
        branched["phases"][1]["branch"] = "feature/p2"
        projb2, mpathb2 = mk("so-branch", branched)
        code, txt = run(["signoff", "P2", "--verdict", "passed", "--summary", "z",
                         "--no-evidence-reason", "fixture",
                         "--project-dir", projb2, "--json"])
        try:
            payload = json.loads(txt)
        except ValueError:
            payload = {}
        check("so9 a phase WITH a branch is signed off and not yet done - done once "
              "close-phase lands it - and --json says both: %r" % (payload,),
              code == 0 and payload.get("effectiveStatus") == "in_progress"
              and payload.get("awaiting") == "merge"
              and "feature/p2" in json.dumps(payload))
        _so9_ph = [p for p in _mio.load_manifest(mpathb2)["phases"]
                   if p["id"] == "P2"][0]
        check("so9b ...and it stores NO done: the derivation still answers "
              "in_progress until the merge, and a stored done would win over it - "
              "the case that goes red when sign-off writes done unconditionally: %r"
              % (_so9_ph.get("status"),),
              _so9_ph.get("status") == "in_progress")
        # THE SHARDED LAYOUT, where a phase's status lives twice: in its shard and
        # mirrored on the index stub. A parent-branch phase reads done the moment
        # it is signed off, and both copies must say so - the stub is what a reader
        # of the index alone, an older plugin's hooks included, is answered from.
        shardsign = base_manifest()
        shardsign["phases"][1]["tasks"][1]["status"] = "done"
        projss, mpss = mk("so-sharded", shardsign, sharded=True)
        code, txt = run(["signoff", "P2", "--verdict", "passed", "--summary", "s",
                         "--no-evidence-reason", "fixture",
                         "--project-dir", projss])
        _ss_idx = _mio.read_json(mpss)
        _ss_stub = [s for s in _ss_idx["phases"] if s.get("id") == "P2"][0]
        _ss_body = _mio.read_json(os.path.join(os.path.dirname(mpss),
                                               _ss_stub["shard"]))
        _ss_eff = _mio.effective_phase_status(
            [p for p in _mio.load_manifest(mpss)["phases"] if p["id"] == "P2"][0])
        check("so10 a parent-branch phase signed off in the SHARDED layout stores "
              "done on its shard AND its index stub, agreeing with the derivation: "
              "stub=%r shard=%r derived=%r (%s)"
              % (_ss_stub.get("status"), _ss_body.get("status"), _ss_eff, txt),
              code == 0 and _ss_eff == "done"
              and _ss_stub.get("status") == "done"
              and _ss_body.get("status") == "done")

        # ---- (gs) a GROUP of phases built on one branch, signed off together ----
        # A real repository: the group's review is scoped from its tasks' commits,
        # and whether each commit is on the branch is git's answer, not a fixture's.
        def gs_git(proj, *a):
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            done_ = subprocess.run(["git", "-C", proj] + list(a), env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return done_.stdout.decode("utf-8", "replace").strip()

        def gs_fixture(name, gates=(["test"], ["test"]), sharded=False):
            """(proj, mpath, shas) - P1 and P2, one task each, both finished, no
            branch recorded, their commits on `combined`; `stray` is a commit on
            main that the branch does not carry."""
            plan = base_manifest()
            plan["phases"] = [
                {"id": "P1", "title": "One", "status": "in_progress",
                 "testGate": list(gates[0]), "branch": None, "baseRef": None,
                 "tasks": [{"id": "P1.1", "title": "a", "status": "done",
                            "files": ["src/p1.py"]}]},
                {"id": "P2", "title": "Two", "status": "in_progress",
                 "testGate": list(gates[1]), "branch": None, "baseRef": None,
                 "tasks": [{"id": "P2.1", "title": "b", "status": "done",
                            "files": ["src/p2.py"]},
                           {"id": "P2.2", "title": "c", "status": "cancelled"}]},
            ]
            plan["fileIndex"] = {"src/p1.py": ["P1.1"], "src/p2.py": ["P2.1"]}
            proj, mpath = mk(name, plan, git=True, sharded=sharded)
            gs_git(proj, "checkout", "-q", "-b", "main")
            gs_git(proj, "commit", "-q", "--allow-empty", "-m", "base")
            gs_git(proj, "checkout", "-q", "-b", "combined")
            shas = {}
            for tid in ("P1.1", "P2.1"):
                gs_git(proj, "commit", "-q", "--allow-empty", "-m", tid)
                shas[tid] = gs_git(proj, "rev-parse", "HEAD")
            gs_git(proj, "checkout", "-q", "main")
            gs_git(proj, "commit", "-q", "--allow-empty", "-m", "stray")
            shas["stray"] = gs_git(proj, "rev-parse", "HEAD")
            written = _mio.load_manifest(mpath)
            for ph in written["phases"]:
                for t in ph["tasks"]:
                    if t["id"] in shas:
                        t["commit"] = shas[t["id"]]
            if sharded:
                _mio.save_sharded(mpath, written)
            else:
                _panel_write._atomic_write_json(mpath, written)
            return proj, mpath, shas

        def gs_gate(proj, mpath, carrier, also=None, reuse=False):
            """The group's one gate run, recorded - the real script, so the
            evidence the record checks is a row a real run wrote. `reuse` lets
            the gate repeat an earlier verdict, which is its default."""
            argv = [sys.executable, os.path.join(_output.SCRIPTS_DIR, "governance",
                                                 "run-test-gate.py"),
                    mpath, carrier, "--record", "--project-dir", proj]
            if not reuse:
                argv.append("--no-reuse")
            if also:
                argv += ["--also", also]
            done_ = subprocess.run(argv, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, cwd=proj)
            return done_.returncode

        gs_proj, gs_mp, gs_shas = gs_fixture("gs-plan")
        _gs_before = open(gs_mp, "rb").read()
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", gs_proj])
        _gs_lines = txt.split("\n")
        _gs_land = [ln.strip() for ln in _gs_lines if "close-phase.py" in ln]
        check("gs1 --plan over a group names the review scope from the tasks' "
              "commits - every one, the cancelled task's absence included - and "
              "writes nothing: exit %r, %s" % (code, txt),
              code == 0 and open(gs_mp, "rb").read() == _gs_before
              and all(("git show %s" % gs_shas[t]) in txt
                      for t in ("P1.1", "P2.1"))
              and "src/p1.py" in txt and "src/p2.py" in txt)
        check("gs2 ...ONE gate run over the union and ONE invariants run - counted, "
              "not found: %r"
              % ([ln for ln in _gs_lines if "run-test-gate.py" in ln
                  or "verify-invariants.py" in ln],),
              len([ln for ln in _gs_lines if "run-test-gate.py" in ln]) == 1
              and len([ln for ln in _gs_lines if "verify-invariants.py" in ln]) == 1)
        check("gs3 ...and lands each phase with close-phase --branch, in order, the "
              "branch and its worktree kept until the LAST one - the first landing "
              "merges the whole branch, so a deletion there strands the rest: %r"
              % (_gs_land,),
              len(_gs_land) == 2
              and " P1 " in _gs_land[0] and " P2 " in _gs_land[1]
              and all("--branch combined" in ln for ln in _gs_land)
              and "--keep-branch" in _gs_land[0]
              and "--keep-worktree" in _gs_land[0]
              and "--keep-branch" not in _gs_land[1]
              and "--keep-worktree" not in _gs_land[1])
        g2_proj, g2_mp, _g2 = gs_fixture("gs-gate", gates=(["test"],
                                                           ["test", "lint"]))
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", g2_proj])
        _g2_gate = [ln for ln in txt.split("\n") if "run-test-gate.py" in ln]
        check("gs4 the one gate run is carried by the member whose testGate covers "
              "the union - P2's, here: %r" % (_g2_gate,),
              code == 0 and len(_g2_gate) == 1
              and 'run-test-gate.py" docs/audit/audit-plan.json P2 --also P1'
              in _g2_gate[0])
        g3_proj, g3_mp, _g3 = gs_fixture("gs-nogate", gates=(["lint"], ["test"]))
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", g3_proj])
        check("gs5 ...and when no member's gate covers the union, it is refused, "
              "naming the verb that makes one carry it - no single run could "
              "measure it: exit %r, %s" % (code, txt),
              code == 2 and "run-test-gate.py" not in txt and "retarget" in txt)
        _gs_record = ["signoff", "P1,P2", "--branch", "combined",
                      "--verdict", "passed", "--summary", "both landed",
                      "--review-outcome", "no findings", "--project-dir", gs_proj]
        _gs_b0 = open(gs_mp, "rb").read()
        code, txt = run(_gs_record)
        check("gsb1 the record refuses a group whose branch and baseRef are not "
              "bound yet, naming --bind - the sign-off's invariants run has to see "
              "them, so they are written before it: exit %r, %s" % (code, txt),
              code == 2 and "--bind" in txt and open(gs_mp, "rb").read() == _gs_b0)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--bind",
                         "--project-dir", gs_proj])
        _gs_bound = dict((p["id"], p) for p in _mio.load_manifest(gs_mp)["phases"])
        _gs_fork = gs_git(gs_proj, "merge-base", "main", "combined")
        check("gsb2 --bind writes each member's branch and its fork point as baseRef "
              "and NOTHING of the verdict: %s" % (txt,),
              code == 0 and len(_gs_fork) == 40
              and all(_gs_bound[p]["branch"] == "combined"
                      and _gs_bound[p]["baseRef"] == _gs_fork
                      and not _mio.signoff_recorded(_gs_bound[p])
                      for p in ("P1", "P2")))
        _gs_b1 = open(gs_mp, "rb").read()
        code, txt = run(_gs_record)
        check("gse1 --verdict passed with no gate evidence for the carrier is refused, "
              "naming the gate run that supplies it: exit %r, %s" % (code, txt),
              code == 2 and "run-test-gate.py" in txt and "--also P2" in txt
              and open(gs_mp, "rb").read() == _gs_b1)
        _gs_gate = gs_gate(gs_proj, gs_mp, "P1", "P2")
        code, txt = run(_gs_record)
        _gs_after = dict((p["id"], p) for p in _mio.load_manifest(gs_mp)["phases"])
        check("gs6 the record signs off EVERY member in one write, keeps the bound "
              "branch and baseRef, and stores no done - each reads done once "
              "close-phase lands it: gate %r / %s" % (_gs_gate, txt),
              code == 0
              and all(_gs_after[p]["review"]["status"] == "passed"
                      and _gs_after[p]["summary"] == "both landed"
                      and _gs_after[p]["branch"] == "combined"
                      and _gs_after[p]["baseRef"] == _gs_fork
                      and _gs_after[p]["status"] == "in_progress"
                      and _mio.effective_phase_status(_gs_after[p]) == "in_progress"
                      for p in ("P1", "P2"))
              and len([ln for ln in txt.split("\n") if "close-phase.py" in ln]) == 2)
        _gs_p1ev = _gs_after["P1"].get("testEvidence") or {}
        _gs_p2ev = _gs_after["P2"].get("testEvidence") or {}
        check("gse2 ...and the member that did not carry the gate records the "
              "carrier's run as its evidence, naming the carrier - a record that "
              "outlives this output: %r / %r" % (_gs_p1ev, _gs_p2ev),
              _gs_p1ev.get("runId") and _gs_p2ev.get("runId") == _gs_p1ev["runId"]
              and _gs_p2ev.get("status") == _gs_p1ev.get("status")
              and _gs_p2ev.get("gradedBy") == "P1"
              and "gradedBy" not in _gs_p1ev)
        _gs_rows = [r for r in _journal_io.read_all(gs_proj)
                    if r.get("action") == "phase.verdict"]
        check("gs7 ...with one phase.verdict row per member: %r"
              % ([(r.get("details") or {}).get("phaseId") for r in _gs_rows],),
              sorted((r.get("details") or {}).get("phaseId") for r in _gs_rows)
              == ["P1", "P2"])
        # THE GROUP PATH DERIVES THE TALLY TOO, per member: P2 holds a finding,
        # P1 holds none, and the typed tally in the shared outcome is replaced
        # on the one and dropped on the other, since nothing under it counts.
        gt_proj, gt_mp, _gt_shas = gs_fixture("gs-tally")
        _gt_f = run(["finding", "P2", "--severity", "med", "--file", "src/p2.py",
                     "--issue", "i", "--resolution", "r", "--project-dir", gt_proj])
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", gt_proj])
        _gt_code = run(["signoff", "P1,P2", "--branch", "combined",
                        "--verdict", "skipped", "--summary", "s",
                        "--review-outcome", "matches [findings: 7 - 7 high, 0 med, "
                        "0 low; 7 with a recorded fix commit]",
                        "--project-dir", gt_proj])
        _gt_ph = dict((p["id"], p) for p in _mio.load_manifest(gt_mp)["phases"])
        check("gs6t the GROUP sign-off derives each member's tally from its own "
              "findings - the typed one is replaced where a finding stands under "
              "it and dropped where none does: %r"
              % ((_gt_f[0], _gt_code, [(_gt_ph[p].get("review") or {}).get("outcome")
                                       for p in ("P1", "P2")]),),
              _gt_f[0] == 0 and _gt_code[0] == 0
              and (_gt_ph["P2"].get("review") or {}).get("outcome")
              == "matches [findings: 1 - 0 high, 1 med, 0 low; "
                 "0 with a recorded fix commit]"
              and (_gt_ph["P1"].get("review") or {}).get("outcome") == "matches")

        # THE GROUP IS ASKED THE SAME PROPERTY, every member before any write:
        # under `review.perTask: phase`, a member whose done task holds no phase
        # review's answers refuses the whole group - and filed returns for each
        # member's commits let it through.
        gp_proj, gp_mp, gp_shas = gs_fixture("gs-held")
        _panel_write._atomic_write_json(
            os.path.join(gp_proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json",
             "review": {"perTask": "phase"}})
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", gp_proj])
        _gp_record = ["signoff", "P1,P2", "--branch", "combined",
                      "--verdict", "skipped", "--summary", "s",
                      "--project-dir", gp_proj]
        _gp_b0 = open(gp_mp, "rb").read()
        _gp_held = run(_gp_record)
        _gp_unwritten = open(gp_mp, "rb").read() == _gp_b0
        for _gp_pid, _gp_tid in (("P1", "P1.1"), ("P2", "P2.1")):
            _gp_body = {"findings": [], "preExisting": [],
                        "intent": {"answer": "matches", "note": "n",
                                   "missing": []}, "verdict": "clean",
                        "tasks": [{"id": _gp_tid, "commit": gp_shas[_gp_tid],
                                   "answer": "matches", "note": "n",
                                   "missing": [], "redFirst": "not-attempted",
                                   "redFirstBasis": "gate-only, no test added",
                                   "inheritedTests": "not-asked",
                                   "inheritedTestsBasis": "whole suite"}]}
            _gp_real = sys.stdin
            sys.stdin = io.StringIO(json.dumps(_gp_body))
            try:
                M.main(["file-return", _gp_pid, "--role", "reviewer", "--head",
                        gp_shas["P2.1"], "--project-dir", gp_proj],
                       out=lambda _line: None)
            finally:
                sys.stdin = _gp_real
        _gp_pass = run(_gp_record)
        check("gsp1 under `review.perTask: phase` a GROUP sign-off is refused, "
              "writing nothing, while any member's task is owed its answers - and "
              "signs off once each member's filed return answers its commit: %r"
              % ((_gp_held[0], _gp_held[1][-200:], _gp_pass[0]),),
              _gp_held[0] == 2 and "P1.1" in _gp_held[1]
              and "P2.1" in _gp_held[1] and _gp_unwritten
              and _gp_pass[0] == 0)
        _gp_after = _mio.load_manifest(gp_mp)
        _gp_reads = dict(
            (p.get("id"), (p.get("review") or {}).get(_fr.READ_RETURNS_FIELD))
            for p in _gp_after["phases"] if p.get("id") in ("P1", "P2"))
        _gp_want = dict((pid, _fr.read_record(_fr.phase_returns(
            os.path.join(gp_proj, "docs", "audit", "evidence"), pid)))
            for pid in ("P1", "P2"))
        check("gsp2 a GROUP sign-off records on each member's review the read "
              "set of that member's own filed returns, as the single-phase "
              "verb does: %r" % (_gp_reads,),
              _gp_reads == _gp_want and all(len(v or []) == 1
                                            for v in _gp_reads.values()))

        # A BROKEN INSTALL IS REFUSED BEFORE THE WRITE, on the verbs that have no
        # pre-write validation of their own: sign-off, the group sign-off and
        # seed. Otherwise they write, fail the post-write check on the missing
        # schema and roll back with a sentence blaming the operator's change.
        import _manifest_crossrefs as _bi_xr                      # noqa: E402
        _bi_real = _bi_xr.load_plan_schema

        def _bi_broken(root=None):
            raise OSError("schema gone")

        def _bi_run(argv):
            _bi_xr.load_plan_schema = _bi_broken
            try:
                return run(argv)
            finally:
                _bi_xr.load_plan_schema = _bi_real

        def _bi_ok(code, txt, unchanged):
            return (code == E_INVALID_CODE and unchanged
                    and "install is broken" in txt
                    and "would leave the manifest invalid" not in txt
                    and "is not valid, so nothing was kept" not in txt)
        E_INVALID_CODE = M.E_INVALID
        _bi_one = base_manifest()
        _bi_one["phases"][1]["tasks"][1]["status"] = "done"
        _bi_proj1, _bi_mp1 = mk("bi-signoff", _bi_one, git=True)
        _bi_before1 = open(_bi_mp1, "rb").read()
        _bi_r1 = _bi_run(["signoff", "P2", "--verdict", "skipped", "--summary",
                          "s", "--project-dir", _bi_proj1])
        check("bi1 RED-FIRST: `signoff` on an install whose schema cannot be "
              "read refuses BEFORE writing, says the install is broken, and "
              "the manifest keeps its bytes: %r" % ((_bi_r1[0], _bi_r1[1][-400:]),),
              _bi_ok(_bi_r1[0], _bi_r1[1],
                     open(_bi_mp1, "rb").read() == _bi_before1))
        _bi_proj2, _bi_mp2, _bi_shas = gs_fixture("bi-group")
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", _bi_proj2])
        _bi_before2 = open(_bi_mp2, "rb").read()
        _bi_r2 = _bi_run(["signoff", "P1,P2", "--branch", "combined",
                          "--verdict", "skipped", "--summary", "s",
                          "--project-dir", _bi_proj2])
        check("bi2 RED-FIRST: the GROUP sign-off on the same broken install "
              "refuses before writing, in the same words, and the manifest "
              "keeps its bytes: %r" % ((_bi_r2[0], _bi_r2[1][-400:]),),
              _bi_ok(_bi_r2[0], _bi_r2[1],
                     open(_bi_mp2, "rb").read() == _bi_before2))
        _bi_proj3, _bi_mp3 = mk_empty("bi-seed")
        _bi_r3 = _bi_run(["seed", "--project-dir", _bi_proj3])
        check("bi3 RED-FIRST: `seed` on the same broken install refuses before "
              "writing and creates no file: %r"
              % ((_bi_r3[0], _bi_r3[1][-400:], os.path.exists(_bi_mp3)),),
              _bi_ok(_bi_r3[0], _bi_r3[1], not os.path.exists(_bi_mp3)))
        g4_proj, g4_mp, g4_shas = gs_fixture("gs-stray")
        _g4 = _mio.load_manifest(g4_mp)
        _g4["phases"][1]["tasks"][0]["commit"] = g4_shas["stray"]
        _panel_write._atomic_write_json(g4_mp, _g4)
        _g4_before = open(g4_mp, "rb").read()
        code, txt = run(["signoff", "P1,P2", "--branch", "combined",
                         "--verdict", "passed", "--summary", "s",
                         "--project-dir", g4_proj])
        check("gs8 a task commit the branch does not carry refuses the WHOLE group "
              "and writes nothing - P1 is not signed off beside it: exit %r, %s"
              % (code, txt),
              code == 2 and "P2.1" in txt and open(g4_mp, "rb").read() == _g4_before)
        g5_proj, g5_mp, _g5 = gs_fixture("gs-nocommit")
        _g5m = _mio.load_manifest(g5_mp)
        _g5m["phases"][0]["tasks"][0]["commit"] = None
        _g5m["phases"][1]["branch"] = "elsewhere"
        _panel_write._atomic_write_json(g5_mp, _g5m)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", g5_proj])
        check("gs9 a finished task with no commit, and a member recording ANOTHER "
              "branch, are both refused and both named: exit %r, %s" % (code, txt),
              code == 2 and "task P1.1 records no commit" in txt
              and "records branch 'elsewhere'" in txt)
        code, txt = run(["signoff", "P1,P2", "--verdict", "passed", "--summary", "s",
                         "--project-dir", gs_proj])
        check("gs10 a group without --branch is a usage error naming it: %s" % (txt,),
              code == 2 and "--branch" in txt)
        g6_proj, g6_mp, _g6 = gs_fixture("gs-open")
        _g6m = _mio.load_manifest(g6_mp)
        _g6m["phases"][1]["tasks"][0]["status"] = "in_progress"
        _panel_write._atomic_write_json(g6_mp, _g6m)
        _g6_before = open(g6_mp, "rb").read()
        code, txt = run(["signoff", "P1,P2", "--branch", "combined",
                         "--verdict", "passed", "--summary", "s",
                         "--project-dir", g6_proj])
        check("gs11 one member with open work refuses the group, all or nothing: "
              "exit %r, %s" % (code, txt),
              code == 2 and "P2.1" in txt and open(g6_mp, "rb").read() == _g6_before)
        g8_proj, g8_mp, _g8 = gs_fixture("gs-parents")
        _g8m = _mio.load_manifest(g8_mp)
        _g8m["phases"][1]["parentBranch"] = "develop"
        _panel_write._atomic_write_json(g8_mp, _g8m)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", g8_proj])
        check("gs13 members that land in different parents are refused - one branch "
              "lands in one: exit %r, %s" % (code, txt),
              code == 2 and "develop" in txt and "different parents" in txt)
        g7_proj, g7_mp, _g7 = gs_fixture("gs-sharded", sharded=True)
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", g7_proj])
        gs_gate(g7_proj, g7_mp, "P1", "P2")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined",
                         "--verdict", "passed", "--summary", "s",
                         "--project-dir", g7_proj])
        _g7_ph = dict((p["id"], p) for p in _mio.load_manifest(g7_mp)["phases"])
        check("gs12 in the SHARDED layout every member's shard takes the record, and "
              "no index stub is left behind its shard: %s" % (txt,),
              code == 0 and _mio.stale_stubs(g7_mp) == []
              and all(_g7_ph[p]["review"]["status"] == "passed"
                      and _g7_ph[p]["branch"] == "combined" for p in ("P1", "P2"))
              and "phases/P1.json" in txt and "phases/P2.json" in txt)
        g9_proj, g9_mp, _g9 = gs_fixture("gs-self")
        _g9_before = open(g9_mp, "rb").read()
        code, txt = run(["signoff", "P1,P2", "--branch", "main", "--plan",
                         "--project-dir", g9_proj])
        check("gs14 a group --branch that IS the members' parent is refused - landing "
              "it would plan deleting the parent - and nothing is written or "
              "printed to land: exit %r, %s" % (code, txt),
              code == 2 and "its own parent" in txt and "close-phase.py" not in txt
              and open(g9_mp, "rb").read() == _g9_before)
        g10_proj, g10_mp, _g10 = gs_fixture("gs-unrecorded")
        gs_git(g10_proj, "checkout", "-q", "combined")
        gs_git(g10_proj, "commit", "-q", "--allow-empty", "-m", "hand fix-up")
        _g10_extra = gs_git(g10_proj, "rev-parse", "HEAD")
        gs_git(g10_proj, "checkout", "-q", "main")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", g10_proj])
        check("gs15 a commit on the branch that is no member's recorded commit is "
              "refused BY NAME - the first landing would carry it unreviewed: "
              "exit %r, %s" % (code, txt),
              code == 2 and _g10_extra[:12] in txt and "not reviewed" in txt)
        _journal_io.append_from_cli(g10_proj, {
            "action": "audit.state.committed", "actor": {"via": "cli"},
            "target": "docs/audit/audit-plan.json", "summary": "state",
            "details": {"commit": _g10_extra, "phaseId": "P2"}})
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", g10_proj])
        check("gs16 SECOND DIRECTION: the same commit, journaled as a member's "
              "audit-state commit, is accounted for and the plan stands: exit %r, %s"
              % (code, txt[:300]),
              code == 0 and "not reviewed" not in txt)
        _g10_row_other = gs_fixture("gs-other-phase")
        g11_proj = _g10_row_other[0]
        gs_git(g11_proj, "checkout", "-q", "combined")
        gs_git(g11_proj, "commit", "-q", "--allow-empty", "-m", "another phase")
        _g11_extra = gs_git(g11_proj, "rev-parse", "HEAD")
        gs_git(g11_proj, "checkout", "-q", "main")
        _journal_io.append_from_cli(g11_proj, {
            "action": "audit.state.committed", "actor": {"via": "cli"},
            "target": "docs/audit/audit-plan.json", "summary": "state",
            "details": {"commit": _g11_extra, "phaseId": "P7"}})
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", g11_proj])
        check("gs17 ...but a commit the journal records for a phase OUTSIDE the "
              "group is still refused: exit %r, %s" % (code, txt[:300]),
              code == 2 and _g11_extra[:12] in txt)
        g12_proj = gs_fixture("gs-plan-sharded", sharded=True)[0]
        _gs_plan_lines = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                              "--project-dir", g12_proj])[1]
        check("gs18 the plan prints the commit step's commands too - one "
              "commit-audit-state per member and the index commit in the sharded "
              "layout - and the gate spelled with --also: %s" % (_gs_plan_lines,),
              ('commit-audit-state.py" docs/audit/audit-plan.json P1'
               in _gs_plan_lines
               and 'commit-audit-state.py" docs/audit/audit-plan.json P2'
               in _gs_plan_lines
               and "commit-manifest-index.py" in _gs_plan_lines
               and 'run-test-gate.py" docs/audit/audit-plan.json P1 --also P2'
               in _gs_plan_lines))
        # --- sign-off's gate evidence on the single-phase path too --------------
        s1_proj, s1_mp, _s1 = gs_fixture("so-evidence")
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--project-dir", s1_proj])
        check("so11 --verdict passed on ONE phase with no gate evidence is refused, "
              "naming the gate run and the reason flag: exit %r, %s" % (code, txt),
              code == 2 and "run-test-gate.py" in txt
              and "--no-evidence-reason" in txt)
        gs_gate(s1_proj, s1_mp, "P1")
        os.makedirs(os.path.join(s1_proj, "src"), exist_ok=True)
        with open(os.path.join(s1_proj, "src", "p1.py"), "w") as fh:
            fh.write("changed after the gate\n")
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--project-dir", s1_proj])
        check("so12 ...and evidence taken BEFORE the phase's files changed is not "
              "current, so it is refused too: exit %r, %s" % (code, txt),
              code == 2 and "have changed since it was measured" in txt)
        gs_gate(s1_proj, s1_mp, "P1")
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--project-dir", s1_proj])
        check("so13 SECOND DIRECTION: with a current recorded run, the same sign-off "
              "is written: exit %r, %s" % (code, txt), code == 0)
        s2_proj, s2_mp, _s2 = gs_fixture("so-reason")
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--no-evidence-reason", "graded by hand: no runner here",
                         "--project-dir", s2_proj])
        _s2_ph = [p for p in _mio.load_manifest(s2_mp)["phases"]
                  if p["id"] == "P1"][0]
        check("so14 ...and an explicit reason is RECORDED on the review, where the "
              "evidence badge on the report and the panel shows it: exit %r, %r"
              % (code, _s2_ph.get("review")),
              code == 0 and (_s2_ph.get("review") or {}).get("noEvidenceReason")
              == "graded by hand: no runner here")
        s3_proj, s3_mp, _s3 = gs_fixture("so-skipped")
        code, txt = run(["signoff", "P1", "--verdict", "skipped", "--summary", "s",
                         "--project-dir", s3_proj])
        check("so15 --verdict skipped needs no gate evidence - it says no review "
              "passed anything: exit %r, %s" % (code, txt), code == 0)
        # A REASON OUTLIVING ITS SIGN-OFF: an earlier review left one behind, and
        # a later `passed` stands on a bound run with no reason of its own. The
        # landing honours a recorded reason, so a stale one would excuse a green
        # this sign-off did stand on.
        s4_proj, s4_mp, _s4 = gs_fixture("so-stale-reason")
        _s4m = _mio.load_manifest(s4_mp)
        _s4m["phases"][0]["review"] = {"status": "failed",
                                       "noEvidenceReason": "graded by hand"}
        _panel_write._atomic_write_json(s4_mp, _s4m)
        gs_gate(s4_proj, s4_mp, "P1")
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--project-dir", s4_proj])
        _s4_ph = [p for p in _mio.load_manifest(s4_mp)["phases"]
                  if p["id"] == "P1"][0]
        check("so16 RED-FIRST: a sign-off that gives no --no-evidence-reason drops "
              "the one an earlier review recorded - the reason belongs to the "
              "sign-off that gave it: exit %r, review %r"
              % (code, _s4_ph.get("review")),
              code == 0 and (_s4_ph.get("review") or {}).get("status") == "passed"
              and "noEvidenceReason" not in (_s4_ph.get("review") or {}))
        s5_proj, s5_mp, _s5 = gs_fixture("so-stale-reason-group")
        _s5m = _mio.load_manifest(s5_mp)
        for _s5p in _s5m["phases"]:
            _s5p["review"] = {"status": "failed",
                              "noEvidenceReason": "graded by hand"}
        _panel_write._atomic_write_json(s5_mp, _s5m)
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", s5_proj])
        gs_gate(s5_proj, s5_mp, "P1", "P2")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--verdict",
                         "passed", "--summary", "s", "--project-dir", s5_proj])
        _s5_reviews = [p.get("review") or {}
                       for p in _mio.load_manifest(s5_mp)["phases"]]
        check("so17 RED-FIRST: ...and so does a GROUP sign-off, on every member: "
              "exit %r, reviews %r, %s" % (code, _s5_reviews, txt[-200:]),
              code == 0 and all("noEvidenceReason" not in r for r in _s5_reviews))

        # ---- (ve) ONE verdict-binding rule: sign-off grades as a task commit does
        def ve_rows(proj):
            return _ve_evidence.read_rows(proj)["rows"]
        import _evidence_io as _ve_evidence
        v1_proj, v1_mp, _v1 = gs_fixture("ve-reuse")
        gs_gate(v1_proj, v1_mp, "P1")
        _v1_rc = gs_gate(v1_proj, v1_mp, "P1", reuse=True)
        _v1_reused = [r for r in ve_rows(v1_proj)
                      if r.get(_ve_evidence.VERDICT_SOURCE) == _ve_evidence.REUSED]
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--project-dir", v1_proj])
        check("ve1 a phase gate recorded once with --no-reuse and again WITH reuse - "
              "the gate's default - signs off `passed`: the repeat is graded "
              "against the run that measured it: gate %r, reused rows %d, exit %r, %s"
              % (_v1_rc, len(_v1_reused), code, txt),
              _v1_rc == 0 and len(_v1_reused) == 1 and code == 0)
        v2_proj, v2_mp, _v2 = gs_fixture("ve-orphan")
        gs_gate(v2_proj, v2_mp, "P1")
        gs_gate(v2_proj, v2_mp, "P1", reuse=True)
        _v2_src = [r for r in ve_rows(v2_proj)
                   if r.get(_ve_evidence.VERDICT_SOURCE) == _ve_evidence.REUSED]
        _v2_origin = ((_v2_src or [{}])[0].get("reusedFrom") or {}).get("runId")
        for _v2_path in _ve_evidence.ledger_files(v2_proj):
            with open(_v2_path) as fh:
                _v2_lines = fh.read().splitlines(True)
            with open(_v2_path, "w") as fh:
                fh.write("".join(ln for ln in _v2_lines
                                 if not (_v2_origin and _v2_origin in ln
                                         and '"reusedFrom"' not in ln)))
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--project-dir", v2_proj])
        check("ve2 SECOND DIRECTION: a repeated verdict whose source run is gone from "
              "the ledger is refused - the tree it was measured on is not "
              "established: origin %r, exit %r, %s" % (_v2_origin, code, txt),
              bool(_v2_origin) and code == 2 and "not in the ledger" in txt)
        v3_proj, v3_mp, _v3 = gs_fixture("ve-manifest")
        _v3m = _mio.load_manifest(v3_mp)
        _v3m["phases"][0]["tasks"][0]["files"] = ["src/p1.py",
                                                  "docs/audit/audit-plan.json"]
        _v3m["fileIndex"]["docs/audit/audit-plan.json"] = ["P1.1"]
        _panel_write._atomic_write_json(v3_mp, _v3m)
        gs_gate(v3_proj, v3_mp, "P1")
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--project-dir", v3_proj])
        check("ve3 a phase that declares its own manifest file signs off: the "
              "recorder's own writes to it are left out on both sides, as a task "
              "commit leaves them: exit %r, %s" % (code, txt), code == 0)
        v4_proj, v4_mp, _v4 = gs_fixture("ve-gate-changed")
        _v4m = _mio.load_manifest(v4_mp)
        _v4m["phases"][0]["testGate"] = []
        _panel_write._atomic_write_json(v4_mp, _v4m)
        gs_gate(v4_proj, v4_mp, "P1")
        _v4m = _mio.load_manifest(v4_mp)
        _v4m["phases"][0]["testGate"] = ["test"]
        _panel_write._atomic_write_json(v4_mp, _v4m)
        code, txt = run(["signoff", "P1", "--verdict", "passed", "--summary", "s",
                         "--project-dir", v4_proj])
        check("ve4 an `empty-gate` run recorded before the gate gained an entry backs "
              "no `passed` - a gate changed after the measurement: exit %r, %s"
              % (code, txt), code == 2 and "different gate" in txt)
        v5_proj, v5_mp, _v5 = gs_fixture("ve-group-reuse")
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", v5_proj])
        gs_gate(v5_proj, v5_mp, "P1", "P2")
        gs_gate(v5_proj, v5_mp, "P1", "P2", reuse=True)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--verdict",
                         "passed", "--summary", "s", "--project-dir", v5_proj])
        check("ve5 the group's gate, repeated by reuse, still backs the group's "
              "`passed`: exit %r, %s" % (code, txt), code == 0)
        v6_proj, v6_mp, _v6 = gs_fixture("ve-group-alone")
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", v6_proj])
        gs_gate(v6_proj, v6_mp, "P1")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--verdict",
                         "passed", "--summary", "s", "--project-dir", v6_proj])
        check("ve6 a carrier run that did NOT own the other member (no --also) backs "
              "no group verdict, and the refusal names the member it left out: "
              "exit %r, %s" % (code, txt),
              code == 2 and "P2" in txt and "--also P2" in txt)

        v7_proj, v7_mp, _v7 = gs_fixture("ve-group-owned")
        _v7m = _mio.load_manifest(v7_mp)
        _v7m["phases"][1]["tasks"][0]["files"] = ["src/p1.py"]
        _v7m["fileIndex"] = {"src/p1.py": ["P1.1", "P2.1"]}
        _panel_write._atomic_write_json(v7_mp, _v7m)
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", v7_proj])
        gs_gate(v7_proj, v7_mp, "P1")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--verdict",
                         "passed", "--summary", "s", "--project-dir", v7_proj])
        check("ve7 even over the SAME files, a carrier run that did not own the other "
              "member (no `groupWith` on its row) backs no group verdict: exit %r, %s"
              % (code, txt), code == 2 and "owned P1 alone, not P2" in txt)
        _v7_again = gs_gate(v7_proj, v7_mp, "P1", "P2", reuse=True)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--verdict",
                         "passed", "--summary", "s", "--project-dir", v7_proj])
        check("ve8 ...and the command that refusal prints, run as printed - WITH the "
              "gate's default reuse - reaches sign-off: a group run never repeats a "
              "solo one: gate %r, exit %r, %s" % (_v7_again, code, txt),
              _v7_again == 0 and code == 0)
        n1_proj, n1_mp, _n1 = gs_fixture("ve-nogate-old", gates=(["test"], []))
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", n1_proj])
        gs_gate(n1_proj, n1_mp, "P1")
        _n1m = _mio.load_manifest(n1_mp)
        _n1m["phases"][0]["testGate"] = []
        _panel_write._atomic_write_json(n1_mp, _n1m)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--verdict",
                         "passed", "--summary", "s", "--project-dir", n1_proj])
        _n1_p2 = [p for p in _mio.load_manifest(n1_mp)["phases"] if p["id"] == "P2"][0]
        check("ve9 a carrier whose gate declares no entry copies NO old run onto the "
              "members - the sign-off rests on review alone, and says so: exit %r, "
              "P2 evidence %r, %s" % (code, _n1_p2.get("testEvidence"), txt),
              code == 0 and not _n1_p2.get("testEvidence")
              and "rests on review alone" in txt)

        # ---- (ga) what a group branch may carry that no member records --------
        a1_proj, a1_mp, _a1 = gs_fixture("ga-accept")
        gs_git(a1_proj, "checkout", "-q", "combined")
        gs_git(a1_proj, "commit", "-q", "--allow-empty", "-m", "planning")
        _a1_extra = gs_git(a1_proj, "rev-parse", "HEAD")
        gs_git(a1_proj, "checkout", "-q", "main")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--accept", _a1_extra, "--reason", "the multi-phase plan",
                         "--project-dir", a1_proj])
        check("ga1 --accept <sha> --reason lets a commit no member records into the "
              "group, and the plan lists it for review rather than hiding it: "
              "exit %r, %s" % (code, txt),
              code == 0 and ("git show %s" % (_a1_extra,)) in txt
              and "the multi-phase plan" in txt)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--accept", _a1_extra, "--project-dir", a1_proj])
        check("ga2 ...and --accept with no --reason is refused: an accepted commit "
              "is recorded with why: exit %r, %s" % (code, txt),
              code == 2 and "--reason" in txt)
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--accept", _a1_extra, "--reason", "the multi-phase plan",
             "--project-dir", a1_proj])
        gs_gate(a1_proj, a1_mp, "P1", "P2")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--verdict",
                         "passed", "--summary", "s", "--accept", _a1_extra,
                         "--reason", "the multi-phase plan",
                         "--project-dir", a1_proj])
        _a1_ph = dict((p["id"], p) for p in _mio.load_manifest(a1_mp)["phases"])
        check("ga3 ...and the record writes the accepted commit and its reason on "
              "every member's review: exit %r, %r"
              % (code, [_a1_ph[p].get("review") for p in ("P1", "P2")]),
              code == 0 and all(
                  [{"commit": _a1_extra, "reason": "the multi-phase plan"}]
                  == (_a1_ph[p].get("review") or {}).get("acceptedCommits")
                  for p in ("P1", "P2")))
        # A branch BUILT BY MERGING the members' own branches, --no-ff.
        m_plan = base_manifest()
        m_plan["phases"] = [
            {"id": "P1", "title": "One", "status": "in_progress", "testGate": ["test"],
             "branch": None, "baseRef": None,
             "tasks": [{"id": "P1.1", "title": "a", "status": "done",
                        "files": ["src/p1.py"]}]},
            {"id": "P2", "title": "Two", "status": "in_progress", "testGate": ["test"],
             "branch": None, "baseRef": None,
             "tasks": [{"id": "P2.1", "title": "b", "status": "done",
                        "files": ["src/p2.py"]}]}]
        m_proj, m_mp = mk("ga-merged", m_plan, git=True)
        gs_git(m_proj, "checkout", "-q", "-b", "main")
        gs_git(m_proj, "commit", "-q", "--allow-empty", "-m", "base")
        _m_sha = {}
        for tid, side in (("P1.1", "side1"), ("P2.1", "side2")):
            gs_git(m_proj, "checkout", "-q", "-b", side, "main")
            gs_git(m_proj, "commit", "-q", "--allow-empty", "-m", tid)
            _m_sha[tid] = gs_git(m_proj, "rev-parse", "HEAD")
        gs_git(m_proj, "checkout", "-q", "-b", "combined", "main")
        gs_git(m_proj, "merge", "-q", "--no-ff", "-m", "merge side1", "side1")
        gs_git(m_proj, "merge", "-q", "--no-ff", "-m", "merge side2", "side2")
        gs_git(m_proj, "checkout", "-q", "main")
        _m_m = _mio.load_manifest(m_mp)
        for _ph in _m_m["phases"]:
            for _t in _ph["tasks"]:
                _t["commit"] = _m_sha[_t["id"]]
        _panel_write._atomic_write_json(m_mp, _m_m)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", m_proj])
        check("ga4 a combined branch built by merging the members' branches is "
              "accounted for: each merge commit's parents are member commits or the "
              "parent side: exit %r, %s" % (code, txt[:400]), code == 0)
        # A merge that CARRIES CONTENT OF ITS OWN - an evil merge or a conflict
        # resolution - is not made of its parents and is refused unless accepted.
        e_proj, e_mp = mk("ga-evil", m_plan, git=True)
        gs_git(e_proj, "checkout", "-q", "-b", "main")
        gs_git(e_proj, "commit", "-q", "--allow-empty", "-m", "base")
        _e_sha = {}
        for tid, side in (("P1.1", "side1"), ("P2.1", "side2")):
            gs_git(e_proj, "checkout", "-q", "-b", side, "main")
            with open(os.path.join(e_proj, "%s.txt" % side), "w") as fh:
                fh.write(tid + "\n")
            gs_git(e_proj, "add", "%s.txt" % side)
            gs_git(e_proj, "commit", "-q", "-m", tid)
            _e_sha[tid] = gs_git(e_proj, "rev-parse", "HEAD")
        gs_git(e_proj, "checkout", "-q", "-b", "combined", "main")
        gs_git(e_proj, "merge", "-q", "--no-ff", "-m", "merge side1", "side1")
        gs_git(e_proj, "merge", "-q", "--no-ff", "--no-commit", "side2")
        with open(os.path.join(e_proj, "backdoor.txt"), "w") as fh:
            fh.write("nobody reviewed this\n")
        gs_git(e_proj, "add", "backdoor.txt")
        gs_git(e_proj, "commit", "-q", "-m", "merge side2")
        _e_evil = gs_git(e_proj, "rev-parse", "HEAD")
        gs_git(e_proj, "checkout", "-q", "main")
        _e_m = _mio.load_manifest(e_mp)
        for _ph in _e_m["phases"]:
            for _t in _ph["tasks"]:
                _t["commit"] = _e_sha[_t["id"]]
        _panel_write._atomic_write_json(e_mp, _e_m)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", e_proj])
        check("ga8 a merge whose tree is not the automatic merge of its parents "
              "carries content of its own, and is refused by name for review: "
              "exit %r, %s" % (code, txt),
              code == 2 and _e_evil[:12] in txt and "of its own" in txt)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--accept", _e_evil, "--reason", "the conflict resolution",
                         "--project-dir", e_proj])
        _e_tree = gs_git(e_proj, "merge-tree", "--write-tree", _e_evil + "^1",
                         _e_evil + "^2").split("\n")[0].strip()
        check("ga8b ...and --accept takes it into the review, listed with the "
              "comparison the check made - the automatic merge's tree against the "
              "merge (`git diff <tree> <sha>`): exit %r, %s" % (code, txt),
              code == 0 and ("git diff %s %s" % (_e_tree, _e_evil)) in txt)

        def ga_merged(name, how, extra=None):
            """(proj, mpath, shas) - side1 (P1.1) and side2 (P2.1), each adding one
            file, merged into `combined` from main. `how` is "two" for two --no-ff
            merges, "octopus" for one merge of both, "drop" for a second merge that
            leaves side2's file out, "evil-then-clean" for an edited first merge and
            a clean second."""
            proj, mpath = mk(name, m_plan, git=True)
            gs_git(proj, "checkout", "-q", "-b", "main")
            gs_git(proj, "commit", "-q", "--allow-empty", "-m", "base")
            shas = {}
            for tid, side in (("P1.1", "side1"), ("P2.1", "side2")):
                gs_git(proj, "checkout", "-q", "-b", side, "main")
                with open(os.path.join(proj, "%s.txt" % side), "w") as fh:
                    fh.write(tid + "\n")
                gs_git(proj, "add", "%s.txt" % side)
                gs_git(proj, "commit", "-q", "-m", tid)
                shas[tid] = gs_git(proj, "rev-parse", "HEAD")
            gs_git(proj, "checkout", "-q", "-b", "combined", "main")
            if how == "octopus":
                gs_git(proj, "merge", "-q", "--no-ff", "-m", "octopus", "side1",
                       "side2")
            elif how in ("evil-then-clean", "evil-then-evil"):
                gs_git(proj, "merge", "-q", "--no-ff", "--no-commit", "side1")
                with open(os.path.join(proj, "edit.txt"), "w") as fh:
                    fh.write("an edit inside the merge\n")
                gs_git(proj, "add", "edit.txt")
                gs_git(proj, "commit", "-q", "-m", "merge side1")
                shas["m1"] = gs_git(proj, "rev-parse", "HEAD")
                if how == "evil-then-evil":
                    gs_git(proj, "merge", "-q", "--no-ff", "--no-commit", "side2")
                    with open(os.path.join(proj, "edit2.txt"), "w") as fh:
                        fh.write("a second edit inside a merge\n")
                    gs_git(proj, "add", "edit2.txt")
                    gs_git(proj, "commit", "-q", "-m", "merge side2")
                else:
                    gs_git(proj, "merge", "-q", "--no-ff", "-m", "merge side2",
                           "side2")
                shas["m2"] = gs_git(proj, "rev-parse", "HEAD")
            else:
                gs_git(proj, "merge", "-q", "--no-ff", "-m", "merge side1", "side1")
                shas["m1"] = gs_git(proj, "rev-parse", "HEAD")
                if how == "drop":
                    gs_git(proj, "merge", "-q", "--no-ff", "--no-commit", "side2")
                    gs_git(proj, "rm", "-q", "-f", "side2.txt")
                    gs_git(proj, "commit", "-q", "-m", "merge side2")
                else:
                    gs_git(proj, "merge", "-q", "--no-ff", "-m", "merge side2",
                           "side2")
                shas["m2"] = gs_git(proj, "rev-parse", "HEAD")
            gs_git(proj, "checkout", "-q", "main")
            plan_now = _mio.load_manifest(mpath)
            for ph in plan_now["phases"]:
                for t in ph["tasks"]:
                    t["commit"] = shas[t["id"]]
            _panel_write._atomic_write_json(mpath, plan_now)
            return proj, mpath, shas

        # A git that cannot recompute a merge (before 2.38, or a missing object)
        # is a question not asked - never an edit.
        o_proj, o_mp, o_shas = ga_merged("ga-oldgit", "two")
        _real = M._worktrees._runner(None)

        def _old_git(git_root, argv, timeout=60):
            if argv[:2] == ["merge-tree", "--write-tree"]:
                return 128, "", "fatal: unknown rev --write-tree\n"
            return _real(git_root, argv)
        _o_plan = M.group_plan(_mio.load_manifest(o_mp), ["P1", "P2"], "combined",
                               o_proj, run=_old_git, journal_rows=[])
        _o_text = "\n".join(_o_plan["refusals"])
        check("ga11 under a git that cannot recompute a merge, each clean merge is "
              "refused as a question that could not be asked - git's own line and the "
              "2.38 floor named - and never as an edit: %s" % (_o_text,),
              "could not be asked" in _o_text and "2.38" in _o_text
              and "unknown rev --write-tree" in _o_text
              and "an edit" not in _o_text and o_shas["m1"][:12] in _o_text)
        _o_m2 = [ln for ln in _o_plan["refusals"] if o_shas["m2"][:12] in ln
                 and ln.find(o_shas["m2"][:12]) < 20]
        check("ga11b ...and the merge above it is JUDGED now, not promised accounting "
              "it was never checked for: under this git it too could not be asked, "
              "said with its own reason and the refused merge below it: %s"
              % (_o_m2,),
              len(_o_m2) == 1 and "could not be asked" in _o_m2[0]
              and ("also a merge over %s" % (o_shas["m1"][:12],)) in _o_m2[0]
              and "accounted once" not in _o_text
              and "no member records" not in _o_text)
        od_proj, od_mp, od_shas = ga_merged("ga-oldgit-drop", "drop")
        _od_plan = M.group_plan(_mio.load_manifest(od_mp), ["P1", "P2"], "combined",
                                od_proj, run=_old_git, journal_rows=[])
        _od_text = "\n".join(_od_plan["refusals"])
        _od_cmd = [c for c in _od_text.split("`") if c.startswith("git show -m ")
                   and od_shas["m2"] in c]
        _od_out = (subprocess.run(_od_cmd[0].split(), cwd=od_proj,
                                  stdout=subprocess.PIPE).stdout.decode()
                   if _od_cmd else "")
        check("ga11c a merge that DROPS a side, under a git that cannot recompute it, "
              "names a review command that shows the drop - a diff against each "
              "parent (`git show -m`), where `git show` alone shows nothing: "
              "command %r, shows side2.txt %r" % (_od_cmd, "side2.txt" in _od_out),
              len(_od_cmd) == 1 and "side2.txt" in _od_out)
        oc_proj, oc_mp, oc_shas = ga_merged("ga-octopus", "octopus")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", oc_proj])
        check("ga12 a clean OCTOPUS merge is refused as not established - merge-tree "
              "recomputes two parents only - and not as an edit: exit %r, %s"
              % (code, txt),
              code == 2 and "octopus" in txt and "an edit" not in txt
              and "could not be asked" in txt
              and "carries content of its own" not in txt)
        d_proj, d_mp, d_shas = ga_merged("ga-drop", "drop")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", d_proj])
        _d_cmd = [ln for ln in txt.split("`") if ln.startswith("git diff ")]
        _d_out = (subprocess.run(_d_cmd[0].split(), cwd=d_proj,
                                 stdout=subprocess.PIPE).stdout.decode()
                  if _d_cmd else "")
        check("ga13 a merge that silently DROPS a side's change is refused, and the "
              "review command it prints shows the dropped change - where `git show "
              "--cc` shows nothing: exit %r, command %r, shows %r"
              % (code, _d_cmd, _d_out[:120]),
              code == 2 and len(_d_cmd) == 1 and "side2.txt" in _d_out
              and "git show --cc" not in txt)
        w_proj, w_mp, w_shas = ga_merged("ga-waiting", "evil-then-clean")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", w_proj])
        check("ga14 a clean merge over a refused merge is named as waiting on it: "
              "exit %r, %s" % (code, txt),
              code == 2 and ("%s is a merge over %s" % (w_shas["m2"][:12],
                                                        w_shas["m1"][:12])) in txt)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--accept", w_shas["m1"], "--reason", "the edit is reviewed",
                         "--project-dir", w_proj])
        check("ga14b ...and once the refused merge is accepted, the clean merge over "
              "it is accounted and the plan stands: exit %r, %s" % (code, txt),
              code == 0)
        ww_proj, ww_mp, ww_shas = ga_merged("ga-evil-evil", "evil-then-evil")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", ww_proj])
        check("ga14c a merge with content of its own over a refused merge is refused "
              "NOW with its own reason - never promised accounting once the one below "
              "is: exit %r, %s" % (code, txt),
              code == 2 and "accounted once" not in txt
              and ("merge %s carries content of its own" % (ww_shas["m2"][:12],))
              in txt)
        # One --accept names ONE commit.
        p_proj, p_mp, _p = gs_fixture("ga-prefix")
        gs_git(p_proj, "checkout", "-q", "combined")
        _p_extra = []
        for i in range(24):
            gs_git(p_proj, "commit", "-q", "--allow-empty", "-m", "stray%d" % i)
            _p_extra.append(gs_git(p_proj, "rev-parse", "HEAD"))
        gs_git(p_proj, "checkout", "-q", "main")
        _p_short = _p_extra[0][:1]
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--accept", _p_short, "--reason", "r",
                         "--project-dir", p_proj])
        check("ga9 an --accept value that does not resolve to exactly one commit - a "
              "one-character prefix - is refused by name, and takes nothing in: "
              "exit %r, %s" % (code, txt),
              code == 2 and ("--accept %s" % (_p_short,)) in txt
              and "exactly one commit" in txt)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--accept", "0" * 40, "--reason", "r",
                         "--project-dir", p_proj])
        check("ga9b ...and so is a full SHA that names no commit",
              code == 2 and "exactly one commit" in txt, txt)
        q_proj, q_mp, _q = gs_fixture("ga-unique")
        gs_git(q_proj, "checkout", "-q", "combined")
        gs_git(q_proj, "commit", "-q", "--allow-empty", "-m", "planning")
        _q_extra = gs_git(q_proj, "rev-parse", "HEAD")
        gs_git(q_proj, "checkout", "-q", "main")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--accept", _q_extra[:12], "--reason", "r",
                         "--project-dir", q_proj])
        check("ga9c SECOND DIRECTION: a unique short SHA resolves to its one commit, "
              "listed in full: exit %r, %s" % (code, txt),
              code == 0 and ("git show %s" % (_q_extra,)) in txt)
        _q_ref = _q_extra[:6]
        gs_git(q_proj, "branch", _q_ref, "main")
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--accept", _q_ref, "--reason", "r", "--project-dir", q_proj])
        check("ga10b a HEX-spelled name that is also a branch resolves through the ref, "
              "not to the commit it prefixes - refused, saying it names a ref: exit %r, "
              "%s" % (code, txt),
              code == 2 and ("--accept %s names a ref" % (_q_ref,)) in txt)
        gs_git(q_proj, "branch", "-D", _q_ref)
        for _ref in ("combined", "HEAD", "combined~0"):
            code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                             "--accept", _ref, "--reason", "r",
                             "--project-dir", q_proj])
            check("ga10 --accept %s - a ref or a revision expression, re-resolved on "
                  "every call - is refused by name: it takes a hex SHA: exit %r, %s"
                  % (_ref, code, txt),
                  code == 2 and ("--accept %s is not a commit SHA" % (_ref,)) in txt)
        # The group-only flags on ONE phase are refused, not ignored.
        f_proj, f_mp, _f = gs_fixture("gs-single-flags")
        _f_before = open(f_mp, "rb").read()
        code, txt = run(["signoff", "P1", "--bind", "--project-dir", f_proj])
        check("gs19 `signoff P1 --bind` is refused, naming the group form - it used "
              "to ask for a verdict: exit %r, %s" % (code, txt),
              code == 2 and "--branch" in txt and "--verdict" not in txt
              and open(f_mp, "rb").read() == _f_before)
        code, txt = run(["signoff", "P1", "--accept", "abc123", "--reason", "r",
                         "--verdict", "skipped", "--summary", "s",
                         "--project-dir", f_proj])
        check("gs19b ...and so is --accept on one phase, with nothing written - it "
              "used to sign off and record nothing of the accept: exit %r, %s"
              % (code, txt),
              code == 2 and "--branch" in txt and open(f_mp, "rb").read() == _f_before)
        g8b_proj, g8b_mp, g8b_shas = gs_fixture("ga-rebased")
        _g8b = _mio.load_manifest(g8b_mp)
        _g8b["phases"][1]["tasks"][0]["commit"] = g8b_shas["stray"]
        _panel_write._atomic_write_json(g8b_mp, _g8b)
        code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                         "--project-dir", g8b_proj])
        check("ga5 a recorded task commit missing from the branch names "
              "repair-commits.py, the verb that re-points a rebased task: exit %r, %s"
              % (code, txt), code == 2 and "repair-commits.py" in txt)
        j_proj, j_mp, _j = gs_fixture("ga-journal")
        gs_git(j_proj, "checkout", "-q", "combined")
        gs_git(j_proj, "commit", "-q", "--allow-empty", "-m", "audit-state")
        gs_git(j_proj, "checkout", "-q", "main")
        _j_real = M._journal_io.read_all

        def _j_broken(*_a, **_k):
            raise IOError("the trail is not readable here")
        M._journal_io.read_all = _j_broken
        try:
            code, txt = run(["signoff", "P1,P2", "--branch", "combined", "--plan",
                             "--project-dir", j_proj])
        finally:
            M._journal_io.read_all = _j_real
        check("ga6 a commit that only the journal could account for, with the journal "
              "unreadable, is said as that - not as a commit no member records: "
              "exit %r, %s" % (code, txt),
              code == 2 and "journal could not be read" in txt
              and "the trail is not readable here" in txt)
        b_proj, b_mp, _b = gs_fixture("ga-bind-trail")
        run(["signoff", "P1,P2", "--branch", "combined", "--bind",
             "--project-dir", b_proj])
        gs_gate(b_proj, b_mp, "P1", "P2")
        run(["signoff", "P1,P2", "--branch", "combined", "--verdict", "passed",
             "--summary", "s", "--project-dir", b_proj])
        _b_rows = _journal_io.read_all(b_proj)
        _b_bind = [r for r in _b_rows if r.get("action") == "phase.bind"]
        _b_ptr = [r for r in _b_rows if r.get("action") == "phase.testEvidence"
                  and (r.get("details") or {}).get("phaseId") == "P2"
                  and (r.get("details") or {}).get("fromPhase") == "P1"]
        check("ga7 --bind journals a phase.bind row per member, and the record "
              "journals the copied pointer on P2 naming P1: %r / %r"
              % ([(r.get("details") or {}).get("phaseId") for r in _b_bind],
                 [r.get("summary") for r in _b_ptr]),
              sorted((r.get("details") or {}).get("phaseId") for r in _b_bind)
              == ["P1", "P2"] and len(_b_ptr) == 1)

        # ---- (sv) a close stores its bug's derived status; settle stores the rest
        # A linked bug derives `fixed` and its `fixedIn` from its fix task's close,
        # and `bugs[]` lives in the INDEX, so the close writes the index here and
        # nowhere else - `pd12` pins that a close with no bug leaves it untouched.
        bugfix = pd_fixture()
        bugfix["phases"][1]["tasks"][-1]["bugId"] = "BUG-1"
        bugfix["bugs"] = [{"id": "BUG-1", "title": "b", "status": "triaged",
                           "taskId": "P2.4", "fixedIn": None},
                          {"id": "BUG-2", "title": "other", "status": "triaged",
                           "taskId": None, "fixedIn": None}]
        projbf, mpbf = mk("sv-bugfix", bugfix, sharded=True)
        code, txt = run(["done", "P2.4", "--commit", _PD_SHA,
                         "--project-dir", projbf] + _NOT_ASKED)
        _bf_idx = _mio.read_json(mpbf)
        _bf = dict((b["id"], b) for b in _bf_idx.get("bugs") or [])
        check("sv1 closing a bug's fix task stores the bug's derived `fixed` and "
              "its `fixedIn` on the index, says so with the basis, and leaves "
              "the bug it does not fix alone: %r / %s"
              % (_bf, txt[-300:]),
              code == 0 and _bf["BUG-1"]["status"] == "fixed"
              and _bf["BUG-1"]["fixedIn"] == _PD_SHA
              and _bf["BUG-2"]["status"] == "triaged"
              and _bf["BUG-2"]["fixedIn"] is None
              and "stored bug BUG-1.status: triaged -> fixed" in txt
              and "fix task P2.4 is done" in txt
              and "commit-manifest-index.py" in txt)

        # A plan carrying stale values from before the verbs stored them: a
        # parent-branch phase signed off at in_progress, a stub mirroring an old
        # status, a bug whose fix task is done, a person's `wontfix` beside it, and
        # a signed-off BRANCH phase that has not merged - the last two are the
        # values settle must NOT move.
        stale = base_manifest()
        stale["phases"][1].update(status="in_progress", review={"status": "passed"})
        stale["phases"][1]["tasks"][1].update(status="done", commit=_PD_SHA,
                                              bugId="BUG-1")
        stale["phases"][2].update(status="in_progress", branch="feature/p3",
                                  review={"status": "passed"},
                                  tasks=[{"id": "P3.1", "title": "x",
                                          "status": "done"}])
        stale["bugs"] = [{"id": "BUG-1", "title": "b", "status": "in_progress",
                          "taskId": "P2.3", "fixedIn": None},
                         {"id": "BUG-2", "title": "w", "status": "wontfix",
                          "taskId": None, "fixedIn": None}]
        projst, mpst = mk("sv-settle", stale, sharded=True, git=True)
        _st_idx = _mio.read_json(mpst)
        for _stub in _st_idx["phases"]:
            if _stub.get("id") == "P1":
                _stub["status"] = "in_progress"      # a stub fallen behind its shard
        _panel_write._atomic_write_json(mpst, _st_idx)
        _st_drift = _mio.derived_disagreements(_mio.load_manifest(mpst))
        code, txt = run(["settle", "--project-dir", projst])
        _st_after = _mio.load_manifest(mpst)
        _st_idx2 = _mio.read_json(mpst)
        _st_stub = dict((s["id"], s.get("status")) for s in _st_idx2["phases"])
        _st_ph = dict((p["id"], p) for p in _st_after["phases"])
        _st_bug = dict((b["id"], b) for b in _st_after["bugs"])
        check("sv2 settle stores every derived value a stale plan carries - the "
              "phase on its shard AND stub, a stub fallen behind its shard, the "
              "bug's status and fixedIn - and leaves the derivation with nothing "
              "to say: %s" % (txt,),
              code == 0
              and sorted((r["id"], r["field"]) for r in _st_drift)
              == [("BUG-1", "fixedIn"), ("BUG-1", "status"), ("P2", "status")]
              and _st_ph["P2"]["status"] == "done" and _st_stub["P2"] == "done"
              and _st_stub["P1"] == "done"
              and _st_bug["BUG-1"]["status"] == "fixed"
              and _st_bug["BUG-1"]["fixedIn"] == _PD_SHA
              and _mio.derived_disagreements(_st_after) == [])
        check("sv3 ...and moves NOTHING the derivation does not answer: a person's "
              "`wontfix` stays, and a signed-off phase on an unmerged branch stays "
              "in_progress on shard and stub - the cases that go red when settle "
              "writes done for every signed-off phase: P3=%r/%r BUG-2=%r"
              % (_st_ph["P3"]["status"], _st_stub["P3"], _st_bug["BUG-2"]["status"]),
              _st_ph["P3"]["status"] == "in_progress" and _st_stub["P3"] == "in_progress"
              and _st_bug["BUG-2"]["status"] == "wontfix")
        _st_rows = [r for r in _journal_io.read_all(projst)
                    if r.get("action") == "plan.settle"]
        check("sv4 ...with ONE plan.settle journal row naming each value it moved: %r"
              % ([(r.get("details") or {}).get("changes") for r in _st_rows],),
              len(_st_rows) == 1
              and sorted((c.get("id"), c.get("field")) for c in
                         (_st_rows[0].get("details") or {}).get("changes") or [])
              == [("BUG-1", "fixedIn"), ("BUG-1", "status"), ("P2", "status")])
        with open(mpst, "rb") as _fh:
            _st_bytes = _fh.read()
        code, txt = run(["settle", "--project-dir", projst])
        check("sv5 a second settle has nothing to do, says what it examined, writes "
              "not a byte and journals nothing: %s" % (txt,),
              code == 0 and "nothing to settle" in txt and "examined" in txt
              and open(mpst, "rb").read() == _st_bytes
              and len([r for r in _journal_io.read_all(projst)
                       if r.get("action") == "plan.settle"]) == 1)
        # THE SINGLE-FILE LAYOUT, which writes the whole plan in one file and has
        # no stub to re-mirror: the same stale plan, the same answers.
        projsf, mpsf = mk("sv-settle-single", stale, git=True)
        code, txt = run(["settle", "--project-dir", projsf])
        _sf_after = _mio.load_manifest(mpsf)
        _sf_ph = dict((p["id"], p) for p in _sf_after["phases"])
        _sf_bug = dict((b["id"], b) for b in _sf_after["bugs"])
        check("sv6 settle on the SINGLE-FILE layout stores the phase's and the bug's "
              "derived values, leaves the unmerged branch phase and the wontfix "
              "alone, and journals one plan.settle row: %s" % (txt,),
              code == 0 and not _mio.is_sharded(_mio.read_json(mpsf))
              and _sf_ph["P2"]["status"] == "done"
              and _sf_ph["P3"]["status"] == "in_progress"
              and _sf_bug["BUG-1"]["status"] == "fixed"
              and _sf_bug["BUG-1"]["fixedIn"] == _PD_SHA
              and _sf_bug["BUG-2"]["status"] == "wontfix"
              and _mio.derived_disagreements(_sf_after) == []
              and len([r for r in _journal_io.read_all(projsf)
                       if r.get("action") == "plan.settle"]) == 1)
        with open(mpsf, "rb") as _fh:
            _sf_bytes = _fh.read()
        code, txt = run(["settle", "--project-dir", projsf])
        check("sv7 ...and a second settle there writes nothing and journals nothing: "
              "%s" % (txt,),
              code == 0 and "nothing to settle" in txt
              and open(mpsf, "rb").read() == _sf_bytes
              and len([r for r in _journal_io.read_all(projsf)
                       if r.get("action") == "plan.settle"]) == 1)

        # ---- (ro) re-open: a done task goes back to pending, or is refused -----
        # A SIGNED-OFF PHASE IS NOT RE-OPENED THROUGH ONE OF ITS TASKS. Its done is
        # stored now, and a stored done wins inside the derivation, so re-opening a
        # task under it leaves a phase marked done over open work - a FINDING that
        # makes every verb after it refuse the plan as already invalid, the verb
        # that would close the re-opened task included. And the phase could never
        # be signed again: its verdict is on record and sign-off is not re-decided.
        # The hand re-open `commands/run.md` prescribed is the path this repro
        # walks, so the case first shows what it led to.
        rosigned = base_manifest()
        rosigned["phases"][1]["tasks"][1].update(status="done", commit=_PD_SHA,
                                                 completedAt="2026-01-02T00:00:00Z")
        projro, mpro = mk("ro-signed", rosigned)
        run(["signoff", "P2", "--verdict", "passed", "--summary", "s",
             "--no-evidence-reason", "fixture", "--project-dir", projro])
        _ro_hand = _mio.load_manifest(mpro)
        for _t in _ro_hand["phases"][1]["tasks"]:
            if _t["id"] == "P2.3":
                _t.update(status="pending", attempts=0, commit=None,
                          completedAt=None)
        _ro_hand_proj, _ro_hand_mp = mk("ro-hand", _ro_hand)
        code_h, txt_h = run(["start", "P2.3", "--project-dir", _ro_hand_proj])
        check("ro0 the hand re-open under a signed-off phase leaves a stored done "
              "over open work, and the next verb refuses the plan as already "
              "invalid - the dead end the verb below refuses to walk into: %r"
              % (txt_h[-160:],),
              code_h == M.E_INVALID and "already invalid" in txt_h)
        with open(mpro, "rb") as _fh:
            _ro_before = _fh.read()
        code, txt = run(["reopen", "P2.3", "--reason", "regressed",
                         "--project-dir", projro])
        check("ro1 `reopen` REFUSES a task whose phase is signed off, writes not a "
              "byte, and names the two ways forward - a new task in an open "
              "phase, or /audit:bug: %s" % (txt,),
              code == 2 and "signed off" in txt
              and "/audit:task add" in txt and "/audit:bug" in txt
              and open(mpro, "rb").read() == _ro_before)
        robranch = base_manifest()
        robranch["phases"][1]["tasks"][1].update(status="done", commit=_PD_SHA)
        robranch["phases"][1].update(branch="feature/p2",
                                     review={"status": "passed"})
        projrb, _mprb = mk("ro-awaiting-merge", robranch)
        code, txt = run(["reopen", "P2.3", "--reason", "r", "--project-dir", projrb])
        check("ro2 ...and so is a phase signed off and only awaiting its merge: it "
              "still reads in_progress, but the verdict on record reviewed the work "
              "as it stands: %s" % (txt,),
              code == 2 and "signed off" in txt)
        roopen = base_manifest()
        roopen["phases"][1]["tasks"][0].update(
            commit=_PD_SHA, completedAt="2026-01-02T00:00:00Z", attempts=1,
            outcome={"technical": "t", "descriptive": "d"}, verifiedBy=["t1"],
            bugId="BUG-1")
        roopen["bugs"] = [{"id": "BUG-1", "title": "b", "status": "fixed",
                           "taskId": "P2.1", "fixedIn": _PD_SHA}]
        projrop, mprop = mk("ro-open", roopen)
        code, txt = run(["reopen", "P2.1", "--reason", "regressed in prod",
                         "--project-dir", projrop])
        _ro_m = _mio.load_manifest(mprop)
        _ro_t = [t for t in _ro_m["phases"][1]["tasks"] if t["id"] == "P2.1"][0]
        _ro_b = _ro_m["bugs"][0]
        _ro_rows = [r for r in _journal_io.read_all(projrop)
                    if r.get("action") == "task.reopen"]
        check("ro3 the ALLOW case: a done task in an open phase goes back to "
              "pending with its close cleared, its bug goes back to in_progress "
              "with no fixedIn, one task.reopen row carries the reason, and the "
              "plan still validates: %s" % (txt,),
              code == 0 and _ro_t["status"] == "pending" and _ro_t["attempts"] == 0
              and _ro_t["commit"] is None and _ro_t["completedAt"] is None
              and _ro_t["outcome"] == {"technical": None, "descriptive": None}
              and _ro_t["verifiedBy"] == []
              and _ro_b["status"] == "in_progress" and _ro_b["fixedIn"] is None
              and len(_ro_rows) == 1
              and (_ro_rows[0].get("details") or {}).get("reason")
              == "regressed in prod"
              and _panel_write._cores()[0].validate(_ro_m)[0] == [])
        code, txt = run(["reopen", "P2.3", "--reason", "r", "--project-dir", projrop])
        check("ro4 ...and a task that is not done is refused: there is no close to "
              "undo: %s" % (txt,), code == 2 and "not done" in txt)

        # ---- (bs) the branch suffix: ids two branches cannot both mint --------
        def git(proj, *a):
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.run(["git", "-C", proj] + list(a), check=True, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        import _id_shape
        projb, mpathb = mk("bs-branch", base_manifest(), git=True)
        git(projb, "checkout", "-q", "-b", "main")
        git(projb, "commit", "-q", "--allow-empty", "-m", "base")
        git(projb, "checkout", "-q", "-b", "feature/x")
        sfx = _id_shape.branch_suffix("feature/x", base_manifest())
        code, txt = run(["add", "On a side branch", "--phase", "P2",
                         "--project-dir", projb])
        check("bs1 a task added on a side branch carries that branch's suffix, so a "
              "second branch adding to P2 cannot mint the same id: %s" % (txt,),
              code == 0 and task_in(mpathb, "P2.4-%s" % sfx) is not None)
        code, txt = run(["add-phase", "Side work", "--outcome", "done",
                         "--project-dir", projb])
        check("bs2 a phase is NEVER suffixed, even added on a side branch - phases are "
              "minted on the development branch (a side branch is warned and offered "
              "a proposal instead), and a phase id is a branch, lock and shard name: %s"
              % (txt,),
              code == 0 and any(p.get("id") == "P4" for p in
                                _mio.load_manifest(mpathb)["phases"]))
        code, txt = run(["add", "In the side phase", "--phase", "P4",
                         "--project-dir", projb])
        check("bs3 ...while a task added to it on that branch still carries the suffix: %s"
              % (txt,),
              code == 0 and task_in(mpathb, "P4.1-%s" % sfx) is not None)
        code, txt = run(["next-id", "bug", "--project-dir", projb])
        check("bs4 next-id bug on a side branch prints BUG-<max+1>-<suffix>: %r" % (txt,),
              code == 0 and txt.strip().splitlines()[-1] == "BUG-1-%s" % sfx)
        git(projb, "checkout", "-q", "main")
        code, txt = run(["add", "On main", "--phase", "P2", "--project-dir", projb])
        check("bs5 SECOND DIRECTION: on the development branch the id is exactly what "
              "it was before - P2.5, no suffix, the number continuing past the "
              "suffixed sibling: %s" % (txt,),
              code == 0 and task_in(mpathb, "P2.5") is not None)
        code, txt = run(["next-id", "bug", "--project-dir", projb])
        check("bs6 ...and next-id bug there prints plain BUG-1: %r" % (txt,),
              code == 0 and txt.strip().splitlines()[-1] == "BUG-1")
        code, txt = run(["next-id", "prop", "--project-dir", projb])
        check("bs6b next-id prop on the development branch prints PROP-1: %r" % (txt,),
              code == 0 and txt.strip().splitlines()[-1] == "PROP-1")
        git(projb, "checkout", "-q", "feature/x")
        code, txt = run(["next-id", "prop", "--project-dir", projb])
        check("bs6c ...and on a side branch PROP-1-<suffix>, because a proposal parked "
              "on a phase branch is exactly the record two branches both write: %r"
              % (txt,), code == 0 and txt.strip().splitlines()[-1] == "PROP-1-%s" % sfx)
        # ---- (pk) a phase on a side branch: warned once, or parked ------------
        # A branch of its own, so "the first time on this branch" is not already
        # spent by bs2's add-phase on feature/x.
        import _journal_io
        git(projb, "checkout", "-q", "-b", "feature/y")
        sfy = _id_shape.branch_suffix("feature/y", base_manifest())
        phases_before = [p["id"] for p in _mio.load_manifest(mpathb)["phases"]]
        code, txt = run(["add-phase", "Parked idea", "--outcome", "later",
                         "--park", "--project-dir", projb])
        man = _mio.load_manifest(mpathb)
        parked = [p for p in man.get("proposals") or [] if p.get("name") == "Parked idea"]
        check("pk1 add-phase --park on a side branch writes NO live phase and parks the "
              "same phase as a proposal carrying the branch suffix and the branch: %s"
              % (txt,),
              code == 0 and [p["id"] for p in man["phases"]] == phases_before
              and len(parked) == 1 and parked[0]["id"] == "PROP-1-%s" % sfy
              and parked[0]["status"] == "proposed" and parked[0].get("branch") == "feature/y"
              and parked[0]["payload"]["phase"]["title"] == "Parked idea")
        check("pk2 ...the parked payload is the SAME phase add-phase would have written "
              "(its template), reserving a SUFFIXED placeholder rather than the next "
              "plain P<n> - two branches parking one each would otherwise both reserve "
              "it - and the plan still validates",
              parked and parked[0]["payload"]["phase"].get("desiredOutcome") == "later"
              and parked[0]["payload"]["phase"]["id"] == "P5-%s" % sfy
              and not _rules.validate(man)[0])
        check("pk3 ...and it says how the phase gets out: materialize after the phase "
              "branch merges, on the development branch: %s" % (txt,),
              "materialize" in txt and "PROP-1-%s" % sfy in txt and "main" in txt)
        code, txt = run(["add-phase", "Side phase", "--outcome", "o",
                         "--project-dir", projb])
        check("pk4 a live add-phase on a side branch is NOT blocked, and the first one on "
              "that branch warns, naming the development branch and --park: %s" % (txt,),
              code == 0 and "was minted on feature/y, not on the development branch "
              "main" in txt and "--park" in txt)
        rows = [r for r in _journal_io.read_all(projb)
                if r.get("action") == "phase.add"
                and (r.get("details") or {}).get("branch") == "feature/y"]
        check("pk5 ...and the phase.add row records the branch it was minted on, which "
              "is what 'the first time' is read from: %r" % (rows,), len(rows) == 1)
        code, txt = run(["add-phase", "Another side phase", "--outcome", "o",
                         "--project-dir", projb])
        check("pk6 the SECOND add-phase on that branch is silent - warned once, never "
              "nagged: %s" % (txt,), code == 0 and "was minted on" not in txt)
        git(projb, "checkout", "-q", "main")
        code, txt = run(["add-phase", "Trunk phase", "--outcome", "o",
                         "--project-dir", projb])
        check("pk7 SECOND DIRECTION: add-phase on the development branch never warns: %s"
              % (txt,), code == 0 and "was minted on" not in txt)
        code, txt = run(["add-phase", "Trunk idea", "--outcome", "o", "--park",
                         "--project-dir", projb])
        check("pk8 --park on the development branch parks an unsuffixed PROP: %s" % (txt,),
              code == 0 and any(p.get("name") == "Trunk idea" and p["id"] == "PROP-2"
                                for p in _mio.load_manifest(mpathb).get("proposals")))
        # ---- (cb) several phases running: the checked-out branch decides -----
        # Three developers leave several in_progress phases in the shared index;
        # "the current phase" is the one whose branch is checked out here.
        two = base_manifest()
        two["phases"][2]["status"] = "in_progress"
        two["phases"][1]["branch"] = "feature/p2-live"
        two["phases"][2]["branch"] = "feature/p3-parked"
        projc, mpathc = mk("cb-branch", two, git=True)
        git(projc, "checkout", "-q", "-b", "main")
        git(projc, "commit", "-q", "--allow-empty", "-m", "base")
        git(projc, "checkout", "-q", "-b", "feature/p3-parked")
        code, txt = run(["add", "Found while on P3", "--project-dir", projc])
        sfc = _id_shape.branch_suffix("feature/p3-parked", two)
        check("cb1 with two phases in_progress, a task added without --phase goes to the "
              "one whose recorded branch is checked out, and says why: %s" % (txt,),
              code == 0 and task_in(mpathc, "P3.1-%s" % sfc) is not None
              and "feature/p3-parked" in txt)
        code, txt = run(["add", "Found again", "--project-dir", projc, "--json"])
        try:
            payload = json.loads(txt)
        except ValueError as exc:
            payload = {"unparseable": str(exc)}
        check("cb1b ...and under --json the output stays ONE parseable object, carrying "
              "why that phase was chosen: %r" % (txt[:200],),
              code == 0 and "feature/p3-parked" in json.dumps(payload.get("phaseBasis")))
        git(projc, "checkout", "-q", "-b", "feature/unrelated")
        code, txt = run(["add", "From nowhere", "--project-dir", projc])
        check("cb2 SECOND DIRECTION: on a branch no running phase records, --phase is "
              "still required - a guess would write another developer's phase: %s"
              % (txt,), code == 2 and "--phase required" in txt)

        git(projb, "checkout", "-q", "feature/x")
        code, txt = run(["next-id", "task", "--phase", "P2", "--project-dir", projb])
        before_ids = sorted(_mio.tasks_by_id(_mio.load_manifest(mpathb)))
        check("bs8 next-id task --phase prints the id a hand-written task takes, from the "
              "SAME allocator `add` uses - its suffix, and past every sibling: %r" % (txt,),
              code == 0 and txt.strip().splitlines()[-1] == "P2.6-%s" % sfx)
        check("bs9 ...and writes nothing", sorted(_mio.tasks_by_id(
            _mio.load_manifest(mpathb))) == before_ids)
        code, txt = run(["next-id", "task", "--project-dir", projb])
        check("bs10 next-id task without --phase refuses: a task id belongs to a phase",
              code == 2 and "--phase" in txt, txt)
        code, txt = run(["next-id", "phase", "--project-dir", projb])
        check("bs7 next-id takes no `phase`: a phase id is minted only by add-phase, "
              "which writes it under the lock", code == 2, txt)

        # ---- (pe) phase entry: the first start cuts the phase branch ---------
        # `orchestrator.md`'s Phase entry was prose run BEFORE `start`, so a phase
        # driven through the verbs never got a branch at all. `start` performs it.
        import _branch

        def head_of(proj):
            return subprocess.check_output(
                ["git", "-C", proj, "symbolic-ref", "--short", "-q", "HEAD"]
            ).decode().strip()

        def sha_of(proj, ref):
            return subprocess.check_output(
                ["git", "-C", proj, "rev-parse", ref]).decode().strip()

        def entry_repo(name, manifest=None):
            proj, mp = mk(name, manifest or base_manifest(), git=True)
            git(proj, "checkout", "-q", "-b", "main")
            git(proj, "commit", "-q", "--allow-empty", "-m", "base")
            return proj, mp

        def p2_of(mp):
            return [p for p in _mio.load_manifest(mp)["phases"] if p["id"] == "P2"][0]

        want = _branch.phase_answer(base_manifest()["meta"], base_manifest()["phases"][1],
                                    "")["branch"]
        proje, mpe = entry_repo("pe-cut")
        base_sha = sha_of(proje, "HEAD")
        code, txt = run(["start", "P2.3", "--project-dir", proje])
        ph = p2_of(mpe)
        check("pe1 the first start of a phase with no branch, on its parent, CUTS the "
              "branch: checked out, recorded on the phase with the commit it forked "
              "from, and said: %s" % (txt,),
              code == 0 and head_of(proje) == want and ph.get("branch") == want
              and ph.get("baseRef") == base_sha and want in txt)
        rows = [r for r in _journal_io.read_all(proje) if r.get("action") == "task.start"]
        check("pe1b ...and the start row records the branch it cut",
              bool(rows) and want in (rows[-1].get("summary") or "")
              and (rows[-1].get("details") or {}).get("branch") == want, rows[-1:])
        mfix = base_manifest()
        mfix["phases"][1]["tasks"].append({"id": "P2.4", "title": "c",
                                           "status": "pending"})
        projf, mpf = entry_repo("pe-onbranch", mfix)
        run(["start", "P2.3", "--project-dir", projf])
        code, txt = run(["start", "P2.4", "--project-dir", projf])
        check("pe2 a later start on the phase's own branch cuts nothing and changes "
              "nothing about the branch: %s" % (txt,),
              code == 0 and head_of(projf) == want and p2_of(mpf).get("branch") == want)
        git(projf, "checkout", "-q", "main")
        before = open(mpf, "rb").read()
        code, txt = run(["start", "P2.4", "--project-dir", projf])
        check("pe3 a phase that records a branch REFUSES a start from any other one, "
              "names both and the switch, and writes nothing: %s" % (txt,),
              code == 2 and want in txt and "main" in txt and "git switch" in txt
              and open(mpf, "rb").read() == before)
        projs, mps = entry_repo("pe-side")
        git(projs, "checkout", "-q", "-b", "feature/other")
        before = open(mps, "rb").read()
        code, txt = run(["start", "P2.3", "--project-dir", projs])
        check("pe4 the first start OFF the resolved parent refuses, naming the parent "
              "and where it came from, and neither writes nor branches: %s" % (txt,),
              code == 2 and "main" in txt and "feature/other" in txt
              and open(mps, "rb").read() == before and head_of(projs) == "feature/other"
              and subprocess.run(["git", "-C", projs, "rev-parse", "--verify", "-q",
                                  "refs/heads/" + want],
                                 stdout=subprocess.DEVNULL).returncode != 0)
        projd, mpd = entry_repo("pe-detached")
        git(projd, "checkout", "-q", "--detach")
        code, txt = run(["start", "P2.3", "--project-dir", projd])
        check("pe5 a detached HEAD refuses - there is no branch to fork from: %s" % (txt,),
              code == 2 and "detached" in txt.lower())
        proju, mpu = mk("pe-unborn", base_manifest(), git=True)
        code, txt = run(["start", "P2.3", "--project-dir", proju])
        check("pe6 a repository with no commit yet refuses and says to commit first - "
              "there is no base for the phase to fork from: %s" % (txt,),
              code == 2 and "commit" in txt.lower() and task_in(mpu, "P2.3")["status"]
              == "pending")
        projt, mpt = entry_repo("pe-taken")
        git(projt, "branch", want)
        code, txt = run(["start", "P2.3", "--project-dir", projt])
        check("pe7 a branch name already taken that the phase does not record refuses "
              "rather than adopting a branch nothing says is this phase's: %s" % (txt,),
              code == 2 and want in txt and "already exists" in txt
              and p2_of(mpt).get("branch") is None)
        projw, mpw = entry_repo("pe-adopt")
        fork_sha = sha_of(projw, "HEAD")
        git(projw, "checkout", "-q", "-b", want)
        git(projw, "commit", "-q", "--allow-empty", "-m", "on the branch already")
        code, txt = run(["start", "P2.3", "--project-dir", projw])
        check("pe8 standing on EXACTLY the branch the plan composes for this phase - "
              "what /audit:worktree add checks out - records it, with the fork point "
              "as baseRef, instead of refusing it for not being the parent: %s" % (txt,),
              code == 0 and p2_of(mpw).get("branch") == want
              and p2_of(mpw).get("baseRef") == fork_sha)
        projr, mpr = entry_repo("pe-rollback")
        git(projr, "branch", "audit")
        before = open(mpr, "rb").read()
        code, txt = run(["start", "P2.3", "--project-dir", projr])
        check("pe9 when git refuses the cut after the write (here a branch `audit` "
              "blocks `audit/...`), the write is rolled back and the refusal carries "
              "git's reason: %s" % (txt,),
              code != 0 and open(mpr, "rb").read() == before and head_of(projr) == "main")
        projn, mpn = mk("pe-nogit", base_manifest())
        code, txt = run(["start", "P2.3", "--project-dir", projn])
        check("pe10 outside a git repository the phase runs with no branch, and the "
              "output says so rather than implying one: %s" % (txt,),
              code == 0 and p2_of(mpn).get("branch") is None
              and "no git repository" in txt)
        projh, mph = mk("pe-sharded", base_manifest(), sharded=True, git=True)
        git(projh, "checkout", "-q", "-b", "main")
        git(projh, "add", "-A")
        git(projh, "commit", "-q", "-m", "base")
        h_sha = sha_of(projh, "HEAD")
        code, txt = run(["start", "P2.3", "--project-dir", projh])
        with open(mph, encoding="utf-8") as fh:
            h_stub = [p for p in json.load(fh)["phases"] if p["id"] == "P2"][0]
        h_shard_path = os.path.join(os.path.dirname(mph), h_stub.get("shard") or "")
        with open(h_shard_path, encoding="utf-8") as fh:
            h_shard = json.load(fh)
        check("pe11 on the SHARDED layout the cut lands branch and baseRef in the phase's "
              "shard - the file a phase run owns - and not in the index stub, which two "
              "phase branches would otherwise both rewrite: %r"
              % ({k: h_stub.get(k) for k in ("branch", "baseRef")},),
              code == 0 and head_of(projh) == want and h_shard.get("branch") == want
              and h_shard.get("baseRef") == h_sha
              and "branch" not in h_stub and "baseRef" not in h_stub)
        # ---- (ia) an intent question deliberately not asked, and its reader ---
        # `--intent` took three words, every one of them a reviewer's answer, so a
        # close whose reviewer was skipped ON PURPOSE (a two-string edit) had no
        # spelling: omitting the flag records the same absence as a reviewer call
        # that died, and those are opposite facts. `not-asked` is the fourth word,
        # and it carries its reason or it is refused.
        projia, mpia = mk("ia-not-asked", pd_fixture())
        code, txt = run(["done", "P2.4", "--commit", _PD_SHA, "--intent", "not-asked",
                         "--intent-basis", "two-string copy edit, reviewer not spawned",
                         "--project-dir", projia])
        _ia_t = task_in(mpia, "P2.4") or {}
        check("ia1 `--intent not-asked --intent-basis TEXT` records a deliberate "
              "no-question as its own answer, the basis verbatim beside the SHA: %s"
              % (txt,),
              code == 0 and (_ia_t.get("intentCheck") or {}).get("answer") == "not-asked"
              and (_ia_t.get("intentCheck") or {}).get("basis")
              == "two-string copy edit, reviewer not spawned"
              and (_ia_t.get("intentCheck") or {}).get("commit") == _PD_SHA)
        projia2, mpia2 = mk("ia-no-basis", pd_fixture())
        with open(mpia2, "rb") as _fh:
            _ia_before = _fh.read()
        _ia_nob = run(["done", "P2.4", "--commit", _PD_SHA, "--intent", "not-asked",
                       "--project-dir", projia2])
        _ia_orphan = run(["done", "P2.4", "--commit", _PD_SHA,
                          "--intent-basis", "a reason with no answer",
                          "--project-dir", projia2])
        with open(mpia2, "rb") as _fh:
            _ia_after = _fh.read()
        check("ia2 `not-asked` with no basis is refused, and so is a basis with no "
              "answer beside it - a skip nobody can explain reads exactly like a "
              "reviewer call that never came back; nothing written: %r"
              % ((_ia_nob[0], _ia_orphan[0], _ia_nob[1][:100]),),
              _ia_nob[0] == 2 and "--intent-basis" in _ia_nob[1]
              and _ia_orphan[0] == 2 and "--intent" in _ia_orphan[1]
              and _ia_after == _ia_before)
        # THE READER. Nothing read `intentCheck` at all, so an absent answer was
        # invisible everywhere a phase is judged. Sign-off is where the answer is
        # owed, so it names the done tasks carrying none - and a deliberate
        # `not-asked` IS an answer, which is the second direction.
        iasign = base_manifest()
        iasign["phases"][1]["tasks"][1].update(status="done", commit=_PD_SHA)
        iasign["phases"][1]["tasks"].append(
            {"id": "P2.5", "title": "skipped on purpose", "status": "done",
             "commit": _PD_SHA,
             "intentCheck": {"answer": "not-asked", "basis": "copy edit",
                             "commit": _PD_SHA}})
        projis, _mpis = mk("ia-signoff", iasign)
        code, txt = run(["signoff", "P2", "--verdict", "passed", "--summary", "s",
                         "--no-evidence-reason", "the case is about intent answers",
                         "--project-dir", projis])
        _ia_line = [ln for ln in txt.splitlines() if "no intent answer" in ln]
        check("ia3 sign-off NAMES the done tasks with no intent answer, and leaves "
              "out the one whose answer is a deliberate not-asked: %r" % (_ia_line,),
              code == 0 and len(_ia_line) == 1 and "P2.1" in _ia_line[0]
              and "P2.3" in _ia_line[0] and "P2.5" not in _ia_line[0])
        projis2, _mpis2 = mk("ia-signoff-json", iasign)
        code, txt = run(["signoff", "P2", "--verdict", "passed", "--summary", "s",
                         "--no-evidence-reason", "the case is about intent answers",
                         "--json", "--project-dir", projis2])
        try:
            _ia_js = json.loads(txt)
        except ValueError:
            _ia_js = {}
        check("ia4 ...and `--json` carries the same list as data: %r"
              % (_ia_js.get("intentUnanswered"),),
              code == 0 and _ia_js.get("intentUnanswered") == ["P2.1", "P2.3"])
        iaall = base_manifest()
        iaall["phases"][1]["tasks"] = [
            {"id": "P2.1", "title": "a", "status": "done", "commit": _PD_SHA,
             "files": ["src/a.ts"],
             "intentCheck": {"answer": "matches", "commit": _PD_SHA}}]
        projia3, _mpia3 = mk("ia-signoff-answered", iaall)
        code, txt = run(["signoff", "P2", "--verdict", "passed", "--summary", "s",
                         "--no-evidence-reason", "the case is about intent answers",
                         "--project-dir", projia3])
        check("ia5 SECOND DIRECTION: a phase whose every done task carries an answer "
              "prints no such line - the one an always-on list would fail: %s" % (txt,),
              code == 0 and "no intent answer" not in txt)
        with open(os.path.join(_output.PLUGIN_ROOT, "schema",
                               "audit-plan.schema.json"), encoding="utf-8") as _fh:
            _ia_enum = (json.load(_fh)["$defs"]["intentCheck"]["properties"]
                        ["answer"]["enum"])
        _ia_choices = [a.choices for a in M.build_parser()._actions
                       if a.dest == "intent"]
        check("ia6 the words `--intent` accepts are the schema enum's, in its order - "
              "a word the parser took and the schema does not list is a value the "
              "schema calls invalid, and one the schema lists and the parser does "
              "not is an answer nobody can record - except `deferred`, which the "
              "enum lists and only the close itself writes, so no caller can "
              "type it: %r" % ((_ia_choices, _ia_enum),),
              _ia_choices == [list(M.INTENT_ANSWERS)]
              and list(M.INTENT_ANSWERS) + [_fr.INTENT_DEFERRED] == _ia_enum
              and _fr.INTENT_DEFERRED not in M.INTENT_ANSWERS)

        # ---- (nc) a close that changed nothing, on purpose -----------------------
        # `done` demanded a SHA, so a task whose correct answer was "nothing needs
        # to change" had two exits and both were wrong: `cancel` (it WAS done) or a
        # fabricated commit. `--no-change --reason` closes it with the reason and
        # the HEAD it examined, and no commit - which is what it really has.
        projnc, mpnc, headnc = pd_repo("nc-close", pd_fixture())
        code, txt = run(["done", "P2.4", "--no-change",
                         "--reason", "backend-only, nothing to edit here",
                         "--project-dir", projnc])
        _nc_t = task_in(mpnc, "P2.4") or {}
        _nc_rows = [r for r in _journal_io.read_all(projnc)
                    if r.get("action") == "task.done"]
        check("nc1 `done --no-change --reason` closes a started task with no commit, "
              "recording outcome.noChange {reason, examinedAt: HEAD} and leaving the "
              "outcome half nobody named standing: %s" % (txt,),
              code == 0 and _nc_t.get("status") == "done"
              and _nc_t.get("commit") is None
              and (_nc_t.get("outcome") or {}).get("noChange")
              == {"reason": "backend-only, nothing to edit here",
                  "examinedAt": headnc}
              and (_nc_t.get("outcome") or {}).get("technical")
              == "attempt 1: gate red on t_checkout"
              and len(_nc_rows) == 1
              and (_nc_rows[0].get("details") or {}).get("reason")
              == "backend-only, nothing to edit here")
        projnc2, mpnc2 = mk("nc-refusals", pd_fixture())
        with open(mpnc2, "rb") as _fh:
            _nc_before = _fh.read()
        _nc_noreason = run(["done", "P2.4", "--no-change", "--project-dir", projnc2])
        _nc_both = run(["done", "P2.4", "--no-change", "--reason", "r",
                        "--commit", _PD_SHA, "--project-dir", projnc2])
        _nc_stray = run(["done", "P2.4", "--commit", _PD_SHA, "--reason", "r",
                         "--project-dir", projnc2])
        with open(mpnc2, "rb") as _fh:
            _nc_after = _fh.read()
        check("nc2 `--no-change` with no reason, `--no-change` beside a commit, and a "
              "`--reason` on a close that is not a no-change close are each refused, "
              "and nothing is written: %r"
              % ((_nc_noreason[0], _nc_both[0], _nc_stray[0]),),
              _nc_noreason[0] == 2 and "--reason" in _nc_noreason[1]
              and _nc_both[0] == 2 and "--no-change" in _nc_both[1]
              and _nc_stray[0] == 2 and "--no-change" in _nc_stray[1]
              and _nc_after == _nc_before)
        projnc3, mpnc3 = mk("nc-nogit", pd_fixture())
        code, txt = run(["done", "P2.4", "--no-change", "--reason", "nothing to do",
                         "--project-dir", projnc3])
        _nc3 = ((task_in(mpnc3, "P2.4") or {}).get("outcome") or {}).get("noChange")
        check("nc3 with no git to ask, the close is written with examinedAt null and "
              "the output SAYS the examined commit was not recorded: %s" % (txt,),
              code == 0 and isinstance(_nc3, dict) and _nc3.get("examinedAt") is None
              and "examinedAt: NOT RECORDED" in txt)
        ncpend = base_manifest()
        projnc4, _mpnc4 = mk("nc-unstarted", ncpend)
        code, txt = run(["done", "P2.3", "--no-change", "--reason", "r",
                         "--project-dir", projnc4])
        check("nc4 a task that was never started is still refused: a no-change close "
              "claims the task was LOOKED AT, and nothing records that it was: %s"
              % (txt,), code == 2 and "start" in txt)

        # ---- (bk) a task set blocked, with the reason it is waiting --------------
        projbk, mpbk = mk("bk-block", base_manifest())
        code, txt = run(["block", "P2.3", "--reason", "waiting on the BE endpoint",
                         "--project-dir", projbk])
        _bk_t = task_in(mpbk, "P2.3") or {}
        _bk_rows = [r for r in _journal_io.read_all(projbk)
                    if r.get("action") == "task.block"]
        check("bk1 `block <id> --reason` sets status blocked, keeps the reason in "
              "blockedReason and writes one task.block row carrying it: %s" % (txt,),
              code == 0 and _bk_t.get("status") == "blocked"
              and _bk_t.get("blockedReason") == "waiting on the BE endpoint"
              and len(_bk_rows) == 1
              and (_bk_rows[0].get("details") or {}).get("reason")
              == "waiting on the BE endpoint")
        with open(mpbk, "rb") as _fh:
            _bk_before = _fh.read()
        _bk_noreason = run(["block", "P2.1", "--project-dir", projbk])
        _bk_done = run(["block", "P2.1", "--reason", "r", "--project-dir", projbk])
        _bk_phase = run(["block", "P2", "--reason", "r", "--project-dir", projbk])
        _bk_again = run(["block", "P2.3", "--reason", "r2", "--project-dir", projbk])
        with open(mpbk, "rb") as _fh:
            _bk_after = _fh.read()
        check("bk2 no reason, a done task, a phase id and an already-blocked task "
              "are each refused and nothing is written: %r"
              % ([_bk_noreason[0], _bk_done[0], _bk_phase[0], _bk_again[0]],),
              [_bk_noreason[0], _bk_done[0], _bk_phase[0], _bk_again[0]]
              == [2, 2, 2, 2] and "already blocked" in _bk_again[1]
              and _bk_after == _bk_before)
        code, txt = run(["start", "P2.3", "--project-dir", projbk])
        _bk_s = task_in(mpbk, "P2.3") or {}
        _bk_start = [c for r in _journal_io.read_all(projbk)
                     if r.get("action") == "task.start"
                     for c in ((r.get("details") or {}).get("changes") or [])
                     if c.get("field") == "blockedReason"]
        check("bk3 starting the blocked task clears the reason it was blocked for - "
              "a running task carrying a stale blockedReason reads as still "
              "waiting - and the task.start row says what it cleared: %r"
              % (_bk_start,),
              code == 0 and _bk_s.get("status") == "in_progress"
              and "blockedReason" not in _bk_s
              and [(c.get("from"), c.get("to")) for c in _bk_start]
              == [("waiting on the BE endpoint", None)])

        # ---- (nt) an append-only note ----------------------------------------------
        projnt, mpnt = mk("nt-note", pd_fixture())
        code1, txt1 = run(["note", "P2.4", "--text", "BE replied: endpoint ships Friday",
                           "--project-dir", projnt])
        code2, txt2 = run(["note", "P2.4", "--text", "Friday slipped to Monday",
                           "--project-dir", projnt])
        _nt_t = task_in(mpnt, "P2.4") or {}
        _nt_notes = _nt_t.get("notes") or []
        _nt_rows = [r for r in _journal_io.read_all(projnt)
                    if r.get("action") == "task.note"]
        check("nt1 `note` APPENDS {at, text} to a STARTED task - the task `scope "
              "--description` refuses - leaving the earlier note and the "
              "description as they were, one task.note row per call: %r"
              % (_nt_notes,),
              code1 == 0 and code2 == 0
              and [n.get("text") for n in _nt_notes]
              == ["BE replied: endpoint ships Friday", "Friday slipped to Monday"]
              and all(isinstance(n.get("at"), str) for n in _nt_notes)
              and _nt_t.get("description") == "" and len(_nt_rows) == 2)
        with open(mpnt, "rb") as _fh:
            _nt_before = _fh.read()
        _nt_empty = run(["note", "P2.4", "--text", "", "--project-dir", projnt])
        _nt_phase = run(["note", "P2", "--text", "x", "--project-dir", projnt])
        with open(mpnt, "rb") as _fh:
            _nt_after = _fh.read()
        check("nt2 an empty note and a phase id are refused, nothing written: %r"
              % ((_nt_empty[0], _nt_phase[0]),),
              _nt_empty[0] == 2 and _nt_phase[0] == 2 and _nt_after == _nt_before)

        # A note is caller free text: a machine path in it is refused at the
        # verb's door, before the lock, so neither the shard nor the journal
        # takes it. Neutral, and built so this file never spells one whole.
        _nt_home = "/" + "/".join(("Users", "someone", "notes", "probe.md"))
        _nt_rows_before = len([r for r in _journal_io.read_all(projnt)])
        _nt_mp = run(["note", "P2.4", "--text", "probe kept at %s" % (_nt_home,),
                      "--project-dir", projnt])
        _nt_mp_in = run_on_stdin(["note", "P2.4", "--text", "-",
                                  "--project-dir", projnt],
                                 "probe kept at %s\n" % (_nt_home,))
        with open(mpnt, "rb") as _fh:
            _nt_mp_after = _fh.read()
        _nt_rows_after = len([r for r in _journal_io.read_all(projnt)])
        check("nt3 a note carrying a home path - on argv or on stdin - exits "
              "non-zero, leaves the shard and the journal unchanged, and names "
              "the field and the shape without echoing the path: %r"
              % ((_nt_mp[0], _nt_mp_in[0], _nt_mp[1][:160]),),
              _nt_mp[0] != 0 and _nt_mp_in[0] != 0
              and _nt_mp_after == _nt_before
              and _nt_rows_after == _nt_rows_before
              and "--text" in _nt_mp[1] and "posix-home" in _nt_mp[1]
              and "--text" in _nt_mp_in[1]
              and "someone" not in _nt_mp[1] + _nt_mp_in[1])
        _nt_ok = run(["note", "P2.4", "--text",
                      "probe kept at docs/probe.md, see https://example.com/x",
                      "--project-dir", projnt])
        check("nt4 ALLOW twin: a note naming a repo-relative path and a URL is "
              "written - the mutation this catches is a door that refuses "
              "every path-shaped note: %r" % (_nt_ok,),
              _nt_ok[0] == 0
              and [n.get("text") for n in
                   ((task_in(mpnt, "P2.4") or {}).get("notes") or [])][-1:]
              == ["probe kept at docs/probe.md, see https://example.com/x"])

        # Every shape the commit-time detector flags is refused at the same
        # door, and a file URL into a home directory with them. Each sample is
        # built so this file never spells one whole.
        _nt_shapes = (
            ("session-slug", "/x/" + "-".join(("", "Users", "someone",
                                               "Desktop", "x")) + "/s"),
            ("escaped-path", "%2F".join(("q=", "Users", "someone", "x"))),
            ("tempdir-session", "/".join(("", "private", "tmp", "claude-501",
                                          "probe"))),
            ("unexpanded-home", "cwd=" + "~" + "/probe/notes.md"),
            ("posix-home", "file://" + "/".join(("", "Users", "someone",
                                                  "r.html"))),
        )
        with open(mpnt, "rb") as _fh:
            _nt5_before = _fh.read()
        _nt5 = [(name, run(["note", "P2.4", "--text", "probe at %s" % (raw,),
                            "--project-dir", projnt]))
                for name, raw in _nt_shapes]
        with open(mpnt, "rb") as _fh:
            _nt5_after = _fh.read()
        check("nt5 a note carrying any detector shape, or a file URL into a home "
              "directory, is refused at the door by that shape's name and the "
              "shard is unchanged: %r" % ([(n, r[0]) for n, r in _nt5],),
              all(r[0] == 2 and n in r[1] and "someone" not in r[1]
                  for n, r in _nt5)
              and _nt5_after == _nt5_before)
        _nt6_text = ("probe at https://example.com/Users/guide, "
                     "docs/users-guide.md and q=%2Fdocs%2Fx")
        _nt6 = run(["note", "P2.4", "--text", _nt6_text, "--project-dir", projnt])
        check("nt6 ALLOW twin: an https URL whose path merely holds the word, a "
              "kebab file name and an encoded repo path are written verbatim - "
              "the mutation this catches is a shape that refuses every URL: %r"
              % (_nt6,),
              _nt6[0] == 0
              and [n.get("text") for n in
                   ((task_in(mpnt, "P2.4") or {}).get("notes") or [])][-1:]
              == [_nt6_text])
        # Prose naming an option and a bare user name, each a dash-led word
        # at a token start with nothing after it, is not a session slug.
        _nt7_text = ("fix the go-home-now button; rename " + "-home-dir"
                     + " option, abc " + "-Users-bob")
        _nt7 = run(["note", "P2.4", "--text", _nt7_text, "--project-dir", projnt])
        check("nt7 ALLOW: a note naming a -home-<word> option and a "
              "-Users-<name> in prose is written verbatim - the mutation this "
              "catches is a slug shape that takes the user segment alone: %r"
              % (_nt7,),
              _nt7[0] == 0
              and [n.get("text") for n in
                   ((task_in(mpnt, "P2.4") or {}).get("notes") or [])][-1:]
              == [_nt7_text])
        _nt8_path = "/".join(("", "Users", "someone", "r.html"))
        with open(mpnt, "rb") as _fh:
            _nt8_before = _fh.read()
        _nt8 = run(["note", "P2.4", "--text",
                    "open file://localhost%s now" % (_nt8_path,),
                    "--project-dir", projnt])
        with open(mpnt, "rb") as _fh:
            _nt8_after = _fh.read()
        _nt8_web = "open https://localhost%s now" % (_nt8_path,)
        _nt8_ok = run(["note", "P2.4", "--text", _nt8_web,
                       "--project-dir", projnt])
        check("nt8 a file URL naming a host before a home directory is refused "
              "at the door as posix-home, nothing written, and its https twin "
              "with the same host and path is written verbatim: %r"
              % ((_nt8[0], _nt8[1][:160], _nt8_ok[0]),),
              _nt8[0] == 2 and "posix-home" in _nt8[1]
              and "someone" not in _nt8[1] and _nt8_after == _nt8_before
              and _nt8_ok[0] == 0
              and [n.get("text") for n in
                   ((task_in(mpnt, "P2.4") or {}).get("notes") or [])][-1:]
              == [_nt8_web])

        # ---- (md) a gate command and a test name pass the same door ----------------
        projgd, mpgd = mk("gd-gate-door", pd_fixture())
        _gd_home = "python3 " + "/".join(("", "Users", "someone", "repo", "tools",
                                          "t.py"))
        with open(mpgd, "rb") as _fh:
            _gd_before = _fh.read()
        _gd = [
            ("--gate", run(["retarget", "P3", "--gate", _gd_home,
                            "--project-dir", projgd])),
            ("--gate-set", run(["retarget", "P3", "--gate-set", "test", _gd_home,
                                "--project-dir", projgd])),
            ("--gate", run(["scope", "P2.3", "--gate", _gd_home,
                            "--project-dir", projgd])),
            ("--verified-by", run(["done", "P2.4", "--commit", "abc1234",
                                   "--verified-by", "t_ok," + _gd_home,
                                   "--project-dir", projgd] + _NOT_ASKED)),
        ]
        with open(mpgd, "rb") as _fh:
            _gd_after = _fh.read()
        check("md1 a home path in retarget's --gate and --gate-set, scope's "
              "--gate and done's --verified-by is refused before the lock, by "
              "flag and shape and without the path, and nothing is written: %r"
              % ([(f, r[0], r[1][:120]) for f, r in _gd],),
              all(r[0] == 2 and f in r[1] and "posix-home" in r[1]
                  and "someone" not in r[1] for f, r in _gd)
              and _gd_after == _gd_before)
        _gd_ok = run(["retarget", "P3", "--gate", "python3 tools/t.py",
                      "--project-dir", projgd])
        _gd_ok_set = run(["retarget", "P3", "--gate-set", "test",
                          "python3 tools/u.py", "--project-dir", projgd])
        _gd_phase = [p for p in (_mio.load_manifest(mpgd).get("phases") or [])
                     if p.get("id") == "P3"]
        check("md2 ALLOW twin: a plain repo-relative gate command is written by "
              "both spellings - the mutation this catches is a door that refuses "
              "every gate value: %r" % ((_gd_ok[0], _gd_ok_set[0],
                                         _gd_phase[:1]),),
              _gd_ok[0] == 0 and _gd_ok_set[0] == 0
              and [p.get("testGate") for p in _gd_phase]
              == [["test", "python3 tools/u.py"]])

        # ---- (rv) review findings: recorded by a verb, the tally derived ----------
        # Sign-off step 1 records the reviewer's findings, and until these verbs
        # that record was a hand edit of the phase shard - no lock, no journal row,
        # and a severity outside the vocabulary written with nothing to refuse it.
        # The fixture is a phase in sign-off: every task done, no verdict yet.
        def rv_fixture():
            fx = base_manifest()
            fx["phases"][1]["tasks"][1].update(
                status="done", commit="abcdef1234567890abcdef1234567890abcdef12")
            # A fix task that has NOT landed, in a phase of its own so P2's
            # sign-off is not held up by it.
            fx["phases"][2]["tasks"] = [{"id": "P3.1", "title": "fix, not landed",
                                         "status": "pending"}]
            return fx

        def rv_phase(mp, pid="P2"):
            return [p for p in _mio.load_manifest(mp)["phases"]
                    if p["id"] == pid][0]

        def rv_rows(proj, action):
            return [r for r in _journal_io.read_all(proj)
                    if r.get("action") == action]

        def rv_bytes(mp):
            with open(mp, "rb") as _fh:
                return _fh.read()

        _RV_ARGS = ["--file", "src/a.ts:12-30",
                    "--issue", "the guard reads the spelling, not the operation",
                    "--resolution", "decide from the resolved path"]
        projrv, mprv = mk("rv-findings", rv_fixture())
        _rv_before = rv_bytes(mprv)
        with open(os.devnull, "w") as _null, contextlib.redirect_stderr(_null):
            _rv_nosev = run(["finding", "P2"] + _RV_ARGS + ["--project-dir", projrv])
            _rv_badsev = run(["finding", "P2", "--severity", "medium"] + _RV_ARGS
                             + ["--project-dir", projrv])
            _rv_bare = run(["finding", "P2", "--severity", "high",
                            "--project-dir", projrv])
        check("rv1 RED-FIRST: a finding with no --severity is refused exit 2 naming "
              "the missing field, BEFORE any write - the manifest is byte "
              "identical and no review.finding row was written: %r"
              % (_rv_nosev[1][:200],),
              _rv_nosev[0] == 2 and "--severity" in _rv_nosev[1]
              and rv_bytes(mprv) == _rv_before
              and rv_rows(projrv, "review.finding") == [])
        check("rv2 RED-FIRST: a severity outside the vocabulary is refused naming "
              "the vocabulary the validator grades against, nothing written: %r"
              % (_rv_badsev[1][:200],),
              _rv_badsev[0] == 2 and "'medium'" in _rv_badsev[1]
              and "low, med, high" in _rv_badsev[1]
              and rv_bytes(mprv) == _rv_before)
        check("rv2b ...and a finding missing several fields names EVERY one of them "
              "in one refusal - one round trip, not one per field: %r"
              % (_rv_bare[1][:200],),
              _rv_bare[0] == 2 and "--file" in _rv_bare[1]
              and "--issue" in _rv_bare[1] and "--resolution" in _rv_bare[1]
              and rv_bytes(mprv) == _rv_before)
        _rv_one = run(["finding", "P2", "--severity", "high"] + _RV_ARGS
                      + ["--project-dir", projrv])
        _rv_two = run(["finding", "P2", "--severity", "med", "--file", "src/b.ts",
                       "--issue", "the retry arm is unbounded",
                       "--resolution", "cap it", "--project-dir", projrv])
        _rv_ph = rv_phase(mprv)
        _rv_f = (_rv_ph.get("review") or {}).get("findings") or []
        _rv_frows = rv_rows(projrv, "review.finding")
        check("rv3 ALLOW: a well-formed finding is APPENDED in the schema's shape "
              "with an allocated id, in FINDING_FIELDS order, and each call writes "
              "one review.finding row naming the phase: %r"
              % ((_rv_one[0], _rv_two[0], _rv_f),),
              _rv_one[0] == 0 and _rv_two[0] == 0
              and [list(f.keys()) for f in _rv_f]
              == [list(_phases.FINDING_FIELDS)] * 2
              and [f["id"] for f in _rv_f] == ["P2-R1", "P2-R2"]
              and _rv_f[0]["severity"] == "high"
              and _rv_f[0]["file"] == "src/a.ts:12-30"
              and _rv_f[0]["resolution"] == "decide from the resolved path"
              and len(_rv_frows) == 2
              and all((r.get("details") or {}).get("phaseId") == "P2"
                      for r in _rv_frows))
        _rv_w = _rules.validate(_mio.load_manifest(mprv))[1]
        check("rv3b ...and the written findings draw none of the validator's "
              "finding-shape warnings - the verb writes the shape the warning "
              "asks for: %r" % ([w for w in _rv_w if "review." in str(w)],),
              not [w for w in _rv_w if "review.findings" in str(w)])
        check("rv4 the TALLY is derived from review.findings on every write: two "
              "findings, one high and one med, none fixed: %r"
              % (_rv_ph.get("review", {}).get("outcome"),),
              (_rv_ph.get("review") or {}).get("outcome")
              == "[findings: 2 - 1 high, 1 med, 0 low; 0 with a recorded fix commit]")
        _RV_SHA = "0123456789abcdef0123456789abcdef01234567"
        _rv_res = run(["resolve-finding", "P2-R1", "--fix-task", "P2.1",
                       "--commit", _RV_SHA, "--project-dir", projrv])
        _rv_ph = rv_phase(mprv)
        _rv_r1 = ((_rv_ph.get("review") or {}).get("findings") or [{}])[0]
        _rv_rrows = rv_rows(projrv, "review.resolve")
        check("rv5 RED-FIRST: `resolve-finding` records the fix task and commit on "
              "the finding, keeps what the reviewer asked for in the resolution "
              "text, and writes one review.resolve row: %r" % ((_rv_res, _rv_r1),),
              _rv_res[0] == 0 and _rv_r1.get("fixTask") == "P2.1"
              and _rv_r1.get("commit") == _RV_SHA
              and _rv_r1.get("resolution")
              == "fixed in P2.1 (%s): decide from the resolved path" % (_RV_SHA[:12],)
              and len(_rv_rrows) == 1
              and (_rv_rrows[0].get("details") or {}).get("taskId") == "P2.1"
              and (_rv_rrows[0].get("details") or {}).get("commit") == _RV_SHA)
        check("rv5b ...and the tally counts it as fixed, derived again: %r"
              % ((_rv_ph.get("review") or {}).get("outcome"),),
              (_rv_ph.get("review") or {}).get("outcome")
              == "[findings: 2 - 1 high, 1 med, 0 low; 1 with a recorded fix commit]")
        _rv_own = run(["resolve-finding", "P2-R2", "--fix-task", "P2.3",
                       "--json", "--project-dir", projrv])
        try:
            _rv_own_j = json.loads(_rv_own[1])
        except ValueError:
            _rv_own_j = {}
        _rv_r2 = ((rv_phase(mprv).get("review") or {}).get("findings") or [{}, {}])[1]
        check("rv5c with no --commit the fix task's OWN recorded commit is the one "
              "written - the SHA the close already fixed, not a second typing of "
              "it - and --json says so: %r" % (_rv_own_j,),
              _rv_own[0] == 0 and _rv_own_j.get("ok") is True
              and _rv_r2.get("commit") == "abcdef1234567890abcdef1234567890abcdef12")
        _rv_before2 = rv_bytes(mprv)
        _rv_ref = [run(argv + ["--project-dir", projrv])[0] for argv in (
            ["resolve-finding", "P2-R9", "--fix-task", "P2.3", "--commit", _RV_SHA],
            ["resolve-finding", "P2-R1", "--fix-task", "P9.9", "--commit", _RV_SHA],
            ["resolve-finding", "P2-R1", "--fix-task", "P2", "--commit", _RV_SHA],
            ["resolve-finding", "P2-R1", "--fix-task", "P2.1"],
            ["resolve-finding", "P2-R1", "--fix-task", "P2.3", "--commit", "HEAD"],
            ["resolve-finding", "P2-R1", "--fix-task", "P2.3",
             "--commit", "fedcba9876543210fedcba9876543210fedcba98"],
            ["resolve-finding", "P2-R1", "--commit", _RV_SHA])]
        check("rv6 a finding no phase holds, a fix task the plan does not hold, a "
              "PHASE id as the fix task, a fix that has not landed (no --commit and "
              "none recorded), a ref name for a SHA, a commit contradicting the one "
              "the task recorded, and no --fix-task are each refused exit 2 with "
              "nothing written: %r" % (_rv_ref,),
              _rv_ref == [2] * 7 and rv_bytes(mprv) == _rv_before2)

        _rv_before2b = rv_bytes(mprv)
        _rv_pend = run(["resolve-finding", "P2-R1", "--fix-task", "P3.1",
                        "--commit", _RV_SHA, "--project-dir", projrv])
        check("rv6b RED-FIRST: a fix task that has not landed is refused even with "
              "--commit - the SHA a caller types for a pending task is a claim "
              "about work nobody has closed: %r" % (_rv_pend,),
              _rv_pend[0] == 2 and "P3.1" in _rv_pend[1]
              and "pending" in _rv_pend[1] and rv_bytes(mprv) == _rv_before2b)

        # A CORRECTION IS TEXT ONLY. The verdict and its phase.verdict row are
        # the reviewer's call recorded once; a typo in the outcome must not cost
        # a re-sign-off, and fixing it must not be a way to re-decide anything.
        _rv_sign = run(["signoff", "P2", "--verdict", "passed",
                        "--summary", "Search sanitized end to end.",
                        "--review-outcome", "matches",
                        "--no-evidence-reason", "fixture: no gate is run here",
                        "--project-dir", projrv])
        _rv_ph = rv_phase(mprv)
        check("rv7 signoff's --review-outcome carries the DERIVED tally too - every "
              "writer of review.outcome derives it, or the verb that writes it last "
              "decides whether it is true: %r"
              % ((_rv_sign[0], (_rv_ph.get("review") or {}).get("outcome")),),
              _rv_sign[0] == 0
              and (_rv_ph.get("review") or {}).get("outcome")
              == "matches [findings: 2 - 1 high, 1 med, 0 low; 2 with a recorded fix commit]")
        _rv_vrows = rv_rows(projrv, "phase.verdict")
        _rv_status = (_rv_ph.get("review") or {}).get("status")
        _rv_cor = run(["correct", "P2",
                       "--review-outcome", "matches after two fixes",
                       "--summary", "Search sanitized end to end, both paths.",
                       "--project-dir", projrv])
        _rv_ph2 = rv_phase(mprv)
        _rv_crows = rv_rows(projrv, "review.correct")
        check("rv8 RED-FIRST: `correct` rewrites the outcome and the summary as "
              "TEXT, with one review.correct row of its own: %r"
              % ((_rv_cor, (_rv_ph2.get("review") or {}).get("outcome"),
                  _rv_ph2.get("summary")),),
              _rv_cor[0] == 0
              and (_rv_ph2.get("review") or {}).get("outcome")
              == "matches after two fixes [findings: 2 - 1 high, 1 med, 0 low; "
                 "2 with a recorded fix commit]"
              and _rv_ph2.get("summary") == "Search sanitized end to end, both paths."
              and len(_rv_crows) == 1)
        check("rv8b ...and the VERDICT and ITS ROW are untouched: review.status is "
              "what signoff wrote, the phase.verdict rows are the same rows, no new "
              "one - a correction never re-decides the verdict: %r"
              % ((_rv_status, (_rv_ph2.get("review") or {}).get("status"),
                  len(_rv_vrows)),),
              _rv_status == "passed"
              and (_rv_ph2.get("review") or {}).get("status") == "passed"
              and len(_rv_vrows) == 1
              and rv_rows(projrv, "phase.verdict") == _rv_vrows)
        # THE OVER-FIRE DIRECTION: a tally typed into the text is prose, never
        # the count. A version that read the numbers back out of the outcome
        # would keep the nine; the list holds two.
        _rv_typed = run(["correct", "P2", "--review-outcome",
                         "matches [findings: 9 - 9 high, 0 med, 0 low; "
                         "9 with a recorded fix commit]", "--project-dir", projrv])
        _rv_out = (rv_phase(mprv).get("review") or {}).get("outcome") or ""
        check("rv9 a tally TYPED into the outcome is replaced by the one the "
              "findings derive, and there is exactly one: %r" % (_rv_out,),
              _rv_typed[0] == 0 and _rv_out.count("[findings:") == 1
              and _rv_out == "matches [findings: 2 - 1 high, 1 med, 0 low; "
                             "2 with a recorded fix commit]")
        _rv_before3 = rv_bytes(mprv)
        with open(os.devnull, "w") as _null, contextlib.redirect_stderr(_null):
            _rv_cref = [run(argv + ["--project-dir", projrv])[0] for argv in (
                ["correct", "P2", "--verdict", "skipped", "--summary", "s"],
                ["correct", "P2"],
                ["correct", "P2", "--summary", ""],
                ["correct", "P2.1", "--summary", "s"])]
        check("rv10 `correct` refuses --verdict (it does not read it), a call with "
              "nothing to correct, an empty text and a task id - nothing written: %r"
              % (_rv_cref,),
              _rv_cref == [2] * 4 and rv_bytes(mprv) == _rv_before3)
        projrv2, mprv2 = mk("rv-unsigned", rv_fixture())
        _rv_pre = run(["correct", "P2", "--summary", "s", "--project-dir", projrv2])
        check("rv10b ...and a phase with no verdict yet: there is no record to "
              "correct, and the one that writes it is signoff: %r" % (_rv_pre,),
              _rv_pre[0] == 2 and "signoff" in _rv_pre[1])
        _rv_leg = rv_fixture()
        _rv_leg["phases"][1]["review"] = {"status": "pending",
                                          "findings": ["a legacy free-text note"]}
        projrv3, mprv3 = mk("rv-legacy", _rv_leg)
        _rv_l = run(["finding", "P2", "--severity", "low", "--file", "README.md",
                     "--issue", "typo", "--resolution", "fix it", "--json",
                     "--project-dir", projrv3])
        try:
            _rv_lj = json.loads(_rv_l[1])
        except ValueError:
            _rv_lj = {}
        _rv_lr = rv_phase(mprv3).get("review") or {}
        _rv_lw = _rules.validate(_mio.load_manifest(mprv3))[1]
        check("rv11 a legacy string finding stays where it is, the new one is "
              "numbered past it, and the tally names the entry outside the "
              "vocabulary rather than dropping it; --json carries the finding: %r"
              % ((_rv_lj.get("finding"), _rv_lr.get("outcome")),),
              _rv_l[0] == 0 and (_rv_lj.get("finding") or {}).get("id") == "P2-R1"
              and _rv_lr.get("findings", [None])[0] == "a legacy free-text note"
              # ...and the validator DOES warn on this plan, which is what keeps
              # rv3b's silence from being the silence of a warning that never fires.
              and [w for w in _rv_lw if "review.findings" in str(w)] != []
              and _rv_lr.get("outcome")
              == "[findings: 2 - 0 high, 0 med, 1 low, 1 outside low|med|high; "
                 "0 with a recorded fix commit]")

        # ---- the batch form, the landed phase, reopen, and the journal's view ------
        # A batch is ONE lock and ONE write for every finding a review returned,
        # which is what parallel single-finding calls could never be.
        projrb, mprb = mk("rv-batch", rv_fixture())
        _rb_file = os.path.join(tmp, "rv-batch-findings.json")
        with open(_rb_file, "w", encoding="utf-8") as _fh:
            json.dump([{"id": 1, "severity": "high", "file": "src/a.ts:3",
                        "issue": "reads `argv` as prose", "resolution": "read the path"},
                       {"severity": "low", "file": "src/b.ts",
                        "issue": "i2", "resolution": "r2"},
                       {"severity": "low", "file": "README.md",
                        "issue": "i3", "resolution": "r3"}], _fh)
        _rb = run(["finding", "P2", "--findings-file", _rb_file,
                   "--project-dir", projrb])
        _rb_f = (rv_phase(mprb).get("review") or {}).get("findings") or []
        _rb_rows = rv_rows(projrb, "review.finding")
        check("rv12 `finding --findings-file` records EVERY finding a review "
              "returned in one write, each with an allocated id (the reviewer's "
              "own number is not the plan's id), one review.finding row each: %r"
              % ((_rb[0], [f.get("id") for f in _rb_f], len(_rb_rows)),),
              _rb[0] == 0 and [f.get("id") for f in _rb_f] == ["P2-R1", "P2-R2", "P2-R3"]
              and _rb_f[0].get("issue") == "reads `argv` as prose"
              and len(_rb_rows) == 3
              and (rv_phase(mprb).get("review") or {}).get("outcome")
              == "[findings: 3 - 1 high, 0 med, 2 low; 0 with a recorded fix commit]")
        _rb_before = rv_bytes(mprb)
        _rb_bad = os.path.join(tmp, "rv-batch-bad.json")
        with open(_rb_bad, "w", encoding="utf-8") as _fh:
            json.dump([{"severity": "low", "file": "a", "issue": "i", "resolution": "r"},
                       {"severity": "medium", "file": "b", "issue": "i",
                        "resolution": "r"}], _fh)
        _rb_badr = run(["finding", "P2", "--findings-file", _rb_bad,
                        "--project-dir", projrb])
        _rb_mix = run(["finding", "P2", "--findings-file", _rb_file,
                       "--severity", "low", "--project-dir", projrb])
        with open(_rb_bad, "w", encoding="utf-8") as _fh:
            _fh.write("{not json")
        _rb_torn = run(["finding", "P2", "--findings-file", _rb_bad,
                        "--project-dir", projrb])
        check("rv12b ...and a batch with ONE bad entry is refused WHOLE, naming the "
              "entry; a batch beside the per-field flags and a file that is not "
              "a JSON list are refused too - nothing written: %r"
              % ((_rb_badr, _rb_mix[0], _rb_torn[0]),),
              _rb_badr[0] == 2 and "entry 2" in _rb_badr[1]
              and "'medium'" in _rb_badr[1]
              and _rb_mix[0] == 2 and _rb_torn[0] == 2
              and rv_bytes(mprb) == _rb_before)

        projrs, mprs = mk("rv-batch-stdin", rv_fixture())
        _rs = run_on_stdin(["finding", "P2", "--findings-file", "-",
                            "--project-dir", projrs],
                           json.dumps([{"severity": "med", "file": "a",
                                        "issue": "quotes `code` and 'text'",
                                        "resolution": "r"}]))
        _rs_f = (rv_phase(mprs).get("review") or {}).get("findings") or []
        check("rv12c ...and `--findings-file -` reads the batch off stdin verbatim, "
              "backticks and quotes intact - the route step 1 prescribes: %r"
              % ((_rs[0], _rs_f),),
              _rs[0] == 0 and [f.get("issue") for f in _rs_f]
              == ["quotes `code` and 'text'"])

        # PARALLEL CALLS FROM ONE SESSION. Several processes carrying one session
        # id and one CLAUDE_PID is what several Bash calls in one message are; the
        # lock let each of them back in as "already yours", so every one wrote
        # over the others and reported success.
        projpar, mppar = mk("rv-parallel", rv_fixture(), git=True)
        _par_env = dict(os.environ, CLAUDE_CODE_SESSION_ID="s-one-session",
                        CLAUDE_PID=str(os.getpid()))
        _par_env.pop("AUDIT_LOCK_TOKENS", None)
        _par_script = os.path.join(_output.SCRIPTS_DIR, "manifest", "audit-task.py")
        _par_procs = [subprocess.Popen(
            [sys.executable, _par_script, "finding", "P2", "--severity", "low",
             "--file", "src/p%d.ts" % n, "--issue", "issue %d" % n,
             "--resolution", "fix %d" % n, "--project-dir", projpar],
            env=_par_env, cwd=projpar, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT) for n in range(4)]
        _par_out = [(pr.wait(), pr.stdout.read().decode("utf-8", "replace"))
                    for pr in _par_procs]
        for pr in _par_procs:
            pr.stdout.close()
        _par_f = (rv_phase(mppar).get("review") or {}).get("findings") or []
        check("rv13 RED-FIRST: four `finding` processes of ONE session run at once "
              "and EVERY finding lands, under four distinct ids - the lock "
              "serialises another process of the same session instead of letting "
              "it back in: %r"
              % (([c for c, _t in _par_out], sorted(f.get("file") for f in _par_f)),),
              [c for c, _t in _par_out] == [0] * 4
              and sorted(f.get("file") for f in _par_f)
              == ["src/p%d.ts" % n for n in range(4)]
              and sorted(f.get("id") for f in _par_f)
              == ["P2-R%d" % n for n in range(1, 5)])

        # A LANDED PHASE IS A CLOSED RECORD; a signed-off one still in flight
        # takes the finding and the row says it arrived after the verdict.
        _rl = rv_fixture()
        _rl["phases"][1].update(review={"status": "passed"}, summary="s",
                                branch="audit/p2", mergedAt="2026-09-01T00:00:00Z")
        projrl, mprl = mk("rv-landed", _rl)
        _rl_before = rv_bytes(mprl)
        _rl_code = run(["finding", "P2", "--severity", "low", "--file", "a",
                        "--issue", "i", "--resolution", "r", "--project-dir", projrl])
        check("rv14 RED-FIRST: `finding` refuses a phase that has LANDED (mergedAt "
              "set), naming when and the verb that re-opens review: %r" % (_rl_code,),
              _rl_code[0] == 2 and "2026-09-01T00:00:00Z" in _rl_code[1]
              and "/audit:review" in _rl_code[1] and rv_bytes(mprl) == _rl_before)
        _ru = rv_fixture()
        _ru["phases"][1].update(review={"status": "passed"}, summary="s",
                                branch="audit/p2")
        projru, mpru = mk("rv-unlanded", _ru)
        _ru_code = run(["finding", "P2", "--severity", "low", "--file", "a",
                        "--issue", "i", "--resolution", "r", "--project-dir", projru])
        _ru_rows = rv_rows(projru, "review.finding")
        check("rv14b ALLOW: a signed-off phase that has NOT landed still takes a "
              "finding, and both the output and the row say the verdict was "
              "already on record: %r" % ((_ru_code, [r.get("summary") for r in _ru_rows]),),
              _ru_code[0] == 0 and "verdict passed" in _ru_code[1]
              and len(_ru_rows) == 1
              and "verdict passed" in (_ru_rows[0].get("summary") or ""))

        # REOPEN takes the fix back, so the finding stops saying it was fixed.
        projro, mpro = mk("rv-reopen", rv_fixture())
        run(["finding", "P2", "--severity", "med", "--file", "a", "--issue", "i",
             "--resolution", "decide", "--project-dir", projro])
        run(["resolve-finding", "P2-R1", "--fix-task", "P2.3",
             "--project-dir", projro])
        _ro_code = run(["reopen", "P2.3", "--reason", "the fix was wrong",
                        "--project-dir", projro])
        _ro_ph = rv_phase(mpro)
        _ro_f = ((_ro_ph.get("review") or {}).get("findings") or [{}])[0]
        check("rv15 RED-FIRST: `reopen` of a fix task clears the commit from every "
              "finding that recorded it, restores the reviewer's resolution, and "
              "the tally stops counting it: %r"
              % ((_ro_code[0], _ro_f, (_ro_ph.get("review") or {}).get("outcome")),),
              _ro_code[0] == 0 and not _ro_f.get("commit")
              and _ro_f.get("resolution") == "decide"
              and (_ro_ph.get("review") or {}).get("outcome")
              == "[findings: 1 - 0 high, 1 med, 0 low; 0 with a recorded fix commit]")

        # THE JOURNAL'S VIEW OF A LONG OUTCOME keeps its END, where the tally is.
        projrj, mprj = mk("rv-journal", rv_fixture())
        run(["signoff", "P2", "--verdict", "skipped", "--summary", "s",
             "--review-outcome", "x" * 300, "--project-dir", projrj])
        run(["finding", "P2", "--severity", "high", "--file", "a", "--issue", "i",
             "--resolution", "r", "--project-dir", projrj])
        _rj_ch = [c for r in rv_rows(projrj, "review.finding")
                  for c in ((r.get("details") or {}).get("changes") or [])
                  if c.get("field") == "review.outcome"]
        check("rv16 RED-FIRST: a long outcome is shortened from the MIDDLE in the "
              "journal row, so the tally at its end is what the row shows "
              "changing: %r" % (_rj_ch,),
              len(_rj_ch) == 1
              and str(_rj_ch[0].get("to")).endswith(
                  "[findings: 1 - 1 high, 0 med, 0 low; 0 with a recorded fix commit]")
              and "truncated" not in str(_rj_ch[0].get("to")))

        # A FIX RECORDED BY HAND is prose; the clause counts only what it names.
        _rh = rv_fixture()
        _rh["phases"][1]["review"] = {"status": "pending", "findings": [
            {"id": "P2-R1", "severity": "med", "file": "a", "issue": "i",
             "resolution": "fixed in P2.3 (abcdef123456)"}]}
        projrh, mprh = mk("rv-hand", _rh)
        run(["finding", "P2", "--severity", "low", "--file", "b", "--issue", "i",
             "--resolution", "r", "--project-dir", projrh])
        _rh_out = (rv_phase(mprh).get("review") or {}).get("outcome") or ""
        check("rv17 the clause says exactly what it counts - a fix recorded by hand "
              "in the resolution text is not one the fields recorded, so it reads "
              "`0 with a recorded fix commit` and nothing calls it unfixed: %r"
              % (_rh_out,),
              _rh_out == "[findings: 2 - 0 high, 1 med, 1 low; "
                         "0 with a recorded fix commit]")

        # ---- (mv) move: the hand procedure, as a verb ------------------------------
        def mv_fixture():
            fx = base_manifest()
            fx["phases"][1]["tasks"][1].update(files=["src/b.ts"], bugId="BUG-1")
            fx["phases"][1]["tasks"].append(
                {"id": "P2.4", "title": "waits on b", "status": "pending",
                 "dependsOn": ["P2.3"]})
            fx["phases"][2]["tasks"] = [
                {"id": "P3.1", "title": "already there", "status": "pending",
                 "blockedBy": ["P2.3"]}]
            fx["fileIndex"]["src/b.ts"] = ["P2.3"]
            fx["bugs"] = [{"id": "BUG-1", "title": "b", "status": "open",
                           "severity": "low", "taskId": "P2.3"}]
            fx["proposals"] = [{"id": "PROP-1", "status": "proposed",
                                "payload": {"phase": {
                                    "id": "P4", "title": "parked", "status": "pending",
                                    "blockedBy": ["P2.3"],
                                    "tasks": [{"id": "P4.1", "title": "x",
                                               "status": "pending",
                                               "blockedBy": ["P2.3"]}]}}}]
            return fx

        for _mv_layout in ("single", "sharded"):
            projmv, mpmv = mk("mv-%s" % _mv_layout, mv_fixture(),
                              sharded=_mv_layout == "sharded")
            _mv_next = (run(["next-id", "task", "--phase", "P3", "--json",
                             "--project-dir", projmv])[1])
            try:
                _mv_next = json.loads(_mv_next).get("id")
            except ValueError:
                _mv_next = None
            code, txt = run(["move", "P2.3", "--to", "P3", "--project-dir", projmv])
            _mv_m = _mio.load_manifest(mpmv)
            _mv_by = _mio.tasks_by_id(_mv_m)
            _mv_new = _mv_by.get(_mv_next) or {}
            _mv_prop = _mv_m["proposals"][0]["payload"]["phase"]
            _mv_rows = [r for r in _journal_io.read_all(projmv)
                        if r.get("action") == "task.move"]
            check("mv1-%s `move` renumbers the task with the id `next-id task` "
                  "names, records movedFrom, and rewrites every reference - a "
                  "sibling's dependsOn, the target phase's blockedBy, fileIndex, "
                  "the bug's taskId and the parked proposal's phase and task - "
                  "then validates, with one task.move row: %s" % (_mv_layout, txt),
                  code == 0 and _mv_next == "P3.2" and "P2.3" not in _mv_by
                  and _mv_new.get("movedFrom", {}).get("id") == "P2.3"
                  and _mv_new.get("movedFrom", {}).get("phase") == "P2"
                  and _mv_by["P2.4"].get("dependsOn") == ["P3.2"]
                  and _mv_by["P3.1"].get("blockedBy") == ["P3.2"]
                  and _mv_m["fileIndex"].get("src/b.ts") == ["P3.2"]
                  and _mv_m["bugs"][0].get("taskId") == "P3.2"
                  and _mv_prop.get("blockedBy") == ["P3.2"]
                  and _mv_prop["tasks"][0].get("blockedBy") == ["P3.2"]
                  and [p["id"] for p in _mv_m["phases"]
                       if any(t["id"] == "P3.2" for t in p.get("tasks") or [])]
                  == ["P3"]
                  and _panel_write._cores()[0].validate(_mv_m)[0] == []
                  and len(_mv_rows) == 1
                  and (_mv_rows[0].get("details") or {}).get("fromId") == "P2.3"
                  and (_mv_rows[0].get("details") or {}).get("toId") == "P3.2")
        mvref = mv_fixture()
        mvref["phases"][1]["tasks"].append(
            {"id": "P2.5", "title": "running", "status": "in_progress",
             "attempts": 1})
        projmr, mpmr = mk("mv-refusals", mvref)
        with open(mpmr, "rb") as _fh:
            _mv_before = _fh.read()
        _mv_codes = [run(argv + ["--project-dir", projmr])[0] for argv in (
            ["move", "P2.3"],                       # no --to
            ["move", "P2.3", "--to", "P2"],         # same phase
            ["move", "P2.1", "--to", "P3"],         # done
            ["move", "P2.5", "--to", "P3"],         # in_progress
            ["move", "P2.3", "--to", "P1"],         # target done
            ["move", "P2.3", "--to", "P9"],         # no such phase
            ["move", "P2.9", "--to", "P3"])]        # no such task
        with open(mpmr, "rb") as _fh:
            _mv_after = _fh.read()
        check("mv2 every refusal the documented procedure lists fires before a "
              "write - no --to, the same phase, a done task, a running task, a done "
              "target, an unknown phase, an unknown task: %r" % (_mv_codes,),
              _mv_codes == [2] * 7 and _mv_after == _mv_before)

        # ---- (dr) `add --dry-run`: built and validated, nothing written -------
        projdr, mpdr = mk("dr-dry", base_manifest())
        with open(mpdr, "rb") as _fh:
            _dr_before = _fh.read()
        code, txt = run(["add", "Would be", "--phase", "P2", "--files", "src/a.ts",
                         "--dry-run", "--project-dir", projdr])
        with open(mpdr, "rb") as _fh:
            _dr_after = _fh.read()
        _dr_rows = [r for r in _journal_io.read_all(projdr)
                    if r.get("action") == "task.add"]
        check("dr1 `add --dry-run` names the id and the task it WOULD write, and "
              "writes nothing - the manifest byte identical and no task.add row: %s"
              % (txt,),
              code == 0 and "DRY RUN" in txt and "P2.4" in txt
              and _dr_after == _dr_before and _dr_rows == [])
        code, txt = run(["add", "Bad dep", "--phase", "P2", "--depends-on", "P9.9",
                         "--dry-run", "--project-dir", projdr])
        with open(mpdr, "rb") as _fh:
            _dr_after2 = _fh.read()
        check("dr2 ...and it VALIDATES what it built: a dependency on nothing is the "
              "same FINDING the real add rolls back on, with nothing written: %s"
              % (txt,),
              code == M.E_INVALID and "FINDING" in txt and "P9.9" in txt
              and _dr_after2 == _dr_before)
        code, txt = run(["add", "Would be", "--phase", "P2", "--dry-run", "--json",
                         "--project-dir", projdr])
        try:
            _dr_js = json.loads(txt)
        except ValueError:
            _dr_js = {}
        check("dr3 ...and `--json` says it was a dry run, as data: %r"
              % (sorted(_dr_js),),
              code == 0 and _dr_js.get("dryRun") is True
              and _dr_js.get("id") == "P2.4" and _dr_js.get("written") == [])

        # ---- (jr) `--json` refusals are JSON -----------------------------------
        projjr, mpjr = mk("jr-refusals", base_manifest())
        _jr = {}
        for _jrwhat, _jrargv in (
                ("validator", ["add", "Bad", "--phase", "P2", "--depends-on", "P9.9"]),
                ("argv-gap", ["add", "Gap", "--phase", "P2", "--description",
                              " leading space"]),
                ("usage", ["add", "No phase", "--phase", "P9"])):
            _jrc, _jrt = run(_jrargv + ["--json", "--project-dir", projjr])
            try:
                _jrj = json.loads(_jrt)
            except ValueError:
                _jrj = None
            _jr[_jrwhat] = (_jrc, _jrj)
        check("jr1 every refusal under `--json` is ONE JSON object - {ok: false, "
              "refused, findings} - on the validator's refusal, the argv-gap "
              "refusal and a usage refusal alike, with the exit code unchanged: %r"
              % (dict((k, (v[0], sorted(v[1]) if isinstance(v[1], dict) else v[1]))
                      for k, v in _jr.items()),),
              all(isinstance(v[1], dict) and v[1].get("ok") is False
                  and isinstance(v[1].get("refused"), str) and v[1]["refused"]
                  and isinstance(v[1].get("findings"), list)
                  for v in _jr.values())
              and _jr["validator"][0] == M.E_INVALID
              and any("P9.9" in f for f in _jr["validator"][1]["findings"])
              and _jr["argv-gap"][0] == 2 and _jr["usage"][0] == 2)
        code, txt = run(["add", "Fine", "--phase", "P2", "--json",
                         "--project-dir", projjr])
        try:
            _jr_ok = json.loads(txt)
        except ValueError:
            _jr_ok = {}
        check("jr2 SECOND DIRECTION: a successful `--json` call is still the verb's "
              "own object, not wrapped: %r" % (sorted(_jr_ok)[:6],),
              code == 0 and _jr_ok.get("ok") is True and "refused" not in _jr_ok)

        # ---- (lf) list flags repeat, and say their separator ---------------------
        projlf, mplf = mk("lf-lists", base_manifest())
        code, txt = run(["add", "Repeated", "--phase", "P2",
                         "--depends-on", "P2.1", "--depends-on", "P2.3",
                         "--files", "src/a.ts", "--files", "src/b.ts,src/c.ts",
                         "--project-dir", projlf])
        _lf_t = task_in(mplf, "P2.4") or {}
        check("lf1 a list flag REPEATS and still splits on commas: two --depends-on "
              "and a mixed --files land as one list each, in order: %r"
              % ((_lf_t.get("dependsOn"), _lf_t.get("files")),),
              code == 0 and _lf_t.get("dependsOn") == ["P2.1", "P2.3"]
              and _lf_t.get("files") == ["src/a.ts", "src/b.ts", "src/c.ts"])
        _lf_help = dict((a.dest, a.help or "") for a in M.build_parser()._actions)
        _lf_miss = [d for d in ("files", "depends_on", "blocked_by", "verified_by")
                    if not ("comma" in _lf_help.get(d, "")
                            and "repeat" in _lf_help.get(d, "")
                            and re.search(r"--[a-z-]+ \S+,\S+", _lf_help.get(d, "")))]
        check("lf2 each list flag's --help names the separator, says it repeats and "
              "shows an example - the separator was guessed before: %r" % (_lf_miss,),
              _lf_miss == [])
        projlf2, mplf2 = mk("lf-verified", pd_fixture())
        code, txt = run(["done", "P2.4", "--commit", _PD_SHA,
                         "--verified-by", "t_one", "--verified-by", "t_two,t_three",
                         "--project-dir", projlf2] + _NOT_ASKED)
        check("lf3 ...and `done --verified-by` repeats the same way: %r"
              % ((task_in(mplf2, "P2.4") or {}).get("verifiedBy"),),
              code == 0 and (task_in(mplf2, "P2.4") or {}).get("verifiedBy")
              == ["t_one", "t_two", "t_three"])

        # ---- (dy) scope's DIRTY note means the index bytes changed ---------------
        def dy_manifest():
            fx = base_manifest()
            fx["phases"][1]["tasks"] += [
                {"id": "P2.4", "title": "owns b", "status": "pending",
                 "files": ["src/b.ts"],
                 "tests": {"mode": "gate-only", "add": [], "gate": ["test"]}},
                {"id": "P2.5", "title": "shares b", "status": "pending",
                 "files": ["src/b.ts"]}]
            fx["fileIndex"]["src/b.ts"] = ["P2.4", "P2.5"]
            return fx

        projdy, mpdy = mk("dy-dirty", dy_manifest(), sharded=True, git=True)
        git(projdy, "add", "-A")
        git(projdy, "commit", "-q", "-m", "base")
        with open(mpdy, "rb") as _fh:
            _dy_before = _fh.read()
        code, txt = run(["scope", "P2.4", "--gate-clear", "--json",
                         "--project-dir", projdy])
        with open(mpdy, "rb") as _fh:
            _dy_after = _fh.read()
        try:
            _dy_js = json.loads(txt)
        except ValueError:
            _dy_js = {}
        _dy_rel = _output.posix_rel(mpdy, projdy)
        check("dy1 a scope that moves no index row leaves the index BYTE IDENTICAL - "
              "the shared row P2.4 heads keeps its order - and carries no DIRTY note "
              "and no index in `written`: %r"
              % ((_dy_js.get("written"), _dy_js.get("indexDirtyNote")),),
              code == 0 and _dy_after == _dy_before
              and "indexDirtyNote" not in _dy_js
              and _dy_js.get("written") and _dy_rel not in _dy_js["written"])
        code, txt = run(["scope", "P2.4", "--files", "src/b.ts,src/a.ts",
                         "--project-dir", projdy])
        with open(mpdy, "rb") as _fh:
            _dy_after2 = _fh.read()
        _dy_idx = json.loads(_dy_after2.decode("utf-8")).get("fileIndex") or {}
        check("dy2 SECOND DIRECTION: a scope that claims a path writes the index and "
              "says it is DIRTY, and the shared row still reads in its old order: %r"
              % (_dy_idx,),
              code == 0 and _dy_after2 != _dy_before and "is now DIRTY" in txt
              and _dy_idx.get("src/b.ts") == ["P2.4", "P2.5"]
              and _dy_idx.get("src/a.ts") == ["P2.1", "P2.4"])

        # IDENTICAL BYTES ARE NOT A WRITE, asked of the writer itself: handed a
        # fileIndex it calls changed and is not, it leaves the index alone and
        # does not name it in `written` - which is what the DIRTY note reads.
        projdy3, mpdy3 = mk("dy-same-bytes", dy_manifest(), sharded=True)
        with open(mpdy3, "rb") as _fh:
            _dy3_before = _fh.read()
        _dy3_written = M._write_add(projdy3, mpdy3, _mio.read_json(mpdy3),
                                    _mio.load_manifest(mpdy3), "P2", True)
        with open(mpdy3, "rb") as _fh:
            _dy3_after = _fh.read()
        check("dy3 a write handed `fileIndex` as changed when it is not leaves the "
              "index byte identical and out of `written`: %r" % (_dy3_written,),
              _dy3_after == _dy3_before
              and _output.posix_rel(mpdy3, projdy3) not in _dy3_written)

        # ---- (cg) the colon that starts an identifier is not a hole ------------
        projcg, mpcg = mk("cg-colon", base_manifest())
        _cg_texts = ("params :id and :key are validated",
                     "the route takes :slug and :_token")
        _cg = [run(["add", "Colon %d" % i, "--phase", "P2", "--description", t,
                    "--project-dir", projcg])[0] for i, t in enumerate(_cg_texts)]
        _cg_stored = sorted(t.get("description") for t in
                            _mio.tasks_by_id(_mio.load_manifest(mpcg)).values()
                            if (t.get("title") or "").startswith("Colon"))
        check("cg1 a colon that STARTS an identifier (`:id`, `:slug`, `:_token`) "
              "is written verbatim - the shape this plan's own texts carry: %r"
              % (_cg_stored,),
              _cg == [0, 0] and _cg_stored == sorted(_cg_texts))
        code, txt = run(["add", "Spaced colon", "--phase", "P2", "--description",
                         "the value : is gone", "--project-dir", projcg])
        check("cg2 SECOND DIRECTION: a colon with whitespace on BOTH sides is still "
              "the hole it was, and refused: %s" % (txt[:120],),
              code == 2 and "hugs the word" in txt)

        # ---- (gs) the refusal names substitution, and is short ------------------
        projgs, _mpgs = mk("gs-short", base_manifest())
        code, txt = run(["add", "Lead", "--phase", "P2", "--description",
                         " now returns 204", "--project-dir", projgs])
        _gs_lines = txt.splitlines()
        _gs_route = [i for i, ln in enumerate(_gs_lines) if "<<'BRIEF'" in ln]
        check("gz1 a leading or doubled space is named as LIKELY backtick "
              "substitution, pointing at the shell's own stderr, in a refusal cut to "
              "the route and the marked span: %d line(s): %r"
              % (len(_gs_lines), txt),
              code == 2 and "COMMAND SUBSTITUTION" in txt
              and "command not found" in txt and len(_gs_lines) <= 8
              and _gs_route and _gs_route[0] <= 2 and "Seen at:" in txt)
        code, txt = run(["add", "Comma", "--phase", "P2", "--description",
                         "gating on , returning it", "--project-dir", projgs])
        check("gz2 SECOND DIRECTION: a shape that is just as likely code quoted into "
              "prose does not claim substitution as likely - it says the check "
              "cannot tell them apart: %r" % (txt,),
              code == 2 and "likely" not in txt.lower()
              and "cannot tell" in txt and len(txt.splitlines()) <= 8)

        # ---- (ew) phase entry warns about an empty gate or a missing outcome ---
        ewfx = base_manifest()
        ewfx["phases"][2]["tasks"] = [{"id": "P3.1", "title": "first",
                                       "status": "pending"}]
        projew, _mpew = mk("ew-entry", ewfx)
        code, txt = run(["start", "P3.1", "--project-dir", projew])
        _ew = [ln for ln in txt.splitlines() if "phase entry" in ln.lower()
               and "WARNING" in ln]
        check("ew1 the start that ENTERS a phase with an empty testGate and no "
              "desiredOutcome warns about each - and still exits 0, because an "
              "empty gate is a designed state: %r" % (_ew,),
              code == 0 and len(_ew) == 2
              and any("testGate" in ln for ln in _ew)
              and any("desiredOutcome" in ln for ln in _ew))
        ewok = base_manifest()
        ewok["phases"][2].update(testGate=["test"], desiredOutcome="it ships")
        ewok["phases"][2]["tasks"] = [{"id": "P3.1", "title": "first",
                                       "status": "pending"}]
        projew2, _mpew2 = mk("ew-entry-ok", ewok)
        code, txt = run(["start", "P3.1", "--project-dir", projew2])
        code2, txt2 = run(["start", "P2.3", "--project-dir", projew])
        check("ew2 SECOND DIRECTION: entering a phase that has both prints no such "
              "warning, and neither does a start inside a phase already running: %r"
              % ((txt[-120:], txt2[-120:]),),
              code == 0 and "phase entry" not in txt.lower()
              and code2 == 0 and "phase entry" not in txt2.lower())

        # ---- (gd) a gate token that is a directory ------------------------------
        projgd, _mpgd = mk("gd-dir", base_manifest())
        os.makedirs(os.path.join(projgd, "src"), exist_ok=True)
        code, txt = run(["add", "Dir gate", "--phase", "P2", "--gate", "src",
                         "--project-dir", projgd])
        _gd = [ln for ln in txt.splitlines() if "directory" in ln and "src" in ln]
        check("gd1 a gate entry that is one token, no buildCommands key, and a "
              "DIRECTORY in the project tree is warned about - it names no command "
              "- and the add still happens: %r" % (_gd,),
              code == 0 and len(_gd) == 1 and _gd[0].startswith("WARNING"))
        code, txt = run(["scope", "P2.3", "--gate", "src", "--tests-mode",
                         "gate-only", "--project-dir", projgd])
        check("gd2 ...and `scope --gate` warns the same way: %s" % (txt[-200:],),
              code == 0 and any("directory" in ln and "src" in ln
                                and ln.startswith("WARNING")
                                for ln in txt.splitlines()))
        # A DIRECTORY NAMED LIKE THE KEY, so the key check is what keeps this quiet
        # rather than the absence of a directory.
        os.makedirs(os.path.join(projgd, "test"), exist_ok=True)
        code, txt = run(["add", "Key gate", "--phase", "P2", "--gate", "test",
                         "--gate", "pytest src", "--project-dir", projgd])
        check("gd3 SECOND DIRECTION: a buildCommands key and a command that merely "
              "NAMES a directory draw no such warning: %s" % (txt[-200:],),
              code == 0 and not [ln for ln in txt.splitlines()
                                 if "directory" in ln and ln.startswith("WARNING")])

        # ---- (rv) review findings: a bug's derived state must survive a
        # close that changed nothing -------------------------------------------
        # R1: a no-change close on a bug's FIX TASK would derive the bug `fixed`
        # with no fixedIn - a bug marked fixed with no fix commit, which the
        # release guard then stops counting as open.
        rvbug = pd_fixture()
        rvbug["phases"][1]["tasks"][-1]["bugId"] = "BUG-1"
        rvbug["bugs"] = [{"id": "BUG-1", "title": "b", "status": "in_progress",
                          "severity": "low", "taskId": "P2.4"}]
        projrv1, mprv1 = mk("rv-nochange-bug", rvbug)
        with open(mprv1, "rb") as _fh:
            _rv1_before = _fh.read()
        code, txt = run(["done", "P2.4", "--no-change", "--reason", "not a bug",
                         "--project-dir", projrv1])
        with open(mprv1, "rb") as _fh:
            _rv1_after = _fh.read()
        _rv1_bug = (_mio.load_manifest(mprv1).get("bugs") or [{}])[0]
        check("nc5 `done --no-change` on a bug's FIX TASK is refused and names "
              "`/audit:bug close <id> not_a_bug|wontfix` - a bug is never fixed "
              "without a fix commit - and the bug stays open: %s" % (txt,),
              code == 2 and "/audit:bug close BUG-1" in txt
              and "not_a_bug" in txt and _rv1_after == _rv1_before
              and _rv1_bug.get("status") == "in_progress")
        check("nc6 ...and the route it names runs CANCEL FIRST: `/audit:bug close` "
              "refuses while the bug's task is in progress, so the other order "
              "fails at its first step: %s" % (txt,),
              "/audit:task cancel P2.4" in txt
              and txt.index("/audit:task cancel P2.4") < txt.index("/audit:bug close"))
        # R2: the moved-away id is never minted again.
        projrv2, mprv2 = mk("rv-move-reissue", base_manifest())
        run(["move", "P2.3", "--to", "P3", "--project-dir", projrv2])
        code, txt = run(["add", "After the move", "--phase", "P2", "--json",
                         "--project-dir", projrv2])
        try:
            _rv2_id = json.loads(txt).get("id")
        except ValueError:
            _rv2_id = None
        check("mv3 moving a phase's HIGHEST task and then adding to that phase does "
              "not reissue the moved-away id: %r" % (_rv2_id,),
              code == 0 and _rv2_id == "P2.4")
        code, txt = run(["move", "P3.1", "--to", "P2", "--project-dir", projrv2])
        _rv2_m = _mio.tasks_by_id(_mio.load_manifest(mprv2))
        _rv2_back = [t for t in _rv2_m.values()
                     if (t.get("movedFrom") or {}).get("id") == "P3.1"]
        check("mv4 a second move keeps the first one's origin in the chain - so both "
              "old ids stay taken and a reader can still join the oldest rows: %r"
              % ([t.get("movedFrom") for t in _rv2_back],),
              code == 0 and len(_rv2_back) == 1
              and (_rv2_back[0]["movedFrom"].get("previous") or {}).get("id")
              == "P2.3" and _rv2_back[0]["id"] == "P2.5")
        # R3: move says what it leaves behind in the evidence ledger.
        import _evidence_io
        projrv3, mprv3 = mk("rv-move-evidence", base_manifest())
        _evidence_io.append_row(projrv3, {
            "v": 1, "runId": "RV1", "ts": "2026-08-26T10:00:00Z", "scope": "task",
            "taskId": "P2.3", "phaseId": "P2", "status": "failed", "steps": []})
        code, txt = run(["move", "P2.3", "--to", "P3", "--json",
                         "--project-dir", projrv3])
        try:
            _rv3_js = json.loads(txt)
        except ValueError:
            _rv3_js = {}
        projrv3b, _mprv3b = mk("rv-move-evidence-human", base_manifest())
        _evidence_io.append_row(projrv3b, {
            "v": 1, "runId": "RV2", "ts": "2026-08-26T10:00:00Z", "scope": "task",
            "taskId": "P2.3", "phaseId": "P2", "status": "failed", "steps": []})
        code2, txt2 = run(["move", "P2.3", "--to", "P3", "--project-dir", projrv3b])
        _rv3_line = [ln.strip() for ln in txt2.splitlines()
                     if ln.strip().startswith("evidence:")]
        check("mv5 a move over ONE recorded run counts it exactly - `--json` "
              "carries evidenceRunsLeft 1 and the line names the count and the "
              "two readers that join it: %r" % ((_rv3_js.get("evidenceRunsLeft"),
                                                  _rv3_line),),
              code == 0 and _rv3_js.get("evidenceRunsLeft") == 1 and code2 == 0
              and len(_rv3_line) == 1
              and _rv3_line[0].startswith("evidence: 1 recorded run(s) stay keyed "
                                          "to P2.3")
              and "/audit:doctor and --reconcile join them" in _rv3_line[0])
        projrv3c, _mprv3c = mk("rv-move-no-evidence", base_manifest())
        code3, txt3 = run(["move", "P2.3", "--to", "P3", "--project-dir", projrv3c])
        check("mv5b SECOND DIRECTION: a move over NO recorded run prints no evidence "
              "line at all: %s" % (txt3,),
              code3 == 0 and not [ln for ln in txt3.splitlines()
                                  if ln.strip().startswith("evidence:")])
        with open(os.path.join(_output.PLUGIN_ROOT, "schema",
                               "audit-plan.schema.json"), encoding="utf-8") as _fh:
            _rv_mf = (json.load(_fh)["$defs"]["task"]["properties"]["movedFrom"])
        check("mv5c the schema documents `movedFrom.previous`, the link a second "
              "move nests: %r" % (sorted(_rv_mf.get("properties") or {}),),
              "previous" in (_rv_mf.get("properties") or {})
              and "previous" in _rv_mf.get("description", ""))
        # R6: the target resolves before the task's own status is judged, and a
        # signed-off target's refusal speaks of the move.
        projrv6, _mprv6 = mk("rv-move-order", base_manifest())
        code, txt = run(["move", "P2.1", "--to", "P99", "--project-dir", projrv6])
        check("mv6 `move <done task> --to <no such phase>` names the missing phase - "
              "item 1 of the documented order - before the task's status: %s"
              % (txt,), code == 2 and "no phase P99" in txt)
        code, txt = run(["move", "P2.1", "--to", "P1", "--project-dir", projrv6])
        check("mv6b `move <done task> --to <done phase>` answers with the TASK's "
              "refusal (item 3), not the target's state (item 5) - the phase is "
              "checked for existence first and judged after the task: %s" % (txt,),
              code == 2 and "P2.1 is done" in txt and "phase P1 is done" not in txt)
        rvso = base_manifest()
        rvso["phases"][2].update(status="in_progress", branch="audit/p3",
                                 review={"status": "passed"})
        rvso["phases"][2]["tasks"] = [{"id": "P3.1", "title": "x", "status": "done"}]
        projrv6b, _mprv6b = mk("rv-move-signed", rvso)
        code, txt = run(["move", "P2.3", "--to", "P3", "--project-dir", projrv6b])
        check("mv7 ...and a signed-off target's refusal is about the MOVE, not about "
              "adding a task: %s" % (txt,),
              code == 2 and "signed off" in txt and "moved" in txt
              and "a task added now" not in txt)
        # R5: a --json no-op is a JSON object.
        projrv5, _mprv5 = mk("rv-json-noop", base_manifest())
        code, txt = run(["scope", "P2.3", "--risk", "low", "--json",
                         "--project-dir", projrv5])
        code2, txt2 = run(["scope", "P2.3", "--risk", "low", "--json",
                           "--project-dir", projrv5])
        code3, txt3 = run(["retarget", "P3", "--area", "", "--json",
                           "--project-dir", projrv5])
        code4, txt4 = run(["retarget", "P3", "--area", "", "--json",
                           "--project-dir", projrv5])
        def _rv_obj(t):
            try:
                o = json.loads(t)
            except ValueError:
                return None
            return o if isinstance(o, dict) else None
        check("jr3 a `--json` call that changes nothing - `scope` and `retarget` "
              "alike - prints one object saying so, never prose: %r"
              % ((_rv_obj(txt2), _rv_obj(txt4)),),
              code2 == 0 and (_rv_obj(txt2) or {}).get("changed") is False
              and (_rv_obj(txt2) or {}).get("ok") is True
              and code4 == 0 and (_rv_obj(txt4) or {}).get("changed") is False)
        # R7: the ceiling refusal names the verb the reference docs now require.
        rvcap = base_manifest()
        rvcap["phases"][1]["tasks"][1].update(attempts=3, maxAttempts=3)
        projrv7, _mprv7 = mk("rv-ceiling", rvcap)
        code, txt = run(["start", "P2.3", "--project-dir", projrv7])
        check("bk4 the start refused at maxAttempts names `audit-task.py block <id> "
              "--reason`, the verb the orchestrator is told to use: %s" % (txt,),
              code == 2 and "audit-task.py block P2.3 --reason" in txt)
        # Pre-existing: fileIndex rows keyed through the line-range suffix.
        projrvx, mprvx = mk("rv-line-suffix", base_manifest())
        code, txt = run(["scope", "P2.3", "--files", "src/q.ts:10-20",
                         "--project-dir", projrvx])
        code2, txt2 = run(["add", "Ranged", "--phase", "P2", "--files",
                           "src/r.ts:1-5", "--project-dir", projrvx])
        _rvx = _mio.load_manifest(mprvx).get("fileIndex") or {}
        check("fx1 `scope` and `add` key a `:line-range` entry's fileIndex row by the "
              "PATH - the key the plan gate and the validator match on: %r" % (_rvx,),
              code == 0 and code2 == 0 and _rvx.get("src/q.ts") == ["P2.3"]
              and _rvx.get("src/r.ts") == ["P2.4"]
              and "src/q.ts:10-20" not in _rvx and "src/r.ts:1-5" not in _rvx)
        code, txt = run(["scope", "P2.3", "--files", "src/a.ts",
                         "--project-dir", projrvx])
        _rvx2 = _mio.load_manifest(mprvx).get("fileIndex") or {}
        check("fx2 ...and releasing that entry removes the task from the PATH's row: "
              "%r" % (_rvx2,),
              code == 0 and "P2.3" not in (_rvx2.get("src/q.ts") or [])
              and "P2.3" in (_rvx2.get("src/a.ts") or []))
        # R4: a colon before a DIGIT after whitespace is what a substituted
        # "`path`:line" citation leaves, so it stays refused.
        projrv4, _mprv4 = mk("rv-colon-digit", base_manifest())
        code, txt = run(["add", "Cite", "--phase", "P2", "--description",
                         "see :2680 for the retry", "--project-dir", projrv4])
        check("cg3 SECOND DIRECTION: ` :2680` - what \"`run-test-gate.py`:2680\" "
              "leaves after substitution - is still refused: %s" % (txt[:120],),
              code == 2 and "hugs the word" in txt)
        # R8: a span substituted at the END leaves trailing whitespace on its own.
        code, txt = run(["add", "Trail", "--phase", "P2", "--description",
                         "fix the build ", "--project-dir", projrv4])
        check("gz3 trailing whitespace is named as likely COMMAND SUBSTITUTION too - a "
              "span at the end of the text leaves it as mechanically as one at the "
              "start: %s" % (txt,),
              code == 2 and "Likely COMMAND SUBSTITUTION" in txt)

        # ---- (dg) a gate-only task narrows only to a SUITE PATH ----------------
        # `tests.add` already proves a tdd/regression task creates a real test
        # file, so its `files` arm stays unfiltered (dg3, unchanged from
        # today) - but a gate-only task names no case at all, and a source
        # file among its `files` is not evidence the sibling's suite-running
        # command has anything of THIS task's to run. RED-FIRST on today's
        # code: before this fix, dg1 below reads back
        # `["vitest run src/Button.tsx README.md"]` with basis `"files"`, the
        # sibling's spelling pointed at two files it never tested.
        def dg_manifest():
            return {
                "meta": {"version": 2,
                         "buildCommands": {"lint": "eslint .",
                                           "typecheck": "tsc --noEmit",
                                           "test": "vitest run"},
                         "phaseGate": {"always": ["lint", "typecheck"]}},
                "phases": [
                    {"id": "P1", "title": "UI", "status": "in_progress",
                     "testGate": ["lint", "typecheck", "test"],
                     "tasks": [
                         {"id": "P1.1", "title": "seed", "status": "done",
                          "files": ["src/a.ts"],
                          "tests": {"mode": "gate-only", "add": [],
                                    "expectRedFirst": False,
                                    "gate": ["vitest run src/a.test.ts"]}}]},
                ],
                "fileIndex": {"src/a.ts": ["P1.1"]},
                "bugs": [],
            }

        dg_proj, dg_mp = mk("dg-gate", dg_manifest())

        def dg_tests(tid):
            return (task_in(dg_mp, tid) or {}).get("tests") or {}

        codedg, txtdg = run(
            ["add", "New button", "--phase", "P1", "--project-dir", dg_proj,
             "--files", "src/Button.tsx,README.md"])
        check("dg1 RED-FIRST: a gate-only task whose files name NO suite path "
              "gets `meta.phaseGate.always`, with basis `gate-only-no-suite` - "
              "never the sibling's spelling pointed at two source files "
              "nothing here tested: %r"
              % ((dg_tests("P1.2").get("gate"), dg_tests("P1.2").get("gateBasis")),),
              codedg == 0
              and dg_tests("P1.2").get("gate") == ["lint", "typecheck"]
              and dg_tests("P1.2").get("gateBasis") == "gate-only-no-suite")

        # ALLOW CASE: a suite path AMONG the files still narrows the gate, in
        # the sibling's spelling - the arm this fix must not disable outright.
        codedg, txtdg = run(
            ["add", "New button, tested", "--phase", "P1",
             "--project-dir", dg_proj, "--files",
             "src/Button.tsx,src/Button.test.tsx"])
        check("dg2 ALLOW CASE: a suite path among the files still narrows the "
              "gate, in the sibling's spelling: %r"
              % ((dg_tests("P1.3").get("gate"), dg_tests("P1.3").get("gateBasis")),),
              codedg == 0
              and dg_tests("P1.3").get("gate")
              == ["vitest run src/Button.test.tsx"]
              and dg_tests("P1.3").get("gateBasis") == "files")

        # ALLOW CASE: a REGRESSION task's `files` arm is unfiltered, exactly as
        # today - `tests.add`'s invariant already covers it, this fix is
        # gate-only's alone.
        codedg, txtdg = run(
            ["add", "Fix a regression", "--phase", "P1",
             "--project-dir", dg_proj, "--tests-mode", "regression",
             "--files", "src/Button.tsx"])
        check("dg3 ALLOW CASE: a regression task keeps today's unfiltered "
              "`files` arm even with only a source file named: %r"
              % ((dg_tests("P1.4").get("gate"), dg_tests("P1.4").get("gateBasis")),),
              codedg == 0
              and dg_tests("P1.4").get("gate") == ["vitest run src/Button.tsx"]
              and dg_tests("P1.4").get("gateBasis") == "files")

        # ---- (pg) a NEW PHASE's gate: always FIRST, exclude the only drop ------
        pg_always = {
            "meta": {"version": 2,
                     "buildCommands": {"test": "npm test",
                                       "lint": "npm run lint"},
                     "phaseGate": {"always": ["lint"]}},
            "phases": [], "fileIndex": {}, "bugs": [],
        }
        pg_proj, pg_mp = mk("pg-always", pg_always)
        code, txt = run(["add-phase", "Docs", "--outcome", "shipped",
                         "--project-dir", pg_proj])

        def pg_gate(mp, title):
            found = [p for p in _mio.load_manifest(mp)["phases"]
                    if p.get("title") == title]
            return found[0].get("testGate") if found else None

        check("pg1 RED-FIRST: `meta.phaseGate.always` puts a key FIRST and every "
              "OTHER buildCommands key still follows, in buildCommands order - "
              "`always` is an ORDER and never a narrowing, so `test` does not "
              "vanish: %r" % (pg_gate(pg_mp, "Docs"),),
              code == 0 and pg_gate(pg_mp, "Docs") == ["lint", "test"]
              and "meta.phaseGate.always first" in txt)

        pg_exclude = {
            "meta": {"version": 2,
                     "buildCommands": {"test": "npm test",
                                       "lint": "npm run lint",
                                       "coverage": "npm run coverage"},
                     "phaseGate": {"exclude": ["coverage"]}},
            "phases": [], "fileIndex": {}, "bugs": [],
        }
        pg_proj2, pg_mp2 = mk("pg-exclude", pg_exclude)
        code, txt = run(["add-phase", "Docs2", "--outcome", "shipped",
                         "--project-dir", pg_proj2])
        check("pg2 RED-FIRST: `meta.phaseGate.exclude` drops the buildCommands "
              "key it names from a NEW phase's gate, and the basis names the "
              "exclusion - today's code writes `coverage` in anyway and the "
              "basis names no exclusion at all: %r"
              % ((pg_gate(pg_mp2, "Docs2"), txt.splitlines()[2]
                  if len(txt.splitlines()) > 2 else txt),),
              code == 0 and pg_gate(pg_mp2, "Docs2") == ["test", "lint"]
              and "coverage" not in (pg_gate(pg_mp2, "Docs2") or [])
              and "excluded by meta.phaseGate.exclude" in txt
              and "coverage" in txt)

        # pg3: EXCLUDE-TO-NOTHING - `meta.phaseGate.exclude` names every
        # buildCommands key and `always` adds none back, so the derived
        # default has nothing left. Today's code (which never reads `exclude`
        # at all) would write both keys in anyway; this is CERTAIN even with
        # no evidence in hand (`phase_gate_suite_gap`'s first arm), which is
        # why the validator's warning fires from the plan alone.
        pg_nothing = {
            "meta": {"version": 2,
                     "buildCommands": {"lint": "npm run lint",
                                       "test": "npm test"},
                     "phaseGate": {"exclude": ["lint", "test"]}},
            "phases": [], "fileIndex": {}, "bugs": [],
        }
        pg_proj3, pg_mp3 = mk("pg-nothing", pg_nothing)
        code, txt = run(["add-phase", "Docs3", "--outcome", "shipped",
                         "--project-dir", pg_proj3])
        check("pg3 RED-FIRST EXCLUDE-TO-NOTHING: `meta.phaseGate.exclude` "
              "naming EVERY buildCommands key, with no `always`, writes an "
              "EMPTY gate - the basis names `meta.phaseGate.exclude` as the "
              "cause, and the post-write warnings carry `phase_gate_suite_gap`'s "
              "'phase gate runs no suite' line, since nothing here can prove "
              "this phase done: %r"
              % ((pg_gate(pg_mp3, "Docs3"),
                  [ln for ln in txt.splitlines() if "WARNING" in ln]),),
              code == 0 and pg_gate(pg_mp3, "Docs3") == []
              and "meta.phaseGate.exclude" in txt
              and "phase gate runs no suite" in txt)

        # pg4: ABSENT phaseGate = TODAY - locked to the literal, now that the
        # derivation this case checks (calling `phase_gate_default` at all) is
        # itself part of the committed HEAD this suite runs against. This case
        # used to capture its expected value by loading HEAD's OWN
        # `_phase_gate` text dynamically and running it - the right proof
        # while HEAD still held the PRE-fix code, so a hand-derived
        # expectation could not be an inference from the same function being
        # tested. Once that derivation landed, HEAD's `_phase_gate` IS this
        # module's, so that comparison had become `M._phase_gate` read back at
        # itself (and broke outright: the extracted function text called
        # `_phases.phase_gate_default`, a name that exists in THIS module's
        # namespace and not in the bare one the extracted text was `exec`'d
        # into - `NameError: name '_phases' is not defined`). The mutation
        # this case exists to catch (building the default from SORTED keys)
        # was proved live during that derivation's own red-first pass; the
        # literal here is what stays to keep proving it.
        import types
        _pg4_args = types.SimpleNamespace(gate=None, gate_clear=False)
        _pg4_manifest = {"meta": {
            "version": 2,
            "buildCommands": {"test": "npm test", "lint": "npm run lint",
                              "coverage": "npm run coverage"}}}
        _pg4_got = M._phase_gate(_pg4_args, _pg4_manifest)
        check("pg4 ABSENT phaseGate = TODAY: with no `meta.phaseGate` at all, "
              "the gate is every buildCommands key in ITS OWN declared order "
              "(`test, lint, coverage`), never sorted, with basis 'from "
              "meta.buildCommands': %r" % (_pg4_got,),
              _pg4_got == (["test", "lint", "coverage"],
                          "from meta.buildCommands"))

        # ---- (ff) a fix task opened after a red run is gated on ITS failing --
        # suites -- `add --failing-from <runId>`. `named_failing_suites`'s own
        # rule: only a step whose `failingSuitesBasis` says the runner NAMED
        # them counts; a tail excerpt is not a list of failing tests.
        import _evidence_io as _ff_ev

        def ff_manifest():
            return {
                "meta": {"version": 2,
                         "buildCommands": {"lint": "eslint .",
                                           "test": "vitest run"}},
                "phases": [
                    {"id": "P1", "title": "Cart", "status": "in_progress",
                     "testGate": ["lint", "test"],
                     "tasks": [{
                         "id": "P1.1", "title": "seed", "status": "done",
                         "files": ["src/a.ts"],
                         "tests": {"mode": "gate-only", "add": [],
                                  "expectRedFirst": False,
                                  "gate": ["lint",
                                          "vitest run src/a.test.ts"]}}]},
                    {"id": "P2", "title": "Elsewhere", "status": "pending",
                     "testGate": ["lint", "test"], "tasks": []},
                ],
                "fileIndex": {"src/a.ts": ["P1.1"]},
                "bugs": [],
            }

        ff_proj, ff_mp = mk("ff-failing-from", ff_manifest())
        # ON DISK, because a named suite is only narrowed to when the gate can
        # open it from the project root; this project is not a git one, so a
        # spelling it does not hold has no tracked file to be pinned onto.
        for _ff_rel in ("src/cart.test.ts", "src/spied.test.ts"):
            os.makedirs(os.path.join(ff_proj, "src"), exist_ok=True)
            with open(os.path.join(ff_proj, _ff_rel), "w") as fh:
                fh.write("// a fixture suite\n")
        _ff_ev.append_row(ff_proj, {
            "v": 1, "runId": "RUN-VITEST", "ts": "2026-09-01T00:00:00Z",
            "scope": "phase", "phaseId": "P1", "status": "failed",
            "steps": [{"name": "test", "exit": 1,
                      "failingSuites": ["src/cart.test.ts"],
                      "failingSuitesBasis": ("the 1 suite file(s) vitest "
                                             "named as failing, read from "
                                             "vitest's FAIL <file> line(s)")}]})

        def ff_tests(tid):
            return (task_in(ff_mp, tid) or {}).get("tests") or {}

        codeff, txtff = run(
            ["add", "Fix the cart total", "--phase", "P1",
             "--project-dir", ff_proj, "--failing-from", "RUN-VITEST",
             "--tests-add", "src/cart2.test.ts: covers the new branch too"])
        check("ff1 RED-FIRST (dg21): a fixture ledger row with a failed step "
              "whose failingSuites names ['src/cart.test.ts'] (named basis) "
              "and a sibling spelled 'vitest run src/a.test.ts' give the new "
              "task 'vitest run src/cart.test.ts <its tests.add path>' and "
              "gateBasis failing-from-run:<runId> - today's parser does not "
              "know --failing-from at all, so this exits 2 rather than 0: %r"
              % ((codeff, ff_tests("P1.2").get("gate"),
                  ff_tests("P1.2").get("gateBasis")),),
              codeff == 0
              and ff_tests("P1.2").get("gate")
              == ["lint",
                  "vitest run src/cart.test.ts src/cart2.test.ts"]
              and ff_tests("P1.2").get("gateBasis")
              == "failing-from-run:RUN-VITEST")

        # ---- MUTATION GUARD: a JEST-shaped row, `failing` carries CHECK -----
        # names, never a suite path - reading suites off it instead of
        # `failingSuites` would put a check's own title where a file path
        # belongs.
        _ff_ev.append_row(ff_proj, {
            "v": 1, "runId": "RUN-JEST", "ts": "2026-09-01T00:05:00Z",
            "scope": "phase", "phaseId": "P1", "status": "failed",
            "steps": [{"name": "test", "exit": 1,
                      "failing": ["renders the cart > totals an empty cart"],
                      "failingSuites": ["src/cart.test.ts"],
                      "failingSuitesBasis": ("the 1 suite file(s) jest named "
                                             "as failing, read from jest's "
                                             "FAIL <path> header(s)")}]})
        codeff, txtff = run(
            ["add", "Fix on a jest-shaped row", "--phase", "P1",
             "--project-dir", ff_proj, "--failing-from", "RUN-JEST"])
        check("ff2 MUTATION GUARD (dg21): the suite is read off "
              "`failingSuites`, a FILE, never off `failing`, a CHECK's own "
              "title with no path in it at all: %r"
              % (ff_tests("P1.3").get("gate"),),
              codeff == 0
              and ff_tests("P1.3").get("gate")
              == ["lint", "vitest run src/cart.test.ts"])

        # ---- ALLOW CASE: a TAIL basis falls through, printing why ----------
        _ff_ev.append_row(ff_proj, {
            "v": 1, "runId": "RUN-TAIL", "ts": "2026-09-01T00:10:00Z",
            "scope": "phase", "phaseId": "P1", "status": "failed",
            "steps": [{"name": "test", "exit": 1,
                      "failingSuitesBasis": (
                          "no runner this gate can count recognised, so no "
                          "suite file could be named")}]})
        codeff, txtff = run(
            ["add", "Fix from a tail-only row", "--phase", "P1",
             "--project-dir", ff_proj, "--failing-from", "RUN-TAIL",
             "--tests-add", "src/tail.test.ts: the case this task writes"])
        check("ff3 ALLOW CASE: a row with a TAIL basis (no runner named a "
              "suite) falls through to the task's tests.add gate, with the "
              "reason PRINTED rather than an empty gate - the gate is never "
              "empty just because --failing-from could not narrow anything: "
              "%r" % ((codeff, ff_tests("P1.4").get("gate"),
                       ff_tests("P1.4").get("gateBasis")),),
              codeff == 0
              and ff_tests("P1.4").get("gate")
              == ["lint", "vitest run src/tail.test.ts"]
              and ff_tests("P1.4").get("gateBasis") == "tests.add"
              and "named no suite as failing" in txtff)

        # ---- ALLOW CASE: an unknown runId is refused, exit 2 ----------------
        codeff, txtff = run(
            ["add", "Fix an id nobody recorded", "--phase", "P1",
             "--project-dir", ff_proj, "--failing-from", "NO-SUCH-RUN"])
        check("ff4 ALLOW CASE: an unknown runId is refused exit 2, naming NO "
              "run rather than handing back the ordinary derivation in "
              "silence: %r" % (txtff[:120],),
              codeff == 2 and "no run with this id" in txtff
              and task_in(ff_mp, "P1.5") is None)

        # ---- a torn ledger line: the run is not called absent ---------------
        # It may be the very line the read lost, so the refusal names the
        # file that could not be read in full, as --caught's does.
        fl_proj, fl_mp = mk("ff-torn", ff_manifest())
        _ff_ev.append_row(fl_proj, {
            "v": 1, "runId": "RUN-FL", "ts": "2026-09-01T00:00:00Z",
            "scope": "phase", "phaseId": "P1", "status": "failed",
            "steps": []})
        _fl_ledger = _ff_ev.ledger_files(fl_proj)[-1]
        with open(_fl_ledger, "a", encoding="utf-8") as _fl_fh:
            _fl_fh.write('{"v": 1, "runId": "RUN-FL-LOST", "ts": "2026-09\n')
        codefl, txtfl = run(
            ["add", "Fix from a lost run", "--phase", "P1",
             "--project-dir", fl_proj, "--failing-from", "RUN-FL-LOST"])
        check("ff4b RED-FIRST: --failing-from a run not among the readable "
              "rows, with a ledger line torn, is refused exit 2 naming the "
              "file that could not be read in full - never 'no such run': %r"
              % ((codefl, txtfl[:300]),),
              codefl == 2 and os.path.basename(_fl_ledger) in txtfl
              and "could not be read" in txtfl
              and "is in the evidence ledger" not in txtfl)

        # ---- ALLOW CASE: a PASSED row is refused, exit 2 --------------------
        _ff_ev.append_row(ff_proj, {
            "v": 1, "runId": "RUN-GREEN", "ts": "2026-09-01T00:15:00Z",
            "scope": "phase", "phaseId": "P1", "status": "passed", "steps": []})
        codeff, txtff = run(
            ["add", "Fix from a green run", "--phase", "P1",
             "--project-dir", ff_proj, "--failing-from", "RUN-GREEN"])
        check("ff5 ALLOW CASE: a run that PASSED is refused exit 2, naming its "
              "actual status - a fix task opened from a passed run is not "
              "failed-first: %r" % (txtff[:120],),
              codeff == 2 and "not a FAILED run" in txtff and "passed" in txtff
              and task_in(ff_mp, "P1.5") is None)

        # ---- ALLOW CASE: a row scoped to a DIFFERENT phase is refused -------
        _ff_ev.append_row(ff_proj, {
            "v": 1, "runId": "RUN-OTHER", "ts": "2026-09-01T00:20:00Z",
            "scope": "phase", "phaseId": "P2", "status": "failed",
            "steps": [{"name": "test", "exit": 1,
                      "failingSuites": ["src/other.test.ts"],
                      "failingSuitesBasis": ("the 1 suite file(s) vitest "
                                             "named as failing, read from "
                                             "vitest's FAIL <file> line(s)")}]})
        codeff, txtff = run(
            ["add", "Fix P1 from P2's run", "--phase", "P1",
             "--project-dir", ff_proj, "--failing-from", "RUN-OTHER"])
        check("ff6 ALLOW CASE: a row scoped to a DIFFERENT phase is refused - "
              "a fix task's gate can only narrow to suites THIS phase's own "
              "run named as failing: %r" % (txtff[:140],),
              codeff == 2 and "not phase P1's" in txtff
              and task_in(ff_mp, "P1.5") is None)

        # ---- RED-FIRST: a MUTED step never narrows a fix task's gate -------
        # A step the committed row marks `muted` failed under a quarantine: a
        # known failure a bug already tracks, not something this run caught.
        # Its named suites are the one reading that must stay out of the gate.
        _ff_muted_basis = ("the 1 suite file(s) vitest named as failing, "
                           "read from vitest's FAIL <file> line(s)")
        _ff_ev.append_row(ff_proj, {
            "v": 1, "runId": "RUN-MUTED", "ts": "2026-09-01T00:25:00Z",
            "scope": "phase", "phaseId": "P1", "status": "failed",
            "steps": [{"name": "test", "exit": 1,
                      "failingSuites": ["src/quarantined.test.ts"],
                      "failingSuitesBasis": _ff_muted_basis,
                      "muted": [{"test": "src/quarantined.test.ts",
                                 "bugId": "BUG-1",
                                 "until": "2999-01-01"}]}]})
        _ff_muted_row = _ff_ev.row_by_run(
            _ff_ev.read_rows(ff_proj)["rows"], "RUN-MUTED")
        codeff, txtff = run(
            ["add", "Fix beside a quarantine", "--phase", "P1",
             "--project-dir", ff_proj, "--failing-from", "RUN-MUTED",
             "--tests-add", "src/fix.test.ts: the case this task writes"])
        check("ff7 RED-FIRST: a failed row whose ONLY failing suite sits on a "
              "step the row marks muted yields no failing-from paths, so the "
              "task falls through to its tests.add gate with the reason "
              "printed - a quarantined suite never narrows a fix task's "
              "gate: %r" % ((codeff, _ff_ev.named_failing_suites(
                  (_ff_muted_row or {}).get("steps")),
                  ff_tests("P1.5").get("gate"),
                  ff_tests("P1.5").get("gateBasis")),),
              _ff_muted_row is not None
              and _ff_ev.named_failing_suites(
                  _ff_muted_row.get("steps")) == []
              and codeff == 0
              and ff_tests("P1.5").get("gate")
              == ["lint", "vitest run src/fix.test.ts"]
              and ff_tests("P1.5").get("gateBasis") == "tests.add"
              and "named no suite as failing" in txtff)
        # ...and the direction a skip that is too wide breaks in: only the
        # muted STEP is skipped, never the row it sits in.
        _ff_mixed = {"steps": [
            {"name": "unit", "exit": 1,
             "failingSuites": ["src/quarantined.test.ts"],
             "failingSuitesBasis": _ff_muted_basis,
             "muted": [{"test": "src/quarantined.test.ts", "bugId": "BUG-1",
                        "until": "2999-01-01"}]},
            {"name": "e2e", "exit": 1, "failingSuites": ["src/live.test.ts"],
             "failingSuitesBasis": _ff_muted_basis, "muted": []}]}
        check("ff8 ALLOW CASE: in a row with a muted step and an unmuted one "
              "(an empty `muted` is no quarantine), only the unmuted step's "
              "suites are read: %r"
              % (_ff_ev.named_failing_suites(_ff_mixed["steps"]),),
              _ff_ev.named_failing_suites(_ff_mixed["steps"])
              == ["src/live.test.ts"])

        # ---- ONE READING: both verbs ask `_evidence_io`, never a copy ------
        # A spy stands in for the shared reading and answers with a suite no
        # row names, so a verb still reading its own copy would narrow to the
        # row's real suite instead - the answer, not merely the call, has to
        # come from the shared function.
        _sp_calls = []
        _sp_real = _ff_ev.named_failing_suites

        def _sp_spy(steps):
            _sp_calls.append(steps)
            return ["src/spied.test.ts"]
        _ff_ev.named_failing_suites = _sp_spy
        try:
            codesp, txtsp = run(
                ["add", "Fix read through the spy", "--phase", "P1",
                 "--project-dir", ff_proj, "--failing-from", "RUN-VITEST"])
        finally:
            _ff_ev.named_failing_suites = _sp_real
        check("ff9 the failing-from gate is read through "
              "`_evidence_io.named_failing_suites`, handed the row's steps, "
              "and narrows to what IT answers: %r"
              % ((codesp, _sp_calls, ff_tests("P1.6").get("gate")),),
              M._evidence_io is _ff_ev
              and not hasattr(M, "_named_failing_suites")
              and codesp == 0 and len(_sp_calls) == 1
              and isinstance(_sp_calls[0], list)
              and _sp_calls[0][0].get("failingSuites")
              == ["src/cart.test.ts"]
              and ff_tests("P1.6").get("gate")
              == ["lint", "vitest run src/spied.test.ts"])

        # ---- a runner's spelling becomes a path FROM THE PROJECT ROOT -------
        # The gate runs with the project root as its working directory, and a
        # runner may name a suite relative to its own. A git project whose
        # sibling spells `python3 -m pytest <path>`, holding suites chosen so
        # each case's spelling answers differently: one unique suffix match,
        # one shared by two tracked files, and one that exists from the root
        # AND shares its suffix with a deeper tracked file.
        rr_manifest = {
            "meta": {"version": 2,
                     "buildCommands": {"test": "python3 -m pytest"}},
            "phases": [{"id": "P1", "title": "Api", "status": "in_progress",
                        "testGate": ["test"],
                        "tasks": [{
                            "id": "P1.1", "title": "seed", "status": "done",
                            "files": ["backend/a.py"],
                            "tests": {"mode": "gate-only", "add": [],
                                      "expectRedFirst": False,
                                      "gate": ["python3 -m pytest "
                                               "backend/tests/test_a.py"]}}]},
                       # A phase with NO testGate, for ff20's last fallback.
                       {"id": "P2", "title": "Bare", "status": "in_progress",
                        "testGate": [],
                        "tasks": [{
                            "id": "P2.1", "title": "seed", "status": "done",
                            "files": ["backend/b.py"],
                            "tests": {"mode": "gate-only", "add": [],
                                      "expectRedFirst": False,
                                      "gate": ["python3 -m pytest "
                                               "backend/tests/test_a.py"]}}]}],
            "fileIndex": {"backend/a.py": ["P1.1"], "backend/b.py": ["P2.1"]},
            "bugs": [],
        }
        rr_proj, rr_mp = mk("ff-runner-relative", rr_manifest, git=True)
        rr_suites = ["backend/tests/test_a.py", "backend/tests/test_old.py",
                     "backend/tests/test_dup.py", "tools/tests/test_dup.py",
                     "tests/test_root.py", "backend/tests/test_root.py"]
        for rel in rr_suites:
            os.makedirs(os.path.dirname(os.path.join(rr_proj, rel)),
                        exist_ok=True)
            with open(os.path.join(rr_proj, rel), "w") as fh:
                fh.write("def test_x():\n    assert True\n")
        subprocess.run(["git", "-C", rr_proj, "add", "--"] + rr_suites,
                       check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        rr_named = ("the 1 suite file(s) pytest %s, read from its FAILED "
                    "<path> lines" % (_ff_ev.NAMED_FAILING,))
        # A file OUTSIDE the project, real on disk, so an absolute spelling of
        # it is refused for where it lies and not for being missing.
        rr_outside = os.path.join(tmp, "outside_test_x.py")
        with open(rr_outside, "w") as fh:
            fh.write("def test_x():\n    assert True\n")
        # The step's recorded `name` is the gate entry the run ran; RUN-STEP's
        # is a literal command distinct from the phase's `test`, so a gate
        # read off the step and one read off the phase disagree.
        rr_step_entry = "python3 -m pytest backend/tests"
        for rr_id, rr_list, rr_name in (
                ("RUN-REL", ["test_old.py"], "test"),
                ("RUN-DUP", ["test_dup.py"], "test"),
                ("RUN-ROOT", ["tests/test_root.py"], "test"),
                ("RUN-PART", ["test_old.py", "test_dup.py"], "test"),
                ("RUN-STEP", ["test_dup.py"], rr_step_entry),
                ("RUN-ABSIN", [os.path.join(rr_proj, "backend", "tests",
                                            "test_old.py")], "test"),
                ("RUN-ABSOUT", [rr_outside], "test"),
                ("RUN-DOT", ["./test_old.py"], "test")):
            _ff_ev.append_row(rr_proj, {
                "v": 1, "runId": rr_id, "ts": "2026-09-01T00:00:00Z",
                "scope": "phase", "phaseId": "P1", "status": "failed",
                "steps": [{"name": rr_name, "exit": 1,
                           "failingSuites": rr_list,
                           "failingSuitesBasis": rr_named}]})

        def rr_tests(tid):
            return (task_in(rr_mp, tid) or {}).get("tests") or {}

        coderr, txtrr = run(
            ["add", "Fix the old suite", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-REL"])
        check("ff10 RED-FIRST: a runner that names its suite relative to its "
              "own directory (`test_old.py`) gets the one tracked path it "
              "names, spelled from the project root the gate runs in - not "
              "the runner's spelling, which that directory cannot open: %r"
              % ((coderr, rr_tests("P1.2").get("gate"),
                  rr_tests("P1.2").get("gateBasis")),),
              coderr == 0
              and rr_tests("P1.2").get("gate")
              == ["python3 -m pytest backend/tests/test_old.py"]
              and rr_tests("P1.2").get("gateBasis")
              == "failing-from-run:RUN-REL")

        coderr, txtrr = run(
            ["add", "Fix a suite two files could be", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-DUP",
             "--tests-add", "backend/tests/test_new.py: the case it writes"])
        check("ff11 a spelling two tracked files end in names neither of "
              "them, and a task WITH tests.add still gets the failed step's "
              "own entry (`test`) rather than its tests.add narrowing, which "
              "would run neither suite - the resolver's reason, naming both, "
              "printed before the basis: %r"
              % ((coderr, rr_tests("P1.3").get("gate"),
                  rr_tests("P1.3").get("gateBasis"),
                  [ln for ln in txtrr.splitlines() if "names each" in ln]),),
              coderr == 0
              and rr_tests("P1.3").get("gate") == ["test"]
              and rr_tests("P1.3").get("gateBasis")
              == "failing-from-run:RUN-DUP"
              and "names each of backend/tests/test_dup.py, "
                  "tools/tests/test_dup.py" in txtrr
              and "so no suite is narrowed to" in txtrr
              and txtrr.index("names each of") < txtrr.index(
                  "so no suite is narrowed to"))

        coderr, txtrr = run(
            ["add", "Fix the root suite", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-ROOT"])
        check("ff12 ONE RULE FOR AMBIGUITY: a spelling that exists from the "
              "project root while a deeper tracked file ends in it too is "
              "ambiguous - the resolver's own rule, that an exact-equal path "
              "breaks no tie - so it gates on the failed step, naming both: "
              "%r" % ((coderr, rr_tests("P1.4").get("gate"),
                       [ln for ln in txtrr.splitlines()
                        if "names each" in ln]),),
              coderr == 0
              and rr_tests("P1.4").get("gate") == ["test"]
              and rr_tests("P1.4").get("gateBasis")
              == "failing-from-run:RUN-ROOT"
              and "names each of backend/tests/test_root.py, "
                  "tests/test_root.py" in txtrr)

        coderr, txtrr = run(
            ["add", "Fix one of two", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-PART",
             "--tests-add", "backend/tests/test_part.py: the case it writes"])
        check("ff13 ONE UNRESOLVED SUITE REFUSES THEM ALL: a run naming one "
              "pinnable suite and one ambiguous one narrows to NEITHER - a "
              "gate over the pinnable one alone could pass while the other "
              "failure never runs: %r"
              % ((coderr, rr_tests("P1.5").get("gate"),
                  rr_tests("P1.5").get("gateBasis")),),
              coderr == 0
              and rr_tests("P1.5").get("gate") == ["test"]
              and rr_tests("P1.5").get("gateBasis")
              == "failing-from-run:RUN-PART"
              and "names each of" in txtrr
              and "test_old.py" not in " ".join(
                  rr_tests("P1.5").get("gate") or []))

        coderr, txtrr = run(
            ["add", "Fix from a literal step", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-STEP",
             "--files", "backend/a.py",
             "--tests-add", "backend/tests/test_step.py: the case it writes"])
        check("ff15 THE FAILURE STAYS IN THE GATE: a task with tests.add AND "
              "files, from a run whose failed step ran a literal command and "
              "named an unpinnable suite, is gated on THAT step's recorded "
              "entry - not its own paths, and not the phase's `test`: %r"
              % ((coderr, rr_tests("P1.6").get("gate"),
                  rr_tests("P1.6").get("gateBasis")),),
              coderr == 0
              and rr_tests("P1.6").get("gate") == [rr_step_entry]
              and rr_tests("P1.6").get("gateBasis")
              == "failing-from-run:RUN-STEP"
              and "(%s)" % (rr_step_entry,) in txtrr)

        coderr, txtrr = run(
            ["add", "Fix from an absolute path inside", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-ABSIN"])
        check("ff16 an ABSOLUTE spelling inside the project is written "
              "relative to it - no machine path reaches the plan: %r"
              % ((coderr, rr_tests("P1.7").get("gate")),),
              coderr == 0
              and rr_tests("P1.7").get("gate")
              == ["python3 -m pytest backend/tests/test_old.py"]
              and rr_proj not in " ".join(rr_tests("P1.7").get("gate") or []))

        coderr, txtrr = run(
            ["add", "Fix from an absolute path outside", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-ABSOUT"])
        check("ff17 an ABSOLUTE spelling OUTSIDE the project is refused with "
              "the reason and gates on the failed step - the file exists, so "
              "only where it lies can refuse it: %r"
              % ((coderr, rr_tests("P1.8").get("gate"),
                  [ln for ln in txtrr.splitlines() if "outside" in ln]),),
              coderr == 0
              and rr_tests("P1.8").get("gate") == ["test"]
              and "lies outside the project" in txtrr
              and rr_outside not in " ".join(
                  rr_tests("P1.8").get("gate") or []))

        coderr, txtrr = run(
            ["add", "Fix from a dot-slash spelling", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-DOT"])
        check("ff18 `./test_old.py` is normalized before the resolver reads "
              "it, and pins the one tracked path it names: %r"
              % ((coderr, rr_tests("P1.9").get("gate")),),
              coderr == 0
              and rr_tests("P1.9").get("gate")
              == ["python3 -m pytest backend/tests/test_old.py"])

        # ---- a failed step with NO recorded `name` -------------------------
        # Nothing names the entry that ran the failure, so the gate is the
        # phase's testGate, wide - the gate the run was measured against -
        # and only a phase with no testGate falls to the ordinary arms.
        for rr_phase, rr_id in (("P1", "RUN-NONAME"), ("P2", "RUN-NONAME2")):
            _ff_ev.append_row(rr_proj, {
                "v": 1, "runId": rr_id, "ts": "2026-09-01T00:00:00Z",
                "scope": "phase", "phaseId": rr_phase, "status": "failed",
                "steps": [{"exit": 1, "failingSuites": ["test_dup.py"],
                           "failingSuitesBasis": rr_named}]})
        coderr, txtrr = run(
            ["add", "Fix from a nameless step", "--phase", "P1",
             "--project-dir", rr_proj, "--failing-from", "RUN-NONAME",
             "--tests-add", "backend/tests/test_nn.py: the case it writes"])
        coden2, txtn2 = run(
            ["add", "Fix from a nameless step, bare phase", "--phase", "P2",
             "--project-dir", rr_proj, "--failing-from", "RUN-NONAME2",
             "--tests-add", "backend/tests/test_nn2.py: the case it writes"])
        check("ff20 a failed step with no recorded name and an unpinnable "
              "suite gates on the phase's testGate, wide, saying so - not on "
              "this task's tests.add; with no testGate either, the ordinary "
              "arms answer, the reason still printed first: %r"
              % ((coderr, rr_tests("P1.10").get("gate"),
                  rr_tests("P1.10").get("gateBasis"),
                  [ln for ln in txtrr.splitlines() if "  gate: " in ln],
                  coden2,
                  (task_in(rr_mp, "P2.2") or {}).get("tests", {}).get("gate"),
                  (task_in(rr_mp, "P2.2") or {}).get("tests", {}).get(
                      "gateBasis")),),
              coderr == 0
              and rr_tests("P1.10").get("gate") == ["test"]
              and rr_tests("P1.10").get("gateBasis")
              == "failing-from-run:RUN-NONAME"
              and "recorded no gate entry for its failed step" in txtrr
              and coden2 == 0
              and (task_in(rr_mp, "P2.2") or {}).get("tests", {}).get("gate")
              == ["python3 -m pytest backend/tests/test_nn2.py"]
              and (task_in(rr_mp, "P2.2") or {}).get("tests", {}).get(
                  "gateBasis") == "tests.add"
              and "names each of" in txtn2 and "so falling through" in txtn2)

        # A NEWLINE IN A TRACKED PATH, at the unit level: a file name holding
        # one cannot be created on every platform CI runs on, so the listing
        # is handed in. It is the ONLY suffix match, so the resolver would
        # answer with it and nothing but the control-character refusal
        # keeps it out of a one-line shell gate.
        _nl_path = "nl" + chr(10) + "dir/test_nl.py"

        def _nl_listing(_root, _args, timeout=60):
            return 0, "backend/a.py\0%s\0" % (_nl_path,), ""
        _nl_got = M._root_spelled_suites(["test_nl.py"], rr_proj,
                                         run=_nl_listing)
        check("ff19 a tracked candidate holding a newline is refused, never "
              "returned into a gate: %r" % (_nl_got,),
              _nl_got[0] is None
              and "control character" in (_nl_got[1] or "")
              and chr(10) not in (_nl_got[1] or ""))

        # ---- git CANNOT list, so there is no candidate set at all -----------
        # `ff_proj` is not a git repository. A spelling that is not on disk
        # there must gate on the failed step naming the listing failure - an
        # unlisted tree read as an empty one would print a "no candidate"
        # reason that blames the spelling for what git never said. The spy on
        # `_git` counts `ls-files` calls: each add asks once, and a suite
        # that exists from the root is kept as written when git cannot
        # answer, since nothing is left that could show it a twin.
        _ff_ev.append_row(ff_proj, {
            "v": 1, "runId": "RUN-NOGIT", "ts": "2026-09-01T00:30:00Z",
            "scope": "phase", "phaseId": "P1", "status": "failed",
            "steps": [{"name": "test", "exit": 1,
                       "failingSuites": ["gone.test.ts"],
                       "failingSuitesBasis": ("the 1 suite file(s) vitest "
                                              "named as failing, read from "
                                              "vitest's FAIL <file> line(s)")}]})
        _ls_calls = []
        _ls_real = M._worktrees._git

        def _ls_spy(git_root, args, timeout=60):
            if list(args)[:1] == ["ls-files"]:
                _ls_calls.append(git_root)
            return _ls_real(git_root, args, timeout=timeout)
        M._worktrees._git = _ls_spy
        try:
            codeng, txtng = run(
                ["add", "Fix where git cannot list", "--phase", "P1",
                 "--project-dir", ff_proj, "--failing-from", "RUN-NOGIT",
                 "--tests-add", "src/nogit.test.ts: the case it writes"])
            _ls_after_nogit = len(_ls_calls)
            codeon, _txton = run(
                ["add", "Fix a suite on disk", "--phase", "P1",
                 "--project-dir", ff_proj, "--failing-from", "RUN-VITEST"])
        finally:
            M._worktrees._git = _ls_real
        check("ff14 FAIL LOUD: where git cannot list the tracked files, a "
              "spelling not on disk gates on the failed step's entry with "
              "the LISTING failure named, and no gate entry carries the "
              "unresolved spelling; a suite that exists from the root is "
              "then kept as written, git asked once per add: %r"
              % ((codeng, ff_tests("P1.7").get("gate"),
                  ff_tests("P1.7").get("gateBasis"),
                  [ln for ln in txtng.splitlines() if "could not be listed"
                   in ln], _ls_calls, codeon,
                  ff_tests("P1.8").get("gate")),),
              codeng == 0
              and ff_tests("P1.7").get("gate") == ["test"]
              and ff_tests("P1.7").get("gateBasis")
              == "failing-from-run:RUN-NOGIT"
              and "gone.test.ts is not on disk from the project root, and "
                  "the tracked files could not be listed (git ls-files: "
                  in txtng
              and "no candidate path" not in txtng
              and "gone.test.ts" not in " ".join(
                  ff_tests("P1.7").get("gate") or [])
              and _ls_after_nogit == 1
              and codeon == 0 and len(_ls_calls) == 2
              and ff_tests("P1.8").get("gate")
              == ["lint", "vitest run src/cart.test.ts"])

        # ---- (cp) couple / uncouple: `meta.coupling`, an index-only write --
        import _evidence_io as _cp_ev

        def cp_meta(mpath):
            try:
                return _mio.load_manifest(mpath).get("meta") or {}
            except Exception:
                return {}

        def cp_coupling(mpath):
            return cp_meta(mpath).get("coupling") or []

        def cp_journal(project, action):
            """Every row of `action` the journal actually holds - the same
            read every other verb's case in this file takes (`task.scope`,
            `phase.cancel`), so a coupling row is read the way the rest of
            the trail already is rather than by a second route."""
            jmod = _panel_write._journalmod()
            return [r for r in (jmod.read_all(project) if jmod else [])
                   if r.get("action") == action]

        def cp_repo(name, manifest):
            """A fixture whose project really IS a git repository with a
            commit - `pd_repo`'s own reason: the question `couple` asks is
            whether git resolves a SHA, and a stub would answer for a third
            party neither the suite nor the code asked."""
            proj, mpath = mk(name, manifest, git=True)
            for argv in (["config", "user.email", "t@example.com"],
                         ["config", "user.name", "Test User"],
                         ["add", "-A"], ["commit", "-qm", "seed"]):
                subprocess.run(["git", "-C", proj] + argv,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            head = subprocess.run(["git", "-C", proj, "rev-parse", "HEAD"],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
            return proj, mpath, head.stdout.decode("utf-8", "replace").strip()

        cp_proj, cp_mp = mk("cp-couple", base_manifest())
        _cp_ev.append_row(cp_proj, {
            "v": 1, "runId": "RUN-CP1", "ts": "2026-09-01T00:00:00Z",
            "scope": "phase", "phaseId": "P2", "status": "failed", "steps": []})

        codecp, txtcp = run(
            ["couple", "--test", "tests/test_a.py",
             "--sources", "src/a.ts,src/b.ts",
             "--basis-run", "RUN-CP1", "--basis-head", "deadbeef",
             "--phases", "P2", "--project-dir", cp_proj])
        check("cp1 RED-FIRST: `couple` is an unknown verb on current code, "
              "so this must exit 2 (usage) rather than write an entry -- "
              "green here means `meta.coupling` can only be written by hand: "
              "%r" % ((codecp, cp_coupling(cp_mp)),),
              codecp == 0
              and cp_coupling(cp_mp) == [
                  {"test": "tests/test_a.py",
                   "sources": ["src/a.ts", "src/b.ts"],
                   "basis": {"runId": "RUN-CP1", "head": "deadbeef",
                            "phases": ["P2"]},
                   "learnedAt": cp_coupling(cp_mp)[0]["learnedAt"]}])
        _cp_learned_at = cp_coupling(cp_mp)[0]["learnedAt"] if cp_coupling(cp_mp) else None
        _cp_learned_rows = cp_journal(cp_proj, "coupling.learned")
        # `details.to` is a LIST, so `_journal_io._clip` spells it as JSON
        # text - decoded rather than compared as text, `jf_val`'s own reason
        # two groups over.
        _cp_learned_det = (_cp_learned_rows[0].get("details") or {}
                           if _cp_learned_rows else {})
        check("cp1b `couple` writes exactly one `coupling.learned` journal "
              "row, carrying {field, to, runId, commit} - read the way "
              "every other verb's case in this file reads its own action: "
              "%r" % (_cp_learned_rows,),
              len(_cp_learned_rows) == 1
              and _cp_learned_det.get("field") == "tests/test_a.py"
              and json.loads(_cp_learned_det.get("to") or "null")
              == ["src/a.ts", "src/b.ts"]
              and _cp_learned_det.get("runId") == "RUN-CP1"
              and _cp_learned_det.get("commit") == "deadbeef")

        # ---- MUTATION GUARD: coupling the SAME test twice UNIONS the -------
        # sources and keeps the first `learnedAt` -- an implementation that
        # OVERWRITES the entry instead of widening it would drop the first
        # source and/or move `learnedAt`, and this is the case that catches it.
        codecp2, txtcp2 = run(
            ["couple", "--test", "tests/test_a.py",
             "--sources", "src/c.ts",
             "--basis-run", "RUN-CP1", "--basis-head", "deadbeef",
             "--project-dir", cp_proj])
        check("cp2 MUTATION GUARD: a second `couple` on the same test widens "
              "`sources` (union, order-preserving) and keeps the FIRST "
              "`learnedAt` rather than replacing the entry: %r"
              % (cp_coupling(cp_mp),),
              codecp2 == 0 and len(cp_coupling(cp_mp)) == 1
              and cp_coupling(cp_mp)[0]["sources"]
              == ["src/a.ts", "src/b.ts", "src/c.ts"]
              and cp_coupling(cp_mp)[0]["learnedAt"] == _cp_learned_at)

        # ---- MUTATION GUARD: a re-couple does not pin `basis` -- a THIRD --
        # `couple` on the same test, passing a DIFFERENT --basis-run,
        # --basis-head and --phases, must still keep the entry's basis
        # exactly as the first call wrote it: `basis` is what taught the
        # coupling, and only the first teaching counts.
        _cp_ev.append_row(cp_proj, {
            "v": 1, "runId": "RUN-CP2", "ts": "2026-09-01T00:30:00Z",
            "scope": "phase", "phaseId": "P3", "status": "failed", "steps": []})
        codecp2b, txtcp2b = run(
            ["couple", "--test", "tests/test_a.py",
             "--sources", "src/d.ts",
             "--basis-run", "RUN-CP2", "--basis-head", "cafebabe",
             "--phases", "P3", "--project-dir", cp_proj])
        check("cp2b MUTATION GUARD: a re-couple with a DIFFERENT basis "
              "widens `sources` again but keeps the FIRST call's basis "
              "{runId, head, phases} - an implementation that overwrote "
              "basis on every call would move it here: %r"
              % (cp_coupling(cp_mp),),
              codecp2b == 0 and len(cp_coupling(cp_mp)) == 1
              and cp_coupling(cp_mp)[0]["sources"]
              == ["src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts"]
              and cp_coupling(cp_mp)[0]["basis"] == {
                  "runId": "RUN-CP1", "head": "deadbeef", "phases": ["P2"]}
              and cp_coupling(cp_mp)[0]["learnedAt"] == _cp_learned_at)

        # ---- ALLOW CASE: a runId the ledger lacks is refused, exit 2 -------
        codecp3, txtcp3 = run(
            ["couple", "--test", "tests/test_b.py",
             "--sources", "src/z.ts", "--basis-run", "NO-SUCH-RUN",
             "--basis-head", "deadbeef", "--project-dir", cp_proj])
        check("cp3 ALLOW CASE: --basis-run naming a run the evidence ledger "
              "does not hold is refused exit 2, and nothing is written -- a "
              "coupling says what taught it: %r" % (txtcp3[:140],),
              codecp3 == 2 and "no run with this id" in txtcp3
              and len(cp_coupling(cp_mp)) == 1)

        # ---- ALLOW CASE: --test naming no real path is refused -------------
        codecp4, txtcp4 = run(
            ["couple", "--test", "not a path at all",
             "--sources", "src/z.ts", "--basis-run", "RUN-CP1",
             "--basis-head", "deadbeef", "--project-dir", cp_proj])
        check("cp4 ALLOW CASE: --test that neither `tests_add_path` nor "
              "`is_suite_path` accepts is refused exit 2: %r" % (txtcp4[:140],),
              codecp4 == 2 and len(cp_coupling(cp_mp)) == 1)

        # ---- (cp) uncouple -------------------------------------------------
        codecp5, txtcp5 = run(
            ["uncouple", "--test", "tests/test_a.py",
             "--project-dir", cp_proj])
        check("cp5 `uncouple --test` drops the entry it names: %r"
              % (cp_coupling(cp_mp),),
              codecp5 == 0 and cp_coupling(cp_mp) == [])
        _cp_dropped_rows = cp_journal(cp_proj, "coupling.dropped")
        _cp_dropped_det = (_cp_dropped_rows[0].get("details") or {}
                           if _cp_dropped_rows else {})
        check("cp5b `uncouple` writes exactly one `coupling.dropped` "
              "journal row, carrying {field, from}: %r" % (_cp_dropped_rows,),
              len(_cp_dropped_rows) == 1
              and _cp_dropped_det.get("field") == "tests/test_a.py"
              and json.loads(_cp_dropped_det.get("from") or "null")
              == ["src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts"])

        # ---- ALLOW CASE: uncoupling an unknown test is refused, exit 2 -----
        codecp6, txtcp6 = run(
            ["uncouple", "--test", "tests/test_a.py",
             "--project-dir", cp_proj])
        check("cp6 RED-FIRST/ALLOW CASE: `uncouple` of a test carrying no "
              "coupling entry is refused exit 2 - a no-op reporting success "
              "would hide that nothing was there to drop: %r" % (txtcp6[:140],),
              codecp6 == 2 and "carries no meta.coupling entry" in txtcp6)

        # ---- (cc) couple --caught: a coupling that earned its place --------
        # `lastCaught` is the ts of a third-place (scope `full`) run whose
        # runner NAMED the coupled test as failing. Without a writer, every
        # coupling ages from `learnedAt` as though it never caught anything.
        cc_proj, cc_mp = mk("cc-caught", base_manifest())
        _cc_named = ("the 1 suite file(s) pytest named as failing, read "
                     "from pytest's FAILED <path> line(s)")

        def cc_row(run_id, ts, scope, suites, basis, **extra):
            step = {"name": "test", "exit": 1, "failingSuites": suites,
                    "failingSuitesBasis": basis}
            step.update(extra)
            row = {"v": 1, "runId": run_id, "ts": ts, "scope": scope,
                   "status": "failed", "steps": [step]}
            if scope == "phase":
                row["phaseId"] = "P2"
            _cp_ev.append_row(cc_proj, row)

        def cc_entry():
            return next((e for e in cp_coupling(cc_mp)
                         if e.get("test") == "tests/test_c.py"), None)

        cc_row("RUN-CC-MISS", "2026-09-01T00:00:00Z", "phase",
               ["tests/test_c.py"], _cc_named)
        codecc0, _ = run(
            ["couple", "--test", "tests/test_c.py", "--sources", "src/c.ts",
             "--basis-run", "RUN-CC-MISS", "--basis-head", "deadbeef",
             "--project-dir", cc_proj])
        _cc_first = dict(cc_entry() or {})
        check("cc0 a coupling first written from a miss carries no "
              "lastCaught: %r" % ((codecc0, _cc_first),),
              codecc0 == 0 and _cc_first.get("test") == "tests/test_c.py"
              and "lastCaught" not in _cc_first)

        cc_row("RUN-CC-FULL", "2026-09-03T00:00:00Z", "full",
               ["tests/test_c.py"], _cc_named)
        codecc1, txtcc1 = run(
            ["couple", "--test", "tests/test_c.py", "--caught", "RUN-CC-FULL",
             "--project-dir", cc_proj])
        _cc_after = dict(cc_entry() or {})
        _cc_rows = cp_journal(cc_proj, "coupling.caught")
        _cc_det = (_cc_rows[0].get("details") or {}) if _cc_rows else {}
        check("cc1 RED-FIRST: `couple --test <coupled> --caught <runId>` on a "
              "full row whose runner NAMED the test as failing sets "
              "lastCaught to that row's ts, changes nothing else on the "
              "entry, and writes exactly one `coupling.caught` journal row - "
              "on current code `--caught` is not a flag at all: %r"
              % ((codecc1, txtcc1[:160], _cc_after, _cc_rows),),
              codecc1 == 0
              and _cc_after.get("lastCaught") == "2026-09-03T00:00:00Z"
              and dict((k, v) for k, v in _cc_after.items()
                       if k != "lastCaught") == _cc_first
              and len(_cc_rows) == 1
              and _cc_det.get("field") == "tests/test_c.py"
              and _cc_det.get("runId") == "RUN-CC-FULL"
              and _cc_det.get("to") == "2026-09-03T00:00:00Z")

        # ---- MUTATION GUARD: a TAIL basis is not a runner naming a test ----
        cc_row("RUN-CC-TAIL", "2026-09-04T00:00:00Z", "full",
               ["tests/test_c.py"],
               "no runner this gate can count recognised; the last lines of "
               "its output are kept instead")
        codecc2, txtcc2 = run(
            ["couple", "--test", "tests/test_c.py", "--caught", "RUN-CC-TAIL",
             "--project-dir", cc_proj])
        check("cc2 MUTATION GUARD: a full row whose failing suites came off a "
              "TAIL, not a runner's own summary, is refused exit 2 naming the "
              "run, and lastCaught stays where cc1 put it: %r"
              % ((codecc2, txtcc2[:200], cc_entry()),),
              codecc2 == 2 and "RUN-CC-TAIL" in txtcc2
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00Z"
              and len(cp_journal(cc_proj, "coupling.caught")) == 1)

        # ---- ALLOW CASES: --caught never creates, and reads only `full` ----
        cc_row("RUN-CC-OTHER", "2026-09-05T00:00:00Z", "full",
               ["tests/test_d.py"], _cc_named)
        codecc3, txtcc3 = run(
            ["couple", "--test", "tests/test_d.py", "--caught",
             "RUN-CC-OTHER", "--project-dir", cc_proj])
        check("cc3 ALLOW CASE: --caught on a test that is NOT coupled is "
              "refused exit 2 and creates no entry - a catch is recorded "
              "against a coupling, never in place of one: %r"
              % ((codecc3, txtcc3[:200], cp_coupling(cc_mp)),),
              codecc3 == 2 and "carries no meta.coupling entry" in txtcc3
              and [e.get("test") for e in cp_coupling(cc_mp)]
              == ["tests/test_c.py"])
        cc_row("RUN-CC-PHASE", "2026-09-06T00:00:00Z", "phase",
               ["tests/test_c.py"], _cc_named)
        codecc4, txtcc4 = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-PHASE", "--project-dir", cc_proj])
        check("cc4 ALLOW CASE: a phase-scope row naming the test is refused "
              "exit 2, naming its scope - only a third-place run is a catch "
              "the coupling itself earned: %r" % ((codecc4, txtcc4[:200]),),
              codecc4 == 2 and "'phase'" in txtcc4
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00Z")
        codecc5, txtcc5 = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-OTHER", "--project-dir", cc_proj])
        check("cc5 ALLOW CASE: a full row that named OTHER suites is refused "
              "exit 2 - it caught something, not this test: %r"
              % ((codecc5, txtcc5[:200]),),
              codecc5 == 2 and "tests/test_c.py" in txtcc5
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00Z")
        cc_row("RUN-CC-MUTED", "2026-09-07T00:00:00Z", "full",
               ["tests/test_c.py"], _cc_named,
               muted=[{"test": "tests/test_c.py", "bugId": "BUG-1",
                       "until": "2999-01-01"}])
        codecc6, txtcc6 = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-MUTED", "--project-dir", cc_proj])
        check("cc6 ALLOW CASE: a full row whose step naming the test was "
              "MUTED is refused exit 2 - a quarantined failure is not a "
              "catch: %r" % ((codecc6, txtcc6[:200]),),
              codecc6 == 2
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00Z")
        codecc7, txtcc7 = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-FULL", "--sources", "src/z.ts",
             "--project-dir", cc_proj])
        check("cc7 ALLOW CASE: --caught with --sources is refused exit 2 and "
              "the sources stay as they were - recording a catch never "
              "changes what the test is coupled to: %r"
              % ((codecc7, txtcc7[:200], cc_entry()),),
              codecc7 == 2 and "--sources" in txtcc7
              and (cc_entry() or {}).get("sources") == ["src/c.ts"])
        codecc8, txtcc8 = run(
            ["couple", "--test", "tests/test_c.py", "--caught", "NO-SUCH-RUN",
             "--project-dir", cc_proj])
        check("cc8 ALLOW CASE: an unknown runId is refused exit 2: %r"
              % ((codecc8, txtcc8[:200]),),
              codecc8 == 2 and "no run with this id" in txtcc8)
        cc_row("RUN-CC-OLD", "2026-09-02T00:00:00Z", "full",
               ["tests/test_c.py"], _cc_named)
        codecc9, txtcc9 = run(
            ["couple", "--test", "tests/test_c.py", "--caught", "RUN-CC-OLD",
             "--project-dir", cc_proj])
        check("cc9 a catch OLDER than the recorded lastCaught writes nothing "
              "and adds no journal row, but exits 0 saying lastCaught "
              "already records a newer catch - newest only, and an "
              "out-of-order import is not an error: %r"
              % ((codecc9, txtcc9[:200], cc_entry()),),
              codecc9 == 0 and "already records" in txtcc9
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00Z"
              and len(cp_journal(cc_proj, "coupling.caught")) == 1)
        codecc10, txtcc10 = run(
            ["couple", "--test", "tests/test_c.py", "--caught", "RUN-CC-FULL",
             "--project-dir", cc_proj])
        check("cc10 the SAME run replayed is idempotent: exit 0, nothing "
              "written, no second journal row: %r"
              % ((codecc10, txtcc10[:200], cc_entry()),),
              codecc10 == 0 and "already records" in txtcc10
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00Z"
              and len(cp_journal(cc_proj, "coupling.caught")) == 1)

        # ---- MUTATION GUARD: moments are compared, never text ---------------
        # `2026-09-03T01:00:00+02:00` sorts AFTER `2026-09-03T00:00:00Z` as
        # text and is an hour BEFORE it as a moment; `...00.5Z` sorts before
        # `...00Z` as text ('.' < 'Z') and is half a second after it.
        cc_row("RUN-CC-OFFSET", "2026-09-03T01:00:00+02:00", "full",
               ["tests/test_c.py"], _cc_named)
        codecc11, txtcc11 = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-OFFSET", "--project-dir", cc_proj])
        check("cc11 MUTATION GUARD: a row whose ts is LATER as text but "
              "EARLIER as a moment (an offset against Z) writes nothing: %r"
              % ((codecc11, txtcc11[:200], cc_entry()),),
              codecc11 == 0 and "already records" in txtcc11
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00Z"
              and len(cp_journal(cc_proj, "coupling.caught")) == 1)
        cc_row("RUN-CC-FRAC", "2026-09-03T00:00:00.5Z", "full",
               ["tests/test_c.py"], _cc_named)
        codecc12, txtcc12 = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-FRAC", "--project-dir", cc_proj])
        check("cc12 MUTATION GUARD: a row whose ts is EARLIER as text but "
              "LATER as a moment (a fraction against Z) is written: %r"
              % ((codecc12, txtcc12[:200], cc_entry()),),
              codecc12 == 0
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00.5Z"
              and len(cp_journal(cc_proj, "coupling.caught")) == 2)

        # ---- ALLOW CASE: a ts no parser reads is refused, naming it --------
        # Written as a raw ledger line, so no writer's own normalising can
        # repair the value before the verb sees it.
        with open(_cp_ev.ledger_files(cc_proj)[-1], "a",
                  encoding="utf-8") as _cc_fh:
            _cc_fh.write(json.dumps({
                "v": 1, "runId": "RUN-CC-BADTS", "ts": "last tuesday",
                "scope": "full", "status": "failed",
                "steps": [{"name": "test", "exit": 1,
                           "failingSuites": ["tests/test_c.py"],
                           "failingSuitesBasis": _cc_named}]}) + "\n")
        codecc13, txtcc13 = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-BADTS", "--project-dir", cc_proj])
        check("cc13 ALLOW CASE: a row whose ts does not parse as a moment is "
              "refused exit 2, naming the ts: %r"
              % ((codecc13, txtcc13[:200], cc_entry()),),
              codecc13 == 2 and "last tuesday" in txtcc13
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00.5Z")

        # ---- ALLOW CASE: a torn ledger line is named, never silence --------
        # A run not found among the READABLE rows may sit on the line the read
        # lost, so both lookups say which file could not be read in full.
        tl_proj, tl_mp = mk("cc-torn", base_manifest())
        _cp_ev.append_row(tl_proj, {
            "v": 1, "runId": "RUN-TL", "ts": "2026-09-01T00:00:00Z",
            "scope": "phase", "phaseId": "P2", "status": "failed",
            "steps": []})
        codetl0, _ = run(
            ["couple", "--test", "tests/test_t.py", "--sources", "src/t.ts",
             "--basis-run", "RUN-TL", "--basis-head", "deadbeef",
             "--project-dir", tl_proj])
        _tl_ledger = _cp_ev.ledger_files(tl_proj)[-1]
        with open(_tl_ledger, "a", encoding="utf-8") as _tl_fh:
            _tl_fh.write('{"v": 1, "runId": "RUN-TL-LOST", "ts": "2026-09\n')
        _tl_name = os.path.basename(_tl_ledger)
        codetl1, txttl1 = run(
            ["couple", "--test", "tests/test_t.py", "--caught", "RUN-TL-LOST",
             "--project-dir", tl_proj])
        codetl2, txttl2 = run(
            ["couple", "--test", "tests/test_u.py", "--sources", "src/u.ts",
             "--basis-run", "RUN-TL-LOST", "--basis-head", "deadbeef",
             "--project-dir", tl_proj])
        check("cc14 ALLOW CASE: with a torn ledger line, a run not found is "
              "refused exit 2 by BOTH --caught and --basis-run, each naming "
              "the file that could not be read in full: %r"
              % ((codetl0, codetl1, txttl1[:240], codetl2, txttl2[:240]),),
              codetl0 == 0
              and codetl1 == 2 and _tl_name in txttl1
              and "could not be read" in txttl1
              and codetl2 == 2 and _tl_name in txttl2
              and "could not be read" in txttl2
              and [e.get("test") for e in cp_coupling(tl_mp)]
              == ["tests/test_t.py"])

        # ---- ONE READING, the --caught half: the spy answers WITHOUT the ---
        # coupled test, so a verb reading its own copy would accept a row that
        # really names it - the refusal has to come from the shared function.
        cc_row("RUN-CC-SPY", "2026-09-09T00:00:00Z", "full",
               ["tests/test_c.py"], _cc_named)
        _sp_calls2 = []

        def _sp_spy2(steps):
            _sp_calls2.append(steps)
            return ["tests/other.py"]
        _cp_ev.named_failing_suites = _sp_spy2
        try:
            codesp2, txtsp2 = run(
                ["couple", "--test", "tests/test_c.py", "--caught",
                 "RUN-CC-SPY", "--project-dir", cc_proj])
        finally:
            _cp_ev.named_failing_suites = _sp_real
        check("cc15 `--caught` reads the catch through "
              "`_evidence_io.named_failing_suites`, handed the row's steps, "
              "and refuses when IT does not name the test: %r"
              % ((codesp2, txtsp2[:200], len(_sp_calls2)),),
              codesp2 == 2 and len(_sp_calls2) == 1
              and isinstance(_sp_calls2[0], list)
              and _sp_calls2[0][0].get("failingSuites") == ["tests/test_c.py"]
              and "tests/other.py" in txtsp2
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-03T00:00:00.5Z")

        # ---- a runner naming the suite relative to its own directory -------
        # `_evidence_io.listed_by` is the one reading of "this suite is one of
        # those": equal, or either a `/`-bounded path suffix of the other.
        cc_row("RUN-CC-REL", "2026-09-10T00:00:00Z", "full",
               ["test_c.py"], _cc_named)
        _cc_caught_before = len(cp_journal(cc_proj, "coupling.caught"))
        codecc16, txtcc16 = run(
            ["couple", "--test", "tests/test_c.py", "--caught", "RUN-CC-REL",
             "--project-dir", cc_proj])
        check("cc16 RED-FIRST: a full row whose runner named test_c.py - the "
              "coupled tests/test_c.py, relative to the runner's own "
              "directory - is a catch, recorded under the PLAN'S key and no "
              "other: %r" % ((codecc16, txtcc16[:200], cp_coupling(cc_mp)),),
              codecc16 == 0
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-10T00:00:00Z"
              and [e.get("test") for e in cp_coupling(cc_mp)]
              == ["tests/test_c.py"]
              and len(cp_journal(cc_proj, "coupling.caught"))
              == _cc_caught_before + 1)
        # ALLOW CASE: the same basename under ANOTHER directory is neither
        # equal to the key nor a `/`-bounded suffix of it, either way round,
        # so `listed_by` says it is a different suite - the mutation
        # 'compare basenames' is what this is here to turn red.
        cc_row("RUN-CC-ELSEWHERE", "2026-09-11T00:00:00Z", "full",
               ["other/test_c.py"], _cc_named)
        codecc17, txtcc17 = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-ELSEWHERE", "--project-dir", cc_proj])
        check("cc17 ALLOW CASE: a full row naming other/test_c.py - the same "
              "basename in another directory - is refused exit 2, the "
              "refusal names what the runner named, and lastCaught stays "
              "where cc16 put it: %r" % ((codecc17, txtcc17[:240]),),
              codecc17 == 2 and "other/test_c.py" in txtcc17
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-10T00:00:00Z"
              and len(cp_journal(cc_proj, "coupling.caught"))
              == _cc_caught_before + 1)

        # ---- one bare name, two coupled suites carrying it -----------------
        # `test_c.py` is listed by BOTH pkg_a/ and pkg_b/tests/test_c.py, so
        # the run cannot say which one failed; crediting either would reset
        # the age of a coupling that caught nothing.
        am_manifest = base_manifest()
        am_manifest["meta"]["coupling"] = [
            {"test": test, "sources": [src],
             "basis": {"runId": "RUN-AM-OLD", "head": "deadbeef",
                       "phases": ["P2"]},
             "learnedAt": "2026-01-01T00:00:00Z"}
            for test, src in (("pkg_a/tests/test_c.py", "pkg_a/c.ts"),
                              ("pkg_b/tests/test_c.py", "pkg_b/c.ts"))]
        am_proj, am_mp = mk("cc-ambiguous", am_manifest)
        _cp_ev.append_row(am_proj, {
            "v": 1, "runId": "RUN-AM", "ts": "2026-09-12T00:00:00Z",
            "scope": "full", "status": "failed",
            "steps": [{"name": "test", "exit": 1,
                       "failingSuites": ["test_c.py"],
                       "failingSuitesBasis": _cc_named}]})
        codecc18, txtcc18 = run(
            ["couple", "--test", "pkg_a/tests/test_c.py", "--caught",
             "RUN-AM", "--project-dir", am_proj])
        check("cc18 RED-FIRST: --caught for pkg_a/tests/test_c.py off a run "
              "that named only test_c.py, while pkg_b/tests/test_c.py is "
              "coupled too, is refused exit 2 naming both keys, and neither "
              "lastCaught moves: %r"
              % ((codecc18, txtcc18[-320:], cp_coupling(am_mp)),),
              codecc18 == 2
              and "pkg_a/tests/test_c.py" in txtcc18
              and "pkg_b/tests/test_c.py" in txtcc18
              and not any(e.get("lastCaught") for e in cp_coupling(am_mp))
              and cp_journal(am_proj, "coupling.caught") == [])

        # ---- a row listing the suite as its OWN miss is no catch of it -----
        # `full-gate.py` credits no catch off such a row; the verb must refuse
        # it by the same reading (`_evidence_io.own_miss`), whichever of the
        # runner's spelling or the plan's key the row recorded the miss under.
        _cc_before_own = len(cp_journal(cc_proj, "coupling.caught"))
        for _own_id, _own_spelled in (("RUN-CC-OWN", "tests/test_c.py"),
                                      ("RUN-CC-OWN-REL", "test_c.py")):
            _cp_ev.append_row(cc_proj, {
                "v": 1, "runId": _own_id, "ts": "2026-09-13T00:00:00Z",
                "scope": "full", "status": "failed",
                "steps": [{"name": "test", "exit": 1,
                           "failingSuites": [_own_spelled],
                           "failingSuitesBasis": _cc_named}],
                "selectionMiss": [{"test": _own_spelled, "phases": ["P2"],
                                   "sources": ["src/c.ts"]}]})
        codecc19, txtcc19 = run(
            ["couple", "--test", "tests/test_c.py", "--caught", "RUN-CC-OWN",
             "--project-dir", cc_proj])
        codecc19r, txtcc19r = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-OWN-REL", "--project-dir", cc_proj])
        check("cc19 RED-FIRST: --caught off a full row whose own "
              "selectionMiss lists the suite - under the plan's key or the "
              "runner's own spelling - is refused exit 2, saying so, and "
              "lastCaught stays where cc16 put it: %r"
              % ((codecc19, txtcc19[:240], codecc19r, txtcc19r[:240]),),
              codecc19 == 2 and "its own selection miss" in txtcc19
              and codecc19r == 2 and "its own selection miss" in txtcc19r
              and (cc_entry() or {}).get("lastCaught")
              == "2026-09-10T00:00:00Z"
              and len(cp_journal(cc_proj, "coupling.caught"))
              == _cc_before_own)

        # ---- a date-only ts is placed where the ledger places it -----------
        # `_evidence_io.stamp_moment` reads `2026-09-20` as that day's start,
        # the reading the ledger orders its rows by.
        cc_row("RUN-CC-DAY", "2026-09-20", "full", ["tests/test_c.py"],
               _cc_named)
        codecc20, txtcc20 = run(
            ["couple", "--test", "tests/test_c.py", "--caught", "RUN-CC-DAY",
             "--project-dir", cc_proj])
        cc_row("RUN-CC-DAY-OLD", "2026-09-19", "full", ["tests/test_c.py"],
               _cc_named)
        codecc20b, txtcc20b = run(
            ["couple", "--test", "tests/test_c.py", "--caught",
             "RUN-CC-DAY-OLD", "--project-dir", cc_proj])
        check("cc20 RED-FIRST: a full row stamped with a date alone is a "
              "catch at that day's start (lastCaught 2026-09-20), and an "
              "older date-only row after it writes nothing: %r"
              % ((codecc20, txtcc20[:200], codecc20b, txtcc20b[:200],
                  (cc_entry() or {}).get("lastCaught")),),
              codecc20 == 0 and codecc20b == 0
              and (cc_entry() or {}).get("lastCaught") == "2026-09-20"
              and "nothing written" in txtcc20b)

        # ---- (cp) --basis-head is asked of git, exactly as `done --commit` -
        cp_projg, cp_mpg, cp_head = cp_repo("cp-git", base_manifest())
        _cp_ev.append_row(cp_projg, {
            "v": 1, "runId": "RUN-CPG", "ts": "2026-09-01T01:00:00Z",
            "scope": "phase", "phaseId": "P2", "status": "failed", "steps": []})
        codecp7, txtcp7 = run(
            ["couple", "--test", "tests/test_g.py", "--sources", "src/g.ts",
             "--basis-run", "RUN-CPG", "--basis-head", "0" * 40,
             "--phases", "P2", "--project-dir", cp_projg])
        check("cp7 RED-FIRST/ALLOW CASE: --basis-head naming a SHA git CAN "
              "be asked about and does not have is refused exit 2, nothing "
              "written - the same refusal `done --commit` gives a "
              "fabricated SHA: %r" % (txtcp7[:160],),
              codecp7 == 2 and "0" * 12 in txtcp7
              and cp_coupling(cp_mpg) == [])
        codecp8, txtcp8 = run(
            ["couple", "--test", "tests/test_g.py", "--sources", "src/g.ts",
             "--basis-run", "RUN-CPG", "--basis-head", cp_head,
             "--phases", "P2", "--project-dir", cp_projg])
        check("cp8 ALLOW CASE, the direction cp7 breaks in: the repository's "
              "REAL head is accepted, and a real phase id passes --phases "
              "unchanged: %r" % ((codecp8, cp_coupling(cp_mpg)),),
              codecp8 == 0 and len(cp_coupling(cp_mpg)) == 1
              and cp_coupling(cp_mpg)[0]["basis"] == {
                  "runId": "RUN-CPG", "head": cp_head, "phases": ["P2"]})
        codecp9, txtcp9 = run(
            ["couple", "--test", "tests/test_h.py", "--sources", "src/h.ts",
             "--basis-run", "RUN-CPG", "--basis-head", cp_head,
             "--phases", "P2,P404", "--project-dir", cp_projg])
        check("cp9 RED-FIRST/ALLOW CASE: --phases naming an id the plan "
              "does not hold is refused exit 2, and nothing is added: %r"
              % (txtcp9[:140],),
              codecp9 == 2 and "P404" in txtcp9
              and len(cp_coupling(cp_mpg)) == 1)

        # ---- (ba) bug-add: the bug shape `commands/bug.md` spells, by a verb --
        # The shape is spelled here as a literal, not read off the verb: a
        # case that asked the verb which keys it writes would agree with any
        # verb. The fixture already holds a closed bug with a HIGH number, so
        # an id computed by hand from the list length and the allocator's
        # max+1 answer are different strings.
        BA_KEYS = ["id", "title", "status", "severity", "reportedAt",
                   "reportedBy", "description", "repro", "expected", "actual",
                   "files", "taskId", "fixedIn", "notes"]

        def ba_bugs(mpath):
            try:
                return _mio.load_manifest(mpath).get("bugs")
            except Exception:
                return None

        def ba_bytes(mpath):
            with open(mpath, "rb") as fh:
                return fh.read()

        _ba_fx = base_manifest()
        _ba_fx["bugs"] = [{"id": "BUG-7", "title": "older", "status": "wontfix"}]
        ba_proj, ba_mp = mk("ba-add", _ba_fx)
        _ba_pre = _mio.load_manifest(ba_mp)
        _ba_want_id = M._id_shape.next_bug_id(_ba_pre,
                                              M._mint_suffix(ba_mp, _ba_pre))
        # A doubled space and a trailing one in the operator's words, on the
        # stdin route the prose guard leaves open for exactly such text:
        # stored as typed, not tidied.
        _ba_desc = "Login  crashes on an empty email "
        codeba, txtba = run_on_stdin(
            ["bug-add", "Login crashes", "--severity", "high",
             "--description", "-", "--files", "src/a.ts,src/b.ts",
             "--repro", "submit the form empty", "--expected", "a message",
             "--actual", "a stack trace", "--project-dir", ba_proj],
            _ba_desc + "\n")
        _ba_new = [b for b in (ba_bugs(ba_mp) or []) if b.get("id") != "BUG-7"]
        _ba_bug = _ba_new[0] if len(_ba_new) == 1 else {}
        check("ba1 RED-FIRST: `bug-add` writes exactly the step-3 shape of "
              "`commands/bug.md` - every key present, `status` open, the "
              "operator's words unchanged, and the unset links null. On "
              "current code the verb is unknown and a bug is a hand edit: %r"
              % ((codeba, txtba[:160], _ba_new),),
              codeba == 0 and len(_ba_new) == 1
              and list(_ba_bug) == BA_KEYS
              and _ba_bug.get("title") == "Login crashes"
              and _ba_bug.get("status") == "open"
              and _ba_bug.get("severity") == "high"
              and _ba_bug.get("description") == _ba_desc
              and _ba_bug.get("repro") == "submit the form empty"
              and _ba_bug.get("expected") == "a message"
              and _ba_bug.get("actual") == "a stack trace"
              and _ba_bug.get("files") == ["src/a.ts", "src/b.ts"]
              and _ba_bug.get("reportedBy") is None
              and _ba_bug.get("taskId") is None
              and _ba_bug.get("fixedIn") is None
              and _ba_bug.get("notes") is None
              and bool(_ba_bug.get("reportedAt")))
        check("ba1b the id is the allocator's answer (max+1 over the bugs the "
              "plan holds, suffix included), not a count: %r"
              % ((_ba_bug.get("id"), _ba_want_id),),
              _ba_want_id == "BUG-8" and _ba_bug.get("id") == _ba_want_id)
        _ba_rows = cp_journal(ba_proj, "bug.add")
        check("ba1c exactly one `bug.add` journal row, naming the bug it "
              "wrote: %r" % (_ba_rows,),
              len(_ba_rows) == 1
              and ((_ba_rows[0].get("details") or {}).get("field")
                   == _ba_want_id))

        # A plan with no `bugs` key at all: the verb creates the list rather
        # than refusing, which is step 1 of `commands/bug.md`.
        _ba_nokey = base_manifest()
        del _ba_nokey["bugs"]
        ba_proj2, ba_mp2 = mk("ba-nokey", _ba_nokey)
        codeba2, txtba2 = run(
            ["bug-add", "No list yet", "--severity", "low",
             "--description", "d", "--project-dir", ba_proj2])
        _ba_list2 = ba_bugs(ba_mp2)
        check("ba2 on a plan with no `bugs` key, `bug-add` creates the list "
              "and writes the one bug, with `files` an empty list when none "
              "was named: %r" % ((codeba2, txtba2[:160], _ba_list2),),
              codeba2 == 0 and isinstance(_ba_list2, list)
              and len(_ba_list2) == 1
              and _ba_list2[0].get("id") == "BUG-1"
              and _ba_list2[0].get("files") == []
              and _ba_list2[0].get("repro") is None)

        # THE VERB AND THE PUBLISHED SCHEMA, ONE SHAPE. The bug `ba2` wrote
        # (no --repro, --expected or --actual, so those answers are null) is
        # read back and every key is held against the type the schema file
        # declares for it under the bug item. `validate-manifest.py` applies
        # no JSON Schema, so without this a record the verb writes can fail
        # the strict CI validation while every local gate stays green.
        with open(os.path.join(_output.PLUGIN_ROOT, "schema",
                               "audit-plan.schema.json"),
                  "r", encoding="utf-8") as _fh:
            _ba_schema = json.load(_fh)

        _BA_READ = ("$ref", "type", "enum", "items", "oneOf", "anyOf", "pattern")
        _BA_ANNOTATIONS = ("description", "title", "default", "examples",
                           "$comment", "deprecated", "readOnly", "writeOnly")

        def ba_resolve(node):
            # A `$ref` is followed and its siblings merged in; a sibling that
            # restates a key of the target is kept apart as an unread key, so
            # the conjunction is never read as the sibling alone.
            ref = node.get("$ref") if isinstance(node, dict) else None
            if not ref:
                return node
            target = _ba_schema
            for part in ref.lstrip("#/").split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            merged = dict(ba_resolve(target))
            for key, val in node.items():
                if key == "$ref" or key in _BA_ANNOTATIONS:
                    continue
                merged["$ref sibling " + key if key in merged else key] = val
            return merged

        _BA_JSON_TYPES = {
            "string": lambda v: isinstance(v, str),
            "null": lambda v: v is None,
            "array": lambda v: isinstance(v, list),
            "object": lambda v: isinstance(v, dict),
            "boolean": lambda v: isinstance(v, bool),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: (isinstance(v, (int, float))
                                 and not isinstance(v, bool))}

        def ba_admits(node, value):
            # Reads $ref, type, enum, items, pattern, oneOf/anyOf - not a validator.
            # None means the node carries a constraint this reader does not
            # read, or none at all; the case treats that as a fault, not a pass.
            node = ba_resolve(node)
            if not isinstance(node, dict):
                return None
            if any(k not in _BA_READ and k not in _BA_ANNOTATIONS for k in node):
                return None
            verdicts = []
            if "pattern" in node:
                verdicts.append(not isinstance(value, str)
                                or re.search(node["pattern"], value) is not None)
            if "type" in node:
                names = node["type"]
                names = [names] if isinstance(names, str) else list(names)
                verdicts.append(any(_BA_JSON_TYPES.get(n, lambda v: False)(value)
                                    for n in names))
            if "enum" in node:
                verdicts.append(value in node["enum"])
            if isinstance(value, list) and "items" in node:
                verdicts.append(all(ba_admits(node["items"], item) is True
                                    for item in value))
            for combiner in ("oneOf", "anyOf"):
                if combiner in node:
                    hits = [ba_admits(arm, value) is True
                            for arm in node[combiner]]
                    verdicts.append(hits.count(True) == 1 if combiner == "oneOf"
                                    else any(hits))
            return all(verdicts) if verdicts else None

        _ba_item = ba_resolve(
            _ba_schema.get("properties", {}).get("bugs", {}).get("items", {}))
        _ba_props = _ba_item.get("properties", {})

        def ba_type_faults(record):
            unknown = sorted(k for k in record if k not in _ba_props)
            wrong = sorted(k for k in record if k in _ba_props
                           and ba_admits(_ba_props[k], record[k]) is not True)
            return unknown, wrong

        _ba_rec = dict(_ba_list2[0]) if len(_ba_list2 or []) == 1 else {}
        _ba_faults = ba_type_faults(_ba_rec)
        check("ba5 RED-FIRST: every key of a bug `bug-add` writes with no "
              "--repro/--expected/--actual is a property the published schema "
              "declares under the bug item, and every value - the null "
              "answers included - is a type the schema admits for it "
              "(unknown keys, wrong-typed keys): %r"
              % ((_ba_faults, sorted(_ba_rec)),),
              list(_ba_rec) == BA_KEYS and bool(_ba_props)
              and _ba_faults == ([], []))
        # The allow twin: the same reader must pass the shapes the schema
        # does admit and REPORT one it does not, or ba5 could be green over
        # a reader that admits everything.
        _ba_twin = {}
        for _ba_what, _ba_val in (("repro string", "step one"),
                                  ("repro list", ["step one", "step two"]),
                                  ("repro integer", 7),
                                  ("repro list of integers", [7])):
            _ba_twin[_ba_what] = ba_type_faults(dict(_ba_rec, repro=_ba_val))
        _ba_twin["id off its pattern"] = ba_type_faults(dict(_ba_rec, id="BUG-x"))
        _ba_twin["an unread keyword"] = ba_admits(
            {"type": "string", "minLength": 1}, "s")
        check("ba5b ALLOW CASE: `repro` as a string or a list of strings "
              "passes the same reader, `repro` as an integer or a list of "
              "integers and an id off the schema's pattern are reported by "
              "name, and a constraint the reader does not read is 'cannot "
              "read', not a pass: %r" % (_ba_twin,),
              _ba_twin == {"repro string": ([], []),
                           "repro list": ([], []),
                           "repro integer": ([], ["repro"]),
                           "repro list of integers": ([], ["repro"]),
                           "id off its pattern": ([], ["id"]),
                           "an unread keyword": None})
        _ba_full = ba_type_faults(_ba_bug)
        check("ba5c the bug `bug-add` writes with EVERY answer given (ba1's "
              "record) is typed clean by the same reader: %r" % (_ba_full,),
              list(_ba_bug) == BA_KEYS and _ba_full == ([], []))

        # THE VERB LOADS THE SCHEMA ONCE AND HANDS IT IN. A verb validates before
        # its write and after it; the loader is replaced by a counter, so one read
        # across both calls means the schema was loaded once and passed - the
        # rules' own fallback would read again on every call.
        import _manifest_crossrefs as _xr                         # noqa: E402
        _vs_real = _xr.load_plan_schema
        _vs_reads = []

        def _vs_counting(root=None):
            _vs_reads.append(root)
            return _vs_real(root)

        def _vs_broken(root=None):
            raise OSError("schema gone")
        _vs_plan = _mio.load_manifest(ba_mp)
        _vs_plan["bugs"][-1]["files"] = "src/a.ts"
        _xr.load_plan_schema = _vs_counting
        try:
            _vs_v = M._validator()
            _vs_pre = _vs_v.validate(_vs_plan)
            _vs_post = _vs_v.validate(_vs_plan)
        finally:
            _xr.load_plan_schema = _vs_real
        _xr.load_plan_schema = _vs_broken
        try:
            _vs_gone = M._validator().validate(_vs_plan)
        finally:
            _xr.load_plan_schema = _vs_real
        with open(os.path.join(_output.SCRIPTS_DIR, "manifest", "audit-task.py"),
                  "r", encoding="utf-8") as _fh:
            _vs_src = _fh.read()
        check("ba6 a verb's validator reads the schema ONCE for its pre- and "
              "post-write checks and types bug values with it; every verb takes "
              "the rules through that one validator; an unreadable schema is a "
              "finding its pre-check refuses on: %r"
              % ((len(_vs_reads), _vs_src.count("_cores()"),
                  _vs_pre[1][-1:], _vs_gone[0][:1]),),
              len(_vs_reads) == 1 and _vs_pre == _vs_post
              and any("files is string" in x for x in _vs_pre[1])
              and _vs_src.count("_cores()") == 1
              and _vs_src.count("vm = _validator()") >= 1
              and len(_vs_gone[0]) >= 1
              and "install is broken" in _vs_gone[0][0])

        # THE DOCUMENT AND THE CODE, ONE ORDER. The brace list step 3 of
        # `commands/bug.md` spells is parsed out of the file and compared with
        # the verb's own template, so neither can gain, lose or reorder a key
        # without the other.
        with open(os.path.join(_output.PLUGIN_ROOT, "commands", "bug.md"),
                  "r", encoding="utf-8") as _fh:
            _ba_doc = _fh.read()
        _ba_braces = re.findall(r"\{id, title,[^{}]*\}", _ba_doc)
        _ba_doc_keys = ([part.strip().split(":")[0].strip()
                         for part in _ba_braces[0].strip("{}").split(",")]
                        if len(_ba_braces) == 1 else [])
        check("ba1d the `{id, title, ...}` shape `commands/bug.md` step 3 "
              "spells is, key for key and in order, the verb's "
              "`_BUG_TEMPLATE_KEYS` - and the spelling occurs once, so the "
              "case reads the one the document means: %r"
              % ((len(_ba_braces), _ba_doc_keys),),
              len(_ba_braces) == 1
              and _ba_doc_keys == list(M._BUG_TEMPLATE_KEYS) == BA_KEYS)

        # Refusals: after the lock, before the read and before any byte
        # moves. Each sub-case also asserts the VERB's own sentence, so an
        # argparse exit 2 (an unknown verb, say) cannot stand in for it.
        _ba_before = ba_bytes(ba_mp)
        _ba_ref = {}
        for _baargv, _bawhat, _bawant in (
                (["bug-add", "T", "--description", "d"], "no --severity",
                 "bug-add needs --severity"),
                (["bug-add", "T", "--severity", "urgent", "--description", "d"],
                 "bad --severity", "bug-add needs --severity"),
                (["bug-add", "T", "--severity", "low"], "no --description",
                 "bug-add needs --description"),
                (["bug-add", "", "--severity", "low", "--description", "d"],
                 "no title", "bug-add needs a title")):
            _bacode, _batxt = run(_baargv + ["--project-dir", ba_proj])
            _ba_ref[_bawhat] = (_bacode, _bawant in _batxt)
        check("ba3 a bug-add missing its severity, description or title, or "
              "carrying a severity outside low/med/high, is refused exit 2 "
              "IN THE VERB'S OWN WORDS and writes nothing: %r" % (_ba_ref,),
              sorted(_ba_ref.values()) == [(2, True)] * len(_ba_ref)
              and ba_bytes(ba_mp) == _ba_before)

        # Sharded: the bug lands in the index and no shard is rewritten.
        ba_proj3, ba_mp3 = mk("ba-shard", base_manifest(), sharded=True)
        _ba_shards = dict(
            (os.path.join(dp, fn), ba_bytes(os.path.join(dp, fn)))
            for dp, _dn, fns in os.walk(os.path.dirname(ba_mp3))
            for fn in fns if os.path.join(dp, fn) != ba_mp3
            and fn.endswith(".json"))
        codeba3, txtba3 = run(
            ["bug-add", "Sharded", "--severity", "med", "--description", "d",
             "--project-dir", ba_proj3])
        _ba_idx = _mio.read_json(ba_mp3)
        check("ba4 on a sharded plan the bug is written into the INDEX and "
              "every shard keeps its bytes: %r"
              % ((codeba3, txtba3[:160], _ba_idx.get("bugs")),),
              codeba3 == 0 and bool(_ba_shards)
              and [b.get("id") for b in (_ba_idx.get("bugs") or [])]
              == ["BUG-1"]
              and all(ba_bytes(p) == b for p, b in _ba_shards.items()))

        # ---- (mu) mute / unmute: the only writers of `meta.muted` ----------
        def mu_muted(mpath):
            return cp_meta(mpath).get("muted")

        _mu_fx = base_manifest()
        _mu_fx["bugs"] = [{"id": "BUG-3", "title": "flaky", "status": "open"}]
        mu_proj, mu_mp = mk("mu-mute", _mu_fx)
        codemu, txtmu = run_on_stdin(
            ["mute", "--test", "tests/test_a.py", "--reason", "-",
             "--owner", "alice", "--until", "2998-01-01", "--bug", "BUG-3",
             "--project-dir", mu_proj], "flaky  on CI \n")
        check("mu1 RED-FIRST: `mute` writes one `meta.muted` entry carrying "
              "the five fields the validator grades, the reason unchanged. On "
              "current code the verb is unknown and a quarantine is a hand "
              "edit: %r" % ((codemu, txtmu[:160], mu_muted(mu_mp)),),
              codemu == 0
              and mu_muted(mu_mp) == [
                  {"test": "tests/test_a.py", "reason": "flaky  on CI ",
                   "owner": "alice", "until": "2998-01-01",
                   "bugId": "BUG-3"}])
        _mu_rows = cp_journal(mu_proj, "test.muted")
        check("mu1b exactly one `test.muted` journal row, naming the test: %r"
              % (_mu_rows,),
              len(_mu_rows) == 1
              and ((_mu_rows[0].get("details") or {}).get("field")
                   == "tests/test_a.py"))

        _mu_before = ba_bytes(mu_mp)
        codemu2, txtmu2 = run(
            ["mute", "--test", "tests/test_b.py", "--reason", "r",
             "--owner", "alice", "--until", "2998-01-01",
             "--project-dir", mu_proj])
        check("mu2 a mute with no --bug is refused exit 2 before anything "
              "is written - a quarantine nothing tracks is the shape it "
              "exists to refuse: %r" % (txtmu2[:160],),
              codemu2 == 2 and "--bug" in txtmu2
              and ba_bytes(mu_mp) == _mu_before)

        # The verb does NOT look the bug up itself: the validator's
        # `rules.muted.bug-unknown` finding refuses it on the revalidation,
        # and the write is rolled back. Skipping the revalidation turns this
        # red, which is the mutation it is here for.
        codemu3, txtmu3 = run(
            ["mute", "--test", "tests/test_b.py", "--reason", "r",
             "--owner", "alice", "--until", "2998-01-01", "--bug", "BUG-404",
             "--project-dir", mu_proj])
        check("mu3 a mute naming a bug the plan lacks is refused by the "
              "validator's finding (exit 1, the FINDING line printed) and "
              "rolled back byte for byte: %r" % (txtmu3[:240],),
              codemu3 == 1 and "REFUSED" in txtmu3
              and "FINDING: " in txtmu3 and "BUG-404" in txtmu3
              and ba_bytes(mu_mp) == _mu_before
              and not cp_journal(mu_proj, "test.muted")[1:])

        codemu4, txtmu4 = run(
            ["mute", "--test", "tests/test_a.py", "--reason", "still flaky",
             "--owner", "bob", "--until", "2999-06-30", "--bug", "BUG-3",
             "--project-dir", mu_proj])
        check("mu4 a mute on an already-muted test with a LATER until "
              "extends that one entry rather than appending a second: %r"
              % ((codemu4, txtmu4[:160], mu_muted(mu_mp)),),
              codemu4 == 0
              and mu_muted(mu_mp) == [
                  {"test": "tests/test_a.py", "reason": "still flaky",
                   "owner": "bob", "until": "2999-06-30", "bugId": "BUG-3"}])
        _mu_before4 = ba_bytes(mu_mp)
        _mu_short = {}
        for _muargv, _muwhat, _muwant in (
                (["--until", "2999-06-30"], "same until", "a re-mute only EXTENDS"),
                (["--until", "2998-01-01"], "earlier until",
                 "a re-mute only EXTENDS"),
                (["--until", "2000-01-01"], "past until", "is already past"),
                (["--until", "next week"], "unreadable until",
                 "mute needs --until")):
            _mucode, _mutxt = run(
                ["mute", "--test", "tests/test_a.py", "--reason", "r",
                 "--owner", "bob", "--bug", "BUG-3"] + _muargv
                + ["--project-dir", mu_proj])
            _mu_short[_muwhat] = (_mucode, _muwant in _mutxt)
        check("mu4b a re-mute whose until does not extend the entry, an until "
              "already past, and one that is not a calendar day are refused "
              "exit 2 IN THE VERB'S OWN WORDS and write nothing: %r"
              % (_mu_short,),
              sorted(_mu_short.values()) == [(2, True)] * len(_mu_short)
              and ba_bytes(mu_mp) == _mu_before4)

        # ALLOW CASE: unmute removes exactly the entry it names.
        codemu5, _t = run(
            ["mute", "--test", "tests/test_c.py", "--reason", "r",
             "--owner", "carol", "--until", "2998-01-01", "--bug", "BUG-3",
             "--project-dir", mu_proj])
        _mu_keep = [e for e in (mu_muted(mu_mp) or [])
                    if e.get("test") == "tests/test_c.py"]
        codemu6, txtmu6 = run(
            ["unmute", "--test", "tests/test_a.py", "--project-dir", mu_proj])
        check("mu5 ALLOW CASE: `unmute --test` removes exactly the entry it "
              "names and leaves every other mute as it was: %r"
              % ((codemu5, codemu6, txtmu6[:160], mu_muted(mu_mp)),),
              codemu5 == 0 and codemu6 == 0 and len(_mu_keep) == 1
              and mu_muted(mu_mp) == _mu_keep)
        _mu_un = cp_journal(mu_proj, "test.unmuted")
        check("mu5b exactly one `test.unmuted` journal row, naming the "
              "test: %r" % (_mu_un,),
              len(_mu_un) == 1
              and ((_mu_un[0].get("details") or {}).get("field")
                   == "tests/test_a.py"))
        codemu7, txtmu7 = run(
            ["unmute", "--test", "tests/test_a.py", "--project-dir", mu_proj])
        check("mu6 `unmute` of a test carrying no mute is refused exit 2 - a "
              "no-op reporting success would hide that nothing was muted: %r"
              % (txtmu7[:160],),
              codemu7 == 2 and "tests/test_a.py" in txtmu7)

        # An EXPIRED mute is a warning, so a plan carrying one is not refused
        # by the pre-check: extending it and lifting it both run.
        _mu_old = base_manifest()
        _mu_old["bugs"] = [{"id": "BUG-3", "title": "flaky", "status": "open"}]
        _mu_old["meta"]["muted"] = [
            {"test": "tests/test_x.py", "reason": "r", "owner": "o",
             "until": "2000-01-01", "bugId": "BUG-3"},
            {"test": "tests/test_y.py", "reason": "r", "owner": "o",
             "until": "2000-01-01", "bugId": "BUG-3"}]
        mu_proj8, mu_mp8 = mk("mu-expired", _mu_old)
        codemu8, txtmu8 = run(
            ["mute", "--test", "tests/test_x.py", "--reason", "r",
             "--owner", "o", "--until", "2998-01-01", "--bug", "BUG-3",
             "--project-dir", mu_proj8])
        codemu9, txtmu9 = run(
            ["unmute", "--test", "tests/test_y.py", "--project-dir", mu_proj8])
        check("mu7 on a plan carrying an expired mute, an extending mute and "
              "an unmute both run like every other verb: %r"
              % ((codemu8, txtmu8[:160], codemu9, txtmu9[:160],
                  mu_muted(mu_mp8)),),
              codemu8 == 0 and codemu9 == 0
              and [(e.get("test"), e.get("until"))
                   for e in (mu_muted(mu_mp8) or [])]
              == [("tests/test_x.py", "2998-01-01")])

        # ---- (mo) the optional manifest positional AFTER the flags --------
        # Documented for `bug-add`, `mute` and `couple` alike, and plain
        # `parse_args` has refused a trailing positional after options on
        # interpreters this project still supports (3.9 measured). The manifest each call
        # names sits at a path the fixture's config does NOT name, so a
        # trailing positional that was dropped - and the configured file
        # written instead - reads differently from one that was used.
        def mo_alt(name):
            fx = base_manifest()
            fx["bugs"] = [{"id": "BUG-3", "title": "flaky", "status": "open"}]
            proj, conf = mk(name, fx)
            alt = os.path.join(proj, "alt", "plan.json")
            os.makedirs(os.path.dirname(alt), exist_ok=True)
            _panel_write._atomic_write_json(alt, fx)
            _cp_ev.append_row(proj, {
                "v": 1, "runId": "RUN-IX", "ts": "2026-09-01T00:00:00Z",
                "scope": "phase", "phaseId": "P2", "status": "failed",
                "steps": []})
            return proj, conf, alt

        def mo_facts(alt):
            man = _mio.load_manifest(alt)
            meta = man.get("meta") or {}
            return ([b.get("id") for b in man.get("bugs") or []],
                    [e.get("test") for e in meta.get("muted") or []],
                    [e.get("test") for e in meta.get("coupling") or []])

        ix_proj, ix_conf, ix_alt = mo_alt("mo-order")
        _ix_conf_before = ba_bytes(ix_conf)
        _ix = {}
        _ix["bug-add"] = run(
            ["bug-add", "T", "--severity", "low", "--description", "d",
             "--project-dir", ix_proj, ix_alt])[0]
        _ix["mute"] = run(
            ["mute", "--test", "tests/test_ix.py", "--reason", "r",
             "--owner", "o", "--until", "2998-01-01", "--bug", "BUG-3",
             "--project-dir", ix_proj, ix_alt])[0]
        _ix["couple"] = run(
            ["couple", "--test", "tests/test_ix.py", "--sources", "src/a.ts",
             "--basis-run", "RUN-IX", "--basis-head", "deadbeef",
             "--project-dir", ix_proj, ix_alt])[0]
        check("mo1 a manifest path passed AFTER the flags parses on every "
              "supported interpreter, for `bug-add`, `mute` and `couple`, and "
              "each call writes into THAT manifest while the configured one "
              "keeps its bytes: %r" % ((_ix, mo_facts(ix_alt)),),
              _ix == {"bug-add": 0, "mute": 0, "couple": 0}
              and mo_facts(ix_alt) == (["BUG-3", "BUG-4"],
                                       ["tests/test_ix.py"],
                                       ["tests/test_ix.py"])
              and ba_bytes(ix_conf) == _ix_conf_before)

        # ...and with NO --project-dir, from a cwd that is another project:
        # the named manifest alone decides the root, so the lock, the config,
        # the evidence lookup and the journal row all belong to ITS project.
        # The verbs that take no id move the lone positional into the
        # manifest slot, and that has to happen before the root is resolved.
        mo_proj, mo_conf, mo_alt_mp = mo_alt("mo-named")
        mo_home, mo_home_mp = mk("mo-elsewhere", base_manifest())
        _mo_conf_before = ba_bytes(mo_conf)
        _mo_home_before = ba_bytes(mo_home_mp)
        _mo_cwd, _mo_env = os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR")
        _mo = {}
        try:
            os.chdir(mo_home)
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            _mo["bug-add"] = run(
                ["bug-add", "T", "--severity", "low", "--description", "d",
                 mo_alt_mp])[0]
            _mo["mute"] = run(
                ["mute", "--test", "tests/test_mo.py", "--reason", "r",
                 "--owner", "o", "--until", "2998-01-01", "--bug", "BUG-3",
                 mo_alt_mp])[0]
            _mo["unmute"] = run(["unmute", "--test", "tests/test_mo.py",
                                 mo_alt_mp])[0]
            _mo["couple"] = run(
                ["couple", "--test", "tests/test_mo.py", "--sources",
                 "src/a.ts", "--basis-run", "RUN-IX", "--basis-head",
                 "deadbeef", mo_alt_mp])[0]
            _mo["uncouple"] = run(["uncouple", "--test", "tests/test_mo.py",
                                   mo_alt_mp])[0]
        finally:
            os.chdir(_mo_cwd)
            if _mo_env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = _mo_env
        _mo_actions = ("bug.add", "test.muted", "test.unmuted",
                       "coupling.learned", "coupling.dropped")
        _mo_rows = dict((a, len(cp_journal(mo_proj, a))) for a in _mo_actions)
        _mo_stray = dict((a, len(cp_journal(mo_home, a))) for a in _mo_actions)
        check("mo2 with no --project-dir and the cwd in ANOTHER project, a "
              "trailing manifest decides the root for `bug-add`, `mute`, "
              "`unmute`, `couple` and `uncouple`: each writes that manifest "
              "and journals into its project, and the other project is "
              "untouched: %r"
              % ((_mo, mo_facts(mo_alt_mp), _mo_rows, _mo_stray),),
              _mo == {"bug-add": 0, "mute": 0, "unmute": 0, "couple": 0,
                      "uncouple": 0}
              and mo_facts(mo_alt_mp) == (["BUG-3", "BUG-4"], [], [])
              and _mo_rows == dict((a, 1) for a in _mo_actions)
              and _mo_stray == dict((a, 0) for a in _mo_actions)
              and ba_bytes(mo_conf) == _mo_conf_before
              and ba_bytes(mo_home_mp) == _mo_home_before)
        # ...and the ORDER, for every door that takes no id - `settle`
        # included, whose write leaves no journal row to catch it by: the
        # positional is moved by the one helper, before the root is resolved,
        # and nowhere else in the file moves it.
        import inspect as _mo_inspect
        _mo_src = _mo_inspect.getsource(M)
        _mo_order = {}
        for _mo_door in (M.cmd_settle, M.cmd_couple, M.cmd_uncouple,
                         M.cmd_mute, M.cmd_unmute):
            _mo_body = _mo_inspect.getsource(_mo_door)
            _mo_move = _mo_body.find("_manifest_from_positional(args)")
            _mo_root = _mo_body.find("_resolve_project(args)")
            _mo_order[_mo_door.__name__] = 0 <= _mo_move < _mo_root
        check("mo3 every door that takes no id moves a lone positional into "
              "the manifest slot BEFORE resolving the root, through one "
              "helper, and the move is spelled nowhere else: %r"
              % ((_mo_order, _mo_src.count("args.manifest = args.title")),),
              all(_mo_order.values()) and len(_mo_order) == 5
              and _mo_src.count("args.manifest = args.title") == 1)

    finally:
        _harness.remove_tree(tmp)


def _cli(argv, cwd):
    """`(exit, stdout)` of this command run as the main loop runs it: a process
    started in `cwd`, with the session's own variables dropped."""
    import subprocess
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    done = subprocess.run(
        [sys.executable, _loader.script_path("audit-task.py")] + argv,
        cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, encoding="utf-8")
    return done.returncode, done.stdout


def _success_line_cases(check):
    """A write, said in one line naming the task and the file written; a value
    verb's one line kept as it is; `--verbose` and a refusal, in full."""
    root = _harness.fixture_root("audit-task-sl-")

    def project(name):
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json"})
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        _panel_write._atomic_write_json(mpath, {
            "meta": {"version": 2, "buildCommands": {"test": "true"}},
            "phases": [{"id": "P1", "title": "Live", "status": "in_progress",
                        "testGate": ["test"], "tasks": [
                            {"id": "P1.1", "title": "a",
                             "status": "in_progress", "files": ["src/a.ts"],
                             "startedAt": "2026-01-01T00:00:00Z",
                             "attempts": 1, "maxAttempts": 3}]}],
            "fileIndex": {"src/a.ts": ["P1.1"]}, "bugs": []})
        return proj

    short_proj, long_proj = project("short"), project("long")
    code, short = _cli(["note", "P1.1", "--text", "probe"], short_proj)
    lines = short.splitlines()
    check("sl1 a successful write prints ONE line within the byte bound, "
          "naming what was done to which task and the file it wrote: %r"
          % (short,),
          code == 0 and len(lines) == 1
          and len(lines[0].encode("utf-8")) <= 200
          and lines[0].startswith("[audit-task] P1.1 note 1 appended")
          and lines[0].endswith("written: docs/audit/audit-plan.json"))
    vcode, verbose = _cli(["note", "P1.1", "--text", "probe", "--verbose"],
                          long_proj)
    check("sl2 ...and `--verbose` prints the text the verb always printed: the "
          "same headline, then the lines after it, the record's among them: %r"
          % (verbose,),
          vcode == 0 and len(verbose.splitlines()) > 1
          and verbose.splitlines()[0].split(" at ")[0]
          == lines[0].split(" at ")[0]
          and "  written: docs/audit/audit-plan.json" in verbose.splitlines())
    icode, minted = _cli(["next-id", "task", "--phase", "P1"], short_proj)
    check("sl3 a verb that answers with a value keeps its one line exactly, "
          "since a caller reads that line AS the value: %r" % (minted,),
          icode == 0 and minted.startswith("P1.2") and minted.count("\n") == 1
          and not minted.startswith("["))
    wcode, wide = _cli(["note", "P1.1", "--text", "w" * 300], short_proj)
    check("sl5 a headline carrying a long text of the caller's is the part cut, "
          "and the cut says so; the file written is kept whole: %r" % (wide,),
          wcode == 0 and wide.count("\n") == 1
          and len(wide.rstrip("\n").encode("utf-8")) <= 200
          and _output.CLIPPED_MARK in wide
          and wide.rstrip("\n").endswith("; written: docs/audit/audit-plan.json"))
    refused = _cli(["done", "P1.1", "--outcome", "x"], short_proj)
    check("sl4 a refusal prints in full, `--verbose` or not - the deny twin of "
          "sl1: %r" % (refused,),
          refused[0] == M.E_USAGE and len(refused[1].splitlines()) > 1
          and refused == _cli(["done", "P1.1", "--outcome", "x", "--verbose"],
                              short_proj))
    # What the write itself decided survives the short form: the gate basis,
    # the next command, and a warning about the id it wrote. A warning about
    # another id was there before the write and is still dropped.
    held = project("held")
    _cli(["add", "Earlier", "--phase", "P1", "--files", "src/c.ts",
          "--tests-mode", "tdd"], held)
    acode, added = _cli(["add", "Later", "--phase", "P1", "--files", "src/b.ts",
                         "--tests-mode", "tdd"], held)
    alines = added.splitlines()
    check("sl6 an `add` keeps, beside its headline, the gate basis, the ready "
          "line and the warning naming the task it added, and drops the "
          "warning about the task added before it: %r" % (added,),
          acode == 0 and alines[0].startswith("[audit-task] P1.3 added")
          and alines[0].rstrip().endswith("written: docs/audit/audit-plan.json")
          and sum(1 for ln in alines if ln.startswith("gate: ")) == 1
          and "ready now -- /audit:run P1.3" in alines
          and sum(1 for ln in alines if ln.startswith("WARNING: task P1.3:")) == 1
          and not any("P1.2" in ln for ln in alines if ln.startswith("WARNING")))


# A close against a commit needs the reviewer's filed return or a deliberate
# `not-asked` with its basis. The cases whose subject is something else close the
# second way, so the review rule is not what they answer to.
_NOT_ASKED = ["--intent", "not-asked", "--intent-basis",
              "the review is not this case's subject"]
_FR_START = "2026-01-01T00:00:00Z"
_FR_SHA = "0123456789abcdef0123456789abcdef01234567"


def _fr_executor(**over):
    """An executor return in the shape `agents/audit-executor.md` declares."""
    body = {"gates": {"python3 t.py": "pass"},
            "redFirst": {"status": "proved",
                         "basis": "python3 t.py exit 1, fr_case failed",
                         "at": "2026-01-01T00:05:00Z"},
            "outcome": {"technical": "filed technical",
                        "descriptive": "filed descriptive"},
            "testsAdded": ["fr_case_one", "fr_case_two"],
            "stamp": "audit-stamp: v2 head=abc"}
    body.update(over)
    return json.dumps(body, indent=1) + "\n"


def _fr_reviewer(answer="matches"):
    """A task-mode reviewer return in the shape `agents/audit-reviewer.md`
    declares."""
    return json.dumps({"findings": [], "preExisting": [],
                       "intent": {"answer": answer, "note": "n", "missing": []},
                       "verdict": "clean"}) + "\n"


def _return_cases(check):
    """The filing verb and the rule `done` puts on every close that passes
    `--commit`: a return lands at one derived path, once per start and role, and
    a close reads the reviewer's filed answer instead of a word typed beside it."""
    import io
    root = _harness.fixture_root("audit-task-fr-")

    def project(name, started=_FR_START, attempts=1):
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        # `always`, the reading these cases were written for: the rule on a
        # close under a reviewer per task. `phase` is the `hd` block's.
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json",
             "review": {"perTask": "always"}})
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        task = {"id": "P1.1", "title": "a", "status": "in_progress",
                "description": "do a", "files": ["src/a.ts"],
                "tests": {"mode": "gate-only", "add": [],
                          "expectRedFirst": False, "gate": ["test"]},
                "attempts": attempts, "maxAttempts": 3}
        if started:
            task["startedAt"] = started
        _panel_write._atomic_write_json(mpath, {
            "meta": {"version": 2, "buildCommands": {"test": "true"}},
            "phases": [{"id": "P1", "title": "Live", "status": "in_progress",
                        "testGate": ["test"], "tasks": [task]}],
            "fileIndex": {"src/a.ts": ["P1.1"]}, "bugs": []})
        return proj, mpath

    def returns_dir(proj):
        return os.path.join(proj, "docs", "audit", "evidence", "returns")

    def derived(proj, role, start="20260101T000000Z"):
        return os.path.join(returns_dir(proj), "P1.1",
                            "%s.%s.json" % (start, role))

    def run(argv, stdin=""):
        lines = []
        real = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            code = M.main(argv, out=lines.append)
        finally:
            sys.stdin = real
        return code, "\n".join(str(x) for x in lines)

    def file_return(proj, role, text, tid="P1.1"):
        return run(["file-return", tid, "--role", role, "--project-dir", proj],
                   text)

    def read(path):
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def restart(mpath, started):
        """A second start of the same task: `start` re-stamps `startedAt`, and
        that stamp is what keeps two attempts' returns apart."""
        body = _mio.read_json(mpath)
        body["phases"][0]["tasks"][0]["startedAt"] = started
        _panel_write._atomic_write_json(mpath, body)

    def task(mpath):
        return _mio.tasks_by_id(_mio.load_manifest(mpath)).get("P1.1") or {}

    # ---- (fr) the filing verb ---------------------------------------------
    proj, mpath = project("fr-path")
    c1, t1 = file_return(proj, "executor", _fr_executor(), tid="../P1.1")
    c2, t2 = file_return(proj, "../../reviewer", _fr_reviewer())
    check("fr1 a path-like task id or role is refused and nothing is written - "
          "the verb takes no path and derives the one file it writes: %r"
          % ((c1, t1[:120], c2, t2[:120]),),
          c1 == M.E_USAGE and c2 == M.E_USAGE
          and "no path" in t1 and "no path" in t2
          and not os.path.exists(returns_dir(proj)))
    c3, t3 = file_return(proj, "executor", _fr_executor())
    check("fr2 ALLOW: a well-formed executor return is written at the derived "
          "path, byte-identical to what was handed in on stdin: %r" % (t3,),
          c3 == 0 and read(derived(proj, "executor"))
          == _fr_executor().encode("utf-8")
          and "returns/P1.1/20260101T000000Z.executor.json" in t3)

    proj, mpath = project("fr-shape")
    bad = json.loads(_fr_executor())
    del bad["stamp"]
    c4, t4 = file_return(proj, "executor", json.dumps(bad))
    c5, t5 = file_return(proj, "executor", "{not json")
    c6, t6 = file_return(proj, "reviewer", json.dumps(
        {"findings": [], "intent": {"answer": "maybe"}, "verdict": "clean"}))
    check("fr3 a malformed return writes nothing and the refusal names what is "
          "wrong - a missing field, text that is not JSON, a word outside the "
          "vocabulary: %r" % ((c4, t4[:100], c5, c6, t6[:100]),),
          c4 == M.E_USAGE and "stamp" in t4
          and c5 == M.E_USAGE and c6 == M.E_USAGE and "maybe" in t6
          and not os.path.exists(returns_dir(proj)))

    proj, mpath = project("fr-once")
    file_return(proj, "executor", _fr_executor())
    first = read(derived(proj, "executor"))
    c7, t7 = file_return(proj, "executor", _fr_executor(stamp="audit-stamp: v2 other"))
    c8, _t8 = file_return(proj, "reviewer", _fr_reviewer())
    restart(mpath, "2026-01-02T00:00:00Z")
    c9, _t9 = file_return(proj, "executor", _fr_executor(stamp="audit-stamp: v2 retry"))
    check("fr4 a second filing for one task and role in one start is refused "
          "and the first return is byte-identical afterwards; the OTHER role "
          "files in the same start, and the same role files again after a "
          "re-start - so a verb refusing every second filing fails here: %r"
          % ((c7, t7[:100], c8, c9),),
          c7 == M.E_USAGE and "already filed" in t7
          and read(derived(proj, "executor")) == first
          and c8 == 0 and read(derived(proj, "reviewer")) is not None
          and c9 == 0
          and b"retry" in (read(derived(proj, "executor",
                                        "20260102T000000Z")) or b""))

    proj, mpath = project("fr-unstarted", started=None)
    c10, t10 = file_return(proj, "executor", _fr_executor())
    check("fr5 a task with no recorded start has no current start to file "
          "under, so the filing is refused writing nothing: %r" % (t10[:120],),
          c10 == M.E_USAGE and "start" in t10
          and not os.path.exists(returns_dir(proj)))

    # ---- (fc) the rule on `done` ------------------------------------------
    def close(proj, *extra):
        return run(["done", "P1.1", "--project-dir", proj, "--commit", _FR_SHA]
                   + list(extra))

    proj, mpath = project("dr-none")
    before = read(mpath)
    r1 = close(proj)
    r2 = close(proj, "--intent", "matches")
    check("fc1 a plain `done --commit` with no reviewer return filed for the "
          "current start is refused writing nothing - with no --intent and "
          "with --intent matches alike: %r" % ((r1[0], r1[1][:160], r2[0]),),
          r1[0] == M.E_USAGE and r2[0] == M.E_USAGE
          and "reviewer" in r1[1] and "not-asked" in r1[1]
          and read(mpath) == before)

    proj, mpath = project("dr-stale")
    file_return(proj, "reviewer", _fr_reviewer())
    restart(mpath, "2026-01-02T00:00:00Z")
    before = read(mpath)
    r3 = close(proj, "--intent", "matches")
    check("fc2 a reviewer return from an EARLIER start does not count: the "
          "same close is refused, nothing written: %r" % ((r3[0], r3[1][:120]),),
          r3[0] == M.E_USAGE and read(mpath) == before)

    proj, mpath = project("dr-match")
    file_return(proj, "reviewer", _fr_reviewer("matches"))
    r4 = close(proj, "--intent", "matches")
    proj2, mpath2 = project("dr-match-bare")
    file_return(proj2, "reviewer", _fr_reviewer("matches"))
    r5 = close(proj2)
    check("fc3 ALLOW: over a filed `matches` for the current start, `done "
          "--commit --intent matches` closes, and the same close with no "
          "--intent records the filed answer: %r"
          % ((r4[0], r5[0], task(mpath2).get("intentCheck")),),
          r4[0] == 0 and task(mpath).get("status") == "done"
          and (task(mpath).get("intentCheck") or {}).get("answer") == "matches"
          and r5[0] == 0
          and (task(mpath2).get("intentCheck") or {}).get("answer") == "matches"
          and (task(mpath2).get("intentCheck") or {}).get("commit") == _FR_SHA)

    proj, mpath = project("dr-diverge")
    file_return(proj, "reviewer", _fr_reviewer("diverges"))
    before = read(mpath)
    r6 = close(proj, "--intent", "matches")
    r7 = close(proj, "--intent", "not-asked", "--intent-basis", "too small")
    check("fc4 over a filed `diverges`, a typed `matches` is refused and so is "
          "`not-asked` with its basis - a typed word cannot replace an answer a "
          "reviewer filed: %r" % ((r6[0], r6[1][:120], r7[0]),),
          r6[0] == M.E_USAGE and r7[0] == M.E_USAGE
          and "diverges" in r6[1] and read(mpath) == before)

    proj, mpath = project("dr-notasked")
    r8 = close(proj, "--intent", "not-asked", "--intent-basis", "a one-line typo")
    proj2, mpath2 = project("dr-nochange")
    r9 = run(["done", "P1.1", "--project-dir", proj2, "--no-change", "--reason",
              "already right", "--intent", "not-asked", "--intent-basis",
              "no diff to bind"])
    check("fc5 ALLOW: `done --commit --intent not-asked` with its basis closes "
          "with no return filed, and a `--no-change` close with not-asked and "
          "its basis closes as it does today: %r" % ((r8[0], r9[0], r9[1][:120]),),
          r8[0] == 0 and task(mpath).get("status") == "done"
          and (task(mpath).get("intentCheck") or {}).get("answer") == "not-asked"
          and r9[0] == 0 and task(mpath2).get("status") == "done")

    # ---- (fc) `done --from-return` ----------------------------------------
    proj, mpath = project("dr-fr-noexec")
    file_return(proj, "reviewer", _fr_reviewer())
    before = read(mpath)
    r10 = close(proj, "--from-return")
    proj2, mpath2 = project("dr-fr-norev")
    file_return(proj2, "executor", _fr_executor())
    before2 = read(mpath2)
    r11 = close(proj2, "--from-return")
    check("fc6 `done --from-return` is refused writing nothing when the "
          "executor's return for the current start is missing, and meets the "
          "plain form's rule too - no reviewer return and no not-asked is "
          "refused: %r" % ((r10[0], r10[1][:120], r11[0], r11[1][:120]),),
          r10[0] == M.E_USAGE and "executor" in r10[1] and read(mpath) == before
          and r11[0] == M.E_USAGE and "reviewer" in r11[1]
          and read(mpath2) == before2)

    proj, mpath = project("dr-fr-both")
    file_return(proj, "executor", _fr_executor())
    file_return(proj, "reviewer", _fr_reviewer("matches"))
    r12 = close(proj, "--from-return")
    t12 = task(mpath)
    check("fc7 ALLOW: with both returns filed for the current start, "
          "`--from-return` closes from them - the outcome, verifiedBy from "
          "testsAdded, the reviewer's answer, and the red-first block onto "
          "task.redFirst rather than into outcome text alone: %r"
          % ((r12[0], r12[1][:200], t12.get("redFirst"), t12.get("outcome")),),
          r12[0] == 0 and t12.get("status") == "done"
          and (t12.get("outcome") or {}).get("technical") == "filed technical"
          and (t12.get("outcome") or {}).get("descriptive") == "filed descriptive"
          and t12.get("verifiedBy") == ["fr_case_one", "fr_case_two"]
          and (t12.get("intentCheck") or {}).get("answer") == "matches"
          and t12.get("redFirst") == json.loads(_fr_executor())["redFirst"])

    proj, mpath = project("dr-fr-notasked")
    file_return(proj, "executor", _fr_executor())
    r13 = close(proj, "--from-return", "--intent", "not-asked",
                "--intent-basis", "review skipped on purpose")
    check("fc8 ALLOW: the executor's return filed and the close passing "
          "`--intent not-asked` with its basis closes from that return: %r"
          % ((r13[0], r13[1][:160]),),
          r13[0] == 0 and (task(mpath).get("redFirst") or {}).get("status")
          == "proved")

    proj, mpath = project("dr-fr-mixed")
    file_return(proj, "executor", _fr_executor())
    file_return(proj, "reviewer", _fr_reviewer())
    before = read(mpath)
    r14 = close(proj, "--from-return", "--descriptive", "typed instead")
    check("fc9 `--from-return` beside a typed --descriptive is refused, "
          "nothing written - one close takes its account from one place: %r"
          % ((r14[0], r14[1][:120]),),
          r14[0] == M.E_USAGE and "--from-return" in r14[1]
          and read(mpath) == before)


_HD_SHA2 = "1111111111111111111111111111111111111111"
_HD_SHA3 = "2222222222222222222222222222222222222222"
_HD_HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_HD_HEAD2 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_HD_BASIS = ["--intent-basis", "a one-line typo"]


def _hd_entry(tid, commit, **over):
    """One `tasks` entry of a phase-mode reviewer return, whole."""
    entry = {"id": tid, "commit": commit, "answer": "matches", "note": "n",
             "missing": [], "redFirst": "proved",
             "redFirstBasis": "t.py exit 1, its own case",
             "inheritedTests": "not-asked",
             "inheritedTestsBasis": "the gate runs the whole suite"}
    entry.update(over)
    return entry


def _hd_return(entries):
    return json.dumps({"findings": [], "preExisting": [],
                       "intent": {"answer": "matches", "note": "n",
                                  "missing": []},
                       "verdict": "clean", "tasks": entries}) + "\n"


def _held_cases(check):
    """`review.perTask: phase` - the close that writes `deferred`, the key
    recorded once per phase and kept by the task, `add --fixes`, the phase
    return's filing, and sign-off's refusal while a task lacks its answers."""
    import io
    root = _harness.fixture_root("audit-task-hd-")

    def tk(tid, status="in_progress", started=_FR_START, **over):
        task = {"id": tid, "title": tid, "status": status,
                "description": "do " + tid, "files": ["src/%s.ts" % (tid,)],
                "tests": {"mode": "gate-only", "add": [],
                          "expectRedFirst": False, "gate": ["test"]},
                "attempts": 1 if started else 0, "maxAttempts": 3}
        if started:
            task["startedAt"] = started
        task.update(over)
        return task

    def done_tk(tid, commit, key="phase", **over):
        fields = {"status": "done", "commit": commit, "reviewPerTask": key,
                  "completedAt": "2026-01-01T01:00:00Z",
                  "intentCheck": {"answer": "deferred", "commit": commit,
                                  "at": "2026-01-01T01:00:00Z"}}
        fields.update(over)
        return tk(tid, **fields)

    def ph(pid, tasks, **over):
        phase = {"id": pid, "title": pid, "status": "in_progress",
                 "testGate": ["test"], "tasks": tasks}
        phase.update(over)
        return phase

    def finding(fid, **over):
        entry = {"id": fid, "severity": "low", "file": "src/a.ts",
                 "issue": "i", "resolution": "r"}
        entry.update(over)
        return entry

    def cfg(proj, key):
        body = {"manifestPath": "docs/audit/audit-plan.json"}
        if key is not None:
            body["review"] = {"perTask": key}
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"), body)

    def project(name, phases, key=None):
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        cfg(proj, key)
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        index = {}
        for phase in phases:
            for task in phase["tasks"]:
                for f in task["files"]:
                    index.setdefault(f, []).append(task["id"])
        _panel_write._atomic_write_json(mpath, {
            "meta": {"version": 2, "buildCommands": {"test": "true"}},
            "phases": phases, "fileIndex": index, "bugs": []})
        return proj, mpath

    def run(argv, stdin=""):
        lines = []
        real = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            code = M.main(argv, out=lines.append)
        finally:
            sys.stdin = real
        return code, "\n".join(str(x) for x in lines)

    def verb(proj, *argv, **kw):
        return run(list(argv) + ["--project-dir", proj], kw.get("stdin", ""))

    def close(proj, tid, *extra, **kw):
        return verb(proj, "done", tid, "--commit", kw.get("sha", _FR_SHA), *extra)

    def read(path):
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def plan(mpath):
        return _mio.load_manifest(mpath)

    def task(mpath, tid):
        return _mio.tasks_by_id(plan(mpath)).get(tid) or {}

    def phase(mpath, pid):
        return [p for p in plan(mpath)["phases"] if p.get("id") == pid][0]

    def answer(mpath, tid):
        return (task(mpath, tid).get("intentCheck") or {}).get("answer")

    def returns(proj, pid):
        return os.path.join(proj, "docs", "audit", "evidence", "returns", pid)

    def file_phase(proj, pid, head, entries):
        return verb(proj, "file-return", pid, "--role", "reviewer",
                    "--head", head, stdin=_hd_return(entries))

    def signoff(proj, pid, verdict="skipped", *extra):
        return verb(proj, "signoff", pid, "--verdict", verdict, "--summary",
                    "the phase did its work", *extra)

    # ---- the close -------------------------------------------------------------
    # No `review` key in the config: the shipped default, `phase`.
    proj, mpath = project("close-refused", [ph("P1", [tk("P1.1")])])
    run(["file-return", "P1.1", "--role", "executor", "--project-dir", proj],
        _fr_executor())
    before = read(mpath)
    r1 = close(proj, "P1.1", "--from-return", "--intent", "not-asked",
               *_HD_BASIS)
    r2 = close(proj, "P1.1", "--intent", "not-asked", *_HD_BASIS)
    r3 = close(proj, "P1.1", "--intent", "matches")
    check("hd1 under the shipped `phase`, a close with a commit refuses every "
          "--intent word - from the return with not-asked and its basis, plain "
          "not-asked with its basis, plain matches - writing nothing: %r"
          % ([(r[0], r[1][:90]) for r in (r1, r2, r3)],),
          [r[0] for r in (r1, r2, r3)] == [M.E_USAGE] * 3
          and all("review.perTask" in r[1] for r in (r1, r2, r3))
          and read(mpath) == before)
    r4 = close(proj, "P1.1")
    t4, p4 = task(mpath, "P1.1"), phase(mpath, "P1")
    check("hd2 ALLOW: the same task closed with no --intent closes, records "
          "`deferred` bound to its commit, and records the key it took on the "
          "task and on the phase that had none: %r"
          % ((r4[0], t4.get("intentCheck"), t4.get("reviewPerTask"),
              p4.get("reviewPerTask")),),
          r4[0] == 0 and t4.get("status") == "done"
          and t4.get("intentCheck", {}).get("answer") == "deferred"
          and t4.get("intentCheck", {}).get("commit") == _FR_SHA
          and t4.get("reviewPerTask") == "phase"
          and p4.get("reviewPerTask") == "phase")
    proj, mpath = project("close-nochange", [ph("P1", [tk("P1.1")])])
    r5 = verb(proj, "done", "P1.1", "--no-change", "--reason", "already right",
              "--intent", "not-asked", "--intent-basis", "no diff to bind")
    check("hd3 ALLOW: a `--no-change` close with not-asked and its basis is "
          "accepted under `phase` - without this half a close refusing every "
          "not-asked would pass: %r" % ((r5[0], r5[1][:120]),),
          r5[0] == 0 and answer(mpath, "P1.1") == "not-asked")
    proj, mpath = project("close-always", [ph("P1", [tk("P1.1")])], "always")
    r6 = close(proj, "P1.1", "--intent", "not-asked", *_HD_BASIS)
    check("hd4 ALLOW: under `always` the plain close with not-asked and its "
          "basis closes as it did before the key - without this half a rule "
          "refusing it under every key would pass: %r" % ((r6[0], r6[1][:120]),),
          r6[0] == 0 and answer(mpath, "P1.1") == "not-asked"
          and task(mpath, "P1.1").get("reviewPerTask") == "always")

    # ---- the fix-task exception and `add --fixes` -------------------------------
    p1 = ph("P1", [tk("P1.1")], review={"findings": [
        finding("P1-R1"), finding("P1-R2", fixTask="P1.1")]})
    p2 = ph("P2", [tk("P2.1", status="pending", started=None)],
            status="pending", review={"findings": [finding("P2-R1")]})
    proj, mpath = project("fixes", [p1, p2])
    before = read(mpath)
    a1 = verb(proj, "add", "fix the other phase", "--phase", "P1",
              "--files", "src/f.ts", "--fixes", "P2-R1")
    a2 = verb(proj, "add", "fix a taken one", "--phase", "P1",
              "--files", "src/f.ts", "--fixes", "P1-R2")
    a3 = verb(proj, "scope", "P1.1", "--fixes", "P1-R1")
    check("hd5 `add --fixes` naming another phase's finding, or one already "
          "naming another task, is refused writing nothing, and every other "
          "verb refuses the flag: %r" % ([(a[0], a[1][:100]) for a in (a1, a2, a3)],),
          [a[0] for a in (a1, a2, a3)] == [M.E_USAGE] * 3
          and "P2-R1" in a1[1] and "P1.1" in a2[1] and "--fixes" in a3[1]
          and read(mpath) == before)
    a4 = verb(proj, "add", "fix R1", "--phase", "P1", "--files", "src/f.ts",
              "--fixes", "P1-R1")
    fixer = [t for t in phase(mpath, "P1")["tasks"] if t.get("title") == "fix R1"]
    fid = fixer[0]["id"] if fixer else None
    linked = [f for f in phase(mpath, "P1")["review"]["findings"]
              if f.get("id") == "P1-R1"]
    check("hd6 ALLOW: `add --fixes` naming its own phase's free finding writes "
          "`fixes` on the task and the finding's `fixTask`, in one write: %r"
          % ((a4[0], fid, linked),),
          a4[0] == 0 and fid and fixer[0].get("fixes") == ["P1-R1"]
          and linked and linked[0].get("fixTask") == fid)
    verb(proj, "start", fid)
    r7 = close(proj, fid, "--intent", "not-asked", "--intent-basis", "fix task")
    before = read(mpath)
    r8 = close(proj, "P1.1", "--intent", "not-asked", "--intent-basis", "fix task")
    check("hd7 under `phase`, the task `add --fixes` recorded closes not-asked "
          "with its basis, and a task not recorded that way is refused the same "
          "flags, writing nothing: %r" % ((r7[0], r7[1][:100], r8[0]),),
          r7[0] == 0 and answer(mpath, fid) == "not-asked"
          and r8[0] == M.E_USAGE and read(mpath) == before)

    # Linked by `resolve-finding`, then reopened: the link is not the key.
    proj, mpath = project("relinked", [ph("P1", [tk("P1.1")], review={
        "findings": [finding("P1-R1")]})])
    close(proj, "P1.1")
    verb(proj, "resolve-finding", "P1-R1", "--fix-task", "P1.1")
    verb(proj, "reopen", "P1.1", "--reason", "redo")
    verb(proj, "start", "P1.1")
    before = read(mpath)
    r9 = close(proj, "P1.1", "--intent", "not-asked", *_HD_BASIS, sha=_HD_SHA2)
    proj2, mpath2 = project("relinked-fixes", [ph("P1", [tk("P1.1")], review={
        "findings": [finding("P1-R1")]})])
    verb(proj2, "add", "fix R1", "--phase", "P1", "--files", "src/f.ts",
         "--fixes", "P1-R1")
    verb(proj2, "start", "P1.2")
    close(proj2, "P1.2", "--intent", "not-asked", *_HD_BASIS)
    verb(proj2, "reopen", "P1.2", "--reason", "redo")
    verb(proj2, "start", "P1.2")
    r10 = close(proj2, "P1.2", "--intent", "not-asked", *_HD_BASIS, sha=_HD_SHA2)
    check("hd8 a task closed `deferred`, linked by resolve-finding, reopened, "
          "restarted and closed not-asked is refused - it carries no `fixes` - "
          "and the same sequence on a task `add --fixes` recorded closes: %r"
          % ((r9[0], r9[1][:100], r10[0], r10[1][:100]),),
          r9[0] == M.E_USAGE and read(mpath) == before
          and r10[0] == 0 and answer(mpath2, "P1.2") == "not-asked")

    # ---- the key, once per phase and kept by the task ---------------------------
    proj, mpath = project("key-switch", [ph("P1", [
        tk("P1.1", status="pending", started=None),
        tk("P1.2", status="pending", started=None)], status="pending")], "phase")
    s1 = verb(proj, "start", "P1.1")
    keyed = (phase(mpath, "P1").get("reviewPerTask"),
             task(mpath, "P1.1").get("reviewPerTask"))
    cfg(proj, "always")
    verb(proj, "start", "P1.2", "--force", "--reason", "parallel")
    before = read(mpath)
    r11 = close(proj, "P1.1", "--intent", "not-asked", *_HD_BASIS)
    check("hd9 `start` records the key on the phase at its first start and on "
          "the task; with the config then switched to `always`, a second task "
          "still records `phase` and a plain not-asked close is still refused: %r"
          % ((s1[0], keyed, task(mpath, "P1.2").get("reviewPerTask"), r11[0]),),
          s1[0] == 0 and keyed == ("phase", "phase")
          and task(mpath, "P1.2").get("reviewPerTask") == "phase"
          and r11[0] == M.E_USAGE and read(mpath) == before)

    # Started under `phase`, blocked, moved to a phase that recorded `always`.
    p1 = ph("P1", [tk("P1.1", status="pending", started=None),
                   tk("P1.2", status="pending", started=None)], status="pending")
    p2 = ph("P2", [tk("P2.1", reviewPerTask="always")], reviewPerTask="always")
    proj, mpath = project("moved", [p1, p2], "phase")
    verb(proj, "start", "P1.1")
    verb(proj, "block", "P1.1", "--reason", "waits")
    verb(proj, "move", "P1.1", "--to", "P2")
    moved = [t["id"] for t in phase(mpath, "P2")["tasks"] if t.get("title") == "P1.1"]
    mid = moved[0] if moved else "missing"
    before = read(mpath)
    r12 = close(proj, mid, "--intent", "not-asked", *_HD_BASIS)
    refused_moved = r12[0] == M.E_USAGE and read(mpath) == before
    r13 = close(proj, mid)
    verb(proj, "move", "P1.2", "--to", "P2")
    moved2 = [t["id"] for t in phase(mpath, "P2")["tasks"] if t.get("title") == "P1.2"]
    mid2 = moved2[0] if moved2 else "missing"
    verb(proj, "start", mid2)
    r14 = close(proj, mid2, "--intent", "not-asked", *_HD_BASIS)
    check("hd10 a task started under `phase`, blocked and moved to a phase that "
          "recorded `always` keeps `phase`: not-asked is refused and no --intent "
          "closes `deferred`; a task moved there before its first start takes "
          "`always` and closes not-asked: %r"
          % ((mid, r12[0], r13[0], answer(mpath, mid), mid2, r14[0]),),
          refused_moved and r13[0] == 0 and answer(mpath, mid) == "deferred"
          and r14[0] == 0 and answer(mpath, mid2) == "not-asked")

    # Blocked from `pending`: no `start` ever gave the task or its phase a key.
    def unstarted(name, key):
        return project(name, [ph("P1", [
            tk("P1.1", status="pending", started=None),
            tk("P1.2", status="pending", started=None)], status="pending")], key)
    proj, mpath = unstarted("blocked-phase", "phase")
    verb(proj, "block", "P1.1", "--reason", "waits")
    before = read(mpath)
    r15 = close(proj, "P1.1", "--intent", "not-asked", *_HD_BASIS)
    refused_blocked = r15[0] == M.E_USAGE and read(mpath) == before
    r16 = close(proj, "P1.1")
    cfg(proj, "always")
    verb(proj, "start", "P1.2")
    proj2, mpath2 = unstarted("blocked-always", "always")
    verb(proj2, "block", "P1.1", "--reason", "waits")
    r17 = close(proj2, "P1.1", "--intent", "not-asked", *_HD_BASIS)
    check("hd11 a task blocked from `pending` and closed under a config reading "
          "`phase` is refused not-asked, closes `deferred` with no --intent and "
          "records `phase` on itself and its phase, so a task started after the "
          "config reads `always` still records `phase`; under `always` the same "
          "first close records `always` and closes not-asked: %r"
          % ((r15[0], r16[0], phase(mpath, "P1").get("reviewPerTask"),
              task(mpath, "P1.2").get("reviewPerTask"), r17[0]),),
          refused_blocked and r16[0] == 0
          and answer(mpath, "P1.1") == "deferred"
          and task(mpath, "P1.1").get("reviewPerTask") == "phase"
          and phase(mpath, "P1").get("reviewPerTask") == "phase"
          and task(mpath, "P1.2").get("reviewPerTask") == "phase"
          and r17[0] == 0 and answer(mpath2, "P1.1") == "not-asked"
          and phase(mpath2, "P1").get("reviewPerTask") == "always")

    p1 = ph("P1", [tk("P1.1", status="pending", started=None),
                   tk("P1.2", status="pending", started=None)], status="pending")
    p2 = ph("P2", [tk("P2.1", status="pending", started=None)], status="pending")
    p3 = ph("P3", [tk("P3.1", reviewPerTask="always")], reviewPerTask="always")
    proj, mpath = project("blocked-moved", [p1, p2, p3], "phase")
    verb(proj, "block", "P1.1", "--reason", "waits")
    verb(proj, "move", "P1.1", "--to", "P2")
    in2 = [t["id"] for t in phase(mpath, "P2")["tasks"] if t.get("title") == "P1.1"]
    m2 = in2[0] if in2 else "missing"
    before = read(mpath)
    r18 = close(proj, m2, "--intent", "not-asked", *_HD_BASIS)
    refused_m2 = r18[0] == M.E_USAGE and read(mpath) == before
    r19 = close(proj, m2)
    verb(proj, "block", "P1.2", "--reason", "waits")
    verb(proj, "move", "P1.2", "--to", "P3")
    in3 = [t["id"] for t in phase(mpath, "P3")["tasks"] if t.get("title") == "P1.2"]
    m3 = in3[0] if in3 else "missing"
    r20 = close(proj, m3, "--intent", "not-asked", *_HD_BASIS)
    check("hd12 a task blocked from `pending` and moved into a phase none of "
          "whose tasks has started is refused not-asked and closes `deferred`; "
          "moved instead into a phase that recorded `always`, it closes "
          "not-asked: %r" % ((m2, r18[0], r19[0], m3, r20[0]),),
          refused_m2 and r19[0] == 0 and answer(mpath, m2) == "deferred"
          and r20[0] == 0 and answer(mpath, m3) == "not-asked")

    proj, mpath = project("terminal", [ph("P1", [done_tk("P1.1", _FR_SHA),
                                                 tk("P1.2")])])
    before = read(mpath)
    c1 = verb(proj, "cancel", "P1.1", "--reason", "drop")
    c2 = verb(proj, "block", "P1.1", "--reason", "wait")
    check("hd13 `cancel` and `block` of a task closed `deferred` are refused, "
          "writing nothing: %r" % ((c1[0], c2[0]),),
          c1[0] == M.E_USAGE and c2[0] == M.E_USAGE and read(mpath) == before)

    # ---- the phase return and sign-off -----------------------------------------
    def two_done(name, key=None):
        return project(name, [ph("P1", [done_tk("P1.1", _FR_SHA),
                                        done_tk("P1.2", _HD_SHA2)],
                                 reviewPerTask="phase")], key)

    proj, mpath = two_done("file-short")
    f1 = file_phase(proj, "P1", _HD_HEAD, [_hd_entry("P1.1", _FR_SHA)])
    nothing = not os.path.exists(returns(proj, "P1"))
    f2 = file_phase(proj, "P1", _HD_HEAD, [_hd_entry("P1.1", _FR_SHA),
                                           _hd_entry("P1.2", _HD_SHA2)])
    check("hd14 a phase return lacking the entry of one task owed an answer is "
          "refused at filing, writing nothing and naming that task; with the "
          "entry restored it files, keyed on the head: %r"
          % ((f1[0], f1[1][:160], f2[0], f2[1][:120]),),
          f1[0] == M.E_USAGE and "P1.2" in f1[1] and nothing
          and f2[0] == 0
          and os.path.isfile(os.path.join(returns(proj, "P1"),
                                          "%s.reviewer.json" % (_HD_HEAD,))))
    f3 = file_phase(proj, "P1", _HD_HEAD2, [_hd_entry("P1.1", _FR_SHA)])
    proj2, mpath2 = two_done("file-commit")
    f4 = file_phase(proj2, "P1", _HD_HEAD, [_hd_entry("P1.1", _HD_SHA3),
                                            _hd_entry("P1.2", _HD_SHA2)])
    check("hd15 an entry naming a commit other than its task records is refused "
          "at filing, and so is a second entry for a commit an earlier return "
          "answers - each writing nothing: %r"
          % ((f3[0], f3[1][:160], f4[0], f4[1][:160]),),
          f3[0] == M.E_USAGE and "already answers" in f3[1]
          and not os.path.exists(os.path.join(
              returns(proj, "P1"), "%s.reviewer.json" % (_HD_HEAD2,)))
          and f4[0] == M.E_USAGE and "P1.1" in f4[1]
          and not os.path.exists(returns(proj2, "P1")))

    proj, mpath = two_done("signoff")
    before = read(mpath)
    g1 = signoff(proj, "P1", "skipped")
    g2 = signoff(proj, "P1", "passed", "--no-evidence-reason", "no gate here")
    check("hd16 under `phase`, sign-off of a phase with tasks owed an answer is "
          "refused writing nothing and names them - under `--verdict skipped` as "
          "under `passed`: %r" % ((g1[0], g1[1][:160], g2[0]),),
          g1[0] == M.E_USAGE and "P1.1" in g1[1] and "P1.2" in g1[1]
          and g2[0] == M.E_USAGE and read(mpath) == before)
    file_phase(proj, "P1", _HD_HEAD, [_hd_entry("P1.1", _FR_SHA),
                                      _hd_entry("P1.2", _HD_SHA2)])
    g3 = signoff(proj, "P1", "skipped")
    ic = task(mpath, "P1.1").get("intentCheck") or {}
    check("hd17 ALLOW: once a filed phase return answers each task's commit, "
          "`skipped` signs off and writes the three answers onto each task, bound "
          "to its commit - without this half a sign-off refusing every `skipped` "
          "would pass: %r" % ((g3[0], g3[1][:120], ic),),
          g3[0] == 0 and ic.get("answer") == "matches"
          and ic.get("commit") == _FR_SHA and ic.get("redFirst") == "proved"
          and ic.get("inheritedTests") == "not-asked"
          and ic.get("inheritedTestsBasis") and ic.get("return"))
    proj, mpath = project("signoff-always", [ph("P1", [
        done_tk("P1.1", _FR_SHA, key="always",
                intentCheck={"answer": "not-asked", "basis": "typo",
                             "commit": _FR_SHA})], reviewPerTask="always")])
    g4 = signoff(proj, "P1", "skipped")
    check("hd18 ALLOW: a phase with no task whose key reads `phase` signs off "
          "`skipped` as it did before the key: %r" % ((g4[0], g4[1][:120]),),
          g4[0] == 0)

    missing = []
    for field in ("answer", "redFirst", "inheritedTests"):
        proj, mpath = two_done("signoff-drop-%s" % (field,))
        file_phase(proj, "P1", _HD_HEAD, [_hd_entry("P1.1", _FR_SHA),
                                          _hd_entry("P1.2", _HD_SHA2)])
        path = os.path.join(returns(proj, "P1"), "%s.reviewer.json" % (_HD_HEAD,))
        if read(path) is None:
            missing.append("%s (no return was filed to edit)" % (field,))
            continue
        body = json.loads(read(path).decode("utf-8"))
        body["tasks"][0].pop(field)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        before = read(mpath)
        g5 = signoff(proj, "P1", "skipped")
        if not (g5[0] == M.E_USAGE and "P1.1" in g5[1] and read(mpath) == before):
            missing.append(field)
    check("hd19 a filed return with one task's intent answer, red-first grade or "
          "inherited-test answer removed by hand is refused at sign-off, naming "
          "the task: %r" % (missing,), missing == [])

    proj, mpath = two_done("recommitted")
    file_phase(proj, "P1", _HD_HEAD, [_hd_entry("P1.1", _FR_SHA),
                                      _hd_entry("P1.2", _HD_SHA2)])
    verb(proj, "reopen", "P1.1", "--reason", "redo")
    verb(proj, "start", "P1.1")
    close(proj, "P1.1", sha=_HD_SHA3)
    before = read(mpath)
    g6 = signoff(proj, "P1", "skipped")
    refused_again = g6[0] == M.E_USAGE and "P1.1" in g6[1] and read(mpath) == before
    f5 = file_phase(proj, "P1", _HD_HEAD2, [_hd_entry("P1.1", _HD_SHA3)])
    g7 = signoff(proj, "P1", "skipped")
    check("hd20 a task answered in a filed phase return, then reopened, "
          "recommitted and closed `deferred`, is refused at sign-off while the "
          "earlier entry is still filed; a return answering its new commit lets "
          "sign-off pass: %r" % ((g6[0], g6[1][:120], f5[0], f5[1][:120], g7[0]),),
          refused_again and f5[0] == 0 and g7[0] == 0
          and (task(mpath, "P1.1").get("intentCheck") or {}).get("commit")
          == _HD_SHA3)

    # A fix task whose finding `resolve-finding` points at another task loses
    # the exception: sign-off refuses it until a phase return answers it.
    projf, mpathf = project("fix-relinked-signoff", [ph("P1", [
        done_tk("P1.1", _HD_SHA2, intentCheck={
            "answer": "matches", "commit": _HD_SHA2, "redFirst": "proved",
            "redFirstBasis": "b", "inheritedTests": "none-found"})],
        review={"findings": [finding("P1-R1")]})])
    verb(projf, "add", "fix R1", "--phase", "P1", "--files", "src/f.ts",
         "--fixes", "P1-R1")
    verb(projf, "start", "P1.2")
    close(projf, "P1.2", "--intent", "not-asked", *_HD_BASIS)
    file_phase(projf, "P1", _HD_HEAD, [_hd_entry("P1.1", _HD_SHA2)])
    verb(projf, "resolve-finding", "P1-R1", "--fix-task", "P1.1")
    before = read(mpathf)
    g9 = signoff(projf, "P1", "skipped")
    refused_relinked = (g9[0] == M.E_USAGE and "P1.2" in g9[1]
                        and read(mpathf) == before)
    f8 = file_phase(projf, "P1", _HD_HEAD2, [_hd_entry("P1.2", _FR_SHA)])
    g10 = signoff(projf, "P1", "skipped")
    check("hd22 a task `add --fixes` recorded, closed not-asked, whose finding "
          "`resolve-finding` then points at another task, is refused at sign-off "
          "naming it, and signs off once a filed phase return answers its "
          "commit: %r" % ((g9[0], g9[1][-160:], f8[0], g10[0]),),
          refused_relinked and f8[0] == 0
          and g10[0] == 0)

    # ---- what a verdict read ------------------------------------------------
    # The read set is this sign-off's, never carried forward from an earlier
    # review, and it covers the tip's committed returns as well as the
    # checkout's evidence - each read through the same human stop.
    def read_set_cases():
        stale = {"return": "returns/P1/stale.reviewer.json", "sha256": "0" * 64}
        proj, mpath = project("signoff-reread", [ph(
            "P1", [done_tk("P1.1", _FR_SHA), done_tk("P1.2", _HD_SHA2)],
            reviewPerTask="phase",
            review={"status": "pending", _fr.READ_RETURNS_FIELD: [stale]})])
        file_phase(proj, "P1", _HD_HEAD, [_hd_entry("P1.1", _FR_SHA),
                                          _hd_entry("P1.2", _HD_SHA2)])
        again = signoff(proj, "P1", "skipped")
        rec = (phase(mpath, "P1").get("review") or {}).get(
            _fr.READ_RETURNS_FIELD) or []
        filed = _fr.phase_returns(os.path.join(proj, "docs", "audit",
                                               "evidence"), "P1")
        check("rr2 a sign-off over a review that already carries a read set "
              "rewrites it with what this sign-off read - a record merged with "
              "the earlier one would vouch for a return nobody read now: %r"
              % ((again[0], rec),),
              again[0] == 0 and stale not in rec
              and rec == _fr.read_record(filed) and len(rec) == 1)

        def tip_project(name, intent):
            """P1 on branch `audit/p1-rr` in a git checkout of its own, a phase
            return committed at the tip and then removed from the evidence on
            disk, so the tip is the one place holding it."""
            proj, mpath = project(name, [ph(
                "P1", [done_tk("P1.1", _FR_SHA), done_tk("P1.2", _HD_SHA2)],
                reviewPerTask="phase", branch="audit/p1-rr")])
            import subprocess
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

            def git(*a):
                return subprocess.run(["git", "-C", proj] + list(a), env=env,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
            git("init", "-q", "-b", "main")
            git("add", "-A")
            git("commit", "-q", "-m", "base")
            git("checkout", "-q", "-b", "audit/p1-rr")
            body = json.loads(_hd_return([_hd_entry("P1.1", _FR_SHA),
                                          _hd_entry("P1.2", _HD_SHA2)]))
            body["intent"]["answer"] = intent
            rel = _fr.phase_return_rel("P1", _HD_HEAD)
            path = os.path.join(proj, "docs", "audit", "evidence",
                                *rel.split("/"))
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(body, fh)
            git("add", "-A")
            git("commit", "-q", "-m", "the phase return")
            os.remove(path)
            return proj, mpath, rel, body

        proj, mpath, rel, body = tip_project("signoff-tip-read", "matches")
        file_phase(proj, "P1", _HD_HEAD2, [_hd_entry("P1.1", _FR_SHA),
                                           _hd_entry("P1.2", _HD_SHA2)])
        tipped = signoff(proj, "P1", "skipped")
        rec = (phase(mpath, "P1").get("review") or {}).get(
            _fr.READ_RETURNS_FIELD) or []
        check("rr3 the read set covers the tip's committed returns as well as "
              "the checkout's evidence: a return the tip commits and the disk "
              "no longer holds is read and recorded: %r" % ((tipped[0], rec),),
              tipped[0] == 0 and len(rec) == 2
              and {"return": rel, "sha256": _fr.return_signature(
                  (rel, body, None))} in rec)

        proj, mpath, rel, body = tip_project("signoff-tip-human", "diverges")
        file_phase(proj, "P1", _HD_HEAD2, [_hd_entry("P1.1", _FR_SHA),
                                           _hd_entry("P1.2", _HD_SHA2)])
        before = read(mpath)
        held = signoff(proj, "P1", "skipped")
        check("rr3b THE TWIN: ...and a `diverges` there is put through the same "
              "human stop as one on disk - a read set recording a return the "
              "stop never asked about would vouch for an unsettled answer: %r"
              % ((held[0], held[1][-240:]),),
              held[0] == M.E_USAGE and "intent diverges" in held[1]
              and read(mpath) == before)

    # ---- the answers only a human settles, at the verb ------------------------
    # The driver's triage stops on them; the sign-off verb, run by hand, must
    # stop on them too, and read the same settlement the triage's accept writes.
    def human_answer_cases():
        def settle(proj, keys, text=None, by_name_only=False):
            """The driver's settlement record in `proj`, naming `keys` - each
            bound to the signature of the return in `proj`'s evidence it
            names, as the triage's accept records it, unless `by_name_only`,
            the record a driver older than the signatures wrote."""
            hc = _loader.load_hooks_config()
            path = os.path.join(str(hc.state_dir(pathlib.Path(proj), {})),
                                "drive", "P1.json")
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            filed = _fr.phase_returns(os.path.join(proj, "docs", "audit",
                                                   "evidence"), "P1")
            answers = [a for a in _fr.needs_human(filed) if a["key"] in keys]
            block = _fr.settlement_after({}, answers, "the owner read it: fine")
            block["keys"] = list(keys)
            if by_name_only:
                block.pop(_fr.SIGNATURES_FIELD, None)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text if text is not None else json.dumps(
                    {_fr.SETTLED_FIELD: block}))

        hd_rel = _fr.phase_return_rel("P1", _HD_HEAD)
        proj, mpath = two_done("signoff-diverges")
        file_phase(proj, "P1", _HD_HEAD, [
            _hd_entry("P1.1", _FR_SHA, answer="diverges", note="does another thing"),
            _hd_entry("P1.2", _HD_SHA2, redFirst="not-proved",
                      redFirstBasis="no red seen")])
        before = read(mpath)
        h1 = signoff(proj, "P1", "skipped")
        check("hd25 a filed phase return answering `diverges` for one task and "
              "`not-proved` for another refuses sign-off by hand, writing nothing, "
              "naming both answers and the driver's accept that settles them: %r"
              % ((h1[0], h1[1][-300:]),),
              h1[0] == M.E_USAGE and read(mpath) == before
              and "P1.1" in h1[1] and "intent diverges" in h1[1]
              and "red-first not-proved" in h1[1] and "--answer accept" in h1[1])
        check("hd29 ...and with no phase review marked in the driver's state, "
              "the remedy says the driver reads the review already filed at the "
              "current head - it pays for no second one - and ends on signing "
              "off again: %r" % (h1[1][-420:],),
              "already filed at the current head" in h1[1]
              and "second paid review" not in h1[1] and "sign off again" in h1[1]
              and "group sign-off" not in h1[1])
        filed_p1 = _fr.phase_returns(os.path.join(proj, "docs", "audit",
                                                  "evidence"), "P1")
        _lines, as_member = M._human_settlement(proj, {}, "P1", filed_p1,
                                                group=True)
        check("hd29g a group member's refusal says to answer its triage only "
              "`accept`, never `sign-off` (which lands the member alone), and to "
              "run the group sign-off again: %r" % ((as_member or "")[-420:],),
              "only `accept`" in (as_member or "")
              and "lands this member alone" in (as_member or "")
              and "group sign-off again" in (as_member or ""))
        settle(proj, [], text=json.dumps({"phaseReview": {"head": _HD_HEAD}}))
        marked = signoff(proj, "P1", "skipped")
        check("hd29b THE TWIN: with a phase review marked in the driver's state, "
              "the same refusal says nothing of finding a review at the head - "
              "the driver reads the "
              "marked review's return there rather than dispatching one: %r" % ((marked[0], marked[1][-300:]),),
              marked[0] == M.E_USAGE and "intent diverges" in marked[1]
              and "already filed at the current head" not in marked[1])
        qualifier = "where a review skill resolves or a task is owed its answers"
        check("hd29q the unmarked remedy keeps the condition the driver reads or "
              "dispatches a review under - a review skill resolving, or a task "
              "owed its answers; without one the driver reads no return and "
              "dispatches none: %r" % (h1[1][-480:],),
              qualifier in h1[1])
        check("hd29r THE TWIN: the marked remedy, which promises no read or "
              "dispatch, carries no such condition - a qualifier printed on "
              "every refusal would fail here: %r" % (marked[1][-300:],),
              qualifier not in marked[1])
        settle(proj, [hd_rel + "#P1.1#intent diverges"])
        h2 = signoff(proj, "P1", "skipped")
        check("hd25b ...and settling one of the two still refuses, naming only the "
              "one left: %r" % ((h2[0], h2[1][-300:]),),
              h2[0] == M.E_USAGE and read(mpath) == before
              and "red-first not-proved" in h2[1] and "intent diverges" not in h2[1])
        settle(proj, [hd_rel + "#P1.1#intent diverges",
                      hd_rel + "#P1.2#red-first not-proved"])
        h3 = signoff(proj, "P1", "skipped")
        check("hd26 ALLOW: once the settlement records both, the same sign-off "
              "passes and carries the answers onto the tasks - without this half a "
              "verb refusing every `diverges` would pass: %r" % ((h3[0], h3[1][-200:]),),
              h3[0] == 0 and answer(mpath, "P1.1") == "diverges"
              and "the owner read it: fine" in h3[1])
        filed_h3 = _fr.phase_returns(os.path.join(proj, "docs", "audit",
                                                  "evidence"), "P1")
        rec_h3 = (phase(mpath, "P1").get("review") or {}).get(
            _fr.READ_RETURNS_FIELD)
        check("rr1 the verdict records what it read: the sign-off writes the "
              "signature of every filed phase return it read on the phase "
              "review, so a landing can tell a return filed after it from one "
              "it read, wherever either sits: %r" % (rec_h3,),
              isinstance(rec_h3, list) and len(rec_h3) == 1
              and rec_h3[0].get("return") == hd_rel
              and rec_h3[0].get("sha256") == _fr.return_signature(filed_h3[0]))
        read_set_cases()
        bound_cases(settle, hd_rel)

        proj, mpath = two_done("signoff-state-broken")
        file_phase(proj, "P1", _HD_HEAD, [
            _hd_entry("P1.1", _FR_SHA, answer="diverges"),
            _hd_entry("P1.2", _HD_SHA2)])
        settle(proj, [], text="{not json")
        before = read(mpath)
        h4 = signoff(proj, "P1", "skipped")
        check("hd27 a settlement record that will not parse refuses, never reads as "
              "nothing settled or as everything settled: %r" % ((h4[0], h4[1][-200:]),),
              h4[0] == M.E_USAGE and read(mpath) == before
              and "cannot be read" in h4[1])

        proj, mpath = project("signoff-intent-always", [ph("P1", [
            done_tk("P1.1", _FR_SHA, key="always",
                    intentCheck={"answer": "matches", "commit": _FR_SHA})],
            reviewPerTask="always")], "always")
        body = json.loads(_hd_return([]))
        body["intent"] = {"answer": "cannot-tell", "note": "unclear", "missing": []}
        early = verb(proj, "file-return", "P1", "--role", "reviewer", "--head",
                     _HD_HEAD, stdin=json.dumps(body))
        before = read(mpath)
        h5 = signoff(proj, "P1", "skipped")
        unchanged = read(mpath) == before
        settle(proj, [hd_rel + "#phase"])
        h6 = signoff(proj, "P1", "skipped")
        check("hd28 a phase intent of `cannot-tell` refuses sign-off under `always` "
              "too - the phase intent stop is not the `phase` key's - and the same "
              "sign-off passes once it is settled: %r"
              % ((h5[0], h5[1][-200:], h6[0]),),
              h5[0] == M.E_USAGE and "intent cannot-tell" in h5[1]
              and unchanged and h6[0] == 0)
        # A recorded verdict is what close-phase reads as the human having
        # settled every answer that verdict's checkout holds, so a return filed
        # there after it would land an answer nobody was asked about.
        late_body = json.loads(_hd_return([]))
        late_body["intent"] = {"answer": "diverges", "note": "late: missed it",
                               "missing": []}
        before = read(mpath)
        late = verb(proj, "file-return", "P1", "--role", "reviewer", "--head",
                    _HD_HEAD2, stdin=json.dumps(late_body))
        late_path = os.path.join(returns(proj, "P1"),
                                 "%s.reviewer.json" % (_HD_HEAD2,))
        check("hd30 a phase return filed once a sign-off verdict is recorded is "
              "refused, naming the verdict, and writes no file and no plan "
              "byte: %r" % ((late[0], late[1][-240:]),),
              late[0] == M.E_USAGE and "signed off" in late[1]
              and read(late_path) is None and read(mpath) == before)
        check("hd30b THE TWIN: the same phase's return filed before the verdict "
              "was taken - a refusal keyed on the phase alone would refuse it "
              "too: %r" % ((early[0], early[1][-160:]),),
              early[0] == 0 and read(os.path.join(
                  returns(proj, "P1"), "%s.reviewer.json" % (_HD_HEAD,)))
              is not None)
    # ---- a settlement binds to the answer it settled ---------------------------
    # The read set a sign-off records vouches for content, so the settlement it
    # honours must be bound to content too: a name is shared by every answer
    # filed under it.
    def bound_cases(settle, hd_rel):
        key = hd_rel + "#P1.1#intent diverges"
        proj, mpath = two_done("signoff-name-only")
        file_phase(proj, "P1", _HD_HEAD, [
            _hd_entry("P1.1", _FR_SHA, answer="diverges", note="note A"),
            _hd_entry("P1.2", _HD_SHA2)])
        settle(proj, [key], by_name_only=True)
        before = read(mpath)
        named = signoff(proj, "P1", "skipped")
        check("hs1 a settlement recorded by name alone - no signature binding "
              "it to the content the human saw - is not honoured, and the "
              "refusal names how to settle it again so the signature is "
              "recorded: %r" % ((named[0], named[1][-420:]),),
              named[0] == M.E_USAGE and read(mpath) == before
              and "intent diverges" in named[1] and "by name only" in named[1]
              and "drive-phase.py next P1" in named[1])
        settle(proj, [key])
        bound = signoff(proj, "P1", "skipped")
        check("hs1b THE ALLOW TWIN: the same answer settled with its signature "
              "signs off: %r" % ((bound[0], bound[1][-200:]),),
              bound[0] == 0 and answer(mpath, "P1.1") == "diverges")

        proj, mpath = two_done("signoff-other-content")
        file_phase(proj, "P1", _HD_HEAD, [
            _hd_entry("P1.1", _FR_SHA, answer="diverges", note="note A"),
            _hd_entry("P1.2", _HD_SHA2)])
        settle(proj, [key])
        path = os.path.join(proj, "docs", "audit", "evidence", *hd_rel.split("/"))
        with open(path, "r", encoding="utf-8") as fh:
            settled_body = json.load(fh)
        swapped = json.loads(json.dumps(settled_body))
        swapped["tasks"][0]["note"] = "note B: another answer"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(swapped, fh)
        before = read(mpath)
        other = signoff(proj, "P1", "skipped")
        check("hs2 a settlement bound to one answer's signature does not cover "
              "another answer under the same name - the return replaced by "
              "one with another note is refused: %r"
              % ((other[0], other[1][-300:]),),
              other[0] == M.E_USAGE and read(mpath) == before
              and "intent diverges" in other[1])
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(settled_body, fh, indent=2)
        same = signoff(proj, "P1", "skipped")
        check("hs2b THE ALLOW TWIN: ...and with the answer the human settled "
              "back, its bytes laid out anew, the same sign-off passes: %r"
              % ((same[0], same[1][-200:]),),
              same[0] == 0)

        for cid, settled in (("hs3", True), ("hs3b", False)):
            proj, mpath, wt, rel = outside_worktree("signoff-r70-%s" % (cid,))
            if settled:
                settle(wt, [rel + "#phase"])
            before = read(mpath)
            got = signoff(proj, "P1", "skipped")
            if settled:
                check("hs3 A PLAN OUTSIDE THE REPOSITORY, the branch in a linked "
                      "worktree, a phase return committed at its tip and "
                      "settled in that worktree's record: the sign-off run "
                      "from the parent checkout asks the tip's return against "
                      "the settlement records the landing honours, and signs "
                      "off: %r" % ((got[0], got[1][-300:]),),
                      got[0] == 0 and read(mpath) != before)
            else:
                check("hs3b THE TWIN: ...and with no record settling it, the "
                      "same sign-off is refused, writing nothing: %r"
                      % ((got[0], got[1][-300:]),),
                      got[0] == M.E_USAGE and read(mpath) == before
                      and "intent diverges" in got[1])
        unreadable_record_cases(settle)
        tip_remedy_cases()

    # ---- a settlement record that cannot be read --------------------------------
    # It matters only to an answer that waits on a human: a sign-off with
    # nothing to settle reads no settlement, so a broken record anywhere among
    # the checkouts asked does not hold it.
    def names(path, text):
        """Whether `text` names `path`, as given or as git prints it resolved."""
        return path in text or os.path.realpath(path) in text

    def unreadable_record_cases(settle):
        for cid, intent in (("hs4", "diverges"), ("hs4b", "matches")):
            proj, mpath, wt, _rel = outside_worktree("signoff-broken-%s" % (cid,),
                                                     intent)
            settle(wt, [], text="{not json")
            before = read(mpath)
            got = signoff(proj, "P1", "skipped")
            if intent == "diverges":
                check("hs4 a sibling worktree's settlement record that will not "
                      "parse, with an answer waiting on a human: the sign-off is "
                      "refused, naming the answer and that record: %r"
                      % ((got[0], got[1][-600:]),),
                      got[0] == M.E_USAGE and read(mpath) == before
                      and "intent diverges" in got[1]
                      and "cannot be read" in got[1]
                      and os.path.join("drive", "P1.json") in got[1]
                      and names(wt, got[1]))
            else:
                check("hs4b THE ALLOW TWIN: the same broken sibling record with "
                      "no answer only a human settles signs off - refusing over "
                      "a record nothing needs to read would fail here: %r"
                      % ((got[0], got[1][-400:]),),
                      got[0] == 0 and read(mpath) != before)

        proj, mpath = two_done("signoff-own-broken-quiet")
        file_phase(proj, "P1", _HD_HEAD, [_hd_entry("P1.1", _FR_SHA),
                                          _hd_entry("P1.2", _HD_SHA2)])
        settle(proj, [], text="{not json")
        before = read(mpath)
        own = signoff(proj, "P1", "skipped")
        check("hs4c the signing checkout's own record that will not parse, with "
              "nothing waiting on a human, signs off too: %r"
              % ((own[0], own[1][-400:]),),
              own[0] == 0 and read(mpath) != before)

    # ---- a waiting answer only the tip commits ---------------------------------
    # The driver's triage lists the returns in its own checkout's evidence, so a
    # remedy pointing at the triage must name the checkout whose triage lists
    # the answer.
    def tip_remedy_cases():
        import shutil
        import subprocess
        proj, mpath, wt, _rel = outside_worktree("signoff-tip-remedy")
        got = signoff(proj, "P1", "skipped")
        check("hs5 an unsettled answer the tip commits and this checkout's "
              "evidence does not hold: the refusal names the worktree holding "
              "the branch as the checkout whose triage lists it: %r"
              % ((got[0], got[1][-700:]),),
              got[0] == M.E_USAGE and "intent diverges" in got[1]
              and "the worktree holding audit/p1-wt" in got[1]
              and names(wt, got[1]) and "git worktree add" not in got[1])
        subprocess.run(["git", "-C", proj, "worktree", "remove", "--force", wt],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        gone = signoff(proj, "P1", "skipped")
        check("hs5b ...and with no worktree holding the branch, the refusal "
              "names the `git worktree add` that creates one: %r"
              % ((gone[0], gone[1][-700:]),),
              gone[0] == M.E_USAGE and "intent diverges" in gone[1]
              and "git worktree add <dir> audit/p1-wt" in gone[1]
              and not names(wt, gone[1]))

        # The same branch, held by the same worktree, and the same return
        # also in this checkout's evidence: only where the answer sits differs.
        proj, mpath, wt, rel = outside_worktree("signoff-local-remedy")
        held_here = os.path.join(proj, "docs", "audit", "evidence",
                                 *rel.split("/"))
        os.makedirs(os.path.dirname(held_here))
        shutil.copyfile(os.path.join(wt, "docs", "audit", "evidence",
                                     *rel.split("/")), held_here)
        local = signoff(proj, "P1", "skipped")
        check("hs5c THE TWIN: the same unsettled answer held in this "
              "checkout's own evidence as well keeps the plain remedy - naming "
              "another checkout for every answer on a phase branch would fail "
              "here: %r" % ((local[0], local[1][-500:]),),
              local[0] == M.E_USAGE and "intent diverges" in local[1]
              and "git worktree add" not in local[1]
              and "the worktree holding" not in local[1]
              and "drive-phase.py next P1" in local[1])

    def outside_worktree(name, intent="diverges"):
        """`(proj, mpath, wt, rel)` - a git checkout `proj` whose plan lies in
        a directory beside it, P1 on `audit/p1-wt` checked out in the linked
        worktree `wt`, and a phase return answering `intent` for the phase
        committed at that branch's tip from `wt`."""
        import subprocess
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        mpath = os.path.join(root, name + "-plan", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": mpath, "evidence": {"dir": "docs/audit/evidence"},
             "review": {"perTask": "always"}})
        phases = [ph("P1", [done_tk("P1.1", _FR_SHA, key="always", intentCheck={
            "answer": "matches", "commit": _FR_SHA})],
            reviewPerTask="always", branch="audit/p1-wt")]
        index = {}
        for t in phases[0]["tasks"]:
            for f in t["files"]:
                index.setdefault(f, []).append(t["id"])
        _panel_write._atomic_write_json(mpath, {
            "meta": {"version": 2, "buildCommands": {"test": "true"}},
            "phases": phases, "fileIndex": index, "bugs": []})
        with open(os.path.join(proj, ".gitignore"), "w") as fh:
            fh.write(".claude/state/\n")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

        def git(where, *a):
            return subprocess.run(["git", "-C", where] + list(a), env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        git(proj, "init", "-q", "-b", "main")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", "base")
        wt = proj + "-wt"
        git(proj, "worktree", "add", "-q", "-b", "audit/p1-wt", wt)
        body = json.loads(_hd_return([]))
        body["intent"] = {"answer": intent, "missing": [],
                          "note": "the phase missed its outcome"}
        rel = _fr.phase_return_rel("P1", _HD_HEAD)
        path = os.path.join(wt, "docs", "audit", "evidence", *rel.split("/"))
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "the phase return")
        return proj, mpath, wt, rel

    human_answer_cases()

    # ...and so does a fix task moved away from its findings.
    p1 = ph("P1", [tk("P1.1")], review={"findings": [finding("P1-R1")]})
    p2 = ph("P2", [tk("P2.1", status="pending", started=None)],
            status="pending")
    projf, mpathf = project("fix-moved", [p1, p2])
    verb(projf, "add", "fix R1", "--phase", "P1", "--files", "src/f.ts",
         "--fixes", "P1-R1")
    verb(projf, "move", "P1.2", "--to", "P2")
    fm = [t["id"] for t in phase(mpathf, "P2")["tasks"] if t.get("title") == "fix R1"]
    fmid = fm[0] if fm else "missing"
    verb(projf, "start", fmid, "--force", "--reason", "fixture")
    before = read(mpathf)
    r21 = close(projf, fmid, "--intent", "not-asked", *_HD_BASIS)
    check("hd23 a fix task moved to another phase, away from the findings it "
          "names, is no longer a recorded fix task: its not-asked close is "
          "refused, writing nothing: %r" % ((fmid, r21[0], r21[1][-140:]),),
          fmid != "missing" and r21[0] == M.E_USAGE and read(mpathf) == before)

    f6 = verb(proj, "file-return", "P1", "--role", "reviewer",
              stdin=_hd_return([]))
    f7 = verb(proj, "file-return", "P1.2", "--role", "reviewer", "--head",
              _HD_HEAD, stdin=_hd_return([]))
    check("hd21 a phase return needs `--head`, the head its brief was computed "
          "at, and a task's return takes none: %r" % ((f6[0], f7[0]),),
          f6[0] == M.E_USAGE and "--head" in f6[1]
          and f7[0] == M.E_USAGE and "--head" in f7[1])

    # A recorded fix task's close under `phase` has one form. With no --intent
    # it would record `deferred`, an answer the phase review never owes a fix
    # task, so sign-off could then never pass.
    projx, mpathx = project("fix-deferred", [ph("P1", [tk("P1.1")], review={
        "findings": [finding("P1-R1")]})])
    verb(projx, "add", "fix R1", "--phase", "P1", "--files", "src/f.ts",
         "--fixes", "P1-R1")
    verb(projx, "start", "P1.2")
    before = read(mpathx)
    r22 = close(projx, "P1.2")
    after = read(mpathx)
    r23 = close(projx, "P1.2", "--intent", "not-asked", *_HD_BASIS)
    check("hd24 under `phase`, a recorded fix task closed with no --intent is "
          "refused naming `--intent not-asked --intent-basis`, writing nothing, "
          "and the same task closed that way closes: %r"
          % ((r22[0], r22[1][-160:], r23[0]),),
          r22[0] == M.E_USAGE and "--intent not-asked" in r22[1]
          and "--intent-basis" in r22[1] and after == before
          and r23[0] == 0 and answer(mpathx, "P1.2") == "not-asked")


def _batch_doc(**over):
    """A planning file in the shape `add --from-file` reads: the request as
    typed, its open choices, one phase and two tasks, the second waiting on the
    first by its key and the first on a task the plan already holds."""
    doc = {"request": "  Make refunds exact.\nKeep the API as it is.  ",
           "openChoices": ["round half-even or half-up"],
           "phase": {"title": "Exact refunds",
                     "desiredOutcome": "refunds sum to the cent"},
           "tasks": [{"key": "sum", "title": "sum in integer cents",
                      "files": ["src/b.ts"], "dependsOn": ["P1.1"],
                      "tests": {"mode": "tdd",
                                "add": ["tests/b.test.ts: sums exactly"]}},
                     {"title": "document the rounding", "files": ["docs/b.md"],
                      "dependsOn": ["sum"]}]}
    doc.update(over)
    return doc


def _phase_section(text, lead):
    """The `## ` section of a command body whose heading starts with `lead`."""
    start = text.find("\n## " + lead)
    end = text.find("\n## ", start + 1)
    return text[start:end if end > start else len(text)] if start >= 0 else ""


def _phase_add_gaps(text):
    """What the `add` section of commands/phase.md fails to name, as sentences:
    a `phase` key the batch file takes, a flag the hint gives `add`, or
    `add-phase` beside `--park`. Empty is the one answer that passes."""
    import re
    section = _phase_section(text, "Subcommand: `add")
    if not section:
        return ["no `add` section"]
    hint = re.search(r"^argument-hint: '(.*)'$", text, re.M)
    add = [part for part in (hint.group(1) if hint else "").split(" | ")
           if part.startswith("add ")]
    gaps = ([] if add else ["the hint gives no `add` form"])
    gaps += ["the `phase` key %r" % (key,) for key in M.BATCH_PHASE_KEYS
             if '"%s"' % (key,) not in section]
    gaps += ["the flag %s" % (flag,) for flag in
             sorted(set(re.findall(r"--[a-z][a-z-]*", add[0] if add else "")))
             if flag not in section]
    park = section.find("--park")
    if park < 0 or "add-phase" not in section[park:park + 160]:
        gaps.append("`add-phase` beside `--park`")
    return gaps


def _phase_run_gaps(text):
    """What the run section of commands/phase.md fails to name: the preview's
    `audit-status.py --phase` and the `not started yet` reading."""
    import re
    section = _phase_section(text, "Run a phase")
    if not section:
        return ["no run section"]
    gaps = []
    if not re.search(r'audit-status\.py"? --phase', section):
        gaps.append("`audit-status.py --phase`")
    if "not started yet" not in section:
        gaps.append("`not started yet`")
    return gaps


def _batch_cases(check):
    """`add --from-file`: a phase and its tasks from one file in one write, the
    request saved verbatim beside its open choices, and a malformed file or a
    dependency the plan does not hold refused with nothing written."""
    root = _harness.fixture_root("audit-task-fb-")

    def project(name, sharded=False):
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json"})
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        plan = {"meta": {"version": 2, "buildCommands": {"test": "true"}},
                "phases": [{"id": "P1", "title": "Live", "status": "pending",
                            "testGate": ["test"], "tasks": [
                                {"id": "P1.1", "title": "a",
                                 "status": "pending", "files": ["src/a.ts"],
                                 "attempts": 0, "maxAttempts": 3}]}],
                "fileIndex": {"src/a.ts": ["P1.1"]}, "bugs": []}
        if sharded:
            _mio.save_sharded(mpath, plan)
        else:
            _panel_write._atomic_write_json(mpath, plan)
        return proj, mpath

    def batch(proj, doc, raw=None):
        path = os.path.join(proj, "plan-batch.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(raw if raw is not None else json.dumps(doc, indent=1))
        return path

    def tree_bytes(proj):
        """Every file under the plan's directory, by relative path - a refused
        batch must leave each one as it was and add none."""
        base = os.path.join(proj, "docs", "audit")
        seen = {}
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                full = os.path.join(dirpath, name)
                with open(full, "rb") as fh:
                    seen[os.path.relpath(full, base)] = fh.read()
        return seen

    def phase_of(mpath, pid):
        for ph in _mio.load_manifest(mpath).get("phases") or []:
            if ph.get("id") == pid:
                return ph
        return None

    proj, mpath = project("valid")
    doc = _batch_doc()
    code, txt = _cli(["add", "--from-file", batch(proj, doc)], proj)
    ph = phase_of(mpath, "P2") or {}
    tasks = dict((t.get("id"), t) for t in ph.get("tasks") or [])
    written = _mio.load_manifest(mpath)
    findings = M._validator().validate(written)[0]
    check("fb1 a valid file writes the phase and its tasks in one call: the "
          "request byte for byte, its open choices, each task under an "
          "allocated id with a key resolved to that id and a plan id kept, "
          "the fileIndex rows, and a plan the validator passes: %r"
          % ((code, txt, sorted(tasks), findings),),
          code == 0 and ph.get("request") == doc["request"]
          and ph.get("openChoices") == doc["openChoices"]
          and ph.get("desiredOutcome") == "refunds sum to the cent"
          and sorted(tasks) == ["P2.1", "P2.2"]
          and tasks["P2.1"].get("dependsOn") == ["P1.1"]
          and tasks["P2.2"].get("dependsOn") == ["P2.1"]
          and tasks["P2.1"]["tests"]["mode"] == "tdd"
          and "tests/b.test.ts" in tasks["P2.1"]["files"]
          and written["fileIndex"].get("src/b.ts") == ["P2.1"]
          and findings == [])
    check("fb2 ...said in one success line naming the phase, its tasks and "
          "the file written, with the gate basis the write decided on a line "
          "of its own: %r" % (txt,),
          txt.startswith("[audit-task] phase P2 added with P2.1, P2.2")
          and "written: docs/audit/audit-plan.json" in txt.splitlines()[0]
          and [ln for ln in txt.splitlines()[1:]]
          == ["gate: test (from meta.buildCommands)"])

    proj, mpath = project("sharded", sharded=True)
    code, txt = _cli(["add", "--from-file", batch(proj, _batch_doc())], proj)
    stubs = [s.get("id") for s in _mio.read_json(mpath).get("phases") or []]
    shard = os.path.join(os.path.dirname(mpath), "phases", "P2.json")
    check("fb3 in the sharded layout the batch writes the new phase's shard "
          "and its index stub, tasks inside the shard: %r"
          % ((code, txt, stubs),),
          code == 0 and stubs == ["P1", "P2"] and os.path.isfile(shard)
          and [t.get("id") for t in _mio.read_json(shard).get("tasks") or []]
          == ["P2.1", "P2.2"])

    proj, mpath = project("no-choices")
    code, txt = _cli(["add", "--from-file",
                      batch(proj, _batch_doc(openChoices=[]))], proj)
    check("fb4 ALLOW: an empty list of open choices is an answer, and is "
          "written as one: %r" % ((code, txt),),
          code == 0 and (phase_of(mpath, "P2") or {}).get("openChoices") == [])

    proj, mpath = project("not-json")
    before = tree_bytes(proj)
    code, txt = _cli(["add", "--from-file",
                      batch(proj, None, raw='{"request": "x", ')], proj)
    check("fb5 a file that is not JSON is refused and nothing is written: %r"
          % ((code, txt),),
          code == M.E_USAGE and "cannot read it as JSON" in txt
          and tree_bytes(proj) == before)

    proj, mpath = project("shape")
    before = tree_bytes(proj)
    bad = _batch_doc()
    del bad["openChoices"]
    bad["tasks"][1]["dependOn"] = ["sum"]
    code, txt = _cli(["add", "--from-file", batch(proj, bad)], proj)
    check("fb6 a malformed file is refused naming every fault - the missing "
          "open choices and the misspelt key - and nothing is written: %r"
          % ((code, txt),),
          code == M.E_USAGE and "openChoices" in txt and "dependOn" in txt
          and tree_bytes(proj) == before)

    proj, mpath = project("missing-dep")
    before = tree_bytes(proj)
    gone = _batch_doc()
    gone["tasks"][1]["dependsOn"] = ["sum", "P9.9"]
    code, txt = _cli(["add", "--from-file", batch(proj, gone)], proj)
    check("fb7 a task naming a dependency the plan does not hold is refused "
          "by that name, and nothing is written - the allow twin is fb1, "
          "whose key and plan id both resolve: %r" % ((code, txt),),
          code == M.E_USAGE and "P9.9" in txt and "'sum'" not in txt
          and tree_bytes(proj) == before)

    proj, mpath = project("stray-flag")
    before = tree_bytes(proj)
    code, txt = _cli(["add", "--from-file", batch(proj, _batch_doc()),
                      "--files", "src/c.ts"], proj)
    check("fb8 a task flag beside --from-file is refused rather than applied "
          "to some of the tasks, and nothing is written: %r" % ((code, txt),),
          code == M.E_USAGE and "--files" in txt
          and tree_bytes(proj) == before)

    schema_path = os.path.join(_output.PLUGIN_ROOT, "schema",
                               "audit-plan.schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        props = json.load(fh)["$defs"]["phase"]["properties"]
    check("fb9 the plan's schema names the saved request and its open "
          "choices on the phase, the fields the phase reviewer's brief reads: "
          "%r" % ((props.get("request"), props.get("openChoices")),),
          (props.get("request") or {}).get("type") == "string"
          and (props.get("openChoices") or {}).get("type") == "array"
          and ((props.get("openChoices") or {}).get("items") or {})
          .get("type") == "string")

    with open(os.path.join(_output.PLUGIN_ROOT, "commands", "phase.md"),
              encoding="utf-8") as fh:
        doc_text = fh.read()
    head = doc_text.split("\n---", 1)[0]
    start = doc_text.find("\n## Subcommand: `add")
    end = doc_text.find("\n## ", start + 1)
    section = doc_text[start:end] if start >= 0 and end > start else ""
    import re
    heredoc = re.findall(r"add --from-file - <<'([A-Z]+)'", section)
    check("fb10 the `add` section of commands/phase.md is the batch's own: it "
          "names `add --from-file -` under exactly one quoted heredoc word, "
          "sends the main loop to no file tool for the plan, the command may "
          "still run Bash, and the section is at most 8000 bytes: %r"
          % ((len(section.encode("utf-8")), heredoc,
              "Write tool" in section),),
          len(heredoc) == 1 and "Write tool" not in section
          and "allowed-tools:" in head
          and "Bash" in head.split("allowed-tools:", 1)[1].splitlines()[0]
          and 0 < len(section.encode("utf-8")) <= 8000)
    gaps = _phase_add_gaps(doc_text)
    check("fb11 the `add` section of commands/phase.md names every `phase` key "
          "the batch file takes, every flag the hint gives `add`, and "
          "`add-phase` beside `--park` - the main loop reads no other text "
          "before writing the file: %r" % (gaps,),
          gaps == [])
    gaps = _phase_run_gaps(doc_text)
    check("fb12 the run section of commands/phase.md names the preview's "
          "`audit-status.py --phase` and reads a phase with no branch as `not "
          "started yet`: %r" % (gaps,), gaps == [])
    _batch_stdin_cases(check, project, batch, tree_bytes, section, heredoc)


def _cli_in(argv, cwd, text, env_over=None):
    """`_cli` with `text` on stdin - the way a heredoc reaches the verb."""
    import subprocess
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    env.update(env_over or {})
    done = subprocess.run(
        [sys.executable, _loader.script_path("audit-task.py")] + argv,
        cwd=cwd, env=env, input=text, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, universal_newlines=True, encoding="utf-8")
    return done.returncode, done.stdout


def _plan_bytes(proj):
    """The plan's own files under docs/audit, by relative path. The journal is
    left out: its rows carry the moment they were written, so two runs of
    one write never agree there and the comparison is about the plan."""
    base = os.path.join(proj, "docs", "audit")
    seen = {}
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "journal"]
        for name in files:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as fh:
                seen[os.path.relpath(full, base)] = fh.read()
    return seen


def _bash_hooks():
    """`[(event, script), ...]` - every hook hooks.json routes a Bash call to,
    read from the file the host reads, so a guard added there is asked too."""
    with open(os.path.join(_output.PLUGIN_ROOT, "hooks", "hooks.json"),
              encoding="utf-8") as fh:
        table = json.load(fh)["hooks"]
    out = []
    for event in ("PreToolUse", "PostToolUse"):
        for group in table.get(event) or []:
            if not _matches_bash(group.get("matcher", "")):
                continue
            for hook in group.get("hooks") or []:
                parts = hook.get("command", "").split()
                name = [p for p in parts if p.endswith(".py")]
                if name:
                    out.append((event, name[0]))
    return out


def _matches_bash(matcher):
    import re
    return bool(matcher) and re.fullmatch("(?:%s)" % (matcher,), "Bash") is not None


def _hook_refusal(event, script, command, proj):
    """`None` when the hook lets `command` through, else what it said: a
    non-zero exit, a `deny`/`ask` permission decision, or a `block`."""
    import subprocess
    payload = {"hook_event_name": event, "tool_name": "Bash", "cwd": proj,
               "tool_input": {"command": command}, "session_id": "fb-stdin"}
    if event == "PostToolUse":
        payload["tool_response"] = {"stdout": "", "stderr": "",
                                    "interrupted": False}
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    env["CLAUDE_PROJECT_DIR"] = proj
    env["CLAUDE_PLUGIN_ROOT"] = _output.PLUGIN_ROOT
    done = subprocess.run(
        [sys.executable, os.path.join(_output.PLUGIN_ROOT, "hooks", script)],
        cwd=proj, env=env, input=json.dumps(payload), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, universal_newlines=True, encoding="utf-8")
    said = (done.stdout or "").strip()
    try:
        verdict = json.loads(said) if said else {}
    except ValueError:
        verdict = {}
    spec = verdict.get("hookSpecificOutput") or {}
    if (done.returncode != 0
            or spec.get("permissionDecision") in ("deny", "ask")
            or verdict.get("decision") == "block"):
        return "%s exit %d: %s %s" % (script, done.returncode, said[:200],
                                      (done.stderr or "")[-200:])
    return None


def _batch_stdin_cases(check, project, batch, tree_bytes, section, heredoc):
    """`add --from-file -`: the plan batch read off stdin, so planning writes
    no file of its own - through the checks and the single revalidated write
    the file form has, and as the form commands/phase.md shows."""
    doc = _batch_doc()
    text = json.dumps(doc, indent=1)
    proj_f, mpath_f = project("from-file", sharded=True)
    code_f, txt_f = _cli(["add", "--from-file", batch(proj_f, doc)], proj_f)
    proj_s, mpath_s = project("from-stdin", sharded=True)
    code_s, txt_s = _cli_in(["add", "--from-file", "-"], proj_s, text)
    plan_f, plan_s = _plan_bytes(proj_f), _plan_bytes(proj_s)
    shard = _mio.read_json(os.path.join(os.path.dirname(mpath_s), "phases",
                                        "P2.json")) if code_s == 0 else {}
    check("fb13 the same batch on stdin and from a file writes byte-identical "
          "plans, the request kept verbatim and every open choice counted: %r"
          % ((code_f, code_s, txt_s, sorted(plan_s)),),
          code_f == 0 and code_s == 0 and plan_s == plan_f
          and "phases/P2.json" in [p.replace(os.sep, "/") for p in plan_s]
          and shard.get("request") == doc["request"]
          and len(shard.get("openChoices") or []) == len(doc["openChoices"])
          and shard.get("openChoices") == doc["openChoices"])

    proj, _mpath = project("stdin-shape")
    before = tree_bytes(proj)
    bad = _batch_doc()
    del bad["openChoices"]
    code, txt = _cli_in(["add", "--from-file", "-"], proj, json.dumps(bad))
    empty = _cli_in(["add", "--from-file", "-"], proj, "")
    check("fb14 a malformed batch on stdin is refused naming the field and "
          "stdin as its source, an empty stdin is refused as empty rather "
          "than read as nothing to add, and the plan's bytes are unchanged - "
          "the allow twin is fb13: %r" % ((code, txt, empty),),
          code == M.E_USAGE and "openChoices" in txt
          and "the batch on stdin" in txt and "nothing written" in txt
          and empty[0] == M.E_USAGE and "stdin was empty" in empty[1]
          # Read as `{}`, an empty stdin would be refused for every missing
          # field instead - the wrong fault named, which this tells apart.
          and "openChoices" not in empty[1]
          and tree_bytes(proj) == before)

    # The command exactly as the add section spells it, with `S` expanded the
    # way the section's own preamble defines it and the batch as its body.
    import re
    shown = re.search(r"`(S/manifest/audit-task\.py\" add --from-file - "
                      r"<<'([A-Z]+)')`", section)
    command = None
    if shown and len(heredoc) == 1:
        command = (shown.group(1).replace(
            "S/", 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/', 1)
            + "\n" + text + "\n" + shown.group(2) + "\n")
    proj_h, _mh = project("heredoc", sharded=True)
    ran = None
    if command:
        import subprocess
        env = dict((k, v) for k, v in os.environ.items()
                   if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
        env["CLAUDE_PLUGIN_ROOT"] = _output.PLUGIN_ROOT
        ran = subprocess.run(["sh", "-c", command], cwd=proj_h, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, encoding="utf-8")
    gate = None
    tool = os.path.join(_output.REPO_ROOT, "tools", "measure-context.py")
    if os.path.isfile(tool):
        import subprocess
        gate = subprocess.run(
            [sys.executable, tool, "--gate", "--tree", _output.PLUGIN_ROOT],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, encoding="utf-8")
    check("fb15 the heredoc the add section shows, run by a shell as written, "
          "writes the plan the file form writes, and `measure-context.py "
          "--gate` still holds every entry the command loads under its "
          "ceiling: %r" % ((command and command[:90],
                            ran and (ran.returncode, ran.stdout[-160:]),
                            gate and (gate.returncode, gate.stdout[-300:])),),
          ran is not None and ran.returncode == 0
          and _plan_bytes(proj_h) == plan_f
          and gate is not None and gate.returncode == 0
          and "GATE OK" in gate.stdout)

    hooks = _bash_hooks()
    proj_g, _mg = project("guards")
    refused = [(e, s, why) for e, s in hooks
               for why in [_hook_refusal(e, s, command or "", proj_g)] if why]
    # The over-fire twin: the same runner must SEE a refusal when a guard
    # gives one, or an empty `refused` would be a reader that never looks.
    control = _hook_refusal("PreToolUse", "guard-secrets-read.py",
                            "cat .env", proj_g)
    check("fb16 every hook hooks.json routes Bash to, given the add section's "
          "heredoc as its payload, refuses nothing - and the same reader sees "
          "the secrets guard refuse `cat .env`: %r"
          % ((sorted(set(s for _e, s in hooks)), refused, control),),
          command is not None and len(hooks) >= 2
          and "guard-secrets-read.py" in [s for _e, s in hooks]
          and refused == [] and control is not None)


def _unblock_cases(check):
    """`unblock <id> --reason`: the way past a task whose attempts are spent.
    `start` refuses one past `maxAttempts`, `--force` included, and the hand
    edit that reset the count is what the verbs replace - so the reset is a
    verb, takes a human's reason, and is journaled."""
    import _journal_io
    root = _harness.fixture_root("audit-task-ub-")

    def tk(tid, status, attempts, **over):
        task = {"id": tid, "title": tid, "status": status,
                "description": "do " + tid, "files": ["src/%s.ts" % (tid,)],
                "tests": {"mode": "gate-only", "add": [],
                          "expectRedFirst": False, "gate": ["test"]},
                "attempts": attempts, "maxAttempts": 3}
        if attempts:
            task["startedAt"] = "2026-01-01T00:00:00Z"
        task.update(over)
        return task

    def project(name, tasks):
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json",
             "review": {"perTask": "always"}})
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        index = dict((t["files"][0], [t["id"]]) for t in tasks)
        _panel_write._atomic_write_json(mpath, {
            "meta": {"version": 2, "buildCommands": {"test": "true"}},
            "phases": [{"id": "P1", "title": "P1", "status": "in_progress",
                        "testGate": ["test"], "tasks": tasks}],
            "fileIndex": index, "bugs": []})
        return proj, mpath

    def verb(proj, *argv):
        lines = []
        code = M.main(list(argv) + ["--project-dir", proj], out=lines.append)
        return code, "\n".join(str(x) for x in lines)

    def task(mpath, tid):
        return _mio.tasks_by_id(_mio.load_manifest(mpath)).get(tid) or {}

    def read(path):
        with open(path, "rb") as fh:
            return fh.read()

    try:
        proj, mpath = project("blocked", [
            tk("P1.1", "blocked", 3, blockedReason="attempts exhausted"),
            tk("P1.2", "pending", 0), tk("P1.3", "done", 1, commit="a" * 40),
            tk("P1.4", "in_progress", 3),
            tk("P1.5", "blocked", 1, blockedReason="waiting on the API")])
        refused_start = verb(proj, "start", "P1.1", "--force", "--reason", "x")
        before = read(mpath)
        nr = verb(proj, "unblock", "P1.1")
        fresh = verb(proj, "unblock", "P1.2", "--reason", "r")
        closed = verb(proj, "unblock", "P1.3", "--reason", "r")
        whole = verb(proj, "unblock", "P1", "--reason", "r")
        waiting = verb(proj, "unblock", "P1.5", "--reason", "r")
        check("ub1 `unblock` with no reason, of a task with attempts left, of "
              "one blocked for another reason with attempts left (its count is "
              "not this verb's to reset), of a done task and of a phase id is "
              "refused, and nothing is written: %r"
              % ([(r[0], r[1][-90:]) for r in (nr, fresh, waiting, closed,
                                                whole)],),
              [r[0] for r in (nr, fresh, waiting, closed, whole)]
              == [M.E_USAGE] * 5
              and "--reason" in nr[1] and "start P1.2" in fresh[1]
              and "start P1.5" in waiting[1] and read(mpath) == before)
        code, text = verb(proj, "unblock", "P1.1", "--reason",
                          "the human read the red and says try again")
        t1 = task(mpath, "P1.1")
        rows = [r for r in _journal_io.read_all(proj)
                if r.get("action") == "task.unblock"]
        started = verb(proj, "start", "P1.1")
        check("ub2 ALLOW: a blocked task whose attempts are spent is put back to "
              "pending with its count reset and its block reason cleared, one "
              "task.unblock row carries the reason, and the `start` refused "
              "before it now runs: %r"
              % ((refused_start[0], code, t1.get("status"), t1.get("attempts"),
                  len(rows), started[0], text[:160]),),
              refused_start[0] == M.E_USAGE and code == 0
              and t1.get("status") == "pending" and t1.get("attempts") == 0
              and "blockedReason" not in t1 and len(rows) == 1
              and (rows[0].get("details") or {}).get("reason")
              == "the human read the red and says try again"
              and started[0] == 0)
        code, _text = verb(proj, "unblock", "P1.4", "--reason", "go on")
        t4 = task(mpath, "P1.4")
        check("ub3 ALLOW: a running task whose attempts are spent, never set "
              "blocked, has its count reset and stays running - the unblock "
              "is of the count, and a rule reading status alone refuses it: %r"
              % ((code, t4.get("status"), t4.get("attempts")),),
              code == 0 and t4.get("status") == "in_progress"
              and t4.get("attempts") == 0)
        doc = M.__doc__ or ""
        check("ub4 the verb is in the usage block and in VERB_FLAGS with "
              "`--reason` its one flag: %r" % (M.VERB_FLAGS.get("unblock"),),
              "audit-task.py unblock <taskId> --reason" in doc
              and M.VERB_FLAGS.get("unblock") == ("reason",))
    finally:
        _harness.remove_tree(root)


def _no_change_moved_cases(check):
    """`done --no-change` is a claim that the task's files did not need to
    change. A task with no commit is never asked the landing property, so the
    claim is checked against git: a commit since the task's start touching one
    of its files, or an uncommitted change to one, refuses it."""
    import subprocess
    root = _harness.fixture_root("audit-task-ncm-")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(proj, *argv, **kw):
        e = dict(env)
        if kw.get("date"):
            e["GIT_AUTHOR_DATE"] = e["GIT_COMMITTER_DATE"] = kw["date"]
        return subprocess.run(["git", "-C", proj] + list(argv), env=e,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(proj, rel, text):
        path = os.path.join(proj, *rel.split("/"))
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            fh.write(text)

    def project(name):
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json",
             "review": {"perTask": "always"}})
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        task = {"id": "P1.1", "title": "t", "status": "in_progress",
                "description": "d", "files": ["src/a.ts"],
                "tests": {"mode": "gate-only", "add": [],
                          "expectRedFirst": False, "gate": ["test"]},
                "attempts": 1, "maxAttempts": 3,
                "startedAt": "2026-01-01T00:00:00Z"}
        _panel_write._atomic_write_json(mpath, {
            "meta": {"version": 2, "buildCommands": {"test": "true"}},
            "phases": [{"id": "P1", "title": "P1", "status": "in_progress",
                        "testGate": ["test"], "tasks": [task]}],
            "fileIndex": {"src/a.ts": ["P1.1"]}, "bugs": []})
        git(proj, "init", "-q", "-b", "main")
        write(proj, "src/a.ts", "a\n")
        write(proj, "src/b.ts", "b\n")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", "base", date="2025-06-01T00:00:00Z")
        return proj, mpath

    def close(proj):
        lines = []
        code = M.main(["done", "P1.1", "--no-change", "--reason", "nothing to do",
                       "--project-dir", proj], out=lines.append)
        return code, "\n".join(str(x) for x in lines)

    def read(path):
        with open(path, "rb") as fh:
            return fh.read()

    try:
        proj, mpath = project("committed")
        write(proj, "src/a.ts", "changed\n")
        git(proj, "commit", "-q", "-am", "work", date="2026-02-01T00:00:00Z")
        before = read(mpath)
        code, text = close(proj)
        check("ncm1 a commit since the task's start touching its file refuses "
              "`--no-change`, naming the file, and writes nothing: %r"
              % ((code, text[:200]),),
              code == M.E_USAGE and "src/a.ts" in text and read(mpath) == before)
        proj, mpath = project("dirty")
        write(proj, "src/a.ts", "uncommitted\n")
        before = read(mpath)
        code, text = close(proj)
        check("ncm2 an uncommitted change to the task's file refuses it too, "
              "writing nothing: %r" % ((code, text[:200]),),
              code == M.E_USAGE and "src/a.ts" in text and read(mpath) == before)
        proj, mpath = project("unmoved")
        write(proj, "src/b.ts", "another task's\n")
        git(proj, "commit", "-q", "-am", "other", date="2026-02-01T00:00:00Z")
        code, text = close(proj)
        check("ncm3 ALLOW: the task's file last changed BEFORE its start, and "
              "a commit since touching another file only, closes no-change - "
              "a check reading all of history, or every file, would refuse "
              "this: %r" % ((code, text[:200]),),
              code == 0)
        _no_change_layout_cases(check, project, git, write, close, read)
    finally:
        _harness.remove_tree(root)


def _no_change_layout_cases(check, project, git, write, close, read):
    """The two ways the check used to miss or over-reach: a git repository in a
    subdirectory of the project, whose task files are project-relative, and a
    sibling's commit dated at or after this task's start but made before it."""
    def replan(mpath, edit):
        plan = _mio.load_manifest(mpath)
        edit(plan)
        _panel_write._atomic_write_json(mpath, plan)

    def sub_root(proj, mpath):
        """Move the fixture's repository into `app/`, the config's gitRoot,
        with the task's file declared project-relative."""
        import shutil
        app = os.path.join(proj, "app")
        os.makedirs(app)
        shutil.move(os.path.join(proj, ".git"), os.path.join(app, ".git"))
        shutil.move(os.path.join(proj, "src"), os.path.join(app, "src"))
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json", "gitRoot": "app",
             "review": {"perTask": "always"}})
        git(app, "add", "-A")
        git(app, "commit", "-q", "-m", "moved", date="2025-06-02T00:00:00Z")

        def files(plan):
            plan["phases"][0]["tasks"][0]["files"] = ["app/src/a.ts"]
            plan["fileIndex"] = {"app/src/a.ts": ["P1.1"]}
        replan(mpath, files)
        return app

    proj, mpath = project("subroot-moved")
    app = sub_root(proj, mpath)
    write(app, "src/a.ts", "changed\n")
    git(app, "commit", "-q", "-am", "work", date="2026-02-01T00:00:00Z")
    before = read(mpath)
    code, text = close(proj)
    check("ncm4 with the repository in a subdirectory (`gitRoot`), a commit "
          "since the start touching the task's project-relative file refuses "
          "`--no-change` - each entry is read relative to the git root, as the "
          "task commit stages it: %r" % ((code, text[:240]),),
          code == M.E_USAGE and "src/a.ts" in text and read(mpath) == before)
    proj, mpath = project("subroot-other")
    app = sub_root(proj, mpath)
    write(app, "src/b.ts", "another task's\n")
    git(app, "commit", "-q", "-am", "other", date="2026-02-01T00:00:00Z")
    code, text = close(proj)
    check("ncm4b ALLOW: the same layout with a commit touching another file "
          "only closes no-change: %r" % ((code, text[:200]),), code == 0)

    def unstarted(plan):
        """The task not yet started, in a phase that started earlier: its
        `baseRef` is the fixture's base commit, so the phase's own bound does
        not stand in for the task's."""
        task = plan["phases"][0]["tasks"][0]
        task.update(status="pending", attempts=0)
        task.pop("startedAt", None)
        plan["phases"][0]["baseRef"] = base_of[0]

    def start(proj):
        lines = []
        code = M.main(["start", "P1.1", "--project-dir", proj],
                      out=lines.append)
        return code, "\n".join(str(x) for x in lines)

    base_of = [None]
    proj, mpath = project("start-head")
    base_of[0] = git(proj, "rev-parse", "HEAD").stdout.decode().strip()
    replan(mpath, unstarted)
    # A sibling's commit made BEFORE this start, dated after it: the date a
    # commit carries is not when it entered this branch.
    write(proj, "src/a.ts", "the sibling's\n")
    git(proj, "commit", "-q", "-am", "sibling", date="2099-01-01T00:00:00Z")
    s1 = start(proj)
    code, text = close(proj)
    check("ncm5 a commit already in HEAD when the task started does not refuse "
          "its `--no-change`, whatever date it carries - the span starts at "
          "the head the start recorded: start %r, close %r"
          % (s1[0], (code, text[:240])),
          s1[0] == 0 and code == 0)
    proj, mpath = project("start-head-after")
    base_of[0] = git(proj, "rev-parse", "HEAD").stdout.decode().strip()
    replan(mpath, unstarted)
    s2 = start(proj)
    write(proj, "src/a.ts", "this task's\n")
    git(proj, "commit", "-q", "-am", "work", date="2020-01-01T00:00:00Z")
    before = read(mpath)
    code, text = close(proj)
    check("ncm5b ...and a commit made after the start refuses it, even dated "
          "before the start - a span still cut by committer date would pass "
          "it: start %r, close %r" % (s2[0], (code, text[:240])),
          s2[0] == 0 and code == M.E_USAGE and "src/a.ts" in text
          and read(mpath) == before)

    proj, mpath = project("sibling-commit")
    write(proj, "src/a.ts", "the sibling's\n")
    git(proj, "commit", "-q", "-am", "sibling", date="2026-02-01T00:00:00Z")
    sib = git(proj, "rev-parse", "HEAD").stdout.decode().strip()

    def sibling(plan):
        plan["phases"][0]["tasks"].append(
            {"id": "P1.2", "title": "s", "status": "done", "description": "d",
             "files": ["src/a.ts"], "commit": sib,
             "completedAt": "2026-02-01T00:00:00Z",
             "tests": {"mode": "gate-only", "add": [],
                       "expectRedFirst": False, "gate": ["test"]},
             "attempts": 1, "maxAttempts": 3,
             "startedAt": "2026-01-01T00:00:00Z"})
        plan["fileIndex"]["src/a.ts"] = ["P1.1", "P1.2"]
    replan(mpath, sibling)
    code, text = close(proj)
    check("ncm6 with no start head recorded, a commit another task records as "
          "its own is that task's work and does not refuse this one's "
          "`--no-change` (ncm1 is the refusal beside it): %r"
          % ((code, text[:240]),), code == 0)


STAGES = (("at-block", "_cases"), ("sl-block", "_success_line_cases"),
          ("fr-block", "_return_cases"), ("fb-block", "_batch_cases"),
          ("hd-block", "_held_cases"), ("ub-block", "_unblock_cases"),
          ("ncm-block", "_no_change_moved_cases"))


def _selftest(only=()):
    """Every block, or only the ones `--stage <label>` names - a narrowed run a
    red-first proof in a throwaway tree can afford."""
    unknown = [o for o in only if o not in dict(STAGES)]

    def body(check):
        if unknown:
            check("--stage names a block of this suite: %r" % (unknown,), False)
        # Each block staged, so one that raises still lets the other run.
        for label, fn in STAGES:
            if not only or label in only:
                _harness.stage(check, label, globals()[fn])
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        args = sys.argv[1:]
        raise SystemExit(_selftest([args[i + 1] for i, a in enumerate(args[:-1])
                                    if a == "--stage"]))
    sys.stderr.write("usage: test_audit_task.py --selftest [--stage LABEL ...]\n")
    raise SystemExit(2)
