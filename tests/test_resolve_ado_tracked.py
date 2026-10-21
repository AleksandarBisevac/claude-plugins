#!/usr/bin/env python3
"""
The cases for `resolve-ado-tracked.py` — the door onto `_ado_tracked`.

The rules live in `_ado_tracked` and have their own suite; what is pinned HERE
is the door, and its exit-code contract is most of it:

- **"nothing is tracked" is EXIT 0, and it gets its own sentence.** A plan every
  phase of which is deliberately off the board is a plan, not a fault. A door
  that exited non-zero over a state somebody authored on purpose would be
  switched off inside a day, taking the real answers with it — and one whose
  success line reads identically whether it planned every phase or none is the
  shape that gets believed on the wrong day. `rt13` holds both halves.
- **There is NO exit 1.** `rt40` runs every fixture in this file and asserts the
  code is never 1. `resolve-ado-parent.py` has one because a hierarchy violation
  is a link nothing can build; this command's worst news is a declared
  intention, and inventing a refusal for it would put the door in the way of the
  exact thing it records.
- **Unreadable input is 2, and a scope naming nothing is 2.** "Tracked: nothing"
  about an id that does not exist reads exactly like a plan somebody keeps
  deliberately internal, which is the one confusion this feature exists to end.
- **The SHARDED layout is reached through `_manifest_io`, and `rt30` proves it
  end to end.** The declaration and the tasks both live in the shard body, so
  the index file this suite writes carries neither — `rt31` asserts that
  separately, off the file, so the pair is two computations and not one value
  compared with itself. A door reaching for `json.load` reports that plan
  TRACKED, by default, with no task rows at all.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("resolve-ado-tracked.py", modname="resolve_ado_tracked")


def _phase(pid, tracked=None, tasks=None):
    phase = {"id": pid, "title": pid, "status": "pending",
             "tasks": list(tasks or [])}
    if tracked is not None:
        phase["adoTracked"] = tracked
    return phase


def _task(tid, **extra):
    task = {"id": tid, "title": tid, "status": "pending"}
    task.update(extra)
    return task


def _manifest(phases, ado=None, bugs=None):
    return {"meta": {"version": 2, "ado": ado if ado is not None else {}},
            "phases": list(phases), "bugs": list(bugs or [])}


def _write(root, name, obj):
    path = os.path.join(root, name)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def _run_full(argv, seen=None):
    """(exit code, stdout, stderr) — the printed answer is half this command's
    contract, and on the exit-2 paths the SENTENCE is the other half.

    Three different failures share exit 2 here — a manifest nobody can open, a
    manifest that will not parse, and a scope naming nothing — and a case
    reading only the code cannot tell which one it provoked. That is the shape
    where a mutation moves the failure from one branch to another and every case
    stays green.

    `seen` collects every code this suite ever produced, so `rt40` can assert
    over the whole file that 1 is not among them rather than over the fixtures
    somebody remembered to list.
    """
    out, err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = M.main(argv)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    if seen is not None:
        seen.append(code)
    return (code, out.getvalue(), err.getvalue())


def _cases(check):
    codes = []

    def run(argv):
        """(exit code, stdout) — `_run_full` for the cases that read no stderr."""
        code, out, _err = _run_full(argv, codes)
        return code, out

    # --- argument parsing, before anything reads a file -----------------------
    check("rt1 no arguments is a usage error, not an accidental pass",
          _run_full([], codes)[0] == 2)
    check("rt2 the default scope is every item, because the push plan needs the "
          "whole picture and a command whose default answers about nothing is "
          "one people forget to scope: %r" % (M.parse_args(["m.json"])[0],),
          M.parse_args(["m.json"])[0]["scope"] == "all"
          and M.parse_args(["m.json"])[0]["target"] is None
          and M.parse_args(["m.json"])[0]["json"] is False)
    for _argv, _why in ((["m.json", "--phase"], "a scope flag with no id"),
                        (["m.json", "--nope"], "an unknown flag"),
                        (["--json", "m.json"], "no manifest first")):
        _opts, _err = M.parse_args(_argv)
        check("rt3 %s is refused with a sentence rather than parsed into a "
              "default: %r" % (_why, _err), bool(_err))
    check("rt4 ...and the flags that ARE legal parse into the scope they name - "
          "the control, without which a parser that refused everything would "
          "pass rt3: %r" % (M.parse_args(["m.json", "--task", "P1.1",
                                          "--json"])[0],),
          M.parse_args(["m.json", "--phase", "P3"])[0]["scope"] == "phase"
          and M.parse_args(["m.json", "--phase", "P3"])[0]["target"] == "P3"
          and M.parse_args(["m.json", "--task", "P1.1", "--json"])[0]["json"]
          and M.parse_args(["m.json", "--task", "P1.1"])[1] is None)

    root = _harness.fixture_root("qg-adotracked-")

    # --- exit 2: the input, and only the input --------------------------------
    _missing = os.path.join(root, "no-such.json")
    _code, _out, _err = _run_full([_missing], codes)
    check("rt10 an unreadable manifest is exit 2 with NOTHING on stdout, and it "
          "names the file - a 0 would report a plan nobody could open as a plan "
          "that tracks nothing: rc=%d %r" % (_code, _err.strip()[:60]),
          _code == 2 and _out == "" and _missing in _err)
    _bad = os.path.join(root, "broken.json")
    with open(_bad, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    _code, _out, _err = _run_full([_bad], codes)
    check("rt11 ...and so is a manifest that will not parse: rc=%d %r"
          % (_code, _out), _code == 2 and _out == "")

    # --- exit 0: including the answer that looks like a failure ---------------
    _plain = _write(root, "plain.json", _manifest(
        [_phase("P1", tasks=[_task("P1.1")]),
         _phase("P2", tracked=False, tasks=[_task("P2.1")]),
         _phase("P3", tracked=True)],
        bugs=[{"id": "BUG-1", "title": "b", "status": "open"}]))
    _code, _out = run([_plain])
    check("rt12 a mixed plan is exit 0 and prints every count, including the "
          "ones at zero - a count that appears only when it is non-zero cannot "
          "be told from a count nobody took: rc=%d %r"
          % (_code, _out.splitlines()[:1]),
          _code == 0
          and "5 item(s), 3 on the board, 2 deliberately untracked, "
              "0 not answered" in _out)
    check("rt13 ...and each row carries the sentence that makes its answer "
          "true, counted rather than asserted present - one basis would leave "
          "the rest looking explained: %r"
          % ([x for x in _out.splitlines() if " -> " in x][:1],),
          len([x for x in _out.splitlines() if " -> " in x]) == 5
          and len([x for x in _out.splitlines()
                   if " -> NOT TRACKED -- declared adoTracked: false" in x]) == 1
          and len([x for x in _out.splitlines()
                   if "no adoTracked anywhere" in x]) == 2)
    check("rt14 ...and the bug is reported APART, always and at whatever count, "
          "because a bug is owned by no phase and counting it among the plan's "
          "items would report the ordinary state of every bug as a gap: %r"
          % ([x for x in _out.splitlines() if "bugs:" in x],),
          "bugs: 1 not covered" in _out
          and len([x for x in _out.splitlines() if "BUG-1" in x]) == 0)

    _none = _write(root, "none-tracked.json", _manifest(
        [_phase("P1", tracked=False, tasks=[_task("P1.1")]),
         _phase("P2", tracked=False)]))
    _code, _out = run([_none])
    check("rt15 a plan with NOTHING on the board is EXIT 0 - the state was "
          "authored on purpose, and a command that refused it would be in the "
          "way of the exact intent it records: rc=%d" % (_code,),
          _code == 0)
    check("rt16 ...and it SAYS so in its own words rather than printing the "
          "ordinary OK line, which would read the same whether every phase was "
          "planned or none: %r" % (_out.splitlines()[-1:],),
          "NOTHING in scope belongs on the board" in _out
          and "3 deliberately untracked" in _out)
    _code, _out = run([_plain])
    check("rt17 ...while a plan that DOES track something gets the ordinary "
          "line - the second direction, and the only case that fails if that "
          "sentence ever becomes unconditional: %r" % (_out.splitlines()[-1:],),
          "NOTHING in scope belongs on the board" not in _out
          and "every in-scope item has an answer" in _out)

    # --- the scope: what it narrows, and what it must not hide ----------------
    _code, _out = run([_plain, "--phase", "P2"])
    check("rt20 a --phase covers the tasks under it, because a task's answer IS "
          "its phase's - a scope returning the phase alone would drop every row "
          "the declaration actually moved: rc=%d %r"
          % (_code, [x for x in _out.splitlines() if " -> " in x]),
          _code == 0
          and len([x for x in _out.splitlines() if " -> " in x]) == 2
          and "2 item(s), 0 on the board, 2 deliberately untracked" in _out)
    check("rt21 ...and what it did NOT ask about is counted and graded rather "
          "than dropped, so a scoped run's numbers cannot be read as facts "
          "about the file: %r"
          % ([x for x in _out.splitlines() if "outside this scope" in x],),
          "outside this scope: 3 item(s) not asked about, 0 of them "
          "deliberately untracked" in _out)
    check("rt22 ...and the bug line still reports the WHOLE manifest, because a "
          "scoped run printing '0 bugs' would answer about P2 in a sentence "
          "that reads as a fact about the file: %r"
          % ([x for x in _out.splitlines() if "bugs:" in x],),
          "bugs: 1 not covered" in _out)
    _code, _out, _err = _run_full([_plain, "--phase", "P9"], codes)
    check("rt23 a scope naming nothing is exit 2 with nothing on stdout, and it "
          "names what it looked for - 'tracked: nothing' about an id that does "
          "not exist reads exactly like a plan somebody keeps deliberately "
          "internal: rc=%d %r" % (_code, _err.strip()[:70]),
          _code == 2 and _out == "" and "'P9'" in _err and "phase" in _err)
    check("rt24 ...and so does a --task naming nothing, while the ids that DO "
          "exist are answered - the control, without which a door that refused "
          "every scope would pass rt23",
          _run_full([_plain, "--task", "P9.9"], codes)[0] == 2
          and _run_full([_plain, "--task", "P2.1"], codes)[0] == 0
          and _run_full([_plain, "--phase", "P2"], codes)[0] == 0)

    # --- --json carries the same verdict --------------------------------------
    _code, _out = run([_plain, "--json"])
    _doc = json.loads(_out)
    check("rt30 --json exits with the SAME code as the printed form and carries "
          "the same counts, so a script and a person cannot disagree about a "
          "board: rc=%d %r" % (_code, _doc.get("counts")),
          _code == 0
          and sorted(_doc) == ["counts", "manifestCounts", "rows", "scope",
                               "target", "warnings"]
          and _doc["counts"] == {"items": 5, "tracked": 3, "untracked": 2,
                                 "unanswered": 0, "bugs": 1}
          and _doc["scope"] == "all" and _doc["target"] is None)
    check("rt31 ...and every row carries the whole answer - what it is about, "
          "which item, the verdict and the basis - so no consumer has to "
          "re-derive one from a bare boolean: %r" % (_doc["rows"][:1],),
          len(_doc["rows"]) == 6
          and all(sorted(r) == ["basis", "id", "kind", "tracked", "warnings"]
                  for r in _doc["rows"])
          and all(r["basis"] for r in _doc["rows"]))
    _code, _out = run([_plain, "--phase", "P2", "--json"])
    _scoped = json.loads(_out)
    check("rt32 ...and a SCOPED --json carries both tallies: `counts` answers "
          "what was asked and `manifestCounts` answers about the file, because "
          "a consumer given only the first cannot tell a manifest that tracks "
          "nothing from a scope that happens to contain nothing tracked: %r"
          % ([_scoped.get("counts"), _scoped.get("manifestCounts")],),
          _code == 0
          and _scoped["counts"]["items"] == 2
          and _scoped["counts"]["bugs"] == 0
          and _scoped["manifestCounts"]["items"] == 5
          and _scoped["manifestCounts"]["bugs"] == 1)

    # --- the sharded layout, end to end (the door's own half of the rule) -----
    # The declaration and the tasks BOTH live in the shard body; the index
    # carries neither. `rt41` asserts that off the FILE rather than off this
    # fixture literal, so the pair is two computations and not one value
    # compared with itself - the shortcut that makes a verification circular.
    _index_doc = {"meta": {"version": 3, "ado": {}},
                  "phases": [{"id": "P1", "title": "P1", "status": "pending",
                              "shard": "phases/P1.json"}],
                  "bugs": []}
    _sharded = _write(root, "sharded.json", _index_doc)
    _write(root, os.path.join("phases", "P1.json"),
           {"id": "P1", "title": "P1", "status": "pending",
            "adoTracked": False,
            "tasks": [_task("P1.1"), _task("P1.2")]})
    _code, _out = run([_sharded])
    check("rt40 the SHARDED layout is read through _manifest_io, so the door "
          "reaches the declaration and the tasks that live in the shard body. A "
          "door reaching for json.load sees neither and reports this plan "
          "TRACKED by default, with no task row at all: rc=%d %r"
          % (_code, [x for x in _out.splitlines() if " -> " in x]),
          _code == 0
          and "3 item(s), 0 on the board, 3 deliberately untracked" in _out
          and len([x for x in _out.splitlines()
                   if " -> NOT TRACKED -- " in x]) == 3
          and len([x for x in _out.splitlines() if "P1.2" in x]) == 1)
    with open(_sharded, "r", encoding="utf-8") as fh:
        _raw = json.load(fh)
    check("rt41 ...and the index file itself carries neither the declaration "
          "nor a task, which is what makes rt40 a real result rather than a "
          "value compared with itself: %r" % (_raw["phases"],),
          all("adoTracked" not in p and "tasks" not in p
              for p in _raw["phases"])
          and any("shard" in p for p in _raw["phases"]))
    check("rt42 ...and the run emits NO index-stub warning, which is the "
          "second direction: the refusal the rules raise for an un-assembled "
          "phase must not fire once the loader has done its job: %r"
          % ([x for x in _out.splitlines() if x.startswith("WARNING:")],),
          len([x for x in _out.splitlines() if x.startswith("WARNING:")]) == 0
          and "NOT ANSWERED" not in _out)

    # --- a warning reaches the operator ---------------------------------------
    _inert = _write(root, "inert.json", _manifest(
        [_phase("P1", tracked=False,
                tasks=[_task("P1.1", adoTracked=True)])]))
    _code, _out = run([_inert])
    check("rt50 a task's own adoTracked is reported as INERT rather than "
          "silently ignored, and the run still exits 0 because nothing about it "
          "is unanswerable: rc=%d %r"
          % (_code, [x for x in _out.splitlines() if x.startswith("WARNING:")]),
          _code == 0
          and len([x for x in _out.splitlines()
                   if x.startswith("WARNING:") and "INERT" in x]) == 1
          and len([x for x in _out.splitlines()
                   if " -> NOT TRACKED -- " in x]) == 2)

    # --- the code that is not in this command's vocabulary --------------------
    # OVER EVERY RUN THIS SUITE MADE, collected as they happened rather than
    # over the fixtures somebody remembered to list. `_run_full` appends to
    # `codes`, so a case added later is covered by this one without being
    # edited into it.
    check("rt60 there is NO exit 1 anywhere in this command: a hierarchy "
          "violation is a link nothing can build and earns one in "
          "resolve-ado-parent, while 'this phase is not on the board' is a "
          "normal state somebody authored - inventing a refusal for it would "
          "put the door in the way of the intent it records: %r"
          % (sorted(set(codes)),),
          codes and sorted(set(codes)) == [0, 2])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_resolve_ado_tracked.py --selftest\n")
    raise SystemExit(2)
