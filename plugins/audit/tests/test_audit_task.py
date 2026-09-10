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
import _output                                     # noqa: E402  (SCRIPTS_DIR, to read a sibling's source)
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
# verb, both layouts), w (the _waiting_on index), u (usage errors), sc (scope,
# the F189 verb), rt (retarget, the F190 verb), gc (F196: the empty gate a task
# could not reach), jf (F197: the prior state the trail attests), ag (F201: the
# empty gate at CREATION), fn (F202: the files row for a change that did not
# happen), sf (F199: the three task fields `scope` did not reach), sn (F208: the
# task with no `tests` object), qg (F207: add-phase's empty gate), wd (F271: the
# widening `scope` refused on the very task it exists for), pb (F275: the owning
# phase's blockedBy, the readiness term this file's own copy never carried),
# eb (F285: the brief a shell had already eaten, and the stdin route out).
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
                          # The DOCUMENTED shape, `<path>: <what it asserts>`
                          # (F294). It used to be a bare sentence here, and the
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
        # F258. The case named in `tests.add` is a file this task CREATES, so a
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
              "sentence around it, which is F294: %r" % (t.get("files"),),
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

        # ---- (tp) F294: the files union takes the PATH, or nothing -----------
        # THE FIXTURES ARE THIS REPOSITORY'S OWN `tests.add` STRINGS, both
        # shapes, because the premise F258 wrote down ("a tdd task creates the
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
        # the path shape, and `_manifest_rules._check_tests_add_shape` says so.
        #
        # IT IS A WARNING THROUGH THE 2.x LINE AND THIS CASE ASSERTS THE WRITE
        # SUCCEEDS. That is the direction it was written in an hour ago and it
        # asserted the opposite - refused, rolled back, exit 1 - so it is
        # DRIVEN rather than edited: `COMPATIBILITY.md` promises a manifest
        # that validates keeps validating through the major line, and refusing
        # here would break that promise for a field the schema documents as
        # free prose. The refusal arrives at 3.0.0 and the warning is what
        # announces it, which is why the text has to carry the release.
        with open(_tp_mp, "rb") as _fh:
            _tp_before = _fh.read()
        code, _tp_tdd = run(["add", "Tdd with prose", "--phase", "P2",
                             "--project-dir", _tp_proj,
                             "--tests-mode", "tdd",
                             "--tests-add", _TP_PROSE])
        with open(_tp_mp, "rb") as _fh:
            _tp_after = _fh.read()
        _tp_written = task_in(_tp_mp, "P2.6") or {}
        check("tp8 the SAME entry at `tdd` mode is WRITTEN and warned about, "
              "not refused: the manifest changed, the entry is in the task "
              "verbatim, and the report carries the deprecation with the "
              "release it bites in. Byte inequality is half the assertion, "
              "because a rolled-back write also prints warnings: %r"
              % (_tp_tdd[-300:],),
              code == 0 and _tp_after != _tp_before
              and (_tp_written.get("tests") or {}).get("add") == [_TP_PROSE]
              and "names no file" in _tp_tdd
              and "FINDING AT 3.0.0" in _tp_tdd
              and _TP_PROSE in _tp_tdd)
        check("tp8b ...and `files` still gained nothing from it, which is the "
              "half the warning is ABOUT: the write being allowed does not "
              "make the scope complete, so the note this verb prints and the "
              "validator's deprecation are two different sentences about one "
              "entry: %r" % (_tp_written.get("files"),),
              _tp_written.get("files") == []
              and "name no file" in _tp_tdd)
        # `scope` is the OTHER two write sites, and F294 was in all three. The
        # verb an operator reaches for when reality differed from the plan is
        # the last place that should hand back a scope it knows to be short.
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
        # F296, END TO END, and the fixture above cannot reach it: `P0`, `P1`
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
        check("p3b F296: the id is the HIGHEST plus one, so a gap in the plan "
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
        # what the three call sites pass and what F275 turned the lookup into. A
        # synthetic dict handed in from outside answers about no task at all -
        # and it was exactly that shape, a task dict with no phase attached to
        # it, which hid the fourth readiness term here for as long as it did.
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
        # w7-w8: F275, the fourth term of the readiness rule. `reference/
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
        # F271 NARROWED THIS REFUSAL, F283 SPLIT WHAT WAS LEFT, and neither
        # removed it. The call above REPLACES `src/a.ts` with `src/b.ts`, so it
        # is a NARROWING - and a narrowing is refused on a done task for the one
        # reason that is true of a done task: its commit was graded against the
        # list it holds, so dropping an entry moves a judgement already made.
        # (What F283 opened is the other shape, a WIDENING, which settles the
        # index rather than re-judging anything - the st group holds it.)
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

        # ---- (sn) F208: the verb was unusable on the task it exists for ------
        # `tests` used to be materialized unconditionally, so `scope --files`
        # alone left `tests: {}` behind - and an ABSENT `tests` is legal while
        # one present without a `mode` is not (`_manifest_phases.py`). The
        # rollback held, so nothing was ever corrupted; the verb simply could
        # not run. Measured live on the F189 case itself: an imported task whose
        # description says "scope files/tests before running" has no `tests`
        # key, and the refusal read `tests.mode None not in [...]`, which
        # describes the manifest for a defect in the writer.
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
        # ---- (rn) F288: a phase can be renamed, and a rename is not a label ---
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
        # `build_parser()` to ask (F295 extracted it, the same shape P26.1
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
        # F190's OTHER half of the pending rule: an attempted task keeps an
        # outcome describing work judged under the scope it had.
        #
        # THE CALL CHANGED WITH F271 AND THE CLAIM DID NOT. This used to pass
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

        # ---- (gc) F196: the empty gate a task could not reach ----------------
        # `/audit:phase retarget` took `--gate-clear` in the release that gave
        # `scope` its `--gate`, and `scope` did not take the clear - so a phase
        # could say "nothing here can prove this" and a task could not. THE
        # REASON DIFFERS FROM `retarget`'s, which is why the same flag needed its
        # own justification: that verb APPENDS to `testGate`, so the append is
        # what left the empty gate unspellable, while this one REPLACES
        # `tests.gate` outright. The gap here is in the values - no `--gate`
        # VALUE says "none". Measured live: a phase retargeted to `testGate: []`
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

        # ---- (jf) F197: what the trail says the prior state was --------------
        # `_locked_scope` builds the journal's `changes` list. Three fields read
        # the value they replace; `tests.add` and `tests.gate` wrote a literal
        # `None`. Measured live: a row said the gate went from nothing to a
        # command when it went from `["lint"]`. The chain verifies, the row is
        # genuine, and it is wrong about the prior state - so the surface built to
        # answer "what was this gated on before, and who changed it" gave a false
        # answer. Same class as F191 and F184: integrity guaranteed, content not
        # true.
        jfm = base_manifest()
        # Both entries carry the documented `<path>: <what it asserts>` shape
        # (F294): the union carries the PATH and not the sentence, so a fixture
        # whose entries name no file would leave `files` unmoved and take the
        # row this group is about out of the journal.
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
              "into it (F258): a case the task creates is a file it owns, and a "
              "scope that named one without the other was the shape that cost a "
              "real run 13 hand-fixes: %r" % (sorted(jf_from),),
              sorted(jf_from) == ["files", "tests.add", "tests.gate"])
        os.makedirs(os.path.join(jf_proj, "src"), exist_ok=True)
        for _jff in ("d.ts", "e.ts"):
            with open(os.path.join(jf_proj, "src", _jff), "w") as _fh:
                _fh.write("x\n")
        code, txt = run(["scope", "P2.3", "--files", "src/d.ts",
                         "--project-dir", jf_proj])
        # F258, the invariant asserted on its own rather than as a side effect of
        # jf4's row count: `files` must contain everything `tests.add` names, from
        # whichever writer touched the task last.
        _jf_node = [t for p in _mio.load_manifest(jf_mp).get("phases") or []
                    for t in (p.get("tasks") or []) if t.get("id") == "P2.3"]
        # F294 narrowed the claim this makes: `files` carries the PATH each
        # entry names, not the entry. Asked through the same parser the writer
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

        # ---- (ag) F201: the empty gate at CREATION ---------------------------
        # F196's exact shape one verb over. `--gate-clear` is defined GLOBALLY on
        # the parser, so argparse accepted `add --gate-clear`, `_build_task` never
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

        # ---- (fn) F202: a row for a change that did not happen ---------------
        # F197's class one field over and not named by that entry: the `files` row
        # went in under a bare `if files:`, so re-scoping to the list the task
        # already held printed and journaled `files: [...] -> [...]`. Milder than
        # F197 (the `from` is true, so nobody is misled about the prior state) and
        # still a hash-chained row attesting a change that never occurred, which is
        # exactly what a reader counting "who changed this task's scope, and when"
        # counts. The three sibling fields already compared.
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

        # ---- (sf) F199: the three fields `scope` did not reach ---------------
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
              "says so - F202's comparison at the new field, so the fix did not "
              "arrive carrying the bug it was fixing: %r" % (txt[:70],),
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
              "is what F197 was about and a new field must not arrive with a "
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
        # It read "THE PENDING GUARD IS THE WHOLE CALL, not a per-field rule",
        # which F271 replaced: a started task will take a WIDENING of `files` or
        # `tests.add`, because that is the one change `_invariants.commit_scope`
        # cannot re-judge an already-recorded commit over. What is unchanged is
        # this case's own claim - `risk` REPLACES a value the attempt ran under,
        # so F190's reason still covers it exactly as it covers the other two
        # fields F199 added, and the sentence the caller meets is still F190's.
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

        # ---- (wd) F271: `scope` refused the case it exists for ---------------
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
              "`risk` REPLACES a value the attempt ran under, so F190's sentence "
              "is still the one the caller meets: %r" % (txt[:240],),
              code == 2 and "already been attempted (1)" in txt
              and '`risk` would move from "low" to "high"' in txt)
        code, txt = run(["scope", "P2.3", "--tests-add", "src/known.test.ts",
                         "--tests-add", "src/needed.test.ts",
                         "--project-dir", wd_proj])
        _wdt = task_in(wd_mp, "P2.3") or {}
        check("wd6 `tests.add` widens on the same terms, and the case it names "
              "lands in `files` with it (F258) - a task that CREATES a test file "
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
              "F283's split is exactly here: `done` takes a widening because "
              "there is an index to settle, `cancelled` does not because nothing "
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

        # F300. THE DOCUMENT JOIN, and the half this group left open. F271
        # repaired the verb and the cases above pin the behaviour, but nothing
        # tied either of them to the document that PRESCRIBES this recovery --
        # so the `in_progress` arm was repaired without being named, and a gate
        # tightened back would meet no case that reads the flow it breaks.
        # `reference/orchestrator.md` writes the state in its Execute step
        # (`task.status = "in_progress"` and `task.attempts += 1`, in one step,
        # BEFORE the executor is spawned) and then names the remedy for the
        # moment the plan gate refuses a file that task genuinely needs: widen
        # `task.files` through this verb and tell the RUNNING executor to carry
        # on, rather than spawning a fresh one. Released 2.2.0 wrote that state
        # and refused that remedy, so the route the document sells as the cheap
        # one was the route an operator could not take -- reported from a live
        # phase run.
        #
        # READ OUT OF THE DOCUMENT, st5's rule: a reworded prescription, or a
        # state whose write moves, has to come past this case instead of
        # drifting away from the verb it names. READ, NOT CAUGHT -- a suite that
        # cannot open the document it is comparing must fail rather than assert
        # on an empty string.
        with open(os.path.join(_output.PLUGIN_ROOT, "reference",
                               "orchestrator.md"), "r",
                  encoding="utf-8") as _fh:
            _orc_src = _fh.read()
        _orc_starts = ('task.status = "in_progress"' in _orc_src
                       and "task.attempts += 1" in _orc_src)
        _orc_widens = ("A widened scope CONTINUES the executor" in _orc_src
                       and "widen `task.files` (`/audit:task scope`)"
                       in _orc_src)
        wdd = base_manifest()
        # The state that Execute step leaves behind, and nothing more. `tests.add`
        # is EMPTY on purpose: `--files` unions the task's own cases back in
        # (F258), so a case file sitting there would re-add itself in the
        # narrowing below and hide the drop that call exists to show.
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
        check("wd12 THE DOCUMENTED RECOVERY, DRIVEN: `orchestrator.md` sets "
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
              "is the silent move F190 protects against -- an operator retyping "
              "the list from memory -- and it is the shape that separates a "
              "guard grading the DIRECTION of the change from one that merely "
              "notices something was added: %r" % (txt[:200],),
              code == 2 and _wdd_after == _wdd_before
              and "`files` would drop src/documented.ts" in txt
              and (task_in(wdd_mp, "P2.3") or {}).get("files")
              == ["src/documented.ts", "src/refused.ts"])

        # ---- (st) F283: `done` settles the RECORD, not the INDEX -------------
        # The product prescribed a remedy and refused it in the same breath. At
        # sign-off `_invariants.manifest_revalidated` prints, as its own repair,
        # "run `/audit:task scope <id> --files ...` to re-derive the index" - and
        # sign-off runs only when every task is `done`, which this verb refused.
        # A live run spent 172,417 tokens on three fix-run subagents before that
        # surfaced. F271 widened the STARTED rule five hours earlier and left the
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
        _st_rows = [r for r in (_stmod.read_all(st_proj) if _stmod else [])
                    if r.get("action") == "task.scope"]
        check("st3 ...and the row DATES it, because a settlement written into a "
              "finished task's record is exactly the thing a reader will later "
              "ask when happened: %r" % (_st_rows[-1:],),
              len(_st_rows) == 1
              and "WIDENED" in (_st_rows[0].get("summary") or "")
              and "done" in (_st_rows[0].get("summary") or "")
              and (_st_rows[0].get("details") or {}).get("attempt") == 1)
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

        # ---- (pb) F275: readiness ignored the owning phase's blockedBy -------
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

        # ---- (qg) F207: add-phase reaches the EMPTY gate ---------------------
        # The THIRD verb of one shape. `--gate-clear` sits on the shared parser, so
        # argparse accepted it here while `_phase_gate` never looked - the new
        # phase inherited `meta.buildCommands` and the caller was told the call
        # worked. `scope` was F196 and `add` was F201; the check that exists
        # because of those two did not cover the verb where it happened again,
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

        # ---- (eb) F285: the brief the shell had already eaten ----------------
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

        # ---- (pf) F293: the CLASS `--description` was one member of -----------
        # F285 fixed one flag. Two more carry the operator's own prose into the
        # manifest AND into the hash-chained journal through the same shell:
        # `--reason`, which F191 made a VERBATIM field precisely so nobody would
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
              "and written. `--reason` is the sharpest - F191 made it VERBATIM "
              "so nobody would paraphrase it, so a hole in one is silent by "
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
        # F293's OWN REGRESSION, reported from a live run and the reason an
        # advisory printed before dispatch is a defect rather than a style
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
        # F293 closed the class for FLAGS and left the TITLE, which put the
        # guard on the CORRECTION path and not on the path where a title first
        # reaches the manifest: `retarget --rename "$T"` refused a run of spaces
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
              and sorted(M.PROSE_POSITIONAL) == ["add", "add-phase"])
        check("pf9 the class is a TABLE and not four call sites, and what is "
              "OUTSIDE it was measured rather than assumed: `--gate` carries a "
              "COMMAND (`make check ; true` trips the gap shapes and is exactly "
              "right), and the id lists leave an empty element `_split_csv` "
              "already drops: %r" % (sorted(M.PROSE_FLAGS),),
              sorted(M.PROSE_FLAGS)
              == ["description", "outcome", "reason", "rename"]
              and "gate" not in M.PROSE_FLAGS
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

        # ---- (vf) F295: a flag a verb does not read is a usage error ----------
        # ONE PARSER SERVES FIVE VERBS. Driven across the grid before the fix,
        # half the (verb, flag) pairs were ACCEPTED, wrote nothing and reported
        # success with exit 0 - `scope --outcome`, `retarget --files`,
        # `add --id`, `add-phase --risk`, `add-phase --files` among them. F196,
        # F201 and F207 each fixed one cell of that grid; `--rename` was born
        # ignored by four verbs, which is what makes it a class rather than
        # three incidents.
        import ast
        import re
        vf_proj, vf_mp = mk("vf-flags", base_manifest())
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
                   "add-phase": ["add-phase", "T", "--outcome", "o"],
                   "cancel": ["cancel", "P2.3", "--reason", "r"],
                   "scope": ["scope", "P2.3", "--files", "src/a.ts"],
                   "retarget": ["retarget", "P2", "--gate", "true"]}
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
        check("vf3 ...and the WHOLE grid: every flag no verb of the five reads "
              "exits 2 on that verb, and not one of those calls wrote a byte. "
              "Counted over the parser's own option list, so a flag added "
              "tomorrow is inside this case by existing - which is the half "
              "that makes `--rename`'s birth defect impossible to repeat: %r"
              % (_vf_leaks,),
              _vf_leaks == [] and _vf_after3 == _vf_before)
        # SECOND-DIRECTION CASES. A refusal that fires on a flag the verb DOES
        # read is a refusal somebody routes around inside a day, and the
        # universal flags are the ones every verb has to keep taking.
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
                (["cancel", "P3", "--reason", "dropped", "--json"],
                 "cancel/--json")):
            _vf_ok[_vfwhat] = run(_vfargv + ["--project-dir", vf_proj])[0]
        check("vf4 SECOND-DIRECTION CASE: every flag a verb DOES read still "
              "works, and `--json` / `--project-dir` reach all five - a guard "
              "that fires on a correct call is a guard somebody routes around "
              "inside the day: %r" % (_vf_ok,),
              sorted(_vf_ok.values()) == [0] * 5)
        _vf_empty = run(["cancel", "P2.3", "--reason", "r", "--description",
                         "", "--project-dir", vf_proj])[0]
        check("vf5 ...and the census reads ARGV rather than the namespace: "
              "`--description \"\"` holds the parser's own default, so a check "
              "comparing values could not tell it from a flag nobody passed - "
              "which is the half of a flag that is ignored MOST quietly: %r"
              % (_vf_empty,), _vf_empty == 2)
        # THE TABLE, GRADED AGAINST THE REAL DISPATCH. A hand-written table
        # nothing compares to the code is the same defect one level up: F207's
        # entry says a row added to `test__refs.py`'s writer table stayed green
        # with the flag's read DELETED, which is a check asserting nothing.
        with open(os.path.join(_output.SCRIPTS_DIR, "manifest",
                               "audit-task.py"), "r", encoding="utf-8") as _fh:
            _vf_src = _fh.read()
        _vf_tree = ast.parse(_vf_src)
        _vf_defs = dict((n.name, n) for n in _vf_tree.body
                        if isinstance(n, ast.FunctionDef))

        def vf_doors(tree):
            """{verb: door function} off `main`'s own `doors` map.

            DERIVED AND NOT LISTED. The roots of the walk below are the five
            functions the dispatch actually reaches, and a list of them kept
            here would be a sixth description of the verb set - which is the
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
              "the F295 defect back: %r" % (_vf_off,), _vf_off == {})
        # THE VACUITY GUARD, and it is the half that matters: an empty door map,
        # a renamed function or an option list that failed to resolve all leave
        # vf6 green over nothing at all.
        _vf_choices = sorted(a.choices or [] for a in _vf_parser._actions
                             if a.dest == "command")
        _vf_unresolved = sorted(d for d in _vf_map.values()
                                if d not in _vf_defs)
        check("vf7 ...over a door map, a call graph and an option list that all "
              "actually resolved: five verbs, every door found in the AST, and "
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
        # accepted, so the one shape it rejects is one `parse_args` rejects
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
              "five derived sets, so a flag that becomes universal cannot stay "
              "listed per verb and one that stops being universal cannot stay "
              "here - the table's own vocabulary is derived too: %r"
              % (sorted(_vf_common),),
              _vf_common == set(M.UNIVERSAL_FLAGS))

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
