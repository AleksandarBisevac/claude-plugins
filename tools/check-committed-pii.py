#!/usr/bin/env python3
"""No COMMITTED artifact may carry the identity of the machine that made it.

WHY THIS EXISTS. A user running the plugin on a real project found their own user
name and their whole directory layout inside a committed journal row. The journal
is committed ON PURPOSE -- it is the tamper-evident audit trail, and
`_doctor_trail.check_journal()` warns when it is NOT in git -- so that was not a
stray log line that rotates away. It was a designed artifact carrying machine
identity into a repository that may go to a client. That is
[CWE-532](https://cwe.mitre.org/data/definitions/532.html), which names "full path
names, and system information" in as many words.

`_journal_io.py` closed the channel by construction: command text is not on the
details allow-list any more, a cwd is stored relative to the repo or not at all,
and `actor.host` is not stored. THIS IS THE BACKSTOP FOR THAT, and it reads a
different thing on purpose -- the BYTES GIT TRACKS, not the code that produced
them. A rule that reads the writer can only prove the writer was fixed; only a
rule that reads the committed file can prove nothing else writes there, that no
older artifact is still shipping, and that a hand edit did not put it back.

WHY A TOOL AND NOT A `*_violations()` UNDER scripts/. It asks git what is tracked,
which is `check-rendered-artifacts.py`'s shape rather than `_deps`'. (And a
`*_violations` name inside a gate module would make `prove-gates.coverage()` demand
a TABLE row for it in the same change, which is a different argument in a different
file.)

THE DOMAIN IS NARROW ON PURPOSE, and the narrowing is the difference between a lint
somebody reads and a lint somebody mutes. An all-files scan for, say, an email
address fires on several deliberate sites in this repo -- an author fixture, a
schema example, the license -- and a check whose first run produces findings
nobody intends to fix teaches its reader to skip the whole file. So it reads what
the plugin GENERATES and commits: journal files (live and archived), rendered
reports, and the theme documents the panel writes.

THE REPORT DOMAIN IS DERIVED, NOT LISTED. A report's base name is the user's --
`--basename`, then `meta.reportBasename`, then a default -- so a list of names
would be right for this repo and wrong for every other. A rendered report is
recognised by the generation stamp it prints, which is the same fact
`check-rendered-artifacts.py` reads to pin a render's clock.

IT NEVER PRINTS WHAT IT MATCHED. A lint that echoes the leak into a CI log is the
same bug one layer out, and CI logs on a public repository are public. A finding is
`path:line:detector` and a column, which is enough for a human with the file open
and useless to anyone without it.

A FILE IT CANNOT READ IS A FINDING, never a skip: "I could not clear this" and
"this is clean" are different answers, and only one of them is safe to print as the
other.

IT STARTS RED, and that is handled in the open rather than by narrowing detectors
until they go quiet. `BASELINE` names each already-committed finding with the
reason it stays, the reasons are themselves checked, and a baseline entry that no
longer matches anything is reported -- so this cannot become a place where dead
exemptions accumulate while the check quietly stops covering what it claims.

IT TRAVELS, WHICH IS WHAT IT WAS WRITTEN FOR AND WAS NOT WIRED FOR. Every
paragraph above reasons about OTHER repositories -- only a rule reading the
committed file can prove nothing else writes there; a list of report names would
be right here and wrong everywhere else -- and yet the root was `__file__`'s
grandparent and the command took no path, so the one tree it could never be
pointed at was the one where the leak was found (F112). `--repo <path>` is that
path. `findings()`, `tracked_paths()` and `domain_files()` always took it.

AND THE BASELINE DOES NOT TRAVEL WITH IT. Its rows name bytes in THIS project's
hash chain and the reason each stays is a fact about THIS project, so applying
them to another tree would clear a finding on a decision its owner never took --
which is the failure mode of a shipped exemption table, and it would land on
exactly the person who needs the finding. So a `--repo` naming any tree but this
one is scanned with the table not consulted, and the closing line says so.

AND IT CANNOT READ AN IMAGE, WHICH IS SAID HERE BECAUSE THE GAP IS REAL (F137).
Every committed screenshot under `docs/screenshots/` is a picture of a rendered
surface - the same surfaces this file scans as text - and one of them, the plan
gate card, paints file paths that on a real project name the operator's machine.
Nothing above reaches them: the domain is decided by a path rule or by a
generation stamp read out of decoded UTF-8, so a `.png` never enters it and never
could. This is NOT the narrowing two paragraphs up, which is a choice about what
is worth reading; it is a limit of what can be read at all, and a limit nothing
names is indistinguishable from coverage.

OCR IS NOT THE REPAIR, and the honest one is upstream: the capture knows the
strings it is about to paint, and it knows them BEFORE the shutter opens. So the
same detector vocabulary is offered to a caller through `--scan-text`, which
judges text handed to it on stdin rather than anything git tracks -
`tools/capture-screenshots.mjs` pipes the paths its fixtures will render through
it and refuses to photograph a surface that would carry machine identity into a
committed PNG. One vocabulary, in one file, with two readers: a rule that read the
committed bytes and a second rule that re-spelled these patterns in JavaScript
would be two tables nothing compares.

WHAT `--scan-text` DELIBERATELY IS NOT is a domain. It carries no baseline, asks
git nothing, and makes no claim about a repository; it answers one question about
one string for whoever asked. That is why an empty read is its own finding there
too: a caller that piped nothing and got a clean answer would take it for a clean
surface.

A DOMAIN THAT NARROWED TO NOTHING IS ITS OWN FINDING (`domain-empty`), for the
same reason an unreadable file is one. While the root was hard-wired this could
not happen -- this repository always tracks a journal and a rendered report -- and
with `--repo` it is what a mistyped path does first, so "there is nothing of ours
committed here" had to stop printing as "every committed artifact is clean".

Run it:   python3 tools/check-committed-pii.py
          python3 tools/check-committed-pii.py --repo /path/to/a/real/project
          echo "$SOME_PATH" | python3 tools/check-committed-pii.py --scan-text
          python3 tools/check-committed-pii.py --selftest
Exit 0 when every committed artifact is clean, 1 naming each finding (and each
dead baseline entry, and an empty domain), 2 on a usage error. `--scan-text` reads
stdin instead of a repository and exits 1 on a detector hit or on an empty read.
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- the domain ---------------------------------------------------------------
# What the plugin GENERATES and tells a user to commit. Everything else this
# repository tracks is written by a human, who is allowed to spell a home
# directory in a sentence.
_JOURNAL_RE = re.compile(r"(?:^|/)journal/(?:archive/)?[^/]+\.jsonl$")
# THE EVIDENCE LEDGER, WHICH IS THE JOURNAL'S ARGUMENT ONE DIRECTORY OVER.
# `_evidence_io` says in as many words that a run record "sits beside the manifest
# and is COMMITTED, exactly like the journal", and an evidence row carries the
# things this file exists to read: gate commands and repo-relative paths, written
# by a machine rather than typed by a human. Until the recorder shipped no such
# file existed anywhere, so the domain had never been widened to it and a leak
# there would have been committed unread.
#
# THE SHAPE IS `_JOURNAL_RE`'s AND THE LIMIT IS THE SAME LIMIT. Both directory
# names are `DEFAULT_DIRNAME` conventions a project may override (`journal.dir`,
# `evidence.dir`), so both rules are a convention rather than a derivation - said
# here rather than left for a reader to find, because a path rule that looks
# authoritative is the kind nobody re-checks. There is no `archive/` arm: nothing
# rolls the evidence ledger over, and an arm for a directory no writer creates
# would read as coverage of a case that does not exist.
_EVIDENCE_RE = re.compile(r"(?:^|/)evidence/[^/]+\.jsonl$")
_THEME_RE = re.compile(r"(?:^|/)\.claude/(?:audit\.theme\.json|themes/[^/]+\.json)$")
# The same stamp `check-rendered-artifacts.py` reads to pin a render's clock; here
# it is what identifies a file as a rendered report at all, so a repository that
# renamed its report is still covered and a hand-written document never is.
_REPORT_STAMP = re.compile(r"generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")
_REPORT_EXT = (".html", ".md")


def domain_of(rel, text):
    """Which surface `rel` belongs to, or None when it is nobody's business here.

    `text` is read for the report rule only, and a caller that has not read the
    file may pass None -- in which case the path rules still answer and the
    content rule declines, which is the safe direction for a DOMAIN question:
    declining scans less, never more.
    """
    slug = rel.replace("\\", "/")
    if _JOURNAL_RE.search(slug):
        return "journal"
    if _EVIDENCE_RE.search(slug):
        return "evidence"
    if _THEME_RE.search(slug):
        return "theme"
    if (slug.endswith(_REPORT_EXT) and isinstance(text, str)
            and _REPORT_STAMP.search(text)):
        return "report"
    return None


def tracked_paths(repo=None):
    """(rels, problem) -- every path git tracks, or why the question failed.

    A problem is REPORTED by the caller and never treated as an empty tree: a
    scan that found nothing because it could not ask is the exact shape of a
    green run that checked nothing.
    """
    root = repo or REPO
    try:
        out = subprocess.check_output(["git", "-C", root, "ls-files", "-z"],
                                      stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        return [], "git could not list the tracked files: %s" % (exc,)
    return [p for p in out.decode("utf-8", "replace").split("\0") if p], None


# --- the detectors ------------------------------------------------------------
# EACH IS NAMED so a finding says which one fired, and each is a SHAPE rather than
# a value: nothing here is derived from the machine running it, or the check would
# be blind to every other machine's leak. They may over-flag, and that is the whole
# division of labour with `_journal_io`'s redaction -- a detector's false positive
# costs a human a minute; a rewriter's false negative is already committed.
#
# THE TRANSFORM SPELLINGS LIVE HERE, and this is the only place in the tree that
# should know them. A session directory reaches a command line dash-joined
# (`-Users-someone-Desktop-...`), a URL percent-escaped, and a Windows path
# backslashed -- three renderings of one leak, and a substitution table that tried
# to cover all three is what the redaction deliberately does not do.
DETECTORS = (
    ("posix-home", re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")),
    ("windows-user-path", re.compile(r"[A-Za-z]:\\{1,2}Users\\|\\{2,4}[A-Za-z0-9._-]+\\{1,2}[A-Za-z0-9._$-]+\\")),
    ("session-slug", re.compile(r"-(?:Users|home)-[A-Za-z0-9._]+|-private-tmp-")),
    ("escaped-path", re.compile(r"%2F(?:Users|home)%2F|%5CUsers%5C", re.I)),
    ("tempdir-session", re.compile(r"/(?:private/)?tmp/claude-\d+"
                                   r"|/var/folders/[A-Za-z0-9_+]{2,}"
                                   r"|\\Temp\\claude-", re.I)),
    ("unexpanded-home", re.compile(r"(?:^|[\s\"'=:(\[,])~/")),
)

# --- the contract checks ------------------------------------------------------
# NOT heuristics. A journal row has a shape this repository owns, so these ask
# whether the shape is the one `_journal_io` writes today rather than whether some
# text looks suspicious -- which is a stronger claim and a quieter one.
_WRITER_SHAPES = (
    re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}$"),  # a session id
    re.compile(r"^[0-9a-f]{16}$"),                       # a persisted writer token
    re.compile(r"^writer-\d+$"),                         # the last-resort pid form
)


# The surfaces whose FILE NAME carries a writer id. Both are written by one
# function - `_journal_io.file_for` composes `<month>.<writerId>.jsonl` for the
# journal and `_evidence_io.append_row` calls that same function - so one leak
# reaches both names, and a rule that read only the older of the two would be
# describing the code as it was before the recorder shipped.
_WRITER_NAMED = ("journal", "evidence")


def writer_id_problem(basename):
    """Why a record file's writer id is not one of the shapes this plugin mints.

    Checked for BOTH surfaces in `_WRITER_NAMED`, because both names come out of
    `_journal_io.writer_id` and a machine name lands in them identically. What
    differs is the REPAIR and not the finding: a journal name has none at all --
    `genesis_prev()` seeds the chain from these bytes, so correcting one breaks
    `verify()` on every clone that already holds the file -- while an evidence
    file is chained to nothing and can simply be renamed. A cheaper repair is not
    a reason to look away from the leak, and saying which one applies is what
    stops the journal's argument being read as the only argument.
    """
    stem = basename[:-len(".jsonl")] if basename.endswith(".jsonl") else basename
    _month, _dot, wid = stem.partition(".")
    if not wid:
        return "carries no writer id at all"
    if any(shape.match(wid) for shape in _WRITER_SHAPES):
        return None
    return ("names its writer with something that is neither a session id, a "
            "minted writer token, nor the pid fallback")


def journal_row_problems(row):
    """The detector names one parsed journal row trips, in order."""
    out = []
    actor = row.get("actor")
    if isinstance(actor, dict) and "host" in actor:
        out.append("journal-actor-host")
    details = row.get("details")
    if isinstance(details, dict) and "command" in details:
        out.append("journal-details-command")
    return out


# --- scanning -----------------------------------------------------------------
def scan_text(rel, text, surface):
    """[(rel, line, detector, column)] for one file's contents."""
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        for name, pattern in DETECTORS:
            for m in pattern.finditer(line):
                out.append((rel, n, name, m.start() + 1))
        if surface != "journal":
            continue
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except ValueError:
            # A torn LAST line is what a crash mid-append leaves behind and the
            # chain before it is intact, so it is not this check's business. A
            # torn line anywhere else is a row nobody can clear.
            if n != len(text.split("\n")) and line.strip():
                out.append((rel, n, "journal-unparseable-row", 1))
            continue
        if isinstance(row, dict):
            out.extend((rel, n, name, 1) for name in journal_row_problems(row))
    return out


def domain_files(repo=None):
    """([(rel, surface, text)], [problem rows]) -- the files this check judges.

    Returned rather than folded into `findings()` so a case can assert the set is
    NOT EMPTY. Every case below judges the findings, and "no findings" over a
    domain that narrowed to nothing is the silent pass this repository keeps
    re-finding; only the set itself can tell the two apart.
    """
    root = repo or REPO
    rels, problem = tracked_paths(root)
    if problem is not None:
        return [], [(".", 0, "domain-unavailable", 1)]
    keep, bad = [], []
    for rel in rels:
        surface = domain_of(rel, None)
        if surface is None and not rel.endswith(_REPORT_EXT):
            continue
        try:
            with io.open(os.path.join(root, rel.replace("/", os.sep)),
                         "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            if surface is None:
                # A .html or .md that will not decode is not a rendered report --
                # a report is UTF-8 by construction - so it never entered the
                # domain and there is nothing here to clear.
                continue
            bad.append((rel, 0, "unreadable", 1))
            continue
        if surface is None:
            surface = domain_of(rel, text)
            if surface is None:
                continue
        keep.append((rel, surface, text))
    return keep, bad


def scan(repo=None):
    """One run's whole answer: `root`, `rows`, `files`, `surfaces`, `baselined`.

    ONE WALK, and the domain travels with the rows because "no findings" has two
    very different meanings -- every committed artifact is clean, or this tree
    holds no artifact of ours -- and only the domain tells them apart. That could
    not happen while the root was hard-wired to this repository, which always
    tracks both surfaces; with `--repo` it is the first thing a mistyped path
    does, so the empty domain is a ROW rather than a footnote.
    """
    root = repo if repo is not None else REPO
    keep, rows = domain_files(root)
    rows = list(rows)
    for rel, surface, text in keep:
        rows.extend(scan_text(rel, text, surface))
        if surface in _WRITER_NAMED:
            problem = writer_id_problem(os.path.basename(rel))
            if problem is not None:
                # NAMED FOR THE SURFACE, so a finding sends the reader to the
                # right repair: one of these names can be corrected and the other
                # cannot, and a single detector name would hide which.
                rows.append((rel, 0, "%s-writer-id" % (surface,), 1))
    if not keep and not rows:
        # NOT reported when `rows` already carries `domain-unavailable`: git
        # having refused the question and git having answered "nothing of yours
        # is here" are two findings, and printing both for one tree would send
        # the reader looking for a second cause.
        rows.append((".", 0, "domain-empty", 1))
    return {"root": root,
            "rows": sorted(rows),
            "files": [rel for rel, _s, _t in keep],
            "surfaces": sorted(set(s for _r, s, _t in keep)),
            "baselined": baseline_applies(root)}


def findings(repo=None):
    """[(rel, line, detector, column)] over every tracked file in the domain.

    Sorted, so two runs on one tree produce one order and a diff of two reports is
    the change rather than the shuffling.
    """
    return scan(repo)["rows"]


# --- what is already committed, and stays -------------------------------------
# (path, line, detector, reason). ONE reason for both rows, said once per row
# because a row is what a reader looks up. The reason is the user's decision and
# this is where it is recorded rather than hidden: existing history is left alone.
BASELINE = (
    ("docs/audit/journal/2026-08.3f33caa7-c0c9-4a4e-9c3b.jsonl", 1,
     "journal-actor-host",
     "written before `actor.host` was dropped. The row cannot be edited: its hash "
     "covers these bytes and the file's committed history is one of the trail's "
     "anchors, so rewriting it would break `verify()` on every clone. Forward-only "
     "was the decision, and this is it being recorded rather than hidden."),
    ("docs/audit/journal/2026-08.3f33caa7-c0c9-4a4e-9c3b.jsonl", 2,
     "journal-actor-host",
     "the second row of the same file, for the same reason: the chain runs through "
     "it, so it can be superseded by later rows but never corrected in place."),
)

_MIN_REASON = 60          # a reason short enough to be a label is not a reason


def baseline_applies(repo=None):
    """Whether THIS repository's `BASELINE` may clear a finding in `repo`.

    ONLY IN THE TREE THE TABLE DESCRIBES. Both rows name bytes inside one hash
    chain and the reason each stays -- "rewriting it would break `verify()` on
    every clone" -- is a fact about THAT chain. Carried into somebody else's
    repository the same `(path, line, detector)` key would clear a finding on a
    decision its owner never took, and the whole point of `--repo` is that the
    person whose name is in those rows gets to see them. A clone or a worktree of
    this project resolves to a different directory and is therefore scanned
    unbaselined too, which prints two findings that are already accounted for --
    the loud direction, chosen deliberately over a path-independent identity test
    that would have to guess what "the same project" means.
    """
    root = repo if repo is not None else REPO
    return os.path.realpath(root) == os.path.realpath(REPO)


def baseline_index():
    return dict(((p, n, d), why) for p, n, d, why in BASELINE)


def unbaselined(rows):
    """The findings nobody has accounted for -- what a run reports."""
    known = baseline_index()
    return [r for r in rows if (r[0], r[1], r[2]) not in known]


def dead_baseline(rows):
    """[(path, line, detector)] declared as known and matching nothing any more.

    Reported like a finding, because a table that only ever grows stops describing
    the system and starts describing its own history.
    """
    live = set((r[0], r[1], r[2]) for r in rows)
    return [k for k in sorted(baseline_index()) if k not in live]


def reasonless_baseline():
    """Baseline entries whose reason does not carry one."""
    return [k for k, why in sorted(baseline_index().items())
            if not isinstance(why, str) or len(why.strip()) < _MIN_REASON]


def render(row):
    """One finding, as a line that names WHERE and WHICH and nothing else."""
    rel, line, detector, col = row
    return "%s:%d:%s (column %d)" % (rel, line, detector, col)


# --- what a run says about itself ---------------------------------------------
# THE SYNTHETIC DETECTORS. Neither is text a pattern matched, so neither has a
# file and a column a reader can open - which is why they get a sentence of their
# own rather than being left to read as a leak at line 0 of the repository root.
SYNTHETIC = {
    "domain-empty": ("this tree tracks no journal, no rendered report and no "
                     "theme document of ours, so the run cleared NOTHING - "
                     "check the path before reading anything into it"),
    "domain-unavailable": ("git could not be asked what this tree tracks, so "
                           "the run cleared nothing"),
}


def ok_line(run):
    """The line a clean run prints, with the basis for every claim in it.

    A pure function of `scan()`'s dict, so a case reads it without a fixture
    tree. THE SURFACES ARE HALF THE CLAIM: "no findings" is worth nothing until
    the line also says what was looked at, and the baseline clause says whether a
    decision recorded in THIS repository was allowed to clear anything in the
    tree that was actually scanned.

    AND THE ROOT IS NOT IN IT. Written with the absolute root first, which put
    `/Users/<name>/...` on the tool's own stdout - and on a CI runner it would
    have put the checkout path there, which is `posix-home`'s own shape. A check
    against CWE-532 that prints a home directory into a public log is the bug it
    exists for, one layer out; the operator knows which tree they named, and the
    baseline clause says all that has to be said about which one it was.
    """
    if run["baselined"]:
        basis = ("; %d accounted for by BASELINE" % (len(run["rows"]),)
                 if run["rows"] else "")
    else:
        basis = ("; BASELINE NOT consulted - the tree named by --repo is not the "
                 "repository that table describes, and one project's exemptions "
                 "do not clear another project's findings")
    # THE WORD `TEXT` IS THE REPAIR FOR F137, and it is one word because the
    # over-claim was one word wide. "No committed artifact carries machine
    # identity" is false about a repository that also commits screenshots of these
    # very surfaces, and a headline that over-claims is worse than a narrow one
    # because the parenthetical nobody reads was carrying the whole qualification.
    return ("OK: no committed TEXT artifact carries machine identity (%d file(s) "
            "in the domain [%s], %d finding(s)%s). An image carries no text to "
            "scan and is outside this domain by construction; --scan-text is how "
            "the strings that BECOME one are judged, before the shutter."
            % (len(run["files"]), ", ".join(run["surfaces"]) or "nothing",
               len(run["rows"]), basis))


# --- the same vocabulary, offered to a caller ---------------------------------
# The label a `--scan-text` finding is rendered under. A DASH and not a path,
# because the caller knows what it piped and this file must not print it: the
# whole point of a stdin mode here is that the text may be the leak.
STDIN_LABEL = "-"


def stdin_report(text):
    """`(exit code, [lines])` for one `--scan-text` run.

    PURE, so the cases read exactly what a caller reads rather than a fixture of
    it, and so the empty-read branch can be driven without a pipe.

    NO BASELINE AND NO DOMAIN. Those are answers about a repository and this is an
    answer about a string somebody handed over; consulting either would let a
    decision recorded about committed bytes clear a finding about a path that is
    about to be painted into a picture.

    AN EMPTY READ IS A FINDING for the same reason `domain-empty` is one. A caller
    that piped nothing - a variable that was not set, a command that failed
    upstream - would otherwise receive the clean answer and photograph the surface
    it was asking about.
    """
    if not text.strip():
        return 1, ["NOTHING WAS READ: --scan-text was given no text, so it "
                   "cleared nothing. A caller that piped an unset variable and "
                   "read this as clean would have its answer from a run that "
                   "looked at no characters at all."]
    rows = scan_text(STDIN_LABEL, text, "text")
    if rows:
        lines = ["FOUND %s" % (render(row),) for row in sorted(rows)]
        lines.append("The text handed to --scan-text carries machine identity. "
                     "It is deliberately not echoed - the caller knows what it "
                     "piped, and a check that printed the leak would be the bug "
                     "it exists for, one layer out.")
        return 1, lines
    return 0, ["OK: no machine identity in the text read from stdin (%d line(s), "
               "%d detector(s) applied)"
               % (len(text.split("\n")), len(DETECTORS))]


# --- selftest -----------------------------------------------------------------
def _fixture_tree(files):
    """A git tree that is NOT this repository, holding exactly `files`.

    STAGED, NOT COMMITTED. `git ls-files` -- the one question this tool asks git
    -- reads the index, and a commit would need a configured identity the runner
    may not have. The caller removes the directory.
    """
    root = tempfile.mkdtemp(prefix="pii-fixture-")
    for rel, text in files:
        path = os.path.join(root, rel.replace("/", os.sep))
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    for args in (["init", "-q"], ["add", "-A"]):
        subprocess.check_call(["git", "-C", root] + args,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    return root


def _captured(argv):
    """`(exit code, stdout)` for one `main()` run -- the printed lines are the
    contract a person pointing this at their own project actually reads."""
    held, buf = sys.stdout, io.StringIO()
    sys.stdout = buf
    try:
        code = main(argv)
    finally:
        sys.stdout = held
    return code, buf.getvalue()


def _foreign_cases(check):
    """The half F112 was: the tool pointed at a tree that is not this repository.

    Split out so the fixture trees are built and removed in one place, and so the
    `finally` covers every case below rather than the first one that raises.
    """
    # THE PATH AND THE LINES ARE THE BASELINE'S OWN, read off the table rather
    # than typed: that is the fixture value that tells the two implementations
    # apart. A version applying this repository's exemptions to any tree it is
    # given clears the first two rows and reports a foreign journal as clean -
    # which is exactly the silent pass a shipped exemption table causes, landing
    # on the one person who needs the finding.
    leaky_rel = BASELINE[0][0]
    clean_rel = os.path.join(os.path.dirname(leaky_rel),
                             "2026-08.a1b2c3d4e5f60718.jsonl").replace(os.sep, "/")
    host = '{"actor":{"via":"hook","host":"a-laptop.local"}}'
    leaky = _fixture_tree([
        (leaky_rel, host + "\n" + host + "\n"
         + '{"details":{"command":"npm ci","cwd":"/Users/someone/src"}}' + "\n"),
        ("README.md", "a human wrote this, and mentioned /Users/someone\n"),
    ])
    empty = _fixture_tree([("README.md", "nothing of ours is committed here\n")])
    clean = _fixture_tree([(clean_rel, '{"actor":{"via":"hook"}}\n')])
    # THE EVIDENCE LEDGER, WITH THE LEAK WHERE AN EVIDENCE ROW REALLY CARRIES ONE.
    # A step's command and a coverage path are what `_evidence_io` writes, and the
    # file name is minted by the same `_journal_io.writer_id` the journal's is - so
    # this fixture is the shape of the record rather than an invented string in a
    # `.jsonl`. The sibling directory is the second direction: it is not the
    # evidence ledger, and a rule that matched any `.jsonl` under `docs/audit`
    # would drag a project's own data files into a domain that never claimed them.
    evidence = _fixture_tree([
        ("docs/audit/evidence/2026-08.MacBook-Pro.local-48645.jsonl",
         '{"v":1,"runId":"r1","scope":"task","status":"passed","steps":'
         '[{"name":"test","command":"npm test"}],"observations":'
         '{"coverage":["/Users/someone/src/app.ts"]}}\n'),
        ("docs/audit/evidence-notes/2026-08.a1b2c3d4e5f60718.jsonl",
         '{"note":"a human wrote this under /Users/someone"}\n'),
    ])
    try:
        rows = findings(leaky)
        seen = sorted((r[1], r[2]) for r in rows)
        check("q13 `--repo` scans the tree it is GIVEN and reports that tree's "
              "findings, which is the whole of F112 - the tool exists because a "
              "user found their own name in a committed journal on a real "
              "project, and until this flag it could only ever be run here: %r"
              % (seen,),
              seen == [(1, "journal-actor-host"), (2, "journal-actor-host"),
                       (3, "journal-details-command"), (3, "posix-home")]
              and sorted(set(r[0] for r in rows)) == [leaky_rel])

        code, text = _captured(["--repo", leaky])
        _cleared = [r for r in rows if r not in unbaselined(rows)]
        check("q14 ...and THIS repository's BASELINE clears nothing there. The "
              "fixture's leak sits at the table's own path and lines, so a "
              "version that consulted the table would exit 0 over a journal "
              "naming somebody's machine: exit %d, %d row(s) the table would "
              "have cleared here" % (code, len(_cleared)),
              code == 1 and len(_cleared) == 2
              and baseline_applies(leaky) is False
              and text.count("FOUND %s:1:journal-actor-host" % (leaky_rel,)) == 1
              and text.count("FOUND %s:2:journal-actor-host" % (leaky_rel,)) == 1)

        ecode, etext = _captured(["--repo", empty])
        check("q15 a DOMAIN THAT NARROWED TO NOTHING is a finding and not an "
              "all-clear - a mistyped path is the first thing `--repo` makes "
              "possible, and 'nothing of ours is committed here' must not print "
              "as 'every committed artifact is clean': exit %d" % (ecode,),
              ecode == 1 and etext.count("domain-empty") == 2
              and "NOTHING WAS CHECKED" in etext
              and not etext.startswith("OK:"))

        # THE SECOND DIRECTION, and it looks vacuous: a `domain-empty` row that
        # fired unconditionally would satisfy q15 for ever while refusing every
        # clean project. This is the only case that fails if it does.
        ccode, ctext = _captured(["--repo", clean])
        crun = scan(clean)
        check("q16 ...while a foreign tree WITH one of our artifacts, and clean, "
              "exits 0 and says which surface it read: %r" % (ctext.strip(),),
              ccode == 0 and "domain-empty" not in ctext
              and crun["surfaces"] == ["journal"] and crun["rows"] == []
              and "[journal]" in ctext)

        # THE TOOL APPLIED TO ITSELF, counted rather than eyeballed. Written with
        # the absolute root in it first, which put a home directory on stdout -
        # and on a runner it would be the checkout path, which is `posix-home`'s
        # own shape. A CWE-532 check printing one into a public log is the bug it
        # exists for, one layer out.
        _echo = dict((name, len(scan_text("ok.md", ok_line(run), "report")))
                     for name, run in (("this repo", scan()),
                                       ("a foreign tree", crun)))
        erun = scan(evidence)
        check("q22 the EVIDENCE LEDGER is in the domain and is really scanned - "
              "`_evidence_io` commits a run record beside the manifest exactly as "
              "the journal is committed, and a row carries gate commands and "
              "repo-relative paths, so until this rule the first such file to land "
              "would have been committed unread: %r, %r"
              % (erun["surfaces"], sorted((r[1], r[2]) for r in erun["rows"])),
              erun["surfaces"] == ["evidence"]
              and sorted((r[1], r[2]) for r in erun["rows"])
              == [(0, "evidence-writer-id"), (1, "posix-home")]
              and erun["files"]
              == ["docs/audit/evidence/2026-08.MacBook-Pro.local-48645.jsonl"])

        # THE SECOND DIRECTION, and it is the one that decides between a rule and
        # a file extension: the sibling `.jsonl` above carries a home directory in
        # plain text and is NOT this check's business, because a human wrote it.
        # A domain that swallowed it would fire on deliberate sites and teach its
        # reader to skip the file, which is the narrowing this tool is built on.
        check("q23 ...while a `.jsonl` that is not the evidence ledger stays "
              "OUTSIDE the domain, however much it looks like one",
              domain_of("docs/audit/evidence/2026-08.abc.jsonl", None) == "evidence"
              and domain_of("evidence/2026-08.abc.jsonl", None) == "evidence"
              and domain_of("docs/audit/evidence-notes/2026-08.abc.jsonl", None)
              is None
              and domain_of("docs/audit/evidence/summary.json", None) is None
              and domain_of("docs/audit/evidence.jsonl", None) is None)

        check("q17 the OK line trips NONE of this file's own detectors, on both "
              "roots - the line CI prints and the line a `--repo` run prints: %r"
              % (_echo,),
              set(_echo.values()) == set([0])
              and clean not in ok_line(crun))
    finally:
        # F155. Each of these is a real repository with a file STAGED into it, and
        # staging is enough: `git add` writes a loose object and writes it
        # read-only. On windows `os.unlink` reads that attribute off the file and
        # raises, so `shutil.rmtree` leaves `.git/objects/**` behind - and
        # `ignore_errors=True` leaves it behind silently. The windows leg of CI
        # runs the sweep, the sweep runs this file's `--selftest` from a scratch
        # directory and refuses a file that left anything in it, so this site was
        # live rather than theoretical.
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        for root in (leaky, empty, clean, evidence):
            remove_tree(root)


def _cases(check):
    _user = "aleksandarbisevac"
    # ONE LEAK, EVERY SPELLING IT ARRIVES IN. A session directory reaches a
    # command line dash-joined, a URL percent-escaped and a Windows path
    # backslashed, and knowing all three is exactly the knowledge that belongs in
    # a detector rather than in a rewriter. The table is per DETECTOR, so deleting
    # one is a red case with its name on it rather than a quieter report.
    _spellings = (
        ("posix-home", "cwd=/Users/%s/Desktop/personal" % _user),
        ("posix-home", "cwd=/home/%s/src" % _user),
        ("session-slug", "SCRATCH=/x/-Users-%s-Desktop-personal-x/probe.sh" % _user),
        ("escaped-path", "file:///%%2FUsers%%2F%s%%2Fx" % _user),
        ("windows-user-path", "cwd=C:\\Users\\%s\\src" % _user),
        ("tempdir-session", "/private/tmp/claude-501/probe"),
        ("unexpanded-home", "cwd=~/Desktop/personal"),
    )
    _missed = [(want, sorted(set(h[2] for h in scan_text("f.md", line, "report"))))
               for want, line in _spellings
               if want not in set(h[2] for h in scan_text("f.md", line, "report"))]
    check("q1 every spelling one leak arrives in is caught, and each finding says "
          "WHICH detector fired - the transform knowledge lives here, in something "
          "allowed to over-flag, and not in the redaction: %r" % (_missed,),
          _missed == [])

    # THE SECOND DIRECTION, and it looks vacuous: a detector that always fires
    # would pass q1 forever while making every committed file a finding, which is
    # how a lint gets muted rather than fixed. This is the only case that fails
    # when a pattern becomes unconditional.
    _clean = scan_text("f.md", "generated 2026-01-01 00:00 UTC\nnpm ci\n"
                               "docs/audit/audit-plan.json\n", "report")
    check("q2 an ordinary rendered line trips NOTHING - a check that flagged every "
          "file would be muted within a day: %r" % (_clean,), _clean == [])

    # The rule this whole file would otherwise break one layer out. Counted over
    # the rendered line rather than asserted absent, because a report that
    # embedded the match once and elided it once would pass a presence check.
    _leak = ("SCRATCH=/private/tmp/claude-501/-Users-%s-Desktop-personal-x/probe.sh"
             % _user)
    _line = render(scan_text("f.jsonl", _leak, "report")[0])
    _echo = dict((frag, _line.count(frag))
                 for frag in (_user, "/private/tmp", "-Users-", "SCRATCH"))
    check("q3 a rendered finding echoes NO part of what it matched - CI logs on a "
          "public repository are public, and a lint that prints the leak is the "
          "same bug one layer out: %r" % (_echo,),
          set(_echo.values()) == set([0]) and _line.startswith("f.jsonl:1:"))

    check("q4 the domain is the artifacts the PLUGIN writes, and a document a "
          "human wrote is outside it - an all-files scan fires on deliberate "
          "sites and trains its reader to skip the file",
          domain_of("docs/audit/journal/2026-08.abc.jsonl", None) == "journal"
          and domain_of("docs/audit/journal/archive/2026-07.abc.jsonl", None)
          == "journal"
          and domain_of(".claude/audit.theme.json", None) == "theme"
          and domain_of(".claude/themes/dusk.json", None) == "theme"
          and domain_of("CONTRIBUTING.md", "run it from ~/src") is None
          and domain_of("SECURITY.md", "an example under /Users/someone") is None)
    check("q5 a rendered report is recognised by the stamp it prints, not by a "
          "list of base names - the base name is the user's (`--basename`, then "
          "`meta.reportBasename`), so a list would be right here and wrong "
          "everywhere else",
          domain_of("examples/x/whatever-they-called-it.html",
                    "<p>generated 2026-08-19 20:16 UTC</p>") == "report"
          and domain_of("docs/index.html", "no stamp in here") is None)

    _live = findings()
    _kept, _bad = domain_files()
    _surfaces = sorted(set(s for _r, s, _t in _kept))
    # A FILTER THAT NARROWED TO NOTHING MUST NOT READ AS ALL CLEAR. Every case
    # below judges `_live`, and `_live == []` over an empty domain is the silent
    # pass this repository keeps re-finding - so the SET is asserted, not only its
    # verdict, and both surfaces this tree actually has must be in it.
    check("q6 the domain over the live tree is not empty and reaches every "
          "surface this repository commits - the journal, the evidence ledger "
          "and the rendered reports - so the cases below are judging something: "
          "%d file(s), %r" % (len(_kept), _surfaces),
          _bad == [] and _surfaces == ["evidence", "journal", "report"])

    check("q7 every committed artifact is clean except what BASELINE accounts "
          "for: %r" % ([render(r) for r in unbaselined(_live)],),
          unbaselined(_live) == [])
    # The other direction of an exemption table: an entry that matches nothing any
    # more is a claim about a system that has moved on, and a table nobody prunes
    # stops covering what it says it covers.
    _dead = dead_baseline(_live)
    check("q8 ...and every BASELINE entry still matches a real finding, so a dead "
          "exemption is reported rather than accumulating: %r" % (_dead,),
          _dead == [])
    _bad = reasonless_baseline()
    check("q9 ...and every BASELINE entry carries a reason a reader can disagree "
          "with, not a label: %r" % (_bad,), _bad == [])

    _row = {"actor": {"author": None, "sessionId": "s", "via": "hook",
                      "host": "MacBook-Pro.local"},
            "details": {"command": "npm ci"}}
    check("q10 the journal's CONTRACT checks read the row's shape rather than its "
          "text: a host field and a command key are findings whatever they "
          "contain, which catches the leak a detector's vocabulary would miss",
          journal_row_problems(_row)
          == ["journal-actor-host", "journal-details-command"]
          and journal_row_problems({"actor": {"via": "hook"},
                                    "details": {"commandSha256": "0" * 64}}) == [])

    check("q11 a journal file's WRITER ID is checked too - it is the one field "
          "with no repair path, because `genesis_prev` seeds the chain from these "
          "bytes and a name committed there can never be corrected",
          writer_id_problem("2026-08.3f33caa7-c0c9-4a4e-9c3b.jsonl") is None
          and writer_id_problem("2026-08.a1b2c3d4e5f60718.jsonl") is None
          and writer_id_problem("2026-08.writer-48645.jsonl") is None
          and writer_id_problem("2026-08.MacBook-Pro.local-48645.jsonl")
          is not None
          and writer_id_problem("2026-08.jsonl") is not None)

    _torn = scan_text("f.jsonl", '{"actor":{"via":"hook"}}\n{"half', "journal")
    _mid = scan_text("f.jsonl", '{"half\n{"actor":{"via":"hook"}}\n', "journal")
    check("q12 a torn LAST line is a crash, not a cover-up, and is not this "
          "check's finding - while an unparseable line ANYWHERE ELSE is a row "
          "nobody can clear: %r vs %r" % (_torn, _mid),
          _torn == [] and [h[2] for h in _mid] == ["journal-unparseable-row"])

    _foreign_cases(check)

    # The command line, as a value rather than as an exit code, because `--repo`
    # gave it three ways to be wrong where it had one: a flag whose value is
    # missing, a word nobody recognises, and a path that is not a directory. All
    # three exit 2, so only the returned reason tells them apart - and a `--repo`
    # that silently swallowed the next word would scan the wrong tree and say so
    # nowhere.
    # The bad path is a RELATIVE name on purpose. An absolute one would put the
    # checkout path into this case's label, and the label is printed by every
    # sweep - on a runner that is the home directory of the build user, which is
    # `posix-home`, in the selftest of the file that defines it.
    #
    # AND EACH MESSAGE IS CLASSIFIED, not merely compared with the others. Asked
    # only whether the three differ, this case stayed green against a `--repo`
    # with no value reported as an unrecognised argument - the two messages
    # differ because they quote different words, so distinctness was satisfied by
    # the wrong diagnosis. What the reader needs is the KIND.
    # -- the vocabulary offered to a caller, which is F137's half of this file --
    # THE FIXTURE IS A WINDOWS TEMP ROOT, and it is chosen rather than convenient:
    # `capture-screenshots.mjs` builds its fixtures under the platform temp
    # directory on windows, which is per-user and therefore SPELLS the user's
    # name - and the panel paints that path into its topbar. So this is the string
    # that would become a committed PNG, not an invented one.
    _painted = "C:\\Users\\somebody\\AppData\\Local\\Temp\\audit-shots"
    _code, _lines = stdin_report(_painted + "\n")
    _echo = dict((frag, " ".join(_lines).count(frag))
                 for frag in ("somebody", "AppData", "audit-shots"))
    check("q19 `--scan-text` judges text a CALLER hands over, with the same "
          "detectors and the same refusal to echo what matched - this is how the "
          "strings that become a committed picture get checked, since no rule "
          "here can read a PNG: exit %d, %r" % (_code, _echo),
          _code == 1
          and any("windows-user-path" in line for line in _lines)
          and set(_echo.values()) == set([0]))

    # THE SECOND DIRECTION, and it looks vacuous: a mode that reported something
    # for every input would satisfy q19 for ever while refusing every capture this
    # repository actually runs. The fixture is the POSIX scratch root the capture
    # really uses, which is the case that must stay quiet.
    _clean_code, _clean_lines = stdin_report("/tmp/audit-shots-501\n")
    check("q20 ...and the scratch root a capture on this platform really builds "
          "under trips nothing, so the guard does not refuse the run it was "
          "written to allow: exit %d, %r" % (_clean_code, _clean_lines),
          _clean_code == 0 and len(_clean_lines) == 1
          and _clean_lines[0].startswith("OK:")
          and scan_text("ok.md", _clean_lines[0], "report") == [])

    _empty = stdin_report("   \n")
    check("q21 an EMPTY read is its own finding, never a clean answer - a caller "
          "that piped an unset variable would otherwise photograph the surface it "
          "was asking about on the strength of a run that read no characters: %r"
          % (_empty,),
          _empty[0] == 1 and "NOTHING WAS READ" in _empty[1][0])

    _msgs = [parse_argv(a)[1] for a in ([], ["--repo"], ["--nonsense"],
                                        ["--repo", "no-such-directory-here"])]
    check("q18 the command line is parsed into a value, and each wrong shape is "
          "refused by its own KIND - a missing value, an unknown word and a path "
          "that is no directory send the reader to three different fixes: %r"
          % (_msgs,),
          parse_argv([]) == (None, None)
          and parse_argv(["--repo", REPO])[0] == REPO
          and _msgs[1].startswith("--repo needs")
          and _msgs[2].startswith("unexpected argument")
          and _msgs[3].startswith("not a directory")
          and len(set(_msgs[1:])) == 3)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


USAGE = ("usage: check-committed-pii.py [--repo <path>] [--scan-text] "
         "[--selftest]\n")


def parse_argv(argv):
    """`(repo, problem)` -- the one flag, or why the command line is not one.

    SPLIT OUT SO THE USAGE ERRORS ARE CASES. A flag whose value is missing and a
    flag nobody recognises both used to be "any argument at all", which was true
    while `--selftest` was the only word this accepted; with a value to parse,
    `--repo` swallowing the next word or nothing at all are two different wrong
    answers and only a return value tells them apart.
    """
    repo, rest, i = None, [], 0
    while i < len(argv):
        if argv[i] == "--repo":
            if i + 1 >= len(argv):
                return None, "--repo needs a path"
            repo = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    if rest:
        return None, "unexpected argument(s): %s" % (" ".join(rest),)
    if repo is not None and not os.path.isdir(repo):
        return None, "not a directory: %s" % (repo,)
    return repo, None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return _selftest()
    # HANDLED LIKE `--selftest` AND BEFORE `parse_argv`, on purpose: it names no
    # repository and takes no value, so threading it through the `--repo` parser
    # would give that parser a second question to answer and `q18`'s three kinds
    # of wrong command line a fourth that is not about a path at all.
    if "--scan-text" in argv:
        rest = [a for a in argv if a != "--scan-text"]
        if rest:
            sys.stderr.write("check-committed-pii.py: --scan-text reads stdin and "
                             "takes nothing else: %s\n" % (" ".join(rest),))
            sys.stderr.write(USAGE)
            return 2
        code, lines = stdin_report(sys.stdin.read())
        for line in lines:
            sys.stdout.write(line + "\n")
        return code
    repo, problem = parse_argv(argv)
    if problem is not None:
        sys.stderr.write("check-committed-pii.py: %s\n" % (problem,))
        sys.stderr.write(USAGE)
        return 2
    run = scan(repo)
    live = run["rows"]
    # THE TABLE IS THIS REPOSITORY'S, so in any other tree every row stands. A
    # dead-baseline report is meaningless there for the same reason: the entries
    # were never claims about that tree, so they cannot have gone stale in it.
    bad = unbaselined(live) if run["baselined"] else list(live)
    dead = dead_baseline(live) if run["baselined"] else []
    for row in bad:
        sys.stdout.write("FOUND %s\n" % render(row))
    for key in dead:
        sys.stdout.write("DEAD BASELINE %s:%d:%s - it matches nothing any more, so "
                         "the exemption is describing a system that has moved on\n"
                         % key)
    if bad or dead:
        for name in sorted(set(r[2] for r in bad) & set(SYNTHETIC)):
            sys.stdout.write("\nNOTHING WAS CHECKED (%s): %s\n"
                             % (name, SYNTHETIC[name]))
        sys.stdout.write("\nA committed artifact carries machine identity, an "
                         "exemption has gone stale, or nothing was checked. The "
                         "matched text is deliberately not printed - open the "
                         "file at the line named above.\n")
        return 1
    sys.stdout.write(ok_line(run) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
