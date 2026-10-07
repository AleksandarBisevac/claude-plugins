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
the plugin GENERATES and commits: journal files (live and archived), the evidence
ledger, the plan (its index and every phase shard), rendered reports, and the
theme documents the panel writes.

THE PLAN IS IN FOR THE JOURNAL'S REASON. The plugin writes the index and its
shards, a user commits them, and a task's text is where an agent records what it
did - so a scratch file named by its absolute path lands there as easily as in a
journal row. The index is the file the project's config names and the shards are
wherever the index points, both asked of the plugin rather than listed here; a
document a human keeps beside the plan stays outside, as every such document does.

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
pointed at was the one where the leak was found. `--repo <path>` is that
path. `findings()`, `tracked_paths()` and `domain_files()` always took it.

AND THE BASELINE DOES NOT TRAVEL WITH IT. Its rows name bytes in THIS project's
hash chain and the reason each stays is a fact about THIS project, so applying
them to another tree would clear a finding on a decision its owner never took --
which is the failure mode of a shipped exemption table, and it would land on
exactly the person who needs the finding. So a `--repo` naming any tree but this
one is scanned with the table not consulted, and the closing line says so.

AND IT CANNOT READ AN IMAGE, WHICH IS SAID HERE BECAUSE THE GAP IS REAL.
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

import hashlib
import io
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugins", "audit", "scripts"))
import _output  # noqa: E402  (install_path: the plugin's folders are labels)

_output.install_path()
import _journal_io  # noqa: E402  (the machine-path shapes the writer refuses on)

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
# THE TRANSFORM SPELLINGS ARE THE WRITER'S TOO. A session directory reaches a
# command line dash-joined (`-Users-someone-Desktop-...`), a URL percent-escaped,
# and a Windows path backslashed -- renderings of one leak. The writer
# refuses and redacts each by name rather than substituting one rendering for
# another, so the patterns live beside its own and are read from there.
#
# THE LEADING SEPARATOR IS NOT WHAT MAKES A PATH SOMEBODY'S MACHINE, and keying
# on it left the narrowest possible hole in the rule this file exists for. A
# producer that trims leading dots and separators hands the next reader
# `Users/someone/proj/x.js`, which looks repo-relative, resolves as
# repo-relative, and carries a home directory - so the detector whose whole
# subject is that leak went green on it. The separator is therefore OPTIONAL and
# a token BOUNDARY is what is required instead: the match must begin where a
# word begins, which is what keeps `docs/home/alice.md` and `src/users/x.ts` -
# repo-relative paths that merely resemble one - out of the set. The producer
# side is fixed too (`run-test-gate.files_named` keeps the separator now); a
# detector that could only see the tidy spelling is the half of that pair which
# has to stand on its own, because it is the one reading bytes somebody already
# committed.
#
# NO ROW IS SPELLED HERE. `_journal_io` refuses a caller's free-text value
# carrying any of these shapes before the row is hashed, and redacts the
# plugin's own, so the writer and this backstop read one definition -
# `_journal_io.MACHINE_PATH_SHAPES`, the same pattern objects - and the token
# boundary with them. A copy here would agree with the writer until the day one
# side was widened, and the row the other side missed would be the one already
# committed. The one deliberate difference is the writer's, not this table's:
# it takes a relative path whose first segment is `home`, which this flags.
DETECTORS = _journal_io.MACHINE_PATH_SHAPES

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

# The `.wt-<8 hex>` key a linked worktree's writer id carries after the minted
# shape (`_journal_io.WORKTREE_MARK` plus half a random token).
_WORKTREE_SUFFIX = re.compile(r"\.wt-[0-9a-f]{8}$")


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
    # A linked worktree's writer is the minted shape plus `_journal_io`'s
    # worktree key - a random token too, so the shape below still decides.
    wid = _WORKTREE_SUFFIX.sub("", wid)
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


# A phase's `claim` is written into the shard the plugin commits, so a `host` in it
# is the same machine name the journal stopped storing. `audit-task start` writes a
# claim with no host; this is the backstop that reads the committed bytes for one a
# hand edit, an older writer or another tool put there. A shape check like the
# journal's: the key is the finding, whatever it holds.
_CLAIM_KEY = re.compile(r'^(\s*)"claim"\s*:\s*\{')
_HOST_KEY = re.compile(r'"host"\s*:')


def _claim_hosts(node):
    """How many `claim` objects under `node` carry a `host` key."""
    if isinstance(node, list):
        return sum(_claim_hosts(item) for item in node)
    if not isinstance(node, dict):
        return 0
    claim = node.get("claim")
    own = 1 if isinstance(claim, dict) and "host" in claim else 0
    return own + sum(_claim_hosts(v) for k, v in node.items() if k != "claim")


def plan_claim_host_lines(text):
    """The line of each `host` key inside a phase `claim`, in one plan file.

    THE PARSE DECIDES, THE TEXT LOCATES. Whether a claim carries a host is asked
    of the parsed document, so a `host` anywhere else in the plan is not a
    finding; the line is then read off the text, because a finding names the line
    a person opening the file lands on. A claim the parse found and the text walk
    could not place is still reported, at line 0, rather than dropped. A file that
    does not parse answers nothing here: the index's own unparseable row is
    `plan_files`' to report.
    """
    try:
        want = _claim_hosts(json.loads(text))
    except ValueError:
        return []
    if not want:
        return []
    lines, found = text.split("\n"), []
    for i, line in enumerate(lines):
        m = _CLAIM_KEY.match(line)
        if not m:
            continue
        rest = line[m.end():]
        if "}" in rest:
            # The whole claim on one line.
            if _HOST_KEY.search(rest):
                found.append(i + 1)
            continue
        for j in range(i + 1, len(lines)):
            if lines[j].strip().startswith("}"):
                break
            if _HOST_KEY.search(lines[j]):
                found.append(j + 1)
                break
    return found[:want] + [0] * max(0, want - len(found))


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
    if surface == "plan":
        out.extend((rel, n, "plan-claim-host", 1)
                   for n in plan_claim_host_lines(text))
    return out


_HOOKS_DIR = os.path.join(REPO, "plugins", "audit", "hooks")
_CONFIG_REL = ".claude/audit.config.json"


def _plugin_config(root):
    """The plugin's own merged config for `root` -- `hooks/_config.load`.

    ASKED, NOT RE-SPELLED. `_config` owns the default `manifestPath` and how a
    project's `audit.config.json` overrides it; a second copy of either here would
    agree with the plugin until the day it did not. Imported inside the call, as
    `_journal_io._config_mod` does, so `--scan-text` never pays for it.
    """
    return _config_module().load(root)


def _config_module():
    """`hooks/_config`, imported on first use - see `_plugin_config`."""
    if _HOOKS_DIR not in sys.path:
        sys.path.insert(0, _HOOKS_DIR)
    import _config                                        # noqa: E402
    return _config


def _default_manifest_path():
    """The `manifestPath` a project with no config gets, asked of the plugin."""
    return _config_module().DEFAULTS["manifestPath"]


def _repo_rel(root, path):
    """`path` as a posix path relative to `root`, or None when it is outside."""
    if not isinstance(path, str) or not path.strip():
        return None
    path = path.strip().replace("\\", "/")
    if os.path.isabs(path):
        path = os.path.relpath(path, root).replace(os.sep, "/")
    rel = posixpath.normpath(path)
    if rel == ".." or rel.startswith("../"):
        return None
    return rel


def plan_files(root, rels):
    """`(set of rels, [problem rows])` -- the PLAN: its index and its shards.

    DERIVED THE WAY THE PLUGIN FINDS ITS OWN PLAN. The index is the file the
    project's config names (`manifestPath`, through `_plugin_config`), and the
    shards are wherever the index's own `shard` pointers say, resolved against the
    index's directory exactly as `_manifest_io.load_manifest` resolves them. Every
    TRACKED JSON file directly in a directory those pointers name is in, not only
    the files they name today: a shard the index stopped pointing at is still
    committed.

    A SHARD DIRECTORY THAT IS THE INDEX'S OWN is not swept whole, because that
    directory also holds whatever a human keeps beside the plan; only the pointed
    files are taken from it. The domain grows by the plan and not by every JSON
    file near it, which is the narrowing the rest of this file is built on.

    An index that is tracked but does not parse is a FINDING, never a skip: its
    pointers cannot be read, so "no shard carried a leak" would be a claim about
    files nobody located.
    """
    cfg = _plugin_config(root)
    problems = []
    if cfg.get("_configError"):
        problems.append((_CONFIG_REL, 0, "plan-config-unreadable", 1))
    tracked = set(rels)
    index = _repo_rel(root, cfg.get("manifestPath"))
    if index is None or index not in tracked:
        return set(), problems
    try:
        with io.open(os.path.join(root, index.replace("/", os.sep)), "r",
                     encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set([index]), problems + [(index, 0, "plan-index-unparseable", 1)]
    base = posixpath.dirname(index)
    stubs = data.get("phases") if isinstance(data, dict) else None
    shards, dirs = set(), set()
    for stub in (stubs if isinstance(stubs, list) else []):
        pointer = stub.get("shard") if isinstance(stub, dict) else None
        rel = _repo_rel(root, posixpath.join(base, pointer.replace("\\", "/"))
                        if isinstance(pointer, str) else None)
        if rel is None:
            continue
        shards.add(rel)
        if posixpath.dirname(rel) != base:
            dirs.add(posixpath.dirname(rel))
    # SHARD-SHAPED FILES ONLY: JSON directly inside a directory a pointer names,
    # which is every file a pointer COULD name there. A script, a note, or a
    # subdirectory beside the shards is somebody's work kept near the plan, and
    # sweeping it in is the widening this file's domain refuses everywhere else.
    under = set(r for r in tracked
                if posixpath.dirname(r) in dirs and r.endswith(".json"))
    return set([index]) | (shards & tracked) | under, problems


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
    plan, bad = plan_files(root, rels)
    keep, bad = [], list(bad)
    for rel in rels:
        surface = domain_of(rel, None)
        if surface is None and rel in plan:
            surface = "plan"
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


# --- what a baseline row is keyed by -------------------------------------------
# THE LINE NUMBER, FOR A FILE WHOSE LINES DO NOT MOVE. A journal and an evidence
# ledger are append-only, so a row's line is fixed the day it is written; a
# rendered report is regenerated whole and compared against a fresh render, so a
# moved line there is a changed artifact anyway.
#
# THE LINE'S TEXT, FOR THE PLAN. The plugin rewrites the index and a shard in
# place - a phase stub, a file-index entry, a task's status - and every such write
# moves every line after it. Keyed by number, one routine phase-add printed each
# exempted row below it as FOUND at its new line and DEAD BASELINE at its old one.
# Keyed by a digest of what the matched line SAYS, a move changes nothing, while
# an edit to that line - the only edit that can change what was decided about it -
# kills the row and re-reports the finding. The line number is still printed; it
# is just not what the exemption is attached to.
_ANCHORED = ("plan",)
_ANCHOR_PREFIX = "line-sha256:"


def line_anchor(line):
    """The key a plan line is baselined by: a digest of what it says.

    Leading and trailing whitespace and a trailing comma are not part of what a
    line says: a re-indent, or a sibling key appended after it in the same JSON
    object, changes them without touching the text the exemption was decided on.
    """
    said = line.strip()
    if said.endswith(","):
        said = said[:-1].rstrip()
    return _ANCHOR_PREFIX + hashlib.sha256(said.encode("utf-8")).hexdigest()[:16]


def baseline_key(row, anchors=None):
    """`(path, line-or-anchor, detector)` -- what a finding is looked up by."""
    rel, n, detector = row[0], row[1], row[2]
    return (rel, (anchors or {}).get((rel, n), n), detector)


def scan(repo=None):
    """One run's whole answer: `root`, `rows`, `anchors`, `files`, `surfaces`,
    `baselined`. `anchors` maps a plan finding's `(path, line)` to its
    `line_anchor`, which is what `baseline_key` looks it up by.

    ONE WALK, and the domain travels with the rows because "no findings" has two
    very different meanings -- every committed artifact is clean, or this tree
    holds no artifact of ours -- and only the domain tells them apart. That could
    not happen while the root was hard-wired to this repository, which always
    tracks both surfaces; with `--repo` it is the first thing a mistyped path
    does, so the empty domain is a ROW rather than a footnote.
    """
    root = repo if repo is not None else REPO
    keep, rows = domain_files(root)
    rows, anchors = list(rows), {}
    for rel, surface, text in keep:
        found = scan_text(rel, text, surface)
        rows.extend(found)
        if surface in _ANCHORED:
            lines = text.split("\n")
            anchors.update(((rel, n), line_anchor(lines[n - 1]))
                           for _r, n, _d, _c in found if 0 < n <= len(lines))
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
            "anchors": anchors,
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
# (path, line, detector, reason) - the line is a `line_anchor` for the plan, see
# `baseline_key`. ONE reason for both rows, said once per row
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
    ("docs/audit/journal/2026-09.24c1c300-045e-45b9-beaf.wt-cbe2f966.jsonl", 95,
     "posix-home",
     "a review.finding row whose prose says 'the isolated home/TMPDIR' - a phrase "
     "about the sweep's scratch environment, not a directory of any machine. "
     "posix-home matches `home/` before a word by design, and the row is chained and "
     "already merged elsewhere, so it is recorded here rather than rewritten."),
    ("docs/audit/journal/2026-09.24c1c300-045e-45b9-beaf.jsonl", 1419,
     "posix-home",
     "the phase.add row of the phase that adds the entry above: its outcome quotes "
     "the same phrase 'home/TMPDIR' while naming the false positive it fixes. No "
     "machine path is in it, and the chain runs through it, so it stays."),
    ("docs/audit/journal/2026-09.24c1c300-045e-45b9-beaf.jsonl", 1420,
     "posix-home",
     "the task.add row beside it, whose title quotes the same phrase for the same "
     "reason. A phrase, not a directory; chained, so recorded rather than rewritten."),
    ("docs/audit/journal/2026-10.6c881c24-c1fd-461f-8c48.wt-d215e320.jsonl", 23,
     "posix-home",
     "a task.note row whose text quoted an operator's command, and that command's "
     "argument was an absolute path under the operator's home directory. The "
     "plan's copy of the note was corrected to a repository-relative spelling; "
     "this row cannot be - its hash covers these bytes and the chain runs "
     "through it - so it is recorded here rather than rewritten."),
    ("docs/audit/journal/2026-10.6c881c24-c1fd-461f-8c48.wt-d215e320.jsonl", 114,
     "posix-home",
     "a row whose text quotes a relative 'home/page.tsx' as the example of a "
     "repository path the writer must accept - a file a repository may hold, "
     "not a directory of any machine. posix-home flags `home/` at a token start "
     "by design, and the row is chained, so it is recorded rather than rewritten."),
    ("docs/audit/journal/2026-10.6c881c24-c1fd-461f-8c48.wt-d215e320.jsonl", 194,
     "unexpanded-home",
     "a review-finding row quoting the reviewer's own probe text: the tilde "
     "config directory every install shares, written to show it is refused at "
     "the writer's door. A placeholder location, not a path of any machine; the "
     "row is chained, so it is recorded rather than rewritten."),
    ("docs/audit/journal/2026-10.6c881c24-c1fd-461f-8c48.wt-d215e320.jsonl", 195,
     "posix-home",
     "a review-finding row quoting the reviewer's own probe text: two file URLs "
     "into a placeholder home directory of a one-letter user, one with no host "
     "and one naming localhost, showing which of the two the shapes caught. "
     "Neither names a machine; the row is chained, so it is recorded rather "
     "than rewritten."),
    # THE PLAN'S ROWS, recorded when the plan entered the domain. Every one is a
    # shape QUOTED in a task's text - an example, a fixture name, a phrase - and
    # names no machine. KEYED BY WHAT THE LINE SAYS (`line_anchor`), not by its
    # number: the plugin rewrites these files in place and every write moves
    # the lines after it, while only an edit to the matched line itself can
    # change what was decided - and that edit kills the row out loud, as DEAD
    # BASELINE beside a FOUND. `baseline_key` says why the rows above differ.
    ("docs/audit/audit-plan.json", "line-sha256:c3abd5e92b28bfdb",
     "windows-user-path",
     "a bug row's text giving an example of what a dirname call returns on "
     "Windows: a drive-letter scratch path under a temp folder, spelled with "
     "escaped backslashes. It names no user directory and no machine."),
    ("docs/audit/phases/P34.json", "line-sha256:871064e665529ce3",
     "unexpanded-home",
     "a task outcome naming where the lock file lives: the documented config "
     "directory, written as the tilde default beside its environment override. "
     "A location every install shares, not a path of any machine."),
    ("docs/audit/phases/P72.json", "line-sha256:4f87b3c1a172cfa6",
     "unexpanded-home",
     "a task's text quoting a refused shell command as the example of what the "
     "guard must block - a redirect into a shell start-up file under the tilde. "
     "It is the attack being described, not a path this project touched."),
    ("docs/audit/phases/P72.json", "line-sha256:84608e710183b4cf",
     "unexpanded-home",
     "the same refused-command example, repeated in a second task's text of the "
     "same phase. An illustration of the guarded operation, not a directory of "
     "any machine."),
    ("docs/audit/phases/P75.json", "line-sha256:f9821ee5e1053e2a",
     "posix-home",
     "a task's text listing the checkout layouts that make two absolute paths "
     "collide, one of them the hosted CI runner's standard work directory. That "
     "is the runner image's fixed layout, identical everywhere, not an operator."),
    ("docs/audit/phases/P82.json", "line-sha256:8dc84fcac7058bd0",
     "windows-user-path",
     "a task's text describing how a CRLF file is rewritten on Windows, with the "
     "carriage-return and newline escapes spelled out as escaped backslash "
     "sequences. The detector reads the escapes as path separators; no path."),
    ("docs/audit/phases/P82.json", "line-sha256:6a79a0c4d37badc3",
     "windows-user-path",
     "a task's text quoting how git prints a non-ASCII test file name under its "
     "default quoting: the octal bytes of a UTF-8 character, each behind an "
     "escaped backslash. A repository-relative file name, not a user path."),
    ("docs/audit/phases/P82.json", "line-sha256:57a13209e18be434",
     "unexpanded-home",
     "a task's text naming two marker files a selftest writes and removes in the "
     "sandboxed home, both spelled with the tilde. Fixture names the suite "
     "invents; one row covers both columns because the key is the line's text."),
    ("docs/audit/phases/P82.json", "line-sha256:6c0da7b36de3bf33",
     "posix-home",
     "a task's text saying a run is green under the sweep's isolated home and "
     "temp directories - the phrase the journal rows above are baselined for. "
     "Prose about the scratch environment, not a directory of any machine."),
    ("docs/audit/phases/P90.json", "line-sha256:8a691891eb8e1159",
     "posix-home",
     "the phase outcome of the change that baselined the journal phrase above; "
     "it quotes that phrase while saying it is not a home directory. Quoting "
     "the false positive trips it again; nothing here names a machine."),
    ("docs/audit/phases/P90.json", "line-sha256:e4ce8c0a69c04ed3",
     "posix-home",
     "the title of that same phase's task, quoting the phrase the detector "
     "matched in the journal row. A description of a false positive, not a "
     "path of any machine."),
    ("docs/audit/phases/P90.json", "line-sha256:e6105cb8d2235f5d",
     "posix-home",
     "the description of that task, quoting the matched words to locate the "
     "journal finding it baselines. It states in its own text that no path of "
     "this machine is present, and none is."),
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


def unbaselined(rows, anchors=None):
    """The findings nobody has accounted for -- what a run reports.

    `anchors` is `scan()`'s, and without it every row is looked up by its line:
    right for the surfaces whose lines never move, wrong for the plan.
    """
    known = baseline_index()
    return [r for r in rows if baseline_key(r, anchors) not in known]


def _key_order(key):
    # A line and an anchor sit in one column, and Python 3 will not order an int
    # against a str; the rendered form orders both without guessing a rank.
    return (key[0], "%s" % (key[1],), key[2])


def dead_baseline(rows, anchors=None):
    """[(path, line-or-anchor, detector)] declared as known and matching nothing
    any more.

    Reported like a finding, because a table that only ever grows stops describing
    the system and starts describing its own history.
    """
    live = set(baseline_key(r, anchors) for r in rows)
    return [k for k in sorted(baseline_index(), key=_key_order) if k not in live]


def reasonless_baseline():
    """Baseline entries whose reason does not carry one."""
    return [k for k, why in sorted(baseline_index().items())
            if not isinstance(why, str) or len(why.strip()) < _MIN_REASON]


def render(row):
    """One finding, as a line that names WHERE and WHICH and nothing else."""
    rel, line, detector, col = row
    return "%s:%d:%s (column %d)" % (rel, line, detector, col)


# --- what a run says about itself ---------------------------------------------
# THE SYNTHETIC DETECTORS. None is text a pattern matched, so none has a column a
# reader can open - which is why each gets a sentence of its own rather than
# being left to read as a leak at line 0.
SYNTHETIC = {
    "domain-empty": ("this tree tracks no journal, no evidence ledger, no plan, "
                     "no rendered report and no theme document of ours, so the "
                     "run cleared NOTHING - "
                     "check the path before reading anything into it"),
    "domain-unavailable": ("git could not be asked what this tree tracks, so "
                           "the run cleared nothing"),
    "plan-index-unparseable": ("the plan's index does not parse, so its shard "
                               "pointers could not be read and no shard was "
                               "located, let alone cleared - the index's own "
                               "text was scanned and nothing more"),
    "plan-config-unreadable": ("the project's audit config did not parse, so "
                               "the plugin's default manifestPath was used - if "
                               "the config names a plan elsewhere, that plan "
                               "was not read"),
}

# AND EACH GETS ITS OWN HEADLINE, because they do not all mean the same thing: an
# empty or unanswerable domain cleared nothing, an unreadable index cleared the
# index but no shard, and an unreadable config still read a plan - the default
# one - which is not "nothing checked". Kept apart from SYNTHETIC so that table
# stays one sentence per name, which is the shape its readers expect.
_SYNTHETIC_HEADLINE = {
    "domain-empty": "NOTHING WAS CHECKED",
    "domain-unavailable": "NOTHING WAS CHECKED",
    "plan-index-unparseable": "NO SHARD WAS CLEARED",
    "plan-config-unreadable": "THE DEFAULT PLAN WAS READ",
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
    # THE WORD `TEXT` IS THE REPAIR, and it is one word because the
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
    """Half of what was wrong: the tool pointed at a tree that is not this repository.

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
    plan, plan_leaks = _plan_fixture()
    try:
        _plan_cases(check, plan, plan_leaks)
        rows = findings(leaky)
        seen = sorted((r[1], r[2]) for r in rows)
        check("q13 `--repo` scans the tree it is GIVEN and reports that tree's "
              "findings, which is exactly why the tool exists - a user found their "
              "own name in a committed journal on a real "
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
        # Each of these is a real repository with a file STAGED into it, and
        # staging is enough: `git add` writes a loose object and writes it
        # read-only. On windows `os.unlink` reads that attribute off the file and
        # raises, so `shutil.rmtree` leaves `.git/objects/**` behind - and
        # `ignore_errors=True` leaves it behind silently. The windows leg of CI
        # runs the sweep, the sweep runs this file's `--selftest` from a scratch
        # directory and refuses a file that left anything in it, so this site was
        # live rather than theoretical.
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        for root in (leaky, empty, clean, evidence, plan):
            remove_tree(root)


# A script beside the fixture's shards. Assembled, because `_refs` reads every
# script name written in tools/ as a reference to a file that must exist, and
# this one is a fixture that exists only inside a temporary tree.
_STRAY_SCRIPT = "plan/shards/helper" + ".py"


def _plan_fixture():
    """`(root, leaks)` -- a tree whose PLAN names machine paths in task text.

    The plan lives where a project's own config says, not at the default, so a
    domain that LISTED the default path would miss it and only one that asks the
    config finds it. The paths are assembled from pieces at run time: this file's
    own source is read by scanners that would otherwise see the shape it tests.
    `leaks` is `{rel: (line, detector)}`, the answer the domain has to produce.
    """
    home = "/".join(["", "Us" + "ers", "some" + "one", "scratch", "probe.sh"])
    scratch = "/".join(["", "priv" + "ate", "t" + "mp", "claude-" + "7",
                        "s", "probe.json"])

    def shard(pid, text, claim=None):
        body = {"id": pid, "tasks": [{"id": pid + ".1", "description": text}]}
        if claim is not None:
            body["claim"] = claim
        return json.dumps(body, indent=2) + "\n"
    claim = {"sessionId": "s-1", "branch": "audit/p", "at": "2026-01-01T00:00:00Z"}
    index = json.dumps({"meta": {"version": 2}, "phases": [
        {"id": "P1", "shard": "shards/P1.json"},
        {"id": "P2", "shard": "shards/P2.json"},
        {"id": "P3", "shard": "shards/P3.json"},
        {"id": "P4", "shard": "P4.json"},
        {"id": "P5", "shard": "shards/P5.json"}]}, indent=2) + "\n"
    files = [
        (".claude/audit.config.json",
         json.dumps({"manifestPath": "plan/roadmap.json"}) + "\n"),
        ("plan/roadmap.json", index),
        ("plan/shards/P1.json", shard("P1", "wrote the probe to %s" % home)),
        ("plan/shards/P2.json", shard("P2", "the result sits in %s" % scratch)),
        # THE ALLOW CASE: repo-relative paths and bare base names are what an
        # honest shard carries, and a plan surface that flagged them would be
        # muted the first day.
        # ...and its claim is the allow twin of P5's below: session, branch and
        # moment, no machine name.
        ("plan/shards/P3.json", shard("P3", "edit tools/check-committed-pii.py "
                                            "and docs/home/notes.md; see probe.sh",
                                      claim)),
        # A claim carrying a `host`: a machine name in a committed shard, which no
        # detector's vocabulary would see because the value is just a word.
        ("plan/shards/P5.json", shard("P5", "nothing to see",
                                      dict(claim, host="a-laptop"))),
        # A shard pointed at BESIDE the index is taken, and the directory it
        # sits in is not swept: that directory is also where the human's note
        # below lives. The domain grew by the plan, not by every JSON file near
        # it, and this pair is what fails if a shard beside the index widens
        # the sweep to its whole directory.
        ("plan/P4.json", shard("P4", "nothing here but plan/roadmap.json")),
        ("plan/notes.json", json.dumps({"n": home}) + "\n"),
        # A file BESIDE a pointed shard that no pointer could name: a shard is
        # JSON, so a script sitting in the shard directory is somebody's tool and
        # not the plan, however close to it it lives.
        (_STRAY_SCRIPT, "SCRATCH = %r\n" % (home,)),
    ]
    # The line is READ off the rendered shard rather than counted by hand, so the
    # expected answer is the line a person opening the file would land on.
    body = dict(files)

    def line_of(rel, key='"description"'):
        return [n for n, text in enumerate(body[rel].split("\n"), 1)
                if key in text][0]
    leaks = {"plan/shards/P1.json": (line_of("plan/shards/P1.json"), "posix-home"),
             "plan/shards/P2.json": (line_of("plan/shards/P2.json"),
                                     "tempdir-session"),
             "plan/shards/P5.json": (line_of("plan/shards/P5.json", '"host"'),
                                     "plan-claim-host")}
    return _fixture_tree(files), leaks


def _plan_cases(check, plan, leaks):
    """The plan -- its index and every shard -- is a surface this tool reads."""
    prun = scan(plan)
    # A LIST, not a dict: a second detector firing on one line is a different
    # answer, and a mapping keyed by file would fold it away.
    seen = sorted((r[0], r[1], r[2]) for r in prun["rows"])
    check("q24 the PLAN is in the domain, found where the project's config puts "
          "it, and a machine path in a shard's task text is reported with its "
          "file and line - the plugin writes those shards and a user commits "
          "them, so a leak there was committed unread: %r, %r"
          % (seen, prun["files"]),
          seen == sorted((rel, n, d) for rel, (n, d) in leaks.items())
          and prun["surfaces"] == ["plan"]
          and sorted(prun["files"]) == ["plan/P4.json", "plan/roadmap.json",
                                        "plan/shards/P1.json",
                                        "plan/shards/P2.json", "plan/shards/P3.json",
                                        "plan/shards/P5.json"])

    code, text = _captured(["--repo", plan])
    _echo = dict((frag, text.count(frag))
                 for frag in ("some" + "one", "claude-" + "7", "probe.json",
                              "scratch", "a-laptop"))
    check("q25 ...and the run names each such shard by file and line and echoes "
          "NOTHING it matched, while the shard carrying only repo-relative paths "
          "and base names is not a finding: exit %d, %r" % (code, _echo),
          code == 1 and set(_echo.values()) == set([0])
          and all(text.count("FOUND %s:%d:%s " % (rel, n, d)) == 1
                  for rel, (n, d) in leaks.items())
          and text.count("FOUND ") == len(leaks)
          and "P3.json" not in text and "notes.json" not in text)

    check("q28 ...and a shard directory contributes only what a pointer could "
          "name - JSON directly inside it - so a script beside a pointed shard, "
          "carrying a machine path, stays outside the plan: %r" % (prun["files"],),
          _STRAY_SCRIPT not in prun["files"]
          and posixpath.basename(_STRAY_SCRIPT) not in text
          and "plan/shards/P3.json" in prun["files"])


def _plan_problem_cases(check):
    """The two plan rows that are not a pattern match, each driven to fire once.

    One tree per row, each broken in exactly one way, so a case that saw BOTH
    rows, or a detector row as well, is telling the reader something went wrong
    beyond the one thing this tree was built to break.
    """
    default_index = _default_manifest_path()
    # A config that is not JSON: the plugin falls back to its defaults, so the
    # default index is still read - which is why the row says "the default was
    # used" and not "nothing was checked".
    cfg_bad = _fixture_tree([
        (_CONFIG_REL, "{ this is not json\n"),
        (default_index, json.dumps({"phases": []}) + "\n"),
    ])
    # An index cut off mid-write: its pointers cannot be read, so no shard was
    # located, let alone cleared.
    idx_bad = _fixture_tree([
        (_CONFIG_REL, json.dumps({"manifestPath": "plan/roadmap.json"}) + "\n"),
        ("plan/roadmap.json", '{"phases": [{"id": "P1", "shard": "shards/P'),
        ("plan/shards/P1.json", json.dumps({"id": "P1"}) + "\n"),
    ])
    try:
        crun = scan(cfg_bad)
        ccode, ctext = _captured(["--repo", cfg_bad])
        check("q29 a config that does not parse is ONE finding naming the config, "
              "and the plan at the default path is still read - exit %d, %r, %r"
              % (ccode, crun["rows"], crun["surfaces"]),
              crun["rows"] == [(_CONFIG_REL, 0, "plan-config-unreadable", 1)]
              and crun["surfaces"] == ["plan"] and ccode == 1
              and ctext.count("(plan-config-unreadable): ") == 1
              and ctext.count("THE DEFAULT PLAN WAS READ") == 1)

        irun = scan(idx_bad)
        icode, itext = _captured(["--repo", idx_bad])
        check("q30 an index that does not parse is ONE finding naming the index, "
              "and no shard it might have pointed at is claimed as read - exit "
              "%d, %r, %r" % (icode, irun["rows"], irun["files"]),
              irun["rows"] == [("plan/roadmap.json", 0, "plan-index-unparseable", 1)]
              and irun["files"] == ["plan/roadmap.json"] and icode == 1
              and itext.count("(plan-index-unparseable): ") == 1
              and itext.count("NO SHARD WAS CLEARED") == 1)
    finally:
        from _suite import remove_tree   # tools/_suite.py says why the import is here
        for root in (cfg_bad, idx_bad):
            remove_tree(root)


def _with_edited_domain(edit):
    """`(exit, stdout)` of a plain run over this tree, every domain text passed
    through `edit(rel, surface, text)` first.

    IN MEMORY, NEVER ON DISK. The question is what the check says about a plan
    the plugin has just rewritten, and the committed plan is the one fixture
    whose baselined rows are real; editing the files to ask it would leave a
    mutated plan behind on any failure.
    """
    held = globals()["domain_files"]

    def patched(repo=None):
        keep, bad = held(repo)
        return [(rel, s, edit(rel, s, t)) for rel, s, t in keep], bad
    globals()["domain_files"] = patched
    try:
        return _captured([])
    finally:
        globals()["domain_files"] = held


def _moving_cases(check):
    """A baselined plan row survives the plugin moving its line, and only that."""
    keep, _bad = domain_files()
    plan = set(rel for rel, s, _t in keep if s == "plan")
    hits = sorted(r for r in findings() if r[0] in plan and r[1] > 0)
    code0, out0 = _captured([])

    # EVERY plan file gains a line at the top: what adding a phase stub or a
    # file-index entry does to every row below it in the index.
    def shift(_rel, surface, text):
        return ("\n" + text) if surface == "plan" else text
    code1, out1 = _with_edited_domain(shift)
    check("q26 a line inserted ABOVE a baselined plan match leaves it accounted "
          "for - routine plugin writes to the index move every line after them, "
          "and a key that moved with them turned the next phase-add red: "
          "exit %d over %d baselined plan hit(s), %r"
          % (code1, len(hits), [l for l in out1.split("\n") if l][:4]),
          hits != [] and code0 == 0 and code1 == 0
          and "FOUND " not in out1 and "DEAD BASELINE " not in out1)

    rel, n = hits[0][0], hits[0][1]
    on_line = [r for r in hits if (r[0], r[1]) == (rel, n)]
    detectors = sorted(set(r[2] for r in on_line))

    def at_line(k, suffix):
        def edit(r, _surface, text):
            if r != rel:
                return text
            lines = text.split("\n")
            lines[k - 1] = lines[k - 1] + suffix
            return "\n".join(lines)
        return edit
    code2, out2 = _with_edited_domain(at_line(n, " edited"))
    dead = [l for l in out2.split("\n") if l.startswith("DEAD BASELINE ")]
    check("q27 ...while an edit to the MATCHED LINE itself is re-decided out "
          "loud: the finding prints as FOUND at its line and the row that "
          "exempted the old text as DEAD BASELINE - exit %d, %r"
          % (code2, [l for l in out2.split("\n") if l][:4]),
          code2 == 1
          and out2.count("FOUND ") == len(on_line)
          and all(out2.count("FOUND %s:%d:%s " % (rel, n, d)) >= 1
                  for d in detectors)
          and len(dead) == len(detectors)
          and all(l.startswith("DEAD BASELINE %s:" % (rel,)) for l in dead))

    # THE SECOND DIRECTION: a key so loose that ANY edit to the file cleared it,
    # or so tight that any edit killed it, fails here and nowhere else.
    quiet = [k for k in range(1, n) if all(r[1] != k for r in hits
                                           if r[0] == rel)]
    code3, out3 = _with_edited_domain(at_line(quiet[0], " unrelated"))
    check("q27b ...and an unrelated edit elsewhere in the same file changes "
          "nothing at all: exit %d, output identical to the untouched run: %r"
          % (code3, out3 == out0),
          quiet != [] and code3 == 0 and out3 == out0)


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

    # THE SPELLING WITH THE LEADING SEPARATOR ALREADY GONE. A producer that
    # trimmed leading dots and separators is how a home directory reached a
    # committed row looking repo-relative, and this file was the thing that was
    # supposed to see it. Driven inside a quoted JSON value because that is the
    # shape the row actually stores - a bare line would let a start-anchored
    # pattern pass for a boundary test.
    _stripped = (
        ("posix-home", '{"coverageBasis":"among them: Users/%s/p/x.js"}' % _user),
        ("posix-home", '{"coverageBasis":"among them: home/%s/p/x.js"}' % _user),
        ("tempdir-session", '{"b":"tmp/claude-501/probe, private/tmp/claude-7/x"}'),
        ("tempdir-session", '{"b":"var/folders/zz/T/probe"}'),
    )
    _blind = [(want, line, sorted(set(h[2] for h in scan_text("f.jsonl", line,
                                                              "evidence"))))
              for want, line in _stripped
              if want not in set(h[2] for h in scan_text("f.jsonl", line,
                                                         "evidence"))]
    check("q2a a machine path whose LEADING SEPARATOR was stripped is still "
          "found - the narrowest hole there is in a check whose whole subject "
          "is this class, and the one that was open: %r" % (_blind,),
          _blind == [])
    # THE ALLOW CASE FOR q2a, AND IT IS THE ONE TO DRIVE HARDEST. Dropping the
    # separator requirement without putting a boundary in its place convicts
    # every repo-relative path with `home` or `users` as a directory inside it -
    # honest paths, in a file the plugin writes, reported as somebody's machine.
    # That is the shape that gets a check switched off rather than fixed.
    _honest = ("docs/home/alice.md", "src/users/profile.ts",
               "app/home/settings.ts", "myhome/index.ts",
               "a/var/folders/index.ts", "build/tmp/claude-notes.md")
    _wrong = [(p, sorted(set(h[2] for h in scan_text("f.jsonl",
                                                     '{"coverage":["%s"]}' % p,
                                                     "evidence"))))
              for p in _honest
              if scan_text("f.jsonl", '{"coverage":["%s"]}' % p, "evidence")]
    check("q2b ...and a repo-relative path that merely RESEMBLES one is left "
          "alone: the separator became optional, not absent, and a match has "
          "to start where a word starts: %r" % (_wrong,), _wrong == [])

    # EVERY PLACE A REAL SLUG STANDS, each a whole path segment: at a token
    # start, under the harness's projects directory, under a scratch tempdir,
    # quoted, and in the Windows spelling whose drive letter carries a dash.
    _slugs = (
        "dir -Users-%s-Desktop-x" % _user,
        "~/.claude/projects/-Users-%s-Desktop-x/s.jsonl" % _user,
        "/private/tmp/claude-501/-Users-%s-Desktop-x/s" % _user,
        "/projects/-home-%s-src/s.jsonl" % _user,
        "/projects/-private-tmp-probe/s.jsonl",
        '{"b":"-Users-%s-x"}' % _user,
        "D:\\data\\.claude\\projects\\C--Users-%s-x" % _user,
    )
    _unseen = [line for line in _slugs
               if "session-slug" not in set(h[2] for h in
                                            scan_text("f.md", line, "report"))]
    check("q2c a session slug is found at every placement a real one takes: %r"
          % (_unseen,), _unseen == [])
    # THE ALLOW TWIN q2c's start rule exists for: a kebab word holding the
    # same letters mid-word is prose, and a door refusing it gets routed around.
    _kebab = ("the my-home-page component, the add-Users-list view and "
              "go-home-now")
    _kebab_hits = scan_text("f.md", _kebab, "report")
    check("q2d ALLOW: kebab prose holding -home-<word> and -Users-<word> "
          "mid-word trips nothing: %r" % (_kebab_hits,), _kebab_hits == [])
    # A dash-led word at a token start with nothing after it - an option name,
    # a bare user name in prose - is not a slug either; beside a separator the
    # same lone segment is.
    # Each placement q2f takes has its whitespace-led twin here.
    _lone_u = "-".join(("", "Users", _user))
    _lone_h = "-".join(("", "home", "dir"))
    _proses = (
        "rename %s option, abc %s here" % (_lone_h, _lone_u),
        '{"b":"see %s here"}' % (_lone_u,),
        "set HOME = %s for it" % (_lone_h,),
        "( see %s )" % (_lone_u,),
        "first line\n  %s is an option" % (_lone_h,),
        "the C%s page" % (_lone_u,),
        "an option named `%s`" % (_lone_h,),
    )
    _prose_hits = [(p, scan_text("f.md", p, "report")) for p in _proses
                   if scan_text("f.md", p, "report")]
    check("q2e ALLOW: prose naming a -home-<word> option and a lone "
          "-Users-<name> led by whitespace, at every placement q2f convicts, "
          "trips nothing: %r" % (_prose_hits,), _prose_hits == [])
    _lone = ("/projects/%s" % (_lone_u,), "-home-%s/s.jsonl" % _user,
             '{"b":"%s"}' % (_lone_u,), "HOME=%s" % (_lone_u,),
             "cwd (%s)" % (_lone_u,), "first line\n%s here" % (_lone_u,),
             "dir C-%s here" % (_lone_u,), "path:%s" % (_lone_u,))
    _lone_unseen = [line for line in _lone
                    if "session-slug" not in set(h[2] for h in
                                                 scan_text("f.md", line,
                                                           "report"))]
    check("q2f ...and the same lone segment bounded by a separator, a quote, "
          "a key's `=`, a parenthesis, a line start, a colon or a drive "
          "letter is found: "
          "%r" % (_lone_unseen,), _lone_unseen == [])
    # A file URL may name a host before its path; an https URL with the same
    # host and path names a web page.
    _hosted = scan_text("f.md", "open file://localhost/Users/%s/r.html" % _user,
                        "report")
    _web = scan_text("f.md", "open https://localhost/Users/%s/r.html" % _user,
                     "report")
    check("q2g a file URL naming a host before a home directory is found, and "
          "its https twin with the same host and path trips nothing: %r"
          % ((_hosted, _web),),
          "posix-home" in set(h[2] for h in _hosted) and _web == [])

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

    _run = scan()
    _live, _anchors = _run["rows"], _run["anchors"]
    _kept, _bad = domain_files()
    _surfaces = sorted(set(s for _r, s, _t in _kept))
    # A FILTER THAT NARROWED TO NOTHING MUST NOT READ AS ALL CLEAR. Every case
    # below judges `_live`, and `_live == []` over an empty domain is the silent
    # pass this repository keeps re-finding - so the SET is asserted, not only its
    # verdict, and both surfaces this tree actually has must be in it.
    check("q6 the domain over the live tree is not empty and reaches every "
          "surface this repository commits - the journal, the evidence ledger, "
          "the plan and the rendered reports - so the cases below are judging "
          "something: %d file(s), %r" % (len(_kept), _surfaces),
          _bad == [] and _surfaces == ["evidence", "journal", "plan", "report"])

    check("q7 every committed artifact is clean except what BASELINE accounts "
          "for: %r" % ([render(r) for r in unbaselined(_live, _anchors)],),
          unbaselined(_live, _anchors) == [])
    # The other direction of an exemption table: an entry that matches nothing any
    # more is a claim about a system that has moved on, and a table nobody prunes
    # stops covering what it says it covers.
    _dead = dead_baseline(_live, _anchors)
    check("q8 ...and every BASELINE entry still matches a real finding, so a dead "
          "exemption is reported rather than accumulating: %r" % (_dead,),
          _dead == [])
    _bad = reasonless_baseline()
    check("q9 ...and every BASELINE entry carries a reason a reader can disagree "
          "with, not a label: %r" % (_bad,), _bad == [])

    # BEFORE the cases that print a synthetic row: a missing headline is a
    # KeyError inside `main`, and this is the case that names it rather than a
    # traceback from whichever run met it first.
    check("q31 every synthetic row has both its sentence and its headline - "
          "the run prints the pair, so a name in one table and not the other "
          "is a crash on exactly the run that most needs its explanation: %r"
          % (sorted(set(SYNTHETIC) ^ set(_SYNTHETIC_HEADLINE)),),
          set(SYNTHETIC) == set(_SYNTHETIC_HEADLINE)
          and "plan-index-unparseable" in SYNTHETIC
          and "plan-config-unreadable" in SYNTHETIC)
    _moving_cases(check)
    _plan_problem_cases(check)

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

    # A PHASE CLAIM'S `host`, in both layouts and both spellings. The parse
    # decides and the text only locates, so the allow cases are a claim with no
    # host and a `host` key that is not under a claim at all.
    _cl = {"sessionId": "s", "branch": "b", "at": "t"}
    _shard = json.dumps({"id": "P1", "claim": dict(_cl, host="a-laptop")},
                        indent=2)
    _single = json.dumps({"phases": [{"id": "P1", "claim": dict(_cl, host="x")},
                                     {"id": "P2", "claim": _cl}]}, indent=2)
    _compact = '{"id": "P1",\n "claim": {"sessionId": "s", "host": "x"}}'
    _hostless = json.dumps({"id": "P1", "claim": _cl,
                            "tasks": [{"id": "P1.1", "host": "a-laptop"}]},
                           indent=2)

    def _host_line(text):
        return [n for n, line in enumerate(text.split("\n"), 1)
                if '"host"' in line]
    _got = dict((name, [(r[1], r[2]) for r in scan_text("f.json", text, "plan")])
                for name, text in (("shard", _shard), ("single", _single),
                                   ("compact", _compact),
                                   ("hostless", _hostless)))
    check("q32 a `host` under a phase `claim` in a plan file is a finding at the "
          "line of the key - a shard and a single-file manifest alike, the claim "
          "spread over lines or on one - while a claim with no host, and a "
          "`host` key outside any claim, are clean: %r" % (_got,),
          _got["shard"] == [(_host_line(_shard)[0], "plan-claim-host")]
          and _got["single"] == [(_host_line(_single)[0], "plan-claim-host")]
          and _got["compact"] == [(2, "plan-claim-host")]
          and _got["hostless"] == []
          and [r[2] for r in scan_text("f.json", _shard, "report")] == [])

    check("q11 a journal file's WRITER ID is checked too - it is the one field "
          "with no repair path, because `genesis_prev` seeds the chain from these "
          "bytes and a name committed there can never be corrected",
          writer_id_problem("2026-08.3f33caa7-c0c9-4a4e-9c3b.jsonl") is None
          and writer_id_problem("2026-08.a1b2c3d4e5f60718.jsonl") is None
          and writer_id_problem("2026-08.writer-48645.jsonl") is None
          and writer_id_problem("2026-08.MacBook-Pro.local-48645.jsonl")
          is not None
          and writer_id_problem("2026-08.jsonl") is not None)
    check("q11b ...and a LINKED WORKTREE's writer id - a minted shape followed by "
          "the `.wt-<8 hex>` key `_journal_io.worktree_key` appends - is one of "
          "those shapes, while the suffix alone, or a name in its place, is not",
          writer_id_problem("2026-09.24c1c300-045e-45b9-beaf.wt-09806857.jsonl")
          is None
          and writer_id_problem("2026-09.a1b2c3d4e5f60718.wt-09806857.jsonl")
          is None
          and writer_id_problem("2026-09.wt-09806857.jsonl") is not None
          and writer_id_problem("2026-09.3f33caa7-c0c9-4a4e-9c3b.wt-laptop.jsonl")
          is not None)

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
    # -- the vocabulary offered to a caller, the other half of this file --
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
    bad = unbaselined(live, run["anchors"]) if run["baselined"] else list(live)
    dead = dead_baseline(live, run["anchors"]) if run["baselined"] else []
    for row in bad:
        sys.stdout.write("FOUND %s\n" % render(row))
    for key in dead:
        sys.stdout.write("DEAD BASELINE %s:%s:%s - it matches nothing any more, so "
                         "the exemption is describing a system that has moved on\n"
                         % key)
    if bad or dead:
        for name in sorted(set(r[2] for r in bad) & set(SYNTHETIC)):
            sys.stdout.write("\n%s (%s): %s\n"
                             % (_SYNTHETIC_HEADLINE[name], name, SYNTHETIC[name]))
        sys.stdout.write("\nA committed artifact carries machine identity, an "
                         "exemption has gone stale, or nothing was checked. The "
                         "matched text is deliberately not printed - open the "
                         "file at the line named above.\n")
        return 1
    sys.stdout.write(ok_line(run) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
