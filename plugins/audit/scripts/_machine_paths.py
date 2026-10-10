#!/usr/bin/env python3
"""
What counts as machine identity in a string, and how to take it out - stdlib only.

WHY THIS IS NOT IN `_journal_io`. The journal, the evidence ledger and the plan
are all committed, and a string any of them writes can carry the author's home
directory or the checkout's root. The plan's writer (`_manifest_io`) and the
journal's (`_journal_io`) sit in the same layer and may not import each other,
so the detector and the redaction they share lived in the one of them that could
not be reached from the other. A lower module both import is the only shape in
which "every save passes through one scrub" holds for the plan too.

One fact, one home: the shapes `tools/check-committed-pii.py` flags, the
refusal at a verb's door, and the redaction of the plugin's own text are all
this file's patterns. `_journal_io` re-exports the names its callers use.

The cases for this file live in `plugins/audit/tests/test__machine_paths.py`.
Exit codes (as a command): 0 selftest pointer printed - 2 usage error.
"""

import json
import os
import re
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()


OUTSIDE_TOKEN = "<outside-repo>"


def canonical(obj):
    """One spelling per value, so two machines hash the same row identically."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# --- resolving a path against the repo -----------------------------------------
def repo_relative_or_token(project, path):
    """`path` as a repo-relative posix path, `"."` at the root, else `OUTSIDE_TOKEN`.

    DELIBERATELY NOT `hooks/_config.within_root()`, which asks the same question and
    documents the OPPOSITE failure direction: it answers True for input it cannot
    resolve, because for a gate "I could not tell" must leave the gate where it
    already was. Here that same answer would write a raw home directory into a
    committed file, so every unresolvable, empty or outside case lands on the token.
    Same question, opposite failure direction, on purpose -- this is a note against
    somebody later noticing the resemblance and deduplicating the two back together.

    NEVER `os.path.relpath` HERE: this function takes a path from anywhere - a
    payload, a config, another drive - and across Windows drives `relpath` RAISES,
    so a redactor built on it hands its caller an exception where a token was
    wanted. A prefix comparison over resolved absolute paths has no such edge.

    SCOPED TO THIS FUNCTION, and it did not used to be. Written as a flat "never",
    it read as a rule about the module and was already false one function over:
    `verify_dir` derives a journal-relative `where` with `relpath`, legitimately,
    because both sides come from one directory walk and cannot be on two drives.
    A rule stated wider than it holds is the kind a later reader either obeys
    where it costs something or disbelieves where it matters.

    Case is compared EXACTLY, which is the other place the direction shows: on a
    case-insensitive volume a differently-spelled inside path is called outside and
    the row loses information, where a case-insensitive compare would have to slice
    the root off a path it only approximately matched.
    """
    if not project or not isinstance(path, str):
        # A NON-STRING IS THE TOKEN, and this is not defensive typing. `_clip`
        # spells a list or a dict canonically, so a redactor that accepted one
        # would be handed `["/Users/..."]` -- a string that is not absolute, which
        # joins onto the repo root and comes back looking repo-relative with the
        # home directory still inside it. The type is the only thing that tells
        # those apart, and only before something stringifies it.
        return OUTSIDE_TOKEN
    try:
        root = os.path.realpath(str(project))
        raw = path.replace("\\", "/")
        if not raw:
            return OUTSIDE_TOKEN
        joined = raw if os.path.isabs(raw) else os.path.join(root, raw)
        full = os.path.realpath(joined)
        spelled = _spelled_under(project, root, joined, full)
    except Exception:
        return OUTSIDE_TOKEN
    root = root.rstrip(os.sep) or root
    if full == root:
        return "."
    if not full.startswith(root + os.sep):
        return OUTSIDE_TOKEN
    if spelled:
        return spelled
    return full[len(root) + 1:].replace(os.sep, "/")


def _spelled_under(project, real_root, joined, full):
    """`joined` relative to the root as the writer SPELLED it, or None.

    INSIDE OR OUTSIDE IS THE REALPATH'S ANSWER, and the caller asks it; this
    only chooses the spelling of a path already known to be inside. A path
    through a symlinked directory resolves to the link's target, and handing
    that back would record a file the writer never named - so when the
    normalised spelling sits under either spelling of the root, and still
    resolves to the same file, it is the one kept. The resolve check is what
    keeps a lexical `..` collapse past a symlink from naming a different file."""
    norm = os.path.normpath(os.path.abspath(joined))
    for root in (os.path.abspath(str(project)), real_root):
        root = root.rstrip(os.sep) or root
        if norm.startswith(root + os.sep) and os.path.realpath(norm) == full:
            return norm[len(root) + 1:].replace(os.sep, "/")
    return None


# A path token INSIDE a line of free-form program output, and deliberately WIDER
# than `run-test-gate._PATHISH`, which harvests paths out of the same text for a
# different purpose. That one may under-match harmlessly - a path it misses only
# costs an overlap nobody counted - and this one may not: a token it misses is a
# home directory published permanently in a committed, hash-chained row. So it
# fires on any run of path characters carrying a separator in EITHER spelling,
# which is what reaches a drive-letter path and a `~/work/...` one; `_PATHISH`
# can see neither, because it requires a literal `/` and excludes both `~` and
# `:`.
#
# A LONE SEPARATOR IS NOT A PATH. One side of the separator must carry at least
# one path character, so the `/` in `1 / 2` is left alone - an arithmetic slash
# rewritten to the outside token is the kind of over-firing that gets a redactor
# read as broken rather than as careful.
_TEXT_PATH = re.compile(r"[~A-Za-z0-9_.@$:+-]+[/\\][~A-Za-z0-9_.@$:+\\/-]*"
                        r"|[/\\][~A-Za-z0-9_.@$:+\\/-]+")
# Spellings a repo-relative path never has, and which `repo_relative_or_token`
# would resolve as one anyway. It asks `os.path.isabs`, which on posix answers
# False for a drive-letter path, for a `~`-prefixed one and for a UNC share - so
# each would be JOINED onto the repo root and handed back looking local with the
# machine name still inside it. Measured, not argued: before this line a
# `C:\\Users\\...` token came back as `C:/Users/...` and a `~/work/...` token came
# back unchanged, and both are what `tools/check-committed-pii.py` detects.
#
# JUDGED HERE AND NOT THERE, because the two functions take input from different
# places: `repo_relative_or_token`'s callers hand it paths git and this plugin
# produced, and this one's arrive from a runner's stdout, where every spelling on
# every platform is reachable.
_NOT_RELATIVE = re.compile(r"^(?:~|[A-Za-z]:[/\\]|[/\\]{2})")


def redacted_paths(project, text):
    """Every path token in one piece of program output, redacted. NOT bounded.

    THE RULE WITHOUT THE BOUND, because the bound is the caller's and the rule
    is not. `redacted_text` below holds a journal value to a value's budget; the
    evidence ledger's basis sentences carry no such budget and never did, so
    clipping one to make it redactable would have been this function's cut
    imposed on a field it does not own. Splitting the two is what stopped the
    second reader copying the substitution instead - one grammar, one token
    table, two budgets.
    """
    body = text if isinstance(text, str) else str(text or "")

    def _token(match):
        raw = match.group(0)
        if _NOT_RELATIVE.match(raw):
            return OUTSIDE_TOKEN
        return repo_relative_or_token(project, raw)

    return _TEXT_PATH.sub(_token, body)


# --- the shapes -----------------------------------------------------------------
# THE SHAPES THAT ARE MACHINE IDENTITY, defined once and read twice: here, to
# refuse a caller's value and redact the plugin's own before either is hashed,
# and by `tools/check-committed-pii.py`, whose `DETECTORS` takes these very
# pattern objects for its rows of the same names. A writer that judged one
# spelling while the detector flagged another would let through exactly the row
# the detector then reports, too late, so the agreement is held by identity
# rather than by a comment - and `ft7` in `test__journal_io.py` is the case that
# fails when either side grows a copy.
#
# The token boundary is what keeps `docs/home/alice.md` and `src/users/x.ts`,
# repo-relative paths that merely resemble a home directory, out of the set. The
# leading separator is optional IN THE PATTERN because the detector reads
# committed bytes, where a producer that trimmed it still left a home directory
# behind and a human reviews what it flags. The writer reads the same pattern
# and additionally requires that separator (`machine_path_shape`): a repository
# may hold a `home/` directory of its own, and a writer that refused
# `home/<x>` would refuse that repository's own paths with nobody to overrule it.
# A character that may sit INSIDE a path token, so one standing before a
# match means the match does not start a token. One class, two readers: the
# lookbehind below, and the checkout-root search, which uses `str.find` and so
# asks the character before the root with `_TOKEN_CHAR`.
#
# A TOKEN ALSO STARTS RIGHT AFTER A URL SCHEME'S `://`. The character before
# the path of a `file:///` URL is a separator, which on its own reads as the
# middle of a path, so a file URL into a home directory used to pass both the
# writer and the detector. An `https://host/Users/x` still does not fire: the
# word there follows the host, not the scheme.
#
# FOR THE FILE SCHEME ONLY, A TOKEN ALSO STARTS AFTER `file://<host>`, and the
# host is part of the match. A file URL's host names the machine whose disk the
# path is on, so `file://localhost/Users/x` is the same home directory as
# `file:///Users/x`; an https host names a web server, whose path is a page.
#
# THE SHAPES AFTER THE HOME-DIRECTORY PAIR WERE THE DETECTOR'S ALONE, and the
# writer let each through to a hash-chained row the detector then flagged when
# nothing could change it. They sit here now for the same reason that pair does.
_TOKEN_CLASS = r"[A-Za-z0-9._~$+/\\-]"
MACHINE_PATH_TOKEN_START = (r"(?:(?<!%s)|(?<=://)|(?i:(?<=file://))"
                            r"[A-Za-z0-9.-]+(?=[/\\]))" % (_TOKEN_CLASS,))
# A slug's start: `_TOKEN_CLASS` without the separators, because a slug is
# itself a segment and so follows one.
_SLUG_START = r"(?<![A-Za-z0-9._~$+-])"
# What follows a slug's user segment for it to be a slug: another segment, or
# a separator closing it as a path segment. Without one of the two, a dash-led
# word at a token start - an option named `-home-<word>`, a `-Users-<name>` in
# prose - matched, and the writer replaced a whole sentence for it.
_SLUG_USER = r"-(?:Users|home)-[A-Za-z0-9._]+"
# Where a LONE user segment still names a home: led by the start of the text
# or of a line, a separator, a quote, a key's `=` or `:`, or a parenthesis -
# the places a value stands rather than a word in a sentence. Whitespace and a
# backtick are left out, so `-home-dir` in prose or a code span is no slug.
_SLUG_LONE_LEAD = r"(?<![^\n/\\\"'=:(])"
_MACHINE_PATH_SHAPES = (
    ("posix-home", re.compile(MACHINE_PATH_TOKEN_START
                              + r"[/\\]?(?:Users|home)/[A-Za-z0-9._-]+")),
    ("windows-user-path", re.compile(
        r"[A-Za-z]:\\{1,2}Users\\|\\{2,4}[A-Za-z0-9._-]+\\{1,2}[A-Za-z0-9._$-]+\\")),
    # A home directory flattened into one directory NAME, the way the
    # harness names a project's scratch and session directories. The slug is
    # a whole path segment, so its leading dash stands at a token start - or
    # behind a drive letter's own dash, the Windows spelling - and a kebab
    # word holding `-home-` mid-word is prose, not a slug. A real slug
    # carries more than the user segment, or stands where a value does; the
    # lone segment is taken after a drive letter's dash, before a separator,
    # or behind `_SLUG_LONE_LEAD`, and never behind whitespace alone.
    ("session-slug", re.compile(
        _SLUG_START + r"(?:[A-Za-z]-)?" + _SLUG_USER
        + r"(?:-[A-Za-z0-9._]|(?=[/\\]))"
        r"|" + _SLUG_START + r"[A-Za-z]-" + _SLUG_USER
        + r"|" + _SLUG_LONE_LEAD + r"(?:[A-Za-z]-)?" + _SLUG_USER
        + r"|" + _SLUG_START + r"-private-tmp-")),
    ("escaped-path", re.compile(r"%2F(?:Users|home)%2F|%5CUsers%5C", re.I)),
    ("tempdir-session", re.compile(
        MACHINE_PATH_TOKEN_START + r"/?(?:private/)?tmp/claude-\d+"
        r"|" + MACHINE_PATH_TOKEN_START + r"/?var/folders/[A-Za-z0-9_+]{2,}"
        r"|\\Temp\\claude-", re.I)),
    # Refused at the writer's door even in prose such as `use ~/.config`, by
    # choice: the commit-time detector reads this same pattern and fails the
    # build on it, so a row the writer let through would be one the build then
    # rejects after its hash chain made it permanent.
    ("unexpanded-home", re.compile(r"(?:^|[\s\"'=:(\[,])~/")),
)
# THE PUBLIC NAME IS THE DETECTOR'S, and nothing in this module reads it. A row
# never carries these patterns - a refusal or a redaction is what they produce -
# so they are not row shape for `audit-journal.py` to re-export, and the
# functions here read the private name `test__journal_io.py`'s re-export walk
# leaves out for that reason.
MACHINE_PATH_SHAPES = _MACHINE_PATH_SHAPES
_TOKEN_CHAR = re.compile(_TOKEN_CLASS)
# A `posix-home` match the writer takes: its home word stands behind a
# separator, which a match missing its leading one does not have.
_HOME_AFTER_SEPARATOR = re.compile(r"[/\\](?:Users|home)/")
# The shape name a refusal gives for the checkout's own root, which is machine
# layout whatever directory it sits under and so has no pattern of its own.
_CHECKOUT_ROOT_SHAPE = "checkout-root"
# An ABSOLUTE path token in a sentence, and only those: a relative spelling is
# already what a row may say and is left byte for byte. The lookbehind lets `=`
# and `:` stand before the separator, so `X=/abs/...` and a `scheme://` are
# reached, and keeps a separator in the middle of a word from starting a token.
_ABS_TOKEN = re.compile(r"(?<![A-Za-z0-9_.@$+~/\\-])"
                        r"(?:[A-Za-z]:)?[/\\][~A-Za-z0-9_.@$:+\\/-]+")


def _checkout_roots(project):
    """Every spelling of `project`'s root a value could carry, posix-separated.

    Both the given and the resolved one: a temp root reached through a symlink
    is spelled one way by the caller and the other way by `realpath`. A root that
    is the filesystem root itself is no spelling at all - every absolute path
    starts with it - so it is left out rather than refusing everything."""
    if not project:
        return ()
    spellings = set()
    for way in (os.path.abspath, os.path.realpath):
        try:
            root = way(str(project)).replace("\\", "/").rstrip("/")
        except Exception:
            continue
        if root and "/" in root:
            spellings.add(root)
    return tuple(sorted(spellings, key=len, reverse=True))


def _in_repo_relative(project, text):
    """`text` with every absolute token INSIDE the repo spelled repo-relative.

    `repo_relative_or_token` under each absolute token, the same map
    `redacted_paths` uses - but an outside token is left as it stands rather than
    collapsed to `OUTSIDE_TOKEN`: whether it may be stored is the shape check's
    question, and a token that names no machine (a URL, `/usr/bin`) says what
    its writer meant."""
    if not project:
        return text

    def _token(match):
        raw = match.group(0)
        # Absolute on THIS platform, or `repo_relative_or_token` joins it onto
        # the root: a drive-letter path on posix would come back looking local
        # with the user directory still inside it, which `_NOT_RELATIVE`'s note
        # measured. Left alone, it reaches the shape check as it was written.
        if not os.path.isabs(raw):
            return raw
        rel = repo_relative_or_token(project, raw)
        return raw if rel == OUTSIDE_TOKEN else rel

    return _ABS_TOKEN.sub(_token, text)


def _root_at(flat, root):
    """Does `root` stand in `flat` as a whole token - a token start before it
    and a path boundary after it?

    BOTH ENDS, and the leading one is not decoration. A checkout rooted at a
    short path - a container's `/src`, `/app`, `/repo` - is a segment a
    relative path or a URL carries too: `lib/src/foo.ts`, a link's
    `example.com/src/x`. Asked only at its end, the root matched inside both
    and a caller's ordinary sentence was refused as machine layout."""
    at = flat.find(root)
    while at != -1:
        end = at + len(root)
        starts = (at == 0 or not _TOKEN_CHAR.match(flat[at - 1])
                  or flat[:at].endswith("://"))
        ends = end == len(flat) or not re.match(r"[A-Za-z0-9._-]", flat[end])
        if starts and ends:
            return True
        at = flat.find(root, at + 1)
    return False


def _shape_fires(name, match):
    """Whether one pattern match is machine identity TO THE WRITER.

    `posix-home` fires only on a match carrying a separator before its home
    word - first in the match, or after a file URL's host; the detector reads
    the same pattern without that condition - the section's note above
    `_MACHINE_PATH_SHAPES` says why the two differ."""
    if name == "posix-home":
        return _HOME_AFTER_SEPARATOR.search(match.group(0)) is not None
    return True


def machine_path_shape(text, roots=()):
    """The name of the first machine-identity shape `text` carries, else None.

    The writer's answer, which every check and redaction here reads. The
    checkout's root is asked first, so a root that also sits under a home
    directory is named for what it is rather than for where it happens to be."""
    flat = text.replace("\\", "/")
    for root in roots:
        if _root_at(flat, root):
            return _CHECKOUT_ROOT_SHAPE
    for name, pattern in _MACHINE_PATH_SHAPES:
        if any(_shape_fires(name, m) for m in pattern.finditer(text)):
            return name
    return None


def _judged_text(value):
    """`value` as the text a check or a redaction reads, or None for a value
    that carries no text at all.

    Structured values are judged in the canonical spelling `_clip` would store;
    a non-string scalar carries no path; an unspellable value is one `_clip`
    stores nothing for, so there is nothing to judge either."""
    if value is None or isinstance(value, (bool, int, float)):
        return None
    if isinstance(value, str):
        return value
    try:
        return canonical(value)
    except Exception:
        return None


def redacted_free_text(project, value, roots=None):
    """`value` as a row may say it: in-repo absolute paths spelled
    repo-relative, every token still carrying machine identity replaced by
    `OUTSIDE_TOKEN`. NEVER raises, and never refuses.

    FOR TEXT THE PLUGIN BUILT ITSELF - a hook's rendered change, a verdict
    sentence, git's refusal quoted in a withdrawal - and for every row value,
    because `_normalise` cannot tell whose text it holds. A caller's text has
    already met `check_free_text` at the verb's door; this is what keeps the
    rest from costing a writer its own row, which is what refusing it here did.

    TOKEN BY TOKEN, over `_TEXT_PATH`'s grammar, so only the path is replaced
    and the sentence around it survives; a URL or a repo-relative path names no
    machine and is left byte for byte, unlike `redacted_text`, whose program
    output collapses every outside path. If the result still carries a shape -
    a spelling the token grammar split differently from the shape - the WHOLE
    value becomes `OUTSIDE_TOKEN`: failing toward the constant is
    `program_token`'s direction, and a second marker would be one more word of
    row vocabulary for every reader to learn."""
    text = _judged_text(value)
    if text is None:
        return value
    if not may_hold_path(text):
        return text
    if roots is None:
        roots = _checkout_roots(project)
    text = _in_repo_relative(project, text)

    def _token(match):
        raw = match.group(0)
        return OUTSIDE_TOKEN if machine_path_shape(raw, roots) else raw

    out = _TEXT_PATH.sub(_token, text)
    if machine_path_shape(out, roots):
        return OUTSIDE_TOKEN
    return out


def scrubbed_values(project, value, roots=None, seen=None, keep=()):
    """`value` with every string in it run through `redacted_free_text`; a NEW
    structure, the argument untouched. Dict keys, numbers and booleans stay.

    THE SAVE BOUNDARY'S SCRUB, for a record whose fields the plugin composed
    from places no caller reviewed - a red helper's sandbox description, a
    runner's stderr. It is the existing redaction applied to every string, so
    there is no second detector to drift from the first. One call shares its
    roots and a memo (`seen`) across the whole walk: a shard repeats the same
    sentences many times, and the redaction is a pure function of the string.

    THE RULE FOR WHAT IT MUST NOT TOUCH: a value some reader compares back to
    another record, or resolves as a key, an id or a path, is not free text.
    Rewriting it makes the row stop matching the thing it was copied from. A
    caller names such a field in `keep` (the dict KEY whose value passes
    through, at any depth); the name is the caller's, because only the caller
    knows which of its fields a reader compares. A kept value is a copy of
    something that was itself saved through this scrub - the plan's own
    command - so it adds no machine path the plan did not already refuse.
    """
    if roots is None:
        roots = _checkout_roots(project)
    if seen is None:
        seen = {}
    if isinstance(value, str):
        if value not in seen:
            seen[value] = redacted_free_text(project, value, roots)
        return seen[value]
    if isinstance(value, dict):
        return dict((k, v if k in keep
                     else scrubbed_values(project, v, roots, seen, keep))
                    for k, v in value.items())
    if isinstance(value, list):
        return [scrubbed_values(project, v, roots, seen, keep) for v in value]
    return value


# --- the cheap pre-reject --------------------------------------------------------
# A STRING THAT CARRIES NONE OF THESE CANNOT HOLD A MACHINE PATH, and the claim is
# derived from the patterns above rather than assumed: every shape needs a
# separator (`/` or `\\`) or the escape `%` (`escaped-path`), except the
# `session-slug`, whose user segment is dash-joined - so the slug's own two
# literals are named here. The checkout root and `_TEXT_PATH` need a separator
# too. Prose, ids and hashes are most of a plan's strings and skip the regexes.
# `test__machine_paths.py` runs every shape sample and a corpus of real shards
# through this and the full path and fails when they disagree.
_MAY_HOLD_PATH = re.compile(r"[/\\%]|-(?:Users|home)-|-private-tmp-")


def may_hold_path(text):
    """False only when `text` provably names no machine path."""
    return _MAY_HOLD_PATH.search(text) is not None


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        print("_machine_paths.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__machine_paths.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
