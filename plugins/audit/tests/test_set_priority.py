#!/usr/bin/env python3
"""
The cases for `set-priority.py` — pinning a phase, and refusing to pin two.

`set-priority.py` is hyphenated, so it comes through `_loader.load_script` and this
file substitutes underscores; `test_audit_task.py` is the precedent for both halves
of that rule. Every fixture lives under one `tempfile.mkdtemp()` removed in a single
`finally`.

WHAT IS PINNED, and why each one is here rather than trusted:

- **A second holder of tier 1 is refused, and the refusal NAMES the holder.**
  A refusal that leaves the reader to go and find the conflicting phase is a
  refusal people route around instead of resolving.
- **`--force` writes it anyway, and the manifest still VALIDATES.** That is not a
  nicety: this command rolls back on findings, so if the doubled tier were a
  finding rather than a warning, `--force` would undo its own write. The case is
  the proof that the validator's choice and this flag agree.
- **Tier 2 is written as tier 2.** `E_USAGE` is 2, and a parser returning "the
  tier, or the exit code" would make a legal write indistinguishable from a
  refusal. The fixture value is chosen so the two implementations disagree.
- **Sharded: the INDEX is written and the SHARD is not.** Touching the shard would
  put the value where the next load discards it and would manufacture a merge
  conflict against the phase branch running in it.
- **The manifest is revalidated from DISK after the write**, and a journal row
  exists. Both are the house contract for a command that mutates the manifest.

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
import _manifest_io as _mio                        # noqa: E402
import _priority                                   # noqa: E402

M = _loader.load_script("set-priority.py", modname="set_priority")


def _base_manifest():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P1", "title": "One", "status": "pending",
             "tasks": [{"id": "P1.1", "title": "a", "status": "pending"}]},
            {"id": "P2", "title": "Two", "status": "pending",
             "tasks": [{"id": "P2.1", "title": "b", "status": "pending"}]},
            {"id": "P3", "title": "Three", "status": "pending",
             "tasks": [{"id": "P3.1", "title": "c", "status": "pending"}]},
        ],
    }


# --- cases --------------------------------------------------------------------
# Letters taken in this file (NEW file -- fresh letter space): w (the write),
# u (uniqueness + --force), c (--clear), y (layout: sharded vs single),
# j (journal + --json), e (usage errors), v (revalidation).
def _cases(check):
    root = tempfile.mkdtemp(prefix="set-priority-selftest-")

    def project(sharded=False, manifest=None):
        """A project directory with a manifest, in whichever layout is asked for."""
        d = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(d, ".claude"))
        os.makedirs(os.path.join(d, "docs", "audit"))
        mpath = os.path.join(d, "docs", "audit", "audit-plan.json")
        data = manifest if manifest is not None else _base_manifest()
        if sharded:
            _mio.save_sharded(mpath, data)
        else:
            with open(mpath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        return d, mpath

    def run(argv):
        lines = []
        code = M.main(argv, out=lines.append)
        return code, "\n".join(lines)

    def raw(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    try:
        # --- the write --------------------------------------------------------
        _d, mp = project()
        code, out = run([mp, "P3", "1"])
        check("w1 a pin is written and reported with both ends of the change",
              code == 0 and "P3 priority none -> 1" in out, "%r %r" % (code, out))
        check("w2 ...and the file carries it, on the phase the command named",
              raw(mp)["phases"][2].get("priority") == 1,
              repr(raw(mp)["phases"][2]))
        check("w3 ...and NO other phase gained one - a write that touched the "
              "others would re-sort a plan nobody asked to re-sort",
              [p.get("priority") for p in raw(mp)["phases"]] == [None, None, 1],
              repr([p.get("priority") for p in raw(mp)["phases"]]))
        code, out = run([mp, "P3", "1"])
        check("w4 writing the value it already holds writes NOTHING and says so - "
              "a no-op rewrite is a renormalised file and a journal row about no "
              "change",
              code == 0 and "already priority 1" in out, "%r %r" % (code, out))

        _d, mp = project()
        code, out = run([mp, "P1", "2"])
        check("w5 tier 2 is written as tier 2. E_USAGE is 2, so a parser that "
              "returned 'the tier, or the exit code' would make this legal write "
              "indistinguishable from a refusal - the fixture value is chosen to "
              "tell the two apart",
              code == 0 and raw(mp)["phases"][0].get("priority") == 2,
              "%r %r" % (code, raw(mp)["phases"][0].get("priority")))

        # --- uniqueness -------------------------------------------------------
        _d, mp = project()
        run([mp, "P3", "1"])
        code, out = run([mp, "P1", "1"])
        check("u1 a second holder of tier 1 is REFUSED",
              code == 2, "%r %r" % (code, out))
        check("u2 ...and the refusal NAMES the current holder. A refusal that "
              "leaves the reader to go and find the conflict is one people route "
              "around instead of resolving",
              "P3 already holds priority 1" in out, repr(out))
        check("u3 ...and nothing was written - the refusal is BEFORE the mutation",
              raw(mp)["phases"][0].get("priority") is None,
              repr(raw(mp)["phases"][0]))
        code, out = run([mp, "P1", "1", "--force"])
        check("u4 --force writes the second holder",
              code == 0 and raw(mp)["phases"][0].get("priority") == 1,
              "%r %r" % (code, out))
        check("u5 ...and the manifest STILL VALIDATES, which is what makes "
              "--force possible at all: this command rolls back on findings, so "
              "a doubled tier reported as a FINDING would undo the write it was "
              "explicitly asked to make. The doubled tier is a WARNING, and the "
              "warning names the tie-break",
              "both hold priority 1" in out and "P1 wins" in out, repr(out))
        _d, mp_single = project()
        run([mp_single, "P3", "1"])
        _c, out_single = run([mp_single, "P2", "3"])
        check("u6 SECOND-DIRECTION CASE: on a manifest with ONE holder of tier 1 "
              "there is no such warning. This is what goes red if the uniqueness "
              "rule becomes unconditional and starts reporting every pin - and "
              "it needs its OWN fixture, because the forced manifest above still "
              "carries two holders",
              "both hold priority" not in out_single, repr(out_single))

        # --- clearing ---------------------------------------------------------
        _d, mp = project()
        run([mp, "P2", "1"])
        code, out = run([mp, "P2", "--clear"])
        check("c1 --clear removes the pin and says what it removed",
              code == 0 and "priority 1 -> none" in out, "%r %r" % (code, out))
        check("c2 ...and the KEY is gone, not set to null - an absent priority is "
              "how a phase says unprioritised, and a null would be a value the "
              "schema does not allow",
              "priority" not in raw(mp)["phases"][1], repr(raw(mp)["phases"][1]))
        code, out = run([mp, "P2", "--clear"])
        check("c3 clearing an unpinned phase writes nothing and says so",
              code == 0 and "already unprioritised" in out, "%r %r" % (code, out))
        code, out = run([mp, "P2", "2", "--clear"])
        check("c4 a tier AND --clear together is a usage error, not a silent "
              "preference for one of them",
              code == 2 and "not both" in out, "%r %r" % (code, out))

        # --- the sharded layout -----------------------------------------------
        d, mp = project(sharded=True)
        shard = os.path.join(os.path.dirname(mp), "phases", "P2.json")
        before = open(shard, "rb").read()
        code, out = run([mp, "P2", "1"])
        check("y1 sharded: the pin lands on the INDEX STUB, where the order is "
              "computable without opening a single shard",
              code == 0 and raw(mp)["phases"][1].get("priority") == 1,
              "%r %r" % (code, raw(mp)["phases"][1]))
        check("y2 ...and the SHARD is byte-identical. Writing it would put the "
              "value where the next load discards it, and would manufacture a "
              "merge conflict against the phase branch running in that shard",
              open(shard, "rb").read() == before)
        check("y3 ...and the assembled manifest carries the pin, so every reader "
              "sees it without knowing which layout it came from",
              _priority.tier_of(_mio.load_manifest(mp)["phases"][1]) == 1)
        check("y4 ...and only the index is reported as written",
              out.count("audit-plan.json") >= 1 and "P2.json" not in out,
              repr(out))

        # --- a value written into a shard BODY is reported, not absorbed -------
        d, mp = project(sharded=True)
        body = raw(os.path.join(os.path.dirname(mp), "phases", "P2.json"))
        body["priority"] = 1
        with open(os.path.join(os.path.dirname(mp), "phases", "P2.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2)
        check("y5 an index-only field sitting in a shard body is NAMED by the "
              "module that can see both halves - the assembled manifest has "
              "already dropped it, which is exactly the state a reader has to be "
              "told about",
              _mio.index_only_in_bodies(mp) == [("P2", "priority")],
              repr(_mio.index_only_in_bodies(mp)))
        check("y6 ...and it really was dropped: the assembled phase is "
              "unprioritised, so the value orders nothing",
              _priority.tier_of(_mio.load_manifest(mp)["phases"][1]) is None)
        check("y7 SECOND-DIRECTION CASE: a clean sharded manifest reports NO "
              "such field. An empty list is also what a broken scanner returns, "
              "so this is the case that says the scanner looked",
              _mio.index_only_in_bodies(project(sharded=True)[1]) == [])

        # --- revalidation + the journal ---------------------------------------
        d, mp = project()
        code, out = run([mp, "P1", "1", "--json"])
        payload = json.loads(out)
        check("j1 --json reports both ends of the change and what was written",
              code == 0 and payload["ok"] and payload["from"] is None
              and payload["to"] == 1 and payload["written"], repr(payload))
        rows = []
        for base, _dirs, files in os.walk(d):
            for f in files:
                if f.endswith(".jsonl"):
                    with open(os.path.join(base, f), encoding="utf-8") as fh:
                        rows += [json.loads(ln) for ln in fh if ln.strip()]
        actions = [r.get("action") for r in rows]
        check("j2 the write leaves a `phase.priority` row in the audit trail - "
              "the journal-writes HOOK cannot see an os.replace, so this command "
              "appends its own",
              actions.count("phase.priority") == 1, repr(actions))
        check("j3 ...and the row carries BOTH ends, so the trail answers 'what "
              "did it say before' rather than only 'it changed'",
              [r for r in rows if r.get("action") == "phase.priority"][0]
              ["details"] == {"phaseId": "P1", "from": None, "to": 1},
              repr(rows))

        # --- maxTier is advisory and nothing is clamped -----------------------
        d, mp = project()
        with open(os.path.join(d, ".claude", "audit.config.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"priority": {"maxTier": 2}}, fh)
        code, out = run([mp, "P1", "5"])
        check("m1 a tier ABOVE priority.maxTier is WRITTEN, exactly as given - a "
              "clamped value would be a file that says one thing and a run that "
              "does another",
              code == 0 and raw(mp)["phases"][0].get("priority") == 5,
              "%r %r" % (code, raw(mp)["phases"][0].get("priority")))
        check("m2 ...and the note carries BOTH numbers, because a claim about a "
              "value nothing enforces has to name the value that made it true",
              "above priority.maxTier 2" in out and "pinned at 5" in out,
              repr(out))
        d2, mp2 = project()
        with open(os.path.join(d2, ".claude", "audit.config.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"priority": {"maxTier": 2}}, fh)
        code, out = run([mp2, "P2", "2"])
        check("m3 SECOND-DIRECTION CASE: a tier exactly AT the maximum draws no "
              "note. It needs its OWN fixture, because the note is about the "
              "MANIFEST rather than about the tier just written - and the one "
              "above still holds a phase at 5. This is what goes red if the "
              "advisory becomes unconditional and every pin carries a warning",
              code == 0 and "maxTier" not in out, repr(out))

        # --- an already-invalid manifest is refused BEFORE the write ----------
        bad = _base_manifest()
        bad["phases"][0]["tasks"][0]["id"] = "P2.1"     # duplicate id
        _d, mp = project(manifest=bad)
        code, out = run([mp, "P1", "1"])
        check("v1 an already-invalid manifest is refused with nothing written - "
              "which is what tells 'your change broke it' apart from 'it was "
              "broken when you arrived'",
              code == 1 and "already invalid" in out
              and raw(mp)["phases"][0].get("priority") is None,
              "%r %r" % (code, out))

        # --- usage errors -----------------------------------------------------
        _d, mp = project()
        for argv, why in (([mp, "PX", "1"], "an unknown phase"),
                          ([mp, "P1", "0"], "tier 0"),
                          ([mp, "P1", "-2"], "a negative tier"),
                          ([mp, "P1", "one"], "a non-integer tier"),
                          ([mp, "P1"], "no tier and no --clear")):
            code, out = run(argv)
            check("e1 %s is a usage error that says why (%r)" % (why, out[:60]),
                  code == 2 and out.strip() != "", "%r %r" % (code, out))
        code, out = run([os.path.join(os.path.dirname(mp), "nope.json"),
                         "P1", "1"])
        check("e2 a missing manifest is a usage error naming the path",
              code == 2 and "nope.json" in out, "%r %r" % (code, out))
        check("e3 ...and none of those errors wrote anything",
              raw(mp)["phases"][0].get("priority") is None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_set_priority.py --selftest\n")
    raise SystemExit(2)
