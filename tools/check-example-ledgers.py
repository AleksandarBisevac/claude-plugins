#!/usr/bin/env python3
"""No COMMITTED evidence ledger may record a verdict the runner cannot produce.

WHY THIS EXISTS. `examples/acme-store/` ships an evidence ledger, and one run in it
recorded `status: "passed"` while `observations.treeMutated` named a file the task
itself declares. That row was a FAITHFUL recording of what the runner did before
F280 was fixed -- which is exactly what makes it a fault rather than a typo. F280
gives such a run its own verdict (`gate-mutated`), so the row became
unproducible, and the showcase would have gone on publishing a verdict no current
run can reach. The word is published four times over: the ledger row, the phase
shard's cached pointer, the Markdown twin, and `docs/index.html`.

THE DURABLE HALF IS THAT NOTHING READ IT. `check-rendered-artifacts.py` diffs the
committed artifacts against a fresh render, and the demo USAGE ledger is diffed
against a fresh generation because `gen-demo-usage.py` derives it. The acme-store
evidence ledger is neither: it is hand-maintained content shaped like derived
content, so the vocabulary it uses was free to fall behind the schema's with no
instrument between them. One stale row is what revealed that; the missing
instrument is the defect.

WHY A GATE AND NOT A DERIVATION. Deriving the ledger would make it unable to rot,
and it was considered and declined: the example is a NARRATIVE a reader copies, and
a generator producing that narrative would cost the showcase the thing it is for.
So the ledger stays hand-written and this reads it -- which is the same division
`check-committed-pii.py` draws, a rule over the BYTES GIT TRACKS rather than over
the code that produced them.

WHY A TOOL AND NOT A `*_violations()` UNDER scripts/. It asks git what is tracked,
which is `check-rendered-artifacts.py`'s and `check-committed-pii.py`'s shape rather
than `_deps`'. A `*_violations` name inside a gate module would also make
`prove-gates.coverage()` demand a TABLE row for it in the same change.

THE VOCABULARY IS DERIVED FROM THE SCHEMA, NEVER LISTED HERE. `COMPATIBILITY.md`
declines to promise the enum is closed, so a list in this file would be a second
description of a set that is explicitly allowed to grow -- the defect this
repository names most often, and the one that produced F292 and F299. The schema is
also the right source rather than `_status_facts.KNOWN_EVIDENCE`: a committed ledger
is DATA measured against a published contract, and `test__manifest_vocab` already
pins that the code and the schema agree, so reading both here would add a third
copy without adding a check.

THE CONTRADICTION RULE IS DELIBERATELY NARROW. Only `passed` beside a non-empty
`treeMutated` is a finding. A run whose commands FAILED and which also rewrote the
tree is honestly `failed` -- the failure dominates and no information is lost -- and
the states that never finished (`timed-out`, `cancelled`) carry no tree observation
at all. Widening this to "any status but `gate-mutated` beside a mutated tree" would
fire on rows that are already telling the truth, and a check whose first run
produces findings nobody intends to fix teaches its reader to skip the file.

A CACHE MAY NOT DISAGREE WITH WHAT IT CACHES. The schema says `testEvidence` is "a
POINTER at the run that last exercised this task ... IT IS A CACHE AND NOT THE
SOURCE OF TRUTH". So a cached `status` whose `runId` resolves to a ledger row with a
different word is a finding too: the row is the truth, and a reader who trusts the
cheap read gets the wrong verdict. A pointer whose `runId` resolves NOWHERE is not a
finding -- the ledger may have been archived, and the schema says an absent or
unresolvable pointer means "no evidence recorded", never "failed".

EXIT 0 only when a real set was compared. Nothing found, or a question that could
not be asked, exits non-zero and says which -- a run that compared no ledgers is
the exact shape of a green run that checked nothing.
"""
import io
import json
import os
import subprocess
import sys

_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
sys.path.insert(0, os.path.join(REPO, "plugins", "audit", "scripts"))

import _output  # noqa: E402  (the anchor: install_path, safe_stdio)

_output.install_path()

SCHEMA_REL = "plugins/audit/schema/audit-plan.schema.json"
# Where the published vocabulary lives. Spelled as a PATH rather than searched for,
# because "the enum containing 'passed'" would silently follow the first such enum
# the schema grows, and a check that guesses which contract it is reading is not
# reading a contract.
STATUS_PATH = ("$defs", "testEvidence", "properties", "status")

# A ledger is recognised by WHERE the plugin puts it, which is the one thing a
# caller cannot rename: `_evidence_io` writes month-stamped `.jsonl` files into an
# `evidence/` directory beside the manifest. The month stamp is not matched - a
# ledger somebody archived under another name is still a ledger.
LEDGER_DIR = "evidence"
LEDGER_EXT = ".jsonl"

PASSED = "passed"


# --- asking the tree ----------------------------------------------------------


def tracked_paths(repo=None):
    """(rels, problem) -- every path git tracks, or why the question failed.

    A problem is REPORTED by the caller and never read as an empty tree: a scan
    that found nothing because it could not ask is the shape of a green run that
    checked nothing.
    """
    root = repo or REPO
    try:
        out = subprocess.check_output(["git", "-C", root, "ls-files", "-z"],
                                      stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        return [], "git could not list the tracked files: %s" % (exc,)
    return [p for p in out.decode("utf-8", "replace").split("\0") if p], None


def ledger_rels(rels):
    """Every tracked path that is an evidence ledger, in a stable order."""
    out = []
    for rel in rels:
        parts = rel.split("/")
        if len(parts) >= 2 and parts[-2] == LEDGER_DIR \
                and parts[-1].endswith(LEDGER_EXT):
            out.append(rel)
    return sorted(out)


def manifest_rels(rels):
    """Every tracked manifest index and phase shard, in a stable order.

    Recognised by shape rather than by name: a JSON file carrying `phases` is an
    index, and one under a `phases/` directory is a shard. Both hold `testEvidence`
    pointers, and this tool has an opinion about a pointer wherever it sits.
    """
    out = []
    for rel in rels:
        if not rel.endswith(".json"):
            continue
        parts = rel.split("/")
        if "phases" in parts[:-1] or parts[-1].endswith("-plan.json"):
            out.append(rel)
    return sorted(out)


def schema_statuses(repo=None):
    """(frozenset, problem) -- the published `testEvidence.status` vocabulary."""
    path = os.path.join(repo or REPO, SCHEMA_REL.replace("/", os.sep))
    try:
        with io.open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return frozenset(), "%s could not be read: %s" % (SCHEMA_REL, exc)
    node = doc
    for key in STATUS_PATH:
        if not isinstance(node, dict) or key not in node:
            return frozenset(), (
                "%s no longer carries %s, so the vocabulary this tool measures "
                "against could not be located - the schema moved and this path "
                "did not" % (SCHEMA_REL, "/".join(STATUS_PATH)))
        node = node[key]
    enum = node.get("enum") if isinstance(node, dict) else None
    if not isinstance(enum, list) or not enum:
        return frozenset(), (
            "%s declares %s with no enum, so there is no published vocabulary to "
            "compare a committed row against" % (SCHEMA_REL, "/".join(STATUS_PATH)))
    return frozenset(str(v) for v in enum), None


def read_rows(path):
    """([(lineno, row), ...], problem) -- the JSON objects one ledger holds.

    A line that will not parse is a PROBLEM and not a skipped line: a ledger with
    a torn row is a ledger this tool did not fully read, and saying so is the
    difference between "no findings" and "no findings in the part I could see".
    """
    try:
        with io.open(path, encoding="utf-8") as fh:
            raw = fh.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [], "could not be read: %s" % (exc,)
    rows = []
    for lineno, line in enumerate(raw, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            return [], "line %d will not parse as JSON (%s)" % (lineno, exc)
        if isinstance(row, dict):
            rows.append((lineno, row))
    return rows, None


# --- the rules ----------------------------------------------------------------


def status_findings(rel, rows, known):
    """[(rel, lineno, why), ...] -- rows whose status is not in the vocabulary."""
    out = []
    for lineno, row in rows:
        status = row.get("status")
        if status is None:
            continue
        if str(status) not in known:
            out.append((rel, lineno, (
                "records status %r, which the schema's published vocabulary does "
                "not carry (%s) - a consumer reading this row meets a word its "
                "build has never heard of"
                % (status, ", ".join(sorted(known))))))
    return out


def _mutated_paths(row):
    """The paths a row says the gate rewrote, read the way the RENDERER reads them.

    `observations.treeMutated` is where `_evidence_io` puts them, and it also
    writes a TOP-LEVEL copy - so `_report_html.tev_flags` reads
    `obs.get("treeMutated", row.get("treeMutated"))` and falls back. A checker that
    read only the nested key would pass a hand-written row carrying only the
    top-level one WHILE the report drew a `tree-mutated` mark on it, and this
    ledger is hand-written by design, which is the whole reason the tool exists.
    Read both, in the renderer's order, or the gate and the page disagree.
    """
    obs = row.get("observations")
    nested = obs.get("treeMutated") if isinstance(obs, dict) else None
    if isinstance(nested, list):
        return [p for p in nested]
    top = row.get("treeMutated")
    return [p for p in top] if isinstance(top, list) else []


def contradiction_findings(rel, rows):
    """[(rel, lineno, why), ...] -- rows whose own observations deny their verdict.

    One rule, for the reason the module docstring gives: `passed` beside a tree the
    gate rewrote. F280 gave that run its own word, so a row still spelling it
    `passed` is recording a verdict the runner can no longer reach.
    """
    out = []
    for lineno, row in rows:
        if str(row.get("status")) != PASSED:
            continue
        mutated = _mutated_paths(row)
        if mutated:
            out.append((rel, lineno, (
                "records %r while its own observations.treeMutated names %s - a "
                "gate that rewrote the tree has its own verdict since F280, so "
                "this row publishes a result no current run can produce"
                % (PASSED, ", ".join(str(m) for m in mutated[:3])))))
    return out


def _holders(doc):
    """(label, block) for every task and phase in one manifest document."""
    out = []
    phases = doc.get("phases")
    if isinstance(phases, list):
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            out.append((str(phase.get("id")), phase.get("testEvidence")))
            for task in (phase.get("tasks") or []):
                if isinstance(task, dict):
                    out.append((str(task.get("id")), task.get("testEvidence")))
    # A shard is one phase written on its own, with no `phases` wrapper.
    if not out and isinstance(doc.get("tasks"), list):
        out.append((str(doc.get("id")), doc.get("testEvidence")))
        for task in doc["tasks"]:
            if isinstance(task, dict):
                out.append((str(task.get("id")), task.get("testEvidence")))
    return [(label, block) for label, block in out if isinstance(block, dict)]


def pointer_findings(rel, doc, known, by_run):
    """[(rel, label, why), ...] -- cached verdicts that are wrong or stale.

    Two rules. A cached word outside the vocabulary is the same fault as in a row.
    A cached word that DISAGREES with the ledger row its own `runId` names is worse,
    because the schema calls this block a cache and a cache that can disagree with
    its source is the thing that block was designed not to be. A `runId` resolving
    nowhere is NOT a finding: the schema says an unresolvable pointer means "no
    evidence recorded", never "failed".
    """
    out = []
    for label, block in _holders(doc):
        status = block.get("status")
        if status is not None and str(status) not in known:
            out.append((rel, label, (
                "caches status %r, which the schema's published vocabulary does "
                "not carry" % (status,))))
            continue
        run_id = block.get("runId")
        truth = by_run.get(str(run_id)) if run_id is not None else None
        if truth is not None and status is not None and str(status) != truth:
            out.append((rel, label, (
                "caches status %r while run %s in the ledger records %r - the "
                "ledger is the source of truth and this cache disagrees with it"
                % (status, run_id, truth))))
    return out


def pointer_reach(doc, by_run):
    """(pointers, resolved) -- how many cached pointers exist, and how many
    name a run some committed ledger actually holds.

    The pair is what lets `findings()` tell "no cache disagrees" from "no cache
    was compared". A count of findings cannot: both are zero.
    """
    pointers = 0
    resolved = 0
    for _label, block in _holders(doc):
        run_id = block.get("runId")
        if run_id is None:
            continue
        pointers += 1
        if str(run_id) in by_run:
            resolved += 1
    return pointers, resolved


def findings(repo=None):
    """(rows, counts, problem) -- everything wrong, and what was really compared."""
    root = repo or REPO
    rels, problem = tracked_paths(root)
    if problem:
        return [], {}, problem
    known, problem = schema_statuses(root)
    if problem:
        return [], {}, problem

    ledgers = ledger_rels(rels)
    if not ledgers:
        return [], {}, (
            "no committed evidence ledger was found under any %s/ directory, so "
            "this run compared nothing - which is not the same answer as a tree "
            "with nothing wrong in it" % (LEDGER_DIR,))

    out = []
    by_run = {}
    seen_rows = 0
    for rel in ledgers:
        rows, trouble = read_rows(os.path.join(root, rel.replace("/", os.sep)))
        if trouble:
            out.append((rel, 0, trouble))
            continue
        seen_rows += len(rows)
        for _lineno, row in rows:
            run_id = row.get("runId")
            status = row.get("status")
            if run_id is not None and status is not None:
                by_run[str(run_id)] = str(status)
        out.extend(status_findings(rel, rows, known))
        out.extend(contradiction_findings(rel, rows))

    if not seen_rows and not out:
        return [], {}, (
            "%d committed ledger(s) were found and every one of them is empty, so "
            "no verdict was actually read" % (len(ledgers),))

    # THE POINTER HALF OWES THE SAME PROMISE AS THE LEDGER HALF, and it did not
    # have it: a manifest that would not parse was skipped in silence, nothing
    # refused when zero manifests were read, and `counts` never recorded how many
    # pointers were actually COMPARED - so a run in which no pointer resolved
    # printed OK. That is not hypothetical: the schema calls `runId` opaque and
    # free to change spelling, and the day it changes every `by_run` lookup misses
    # and this half of the tool silently stops asking anything.
    manifests = manifest_rels(rels)
    checked_manifests = 0
    pointers = 0
    resolved = 0
    for rel in manifests:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with io.open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            # NAMED, not skipped. A manifest nobody could read is not a manifest
            # with nothing wrong in it, and this tool is the only reader of these.
            out.append((rel, 0, "could not be read, so its cached verdicts were "
                                "not checked: %s" % (exc,)))
            continue
        if not isinstance(doc, dict):
            out.append((rel, 0, "is not a JSON object, so its cached verdicts "
                                "were not checked"))
            continue
        checked_manifests += 1
        held, hit = pointer_reach(doc, by_run)
        pointers += held
        resolved += hit
        for rel_, label, why in pointer_findings(rel, doc, known, by_run):
            out.append((rel_, label, why))

    if pointers and not resolved:
        return [], {}, (
            "%d cached testEvidence pointer(s) were found across %d manifest(s) "
            "and NOT ONE of them names a run any committed ledger holds, so the "
            "cache-agrees-with-the-ledger half of this run compared nothing - "
            "which is what a changed `runId` spelling looks like, and is not the "
            "same answer as a tree with nothing wrong in it"
            % (pointers, checked_manifests))

    counts = {"ledgers": len(ledgers), "rows": seen_rows,
              "manifests": checked_manifests, "vocabulary": len(known),
              "pointers": pointers, "resolved": resolved}
    return out, counts, None


def ok_line(counts):
    """The clean verdict, carrying what it looked at rather than just 'OK'."""
    return ("OK: %d row(s) across %d committed ledger(s) record a verdict the "
            "schema publishes, none contradicts its own observations, and %d of "
            "%d cached pointer(s) across %d manifest(s) resolved and agree "
            "(vocabulary: %d word(s))"
            % (counts["rows"], counts["ledgers"], counts["resolved"],
               counts["pointers"], counts["manifests"], counts["vocabulary"]))


# --- CLI ----------------------------------------------------------------------


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rows, counts, problem = findings()
    if problem:
        sys.stdout.write("REFUSED: %s\n" % (problem,))
        return 1
    if rows:
        for rel, where, why in rows:
            sys.stdout.write("FINDING %s%s\n        %s\n"
                             % (rel, (":%s" % (where,)) if where else "", why))
        sys.stdout.write("\nA committed ledger records a verdict the runner cannot "
                         "produce, or a cache disagrees with it. Fix the row, then "
                         "the pointer that copied it, then re-render every artifact "
                         "that prints it.\n")
        return 1
    sys.stdout.write(ok_line(counts) + "\n")
    return 0


def _cases(check):
    _known = frozenset({"passed", "failed", "gate-mutated"})

    # el1. The live claim.
    _rows, _counts, _problem = findings()
    check("el1 THE LIVE CLAIM: every committed ledger records a published verdict, "
          "no row contradicts its own observations, and no cache disagrees with "
          "the ledger: %r / %s" % (_rows, _problem),
          _problem is None and _rows == [])

    # el2. ...over a real set. `el1` returns [] over a tree it never reached too,
    # and telling those two apart is the whole point of the rule.
    check("el2 ...over a derivation that reached a REAL set, not an empty one - a "
          "run that compared no ledgers is the shape of a green run that checked "
          "nothing: %r" % (_counts,),
          _problem is None and _counts.get("ledgers", 0) >= 2
          and _counts.get("rows", 0) >= 5
          and _counts.get("manifests", 0) >= 2
          and _counts.get("vocabulary", 0) >= 7
          # ...and the POINTER half reached one too. This conjunct is the one that
          # was missing: `el1` returns [] over a run in which no pointer resolved
          # exactly as it does over a run in which every pointer agreed.
          and _counts.get("pointers", 0) >= 5
          and _counts.get("resolved", 0) == _counts.get("pointers", 0))

    # el3. The vocabulary is DERIVED, so it must contain the word F280 added and
    # must come from the schema rather than from a list in this file.
    _vocab, _vp = schema_statuses()
    check("el3 the vocabulary is read from the schema and carries F280's member, "
          "because a list here would be a second description of a set "
          "COMPATIBILITY.md refuses to close: %r / %s" % (sorted(_vocab), _vp),
          _vp is None and "gate-mutated" in _vocab and "passed" in _vocab)

    # el4. An unknown word is a finding, naming the word.
    _f = status_findings("x/evidence/a.jsonl",
                         [(3, {"runId": "r1", "status": "invented"})], _known)
    check("el4 a row whose status is outside the published vocabulary is a "
          "finding that NAMES the word: %r" % (_f,),
          len(_f) == 1 and _f[0][1] == 3 and "'invented'" in _f[0][2])

    # el5. ...and a row with no status at all is not one. An absent verdict is a
    # different state from a wrong one, and the schema says so in as many words.
    check("el5 ...and a row recording NO status is not a finding, because absent "
          "and wrong are different answers",
          status_findings("x/evidence/a.jsonl", [(1, {"runId": "r"})], _known) == [])

    # el6. The fault itself: F297's row.
    _c = contradiction_findings("x/evidence/a.jsonl", [
        (4, {"runId": "r1", "status": "passed",
             "observations": {"treeMutated": ["src/checkout/validate.ts"]}})])
    check("el6 F297's OWN ROW: `passed` beside a non-empty treeMutated is a "
          "finding, naming the file: %r" % (_c,),
          len(_c) == 1 and "validate.ts" in _c[0][2])

    # el7. THE NARROWING, and it is the case that stops el6 being satisfied by a
    # rule that fires on everything. A failed run that also moved files is telling
    # the truth, and an empty list is not a mutated tree.
    _quiet = contradiction_findings("x/evidence/a.jsonl", [
        (1, {"status": "failed", "observations": {"treeMutated": ["a.txt"]}}),
        (2, {"status": "passed", "observations": {"treeMutated": []}}),
        (3, {"status": "gate-mutated", "observations": {"treeMutated": ["a.txt"]}}),
        (4, {"status": "passed"}),
    ])
    check("el7 ...and none of `failed` with a mutated tree, `passed` with an EMPTY "
          "list, `gate-mutated`, or a row with no observations is one - the "
          "narrowing that keeps this a finding somebody fixes: %r" % (_quiet,),
          _quiet == [])

    # el8. A cache that disagrees with the ledger row it points at.
    _doc = {"phases": [{"id": "P2", "tasks": [
        {"id": "P2.1", "testEvidence": {"runId": "r9", "status": "passed"}}]}]}
    _p = pointer_findings("x/phases/P2.json", _doc, _known, {"r9": "gate-mutated"})
    check("el8 a cached verdict that DISAGREES with the ledger row its own runId "
          "names is a finding - the schema calls this block a cache, and a cache "
          "that can disagree with its source is what it was designed not to be: "
          "%r" % (_p,),
          len(_p) == 1 and _p[0][1] == "P2.1" and "gate-mutated" in _p[0][2])

    # el9. ...but a runId resolving NOWHERE is not, and neither is agreement. The
    # schema says an unresolvable pointer means "no evidence recorded".
    _ok = pointer_findings("x/phases/P2.json", _doc, _known, {})
    _same = pointer_findings("x/phases/P2.json", _doc, _known, {"r9": "passed"})
    check("el9 ...while a runId that resolves nowhere is NOT a finding (the ledger "
          "may be archived, and the schema reads an unresolvable pointer as 'no "
          "evidence recorded'), and neither is a cache that agrees: %r / %r"
          % (_ok, _same),
          _ok == [] and _same == [])

    # el10. A shard is one phase with no `phases` wrapper, which is the layout this
    # repo's own plan uses - so a rule that only read an index would be blind here.
    _shard = {"id": "P2", "tasks": [
        {"id": "P2.1", "testEvidence": {"runId": "r9", "status": "invented"}}]}
    _sp = pointer_findings("x/phases/P2.json", _shard, _known, {})
    check("el10 a SHARD (one phase, no `phases` wrapper) is read too, because the "
          "sharded layout is what this repo's own plan uses: %r" % (_sp,),
          len(_sp) == 1 and _sp[0][1] == "P2.1")

    # el11. A torn ledger is reported, never silently skipped.
    import tempfile
    _tmp = tempfile.mkdtemp(prefix="cel-")
    try:
        _torn = os.path.join(_tmp, "torn.jsonl")
        with io.open(_torn, "w", encoding="utf-8") as fh:
            fh.write('{"runId": "r1", "status": "passed"}\n{not json\n')
        _rows2, _trouble = read_rows(_torn)
        check("el11 a ledger with a torn row is a PROBLEM and not a skipped line - "
              "'no findings' and 'no findings in the part I could read' are "
              "different answers: %r / %r" % (_rows2, _trouble),
              _rows2 == [] and _trouble is not None and "line 2" in _trouble)
    finally:
        import shutil
        shutil.rmtree(_tmp, ignore_errors=True)

    # el12. The schema path is pinned, not searched for.
    check("el12 the vocabulary's location is a fixed path rather than 'the first "
          "enum containing passed', so this cannot silently start reading a "
          "different contract the schema grows: %r" % (STATUS_PATH,),
          STATUS_PATH == ("$defs", "testEvidence", "properties", "status"))

    # el13. Ledger discovery is by DIRECTORY, so an archived month is still one.
    _found = ledger_rels(["docs/audit/evidence/2026-09.abc.jsonl",
                          "examples/x/evidence/archive-2025.jsonl",
                          "docs/audit/journal/2026-09.abc.jsonl",
                          "examples/x/evidence/notes.md",
                          "evidence.jsonl"])
    check("el13 a ledger is recognised by the directory the writer puts it in, so "
          "an archived name is still one - and a journal, a stray .md and a "
          "top-level file are not: %r" % (_found,),
          _found == ["docs/audit/evidence/2026-09.abc.jsonl",
                     "examples/x/evidence/archive-2025.jsonl"])

    # el14. THE RENDERER'S FALLBACK. `_evidence_io` writes treeMutated twice - into
    # observations AND at the top level - and `_report_html.tev_flags` reads
    # `obs.get("treeMutated", row.get("treeMutated"))`. A checker reading only the
    # nested key passed a hand-written row the report drew a `tree-mutated` mark on.
    _nested_only = contradiction_findings("x/evidence/a.jsonl", [
        (1, {"status": "passed", "observations": {"treeMutated": ["a.txt"]}})])
    _top_only = contradiction_findings("x/evidence/a.jsonl", [
        (2, {"status": "passed", "treeMutated": ["b.txt"]})])
    _neither = contradiction_findings("x/evidence/a.jsonl", [
        (3, {"status": "passed", "observations": {}})])
    check("el14 a row carrying treeMutated only at the TOP level is caught too, "
          "because that is the key the report falls back to - and a row carrying "
          "it nowhere still is not a finding: %r / %r / %r"
          % (_nested_only, _top_only, _neither),
          len(_nested_only) == 1 and len(_top_only) == 1
          and "b.txt" in _top_only[0][2] and _neither == [])

    # el15. The pair that lets `findings()` tell "nothing disagreed" from "nothing
    # was compared" - a count of findings cannot, because both are zero.
    _reach_doc = {"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "testEvidence": {"runId": "r1", "status": "passed"}},
        {"id": "P1.2", "testEvidence": {"runId": "r2", "status": "passed"}},
        {"id": "P1.3", "status": "pending"}]}]}
    _all_hit = pointer_reach(_reach_doc, {"r1": "passed", "r2": "passed"})
    _none_hit = pointer_reach(_reach_doc, {})
    check("el15 pointer_reach counts pointers HELD and pointers RESOLVED apart, "
          "which is what makes a run where no runId resolves distinguishable from "
          "one where every cache agreed: %r vs %r" % (_all_hit, _none_hit),
          _all_hit == (2, 2) and _none_hit == (2, 0))


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
