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

Run it:   python3 tools/check-committed-pii.py
          python3 tools/check-committed-pii.py --selftest
Exit 0 when every committed artifact is clean, 1 naming each finding (and each
dead baseline entry), 2 on a usage error.
"""

import io
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- the domain ---------------------------------------------------------------
# What the plugin GENERATES and tells a user to commit. Everything else this
# repository tracks is written by a human, who is allowed to spell a home
# directory in a sentence.
_JOURNAL_RE = re.compile(r"(?:^|/)journal/(?:archive/)?[^/]+\.jsonl$")
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


def writer_id_problem(basename):
    """Why a journal file's writer id is not one of the shapes this plugin mints.

    The file NAME is the one field with no repair path: `genesis_prev()` seeds the
    chain from these bytes, so a machine name committed here can never be corrected
    without breaking `verify()` on every clone that already holds the file. Which
    is why the name is checked as well as the contents.
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


def findings(repo=None):
    """[(rel, line, detector, column)] over every tracked file in the domain.

    Sorted, so two runs on one tree produce one order and a diff of two reports is
    the change rather than the shuffling.
    """
    keep, out = domain_files(repo)
    out = list(out)
    for rel, surface, text in keep:
        out.extend(scan_text(rel, text, surface))
        if surface == "journal":
            problem = writer_id_problem(os.path.basename(rel))
            if problem is not None:
                out.append((rel, 0, "journal-writer-id", 1))
    return sorted(out)


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


# --- selftest -----------------------------------------------------------------
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
    check("q6 the domain over the live tree is not empty and reaches both the "
          "journal and the rendered reports, so the cases below are judging "
          "something: %d file(s), %r" % (len(_kept), _surfaces),
          _bad == [] and _surfaces == ["journal", "report"])

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


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


def main():
    if "--selftest" in sys.argv[1:]:
        return _selftest()
    if len(sys.argv) > 1:
        sys.stderr.write("usage: check-committed-pii.py [--selftest]\n")
        return 2
    live = findings()
    bad = unbaselined(live)
    for row in bad:
        sys.stdout.write("FOUND %s\n" % render(row))
    dead = dead_baseline(live)
    for key in dead:
        sys.stdout.write("DEAD BASELINE %s:%d:%s - it matches nothing any more, so "
                         "the exemption is describing a system that has moved on\n"
                         % key)
    if bad or dead:
        sys.stdout.write("\nA committed artifact carries machine identity, or an "
                         "exemption has gone stale. The matched text is "
                         "deliberately not printed - open the file at the line "
                         "named above.\n")
        return 1
    sys.stdout.write("OK: no committed artifact carries machine identity "
                     "(%d finding(s), all accounted for by BASELINE)\n"
                     % (len(live),))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
