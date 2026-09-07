#!/usr/bin/env python3
"""
Where a phase's branch comes from and what it is called — stdlib only.

Two questions the orchestrator asks per phase, whose answers used to be one
hard-coded shape each:

    parent branch   phase.parentBranch ?? meta.developmentBranch ?? "main"
    branch name     meta.branch.template, or the meta.branchPrefix shape

Both are implemented HERE rather than in prose, and that is the whole point of the
module. `reference/orchestrator.md` used to say "compose the branch name:
`<prefix>/<phaseId-lowercase>-<slug>`", which a reader can follow because the shape
is fixed. A TEMPLATE cannot be followed that way: `{type}/{initials}/{phase}-{slug}`
has to collapse an empty `{initials}` TOGETHER WITH the separator behind it, or it
yields `feature//p2-…`, which git rejects — and a rule with a case like that is a
rule that needs cases, not sentences.

`meta.branchPrefix` keeps working and keeps producing byte-identical names. It is
not deprecated here: an existing manifest that carries it must not change meaning
by upgrading, so `config()` reports WHICH shape it used (`basis`) and every caller
that prints a branch name can say so.

Every function returns the basis alongside the value — a branch whose type was
decided three levels away is otherwise a branch nobody can explain. That is the
house rule about a claim carrying what makes it true, applied to a name.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__branch.py`.
"""
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

# The conventional set, in the order a reader of the convention meets them. The
# list is ALSO what the orchestrator's pre-approved git globs are derived from
# (`approved_globs`), so adding a type here is what makes it usable without a
# permission prompt on every branch operation.
DEFAULT_TYPES = ("feature", "bugfix", "hotfix", "release", "docs", "refactor",
                 "test", "chore")

TYPE_HELP = {
    "feature": "new capability",
    "bugfix": "a defect in delivered work",
    "hotfix": "urgent fix against a released line",
    "release": "preparing a release",
    "docs": "documentation only",
    "refactor": "restructuring with no behaviour change",
    "test": "adding or improving tests",
    "chore": "maintenance, tooling, dependencies",
}

DEFAULT_TEMPLATE = "{type}/{initials}/{phase}-{slug}"
DEFAULT_TYPE = "feature"
DEFAULT_PREFIX = "audit"
DEFAULT_SLUG_MAX = 30
DEFAULT_PARENT = "main"

_PLACEHOLDER = re.compile(r"(\{[a-zA-Z]+\})")
PLACEHOLDERS = ("type", "initials", "phase", "slug")


# --- config -------------------------------------------------------------------

def config(meta):
    """The effective naming convention, and which key decided it.

    `basis` is not decoration: `meta.branchPrefix` and `meta.branch` produce
    different names from the same manifest, and a reader looking at a branch has
    no way to tell which one was in force.
    """
    meta = meta or {}
    blk = meta.get("branch")
    if isinstance(blk, dict) and blk:
        types = blk.get("types")
        if not isinstance(types, list) or not types:
            types = list(DEFAULT_TYPES)
        return {
            "template": blk.get("template") or DEFAULT_TEMPLATE,
            "defaultType": blk.get("defaultType") or DEFAULT_TYPE,
            "types": [str(t) for t in types],
            "initials": blk.get("initials"),
            "slugMaxLength": blk.get("slugMaxLength") or DEFAULT_SLUG_MAX,
            "basis": "meta.branch",
        }
    # The pre-0.44 shape. Reproduced as a template so there is ONE expansion path
    # rather than two that must be kept agreeing.
    prefix = meta.get("branchPrefix") or DEFAULT_PREFIX
    return {
        "template": "%s/{phase}-{slug}" % prefix,
        "defaultType": DEFAULT_TYPE,
        "types": list(DEFAULT_TYPES),
        "initials": None,
        "slugMaxLength": DEFAULT_SLUG_MAX,
        "basis": ("meta.branchPrefix" if meta.get("branchPrefix")
                  else "default (no meta.branch, no meta.branchPrefix)"),
    }


# --- pieces -------------------------------------------------------------------

def slugify(title, max_len=DEFAULT_SLUG_MAX):
    """phase.title -> the `{slug}` segment. Empty in, empty out — the caller
    collapses it rather than substituting a placeholder word."""
    s = str(title or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if max_len and len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s


def initials_from(name):
    """A git identity -> initials, or "" when it yields none.

    Deliberately conservative: an identity that does not initial usefully returns
    nothing, and the placeholder collapses. Guessing here would put a wrong
    person's mark on a branch, which is worse than no mark.
    """
    words = [w for w in re.split(r"[^A-Za-z]+", str(name or "")) if w]
    if not words:
        return ""
    if len(words) == 1:
        # A one-word identity is usually CamelCase ("AleksandarBisevac"), and a
        # single letter identifies nobody. Split on the capitals; if there are
        # none to split on, take the first two letters rather than one.
        parts = re.findall(r"[A-Z][a-z]*|[a-z]+", words[0])
        if len(parts) > 1:
            return "".join(p[0].lower() for p in parts[:3])
        return words[0][:2].lower()
    return "".join(w[0].lower() for w in words[:3])


def resolve_type(meta, phase, from_bug=False):
    """{type} for this phase, with the basis that chose it."""
    cfg = config(meta)
    explicit = (phase or {}).get("branchType")
    if explicit:
        return {"type": str(explicit), "basis": "phase.branchType",
                "known": str(explicit) in cfg["types"]}
    if from_bug:
        return {"type": "bugfix", "basis": "derived (bugs[] origin)",
                "known": "bugfix" in cfg["types"]}
    return {"type": cfg["defaultType"], "basis": "meta.branch.defaultType",
            "known": cfg["defaultType"] in cfg["types"]}


def parent_branch(meta, phase):
    """Which branch this phase forks from and merges back into.

    Same precedence chain `_areas.resolve_review_skill` uses, and the same reason
    for returning the basis: a phase that merged somewhere other than the
    development branch has NOT reached it, and the sign-off report has to say so
    rather than let silence read as "landed".
    """
    meta = meta or {}
    own = (phase or {}).get("parentBranch")
    dev = meta.get("developmentBranch") or DEFAULT_PARENT
    if own:
        return {"branch": str(own), "basis": "phase.parentBranch",
                "is_development": str(own) == dev}
    return {"branch": dev,
            "basis": ("meta.developmentBranch" if meta.get("developmentBranch")
                      else "default 'main'"),
            "is_development": True}


# --- merge policy ---------------------------------------------------------------

# What happens once a phase's tasks are all done. Three switches, all ON by default,
# because that is the behaviour `reference/orchestrator.md` already describes as the
# normal path -- turning one off is the deliberate act, not turning it on.
MERGE_KEYS = ("auto", "removeWorktree", "deleteBranch")
DEFAULT_MERGE = {"auto": True, "removeWorktree": True, "deleteBranch": True}


def merge_policy(meta):
    """What sign-off does after the tasks are done, and which key decided each half.

    IT LIVES BESIDE `parent_branch` AND NOT IN THE CONFIG FILE, and that is the whole
    placement argument. `.claude/audit.config.json` has exactly one git key
    (`gitRoot`); the merge TARGET is already `meta.developmentBranch` and the branch
    NAME is already `meta.branch`. A policy about what happens after that merge,
    stored in the other file, would create a second home for branch decisions and the
    "which one wins" question `COMPATIBILITY.md` treats as a major release.

    ABSENT READS AS ON, per key rather than per block. A manifest carrying
    `{"auto": false}` still removes the worktree and deletes the branch when the
    human merges by hand -- the three answer different questions and a half-written
    block must not silently switch off the two it does not mention. It is also the
    grammar the panel already speaks: agreeing with the default DELETES the key, so a
    round trip through the form leaves the file as it found it.

    `auto: false` IS THE HUMAN-IN-THE-LOOP SWITCH. It does not make sign-off fail; it
    makes it stop before the merge and print the command it would have run. A phase
    that is reviewed, gated and committed but not merged is a real and reasonable
    state on a team that lands work through a pull request, and the plugin had no way
    to say it.

    Every value carries the key that produced it for `config()`'s reason: a run that
    deleted somebody's branch owes an answer to "who asked for that", and `default`
    is a different answer from `meta.merge.deleteBranch`.
    """
    meta = meta or {}
    blk = meta.get("merge")
    out = {}
    for key in MERGE_KEYS:
        if isinstance(blk, dict) and key in blk:
            out[key] = bool(blk[key])
            out[key + "Basis"] = "meta.merge.%s" % (key,)
        else:
            out[key] = DEFAULT_MERGE[key]
            out[key + "Basis"] = "default (absent reads as on)"
    return out


# --- expansion ----------------------------------------------------------------

def expand(template, values):
    """Substitute placeholders, collapsing an empty one WITH its separator.

    The separator behind an empty placeholder goes with it; when the empty
    placeholder is last, the separator in front of it goes instead. Without this
    an absent `{initials}` yields `feature//p2-x`, which git rejects.
    """
    toks = [t for t in _PLACEHOLDER.split(str(template or "")) if t != ""]
    out = []
    i = 0
    n = len(toks)
    while i < n:
        tok = toks[i]
        if tok.startswith("{") and tok.endswith("}"):
            val = str(values.get(tok[1:-1], "") or "").strip()
            if val:
                out.append(val)
            elif i + 1 < n and not toks[i + 1].startswith("{"):
                i += 1                       # swallow the separator behind it
            elif out:
                out.pop()                    # last placeholder: the one in front
        else:
            out.append(tok)
        i += 1
    return "".join(out)


def compose(meta, phase, initials=None, from_bug=False):
    """The phase's branch name, plus everything needed to explain it."""
    cfg = config(meta)
    kind = resolve_type(meta, phase, from_bug=from_bug)
    ini = cfg["initials"]
    if ini is None:
        ini = initials_from(initials)
    values = {
        "type": kind["type"],
        "initials": str(ini or ""),
        "phase": str((phase or {}).get("id") or "").lower(),
        "slug": slugify((phase or {}).get("title"), cfg["slugMaxLength"]),
    }
    name = expand(cfg["template"], values)
    return {
        "name": name,
        "basis": cfg["basis"],
        "type": kind["type"],
        "typeBasis": kind["basis"],
        "violations": ref_violations(name),
        "unknownType": not kind["known"],
    }


# --- git ref legality ---------------------------------------------------------

_BAD_CHARS = " ~^:?*[\\"


def ref_violations(name):
    """Why `name` is not a legal git branch, in the reader's words.

    Not a full `git check-ref-format` port — the subset a template can produce.
    It reports a LIST because a bad template usually breaks more than one rule,
    and fixing them one round-trip at a time is the cost of reporting just the
    first.
    """
    out = []
    s = str(name or "")
    if not s:
        out.append("empty")
        return out
    if s.startswith("/") or s.endswith("/"):
        out.append("begins or ends with '/'")
    if "//" in s:
        out.append("contains '//' (an empty path component)")
    if ".." in s:
        out.append("contains '..'")
    if "@{" in s:
        out.append("contains '@{'")
    if s == "@":
        out.append("is the single character '@'")
    if s.endswith("."):
        out.append("ends with '.'")
    if s.endswith(".lock"):
        out.append("ends with '.lock'")
    bad = sorted(set(c for c in s if c in _BAD_CHARS or ord(c) < 32 or ord(c) == 127))
    if bad:
        out.append("contains %s" % ", ".join(
            ("a space" if c == " " else "control character %d" % ord(c))
            if (c == " " or ord(c) < 32 or ord(c) == 127) else "'%s'" % c
            for c in bad))
    for comp in s.split("/"):
        if comp.startswith("."):
            out.append("path component %r begins with '.'" % comp)
            break
    return out


# --- the orchestrator's pre-approved globs ------------------------------------

def approved_globs(meta):
    """The `<type>/*` patterns branch operations may run unconfirmed.

    `reference/orchestrator.md` pre-approves `git switch -c` and `git switch` for
    these — PHASE ENTRY, which is the only branch operation the orchestrator still
    composes itself. Merging, deleting and every worktree verb moved into
    `close-phase.py` and `manage-worktrees.py`, and are approved as the script calls
    they now are; this list stopped covering them and says so rather than carrying
    half its verbs as decoration.

    Derived rather than written down because the failure mode of a stale list is a
    permission prompt on every branch operation — loud, but confusing enough to be
    blamed on the harness rather than on the config.
    """
    cfg = config(meta)
    if cfg["basis"] == "meta.branch":
        return ["%s/*" % t for t in cfg["types"]]
    return ["%s/*" % (cfg["template"].split("/", 1)[0],)]


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_branch.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__branch.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
