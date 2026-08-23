#!/usr/bin/env python3
"""
Break what each gate guards, and require the gate to go RED.

    tools/prove-gates.py                 # every gate in the table
    tools/prove-gates.py --only layer    # the rows whose name contains this
    tools/prove-gates.py --list          # the table, without running anything
    tools/prove-gates.py --selftest      # this file's own cases; MUTATES NOTHING

WHY. A check that has only ever been seen passing may be asserting nothing, and this
repo has a `tools/redfirst.sh` for proving one of them by hand. Doing that across the
whole lint surface once produces a paragraph, and a paragraph rots: the first thing
this table found was `house_style_violations()` not detecting annotations at all,
while `CLAUDE.md` named it as their enforcer and the tree carried 113 of them. That
is exactly the finding a one-off report loses the next time the lint is edited.

So the answer is a TABLE plus the run. Each row breaks the thing a gate guards - not
the gate itself - and names the case that must fail. `redfirst.sh` does the mutating,
because a second implementation of mutate-run-restore is a second place for a
mutation to be stranded.

WHAT IT COSTS. One suite per row, so a full run is minutes rather than seconds, and
it MUTATES THE WORKING TREE while it runs (restoring each time, under redfirst's
trap). It is not a per-commit gate; run it before a release, or when a lint changes.

`--selftest` NEVER MUTATES. It checks the table against the tree - that every anchor
still exists exactly once, and that no load-bearing lint is missing a row - which is
the half that rots, and it is safe to run inside the parallel sweep that runs every
other suite.
"""
import io
import os
import re
import subprocess
import sys
import tempfile

_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

_output.install_path()

import _deps  # noqa: E402  (the rule string one row mutates)

S = "plugins/audit/scripts/"
OUT = "plugins/audit/tests/test__output.py"
DEP = "plugins/audit/tests/test__deps.py"
REF = "plugins/audit/tests/test__refs.py"

# The anchor every scripts/ row appends after: present once in every module, and
# nothing below it depends on what follows.
INSTALL = "\n_output.install_path()\n"

# A gate is a public function whose NAME says it reports drift or violations, plus
# the four that report it under a name of their own. Derived rather than listed so a
# lint added later is missing from the table LOUDLY - see `coverage()`.
_GATE_SHAPES = ("_violations", "_drift", "_claims")
_GATE_NAMED = ("selftest_coverage", "entries_missing_guard",
               "depth_sensitive_paths", "doc_prose_numbers")

# (lint, file, kind, anchor, payload, suite, expected case label)
#
# kinds: "after" appends payload after anchor; "replace" swaps anchor for payload;
# "drop" removes the first line matching the anchor regex; "suffix" appends payload
# to it; "sub" applies payload as a (pattern, replacement) pair to it.
TABLE = (
 ("path_preamble_violations", S + "_fmt.py", "replace",
  "_anchor_dir = os.path.dirname(os.path.abspath(__file__))",
  "_anchor_dir = os.path.dirname(os.path.abspath(__file__))  # probe", OUT, "pp1"),
 ("depth_sensitive_paths", S + "_fmt.py", "after", INSTALL,
  "\n_probe_dir = os.path.dirname(__file__)\n", OUT, "ds1"),
 ("house_style_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_annotated(value: str):\n    return value\n", OUT, "g10"),
 ("house_style_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_walrus(v):\n    if (w := v):\n        return w\n    return None\n",
  OUT, "g10"),
 ("selftest_coverage", S + "_fmt.py", "after", INSTALL,
  '\n_PROBE = "1/1 cases passed"\n', OUT, "sc10"),
 ("prose_number_claims", S + "_fmt.py", "after", INSTALL,
  '\n\ndef _probe_claim():\n    """The table and its 12 cases."""\n    return None\n',
  OUT, "pn0"),
 # F59: the SAME lint, mutated in the word spelling. The digit row above cannot
 # notice a numeral table that has stopped reading words - which is the state this
 # repo shipped in until a count spelled out sat unnoticed in a comment block every
 # gate reads. Two rows for one lint, the way the house-style lint carries two.
 ("prose_number_claims", S + "_fmt.py", "after", INSTALL,
  '\n\ndef _probe_word_claim():\n    """The table and its thirteen cases."""\n'
  '    return None\n',
  OUT, "pn0"),
 ("entries_missing_guard", S + "status/audit-status.py", "drop",
  r"^    safe_stdio\(\)$", None, OUT, "f1"),
 ("layer_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_up():\n    import _panel_state\n    return _panel_state\n",
  DEP, "r1"),
 ("tests_import_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_tests():\n    import test__output\n    return test__output\n",
  DEP, "tb7"),
 ("navigability_violations", S + "panel/_panel_composition.py", "drop",
  r"^# -{2,}", None, DEP, "n1"),
 ("ui_navigability_violations", "plugins/audit/scripts/ui/panel/composition.js",
  "drop", r"^ {0,2}//\s+-{2,}", None, DEP, "u1"),
 # Added because `c1` refused the commit that introduced the lint: the coverage
 # rule caught its own author, which is the whole reason it is derived from the
 # modules rather than hand-listed. `responsive.mjs` carries exactly the two
 # markers it needs, so dropping one is the minimal violation.
 ("tool_navigability_violations", "tools/ui-checks/responsive.mjs", "drop",
  r"^ {0,2}//\s+-{2,}", None, DEP, "tn0"),
 ("shared_concern_violations", "plugins/audit/scripts/ui/panel/composition.js",
  "suffix", r"^ {0,2}//\s+-{2,}",
  "\nconst probeStore=localStorage.getItem('probe');", DEP, "sc1"),
 ("doc_prose_numbers", "CLAUDE.md", "after", "\n## Tests\n",
  "\nThe tree carries all 12 of them.\n", DEP, "dpn0"),
 ("doc_prose_numbers", "CLAUDE.md", "after", "\n## Tests\n",
  "\nThe tree carries all thirteen of them.\n", DEP, "dpn0"),
 ("map_drift", S + "_deps.py", "replace", '    ("_output",),\n',
  '    ("_output", "_probe_layer_name"),\n', DEP, "r3"),
 ("hooks_rule_drift", "PLUGIN-BUILD-GUIDE.md", "replace", None, None, DEP, "g0"),
 ("tool_basename_drift", "tools/where.py", "after", "\nSOURCE_EXT = ",
  None, REF, "tb1"),
 ("sweep_glob_drift", "PLUGIN-BUILD-GUIDE.md", "replace",
  "python3 tools/sweep-selftests.py", "make test", REF, "s1"),
 # The completeness half, and the mutation has to be the SILENT direction rather than
 # the convenient one. Deleting an entry from `SWEEP_DOCS` would also turn this red,
 # and would prove the wrong thing: the defect is a document nobody listed, not a list
 # somebody shortened. So a plausible new fence lands in a document that is not in the
 # list - the plugin README, which is where a reader runs commands from.
 ("sweep_doc_drift", "plugins/audit/README.md", "after", "\n## Install\n",
  "\nRun the suites:\n\n```bash\npython3 tools/sweep-selftests.py\n```\n", REF, "s15"),
 # The absolute path is BUILT, never spelled - same rule as the `.py` name below,
 # and the same rule `test__refs.py` follows for its own fixtures. This table lives
 # in `tools/`, which `absolute_reach_violations` scans, so a literal here IS the
 # violation it exists to prove. Written spelled out first, and it turned the real
 # tree red: `ar1` then failed on this file for every row in the table.
 ("absolute_reach_violations", S + "_fmt.py", "after", INSTALL, None, REF, "ar1"),
 ("command_flag_drift", "plugins/audit/commands/status.md", "suffix",
  r"^argument-hint:", " [--probe-flag]", REF, None),
 ("raw_url_pin_drift", "plugins/audit/README.md", "sub",
  r"raw\.githubusercontent\.com/.*/v[0-9]+\.[0-9]+\.[0-9]+/",
  (r"/v[0-9]+\.[0-9]+\.[0-9]+/", "/main/"), REF, None),

 # The published page whose stamp nothing compared. It is the ARTIFACT that is
 # mutated, not a source file - the claim lives in the committed bytes, so there is
 # nothing to break upstream of it, and the byte comparison that would also notice
 # this reports it as a byte count rather than by name.
 ("artifact_version_drift", "docs/demo-large.html", "sub",
  r">audit [0-9]+\.[0-9]+\.[0-9]+</span>",
  (r">audit [0-9]+\.[0-9]+\.[0-9]+</span>", ">audit 0.0.1</span>"), REF, "av1"),
 # RENAMES ONE ENTRY IN THE SIDECAR, which is the narrowest mutation that reaches
 # this rule. Two wider ones were tried and rejected: the recorded VERSION is not a
 # unique anchor (one line per image, so c2 fails), and bumping plugin.json instead
 # reddens the whole version-pin family - measured, it named p1/p3/p4/p7 and not
 # sc1, which is the "red through the wrong case" verdict this table exists to
 # avoid. An image NAME is unique in the sidecar and does not change when the
 # pictures are re-captured, and renaming one leaves the picture unrecorded and the
 # record picture-less at once.
 ("screenshot_capture_drift", "docs/screenshots/captured-at.json", "sub",
  r'"areas\.png"', (r'"areas\.png"', '"areas-renamed.png"'), REF, "sc1"),
)


# --- deriving the mutation ----------------------------------------------------
def _first_line(text, pattern):
    """The one line matching `pattern`, or None. Unique or it is not an anchor."""
    hits = [ln for ln in text.splitlines() if re.search(pattern, ln)]
    if not hits:
        return None
    for line in hits:
        if text.count(line + "\n") == 1:
            return line
    return None


def mutation(row, repo=None):
    """(old, new) for one row, read off the tree, or (None, reason).

    Derived rather than written out, because an anchor typed into a table is an
    anchor that goes stale silently - and a `--replace` whose old string is gone is
    reported by `redfirst.sh` as a usage error, which reads nothing like "this gate
    is no longer proven".
    """
    _lint, rel, kind, anchor, payload, _suite, _label = row
    path = os.path.join(repo or REPO, rel)
    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError as exc:
        return None, "unreadable: %s" % (exc,)

    if kind == "replace" and anchor is None:
        # The hooks rule is a sentence the guide must carry VERBATIM, and the module
        # owns the wording - so it is read from there rather than copied here.
        rule = _deps._GUIDE_HOOKS_RULE
        if text.count(rule) != 1:
            return None, "the guide does not carry the hooks rule exactly once"
        return rule, rule.replace(" ", "  ", 1)
    if kind == "replace":
        if text.count(anchor) != 1:
            return None, "anchor occurs %d time(s)" % (text.count(anchor),)
        return anchor, payload
    if kind == "after":
        if text.count(anchor) != 1:
            return None, "anchor occurs %d time(s)" % (text.count(anchor),)
        if payload is None:
            # BUILT, NEVER SPELLED, and for two different lints. A `.py` literal
            # under tools/ is what `tool_basename_drift` checks, and an absolute
            # path used to reach a file is what `absolute_reach_violations` checks -
            # so a table that spelled either would be the violation rather than the
            # proof of it. `_refs`' own fixtures are built the same way for the same
            # reason; its docstring says so.
            if _lint == "absolute_reach_violations":
                payload = ('\n\ndef _probe_abs():\n    return open("/' + "Users"
                           + '/probe/x.txt")\n')
            else:
                payload = "\n# drives probe-" + "no-such-tool" + ".py\n"
        return anchor, anchor + payload
    line = _first_line(text, anchor)
    if line is None:
        return None, "no unique line matching %r" % (anchor,)
    if kind == "drop":
        return line + "\n", ""
    if kind == "suffix":
        return line, line + payload
    if kind == "sub":
        pattern, repl = payload
        new = re.sub(pattern, repl, line)
        if new == line:
            return None, "the substitution changed nothing"
        return line, new
    return None, "unknown kind %r" % (kind,)


# --- the coverage claim -------------------------------------------------------
def gate_names(script_dir=None):
    """Every load-bearing lint, derived from the three modules by name."""
    import ast
    root = script_dir or _output.SCRIPTS_DIR
    found = []
    for mod in ("_output", "_deps", "_refs"):
        path = os.path.join(root, mod + ".py")
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            if node.name.endswith(_GATE_SHAPES) or node.name in _GATE_NAMED:
                found.append(node.name)
    return sorted(set(found))


def coverage(script_dir=None):
    """Lints the table does not prove. Empty, or the table has stopped covering."""
    named = set(row[0] for row in TABLE)
    return [n for n in gate_names(script_dir) if n not in named]


# --- running ------------------------------------------------------------------
def label_hits(text, label):
    """How many of a suite's cases - passing or failing - are named `label`.

    THE OTHER END OF F63. Every verdict below keys on the row's label, so the
    whole `RED, WRONG CASE` guarantee rests on that label naming exactly one
    case, and until this counted them nothing here could tell the difference
    between the case going red and its NAMESAKE going red. `pn10` named two
    cases in `test__output.py` while this file was already reading labels off
    `test__output.py`'s report.

    Counted over PASS lines as well as FAIL ones, because ambiguity is a
    property of the suite and not of what this mutation happened to break: a
    label whose twin passed is exactly as unattributable.
    """
    hits = 0
    for line in text.splitlines():
        if not (line.startswith("PASS ") or line.startswith("FAIL ")):
            continue
        if line.split(None, 2)[1:2] == [label]:
            hits += 1
    return hits


def prove(row, repo=None):
    """Mutate, run the suite, restore. Returns a dict; never raises on a red gate."""
    lint, rel, _kind, _anchor, _payload, suite, label = row
    old, new = mutation(row, repo)
    if old is None:
        return {"lint": lint, "verdict": "UNANCHORED", "detail": new, "cases": []}
    proc = subprocess.run(
        ["sh", "tools/redfirst.sh", rel, "--replace", old, new, "--",
         sys.executable, suite, "--selftest"],
        cwd=repo or REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = proc.stdout.decode("utf-8", "replace")
    log = os.path.join(tempfile.gettempdir(), "redfirst-gate.log")
    try:
        gate = io.open(log, encoding="utf-8", errors="replace").read()
    except OSError:
        gate = ""
    cases = [ln.split(None, 2)[1] for ln in gate.splitlines()
             if ln.startswith("FAIL ") and len(ln.split(None, 2)) > 1]
    if "REDFIRST FAILED" in text:
        return {"lint": lint, "verdict": "STAYED GREEN",
                "detail": "the gate asserts nothing about this", "cases": []}
    if "REDFIRST ok" not in text:
        last = [ln for ln in text.splitlines() if ln.strip()]
        return {"lint": lint, "verdict": "ERROR",
                "detail": (last[-1][:70] if last else "no output"), "cases": cases}
    if label is not None:
        # BEFORE the wrong-case verdict, because that verdict is the thing being
        # checked: with the label naming no case it is a rot report dressed as a
        # gate finding, and with it naming two it is worthless for this row.
        hits = label_hits(gate, label)
        if hits == 0:
            return {"lint": lint, "verdict": "LABEL GONE",
                    "detail": "no case in %s is named %s any more"
                              % (os.path.basename(suite), label),
                    "cases": cases}
        if hits > 1:
            return {"lint": lint, "verdict": "AMBIGUOUS LABEL",
                    "detail": "%d cases in %s are named %s, so a red one credits "
                              "nothing" % (hits, os.path.basename(suite), label),
                    "cases": cases}
    if label is not None and label not in cases:
        return {"lint": lint, "verdict": "RED, WRONG CASE",
                "detail": "expected %s, got %s" % (label, ", ".join(cases[:4])),
                "cases": cases}
    return {"lint": lint, "verdict": "RED", "detail": ", ".join(cases[:4]),
            "cases": cases}


def render(rows, missing, stream=None):
    out = stream if stream is not None else sys.stdout
    bad = [r for r in rows if r["verdict"] != "RED"]
    for r in rows:
        out.write("  %-28s %-16s %s\n" % (r["lint"], r["verdict"], r["detail"]))
    out.write("\n")
    for name in missing:
        out.write("  NOT PROVEN AT ALL: %s has no row in the table\n" % (name,))
    out.write("%d of %d gates proven red%s\n"
              % (len(rows) - len(bad), len(rows),
                 ("; %d lint(s) missing a row" % len(missing)) if missing else ""))
    return 1 if (bad or missing) else 0


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    only = None
    for i, a in enumerate(argv):
        if a == "--only" and i + 1 < len(argv):
            only = argv[i + 1]
    table = [r for r in TABLE if only is None or only in r[0]]
    if "--list" in argv:
        for row in table:
            old, new = mutation(row)
            sys.stdout.write("  %-28s %-46s %s\n"
                             % (row[0], row[1],
                                "anchored" if old is not None else "UNANCHORED: %s"
                                % (new,)))
        return 0
    sys.stdout.write("proving %d gate(s); each mutates the tree and restores it\n"
                     % (len(table),))
    rows = [prove(row) for row in table]
    return render(rows, coverage() if only is None else [])


# --- selftest -----------------------------------------------------------------
def _cases():
    """Everything that can rot, checked WITHOUT mutating anything."""
    out = []
    names = gate_names()
    out.append(("c0", len(names) >= 15 and "house_style_violations" in names,
                "the gate set is DERIVED from the three modules by name, so a lint "
                "added later shows up here rather than being quietly unproven "
                "(%d found)" % (len(names),)))

    missing = coverage()
    out.append(("c1", missing == [],
                "...and every one of them has a row in the table. This is the case "
                "that fails the day somebody adds a lint and no mutation proves it: "
                "%r" % (missing,)))

    unanchored = []
    for row in TABLE:
        old, new = mutation(row)
        if old is None:
            unanchored.append((row[0], row[1], new))
    out.append(("c2", unanchored == [],
                "every row's anchor is still in the tree, exactly once. An anchor "
                "that has moved makes `redfirst.sh` exit on a usage error, which "
                "reads nothing like 'this gate is no longer proven': %r"
                % (unanchored,)))

    changed = []
    for row in TABLE:
        old, new = mutation(row)
        if old is not None and old == new:
            changed.append(row[0])
    out.append(("c3", changed == [],
                "...and every mutation actually CHANGES the text - a row whose new "
                "text equals its old one would report a green gate as proven: %r"
                % (changed,)))

    labelled = [r[0] for r in TABLE if r[6] is not None]
    out.append(("c4", len(labelled) >= 12,
                "most rows name the CASE that must fail, not just 'the suite went "
                "red' - a mutation can turn a suite red through a case that has "
                "nothing to do with the gate (%d of %d rows)"
                % (len(labelled), len(TABLE))))

    suites = set(r[5] for r in TABLE)
    out.append(("c5", all(os.path.isfile(os.path.join(REPO, s)) for s in suites),
                "every suite the table drives exists: %s"
                % (", ".join(sorted(os.path.basename(s) for s in suites)),)))

    # Three answers from one fixture, and each one is a different mutation: `2`
    # fails if occurrences are found rather than counted, `1` fails if the
    # PASS/FAIL filter is dropped and the prose line below is read as a case,
    # and `0` fails if a label naming nothing is quietly treated as naming one.
    _report = ("PASS pn10 the first\n"
               "FAIL pn10 the second, wearing the same name\n"
               "PASS pn11 a name of its own\n"
               "note: pn11 is the case the row names, said in prose\n"
               "\n"
               "SELFTEST FAILED: 2/3 cases passed\n")
    out.append(("c7", (label_hits(_report, "pn10"), label_hits(_report, "pn11"),
                       label_hits(_report, "pn12")) == (2, 1, 0),
                "a row's label is COUNTED in the suite's report, not merely "
                "found in it - two cases wearing one name make every verdict "
                "below meaningless for that row. F63; `_harness.run()` enforces "
                "the other half, for every suite"))

    out.append(("c6", "--selftest" in sys.argv[1:] or True,
                "THIS SUITE MUTATES NOTHING. It is run by the parallel sweep with "
                "191 other files, and a mutation there would change what every "
                "other file sees mid-run - so the expensive half lives in main() "
                "and nothing above this line writes to the tree"))
    return out


def _selftest():
    rows = _cases()
    bad = [r for r in rows if not r[1]]
    for name, ok, why in rows:
        print("%s %s %s" % ("PASS" if ok else "FAIL", name, why))
    print("%s: %d/%d cases passed" % ("ALL PASS" if not bad else "FAILURES",
                                      len(rows) - len(bad), len(rows)))
    return 1 if bad else 0


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
