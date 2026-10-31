#!/usr/bin/env python3
"""
Break what each gate guards, and require the gate to go RED. Then weaken each guard
until it over-fires, and require it to have been proven QUIET.

    tools/prove-gates.py                 # both directions, for every row
    tools/prove-gates.py --red           # only the break-it-and-see-red half
    tools/prove-gates.py --allow         # only the stays-quiet half
    tools/prove-gates.py --only layer    # the rows whose name contains this
    tools/prove-gates.py --changed a b   # the rows a change to these files touches
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

AND `ALLOW` IS THE SAME MACHINERY POINTED THE OTHER WAY. Proving a check goes
red is one half of its specification; the half nothing here asserted is that it says
NOTHING about legitimate input, which is the failure this repo ships most often - a
guard that refuses a write for what the prose inside it quoted, and then gets routed
around. An allow row weakens the GUARD until it over-fires and requires a case
asserting a known-good input to go red. Its own header says how the mutations are
chosen and where an allow case is not meaningful.

WHAT IT COSTS. One suite per row, so a full run is minutes rather than seconds. The
rows run concurrently, each in a WORKER TREE - a detached `git worktree` at HEAD
carrying the checkout's uncommitted edits and its untracked files that are not
ignored (an untracked nested repository is named on stderr and not carried), under
a scratch directory outside every checkout - on all cores but two (every core under
CI=true), and the report is rendered in the table's order whatever order they
finish in. A row mutates its worker tree and restores it under redfirst's trap; the
checkout itself is never written, and the trees are removed when the run ends - a
SIGTERM included, which first stops the rows still running rather than waiting
them out - or by the next run when this one was killed outright. Only the
pool's own worktree registrations are ever removed. It is not a per-commit gate;
run it before a release, or when a lint changes.

`--changed <paths>` IS THE "WHEN A LINT CHANGES" HALF, and the drive's sign-off
step is its caller: it hands over the files the phase changed, and only the rows
one of them touches run - the lint's own file, the file the row mutates, or the
suite holding the case it names (`changed_rows()`) - both directions unless
`--red`/`--allow` narrows it. A set naming no such file runs nothing and prints
`ran none` rather than exiting silently, and a row that is not proven prints a
`ROW NOT PROVEN:` line naming its direction, lint and the file it mutates - the
line that stop quotes.

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
# `_deps` lives outside the plugin, and `install_path()` never adds that directory.
if _output.LINTS_DIR not in sys.path:
    sys.path.insert(0, _output.LINTS_DIR)

import _deps  # noqa: E402  (the rule string one row mutates)

S = "plugins/audit/scripts/"
# The two lint modules (`_deps`, `_refs`) sit outside the plugin, so their rows name a
# prefix of their own.
L = "tools/lints/"
OUT = "tests/test__output.py"
DEP = "tests/test__deps.py"
REF = "tests/test__refs.py"
CFG = "tests/test__config_rules.py"
CFGL = "tests/test__config_rules_lints.py"
OUTL = "tests/test__output_lints.py"
ADP = "tests/test__ado_parent.py"
ADC = "tests/test__ado_conventions.py"
# The suites the derived remainder answers to. Every one of these lints was outside the
# hand-written source list, so none of them had a row until the list became a walk.
HLP = "tests/test__help.py"
HLPL = "tests/test__help_lints.py"
MVO = "tests/test__manifest_vocab.py"
BRN = "tests/test__branch.py"
ARE = "tests/test__areas.py"
TRL = "tests/test__doctor_trail.py"
FRT = "tests/test__filed_returns.py"
BEN = "tools/bench-hooks.py"          # its cases are inline, like every tools/ file

# The anchor every scripts/ row appends after: present once in every module, and
# nothing below it depends on what follows.
INSTALL = "\n_output.install_path()\n"

# A gate is a public function whose NAME says it reports drift or violations, plus
# the ones that report it under a name of their own. Derived rather than listed so a
# lint added later is missing from the table LOUDLY - see `coverage()`.
#
# `affected_dispatch` IS IN THE SECOND GROUP, AND THAT IS A DECISION RATHER THAN A
# CONVENTION SOMEBODY SKIPPED. Its name says nothing about reporting, and the
# arm that reads what a function DOES cannot see it either: it takes no required
# argument, but its corpus is a SUBPROCESS and a file - it runs `tools/affected.py`
# and reads the prefixes `tools/verify.sh` will dispatch - rather than one of the
# shared tree walks `_TREE_WALKS` names. Widening `walks_the_tree()` to "anything
# that shells out" would admit every runnable tool in this repo, so the honest
# answer is the name, with the reason beside it.
_GATE_SHAPES = ("_violations", "_drift", "_claims")
_GATE_NAMED = ("selftest_coverage", "entries_missing_guard",
               "depth_sensitive_paths", "doc_prose_numbers", "scratch_debris",
               "affected_dispatch")


# THE TWO PROSE-NUMBER PAYLOADS ARE BUILT, NOT WRITTEN, and that is not tidiness.
# `prose_number_claims()` now reads every `.py` this repo keeps, `tools/` included,
# so a payload spelling its own claim out would be a finding IN THE PROVER - the
# lint's needle planted in the tree the lint walks. The house repair is to build
# the literal rather than write it, so the count arrives through `%` and the line
# carries no numeral in front of the noun. `doc_prose_numbers()` reads every `.md`,
# which is why the CLAUDE.md payload gets the same treatment.

# The lint modules that left `scripts/` for `tools/lints/`, relative to it. `_GATE_ROOTS`
# reaches them through `tools`, so listing them here is only what `a3b` compares the
# derived guard files against.
_GATE_LINT_MODULES = ("_deps.py", "_refs.py", "_output_lints.py", "_help_lints.py",
                      "_config_rules_lints.py")

# Where those lints live, relative to `scripts/`. A list, because it is what
# `coverage()` under-claims by if a module holding one is left off it - and that
# happened: `config/_config_rules.py` grew the config-vocabulary comparison and its
# `*_drift` names were invisible here until this tuple named the directory.
_GATE_MODULES = (os.path.join("manifest", "_ado_parent.py"),
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
# `tools/_suite.py` is here for `unsafe_removal_violations()`, which refuses a
# tool that builds a git repository with objects in it and then removes the tree with
# a call that cannot unlink a read-only file. It joins this tuple in the same commit
# as its rows, which is the only way anything may join it: a coverage rule that
# arrives already failing gets an exemption written for it on day one, and that is
# how an exemption table stops meaning anything.
#
# ITS NEIGHBOUR IN THAT FILE WAS THE HOLE. `hand_rolled_runners()` keeps every
# tool's selftest on the shared harness, and it had a row in neither table and no
# recorded reason for having none - because its NAME ends in no shape above and it is
# not in the list below, so nothing here could see it and `coverage()` could never
# report it absent. The repair was NOT to rename the function to fit the pattern: a
# gate the derivation cannot see is a hole in the derivation, and renaming would have
# closed this instance while leaving the next one to be found the same way.
# `_TREE_WALKS` is the arm that closes it.
#
# THE META-GATE, AND WHAT IT FELL THROUGH IS NEITHER A NAME NOR A SIGNATURE.
# `gate-parity.py` was what kept the hand-maintained descriptions of the gate set
# honest with each other - it holds the workflow to the runner's slices now - and
# nothing proved any of its checks. It was NOT missed
# the way `hand_rolled_runners()` was missed above: `shard_matrix_drift`,
# `slice_drift` and `exemption_audit_drift` each end in a shape above, so the name
# arm would have derived them the moment anything opened the file. Nothing opened it -
# every arm reads functions out of `_gate_sources()`, which is this tuple and
# `_GATE_MODULES`, both written by hand. The file-level enumeration is the hole,
# and it SUBSUMES the function-level hole `_TREE_WALKS` closed: a file nobody lists is
# invisible to every arm at once, the arm added to close the last hole included.
#
# THIS ROW REGISTERS THE INSTANCE AND DOES NOT CLOSE THAT HOLE, said here rather
# than implied by a repair that is not one. Deriving the file set off the tree is
# not a drop-in swap, for two measured reasons. The NAME arm is a convention that
# holds only inside curated modules: `bench-hooks.render_violations()` takes a
# required argument and formats a report, so a widened scan would derive a
# FORMATTER as a lint, and `NOT_A_GATE` refuses by construction to excuse anything
# the name arm reaches. And it would arrive already failing by a wide margin -
# `config/_help.py`, `_ui_theme.py`, `manifest/_areas.py` and `manifest/_branch.py`
# each hold lints with a row in neither table. A coverage rule that arrives already
# failing gets an exemption written for it on day one, which is how an exemption
# table stops meaning anything. Re-derive the shape-named half of that remainder
# rather than trusting this paragraph - what it prints beyond `_GATE_MODULES` and
# this tuple is what a widened scan would owe rows for, and the walk-shaped half
# sits behind it:
#
#   grep -rnE "^def [a-z_]+_(violations|drift|claims)\(" \
#     plugins/audit/scripts tools
#
# ADDED WITH ITS ROWS, WHICH IS THE ONLY WAY IT MAY BE ADDED - the rule the two
# entries above it joined under, and the reason this is one commit and not two.
_GATE_OUTSIDE = ("tools/sweep-selftests.py", "tools/_suite.py",
                 "tools/gate-parity.py")

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
# the directory it was run from, and `_suite.py`'s removal rule. Each has the
# same two halves as any lint above and earns rows in both tables for the same reason.
#
# NAMED, NOT WIDENED TO A DIRECTORY. `a3`'s property is that an ALLOW row mutates the
# GUARD and never the thing the guard watches. Admitting all of `tools/` would admit
# every document and rendered artifact a tool reads, which is the direction the red
# table already covers - so each guard is added by name and the next one will have to
# be too.
# `GUARD_FILES` USED TO BE A LITERAL HERE and is derived now, by `guard_files()`.
# It is bound BELOW `NOT_A_GATE`, because deriving it needs that table to know which
# tree-walking helpers are not verdicts - a hand-written copy beside a hand-written
# source list is two lists that can disagree, which is the failure mode a single
# derivation exists to close off.

# (lint, file, kind, anchor, payload, suite, expected case label)#
# `count` is a number OR the word for it: the second row of each pair exists to
# prove the numeral table still reads the word spelling, and one builder
# serving both is what stops the two payloads drifting into different sentences.
def _claim_payload(count):
    """A probe function whose docstring makes a cardinality claim."""
    return ('\n\ndef _probe_claim():\n    """The table and its %s cases."""\n'
            '    return None\n' % (count,))


def _doc_claim_payload(count):
    """A prose line making a completeness claim, for the document scan."""
    return "\nThe tree carries all %s of them.\n" % (count,)


# BUILT FROM THE SLICE UP, so both rows are one sentence with one difference. The
# body is a literal rather than a formatted string on purpose: written with `%` it
# would be a live instance of the shape inside the prover, which is the lint's own
# needle planted in a tree the lint walks - the mistake the two prose payloads above
# were rewritten to stop making.
def _truncated_payload(sliced):
    """A probe whose one sentence counts a whole set and shows `sliced` of it."""
    return ('\n\ndef _probe_truncated(items):\n'
            '    return "%d thing(s): %s" % (len(items),\n'
            '                                ", ".join(' + sliced + '))\n')


# (lint, file, kind, anchor, payload, suite, expected case label)
# --- naming the case a row is about -------------------------------------------
# A row's last field names the case whose failure IS the proof, and there are two
# spellings of that because the tree has two kinds of label. A leading identifier
# (`pp1`, `sc10`) is one; a sentence is the other, and the suites that open theirs
# with `the`, `a`, `no`, `every` or a colon-suffixed group tag are most of them:
#
#   grep -hoE 'check\("[^ "]+' tests/*.py | sed 's/check("//' \
#     | grep -vE '^[a-z]+[0-9]' | sort -u
#
# Reading the first token was the only way in, so no row could point into any of
# those suites and the coarse whole-suite verdict was all they could ever get -
# which is the weaker claim this table exists to avoid.
#
# The suites are NOT migrated to leading ids. Their labels are readable sentences,
# which is the right thing for whoever reads the failure; what was missing is
# machine addressability, so the machine side is what changed.
def substr(text):
    """A selector that names a case by a piece of its LABEL, not by a leading id.

    For the suites whose labels are sentences, and for a case sharing a family
    id with its siblings - `substr("sc9 the panel")` reaches one of four `sc9`
    cases that `AMBIGUOUS LABEL` is otherwise right to refuse.

    IT MUST STILL BE UNIQUE, and that is not a weakening of the leading-id rule but
    the same rule read one level up: the whole `RED, WRONG CASE` guarantee rests on
    the row naming exactly one case, so a selector matching two is refused
    exactly as a duplicated id is. A substring is enough to be unique and short
    enough to stay readable in the table.
    """
    return ("substr", text)


def _read_source(path):
    """A whole-file UTF-8 read, closed by a `with` rather than left to the
    collector, which closes it at once only on an interpreter that counts
    references. Raises as `io.open` does, so each caller keeps its own
    `except`."""
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


# MOVED UP FROM BESIDE `mutation()`, which is its other caller: `_nav_min_target`
# below needs it while TABLE is still being built, and a name used before its own
# definition is a `NameError` rather than a subtle bug - so it has to sit here,
# ahead of the table, and not merely ahead of `mutation()`.
def _first_line(text, pattern):
    """The one line matching `pattern`, or None. Unique or it is not an anchor."""
    hits = [ln for ln in text.splitlines() if re.search(pattern, ln)]
    if not hits:
        return None
    for line in hits:
        if text.count(line + "\n") == 1:
            return line
    return None


def _nav_min_target(script_dir=None, hooks_dir=None, repo=None):
    """The repo-relative path of a file `navigability_violations` applies to,
    that carries EXACTLY the minimum non-selftest section markers the rule
    allows (2), where the FIRST `# -{2,}` line - the one a DROP mutation
    removes - is one of those two: dropping it must actually take the file
    below the floor, or the mutation proves nothing.

    DERIVED, not written down, because a name written into the table cannot
    see either way this row has already gone quiet: a refactor once took the
    named file below the LENGTH floor, and separately, a file can drift PAST
    the MARKER floor instead - `drop` removes one line, so a file holding
    three or more still has enough left after the drop, and the gate reports
    STAYED GREEN while the lint itself is fine. A walk run at the moment the
    mutation is needed sees whichever of the two has drifted; a name typed
    here can only ever describe the tree as it was the day it was chosen.

    Refuses LOUDLY when the tree holds no such file, rather than falling back
    to a name that once qualified: a target this walk cannot find is the row
    itself having nothing to mutate, and reporting a colour over that silence
    is exactly the failure this row exists to catch.
    """
    repo = repo or REPO
    for _rel, _kind, path in _deps._real_source_files(script_dir, hooks_dir):
        try:
            text = _read_source(path)
        except (OSError, UnicodeDecodeError):
            continue
        if len(text.splitlines()) < _deps._NAV_MIN_LINES:
            continue
        names = _deps._section_header_names(text)
        if names is None or len([n for n in names if n != "selftest"]) != 2:
            continue
        line = _first_line(text, r"^# -{2,}")
        if line is None:
            continue
        after = _deps._section_header_names(text.replace(line + "\n", "", 1))
        after_headers = len([n for n in after if n != "selftest"]) \
            if after is not None else 0
        if after_headers >= 2:
            continue  # the marker the drop removes is not one of the two counted
        return _output.posix_rel(path, repo)
    raise RuntimeError(
        "prove-gates.py: no file under scripts/ or hooks/ is >= %d lines while "
        "carrying EXACTLY the minimum 2 non-selftest section markers - the "
        "navigability_violations row ('n1') has no file left to drop a marker "
        "from, and reporting a colour over that silence would be the STAYED "
        "GREEN this row exists to catch" % (_deps._NAV_MIN_LINES,))


# --- the RED table: break the guarded thing, the guard must fire ---------------
# (lint, file, kind, anchor, payload, suite, the case that must go red)#
# kinds: "after" appends payload after anchor; "replace" swaps anchor for payload;
# "drop" removes the first line matching the anchor regex; "suffix" appends payload
# to it; "sub" applies payload as a (pattern, replacement) pair to it.
#
# `replace` IS THE KIND THAT SPANS LINES, which is worth stating outright:
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
  "_anchor_dir = os.path.dirname(os.path.abspath(__file__))  # probe", OUTL, "pp1"),
 # THE SAME LINT, MUTATED IN THE HALF THE ROW ABOVE CANNOT REACH. That one
 # breaks the block so the WHOLE-TEXT count falls to zero; this one leaves the block
 # intact and repeats one of its lines, which is the shape the doubled bootstraps
 # under `panel/` arrived in - a second `install_path()` that a count of the whole
 # block reads as compliant. The payload IS the anchor, so nothing here spells the
 # preamble a second time.
 ("path_preamble_violations", S + "_fmt.py", "after", INSTALL, INSTALL, OUTL, "pp1"),
 ("depth_sensitive_paths", S + "_fmt.py", "after", INSTALL,
  "\n_probe_dir = os.path.dirname(__file__)\n", OUTL, "ds1"),
 ("house_style_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_annotated(value: str):\n    return value\n", OUTL, "g10"),
 ("house_style_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_walrus(v):\n    if (w := v):\n        return w\n    return None\n",
  OUTL, "g10"),
 # THE COVERAGE RULE, MUTATED AT ITS DECISION. Every module is covered when its
 # `tests/test_<name>.py` exists; answer "covered" for everything and a shipped module
 # nobody tests reads clean. `sc2` builds the module with no test file.
 ("selftest_coverage", L + "_output_lints.py", "replace",
  "        if expected in test_files:\n            out[\"covered\"].append(named)",
  "        if True:\n            out[\"covered\"].append(named)", OUTL, "sc2"),
 ("prose_number_claims", S + "_fmt.py", "after", INSTALL,
  _claim_payload(12), OUTL, "pn0"),
 # The SAME lint, mutated in the word spelling. The digit row above cannot
 # notice a numeral table that has stopped reading words - which is the state this
 # repo shipped in until a count spelled out sat unnoticed in a comment block every
 # gate reads. Two rows for one lint, the way the house-style lint carries two.
 ("prose_number_claims", S + "_fmt.py", "after", INSTALL,
  _claim_payload("thirteen"), OUTL, "pn0"),
 ("entries_missing_guard", S + "status/audit-status.py", "drop",
  r"^    safe_stdio\(\)$", None, OUTL, "f1"),
 # An entry point whose parser stops going through the usage hook answers an
 # older copy's unknown verb with a bare "invalid choice" again.
 ("usage_hint_violations", S + "status/audit-logs.py", "drop",
  r"^    _claude_home\.attach_usage_hint\(ap\)$", None, OUTL, "uh7"),
 ("layer_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_up():\n    import _panel_state\n    return _panel_state\n",
  DEP, "r1"),
 ("tests_import_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_tests():\n    import test__output\n    return test__output\n",
  DEP, "tb7"),
 # The one-encoding rule, crippled. It is the whole mechanism keeping a second
 # escaping from coming back into the manifest writers, and a version reporting
 # nothing reads exactly like a tree that decides the escaping in one place.
 ("json_encoding_violations", L + "_deps.py", "replace",
  "def json_encoding_violations(script_dir=None, hooks_dir=None):",
  "def json_encoding_violations(script_dir=None, hooks_dir=None):\n    return []",
  DEP, "je2"),
 # The one-way-to-replace rule, crippled. It is what keeps a state file from being
 # replaced by code that shares its temp name with another writer, and a version
 # reporting nothing reads exactly like a tree that replaces only at its writers.
 ("state_write_violations", L + "_deps.py", "replace",
  "def state_write_violations(script_dir=None, hooks_dir=None, table=None):",
  "def state_write_violations(script_dir=None, hooks_dir=None, table=None):\n"
  "    return []",
  DEP, "sw3"),
 # The scrub-by-default rule, crippled. It is what keeps a new caller from
 # reaching the JSON writer that leaves machine paths in, and a version
 # reporting nothing reads exactly like a tree whose only raw writes are listed.
 ("raw_json_writer_violations", L + "_output_lints.py", "replace",
  "def raw_json_writer_violations(script_dir=None, hooks_dir=None, table=None):",
  "def raw_json_writer_violations(script_dir=None, hooks_dir=None, table=None):\n"
  "    return []",
  OUTL, "rj1"),
 # The bare-output-cut rule, crippled. It is what keeps a failing tool's
 # output from being cut to its head again, which is how a pre-commit hook's
 # actual failure went missing from the record twice.
 ("bare_output_cut_violations", L + "_output_lints.py", "replace",
  "def bare_output_cut_violations(dirs=None, pending=None):",
  "def bare_output_cut_violations(dirs=None, pending=None):\n"
  "    return []",
  OUTL, "bc1"),
 # The run-text line-end rule, crippled. It is what keeps a pattern anchored at
 # `$` from being applied to a run whose lines end `\r\n`, and a version
 # reporting nothing reads exactly like a tree whose every reader normalises.
 ("runner_line_end_violations", L + "_output_lints.py", "replace",
  "def runner_line_end_violations(dirs=None, home=RUNNER_TEXT_HOME, pending=None):",
  "def runner_line_end_violations(dirs=None, home=RUNNER_TEXT_HOME, pending=None):\n"
  "    return []",
  OUTL, "le1"),
 # ...and the real tree's end-of-run reader reading text it did not normalise:
 # that is the read a `\r` silently defeats, and `le4` is the case that reads the
 # real tree for it.
 ("runner_line_end_violations", S + "governance/run-test-gate.py", "replace",
  "    body = _ro.plain_text(text)\n    if wrapper_words(command):\n        return False\n",
  "    body = text or \"\"\n    if wrapper_words(command):\n        return False\n",
  OUTL, "le4"),
 # The newline rule, crippled. It is what keeps a committed file from being
 # written CRLF on Windows, and a version reporting nothing reads exactly like
 # a tree whose every text-mode write names its newline.
 ("text_write_newline_violations", L + "_output_lints.py", "replace",
  "def text_write_newline_violations(dirs=None, pending=None):",
  "def text_write_newline_violations(dirs=None, pending=None):\n"
  "    return []",
  OUTL, "nw1"),
 # The encoding rule, crippled. It is what keeps a text handle or a text-mode
 # subprocess from decoding in the locale's encoding, and a version reporting
 # nothing reads exactly like a tree whose every text I/O names UTF-8.
 ("text_encoding_violations", L + "_output_lints.py", "replace",
  "def text_encoding_violations(dirs=None, pending=None):",
  "def text_encoding_violations(dirs=None, pending=None):\n"
  "    return []",
  OUTL, substr("with no encoding anywhere under scripts/ or hooks/")),
 # The shell-script rule, crippled. It is what keeps a script from finding its
 # own directory in a way a backslash-only $0 defeats.
 ("sh_self_dir_violations", L + "_output_lints.py", "replace",
  "def sh_self_dir_violations(root=None):",
  "def sh_self_dir_violations(root=None):\n"
  "    return []",
  OUTL, "sd1"),
 # The returns-writer rule, crippled. It is what keeps a filed return - a
 # committed file under docs/audit - from being written past the scrub, and a
 # version reporting nothing reads exactly like a tree whose returns are clean.
 ("returns_writer_violations", L + "_output_lints.py", "replace",
  "def returns_writer_violations(script_dir=None):",
  "def returns_writer_violations(script_dir=None):\n"
  "    return []",
  OUTL, "rw1"),
 # The closers' one-read rule, crippled. It is what keeps a closer from reading
 # a filed return past the journal row that recorded it, and a version reporting
 # nothing reads exactly like a tree whose closers all read the checked way.
 ("plain_read_violations", S + "manifest/_filed_returns.py", "replace",
  "def plain_read_violations(script_dir=None, exempt=None):",
  "def plain_read_violations(script_dir=None, exempt=None):\n"
  "    return []",
  FRT, "pr1"),
 # The text-ordered-timestamp rule, crippled. It is what keeps a new reader from
 # ordering rows by how a stamp is spelled, and a version reporting nothing
 # reads exactly like a tree that orders every stamp by its moment.
 ("ts_order_violations", L + "_output_lints.py", "replace",
  "def ts_order_violations(script_dir=None, hooks_dir=None, table=None):",
  "def ts_order_violations(script_dir=None, hooks_dir=None, table=None):\n"
  "    return []",
  OUTL, "to1"),
 # The one-project-resolver rule, met by a new site in the real tree: a project
 # taken as dirname of a manifest path is the shape that sited a gate's record in
 # `docs/audit/docs/audit`, and the live-tree case has to see it.
 ("manifest_dirname_project_violations", S + "_fmt.py", "after", INSTALL,
  "\n\ndef _probe_project(manifest_path):\n"
  "    project = os.path.dirname(manifest_path)\n"
  "    return project\n", OUT, "md4"),
 # The one-tree rule, crippled. It is what keeps a hook from reading the main
 # checkout's plan for work in a linked worktree, and a version reporting
 # nothing reads exactly like hooks that all ask `_config.tree_for`.
 ("hook_tree_violations", L + "_deps.py", "replace",
  "def hook_tree_violations(hooks_dir=None):",
  "def hook_tree_violations(hooks_dir=None):\n    return []",
  DEP, "ht1"),
 # ...and its second rule, the same defect spelled `tree_for(PROJECT_ONLY)`.
 ("hook_tree_violations", L + "_deps.py", "replace",
  "            elif project_only and name in reads and name not in places:",
  "            elif False:",
  DEP, "ht7"),
 # The one-door rule for git's path base, crippled. A listing call that skips
 # the pair reads exactly like a tree where every call passes through it, and
 # `gb2` is the reverted site the lint must name.
 ("git_path_base_violations", L + "_deps.py", "replace",
  "def git_path_base_violations(script_dir=None, hooks_dir=None, exempt=None):",
  "def git_path_base_violations(script_dir=None, hooks_dir=None, exempt=None):\n"
  "    return []",
  DEP, "gb2"),
 # ...and its table, honouring a blank reason: a row with nothing to say would
 # then excuse the call it names.
 ("git_path_base_violations", L + "_deps.py", "replace",
  "                if why is not None and why.strip():",
  "                if why is not None:",
  DEP, "gb4"),
 # The whole mechanism, crippled the same way. A comment or a document citing
 # the private register is a claim nobody can check on the far side of it, and
 # a version reporting nothing reads exactly like a tree with no citations left
 # to find.
 ("register_citation_violations", L + "_deps.py", "replace",
  "def register_citation_violations(repo_root=None, table=None):",
  "def register_citation_violations(repo_root=None, table=None):\n    return []",
  DEP, "rc15"),
 # TWO CONSTRAINTS, and this row has now lost each of them once. The target must
 # be a file the rule APPLIES to (>= `_deps._NAV_MIN_LINES`) AND one carrying
 # EXACTLY the minimum non-selftest markers the rule allows (2), because `drop`
 # removes ONE line: a file with more than the minimum still has enough left
 # afterwards and never violates.
 #
 # A name typed into this table can only ever describe the tree as it was the
 # day it was chosen, which is why it has drifted in BOTH directions with no
 # test going red either time: first by falling below the LENGTH floor when a
 # refactor moved code out of the named file, and later - the constraint the
 # fix for THAT said nothing about - by growing PAST the MARKER floor while
 # comfortably clear of the length one. Both failures print the same colour,
 # STAYED GREEN, with the lint itself unbothered either time.
 #
 # `_nav_min_target()` is the repair: asked, not told, which file currently
 # sits at exactly the floor this mutation needs - so a future drift in EITHER
 # constraint moves what it returns instead of silencing what it proves - and
 # it refuses loudly rather than answer with a name that no longer qualifies.
 ("navigability_violations", _nav_min_target(), "drop",
  r"^# -{2,}", None, DEP, "n1"),
 # A count printed over evidence that was cut. TWO ROWS FOR ONE LINT, the
 # way the house-style and prose-number pairs are two, and for the same reason -
 # the second spelling is one an arm of the rule could silently stop reading. The
 # first plants the slice on the collection itself; the second wraps it, which is
 # how three of this lint's own sibling rows were written and is the arm that reads
 # the names a sliced EXPRESSION mentions rather than only the whole of it.
 ("truncated_evidence_violations", S + "_fmt.py", "after", INSTALL,
  _truncated_payload("items[:3]"), OUTL, "te11"),
 ("truncated_evidence_violations", S + "_fmt.py", "after", INSTALL,
  _truncated_payload("sorted(items)[:3]"), OUTL, "te11"),
 ("doc_prose_numbers", "CLAUDE.md", "after", "\n## Tests\n",
  _doc_claim_payload(12), DEP, "dpn0"),
 ("doc_prose_numbers", "CLAUDE.md", "after", "\n## Tests\n",
  _doc_claim_payload("thirteen"), DEP, "dpn0"),
 ("map_drift", L + "_deps.py", "replace", '    ("_output",),\n',
  '    ("_output", "_probe_layer_name"),\n', DEP, "r3"),
 ("hooks_rule_drift", "PLUGIN-BUILD-GUIDE.md", "replace", None, None, DEP, "g0"),
 ("tool_basename_drift", "tools/where.py", "after", "\nSOURCE_EXT = ",
  None, REF, "tb1"),
 ("sweep_glob_drift", "PLUGIN-BUILD-GUIDE.md", "replace",
  "python3 tools/sweep-selftests.py", "make test", REF, "s1"),
 # A path assembled from string literals has two halves to report: a whole path
 # that crosses a piece boundary, and the anchor alone split with the rest finished
 # through a name. Each is switched off on its own, so neither row can stay green
 # on the strength of the other.
 ("split_literal_violations", L + "_refs.py", "replace",
  "    paths = [m for m in pattern.finditer(joined)\n"
  "             if crosses(m) and _suite_anchored(m, suites)]",
  "    paths = [m for m in pattern.finditer(joined)\n"
  "             if False]", REF, "sl2"),
 ("split_literal_violations", L + "_refs.py", "replace",
  "    anchors = [m for m in _ANCHOR_RE.finditer(joined) if crosses(m)",
  "    anchors = [m for m in _ANCHOR_RE.finditer(joined) if False", REF, "sl2b"),
 # BOTH ROWS BELOW USED TO NAME NO CASE, and the coarse verdict was the only
 # thing available to them - not because their suite could not be named, but
 # because nobody had looked. The names here were read off a live run of each
 # row: `cf1` is the only case the flag mutation reddens, and the URL
 # mutation reddens the version-pin family, of which `p1` is one.
 ("command_flag_drift", "plugins/audit/commands/status.md", "suffix",
  r"^argument-hint:", " [--probe-flag]", REF, "cf1"),
 # A prohibition the document states and nothing accounts for. The mutation
 # is the shape the rule exists for: somebody writes a new **NEVER** and no hook
 # is asked whether anything stops it. `orchestrator.md` is the subject because it
 # is the document that governs every run and, measured, the one nothing checks.
 ("prohibition_drift", "plugins/audit/reference/orchestrator.md", "replace",
  "## Reporting",
  "## Reporting\n\n**NEVER `git cherry-pick` onto a phase branch.**",
  "tools/check-prohibitions.py", "pr0"),
 # The launcher's `ask` fail mode is what tells an operator the guards are
 # NOT running when no interpreter can be found, so a deciding guard registered
 # `open` is the one failure a blocking guard may not have: silent absence. The
 # mutation is the shape the rule exists for - somebody edits the wiring and the
 # loud fallback is quietly gone - and it is the WIRING that moves here, because
 # the guard watching it lives in the file the ALLOW row mutates instead.
 ("fail_mode_drift", "plugins/audit/hooks/hooks.json", "replace",
  "guard-secrets-read.py ask", "guard-secrets-read.py open",
  "tools/check-prohibitions.py", "pr6c"),
 # The pointer that says a human's own words go in unchanged. Removed from
 # ONE doc, because that is the shape the fault had: three commands said nothing
 # and the fourth's silence was the one that got a paraphrase into the chain.
 ("verbatim_rule_drift", "plugins/audit/commands/task.md", "replace",
  "**The operator's words go in VERBATIM**", "**A note about the reason**",
  REF, "vb1"),
 # ...and the heading those pointers name. A pointer at a section nobody kept
 # reads as compliance while naming nothing, so the rule doc is its own row.
 ("verbatim_rule_drift", "plugins/audit/reference/manifest-conventions.md",
  "replace", "## The operator's words go in unchanged",
  "## Operator text", REF, "vb2"),
 # The word for a red-first proof that could not be MADE, removed from the
 # document the CHECK reached rather than the one a person remembered: `bug.md`
 # orders a red-first repro test and owes the word for exactly that reason. The
 # mutation is the state every document was in before this entry - the proof is
 # ordered, and an executor refused permission to make it has no word for what
 # happened and writes an inference instead.
 ("red_first_drift", "plugins/audit/commands/bug.md", "replace",
  "and `could-not-prove` — with the", "and nothing in particular — with the",
  REF, "rf1"),
 # ...and the DECLARATION those pointers rest on. Drop the word from the enum and
 # every document still points at it, every document still passes, and the record
 # has nowhere to put what the documents just promised.
 ("red_first_drift", "plugins/audit/schema/audit-plan.schema.json", "replace",
  '            "could-not-prove",\n            "not-attempted"\n',
  '            "not-attempted"\n', REF, "rf2"),
 # The reviewer's return grading with a word the schema rejects and nothing
 # declares reviewer-only - the shipped state, `not-applicable` standing where
 # the executor's `not-attempted` belongs, which read as consistent on its own.
 ("red_first_vocabulary_drift", "plugins/audit/agents/audit-reviewer.md", "replace",
  '"redFirst": "proved|not-proved|could-not-prove|not-attempted"',
  '"redFirst": "proved|not-proved|could-not-prove|not-applicable"', REF, "rv1"),
 # The phase review's per-task entry loses `commit`, the key that binds each
 # answer to the diff it was given: every reviewer following the format files
 # an entry the verb refuses, and sign-off can never write the answers.
 ("phase_return_key_drift", "plugins/audit/agents/audit-reviewer.md", "replace",
  ' "commit": "<the SHA the brief handed>",', "", REF, "prk1"),
 # THE BRIEF GROWS A FIELD AND THE REFERENCE DOES NOT FOLLOW; renaming a key
 # is that event with a shorter diff. `testsAdded` is what fills `task.verifiedBy`,
 # so this is the shipped defect with the name changed - the field was declared,
 # the fallback path restated every rule beside it, and nobody asked for this one.
 ("return_shape_drift", "plugins/audit/agents/audit-executor.md", "replace",
  '"testsAdded"', '"testsWritten"', REF, "rs1"),
 # ...and the direction that actually shipped: the reference stops naming a field
 # AS a field. The backticks are the whole rule rather than a typographic taste -
 # `gates` in a sentence is a report about a run, in backticks it is a key a prompt
 # can ask a subagent for - so taking them off is taking the ask away.
 ("return_shape_drift", "plugins/audit/reference/execute-task.md", "replace",
  "`gates` per gate", "gates per gate", REF, "rs1"),
 # ...and the DECLARATION going missing, which neither row above reaches: with no
 # trigger there is no block, and a check that read a clean sheet out of that would
 # be grading a reference which asks for nothing as one that asks for everything.
 ("return_shape_drift", "plugins/audit/agents/audit-executor.md", "replace",
  "Report back a structured outcome:", "Report back what happened:", REF, "rs2"),
 # The runner list loses a runner red still reads - the reference keeps telling an
 # operator the helper reads fewer runners than it does, which is the shape a list
 # written from memory takes the day the table grows a reader.
 ("runner_list_drift", "plugins/audit/reference/execute-task.md", "replace",
  "`jest` and `vitest`. The output decides", "and `jest`. The output decides",
  REF, "rl1"),
 # A followed row goes back to citing reference prose - the state every row was in
 # before the pipeline stopped reading it - so the rule names a section its reader
 # never opens and is followed by nobody.
 ("followed_anchor_drift", "plugins/audit/README.md", "replace",
  "| step `decide-high-risk` |", "| § Non-negotiable guardrails |", REF, "fa1"),
 # ...and the step a row names stops printing its rule: the anchor still resolves
 # to a step, and the model at that step is told nothing.
 ("followed_anchor_drift", S + "governance/drive-phase.py", "replace",
  '"rule": ("Ask the human (AskUserQuestion); confirm only on their yes, "\n'
  '                 "else block with their reason.",)},',
  '"rule": ()},', REF, "fa1"),
 # A first-contact command goes back to handing a script that finds the
 # manifest itself a placeholder for the model to fill in - the guess the
 # model then narrates to the user.
 ("manifest_placeholder_drift", "plugins/audit/commands/status.md", "replace",
  '/audit-status.py" $ARGUMENTS',
  '/audit-status.py" <manifestPath> $ARGUMENTS', REF, "mp1"),
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
 # two code paths and only one of them was ever proved. This one is the SOURCE
 # side: a picture whose UI has moved under it, which no version stamp can see. A
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
 # The rule is scoped by kind, so the branch grew a second clause. A row that
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
 # its whole life, because `additionalProperties: true` accepts anything. So
 # the row that would have caught that goes first: rename the schema property and a
 # key the plugin reads stops being published.
 ("config_vocab_drift", "plugins/audit/schema/audit-config.schema.json", "replace",
  '    "ui": {\n', '    "uiRenamed": {\n', CFGL, "cv1"),
 # The same rule one surface further: a lever with a panel control and no
 # published row. A RENAME rather than a deletion - deleting the row would also cut
 # the table's contiguous run and take every key below it down at once, which proves
 # the wrong thing.
 ("config_vocab_drift", "plugins/audit/README.md", "sub",
  r"^\| `bypassKeyword` \|", ("`bypassKeyword`", "`bypassKeywordd`"), CFGL, "cv1"),
 # ...and the direction a markdown table makes possible at all: the heading moves,
 # nothing can be located, and the reader must SAY that rather than hand back the
 # empty finding list a clean table hands back. A parser that fails quiet is worse
 # than no parser, and this is the row that keeps it loud.
 ("config_vocab_drift", "plugins/audit/README.md", "replace",
  "## Configuration (`.claude/audit.config.json`)", "## Config keys", CFGL, "cv1"),
 # The comparison itself, on the branch only it owns. Its cases are fixture-driven
 # for the reason `_help.vocab_drift()`'s are - a lint you can only run against the
 # real tree is a lint whose own failure modes are untested - so this row breaks the
 # rule and the fixture case goes red where the three above cannot.
 ("root_vocab_drift", L + "_config_rules_lints.py", "replace",
  "set(known) - published - set(exempt)", "set()", CFGL, "cv4"),
 # THE ONLY ROW HERE THAT BREAKS A TEST RATHER THAN A SCRIPT, because a
 # test IS what this guard watches: the thing `scratch_debris()` guards is a suite
 # leaving its fixture behind in the directory it was run from. The payload is the
 # defect verbatim - a `mkdtemp` with no cleanup, inside a suite that otherwise
 # passes - and `x4` is the case that runs a real suite from this tree and reads
 # what it left. It is anchored on `def _selftest():` rather than on an import, so
 # the leak happens when the suite RUNS: a payload at module scope would leak while
 # the file was merely imported, which is not the shape being proven.
 ("scratch_debris", "tests/test__cli_fmt.py", "after",
  "def _selftest():\n",
  '    import tempfile as _leak\n    _leak.mkdtemp(prefix="probe-leak-")\n',
  "tools/sweep-selftests.py", "x4"),

 # --- The callers, and the rule that stops the next one -----------------------
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
 # THE PAYLOAD IS THE DEFECT VERBATIM: a relative path between a `mkdtemp` result
 # and the checkout, planted in a tool that already imports both names. It sits at
 # the top of `_selftest` and the case that goes red only READS the file, so the
 # line is never executed; `s33` is the case that reads every tool.
 ("unsafe_relpath_violations", "tools/check-git-pipeline.py", "after",
  "def _selftest():\n",
  "    os.path.relpath(tempfile.mkdtemp(), REPO)\n",
  "tools/_suite.py", "s33"),
 # THE READ AND THE TRIM DO NOT HAVE TO SHARE A LINE, which is the half of this
 # rule the defect it is named for actually needed: the bug type is read on one
 # line and its whitespace decided two lines down. Stop looking past the
 # expression and the repaired module reads as normalising NOTHING, so the rule
 # goes quiet about the very copy it exists to catch. `ck3` is the pre-fix pair
 # reconstructed as a fixture.
 ("config_read_violations", L + "_deps.py", "replace",
  "            normalisers = normalisers | _name_normalisers(scope, local)",
  "            normalisers = normalisers", DEP, "ck3"),
 # --- The two lints the name-shaped derivation could not see ------------------
 # THE MUTATED FILE IS A TOOL, not the guard: what `hand_rolled_runners()` watches
 # is a tool running its own suite instead of handing its cases to the shared
 # runner, and the payload is that defect at its smallest - a `_selftest` whose
 # body is no longer the delegation. `where.py` is the target because its
 # delegation appears exactly once in the file, so the anchor cannot reach two
 # places, and because nothing else in the tree reads it while this row runs.
 ("hand_rolled_runners", "tools/where.py", "replace",
  "    return run(_cases)", "    return 0", "tools/_suite.py", "s5"),
 # THE MERGED-BLOCK ACCESSOR. A config block that arrives through a `<root>_cfg`
 # call puts no key on the line, so without this branch every read taken off it
 # resolves to nothing and the module holding them is absent from the key's reader
 # list entirely - which is how a padded date slipped past a rule added the
 # same round to catch one key read two ways. `ck18` is that pair as a fixture.
 ("config_read_violations", L + "_deps.py", "replace",
  "    block = _block_accessor(node, roots)",
  "    block = None", DEP, "ck18"),
 # THE READER, NOT THE PRODUCER. This row used to delete the producer's own
 # `"countsBasis"` key, which reads like the historical defect it was named
 # after - `_evidence_io.row_for` once read `result.get("countsBasis")` while
 # nothing wrote it - but that read is off a PARAMETER the scan cannot resolve
 # to a producer at all, so removing the write never became a `dict_key_violations`
 # finding here: only `dk1`, the floor case that names this exact producer and
 # key to prove the scan even reached it, reddened - crediting a case the sweep
 # never observed, before the rule under test had anything to report.
 #
 # THIS READ IS RESOLVED, where that one is not: `pointer` is a local assigned
 # straight from `_ev.write_pointer(...)`, so the scan traces it to that
 # producer's own key set. Asking it for a key nothing writes is the shape only
 # the rule under test, through `dk2b`, catches; no producer's key set moves, so
 # the floor case stays exactly where it was.
 ("dict_key_violations", S + "governance/run-test-gate.py", "replace",
  'pointer.get("releaseRefused")', 'pointer.get("releaseRefusedXYZ")',
  DEP, "dk2b"),

 # --- The meta-gate: the workflow held to the runner it dispatches ------------
 # AN EXEMPTION TABLE RENAMED OUT FROM UNDER ITS CLASSIFICATION. The row in
 # `AUDITED_EXEMPTIONS` then names a subject that does not exist, which is the
 # register's own recurring shape one level up: an excuse that outlived the thing
 # it excused. Mutated in the module that OWNS the table rather than in the
 # classifier, so this is the guarded thing breaking and not the guard.
 ("exemption_audit_drift", L + "_ui_theme_lints.py", "replace",
  "CONTRAST_EXEMPTIONS = (", "CONTRAST_EXEMPTIONS_RENAMED = (",
  "tools/gate-parity.py", "ea1"),
 # A SHARDED SLICE THAT SKIPS A PART. A sweep slice may be split only because the
 # cells together still run every file; the mutation is the matrix that dropped
 # one, every slice still named by a job. `sv7` reads the real workflow against
 # the real runner's list.
 ("shard_matrix_drift", ".github/workflows/ci.yml", "replace",
  "        shard: [1, 2, 3, 4, 5]",
  "        shard: [1, 2, 3, 4]",
  "tools/gate-parity.py", "sv7"),
 # A RELEASE TIER THAT NO LONGER SWEEPS THE WHOLE TREE UNDER THE CODE PAGE. The
 # code-page leg's slice depends on the tier, and the mutation is its release arm
 # naming the per-run selection, so no run of any tier sweeps the suites that
 # selection leaves out. Chosen over swapping the per-run arm because nothing else
 # sees this one: a per-run arm naming the whole slice also leaves the per-run
 # slice with no per-run job, which `slice_drift` reports on its own, so `sv7`
 # would go red with this lint deleted. `sv7` reads the real workflow through
 # `slice_verdict()`, the path the gate itself takes.
 ("encoding_leg_drift", ".github/workflows/ci.yml", "replace",
  "'selftests-cp1252-whole' ||",
  "'selftests-cp1252' ||",
  "tools/gate-parity.py", "sv7"),
 # A PER-RUN SLICE NO JOB RUNS ANY MORE. The runner still lists it and every other
 # cell still runs, so nothing else notices that the Windows code-page leg is gone
 # from CI; only holding the matrix to the list does.
 ("slice_drift", ".github/workflows/ci.yml", "replace",
  "        leg: [plain, stress, cp1252]",
  "        leg: [plain, stress]",
  "tools/gate-parity.py", "sv7"),
 # ...and the other direction: a job naming a slice the runner does not list,
 # which the runner refuses the day the job runs - a red CI run with every local
 # gate green.
 ("slice_drift", ".github/workflows/ci.yml", "replace",
  "run: sh tools/verify.sh --only lint,runner,e2e",
  "run: sh tools/verify.sh --only lint,runner,e2e,lnt",
  "tools/gate-parity.py", "sv7"),
 # ...and the other question asked of that same runner, which is a PAIR rather
 # than a file: the selector chooses the checks and the runner dispatches them, and
 # the fault was a check the selector named and the runner had no arm for. The
 # mutation takes the arm away rather than teaching the selector a new shape,
 # because that is the direction with a unique anchor and because it leaves the
 # selector emitting the plugin validator the arm was added for - so the row is
 # about the disagreement and not about a probe. `ad0` runs the real pair.
 ("affected_dispatch", "tools/verify.sh", "sub", r"^    grep -v -e ",
  (r" -e '\^claude '", ""), "tools/gate-parity.py", "ad0"),

 # --- The fail-mode table, against the wiring that decides it -----------------
 # THE MUTATED FILE IS THE DOCUMENT, because a document is what this rule watches.
 # SECURITY.md tells a reader which hooks PROMPT when no interpreter can be found
 # and which pass in silence, and what actually decides that is the second argument
 # of each registration in `hooks.json`. This is that sentence going wrong in the
 # direction that matters: a BLOCKING guard documented as failing quietly, which is
 # the claim someone reads while deciding whether to trust this plugin with their
 # repository. `fm0` is the case that reads the real table against the real wiring.
 ("failmode_table_drift", "SECURITY.md", "replace",
  "| `guard-edits` | PreToolUse edits | **ask** | allow |",
  "| `guard-edits` | PreToolUse edits | silent | no-op |",
  "tools/gate-parity.py", "fm0"),
 # ...AND THE DIRECTION A ONE-SIDED RULE CANNOT SEE: the row is DELETED rather than
 # changed. Every cell that remains then agrees with its registration, so a check
 # that compared only the rows it found would report a table it had just watched
 # shrink as being in perfect agreement. `remind-tdd` is the row whose whole line is
 # unique in the document and whose hook stays wired after it goes.
 ("failmode_table_drift", "SECURITY.md", "drop", r"^\| `remind-tdd` \|",
  None, "tools/gate-parity.py", "fm0"),

 # --- The remainder the hand-written source list was hiding --------------------
 # Fifteen lints arrived the moment `_gate_sources()` became a walk. Every row
 # below is the debt that list was deferring, and each is written the way the rows
 # above are: break the thing the rule guards, and name the case that must notice.
 #
 # THE ONES THAT TAKE AN ARGUMENT ARE MUTATED IN THE RULE ITSELF, which is the
 # idiom `hierarchy_violations` already uses two screens up: a pure comparator has
 # no corpus in the tree to break, so the RED direction cripples its detection and
 # the fixture case that expects a finding goes red.

 # A KNOWN_* set that stops agreeing with the schema. `meta.merge` is the newest
 # one, which makes it the honest choice: a set added last week is the set most
 # likely to drift, and this is the rule that would say so. `mv18` and not the
 # scope case beside it: `mv19` counts anchors and properties, and a set losing a
 # key moves neither.
 ("schema_vocab_drift", S + "manifest/_manifest_vocab.py", "replace",
  'KNOWN_MERGE = {"auto", "removeWorktree", "deleteBranch"}',
  'KNOWN_MERGE = {"auto", "removeWorktree"}', MVO, "mv18"),
 # THE PURE COMPARATOR BEHIND IT, crippled. `vocab_drift` is what
 # `schema_vocab_drift` hands its three inputs to; a version that reports nothing
 # leaves every KNOWN_* set unchecked while the wrapper still runs.
 ("vocab_drift", L + "_help_lints.py", "replace",
  "def vocab_drift(levels, sets, anchors, off_schema):",
  "def vocab_drift(levels, sets, anchors, off_schema):\n    return []", MVO, "mv22"),
 # The mutation IS the defect that shipped: a command doc advertising a
 # value its parser refuses. `/audit:status --view pending` was documented and
 # exited 2 through a green gate set, because nothing asked a parser what a flag's
 # values were. `ch7` is the live case over the real command surface.
 ("command_choice_drift", "plugins/audit/commands/status.md", "replace",
  "[--view active|archived|all]", "[--view active|pending|archived|all]",
  HLPL, "ch7"),
 # ...and the comparator's own half, crippled the way `vocab_drift`'s is above: a
 # `choice_drift` that answers nothing lets every disagreement through while the
 # walk around it goes on looking busy.
 ("choice_drift", L + "_help_lints.py", "replace",
  "def choice_drift(cmd, advertised, accepted, unreadable):",
  "def choice_drift(cmd, advertised, accepted, unreadable):\n    return []",
  HLPL, "ch2"),
 # The git-ref rule, crippled. `ref_violations` is the reason a branch template
 # cannot compose a name git refuses, and a version reporting nothing lets the
 # validator pass a manifest whose every branch operation fails at the shell.
 ("ref_violations", S + "manifest/_branch.py", "replace",
  "def ref_violations(name):",
  "def ref_violations(name):\n    return []", BRN, "r1"),
 # The state-shape comparison, crippled. It is what tells a slot this copy wrote
 # from one an older build left, and a version reporting nothing makes every
 # sidecar look current.
 ("state_shape_drift", S + "status/_doctor_trail.py", "replace",
  "def state_shape_drift(state_dir, shape):",
  "def state_shape_drift(state_dir, shape):\n    return []", TRL, "dt32"),
 # The import budget, crippled. A hook reaching past the shared floor is paid on
 # every matching tool call, and a version reporting nothing is how that cost
 # arrives without anybody choosing it.
 ("budget_violations", BEN, "replace",
  "def budget_violations(hooks_dir=None, python=None):",
  "def budget_violations(hooks_dir=None, python=None):\n    return []",
  BEN, "h6"),
 # The explorer's return contract is written twice - the agent's own doc and
 # `commands/init.md`'s fallback restatement - and nothing read either copy. A field
 # added to ONE of them is the whole fault, so that is the mutation: the agent-side
 # copy gains a field the command-side copy has never heard of.
 ("explorer_contract_drift", "plugins/audit/agents/audit-explorer.md", "after",
  '"suggestedTests": ["...", ...], ', '"confidence": "0-1", ', DEP, "ec1"),
 # TWO WAYS, because the lint has two ways to stop being true. First the
 # document: the state commit's paragraph reverts to the wording an earlier
 # writer's paragraph shipped with, which is the historical bug and encodes no
 # checkable claim at all.
 ("commit_spelling_drift", "PLUGIN-BUILD-GUIDE.md", "replace",
  "**Its spelling is a fixed literal in the scope position**: `chore(audit-state):`",
  "**Its spelling is a distinct conventional type**: the fixed literal `audit-state`",
  DEP, "cs1"),
 # Then the DERIVATION, which is what makes it a class rather than a row per
 # file: drop a writer out of the discovery and the lint goes quiet about it.
 # This is the shape that would let a second writer ship undocumented.
 ("commit_spelling_drift", L + "_deps.py", "after",
  "        found = _commit_constants_in(tree)",
  '\n        if name == "commit-task-work.py":\n            found = {}',
  DEP, "cs1b"),
 # `orchestrator.md` governed every run with ONE anchored sentence, and each
 # of its fourteen sections was deleted in turn without a single gate noticing. So
 # both sides get a row, because a claim rots in both directions: the DOCUMENT half
 # renames a section heading, which is how a rule silently stops being stated.
 ("claim_drift", "plugins/audit/reference/orchestrator.md", "replace",
  "## Concurrency lock", "## Concurrency luck", ARE, "oa1"),
 # ...and the CODE half moves a literal the document quotes. This is the direction
 # a string-presence check cannot see at all, and it is the one that actually
 # happened three times this week.
 ("claim_drift", S + "governance/_locks.py", "replace",
  "E_LIVE, E_STALE, E_USAGE, E_ERR = 3, 4, 2, 1",
  "E_LIVE, E_STALE, E_USAGE, E_ERR = 7, 4, 2, 1", ARE, "oa4"),
 # ...and the LIST arm, which the two rows above cannot reach: they both mutate
 # `CLAIM_ANCHORS`, while `LIST_ANCHORS` derives a whole VOCABULARY from the enum
 # that owns it and compares it set-against-set. That arm was added with cases and
 # no mutation row, so it was the one part of this lint nothing here proved -
 # reported by the lane that added the second list row rather than found by the
 # coverage rule, because `coverage()` derives lints by NAME and both arms answer
 # to one name. Blinding the members-minus-stated half is the smallest mutation
 # that leaves the other arm intact, so a red here credits the list arm alone.
 ("claim_drift", S + "manifest/_areas.py", "replace",
  "        for name in sorted(members - stated):",
  "        for name in sorted(set()):", ARE, "oa14"),
 # The list anchor's window, and the mutation is the spelling it SHIPPED
 # with: `.*?` under `re.S` runs past the function body, so deleting the guard
 # the row is anchored to made the pattern latch onto a repeat of the same code
 # shape hundreds of lines further down and report a status the verb no longer
 # refuses. A false finding naming the wrong guard, from a row whose comment said
 # it could not slide. The bound is "no line may begin in column 0", which is a
 # property of a top-level body rather than a guess at what follows it.
 ("claim_drift", S + "manifest/_areas.py", "replace",
  r'def _locked_scope\((?:(?!\n\S).)*?node',
  r'def _locked_scope\(.*?node', ARE, "oa26"),
 # The refusal that keeps an EMPTY vocabulary from agreeing with any
 # document. Blinding it does not go quiet - it turns every word the section
 # names into "a status the code does not produce", so the run stays non-zero
 # while pointing at the wrong side, which is why the case asserts the
 # empty-vocabulary finding AND the absence of the member findings.
 ("claim_drift", S + "manifest/_areas.py", "replace",
  "        if not members:", "        if False:", ARE, "oa28"),
)


# --- the other half of the specification: the guard that stays QUIET ----------
# EVERY ROW ABOVE PROVES A CHECK GOES RED, AND NONE PROVED ONE STAYS QUIET.
# A guard has two halves: it fires on the thing it exists for, and it says nothing
# about legitimate input. Only the first was ever proven here, and the second is
# this repo's repeatedly-shipped failure mode - a guard refused a heredoc that
# CREATED a markdown file because the prose inside it quoted a path to a key file.
# The operation was a write, the target was a document, and the only
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
# document, the comment stripper that stops stripping. Those are the shapes this
# failure mode arrived in, and each one has a legitimate input the suite already
# names.
#
# A FEW ROWS NAME THE SAME CASE AS THEIR RED TWIN, and that is deliberate rather
# than lazy: a suite's live-tree assertion is the only allow corpus some of these
# rules have, and a row here proves that assertion is sensitive in BOTH directions
# instead of only the one it was written for.
ALLOW = (
 # The coverage rule's exemption table ignored: a module a row names with its reason
 # would be convicted anyway, which is the over-fire a guard that cannot be excused
 # invites, and `sc3` holds the named exemption quiet.
 ("selftest_coverage", L + "_output_lints.py", "replace",
  "        elif named in exempt:\n            out[\"exempt\"].append(named)",
  "        elif False:\n            out[\"exempt\"].append(named)", OUTL, "sc3"),
 # The one-door rule for git's path base, widened past the door: a function
 # that rebases its listing through the pair would be convicted anyway, and
 # `gb1` reads the whole tree, where every routed site is such a function.
 ("git_path_base_violations", L + "_deps.py", "replace",
  "                if name in reach:\n                    continue\n",
  "", DEP, "gb1"),
 # ...and its table ignored: a single-base site the table names with its reason
 # would be convicted, and `gb3`'s excused fixture is one.
 ("git_path_base_violations", L + "_deps.py", "replace",
  "                if why is not None and why.strip():\n"
  "                    continue\n",
  "", DEP, "gb3"),
 # `_output.py` is exempt from this rule BY NAME, and `pp10`'s fixture is the
 # ordinary compliant file. Counting one preamble too many is the smallest
 # plausible off-by-one, and it convicts every correctly-bootstrapped file.
 ("path_preamble_violations", L + "_output_lints.py", "replace",
  "        found = src.count(PATH_PREAMBLE)",
  "        found = src.count(PATH_PREAMBLE) + 1", OUTL, "pp10"),
 # THE SAME LINT'S NARROWING, REMOVED. The repeat check compares whole LINES of
 # the preamble and skips the blank ones. Stop skipping them and a blank line
 # becomes a preamble line, so every file holding one more than once - which is
 # every file - reads as a partial repeat. `pp10` is the ordinary compliant
 # fixture, and it is what stops the repair over-firing on the whole tree it was
 # added to clean.
 ("path_preamble_violations", L + "_output_lints.py", "replace",
  "    wanted = set(line for line in PATH_PREAMBLE.splitlines() if line.strip())",
  "    wanted = set(PATH_PREAMBLE.splitlines())", OUTL, "pp10"),
 # --- The narrowing that lives in two statements ------------------------------
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
 ("path_preamble_violations", L + "_output_lints.py", "replace",
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
  "            seen.add(hit[0])\n", OUTL, "pp13"),
 # THE PUREST INSTANCE OF THAT NARROWING SHAPE IN THE TREE. The rule bans
 # `__file__`, and the pinned preamble is the one legitimate occurrence of it -
 # which is why the preamble is cut out before the scan. Stop cutting it and
 # every compliant file reads as a violation, quoting the very bytes the house
 # rule tells people to paste.
 ("depth_sensitive_paths", L + "_output_lints.py", "replace",
  "            tree = ast.parse(src.replace(PATH_PREAMBLE, blanked), filename=rel)",
  "            tree = ast.parse(src, filename=rel)", OUTL, "ds5"),
 # The rule is the annotation, not the parameter. Drop the `is not None` and a
 # default argument - `ga5`'s fixture, and most signatures in the tree - is
 # reported as annotated.
 ("house_style_violations", L + "_output_lints.py", "replace",
  "        elif isinstance(node, ast.arg) and node.annotation is not None:",
  "        elif isinstance(node, ast.arg):", OUTL, "ga5"),
 # An importable helper has no entry block and its importer holds the guard. Take
 # that clause away and every module in the tree owes a `safe_stdio()` it must not
 # have. `f1` is the live-tree assertion, which is this rule's allow corpus.
 ("entries_missing_guard", L + "_output_lints.py", "replace",
  "            if not entries:", "            if False:", OUTL, "f1"),
 # A parser wrapped at construction, and a `parents=` template that never parses
 # argv, are the two narrowings. Take them away and the template every subcommand
 # parser inherits from reads as a bare parser; `uh5` names those fixtures quiet.
 ("usage_hint_violations", L + "_output_lints.py", "replace",
  "        if id(call) in wrapped or name in templates:",
  "        if False:", OUTL, "uh5"),
 # Two rows, one per escape hatch the house rule promises. A number that carries
 # the command re-deriving it is legal; blind the basis reader and the repair
 # itself becomes the finding.
 ("prose_number_claims", L + "_output_lints.py", "replace",
  '    for chunk in _backtick_chunks(line) + _backtick_chunks(following or ""):',
  "    for chunk in []:", OUTL, "pn5"),
 # ...and history is legal too. A decision record that says what a count was on a
 # given day is the second hatch, and this is the row that fails if it closes.
 ("prose_number_claims", L + "_output_lints.py", "replace",
  "        if _looks_historical(scope):", "        if False:", OUTL, "pn4"),
 # THIS LINT'S TWO NARROWINGS, EACH REMOVED. Both are the same shape - a guard
 # that convicts the very thing the house rule tells people to write - and both have
 # legitimate input in the real tree, which is what makes the rows mean something.
 #
 # The remainder clause first: `len(X) - n` in the same sentence IS the repair, so
 # a rule that stops crediting it reports `hooks/meter-usage.py` and
 # `_warning_groups.py` - the two sites that were already correct before
 # `some_of()` existed, one of which is a hook and can never reach it.
 ("truncated_evidence_violations", L + "_output_lints.py", "replace",
  "                    if key in sliced and key not in stated:",
  "                    if key in sliced:", OUTL, "te8"),
 # ...and the same-collection clause, which is the same shape: the narrowing lives
 # in TWO statements, because the line that REPORTS is keyed by the same property
 # the line above it tests. Widening only the test leaves `sliced[key]` looking up
 # a key it just stopped requiring, so the function RAISES and the suite dies
 # before the named case runs - a mutation that proves nothing while reporting a
 # guard proven. Measured, not assumed: written the short way first, this row came
 # back `LABEL GONE` with a KeyError. So the anchor is the block.
 #
 # WEAKENED, IT CONVICTS THE REPAIRED FUNCTION FOR THE LINE BESIDE THE ONE IT
 # REPAIRED. A count beside a slice of something ELSE is a SHA abbreviated for
 # width, and in `_doctor_completions._check_commit_trail` that pair sits inside
 # one sentence - which is `te7`'s fixture, copied from it.
 ("truncated_evidence_violations", L + "_output_lints.py", "replace",
  "                    if key in sliced and key not in stated:\n"
  "                        violations.append((name, sliced[key],\n"
  "                                           _TRUNCATED_EVIDENCE))\n",
  "                    if sliced and key not in stated:\n"
  "                        violations.append((name, min(sliced.values()),\n"
  "                                           _TRUNCATED_EVIDENCE))\n",
  OUTL, "te7"),
 # A file may import a sibling in a LOWER layer. Flag every edge and the legal
 # downward import - the shape most of this tree is built from - is a violation.
 ("layer_violations", L + "_deps.py", "replace",
  "        if not (li > lj):", "        if True:", DEP, "w3"),
 # EVERY migrated file names its test file in prose, twice. Swap the AST edge
 # reader for the string-literal one and the whole tree reaches into `tests/`,
 # which is the looser scan the docstring says it refuses to be.
 ("tests_import_violations", L + "_deps.py", "replace",
  "                for name in sorted(set(_imported_sibling_names(tree, found, None))):",
  "                for name in sorted(set(_py_literal_basenames(tree)) & found):",
  DEP, "tb4"),
 # The one-encoding rule, widened past the manifest writer to every `json.dump`
 # that carries an escaping. The journal's canonical row and the hook that appends
 # to it both spell one, because the string is a sha256 INPUT chaining one row to
 # the next rather than a document anybody diffs - so the widened rule convicts
 # honest code, and a lint that convicts honest code is one people route around.
 ("json_encoding_violations", L + "_deps.py", "replace",
  "                if _called_name(node) not in JSON_WRITER_NAMES:",
  "                if _called_name(node) not in JSON_WRITER_NAMES "
  "+ _JSON_DUMP_NAMES:",
  DEP, "je5"),
 # The one-way-to-replace rule, widened from the os module's two functions to any
 # method of those names. A string's `.replace` is the commonest call in the tree
 # and replaces no file, so the widened rule convicts every string edit - `sw4`'s
 # fixture holds a string's, a path's and an unbound str method's.
 ("state_write_violations", L + "_deps.py", "replace",
  "            and isinstance(func.value, ast.Name) and func.value.id in modules:",
  "            and isinstance(func.value, (ast.Name, ast.Attribute)):",
  DEP, "sw4"),
 # The raw-writer allow-list, ignored: a site that names its reason for
 # writing bytes exactly as given - a re-encoding, the user's own settings -
 # would be convicted anyway, and `rj2`'s fixture holds one beside the
 # scrubbing writer in the same file.
 ("raw_json_writer_violations", L + "_output_lints.py", "replace",
  "                if (named, where) not in allowed:",
  "                if True:", OUTL, "rj2"),
 # The bare-output-cut rule, widened to every slice: an id or SHA
 # abbreviation is a short head cut on purpose, and convicting it would teach
 # authors to route around the lint.
 ("bare_output_cut_violations", L + "_output_lints.py", "replace",
  "sl.upper.value < OUTPUT_CUT_MIN", "sl.upper.value < 0", OUTL, "bc2"),
 # The run-text line-end rule, widened past the modules that import the home of
 # the normalisation: a markdown reader with the same anchored pattern never
 # sees a `\r`, and convicting it would teach authors to route around the lint.
 # `le2`'s fixture holds one.
 ("runner_line_end_violations", L + "_output_lints.py", "replace",
  "        if stem[name] != home \\\n"
  "                and not any(module == home for module, _m in aliases.values()):\n"
  "            continue\n",
  "", OUTL, "le2"),
 # ...and with the normaliser's call name emptied: text that passed through
 # `plain_text` or came out of `.splitlines()` is the fix itself, and `le2`'s
 # compliant module is built from both.
 ("runner_line_end_violations", L + "_output_lints.py", "replace",
  "        if _call_name(expr) in (RUNNER_TEXT_NORMALISER, \"splitlines\"):",
  "        if _call_name(expr) in ():", OUTL, "le2"),
 # ...and its pending table ignored: a site the table names while it still
 # holds such a read would be convicted anyway, and `le3` is the case that
 # holds one silenced.
 ("runner_line_end_violations", L + "_output_lints.py", "replace",
  "                if site not in pending:\n"
  "                    violations.add((name, line, _LINE_END_READ))",
  "                if True:\n"
  "                    violations.add((name, line, _LINE_END_READ))",
  OUTL, "le3"),
 # The text-ordered-timestamp rule, widened from a `ts` read in place to one
 # inside ANY call: `stamp_moment(r.get("ts"))` is the moment the stamp names,
 # the fix itself, and `to2`'s fixture holds `_evidence_io`'s helpers built on it.
 ("ts_order_violations", L + "_output_lints.py", "replace",
  "    if isinstance(node, ast.Call) and _called_name(node) == \"str\" \\\n",
  "    if isinstance(node, ast.Call) and _called_name(node) != \"get\" \\\n",
  OUTL, "to2"),
 # ...and its table ignored: a site the table names with its reason would be
 # convicted anyway, and `to3`'s fixture holds one.
 ("ts_order_violations", L + "_output_lints.py", "replace",
  "                if (named, where) in allowed:\n                    continue\n",
  "", OUTL, "to3"),
 # The newline rule, widened to binary handles: a `wb` handle has no newline
 # translation to name, and convicting it would teach authors to route around.
 ("text_write_newline_violations", L + "_output_lints.py", "replace",
  "    if not isinstance(mode, str) or \"b\" in mode:",
  "    if not isinstance(mode, str):", OUTL, "nw2"),
 # ...and its pending table ignored: a file the table names while it still
 # holds such a write would be convicted anyway.
 ("text_write_newline_violations", L + "_output_lints.py", "replace",
  "                if name not in pending:\n"
  "                    violations.append((name, node.lineno, _NEWLINE_WRITE))",
  "                if True:\n"
  "                    violations.append((name, node.lineno, _NEWLINE_WRITE))",
  OUTL, "nw3"),
 # The encoding rule, widened to binary handles: a `rb` handle decodes nothing,
 # and convicting it would teach authors to name an encoding on bytes.
 ("text_encoding_violations", L + "_output_lints.py", "replace",
  "        return \"b\" not in mode.value",
  "        return True", OUTL, "en2"),
 # ...and widened past the encoding a subprocess names: the fix itself, a
 # `text=True` beside `encoding="utf-8"`, would be convicted.
 ("text_encoding_violations", L + "_output_lints.py", "replace",
  "    if name in _TEXT_RUNNERS and _text_switched(call) \\\n"
  "            and _keyword(call, \"encoding\") is None:",
  "    if name in _TEXT_RUNNERS and _text_switched(call):",
  OUTL, "en2"),
 # ...and its pending table ignored: a file the table names while it still
 # holds such a site would be convicted anyway.
 ("text_encoding_violations", L + "_output_lints.py", "replace",
  "            if name in pending:\n                continue\n",
  "", OUTL, "en3"),
 # The shell-script rule, widened to comments: a comment may name the pattern
 # it explains, and convicting it would make the explanation unwritable.
 ("sh_self_dir_violations", L + "_output_lints.py", "replace",
  "                if line.lstrip().startswith(\"#\"):\n"
  "                    continue\n",
  "", OUTL, "sd2"),
 # The returns-writer rule, widened: a function that only builds a return path
 # without writing one is not a bypass, and convicting it would push readers of
 # the path into the writer.
 ("returns_writer_violations", L + "_output_lints.py", "replace",
  "            if built and wrote:",
  "            if built or wrote:", OUTL, "rw2"),
 # The closers' one-read rule, widened: the checked read shares the plain one's
 # name as a prefix, and convicting it would refuse the very read the rule asks for.
 ("plain_read_violations", S + "manifest/_filed_returns.py", "replace",
  "(isinstance(fn, ast.Attribute) and fn.attr == PLAIN_READ)",
  "(isinstance(fn, ast.Attribute) and fn.attr.startswith(PLAIN_READ))",
  FRT, "pr2"),
 # The one-project-resolver rule, its table ignored: a site the table names with
 # its reason would be convicted anyway, and `md2`'s fixture holds one.
 ("manifest_dirname_project_violations", L + "_output_lints.py", "replace",
  "            if (rel, where) not in allowed:\n"
  "                violations.append(\n"
  "                    (rel, \"line %d (%s): derives a project",
  "            if True:\n"
  "                violations.append(\n"
  "                    (rel, \"line %d (%s): derives a project", OUT, "md2"),
 # The one-tree rule, widened to every `repo_root`. The config and the
 # session's own state live with the project on purpose, so a hook resolving
 # the project for those alone is honest code this would convict. The message
 # reads `reads` with a default, because indexing it raised KeyError on the
 # very fixture the allow case names and the suite died before printing it.
 ("hook_tree_violations", L + "_deps.py", "replace",
  "            if uses_root and name in reads:\n"
  "                violations.append((rel, \"%s resolves `_config.repo_root` and reads \"\n"
  "                                        \"the plan's tree through %s - ask \"\n"
  "                                        \"`_config.tree_for` which tree the work \"\n"
  "                                        \"is in\" % (name, reads[name])))",
  "            if uses_root:\n"
  "                violations.append((rel, \"%s resolves `_config.repo_root` and reads \"\n"
  "                                        \"the plan's tree through %s - ask \"\n"
  "                                        \"`_config.tree_for` which tree the work \"\n"
  "                                        \"is in\" % (name, reads.get(name, \"?\"))))",
  DEP, "ht3"),
 # The exemption table, ignored: the one scope that reads the project's plan
 # on purpose, with its reason declared, would be convicted anyway.
 ("hook_tree_violations", L + "_deps.py", "replace",
  '                if exempt.pop(key, "").strip():',
  "                if False:", DEP, "ht10"),
 # `reference/tracker-sync.md` names its own live-network probes "live-gate
 # F<n>", which resolves inside that same document and is not the private
 # register - drop the narrowing and the lint convicts the document for
 # naming its own evidence.
 ("register_citation_violations", L + "_deps.py", "replace",
  "        if before.endswith(_LIVE_GATE_MARKER):\n            continue",
  "        if False:\n            continue", DEP, "rc2"),
 # A byte-for-byte comparison that stops honouring the fence's trailing newline
 # reports drift on a guide that is exactly right, which is the direction a
 # regenerate-and-commit instruction cannot fix.
 ("map_drift", L + "_deps.py", "replace",
  "    if block != expected:", "    if block != expected.rstrip():", DEP, "g1"),
 # The excuse pattern, widened to the word it is about. The guide has to STATE the
 # hooks rule to satisfy the other half of this lint, so a pattern that matches the
 # subject convicts the document for complying.
 ("hooks_rule_drift", L + "_deps.py", "replace",
  "    hit = _GUIDE_HOOKS_EXCUSE.search(text)",
  '    hit = re.search("hooks", text)', DEP, "g0"),
 # Two markers is the floor the house rule sets, so a file carrying exactly two is
 # the legitimate minimum. Raise the bar by one and the rule convicts the shape it
 # asks for.
 ("navigability_violations", L + "_deps.py", "replace",
  "        if headers < 2:", "        if headers < 3:", DEP, "n6"),
 # The region scope, at the format each rule's own allow case is written in. A
 # document may QUOTE the retired sweep while telling a reader to run the current
 # one - a warning against it is the commonest way - and only the runnable region
 # separates the two.
 ("sweep_glob_drift", L + "_refs.py", "replace",
  "        return _yaml_run_scripts(text), None",
  "        return text, None", REF, "s5"),
 # The fence scope again, in the rule that spares the changelog's historical URL.
 # Read the whole document and a quotation of a dead link becomes a published
 # fetch instruction.
 #
 # THE FENCE PATTERN IS SWAPPED FOR A WHOLE-TEXT ONE, and widening the INNER loop
 # was tried first and proved nothing: the document this row is about carries no
 # fence at all, so the outer loop never ran and `p11` stayed green over a rule
 # that had stopped scoping anything. The over-fire has to reach a document with
 # nothing fenced in it, which is precisely the document the scope exists for.
 ("raw_url_pin_drift", L + "_refs.py", "replace",
  "    for fence in _FENCE_RE.finditer(text):",
  '    for fence in re.finditer(r"(?s)\\A(.*)\\Z", text):', REF, "p11"),
 # A page stamped with the current release is the whole point of the rule. Compare
 # nothing and every committed page is stale, including the one a release just
 # re-rendered.
 ("artifact_version_drift", L + "_refs.py", "replace",
  "            if stamp != version:", "            if True:", REF, "av5"),
 # ...and the same for the pictures: a sidecar that agrees about the bytes, the
 # version and the sources is the clean state, so a comparison that always
 # disagrees demands a re-capture that cannot help.
 ("screenshot_capture_drift", L + "_refs.py", "replace",
  '        if entry.get("sha256") != digest:', "        if True:", REF, "sc3"),
 # A tool may name itself, a hook and a test file. Ask the wrong set and all three
 # legitimate spellings are reported as references to files that are gone.
 ("tool_basename_drift", L + "_refs.py", "replace",
  "                if name not in known:", "                if name not in fixtures:",
  REF, "tb5"),
 # A run of literals is a split only where a path crosses a boundary between
 # pieces. Call every match a crossing and each long message that merely wraps
 # beside a whole path is reported.
 ("split_literal_violations", L + "_refs.py", "replace",
  "        return any(match.start() < start < match.end() for start, _ln in starts)",
  "        return True", REF, "sl3"),
 # The README row is where a declared flag has to appear. Read no row at all and
 # every command that documents its flags correctly is reported for omitting them.
 ("command_flag_drift", L + "_refs.py", "replace",
  "        row_flags = set(_FLAG.findall(rows[cmd]))",
  "        row_flags = set()", REF, "cf1"),
 # The needle narrowed back to a flag. `bug close` names none - it asks for "a
 # one-line `notes` justification" - so a flag-only census read three docs and
 # treated the fourth as having nothing to discharge, which is a clean sheet over
 # the one thing it could not see.
 ("verbatim_rule_drift", L + "_refs.py", "replace",
  'VERBATIM_FLAGS = ("--reason", "justification", "--confirm-high-risk")',
  'VERBATIM_FLAGS = ("--reason",)', REF, "vb3"),
 # The published vocabulary, minus one key the plugin really does publish. `cv1`
 # is the live-tree assertion over three surfaces written for three readers, and
 # this is what makes it a claim rather than a habit.
 ("config_vocab_drift", L + "_config_rules_lints.py", "replace",
  '    return set(schema["properties"]), None',
  '    return set(schema["properties"]) - set(["ui"]), None', CFGL, "cv1"),
 # A surface publishing exactly the vocabulary is SILENT. Stop subtracting what it
 # published and the agreement itself is the finding - the same line the red row
 # empties, mutated the other way.
 ("root_vocab_drift", L + "_config_rules_lints.py", "replace",
  "set(known) - published - set(exempt)", "set(known) - set(exempt)", CFGL, "cv3"),
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
 # THE PUREST SHAPE THIS GUARD HAS: the checker plants a file in the scratch
 # directory so it can tell a DELETION apart from a clean run, and that file is the
 # one thing in there it must not report. Stop excluding it and every suite in the
 # tree - all of them clean - is convicted of having dirtied its directory by the
 # evidence the checker left. `x2d` is the case that asserts a child which touches
 # nothing produces no finding, and it is the only one written to fail here.
 # THE ANCHOR REMOVED. A configuration path must start at a top-level property of
 # one of the two schemas; without it any dict carrying a `types` key is a config
 # block, and a BOARD's answer to a probe is convicted as a configured value in a
 # file that reads no configuration on that line at all. `ck7` is the fixture.
 ("config_read_violations", L + "_deps.py", "replace",
  "        return ((key,) if key in roots else None), normalisers",
  "        return (key,), normalisers", DEP, "ck7"),
 ("scratch_debris", "tools/sweep-selftests.py", "replace",
  "    strays = [name for name in left if name != sentinel]",
  "    strays = list(left)",
  "tools/sweep-selftests.py", substr("touches nothing")),
# --- the quiet half, continued: the removal rows ------------------------------
 # --- The half that decides who the rule is ALLOWED to leave alone ------------
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
 # THE RELATIVE-PATH RULE CONVICTING EVERY PAIR is the over-eager version: a call
 # whose two sides are both scratch, both checkout, or unknown can sit on one drive
 # by construction, and a rule that named them would be routed around within a
 # day. `s29` asserts three such calls are NOT reported, so it reads as vacuous and
 # passes on every version except this one.
 ("unsafe_relpath_violations", "tools/_suite.py", "replace",
  '        if {first, second} == {"scratch", "checkout"}:',
  "        if True:", "tools/_suite.py", "s29"),
 # --- The quiet half for the two lints nothing used to derive -----------------
 # THE NARROWING IS THE IMPORT LINE. A tool's `_selftest` is two statements, and
 # only one of them is the delegation; the other is what makes the runner
 # reachable. Stop admitting it and every tool in the tree is convicted of running
 # its own suite - by the very line the rule tells them to write. `s6` is the case
 # written for exactly that: it asserts a delegating body is NOT reported, so it
 # reads as vacuous and passes on every version except the over-eager one.
 ("hand_rolled_runners", "tools/_suite.py", "replace",
  '    return isinstance(stmt, ast.ImportFrom) and stmt.module == "_suite"',
  "    return False", "tools/_suite.py", "s6"),
 # THE PREFIX MUST BE A TOP-LEVEL PROPERTY, not merely a property name. `pricing`
 # is in the vocabulary as a NESTED key, so an accessor test that took any name
 # invents a path in a file that configures nothing on that line. `ck21` is the
 # fixture.
 ("config_read_violations", L + "_deps.py", "replace",
  "    return block if block in roots else None",
  "    return block or None", DEP, "ck21"),
 # THE OVER-FIRE THIS RULE IS ONE CHARACTER AWAY FROM. The whole guard is the
 # membership test between a key that was READ and the key set the value is known
 # to carry; drop it and every dict read in the tree is a finding, which is the
 # version of this lint that gets deleted in a week rather than obeyed. `dk4` is
 # the pair written for exactly this - the same producer and reader as `dk3` with
 # the key WRITTEN - so it fails on a rule that fires unconditionally while `dk3`
 # goes on passing.
 ("dict_key_violations", L + "_deps.py", "replace",
  "                if key in carried:", "                if False:", DEP, "dk4"),
 # --- The quiet half for the meta-gate ------------------------------------------
 # THE OVER-FIRE IS CONVICTING A MATRIX THAT RUNS EVERY PART. Report the missing
 # parts whether or not any are missing and every sharded workflow reads as
 # skipping one - `sv0`'s full `[1, 2, 3]` for `/3` is the pair that expects
 # silence.
 ("shard_matrix_drift", "tools/gate-parity.py", "replace",
  "            if want - have:",
  "            if True:",
  "tools/gate-parity.py", "sv0"),
 # THE SLICE RULE'S TWO OVER-FIRES. Convict every per-run slice whatever runs it,
 # or every slice a job names whether the list prints it or not, and a workflow
 # that runs every slice it should - `sv0`'s fixture - is reported broken.
 ("slice_drift", "tools/gate-parity.py", "replace",
  "        if \"per-run\" in tiers:\n            continue\n",
  "        if False:\n            continue\n",
  "tools/gate-parity.py", "sv0"),
 ("slice_drift", "tools/gate-parity.py", "replace",
  "        if name not in listed:",
  "        if True:",
  "tools/gate-parity.py", "sv0"),
 # THE CODE-PAGE RULE'S TWO OVER-FIRES, one per direction it reads. Report a
 # release tier without the whole tree whether or not one sweeps it, and the real
 # workflow - whose release arm does - is convicted: `el0` is that live pair.
 ("encoding_leg_drift", "tools/gate-parity.py", "replace",
  "    if not release_whole:",
  "    if True:",
  "tools/gate-parity.py", "el0"),
 # ...and read every windows cell as one a per-run run starts, whatever its tier,
 # and a whole-tree sweep that only the release tier runs is convicted as a
 # per-run cost. `el3` is a release-only job carrying exactly that sweep.
 ("encoding_leg_drift", "tools/gate-parity.py", "replace",
  "                if \"per-run\" in run[\"tiers\"]:",
  "                if True:",
  "tools/gate-parity.py", "el3"),
 # THE DERIVATION, WIDENED PAST THE THING IT SEPARATES. A reason is a SENTENCE;
 # the length floor is what tells an excuse from a label, and `{"P1": "done"}` is
 # data. Drop it to nothing and every string-to-string map in the tree becomes an
 # exemption owed a classification - a rule demanding rows about label tables,
 # which is a lint people delete rather than obey. `ea1` is the live case.
 ("exemption_audit_drift", "tools/gate-parity.py", "replace",
  "_REASON_MIN = 30", "_REASON_MIN = 0",
  "tools/gate-parity.py", "ea1"),
 # THE REGION SCOPE, in the shape every other region rule's allow row takes. The
 # selector prints its REASONS and its commands indented identically, and only the
 # `run:` line tells them apart - which is the ambiguity that made a catch-all arm
 # impossible and the silent skip the only option. Widen past it and the guard
 # reports the selector's own explanations as checks the runner cannot dispatch,
 # which is a finding against a tool for explaining itself. `ad4` is the case that
 # asserts a reason line indented like a command is not one.
 ("affected_dispatch", "tools/gate-parity.py", "replace",
  '        if not started or not line.startswith("  ") '
  'or line.startswith("  ("):',
  '        if not line.startswith("  ") or line.startswith("  ("):',
  "tools/gate-parity.py", "ad4"),

 # --- The two shapes a careless reader of that table loses in silence ----------
 # THE PARENTHETICAL STRIPPER THAT STOPS STRIPPING. One script appears in the table
 # twice because its events fail differently, and the second row is disambiguated by
 # a parenthetical name - so the hook is read with the parenthesis dropped. Stop
 # dropping it and the rule convicts a correct document twice over: a row describing
 # a hook nothing wires, and the pair that row was FOR, wired and undescribed.
 # `fm3` is the case that asserts an agreeing table and wiring report nothing, and
 # its fixture carries a parenthetical for exactly this.
 ("failmode_table_drift", "tools/gate-parity.py", "replace",
  r'        hook = re.sub(r"\([^)]*\)", "", _plain(cells[columns["hook"]])).strip()',
  '        hook = _plain(cells[columns["hook"]])',
  "tools/gate-parity.py", "fm3"),
 # ...AND THE OTHER TRAP, IN THE SHAPE SOMEBODY WOULD ACTUALLY WRITE IT. One cell
 # words several events, and a reader that took the first of them would leave the
 # rest of that row's pairs described by nothing - and then report them as wired and
 # undocumented. Narrowed to the first event, the rule convicts a table that covers
 # every pair it should. `fm3`'s fixture words two events in one cell for this
 # reason, and the narrowing is a slice rather than damage: the rule still parses,
 # still reads every row, and answers wrongly about exactly this shape.
 ("failmode_table_drift", "tools/gate-parity.py", "replace",
  '        named = tuple(event for event in events\n'
  '                      if re.search(r"\\b%s\\b" % (re.escape(event),),\n'
  '                                   cells[columns["event"]]))',
  '        named = tuple(event for event in events\n'
  '                      if re.search(r"\\b%s\\b" % (re.escape(event),),\n'
  '                                   cells[columns["event"]]))[:1]',
  "tools/gate-parity.py", "fm3"),

 # --- The same set of lints, weakened until they over-fire ---------------------
 # Every row here widens a rule until it convicts something correct, and names the
 # case that must go red for it. Most of them name their RED twin, for the reason
 # this table's own header gives: a suite's live-tree assertion is the only allow
 # corpus these rules have, and a row here proves that assertion is sensitive in
 # both directions rather than only the one it was written for.

 # The OFF_SCHEMA exemption, dropped. Every key that table legitimately excuses
 # - a key the plugin accepts and the schema deliberately does not declare -
 # then reports as drift, which is the state `mv21` asserts is normal.
 ("vocab_drift", L + "_help_lints.py", "replace",
  "        for key in sorted(vocab - schema - set(exempt)):",
  "        for key in sorted(vocab - schema):", MVO, "mv18"),
 # The trigger dropped, which turns "a document that NAMES a red-first proof"
 # into "every document in three directories" - the explorer brief, the reviewer
 # brief and every command doc convicted for a rule they have no part in. That is
 # how a check like this gets routed around inside a day, and it is the direction
 # the narrowing was chosen against: the scan is deliberately WIDE (whole
 # directories, so a new document arriving without the word is reported) and the
 # trigger is the only thing keeping the width from becoming noise.
 ("red_first_drift", L + "_refs.py", "replace",
  "            if RED_FIRST_TRIGGER not in text:",
  '            if "" not in text:', REF, "rf7"),
 # The declared reviewer-only grade dropped from what the reviewer may say, so
 # the lint refuses `not-proved` - the reviewer's honest answer when nothing names
 # a red run. A lint that convicts the one grade the design keeps on purpose is
 # the kind that gets deleted rather than believed.
 ("red_first_vocabulary_drift", L + "_refs.py", "replace",
  "    allowed = set(schema) | set(RED_FIRST_REVIEWER_ONLY)\n",
  "    allowed = set(schema)\n", REF, "rv3"),
 # The comparison made unconditional: every key the verb reads is reported as
 # omitted whether the format names it or not, so a format and a verb that
 # agree are convicted - the over-fire that gets a check deleted.
 ("phase_return_key_drift", L + "_refs.py", "replace",
  "                        for k in verb if k not in brief)\n",
  "                        for k in verb)\n", REF, "prk3"),
 # The TOP-LEVEL restriction dropped, so every nested key of the declared
 # shape is demanded as a standalone backticked word of its own: a reference that
 # writes `outcome` = `{ technical, descriptive }` is convicted for naming both
 # halves in one breath, which is honest prose and the ordinary way to write it.
 # The restriction is the only thing keeping this check's width from becoming
 # noise, which is the same argument `rf7` makes for its trigger.
 ("return_shape_drift", L + "_refs.py", "replace",
  "            if (depth == 1\n", "            if (True\n", REF, "rs6"),
 # The list sentence's end dropped, so every backticked word after it in the
 # document reads as a runner - `could-not-prove`, a flag, a file name - and a
 # document naming exactly the table's runners is convicted for the sentences
 # that follow it. The full stop is the narrowing that keeps the list the list.
 ("runner_list_drift", L + "_refs.py", "replace",
  '    stop = text.find(".", start)\n', "    stop = -1\n", REF, "rl3"),
 # The empty-rule test made unconditional: every step a row names is reported as
 # printing no rule, so a table whose every anchor resolves is convicted - the
 # over-fire that gets a check deleted rather than believed.
 ("followed_anchor_drift", L + "_refs.py", "replace",
  "            elif not steps[name]:\n", "            elif True:\n", REF, "fa2"),
 # The filter to scripts that resolve the manifest themselves, dropped. A
 # placeholder handed to a script that does NOT resolve it is still needed
 # (`status.md` hands `verify-invariants.py` one), so a lint that read every
 # placeholder convicts a line the model genuinely has to fill in.
 ("manifest_placeholder_drift", L + "_refs.py", "replace",
  "                if script not in resolving:\n                    continue\n",
  "", REF, "mp1"),
 # The needle widened from a BOLDED prohibition to any sentence carrying the word.
 # `orchestrator.md` says "never goes out of date" about a manifest and "never
 # recompute it" about a budget - prose about a thing, not a rule about an action -
 # so a matcher that took the bare word convicts the document for explaining
 # itself, which is the over-fire this narrowing was chosen against.
 ("prohibition_drift", "tools/check-prohibitions.py", "replace",
  r'_BOLD_NEVER = re.compile(r"\*\*[^*]*\bNEVER\b[^*]*\*\*")',
  r'_BOLD_NEVER = re.compile(r"[^.\n]*\bnever\b[^.\n]*", re.I)',
  "tools/check-prohibitions.py", "pr0"),
 # Drop the half that asks whether the hook DECIDES and the rule becomes
 # "every registration must be `ask`", which convicts `journal-writes.py` for
 # being wired the only way it correctly can be. That is the over-fire this
 # guard would be switched off for, and the reason the pairing is checked in two
 # directions rather than as one rule about tokens.
 ("fail_mode_drift", "tools/check-prohibitions.py", "replace",
  '        if decides and mode != "ask":',
  '        if mode != "ask":',
  "tools/check-prohibitions.py", "pr6c"),
 # The hint read TOO LOOSELY. Only the pipe-separated form makes a claim about a
 # set; widen the needle to swallow a metavar and `--phase <id>` becomes a
 # one-value list no parser declares, so every correctly written command is
 # convicted. `ch7` is the live claim that the real surface is clean, which is
 # exactly what an over-firing needle takes away.
 ("command_choice_drift", L + "_help_lints.py", "replace",
  r'([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)+)")',
  r'([<a-z][a-z0-9-.,>]*(?:\|[a-z][a-z0-9-]*)*)")', HLPL, "ch7"),
 # The refusing half, dropped. Report only the values the parser has that the doc
 # lacks and the direction the shipped defect actually took - a doc promising a
 # value the parser rejects - stops being reported at all, while the walk still
 # looks busy.
 ("choice_drift", L + "_help_lints.py", "replace",
  "            if value not in got:",
  "            if False:", HLPL, "ch2"),
 # The git-ref rule, widened to a character every branch name here carries. `r3`
 # is the ALLOW case the module already had - a legal name reports nothing - and
 # it is what stops the rule being tightened into nonsense.
 ("ref_violations", S + "manifest/_branch.py", "replace",
  '_BAD_CHARS = " ~^:?*[\\\\"', '_BAD_CHARS = " ~^:?*[\\\\/"', BRN, "r3"),
 # The sidecar skip, removed. A plugin's own sidecar shares the session prefix and
 # holds one unrelated key, so reading it as this copy's slot reports drift on
 # every project that has ever journalled a write - which is `dt33`'s case.
 ("state_shape_drift", S + "status/_doctor_trail.py", "replace",
  'name.startswith(shape["sidecar"]) or not ', "not ", TRL, "dt33"),
 # The floor subtraction, dropped. Every hook then reports every module it loads,
 # including the shared floor every one of them pulls - so `h7`, the hook that
 # imports only floor members, is convicted.
 ("budget_violations", BEN, "replace",
  "        allowed = set(floor) | set(granted)", "        allowed = set(granted)",
  BEN, "h7"),
 # The three `schema_*_drift` wrappers are proven through the comparators above,
 # which is where their whole verdict is computed - so what is weakened here is
 # the INPUT each one reads, and the live case that must notice is its own.
 ("schema_vocab_drift", L + "_help_lints.py", "replace",
  "def vocab_sets(mod=None):",
  "def vocab_sets(mod=None):\n    return {'KNOWN_GHOST': ()}", MVO, "mv18"),
 # This lint's over-fire. The field/value split is structural: the value half of a
 # `key: value` pair is consumed first so a value that happens to be
 # identifier-shaped cannot be read as a field name. Reverse the regex to
 # key-colon only and every bare identifier in either block becomes a field, so
 # the two agreeing copies start disagreeing about the tree as it stands.
 ("explorer_contract_drift", L + "_deps.py", "replace",
  '    r\':\\s*"[A-Za-z_][A-Za-z0-9_]*"|"([A-Za-z_][A-Za-z0-9_]*)"\')',
  '    r\'"([A-Za-z_][A-Za-z0-9_]*)"\\s*:\')', DEP, "ec1"),
 # This lint's over-fire, and it is the reason the subsection bound reads the heading
 # LEVEL rather than a literal `## `. Bound it on `## ` and one script's
 # subsection swallows the next sibling script's paragraph, so every writer is
 # convicted of claiming its neighbour's commit spelling. `cs9`, over a fixture
 # whose level-3 siblings carry spellings of their own: the real guide holds one
 # writer now, whose swallowed neighbours quote no spelling, so `cs1` stays green
 # under this mutation and would prove nothing.
 ("commit_spelling_drift", L + "_deps.py", "replace",
  '    pattern = re.compile(r"\\n#{1,%d} " % (level,))',
  '    pattern = re.compile(r"\\n## ")', DEP, "cs9"),
 # This lint's over-fire. Anchors are section-SCOPED: drop the
 # scoping and every anchor matches text anywhere in the document, so a neighbour's
 # sentence launders a section that no longer states its own rule.
 ("claim_drift", S + "manifest/_areas.py", "replace",
  "    hits = [(name, body) for name, body in sections if name.startswith(prefix)]",
  "    hits = [(name, body) for name, body in sections]", ARE, "oa5"),
 # `oa28`'s other direction. Make the empty-vocabulary refusal UNCONDITIONAL and
 # every list row reports an empty vocabulary on every run - the shape a guard
 # gets switched off for. It reddens several neighbours as well, which does not
 # affect the verdict: it keys on the named case, and `oa29` is the one that
 # asserts a vocabulary WITH members stays quiet.
 ("claim_drift", S + "manifest/_areas.py", "replace",
  "        if not members:", "        if members is not None:", ARE, "oa29"),
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
        text = _read_source(path)
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
            # BUILT, NEVER SPELLED: a `.py` literal under tools/ is what
            # `tool_basename_drift` checks, so a table that spelled one would be
            # the violation rather than the proof of it. `_refs`' own fixtures are
            # built the same way for the same reason; its docstring says so.
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
 ("suite_elsewhere_paths",
  "the sweep's EXCLUSION LIST, for the reason `sweep_files` is one: it answers which "
  "development modules keep their cases in `tests/` rather than carrying a suite of "
  "their own, and a list of paths is not a list of findings. The verdict on each of "
  "those modules is `selftest_coverage`'s - which has rows above - and the list is "
  "held against the real tree by the sweep's own cases `d2` and `d3`."),
 ("self_resolving_scripts",
  "the INPUT to `manifest_placeholder_drift`, not a verdict: it answers which "
  "scripts call `<module>.resolve_manifest(...)` and so find the manifest "
  "themselves. A set of script names is what the placeholder lint judges command "
  "lines against, and an empty or wrong set shows up as that lint's mp1/mp2 going "
  "red, not as a finding of its own."),
 ("reach_graph",
  "the GRAPH the affected-check selection reads, not a verdict: it answers who "
  "imports and who runs each module and which suites scan the tree, and a graph "
  "of edges is not a list of findings. What makes it a candidate is that it "
  "walks every file under its roots with no argument; what makes it not a gate "
  "is that nothing it returns is a pass or a fail."),
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


# The three places this repository keeps code that can judge it.
_GATE_ROOTS = ("plugins/audit/scripts", "plugins/audit/hooks", "tools")


def _gate_sources(script_dir=None, repo=None):
    """[(rel, path, tree)] for every file that could hold a guard — DERIVED, not
    listed. `rel` is the file in forward slashes, repo-relative for a root under
    the repository and relative to `script_dir` when one is given.

    `rel` IS SPELLED AGAINST THE ROOT THE WALK STARTED FROM, never against the
    repository: `script_dir` is a fixture under the temp directory, which on the
    windows runner is on another drive than the checkout, and `os.path.relpath`
    between two drives raises instead of answering. A file found by walking a root
    is always on that root's drive, so the relative path below always exists.

    THE FILE-LEVEL HOLE, and it subsumes the earlier function-level one. Both
    derivation arms below used to iterate a HAND-WRITTEN tuple of paths, so
    neither of them was the
    first filter: **being listed was.** A file nobody listed was invisible to every
    arm at once, including the arm added to reach lints whose names say nothing —
    and `coverage()` cannot report a lint it never derives, so the table went on
    looking complete while fifteen lints had no proof at all.

    A WALK now, over `_GATE_ROOTS`. Adding a FILE is free; adding a LINT costs rows,
    which is the way round it should always have been.

    TWO THINGS THE WALK FOUND ON ITS FIRST RUN, both fixed rather than excused: it
    derived `bench-hooks.render_violations`, which is a FORMATTER whose name ended in
    a reporting shape (renamed `render_budget_findings` — the name arm refuses by
    construction to excuse what it reaches, and the repair was the name), and it
    surfaced a rule with no caller outside its own suite (since retired).

    AND ONE NARROWING WAS TRIED AND MEASURED WRONG, recorded so it is not tried
    again: refusing functions that take a required argument looks right — those are
    comparators, and `vocab_drift` really is the pure half of `schema_vocab_drift`
    beside it. It also removes `hierarchy_violations`, `conformance_violations`
    and `provenance_tag_violations`, every one a real lint with rows in both tables. A
    required argument does not tell a comparator from a rule; only what the caller
    does with it would, and an AST walk over one function cannot see that.

    `script_dir` still overrides the plugin half so a case can point the whole
    derivation at a fixture tree; when it is given, nothing else is walked.
    """
    repo_root = repo or REPO
    if script_dir is not None:
        roots = [("", script_dir)]
    else:
        roots = [(rel + "/", os.path.join(repo_root, rel.replace("/", os.sep)))
                 for rel in _GATE_ROOTS]
    out = []
    for prefix, root in roots:
        for dirpath, _dirs, files in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                rel = prefix + os.path.relpath(path, root).replace(os.sep, "/")
                try:
                    out.append((rel, path,
                                ast.parse(_read_source(path))))
                except (OSError, SyntaxError):
                    continue
    return out


def _derived_gates(script_dir=None, repo=None):
    """`[(file, lint)]` for every load-bearing lint and the file defining it,
    `file` as `_gate_sources()` spells it: repo-relative with forward slashes, or
    relative to `script_dir` when a case names one. The ONE reading of which function
    is a gate: `gate_names()`, `guard_files()` and `lint_homes()` are each a
    projection of it, so the set of lints and the set of their homes cannot be
    derived by two predicates that drift apart."""
    repo_root = repo or REPO
    excused = set(name for name, _why in NOT_A_GATE)
    out = []
    for rel, _path, tree in _gate_sources(script_dir, repo_root):
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            # A NARROWING WAS TRIED HERE AND MEASURED WRONG, which is worth more
            # than the space it costs. The idea was that a function you must hand
            # data to is a comparator rather than a rule - it would have removed
            # `vocab_drift`, which really is the pure half of `schema_vocab_drift`
            # beside it. It also removed `hierarchy_violations`,
            # `conformance_violations` and `provenance_tag_violations`, every one
            # of which is a real lint with rows in both tables. A required argument
            # does not tell a comparator from a rule; only what the caller does
            # with it would, and `_needs_an_argument` cannot see that.
            if (node.name.endswith(_GATE_SHAPES) or node.name in _GATE_NAMED
                    or (walks_the_tree(node) and node.name not in excused)):
                out.append((rel, node.name))
    return sorted(set(out))


def guard_files(repo=None):
    """Repo-relative paths an ALLOW row may mutate: every file holding a lint.

    DERIVED off `_gate_sources` for the reason the sources themselves now are. It
    was a hand-written tuple beside a hand-written source list, so the two could
    disagree and the only symptom would have been an ALLOW row that could not be
    written — which reads as the rule being awkward rather than as a list being
    short.

    A file earns a place by HOLDING a lint, not by being walked: `a3`'s property is
    that an ALLOW row mutates the guard and never the thing the guard watches, and
    admitting every file under the roots would admit every document and artifact a
    tool reads.
    """
    return tuple(sorted(set(rel for rel, _name in _derived_gates(repo=repo))))


# Bound after the two functions it needs, and after `NOT_A_GATE` above them: a
# tree-walking helper that is not a verdict must not drag its file in here.
GUARD_FILES = guard_files()


def gate_names(script_dir=None, repo=None):
    """Every load-bearing lint in the files that hold one, by name AND by shape.

    TWO ROOTS, because the guards are in two places: `_GATE_MODULES` under
    `scripts/`, and `_GATE_OUTSIDE` repo-relative. A version that read only the
    first derived a set that both coverage rules below then compared against - so
    a guard living outside the plugin was invisible to the rule that asks whether
    it is proven AND to the rule that asks whether its row still means anything.

    AND TWO ARMS, because a name is a convention and a convention is something a
    lint can fall straight through. A lint whose name ends in none of the shapes and sits in no list was
    invisible to BOTH coverage rules at once - which is the same silence one level
    up: `coverage()` cannot report a lint it never derives, so the table went on
    looking complete. `walks_the_tree()` reaches those by what they DO, and
    `NOT_A_GATE` is where a walk that is not a verdict says so out loud.
    """
    return sorted(set(name for _rel, name in _derived_gates(script_dir, repo)))


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
    for _rel, _path, tree in _gate_sources(script_dir, repo):
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


_HOLE = None    # one run of text a label fills in at run time
_FORMAT_SPEC = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[sdrfxi]")


def _label_template(node):
    """A `check()` label as a list of characters and `_HOLE`s, from its AST.

    A string constant is its characters; `"..." % (...)` is its left side with each
    format specifier a hole; `a + b` is both sides; anything else (a variable, a
    call) is one hole. The holes are what keep a label built in a loop from being
    called undefined: its fixed part is still read, and the part filled at run time
    can be anything.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return list(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _label_template(node.left) + _label_template(node.right)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        left = _label_template(node.left)
        text = "".join(c if c is not _HOLE else "\0" for c in left)
        out = []
        for i, piece in enumerate(_FORMAT_SPEC.split(text.replace("%%", "\1"))):
            if i:
                out.append(_HOLE)
            out.extend("%" if c == "\1" else c for c in piece
                       if c != "\0")
            out.extend(_HOLE for c in piece if c == "\0")
        return out
    return [_HOLE]


def _label_templates(path):
    """Every `check(...)` label in a suite's source as a template; None when the
    file cannot be read or parsed, which the caller must not read as "no labels"."""
    try:
        tree = ast.parse(_read_source(path))
    except (OSError, SyntaxError, ValueError):
        return None
    return [_label_template(n.args[0]) for n in ast.walk(tree)
            if isinstance(n, ast.Call) and n.args
            and isinstance(n.func, ast.Name) and n.func.id == "check"]


def _could_contain(template, text):
    """Can some filling of the template's holes contain `text` as a substring?

    Only if `text` also touches a fixed character of the template: a hole accepts
    any text, so a selector that fits wholly inside one is not evidence that any
    label carries it, and a check that accepted it would accept every selector.
    """
    seen = set()

    def walk(i, j, anchored):
        if j == len(text):
            return anchored
        if (i, j, anchored) in seen or i == len(template):
            return False
        seen.add((i, j, anchored))
        if template[i] is _HOLE:
            return any(walk(i + 1, j + k, anchored)
                       for k in range(len(text) - j + 1))
        return template[i] == text[j] and walk(i + 1, j + 1, True)

    return any(walk(i, 0, False) for i in range(len(template) + 1))


def _template_defines(template, target):
    """Does a label of this shape carry the row's selector?

    An id is the template's leading token, read only while it is literal: a hole
    right after the id could be more id (`zz1` + `a`), so it is not trusted.
    """
    if isinstance(target, tuple):
        return _could_contain(template, target[1])
    lead = template[:len(target) + 1]
    return (lead[:len(target)] == list(target)
            and (len(lead) == len(target)
                 or (lead[-1] is not _HOLE and lead[-1].isspace())))


def undefined_cases(rows, repo=None):
    """`(lint, suite, selector)` for every row whose case no suite source defines.

    A SECOND CHECK ON THE SAME SELECTOR, AND THE ONE THAT NEEDS NO MUTATION.
    `verdict()` reports LABEL GONE only on a run that mutates a worker tree and
    sends a suite red, so a row keyed on an id that stopped existing - a label
    that lost the space after its id reads as another id, `vb1 a` as `vb1a` - sat in the
    table until somebody ran the proof. Reading the suite's `check()` labels is
    the half the selftest can do on every sweep.

    A row naming no case (the coarse claim) is not this function's business, and a
    suite it cannot read is reported as undefined rather than skipped: an empty
    answer must mean every named case was found.
    """
    out = []
    for row in rows:
        lint, suite, target = row[0], row[5], row[6]
        if target is None:
            continue
        templates = _label_templates(os.path.join(repo or REPO, suite))
        if templates is None or not any(_template_defines(t, target)
                                        for t in templates):
            out.append((lint, suite, selector_text(target)))
    return out


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

    THE OTHER END OF THE SAME GAP. Every verdict below keys on the selector, so the whole
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
    `prove()` would mean mutating a worker tree to prove something about a string. Here
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
# to its own mutation. That is the same defect `verify.sh` was repaired for; no lint
# forbids it any more, so keeping a scratch path per run is author-enforced.
#
# THE REPAIR IS TO MOVE THE ROOT, NOT THE NAME. Pointing the child's temp root at a
# per-run directory makes the fixed basename unique without `redfirst.sh` having to
# emit the path it chose - which would be a contract change to the one script here
# that mutates a tree (a worker tree; never the checkout). It also sweeps up
# anything the mutated suite leaks, for free, which is the same trick
# `sweep-selftests.py` plays on every suite it runs.
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


def worker_env(scratch, tree, base=None):
    """`redfirst_env()` for a row run in the worker tree `tree`: git's location
    variables dropped, and a project or working directory the caller named
    pointed at the tree, so the row's child never resolves the checkout."""
    env = redfirst_env(scratch, _git_env(base))
    for name in ("CLAUDE_PROJECT_DIR", "PWD"):
        if name in env:
            env[name] = tree
    return env


def _bytes_or_none(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def redfirst_call(rel, old, new, suite, tree, scratch, base=None):
    """`{"argv", "cwd", "env"}` of the one child a row starts: `redfirst.sh`
    mutating `rel` in the worker tree `tree`, then the row's suite, with every
    temp root at `scratch`. A pure function of its arguments, so what a row's
    child is handed is pinned by a case without starting anything."""
    return {"argv": ["sh", "tools/redfirst.sh", rel, "--replace", old, new,
                     "--allow-dirty", "--", sys.executable, suite, "--selftest"],
            "cwd": tree, "env": worker_env(scratch, tree, base)}


def prove(row, repo, run=None, base=None):
    """Mutate, run the suite, restore - in `repo`, a worker tree, never the
    checkout: there is no default tree. Returns a dict; never raises on a red
    gate. `run` (default `subprocess.run`) and `base` (default the real
    environment) are the seams a case reads the child's call through.

    `--allow-dirty` because the tree mirrors the checkout's own edits, so the file
    a row mutates may differ from HEAD by design. redfirst's refusal exists for a
    tree somebody else may be writing to, and a worker tree has one writer: the
    row it is running. Its trap restores the file; the bytes are compared here as
    well, so a row that left its mutation behind is a verdict and not a silently
    poisoned tree for the next row on it."""
    lint, rel, _kind, _anchor, _payload, suite, target = row
    if not repo:
        raise ValueError("prove() needs a worker tree; the checkout is never one")
    tree = repo
    run = subprocess.run if run is None else run
    old, new = mutation(row, tree)
    if old is None:
        return {"lint": lint, "verdict": "UNANCHORED", "detail": new, "cases": []}
    path = os.path.join(tree, rel)
    before = _bytes_or_none(path)
    scratch = tempfile.mkdtemp(prefix="prove-gates-")
    try:
        call = redfirst_call(rel, old, new, suite, tree, scratch, base)
        proc = run(call["argv"], cwd=call["cwd"], env=call["env"],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = proc.stdout.decode("utf-8", "replace")
        try:
            with io.open(gate_log_path(scratch), encoding="utf-8",
                         errors="replace") as fh:
                gate = fh.read()
        except OSError:
            gate = ""
    finally:
        # THE ANSWER HERE IS THE PLAIN CALL - recorded rather than left
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
        # writes an object into one. The half that keeps "it never runs on the
        # windows leg" true is weaker and said so: CI runs verify.sh's slices and
        # nothing else, no slice runs this tool (`sh tools/verify.sh --list`
        # shows it), and nothing fails the day one is taught to - the change
        # would have to add it to a slice, where review sees it.
        shutil.rmtree(scratch, ignore_errors=True)
    if before is not None and _bytes_or_none(path) != before:
        with open(path, "wb") as fh:
            fh.write(before)
        return {"lint": lint, "verdict": "ERROR",
                "detail": "left %s mutated; put back from its pre-row bytes" % (rel,),
                "cases": []}
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


def render(rows, missing, stale=(), stream=None, claim="gates proven red",
           undefined=(), direction="red"):
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
    for lint, suite, selector in undefined:
        out.write("  NO SUCH CASE: the row for %s names %r, which no check() in %s "
                  "spells, so its proof can only ever read LABEL GONE\n"
                  % (lint, selector, suite))
    for r in coarse:
        out.write("  NAMES NO CASE: %s is proven only by its whole suite going "
                  "red\n" % (r["lint"],))
    # One line per row that was not proven, led by a fixed phrase and naming the
    # direction, the lint and its file: the sign-off step that runs this probe
    # quotes these lines as the reason it stopped, so the row is named there
    # rather than left for a reader to find in the column table above.
    for r in bad:
        out.write("  ROW NOT PROVEN: %s %s in %s - %s\n"
                  % (direction, r["lint"], r.get("file") or "?", r["verdict"]))
    out.write("%d of %d %s%s%s\n"
              % (len(rows) - len(bad), len(rows), claim,
                 ("; %d lint(s) missing a row" % len(missing)) if missing else "",
                 ("; %d row(s) naming no lint" % len(stale)) if stale else "")
              + (("; %d row(s) naming no case" % len(undefined))
                 if undefined else ""))
    return 1 if (bad or missing or stale or undefined) else 0


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
    changed = changed_paths(argv)
    if changed is not None:
        homes = lint_homes() if any(changed) else {}
        table = changed_rows(table, changed, homes)
        allow = changed_rows(allow, changed, homes)
        # NOTHING TO RUN IS SAID, AND IT IS SAID BEFORE ANY WORKER TREE. A set that
        # names no lint file is the common case at a phase's sign-off, and a
        # silent exit 0 there would read as every guarded lint proven.
        if not ((want_red and table) or (want_allow and allow)):
            sys.stdout.write("prove-gates: --changed named %d path(s) and none "
                             "is a lint's own file, the file a %s row mutates "
                             "or the suite holding its case, so ran none\n"
                             % (len(changed), "/".join(
                                 d for d, on in (("red", want_red),
                                                 ("allow", want_allow)) if on)))
            return 0
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
    # NO MARKER IS HELD. The one `_suite.hold` writes announced a run rewriting
    # the checkout, so a concurrent sweep would refuse rather than read a
    # half-mutated file;
    # every row now runs in a worker tree (`open_workers`), the checkout is never
    # written, and there is nothing mid-mutation for a sweep to read. Nor is a
    # second run refused: two runs hold two pools, and neither reads the other's.
    rows = (len(table) if want_red else 0) + (len(allow) if want_allow else 0)
    # A pool that cannot be reaped or opened is a refusal (exit 2), never a row
    # not proven: the drive reads exit 1 as a verdict on the lints.
    try:
        removed, left = reap_stale(REPO)
    except (RuntimeError, OSError) as exc:
        sys.stderr.write("prove-gates: could not look for a killed run's worker "
                         "trees, so no row ran: %s\n" % (exc,))
        return 2
    for root in removed:
        sys.stderr.write("prove-gates: took down %s, a pool its killed run left "
                         "registered\n" % (root,))
    # A stale pool that could not be taken down is the same refusal: exit 0
    # would read as a clean run over a checkout still carrying a killed run's
    # registrations, and exit 1 is a verdict on the lints.
    for root, problem in left:
        sys.stderr.write("prove-gates: could not take down %s, a pool its killed "
                         "run left registered, so no row ran: %s\n"
                         % (root, problem))
    if left:
        return 2
    pool = None
    try:
        if rows:
            try:
                pool = open_workers(REPO, pool_size(rows))
            except (RuntimeError, OSError) as exc:
                sys.stderr.write("prove-gates: could not open the worker trees, "
                                 "so no row ran: %s\n" % (exc,))
                return 2
            for rel in pool.get("skipped") or ():
                sys.stderr.write("prove-gates: %s is untracked and not a file (a "
                                 "nested repository, most often), so the worker "
                                 "trees do not carry it\n" % (rel,))
        return _prove(want_red, want_allow, table, allow,
                      only is None and changed is None,
                      trees=pool["trees"] if pool else None)
    finally:
        for problem in close_workers(REPO, pool):
            sys.stderr.write("prove-gates: left behind - %s; the next run takes "
                             "it down\n" % (problem,))


def changed_paths(argv):
    """The paths after `--changed`, up to the next flag - `[]` for a bare
    `--changed` - or None when the flag is absent, which is the whole table."""
    if "--changed" not in argv:
        return None
    out = []
    for arg in argv[argv.index("--changed") + 1:]:
        if arg.startswith("--"):
            break
        out.append(arg)
    return out


def _repo_rel(path):
    """`path` spelled as a row spells its file: forward slashes, no `./`."""
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def lint_homes(repo=None):
    """`{lint: (file, ...)}` - the file or files defining each load-bearing lint,
    projected off `_derived_gates()`, the walk `coverage()` derives the lints by."""
    homes = {}
    for rel, name in _derived_gates(repo=repo):
        homes.setdefault(name, []).append(rel)
    return dict((name, tuple(files)) for name, files in homes.items())


def changed_rows(rows, paths, homes=None):
    """The rows a change to one of `paths` owes a re-proof: a row is kept when
    the set holds the file DEFINING its lint (`homes`, else `lint_homes()`), the
    file its mutation edits, or the suite holding the case that must go red.

    THREE FILES, NOT ONE, because a row's mutated file is the thing its lint
    guards and is mostly not the lint's own file - most red rows plant their
    violation in some module the lint walks. Selecting by that file alone let a
    phase that weakened a lint, or the suite case guarding it, re-prove none of
    its rows, while the sign-off read the probe as green."""
    wanted = set(_repo_rel(p) for p in paths if p)
    if not wanted:
        return []
    homes = lint_homes() if homes is None else homes
    return [r for r in rows if r[1] in wanted or r[5] in wanted
            or any(h in wanted for h in homes.get(r[0], ()))]


# --- the worker pool: every row runs in a tree of its own --------------------
# A ROW NEVER RUNS IN THE CHECKOUT. Each one mutates a file, runs a suite and
# restores the file; done in the one live tree that is one row at a time, and the
# whole table outgrew the bound the drive's sign-off holds this probe to. So the
# rows run concurrently, each in a worker tree: a detached `git worktree` at HEAD
# carrying the checkout's tracked diff (staged into the tree's index) and its
# untracked, non-ignored files, so a run over a dirty tree still proves what its
# author is looking at. Ignored files are not carried, and neither is an untracked
# nested repository - `_mirror` names each one it skips. What the checkout sees is
# git registering and unregistering those trees under its git dir; `git status`
# never lists that, which is what the drive compares around the run.
#
# A KILLED RUN NEVER REACHES ITS `finally`, so every pool carries an owner file
# naming its pid, written before its first tree is added, and each run starts by
# reaping the pools whose owner is known to be gone (`reap_stale`). A pool whose
# owner is alive, or whose owner cannot be judged, may be another run's, and is
# left alone. A SIGTERM is turned into an exit (`__main__` below), so the drive's
# timeout teardown still reaches the `finally` that closes the pool.
#
# AND THAT `finally` DOES NOT WAIT OUT A RUNNING ROW. The exit lands in the main
# thread while rows are mid-suite on the pool's threads, and the thread pool's
# shutdown waits for them; a row is minutes long. So each row's child runs as a
# process group of its own (`_proc_group.group_kwargs`), and an exit or an
# interrupt stops every running group (`_stop_rows`) before that wait - which
# then waits for rows unwinding, not rows running. The cost is the one
# `_proc_group` names: a signal sent to THIS run's group no longer reaches the
# rows by itself, and a SIGKILL (no handler, no `finally`) leaves them running
# for their own length, and the pool for the next run to reap. A row whose child
# ignores SIGTERM is given `_proc_group.GRACE_SECONDS` before its SIGKILL, one
# such row after another - the same grace the drive's teardown gives this whole
# probe before its own SIGKILL, so a row that ignores SIGTERM can still cost the
# pool its cleanup, and the next run reaps it.
#
# ONLY THE POOL'S OWN REGISTRATIONS ARE EVER REMOVED. A bare `git worktree prune`
# would also unregister every other worktree of the checkout whose directory is
# missing - a kept audit tree with its provenance file among them - and the plugin
# reaps only what it started. So a registration is dropped by name: a path under a
# pool root, its admin directory checked to point there before it is deleted.
POOL_OWNER = "prove-gates-pool.json"
POOL_PREFIX = "prove-gates-pool-"

# A worker tree is the checkout's content, not its git location: a caller running
# under a git hook exports these, and a child reading them would act on the
# checkout instead of the tree it was started in.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                      "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_PREFIX")


def pool_size(rows, cpus=None, environ=None):
    """How many worker trees a run over `rows` rows opens: the sweep's own rule
    (`default_jobs` in `tools/sweep-selftests.py`, loaded rather than copied, so
    the two cannot disagree), capped at the rows there are."""
    import _loader
    jobs = _loader.load(os.path.join(_here, "sweep-selftests.py")).default_jobs
    return max(0, min(rows, jobs(cpus, environ)))


def run_ordered(items, work, jobs, on_abort=None):
    """`[work(item) for item in items]`, run on `jobs` threads, returned in the
    order of `items` whatever order they finish in - so a report rendered from it
    is byte-stable under any scheduling. An exception - one item's, or an
    interrupt or exit reaching the caller - cancels every item not yet started,
    calls `on_abort()` to stop the running ones, and is raised here once they
    have returned, so neither a Ctrl-C nor a SIGTERM waits out the queue or a
    running item."""
    from concurrent import futures
    if not items:
        return []
    pool = futures.ThreadPoolExecutor(max_workers=max(1, jobs))
    pending = []
    try:
        pending = [pool.submit(work, item) for item in items]
        return [f.result() for f in pending]
    except BaseException:
        for f in pending:
            f.cancel()
        if on_abort is not None:
            on_abort()
        raise
    finally:
        for f in pending:
            f.cancel()
        pool.shutdown(wait=True)


def _row_children():
    """The state `_row_runner` and `_stop_rows` share for one run: the children
    running now, and whether the run is stopping. Built per run, never held at
    module level, so two runs in one process cannot stop each other's rows."""
    import threading
    return {"live": set(), "stopping": False, "lock": threading.Lock()}


def _row_runner(children):
    """A `subprocess.run` for `prove()` whose child is a process group of its
    own, recorded in `children` while it runs. Once the run is stopping it starts
    nothing: the check and the start share the lock `_stop_rows` takes, so a row
    cannot start its child between the stop's snapshot and its end."""
    import _proc_group   # on sys.path through `install_path()` above

    def run(argv, **kwargs):
        kwargs = dict(kwargs, **_proc_group.group_kwargs())
        with children["lock"]:
            if children["stopping"]:
                raise RuntimeError("the run is stopping, so this row's child was "
                                   "not started")
            proc = subprocess.Popen(argv, **kwargs)
            children["live"].add(proc)
        try:
            out, err = proc.communicate()
        finally:
            with children["lock"]:
                children["live"].discard(proc)
        return subprocess.CompletedProcess(argv, proc.returncode, out, err)
    return run


def _stop_rows(children, stream=None):
    """Stop every row child running now, each as a whole group
    (`_proc_group.tear_down`), and start no more. Says on `stream` (stderr by
    default) each one whose stop could not be confirmed; returns how many."""
    import _proc_group   # on sys.path through `install_path()` above
    out = sys.stderr if stream is None else stream
    with children["lock"]:
        children["stopping"] = True
        running = list(children["live"])
    unconfirmed = 0
    for proc in running:
        if not _proc_group.tear_down(proc):
            unconfirmed += 1
            out.write("prove-gates: a row's child (pid %s) could not be confirmed "
                      "stopped\n" % (proc.pid,))
    return unconfirmed


def _git_env(base=None):
    env = dict(os.environ if base is None else base)
    for name in _GIT_LOCATION_VARS:
        env.pop(name, None)
    return env


def _git(cwd, args, data=None):
    """`(code, stdout bytes, stderr text)` of git in `cwd`. Checkout hooks are
    switched off: a worker tree is a scratch copy, not a checkout anybody works
    in."""
    proc = subprocess.run(
        ["git", "-c", "core.hooksPath=%s" % (os.devnull,)] + list(args),
        cwd=cwd, input=data, env=_git_env(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


def _under_a_checkout(path):
    """True when `path` or a directory above it holds a `.git`: a worker tree
    there would be read as part of that checkout by anything resolving one."""
    here = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return True
        up = os.path.dirname(here)
        if up == here:
            return False
        here = up


def _pool_parent():
    """The temp root the pool goes under: the one `tempfile` names, else the
    platform's own, whichever has no checkout above it. None when neither does."""
    seen = [tempfile.gettempdir()]
    if os.name == "posix":
        seen.append("/tmp")
    for cand in seen:
        if os.path.isdir(cand) and not _under_a_checkout(cand):
            return cand
    return None


def _mirror(repo, tree):
    """Write the checkout's uncommitted content into `tree`, a fresh worktree at
    HEAD: the tracked diff against HEAD (staged and unstaged, deletions and binary
    files included), applied to the tree's index as well so a staged new file is
    tracked there too, and every untracked file git does not ignore. Returns
    `(problem or None, skipped)` - `skipped` the untracked paths that are not a
    file or a link (an untracked nested repository is listed as its directory),
    which are not carried."""
    code, patch, err = _git(repo, [
        "diff", "HEAD", "--binary", "--no-ext-diff", "--no-textconv",
        "--no-renames", "--no-color", "--src-prefix=a/", "--dst-prefix=b/"])
    if code != 0:
        return "git diff HEAD in %s: %s" % (repo, err.strip()), []
    if patch.strip():
        code, _o, err = _git(tree, ["apply", "--index", "--binary",
                                    "--whitespace=nowarn", "-"], data=patch)
        if code != 0:
            return ("the checkout's diff does not apply to HEAD: %s"
                    % (err.strip(),)), []
    code, out, err = _git(repo, ["ls-files", "--others", "--exclude-standard",
                                 "-z"])
    if code != 0:
        return "git ls-files in %s: %s" % (repo, err.strip()), []
    skipped = []
    for rel in [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]:
        src, dst = os.path.join(repo, rel), os.path.join(tree, rel)
        parent = os.path.dirname(dst)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        if os.path.islink(src):
            os.symlink(os.readlink(src), dst)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
        else:
            skipped.append(rel)
    return None, skipped


def open_workers(repo, count):
    """`{"root", "trees", "skipped"}` - `count` worker trees mirroring `repo`'s
    current content, under one fresh scratch directory outside every checkout;
    `skipped` is what `_mirror` could not carry, for the caller to say aloud.
    Raises RuntimeError naming what failed, after taking down what it had made."""
    parent = _pool_parent()
    if parent is None:
        raise RuntimeError("no temp root without a checkout above it, so a worker "
                           "tree would be read as part of that checkout")
    root = os.path.realpath(tempfile.mkdtemp(prefix=POOL_PREFIX, dir=parent))
    import json
    with io.open(os.path.join(root, POOL_OWNER), "w", encoding="utf-8") as fh:
        fh.write(u"%s\n" % json.dumps({"pid": os.getpid(),
                                      "repo": os.path.realpath(repo)}))
    pool = {"root": root, "trees": [], "skipped": []}
    try:
        for i in range(count):
            tree = os.path.join(root, "w%d" % (i,))
            code, _o, err = _git(repo, ["worktree", "add", "--detach", "--quiet",
                                        tree, "HEAD"])
            if code != 0:
                raise RuntimeError("git worktree add %s: %s" % (tree, err.strip()))
            pool["trees"].append(tree)
            problem, skipped = _mirror(repo, tree)
            if problem:
                raise RuntimeError(problem)
            pool["skipped"] = skipped
    except BaseException:
        close_workers(repo, pool)
        raise
    return pool


def close_workers(repo, pool):
    """Unregister and delete every tree of `pool`, then its scratch root.
    Returns the problems - empty when nothing is left behind."""
    if not pool:
        return []
    problems = []
    for tree in pool.get("trees", ()):
        # Twice forced: once for a tree a killed row left dirty, twice for one a
        # killed `worktree add` left locked mid-creation.
        code, _o, err = _git(repo, ["worktree", "remove", "--force", "--force",
                                    tree])
        if code != 0 and os.path.exists(tree):
            problems.append("git worktree remove %s: %s" % (tree, err.strip()))
        elif code != 0:
            problem = _drop_registration(repo, tree, pool["root"])
            if problem:
                problems.append(problem)
    if pool.get("root") and not _output.remove_tree(pool["root"]):
        problems.append("could not delete %s" % (pool["root"],))
    return problems


# ONE DIRECTORY, ONE SPELLING. The paths the pool compares come from three
# writers: `open_workers` (resolved, native separators), `git worktree list` and
# an admin directory's `gitdir` (git's record - forward slashes on Windows, and
# whatever spelling the tree was registered under). Windows adds an 8.3 short
# name for the temp root beside its long one, and folds case. So no comparison
# here is made on a raw string: each side goes through `_canonical_path`, and a
# root the reaper REPORTS is spelled the way `open_workers` spelled it.
def _canonical_path(path, flavour=None):
    """`path` resolved - which on Windows also gives the long name for an 8.3
    short one and native separators - then case-folded where the platform folds
    case. `flavour` is the path module (`ntpath` lets a case drive Windows'
    folding on any platform)."""
    flavour = os.path if flavour is None else flavour
    return flavour.normcase(flavour.realpath(path))


def _under(path, root, resolve=None):
    """True when `path` is `root` or below it, on the separator boundary, both
    spelled canonically (`resolve`, injectable, defaults to `_canonical_path`)."""
    import _worktrees    # on sys.path through `install_path()` above
    return _worktrees.within_tree(root, path, resolve or _canonical_path)


def _admin_of(gitdirs, tree, resolve=None):
    """The name of the admin directory whose `gitdir` record names `tree`, or
    None. `gitdirs` is `[(name, recorded gitdir)]`; the record is the tree's
    `.git` file, so its directory is the tree, compared canonically."""
    import _worktrees    # on sys.path through `install_path()` above
    fn = resolve or _canonical_path
    for name, said in gitdirs:
        if _worktrees.same_tree(os.path.dirname(said), tree, fn):
            return name
    return None


def _drop_registration(repo, tree, root):
    """Unregister the pool tree `tree`, whose directory is already gone, by
    deleting its own admin directory - after reading that directory's `gitdir`
    and finding it names `tree`, under the pool root `root`. Never a prune: that
    would take every missing worktree of the checkout with it. Returns a
    problem string, or None."""
    if not _under(tree, root):
        return "%s is not under the pool root %s; left registered" % (tree, root)
    code, out, err = _git(repo, ["rev-parse", "--git-common-dir"])
    if code != 0:
        return "git rev-parse --git-common-dir in %s: %s" % (repo, err.strip())
    common = out.decode("utf-8", "surrogateescape").strip()
    # Relative to `repo` when git prints it relative; join keeps an absolute one.
    admin_root = os.path.join(repo, common, "worktrees")
    names = sorted(os.listdir(admin_root)) if os.path.isdir(admin_root) else []
    gitdirs = []
    for name in names:
        try:
            with io.open(os.path.join(admin_root, name, "gitdir"),
                         encoding="utf-8") as fh:
                gitdirs.append((name, fh.read().strip()))
        except OSError:
            continue
    name = _admin_of(gitdirs, tree)
    if name is None:
        return "no admin directory of %s names %s" % (repo, tree)
    admin = os.path.join(admin_root, name)
    if _output.remove_tree(admin):
        return None
    return "could not delete %s, the registration of %s" % (admin, tree)


def _owner_pid(root):
    """The pid in a pool root's owner file, or None when it holds none."""
    import json
    try:
        with io.open(os.path.join(root, POOL_OWNER), encoding="utf-8") as fh:
            pid = json.load(fh).get("pid")
    except (OSError, ValueError, AttributeError):
        return None
    return pid if isinstance(pid, int) else None


def _pid_state(pid):
    """True / False / None (cannot tell) - the plugin's own probe, read
    three-valued. `_suite.pid_alive` folds the unknown into False, which is right
    for an advisory marker and wrong for a pool: reaping on it would take down a
    run that may still be using its trees."""
    import _locks        # on sys.path through `install_path()` above
    return _locks.pid_alive(pid)


def _pool_tree(tree):
    """True when `tree` is spelled the way `open_workers` names a worker tree:
    `w<N>` directly under a directory named with the pool prefix."""
    root = os.path.dirname(tree)
    return (os.path.basename(root).startswith(POOL_PREFIX)
            and re.match(r"w\d+$", os.path.basename(tree)) is not None)


def reap_stale(repo, alive=None):
    """Take down every pool a killed run left registered with `repo`. Returns
    `(taken, left)`: `taken` the roots taken down whole, sorted, each spelled as
    `open_workers` spells a root (resolved) rather than as git lists it; `left`
    the `(root, problem)` of each stale pool `close_workers` could not finish,
    which is NOT in `taken` - a registration or a directory it left behind is a
    pool still there, and reporting it as taken down would be a claim with
    nothing behind it. A pool is stale when its owner file names a pid
    that is known to be gone - `alive(pid)` is False, not merely falsy - or when
    its root is gone altogether, owner file included, so no run can be using it.
    A tree that is not a pool tree is somebody else's, and never touched. Raises
    RuntimeError when git cannot list the worktrees: a run that cannot tell its
    own stale trees from another's does not start."""
    alive = _pid_state if alive is None else alive
    code, out, err = _git(repo, ["worktree", "list", "--porcelain"])
    if code != 0:
        raise RuntimeError("git worktree list in %s: %s" % (repo, err.strip()))
    trees = [ln[len("worktree "):] for ln in
             out.decode("utf-8", "surrogateescape").splitlines()
             if ln.startswith("worktree ")]
    stale, spelled = {}, {}
    for tree in [t for t in trees if _pool_tree(t)]:
        root = os.path.dirname(tree)
        if os.path.isdir(root):
            pid = _owner_pid(root)
            if pid is None or alive(pid) is not False:
                continue
        key = _canonical_path(root)
        spelled.setdefault(key, (os.path.realpath(root), root))
        stale.setdefault(key, []).append(tree)
    taken, left = [], []
    for key in sorted(stale):
        problems = close_workers(repo, {"root": spelled[key][1],
                                        "trees": stale[key]})
        if problems:
            left.extend((spelled[key][0], p) for p in problems)
        else:
            taken.append(spelled[key][0])
    return sorted(taken), left


def _proved(rows, trees=None):
    """`prove()` over `rows`, each in a worker tree of its own and each result
    carrying the file its row mutates, so a row that is not proven can be named
    with it. Results come back in the order of `rows`. Each row's child is
    started through `_row_runner`, so an exit or an interrupt stops the running
    rows (`_stop_rows`) rather than waiting them out."""
    import queue
    if not rows:
        return []
    if not trees:
        # Never the checkout as a fallback: a row there is the live-tree mutation
        # the pool exists to keep out of it.
        raise RuntimeError("%d row(s) and no worker tree to run them in"
                           % (len(rows),))
    free = queue.Queue()
    for tree in trees:
        free.put(tree)

    children = _row_children()
    runner = _row_runner(children)

    def one(row):
        tree = free.get()
        try:
            return dict(prove(row, tree, run=runner), file=row[1])
        finally:
            free.put(tree)
    return run_ordered(list(rows), one, len(trees),
                       on_abort=lambda: _stop_rows(children))


def _prove(want_red, want_allow, table, allow, whole, trees=None):
    """Both halves over the rows given, as ONE queue across the worker trees, then
    rendered half by half in the table's order. `whole` is a run over the entire
    table: only then is a lint with no row reported missing, since a narrowed run
    (`--only`, `--changed`) leaves rows out on purpose."""
    red = list(table) if want_red else []
    quiet = list(allow) if want_allow else []
    done = _proved(red + quiet, trees)
    code = 0
    if want_red:
        sys.stdout.write("proving %d gate(s) go RED; each mutates a worker tree "
                         "and restores it\n" % (len(table),))
        code |= render(done[:len(red)], coverage() if whole else [],
                       stale_rows(table), undefined=undefined_cases(table))
    if want_allow:
        sys.stdout.write("\nproving %d guard(s) stay QUIET; each weakens the GUARD "
                         "so it over-fires, and the named allow case must go red\n"
                         % (len(allow),))
        code |= render(done[len(red):], allow_coverage() if whole else [],
                       stale_rows(allow), claim=ALLOW_CLAIM,
                       undefined=undefined_cases(allow), direction="allow")
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

    # A ROW NAMING A CASE NO SUITE DEFINES, found without running a suite. A case
    # whose label lost the space after its id changes id silently (`vb1 a gate`
    # became `vb1a gate`), and a row keyed on the old id then reads LABEL GONE only
    # on a run that mutates a worker tree - so the table is read against the suites'
    # source here. The suite is a scratch file, not a path of the plugin, so the
    # case fails on this function and not on the tree it happens to run in.
    _c1d_dir = tempfile.mkdtemp(prefix="prove-gates-c1d-")
    try:
        with io.open(os.path.join(_c1d_dir, "suite_zz"), "w",
                     encoding="utf-8") as _fh:
            _fh.write('def _cases(check):\n'
                      '    check("zz1 a defined case", True)\n'
                      '    check("zz2 another, %d" % (3,), True)\n'
                      '    check("a sentence label with no id", True)\n')
        _row = ("lint_a", "x", "drop", "a", None, "suite_zz", "zz1")
        _gone = ("lint_b", "x", "drop", "a", None, "suite_zz", "zz9")
        _glued = ("lint_c", "x", "drop", "a", None, "suite_zz", "zz1a")
        _sub = ("lint_d", "x", "drop", "a", None, "suite_zz",
                substr("a sentence label"))
        _sub_gone = ("lint_e", "x", "drop", "a", None, "suite_zz",
                     substr("no such words"))
        _coarse = ("lint_f", "x", "drop", "a", None, "suite_zz", None)
        _undef = undefined_cases(
            (_row, _gone, _glued, _sub, _sub_gone, _coarse), repo=_c1d_dir)
    finally:
        shutil.rmtree(_c1d_dir, ignore_errors=True)
    check("c1d a gate row naming a case id that no suite defines is refused by "
          "name, while a row naming a defined id is accepted: %r" % (_undef,),
          [u[0] for u in _undef] == ["lint_b", "lint_c", "lint_e"]
          and all(u[2] in ("zz9", "zz1a", "no such words") for u in _undef)
          and all(u[1] == "suite_zz" for u in _undef))

    _undef_tree = undefined_cases(TABLE + ALLOW)
    check("c1e every case a row names is spelled by a check() in the suite the "
          "row runs - the tree's own tables, read against the tree's own "
          "suites: %r" % (_undef_tree,),
          _undef_tree == [])
    _buf = io.StringIO()
    _code = render([], [], undefined=[("lint_b", "suite_zz", "zz9")],
                   stream=_buf)
    check("c1f ...and a row naming an undefined case fails the run BY NAME, "
          "where the same render with no such row exits clean: %r"
          % (_buf.getvalue()[-160:],),
          _code == 1 and "NO SUCH CASE: the row for lint_b names 'zz9'"
          in _buf.getvalue()
          and render([], [], stream=io.StringIO()) == 0)

    # THE RETIRED LINTS, asked of the three places one lives in: the derivation, the
    # red table and the quiet table. The list is this case's data - lints whose
    # measured catch was nothing, deleted with their cases - and it is spelled here
    # because a name that comes back is exactly what it exists to refuse. Asking the
    # DERIVATION and not only the tables is the half that matters: a retired name
    # still defined in a gate module is a lint that would be proven again by the
    # next person to add its row.
    _retired = (
        "rule_drift", "panel_route_violations", "shared_concern_violations",
        "tool_navigability_violations", "tracker_dependency_violations",
        "uncalled_helper_claims", "layer_mention_drift", "agent_doc_drift",
        "schema_inline_drift", "schema_subset_drift", "source_drift",
        "redundant_constants", "phase_id_doc_drift", "absolute_reach_violations",
        "command_reach_violations", "discovery_projection_drift", "doc_link_drift",
        "handbook_drift", "render_target_drift", "signoff_fix_route_drift",
        "sweep_doc_drift", "cr_violations", "declared_asset_drift",
        "exemption_reason_drift", "scratch_isolation", "sweep_roots_drift",
        "revisit_trigger_drift", "removal_helper_drift", "isolation_drift",
        "ui_navigability_violations")
    _held = sorted(set(_retired) & (set(names) | set(r[0] for r in TABLE)
                                    | set(r[0] for r in ALLOW)))
    # ...and the rule that makes retiring a lint a deletion rather than a quiet
    # hole: a lint added to a gate module with no row is named, by name. The
    # fixture is a module holding one unproven lint beside one helper that is no
    # lint, so the answer is the lint and only the lint.
    _fx = tempfile.mkdtemp(prefix="prove-gates-unproven-")
    try:
        with io.open(os.path.join(_fx, "_output.py"), "w", encoding="utf-8") as fh:
            fh.write("def probe_unproven_violations():\n    return []\n\n\n"
                     "def helper(x):\n    return x\n")
        _unproven = coverage(script_dir=_fx)
    finally:
        shutil.rmtree(_fx, ignore_errors=True)
    check("the derived lint table no longer holds a retired name, and a lint left "
          "without a row still fails the sweep by name: retired names still "
          "derived or still carrying a row %r; a fixture lint with no row is "
          "reported as %r" % (_held, _unproven),
          _held == [] and _unproven == ["probe_unproven_violations"])

    # THE SAME FIXTURE ON ANOTHER DRIVE. On the hosted windows runner the temp
    # directory is on one drive and the checkout on another, and a relative path
    # between two drives does not exist: `os.path.relpath` raises ValueError. The
    # derivation once spelled every walked file relative to the REPOSITORY, so the
    # fixture above raised there while the cases were still being built and every
    # case after it went unrun. A posix host has one drive, so the windows answer is
    # injected: for the length of this case `os.path.relpath` raises exactly where
    # windows would - one side inside the fixture, the other outside it - and
    # answers as before everywhere else. `_armed` is asked first - the patched
    # name IS the stub, and the stub refuses the very pair the derivation once
    # built - so a green below cannot come from an injection that never bit. The
    # stub is called by its own name there: spelled through `os.path` with a
    # scratch side and a checkout side, it is the shape `_suite`'s relative-path
    # rule refuses, and that rule reads text, not which function a name is bound to.
    _fx2 = tempfile.mkdtemp(prefix="prove-gates-drive-")
    _real_relpath = os.path.relpath

    def _across_drives(path, start=os.curdir):
        if _under(path, _fx2) != _under(start, _fx2):
            raise ValueError("path is on mount 'C:', start on mount 'D:'")
        return _real_relpath(path, start)

    try:
        with io.open(os.path.join(_fx2, "_output.py"), "w",
                     encoding="utf-8") as fh:
            fh.write("def probe_unproven_violations():\n    return []\n")
        os.path.relpath = _across_drives
        try:
            try:
                _across_drives(os.path.join(_fx2, "_output.py"), REPO)
                _armed = False
            except ValueError:
                _armed = os.path.relpath is _across_drives
            try:
                _crossed = coverage(script_dir=_fx2)
            except ValueError as exc:
                _crossed = "raised ValueError: %s" % (exc,)
        finally:
            os.path.relpath = _real_relpath
    finally:
        shutil.rmtree(_fx2, ignore_errors=True)
    check("c1g ...and that fixture is derived the same when it sits on another "
          "drive than the repository, which is where the windows runner's temp "
          "directory sits: the walk spells each file against the root it walked, "
          "never across to the repository (injection armed: %r; derived %r)"
          % (_armed, _crossed),
          _armed and _crossed == ["probe_unproven_violations"])

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

    # THE BLOCK ANCHOR, PINNED WHERE IT IS USED. A narrowing that lives in
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
          "below meaningless for that row; `_harness.run()` enforces "
          "the other half, for every suite",
          (case_hits(_report, "pn10"), case_hits(_report, "pn11"),
           case_hits(_report, "pn12")) == (2, 1, 0))

    # -- naming a case that has no leading id ----------------------------------
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
          "by one - stated as a measurement rather than as a "
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

    # --- the arm that does not read a name ------------------------------------
    # A lint with a row in neither table and no recorded reason for having neither,
    # because its NAME matched no shape and it was in no list - so `coverage()`
    # could not report it absent and the table went on looking complete. The repair
    # is the derivation and not the name.
    _ng_live = gate_names()
    check("ng0 THE LIVE CLAIM: the derivation reaches a lint whose name says "
          "nothing about what it is, and every row that excuses one says why. "
          "`hand_rolled_runners` is the name this arm exists for, and a version that "
          "lost this arm would drop it silently - `coverage()` cannot report a "
          "lint it never derives: %r" % (not_a_gate_problems(),),
          "hand_rolled_runners" in _ng_live
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

    # `prove()` removes its scratch with the plain call, and the reason
    # recorded beside it is a MEASURED one - every suite a row names removes its own
    # fixtures, so no repository and nothing read-only is left under there - rather
    # than the tempting one about which platform the shell can run on, which was
    # false in both halves. What keeps that record honest is that the rule which
    # WOULD convict a careless removal already reaches this file, and that is
    # asserted here instead of left as prose nobody re-checks.
    from _suite import unsafe_removal_violations   # the tools/ removal rule
    _rf_self = os.path.basename(__file__)
    _rf_walked = [rel for rel, _p in _output.py_files(os.path.join(REPO, "tools"))]
    _rf_findings = [rel for rel, _p in unsafe_removal_violations()]
    check("rf3 the removal rule REACHES this file and finds nothing in it - the "
          "premise the plain removal in `prove()` is recorded on. Both halves are "
          "needed: reaching it is what makes the silence mean something, and a "
          "file outside the walk would be silent for the other reason: %r / %r"
          % (_rf_self in _rf_walked, _rf_findings),
          _rf_self in _rf_walked and _rf_self not in _rf_findings)

    # -- the ALLOW half, checked the same way and for the same reason -----------
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
    _derived = ([S + m.replace(os.sep, "/") for m in _GATE_MODULES]
                + [L + m for m in _GATE_LINT_MODULES])
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
    # (it shells out to redfirst.sh), so the checkable statement is that `_cases`
    # never calls it. The one case that does, `pw8`, hands it a recording runner
    # and a scratch tree, so no child starts and nothing outside the scratch moves.
    _c6_tree = ast.parse(_read_source(__file__))
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
          "in main() and `_cases` never calls `prove()`: %r" % (_c6_calls,),
          len(_c6_fns) == 1 and _c6_calls == [])
    _changed_cases(check)
    _worker_cases(check)


def _changed_run(argv, survives=()):
    """`(code, printed, proved, holds)` of `main(argv)` with the expensive half
    replaced: `prove` answers RED for every row - STAYED GREEN for a row whose
    lint is in `survives` - and records which row it was handed; the worker pool
    is a recorder too (`holds`, one entry per pool opened), so a case here never
    registers a worktree with this checkout. The marker a run once held is
    recorded as well, so a case can say it is no longer taken."""
    import _suite
    import threading
    proved, holds, marked = [], [], []
    lock = threading.Lock()

    def fake_prove(row, repo=None, run=None):
        with lock:
            proved.append(row)
        if row[0] in survives:
            return {"lint": row[0], "verdict": "STAYED GREEN",
                    "detail": "the gate asserts nothing about this", "cases": []}
        return {"lint": row[0], "verdict": "RED", "detail": "x1", "cases": ["x1"]}

    def fake_open(repo, count):
        holds.append(count)
        return {"root": None, "trees": ["fake-tree-%d" % (i,)
                                        for i in range(max(1, count))]}
    fakes = {"prove": fake_prove, "open_workers": fake_open,
             "close_workers": lambda repo, pool: [],
             "reap_stale": lambda repo, alive=None: ([], [])}
    real = dict((n, globals()[n]) for n in fakes)
    real_hold, real_out = _suite.hold, sys.stdout
    globals().update(fakes)
    _suite.hold = lambda git_dir, pid=None: marked.append(git_dir)
    buf = io.StringIO()
    sys.stdout = buf
    try:
        code = main(argv)
    finally:
        sys.stdout = real_out
        globals().update(real)
        _suite.hold = real_hold
    return code, buf.getvalue(), proved, holds + marked


def _rendered_order(text):
    """The lint names of the rendered row lines, top to bottom."""
    return re.findall(r"^  (\S+) +RED\b", text, re.M)


def _text_homes(names, repo=None):
    """`{lint: [files holding "def <lint>(" at column 0]}` over `plugins/` and
    `tools/`, read as TEXT. Deliberately not the walk `changed_rows` reads, so the
    cases below compare two readings of where a lint lives instead of one reading
    with itself."""
    root = repo or REPO
    want = set(names)
    homes = {}
    for top in ("plugins", "tools"):
        for dirpath, dirs, files in os.walk(os.path.join(root, top)):
            dirs[:] = sorted(d for d in dirs
                             if d not in ("__pycache__", "node_modules"))
            for name in sorted(f for f in files if f.endswith(".py")):
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                for hit in re.findall(r"^def ([A-Za-z_]\w*)\(", text, re.M):
                    if hit in want:
                        homes.setdefault(hit, []).append(rel)
    return homes


def _rows_touched(rows, paths, homes):
    """The rows a change to `paths` owes a re-proof: the lint's home, the file the
    row mutates, or the suite holding the case that must go red."""
    want = set(p[2:] if p.startswith("./") else p for p in paths)
    return [r for r in rows if r[1] in want or r[5] in want
            or any(h in want for h in homes.get(r[0], ()))]


def _changed_cases(check):
    """`--changed <paths>`: the rows a change to those paths owes a re-proof -
    by the lint's home, the file a row mutates, or the suite holding its case -
    both directions, and nothing for a set that names no such file, said aloud."""
    both = sorted(set(r[1] for r in TABLE) & set(r[1] for r in ALLOW))
    lint_file = both[0] if both else ""
    homes = _text_homes(set(r[0] for r in TABLE + ALLOW))
    red_rows = _rows_touched(TABLE, [lint_file], homes)
    allow_rows = _rows_touched(ALLOW, [lint_file], homes)
    pick = globals().get("changed_rows")
    derived = lint_homes()
    # A lint whose every red row mutates some OTHER file than the one defining
    # it: the shape a selection by mutated file alone re-proves nothing for.
    away = sorted(n for n, h in homes.items()
                  if len(h) == 1 and any(r[0] == n for r in TABLE)
                  and all(r[1] != h[0] for r in TABLE if r[0] == n))
    sets = ([lint_file, "README.md"], [], ["./" + lint_file],
            [homes.get("house_style_violations", [""])[0]], [OUTL])
    # The home-only set goes through the default derivation - the one set whose
    # answer changes if that default reads no homes - and the rest through one
    # derivation handed in: a walk of the tree is seconds, not a lookup.
    got = ([pick(TABLE, s) if i == 3 else pick(TABLE, s, derived)
            for i, s in enumerate(sets)] if pick else None)
    want = [_rows_touched(TABLE, s, homes) for s in sets]
    check("ch1 changed_rows keeps EXACTLY the rows a changed path touches - a "
          "lint's home, the file a row mutates, the suite holding its case - a "
          "`./` spelling included, and an empty set keeps none. Exact, so a "
          "selection widened to every row is red here: %r"
          % ([(len(g), len(w)) for g, w in zip(got, want)] if got
             else "no changed_rows",),
          bool(red_rows) and got is not None and got == want
          and got[1] == [] and all(len(g) < len(TABLE) for g in got))

    lost = {}
    for name in away:
        home = homes[name][0]
        for rows in (TABLE, ALLOW):
            mine = [r for r in rows if r[0] == name]
            kept = pick(rows, [home], derived) if pick else []
            if [r for r in mine if r not in kept]:
                lost[name] = home
    home = homes.get("house_style_violations", [""])[0]
    code, said, proved, _h = _changed_run(["--changed", home])
    mine = [r for r in TABLE + ALLOW if r[0] == "house_style_violations"]
    check("ch5 --changed names a lint's rows when only the lint's OWN file "
          "changed, though every red row of it mutates another file - %d such "
          "lints, house_style_violations among them, and main() given only its "
          "home proves every row of it in both directions; lints whose rows the "
          "home file left out: %r; main: %r"
          % (len(away), sorted(lost.items())[:6],
             (code, len([r for r in mine if r in proved]), len(mine))),
          pick is not None and "house_style_violations" in away
          and lost == {} and code == 0 and bool(mine)
          and all(r in proved for r in mine))

    suites = sorted(set(r[5] for r in TABLE + ALLOW))
    apart = [r for r in TABLE
             if r[5] != r[1] and r[5] not in homes.get(r[0], ())]
    missed = []
    for suite in suites:
        for rows in (TABLE, ALLOW):
            kept = pick(rows, [suite], derived) if pick else []
            missed.extend("%s -> %s" % (suite, r[0]) for r in rows
                          if r[5] == suite and r not in kept)
    check("ch6 --changed names a lint's rows when only its GUARDING SUITE "
          "changed - the file holding the case a row needs red, which is "
          "neither the lint's home nor the mutated file for %d red rows; rows "
          "their suite left out: %r" % (len(apart), sorted(set(missed))[:6]),
          pick is not None and bool(apart) and missed == [])

    code, said, proved, holds = _changed_run(["--changed", lint_file,
                                              "README.md"])
    check("ch2 --changed with a lint's file proves the rows it touches in BOTH "
          "directions and no other row, opens one worker pool and holds no "
          "marker, and renders its red rows, then its allow rows, in the "
          "table's order whatever order they ran in: "
          "%r" % ((code, len(proved), len(red_rows), len(allow_rows),
                               said[-200:]),),
          code == 0 and bool(allow_rows)
          and sorted(proved, key=repr) == sorted(red_rows + allow_rows, key=repr)
          and len(holds) == 1 and "go RED" in said and "stay QUIET" in said
          and _rendered_order(said) == [r[0] for r in red_rows + allow_rows])

    runs = [_changed_run(argv) for argv in (["--changed"],
                                            ["--changed", "README.md"],
                                            ["--changed", "README.md", "--red"])]
    check("ch3 an empty set, or one naming no file any row is touched by, runs "
          "NO row, opens no worker tree, holds no marker, exits 0 and SAYS it ran none - it never "
          "reads as a proof of everything: %r"
          % ([(c, len(p), len(h), s.strip()[-120:]) for c, s, p, h in runs],),
          all(c == 0 and p == [] and h == [] and "ran none" in s
              for c, s, p, h in runs))

    victim = red_rows[0][0] if red_rows else None
    code, said, proved, _h = _changed_run(["--changed", lint_file],
                                          survives=(victim,))
    named = [ln.strip() for ln in said.splitlines()
             if ln.strip().startswith("ROW NOT PROVEN")]
    check("ch4 a surviving mutation exits 1 and names the row: one ROW NOT "
          "PROVEN line per row of that lint, each naming its direction and the "
          "lint, and no line for a row that went red: %r" % ((code, named),),
          code == 1 and victim is not None and bool(named)
          and all(victim in ln for ln in named)
          and any(ln.startswith("ROW NOT PROVEN: red ") for ln in named)
          and len(named) == len([r for r in red_rows + allow_rows
                                 if r[0] == victim]))


def _fixture_git(repo, *args):
    """`(code, stdout)` of git in a scratch fixture - never this checkout. The
    identity is passed per call because the sweep hands a suite none."""
    proc = subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false"] + list(args),
        cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _fixture_repo():
    """A scratch repository whose working tree differs from HEAD in every way a
    worker must mirror or must not: a modified tracked file, a staged one, a
    deleted one, an untracked one (a space in its name), an ignored one, and a
    new file that is staged but was never committed."""
    repo = tempfile.mkdtemp(prefix="prove-gates-fixture-")
    files = {"a.txt": "old\n", "s.txt": "old\n", "gone.txt": "here\n",
             ".gitignore": "ign.txt\n"}
    for name, body in files.items():
        with io.open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        code, out = _fixture_git(repo, *args)
        if code != 0:
            raise RuntimeError("fixture git %r: %s" % (args, out))
    for name, body in (("a.txt", "new\n"), ("s.txt", "staged\n"),
                       ("b file.txt", "fresh\n"), ("ign.txt", "ignored\n"),
                       ("n.txt", "added\n")):
        with io.open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    os.remove(os.path.join(repo, "gone.txt"))
    _fixture_git(repo, "add", "s.txt", "n.txt")
    return repo


def _read_or_none(path):
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def _registered(repo):
    """The worktree paths git has registered for `repo`, the main one excluded."""
    code, out = _fixture_git(repo, "worktree", "list", "--porcelain")
    main = os.path.realpath(repo)
    return [ln[len("worktree "):] for ln in out.splitlines()
            if ln.startswith("worktree ")
            and os.path.realpath(ln[len("worktree "):]) != main]


def _worker_cases(check):
    """The parallel half: rows run in worker trees, never in the live checkout.
    Every git here runs in a scratch fixture; `prove()` is reached only by `pw8`,
    through a recording runner that starts nothing."""
    import threading
    import time
    import _loader

    # Inverse sleeps, so the order rows FINISH in is the reverse of the order
    # they were handed in: a collector keyed on completion is red here.
    done, live, peak = [], [0], [0]
    lock = threading.Lock()

    def work(item):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.03 * (6 - item))
        with lock:
            live[0] -= 1
            done.append(item)
        return item * 10
    runner = globals().get("run_ordered")
    got = runner(list(range(6)), work, 6) if runner else None
    check("pw1 rows run concurrently and their results come back in the TABLE's "
          "order whatever order they finish in, so the rendered output is "
          "byte-stable under any scheduling: results %r, finished %r, peak %d"
          % (got, done, peak[0]),
          got == [0, 10, 20, 30, 40, 50] and done != sorted(done) and peak[0] > 1)

    size = globals().get("pool_size")
    sweep_rule = _loader.load(os.path.join(_here, "sweep-selftests.py")).default_jobs
    grid = [(rows, cpus, env) for rows in (0, 1, 3, 200) for cpus in (1, 2, 3, 10)
            for env in ({}, {"CI": "true"}, {"CI": "false"})]
    wrong = [(r, c, e, size(r, c, e) if size else None,
              min(r, sweep_rule(c, e))) for r, c, e in grid
             if not size or size(r, c, e) != min(r, sweep_rule(c, e))]
    check("pw2 the worker count is the sweep's own rule - all cores but two, "
          "every core under CI=true, never below one - capped at the rows there "
          "are, and none for no rows: %r" % (wrong[:4],),
          size is not None and wrong == [] and size(200, 10, {}) == 8
          and size(200, 10, {"CI": "true"}) == 10 and size(0, 10, {}) == 0)

    opener, closer = globals().get("open_workers"), globals().get("close_workers")
    reaper = globals().get("reap_stale")
    repo = _fixture_repo()
    pool, killed, alias = None, None, None
    try:
        _c, before = _fixture_git(repo, "status", "--porcelain")
        pool = opener(repo, 2) if opener else None
        trees = pool["trees"] if pool else []
        seen = dict((name, [_read_or_none(os.path.join(t, name)) for t in trees])
                    for name in ("a.txt", "s.txt", "b file.txt", "ign.txt",
                                 "gone.txt", "n.txt"))
        indexed = [_fixture_git(t, "ls-files", "--error-unmatch", "n.txt")[0] == 0
                   for t in trees]
        outside = all(not (os.path.realpath(t) + os.sep).startswith(
            os.path.realpath(repo) + os.sep) for t in trees)
        check("pw3 worker tree mirrors a dirty tracked file and an untracked file "
              "- the modified and the staged tracked file carry the working "
              "tree's bytes, the untracked file is there, the deleted file is "
              "not, the ignored file is not, a staged new file is there AND in "
              "the worker's index, and every tree sits outside the checkout: "
              "%r, staged-new indexed %r" % (seen, indexed),
              len(trees) == 2 and outside
              and seen["a.txt"] == ["new\n"] * 2
              and seen["s.txt"] == ["staged\n"] * 2
              and seen["b file.txt"] == ["fresh\n"] * 2
              and seen["ign.txt"] == [None] * 2
              and seen["gone.txt"] == [None] * 2
              and seen["n.txt"] == ["added\n"] * 2 and indexed == [True] * 2)
        problems = closer(repo, pool) if (closer and pool) else ["no close_workers"]
        left = _registered(repo)
        root_gone = bool(pool) and not os.path.exists(pool["root"])
        _c, after = _fixture_git(repo, "status", "--porcelain")
        status_kept = before == after
        check("pw4 closing the pool leaves no registered worktree and no scratch "
              "directory, and the checkout's status is what it was before the "
              "pool opened: problems %r, registered %r, root gone %r, status "
              "kept %r" % (problems, left, root_gone, status_kept),
              problems == [] and left == [] and root_gone and status_kept)

        # A run that is killed never reaches its `finally`. The pool it leaves is
        # found by its owner marker and taken down by the next run - and only when
        # its owner is gone, which is the half that keeps a CONCURRENT run's pool.
        # Its registration is respelled first: git lists a tree as its record
        # spells it, which on Windows is never the spelling `open_workers` holds
        # (forward slashes, a long name for the temp root's short one), so the
        # roots the reaper reports are judged against the run's own spelling.
        killed = opener(repo, 1) if opener else None
        alias = tempfile.mkdtemp(prefix="prove-gates-alias-")
        respelled = _respell_registration(killed["trees"][0], alias) \
            if killed else None
        spared = reaper(repo, alive=lambda pid: True) if reaper else None
        still = _registered(repo)
        reaped = reaper(repo, alive=lambda pid: False) if reaper else None
        after_reap = _registered(repo)
        # Where the platform will not make the link, the registration keeps
        # git's own record and the second spelling goes unexercised here. That
        # narrowing is printed in the case's own line, so a log shows which
        # spelling a pass covered rather than reading the same either way,
        # and the case asserts the spelling it did exercise: the one registration
        # git lists is the pool's own worker tree, read canonically.
        exercised = ("a second spelling, through a link" if respelled else
                     "git's own record only - this platform would not make the "
                     "link, so the second spelling was NOT exercised")
        check("pw5 a killed run's pool is reaped by the next run - registration "
              "and scratch both - only when its owner process is gone; a live "
              "owner's pool is left alone; and the root it reports is the one "
              "the run opened, however git spells the registration (spelling "
              "exercised: %s): listed as "
              "%r, spared %r (%d registered), reaped %r against %r (%r "
              "registered, root gone %r)"
              % (exercised, respelled, spared, len(still), reaped,
                 killed["root"] if killed else None, after_reap,
                 bool(killed) and not os.path.exists(killed["root"])),
              killed is not None and spared == ([], []) and len(still) == 1
              and (still == [respelled]
                   or (respelled is None and os.name == "nt"
                       and len(still) == 1 and killed is not None
                       and _canonical_path(still[0])
                       == _canonical_path(killed["trees"][0])))
              and reaped == ([killed["root"]], []) and after_reap == []
              and not os.path.exists(killed["root"]))
    finally:
        for wt in _registered(repo):
            _fixture_git(repo, "worktree", "remove", "--force", wt)
        for p in [x["root"] for x in (pool, killed) if x]:
            _output.remove_tree(p)
        if alias:
            _output.remove_tree(alias)
        _output.remove_tree(repo)
    _foreign_cases(check, opener, closer, reaper)
    _spelling_cases(check)
    _owner_probe_cases(check)


def _respell_registration(tree, scratch):
    """Rewrite git's record of the worker tree `tree` so `git worktree list`
    prints it through a link in `scratch` to its pool's parent: one directory
    under a second spelling, which is what git's forward slashes and an 8.3
    short name are on Windows. Returns the spelling git now prints, or None when
    this platform will not make the link (Windows without the privilege), where
    git's own forward slashes are already a second spelling."""
    link = os.path.join(scratch, "via")
    try:
        os.symlink(os.path.dirname(os.path.dirname(tree)), link)
    except (OSError, NotImplementedError, AttributeError):
        return None
    code, admin = _fixture_git(tree, "rev-parse", "--absolute-git-dir")
    if code != 0:
        raise RuntimeError("fixture rev-parse in %s: %s" % (tree, admin))
    respelled = os.path.join(link, os.path.basename(os.path.dirname(tree)),
                             os.path.basename(tree)).replace("\\", "/")
    with io.open(os.path.join(admin.strip(), "gitdir"), "w",
                 encoding="utf-8") as fh:
        fh.write(u"%s/.git\n" % (respelled,))
    return respelled


def _spelling_cases(check):
    """Windows spells one directory several ways - git's forward slashes, the
    native backslashes, an 8.3 short name beside the long one, either case - and
    every comparison the pool makes of a tree, a pool root and an admin gitdir
    must read them as one. Driven on every platform: `ntpath` stands in for the
    Windows path module, and the injected resolver models what Windows'
    `realpath` adds to it, the long name for a short one."""
    import ntpath
    canon = globals().get("_canonical_path")
    under = globals().get("_under")
    admin_of = globals().get("_admin_of")
    temp = "C:\\Users\\runneradmin\\AppData\\Local\\Temp\\sw-q"
    short = "C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\sw-q"
    root = temp + "\\prove-gates-pool-ab"
    git_tree = (temp + "\\prove-gates-pool-ab\\w0").replace("\\", "/")
    short_tree = short + "\\prove-gates-pool-ab\\w0"
    sibling = temp + "\\prove-gates-pool-ab-other\\w0"
    foreign = short + "\\prove-gates-foreign-q\\foreign"

    def as_windows(path):
        return ntpath.normcase(ntpath.normpath(path)).replace("runner~1",
                                                              "runneradmin")
    try:
        folded = (canon(git_tree, ntpath), canon(root.upper() + "\\w0", ntpath))
        inside = [under(t, r, as_windows) for t, r in (
            (git_tree, root), (short_tree, root), (short_tree, root.upper()),
            (git_tree, short + "\\prove-gates-pool-ab"))]
        outside = [under(t, root, as_windows) for t in (sibling, foreign)]
        gitdirs = [("foreign", foreign.replace("\\", "/") + "/.git"),
                   ("w0", short_tree.replace("\\", "/") + "/.git")]
        named = (admin_of(gitdirs, git_tree, as_windows),
                 admin_of(gitdirs, root.upper() + "\\W0", as_windows),
                 admin_of(gitdirs, sibling, as_windows))
    except TypeError as exc:
        folded = inside = outside = named = "not injectable: %s" % (exc,)
    check("pw14 one Windows directory under every spelling it is given - git's "
          "forward slashes, native backslashes, the 8.3 short name, either case "
          "- is one directory to the pool: the canonical spelling folds slash "
          "and case %r, each spelling of a pool tree is under each spelling of "
          "its root %r, a sibling sharing the root's prefix and a foreign tree "
          "are not %r, and the admin directory found for a tree is the one "
          "whose gitdir names it under any spelling, none for a sibling %r"
          % (folded, inside, outside, named),
          canon is not None and under is not None and admin_of is not None
          and isinstance(folded, tuple) and folded[0] == folded[1]
          and folded[0] == root.lower() + "\\w0"
          and inside == [True] * 4 and outside == [False, False]
          and named == ("w0", "w0", None))


def _owner_probe_cases(check):
    """The reaper's own liveness probe, not an injected one: a pool owned by this
    process - alive by construction - stands, and one whose owner file names a
    process that has exited is reaped. On Windows this is the OpenProcess probe
    answering about a real pid; an injected `alive` cannot test that."""
    repo = _fixture_repo()
    pools = []
    try:
        live = open_workers(repo, 1)
        pools.append(live)
        dead = open_workers(repo, 1)
        pools.append(dead)
        child = subprocess.run([sys.executable, "-c",
                                "import os; print(os.getpid())"],
                               stdout=subprocess.PIPE)
        gone = int(child.stdout.decode("ascii").strip())
        import json
        with io.open(os.path.join(dead["root"], POOL_OWNER), "w",
                     encoding="utf-8") as fh:
            fh.write(u"%s\n" % json.dumps({"pid": gone, "repo": repo}))
        reaped = reap_stale(repo)
        standing = os.path.isdir(live["root"]) and os.path.isdir(live["trees"][0])
        check("pw15 with the platform's own probe a pool owned by a live process "
              "stands and one whose owner exited is reaped, reported as the root "
              "the run opened: reaped %r, want %r, live pool standing %r"
              % (reaped, ([dead["root"]], []), standing),
              reaped == ([dead["root"]], []) and standing)
    finally:
        for wt in _registered(repo):
            _fixture_git(repo, "worktree", "remove", "--force", wt)
        for p in [x["root"] for x in pools if x]:
            _output.remove_tree(p)
        _output.remove_tree(repo)


def _foreign_worktree(repo):
    """A worktree of `repo` that is not the pool's, with a provenance file in its
    admin directory, whose directory is then deleted by hand - the state a global
    `git worktree prune` erases. Returns `(path, admin_dir, scratch_parent)`."""
    parent = tempfile.mkdtemp(prefix="prove-gates-foreign-")
    path = os.path.join(parent, "foreign")
    code, out = _fixture_git(repo, "worktree", "add", "-q", "-b", "foreign", path)
    if code != 0:
        raise RuntimeError("fixture worktree add: %s" % out)
    _c, admin = _fixture_git(path, "rev-parse", "--absolute-git-dir")
    admin = admin.strip()
    with io.open(os.path.join(admin, "audit-worktree.json"), "w",
                 encoding="utf-8") as fh:
        fh.write("{}\n")
    _output.remove_tree(path)
    return path, admin, parent


def _foreign_cases(check, opener, closer, reaper):
    """Reaping and closing touch only the pool's own registrations: a worktree
    somebody else made, even one whose directory is gone, stays registered with
    its provenance, and a pid whose liveness is unknown keeps its pool."""
    repo = _fixture_repo()
    parent, pools = None, []
    try:
        foreign, admin, parent = _foreign_worktree(repo)
        mine = os.path.realpath(foreign)
        killed = opener(repo, 1) if opener else None
        pools.append(killed)
        reaped = reaper(repo, alive=lambda pid: False) if reaper else None
        after_reap = [p for p in _registered(repo) if os.path.realpath(p) == mine]
        pool = opener(repo, 1) if opener else None
        pools.append(pool)
        problems = closer(repo, pool) if (closer and pool) else ["no close_workers"]
        after_close = [p for p in _registered(repo) if os.path.realpath(p) == mine]
        kept = os.path.isfile(os.path.join(admin, "audit-worktree.json"))
        check("pw6 reaping removes only the pool's own worktree entries and leaves "
              "a foreign worktree registered - a foreign tree whose directory was "
              "deleted is still listed, provenance and all, after a dead owner's "
              "pool is reaped and after a pool is closed, while both pools are "
              "gone: reaped %r, foreign after reap %r, close problems %r, foreign "
              "after close %r, provenance kept %r, pool registrations left %r"
              % (reaped, after_reap, problems, after_close, kept,
                 [p for p in _registered(repo) if os.path.realpath(p) != mine]),
              bool(killed) and reaped == ([killed["root"]], []) and len(after_reap) == 1
              and problems == [] and len(after_close) == 1 and kept
              and [p for p in _registered(repo) if os.path.realpath(p) != mine] == [])

        # Unknown is not dead: a pid the platform cannot answer about may be a
        # concurrent run's, and taking its pool down breaks that run mid-row.
        unknown = opener(repo, 1) if opener else None
        pools.append(unknown)
        spared = reaper(repo, alive=lambda pid: None) if reaper else None
        standing = bool(unknown) and os.path.isdir(unknown["root"])
        check("pw7 an owner pid whose liveness is unknown keeps its pool - only an "
              "explicit not-alive reaps: reaped %r, root standing %r"
              % (spared, standing),
              unknown is not None and spared == ([], []) and standing)
        close_workers(repo, unknown)

        # A pool whose whole root was deleted (a temp cleaner) has no owner file
        # left to ask, and no run can be using it: its registrations go, by name.
        # The by-name removal is also driven directly, for the git that refuses
        # `worktree remove` on a missing directory: it drops a pool tree's admin
        # directory, and refuses a path outside the pool root it is handed.
        gone = opener(repo, 1) if opener else None
        pools.append(gone)
        if gone:
            _output.remove_tree(gone["root"])
        reaped_gone = reaper(repo, alive=lambda pid: True) if reaper else None
        direct = opener(repo, 1) if opener else None
        pools.append(direct)
        dropper = globals().get("_drop_registration")
        refused = dropped = "no _drop_registration"
        if dropper and direct:
            refused = dropper(repo, foreign, direct["root"])
            _output.remove_tree(direct["trees"][0])
            dropped = dropper(repo, direct["trees"][0], direct["root"])
        left = [os.path.realpath(p) for p in _registered(repo)]
        check("pw13 a pool whose root is gone is unregistered by the next run, and "
              "the by-name removal drops a pool tree's own admin directory while "
              "refusing a path outside the pool - the foreign tree stays: reaped "
              "%r, refused %r, dropped %r, registered %r"
              % (reaped_gone, refused, dropped, left),
              bool(gone) and reaped_gone == ([gone["root"]], [])
              and bool(refused) and "not under the pool root" in refused
              and dropped is None and left == [mine]
              and os.path.isfile(os.path.join(admin, "audit-worktree.json")))
    finally:
        for wt in _registered(repo):
            _fixture_git(repo, "worktree", "remove", "--force", wt)
        for p in [x["root"] for x in pools if x]:
            _output.remove_tree(p)
        for p in (parent, repo):
            if p:
                _output.remove_tree(p)
    _isolation_cases(check)
    _teardown_cases(check)


def _isolation_cases(check):
    """What one row's child is handed - argv, working directory, environment -
    read off `prove()` itself through a recording runner, in a scratch tree, so
    nothing is mutated and nothing is started. A real run would also pass with
    the child in the checkout: the suite it names is there too."""
    tree = tempfile.mkdtemp(prefix="prove-gates-isolation-")
    calls = []
    try:
        with io.open(os.path.join(tree, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write(u"anchor line\n")
        # Assembled, not written whole: a whole name here reads to the tools/
        # basename lint as a reference to a suite that does not exist.
        suite = "tests/test_probe" + ".py"
        row = ("probe_lint", "f.txt", "replace", "anchor line", "mutated line",
               suite, "c1 probe")
        base = {"PATH": os.environ.get("PATH", ""), "CLAUDE_PROJECT_DIR": REPO,
                "PWD": REPO, "GIT_DIR": os.path.join(REPO, ".git"),
                "GIT_WORK_TREE": REPO, "GIT_INDEX_FILE": os.path.join(REPO, "idx")}
        import types
        done = types.SimpleNamespace(stdout=b"REDFIRST ok\n", returncode=0)

        def record(argv, **kw):
            calls.append(dict(kw, argv=list(argv),
                              scratch_seen=os.path.isdir(kw.get("env", {})
                                                         .get("TMPDIR", ""))))
            return done

        def leave_mutated(argv, **kw):
            with io.open(os.path.join(tree, "f.txt"), "w", encoding="utf-8") as fh:
                fh.write(u"mutated line\n")
            return done
        try:
            prove(row, tree, run=record, base=base)
            left = prove(row, tree, run=leave_mutated, base=base)
        except TypeError as exc:      # a prove() that takes no runner pins nothing
            left = {"verdict": "no injectable runner: %s" % (exc,)}
        call = calls[0] if calls else {}
        env = call.get("env") or {}
        argv = call.get("argv") or []
        scratch = env.get("TMPDIR", "")
        mine = os.path.realpath(tree)
        wrong = [k for k, ok in (
            ("cwd is the worker tree", os.path.realpath(call.get("cwd") or "") == mine),
            ("argv runs redfirst on the row's file, allowing a dirty tree, then the "
             "row's suite", argv[:7] == ["sh", "tools/redfirst.sh", "f.txt",
                                         "--replace", "anchor line", "mutated line",
                                         "--allow-dirty"]
             and argv[-4:] == ["--", sys.executable, suite, "--selftest"]),
            ("CLAUDE_PROJECT_DIR and PWD repointed at the tree",
             env.get("CLAUDE_PROJECT_DIR") == tree and env.get("PWD") == tree),
            ("git's location variables dropped",
             not [v for v in _GIT_LOCATION_VARS if v in env]),
            ("every temp root is one scratch outside tree and checkout, gone after",
             bool(scratch) and all(env.get(v) == scratch for v in _TEMP_VARS)
             and call.get("scratch_seen") and not os.path.exists(scratch)
             and not os.path.realpath(scratch).startswith(mine + os.sep)
             and not os.path.realpath(scratch).startswith(
                 os.path.realpath(REPO) + os.sep))) if not ok]
        restored = _read_or_none(os.path.join(tree, "f.txt"))
        check("pw8 a row's child runs in its worker tree and nowhere else - cwd "
              "the tree, redfirst told --allow-dirty, CLAUDE_PROJECT_DIR and PWD "
              "pointed at the tree, git's location variables gone, temp roots one "
              "scratch - and a row that leaves its mutation behind is an ERROR "
              "with the file put back from its pre-row bytes: wrong %r, left %r, "
              "file now %r" % (wrong, left.get("verdict"), restored),
              len(calls) == 1 and wrong == [] and left.get("verdict") == "ERROR"
              and "left f.txt mutated" in (left.get("detail") or "")
              and restored == "anchor line\n")
    finally:
        _output.remove_tree(tree)


def _teardown_cases(check):
    """How a run ends when it does not end normally: an interrupt cancels the
    queue, a nested repository is named rather than silently left out, a pool
    that cannot be reaped is a refusal, and a SIGTERM still reaches `finally`."""
    import threading
    import time
    started = []
    lock = threading.Lock()

    def work(item):
        with lock:
            started.append(item)
        time.sleep(0.05)
        if item == 0:
            raise KeyboardInterrupt
        return item
    raised = None
    try:
        run_ordered(list(range(6)), work, 1)
    except KeyboardInterrupt:
        raised = "KeyboardInterrupt"
    time.sleep(0.2)            # anything not cancelled would have started by now
    check("pw9 an interrupt in the queue cancels the rows not yet started rather "
          "than waiting all of them out: raised %r, started %r"
          % (raised, started),
          raised == "KeyboardInterrupt" and 1 <= len(started) <= 2)

    repo = _fixture_repo()
    pool = None
    try:
        nested = os.path.join(repo, "vendor")
        os.makedirs(nested)
        _fixture_git(nested, "init", "-q")
        with io.open(os.path.join(nested, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write(u"x = 1\n")
        pool = open_workers(repo, 1)
        carried = os.path.exists(os.path.join(pool["trees"][0], "vendor", "f.txt"))
        check("pw10 an untracked nested repository is reported as not carried, "
              "not dropped in silence: skipped %r, carried %r"
              % (pool.get("skipped"), carried),
              pool.get("skipped") == ["vendor/"] and not carried)
    finally:
        if pool:
            close_workers(repo, pool)
        _output.remove_tree(repo)

    not_a_repo = tempfile.mkdtemp(prefix="prove-gates-norepo-")
    try:
        try:
            got = ("returned", reap_stale(not_a_repo))
        except RuntimeError as exc:
            got = ("raised", str(exc)[:60])
    finally:
        _output.remove_tree(not_a_repo)
    opened = []

    def no_reap(repo, alive=None):
        raise RuntimeError("git worktree list: fixture refusal")
    fakes = {"reap_stale": no_reap,
             "open_workers": lambda repo, count: opened.append(count)}
    real = dict((n, globals()[n]) for n in fakes)
    real_err = sys.stderr
    buf = io.StringIO()
    globals().update(fakes)
    sys.stderr = buf
    try:
        code = main(["--only", "house_style_violations", "--red"])
    except Exception as exc:          # a traceback is exit 1: not a refusal
        code = "raised %s" % (type(exc).__name__,)
    finally:
        sys.stderr = real_err
        globals().update(real)
    check("pw11 a run that cannot list the worktrees to reap refuses with exit 2 "
          "and opens no pool - exit 1 would read as a lint not proven: reap on a "
          "non-repository %r, main %r, opened %r, said %r"
          % (got, code, opened, buf.getvalue().strip()[:80]),
          got[0] == "raised" and code == 2 and opened == []
          and "no row ran" in buf.getvalue())

    # A stale pool whose take-down fails is still there, so it is not reported
    # as taken down: the reaper names it beside its problem, and a run whose
    # reap left one refuses before it opens a pool of its own. The real pools
    # reaped in pw5, pw6, pw13 and pw15 are the other direction - each asserts
    # an empty `left`, which a reaper reporting every pool as stuck turns red.
    repo = _fixture_repo()
    stuck, stuck_got, stuck_standing = None, None, None
    real_close = close_workers
    try:
        stuck = open_workers(repo, 1)
        globals()["close_workers"] = lambda r, pool: [
            "fixture: could not delete %s" % (pool["root"],)]
        try:
            stuck_got = reap_stale(repo, alive=lambda pid: False)
        finally:
            globals()["close_workers"] = real_close
        stuck_standing = os.path.isdir(stuck["root"])
    finally:
        if stuck:
            close_workers(repo, stuck)
        _output.remove_tree(repo)
    stuck_opened = []
    stuck_fakes = {
        "reap_stale": lambda repo, alive=None: (
            [], [("/scratch/prove-gates-pool-stuck", "fixture: could not delete")]),
        "open_workers": lambda repo, count: stuck_opened.append(count)}
    real = dict((n, globals()[n]) for n in stuck_fakes)
    buf = io.StringIO()
    globals().update(stuck_fakes)
    sys.stderr = buf
    try:
        stuck_code = main(["--only", "house_style_violations", "--red"])
    except Exception as exc:          # a traceback is exit 1: not a refusal
        stuck_code = "raised %s" % (type(exc).__name__,)
    finally:
        sys.stderr = real_err
        globals().update(real)
    stuck_said = buf.getvalue()
    check("pw16 a stale pool the reaper could not take down is reported as left "
          "beside its problem and never as taken down, and a run whose reap "
          "left one refuses with exit 2, naming it, and opens no pool: reaped "
          "%r (pool standing %r), main %r, opened %r, said %r"
          % (stuck_got, stuck_standing, stuck_code, stuck_opened,
             stuck_said.strip()[:120]),
          bool(stuck) and stuck_got is not None and stuck_got[0] == []
          and [r for r, _p in stuck_got[1]] == [stuck["root"]]
          and "fixture: could not delete" in stuck_got[1][0][1]
          and stuck_standing is True
          and stuck_code == 2 and stuck_opened == []
          and "could not take down /scratch/prove-gates-pool-stuck" in stuck_said
          and "took down" not in stuck_said)
    _stop_cases(check)


# How long the slow row's child would sleep if nothing stopped it. Not a bound
# the case reads: the verdict is HOW the child ended (a signal or a kill, not its
# own exit 0), so a slow runner cannot pass or fail it. The figure only sets what
# a run that does not stop its rows costs before it goes red.
_SLOW_ROW_SECONDS = 30


def _stop_cases(check):
    """An exit reaching `_proved` stops the rows running at that moment instead
    of waiting them out, and starts no row's child after it. Driven through
    `_proved` itself, with `prove` swapped for one that starts a real child
    through the runner it is handed, so the wiring is what is judged."""
    import threading
    scratch = tempfile.mkdtemp(prefix="prove-gates-stop-")
    marker = os.path.join(scratch, "slow-started")
    ended, raised = {}, None

    def fake_prove(row, repo=None, run=None):
        if row[0] == "slow":
            proc = run([sys.executable, "-c",
                        "import sys, time\n"
                        "open(sys.argv[1], 'w').close()\n"
                        "time.sleep(float(sys.argv[2]))\n",
                        marker, str(_SLOW_ROW_SECONDS)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            ended["slow"] = proc.returncode
            return {"lint": "slow", "verdict": "PROVEN", "detail": ""}
        # The exit arrives while the slow row's child is known to be running:
        # its marker is on disk. The wait is a precondition, not a measurement;
        # its cap only keeps a child that never starts from hanging the suite.
        waited = threading.Event()
        for _ in range(6000):
            if os.path.exists(marker):
                break
            waited.wait(0.01)
        ended["ready"] = os.path.exists(marker)
        raise SystemExit(143)
    real_prove = prove
    globals()["prove"] = fake_prove
    try:
        try:
            _proved([("boom", "b.txt"), ("slow", "s.txt")], trees=["t0", "t1"])
        except SystemExit as exc:
            raised = exc.code
    finally:
        globals()["prove"] = real_prove
        _output.remove_tree(scratch)
    stopping = _row_children()
    _stop_rows(stopping, stream=io.StringIO())
    try:
        _row_runner(stopping)([sys.executable, "-c", "pass"])
        after = "started"
    except RuntimeError as exc:
        after = "refused: %s" % (exc,)
    check("pw17 an exit reaching the rows stops the row still running - its "
          "child ends by a signal or a kill, not by its own exit 0 after "
          "sleeping out its length - and once a run is stopping no row starts a "
          "child: raised %r, slow child started %r, slow child ended %r, a row "
          "after the stop %r"
          % (raised, ended.get("ready"), ended.get("slow"), after),
          raised == 143 and ended.get("ready") is True
          and ended.get("slow") not in (None, 0)
          and after.startswith("refused"))

    tree = ast.parse(_read_source(__file__))
    mains = [n for n in tree.body if isinstance(n, ast.If)
             and "__main__" in ast.dump(n.test)]
    order = [c.func.attr if isinstance(c.func, ast.Attribute) else
             getattr(c.func, "id", None)
             for n in mains for c in ast.walk(n) if isinstance(c, ast.Call)]
    installs = [c for n in mains for c in ast.walk(n) if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute) and c.func.attr == "signal"
                and len(c.args) == 2 and "SIGTERM" in ast.dump(c.args[0])
                and getattr(c.args[1], "id", None) == "_exit_on_term"]
    try:
        _exit_on_term(15, None)
        exited = None
    except SystemExit as exc:
        exited = exc.code
    except NameError:
        exited = "no handler"
    check("pw12 a SIGTERM is raised as an exit, installed before main runs, so "
          "main's finally closes the pool: installs %d, calls %r, exit %r"
          % (len(installs), order, exited),
          len(installs) == 1 and "main" in order
          and order.index("signal") < order.index("main") and exited == 143)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


def _exit_on_term(signum, _frame):
    """A SIGTERM - the drive's teardown of a probe past its bound - raised as an
    exit, so `main`'s `finally` closes the worker pool instead of leaving it
    registered with the checkout."""
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    import signal
    signal.signal(signal.SIGTERM, _exit_on_term)
    sys.exit(main(sys.argv[1:]))
