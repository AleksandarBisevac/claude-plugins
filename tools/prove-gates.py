#!/usr/bin/env python3
"""
Break what each gate guards, and require the gate to go RED. Then weaken each guard
until it over-fires, and require it to have been proven QUIET.

    tools/prove-gates.py                 # both directions, for every row
    tools/prove-gates.py --red           # only the break-it-and-see-red half
    tools/prove-gates.py --allow         # only the stays-quiet half
    tools/prove-gates.py --only layer    # the rows whose name contains this
    tools/prove-gates.py --list          # the tables, without running anything
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

AND `ALLOW` IS THE SAME MACHINERY POINTED THE OTHER WAY (F55). Proving a check goes
red is one half of its specification; the half nothing here asserted is that it says
NOTHING about legitimate input, which is the failure this repo ships most often - a
guard that refuses a write for what the prose inside it quoted, and then gets routed
around. An allow row weakens the GUARD until it over-fires and requires a case
asserting a known-good input to go red. Its own header says how the mutations are
chosen and where an allow case is not meaningful.

WHAT IT COSTS. One suite per row, so a full run is minutes rather than seconds, and
it MUTATES THE WORKING TREE while it runs (restoring each time, under redfirst's
trap). It is not a per-commit gate; run it before a release, or when a lint changes.

`--selftest` NEVER MUTATES. It checks the table against the tree - that every anchor
still exists exactly once, that no load-bearing lint is missing a row, and that no
row names a lint the tree has stopped deriving - which is the half that rots, and it
is safe to run inside the parallel sweep that runs every other suite.

THAT LAST DIRECTION IS NOT SYMMETRY FOR ITS OWN SAKE. A row whose lint was deleted
or renamed does not go quiet: its anchor may still be in the file, so the mutation
still reddens the suite, the named case still fails, and the row is counted as a
gate proven while proving a rule that is gone. `coverage()` cannot see it - a lint
nothing derives can never be reported as missing a row - so the table would go on
growing as a record of its own history. `stale_rows()` is the other end.
"""
import ast
import io
import os
import re
import shutil
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
ADP = "plugins/audit/tests/test__ado_parent.py"
ADC = "plugins/audit/tests/test__ado_conventions.py"

# The anchor every scripts/ row appends after: present once in every module, and
# nothing below it depends on what follows.
INSTALL = "\n_output.install_path()\n"

# A gate is a public function whose NAME says it reports drift or violations, plus
# the four that report it under a name of their own. Derived rather than listed so a
# lint added later is missing from the table LOUDLY - see `coverage()`.
_GATE_SHAPES = ("_violations", "_drift", "_claims")
_GATE_NAMED = ("selftest_coverage", "entries_missing_guard",
               "depth_sensitive_paths", "doc_prose_numbers", "scratch_debris")


# THE TWO PROSE-NUMBER PAYLOADS ARE BUILT, NOT WRITTEN, and that is not tidiness.
# `prose_number_claims()` now reads every `.py` this repo keeps, `tools/` included,
# so a payload spelling its own claim out would be a finding IN THE PROVER - the
# lint's needle planted in the tree the lint walks. The house repair is to build
# the literal rather than write it, so the count arrives through `%` and the line
# carries no numeral in front of the noun. `doc_prose_numbers()` reads every `.md`,
# which is why the CLAUDE.md payload gets the same treatment.

# Where those lints live, relative to `scripts/`. A list, because it is what
# `coverage()` under-claims by if a module holding one is left off it - and that
# happened: `config/_config_rules.py` grew the config-vocabulary comparison and its
# `*_drift` names were invisible here until this tuple named the directory.
_GATE_MODULES = ("_output.py", "_deps.py", "_refs.py",
                 os.path.join("config", "_config_rules.py"),
                 os.path.join("manifest", "_ado_parent.py"),
                 # ADDED WITH ITS ROWS, WHICH IS THE ONLY WAY IT MAY BE ADDED.
                 # This tuple was scoped to one module of `manifest/` on the
                 # argument that naming the directory would demand rows for
                 # `_ado_conventions`' lints and none existed - a coverage rule
                 # that arrives already failing gets an exemption written for it
                 # on day one, which is how an exemption table stops meaning
                 # anything. The answer to that is the rows, not the narrower
                 # scope: the module kept growing (a typeless-rule reason and a
                 # fetched-row translator) while nothing here could notice, so
                 # the uncovered surface grew behind an argument for leaving it
                 # uncovered. Each of its lints has a row in each table below.
                 os.path.join("manifest", "_ado_conventions.py"))

# ...and the guards that do not live in the plugin at all, repo-relative because
# they are not under `scripts/`. The first was reachable through `GUARD_FILES` for
# mutation and through neither table's coverage rule for NAMING, which is why
# `scratch_debris` sat in both tables while `gate_names()` derived it from nowhere:
# `coverage()` could not miss it (a lint it never names cannot be reported absent)
# and `stale_rows()` would have reported the live row as dead. One derivation,
# reaching every file that holds a lint, is what makes both directions honest.
#
# `tools/_suite.py` is here for `unsafe_removal_violations()` (F155), which refuses a
# tool that builds a git repository with objects in it and then removes the tree with
# a call that cannot unlink a read-only file. It joins this tuple in the same commit
# as its rows, which is the only way anything may join it: a coverage rule that
# arrives already failing gets an exemption written for it on day one, and that is
# how an exemption table stops meaning anything.
#
# ITS NEIGHBOUR IN THAT FILE WAS THE HOLE (F166). `hand_rolled_runners()` keeps every
# tool's selftest on the shared harness, and it had a row in neither table and no
# recorded reason for having none - because its NAME ends in no shape above and it is
# not in the list below, so nothing here could see it and `coverage()` could never
# report it absent. The repair was NOT to rename the function to fit the pattern: a
# gate the derivation cannot see is a hole in the derivation, and renaming would have
# closed this instance while leaving the next one to be found the same way.
# `_TREE_WALKS` is the arm that closes it, and asking the question of the whole tree
# found a second: `_output.redundant_constants()`, load-bearing since the day it was
# written, asserted over the real tree by its own suite, and proven by nothing.
_GATE_OUTSIDE = ("tools/sweep-selftests.py", "tools/_suite.py")

# THE ARM THAT DOES NOT READ A NAME. A lint here judges the REPOSITORY: it takes no
# required argument and walks the tree with one of the shared walks, and everything
# else about it - what it is called, what it reports - is style. Both halves are
# needed. Without the walk, every parameterless helper in a gate module is a
# candidate; without the parameterless half, the per-source pure functions these
# lints are built out of (`runner_problem`, `removal_problem`) would be counted
# twice under two names for one rule.
#
# THE WALKS ARE NAMED RATHER THAN GUESSED AT, because a walk is a shared thing here
# and a second one would already be a defect: `_output.py_files()` is the recursive
# walk the sweep, the lints and the classifier all use, `lint_py_files()` is its
# scoped sibling, and `kept_files()` is the derived-off-`.gitignore` set the prose
# scans read.
_TREE_WALKS = ("py_files", "lint_py_files", "kept_files")

# THE FILES AN `ALLOW` ROW MAY MUTATE: every file that HOLDS a guard, repo-relative.
# `_GATE_MODULES` under `scripts/`, plus the guards that do not live in the plugin at
# all - `sweep-selftests.py`'s `scratch_debris()`, which refuses a suite that changed
# the directory it was run from (F119), and `_suite.py`'s removal rule. Each has the
# same two halves as any lint above and earns rows in both tables for the same reason.
#
# NAMED, NOT WIDENED TO A DIRECTORY. `a3`'s property is that an ALLOW row mutates the
# GUARD and never the thing the guard watches. Admitting all of `tools/` would admit
# every document and rendered artifact a tool reads, which is the direction the red
# table already covers - so each guard is added by name and the next one will have to
# be too.
GUARD_FILES = tuple([S + m.replace(os.sep, "/") for m in _GATE_MODULES]
                    + list(_GATE_OUTSIDE))

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
#
# `replace` IS THE KIND THAT SPANS LINES, and writing that down is F149's answer.
# `drop`, `suffix` and `sub` all reach their target through `_first_line()`, so one
# line is all they can ever touch; `replace` is a whole-TEXT count and swap, here
# and again in `redfirst.sh`, so its anchor may be a block and a row may therefore
# change two statements at once.
#
# THAT IS NOT A DETAIL, because a narrowing is not always one line. Whole-line
# equality in `_preamble_line_repeats()` is whole-line equality in TWO places - the
# match, and the key the seen-set remembers - and a mutation that widened one of
# them leaves a rule the tree still passes, which is a row reporting a guard proven
# while it proved nothing. The alternative on offer was a column recording that a
# direction had been proven BY HAND somewhere else. That is the paragraph this file
# was written to replace, and it would have spelled "proven elsewhere" the same way
# `ALLOW_EXEMPT` spells "a row here would prove nothing" - two different states, one
# spelling, which is the defect that table's own docstring names. So the row is a
# row. `c2b` pins the capability and its use together, because a `replace` quietly
# rewritten to read lines would strand every row of this shape at once.
TABLE = (
 ("path_preamble_violations", S + "_fmt.py", "replace",
  "_anchor_dir = os.path.dirname(os.path.abspath(__file__))",
  "_anchor_dir = os.path.dirname(os.path.abspath(__file__))  # probe", OUT, "pp1"),
 # F94: THE SAME LINT, MUTATED IN THE HALF THE ROW ABOVE CANNOT REACH. That one
 # breaks the block so the WHOLE-TEXT count falls to zero; this one leaves the block
 # intact and repeats one of its lines, which is the shape the doubled bootstraps
 # under `panel/` arrived in - a second `install_path()` that a count of the whole
 # block reads as compliant. The payload IS the anchor, so nothing here spells the
 # preamble a second time.
 ("path_preamble_violations", S + "_fmt.py", "after", INSTALL, INSTALL, OUT, "pp1"),
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
 # TWO CONSTRAINTS, and this row lost the first one silently. The target must be
 # a file the rule APPLIES to (400+ lines) AND one carrying EXACTLY the two
 # markers it needs, because `drop` removes ONE line: a file with fourteen
 # markers still has thirteen afterwards and never violates.
 #
 # It named `panel/_panel_composition.py` until F91 moved `_proposals_view` out
 # of it. At 344 lines the rule had nothing to say there any more, so the
 # mutation proved nothing and this gate reported STAYED GREEN while the lint
 # itself was fine - one change making an unrelated gate stop asserting, with no
 # test going red anywhere. A row naming a file NEAR the threshold is a row with
 # an expiry date, which is why the replacement is 253 lines clear of it rather
 # than the two closer candidates.
 ("navigability_violations", "plugins/audit/hooks/require-plan.py", "drop",
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
 # F110: the pairing nothing checked. A route table in Python and a set of
 # controls in JavaScript, each half tested on its own, and `POST
 # /api/gate-events/prune` shipping for a release with no control naming it. The
 # mutation adds a route to the real dispatcher, which is the shape the defect
 # arrived in - an endpoint written first, its control "not yet".
 ("panel_route_violations", S + "panel/panel-server.py", "after",
  "                self._json(200, discover(project)); return\n",
  '            if path == "/api/probe-uncalled":\n'
  "                self._json(200, {}); return\n", DEP, "pr1"),
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
 # TWO ROWS FOR THE SCREENSHOT RULE, because it now answers two questions through
 # two code paths and only one of them was ever proved. This one is the SOURCE side
 # (F85): a picture whose UI has moved under it, which no version stamp can see. A
 # `ui/` COMMENT is appended rather than a rule changed, because the mutation only
 # has to move bytes - a behavioural edit would redden the report's own pins too and
 # make the verdict about the wrong thing. The marker line is unique in its file,
 # which is what the anchor needs.
 ("screenshot_capture_drift",
  "plugins/audit/scripts/ui/report-css/empty-state.css", "suffix",
  r"^/\* ---- load reveal", "\n/* a byte moved under a committed picture */",
  REF, "sc1"),
 # ...and the SIDECAR side. RENAMES ONE ENTRY IN IT, which is the narrowest
 # mutation that reaches this rule. Two wider ones were tried and rejected: the
 # recorded VERSION is not a unique anchor (one line per image, so c2 fails), and
 # bumping plugin.json instead reddens the whole version-pin family - measured, it
 # named p1/p3/p4/p7 and not sc1, which is the "red through the wrong case" verdict
 # this table exists to avoid. An image NAME is unique in the sidecar and does not
 # change when the pictures are re-captured, and renaming one leaves the picture
 # unrecorded and the record picture-less at once.
 ("screenshot_capture_drift", "docs/screenshots/captured-at.json", "sub",
  r'"areas\.png"', (r'"areas\.png"', '"areas-renamed.png"'), REF, "sc1"), # The hierarchy check, on the tier that can be broken without a network and
 # without a cache. `_loop_from` walking UP the declared parent edges is the
 # whole of tier A past the self-parent case, and a walk that never finds a loop
 # is the SILENT failure: every plan validates, and the item that hangs under its
 # own child is created exactly as ADO already accepts it. `hp2` is the case,
 # and it is the one modelled on the pair that exists on a live board.
 ("hierarchy_violations", S + "manifest/_ado_parent.py", "replace",
  "    chain, seen, cursor = [], set(), start",
  "    return None\n    chain, seen, cursor = [], set(), start", ADP, "hp2"),
 # THE BOARD STANDARD, on the rule that needs neither a network nor a fixture
 # board to break. `requireParent` is the one conformance rule whose whole
 # implementation is a single branch, so switching the branch off is the minimal
 # mutation that stops the check checking - and `ac14` is the case that says an
 # item with nowhere to hang is refused, which is the finding this rule exists
 # to produce. Nothing upstream of the module can break it: the standard is a
 # config block and the item is a dict the connector builds.
 # The anchor is the FIRST line of a two-line condition, not the whole condition:
 # F120 scoped this rule by kind, so the branch grew a second clause. A row that
 # pinned the old one-line spelling went to "anchor occurs 0 time(s)" the moment
 # that landed - which is the coverage rule doing its job, and the reason the
 # payload opens the parenthesis it no longer closes on this line.
 ("conformance_violations", S + "manifest/_ado_conventions.py", "replace",
  '    if (conventions.get("requireParent") is True',
  "    if (False",
  ADC, "ac14"),
 # The provenance door, and it is a SEPARATE lint rather than a caller of the one
 # above: `_manifest_ado` asks it at authoring time, so a manifest can be told its
 # own board would refuse every item the connector creates. Emptying the delegation
 # is the mutation because the door IS the delegation - everything above it is
 # narrowing - and `ac36` is the case that reads the warning back out of
 # `check_ado_meta`, which is where a caller meets this.
 ("provenance_tag_violations", S + "manifest/_ado_conventions.py", "replace",
  "    return _tag_violations(split_tags(tag), vocabulary)", "    return []",
  ADC, "ac36"),
 # The config vocabulary. Three rows for the tree-bound half, because it has three
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
  "set(known) - published - set(exempt)", "set()", CFG, "cv4"),
 # F119, AND THE ONLY ROW HERE THAT BREAKS A TEST RATHER THAN A SCRIPT, because a
 # test IS what this guard watches: the thing `scratch_debris()` guards is a suite
 # leaving its fixture behind in the directory it was run from. The payload is the
 # defect verbatim - a `mkdtemp` with no cleanup, inside a suite that otherwise
 # passes - and `x4` is the case that runs a real suite from this tree and reads
 # what it left. It is anchored on `def _selftest():` rather than on an import, so
 # the leak happens when the suite RUNS: a payload at module scope would leak while
 # the file was merely imported, which is not the shape being proven.
 ("scratch_debris", "plugins/audit/tests/test__cli_fmt.py", "after",
  "def _selftest():\n",
  '    import tempfile as _leak\n    _leak.mkdtemp(prefix="probe-leak-")\n',
  "tools/sweep-selftests.py", "x4"),

 # --- F139: one fact with two homes, and the rule that compares them ----------
 # THE MUTATED FILE IS THE HOME, not the guard: `_harness.remove_tree()` is where
 # the read-only-object fact lives, and the sweep runner keeps a copy because a
 # runner may not import a file it is one of the runners OF. The thing this rule
 # guards is the two staying identical, so the mutation edits ONE of them and
 # changes nothing else - a permission constant, which is exactly the shape a
 # forgotten carry-across arrives in. `rm1` is the case that reads both files.
 ("removal_helper_drift", "plugins/audit/tests/_harness.py", "replace",
  "                os.chmod(os.path.join(base, name), 0o700)",
  "                os.chmod(os.path.join(base, name), 0o755)",
  "tools/sweep-selftests.py", "rm1"),
 # --- F155: the callers, and the rule that stops the next one -----------------
 # THE MUTATED FILE IS A CALLER, not the guard: the drift row above watches the two
 # copies of the helper agreeing, and this one watches a tool actually USING it. The
 # payload is the defect verbatim - the ordinary removal with `ignore_errors=True`,
 # which is how every one of these sites was spelled - and it is planted in the tool
 # that builds the most thoroughly written repository in the tree, so the finding is
 # the real shape rather than a fixture's. `s16` is the case that reads every tool.
 #
 # THE SITE IS THE JOURNAL RESET AND NOT ONE OF THE TWO FIXTURE ROOTS, because it is
 # the one that appears once: both roots are removed by identically spelled lines,
 # and an anchor matching two places is a mutation nobody can predict the reach of.
 ("unsafe_removal_violations", "tools/check-git-pipeline.py", "replace",
  '    remove_tree(os.path.join(fx["root"], "docs", "audit", "journal"))',
  '    shutil.rmtree(os.path.join(fx["root"], "docs", "audit", "journal"),\n'
  '                  ignore_errors=True)',
  "tools/_suite.py", "s16"),
 # THE READ AND THE TRIM DO NOT HAVE TO SHARE A LINE, which is the half of this
 # rule the defect it is named for actually needed: the bug type is read on one
 # line and its whitespace decided two lines down. Stop looking past the
 # expression and the repaired module reads as normalising NOTHING, so the rule
 # goes quiet about the very copy it exists to catch. `ck3` is the pre-fix pair
 # reconstructed as a fixture.
 ("config_read_violations", S + "_deps.py", "replace",
  "            normalisers = normalisers | _name_normalisers(scope, local)",
  "            normalisers = normalisers", DEP, "ck3"),
 # --- F166: the two lints the name-shaped derivation could not see ------------
 # THE MUTATED FILE IS A TOOL, not the guard: what `hand_rolled_runners()` watches
 # is a tool running its own suite instead of handing its cases to the shared
 # runner, and the payload is that defect at its smallest - a `_selftest` whose
 # body is no longer the delegation. `where.py` is the target because its
 # delegation appears exactly once in the file, so the anchor cannot reach two
 # places, and because nothing else in the tree reads it while this row runs.
 ("hand_rolled_runners", "tools/where.py", "replace",
  "    return run(_cases)", "    return 0", "tools/_suite.py", "s5"),
 # ...and the second lint the corrected derivation turned up, which had been
 # load-bearing and unproven since it was written. The payload is the defect
 # verbatim: the constant `_panel_paths.py` already declares, planted in a module
 # that never reads it, which is exactly the shape the panel server shipped.
 ("redundant_constants", S + "_fmt.py", "after", INSTALL,
  '\nCONFIG_REL = ".claude/audit.config.json"\n', OUT, "rc7"),
 # THE MERGED-BLOCK ACCESSOR. A config block that arrives through a `<root>_cfg`
 # call puts no key on the line, so without this branch every read taken off it
 # resolves to nothing and the module holding them is absent from the key's reader
 # list entirely - which is how F168 served a padded date past a rule added the
 # same round to catch one key read two ways. `ck18` is that pair as a fixture.
 ("config_read_violations", S + "_deps.py", "replace",
  "    block = _block_accessor(node, roots)",
  "    block = None", DEP, "ck18"),
)


# --- the other half of the specification: the guard that stays QUIET ----------
# EVERY ROW ABOVE PROVES A CHECK GOES RED, AND NONE PROVED ONE STAYS QUIET (F55).
# A guard has two halves: it fires on the thing it exists for, and it says nothing
# about legitimate input. Only the first was ever proven here, and the second is
# this repo's repeatedly-shipped failure mode - a guard refused a heredoc that
# CREATED a markdown file because the prose inside it quoted a path to a key file
# (F116). The operation was a write, the target was a document, and the only
# secret-ish thing on the line was a sentence. Nobody had a case for that.
#
# THE MECHANISM IS THE ONE ABOVE, POINTED THE OTHER WAY. A row still mutates one
# file, runs one suite and requires one named case to go red; what changes is WHICH
# file and WHAT the case claims. Here the mutated file is the GUARD, weakened so it
# OVER-fires, and the named case is one asserting a known-good input produces no
# finding. If that case stays green while the guard flags everything it can see,
# the case is asserting nothing - which is exactly what "run it and assert no
# output" does in a tree that is already clean.
#
# So the mutation is chosen to be a NARROWING REMOVED rather than damage: the
# exempted file that stops being exempt, the prose scope that widens to the whole
# document, the comment stripper that stops stripping. Those are the shapes F116
# arrived in, and each one has a legitimate input the suite already names.
#
# A FEW ROWS NAME THE SAME CASE AS THEIR RED TWIN, and that is deliberate rather
# than lazy: a suite's live-tree assertion is the only allow corpus some of these
# rules have, and a row here proves that assertion is sensitive in BOTH directions
# instead of only the one it was written for.
ALLOW = (
 # `_output.py` is exempt from this rule BY NAME, and `pp10`'s fixture is the
 # ordinary compliant file. Counting one preamble too many is the smallest
 # plausible off-by-one, and it convicts every correctly-bootstrapped file.
 ("path_preamble_violations", S + "_output.py", "replace",
  "        found = src.count(PATH_PREAMBLE)",
  "        found = src.count(PATH_PREAMBLE) + 1", OUT, "pp10"),
 # F94's NARROWING, REMOVED. The repeat check compares whole LINES of the preamble
 # and skips the blank ones. Stop skipping them and a blank line becomes a preamble
 # line, so every file holding one more than once - which is every file - reads as a
 # partial repeat. `pp10` is the ordinary compliant fixture, and it is what stops
 # the F94 repair over-firing on the whole tree it was added to clean.
 ("path_preamble_violations", S + "_output.py", "replace",
  "    wanted = set(line for line in PATH_PREAMBLE.splitlines() if line.strip())",
  "    wanted = set(PATH_PREAMBLE.splitlines())", OUT, "pp10"),
 # --- F149: the narrowing that lives in two statements ------------------------
 # THE THIRD NARROWING IN THAT REPAIR, and the one no single-line row can reach.
 # The repeat check is whole-line equality twice over: once where a source line is
 # matched against the block, and once in the key the seen-set remembers. Widen
 # only the match and the seen-set still holds the raw source line, so a MENTION
 # and a real preamble line never collide and the rule goes on passing - a row
 # that changed one of them would report a guard proven while proving nothing.
 # So the anchor is a block, which `replace` has always allowed and the kind note
 # above now says out loud.
 #
 # WEAKENED, IT CONVICTS TWO CORRECT FILES, measured rather than assumed:
 # `_loader.py` and `panel-server.py` each spell `_output.install_path()` inside a
 # longer line - a docstring sentence and a commented one-liner - and `pp13`'s
 # fixture is a copy of exactly that arrangement.
 ("path_preamble_violations", S + "_output.py", "replace",
  "        if line not in wanted:\n"
  "            continue\n"
  "        if line in seen:\n"
  "            repeats.append(number)\n"
  "        else:\n"
  "            seen.add(line)\n",
  "        hit = sorted(w for w in wanted if w in line)\n"
  "        if not hit:\n"
  "            continue\n"
  "        if hit[0] in seen:\n"
  "            repeats.append(number)\n"
  "        else:\n"
  "            seen.add(hit[0])\n", OUT, "pp13"),
 # THE PUREST F116 SHAPE IN THE TREE. The rule bans `__file__`, and the pinned
 # preamble is the one legitimate occurrence of it - which is why the preamble is
 # cut out before the scan. Stop cutting it and every compliant file reads as a
 # violation, quoting the very bytes the house rule tells people to paste.
 ("depth_sensitive_paths", S + "_output.py", "replace",
  "            tree = ast.parse(src.replace(PATH_PREAMBLE, blanked), filename=rel)",
  "            tree = ast.parse(src, filename=rel)", OUT, "ds5"),
 # The rule is the annotation, not the parameter. Drop the `is not None` and a
 # default argument - `ga5`'s fixture, and most signatures in the tree - is
 # reported as annotated.
 ("house_style_violations", S + "_output.py", "replace",
  "        elif isinstance(node, ast.arg) and node.annotation is not None:",
  "        elif isinstance(node, ast.arg):", OUT, "ga5"),
 # An importable helper has no entry block and its importer holds the guard. Take
 # that clause away and every module in the tree owes a `safe_stdio()` it must not
 # have. `f1` is the live-tree assertion, which is this rule's allow corpus.
 ("entries_missing_guard", S + "_output.py", "replace",
  "            if not entries:", "            if False:", OUT, "f1"),
 # The docstring filter, removed - which is the bug this classifier actually
 # shipped: a migrated file DESCRIBING the contract came back classified as
 # carrying a suite, so the file that did the right thing was the defect.
 ("selftest_coverage", S + "_output.py", "replace",
  "             and id(node) not in prose]", "             ]", OUT, "sc2b"),
 # Two rows, one per escape hatch the house rule promises. A number that carries
 # the command re-deriving it is legal; blind the basis reader and the repair
 # itself becomes the finding.
 ("prose_number_claims", S + "_output.py", "replace",
  '    for chunk in _backtick_chunks(line) + _backtick_chunks(following or ""):',
  "    for chunk in []:", OUT, "pn5"),
 # ...and history is legal too. A decision record that says what a count was on a
 # given day is the second hatch, and this is the row that fails if it closes.
 ("prose_number_claims", S + "_output.py", "replace",
  "        if _looks_historical(scope):", "        if False:", OUT, "pn4"),
 # A file may import a sibling in a LOWER layer. Flag every edge and the legal
 # downward import - the shape most of this tree is built from - is a violation.
 ("layer_violations", S + "_deps.py", "replace",
  "        if not (li > lj):", "        if True:", DEP, "w3"),
 # EVERY migrated file names its test file in prose, twice. Swap the AST edge
 # reader for the string-literal one and the whole tree reaches into `tests/`,
 # which is the looser scan the docstring says it refuses to be.
 ("tests_import_violations", S + "_deps.py", "replace",
  "            for name in sorted(set(_imported_sibling_names(tree, test_names, None))):",
  "            for name in sorted(set(_py_literal_basenames(tree)) & test_names):",
  DEP, "tb4"),
 # A byte-for-byte comparison that stops honouring the fence's trailing newline
 # reports drift on a guide that is exactly right, which is the direction a
 # regenerate-and-commit instruction cannot fix.
 ("map_drift", S + "_deps.py", "replace",
  "    if block != expected:", "    if block != expected.rstrip():", DEP, "g1"),
 # The excuse pattern, widened to the word it is about. The guide has to STATE the
 # hooks rule to satisfy the other half of this lint, so a pattern that matches the
 # subject convicts the document for complying.
 ("hooks_rule_drift", S + "_deps.py", "replace",
  "    hit = _GUIDE_HOOKS_EXCUSE.search(text)",
  '    hit = re.search("hooks", text)', DEP, "g0"),
 # Two markers is the floor the house rule sets, so a file carrying exactly two is
 # the legitimate minimum. Raise the bar by one and the rule convicts the shape it
 # asks for.
 ("navigability_violations", S + "_deps.py", "replace",
  "        if headers < 2:", "        if headers < 3:", DEP, "n6"),
 # An extension with no marker syntax on record is SKIPPED rather than guessed at,
 # and that property is argued at the table. Guess anyway - hand every file the
 # first syntax in it - and a document markup file is graded by a comment shape it
 # cannot have.
 ("ui_navigability_violations", S + "_deps.py", "replace",
  "            if name.endswith(ext):", "            if True:", DEP, "u7"),
 # The same arithmetic one surface further, and a separate row because `tools/` is
 # a separate corpus: a file carrying exactly as many markers as the rule asks for
 # is the legitimate case, and one more than it asks for is nobody's.
 ("tool_navigability_violations", S + "_deps.py", "replace",
  "        want = max(2, -(-len(lines) // _NAV_MIN_LINES))",
  "        want = max(2, -(-len(lines) // _NAV_MIN_LINES)) + 1", DEP, "tn4"),
 # F116 ITSELF, in the one lint here that already meets it: a needle appearing
 # only in a COMMENT is a mention, not a copy. Stop stripping comments and the
 # scout convicts a file for explaining the convention it follows.
 #
 # `sc7` AND NOT `sc11`, measured rather than assumed: `sc11` calls `_code_only`
 # directly, so it judges the stripper and stays green while the LINT is the thing
 # over-firing. `sc7` runs the fixture through `shared_concern_violations`, which
 # is where the allow claim lives.
 ("shared_concern_violations", S + "_deps.py", "replace",
  "                body = _code_only(fh.read())",
  "                body = fh.read()", DEP, "sc7"),
 # The two routes the BROWSER asks for itself - the document and its tab icon -
 # are skipped structurally, because nothing on a page fetches the page. Remove
 # that narrowing and the lint convicts a panel for being a web page: `pr4`'s
 # fixture serves exactly those two beside one route its control really calls.
 ("panel_route_violations", S + "_deps.py", "replace",
  '_PANEL_BROWSER_ROUTES = frozenset(("/", "/favicon.ico"))',
  "_PANEL_BROWSER_ROUTES = frozenset()", DEP, "pr4"),
 # A reach is judged absolute; the relative spelling is the REPAIR. Drop the test
 # and the rule forbids its own remedy, which is the failure that gets a lint
 # switched off rather than fixed.
 ("absolute_reach_violations", S + "_refs.py", "replace",
  '                        if spec.startswith("/") and spec not in allowed:',
  "                        if spec not in allowed:", REF, "ar4"),
 # The region scope, at the format each rule's own allow case is written in. A
 # document may QUOTE the retired sweep while telling a reader to run the current
 # one - a warning against it is the commonest way - and only the runnable region
 # separates the two.
 ("sweep_glob_drift", S + "_refs.py", "replace",
  "        return _yaml_run_scripts(text), None",
  "        return text, None", REF, "s5"),
 # ...and the same narrowing for the list rule: prose ABOUT the sweep must not
 # drag a document under it, or half the tree owes an entry for mentioning a
 # command.
 ("sweep_doc_drift", S + "_refs.py", "replace",
  '        return "\\n".join(f.group(1) for f in _FENCE_RE.finditer(text)), None',
  "        return text, None", REF, "s19"),
 # Another host, a mail link and an in-page anchor are not claims about a file in
 # this tree. Stop excluding them and every outbound link in every document is a
 # missing file.
 ("doc_link_drift", S + "_refs.py", "replace",
  '        if "://" in written or written.startswith("mailto:"):',
  "        if False:", REF, "dl11"),
 # The fence scope again, in the rule that spares the changelog's historical URL.
 # Read the whole document and a quotation of a dead link becomes a published
 # fetch instruction.
 #
 # THE FENCE PATTERN IS SWAPPED FOR A WHOLE-TEXT ONE, and widening the INNER loop
 # was tried first and proved nothing: the document this row is about carries no
 # fence at all, so the outer loop never ran and `p11` stayed green over a rule
 # that had stopped scoping anything. The over-fire has to reach a document with
 # nothing fenced in it, which is precisely the document the scope exists for.
 ("raw_url_pin_drift", S + "_refs.py", "replace",
  "    for fence in _FENCE_RE.finditer(text):",
  '    for fence in re.finditer(r"(?s)\\A(.*)\\Z", text):', REF, "p11"),
 # A page stamped with the current release is the whole point of the rule. Compare
 # nothing and every committed page is stale, including the one a release just
 # re-rendered.
 ("artifact_version_drift", S + "_refs.py", "replace",
  "            if stamp != version:", "            if True:", REF, "av5"),
 # ...and the same for the pictures: a sidecar that agrees about the bytes, the
 # version and the sources is the clean state, so a comparison that always
 # disagrees demands a re-capture that cannot help.
 ("screenshot_capture_drift", S + "_refs.py", "replace",
  '        if entry.get("sha256") != digest:', "        if True:", REF, "sc3"),
 # A tool may name itself, a hook and a test file. Ask the wrong set and all three
 # legitimate spellings are reported as references to files that are gone.
 ("tool_basename_drift", S + "_refs.py", "replace",
  "                if name not in known:", "                if name not in fixtures:",
  REF, "tb5"),
 # The README row is where a declared flag has to appear. Read no row at all and
 # every command that documents its flags correctly is reported for omitting them.
 ("command_flag_drift", S + "_refs.py", "replace",
  "        row_flags = set(_FLAG.findall(rows[cmd]))",
  "        row_flags = set()", REF, "cf1"),
 # The published vocabulary, minus one key the plugin really does publish. `cv1`
 # is the live-tree assertion over three surfaces written for three readers, and
 # this is what makes it a claim rather than a habit.
 ("config_vocab_drift", S + "config/_config_rules.py", "replace",
  '    return set(schema["properties"]), None',
  '    return set(schema["properties"]) - set(["ui"]), None', CFG, "cv1"),
 # A surface publishing exactly the vocabulary is SILENT. Stop subtracting what it
 # published and the agreement itself is the finding - the same line the red row
 # empties, mutated the other way.
 ("root_vocab_drift", S + "config/_config_rules.py", "replace",
  "set(known) - published - set(exempt)", "set(known) - set(exempt)", CFG, "cv3"),
 # The docstring beside this comparison argues the case out loud: a checker that
 # refuses a deliberate, legal arrangement gets switched off. A ladder whose
 # parent outranks its child is that arrangement, and `!=` convicts it.
 ("hierarchy_violations", S + "manifest/_ado_parent.py", "replace",
  "    if parent_rank < child_rank:", "    if parent_rank != child_rank:",
  ADP, "hp14"),
 # THE TYPE SCOPING, REMOVED - and the module argues this one out loud: "a checker
 # that demanded acceptance criteria on a task would be refused so often it would
 # be switched off". A board scopes required fields BY work item type, so flatten
 # the lookup and every Task owes a story's acceptance criteria. `ac5` is the case
 # that says the story's rule does not fire on a task, and it is the only shape of
 # over-fire this rule can have that a clean tree would not already show.
 ("conformance_violations", S + "manifest/_ado_conventions.py", "replace",
  "        for name in (required.get(wit) or []):",
  "        for name in [n for names in required.values() for n in names]:",
  ADC, "ac5"),
 # THE PUBLISHED ASYMMETRY, AND IT IS A COMPATIBILITY PROMISE RATHER THAN A
 # PREFERENCE. `{"*": []}` admits any bare tag - the schema, the connector doc and
 # this repo's own example all spell a free-form board that way - so reading the
 # empty list as "forbids every bare tag" turns a manifest somebody already wrote
 # into a board that refuses the connector's own provenance tag. The mutation is
 # that reading, in the shared tag rule both lints reach through, and the named
 # case is on the PROVENANCE path: it asks whether a board admits the tag this
 # connector writes, over a vocabulary that has an empty wildcard in it.
 ("provenance_tag_violations", S + "manifest/_ado_conventions.py", "replace",
  "        elif bare_allowed and tag not in bare_allowed:",
  "        elif tag not in (bare_allowed or []):",
  ADC, substr("no contradiction warning for free-form vocabulary")),
 # THE PUREST F116 SHAPE THIS GUARD HAS: the checker plants a file in the scratch
 # directory so it can tell a DELETION apart from a clean run, and that file is the
 # one thing in there it must not report. Stop excluding it and every suite in the
 # tree - all of them clean - is convicted of having dirtied its directory by the
 # evidence the checker left. `x2d` is the case that asserts a child which touches
 # nothing produces no finding, and it is the only one written to fail here.
 # THE ANCHOR REMOVED. A configuration path must start at a top-level property of
 # one of the two schemas; without it any dict carrying a `types` key is a config
 # block, and a BOARD's answer to a probe is convicted as a configured value in a
 # file that reads no configuration on that line at all. `ck7` is the fixture.
 ("config_read_violations", S + "_deps.py", "replace",
  "        return ((key,) if key in roots else None), normalisers",
  "        return (key,), normalisers", DEP, "ck7"),
 ("scratch_debris", "tools/sweep-selftests.py", "replace",
  "    strays = [name for name in left if name != sentinel]",
  "    strays = list(left)",
  "tools/sweep-selftests.py", substr("touches nothing")),
 # --- F139: the quiet half of the copy-comparison -----------------------------
 # THE NARROWING IS THE DOCSTRING, and it is the F116 shape again. The two copies
 # of `remove_tree` are REQUIRED to describe themselves differently - one carries
 # the measurement that chose the fallback order, the other carries the pointer
 # and the reason a copy exists at all - so the comparison drops the docstring and
 # reads the statements. Stop dropping it and the rule convicts the arrangement it
 # was written to police, which is how a comparison gets deleted rather than
 # fixed. `rm2` is the case that asserts a docstring-only difference is not drift.
 ("removal_helper_drift", "tools/sweep-selftests.py", "replace",
  "            body = body[1:]", "            body = list(body)",
  "tools/sweep-selftests.py", "rm2"),
 # --- F155: the half that decides who the rule is ALLOWED to leave alone ------
 # THE NARROWING IS THE OBJECT VERB, and it is the difference between a rule and a
 # demand. A bare repository initialisation writes no object, so there is nothing
 # read-only under it and the ordinary removal is correct; one staged file is enough
 # to put a read-only loose object there. Remove this half and the rule fires on any
 # tool that so much as initialises a repository - which convicts the demo capture,
 # whose fixture does exactly that and never writes to it, and buys a careful removal
 # with no failure behind it. `s14` is the pair written for this mutation and nothing
 # else: it asserts that something is NOT reported, so it reads as vacuous and passes
 # on every version except the over-eager one.
 ("unsafe_removal_violations", "tools/_suite.py", "replace",
  "    if not any(marker in words for marker in OBJECT_MARKERS):",
  "    if False:", "tools/_suite.py", "s14"),
 # --- F166: the quiet half for the two lints nothing used to derive -----------
 # THE NARROWING IS THE IMPORT LINE. A tool's `_selftest` is two statements, and
 # only one of them is the delegation; the other is what makes the runner
 # reachable. Stop admitting it and every tool in the tree is convicted of running
 # its own suite - by the very line the rule tells them to write. `s6` is the case
 # written for exactly that: it asserts a delegating body is NOT reported, so it
 # reads as vacuous and passes on every version except the over-eager one.
 ("hand_rolled_runners", "tools/_suite.py", "replace",
  '    return isinstance(stmt, ast.ImportFrom) and stmt.module == "_suite"',
  "    return False", "tools/_suite.py", "s6"),
 # THE NARROWING IS "NEVER READ HERE", and it is the difference between a lint
 # whose remedy is always DELETION and one whose remedy is sometimes a refactor
 # with call sites to move. Remove it and every duplicated constant is reported,
 # read or not - which is a demand with no failure behind it and the shape that
 # teaches a reader to skip the lint. `rc3` is the pair: it asserts that a
 # duplicate which IS read stays silent.
 ("redundant_constants", S + "_output.py", "replace",
  "                if const_name not in unread.get(name, ()):",
  "                if False:", OUT, "rc3"), # THE PREFIX MUST BE A TOP-LEVEL PROPERTY, not merely a property name. `pricing`
 # is in the vocabulary as a NESTED key, so an accessor test that took any name
 # invents a path in a file that configures nothing on that line. `ck21` is the
 # fixture.
 ("config_read_violations", S + "_deps.py", "replace",
  "    return block if block in roots else None",
  "    return block or None", DEP, "ck21"),
)


# WHERE AN ALLOW CASE IS NOT MEANINGFUL, said here rather than left as a gap. The
# entry names the lint and the reason, and `allow_coverage()` refuses a lint that
# has neither a row nor a line in this table - the same shape `coverage()` refuses
# a lint with no red row, because an exemption nobody can read is a lint quietly
# dropped.
ALLOW_EXEMPT = (
 ("doc_prose_numbers",
  "it reads the shape through `prose_claims_in`, which the two prose_number_claims "
  "rows above already mutate - a row here would re-prove one narrowing through a "
  "second front door and report it as a second gate. Its own half is the DOCUMENT "
  "SET, derived off `.gitignore`; over-firing there means reading a file this repo "
  "does not keep, and no case in its suite asserts an ignored document is left "
  "alone, so there is nothing here to name yet. Revisit when one exists."),)

_MIN_ALLOW_REASON = 80    # a reason short enough to be a label is not a reason


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
# WHAT THE STRUCTURAL ARM IS ALLOWED TO LEAVE OUT, with the reason, and checked in
# both directions below. A row here says "this walks the tree with no argument and
# is still not a gate", which is a claim a reader can disagree with; a row naming a
# function the shapes above already derive, or one the arm no longer reaches, does
# nothing and is reported exactly as a violation is. Kept short on purpose: a table
# that grows faster than the arm finds things is the arm being turned off.
NOT_A_GATE = (
 ("script_files",
  "the WALK ITSELF. It answers which files are under `scripts/`, and a list of "
  "files is not a list of findings - every lint above it asks this for the tree it "
  "judges, so a row proving it goes red would be proving that the repository has "
  "files in it. What makes it a candidate is the shape it shares with a lint; what "
  "makes it not one is that nothing it returns is a verdict."),
 ("sweep_files",
  "the sweep's DISCOVERY, for the same reason one file over: it answers which files "
  "must carry a suite at all, and the verdict on each of them is `grade()`'s - which "
  "is a pure function of an exit code and some text, has no walk in it, and is "
  "reached through `scratch_debris` and the sweep's own cases rather than through "
  "this name."),
)

_MIN_NOT_A_GATE_REASON = 80   # a reason short enough to be a label is not a reason


def _call_name(node):
    """The attribute or bare name a `Call` invokes, or None for anything else."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def walks_the_tree(node):
    """True for a function that judges the REPOSITORY rather than a caller's input.

    The property, not the name: no required argument, and a call to one of the
    shared walks somewhere inside. `_TREE_WALKS` says why both halves are needed.
    """
    args = node.args
    if getattr(args, "posonlyargs", None) or args.vararg or args.kwonlyargs:
        return False
    if len(args.args) != len(args.defaults):
        return False
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _call_name(child) in _TREE_WALKS:
            return True
    return False


def _gate_sources(script_dir=None, repo=None):
    """[(path, tree)] for every file that holds a guard and could be parsed."""
    root = script_dir or _output.SCRIPTS_DIR
    repo_root = repo or REPO
    paths = ([os.path.join(root, rel) for rel in _GATE_MODULES]
             + [os.path.join(repo_root, rel.replace("/", os.sep))
                for rel in _GATE_OUTSIDE])
    out = []
    for path in paths:
        try:
            out.append((path, ast.parse(io.open(path, encoding="utf-8").read())))
        except (OSError, SyntaxError):
            continue
    return out


def gate_names(script_dir=None, repo=None):
    """Every load-bearing lint in the files that hold one, by name AND by shape.

    TWO ROOTS, because the guards are in two places: `_GATE_MODULES` under
    `scripts/`, and `_GATE_OUTSIDE` repo-relative. A version that read only the
    first derived a set that both coverage rules below then compared against - so
    a guard living outside the plugin was invisible to the rule that asks whether
    it is proven AND to the rule that asks whether its row still means anything.

    AND TWO ARMS, because a name is a convention and a convention is what F166 fell
    through. A lint whose name ends in none of the shapes and sits in no list was
    invisible to BOTH coverage rules at once - which is the same silence one level
    up: `coverage()` cannot report a lint it never derives, so the table went on
    looking complete. `walks_the_tree()` reaches those by what they DO, and
    `NOT_A_GATE` is where a walk that is not a verdict says so out loud.
    """
    found = []
    excused = set(name for name, _why in NOT_A_GATE)
    for _path, tree in _gate_sources(script_dir, repo):
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            if node.name.endswith(_GATE_SHAPES) or node.name in _GATE_NAMED:
                found.append(node.name)
            elif walks_the_tree(node) and node.name not in excused:
                found.append(node.name)
    return sorted(set(found))


def not_a_gate_problems(script_dir=None, repo=None, table=None):
    """[(name, problem)] for every row that has stopped excusing anything.

    THREE WAYS A ROW STOPS DESCRIBING THE SYSTEM, and the third is the one a
    presence check cannot see: a row for a function the shapes ALREADY derive is not
    an exemption at all, it is a sentence about a state that has passed, and it
    stays green forever while quietly claiming to have silenced something.

    Takes the table rather than only reading `NOT_A_GATE`, for the reason
    `compare()` in `gate-parity.py` does: showing that each direction is really
    checked needs a row planted on purpose, and planting one in the live table would
    be a case that edits the thing it is asserting about.
    """
    table = NOT_A_GATE if table is None else table
    reached = set()
    named = set()
    for _path, tree in _gate_sources(script_dir, repo):
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            if node.name.endswith(_GATE_SHAPES) or node.name in _GATE_NAMED:
                named.add(node.name)
            elif walks_the_tree(node):
                reached.add(node.name)
    out = []
    for name, why in table:
        if name in named:
            out.append((name, "is already derived by name, so this row silences "
                              "nothing and can never be wrong"))
        elif name not in reached:
            out.append((name, "walks no tree in any file that holds a guard any "
                              "more, so the row excuses a shape nothing has"))
        elif not isinstance(why, str) or len(why.strip()) < _MIN_NOT_A_GATE_REASON:
            out.append((name, "carries no reason a reader could disagree with"))
    return out


def coverage(script_dir=None, repo=None):
    """Lints the table does not prove. Empty, or the table has stopped covering."""
    named = set(row[0] for row in TABLE)
    return [n for n in gate_names(script_dir, repo) if n not in named]


def stale_rows(rows, script_dir=None, repo=None):
    """The lints `rows` names that nothing in the tree derives any more.

    THE OTHER DIRECTION OF `coverage()`, AND THE ONE A SINGLE-DIRECTION TABLE
    CANNOT SEE. `coverage()` catches a lint with no row. Nothing caught a ROW
    naming a lint that has been deleted or renamed - and such a row does not go
    quiet: its anchor may still be in the file, so the mutation still reddens the
    suite, the named case still fails, and the row is counted as a gate proven
    while proving a rule that no longer exists. A table that only ever grows stops
    describing the system and starts recording its own history, which is exactly
    what `check-committed-pii.py` reports a dead BASELINE entry for.

    Takes the rows rather than reading TABLE, so each direction's summary names
    its own dead rows and a case can hand it a table with one planted in it.
    """
    live = set(gate_names(script_dir, repo))
    return sorted(set(row[0] for row in rows if row[0] not in live))


def allow_coverage(script_dir=None, repo=None):
    """Lints with no ALLOW row and no reason recorded for going without one.

    THE SAME RULE AS `coverage()`, APPLIED TO THE OTHER HALF. A lint added later
    arrives here unproven in the quiet direction, and the only two answers this
    accepts are a row or a sentence saying why a row would prove nothing - because
    "nobody got round to it" and "an allow case is not meaningful here" are
    different states, and a bare gap spells them the same way.
    """
    named = set(row[0] for row in ALLOW) | set(n for n, _why in ALLOW_EXEMPT)
    return [n for n in gate_names(script_dir, repo) if n not in named]


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
# ONE SCRATCH DIRECTORY PER ROW, AND THE VERDICT COMES BACK THROUGH IT.
# `redfirst.sh` writes the gate's output to `redfirst-gate.log` under the temp root
# and this file read it back from the SYSTEM temp root by name - so two runs on one
# machine crossed, and the one that read second attributed the other's failing cases
# to its own mutation. That is the same defect `verify.sh` was repaired for, and the
# rule that now forbids it lives in `gate-parity.scratch_isolation()`.
#
# THE REPAIR IS TO MOVE THE ROOT, NOT THE NAME. Pointing the child's temp root at a
# per-run directory makes the fixed basename unique without `redfirst.sh` having to
# emit the path it chose - which would be a contract change to the one script here
# that mutates the working tree. It also sweeps up anything the mutated suite leaks,
# for free, which is the same trick `sweep-selftests.py` plays on every suite it runs.
LOG_BASENAME = "redfirst-gate.log"

# All three, because the shell reads the first and `tempfile` reads the other two on
# Windows - and a variable left unpinned is a lookup that quietly finds the shared
# directory again. Same reason `sweep-selftests.py` pins more than one.
_TEMP_VARS = ("TMPDIR", "TMP", "TEMP")


def redfirst_env(scratch, base=None):
    """`base` (default the real environment) with every temp root set to `scratch`."""
    env = dict(os.environ if base is None else base)
    for name in _TEMP_VARS:
        env[name] = scratch
    return env


def gate_log_path(scratch):
    """Where `redfirst.sh` writes the gate output, given the root it was handed."""
    return os.path.join(scratch, LOG_BASENAME)


def prove(row, repo=None):
    """Mutate, run the suite, restore. Returns a dict; never raises on a red gate."""
    lint, rel, _kind, _anchor, _payload, suite, target = row
    old, new = mutation(row, repo)
    if old is None:
        return {"lint": lint, "verdict": "UNANCHORED", "detail": new, "cases": []}
    scratch = tempfile.mkdtemp(prefix="prove-gates-")
    try:
        proc = subprocess.run(
            ["sh", "tools/redfirst.sh", rel, "--replace", old, new, "--",
             sys.executable, suite, "--selftest"],
            cwd=repo or REPO, env=redfirst_env(scratch),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = proc.stdout.decode("utf-8", "replace")
        try:
            gate = io.open(gate_log_path(scratch), encoding="utf-8",
                           errors="replace").read()
        except OSError:
            gate = ""
    finally:
        # F165, AND THE ANSWER HERE IS THE PLAIN CALL - recorded rather than left
        # for the next reader to work out again, and recorded on what was MEASURED
        # rather than on where this code can run.
        #
        # THE REASON THAT READS WELL AND IS FALSE: this path is reached only by
        # shelling out to `sh`, so a windows-shaped removal would be dead code.
        # Both halves of that are wrong. `redfirst_env()` above points the child's
        # temp roots at THIS directory, so a mutated suite allocates its fixtures
        # inside it - git repositories included, whose loose objects are the
        # read-only files the careful removal exists for - and the shell ships on
        # windows anyway. A premise nobody re-checks is the exemption shape this
        # repo keeps re-finding, so it is not the one written down here.
        #
        # WHAT IS TRUE IS SMALLER AND MEASURABLE: every suite a row names removes
        # its own fixtures, so what a run leaves under here is `redfirst.sh`'s gate
        # log and nothing beside it - no repository, nothing read-only. Re-derive
        # that rather than trusting this line, per suite named in the tables above:
        #
        #   d=$(mktemp -d); TMPDIR=$d TMP=$d TEMP=$d python3 <suite> --selftest
        #   ls -aR "$d"
        #
        # AND THE PREMISE IS ENFORCED AND NOT MERELY RECORDED, which is the
        # difference between this and an exemption in prose.
        # `sweep-selftests.scratch_debris()` fails any suite that leaves anything
        # in the directory it was handed; `_suite.unsafe_removal_violations()`
        # walks `tools/` and convicts THIS file the day it builds a repository and
        # writes an object into one; and `gate-parity`'s ABSENT_BY_DESIGN row for
        # this tool reports itself stale the day a workflow adopts it, which is
        # the half that keeps "it never runs on the windows leg" honest.
        shutil.rmtree(scratch, ignore_errors=True)
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


def render(rows, missing, stale=(), stream=None, claim="gates proven red"):
    """The report for ONE direction's rows. `claim` is what a proven row means.

    Parameterised rather than duplicated: the arithmetic, the coarse notice and the
    missing-row notice are identical for both halves, and the only thing that
    differs is the sentence a reader is owed - "this check goes red when the thing
    it guards breaks" and "this check stays quiet on input that is fine" are two
    claims, and a summary that spelled them the same way would hide which one the
    run just established.
    """
    out = stream if stream is not None else sys.stdout
    bad = [r for r in rows if r["verdict"] not in PROVEN]
    coarse = [r for r in rows if r["verdict"] == COARSE]
    for r in rows:
        out.write("  %-28s %-16s %s\n" % (r["lint"], r["verdict"], r["detail"]))
    out.write("\n")
    for name in missing:
        out.write("  NOT PROVEN AT ALL: %s has no row in the table\n" % (name,))
    for name in stale:
        out.write("  NO SUCH LINT: the row for %s names a rule nothing in the tree "
                  "derives any more, so whatever it just reddened credits "
                  "nothing\n" % (name,))
    for r in coarse:
        out.write("  NAMES NO CASE: %s is proven only by its whole suite going "
                  "red\n" % (r["lint"],))
    out.write("%d of %d %s%s%s\n"
              % (len(rows) - len(bad), len(rows), claim,
                 ("; %d lint(s) missing a row" % len(missing)) if missing else "",
                 ("; %d row(s) naming no lint" % len(stale)) if stale else ""))
    return 1 if (bad or missing or stale) else 0


ALLOW_CLAIM = "guards proven to stay quiet on known-good input"


def main(argv):
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(__doc__.strip() + "\n")
        return 0
    only = None
    for i, a in enumerate(argv):
        if a == "--only" and i + 1 < len(argv):
            only = argv[i + 1]
    # BOTH DIRECTIONS BY DEFAULT, because a guard's specification is two-sided and
    # a run that proved one half would report a number that reads like the whole.
    # `--red` / `--allow` narrow it when only one half is being worked on.
    want_red = "--allow" not in argv
    want_allow = "--red" not in argv
    table = [r for r in TABLE if only is None or only in r[0]]
    allow = [r for r in ALLOW if only is None or only in r[0]]
    if "--list" in argv:
        for label, rows in (("red", table if want_red else []),
                            ("allow", allow if want_allow else [])):
            for row in rows:
                old, new = mutation(row)
                sys.stdout.write("  %-5s %-28s %-40s %s\n"
                                 % (label, row[0], row[1],
                                    "anchored" if old is not None
                                    else "UNANCHORED: %s" % (new,)))
        for name, _why in ALLOW_EXEMPT:
            if want_allow and (only is None or only in name):
                sys.stdout.write("  %-5s %-28s %s\n"
                                 % ("allow", name, "no allow case; reason recorded"))
        return 0
    code = 0
    if want_red:
        sys.stdout.write("proving %d gate(s) go RED; each mutates the tree and "
                         "restores it\n" % (len(table),))
        code |= render([prove(row) for row in table],
                       coverage() if only is None else [],
                       stale_rows(table))
    if want_allow:
        sys.stdout.write("\nproving %d guard(s) stay QUIET; each weakens the GUARD "
                         "so it over-fires, and the named allow case must go red\n"
                         % (len(allow),))
        code |= render([prove(row) for row in allow],
                       allow_coverage() if only is None else [],
                       stale_rows(allow), claim=ALLOW_CLAIM)
    return code


# --- selftest -----------------------------------------------------------------
def _cases(check):
    """Everything that can rot, checked WITHOUT mutating anything."""
    names = gate_names()
    check("c0 the gate set is DERIVED from the three modules by name, so a lint "
          "added later shows up here rather than being quietly unproven "
          "(%d found)" % (len(names),),
          len(names) >= 15 and "house_style_violations" in names)

    check("c0b ...and the derivation reaches the guard that does NOT live in the "
          "plugin, which is the half a single root could not see: a lint held "
          "under tools/ was named by both tables and derived by nothing, so one "
          "coverage rule could never report it absent and the other would have "
          "reported its live row as dead",
          "scratch_debris" in names)

    missing = coverage()
    check("c1 ...and every one of them has a row in the table. This is the case "
          "that fails the day somebody adds a lint and no mutation proves it: "
          "%r" % (missing,),
          missing == [])

    # THE OTHER DIRECTION OF c1, and the one nothing asked. A row naming a lint
    # that has been deleted or renamed does not go quiet: its anchor may still be
    # in the file, so the mutation still reddens the suite and the row is counted
    # as a gate proven while proving a rule that is gone.
    _stale = stale_rows(TABLE)
    check("c1b every row in the table names a lint the tree still derives - a "
          "table that only ever grows stops describing the system and starts "
          "recording its own history, which is the same finding "
          "`check-committed-pii.py` reports for a dead baseline entry: %r"
          % (_stale,),
          _stale == [])
    # THE PAIR, because c1b passes on a version of `stale_rows` that always
    # answers "nothing" - which is precisely the shape it is replacing.
    _planted = ("no_such_lint_violations",) + TABLE[0][1:]
    check("c1c ...and a planted row IS reported while a live one beside it is "
          "not, so c1b is a claim about the table rather than about a function "
          "that cannot fire: %r vs %r"
          % (stale_rows((_planted, TABLE[0])), stale_rows((TABLE[0],))),
          stale_rows((_planted, TABLE[0])) == ["no_such_lint_violations"]
          and stale_rows((TABLE[0],)) == [])

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

    # F149: THE BLOCK ANCHOR, PINNED WHERE IT IS USED. A narrowing that lives in
    # two statements cannot be reached one line at a time, and the answer chosen
    # was a row rather than a column recording that somebody had proven it by
    # hand. Both halves are asserted, because either alone is empty: that at least
    # one row's anchor really does span lines, and that every such anchor still
    # resolves - a `replace` rewritten to read one line would strand them all, and
    # `mutation()` would then hand back a reason instead of a text.
    #
    # A TRAILING NEWLINE IS NOT A BLOCK, and the first draft of this counted one:
    # `map_drift` and `config_vocab_drift` anchor on a single line WITH its newline
    # so the swap keeps it, and a test for a newline anywhere reported both of them
    # as multi-line - which would have left this case green with the only real
    # block row deleted. The line count after the trailing newlines are stripped is
    # what tells a statement from a pair of them.
    _blocks = [r for r in TABLE + ALLOW
               if r[2] == "replace"
               and len((r[3] or "").rstrip("\n").splitlines()) > 1]
    _block_says = [(r[0], mutation(r)[0] is not None) for r in _blocks]
    check("c2b a row's anchor may span more than one line, and one does - the "
          "shape a narrowing spelled in two statements needs, and the reason "
          "neither table has a 'proven elsewhere' column: %r" % (_block_says,),
          _blocks != [] and all(ok for _lint, ok in _block_says))

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

    suites = set(r[5] for r in TABLE) | set(r[5] for r in ALLOW)
    check("c5 every suite either table drives exists: %s"
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
    _buf = io.StringIO()
    _code = render([{"lint": "probe_drift", "verdict": "RED", "detail": "d",
                     "cases": ["x1"]}], [], ["ghost_drift"], stream=_buf)
    check("c14b a row naming a lint nothing derives is REPORTED and turns the "
          "exit code, even though its mutation reddened the suite exactly as a "
          "live row's would - that verdict is what made the stale row invisible: "
          "%r" % (_buf.getvalue(),),
          _code == 1 and "NO SUCH LINT" in _buf.getvalue()
          and "ghost_drift" in _buf.getvalue()
          and "naming no lint" in _buf.getvalue())
    # c15 LOOKS VACUOUS AND IS THE SECOND-DIRECTION CASE: it passes on a render
    # that never learned about the coarse verdict, and it is the only one here
    # that fails if that line starts printing for every row.
    _buf = io.StringIO()
    render([{"lint": "probe_drift", "verdict": "RED", "detail": "x1",
             "cases": ["x1"]}], [], stream=_buf)
    check("c15 a row that DOES name its case gets no such line, so the notice "
          "means something when it appears",
          "NAMES NO CASE" not in _buf.getvalue())
    # ...and the same second direction for c14b's notice, which is the only case
    # that fails if it starts printing unconditionally.
    check("c15b ...and a run with no stale rows prints no NO SUCH LINT line and "
          "exits 0, so that notice means something when it appears",
          "NO SUCH LINT" not in _buf.getvalue())

    # --- F166: the arm that does not read a name ------------------------------
    # A lint with a row in neither table and no recorded reason for having neither,
    # because its NAME matched no shape and it was in no list - so `coverage()`
    # could not report it absent and the table went on looking complete. The repair
    # is the derivation and not the name.
    _ng_live = gate_names()
    check("ng0 THE LIVE CLAIM: the derivation reaches a lint whose name says "
          "nothing about what it is, and every row that excuses one says why. "
          "`hand_rolled_runners` is the name F166 was about, and a version that "
          "lost this arm would drop it silently - `coverage()` cannot report a "
          "lint it never derives: %r" % (not_a_gate_problems(),),
          "hand_rolled_runners" in _ng_live
          and "redundant_constants" in _ng_live
          and not_a_gate_problems() == [])

    # THE ARM'S THREE FIXTURES, differing in one property each, because both halves
    # of it carry weight and a rule that answered the same way to all three would
    # pass one of them by accident. The walk name is read out of `_TREE_WALKS`
    # rather than written, so a fixture cannot go on testing a walk the tree has
    # stopped sharing.
    _ng_src = ("def judges(root=None):\n"
               "    return [r for r, _p in _output.%s(root)]\n"
               "\n"
               "def needs_input(source):\n"
               "    return [r for r, _p in _output.%s(source)]\n"
               "\n"
               "def counts_nothing(root=None):\n"
               "    return []\n" % (_TREE_WALKS[0], _TREE_WALKS[0]))
    _ng_fns = dict((n.name, n) for n in ast.parse(_ng_src).body
                   if isinstance(n, ast.FunctionDef))
    check("ng1 the arm asks what a function DOES: no required argument AND a walk "
          "of the shared tree. Drop the first half and every per-source helper "
          "these lints are built out of is counted as a second rule under a "
          "second name; drop the second and every parameterless helper in a gate "
          "module is a candidate: %r"
          % (sorted((n, walks_the_tree(f)) for n, f in _ng_fns.items()),),
          walks_the_tree(_ng_fns["judges"])
          and not walks_the_tree(_ng_fns["needs_input"])
          and not walks_the_tree(_ng_fns["counts_nothing"]))

    # THE TABLE, BOTH DIRECTIONS, driven from planted rows so neither depends on
    # the live table happening to contain the shape. The invented name carries no
    # `.py` spelling for the reason the fixtures further up this file do not.
    _ng_dead = not_a_gate_problems(
        table=(("probe_absent_helper", "a reason long enough to be a decision "
                                       "somebody could read and disagree with, "
                                       "which is what the length floor is for"),))
    _ng_named = not_a_gate_problems(
        table=(("layer_violations", "a reason long enough to be a decision "
                                    "somebody could read and disagree with, "
                                    "which is what the length floor is for"),))
    _ng_short = not_a_gate_problems(table=(("script_files", "too short"),))
    check("ng2 a row for a function nothing reaches, a row for one the SHAPES "
          "already derive, and a row whose reason is a label are three separate "
          "findings. The middle one is why this is checked at all: it silences "
          "nothing, so it can never be wrong, and it stays green forever while "
          "claiming to have excused something: %r / %r / %r"
          % (_ng_dead, _ng_named, _ng_short),
          len(_ng_dead) == 1 and "walks no tree" in _ng_dead[0][1]
          and len(_ng_named) == 1 and "already derived" in _ng_named[0][1]
          and len(_ng_short) == 1 and "no reason" in _ng_short[0][1])

    # ...and the second direction of the same table: every live row names a
    # function the arm really DOES reach, so the rows are excusing something rather
    # than describing a shape the tree no longer has. This is the case that fails
    # if a row is ever added to get a lint past `c1` - the excused name would then
    # be a gate the arm reaches and nothing proves.
    _ng_excused = sorted(name for name, _why in NOT_A_GATE)
    check("ng3 every excused name is really reached by the arm and really absent "
          "from the derived set - which is what stops this table becoming the "
          "place a lint goes to stop being proven: %r" % (_ng_excused,),
          _ng_excused
          and not any(name in _ng_live for name in _ng_excused)
          and not_a_gate_problems(table=NOT_A_GATE) == [])

    # --- the verdict comes back through a per-run path ------------------------
    # This file read `redfirst.sh`'s gate log out of the SYSTEM temp root by name,
    # so two runs on one machine crossed and the second attributed the first's
    # failing cases to its own mutation - a wrong verdict, in the tool whose whole
    # job is to say whether a verdict means anything.
    _rf_env = redfirst_env("/probe/scratch", base={"PATH": "/bin"})
    check("rf1 every temp-root variable is pinned, not just the one the shell "
          "reads: the child is python as well as sh, and a variable left alone is "
          "a lookup that quietly finds the shared directory again - which is the "
          "platform-shaped half of this bug rather than a second one: %r"
          % (sorted(_rf_env.items()),),
          all(_rf_env[n] == "/probe/scratch" for n in _TEMP_VARS)
          and _rf_env["PATH"] == "/bin"
          and len(_TEMP_VARS) > 1)
    check("rf2 ...and the log is read back from the directory the child was "
          "handed, so two rows running at once cannot read each other's verdict. "
          "Two different roots, two different paths - asserting one path alone "
          "would pass on the version that ignored its argument: %r vs %r"
          % (gate_log_path("/probe/a"), gate_log_path("/probe/b")),
          gate_log_path("/probe/a") != gate_log_path("/probe/b")
          and os.path.basename(gate_log_path("/probe/a")) == LOG_BASENAME)

    # F165: `prove()` removes its scratch with the plain call, and the reason
    # recorded beside it is a MEASURED one - every suite a row names removes its own
    # fixtures, so no repository and nothing read-only is left under there - rather
    # than the tempting one about which platform the shell can run on, which was
    # false in both halves. What keeps that record honest is that the rule which
    # WOULD convict a careless removal already reaches this file, and that is
    # asserted here instead of left as prose nobody re-checks.
    from _suite import unsafe_removal_violations   # the tools/ removal rule (F155)
    _rf_self = os.path.basename(__file__)
    _rf_walked = [rel for rel, _p in _output.py_files(os.path.join(REPO, "tools"))]
    _rf_findings = [rel for rel, _p in unsafe_removal_violations()]
    check("rf3 the removal rule REACHES this file and finds nothing in it - the "
          "premise the plain removal in `prove()` is recorded on. Both halves are "
          "needed: reaching it is what makes the silence mean something, and a "
          "file outside the walk would be silent for the other reason: %r / %r"
          % (_rf_self in _rf_walked, _rf_findings),
          _rf_self in _rf_walked and _rf_self not in _rf_findings)

    # -- the ALLOW half, checked the same way and for the same reason (F55) -----
    _a_unanchored = []
    _a_static = []
    for row in ALLOW:
        old, new = mutation(row)
        if old is None:
            _a_unanchored.append((row[0], row[1], new))
        elif old == new:
            _a_static.append(row[0])
    check("a1 every ALLOW row's anchor is still in the guard, exactly once, and "
          "the weakening really changes it. An anchor that moved makes "
          "`redfirst.sh` exit on a usage error, which reads nothing like 'this "
          "guard is no longer proven quiet': %r %r"
          % (_a_unanchored, _a_static),
          _a_unanchored == [] and _a_static == [])

    _a_unnamed = [r[0] for r in ALLOW if r[6] is None]
    check("a2 every ALLOW row NAMES the case that must go red, with no coarse "
          "spelling available. A whole suite reddens the moment a guard starts "
          "flagging everything, so 'the suite went red' would be satisfied by any "
          "over-fire and would credit this row for nothing: %r" % (_a_unnamed,),
          _a_unnamed == [])

    # The mutated file is the GUARD, and that is what makes the row an ALLOW row
    # rather than a red one wearing the label. A row pointed at a document or a
    # committed artifact would be breaking the thing the guard watches, which is
    # the direction the table above already covers.
    #
    # READ AGAINST A NAMED LIST, not against a directory. This used to say "under
    # `scripts/` and in `_GATE_MODULES`", which was the same claim while every
    # guard lived in the plugin; `scratch_debris()` does not, so the list is now
    # explicit and a guard added anywhere has to be added to it by name. A version
    # spelled as "anywhere under tools/" would have admitted every artifact and
    # document a tool reads, which is exactly the wrong side.
    _wrong_side = [(r[0], r[1]) for r in ALLOW if r[1] not in GUARD_FILES]
    check("a3 every ALLOW row mutates a file that HOLDS a guard and not the "
          "thing the guard watches - the property that makes this the other "
          "direction rather than a second copy of the first: %r" % (_wrong_side,),
          _wrong_side == [])

    # a3b is the case that stops a3 being satisfied by widening. Every entry in
    # `GUARD_FILES` has to name a file that exists, and the plugin-side half has to
    # still be exactly the derived module list - so a path cannot be appended here
    # to get a row past a3 without that being visible as a second, named guard.
    _missing_guard = [p for p in GUARD_FILES
                      if not os.path.isfile(os.path.join(REPO, p))]
    _derived = [S + m.replace(os.sep, "/") for m in _GATE_MODULES]
    check("a3b ...and the list of guard-holding files names real files, and "
          "still carries every module `gate_names()` derives its lints from: "
          "%r" % (_missing_guard,),
          _missing_guard == []
          and all(p in GUARD_FILES for p in _derived))

    _a_stale = stale_rows(ALLOW)
    check("a4b every ALLOW row names a lint the tree still derives, for the same "
          "reason c1b asks it of the red table: a weakening applied to a guard "
          "that no longer exists still reddens a suite, and would be counted as "
          "a guard proven quiet: %r" % (_a_stale,),
          _a_stale == [])

    _a_missing = allow_coverage()
    check("a4 ...and every load-bearing lint either has an ALLOW row or a "
          "recorded reason it cannot have one. This is the case that fails the "
          "day somebody adds a guard and nothing proves it stays quiet: %r"
          % (_a_missing,),
          _a_missing == [])

    _real = set(gate_names())
    _rowed = set(r[0] for r in ALLOW)
    _bad_exempt = [(n, "names no lint this repo has") for n, _w in ALLOW_EXEMPT
                   if n not in _real]
    _bad_exempt += [(n, "is exempt AND has a row") for n, _w in ALLOW_EXEMPT
                    if n in _rowed]
    _bad_exempt += [(n, "reason too short to disagree with")
                    for n, why in ALLOW_EXEMPT if len(why) < _MIN_ALLOW_REASON]
    check("a5 every exemption names a real lint, carries a reason a reader can "
          "disagree with, and excuses nothing that already has a row - so this "
          "cannot become the place a guard goes to stop being proven: %r"
          % (_bad_exempt,),
          _bad_exempt == [])

    # a6 LOOKS VACUOUS AND IS THE SECOND-DIRECTION CASE. Every case above passes
    # against a `render()` that prints one sentence for both halves, and a reader
    # of that summary could not tell which claim the run established. This is the
    # only case that fails if the two collapse back into one.
    _red_buf, _allow_buf = io.StringIO(), io.StringIO()
    _one = [{"lint": "probe_drift", "verdict": "RED", "detail": "x1",
             "cases": ["x1"]}]
    render(_one, [], stream=_red_buf)
    render(_one, [], stream=_allow_buf, claim=ALLOW_CLAIM)
    check("a6 the two halves say DIFFERENT things about what a proven row means "
          "- 'goes red when the thing it guards breaks' and 'stays quiet on input "
          "that is fine' are two claims, and one summary sentence for both would "
          "hide which one just ran: %r vs %r"
          % (_red_buf.getvalue().strip()[-40:],
             _allow_buf.getvalue().strip()[-40:]),
          _red_buf.getvalue() != _allow_buf.getvalue()
          and ALLOW_CLAIM in _allow_buf.getvalue()
          and ALLOW_CLAIM not in _red_buf.getvalue())

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
