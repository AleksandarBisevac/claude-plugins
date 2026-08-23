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
the gate itself - and names the case that must fail: by the leading id its label
carries, or by `substr("some words from the label")` for the many suites whose labels
are sentences. `redfirst.sh` does the mutating, because a second implementation of
mutate-run-restore is a second place for a mutation to be stranded.

WHAT IT COSTS. One suite per row, so a full run is minutes rather than seconds, and
it MUTATES THE WORKING TREE while it runs (restoring each time, under redfirst's
trap). It is not a per-commit gate; run it before a release, or when a lint changes.

`--selftest` NEVER MUTATES. It checks the table against the tree - that every anchor
still exists exactly once, and that no load-bearing lint is missing a row - which is
the half that rots, and it is safe to run inside the parallel sweep that runs every
other suite.
"""
import ast
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
CFG = "plugins/audit/tests/test__config_rules.py"

# The anchor every scripts/ row appends after: present once in every module, and
# nothing below it depends on what follows.
INSTALL = "\n_output.install_path()\n"

# A gate is a public function whose NAME says it reports drift or violations, plus
# the four that report it under a name of their own. Derived rather than listed so a
# lint added later is missing from the table LOUDLY - see `coverage()`.
_GATE_SHAPES = ("_violations", "_drift", "_claims")
_GATE_NAMED = ("selftest_coverage", "entries_missing_guard",
               "depth_sensitive_paths", "doc_prose_numbers")


# THE TWO PROSE-NUMBER PAYLOADS ARE BUILT, NOT WRITTEN, and that is not tidiness.
# `prose_number_claims()` now reads every `.py` this repo keeps, `tools/` included,
# so a payload spelling its own claim out would be a finding IN THE PROVER - the
# lint's needle planted in the tree the lint walks. The house repair is to build
# the literal rather than write it, so the count arrives through `%` and the line
# carries no numeral in front of the noun. `doc_prose_numbers()` reads every `.md`,
# which is why the CLAUDE.md payload gets the same treatment.# Where those lints live, relative to `scripts/`. A list, because it is what
# `coverage()` under-claims by if a module holding one is left off it - and that
# happened: `config/_config_rules.py` grew the config-vocabulary comparison and its
# `*_drift` names were invisible here until this tuple named the directory.
_GATE_MODULES = ("_output.py", "_deps.py", "_refs.py",
                 os.path.join("config", "_config_rules.py"))

# (lint, file, kind, anchor, payload, suite, expected case label)#
# `count` is a number OR the word for it: the second row of each pair exists to
# prove the numeral table still reads the word spelling (F59), and one builder
# serving both is what stops the two payloads drifting into different sentences.
def _claim_payload(count):
    """A probe function whose docstring makes a cardinality claim."""
    return ('\n\ndef _probe_claim():\n    """The table and its %s cases."""\n'
            '    return None\n' % (count,))


def _doc_claim_payload(count):
    """A prose line making a completeness claim, for the document scan."""
    return "\nThe tree carries all %s of them.\n" % (count,)


# (lint, file, kind, anchor, payload, suite, expected case label)
# --- naming the case a row is about -------------------------------------------
# A row's last field names the case whose failure IS the proof, and there are two
# spellings of that because the tree has two kinds of label. A leading identifier
# (`pp1`, `sc10`) is one; a sentence is the other, and the suites that open theirs
# with `the`, `a`, `no`, `every` or a colon-suffixed group tag are most of them:
#
#   grep -hoE 'check\("[^ "]+' plugins/audit/tests/*.py | sed 's/check("//' \
#     | grep -vE '^[a-z]+[0-9]' | sort -u
#
# Reading the first token was the only way in, so no row could point into any of
# those suites and the coarse whole-suite verdict was all they could ever get -
# which is the weaker claim this table exists to avoid (F74).
#
# The suites are NOT migrated to leading ids. Their labels are readable sentences,
# which is the right thing for whoever reads the failure; what was missing is
# machine addressability, so the machine side is what changed.
def substr(text):
    """A selector that names a case by a piece of its LABEL, not by a leading id.

    For the suites whose labels are sentences, and for a case sharing a family
    id with its siblings - `substr("sc9 the panel")` reaches one of four `sc9`
    cases that `AMBIGUOUS LABEL` is otherwise right to refuse.

    IT MUST STILL BE UNIQUE, and that is not a weakening of F63's rule but the
    same rule read one level up: the whole `RED, WRONG CASE` guarantee rests on
    the row naming exactly one case, so a selector matching two is refused
    exactly as a duplicated id is. A substring is enough to be unique and short
    enough to stay readable in the table.
    """
    return ("substr", text)


# (lint, file, kind, anchor, payload, suite, the case that must go red)#
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
  _claim_payload(12), OUT, "pn0"),
 # F59: the SAME lint, mutated in the word spelling. The digit row above cannot
 # notice a numeral table that has stopped reading words - which is the state this
 # repo shipped in until a count spelled out sat unnoticed in a comment block every
 # gate reads. Two rows for one lint, the way the house-style lint carries two.
 ("prose_number_claims", S + "_fmt.py", "after", INSTALL,
  _claim_payload("thirteen"), OUT, "pn0"),
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
  _doc_claim_payload(12), DEP, "dpn0"),
 ("doc_prose_numbers", "CLAUDE.md", "after", "\n## Tests\n",
  _doc_claim_payload("thirteen"), DEP, "dpn0"),
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
 # Two rows, one per direction, because the document graph fails in two ways and only
 # one of them is loud. The SILENT one first: the link is REPOINTED at a file that
 # exists, so nothing dangles and the changelog simply stops being reachable - which is
 # what a README reorganisation does, and what nothing in this tree noticed before.
 # `CHANGELOG.md` is the target because it has exactly one inbound link, so the
 # mutation isolates the orphan half instead of tripping both at once.
 ("doc_link_drift", "README.md", "sub", r"^- \[CHANGELOG\]\(CHANGELOG\.md\)",
  (r"\(CHANGELOG\.md\)", "(LICENSE)"), REF, "dl1"),
 # ...and the loud one: a target that names nothing, the shape a rename leaves behind.
 # The quickstart is reached from several documents, so this one cannot orphan it and
 # tests the resolution rather than the reachability.
 ("doc_link_drift", "README.md", "sub", r"^- \[QUICKSTART\]\(QUICKSTART\.md\)",
  (r"\(QUICKSTART\.md\)", "(QUICKSTART-moved.md)"), REF, "dl1"),
 # The absolute path is BUILT, never spelled - same rule as the `.py` name below,
 # and the same rule `test__refs.py` follows for its own fixtures. This table lives
 # in `tools/`, which `absolute_reach_violations` scans, so a literal here IS the
 # violation it exists to prove. Written spelled out first, and it turned the real
 # tree red: `ar1` then failed on this file for every row in the table.
 ("absolute_reach_violations", S + "_fmt.py", "after", INSTALL, None, REF, "ar1"),
 # BOTH ROWS BELOW USED TO NAME NO CASE, and the coarse verdict was the only
 # thing available to them - not because their suite could not be named, but
 # because nobody had looked. The names here were read off a live run of each
 # row (F74): `cf1` is the only case the flag mutation reddens, and the URL
 # mutation reddens the version-pin family, of which `p1` is one.
 ("command_flag_drift", "plugins/audit/commands/status.md", "suffix",
  r"^argument-hint:", " [--probe-flag]", REF, "cf1"),
 ("raw_url_pin_drift", "plugins/audit/README.md", "sub",
  r"raw\.githubusercontent\.com/.*/v[0-9]+\.[0-9]+\.[0-9]+/",
  (r"/v[0-9]+\.[0-9]+\.[0-9]+/", "/main/"), REF, "p1"),

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
  r'"areas\.png"', (r'"areas\.png"', '"areas-renamed.png"'), REF, "sc1"), # The config vocabulary. Three rows for the tree-bound half, because it has three
 # failure modes and only the first announces itself. `ui` was read by `_ui_theme`,
 # written by the panel, validated and defaulted - and unpublished in the schema for
 # its whole life, because `additionalProperties: true` accepts anything (F79). So
 # the row that would have caught that goes first: rename the schema property and a
 # key the plugin reads stops being published.
 ("config_vocab_drift", "plugins/audit/schema/audit-config.schema.json", "replace",
  '    "ui": {\n', '    "uiRenamed": {\n', CFG, "cv1"),
 # The same rule one surface further (F80): a lever with a panel control and no
 # published row. A RENAME rather than a deletion - deleting the row would also cut
 # the table's contiguous run and take every key below it down at once, which proves
 # the wrong thing.
 ("config_vocab_drift", "plugins/audit/README.md", "sub",
  r"^\| `bypassKeyword` \|", ("`bypassKeyword`", "`bypassKeywordd`"), CFG, "cv1"),
 # ...and the direction a markdown table makes possible at all: the heading moves,
 # nothing can be located, and the reader must SAY that rather than hand back the
 # empty finding list a clean table hands back. A parser that fails quiet is worse
 # than no parser, and this is the row that keeps it loud.
 ("config_vocab_drift", "plugins/audit/README.md", "replace",
  "## Configuration (`.claude/audit.config.json`)", "## Config keys", CFG, "cv1"),
 # The comparison itself, on the branch only it owns. Its cases are fixture-driven
 # for the reason `_help.vocab_drift()`'s are - a lint you can only run against the
 # real tree is a lint whose own failure modes are untested - so this row breaks the
 # rule and the fixture case goes red where the three above cannot.
 ("root_vocab_drift", S + "config/_config_rules.py", "replace",
  "set(known) - published - set(exempt)", "set()", CFG, "cv4"),)


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
    """Every load-bearing lint, derived by name from the modules that hold one."""
    import ast
    root = script_dir or _output.SCRIPTS_DIR
    found = []
    for rel in _GATE_MODULES:
        path = os.path.join(root, rel)
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


# --- the verdict, as a pure function of the report ----------------------------
COARSE = "RED (SUITE ONLY)"

# The verdicts that count as a gate proven. `COARSE` is one of them and says so
# in its own name: the row's mutation did redden its suite, and that is all it
# claims. A verdict list beats `!= "RED"` here because "proven" now has two
# strengths and a reader of the summary should be able to see which they got.
PROVEN = ("RED", COARSE)


def selector_text(target):
    """The text a row's selector matches on, whichever spelling it is."""
    return target[1] if isinstance(target, tuple) else target


def _selector_says(target):
    """How to name the selector in a message, so the two spellings read apart."""
    if isinstance(target, tuple):
        return "a case whose label contains %r" % (target[1],)
    return "the case named %s" % (target,)


def matches(label, target):
    """Does one rendered case label satisfy a row's selector?

    `label` is everything a report printed after `PASS `/`FAIL `. The id
    spelling reads the leading token, which is the key `_harness.case_id()`
    hands out and the one thing about a label that is checked for uniqueness.
    """
    if isinstance(target, tuple):
        return target[1] in label
    return label.split(None, 1)[:1] == [target]


def case_labels(text, only_failing=False):
    """Every case label a rendered report printed, in order.

    PASS lines count too, unless a caller asks otherwise, because ambiguity is
    a property of the suite and not of what this mutation happened to break: a
    selector whose twin PASSED is exactly as unattributable.
    """
    out = []
    for line in text.splitlines():
        if line.startswith("FAIL "):
            out.append(line[5:])
        elif line.startswith("PASS ") and not only_failing:
            out.append(line[5:])
    return out


def case_hits(text, target):
    """How many of a suite's cases the row's selector names.

    THE OTHER END OF F63. Every verdict below keys on the selector, so the whole
    `RED, WRONG CASE` guarantee rests on it naming exactly one case, and until
    this counted them nothing here could tell the difference between the case
    going red and its NAMESAKE going red. `pn10` named two cases in
    `test__output.py` while this file was already reading labels off
    `test__output.py`'s report.
    """
    return sum(1 for label in case_labels(text) if matches(label, target))


def failing_ids(text):
    """The leading token of every failing case, for the report's detail column."""
    return [label.split(None, 1)[0]
            for label in case_labels(text, only_failing=True)
            if label.split(None, 1)]


def verdict(target, gate, suite):
    """`(verdict, detail)` for a suite that went red - a pure function of its report.

    SPLIT FROM `prove()` BECAUSE THE INTERESTING BRANCHES ARE THE ONES A LIVE RUN
    NEVER TAKES. An ambiguous selector, a selector naming nothing, and a row that
    names no case at all are all states of the TABLE, so driving them through
    `prove()` would mean mutating the tree to prove something about a string. Here
    they are a rendered report written out in the selftest, and the sweep runs
    them with everything else.
    """
    base = os.path.basename(suite)
    ids = ", ".join(failing_ids(gate)[:4])
    if target is None:
        # SAID OUT LOUD, because a coarse claim wearing the same word as a precise
        # one is how "I could not be precise here" becomes invisible. Every case in
        # every suite is now nameable - `substr()` reaches the ones an id cannot -
        # so a row without a selector is a choice, and this is the line that asks
        # the next author to make it deliberately.
        return (COARSE,
                "no case named: the claim is only that %s went red. Any case can "
                "be named - a leading id, or substr() for a label that is a "
                "sentence" % (base,))
    hits = case_hits(gate, target)
    # BEFORE the wrong-case verdict, because that verdict is the thing being
    # checked: with the selector naming no case it is a rot report dressed as a
    # gate finding, and with it naming two it is worthless for this row.
    if hits == 0:
        return ("LABEL GONE",
                "%s is not in %s any more" % (_selector_says(target), base))
    if hits > 1:
        return ("AMBIGUOUS LABEL",
                "%d cases in %s match %r, so a red one credits nothing"
                % (hits, base, selector_text(target)))
    if not any(matches(label, target)
               for label in case_labels(gate, only_failing=True)):
        return ("RED, WRONG CASE",
                "expected %s, got %s" % (_selector_says(target), ids))
    return ("RED", ids)


# --- running ------------------------------------------------------------------
def prove(row, repo=None):
    """Mutate, run the suite, restore. Returns a dict; never raises on a red gate."""
    lint, rel, _kind, _anchor, _payload, suite, target = row
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
    cases = failing_ids(gate)
    if "REDFIRST FAILED" in text:
        return {"lint": lint, "verdict": "STAYED GREEN",
                "detail": "the gate asserts nothing about this", "cases": []}
    if "REDFIRST ok" not in text:
        last = [ln for ln in text.splitlines() if ln.strip()]
        return {"lint": lint, "verdict": "ERROR",
                "detail": (last[-1][:70] if last else "no output"), "cases": cases}
    said, detail = verdict(target, gate, suite)
    return {"lint": lint, "verdict": said, "detail": detail, "cases": cases}


def render(rows, missing, stream=None):
    out = stream if stream is not None else sys.stdout
    bad = [r for r in rows if r["verdict"] not in PROVEN]
    coarse = [r for r in rows if r["verdict"] == COARSE]
    for r in rows:
        out.write("  %-28s %-16s %s\n" % (r["lint"], r["verdict"], r["detail"]))
    out.write("\n")
    for name in missing:
        out.write("  NOT PROVEN AT ALL: %s has no row in the table\n" % (name,))
    for r in coarse:
        out.write("  NAMES NO CASE: %s is proven only by its whole suite going "
                  "red\n" % (r["lint"],))
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
def _cases(check):
    """Everything that can rot, checked WITHOUT mutating anything."""
    names = gate_names()
    check("c0 the gate set is DERIVED from the three modules by name, so a lint "
          "added later shows up here rather than being quietly unproven "
          "(%d found)" % (len(names),),
          len(names) >= 15 and "house_style_violations" in names)

    missing = coverage()
    check("c1 ...and every one of them has a row in the table. This is the case "
          "that fails the day somebody adds a lint and no mutation proves it: "
          "%r" % (missing,),
          missing == [])

    unanchored = []
    for row in TABLE:
        old, new = mutation(row)
        if old is None:
            unanchored.append((row[0], row[1], new))
    check("c2 every row's anchor is still in the tree, exactly once. An anchor "
          "that has moved makes `redfirst.sh` exit on a usage error, which "
          "reads nothing like 'this gate is no longer proven': %r"
          % (unanchored,),
          unanchored == [])

    changed = []
    for row in TABLE:
        old, new = mutation(row)
        if old is not None and old == new:
            changed.append(row[0])
    check("c3 ...and every mutation actually CHANGES the text - a row whose new "
          "text equals its old one would report a green gate as proven: %r"
          % (changed,),
          changed == [])

    labelled = [r[0] for r in TABLE if r[6] is not None]
    check("c4 most rows name the CASE that must fail, not just 'the suite went "
          "red' - a mutation can turn a suite red through a case that has "
          "nothing to do with the gate (%d of %d rows)"
          % (len(labelled), len(TABLE)),
          len(labelled) >= 12)

    suites = set(r[5] for r in TABLE)
    check("c5 every suite the table drives exists: %s"
          % (", ".join(sorted(os.path.basename(s) for s in suites)),),
          all(os.path.isfile(os.path.join(REPO, s)) for s in suites))

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
    check("c7 a row's selector is COUNTED in the suite's report, not merely "
          "found in it - two cases wearing one name make every verdict "
          "below meaningless for that row. F63; `_harness.run()` enforces "
          "the other half, for every suite",
          (case_hits(_report, "pn10"), case_hits(_report, "pn11"),
           case_hits(_report, "pn12")) == (2, 1, 0))

    # -- naming a case that has no leading id (F74) ----------------------------
    # THE FIXTURE IS A REAL SUITE'S OUTPUT, trimmed. `test__panel_viewer.py`
    # opens every label with one group tag, so the tag names every case in it and
    # the words after it are the only thing that tells them apart - which is
    # what a hand-written `t1`/`t2` fixture would have hidden.
    _sentences = ("PASS viewer: the first call really does resolve\n"
                  "FAIL viewer: with no identity file and no environment "
                  "moved, the second call resolves NOTHING\n"
                  "\n"
                  "SELFTEST FAILED: 1/2 cases passed\n")
    check("c8 an id selector reads the LEADING token and nothing else, so a "
          "suite whose labels open with a word or a group tag cannot be named "
          "by one - which is F74 stated as a measurement rather than as a "
          "complaint",
          case_hits(_sentences, "resolves") == 0
          and case_hits(_sentences, "viewer:") == 2)
    check("c9 ...and a substr() selector reaches exactly one of those two "
          "cases, by the words that tell them apart",
          case_hits(_sentences, substr("no identity file")) == 1
          and case_hits(_sentences, substr("the first call")) == 1)
    check("c10 a selector matching TWO cases is refused, in either spelling - "
          "the group tag and a substring that is not specific enough fail the "
          "same way, because the RED-WRONG-CASE guarantee rests on the "
          "selector naming one case",
          verdict("viewer:", _sentences, DEP)[0] == "AMBIGUOUS LABEL"
          and verdict(substr("call"), _sentences, DEP)[0] == "AMBIGUOUS LABEL")
    # THE DISTINGUISHABILITY CASE. A selector that names nothing and a gate that
    # noticed nothing are two different findings - one is a rotted table, the
    # other is a lint asserting nothing - and reporting either as the other sends
    # the reader to the wrong file. STAYED GREEN is `prove()`'s, and the two
    # strings are asserted apart here rather than trusted to differ.
    _gone = verdict(substr("a wording nothing in this suite carries"),
                    _sentences, DEP)
    check("c11 a selector naming NOTHING says the table has rotted, and says it "
          "differently from a gate that stayed green: %r" % (_gone,),
          _gone[0] == "LABEL GONE" and _gone[0] != "STAYED GREEN"
          and "test__deps.py" in _gone[1])
    check("c12 a selector naming exactly one FAILING case is the proof, and one "
          "naming exactly one case that PASSED is 'red, wrong case' - the pair, "
          "because a version that only counted matches would call both of them "
          "proven",
          verdict(substr("no identity file"), _sentences, DEP)[0] == "RED"
          and verdict(substr("the first call"), _sentences, DEP)[0]
          == "RED, WRONG CASE")

    # -- the coarse verdict says it is coarse ----------------------------------
    _coarse = verdict(None, _sentences, DEP)
    check("c13 a row that names no case gets a verdict of its OWN, which names "
          "the suite and says a case could have been named: %r" % (_coarse,),
          _coarse[0] == COARSE and "test__deps.py" in _coarse[1]
          and "substr()" in _coarse[1])
    _buf = io.StringIO()
    _code = render([{"lint": "probe_drift", "verdict": COARSE, "detail": "d",
                     "cases": []}], [], stream=_buf)
    check("c14 ...and it still counts as PROVEN - the row's mutation did redden "
          "its suite - while the summary says out loud that this one names no "
          "case: %r" % (_buf.getvalue(),),
          _code == 0 and "NAMES NO CASE: probe_drift" in _buf.getvalue())
    # c15 LOOKS VACUOUS AND IS THE SECOND-DIRECTION CASE: it passes on a render
    # that never learned about the coarse verdict, and it is the only one here
    # that fails if that line starts printing for every row.
    _buf = io.StringIO()
    render([{"lint": "probe_drift", "verdict": "RED", "detail": "x1",
             "cases": ["x1"]}], [], stream=_buf)
    check("c15 a row that DOES name its case gets no such line, so the notice "
          "means something when it appears",
          "NAMES NO CASE" not in _buf.getvalue())

    # ASSERTED FROM THE AST, because the old form was `"--selftest" in
    # sys.argv[1:] or True` - a comment wearing a PASS line, which cannot fail and
    # so guaranteed nothing about the property it names. `prove()` is what mutates
    # (it shells out to redfirst.sh), so the checkable statement is that the suite
    # never reaches it.
    _c6_tree = ast.parse(io.open(__file__, encoding="utf-8").read())
    _c6_fns = [_n for _n in _c6_tree.body
               if isinstance(_n, ast.FunctionDef) and _n.name == "_cases"]
    _c6_calls = sorted(set(
        (_c.func.id if isinstance(_c.func, ast.Name) else _c.func.attr)
        for _fn in _c6_fns for _c in ast.walk(_fn)
        if isinstance(_c, ast.Call)
        and ((isinstance(_c.func, ast.Name) and _c.func.id == "prove")
             or (isinstance(_c.func, ast.Attribute)
                 and isinstance(_c.func.value, ast.Name)
                 and _c.func.value.id == "subprocess"))))
    check("c6 THIS SUITE MUTATES NOTHING. It is run by the parallel sweep "
          "alongside every other suite in the tree, and a mutation here would "
          "change what all of them see mid-run - so the expensive half lives "
          "in main() and this suite never reaches `prove()`: %r" % (_c6_calls,),
          len(_c6_fns) == 1 and _c6_calls == [])

def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
